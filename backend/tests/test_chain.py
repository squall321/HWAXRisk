# 잡 사슬(재설계 M3 S3-5) — 검토 잡이 마감 범위를 닫으면 쟁점 → 종합이 사람 손 없이 이어지고, 좁은 범위 뒤에는 판만 서며, 끊긴 사슬은 sweep 이 메우는지 본다
"""원장은 생산자 경로다 — 대상은 라우트(rig.target, flow cells), 검토는 가짜 검토 엔진의 루프(Rig), 쟁점 잡은 러너(claim_next_job →
run_panel)가 가짜 쟁점 패널 엔진으로, 종합 잡은 SynthWorker 가 가짜 요약 엔진으로 돈다. 다음 잡은 사슬 훅이 세운다(손으로 만들지
않는다). m3-synthesis S3-5 의 시험 ①~⑥ 이다. ⑦(패널 대상의 Tier B → C 자동 후속)은 tests/test_runner_panel.py 가 지금 그대로 본다.
"""
from __future__ import annotations

import json

import pytest

from app import chain, closure, config, entry, issues, routes, runner, synth
from app.common import now_epoch
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
    """검토 잡 하나를 끝까지. 시험대 시계를 지난 달에서 시작한다 — 시험대는 틱마다 시계를 61초씩 밀어 실제 시각보다 앞서 가는데,
    sweep 은 '마지막으로 끝난 잡' 을 끝난 시각으로 고르므로 검토 잡이 뒤에 실제 시각으로 끝난 쟁점·종합 잡보다 늦게 끝난 것처럼 보인다."""
    job_id = rig.job(store, key, scope=scope)
    rig.Rig(store, _fake(), clock=rig.Clock(now_epoch() - 30 * 86400)).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)
    return job_id


def _one(rows: list, what: str):
    """하나뿐이어야 하는 행 — 아니면 단언 실패(풀어 쓰기의 ValueError 가 아니라)."""
    assert len(rows) == 1, (what, rows)
    return rows[0]


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
    issue_job = _one(_jobs(store, key, "issues"), "issues 잡")
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
    synth_job = _one(_jobs(store, key, "synth"), "synth 잡")
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
    synth_job = _one(_jobs(store, key, "synth"), "synth 잡")
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
    # 훅이 한 번 더 불려도(겹친 sweep) 앞 잡 하나에 다음 잡은 하나 — 살아 있는 쟁점 잡이 있어 세우지 않고, 직접 세우려 해도 그 잡이다.
    again = chain.on_reviews_closed(store, rig.job_row(store, job_id))
    assert (again["stage"], again["reason"], again["job_id"]) == (None, "issues_live", made[0]["job_id"])
    twice = chain.create_stage_job(store, key, "issues", prev=rig.job_row(store, job_id), reason="sweep", round_no=1)
    assert (twice["created"], twice["job_id"]) == (False, made[0]["job_id"])
    assert len(_jobs(store, key, "issues")) == 1


def test_a_missing_credential_still_makes_the_next_job_row_with_the_reason(store, monkeypatch):
    """④ 자격 해석기가 사슬 중간부터 None 을 돌려줘도 다음 잡 행은 queued 로 생기고 error 에 pat_unavailable 이 적힌다(사슬이
    자격 검사로 끊기지 않는다 — 집는 쪽이 건너뛴다)."""
    key = rig.target(store)
    monkeypatch.setattr(runner, "resolve_credential_with_note",
                        lambda *a, **k: (None, "koo@example.com 의 쓸 수 있는 포털 PAT 가 없다(가짜)"))
    _review(store, key)
    issue_job = _one(_jobs(store, key, "issues"), "issues 잡")
    assert issue_job["state"] == "queued" and issue_job["error"].startswith("pat_unavailable: ")
    assert issue_job["credential_email"] is None


