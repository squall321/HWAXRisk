# 소스 어댑터(mcad·dyna·ecad_stub)와 게이트웨이 발견·캡처 오케스트레이션 — 응답 형상은 P1 정찰 실측 그대로이고 외부 호출은 전부 MockTransport(실 네트워크 0)
from __future__ import annotations

import json

import httpx
import pytest

from app import ir_builder
from app.adapters import dyna as dyna_adapter
from app.adapters import ecad_stub, mcad
from app.adapters import registry as adapters_registry
from app.adapters import base as adapters_base
from app.adapters.base import CallRecorder, Principal, RestGetClient
from app.errors import AppError
from app.ra_client import McpHttpClient

OWNER = "me@example.com"
SF_PROJECT = "001a02ba21cd51064a68c35"
APP_KEY = "heax-step_forge"
DYNA_APP_KEY = "heax-kooremapper_mcp"
KSHA = "abcd1234ef567890abcd1234ef567890abcd1234ef567890abcd1234ef567890"


# ---------------------------------------------------------------- 소스 응답 픽스처(정찰 실측 형상)
TREE_JSON = {
    "project": "sif-e2e",
    "unit_system": "mm",
    "files": [{"relpath": "a_stack.step", "sha256": "0" * 64, "size_bytes": 1024,
               "schema_ap": "AUTOMOTIVE_DESIGN", "header_unit": "millimetre"}],
    "nodes": [
        {"id": "n0", "parent_id": None, "kind": "file", "name": "a_stack.step", "path": "/sif-e2e/a_stack.step",
         "depth": 1, "seq": 0, "shape_def_id": None, "transform": None, "world_transform": None,
         "auto_named": False, "color": None},
        {"id": "n1", "parent_id": "n0", "kind": "assembly", "name": "STACK_ASM",
         "path": "/sif-e2e/a_stack.step/STACK_ASM", "depth": 2, "seq": 1, "shape_def_id": None,
         "transform": None, "world_transform": None, "auto_named": False, "color": None},
        {"id": "n4", "parent_id": "n1", "kind": "instance", "name": "PLATE_1",
         "path": "/sif-e2e/a_stack.step/STACK_ASM/PLATE_1", "depth": 3, "seq": 4, "shape_def_id": "s1",
         "transform": None,
         "world_transform": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
         "auto_named": False, "color": None},
        {"id": "n5", "parent_id": "n1", "kind": "instance", "name": "PLATE_2",
         "path": "/sif-e2e/a_stack.step/STACK_ASM/PLATE_2", "depth": 3, "seq": 5, "shape_def_id": "s2",
         "transform": None,
         # z 로 1.2 mm 올려 쌓은 두 번째 판재 — world 재계산이 살아 있으면 bbox_world 가 [.., 1.2, .., 2.2] 다.
         "world_transform": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 1.2], [0, 0, 0, 1]],
         "auto_named": False, "color": None},
        {"id": "n6", "parent_id": "n1", "kind": "instance", "name": "BRACKET_L",
         "path": "/sif-e2e/a_stack.step/STACK_ASM/BRACKET_L", "depth": 3, "seq": 6, "shape_def_id": None,
         "transform": None, "world_transform": None, "auto_named": True, "color": None},
    ],
    "shape_defs": {
        "s1": {"kind": "solid", "bbox": [0, 0, 0, 50, 40, 1.2], "volume": 2400.0, "area": 4120.0,
               "centroid": [25.0, 20.0, 0.6], "material": "AL6061", "density": None, "density_unit": None,
               "instance_count": 1, "has_geometry": 1, "solid_count": 1, "construction_only": False,
               "xcaf_entry": "0:1:1:1", "step_file": "a_stack.step"},
        "s2": {"kind": "solid", "bbox": [0, 0, 0, 50, 40, 1.0], "volume": 2000.0, "area": 3800.0,
               "centroid": [25.0, 20.0, 0.5], "material": "AL6061", "density": None, "density_unit": None,
               "instance_count": 1, "has_geometry": 1, "solid_count": 1, "construction_only": False,
               "xcaf_entry": "0:1:1:2", "step_file": "a_stack.step"},
    },
    "summary": {"files": 1, "shape_defs": 2, "nodes": 5, "assemblies": 1, "instances": 3,
                "leaf_instances": 2, "max_depth": 4, "auto_named_nodes": 1, "auto_named_defs": 0,
                "defs_without_geometry": 1, "warnings": 1},
    "warnings": [{"severity": "WARNING", "code": "auto_named", "message": "이름이 자동 생성됐다.",
                  "ref": "a_stack.step#BRACKET_L"}],
}

GRAPH_JSON = {
    "nodes": [{"id": "n4", "name": "PLATE_1", "path": "/sif-e2e/a_stack.step/STACK_ASM/PLATE_1",
               "shape_def": "s1", "degree": 1}],
    "edges": [{"a": "n4", "b": "n5", "kind": "tied"}],
    "orphans": [],
    "counts": {"tied": 1},
    "scope": None,
}

PARTS_REST = {"parts": [
    {"id": "n4", "shape_def_id": "s1", "name": "PLATE_1", "path": "/sif-e2e/a_stack.step/STACK_ASM/PLATE_1",
     "kind": "solid", "bbox": [0, 0, 0, 50, 40, 1.2], "volume": 2400.0},
    {"id": "n5", "shape_def_id": "s2", "name": "PLATE_2", "path": "/sif-e2e/a_stack.step/STACK_ASM/PLATE_2",
     "kind": "solid", "bbox": [0, 0, 0, 50, 40, 1.0], "volume": 2000.0},
]}

# MCP list_parts — id·shape_def_id 없음, bbox 는 shape_def 로컬, volume 등은 전부 null(정찰 실측).
PARTS_MCP = {"parts": [
    {"name": "PLATE_1", "path": "/sif-e2e/a_stack.step/STACK_ASM/PLATE_1", "kind": "solid",
     "bbox": [0.0, 0.0, 0.0, 50.0, 40.0, 1.2], "color": None, "instance_count": 1, "has_geometry": 1,
     "volume": None, "area": None, "centroid": None, "material": None, "density": None, "density_unit": None},
    {"name": "PLATE_2", "path": "/sif-e2e/a_stack.step/STACK_ASM/PLATE_2", "kind": "solid",
     "bbox": [0.0, 0.0, 0.0, 50.0, 40.0, 1.0], "color": None, "instance_count": 1, "has_geometry": 1,
     "volume": None, "area": None, "centroid": None, "material": None, "density": None, "density_unit": None},
]}

PROJECT_TREE_MCP = {
    "summary": TREE_JSON["summary"],
    "warnings": [],
    "nodes": [{"name": "a_stack.step", "kind": "file", "path": "/sif-e2e/a_stack.step"},
              {"name": "STACK_ASM", "kind": "assembly", "path": "/sif-e2e/a_stack.step/STACK_ASM"},
              {"name": "PLATE_1", "kind": "instance", "path": "/sif-e2e/a_stack.step/STACK_ASM/PLATE_1"},
              {"name": "PLATE_2", "kind": "instance", "path": "/sif-e2e/a_stack.step/STACK_ASM/PLATE_2"}],
}

