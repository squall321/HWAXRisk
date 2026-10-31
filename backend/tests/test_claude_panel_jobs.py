# Tier 패널 잡의 판단 LLM 을 Claude 로 — 만들기(엄격한 동의 · 동의한 사람의 PAT 만 · 외부 길 확인) · 돌리기(외부 응답자 · 엔진이 알린 좌석 조회 길) · 보고서 줄 · REST 감사
"""포털 docs/claude-delib-parity C4 — 종전엔 패널 잡(mode=panels)이 llm=claude 를 422 로 거절했다(Claude 는 검토 잡과 그 사슬에만). 이제 패널
잡도 검토 잡과 같은 문(check_llm_choice · resolve_job_credential · require_external_llm)을 지나 Claude 로 돈다. 러너의 패널 실행은 쟁점 잡과
같은 길이다(외부 창의 브리프 · delib_opts.llm=external · 동의한 사람의 PAT · 보류 external_worker · llm_mismatch).

  실행:  .venv/bin/python -m pytest tests/test_claude_panel_jobs.py
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from app import config, registry, routes, runner
from app.common import now_epoch
from app.errors import AppError
from tests import factories
from tests import test_external_llm_jobs as X
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.test_runner_panel import OWNER, FakePanelEngine, _enc, fake_narrative, fake_registry, give_credential, seeded

PEER = "peer@x"


@pytest.fixture(autouse=True)
def _gateway_secret(monkeypatch):
    """seeded 대상은 게이트웨이 발급을 받아 본 박스다(test_runner_panel 과 같다)."""
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: "runner-panel-gateway-secret")


@pytest.fixture
def cfg(tmp_path):
    return dataclasses.replace(config.settings, data_dir=tmp_path)


def _peer_pat(store) -> None:
    store.upsert_credential(PEER, _enc("pat-peer"), "sub-2", PEER, "[]", now_epoch() + 30 * 86400)


def _claude(store, target_key, cfg, **kw) -> dict:
    return runner.create_job(store, target_key, "A", owner_sub=OWNER, settings=cfg, requester_sub=PEER, llm="claude",
                             consent_source="web", **{"consent_external": True, **kw})


def _params(store, job_id: str) -> dict:
    return json.loads(store.query_one("SELECT params_json FROM rr_jobs WHERE id = ?", (job_id,))["params_json"])


class ClaudeEngine(FakePanelEngine):
    """패널 가짜 엔진의 외부 응답자 판 — /health 에 외부 길(근거 예산), 결과에 엔진 result 프레임의 llm · tool_mode(delib_frames.json
    의 모양 — tool_mode 를 바꿔 끼울 수 있다)."""

    def __init__(self, tool_mode: str | None = None) -> None:
        super().__init__()
        self.tool_mode = tool_mode

    def health(self) -> dict:
        return {**super().health(), "evid_budget": 500_000, "external_llm": dict(fre.load_external("health_on.json")["external_llm"])}

    def run(self, delib_opts, *, owner_sub=None):
        result = fre.load_external("delib_frames.json")["result"]
        return {**super().run(delib_opts, owner_sub=owner_sub), "llm": result["llm"],
                "tool_mode": self.tool_mode or result["tool_mode"]}


# ---------------------------------------------------------------- 만들기
def test_a_claude_panel_job_needs_a_strict_consent_and_the_consenters_own_pat(risk_store, cfg, monkeypatch):
    target_key = seeded(risk_store)
    give_credential(risk_store)                                   # 대상 소유자만 PAT 가 있다
    X._probe(monkeypatch, X._external_fake())
    for bad in ("true", 1, None, False):
        with pytest.raises(AppError) as refused:
            _claude(risk_store, target_key, cfg, consent_external=bad)
        assert (refused.value.code, refused.value.http_status) == ("consent_external_required", 422), bad
    with pytest.raises(AppError) as refused:
        _claude(risk_store, target_key, cfg)
    assert refused.value.code == "pat_unavailable" and f"동의한 사람({PEER})" in refused.value.message, \
        "대상 소유자의 PAT 로 내려갔다 — 과제는 동의한 사람의 워크플로만 집는다"
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_jobs")["n"] == 0
    _peer_pat(risk_store)
    made = _claude(risk_store, target_key, cfg)
    assert (made["llm"], made["consent_external"]["by"], made["consent_external"]["source"]) == ("claude", PEER, "web")
    assert (made["credential"], made["credential_email"]) == ("requester", PEER)
    params = _params(risk_store, made["job_id"])
    assert (params["llm"], params["consent_external"]) == ("claude", made["consent_external"])
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    job = routes.coverage_payload(target_key)["job"]               # 진행판 · MCP risk_get_coverage 의 패널 잡 칸
    assert (job["id"], job["llm"], job["consent_external"]) == (made["job_id"], "claude", made["consent_external"])
    assert "params_json" not in job


def test_a_panel_jobs_consent_refusal_says_what_a_panel_job_sends(risk_store, cfg, monkeypatch):
    """패널 잡의 422 consent_external_required 글은 패널 잡이 내보내는 것(그 패널의 브리프 · 좌석 조회 결과)을 말한다 — 종전에는 검토 잡의
    반출 글(지식카드 · 사슬이 이어 도는 쟁점 패널 · 종합 요약)을 그대로 썼다(화면 세션 청할 것). 동의는 그 잡에만이고 C3 자동 후속 Tier C
    는 GLM 이다. 검토 잡의 글은 그대로다."""
    from app import review_runner

    target_key = seeded(risk_store)
    _peer_pat(risk_store)
    X._probe(monkeypatch, X._external_fake())
    with pytest.raises(AppError) as refused:
        _claude(risk_store, target_key, cfg, consent_external=None)
    message = refused.value.message
    assert runner.PANEL_EGRESS_WARNING in message and "그 패널의 브리프" in message and "좌석이 조회한 결과" in message
    assert review_runner.EGRESS_WARNING not in message and "사슬이 이어 도는" not in message
    assert "Tier C 는 GLM" in message
    with pytest.raises(AppError) as review_refused:
        review_runner.check_llm_choice("claude", None)
    assert review_runner.EGRESS_WARNING in review_refused.value.message


def test_a_claude_panel_job_is_refused_while_the_engine_keeps_the_external_path_closed(risk_store, cfg, monkeypatch):
    target_key = seeded(risk_store)
    _peer_pat(risk_store)
    X._probe(monkeypatch, FakeReviewEngine(rig.packs()))          # /health 에 external_llm 이 없다(기본 꺼짐)
    with pytest.raises(AppError) as refused:
        _claude(risk_store, target_key, cfg)
    assert (refused.value.code, refused.value.http_status) == ("external_llm_unavailable", 409)
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_jobs")["n"] == 0


def test_a_glm_panel_job_keeps_its_old_params_and_reply(risk_store, cfg, monkeypatch):
    target_key = seeded(risk_store)
    give_credential(risk_store)
    made = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    assert "llm" not in made and "consent_external" not in made
    params = _params(risk_store, made["job_id"])
    assert "llm" not in params and "consent_external" not in params
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    job = routes.coverage_payload(target_key)["job"]
    # 판단 LLM 칸(llm · consent_external)은 없다 — signals 는 도는 패널마다의 신호 목록이다(화면 세션 10-31, GLM · Claude 잡 모두).
    # hold_code · hold_until — 보류 코드(external_worker 따위)를 code 로 가른다(화면 세션 청할 것, 검토 잡 줄과 같은 두 칸).
    assert set(job) == {"id", "tier", "state", "pause_reason", "hold_code", "hold_until", "panels_done", "panels_total", "error",
                        "signal", "signals"}
    assert (job["hold_code"], job["hold_until"]) == (None, None)


# ---------------------------------------------------------------- 돌리기
@pytest.mark.parametrize("tool_mode", ["tools", "evidence_only"])
def test_a_claude_panel_runs_on_the_external_responder_and_records_the_engines_seat_lookup_way(risk_store, cfg, monkeypatch,
                                                                                               tool_mode):
    """delib_opts 에 llm external · 동의 true · 대상 열쇠, 엔진에 넘기는 자격은 동의한 사람, 브리프는 외부 창의 근거 예산이다. 패널의
    tool_mode 는 엔진이 result 프레임으로 알린 길(글 왕복이면 tools — 좌석 조회가 수치 근거로 세어진다)이다."""
    target_key = seeded(risk_store)
    give_credential(risk_store)
    _peer_pat(risk_store)
    X._probe(monkeypatch, X._external_fake())
    _claude(risk_store, target_key, cfg)
    job = runner.claim_next_job(risk_store, cfg)
    assert job["credential_email"] == PEER
    engine, recorder = ClaudeEngine(tool_mode), {}
    out = runner.run_panel(risk_store, cfg, engine, job,
                           narrative_mod=fake_narrative(recorder), registry_mod=fake_registry(recorder))
    assert out["status"] == "done", out
    (opts,) = engine.calls
    assert (opts["llm"], opts["consent_external"], opts["target_key"]) == ("external", True, target_key)
    assert engine.owner_subs == [PEER]
    panel = risk_store.query_one("SELECT model_json, quality_json, tool_mode FROM rr_panels WHERE id = ?", (out["panel_id"],))
    model, quality = json.loads(panel["model_json"]), json.loads(panel["quality_json"])
    assert (model["llm"], model["model"], model["evid_budget"]) == ("external", "external",
                                                                   fre.load_external("health_on.json")["external_llm"]["evid_budget"])
    assert quality["llm"] == "external" and "llm_mismatch" not in quality["flags"]
    assert panel["tool_mode"] == tool_mode


def test_a_claude_panel_without_a_worker_pauses_the_job_on_external_worker(risk_store, cfg, monkeypatch):
    """의장이 과제를 받을 워커가 없어 못 냈다(cause external_worker_absent) — 쟁점 잡과 같이 보류 external_worker 로 멈춘다."""
    target_key = seeded(risk_store)
    give_credential(risk_store)
    _peer_pat(risk_store)
    X._probe(monkeypatch, X._external_fake())
    _claude(risk_store, target_key, cfg)
    job = runner.claim_next_job(risk_store, cfg)
    failed = runner.EngineNoDecision("chair_failed", "의장 실패 — 외부 응답자가 없다", knob="EXTERNAL_LLM_WAIT_S",
                                     cause="external_worker_absent", conv_id="conv-1")
    out = runner.run_panel(risk_store, cfg, FakePanelEngine(raise_error=failed), job,
                           narrative_mod=fake_narrative({}), registry_mod=fake_registry({}))
    assert out["status"] == "error"
    row = risk_store.query_one("SELECT state, hold_code FROM rr_jobs WHERE id = ?", (job["id"],))
    assert (row["state"], row["hold_code"]) == ("paused", "external_worker")
    # 진행판 · MCP risk_get_coverage 의 패널 잡 줄도 그 보류를 code 로 싣는다 — 종전에는 칸이 없어 pause_reason(null)뿐이라 화면이
    # '모름' 이었다(화면 세션 청할 것). 자동 재개 시각이 없다(사람이 워크플로를 다시 돌리고 재개한다).
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    line = routes.coverage_payload(target_key)["job"]
    assert (line["id"], line["state"], line["pause_reason"], line["hold_code"], line["hold_until"]) == (
        job["id"], "paused", None, "external_worker", None)


def test_cancelling_a_held_claude_panel_job_clears_the_hold_on_its_coverage_line(risk_store, cfg, monkeypatch):
    """보류 external_worker 로 멈춘 Claude 패널 잡을 주인이 취소하면(REST · MCP risk_job_action — 같은 runner.cancel_job) 보류 열을 비운다
    — 재개와 검토 잡의 취소가 그렇듯. 종전에는 패널 갈래가 보류를 남겨, 취소된 잡의 진행판 줄이 hold_code external_worker 를 싣고 화면의
    '멈춘 까닭' 이 '워크플로를 다시 돌린 뒤 재개' 를 말했다(반대 검토 10-31)."""
    target_key = seeded(risk_store)
    give_credential(risk_store)
    _peer_pat(risk_store)
    X._probe(monkeypatch, X._external_fake())
    _claude(risk_store, target_key, cfg)
    job = runner.claim_next_job(risk_store, cfg)
    failed = runner.EngineNoDecision("chair_failed", "의장 실패 — 외부 응답자가 없다", knob="EXTERNAL_LLM_WAIT_S",
                                     cause="external_worker_absent", conv_id="conv-1")
    runner.run_panel(risk_store, cfg, FakePanelEngine(raise_error=failed), job,
                     narrative_mod=fake_narrative({}), registry_mod=fake_registry({}))
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    assert routes.coverage_payload(target_key)["job"]["hold_code"] == "external_worker"
    assert routes.job_action(job["id"], "cancel", ident=factories.ident(OWNER))["state"] == "cancelled"
    line = routes.coverage_payload(target_key)["job"]
    assert (line["id"], line["state"], line["pause_reason"], line["hold_code"], line["hold_until"]) == (
        job["id"], "cancelled", None, None, None)
    assert risk_store.query_one("SELECT hold_n FROM rr_jobs WHERE id = ?", (job["id"],))["hold_n"] == 0


def test_two_panel_jobs_made_in_the_same_second_read_as_the_later_one(risk_store, cfg, monkeypatch):
    """진행판의 패널 잡 줄은 마지막 패널 잡이다 — 같은 초에 선 둘이면 넣은 차례(rowid)로 가른다(검토 잡 줄 · 사슬 단계와 같다). 웹
    REST 는 부를 때마다 새 잡을 세운다(화면 세션 FE-27)."""
    target_key = seeded(risk_store)
    give_credential(risk_store)
    made = runner.new_uuid
    monkeypatch.setattr(runner, "new_uuid", lambda: "f" * 32)
    first = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    monkeypatch.setattr(runner, "new_uuid", made)
    runner.cancel_job(risk_store, first, by=OWNER)
    monkeypatch.setattr(runner, "new_uuid", lambda: "0" * 32)
    second = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    monkeypatch.setattr(runner, "new_uuid", made)
    risk_store.execute("UPDATE rr_jobs SET created_at = 1793000000 WHERE target_key = ?", (target_key,))
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    assert routes.coverage_payload(target_key)["job"]["id"] == second


def test_the_c3_follow_up_of_a_claude_tier_b_job_stays_on_glm(risk_store, cfg, monkeypatch):
    """정책(의도 — 바꾸지 않는다) — Claude 로 고른 Tier B 잡이 닫힘 레벨 C3 에서 끝나면 러너가 세우는 자동 후속 Tier C 는 판단 LLM 을
    물려받지 않고 GLM 으로 돈다. 반출 동의는 잡마다다(사용자 결정 10-15) — 사람이 그 잡에 동의하지 않았는데 시스템이 데이터를 Claude 로
    보내지 않는다. 후속 잡에는 llm · consent_external 칸이 없고 자격은 GLM 잡의 순서(요청자 → 소유자)다(context-notes RF-11)."""
    target_key = seeded(risk_store)
    give_credential(risk_store)
    _peer_pat(risk_store)
    X._probe(monkeypatch, X._external_fake())
    risk_store.execute("UPDATE rr_targets SET close_level = 'C3' WHERE target_key = ?", (target_key,))
    made = runner.create_job(risk_store, target_key, "B", owner_sub=OWNER, settings=cfg, requester_sub=PEER, llm="claude",
                             consent_source="web", consent_external=True)
    assert made["llm"] == "claude"
    job = dict(risk_store.query_one("SELECT id, target_key, tier, owner_sub, params_json FROM rr_jobs WHERE id = ?",
                                    (made["job_id"],)))
    job["params"] = json.loads(job.pop("params_json"))
    follow = runner._finish_job(risk_store, job, cfg)["next_job"]
    params = _params(risk_store, follow)
    assert (params["tier"], params["consent_source"], params["requester"]) == ("C", "close_level", PEER)
    assert "llm" not in params and "consent_external" not in params
    assert risk_store.query_one("SELECT credential_email FROM rr_jobs WHERE id = ?", (follow,))["credential_email"] == PEER


# ---------------------------------------------------------------- 보고서 · REST
def _panel_row(panel_no: int, quality: dict) -> dict:
    return {"id": f"p-{panel_no}", "panel_no": panel_no, "tier": "A", "status": "done", "engine": "web", "tool_mode": "tools",
            "conv_id": "c", "report_id": 1, "seats_json": "[]", "risk_spec_json": "{}", "risk_spec_parsed": 1,
            "quality_json": json.dumps(quality)}


def test_the_consolidated_report_names_the_judge_llm_of_a_claude_panel_only(risk_store):
    lines = registry._minutes_lines(risk_store, "t1", [_panel_row(1, {"llm": "external", "flags": []}),
                                                       _panel_row(2, {"flags": []})], [])
    one, two = (line for line in lines if line.startswith("panel_no="))
    assert "engine=web/tools llm=external conv_id=" in one
    assert "llm=" not in two and "engine=web/tools conv_id=" in two, "GLM 패널의 줄은 종전 그대로다"


def test_the_rest_route_takes_a_claude_panel_job_and_audits_the_consent(risk_store, monkeypatch):
    target_key = seeded(risk_store)
    give_credential(risk_store)
    X._probe(monkeypatch, X._external_fake())
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    body = routes.JobBody(mode="panels", tier="A", llm="claude", consent_external="true")
    with pytest.raises(AppError) as refused:
        routes.create_job(target_key, body, ident=factories.ident(OWNER))
    assert refused.value.code == "consent_external_required"
    out = routes.create_job(target_key, routes.JobBody(mode="panels", tier="A", llm="claude", consent_external=True),
                            ident=factories.ident(OWNER))
    assert out["llm"] == "claude" and out["consent_external"]["by"] == OWNER
    (audit,) = [json.loads(r["after_json"]) for r in risk_store.query("SELECT after_json FROM rr_audit WHERE action = 'job.create'")]
    assert (audit["mode"], audit["tier"], audit["llm"], audit["consent_external"]) == ("panels", "A", "claude",
                                                                                      out["consent_external"])
    runner.cancel_job(risk_store, out["job_id"], by=OWNER)
    glm = routes.create_job(target_key, routes.JobBody(mode="panels", tier="A"), ident=factories.ident(OWNER))
    assert "llm" not in glm
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_audit WHERE action = 'job.create'")["n"] == 1, \
        "GLM 패널 잡은 종전대로 감사 행이 없다"


# ---------------------------------------------------------------- C3 자동 후속 — 의도된 동작(사용자 결정 10-15)
def test_the_c3_follow_up_of_a_claude_tier_b_job_stays_on_glm(risk_store, cfg, monkeypatch):
    """Claude 로 돈 Tier B 잡 뒤에 러너가 세우는 C3 자동 후속 Tier C 는 판단 LLM 을 물려받지 않는다 — GLM 이다. 반출 동의는 잡마다
    사람이 하는 것이라(사용자 결정 10-15) 사람이 동의하지 않은 후속 잡이 그 대상의 자료를 Claude 로 보내지 않는다. 사람이 그 Tier C 도
    Claude 로 돌리려면 그 잡을 손으로 만들며 동의한다. 메모 · 층 · 뺀 항목은 물려받는다(BL-10 — test_brief_exclude)."""
    target_key = seeded(risk_store)
    risk_store.execute("UPDATE rr_targets SET close_level = 'C3' WHERE target_key = ?", (target_key,))
    give_credential(risk_store)
    _peer_pat(risk_store)
    X._probe(monkeypatch, X._external_fake())
    made = runner.create_job(risk_store, target_key, "B", owner_sub=OWNER, settings=cfg, requester_sub=PEER, llm="claude",
                             consent_source="web", consent_external=True)
    assert made["llm"] == "claude"
    job = dict(risk_store.query_one("SELECT id, target_key, tier, owner_sub, params_json FROM rr_jobs WHERE id = ?",
                                    (made["job_id"],)))
    job["params"] = json.loads(job.pop("params_json"))

    follow = runner._finish_job(risk_store, job, cfg)["next_job"]

    params = _params(risk_store, follow)
    assert (params["tier"], params["consent_source"], params["requester"]) == ("C", "close_level", PEER)
    assert "llm" not in params and "consent_external" not in params, "사람이 동의하지 않은 후속 잡이 Claude 로 돈다"
    assert runner.job_llm(params) is None
