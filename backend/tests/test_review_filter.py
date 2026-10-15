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

from app import config, expert_report, relevance, review_cells, review_verify, routes, units
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
    """사람이 force 로 다시 연 셀(route_forced human_retry)은 새 잡이 거를 셀로 볼 입력이어도 분류하지 않고 끝까지 본다. 표본 셀이면
    그 표지 · 분류 기록은 남는다(반대 검토 HIGH 3 — 다시 돈 정산이 결과를 다시 적는다)."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=100)
    key, _job, fake, kinds = _run(store, SMALL)
    b = kinds["boundary"]
    before = _cell(store, key, b, STD2)
    assert before["route"] == "audit"
    _knobs(monkeypatch, risk_filter_audit_pct=0)                 # 새 잡이면 거를 셀이다
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[b, STD2]], force=True, reason="사람이 다시 본다"),
                                  ident=factories.ident(rig.OWNER))
    rig.Rig(store, fake).finish(out["job"]["job_id"])
    cell = _cell(store, key, b, STD2)
    assert (cell["state"], cell["route"], cell["route_forced"], cell["route_json"]) == (
        "reviewed", "audit", review_cells.HUMAN_RETRY, before["route_json"])         # 다시 분류하지 않았다
    assert cell["sample_json"]["filter_audit"]["result"] in review_cells.AUDIT_RESULTS


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


def _offcard_handoff_target(store, monkeypatch) -> tuple[str, FakeReviewEngine, dict[str, str], rig.Rig]:
    """승인 · 표본 0% · 보충 표본 바닥 0(거른 셀이 잡 끝 표본으로 다시 열리지 않게) — 1순위 셋이 먼저 다 닫힌 원장."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    monkeypatch.setattr(review_cells, "AUDIT_MIN_N", 0)
    monkeypatch.setattr(review_cells, "AUDIT_DOMAIN_FLOOR", 0)
    key = rig.target(store, ROSTER)
    fake = _fake(ROSTER)
    kinds = _units(store, key)
    _quiet(fake, kinds["boundary"], kinds["global"])
    return key, fake, kinds, rig.Rig(store, fake)


OFFCARD_WHY = "카드 밖 호출이 다른 영역의 몫으로 본 줄"


def test_another_experts_offcard_handoff_keeps_the_cell_it_arrives_before(store, monkeypatch):
    """반대 검토 LOW 15 — 카드 밖 호출의 h 줄(그 셀의 단위를 다른 영역으로 넘긴다)도 넘김이다(M3.md 4.9 의 h 줄은 훑기에 한정하지
    않는다). mech 1순위의 카드 밖 호출이 경계 단위를 std 로 넘긴 뒤 std 2순위가 분류하면 7번 줄(handoff)로 검토에 남고
    route_json.handoff 에 보낸 전문가가 있다(종전에는 걸러졌다)."""
    key, fake, kinds, r = _offcard_handoff_target(store, monkeypatch)
    b = kinds["boundary"]
    fake.offcard_handoffs = {(MECH1, b): "std"}
    r.finish(rig.job(store, key, scope={"agents": [STD1, MECH1, MEM1]}))
    assert json.loads(_cell(store, key, b, MECH1)["handoffs_json"])[0]["to"] == "std"
    r.finish(rig.job(store, key, scope={"agents": [STD2]}))
    cell = _cell(store, key, b, STD2)
    assert (cell["state"], cell["route"], cell["route_forced"]) == ("reviewed", "review", "handoff")
    assert cell["route_json"]["handoff"] == [{"from": MECH1, "why": OFFCARD_WHY}]
    assert review_cells.review_invariants(store, key) == []


def test_a_late_offcard_handoff_reopens_the_filtered_cell_at_job_end(store, monkeypatch):
    """반대 검토 LOW 15 · 2차 MEDIUM 3 — 거른 뒤에 온 카드 밖 넘김: std 2순위가 경계 단위를 거른 뒤(앞 잡) mech 2순위의 카드 밖 호출이
    그 단위를 std 로 넘긴다. 잡 끝(보충 표본 앞)이 그 셀을 다시 열고 그 셀만 지금 잡에 묶는다(머리는 범위로 찍지 않는다 — 3차 ·
    D-47) — 지금 잡이 그 셀을 다시 분류해 7번 줄로 검토한다(종전에는 거른 잡의 결속 그대로 pending 으로 남아 아무 잡도 돌리지 않았다).
    자기 넘김은 세지 않으므로 다시 열린 셀이 다시 걸러져 잡 끝이 되풀이되지 않는다."""
    key, fake, kinds, r = _offcard_handoff_target(store, monkeypatch)
    b = kinds["boundary"]
    r.finish(rig.job(store, key, scope={"agents": [STD1, MECH1, MEM1]}))
    r.finish(rig.job(store, key, scope={"agents": [STD2]}))
    assert _cell(store, key, b, STD2)["state"] == "na_irrelevant"
    fake.offcard_handoffs = {(MECH2, b): "std"}
    sender = rig.job(store, key, scope={"agents": [MECH2]})
    r.finish(sender)
    assert rig.state(store, sender) == "completed"
    cell = _cell(store, key, b, STD2)
    assert (cell["state"], cell["run_id"], cell["route"], cell["route_forced"], cell["reopened_n"]) == (
        "reviewed", sender, "review", "handoff", 1)
    assert cell["route_json"]["handoff"] == [{"from": MECH2, "why": OFFCARD_WHY}]
    assert _head_run(store, key, STD2) != sender                      # 셀만 묶는다 — 머리는 범위로 찍지 않는다(3차 · D-47)
    assert review_cells.review_invariants(store, key) == []


def _head_run(store, key: str, agent: str) -> str | None:
    return store.query_one("SELECT run_id FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?", (key, agent))["run_id"]


