# F2 단면 자리 찾기 시험 — 손 셈 예로 변환을 적고(검증 · 강제 · 감사) refdes · 넷 · 보드 좌표 · 리스크 항목을 MCAD 점 · 몸체 · 단면 둘로 찾는다(게이트웨이 대역 · 실제 캡처로 지은 스냅샷)
"""설계 docs/f2-locate-for-section.md.

  · 게이트웨이 대역은 httpx 전송 한 곳이다(소켓 0). 답의 꼴은 ODB 허브 레퍼런스(포털 docs/procedures/fixtures/odb-hub/reference.md §4.6 ·
    §4.10 · §4.11)와 StepForge 원문(app/mcp_server.py part_info · corner_proximity)의 꼴이다 — 실물은 cae00 에서 처음 본다(설계 6절).
  · 보드는 손 셈 예다 — `x_CAD = 82.13 − x_ODB`, `y_CAD = y_ODB + 2.82`, ODB top = CAD 보드 몸체의 아래 면(z 0.5). 외곽 70 × 50 mm 이고
    대칭이 아닌 고정홀 셋이 있다(tests/test_board_transform.py 와 같은 보드).
  · 스냅샷은 실제 캡처(adapters_registry.capture_all — mcad 는 StepForge REST 트리, ecad 는 tests/test_ecad_adapter 의 가짜 허브)로 짓는다.

  실행:  .venv/bin/python -m pytest tests/test_locate_for_section.py
"""
from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

import app.mcp_server as srv
from app import board_transform as bt
from app import config, export, identity, ir_builder, routes
from app.common import now_epoch
from app.errors import AppError
from tests import factories
from tests import test_adapters as recon
from tests.test_ecad_adapter import JOB_STD, FakeOdbHub
from tests.test_ecad_adapter import _capture as capture_with_hub

OWNER = "f2-owner@example.com"
EDITOR = "f2-editor@example.com"
VIEWER = "f2-viewer@example.com"
STRANGER = "f2-stranger@example.com"
NOPAT = "f2-nopat@example.com"
PATS = {OWNER: "owner-pat-not-real", EDITOR: "editor-pat-not-real", VIEWER: "viewer-pat-not-real", STRANGER: "stranger-pat-not-real"}
BOX_PAT = "box-read-pat-not-real"
SF = "019f2phone000000000000a1"
JOB = JOB_STD
PCB = "/PHONE/phone.step/PHONE_ASM/MAIN_PCB"

# ---------------------------------------------------------------- 손 셈 보드(ODB 좌표)와 그 CAD(같은 보드를 손 셈 변환으로 옮긴 것)
HAND = {"mirror_x": True, "mirror_y": False, "offset_x": 82.13, "offset_y": 2.82, "top_face": "zmin"}
VOLUME = {"grand_total_mm3": 2275.0, "pkg_mass_kg": 0.004,
          "board": {"outline_area_mm2": 3500.0, "x_mm": 70.0, "y_mm": 50.0, "thickness_mm": 0.65, "signal_layers": 8,
                    "volume_mm3": 2275.0, "stackup_verdict": "standard", "stackup_id": "SU47-0.65T-8L-030"},
          "report_url": "http://odb-hub.test/api/jobs/x/report/volume"}
HOLES = {"hole_count": 3, "cutout_count": 0, "summary": "고정홀 3개",
         "holes": [{"x": 8.0, "y": -44.0, "diameter_mm": 1.6, "nominal_mm": 1.6, "kind": "BOTH", "plating": "PLATED",
                    "mount_attr": True, "confidence": "HIGH"},
                   {"x": 70.0, "y": -5.0, "diameter_mm": 1.6, "nominal_mm": 1.6, "kind": "BOTH", "plating": "PLATED",
                    "mount_attr": True, "confidence": "HIGH"},
                   {"x": 40.0, "y": -30.0, "diameter_mm": 2.0, "nominal_mm": 2.0, "kind": "BOTH", "plating": "NON_PLATED",
                    "mount_attr": True, "confidence": "HIGH"}],
         "page": 1, "page_size": 100, "returned": 3, "total": 3, "has_more": False}
PCB_BOX = [7.13, -45.18, 0.5, 77.13, 4.82, 1.15]
PART_INFO = {"id": "n2", "name": "MAIN_PCB", "path": PCB, "kind": "solid", "volume": 2275.0, "bbox": [0, 0, 0, 70.0, 50.0, 0.65],
             "world_bbox": PCB_BOX, "world_center": [42.13, -20.18, 0.825], "material": {"step": "FR4", "manual": None}, "tags": [],
             "meta": {}, "interfaces": [], "interface_count": 0, "mesh": []}
CORNER = {"project": "PHONE", "considered": 1, "scanned": 1, "with_holes": 1, "unexamined": 0, "partial": False,
          "unexamined_parts": 0, "unexamined_list": [], "scan_budget_s": None, "unit": "mm",
          "parts": [{"part": "MAIN_PCB", "path": PCB, "ok": True, "holes": 3, "obb_extents_mm": [70.0, 50.0, 0.65],
                     "diagonal_mm": 86.04, "min_distance_mm": 3.0, "worst": None, "skipped_voids": 0, "unexamined": 0,
                     "hole_list": [{"radius_mm": 0.8, "center": [74.13, -41.18, 0.5], "axis": [0.0, 0.0, 1.0]},
                                   {"radius_mm": 0.8, "center": [12.13, -2.18, 1.15], "axis": [0.0, 0.0, -1.0]},
                                   {"radius_mm": 1.0, "center": [42.13, -27.18, 0.825], "axis": [0.0, 0.0, 1.0]},
                                   {"radius_mm": 0.4, "center": [30.0, -1.0, 0.8], "axis": [1.0, 0.0, 0.0]}]}],
          "note": "거리는 꼭짓점에서 구멍 축선까지의 수직거리다"}


def _detail(refdes: str, x: float, y: float, side: str | None, pins: list[tuple[float, float]], **more: Any) -> dict:
    """get_part_detail(레퍼런스 §4.6 꼴) — 핀마다 넷 · 좌표."""
    out = {"refdes": refdes, "pkg_name": "bga41f_W235L235_SB019_1_LT", "pkg_width": 2.4, "pkg_length": 1.2, "x": x, "y": y,
           "rotation": 0.0, "mirror": side == "bottom", "device_type": "IC", "type": "IC", "pin_count": len(pins),
           "pins": [{"pin_num": i, "name": f"A{i + 1}", "net": "N1", "pad": "r190", "x": px, "y": py} for i, (px, py) in enumerate(pins)],
           "pins_truncated": False, "net_count": 1, **more}
    if side is not None:
        out["side"] = side
    return out


# U1001 은 top 면(손 셈 — CAD 아래 면 z 0.5 의 −z 쪽)이고 핀이 x 로 길다(2.4 × 1.2). U1003 은 bottom 면이고 CAD 에 몸체가 없다.
DETAILS = {
    "U1001": _detail("U1001", 30.0, -20.0, "top", [(28.8, -20.6), (31.2, -20.6), (28.8, -19.4), (31.2, -19.4)]),
    "U1003": _detail("U1003", 45.0, -12.0, "bottom", [(44.5, -13.0), (45.5, -13.0), (44.5, -11.0), (45.5, -11.0)]),
    # 허브 답에 side 가 없는 부품 — 스냅샷의 ECAD 부품 노드(U1002 는 가짜 허브의 top 부품)에서 면을 읽는다.
    "U1002": _detail("U1002", 20.0, -40.0, None, [(19.0, -40.5), (21.0, -40.5), (19.0, -39.5), (21.0, -39.5)]),
    "U1005": _detail("U1005", 60.0, -40.0, None, [(59.0, -40.5), (61.0, -40.5)]),
}

# ---------------------------------------------------------------- CAD 트리(StepForge REST tree.json 꼴) — 실제 mcad 어댑터가 노드를 짓는다
BODIES = [
    ("MAIN_PCB", PCB_BOX, "FR4"),
    ("U1001_BODY", [50.93, -17.78, -0.3, 53.33, -16.58, 0.5], "EMC"),      # 손 셈 자리(52.13, −17.18)의 부품 몸체 — 아래 면 밑
    ("SHIELD_CAN_1", [40.0, -25.0, -1.2, 60.0, -10.0, 0.5], "SUS"),        # U1001 을 덮는 쉴드캔(bbox 가 품을 뿐이다)
    ("REAR_HOUSING", [0.0, -60.0, -3.0, 90.0, 10.0, 5.0], "PC"),          # 다 품는 하우징
    ("SCREW_M14#1", [73.33, -41.98, -1.0, 74.93, -40.38, 1.65], "STEEL"),  # 같은 나사 둘 — 이름 꼬리 #n 을 떼면 같아 같은 정규 키다(모호한 주제)
    ("SCREW_M14#2", [11.33, -2.98, -1.0, 12.93, -1.38, 1.65], "STEEL"),
]


