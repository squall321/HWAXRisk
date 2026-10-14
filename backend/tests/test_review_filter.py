# 거르기 분류(재설계 M3 C3-6) — 실제 단위·실제 변경 → 영역 표·가짜 엔진으로 훑기 뒤 셀이 걸러지고·표본이 되고·검토로 가는 것을 본다
"""m3-cells 3.2 의 열 줄을 검토 루프 끝까지 돌려 원장으로 본다(결정표 자체의 줄마다 시험은 test_relevance.py).

- 대상은 시험대(review_rig)의 합성 40건 → 단위 다섯(묶음 셋 · 경계 하나 · 전역 하나)이다. 진짜 변경 → 영역 표에서 `std` 영역은
  경계 단위에서만 코드 신호가 '무관' 이고(전역도 무관이지만 3번 줄이 막는다), `mech` 는 전부 '관련', `mem` 은 전부 '무관' 이다.
- 승인 문(#40)은 표가 아직 초안이라 닫혀 있다 — 거르기를 보는 시험은 잡을 만들 때만 승인을 연다(잡이 그 값을 얼린다).
- 워커 하나로 돌린다 — 검토 순서가 1순위를 먼저 집어 1순위 셀이 다 닫힌 뒤 나머지가 분류된다(8번 줄이 풀린 때).
"""
from __future__ import annotations

import dataclasses
import json
import threading

import pytest

from app import config, relevance, review_cells, routes, units
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

STD1, STD2, STD3 = "std-syn-0", "std-syn-1", "std-syn-2"     # std 영역 1·2·3순위(3순위는 카드 0장)
MECH1, MECH2 = "mech-syn-0", "mech-syn-1"
MEM1, MEM2 = "mem-syn-0", "mem-syn-1"                       # 회로 영역 — 합성 쌍에 ECAD 가 없어 입력 결손 전문가다
ROSTER: tuple[dict, ...] = (
    {"key": STD1, "domain": "std", "relevance": 0.99}, {"key": STD2, "domain": "std", "relevance": 0.9},
    {"key": STD3, "domain": "std", "relevance": 0.8},
    {"key": MECH1, "domain": "mech", "relevance": 0.99}, {"key": MECH2, "domain": "mech", "relevance": 0.9},
    {"key": MEM1, "domain": "mem", "relevance": 0.99}, {"key": MEM2, "domain": "mem", "relevance": 0.9},
)
SMALL: tuple[dict, ...] = ROSTER[:2]


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_review_concurrency=1)
    return risk_store


def _knobs(monkeypatch, **values) -> None:
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, **values))


def _approve(monkeypatch) -> None:
    """승인 문을 연다 — 잡을 만들 때만 듣는다(create_review_job 이 얼린다)."""
    monkeypatch.setattr(relevance, "routing_approved", lambda **_: True)


def _packs(roster) -> dict[str, dict]:
    ok, empty = fre.load("pack_ok.json"), fre.load("pack_empty.json")
    return {r["key"]: (fre.derive_pack(empty, r["key"], name="카드 0장", domain=r["domain"], keep="none") if r["key"] == STD3
                       else fre.derive_pack(ok, r["key"], name=r["key"], domain=r["domain"])) for r in roster}


def _fake(roster) -> FakeReviewEngine:
    """걸림 없는 대본의 가짜 엔진 — 카드 판정은 적용·OK, 카드 밖 지적 0. 표본·그림자 셀의 결과가 놓침(risk_miss)이 아니라 넓힘이
    일어나지 않는다(넓힘을 보는 시험이 걸림을 따로 건다)."""
    fake = FakeReviewEngine(_packs(roster))
    fake.offcard_findings = 0
    return fake


def _units(store, key: str) -> dict[str, str]:
    """kind → unit_id(경계·전역은 하나씩, 묶음은 첫째)."""
    out: dict[str, str] = {}
    for u in units.load_units(store, key):
        out.setdefault(u["kind"], u["unit_id"])
    return out


