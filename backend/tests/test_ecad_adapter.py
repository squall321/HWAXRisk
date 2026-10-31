# ECAD(ODB 허브) 1단계 — 요청서 부록 A 꼴의 가짜 odb-hub(표준 · 비표준 적층 두 보드 · list_parts 100행 쪽 상한 · 이름 겹침 접두)로 발견 · 캡처 · 표지 · 보드 찾기 · 붙이기 · 떼기를 본다(실 허브 호출 0)
"""포털 docs/design-risk-review/ecad-1031 의 ER-01 ~ ER-05 를 시험한다.

가짜의 응답 꼴은 cae00 10-31 실측(요청서 부록 A)과 허브 레퍼런스(포털 docs/procedures/fixtures/odb-hub/reference.md 4절)에서
옮겼다. find_job 의 봉투 열쇠는 부록 A 에 없어 list_jobs 와 같은 `jobs` 로 둔다(어댑터는 알려진 꼴 넷을 읽는다).
dev 게이트웨이에는 odb-hub 가 없다 — 실물 확인은 cae00 다시 볼 시험(요청서 6절)이다.
"""
from __future__ import annotations

import asyncio
import collections
import copy
import hashlib
import json
import tracemalloc
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft7Validator

import app.mcp_server as srv
from app import diff as diff_module
from app import identity, ir_builder, planner, routes
from app import state as state_module
from app import units as units_module
from app.adapters import base as adapters_base
from app.adapters import ecad as ecad_adapter
from app.adapters import mcad
from app.adapters import registry as adapters_registry
from app.adapters.base import CallRecorder, Principal, RestGetClient
from app.common import now_epoch
from app.errors import AppError
from app.ra_client import McpHttpClient
from tests import factories
from tests import test_adapters as recon
from tests.test_diff import _load as _pair
from tests.test_e2e_smoke import no_network  # noqa: F401 — autouse: 실제 소켓으로 나가는 httpx 를 막는다

OWNER = "board-owner@example.com"
SCHEMA = json.loads((Path(ir_builder.__file__).parent / "schemas" / "rr_ir.v1.json").read_text(encoding="utf-8"))
ODB = "odb-hub"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# job_id 는 원본 sha256 앞 16자리다(부록 A).
SHA_STD, SHA_NON = _sha("alpha_main_r07.tgz"), _sha("alpha_main_r08.tgz")
JOB_STD, JOB_NON = SHA_STD[:16], SHA_NON[:16]
# 표준 적층 보드(보드 1 꼴 — 동박 10층, 5종 23행, 전체 35행, 분류된 부품 748 · 배치 924)와
# 비표준 적층 보드(보드 2 꼴 — 동박 8층, 5종 19행, 분류된 부품 528 · 배치 702).
STD_DIELECTRIC = [40.0, 40.0, 40.0, 40.0, 60.0, 40.0, 40.0, 40.0, 40.0]
NON_DIELECTRIC = [45.0] * 7


def _board_layers(n_copper: int, dielectric: list[float], extra: list[dict]) -> list[dict]:
    """get_board_layers.layers[] — 위에서 아래 물리 순서. 부품 · 페이스트 층이 5종 사이에 끼고 드릴 · 문서 층이 뒤에 온다."""
    rows = [{"name": "comp_+_top", "type": "COMPONENT", "thickness_um": None},
            {"name": "sst", "type": "SILK_SCREEN", "thickness_um": None},
            {"name": "spt", "type": "SOLDER_PASTE", "thickness_um": None},
            {"name": "smt", "type": "SOLDER_MASK", "thickness_um": 20.0}]
    for i in range(1, n_copper + 1):
        rows.append({"name": f"signal_{i}", "type": "SIGNAL", "thickness_um": 25.0 if i in (1, n_copper) else 15.0})
        if i < n_copper:
            rows.append({"name": f"dielectric_{i}", "type": "DIELECTRIC", "thickness_um": dielectric[i - 1]})
    rows += [{"name": "smb", "type": "SOLDER_MASK", "thickness_um": 20.0},
             {"name": "spb", "type": "SOLDER_PASTE", "thickness_um": None},
             {"name": "ssb", "type": "SILK_SCREEN", "thickness_um": None},
             {"name": "comp_+_bot", "type": "COMPONENT", "thickness_um": None}]
    return rows + extra


def _standard_stackup(n_copper: int, dielectric: list[float]) -> list[dict]:
    """check_job_stackup.layers[] — 표준 적층(SR · L1 · L1-L2 꼴), 실크 층은 없다."""
    rows = [{"name": "SR", "kind": "SolderResist", "thickness_um": 20.0, "material": "SR"}]
    for i in range(1, n_copper + 1):
        rows.append({"name": f"L{i}", "kind": "Signal", "thickness_um": 25.0 if i in (1, n_copper) else 15.0,
                     "material": "CU"})
        if i < n_copper:
            rows.append({"name": f"L{i}-L{i + 1}", "kind": "Dielectric", "thickness_um": dielectric[i - 1],
                         "material": "CCL" if dielectric[i - 1] == 60.0 else "PPG"})
    rows.append({"name": "SR", "kind": "SolderResist", "thickness_um": 20.0, "material": "SR"})
    return rows


CATEGORIES = [("C", "Capacitor", "cap0402", 2), ("L", "Inductor", "ind0603", 2), ("U", "IC", "bga41f_W235L235", 41),
              ("J", "Connector", "con10p_W5L2", 10), ("SH", "Shield Can", "shield_W20L15", 4)]


def _parts(n: int, tag: str) -> list[dict]:
    """list_parts 행 — 분류된 부품만(category Unknown 인 저항 · 테스트 포인트는 허브가 뺀다)."""
    rows = []
    for i in range(n):
        prefix, category, pkg, pins = CATEGORIES[i % len(CATEGORIES)]
        rows.append({"refdes": f"{prefix}{1000 + i}", "part_name": f"{tag}-{i:05d}", "pkg_name": pkg,
                     "pkg_width": 1.0, "pkg_length": 0.5, "side": "top" if i % 3 else "bottom",
                     "pin_count": pins, "category": category})
    return rows


def _volume(parts: list[dict], placed: tuple[int, int], *, n_copper: int, verdict: str) -> dict:
    """get_volume_result — 외곽 폭 · 높이 · 면적(원점 없음), 면마다 배치 수와 큰 부품 10개(높이)."""
    def big(side: str) -> list[dict]:
        rows = [p for p in parts if p["side"] == side and p["category"] in ("Shield Can", "Connector", "IC")][:10]
        return [{"refdes": p["refdes"], "area_mm2": 20.0, "height_mean_mm": 1.2, "volume_mm3": 24.0} for p in rows]

    return {"grand_total_mm3": 3007.9131, "pkg_mass_kg": 0.0117,
            "board": {"outline_area_mm2": 6065.3397, "x_mm": 107.18, "y_mm": 72.9693, "thickness_mm": 0.59,
                      "signal_layers": n_copper, "volume_mm3": 3942.47, "stackup_verdict": verdict,
                      "stackup_id": None},
            "total_with_board_mm3": 6950.38,
            "top": {"count": placed[0], "total_volume_mm3": 1200.0, "missing_height": 0, "largest_items": big("top")},
            "bottom": {"count": placed[1], "total_volume_mm3": 800.0, "missing_height": 0,
                       "largest_items": big("bottom")},
            "scopes": [{"key": "unit", "n_units": 1, "total_mm3": 6950.38, "mass_g": 29.87, "basis": "보드 외곽 면적 × 두께"}]}


def _job(job_id: str, revision: str, filename: str) -> dict:
    return {"job_id": job_id, "project": "PRJ-ALPHA", "model": "SM-X100", "board_type": "Main", "revision": revision,
            "job_name": "designodb", "step_name": "pcb", "original_filename": filename,
            "uploaded_at": "2026-10-20T01:02:03+00:00", "uploaded_by": "anonymous", "cache_ready": True,
            "analyses_done": ["volume", "checklist"]}


def _boards() -> dict:
    std_parts, non_parts = _parts(748, "PN"), _parts(528, "QN")
    return {
        JOB_STD: {
            "job": _job(JOB_STD, "0.7", "alpha_main_r07.tgz"),
            "layers": {"job_id": JOB_STD, "layer_count": 35, "signal_layer_count": 10, "total_thickness_mm": 0.59,
                       "thickness_source": "odb", "stackup_verdict": "standard",
                       "viewer_url": f"http://odb-hub.test/viewer?job={JOB_STD}",
                       "layers": _board_layers(10, STD_DIELECTRIC, [
                           *({"name": f"drill_{a}-{b}", "type": "DRILL", "thickness_um": None}
                             for a, b in ((1, 2), (2, 3), (1, 10), (9, 10), (8, 9), (3, 8))),
                           {"name": "doc_fab", "type": "DOCUMENT", "thickness_um": None},
                           {"name": "doc_assy", "type": "DOCUMENT", "thickness_um": None}])},
            "stackup": {"verdict": "standard", "message": "표준 스택업 확인 — 0.59mm / 10L (가이드 4.7)",
                        "thickness_mm": 0.59, "thickness_source": "misc/attrlist .board_thickness (finished)",
                        "layer_count": 10, "chosen_id": "SU47-0.59T-10L-001", "chosen_by_user": False,
                        "layers": _standard_stackup(10, STD_DIELECTRIC)},
            "volume": _volume(std_parts, (610, 314), n_copper=10, verdict="standard"),
            "download": {"job_id": JOB_STD, "sha256": SHA_STD, "size_bytes": 48_211_337, "filename": "alpha_main_r07.tgz"},
            "parts": std_parts,
        },
        JOB_NON: {
            "job": _job(JOB_NON, "0.8", "alpha_main_r08.tgz"),
            "layers": {"job_id": JOB_NON, "layer_count": 26, "signal_layer_count": 8, "total_thickness_mm": 0.495,
                       "thickness_source": "odb", "stackup_verdict": "non_standard",
                       "viewer_url": f"http://odb-hub.test/viewer?job={JOB_NON}",
                       "layers": _board_layers(8, NON_DIELECTRIC, [
                           {"name": f"drill_{a}-{b}", "type": "DRILL", "thickness_um": None}
                           for a, b in ((1, 2), (1, 8), (7, 8))])},
            "stackup": {"verdict": "non_standard", "message": "표준에 없는 두께 — 0.495mm / 8L",
                        "thickness_mm": 0.495, "layer_count": 8, "chosen_id": None, "chosen_by_user": False,
                        "layers": [], "suggestions": [{"stackup_id": "SU47-0.50T-8L-010", "total_um": 500.0}]},
            "volume": _volume(non_parts, (470, 232), n_copper=8, verdict="non_standard"),
            "download": {"job_id": JOB_NON, "sha256": SHA_NON, "size_bytes": 39_002_118, "filename": "alpha_main_r08.tgz"},
            "parts": non_parts,
        },
    }


