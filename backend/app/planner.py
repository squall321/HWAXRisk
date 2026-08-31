# 로스터 고정·Tier 편성·커버리지 상태기계(plan §6.3·§6.4·§6.8) — 결정론, LLM·네트워크 호출 없음
from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app import config, taxonomy
from app.common import canonical_json, new_uuid, now_epoch
from app.errors import AppError

PLANNER_VERSION = "planner-1.0"

# ---------------------------------------------------------------- 편성 상수(plan §0.6 공유 상수표)
CHAIR_TEMPLATE = "risk-review"
ADVERSARY_KEY = "delib-baseline-defender"          # 엔진이 합성 push 하는 지정 반대석(원장 미집계)
PRIMARY_SEATS = 4
COUNTER_SEATS = 1
ROSTER_SEATS = PRIMARY_SEATS + COUNTER_SEATS        # 원장에서 소진되는 좌석 수(패널은 +adversary 로 6석)
PANEL_SEATS = ROSTER_SEATS + 1
ROUNDS = 3
FREE_TOOLS = 1
TOOL_BUDGET = 3
MAX_TOOLS = 6
MAX_APPS = 3
MAX_EVIDENCE = 12
DEFAULT_MODIFIERS: tuple[str, ...] = ("toulmin",)
MODIFIER_WHITELIST: tuple[str, ...] = ("voi", "premortem", "toulmin", "eliminative", "anon1r")
# 예산 게이트가 tools 를 줄일 때 남기는 2개(plan §6.10.2).
MINIMAL_TOOLS: tuple[str, ...] = ("list_interfaces", "interface_graph")

TIERS: tuple[str, ...] = ("A", "B", "C")
B_TIER_RATIO = 0.3
TIER_C_XD_DOMAIN = "xd"
TIER_C_XD_MAX = 3                                   # Tier C 한 패널의 xd 좌석 상한
TIER_C_NON_XD_MIN = 2                               # Tier C 한 패널의 비-xd 좌석 하한(공급이 있을 때만)
PANEL_WALL_CLOCK_MIN: tuple[int, int] = (10, 18)    # 패널 1건 벽시계 분(plan §6.10.1)
MAX_SEAT_RETRY = 2                                  # retry > 2 면 skipped

# ---------------------------------------------------------------- 커버리지 상태(plan §6.8.2)
TERMINAL_STATUSES: frozenset[str] = frozenset({"done", "done_weak", "abstain", "skipped", "deferred", "carried"})
OPEN_STATUSES: frozenset[str] = frozenset({"pending", "assigned", "running", "failed"})
ACTIVE_STATUSES: frozenset[str] = frozenset({"assigned", "running"})
ALL_STATUSES: frozenset[str] = TERMINAL_STATUSES | OPEN_STATUSES
# 허용 전이만 적는다(빈 집합 = 종결, 되돌리기는 carried 뿐).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"assigned", "skipped"}),
    "assigned": frozenset({"running", "pending", "skipped"}),
    "running": frozenset({"done", "done_weak", "abstain", "failed", "pending", "skipped"}),
    "failed": frozenset({"pending", "skipped"}),
    "done": frozenset(),
    "done_weak": frozenset(),
    "abstain": frozenset(),
    "skipped": frozenset(),
    "deferred": frozenset(),
    "carried": frozenset({"pending"}),
}


class PlanConflict(Exception):
    """동시 편성 경쟁으로 좌석 선점 rowcount 가 좌석 수와 달라 트랜잭션을 롤백했다(내부 신호)."""


# ---------------------------------------------------------------- 설정·자산
def _cfg(settings: Any | None) -> Any:
    return config.settings if settings is None else settings


def domain_of(agent_key: str) -> str:
    """전문가 키의 도메인 = 첫 '-' 앞 접두사(plan §6.3). list_agents 의 domain 값이 있으면 호출자가 그것을 넘긴다."""
    return str(agent_key).split("-", 1)[0].strip().lower()


def adjacency(settings: Any | None = None) -> dict[str, tuple[str, ...]]:
    """counter 석 인접 표 — assets/adjacency.v1.json, Settings risk_adjacency(JSON) 가 있으면 그것으로 덮는다."""
    raw = (getattr(_cfg(settings), "risk_adjacency", "") or "").strip()
    if raw:
        try:
            doc = json.loads(raw)
        except ValueError as exc:
            raise AppError("E100", f"Settings risk_adjacency 가 JSON 이 아닙니다 — {exc}.", 422) from exc
    else:
        doc = taxonomy.load_json("adjacency")
    table = doc.get("adjacency") if isinstance(doc, dict) and "adjacency" in doc else doc
    if not isinstance(table, dict):
        raise AppError("E100", "인접 표가 객체가 아닙니다(adjacency).", 422)
    return {str(k): tuple(str(v) for v in (vals or [])) for k, vals in table.items()}