@pytest.mark.parametrize("crash", [False, True])
def test_widening_binds_an_earlier_jobs_filtered_cells_to_the_running_job_without_stamping_the_head(store, monkeypatch, crash):
    """반대 검토 2차 MEDIUM 3 · 3차 MEDIUM 2 · D-47 — 앞 잡(회로 2순위)이 거른 셀을 지금 잡(회로 1순위 그림자의 사람의 다시)의 넓힘이
    다시 열면 그 셀만 지금 잡에 묶여 지금 잡이 끝까지 돌린다 — 정산의 곧바로 넓힘(정상 길)이든, 넓히기 전에 죽어 잡 끝이 거둔 길이든
    같다. 종전 정상 길은 앞 잡의 결속 그대로 pending 이라 아무 잡도 돌리지 않았다. 전문가 머리는 범위로 찍지 않는다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    monkeypatch.setattr(review_cells, "AUDIT_MIN_N", 0)
    monkeypatch.setattr(review_cells, "AUDIT_DOMAIN_FLOOR", 0)
    key = rig.target(store, ROSTER)
    us = units.load_units(store, key)
    bundles = [u["unit_id"] for u in us if u["kind"] == "bundle"]
    fake = _fake(ROSTER)
    _quiet(fake, *bundles)
    for u in us:
        fake.noinput_q1[u["unit_id"]], fake.noinput_q2[u["unit_id"]] = ["no"], [""]
    r = rig.Rig(store, fake)
    r.finish(rig.job(store, key, scope={"agents": [STD1, MECH1, MEM1]}))
    shadow = next(c for c in _cells(store, key) if c["agent_key"] == MEM1 and (c["sample_json"] or {}).get("shadow"))
    earlier = rig.job(store, key, scope={"agents": [MEM2]})
    r.finish(earlier)
    filtered = [c["unit_id"] for c in _cells(store, key) if c["agent_key"] == MEM2 and c["state"] == "na_irrelevant"]
    assert filtered
    fake.noinput_q1[shadow["unit_id"]] = ["yes"]                     # 다시 보니 그림자가 걸림을 놓쳤다
    real, crashed = review_cells.widen, []

    def crash_once(*args, **kwargs):
        if crash and not crashed:
            crashed.append(1)
            raise RuntimeError("넓히기 직전에 죽었다(가짜)")
        return real(*args, **kwargs)

    monkeypatch.setattr(review_cells, "widen", crash_once)
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[shadow["unit_id"], MEM1]], force=True,
                                                             reason="그림자를 다시 본다"), ident=factories.ident(rig.OWNER))
    running = out["job"]["job_id"]
    r.finish(running)
    assert bool(crashed) is crash and rig.state(store, running) == "completed"
    assert "mem" in review_cells.widened_domains(store, key)
    reaped = [_cell(store, key, u, MEM2) for u in filtered]
    assert {(c["state"], c["run_id"], c["route_forced"]) for c in reaped} == {("reviewed", running, "widened")}
    assert _head_run(store, key, MEM2) == earlier                    # 머리는 범위로 찍지 않는다


def test_a_late_sweep_handoff_binds_an_earlier_jobs_filtered_cell_to_the_running_job(store, monkeypatch):
    """반대 검토 3차 MEDIUM 2 · D-47(재현 B1) — 앞 잡(std 2순위)이 거른 경계 단위를 지금 잡(mech 2순위)의 훑기가 std 로 넘기면 곧바로
    다시 연 그 셀만 지금 잡에 묶여 지금 잡이 돌린다(종전에는 앞 잡의 결속 그대로 pending 이라 지금 잡이 끝나고 아무 잡도 돌리지
    않았다). 머리는 찍지 않는다."""
    key, fake, kinds, r = _offcard_handoff_target(store, monkeypatch)
    b = kinds["boundary"]
    r.finish(rig.job(store, key, scope={"agents": [STD1, MECH1, MEM1]}))
    earlier = rig.job(store, key, scope={"agents": [STD2]})
    r.finish(earlier)
    assert _cell(store, key, b, STD2)["state"] == "na_irrelevant"
    fake.handoff_to, fake.handoff_unit, fake.handoff_from = "std", b, {MECH2}
    sender = rig.job(store, key, scope={"agents": [MECH2]})
    r.finish(sender)
    cell = _cell(store, key, b, STD2)
    assert (rig.state(store, sender), cell["state"], cell["run_id"], cell["route_forced"]) == (
        "completed", "reviewed", sender, "handoff")
    assert _head_run(store, key, STD2) == earlier
    assert rig.progress(store, sender)["experts"] == {"total": 2, "by_state": {**{s: 0 for s in review_cells.EXPERT_STATES},
                                                                               "ready": 2}}   # 그 셀로 묶인 전문가도 그 잡의 몫


@pytest.mark.parametrize("path", ["handoff_reap", "top_up"])
def test_a_reopened_cell_runs_alone_and_never_pulls_the_experts_unscoped_cells_into_the_job(store, monkeypatch, path):
    """반대 검토 3차 MEDIUM 3 · D-47(재현 C) — std 2순위를 경계 단위 하나로만 잡은 앞 잡이 그 셀을 거른 뒤(나머지 넷은 한 번도 잡히지
    않았다), 지금 잡(mech 2순위)의 잡 끝이 그 셀을 다시 열면(카드 밖 넘김 거두기 · 보충 표본) 그 셀 하나만 지금 잡에 묶여 돈다.
    종전에는 머리를 지금 잡으로 찍어 adopt_released 가 그 전문가의 범위 밖 셀 넷까지 거둬 다섯 단위를 다 돌렸다(범위 · 동의 · 추정
    밖). 엔진 호출은 그 셀의 것뿐이다."""
    key, fake, kinds, r = _offcard_handoff_target(store, monkeypatch)
    b = kinds["boundary"]
    others = [u["unit_id"] for u in units.load_units(store, key) if u["unit_id"] != b]
    r.finish(rig.job(store, key, scope={"agents": [STD1, MECH1, MEM1]}))
    earlier = rig.job(store, key, scope={"agents": [STD2], "unit_ids": [b]})
    r.finish(earlier)
    assert _cell(store, key, b, STD2)["state"] == "na_irrelevant"
    if path == "handoff_reap":
        fake.offcard_handoffs = {(MECH2, b): "std"}
    else:
        monkeypatch.setattr(review_cells, "AUDIT_MIN_N", 1)
        monkeypatch.setattr(review_cells, "AUDIT_DOMAIN_FLOOR", 1)
    before = {u: (_cell(store, key, u, STD2)["state"], _cell(store, key, u, STD2)["run_id"]) for u in others}
    runs = len(fake.calls("run"))
    current = rig.job(store, key, scope={"agents": [MECH2]})
    r.finish(current)
    cell = _cell(store, key, b, STD2)
    assert (rig.state(store, current), cell["state"], cell["run_id"]) == ("completed", "reviewed", current)
    assert {u: (_cell(store, key, u, STD2)["state"], _cell(store, key, u, STD2)["run_id"]) for u in others} == before
    std2 = [c["body"] for c in fake.calls("run")[runs:] if c["body"]["expert"]["key"] == STD2]
    assert {(b_.get("unit") or {}).get("unit_id") for b_ in std2} == {b}         # 그 셀의 호출뿐(종전 15 — 다섯 단위)
    assert _head_run(store, key, STD2) == earlier


def test_an_experts_handoff_to_its_own_domain_never_reopens_its_own_filtered_cell_at_job_end(store, monkeypatch):
    """반대 검토 LOW 15 의 짝 — 자기 훑기가 자기 영역으로 넘긴 줄은 7번 줄이 세지 않는다(그 셀은 걸러진다). 잡 끝의 넘김 거두기도
    그 줄로 그 셀을 다시 열지 않는다 — 열면 다시 분류돼 또 걸러지고 잡 끝이 그것을 되풀이해 잡이 끝나지 않는다."""
    key, fake, kinds, r = _offcard_handoff_target(store, monkeypatch)
    b = kinds["boundary"]
    r.finish(rig.job(store, key, scope={"agents": [STD1, MECH1, MEM1]}))
    fake.handoff_to, fake.handoff_unit, fake.handoff_from = "std", b, {STD2}
    job_id = rig.job(store, key, scope={"agents": [STD2]})
    r.finish(job_id, ticks=60)
    cell = _cell(store, key, b, STD2)
    assert rig.state(store, job_id) == "completed"
    assert (cell["state"], cell["route_json"]["decision"], cell["route_json"]["handoff"], cell["reopened_n"]) == (
        "na_irrelevant", "filtered", [], 0)
    assert review_cells.handoffs(store, key) == [{"from": STD2, "unit_id": b, "to": "std",
                                                  "why": "훑기가 다른 영역의 몫으로 본 단위"}]
    # 2차 MEDIUM 3 — 그 전문가의 다음 세션(다른 셀의 사람의 다시)이 원장의 훑기를 다시 읽어도 자기 넘김으로 제 셀을 다시 열지 않는다
    other = next(c["unit_id"] for c in _cells(store, key) if c["agent_key"] == STD2 and c["state"] == "reviewed")
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[other, STD2]], force=True, reason="다른 셀을 다시 본다"),
                                  ident=factories.ident(rig.OWNER))
    r.finish(out["job"]["job_id"])
    cell = _cell(store, key, b, STD2)
    assert (cell["state"], cell["reopened_n"]) == ("na_irrelevant", 0)


def _head_state(store, key: str, agent: str) -> str:
    return store.query_one("SELECT state FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?", (key, agent))["state"]


def _std2_filtered_job(store, monkeypatch) -> tuple[str, dict[str, str], rig.Rig]:
    """std 1순위가 먼저 다 닫힌 원장(보충 표본 바닥 0 — 잡 끝이 거른 셀을 표본으로 다시 열지 않는다)."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    monkeypatch.setattr(review_cells, "AUDIT_MIN_N", 0)
    monkeypatch.setattr(review_cells, "AUDIT_DOMAIN_FLOOR", 0)
    key = rig.target(store, SMALL)
    fake = _fake(SMALL)
    kinds = _units(store, key)
    _quiet(fake, kinds["boundary"], kinds["global"])
    r = rig.Rig(store, fake)
    r.finish(rig.job(store, key, scope={"agents": [STD1]}))
    return key, kinds, r