def _tree() -> dict:
    nodes = [{"id": "n0", "parent_id": None, "kind": "file", "name": "phone.step", "path": "/PHONE/phone.step", "depth": 1, "seq": 0,
              "shape_def_id": None, "transform": None, "world_transform": None, "auto_named": False, "color": None},
             {"id": "n1", "parent_id": "n0", "kind": "assembly", "name": "PHONE_ASM", "path": "/PHONE/phone.step/PHONE_ASM", "depth": 2,
              "seq": 1, "shape_def_id": None, "transform": None, "world_transform": None, "auto_named": False, "color": None}]
    defs: dict[str, dict] = {}
    for i, (name, box, material) in enumerate(BODIES, start=2):
        size = [box[3] - box[0], box[4] - box[1], box[5] - box[2]]
        shape = "s-screw" if name.startswith("SCREW") else f"s{i}"
        defs[shape] = {"kind": "solid", "bbox": [0.0, 0.0, 0.0, *size], "volume": size[0] * size[1] * size[2], "area": None,
                       "centroid": [v / 2 for v in size], "material": material, "density": None, "density_unit": None,
                       "instance_count": 2 if shape == "s-screw" else 1, "has_geometry": 1, "solid_count": 1,
                       "construction_only": False, "xcaf_entry": f"0:1:1:{i}", "step_file": "phone.step"}
        nodes.append({"id": f"n{i}", "parent_id": "n1", "kind": "instance", "name": name, "path": f"/PHONE/phone.step/PHONE_ASM/{name}",
                      "depth": 3, "seq": i, "shape_def_id": shape, "transform": None,
                      "world_transform": [[1, 0, 0, box[0]], [0, 1, 0, box[1]], [0, 0, 1, box[2]], [0, 0, 0, 1]],
                      "auto_named": False, "color": None})
    return {"project": "PHONE", "unit_system": "mm",
            "files": [{"relpath": "phone.step", "sha256": "1" * 64, "size_bytes": 4096, "schema_ap": "AUTOMOTIVE_DESIGN",
                       "header_unit": "millimetre"}],
            "nodes": nodes, "shape_defs": defs,
            "summary": {"files": 1, "shape_defs": len(defs), "nodes": len(nodes), "assemblies": 1, "instances": len(BODIES),
                        "leaf_instances": len(BODIES), "max_depth": 3, "auto_named_nodes": 0, "auto_named_defs": 0,
                        "defs_without_geometry": 0, "warnings": 0},
            "warnings": []}


def _cad_routes() -> dict:
    base = f"/apps/step_forge/api/projects/{SF}"
    tree = _tree()
    parts = [{"id": n["id"], "shape_def_id": n["shape_def_id"], "name": n["name"], "path": n["path"], "kind": "solid"}
             for n in tree["nodes"] if n["kind"] == "instance"]
    # 쉴드캔이 보드에 붙어 있다(tied) — 계면 주제의 원천.
    iface = {"counts": {"tied": 1}, "interfaces": [
        {"id": 7, "node_a": "n2", "node_b": "n4", "name_a": "MAIN_PCB", "name_b": "SHIELD_CAN_1", "kind": "tied", "min_gap": 0.0,
         "contact_area_est": 40.0, "band_width": 0.05, "penetration_depth": None, "penetration_volume": None, "cross_file": 0,
         "status": "auto", "note": None}]}
    return {base: {"id": SF, "name": "PHONE", "tol_config": {"tied_gap": 0.05, "clearance_gap": 1.0, "tied_area": 1.0,
                                                             "tied_width": 0.05}},
            f"{base}/tree": tree, f"{base}/artifacts/graph/": {"nodes": [], "edges": [], "orphans": [], "counts": {"tied": 1}},
            f"{base}/parts": {"parts": parts}, f"{base}/interfaces": iface}


# ---------------------------------------------------------------- 게이트웨이 대역
class Gateway:
    """게이트웨이 하나 — `/mcp`(JSON-RPC)와 `/tools-map`. 도구마다 답(본문 · 인자를 받아 본문을 내는 함수 · ('error', 글))을 정하고 받은
    요청마다 (무엇, 도구, 인자, Authorization)을 `seen` 에 적는다. 답은 FastMCP 가 dict 를 내는 꼴(들여쓰기 JSON 글 한 덩이)이다."""

    def __init__(self) -> None:
        self.answers: dict[str, Any] = {}
        self.tool_map: dict[str, str] = {}
        self.seen: list[tuple[str, str | None, dict | None, str | None]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization")
        if request.method == "GET" and request.url.path.endswith("/tools-map") and self.tool_map:
            self.seen.append(("tools-map", None, None, auth))
            return httpx.Response(200, json={"map": dict(self.tool_map)})
        if request.method != "POST" or not request.url.path.endswith("/mcp"):
            self.seen.append((f"{request.method} {request.url.path}", None, None, auth))
            return httpx.Response(404, json={"detail": "not found"})
        payload = json.loads(request.content.decode("utf-8") or "{}")
        method, rid = payload.get("method"), payload.get("id")
        if method == "initialize":
            self.seen.append(("initialize", None, None, auth))
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {}}, headers={"mcp-session-id": "sess-f2"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        name = str((payload.get("params") or {}).get("name") or "")
        args = dict((payload.get("params") or {}).get("arguments") or {})
        self.seen.append(("tools/call", name, args, auth))
        answer = self.answers.get(name, ("error", f"unknown tool: {name}"))
        if callable(answer):
            answer = answer(args)
        if isinstance(answer, tuple):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {
                "isError": answer[0] == "error", "content": [{"type": "text", "text": answer[1]}]}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {
            "isError": False, "content": [{"type": "text", "text": json.dumps(answer, ensure_ascii=False, indent=2)}]}})

    def calls(self, tool: str) -> list[tuple[dict | None, str | None]]:
        return [(args, auth) for what, name, args, auth in self.seen if what == "tools/call" and name == tool]

    def tools_called(self) -> list[str]:
        return [name for what, name, _args, _auth in self.seen if what == "tools/call"]

    def auths(self) -> set[str | None]:
        return {auth for *_rest, auth in self.seen}


def _hub_answers(gw: Gateway) -> None:
    gw.answers.update({
        "odbhub_get_volume_result": VOLUME, "odbhub_get_mounting_holes": HOLES, "heaxstep_forge_part_info": PART_INFO,
        "heaxstep_forge_corner_proximity": CORNER,
        "odbhub_get_part_detail": lambda a: copy.deepcopy(DETAILS.get(a.get("refdes"), {"error": "부품이 없습니다"})),
        "odbhub_get_net": lambda a: ({"name": a.get("net"), "pin_count": 2, "units": "mm", "layers": [],
                                      "pins": [{"refdes": "C1", "pin": "1", "x": 10.0, "y": -10.0},
                                               {"refdes": "C2", "pin": "2", "x": 16.0, "y": -12.0}]}
                                     if a.get("net") == "VBAT" else {"name": a.get("net"), "pin_count": 2, "units": "mm", "layers": []}),
    })


def _who(email: str, source: str = "bearer", role: str = "user") -> identity.Identity:
    return identity.Identity(email=email, display_name="F2", role=role, organization="qa", anonymous=False, source=source)


def _register(store, email: str) -> None:
    store.upsert_credential(email, identity.encrypt_pat(PATS[email]).decode("ascii"), "sub", email, "[]", now_epoch() + 30 * 86400)


@dataclass
class Box:
    store: Any
    gw: Gateway
    project: str


@pytest.fixture
def box(risk_store, monkeypatch) -> Box:
    """주인의 과제(편집자 · 보기 구성원)에 ECAD 보드(JOB)와 기구 CAD 원천(SF)이 붙어 있다. 박스 읽기 PAT 는 늘 있다 — 산 호출이 그것으로
    내려가지 않는지가 요지다. NOPAT 는 PAT 를 등록하지 않은 편집자다."""
    gw = Gateway()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: gw.handle(request))
    monkeypatch.setattr(config, "load_secrets", lambda *_a, **_k: {"HWAXRISK_PORTAL_PAT": BOX_PAT})
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    for email in PATS:
        _register(risk_store, email)
    owner = _who(OWNER)
    project = routes.create_project(routes.ProjectBody(code="F2-1", name="단면 자리", stage="DV1", classification="internal"),
                                    ident=owner)["id"]
    routes.put_members(project, routes.MembersBody(members=[routes.MemberItem(email=EDITOR, role="editor"),
                                                            routes.MemberItem(email=VIEWER, role="viewer"),
                                                            routes.MemberItem(email=NOPAT, role="editor")]), ident=owner)
    gw.tool_map = {"find_job": "odb-hub"}
    gw.answers["find_job"] = {"jobs": [{"job_id": JOB, "project": "PRJ-ALPHA", "model": "SM-X100", "board_type": "Main",
                                        "revision": "0.7", "original_filename": "alpha_main_r07.tgz", "uploaded_at": 1}]}
    routes.put_ecad_board(project, routes.EcadBoardBody(odb_job_id=JOB), ident=owner)
    routes.add_source(project, routes.SourceBody(kind="mcad", app_key="heax-step_forge", ref={"stepforge_project_id": SF}), ident=owner)
    _hub_answers(gw)
    gw.seen.clear()
    return Box(store=risk_store, gw=gw, project=project)


def _freeze(store, project: str, captured_at: int = 1761800000) -> dict:
    """실제 캡처(mcad REST 트리 + 가짜 ODB 허브)로 그 과제의 스냅샷을 얼린다 — IR 과 스냅샷 id. 캡처 시각은 기본이 등록보다 앞이다(등록 뒤에
    찍은 스냅샷은 captured_at 을 준다)."""
    hub = FakeOdbHub()
    hub.others = {name: body for name, body in recon.MCP_TOOLS_FULL.items()}
    hub.others["heaxstep_forge_list_parts"] = recon.MCP_TOOLS_FULL["list_parts"]
    card = {"kind": "mcad", "app_key": recon.APP_KEY, "ref": {"stepforge_project_id": SF}}
    captured = capture_with_hub(hub, JOB, extra_sources=[card], rest=recon._rest(_cad_routes()))
    frozen = ir_builder.freeze_snapshot(store, project_id=project, owner_sub=OWNER, label="cad", adapter_results=captured["results"],
                                        calls=captured["calls"], snapshot_id=captured["snapshot_id"], captured_at=captured_at)
    return {"snapshot_id": frozen["snapshot_id"], "ir": ir_builder.load_ir(store, frozen["snapshot_id"])}