# list_interfaces — 13필드, row id 없음, cross_file 은 int, counts 는 0인 kind 키를 생략한다.
IFACE_TIED = {"counts": {"tied": 1}, "interfaces": [
    {"node_a": "n4", "node_b": "n5", "name_a": "PLATE_1", "name_b": "PLATE_2", "kind": "tied",
     "min_gap": 0.0, "contact_area_est": 2000.0, "band_width": 0.05, "penetration_depth": None,
     "penetration_volume": None, "cross_file": 0, "status": "confirmed", "note": "공차 밴드 안에서 맞닿음"},
]}
IFACE_EMPTY = {"counts": {"tied": 1}, "interfaces": []}
# REST /projects/{id}/interfaces — MCP 판과 같은 필드에 **행 id 가 더 있다**(StepForge app/rest.py:257 SELECT).
# 그래서 정상 경로는 이 응답을 쓰고 계면 원장이 행 id 로 앵커된다.
IFACE_REST = {"counts": {"tied": 1}, "interfaces": [
    dict(IFACE_TIED["interfaces"][0], id=41),
]}
# interface_graph(json) — counts 4키 고정, orphans 는 배열, edges 는 nodes 없이 실제 노드 id 를 쓴다.
IFACE_GRAPH = {"counts": {"tied": 1, "touching": 0, "clearance": 0, "interference": 0}, "orphans": ["n6"],
               "edges": [{"a": "n4", "b": "n5", "name_a": "PLATE_1", "name_b": "PLATE_2", "kind": "tied",
                          "min_gap": 0.0, "contact_area_est": 2000.0, "cross_file": False,
                          "status": "confirmed"}]}

JOB_STATUS_DONE = {"status": "done", "finished_at": 1756590000,
                   "params": {"tied_gap": 0.05, "clearance_gap": 1.0, "tied_area": 1.0, "tied_width": 0.05,
                              "scope": None}}

INSPECT_FILE = {"meta": {
    "nodes": 12000, "elements": 9800, "parts": 2, "valid": True,
    "bbox_min": [0, 0, 0], "bbox_max": [50, 40, 2.2], "size": [50, 40, 2.2],
    "keyword_counts": {"*PART": 2, "*SECTION_SOLID": 1, "*CONTACT_TIED_SURFACE_TO_SURFACE": 1},
    "truncated_scan": False, "includes": [],
    "modelmeta": {
        "conventions": {"unit": "mm-kg-ms"},
        "parts": [
            {"pid": 1, "title": "Stack\\PLATE_1", "elem_class": "solid", "n_elems": 5000,
             "bbox_min": [0, 0, 0], "bbox_max": [50, 40, 1.2], "size": [50, 40, 1.2], "area_ext": 4120.0,
             "volume": 2400.0, "proj": {"x": 2000.0, "y": 60.0, "z": 48.0},
             "material": {"mid": 1, "kfile": {"keyword": "*MAT_ELASTIC", "name": "AL", "E": 70000.0},
                          "db": {"match_basis": "name-mat", "db_mid": 3, "name": "AL6061", "tag": "AL6061"}}},
            {"pid": 2, "title": "Stack\\SHIELD", "elem_class": "shell", "n_elems": 4800,
             "bbox_min": [0, 0, 1.2], "bbox_max": [50, 40, 1.4], "size": [50, 40, 0.2], "area_ext": 3800.0,
             "volume": 0, "proj": {"x": 2000.0, "y": 10.0, "z": 8.0},
             "material": {"mid": 2, "kfile": {"keyword": "*MAT_PIECEWISE_LINEAR_PLASTICITY"}, "db": None}},
        ],
        "connectivity": {
            "contact_edges": [{"a": 1, "b": 2, "a_title": "Stack\\PLATE_1", "b_title": "Stack\\SHIELD",
                               "contact": 1, "type": "*CONTACT_TIED_SURFACE_TO_SURFACE", "title": "tie1",
                               "fs": None}],
            "single_surface": [{"contact": 2, "type": "*CONTACT_AUTOMATIC_SINGLE_SURFACE",
                                "title": "self", "pids": [1, 2]}],
            "contacts_total": 2, "unresolved_sides": 0, "edges_truncated": False,
        },
    },
}}


