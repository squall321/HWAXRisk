# Claude 길 X-2 반대 검토(X-D7)의 회귀 — 동의는 번지지 않는다(길) · MCP 동의는 JSON true 만 · 재개한 종합 잡의 인프라 몫 · 패널 모델 기록 · 패널 모드의 llm · 동의자 없는 잡
"""검토자의 재현 탐침(스크래치 x2-review 의 test_zz_x2_probe · test_zz_x2_probe2 · probes/mcp_bool · mcp_strict)을 시험으로 옮겼다 —
탐침의 장면은 그대로 두고 단언을 고친 동작(context-notes XR-12~XR-15)으로 바꿨다. 실제 Claude 는 부르지 않는다(X-D1). 가짜 엔진은
tests/test_external_llm_jobs.py 의 것을 쓴다.
"""
from __future__ import annotations

import json
import re

import pytest

from app import chain, config, issues, routes, runner, synth
from app.common import now_epoch
from tests import factories
from tests import test_external_llm_jobs as X
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

OWNER, EDITOR, SEAL = rig.OWNER, X.EDITOR, rig.SEAL
_ISSUE_RE = re.compile(r"\[쟁점 (iss-[0-9a-f]{12})")


class LaneEngine(X.ExternalPanelEngine):
    """쟁점 패널 가짜 엔진 — 외부 응답자 길(delib_opts.llm=external)로 온 패널에만 외부 응답자 답의 표지(result 프레임의 llm ·
    tool_mode)를 단다. GLM 패널은 종전 모양이다. 받은 (쟁점, 길, 엔진에 넘긴 자격)을 남긴다."""

    def __init__(self, store, script=None) -> None:
        super().__init__(store, script, llm=None)
        self.seen: list[tuple[str | None, str | None, str | None]] = []

    def run(self, delib_opts, *, owner_sub=None):
        out = super().run(delib_opts, owner_sub=owner_sub)
        found = _ISSUE_RE.search(str(delib_opts.get("question") or ""))
        self.seen.append((found.group(1) if found else None, delib_opts.get("llm"), owner_sub))
        if delib_opts.get("llm") == "external":
            out.update(llm="external", tool_mode=fre.load_external("delib_frames.json")["result"]["tool_mode"])
        return out


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _run_panels(store, engine, *, limit: int = 40) -> None:
    for _ in range(limit):
        job = runner.claim_next_job(store, config.settings, engine=engine)
        if job is None:
            return
        runner.run_panel(store, config.settings, engine, job)
    raise AssertionError(f"패널 러너가 {limit}번 안에 비지 않았다")


def _params(store, job_id: str) -> dict:
    return json.loads(rig.job_row(store, job_id)["params_json"])


def _issue_jobs(store, key: str) -> list[dict]:
    return [dict(r) for r in store.query("SELECT id, state, params_json, chain_json FROM rr_jobs WHERE target_key = ?"
                                         " AND mode = 'issues' ORDER BY created_at, rowid", (key,))]


def _queued(store, key: str) -> list[str]:
    return [r["issue_id"] for r in store.query("SELECT issue_id FROM rr_issues WHERE target_key = ? AND state = 'queued'"
                                               " ORDER BY issue_id", (key,))]


def _held_claude_issues_job(store, key: str) -> str:
    """탐침 2a — EDITOR 의 claude 사슬이 세운 쟁점 잡(동의 by EDITOR)이 일꾼 부재로 보류 external_worker 다(사람이 재개를 기다린다)."""
    job_id = issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=EDITOR, consent_source="chain", llm="claude",
                                      consent_external={"by": EDITOR, "at": now_epoch(), "source": "web"})["job_id"]
    runner._set_job(store, job_id, "paused", by="code:external_worker_absent", hold={"code": "external_worker", "until": None},
                    error="external_worker_absent: 가짜")
    return job_id


def _glm_reviews_close_the_scope(store, key: str) -> list[str]:
    """탐침 2a — OWNER 의 GLM 검토 잡 둘(동의 없음)이 격자 전부를 닫는다(둘이 K01 을 FAIL — 갈린 쟁점이 선다). GLM 사슬이 쟁점을 고른다."""
    made = []
    for experts, verdicts in (([SEAL, "mech-syn-0"], {X._rid("K01"): ("yes", "FAIL")}),
                              ([rig.BACKGROUND_ONLY, rig.ZERO_CARDS, "xd-syn-0", "xd-syn-1"], {})):
        job_id = rig.job(store, key, scope={"agents": experts})
        fake = FakeReviewEngine(rig.packs())
        fake.verdicts = dict(verdicts)
        fake.mechs = {rid: ("interface.clearance", "") for rid in verdicts}
        rig.Rig(store, fake).finish(job_id, ticks=2000)
        assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)
        made.append(job_id)
    return made


