# Claude 길 X-2 잡 — 판단 LLM 선택 · 반출 동의 · 외부 길 호출 · 보류 external_worker · 사슬 상속 · 쟁점 패널 · 요약 · 표기 · 길잡이(가짜만)
"""포털 docs/risk-claude-engine 의 걸음 X-2 를 생산자 경로로 본다 — 대상 · 원장은 검토 루프 시험대(tests/synth/review_rig.py)가 짓고,
엔진은 실제 `PortalReviewEngine` 에 가짜 엔진(외부 응답자 길을 엔진 계약 예제 모양으로 흉내 낸다)을 꽂는다. 실제 Claude 는 부르지
않는다(사용자 결정 X-D1). GLM 잡이 종전과 같은지(요청 · params · 글)도 같이 본다.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app import (chain, config, engine_client, entry, expert_report, identity, issues, registry, review_quality,
                 review_runner, routes, runner, synth, units)
from app.common import now_epoch
from app.errors import AppError
from app.runner import EngineNoDecision, EngineRejected
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.fake_summary_engine import FakeSummaryEngine
from tests.synth.issue_panel_engine import IssuePanelEngine

OWNER = rig.OWNER
SEAL = rig.SEAL
EDITOR = "editor@example.com"
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}
JUDGE = "판단 LLM: Claude(외부, 사용자 신고 모델)"
# 반출 경고(XR-12) — 카드 대조만이 아니라 사슬이 이어 도는 쟁점 · 종합의 입력(대상 전체)도 나간다고 말해야 한다
EGRESS = ("이 잡의 지식카드·설계 변경 원문과, 사슬이 이어 도는 쟁점 패널·종합 요약의 입력(이 대상 전체의 등록부 행·쟁점·요약 —"
          " 다른 사람의 검토 결과도 든다)이 Claude(외부)로 나갑니다")
ABSENT = fre.load_external("error_external_worker_absent.json")
EVID_BUDGET = fre.load_external("health_on.json")["external_llm"]["evid_budget"]
# GLM 검토 잡 params 의 칸(X-2 전과 같아야 한다 — 새 칸은 claude 잡에만)
GLM_PARAM_KEYS = {"scope", "user_memo", "requester", "consent", "consent_source", "chain", "credential", "calls_estimate", "knobs"}


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _rid(alias: str) -> str:
    return str(CARDS[alias]["record_id"])


def _probe(monkeypatch, fake: FakeReviewEngine) -> None:
    """잡을 만들 때의 /health 탐침(review_runner.require_external_llm)이 가짜 엔진을 본다."""
    monkeypatch.setattr(engine_client, "build_review_engine",
                        lambda store, settings: engine_client.PortalReviewEngine(store, settings, transport=fake.transport))


def _one_cell(store, key: str) -> dict:
    return {"agents": [SEAL], "unit_ids": [units.load_units(store, key)[0]["unit_id"]]}


def _claude_job(store, key: str, scope=None, *, requester: str = OWNER, consent=True) -> dict:
    rig.pat(store)
    return review_runner.create_review_job(store, key, owner_sub=OWNER, requester_sub=requester, scope=scope, consent=True,
                                           consent_source="web", settings=config.settings, llm="claude",
                                           consent_external=consent)


def _params(store, job_id: str) -> dict:
    return json.loads(rig.job_row(store, job_id)["params_json"])


def _external_fake(**switches) -> FakeReviewEngine:
    fake = FakeReviewEngine(rig.packs())
    fake.external = True
    for name, value in switches.items():
        setattr(fake, name, value)
    return fake


def _jobs_n(store) -> int:
    return int(store.query_one("SELECT COUNT(*) AS n FROM rr_jobs")["n"])


def _delegate(email: str = OWNER) -> identity.Identity:
    """게이트웨이 위임으로 확인된 신원(MCP 입구를 entry 로 직접 부를 때 — 동의 입구는 mcp)."""
    return identity.Identity(email=email, display_name=email, role=None, organization=None, anonymous=False, source="sso",
                             delegated=True)


def _project_with_source(store, key: str) -> str:
    """길잡이가 대상 단계까지 걸어가게 소스를 붙인다(합성 대상은 소스 행 없이 스냅샷을 만든다)."""
    project_id = store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]
    routes.add_source(project_id, routes.SourceBody(kind="mcad", ref={"stepforge_project_id": "sf-1"}),
                      ident=factories.ident(OWNER))
    return project_id


# ================================================================ 잡 만들기
@pytest.mark.parametrize("consent", [None, False, "true", 1, "yes", {"ok": True}])
def test_claude_needs_a_json_true_consent_and_makes_nothing_without_it(store, monkeypatch, consent):
    """llm=claude 는 consent_external 이 JSON 참일 때만 선다 — 글자 'true' · 1 도 아니다(422 consent_external_required). 엔진이 길을
    열어 두어도 잡 행은 생기지 않는다. 사람 대신 동의를 채우는 길은 없다."""
    key = rig.target(store)
    _probe(monkeypatch, _external_fake())
    with pytest.raises(AppError) as refused:
        _claude_job(store, key, consent=consent)
    assert (refused.value.code, refused.value.http_status) == ("consent_external_required", 422)
    assert EGRESS in refused.value.message
    assert _jobs_n(store) == 0


def test_an_unknown_llm_value_is_refused(store, monkeypatch):
    key = rig.target(store)
    rig.pat(store)
    for llm in ("external", "gpt", "Claude"):
        with pytest.raises(AppError) as refused:
            review_runner.create_review_job(store, key, owner_sub=OWNER, consent=True, settings=config.settings, llm=llm,
                                            consent_external=True)
        assert (refused.value.code, refused.value.http_status) == ("E100", 422), llm
    assert _jobs_n(store) == 0


def test_claude_is_refused_when_the_engine_did_not_open_the_external_path(store, monkeypatch):
    """에이전트 서버 /health 의 capabilities 에 external_llm 이 없으면(기본 꺼짐) 409 external_llm_unavailable — /health 를 읽지
    못해도 같다(확인하지 못한 길에 잡을 세우지 않는다). 같은 박스의 GLM 잡은 탐침 없이 그대로 선다."""
    key = rig.target(store)
    closed = FakeReviewEngine(rig.packs())
    _probe(monkeypatch, closed)
    with pytest.raises(AppError) as refused:
        _claude_job(store, key)
    assert (refused.value.code, refused.value.http_status) == ("external_llm_unavailable", 409)
    assert refused.value.detail == {"reason": "capability_absent", "knob": "EXTERNAL_LLM_ENABLED"}
    closed.health_status = 503
    with pytest.raises(AppError) as unreadable:
        _claude_job(store, key)
    assert (unreadable.value.code, unreadable.value.detail["reason"]) == ("external_llm_unavailable", "health_unreachable")
    assert _jobs_n(store) == 0
    before = len(closed.requests)
    rig.job(store, key)                                      # GLM — 탐침하지 않는다
    assert len(closed.requests) == before and _jobs_n(store) == 1


def test_a_claude_job_records_who_consented_when_and_through_which_door(store, monkeypatch):
    key = rig.target(store)
    _probe(monkeypatch, _external_fake())
    before = now_epoch()
    out = _claude_job(store, key, _one_cell(store, key))
    params = _params(store, out["job_id"])
    consent = params["consent_external"]
    assert params["llm"] == out["llm"] == "claude" and out["consent_external"] == consent
    assert (consent["by"], consent["source"]) == (OWNER, "web") and before <= consent["at"] <= now_epoch()
    assert set(params) == GLM_PARAM_KEYS | {"llm", "consent_external"}
    glm = review_runner.create_review_job(store, rig.target(store, seed=7), owner_sub=OWNER, requester_sub=OWNER,
                                          consent=True, consent_source="web", settings=config.settings)
    assert set(_params(store, glm["job_id"])) == GLM_PARAM_KEYS and "llm" not in glm and "consent_external" not in glm


def test_a_claude_job_runs_only_with_the_consenters_own_pat(store, monkeypatch):
    """동의한 사람(요청자)의 PAT 로만 돈다 — 그 사람의 PAT 가 없으면 GLM 잡처럼 대상 소유자의 PAT 로 내려가지 않고 422 다(과제는 그
    사람의 Claude Code 워크플로만 집는다). 그 사람이 PAT 를 등록하면 requester 자격으로 선다."""
    key = rig.target(store)
    _probe(monkeypatch, _external_fake())
    rig.pat(store)                                            # 대상 소유자만 PAT 가 있다
    glm = review_runner.create_review_job(store, key, owner_sub=OWNER, requester_sub=EDITOR, consent=True,
                                          consent_source="web", settings=config.settings)
    assert (glm["credential"]["kind"], glm["credential"]["email"]) == ("owner", OWNER)
    runner.cancel_job(store, glm["job_id"], by=OWNER)
    with pytest.raises(AppError) as refused:
        _claude_job(store, key, requester=EDITOR)
    assert refused.value.code == "pat_unavailable" and f"동의한 사람({EDITOR})" in refused.value.message
    rig.pat(store, EDITOR)
    made = _claude_job(store, key, requester=EDITOR)
    assert (made["credential"]["kind"], made["credential"]["email"]) == ("requester", EDITOR)
    assert made["consent_external"]["by"] == EDITOR


def test_the_rest_body_takes_llm_and_a_strict_consent(store, monkeypatch):
    key = rig.target(store)
    rig.pat(store)
    _probe(monkeypatch, _external_fake())
    with pytest.raises(ValidationError):
        routes.JobBody(mode="panels", tier="A", llm="claude")         # 패널 잡은 이 박스의 LLM 으로만 돈다
    with pytest.raises(ValidationError):
        routes.JobBody(mode="reviews", llm="external")                # 엔진의 이름은 앱의 선택이 아니다
    body = routes.JobBody(mode="reviews", llm="claude", consent_external="true", scope=_one_cell(store, key))
    with pytest.raises(AppError) as refused:
        routes.create_job(key, body, ident=factories.ident(OWNER))
    assert refused.value.code == "consent_external_required"
    body = routes.JobBody(mode="reviews", llm="claude", consent_external=True, scope=_one_cell(store, key))
    out = routes.create_job(key, body, ident=factories.ident(OWNER))
    assert out["llm"] == "claude" and out["consent_external"]["source"] == "api"          # Bearer 는 api 입구
    (audit,) = [json.loads(r["after_json"]) for r in store.query("SELECT after_json FROM rr_audit WHERE action = 'job.create'")]
    assert audit["llm"] == "claude" and audit["consent_external"] == out["consent_external"]
    view = routes.review_payload(store, key, "cells")["job"]
    assert (view["llm"], view["consent_external"]) == ("claude", out["consent_external"])


def test_risk_start_job_carries_the_two_arguments_and_the_egress_warning(store, monkeypatch):
    import asyncio

    import app.mcp_server as srv

    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    tool = tools["risk_start_job"]
    assert {"llm", "consent_external"} <= set(tool.inputSchema["properties"])
    assert EGRESS in tool.description and "consent_external=true" in tool.description
    assert "동의를 받은 뒤에만" in tool.description and "external_worker" in tool.description
    key = rig.target(store)
    rig.pat(store)
    _probe(monkeypatch, _external_fake())
    ident = _delegate()
    with pytest.raises(AppError) as refused:
        entry.start_job(ident, target_key=key, mode="reviews", llm="claude", scope=_one_cell(store, key))
    assert refused.value.code == "consent_external_required"
    made = entry.start_job(ident, target_key=key, mode="reviews", llm="claude", consent_external=True,
                           scope=_one_cell(store, key))
    assert made["created"] is True and made["llm"] == "claude" and made["consent_external"]["source"] == "mcp"
    again = entry.start_job(ident, target_key=key, mode="reviews", scope=_one_cell(store, key), llm="glm")
    assert (again["created"], again["differs"], again["llm"]) == (False, ["llm"], "claude")


# ================================================================ 검토 루프 — 외부 응답자 길
def test_a_claude_job_runs_every_call_on_the_external_lane_and_says_so(store, monkeypatch):
    """창은 ?llm=external, 계획은 llm(동의 칸 없이), 호출은 llm + consent_external:true 로 간다. 판은 외부 창의 것이고(GLM 판과 갈린다)
    엔진이 외부 응답자 답에 단 model · llm 이 호출 원장에 남는다. 품질 글과 전문가 보고서가 '판단 LLM: Claude(외부, 사용자 신고
    모델)' 를 말한다. 셀은 차감되지 않는다."""
    key = rig.target(store)
    fake = _external_fake()
    _probe(monkeypatch, fake)
    job_id = _claude_job(store, key, _one_cell(store, key))["job_id"]
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)
    limits = fake.calls("limits")
    assert limits and {r["llm"] for r in limits} == {"external"}
    plans = [r["body"] for r in fake.calls("plan")]
    assert plans and all(b["llm"] == "external" and "consent_external" not in b for b in plans)
    runs = [r["body"] for r in fake.calls("run")]
    assert runs and all((b["llm"], b["consent_external"]) == ("external", True) for b in runs)
    ext = fre.load_external("limits_external.json")
    assert all((b.get("expect") or {}).get("limits_rev_kind") == ext["limits_rev_by_kind"][b["kind"]] for b in runs)
    calls = [dict(r) for r in store.query("SELECT model, state, quality_json FROM rr_review_calls WHERE run_id = ?", (job_id,))]
    assert {(c["model"], c["state"]) for c in calls} == {("external", "ok")}
    assert all("llm_mismatch" not in json.loads(c["quality_json"])["app"] for c in calls)
    assert {c["charged"] for c in store.query("SELECT charged FROM rr_review_cells WHERE run_id = ?", (job_id,))} == {0}
    text = review_quality.block(store, key)["text"]
    assert JUDGE in text.split("\n")[0] and "어긋남" not in text
    report = expert_report.build_report(store, key, SEAL)
    md = "\n".join(expert_report._md_head(report))
    assert JUDGE in md
    assert "llm_mismatch" not in _params(store, job_id)


