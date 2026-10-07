# planner.py 시험 — 로스터 고정·Tier 산술(plan §6.3·§6.4.1)·편성 결정론(§6.4.2)·커버리지 상태기계와 불변식(§6.8)
from __future__ import annotations

import dataclasses
import json
import math
from contextlib import contextmanager

import pytest

from app import config, planner
from app.common import now_epoch
from app.errors import AppError

# plan §6.3 끝 문단의 실측 도메인 규모(합 359 — plan 본문은 이를 ≈350 으로 반올림해 Tier C 패널 수를 적는다).
PLAN_SIZES: dict[str, int] = {
    "xd": 122, "sim": 22, "cam": 21, "rel": 20, "soc": 20, "disp": 19, "mech": 19, "pcb": 19,
    "rf": 19, "passive": 18, "pwr": 18, "sh": 17, "mem": 16, "std": 8, "material": 1,
}
# plan §6.4.1 산술 줄의 도메인별 ceil(0.3·|d|).
PLAN_B_CUT: dict[str, int] = {
    "xd": 37, "sim": 7, "cam": 7, "rel": 6, "soc": 6, "disp": 6, "mech": 6, "pcb": 6,
    "rf": 6, "passive": 6, "pwr": 6, "sh": 6, "mem": 5, "std": 3, "material": 1,
}


# ---------------------------------------------------------------- 픽스처 위의 소도구
def agents(sizes: dict[str, int]) -> list[dict]:
    """도메인별 n 명의 전문가 목록. relevance 는 내림차순이라 rank_in_domain 이 인덱스+1 이 된다."""
    return [
        {"key": f"{dom}-a{i:03d}", "domain": dom, "relevance": (n - i) / 100.0}
        for dom, n in sizes.items()
        for i in range(n)
    ]


def make_target(store, target_key: str = "t1", *, kind: str = "diff", report_ids: list | None = None) -> str:
    now = now_epoch()
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, external_sync_json,"
        " report_ids_json, level, created_at, updated_at) VALUES (?, 'u@x', ?, 'r1', 'p1', 'h1', '{}', ?, 'C0', ?, ?)",
        (target_key, kind, json.dumps(report_ids or []), now, now),
    )
    return target_key


def seeded(store, sizes: dict[str, int], *, ecad_absent: bool = False, kind: str = "diff") -> str:
    target_key = make_target(store, kind=kind)
    planner.freeze_roster(store, target_key, "u@x", agents(sizes), ecad_absent=ecad_absent)
    return target_key


def coverage(store, target_key: str) -> dict[str, dict]:
    rows = store.query(
        "SELECT agent_key, domain, status, tier, origin, panel_id, retry, cycle, reason, opinion_id,"
        " carried_from_opinion_id FROM rr_coverage WHERE target_key = ?",
        (target_key,),
    )
    return {r["agent_key"]: dict(r) for r in rows}


def set_status(store, target_key: str, agent_key: str, status: str, **cols) -> None:
    sets = ", ".join(f"{name} = ?" for name in cols)
    sql = "UPDATE rr_coverage SET status = ?" + (", " + sets if sets else "") + \
          " WHERE target_key = ? AND agent_key = ?"
    store.execute(sql, (status, *cols.values(), target_key, agent_key))


# ---------------------------------------------------------------- 도메인·인접 표
def test_domain_of_is_prefix_before_first_dash():
    assert planner.domain_of("mech-housing-structure") == "mech"
    assert planner.domain_of("XD-Mech-Assembly") == "xd"


def test_adjacency_default_table_matches_plan():
    table = planner.adjacency()
    # plan §6.4.2 3단계 인접 표 v1 전문.
    assert table["mech"] == ("pcb", "disp", "sh")
    assert table["pcb"] == ("mech", "pwr", "rf", "std")
    assert table["xd"] == ("mech", "disp", "cam")
    assert set(table) == set(PLAN_SIZES)


def test_adjacency_settings_override_and_bad_json():
    override = dataclasses.replace(config.settings, risk_adjacency=json.dumps({"mech": ["sim"]}))
    assert planner.adjacency(override) == {"mech": ("sim",)}
    with pytest.raises(AppError) as exc:
        planner.adjacency(dataclasses.replace(config.settings, risk_adjacency="{not json"))
    assert exc.value.code == "E100"


