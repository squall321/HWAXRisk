# 잡 사슬(재설계 M3 S3-5) — 검토 잡이 마감 범위를 닫으면 쟁점 → 종합이 사람 손 없이 이어지고, 좁은 범위 뒤에는 판만 서며, 끊긴 사슬은 sweep 이 메우는지 본다
"""원장은 생산자 경로다 — 대상은 라우트(rig.target, flow cells), 검토는 가짜 검토 엔진의 루프(Rig), 쟁점 잡은 러너(claim_next_job →
run_panel)가 가짜 쟁점 패널 엔진으로, 종합 잡은 SynthWorker 가 가짜 요약 엔진으로 돈다. 다음 잡은 사슬 훅이 세운다(손으로 만들지
않는다). m3-synthesis S3-5 의 시험 ①~⑥ 이다. ⑦(패널 대상의 Tier B → C 자동 후속)은 tests/test_runner_panel.py 가 지금 그대로 본다.
"""
from __future__ import annotations

import json

import pytest

from app import chain, closure, config, issues, routes, runner, synth
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.fake_summary_engine import FakeSummaryEngine
from tests.synth.issue_panel_engine import IssuePanelEngine

OWNER = rig.OWNER
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_issue_panel_cap=2, risk_issue_panel_hard_cap=2)
    return risk_store


def _fake() -> FakeReviewEngine:
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {str(CARDS["K01"]["record_id"]): ("yes", "FAIL")}
    fake.mechs = {str(CARDS["K01"]["record_id"]): ("interface.clearance", "")}
    return fake


def _review(store, key: str, scope=None) -> str:
    job_id = rig.job(store, key, scope=scope)
    rig.Rig(store, _fake()).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)
    return job_id


def _jobs(store, key: str, mode: str) -> list[dict]:
    return [{**dict(r), "chain": json.loads(r["chain_json"] or "{}")} for r in store.query(
        "SELECT id, mode, state, error, params_json, chain_json, credential_email FROM rr_jobs WHERE target_key = ?"
        " AND mode = ? ORDER BY rowid", (key, mode))]


def _versions(store, key: str) -> list[tuple[int, str]]:
    return [(int(r["version_no"]), r["trigger"]) for r in store.query(
        "SELECT version_no, trigger FROM rr_reports WHERE target_key = ? ORDER BY version_no", (key,))]


def _run_issue_jobs(store, engine, *, limit: int = 20) -> None:
    for _ in range(limit):
        job = runner.claim_next_job(store, config.settings, engine=engine)
        if job is None:
            return
        runner.run_panel(store, config.settings, engine, job)


def _run_synth(store, engine) -> None:
    worker = synth.SynthWorker(store, config.settings, engine)
    for _ in range(300):
        if worker.tick()["step"] == "idle":
            return
    raise AssertionError("종합 잡이 300틱 안에 끝나지 않았다")


def test_a_cells_target_closes_at_c3_and_a_panel_target_keeps_the_box_knob(store, monkeypatch, tmp_path):
    """카드 대조 대상의 마감 레벨은 전원(C3 — D-34)이고 패널 대상은 박스 손잡이 그대로다. 방식을 바꾸면 마감 레벨이 따라가고 감사
    행에 앞뒤가 남는다."""
    cells = rig.target(store)
    assert store.query_one("SELECT close_level FROM rr_targets WHERE target_key = ?", (cells,))["close_level"] == "C3"
    diff = factories.make_diff_target(store, 40, open_target=False)
    panels = routes.create_target(routes.TargetBody(kind="diff", ref_id=diff.diff_id, consent=True, flow="panels",
                                                    agents=[dict(r) for r in rig.ROSTER]),
                                  ident=factories.ident(OWNER))["target_key"]
    assert store.query_one("SELECT close_level FROM rr_targets WHERE target_key = ?", (panels,))["close_level"] == "C2"
    routes.post_target_flow(panels, routes.FlowBody(to="cells", reason="카드 대조로 바꾼다"), ident=factories.ident(OWNER))
    assert store.query_one("SELECT close_level FROM rr_targets WHERE target_key = ?", (panels,))["close_level"] == "C3"
    audit = store.query_one("SELECT before_json, after_json FROM rr_audit WHERE subject_id = ? AND action = 'target.flow'",
                            (panels,))
    assert (json.loads(audit["before_json"]), json.loads(audit["after_json"])) == (
        {"flow": "panels", "close_level": "C2"}, {"flow": "cells", "close_level": "C3"})
    routes.post_target_flow(panels, routes.FlowBody(to="panels", reason="되돌린다"), ident=factories.ident(OWNER))
    assert store.query_one("SELECT close_level FROM rr_targets WHERE target_key = ?", (panels,))["close_level"] == "C2"


