# E10 필드 근거 호출의 벽시계 기한(HWAXRISK_FIELD_TIMEOUT_S) — ping 을 흘리는 게이트웨이에서도 기한이 걸리는지 가짜 시계로 묻는다
"""왜 — httpx 의 한도는 바이트 사이 침묵만 잰다. 게이트웨이는 도구가 도는 동안 15초마다 ping 주석 줄을 흘리므로 15초를
넘는 한도는 호출 길이를 자르지 못하고(실측 — 한도 20초로 34초짜리 호출이 그대로 돌아왔다), 15초보다 작은 한도만 실제
상한이다. 종전 값은 리터럴 5초였다 — 패널 시작 때의 문헌·VOC 조회가 부하 걸린 박스에서 5초를 넘기면 그 줄이 빠진 채
몇 시간짜리 패널이 돌았고, 손잡이가 없어 올릴 길도 없었다.

시험은 실제로 기다리지 않는다. 가짜 게이트웨이의 응답 본문이 ping 을 낼 때마다 가짜 시계를 밀고, 클라이언트는 그 시계를
읽는다(`ra_client.time`).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app import brief, config, field_source, ra_client, render
from app.adapters import registry as adapters_registry
from app.ra_client import McpHttpClient

GATEWAY = "https://gw.test/mcp"
ISSUES = {"issues": [{"issue_key": "ISS-1", "category": "파손/깨짐", "n": 7, "text": "낙하 후 힌지 파손"}]}
PING_S = 15.0                       # 게이트웨이(sse_starlette)가 주석 줄을 흘리는 간격


class _Clock:
    """`ra_client.time` 을 대신한다 — monotonic 은 가짜 게이트웨이가 민다."""

    def __init__(self) -> None:
        self.now = 5000.0

    def monotonic(self) -> float:
        return self.now


class _ToolReply(httpx.SyncByteStream):
    """tools/call 응답 본문 — 도구가 `answer_after` 초에 끝난다. 그때까지 `ping_s` 마다 주석 줄을 흘린다(None 이면 조용하다).

    조용한 채로 요청의 읽기 한도를 넘기면 전송 계층이 하듯 `httpx.ReadTimeout` 을 올린다.
    """

    def __init__(self, clock: _Clock, rpc_id: int, *, answer_after: float, ping_s: float | None,
                 read_timeout: float | None) -> None:
        self.clock, self.rpc_id = clock, rpc_id
        self.answer_after, self.ping_s, self.read_timeout = answer_after, ping_s, read_timeout
        self.answered = False
        self.closed = False

    def __iter__(self):
        waited = 0.0
        while self.ping_s is not None and waited + self.ping_s < self.answer_after:
            waited += self.ping_s
            self.clock.now += self.ping_s
            yield b": ping - 2026-10-08 00:00:00+00:00\r\n\r\n"
        gap = self.answer_after - waited
        if self.read_timeout is not None and gap > self.read_timeout:
            self.clock.now += self.read_timeout
            raise httpx.ReadTimeout("idle")
        self.clock.now += gap
        self.answered = True
        message = {"jsonrpc": "2.0", "id": self.rpc_id,
                   "result": {"content": [{"type": "text", "text": json.dumps(ISSUES, ensure_ascii=False)}],
                              "isError": False}}
        yield b"event: message\r\ndata: " + json.dumps(message).encode() + b"\r\n\r\n"

    def close(self) -> None:
        self.closed = True


class _Gateway:
    """MCP streamable-http 게이트웨이 흉내 — 핸드셰이크는 곧바로, 도구 응답은 `_ToolReply` 로."""

    def __init__(self, clock: _Clock, *, answer_after: float, ping_s: float | None = PING_S) -> None:
        self.clock, self.answer_after, self.ping_s = clock, answer_after, ping_s
        self.replies: list[_ToolReply] = []
        self.read_timeouts: list[float | None] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        if body["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}},
                                  headers={"mcp-session-id": "s1"})
        if body["method"] != "tools/call":
            return httpx.Response(202)
        read = request.extensions["timeout"]["read"]
        self.read_timeouts.append(read)
        self.replies.append(_ToolReply(self.clock, body["id"], answer_after=self.answer_after,
                                       ping_s=self.ping_s, read_timeout=read))
        return httpx.Response(200, stream=self.replies[-1], headers={"content-type": "text/event-stream"})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(ra_client, "time", fake)
    return fake


def test_a_deadline_cuts_a_call_that_pings_keep_alive(clock):
    """ping 이 15초마다 흐르고 도구는 34초에 답한다 — 기한 20초는 ping 한 칸 안(30초)에서 끊고, 응답을 닫는다."""
    gateway = _Gateway(clock, answer_after=34)
    mcp = McpHttpClient(GATEWAY, client=gateway.client(), timeout=20, deadline_s=20)
    started = clock.now

    reply = mcp.call("search_scholar", {"q": "thin stack"})

    assert (reply["ok"], reply["error"]) == (False, "deadline_exceeded")
    assert clock.now - started == 30                         # 20초 + 넘겨 들은 폭은 ping 한 칸(15초)을 넘지 않는다
    assert gateway.replies[0].closed and not gateway.replies[0].answered


def test_without_a_deadline_the_same_call_runs_to_its_end(clock):
    """대조군 — 기한 없이 부르면 34초짜리 답이 그대로 온다. 한도 20초(float)는 줄 사이 침묵만 재서 ping 이 되감는다."""
    gateway = _Gateway(clock, answer_after=34)
    mcp = McpHttpClient(GATEWAY, client=gateway.client(), timeout=20)
    started = clock.now

    reply = mcp.call("search_scholar", {"q": "thin stack"})

    assert reply == {"ok": True, "result": ISSUES} and clock.now - started == 34


def test_a_silent_gateway_is_cut_at_the_deadline_too(clock):
    """ping 도 없는 상대 — 침묵 한도를 남은 기한까지로 줄여 걸고, 걸리면 같은 이름(deadline_exceeded)으로 말한다."""
    gateway = _Gateway(clock, answer_after=34, ping_s=None)
    mcp = McpHttpClient(GATEWAY, client=gateway.client(), timeout=60, deadline_s=20)
    started = clock.now

    reply = mcp.call("get_top_issues", {})

    assert reply["error"] == "deadline_exceeded" and clock.now - started == 20
    assert gateway.read_timeouts == [20]                     # 침묵 한도 60초가 남은 기한 20초로 줄었다


def test_a_gateway_that_goes_silent_inside_the_deadline_is_still_a_transport_error(clock):
    """기한이 남았는데 침묵 한도에 걸린 것은 죽은 게이트웨이다 — 기한 초과와 섞지 않는다(올릴 손잡이가 다르다)."""
    gateway = _Gateway(clock, answer_after=34, ping_s=None)
    mcp = McpHttpClient(GATEWAY, client=gateway.client(), timeout=5, deadline_s=20)

    reply = mcp.call("get_top_issues", {})

    assert reply["error"] == "transport_error" and "ReadTimeout" in reply["detail"]


def test_a_seven_second_answer_now_arrives(clock):
    """종전 5초 리터럴이 버리던 호출 — 게이트웨이는 7초에 답했는데 앱이 5초에 놓았다. 20초 기한에서는 받는다."""
    gateway = _Gateway(clock, answer_after=7)
    mcp = McpHttpClient(GATEWAY, client=gateway.client(), timeout=20, deadline_s=20)

    assert mcp.call("search_scholar", {"q": "thin stack"}) == {"ok": True, "result": ISSUES}
    assert gateway.read_timeouts == [20]


def test_the_channel_takes_its_deadline_from_the_knob(monkeypatch, tmp_path):
    """from_settings 가 손잡이 값을 침묵 한도와 벽시계 기한 양쪽에 건다 — 5초 리터럴은 어디에도 없다."""
    monkeypatch.setattr(adapters_registry, "gateway_tool_names", lambda **_kw: ())
    assert config.DEFAULT_FIELD_TIMEOUT_S == 20
    # 손잡이가 없는 설정 객체(시험 대역)도 코드 기본값으로 돈다.
    bare = field_source.from_settings(SimpleNamespace(gateway_mcp=GATEWAY, data_dir=tmp_path), portal_pat="stub")
    assert (bare.timeout, bare.mcp.timeout, bare.mcp.deadline_s) == (20, 20, 20)
    tuned = field_source.from_settings(
        SimpleNamespace(gateway_mcp=GATEWAY, data_dir=tmp_path, risk_field_timeout_s=45), portal_pat="stub")
    assert (tuned.timeout, tuned.mcp.timeout, tuned.mcp.deadline_s) == (45, 45, 45)
    assert field_source.FieldSource(object()).timeout == 20
    # 아무도 읽지 않던 5초 상수들 — 남아 있으면 다음 사람이 그것을 손잡이로 믿는다.
    assert not hasattr(field_source, "FIELD_TIMEOUT_S")
    assert not hasattr(brief, "FIELD_CALL_TIMEOUT_S") and not hasattr(brief, "FIELD_REUSE_S")


def test_an_expired_lookup_names_the_limit_and_the_knob(risk_store, clock, monkeypatch, tmp_path):
    """기한을 넘긴 줄은 한도와 손잡이를 말한다 — 원장에도 그 사유로 남는다. 종전 문구에는 값도 손잡이도 없었다."""
    risk_store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, product_code, product_refs_json,"
        " predecessor_product_code, created_at, updated_at) VALUES ('P1','u@x','F7','F7','F7-2024',NULL,NULL,1,1)")
    risk_store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash,"
        " external_sync_json, created_at, updated_at) VALUES ('snap:S1','u@x','snap','S1','P1','h1','{}',1,1)")
    ctx = brief._target_context(risk_store, "snap:S1")
    monkeypatch.setattr(adapters_registry, "gateway_tool_names", lambda **_kw: ())
    gateway = _Gateway(clock, answer_after=34)
    source = field_source.from_settings(SimpleNamespace(gateway_mcp=GATEWAY, data_dir=tmp_path),
                                        portal_pat="stub", http_client=gateway.client())

    lines = brief._field_evidence_lines(risk_store, ctx, source)

    assert lines == ["[조회 불가: get_top_issues — 20초 초과(HWAXRISK_FIELD_TIMEOUT_S)]"]
    assert render.lint_text("\n".join(lines))["ok"]
    row = risk_store.query_one("SELECT ok, error FROM rr_brief_calls WHERE tool = 'get_top_issues'")
    assert (row["ok"], row["error"]) == (0, "deadline_exceeded")
