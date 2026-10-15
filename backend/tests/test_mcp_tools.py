# FastMCP 도구 이름·시그니처 고정 · 없는 id 는 예외 대신 오류 dict · tier A 는 웹 전용 + 이식된 exact Route('/mcp')(initialize·307 아님)
from __future__ import annotations

import asyncio
import json
import re

import pytest

import app.mcp_server as srv

# 발견·조회 7종(2026-09-07 추가)이 먼저 온다 — MCP 클라이언트는 id 를 모른 채 들어오므로
# risk_list_projects 가 실질적 진입점이다. 그 뒤가 원장 접점 7종(plan §0.5.2).
TOOL_NAMES = [
    "risk_list_projects",
    "risk_get_coverage",
    "risk_list_panels",
    "risk_get_panel_transcript",
    "risk_taxonomy",
    "risk_get_precedents",
    "risk_similar_projects",
    "risk_get_snapshot",
    "risk_get_diff",
    "risk_get_registry",
    "risk_claims_for_ref",
    "risk_get_brief",
    "risk_submit_panel_result",
    "risk_add_finding",
    # Claude 입구 12종(2026-10-10, PLAN M1 'Claude 입구'·D-23) — 길잡이가 먼저, 그 뒤가 웹 화면의 순서다.
    # risk_repersist_panel 은 10-11 dev 실주행에서 저장 실패를 Claude 에서 풀 수 없던 것을 메운다.
    "risk_next_step",
    "risk_create_project",
    "risk_add_source",
    "risk_capture_snapshot",
    "risk_ack_gate",
    "risk_get_sameas",
    "risk_decide_sameas",
    "risk_create_diff",
    "risk_open_target",
    "risk_start_job",
    "risk_job_action",
    "risk_repersist_panel",
    # 검토 단위 1종(재설계 M2 U5) — 카드 대조의 단위를 읽는다. 새 도구는 뒤에 붙는다(옛 도구의 이름·순서는 그대로).
    "risk_get_units",
    # 카드 대조 검토 2종(재설계 M2 S12) — 셀 격자와 전문가 보고서를 읽는다. 검토 잡은 risk_start_job(mode='reviews') 이다.
    "risk_get_cells",
    "risk_get_expert_report",
    # 쟁점·종합 보고서 2종(재설계 M3 S3-10) — 읽기 전용, 앞 목록 + 둘(29 → 31).
    "risk_get_issues",
    "risk_get_report",
]
ENTRY_TOOLS = TOOL_NAMES[TOOL_NAMES.index("risk_next_step"):TOOL_NAMES.index("risk_repersist_panel") + 1]
# 도구별 대표 인자와, 빈 원장에서 기대하는 오류 코드(없으면 None = 정상 응답).
# 읽기 4종은 범위 밖 id 의 존재를 숨겨 not_visible 이다. 브리프는 brief_token 대조이되(§8.2.5) 결과를 낼 수 있는 신원에게만
# 열려(RV-1) 요청 밖에서는 토큰을 보기 전에 delegation_required 다.
# 쓰기 도구(입구 9종 + 결과 제출·사람 finding)는 요청 밖(신원 없음)에서 전부 delegation_required 다 — 게이트웨이 위임으로
# 확인된 신원만 쓴다. 읽기 입구 둘(길잡이·same-as 표)은 unauthorized 다. 인자가 틀렸든 맞든 신원 검사가 먼저다.
CALLS = [
    # 발견·조회 — 빈 원장에서 목록은 정상 응답(빈 배열), 단일 id 는 존재를 숨긴다.
    ("risk_list_projects", {}, None),
    ("risk_taxonomy", {}, None),
    ("risk_get_coverage", {"target_key": "snap:s1"}, "not_visible"),
    ("risk_list_panels", {"target_key": "snap:s1"}, "not_visible"),
    ("risk_get_panel_transcript", {"panel_id": "p1"}, "not_visible"),
    ("risk_get_precedents", {"diff_id": "d1"}, "not_visible"),
    ("risk_similar_projects", {"project_id": "p1"}, "not_visible"),
    ("risk_get_snapshot", {"snapshot_id": "s1", "part": "ir"}, "not_visible"),
    ("risk_get_diff", {"diff_id": "d1", "part": "summary"}, "not_visible"),
    ("risk_get_registry", {"target_key": "snap:s1"}, "not_visible"),
    ("risk_get_issues", {"target_key": "snap:s1"}, "not_visible"),
    ("risk_get_report", {"target_key": "snap:s1"}, "not_visible"),
    ("risk_claims_for_ref", {"ref": "e:0123456789ab"}, None),
    ("risk_get_brief", {"target_key": "snap:s1", "brief_token": "nope"}, "delegation_required"),
    ("risk_submit_panel_result", {"panel_id": "p1", "engine": "mcp", "decision_text": "…", "turns": [],
                                  "report_id": None, "actor": "someone@example.com"}, "delegation_required"),
    ("risk_add_finding", {"target_key": "diff:d1", "claim": "간극이 좁다",
                          "cites": [{"ref": "p:0123456789ab", "quote": "«PLATE_1»"}],
                          "actor": "someone@example.com"}, "delegation_required"),
    ("risk_next_step", {}, "unauthorized"),
    ("risk_next_step", {"project_id": "p1"}, "unauthorized"),
    ("risk_create_project", {"code": "PRJ-1", "name": "과제", "classification": "internal"}, "delegation_required"),
    ("risk_add_source", {"project_id": "p1", "kind": "mcad", "ref": {"stepforge_project_id": "sf1"}},
     "delegation_required"),
    ("risk_capture_snapshot", {"project_id": "p1"}, "delegation_required"),
    ("risk_ack_gate", {"snapshot_id": "s1", "gate": "G3", "reason": "확인함"}, "delegation_required"),
    ("risk_get_sameas", {"base_snapshot_id": "s0", "target_snapshot_id": "s1"}, "unauthorized"),
    ("risk_decide_sameas", {"base_snapshot_id": "s0", "target_snapshot_id": "s1",
                            "decisions": [{"a_stable": "a", "b_stable": "b", "decision": "confirm"}]},
     "delegation_required"),
    ("risk_create_diff", {"base_snapshot_id": "s0", "target_snapshot_id": "s1"}, "delegation_required"),
    ("risk_open_target", {"kind": "diff", "ref_id": "d1", "consent": True}, "delegation_required"),
    ("risk_start_job", {"target_key": "diff:d1", "tier": "B"}, "delegation_required"),
    ("risk_job_action", {"job_id": "j1", "action": "pause"}, "delegation_required"),
    ("risk_repersist_panel", {"panel_id": "pn1"}, "delegation_required"),
    ("risk_get_units", {"target_key": "snap:s1"}, "not_visible"),
    ("risk_get_units", {"target_key": "snap:s1", "unit_id": "u-0123456789ab", "part": "lines"}, "not_visible"),
    ("risk_get_cells", {"target_key": "snap:s1"}, "not_visible"),
    ("risk_get_expert_report", {"target_key": "snap:s1", "agent_key": "mech-test-seal"}, "not_visible"),
]
_HANGUL = re.compile(r"[가-힣]")
# 인자 이름에 비밀이 오면 게이트웨이·포털 절차·클라이언트 대화 기록에 값이 남는다(작업 지시서 A-11) — 포털 절차의
# SECRET_KEY 와 같은 낱말 목록이다. 기존 risk_get_brief 의 brief_token 은 일회성 열쇠라 입구 도구에만 건다.
_SECRET_ARG = re.compile(r"token|secret|password|authorization|api_key|cookie|pat", re.I)