@pytest.fixture
def frozen(box) -> dict:
    return _freeze(box.store, box.project)


def _put(box: Box, who: str = OWNER, *, via: str = "bearer", role: str = "user", **change: Any) -> dict:
    fields = {"board_body": PCB, **HAND, **change}
    return routes.put_board_transform(box.project, routes.BoardTransformBody(**fields), ident=_who(who, via, role))


def _locate(box: Box, who: str = OWNER, **inputs: Any) -> dict:
    return routes.get_locate(box.project, **{**dict.fromkeys(("finding_id", "target_key", "cluster_key", "refdes", "net", "x", "y",
                                                              "side", "odb_job_id", "stepforge_project_id")), **inputs},
                             ident=_who(who))


def _refused(call) -> AppError:
    with pytest.raises(AppError) as err:
        call()
    return err.value


def _audits(store, action: str = "project.board_transform") -> list[dict]:
    return [dict(r) for r in store.query("SELECT owner_sub, actor, actor_verified, channel, scope, subject_id, before_json, after_json,"
                                         " reason FROM rr_audit WHERE action = ? ORDER BY at, rowid", (action,))]


def _call(tool: str, /, **kwargs) -> dict:
    out = getattr(srv, tool)(**kwargs)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


# ================================================================ 변환 적기 — 검증 · 강제 · 감사
def test_the_hand_transform_registers_as_verified_with_one_audit_row_and_the_persons_pat_only(box):
    """손 셈을 적으면 이 박스에서 그 사람의 PAT 로 ODB 외곽 크기 · 고정홀과 CAD 보드 몸체 · 구멍을 읽어 검증하고(오차 0 · 짝 셋 · 모호하지
    않음) verified 로 적는다. 등록 때 읽은 몸체 z 범위가 남고 감사 한 줄이다. 축이 z 가 아닌 CAD 구멍은 짝에 쓰지 않는다. 같은 값을 다시 적으면
    다시 검증하되 감사는 없다. 박스 PAT 는 한 번도 나가지 않는다."""
    out = _put(box)
    reg = out["registration"]
    assert out["changed"] is True and out["previous"] is None
    assert (reg["status"], reg["error_mm"], reg["source"], reg["board_body_path"]) == ("verified", 0.0, "manual", PCB)
    assert reg["formula"] == "x_CAD = 82.13 − x_ODB · y_CAD = y_ODB + 2.82 · ODB top → CAD 아래 면(zmin) · 단위 mm"
    assert (reg["board_z_min"], reg["board_z_max"], reg["unit"]) == (0.5, 1.15, "mm")
    check = reg["verification"]
    assert check["ok"] and check["checks"]["holes"]["matched"] == 3 and check["checks"]["size"]["error_mm"] == 0.0
    assert check["checks"]["outline"]["measured"] is False                      # 지금 허브에는 외곽 bbox(OH-04)가 없다
    assert reg["evidence"]["cad"]["holes_off_axis"] == 1
    assert box.gw.calls("odbhub_get_mounting_holes") == [({"job_id": JOB, "page": 1, "page_size": 100}, f"Bearer {PATS[OWNER]}")]
    assert box.gw.calls("heaxstep_forge_corner_proximity") == [
        ({"project_id": SF, "part": PCB, "limit": 500, "full": True}, f"Bearer {PATS[OWNER]}")]
    assert box.gw.auths() == {f"Bearer {PATS[OWNER]}"}
    rows = _audits(box.store)
    assert [(r["actor"], r["channel"], r["scope"], r["subject_id"], r["before_json"]) for r in rows] == [
        (OWNER, "rest", "project", box.project, None)]
    assert json.loads(rows[0]["after_json"])["status"] == "verified" and rows[0]["reason"] is None

    again = _put(box)
    assert again["changed"] is False and again["previous"]["status"] == "verified" and len(_audits(box.store)) == 1
    listed = routes.get_board_transforms(box.project, ident=_who(VIEWER))
    assert [t["formula"] for t in listed["transforms"]] == [reg["formula"]] and listed["max_error_mm"] == bt.MAX_ERROR_MM


def test_a_wrong_mirror_is_refused_and_forcing_needs_a_reason_and_is_audited(box):
    """뒤집기를 빠뜨린 값은 검증을 지나지 못해 적지 않는다(422 transform_unverified — 까닭 · 오차 · 근거). 강제는 사유가 있어야 하고(422
    reason_required) 사유와 함께면 forced 로 적고 감사 행에 사유를 남긴다. 강제한 변환으로 찾은 자리는 경고를 단다."""
    wrong = {"mirror_x": False, "top_face": "zmax"}
    err = _refused(lambda: _put(box, **wrong))
    assert (err.code, err.http_status) == ("transform_unverified", 422)
    assert "holes_mostly_unmatched" in err.detail["verification"]["reasons"] and "position_unverified" in err.detail["verification"]["reasons"]
    assert routes.get_board_transforms(box.project, ident=_who(OWNER))["transforms"] == [] and _audits(box.store) == []
    err = _refused(lambda: _put(box, force=True, **wrong))
    assert (err.code, err.http_status) == ("reason_required", 422)
    forced = _put(box, force=True, reason="기구 도면으로 확인했다", **wrong)["registration"]
    assert forced["status"] == "forced" and forced["reason"] == "기구 도면으로 확인했다"
    assert _audits(box.store)[-1]["reason"] == "기구 도면으로 확인했다"
    # 강제한 (뒤집지 않은) 변환으로는 (30, −20) 이 보드 밖(x 112.13)이라 point_off_board 다 — 보드 안에 드는 좌표로 본다.
    assert _locate(box, x=30.0, y=-20.0)["reason"]["code"] == "point_off_board"
    found = _locate(box, x=-40.0, y=-20.0)
    assert found["status"] == "located" and found["warnings"][0].startswith("transform_forced")


def test_a_face_against_the_mirror_is_refused_even_when_every_hole_matches(box):
    """x 만 뒤집고 위 면이라 적으면 거울상이다 — 자리는 다 맞아도 거절한다(뒤집기와 면 가운데 하나만 틀린 부호 실수)."""
    err = _refused(lambda: _put(box, top_face="zmax"))
    assert err.detail["verification"]["reasons"] == ["handedness_mismatch"]


def test_an_unreadable_cad_board_is_never_written_even_when_forced(box):
    """CAD 보드 몸체를 못 읽으면 부품 면의 z 를 모른다 — 강제로도 적지 않는다."""
    box.gw.answers["heaxstep_forge_part_info"] = ("error", "그런 파트가 없다: /PHONE/nope — list_parts 로 확인할 것")
    err = _refused(lambda: _put(box, board_body="/PHONE/nope", force=True, reason="그래도"))
    assert (err.code, err.http_status) == ("transform_cad_board_unread", 422) and "그런 파트가 없다" in err.message


# ================================================================ 위치 찾기 — 보드 길
def test_a_top_side_part_lands_on_the_bottom_face_through_the_hand_transform(box, frozen):
    """손 셈 그대로 — U1001(ODB 핀 bbox 가운데 30, −20 · top 면)은 MCAD (52.13, −17.18) 이고 z 는 CAD 아래 면 0.5 다. 핀이 x 로 길어 앞
    평면은 y = −17.18(긴 축을 품는다), 뒤 평면은 x = 52.13 이다 — F1 에 그대로 넘길 꼴(unit mm). 그 자리 바로 바깥을 품는 가장 작은 몸체가
    부품 크기에 맞아 U1001_BODY 가 몸체다(쉴드캔 · 하우징은 후보로만)."""
    _put(box)
    box.gw.seen.clear()
    out = _locate(box, refdes="U1001")
    assert out["status"] == "located" and out["stepforge_project_id"] == SF and out["odb_job_id"] == JOB
    assert out["mcad"] == {"x": 52.13, "y": -17.18, "z": 0.5, "unit": "mm"}
    assert out["planes"] == [{"axis": "y", "offset": -17.18, "unit": "mm"}, {"axis": "x", "offset": 52.13, "unit": "mm"}]
    assert out["plane_basis"]["long_axis"] == "x" and out["plane_basis"]["basis"].startswith("pins")
    assert out["body"]["path"] == "/PHONE/phone.step/PHONE_ASM/U1001_BODY" and out["body"]["snapshot_id"] == frozen["snapshot_id"]
    assert [c["path"].rsplit("/", 1)[-1] for c in out["body_candidates"]] == ["U1001_BODY", "SHIELD_CAN_1", "REAR_HOUSING"]
    assert out["ecad"]["side"] == "top" and out["ecad"]["z_basis"].startswith("mount_face") and out["ecad"]["center_basis"] == "pins"
    assert out["transform"]["formula"].startswith("x_CAD = 82.13 − x_ODB") and out["transform"]["status"] == "verified"
    f1 = out["f1"]
    assert (f1["stepforge_project_id"], f1["point"], f1["part"], f1["planes"], f1["window_mm"]) == (
        SF, out["mcad"], out["body"]["path"], out["planes"], 10.0)
    assert box.gw.tools_called() == ["odbhub_get_part_detail"] and box.gw.auths() == {f"Bearer {PATS[OWNER]}"}


