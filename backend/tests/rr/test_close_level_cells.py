# 완결 판정 결정표(재설계 M3 S3-12 C11) — cells 대상의 레벨·표기가 원장 상태마다 표대로인지 생산자 경로(검토 루프·잡 사슬·셀 처분)로 본다
"""원장은 손 INSERT 없이 만든다 — 대상은 라우트, 셀·판정·보고서는 가짜 검토 엔진의 검토 루프, 쟁점 → 종합은 검토 잡 끝의 잡 사슬
(S3-5)이 세운 잡을 러너(가짜 쟁점 패널 엔진)와 종합 워커(가짜 요약 엔진)가 돈다. 확인은 `closure.ack_residual` 이다. cells 대상의
마감 레벨은 C3(D-34)이고, C2 마감은 M2 때 연 cells 대상(그때는 패널 손잡이 C2 를 얼렸다)으로 만든다 — 마감 레벨을 고르는 길이 없어
그 한 칸만 손으로 적는다.

행은 m3-synthesis S3-12 C11 의 ②~⑦ 이다. ①(단위 0)은 단위가 안 서면 대상이 panels 로 열려 cells 판정에 오지 않는다(W2-05 —
tests/test_target_flow.py). 입력 결손·다시 연 셀의 행(⑧~⑬)은 셀 처분으로 상태를 만드는 다음 걸음에서 더한다. ⑭(거른 셀 표본)·
C-a(단조)·C-e(옛 타깃)는 tests/test_closure.py 에 있다.
"""
from __future__ import annotations

import pytest

from app import closure, config, planner, runner, synth, units
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


def _fake(roster=rig.ROSTER, *, no_input: dict | None = None) -> FakeReviewEngine:
    fake = FakeReviewEngine(rig.packs(roster))
    fake.verdicts = {str(CARDS["K01"]["record_id"]): ("yes", "FAIL")}
    fake.mechs = {str(CARDS["K01"]["record_id"]): ("interface.clearance", "")}
    fake.noinput_q1 = dict(no_input or {})
    return fake


def _review(store, key: str, scope=None, *, fake: FakeReviewEngine | None = None) -> str:
    job_id = rig.job(store, key, scope=scope)
    rig.Rig(store, fake or _fake()).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)
    return job_id


def _issues(store) -> None:
    """사슬이 세운 쟁점 잡을 러너가 끝까지(가짜 쟁점 패널 엔진) — 끝나면 사슬이 종합 잡을 세운다."""
    engine = IssuePanelEngine(store)
    while (job := runner.claim_next_job(store, config.settings, engine=engine)) is not None:
        runner.run_panel(store, config.settings, engine, job)


def _synth(store) -> None:
    worker = synth.SynthWorker(store, config.settings, FakeSummaryEngine())
    for _ in range(300):
        if worker.tick()["step"] == "idle":
            return
    raise AssertionError("종합 잡이 300틱 안에 끝나지 않았다")


def _ack_all(store, key: str) -> dict:
    result = closure.refresh(store, key)
    for item in [q for q in result["qualifiers"] if q["blocking"] and not q["acked"]]:
        closure.ack_residual(store, key, item["item"], reason="결정표 — 이 잔여는 넘긴다", by=OWNER,
                             basis_hash=item["basis_hash"])
    return closure.refresh(store, key)


def _reps(store, key: str) -> list[str]:
    best: dict[str, dict] = {}
    for row in planner.review_order(store, key):
        if row["domain"] not in best or row["rank_in_domain"] < best[row["domain"]]["rank_in_domain"]:
            best[row["domain"]] = row
    return [r["agent_key"] for r in best.values()]


# ---------------------------------------------------------------- ② ~ ⑦
def test_row2_an_incomplete_grid_is_c0(store):
    """② 격자 결손(검토 잡 전 — 셀 0 · 기대 로스터 × 단위) → C0, 표기에 '격자 결손 N셀'."""
    key = rig.target(store)
    result = closure.close_level_cells(store, key, persist=False)
    expected = len(rig.ROSTER) * len(units.load_units(store, key))
    assert (result["level"], result["close_level"], result["c1"]) == ("C0", "C3", False)
    assert result["level_label"].startswith(f"C0(격자 결손 {expected}셀") and result["level_label"].endswith(f"{TAIL})")


