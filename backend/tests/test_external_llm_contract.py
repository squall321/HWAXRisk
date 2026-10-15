# Claude 길 X-2 엔진 계약 재생 — 엔진 외부 응답자 계약 예제(바이트 사본)를 앱의 엔진 클라이언트 · 분류표 · 심의 수집에 그대로 흘린다
"""에이전트 서버 README '외부 응답자' 절의 계약을 앱 쪽에서 본다(실제 Claude 는 부르지 않는다 — 엔진이 가짜 일꾼으로 뜬 예제다).

- 카드 대조 — limits 의 `?llm=external` · plan 의 `llm` · run 의 `llm` + `consent_external`, 끝 결과와 오류 프레임(일꾼 없음 · 답 시간
  초과)의 부류, 스트림 전 거절(rejects.json)의 부류.
- /health — 길을 연 박스(health_on)와 닫은 박스(health_off)의 칸.
- 심의(쟁점 패널) — result 프레임의 llm · tool_mode, 의장 실패의 cause, 길 닫힘 · 동의 없음 · 신원 없음 거절(delib_frames.json).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app import common, engine_client, identity, review_ops
from app.runner import EngineError, EngineNoDecision, EngineRejected, PatUnavailable
from tests.conftest import FIXTURES_DIR

EXTERNAL = FIXTURES_DIR / "external_llm" / "contract"
USER = "reviewer@example.com"


def _load(name: str):
    return json.loads((EXTERNAL / name).read_text(encoding="utf-8"))


def _engine(tmp_path, handler) -> engine_client.PortalReviewEngine:
    row = {"owner_sub": USER, "portal_pat": identity.encrypt_pat("pat-u").decode("ascii"), "pat_email": USER,
           "pat_exp": common.now_epoch() + 30 * 86400, "revoked_at": None, "pat_groups_json": "[]"}
    store = SimpleNamespace(get_credential=lambda sub: row if sub == USER else None)
    settings = SimpleNamespace(data_dir=tmp_path, portal_base="http://portal.test", agent_url="http://agent.test")
    return engine_client.PortalReviewEngine(store, settings, transport=httpx.MockTransport(handler))


def _stream(body: bytes) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------- 이름 · 본문 칸
def test_the_app_name_claude_goes_to_the_engine_as_external_and_glm_bodies_do_not_change():
    """앱의 선택은 claude, 엔진의 이름은 external 이다(엔진은 claude 를 bad_request 로 거절한다 — rejects.json). plan 은 llm 만(엔진
    PlanRequest 는 엄격하다), run 은 llm + 동의 표지. GLM(없음 · glm)은 칸을 하나도 더하지 않는다."""
    assert "claude" in _load("rejects.json")["bad_request.limits"]["body"]["message"]
    assert engine_client.engine_llm("claude") == "external"
    assert engine_client.engine_llm(None) is None and engine_client.engine_llm("glm") is None
    assert engine_client.llm_fields(None, "run") == engine_client.llm_fields("glm", "plan") == {}
    assert engine_client.llm_fields("claude", "plan") == {"llm": "external"}
    assert engine_client.llm_fields("claude", "run") == {"llm": "external", "consent_external": True}
    # 엔진 계약 예제의 요청과 같은 모양이다 — plan 예제에는 동의 칸이 없고 run 예제에는 둘 다 있다
    assert _load("plan_external_req.json")["llm"] == "external" and "consent_external" not in _load("plan_external_req.json")
    request = _load("req_verdict_ok.json")
    assert {k: request[k] for k in ("llm", "consent_external")} == engine_client.llm_fields("claude", "run")


def test_limits_ask_the_external_lane_with_the_query_and_glm_stays_unchanged(tmp_path):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        lane = request.url.params.get("llm")
        return httpx.Response(200, json=_load("limits_external.json") if lane == "external" else {"limits_rev": "glm"})

    engine = _engine(tmp_path, handler)
    assert engine.limits(email=USER, llm="external") == _load("limits_external.json")
    assert engine.limits(email=USER) == {"limits_rev": "glm"}
    assert seen == ["http://portal.test/agent/card-review/limits?llm=external",
                    "http://portal.test/agent/card-review/limits"]
    lim = _load("limits_external.json")
    # 외부 창의 limits 는 창 출처 external · 판이 GLM 과 갈린다 — 앱은 그 출처를 '아는 창' 으로 본다(fallback 가정이 아니다)
    assert (lim["ctx_source"], lim["llm"]) == ("external", "external")
    from app import review_runner

    assert lim["ctx_source"] in review_runner.known_ctx_sources("external")
    assert lim["ctx_source"] not in review_runner.known_ctx_sources(None)
    assert review_runner.limits_match(lim, "external") and not review_runner.limits_match({"llm": None}, "external")
    assert review_runner.limits_match({"llm": None}, None)


def test_plan_passes_the_llm_through_and_returns_the_external_rev(tmp_path):
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=_load("plan_external.json"))

    out = _engine(tmp_path, handler).plan(_load("plan_external_req.json"), email=USER)
    assert out == _load("plan_external.json") and out["llm"] == "external"
    assert sent == [_load("plan_external_req.json")]
    assert out["limits_rev"] == _load("limits_external.json")["limits_rev"]


# ---------------------------------------------------------------- run 장면(index.json)
INDEX = _load("index.json")
RESULT_SCENES = sorted(name for name, scene in INDEX.items() if scene["final"].startswith("result_"))
ERROR_SCENES = sorted(name for name, scene in INDEX.items() if scene["final"].startswith("error_"))


def test_every_external_scene_is_either_a_result_or_a_worker_error():
    assert set(RESULT_SCENES) | set(ERROR_SCENES) == set(INDEX)
    assert {_load(INDEX[n]["final"])["code"] for n in ERROR_SCENES} == set(review_ops.EXTERNAL_WORKER_CODES)


@pytest.mark.parametrize("scene", RESULT_SCENES)
def test_external_result_frames_replay_through_the_client(tmp_path, scene):
    """엔진이 가짜 일꾼으로 낸 프레임 그대로 — 끝 결과가 바이트 단위로 같은 dict 이고 meta 가 외부 응답자 답의 표지를 단다(llm ·
    model external, usage null — 모름이지 0 이 아니다). 요청은 그 장면의 요청 그대로 간다."""
    meta = INDEX[scene]
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/agent/card-review/run"
        sent.append(json.loads(request.content))
        return _stream((EXTERNAL / meta["frames"]).read_bytes())

    request = _load(meta["request"])
    result = _engine(tmp_path, handler).run(request, email=USER)
    assert result == _load(meta["final"])
    assert (result["meta"]["llm"], result["meta"]["model"], result["meta"]["usage"]) == ("external", "external", None)
    assert sent == [request]


@pytest.mark.parametrize("scene", ERROR_SCENES)
def test_external_worker_errors_are_infra_and_never_charge(tmp_path, scene):
    """일꾼 없음 · 답 시간 초과는 인프라(차감 없음 — 기다림 한도를 넘긴 사정이지 셀 탓이 아니다)이고 엔진의 비트 · 손잡이를 버리지
    않는다. 차단기가 그것으로 열리면 llm_outage 가 아니라 external_worker(사람이 워크플로를 다시 돌리고 재개한다)다."""
    meta = INDEX[scene]
    final = _load(meta["final"])
    engine = _engine(tmp_path, lambda request: _stream((EXTERNAL / meta["frames"]).read_bytes()))
    with pytest.raises(EngineRejected) as raised:
        engine.run(_load("req_verdict_ok.json"), email=USER)
    exc = raised.value
    assert exc.code == final["code"] and exc.knob == final["knob"]
    assert (exc.infra, exc.retryable) == (True, True) and exc.detail == final
    outcome = engine_client.review_outcome(exc)
    assert (outcome.klass, outcome.charge, outcome.hold_code) == (review_ops.INFRA, False, None)
    assert review_ops.outage_hold([final["code"]] * 10) == "external_worker"
    assert review_ops.HOLD_CODES["external_worker"].auto is False
    assert review_ops.hold_delay_s("external_worker", 1) is None


def test_the_outage_hold_follows_what_the_infra_failures_were():
    """차단기의 인프라 창이 외부 응답자 부재가 절반 이상이면 external_worker, 아니면 종전 llm_outage 다(GLM 잡은 늘 llm_outage)."""
    absent = "external_worker_absent"
    assert review_ops.outage_hold(["llm_unreachable"] * 10) == "llm_outage"
    assert review_ops.outage_hold([absent] * 5 + ["portal_unreachable"] * 5) == "external_worker"
    assert review_ops.outage_hold([absent] * 4 + ["portal_unreachable"] * 6) == "llm_outage"
    assert review_ops.outage_hold([]) == "llm_outage"


# ---------------------------------------------------------------- 스트림 전 거절(rejects.json)
REJECT_HOLDS = {
    "external_llm_disabled.limits": "external_config", "external_llm_disabled.plan": "external_config",
    "external_llm_disabled.run": "external_config", "external_consent_required.run": "external_config",
    "external_owner_missing.run": "external_config",
    # 모르는 llm 값 · 길이 다른 판 — 앱의 계약 어긋남(앱은 claude 를 늘 external 로 옮기고 판을 그 길의 limits 에서 받는다)
    "bad_request.limits": "contract", "bad_request.run": "contract", "rev_mismatch.run": "contract",
}


def test_every_external_rejection_is_classified():
    assert set(REJECT_HOLDS) == {k for k in _load("rejects.json") if not k.startswith("_")}


@pytest.mark.parametrize("name", sorted(REJECT_HOLDS))
def test_external_rejections_hold_the_job_without_charging(tmp_path, name):
    """설정 문제(길 닫힘 · 동의 표지 · 신원)는 셀 탓이 아니다 — 같은 호출을 다시 내도 같아 잡을 설정 보류(external_config)로 멈춘다."""
    refused = _load("rejects.json")[name]
    engine = _engine(tmp_path, lambda request: httpx.Response(refused["status"], json=refused["body"]))
    route = name.split(".", 1)[1]
    with pytest.raises((EngineRejected, PatUnavailable)) as raised:
        if route == "limits":
            engine.limits(email=USER, llm="external")
        elif route == "plan":
            engine.plan(_load("plan_external_req.json"), email=USER)
        else:
            engine.run(_load("req_verdict_ok.json"), email=USER)
    outcome = engine_client.review_outcome(raised.value)
    assert (outcome.klass, outcome.hold_code, outcome.charge) == (review_ops.JOB, REJECT_HOLDS[name], False), name
    assert review_ops.HOLD_CODES["external_config"].auto is False


# ---------------------------------------------------------------- /health
def test_health_shows_the_external_block_only_on_a_box_that_opened_the_path(tmp_path):
    on, off = _load("health_on.json"), _load("health_off.json")
    assert engine_client.external_health(on) == {
        "evid_budget": on["external_llm"]["evid_budget"], "ctx_tokens": on["external_llm"]["ctx_tokens"],
        "max_tokens": on["external_llm"]["max_tokens"], "max_inflight": on["external_llm"]["max_inflight"],
        "wait_s": on["external_llm"]["wait_s"], "answer_s": on["external_llm"]["answer_s"]}
    assert engine_client.external_health(off) is None
    assert engine_client.external_health({**on, "capabilities": ["card_review"]}) is None    # 칸이 남아도 능력이 없으면 닫힘

    def handler(info):
        return lambda request: httpx.Response(200, json={"model": "glm", **info})

    assert _engine(tmp_path, handler(on)).health()["external_llm"]["evid_budget"] == on["external_llm"]["evid_budget"]
    closed = _engine(tmp_path, handler(off)).health()
    assert "external_llm" not in closed and closed["card_review"]["capable"] is True


# ---------------------------------------------------------------- 심의(쟁점 패널) 프레임(delib_frames.json)
DELIB = _load("delib_frames.json")


def _frames(*parts: str) -> list[str]:
    return list("".join(parts).splitlines())


def test_an_external_deliberation_result_carries_its_marks():
    """외부 응답자 심의의 result 프레임은 llm · tool_mode 를 단다 — 러너가 그것으로 무엇이 돌았나를 본다(Claude 길 X-2)."""
    result = DELIB["result"]
    lines = _frames(_sse("status", DELIB["start_status"]), _sse("delib", DELIB["notice_card"]), _sse("result", result),
                    _sse("done", {}))
    out = engine_client.collect_stream(engine_client.parse_sse(lines))
    assert (out["llm"], out["tool_mode"]) == ("external", "evidence_only")
    assert out["decision_text"] == result["content"]
    plain = engine_client.collect_stream(engine_client.parse_sse(_frames(_sse("result", {"type": "text", "content": "x"}),
                                                                         _sse("done", {}))))
    assert "llm" not in plain and "tool_mode" not in plain          # GLM 심의의 결과 dict 는 종전 그대로


def test_a_chair_that_lost_its_worker_reports_the_cause():
    failed = DELIB["chair_failed_absent"]
    lines = _frames(_sse("warning", DELIB["seat_lost_absent"]), _sse("error", failed), _sse("done", {}))
    with pytest.raises(EngineNoDecision) as raised:
        engine_client.collect_stream(engine_client.parse_sse(lines))
    assert (raised.value.code, raised.value.cause) == ("chair_failed", "external_worker_absent")
    assert raised.value.cause in review_ops.EXTERNAL_WORKER_CODES


@pytest.mark.parametrize("name", ["refused_disabled", "refused_consent_required", "refused_owner_missing"])
def test_a_refused_external_deliberation_is_a_typed_rejection(name):
    frame = DELIB[name]
    with pytest.raises(EngineRejected) as raised:
        engine_client.collect_stream(engine_client.parse_sse(_frames(_sse("error", frame), _sse("done", {}))))
    assert raised.value.code == frame["code"] in review_ops.EXTERNAL_CONFIG_CODES


def test_an_unknown_llm_value_stays_a_plain_engine_error():
    """모르는 llm 값(bad_request)은 앱이 보내지 않는 값이다 — 종전처럼 엔진 오류로 닫힌다(설정 보류로 덮지 않는다)."""
    with pytest.raises(EngineError) as raised:
        engine_client.collect_stream(engine_client.parse_sse(_frames(_sse("error", DELIB["refused_bad_request"]),
                                                                     _sse("done", {}))))
    assert not isinstance(raised.value, EngineRejected) and str(raised.value).startswith("bad_request")