# 허브의 도구 39개 가운데 이름이 있는 것 — 게이트웨이는 다른 앱과 겹친 둘(list_jobs · list_parts)에만 접두를 붙인다(요청서 1절).
ODB_TOOLS = ("ping", "list_jobs", "find_job", "list_rules", "get_rule_detail", "get_checklist_result", "get_violation_map",
             "list_parts", "get_part_detail", "get_parts_summary", "get_managed_parts", "get_board_layers", "list_stackups",
             "get_stackup", "check_job_stackup", "match_stackup", "get_mounting_holes", "get_volume_result",
             "get_interposer_result", "get_copper_result", "list_results", "get_compare_result", "get_compare_table",
             "get_task", "run_checklist", "run_analysis", "run_compare", "find_nets", "get_net", "get_odb_download")


def tool_map(*, prefixed: bool = True, drop: tuple[str, ...] = ()) -> dict[str, str]:
    """게이트웨이 `/tools-map` 의 map(실이름 → 백엔드). prefixed 면 StepForge · KooRemapper 와 이름이 겹친 상태다."""
    out: dict[str, str] = {}
    for tool in ODB_TOOLS:
        if tool in drop:
            continue
        out[f"odbhub_{tool}" if prefixed and tool in ("list_jobs", "list_parts") else tool] = ODB
    for tool in mcad.REQUIRED_TOOLS:
        if tool == "list_parts":
            if prefixed:
                out["heaxstep_forge_list_parts"] = recon.APP_KEY
            continue
        out[tool] = recon.APP_KEY
    if prefixed:
        out["heaxkooremapper_mcp_list_jobs"] = "heax-kooremapper_mcp"
    return out


class FakeOdbHub:
    """게이트웨이 MCP 를 흉내낸다 — odb-hub 도구는 부록 A 꼴로 답하고, 다른 백엔드의 도구는 `others` 원문을 준다.

    `fail` 은 원래 이름 → 'tool_error'(isError) · 'envelope'(200 + {error, hint}) 다. `ignore_page` 면 list_parts 가 늘 첫 쪽을 준다.
    """

    def __init__(self, tools: dict[str, str] | None = None, *, others: dict | None = None) -> None:
        self.boards = _boards()
        filler = [{"job_id": f"{0xF00 + i:016x}", "project": "FILLER", "model": f"FM-{i}", "board_type": "Sub",
                   "revision": "1.0", "job_name": "designodb", "original_filename": f"filler_{i}.tgz",
                   "uploaded_at": "2026-09-01T00:00:00+00:00"} for i in range(12)]
        self.jobs = [b["job"] for b in self.boards.values()] + filler
        self.tools = dict(tools if tools is not None else tool_map())
        self.others = dict(others or {})
        self.fail: dict[str, str] = {}
        self.ignore_page = False
        self.calls: list[tuple[str, dict]] = []

    # ---- odb-hub 도구
    def _find_job(self, args: dict) -> dict:
        query = str(args.get("query") or "").strip().lower()
        hits = [j for j in self.jobs if query == j["job_id"].lower()]
        hits += [j for j in self.jobs if j not in hits and query and any(
            query in str(j.get(k) or "").lower() for k in ("project", "model", "original_filename"))]
        if not hits:
            return {"error": "결과가 없습니다", "hint": "과제명 · 모델명 · 파일 이름이나 job_id 로 찾으세요"}
        return {"query": args.get("query"), "jobs": copy.deepcopy(hits[:10]), "count": min(len(hits), 10),
                "truncated": len(hits) > 10}

    def _list_parts(self, board: dict, args: dict) -> dict:
        size = max(1, min(int(args.get("page_size") or 20), 100))           # 5000 을 줘도 100 이다(부록 B)
        page = 1 if self.ignore_page else max(1, int(args.get("page") or 1))
        rows = board["parts"][(page - 1) * size: page * size]
        total = len(board["parts"])
        return {"job_id": board["job"]["job_id"], "rows": copy.deepcopy(rows), "total": total, "page": page,
                "page_size": size, "returned": len(rows), "has_more": page * size < total}

    def answer(self, original: str, args: dict):
        if self.fail.get(original) == "envelope":
            return {"error": f"{original} 결과가 없습니다", "hint": "run_analysis 로 계산한 뒤 다시 조회하세요"}
        if original == "find_job":
            return self._find_job(args)
        board = self.boards.get(str(args.get("job_id") or ""))
        if board is None:
            return {"error": "잡을 찾을 수 없습니다"}
        if original == "list_parts":
            return self._list_parts(board, args)
        key = {"get_board_layers": "layers", "check_job_stackup": "stackup", "get_volume_result": "volume",
               "get_odb_download": "download"}.get(original)
        return copy.deepcopy(board[key]) if key else {"error": f"가짜에 없는 도구 {original}"}

    # ---- 전송(MockTransport)
    def handler(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}},
                                  headers={"mcp-session-id": "sess-odb"})
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        name, args = payload["params"]["name"], payload["params"]["arguments"]
        self.calls.append((name, args))
        backend = self.tools.get(name)
        original = name[len("odbhub_"):] if name.startswith("odbhub_") else name
        if backend == ODB and self.fail.get(original) != "tool_error":
            body = self.answer(original, args)
        elif backend is not None and name in self.others:
            body = self.others[name]
        else:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
                "isError": True, "content": [{"type": "text", "text": f"unknown tool: {name}"}]}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": body}})

    def mcp(self) -> McpHttpClient:
        return McpHttpClient("https://gw.test/mcp", headers={"Authorization": "Bearer portal-pat"},
                             client=httpx.Client(transport=httpx.MockTransport(self.handler)))

    def channels(self) -> dict:
        """routes 가 부르는 clients_from_settings 의 반환 꼴 — 게이트웨이 MCP · 도구 지도(REST 는 쓰지 않는다)."""
        return {"mcp": self.mcp(), "rest": RestGetClient("https://heax.test", None), "portal_pat": "portal-pat",
                "service_pat": None, "rest_credential": None, "tool_names": tuple(sorted(self.tools)),
                "tool_map": dict(self.tools)}

    def called(self, original: str) -> list[dict]:
        return [args for name, args in self.calls if name in (original, f"odbhub_{original}")]


@pytest.fixture
def hub() -> FakeOdbHub:
    return FakeOdbHub()


def _capture(hub: FakeOdbHub, job_id: str | None, *, kinds=None, extra_sources=(), rest=None) -> dict:
    sources = list(extra_sources)
    if job_id is not None:
        sources.append({"kind": "ecad", "app_key": ODB, "ref": {"odb_job_id": job_id}})
    return adapters_registry.capture_all(
        sources=sources, principal=Principal(owner_sub=OWNER, portal_pat="portal-pat", mcp_credential="user"),
        mcp_client=hub.mcp(), rest_client=rest, kinds=kinds, tool_names=tuple(sorted(hub.tools)), tool_map=hub.tools)


def _ecad(captured: dict) -> dict:
    return next(r for r in captured["results"] if r["source"]["kind"] == "ecad")


def _build(captured: dict) -> dict:
    return ir_builder.build_ir(project_id="0" * 32, owner_sub=OWNER, label="ECAD", snapshot_id="f" * 32,
                              adapter_results=captured["results"], captured_at=1761800000)


def _map_client(body: dict, status_code: int = 200) -> httpx.Client:
    """게이트웨이 `/tools-map` 하나만 답하는 가짜(무인증 GET)."""
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status_code, json=body)))


def _errors(ir: dict) -> list[str]:
    return sorted(f"{'.'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
                  for e in Draft7Validator(SCHEMA).iter_errors(ir))


# ================================================================ 발견(ER-02)
@pytest.mark.parametrize("prefixed", [True, False], ids=["prefixed", "bare"])
def test_discovery_finds_the_six_tools_by_backend_and_original_name(prefixed):
    """백엔드 odb-hub 와 원래 이름으로 찾는다 — 접두형(odbhub_list_parts)이든 맨이름이든 같은 답이고 상태는 실측(ready)이다."""
    body = {"map": tool_map(prefixed=prefixed)}
    rows = {r["kind"]: r for r in adapters_registry.discover_adapters(client=_map_client(body), force=True)}
    assert rows["ecad"]["status"] == "ready" and rows["ecad"]["tools_ok"] is True
    assert rows["ecad"]["app_key"] == ODB and rows["ecad"]["tools_missing"] == []
    probe = adapters_registry.GatewayRegistry("http://gw.test:9110/mcp", client=_map_client(body)).probe("ecad")
    assert probe["tools_present"] == list(ecad_adapter.REQUIRED_TOOLS) and probe["reachable"] is True


