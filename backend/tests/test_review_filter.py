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

from app import config, relevance, review_cells, units
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
    fake = FakeReviewEngine(_packs(roster))
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
    """승인 · 거르기 on · 표본 0% — 두 신호가 다 무관인 셀만 걸러진다(na_irrelevant · route/basis filtered · 선점 없음 · 그 셀의
    판정·카드 밖 호출 0). 입력 결손 전문가도 훑기가 결측 블록을 받은 판(cr-sweep-2)이면 같은 규칙으로 걸러지고, 나머지 셀은 입력
    결손 호출 길(route noinput)이다. 강제 줄은 저마다 그 이름으로 셀을 검토에 남긴다 — 1순위(그 셀이 거를 셀이었으면 그림자) · 전역
    단위 · 카드 0장. 코드 신호가 관련이거나 훑기가 maybe 인 셀은 강제 없이 검토다. 걸러진 셀의 route_json 에 두 신호와 규칙·판
    표지가 얼고, 거른 셀만 남은 전문가는 없으니 원장은 그대로 닫힌다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key, job_id, fake, kinds = _run(store)
    b, g, u1 = kinds["boundary"], kinds["global"], kinds["bundle"]

    filtered = [c for c in _cells(store, key) if c["state"] == "na_irrelevant"]
    assert [(c["unit_id"], c["agent_key"]) for c in filtered] == [(b, MEM2), (b, STD2)]
    cell = filtered[1]
    assert (cell["route"], cell["route_forced"], cell["basis"], cell["lease_owner"]) == ("filtered", None, "filtered", None)
    assert cell["finished_at"] is not None and cell["run_id"] == job_id
    rj = cell["route_json"]
    assert (rj["rule"], rj["decision"], rj["filter"], rj["forced_all"], rj["handoff"], rj["audit"]) == (
        "both_unrelated", "filtered", "on", [], [], {"score": rj["audit"]["score"], "pct": 0})
    assert rj["routing_rev"] == relevance.routing_rev()
    assert (rj["code"]["verdict"], rj["sweep"]["verdict"], rj["sweep"]["rel"], rj["sweep"]["k"]) == (
        "unrelated", "unrelated", "no", [])
    assert "std" not in rj["code"]["related_domains"] and "mech" in rj["code"]["related_domains"]
    assert [x["kind"] for x in _unit_runs(fake, STD2, b)] == []               # 걸러진 셀은 아무 호출도 받지 않는다

    def route(unit_id, agent):
        c = _cell(store, key, unit_id, agent)
        return c["state"], c["route"], c["route_forced"]

    assert route(b, STD1) == ("reviewed", "review", "rank1")
    assert _cell(store, key, b, STD1)["sample_json"]["shadow"] == {"would_filter": True, "result": None}
    assert route(g, STD2) == ("reviewed", "review", "global_unit")
    assert route(b, STD3) == ("reviewed", "review", "no_cards")
    assert route(b, MEM2)[:2] == ("na_irrelevant", "filtered")               # 결측 블록을 받은 훑기(cr-sweep-2)의 무관
    assert _cell(store, key, b, MEM2)["route_json"]["forced_all"] == []
    assert route(u1, MEM2) == ("reviewed", "noinput", None)                   # 훑기 maybe — 입력 결손 호출 길
    assert route(g, MEM2) == ("reviewed", "noinput", "global_unit")
    assert route(b, MEM1) == ("reviewed", "noinput", "rank1")
    assert route(b, MECH2) == ("reviewed", "review", None)                    # 코드 신호가 관련 — 10번 줄
    assert _cell(store, key, b, MECH2)["route_json"]["rule"] == "signal_related"
    assert route(u1, STD2) == ("reviewed", "review", None)
    # 1순위 그림자 — 그 사람이 1순위가 아니었다면 걸렀을 셀만. 다른 강제 줄이 걸린 셀(전역 단위)은 그림자가 아니다.
    shadows = sorted((c["unit_id"], c["agent_key"]) for c in _cells(store, key) if (c["sample_json"] or {}).get("shadow"))
    assert shadows == [(b, MEM1), (b, STD1)]
    assert {c["route"] for c in _cells(store, key)} <= {"filtered", "review", "noinput"}
    tally = review_cells.expert_tally(store, key, STD2)
    assert (tally["filtered"], tally["reviewed"], tally["open"]) == (1, 4, 0)
    ledger = {r["agent_key"]: r["status"] for r in store.query("SELECT agent_key, status FROM rr_coverage WHERE"
                                                               " target_key = ?", (key,))}
    assert ledger[STD2] == "done"


def test_the_audit_rate_sends_the_cell_to_the_end_and_a_full_rate_filters_nothing(store, monkeypatch):
    """표본 100% — 거를 셀이 걸러지지 않고 끝까지 판정된다(route audit · filter_audit · sample_json.filter_audit 의 점수와
    picked_by rate, 결과는 정산 몫이라 비었다). 시도 표지(attempt)는 남는다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=100)
    key, _job, fake, kinds = _run(store, SMALL)
    cell = _cell(store, key, kinds["boundary"], STD2)
    assert (cell["state"], cell["route"], cell["route_forced"]) == ("reviewed", "audit", "filter_audit")
    assert cell["route_json"]["decision"] == "audit" and cell["route_json"]["audit"]["pct"] == 100
    audit = cell["sample_json"]["filter_audit"]
    assert audit == {"score": cell["route_json"]["audit"]["score"], "picked_by": "rate", "result": None}
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
    assert cell["sample_json"]["shadow"] == {"would_filter": True, "result": None}
    assert [c for c in _cells(store, key) if c["state"] == "na_irrelevant"] == []


def test_a_closed_approval_gate_filters_nothing_even_with_the_filter_on(store, monkeypatch):
    """승인 문이 닫힌 표(초안)로 만든 잡 — 코드 신호가 전 영역 모름(not_approved)이라 아무것도 걸러지지 않는다(#40). 잡은 그
    승인 여부를 얼린다 — 잡이 선 뒤에 문이 열려도 그 잡은 거르지 않는다."""
    key = rig.target(store, SMALL)
    job_id = rig.job(store, key)
    _approve(monkeypatch)                                   # 잡이 선 뒤에 연 문은 그 잡에 듣지 않는다
    fake = FakeReviewEngine(_packs(SMALL))
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


# ---------------------------------------------------------------- 재기동
def test_a_restart_keeps_the_classification_and_never_reclassifies(store, monkeypatch):
    """1순위가 먼저 다 닫힌 뒤 2순위 세션이 분류하고 판정 호출 도중 죽는다 — 재기동 복구 뒤 새 러너는 걸러진 셀을 다시 열지 않고
    검토 셀의 분류(route·route_json)를 그대로 둔 채 이어 돈다. 걸러진 셀은 끝까지 호출 0 이다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    key = rig.target(store, SMALL)
    fake = FakeReviewEngine(_packs(SMALL))
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
    assert {u: (c["route"], c["route_forced"], c["route_json"]) for u, c in after.items()} == {
        u: v[1:] for u, v in classified.items()}
    assert after[kinds["boundary"]]["state"] == "na_irrelevant"
    assert [x["kind"] for x in _unit_runs(fake, STD2, kinds["boundary"])] == []
    assert review_cells.review_invariants(store, key) == []