def test_a_bottom_side_part_sits_on_the_top_face_and_a_loose_box_is_not_called_its_body(box, frozen):
    """U1003(bottom 면)은 CAD 위 면(z 1.15)에 앉는다. 그 자리를 품는 몸체는 하우징뿐이라(부품 몸체가 CAD 에 없다) 몸체로 말하지 않고 후보로만
    싣는다 — 엉뚱한 몸체를 F1 에 넘기지 않는다."""
    _put(box)
    out = _locate(box, refdes="U1003")
    assert out["mcad"] == {"x": 37.13, "y": -9.18, "z": 1.15, "unit": "mm"}
    assert out["body"] is None and out["body_note"].startswith("bbox_only") and out["f1"]["part"] is None
    assert [c["path"].rsplit("/", 1)[-1] for c in out["body_candidates"]] == ["REAR_HOUSING"]
    # 핀이 y 로 길다(1 × 2) — 앞 평면은 x 법선이다.
    assert out["planes"][0] == {"axis": "x", "offset": 37.13, "unit": "mm"}


def test_an_ic_with_a_stand_off_under_a_shield_can_is_its_own_body(box, monkeypatch):
    """(반대 검토 R3) U2000(top 면 · 패키지 10 × 8 · 핀 9 × 7) — CAD 몸체가 보드 면에서 0.2 mm 떠 있고(볼 스탠드오프) 쉴드캔이 그것을 덮는다.
    종전에는 면 바로 바깥 0.05 mm 의 한 점만 찔러 IC 를 놓치고 쉴드캔(12 × 10 — 두 배 안)을 몸체 · F1 part 로 냈다. 이제 면 바깥 선분에 걸리는
    몸체 가운데 크기가 맞고 크기가 맞는 다른 후보를 품지 않는 것이 몸체다 — 쉴드캔은 IC 를 품어 빠진다."""
    pins = [(10.5, -33.5), (19.5, -33.5), (10.5, -26.5), (19.5, -26.5)]
    monkeypatch.setitem(DETAILS, "U2000", _detail("U2000", 15.0, -30.0, "top", pins, pkg_width=10.0, pkg_length=8.0))
    monkeypatch.setitem(globals(), "BODIES", list(BODIES) + [
        ("U2000_BODY", [62.13, -31.18, -0.9, 72.13, -23.18, 0.3], "EMC"),        # 보드 아래 면(0.5)에서 0.2 mm 떠 있다
        ("SHIELD_CAN_2", [61.13, -32.18, -1.3, 73.13, -22.18, 0.5], "SUS")])       # 보드 면에 붙어 IC 를 덮는다
    _freeze(box.store, box.project)
    _put(box)
    out = _locate(box, refdes="U2000")
    assert out["status"] == "located" and out["mcad"] == {"x": 67.13, "y": -27.18, "z": 0.5, "unit": "mm"}
    assert out["body"]["path"].endswith("/U2000_BODY") and out["f1"]["part"] == out["body"]["path"] and out["body_note"] is None
    fits = {c["path"].rsplit("/", 1)[-1]: c["fits_part"] for c in out["body_candidates"]}
    assert fits == {"U2000_BODY": True, "SHIELD_CAN_2": True, "REAR_HOUSING": False}


def test_a_tiny_body_at_the_part_centre_is_not_the_part(box, monkeypatch):
    """(반대 검토 R3b) U1001 가운데의 0.3 mm 볼 몸체 — 종전에는 크기에 아래 한계가 없어 찌른 점을 품는 가장 작은 몸체(볼)를 IC 의 몸체로 냈다.
    면내 두 변이 부품 크기의 절반 이상이어야 하므로 볼은 후보일 뿐이고 몸체는 U1001_BODY 다."""
    monkeypatch.setitem(globals(), "BODIES", list(BODIES) + [("U1001_BALL_C3", [51.98, -17.33, 0.2, 52.28, -17.03, 0.5], "SAC")])
    _freeze(box.store, box.project)
    _put(box)
    out = _locate(box, refdes="U1001")
    assert out["body"]["path"].endswith("/U1001_BODY")
    assert {c["path"].rsplit("/", 1)[-1]: c["fits_part"] for c in out["body_candidates"]}["U1001_BALL_C3"] is False


def test_a_same_size_body_stacked_on_the_part_is_not_the_part(box, monkeypatch):
    """부품 몸체 바깥 쪽에 같은 크기의 써멀 패드가 얹혀 있으면(선분이 둘 다 건드린다) 보드 면에 가까운 쪽이 실장된 부품이다 — 패드는 크기가
    맞는 후보일 뿐이다(PoP 의 위 패키지 · 덮개도 같다)."""
    monkeypatch.setitem(globals(), "BODIES", list(BODIES) + [("U1001_PAD", [50.93, -17.78, -0.6, 53.33, -16.58, -0.3], "SIL")])
    _freeze(box.store, box.project)
    _put(box)
    out = _locate(box, refdes="U1001")
    assert out["body"]["path"].endswith("/U1001_BODY")
    assert [c["path"].rsplit("/", 1)[-1] for c in out["body_candidates"] if c["fits_part"]] == ["U1001_PAD", "U1001_BODY"]


def test_two_bodies_of_the_part_size_that_neither_enclose_nor_stack_are_not_chosen_between(box, monkeypatch):
    """크기 · 자리가 맞고 서로 품지도 얹히지도 않는 몸체가 둘이면(부품 둘레를 두른 언더필 몸체 — z 가 부품과 겹친다) 고르지 않는다 — body null
    과 둘 다 fits_part 인 후보 · 까닭 ambiguous. F1 에 엉뚱한 part 를 넘기지 않고 사람이 항목 위치로 고른다."""
    monkeypatch.setitem(globals(), "BODIES", list(BODIES) + [("U1001_UNDERFILL", [50.83, -17.88, 0.1, 53.43, -16.48, 0.5], "EPX")])
    _freeze(box.store, box.project)
    _put(box)
    out = _locate(box, refdes="U1001")
    assert out["status"] == "located" and out["body"] is None and out["f1"]["part"] is None
    assert out["body_note"].startswith("ambiguous")
    assert [c["path"].rsplit("/", 1)[-1] for c in out["body_candidates"] if c["fits_part"]] == ["U1001_UNDERFILL", "U1001_BODY"]


def test_board_coordinates_without_a_side_land_mid_board_without_any_gateway_call(box, frozen):
    """보드 좌표는 변환만으로 자리가 선다 — 게이트웨이를 부르지 않는다(PAT 가 없어도 답한다). 면이 없으면 z 는 보드 두께 가운데이고 몸체는 보드
    몸체다. 면을 주면 그 면이고 몸체는 후보로만(대상 크기가 없다)."""
    _put(box)
    box.gw.seen.clear()
    mid = _locate(box, who=NOPAT, x=30.0, y=-20.0)
    assert mid["mcad"] == {"x": 52.13, "y": -17.18, "z": 0.825, "unit": "mm"} and mid["body"]["path"] == PCB
    assert mid["plane_basis"]["long_axis"] == "x" and mid["plane_basis"]["basis"].startswith("board")        # 보드가 x 로 길다
    top = _locate(box, x=30.0, y=-20.0, side="top")
    assert top["mcad"]["z"] == 0.5 and top["body"] is None and top["body_candidates"]
    assert box.gw.seen == []


def test_a_point_off_the_board_is_unknown_instead_of_naming_the_board(box, frozen):
    """(반대 검토 R2) 면 없는 보드 좌표는 보드 몸체를 몸체로 낸다 — 종전에는 보드에서 수백 mm 떨어진 (500, 500) 도 located 이고 보드 몸체가
    몸체 · F1 part 였다. 옮긴 자리가 CAD 보드 몸체 bbox(오차 상한 0.5 mm 만큼 너그럽게) 밖이면 unknown point_off_board 와 옮긴 자리 · 보드 bbox
    다(자리 · F1 칸을 싣지 않는다). 가장자리에서 상한 안은 받는다."""
    _put(box)
    far = _locate(box, x=500.0, y=500.0)
    assert (far["status"], far["reason"]["code"]) == ("unknown", "point_off_board") and "f1" not in far and "body" not in far
    assert far["mapped"] == {"x": -417.87, "y": 502.82, "unit": "mm"} and far["board_bbox"] == PCB_BOX
    edge = _locate(box, x=75.3, y=-47.5)                  # → (6.83, −44.68) — x 가 보드 가장자리(7.13)에서 0.3 mm 밖
    assert edge["status"] == "located" and edge["body"]["path"] == PCB
    assert _locate(box, x=76.0, y=-20.0)["reason"]["code"] == "point_off_board"        # 1 mm 밖


def test_a_net_lands_on_its_pin_box_and_a_net_without_pin_coordinates_is_unknown(box):
    """넷은 get_net 핀 좌표의 bbox 가운데다(z 는 보드 가운데 — 몸체는 정하지 않는다). 핀 좌표를 주지 않는 허브 답은 unknown net_pins_absent 와
    고칠 곳(ODB 허브 몫)이다 — 지어내지 않는다."""
    _put(box)
    out = _locate(box, net="VBAT")
    assert out["mcad"] == {"x": 69.13, "y": -8.18, "z": 0.825, "unit": "mm"} and out["body"] is None
    assert box.gw.calls("odbhub_get_net")[0][0] == {"job_id": JOB, "net": "VBAT"}
    none = _locate(box, net="GND")
    assert none["status"] == "unknown" and none["reason"]["code"] == "net_pins_absent" and "ODB 허브" in none["reason"]["fix"]