def test_a_tool_missing_from_the_odb_backend_is_unavailable_even_if_another_app_has_that_name():
    """StepForge 의 `heaxstep_forge_list_parts` 는 ODB 허브의 list_parts 가 아니다 — 그 백엔드에 없으면 없는 것이다."""
    body = {"map": tool_map(drop=("list_parts", "get_odb_download"))}
    rows = {r["kind"]: r for r in adapters_registry.discover_adapters(client=_map_client(body), force=True)}
    assert rows["ecad"]["status"] == "unavailable" and rows["ecad"]["tools_ok"] is False
    assert rows["ecad"]["tools_missing"] == ["get_odb_download", "list_parts"]
    # 게이트웨이를 아예 못 읽었으면 '없다' 가 아니라 '못 물어봤다' 다.
    dead = {r["kind"]: r for r in adapters_registry.discover_adapters(client=_map_client({}, 503), force=True)}
    assert dead["ecad"]["status"] == "planned" and dead["ecad"]["gateway_error"] == "http_503"


def test_each_call_goes_to_its_own_backend_when_two_apps_share_a_name():
    """list_parts 는 StepForge 와 ODB 허브에 다 있어 둘 다 접두형이다 — 호출은 그 소스의 백엔드 것으로 나간다.

    종전 해석(suffix 하나)은 후보가 둘이라 맨이름 `list_parts` 로 불렀고 그 이름은 게이트웨이에 없다(mcad MCP 폴백이 그렇게 죽는다).
    """
    names = tool_map()
    assert adapters_base.backend_tool_name("list_parts", ODB, names) == "odbhub_list_parts"
    assert adapters_base.backend_tool_name("list_parts", recon.APP_KEY, names) == "heaxstep_forge_list_parts"
    assert adapters_base.backend_tool_name("find_job", ODB, names) == "find_job"
    assert adapters_base.backend_tool_name("list_parts", "heax-nobody", names) is None
    assert adapters_base.resolve_tool_name("list_parts", tuple(names)) == "list_parts"          # 옛 해석은 다의라 맨이름
    seen: list = []
    recorder = CallRecorder("cafe0000deadbeef", mcp=recon._mcp({"heaxstep_forge_list_parts": {"parts": []},
                                                                   "odbhub_list_parts": {"rows": [], "total": 0}}, seen),
                            tool_names=tuple(names), tool_map=names)
    mcad_reply = recorder.call("mcp", "list_parts", {}, source_kind="mcad", app_key=recon.APP_KEY)
    odb_reply = recorder.call("mcp", "list_parts", {"job_id": JOB_STD}, source_kind="ecad", app_key=ODB,
                              response_contract=ecad_adapter.RESPONSE_CONTRACT)
    assert [n for n, _ in seen] == ["heaxstep_forge_list_parts", "odbhub_list_parts"]
    # 계약은 그 어댑터의 표로 잰다 — ODB 허브의 rows 를 StepForge 의 /parts 로 재면 늘 위반이다.
    assert mcad_reply["contract_ok"] is True and odb_reply["contract_ok"] is True


# ================================================================ 캡처(ER-03 · ER-04)
def test_a_standard_board_lands_as_board_layers_and_classified_components(hub):
    """보드 1 꼴 — find_job · get_board_layers · check_job_stackup · get_volume_result · get_odb_download 한 번씩과
    odbhub_list_parts 8쪽(100행씩), 모두 13번. ecad_absent 가 없고 component 수 = list_parts total, layer 수 = 5종으로 거른 행 수다."""
    captured = _capture(hub, JOB_STD)
    result = _ecad(captured)
    source, nodes = result["source"], result["nodes"]
    components = [n for n in nodes if n["kind"] == "component"]
    layers = [n for n in nodes if n["kind"] == "layer"]

    assert result["missing"] == {"ecad_absent": False} and "ecad_absent" not in source["degraded"]
    assert len(components) == len(hub.boards[JOB_STD]["parts"]) == 748 == source["stats"]["n_components"]
    five = [r for r in hub.boards[JOB_STD]["layers"]["layers"] if r["type"] in ecad_adapter.LAYER_TYPES]
    assert len(layers) == len(five) == 23 and source["stats"]["layer_rows_all"] == 35
    # 호출 수 · 이름 · 인자 — 겹친 이름은 접두형으로, 인자는 기본값이라도 다 싣는다(허브가 빠진 선택 인자를 거부한 적이 있다).
    assert [n for n, _ in hub.calls] == ["find_job", "get_board_layers", "check_job_stackup", "get_volume_result",
                                         "get_odb_download"] + ["odbhub_list_parts"] * 8
    assert [a["page"] for a in hub.called("list_parts")] == list(range(1, 9))
    assert all(a == {"job_id": JOB_STD, "category": "", "side": "", "sort": "", "page": a["page"], "page_size": 100}
               for a in hub.called("list_parts"))
    assert [c["tool"] for c in captured["calls"]][-1] == "odbhub_list_parts"
    assert all(c["ok"] and c["contract_ok"] in (True, None) for c in captured["calls"])

    # 보드(소스 1건) — 이름은 project · model · board_type · revision, 동박층 수는 signal_layer_count, 해시는 원본 sha256.
    assert source["ref"] == {"board_id": JOB_STD, "name": "PRJ-ALPHA / SM-X100 / Main / 0.7"}
    assert source["source_hash"] == SHA_STD and source["adapter_version"] == ecad_adapter.ADAPTER_VERSION
    stats = source["stats"]
    assert (stats["thickness_mm"], stats["stackup_verdict"], stats["layer_count"]) == (0.59, "standard", 10)
    assert stats["stackup_total_mm"] == 0.59 and stats["units"] == "mm" and stats["outline_bbox"] is None
    assert stats["outline"] == {"x_mm": 107.18, "y_mm": 72.9693, "area_mm2": 6065.3397}
    assert (stats["n_components_basis"], stats["n_components_placed"], stats["n_nets"]) == ("classified", 924, None)

    # 적층 — 위에서 아래 순서로 1부터, 5종 어휘, 두께는 mm(실크는 null), 재료는 맞춘 표준 적층에서, 동박 무게는 없다.
    assert [n["attrs"]["idx"] for n in layers] == list(range(1, 24))
    assert [n["attrs"]["name"] for n in layers] == [r["name"] for r in five]
    assert [n["canon_key"] for n in layers[:2]] == ["ecad:layer:1", "ecad:layer:2"]
    assert [n["attrs"]["type"] for n in layers[:6]] == ["silkscreen", "soldermask", "signal", "dielectric", "signal",
                                                        "dielectric"]
    assert layers[0]["attrs"]["thickness"] is None and layers[2]["attrs"]["thickness"] == 0.025
    assert [n["attrs"]["material"] for n in layers[:5]] == [None, "SR", "CU", "PPG", "CU"]
    assert {n["attrs"]["copper_weight"] for n in layers} == {None}

    # 부품 — 좌표 · 회전 · 넷 · 값은 지어내지 않고 null, 높이는 큰 부품 10개씩만.
    first = next(n for n in components if n["local_key"] == "C1000")
    assert first["canon_key"] == "ecad:C1000" and first["group"] == "bottom"
    assert first["attrs"] == {"refdes": "C1000", "part_number": "PN-00000", "footprint": "cap0402", "side": "bottom",
                              "x": None, "y": None, "rot": None, "pin_count": 2, "nets": None, "height": None,
                              "value": None}
    tall = [n for n in components if n["attrs"]["height"] is not None]
    assert len(tall) == 20 and {n["attrs"]["height"] for n in tall} == {1.2}

    # ER-04 — 표준 적층 보드는 재료가 맞아 stackup_material_unmatched 가 없다.
    assert set(source["degraded"]) == {
        "ecad_nets_deferred", "component_xy_deferred", "components_unclassified_omitted", "outline_origin_unknown",
        "copper_weight_absent", "plane_type_unknown", "odb_version_absent", "component_value_absent",
        "component_height_partial"}
    assert result["warnings"] == []

    ir = _build(captured)
    assert _errors(ir) == []
    assert ir["missing"]["ecad_absent"] is False and ir["ir_version"] == "1.1" and ir["primary_source"] == "ecad"
    assert sum(1 for n in ir["nodes"] if n["kind"] == "component") == 748


def test_a_non_standard_board_keeps_layers_but_leaves_materials_unmatched(hub):
    """보드 2 꼴 — 적층이 표준에 없어 재료가 비고(표준 적층에서만 온다) stackup_material_unmatched 다. 부품은 6쪽이다."""
    result = _ecad(_capture(hub, JOB_NON))
    layers = [n for n in result["nodes"] if n["kind"] == "layer"]
    components = [n for n in result["nodes"] if n["kind"] == "component"]
    assert len(layers) == 19 and len(components) == 528
    assert {n["attrs"]["material"] for n in layers} == {None}
    assert "stackup_material_unmatched" in result["source"]["degraded"]
    assert result["source"]["stats"]["stackup_verdict"] == "non_standard"
    assert result["source"]["stats"]["stackup_total_mm"] == 0.495 == result["source"]["stats"]["thickness_mm"]
    assert (result["source"]["stats"]["n_components"], result["source"]["stats"]["n_components_placed"]) == (528, 702)
    assert len(hub.called("list_parts")) == 6


