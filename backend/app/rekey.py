# 확정을 뒤집는 조작의 키 전파(rekey, plan §5.9.5) — 원장 이력 → 영향 finding 의 subject_key 재계산 → 별칭 append·revoke → registry.merge → priors·패턴·큐 → rr_audit
"""확정을 뒤집는 네 조작(same-as reject · unmerge_key · iface-ledger rejected · 계면 별칭 revoke)과 그 짝인 merge_key 가 표기만 바꾸고
끝나지 않게 한다. 한 조작 = 한 트랜잭션이다 — 어느 걸음이 실패하면(별칭 6홉 · 순환은 409) 원장 변경까지 함께 되돌아간다.

모델. finding 의 `subject_key` 는 저장 때 그 스냅샷 노드의 ckey(동결 시점의 유효 ckey)로 굳고 `cluster_key` 도 삽입 시 동결이다(§4.3.2 1).
'지금 원장으로 다시 센 주체' 는 그 동결 주체의 ckey 를 지금의 `rr_part_keys.merged_into` 사슬로 풀고(`sameas.resolve_ckey`) 계면이면
살아 있는 `rr_iface_alias` 로 접은 값이다(`current_subject`). 같은 `cluster_key` 의 finding 은 동결 주체가 같으므로 다시 센 키도 같다 —
그래서 별칭(옛 키 → 새 키)으로 옮길 수 있다. 다시 센 키가 동결 키와 다르면 원장 별칭(reason ckey_merge · iface_alias)을 세우고, 같으면
그 옛 키에 원장이 세웠던 별칭을 거둔다(같은 사람 · 같은 시각). 사람이 세운 별칭(cluster_merge · dim_rename)은 건드리지 않는다. 재매핑
별칭(taxonomy_major)은 사람 결정이 아니라 키 계보라 그 끝 키에서 원장 별칭을 이어 붙인다(재매핑 별칭 자체는 그대로).
등록부는 별칭 해석으로 다시 병합된다 — 접힌 옛 행은 superseded 로 닫히고(registry._close_vacated_rows) 다시 갈라지면 다시 열린다. 다시
병합하는 대상은 주체로 닿는 원자의 대상과, 별칭 사슬이 바뀐 키를 지나는 키(사람 별칭 Q → Y 의 Q)를 동결 키로 가진 원자의 대상이다.

한계. 동결 스냅샷의 노드 ckey 는 바뀌지 않는다(§2.7.3). 병합이 서 있던 동안 동결한 스냅샷의 노드는 이미 대표 키를 받았으므로 병합을
풀어도 그 스냅샷 위 finding 의 주체는 대표 키 그대로다 — 갈라 보려면 '재해석 적용'(새 스냅샷)이 필요하다. intra · pair same-as 확정도 같은
까닭으로 동결 때 노드 ckey 에 흡수된다 — reject 의 키 효과는 그 확정에서 자동 승계된 rr_part_keys 행(§2.7.3)을 되돌리는 것이다.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from app import common, narrative, registry, sameas
from app.errors import AppError

# 원장이 세우고 원장 되돌리기가 거두는 별칭 사유. 그 밖(cluster_merge · taxonomy_major · dim_rename)은 사람 · 재매핑의 몫이다.
LEDGER_REASONS: tuple[str, ...] = ("ckey_merge", "iface_alias")
OPS: tuple[str, ...] = ("sameas_reject", "unmerge_key", "iface_ledger_reject", "iface_alias_revoke", "merge_key")
AUTO_DECIDED_BY = "code:pair_correspondence"


def _loads(text: Any) -> dict:
    try:
        value = json.loads(text) if text else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------- 2·3걸음의 재료 — 지금 원장의 주체
def current_subject(store: Any, subject_key: str | None, owner_sub: str) -> tuple[str, str]:
    """(지금 원장으로 다시 센 subject_key, 바뀐 까닭) — 까닭은 '' · 'ckey_merge' · 'iface_alias'.

    ck: 로 된 파트(1개) · 계면(2개) 주체만 다시 센다 — dim: · asm: · 미해석('')은 원장과 무관해 그대로다. 파트 ckey 는 merged_into 사슬
    끝까지(≤5단) 풀고, 계면은 푼 두 키를 정렬한 쌍을 살아 있는 rr_iface_alias 로 접는다(저장 때 `narrative.resolve_subject` 와 같은 순서).
    """
    key = str(subject_key or "")
    parts = key.split("|")
    if not key or len(parts) > 2 or not all(p.startswith("ck:") for p in parts):
        return key, ""
    resolved = [sameas.resolve_ckey(store, part, owner_sub) for part in parts]
    if len(resolved) == 1:
        return resolved[0], ("ckey_merge" if resolved[0] != key else "")
    via_ckeys = "|".join(sorted(resolved))
    alias = store.query_one(
        "SELECT canonical_a, canonical_b FROM rr_iface_alias WHERE alias_key = ? AND status = 'active'", (via_ckeys,))
    out = "|".join(sorted((str(alias["canonical_a"]), str(alias["canonical_b"])))) if alias is not None else via_ckeys
    if out == key:
        return key, ""
    return out, ("ckey_merge" if via_ckeys != key else "iface_alias")


def with_descendants(store: Any, ckeys: Iterable[str], owner_sub: str) -> set[str]:
    """그 ckey 들과 merged_into 사슬로 그 키들에 매달린 키 전부 — 그 키가 풀리는 길이 바뀌면 함께 바뀌는 키다(≤5단)."""
    out = {str(c) for c in ckeys if c}
    frontier = set(out)
    for _ in range(sameas.MERGE_CHAIN_MAX):
        if not frontier:
            break
        marks = ",".join("?" for _ in frontier)
        rows = store.query(
            f"SELECT ckey FROM rr_part_keys WHERE owner_sub = ? AND status = 'merged' AND merged_into IN ({marks})",
            (owner_sub, *sorted(frontier)))
        frontier = {str(r["ckey"]) for r in rows} - out
        out |= frontier
    return out


def touching_findings(store: Any, owner_sub: str, ckeys: Iterable[str] = (), pairs: Iterable[str] = (),
                      cluster_keys: Iterable[str] = ()) -> list[dict]:
    """2걸음 — 그 소유자의 finding 가운데 동결 주체가 그 ckey 를 담거나 그 계면 쌍과 같은 것(`ix_rr_findings_subject`), 그리고 동결
    cluster_key 가 `cluster_keys` 에 든 것(`ix_rr_findings_cluster` — 주체로는 닿지 않고 바뀐 별칭 사슬로만 닿는 원자).

    카드 대조 finding 도 센다 — 별칭은 소유자 단위의 키 사실이라 흐름을 가리지 않는다(등록부 병합이 흐름마다 거른다).
    """
    conds: list[str] = []
    params: list[Any] = [owner_sub]
    for ck in sorted({str(c) for c in ckeys if c}):
        conds.append("subject_key = ? OR subject_key LIKE ? OR subject_key LIKE ?")
        params += [ck, f"{ck}|%", f"%|{ck}"]
    for pair in sorted({str(p) for p in pairs if p}):
        conds.append("subject_key = ?")
        params.append(pair)
    frozen = sorted({str(k) for k in cluster_keys if k})
    if frozen:
        conds.append(f"cluster_key IN ({','.join('?' for _ in frozen)})")
        params += frozen
    if not conds:
        return []
    where = " OR ".join(f"({c})" for c in conds)
    return [dict(r) for r in store.query(
        "SELECT finding_id, target_key, cluster_key, subject_key, mechanism, mechanism_detail, change_kind, finding_json"
        f" FROM rr_findings WHERE owner_sub = ? AND ({where}) ORDER BY finding_id", params)]


def _key_inputs(row: Mapping[str, Any]) -> tuple[Any, Any, Any] | None:
    """동결 cluster_key 를 다시 만드는 입력(mechanism, 키 세부, change_kind) — 못 만들면 None(그 키는 옮기지 않는다).

    키 세부는 finding_json.key_detail(카드 대조 미분류 쪼개기)이 있으면 그것, 없으면 mechanism_detail 이다. 생산자마다 빈 값을 넘기는
    꼴(None · '')이 달라 둘 다 대본다 — 다시 만든 키가 동결 키와 같아야 새 키를 같은 식으로 셀 수 있다.
    """
    finding = _loads(row.get("finding_json"))
    subject, frozen = str(row.get("subject_key") or ""), str(row.get("cluster_key") or "")
    for detail in dict.fromkeys((finding.get("key_detail"), row.get("mechanism_detail"))):
        inputs = _reproduce(row.get("mechanism"), detail, subject, row.get("change_kind"), frozen)
        if inputs is not None:
            return inputs
    return None


def _reproduce(mech: Any, detail: Any, subject: str, change: Any, expected: str) -> tuple[Any, Any, Any] | None:
    """(mechanism, 세부, change_kind) 로 `expected` 키를 다시 만들 수 있으면 그 입력 — 빈 값의 두 꼴(None · '')을 다 대본다."""
    for inputs in ((mech, detail, change), (mech or "", detail or "", change or "")):
        if narrative.cluster_key_of(inputs[0], inputs[1], subject, inputs[2]) == expected:
            return inputs
    return None


def _active_alias(store: Any, owner_sub: str, old_key: str):
    return store.query_one(
        "SELECT new_cluster_key, reason, evidence_json FROM rr_cluster_alias"
        " WHERE owner_sub = ? AND old_cluster_key = ? AND revoked_at IS NULL", (owner_sub, old_key))


def _landing(store: Any, owner_sub: str, key: str, inputs: tuple | None, subject: str) -> tuple[str, tuple | None, Any, bool]:
    """원장 별칭이 설 자리 — 동결 키에서 재매핑 별칭(taxonomy_major)을 따라간 끝. (자리, 그 자리의 키 입력, 그 자리의 사람 별칭, 됨).

    재매핑 별칭은 사람 판단이 아니라 키 계보다(같은 원자의 메커니즘 세부만 바꾼 새 키, `learning.apply_remap`) — 그 별칭을 거두거나
    덮지 않고 그 끝 키에서 원장 별칭을 이어 붙여야 재매핑한 원자도 파트 병합을 따라간다. 사람 별칭(cluster_merge · dim_rename)에
    닿으면 그 자리에서 멈춘다(사람 결정이 이긴다). `inputs` 가 있으면 재매핑 한 걸음마다 그 근거의 to_detail 로 다음 키를 같은 식으로
    다시 만들어 보고, 못 만들면 됨=False 다(다른 식의 키를 지어 잇지 않는다). `inputs` 가 없으면(원장이 원하는 키가 없는 되돌리기)
    끝 자리만 찾는다.
    """
    current = key
    for _ in range(registry.ALIAS_MAX_HOPS + 1):
        alias = _active_alias(store, owner_sub, current)
        if alias is None or alias["reason"] in LEDGER_REASONS:
            return current, inputs, None, True
        if alias["reason"] != "taxonomy_major":
            return current, inputs, alias, True
        nxt = str(alias["new_cluster_key"])
        if inputs is not None:
            to_detail = _loads(alias["evidence_json"]).get("to_detail")
            inputs = _reproduce(inputs[0], to_detail, subject, inputs[2], nxt) if to_detail else None
            if inputs is None:
                return current, None, None, False
        current = nxt
    return current, None, None, False                 # 5홉을 넘는 재매핑 사슬 — 끝을 모른다


# ---------------------------------------------------------------- 3걸음 — 별칭 맞추기
def upstream_keys(store: Any, owner_sub: str, keys: Iterable[str]) -> set[str]:
    """그 키들과, 살아 있는 별칭 사슬이 그 키들을 지나는 키 전부(그 소유자) — 그 키의 별칭이 바뀌면 함께 풀이가 바뀌는 키다.

    앞 키에서 그 키에 닿기까지의 별칭은 이 맞추기가 건드리지 않는 키의 것이라 바꾸기 전과 뒤가 같다 — 그래서 바꾸기 전에 한 번 센다.
    """
    out = {str(k) for k in keys if k}
    frontier = set(out)
    for _ in range(registry.ALIAS_MAX_HOPS + 1):
        if not frontier:
            break
        marks = ",".join("?" for _ in frontier)
        rows = store.query(
            "SELECT old_cluster_key FROM rr_cluster_alias WHERE owner_sub = ? AND revoked_at IS NULL"
            f" AND new_cluster_key IN ({marks})", (owner_sub, *sorted(frontier)))
        frontier = {str(r["old_cluster_key"]) for r in rows} - out
        out |= frontier
    return out


def _plan(store: Any, owner_sub: str, findings: Iterable[Mapping[str, Any]]) -> dict:
    """동결 cluster_key 마다 원장 별칭이 설 자리와 원장이 원하는 키를 센다(아무것도 쓰지 않는다)."""
    groups: dict[str, dict] = {}
    for row in findings:
        key = str(row.get("cluster_key") or "")
        if key:
            groups.setdefault(key, {"row": row, "targets": set()})["targets"].add(str(row.get("target_key") or ""))
    decisions: dict[str, dict] = {}
    kept_human: list[dict] = []
    skipped: list[dict] = []
    for key in sorted(groups):
        row = groups[key]["row"]
        frozen_subject = str(row.get("subject_key") or "")
        subject, why = current_subject(store, frozen_subject, owner_sub)
        inputs = None
        if why:
            inputs = _key_inputs(row)
            if inputs is None:
                skipped.append({"cluster_key": key, "reason": "key_not_reproducible"})
                continue
        landing, inputs, human, ok = _landing(store, owner_sub, key, inputs, frozen_subject)
        if not ok:
            skipped.append({"cluster_key": key, "reason": "remap_not_reproducible", "at": landing})
            continue
        want = None
        if why:
            want = narrative.cluster_key_of(inputs[0], inputs[1], subject, inputs[2])
            want = None if want == landing else want
        if human is not None:
            # 사람이 세운 별칭은 원장 되돌리기가 거두거나 덮지 않는다 — 원장이 다른 키를 가리켜도 사람 결정이 이긴다.
            if want is not None and human["new_cluster_key"] != want:
                kept_human.append({"cluster_key": landing, "alias": str(human["new_cluster_key"]), "reason": human["reason"],
                                   "ledger_wants": want})
            continue
        decisions.setdefault(landing, {"want": want, "why": why, "via": key, "subject_before": row.get("subject_key"),
                                       "subject_after": subject})
    return {"decisions": decisions, "kept_human": kept_human, "skipped": skipped, "keys": sorted(groups),
            "targets": sorted({t for g in groups.values() for t in g["targets"] if t})}


def _check_chains(store: Any, owner_sub: str, keys: Iterable[str]) -> None:
    """맞춘 뒤의 별칭으로 그 키들의 사슬이 5홉 안이고 순환하지 않는지 — 세울 때의 점검(`add_cluster_alias`)은 새 별칭 뒤만 세므로,
    사람 별칭이 이 키로 이어 오는 앞 키(Q → Y 에 Y → X 가 서면 Q 의 사슬)가 넘는 것은 여기서 본다. 넘으면 409 다."""
    for key in sorted(keys):
        if registry._alias_hops(store, key, owner_sub) > registry.ALIAS_MAX_HOPS:
            raise AppError("alias_chain_too_long",
                           f"별칭 체인이 {registry.ALIAS_MAX_HOPS} 홉을 넘거나 순환합니다 — {key}.", 409)


def reconcile_aliases(store: Any, owner_sub: str, findings: Iterable[Mapping[str, Any]], *, op: str, actor: str,
                      at: int) -> dict:
    """동결 cluster_key 마다 지금 원장의 키를 세어 원장 별칭을 맞춘다 — 다르면 append, 같으면 원장이 세웠던 별칭을 revoke.

    거둘 별칭을 먼저 다 거두고 그 뒤에 세운다 — 세울 때의 홉 · 순환 점검이 같은 맞추기가 곧 거둘 별칭을 세지 않게 한다(종전에는 키
    마다 거두고 세워, 같은 모양이 키 해시 차례에 따라 409 가 됐다). 맞춘 뒤 바뀐 키와 그 앞 키의 사슬을 한 번 더 본다(`_check_chains`).
    반환 `{added[], revoked[], kept_human[], skipped[], targets[], keys[], before{}, after{}}` — before · after 는 바뀐 키와 그 앞 키
    (`upstream_keys`)의 맞추기 전후 풀이다. 별칭 6홉 · 순환이면 409 를 그대로 올린다(부르는 트랜잭션 전체가 되돌아간다).
    """
    plan = _plan(store, owner_sub, findings)
    closure = upstream_keys(store, owner_sub, set(plan["keys"]) | set(plan["decisions"]))
    before = {k: registry.resolve_cluster_key(store, k, owner_sub=owner_sub) for k in sorted(closure)}
    revoked: list[dict] = []
    adding: list[str] = []
    for landing in sorted(plan["decisions"]):
        want = plan["decisions"][landing]["want"]
        alias = _active_alias(store, owner_sub, landing)
        if alias is not None and alias["new_cluster_key"] != want:
            registry.revoke_cluster_alias(store, landing, owner_sub=owner_sub, revoked_by=actor, at=at)
            revoked.append({"old": landing, "new": str(alias["new_cluster_key"]), "reason": str(alias["reason"])})
            alias = None
        if want is not None and alias is None:
            adding.append(landing)
    added: list[dict] = []
    for landing in adding:
        item = plan["decisions"][landing]
        evidence = {"op": op, "subject_before": item["subject_before"], "subject_after": item["subject_after"], "by": actor}
        if item["via"] != landing:
            evidence["via"] = item["via"]           # 재매핑 별칭 끝에 이어 붙였다 — 그 원자의 동결 키
        registry.add_cluster_alias(store, landing, item["want"], owner_sub=owner_sub, reason=item["why"], decided_by=actor,
                                   at=at, evidence=evidence)
        added.append({"old": landing, "new": item["want"], "reason": item["why"]})
    _check_chains(store, owner_sub, closure)
    after = {k: registry.resolve_cluster_key(store, k, owner_sub=owner_sub) for k in sorted(closure)}
    return {"added": added, "revoked": revoked, "kept_human": plan["kept_human"], "skipped": plan["skipped"],
            "targets": plan["targets"], "keys": plan["keys"], "before": before, "after": after}


# ---------------------------------------------------------------- 5걸음 — 패턴 · 큐
def _resolve_stored(store: Any, key: str, owner_sub: str) -> str:
    """등록부 · 큐에 적힌 키(.imp 접미 포함)를 별칭으로 푼 값 — 접미는 그대로 둔다."""
    base = registry.strip_improvement_suffix(key)
    return registry.resolve_cluster_key(store, base, owner_sub=owner_sub) + key[len(base):]


def reinterpret_patterns(store: Any, owner_sub: str, keys: set[str], *, at: int) -> list[dict]:
    """rr_patterns.cluster_key_norm 재해석 — 별칭으로 다른 키에 접힌 패턴은 그 대표 패턴 id 를 merged_into 에, 다시 갈라지면 NULL 로.

    대표 키에 아직 패턴이 없으면 merged_into 를 비워 둔다(가리킬 행이 없다 — 다음 야간 마이너가 대표 패턴을 세운다). n_* 재합산은
    야간 마이너의 몫이다(접힌 패턴은 마이너가 건너뛴다).
    """
    changed: list[dict] = []
    for pattern in store.query(
            "SELECT id, cluster_key_norm, merged_into FROM rr_patterns WHERE owner_sub = ? ORDER BY id", (owner_sub,)):
        norm = str(pattern["cluster_key_norm"])
        if norm not in keys:
            continue
        resolved = registry.resolve_cluster_key(store, norm, owner_sub=owner_sub)
        rep = None
        if resolved != norm:
            row = store.query_one("SELECT id FROM rr_patterns WHERE cluster_key_norm = ?", (resolved,))
            rep = str(row["id"]) if row is not None and str(row["id"]) != str(pattern["id"]) else None
        if (pattern["merged_into"] or None) != rep:
            store.execute("UPDATE rr_patterns SET merged_into = ?, updated_at = ? WHERE id = ?", (rep, at, pattern["id"]))
            changed.append({"pattern_id": str(pattern["id"]), "merged_into": rep})
    return changed


def close_invalid_merge_items(store: Any, owner_sub: str, keys: set[str], *, actor: str, at: int) -> list[str]:
    """열린 rr_curation_queue(kind='cluster_merge') 가운데 이 재키로 무효가 된 항목을 닫는다 — status='rejected' ·
    decision_json.reason='rekey'. 무효 = 두 키가 이제 같은 키로 풀리거나(이미 접혔다) 어느 한쪽이 다른 키에 접혀 홀로 서지 않는다."""
    closed: list[str] = []
    for item in store.query(
            "SELECT id, payload_json FROM rr_curation_queue WHERE kind = 'cluster_merge' AND status = 'open'"
            " AND owner_sub = ? ORDER BY id", (owner_sub,)):
        payload = _loads(item["payload_json"])
        a, b = str(payload.get("a") or ""), str(payload.get("b") or "")
        if not ({registry.strip_improvement_suffix(a), registry.strip_improvement_suffix(b)} & keys):
            continue
        ra, rb = _resolve_stored(store, a, owner_sub), _resolve_stored(store, b, owner_sub)
        if ra == rb or ra != a or rb != b:
            store.execute(
                "UPDATE rr_curation_queue SET status = 'rejected', decision_json = ?, decided_by = ?, decided_at = ?"
                " WHERE id = ?",
                (common.canonical_json({"reason": "rekey", "a_resolved": ra, "b_resolved": rb}), actor, at, item["id"]))
            closed.append(str(item["id"]))
    return closed


# ---------------------------------------------------------------- 2~6걸음 한 벌
def run(store: Any, *, op: str, owner_sub: str, actor: str | None = None, ckeys: Iterable[str] = (),
        pairs: Iterable[str] = (), subject_id: str, project_id: str | None = None,
        ledger: Mapping[str, Any] | None = None, channel: str = "rest", actor_verified: bool = True,
        at: int | None = None, via: str | None = None) -> dict:
    """§5.9.5 의 2~6걸음. 1걸음(원장 행의 이력 — prev_status · revoked_* · merged_into=NULL)은 부르는 쪽이 같은 트랜잭션에서 먼저 한다.

    2 그 키를 주체로 가진 finding(`touching_findings`) → 3 별칭 맞추기(`reconcile_aliases`) → 4 영향 대상마다 `registry.merge`(멱등 —
    support · contested · rejected · human_n 은 원자에서 다시 센다, 접힌 행은 superseded 로 닫힌다) → 5 기여 · priors 재합산(병합이 한다) ·
    패턴 merged_into · 무효 큐 닫기 → 6 rr_audit(scope='registry', action='rekey') 1행.

    영향 대상은 주체로 닿는 원자의 대상과, 풀이가 바뀐 키(별칭 사슬이 바뀐 키를 지나는 앞 키 포함)를 동결 키로 가진 원자의 대상이다 —
    사람 별칭(key(Q) → key(Y))으로만 Y 의 클러스터에 닿는 대상도 Y 가 X 에 접히면 함께 접힌다. 종전에는 주체로 닿는 대상만 다시 병합해
    그 대상의 등록부 · priors 가 다음 병합까지 옛 별칭대로 남았다.

    `channel` · `actor_verified` 는 감사 행의 입구와 행위자 검증이다 — 부르는 라우트가 신원 출처에서 정한다(MCP 길은 mcp · 0, 사용자 결정
    10-31 — 종전에는 검증 1 이 글자로 박혀 MCP 의 same-as reject 도 검증된 행위자로 적혔다). `via`("admin")는 그 조작을 관리자 우회로만
    들였다는 표시다 — 감사 행 after 의 `via` 칸에 싣는다(routes._audit 과 같은 칸, 사용자 결정 11-01).
    """
    if op not in OPS:
        raise AppError("E100", f"rekey op 는 {list(OPS)} 중 하나여야 합니다 — {op!r}.", 422)
    actor = actor or owner_sub
    at = common.now_epoch() if at is None else int(at)
    with store.tx():
        findings = touching_findings(store, owner_sub, ckeys, pairs)
        keys = {str(f["cluster_key"]) for f in findings if f.get("cluster_key")}
        aliases = reconcile_aliases(store, owner_sub, findings, op=op, actor=actor, at=at)
        before, after = aliases["before"], aliases["after"]
        moved = {k for k in before if before[k] != after[k]}
        reached = touching_findings(store, owner_sub, cluster_keys=moved - keys)
        targets = sorted(set(aliases["targets"]) | {str(f["target_key"]) for f in reached if f.get("target_key")})
        merged = {target: registry.merge(store, target, owner_sub=owner_sub) for target in targets}
        touched = set(before) | set(before.values()) | set(after.values())
        patterns = reinterpret_patterns(store, owner_sub, touched, at=at)
        queue_closed = close_invalid_merge_items(store, owner_sub, touched, actor=actor, at=at)
        shown = sorted(keys | moved)
        audit_id = common.new_uuid()
        store.execute(
            "INSERT INTO rr_audit(id, owner_sub, actor, actor_verified, channel, scope, subject_id, project_id, action,"
            " before_json, after_json, reason, at) VALUES (?,?,?,?,?,'registry',?,?,'rekey',?,?,NULL,?)",
            (audit_id, owner_sub, actor, int(bool(actor_verified)), channel, subject_id, project_id,
             common.canonical_json({"op": op, "ledger": dict(ledger or {}),
                                    "old_cluster_keys": {k: before[k] for k in shown}}),
             common.canonical_json({"new_cluster_keys": {k: after[k] for k in shown},
                                    "findings_n": len(findings) + len(reached), "targets_n": len(targets),
                                    "aliases_added": aliases["added"], "aliases_revoked": aliases["revoked"],
                                    "kept_human": aliases["kept_human"], "skipped": aliases["skipped"],
                                    "patterns": patterns, "queue_closed": queue_closed,
                                    **({"via": via} if via is not None else {})}),
             at))
    return {"op": op, "findings_n": len(findings) + len(reached), "targets": targets,
            "aliases_added": aliases["added"], "aliases_revoked": aliases["revoked"],
            "kept_human": aliases["kept_human"], "skipped": aliases["skipped"],
            "folded": {t: m.get("folded", 0) for t, m in merged.items()},
            "patterns": patterns, "queue_closed": queue_closed, "audit_id": audit_id}


# ---------------------------------------------------------------- 1걸음 — 조작마다(같은 트랜잭션)
def unmerge_auto_rows(store: Any, sameas_id: str, *, owner_sub: str, actor: str, at: int) -> list[str]:
    """same-as 확정에서 자동 승계된 rr_part_keys 행(decided_by='code:pair_correspondence' · 근거의 ledger_id = 그 rr_sameas 행)을
    되돌린다 — merged_into=NULL · status='confirmed' · merge_evidence_json=NULL(§5.9.5 1, 행 삭제 없음). 되돌린 ckey 목록."""
    out: list[str] = []
    for row in store.query(
            "SELECT ckey, merge_evidence_json FROM rr_part_keys WHERE owner_sub = ? AND status = 'merged'"
            " AND decided_by = ? ORDER BY ckey", (owner_sub, AUTO_DECIDED_BY)):
        if str(_loads(row["merge_evidence_json"]).get("ledger_id") or "") != str(sameas_id):
            continue
        store.execute(
            "UPDATE rr_part_keys SET status = 'confirmed', merged_into = NULL, merge_evidence_json = NULL,"
            " decided_by = ?, decided_at = ?, updated_at = ? WHERE ckey = ? AND owner_sub = ?",
            (actor, at, at, row["ckey"], owner_sub))
        out.append(str(row["ckey"]))
    return out


def revoke_iface_alias(store: Any, alias_key: str, *, owner_sub: str, actor: str | None = None,
                       at: int | None = None, channel: str = "rest", actor_verified: bool = True) -> dict:
    """계면 별칭 revoke — rr_iface_alias.status='revoked' · revoked_by · revoked_at(행 삭제 없음)을 쓰고 같은 트랜잭션에서 재키를 돈다.

    영향 주체는 그 별칭의 두 키 · 대표 두 키에 걸린(병합 사슬 포함) 주체다. 철회 뒤 새 원자의 주체도 이 별칭으로 접히지 않는다
    (`narrative._iface_alias` 가 살아 있는 별칭만 본다). 남의 별칭은 없는 별칭과 같은 404 다.
    """
    actor = actor or owner_sub
    at = common.now_epoch() if at is None else int(at)
    row = store.query_one(
        "SELECT alias_key, canonical_a, canonical_b, status FROM rr_iface_alias WHERE alias_key = ? AND owner_sub = ?",
        (alias_key, owner_sub))
    if row is None:
        raise AppError("E404", f"계면 별칭이 없습니다 — {alias_key}.", 404)
    if row["status"] == "revoked":
        return {"alias_key": alias_key, "revoked": False, "already": True}
    with store.tx():
        store.execute(
            "UPDATE rr_iface_alias SET status = 'revoked', revoked_by = ?, revoked_at = ?, updated_at = ?"
            " WHERE alias_key = ? AND owner_sub = ?", (actor, at, at, alias_key, owner_sub))
        parts = {*str(alias_key).split("|"), str(row["canonical_a"]), str(row["canonical_b"])}
        out = run(store, op="iface_alias_revoke", owner_sub=owner_sub, actor=actor, channel=channel,
                  actor_verified=actor_verified, at=at, ckeys=with_descendants(store, parts, owner_sub),
                  subject_id=f"alias:{alias_key}",
                  ledger={"alias_key": alias_key, "canonical": [row["canonical_a"], row["canonical_b"]]})
    return {"alias_key": alias_key, "revoked": True, "revoked_at": at, "rekey": out}
