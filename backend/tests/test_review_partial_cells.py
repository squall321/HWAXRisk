# 넘긴 셀 한 길(반대 검토 3차 HIGH 1 · D-47) — 같은 자료면 넘긴 셀의 finding 이 검토한 셀의 것과 같다(표지 '넘긴 셀 — 일부만 판정' 만 다르다)
"""자료는 생산자 경로(가짜 엔진의 검토 루프)로 짓고, 같은 원장에서 셀 상태만 reviewed · skipped 로 바꿔 보고서의 구성원 함수
(`expert_report.build_findings`)가 내는 finding 을 견준다. 넘긴 셀의 셈(`Ledger.member_counts`)은 그 함수들이 실제로 낸 구성원 수다."""
from __future__ import annotations

import dataclasses

import pytest

from app import config, expert_report, units
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.test_review_noinput import MEM1
from tests.test_review_noinput import ROSTER as GAP_ROSTER
from tests.test_review_noinput import _packs as gap_packs

K01 = str(fre.load("pack_ok.json")["cards"][0]["record_id"])
NO_ROWS = {"code": "no_rows", "message": "판정 행이 하나도 없다(가짜)", "infra": False, "retryable": False}
CONTESTED = {"verdict": ["yes", "FAIL"], "why": "같은 카드의 다른 답", "attempt": 1, "raw": "FAILED?"}

# 갈래 — (전문가, 가짜 엔진 스위치, 이중 판정, finding 이 서나, 셈의 종류)
NO_OFFCARD = {"offcard_findings": 0}                 # 카드 갈래는 카드 밖 f 줄 없이(가짜 엔진의 기본은 한 줄이다)
CASES = {
    "card_fail": (rig.SEAL, {**NO_OFFCARD, "verdicts": {K01: ("yes", "FAIL")}}, "all", True, "card"),
    "card_warning": (rig.SEAL, {**NO_OFFCARD, "verdicts": {K01: ("yes", "WARNING")}}, "all", True, "card"),
    "card_split": (rig.SEAL, {**NO_OFFCARD, "verdicts": {K01: ("yes", "FAIL")}, "rev_verdicts": {K01: ("yes", "OK")},
                              "solo_verdicts": {K01: ("yes", "OK")}}, "all", True, "card"),
    "card_marked_judged": (rig.SEAL, {**NO_OFFCARD, "dup_conflict": {"K01"}, "contested": {"K01": CONTESTED}}, "all", False,
                           None),
    "card_marked_unjudged": (rig.SEAL, {**NO_OFFCARD, "verdicts": {K01: ("unknown", "undetermined")},
                                        "dup_conflict": {"K01"}, "contested": {"K01": CONTESTED},
                                        "error_kinds": {"verdict:rev"}}, "flagged", True, "card"),
    "offcard_risk": (rig.ZERO_CARDS, {"offcard_findings": 1}, "all", True, "offcard"),
    "noinput_yes": (MEM1, {"noinput_script": [[{"impact": "yes", "title": "A"}]]}, "all", True, "noinput"),
    "noinput_unknown": (MEM1, {"noinput_script": [[{"impact": "unknown", "title": "A"}]]}, "all", False, None),
}


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_review_concurrency=1)
    return risk_store


def _ledger_data(store, monkeypatch, agent: str, switches: dict, dual: str) -> tuple[str, str]:
    """그 갈래의 자료를 가진 셀 하나(그 전문가 × 첫 단위) — (대상, 단위)."""
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_dual=dual))
    gap = agent == MEM1
    key = rig.target(store, GAP_ROSTER) if gap else rig.target(store)
    unit_id = units.load_units(store, key)[0]["unit_id"]
    fake = FakeReviewEngine(gap_packs(GAP_ROSTER) if gap else rig.packs())
    for name, value in switches.items():
        if name == "noinput_script":
            fake.noinput_script, fake.noinput_q2 = {unit_id: value}, {unit_id: [""]}
        elif name == "error_kinds":
            fake.error_cells, fake.error_kinds = {(agent, unit_id): NO_ROWS}, value
        else:
            setattr(fake, name, value)
    rig.Rig(store, fake).finish(rig.job(store, key, scope={"agents": [agent], "unit_ids": [unit_id]}))
    return key, unit_id


def _findings_as(store, key: str, agent: str, unit_id: str, state: str) -> tuple[list[dict], dict | None]:
    """같은 원장에서 셀 상태만 바꿔 그 단위의 finding 과 넘긴 셀의 구성원 셈."""
    store.execute("UPDATE rr_review_cells SET state = ?, decided_by = ?, decide_note = ? WHERE target_key = ? AND unit_id = ?"
                  " AND agent_key = ?", (state, rig.OWNER if state == "skipped" else None,
                                         "같은 자료를 넘긴 셀로 본다" if state == "skipped" else None, key, unit_id, agent))
    ledger = expert_report.load_ledger(store, key, agent)
    found = [f for f in expert_report.build_findings(store, ledger)["findings"] if f["unit_ids"] == [unit_id]]
    return found, getattr(ledger, "member_counts", {}).get(unit_id)


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_skipped_cell_yields_the_reviewed_cells_findings_for_the_same_data(store, monkeypatch, case):
    """반대 검토 3차 HIGH 1 · D-47 — 넘긴 셀은 검토한 셀과 같은 구성원 함수(카드 · 카드 밖 · 입력 결손)를 가진 자료 그대로 지난다. 같은
    자료면 finding 이 같고(표지 partial_cell 만 다르다), 넘긴 셀의 셈은 그 함수들이 낸 구성원이다(영향 모름 · 두 번째 판정까지 받은
    부딪침 표지는 finding 이 아니라 둘 다 0)."""
    agent, switches, dual, expect, kind = CASES[case]
    key, unit_id = _ledger_data(store, monkeypatch, agent, switches, dual)
    reviewed, _ = _findings_as(store, key, agent, unit_id, "reviewed")
    skipped, counts = _findings_as(store, key, agent, unit_id, "skipped")

    def strip(rows: list[dict]) -> list[dict]:
        return [{k: v for k, v in f.items() if k != "partial_cell"} for f in rows]

    assert strip(skipped) == strip(reviewed)
    assert bool(reviewed) is expect
    assert all(f.get("partial_cell") for f in skipped) and not any(f.get("partial_cell") for f in reviewed)
    assert {k for k, n in (counts or {}).items() if n} == ({kind} if kind else set())