# ---------------------------------------------------------------- 로스터 고정(plan §6.3)
def _normalize_agents(agents: Iterable[Mapping[str, Any]], allowed_domains: Sequence[str]) -> list[dict]:
    """[{key, domain, relevance}] 로 정규화하고 도메인 화이트리스트 밖·중복 키를 정리한다(같은 집합이면 같은 결과)."""
    allow = set(allowed_domains)
    best: dict[str, dict] = {}
    for item in agents:
        key = str(item.get("key") or item.get("agent_key") or "").strip()
        if not key:
            continue
        dom = str(item.get("domain") or "").strip().lower() or domain_of(key)
        if dom not in allow:
            continue
        rel = item.get("relevance")
        rel = float(rel) if isinstance(rel, (int, float)) else 0.0
        prev = best.get(key)
        if prev is None or rel > prev["relevance"]:
            best[key] = {"key": key, "domain": dom, "relevance": rel}
    rows = sorted(best.values(), key=lambda r: (r["domain"], -r["relevance"], r["key"]))
    return rows


def freeze_roster(
    store: Any,
    target_key: str,
    owner_sub: str,
    agents: Iterable[Mapping[str, Any]],
    *,
    ecad_absent: bool = False,
    settings: Any | None = None,
) -> dict:
    """rr_roster 를 고정하고 rr_coverage 를 pending(ECAD 부재 도메인의 rank≠1 은 deferred)으로 만든다.

    agents 는 호출자(라우트·어댑터)가 이미 조회한 `list_agents`+`recommend_agents` 결과다 — 이 함수는 네트워크를 부르지 않는다.
    같은 agents 집합이면 같은 rank_in_domain 이 나온다(정렬 relevance desc, agent_key asc).
    이미 고정된 타깃에 다시 부르면 기존 행을 덮지 않는다(INSERT OR IGNORE).
    """
    cfg = _cfg(settings)
    rows = _normalize_agents(agents, cfg.risk_roster_domains)
    ecad_domains = set(cfg.risk_ecad_domains)
    now = now_epoch()

    roster_params: list[tuple] = []
    coverage_params: list[tuple] = []
    rank = 0
    prev_domain = None
    deferred = 0
    for row in rows:
        if row["domain"] != prev_domain:
            prev_domain, rank = row["domain"], 0
        rank += 1
        ecad_dep = 1 if row["domain"] in ecad_domains else 0
        roster_params.append((target_key, row["key"], owner_sub, row["domain"], row["relevance"], rank, ecad_dep, now))
        if ecad_dep and ecad_absent and rank != 1:
            status, reason = "deferred", "ecad_absent"
            deferred += 1
        else:
            status, reason = "pending", None
        coverage_params.append((target_key, row["key"], owner_sub, row["domain"], status, reason, now))

    with store.tx() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO rr_roster(target_key, agent_key, owner_sub, domain, relevance, rank_in_domain,"
            " ecad_dependent, frozen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            roster_params,
        )
        conn.executemany(
            "INSERT OR IGNORE INTO rr_coverage(target_key, agent_key, owner_sub, domain, status, reason, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            coverage_params,
        )
        conn.execute(
            "UPDATE rr_targets SET roster_frozen_at = ?, planner_version = ?, updated_at = ? WHERE target_key = ?",
            (now, PLANNER_VERSION, now, target_key),
        )
    return {"roster_size": len(rows), "deferred": deferred, "frozen_at": now}


def refresh_roster(
    store: Any,
    target_key: str,
    agents: Iterable[Mapping[str, Any]],
    *,
    settings: Any | None = None,
) -> dict:
    """`list_agents` 에 새로 생긴 키만 pending 으로 덧붙인다(rank 는 도메인 기존 최대 다음부터, 기존 행은 불변)."""
    cfg = _cfg(settings)
    target = store.query_one("SELECT owner_sub FROM rr_targets WHERE target_key = ?", (target_key,))
    if target is None:
        raise AppError("E404", f"타깃이 없습니다: {target_key}", 404)
    owner_sub = target["owner_sub"]
    existing = {r["agent_key"] for r in store.query("SELECT agent_key FROM rr_roster WHERE target_key = ?", (target_key,))}
    max_rank: dict[str, int] = {
        r["domain"]: int(r["mx"] or 0)
        for r in store.query(
            "SELECT domain AS domain, MAX(rank_in_domain) AS mx FROM rr_roster WHERE target_key = ? GROUP BY domain",
            (target_key,),
        )
    }
    ecad_domains = set(cfg.risk_ecad_domains)
    now = now_epoch()
    roster_params: list[tuple] = []
    coverage_params: list[tuple] = []
    for row in _normalize_agents(agents, cfg.risk_roster_domains):
        if row["key"] in existing:
            continue
        rank = max_rank.get(row["domain"], 0) + 1
        max_rank[row["domain"]] = rank
        ecad_dep = 1 if row["domain"] in ecad_domains else 0
        roster_params.append((target_key, row["key"], owner_sub, row["domain"], row["relevance"], rank, ecad_dep, now))
        coverage_params.append((target_key, row["key"], owner_sub, row["domain"], "pending", None, now))
    if roster_params:
        with store.tx() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO rr_roster(target_key, agent_key, owner_sub, domain, relevance, rank_in_domain,"
                " ecad_dependent, frozen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                roster_params,
            )
            conn.executemany(
                "INSERT OR IGNORE INTO rr_coverage(target_key, agent_key, owner_sub, domain, status, reason, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                coverage_params,
            )
    return {"added_pending": len(roster_params)}