def test_each_reason_a_place_cannot_be_found_is_named(box, frozen):
    """unknown 의 까닭 — 변환 미등록(고칠 곳과) · 보드를 모름 · 허브가 그 refdes 를 모름 · 면을 모름(허브 답에도 스냅샷에도 없다). 허브 답에 side
    가 없으면 그 보드를 읽은 스냅샷의 ECAD 부품 면을 쓴다."""
    missing = _locate(box, refdes="U1001")
    assert missing["status"] == "unknown" and missing["reason"]["code"] == "transform_missing"
    assert "risk_propose_board_transform" in missing["reason"]["fix"] and box.gw.seen == []
    _put(box)
    other = _locate(box, refdes="U1001", odb_job_id="0" * 16)
    assert other["reason"]["code"] == "transform_missing" and other["odb_job_id"] == "0" * 16
    assert _locate(box, refdes="NOPE")["reason"]["code"] == "refdes_not_found"
    from_snapshot = _locate(box, refdes="U1002")
    assert from_snapshot["status"] == "located" and from_snapshot["ecad"]["side"] == "top"
    assert from_snapshot["ecad"]["side_basis"] == "snapshot"
    assert _locate(box, refdes="U1005")["reason"]["code"] == "side_unknown"            # 가짜 허브의 보드에 U1005 는 없다
    routes.delete_ecad_board(box.project, ident=_who(OWNER))            # 과제에서 보드를 떼면 보드를 모른다
    assert _locate(box, refdes="U1001")["reason"]["code"] == "board_missing"


def _moved(dx: float) -> list[tuple[str, list[float], str]]:
    """CAD 조립 전체(보드 포함)를 +x 로 dx mm 옮긴 몸체 목록."""
    return [(name, [b[0] + dx, b[1], b[2], b[3] + dx, b[4], b[5]], material) for name, b, material in BODIES]


def test_a_board_moved_in_a_snapshot_taken_after_registration_makes_the_transform_stale(box, monkeypatch):
    """(반대 검토 R1) 등록 뒤에 찍은 스냅샷에서 CAD 조립 전체(보드 포함)가 +x 로 5 mm 옮겨졌다 — 종전에는 변환이 그대로 located 였고 옛 자리 ·
    평면(x 52.13)을 F1 에 넘기며 warnings 가 비었다(몸체 칸의 snapshot_board_moved 뿐). 이제 refdes · 넷 · 보드 좌표 모두 unknown
    transform_stale 과 고칠 곳(지금 CAD 로 다시 맞춰 적기)이고 옛 자리 · F1 칸을 싣지 않는다. 낡았으면 허브를 부르지 않는다."""
    _put(box)
    monkeypatch.setitem(globals(), "BODIES", _moved(5.0))
    snap = _freeze(box.store, box.project, captured_at=now_epoch() + 60)
    box.gw.seen.clear()
    for inputs in ({"refdes": "U1001"}, {"net": "VBAT"}, {"x": 30.0, "y": -20.0}):
        out = _locate(box, **inputs)
        assert out["status"] == "unknown" and out["reason"]["code"] == "transform_stale", (inputs, out.get("reason"))
        assert "risk_set_board_transform" in out["reason"]["fix"] and "mcad" not in out and "f1" not in out
        assert (out["snapshot_id"], out["board_moved_mm"]) == (snap["snapshot_id"], 5.0)
    assert box.gw.seen == []
    # 다시 적으면(지금 CAD 가 옮겨진 자리라고 답한다) 새 등록이 그 스냅샷과 맞아 다시 자리를 낸다.
    box.gw.answers["heaxstep_forge_part_info"] = {**PART_INFO, "world_bbox": [v + 5.0 if i in (0, 3) else v for i, v in enumerate(PCB_BOX)]}
    box.gw.answers["heaxstep_forge_corner_proximity"] = copy.deepcopy(CORNER)
    for hole in box.gw.answers["heaxstep_forge_corner_proximity"]["parts"][0]["hole_list"]:
        hole["center"][0] += 5.0
    _put(box, offset_x=87.13)
    again = _locate(box, refdes="U1001")
    assert again["status"] == "located" and again["mcad"]["x"] == 57.13 and again["body"]["path"].endswith("/U1001_BODY")


def test_a_snapshot_older_than_the_registration_keeps_the_point_and_skips_its_bodies(box, monkeypatch):
    """등록보다 앞서 찍은 스냅샷이 다른 보드 자리를 보이면 낡은 것은 스냅샷이다(변환은 그 뒤의 CAD 로 검증됐다) — 자리는 그대로 내고 그
    스냅샷으로 몸체를 찾지 않는다(몸체 칸에 까닭)."""
    monkeypatch.setitem(globals(), "BODIES", _moved(5.0))
    _freeze(box.store, box.project)                 # 등록보다 앞선 캡처 시각
    _put(box)
    out = _locate(box, refdes="U1001")
    assert out["status"] == "located" and out["mcad"] == {"x": 52.13, "y": -17.18, "z": 0.5, "unit": "mm"}
    assert out["body"] is None and out["body_note"].startswith("snapshot_board_moved") and out["f1"]["part"] is None


def test_a_registration_without_its_verification_record_is_not_used(box):
    """(반대 검토 c) 과제 폐기는 등록의 검증 기록(verify_json)을 지우고 status 는 verified 로 남긴다 — 종전에는 그 행으로 located 였다. 검증 기록이
    없는 행은 검증하지 않은 것이다(transform_unverified). 다시 적으면 쓴다. 폐기된 과제는 다시 적을 수 없어 고칠 곳 대신 그렇게 말한다."""
    _put(box)
    box.store.execute("UPDATE rr_board_transforms SET verify_json = NULL")
    wiped = _locate(box, x=30.0, y=-20.0)
    assert (wiped["status"], wiped["reason"]["code"]) == ("unknown", "transform_unverified") and "risk_set_board_transform" in wiped["reason"]["fix"]
    _put(box)
    assert _locate(box, x=30.0, y=-20.0)["status"] == "located"
    code = box.store.query_one("SELECT code FROM rr_projects WHERE id = ?", (box.project,))["code"]
    routes.purge_project(box.project, routes.PurgeBody(code=code, reason="지운다"), ident=_who(OWNER))
    assert box.store.query_one("SELECT status FROM rr_board_transforms")["status"] == "verified"
    purged = _locate(box, x=30.0, y=-20.0)
    assert (purged["status"], purged["reason"]["code"]) == ("unknown", "transform_unverified")
    assert "fix" not in purged["reason"] and "폐기" in purged["reason"]["message"]


class _HubChannel:
    """게이트웨이 없이 read_odb_board 를 부르는 채널 대역 — 도구 이름 끝으로 답을 고른다."""

    def __init__(self, holes_reply: dict, volume: dict | None = None) -> None:
        self.holes_reply, self.volume = holes_reply, volume or VOLUME

    def call(self, name: str, args: dict, deadline: float | None = None) -> dict:
        return {"ok": True, "result": copy.deepcopy(self.volume if name.endswith("get_volume_result") else self.holes_reply)}


def test_a_hole_list_shorter_than_the_hubs_count_is_flagged_as_truncated():
    """(반대 검토 R9) 허브 답(레퍼런스 §4.10 꼴 — 쪽 넘김 칸이 없다)이 hole_count 30 인데 holes 가 20 개면 잘린 답이다 — 종전에는 has_more 만
    보아 다 읽은 것으로 쳤다(notes 빔). 받은 수가 허브가 말한 수(total, 없으면 hole_count)보다 적으면 holes_truncated 와 notes 로 말하고 검증의
    checks.holes.odb_truncated 에 싣는다 — 받은 구멍만으로도 짝 · 모호함은 그대로 재므로 거절하지는 않는다. 수가 맞으면 말하지 않는다."""
    from app import locate

    short = {"hole_count": 30, "cutout_count": 0, "holes": [{"x": 8.0, "y": -44.0, "diameter_mm": 1.6}] * 20}
    odb = locate.read_odb_board(_HubChannel(short), "odb-hub", JOB, [])
    assert len(odb["holes"]) == 20 and odb["holes_truncated"] is True and odb["holes_read"] is True
    assert [n for n in odb["notes"] if "30" in n and "20" in n]
    odb_in, _cad_in = locate.verify_inputs({"odb": odb, "cad": {"bbox": PCB_BOX, "holes": [], "unit_suspect": False}})
    assert bt.verify(bt.Transform(True, False, 82.13, 2.82, "zmin"), odb_in, {"bbox": PCB_BOX, "holes": []})["checks"]["holes"]["odb_truncated"]
    whole = locate.read_odb_board(_HubChannel(copy.deepcopy(HOLES)), "odb-hub", JOB, [])
    assert whole["holes_truncated"] is False and whole["notes"] == [] and len(whole["holes"]) == 3


def test_odb_answers_that_name_another_length_unit_are_not_read_as_millimetres(box, frozen):
    """ODB 허브는 길이를 다 mm 로 준다(레퍼런스 §3) — 그래도 답이 units · unit 칸으로 다른 단위를 말하면 mm 로 읽지 않는다(종전에는 get_net
    만 보았다). 부품 답은 unknown odb_unit_unexpected, 외곽 크기 · 고정홀은 못 읽은 것으로 쳐서 등록 검증이 거절한다."""
    _put(box)
    box.gw.answers["odbhub_get_part_detail"] = lambda a: {**copy.deepcopy(DETAILS["U1001"]), "units": "inch"}
    assert _locate(box, refdes="U1001")["reason"]["code"] == "odb_unit_unexpected"
    box.gw.answers["odbhub_get_volume_result"] = {**VOLUME, "unit": "inch"}
    assert "odb_size_unread" in _refused(lambda: _put(box)).detail["verification"]["reasons"]
    box.gw.answers["odbhub_get_volume_result"] = VOLUME
    box.gw.answers["odbhub_get_mounting_holes"] = {**HOLES, "units": "mil"}
    refused = _refused(lambda: _put(box)).detail
    assert "position_unverified" in refused["verification"]["reasons"] and refused["evidence"]["odb"]["holes"] == []


