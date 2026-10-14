# 완결 판정 결정표(재설계 M3 S3-12 C11) — cells 대상의 레벨·표기가 원장 상태마다 표대로인지 생산자 경로(검토 루프·쟁점·종합)로 본다
"""원장은 손 INSERT 없이 만든다 — 대상은 라우트, 셀·판정·보고서는 가짜 검토 엔진의 M2 루프, 쟁점은 S3-6 선정·S3-7 쟁점 패널(가짜
쟁점 패널 엔진), 보고서 판은 종합 잡(가짜 요약 엔진), 확인은 closure.ack_residual. 마감 레벨은 대상을 열 때의 손잡이
(HWAXRISK_DEFAULT_CLOSE_LEVEL)로 정한다.

이 판의 행은 m3-synthesis S3-12 C11 의 ②③④⑤⑥⑦ 이다. 입력 결손 셀(⑧⑨⑩⑫)·셀 다시 열기(⑪⑬)는 셀 꾸러미(C3-3 · C3-4)가
`m3` 에 합쳐진 뒤 그 상태 전이 함수로 더한다. ⑭(거른 셀 표본)·C-a(단조)·C-e(옛 타깃)는 tests/test_closure.py 에 있다.
"""
from __future__ import annotations

import pytest

from app import closure, config, issues, registry, runner, synth, units
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.fake_summary_engine import FakeSummaryEngine
from tests.synth.issue_panel_engine import IssuePanelEngine

OWNER = rig.OWNER
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}
TAIL = "2차 영향 미실행(넘김 0건 표만) · 결손 사냥 미실행"


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_issue_panel_cap=48, risk_issue_panel_hard_cap=48)
    return risk_store


def _target(store, monkeypatch, tmp_path, close: str) -> str:
    rig.configure(monkeypatch, store, tmp_path, risk_issue_panel_cap=48, risk_issue_panel_hard_cap=48,
                  risk_default_close_level=close)
    return rig.target(store)


def _review(store, key: str, scope=None) -> None:
    job_id = rig.job(store, key, scope=scope)
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {str(CARDS["K01"]["record_id"]): ("yes", "FAIL")}
    fake.mechs = {str(CARDS["K01"]["record_id"]): ("interface.clearance", "")}
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)
    registry.merge(store, key)


def _issues(store, key: str) -> None:
    issues.select_issues(store, key, selected_round=1, cells_hash=closure.closing_hash(store, key))
    issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    engine = IssuePanelEngine(store)
    while (job := runner.claim_next_job(store, config.settings, engine=engine)) is not None:
        if runner.run_panel(store, config.settings, engine, job)["status"] == "no_panel":
            break


def _synth(store, key: str) -> None:
    synth.create_synth_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    worker = synth.SynthWorker(store, config.settings, FakeSummaryEngine())
    for _ in range(200):
        if worker.tick()["step"] == "completed":
            break


def _ack_all(store, key: str) -> dict:
    result = closure.refresh(store, key)
    for item in [q for q in result["qualifiers"] if q["blocking"] and not q["acked"]]:
        closure.ack_residual(store, key, item["item"], reason="결정표 — 이 잔여는 넘긴다", by=OWNER,
                             basis_hash=item["basis_hash"])
    return closure.refresh(store, key)


def _reps(store, key: str) -> list[str]:
    from app import planner

    order = planner.review_order(store, key)
    best: dict[str, dict] = {}
    for row in order:
        if row["domain"] not in best or row["rank_in_domain"] < best[row["domain"]]["rank_in_domain"]:
            best[row["domain"]] = row
    return [r["agent_key"] for r in best.values()]


def test_row2_an_incomplete_grid_is_c0(store, monkeypatch, tmp_path):
    """② 격자 결손(검토 잡 전 — 셀 0 · 기대 로스터 × 단위) → C0, 표기에 '격자 결손 N셀'."""
    key = _target(store, monkeypatch, tmp_path, "C3")
    result = closure.close_level_cells(store, key, persist=False)
    expected = len(rig.ROSTER) * len(units.load_units(store, key))
    assert (result["level"], result["c1"]) == ("C0", False)
    assert result["level_label"].startswith(f"C0(격자 결손 {expected}셀") and result["level_label"].endswith(f"{TAIL})")