@pytest.mark.parametrize("change", ["ambiguous", "one_layer_short", "kind_swapped"])
def test_materials_come_only_from_a_standard_stackup_that_lines_up_layer_by_layer(hub, change):
    """재료는 맞춘 표준 적층에서만 온다 — 판정이 standard 가 아니거나(후보가 여럿인 ambiguous 도) 층 수 · 구분 차례가 하나라도
    어긋나면 자리를 짐작하지 않고 비운다."""
    stackup = hub.boards[JOB_STD]["stackup"]
    if change == "ambiguous":
        stackup["verdict"] = "ambiguous"
    elif change == "one_layer_short":
        stackup["layers"] = stackup["layers"][:-1]
    else:
        stackup["layers"][1], stackup["layers"][2] = stackup["layers"][2], stackup["layers"][1]
    result = _ecad(_capture(hub, JOB_STD))
    assert {n["attrs"]["material"] for n in result["nodes"] if n["kind"] == "layer"} == {None}
    assert "stackup_material_unmatched" in result["degraded"]


def test_an_ecad_board_freezes_beside_mcad_and_mcad_keeps_its_own_tools(hub, risk_store):
    """mcad 와 함께 캡처해도 각 호출은 제 백엔드로 간다 — 스냅샷이 서고(same-as intra mcad↔ecad 포함) ecad_absent 가 없다."""
    hub.others = {name: body for name, body in recon.MCP_TOOLS_FULL.items()}
    hub.others["heaxstep_forge_list_parts"] = recon.MCP_TOOLS_FULL["list_parts"]
    project_id = "e" * 32                  # 봉투 스키마의 project_id 는 32자리 16진이다
    risk_store.execute("INSERT INTO rr_projects(id, owner_sub, code, created_at, updated_at) VALUES (?,?,?,?,?)",
                       (project_id, OWNER, "EC1", 100, 100))
    mcad_card = {"kind": "mcad", "app_key": recon.APP_KEY,
                 "ref": {"stepforge_project_id": recon.SF_PROJECT, "detect_job_id": "01JDET"}}
    captured = _capture(hub, JOB_STD, extra_sources=[mcad_card], rest=recon._rest(recon.REST_ROUTES))
    assert [r["source"]["kind"] for r in captured["results"]] == ["mcad", "ecad"]
    frozen = ir_builder.freeze_snapshot(risk_store, project_id=project_id, owner_sub=OWNER, label="EC1",
                                        adapter_results=captured["results"], calls=captured["calls"],
                                        snapshot_id=captured["snapshot_id"], captured_at=1761800000)
    ir = ir_builder.load_ir(risk_store, frozen["snapshot_id"])
    assert ir["missing"]["ecad_absent"] is False and ir["primary_source"] == "mcad" and _errors(ir) == []
    assert {n["domain"] for n in ir["nodes"]} == {"mcad", "ecad"}
    stored = risk_store.query_one("SELECT COUNT(*) AS n FROM rr_ir_nodes WHERE snapshot_id = ? AND kind = 'component'",
                                  (frozen["snapshot_id"],))["n"]
    assert stored == 748
    # mcad 의 MCP 호출은 StepForge 이름 그대로, ecad 의 list_parts 는 odbhub_ 접두형이다.
    mcad_tools = {c["tool"] for c in captured["calls"] if c["source_kind"] == "mcad"}
    assert "odbhub_list_parts" not in mcad_tools and {"job_status", "part_mesh_map"} <= mcad_tools


def test_the_state_does_not_count_deferred_nets_as_zero(hub):
    """넷은 2단계라 미측정이다 — 0 이 아니다. 부품 수는 분류된 부품만이라고 적는다."""
    st = state_module.build_state(_build(_capture(hub, JOB_STD)), computed_at=1761800001)
    nets, components = st["signals"]["counts.ecad.nets"], st["signals"]["counts.ecad.components"]
    assert (nets["known"], nets["value"]) == (False, None) and "ecad_nets_deferred" in nets["text"]
    assert (components["known"], components["value"]) == (True, 748) and "분류된 부품만" in components["text"]


# ---------------------------------------------------------------- 정직한 결측(ER-04 · 요청서 6절)
def test_without_a_board_nothing_is_called(hub):
    captured = _capture(hub, None, extra_sources=[{"kind": "dyna", "app_key": "heax-kooremapper_mcp", "ref": {}}])
    assert _ecad(captured)["missing"] == {"ecad_absent": True}
    assert not [n for n, _ in hub.calls if hub.tools.get(n) == ODB]
    assert not [c for c in captured["calls"] if c["source_kind"] == "ecad"]


def test_a_board_left_out_of_the_requested_kinds_is_not_read(hub):
    """kinds 에 ecad 가 없으면 붙은 보드도 읽지 않는다 — ECAD 없는 옛 스냅샷과 견줄 캡처를 사람이 고를 수 있다."""
    captured = _capture(hub, JOB_STD, kinds=["dyna"],
                        extra_sources=[{"kind": "dyna", "app_key": "heax-kooremapper_mcp", "ref": {}}])
    result = _ecad(captured)
    assert result["missing"] == {"ecad_absent": True} and result["source"]["adapter_version"] == "0.0-stub"
    assert "kinds" in result["warnings"][0]["message"] and not hub.called("find_job")
    # 보드 카드만 있고 ecad 를 요청하지 않았으면 읽을 소스가 없다.
    with pytest.raises(AppError) as err:
        _capture(FakeOdbHub(), JOB_STD, kinds=["mcad"])
    assert err.value.code == "source_unreachable"


@pytest.mark.parametrize("case", ["tool_missing", "no_channel", "map_unreadable"])
def test_a_board_the_capture_never_reached_is_absent_with_its_reason(hub, case):
    """호출 없이 끝난 실패(도구 없음 · 자격 없음 · 도구 지도를 못 읽음)는 결측 + 경고다 — dyna 의 자격 없음과 같은 꼴이고
    capture_failed 가 아니다(그것은 find_job 을 불렀는데 실패했을 때만이다). 까닭은 경고의 code 로 갈린다."""
    if case == "tool_missing":
        hub.tools = tool_map(drop=("get_odb_download",))
        result, want = _ecad(_capture(hub, JOB_STD)), "ecad_tools_missing"
        assert "get_odb_download" in result["warnings"][0]["message"]
    elif case == "no_channel":
        result = _ecad(adapters_registry.capture_all(
            sources=[{"kind": "ecad", "app_key": ODB, "ref": {"odb_job_id": JOB_STD}}], principal=Principal(owner_sub=OWNER),
            mcp_client=None, tool_map=hub.tools))
        want = "ecad_pat_absent"
    else:
        result = _ecad(adapters_registry.capture_all(
            sources=[{"kind": "ecad", "app_key": ODB, "ref": {"odb_job_id": JOB_STD}}],
            principal=Principal(owner_sub=OWNER, portal_pat="portal-pat", mcp_credential="user"), mcp_client=hub.mcp(),
            tool_map={}))
        want = "ecad_gateway_unreadable"
    assert hub.calls == []
    assert result["missing"] == {"ecad_absent": True}
    assert result["nodes"] == [] and result["degraded"] == ["ecad_absent"]
    assert (result["warnings"][0]["code"], result["warnings"][0]["severity"]) == (want, "WARNING")
    assert result["source"]["adapter_version"] == "0.0-stub" and result["source"]["ref"] == {"board_id": JOB_STD}
    ir = _build({"results": [result]})
    assert ir["missing"]["ecad_absent"] is True and ir["missing"]["ecad_capture_failed"] is False and _errors(ir) == []


@pytest.mark.parametrize("case", ["not_found", "find_job_error"])
def test_a_board_that_could_not_be_read_is_a_failed_capture_not_an_empty_board(hub, case):
    """find_job 을 불렀는데 실패했거나 그 job_id 가 없으면 '회로가 없다' 가 아니다 — ecad_absent 와 ecad_capture_failed 가 함께
    서고 까닭이 경고에 남는다(§2.11.3 필수 호출 실패)."""
    if case == "not_found":
        result, want = _ecad(_capture(hub, "0123456789abcdef")), "ecad_board_not_found"
        assert [n for n, _ in hub.calls] == ["find_job"] and "결과가 없습니다" in result["warnings"][0]["message"]
    else:
        hub.fail["find_job"] = "tool_error"
        result, want = _ecad(_capture(hub, JOB_STD)), "capture_call_failed"
    assert result["missing"] == {"ecad_absent": True, "ecad_capture_failed": True}
    assert result["nodes"] == [] and result["degraded"] == ["ecad_absent"]
    assert (result["warnings"][0]["code"], result["warnings"][0]["severity"]) == (want, "WARNING")
    assert result["source"]["adapter_version"] == "0.0-stub"
    ir = _build({"results": [result]})
    assert ir["missing"]["ecad_absent"] is True and ir["missing"]["ecad_capture_failed"] is True and _errors(ir) == []


def test_an_optional_call_that_fails_leaves_its_fields_empty_and_marks_the_capture_partial(hub):
    """선택 호출 실패(§2.11.3 표) — 그 칸만 비고 capture_partial 이다. 부품은 그대로 실린다."""
    hub.fail["get_volume_result"] = "tool_error"
    result = _ecad(_capture(hub, JOB_STD))
    stats = result["source"]["stats"]
    assert "capture_partial" in result["degraded"] and stats["outline"] is None and stats["n_components_placed"] is None
    assert len([n for n in result["nodes"] if n["kind"] == "component"]) == 748
    assert {"components_unclassified_omitted", "component_height_partial"} <= set(result["degraded"])
    assert [w["code"] for w in result["warnings"]] == ["capture_call_failed"]