def test_a_cancelled_issue_job_ends_the_chain(store):
    """⑤ 사람이 쟁점 잡을 취소하면 종합 잡이 생기지 않고 남은 쟁점은 untried_cap(chain_cancelled)이다. sweep 도 잇지 않는다."""
    key = rig.target(store)
    _review(store, key)
    issue_job = _one(_jobs(store, key, "issues"), "issues 잡")
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
    issue_job = _one(_jobs(store, key, "issues"), "issues 잡")
    assert (issue_job["state"], issue_job["error"]) == ("failed", "engine_fail_streak")
    synth_job = _one(_jobs(store, key, "synth"), "synth 잡")
    assert (synth_job["chain"]["prev_job_id"], synth_job["chain"]["reason"]) == (issue_job["id"], "issues_failed")
    assert _versions(store, key)[-1][1] == "issues_closed"


@pytest.mark.parametrize("one_upheld", [False, True])
def test_five_rejected_issue_panels_leave_a_low_yield_note_without_stopping_the_job(store, monkeypatch, tmp_path, one_upheld):
    """최근 다섯 쟁점 패널이 전부 기각이면 쟁점 잡 진행판에 advice='issue_yield_low' 가 선다 — 잡은 멈추지 않는다(멈춤은 사람이
    정한다, 3.12). 다섯 가운데 하나라도 유지면 알림이 없다."""
    rig.configure(monkeypatch, store, tmp_path, risk_issue_panel_cap=48, risk_issue_panel_hard_cap=48)
    key = rig.target(store)
    _review(store, key)
    queued = [i for i in issues.issue_rows(store, key) if i["state"] == "queued"]
    assert len(queued) >= issues.YIELD_WINDOW
    script: dict = {"*": {"status": "rejected_in_panel"}}
    if one_upheld:
        script[queued[-1]["issue_id"]] = {"severity": "중대", "judgement": "FAIL"}
    _run_issue_jobs(store, IssuePanelEngine(store, script))
    issue_job = _one(_jobs(store, key, "issues"), "issues 잡")
    row = store.query_one("SELECT progress_json FROM rr_jobs WHERE id = ?", (issue_job["id"],))
    progress = json.loads(row["progress_json"] or "{}")
    assert issue_job["state"] == "completed"
    assert progress.get("advice") == (None if one_upheld else "issue_yield_low")
    assert issues.yield_advice(store, key) == (None if one_upheld else "issue_yield_low")


class _ProgressEngine(IssuePanelEngine):
    """진행 콜백을 받는 쟁점 패널 엔진 — 첫 프레임을 적게 한 뒤 그 순간의 잡 진행판을 기록한다(패널이 도는 동안 보이는 것)."""

    def __init__(self, store, script) -> None:
        super().__init__(store, script)
        self.seen: list[dict] = []

    def run(self, delib_opts, *, owner_sub=None, on_progress=None):
        on_progress({"last_step": "좌석 발언"}, force=True)
        row = self.store.query_one("SELECT progress_json FROM rr_jobs WHERE mode = 'issues' AND state = 'running'")
        self.seen.append(json.loads(row["progress_json"] or "{}"))
        return super().run(delib_opts, owner_sub=owner_sub)


def test_the_low_yield_note_stays_on_the_board_while_the_next_issue_panel_runs(store, monkeypatch, tmp_path):
    """알림은 다음 쟁점 패널이 도는 동안에도 진행판에 남는다 — 패널의 진행 줄이 진행판을 새로 쓸 때 머리에 실린다. 결정문을 못 읽은
    패널도 불명이라 다섯이 차면 여섯째부터 보인다."""
    rig.configure(monkeypatch, store, tmp_path, risk_issue_panel_cap=48, risk_issue_panel_hard_cap=48)
    key = rig.target(store)
    _review(store, key)
    engine = _ProgressEngine(store, {"*": "unparseable"})
    _run_issue_jobs(store, engine)
    assert len(engine.seen) > issues.YIELD_WINDOW
    assert [s.get("advice") for s in engine.seen] == [None] * issues.YIELD_WINDOW + ["issue_yield_low"] * (
        len(engine.seen) - issues.YIELD_WINDOW)