# ---------------------------------------------------------------- 로스터 고정(plan §6.3)
def test_freeze_roster_ranks_by_relevance_then_key(risk_store):
    target_key = make_target(risk_store)
    rows = [
        {"key": "mech-b", "domain": "mech", "relevance": 0.5},
        {"key": "mech-a", "domain": "mech", "relevance": 0.5},   # 동률이면 agent_key asc
        {"key": "mech-c", "domain": "mech", "relevance": 0.9},
        {"key": "sw-x", "domain": "sw", "relevance": 1.0},       # 화이트리스트 밖 도메인은 버린다
        {"key": "sim-a", "relevance": 0.1},                      # domain 미제공 → 키 접두사
    ]
    out = planner.freeze_roster(risk_store, target_key, "u@x", rows)
    assert out["roster_size"] == 4 and out["deferred"] == 0

    ranked = {
        r["agent_key"]: r["rank_in_domain"]
        for r in risk_store.query(
            "SELECT agent_key, rank_in_domain FROM rr_roster WHERE target_key = ?", (target_key,)
        )
    }
    assert ranked == {"mech-c": 1, "mech-a": 2, "mech-b": 3, "sim-a": 1}
    assert {k: v["status"] for k, v in coverage(risk_store, target_key).items()} == {
        "mech-c": "pending", "mech-a": "pending", "mech-b": "pending", "sim-a": "pending",
    }
    frozen = risk_store.query_one(
        "SELECT roster_frozen_at, planner_version FROM rr_targets WHERE target_key = ?", (target_key,)
    )
    assert frozen["roster_frozen_at"] == out["frozen_at"]
    assert frozen["planner_version"] == planner.PLANNER_VERSION


def test_freeze_roster_defers_ecad_dependents_except_rank_one(risk_store):
    target_key = seeded(risk_store, {"pcb": 3, "mech": 2}, ecad_absent=True)
    rows = coverage(risk_store, target_key)
    assert rows["pcb-a000"]["status"] == "pending"                     # rank 1 대표는 남는다
    assert rows["pcb-a001"]["status"] == "deferred"
    assert rows["pcb-a001"]["reason"] == "ecad_absent"
    assert rows["pcb-a002"]["status"] == "deferred"
    assert rows["mech-a000"]["status"] == "pending" and rows["mech-a001"]["status"] == "pending"
    assert {r["agent_key"]: r["ecad_dependent"] for r in risk_store.query(
        "SELECT agent_key, ecad_dependent FROM rr_roster WHERE target_key = ?", (target_key,))} == {
        "pcb-a000": 1, "pcb-a001": 1, "pcb-a002": 1, "mech-a000": 0, "mech-a001": 0,
    }


def test_freeze_roster_twice_does_not_overwrite(risk_store):
    target_key = seeded(risk_store, {"mech": 2})
    set_status(risk_store, target_key, "mech-a000", "done", opinion_id="op1")
    planner.freeze_roster(risk_store, target_key, "u@x", agents({"mech": 2}))
    assert coverage(risk_store, target_key)["mech-a000"]["status"] == "done"


def test_refresh_roster_appends_only_new_keys(risk_store):
    target_key = seeded(risk_store, {"mech": 2})
    grown = agents({"mech": 2}) + [{"key": "mech-new", "domain": "mech", "relevance": 9.9}]
    out = planner.refresh_roster(risk_store, target_key, grown)
    assert out["added_pending"] == 1
    ranked = {
        r["agent_key"]: r["rank_in_domain"]
        for r in risk_store.query("SELECT agent_key, rank_in_domain FROM rr_roster WHERE target_key = ?", (target_key,))
    }
    # relevance 가 가장 높아도 rank 는 기존 최대 다음이다(편성 결정론 보호).
    assert ranked == {"mech-a000": 1, "mech-a001": 2, "mech-new": 3}
    assert coverage(risk_store, target_key)["mech-new"]["status"] == "pending"

    with pytest.raises(AppError) as exc:
        planner.refresh_roster(risk_store, "없는타깃", grown)
    assert exc.value.code == "E404"


# ---------------------------------------------------------------- Tier 산술(plan §6.4.1)
def test_tier_rank_cap_matches_plan_table():
    for dom, size in PLAN_SIZES.items():
        assert planner.tier_rank_cap("A", size) == 1
        assert planner.tier_rank_cap("B", size) == PLAN_B_CUT[dom]
        assert planner.tier_rank_cap("C", size) is None
    assert sum(PLAN_B_CUT.values()) == 114                     # plan §6.4.1 '합 114'
    with pytest.raises(AppError) as exc:
        planner.tier_rank_cap("D", 10)
    assert exc.value.code == "E100"


def test_tier_plan_reproduces_plan_arithmetic(risk_store):
    target_key = seeded(risk_store, PLAN_SIZES)
    out = planner.tier_plan(risk_store, target_key)
    total = sum(PLAN_SIZES.values())
    assert out["roster_size"] == total and out["deferred"] == 0
    assert {d: v["b_cut"] for d, v in out["domains"].items()} == PLAN_B_CUT

    tiers = {t["tier"]: t for t in out["tiers"]}
    assert (tiers["A"]["cumulative_seats"], tiers["A"]["added_seats"], tiers["A"]["panels"]) == (15, 15, 3)
    assert (tiers["B"]["cumulative_seats"], tiers["B"]["added_seats"], tiers["B"]["panels"]) == (114, 99, 20)
    # Tier C 는 로스터 실측 전원 — plan 표의 +48 은 총원을 ≈350 으로 반올림한 값이고, 규칙은 ceil(추가 좌석 / 5) 다.
    assert tiers["C"]["cumulative_seats"] == total
    assert tiers["C"]["added_seats"] == total - 114
    assert tiers["C"]["panels"] == math.ceil((total - 114) / planner.ROSTER_SEATS) == 49
    assert out["panels_total"] == 3 + 20 + 49

    budget = out["budget"]
    assert out["cost_estimate"] == {
        "panels": out["panels_total"],
        "llm_calls_low": out["panels_total"] * budget["est_low"],
        "llm_calls_high": out["panels_total"] * budget["est_high"],
        "wall_clock_min_low": out["panels_total"] * 10,
        "wall_clock_min_high": out["panels_total"] * 18,
    }


