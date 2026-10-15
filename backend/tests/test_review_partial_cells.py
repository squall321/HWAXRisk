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