# ---------------------------------------------------------------- 길잡이(risk_next_step — 3.11)
def test_the_guide_follows_the_chain_to_the_report_and_names_the_residuals_left_for_a_person(store):
    """쟁점 잡이 서면 where='issues' · risk_get_issues 를 지켜보고, 사람이 멈추면 막힘 chain_paused 와 재개가 맨 앞이다. 사슬이
    끝나면 where='done' · risk_get_report(part summary) 걸음, facts 의 완결 표기·사슬 단계·보고서 머리, 막음 잔여는 '웹 화면에서
    소유자·관리자가 확인한다' 막힘이다(Claude 경로의 확인은 없다)."""
    from tests.test_review_mcp import _delegate, _project_with_source

    key = rig.target(store)
    project_id = _project_with_source(store, key)
    _review(store, key)
    issue_job = _one(_jobs(store, key, "issues"), "issues 잡")
    waiting = entry.next_step(_delegate(), project_id=project_id)
    assert waiting["where"] == "issues" and waiting["next"][0]["tool"] == "risk_get_issues"
    assert waiting["facts"]["stage"]["job_id"] == issue_job["id"] and waiting["facts"]["level_label"].startswith("C1(")
    assert waiting["blocked"] == []
    runner.pause_job(store, issue_job["id"], by=OWNER)
    paused = entry.next_step(_delegate(), project_id=project_id)
    assert [b["code"] for b in paused["blocked"]] == ["chain_paused"] and paused["where"] == "issues"
    assert paused["next"][0] == {**paused["next"][0], "tool": "risk_job_action",
                                 "args": {"job_id": issue_job["id"], "action": "resume"}}
    runner.resume_job(store, issue_job["id"], by=OWNER)
    _run_issue_jobs(store, IssuePanelEngine(store))
    _run_synth(store, FakeSummaryEngine({"xd": "over_budget"}))
    done = entry.next_step(_delegate(), project_id=project_id)
    assert done["where"] == "done" and done["facts"]["report"]["trigger"] == "synth_done"
    report = _one([s for s in done["next"] if s["tool"] == "risk_get_report"], "걸음 risk_get_report")
    assert report["args"] == {"target_key": key, "part": "summary"} and report["write"] is False
    residual = _one([b for b in done["blocked"] if b["code"] == "residual_unacked"], "막힘 residual_unacked")
    pending = [q["item"] for q in closure.cached(store, key)["qualifiers"] if q["blocking"] and not q["acked"]]
    assert residual["items"] == pending and pending and "/closure" in residual["fix"]
    assert any("서술 없이 표만 선 요약 1건 — xd ctx_too_small" in n for n in done["notes"])


def test_the_guide_says_the_issue_job_waits_for_a_pat(store, monkeypatch):
    """자격이 없어 사슬 잡이 집히지 않으면 막힘 pat_unavailable 이 그 잡을 가리킨다."""
    from tests.test_review_mcp import _delegate, _project_with_source

    key = rig.target(store)
    project_id = _project_with_source(store, key)
    monkeypatch.setattr(runner, "resolve_credential_with_note", lambda *a, **k: (None, "PAT 없음(가짜)"))
    _review(store, key)
    issue_job = _one(_jobs(store, key, "issues"), "issues 잡")
    out = entry.next_step(_delegate(), project_id=project_id)
    pat = _one([b for b in out["blocked"] if b["code"] == "pat_unavailable"], "막힘 pat_unavailable")
    assert pat["job_id"] == issue_job["id"] and out["where"] == "issues"


def test_the_guide_shows_a_credential_hold_on_the_issue_job_with_how_to_register(store):
    """review1 M1 — 쟁점 잡이 자격 실패로 보류 credential 에 멈추면 길잡이는 막힘 chain_paused(재개가 맨 앞)와 pat_unavailable(포털에서
    PAT 를 등록하는 법)을 함께 준다. 사슬은 그동안 종합으로 넘어가지 않는다."""
    from tests.test_review_mcp import _delegate, _project_with_source

    key = rig.target(store)
    project_id = _project_with_source(store, key)
    _review(store, key)
    issue_job = _one(_jobs(store, key, "issues"), "issues 잡")
    engine = IssuePanelEngine(store, {"*": runner.PatUnavailable("koo@example.com 의 PAT 가 만료됐다(가짜)")})
    runner.run_panel(store, config.settings, engine, runner.claim_next_job(store, config.settings, engine=engine))
    out = entry.next_step(_delegate(), project_id=project_id)
    codes = [b["code"] for b in out["blocked"]]
    assert "chain_paused" in codes and "pat_unavailable" in codes and out["where"] == "issues"
    pat = _one([b for b in out["blocked"] if b["code"] == "pat_unavailable"], "막힘 pat_unavailable")
    assert pat["job_id"] == issue_job["id"] and "PAT" in pat["fix"]
    assert out["next"][0] == {**out["next"][0], "tool": "risk_job_action", "args": {"job_id": issue_job["id"], "action": "resume"}}
    assert chain.sweep(store)["made"] == [] and _jobs(store, key, "synth") == []