def test_row3_open_representative_cells_are_c0_and_row4_closed_ones_are_c1(store):
    """③ 대표(영역 순위 1) 셀이 열려 있으면 C0 · '열린 셀 N'. ④ 대표 셀이 다 닫히고 나머지가 열려 있으면 C1 · '열린 셀 N'. 좁은
    범위라 사슬은 판(reviews_partial)만 세운다."""
    key = rig.target(store)
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
    assert {r["mode"] for r in store.query("SELECT mode FROM rr_jobs WHERE target_key = ?", (key,))} == {"reviews"}


def test_row5_tier_b_depth_fresh_issues_and_no_open_p1_are_c2(store):
    """⑤ 격자 전부 닫힘 → 사슬이 쟁점을 지금 셀 지문으로 고르고 쟁점 잡을 세운다. P1 이 도는 동안은 C1, 다 끝나면 C2. 마감 레벨 C3
    대상이라 종합 판 전에는 '후속 낡음(종합 전)' 이 붙는다(맨 C2 가 아니다)."""
    key = rig.target(store)
    _review(store, key)
    running = closure.cached(store, key)
    assert running["level"] == "C1" and running["counts"]["issues"]["p1"]["open"] >= 1
    _issues(store)
    result = closure.refresh(store, key)
    assert (result["level"], result["c2"], result["c3"]) == ("C2", True, False)
    assert result["level_label"].startswith("C2(") and "후속 낡음(종합 전)" in result["level_label"]


def test_row6_a_c2_target_waits_for_its_blocking_residuals_and_closes_after_the_acks(store):
    """⑥ 마감 레벨 C2 대상(M2 때 연 cells 대상) — 막음 잔여가 남으면 'C2 · 마감 대기(…)', 전부 확인하면 C2(closed)(…) 이고 저장
    레벨이 오른다."""
    key = rig.target(store)
    store.execute("UPDATE rr_targets SET close_level = 'C2' WHERE target_key = ?", (key,))   # M2 때 얼린 패널 손잡이 값
    _review(store, key)
    _issues(store)
    waiting = closure.refresh(store, key)
    assert any(q["blocking"] for q in waiting["qualifiers"])
    assert (waiting["level"], waiting["level_label"][:len("C2 · 마감 대기(")]) == ("C2", "C2 · 마감 대기(")
    closed = _ack_all(store, key)
    assert closed["level"] == "C2(closed)" and closed["level_label"].startswith("C2(closed)(")
    assert store.query_one("SELECT level FROM rr_targets WHERE target_key = ?", (key,))["level"] == "C2(closed)"


def test_row7_everything_closed_with_acked_residuals_and_a_fresh_report_is_c3_never_bare(store):
    """⑦ 전원 종결 · 쟁점 끝 · 종합 판이 지금 지문으로 섰다(사슬이 사람 손 없이) · 막음 잔여는 'C2 · C3 대기(…)' 로 기다리다 전부
    확인하면 저장 C3, 표기는 `C3(… · 2차 영향 미실행 · 결손 사냥 미실행)` — 맨 C3 는 M3 에서 나오지 않는다."""
    key = rig.target(store)
    _review(store, key)
    _issues(store)
    _synth(store)
    waiting = closure.refresh(store, key)
    assert waiting["detail"]["fresh"] == {**waiting["detail"]["fresh"], "issues": True, "report": True}
    assert any(q["blocking"] and not q["acked"] for q in waiting["qualifiers"])
    assert waiting["level_label"].startswith("C2 · C3 대기(")
    done = _ack_all(store, key)
    assert (done["level"], done["c3"]) == ("C3", True)
    assert done["level_label"].startswith("C3(") and done["level_label"].endswith(f"{TAIL})")
    assert done["level_label"] != "C3"