def test_a_value_the_hub_does_not_have_is_a_warning_not_a_failure(hub):
    """허브의 봉투형 오류(200 + error — 분석을 돌리지 않은 보드)는 그 칸이 허브에 없다는 뜻이다 — 경고만 남고 부분 캡처가 아니다."""
    hub.fail["get_volume_result"] = "envelope"
    result = _ecad(_capture(hub, JOB_STD))
    assert "capture_partial" not in result["degraded"] and result["source"]["stats"]["outline"] is None
    assert [w["code"] for w in result["warnings"]] == ["odb_error_body"]
    assert "get_volume_result 결과가 없습니다" in result["warnings"][0]["message"]


def test_components_over_the_cap_are_truncated_and_say_so(hub, monkeypatch):
    monkeypatch.setattr(ecad_adapter, "MAX_COMPONENTS", 150)
    result = _ecad(_capture(hub, JOB_STD))
    assert len([n for n in result["nodes"] if n["kind"] == "component"]) == 150
    assert "components_truncated" in result["degraded"] and len(hub.called("list_parts")) == 2


def test_a_hub_that_ignores_the_page_does_not_loop(hub):
    """다음 쪽이 있다는데 새 행이 없으면 멈춘다 — 같은 쪽을 끝없이 부르지 않는다."""
    hub.ignore_page = True
    result = _ecad(_capture(hub, JOB_STD))
    assert len(hub.called("list_parts")) == 2 and "capture_partial" in result["degraded"]
    assert len([n for n in result["nodes"] if n["kind"] == "component"]) == 100
    assert "odb_paging_stalled" in [w["code"] for w in result["warnings"]]


# ================================================================ 보드 고르기(ER-01) — REST · MCP
WEB = identity.Identity(email=OWNER, display_name=OWNER, role="user", organization=None, anonymous=False,
                        source="cookie", token="heax-web-token")


@pytest.fixture
def web_box(risk_store, monkeypatch, hub):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(adapters_registry, "clients_from_settings", lambda *a, **k: hub.channels())
    # ECAD 보드는 그 사람의 등록된 포털 PAT 로만 찾고 읽는다(사용자 결정 10-31) — 웹 설정 화면이 남기는 것과 같은 자격 행.
    risk_store.upsert_credential(OWNER, identity.encrypt_pat("pat-board-owner").decode("ascii"), "sub-owner", OWNER, "[]",
                                 now_epoch() + 30 * 86400)
    project = routes.create_project(routes.ProjectBody(code="EC-1", name="보드 과제", classification="internal"), ident=WEB)
    return project["id"]


def _audits(store) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT action, before_json, after_json, channel FROM rr_audit WHERE action = 'project.ecad_board' ORDER BY rowid",
        ())]


def test_the_search_shows_candidates_and_never_picks_one(web_box, hub):
    """같은 모델의 두 판이 다 후보로 나온다 — 고르는 것은 사람이다. 10개를 넘으면 truncated 다."""
    out = routes.get_ecad_boards(q="SM-X100", ident=WEB)
    assert [c["job_id"] for c in out["candidates"]] == [JOB_STD, JOB_NON] and out["truncated"] is False
    assert out["candidates"][0]["name"] == "PRJ-ALPHA / SM-X100 / Main / 0.7"
    assert set(out["candidates"][0]) == {*ecad_adapter.CANDIDATE_KEYS, "name"}
    assert "chosen" not in out and out["app_key"] == ODB and out["tool"] == "find_job"
    many = routes.get_ecad_boards(q="FILLER", ident=WEB)
    assert len(many["candidates"]) == ecad_adapter.SEARCH_MAX and many["truncated"] is True
    none = routes.get_ecad_boards(q="없는 보드", ident=WEB)
    assert none["candidates"] == [] and "결과가 없습니다" in none["hub_message"]
    with pytest.raises(AppError) as empty:
        routes.get_ecad_boards(q="  ", ident=WEB)
    assert empty.value.http_status == 422


def test_set_replace_and_clear_the_board_of_a_project(web_box, hub, risk_store):
    project_id = web_box
    first = routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id=JOB_STD.upper()), ident=WEB)
    assert first["changed"] is True and first["previous_odb_job_id"] is None
    assert first["source"]["ref"] == {"odb_job_id": JOB_STD} and first["source"]["app_key"] == ODB
    assert first["source"]["probe"]["board"]["name"] == "PRJ-ALPHA / SM-X100 / Main / 0.7"
    assert first["source"]["status"] == "linked"
    card_id = first["source"]["id"]
    # 다른 판으로 바꾸면 같은 카드가 바뀐다(카드는 과제마다 한 장) — 감사가 남는다.
    second = routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id=JOB_NON), ident=WEB)
    assert (second["changed"], second["previous_odb_job_id"], second["source"]["id"]) == (True, JOB_STD, card_id)
    again = routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id=JOB_NON), ident=WEB)
    assert again["changed"] is False
    assert [s["kind"] for s in routes._project_sources(project_id)] == ["ecad"]
    # 지어낸 job_id(꼴은 맞는다)는 find_job 에 없어 붙지 않는다. 꼴이 틀리면 허브를 부르지도 않는다.
    with pytest.raises(AppError) as unknown:
        routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id="0123456789abcdef"), ident=WEB)
    assert (unknown.value.code, unknown.value.http_status) == ("ecad_board_not_found", 422)
    calls = len(hub.calls)
    with pytest.raises(AppError) as malformed:
        routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id="SM-X100"), ident=WEB)
    assert malformed.value.code == "E100" and len(hub.calls) == calls
    assert routes._project_sources(project_id)[0]["ref"] == {"odb_job_id": JOB_NON}

    cleared = routes.delete_ecad_board(project_id, ident=WEB)
    assert (cleared["removed"], cleared["previous_odb_job_id"]) == (1, JOB_NON)
    assert routes._project_sources(project_id) == []
    assert routes.delete_ecad_board(project_id, ident=WEB)["removed"] == 0
    audits = _audits(risk_store)
    assert [json.loads(a["after_json"])["odb_job_id"] for a in audits] == [JOB_STD, JOB_NON, None]
    assert {a["channel"] for a in audits} == {"web"}


def test_the_generic_source_route_does_not_attach_a_board(web_box):
    """일반 소스 연결로는 붙지 않는다 — find_job 확인 없이 붙거나 카드가 둘이 되면 어느 보드를 읽을지 uuid 순서가 정한다."""
    with pytest.raises(AppError) as err:
        routes.add_source(web_box, routes.SourceBody(kind="ecad", app_key=ODB, ref={"odb_job_id": JOB_STD}), ident=WEB)
    assert (err.value.code, err.value.http_status) == ("ecad_board_route", 422)
    assert "ecad-board" in err.value.detail["fix"] and routes._project_sources(web_box) == []


def test_capture_after_attaching_reads_the_board_into_the_snapshot(web_box, hub, risk_store):
    """요청서 6절 1단계 캡처 — 보드를 붙인 과제를 캡처하면 missing.ecad_absent 가 없고 component 수가 list_parts total,
    layer 수가 5종으로 거른 행 수다. 카드의 도달 측정도 캡처가 본 것으로 바뀐다."""
    project_id = web_box
    routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id=JOB_STD), ident=WEB)
    before = len(hub.calls)
    out = routes.create_snapshot(project_id, routes.SnapshotBody(), ident=WEB)
    assert out["job_state"] == "done" and out["reused"] is False
    snap = risk_store.query_one("SELECT missing_json, ir_version FROM rr_snapshots WHERE id = ?", (out["snapshot_id"],))
    assert json.loads(snap["missing_json"])["ecad_absent"] is False and snap["ir_version"] == "1.1"
    counts = {r["kind"]: r["n"] for r in risk_store.query(
        "SELECT kind, COUNT(*) AS n FROM rr_ir_nodes WHERE snapshot_id = ? GROUP BY kind", (out["snapshot_id"],))}
    assert counts == {"board": 1, "component": 748, "layer": 23}
    assert len(hub.calls) - before == 13
    card = routes._project_sources(project_id)[0]
    assert card["probe"]["detail"].startswith("capture_ok calls=13") and card["probe"]["board"]["job_id"] == JOB_STD
    # ECAD 는 MCP 로만 읽는다 — 카드의 capture_mode 도 그렇게 적는다(종전에는 rest_primary 로 박혀 있었다).
    assert (card["status"], card["probe"]["capture_mode"]) == ("linked", "mcp")


def test_the_routes_answer_over_http(client, web_box, hub):
    """REST 경로 셋 — GET /api/ecad/boards · PUT · DELETE /api/projects/{id}/ecad-board(신원은 웹 쿠키 신원으로 둔다)."""
    from app.main import app

    app.dependency_overrides[identity.current] = lambda: WEB
    try:
        found = client.get("/api/ecad/boards", params={"q": "SM-X100"})
        assert found.status_code == 200 and len(found.json()["candidates"]) == 2
        put = client.put(f"/api/projects/{web_box}/ecad-board", json={"odb_job_id": JOB_STD})
        assert put.status_code == 200 and put.json()["source"]["ref"] == {"odb_job_id": JOB_STD}
        missing = client.put(f"/api/projects/{web_box}/ecad-board", json={"odb_job_id": "0123456789abcdef"})
        assert missing.status_code == 422 and missing.json()["error"]["code"] == "ecad_board_not_found"
        gone = client.delete(f"/api/projects/{web_box}/ecad-board")
        assert gone.status_code == 200 and gone.json()["removed"] == 1
    finally:
        app.dependency_overrides.pop(identity.current, None)