def test_a_c2_target_chains_once_its_tier_b_scope_closes_even_with_other_cells_open(store):
    """마감 레벨 C2 대상(M2 때 연 cells 대상)의 마감 범위는 Tier B 범위(A·B)다 — 그 전문가만 돈 검토 잡이 끝나면 나머지 셀이 열려
    있어도 쟁점을 고르고 쟁점 잡을 세운다. 같은 범위를 C3 대상에서 돌면 판만 선다."""
    from app import planner

    key = rig.target(store)
    store.execute("UPDATE rr_targets SET close_level = 'C2' WHERE target_key = ?", (key,))   # M2 때 얼린 패널 손잡이 값
    tier_b = [r["agent_key"] for r in planner.review_order(store, key) if r["tier"] in ("A", "B")]
    assert 0 < len(tier_b) < len(rig.ROSTER)
    _review(store, key, scope={"agents": tier_b})
    assert chain.scope_open(store, key) == 0
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_review_cells WHERE target_key = ? AND state = 'pending'",
                           (key,))["n"] > 0
    assert len(_jobs(store, key, "issues") + _jobs(store, key, "synth")) == 1
    other = rig.target(store, seed=7)
    _review(store, other, scope={"agents": tier_b})
    assert chain.scope_open(store, other) > 0 and _jobs(store, other, "issues") == _jobs(store, other, "synth") == []


def test_a_review_that_closes_while_a_stage_waits_leaves_the_next_step_to_that_stage(store, monkeypatch, tmp_path):
    """살아 있는 단계가 있으면 사슬은 같은 일을 또 세우지 않는다 — 쟁점 잡이 줄에 있으면(고른 쟁점을 사람이 다 넘겨 다시 골라도 대기
    쟁점이 없다) 새 쟁점 잡도 종합 잡도 없고(그 잡이 끝나면 종합을 잇는다), 종합 잡이 아직 집히지 않았으면 새 종합 잡이 없다. 끝내
    종합 잡은 하나다."""
    rig.configure(monkeypatch, store, tmp_path, risk_issue_panel_cap=48, risk_issue_panel_hard_cap=48)   # 고른 쟁점이 다 대기다
    key = rig.target(store)
    _review(store, key)
    issue_job = _one(_jobs(store, key, "issues"), "issues 잡")
    for issue in [i for i in issues.issue_rows(store, key) if i["state"] == "queued"]:
        routes.put_issue(issue["issue_id"], routes.IssueActionBody(action="skip", reason="이번에는 넘긴다"),
                         ident=factories.ident(OWNER))
    retry = store.query_one("SELECT unit_id, agent_key, state FROM rr_review_cells WHERE target_key = ? AND agent_key = ?"
                            " AND state = 'reviewed' LIMIT 1", (key, "xd-syn-1"))
    from app import review_runner

    made = review_runner.dispose_cells(store, key, action="retry", rows=[dict(retry)], decided_by=OWNER, owner_sub=OWNER,
                                       note="다시 본다", force=True, start=True, consent=True, consent_source="web")
    rig.Rig(store, _fake()).finish(made["job"]["job_id"])
    assert [j["id"] for j in _jobs(store, key, "issues")] == [issue_job["id"]] and _jobs(store, key, "synth") == []
    # 줄에 선 쟁점 잡이 이번 고르기의 지문을 받았다 — 쟁점을 다 그대로 둔 다시 고르기라도 쟁점 단계가 지금 지문으로 신선하다.
    assert [i["state"] for i in issues.issue_rows(store, key) if i["state"] in ("queued", "untried_cap")] == []
    rearmed = _jobs(store, key, "issues")[0]["chain"]
    assert (rearmed.get("rearmed_by"), rearmed.get("cells_hash")) == (made["job"]["job_id"], closure.closing_hash(store, key))
    assert closure.refresh(store, key)["detail"]["fresh"]["issues"] is True
    _run_issue_jobs(store, IssuePanelEngine(store))
    synth_job = _one(_jobs(store, key, "synth"), "synth 잡")
    assert synth_job["chain"]["prev_job_id"] == issue_job["id"]
    again = review_runner.dispose_cells(store, key, action="retry", rows=[dict(retry)], decided_by=OWNER,
                                        owner_sub=OWNER, note="한 번 더", force=True, start=True, consent=True,
                                        consent_source="web")
    rig.Rig(store, _fake()).finish(again["job"]["job_id"])
    assert [j["id"] for j in _jobs(store, key, "synth")] == [synth_job["id"]]
    assert _jobs(store, key, "synth")[0]["chain"].get("rearmed_by") == again["job"]["job_id"]


