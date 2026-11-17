# 게이트웨이 읽기 전용 거절(GW-02) 시험 — 'read_only: <도구> — <까닭>' 글이 tool_error 낱말 뒤로 사라지지 않고 답의 refusal · 호출 행 · ECAD 보드 찾기 오류에 실린다
"""HWAXPortal docs/request-1117 GW-02(포털 몫)의 앱 쪽 덧붙임. 게이트웨이는 읽기 전용 포털 PAT 로 조회가 아닌 도구를 부르면 isError 결과의 글을
`read_only: '<도구>' — 읽기 전용 토큰(scopes 에 read 만)은 …` 로 준다(HWAXMcpGateway gateway.py `_readonly_denial`). 앱은 그 글을 잃고 'tool_error' 만
남겼다 — 이제 McpHttpClient 답의 `refusal{reason: 'read-only', tool, message}`, 캡처 호출 행의 error, ECAD 보드 찾기의 409 글 · detail 에 그대로 실린다.

  실행:  .venv/bin/python -m pytest tests/test_gateway_refusal.py
"""
from __future__ import annotations

import httpx
import pytest

from app import ra_client
from app.adapters import ecad as ecad_adapter
from app.adapters.base import CallRecorder
from app.errors import AppError

DENIAL = ("read_only: 'odbhub_find_job' — 읽기 전용 토큰(scopes 에 read 만)은 조회 도구만 부른다. 이 도구가 조회라면 운영자가 게이트웨이 "
          "read_tools.json 에 'odb-hub:find_job' 를 더하거나, 앱이 그 도구에 readOnlyHint 를 단다.")


def _gateway(text: str) -> ra_client.McpHttpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        if '"tools/call"' not in body:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
            "isError": True, "content": [{"type": "text", "text": text}]}})

    return ra_client.McpHttpClient("https://gw.test/mcp", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_the_client_keeps_the_refusal_text_and_the_tool_name():
    reply = _gateway(DENIAL).call("odbhub_find_job", {"query": "PRJ"})
    assert reply["ok"] is False and reply["error"] == "tool_error"           # 낱말로 가르는 곳은 그대로다
    assert reply["refusal"] == {"reason": "read-only", "tool": "odbhub_find_job", "message": DENIAL}
    assert ra_client.failure_text(reply) == DENIAL
    other = _gateway("unknown: odbhub_find_job").call("odbhub_find_job", {})
    assert "refusal" not in other and ra_client.failure_text(other) == "tool_error"


@pytest.mark.parametrize("text,tool", [
    ("read_only: rest_call POST — 읽기 전용 토큰(scopes 에 read 만)은 GET · HEAD 만 부른다.", "rest_call"),
    ("read_only: save_conversation — 읽기 전용 토큰(scopes 에 read 만)은 대화를 저장할 수 없다.", "save_conversation"),
])
def test_the_tool_name_is_read_from_each_refusal_shape(text, tool):
    assert ra_client.gateway_refusal(text, "called_name")["tool"] == tool
    assert ra_client.gateway_refusal("오류", "x") is None and ra_client.gateway_refusal({"read_only": 1}, "x") is None


def test_a_capture_call_row_and_the_board_search_carry_the_refusal():
    recorder = CallRecorder("cafe0000deadbeef", mcp=_gateway(DENIAL))
    got = recorder.call("mcp", "odbhub_find_job", {"query": "PRJ"}, source_kind="ecad", app_key="odb-hub")
    assert got["error"] == DENIAL and got["refusal"]["reason"] == "read-only"
    assert recorder.calls[-1]["error"] == DENIAL                             # 호출 행(rr_snapshot_calls.error)에도 그 글
    with pytest.raises(AppError) as exc:
        ecad_adapter.search_boards(_gateway(DENIAL), {"odbhub_find_job": "odb-hub"}, "PRJ", app_key="odb-hub")
    assert exc.value.code == "ecad_read_only" and exc.value.http_status == 409
    assert "read_only: 'odbhub_find_job'" in exc.value.message and exc.value.detail["refusal"]["tool"] == "odbhub_find_job"
