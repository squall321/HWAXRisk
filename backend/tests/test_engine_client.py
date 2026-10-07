# engine_client 배선 검사 — SSE 프레임 파싱·좌석 귀속 입력 조립·자격 순서((b)→(a))·429/연결오류 분기(전부 MockTransport, 실 LLM 호출 없음)
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app import config, engine_client, identity

def _enc(pat: str) -> str:
    """저장 열 portal_pat_enc 는 Fernet 암호문이다(plan §8.2.7) — 픽스처도 같은 형식으로 넣는다."""
    return identity.encrypt_pat(pat).decode("ascii")

from app.runner import EngineBusy, EngineError, EngineStreamLost

# agent-server 실제 프레임 규약 — `event: <name>\ndata: <json>\n\n`(deliberation.py `_sse`/`_delib`).
STREAM = (
    'event: delib\ndata: {"kind": "personas", "personas": [{"key": "xd-a0", "origin": "primary"}, '
    '{"key": "delib-baseline-defender", "origin": "counter"}]}\n\n'
    'event: status\ndata: {"step": "xd-a0 조회: list_interfaces", "tool": "list_interfaces"}\n\n'
    'event: delib\ndata: {"kind": "evidence", "source": "xd-a0 · list_interfaces", "text": "…", "included": true}\n\n'
    'event: delib\ndata: {"kind": "turn", "round": 1, "persona": "xd-a0", "say": "간극이 좁다", "stance": "oppose"}\n\n'
    'event: warning\ndata: {"code": "credential_degraded"}\n\n'
    'event: delib\ndata: {"kind": "decision", "text": "결정문 본문"}\n\n'
    'event: delib\ndata: {"kind": "outcome", "report_id": 77, "tally": {"agree": 1, "total": 1}}\n\n'
    'event: result\ndata: {"type": "text", "content": "전문"}\n\n'
    "event: done\ndata: {}\n\n"
)


def _settings(tmp_path, **limits):
    return SimpleNamespace(data_dir=tmp_path, portal_base="http://portal.test",
                           agent_url="http://agent.test", **limits)


class _Store:
    """_user_credentials 만 흉내 내는 최소 저장소."""

    def __init__(self, row=None):
        self.row = row

    def get_credential(self, owner_sub):
        return self.row


def test_parse_sse_splits_event_and_json():
    frames = list(engine_client.parse_sse(STREAM.splitlines()))
    assert [name for name, _ in frames][:3] == ["delib", "status", "delib"]
    assert frames[0][1]["kind"] == "personas"


def test_collect_stream_builds_runner_contract():
    result = engine_client.collect_stream(engine_client.parse_sse(STREAM.splitlines()))
    assert result["decision_text"] == "결정문 본문"
    assert result["report_id"] == 77
    assert result["pat_degraded"] is True
    assert result["turns"] == [{"round": 1, "persona": "xd-a0", "say": "간극이 좁다",
                                "stance": "oppose", "position": None}]
    kinds = [e["kind"] for e in result["events"]]
    assert kinds == ["personas", "status", "evidence", "turn", "warning"]
    # 좌석 귀속(runner.attribute_events)이 그대로 먹는 모양이어야 한다.
    from app.runner import attribute_events

    attribution = attribute_events(result["events"], ["xd-a0"])
    assert attribution["seats"]["xd-a0"] == {"tool_calls_n": 1, "tool_calls_ok": 1, "used_tool": True,
                                             "turns_n": 1, "tool_calls": [{"tool": "list_interfaces",
                                                                           "activity_idx": 0}]}
    assert attribution["extra_seats"] == []