def test_a_narrow_review_makes_only_a_code_report_and_the_full_one_chains_issues_then_synthesis(store):
    """① 범위 셋의 검토 잡이 끝나면 병합은 하되 쟁점·종합 잡이 생기지 않고 코드 조립 판 v1(reviews_partial)이 서며 표기에 '열린 셀 N'
    이 있다.
    ② 이어 전원 검토 잡이 끝나면 쟁점 잡 → 종합 잡이 차례로 생기고 판이 v2(reviews_closed) · v3(issues_closed) · v4(synth_done)로
    오른다. 사슬 잡은 앞 잡의 요청자를 잇고 동의 출처가 chain 이며 chain_json 이 앞 잡·뿌리·지문을 단다."""
    key = rig.target(store)
    first = _review(store, key, scope={"agents": [r["key"] for r in rig.ROSTER[:3]]})
    assert _jobs(store, key, "issues") == [] and _jobs(store, key, "synth") == []
    assert _versions(store, key) == [(1, "reviews_partial")]
    # 좁은 범위여도 병합은 한다 — 카드 대조 finding 이 등록부에 섰다(검토 루프는 등록부를 쓰지 않는다, 사슬의 몫).
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_registry WHERE target_key = ?", (key,))["n"] > 0
    open_n = chain.scope_open(store, key)
    assert open_n > 0 and f"열린 셀 {open_n}" in closure.cached(store, key)["level_label"]
    assert issues.issue_rows(store, key) == []

    second = _review(store, key)
    assert chain.scope_open(store, key) == 0
    (issue_job,) = _jobs(store, key, "issues")
    assert issue_job["state"] == "queued" and _jobs(store, key, "synth") == []
    assert {k: issue_job["chain"][k] for k in ("root_job_id", "prev_job_id", "stage", "round", "scope_open", "reason")} == {
        "root_job_id": second, "prev_job_id": second, "stage": "issues", "round": 1, "scope_open": 0,
        "reason": "reviews_closed"}
    assert issue_job["chain"]["cells_hash"] == closure.closing_hash(store, key)
    params = json.loads(issue_job["params_json"])
    assert (params["requester"], params["consent_source"]) == (OWNER, "chain")
    assert _versions(store, key) == [(1, "reviews_partial"), (2, "reviews_closed")]
    assert first != second

    _run_issue_jobs(store, IssuePanelEngine(store, {"*": {"severity": "중대", "judgement": "FAIL"}}))
    assert _jobs(store, key, "issues")[0]["state"] == "completed"
    (synth_job,) = _jobs(store, key, "synth")
    assert (synth_job["state"], synth_job["chain"]["prev_job_id"], synth_job["chain"]["root_job_id"],
            synth_job["chain"]["reason"]) == ("queued", issue_job["id"], second, "issues_completed")
    assert _versions(store, key)[-1] == (3, "issues_closed")

    _run_synth(store, FakeSummaryEngine())
    assert _jobs(store, key, "synth")[0]["state"] == "completed"
    assert _versions(store, key) == [(1, "reviews_partial"), (2, "reviews_closed"), (3, "issues_closed"), (4, "synth_done")]
    fresh = closure.cached(store, key)["detail"]["fresh"]
    assert (fresh["issues"], fresh["report"]) == (True, True)
    assert chain.sweep(store)["made"] == []