def _direct(name: str, args: dict) -> dict:
    """도구 함수를 직접 부른다 — 입구 도구는 async(본문을 스레드로 넘긴다)라 코루틴을 끝까지 돌린다."""
    out = getattr(srv, name)(**args)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


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


def test_tools_registered_in_order():
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
    # 상한(500·200·100) 뒤를 이어 받는 offset 은 선택 인자다(절단 전수 조사 M1).
    assert set(props("risk_get_snapshot")) == {"snapshot_id", "part", "offset"}
    # 변경 줄(part='lines')의 거름·이어 받기는 선택 인자다 — 종전 두 인자만 줘도 같은 응답이다(WP1 S14).
    assert set(props("risk_get_diff")) == {"diff_id", "part", "change_kind", "q", "offset", "limit"}
    assert set(tools["risk_get_diff"].inputSchema["required"]) == {"diff_id", "part"}
    # 등록부 — 주의 등급·단위 거름(재설계 M3 S3-10)은 선택 인자다.
    assert set(props("risk_get_registry")) == {"target_key", "status", "severity", "domain", "offset", "attention", "unit_id"}
    assert set(props("risk_claims_for_ref")) == {"ref", "offset"}
    assert set(props("risk_get_brief")) == {"target_key", "brief_token", "tier"}
    assert props("risk_get_brief")["tier"]["default"] == "B"
    assert set(tools["risk_get_brief"].inputSchema["required"]) == {"target_key", "brief_token"}
    for name in ("risk_get_snapshot", "risk_get_diff", "risk_get_registry", "risk_claims_for_ref",
                 "risk_get_brief", "risk_list_projects", "risk_get_coverage", "risk_list_panels",
                 "risk_get_panel_transcript", "risk_taxonomy", "risk_get_precedents",
                 "risk_similar_projects", "risk_get_units", "risk_get_cells", "risk_get_expert_report",
                 "risk_get_issues", "risk_get_report"):
        assert "actor" not in set(props(name))
    # 검토 단위 — 대상 하나에 목록·단위 하나를 고르고, 나머지는 offset 으로 이어 받는다.
    assert set(props("risk_get_units")) == {"target_key", "unit_id", "part", "offset"}
    assert set(tools["risk_get_units"].inputSchema["required"]) == {"target_key"}
    assert props("risk_get_units")["part"]["default"] == "manifest"
    # 카드 대조 검토 — 셀은 거름 셋과 나눠 받기, 보고서는 전문가 하나의 쪽(part 기본 summary · page 1).
    assert set(props("risk_get_cells")) == {"target_key", "agent_key", "unit_id", "state", "limit", "offset", "job_id"}
    assert set(tools["risk_get_cells"].inputSchema["required"]) == {"target_key"}
    assert (props("risk_get_cells")["limit"]["default"], props("risk_get_cells")["offset"]["default"]) == (200, 0)
    assert set(props("risk_get_expert_report")) == {"target_key", "agent_key", "part", "unit_id", "page", "version"}
    assert props("risk_get_expert_report")["version"]["default"] is None             # REST 와 같은 판 확인(R3B-13)
    assert set(tools["risk_get_expert_report"].inputSchema["required"]) == {"target_key", "agent_key"}
    assert (props("risk_get_expert_report")["part"]["default"], props("risk_get_expert_report")["page"]["default"]) == (
        "summary", 1)
    # 쟁점·종합 보고서(M3 S3-10) — 쟁점은 거름 둘과 나눠 받기, 보고서는 판의 쪽(part 기본 summary · page 1 · version 대조).
    assert set(props("risk_get_issues")) == {"target_key", "state", "p_class", "limit", "offset"}
    assert set(props("risk_get_report")) == {"target_key", "part", "version", "page"}
    assert (props("risk_get_report")["part"]["default"], props("risk_get_report")["page"]["default"]) == ("summary", 1)
    # 발견·조회는 인자가 최소여야 한다 — id 를 모르는 클라이언트가 첫 호출로 쓴다.
    assert set(props("risk_list_projects")) == set()
    assert set(props("risk_taxonomy")) == {"part", "offset"}
    # 진행판 — 검토 순서 전부(order_offset)와 좌석 행(seat_offset)은 와이어 한도 안에서 쪽으로 받는다(R3B-1).
    assert set(props("risk_get_coverage")) == {"target_key", "with_seats", "domain", "order_offset", "seat_offset"}
    assert (props("risk_get_coverage")["order_offset"]["default"], props("risk_get_coverage")["seat_offset"]["default"]) == (
        None, 0)
    assert set(props("risk_similar_projects")) == {"project_id", "k"}
    submit = props("risk_submit_panel_result")
    assert set(submit) == {"panel_id", "engine", "decision_text", "turns", "report_id", "actor", "model",
                           "evidence_omitted"}
    assert submit["model"]["default"] is None
    # 좌석에 못 간 근거 — hwax-risk-review.js 가 이 이름으로 싣는다. 선택 인자다(안 실어도 종전과 같다).
    assert submit["evidence_omitted"]["default"] is None
    # §8.2.5 표 — report_id 는 선택(`report_id?`)이다.
    assert set(tools["risk_submit_panel_result"].inputSchema["required"]) == {
        "panel_id", "engine", "decision_text", "turns", "actor"}