def _cell(store, key: str, unit_id: str, agent: str) -> dict:
    row = dict(store.query_one("SELECT * FROM rr_review_cells WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                               (key, unit_id, agent)))
    row["route_json"] = json.loads(row["route_json"]) if row["route_json"] else None
    row["sample_json"] = json.loads(row["sample_json"]) if row["sample_json"] else None
    return row


def _cells(store, key: str) -> list[dict]:
    return [_cell(store, key, r["unit_id"], r["agent_key"]) for r in store.query(
        "SELECT unit_id, agent_key FROM rr_review_cells WHERE target_key = ? ORDER BY agent_key, unit_seq", (key,))]


def _unit_runs(fake: FakeReviewEngine, agent: str, unit_id: str) -> list[dict]:
    return [r["body"] for r in fake.calls("run")
            if r["body"]["expert"]["key"] == agent and (r["body"].get("unit") or {}).get("unit_id") == unit_id]


def _quiet(fake: FakeReviewEngine, *unit_ids: str) -> None:
    """훑기가 그 단위를 '무관'(rel no · k 없음)으로 보게 한다."""
    for unit_id in unit_ids:
        fake.sweep_rel[unit_id] = "no"
        fake.sweep_k[unit_id] = []


def _run(store, roster=ROSTER, *, scope=None, fake_setup=None) -> tuple[str, str, FakeReviewEngine, dict[str, str]]:
    key = rig.target(store, roster)
    job_id = rig.job(store, key, scope=scope)
    fake = _fake(roster)
    kinds = _units(store, key)
    _quiet(fake, kinds["boundary"], kinds["global"])
    if fake_setup is not None:
        fake_setup(fake, kinds)
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    assert review_cells.review_invariants(store, key) == []
    return key, job_id, fake, kinds


# ---------------------------------------------------------------- 열 줄 — 한 원장에서
def test_a_cell_both_signals_call_unrelated_is_filtered_and_every_forcing_rule_keeps_its_cell(store, monkeypatch):
    """승인 · 거르기 on · 표본 0% — 두 신호가 다 무관인 셀만 걸러진다(route_json 의 결정 filtered · 두 신호와 규칙·판 표지가 언다).
    입력 결손 전문가도 훑기가 결측 블록을 받은 판(cr-sweep-2)이면 같은 규칙으로 걸러지고, 나머지 셀은 입력 결손 호출 길(route
    noinput)이다. 강제 줄은 저마다 그 이름으로 셀을 검토에 남긴다 — 1순위(그 셀이 거를 셀이었으면 그림자) · 전역 단위 · 카드 0장.
    코드 신호가 관련이거나 훑기가 maybe 인 셀은 강제 없이 검토다. 걸러진 셀은 그 세션에서 아무 호출도 받지 않고, 잡 끝 보충 표본
    (C3-7 — 거를 수 있던 셀이 바닥 min(N, 59)에 못 미친다)이 영역마다 하나씩 다시 열어 끝까지 판정한다(route audit · filter_floor ·
    결과는 놓침 넷 가운데 하나). 그림자 셀에도 결과가 남는다. 걸림을 놓친 결과가 없으니 넓힌 영역도 없다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)

    def setup(fake, kinds):
        # 경계 단위의 입력 결손 호출은 '영향 없음 · 확인할 것 없음' — 회로 1순위의 그림자가 놓침이 아니게(넓힘이 없게)
        fake.noinput_q1 = {kinds["boundary"]: ["no"]}
        fake.noinput_q2 = {kinds["boundary"]: [""]}

    key, job_id, fake, kinds = _run(store, fake_setup=setup)
    b, g, u1 = kinds["boundary"], kinds["global"], kinds["bundle"]

    classified = [c for c in _cells(store, key) if (c["route_json"] or {}).get("decision") == "filtered"]
    assert [(c["unit_id"], c["agent_key"]) for c in classified] == [(b, MEM2), (b, STD2)]
    cell = _cell(store, key, b, STD2)
    rj = cell["route_json"]
    assert (rj["rule"], rj["decision"], rj["filter"], rj["forced_all"], rj["handoff"], rj["audit"]) == (
        "both_unrelated", "filtered", "on", [], [], {"score": rj["audit"]["score"], "pct": 0})
    assert rj["routing_rev"] == relevance.routing_rev()
    assert (rj["code"]["verdict"], rj["sweep"]["verdict"], rj["sweep"]["rel"], rj["sweep"]["k"]) == (
        "unrelated", "unrelated", "no", [])
    assert "std" not in rj["code"]["related_domains"] and "mech" in rj["code"]["related_domains"]
    # 보충 표본 — 다시 열려 끝까지 판정됐다(분류 기록은 그대로 둔다)
    assert (cell["state"], cell["route"], cell["route_forced"], cell["basis"], cell["lease_owner"], cell["reopened_n"]) == (
        "reviewed", "audit", "filter_floor", "cards", None, 1)
    assert cell["run_id"] == job_id
    assert cell["sample_json"].get("filter_audit") == {"score": rj["audit"]["score"], "picked_by": "domain_floor",
                                                       "result": "relevance_miss"}
    # 걸러진 셀은 그 세션에서 호출을 받지 않았다 — 그 셀의 호출은 그 전문가의 다른 단위 호출이 다 끝난 뒤다
    runs = [r["body"] for r in fake.calls("run") if r["body"]["expert"]["key"] == STD2 and r["body"]["kind"] != "sweep"]
    mine = [i for i, body in enumerate(runs) if (body.get("unit") or {}).get("unit_id") == b]
    assert mine and min(mine) > max(i for i, body in enumerate(runs) if (body.get("unit") or {}).get("unit_id") != b)

    def route(unit_id, agent):
        c = _cell(store, key, unit_id, agent)
        return c["state"], c["route"], c["route_forced"]

    assert route(b, STD1) == ("reviewed", "review", "rank1")
    assert _cell(store, key, b, STD1)["sample_json"].get("shadow") == {"would_filter": True, "result": "relevance_miss"}
    assert route(g, STD2) == ("reviewed", "review", "global_unit")
    assert route(b, STD3) == ("reviewed", "review", "no_cards")
    assert route(b, MEM2) == ("reviewed", "audit", "filter_floor")         # 결측 블록을 받은 훑기(cr-sweep-2)의 무관
    assert _cell(store, key, b, MEM2)["route_json"]["forced_all"] == []
    assert _cell(store, key, b, MEM2)["sample_json"]["filter_audit"]["result"] == "kept"   # 입력 결손 결과 none
    assert route(u1, MEM2) == ("reviewed", "noinput", None)                   # 훑기 maybe — 입력 결손 호출 길
    assert route(g, MEM2) == ("reviewed", "noinput", "global_unit")
    assert route(b, MEM1) == ("reviewed", "noinput", "rank1")
    assert _cell(store, key, b, MEM1)["sample_json"]["shadow"]["result"] == "kept"
    assert route(b, MECH2) == ("reviewed", "review", None)                    # 코드 신호가 관련 — 10번 줄
    assert _cell(store, key, b, MECH2)["route_json"]["rule"] == "signal_related"
    assert route(u1, STD2) == ("reviewed", "review", None)
    # 1순위 그림자 — 그 사람이 1순위가 아니었다면 걸렀을 셀만. 다른 강제 줄이 걸린 셀(전역 단위)은 그림자가 아니다.
    shadows = sorted((c["unit_id"], c["agent_key"]) for c in _cells(store, key) if (c["sample_json"] or {}).get("shadow"))
    assert shadows == [(b, MEM1), (b, STD1)]
    assert {c["route"] for c in _cells(store, key)} <= {"audit", "review", "noinput"}
    assert review_cells.widened_domains(store, key) == [] and review_cells.filter_off(store, key) is False
    tally = review_cells.expert_tally(store, key, STD2)
    assert (tally["filtered"], tally["reviewed"], tally["open"]) == (0, 5, 0)
    ledger = {r["agent_key"]: r["status"] for r in store.query("SELECT agent_key, status FROM rr_coverage WHERE"
                                                               " target_key = ?", (key,))}
    assert ledger[STD2] == "done"


def test_the_audit_rate_sends_the_cell_to_the_end_and_a_full_rate_filters_nothing(store, monkeypatch):
    """표본 100% — 거를 셀이 걸러지지 않고 끝까지 판정된다(route audit · filter_audit · sample_json.filter_audit 의 점수와
    picked_by rate, 결과는 정산이 놓침 넷으로 적는다 — 걸림 없이 적용이면 relevance_miss). 시도 표지(attempt)는 남는다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=100)
    key, _job, fake, kinds = _run(store, SMALL)
    cell = _cell(store, key, kinds["boundary"], STD2)
    assert (cell["state"], cell["route"], cell["route_forced"]) == ("reviewed", "audit", "filter_audit")
    assert cell["route_json"]["decision"] == "audit" and cell["route_json"]["audit"]["pct"] == 100
    audit = cell["sample_json"].get("filter_audit")
    assert audit == {"score": cell["route_json"]["audit"]["score"], "picked_by": "rate", "result": "relevance_miss"}
    assert cell["sample_json"]["attempt"] == 0
    assert "offcard" in [x["kind"] for x in _unit_runs(fake, STD2, kinds["boundary"])]
    assert [c for c in _cells(store, key) if c["state"] == "na_irrelevant"] == []


def test_shadow_mode_reviews_every_cell_and_marks_the_ones_it_would_have_filtered(store, monkeypatch):
    """거르기 shadow — 9번이 참인 셀도 검토로 보내고 그림자로만 적는다(route review · route_forced 없음 · 규칙 both_unrelated)."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_review_filter="shadow", risk_filter_audit_pct=0)
    key, _job, _fake, kinds = _run(store, SMALL)
    cell = _cell(store, key, kinds["boundary"], STD2)
    assert (cell["state"], cell["route"], cell["route_forced"]) == ("reviewed", "review", None)
    assert (cell["route_json"]["rule"], cell["route_json"]["decision"], cell["route_json"]["filter"]) == (
        "both_unrelated", "review", "shadow")
    assert cell["sample_json"].get("shadow") == {"would_filter": True, "result": "relevance_miss"}
    assert [c for c in _cells(store, key) if c["state"] == "na_irrelevant"] == []


def test_a_closed_approval_gate_filters_nothing_even_with_the_filter_on(store, monkeypatch):
    """승인 문이 닫힌 표(초안)로 만든 잡 — 코드 신호가 전 영역 모름(not_approved)이라 아무것도 걸러지지 않는다(#40). 잡은 그
    승인 여부를 얼린다 — 잡이 선 뒤에 문이 열려도 그 잡은 거르지 않는다."""
    key = rig.target(store, SMALL)
    job_id = rig.job(store, key)
    _approve(monkeypatch)                                   # 잡이 선 뒤에 연 문은 그 잡에 듣지 않는다
    fake = _fake(SMALL)
    kinds = _units(store, key)
    _quiet(fake, kinds["boundary"])
    rig.Rig(store, fake).finish(job_id)
    cell = _cell(store, key, kinds["boundary"], STD2)
    assert (cell["state"], cell["route"]) == ("reviewed", "review")
    assert (cell["route_json"]["code"]["verdict"], cell["route_json"]["code"]["reason"]) == ("unknown", "not_approved")
    assert (cell["route_json"]["rule"], cell["sample_json"].get("shadow")) == ("signal_related", None)


def test_the_filter_off_writes_no_route_at_all_like_an_m2_job(store, monkeypatch):
    """잡 거르기 off(M2 잡과 같은 값) — 분류하지 않는다. route·route_forced·route_json 이 비고 sample_json 은 시도 표지뿐이다
    (M2 원장과 바이트가 같다)."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_review_filter="off")
    key, _job, _fake, _kinds = _run(store, SMALL)
    cells = _cells(store, key)
    assert {(c["state"], c["route"], c["route_forced"]) for c in cells} == {("reviewed", None, None)}
    assert {c["route_json"] is None for c in cells} == {True}
    assert {json.dumps(c["sample_json"], sort_keys=True) for c in cells} == {'{"attempt": 0}'}


def test_an_input_gap_sweep_on_the_old_rev_never_filters_the_gap_experts_cells(store, monkeypatch):
    """입력 결손 전문가의 훑기가 결측 블록을 모르는 판(cr-sweep-1)의 답이면 '무관' 이 'ECAD 가 없어 보이는 것이 없다' 일 수 있어
    거르지 않는다 — 5번 줄(input_gap)로 입력 결손 호출 길이다(X1-17). 그 훑기 요청에는 결측 블록(영역 실마리를 단 ecad 줄)이 실렸고,
    결손이 아닌 전문가의 훑기에는 실리지 않는다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    roster = (ROSTER[0], ROSTER[5], ROSTER[6])

    def setup(fake, kinds):
        fake.base_limits["prompt_rev"]["sweep"] = "cr-sweep-1"

    key, _job, fake, kinds = _run(store, roster, fake_setup=setup)
    cell = _cell(store, key, kinds["boundary"], MEM2)
    assert (cell["state"], cell["route"], cell["route_forced"]) == ("reviewed", "noinput", "input_gap")
    assert (cell["route_json"]["code"]["verdict"], cell["route_json"]["sweep"]["verdict"]) == ("unrelated", "unrelated")
    assert [c for c in _cells(store, key) if c["state"] == "na_irrelevant"] == []
    sweeps = {r["body"]["expert"]["key"]: r["body"]["extra"].get("missing") for r in fake.calls("run")
              if r["body"]["kind"] == "sweep"}
    assert sweeps[STD1] is None
    assert [m["kind"] for m in sweeps[MEM2]] == ["ecad"]
    assert sweeps[MEM2][0]["note"].endswith("이 영역이 볼 것 — 언더필·스택업.")


def test_a_sweep_with_a_failed_deck_trusts_none_of_its_answers(store, monkeypatch):
    """훑기 묶음 둘 가운데 하나가 내용 탓으로 실패하면(sweep_state failed) 다른 묶음이 '무관' 이라 해도 그 전문가의 셀은 훑기 신호가
    모름이라 거르지 않는다 — 실패한 묶음의 카드가 그 단위를 봤는지 모른다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)

    def setup(fake, kinds):
        fake.sweep_split = 2
        fake.sweep_error_aliases = {"K10"}

    key, _job, _fake, kinds = _run(store, SMALL, fake_setup=setup)
    head = store.query_one("SELECT sweep_state, sweep_json FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?",
                           (key, STD2))
    assert head["sweep_state"] == "failed" and json.loads(head["sweep_json"])["units"][kinds["boundary"]]["rel"] == "no"
    cell = _cell(store, key, kinds["boundary"], STD2)
    assert (cell["state"], cell["route"], cell["route_forced"]) == ("reviewed", "review", None)
    assert (cell["route_json"]["sweep"]["verdict"], cell["route_json"]["sweep"]["reason"]) == ("unknown", "sweep_failed")


# ---------------------------------------------------------------- 넘김 · 1순위 대기 · 훑기 관련
def test_another_experts_handoff_keeps_the_cell_and_names_who_sent_it(store, monkeypatch):
    """다른 전문가의 훑기가 경계 단위를 std 로 넘겼다(h 줄) — 그 셀은 7번 줄(handoff)로 검토에 남고 route_json.handoff 에 보낸
    전문가와 까닭이 있다. 자기 훑기가 자기 영역으로 넘긴 줄은 세지 않는다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)

    def setup(fake, kinds):
        fake.handoff_to, fake.handoff_unit = "std", kinds["boundary"]

    key, _job, _fake, kinds = _run(store, SMALL, fake_setup=setup)
    cell = _cell(store, key, kinds["boundary"], STD2)
    assert (cell["state"], cell["route"], cell["route_forced"]) == ("reviewed", "review", "handoff")
    assert cell["route_json"]["handoff"] == [{"from": STD1, "why": "훑기가 다른 영역의 몫으로 본 단위"}]


def test_a_rank_one_cell_still_open_anywhere_in_the_target_keeps_every_cell(store, monkeypatch):
    """1순위 셀이 잡 범위 밖에서 아직 pending 이다 — 두 신호가 다 무관이어도 8번 줄(tier_a_pending)로 검토다(X1-12 (4))."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key, _job, _fake, kinds = _run(store, SMALL, scope={"agents": [STD2]})
    cell = _cell(store, key, kinds["boundary"], STD2)
    assert (cell["state"], cell["route"], cell["route_forced"]) == ("reviewed", "review", "tier_a_pending")
    assert cell["route_json"]["forced_all"] == ["tier_a_pending"]
    assert {c["state"] for c in _cells(store, key) if c["agent_key"] == STD1} == {"pending"}


@pytest.mark.parametrize("rel,k", [("maybe", []), ("no", ["K01"]), ("absent", None)])
def test_a_sweep_that_does_not_say_unrelated_keeps_the_cell(store, monkeypatch, rel, k):
    """훑기가 maybe 이거나 카드를 걸었거나(rel no 에 k) 그 단위를 답에서 빠뜨렸으면(회계가 error 로 적는다) 거르지 않는다 — 모르면
    검토다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)

    def setup(fake, kinds):
        if rel == "absent":
            fake.sweep_drop = {kinds["boundary"]}
        else:
            fake.sweep_rel[kinds["boundary"]], fake.sweep_k[kinds["boundary"]] = rel, k

    key, _job, _fake, kinds = _run(store, SMALL, fake_setup=setup)
    cell = _cell(store, key, kinds["boundary"], STD2)
    assert (cell["state"], cell["route"], cell["route_forced"]) == ("reviewed", "review", None)
    sweep = cell["route_json"]["sweep"]
    assert (sweep["verdict"], sweep["rel"]) == (("unknown", "error") if rel == "absent" else ("related", rel))


def test_a_cell_a_person_reopened_is_never_classified_again(store, monkeypatch):
    """사람이 force 로 다시 연 셀(route_forced human_retry)은 새 잡이 거를 셀로 볼 입력이어도 분류하지 않고 끝까지 본다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=100)
    key, _job, fake, kinds = _run(store, SMALL)
    b = kinds["boundary"]
    assert _cell(store, key, b, STD2)["route"] == "audit"
    _knobs(monkeypatch, risk_filter_audit_pct=0)                 # 새 잡이면 거를 셀이다
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[b, STD2]], force=True, reason="사람이 다시 본다"),
                                  ident=factories.ident(rig.OWNER))
    rig.Rig(store, fake).finish(out["job"]["job_id"])
    cell = _cell(store, key, b, STD2)
    assert (cell["state"], cell["route"], cell["route_forced"], cell["route_json"]) == (
        "reviewed", None, review_cells.HUMAN_RETRY, None)


