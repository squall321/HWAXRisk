# engine_client 배선 검사 — SSE 프레임 파싱·좌석 귀속 입력 조립·자격 순서((b)→(a))·429/연결오류 분기(전부 MockTransport, 실 LLM 호출 없음)
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app import engine_client, identity

def _enc(pat: str) -> str:
    """저장 열 portal_pat_enc 는 Fernet 암호문이다(plan §8.2.7) — 픽스처도 같은 형식으로 넣는다."""
    return identity.encrypt_pat(pat).decode("ascii")

from app.runner import EngineBusy, EngineError

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


def _settings(tmp_path):
    return SimpleNamespace(data_dir=tmp_path, portal_base="http://portal.test",
                           agent_url="http://agent.test")


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


def test_collect_stream_raises_on_error_frame():
    stream = 'event: error\ndata: {"code": "gateway_unavailable", "message": "게이트웨이 불통"}\n\n'
    with pytest.raises(EngineError):
        engine_client.collect_stream(engine_client.parse_sse(stream.splitlines()))


def _engine(tmp_path, handler, store=None):
    return engine_client.PortalPanelEngine(store or _Store(), _settings(tmp_path),
                                           transport=httpx.MockTransport(handler))


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
