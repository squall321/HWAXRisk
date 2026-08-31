# 과제 성격 프로파일을 씨앗(seed)→패널(panel)→확정(confirmed) 3층으로 합성하고 승격시킨다 — plan §4.6.3·§4.6.4
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app import narrative
from app.common import new_uuid, now_epoch, parse_ref, sha256_hex
from app.errors import AppError
from app.registry import CHARACTER_STATUS_ORDER, FACET_ORDER
from app.risk_store import RiskStore

# ---------------------------------------------------------------- 상수(plan §4.6.3·§4.6.4)

# 씨앗 축 → facet(plan §4.6.4 1 의 매핑표). char:philosophy 는 좌석 전용이라 씨앗으로 오지 않는다.
AXIS_FACET: dict[str, str] = {
    "char:structure": "intent",
    "char:interface": "vulnerability",
    "char:tolerance": "constraint",
    "char:maturity": "unknown",
    "char:analysis": "unknown",
    "char:constraint": "constraint",
    "char:change_style": "lineage",
}
DEFAULT_FACET = "unknown"

# 씨앗이 이 태그를 내면 facet unknown 에 코드 진술 1건을 더한다(plan §3.2.4 char:analysis 행).
SOURCE_ABSENT_SEEDS: tuple[str, ...] = ("char:analysis:sim_only", "char:analysis:ecad_only")
SOURCE_ABSENT_TEXT = "[원천 부재] mcad 소스가 없어 형상·계면 축은 미판정"

# 프로파일 정렬에 쓰는 근거 등급 순서(plan §4.6.4 마지막 문단 — confidence 는 쓰지 않는다).
GRADE_RANK: dict[str, int] = {"경험칙": 1, "도구예측": 2, "문헌·규격": 3, "측정": 4}

# 코드가 만든 층(씨앗)의 발화자.
CODE_AUTHOR = "code"