def test_a_glm_job_sends_nothing_new_and_its_text_is_unchanged(store):
    """GLM 잡(없음)은 종전 그대로 — 창 질의 · 계획 · 호출 본문에 llm · 동의 칸이 없고, params 에 새 칸이 없고, 글에 판단 LLM 이 없다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope=_one_cell(store, key))
    fake = FakeReviewEngine(rig.packs())
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    assert {r["llm"] for r in fake.calls("limits")} == {None}
    assert not any({"llm", "consent_external"} & set(r["body"] or {}) for r in fake.requests if r["route"] in ("plan", "run"))
    assert set(_params(store, job_id)) == GLM_PARAM_KEYS
    assert "판단 LLM" not in review_quality.block(store, key)["text"]
    assert "judge_llm" not in review_quality.compute(store, key)
    assert "판단 LLM" not in "\n".join(expert_report._md_head(expert_report.build_report(store, key, SEAL)))


def test_an_absent_worker_holds_the_job_external_worker_and_it_resumes_only_by_a_person(store, monkeypatch):
    """일꾼(잡 주인의 Claude Code 워크플로)이 없으면 엔진이 기다림 한도 뒤 external_worker_absent 로 끝낸다 — 인프라라 셀은 차감
    없이 다시 나가고(기존 다시 내기), 차단기가 열리면 llm_outage(시계로 반쯤 연다)가 아니라 보류 external_worker 다. 시계를 아무리
    밀어도 스스로 돌지 않고, 워크플로가 돌아온 뒤 사람이 재개하면 끝까지 간다."""
    key = rig.target(store)
    fake = _external_fake(external_error=(ABSENT, None))
    _probe(monkeypatch, fake)
    job_id = _claude_job(store, key, {"agents": list(rig.CARD_EXPERTS)})["job_id"]
    r = rig.Rig(store, fake)
    r.run(lambda: rig.state(store, job_id) == "paused", step=1000)
    row = rig.job_row(store, job_id)
    assert (row["hold_code"], row["hold_until"], row["pause_reason"]) == ("external_worker", None, None)
    assert "hwax-risk-claude" in row["error"] and "external_worker_absent" in row["error"]
    infra = [c for c in store.query("SELECT outcome_class, error_code FROM rr_review_calls WHERE run_id = ?", (job_id,))
             if c["outcome_class"] == "infra"]
    assert len(infra) >= 10 and {c["error_code"] for c in infra} == {"external_worker_absent"}
    assert {c["charged"] for c in store.query("SELECT charged FROM rr_review_cells WHERE run_id = ?", (job_id,))} == {0}
    for _ in range(3):
        r.clock.advance(100_000)
        r.tick()
    assert rig.state(store, job_id) == "paused"
    fake.external_error = None                                   # 잡 주인이 워크플로를 다시 돌렸다
    runner.resume_job(store, job_id, by=OWNER)
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed"
    assert {c["charged"] for c in store.query("SELECT charged FROM rr_review_cells WHERE run_id = ?", (job_id,))} == {0}


def test_a_relay_that_drops_the_limits_query_holds_external_config_before_any_call(store, monkeypatch):
    """포털 중계가 ?llm=external 을 버리면 GLM 창이 온다 — 그 판으로 계획하지 않고 설정 보류(external_config)로 멈춘다(호출 0)."""
    key = rig.target(store)
    fake = _external_fake(drop_llm_query=True)
    _probe(monkeypatch, fake)
    job_id = _claude_job(store, key, _one_cell(store, key))["job_id"]
    rig.Rig(store, fake).run(lambda: rig.state(store, job_id) == "paused")
    row = rig.job_row(store, job_id)
    assert row["hold_code"] == "external_config" and "중계" in row["error"]
    assert fake.calls("run") == [] and fake.calls("plan") == []


def test_a_box_that_closed_the_path_after_the_job_was_made_holds_external_config(store, monkeypatch):
    key = rig.target(store)
    fake = _external_fake()
    _probe(monkeypatch, fake)
    job_id = _claude_job(store, key, _one_cell(store, key))["job_id"]
    fake.external = False                                        # 운영자가 스위치를 껐다(또는 값이 틀려 닫혔다)
    rig.Rig(store, fake).run(lambda: rig.state(store, job_id) == "paused")
    row = rig.job_row(store, job_id)
    assert row["hold_code"] == "external_config" and "external_llm_disabled" in row["error"]
    assert fake.calls("run") == []
    assert {c["charged"] for c in store.query("SELECT charged FROM rr_review_cells WHERE run_id = ?", (job_id,))} == {0}


def test_an_answer_that_was_not_the_external_responders_is_flagged_and_not_labelled_claude(store, monkeypatch):
    """claude 잡의 답인데 meta.llm 이 external 이 아니다(중계가 llm 을 버려 이 박스의 LLM 이 답했다) — 답은 받되 Claude 로 적지 않는다.
    그 호출 행에 llm_mismatch, 잡 params 에 셈, 품질 글 · 전문가 보고서에 어긋남이 보인다."""
    key = rig.target(store)
    fake = _external_fake(external_meta_llm=None)
    _probe(monkeypatch, fake)
    job_id = _claude_job(store, key, _one_cell(store, key))["job_id"]
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    calls = [json.loads(r["quality_json"])["app"] for r in store.query(
        "SELECT quality_json FROM rr_review_calls WHERE run_id = ? AND state = 'ok'", (job_id,))]
    assert calls and all(c["llm_mismatch"] == {"want": "external", "got": None} for c in calls)
    assert _params(store, job_id)["llm_mismatch"] == len(calls)
    text = review_quality.block(store, key)["text"].split("\n")[0]
    assert "판단 LLM 어긋남(llm_mismatch)" in text and JUDGE not in text
    assert review_quality.compute(store, key)["judge_llm"] == {"external": 0, "other": len(calls), "mismatch": len(calls)}
    md = "\n".join(expert_report._md_head(expert_report.build_report(store, key, SEAL)))
    assert "llm_mismatch" in md and JUDGE not in md
    assert routes.review_payload(store, key, "cells")["job"]["llm_mismatch"] == len(calls)


def test_the_external_per_owner_cap_is_a_wait_like_any_busy_gate(store, monkeypatch):
    key = rig.target(store)
    fake = _external_fake(busy_n=3, busy_reason="external_per_owner")
    _probe(monkeypatch, fake)
    job_id = _claude_job(store, key, _one_cell(store, key))["job_id"]
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    waits = [c for c in store.query("SELECT state, error_code FROM rr_review_calls WHERE run_id = ?", (job_id,))
             if c["state"] == "wait"]
    assert len(waits) == 3 and {c["error_code"] for c in waits} == {"review_busy"}
    assert {c["charged"] for c in store.query("SELECT charged FROM rr_review_cells WHERE run_id = ?", (job_id,))} == {0}


# ================================================================ 사슬
def test_the_chain_hands_llm_and_consent_to_the_issue_and_synth_jobs(store, monkeypatch):
    """사슬이 세우는 쟁점 · 종합 잡은 검토 잡의 판단 LLM 과 동의 기록(누가 · 언제 · 입구)을 그대로 물려받는다 — GLM 검토 잡 뒤에는
    새 칸이 없다."""
    key = rig.target(store)
    _probe(monkeypatch, _external_fake())
    review = _claude_job(store, key, _one_cell(store, key))
    prev = chain._job(store, review["job_id"])
    made = chain.create_stage_job(store, key, "issues", prev=prev, reason="reviews_closed", round_no=1)
    issue_params = _params(store, made["job_id"])
    assert (issue_params["llm"], issue_params["consent_external"]) == ("claude", review["consent_external"])
    assert issue_params["consent_source"] == "chain"
    nxt = chain.create_stage_job(store, key, "synth", prev=chain._job(store, made["job_id"]), reason="issues_completed",
                                 round_no=1)
    synth_params = _params(store, nxt["job_id"])
    assert (synth_params["llm"], synth_params["consent_external"]) == ("claude", review["consent_external"])
    view = routes.chain_stage(store, key)
    assert (view["llm"], view["consent_external"]) == ("claude", review["consent_external"])

    other = rig.target(store, seed=7)
    glm = rig.job(store, other, scope=_one_cell(store, other))
    made = chain.create_stage_job(store, other, "issues", prev=chain._job(store, glm), reason="reviews_closed", round_no=1)
    assert not {"llm", "consent_external"} & set(_params(store, made["job_id"]))
    assert "llm" not in routes.chain_stage(store, other)


# ================================================================ 쟁점 패널
class ExternalPanelEngine(IssuePanelEngine):
    """쟁점 패널 가짜 엔진의 외부 응답자 판 — /health 에 외부 길의 근거 예산, 결과에 엔진 result 프레임의 llm · tool_mode(delib_frames
    .json 의 모양). 받은 자격(owner_sub)을 남긴다."""

    def __init__(self, store, script=None, *, llm: str | None = "external") -> None:
        super().__init__(store, script)
        self.llm = llm
        self.owners: list[str | None] = []

    def health(self) -> dict:
        return {**super().health(), "evid_budget": 500_000,
                "external_llm": {**fre.load_external("health_on.json")["external_llm"]}}

    def run(self, delib_opts, *, owner_sub=None):
        self.owners.append(owner_sub)
        out = super().run(delib_opts, owner_sub=owner_sub)
        if self.llm is not None:
            result = fre.load_external("delib_frames.json")["result"]
            out.update(llm=self.llm, tool_mode=result["tool_mode"])
        return out


def _issue_ledger(store, monkeypatch, tmp_path) -> str:
    """held_fail 쟁점이 서는 원장 — 둘이 K01 을 FAIL 로, 둘이 OK 로 본다(GLM 검토 잡). 쟁점은 하나만 고른다."""
    key = rig.target(store)
    unit = units.load_units(store, key)[0]["unit_id"]
    for experts, verdicts in (((SEAL, "mech-syn-0"), {_rid("K01"): ("yes", "FAIL")}), (("xd-syn-0", "xd-syn-1"), {})):
        job_id = rig.job(store, key, scope={"agents": list(experts), "unit_ids": [unit]})
        fake = FakeReviewEngine(rig.packs())
        fake.verdicts = dict(verdicts)
        fake.mechs = {rid: ("interface.clearance", "") for rid in verdicts}
        rig.Rig(store, fake).finish(job_id)
        assert rig.state(store, job_id) == "completed"
    registry.merge(store, key)
    rig.configure(monkeypatch, store, tmp_path, risk_issue_panel_cap=1, risk_issue_panel_hard_cap=1)
    issues.select_issues(store, key, selected_round=1)
    return key


def _claude_issues_job(store, key: str, *, by: str = EDITOR) -> str:
    consent = {"by": by, "at": now_epoch(), "source": "web"}
    return issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=by, consent_source="chain",
                                    llm="claude", consent_external=consent)["job_id"]


def test_a_claude_issue_panel_goes_external_with_the_consenters_pat_and_the_external_budget(store, monkeypatch, tmp_path):
    """delib_opts 에 llm external + consent_external true, 엔진에 넘기는 자격은 동의한 사람(대상 소유자가 아니다), 브리프 크기는 /health
    의 external_llm.evid_budget 이다. 엔진 결과가 외부 응답자 답이면 패널에 판단 LLM 과 evidence_only 등급이 남고 보고서 줄이 그것을
    말한다."""
    key = _issue_ledger(store, monkeypatch, tmp_path)
    rig.pat(store, EDITOR)
    job_id = _claude_issues_job(store, key)
    engine = ExternalPanelEngine(store)
    claimed = runner.claim_next_job(store, config.settings, engine=engine)
    assert claimed["id"] == job_id and claimed["credential_email"] == EDITOR
    out = runner.run_panel(store, config.settings, engine, claimed)
    assert out["status"] == "done", out
    (opts,) = engine.calls
    assert (opts["llm"], opts["consent_external"], opts["target_key"]) == ("external", True, key)   # 대상 열쇠 — X-D8 ⑦
    assert engine.owners == [EDITOR]
    panel = store.query_one("SELECT model_json, quality_json, tool_mode FROM rr_panels WHERE id = ?", (out["panel_id"],))
    model = json.loads(panel["model_json"])
    assert (model["llm"], model["evid_budget"]) == ("external", EVID_BUDGET)
    assert model["brief_profile"]["budget"] != 500_000
    quality = json.loads(panel["quality_json"])
    assert quality["llm"] == "external" and "llm_mismatch" not in quality["flags"]
    assert panel["tool_mode"] == "evidence_only"
    assert JUDGE.split(": ", 1)[1] in synth._panel_judge(panel["quality_json"])
    assert any("쟁점 패널 1건 판단 LLM" in line for line in synth._judge_lines(store, key))


def test_the_engine_identity_of_a_claude_panel_is_the_consent_record_even_if_the_requester_differs(store, monkeypatch,
                                                                                                    tmp_path):
    """사슬은 요청자와 동의 기록을 함께 물려주므로 둘은 보통 같은 사람이다. 달라도(손으로 세운 잡) 엔진에 넘기는 자격은 동의 기록의
    사람이다 — 잡을 집을 때 PAT 를 본 그 사람이다(요청자의 PAT 로 돌면 동의하지 않은 사람의 줄에 과제가 선다)."""
    key = _issue_ledger(store, monkeypatch, tmp_path)
    rig.pat(store, EDITOR)
    issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER, consent_source="chain", llm="claude",
                             consent_external={"by": EDITOR, "at": now_epoch(), "source": "web"})
    engine = ExternalPanelEngine(store)
    claimed = runner.claim_next_job(store, config.settings, engine=engine)
    assert claimed["credential_email"] == EDITOR
    assert runner.run_panel(store, config.settings, engine, claimed)["status"] == "done"
    assert engine.owners == [EDITOR]


def test_a_glm_issue_panel_keeps_its_old_options_and_marks(store, monkeypatch, tmp_path):
    key = _issue_ledger(store, monkeypatch, tmp_path)
    issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    engine = ExternalPanelEngine(store, llm=None)
    out = runner.run_panel(store, config.settings, engine, runner.claim_next_job(store, config.settings, engine=engine))
    assert out["status"] == "done"
    (opts,) = engine.calls
    assert not {"llm", "consent_external", "target_key"} & set(opts)
    panel = store.query_one("SELECT model_json, quality_json, tool_mode FROM rr_panels WHERE id = ?", (out["panel_id"],))
    assert "llm" not in json.loads(panel["model_json"]) and json.loads(panel["model_json"])["evid_budget"] == 500_000
    quality = json.loads(panel["quality_json"])
    assert "llm" not in quality and "llm_mismatch" not in quality["flags"] and panel["tool_mode"] == "tools"
    assert synth._panel_judge(panel["quality_json"]) == "" and synth._judge_lines(store, key) == []


def test_a_claude_issue_job_never_runs_on_someone_elses_pat(store, monkeypatch, tmp_path):
    """동의한 사람의 PAT 가 없으면 대상 소유자의 PAT 가 있어도 쟁점 패널을 집지 않는다(서비스 · 남의 PAT 로 내려가지 않는다 — 아무도
    과제를 집지 못하거나 동의하지 않은 사람의 Claude 로 나간다). 잡은 PAT 없음 사유를 달고 기다린다."""
    key = _issue_ledger(store, monkeypatch, tmp_path)
    job_id = _claude_issues_job(store, key)                      # EDITOR 는 PAT 가 없다 — OWNER 만 있다
    engine = ExternalPanelEngine(store)
    assert runner.claim_next_job(store, config.settings, engine=engine) is None
    row = rig.job_row(store, job_id)
    assert row["state"] == "queued" and row["error"].startswith("pat_unavailable") and "동의한 사람" in row["error"]
    assert engine.calls == []
    rig.pat(store, EDITOR)
    claimed = runner.claim_next_job(store, config.settings, engine=engine)
    assert claimed is not None and claimed["credential_email"] == EDITOR


def test_an_absent_worker_in_a_claude_panel_holds_the_issue_job_external_worker(store, monkeypatch, tmp_path):
    key = _issue_ledger(store, monkeypatch, tmp_path)
    rig.pat(store, EDITOR)
    job_id = _claude_issues_job(store, key)
    frame = fre.load_external("delib_frames.json")["chair_failed_absent"]
    engine = ExternalPanelEngine(store, {"*": EngineNoDecision("chair_failed", frame["message"], knob=frame["knob"],
                                                               cause=frame["cause"])})
    out = runner.run_panel(store, config.settings, engine, runner.claim_next_job(store, config.settings, engine=engine))
    assert out["status"] == "error" and out["error"].startswith("chair_failed")
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"], row["hold_until"]) == ("paused", "external_worker", None)
    assert "hwax-risk-claude" in row["error"]
    (issue,) = issues.issue_rows(store, key, ("queued",))
    assert issue["charged"] == 0
    runner.resume_job(store, job_id, by=EDITOR)
    assert rig.job_row(store, job_id)["hold_code"] is None
    ok = ExternalPanelEngine(store)
    assert runner.run_panel(store, config.settings, ok, runner.claim_next_job(store, config.settings, engine=ok))["status"] \
        == "done"


@pytest.mark.parametrize("code", ["external_llm_disabled", "external_consent_required", "external_owner_missing"])
def test_a_closed_external_path_in_a_claude_panel_holds_external_config_uncharged(store, monkeypatch, tmp_path, code):
    key = _issue_ledger(store, monkeypatch, tmp_path)
    rig.pat(store, EDITOR)
    job_id = _claude_issues_job(store, key)
    engine = ExternalPanelEngine(store, {"*": EngineRejected(code, "외부 응답자 길이 닫혔다(가짜)")})
    for _ in range(3):                                          # 세 번이어도 연속 오류로 잡이 죽지 않는다(차감 없음)
        claimed = runner.claim_next_job(store, config.settings, engine=engine)
        if claimed is None:
            runner.resume_job(store, job_id, by=EDITOR)
            claimed = runner.claim_next_job(store, config.settings, engine=engine)
        out = runner.run_panel(store, config.settings, engine, claimed)
        assert out["status"] == "paused" and out["error"] == "external_config"
        row = rig.job_row(store, job_id)
        assert (row["state"], row["hold_code"]) == ("paused", "external_config") and code in row["error"]
    assert runner._error_streak(store, key) == 0
    (issue,) = issues.issue_rows(store, key, ("queued",))
    assert issue["charged"] == 0


def test_a_claude_panel_that_ran_on_glm_is_flagged_llm_mismatch(store, monkeypatch, tmp_path):
    key = _issue_ledger(store, monkeypatch, tmp_path)
    rig.pat(store, EDITOR)
    job_id = _claude_issues_job(store, key)
    engine = ExternalPanelEngine(store, llm=None)               # 중계가 delib_opts.llm 을 버려 이 박스의 LLM 으로 돌았다
    out = runner.run_panel(store, config.settings, engine, runner.claim_next_job(store, config.settings, engine=engine))
    assert out["status"] == "done" and "llm_mismatch" in out["quality_flags"]
    panel = store.query_one("SELECT quality_json, tool_mode FROM rr_panels WHERE id = ?", (out["panel_id"],))
    quality = json.loads(panel["quality_json"])
    assert quality["llm_mismatch"] == {"want": "external", "got": None} and "llm" not in quality
    assert panel["tool_mode"] == "tools"
    assert _params(store, job_id)["llm_mismatch"] == 1
    assert "llm_mismatch" in synth._panel_judge(panel["quality_json"]) and JUDGE not in synth._panel_judge(
        panel["quality_json"])


# ================================================================ 종합(요약)
class ExternalSummaryEngine(FakeSummaryEngine):
    """요약 가짜 엔진의 외부 응답자 판 — limits 는 llm=external 을 받으면 그 길의 표지를, run 은 외부 응답자 답의 meta 를 낸다."""

    def __init__(self, script=None, *, meta_llm: str | None = "external", lane: bool = True) -> None:
        super().__init__(script)
        self.meta_llm = meta_llm
        self.lane = lane
        self.limits_llm: list[str | None] = []

    def limits(self, *, email: str, llm: str | None = None) -> dict:
        self.limits_llm.append(llm)
        out = super().limits(email=email)
        return {**out, "llm": "external"} if llm == "external" and self.lane else out

    def run(self, body, *, email: str, on_progress=None, should_stop=None) -> dict:
        assert (body.get("llm"), body.get("consent_external")) == ("external", True)
        out = super().run({k: v for k, v in body.items() if k not in ("llm", "consent_external")}, email=email)
        if self.meta_llm is not None:
            out["meta"].update(model="external", llm=self.meta_llm, usage=None)
        return out


def _summary_ledger(store) -> str:
    key = rig.target(store)
    job_id = rig.job(store, key, scope=_one_cell(store, key))
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {_rid("K01"): ("yes", "FAIL")}
    fake.mechs = {_rid("K01"): ("interface.clearance", "")}
    rig.Rig(store, fake).finish(job_id)
    registry.merge(store, key)
    return key


def _claude_synth(store, key: str) -> str:
    rig.pat(store)
    return synth.create_synth_job(store, key, owner_sub=OWNER, requester_sub=OWNER, consent_source="chain", llm="claude",
                                  consent_external={"by": OWNER, "at": now_epoch(), "source": "web"})["job_id"]


def _tick(worker, limit: int = 80) -> list[dict]:
    steps = []
    for _ in range(limit):
        steps.append(worker.tick())
        if steps[-1]["step"] in ("completed", "idle", "hold"):
            break
    return steps


def test_a_claude_synth_job_asks_the_external_lane_and_labels_its_narratives(store):
    key = _summary_ledger(store)
    job_id = _claude_synth(store, key)
    engine = ExternalSummaryEngine()
    steps = _tick(synth.SynthWorker(store, config.settings, engine))
    assert steps[-1]["step"] == "completed", steps
    assert set(engine.limits_llm) == {"external"} and engine.requests
    done = [s for s in synth.latest_summaries(store, key) if s["state"] == "done"]
    assert done and {s["model"] for s in done} == {"external"}
    assert synth._narrative_lines(done[0], scope="x")[0].startswith(JUDGE)
    calls = store.query("SELECT model, quality_json FROM rr_review_calls WHERE run_id = ?", (job_id,))
    assert calls and {c["model"] for c in calls} == {"external"}


def test_a_claude_synth_job_whose_relay_dropped_the_lane_holds_external_config(store):
    key = _summary_ledger(store)
    job_id = _claude_synth(store, key)
    steps = _tick(synth.SynthWorker(store, config.settings, ExternalSummaryEngine(lane=False)))
    assert steps[-1] == {"job_id": job_id, "step": "hold", "hold": "external_config"}
    assert rig.job_row(store, job_id)["hold_code"] == "external_config"


def test_an_absent_worker_holds_the_synth_job_after_the_infra_limit_instead_of_closing_code_only(store):
    """요약 호출이 일꾼 없음으로 거듭 실패하면 기존 인프라 한도(HWAXRISK_SUMMARY_INFRA_MAX)까지 다시 내고, 그 뒤에는 서술 없이 닫지
    않고 잡을 보류 external_worker 로 멈춘다(요약은 대기 — 사람이 워크플로를 다시 돌리고 재개한다). 멈출 때 그 잡의 대기 요약의 인프라
    셈을 0 으로 돌린다(XR-13 — 재개한 잡이 다시 내기 몫을 다시 갖는다). 몇 번 뒤 멈췄는지는 잡 행의 글이 말한다."""
    key = _summary_ledger(store)
    job_id = _claude_synth(store, key)
    absent = EngineRejected(ABSENT["code"], ABSENT["message"], infra=True, retryable=True, knob=ABSENT["knob"])
    clock = rig.Clock()
    worker = synth.SynthWorker(store, config.settings, ExternalSummaryEngine({"*": absent}), clock=clock)
    for _ in range(200):
        step = worker.tick()
        if step.get("step") == "hold":
            break
        clock.advance(1000)
    assert step == {"job_id": job_id, "step": "hold", "hold": "external_worker"}
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"], row["hold_until"]) == ("paused", "external_worker", None)
    pending = [s for s in synth.latest_summaries(store, key) if s["run_id"] == job_id and s["state"] == "pending"]
    assert pending and all(s["infra_streak"] == 0 for s in pending)
    assert f"인프라 다시 내기 {config.settings.risk_summary_infra_max}회 뒤 멈췄다" in row["error"]
    assert not [s for s in synth.latest_summaries(store, key) if s["state_reason"] == "infra_exhausted"]


def test_a_claude_summary_that_was_not_the_external_responders_is_flagged(store):
    key = _summary_ledger(store)
    job_id = _claude_synth(store, key)
    steps = _tick(synth.SynthWorker(store, config.settings, ExternalSummaryEngine(meta_llm=None)))
    assert steps[-1]["step"] == "completed"
    flagged = [json.loads(c["quality_json"])["app"]["llm_mismatch"] for c in store.query(
        "SELECT quality_json FROM rr_review_calls WHERE run_id = ? AND state = 'ok'", (job_id,))]
    assert flagged and all(f == {"want": "external", "got": None} for f in flagged)
    assert _params(store, job_id)["llm_mismatch"] == len(flagged)


# ================================================================ 길잡이
def test_the_guide_reminds_a_claude_job_to_run_the_workflow_and_says_how_to_resume_its_holds(store, monkeypatch):
    key = rig.target(store)
    fake = _external_fake()
    _probe(monkeypatch, fake)
    job_id = _claude_job(store, key, _one_cell(store, key))["job_id"]
    project_id = _project_with_source(store, key)
    store.execute("UPDATE rr_jobs SET state = 'running' WHERE id = ?", (job_id,))
    guide = entry.next_step(_delegate(), project_id=project_id)
    assert any("hwax-risk-claude" in n and JUDGE.split(": ", 1)[1] in n for n in guide["notes"]), guide["notes"]
    assert review_runner.ReviewLoop(store, config.settings, None).hold(job_id, "external_worker", "일꾼 없음(시험)")
    guide = entry.next_step(_delegate(), project_id=project_id)
    (held,) = [b for b in guide["blocked"] if b["code"] == "external_worker"]
    assert "hwax-risk-claude" in held["fix"] and "resume" in held["fix"]
    assert [s["args"] for s in guide["next"] if s["tool"] == "risk_job_action"] == [{"job_id": job_id, "action": "resume"}]

    other = rig.target(store, seed=7)
    glm = rig.job(store, other, scope=_one_cell(store, other))
    store.execute("UPDATE rr_jobs SET state = 'running' WHERE id = ?", (glm,))
    pid = _project_with_source(store, other)
    glm_guide = entry.next_step(_delegate(), project_id=pid)
    assert glm_guide["where"] == "running" and not any("hwax-risk-claude" in n for n in glm_guide["notes"])


def test_the_hold_codes_have_fixes_and_never_resume_by_the_clock():
    from app import review_ops

    for code in ("external_worker", "external_config"):
        assert review_ops.HOLD_CODES[code].auto is False and review_ops.hold_delay_s(code, 3) is None
        assert entry.REVIEW_HOLD_FIX[code].endswith(".") and "resume" in entry.REVIEW_HOLD_FIX[code]
