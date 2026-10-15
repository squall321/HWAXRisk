# 거르기가 꺼진 뒤 남은 거른 셀(넓힘과 다시 열기 사이에 잡이 죽거나 취소된 원장) — 잔여 표기와 길잡이가 검토 잡을 걸음으로 주는지 본다
from __future__ import annotations

import pytest

from app import closure, config, review_cells, synth
from tests import factories
from tests.synth import review_rig as rig
from tests.synth.fake_summary_engine import FakeSummaryEngine
from tests.test_review_filter import MECH1, MEM1, MEM2, STD1, STD2, _approve, _cell, _knobs, _risk_miss, _run
from tests.test_review_mcp import _call, _project_with_source


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_review_concurrency=1)
    return risk_store


def _filtered(store, key):
    result = closure.close_level_cells(store, key, persist=False)
    return next((q for q in result["qualifiers"] if q["item"] == "filtered"), None)


def _finish_chain(store):
    worker = synth.SynthWorker(store, config.settings, FakeSummaryEngine())
    for _ in range(300):
        if worker.tick()["step"] == "idle":
            return


def _leave_filtered_cells(monkeypatch):
    """표본 바닥을 0 으로 — 잡 끝 보충 표본이 거른 셀을 다 다시 열지 않아 거른 셀이 남는다."""
    _approve(monkeypatch)
    _knobs(monkeypatch, risk_filter_audit_pct=0)
    monkeypatch.setattr(review_cells, "AUDIT_MIN_N", 0)
    monkeypatch.setattr(review_cells, "AUDIT_DOMAIN_FLOOR", 0)

    def setup(fake, kinds):
        fake.noinput_q1 = {kinds["boundary"]: ["no"]}
        fake.noinput_q2 = {kinds["boundary"]: [""]}
    return setup


def test_거르기가_꺼진_채_남은_거른_셀은_꺼짐을_말하고_길잡이가_검토_잡을_준다(store, monkeypatch):
    key, _job, fake, kinds = _run(store, fake_setup=_leave_filtered_cells(monkeypatch))
    project_id = _project_with_source(store, key)
    b = kinds["boundary"]
    _finish_chain(store)
    item = _filtered(store, key)
    assert item["n"] == 2 and item["off"] is False and item["blocking"] is False
    assert "거르기 꺼짐" not in item["label"]

    # 세 영역에서 놓친 걸림이 정산됐는데 넓힘(같은 트랜잭션의 다시 열기)은 돌지 않았다 — 정산 뒤 넓힘 전에 잡이 죽고 취소된 원장.
    # 살아 있는 검토 잡 없음 · 대기 셀 0 · 거르기 꺼짐 · 거른 셀 2.
    _risk_miss(store, key, b, STD1, "std")
    _risk_miss(store, key, b, MECH1, "mech")
    _risk_miss(store, key, b, MEM1, "mem")
    item = _filtered(store, key)
    assert item["n"] == 2 and item["off"] is True and item["blocking"] is True
    assert "거르기 꺼짐(넓힌 영역 3)" in item["label"] and "검토 잡을 하나 돌리면" in item["label"]

    factories.act_as_delegate(monkeypatch, rig.OWNER)
    guide = _call("risk_next_step", project_id=project_id)
    assert guide["where"] == "review"                      # '끝났다' 가 아니다 — 검토 없이 남은 셀이 있다
    assert any(s["tool"] == "risk_start_job" for s in guide["next"])
    assert any("거른 셀 2개가 검토 없이 남았다" in n for n in guide.get("notes") or ())

    # 아무 범위의 검토 잡 하나 — 잡 끝 정리(reopen_widened · via filter_off)가 남은 거른 셀을 그 잡에 묶어 본다.
    healer = rig.job(store, key, scope={"agents": [STD1]})
    rig.Rig(store, fake).finish(healer)
    assert rig.state(store, healer) == "completed"
    assert _filtered(store, key) is None
    for agent in (STD2, MEM2):
        cell = _cell(store, key, b, agent)
        assert (cell["state"], cell["route_forced"], cell["run_id"]) == ("reviewed", "widened", healer)
    guide = _call("risk_next_step", project_id=project_id)
    assert not any("검토 없이 남았다" in n for n in guide.get("notes") or ())


def test_정상_길은_넓힘이_같은_트랜잭션에서_다시_열어_거름_잔여가_없다(store, monkeypatch):
    key, _job, _fake, kinds = _run(store, fake_setup=_leave_filtered_cells(monkeypatch))
    b = kinds["boundary"]
    live = rig.job(store, key, scope={"agents": [STD1]})           # 넓히는 쪽은 늘 살아 있는 잡이다(_settle 의 run_id)
    _risk_miss(store, key, b, STD1, "std")
    _risk_miss(store, key, b, MECH1, "mech")
    _risk_miss(store, key, b, MEM1, "mem")
    out = review_cells.widen(store, key, "mem", run_id=live)
    assert out["off"] is True and out["reopened"] == 2
    assert review_cells.closure_cells(store, key)["filtered"]["n"] == 0
    assert _filtered(store, key) is None