# ---------------------------------------------------------------- 전송(MockTransport)
def _mcp_handler(tools: dict, seen: list | None = None):
    """게이트웨이 MCP 를 흉내내는 MockTransport 핸들러. 계약에 없는 도구는 isError 로 돌려준다."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}},
                                  headers={"mcp-session-id": "sess-1"})
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        name = payload["params"]["name"]
        if seen is not None:
            seen.append((name, payload["params"]["arguments"]))
        if name not in tools:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                             "result": {"isError": True,
                                                        "content": [{"type": "text", "text": f"unknown tool: {name}"}]}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                         "result": {"structuredContent": tools[name]}})

    return handler


def _rest_handler(routes: dict, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "어댑터는 소스 앱에 GET 만 한다"
        assert request.headers["authorization"] == "Bearer service-pat"
        path = request.url.path
        if seen is not None:
            seen.append(path)
        if path not in routes:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=routes[path])

    return handler


def _mcp(tools: dict, seen: list | None = None) -> McpHttpClient:
    return McpHttpClient("https://gw.test/mcp", headers={"Authorization": "Bearer pat"},
                         client=httpx.Client(transport=httpx.MockTransport(_mcp_handler(tools, seen))))


def _rest(routes: dict, seen: list | None = None, token: str | None = "service-pat") -> RestGetClient:
    return RestGetClient("https://heax.test", token,
                         client=httpx.Client(transport=httpx.MockTransport(_rest_handler(routes, seen))))


BASE = f"/apps/step_forge/api/projects/{SF_PROJECT}"
REST_ROUTES = {
    BASE: {"id": SF_PROJECT, "name": "sif-e2e",
           "tol_config": {"tied_gap": 0.05, "clearance_gap": 1.0, "tied_area": 1.0, "tied_width": 0.05}},
    f"{BASE}/tree": TREE_JSON,
    f"{BASE}/artifacts/graph/": GRAPH_JSON,
    f"{BASE}/parts": PARTS_REST,
    f"{BASE}/interfaces": IFACE_REST,
}
MCP_TOOLS_FULL = {
    "job_status": JOB_STATUS_DONE,
    "list_interfaces": IFACE_TIED,
    "interface_graph": IFACE_GRAPH,
    "project_tree": PROJECT_TREE_MCP,
    "list_parts": PARTS_MCP,
}


def _principal(portal: str | None = "portal-pat", service: str | None = "service-pat") -> Principal:
    return Principal(owner_sub=OWNER, portal_pat=portal, service_pat=service)


# ---------------------------------------------------------------- 게이트웨이 발견(§2.13.2)
def _tools_map_client(body: dict, seen: list | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.url.path)
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_gateway_registry_matches_prefixed_tool_names():
    """게이트웨이는 충돌 시 backend_key 접두를 붙인다 — suffix 매칭이어야 mcad 가 발견된다(recon §4 8항)."""
    body = {"map": {
        "list_parts": APP_KEY, "list_interfaces": APP_KEY, "interface_graph": APP_KEY,
        "project_tree": APP_KEY, "part_mesh_map": APP_KEY, "heaxstep_forge_job_status": APP_KEY,
        "job_status": "smart-twin-cluster",
    }}
    registry = adapters_registry.GatewayRegistry("http://gw.test:9110/mcp", client=_tools_map_client(body))
    probe = registry.probe("mcad")
    assert probe["app_key"] == APP_KEY
    assert probe["reachable"] is True and probe["tools_missing"] == []
    assert probe["rest_ok"] is None


def test_gateway_registry_reports_missing_tools_and_survives_failure():
    registry = adapters_registry.GatewayRegistry("http://gw.test:9110/mcp",
                                                 client=_tools_map_client({"map": {"list_parts": APP_KEY}}))
    probe = registry.probe("mcad")
    assert probe["reachable"] is False
    assert set(probe["tools_missing"]) == set(mcad.REQUIRED_TOOLS) - {"list_parts"}

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    dead = adapters_registry.GatewayRegistry("http://gw.test:9110/mcp",
                                             client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert dead.load() == {}
    assert dead.probe("ecad")["reachable"] is False


def test_ambiguous_tool_name_needs_the_app_key_and_warns(monkeypatch):
    """한 want 집합이 두 백엔드에 다 있으면 app_key 로 좁히고, 그래도 다의면 reachable=false + 경고다."""
    other = "heax-other_forge"
    body = {"map": {}}
    for tool in mcad.REQUIRED_TOOLS:
        body["map"][tool] = APP_KEY
        body["map"][f"otherforge_{tool}"] = other

    registry = adapters_registry.GatewayRegistry("http://gw.test:9110/mcp", client=_tools_map_client(body))
    ambiguous = registry.probe("mcad", app_key="heax-nobody")
    assert ambiguous["app_key"] is None and ambiguous["reachable"] is False
    assert ambiguous["warnings"] == ["ambiguous_tool_name"]
    assert set(ambiguous["candidates"]) == {APP_KEY, other}

    narrowed = adapters_registry.GatewayRegistry(
        "http://gw.test:9110/mcp", client=_tools_map_client(body)).probe("mcad", app_key=other)
    assert narrowed["app_key"] == other and narrowed["reachable"] is True
    assert narrowed["warnings"] == []


def test_type_unexpected_is_a_warning_not_a_silent_cast():
    """정의 밖 cross_file 값은 조용한 캐스팅 대신 warnings.type_unexpected 1건이다(plan §2.13.1)."""
    from app.adapters import mcad as mcad_module

    warnings: list[dict] = []
    assert mcad_module._as_bool(1, warnings=warnings) is True         # int 0/1 은 규칙대로 bool
    assert mcad_module._as_bool(0, warnings=warnings) is False
    assert mcad_module._as_bool(True, warnings=warnings) is True
    assert warnings == []
    assert mcad_module._as_bool("yes", tool="list_interfaces", field="cross_file",
                                warnings=warnings) is True
    assert [w["code"] for w in warnings] == ["type_unexpected"]
    assert warnings[0]["ref"] == "list_interfaces" and "cross_file" in warnings[0]["message"]


def test_gateway_http_base_strips_mcp_suffix():
    assert adapters_registry.gateway_http_base("http://127.0.0.1:9110/mcp") == "http://127.0.0.1:9110"
    assert adapters_registry.gateway_http_base("http://127.0.0.1:9110/") == "http://127.0.0.1:9110"


# ---------------------------------------------------------------- mcad 정상 경로(REST 정본)
def _capture_mcad(*, rest_token="service-pat", tools=None, ref=None, rest_seen=None, mcp_seen=None,
                  routes=None):
    recorder = CallRecorder("cafe0000deadbeef", mcp=_mcp(tools or MCP_TOOLS_FULL, mcp_seen),
                            rest=_rest(routes or REST_ROUTES, rest_seen, rest_token))
    adapter = mcad.McadAdapter(APP_KEY)
    payload = {"stepforge_project_id": SF_PROJECT, "detect_job_id": "01JDET"}
    payload.update(ref or {})
    return adapter.capture(payload, _principal(), recorder), recorder


def test_mcad_rest_channel_builds_world_bbox_and_resolves_edges_by_node_id():
    result, recorder = _capture_mcad()
    source = result["source"]
    assert source["channel"] == "rest+mcp"
    assert source["ref"]["unit_system"] == "mm"
    assert source["ref"]["detect_finished_at"] == 1756590000
    assert source["ref"]["step_files"][0]["header_unit"] == "millimetre"
    # 이 픽스처의 도구 지도에는 system_status 가 없다 — 버전은 null 이고 그 사실이 degraded 로 남는다(§2.2).
    assert source["degraded"] == ["app_version_unknown"]
    assert source["app_version"] == {"version": None, "captured_via": None, "extra": None}
    assert source["tol_known_keys"] == ["clearance_gap", "tied_area", "tied_gap", "tied_width"]
    assert len(source["tol_config_hash"]) == 64

    parts = {n["label"]: n for n in result["nodes"] if n["kind"] == "part"}
    assert set(parts) == {"PLATE_1", "PLATE_2"}          # shape_def 없는 BRACKET_L 은 노드가 아니다
    plate2 = parts["PLATE_2"]["attrs"]
    # world_transform 을 8꼭짓점에 적용해 축정렬 bbox 를 다시 잡는다(±0.01 mm).
    assert plate2["bbox_world"] == pytest.approx([0, 0, 1.2, 50, 40, 2.2], abs=0.01)
    assert plate2["centroid_world"] == pytest.approx([25.0, 20.0, 1.7], abs=0.01)
    assert plate2["bbox_def"] == [0, 0, 0, 50, 40, 1.0]  # 정의 좌표계는 그대로 남는다
    assert plate2["min_dim"] == 1.0 and plate2["size_sorted"] == [50, 40, 1.0]
    assert parts["PLATE_1"]["provenance"]["node_id_at_capture"] == "n4"

    ifaces = [e for e in result["edges"] if e["kind"] == "tied"]
    assert len(ifaces) == 1
    edge = ifaces[0]
    assert edge["a"].endswith("PLATE_1") and edge["b"].endswith("PLATE_2")
    assert edge["attrs"]["cross_file"] is False          # 소스 int 0 → bool 정규화
    assert edge["attrs"]["penetration_depth_is_lower_bound"] is True
    assert edge["attrs"]["tol_config_hash"] == source["tol_config_hash"]
    assert edge["status"] == "confirmed"
    assert any(e["kind"] == "part_of" for e in result["edges"])

    # 소스 원문 warnings 는 축어로 보존한다.
    assert [w["code"] for w in result["warnings"] if w["code"] == "auto_named"] == ["auto_named"]
    # 모든 호출이 로그로 남고 call_id 는 record_calls 공식과 같다.
    assert result["call_ids"] == [c for c in result["call_ids"]] and result["call_ids"][0] == "cafe0000-001"
    assert len(recorder.calls) == len(result["call_ids"])
    assert {c["channel"] for c in recorder.calls} == {"mcp", "rest"}


def test_mcad_source_hash_is_deterministic_and_covers_tol_and_job():
    first, _ = _capture_mcad()
    second, _ = _capture_mcad()
    assert first["source"]["source_hash"] == second["source"]["source_hash"]
    other, _ = _capture_mcad(ref={"detect_job_id": "01JOTHER"})
    assert other["source"]["source_hash"] != first["source"]["source_hash"]


def test_mcad_stops_when_detect_job_is_not_done():
    tools = dict(MCP_TOOLS_FULL, job_status={"status": "running", "params": {}})
    with pytest.raises(AppError) as err:
        _capture_mcad(tools=tools)
    assert err.value.http_status == 409 and err.value.code == "detect_not_done"


# ---------------------------------------------------------------- mcad 강등 경로(MCP 만)
def test_mcad_without_service_pat_degrades_to_mcp_only():
    """서비스 PAT 가 없으면 REST 를 한 번도 부르지 않고 mcp_degraded 로 내려간다."""
    rest_seen: list[str] = []
    result, _ = _capture_mcad(rest_token=None, rest_seen=rest_seen)
    assert rest_seen == []
    source = result["source"]
    assert source["channel"] == "mcp"
    assert {"mcp_degraded", "no_node_id", "no_world_transform", "volume_null_pre_d168"} <= set(source["degraded"])
    # tol 은 detect 잡 params 4키로 아직 살아 있다.
    assert "tol_config_unknown" not in source["degraded"]
    assert source["ref"]["unit_system"] is None          # G6 (b) 입력이 결측이다
    parts = [n for n in result["nodes"] if n["kind"] == "part"]
    assert {n["label"] for n in parts} == {"PLATE_1", "PLATE_2"}
    assert all(n["attrs"]["bbox_world"] is None and n["attrs"]["volume"] is None for n in parts)
    assert all("volume_null" in n["status_flags"] for n in parts)
    assert result["missing"] == {"world_transform_absent": True, "volume_null": True}
    # 끝점 id 를 못 쓰므로 이름이 유일할 때만 엣지를 세운다.
    assert [e["kind"] for e in result["edges"] if e["kind"] == "tied"] == ["tied"]


def test_mcad_mcp_only_drops_edges_with_duplicate_names():
    twin = json.loads(json.dumps(PROJECT_TREE_MCP))
    twin["nodes"].append({"name": "PLATE_1", "kind": "instance",
                          "path": "/sif-e2e/a_stack.step/STACK_ASM/COPY/PLATE_1"})
    parts = json.loads(json.dumps(PARTS_MCP))
    parts["parts"].append(dict(parts["parts"][0], path="/sif-e2e/a_stack.step/STACK_ASM/COPY/PLATE_1"))
    tools = dict(MCP_TOOLS_FULL, project_tree=twin, list_parts=parts)
    result, _ = _capture_mcad(rest_token=None, tools=tools)
    assert [e["kind"] for e in result["edges"] if e["kind"] == "tied"] == []
    assert [w["code"] for w in result["warnings"] if w["code"] == "ambiguous_edge_endpoint"]


def test_mcad_detects_truncation_by_interface_graph_counts():
    """소스가 truncated 플래그를 주지 않으므로 counts 합 > 수신 행 수로 판정한다(recon §4 4항).

    정상 경로는 REST /interfaces 라 그쪽을 비우고, MCP 폴백도 같은 규칙임을 함께 고정한다.
    """
    tools = dict(MCP_TOOLS_FULL, list_interfaces=IFACE_EMPTY)
    routes = dict(REST_ROUTES, **{f"{BASE}/interfaces": IFACE_EMPTY})
    result, _ = _capture_mcad(tools=tools, routes=routes)
    assert "interfaces_truncated" in result["source"]["degraded"]
    # MCP 폴백(REST 자격 없음)에서도 같은 판정이다.
    degraded_only, _ = _capture_mcad(tools=tools, rest_token=None)
    assert "interfaces_truncated" in degraded_only["source"]["degraded"]
    # counts 는 0 인 kind 키가 생략돼 와도 4키 고정으로 정규화한다.
    assert set(result["source"]["stats"]["interface_counts"]) == set(mcad.IFACE_KINDS)


def test_mcad_asks_for_every_part_and_flags_a_short_list():
    """REST `/parts` 는 limit 기본이 500 이고 총수를 주지 않는다 — 명시 상한 + 트리 리프 대조가 유일한 방어다.

    잘린 파트 목록은 오류가 아니라 **없는 리스크**를 만든다(그 파트의 계면·치수가 통째로 사라진다).
    """
    seen: list[str] = []
    urls: list[str] = []

    def handler(request):
        urls.append(str(request.url))
        seen.append(request.url.path)
        body = REST_ROUTES.get(request.url.path)
        return httpx.Response(200, json=body) if body is not None else httpx.Response(404, json={})

    rest = RestGetClient("https://heax.test", "service-pat",
                         client=httpx.Client(transport=httpx.MockTransport(handler)))
    recorder = CallRecorder("cafe0000deadbeef", mcp=_mcp(MCP_TOOLS_FULL), rest=rest)
    result = mcad.McadAdapter(APP_KEY).capture({"stepforge_project_id": SF_PROJECT}, _principal(), recorder)

    # 상한을 명시하지 않으면 소스가 500 으로 클램프한다 — 501번째부터 조용히 사라진다.
    parts_url = next(u for u in urls if u.endswith("/parts") or "/parts?" in u)
    assert f"limit={mcad.REST_PARTS_LIMIT}" in parts_url
    # 픽스처는 트리 리프 2 개 · 파트 2 개로 같다 — 정상이면 절단 표기가 없다.
    assert "parts_truncated" not in result["source"]["degraded"]


def test_mcad_flags_parts_truncated_when_the_list_is_shorter_than_the_tree():
    short = {"parts": PARTS_REST["parts"][:1]}
    routes = dict(REST_ROUTES, **{f"{BASE}/parts": short})
    result, _ = _capture_mcad(routes=routes)

    # 트리 리프 3 개인데 파트 1 개만 왔다 — 소스가 잘랐다는 뜻이다.
    assert "parts_truncated" in result["source"]["degraded"]
    # 경고는 결과 최상위에 실린다 — 사유가 없으면 사람은 왜 잘렸는지 알 수 없다.
    warning = next(w for w in result["warnings"] if w["code"] == "parts_truncated")
    assert warning["message"] == "파트 목록이 잘렸다 — 트리 리프 2 개 중 1 개만 받았다."


def test_mcad_marks_tol_unknown_without_job_or_tol_config():
    routes = dict(REST_ROUTES)
    routes[BASE] = {"id": SF_PROJECT, "name": "sif-e2e"}
    recorder = CallRecorder("cafe0000deadbeef", mcp=_mcp(MCP_TOOLS_FULL), rest=_rest(routes))
    result = mcad.McadAdapter(APP_KEY).capture({"stepforge_project_id": SF_PROJECT}, _principal(), recorder)
    assert result["source"]["tol_config_hash"] is None
    assert {"tol_config_unknown", "detect_absent"} <= set(result["source"]["degraded"])


def test_mcad_raises_when_tree_unreadable_on_both_channels():
    recorder = CallRecorder("cafe0000deadbeef", mcp=_mcp({}), rest=_rest({}, token=None))
    with pytest.raises(AppError) as err:
        mcad.McadAdapter(APP_KEY).capture({"stepforge_project_id": SF_PROJECT}, _principal(), recorder)
    assert err.value.http_status == 409 and err.value.code == "source_unreachable"


# ---------------------------------------------------------------- dyna
def test_dyna_without_portal_pat_makes_no_call():
    """러너 자격 (b) 가 없으면 호출을 한 번도 하지 않고 dyna_absent 로 내려간다(plan §2.13.4)."""
    def boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"자격 없이 소스 호출이 나갔다: {request.url}")

    recorder = CallRecorder("cafe0000deadbeef",
                            mcp=McpHttpClient("https://gw.test/mcp",
                                              client=httpx.Client(transport=httpx.MockTransport(boom))))
    result = dyna_adapter.DynaAdapter(DYNA_APP_KEY).capture(
        {"session_id": "01JSES", "file_id": "01JFIL"}, _principal(portal=None), recorder)
    assert result["missing"] == {"dyna_absent": True}
    assert result["nodes"] == [] and recorder.calls == []
    assert result["source"]["channel"] is None
    assert [w["code"] for w in result["warnings"]] == ["dyna_pat_absent"]


def test_dyna_capture_builds_pid_nodes_contacts_and_scope():
    tools = {"inspect_file": INSPECT_FILE}
    recorder = CallRecorder("cafe0000deadbeef", mcp=_mcp(tools))
    result = dyna_adapter.DynaAdapter(DYNA_APP_KEY).capture(
        {"session_id": "01JSES", "file_id": "01JFIL", "sha256": KSHA}, _principal(), recorder)
    pids = {n["local_key"]: n for n in result["nodes"] if n["kind"] == "pid"}
    assert set(pids) == {"1", "2"}
    assert pids["1"]["canon_key"] == f"dyna:{KSHA[:8]}:1"
    assert pids["1"]["group"] == "Stack"                  # `\` 앞이 group 이다
    # shell 파트의 volume 0 은 미측정이지 0 이 아니다.
    assert pids["2"]["attrs"]["volume"] is None and "shell_volume_zero" in pids["2"]["status_flags"]
    assert "no_secid" in result["source"]["degraded"] and pids["1"]["attrs"]["secid"] is None
    contact = [e for e in result["edges"] if e["kind"] == "contact"]
    scope = [e for e in result["edges"] if e["kind"] == "scope"]
    assert len(contact) == 1 and contact[0]["attrs"]["contact_type"] == "*CONTACT_TIED_SURFACE_TO_SURFACE"
    assert scope[0]["b"] is None and len(scope[0]["members"]) == 2
    # 전사 집계는 어댑터가 아니라 capture_all 의 몫이다(§2.11.3 3a) — 소스 dict 에 context 키가 없다.
    assert "context" not in result["source"]
    assert result["source"]["stats"]["size"] == [50, 40, 2.2]
    assert "detect_absent" in result["source"]["degraded"]


def test_corpus_context_merges_four_tools_in_the_canonical_order():
    """§2.2·§2.11.3 3a — 4응답을 펼쳐 합치고, 호출은 소스 캡처가 아닌 kind 로 적는다."""
    seen: list = []
    tools = {"corpus_summary": {"sessions": 12, "files": 25, "jobs": 8},
             "material_usage": {"materials": [{"mid": 1}]},
             "section_contact_usage": {"sections": [{"secid": 7}], "contacts": [{"cid": 3}]},
             "operation_usage": {"operations": [{"op": "remesh", "n": 4}]}}
    recorder = CallRecorder("cafe0000deadbeef", mcp=_mcp(tools, seen))
    out = dyna_adapter.corpus_context(recorder, app_key=DYNA_APP_KEY, captured_at=1756600000)

    # 순서는 정본 §2.11.3 3a 가 고정한다 — 상수를 다시 읽으면 항진명제가 되므로 값을 박는다.
    assert [name for name, _ in seen] == [
        "corpus_summary", "material_usage", "section_contact_usage", "operation_usage"]
    # 중첩이 아니라 병합이다 — 정본 §2.2 예시의 평평한 키가 그대로 나온다.
    assert out["corpus_usage"] == {
        "app_key": DYNA_APP_KEY, "fetched_at": 1756600000,
        "sessions": 12, "files": 25, "jobs": 8,
        "materials": [{"mid": 1}], "sections": [{"secid": 7}], "contacts": [{"cid": 3}],
        "operations": [{"op": "remesh", "n": 4}]}
    # 소스 캡처 예산·sources[].call_ids·재사용 표기 밖에 두려면 kind 가 소스 kind 와 달라야 한다.
    # 상수를 다시 읽으면 CONTEXT_KIND='dyna' 로 되돌려도 초록이라 값을 박는다.
    assert {c["source_kind"] for c in recorder.calls} == {"context"}
    assert dyna_adapter.CONTEXT_KIND not in ("mcad", "dyna", "dyna_result", "ecad")


_CORPUS_STUBS = {"corpus_summary": {"sessions": 12}, "material_usage": {"materials": []},
                 "section_contact_usage": {"sections": [], "contacts": []},
                 "operation_usage": {"operations": []}}


def test_capture_all_collects_the_context_even_without_any_credential():
    """§2.11.3 3a — 자격(러너 (b))이 없어 3b 를 건너뛰어도 전사 집계는 돈다. 그게 이 항의 요지다.

    이 시험이 없으면 capture_all 의 3a 블록을 통째로 지워도 전 시험이 초록이다.
    """
    out = adapters_registry.capture_all(
        sources=[{"kind": "mcad", "app_key": APP_KEY, "ref": {"stepforge_project_id": SF_PROJECT}},
                 {"kind": "dyna", "app_key": DYNA_APP_KEY, "ref": {}}],
        principal=_principal(portal=None, service=None),
        mcp_client=_mcp(dict(MCP_TOOLS_FULL, **_CORPUS_STUBS)),
        rest_client=_rest(REST_ROUTES), kinds=["mcad", "dyna"])

    # 자격이 없어 dyna 소스는 부재로 떨어지는데(3b 건너뜀) 조직 집계는 채워진다.
    assert any(r["missing"].get("dyna_absent") for r in out["results"])
    usage = out["context"]["corpus_usage"]
    assert usage is not None and usage["sessions"] == 12
    # 소스 캡처 회계와 섞이지 않는다 — kind 가 갈리고 mcad 소스의 call_ids 에 전사 호출이 없다.
    by_kind: dict = {}
    for c in out["calls"]:
        by_kind[c["source_kind"]] = by_kind.get(c["source_kind"], 0) + 1
    assert by_kind[dyna_adapter.CONTEXT_KIND] == 4
    assert len(set(out["results"][0]["call_ids"])) == by_kind["mcad"], "mcad call_ids 에 전사 호출이 섞였다"


def test_an_mcad_only_snapshot_stays_inside_the_call_budget():
    """3a 는 'dyna 캡처' 의 하위 단계다(§2.11.3 3) — mcad 단독 요청은 DynaForge 를 부르지 않는다.

    부르면 정상 경로가 mcp 7 이 되어 §9.2 통과 기준 2 가 `mcp_degraded` 폴백의 지문으로 쓰는 값과 겹친다.
    """
    out = adapters_registry.capture_all(
        sources=[{"kind": "mcad", "app_key": APP_KEY, "ref": {"stepforge_project_id": SF_PROJECT}}],
        principal=_principal(), mcp_client=_mcp(dict(MCP_TOOLS_FULL, **_CORPUS_STUBS)),
        rest_client=_rest(REST_ROUTES), kinds=["mcad"])

    assert out["context"] is None
    # 예산은 source_kind 가 아니라 channel 로 센다(§9.2 통과 기준 2) — 태그로는 빼줄 수 없다.
    called = {c["tool"] for c in out["calls"]}
    assert called & set(dyna_adapter.CORPUS_TOOLS) == set(), "mcad 단독인데 DynaForge 를 불렀다"
    assert all(c["source_kind"] != dyna_adapter.CONTEXT_KIND for c in out["calls"])
    # 이 픽스처의 mcad 경로가 쓰는 mcp 호출 수는 3 을 넘지 않는다(정본 상한).
    assert sum(1 for c in out["calls"] if c["channel"] == "mcp") <= 3


def test_capture_all_uses_the_registered_dyna_app_key_for_the_context():
    """과제가 고른 dyna app_key 를 쓴다 — 정적 기본값을 박으면 다른 백엔드 조직에서 틀린 값이 동결된다."""
    out = adapters_registry.capture_all(
        sources=[{"kind": "mcad", "app_key": APP_KEY, "ref": {"stepforge_project_id": SF_PROJECT}},
                 {"kind": "dyna", "app_key": "heax-other_dyna", "ref": {}}],
        principal=_principal(portal=None, service=None),
        mcp_client=_mcp(dict(MCP_TOOLS_FULL, **_CORPUS_STUBS)),
        rest_client=_rest(REST_ROUTES), kinds=["mcad", "dyna"])

    assert out["context"]["corpus_usage"]["app_key"] == "heax-other_dyna"


def test_context_survives_the_route_into_the_frozen_envelope(risk_store, monkeypatch):
    """capture_all → freeze_snapshot → ir_json 배선 — 통과 기준 (23)(e) 는 여기까지가 한 줄이다."""
    from app import ir_builder

    usage = {"app_key": DYNA_APP_KEY, "sessions": 12, "fetched_at": 1756600000}
    captured, _ = _capture_mcad()
    out = ir_builder.freeze_snapshot(
        risk_store, project_id="0" * 32, owner_sub=OWNER, label="DV1",
        adapter_results=[captured], context={"corpus_usage": usage}, with_state=False)

    stored = json.loads(risk_store.query_one(
        "SELECT ir_json FROM rr_snapshots WHERE id = ?", (out["snapshot_id"],))["ir_json"])
    assert stored["context"]["corpus_usage"] == usage
    assert all("context" not in s for s in stored["sources"])


def test_corpus_context_is_null_only_when_all_four_fail():
    """일부만 실패하면 나머지는 싣는다. 넷 다 실패해야 null 이다(§2.2)."""
    # 스텁에 없는 도구는 isError 로 떨어진다 — corpus_summary 하나만 살려 둔다.
    partial = dyna_adapter.corpus_context(
        CallRecorder("cafe0000deadbeef", mcp=_mcp({"corpus_summary": {"sessions": 12}})),
        app_key=DYNA_APP_KEY, captured_at=1)
    assert partial["corpus_usage"]["sessions"] == 12

    dead = dyna_adapter.corpus_context(
        CallRecorder("cafe0000deadbeef", mcp=_mcp({})), app_key=DYNA_APP_KEY, captured_at=1)
    assert dead["corpus_usage"] is None


def test_corpus_tools_are_not_a_discovery_gate():
    """전사 4종은 발견 게이트가 아니다 — 넣으면 그 도구 없는 게이트웨이에서 dyna 가 통째로 죽는다(§2.13.2)."""
    assert set(dyna_adapter.CORPUS_TOOLS) == {
        "corpus_summary", "material_usage", "section_contact_usage", "operation_usage"}
    # 정본 §2.13.2 의 dyna 집합.
    assert set(dyna_adapter.REQUIRED_TOOLS) == {
        "inspect_file", "list_session_files", "report_summary", "report_part_risk", "report_energy_flow"}
    assert set(dyna_adapter.CORPUS_TOOLS) & set(dyna_adapter.REQUIRED_TOOLS) == set()


def test_dyna_result_absent_without_reports():
    recorder = CallRecorder("cafe0000deadbeef", mcp=_mcp({}))
    result = dyna_adapter.DynaResultAdapter(DYNA_APP_KEY).capture({}, _principal(), recorder)
    assert result["results"] is None and result["missing"] == {"dyna_result_absent": True}
    assert recorder.calls == []


def _report_mcp(by_report: dict, extra: dict | None = None) -> McpHttpClient:
    """report_summary 만 report_id 별로 다른 응답을 주는 MCP 전송."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}},
                                  headers={"mcp-session-id": "sess-1"})
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        name = payload["params"]["name"]
        args = payload["params"]["arguments"]
        if name == "report_summary":
            body = by_report.get(str(args.get("report_id")))
        else:
            body = (extra or {}).get(name)
        if body is None:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
                "isError": True, "content": [{"type": "text", "text": f"unknown: {name}"}]}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": body}})

    return McpHttpClient("https://gw.test/mcp", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_dyna_result_flags_kind_mismatch():
    """지정한 리포트의 kind 가 섞이면 results 를 만들지 않고 result_kind_mismatch 를 세운다(plan §2.2)."""
    recorder = CallRecorder("cafe0000deadbeef", mcp=_report_mcp({
        "r1": {"id": "r1", "kind": "deep", "summary": "요약", "sim_params": {}},
        "r2": {"id": "r2", "kind": "sphere", "summary": "요약", "sim_params": {}},
    }))
    result = dyna_adapter.DynaResultAdapter(DYNA_APP_KEY).capture(
        {"report_ids": ["r1", "r2"]}, _principal(), recorder)
    assert result["results"] is None
    assert result["missing"] == {"result_kind_mismatch": True}
    assert [w["code"] for w in result["warnings"]] == ["result_kind_mismatch"]


def test_dyna_result_builds_results_overlay():
    summary = {"id": "r1", "kind": "sphere", "label": "낙하", "summary": "요약", "n_cases": 12,
               "sim_params": {"unit_system": "mm-kg-ms", "drop_height": 1.2,
                              "impactor": {"mass": 0.5, "velocity": 4.85}}}
    extra = {
        "report_part_risk": {"report_id": "r1", "kind": "sphere", "parts": [
            {"part_id": "1", "part_name": "Stack\\PLATE_1", "worst_stress": {"value": 210.0, "case_key": "0deg"},
             "worst_g": {"value": 900.0}, "worst_disp": None, "min_safety_factor": None}]},
        "report_findings": [{"severity": "WARNING", "title": "국부 항복", "detail": "…", "recommendation": "…"}],
        "report_worst_cases": [{"case_key": "0deg", "identity": {"angle": 0}, "max_stress": 210.0,
                                "max_g": 900.0, "max_disp": 1.1, "min_safety_factor": None}],
        "report_energy_flow": {"edges": [{"src": 1, "dst": 2, "name": "tie1", "peak_force": 12.0,
                                          "total_work": 3.0, "confidence": "low"}]},
    }
    recorder = CallRecorder("cafe0000deadbeef", mcp=_report_mcp({"r1": summary}, extra))
    result = dyna_adapter.DynaResultAdapter(DYNA_APP_KEY).capture(
        {"report_ids": ["r1"], "dyna_source_hash": KSHA, "pid_to_nid": {"1": f"dyna:{KSHA[:8]}:1"}},
        _principal(), recorder)
    results = result["results"]
    assert results["kind"] == "sphere" and results["report_ids"] == ["r1"]
    assert results["part_risk"][0]["nid"] == f"dyna:{KSHA[:8]}:1"
    assert results["part_risk"][0]["min_safety_factor"] is None      # sphere 는 항상 null 이다
    assert [f["severity"] for f in results["findings"]] == ["WARNING"]
    assert results["worst_cases"][0]["case_key"] == "0deg"
    # src/dst 가 pid 임을 확정하기 전이라 load_path 엣지는 만들지 않고 원문만 둔다.
    assert result["edges"] == [] and len(results["energy_edges"]) == 1
    assert result["source"]["binding"] == {"bound_to_dyna_source_hash": KSHA, "method": "user_declared"}
    assert len(results["sim_params_hash"]) == 64


def test_group_of_follows_report_parser_rule():
    assert dyna_adapter.group_of("Stack\\PLATE_1") == "Stack"
    assert dyna_adapter.group_of("Housing/Top") == "Housing"
    assert dyna_adapter.group_of("PLATE") == "Other"


# ---------------------------------------------------------------- ecad 스텁
def test_ecad_stub_is_contract_only():
    recorder = CallRecorder("cafe0000deadbeef", mcp=_mcp({}))
    result = ecad_stub.EcadStubAdapter().capture({}, _principal(), recorder)
    assert result["nodes"] == [] and result["edges"] == []
    assert result["degraded"] == ["ecad_absent"] and result["missing"] == {"ecad_absent": True}
    assert recorder.calls == []
    assert ecad_stub.REQUIRED_TOOLS == ("odb_get_board", "odb_list_components", "odb_list_nets",
                                        "odb_get_stackup")


# ---------------------------------------------------------------- capture_all → freeze_snapshot
def test_capture_all_requires_at_least_one_connected_source():
    """mcad 가 없어도 dyna 단독 캡처는 선다 — 소스가 아예 0 일 때만 409 다(plan §2.2·§0.9 P2-13)."""
    with pytest.raises(AppError) as err:
        adapters_registry.capture_all(sources=[], principal=_principal())
    assert err.value.http_status == 409 and err.value.code == "source_unreachable"

    with pytest.raises(AppError) as unknown_kind:
        adapters_registry.capture_all(sources=[{"kind": "sketchup", "ref": {}}], principal=_principal())
    assert unknown_kind.value.http_status == 409


def test_capture_all_freezes_snapshot_with_matching_call_ids(risk_store):
    risk_store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("p_cap", OWNER, "DV1", 100, 100))
    tools = dict(MCP_TOOLS_FULL, inspect_file=INSPECT_FILE, material_usage={}, section_contact_usage={},
                 corpus_summary={},
                 report_summary={"id": "r1", "kind": "sphere", "summary": "요약", "sim_params": {}},
                 report_part_risk={"parts": [{"part_id": "1", "part_name": "Stack\\PLATE_1",
                                              "worst_stress": {"value": 210.0, "case_key": "0deg"},
                                              "worst_g": {"value": 900.0}, "worst_disp": None,
                                              "min_safety_factor": None}]},
                 report_findings=[], report_worst_cases=[], report_energy_flow={"edges": []})
    mcp_client = _mcp(tools)
    rest_client = _rest(REST_ROUTES)
    captured = adapters_registry.capture_all(
        sources=[{"kind": "mcad", "app_key": APP_KEY, "ref": {"stepforge_project_id": SF_PROJECT,
                                                              "detect_job_id": "01JDET"}},
                 {"kind": "dyna", "app_key": DYNA_APP_KEY, "ref": {"session_id": "01JSES", "file_id": "01JFIL",
                                                                   "sha256": KSHA}},
                 {"kind": "dyna_result", "app_key": DYNA_APP_KEY, "ref": {"report_ids": ["r1"]}}],
        principal=_principal(), mcp_client=mcp_client, rest_client=rest_client)
    kinds = [r["source"]["kind"] for r in captured["results"]]
    assert kinds == ["mcad", "dyna", "dyna_result", "ecad"]
    # dyna_result 는 dyna 뒤에 와야 pid→nid 를 넘겨받는다(결과층 오버레이가 nid 로 붙는다).
    overlay = captured["results"][2]["results"]["part_risk"][0]
    assert overlay["nid"] == ir_builder.make_nid(f"dyna:{KSHA[:8]}:1")
    assert captured["results"][2]["source"]["binding"]["bound_to_dyna_source_hash"] == KSHA

    frozen = ir_builder.freeze_snapshot(
        risk_store, project_id="p_cap", owner_sub=OWNER, label="DV1",
        adapter_results=captured["results"], calls=captured["calls"],
        snapshot_id=captured["snapshot_id"], captured_at=1756600000)
    assert frozen["reused"] is False and len(frozen["ir_hash"]) == 64
    ir = ir_builder.load_ir(risk_store, frozen["snapshot_id"])
    assert ir["missing"]["ecad_absent"] is True and ir["missing"]["dyna_absent"] is False
    assert {n["domain"] for n in ir["nodes"]} == {"mcad", "dyna"}
    # 결과층이 dyna 노드 위에 오버레이로 붙는다(nid 사상이 맞아야 살아난다).
    overlaid = [n for n in ir["nodes"] if (n["attrs"].get("results") or {}).get("worst_stress")]
    assert [n["local_key"] for n in overlaid] == ["1"]

    # provenance.call_id 가 rr_snapshot_calls 의 실제 행 id 와 일치해야 인용 tool:<call_id> 가 산다.
    rows = {r["call_id"] for r in ir_builder.load_calls(risk_store, frozen["snapshot_id"],
                                                        include_response=False)}
    used = {n["provenance"]["call_id"] for n in ir["nodes"] if n["provenance"].get("call_id")}
    assert used and used <= rows
    logged = {r["tool"] for r in ir_builder.load_calls(risk_store, frozen["snapshot_id"],
                                                       include_response=False)}
    assert f"GET /apps/step_forge/api/projects/{SF_PROJECT}/tree" in logged

    # 같은 원문으로 다시 동결하면 같은 ir_hash 라 기존 스냅샷을 재사용한다(결정론).
    again = ir_builder.freeze_snapshot(
        risk_store, project_id="p_cap", owner_sub=OWNER, label="DV1",
        adapter_results=captured["results"], calls=[], snapshot_id=captured["snapshot_id"],
        captured_at=1756600000)
    assert again["reused"] is True and again["ir_hash"] == frozen["ir_hash"]