def test_entry_tool_signatures():
    """입구 12종 — 신원은 도달한 자격이 정하므로 actor 가 없고, 비밀(PAT·토큰)을 인자로 받지 않는다."""
    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    props = lambda n: set(tools[n].inputSchema["properties"])  # noqa: E731
    required = lambda n: set(tools[n].inputSchema.get("required") or [])  # noqa: E731
    for name in ENTRY_TOOLS:
        assert "actor" not in props(name), name
        assert not [p for p in props(name) if _SECRET_ARG.search(p)], (name, props(name))
    assert props("risk_next_step") == {"project_id"} and required("risk_next_step") == set()
    assert props("risk_create_project") == {"code", "name", "classification", "stage", "predecessor_project_id",
                                            "product_code", "adh_scope"}
    # 등급은 반출 경계라 사람이 고른다 — 스키마가 필수로 못박아 Claude 가 빼먹지 못한다.
    assert required("risk_create_project") == {"code", "name", "classification"}
    assert props("risk_add_source") == {"project_id", "kind", "ref", "app_key", "bridge_declared"}
    assert required("risk_add_source") == {"project_id", "kind", "ref"}
    assert props("risk_capture_snapshot") == {"project_id", "label", "kinds", "report_ids",
                                              "detect_result_file_id", "allow_large"}
    assert props("risk_ack_gate") == {"snapshot_id", "gate", "reason", "gates_hash"}
    assert props("risk_get_sameas") == {"base_snapshot_id", "target_snapshot_id"}
    assert props("risk_decide_sameas") == {"base_snapshot_id", "target_snapshot_id", "decisions"}
    assert props("risk_create_diff") == {"base_snapshot_id", "target_snapshot_id"}
    assert props("risk_open_target") == {"kind", "ref_id", "consent", "flow", "reason"}
    assert required("risk_open_target") == {"kind", "ref_id"}
    # 검토 잡은 새 도구가 아니라 mode·scope 다(M2.md 4.7) — tier 는 패널 잡에만 필요해 선택 인자가 됐다.
    assert props("risk_start_job") == {"target_key", "tier", "consent", "modifiers", "user_memo", "concurrency", "mode",
                                       "scope"}
    assert required("risk_start_job") == {"target_key"}
    assert tools["risk_start_job"].inputSchema["properties"]["mode"]["default"] == "panels"
    assert props("risk_job_action") == {"job_id", "action", "reason", "filter", "consent"}    # 실패 셀 처분(재설계 M3 C3-4) · 다시의 동의(MEDIUM 13)
    assert props("risk_repersist_panel") == {"panel_id", "discard"} and required("risk_repersist_panel") == {"panel_id"}