def test_an_imported_registration_is_not_used_until_it_is_verified_here(box):
    """다른 박스에서 들여온 등록(검증 칸 없음 — status NULL)은 위치 찾기가 쓰지 않는다(transform_unverified · 다시 적어 검증한다)."""
    _put(box)
    body = "".join(export.iter_lines(box.store, OWNER, 0))
    box.store.execute("DELETE FROM rr_board_transforms")
    export.import_jsonl(box.store, OWNER, body)
    out = _locate(box, x=30.0, y=-20.0)
    assert out["status"] == "unknown" and out["reason"]["code"] == "transform_unverified" and "다시 적어" in out["reason"]["fix"]
    _put(box)
    assert _locate(box, x=30.0, y=-20.0)["status"] == "located"


# ================================================================ 권한 · 신원 — 쓰기는 편집자 이상, 읽기는 구성원, 산 호출은 그 사람의 PAT 만
def test_writes_are_for_editors_and_reads_for_members_each_with_their_own_pat(box):
    """보기는 403 · 남은 없는 과제와 같은 404 · 편집자는 적되 제 PAT 로 검증한다. 읽기(목록 · 찾기 · 제안)는 구성원 모두이고 산 호출은 부른 사람의
    PAT 다. 남은 읽기도 404 다."""
    err = _refused(lambda: _put(box, VIEWER))
    assert (err.code, err.http_status) == ("role_insufficient", 403)
    assert _refused(lambda: _put(box, STRANGER)).http_status == 404
    assert box.gw.seen == []
    assert _put(box, EDITOR)["registration"]["created_by"] == EDITOR
    assert box.gw.auths() == {f"Bearer {PATS[EDITOR]}"}
    box.gw.seen.clear()
    assert _locate(box, VIEWER, refdes="U1001")["status"] == "located"
    assert box.gw.auths() == {f"Bearer {PATS[VIEWER]}"}
    for read in (lambda: _locate(box, STRANGER, x=1.0, y=1.0), lambda: routes.get_board_transforms(box.project, ident=_who(STRANGER)),
                 lambda: routes.get_board_transform_proposal(box.project, ident=_who(STRANGER))):
        assert _refused(read).http_status == 404
    remove = _refused(lambda: routes.delete_board_transform(box.project, ident=_who(VIEWER)))
    assert remove.http_status == 403
    assert routes.delete_board_transform(box.project, ident=_who(EDITOR))["removed"] == 1
    assert len(_audits(box.store)) == 2 and json.loads(_audits(box.store)[-1]["before_json"])["status"] == "verified"


def test_without_the_persons_pat_nothing_is_sent_and_the_box_pat_is_never_used(box):
    """그 사람의 PAT 가 없으면 적기 · 제안 · refdes 찾기는 409 locate_pat_absent 이고 게이트웨이에 아무것도 보내지 않는다 — 박스 읽기 PAT 로
    내려가지 않는다."""
    for call in (lambda: _put(box, NOPAT), lambda: routes.get_board_transform_proposal(box.project, ident=_who(NOPAT))):
        err = _refused(call)
        assert (err.code, err.http_status, err.detail) == ("locate_pat_absent", 409, {"fix": "portal_pat"})
    _put(box)
    box.gw.seen.clear()
    err = _refused(lambda: _locate(box, NOPAT, refdes="U1001"))
    assert err.code == "locate_pat_absent" and box.gw.seen == []


def test_an_admin_writes_as_an_editor_and_leaves_the_admin_marks(box):
    """관리자는 구성원이 아니어도 편집자로 적는다 — 감사 행에 관리자 표시(via admin)와 관리자 쓰기 줄이 선다."""
    _register_admin = "f2-admin@example.com"
    PATS[_register_admin] = "admin-pat-not-real"
    try:
        _register(box.store, _register_admin)
        out = _put(box, _register_admin, role="admin")
    finally:
        PATS.pop(_register_admin)
    assert out["registration"]["status"] == "verified"
    assert json.loads(_audits(box.store)[-1]["after_json"])["via"] == "admin"
    assert box.store.query_one("SELECT COUNT(*) AS n FROM rr_audit WHERE action = 'admin.write'")["n"] == 1


# ================================================================ 제안
def test_the_proposal_offers_board_bodies_then_finds_the_hand_transform(box, frozen):
    """몸체 경로가 없으면 ODB 외곽 크기에 맞는 몸체(스냅샷)를 준다 — 보드 몸체가 첫째다. 경로를 주면 뒤집기 넷마다의 변환 후보와 검증을 주는데
    첫 후보가 손 셈이다(쓰지 않는다). 그 후보를 그대로 적으면 verified 다."""
    first = routes.get_board_transform_proposal(box.project, ident=_who(VIEWER))
    assert [c["path"] for c in first["board_body_candidates"]] == [PCB] and first["candidates"] == []
    assert first["board_body_candidates"][0]["error_mm"] == 0.0 and first["current"] is None
    second = routes.get_board_transform_proposal(box.project, board_body=PCB, ident=_who(VIEWER))
    top = second["candidates"][0]
    assert top["verification"]["ok"] and top["transform"] == {**HAND, "unit": "mm"}
    assert top["formula"].startswith("x_CAD = 82.13 − x_ODB · y_CAD = y_ODB + 2.82")
    assert routes.get_board_transforms(box.project, ident=_who(OWNER))["transforms"] == []
    taken = top["transform"]
    out = _put(box, source="proposed", **{k: taken[k] for k in HAND})
    assert out["registration"]["status"] == "verified" and out["registration"]["source"] == "proposed"
    assert routes.get_board_transform_proposal(box.project, board_body=PCB, ident=_who(OWNER))["current"]["status"] == "verified"


# ================================================================ 리스크 항목 — 위치 · 주제
def _ckey(ir: dict, label: str) -> str:
    return next(n["ckey"] for n in ir["nodes"] if n.get("label") == label)


def _finding(box: Box, target_key: str, subject_key: str, claim: str = "간극이 작다") -> dict:
    return routes.create_human_finding(target_key, routes.HumanFindingBody(subject_key=subject_key, claim=claim,
                                                                           cites=[{"ref": "warn:f2", "quote": "근거"}]),
                                       ident=_who(OWNER))


@pytest.fixture
def items(box, frozen) -> dict:
    target = factories.make_target(box.store, "snap", frozen["snapshot_id"], agents=factories.agents(("mech", "pcb")), owner=OWNER)
    ir = frozen["ir"]
    made = {"target": target, "ir": ir}
    for name, subject in (("can", _ckey(ir, "SHIELD_CAN_1")), ("pair", "|".join(sorted((_ckey(ir, "MAIN_PCB"), _ckey(ir, "SHIELD_CAN_1"))))),
                          ("screws", _ckey(ir, "SCREW_M14#1")), ("chip", _ckey(ir, "U1002")), ("asm", "asm:PHONE_ASM")):
        made[name] = _finding(box, target, subject, claim=f"{name} 주장")
    return made


def test_a_part_subject_goes_straight_to_its_body_and_planes_without_the_gateway(box, items):
    """주제가 MCAD 몸체 하나면 그 스냅샷 몸체 bbox 가운데 · 몸체 · 두 큰 변의 평면이다 — 변환도 게이트웨이도 쓰지 않는다. 등록부 묶음도 같은
    답이다."""
    out = _locate(box, finding_id=items["can"]["finding_id"])
    assert out["mcad"] == {"x": 50.0, "y": -17.5, "z": -0.35, "unit": "mm"}
    assert out["body"]["path"].endswith("/SHIELD_CAN_1") and out["planes"] == [{"axis": "y", "offset": -17.5, "unit": "mm"},
                                                                               {"axis": "x", "offset": 50.0, "unit": "mm"}]
    assert out["stepforge_project_id"] == SF and out["window_mm"] == 60.0 and box.gw.seen == []
    cluster = _locate(box, target_key=items["target"], cluster_key=items["can"]["cluster_key"])
    assert (cluster["mcad"], cluster["body"]["path"], cluster["planes"]) == (out["mcad"], out["body"]["path"], out["planes"])


def test_a_standing_part_still_gets_two_vertical_section_planes(box, monkeypatch):
    """(반대 검토 R4) 옆으로 선 FPCB(x 로 얇고 z 로 높다)가 주제면 — 종전에는 몸체 bbox 의 가장 얇은 변(x)을 두께로 보아 한 평면이 z 법선의 가로
    단면이었다. 두 평면은 늘 보드 법선 z 를 품는 세로 단면이다(F1 에 넘기는 꼴 그대로) — 면내 긴 축 y 를 품는 x 법선 평면이 앞이다."""
    monkeypatch.setitem(globals(), "BODIES", list(BODIES) + [("SIDE_KEY_FPCB", [0.5, -30.0, -3.0, 1.0, -10.0, 4.0], "PI")])
    snap = _freeze(box.store, box.project)
    target = factories.make_target(box.store, "snap", snap["snapshot_id"], agents=factories.agents(("mech", "pcb")), owner=OWNER)
    finding = _finding(box, target, _ckey(snap["ir"], "SIDE_KEY_FPCB"))
    out = _locate(box, finding_id=finding["finding_id"])
    assert out["status"] == "located" and out["mcad"] == {"x": 0.75, "y": -20.0, "z": 0.5, "unit": "mm"}
    assert out["planes"] == [{"axis": "x", "offset": 0.75, "unit": "mm"}, {"axis": "y", "offset": -20.0, "unit": "mm"}]
    assert out["plane_basis"]["thickness_axis"] == "z" and out["f1"]["planes"] == out["planes"]