# ---------------------------------------------------------------- 응답 계약·소스 앱 버전(plan §2.13.1 · §0.9 P1-21)
def test_response_contract_catches_two_drift_shapes():
    """필드 누락과 타입 변경 둘 다 계약 위반이다 — 없는 계약은 검사 대상이 아니다(contract_ok=None)."""
    from app.adapters import base as adapters_base

    ok = adapters_base.check_contract("list_parts", {"parts": [{"id": 1}]})
    assert ok["contract_ok"] is True and ok["missing"] == [] and ok["type_mismatch"] == []

    missing = adapters_base.check_contract("list_parts", {"items": []})
    assert missing["contract_ok"] is False and missing["missing"] == ["/parts"]

    wrong_type = adapters_base.check_contract("list_parts", {"parts": {"0": {"id": 1}}})
    assert wrong_type["contract_ok"] is False and wrong_type["type_mismatch"] == ["/parts"]

    # 게이트웨이 접두형 이름도 같은 계약을 탄다.
    assert adapters_base.check_contract("heaxstep_forge_list_parts", {"parts": []})["contract_ok"] is True
    assert adapters_base.check_contract("모르는도구", {})["contract_ok"] is None


def test_app_version_probe_is_one_call_and_survives_failure():
    """system_status 를 1회만 부르고, 못 읽으면 version=null 이며 캡처는 계속된다."""
    from app.adapters import base as adapters_base

    tools = dict(MCP_TOOLS_FULL)
    tools["heaxstep_forge_system_status"] = {"version": "0.4.1", "build": "abc"}
    seen: list = []
    recorder = CallRecorder("cafe0000deadbeef", mcp=_mcp(tools, seen))
    version = adapters_base.probe_app_version(recorder, "mcad", app_key=APP_KEY)
    assert version["version"] == "0.4.1" and version["captured_via"] == "heaxstep_forge_system_status"
    assert version["extra"] == {"build": "abc"}
    assert [name for name, _args in seen] == ["heaxstep_forge_system_status"]

    blind = CallRecorder("cafe0000deadbeef", mcp=_mcp(MCP_TOOLS_FULL, []))
    assert adapters_base.probe_app_version(blind, "mcad") == adapters_base.UNKNOWN_APP_VERSION