# ================================================================ 동의는 번지지 않는다(XR-12)
def test_a_glm_chain_neither_rearms_a_held_claude_issue_job_nor_sends_its_issues_out(store):
    """탐침 2a — GLM 사슬이 살아 있는(보류된) claude 쟁점 잡을 다시 세웠고, 사람이 그 잡을 재개하자 OWNER 의 GLM 검토(동의 없음)가 고른
    쟁점이 EDITOR 의 동의 · PAT 로 Claude 에 나갔다. 이제 GLM 사슬은 그 잡에 손대지 않고 제 길의 GLM 쟁점 잡을 세우며, 그 쟁점은 이 박스의
    LLM 으로 OWNER 의 자격으로 돈다."""
    key = rig.target(store)
    rig.pat(store)
    rig.pat(store, EDITOR)
    claude_job = _held_claude_issues_job(store, key)
    glm_reviews = _glm_reviews_close_the_scope(store, key)
    queued = _queued(store, key)
    assert queued, "장면 실패 — GLM 사슬이 쟁점을 세우지 않았다"
    held = rig.job_row(store, claude_job)
    assert json.loads(held["chain_json"] or "{}").get("rearmed_by") is None            # 다시 세우지 않았다
    assert _params(store, claude_job)[issues.ISSUE_ROUNDS_KEY] == {}                    # 일을 더하지 않았다
    glm_jobs = [j for j in _issue_jobs(store, key) if j["id"] != claude_job]
    assert len(glm_jobs) == 1 and "llm" not in json.loads(glm_jobs[0]["params_json"])
    assert json.loads(glm_jobs[0]["chain_json"])["prev_job_id"] in glm_reviews
    assert issues.claude_claims(store, key) == {}
    runner.resume_job(store, claude_job, by=EDITOR)                                   # 동의한 사람이 워크플로를 다시 돌리고 재개했다
    engine = LaneEngine(store)
    _run_panels(store, engine)
    assert sorted(i for i, _, _ in engine.seen) == queued
    assert {(llm, owner) for _, llm, owner in engine.seen} == {(None, OWNER)}, engine.seen


def test_a_person_requeueing_an_issue_never_lands_in_a_live_claude_issue_job(store, monkeypatch, tmp_path):
    """탐침 2b — 사람(OWNER)이 건너뛰었다가 다시 올린 쟁점이 EDITOR 의 살아 있는 claude 쟁점 잡에 붙어 EDITOR 의 Claude 로 나갔다(XR-10 은
    사람이 올린 쟁점의 잡을 GLM 이라 적는다). 이제 사람이 정한 쟁점은 claude 잡의 몫이 아니고, 올리기는 GLM 쟁점 잡을 세운다."""
    key = X._issue_ledger(store, monkeypatch, tmp_path)             # GLM 원장 · 쟁점 하나가 대기(회차 1)
    rig.pat(store, EDITOR)
    claude_job = X._claude_issues_job(store, key, by=EDITOR)
    (issue,) = _queued(store, key)
    assert issues.claude_claims(store, key) == {issue: claude_job}
    with factories.routes_store(store):
        routes.put_issue(issue, routes.IssueActionBody(action="skip", reason="잠시 뺀다"), ident=factories.ident(OWNER))
        out = routes.put_issue(issue, routes.IssueActionBody(action="queue", reason="사람이 다시 올린다"),
                               ident=factories.ident(OWNER))
    assert out["job_id"] != claude_job and "llm" not in _params(store, out["job_id"])
    assert _params(store, out["job_id"])["requester"] == OWNER
    assert issues.claude_claims(store, key) == {}
    assert issues.step_selection(store, key, 1) == {}                 # 사람이 정한 쟁점은 어느 claude 사슬 걸음의 몫도 아니다
    with factories.routes_store(store):                              # 다시 올려도 같은 GLM 잡에 붙는다(claude 잡이 아니다)
        routes.put_issue(issue, routes.IssueActionBody(action="skip", reason="또 뺀다"), ident=factories.ident(OWNER))
        again = routes.put_issue(issue, routes.IssueActionBody(action="queue", reason="또 올린다"), ident=factories.ident(OWNER))
    assert again["job_id"] == out["job_id"]
    engine = LaneEngine(store)
    _run_panels(store, engine)
    assert engine.seen == [(issue, None, OWNER)]