def test_a_classified_cell_keeps_its_route_when_the_inputs_move_before_it_settles(store, monkeypatch):
    """분류는 셀마다 한 번이다 — 1순위 셀이 열려 있어 검토로 보낸(tier_a_pending) 셀은, 세션이 도중에 죽고 그 사이 1순위가 다
    닫혀 같은 입력이면 걸렀을 때가 되어도 다시 분류되지 않는다(입력 지문이 바뀌기 전까지 route·route_json 그대로)."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key = rig.target(store, SMALL)
    fake = _fake(SMALL)
    kinds = _units(store, key)
    b = kinds["boundary"]
    _quiet(fake, b, kinds["global"])
    job_id = rig.job(store, key, scope={"agents": [STD2]})
    gate = threading.Event()
    fake.hold_runs = {3: gate}
    first = rig.Rig(store, fake, boot_id="boot-a")
    first.tick(packs_only=True)
    first.tick(wait=False)
    rig.wait_for(lambda: fake.runs == 3)
    before = _cell(store, key, b, STD2)
    assert (before["route"], before["route_forced"]) == ("review", "tier_a_pending")
    review_cells.recover_running(store)
    store.execute("UPDATE rr_review_cells SET state = 'reviewed' WHERE target_key = ? AND agent_key = ?", (key, STD1))
    second = rig.Rig(store, fake, clock=first.clock, boot_id="boot-b")
    second.finish(job_id)
    gate.set()
    first.loop.join(30)
    after = _cell(store, key, b, STD2)
    assert (after["state"], after["route"], after["route_forced"], after["route_json"]) == (
        "reviewed", "review", "tier_a_pending", before["route_json"])


# ---------------------------------------------------------------- 보이기 — 다섯 곳이 같은 수(C3-8)
def test_grid_board_report_quality_and_closure_show_the_same_filter_numbers(store, monkeypatch):
    """한 원장에서 셀 격자 · 진행판(review.filter) · 전문가 보고서 머리 · 품질 수치 · 완결 몫(closure_cells)을 뽑아 견준다 — 거를 수
    있던 셀 · 거른 셀 · 표본 · 놓침 넷 · 그림자가 다섯 곳에서 같다. 거른 셀의 까닭 한 줄은 판단어 린터를 지나고 훑기 글은 «» 안이다.
    완결 몫의 불변식이 비고 표본 바닥을 채웠다."""
    from app import closure as closure_mod
    from app import expert_report, render, review_quality

    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)

    def setup(fake, kinds):
        fake.noinput_q1 = {kinds["boundary"]: ["no"]}
        fake.noinput_q2 = {kinds["boundary"]: [""]}

    key, _job, _fake_, kinds = _run(store, fake_setup=setup)
    cells = review_cells.closure_cells(store, key)
    flt = cells["filtered"]
    assert (flt["n"], flt["would_filter"], flt["audit"]["sampled"], flt["audit"]["n_audit"], flt["audit"]["floor_met"]) == (
        0, 2, 2, 2, True)
    assert {k: flt["audit"][k] for k in review_cells.AUDIT_RESULTS} == {"risk_miss": 0, "relevance_miss": 1,
                                                                         "undetermined": 0, "kept": 1}
    assert (flt["shadow"]["would_filter"], flt["shadow"]["sampled"], flt["shadow"]["risk_miss"]) == (2, 2, 0)
    assert (flt["widened"], flt["off"], cells["invariants"]) == ([], False, [])
    assert cells["by_state"]["pending"] + cells["by_state"]["running"] == 0
    assert cells["grid"]["expected"] == cells["grid"]["actual"] == len(ROSTER) * 5

    board = routes.coverage_payload(key, owner_sub=rig.OWNER)["review"]["filter"]
    assert (board["mode"], board["would_filter"], board["filtered"], board["audited"]) == ("on", 2, 0, 2)
    assert {k: board["audit"][k] for k in review_cells.AUDIT_RESULTS} == {k: flt["audit"][k] for k in review_cells.AUDIT_RESULTS}
    assert board["shadow"] == flt["shadow"]

    quality = review_quality.compute(store, key)["filter"]
    assert (quality["would_filter"], quality["filtered"], quality["audit"]["sampled"], quality["shadow"]["sampled"]) == (
        2, 0, 2, 2)
    assert quality["audit"]["counts"] == {k: flt["audit"][k] for k in review_cells.AUDIT_RESULTS}
    assert quality["audit"]["risk_miss"]["threshold"] == {"upper_max": 0.05} and quality["audit"]["risk_miss"]["min_n"] == 59
    counts = closure_mod.cell_counts(store, key)["filter"]
    assert (counts["n"], counts["audit"]["sampled"]) == (flt["n"], flt["audit"]["sampled"])

    heads = [expert_report.load_report(store, key, r["key"])["head"]["filter"] for r in ROSTER]
    assert sum(h["audited"] for h in heads) == 2 and sum(h["shadow"] for h in heads) == 2
    assert sum(h["filtered"] for h in heads) == 0 and sum(h["risk_miss"] for h in heads) == 0

    grid = routes.cells_payload(key, owner_sub=rig.OWNER, limit=2000)["rows"]
    assert sum(1 for r in grid if r["route"] == "audit") == 2
    reasons = [r["filter_reason"] for r in grid if r["filter_reason"]]
    assert len(reasons) == flt["would_filter"]
    for reason in reasons:
        assert render.lint_text(reason)["ok"], reason
        assert reason.startswith("코드 신호 무관(관련 영역 ") and "«" in reason
    assert routes.cells_payload(key, owner_sub=rig.OWNER, route="audit")["total"] == 2


# ---------------------------------------------------------------- 표본·그림자의 놓침 · 넓힘 · 늦은 넘김 · 보충 표본(C3-7)
def test_a_shadow_that_missed_a_hit_widens_the_domain_and_its_cells_are_never_filtered(store, monkeypatch):
    """1순위의 그림자 셀(거를 셀이었을 셀)이 끝까지 보니 카드 밖 리스크(심각도 중대)를 냈다 — 놓침(risk_miss)이 sample_json 에
    남고 그 영역(std)이 그 대상에서 넓어진다. 그 뒤 분류되는 같은 영역의 셀은 6번 줄(widened)로 검토다. 넓힘은 저장하지 않고
    원장(표본·그림자 결과)에서 유도한다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)

    def setup(fake, kinds):
        fake.offcard_findings = 1                     # 카드 밖 리스크 '중대' — 그림자 셀의 결과가 놓침이다

    key, _job, _fake, kinds = _run(store, SMALL, fake_setup=setup)
    b = kinds["boundary"]
    assert _cell(store, key, b, STD1)["sample_json"]["shadow"] == {"would_filter": True, "result": "risk_miss"}
    assert review_cells.widened_domains(store, key) == ["std"] and review_cells.filter_off(store, key) is False
    cell = _cell(store, key, b, STD2)
    assert (cell["state"], cell["route"], cell["route_forced"], cell["route_json"]["forced_all"]) == (
        "reviewed", "review", "widened", ["widened"])
    assert (cell["route_json"]["code"]["verdict"], cell["route_json"]["sweep"]["verdict"]) == ("unrelated", "unrelated")