def test_collect_stream_keeps_what_the_engine_says_it_withheld():
    """엔진이 '좌석에 주지 않았다' 고 알린 카드(evidence.included=false)는 사유 문장까지 남겨 러너가 옮겨 적는다."""
    from app.runner import withheld_by_engine

    notice = "근거 12건 중 뒤쪽 10건은 예산(2,000자)을 넘겨 좌석에 주지 않았다."
    stream = (
        'event: delib\ndata: {"kind": "evidence", "source": "챗 정리 · rr_scope", "text": "E0 본문", "included": true}\n\n'
        'event: delib\ndata: {"kind": "evidence", "source": "사전 근거 예산 초과", "text": "%s", "included": false}\n\n'
        'event: delib\ndata: {"kind": "evidence", "source": "xd-a0 · 자유 조회 실패", "text": "timeout", "included": false}\n\n'
        'event: delib\ndata: {"kind": "decision", "text": "결정문"}\n\n'
        "event: done\ndata: {}\n\n"
    ) % notice
    events = engine_client.collect_stream(engine_client.parse_sse(stream.splitlines()))["events"]

    # 좌석 귀속 카드(`<key> · …`)는 빼고, 엔진이 패널 전체에 대해 알린 것만 고른다.
    assert withheld_by_engine(events) == [f"사전 근거 예산 초과 — {notice}"]
    # 좌석에 실린 근거의 본문은 싣지 않는다 — events[] 는 압축 로그다.
    assert events[0] == {"kind": "evidence", "source": "챗 정리 · rr_scope", "included": True}


def test_collect_stream_raises_on_error_frame():
    stream = 'event: error\ndata: {"code": "gateway_unavailable", "message": "게이트웨이 불통"}\n\n'
    with pytest.raises(EngineError):
        engine_client.collect_stream(engine_client.parse_sse(stream.splitlines()))


def _engine(tmp_path, handler, store=None, **limits):
    return engine_client.PortalPanelEngine(store or _Store(), _settings(tmp_path, **limits),
                                           transport=httpx.MockTransport(handler))


def _service_pat(tmp_path) -> None:
    (tmp_path / "secrets.env").write_text("HWAXRISK_PORTAL_PAT=svc-pat\n", encoding="utf-8")
    (tmp_path / "secrets.env").chmod(0o600)


def test_run_posts_deliberation_trigger_and_returns_contract(tmp_path):
    (tmp_path / "secrets.env").write_text("HWAXRISK_PORTAL_PAT=svc-pat\n", encoding="utf-8")
    (tmp_path / "secrets.env").chmod(0o600)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = json.loads(request.content.decode())
        seen[request.url.path + ":auth"] = request.headers.get("authorization")
        if request.url.path == "/agent/conversations":
            return httpx.Response(200, json={"id": "conv-1"})
        return httpx.Response(200, text=STREAM, headers={"content-type": "text/event-stream"})

    result = _engine(tmp_path, handler).run({"question": "질문", "rounds": 3, "personas": []})
    assert seen["/agent/chat"]["message"].startswith(engine_client.DELIBERATE_TRIGGER)
    assert seen["/agent/chat"]["conversation_id"] == "conv-1"
    assert "question" not in seen["/agent/chat"]["delib_opts"]     # question 은 message 로 간다
    assert seen["/agent/chat:auth"] == "Bearer svc-pat"
    assert result["conv_id"] == "conv-1"
    assert result["credential"] == "service"
    assert result["call_path"] == "portal"
    assert result["decision_text"] == "결정문 본문"


def test_run_prefers_owner_pat_over_service(tmp_path):
    (tmp_path / "secrets.env").write_text("HWAXRISK_PORTAL_PAT=svc-pat\n", encoding="utf-8")
    (tmp_path / "secrets.env").chmod(0o600)
    from app.common import now_epoch

    store = _Store({"portal_pat": _enc("owner-pat"), "pat_email": "me@example.com",
                    "pat_groups_json": '["g1"]', "pat_exp": now_epoch() + 86400})
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = request.headers.get("authorization")
        if request.url.path == "/agent/conversations":
            return httpx.Response(404)                              # 대화 생성 실패는 비치명이다
        return httpx.Response(200, text=STREAM, headers={"content-type": "text/event-stream"})

    result = _engine(tmp_path, handler, store).run({"question": "q"}, owner_sub="me@example.com")
    assert seen["/agent/chat"] == "Bearer owner-pat"
    assert result["credential"] == "owner"
    assert result["conv_id"] is None
    assert result["call_groups"] == ["g1"]