def test_tier_plan_with_ecad_absent(risk_store):
    target_key = seeded(risk_store, PLAN_SIZES, ecad_absent=True)
    out = planner.tier_plan(risk_store, target_key)
    ecad_total = sum(PLAN_SIZES[d] for d in config.settings.risk_ecad_domains)
    assert ecad_total == 110 and out["deferred"] == ecad_total - 6 == 104     # plan §6.3 '110 − 6 = 104'
    tiers = {t["tier"]: t for t in out["tiers"]}
    assert (tiers["A"]["cumulative_seats"], tiers["A"]["panels"]) == (15, 3)
    # plan §6.4.1 '114 − 29 = 85' 과 '+14 패널'.
    assert (tiers["B"]["cumulative_seats"], tiers["B"]["added_seats"], tiers["B"]["panels"]) == (85, 70, 14)
    active = sum(PLAN_SIZES.values()) - 104
    assert tiers["C"]["cumulative_seats"] == active
    assert tiers["C"]["panels"] == math.ceil((active - 85) / planner.ROSTER_SEATS)


def test_tier_plan_requires_roster(risk_store):
    make_target(risk_store, "t9")
    with pytest.raises(AppError) as exc:
        planner.tier_plan(risk_store, "t9")
    assert exc.value.code == "E404"


# ---------------------------------------------------------------- 지정 도구·예산(plan §6.10.2)
def test_planned_tools_by_kind_and_reports(risk_store):
    diff0 = make_target(risk_store, "d0", kind="diff")
    diff2 = make_target(risk_store, "d2", kind="diff", report_ids=[11, 12])
    snap1 = make_target(risk_store, "s1", kind="snap", report_ids=[11])
    assert planner.planned_tools(risk_store, diff0) == ["list_interfaces", "interface_graph"]
    assert planner.planned_tools(risk_store, diff2) == [
        "list_interfaces", "interface_graph", "report_part_risk", "compare_reports",
    ]
    assert planner.planned_tools(risk_store, snap1) == [
        "list_interfaces", "interface_graph", "inspect_report", "report_part_risk",
    ]
    with pytest.raises(AppError) as exc:
        planner.planned_tools(risk_store, "없음")
    assert exc.value.code == "E404"


def test_panel_budget_default_and_reduction_gates():
    tools = ["list_interfaces", "interface_graph", "report_part_risk", "compare_reports"]
    base = planner.panel_budget(planner.PANEL_SEATS, planner.ROUNDS, tools, 120)
    # plan §6.10.2 '기본 구성 est_low=49, est_high=95'.
    assert (base["S"], base["T"], base["est_low"], base["est_high"]) == (6, 4, 49, 95)
    assert base["rounds_planned"] == 3 and base["tools_planned"] == tools

    cut = planner.panel_budget(planner.PANEL_SEATS, planner.ROUNDS, tools, 60)
    assert cut["rounds_planned"] == 2 and cut["est_high"] == 59        # 재계산 est_high=59
    assert cut["tools_planned"] == tools

    both = planner.panel_budget(planner.PANEL_SEATS, planner.ROUNDS, tools, 50)
    assert both["rounds_planned"] == 2
    assert both["tools_planned"] == list(planner.MINIMAL_TOOLS)
    assert both["est_high"] == 6 * 2 * 2 + 6 * 1 * 4 + 2 * 2 + 3


def test_resolve_modifiers_keeps_toulmin_and_whitelist_order():
    assert planner.resolve_modifiers(None) == ("toulmin",)
    assert planner.resolve_modifiers(["anon1r", "voi", "없는거"]) == ("voi", "toulmin", "anon1r")