def _filtered_mid_job(store, monkeypatch) -> tuple[str, str, dict, rig.Rig, threading.Event, FakeReviewEngine]:
    """1순위(std)가 먼저 다 닫힌 뒤 2순위 잡이 경계 단위를 거르고 다음 판정 호출에서 선다 — 보충 표본 전의 원장."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key = rig.target(store, SMALL)
    fake = _fake(SMALL)
    kinds = _units(store, key)
    _quiet(fake, kinds["boundary"], kinds["global"])
    rig.Rig(store, fake).finish(rig.job(store, key, scope={"agents": [STD1]}))
    job_id = rig.job(store, key, scope={"agents": [STD2]})
    gate = threading.Event()
    fake.hold_runs = {fake.runs + 3: gate}
    r = rig.Rig(store, fake)
    r.tick(packs_only=True)
    r.tick(wait=False)
    rig.wait_for(lambda: fake.runs == max(fake.hold_runs))
    assert _cell(store, key, kinds["boundary"], STD2)["state"] == "na_irrelevant"
    return key, job_id, kinds, r, gate, fake


def _risk_miss(store, key: str, unit_id: str, agent: str, domain: str | None = None) -> None:
    """정산이 적는 표본·그림자 결과의 놓침을 그 셀에 둔다(넓힘의 원천). 영역을 주면 그 셀의 영역 칸도 바꿔 영역 셋을 만든다."""
    store.execute("UPDATE rr_review_cells SET domain = COALESCE(?, domain), sample_json = json_object('shadow',"
                  " json_object('would_filter', 1, 'result', 'risk_miss')) WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                  (domain, key, unit_id, agent))


def test_widening_reopens_the_domains_filtered_cells_to_be_classified_again(store, monkeypatch):
    """넓힘은 그 영역의 거른 셀을 전부 다시 연다(na_irrelevant → pending · reopened_n + 1 · 분류 칸을 비운다) — 다시 돌면 6번 줄
    widened 로 검토다. 다시 열 것이 없으면 아무것도 바꾸지 않는다. 그 잡 범위 밖에서 걸러진 셀은 보충 표본이 채우지 못한다(short ·
    그 영역)."""
    key, job_id, kinds, r, gate, fake = _filtered_mid_job(store, monkeypatch)
    b = kinds["boundary"]
    short = review_cells.audit_topup(store, key, "another-job", audit_pct=0, salt="s")
    assert (short["reopened"], short["short"], short["domains_short"]) == (0, 1, ["std"])
    _risk_miss(store, key, b, STD1)
    out = review_cells.widen(store, key, "std")
    assert (out["widened"], out["off"], out["reopened"]) == (["std"], False, 1)
    cell = _cell(store, key, b, STD2)
    assert (cell["state"], cell["route"], cell["route_forced"], cell["basis"], cell["reopened_n"]) == (
        "pending", None, "widened", None, 1)
    assert review_cells.reopen_filtered(store, key, via="widened", domain="std") == []      # 다시 열 것이 없다
    review_cells.recover_running(store)
    gate.set()
    r.loop.join(30)
    rig.Rig(store, fake, clock=r.clock, boot_id="boot-b").finish(job_id)
    assert rig.state(store, job_id) == "completed"
    again = _cell(store, key, b, STD2)
    assert (again["state"], again["route"], again["route_forced"]) == ("reviewed", "review", "widened")


def test_a_third_widened_domain_turns_filtering_off_for_the_target(store, monkeypatch):
    """넓힌 영역이 셋이 되는 넓힘은 그 영역 밖의 거른 셀까지 전부 다시 연다(via filter_off) — 대상 전체 거르기가 꺼졌다(원장에서
    유도)."""
    key, _job, kinds, r, gate, _fake_ = _filtered_mid_job(store, monkeypatch)
    _risk_miss(store, key, kinds["global"], STD1, "mech")
    _risk_miss(store, key, kinds["bundle"], STD1, "xd")
    assert review_cells.filter_off(store, key) is False
    _risk_miss(store, key, kinds["boundary"], STD1, "sim")
    assert review_cells.widened_domains(store, key) == ["mech", "sim", "xd"] and review_cells.filter_off(store, key)
    out = review_cells.widen(store, key, "sim")
    assert (out["off"], out["reopened"]) == (True, 1)
    assert _cell(store, key, kinds["boundary"], STD2)["route_forced"] == "filter_off"
    gate.set()
    r.loop.join(30)


def test_a_late_handoff_reopens_a_filtered_cell_of_that_domain(store, monkeypatch):
    """xd 2순위의 훑기가 std 2순위가 이미 거른 경계 단위를 std 로 넘긴다(h 줄) — 그 셀이 다시 열리고(handoff) 다시 분류되면 7번
    줄로 검토다. 넘김 기록에 보낸 전문가가 있다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    roster = (*SMALL, {"key": "xd-syn-0", "domain": "xd", "relevance": 0.99}, {"key": "xd-syn-1", "domain": "xd", "relevance": 0.9})

    def setup(fake, kinds):
        fake.handoff_to, fake.handoff_unit, fake.handoff_from = "std", kinds["boundary"], {"xd-syn-1"}

    key, _job, fake, kinds = _run(store, roster, fake_setup=setup)
    cell = _cell(store, key, kinds["boundary"], STD2)
    assert (cell["state"], cell["route"], cell["route_forced"], cell["reopened_n"]) == ("reviewed", "review", "handoff", 1)
    assert cell["route_json"]["handoff"] == [{"from": "xd-syn-1", "why": "훑기가 다른 영역의 몫으로 본 단위"}]
    order = [r["body"]["expert"]["key"] for r in fake.calls("run") if r["body"]["kind"] == "sweep"]
    assert order.index(STD2) < order.index("xd-syn-1")                     # 넘김이 거른 뒤에 왔다


