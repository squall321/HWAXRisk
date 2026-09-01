# FastMCP 도구 7종(plan §0.5.2) 이름·시그니처 고정 · 없는 id 는 예외 대신 오류 dict · tier A 는 웹 전용 + 이식된 exact Route('/mcp')(initialize·307 아님·HTTP tools/list 7종)
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
    "risk_add_finding",
]
# 도구별 대표 인자와, 빈 원장에서 기대하는 오류 코드(없으면 None = 정상 응답).
# 읽기 4종은 범위 밖 id 의 존재를 숨겨 not_visible 이고, 브리프는 caller 가 아니라 brief_token 대조다(§8.2.5).
CALLS = [
    ("risk_get_snapshot", {"snapshot_id": "s1", "part": "ir"}, "not_visible"),
    ("risk_get_diff", {"diff_id": "d1", "part": "summary"}, "not_visible"),
    ("risk_get_registry", {"target_key": "snap:s1"}, "not_visible"),
    ("risk_claims_for_ref", {"ref": "e:0123456789ab"}, None),
    ("risk_get_brief", {"target_key": "snap:s1", "brief_token": "nope"}, "brief_token_invalid"),
    ("risk_submit_panel_result", {"panel_id": "p1", "engine": "mcp", "decision_text": "…", "turns": [],
                                  "report_id": None, "actor": "someone@example.com"}, "E404"),
    ("risk_add_finding", {"target_key": "diff:d1", "claim": "간극이 좁다",
                          "cites": [{"ref": "p:0123456789ab", "quote": "«PLATE_1»"}],
                          "actor": "someone@example.com"}, "E404"),
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


def test_seven_tools_registered_in_order():
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
    # 읽기 4종에는 actor 가 없다 — 범위는 도달한 Authorization 이 정하고 자칭 문자열은 신원이 아니다(§8.2.5).
    assert set(props("risk_get_snapshot")) == {"snapshot_id", "part"}
    assert set(props("risk_get_diff")) == {"diff_id", "part"}
    assert set(props("risk_get_registry")) == {"target_key", "status", "severity", "domain"}
    assert set(props("risk_claims_for_ref")) == {"ref"}
    assert set(props("risk_get_brief")) == {"target_key", "brief_token", "tier"}
    assert props("risk_get_brief")["tier"]["default"] == "B"
    assert set(tools["risk_get_brief"].inputSchema["required"]) == {"target_key", "brief_token"}
    for name in ("risk_get_snapshot", "risk_get_diff", "risk_get_registry", "risk_claims_for_ref",
                 "risk_get_brief"):
        assert "actor" not in set(props(name))
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
    assert srv.risk_get_brief(target_key="snap:s1", brief_token="t", tier="A") == {"error": "tier_a_web_only"}


def _seed_private_target(store, monkeypatch):
    """과제 1건(기본값 mcp_visibility='private') + 스냅샷 + 타깃."""
    import json as _json

    from app import common, routes

    monkeypatch.setattr(routes, "get_store", lambda: store)
    now = common.now_epoch()
    store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
        " VALUES ('p9', 'owner@a', 'PRJ-9', '비공개', ?, ?)", (now, now))
    store.execute(
        "INSERT INTO rr_snapshots(id, owner_sub, project_id, ir_version, ir_hash, ir_json, source_ids_json,"
        " kinds_json, node_count, edge_count, created_at)"
        " VALUES ('s9', 'owner@a', 'p9', '1.0', 'h9', '{}', '[]', ?, 0, 0, ?)",
        (_json.dumps(["mcad"]), now))
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, level,"
        " external_sync_json, created_at, updated_at) VALUES ('snap:s9', 'owner@a', 'snap', 's9', 'p9', 'h9',"
        " 'C0', '{}', ?, ?)", (now, now))


def test_read_tools_hide_projects_outside_the_caller_scope(risk_store, monkeypatch):
    """기본값 private 과제는 게이트웨이 경유(service) caller 에게 not_visible 이다(plan §5.1 원칙 9·§8.2.5)."""
    _seed_private_target(risk_store, monkeypatch)

    assert srv.risk_get_snapshot("s9", "ir")["error"] == "not_visible"
    assert srv.risk_get_registry("snap:s9")["error"] == "not_visible"
    assert srv.risk_claims_for_ref("e:0123456789ab")["claims"] == []
    # 존재를 숨긴 만큼 지표가 센다(§8.2.5 ③).
    row = risk_store.query_one(
        "SELECT value FROM rr_metrics WHERE dimension = 'global' AND metric = 'mcp_not_visible'")
    assert row is not None and row["value"] == 2
    # 편성 부작용도 없다 — planned 패널이 만들어지지 않는다.
    assert risk_store.query("SELECT id FROM rr_panels") == []