def test_two_captures_differing_only_in_app_version_share_the_ir_hash():
    """소스 앱 버전은 ir_hash 입력이 아니다 — 버전만 다른 두 캡처는 같은 스냅샷이다(plan §2.2)."""
    from app import ir_builder

    first, _ = _capture_mcad()
    second, _ = _capture_mcad()
    second["source"]["app_version"] = {"version": "9.9.9", "captured_via": "heaxstep_forge_system_status",
                                       "extra": None}
    ir_a = ir_builder.build_ir(project_id="p" * 32, owner_sub=OWNER, label="DV1",
                               adapter_results=[first], snapshot_id="a" * 32, captured_at=1756600000)
    ir_b = ir_builder.build_ir(project_id="p" * 32, owner_sub=OWNER, label="DV1",
                               adapter_results=[second], snapshot_id="b" * 32, captured_at=1756600000)
    assert ir_a["ir_hash"] == ir_b["ir_hash"]


def test_contract_result_is_recorded_on_every_call_row():
    """호출마다 contract_ok·contract_missing 이 행에 남는다(NULL = 계약 미정의)."""
    tools = dict(MCP_TOOLS_FULL)
    tools["list_parts"] = {"items": []}          # 계약 위반(필드 누락)
    recorder = CallRecorder("cafe0000deadbeef", mcp=_mcp(tools, []))
    ok = recorder.call("mcp", "interface_graph", {}, source_kind="mcad")
    bad = recorder.call("mcp", "list_parts", {}, source_kind="mcad")
    unknown = recorder.call("mcp", "job_status", {"job_id": "x"}, source_kind="mcad")
    assert ok["contract_ok"] is True
    assert bad["contract_ok"] is False and bad["contract_missing"] == ["/parts"]
    assert unknown["contract_ok"] is None
    logged = {c["tool"]: c for c in recorder.calls}
    assert logged["list_parts"]["contract_missing"] == ["/parts"]
    assert logged["job_status"]["contract_ok"] is None