def test_a_cell_reopened_while_its_expert_finalizes_sends_the_head_back_to_planned_and_the_job_ends(store, monkeypatch):
    """반대 검토 4차 LOW 4 · D-49(재현 P3) — 마감이 그 잡의 열린 셀 0 을 센 뒤 마감 트랜잭션 앞에서 다른 세션의 넓힘이 그 전문가의
    거른 셀을 다시 열면(그 잡에 묶인 pending) 마감은 머리를 partial 이 아니라 planned 로 돌린다. 종전에는 partial 로 닫혀 그 셀을
    아무도 집지 못하고(검토 선점은 planned 만 · 마감 선점은 열린 셀이 없어야) 잡이 60시간을 돌아도 끝나지 않았다."""
    key, kinds, r = _std2_filtered_job(store, monkeypatch)
    b = kinds["boundary"]
    job_id = rig.job(store, key, scope={"agents": [STD2]})
    real, fired = expert_report.prepare, []

    def prepare(store_, target_key, agent):
        out = real(store_, target_key, agent)
        if agent == STD2 and not fired:
            fired.append(review_cells.reopen_filtered(store_, target_key, via="widened", domain="std"))
        return out

    monkeypatch.setattr(expert_report, "prepare", prepare)
    for _ in range(30):
        r.tick()
        if fired:
            break
        r.clock.advance(61)
    assert fired == [[(b, STD2)]]
    cell = _cell(store, key, b, STD2)
    assert (_head_state(store, key, STD2), cell["state"], cell["run_id"]) == ("planned", "pending", job_id)
    r.finish(job_id, ticks=30)
    cell = _cell(store, key, b, STD2)
    assert (rig.state(store, job_id), cell["state"], cell["run_id"], _head_state(store, key, STD2)) == (
        "completed", "na_irrelevant", job_id, "ready")


