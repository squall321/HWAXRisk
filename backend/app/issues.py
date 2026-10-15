# 쟁점 선정·패널·결과(재설계 M3 S3-6·S3-7) — hold 가 가린 FAIL·단독 중대·갈린 판정을 코드가 고르고(LLM 0회) 상한 밖도 행으로 남긴다
"""쟁점은 등록부 클러스터 하나에 하나다(`rr_issues` · M3.md 4.2). 고르는 것은 코드이고 근거는 cells 대상의 등록부·셀·판정 행이다.

- 유형(m3-synthesis 3.6) — `held_fail`(살아 있는 카드 대조 원자의 주장 판정이 FAIL 이거나 주장 심각도가 치명 — hold 가 가린 FAIL,
  P-02) · `solo_severe`(리스크 행, `max(sev3, claimed.sev3) ≥ 2`, 제기 전문가 1명) · `split_verdict`(대표 메커니즘이 미분류가
  아니고 같은 단위·겹치는 변경 참조에 applies=yes·OK·인용 대조 통과를 낸 다른 전문가가 문턱 이상이며 그 셀의 메커니즘 신고에
  같은 코드가 있다, P-03).
- 등급 — P1 = 검증된 주장값(`verified_fail_experts ≥ 1`) 또는 등록부 값이 FAIL·치명, P2 = 검증 안 된 주장 FAIL·치명 또는
  sev3 = 2, P3 = 그 밖.
- 상한(#28) — P1 을 HARD_CAP(48)까지 먼저, P2·P3 은 합계가 CAP(24)에 닿을 때까지. 상한은 그 대상이 돌린 쟁점 패널 누적으로
  센다(다시 고른 회차도 같다). 상한 밖은 지우지 않고 `untried_cap(cap)` 행이다.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app import common, config, registry
from app.risk_store import RiskStore

TYPE_WEIGHT: dict[str, float] = {"held_fail": 1.4, "split_verdict": 1.3, "solo_severe": 1.0}
ISSUE_TYPES: tuple[str, ...] = ("held_fail", "solo_severe", "split_verdict")
P_ORDER: dict[str, int] = {"P1": 0, "P2": 1, "P3": 2}
# 다시 고를 때의 상태 갈래(3.6) — 편성·도는 쟁점은 건드리지 않고, 끝난 쟁점은 근거가 바뀌었을 때만 되돌린다. 사람이 넘긴 것은 그대로.
IN_FLIGHT_STATES: tuple[str, ...] = ("planned", "running")
DONE_STATES: tuple[str, ...] = ("resolved", "inconclusive")
REALLOCATED_STATES: tuple[str, ...] = ("queued", "untried_cap", "withdrawn")
CAP_REASON = "cap"
# 쟁점 패널의 수확 — 최근 YIELD_WINDOW 패널이 전부 기각·불명이면 잡 진행판에 알림을 적는다(멈춤은 사람이 정한다, 3.12 · M3.md 리스크 표).
YIELD_WINDOW = 5
YIELD_LOW_ADVICE = "issue_yield_low"
YIELD_LOW_OUTCOMES: tuple[str, ...] = ("rejected", "undetermined")


def issue_id_of(target_key: str, anchor_cluster_key: str) -> str:
    """'iss-' + sha1(target_key|anchor)[:12] — 같은 닻이면 같은 행이다(다시 골라도)."""
    return "iss-" + hashlib.sha1(f"{target_key}|{anchor_cluster_key}".encode()).hexdigest()[:12]


def _loads(text: Any, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _str(value: Any) -> str:
    return str(value or "").strip()


def _change_refs(finding_json: Mapping[str, Any]) -> set[str]:
    """원자가 인용한 변경 줄 참조(`c:` — 판정 행의 refs_json 과 같은 꼴)."""
    return {_str(c.get("ref")) for c in finding_json.get("cites") or () if isinstance(c, Mapping)
            and _str(c.get("ref")).startswith("c:")}


# ---------------------------------------------------------------- 원장 읽기
def _card_atoms(store: RiskStore, target_key: str) -> dict[str, dict]:
    """살아 있는 카드 대조 원자 — finding_id → {agent_key, unit_id, refs, judgement_claimed, severity_claimed, raisers}."""
    out: dict[str, dict] = {}
    for row in store.query(
            "SELECT finding_id, agent_key, unit_id, status, judgement, severity, evidence_grade, finding_json FROM rr_findings"
            " WHERE target_key = ? AND source_kind = ? AND COALESCE(status, 'open') <> 'rejected_in_panel'"
            " AND COALESCE(origin, 'llm') <> 'human'", (target_key, registry.CARD_REVIEW_SOURCE)):
        fj = _loads(row["finding_json"], {})
        raisers = [_str(k) for k in fj.get("raised_by") or () if _str(k)] or [_str(row["agent_key"])]
        out[str(row["finding_id"])] = {
            "agent_key": _str(row["agent_key"]), "unit_id": _str(row["unit_id"]), "refs": _change_refs(fj),
            "judgement": _str(fj.get("judgement_claimed")) or _str(row["judgement"]),
            "severity": _str(fj.get("severity_claimed")) or _str(row["severity"]),
            "raisers": raisers, "grade": _str(row["evidence_grade"]),
            "cards": sorted({_str(c.get("ref"))[len("card:"):].split("#", 1)[0] for c in fj.get("cites") or ()
                             if isinstance(c, Mapping) and _str(c.get("ref")).startswith("card:")}),
            # 카드 인용이 앱 재대조를 지났나(registry._verified 의 card_only 와 같은 뜻 — 지어낸 인용은 quote_mismatch 다).
            "verified": any(isinstance(c, Mapping) and c.get("ok") and c.get("verified") and not c.get("quote_mismatch")
                            and c.get("ref_type") == "card" for c in fj.get("_resolved_cites") or ())}
    return out


def _ok_verdicts(store: RiskStore, target_key: str) -> dict[str, list[dict]]:
    """단위 → 실효 OK 판정(applies=yes) — {agent_key, record_id, refs, quote_ok}. 반대 측의 원천이다."""
    out: dict[str, list[dict]] = {}
    for row in store.query(
            "SELECT unit_id, agent_key, record_id, refs_json, quote_ok FROM rr_card_verdicts WHERE target_key = ?"
            " AND is_effective = 1 AND applies = 'yes' AND judgement = 'OK' ORDER BY unit_id, agent_key, record_id",
            (target_key,)):
        out.setdefault(str(row["unit_id"]), []).append({
            "agent_key": str(row["agent_key"]), "record_id": str(row["record_id"]),
            "refs": {_str(r) for r in _loads(row["refs_json"], []) or ()}, "quote_ok": row["quote_ok"]})
    return out


def _cell_mechs(store: RiskStore, target_key: str) -> dict[tuple[str, str], set[str]]:
    """(단위, 전문가) → 셀의 메커니즘 신고(`mechs_json`)."""
    return {(str(r["unit_id"]), str(r["agent_key"])): {_str(m) for m in _loads(r["mechs_json"], []) or ()}
            for r in store.query("SELECT unit_id, agent_key, mechs_json FROM rr_review_cells WHERE target_key = ?"
                                 " AND mechs_json IS NOT NULL", (target_key,))}


def _roster_domain(store: RiskStore, target_key: str) -> dict[str, str]:
    return {str(r["agent_key"]): str(r["domain"]) for r in store.query(
        "SELECT agent_key, domain FROM rr_roster WHERE target_key = ?", (target_key,))}


# ---------------------------------------------------------------- 유형 · 등급 · 우선순위
def issue_types(row: Mapping[str, Any], atoms: Sequence[Mapping[str, Any]], verdicts: Mapping[str, list[dict]],
                cell_mechs: Mapping[tuple[str, str], set[str]], *, min_opposers: int) -> tuple[list[str], list[dict]]:
    """(걸린 유형, 반대 측) — `row` 는 등록부 행(merged 를 푼 것), `atoms` 는 그 클러스터의 살아 있는 카드 대조 원자.

    반대 측은 같은 단위·겹치는 변경 참조에 applies=yes·OK 를 낸 제기자 밖의 전문가다(`held_fail` 의 반대 측). `split_verdict`
    의 반대자는 그 가운데 인용 대조를 지났고(quote_ok=1) 그 셀의 메커니즘 신고에 닻 메커니즘 코드가 있는 사람이다."""
    merged = row.get("merged") or {}
    claimed = merged.get("claimed") or {}
    raisers = {k for a in atoms for k in a["raisers"]}
    types: list[str] = []
    if any(a["judgement"] == "FAIL" or a["severity"] == "치명" for a in atoms):
        types.append("held_fail")
    sev3 = max(int(row.get("sev3") or 0), int(claimed.get("sev3") or 0))
    if _str(row.get("direction")) == "risk" and sev3 >= 2 and int(row.get("support_experts") or 0) == 1:
        types.append("solo_severe")
    opposers: dict[str, dict] = {}
    split: set[str] = set()
    code = f"{_str(row.get('mechanism'))}.{_str(row.get('mechanism_detail'))}"
    classified = bool(_str(row.get("mechanism"))) and _str(row.get("mechanism_detail")) not in ("", "unclassified")
    for atom in atoms:
        for verdict in verdicts.get(atom["unit_id"], ()):
            if verdict["agent_key"] in raisers or not (verdict["refs"] & atom["refs"]):
                continue
            entry = opposers.setdefault(verdict["agent_key"], {"agent_key": verdict["agent_key"],
                                                              "unit_ids": set(), "record_ids": set()})
            entry["unit_ids"].add(atom["unit_id"])
            entry["record_ids"].add(verdict["record_id"])
            if classified and verdict["quote_ok"] == 1 and code in cell_mechs.get((atom["unit_id"], verdict["agent_key"]),
                                                                               set()):
                split.add(verdict["agent_key"])
    if len(split) >= min_opposers:
        types.append("split_verdict")
    out = [{"agent_key": k, "unit_ids": sorted(v["unit_ids"]), "record_ids": sorted(v["record_ids"]),
            "split": k in split} for k, v in sorted(opposers.items())]
    return [t for t in ISSUE_TYPES if t in types], out


def p_class_of(row: Mapping[str, Any]) -> str:
    """P1 = 검증된 주장값 또는 등록부 FAIL·치명 · P2 = 검증 안 된 주장 FAIL·치명 또는 sev3 = 2 · P3 = 그 밖."""
    claimed = (row.get("merged") or {}).get("claimed") or {}
    if (int(claimed.get("verified_fail_experts") or 0) >= 1 or _str(row.get("judgement")) == "FAIL"
            or int(row.get("sev3") or 0) == 3):
        return "P1"
    if (_str(claimed.get("judgement")) == "FAIL" or _str(claimed.get("severity")) == "치명"
            or int(row.get("sev3") or 0) == 2):
        return "P2"
    return "P3"


def issue_priority(row: Mapping[str, Any], types: Sequence[str], n_opposers: int) -> float:
    """`max(sev3, claimed.sev3) × w_det × w_grade × max(TYPE_WEIGHT) × (1 + 0.1·min(반대자, 3))`(3.6)."""
    merged = row.get("merged") or {}
    sev3 = max(int(row.get("sev3") or 0), int((merged.get("claimed") or {}).get("sev3") or 0))
    w_det = float(merged.get("w_det") or 1.0)
    w_grade = registry.W_GRADE.get(_str(row.get("evidence_grade")), 0.6)
    weight = max((TYPE_WEIGHT[t] for t in types), default=1.0)
    return round(sev3 * w_det * w_grade * weight * (1 + 0.1 * min(n_opposers, 3)), 6)


def order_key(candidate: Mapping[str, Any]) -> tuple:
    """선정 순서 — (등급, −우선순위, 닻 키). 입력 순서와 무관하다."""
    return (P_ORDER[candidate["p_class"]], -float(candidate["priority"]), str(candidate["anchor_cluster_key"]))


def allocate_cap(ordered: Sequence[Mapping[str, Any]], *, cap: int, hard_cap: int, used_p1: int = 0,
                 used_other: int = 0) -> tuple[set[str], set[str]]:
    """(돌릴 닻, 상한 밖 닻) — P1 을 `hard_cap` 까지 먼저, P2·P3 은 누적 합계가 `cap` 에 닿을 때까지(#28).

    `used_*` 는 그 대상이 이미 돌린 쟁점 패널 수(등급별)다 — 다시 고른 회차도 같은 상한을 쓴다. 곧
    `n_run = min(P1, hard) + max(0, cap − min(P1, hard))` 로 막힌다(이미 돈 것을 빼고)."""
    run: set[str] = set()
    out: set[str] = set()
    p1 = [c for c in ordered if c["p_class"] == "P1"]
    rest = [c for c in ordered if c["p_class"] != "P1"]
    p1_room = max(0, hard_cap - used_p1)
    taken_p1 = p1[:p1_room]
    other_room = max(0, cap - (used_p1 + used_other + len(taken_p1)))
    for chosen, pool in ((taken_p1, p1), (rest[:other_room], rest)):
        keys = {str(c["anchor_cluster_key"]) for c in chosen}
        run |= keys
        out |= {str(c["anchor_cluster_key"]) for c in pool} - keys
    return run, out


def basis_hash_of(basis: Mapping[str, Any]) -> str:
    """제기자·반대자 집합과 주장값의 해시 — 바뀌면 끝난 쟁점을 다시 고른다(P-01 ⓐ)."""
    core = {"raisers": sorted(r["agent_key"] for r in basis.get("raisers") or ()),
            "opposers": sorted(o["agent_key"] for o in basis.get("opposers") or ()),
            "claimed": basis.get("claimed") or {}}
    return common.sha256_hex(common.canonical_json(core))[:16]


def basis_of(row: Mapping[str, Any], atoms: Mapping[str, Mapping[str, Any]], opposers: Sequence[Mapping[str, Any]],
             roster_domain: Mapping[str, str]) -> dict:
    """쟁점 근거 — {raisers[], opposers[], claimed{}, distribution{}, registry_before{}, refs[]}(편성 때 다시 얼린다)."""
    merged = row.get("merged") or {}
    raisers: dict[str, dict] = {}
    for fid, atom in sorted(atoms.items()):
        for key in atom["raisers"]:
            entry = raisers.setdefault(key, {"agent_key": key, "domain": roster_domain.get(key) or key.split("-", 1)[0],
                                             "finding_ids": [], "unit_ids": [], "record_ids": [],
                                             "judgement": atom["judgement"], "severity": atom["severity"],
                                             "verified": False, "grade": atom["grade"]})
            entry["finding_ids"].append(fid)
            entry["record_ids"] = sorted(set(entry["record_ids"]) | set(atom["cards"]))
            entry["verified"] = entry["verified"] or atom["verified"]
            if registry.W_GRADE.get(atom["grade"], 0.6) > registry.W_GRADE.get(entry["grade"], 0.6):
                entry["grade"] = atom["grade"]
            if atom["unit_id"] and atom["unit_id"] not in entry["unit_ids"]:
                entry["unit_ids"].append(atom["unit_id"])
            if registry.JUDGEMENT_ORDER.get(atom["judgement"], 1) > registry.JUDGEMENT_ORDER.get(entry["judgement"], 1):
                entry["judgement"] = atom["judgement"]
            if registry.SEVERITY_ORDER.get(atom["severity"], 1) > registry.SEVERITY_ORDER.get(entry["severity"], 1):
                entry["severity"] = atom["severity"]
    opp = [{**o, "domain": roster_domain.get(o["agent_key"]) or o["agent_key"].split("-", 1)[0]} for o in opposers]
    distribution = {**(merged.get("distribution") or {}), "opposers": len(opp)}
    return {"raisers": [raisers[k] for k in sorted(raisers)], "opposers": opp, "claimed": merged.get("claimed") or {},
            "distribution": distribution,
            "registry_before": {k: row.get(k) for k in ("severity", "sev3", "judgement", "evidence_grade", "priority",
                                                       "support_experts", "support_domains", "support_units",
                                                       "support_verified")},
            "refs": merged.get("cites") or []}


# ---------------------------------------------------------------- 후보 · 선정
def candidates(store: RiskStore, target_key: str, *, settings: Any = None) -> list[dict]:
    """쟁점 후보 — cells 대상의 리스크 행 가운데 코드가 상태를 쥔 것(사람이 닫은 행 제외)에서 유형이 하나라도 걸린 것."""
    cfg = settings or config.settings
    if registry.target_flow(store, target_key) != "cells":
        return []
    sources = {str(r["cluster_key"]): str(r["status_source"] or "code") for r in store.query(
        "SELECT cluster_key, status_source FROM rr_registry WHERE target_key = ?", (target_key,))}
    atoms = _card_atoms(store, target_key)
    verdicts = _ok_verdicts(store, target_key)
    cell_mechs = _cell_mechs(store, target_key)
    roster_domain = _roster_domain(store, target_key)
    owner = store.query_one("SELECT owner_sub FROM rr_targets WHERE target_key = ?", (target_key,))
    owner_sub = _str(owner["owner_sub"]) if owner is not None else ""
    out: list[dict] = []
    for row in registry.registry_rows(store, target_key):
        key = str(row["cluster_key"])
        if row["direction"] != "risk" or key.endswith(registry.IMPROVEMENT_SUFFIX) or sources.get(key, "code") != "code":
            continue
        members = {fid: atoms[fid] for fid in row["merged"].get("member_ids") or () if fid in atoms}
        types, opposers = issue_types(row, list(members.values()), verdicts, cell_mechs,
                                      min_opposers=int(cfg.risk_issue_split_min_opposers))
        if not types:
            continue
        anchor = registry.resolve_cluster_key(store, key, owner_sub=owner_sub)
        rep = members.get(_str(row["merged"].get("claim_finding_id")))
        unit_ids = sorted({a["unit_id"] for a in members.values() if a["unit_id"]}) or list(
            row["merged"].get("unit_ids") or ())
        basis = basis_of(row, members, opposers, roster_domain)
        out.append({"anchor_cluster_key": anchor, "types": types, "p_class": p_class_of(row),
                    "priority": issue_priority(row, types, len(opposers)),
                    "unit_id": (rep["unit_id"] if rep and rep["unit_id"] else (unit_ids[0] if unit_ids else None)),
                    "basis": basis, "basis_hash": basis_hash_of(basis), "owner_sub": _str(row.get("owner_sub"))})
    return sorted(out, key=order_key)


def cap_used(store: RiskStore, target_key: str) -> dict[str, int]:
    """그 대상이 돌린 쟁점 패널 — 끝난 쟁점 패널(`rr_panels.kind='issue'`, done)과 지금 편성·도는 쟁점, 등급별."""
    used = {"P1": 0, "other": 0}
    for row in store.query(
            "SELECT i.p_class AS p_class, COUNT(*) AS n FROM rr_panels p JOIN rr_issues i ON i.issue_id = p.issue_id"
            " WHERE p.target_key = ? AND p.kind = 'issue' AND p.status = 'done' GROUP BY i.p_class", (target_key,)):
        used["P1" if row["p_class"] == "P1" else "other"] += int(row["n"])
    for row in store.query(
            "SELECT i.p_class AS p_class, COUNT(*) AS n FROM rr_issues i WHERE i.target_key = ? AND i.state IN"
            f" ({','.join('?' for _ in IN_FLIGHT_STATES)}) AND NOT EXISTS (SELECT 1 FROM rr_panels p"
            " WHERE p.issue_id = i.issue_id AND p.id = i.panel_id AND p.status = 'done') GROUP BY i.p_class",
            (target_key, *IN_FLIGHT_STATES)):
        used["P1" if row["p_class"] == "P1" else "other"] += int(row["n"])
    return used


def select_issues(store: RiskStore, target_key: str, *, selected_round: int, settings: Any = None,
                  cells_hash: str | None = None) -> dict:
    """쟁점을 고른다(3.6) — 후보를 `rr_issues` 에 쓰고 상한 안은 `queued`, 밖은 `untried_cap(cap)`, 후보에서 빠진 대기 행은
    `withdrawn` 이다. 등록부 행의 `issue_id`·`issue_state` 를 같은 트랜잭션에서 맞춘다. 반환 {candidates, queued, untried_cap,
    withdrawn, reraised, by_type, by_class, cap{base, hard, used}}.

    건드리지 않는 것 — 편성·도는 쟁점, 사람이 정한 쟁점(`status_source='human'` — 올리기·건너뛰기, 상한 밖으로 올린 것도 그대로다,
    review1 L1), 근거가 그대로인 결과 쟁점. **패널이 결과를 낸 쟁점은 상한으로 밀려나지 않고 결과·패널을 잃지 않는다**(review1 H3) —
    근거가 바뀌면 결과를 두고 `reraised_json`(무엇이 언제 바뀌었나)을 적으며, 상한에 자리가 있을 때만 새 패널로 다시 줄을 선다(그
    패널의 결과가 옛 결과를 바꾼다). 자리가 없으면 결과 쟁점 그대로 남아 '패널 판정 — 근거 바뀜, 다시 토의 필요' 로 보인다."""
    cfg = settings or config.settings
    now = common.now_epoch()
    found = candidates(store, target_key, settings=cfg)
    with store.tx():
        existing = {str(r["anchor_cluster_key"]): dict(r) for r in store.query(
            "SELECT issue_id, anchor_cluster_key, state, basis_hash, basis_json, outcome, status_source, reraised_json"
            " FROM rr_issues WHERE target_key = ?", (target_key,))}
        pending: list[dict] = []
        for cand in found:
            row = existing.get(cand["anchor_cluster_key"])
            state = _str(row["state"]) if row else ""
            if row and (_str(row["status_source"]) == "human" or state in IN_FLIGHT_STATES or state == "skipped"):
                cand["action"] = "keep"
            elif row and row["outcome"] is not None:
                # 결과 쟁점 — 근거가 패널 때 근거로 돌아왔으면(또는 그대로면) 다시 토의 표기를 내리고 다시 줄 서지 않는다(조합 검토
                # L2 — 같은 패널을 또 돌리지 않는다). 다시 줄을 서 있으면 근거가 또 바뀌었을 때 새 근거만 다시 적고, 아니면 바뀐
                # 근거가 다시 토의 후보다(상한에 자리가 있을 때만 다시 돈다).
                panel_basis = (_loads(row["reraised_json"], {}) or {}).get("panel_basis_hash") or row["basis_hash"]
                if cand["basis_hash"] == panel_basis:
                    cand["action"] = "restore" if (row["reraised_json"] or state == "queued") else "keep"
                elif state == "queued":
                    cand["action"] = "refresh" if row["basis_hash"] != cand["basis_hash"] else "keep"
                else:
                    cand["action"] = "reraise"
                    pending.append(cand)
            elif state in DONE_STATES and row["basis_hash"] == cand["basis_hash"]:
                cand["action"] = "keep"
            else:
                cand["action"] = "allocate"
                pending.append(cand)
        used = cap_used(store, target_key)
        run, out = allocate_cap(pending, cap=int(cfg.risk_issue_panel_cap), hard_cap=int(cfg.risk_issue_panel_hard_cap),
                                used_p1=used["P1"], used_other=used["other"])
        reraised_n = 0
        for rank, cand in enumerate(found, start=1):
            anchor = cand["anchor_cluster_key"]
            if cand["action"] == "keep":
                store.execute("UPDATE rr_issues SET rank = ?, updated_at = ? WHERE target_key = ? AND anchor_cluster_key = ?",
                              (rank, now, target_key, anchor))
                continue
            if cand["action"] == "restore":
                store.execute(f"UPDATE rr_issues SET state = {_DONE_OF_OUTCOME}, rank = ?, basis_json = ?, basis_hash = ?,"
                              " reraised_json = NULL, updated_at = ? WHERE target_key = ? AND anchor_cluster_key = ?",
                              (rank, common.canonical_json(cand["basis"]), cand["basis_hash"], now, target_key, anchor))
                continue
            if cand["action"] in ("reraise", "refresh"):
                reraised_n += 1
                _reraise(store, target_key, existing[anchor], cand, rank=rank,
                         requeue=cand["action"] == "refresh" or anchor in run, selected_round=selected_round,
                         cells_hash=cells_hash, now=now)
                continue
            state, reason = ("queued", None) if anchor in run else ("untried_cap", CAP_REASON)
            _upsert(store, target_key, cand, rank=rank, state=state, reason=reason, selected_round=selected_round,
                    cells_hash=cells_hash, now=now)
        listed = {c["anchor_cluster_key"] for c in found}
        gone = [a for a, r in existing.items() if a not in listed and _str(r["status_source"]) != "human"
                and _str(r["state"]) in ("queued", "untried_cap")]
        for anchor in gone:
            if existing[anchor]["outcome"] is not None:
                # 다시 줄을 섰던 결과 쟁점이 후보에서 빠졌다 — 결과 쟁점으로 돌아간다(물러나지 않는다 — 결과를 잃지 않는다).
                store.execute(f"UPDATE rr_issues SET state = {_DONE_OF_OUTCOME}, rank = NULL, updated_at = ?"
                              " WHERE target_key = ? AND anchor_cluster_key = ?", (now, target_key, anchor))
                continue
            store.execute("UPDATE rr_issues SET state = 'withdrawn', state_reason = NULL, rank = NULL, updated_at = ?"
                          " WHERE target_key = ? AND anchor_cluster_key = ?", (now, target_key, anchor))
        _sync_registry(store, target_key)
    by_type: dict[str, int] = {}
    by_class: dict[str, int] = {}
    for cand in found:
        for t in cand["types"]:
            by_type[t] = by_type.get(t, 0) + 1
        by_class[cand["p_class"]] = by_class.get(cand["p_class"], 0) + 1
    return {"candidates": len(found), "queued": len(run), "untried_cap": len(out), "withdrawn": len(gone),
            "reraised": reraised_n, "by_type": by_type, "by_class": by_class,
            "cap": {"base": int(cfg.risk_issue_panel_cap), "hard": int(cfg.risk_issue_panel_hard_cap), "used": used}}


# 결과(outcome)가 있는 쟁점이 돌아갈 끝난 상태 — 판정 못 함(undetermined)은 inconclusive, 나머지는 resolved(SQL 식).
_DONE_OF_OUTCOME = "CASE WHEN outcome = 'undetermined' THEN 'inconclusive' ELSE 'resolved' END"


def _keys(entries: Iterable[Mapping[str, Any]] | None) -> set[str]:
    return {_str(e.get("agent_key")) for e in entries or () if isinstance(e, Mapping) and _str(e.get("agent_key"))}


def _reraise(store: RiskStore, target_key: str, row: Mapping[str, Any], cand: Mapping[str, Any], *, rank: int,
             requeue: bool, selected_round: int, cells_hash: str | None, now: int) -> None:
    """패널이 판정한 뒤 근거가 바뀐 쟁점(review1 H3) — 결과(outcome · outcome_json · panel_id)는 두고 `reraised_json` 에 패널 때의
    근거에서 무엇이 바뀌었나(제기자·반대자 들고 남, 주장값 앞뒤)와 언제(at · round)를 적는다. 같은 바뀐 근거면 처음 적은 시각을
    둔다. `requeue`(상한에 자리) 면 새 근거로 다시 줄을 서고(새 패널의 결과가 옛 결과를 바꾼다), 아니면 결과 쟁점 그대로다."""
    before = _loads(row["basis_json"], {}) or {}
    after = cand["basis"]
    old = _loads(row["reraised_json"], {}) or {}
    reraised = old if old.get("basis_hash") == cand["basis_hash"] else {
        "at": now, "round": int(selected_round), "basis_hash": cand["basis_hash"], "panel_basis_hash": row["basis_hash"],
        "raisers_added": sorted(_keys(after.get("raisers")) - _keys(before.get("raisers"))),
        "raisers_removed": sorted(_keys(before.get("raisers")) - _keys(after.get("raisers"))),
        "opposers_added": sorted(_keys(after.get("opposers")) - _keys(before.get("opposers"))),
        "opposers_removed": sorted(_keys(before.get("opposers")) - _keys(after.get("opposers"))),
        "claimed_before": before.get("claimed") or {}, "claimed_after": after.get("claimed") or {}}
    if requeue:
        store.execute(
            "UPDATE rr_issues SET state = 'queued', state_reason = 'reraised', rank = ?, types_json = ?, p_class = ?,"
            " priority = ?, unit_id = ?, basis_json = ?, basis_hash = ?, reraised_json = ?, selected_round = ?, cells_hash = ?,"
            " charged = 0, updated_at = ? WHERE issue_id = ?",
            (rank, common.canonical_json(list(cand["types"])), cand["p_class"], cand["priority"], cand["unit_id"],
             common.canonical_json(cand["basis"]), cand["basis_hash"], common.canonical_json(reraised), int(selected_round),
             cells_hash, now, row["issue_id"]))
        return
    store.execute(f"UPDATE rr_issues SET state = {_DONE_OF_OUTCOME}, rank = ?, reraised_json = ?, updated_at = ?"
                  " WHERE issue_id = ?", (rank, common.canonical_json(reraised), now, row["issue_id"]))


def _upsert(store: RiskStore, target_key: str, cand: Mapping[str, Any], *, rank: int, state: str, reason: str | None,
            selected_round: int, cells_hash: str | None, now: int) -> None:
    """후보 한 건을 대기·상한 밖으로 쓴다 — 같은 닻이면 같은 행(근거·우선순위를 새로 쓰고 결과 칸을 비운다)."""
    params = {"issue_id": issue_id_of(target_key, cand["anchor_cluster_key"]), "target_key": target_key,
              "owner_sub": cand["owner_sub"], "anchor": cand["anchor_cluster_key"], "unit_id": cand["unit_id"],
              "types": common.canonical_json(list(cand["types"])), "p_class": cand["p_class"],
              "priority": cand["priority"], "rank": rank, "basis": common.canonical_json(cand["basis"]),
              "basis_hash": cand["basis_hash"], "state": state, "reason": reason, "round": int(selected_round),
              "cells_hash": cells_hash, "now": now}
    store.execute(
        "INSERT INTO rr_issues (issue_id, target_key, owner_sub, anchor_cluster_key, unit_id, types_json, p_class, priority,"
        " rank, basis_json, basis_hash, state, state_reason, selected_round, cells_hash, created_at, updated_at)"
        " VALUES (:issue_id, :target_key, :owner_sub, :anchor, :unit_id, :types, :p_class, :priority, :rank, :basis,"
        " :basis_hash, :state, :reason, :round, :cells_hash, :now, :now)"
        " ON CONFLICT(issue_id) DO UPDATE SET unit_id = excluded.unit_id, types_json = excluded.types_json,"
        " p_class = excluded.p_class, priority = excluded.priority, rank = excluded.rank, basis_json = excluded.basis_json,"
        " basis_hash = excluded.basis_hash, state = excluded.state, state_reason = excluded.state_reason,"
        " outcome = NULL, outcome_json = NULL, panel_id = NULL, selected_round = excluded.selected_round,"
        " cells_hash = excluded.cells_hash, updated_at = excluded.updated_at", params)


def _sync_registry(store: RiskStore, target_key: str) -> None:
    """등록부 행의 issue_id·issue_state 를 쟁점 행에 맞춘다(병합이 다시 세는 값과 같다 — registry._apply_issue)."""
    for row in store.query("SELECT issue_id, anchor_cluster_key, state, outcome FROM rr_issues WHERE target_key = ?",
                           (target_key,)):
        store.execute("UPDATE rr_registry SET issue_id = ?, issue_state = ? WHERE target_key = ? AND cluster_key = ?",
                      (row["issue_id"], registry.issue_state_of(dict(row)), target_key, row["anchor_cluster_key"]))


def issue_rows(store: RiskStore, target_key: str, states: Iterable[str] | None = None) -> list[dict]:
    """대상의 쟁점 행(순위 순) — types·basis 를 푼다."""
    sql = ("SELECT issue_id, target_key, owner_sub, anchor_cluster_key, unit_id, types_json, p_class, priority, rank,"
           " basis_json, basis_hash, seats_json, state, state_reason, outcome, outcome_json, panel_id, attempts, charged,"
           " selected_round, cells_hash, reraised_json, status_source, created_at, updated_at FROM rr_issues"
           " WHERE target_key = ?")
    params: list[Any] = [target_key]
    picked = list(states or ())
    if picked:
        sql += f" AND state IN ({','.join('?' for _ in picked)})"
        params.extend(picked)
    sql += " ORDER BY rank IS NULL, rank, anchor_cluster_key"
    out = []
    for row in store.query(sql, params):
        item = dict(row)
        item["types"] = _loads(item.pop("types_json"), [])
        item["basis"] = _loads(item.pop("basis_json"), {})
        out.append(item)
    return out


# ================================================================ 쟁점 패널(S3-7) — 지금 심의 엔진의 작은 패널 하나(3라운드)
ISSUE_TIER = "I"                       # rr_panels.tier — 패널 Tier 문지기(FLOW_GATED_TIERS) 밖이다
ISSUE_ROUNDS = 3
SEATS_MIN, SEATS_MAX = 2, 5            # 로스터 좌석(기준선 옹호 지정석은 엔진이 더한다)
RAISER_SEATS, COUNTER_SEATS = 2, 2
QUESTION_MAX = 600
ISSUES_MODE = "issues"
# 쟁점 패널 결과를 그 쟁점에 앉히지 않는 상태(사람이 넘긴 것·후보에서 빠진 것) — 늦게 온 결과가 사람의 결정을 덮지 않는다.
_UNRESOLVABLE_STATES: tuple[str, ...] = ("skipped", "withdrawn")


class PlanConflict(Exception):
    """편성 경합 — 같은 쟁점을 두 편성이 동시에 planned 로 옮기려 했다(한 트랜잭션의 rowcount 가 1 이 아니다)."""


def _mech_label(code: str) -> str:
    from app import taxonomy  # noqa: PLC0415 — 자산 읽기는 쓸 때만.

    for row in (taxonomy.load_taxonomy().get("axes") or {}).get("mechanism") or ():
        if str(row.get("code")) == code:
            return str(row.get("label") or code)
    return code


def anchor_row(store: RiskStore, target_key: str, anchor: str) -> dict | None:
    """닻 클러스터의 등록부 행(merged 를 푼 것)."""
    for row in registry.registry_rows(store, target_key):
        if row["cluster_key"] == anchor:
            return row
    return None


def yield_advice(store: RiskStore, target_key: str) -> str | None:
    """최근 다섯 쟁점 패널(끝난 것 — 늦게 끝난 차례)이 전부 기각(rejected)·불명(undetermined · 결정문 파싱 실패)이면
    `issue_yield_low`, 아니면 None. 다섯이 안 되면 None 이다. 수확 체감 정지(_diminishing)는 쟁점 패널에 걸지 않는다 — 알림만이다."""
    rows = store.query("SELECT id, issue_id, risk_spec_parsed FROM rr_panels WHERE target_key = ? AND kind = 'issue'"
                       " AND status = 'done' ORDER BY COALESCE(ended_at, 0) DESC, panel_no DESC LIMIT ?",
                       (target_key, YIELD_WINDOW))
    if len(rows) < YIELD_WINDOW:
        return None
    for row in rows:
        if not row["risk_spec_parsed"]:
            continue                                   # 결정문을 못 읽었다 — 그 패널은 불명이다
        issue = store.query_one("SELECT outcome, outcome_json FROM rr_issues WHERE issue_id = ?", (row["issue_id"],))
        decided = issue is not None and _loads(issue["outcome_json"], {}).get("panel_id") == row["id"]
        if not (decided and _str(issue["outcome"]) in YIELD_LOW_OUTCOMES):
            return None
    return YIELD_LOW_ADVICE


def create_issues_job(store: RiskStore, target_key: str, *, owner_sub: str, requester_sub: str | None = None,
                      consent_source: str | None = "web", user_memo: str | None = None, settings: Any = None,
                      chain: Mapping[str, Any] | None = None) -> dict:
    """쟁점 잡(`rr_jobs.mode='issues'`, tier NULL) — 대기 쟁점을 패널 러너가 한 줄로 돈다(3.7). 자격이 없어도 행을 만든다 —
    `error='pat_unavailable: …'` 를 적고 집는 쪽이 지금처럼 자격 없는 잡을 건너뛴다(자격 검사로 행을 만들지 않는 일이 없다)."""
    from app import runner  # noqa: PLC0415 — runner 는 이 모듈을 쓴다.

    cfg = settings or config.settings
    credential, note = runner.resolve_credential_with_note(store, cfg, owner_sub, requester_sub)
    queued = store.query_one("SELECT COUNT(*) AS n FROM rr_issues WHERE target_key = ? AND state = 'queued'",
                             (target_key,))
    job_id = common.new_uuid()
    now = common.now_epoch()
    params = {"mode": ISSUES_MODE, "requester": requester_sub, "consent": True, "consent_source": consent_source,
              "user_memo": user_memo or None, "credential": credential["kind"] if credential else None}
    error = None if credential else "pat_unavailable" + (f": {note}" if note else "")
    store.execute(
        "INSERT INTO rr_jobs(id, target_key, owner_sub, tier, state, concurrency, params_json, credential_email,"
        " panels_done, panels_total, error, mode, chain_json, created_at, updated_at)"
        " VALUES (?, ?, ?, NULL, 'queued', 1, ?, ?, 0, ?, ?, ?, ?, ?, ?)",
        (job_id, target_key, owner_sub, common.canonical_json(params), (credential or {}).get("email"),
         int(queued["n"] or 0), error, ISSUES_MODE, common.canonical_json(dict(chain)) if chain else None, now, now))
    return {"job_id": job_id, "issues_queued": int(queued["n"] or 0), "credential": params["credential"],
            **({"error": error} if error else {})}


def _seat_order(entry: Mapping[str, Any], ranks: Mapping[str, int]) -> tuple:
    """제기·반대 석의 차례 — 인용 대조를 지난 사람 → 근거 등급 → rank_in_domain → 키."""
    return (0 if entry.get("verified") or entry.get("split") else 1,
            -registry.W_GRADE.get(_str(entry.get("grade")), 0.6), ranks.get(entry["agent_key"], 99), entry["agent_key"])


def _pick_spread(entries: Sequence[Mapping[str, Any]], n: int, taken_domains: set[str]) -> list[dict]:
    """차례대로 n 명 — 영역이 다르면 다른 영역을 먼저(이미 앉은 영역은 뒤로)."""
    out: list[dict] = []
    pool = list(entries)
    while pool and len(out) < n:
        fresh = [e for e in pool if e["domain"] not in taken_domains]
        pick = (fresh or pool)[0]
        pool.remove(pick)
        out.append(dict(pick))
        taken_domains.add(pick["domain"])
    return out


def seats_for(store: RiskStore, target_key: str, issue: Mapping[str, Any]) -> list[dict]:
    """쟁점 패널의 로스터 좌석(2~5) — 제기 1~2 · 반대 0~2 · 반대가 없으면 인접 1~2. 한 줄은
    `{key, domain, origin, rank_in_domain, issue_role}`(제기 primary · 반대·인접 counter — rr_seat_opinions.origin CHECK 안)."""
    from app import taxonomy  # noqa: PLC0415

    roster = {str(r["agent_key"]): dict(r) for r in store.query(
        "SELECT agent_key, domain, rank_in_domain FROM rr_roster WHERE target_key = ? ORDER BY agent_key", (target_key,))}
    ranks = {k: int(v["rank_in_domain"] or 99) for k, v in roster.items()}
    basis = issue.get("basis") or {}

    def entry(item: Mapping[str, Any]) -> dict:
        key = str(item["agent_key"])
        return {**dict(item), "domain": _str((roster.get(key) or {}).get("domain")) or key.split("-", 1)[0]}

    raisers = sorted((entry(r) for r in basis.get("raisers") or () if r["agent_key"] in roster),
                     key=lambda e: _seat_order(e, ranks))
    opposers = sorted((entry(o) for o in basis.get("opposers") or () if o["agent_key"] in roster),
                      key=lambda e: _seat_order(e, ranks))
    taken: set[str] = set()
    seats = [{**e, "issue_role": "raiser"} for e in _pick_spread(raisers, RAISER_SEATS, taken)]
    seats += [{**e, "issue_role": "opposer"} for e in _pick_spread(opposers, COUNTER_SEATS, taken)]
    if not opposers:
        seats += [{**e, "issue_role": "adjacent"}
                  for e in _adjacent(store, target_key, issue, roster, ranks, {s["agent_key"] for s in seats},
                                     {s["domain"] for s in seats if s["issue_role"] == "raiser"}, taxonomy)]
    seats = seats[:SEATS_MAX]
    return [{"key": s["agent_key"], "domain": s["domain"], "origin": "primary" if s["issue_role"] == "raiser" else "counter",
             "rank_in_domain": ranks.get(s["agent_key"], 99), "issue_role": s["issue_role"]} for s in seats]


def _adjacent(store: RiskStore, target_key: str, issue: Mapping[str, Any], roster: Mapping[str, dict],
              ranks: Mapping[str, int], seated: set[str], raiser_domains: set[str], taxonomy: Any) -> list[dict]:
    """인접 석 1~2 — 닻 메커니즘의 배정표 소유 ∪ 관련 영역 가운데 제기 석과 다른 영역에서, 그 단위 셀이 reviewed 이고 applies=yes
    판정이 많은 사람. 없으면 그 단위를 본(reviewed) 다른 영역 사람, 그래도 없으면 로스터 차례(좌석 하한 2)."""
    anchor = anchor_row(store, target_key, str(issue["anchor_cluster_key"])) or {}
    code = f"{_str(anchor.get('mechanism'))}.{_str(anchor.get('mechanism_detail'))}"
    owners = taxonomy.mech_owners().get(code) or {"owners": (), "related": ()}
    wanted = set(owners["owners"]) | set(owners["related"])
    reviewed = {str(r["agent_key"]): int(r["n"]) for r in store.query(
        "SELECT c.agent_key AS agent_key, COUNT(v.record_id) AS n FROM rr_review_cells c LEFT JOIN rr_card_verdicts v"
        " ON v.target_key = c.target_key AND v.unit_id = c.unit_id AND v.agent_key = c.agent_key AND v.is_effective = 1"
        " AND v.applies = 'yes' WHERE c.target_key = ? AND c.unit_id = ? AND c.state = 'reviewed' GROUP BY c.agent_key",
        (target_key, _str(issue.get("unit_id"))))}
    pool = [k for k in roster if k not in seated and roster[k]["domain"] not in raiser_domains]

    def ordered(keys: Iterable[str]) -> list[str]:
        return sorted(keys, key=lambda k: (-reviewed.get(k, -1), ranks.get(k, 99), k))

    first = ordered(k for k in pool if k in reviewed and roster[k]["domain"] in wanted)
    second = ordered(k for k in pool if k in reviewed and k not in first)
    need = max(1, SEATS_MIN - len(seated))
    picked = (first + second)[:2] or ordered(k for k in roster if k not in seated)[:need]
    return [{"agent_key": k, "domain": roster[k]["domain"]} for k in picked]


def part_names(store: RiskStore, anchor: Mapping[str, Any], limit: int = 4) -> list[str]:
    """닻의 부품 이름 — 등록부가 모은 이름(merged.names), 없으면 주체 ckey 의 표시 이름(rr_part_keys.display_name · 첫 별칭)."""
    names = [str(n) for n in (anchor.get("merged") or {}).get("names") or () if n]
    if names:
        return names[:limit]
    out: list[str] = []
    for ckey in [c for c in _str(anchor.get("subject_key")).split("|") if c][:limit]:
        row = store.query_one("SELECT display_name, aliases_json FROM rr_part_keys WHERE ckey = ?", (ckey,))
        aliases = _loads(row["aliases_json"], []) if row is not None else []
        label = next((_str(a.get("label")) for a in aliases if isinstance(a, Mapping) and _str(a.get("label"))), "")
        out.append(_str(row["display_name"]) if row is not None and row["display_name"] else (label or ckey))
    return out


def issue_question(store: RiskStore, issue: Mapping[str, Any]) -> str:
    """쟁점 패널의 질문(600자 안) — 부품 이름·변경 종류·메커니즘 이름과, finding 의 네 필드를 [근거] I1 의 값 그대로 쓰라는 말."""
    anchor = anchor_row(store, str(issue["target_key"]), str(issue["anchor_cluster_key"])) or {}
    code = f"{_str(anchor.get('mechanism'))}.{_str(anchor.get('mechanism_detail'))}"
    names = part_names(store, anchor) or [_str(anchor.get("subject_key"))]
    head = (f"[쟁점 {issue['issue_id']} · {', '.join(issue.get('types') or ())}] 부품 {', '.join(names)} 의"
            f" {_str(anchor.get('change_kind')) or '변경'} 변경에서 메커니즘 {_mech_label(code)}({code}) 이 성립하는가.")
    tail = (" 결정문의 finding 은 mechanism·mechanism_detail·subject·change_kind 네 필드를 [근거] I1 의 값 그대로 쓰고,"
            " 심각도·판정을 다시 정한다.")
    return (head[:QUESTION_MAX - len(tail)] + tail)[:QUESTION_MAX]


def plan_issue_panel(store: RiskStore, target_key: str, *, job: Mapping[str, Any], settings: Any = None) -> dict | None:
    """다음 대기 쟁점(순위 순) 하나의 패널을 편성한다 — 한 트랜잭션에서 rr_panels(kind='issue'·tier 'I'·issue_id) INSERT 와
    rr_issues 를 queued → planned 로(rowcount 1 일 때만). 좌석 원장(rr_coverage)은 건드리지 않는다. 대기 쟁점이 없으면 None.

    **바깥 트랜잭션 안에서 부르지 마라**(planner.plan_next_panel 과 같다 — 경합 롤백이 바깥 커밋에 섞인다)."""
    from app import planner  # noqa: PLC0415

    rows = issue_rows(store, target_key, ("queued",))
    if not rows:
        return None
    issue = rows[0]
    seats = seats_for(store, target_key, issue)
    target = store.query_one("SELECT owner_sub FROM rr_targets WHERE target_key = ?", (target_key,))
    panel_id = common.new_uuid()
    now = common.now_epoch()
    mods = list(planner.DEFAULT_MODIFIERS)
    budget = {"rounds_planned": ISSUE_ROUNDS, "tools_planned": [], "issue_id": issue["issue_id"]}
    seats_json = common.canonical_json(seats)
    try:
        with store.tx() as conn:
            row = conn.execute("SELECT COALESCE(MAX(panel_no), 0) + 1 AS next_no FROM rr_panels WHERE target_key = ?",
                               (target_key,)).fetchone()
            panel_no = int(row["next_no"])
            conn.execute(
                "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, tier, seats_json, chair_template,"
                " modifiers_json, rounds, engine, tool_mode, status, budget_json, llm_calls_planned, kind, issue_id,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'web', 'tools', 'planned', ?, ?, 'issue', ?, ?)",
                (panel_id, target_key, target["owner_sub"], panel_no, ISSUE_TIER, seats_json, planner.CHAIR_TEMPLATE,
                 common.canonical_json(mods), ISSUE_ROUNDS, common.canonical_json(budget),
                 (len(seats) + 1) * ISSUE_ROUNDS + 3, issue["issue_id"], now))
            cur = conn.execute(
                "UPDATE rr_issues SET state = 'planned', state_reason = NULL, panel_id = ?, seats_json = ?,"
                " attempts = attempts + 1, updated_at = ? WHERE issue_id = ? AND state = 'queued'",
                (panel_id, seats_json, now, issue["issue_id"]))
            if cur.rowcount != 1:
                raise PlanConflict(issue["issue_id"])
            _sync_registry(store, target_key)
    except PlanConflict:
        return None
    return {"id": panel_id, "target_key": target_key, "owner_sub": target["owner_sub"], "panel_no": panel_no,
            "tier": ISSUE_TIER, "kind": "issue", "issue_id": issue["issue_id"], "issue": issue, "seats": seats,
            "seats_json": seats_json, "modifiers": mods, "rounds": ISSUE_ROUNDS, "tools": [], "budget": budget,
            "status": "planned", "created_at": now}


def start_issue_panel(store: RiskStore, panel_id: str) -> None:
    """planned → running(패널·쟁점). 좌석 원장은 건드리지 않는다."""
    now = common.now_epoch()
    with store.tx():
        store.execute("UPDATE rr_panels SET status = 'running', started_at = ? WHERE id = ?", (now, panel_id))
        store.execute("UPDATE rr_issues SET state = 'running', updated_at = ? WHERE panel_id = ? AND state = 'planned'",
                      (now, panel_id))
        row = store.query_one("SELECT target_key FROM rr_panels WHERE id = ?", (panel_id,))
        if row is not None:
            _sync_registry(store, str(row["target_key"]))


LIVE_JOB_STATES: tuple[str, ...] = ("queued", "running", "paused")


def _orphan_reason(store: RiskStore, target_key: str) -> str | None:
    """그 대상에 살아 있는 쟁점 잡이 없으면 놓인 쟁점이 갈 까닭 — 마지막 쟁점 잡이 취소(중)면 chain_cancelled, 그 밖(실패)은
    job_failed. 살아 있는 잡이 있으면 None(그 잡이 다시 집는다)."""
    live = store.query_one(f"SELECT 1 FROM rr_jobs WHERE target_key = ? AND mode = ? AND state IN"
                           f" ({','.join('?' * len(LIVE_JOB_STATES))}) LIMIT 1", (target_key, ISSUES_MODE, *LIVE_JOB_STATES))
    if live is not None:
        return None
    last = store.query_one("SELECT state FROM rr_jobs WHERE target_key = ? AND mode = ? ORDER BY created_at DESC, rowid DESC"
                           " LIMIT 1", (target_key, ISSUES_MODE))
    return "job_failed" if last is not None and _str(last["state"]) == "failed" else "chain_cancelled"


def release_issue(store: RiskStore, panel_id: str, *, charge: bool, reason: str | None = None,
                  settings: Any = None) -> dict | None:
    """패널이 결과 없이 닫혔다 — 그 쟁점(지금 패널이 이 패널인 것만)을 대기로 되돌린다. `charge` 면 내용 탓(charged + 1)이고
    한도(HWAXRISK_ISSUE_MAX_CHARGED)에 닿으면 `inconclusive(reason)` 다. 패널 id 는 남긴다 — 그 패널을 고쳐 다시 내면
    `resolve_issue` 가 이 쟁점에 결과를 앉힌다(다시 편성되면 패널 id 가 바뀌어 옛 패널은 덮지 못한다).

    그 대상에 살아 있는 쟁점 잡이 없으면(사람이 잡을 취소하는 사이 닫힌 패널 — review1 H4) 대기로 두지 않는다 — 집을 잡이 없어
    영영 '쟁점 진행' 으로 남는다. `untry_queued` 와 같은 길로 놓는다(chain_cancelled · job_failed). 앞 패널의 결과가 있는 쟁점은
    결과를 잃지 않는다(review1 H3 — 판정 못 함으로 끝날 때만 결과가 바뀐다)."""
    cfg = settings or config.settings
    row = store.query_one("SELECT issue_id, target_key, state, charged, outcome, reraised_json FROM rr_issues"
                          " WHERE panel_id = ?", (panel_id,))
    if row is None or _str(row["state"]) not in IN_FLIGHT_STATES:
        return None
    target_key = str(row["target_key"])
    charged = int(row["charged"] or 0) + (1 if charge else 0)
    state = "inconclusive" if charge and charged >= int(cfg.risk_issue_max_charged) else "queued"
    now = common.now_epoch()
    with store.tx():
        if state == "inconclusive" and _str(row["outcome"]) in PANEL_VERDICTS:
            state = _keep_verdict(store, row, panel_id, reason or "charged", charged, now)
            _sync_registry(store, target_key)
            return {"issue_id": row["issue_id"], "state": state, "charged": charged}
        store.execute("UPDATE rr_issues SET state = ?, state_reason = ?, outcome = CASE WHEN ? = 'inconclusive' THEN"
                      " 'undetermined' ELSE outcome END, charged = ?, updated_at = ? WHERE issue_id = ?",
                      (state, reason if charge or state != "queued" else None, state, charged, now, row["issue_id"]))
        orphan = _orphan_reason(store, target_key) if state == "queued" else None
        if orphan is not None:
            _untry(store, "issue_id = ?", (row["issue_id"],), orphan)
            state = _str(store.query_one("SELECT state FROM rr_issues WHERE issue_id = ?", (row["issue_id"],))["state"])
        _sync_registry(store, target_key)
    return {"issue_id": row["issue_id"], "state": state, "charged": charged}


# 패널이 낸 판정 — 다시 줄을 선 결과 쟁점은 새 패널이 이 가운데 하나를 낼 때까지 옛 판정을 둔다(조합 검토 M2 — D-52).
PANEL_VERDICTS: tuple[str, ...] = ("upheld", "downgraded", "escalated", "rejected")


def _keep_verdict(store: RiskStore, issue: Mapping[str, Any], panel_id: str, reason: str, charged: int, now: int) -> str:
    """새 패널이 결정하지 못했다(읽을 수 없는 결정문 한도 · 판정 못 함 · 닻 원자 없음) — 옛 판정(outcome · outcome_json)을 둔 채
    결과 쟁점으로 돌아가고, 다시 토의 표기(reraised_json)에 new_panel_failed 를 단다 — '패널 판정 — 근거 바뀜, 다시 토의 필요(새 패널
    결정 못 함)' 로 보인다. 표기는 새 패널이 결정하거나 근거가 패널 때로 돌아올 때만 내려간다."""
    reraised = _loads(issue["reraised_json"], {}) or {}
    reraised["new_panel_failed"] = {"panel_id": panel_id, "reason": reason, "at": now}
    store.execute(f"UPDATE rr_issues SET state = {_DONE_OF_OUTCOME}, reraised_json = ?, charged = ?, updated_at = ?"
                  " WHERE issue_id = ?", (common.canonical_json(reraised), charged, now, issue["issue_id"]))
    return "resolved"