_ROW_COLUMNS = (
    "id, project_id, owner_sub, facet, tag, tags_json, statement, polarity, cites_json, by_json,"
    " variants_json, dissent_json, first_target_key, support_panels, support_targets, confidence,"
    " recall_eligible, needs_review, status, superseded_by, decided_by, decided_at, created_at, updated_at"
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------- 작은 도구

def _loads(text: Any, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _slug(text: str) -> str:
    return _SLUG_RE.sub("_", str(text or "").lower()).strip("_")


def facet_of_tag(tag: str) -> str:
    """통제 어휘 태그의 축으로 facet 을 정한다(plan §4.6.4 1). 축을 모르면 unknown 이다."""
    parts = str(tag or "").split(":")
    return AXIS_FACET.get(":".join(parts[:2]), DEFAULT_FACET)


def _vocab() -> dict:
    """통제 어휘 — narrative 가 이미 캐시해 둔 로더를 그대로 쓴다(중복 로드 금지)."""
    return narrative._character_vocab()


def _panel_of(statement_id: str) -> str | None:
    """패널 산출 행의 id 는 '<panel_id>#C1' 이다(plan §4.2.2 10). 씨앗 행은 '#' 가 없어 None 이다."""
    text = str(statement_id or "")
    return text.split("#", 1)[0] if "#" in text else None


def evidence_grade_of(cites: Sequence[Mapping[str, Any]] | None) -> str:
    """저장된 cites 로 근거 등급을 낸다 — 판정표는 narrative.evidence_grade_from_cites 가 정본이다(§4.4.3)."""
    rows: list[dict] = []
    for cite in cites or ():
        ref = str((cite or {}).get("ref") or "") if isinstance(cite, Mapping) else str(cite or "")
        info = parse_ref(ref)
        if info is None:
            continue
        rows.append({"ok": True, "grade_ok": True, "ref_type": info["kind"], "ref": info["ref"]})
    return narrative.evidence_grade_from_cites({"cites": rows})


# ---------------------------------------------------------------- 계면 태그 별칭 정규화(plan §4.6.3 (4))

def _iface_alias_map(store: RiskStore) -> dict[str, str]:
    """`char:interface:<v>` 값 → 대표 값. rr_iface_alias 의 active 행에서만 만든다."""
    out: dict[str, str] = {}
    rows = store.query(
        "SELECT canonical_a, canonical_b, aliases_json FROM rr_iface_alias WHERE status = 'active'", ())
    for row in rows:
        canonical = "_".join(sorted((_slug(row["canonical_a"]), _slug(row["canonical_b"]))))
        if not canonical:
            continue
        out[canonical] = canonical
        for alias in _loads(row["aliases_json"], []) or ():
            if not isinstance(alias, Mapping):
                continue
            pair = sorted((_slug(alias.get("name_a")), _slug(alias.get("name_b"))))
            key = "_".join(p for p in pair if p)
            if key:
                out[key] = canonical
    return out


def normalize_tags(tags: Iterable[Any], alias_map: Mapping[str, str]) -> list[str]:
    """계면 태그를 별칭 대표 값으로 바꾸고 순서를 보존해 중복만 제거한다."""
    out: list[str] = []
    for raw in tags or ():
        tag = str(raw or "")
        if not tag:
            continue
        if tag.startswith("char:interface:"):
            value = tag[len("char:interface:"):]
            tag = "char:interface:" + alias_map.get(value, value)
        if tag not in out:
            out.append(tag)
    return out


# ---------------------------------------------------------------- L0 씨앗 층(plan §4.6.4 1)

def sync_seed_layer(store: RiskStore, project_id: str, *, owner_sub: str) -> list[str]:
    """최신 스냅샷의 rr_state.character_seed 를 status='seed' 행으로 갈아 끼우고 만든 id 목록을 준다.

    씨앗은 코드 산출이라 통째로 재생성한다 — 사람이 확정(confirmed)했거나 패널이 올린 행은
    status 가 'seed' 가 아니므로 지워지지 않는다.
    """
    row = store.query_one(
        "SELECT s.id AS snapshot_id, st.character_seed_json AS seeds FROM rr_snapshots s"
        " JOIN rr_states st ON st.snapshot_id = s.id WHERE s.project_id = ?"
        " ORDER BY s.created_at DESC, s.id DESC LIMIT 1", (project_id,))
    seeds = _loads(row["seeds"], []) if row is not None else []
    if not isinstance(seeds, list):
        seeds = []

    alias_map = _iface_alias_map(store)
    now = now_epoch()
    made: list[str] = []
    with store.tx():
        store.execute("DELETE FROM rr_character WHERE project_id = ? AND status = 'seed'", (project_id,))
        seen_tags: list[str] = []
        for seed in seeds:
            if not isinstance(seed, Mapping):
                continue
            tags = normalize_tags([seed.get("tag")], alias_map)
            if not tags:
                continue
            tag = tags[0]
            seen_tags.append(tag)
            rule = str(seed.get("rule") or "")
            sid = f"seed:{project_id}:{sha256_hex(f'{rule}|{tag}')[:12]}"
            cites = [{"ref": str(c)} for c in (seed.get("cites") or ()) if str(c)]
            statement = str(seed.get("text") or "").strip() or tag
            _insert_seed_row(store, sid, project_id, owner_sub, facet_of_tag(tag), tag, tags,
                             statement, cites, now)
            made.append(sid)
        if any(tag in SOURCE_ABSENT_SEEDS for tag in seen_tags):
            sid = f"seed:{project_id}:source_absent"
            tag = next(t for t in seen_tags if t in SOURCE_ABSENT_SEEDS)
            _insert_seed_row(store, sid, project_id, owner_sub, "unknown", tag, [tag],
                             SOURCE_ABSENT_TEXT, [], now)
            made.append(sid)
    return made


def _insert_seed_row(store: RiskStore, sid: str, project_id: str, owner_sub: str, facet: str,
                     tag: str, tags: Sequence[str], statement: str, cites: Sequence[dict],
                     now: int) -> None:
    store.execute(
        "INSERT OR REPLACE INTO rr_character(id, project_id, owner_sub, facet, tag, tags_json, statement,"
        " polarity, cites_json, by_json, variants_json, dissent_json, first_target_key, support_panels,"
        " support_targets, confidence, recall_eligible, needs_review, status, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,'observation',?,?,NULL,NULL,NULL,1,1,NULL,1,0,'seed',?,?)",
        (sid, project_id, owner_sub, facet, tag, json.dumps(list(tags), ensure_ascii=False), statement,
         json.dumps(list(cites), ensure_ascii=False), json.dumps([CODE_AUTHOR], ensure_ascii=False),
         now, now),
    )


# ---------------------------------------------------------------- L2 패널 층 병합(plan §4.6.4 2)

def merge_panel_layer(store: RiskStore, project_id: str) -> list[dict]:
    """(project_id, facet, 대표 tag) 로 패널 진술을 묶어 지지 수·이문·이견을 대표 행에 앉힌다.

    행을 지우지 않는다 — narrative.persist 가 패널 재제출마다 그 패널 행만 갈아 끼우므로,
    병합으로 원본 행을 없애면 재제출 한 번에 다른 패널의 문장이 영영 사라진다. 대신 대표 행에만
    집계를 쓰고 흡수된 행은 1/1 로 되돌려 지지 수를 두 번 세지 않게 한다.
    """
    rows = [dict(r) for r in store.query(
        f"SELECT {_ROW_COLUMNS} FROM rr_character WHERE project_id = ? AND status IN ('panel','confirmed')"
        " ORDER BY created_at, id", (project_id,))]
    alias_map = _iface_alias_map(store)

    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        tags = normalize_tags(_loads(row["tags_json"], []) or ([row["tag"]] if row["tag"] else []), alias_map)
        row["_tags"] = tags
        lead = next((t for t in tags if t.startswith("char:")), None)
        row["_lead"] = lead
        # 대표 태그가 없는 문장은 병합하지 않는다(무태그끼리 한 행으로 합치지 않는다, §4.6.4 2).
        groups.setdefault((row["facet"], lead) if lead else ("", row["id"]), []).append(row)

    now = now_epoch()
    merged: list[dict] = []
    with store.tx():
        for members in groups.values():
            members.sort(key=lambda r: (-CHARACTER_STATUS_ORDER.get(str(r["status"]), 0),
                                        int(r["created_at"] or 0), str(r["id"])))
            head, rest = members[0], members[1:]
            panels = {p for p in (_panel_of(r["id"]) for r in members) if p}
            targets = {str(r["first_target_key"]) for r in members if r["first_target_key"]}
            tags: list[str] = []
            for member in members:
                for tag in member["_tags"]:
                    if tag not in tags:
                        tags.append(tag)
            variants = [_excerpt(r) for r in rest]
            dissent = [_excerpt(r) for r in members
                       if r["polarity"] and head["polarity"] and r["polarity"] != head["polarity"]]
            store.execute(
                "UPDATE rr_character SET tag = ?, tags_json = ?, variants_json = ?, dissent_json = ?,"
                " support_panels = ?, support_targets = ?, updated_at = ? WHERE id = ?",
                (head["_lead"], json.dumps(tags, ensure_ascii=False),
                 json.dumps(variants, ensure_ascii=False) if variants else None,
                 json.dumps(dissent, ensure_ascii=False) if dissent else None,
                 max(len(panels), 1), max(len(targets), 1), now, head["id"]),
            )
            for member in rest:
                store.execute(
                    "UPDATE rr_character SET tags_json = ?, variants_json = NULL, dissent_json = NULL,"
                    " support_panels = 1, support_targets = 1, updated_at = ? WHERE id = ?",
                    (json.dumps(member["_tags"], ensure_ascii=False), now, member["id"]),
                )
            merged.append({"id": head["id"], "facet": head["facet"], "tag": head["_lead"],
                           "support_panels": max(len(panels), 1), "support_targets": max(len(targets), 1),
                           "variants": len(variants), "dissent": len(dissent)})
    return merged


def _excerpt(row: Mapping[str, Any]) -> dict:
    """이문·이견 보존 항목 — 문장을 요약하지 않고 축어로 남긴다(§4.6.4 2, crit_13·crit_18)."""
    return {
        "id": str(row["id"]),
        "panel_id": _panel_of(row["id"]),
        "statement": str(row["statement"] or ""),
        "polarity": row["polarity"],
        "by": _loads(row["by_json"], []),
    }


# ---------------------------------------------------------------- x: 자유 태그 승격 후보(plan §4.6.3 (2))

def queue_x_tag_promotions(store: RiskStore, *, owner_sub: str) -> list[str]:
    """서로 다른 타깃 ≥3·패널 ≥2 에서 같은 `x:` 값이 나오면 큐레이션 큐에 올린다(중복 등록 없음).

    임계는 **그 소유자의 코퍼스 안에서** 센다(plan §4.6.3 (2)) — 진술도 큐도 소유자 표라, 필터가 없으면
    사전순 첫 소유자가 남의 태그까지 자기 큐로 가져가고 정작 그 주인은 후보를 못 본다.
    """
    promote = (_vocab().get("promote") or {})
    need_targets = int(promote.get("targets") or 3)
    need_panels = int(promote.get("panels") or 2)

    rows = store.query(
        "SELECT id, tags_json, first_target_key FROM rr_character"
        " WHERE owner_sub = ? AND status != 'superseded' AND tags_json LIKE '%x:%'", (owner_sub,))
    seen_targets: dict[str, set[str]] = {}
    seen_panels: dict[str, set[str]] = {}
    for row in rows:
        for tag in _loads(row["tags_json"], []) or ():
            text = str(tag)
            if not text.startswith("x:"):
                continue
            if row["first_target_key"]:
                seen_targets.setdefault(text, set()).add(str(row["first_target_key"]))
            panel = _panel_of(row["id"])
            if panel:
                seen_panels.setdefault(text, set()).add(panel)

    # 한 번 판단한 태그(open·done·rejected 전부)는 다시 올리지 않는다 — open 만 보면 큐레이터가 reject 한
    # 태그가 매일 밤 새 open 행으로 돌아와 큐가 늘고 배지의 큐 적체 판정이 영구히 켜진다.
    already = set()
    for row in store.query(
            "SELECT payload_json FROM rr_curation_queue WHERE kind = 'x_tag_promote' AND owner_sub = ?",
            (owner_sub,)):
        payload = _loads(row["payload_json"], {})
        if isinstance(payload, Mapping) and payload.get("tag"):
            already.add(str(payload["tag"]))

    now = now_epoch()
    queued: list[str] = []
    with store.tx():
        for tag in sorted(seen_targets):
            if tag in already:
                continue
            targets = seen_targets.get(tag, set())
            panels = seen_panels.get(tag, set())
            if len(targets) < need_targets or len(panels) < need_panels:
                continue
            qid = new_uuid()
            store.execute(
                "INSERT INTO rr_curation_queue(id, owner_sub, kind, payload_json, status, created_at)"
                " VALUES (?,?,'x_tag_promote',?,'open',?)",
                (qid, owner_sub, json.dumps(
                    {"tag": tag, "targets": sorted(targets), "panels": sorted(panels),
                     "vocab_version": _vocab().get("version")}, ensure_ascii=False), now),
            )
            queued.append(tag)
    return queued


# ---------------------------------------------------------------- 프로파일 조립(표시·재사용 순서)

def _order_key(item: Mapping[str, Any]) -> tuple:
    return (
        -CHARACTER_STATUS_ORDER.get(str(item["status"]), 0),
        -int(item["support_panels"] or 0),
        -GRADE_RANK.get(str(item["evidence_grade"]), 0),
        -int(item["updated_at"] or 0),
        str(item["id"]),
    )


def build_profile(store: RiskStore, project_id: str) -> dict:
    """facet 8종 순서·status(confirmed>panel>seed) 순으로 과제 성격 프로파일을 조립한다(읽기 전용)."""
    rows = store.query(
        f"SELECT {_ROW_COLUMNS} FROM rr_character WHERE project_id = ? ORDER BY id", (project_id,))
    grouped: dict[str, list[dict]] = {f: [] for f in FACET_ORDER}
    superseded: list[dict] = []
    dissent: list[dict] = []
    tag_counts: dict[str, int] = {}

    for row in rows:
        item = dict(row)
        item["tags"] = _loads(item.pop("tags_json"), [])
        item["cites"] = _loads(item.pop("cites_json"), [])
        item["by"] = _loads(item.pop("by_json"), [])
        item["variants"] = _loads(item.pop("variants_json"), [])
        item["dissent"] = _loads(item.pop("dissent_json"), [])
        item["evidence_grade"] = evidence_grade_of(item["cites"])
        item["layer"] = item["status"]
        if item["status"] == "superseded":
            superseded.append(item)
            continue
        for tag in item["tags"]:
            tag_counts[str(tag)] = tag_counts.get(str(tag), 0) + 1
        for entry in item["dissent"]:
            dissent.append({"facet": item["facet"], "tag": item["tag"], "head": item["id"], **entry})
        grouped.setdefault(item["facet"], []).append(item)

    facets = []
    for facet in FACET_ORDER:
        items = sorted(grouped.get(facet, []), key=_order_key)
        facets.append({"facet": facet, "statements": items,
                       "na_reason": None if items else "좌석 미기재"})

    project = store.query_one(
        "SELECT character_status FROM rr_projects WHERE id = ?", (project_id,))
    return {
        "project_id": project_id,
        "character_status": project["character_status"] if project is not None else None,
        "facets": facets,
        "facets_filled": sum(1 for f in facets if f["statements"]),
        "tags": [{"tag": t, "n": n} for t, n in sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))],
        "dissent": dissent,
        "superseded": superseded,
        "vocab_version": _vocab().get("version"),
    }