def test_a_person_refreshing_the_report_never_gets_a_waiting_claude_synth_job(store):
    """탐침 2c — 사람(OWNER)의 보고서 다시 내기가 EDITOR 의 동의로 선 대기 claude 종합 잡을 돌려받아 Claude 로 돌았다. 이제 종합 잡 다시
    쓰기는 같은 길(판단 LLM · 동의한 사람)끼리만이고 답은 늘 llm 을 말한다."""
    key = X._summary_ledger(store)
    rig.pat(store, EDITOR)
    consent = {"by": EDITOR, "at": now_epoch(), "source": "web"}
    made = synth.create_synth_job(store, key, owner_sub=OWNER, requester_sub=EDITOR, consent_source="chain", llm="claude",
                                  consent_external=consent)
    assert (made["created"], made["llm"], made["consent_external"]) == (True, "claude", consent)
    with factories.routes_store(store):
        out = routes.post_report(key, routes.ReportBody(refresh_summaries=True), ident=factories.ident(OWNER))
        again = routes.post_report(key, routes.ReportBody(refresh_summaries=True), ident=factories.ident(OWNER))
    assert (out["created"], out["llm"]) == (True, "glm") and out["job_id"] != made["job_id"]
    assert "llm" not in _params(store, out["job_id"]) and "consent_external" not in out
    assert (again["job_id"], again["created"], again["llm"]) == (out["job_id"], False, "glm")
    same = synth.create_synth_job(store, key, owner_sub=OWNER, requester_sub=EDITOR, consent_source="chain", llm="claude",
                                  consent_external=consent)
    assert (same["job_id"], same["created"], same["llm"], same["consent_external"]) == (made["job_id"], False, "claude", consent)
    rig.pat(store)
    other = synth.create_synth_job(store, key, owner_sub=OWNER, requester_sub=OWNER, consent_source="chain", llm="claude",
                                   consent_external={"by": OWNER, "at": now_epoch(), "source": "web"})
    assert other["created"] is True and other["job_id"] not in (made["job_id"], out["job_id"])
    assert _params(store, made["job_id"])["consent_external"]["by"] == EDITOR


def _two_lanes(store, key: str) -> tuple[str, str, list[str], list[str]]:
    """GLM 사슬이 세운 쟁점 잡(대기 쟁점 전부)과, 그 가운데 둘을 제 걸음의 몫으로 적은 EDITOR 의 claude 쟁점 잡 — (GLM 잡, claude 잡,
    claude 몫, GLM 몫)."""
    rig.pat(store)
    rig.pat(store, EDITOR)
    _glm_reviews_close_the_scope(store, key)
    (glm_job,) = [j["id"] for j in _issue_jobs(store, key)]
    queued = _queued(store, key)
    assert len(queued) >= 3, queued
    rounds = {r["issue_id"]: int(r["selected_round"]) for r in store.query(
        "SELECT issue_id, selected_round FROM rr_issues WHERE target_key = ? AND state = 'queued'", (key,))}
    mine = queued[:2]
    claude_job = issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=EDITOR, consent_source="chain",
                                          llm="claude", consent_external={"by": EDITOR, "at": now_epoch(), "source": "web"},
                                          issue_rounds={i: rounds[i] for i in mine})["job_id"]
    return glm_job, claude_job, mine, [i for i in queued if i not in mine]


def test_each_lane_runs_only_its_own_issues_on_one_target(store):
    """한 대상에 두 길의 쟁점 잡이 함께 산다 — claude 잡은 제 몫(사슬 걸음이 고른 쟁점)만 외부 응답자로 EDITOR 의 자격으로, GLM 잡은 그
    밖의 대기 쟁점만 이 박스의 LLM 으로 OWNER 의 자격으로 돈다. 패널 러너는 대상마다 패널 하나로 줄 세운다(먼저 선 잡부터)."""
    key = rig.target(store)
    glm_job, claude_job, mine, rest = _two_lanes(store, key)
    assert issues.claude_claims(store, key) == {i: claude_job for i in mine}
    assert rig.job_row(store, claude_job)["panels_total"] == len(mine)
    engine = LaneEngine(store)
    _run_panels(store, engine)
    external = sorted(i for i, llm, owner in engine.seen if (llm, owner) == ("external", EDITOR))
    local = sorted(i for i, llm, owner in engine.seen if (llm, owner) == (None, OWNER))
    assert external == sorted(mine) and local == sorted(rest) and len(engine.seen) == len(mine) + len(rest), engine.seen
    assert {rig.state(store, glm_job), rig.state(store, claude_job)} == {"completed"}