def test_write_tool_descriptions_ask_for_confirmation_first():
    """쓰기 도구는 설명 앞머리(게이트웨이 검색이 보이는 220자) 안에 '사용자 확인 뒤 부른다' 를 싣는다(허브 규칙 5)."""
    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    readers = {"risk_next_step", "risk_get_sameas"}
    for name in ENTRY_TOOLS:
        head = tools[name].description.strip()[:220]
        if name in readers:
            assert "읽기 전용" in head, name
        else:
            assert "사용자에게" in head and "확인한 뒤 부른다" in head, (name, head)


@pytest.mark.parametrize("name,args,error_code", CALLS, ids=[c[0] for c in CALLS])
def test_each_tool_answers_with_json_not_exception(name, args, error_code):
    """빈 원장에서도 도구는 예외를 올리지 않고 dict 를 돌려주며, MCP 경유 호출과 직접 호출이 같다."""
    direct = _direct(name, args)
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
    # 새 조회 도구도 같은 문지기를 탄다 — 목록은 빈 배열로, 단일 id 는 not_visible 로 숨긴다.
    assert srv.risk_list_projects()["projects"] == []
    assert srv.risk_get_coverage("snap:s9")["error"] == "not_visible"
    assert srv.risk_list_panels("snap:s9")["error"] == "not_visible"
    # 존재를 숨긴 만큼 지표가 센다(§8.2.5 ③).
    row = risk_store.query_one(
        "SELECT value FROM rr_metrics WHERE dimension = 'global' AND metric = 'mcp_not_visible'")
    assert row is not None and row["value"] == 4
    # 편성 부작용도 없다 — planned 패널이 만들어지지 않는다.
    assert risk_store.query("SELECT id FROM rr_panels") == []