def test_row3_open_representative_cells_are_c0_and_row4_closed_ones_are_c1(store, monkeypatch, tmp_path):
    """③ 대표(영역 순위 1) 셀이 열려 있으면 C0 · '열린 셀 N'. ④ 대표 셀이 다 닫히고 나머지가 열려 있으면 C1 · '열린 셀 N'."""
    key = _target(store, monkeypatch, tmp_path, "C3")
    reps = _reps(store, key)
    others = [r["key"] for r in rig.ROSTER if r["key"] not in reps]
    _review(store, key, scope={"agents": others[:1]})
    third = closure.close_level_cells(store, key, persist=False)
    assert third["level"] == "C0" and "열린 셀" in third["level_label"]
    _review(store, key, scope={"agents": reps})
    fourth = closure.close_level_cells(store, key, persist=False)
    open_cells = fourth["unseated_n"]
    assert (fourth["level"], fourth["c1"], fourth["c2"]) == ("C1", True, False) and open_cells > 0
    assert f"열린 셀 {open_cells}" in fourth["level_label"]


def test_row5_tier_b_depth_fresh_issues_and_no_open_p1_are_c2(store, monkeypatch, tmp_path):
    """⑤ 격자 전부 닫힘·깊이·쟁점이 지금 셀 지문으로 돌았고 P1 이 다 끝났다 → C2. 마감 레벨 C3 대상이라 보고서 판 전에는
    '후속 낡음(종합 전)' 이 붙는다(맨 C2 가 아니다)."""
    key = _target(store, monkeypatch, tmp_path, "C3")
    _review(store, key)
    assert closure.close_level_cells(store, key, persist=False)["level"] == "C1"
    _issues(store, key)
    result = closure.refresh(store, key)
    assert (result["level"], result["c2"], result["c3"]) == ("C2", True, False)
    assert result["level_label"].startswith("C2(") and "후속 낡음(종합 전)" in result["level_label"]


def test_row6_a_c2_target_waits_for_its_blocking_residuals_and_closes_after_the_acks(store, monkeypatch, tmp_path):
    """⑥ 마감 레벨 C2 대상 — 막음 잔여가 남으면 'C2 · 마감 대기(…)', 전부 확인하면 C2(closed)(…) 이고 저장 레벨이 오른다."""
    key = _target(store, monkeypatch, tmp_path, "C2")
    _review(store, key)
    _issues(store, key)
    waiting = closure.refresh(store, key)
    assert any(q["blocking"] for q in waiting["qualifiers"])
    assert (waiting["level"], waiting["level_label"][:len("C2 · 마감 대기(")]) == ("C2", "C2 · 마감 대기(")
    closed = _ack_all(store, key)
    assert closed["level"] == "C2(closed)" and closed["level_label"].startswith("C2(closed)(")
    assert store.query_one("SELECT level FROM rr_targets WHERE target_key = ?", (key,))["level"] == "C2(closed)"


def test_row7_everything_closed_with_acked_residuals_and_a_fresh_report_is_c3_never_bare(store, monkeypatch, tmp_path):
    """⑦ 전원 종결 · 쟁점 끝 · 종합 보고서 판이 지금 지문으로 섰다 · 막음 잔여는 'C2 · C3 대기(…)' 로 기다리다 전부 확인하면 저장 C3,
    표기는 `C3(… · 2차 영향 미실행 · 결손 사냥 미실행)` — 맨 C3 는 M3 에서 나오지 않는다."""
    key = _target(store, monkeypatch, tmp_path, "C3")
    _review(store, key)
    _issues(store, key)
    _synth(store, key)
    waiting = closure.refresh(store, key)
    assert waiting["detail"]["fresh"] == {**waiting["detail"]["fresh"], "issues": True, "report": True}
    if any(q["blocking"] and not q["acked"] for q in waiting["qualifiers"]):
        assert waiting["level_label"].startswith("C2 · C3 대기(")
    done = _ack_all(store, key)
    assert (done["level"], done["c3"]) == ("C3", True)
    assert done["level_label"].startswith("C3(") and done["level_label"].endswith(f"{TAIL})")
    assert done["level_label"] != "C3"
