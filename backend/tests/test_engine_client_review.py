# 카드 대조 엔진 클라이언트(m2-wp3b S7) — 응답 → 예외 → 부류 표, 엔진 계약 예제 재생, 대화 0건, 서비스 PAT 0회(전부 MockTransport)
"""포털 중계 `/agent/card-review/{limits,pack,plan,run}` 을 부르는 `PortalReviewEngine` 을 본다.

- 스트림 본문은 엔진이 실제 `run` 으로 낸 프레임(계약 예제 `run_*.sse`)이고, 스트림 전 거절은 엔진 예제(`rejects.json` ·
  `pack_errors.json`)와 포털 중계가 스스로 내는 모양(routes `_CrReject` · 포털 공통 `{detail}`)이다.
- 부류는 `review_ops.classify` 가 정한다(M2.md 4.4). 여기서는 응답 하나가 어느 예외가 되고 그 예외가 어느 부류로 가는지를 본다.
- 자격은 그 사람이 등록한 PAT 하나다(사용자 결정 3) — 서비스 PAT 가 secrets 에 있어도 어떤 요청 머리에도 실리지 않는다.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app import common, config, engine_client, identity, review_ops
from app.runner import EngineBusy, EngineRejected, EngineStreamLost, PatUnavailable
from tests.conftest import FIXTURES_DIR

CONTRACT = FIXTURES_DIR / "card_review" / "contract"
USER = "reviewer@example.com"
USER_PAT = "pat-reviewer"
SVC_PAT = "svc-pat-never-sent"
DAY = 86400


def _load(name: str):
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def _sse(name: str) -> bytes:
    return (CONTRACT / name).read_bytes()


def _settings(tmp_path, **knobs):
    return SimpleNamespace(data_dir=tmp_path, portal_base="http://portal.test", agent_url="http://agent.test", **knobs)


class _Store:
    """get_credential 만 흉내 낸다 — 행 모양은 RiskStore.get_credential 그대로(portal_pat 는 Fernet 암호문)."""

    def __init__(self, rows: dict | None = None):
        self.rows = rows or {}

    def get_credential(self, owner_sub):
        return self.rows.get(owner_sub)


def _row(pat: str = USER_PAT, *, left_s: int = 30 * DAY, revoked: bool = False) -> dict:
    return {"owner_sub": USER, "portal_pat": identity.encrypt_pat(pat).decode("ascii"), "pat_email": USER,
            "pat_exp": common.now_epoch() + left_s, "revoked_at": common.now_epoch() if revoked else None,
            "pat_groups_json": "[]"}


def _engine(tmp_path, handler, *, row: dict | None = None, **knobs) -> engine_client.PortalReviewEngine:
    # 서비스 PAT 를 늘 둔다 — 검토 경로가 그것으로 내려가지 않는다는 것이 이 파일 전체의 전제다.
    (tmp_path / "secrets.env").write_text(f"HWAXRISK_PORTAL_PAT={SVC_PAT}\n", encoding="utf-8")
    (tmp_path / "secrets.env").chmod(0o600)
    store = _Store({USER: row if row is not None else _row()})
    return engine_client.PortalReviewEngine(store, _settings(tmp_path, **knobs), transport=httpx.MockTransport(handler))


def _stream(body: bytes, status: int = 200) -> httpx.Response:
    return httpx.Response(status, content=body, headers={"content-type": "text/event-stream"})


def _raised(fn, *args, **kwargs) -> BaseException:
    with pytest.raises((EngineBusy, PatUnavailable, EngineRejected, EngineStreamLost)) as exc:
        fn(*args, **kwargs)
    return exc.value


# ---------------------------------------------------------------- 엔진 계약 예제 재생(run_*.sse)
INDEX = _load("index.json")
# 끝이 error 인 장면의 부류(M2.md 4.4) — (예외, 부류, 보류 코드).
ERROR_SCENES = {
    "review_busy": (EngineBusy, review_ops.WAIT, None),
    "review_busy_draining": (EngineBusy, review_ops.WAIT, None),        # update-all 비우기(재설계 M3 — 60초 뒤 같은 호출)
    "llm_timeout": (EngineRejected, review_ops.INFRA, None),
    "llm_unreachable": (EngineRejected, review_ops.INFRA, None),
    "llm_error": (EngineRejected, review_ops.INFRA, None),
    "llm_misconfigured": (EngineRejected, review_ops.JOB, "llm_misconfigured"),
    "llm_rejected": (EngineRejected, review_ops.CONTENT, None),
    "context_overflow": (EngineRejected, review_ops.JOB, "ctx_too_small"),
    "truncated_empty": (EngineRejected, review_ops.CONTENT, None),
    "no_rows": (EngineRejected, review_ops.CONTENT, None),
}


def test_every_contract_scene_is_classified():
    """색인의 장면은 result 로 끝나거나 표에 적은 error 로 끝난다 — 엔진이 장면을 더하면 이 표도 같이 는다."""
    finals = {name: _load(scene["final"]) for name, scene in INDEX.items()}
    errors = {name for name, final in finals.items() if "rows" not in final}
    assert errors == set(ERROR_SCENES), sorted(errors ^ set(ERROR_SCENES))


@pytest.mark.parametrize("scene", sorted(INDEX))
def test_the_engine_frames_replay_through_the_client(tmp_path, scene):
    """엔진이 실제로 낸 프레임을 그대로 흘리면 result 장면은 result 프레임이 바이트 단위로 같은 dict 로, error 장면은 그 코드의
    예외로 끝난다. 요청 본문은 그 장면의 요청 예제 그대로 간다(앱이 고치지 않는다)."""
    meta = INDEX[scene]
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/agent/card-review/run"
        sent.append(json.loads(request.content))
        return _stream(_sse(meta["frames"]))

    request = _load(meta["request"])
    engine = _engine(tmp_path, handler)
    final = _load(meta["final"])
    if scene not in ERROR_SCENES:
        assert engine.run(request, email=USER) == final
    else:
        kind, klass, hold = ERROR_SCENES[scene]
        exc = _raised(engine.run, request, email=USER)
        assert type(exc) is kind and exc.code == final["code"]
        outcome = engine_client.review_outcome(exc)
        assert (outcome.klass, outcome.hold_code) == (klass, hold), scene
        if isinstance(exc, EngineRejected):
            # 엔진이 실은 것을 버리지 않는다 — 비트·손잡이·본문(LLM 상태 포함).
            assert exc.infra is final["infra"] and exc.retryable is final["retryable"]
            assert exc.knob == final.get("knob") and exc.detail == final and "http_status" not in exc.detail
        else:
            # 관문 즉답은 30초, update-all 비우기(reason draining)는 60초 뒤 같은 호출이다(M3.md 4.5).
            assert exc.retry_after_s == final["retry_after_s"] == (60 if final.get("reason") == "draining" else 30)
    assert sent == [request]


# ---------------------------------------------------------------- 스트림 전 거절(엔진 rejects · 팩 오류 · 포털 중계)
# (상태, 본문, 머리) → (예외, 코드, 부류, 보류·실패 코드, 대기)
PORTAL_ANSWERS = [
    # 포털 권한 문(feat:deliberation 없음) — 본문이 포털 공통 {detail} 이라 상태로 가른다(D-28).
    (403, {"detail": "이 기능에는 feat:deliberation 이 필요합니다"}, {}, EngineRejected, "denied", review_ops.JOB, "contract", None),
    (401, {"detail": "PAT 가 유효하지 않습니다"}, {}, PatUnavailable, "credential_rejected", review_ops.JOB, "credential", None),
    (404, {"detail": "Not Found"}, {}, EngineRejected, "agent_outdated", review_ops.JOB, "agent_outdated", None),
    (404, {"code": "agent_outdated", "message": "에이전트 서버에 카드 대조 경로가 없다", "upstream": 404}, {},
     EngineRejected, "agent_outdated", review_ops.JOB, "agent_outdated", None),
    (413, {"code": "body_too_large", "message": "본문이 상한을 넘는다", "max_bytes": 4194304}, {},
     EngineRejected, "body_too_large", review_ops.CONTENT, "body_too_large", None),
    (429, {"code": "engine_busy", "message": "중계가 꽉 찼다", "retry_after_s": 30}, {"Retry-After": "30"},
     EngineBusy, "engine_busy", review_ops.WAIT, None, 30),
    (429, "Too Many Requests", {"Retry-After": "7"}, EngineBusy, "engine_busy", review_ops.WAIT, None, 7),
    (502, {"code": "agent_5xx", "message": "에이전트 서버 오류(HTTP 500)", "upstream": 500}, {},
     EngineRejected, "agent_5xx", review_ops.INFRA, None, None),
    (502, {"code": "agent_unreachable", "message": "에이전트 서버에 연결하지 못했다(ConnectError)"}, {},
     EngineRejected, "agent_unreachable", review_ops.INFRA, None, None),
    (504, {"code": "agent_timeout", "message": "600초 안에 오지 않았다", "knob": "AGENT_UNARY_TIMEOUT_S"}, {},
     EngineRejected, "agent_timeout", review_ops.INFRA, None, None),
    (502, "<html>Bad Gateway</html>", {}, EngineRejected, "portal_5xx", review_ops.INFRA, None, None),
    # FastAPI HTTPException(detail={...}) 모양 — 포털이 code 를 detail 안에서 찾는 것과 같은 규칙.
    (422, {"detail": {"code": "unknown_fields", "message": "선언하지 않은 칸", "fields": ["x"]}}, {},
     EngineRejected, "unknown_fields", review_ops.JOB, "contract", None),
]

REJECTS = _load("rejects.json")
PACK_ERRORS = _load("pack_errors.json")
# 엔진 예제 각각의 부류 — (예외, 부류, 보류·실패 코드).
REJECT_CLASS = {
    "unknown_fields": (EngineRejected, review_ops.JOB, "contract"),
    "bad_request": (EngineRejected, review_ops.JOB, "contract"),
    "unsupported_kind": (EngineRejected, review_ops.JOB, "contract"),
    "unsupported_unit_kind": (EngineRejected, review_ops.JOB, "contract"),
    "empty_unit": (EngineRejected, review_ops.JOB, "contract"),
    "deck_too_large": (EngineRejected, review_ops.JOB, "contract"),
    "over_budget": (EngineRejected, review_ops.JOB, "ctx_too_small"),
    "rev_mismatch": (EngineRejected, review_ops.JOB, "contract"),
    "denied": (EngineRejected, review_ops.JOB, "contract"),
    "ctx_too_small": (EngineRejected, review_ops.JOB, "ctx_too_small"),
    "ctx_unknown": (EngineBusy, review_ops.WAIT, None),
    "cover_too_large": (EngineRejected, review_ops.JOB, "contract"),   # 요약의 must_cover 가 상한을 넘었다 — 앱 결함(M3.md 4.5)
}
PACK_CLASS = {
    "agent_not_found": (EngineRejected, review_ops.PACK, "agent_not_found"),
    "tools_unavailable": (EngineRejected, review_ops.PACK, "pack_unavailable"),
    "card_fetch_failed": (EngineRejected, review_ops.PACK, "pack_unavailable"),
    "card_list_unstable": (EngineRejected, review_ops.PACK, "pack_unavailable"),
    "credential_missing": (PatUnavailable, review_ops.JOB, "credential"),
    "credential_rejected": (PatUnavailable, review_ops.JOB, "credential"),
    "review_busy": (EngineBusy, review_ops.WAIT, None),
}


def _answer(status, body, headers):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(status, text=body, headers=headers)
        return httpx.Response(status, json=body, headers=headers)
    return handler


def _code_of(outcome: review_ops.Outcome) -> str | None:
    return outcome.hold_code or outcome.fail_code


def test_every_engine_example_is_in_the_class_tables():
    assert set(REJECT_CLASS) == {k for k in REJECTS if not k.startswith("_")}
    assert set(PACK_CLASS) == set(PACK_ERRORS)


@pytest.mark.parametrize("name", sorted(REJECT_CLASS))
def test_engine_refusals_before_the_stream_keep_their_code_on_every_route(tmp_path, name):
    """엔진의 스트림 전 거절(포털이 상태·본문 그대로 넘긴다)은 run·plan 어느 쪽이든 같은 예외·부류다."""
    example = REJECTS[name]
    kind, klass, code = REJECT_CLASS[name]
    engine = _engine(tmp_path, _answer(example["status"], example["body"], {}))
    for call in (lambda: engine.run({"kind": "verdict"}, email=USER), lambda: engine.plan({"cards": []}, email=USER)):
        exc = _raised(call)
        assert type(exc) is kind and exc.code == name
        outcome = engine_client.review_outcome(exc)
        assert (outcome.klass, _code_of(outcome)) == (klass, code)
        if isinstance(exc, EngineRejected):
            assert exc.detail == {**example["body"], "http_status": example["status"]}
        if isinstance(exc, EngineBusy):
            assert exc.retry_after_s == example["body"]["retry_after_s"] == outcome.retry_after_s


@pytest.mark.parametrize("name", sorted(PACK_CLASS))
def test_pack_errors_keep_their_code(tmp_path, name):
    """팩 오류는 코드를 지킨다 — 502·503 을 portal_5xx 로 덮으면 팩 재시도와 인프라가 섞인다(포털 _cr_answer 와 같은 규칙)."""
    example = PACK_ERRORS[name]
    kind, klass, code = PACK_CLASS[name]
    exc = _raised(_engine(tmp_path, _answer(example["status"], example["body"], {})).pack, "mech-test-seal", email=USER)
    assert type(exc) is kind and exc.code == name
    outcome = engine_client.review_outcome(exc)
    assert (outcome.klass, _code_of(outcome)) == (klass, code)
    if klass == review_ops.PACK:
        assert outcome.max_tries == (review_ops.AGENT_NOT_FOUND_MAX if name == "agent_not_found" else review_ops.PACK_RETRY_MAX)


@pytest.mark.parametrize("status,body,headers,kind,code,klass,hold,wait", PORTAL_ANSWERS)
def test_portal_answers_map_to_the_table(tmp_path, status, body, headers, kind, code, klass, hold, wait):
    """포털 중계가 스스로 내는 것과 앞단(nginx)이 낸 것 — 코드가 없으면 상태로 가르고, 있으면 원문 그대로다."""
    for route in ("run", "limits"):
        engine = _engine(tmp_path, _answer(status, body, headers))
        exc = _raised(engine.run, {"kind": "verdict"}, email=USER) if route == "run" else _raised(engine.limits, email=USER)
        assert type(exc) is kind and exc.code == code, route
        outcome = engine_client.review_outcome(exc)
        assert (outcome.klass, _code_of(outcome), outcome.retry_after_s) == (klass, hold, wait), route


def test_a_portal_that_cannot_be_reached_is_infra(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    for call in ("limits", "run"):
        engine = _engine(tmp_path, handler)
        exc = _raised(engine.limits, email=USER) if call == "limits" else _raised(engine.run, {}, email=USER)
        assert isinstance(exc, EngineRejected) and exc.code == "portal_unreachable" and exc.infra is True
        assert engine_client.review_outcome(exc).klass == review_ops.INFRA


def test_a_200_that_is_not_a_json_object_is_not_silently_read(tmp_path):
    exc = _raised(_engine(tmp_path, lambda r: httpx.Response(200, json=[1, 2])).limits, email=USER)
    assert isinstance(exc, EngineRejected) and exc.code == "review_parse_failed"


# ---------------------------------------------------------------- 스트림을 놓은 것(침묵·절단·벽시계·사람의 정지)
def test_lost_streams_name_the_cause_and_the_knob(tmp_path):
    def body(gen):
        return lambda request: _stream(gen(request))

    def silent(request):
        yield b'event: status\ndata: {"step": "attempt", "n": 2}\n\n'
        raise httpx.ReadTimeout("idle", request=request)

    exc = _raised(_engine(tmp_path, body(silent)).run, {}, email=USER)
    assert isinstance(exc, EngineStreamLost) and exc.code == "engine_silent" and exc.conv_id is None
    assert "카드 대조 스트림이 300초 동안 조용했다(HWAXRISK_REVIEW_READ_TIMEOUT_S)" in str(exc)
    assert "마지막 단계 attempt 2" in str(exc) and "conv_id" not in str(exc) and "심의" not in str(exc)
    assert engine_client.review_outcome(exc) == review_ops.classify("engine_silent")

    def cut(request):
        yield b'event: status\ndata: {"step": "attempt", "n": 1}\n\n'
        raise httpx.RemoteProtocolError("peer closed connection", request=request)

    exc = _raised(_engine(tmp_path, body(cut)).run, {}, email=USER)
    assert isinstance(exc, EngineStreamLost) and exc.code == "engine_stream_cut"
    assert engine_client.review_outcome(exc).klass == review_ops.INFRA

    # 끝 프레임 없이 끝난 스트림 — 포털 중계는 상류가 스스로 끝났으면 아무것도 덧붙이지 않는다.
    exc = _raised(_engine(tmp_path, lambda r: _stream(b'event: status\ndata: {"step": "attempt", "n": 1}\n\n')).run,
                  {}, email=USER)
    assert isinstance(exc, EngineStreamLost) and exc.code == "engine_stream_cut"

    # 포털 중계가 끊김을 알리는 끝(error{agent_unreachable, infra} → done)은 엔진 코드처럼 그대로 간다.
    relay_cut = (b'event: status\ndata: {"step": "attempt", "n": 1}\n\n'
                 b'event: error\ndata: {"code": "agent_unreachable", "message": "\xec\x8a\xa4\xed\x8a\xb8\xeb\xa6\xbc", '
                 b'"infra": true, "retryable": true}\n\nevent: done\ndata: {}\n\n')
    exc = _raised(_engine(tmp_path, lambda r: _stream(relay_cut)).run, {}, email=USER)
    assert isinstance(exc, EngineRejected) and exc.code == "agent_unreachable" and exc.infra is True
    assert engine_client.review_outcome(exc).klass == review_ops.INFRA
    # 엔진의 error 뒤 done 전에 끊기면 중계가 제 끝을 덧붙인다 — 결말은 먼저 온 엔진의 것이다(설정을 고칠 일이 인프라로 묻히지 않게).
    engine_error = _sse("run_llm_misconfigured.sse").rsplit(b"event: done", 1)[0]
    exc = _raised(_engine(tmp_path, lambda r: _stream(engine_error + relay_cut.split(b"\n\n", 1)[1])).run, {}, email=USER)
    assert isinstance(exc, EngineRejected) and exc.code == "llm_misconfigured"

    # done 까지 왔는데 result 가 없다 — 엔진 결함이라 내용 탓으로 센다(같은 셀을 끝없이 다시 내지 않는다).
    exc = _raised(_engine(tmp_path, lambda r: _stream(b"event: done\ndata: {}\n\n")).run, {}, email=USER)
    assert isinstance(exc, EngineRejected) and exc.code == "review_parse_failed"
    assert engine_client.review_outcome(exc).klass == review_ops.CONTENT


def test_the_call_wall_clock_and_a_human_stop_close_the_stream(tmp_path):
    """줄이 계속 와도 호출 벽시계를 넘기면 끊는다 — 처음은 인프라, 같은 호출의 두 번째는 내용 탓이다(review_ops)."""
    now = {"t": common.now_epoch()}
    sent: list[str] = []

    def handler_for(elapsed: int):
        def frames():
            yield b'event: status\ndata: {"step": "attempt", "n": 1}\n\n'
            now["t"] += elapsed
            sent.append("late")
            yield ('event: result\ndata: %s\n\n' % json.dumps(_load("result_verdict_solo.json"))).encode()
            sent.append("end")
            yield b"event: done\ndata: {}\n\n"
        return lambda request: _stream(frames())

    wall_s = config.review_call_timeout_s(_settings(tmp_path))
    assert wall_s == config.DEFAULT_REVIEW_CALL_TIMEOUT_S == 18000
    previous = common.set_clock(lambda: now["t"])
    try:
        assert _engine(tmp_path, handler_for(wall_s)).run({}, email=USER)["variant"] == "solo"
        sent.clear()
        exc = _raised(_engine(tmp_path, handler_for(wall_s + 1)).run, {}, email=USER)
        assert sent == ["late"]
        assert isinstance(exc, EngineStreamLost) and exc.code == "review_timeout"
        assert str(exc).startswith("review_timeout: 카드 대조 호출이 18000초(HWAXRISK_REVIEW_CALL_TIMEOUT_S)를 넘겼다 — "
                                   "경과 18001초, 마지막 단계 attempt 1.")
        first, second = engine_client.review_outcome(exc), engine_client.review_outcome(exc, timeouts_before=1)
        assert (first.klass, first.charge) == (review_ops.INFRA, False)
        assert (second.klass, second.charge, second.fail_code) == (review_ops.CONTENT, True, "review_timeout")
        # 손잡이 0 은 재지 않는다.
        assert _engine(tmp_path, handler_for(30 * DAY), risk_review_call_timeout_s=0).run({}, email=USER)["rows"]
    finally:
        common.set_clock(previous)

    stops = iter([None, "사용자가 잡을 취소했다"])
    exc = _raised(_engine(tmp_path, handler_for(0)).run, {}, email=USER, should_stop=lambda: next(stops))
    assert isinstance(exc, EngineStreamLost) and exc.code == "cancelled"
    assert "사용자가 잡을 취소했다 — 진행 중 카드 대조 호출을 닫았다" in str(exc)
    assert engine_client.review_outcome(exc).klass == review_ops.CANCELLED


def test_timeouts_are_the_review_knobs(tmp_path):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = request.extensions["timeout"]
        if request.url.path.endswith("/run"):
            return _stream(_sse("run_verdict_solo.sse"))
        return httpx.Response(200, json=_load("limits_1m.json"))

    engine = _engine(tmp_path, handler)
    engine.limits(email=USER)
    engine.run({}, email=USER)
    assert seen["/agent/card-review/limits"]["read"] == engine_client.REVIEW_UNARY_READ_S == 660.0
    assert seen["/agent/card-review/run"] == {"connect": engine_client.CONNECT_TIMEOUT_S, "read": 300.0,
                                              "write": engine_client.WRITE_TIMEOUT_S, "pool": engine_client.POOL_TIMEOUT_S}
    _engine(tmp_path, handler, risk_review_read_timeout_s=0).run({}, email=USER)
    assert seen["/agent/card-review/run"]["read"] is None


# ---------------------------------------------------------------- 대화 0건 · 서비스 PAT 0회(나갈 기준 3 · 사용자 결정 3)
def _recorder(log: list):
    def handler(request: httpx.Request) -> httpx.Response:
        log.append({"method": request.method, "path": request.url.path, "headers": dict(request.headers),
                    "body": json.loads(request.content) if request.content else None})
        route = request.url.path.rsplit("/", 1)[-1]
        if route == "run":
            return _stream(_sse("run_verdict_ok.sse"))
        return httpx.Response(200, json=_load({"limits": "limits_1m.json", "pack": "pack_ok.json",
                                               "plan": "plan_ok.json"}[route]))
    return handler


def test_the_four_calls_never_touch_conversations_and_carry_only_the_users_pat(tmp_path):
    log: list = []
    engine = _engine(tmp_path, _recorder(log))
    assert engine.limits(email=USER) == _load("limits_1m.json")
    assert engine.pack("mech-test-seal", email=USER) == _load("pack_ok.json")
    assert engine.plan(_load("plan_req.json"), email=USER) == _load("plan_ok.json")
    assert engine.run(_load("req_verdict_fwd.json"), email=USER) == _load("result_verdict_ok.json")

    assert [(e["method"], e["path"]) for e in log] == [
        ("GET", "/agent/card-review/limits"), ("POST", "/agent/card-review/pack"),
        ("POST", "/agent/card-review/plan"), ("POST", "/agent/card-review/run")]
    assert not any(e["path"].startswith(("/agent/conversations", "/agent/chat")) for e in log)
    assert all("conversation_id" not in (e["body"] or {}) for e in log)
    assert log[1]["body"] == {"agent_key": "mech-test-seal"} and log[2]["body"] == _load("plan_req.json")
    assert log[3]["body"] == _load("req_verdict_fwd.json")         # 앱이 본문을 고치지 않는다
    for entry in log:
        assert entry["headers"]["authorization"] == f"Bearer {USER_PAT}"
        assert not any(SVC_PAT in str(v) for v in entry["headers"].values())


@pytest.mark.parametrize("row,code", [
    (None, "pat_unavailable"),
    ("revoked", "pat_unavailable"),
    ("expiring", "credential_expired"),
    ("edge", "credential_expired"),
])
def test_without_a_usable_user_pat_nothing_is_sent_and_the_service_pat_is_not_used(tmp_path, row, code):
    """등록한 PAT 가 없거나 폐기됐거나 남은 수명이 여유(호출 벽시계 + 600초) 이하면 요청을 하나도 보내지 않는다."""
    margin = config.review_credential_margin_s(_settings(tmp_path))
    assert margin == 18000 + 600
    log: list = []
    previous = common.set_clock(lambda: 1_800_000_000)
    try:
        rows = {"revoked": _row(revoked=True), "expiring": _row(left_s=3600), "edge": _row(left_s=margin)}
        engine = _engine(tmp_path, _recorder(log))
        engine.store.rows = {USER: rows[row]} if row else {}
        for call in (lambda: engine.limits(email=USER), lambda: engine.pack("k", email=USER),
                     lambda: engine.plan({}, email=USER), lambda: engine.run({}, email=USER)):
            exc = _raised(call)
            assert isinstance(exc, PatUnavailable) and exc.code == code
            assert engine_client.review_outcome(exc).hold_code == "credential"
        assert "서비스 계정으로 내려가지 않습니다" in str(exc)
    finally:
        common.set_clock(previous)
    assert log == []


def test_one_second_past_the_margin_is_enough(tmp_path):
    margin = config.review_credential_margin_s(_settings(tmp_path))
    log: list = []
    previous = common.set_clock(lambda: 1_800_000_000)
    try:
        _engine(tmp_path, _recorder(log), row=_row(left_s=margin + 1)).limits(email=USER)
    finally:
        common.set_clock(previous)
    assert [e["headers"]["authorization"] for e in log] == [f"Bearer {USER_PAT}"]


# ---------------------------------------------------------------- plan 의 pair_over · health · 진행 신호
def test_a_plan_without_pair_over_is_an_outdated_engine(tmp_path):
    assert _engine(tmp_path, lambda r: httpx.Response(200, json=_load("plan_pair_over.json"))).plan(
        _load("plan_pair_over_req.json"), email=USER)["pair_over"] == _load("plan_pair_over.json")["pair_over"]
    old = {k: v for k, v in _load("plan_ok.json").items() if k != "pair_over"}
    exc = _raised(_engine(tmp_path, lambda r: httpx.Response(200, json=old)).plan, {}, email=USER)
    assert isinstance(exc, EngineRejected) and exc.code == "agent_outdated"
    assert engine_client.review_outcome(exc).hold_code == "agent_outdated"


HEALTH = {"model": "glm", "provider": "openai", "vllm": "http://llm.test:8000/v1", "engine_rev": "e1",
          "review_active": 3, "capabilities": ["card_review"],
          "card_review": {"rev": "cr-1", "limit": 2, "limit_reason": "delib", "active": 3, "request_worst_s": 10824}}


def test_health_adds_the_review_gate_and_keeps_the_panel_fields(tmp_path):
    def handler(info):
        return lambda request: httpx.Response(200, json=info)

    review = _engine(tmp_path, handler(HEALTH)).health()
    panel = engine_client.PortalPanelEngine(_Store(), _settings(tmp_path),
                                            transport=httpx.MockTransport(handler(HEALTH))).health()
    assert {k: v for k, v in review.items() if k != "card_review"} == panel
    assert review["card_review"] == {"capable": True, "active": 3, "limit": 2, "limit_reason": "delib",
                                     "request_worst_s": 10824, "error": None}
    old = _engine(tmp_path, handler({"model": "glm"})).health()["card_review"]
    assert old == {"capable": False, "active": None, "limit": None, "limit_reason": None, "request_worst_s": None,
                   "error": None}
    broken = {"model": "glm", "review_active": 0, "capabilities": [], "card_review": {"error": "ImportError: x"}}
    assert _engine(tmp_path, handler(broken)).health()["card_review"]["error"] == "ImportError: x"


def test_progress_reports_the_attempt_and_counts_pings(tmp_path):
    body = (b'event: status\ndata: {"step": "attempt", "n": 1}\n\n'
            b'event: ping\ndata: {"idle_s": 15, "ts": 1}\n\n'
            b'event: status\ndata: {"step": "attempt", "n": 2}\n\n') + _sse("run_verdict_solo.sse").split(b"\n\n", 1)[1]
    seen: list = []
    _engine(tmp_path, lambda r: _stream(body)).run({}, email=USER, on_progress=seen.append)
    assert [s["last_step"] for s in seen][:3] == ["attempt 1", "attempt 1", "attempt 2"]
    assert seen[-1]["frames"] == len(seen) and seen[-1]["last_step"] == "attempt 2"


def test_build_review_engine_is_the_portal_client():
    engine = engine_client.build_review_engine(None, config.settings)
    assert type(engine) is engine_client.PortalReviewEngine and engine.transport is None