def test_an_interface_subject_lands_in_the_overlap_of_its_two_bodies(box, items):
    out = _locate(box, finding_id=items["pair"]["finding_id"])
    assert out["status"] == "located" and out["body"] is None and len(out["bodies"]) == 2
    assert out["mcad"] == {"x": 50.0, "y": -17.5, "z": 0.5, "unit": "mm"}          # 쉴드캔이 보드 아래 면에 맞닿은 칸
    assert out["plane_basis"]["basis"].startswith("interface_overlap")


def test_an_ambiguous_or_unplaceable_subject_is_unknown_with_its_candidates(box, items):
    """같은 나사 둘(같은 정규 키)은 고르지 않고 후보를 준다. 조립 주제는 자리가 하나가 아니다."""
    screws = _locate(box, finding_id=items["screws"]["finding_id"])
    assert screws["reason"]["code"] == "subject_ambiguous" and len(screws["candidates"]) == 2
    assert _locate(box, finding_id=items["asm"]["finding_id"])["reason"]["code"] == "subject_not_placeable"


def test_an_ecad_part_subject_takes_the_board_path_through_the_registration(box, items):
    """주제가 ECAD 부품이면 그 스냅샷의 보드로 refdes 길을 탄다 — 등록이 없으면 그 까닭, 있으면 손 셈 자리다."""
    assert _locate(box, finding_id=items["chip"]["finding_id"])["reason"]["code"] == "transform_missing"
    _put(box)
    out = _locate(box, finding_id=items["chip"]["finding_id"])
    assert out["status"] == "located" and out["input"]["via"] == {"refdes": "U1002"}
    assert out["mcad"] == {"x": 62.13, "y": -37.18, "z": 0.5, "unit": "mm"}


def test_an_item_location_is_set_by_editors_audited_and_used_first(box, items):
    """항목 위치(점)를 적으면 위치 찾기가 주제보다 먼저 그 점을 쓴다. 편집자 이상만 적고(보기 403 · 남 404) 바뀌면 감사 한 줄이다. 둘 다 null 이면
    뗀다. mm 가 아닌 단위는 받지 않는다."""
    finding = items["asm"]["finding_id"]
    body = routes.ItemLocationBody(finding_id=finding, part=None, point=routes.ItemPoint(x=10.0, y=-5.0, z=0.5))
    assert _refused(lambda: routes.put_item_location(box.project, body, ident=_who(VIEWER))).http_status == 403
    assert _refused(lambda: routes.put_item_location(box.project, body, ident=_who(STRANGER))).http_status == 404
    inch = routes.ItemLocationBody(finding_id=finding, part=None, point=routes.ItemPoint(x=1.0, y=1.0, z=1.0, unit="inch"))
    assert _refused(lambda: routes.put_item_location(box.project, inch, ident=_who(EDITOR))).code == "unit_unsupported"
    out = routes.put_item_location(box.project, body, ident=_who(EDITOR))
    assert out["changed"] and out["location"]["point"] == {"x": 10.0, "y": -5.0, "z": 0.5, "unit": "mm"}
    found = _locate(box, finding_id=finding)
    assert found["mcad"] == {"x": 10.0, "y": -5.0, "z": 0.5, "unit": "mm"} and found["plane_basis"]["basis"].startswith("item_location")
    rows = _audits(box.store, "finding.location")
    assert [(r["actor"], r["scope"], r["subject_id"]) for r in rows] == [(EDITOR, "finding", finding)]
    same = routes.put_item_location(box.project, body, ident=_who(EDITOR))
    assert same["changed"] is False and len(_audits(box.store, "finding.location")) == 1
    cleared = routes.put_item_location(box.project, routes.ItemLocationBody(finding_id=finding, part=None, point=None),
                                       ident=_who(OWNER))
    assert cleared["changed"] and cleared["location"] is None
    assert _locate(box, finding_id=finding)["reason"]["code"] == "subject_not_placeable"


def test_an_item_location_part_must_be_a_body_of_the_items_snapshot(box, items):
    """(반대 검토 R8) 항목 위치의 몸체 경로를 확인하지 않아 아무 경로(남의 과제의 것도)나 적혔고 위치 찾기가 그것을 body · F1 part 로
    되실었다. 이제 적을 때 그 항목의 스냅샷에 있는 MCAD 부품 경로만 받는다(422 item_part_unknown — 감사 없음). 이미 있는 모르는 경로(들여온 행 ·
    고치기 전에 적힌 것)는 몸체로 되싣지 않고 점만 쓴다(경고와 함께). 점만 적힌 위치는 그 항목 스냅샷의 CAD 과제를 싣는다(반대 검토 b — 요청의
    stepforge_project_id 가 달라도)."""
    finding = items["asm"]["finding_id"]
    stranger_path = "/OTHER_PROJECT/x.step/NOT_A_PART"
    err = _refused(lambda: routes.put_item_location(box.project, routes.ItemLocationBody(
        finding_id=finding, part=stranger_path, point=routes.ItemPoint(x=10.0, y=-5.0, z=0.5)), ident=_who(OWNER)))
    assert (err.code, err.http_status) == ("item_part_unknown", 422) and err.detail["snapshots"] == [items["ir"]["snapshot_id"]]
    assert _audits(box.store, "finding.location") == []
    assert routes.put_item_location(box.project, routes.ItemLocationBody(finding_id=finding, part=PCB, point=None),
                                    ident=_who(OWNER))["changed"]
    box.store.execute("UPDATE rr_findings SET location_json = ? WHERE finding_id = ?",
                      (json.dumps({"part": stranger_path, "point": {"x": 10.0, "y": -5.0, "z": 0.5, "unit": "mm"}}), finding))
    echoed = _locate(box, finding_id=finding)
    assert echoed["status"] == "located" and echoed["mcad"] == {"x": 10.0, "y": -5.0, "z": 0.5, "unit": "mm"}
    assert echoed["body"] is None and echoed["f1"]["part"] is None and echoed["body_note"].startswith("item_part_absent")
    assert echoed["warnings"][0].startswith("item_part_absent")
    routes.put_item_location(box.project, routes.ItemLocationBody(finding_id=finding, part=None, point=routes.ItemPoint(x=10.0, y=-5.0, z=0.5)),
                             ident=_who(OWNER))
    only = _locate(box, finding_id=finding, stepforge_project_id="019f2other00000000000000b")
    assert (only["stepforge_project_id"], only["f1"]["stepforge_project_id"]) == (SF, SF)


def test_a_diff_items_place_is_read_only_by_someone_who_reads_both_projects(box, monkeypatch):
    """(반대 검토 a) 비교 대상의 항목은 앞 판 스냅샷에서 자리를 찾는다 — 앞 판 과제는 다른 과제라 그 과제를 못 읽는 편집자가 그 과제의 몸체 자리를
    꺼냈다. 비교는 두 과제를 다 읽는 사람이 연다(MCP 비교 문 · 웹 _diff_reader) — 위치 찾기와 항목 위치 쓰기도 그 문이다. 못 읽으면 없는 항목과
    같은 404 이고, 앞 판 과제의 보기 구성원이 되면 연다(MCP 도 같다)."""
    base_project = factories.make_project(box.store, owner=OWNER, code="F2-0")
    monkeypatch.setitem(globals(), "BODIES", list(BODIES) + [("OLD_BRACKET", [20.0, -40.0, 1.15, 30.0, -35.0, 2.0], "AL")])
    base = _freeze(box.store, base_project)
    monkeypatch.setitem(globals(), "BODIES", [b for b in BODIES if b[0] != "OLD_BRACKET"])
    target = _freeze(box.store, box.project)
    diff = factories.make_diff(box.store, base["snapshot_id"], target["snapshot_id"], owner=OWNER)
    diff_target = factories.make_target(box.store, "diff", diff["diff_id"], agents=factories.agents(("mech", "pcb")), owner=OWNER)
    finding = _finding(box, diff_target, _ckey(base["ir"], "OLD_BRACKET"))["finding_id"]
    mine = _locate(box, finding_id=finding)
    assert mine["status"] == "located" and mine["body"]["path"].endswith("/OLD_BRACKET") and mine["snapshot_id"] == base["snapshot_id"]
    hidden = _refused(lambda: _locate(box, EDITOR, finding_id=finding))
    gone = _refused(lambda: _locate(box, EDITOR, finding_id="no-such-finding"))
    assert (hidden.code, hidden.http_status) == (gone.code, gone.http_status) == ("E404", 404) and base_project not in hidden.message
    write = routes.ItemLocationBody(finding_id=finding, part=None, point=routes.ItemPoint(x=1.0, y=2.0, z=3.0))
    assert _refused(lambda: routes.put_item_location(box.project, write, ident=_who(EDITOR))).http_status == 404
    factories.act_as_delegate(monkeypatch, EDITOR)
    assert _call("risk_locate_for_section", project_id=box.project, finding_id=finding)["error"] == "E404"
    routes.put_members(base_project, routes.MembersBody(members=[routes.MemberItem(email=EDITOR, role="viewer")]), ident=_who(OWNER))
    assert _locate(box, EDITOR, finding_id=finding)["body"]["path"].endswith("/OLD_BRACKET")
    assert _call("risk_locate_for_section", project_id=box.project, finding_id=finding)["status"] == "located"
    assert routes.put_item_location(box.project, write, ident=_who(EDITOR))["changed"]