# ---------------------------------------------------------------- 편성(plan §6.4.2)
def test_plan_next_panel_seats_and_claim(risk_store):
    target_key = seeded(risk_store, {"mech": 3, "sim": 3, "rel": 2, "xd": 4, "pcb": 2})
    panel = planner.plan_next_panel(risk_store, target_key, "A")

    assert [s["origin"] for s in panel["seats"]] == ["primary"] * 4 + ["counter"]
    assert len({s["domain"] for s in panel["seats"][:4]}) == 4            # primary 는 서로 다른 도메인
    assert all(s["rank_in_domain"] == 1 for s in panel["seats"])          # Tier A = rank 1 만
    assert panel["panel_no"] == 1 and panel["status"] == "planned"
    assert panel["modifiers"] == ["toulmin"] and panel["rounds"] == 3
    assert panel["tools"] == ["list_interfaces", "interface_graph"]

    rows = coverage(risk_store, target_key)
    for seat in panel["seats"]:
        assert rows[seat["key"]]["status"] == "assigned"
        assert rows[seat["key"]]["panel_id"] == panel["id"]
        assert rows[seat["key"]]["tier"] == "A"
        assert rows[seat["key"]]["origin"] == seat["origin"]
    assert sum(1 for r in rows.values() if r["status"] == "assigned") == 5

    stored = risk_store.query_one(
        "SELECT panel_no, tier, seats_json, chair_template, modifiers_json, rounds, engine, tool_mode, status,"
        " budget_json, llm_calls_planned FROM rr_panels WHERE id = ?", (panel["id"],)
    )
    assert stored["seats_json"] == panel["seats_json"]
    assert stored["chair_template"] == planner.CHAIR_TEMPLATE == "risk-review"
    assert json.loads(stored["modifiers_json"]) == ["toulmin"]
    assert (stored["engine"], stored["tool_mode"], stored["status"]) == ("web", "tools", "planned")
    assert stored["llm_calls_planned"] == json.loads(stored["budget_json"])["est_high"]


def test_plan_next_panel_is_deterministic(risk_store):
    """같은 원장 상태·Settings 로 두 번 편성하면 같은 seats_json 이 나온다(plan §6.8.3 7)."""
    target_key = seeded(risk_store, {"mech": 3, "sim": 3, "rel": 2, "xd": 4, "pcb": 2, "disp": 2})
    first = planner.plan_next_panel(risk_store, target_key, "B")

    risk_store.execute(
        "UPDATE rr_coverage SET status = 'pending', panel_id = NULL, origin = NULL, tier = NULL"
        " WHERE target_key = ? AND status = 'assigned'", (target_key,)
    )
    risk_store.execute("DELETE FROM rr_panels WHERE target_key = ?", (target_key,))
    second = planner.plan_next_panel(risk_store, target_key, "B")

    assert second["seats_json"] == first["seats_json"]
    assert second["id"] != first["id"] and second["panel_no"] == first["panel_no"] == 1


def test_plan_next_panel_counter_comes_from_adjacency(risk_store):
    target_key = seeded(risk_store, {"mech": 5, "sim": 5, "rel": 5, "material": 5, "pcb": 1})
    panel = planner.plan_next_panel(risk_store, target_key, "C")
    primary_domains = [s["domain"] for s in panel["seats"][:4]]
    assert sorted(primary_domains) == ["material", "mech", "rel", "sim"]
    counter = panel["seats"][4]
    # mech 의 인접 표 [pcb, disp, sh] 중 pending 이 남은 pcb 가 counter 다.
    assert counter["origin"] == "counter" and counter["domain"] == "pcb"


def test_plan_next_panel_tier_c_limits_xd(risk_store):
    target_key = seeded(risk_store, {"xd": 10, "mech": 1, "sim": 1})
    first = planner.plan_next_panel(risk_store, target_key, "C")
    domains = [s["domain"] for s in first["seats"]]
    assert domains.count("xd") <= planner.TIER_C_XD_MAX
    assert sum(1 for d in domains if d != "xd") >= planner.TIER_C_NON_XD_MIN   # 비-xd 공급이 있을 때 강제

    second = planner.plan_next_panel(risk_store, target_key, "C")
    # 비-xd 공급이 마르면 xd 상한 3석만 남는다.
    assert [s["domain"] for s in second["seats"]] == ["xd"] * planner.TIER_C_XD_MAX


def test_plan_next_panel_returns_none_when_tier_exhausted(risk_store):
    target_key = seeded(risk_store, {"mech": 1, "sim": 1})
    assert planner.plan_next_panel(risk_store, target_key, "A") is not None
    assert planner.plan_next_panel(risk_store, target_key, "A") is None
    with pytest.raises(AppError) as exc:
        planner.plan_next_panel(risk_store, target_key, "Z")
    assert exc.value.code == "E100"


class _ConflictStore:
    """좌석 하나의 선점 UPDATE 만 rowcount 0 으로 만드는 저장소 프록시(동시 편성 경쟁 재현)."""

    def __init__(self, store, blocked_key: str) -> None:
        self._store = store
        self._blocked = blocked_key

    def __getattr__(self, name):
        return getattr(self._store, name)

    @contextmanager
    def tx(self):
        with self._store.tx() as conn:
            yield _ConflictConn(conn, self._blocked)


class _ConflictConn:
    def __init__(self, conn, blocked_key: str) -> None:
        self._conn = conn
        self._blocked = blocked_key

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, sql, params=()):
        if "SET status = 'assigned'" in sql and self._blocked in tuple(params):
            return _ZeroCursor()
        return self._conn.execute(sql, params)


class _ZeroCursor:
    rowcount = 0

    def fetchone(self):
        return None


