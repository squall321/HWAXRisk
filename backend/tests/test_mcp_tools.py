# FastMCP 도구 6종(plan §0.5.2) 이름·시그니처 고정 · 없는 id 는 예외 대신 오류 dict · tier A 는 웹 전용 + 이식된 exact Route('/mcp')(initialize·307 아님·HTTP tools/list 6종)
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
# 도구별 대표 인자와, 빈 원장에서 기대하는 오류 코드(없으면 None = 정상 응답).
CALLS = [
    ("risk_get_snapshot", {"snapshot_id": "s1", "part": "ir", "actor": "a@x"}, "E404"),
    ("risk_get_diff", {"diff_id": "d1", "part": "summary", "actor": "a@x"}, "E404"),
    ("risk_get_registry", {"target_key": "snap:s1", "actor": "a@x"}, "E404"),
    ("risk_claims_for_ref", {"ref": "e:0123456789ab", "actor": "a@x"}, None),
    ("risk_get_brief", {"target_key": "snap:s1", "actor": "a@x"}, "E404"),
    ("risk_submit_panel_result", {"panel_id": "p1", "engine": "mcp", "decision_text": "…", "turns": [],
                                  "report_id": None, "actor": "someone@example.com"}, "E404"),
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


def test_server_name():
    assert srv.mcp.name == "hwax-risk"


def test_signatures_follow_plan():
    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    props = lambda n: tools[n].inputSchema["properties"]  # noqa: E731
    # 조회 5종에는 소유권 해석용 actor(선택)가 붙는다 — 없으면 남의 행이 그대로 나간다(§6.11).
    assert set(props("risk_get_snapshot")) == {"snapshot_id", "part", "actor"}
    assert set(props("risk_get_diff")) == {"diff_id", "part", "actor"}
    assert set(props("risk_get_registry")) == {"target_key", "status", "severity", "domain", "actor"}
    assert set(props("risk_claims_for_ref")) == {"ref", "actor"}
    assert set(props("risk_get_brief")) == {"target_key", "tier", "actor"}
    assert props("risk_get_brief")["tier"]["default"] == "B"
    for name in ("risk_get_snapshot", "risk_get_diff", "risk_get_registry", "risk_claims_for_ref",
                 "risk_get_brief"):
        assert "actor" not in set(tools[name].inputSchema.get("required") or ())
    submit = props("risk_submit_panel_result")
    assert set(submit) == {"panel_id", "engine", "decision_text", "turns", "report_id", "actor", "model"}
    assert submit["model"]["default"] is None
    # §8.2.5 표 — report_id 는 선택(`report_id?`)이다.
    assert set(tools["risk_submit_panel_result"].inputSchema["required"]) == {
        "panel_id", "engine", "decision_text", "turns", "actor"}


@pytest.mark.parametrize("name,args,error_code", CALLS, ids=[c[0] for c in CALLS])
def test_each_tool_answers_with_json_not_exception(name, args, error_code):
    """빈 원장에서도 도구는 예외를 올리지 않고 dict 를 돌려주며, MCP 경유 호출과 직접 호출이 같다."""
    direct = getattr(srv, name)(**args)
    assert isinstance(direct, dict)
    assert direct.get("error") == error_code
    assert _call_via_mcp(name, args) == direct


def test_get_brief_tier_a_is_web_only():
    """Tier A 대표 패널은 웹 러너 전용이다(plan §6.11)."""
    assert srv.risk_get_brief(target_key="snap:s1", tier="A") == {"error": "tier_a_web_only"}


def test_read_tools_without_actor_do_not_leak(risk_store, monkeypatch):
    """actor 를 해석할 수 없으면 남의 설계 데이터를 내주지 않는다(§6.11 — 미해석은 빈 결과)."""
    import json as _json

    from app import common, routes

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    now = common.now_epoch()
    risk_store.execute(
        "INSERT INTO rr_snapshots(id, owner_sub, project_id, ir_version, ir_hash, ir_json, source_ids_json,"
        " kinds_json, node_count, edge_count, created_at)"
        " VALUES ('s9', 'owner@a', 'p9', '1.0', 'h9', '{}', '[]', ?, 0, 0, ?)",
        (_json.dumps(["mcad"]), now),
    )
    risk_store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, level,"
        " external_sync_json, created_at, updated_at) VALUES ('snap:s9', 'owner@a', 'snap', 's9', 'p9', 'h9',"
        " 'C0', '{}', ?, ?)", (now, now))

    assert srv.risk_get_snapshot("s9", "ir")["error"] == "E404"          # actor 없음
    assert srv.risk_get_snapshot("s9", "ir", actor="other@b")["error"] == "E404"   # 남의 것
    assert srv.risk_get_registry("snap:s9")["error"] == "E404"
    assert srv.risk_get_registry("snap:s9", actor="other@b")["error"] == "E404"
    brief = srv.risk_get_brief("snap:s9")
    assert brief["error"] == "E404" and brief["reason"] == "caller_unresolved"
    # 편성 부작용도 없다 — planned 패널이 만들어지지 않는다.
    assert risk_store.query("SELECT id FROM rr_panels") == []


def test_tools_call_the_same_functions_as_rest():
    """MCP 도구는 REST 와 같은 함수를 부른다(파서·병합·저장은 앱 한 곳, plan §6.11)."""
    from app import routes

    assert callable(routes.snapshot_part) and callable(routes.diff_part)
    assert callable(routes.registry_payload) and callable(routes.claims_for_ref)
    assert callable(routes.brief_payload) and callable(routes.complete_panel)


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