@pytest.mark.parametrize("first", ["glm", "claude"])
def test_cancelling_one_lanes_issue_job_releases_only_that_lanes_issues(store, first):
    """취소는 그 잡의 길 것만 놓는다 — 한 길의 잡을 취소해도 다른 길의 살아 있는 잡이 돌 쟁점은 대기 그대로이고, 취소한 잡의 몫만
    untried_cap(chain_cancelled) 이다(종전엔 대상의 대기 쟁점 전부를 놓았다). 두 차례(GLM 먼저 · claude 먼저) 다 본다."""
    key = rig.target(store)
    glm_job, claude_job, mine, rest = _two_lanes(store, key)
    order = [(glm_job, OWNER, rest, mine), (claude_job, EDITOR, mine, rest)]
    for step, (job_id, by, released, kept) in enumerate(order if first == "glm" else order[::-1]):
        runner.cancel_job(store, job_id, by=by)
        states = {r["issue_id"]: (r["state"], r["state_reason"]) for r in store.query(
            "SELECT issue_id, state, state_reason FROM rr_issues WHERE target_key = ?", (key,))}
        assert all(states[i] == ("untried_cap", "chain_cancelled") for i in released), (job_id, states)
        if step == 0:
            assert all(states[i][0] == "queued" for i in kept), ("다른 길의 쟁점까지 놓았다", states)
    assert _queued(store, key) == []


def test_a_released_issue_waits_for_its_own_lane(store):
    """패널이 결과 없이 닫힌 쟁점은 그 쟁점을 돌 잡이 있을 때만 대기로 남는다 — claude 잡의 몫은 그 잡이 살아 있으면, GLM 몫은 살아 있는
    GLM 잡이 있을 때만이다(살아 있는 claude 잡은 제 몫 밖을 집지 않으므로 그 잡만 있으면 미토의로 놓는다)."""
    key = rig.target(store)
    glm_job, claude_job, mine, rest = _two_lanes(store, key)
    runner.cancel_job(store, glm_job, by=OWNER)
    assert issues._orphan_reason(store, key, mine[0]) is None                      # claude 잡이 다시 집는다
    assert issues._orphan_reason(store, key, rest[0]) == "chain_cancelled"         # 살아 있는 GLM 잡이 없다
    with factories.routes_store(store):
        routes.put_issue(rest[0], routes.IssueActionBody(action="queue", reason="사람이 다시 올린다"),
                         ident=factories.ident(OWNER))
    assert issues._orphan_reason(store, key, rest[0]) is None                       # 사람이 세운 GLM 잡이 집는다


def test_the_chain_reuses_only_a_live_stage_job_of_the_same_lane(store):
    """사슬의 '살아 있으면 새로 세우지 않는다' 는 같은 길끼리만이다 — GLM 길은 GLM 잡만, claude 길은 같은 사람의 claude 잡만 본다."""
    key = rig.target(store)
    glm_job, claude_job, _, _ = _two_lanes(store, key)
    assert chain._busy(store, key, "issues", ("glm", None))["id"] == glm_job
    assert chain._busy(store, key, "issues", ("claude", EDITOR))["id"] == claude_job
    assert chain._busy(store, key, "issues", ("claude", OWNER)) is None
    assert chain.job_lane(_params(store, claude_job)) == ("claude", EDITOR) and chain.job_lane({}) == ("glm", None)
    with pytest.raises(ValueError):
        issues.bind_issues(store, glm_job, {"iss-000000000000": 1})                   # GLM 잡에는 몫을 적지 않는다


def test_a_later_step_that_reselects_an_issue_takes_it_into_its_own_lane(store):
    """마지막으로 고른 걸음이 이긴다 — claude 잡이 적은 회차 뒤에 다른 걸음(여기서는 GLM 사슬의 다시 고르기)이 같은 쟁점을 다시 고르면 그
    쟁점은 claude 잡의 몫에서 빠지고 GLM 잡이 돈다(GLM 걸음이 고른 일이 claude 잡에 남아 Claude 로 나가지 않는다)."""
    key = rig.target(store)
    glm_job, claude_job, mine, rest = _two_lanes(store, key)
    round_no = chain._next_round(store, key)
    issues.select_issues(store, key, selected_round=round_no)          # 다른 걸음이 대기 쟁점을 다시 고른다(회차가 오른다)
    assert issues.claude_claims(store, key) == {}
    engine = LaneEngine(store)
    _run_panels(store, engine)
    assert {(llm, owner) for _, llm, owner in engine.seen} == {(None, OWNER)}, engine.seen
    assert sorted(i for i, _, _ in engine.seen) == sorted(mine + rest)