# ------------------------------------------------- 호출 시점 이름 해석(정본 §2.13.2 · 통과 기준 (23)(a))
def test_a_prefixed_tool_is_called_by_its_real_name_and_logged_that_way():
    """정본 §2.13.2 — "게이트웨이 실이름(접두 포함형)을 **호출 인자와** rr_snapshot_calls.tool 에 적는다".

    suffix 매칭이 probe 에만 있고 호출은 맨이름으로 나가면, 게이트웨이가 이름 충돌로 접두를 붙이는
    순간 그 호출들이 **조용히 전멸한다** — probe 는 suffix 로 찾으니 '도구 있음' 으로 보고하고
    실패는 어댑터 쪽에서만 난다.
    """
    # 게이트웨이에는 접두형만 있다(맨이름 job_status 는 없다).
    tools = {"heaxstep_forge_job_status": JOB_STATUS_DONE}
    seen: list = []
    recorder = CallRecorder("cafe0000deadbeef", mcp=_mcp(tools, seen),
                            tool_names=("heaxstep_forge_job_status", "heaxkooremapper_mcp_inspect_file"))

    out = recorder.call("mcp", "job_status", {"job_id": "J1"}, source_kind="mcad")

    assert out["ok"] is True, "맨이름으로 불러 조용히 실패했다"
    assert [n for n, _ in seen] == ["heaxstep_forge_job_status"], "호출 인자가 맨이름이었다"
    assert [c["tool"] for c in recorder.calls] == ["heaxstep_forge_job_status"], "원장이 맨이름이었다"