def test_an_issue_job_that_ends_while_a_synthesis_waits_rearms_that_synthesis_instead_of_queuing_another(store):
    """쟁점 잡이 끝날 때 아직 집히지 않은 종합 잡(사람이 다시 낸 보고서)이 있으면 새 종합 잡을 세우지 않고 그 잡이 지금 원장(쟁점
    결과가 든 등록부 지문)으로 돈다는 표지를 단다."""
    key = rig.target(store)
    _review(store, key)
    issue_job = _one(_jobs(store, key, "issues"), "issues 잡")
    waiting = routes.post_report(key, routes.ReportBody(refresh_summaries=True), ident=factories.ident(OWNER))["job_id"]
    _run_issue_jobs(store, IssuePanelEngine(store, {"*": {"severity": "치명", "judgement": "FAIL"}}))
    synth_job = _one(_jobs(store, key, "synth"), "synth 잡")
    assert synth_job["id"] == waiting
    assert (synth_job["chain"].get("rearmed_by"), synth_job["chain"].get("registry_hash")) == (
        issue_job["id"], synth.registry_hash(store, key))


# ---------------------------------------------------------------- 반대 검토 1차(review1) M8
def test_the_first_sweep_after_the_v5_upgrade_does_not_chain_m2_era_review_jobs(tmp_path, monkeypatch):
    """M8(결정) — 사슬은 M3 코드가 세운 검토 잡(만들 때 사슬 표지를 단 잡)에서만 시작한다. v4(M2 코드)가 끝낸 검토 잡이 걸린 원장을
    v5 로 올린 뒤 첫 sweep 은 아무 잡도 · 판도 · 쟁점도 세우지 않는다 — 사람이 시작하지 않은 쟁점 패널·요약이 돌지 않는다."""
    from tests.rr import v4_build
    from tests.rr.test_v4_upgrade import _thaw
    from app.risk_store import RiskStore

    store = RiskStore(_thaw(v4_build.V4_DIR / v4_build.DB_GZ, tmp_path))
    store.open()
    store.migrate()
    rig.configure(monkeypatch, store, tmp_path)
    reviewed = json.loads((v4_build.V4_DIR / "manifest.json").read_text(encoding="utf-8"))["targets"]["reviewed"]
    assert rig.state(store, reviewed["job_id"]) == "completed"
    out = chain.sweep(store)
    assert out["made"] == []
    for table in ("rr_issues", "rr_reports", "rr_summaries"):
        assert store.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0, table
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_jobs WHERE mode IN ('issues', 'synth')")["n"] == 0
    assert chain.on_reviews_closed(store, rig.job_row(store, reviewed["job_id"]))["reason"] == "pre_m3_job"
    store.close()


def test_a_review_job_made_by_m3_code_carries_the_chain_mark(store):
    """M8(결정) — 검토 잡을 만들 때(사람의 처분이 세우는 잡도) 사슬 표지를 단다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [rig.SEAL]})
    assert json.loads(rig.job_row(store, job_id)["params_json"]).get("chain") is True