def test_run_without_any_credential_raises_pat_unavailable(tmp_path):
    engine = _engine(tmp_path, lambda request: httpx.Response(200, text=""))
    with pytest.raises(engine_client.PatUnavailable):
        engine.run({"question": "q"})


def test_run_maps_429_to_engine_busy_and_connect_error_to_engine_error(tmp_path):
    (tmp_path / "secrets.env").write_text("HWAXRISK_PORTAL_PAT=svc-pat\n", encoding="utf-8")
    (tmp_path / "secrets.env").chmod(0o600)

    def busy(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agent/conversations":
            return httpx.Response(200, json={"id": "c"})
        return httpx.Response(429, text="too many")

    with pytest.raises(EngineBusy):
        _engine(tmp_path, busy).run({"question": "q"})

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(EngineError):
        _engine(tmp_path, broken).run({"question": "q"})


def test_run_cuts_a_stream_that_outlives_the_panel_wall_clock(tmp_path):
    """줄이 계속 와도 패널 벽시계(plan §6.10.2)를 넘기면 끊는다 — 읽기 타임아웃은 줄 사이 침묵만 잰다.

    엔진의 `timeout_s` 는 LLM 호출 한 번의 타임아웃이라 패널 전체를 재 주는 쪽이 없다. 앱이 재지 않으면
    상태 줄만 계속 보내는 심의 하나가 러너 자리를 끝없이 붙든다. 벽시계는 12시간이다 — 40분(2400초)이던 동안
    20석 안팎 패널은 공유 LLM 에 줄만 서다가 잘렸다.
    """
    from app import common

    _service_pat(tmp_path)
    wall_s = config.panel_timeout_s(_settings(tmp_path))
    assert wall_s == config.DEFAULT_PANEL_TIMEOUT_S == 43200
    now = {"t": common.now_epoch()}
    sent: list[str] = []

    def stream(elapsed: int):
        def frames():
            yield 'event: status\ndata: {"step": "시작"}\n\n'.encode()
            now["t"] += elapsed
            sent.append("late")
            yield 'event: delib\ndata: {"kind": "decision", "text": "결정문"}\n\n'.encode()
            sent.append("end")
            yield b"event: done\ndata: {}\n\n"
        return frames()

    def handler_for(elapsed: int):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/agent/conversations":
                return httpx.Response(200, json={"id": "c"})
            return httpx.Response(200, content=stream(elapsed), headers={"content-type": "text/event-stream"})
        return handler

    previous = common.set_clock(lambda: now["t"])
    try:
        # 상한 안에서 끝난 스트림은 그대로 받는다(경계값 포함) — 종전 상한 2400초를 한참 넘긴 것도 받는다.
        inside = _engine(tmp_path, handler_for(wall_s)).run({"question": "q"})
        assert inside["decision_text"] == "결정문"
        sent.clear()
        with pytest.raises(EngineStreamLost) as lost:
            _engine(tmp_path, handler_for(wall_s + 1)).run({"question": "q"})
        # 상한을 넘긴 뒤의 줄은 읽지 않는다 — 끝까지 받고 나서 버리는 것이 아니다.
        assert sent == ["late"]
        # 문구가 값·손잡이·경과·마지막 단계와, 엔진에서 계속 돌 수 있는 그 심의의 대화를 말한다.
        assert lost.value.code == "panel_timeout" and lost.value.conv_id == "c"
        assert str(lost.value) == (
            "panel_timeout: 패널이 43200초(HWAXRISK_PANEL_TIMEOUT_S)를 넘겼다 — 경과 43201초, 마지막 단계 시작."
            " 엔진 쪽 심의는 계속 돌 수 있다(conv_id=c)")

        # 손잡이를 내리면 그 값에서 끊고, 0 이면 재지 않는다.
        with pytest.raises(EngineStreamLost, match=r"패널이 100초\(HWAXRISK_PANEL_TIMEOUT_S\)"):
            _engine(tmp_path, handler_for(101), risk_panel_timeout_s=100).run({"question": "q"})
        unbounded = _engine(tmp_path, handler_for(30 * 86400), risk_panel_timeout_s=0).run({"question": "q"})
        assert unbounded["decision_text"] == "결정문"
    finally:
        common.set_clock(previous)


def test_stream_timeouts_are_a_liveness_net_not_a_per_call_guess(tmp_path):
    """스트림의 읽기 한도는 줄 사이 침묵 15시간이고 쓰기·풀은 그것을 물려받지 않는다.

    종전 값은 '엔진 호출당 타임아웃 1800 + 60' = 1860초였다 — LLM 시도 한 번만 가정한 값이라 엔진이 재시도하거나
    박스 한도를 올리면 건강한 패널을 끊었다. 침묵 한도 셋(포털 46800 < nginx 50400 < 여기) 중 가장 바깥이다.
    """
    _service_pat(tmp_path)
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen[request.url.path] = dict(request.extensions["timeout"])
        if request.url.path == "/agent/conversations":
            return httpx.Response(200, json={"id": "c"})
        return httpx.Response(200, text=STREAM, headers={"content-type": "text/event-stream"})

    # 본문에 호출당 timeout_s 가 실려 와도 읽기 한도를 거기서 유도하지 않는다.
    _engine(tmp_path, handler).run({"question": "q", "timeout_s": 600})
    assert seen["/agent/chat"] == {"connect": 10.0, "read": 54000.0, "write": 30.0, "pool": 30.0}
    _engine(tmp_path, handler, risk_engine_read_timeout_s=7200).run({"question": "q"})
    assert seen["/agent/chat"]["read"] == 7200.0
    _engine(tmp_path, handler, risk_engine_read_timeout_s=0).run({"question": "q"})
    assert seen["/agent/chat"]["read"] is None                     # 0 = 끔


def test_a_lost_stream_is_told_apart_from_an_engine_failure(tmp_path):
    """앱이 스트림을 놓은 것(침묵·중간 절단)은 `EngineStreamLost` 로 가르고, 손잡이와 원인을 말한다.

    종전에는 전부 '포털 /agent/chat 호출 실패(ReadTimeout)' 한 줄이었다 — 값도 손잡이도 없고, 엔진이 그 심의를
    계속 돌리는 경우와 연결조차 못 한 경우가 같은 말이었다.
    """
    _service_pat(tmp_path)

    def chat(body):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/agent/conversations":
                return httpx.Response(200, json={"id": "conv-9"})
            return httpx.Response(200, content=body(request), headers={"content-type": "text/event-stream"})
        return handler

    def silent(request):
        yield 'event: status\ndata: {"step": "1라운드"}\n\n'.encode()
        raise httpx.ReadTimeout("idle", request=request)

    with pytest.raises(EngineStreamLost) as lost:
        _engine(tmp_path, chat(silent)).run({"question": "q"})
    assert lost.value.code == "engine_silent" and lost.value.conv_id == "conv-9"
    assert "포털 스트림이 54000초 동안 조용했다(HWAXRISK_ENGINE_READ_TIMEOUT_S)" in str(lost.value)
    assert "마지막 단계 1라운드" in str(lost.value) and "conv_id=conv-9" in str(lost.value)

    def cut(request):
        yield 'event: status\ndata: {"step": "2라운드"}\n\n'.encode()
        raise httpx.RemoteProtocolError("peer closed connection", request=request)

    with pytest.raises(EngineStreamLost) as lost:
        _engine(tmp_path, chat(cut)).run({"question": "q"})
    assert lost.value.code == "engine_stream_cut"
    assert "NGINX_AGENT_READ_TIMEOUT 또는 포털·에이전트 서버 재기동" in str(lost.value)

    # 포털 릴레이가 제 침묵 한도로 구독을 끊으며 보내는 error 프레임도 같은 사정이다(엔진 실패가 아니다).
    idle = ('event: error\ndata: {"code": "agent_stream_idle", "message": "에이전트 서버가 46800초 동안 조용했다"}\n\n'
            "event: done\ndata: {}\n\n")
    with pytest.raises(EngineStreamLost) as lost:
        _engine(tmp_path, chat(lambda request: idle.encode())).run({"question": "q"})
    assert lost.value.code == "engine_silent" and "agent_stream_idle: 에이전트 서버가 46800초" in str(lost.value)

    # 응답이 흐르기 전의 실패는 엔진까지 가지 못한 것이다 — 놓친 스트림이 아니라 엔진 호출 실패다.
    def refused(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agent/conversations":
            return httpx.Response(200, json={"id": "c"})
        raise httpx.RemoteProtocolError("Server disconnected without sending a response", request=request)

    with pytest.raises(EngineError) as failed:
        _engine(tmp_path, refused).run({"question": "q"})
    assert not isinstance(failed.value, EngineStreamLost)
    # 엔진이 알린 다른 error 프레임도 그대로 엔진 실패다.
    other = 'event: error\ndata: {"code": "gateway_unavailable", "message": "게이트웨이 불통"}\n\n'
    with pytest.raises(EngineError) as failed:
        _engine(tmp_path, chat(lambda request: other.encode())).run({"question": "q"})
    assert not isinstance(failed.value, EngineStreamLost)


PING = 'event: ping\ndata: {"idle_s": 15, "ts": 1}\n\n'


def test_heartbeat_pings_do_not_change_the_result(tmp_path):
    """엔진이 15초마다 흘리는 `event: ping` 이 섞여도 결과는 같다 — events[] 400칸을 먹지 않는다.

    침묵 한도 셋이 살아 있는 심의를 끊지 않는 것은 이 ping 덕이다. 이름이 status 였다면 12시간 패널의 ping
    2,880개가 events[] 를 채워 좌석 귀속에 쓸 진짜 이벤트가 밀려났다.
    """
    frames = STREAM.split("\n\n")
    with_pings = PING + "".join(f"{frame}\n\n{PING * 3}" for frame in frames if frame)
    plain = engine_client.collect_stream(engine_client.parse_sse(STREAM.splitlines()))
    assert engine_client.collect_stream(engine_client.parse_sse(with_pings.splitlines())) == plain
    flood = PING * (engine_client.EVENTS_MAX + 10) + STREAM
    assert engine_client.collect_stream(engine_client.parse_sse(flood.splitlines())) == plain

    _service_pat(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/agent/conversations":
            return httpx.Response(200, json={"id": "c"})
        return httpx.Response(200, text=flood, headers={"content-type": "text/event-stream"})

    result = _engine(tmp_path, handler).run({"question": "q"})
    assert {k: result[k] for k in plain} == plain


def test_health_reads_agent_server(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json={"model": "glm-4.6", "vllm": "http://vllm.box:8000/v1",
                                         "version": "eng-1", "chair_rev": "c9f1"})

    info = _engine(tmp_path, handler).health()
    # chair_rev·sampling·vllm 은 엔진만 아는 값이라 그대로 옮긴다(§6.7.2 1단계).
    assert info == {"model": "glm-4.6", "provider": "vllm", "endpoint_host": "vllm.box", "engine_rev": "eng-1",
                    "chair_rev": "c9f1", "sampling": None, "vllm": "http://vllm.box:8000/v1"}


class FakePanelEngine:
    """주어진 결정문을 그대로 돌려주는 엔진(테스트·건조 실행). LLM·네트워크를 부르지 않는다."""

    def __init__(self, decision_text: str = "", *, turns: Sequence[Mapping[str, Any]] = (),
                 events: Sequence[Mapping[str, Any]] | None = None, conv_id: str | None = None,
                 report_id: Any = None, health_info: Mapping[str, Any] | None = None) -> None:
        self.decision_text = decision_text
        self.turns = [dict(t) for t in turns]
        self.events = None if events is None else [dict(e) for e in events]
        self.conv_id = conv_id
        self.report_id = report_id
        self.health_info = dict(health_info) if health_info is not None else None
        self.calls: list[dict] = []

    def run(self, delib_opts: Mapping[str, Any], *, owner_sub: str | None = None) -> dict:
        self.calls.append(dict(delib_opts))
        return {
            "decision_text": self.decision_text,
            "turns": [dict(t) for t in self.turns],
            "events": None if self.events is None else [dict(e) for e in self.events],
            "conv_id": self.conv_id,
            "report_id": self.report_id,
            "call_path": "portal",
        }

    def health(self) -> dict:
        if self.health_info is None:
            raise EngineError("health 미설정")
        return dict(self.health_info)


def test_fake_engine_returns_given_decision():
    engine = FakePanelEngine("결정문", turns=[{"persona": "xd-a0"}], conv_id="c9")
    out = engine.run({"question": "q"})
    assert out["decision_text"] == "결정문"
    assert out["conv_id"] == "c9"
    assert engine.calls == [{"question": "q"}]


# ---------------------------------------------------------------- SSE 픽스처 3종(plan §0.9 P3-4)
SSE_DIR = __import__("pathlib").Path(__file__).resolve().parent / "fixtures" / "sse"

# (파일, 좌석, 기대 tool_calls_n, tool_calls_ok, attribution_rate)
SSE_EXPECTED = [
    ("normal.sse", ["mech-a0", "sim-a0"], 2, 2, 1.0),
    ("no_tool.sse", ["mech-a0"], 0, 0, None),
]


def _stream(name: str) -> list[str]:
    return (SSE_DIR / name).read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("name,seats,calls_n,calls_ok,rate", SSE_EXPECTED, ids=[c[0] for c in SSE_EXPECTED])
def test_sse_fixtures_match_the_expected_attribution_table(name, seats, calls_n, calls_ok, rate):
    """픽스처 스트림 → parse_sse → collect_stream → attribute_events 가 기대 표와 같다."""
    from app.runner import attribute_events

    result = engine_client.collect_stream(engine_client.parse_sse(_stream(name)))
    attribution = attribute_events(result["events"], seats)
    assert sum(attribution["seats"][k]["tool_calls_n"] for k in seats) == calls_n
    assert sum(attribution["seats"][k]["tool_calls_ok"] for k in seats) == calls_ok
    assert attribution["attribution_rate"] == rate
    assert result["decision_text"]


def test_error_stream_fixture_raises_engine_error():
    with pytest.raises(EngineError):
        engine_client.collect_stream(engine_client.parse_sse(_stream("error.sse")))


def test_events_replay_path_matches_the_direct_sse_path():
    """같은 스트림의 events[] 를 재주입해도 귀속 수치가 같고 0.95 이상이다(plan §6.7.2 7단계)."""
    from app.runner import attribute_events

    seats = ["mech-a0", "sim-a0"]
    direct = engine_client.collect_stream(engine_client.parse_sse(_stream("normal.sse")))
    live = attribute_events(direct["events"], seats)
    # events[] 는 그대로 직렬화·역직렬화되어 POST /panels/{id}/complete 로 다시 들어온다.
    replayed = attribute_events(json.loads(json.dumps(direct["events"])), seats)
    assert replayed == live
    assert live["attribution_rate"] >= 0.95