def test_plan_next_panel_rolls_back_on_seat_conflict(risk_store):
    target_key = seeded(risk_store, {"mech": 1, "sim": 1, "rel": 1, "xd": 1, "pcb": 1})
    probe = planner.plan_next_panel(risk_store, target_key, "A")
    blocked = probe["seats"][0]["key"]
    risk_store.execute(
        "UPDATE rr_coverage SET status = 'pending', panel_id = NULL, origin = NULL, tier = NULL"
        " WHERE target_key = ?", (target_key,)
    )
    risk_store.execute("DELETE FROM rr_panels WHERE target_key = ?", (target_key,))

    assert planner.plan_next_panel(_ConflictStore(risk_store, blocked), target_key, "A") is None
    assert risk_store.query("SELECT id FROM rr_panels WHERE target_key = ?", (target_key,)) == []
    assert {r["status"] for r in coverage(risk_store, target_key).values()} == {"pending"}


# ---------------------------------------------------------------- 좌석 종결 규칙(plan §6.8.2)
def test_seat_status_rules():
    assert planner.seat_status(turns_n=0, decision_ok=True, used_tool=True, cited_refs_n=3) == "failed"
    assert planner.seat_status(turns_n=2, decision_ok=False, used_tool=True, cited_refs_n=3) == "failed"
    assert planner.seat_status(turns_n=2, decision_ok=True, used_tool=False, cited_refs_n=0,
                               abstained=True) == "abstain"
    assert planner.seat_status(turns_n=1, decision_ok=True, used_tool=True, cited_refs_n=0) == "done"
    assert planner.seat_status(turns_n=1, decision_ok=True, used_tool=False, cited_refs_n=2) == "done"
    assert planner.seat_status(turns_n=1, decision_ok=True, used_tool=False, cited_refs_n=0) == "done_weak"
    # 귀속 불가(evidence_only·events 없음)면 cited_refs 만으로 가른다.
    assert planner.seat_status(turns_n=1, decision_ok=True, used_tool=None, cited_refs_n=1) == "done"
    assert planner.seat_status(turns_n=1, decision_ok=True, used_tool=None, cited_refs_n=0) == "done_weak"


def test_start_panel_seats_moves_assigned_to_running(risk_store):
    target_key = seeded(risk_store, {"mech": 2, "sim": 2, "rel": 1, "xd": 1, "pcb": 1})
    panel = planner.plan_next_panel(risk_store, target_key, "A")
    assert planner.start_panel_seats(risk_store, panel["id"]) == len(panel["seats"])
    rows = coverage(risk_store, target_key)
    assert all(rows[s["key"]]["status"] == "running" for s in panel["seats"])
    assert risk_store.query_one("SELECT status FROM rr_panels WHERE id = ?", (panel["id"],))["status"] == "running"
    # 이미 running 이면 다시 옮길 좌석이 없다(멱등).
    assert planner.start_panel_seats(risk_store, panel["id"]) == 0
    with pytest.raises(AppError) as exc:
        planner.start_panel_seats(risk_store, "없는패널")
    assert exc.value.code == "E404"


def test_apply_seat_results_terminal_states_and_retry(risk_store):
    target_key = seeded(risk_store, {"mech": 1, "sim": 1, "rel": 1, "xd": 1, "pcb": 1})
    panel = planner.plan_next_panel(risk_store, target_key, "A")
    planner.start_panel_seats(risk_store, panel["id"])
    keys = [s["key"] for s in panel["seats"]]

    out = planner.apply_seat_results(
        risk_store, panel["id"],
        [
            {"agent_key": keys[0], "turns_n": 3, "used_tool": True, "cited_refs_n": 2, "opinion_id": "op0"},
            {"agent_key": keys[1], "turns_n": 3, "used_tool": False, "cited_refs_n": 0, "opinion_id": "op1"},
            {"agent_key": keys[2], "turns_n": 3, "used_tool": True, "cited_refs_n": 1, "abstained": True,
             "opinion_id": "op2"},
            {"agent_key": keys[3], "turns_n": 0, "used_tool": False, "cited_refs_n": 0},
            # keys[4] 는 결과 자체가 없다 → turn 0 취급.
        ],
        model="glm-test",
    )
    assert out["by_status"] == {"done": 1, "done_weak": 1, "abstain": 1, "pending": 2}
    rows = coverage(risk_store, target_key)
    assert (rows[keys[0]]["status"], rows[keys[0]]["opinion_id"]) == ("done", "op0")
    assert rows[keys[1]]["status"] == "done_weak"
    assert rows[keys[2]]["status"] == "abstain"
    for key in keys[3:]:
        assert (rows[key]["status"], rows[key]["retry"], rows[key]["panel_id"]) == ("pending", 1, None)
    assert risk_store.query_one(
        "SELECT model FROM rr_coverage WHERE target_key = ? AND agent_key = ?", (target_key, keys[0])
    )["model"] == "glm-test"

    # 종결된 좌석은 다시 건드리지 않는다.
    again = planner.apply_seat_results(
        risk_store, panel["id"], [{"agent_key": keys[0], "turns_n": 3, "used_tool": True, "cited_refs_n": 2}]
    )
    assert [s for s in again["seats"] if s["agent_key"] == keys[0]][0]["updated"] is False