# ---------------------------------------------------------------- 원장 조회
def _roster_rows(store: Any, target_key: str) -> list[dict]:
    rows = store.query(
        "SELECT r.agent_key AS agent_key, r.domain AS domain, r.rank_in_domain AS rank_in_domain,"
        " r.ecad_dependent AS ecad_dependent, c.status AS status, c.retry AS retry, c.cycle AS cycle,"
        " c.origin AS origin, c.panel_id AS panel_id, c.opinion_id AS opinion_id,"
        " c.carried_from_opinion_id AS carried_from_opinion_id"
        " FROM rr_roster r LEFT JOIN rr_coverage c ON c.target_key = r.target_key AND c.agent_key = r.agent_key"
        " WHERE r.target_key = ? ORDER BY r.domain ASC, r.rank_in_domain ASC, r.agent_key ASC",
        (target_key,),
    )
    return [dict(r) for r in rows]


def tier_rank_cap(tier: str, domain_size: int) -> int | None:
    """Tier 의 rank_in_domain 상한 — A 는 1, B 는 ceil(0.3·|d|), C 는 제한 없음(None)."""
    if tier not in TIERS:
        raise AppError("E100", f"모르는 tier — {tier!r}. 허용 {list(TIERS)}.", 422)
    if tier == "A":
        return 1
    if tier == "B":
        return max(1, math.ceil(B_TIER_RATIO * domain_size))
    return None


def _in_tier(rank: Any, cap: int | None) -> bool:
    if cap is None:
        return True
    return isinstance(rank, int) and rank <= cap