def test_no_issue_to_run_goes_straight_to_synthesis(store, monkeypatch, tmp_path):
    """쟁점이 하나도 고르지 못하면(전원 OK) 검토 뒤 곧바로 종합 잡이다(reason no_issues)."""
    key = rig.target(store)
    job_id = rig.job(store, key)
    rig.Rig(store, FakeReviewEngine(rig.packs())).finish(job_id)
    assert [i for i in issues.issue_rows(store, key) if i["state"] == "queued"] == []
    assert _jobs(store, key, "issues") == []
    (synth_job,) = _jobs(store, key, "synth")
    assert (synth_job["chain"]["prev_job_id"], synth_job["chain"]["reason"]) == (job_id, "no_issues")


def test_a_crash_between_the_review_and_the_next_job_is_filled_by_one_sweep(store, monkeypatch):
    """③ 검토 잡이 completed 로 바뀐 직후 다음 잡을 만들기 전에 프로세스가 죽었다 — sweep 이 정확히 하나를 만들고, 두 번 돌려도
    하나다. 살아 있는 사슬 잡이 있는 동안 sweep 은 아무것도 하지 않는다."""
    key = rig.target(store)
    real = chain.create_stage_job

    def crash(*args, **kwargs):
        raise SystemError("프로세스가 여기서 죽었다(가짜)")

    monkeypatch.setattr(chain, "create_stage_job", crash)
    job_id = _review(store, key)
    assert _jobs(store, key, "issues") == [] and _jobs(store, key, "synth") == []
    monkeypatch.setattr(chain, "create_stage_job", real)
    made = chain.sweep(store)["made"]
    assert [(m["after"], m["stage"]) for m in made] == [(job_id, "issues")]
    assert chain.sweep(store)["made"] == []
    assert len(_jobs(store, key, "issues")) == 1


def test_a_missing_credential_still_makes_the_next_job_row_with_the_reason(store, monkeypatch):
    """④ 자격 해석기가 사슬 중간부터 None 을 돌려줘도 다음 잡 행은 queued 로 생기고 error 에 pat_unavailable 이 적힌다(사슬이
    자격 검사로 끊기지 않는다 — 집는 쪽이 건너뛴다)."""
    key = rig.target(store)
    monkeypatch.setattr(runner, "resolve_credential_with_note",
                        lambda *a, **k: (None, "koo@example.com 의 쓸 수 있는 포털 PAT 가 없다(가짜)"))
    _review(store, key)
    (issue_job,) = _jobs(store, key, "issues")
    assert issue_job["state"] == "queued" and issue_job["error"].startswith("pat_unavailable: ")
    assert issue_job["credential_email"] is None


def test_a_cancelled_issue_job_ends_the_chain(store):
    """⑤ 사람이 쟁점 잡을 취소하면 종합 잡이 생기지 않고 남은 쟁점은 untried_cap(chain_cancelled)이다. sweep 도 잇지 않는다."""
    key = rig.target(store)
    _review(store, key)
    (issue_job,) = _jobs(store, key, "issues")
    runner.cancel_job(store, issue_job["id"], by=OWNER)
    assert _jobs(store, key, "synth") == []
    assert {(i["state"], i["state_reason"]) for i in issues.issue_rows(store, key) if i["rank"] <= 2} == {
        ("untried_cap", "chain_cancelled")}
    assert chain.sweep(store)["made"] == [] and _jobs(store, key, "synth") == []


def test_three_engine_errors_fail_the_issue_job_and_the_chain_still_reaches_synthesis(store):
    """⑥ 쟁점 패널 셋이 잇달아 엔진 오류면 쟁점 잡이 failed 이고 남은 쟁점이 untried_cap(engine_fail)이며 종합 잡이 생긴다
    (P-08 ② — 보고서에 미토의로 남는다)."""
    key = rig.target(store)
    _review(store, key)
    _run_issue_jobs(store, IssuePanelEngine(store, {"*": runner.EngineError("엔진이 터졌다")}))
    (issue_job,) = _jobs(store, key, "issues")
    assert (issue_job["state"], issue_job["error"]) == ("failed", "engine_fail_streak")
    (synth_job,) = _jobs(store, key, "synth")
    assert (synth_job["chain"]["prev_job_id"], synth_job["chain"]["reason"]) == (issue_job["id"], "issues_failed")
    assert _versions(store, key)[-1][1] == "issues_closed"
