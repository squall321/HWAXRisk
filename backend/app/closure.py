# 완결 판정(재설계 M3 S3-8) — cells 대상의 레벨·잔여·표기·사람 확인을 원장에서 세고 rr_targets 에 캐시한다(잔여가 남으면 맨 C3 가 없다)
"""`registry.close_level` 이 문지기다 — `flow='cells'` 면 `close_level_cells`, 아니면 지금 본문(`registry._close_level_panels`).
레벨 어휘(C0 · C1 · C2 · C2(closed) · C3)는 넓히지 않는다(M3.md 4.10 · m3-synthesis 3.8).

- 셀 몫은 `review_cells.closure_cells`(셀 꾸러미 C3-x — M3.md 4.10 의 모양)를 부른다. 그 함수가 아직 없는 판(셀 꾸러미가 합쳐지기
  전)에서는 같은 모양을 셀 원장에서 GROUP BY 로 센다 — 거르기가 없던 M2 셀이라 `filtered.n` 은 0 이다.
- 잔여(qualifier)는 모든 레벨에 붙는다. '막음' 은 확인(ack) 전에 저장 레벨이 C2(closed)·C3 로 오르지 않는다는 뜻이다.
- 표기 `level_label` 은 잔여가 0 일 때만 맨 레벨 이름이다 — cells 대상에는 2차 영향·결손 사냥 미실행이 늘 있어 M3 에서 맨 C3 는
  나오지 않는다.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app import common, config
from app.errors import AppError
from app.risk_store import RiskStore

LEVEL_ORDER: dict[str, int] = {"C0": 0, "C1": 1, "C2": 2, "C2(closed)": 3, "C3": 4}
OPEN_CELL_STATES: tuple[str, ...] = ("pending", "running")
FILTERED_STATE = "na_irrelevant"
NO_INPUT_STATE = "no_input"
ISSUE_OPEN_STATES: tuple[str, ...] = ("queued", "planned", "running")
ISSUE_UNTRIED_STATES: tuple[str, ...] = ("untried_cap", "inconclusive", "skipped")
EXCLUDED_BLOCKING_REASONS: tuple[str, ...] = ("capture_partial", "partial_scope", "source_drift")
SKIPPED_RATIO_MAX = 0.05          # 넘긴 셀 / (거르지 않고 입력 결손도 아닌 셀) — X1-01
STRONG_RATIO_MIN = 0.7            # 셀 기준 strong(검토한 셀 가운데 카드로 본 셀) — X1-05
UNDETERMINED_MAX = 0.20           # 적용 판정 가운데 보류 비율 — 넘으면 막음(#52, 사용자 확인 대기)
FILTER_UPPER_MAX = 0.05           # 표본 놓침 95% 상한
ACK_REASON_MAX = 300
# 잔여(4.10 표의 차례 + 카드 없는 영역 D-35) — 막음 여부는 늘 막는 것 · 조건부(filtered · undetermined) · 표기만(no_cards ·
# depth_no_cards · cross · mech).
RESIDUAL_ITEMS: tuple[str, ...] = ("input_gap", "failed", "skipped", "issues_untried", "issues_reraised", "filtered",
                                   "unit_excluded", "quality", "undetermined", "no_cards", "depth_no_cards", "cross_not_run",
                                   "mech_not_run")
ALWAYS_BLOCKING: frozenset[str] = frozenset({"input_gap", "failed", "skipped", "issues_untried", "issues_reraised",
                                             "unit_excluded", "quality"})
# 잔여 행에 싣는 쟁점 id 의 수(나머지는 수로 — 진행판 · MCP 와이어).
RESIDUAL_IDS_MAX = 20


def _loads(text: Any, default: Any) -> Any:
    import json  # noqa: PLC0415

    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _hash(rows: Any) -> str:
    return common.sha256_hex(common.canonical_json(rows))[:12]


# ---------------------------------------------------------------- 셀 몫(셀 꾸러미 3.10 · M3.md 4.10)
def closure_cells(store: RiskStore, target_key: str) -> dict:
    """셀 셈 — `review_cells.closure_cells` 가 있으면 그것(정본), 없으면 같은 모양의 셀 원장 GROUP BY."""
    from app import review_cells  # noqa: PLC0415 — review_cells 는 무겁다.

    provider = getattr(review_cells, "closure_cells", None)
    if callable(provider):
        return dict(provider(store, target_key))
    return _cells_from_ledger(store, target_key)


def _cells_from_ledger(store: RiskStore, target_key: str) -> dict:
    """셀 꾸러미의 closure_cells 가 서기 전의 셈 — 같은 칸 이름(M3.md 4.10). 거르기·표본은 M2 셀에 없어 0 이다."""
    rows = [dict(r) for r in store.query(
        "SELECT unit_id, agent_key, domain, state, basis, error_code, decide_note FROM rr_review_cells WHERE target_key = ?",
        (target_key,))]
    by_state: dict[str, int] = {}
    by_basis: dict[str, int] = {}
    failed_codes: dict[str, int] = {}
    skipped_notes: dict[str, int] = {}
    for row in rows:
        by_state[row["state"]] = by_state.get(row["state"], 0) + 1
        if row["state"] == "reviewed":
            by_basis[row["basis"] or "cards"] = by_basis.get(row["basis"] or "cards", 0) + 1
        if row["state"] == "failed":
            failed_codes[row["error_code"] or "unknown"] = failed_codes.get(row["error_code"] or "unknown", 0) + 1
        if row["state"] == "skipped":
            skipped_notes[row["decide_note"] or "-"] = skipped_notes.get(row["decide_note"] or "-", 0) + 1
    no_input = [r for r in rows if r["state"] == NO_INPUT_STATE]
    return {
        "grid": {"actual": len(rows)}, "by_state": by_state, "by_basis": by_basis,
        "failed": {"open": by_state.get("failed", 0), "by_code": failed_codes},
        "skipped": {"n": by_state.get("skipped", 0), "experts": len({r["agent_key"] for r in rows if r["state"] == "skipped"}),
                    "by_note": skipped_notes},
        "filtered": {"n": by_state.get(FILTERED_STATE, 0), "would_filter": 0, "by_domain": {},
                     "audit": {"sampled": 0, "floor_met": True, "risk_miss": 0, "relevance_miss": 0, "undetermined": 0,
                               "kept": 0, "upper95": None, "upper95_conservative": None},
                     "shadow": False, "widened": 0, "off": False},
        "no_input": {"experts": len({r["agent_key"] for r in no_input}), "cells": len(no_input), "by_outcome": {}},
        "undetermined": {"rows": 0, "cells": 0}, "out_of_scope_pending": 0, "invariants": [],
        "_rows": rows,
    }


def cells_hash(store: RiskStore, target_key: str, *, scope: Iterable[str] | None = None) -> str:
    """마감 범위 셀의 지문 — (unit_id, agent_key, state, n_fail, n_warning, n_offcard, error_code) 정렬 sha256[:16].
    `scope` 를 주면 그 전문가들의 셀만(C2 마감 — Tier B 범위). 쟁점 선정·보고서 판이 이 값을 얼려 신선도를 잰다(S3-5 가 같은 함수를 쓴다)."""
    keep = set(scope) if scope is not None else None
    rows = sorted((r["unit_id"], r["agent_key"], r["state"], int(r["n_fail"] or 0), int(r["n_warning"] or 0),
                   int(r["n_offcard"] or 0), r["error_code"] or "")
                  for r in store.query("SELECT unit_id, agent_key, state, n_fail, n_warning, n_offcard, error_code"
                                       " FROM rr_review_cells WHERE target_key = ?", (target_key,))
                  if keep is None or r["agent_key"] in keep)
    return common.sha256_hex(common.canonical_json(rows))[:16]


def closing_agents(store: RiskStore, target_key: str) -> list[str] | None:
    """마감 범위의 전문가 — 마감 레벨이 C3(cells 대상의 기본)이면 None(격자 전부), C2 면 Tier B 범위(A·B) 전문가."""
    from app import planner  # noqa: PLC0415

    row = store.query_one("SELECT close_level FROM rr_targets WHERE target_key = ?", (target_key,))
    if row is None or (row["close_level"] or "C3") == "C3":
        return None
    return [r["agent_key"] for r in planner.review_order(store, target_key) if r["tier"] in ("A", "B")]


def closing_hash(store: RiskStore, target_key: str) -> str:
    """마감 범위의 셀 지문(`closing_agents`) — 쟁점 선정·사슬 잡·보고서 판이 얼리는 값이고 완결 판정의 신선도가 이것과 견준다."""
    return cells_hash(store, target_key, scope=closing_agents(store, target_key))


# ---------------------------------------------------------------- 수
def cell_counts(store: RiskStore, target_key: str) -> dict:
    """완결 판정과 보고서 머리가 같이 쓰는 수(3.8 응답의 counts) — 셀·단위·전문가·쟁점·등록부·넘김·품질."""
    from app import planner, review_quality, units  # noqa: PLC0415 — 무거운 모듈은 쓸 때만.

    cells = closure_cells(store, target_key)
    rows = cells.pop("_rows", None) or [dict(r) for r in store.query(
        "SELECT unit_id, agent_key, domain, state, basis, error_code, decide_note FROM rr_review_cells WHERE target_key = ?",
        (target_key,))]
    order = planner.review_order(store, target_key)
    roster = {r["agent_key"]: r for r in order}
    build = units.active_build(store, target_key) or {}
    reviewable = [u["unit_id"] for u in units.load_units(store, target_key)] if build else []
    stats = build.get("stats") or {}
    unassigned = len((build.get("invariants") or {}).get("U1_unassigned") or ())
    by_agent: dict[str, list[dict]] = {}
    for row in rows:
        by_agent.setdefault(row["agent_key"], []).append(row)

    active_by_domain: dict[str, int] = {}
    have_by_domain: dict[str, int] = {}
    carded_by_domain: dict[str, int] = {}
    input_gap: list[str] = []
    filtered_only = 0
    # 카드 묶음의 바탕(rr_expert_reports.card_basis — cards · background · none). 묶음을 아직 안 받은 전문가는 셀의 basis 로 본다.
    # 묶음을 끝내 못 받은(pack_status error) 전문가는 카드로 보지 못한 카드 전문가로 센다 — 깊이의 분모에 들고 '카드 없는 영역' 이
    # 되지 않는다(M3 묶음 검토 L4 · D-52 — 종전에는 그 영역이 깊이 면제 · 표기만이었다).
    card_basis = {str(r["agent_key"]): "cards" if r["card_basis"] is None and r["pack_status"] == "error" else r["card_basis"]
                  for r in store.query("SELECT agent_key, card_basis, pack_status FROM rr_expert_reports WHERE target_key = ?",
                                       (target_key,))}
    for key, info in roster.items():
        mine = by_agent.get(key, [])
        if info["input_gaps"] or (mine and all(r["state"] == NO_INPUT_STATE for r in mine)):
            input_gap.append(key)
            continue
        if mine and all(r["state"] == FILTERED_STATE for r in mine):
            filtered_only += 1
            continue
        active_by_domain[info["domain"]] = active_by_domain.get(info["domain"], 0) + 1
        basis = card_basis.get(key)
        if basis == "cards" or (basis is None and any((r["basis"] or "") == "cards" for r in mine)):
            carded_by_domain[info["domain"]] = carded_by_domain.get(info["domain"], 0) + 1
        closed = mine and all(r["state"] not in OPEN_CELL_STATES for r in mine)
        if closed and any(r["state"] == "reviewed" and (r["basis"] or "cards") == "cards" for r in mine):
            have_by_domain[info["domain"]] = have_by_domain.get(info["domain"], 0) + 1

    reports = {str(r["agent_key"]): str(r["state"]) for r in store.query(
        "SELECT agent_key, state FROM rr_expert_reports WHERE target_key = ?", (target_key,))}
    finished = [k for k in roster if by_agent.get(k) and all(r["state"] not in OPEN_CELL_STATES for r in by_agent[k])]
    report_counts = {s: sum(1 for v in reports.values() if v == s) for s in ("ready", "partial", "blocked")}
    report_counts.update(expected=len(roster), missing=sum(1 for k in finished if reports.get(k) not in
                                                           ("ready", "partial", "blocked")))
    verdict_gaps = int(store.query_one(
        "SELECT COUNT(*) AS n FROM rr_review_cells WHERE target_key = ? AND state = 'reviewed' AND COALESCE(basis, 'cards')"
        " = 'cards' AND COALESCE(cards_judged, 0) < COALESCE(cards_expected, 0)", (target_key,))["n"] or 0)

    issue_rows = [dict(r) for r in store.query(
        "SELECT state, outcome, p_class, types_json, attempts FROM rr_issues WHERE target_key = ?", (target_key,))]
    by_issue_state: dict[str, int] = {}
    by_outcome: dict[str, int] = {}
    for row in issue_rows:
        by_issue_state[row["state"]] = by_issue_state.get(row["state"], 0) + 1
        if row["outcome"]:
            by_outcome[row["outcome"]] = by_outcome.get(row["outcome"], 0) + 1
    held = [r for r in issue_rows if "held_fail" in _loads(r["types_json"], [])]
    p1 = [r for r in issue_rows if r["p_class"] == "P1"]

    registry_rows = [dict(r) for r in store.query(
        "SELECT attention, merged_json FROM rr_registry WHERE target_key = ? AND direction = 'risk'", (target_key,))]
    attention = {g: sum(1 for r in registry_rows if r["attention"] == g) for g in ("A", "B", "C", "D")}
    card_fail_claimed = sum(1 for r in registry_rows
                            if ((_loads(r["merged_json"], {}).get("claimed") or {}).get("judgement") == "FAIL"))

    handoffs = [(row["agent_key"], h) for row in store.query(
        "SELECT agent_key, handoffs_json FROM rr_review_cells WHERE target_key = ? AND handoffs_json IS NOT NULL",
        (target_key,)) for h in _loads(row["handoffs_json"], []) or () if isinstance(h, Mapping)]
    pairs = {((roster.get(a) or {}).get("domain"), str(h.get("to"))) for a, h in handoffs}
    mechs = [m for row in store.query("SELECT mechs_json FROM rr_review_cells WHERE target_key = ? AND mechs_json IS NOT NULL",
                                      (target_key,)) for m in _loads(row["mechs_json"], []) or ()]
    quality = _quality(store, target_key, review_quality) if rows else {"out_of_bounds": []}
    reviewed = [r for r in rows if r["state"] == "reviewed"]
    strong_ratio = (sum(1 for r in reviewed if (r["basis"] or "cards") == "cards") / len(reviewed)) if reviewed else None

    return {
        "roster": len(roster),
        "units": {"reviewable": len(reviewable), "excluded_by_reason": dict(stats.get("excluded_by_reason") or {}),
                  "unassigned": unassigned},
        "cells": {"expected": len(roster) * len(reviewable), "actual": len(rows), "by_state": dict(cells.get("by_state") or {}),
                  "reviewed_by_basis": dict(cells.get("by_basis") or {}), "verdict_gaps": verdict_gaps},
        "experts": {"active_by_domain": active_by_domain, "have_by_domain": have_by_domain,
                    # 깊이의 분모 — 카드로 본 전문가만(재설계 M3 review1 M5 — 사용자 결정 D-35 를 섞인 영역까지).
                    "carded_by_domain": carded_by_domain,
                    # 실제로 검토한 전문가가 전부 카드 없이(역할·배경만) 본 영역 — 깊이를 막지 않고 표기 잔여다(D-35).
                    "no_card_domains": sorted(d for d, n in active_by_domain.items() if n and not carded_by_domain.get(d)),
                    # 카드로 본 전문가도 있는 영역의 카드 없는 전문가 수 — 깊이에 세지 않고 표기 잔여에 이름이 선다(M5).
                    "cardless_mixed": {d: n - carded_by_domain[d] for d, n in sorted(active_by_domain.items())
                                       if carded_by_domain.get(d) and n > carded_by_domain[d]},
                    "reviewed_cards": sum(have_by_domain.values()), "input_gap": len(input_gap),
                    "input_gap_keys": sorted(input_gap), "filtered_only": filtered_only, "reports": report_counts},
        "filter": dict(cells.get("filtered") or {}),
        "failed": dict(cells.get("failed") or {}), "skipped": dict(cells.get("skipped") or {}),
        "no_input": dict(cells.get("no_input") or {}), "invariants": list(cells.get("invariants") or ()),
        "issues": {"by_state": by_issue_state, "by_outcome": by_outcome,
                   "p1": {"selected": len(p1), "run": sum(1 for r in p1 if int(r["attempts"] or 0) > 0),
                          "untried": sum(1 for r in p1 if r["state"] in ISSUE_UNTRIED_STATES),
                          "open": sum(1 for r in p1 if r["state"] in ISSUE_OPEN_STATES)},
                   "held_fail": {"selected": len(held), "untried": sum(1 for r in held if r["state"] in ISSUE_UNTRIED_STATES)},
                   "open": sum(1 for r in issue_rows if r["state"] in ISSUE_OPEN_STATES),
                   "cap": {"base": int(config.settings.risk_issue_panel_cap),
                           "hard": int(config.settings.risk_issue_panel_hard_cap)}},
        "registry": {"clusters": len(registry_rows), "attention": attention, "card_fail_claimed": card_fail_claimed},
        "handoffs": {"lines": len(handoffs), "pairs": len(pairs)},
        "mechanisms_reported": {"codes": len({m for m in mechs if m and m != "free"}), "free": sum(1 for m in mechs if m == "free")},
        "quality": {"out_of_bounds": list(quality.get("out_of_bounds") or ()),
                    "strong_ratio_cells": round(strong_ratio, 4) if strong_ratio is not None else None},
        "_rows": rows, "_order": order,
    }


def _quality(store: RiskStore, target_key: str, review_quality: Any) -> Mapping[str, Any]:
    """품질 수치 — 검토 루프가 마지막 잡의 진행판에 넣어 둔 값(같은 compute 결과)을 읽는다. 진행판을 읽는 동안 품질 수치를 다시
    세지 않는다(M2 #16 · P-17-13). 진행판에 없을 때만(품질 훅이 없는 배선·옛 잡) 그 자리에서 센다."""
    row = store.query_one("SELECT progress_json FROM rr_jobs WHERE target_key = ? AND mode = 'reviews'"
                          " ORDER BY created_at DESC, id DESC LIMIT 1", (target_key,))
    board = ((_loads(row["progress_json"], {}) if row is not None else {}) or {}).get("quality") or {}
    data = board.get("json") if isinstance(board, Mapping) else None
    if isinstance(data, Mapping) and "out_of_bounds" in data:
        return data
    return review_quality.compute(store, target_key)


# ---------------------------------------------------------------- 잔여
def _undetermined(store: RiskStore, target_key: str) -> tuple[int, int, list]:
    """적용 판정 가운데 보류(applies=unknown · judgement=undetermined)의 수 — (보류, 분모, 보류 행 열쇠)."""
    rows = store.query("SELECT unit_id, agent_key, record_id, applies, judgement FROM rr_card_verdicts WHERE target_key = ?"
                       " AND is_effective = 1 AND applies IN ('yes', 'unknown')", (target_key,))
    held = sorted([r["unit_id"], r["agent_key"], r["record_id"]] for r in rows
                  if r["applies"] == "unknown" or r["judgement"] == "undetermined")
    return len(held), len(rows), held


def residuals(store: RiskStore, target_key: str, counts: Mapping[str, Any]) -> list[dict]:
    """잔여 행(4.10 표) — {item, n, label, blocking, basis_hash, basis_n, …}. 막음 잔여의 basis_hash 는 그 행 집합의 해시다(확인이
    받은 집합과 다르면 그 확인은 낡았다)."""
    rows = counts["_rows"]
    order = {r["agent_key"]: r for r in counts["_order"]}
    out: list[dict] = []

    gap_cells = sorted([r["unit_id"], r["agent_key"]] for r in rows if r["state"] == NO_INPUT_STATE)
    gap_experts = list(counts["experts"]["input_gap_keys"])
    if gap_cells or gap_experts:
        domains = sorted({order[k]["domain"] for k in gap_experts if k in order})
        whole = [d for d in domains if all(k in gap_experts for k, v in order.items() if v["domain"] == d)]
        label = f"입력 결손 {len(gap_experts)}명·{len(gap_cells)}셀" + (f"({'·'.join(whole)})" if whole else "")
        out.append({"item": "input_gap", "n": len(gap_cells), "experts": len(gap_experts), "domains": whole,
                    "label": label, "rows": {"cells": gap_cells, "experts": gap_experts}})
    failed = sorted([r["unit_id"], r["agent_key"], r["error_code"] or ""] for r in rows if r["state"] == "failed")
    if failed:
        out.append({"item": "failed", "n": len(failed), "by_code": dict(counts["failed"].get("by_code") or {}),
                    "label": f"실패 {len(failed)}셀", "rows": failed})
    skipped = sorted([r["unit_id"], r["agent_key"]] for r in rows if r["state"] == "skipped")
    if skipped:
        crowd: dict[tuple, list[int]] = {}
        for r in rows:
            cell = crowd.setdefault(((order.get(r["agent_key"]) or {}).get("domain"), r["unit_id"]), [0, 0])
            cell[0] += 1
            cell[1] += 1 if r["state"] == "skipped" else 0
        crowded = sorted(f"{d}×{u}" for (d, u), (n, s) in crowd.items() if s * 2 > n)
        out.append({"item": "skipped", "n": len(skipped), "crowded": crowded,
                    "label": f"사람 넘김 {len(skipped)}셀" + (f"(몰림 {len(crowded)}칸)" if crowded else ""),
                    "rows": skipped})
    untried = [dict(r) for r in store.query(
        "SELECT issue_id, state, state_reason, p_class, types_json, basis_json FROM rr_issues WHERE target_key = ?"
        f" AND state IN ({','.join('?' * len(ISSUE_UNTRIED_STATES))}) ORDER BY issue_id",
        (target_key, *ISSUE_UNTRIED_STATES))]
    if untried:
        held = [r for r in untried if "held_fail" in _loads(r["types_json"], [])]
        claimed_fail = sum(1 for r in held if ((_loads(r["basis_json"], {}).get("claimed") or {}).get("judgement") == "FAIL"))
        sentences = [f"전문가 {int(((_loads(r['basis_json'], {}).get('claimed') or {}).get('fail_experts')) or 0)}명이 FAIL 로"
                     " 봤으나 미토의" for r in held]
        out.append({"item": "issues_untried", "n": len(untried), "p1": sum(1 for r in untried if r["p_class"] == "P1"),
                    "held_fail": len(held), "sentences": sentences,
                    "label": f"미토의 쟁점 {len(untried)}건(주장 FAIL {claimed_fail})",
                    "rows": [[r["issue_id"], r["state"], r["state_reason"] or ""] for r in untried]})
    # 패널이 판정한 뒤 근거가 바뀌었는데 상한에 자리가 없어 다시 돌지 못한 결과 쟁점(review1 H3 — 조정자 결정: 조용히 남기지 않고
    # 잔여로 보인다). 다시 줄을 선 것(queued)은 쟁점 진행에 든다.
    from app import registry  # noqa: PLC0415 — registry 는 무겁다.

    reraised = [dict(r) for r in store.query(
        "SELECT issue_id, basis_hash, reraised_json FROM rr_issues WHERE target_key = ? AND reraised_json IS NOT NULL"
        " AND state IN ('resolved', 'inconclusive') ORDER BY issue_id", (target_key,))]
    if reraised:
        ids = [r["issue_id"] for r in reraised]
        out.append({"item": "issues_reraised", "n": len(reraised), "issue_ids": ids[:RESIDUAL_IDS_MAX],
                    "label": f"{registry.REARGUE_LABEL} {len(reraised)}건",
                    "rows": [[r["issue_id"], (_loads(r["reraised_json"], {}) or {}).get("basis_hash")] for r in reraised]})
    flt = counts["filter"]
    if int(flt.get("n") or 0):
        audit = flt.get("audit") or {}
        upper = audit.get("upper95")
        blocking = (not audit.get("floor_met", False)) or (upper is not None and float(upper) > FILTER_UPPER_MAX) \
            or bool(flt.get("off"))
        tail = f"표본 {int(audit.get('sampled') or 0)} · 놓친 걸림 {int(audit.get('risk_miss') or 0)}"
        if upper is not None:
            tail += f" · 95% 상한 {float(upper) * 100:.1f}%"
        out.append({"item": "filtered", "n": int(flt["n"]), "audit": dict(audit), "blocking": blocking,
                    "label": f"거름 {int(flt['n']):,}셀({tail})",
                    "rows": [int(flt["n"]), audit.get("sampled"), audit.get("risk_miss"), upper, bool(flt.get("off"))]})
    excluded = counts["units"]["excluded_by_reason"]
    partial = {k: int(v) for k, v in excluded.items() if k in EXCLUDED_BLOCKING_REASONS and int(v)}
    if partial:
        out.append({"item": "unit_excluded", "n": sum(partial.values()), "by_reason": partial,
                    "others": {k: v for k, v in excluded.items() if k not in partial},
                    "label": f"부분 캡처 — 제외 {sum(partial.values())}건", "rows": sorted(partial.items())})
    bounds = list(counts["quality"]["out_of_bounds"])
    strong = counts["quality"]["strong_ratio_cells"]
    if bounds or (strong is not None and strong < STRONG_RATIO_MIN):
        weak = [] if strong is None or strong >= STRONG_RATIO_MIN else [f"셀 기준 strong {strong:.2f}"]
        out.append({"item": "quality", "n": len(bounds) + len(weak), "out_of_bounds": bounds, "strong_ratio_cells": strong,
                    "label": f"검토 품질 기준 밖 {len(bounds) + len(weak)}항", "rows": sorted(bounds) + weak})
    held_n, den, held_rows = _undetermined(store, target_key)
    if held_n:
        ratio = held_n / den if den else 0.0
        out.append({"item": "undetermined", "n": held_n, "of": den, "ratio": round(ratio, 4),
                    "blocking": ratio > UNDETERMINED_MAX, "label": f"보류 {held_n}/{den}({ratio * 100:.0f}%)",
                    "rows": held_rows})
    no_cards = sorted(str(r["agent_key"]) for r in store.query(
        "SELECT agent_key FROM rr_expert_reports WHERE target_key = ? AND card_basis = 'none'", (target_key,)))
    if no_cards:
        out.append({"item": "no_cards", "n": len(no_cards), "label": f"카드 0장 {len(no_cards)}명", "rows": no_cards})
    cardless = list(counts["experts"]["no_card_domains"])
    mixed = dict(counts["experts"].get("cardless_mixed") or {})
    if cardless or mixed:
        names = cardless + [f"{d}(그중 {n}명)" for d, n in sorted(mixed.items())]
        out.append({"item": "depth_no_cards", "n": len(cardless) + len(mixed), "domains": cardless, "mixed": mixed,
                    "label": f"카드 없는 영역 — 역할 판단만 · {'·'.join(names)}", "rows": [cardless, sorted(mixed.items())]})
    out.append({"item": "cross_not_run", "n": counts["handoffs"]["lines"], "pairs": counts["handoffs"]["pairs"],
                "label": f"2차 영향 미실행(넘김 {counts['handoffs']['lines']}건 표만)", "rows": []})
    out.append({"item": "mech_not_run", "n": counts["mechanisms_reported"]["codes"], "label": "결손 사냥 미실행", "rows": []})

    for item in out:
        item.setdefault("blocking", item["item"] in ALWAYS_BLOCKING)
        item["basis_n"] = int(item["n"] or 0)
        item["basis_hash"] = _hash({"item": item["item"], "rows": item.pop("rows")})
    rank = {name: i for i, name in enumerate(RESIDUAL_ITEMS)}
    return sorted(out, key=lambda r: rank[r["item"]])


# ---------------------------------------------------------------- 확인(ack)
def _acks(store: RiskStore, target_key: str) -> dict[str, dict]:
    """item → 그 item 의 가장 늦은 확인 행(취소 포함)."""
    out: dict[str, dict] = {}
    for row in store.query("SELECT item, ack_at, ack_by, ack_reason, basis_n, basis_hash, revoked_by, revoked_at"
                           " FROM rr_close_acks WHERE target_key = ? ORDER BY ack_at, item", (target_key,)):
        out[str(row["item"])] = dict(row)
    return out


def _mark_acks(store: RiskStore, target_key: str, found: Sequence[dict]) -> list[dict]:
    """잔여마다 확인 상태 — 유효(취소 안 됐고 받은 집합이 지금과 같다) · 낡음 · 취소."""
    acks = _acks(store, target_key)
    for item in found:
        ack = acks.get(item["item"])
        if ack is None:
            item["acked"] = False
            continue
        state = ("revoked" if ack["revoked_at"] is not None
                 else "valid" if ack["basis_hash"] == item["basis_hash"] else "stale")
        item["acked"] = state == "valid"
        item["ack"] = {"state": state, "by": ack["ack_by"], "at": ack["ack_at"], "reason": ack["ack_reason"]}
    return list(found)


def ack_residual(store: RiskStore, target_key: str, item: str, *, reason: str, by: str, basis_hash: str) -> dict:
    """막음 잔여 한 종류를 확인한다 — 사유 필수(300자 안, 비면 422 reason_required), 막음 잔여가 아니면 422 ack_not_allowed, 확인
    시점의 집합 해시가 지금과 다르면 409 residual_changed. `rr_audit` 한 행과 캐시 새로 쓰기는 부르는 쪽(REST)이 같은 트랜잭션에서."""
    text = (reason or "").strip()
    if not text or len(text) > ACK_REASON_MAX:
        raise AppError("reason_required", f"확인에는 사유가 필요합니다({ACK_REASON_MAX}자 안).", 422)
    current = next((r for r in residuals(store, target_key, cell_counts(store, target_key)) if r["item"] == item), None)
    if current is None or not current["blocking"]:
        raise AppError("ack_not_allowed", f"확인으로 넘길 수 있는 막음 잔여가 아니다 — {item}.", 422,
                       detail={"item": item})
    if basis_hash != current["basis_hash"]:
        raise AppError("residual_changed", "그 사이 잔여가 바뀌었다 — 다시 읽고 확인한다.", 409,
                       detail={"item": item, "basis_hash": current["basis_hash"], "basis_n": current["basis_n"]})
    owner = store.query_one("SELECT owner_sub FROM rr_targets WHERE target_key = ?", (target_key,))["owner_sub"]
    # 같은 초에 다시 확인해도(낡은 확인을 곧바로 다시) 이력 행이 겹치지 않게 — ack_at 은 키의 일부다(P-11).
    last = store.query_one("SELECT MAX(ack_at) AS t FROM rr_close_acks WHERE target_key = ? AND item = ?", (target_key, item))
    now = max(common.now_epoch(), int(last["t"] or 0) + 1)
    store.execute("INSERT INTO rr_close_acks(target_key, item, ack_at, owner_sub, ack_by, ack_reason, basis_n, basis_hash)"
                  " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (target_key, item, now, owner, by, text, current["basis_n"], current["basis_hash"]))
    return {"item": item, "ack_at": now, "ack_by": by, "basis_hash": current["basis_hash"], "basis_n": current["basis_n"]}


def revoke_ack(store: RiskStore, target_key: str, item: str, *, by: str) -> dict:
    """확인 취소 — 행을 지우지 않고 가장 늦은 유효 확인에 취소를 표기한다. 없으면 404."""
    row = store.query_one("SELECT ack_at FROM rr_close_acks WHERE target_key = ? AND item = ? AND revoked_at IS NULL"
                          " ORDER BY ack_at DESC LIMIT 1", (target_key, item))
    if row is None:
        raise AppError("E404", f"취소할 확인이 없습니다 — {item}.", 404)
    now = common.now_epoch()
    store.execute("UPDATE rr_close_acks SET revoked_by = ?, revoked_at = ? WHERE target_key = ? AND item = ? AND ack_at = ?",
                  (by, now, target_key, item, row["ack_at"]))
    return {"item": item, "revoked_by": by, "revoked_at": now}


# ---------------------------------------------------------------- 레벨 · 표기
def reopened_sum(store: RiskStore, target_key: str) -> int:
    """마감 범위 셀의 다시 연 횟수 합(`reopened_n` — 사람의 다시 · 거른 셀 다시 열기 · 입력이 바뀐 셀). 사슬 잡이 얼려 두고 '후속
    낡음(재검토 N셀)' 의 N 을 이 값의 차로 센다."""
    agents = closing_agents(store, target_key)
    return sum(int(r["reopened_n"] or 0) for r in store.query(
        "SELECT agent_key, reopened_n FROM rr_review_cells WHERE target_key = ? AND reopened_n > 0", (target_key,))
               if agents is None or r["agent_key"] in agents)


def _fresh(store: RiskStore, target_key: str, current: str) -> dict:
    """후속 단계가 지금 셀 지문으로 돌았나 — 쟁점(선정한 쟁점의 cells_hash · 사슬 잡의 chain_json.cells_hash)과 보고서 판(마지막 판이
    지금 지문이고 그 지문으로 종합까지 돈 판 synth_done 이 있다). 낡았을 때 표기에 쓸 것 — 쟁점을 고른 적이 있나(`selected`), 마지막
    사슬 잡 뒤 다시 연 셀 수(`reopened_since` — 사슬 잡이 없으면 None), 종합 판 번호(`synth_version`)."""
    issues_fresh = store.query_one("SELECT 1 FROM rr_issues WHERE target_key = ? AND cells_hash = ? LIMIT 1",
                                   (target_key, current)) is not None
    chains = [_loads(r["chain_json"], {}) or {} for r in store.query(
        "SELECT chain_json FROM rr_jobs WHERE target_key = ? AND mode IN ('issues', 'synth') AND chain_json IS NOT NULL"
        " ORDER BY created_at, rowid", (target_key,))]
    issues_fresh = issues_fresh or any(c.get("cells_hash") == current for c in chains)
    selected = bool(chains) or store.query_one("SELECT 1 FROM rr_issues WHERE target_key = ? LIMIT 1",
                                               (target_key,)) is not None
    baseline = chains[-1].get("reopened_n") if chains else None
    report = store.query_one("SELECT version_no, cells_hash, trigger FROM rr_reports WHERE target_key = ?"
                             " ORDER BY version_no DESC LIMIT 1", (target_key,))
    # 종합 판은 셀 지문만이 아니라 등록부 지문(rr_reports.registry_hash)도 지금 것이어야 신선하다 — 종합 뒤 쟁점 결과가 바뀌면(사람이
    # 올린 상한 밖 쟁점 따위) 셀은 그대로여도 그 판의 쟁점 표 · 서술은 옛 것이다(review1 M3).
    from app import synth  # noqa: PLC0415 — synth 는 이 모듈을 쓴다.

    synthesized = store.query_one("SELECT 1 FROM rr_reports WHERE target_key = ? AND cells_hash = ? AND trigger = 'synth_done'"
                                  " AND registry_hash = ? LIMIT 1",
                                  (target_key, current, synth.registry_hash(store, target_key))) is not None
    synth_version = store.query_one("SELECT MAX(version_no) AS v FROM rr_reports WHERE target_key = ? AND trigger = 'synth_done'",
                                    (target_key,))["v"]
    return {"issues": issues_fresh, "report": bool(report is not None and report["cells_hash"] == current and synthesized),
            "report_version": report["version_no"] if report is not None else None, "synth_version": synth_version,
            "selected": selected,
            "reopened_since": (max(reopened_sum(store, target_key) - int(baseline), 0) if baseline is not None else None)}


def level_label(level: str, labels: Sequence[str], *, head: str | None = None) -> str:
    """`"<레벨>" + ("(" + 잔여 표기를 ' · ' 로 + ")" if 잔여 else "")` — 맨 레벨 이름은 잔여 0 일 때만이다. `head` 는 오르지 못한
    레벨의 머리('C2 · C3 대기' · 'C2 · 마감 대기')다."""
    text = head or level
    return f"{text}({' · '.join(labels)})" if labels else text


def close_level_cells(store: RiskStore, target_key: str, *, persist: bool = True,
                      counts: dict | None = None) -> dict:
    """cells 대상의 완결 판정(3.8) — 지금 계산(`level_current`)과 저장 레벨(내려가지 않는다), 잔여·표기·수. `persist` 면
    rr_targets 의 level·level_label·closure_json·closure_at 을 쓴다(캐시 — 진행판·MCP 가 읽는다)."""
    target = store.query_one("SELECT target_key, level, close_level FROM rr_targets WHERE target_key = ?", (target_key,))
    if target is None:
        raise AppError("E404", f"타깃을 찾지 못했습니다: {target_key}", 404)
    # 종합 보고서는 같은 호출 안의 수 한 벌로 판정과 머리를 낸다(나갈 기준 4) — 그 수를 받으면 다시 세지 않는다.
    counts = counts if counts is not None else cell_counts(store, target_key)
    rows, order = counts["_rows"], counts["_order"]
    target_close = (target["close_level"] or "C3")
    by_agent: dict[str, list[dict]] = {}
    for row in rows:
        by_agent.setdefault(row["agent_key"], []).append(row)

    def all_closed(keys: Iterable[str]) -> bool:
        return all(r["state"] not in OPEN_CELL_STATES for k in keys for r in by_agent.get(k, []))

    reviewable = counts["units"]["reviewable"]
    grid_ok = reviewable >= 1 and counts["cells"]["actual"] == counts["cells"]["expected"]
    domains = list(config.settings.risk_roster_domains) or sorted({r["domain"] for r in order})
    reps = {}
    for r in order:
        if r["domain"] in domains and (r["domain"] not in reps
                                       or (r["rank_in_domain"] or 99) < (reps[r["domain"]]["rank_in_domain"] or 99)):
            reps[r["domain"]] = r
    reports_missing = int(counts["experts"]["reports"]["missing"])
    verdict_gaps = int(counts["cells"]["verdict_gaps"])
    c1 = bool(grid_ok and counts["units"]["unassigned"] == 0 and all_closed(r["agent_key"] for r in reps.values())
              and reports_missing == 0 and verdict_gaps == 0 and not counts["invariants"])

    scope_b = [r["agent_key"] for r in order if r["tier"] in ("A", "B")]
    current_hash = cells_hash(store, target_key, scope=None if target_close == "C3" else scope_b)
    fresh = _fresh(store, target_key, current_hash)
    depth: dict[str, dict] = {}
    depth_ok = True
    no_card_domains = set(counts["experts"]["no_card_domains"])
    carded_by_domain = counts["experts"].get("carded_by_domain") or {}
    for domain, everyone in sorted(counts["experts"]["active_by_domain"].items()):
        # 분모는 카드로 본 전문가다(review1 M5) — 카드 없는 전문가는 깊이를 채울 수 없으니 막지 않고 표기 잔여에 이름만 선다.
        active = int(carded_by_domain.get(domain, 0))
        need = active if active < 3 else max(3, math.ceil(0.3 * active))
        have = int(counts["experts"]["have_by_domain"].get(domain, 0))
        depth[domain] = {"active": active, "have": have, "need": need, "cardless": everyone - active}
        if domain in no_card_domains:
            # 카드 0장 전문가는 역할만으로 답하고 보고서에 잔여로 남는다(D-35) — 그 영역은 깊이를 막지 않는다(잔여 depth_no_cards).
            depth[domain]["exempt"] = "no_cards"
            continue
        depth_ok = depth_ok and have >= need
    p1_open = int(counts["issues"]["p1"]["open"])
    c2 = bool(c1 and all_closed(scope_b) and depth_ok and fresh["issues"] and p1_open == 0)

    found = _mark_acks(store, target_key, residuals(store, target_key, counts))
    blocking_left = [r for r in found if r["blocking"] and not r["acked"]]
    open_cells = sum(1 for r in rows if r["state"] in OPEN_CELL_STATES)
    denominator = sum(1 for r in rows if r["state"] not in (FILTERED_STATE, NO_INPUT_STATE))
    skipped_ratio = (int(counts["skipped"].get("n") or 0) / denominator) if denominator else 0.0
    c3_core = bool(c2 and open_cells == 0 and skipped_ratio <= SKIPPED_RATIO_MAX and counts["issues"]["open"] == 0
                   and fresh["report"])
    c3 = c3_core and not blocking_left

    if reviewable == 0:
        current = "C0"
    elif c3:
        current = "C3"
    elif c2:
        current = "C2(closed)" if target_close == "C2" and not blocking_left else "C2"
    elif c1:
        current = "C1"
    else:
        current = "C0"
    stored = (target["level"] or "C0")
    level = stored if LEVEL_ORDER.get(stored, 0) > LEVEL_ORDER.get(current, 0) else current
    regressed = LEVEL_ORDER.get(current, 0) < LEVEL_ORDER.get(stored, 0)

    notes: list[str] = []
    if reviewable == 0:
        notes.append("심사할 단위 없음")
    if counts["units"]["unassigned"]:
        notes.append(f"미배정 {counts['units']['unassigned']}")
    if reviewable and not grid_ok:
        notes.append(f"격자 결손 {counts['cells']['expected'] - counts['cells']['actual']}셀")
    if open_cells:
        notes.append(f"열린 셀 {open_cells}")
    if verdict_gaps:
        notes.append(f"판정 누락 {verdict_gaps}셀")
    if reports_missing:
        notes.append(f"보고서 누락 {reports_missing}명")
    if counts["issues"]["open"]:
        notes.append(f"쟁점 진행 {counts['issues']['open']}건")
    short = [f"{d} {v['have']}/{v['need']}" for d, v in depth.items() if "exempt" not in v and v["have"] < v["need"]]
    if c1 and short:
        # 셀이 다 닫혔는데 C2 가 아닌 까닭이 깊이면 그 영역과 수를 말한다(review1 M5 — 종전에는 표기에 아무것도 없었다).
        notes.append(f"깊이 미달 {'·'.join(short[:5])}" + (f" 외 {len(short) - 5}영역" if len(short) > 5 else ""))
    if c1 and not fresh["issues"]:
        # 고른 적이 없으면 선정 전, 고른 뒤 셀이 다시 열렸으면 그 수(사슬 잡이 얼린 다시 연 횟수와의 차), 그 밖의 셀 변화는 지문만.
        notes.append("후속 낡음(쟁점 선정 전)" if not fresh["selected"] else
                     f"후속 낡음(재검토 {fresh['reopened_since']}셀)" if fresh["reopened_since"] else "후속 낡음(셀 바뀜)")
    elif c2 and not fresh["report"]:
        notes.append("후속 낡음(종합 전)" if fresh["synth_version"] is None else "후속 낡음(보고서 판)")
    if regressed and open_cells:
        notes.append(f"재개방 {open_cells}셀")      # 셀이 닫힌 채 내려간 것(확인 낡음 따위)은 머리('C3 대기')와 잔여 표기가 말한다
    head = None
    if current == "C2" and target_close == "C3" and c3_core and blocking_left:
        head = "C2 · C3 대기"
    elif current == "C2" and target_close == "C2" and blocking_left:
        head = "C2 · 마감 대기"
    label = level_label(level, notes + [r["label"] for r in found], head=head)

    public_counts = {k: v for k, v in counts.items() if not k.startswith("_")}
    result = {
        "target_key": target_key, "flow": "cells", "level": level, "previous_level": stored,
        "raised": LEVEL_ORDER.get(level, 0) > LEVEL_ORDER.get(stored, 0), "close_level": target_close,
        "level_current": current, "regressed": regressed, "level_label": label,
        "c1": c1, "c2": c2, "c3": c3,
        "qualifiers": [{k: v for k, v in r.items()} for r in found],
        "counts": public_counts,
        # 옛 키(패널 판정의 응답 모양) — 셀 대상에서는 셀 수로 채운다(진행판·보고서가 같은 키를 읽는다).
        "roster_size": counts["roster"], "status_counts": dict(counts["cells"]["by_state"]), "unseated_n": open_cells,
        "detail": {"depth": depth, "strong_ratio_cells": counts["quality"]["strong_ratio_cells"],
                   "skipped_ratio": round(skipped_ratio, 4), "cells_hash": current_hash, "fresh": fresh},
    }
    if persist:
        now = common.now_epoch()
        store.execute("UPDATE rr_targets SET level = ?, level_label = ?, closure_json = ?, closure_at = ?, updated_at = ?"
                      " WHERE target_key = ?",
                      (level, label, common.canonical_json({k: v for k, v in result.items()}), now, now, target_key))
    return result


def refresh(store: RiskStore, target_key: str) -> dict:
    """캐시를 새로 쓴다 — 병합·쟁점 해결·셀 처분·확인·보고서 조립 뒤에 한 번(P-17-13). 패널 대상이면 아무것도 쓰지 않는다."""
    row = store.query_one("SELECT flow FROM rr_targets WHERE target_key = ?", (target_key,))
    if row is None or row["flow"] != "cells":
        return {"target_key": target_key, "flow": "panels", "refreshed": False}
    return close_level_cells(store, target_key, persist=True)


def cached(store: RiskStore, target_key: str) -> dict | None:
    """캐시(closure_json) — 없으면 None."""
    row = store.query_one("SELECT closure_json FROM rr_targets WHERE target_key = ?", (target_key,))
    return _loads(row["closure_json"], None) if row is not None else None