def test_apply_seat_results_skips_after_retry_budget(risk_store):
    target_key = seeded(risk_store, {"mech": 1, "sim": 1})
    panel = planner.plan_next_panel(risk_store, target_key, "A")
    planner.start_panel_seats(risk_store, panel["id"])
    key = panel["seats"][0]["key"]
    risk_store.execute(
        "UPDATE rr_coverage SET retry = ? WHERE target_key = ? AND agent_key = ?",
        (planner.MAX_SEAT_RETRY, target_key, key),
    )
    planner.apply_seat_results(risk_store, panel["id"], [{"agent_key": key, "turns_n": 0}])
    row = coverage(risk_store, target_key)[key]
    assert (row["status"], row["retry"], row["reason"]) == ("skipped", planner.MAX_SEAT_RETRY + 1, "no_turn")


def test_fail_panel_seats_returns_seats_to_pending(risk_store):
    target_key = seeded(risk_store, {"mech": 1, "sim": 1, "rel": 1})
    panel = planner.plan_next_panel(risk_store, target_key, "A")
    planner.start_panel_seats(risk_store, panel["id"])
    out = planner.fail_panel_seats(risk_store, panel["id"])
    assert {s["status"] for s in out["seats"]} == {"pending"}
    rows = coverage(risk_store, target_key)
    assert all(rows[s["key"]]["retry"] == 1 and rows[s["key"]]["panel_id"] is None for s in panel["seats"])

    key = panel["seats"][0]["key"]
    risk_store.execute(
        "UPDATE rr_coverage SET retry = ?, status = 'running' WHERE target_key = ? AND agent_key = ?",
        (planner.MAX_SEAT_RETRY, target_key, key),
    )
    planner.fail_panel_seats(risk_store, panel["id"], reason="engine_fail")
    row = coverage(risk_store, target_key)[key]
    assert (row["status"], row["reason"]) == ("skipped", "engine_fail")


def test_fail_panel_seats_can_release_without_charging_a_retry(risk_store):
    """좌석 탓이 아닌 중단(`charge=False`)은 retry 를 올리지 않는다 — 마지막 재시도에 걸려 있던 좌석도 굳지 않는다."""
    target_key = seeded(risk_store, {"mech": 1, "sim": 1, "rel": 1})
    panel = planner.plan_next_panel(risk_store, target_key, "A")
    planner.start_panel_seats(risk_store, panel["id"])
    key = panel["seats"][0]["key"]
    risk_store.execute(
        "UPDATE rr_coverage SET retry = ? WHERE target_key = ? AND agent_key = ?",
        (planner.MAX_SEAT_RETRY, target_key, key),
    )
    out = planner.fail_panel_seats(risk_store, panel["id"], charge=False)
    assert {s["status"] for s in out["seats"]} == {"pending"}
    rows = coverage(risk_store, target_key)
    assert rows[key]["retry"] == planner.MAX_SEAT_RETRY and rows[key]["status"] == "pending"
    assert all(rows[s["key"]]["panel_id"] is None for s in panel["seats"])
    assert sorted(rows[s["key"]]["retry"] for s in panel["seats"]) == [0, 0, planner.MAX_SEAT_RETRY]
    assert planner.check_invariants(risk_store, target_key) == []


# ---------------------------------------------------------------- 사용자 조작 전이
def test_skip_seat_requires_reason_and_rejects_terminal(risk_store):
    target_key = seeded(risk_store, {"mech": 2})
    assert planner.skip_seat(risk_store, target_key, "mech-a000", "담당자 부재")["status"] == "skipped"
    assert coverage(risk_store, target_key)["mech-a000"]["reason"] == "담당자 부재"

    with pytest.raises(AppError) as exc:
        planner.skip_seat(risk_store, target_key, "mech-a001", "")
    assert exc.value.code == "E100"
    with pytest.raises(AppError) as exc:          # 종결 상태(skipped)에서 다시 skipped 는 막는다
        planner.skip_seat(risk_store, target_key, "mech-a000", "재시도")
    assert (exc.value.code, exc.value.http_status) == ("E100", 409)
    with pytest.raises(AppError) as exc:
        planner.skip_seat(risk_store, target_key, "없는사람", "x")
    assert exc.value.code == "E404"


def test_deferred_and_done_cannot_be_reverted(risk_store):
    target_key = seeded(risk_store, {"pcb": 2}, ecad_absent=True)
    with pytest.raises(AppError) as exc:          # deferred 는 타깃 안에서 바뀌지 않는다
        planner.skip_seat(risk_store, target_key, "pcb-a001", "그만")
    assert exc.value.http_status == 409
    set_status(risk_store, target_key, "pcb-a000", "done", opinion_id="op")
    with pytest.raises(AppError):
        planner.skip_seat(risk_store, target_key, "pcb-a000", "그만")