def _call(tool: str, /, **kwargs) -> dict:
    out = getattr(srv, tool)(**kwargs)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def test_claude_finds_and_sets_the_board_through_the_same_routes(web_box, hub, risk_store, monkeypatch):
    """MCP — 찾기 · 붙이기 · 떼기가 REST 와 같은 함수를 같은 신원으로 지난다. 위임으로 확인된 신원만 쓴다."""
    project_id = web_box
    factories.act_as_delegate(monkeypatch, OWNER)

    found = _call("risk_find_ecad_boards", query="SM-X100")
    assert [c["job_id"] for c in found["candidates"]] == [JOB_STD, JOB_NON] and "사용자" in found["note"]
    attached = _call("risk_set_ecad_board", project_id=project_id, odb_job_id=JOB_NON)
    assert attached["ok"] is True and attached["source"]["ref"] == {"odb_job_id": JOB_NON}
    assert attached["web"]["project"].endswith(project_id)
    refused = _call("risk_add_source", project_id=project_id, kind="ecad", ref={"odb_job_id": JOB_STD})
    assert refused["error"] == "ecad_board_route"
    cleared = _call("risk_set_ecad_board", project_id=project_id, odb_job_id=None)
    assert cleared["removed"] == 1
    audit = risk_store.query("SELECT channel FROM rr_audit WHERE action = 'project.ecad_board'", ())
    assert {r["channel"] for r in audit} == {"mcp"}

    monkeypatch.setattr(srv, "_request", lambda: None)            # 신원 없는 호출(게이트웨이 위임 단언이 없다)
    assert _call("risk_find_ecad_boards", query="SM-X100")["error"] == "delegation_required"
    assert _call("risk_set_ecad_board", project_id=project_id, odb_job_id=JOB_STD)["error"] == "delegation_required"


# ================================================================ 반대 검토(10-31) 뒤 고친 것
def _ecad_ir(hub: FakeOdbHub, job_id: str) -> dict:
    """보드 하나만 캡처한 IR(ECAD 결측 행 · 노드 · 세대의 원천)."""
    return _build(_capture(hub, job_id))


def _with_ecad(ir: dict, ecad_ir: dict) -> dict:
    """mcad 쌍 픽스처(diff_pairs)에 ECAD 를 얹는다 — 소스 행 · 노드 · 결측 둘 · 어댑터 세대를 ECAD 만 캡처한 IR 에서 옮긴다."""
    out = copy.deepcopy(ir)
    out["nodes"] = [n for n in out["nodes"] if n["domain"] != "ecad"] + copy.deepcopy(ecad_ir["nodes"])
    out["sources"] = [s for s in out["sources"] if s["kind"] != "ecad"] + copy.deepcopy(ecad_ir["sources"])
    for key in ("ecad_absent", "ecad_capture_failed"):
        out["missing"][key] = ecad_ir["missing"][key]
    out["versions"]["adapter_versions"]["ecad"] = ecad_ir["versions"]["adapter_versions"]["ecad"]
    return out


def _events(d: dict) -> list[tuple]:
    return [(e["code"], e["confidence"], e.get("caveat")) for e in d["semantic"]["events"]]


def _clone_board(hub: FakeOdbHub, tag: str, revision: str) -> tuple[str, str]:
    """JOB_STD 와 층 · 분류된 부품이 똑같고 정체(job_id · 원본 해시 · 판)만 다른 보드 — 배치 · 배선만 바꾼 판이다."""
    sha = _sha(tag)
    job_id = sha[:16]
    board = copy.deepcopy(hub.boards[JOB_STD])
    board["job"] = _job(job_id, revision, tag)
    board["layers"]["job_id"] = job_id
    board["download"] = {**board["download"], "job_id": job_id, "sha256": sha, "filename": tag}
    hub.boards[job_id] = board
    hub.jobs.append(board["job"])
    return job_id, sha


def test_the_board_is_one_board_node_with_the_contract_fields(hub):
    """보드 1장 = 소스 1건 + board 노드 1건(요청서 ER-03 · 4절). 계약 odb_get_board 의 칸과 판정 · 적층 합 · 배치 수가 노드에
    실린다 — 두께 · 적층 합은 rr_ir 길이 단위 mm 다. label 은 판이 바뀌어도 같고 local_key 는 job_id 다."""
    ir = _ecad_ir(hub, JOB_STD)
    boards = [n for n in ir["nodes"] if n["kind"] == "board"]
    assert len(boards) == 1 and _errors(ir) == []
    board = boards[0]
    assert (board["canon_key"], board["label"], board["local_key"], board["domain"]) == ("ecad:board", "board", JOB_STD,
                                                                                          "ecad")
    assert board["attrs"] == {
        "board_id": JOB_STD, "name": "PRJ-ALPHA / SM-X100 / Main / 0.7", "revision": "0.7", "units": "mm",
        "outline_bbox": None, "outline": {"x_mm": 107.18, "y_mm": 72.9693, "area_mm2": 6065.3397}, "thickness": 0.59,
        "stackup_verdict": "standard", "stackup_id": "SU47-0.59T-10L-001", "ecad_stackup_total": 0.59, "layer_count": 10,
        "n_components": 748, "n_components_placed": 924, "n_nets": None, "odb_version": None, "source_hash": SHA_STD}
    assert board["provenance"]["tool"] == "find_job" and board["geom_fp"] is None


def test_swapping_in_a_revision_with_the_same_stage1_content_makes_a_new_snapshot(web_box, hub, risk_store):
    """반대 검토 1(높음) — 배치 · 배선만 바꾼 판은 1단계 칸(층 · 분류된 부품)이 같다. 보드가 소스에만 있으면 ir_hash 가 같아 앞 판의
    스냅샷이 옛 보드 이름 · 해시로 재사용됐다. 보드 노드가 ir_hash 에 들어 새 스냅샷이 서고, 같은 보드를 다시 캡처하면 재사용이다."""
    project_id = web_box
    twin, twin_sha = _clone_board(hub, "alpha_main_r09_layout_only.tgz", "0.9")
    routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id=JOB_STD), ident=WEB)
    first = routes.create_snapshot(project_id, routes.SnapshotBody(), ident=WEB)
    again = routes.create_snapshot(project_id, routes.SnapshotBody(), ident=WEB)
    assert (again["reused"], again["snapshot_id"]) == (True, first["snapshot_id"])
    routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id=twin), ident=WEB)
    second = routes.create_snapshot(project_id, routes.SnapshotBody(), ident=WEB)
    assert second["reused"] is False and second["snapshot_id"] != first["snapshot_id"]
    ir = ir_builder.load_ir(risk_store, second["snapshot_id"])
    board = next(n for n in ir["nodes"] if n["kind"] == "board")
    source = next(s for s in ir["sources"] if s["kind"] == "ecad")
    assert (board["attrs"]["board_id"], board["attrs"]["revision"], board["attrs"]["source_hash"]) == (twin, "0.9", twin_sha)
    assert (source["ref"]["board_id"], source["source_hash"]) == (twin, twin_sha)
    # 두 판의 차이는 보드 노드 하나다 — 층 · 부품 노드는 그대로다.
    def rest(snapshot_id: str) -> list:
        return sorted((n["nid"], json.dumps(n["attrs"], sort_keys=True))
                      for n in ir_builder.load_ir(risk_store, snapshot_id)["nodes"] if n["kind"] != "board")
    assert rest(first["snapshot_id"]) == rest(second["snapshot_id"])


@pytest.mark.parametrize("why", ["not_found", "partial"])
def test_an_unread_board_leaves_the_mcad_meaning_of_a_pair_diff_alone(hub, why):
    """반대 검토 2 — 보드를 못 읽었거나 부분이면 ECAD 항목에만 capture_partial 이 붙는다. mcad 의 의미 이벤트 · 수치는 보드가 없던
    쌍과 같다(종전에는 ecad_capture_failed 하나가 쌍 전체의 의미층을 지웠고, ECAD 노드 771 개는 사유 없이 '삭제' 였다)."""
    plain = diff_module.compute_diff(_pair("base"), _pair("pair_kind"))
    loaded = _ecad_ir(hub, JOB_STD)
    if why == "not_found":
        broken = _ecad_ir(FakeOdbHub(), "0123456789abcdef")
        assert broken["missing"]["ecad_capture_failed"] is True
    else:
        broken = copy.deepcopy(loaded)
        source = next(s for s in broken["sources"] if s["kind"] == "ecad")
        source["degraded"] = sorted({*source["degraded"], "capture_partial"})
        broken["nodes"] = [n for n in broken["nodes"] if n["kind"] != "component" or n["local_key"] < "J"]
    d = diff_module.compute_diff(_with_ecad(_pair("base"), loaded), _with_ecad(_pair("pair_kind"), broken))
    comp = d["comparability"]
    assert comp["capture_parity"] is True and comp["adapter_parity"] is True
    assert comp["ecad"] == {"base": "present", "target": "failed", "excluded_reason": "capture_partial",
                            "adapter_parity": True}
    assert _events(d) == _events(plain) and _events(plain)
    assert [p["excluded_reason"] for p in d["parametric"]["edge_params"]] == \
        [p["excluded_reason"] for p in plain["parametric"]["edge_params"]]
    ecad = [c for c in d["structural"]["node_changes"] if c["domain"] == "ecad"]
    assert ecad and {c["op"] for c in ecad} == {"removed"} and {c["excluded_reason"] for c in ecad} == {"capture_partial"}
    assert diff_module.changed_ckeys(d) == diff_module.changed_ckeys(plain)