def test_an_item_location_is_held_to_the_write_shape_on_import_and_on_read(box, items):
    """(반대 검토 R6) 항목 위치 칸은 들여오기로도 들어온다 — 종전에는 들인 {unit: inch} 를 mm 로 읽어 자리를 냈고 y · z 가 빠지면 KeyError(GET
    /locate 500)였다. 들여오기는 쓰기 본문과 같은 꼴만 받고 틀린 꼴은 그 칸만 버린다(location_invalid_dropped). 이미 저장된 틀린 꼴(손으로 넣은
    행 · 고치기 전 들여오기)은 위치 찾기가 unknown item_location_invalid 와 고칠 곳으로 답하고, 떼면(무엇을 적든 바뀐 것이다) 고쳐진다."""
    finding = items["asm"]["finding_id"]
    routes.put_item_location(box.project, routes.ItemLocationBody(finding_id=finding, part=None, point=routes.ItemPoint(x=1.0, y=2.0, z=3.0)),
                             ident=_who(OWNER))
    lines = []
    for line in "".join(export.iter_lines(box.store, OWNER, 0)).splitlines():
        obj = json.loads(line)
        if obj.get("table") == "rr_findings" and (obj.get("row") or {}).get("finding_id") == finding:
            obj["row"]["location_json"] = json.dumps({"part": None, "point": {"x": 1.0, "y": 2.0, "z": 3.0, "unit": "inch"}})
        lines.append(json.dumps(obj, ensure_ascii=False))
    box.store.execute("DELETE FROM rr_findings WHERE finding_id = ?", (finding,))
    out = export.import_jsonl(box.store, OWNER, "\n".join(lines) + "\n")
    assert out["inserted"] >= 1 and out["location_invalid_dropped"] == 1
    assert box.store.query_one("SELECT location_json FROM rr_findings WHERE finding_id = ?", (finding,))["location_json"] is None
    assert _locate(box, finding_id=finding)["reason"]["code"] == "subject_not_placeable"         # 위치가 없어 주제(조립)로 간다
    for bad in ({"part": None, "point": {"x": 1.0}}, {"part": None, "point": {"x": 1.0, "y": 2.0, "z": 3.0, "unit": "inch"}},
                {"part": None, "point": {"x": 1, "y": 2, "z": 3}, "extra": True}, {"part": None, "point": {"x": "1", "y": 2, "z": 3}}):
        box.store.execute("UPDATE rr_findings SET location_json = ? WHERE finding_id = ?", (json.dumps(bad), finding))
        found = _locate(box, finding_id=finding)
        assert (found["status"], found["reason"]["code"]) == ("unknown", "item_location_invalid"), bad
        assert "risk_set_item_location" in found["reason"]["fix"]
    cleared = routes.put_item_location(box.project, routes.ItemLocationBody(finding_id=finding, part=None, point=None), ident=_who(OWNER))
    assert cleared["changed"] and json.loads(_audits(box.store, "finding.location")[-1]["before_json"])["invalid"].startswith("point.x")
    assert box.store.query_one("SELECT location_json FROM rr_findings WHERE finding_id = ?", (finding,))["location_json"] is None


def test_purge_blanks_paths_and_locations_and_transfer_moves_the_registration(box, items):
    """폐기는 등록의 몸체 경로 · 근거 · 사유와 항목 위치를 비우고(변환 값은 남는다), 이양은 등록을 새 주인에게 옮긴다."""
    _put(box)
    routes.put_item_location(box.project, routes.ItemLocationBody(target_key=items["target"], cluster_key=items["can"]["cluster_key"],
                                                                  part=PCB, point=None), ident=_who(OWNER))
    routes.transfer_project(box.project, routes.TransferBody(to_email=EDITOR, reason="담당 교체"), ident=_who(OWNER))
    assert box.store.query_one("SELECT owner_sub FROM rr_board_transforms")["owner_sub"] == EDITOR
    assert _locate(box, EDITOR, x=30.0, y=-20.0)["status"] == "located"
    code = box.store.query_one("SELECT code FROM rr_projects WHERE id = ?", (box.project,))["code"]
    routes.purge_project(box.project, routes.PurgeBody(code=code, reason="지운다"), ident=_who(EDITOR))
    row = box.store.query_one("SELECT board_body_path, verify_json, reason, offset_x FROM rr_board_transforms")
    assert (row["board_body_path"], row["verify_json"], row["reason"], row["offset_x"]) == ("", None, None, 82.13)
    assert box.store.query_one("SELECT COUNT(*) AS n FROM rr_registry WHERE location_json IS NOT NULL")["n"] == 0


# ================================================================ MCP — 위임 신원 · REST 와 같은 답 · D-18
def test_the_mcp_tools_need_a_delegated_identity_and_answer_like_rest(box, frozen, monkeypatch):
    """네 도구 다 위임으로 확인된 신원만 받는다(아니면 delegation_required). 위임 신원이면 REST 와 같은 함수의 답이고 산 호출은 그 사람의 PAT 다."""
    for tool, args in (("risk_locate_for_section", {"project_id": box.project, "x": 1.0, "y": 1.0}),
                       ("risk_propose_board_transform", {"project_id": box.project}),
                       ("risk_set_board_transform", {"project_id": box.project, "remove": True}),
                       ("risk_set_item_location", {"project_id": box.project, "part": None, "point": None, "finding_id": "f"})):
        assert _call(tool, **args)["error"] == "delegation_required", tool
    factories.act_as_delegate(monkeypatch, EDITOR)
    written = _call("risk_set_board_transform", project_id=box.project, board_body=PCB, **HAND)
    assert written["registration"]["status"] == "verified" and written["web"]["project"].endswith(box.project)
    assert _audits(box.store)[-1]["channel"] == "mcp" and _audits(box.store)[-1]["actor_verified"] == 0
    box.gw.seen.clear()
    via_mcp = _call("risk_locate_for_section", project_id=box.project, refdes="U1001")
    via_rest = _locate(box, EDITOR, refdes="U1001")
    assert via_mcp == via_rest and box.gw.auths() == {f"Bearer {PATS[EDITOR]}"}
    refused = _call("risk_set_board_transform", project_id=box.project, board_body=PCB, **{**HAND, "top_face": "zmax"})
    assert refused["error"] == "transform_unverified" and refused["detail"]["verification"]["reasons"] == ["handedness_mismatch"]
    factories.act_as_delegate(monkeypatch, STRANGER)
    assert _call("risk_locate_for_section", project_id=box.project, x=1.0, y=1.0)["error"] == "not_visible"


def test_the_f2_tools_are_risk_tools_closed_to_risk_review_seats():
    """D-18 — 네 도구 이름이 risk_ 로 시작하고 좌석에 여는 둘(risk_get_diff · risk_get_snapshot)이 아니다. 에이전트 엔진은 리스크 심사 좌석의
    지정 도구에서 리스크 앱 도구를 이름으로 닫는다(_risk_designated_refusal 의 app 갈래 — 매핑을 못 받아도 닫는다). 자유 조회 접두에도 걸리지
    않는다(risk_ 는 자유 조회 허용 접두가 아니다)."""
    names = {t.name for t in asyncio.run(srv.mcp.list_tools())}
    for name in ("risk_locate_for_section", "risk_propose_board_transform", "risk_set_board_transform", "risk_set_item_location"):
        assert name in names and name.startswith("risk_") and name not in ("risk_get_diff", "risk_get_snapshot")


def test_the_input_is_exactly_one_thing_with_finite_millimetres(box):
    """입력은 꼭 하나 — 없거나 둘이면 422, 좌표는 유한한 수, side 는 좌표와 함께만 top · bottom."""
    for bad in ({}, {"refdes": "U1", "net": "N"}, {"x": 1.0}, {"x": float("nan"), "y": 1.0}, {"refdes": "U1", "side": "top"},
                {"x": 1.0, "y": 1.0, "side": "left"}, {"target_key": "snap:x"}):
        err = _refused(lambda bad=bad: _locate(box, **bad))
        assert (err.code, err.http_status) == ("E100", 422), bad
    assert _refused(lambda: _locate(box, x=1.0, y=1.0, odb_job_id="not-a-job")).http_status == 422


def test_an_unknown_key_is_refused_so_a_misspelled_unit_is_never_read_as_millimetres(box, monkeypatch):
    """본문 꼴은 아는 칸만 받는다 — `units: inch` 처럼 철자가 다른 칸을 버리고 unit 기본값(mm)으로 읽으면 인치 값이 말없이 mm 가 된다. REST 본문
    모델은 422 로, MCP 는 E100 으로 거절한다(변환 본문도 같다)."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        routes.ItemPoint(**{"x": 1.0, "y": 2.0, "z": 3.0, "units": "inch"})
    with pytest.raises(pydantic.ValidationError):
        routes.BoardTransformBody(board_body=PCB, **HAND, units="inch")
    with pytest.raises(pydantic.ValidationError):
        routes.ItemLocationBody(finding_id="f1", part=None, point=None, location={"x": 1})
    factories.act_as_delegate(monkeypatch, OWNER)
    out = _call("risk_set_item_location", project_id=box.project, part=None, finding_id="f1",
                point={"x": 1.0, "y": 2.0, "z": 3.0, "units": "inch"})
    assert out["error"] == "E100" and "units" in out["message"]
