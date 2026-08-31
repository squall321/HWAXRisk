# FastMCP 도구 6종(plan §0.5.2) 이름 고정·각 호출이 not_implemented/ready_in 반환 + 이식된 exact Route('/mcp')(initialize·307 아님·HTTP tools/list 6종)
from __future__ import annotations

import asyncio
import json
import re

import pytest

import app.mcp_server as srv

TOOL_NAMES = [
    "risk_get_snapshot",
    "risk_get_diff",
    "risk_get_registry",
    "risk_claims_for_ref",
    "risk_get_brief",
    "risk_submit_panel_result",
]
# 도구별 대표 인자와 기대 ready_in(snapshot P1 · diff P2 · registry/claims/submit P3 · brief P5).
CALLS = [
    ("risk_get_snapshot", {"snapshot_id": "s1", "part": "ir"}, "P1"),
    ("risk_get_diff", {"diff_id": "d1", "part": "summary"}, "P2"),
    ("risk_get_registry", {"target_key": "snap:s1"}, "P3"),
    ("risk_claims_for_ref", {"ref": "e:abc"}, "P3"),
    ("risk_get_brief", {"target_key": "snap:s1"}, "P5"),
    ("risk_submit_panel_result", {"panel_id": "p1", "engine": "mcp", "decision_text": "…", "turns": [],
                                  "report_id": None, "actor": "someone@example.com"}, "P3"),
]
_HANGUL = re.compile(r"[가-힣]")


def _call_via_mcp(name: str, args: dict | None = None) -> dict:
    """FastMCP.call_tool 결과를 dict 로 정규화 — 버전에 따라 list[Content] 또는 (content, structured) 튜플."""
    res = asyncio.run(srv.mcp.call_tool(name, args or {}))
    if isinstance(res, tuple):
        content, structured = res
        if isinstance(structured, dict) and structured:
            return structured.get("result", structured)
        res = content
    if isinstance(res, dict):
        return res
    return json.loads(res[0].text)


def test_six_tools_registered_in_order():
    tools = asyncio.run(srv.mcp.list_tools())
    assert [t.name for t in tools] == TOOL_NAMES
    for t in tools:
        assert t.description and _HANGUL.search(t.description), f"{t.name} 설명은 한국어 한 줄이어야 한다"
        assert "\n" not in t.description.strip()
        assert "ready_in" in t.description


def test_server_name():
    assert srv.mcp.name == "hwax-risk"


def test_signatures_follow_plan():
    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    props = lambda n: tools[n].inputSchema["properties"]  # noqa: E731
    assert set(props("risk_get_snapshot")) == {"snapshot_id", "part"}
    assert set(props("risk_get_diff")) == {"diff_id", "part"}
    assert set(props("risk_get_registry")) == {"target_key"}
    assert set(props("risk_claims_for_ref")) == {"ref"}
    assert set(props("risk_get_brief")) == {"target_key", "tier"}
    assert props("risk_get_brief")["tier"]["default"] == "B"
    submit = props("risk_submit_panel_result")
    assert set(submit) == {"panel_id", "engine", "decision_text", "turns", "report_id", "actor", "model"}
    assert submit["model"]["default"] is None
    assert set(tools["risk_submit_panel_result"].inputSchema["required"]) == {
        "panel_id", "engine", "decision_text", "turns", "report_id", "actor"}


@pytest.mark.parametrize("name,args,ready_in", CALLS, ids=[c[0] for c in CALLS])
def test_each_tool_is_not_implemented(name, args, ready_in):
    direct = getattr(srv, name)(**args)
    assert direct == {"error": "not_implemented", "ready_in": ready_in}
    assert _call_via_mcp(name, args) == direct


def test_old_p0_tools_are_gone():
    names = {t.name for t in asyncio.run(srv.mcp.list_tools())}
    assert not names & {"risk_health", "risk_get_taxonomy", "risk_get_meta"}


def test_mcp_route_is_exact_not_mount():
    """Route('/mcp') 이식 검증 — app.routes 에 path=='/mcp' 인 Route 가 있고 Mount('/mcp') 는 없다."""
    from starlette.routing import Mount, Route

    from app.main import app

    exact = [r for r in app.routes if isinstance(r, Route) and r.path == "/mcp"]
    assert len(exact) == 1
    assert not [r for r in app.routes if isinstance(r, Mount) and r.path == "/mcp"]


def test_mcp_initialize_at_exact_mcp_without_redirect(client):
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                         "clientInfo": {"name": "pytest", "version": "0"}}},
        headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
    )
    assert r.status_code == 200  # 307 이 아니어야 한다(Mount 였다면 /mcp → /mcp/ 리다이렉트).
    assert r.headers.get("mcp-session-id")
    assert '"protocolVersion"' in r.text


def _jsonrpc_result(r) -> dict:
    """POST /mcp 응답(application/json 또는 text/event-stream) 에서 JSON-RPC result 를 꺼낸다."""
    if r.headers.get("content-type", "").startswith("text/event-stream"):
        payloads = [json.loads(line[5:].strip()) for line in r.text.splitlines() if line.startswith("data:")]
        msg = next(m for m in payloads if "result" in m or "error" in m)
    else:
        msg = r.json()
    assert "error" not in msg, msg
    return msg["result"]


def test_http_tools_list_over_mcp_route(client):
    """plan §9.1 통과 기준 13 — HTTP JSON-RPC 로 initialize → notifications/initialized → tools/list(세션 헤더 재사용) 6종."""
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                         "clientInfo": {"name": "pytest", "version": "0"}}},
        headers=headers,
    )
    assert r.status_code == 200
    session_id = r.headers.get("mcp-session-id")
    assert session_id
    headers["mcp-session-id"] = session_id

    r = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
    assert r.status_code in (200, 202)

    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=headers)
    assert r.status_code == 200
    result = _jsonrpc_result(r)
    assert [t["name"] for t in result["tools"]] == TOOL_NAMES
