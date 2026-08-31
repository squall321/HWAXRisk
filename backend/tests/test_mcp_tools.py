# FastMCP 도구 3종(risk_health·risk_get_taxonomy·risk_get_meta) 등록·호출 + 이식된 exact Route('/mcp')(initialize·307 아님)
from __future__ import annotations

import asyncio
import inspect
import json
import re

import app.mcp_server as srv

TOOL_NAMES = {"risk_health", "risk_get_taxonomy", "risk_get_meta"}
_HANGUL = re.compile(r"[가-힣]")


def _call_direct(fn, **kwargs):
    """@mcp.tool() 이 돌려준 원함수를 직접 호출한다(동기·비동기 모두)."""
    result = fn(**kwargs)
    if inspect.iscoroutine(result):
        result = asyncio.run(result)
    return result


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


def test_three_tools_registered():
    tools = asyncio.run(srv.mcp.list_tools())
    assert {t.name for t in tools} == TOOL_NAMES
    for t in tools:
        assert t.description and _HANGUL.search(t.description), f"{t.name} 설명은 한국어 한 줄이어야 한다"
        assert "\n" not in t.description.strip()


def test_server_name():
    assert srv.mcp.name == "hwax-risk"


def test_risk_health(client):
    body = _call_direct(srv.risk_health)
    assert set(body) >= {"ok", "db_path", "schema_version", "tables"}
    assert body["ok"] is True and body["schema_version"] == 1
    assert {"rr_projects", "rr_sources", "rr_snapshots", "rr_snapshot_calls"} <= set(body["tables"])
    assert _call_via_mcp("risk_health")["schema_version"] == 1


def test_risk_get_taxonomy(client):
    body = _call_direct(srv.risk_get_taxonomy)
    assert body["taxonomy_version"] == "1.0"
    assert "mechanism" in body["axes"]
    assert _call_via_mcp("risk_get_taxonomy")["taxonomy_version"] == "1.0"


def test_risk_get_meta_matches_rest_without_identity(client):
    body = _call_direct(srv.risk_get_meta)
    rest = client.get("/api/meta").json()
    rest.pop("identity")
    assert "identity" not in body
    assert body == rest
    assert body["app_id"] == "hwax_risk" and body["schema_version"] == 1


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