def test_a_ready_head_left_with_a_pending_cell_bound_to_the_live_job_is_planned_again(store, monkeypatch):
    """반대 검토 4차 LOW 4 · D-49 의 안전망 — 어떤 길로든 살아 있는 잡에 묶인 pending 셀이 남았는데 그 전문가 머리가 ready·partial 이면
    (선점할 머리가 없다) 잡 끝 셈 앞에서 그 머리를 planned 로 다시 연다 — 잡이 집을 것 없이 영영 돌지 않는다. 머리를 다시 열지 않은
    묶기(다시 열기의 _reopen 을 건너뛴다)로 그 원장을 만든다."""
    key, kinds, r = _std2_filtered_job(store, monkeypatch)
    b = kinds["boundary"]
    r.finish(rig.job(store, key, scope={"agents": [STD2]}))
    assert (_cell(store, key, b, STD2)["state"], _head_state(store, key, STD2)) == ("na_irrelevant", "ready")
    live = rig.job(store, key, scope={"agents": [STD1]})              # std 1순위의 셀은 다 닫혀 이 잡이 돌 셀은 없다
    real = review_cells._reopen
    monkeypatch.setattr(review_cells, "_reopen", lambda *args, **kwargs: 0)
    assert review_cells.reopen_filtered(store, key, via="widened", domain="std", run_id=live) == [(b, STD2)]
    monkeypatch.setattr(review_cells, "_reopen", real)
    assert (_head_state(store, key, STD2), _cell(store, key, b, STD2)["run_id"]) == ("ready", live)
    r.finish(live, ticks=20)
    cell = _cell(store, key, b, STD2)
    assert (rig.state(store, live), cell["state"], cell["run_id"]) == ("completed", "na_irrelevant", live)


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
    거른 셀이 그 잡의 보충 표본이 아니라 넓힘으로 곧바로 다시 열려 셋째 잡에 묶이고 그 잡이 끝까지 본다(route_forced widened ·
    reviewed — 살아 있는 잡이 다시 연 셀은 그 잡이 돌린다, 반대 검토 3차 MEDIUM 2 · D-47)."""
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
    # 보충 표본은 끝난 잡이 거른 셀(left)까지 표본 점수 순으로 고른다(반대 검토 MEDIUM 7) — 대상 열쇠마다 점수가 달라 b2 가 첫째가
    # 되는 잡 소금을 고른다(잡이 만들 때 얼린다). 그러지 않으면 셋 가운데 무엇을 고르는지가 실행마다 바뀐다.
    pool = [(c["unit_id"], c["agent_key"]) for c in left] + [(b2, MEM2)]
    salt = next(f"s{i}" for i in range(500) if min(pool, key=lambda p, i=i: (review_verify.sample_score(
        "filter_audit", key, *p, salt=f"s{i}"), p)) == (b2, MEM2))
    monkeypatch.setattr(review_verify, "SAMPLE_SALT", salt)
    fake.noinput_q1[b2] = ["yes"]                                     # 끝까지 보니 영향 있음 — 거른 셀이 걸림을 놓쳤다
    third = done({"agents": [MEM2], "unit_ids": [b2]})
    audited = _cell(store, key, b2, MEM2)
    assert (audited["route_forced"], audited["sample_json"]["filter_audit"]["result"]) == (review_cells.FILTER_FLOOR,
                                                                                          "risk_miss")
    assert "mem" in review_cells.widened_domains(store, key)
    reopened = [_cell(store, key, c["unit_id"], c["agent_key"]) for c in left]
    assert {(c["state"], c["route_forced"], c["reopened_n"], c["run_id"]) for c in reopened} == {("reviewed", "widened", 1, third)}


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



@pytest.mark.parametrize("marks", [
    {"contested_by": {"verdict": ["maybe"], "why": "걸릴 수도 있다", "attempt": 1, "raw": "애매"}, "dup_conflict": False},
    {"flipped_from": {"verdict": ["maybe"], "attempt": 1, "raw": "애매"}, "dup_conflict": False},
    {"dup_conflict": True},
])
def test_a_sweep_no_the_engine_marked_as_contested_never_filters_the_cell(store, monkeypatch, marks):
    """반대 검토 HIGH 2 — 훑기 u 줄의 '무관'(rel no)에 엔진이 부딪침 표지(다툼 contested_by · 보충 flipped_from · dup_conflict)를 달았으면
    그 '무관' 은 믿지 않는다(D-42 ④ · M3.md 4.13) — 훑기 신호는 unknown(engine_conflict)이고 셀은 거르지 않고 검토다. 분류 기록에
    그 까닭이 남는다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)

    def setup(fake, kinds):
        fake.sweep_marks = {kinds["boundary"]: marks}

    key, _job, _fake, kinds = _run(store, SMALL, fake_setup=setup)
    cell = _cell(store, key, kinds["boundary"], STD2)
    assert cell["route_json"]["decision"] != "filtered" and cell["state"] == "reviewed"
    assert (cell["route_json"]["sweep"]["verdict"], cell["route_json"]["sweep"]["reason"]) == ("unknown", "engine_conflict")


