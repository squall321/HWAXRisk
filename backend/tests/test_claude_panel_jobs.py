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
    assert set(job) == {"id", "tier", "state", "pause_reason", "panels_done", "panels_total", "error", "signal"}


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
