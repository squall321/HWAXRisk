# ECAD(ODB 허브) 1단계 — 요청서 부록 A 꼴의 가짜 odb-hub(표준 · 비표준 적층 두 보드 · list_parts 100행 쪽 상한 · 이름 겹침 접두)로 발견 · 캡처 · 표지를 본다(실 허브 호출 0)
"""포털 docs/design-risk-review/ecad-1031 의 ER-02 ~ ER-04 를 시험한다.

가짜의 응답 꼴은 cae00 10-31 실측(요청서 부록 A)과 허브 레퍼런스(포털 docs/procedures/fixtures/odb-hub/reference.md 4절)에서
옮겼다. find_job 의 봉투 열쇠는 부록 A 에 없어 list_jobs 와 같은 `jobs` 로 둔다(어댑터는 알려진 꼴 넷을 읽는다).
dev 게이트웨이에는 odb-hub 가 없다 — 실물 확인은 cae00 다시 볼 시험(요청서 6절)이다.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft7Validator

from app import ir_builder
from app import state as state_module
from app.adapters import base as adapters_base
from app.adapters import ecad as ecad_adapter
from app.adapters import mcad
from app.adapters import registry as adapters_registry
from app.adapters.base import CallRecorder, Principal, RestGetClient
from app.errors import AppError
from app.ra_client import McpHttpClient
from tests import test_adapters as recon
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
        sources=sources, principal=Principal(owner_sub=OWNER, portal_pat="portal-pat"), mcp_client=hub.mcp(),
        rest_client=rest, kinds=kinds, tool_names=tuple(sorted(hub.tools)), tool_map=hub.tools)


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


@pytest.mark.parametrize("case", ["tool_missing", "no_channel", "not_found", "find_job_error"])
def test_a_board_that_could_not_be_read_is_a_failed_capture_not_an_empty_board(hub, case):
    """붙은 보드를 못 읽었으면 '회로가 없다' 가 아니다 — ecad_absent 와 ecad_capture_failed 가 함께 서고 까닭이 경고에 남는다."""
    if case == "tool_missing":
        hub.tools = tool_map(drop=("get_odb_download",))
        result, want = _ecad(_capture(hub, JOB_STD)), "ecad_tools_missing"
        assert hub.calls == [] and "get_odb_download" in result["warnings"][0]["message"]
    elif case == "no_channel":
        result = _ecad(adapters_registry.capture_all(
            sources=[{"kind": "ecad", "app_key": ODB, "ref": {"odb_job_id": JOB_STD}}], principal=Principal(owner_sub=OWNER),
            mcp_client=None, tool_map=hub.tools))
        want = "ecad_pat_absent"
    elif case == "not_found":
        result, want = _ecad(_capture(hub, "0123456789abcdef")), "ecad_board_not_found"
        assert [n for n, _ in hub.calls] == ["find_job"] and "결과가 없습니다" in result["warnings"][0]["message"]
    else:
        hub.fail["find_job"] = "tool_error"
        result, want = _ecad(_capture(hub, JOB_STD)), "capture_call_failed"
    assert result["missing"] == {"ecad_absent": True, "ecad_capture_failed": True}
    assert result["nodes"] == [] and result["degraded"] == ["ecad_absent"]
    assert result["warnings"][0]["code"] == want and result["source"]["adapter_version"] == "0.0-stub"
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