def _clean_unit(store, key: str, agent: str) -> str:
    """그 전문가의 둘째 단위를 깨끗하게 검토한다(카드 OK · 카드 밖 없음 · 입력 결손은 영향 없음) — 바탕 입장 agree. 그 단위."""
    other = units.load_units(store, key)[1]["unit_id"]
    gap = agent == MEM1
    clean = FakeReviewEngine(gap_packs(GAP_ROSTER) if gap else rig.packs())
    clean.offcard_findings = 0
    if gap:
        clean.noinput_script, clean.noinput_q2 = {other: [[{"impact": "no", "title": "B"}]]}, {other: [""]}
    rig.Rig(store, clean).finish(rig.job(store, key, scope={"agents": [agent], "unit_ids": [other]}))
    assert store.query_one("SELECT state FROM rr_review_cells WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                           (key, other, agent))["state"] == "reviewed"
    return other


@pytest.mark.parametrize("case", sorted(CASES))
def test_a_skipped_cell_raises_the_stance_exactly_as_the_same_reviewed_cell_would(store, monkeypatch, case):
    """반대 검토 4차 MEDIUM 1 · D-49 — 넘긴 셀의 걸림 후보는 검토한 셀과 같은 걸림 줄(X1-15)로 입장을 올린다(한 길 — D-47). 깨끗하게
    검토한 단위 하나(바탕 agree)가 있는 원장에서 같은 자료의 셀을 검토한 셀로 두든 넘긴 셀로 두든 입장이 같다 — 넘긴 셀이 검토한 셀보다
    더 올리거나 덜 올리지 않는다(기권 판단만 검토한 셀의 몫이다)."""
    agent, switches, dual, _expect, _kind = CASES[case]
    key, unit_id = _ledger_data(store, monkeypatch, agent, switches, dual)
    _clean_unit(store, key, agent)
    stances = {}
    for state in ("reviewed", "skipped"):
        _findings_as(store, key, agent, unit_id, state)
        stances[state] = expert_report.prepare(store, key, agent).opinion["final_stance"]
    assert stances["skipped"] == stances["reviewed"]


@pytest.mark.parametrize("state", ["reviewed", "skipped"])
def test_an_input_gap_impact_yes_raises_the_stance_to_conditional_reviewed_or_skipped(store, monkeypatch, state):
    """조정자 결정(4차 해석 4) — 입력 결손 q1 '영향 있음'(impact=yes)은 검토한 셀이든 넘긴 셀이든 입장을 conditional 로 올린다 — 확인되지
    않은 영향이라 입력이 와야 확인한다(oppose 는 아니다). 종전에는 걸림 줄이 입력 결손 finding 을 보지 않아 agree 였다."""
    key, unit_id = _ledger_data(store, monkeypatch, MEM1, {"noinput_script": [[{"impact": "yes", "title": "A"}]]}, "all")
    _clean_unit(store, key, MEM1)
    found, _ = _findings_as(store, key, MEM1, unit_id, state)
    assert [(f["input_gap"], f["direction"], f.get("judgement_claimed")) for f in found] == [(True, "risk", "WARNING")]
    assert expert_report.prepare(store, key, MEM1).opinion["final_stance"] == "conditional"


def test_an_input_gap_impact_unknown_leaves_the_stance_and_stays_in_the_input_gap_and_needs_sections(store):
    """조정자 결정(4차 해석 4) — 입력 결손 q1 '영향 모름'(impact=unknown)은 입장을 바꾸지 않는다(finding 이 아니다). 그 셀은 no_input 으로
    닫히고 입력 결손 절의 영향 줄과 필요한 정보(q2 — 결측 입력이 오면 확인할 것)에 그대로 남는다."""
    key = rig.target(store, GAP_ROSTER)
    unit_id = units.load_units(store, key)[0]["unit_id"]
    fake = FakeReviewEngine(gap_packs(GAP_ROSTER))
    fake.noinput_script = {unit_id: [[{"impact": "unknown", "title": "A"}]]}
    rig.Rig(store, fake).finish(rig.job(store, key, scope={"agents": [MEM1], "unit_ids": [unit_id]}))
    _clean_unit(store, key, MEM1)
    assert store.query_one("SELECT state FROM rr_review_cells WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                           (key, unit_id, MEM1))["state"] == "no_input"
    prepared = expert_report.prepare(store, key, MEM1)
    assert (prepared.opinion["final_stance"], [f["unit_ids"] for f in prepared.findings]) == ("agree", [])
    (row,) = [u for u in prepared.report["input_gap"]["units"] if u["unit_id"] == unit_id]
    assert [i["impact"] for i in row["impacts"]] == ["unknown"] and row["requests"]
    (needs,) = [u for u in prepared.report["needs_info"] if u["unit_id"] == unit_id]
    assert {src for item in needs["items"] for src in item["from"]} == {"noinput"}