def test_a_glm_step_does_not_count_the_claude_lanes_issues_as_its_work(store, monkeypatch):
    """GLM 사슬 걸음이 세는 대기 쟁점은 끝나지 않은 claude 잡의 몫을 뺀 것이다 — 남은 대기가 전부 claude 몫이면 빈 GLM 쟁점 잡을 세우지
    않고 GLM 종합으로 간다. 이 걸음이 새로 고른 것이 없는 장면이다(고르기를 비워 그 상태를 만든다 — 다시 고르면 회차가 올라 몫이 GLM 으로
    넘어온다)."""
    key = rig.target(store)
    glm_job, claude_job, mine, rest = _two_lanes(store, key)
    runner.cancel_job(store, glm_job, by=OWNER)                       # GLM 몫은 놓였고 claude 몫만 대기다
    first = store.query("SELECT id FROM rr_jobs WHERE target_key = ? AND mode = 'reviews' ORDER BY rowid", (key,))[0]["id"]
    monkeypatch.setattr(issues, "select_issues", lambda *a, **k: {})
    out = chain.on_reviews_closed(store, chain._job(store, first))
    assert (out["stage"], out["created"]) == ("synth", True), out
    assert "llm" not in _params(store, out["job_id"]) and rig.job_row(store, out["job_id"])["mode"] == "synth"
    assert [j["id"] for j in _issue_jobs(store, key)] == [glm_job, claude_job]
    assert issues.claude_claims(store, key) == {i: claude_job for i in mine}


def test_a_claude_chain_step_binds_only_the_issues_of_its_own_round(store, monkeypatch):
    """claude 사슬 걸음(회차 R)이 세우는 쟁점 잡은 그 회차로 고른 쟁점만 적는다 — 같은 대상에 앞 걸음(GLM)이 세운 대기 쟁점이 있어도
    그것은 그 길의 몫이다."""
    key = rig.target(store)
    glm_job, _, _, _ = _two_lanes(store, key)
    runner.cancel_job(store, [j["id"] for j in _issue_jobs(store, key) if j["id"] != glm_job][0], by=EDITOR)
    store.execute("UPDATE rr_issues SET state = 'queued', state_reason = NULL WHERE target_key = ?", (key,))
    queued = _queued(store, key)
    round_no = chain._next_round(store, key)
    store.execute("UPDATE rr_issues SET selected_round = ? WHERE issue_id = ?", (round_no, queued[0]))   # 이 걸음은 하나만 골랐다
    X._probe(monkeypatch, X._external_fake())
    review = X._claude_job(store, key, X._one_cell(store, key), requester=EDITOR)["job_id"]
    made = chain.create_stage_job(store, key, "issues", prev=chain._job(store, review), reason="reviews_closed",
                                  round_no=round_no)
    assert _params(store, made["job_id"])[issues.ISSUE_ROUNDS_KEY] == {queued[0]: round_no}
    assert issues.claude_claims(store, key) == {queued[0]: made["job_id"]}


def test_the_same_consenters_next_claude_step_adds_its_issues_to_the_live_claude_job(store, monkeypatch):
    """같은 사람의 claude 사슬 다음 걸음은 그 사람의 살아 있는 claude 쟁점 잡을 다시 세우고 거기에 제 회차의 쟁점을 더한다(새 잡을 세우지
    않는다) — 다시 고른 쟁점이 그 잡의 몫에 그대로 남는다."""
    key = rig.target(store)
    fake = X._external_fake(verdicts={X._rid("K01"): ("yes", "FAIL")}, mechs={X._rid("K01"): ("interface.clearance", "")})
    X._probe(monkeypatch, fake)
    rig.pat(store)
    rig.pat(store, EDITOR)
    review = X._claude_job(store, key, {"agents": [r["key"] for r in rig.ROSTER]}, requester=EDITOR)["job_id"]
    rig.Rig(store, fake).finish(review, ticks=2000)
    (claude_job,) = [j["id"] for j in _issue_jobs(store, key)]
    queued = _queued(store, key)
    out = chain.on_reviews_closed(store, chain._job(store, review))     # 같은 길의 다음 걸음(회차가 오른다)
    assert (out["job_id"], out["reason"]) == (claude_job, "issues_live") and len(_issue_jobs(store, key)) == 1
    later = chain._next_round(store, key) - 1
    assert _params(store, claude_job)[issues.ISSUE_ROUNDS_KEY] == {i: later for i in queued}
    assert issues.claude_claims(store, key) == {i: claude_job for i in queued}
    assert json.loads(rig.job_row(store, claude_job)["chain_json"])["rearmed_by"] == review