# ---------------------------------------------------------------- 재기동
def test_a_restart_keeps_the_classification_and_never_reclassifies(store, monkeypatch):
    """1순위가 먼저 다 닫힌 뒤 2순위 세션이 분류하고 판정 호출 도중 죽는다 — 재기동 복구 뒤 새 러너는 걸러진 셀을 다시 열지 않고
    검토 셀의 분류(route·route_json)를 그대로 둔 채 이어 돈다. 걸러진 셀은 그 잡의 셀이 다 닫힐 때까지 호출 0 이고, 잡 끝 보충
    표본(C3-7)만 그 셀을 다시 연다(분류 기록 route_json 은 그대로)."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key = rig.target(store, SMALL)
    fake = _fake(SMALL)
    kinds = _units(store, key)
    _quiet(fake, kinds["boundary"], kinds["global"])
    first_job = rig.job(store, key, scope={"agents": [STD1]})
    first = rig.Rig(store, fake, boot_id="boot-a")
    first.finish(first_job)
    second_job = rig.job(store, key, scope={"agents": [STD2]})
    gate = threading.Event()
    fake.hold_runs = {fake.runs + 3: gate}                  # 2순위의 훑기 뒤 두 번째 판정 호출에서 선다
    first.tick()                                            # 묶음 받기
    first.tick(wait=False)
    rig.wait_for(lambda: fake.runs == max(fake.hold_runs))
    classified = {c["unit_id"]: (c["state"], c["route"], c["route_forced"], c["route_json"])
                  for c in _cells(store, key) if c["agent_key"] == STD2}
    assert classified[kinds["boundary"]][:2] == ("na_irrelevant", "filtered")
    assert {v[1] for u, v in classified.items() if u != kinds["boundary"]} == {"review"}

    review_cells.recover_running(store)
    second = rig.Rig(store, fake, clock=first.clock, boot_id="boot-b")
    second.finish(second_job)
    gate.set()
    first.loop.join(30)
    assert rig.state(store, second_job) == "completed"
    after = {c["unit_id"]: c for c in _cells(store, key) if c["agent_key"] == STD2}
    b = kinds["boundary"]
    assert {u: (c["route"], c["route_forced"], c["route_json"]) for u, c in after.items() if u != b} == {
        u: v[1:] for u, v in classified.items() if u != b}
    assert (after[b]["state"], after[b]["route"], after[b]["route_forced"], after[b]["route_json"]) == (
        "reviewed", "audit", "filter_floor", classified[b][3])
    runs = [r["body"] for r in fake.calls("run") if r["body"]["expert"]["key"] == STD2 and r["body"]["kind"] != "sweep"]
    mine = [i for i, body in enumerate(runs) if (body.get("unit") or {}).get("unit_id") == b]
    assert mine and min(mine) > max(i for i, body in enumerate(runs) if (body.get("unit") or {}).get("unit_id") != b)
    assert review_cells.review_invariants(store, key) == []


def test_a_low_floor_samples_one_cell_per_domain_and_a_later_miss_reopens_what_an_earlier_job_filtered(store, monkeypatch):
    """보충 표본 바닥(C3-7)과 넓힘의 즉시 다시 열기 — 1순위가 다 닫힌 뒤(첫 잡) 바닥이 작으면(AUDIT_MIN_N 1 · 비율 0) 둘째 잡이 거른 셀
    가운데 영역마다 한 건만 다시 열려 끝까지 판정되고 나머지는 거른 채 남는다. 완결 몫은 실제 바닥(59 — 거를 수 있던 셀 N 전부)에 못
    미쳐 floor_met 이 거짓이다. 셋째 잡의 보충 표본이 같은 영역에서 걸림을 놓치면(입력 결손 셀의 영향 있음 → risk_miss) 둘째 잡이
    거른 셀이 그 잡의 보충 표본이 아니라 넓힘으로 곧바로 다시 열린다(route_forced widened · pending — 다음 잡이 분류한다)."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key = rig.target(store, ROSTER)
    us = units.load_units(store, key)
    boundary = next(u["unit_id"] for u in us if u["kind"] == "boundary")
    b0, b1, b2 = (u["unit_id"] for u in us if u["kind"] == "bundle")
    fake = _fake(ROSTER)
    _quiet(fake, *(u["unit_id"] for u in us))
    for u in us:                                                      # 입력 결손 호출은 '영향 없음 · 확인할 것 없음'
        fake.noinput_q1[u["unit_id"]], fake.noinput_q2[u["unit_id"]] = ["no"], [""]
    r = rig.Rig(store, fake)

    def done(scope) -> str:
        job_id = rig.job(store, key, scope=scope)
        r.finish(job_id)
        assert rig.state(store, job_id) == "completed"
        return job_id

    done({"agents": [STD1, MECH1, MEM1]})                             # 1순위가 먼저 다 닫힌다(8번 줄)
    monkeypatch.setattr(review_cells, "AUDIT_MIN_N", 1)
    done({"agents": [STD2, MEM2], "unit_ids": [boundary, b0, b1]})
    cells = _cells(store, key)
    floor = [c for c in cells if c["route_forced"] == review_cells.FILTER_FLOOR]
    assert sorted(c["domain"] for c in floor) == ["mem", "std"]       # 영역마다 한 건
    left = [c for c in cells if c["state"] == "na_irrelevant"]
    assert len(left) == 2 and {(c["agent_key"], c["domain"]) for c in left} == {(MEM2, "mem")}
    monkeypatch.setattr(review_cells, "AUDIT_MIN_N", 59)
    audit = review_cells.closure_cells(store, key)["filtered"]["audit"]
    assert (audit["n_audit"], audit["sampled"], audit["floor_met"]) == (4, 2, False)

    monkeypatch.setattr(review_cells, "AUDIT_MIN_N", 3)               # 셋째 잡의 바닥 — 그 잡이 거른 b2 한 건을 다시 연다
    fake.noinput_q1[b2] = ["yes"]                                     # 끝까지 보니 영향 있음 — 거른 셀이 걸림을 놓쳤다
    done({"agents": [MEM2], "unit_ids": [b2]})
    audited = _cell(store, key, b2, MEM2)
    assert (audited["route_forced"], audited["sample_json"]["filter_audit"]["result"]) == (review_cells.FILTER_FLOOR,
                                                                                          "risk_miss")
    assert "mem" in review_cells.widened_domains(store, key)
    reopened = [_cell(store, key, c["unit_id"], c["agent_key"]) for c in left]
    assert {(c["state"], c["route_forced"], c["reopened_n"]) for c in reopened} == {("pending", "widened", 1)}


def test_a_filtered_cell_without_its_classification_record_breaks_the_invariant(store, monkeypatch):
    """불변식 G8 — 거른 셀(na_irrelevant)은 거르기 분류가 거른 셀이다(route filtered · 분류 기록 route_json.rule). 기록이 빠진 거른 셀은
    완결 몫의 불변식에 걸린다(그 대상은 완결을 막는다)."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key, job_id, kinds, r, gate, fake = _filtered_mid_job(store, monkeypatch)
    b = kinds["boundary"]
    assert not any("(G8)" in p for p in review_cells.review_invariants(store, key))
    store.execute("UPDATE rr_review_cells SET route_json = NULL WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                  (key, b, STD2))
    assert any("(G8)" in p for p in review_cells.closure_cells(store, key)["invariants"])
    gate.set()
    r.loop.join(30)