def test_name_resolution_keeps_the_contract_check_on_the_bare_name():
    """계약표는 맨이름 키다 — 실이름으로 찾으면 검사가 조용히 꺼진다(계약 위반이 전부 통과한다)."""
    tools = {"heaxstep_forge_list_parts": {"items": []}}      # 계약 위반(필드 누락)
    recorder = CallRecorder("cafe0000deadbeef", mcp=_mcp(tools, []),
                            tool_names=("heaxstep_forge_list_parts",))

    out = recorder.call("mcp", "list_parts", {}, source_kind="mcad")

    assert out["contract_ok"] is False and out["contract_missing"] == ["/parts"]


def test_an_ambiguous_name_is_not_guessed():
    """한 맨이름에 후보가 둘이면 아무 쪽이나 고르지 않는다 — 남의 백엔드를 부르는 것보다 실패가 낫다.

    그 상태는 probe 의 `ambiguous_tool_name` 이 이미 드러낸다(§2.13.2).
    """
    names = ("heaxstep_forge_job_status", "heaxkooremapper_mcp_job_status")
    assert adapters_base.resolve_tool_name("job_status", names) == "job_status"
    # 맨이름이 실제로 있으면 그것이 정답이다(접두형이 함께 있어도).
    assert adapters_base.resolve_tool_name("job_status", (*names, "job_status")) == "job_status"
    # 발견이 안 됐으면(빈 목록) 예전처럼 맨이름이다.
    assert adapters_base.resolve_tool_name("job_status", ()) == "job_status"