def test_revert_carried_raises_cycle(risk_store):
    target_key = seeded(risk_store, {"mech": 1})
    set_status(risk_store, target_key, "mech-a000", "carried", carried_from_opinion_id="op-prev")
    out = planner.revert_carried(risk_store, target_key, "mech-a000")
    assert {k: out[k] for k in ("target_key", "agent_key", "status", "cycle")} == {
        "target_key": target_key, "agent_key": "mech-a000", "status": "pending", "cycle": 2}
    assert out["status_source"] == "code" and out["decided_by"] is None      # 주체 없이 부르면 자동 전이다
    row = coverage(risk_store, target_key)["mech-a000"]
    # carried_from_opinion_id 는 남긴다(계보).
    assert (row["status"], row["cycle"], row["carried_from_opinion_id"]) == ("pending", 2, "op-prev")
    with pytest.raises(AppError) as exc:          # pending → pending 은 허용 전이가 아니다
        planner.revert_carried(risk_store, target_key, "mech-a000")
    assert exc.value.http_status == 409


def test_allowed_transitions_cover_every_status():
    assert set(planner.ALLOWED_TRANSITIONS) == planner.ALL_STATUSES
    for source, targets in planner.ALLOWED_TRANSITIONS.items():
        assert targets <= planner.ALL_STATUSES, source
    assert planner.TERMINAL_STATUSES & planner.OPEN_STATUSES == frozenset()
    # 종결 상태에서 나가는 유일한 길은 carried → pending 이다.
    assert {s for s in planner.TERMINAL_STATUSES if planner.ALLOWED_TRANSITIONS[s]} == {"carried"}


# ---------------------------------------------------------------- 승계(plan §6.8.2 네 조건)
def _seat_opinion(store, target_key: str, agent_key: str, opinion_id: str, *, tool_calls_ok: int,
                  cited: list[str]) -> None:
    store.execute(
        "INSERT INTO rr_seat_opinions(opinion_id, target_key, panel_id, owner_sub, agent_key, domain, origin,"
        " opinion_json, tool_calls_ok, cited_refs_json, created_at)"
        " VALUES (?, ?, 'panel-prev', 'u@x', ?, ?, 'primary', '{}', ?, ?, ?)",
        (opinion_id, target_key, agent_key, planner.domain_of(agent_key), tool_calls_ok,
         json.dumps(cited), now_epoch()),
    )


def test_apply_carry_over_moves_clean_done_seats(risk_store):
    prev = seeded(risk_store, {"mech": 2})
    make_target(risk_store, "t2")
    planner.freeze_roster(risk_store, "t2", "u@x", agents({"mech": 2}))
    now = now_epoch()
    for key, opinion in (("mech-a000", "op-a"), ("mech-a001", "op-b")):
        set_status(risk_store, prev, key, "done", opinion_id=opinion, finished_at=now)
        _seat_opinion(risk_store, prev, key, opinion, tool_calls_ok=1, cited=["[p:n1]"])

    out = planner.apply_carry_over(
        risk_store, "t2", prev,
        cited_ckeys={"mech-a000": ["ck-clean"], "mech-a001": ["ck-changed"]},
        changed_ckeys=["ck-changed"],
    )
    assert out["carried"] == 1 and out["seats"][0]["agent_key"] == "mech-a000"
    rows = coverage(risk_store, "t2")
    assert (rows["mech-a000"]["status"], rows["mech-a000"]["carried_from_opinion_id"]) == ("carried", "op-a")
    assert rows["mech-a001"]["status"] == "pending"


def test_apply_carry_over_requires_tool_and_refs_and_window(risk_store):
    prev = seeded(risk_store, {"mech": 3})
    make_target(risk_store, "t2")
    planner.freeze_roster(risk_store, "t2", "u@x", agents({"mech": 3}))
    now = now_epoch()
    cases = [
        ("mech-a000", "op-0", 0, ["[p:n1]"], now),                       # used_tool 없음
        ("mech-a001", "op-1", 1, [], now),                               # cited_refs 없음
        ("mech-a002", "op-2", 1, ["[p:n1]"], now - 200 * 86400),         # 창 밖
    ]
    for key, opinion, ok, cited, finished in cases:
        set_status(risk_store, prev, key, "done", opinion_id=opinion, finished_at=finished)
        _seat_opinion(risk_store, prev, key, opinion, tool_calls_ok=ok, cited=cited)

    assert planner.apply_carry_over(risk_store, "t2", prev, cited_ckeys={}, changed_ckeys=[])["carried"] == 0
    assert {r["status"] for r in coverage(risk_store, "t2").values()} == {"pending"}

    # risk_carried_days=0 이면 아무도 넘기지 않는다.
    off = dataclasses.replace(config.settings, risk_carried_days=0)
    assert planner.apply_carry_over(risk_store, "t2", prev, cited_ckeys={}, changed_ckeys=[],
                                    settings=off) == {"carried": 0, "seats": []}