def test_a_board_on_one_side_only_neither_downgrades_mcad_nor_floods_part_added(hub):
    """반대 검토 3 — 앞 스냅샷에 보드가 없고(결측 행 0.0-stub) 뒤에만 실렸다(1.0). mcad 항목 · 이벤트에 parser_differs 가 붙지
    않고, ECAD 노드 772 개는 partial_scope 로 남되 part.added 를 만들지 않는다(웹 기본 kinds 캡처와 MCP 캡처를 견줄 때 흔하다)."""
    plain = diff_module.compute_diff(_pair("base"), _pair("pair_kind"))
    d = diff_module.compute_diff(_pair("base"), _with_ecad(_pair("pair_kind"), _ecad_ir(hub, JOB_STD)))
    assert d["comparability"]["adapter_parity"] is True
    assert d["comparability"]["ecad"] == {"base": "absent", "target": "present", "excluded_reason": "partial_scope",
                                          "adapter_parity": True}
    assert _events(d) == _events(plain)
    ecad = [c for c in d["structural"]["node_changes"] if c["domain"] == "ecad"]
    assert len(ecad) == 1 + 23 + 748 and {(c["op"], c["excluded_reason"]) for c in ecad} == {("added", "partial_scope")}
    assert not [e for e in d["semantic"]["events"] if e["code"] == "part.added"]


def test_an_ecad_generation_change_marks_only_ecad_items(hub):
    """두 쪽 다 보드를 실었는데 ECAD 어댑터 세대가 다르면 ECAD 이벤트에만 parser_differs 와 등급 한 단계 낮춤이다 — mcad 는 그대로."""
    plain = diff_module.compute_diff(_pair("base"), _pair("pair_kind"))
    loaded = _ecad_ir(hub, JOB_STD)
    newer = copy.deepcopy(loaded)
    newer["versions"]["adapter_versions"]["ecad"] = "1.1"
    gone = next(n for n in newer["nodes"] if n["kind"] == "component")
    newer["nodes"].remove(gone)
    d = diff_module.compute_diff(_with_ecad(_pair("base"), loaded), _with_ecad(_pair("pair_kind"), newer))
    assert d["comparability"]["adapter_parity"] is True and d["comparability"]["ecad"]["adapter_parity"] is False
    assert d["comparability"]["ecad"]["excluded_reason"] is None
    removed = [e for e in d["semantic"]["events"] if e["code"] == "part.removed"]
    assert [e["subject"]["dns"] for e in removed] == [[gone["dn"]]]
    assert (removed[0]["caveat"], removed[0]["confidence"]) == ("parser_differs", "low")
    assert [x for x in _events(d) if x[0] != "part.removed"] == _events(plain)


def test_ecad_domains_wait_on_a_diff_target_and_are_told_why(hub, risk_store):
    """반대 검토 4 — 1단계 쌍 비교는 ECAD 칸 변화를 싣지 않는다. diff 대상의 ECAD 의존 영역은 deferred · 입력 결손이고 결측
    블록이 까닭을 말한다. 스냅샷 대상은 보드가 실렸으면 그대로 풀린다(ER-05)."""
    project_id = factories.make_project(risk_store)
    a = factories.make_snapshot(risk_store, project_id, _capture(hub, JOB_STD)["results"], label="A")
    b = factories.make_snapshot(risk_store, project_id, _capture(hub, JOB_NON)["results"], label="B")
    made = factories.make_diff(risk_store, a["snapshot_id"], b["snapshot_id"])
    seats = factories.agents(("mech", "pcb"), 2)
    diff_key = factories.make_target(risk_store, "diff", made["diff_id"], agents=seats)
    order = {r["agent_key"]: r for r in planner.review_order(risk_store, diff_key)}
    assert {k: r["input_gaps"] for k, r in order.items()} == {
        "mech-syn-0": [], "mech-syn-1": [], "pcb-syn-0": ["ecad_absent"], "pcb-syn-1": ["ecad_absent"]}
    assert {k for k, r in order.items() if r["deferred"]} == {"pcb-syn-1"}
    missing = units_module._target_missing(risk_store, diff_key, None)
    assert missing[0] == {"kind": "ecad", "note": units_module._ECAD_DIFF_NOTE}
    assert units_module.gap_missing(missing, ["ecad_absent"], "pcb")[0]["note"].endswith(
        f"이 영역이 볼 것 — {units_module.input_gap_hint('pcb')}.")

    snap_key = factories.make_target(risk_store, "snap", b["snapshot_id"], agents=seats)
    order = planner.review_order(risk_store, snap_key)
    assert all(r["input_gaps"] == [] and not r["deferred"] for r in order)
    assert [m for m in units_module._target_missing(risk_store, snap_key, None) if m["kind"] == "ecad"] == []


@pytest.mark.parametrize("tool", ["list_parts", "get_board_layers"])
def test_a_node_family_the_hub_did_not_give_is_marked_unavailable(hub, tool):
    """반대 검토 5 — 허브가 부품 목록 · 층을 200 + error 로 답하면(분석을 돌리지 않은 보드) 그 노드 가족이 통째로 빠진다. 경고만
    남기면 '보드에 없다' 로 읽히므로 components_unavailable · layers_unavailable 를 세우고 그 수는 미측정(null)이다."""
    hub.fail[tool] = "envelope"
    result = _ecad(_capture(hub, JOB_STD))
    kinds = collections.Counter(n["kind"] for n in result["nodes"])
    stats = result["source"]["stats"]
    degraded = set(result["degraded"])
    if tool == "list_parts":
        assert "components_unavailable" in degraded and kinds["component"] == 0 and stats["n_components"] is None
        assert not degraded & {"components_unclassified_omitted", "component_xy_deferred", "component_value_absent"}
        assert len(hub.called("list_parts")) == 1
    else:
        assert "layers_unavailable" in degraded and kinds["layer"] == 0
        assert (stats["layer_rows"], stats["layer_rows_all"]) == (None, None)
        assert not degraded & {"copper_weight_absent", "plane_type_unknown", "stackup_material_unmatched"}
    assert kinds["board"] == 1 and "capture_partial" not in degraded
    assert [w["code"] for w in result["warnings"]] == ["odb_error_body"]
    assert _errors(_build({"results": [result]})) == []


def test_unstable_paging_that_drops_rows_is_a_partial_capture(hub, monkeypatch):
    """반대 검토 6 — 쪽 순서가 쪽마다 다른 허브는 어떤 행을 두 번 주고 어떤 행은 주지 않는다. 받은 행 수가 total 과 같아도 서로
    다른 행이 모자라면 부분 캡처다(종전에는 겹친 행을 '자료 탓' 경고로만 남기고 빠진 부품을 말하지 않았다)."""
    def unstable(board: dict, args: dict) -> dict:
        page = max(1, int(args.get("page") or 1))
        ordered = sorted(board["parts"], key=lambda p: p["refdes"], reverse=page % 2 == 0)
        rows = ordered[(page - 1) * 100: page * 100]
        return {"job_id": board["job"]["job_id"], "rows": copy.deepcopy(rows), "total": len(board["parts"]), "page": page,
                "page_size": 100, "returned": len(rows), "has_more": page * 100 < len(board["parts"])}

    monkeypatch.setattr(hub, "_list_parts", unstable)
    result = _ecad(_capture(hub, JOB_STD))
    components = [n for n in result["nodes"] if n["kind"] == "component"]
    assert len(components) < 748 and "capture_partial" in result["degraded"]
    incomplete = next(w for w in result["warnings"] if w["code"] == "components_incomplete")
    assert f"서로 다른 행 {len(components)}개" in incomplete["message"] and "받은 행 748" in incomplete["message"]
    assert "duplicate_refdes" in [w["code"] for w in result["warnings"]]


def test_a_hub_that_pages_forever_is_cut_at_the_page_cap(hub, monkeypatch):
    """반대 검토 12 — has_more 를 늘 참으로 주고 쪽마다 새 행 하나만 주는 허브는 종전에 2,000 번 가까이 불렸다. 실을 수 있는
    만큼(total · 상한 2000)의 쪽 수 + 1 에서 멈추고 부분 캡처라고 적는다."""
    def endless(board: dict, args: dict) -> dict:
        page = max(1, int(args.get("page") or 1))
        rows = [dict(board["parts"][0])] * 99 + [{**board["parts"][0], "refdes": f"X{page:05d}"}]
        return {"job_id": board["job"]["job_id"], "rows": rows, "total": 100000, "page": page, "page_size": 100,
                "returned": 100, "has_more": True}

    monkeypatch.setattr(hub, "_list_parts", endless)
    result = _ecad(_capture(hub, JOB_STD))
    assert len(hub.called("list_parts")) == ecad_adapter._page_cap(100000) == 21
    assert "capture_partial" in result["degraded"] and "odb_paging_capped" in [w["code"] for w in result["warnings"]]


def test_a_placed_count_below_the_classified_count_warns_and_keeps_the_marker(hub):
    """반대 검토 11 — 면별 count 가 배치 수가 아니면(큰 부품 10개 수 따위) 배치 수가 분류된 부품 수보다 작다. 그럴 수 없으므로
    경고하고, 분류 안 된 부품이 빠졌다는 표지는 그대로 둔다."""
    volume = hub.boards[JOB_STD]["volume"]
    for side in ("top", "bottom"):
        volume[side]["count"] = len(volume[side]["largest_items"])
    result = _ecad(_capture(hub, JOB_STD))
    assert result["source"]["stats"]["n_components_placed"] == 20
    assert "components_unclassified_omitted" in result["degraded"]
    assert [w["code"] for w in result["warnings"]] == ["placed_below_classified"]


def test_the_placed_count_falls_back_to_counted(hub):
    """요청서 OH-02 는 배치 수를 counted 라 적었다 — count 가 없을 때만 그것을 읽는다(부록 A 는 count)."""
    for side in ("top", "bottom"):
        block = hub.boards[JOB_STD]["volume"][side]
        block["counted"] = block.pop("count")
    assert _ecad(_capture(hub, JOB_STD))["source"]["stats"]["n_components_placed"] == 924