def test_gateway_tool_names_caches_and_survives_failure(monkeypatch):
    """이름 목록은 발견과 같은 TTL 로 캐시한다 — 캡처 한 번에 지도를 여러 번 받아 오지 않는다."""
    adapters_registry.reset_discovery_cache()
    seen: list = []
    body = {"map": {"heaxstep_forge_list_parts": APP_KEY, "job_status": "other"}}
    client = _tools_map_client(body, seen)

    first = adapters_registry.gateway_tool_names(client=client)
    second = adapters_registry.gateway_tool_names(client=client)

    assert first == ("heaxstep_forge_list_parts", "job_status") and second == first
    assert len(seen) == 1, "캐시가 듣지 않았다"

    # 게이트웨이가 죽어 있으면 빈 튜플이다(맨이름으로 부른다) — 발견 실패가 캡처를 막지 않는다.
    adapters_registry.reset_discovery_cache()
    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no gateway")
    assert adapters_registry.gateway_tool_names(
        client=httpx.Client(transport=httpx.MockTransport(dead))) == ()
    adapters_registry.reset_discovery_cache()


def test_a_truncated_tree_discards_mcad_instead_of_building_a_clipped_ir():
    """정본 §2.5.1·§2.13.3 — `nodes` 키가 없으면 mcad 를 **통째로 버린다**.

    리프 > 500 이면 소스가 `nodes` 키를 빼고 `{summary, warnings, note}` 만 준다. 그때 계속 진행하면
    `list_parts`(500 클램프, truncated 플래그 없음)로 노드를 만들어 **501번째부터 조용히 사라진 IR** 을
    '정상' 으로 동결한다 — 그 파트가 낀 간섭이 함께 사라지므로 '없는 리스크' 가 된다.
    §2.2 degraded 표는 이 경로를 "실무 어셈블리에서는 상시 경로" 라고 적는다.
    """
    truncated = {"summary": {"files": 1, "nodes": 900, "leaf_instances": 620, "assemblies": 40,
                             "max_depth": 5, "auto_named_nodes": 3},
                 "warnings": [], "note": "노드가 500을 넘어 목록을 생략했다."}
    tools = dict(MCP_TOOLS_FULL, project_tree=truncated)
    result, _ = _capture_mcad(tools=tools, rest_token=None)

    assert result["nodes"] == [] and result["edges"] == [], "요약만으로 노드·엣지를 지어냈다"
    # 정본 §2.2 missing 표 — `<kind>_capture_failed` 는 `<kind>_absent` 와 **함께** 선다.
    assert result["missing"] == {"mcad_capture_failed": True, "mcad_absent": True}
    assert "tree_truncated" in result["degraded"]
    assert [w["code"] for w in result["warnings"]] == ["tree_truncated"]
    # 소스 행은 남는다 — 무엇을 어떻게 불렀는지가 원장에 있어야 사람이 원인을 본다.
    source = result["source"]
    assert source["kind"] == "mcad" and source["stats"]["leaf_instances"] == 620
    assert source["ref"]["step_files"] == [] and source["source_hash"]


def test_a_truncated_tree_stops_before_the_interface_calls():
    """노드를 못 만들면 계면도 못 만든다 — 끝점을 해석할 노드가 없으므로 호출을 더 내보내지 않는다."""
    truncated = {"summary": {"leaf_instances": 620}, "warnings": [], "note": "생략"}
    seen: list = []
    _capture_mcad(tools=dict(MCP_TOOLS_FULL, project_tree=truncated), rest_token=None, mcp_seen=seen)

    called = [name for name, _ in seen]
    assert "project_tree" in called
    assert "list_interfaces" not in called and "interface_graph" not in called
    assert "list_parts" not in called, "버릴 트리인데 파트 목록까지 받아 왔다"


def test_the_ir_marks_a_failed_mcad_capture_and_drops_its_geometry_gates():
    """버린 mcad 가 IR 에서 어떻게 보이나 — 노드 0건 · 두 플래그 · 형상층 게이트 pass=null."""
    from app import state as state_module

    truncated = {"summary": {"files": 1, "nodes": 900, "leaf_instances": 620},
                 "warnings": [], "note": "생략"}
    mcad_result, _ = _capture_mcad(tools=dict(MCP_TOOLS_FULL, project_tree=truncated), rest_token=None)
    dyna = dyna_adapter.DynaAdapter(DYNA_APP_KEY).capture(
        {"session_id": "01JSES", "file_id": "01JFIL", "sha256": KSHA}, _principal(),
        CallRecorder("cafe0000deadbeef", mcp=_mcp({"inspect_file": INSPECT_FILE})))

    ir = ir_builder.build_ir(project_id="p" * 32, owner_sub=OWNER, label="DV1",
                             adapter_results=[mcad_result, dyna], snapshot_id="c" * 32,
                             captured_at=1756600000)

    assert ir["missing"]["mcad_capture_failed"] is True
    assert ir["missing"]["mcad_absent"] is True
    # mcad 가 없으니 정본 소스는 dyna 다(§2.2) — 노드는 dyna 것만 남는다.
    assert {n["domain"] for n in ir["nodes"]} == {"dyna"}
    state = state_module.build_state(ir)
    # 형상층 게이트는 '위반 0건' 이 아니라 '입력 없음' 이다(§2.12) — 아니면 통과로 읽힌다.
    assert state["gates"]["G3"]["pass"] is None
    assert state["gates"]["G3"]["reason"] == "mcad_absent"