def test_org_visibility_opens_the_same_ids(risk_store, monkeypatch):
    """소유자가 mcp_visibility='org' 로 토글하면 같은 id 가 열린다(§5.1 원칙 9)."""
    _seed_private_target(risk_store, monkeypatch)
    risk_store.execute("UPDATE rr_projects SET mcp_visibility = 'org' WHERE id = 'p9'")

    assert srv.risk_get_snapshot("s9", "ir").get("error") != "not_visible"
    assert srv.risk_get_registry("snap:s9").get("error") != "not_visible"


def test_get_brief_needs_a_matching_unexpired_token(risk_store, monkeypatch):
    """brief_token 은 없거나·다르거나·만료면 brief_token_invalid 이고 맞으면 그 패널 브리프가 열린다(§8.2.5)."""
    from app import common, routes

    _seed_private_target(risk_store, monkeypatch)
    now = common.now_epoch()
    risk_store.execute(
        "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, tier, seats_json, rounds, status, created_at)"
        " VALUES ('pan9', 'snap:s9', 'owner@a', 1, 'B', '[]', 2, 'planned', ?)", (now,))
    token = routes.issue_brief_token(risk_store, "pan9")

    assert srv.risk_get_brief("snap:s9", "")["error"] == "brief_token_invalid"
    assert srv.risk_get_brief("snap:s9", token + "x")["error"] == "brief_token_invalid"
    assert routes.resolve_brief_token("snap:s9", token)["id"] == "pan9"
    # 만료된 토큰도 닫힌다.
    risk_store.execute("UPDATE rr_panels SET brief_token_exp = ? WHERE id = 'pan9'", (now - 1,))
    assert srv.risk_get_brief("snap:s9", token)["error"] == "brief_token_invalid"
    # 원문은 저장하지 않는다 — 해시만 남는다.
    row = risk_store.query_one("SELECT brief_token_hash FROM rr_panels WHERE id = 'pan9'")
    assert row["brief_token_hash"] == routes.brief_token_hash(token) and token not in row["brief_token_hash"]


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
    """plan §9.1 통과 기준 13 — HTTP JSON-RPC 로 initialize → notifications/initialized → tools/list(세션 헤더 재사용) 7종."""
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


# ---------------------------------------------------------------- 사람 finding 두 입구(plan §0.9 P5-10)
def test_add_finding_via_mcp_writes_the_same_row_as_rest(risk_store, monkeypatch):
    """같은 입력이면 MCP 도구와 REST 라우트가 식별자만 다른 같은 행을 만든다."""
    from app import routes
    from tests.test_project_patch import _human_body, _ident, _seeded_target

    target_key = _seeded_target(risk_store, monkeypatch)
    rest = routes.create_human_finding(target_key, _human_body(), ident=_ident("owner@example.com"))
    tool = srv.risk_add_finding(
        target_key=target_key, claim="조립 시 간극이 부족해 보인다",
        cites=[{"ref": "p:0123456789ab", "quote": "«PLATE_1»"}], actor="owner@example.com",
        direction="risk", domain="mech", mechanism="interface", mechanism_detail="clearance",
        change_kind="dimension", subject_key="sk:1", subject_names=["PLATE_1"], severity="중대",
        judgement="WARNING")
    assert "error" not in tool, tool

    cols = ("origin", "author_sub", "panel_id", "direction", "mechanism", "mechanism_detail",
            "change_kind", "subject_key", "severity", "sev3", "judgement", "cluster_key", "status")
    rows = {}
    for name, finding_id in (("rest", rest["finding_id"]), ("mcp", tool["finding_id"])):
        row = risk_store.query_one(
            f"SELECT {', '.join(cols)} FROM rr_findings WHERE finding_id = ?", (finding_id,))
        rows[name] = dict(row)
    assert rows["rest"] == rows["mcp"]
    assert rows["mcp"]["origin"] == "human" and rows["mcp"]["author_sub"] == "owner@example.com"
    assert tool["claim_uid"] != rest["claim_uid"]           # 순번만 다르다