def test_a_glm_issue_job_closing_beside_a_waiting_claude_synth_job_makes_its_own_glm_synth_job(store):
    """종합 단계도 길을 가린다 — GLM 쟁점 잡이 닫힐 때 대기 중인 claude 종합 잡(다른 사람의 동의)을 다시 세우지 않고 GLM 종합 잡을 세운다."""
    key = X._summary_ledger(store)
    rig.pat(store, EDITOR)
    waiting = synth.create_synth_job(store, key, owner_sub=OWNER, requester_sub=EDITOR, consent_source="chain", llm="claude",
                                     consent_external={"by": EDITOR, "at": now_epoch(), "source": "web"})["job_id"]
    glm_issue_job = issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)["job_id"]
    runner._set_job(store, glm_issue_job, "completed")
    out = chain.on_issues_closed(store, chain._job(store, glm_issue_job))
    assert out["created"] is True and out["job_id"] != waiting and "llm" not in _params(store, out["job_id"])
    assert json.loads(rig.job_row(store, waiting)["chain_json"] or "{}").get("rearmed_by") is None


def test_a_claude_review_chain_binds_its_steps_issues_and_runs_them_on_the_consenters_lane(store, monkeypatch):
    """생산자 경로 — EDITOR 가 Claude 로 고른 검토 잡이 격자를 닫으면 사슬이 claude 쟁점 잡을 세우고, 그 잡은 이 걸음(회차)이 고른
    쟁점을 몫으로 적고 외부 응답자로 EDITOR 의 자격으로만 돈다. 뒤에 OWNER 가 손으로 올린 쟁점은 그 잡이 아니라 GLM 잡으로 간다."""
    key = rig.target(store)
    fake = X._external_fake(verdicts={X._rid("K01"): ("yes", "FAIL")}, mechs={X._rid("K01"): ("interface.clearance", "")})
    X._probe(monkeypatch, fake)
    rig.pat(store)
    rig.pat(store, EDITOR)
    review = X._claude_job(store, key, {"agents": [r["key"] for r in rig.ROSTER]}, requester=EDITOR)["job_id"]
    rig.Rig(store, fake).finish(review, ticks=2000)
    assert rig.state(store, review) == "completed", rig.job_row(store, review)
    (claude_job,) = [j for j in _issue_jobs(store, key)]
    params = json.loads(claude_job["params_json"])
    queued = _queued(store, key)
    assert len(queued) >= 2 and params["llm"] == "claude" and params["consent_external"]["by"] == EDITOR
    round_no = json.loads(claude_job["chain_json"])["round"]
    assert params[issues.ISSUE_ROUNDS_KEY] == {i: round_no for i in queued}
    engine = LaneEngine(store, {"*": {"severity": "중대", "judgement": "WARNING"}})
    first = runner.claim_next_job(store, config.settings, engine=engine)
    assert first["id"] == claude_job["id"]
    runner.run_panel(store, config.settings, engine, first)
    assert engine.seen[0][1:] == ("external", EDITOR)
    done = engine.seen[0][0]
    (human, *_) = [i for i in _queued(store, key) if i != done]
    with factories.routes_store(store):                             # 남은 쟁점 하나를 사람이 건너뛰었다가 다시 올린다 — GLM 이다
        routes.put_issue(human, routes.IssueActionBody(action="skip", reason="뺀다"), ident=factories.ident(OWNER))
        routes.put_issue(human, routes.IssueActionBody(action="queue", reason="올린다"), ident=factories.ident(OWNER))
    _run_panels(store, engine)
    by_issue = {i: (llm, owner) for i, llm, owner in engine.seen}
    assert sorted(by_issue) == sorted(queued) and len(engine.seen) == len(queued), engine.seen
    assert all(by_issue[i] == ("external", EDITOR) for i in queued if i != human), by_issue
    assert by_issue[human] == (None, OWNER), by_issue