def test_a_tools_map_the_gateway_failed_to_give_is_not_cached():
    """반대 검토 8 — 한 번 못 읽은 지도(503)를 60 초 캐시하면 그동안 모든 ECAD 캡처 · 찾기가 '도구 없음' 이다. 못 읽은 지도는
    캐시하지 않고, 읽은 지도는 캐시한다(세 번째 부름은 게이트웨이에 가지 않는다 — 가면 응답이 바닥나 StopIteration)."""
    answers = iter([httpx.Response(503, json={"detail": "busy"}), httpx.Response(200, json={"map": tool_map()})])
    client = httpx.Client(transport=httpx.MockTransport(lambda request: next(answers)))
    assert adapters_registry.gateway_tool_map(client=client) == {}
    assert adapters_registry.gateway_tool_map(client=client) == tool_map()
    assert adapters_registry.gateway_tool_map(client=client) == tool_map()


def test_the_search_says_when_the_gateway_map_could_not_be_read(web_box, hub, monkeypatch):
    """지도를 못 읽은 것은 'odb-hub 의 find_job 이 없다' 가 아니다 — 고칠 곳이 게이트웨이라 따로 말한다."""
    monkeypatch.setattr(adapters_registry, "clients_from_settings", lambda *a, **k: {**hub.channels(), "tool_map": {}})
    with pytest.raises(AppError) as err:
        routes.get_ecad_boards(q="SM-X100", ident=WEB)
    assert (err.value.code, err.value.http_status) == ("ecad_gateway_unreadable", 409) and hub.calls == []


def test_a_board_only_project_whose_board_cannot_be_read_freezes_nothing(web_box, hub, risk_store):
    """반대 검토 9 · 10 — 읽은 카드가 ECAD 하나뿐인데 보드를 못 읽었으면 노드 0 개짜리 스냅샷을 동결하지 않고 잡을 failed ·
    409 source_unreachable 로 닫는다(§2.11.3). 호출 원문은 스냅샷 없이 남고 카드는 '연결됨' 이 아니라 그 까닭이다. 붙은 보드만
    있는데 kinds 가 ecad 를 뺐으면 '연결하라' 가 아니라 kinds 를 고칠 일이라고 말한다."""
    project_id = web_box
    routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id=JOB_STD), ident=WEB)
    ok = routes.create_snapshot(project_id, routes.SnapshotBody(), ident=WEB)
    card = routes._project_sources(project_id)[0]
    assert (card["status"], card["probe"]["capture_mode"]) == ("linked", "mcp")

    hub.jobs = [j for j in hub.jobs if j["job_id"] != JOB_STD]             # 허브에서 보드가 지워졌다
    with pytest.raises(AppError) as err:
        routes.create_snapshot(project_id, routes.SnapshotBody(), ident=WEB)
    assert (err.value.code, err.value.http_status) == ("source_unreachable", 409)
    assert err.value.detail == {"kind": "ecad", "reason": "ecad_board_not_found"}
    assert [r["id"] for r in risk_store.query("SELECT id FROM rr_snapshots WHERE project_id = ?", (project_id,))] == \
        [ok["snapshot_id"]]
    job = risk_store.query_one("SELECT state, error_json FROM rr_snapshot_jobs WHERE project_id = ? ORDER BY rowid DESC"
                               " LIMIT 1", (project_id,))
    assert job["state"] == "failed" and json.loads(job["error_json"])["reason"] == "ecad_board_not_found"
    orphan = risk_store.query("SELECT tool FROM rr_snapshot_calls WHERE snapshot_id IS NULL", ())
    assert [r["tool"] for r in orphan] == ["find_job"]
    card = routes._project_sources(project_id)[0]
    assert card["status"] == "unreachable" and card["probe"]["capture_mode"] is None
    assert card["probe"]["detail"].startswith("capture_failed ecad_board_not_found")

    with pytest.raises(AppError) as kinds:
        routes.create_snapshot(project_id, routes.SnapshotBody(kinds=["mcad"]), ident=WEB)
    assert kinds.value.code == "source_unreachable" and kinds.value.detail == {"kinds": ["mcad"], "attached": ["ecad"]}
    assert "연결된 소스는 ecad" in kinds.value.message


@pytest.mark.parametrize("reply", ["others_first", "only_others"])
def test_the_board_is_the_exact_job_id_never_a_first_or_same_model_candidate(web_box, hub, reply):
    """반대 검토 13 — find_job 이 다른 판을 앞에 내도 붙이기 · 캡처는 그 job_id 와 같은 행만 쓴다. 같은 행이 없으면 붙이지 않고
    (ecad_board_not_found) 캡처도 보드를 읽지 않는다 — 첫 후보로 대신하면 모델 이름으로 고르는 것과 같다(ER-01)."""
    rows = [hub.boards[JOB_NON]["job"]] + ([hub.boards[JOB_STD]["job"]] if reply == "others_first" else [])
    hub._find_job = lambda args: {"query": args.get("query"), "jobs": copy.deepcopy(rows), "count": len(rows),
                                  "truncated": False}
    if reply == "others_first":
        out = routes.put_ecad_board(web_box, routes.EcadBoardBody(odb_job_id=JOB_STD), ident=WEB)
        assert out["source"]["ref"] == {"odb_job_id": JOB_STD} and out["ecad_board"]["job_id"] == JOB_STD
    else:
        with pytest.raises(AppError) as err:
            routes.put_ecad_board(web_box, routes.EcadBoardBody(odb_job_id=JOB_STD), ident=WEB)
        assert err.value.code == "ecad_board_not_found" and routes._project_sources(web_box) == []
    mark = len(hub.calls)
    result = _ecad(_capture(hub, JOB_STD))
    after = hub.calls[mark:]
    if reply == "others_first":
        assert result["source"]["ref"]["board_id"] == JOB_STD
        assert sum(1 for n in result["nodes"] if n["kind"] == "component") == 748
        assert {a.get("job_id") for n, a in after if n != "find_job"} == {JOB_STD}
    else:
        assert result["missing"] == {"ecad_absent": True, "ecad_capture_failed": True}
        assert result["warnings"][0]["code"] == "ecad_board_not_found" and [n for n, _ in after] == ["find_job"]


def test_an_empty_job_id_does_not_detach_the_board(web_box, hub, monkeypatch):
    """odb_job_id 가 null 일 때만 뗀다 — 빈 글자는 422 이고 붙은 보드는 그대로다."""
    factories.act_as_delegate(monkeypatch, OWNER)
    assert _call("risk_set_ecad_board", project_id=web_box, odb_job_id=JOB_STD)["ok"] is True
    refused = _call("risk_set_ecad_board", project_id=web_box, odb_job_id="")
    assert refused["error"] == "E100"
    assert routes._project_sources(web_box)[0]["ref"] == {"odb_job_id": JOB_STD}


def test_a_pair_diff_of_two_large_boards_does_not_build_the_full_name_product(hub):
    """반대 검토 15 — same-as 5단계가 모든 쌍을 펼치면 부품 2,000 개 보드 두 판의 쌍 비교가 5 초 · 330 MB 였다. 이름으로 나눠
    짝을 찾아도 대응은 같다(2,023 쌍 전부 name_norm)."""
    def big(tag: str) -> dict:
        board = copy.deepcopy(hub.boards[JOB_STD])
        board["parts"] = _parts(2000, tag)
        return board

    hub.boards[JOB_STD] = big("PN")
    base = _ecad_ir(hub, JOB_STD)
    hub.boards[JOB_STD] = big("QN")
    target = _ecad_ir(hub, JOB_STD)
    tracemalloc.start()
    try:
        d = diff_module.compute_diff(base, target)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert len(d["correspondence"]["matched"]) == 1 + 23 + 2000
    assert d["correspondence"]["method_counts"]["name_norm"] == 1 + 23 + 2000
    assert peak < 50_000_000, f"쌍 비교 최고 메모리 {peak / 1e6:.0f} MB"


def test_a_refdes_that_would_collide_with_a_node_key_is_not_loaded(hub):
    """refdes 가 board · layer: · net: 꼴이면 보드 · 층 · 넷 노드의 canon_key(`ecad:board` · `ecad:layer:<idx>` · `ecad:net:…`)와 겹쳐
    IR 이 서지 않는다(canon_key 중복은 E100) — 그 행만 싣지 않고 경고한다."""
    parts = hub.boards[JOB_STD]["parts"]
    parts[0]["refdes"], parts[1]["refdes"] = "board", "layer:1"
    result = _ecad(_capture(hub, JOB_STD))
    assert sum(1 for n in result["nodes"] if n["kind"] == "component") == 746
    assert [w["code"] for w in result["warnings"]] == ["refdes_reserved"]
    assert "capture_partial" not in result["degraded"]
    ir = _build({"results": [result]})
    assert sum(1 for n in ir["nodes"] if n["kind"] == "board") == 1 and _errors(ir) == []


def test_a_partly_read_board_leaves_the_card_linked_but_says_partial(web_box, hub):
    """보드를 실었지만 선택 호출이 실패했으면 카드는 연결됨이되 capture_partial 과 실패한 호출을 적는다(capture_ok 가 아니다)."""
    routes.put_ecad_board(web_box, routes.EcadBoardBody(odb_job_id=JOB_STD), ident=WEB)
    hub.fail["get_volume_result"] = "tool_error"
    out = routes.create_snapshot(web_box, routes.SnapshotBody(), ident=WEB)
    assert out["job_state"] == "partial"
    card = routes._project_sources(web_box)[0]
    assert (card["status"], card["probe"]["capture_mode"]) == ("linked", "mcp")
    assert card["probe"]["detail"].startswith("capture_partial calls=12 app_key=odb-hub get_volume_result=")
