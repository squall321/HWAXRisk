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
            "SELECT finding_id, agent_key, unit_id, status, judgement, severity, finding_json FROM rr_findings"
            " WHERE target_key = ? AND source_kind = ? AND COALESCE(status, 'open') <> 'rejected_in_panel'"
            " AND COALESCE(origin, 'llm') <> 'human'", (target_key, registry.CARD_REVIEW_SOURCE)):
        fj = _loads(row["finding_json"], {})
        raisers = [_str(k) for k in fj.get("raised_by") or () if _str(k)] or [_str(row["agent_key"])]
        out[str(row["finding_id"])] = {
            "agent_key": _str(row["agent_key"]), "unit_id": _str(row["unit_id"]), "refs": _change_refs(fj),
            "judgement": _str(fj.get("judgement_claimed")) or _str(row["judgement"]),
            "severity": _str(fj.get("severity_claimed")) or _str(row["severity"]),
            "raisers": raisers}
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
                                             "finding_ids": [], "unit_ids": [], "judgement": atom["judgement"],
                                             "severity": atom["severity"]})
            entry["finding_ids"].append(fid)
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
        anchor = registry.resolve_cluster_key(store, key)
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
    `withdrawn` 이다. 편성·도는 쟁점과 사람이 넘긴 쟁점은 건드리지 않고, 끝난 쟁점은 근거 해시가 바뀌었을 때만 다시 대기로 간다.
    등록부 행의 `issue_id`·`issue_state` 를 같은 트랜잭션에서 맞춘다. 반환 {candidates, queued, untried_cap, withdrawn,
    by_type, by_class, cap{base, hard, used}}."""
    cfg = settings or config.settings
    now = common.now_epoch()
    found = candidates(store, target_key, settings=cfg)
    with store.tx():
        existing = {str(r["anchor_cluster_key"]): dict(r) for r in store.query(
            "SELECT issue_id, anchor_cluster_key, state, basis_hash FROM rr_issues WHERE target_key = ?", (target_key,))}
        pending: list[dict] = []
        for cand in found:
            row = existing.get(cand["anchor_cluster_key"])
            state = _str(row["state"]) if row else ""
            if state in IN_FLIGHT_STATES or state == "skipped":
                cand["action"] = "keep"
            elif state in DONE_STATES and row["basis_hash"] == cand["basis_hash"]:
                cand["action"] = "keep"
            else:
                cand["action"] = "allocate"
                pending.append(cand)
        used = cap_used(store, target_key)
        run, out = allocate_cap(pending, cap=int(cfg.risk_issue_panel_cap), hard_cap=int(cfg.risk_issue_panel_hard_cap),
                                used_p1=used["P1"], used_other=used["other"])
        for rank, cand in enumerate(found, start=1):
            anchor = cand["anchor_cluster_key"]
            if cand["action"] == "keep":
                store.execute("UPDATE rr_issues SET rank = ?, updated_at = ? WHERE target_key = ? AND anchor_cluster_key = ?",
                              (rank, now, target_key, anchor))
                continue
            state, reason = ("queued", None) if anchor in run else ("untried_cap", CAP_REASON)
            _upsert(store, target_key, cand, rank=rank, state=state, reason=reason, selected_round=selected_round,
                    cells_hash=cells_hash, now=now)
        gone = [a for a, r in existing.items() if a not in {c["anchor_cluster_key"] for c in found}
                and _str(r["state"]) in ("queued", "untried_cap")]
        for anchor in gone:
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
            "by_type": by_type, "by_class": by_class,
            "cap": {"base": int(cfg.risk_issue_panel_cap), "hard": int(cfg.risk_issue_panel_hard_cap), "used": used}}


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