def test_the_external_sync_summary_rides_the_project_targets_coverage_and_mcp(risk_store, monkeypatch):
    """RA·AIDataHub 반영 요약({state, pending_ops, reason, message})이 과제 화면의 타깃 · 타깃 목록 · 진행판(REST·MCP)에 같은 값으로
    실린다 — 보내는 쪽이 아직 없다는 것(sender_unwired)을 재동기를 누르기 전에도 본다(R3 · U-4)."""
    from app import identity, ra_client, routes

    _seed_private_target(risk_store, monkeypatch)
    risk_store.execute("UPDATE rr_projects SET mcp_visibility = 'org' WHERE id = 'p9'")
    ra_client.queue_sync_ops(risk_store, "snap:s9", "ra", [{"op": "create_object"}])
    want = ra_client.sync_summary(ra_client.load_external_sync(risk_store, "snap:s9"))
    assert want["ra"]["pending_ops"] == 1 and want["ra"]["reason"] == "sender_unwired"
    owner = identity.Identity(email="owner@a", display_name=None, role="user", organization=None, anonymous=False,
                              source="cookie")
    assert routes.coverage_payload("snap:s9", owner_sub="owner@a")["external_sync"] == want
    assert routes.get_project("p9", ident=owner)["targets"][0]["external_sync"] == want
    assert routes.list_targets(ident=owner)["targets"][0]["external_sync"] == want
    assert srv.risk_get_coverage("snap:s9", with_seats=False)["external_sync"] == want
    assert "external_sync_json" not in routes.get_project("p9", ident=owner)["targets"][0]


def test_org_visibility_opens_the_same_ids(risk_store, monkeypatch):
    """소유자가 mcp_visibility='org' 로 토글하면 같은 id 가 열린다(§5.1 원칙 9)."""
    _seed_private_target(risk_store, monkeypatch)
    risk_store.execute("UPDATE rr_projects SET mcp_visibility = 'org' WHERE id = 'p9'")

    assert srv.risk_get_snapshot("s9", "ir").get("error") != "not_visible"
    assert srv.risk_get_registry("snap:s9").get("error") != "not_visible"


def test_get_brief_needs_a_matching_unexpired_token(risk_store, monkeypatch):
    """brief_token 은 없거나·다르거나·만료면 brief_token_invalid 이고 맞으면 그 패널 브리프가 열린다(§8.2.5)."""
    from app import common, routes

    from tests import factories

    _seed_private_target(risk_store, monkeypatch)
    now = common.now_epoch()
    risk_store.execute(
        "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, tier, seats_json, rounds, status, created_at)"
        " VALUES ('pan9', 'snap:s9', 'owner@a', 1, 'B', '[]', 2, 'planned', ?)", (now,))
    token = routes.issue_brief_token(risk_store, "pan9")
    factories.act_as_delegate(monkeypatch, "owner@a")    # 브리프는 결과를 낼 신원에게만 열린다(RV-1) — 그다음이 토큰 대조다

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
    from tests import factories
    from tests.test_project_patch import _human_body, _ident, _seeded_target

    target_key = _seeded_target(risk_store, monkeypatch)
    rest = routes.create_human_finding(target_key, _human_body(), ident=_ident("owner@example.com"))
    factories.act_as_delegate(monkeypatch, "owner@example.com")   # 작성자는 도달한 위임 신원이다(actor 는 신원이 아니다)
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