def test_a_human_retry_keeps_the_sample_marker_so_a_rerun_miss_still_widens_and_a_widening_never_reverts(store, monkeypatch):
    """반대 검토 HIGH 3 — 사람의 다시는 표본 · 그림자 표지를 지우지 않는다(결과만 비우고 앞 결과는 was 에 쌓는다). ① 실패한 보충 표본 셀을
    다시 열어 이번에는 영향 있음(risk_miss)이 나오면 그 영역이 넓어져 남은 거른 셀이 다시 열리고 다시 한 그 잡이 끝까지 본다(살아 있는
    잡이 다시 연 셀은 그 잡에 묶인다 — 3차 MEDIUM 2 · D-47). ② 넓힘의 원인 셀을 강제로 다시 열어도 넓힌 영역은 되돌아가지 않는다(넓힘은
    앞 결과까지 본다)."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key = rig.target(store, ROSTER)
    us = units.load_units(store, key)
    fake = _fake(ROSTER)
    _quiet(fake, *(u["unit_id"] for u in us))
    for u in us:
        fake.noinput_q1[u["unit_id"]], fake.noinput_q2[u["unit_id"]] = ["no"], [""]
    r = rig.Rig(store, fake)
    first = rig.job(store, key, scope={"agents": [STD1, MECH1, MEM1]})
    r.finish(first)
    monkeypatch.setattr(review_cells, "AUDIT_MIN_N", 1)
    fake.error_cells = {(MEM2, u["unit_id"]): {"code": "no_rows", "message": "행이 없다(가짜)", "infra": False, "retryable": False}
                        for u in us}
    second = rig.job(store, key, scope={"agents": [MEM2]})
    r.finish(second)
    cells = {c["unit_id"]: c for c in _cells(store, key) if c["agent_key"] == MEM2}
    failed = [u for u, c in cells.items() if c["state"] == "failed" and c["sample_json"] and "filter_audit" in c["sample_json"]]
    left = [u for u, c in cells.items() if c["state"] == "na_irrelevant"]
    assert len(failed) == 1 and len(left) >= 1
    audit_unit = failed[0]
    fake.error_cells = {}
    fake.noinput_q1[audit_unit] = ["yes"]
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[audit_unit, MEM2]], reason="표본 셀을 다시 본다"),
                                  ident=factories.ident(rig.OWNER))
    retried = _cell(store, key, audit_unit, MEM2)
    assert "filter_audit" in (retried["sample_json"] or {}) and retried["sample_json"]["filter_audit"]["result"] is None
    r.finish(out["job"]["job_id"])
    assert _cell(store, key, audit_unit, MEM2)["sample_json"]["filter_audit"]["result"] == "risk_miss"
    assert "mem" in review_cells.widened_domains(store, key)
    assert {(c["state"], c["route_forced"], c["run_id"]) for c in (_cell(store, key, u, MEM2) for u in left)} == {
        ("reviewed", "widened", out["job"]["job_id"])}

    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[audit_unit, MEM2]], force=True,
                                                             reason="넓힘의 원인 셀을 다시 본다"), ident=factories.ident(rig.OWNER))
    sample = _cell(store, key, audit_unit, MEM2)["sample_json"]
    assert (sample["filter_audit"]["result"], sample.get("was")) == (None, {"filter_audit": ["risk_miss"]})
    assert "mem" in review_cells.widened_domains(store, key)                       # 넓힘은 되돌아가지 않는다

    # 2차 LOW 6 · D-46 — 놓침 증거는 쌓이기만 한다. ③ 다시 돈 표본이 이번에는 놓침이 아니어도(kept) 그 셀은 놓침으로 센다 — 완결 몫 ·
    # 품질 · 보고서가 넓힘과 같은 셈이다(종전에는 지금 결과만 보아 놓침 1 → 0, 95% 상한이 막음에서 안 막음으로 편집자 손에 바뀌었다).
    fake.noinput_q1[audit_unit] = ["no"]
    r.finish(out["job"]["job_id"])
    assert _cell(store, key, audit_unit, MEM2)["sample_json"]["filter_audit"]["result"] == "kept"
    _assert_one_miss(store, key, MEM2, sampled=1)
    # ④ 다시 연 셀이 정산 전에 다른 입력으로 시작하면(start_cell 이 처음부터) 앞 결과(was)가 따라간다 — 넓힘도 놓침 셈도 그대로다.
    # 표지는 지워져 그 셀은 결과를 낸 표본이 아니다 — 바닥(sampled)에는 들지 않고 놓침 수와 비율의 분모에만 든다(3차 LOW 4 · D-47)
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[audit_unit, MEM2]], force=True,
                                                             reason="입력이 바뀐 뒤 다시 본다"), ident=factories.ident(rig.OWNER))
    store.execute("UPDATE rr_review_cells SET input_hash = 'stale-input' WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                  (key, audit_unit, MEM2))
    r.finish(out["job"]["job_id"])
    cell = _cell(store, key, audit_unit, MEM2)
    assert cell["state"] in ("reviewed", "no_input") and (cell["sample_json"] or {}).get("was") == {
        "filter_audit": ["risk_miss", "kept"]}
    assert "mem" in review_cells.widened_domains(store, key)
    _assert_one_miss(store, key, MEM2, sampled=0)


def _assert_one_miss(store, key: str, agent: str, *, sampled: int) -> None:
    """놓침 하나 — 완결 몫(거름 표본) · 품질 수치 · 전문가 보고서 머리가 같은 셈이다. 표본 수는 결과를 낸 표본(지금 표지에 결과가
    있다)이고 비율의 분모는 그 수에 결과를 아직 못 낸 놓침을 더한다(3차 LOW 4 · D-47)."""
    from app import expert_report, review_quality

    quality = review_quality.compute(store, key)["filter"]["audit"]
    assert (quality["sampled"], quality["counts"]["risk_miss"], quality["risk_miss"]["den"]) == (sampled, 1, 1)
    audit = review_cells.closure_cells(store, key)["filtered"]["audit"]
    assert (audit["sampled"], audit["risk_miss"]) == (sampled, 1)
    head = expert_report.load_report(store, key, agent)["head"]["filter"]
    assert head["risk_miss"] == 1


def test_an_audit_that_never_produced_a_result_does_not_meet_the_floor(store, monkeypatch):
    """반대 검토 MEDIUM 6 — 표본 바닥(floor_met)은 결과를 낸 표본만 센다(전체와 영역마다). 거른 셀이 남은 대상에서 유일한 보충 표본이
    끝내 실패하면 표본 0 이라 바닥에 못 미치고 완결의 '거름' 잔여가 막는다(종전에는 실패한 표본을 세어 floor_met 이 참, 95% 상한도
    없어 막지 않았다). 그 표본은 '대기' 가 아니라 '실패' 로 센다."""
    from app import closure

    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key = rig.target(store, ROSTER)
    us = units.load_units(store, key)
    bundles = [u["unit_id"] for u in us if u["kind"] == "bundle"]
    fake = _fake(ROSTER)
    _quiet(fake, *bundles)                                            # 회로(mem)만 걸러진다 — std 는 묶음에서 코드 신호가 관련이다
    for u in us:
        fake.noinput_q1[u["unit_id"]], fake.noinput_q2[u["unit_id"]] = ["no"], [""]
    r = rig.Rig(store, fake)
    r.finish(rig.job(store, key, scope={"agents": [STD1, MECH1, MEM1]}))
    monkeypatch.setattr(review_cells, "AUDIT_MIN_N", 1)
    fake.error_cells = {(MEM2, u): {"code": "no_rows", "message": "행이 없다(가짜)", "infra": False, "retryable": False}
                        for u in bundles}
    r.finish(rig.job(store, key, scope={"agents": [MEM2]}))
    cells = [c for c in _cells(store, key) if c["agent_key"] == MEM2 and c["unit_id"] in bundles]
    assert sorted(c["state"] for c in cells) == ["failed", "na_irrelevant", "na_irrelevant"]
    audit = review_cells.closure_cells(store, key)["filtered"]["audit"]
    assert (audit["sampled"], audit["pending"], audit["failed"], audit["n_audit"], audit["floor_met"]) == (0, 0, 1, 1, False)
    residual = next(r for r in closure.residuals(store, key, closure.cell_counts(store, key)) if r["item"] == "filtered")
    assert residual["blocking"] is True


@pytest.mark.parametrize("was", ["kept", "relevance_miss", "risk_miss"])
def test_a_sample_whose_marker_an_input_change_cleared_counts_only_an_earlier_miss(store, monkeypatch, was):
    """반대 검토 2차 LOW 6 · MEDIUM 4 · 3차 LOW 4 · D-47 — 입력이 바뀌어 표지가 지워진 셀(앞 결과만 sample_json.was 에 남는다)은 결과를
    낸 표본이 아니다 — 결과를 낸 표본은 지금 표지에 결과가 있는 것이고, 잡 끝 보충 표본 · 완결 몫 · 품질이 똑같이 바닥에 세지 않는다
    (셋이 다르게 세면 바닥을 두고 갈린다 — 2차 MEDIUM 4). 앞 결과는 놓침만 센다 — 놓침이면 놓침 수와 비율의 분모에 들고(놓침 증거는
    쌓이기만 한다), 놓침이 아니면 어디에도 세지 않는다(보고서도 그 셀을 '표본으로 끝까지 봄' 으로 적지 않는다)."""
    from app import expert_report, review_quality

    key, _job, kinds, r, gate, _fake = _filtered_mid_job(store, monkeypatch)
    store.execute("UPDATE rr_review_cells SET sample_json = json_object('was', json_object('filter_audit', json_array(?)))"
                  " WHERE target_key = ? AND unit_id = ? AND agent_key = ?", (was, key, kinds["global"], STD1))
    miss = int(was == "risk_miss")
    counts = {"risk_miss": miss, "relevance_miss": 0, "undetermined": 0, "kept": 0}
    quality = review_quality.compute(store, key)["filter"]["audit"]
    assert (quality["sampled"], quality["counts"], quality["risk_miss"]["den"]) == (0, counts, miss)
    closure_audit = review_cells.closure_cells(store, key)["filtered"]["audit"]
    out = review_cells.audit_topup(store, key, "another-job", audit_pct=0, salt="s")
    assert (out["n"], out["sampled"], closure_audit["sampled"]) == (1 + miss, 0, 0)
    assert (closure_audit["pending"], closure_audit["failed"]) == (0, 0)          # 앞 놓침만 남은 셀은 결과를 못 낸 표본도 아니다
    assert {k: closure_audit[k] for k in review_cells.AUDIT_RESULTS} == counts
    assert (closure_audit["upper95"] is None) is not bool(miss)
    head = expert_report.build_report(store, key, STD1)["head"]["filter"]
    assert (head["audited"], head["risk_miss"]) == (miss, miss)
    gate.set()
    r.loop.join(30)


def test_a_refiltered_cell_with_only_an_earlier_non_miss_result_never_fills_the_floor(store, monkeypatch):
    """반대 검토 3차 LOW 4 · D-47(재현 D) — 잡 끝 보충 표본으로 끝까지 본 셀(놓침이 아닌 결과)을 사람이 강제로 다시 열고 정산 전에 입력이
    바뀌면 표지가 지워져 그 셀은 다시 걸러진다(앞 결과만 was 에 남는다). 놓침이 아닌 앞 결과는 그 셀을 결과를 낸 표본으로 만들지
    않는다 — 그 잡 끝 보충 표본이 바닥을 다시 채워 그 셀을 새 표본으로 끝까지 본다. 종전에는 앞 결과로 바닥이 찼다고 보아 아무것도
    다시 열지 않았고(완결 몫 floor_met 참 · 보충 0), 보고서는 거른 셀을 '표본으로 끝까지 봄 — 결과 «relevance_miss»' 로 적었다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key = rig.target(store, SMALL)
    fake = _fake(SMALL)
    kinds = _units(store, key)
    _quiet(fake, kinds["boundary"], kinds["global"])
    b = kinds["boundary"]
    r = rig.Rig(store, fake)
    r.finish(rig.job(store, key, scope={"agents": [STD1]}))
    r.finish(rig.job(store, key, scope={"agents": [STD2]}))         # std 2순위가 b 를 거르고 잡 끝 보충 표본이 b 를 끝까지 본다
    first = _cell(store, key, b, STD2)["sample_json"]["filter_audit"]
    assert first["result"] in review_cells.AUDIT_RESULTS and first["result"] != "risk_miss"
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[b, STD2]], force=True, reason="표본을 다시 본다"),
                                  ident=factories.ident(rig.OWNER))
    store.execute("UPDATE rr_review_cells SET input_hash = 'stale-input' WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                  (key, b, STD2))                                   # 다시 연 셀이 정산 전에 다른 입력으로 시작한다(처음부터)
    r.finish(out["job"]["job_id"])
    cell = _cell(store, key, b, STD2)
    assert (cell["state"], cell["route_forced"]) == ("reviewed", review_cells.FILTER_FLOOR)
    assert cell["sample_json"]["filter_audit"]["result"] in review_cells.AUDIT_RESULTS
    assert cell["sample_json"]["was"] == {"filter_audit": [first["result"]]}
    audit = review_cells.closure_cells(store, key)["filtered"]["audit"]
    assert (audit["sampled"], audit["n_audit"], audit["floor_met"]) == (1, 1, True)               # 새 결과로 바닥이 찼다


def test_an_audit_closed_without_a_result_is_replaced_by_the_next_top_up(store, monkeypatch):
    """반대 검토 2차 MEDIUM 4 · D-46 — 잡 끝 보충 표본이 바닥을 셀 때 결과를 낸 표본과 아직 도는 표본만 센다. 결과 없이 닫힌 표본(끝내
    실패해 넘긴 것)은 세지 않고 그 자리를 다른 거른 셀로 채운다 — 종전에는 표지만 보고 세어 need 0 이라 아무것도 다시 열지 않았고,
    완결 몫(결과를 낸 것만 센다)은 floor_met 거짓이라 사람의 확인 없이는 풀리지 않았다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key = rig.target(store, ROSTER)
    us = units.load_units(store, key)
    bundles = [u["unit_id"] for u in us if u["kind"] == "bundle"]
    fake = _fake(ROSTER)
    _quiet(fake, *bundles)
    for u in us:
        fake.noinput_q1[u["unit_id"]], fake.noinput_q2[u["unit_id"]] = ["no"], [""]
    r = rig.Rig(store, fake)
    r.finish(rig.job(store, key, scope={"agents": [STD1, MECH1, MEM1]}))
    monkeypatch.setattr(review_cells, "AUDIT_MIN_N", 1)
    fake.error_cells = {(MEM2, u): {"code": "no_rows", "message": "행이 없다(가짜)", "infra": False, "retryable": False}
                        for u in bundles}
    r.finish(rig.job(store, key, scope={"agents": [MEM2]}))
    failed = next(c for c in _cells(store, key) if c["agent_key"] == MEM2 and c["state"] == "failed")
    fake.error_cells = {}
    out = routes.post_cells_skip(key, routes.CellsSkipBody(cells=[[failed["unit_id"], MEM2]], reason="표본이 끝내 실패했다"),
                                 ident=factories.ident(rig.OWNER))
    r.finish(out["job"]["job_id"])
    cells = [c for c in _cells(store, key) if c["agent_key"] == MEM2 and c["unit_id"] in bundles]
    replaced = [c for c in cells if c["route_forced"] == review_cells.FILTER_FLOOR and c["state"] in ("reviewed", "no_input")]
    assert [c["unit_id"] for c in replaced] != [] and failed["unit_id"] not in [c["unit_id"] for c in replaced]
    audit = review_cells.closure_cells(store, key)["filtered"]["audit"]
    assert (audit["sampled"], audit["failed"], audit["floor_met"]) == (1, 1, True)


def test_the_job_end_top_up_reopens_cells_an_ended_job_filtered_and_stamps_them_with_its_own_job(store, monkeypatch):
    """반대 검토 MEDIUM 7 — 잡 끝 보충 표본은 끝난(취소된) 잡이 거른 셀도 고른다 — 그 셀을 이 잡 id 로 찍어 이 잡이 끝까지 돌린다.
    종전에는 제 잡이 거른 셀만 골라 앞 잡을 취소하면 거른 셀이 영영 거른 채였고(바닥 미달) 잔여가 확인 없이는 풀리지 않았다."""
    from app import runner

    key, first, kinds, r, gate, fake = _filtered_mid_job(store, monkeypatch)
    b = kinds["boundary"]
    runner.cancel_job(store, first, by=rig.OWNER)
    gate.set()
    r.loop.join(30)
    r.finish(first)
    assert rig.state(store, first) == "cancelled" and _cell(store, key, b, STD2)["state"] == "na_irrelevant"
    second = rig.job(store, key, scope={"agents": [STD1]})
    r.finish(second)
    assert rig.state(store, second) == "completed"
    cell = _cell(store, key, b, STD2)
    assert (cell["state"], cell["route_forced"], cell["run_id"]) == ("reviewed", review_cells.FILTER_FLOOR, second)
    assert review_cells.closure_cells(store, key)["filtered"]["audit"]["floor_met"] is True


def test_a_crash_between_settling_a_sample_and_widening_loses_neither_the_result_nor_the_reopen(store, monkeypatch):
    """반대 검토 MEDIUM 10 ① — 표본 셀의 결과(risk_miss)는 정산과 같은 트랜잭션에 적힌다. 넓힘(거른 셀 다시 열기) 직전에 죽어도 결과는
    남고(불변식 G9 — 닫힌 표본 셀에 결과가 없으면 걸린다), 잡 끝이 넓힌 영역의 남은 거른 셀을 다시 연다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key = rig.target(store, ROSTER)
    us = units.load_units(store, key)
    bundles = [u["unit_id"] for u in us if u["kind"] == "bundle"]
    fake = _fake(ROSTER)
    _quiet(fake, *bundles)
    for u in us:
        fake.noinput_q1[u["unit_id"]], fake.noinput_q2[u["unit_id"]] = ["no"], [""]
    r = rig.Rig(store, fake)
    r.finish(rig.job(store, key, scope={"agents": [STD1, MECH1, MEM1]}))
    monkeypatch.setattr(review_cells, "AUDIT_MIN_N", 1)
    for u in bundles:
        fake.noinput_q1[u] = ["yes"]                                  # 보충 표본이 끝까지 보면 영향 있음 — 놓친 걸림
    real, crashed = review_cells.widen, []

    def crash_once(*args, **kwargs):
        if not crashed:
            crashed.append(1)
            raise RuntimeError("넓히기 직전에 죽었다(가짜)")
        return real(*args, **kwargs)

    monkeypatch.setattr(review_cells, "widen", crash_once)
    job_id = rig.job(store, key, scope={"agents": [MEM2]})
    r.finish(job_id)
    assert crashed and rig.state(store, job_id) == "completed"
    cells = {c["unit_id"]: c for c in _cells(store, key) if c["agent_key"] == MEM2 and c["unit_id"] in bundles}
    audited = [c for c in cells.values() if c["route_forced"] == review_cells.FILTER_FLOOR]
    assert [c["sample_json"]["filter_audit"]["result"] for c in audited] == ["risk_miss"]
    assert review_cells.review_invariants(store, key) == []
    assert "mem" in review_cells.widened_domains(store, key)
    assert {c["state"] for c in cells.values()} - {"reviewed"} <= {"pending"}            # 남은 거른 셀은 다시 열렸다
    assert not any(c["state"] == "na_irrelevant" for c in cells.values())


def test_a_closed_sample_cell_without_its_result_breaks_the_invariant(store, monkeypatch):
    """불변식 G9(반대 검토 MEDIUM 10) — 닫힌(reviewed) 표본 셀에는 결과가 있다. 결과가 빠진 표본 셀(정산과 결과가 갈라진 원장)은
    완결 몫의 불변식에 걸린다(넓힘 신호를 잃은 원장이 조용히 완결되지 않게)."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)

    def setup(fake, kinds):
        fake.noinput_q1 = {kinds["boundary"]: ["no"]}
        fake.noinput_q2 = {kinds["boundary"]: [""]}

    key, _job, _fake, _kinds = _run(store, fake_setup=setup)
    audited = next(c for c in _cells(store, key) if c["route_forced"] == review_cells.FILTER_FLOOR)
    assert audited["state"] in ("reviewed", "no_input") and audited["sample_json"]["filter_audit"]["result"]
    store.execute("UPDATE rr_review_cells SET sample_json = json_set(sample_json, '$.filter_audit.result', json('null'))"
                  " WHERE target_key = ? AND unit_id = ? AND agent_key = ?", (key, audited["unit_id"], audited["agent_key"]))
    assert any("(G9)" in p for p in review_cells.review_invariants(store, key))


def test_a_crash_between_writing_the_sweep_and_reopening_its_handoff_is_replayed_on_restart(store, monkeypatch):
    """반대 검토 MEDIUM 10 ② — 훑기를 적은 뒤 그 넘김(h 줄)으로 거른 셀을 다시 열기 전에 죽어도, 다음 세션이 원장의 훑기를 다시 읽을 때
    그 다시 열기를 이어 한다(거른 셀만 여므로 멱등)."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    roster = (*SMALL, {"key": "xd-syn-0", "domain": "xd", "relevance": 0.99}, {"key": "xd-syn-1", "domain": "xd", "relevance": 0.9})
    real, crashed = review_cells.reopen_filtered, []

    def crash_once(*args, **kwargs):
        if kwargs.get("via") == "handoff" and not crashed:
            crashed.append(1)
            raise RuntimeError("넘김을 다시 열기 직전에 죽었다(가짜)")
        return real(*args, **kwargs)

    def setup(fake, kinds):
        fake.handoff_to, fake.handoff_unit, fake.handoff_from = "std", kinds["boundary"], {"xd-syn-1"}
        monkeypatch.setattr(review_cells, "reopen_filtered", crash_once)

    key, _job, _fake, kinds = _run(store, roster, fake_setup=setup)
    cell = _cell(store, key, kinds["boundary"], STD2)
    assert crashed and (cell["state"], cell["route_forced"]) == ("reviewed", "handoff")