# ---------------------------------------------------------------- 승격(plan §4.6.4 3)

def _row_or_404(store: RiskStore, statement_id: str, owner_sub: str) -> dict:
    row = store.query_one(
        f"SELECT {_ROW_COLUMNS} FROM rr_character WHERE id = ? AND owner_sub = ?", (statement_id, owner_sub))
    if row is None:
        raise AppError("E404", f"성격 진술을 찾을 수 없다 — {statement_id}.", http_status=404)
    return dict(row)


def confirm(store: RiskStore, statement_id: str, *, actor: str, owner_sub: str) -> dict:
    """사람이 진술 1건을 확정한다 — seed·panel 만 confirmed 로 오른다(§4.6.4 3)."""
    row = _row_or_404(store, statement_id, owner_sub)
    if row["status"] == "confirmed":
        return row
    if row["status"] not in ("seed", "panel"):
        raise AppError("E100", f"status={row['status']} 인 진술은 확정할 수 없다.", http_status=400)
    now = now_epoch()
    store.execute(
        "UPDATE rr_character SET status = 'confirmed', decided_by = ?, decided_at = ?, updated_at = ?"
        " WHERE id = ?", (actor, now, now, statement_id))
    refresh_project_status(store, row["project_id"])
    return _row_or_404(store, statement_id, owner_sub)