def _untry(store: RiskStore, where: str, params: tuple, reason: str) -> int:
    """대기 쟁점을 놓는다 — 결과가 없으면 `untried_cap(reason)`(보고서 '미토의'), 앞 패널의 결과가 있으면(다시 줄을 섰던 결과 쟁점)
    그 결과 쟁점으로 돌아간다(review1 H3 — 결과를 잃지 않는다)."""
    return int(store.execute(
        f"UPDATE rr_issues SET state = CASE WHEN outcome IS NULL THEN 'untried_cap' ELSE {_DONE_OF_OUTCOME} END,"
        " state_reason = CASE WHEN outcome IS NULL THEN ? ELSE state_reason END, updated_at = ?"
        f" WHERE state = 'queued' AND {where}", (reason, common.now_epoch(), *params)) or 0)


def untry_queued(store: RiskStore, target_key: str, reason: str) -> int:
    """남은 대기 쟁점을 놓는다(`_untry`) — 쟁점 잡이 연속 오류로 실패했거나(engine_fail) 다른 까닭으로 실패했거나(job_failed) 사람이
    취소했을 때(chain_cancelled)다. 지우지 않는다(보고서 '미토의' 행). 사람이 상한 밖으로 올린 쟁점도 같은 길이다."""
    with store.tx():
        n = _untry(store, "target_key = ?", (target_key,), reason)
        _sync_registry(store, target_key)
    return n