# ---------------------------------------------------------------- 회계·불변식(plan §6.8.3)
def test_coverage_summary_counts_and_strong_ratio(risk_store):
    target_key = seeded(risk_store, {"mech": 3, "sim": 2})
    set_status(risk_store, target_key, "mech-a000", "done", opinion_id="o1")
    set_status(risk_store, target_key, "mech-a001", "done", opinion_id="o2")
    set_status(risk_store, target_key, "mech-a002", "done_weak", opinion_id="o3")
    set_status(risk_store, target_key, "sim-a000", "skipped", reason="사용자")

    out = planner.coverage_summary(risk_store, target_key)
    assert out["roster_size"] == 5
    assert out["by_status"]["done"] == 2 and out["by_status"]["done_weak"] == 1
    assert out["by_status"]["skipped"] == 1 and out["by_status"]["pending"] == 1
    assert sum(out["by_status"].values()) == 5
    assert out["by_domain"]["mech"] == {"done": 2, "done_weak": 1}
    assert (out["terminal_n"], out["unseated_n"]) == (4, 1)
    assert out["strong"] == {"done": 2, "done_weak": 1, "ratio": pytest.approx(2 / 3)}


def test_check_invariants_clean(risk_store):
    target_key = seeded(risk_store, {"mech": 2, "sim": 2, "rel": 1, "xd": 1, "pcb": 1})
    panel = planner.plan_next_panel(risk_store, target_key, "A")
    planner.start_panel_seats(risk_store, panel["id"])
    assert planner.check_invariants(risk_store, target_key) == []

    planner.apply_seat_results(
        risk_store, panel["id"],
        [{"agent_key": s["key"], "turns_n": 2, "used_tool": True, "cited_refs_n": 1, "opinion_id": f"op-{i}"}
         for i, s in enumerate(panel["seats"])],
    )
    assert planner.check_invariants(risk_store, target_key) == []


def test_check_invariants_flags_missing_opinion_and_second_running_panel(risk_store):
    target_key = seeded(risk_store, {"mech": 2, "sim": 2, "rel": 1, "xd": 1, "pcb": 1})
    panel = planner.plan_next_panel(risk_store, target_key, "A")
    planner.start_panel_seats(risk_store, panel["id"])
    # (3) done 인데 opinion_id 가 없다 · carried 인데 carried_from_opinion_id 가 없다.
    set_status(risk_store, target_key, panel["seats"][0]["key"], "done")
    set_status(risk_store, target_key, panel["seats"][1]["key"], "carried")
    # (2) 타깃당 running 패널 2개.
    risk_store.execute(
        "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, tier, seats_json, chair_template, status,"
        " created_at) VALUES ('p-extra', ?, 'u@x', 99, 'A', '[]', 'risk-review', 'running', ?)",
        (target_key, now_epoch()),
    )
    problems = planner.check_invariants(risk_store, target_key)
    assert any(p.startswith("(2)") for p in problems)
    assert sum(1 for p in problems if p.startswith("(3)")) == 2


def test_check_invariants_flags_seat_outside_roster(risk_store):
    target_key = seeded(risk_store, {"mech": 1})
    risk_store.execute(
        "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, tier, seats_json, chair_template, status,"
        " created_at) VALUES ('p-x', ?, 'u@x', 1, 'A', ?, 'risk-review', 'planned', ?)",
        (target_key, json.dumps([{"key": "sim-ghost", "domain": "sim"}]), now_epoch()),
    )
    problems = planner.check_invariants(risk_store, target_key)
    assert [p for p in problems if p.startswith("(5)")]


# ---------------------------------------------------------------- 사람 개입의 주체(plan §0.6·§0.9 P4-13)
def test_human_seat_transitions_record_their_actor(risk_store):
    """decided_by 를 주면 status_source='human'·decided_by·decided_at 이 함께 남는다."""
    target_key = seeded(risk_store, {"mech": 2})
    out = planner.skip_seat(risk_store, target_key, "mech-a000", "휴가", decided_by="me@x")
    assert out["status_source"] == "human" and out["decided_by"] == "me@x" and out["decided_at"]
    row = risk_store.query_one(
        "SELECT status, reason, status_source, decided_by, decided_at FROM rr_coverage"
        " WHERE target_key = ? AND agent_key = 'mech-a000'", (target_key,))
    assert (row["status"], row["reason"]) == ("skipped", "휴가")
    assert (row["status_source"], row["decided_by"]) == ("human", "me@x") and row["decided_at"]

    with pytest.raises(AppError) as blank:
        planner.skip_seat(risk_store, target_key, "mech-a001", "   ", decided_by="me@x")
    assert blank.value.http_status == 422

    set_status(risk_store, target_key, "mech-a001", "carried", carried_from_opinion_id="op-prev")
    back = planner.revert_carried(risk_store, target_key, "mech-a001", decided_by="me@x")
    assert back["status_source"] == "human" and back["decided_by"] == "me@x"