def supersede(store: RiskStore, statement_id: str, *, superseded_by: str, actor: str,
              owner_sub: str) -> dict:
    """사람이 다른 진술을 우선으로 지정할 때만 superseded 로 내린다(§4.6.4 3)."""
    row = _row_or_404(store, statement_id, owner_sub)
    if superseded_by == statement_id:
        raise AppError("E100", "자기 자신을 우선 진술로 지정할 수 없다.", http_status=400)
    winner = _row_or_404(store, superseded_by, owner_sub)
    if winner["project_id"] != row["project_id"]:
        raise AppError("E100", "다른 과제의 진술을 우선 진술로 지정할 수 없다.", http_status=400)
    now = now_epoch()
    store.execute(
        "UPDATE rr_character SET status = 'superseded', superseded_by = ?, decided_by = ?, decided_at = ?,"
        " updated_at = ? WHERE id = ?", (superseded_by, actor, now, now, statement_id))
    refresh_project_status(store, row["project_id"])
    return _row_or_404(store, statement_id, owner_sub)


def refresh_project_status(store: RiskStore, project_id: str) -> str:
    """rr_projects.character_status 를 살아 있는 행의 최고 층으로 맞춘다(seed→panel→confirmed)."""
    rows = store.query(
        "SELECT DISTINCT status FROM rr_character WHERE project_id = ? AND status != 'superseded'",
        (project_id,))
    have = {str(r["status"]) for r in rows}
    status = "confirmed" if "confirmed" in have else ("panel" if "panel" in have else "seed")
    store.execute("UPDATE rr_projects SET character_status = ?, updated_at = ? WHERE id = ?",
                  (status, now_epoch(), project_id))
    return status


# ---------------------------------------------------------------- 합성 1회분

def synthesize(store: RiskStore, project_id: str, *, owner_sub: str) -> dict:
    """씨앗 갱신 → 패널 층 병합 → x: 승격 후보 → 과제 status 갱신 → 프로파일. 몇 번 돌려도 같다."""
    seeds = sync_seed_layer(store, project_id, owner_sub=owner_sub)
    merged = merge_panel_layer(store, project_id)
    queued = queue_x_tag_promotions(store, owner_sub=owner_sub)
    status = refresh_project_status(store, project_id)
    profile = build_profile(store, project_id)
    profile["synthesis"] = {"seeds": len(seeds), "merged_groups": len(merged),
                            "x_tag_queued": queued, "character_status": status}
    return profile