def _panel_atoms(store: RiskStore, panel_id: str) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT finding_id, cluster_key, direction, status, severity, sev3, judgement, evidence_grade, finding_json"
        " FROM rr_findings WHERE panel_id = ? AND source_kind = ? ORDER BY finding_id", (panel_id, registry.ISSUE_PANEL_SOURCE))]


def resolve_issue(store: RiskStore, panel_id: str, *, settings: Any = None) -> dict:
    """쟁점 패널의 결과로 쟁점을 정한다(3.6 결과 어휘) — 반환 {issue_id, state, outcome, stale?}.

    `rr_issues.panel_id` 가 이 패널이 아니면(늦게 끝난 옛 패널·재제출) 쟁점을 건드리지 않는다(P-17-5). 결정문을 파싱하지 못했으면
    내용 탓 하나(한도면 `inconclusive(spec_parse_failed)`). 닻(닻 맞춤으로 붙은 것 포함) 원자가 없으면 `inconclusive`·
    `undetermined(no_matching_atom)`, 전부 기각이거나 개선뿐이면 `resolved`·`rejected`. 살아 있는 리스크 원자 가운데 sev3 가 가장
    큰 것이 주장값 최댓값(없으면 등록부 값)보다 낮으면 `downgraded`, 같으면 `upheld`, 높으면 `escalated`, 판정이 undetermined 면
    `inconclusive`. 등록부 덮어쓰기는 병합이 한다(registry._apply_issue)."""
    cfg = settings or config.settings
    panel = store.query_one("SELECT id, target_key, issue_id, risk_spec_parsed, status FROM rr_panels WHERE id = ?",
                            (panel_id,))
    if panel is None or not panel["issue_id"]:
        return {"issue_id": None, "state": None, "outcome": None}
    issue = store.query_one("SELECT issue_id, target_key, owner_sub, anchor_cluster_key, state, panel_id, charged, basis_json,"
                            " outcome, outcome_json, reraised_json FROM rr_issues WHERE issue_id = ?", (panel["issue_id"],))
    if issue is None:
        return {"issue_id": panel["issue_id"], "state": None, "outcome": None}
    if _str(issue["panel_id"]) != panel_id or _str(issue["state"]) in _UNRESOLVABLE_STATES:
        return {"issue_id": issue["issue_id"], "state": issue["state"], "outcome": None, "stale": True}
    if issue["reraised_json"] and _str((_loads(issue["outcome_json"], {}) or {}).get("panel_id")) == panel_id:
        # 다시 토의를 기다리는 쟁점에 지금 판정을 낸 그 옛 패널을 다시 냈다 — 새 패널의 결정이 아니다. 표기를 내리거나 대기에서 빼거나
        # 옛 판정을 새 근거에 붙이지 않는다(조합 검토 L1).
        return {"issue_id": issue["issue_id"], "state": issue["state"], "outcome": None, "stale": True}
    target_key = str(issue["target_key"])
    now = common.now_epoch()
    verdict = _str(issue["outcome"]) in PANEL_VERDICTS
    if not panel["risk_spec_parsed"]:
        charged = int(issue["charged"] or 0) + 1
        state = "inconclusive" if charged >= int(cfg.risk_issue_max_charged) else "queued"
        with store.tx():
            if state == "inconclusive" and verdict:
                state = _keep_verdict(store, issue, panel_id, "spec_parse_failed", charged, now)
                _sync_registry(store, target_key)
                return {"issue_id": issue["issue_id"], "state": state, "outcome": issue["outcome"]}
            # 앞 패널의 결과가 있으면(다시 줄을 선 결과 쟁점) 대기로 돌아갈 때 그 결과를 둔다(review1 H3).
            store.execute("UPDATE rr_issues SET state = ?, state_reason = 'spec_parse_failed', outcome = CASE WHEN ?"
                          " = 'inconclusive' THEN 'undetermined' ELSE outcome END, charged = ?, updated_at = ? WHERE issue_id = ?",
                          (state, state, charged, now, issue["issue_id"]))
            # 살아 있는 쟁점 잡이 없으면 대기로 두지 않는다 — 집을 잡이 없어 영영 '쟁점 진행' 으로 남는다(조합 검토 M1, release_issue 와
            # 같은 길).
            orphan = _orphan_reason(store, target_key) if state == "queued" else None
            if orphan is not None:
                _untry(store, "issue_id = ?", (issue["issue_id"],), orphan)
                state = _str(store.query_one("SELECT state FROM rr_issues WHERE issue_id = ?", (issue["issue_id"],))["state"])
            _sync_registry(store, target_key)
        return {"issue_id": issue["issue_id"], "state": state, "outcome": "undetermined" if state == "inconclusive" else None}
    anchor = str(issue["anchor_cluster_key"])
    atoms = [a for a in _panel_atoms(store, panel_id)
             if registry.resolve_cluster_key(store, _str(a["cluster_key"]), owner_sub=_str(issue["owner_sub"])) == anchor]
    basis = _loads(issue["basis_json"], {})
    claimed = basis.get("claimed") or {}
    before = basis.get("registry_before") or {}
    base_sev3 = int(claimed.get("sev3") or before.get("sev3") or 0)
    live = [a for a in atoms if _str(a["status"]) != "rejected_in_panel"]
    risk = [a for a in live if _str(a["direction"]) != "improvement"]
    reason = None
    if not atoms:
        state, outcome, reason = "inconclusive", "undetermined", "no_matching_atom"
    elif not risk:
        state, outcome = "resolved", "rejected"
    else:
        atom = max(risk, key=lambda a: (int(a["sev3"] or 0), registry.JUDGEMENT_ORDER.get(_str(a["judgement"]), 0),
                                        _str(a["finding_id"])))
        if _str(atom["judgement"]) == "undetermined":
            state, outcome, reason = "inconclusive", "undetermined", "no_decision"
        else:
            sev3 = int(atom["sev3"] or 0)
            state = "resolved"
            outcome = "downgraded" if sev3 < base_sev3 else ("escalated" if sev3 > base_sev3 else "upheld")
    if outcome == "undetermined" and verdict:
        # 새 패널이 결정하지 못했다(닻 원자 없음 · 판정 못 함) — 옛 판정을 둔다(조합 검토 M2).
        with store.tx():
            state = _keep_verdict(store, issue, panel_id, reason or "no_decision", int(issue["charged"] or 0), now)
            _sync_registry(store, target_key)
        return {"issue_id": issue["issue_id"], "state": state, "outcome": issue["outcome"]}
    # 결과 칸의 원자는 결과·등록부(registry._apply_issue)와 같은 원자다 — (sev3, 판정, finding id). 종전에는 (sev3, finding id) 로
    # 골라 같은 심각도의 OK·FAIL 원자가 섞이면 보고서 줄이 등록부와 어긋났다(review1 M2).
    chosen = atom if risk else None
    outcome_json = {"panel_id": panel_id, "atom_finding_ids": [str(a["finding_id"]) for a in atoms],
                    "severity_after": _str(chosen["severity"]) if chosen else None,
                    "judgement_after": _str(chosen["judgement"]) if chosen else None,
                    "grade_after": _str(chosen["evidence_grade"]) if chosen else None,
                    "contest_note": next((_str(_loads(a["finding_json"], {}).get("contest_note")) for a in atoms
                                          if _str(_loads(a["finding_json"], {}).get("contest_note"))), "")}
    with store.tx():
        # 새 결과가 옛 결과를 바꾼다 — 다시 토의 표기(reraised_json)는 내리고, 사람의 올리기는 그 패널로 끝났다(이제 코드 상태다).
        store.execute("UPDATE rr_issues SET state = ?, state_reason = ?, outcome = ?, outcome_json = ?, reraised_json = NULL,"
                      " status_source = 'code', updated_at = ? WHERE issue_id = ?",
                      (state, reason, outcome, common.canonical_json(outcome_json), now, issue["issue_id"]))
        _sync_registry(store, target_key)
    return {"issue_id": issue["issue_id"], "state": state, "outcome": outcome}