def _domain_sizes(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for row in rows:
        sizes[row["domain"]] = sizes.get(row["domain"], 0) + 1
    return sizes


# ---------------------------------------------------------------- 지정 도구·예산(plan §6.6.4·§6.10.2)
def planned_tools(store: Any, target_key: str) -> list[str]:
    """패널 공통 지정 도구(≤6) — diff 는 pair 조합, snap 은 single 조합. 전사 분포 도구는 넣지 않는다."""
    row = store.query_one("SELECT kind, report_ids_json FROM rr_targets WHERE target_key = ?", (target_key,))
    if row is None:
        raise AppError("E404", f"타깃이 없습니다: {target_key}", 404)
    try:
        report_ids = json.loads(row["report_ids_json"] or "[]")
    except ValueError:
        report_ids = []
    report_ids = report_ids if isinstance(report_ids, list) else []
    if row["kind"] == "diff":
        tools = ["list_interfaces", "interface_graph"]
        if report_ids:
            tools.append("report_part_risk")
        if len(report_ids) >= 2:
            tools.append("compare_reports")
    else:
        tools = ["list_interfaces", "interface_graph", "inspect_report"]
        if report_ids:
            tools.append("report_part_risk")
    return tools[:MAX_TOOLS]


def panel_budget(seats_n: int, rounds: int, tools: Sequence[str], cap: int) -> dict:
    """사전 예산 산정(plan §6.10.2) — est_high 가 cap 을 넘으면 rounds 2, 그래도 넘으면 tools 2개로 줄인다.

    S = 좌석 수(adversary 포함), R = rounds, T = 지정 도구 수.
    est_low = S·R + S·(R−1)·2 + T + 3 · est_high = S·R·2 + S·(R−1)·4 + 2T + 3.
    """
    def estimate(s: int, r: int, t: int) -> tuple[int, int]:
        low = s * r + s * (r - 1) * 2 + t + 3
        high = s * r * 2 + s * (r - 1) * 4 + 2 * t + 3
        return low, high

    planned = list(tools)
    est_low, est_high = estimate(seats_n, rounds, len(planned))
    rounds_planned = rounds
    if est_high > cap:
        rounds_planned = 2
        est_low, est_high = estimate(seats_n, rounds_planned, len(planned))
    if est_high > cap:
        planned = [t for t in MINIMAL_TOOLS]
        est_low, est_high = estimate(seats_n, rounds_planned, len(planned))
    return {
        "S": seats_n,
        "R": rounds,
        "T": len(planned),
        "est_low": est_low,
        "est_high": est_high,
        "cap": cap,
        "rounds_planned": rounds_planned,
        "tools_planned": planned,
    }


def tier_plan(store: Any, target_key: str, *, settings: Any | None = None) -> dict:
    """로스터 실측에서 Tier 별 좌석·패널 수(= ceil(추가 좌석 / 5))와 비용 추정을 다시 계산한다(plan §6.4.1)."""
    cfg = _cfg(settings)
    rows = _roster_rows(store, target_key)
    if not rows:
        raise AppError("E404", f"로스터가 비어 있습니다: {target_key}", 404)
    sizes = _domain_sizes(rows)
    active = [r for r in rows if r["status"] != "deferred"]

    domains: dict[str, dict] = {}
    for dom, size in sorted(sizes.items()):
        d_rows = [r for r in rows if r["domain"] == dom]
        d_deferred = sum(1 for r in d_rows if r["status"] == "deferred")
        domains[dom] = {
            "size": size,
            "deferred": d_deferred,
            "active": size - d_deferred,
            "b_cut": tier_rank_cap("B", size),
        }

    cumulative: dict[str, int] = {}
    for tier in TIERS:
        cumulative[tier] = sum(1 for r in active if _in_tier(r["rank_in_domain"], tier_rank_cap(tier, sizes[r["domain"]])))

    tools = planned_tools(store, target_key)
    budget = panel_budget(PANEL_SEATS, ROUNDS, tools, cfg.risk_panel_llm_cap)

    tiers: list[dict] = []
    prev = 0
    for tier in TIERS:
        added = max(0, cumulative[tier] - prev)
        panels = math.ceil(added / ROSTER_SEATS) if added else 0
        tiers.append({
            "tier": tier,
            "cumulative_seats": cumulative[tier],
            "added_seats": added,
            "panels": panels,
            "llm_calls_low": panels * budget["est_low"],
            "llm_calls_high": panels * budget["est_high"],
        })
        prev = cumulative[tier]

    panels_total = sum(t["panels"] for t in tiers)
    return {
        "roster_size": len(rows),
        "deferred": len(rows) - len(active),
        "domains": domains,
        "tiers": tiers,
        "panels_total": panels_total,
        "budget": budget,
        "cost_estimate": {
            "panels": panels_total,
            "llm_calls_low": panels_total * budget["est_low"],
            "llm_calls_high": panels_total * budget["est_high"],
            "wall_clock_min_low": panels_total * PANEL_WALL_CLOCK_MIN[0],
            "wall_clock_min_high": panels_total * PANEL_WALL_CLOCK_MIN[1],
        },
    }


# ---------------------------------------------------------------- 편성(plan §6.4.2)
def _queues(rows: Sequence[Mapping[str, Any]], tier: str, sizes: Mapping[str, int]) -> dict[str, list[dict]]:
    """Tier 범위 안의 pending 행을 도메인별 큐(rank asc, agent_key asc)로 만든다."""
    queues: dict[str, list[dict]] = {}
    for row in rows:
        if row["status"] != "pending":
            continue
        if not _in_tier(row["rank_in_domain"], tier_rank_cap(tier, sizes[row["domain"]])):
            continue
        queues.setdefault(row["domain"], []).append(dict(row))
    for dom in queues:
        queues[dom].sort(key=lambda r: ((r["rank_in_domain"] if isinstance(r["rank_in_domain"], int) else 10**9), r["agent_key"]))
    return {d: q for d, q in queues.items() if q}


def _domain_cap(domain: str, base_cap: int, tier: str) -> int:
    """한 패널에서 같은 도메인이 가질 수 있는 좌석 수 — 기본 1, 잔량 도메인이 4 미만이면 2, Tier C 의 xd 는 최대 3."""
    if tier == "C" and domain == TIER_C_XD_DOMAIN and base_cap > 1:
        return TIER_C_XD_MAX
    return base_cap


def _reserve_non_xd(tier: str, seats: Sequence[Mapping[str, Any]], queues: Mapping[str, list], remaining_slots: int) -> bool:
    """Tier C 비-xd ≥2 강제 — 공급이 있을 때만이고, 남은 슬롯이 정확히 필요분이면 xd 를 후보에서 뺀다."""
    if tier != "C":
        return False
    have = sum(1 for s in seats if s["domain"] != TIER_C_XD_DOMAIN)
    if have >= TIER_C_NON_XD_MIN:
        return False
    supply = sum(len(q) for d, q in queues.items() if d != TIER_C_XD_DOMAIN)
    need = min(TIER_C_NON_XD_MIN - have, supply)
    return need > 0 and need >= remaining_slots


def _pick_seats(queues: dict[str, list[dict]], tier: str, adj: Mapping[str, Sequence[str]]) -> list[dict]:
    """primary 4석(서로 다른 도메인, 잔량 최대부터 라운드로빈) + counter 1석(인접 표)."""
    seats: list[dict] = []
    counts: dict[str, int] = {}
    for slot in range(PRIMARY_SEATS):
        available = sorted(d for d, q in queues.items() if q)
        if not available:
            break
        base_cap = 1 if len(available) >= PRIMARY_SEATS else 2
        candidates = [d for d in available if counts.get(d, 0) < _domain_cap(d, base_cap, tier)]
        if _reserve_non_xd(tier, seats, queues, PRIMARY_SEATS - slot):
            candidates = [d for d in candidates if d != TIER_C_XD_DOMAIN]
        if not candidates:
            break
        # 잔량이 가장 큰 도메인부터, 동률이면 도메인명 asc.
        pick = min(candidates, key=lambda d: (-len(queues[d]), d))
        row = queues[pick].pop(0)
        if not queues[pick]:
            del queues[pick]
        counts[pick] = counts.get(pick, 0) + 1
        seats.append({
            "key": row["agent_key"],
            "domain": row["domain"],
            "origin": "primary",
            "rank_in_domain": row["rank_in_domain"],
        })

    if seats:
        seated = {s["domain"] for s in seats}
        choice: str | None = None
        for seat in seats:
            for dom in adj.get(seat["domain"], ()):
                if dom not in seated and queues.get(dom):
                    choice = dom
                    break
            if choice:
                break
        if choice is None:
            rest = [d for d, q in queues.items() if q and d not in seated]
            if rest:
                choice = min(rest, key=lambda d: (-len(queues[d]), d))
        if choice:
            row = queues[choice].pop(0)
            if not queues[choice]:
                del queues[choice]
            seats.append({
                "key": row["agent_key"],
                "domain": row["domain"],
                "origin": "counter",
                "rank_in_domain": row["rank_in_domain"],
            })
    return seats


def plan_next_panel(
    store: Any,
    target_key: str,
    tier: str,
    *,
    modifiers: Sequence[str] | None = None,
    settings: Any | None = None,
) -> dict | None:
    """다음 패널 1건을 편성한다(좌석 선점 + rr_panels 행). Tier 범위에 pending 이 없으면 None.

    같은 원장 상태·같은 Settings 면 같은 seats_json 이 나온다. 동시 편성으로 선점 rowcount 가 좌석 수와 다르면
    트랜잭션을 롤백하고 None 을 돌려준다(호출자는 다음 주기에 다시 시도한다).

    **바깥 트랜잭션 안에서 부르지 마라.** `RiskStore.tx` 는 재진입 시 rollback 없이 합류만 하므로(risk_store.py),
    여기서 PlanConflict 를 흡수해도 좌석 선점 UPDATE 가 바깥 커밋에 실려 나간다 — 반쪽 저장이다.
    """
    if tier not in TIERS:
        raise AppError("E100", f"모르는 tier — {tier!r}. 허용 {list(TIERS)}.", 422)
    cfg = _cfg(settings)
    target = store.query_one("SELECT target_key, owner_sub, kind FROM rr_targets WHERE target_key = ?", (target_key,))
    if target is None:
        raise AppError("E404", f"타깃이 없습니다: {target_key}", 404)

    rows = _roster_rows(store, target_key)
    sizes = _domain_sizes(rows)
    queues = _queues(rows, tier, sizes)
    if not queues:
        return None
    seats = _pick_seats(queues, tier, adjacency(cfg))
    if not seats:
        return None

    mods = resolve_modifiers(modifiers)
    tools = planned_tools(store, target_key)
    budget = panel_budget(len(seats) + 1, ROUNDS, tools, cfg.risk_panel_llm_cap)
    seats_json = canonical_json(seats)
    panel_id = new_uuid()
    now = now_epoch()

    try:
        with store.tx() as conn:
            claimed = 0
            for seat in seats:
                conn.execute(
                    "INSERT OR IGNORE INTO rr_coverage(target_key, agent_key, owner_sub, domain, status, updated_at)"
                    " VALUES (?, ?, ?, ?, 'pending', ?)",
                    (target_key, seat["key"], target["owner_sub"], seat["domain"], now),
                )
                cur = conn.execute(
                    "UPDATE rr_coverage SET status = 'assigned', panel_id = ?, origin = ?, tier = ?, updated_at = ?"
                    " WHERE target_key = ? AND agent_key = ? AND status = 'pending'",
                    (panel_id, seat["origin"], tier, now, target_key, seat["key"]),
                )
                claimed += cur.rowcount
            if claimed != len(seats):
                raise PlanConflict(f"좌석 선점 rowcount {claimed} ≠ 좌석 수 {len(seats)}")
            row = conn.execute(
                "SELECT COALESCE(MAX(panel_no), 0) + 1 AS next_no FROM rr_panels WHERE target_key = ?", (target_key,)
            ).fetchone()
            panel_no = int(row["next_no"])
            conn.execute(
                "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, tier, seats_json, chair_template,"
                " modifiers_json, rounds, engine, tool_mode, status, budget_json, llm_calls_planned, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'web', 'tools', 'planned', ?, ?, ?)",
                (
                    panel_id, target_key, target["owner_sub"], panel_no, tier, seats_json, CHAIR_TEMPLATE,
                    canonical_json(list(mods)), budget["rounds_planned"], canonical_json(budget),
                    budget["est_high"], now,
                ),
            )
    except PlanConflict:
        return None

    return {
        "id": panel_id,
        "target_key": target_key,
        "owner_sub": target["owner_sub"],
        "panel_no": panel_no,
        "tier": tier,
        "seats": seats,
        "seats_json": seats_json,
        "modifiers": list(mods),
        "rounds": budget["rounds_planned"],
        "tools": list(budget["tools_planned"]),
        "budget": budget,
        "status": "planned",
        "created_at": now,
    }


def resolve_modifiers(modifiers: Sequence[str] | None) -> tuple[str, ...]:
    """화이트리스트 5종 안의 합집합. toulmin 은 언제나 남는다(plan §6.6.3). 순서는 화이트리스트 순서로 고정."""
    chosen = set(DEFAULT_MODIFIERS)
    for name in modifiers or ():
        if name in MODIFIER_WHITELIST:
            chosen.add(name)
    return tuple(m for m in MODIFIER_WHITELIST if m in chosen)


# ---------------------------------------------------------------- 커버리지 상태기계(plan §6.8)
def seat_status(
    *,
    turns_n: int,
    decision_ok: bool,
    used_tool: bool | None,
    cited_refs_n: int,
    abstained: bool = False,
) -> str:
    """좌석 1석의 종결 상태를 정한다(plan §6.8.2).

    turn 0 → failed · 기권/판정 불가 → abstain · used_tool 또는 cited_refs≠∅ → done · 둘 다 없으면 done_weak.
    used_tool 이 None(evidence_only·events 없음)이면 cited_refs 만으로 done/done_weak 를 가른다.
    """
    if turns_n <= 0 or not decision_ok:
        return "failed"
    if abstained:
        return "abstain"
    if used_tool is None:
        return "done" if cited_refs_n > 0 else "done_weak"
    return "done" if (used_tool or cited_refs_n > 0) else "done_weak"


def _guard(from_status: str, to_status: str) -> None:
    if from_status not in ALLOWED_TRANSITIONS:
        raise AppError("E100", f"모르는 커버리지 상태 — {from_status!r}.", 422)
    if to_status not in ALLOWED_TRANSITIONS[from_status]:
        raise AppError("E100", f"허용되지 않는 전이 {from_status} → {to_status}.", 409)


def _panel_seat_keys(store: Any, panel_id: str) -> tuple[dict, list[dict]]:
    panel = store.query_one(
        "SELECT id, target_key, owner_sub, panel_no, tier, seats_json, status FROM rr_panels WHERE id = ?", (panel_id,)
    )
    if panel is None:
        raise AppError("E404", f"패널이 없습니다: {panel_id}", 404)
    try:
        seats = json.loads(panel["seats_json"])
    except ValueError as exc:
        raise AppError("E300", f"seats_json 을 읽을 수 없습니다: {panel_id} — {exc}") from exc
    return dict(panel), [s for s in seats if isinstance(s, dict)]


def start_panel_seats(store: Any, panel_id: str) -> int:
    """assigned → running(패널 시작). 갱신한 좌석 수를 돌려준다."""
    panel, seats = _panel_seat_keys(store, panel_id)
    now = now_epoch()
    updated = 0
    with store.tx() as conn:
        for seat in seats:
            cur = conn.execute(
                "UPDATE rr_coverage SET status = 'running', started_at = ?, updated_at = ?"
                " WHERE target_key = ? AND agent_key = ? AND status = 'assigned'",
                (now, now, panel["target_key"], seat["key"]),
            )
            updated += cur.rowcount
        conn.execute(
            "UPDATE rr_panels SET status = 'running', started_at = ? WHERE id = ?", (now, panel_id)
        )
    return updated


def apply_seat_results(
    store: Any,
    panel_id: str,
    results: Sequence[Mapping[str, Any]],
    *,
    decision_ok: bool = True,
    model: str | None = None,
) -> dict:
    """패널 좌석의 종결 상태를 기록한다(plan §6.7 9단계).

    results 항목 = {agent_key, turns_n, used_tool, cited_refs_n, abstained?, opinion_id?}.
    결과가 없는 좌석은 turn 0 으로 보고 failed → retry+1 → pending(retry≤2) 또는 skipped(reason=no_turn) 로 간다.
    """
    panel, seats = _panel_seat_keys(store, panel_id)
    by_key = {str(r.get("agent_key")): r for r in results}
    now = now_epoch()
    outcome: list[dict] = []
    with store.tx() as conn:
        for seat in seats:
            key = seat["key"]
            item = by_key.get(key)
            status = seat_status(
                turns_n=int((item or {}).get("turns_n") or 0),
                decision_ok=decision_ok,
                used_tool=(item or {}).get("used_tool"),
                cited_refs_n=int((item or {}).get("cited_refs_n") or 0),
                abstained=bool((item or {}).get("abstained")),
            )
            row = conn.execute(
                "SELECT status, retry FROM rr_coverage WHERE target_key = ? AND agent_key = ?",
                (panel["target_key"], key),
            ).fetchone()
            if row is None or row["status"] not in ACTIVE_STATUSES:
                outcome.append({"agent_key": key, "status": row["status"] if row else None, "updated": False})
                continue
            if status == "failed":
                retry = int(row["retry"] or 0) + 1
                final = "pending" if retry <= MAX_SEAT_RETRY else "skipped"
                reason = None if final == "pending" else "no_turn"
                conn.execute(
                    "UPDATE rr_coverage SET status = ?, retry = ?, reason = ?, panel_id = NULL, origin = NULL,"
                    " finished_at = ?, updated_at = ? WHERE target_key = ? AND agent_key = ?",
                    (final, retry, reason, now if final == "skipped" else None, now, panel["target_key"], key),
                )
                outcome.append({"agent_key": key, "status": final, "retry": retry, "updated": True})
                continue
            conn.execute(
                "UPDATE rr_coverage SET status = ?, opinion_id = ?, model = ?, finished_at = ?, updated_at = ?"
                " WHERE target_key = ? AND agent_key = ?",
                (status, (item or {}).get("opinion_id"), model, now, now, panel["target_key"], key),
            )
            outcome.append({"agent_key": key, "status": status, "updated": True})
    by_status: dict[str, int] = {}
    for item in outcome:
        if item["status"]:
            by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    return {"seats": outcome, "by_status": by_status}


def fail_panel_seats(store: Any, panel_id: str, *, reason: str = "engine_fail") -> dict:
    """패널 error — 좌석 전부 pending(retry+1), retry > 2 면 skipped(reason)."""
    panel, seats = _panel_seat_keys(store, panel_id)
    now = now_epoch()
    outcome: list[dict] = []
    with store.tx() as conn:
        for seat in seats:
            row = conn.execute(
                "SELECT status, retry FROM rr_coverage WHERE target_key = ? AND agent_key = ?",
                (panel["target_key"], seat["key"]),
            ).fetchone()
            if row is None or row["status"] not in ACTIVE_STATUSES:
                continue
            retry = int(row["retry"] or 0) + 1
            final = "pending" if retry <= MAX_SEAT_RETRY else "skipped"
            conn.execute(
                "UPDATE rr_coverage SET status = ?, retry = ?, reason = ?, panel_id = NULL, origin = NULL,"
                " finished_at = ?, updated_at = ? WHERE target_key = ? AND agent_key = ?",
                (final, retry, None if final == "pending" else reason, now if final == "skipped" else None, now,
                 panel["target_key"], seat["key"]),
            )
            outcome.append({"agent_key": seat["key"], "status": final, "retry": retry})
    return {"seats": outcome}


def skip_seat(store: Any, target_key: str, agent_key: str, reason: str) -> dict:
    """사용자 조작 — 비종결 좌석을 skipped(reason 필수)로 닫는다."""
    if not reason:
        raise AppError("E100", "skipped 에는 reason 이 필요합니다.", 422)
    row = store.query_one(
        "SELECT status FROM rr_coverage WHERE target_key = ? AND agent_key = ?", (target_key, agent_key)
    )
    if row is None:
        raise AppError("E404", f"원장 행이 없습니다: {target_key}:{agent_key}", 404)
    _guard(row["status"], "skipped")
    now = now_epoch()
    store.execute(
        "UPDATE rr_coverage SET status = 'skipped', reason = ?, finished_at = ?, updated_at = ?"
        " WHERE target_key = ? AND agent_key = ?",
        (reason, now, now, target_key, agent_key),
    )
    return {"target_key": target_key, "agent_key": agent_key, "status": "skipped", "reason": reason}


def revert_carried(store: Any, target_key: str, agent_key: str) -> dict:
    """carried → pending(cycle+1) 되돌리기(사용자 조작). carried_from_opinion_id 는 남긴다."""
    row = store.query_one(
        "SELECT status, cycle FROM rr_coverage WHERE target_key = ? AND agent_key = ?", (target_key, agent_key)
    )
    if row is None:
        raise AppError("E404", f"원장 행이 없습니다: {target_key}:{agent_key}", 404)
    _guard(row["status"], "pending")
    cycle = int(row["cycle"] or 1) + 1
    now = now_epoch()
    store.execute(
        "UPDATE rr_coverage SET status = 'pending', cycle = ?, reason = NULL, finished_at = NULL, updated_at = ?"
        " WHERE target_key = ? AND agent_key = ?",
        (cycle, now, target_key, agent_key),
    )
    return {"target_key": target_key, "agent_key": agent_key, "status": "pending", "cycle": cycle}


def apply_carry_over(
    store: Any,
    target_key: str,
    prev_target_key: str,
    cited_ckeys: Mapping[str, Sequence[str]],
    changed_ckeys: Iterable[str],
    *,
    settings: Any | None = None,
) -> dict:
    """이전 타깃의 done 좌석을 새 타깃에서 carried 로 넘긴다(plan §6.8.2 네 조건).

    조건 — 이전 상태 done · cited_refs≠∅ · used_tool(tool_calls_ok≥1) · 인용 ckey ∩ 변경 ckey = ∅ ·
    finished_at ≥ now − risk_carried_days. `cited_ckeys` 는 좌석별 인용 ckey 집합(호출자가 diff/IR 로 해석해 넘긴다),
    `changed_ckeys` 는 이전 스냅샷 → 새 스냅샷에서 바뀐 ckey 집합이다. risk_carried_days=0 이면 아무도 넘기지 않는다.
    """
    cfg = _cfg(settings)
    days = int(cfg.risk_carried_days)
    if days <= 0:
        return {"carried": 0, "seats": []}
    changed = {str(c) for c in changed_ckeys}
    cutoff = now_epoch() - days * 86400
    rows = store.query(
        "SELECT c.agent_key AS agent_key, c.opinion_id AS opinion_id, c.finished_at AS finished_at,"
        " o.tool_calls_ok AS tool_calls_ok, o.cited_refs_json AS cited_refs_json"
        " FROM rr_coverage c LEFT JOIN rr_seat_opinions o ON o.opinion_id = c.opinion_id"
        " WHERE c.target_key = ? AND c.status = 'done' ORDER BY c.agent_key ASC",
        (prev_target_key,),
    )
    now = now_epoch()
    carried: list[dict] = []
    with store.tx() as conn:
        for row in rows:
            if not row["opinion_id"] or int(row["finished_at"] or 0) < cutoff:
                continue
            if not (row["tool_calls_ok"] or 0) >= 1:
                continue
            try:
                cited = json.loads(row["cited_refs_json"] or "[]")
            except ValueError:
                cited = []
            if not cited:
                continue
            seat_ckeys = {str(c) for c in cited_ckeys.get(row["agent_key"], ())}
            if seat_ckeys & changed:
                continue
            cur = conn.execute(
                "UPDATE rr_coverage SET status = 'carried', carried_from_opinion_id = ?, finished_at = ?,"
                " updated_at = ? WHERE target_key = ? AND agent_key = ? AND status = 'pending'",
                (row["opinion_id"], now, now, target_key, row["agent_key"]),
            )
            if cur.rowcount:
                carried.append({"agent_key": row["agent_key"], "carried_from_opinion_id": row["opinion_id"]})
    return {"carried": len(carried), "seats": carried}


# ---------------------------------------------------------------- 회계 조회·불변식(plan §6.8.3)
def coverage_summary(store: Any, target_key: str) -> dict:
    """진행판 원천 — 상태별·도메인별 집계, 미착석 수, strong 비율(done/(done+done_weak))."""
    rows = _roster_rows(store, target_key)
    by_status: dict[str, int] = {s: 0 for s in sorted(ALL_STATUSES)}
    by_domain: dict[str, dict[str, int]] = {}
    for row in rows:
        status = row["status"] or "pending"
        by_status[status] = by_status.get(status, 0) + 1
        by_domain.setdefault(row["domain"], {})
        by_domain[row["domain"]][status] = by_domain[row["domain"]].get(status, 0) + 1
    done, weak = by_status.get("done", 0), by_status.get("done_weak", 0)
    unseated = sum(by_status.get(s, 0) for s in OPEN_STATUSES)
    return {
        "roster_size": len(rows),
        "by_status": by_status,
        "by_domain": {d: by_domain[d] for d in sorted(by_domain)},
        "terminal_n": len(rows) - unseated,
        "unseated_n": unseated,
        "strong": {"done": done, "done_weak": weak, "ratio": (done / (done + weak)) if (done + weak) else None},
    }


def check_invariants(store: Any, target_key: str) -> list[str]:
    """plan §6.8.3 의 원장 불변식 위반 목록(빈 리스트 = 통과). 4·6·7 은 러너·테스트가 따로 검사한다."""
    problems: list[str] = []
    rows = _roster_rows(store, target_key)
    summary = coverage_summary(store, target_key)
    if sum(summary["by_status"].values()) != len(rows):
        problems.append("(1) 상태별 카운트 합이 roster_size 와 다르다.")

    running_panels = store.query(
        "SELECT id FROM rr_panels WHERE target_key = ? AND status = 'running' ORDER BY panel_no ASC", (target_key,)
    )
    running_seats = summary["by_status"].get("running", 0)
    if len(running_panels) > 1:
        problems.append(f"(2) 타깃당 running 패널이 {len(running_panels)} 개다(≤1).")
    if running_seats > ROSTER_SEATS * max(1, len(running_panels)) or (running_seats and not running_panels):
        problems.append(f"(2) running 좌석 {running_seats} 이 running 패널 {len(running_panels)} 개의 상한을 넘는다.")

    for row in rows:
        if row["status"] in ("done", "done_weak", "abstain") and not row["opinion_id"]:
            problems.append(f"(3) {row['agent_key']} 가 {row['status']} 인데 opinion_id 가 없다.")
        if row["status"] == "carried" and not row["carried_from_opinion_id"]:
            problems.append(f"(3) {row['agent_key']} 가 carried 인데 carried_from_opinion_id 가 없다.")

    roster_keys = {r["agent_key"] for r in rows}
    for panel in store.query("SELECT id, seats_json FROM rr_panels WHERE target_key = ?", (target_key,)):
        try:
            seats = json.loads(panel["seats_json"])
        except ValueError:
            problems.append(f"(5) 패널 {panel['id']} 의 seats_json 을 읽을 수 없다.")
            continue
        for seat in seats:
            if seat.get("key") not in roster_keys:
                problems.append(f"(5) 패널 {panel['id']} 의 좌석 {seat.get('key')} 가 로스터에 없다.")
    return problems
