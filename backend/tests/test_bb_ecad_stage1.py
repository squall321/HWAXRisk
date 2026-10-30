# 리스크 심사 ECAD 1단계 블랙박스 시험(포털 docs/design-risk-review/ecad-1031/request.md ER-01 ~ ER-05) — 게이트웨이 odb-hub 응답을 부록 A(cae00 10-31 실측 꼴)대로 지은 가짜 위에서 과제 → 보드 붙이기 → 캡처를 공개 경로로 흘려 노드 수 · 유도 칸 · 표지 · 발견 · 자동 고르기 금지를 본다
from __future__ import annotations

import collections
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft7Validator

from app import config, identity, ir_builder, routes
from app.adapters import registry as adapters_registry
from app.errors import AppError
from tests.conftest import REPO_ROOT

# ================================================================ 가정 — 요청서가 이름을 정하지 않은 인터페이스(구현과 다르면 여기만 고친다)
# A1 보드를 붙이는 칸 — ecad 소스 카드(POST /api/projects/{id}/sources, kind='ecad')의 ref 에 `job_id` 를 담는다.
#    ER-01 「과제 대상에 ECAD 보드(job_id)를 담는 칸을 둔다」 와 계약의 job_ref(= odb-hub job_id, 16자리 16진)를 따른다.
# A2 사람이 고를 후보 창구 — 이 앱의 GET 경로 하나(경로에 ecad · odb · board 가운데 하나)가 find_job 후보를 돌려준다.
#    검색어는 q 또는 query 로 받고, 후보는 응답에서 job_id 를 가진 객체 목록, 잘림 표지는 응답의 truncated 다.
# A3 보드 노드 — rr_ir 노드 kind 'board' 1건이다(ER-03 「board · layer · component … 노드를 만든다」).
# A4 attrs 칸 이름 — 계약(docs/odb-adapter-contract.md)의 필드 이름 그대로다. board 는 odb_get_board 의 칸(board_id · name ·
#    units · outline_bbox · thickness · layer_count · n_components · n_nets · odb_version), layer 는 {idx, name, type, thickness,
#    material, copper_weight}, component 는 {refdes, part_number, footprint, side, x, y, rot, pin_count, nets, height, value}다.
# A5 적층 두께 합 — 이름 `ecad_stackup_total`(계약 · 부록 A)로 dims_named 나 board attrs 에 싣는다.


def _ecad_ref(job_id: str) -> dict:
    """A1 — 사람이 고른 보드를 담는 ecad 소스 카드의 ref."""
    return {"job_id": job_id}


def _nodes(ir: dict, kind: str) -> list[dict]:
    return [n for n in ir["nodes"] if n["domain"] == "ecad" and n["kind"] == kind]


def _board(ir: dict) -> dict:
    """A3 — 보드 노드 1건."""
    boards = _nodes(ir, "board")
    assert len(boards) == 1, f"보드 노드는 1건이어야 한다(ER-03) — {len(boards)}건"
    return boards[0]


def _stackup_total_um(ir: dict) -> float | None:
    """A5 — dims_named 의 ecad_stackup_total(단위가 mm 면 µm 로 바꾼다) 또는 board attrs 의 같은 이름(µm)."""
    for dim in ir.get("dims_named") or []:
        if dim.get("name") == "ecad_stackup_total" and dim.get("value") is not None:
            return float(dim["value"]) * (1000.0 if str(dim.get("unit") or "") == "mm" else 1.0)
    value = (_board(ir).get("attrs") or {}).get("ecad_stackup_total")
    return None if value is None else float(value)


def _board_search(client, ident: identity.Identity, project_id: str, query: str) -> dict:
    """A2 — 보드 후보 창구를 경로 모양으로 찾아 TestClient 로 부른다(경로 · 인자 이름이 정해지지 않았다)."""
    from app.main import app

    paths = sorted({r.path for r in routes.router.routes
                    if "GET" in (getattr(r, "methods", None) or set()) and re.search(r"ecad|odb|board", r.path, re.I)})
    assert len(paths) == 1, f"가정 A2 — 보드 후보를 내는 GET 경로(ecad · odb · board)가 하나여야 한다 — {paths}"
    path = paths[0].replace("{project_id}", project_id)
    assert "{" not in path, f"가정 A2 — 모르는 경로 인자가 있다 — {paths[0]}"
    before = app.dependency_overrides.get(identity.current)
    app.dependency_overrides[identity.current] = lambda: ident
    try:
        reply = client.get(path, params={"q": query, "query": query})
    finally:
        if before is None:
            app.dependency_overrides.pop(identity.current, None)
        else:
            app.dependency_overrides[identity.current] = before
    assert reply.status_code == 200, (path, reply.status_code, reply.text[:300])
    return reply.json()


def _candidates(body) -> list[dict]:
    """A2 — 응답에서 job_id 를 가진 객체 목록 하나."""
    if isinstance(body, list):
        return body
    lists = [v for v in body.values()
             if isinstance(v, list) and v and all(isinstance(x, dict) and "job_id" in x for x in v)]
    assert len(lists) == 1, f"가정 A2 — 후보 목록(job_id 를 가진 객체 목록)이 하나여야 한다 — {sorted(body)}"
    return lists[0]


# ================================================================ 가짜 odb-hub — 부록 A 칸 이름 + 09-16 실측 표본(포털 docs/procedures/fixtures/odb-hub/reference.md §4)
# 부록 A 가 정하지 않은 꼴 둘은 가정이다 — find_job 후보 목록의 키(`jobs`, 같은 서버 list_jobs 와 같다고 본다)와
# get_volume_result 면별 배치 수의 키(부록 A 는 count, OH-02 는 counted 라 적었다 — 둘 다 같은 값으로 싣는다).
OWNER = "ecad-bb@example.com"
APP_PAT = "app-portal-pat-not-real"          # 박스 secrets.env 의 HWAXRISK_PORTAL_PAT 자리(가짜 값)
ODB, SF, STE, OTHER = "odb-hub", "heax-step_forge", "smart-twin-cluster", "heax-other_app"
STAGE1_TOOLS = ("find_job", "get_board_layers", "check_job_stackup", "get_volume_result", "get_odb_download", "list_parts")
CONTRACT_TOOLS = ("odb_get_board", "odb_list_components", "odb_list_nets", "odb_get_stackup")
# odb-hub 가 게이트웨이에 내는 도구 — 09-16 표본의 27개(reference.md §2)와 요청서 1절이 이름으로 든 새 셋(find_nets · get_net ·
# get_odb_download). cae00 10-31 에는 39개다 — 나머지 아홉은 이름을 몰라 싣지 않았다(이 시험이 쓰는 도구는 다 들어 있다).
ODB_TOOLS = (
    "ping", "list_jobs", "find_job", "list_rules", "get_rule_detail", "get_checklist_result", "get_violation_map",
    "list_parts", "get_part_detail", "get_parts_summary", "get_managed_parts", "get_board_layers", "list_stackups",
    "get_stackup", "check_job_stackup", "match_stackup", "get_mounting_holes", "get_volume_result", "get_interposer_result",
    "get_copper_result", "list_results", "get_compare_result", "get_compare_table", "get_task", "run_checklist",
    "run_analysis", "run_compare", "find_nets", "get_net", "get_odb_download",
)
# 같은 원래 이름을 내는 남의 백엔드 — 그래서 odb-hub 쪽이 odbhub_list_parts · odbhub_list_jobs 로 노출된다(요청서 1절).
SF_TOOLS = ("list_parts", "list_interfaces", "interface_graph", "project_tree", "job_status", "part_mesh_map")
STE_TOOLS = ("list_jobs", "get_job_details")
LIST_PARTS_PAGE_CAP = 100                   # page_size 5000 을 줘도 100 행으로 줄인다(부록 B).
LIST_PARTS_DEFAULT_PAGE = 20                # 비우면 서버 기본 20(reference.md §2 list_parts).
FIND_JOB_CAP = 10                           # 후보 10개까지, 넘치면 truncated(ER-01).
FIVE = {"SIGNAL": "signal", "POWER_GROUND": "plane", "DIELECTRIC": "dielectric",
        "SOLDER_MASK": "soldermask", "SILK_SCREEN": "silkscreen"}
# ER-04 제안 표지 — 1단계에서 보드 1 · 2 둘 다 서야 한다(둘 다 동박층이 전부 SIGNAL 이고 분류 안 된 부품이 있다).
STAGE1_MARKERS = frozenset({
    "ecad_nets_deferred", "component_xy_deferred", "components_unclassified_omitted", "outline_origin_unknown",
    "copper_weight_absent", "plane_type_unknown", "odb_version_absent", "component_value_absent", "component_height_partial",
})
ER04_MARKERS = STAGE1_MARKERS | {"stackup_material_unmatched"}
# 1단계에서 서면 안 되는 표지 — 보드를 실었는데 부재, 허브가 mm 로 주는데 mil 환산, 2단계 몫(좌표 일부 · 넷 잘림), 748 은 2000 상한 아래다.
NEVER_IN_STAGE1 = frozenset({"ecad_absent", "unit_converted_mil", "component_xy_partial", "nets_truncated",
                             "components_truncated"})
# 1단계가 부르면 안 되는 도구 — 부품 · 넷마다 부르는 2단계 도구와 결과를 만드는(쓰는) 도구.
FORBIDDEN_IN_STAGE1 = frozenset({"get_part_detail", "find_nets", "get_net", "run_checklist", "run_analysis",
                                 "run_compare", "get_managed_parts"})
IC_PKGS = ("bga41f_W235L235_SB019_1_LT", "wlp30_W200L250_SB015", "qfn24_W400L400")
CAP_PKGS = ("C0402_N", "C0201_N", "C0603_N")


def _sha(tag: str) -> str:
    return hashlib.sha256(f"odb-bb:{tag}".encode()).hexdigest()


def _meta(sha: str, project: str, model: str, board_type: str, revision: str, uploaded_at: str) -> dict:
    """find_job · list_jobs 한 행 — job_id 는 sha256 앞 16자리다(부록 A source_hash 행). job_name · step_name 은 기본값이 겹친다."""
    return {"job_id": sha[:16], "project": project, "model": model, "board_type": board_type, "revision": revision,
            "job_name": "designodb", "step_name": "pcb", "original_filename": f"{model}_{board_type}_{revision}.tgz",
            "uploaded_at": uploaded_at, "uploaded_by": "anonymous", "cache_ready": True,
            "analyses_done": ["checklist", "volume"]}


def _side(i: int) -> str:
    return "bottom" if i % 3 == 0 else "top"


def _parts(tag: str, *, ics: int, conns: int, inds: int, caps: int) -> tuple[dict, ...]:
    """list_parts 의 분류된 부품 행 전부(reference.md §4.5 꼴). 실드캔 20개가 면마다 큰 부품 10개다 — 부품 코드가 저마다 다르다."""
    rows: list[dict] = []

    def add(refdes, part, pkg, w, length, side, pins, category):
        rows.append({"refdes": refdes, "part_name": part, "pkg_name": pkg, "pkg_width": round(w, 3),
                     "pkg_length": round(length, 3), "side": side, "pin_count": pins, "category": category})

    for k in range(1, 21):
        add(f"SC{1000 + k}", f"SHIELD-{tag}-{k:02d}", f"SHIELD_CAN_{tag}_{k:02d}", 10.0 + k * 0.5, 8.0 + k * 0.25,
            "top" if k <= 10 else "bottom", 8, "Shield Can")
    for i in range(ics):
        add(f"U{1001 + i}", f"1205-{tag}{i:04d}", IC_PKGS[i % 3], 2.35 + i % 4, 2.35 + i % 5, _side(i),
            41 + (i * 7) % 400, "IC")
    for i in range(conns):
        add(f"J{1001 + i}", f"3710-{tag}{i % 5:04d}", "BTB_40P_0.35", 6.2, 2.1, _side(i), 20 + i % 40, "Connector")
    for i in range(inds):
        add(f"L{1001 + i}", f"2703-{tag}{i % 11:04d}", "L0402_N", 1.0, 0.5, _side(i), 2, "Inductor")
    for i in range(caps):
        add(f"C{1001 + i}", f"2203-{tag}{i % 37:04d}", CAP_PKGS[i % 3], 0.6, 0.3, _side(i), 2, "Capacitor")
    return tuple(rows)


def _layers(copper: list[tuple[str, str, float]], dielectric: list[float], mask_um: float) -> tuple[dict, ...]:
    """get_board_layers.layers — 위에서 아래로 물리 순서이고 부품 · 페이스트 · 드릴 · 문서 층이 섞여 온다. 실크는 두께가 null 이다."""
    def row(name, kind, um=None):
        return {"name": name, "type": kind, "thickness_um": um}

    out = [row("comp_+_top", "COMPONENT"), row("sst", "SILK_SCREEN"), row("spt", "SOLDER_PASTE"),
           row("smt", "SOLDER_MASK", mask_um)]
    for i, (name, kind, um) in enumerate(copper):
        out.append(row(name, kind, um))
        if i < len(dielectric):
            out.append(row(f"dielectric_{i + 1}", "DIELECTRIC", dielectric[i]))
    out += [row("smb", "SOLDER_MASK", mask_um), row("spb", "SOLDER_PASTE"), row("ssb", "SILK_SCREEN"),
            row("comp_+_bot", "COMPONENT")]
    n = len(copper)
    out += [row(f"drl_{a}-{b}", "DRILL") for a, b in ((1, n), (1, 2), (2, 3), (n - 2, n - 1), (n - 1, n), (2, n - 1))]
    out += [row("outline", "DOCUMENT"), row("fab_notes", "DOCUMENT")]
    return tuple(out)


@dataclass(frozen=True)
class Board:
    """odb-hub 보드 1장 — 도구마다 이 값에서 응답을 짓는다."""

    meta: dict
    sha256: str
    layers: tuple
    stackup: dict             # check_job_stackup 응답
    parts: tuple              # 분류된 부품 행(list_parts)
    unclassified: dict        # 면마다 분류 안 된 부품 수 — get_volume_result 배치 수에만 든다(OH-02)
    outline: dict             # get_volume_result.board

    @property
    def job_id(self) -> str:
        return self.meta["job_id"]

    @property
    def five(self) -> list[dict]:
        """5종으로 거른 행(물리 순서) — layer 노드가 되는 행이다(부록 A idx · type 행)."""
        return [r for r in self.layers if r["type"] in FIVE]

    @property
    def total_um(self) -> float:
        return sum(r["thickness_um"] or 0.0 for r in self.five)

    @property
    def copper(self) -> list[dict]:
        return [r for r in self.layers if r["type"] in ("SIGNAL", "POWER_GROUND")]

    def placed(self, side: str) -> int:
        return sum(1 for p in self.parts if p["side"] == side) + self.unclassified[side]

    def heights(self) -> dict[str, float]:
        """면마다 큰 부품 10개의 높이(get_volume_result.largest_items[].height_mean_mm, mm)."""
        return {p["refdes"]: round(1.0 + int(p["refdes"][2:]) % 1000 * 0.05, 3)
                for p in self.parts if p["category"] == "Shield Can"}

    def largest(self, side: str) -> list[dict]:
        heights = self.heights()
        return [{"refdes": p["refdes"], "part_name": p["part_name"], "pkg_name": p["pkg_name"],
                 "volume_mm3": round(p["pkg_width"] * p["pkg_length"] * heights[p["refdes"]], 3),
                 "height_mean_mm": heights[p["refdes"]]}
                for p in self.parts if p["refdes"] in heights and p["side"] == side]

    def materials(self) -> list[str | None]:
        """5종 행마다 맞춘 표준 적층의 자재 — 실크는 표준 적층에 없다. 표준이 아니면 전부 None 이다(부록 A material 행)."""
        standard = iter(self.stackup.get("layers") or [])
        out: list[str | None] = []
        for row in self.five:
            if row["type"] == "SILK_SCREEN" or self.stackup.get("verdict") != "standard":
                out.append(None)
            else:
                out.append(next(standard)["material"])
        return out


def _build(meta: dict, sha: str, *, copper: list[tuple[str, str, float]], dielectric: list[float], mask_um: float,
           standard: list[str] | None, parts: tuple, unclassified: dict, outline_xy: tuple[float, float]) -> Board:
    layers = _layers(copper, dielectric, mask_um)
    total_mm = round(sum(r["thickness_um"] or 0.0 for r in layers if r["type"] in FIVE) / 1000.0, 3)
    n = len(copper)
    if standard is not None:
        rows = [{"name": "SR", "kind": "SolderResist", "thickness_um": mask_um, "material": "SR"}]
        for i, (_, _, um) in enumerate(copper):
            rows.append({"name": f"L{i + 1}", "kind": "Signal", "thickness_um": um, "material": "CU"})
            if i < len(dielectric):
                rows.append({"name": f"L{i + 1}-L{i + 2}", "kind": "Dielectric", "thickness_um": dielectric[i],
                             "material": standard[i]})
        rows.append({"name": "SR", "kind": "SolderResist", "thickness_um": mask_um, "material": "SR"})
        stackup_id = f"SU47-{total_mm:g}T-{n}L-041"
        stackup = {"verdict": "standard", "message": f"표준 스택업 확인 — {total_mm:g}mm / {n}L (가이드 4.7)",
                   "thickness_mm": total_mm, "thickness_source": "misc/attrlist .board_thickness (finished)",
                   "layer_count": n, "chosen_id": stackup_id, "chosen_by_user": False, "layers": rows}
    else:
        stackup_id = None
        stackup = {"verdict": "non_standard", "message": f"표준에 없는 두께 — {total_mm:g}mm / {n}L",
                   "thickness_mm": total_mm, "thickness_source": "odb", "layer_count": n, "chosen_id": None,
                   "chosen_by_user": False, "layers": [],
                   "suggestions": [{"stackup_id": f"SU47-0.65T-{n}L-030", "total_um": 650.0, "layer_count": f"{n}L"}]}
    x_mm, y_mm = outline_xy
    outline = {"outline_area_mm2": round(x_mm * y_mm * 0.78, 4), "x_mm": x_mm, "y_mm": y_mm, "thickness_mm": total_mm,
               "signal_layers": n, "volume_mm3": round(x_mm * y_mm * 0.78 * total_mm, 4),
               "stackup_verdict": stackup["verdict"], "stackup_id": stackup_id}
    return Board(meta=meta, sha256=sha, layers=layers, stackup=stackup, parts=parts, unclassified=unclassified,
                 outline=outline)


def _signal_stack(outer: float, inner: float, n: int) -> list[tuple[str, str, float]]:
    return [(f"signal_{i + 1}", "SIGNAL", outer if i in (0, n - 1) else inner) for i in range(n)]


PROJECT_A, MODEL_A = "PRJ-ALPHA", "SM-A123"
PROJECT_B, MODEL_B = "PRJ-BETA", "SM-B456"
# 보드 1 — 체크리스트가 끝나고 적층이 표준인 보드. 층 35 · 동박 10 · 5종 23행, 분류된 부품 748 · 실제 배치 924(요청서 OH-02 · 부록 A).
SHA1 = _sha("board-1")
B1 = _build(_meta(SHA1, PROJECT_A, MODEL_A, "Main", "0.7", "2026-10-29T02:11:40+00:00"), SHA1,
            copper=_signal_stack(30.0, 15.0, 10), dielectric=[60.0, 60.0, 60.0, 80.0, 60.0, 80.0, 60.0, 60.0, 60.0],
            mask_um=20.0, standard=["PPG", "PPG", "PPG", "PPG", "CCL", "PPG", "PPG", "PPG", "PPG"],
            parts=_parts("A7", ics=95, conns=18, inds=150, caps=465), unclassified={"top": 100, "bottom": 76},
            outline_xy=(107.18, 72.97))
# 보드 1 의 다른 판(같은 과제 · 모델 · 보드 역할, revision 0.8) — find_job(모델) 에 함께 나온다(ER-01).
SHA1R8 = _sha("board-1-rev0.8")
B1R8 = _build(_meta(SHA1R8, PROJECT_A, MODEL_A, "Main", "0.8", "2026-10-30T07:02:11+00:00"), SHA1R8,
              copper=_signal_stack(30.0, 15.0, 10), dielectric=[60.0, 60.0, 60.0, 80.0, 60.0, 80.0, 60.0, 60.0, 60.0],
              mask_um=20.0, standard=["PPG", "PPG", "PPG", "PPG", "CCL", "PPG", "PPG", "PPG", "PPG"],
              parts=_parts("A8", ics=100, conns=18, inds=160, caps=514), unclassified={"top": 101, "bottom": 80},
              outline_xy=(107.18, 72.97))
SUB1 = _meta(_sha("board-1-sub"), PROJECT_A, MODEL_A, "Sub", "0.7", "2026-10-29T02:15:02+00:00")
# 보드 2 — 적층이 표준과 다른 보드. 5종 19행, 분류된 부품 528 · 실제 배치 702(요청서 OH-02 · 부록 A idx 행).
SHA2 = _sha("board-2")
B2 = _build(_meta(SHA2, PROJECT_B, MODEL_B, "S_AP", "0.2", "2026-10-27T11:40:09+00:00"), SHA2,
            copper=_signal_stack(28.0, 14.0, 8), dielectric=[64.0, 64.0, 64.0, 64.0, 64.0, 64.0, 70.0], mask_um=18.0,
            standard=None, parts=_parts("B2", ics=60, conns=12, inds=96, caps=340),
            unclassified={"top": 90, "bottom": 84}, outline_xy=(61.4, 52.3))
# 보드 3 — 보드 2 와 같되 안쪽 동박 둘이 POWER_GROUND 다(두 표본 보드에는 없던 꼴 — 타입 사상만 본다).
SHA3 = _sha("board-3-planes")
_PLANES = [("plane_2" if i == 1 else "plane_7" if i == 6 else name, "POWER_GROUND" if i in (1, 6) else kind, um)
           for i, (name, kind, um) in enumerate(_signal_stack(28.0, 14.0, 8))]
B3 = _build(_meta(SHA3, "PRJ-DELTA", "SM-D789", "Main", "0.1", "2026-10-26T09:00:00+00:00"), SHA3,
            copper=_PLANES, dielectric=[64.0, 64.0, 64.0, 64.0, 64.0, 64.0, 70.0], mask_um=18.0, standard=None,
            parts=_parts("D1", ics=60, conns=12, inds=96, caps=340), unclassified={"top": 90, "bottom": 84},
            outline_xy=(61.4, 52.3))
# 같은 과제로 12장 — find_job 이 10개까지 내고 truncated 를 세운다.
FILLERS = tuple(_meta(_sha(f"filler-{i}"), "PRJ-GAMMA", f"SM-C1{i:02d}", "Main", "1.0", "2026-10-20T00:00:00+00:00")
                for i in range(12))
BOARDS = (B1, B1R8, B2, B3)
JOBS = (B1.meta, B1R8.meta, SUB1, B2.meta, B3.meta, *FILLERS)


def gateway_map(variant: str = "request", *, odb_missing: tuple[str, ...] = (),
                others: dict[str, str] | None = None) -> dict[str, str]:
    """게이트웨이 `/tools-map` 의 map — {게이트웨이 이름: 백엔드}.

    이름이 겹치면 odb-hub 쪽은 `odbhub_` 접두가 붙는다(백엔드 키에서 '-' 를 뺀 접두, registry.tool_matches 설명). variant
    'request' 는 요청서 1절 그대로 odb-hub 쪽만 접두이고, 'both' 는 게이트웨이 규칙대로 남의 쪽에도 접두가 붙은 꼴이다.
    `others` 는 {원래 이름: 백엔드} — 그 이름을 내는 남의 백엔드를 더한다(다른 앱이 같은 이름을 들인 날).
    """
    owners: dict[str, list[str]] = collections.defaultdict(list)
    for name in SF_TOOLS:
        owners[name].append(SF)
    for name in STE_TOOLS:
        owners[name].append(STE)
    for name in ODB_TOOLS:
        if name not in odb_missing:
            owners[name].append(ODB)
    for name, backend in (others or {}).items():
        owners[name].append(backend)
    out: dict[str, str] = {}
    for name, backends in owners.items():
        for backend in backends:
            prefixed = len(backends) > 1 and (backend == ODB or variant == "both")
            out[(backend.replace("-", "") + "_" + name) if prefixed else name] = backend
    return out


def _original(name: str, backend: str) -> str:
    prefix = backend.replace("-", "") + "_"
    return name[len(prefix):] if name.startswith(prefix) else name


@dataclass(frozen=True)
class Call:
    name: str          # 게이트웨이 이름(접두 포함)
    backend: str
    tool: str          # 그 백엔드의 원래 이름
    args: dict


@dataclass
class FakeGateway:
    """게이트웨이 하나 — `/tools-map` 과 `/mcp`(JSON-RPC)를 흉내 내고, 받은 도구 호출을 백엔드 · 원래 이름과 함께 적는다."""

    map: dict
    boards: dict = field(default_factory=lambda: {b.job_id: b for b in BOARDS})
    jobs: tuple = JOBS
    calls: list = field(default_factory=list)
    # 쪽을 끝없이 넘기는 어댑터가 시험을 매달지 않게 하는 상한이다(넘으면 봉투형 오류를 돌려준다).
    call_cap: int = 400

    # ---- 전송(httpx.HTTPTransport.handle_request 자리)
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("/tools-map"):
            return httpx.Response(200, json={"map": dict(self.map)})
        if request.method == "POST" and path.endswith("/mcp"):
            payload = json.loads(request.content.decode("utf-8") or "{}")
            method, rid = payload.get("method"), payload.get("id")
            if method == "initialize":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {}},
                                      headers={"mcp-session-id": "sess-ecad-bb"})
            if method == "notifications/initialized":
                return httpx.Response(202)
            if method == "tools/list":
                tools = [{"name": n, "inputSchema": {"type": "object"}} for n in sorted(self.map)]
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {"tools": tools}})
            if method == "tools/call":
                params = payload.get("params") or {}
                body = self.answer(str(params.get("name") or ""), dict(params.get("arguments") or {}))
                result = ({"isError": True, "content": [{"type": "text", "text": f"unknown tool: {params.get('name')}"}]}
                          if body is None else {"structuredContent": body})
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": result})
        return httpx.Response(404, json={"detail": "not found"})

    # ---- 도구
    def answer(self, name: str, args: dict) -> dict | None:
        backend = self.map.get(name)
        if backend is None:
            return None
        tool = _original(name, backend)
        self.calls.append(Call(name, backend, tool, dict(args)))
        if len(self.calls) > self.call_cap:
            return {"error": "가짜 게이트웨이 호출 상한을 넘었다"}
        if backend != ODB:
            # 남의 백엔드 — 불렸다는 사실이 남는 것이 요지다. 답은 그 앱 꼴의 빈 목록이다.
            return {"parts": []} if tool == "list_parts" else {"jobs": []}
        return self._odb(tool, args)

    def _odb(self, tool: str, args: dict) -> dict:
        if tool == "ping":
            return {"status": "ok", "server": "odb-hub", "jobs": len(self.jobs)}
        if tool == "find_job":
            return self._find_job(str(args.get("query") or ""))
        if tool == "list_jobs":
            limit = min(int(args.get("limit") or 20), 100)
            offset = int(args.get("offset") or 0)
            rows = [dict(j) for j in self.jobs[offset:offset + limit]]
            return {"jobs": rows, "total": len(self.jobs), "returned": len(rows), "offset": offset,
                    "has_more": offset + len(rows) < len(self.jobs)}
        if tool == "get_stackup":
            found = next((b.stackup for b in self.boards.values() if b.stackup.get("chosen_id") == args.get("stackup_id")),
                         None)
            return ({"stackup_id": found["chosen_id"], "layers": [dict(r) for r in found["layers"]]} if found
                    else {"error": "표준 스택업이 없습니다"})
        board = self.boards.get(str(args.get("job_id") or ""))
        if board is None:
            return {"error": "결과가 없습니다", "hint": "job_id 를 확인하세요 — find_job 으로 찾는다"}
        if tool == "get_board_layers":
            return {"job_id": board.job_id, "layer_count": len(board.layers), "signal_layer_count": len(board.copper),
                    "total_thickness_mm": board.stackup["thickness_mm"], "thickness_source": "odb",
                    "layers": [dict(r) for r in board.layers], "stackup_verdict": board.stackup["verdict"]}
        if tool == "check_job_stackup":
            return {"job_id": board.job_id, **json.loads(json.dumps(board.stackup))}
        if tool == "get_volume_result":
            sides = {side: {"count": board.placed(side), "counted": board.placed(side), "missing_height": 0,
                            "largest_items": board.largest(side)} for side in ("top", "bottom")}
            return {"job_id": board.job_id, "grand_total_mm3": 3007.9131, "pkg_mass_kg": 0.011730907,
                    "board": dict(board.outline), **sides, "total_with_board_mm3": 6950.3839,
                    "scopes": [{"key": "unit", "n_units": 1, "total_mm3": 6950.3839, "mass_g": 29.8663,
                                "basis": "보드 외곽 면적 × 두께"}]}
        if tool == "get_odb_download":
            return {"job_id": board.job_id, "sha256": board.sha256, "size_bytes": 18_734_522,
                    "original_filename": board.meta["original_filename"]}
        if tool == "list_parts":
            return self._list_parts(board, args)
        if tool == "get_parts_summary":
            cats = collections.Counter((p["category"], p["side"]) for p in board.parts)
            names = sorted({c for c, _ in cats})
            return {"job_id": board.job_id, "total_parts": len(board.parts),
                    "categories": [{"category": c, "top": cats[(c, "top")], "bottom": cats[(c, "bottom")],
                                    "total": cats[(c, "top")] + cats[(c, "bottom")]} for c in names],
                    "note": "미분류(Unknown) 부품은 웹 추출 탭과 동일하게 제외됩니다"}
        if tool == "get_part_detail":
            row = next((p for p in board.parts if p["refdes"] == args.get("refdes")), None)
            return ({"error": "부품이 없습니다"} if row is None else
                    {**row, "footprint_name": row["pkg_name"], "x": 17.27, "y": -53.815, "rotation": -90.0,
                     "mirror": False, "nets": ["GND"], "net_count": 1, "nets_truncated": False, "pins": [],
                     "pins_truncated": False})
        if tool == "find_nets":
            return {"job_id": board.job_id, "nets": [{"name": f"NET_{i:03d}", "feature_count": 400 - i,
                                                      "layers": ["signal_1"]} for i in range(200)], "count": 200}
        if tool == "get_net":
            return {"name": args.get("net"), "pin_count": 2, "units": "mm", "layers": []}
        if tool.startswith("run_"):
            return {"task_id": f"task-{tool}"}
        return {"error": f"이 가짜는 {tool} 을 흉내 내지 않는다"}

    def _find_job(self, query: str) -> dict:
        """job_id 정확 일치가 먼저, 아니면 과제 · 모델 · 파일 이름 부분 일치(대소문자 무시) — 10개까지, 넘치면 truncated."""
        q = query.strip()
        hits = [j for j in self.jobs if j["job_id"] == q] or [
            j for j in self.jobs if q and any(q.lower() in str(j[k]).lower() for k in ("project", "model", "original_filename"))]
        shown = [dict(j) for j in hits[:FIND_JOB_CAP]]
        return {"query": query, "jobs": shown, "count": len(shown), "truncated": len(hits) > FIND_JOB_CAP}

    def _list_parts(self, board: Board, args: dict) -> dict:
        category = str(args.get("category") or "")
        if category == "Unknown":
            return {"error": "category 'Unknown' 으로는 거를 수 없습니다", "hint": "분류된 범주(IC · Capacitor …)만 받는다"}
        side = str(args.get("side") or "")
        rows = [p for p in board.parts if (not category or p["category"] == category) and (not side or p["side"] == side)]
        size = max(1, min(int(args.get("page_size") or LIST_PARTS_DEFAULT_PAGE), LIST_PARTS_PAGE_CAP))
        page = max(1, int(args.get("page") or 1))
        chunk = rows[(page - 1) * size: page * size]
        return {"job_id": board.job_id, "rows": [dict(r) for r in chunk], "page": page, "page_size": size,
                "returned": len(chunk), "total": len(rows), "has_more": page * size < len(rows)}


# ---------------------------------------------------------------- 상자(박스) — 앱이 내보내는 HTTP 는 전부 가짜 게이트웨이로 간다(소켓 0)
@dataclass
class Box:
    store: object
    gw: FakeGateway
    ident: identity.Identity


@pytest.fixture
def box(risk_store, monkeypatch) -> Box:
    """dev 게이트웨이에는 odb-hub 가 없다 — httpx 전송 한 곳에서 앱의 모든 HTTP 를 가짜로 받는다. 비동기 전송은 막는다.

    MCP 자격은 박스 secrets.env 의 앱 PAT 자리(HWAXRISK_PORTAL_PAT)에 둔다 — odb-hub 는 서비스 토큰 하나로 붙은 백엔드다.
    """
    gw = FakeGateway(map=gateway_map())
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: gw.handle(request))

    def _no_async(*_args, **_kwargs):
        raise AssertionError("이 시험의 경로는 비동기 HTTP 를 쓰지 않는다")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _no_async)
    monkeypatch.setattr(config, "load_secrets", lambda *_a, **_k: {"HWAXRISK_PORTAL_PAT": APP_PAT})
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    ident = identity.Identity(email=OWNER, display_name="ECAD BB", role="user", organization="qa", anonymous=False,
                              source="bearer")
    return Box(store=risk_store, gw=gw, ident=ident)


@dataclass
class Captured:
    project_id: str
    added: dict
    out: dict
    ir: dict
    calls: list


def _new_project(box: Box, code: str) -> str:
    project = routes.create_project(routes.ProjectBody(code=code, name="ECAD 1단계 블랙박스", stage="DV1",
                                                       classification="internal"), ident=box.ident)
    return project["id"]


def _attach(box: Box, project_id: str, ref: dict) -> dict:
    """웹 소스 카드처럼 붙인다 — app_key 는 /meta/adapters(발견)의 ecad 행 값을 그대로 보낸다."""
    ecad = next(r for r in adapters_registry.discover_adapters(force=True) if r["kind"] == "ecad")
    return routes.add_source(project_id, routes.SourceBody(kind="ecad", app_key=ecad["app_key"], ref=ref),
                             ident=box.ident)


def _capture(box: Box, ref: dict, *, code: str = "ECAD-BB-1") -> Captured:
    """과제 → ecad 소스 카드 → 캡처(POST /api/projects/{id}/snapshots) → 동결된 rr_ir.

    `calls` 는 캡처 한 번이 부른 도구다(ER-03 의 '보드 1장에 …'). 붙일 때 부른 것은 box.gw.calls 에 함께 남는다.
    """
    project_id = _new_project(box, code)
    added = _attach(box, project_id, ref)
    mark = len(box.gw.calls)
    out = routes.create_snapshot(project_id, routes.SnapshotBody(label="DV1"), ident=box.ident)
    return Captured(project_id, added, out, ir_builder.load_ir(box.store, out["snapshot_id"]),
                    list(box.gw.calls[mark:]))


def _ecad_source(ir: dict) -> dict:
    return next(s for s in ir["sources"] if s["kind"] == "ecad")


def _recipe(calls: list[Call]) -> collections.Counter:
    return collections.Counter(c.name for c in calls)


def _assert_recipe(calls: list[Call], board: Board, *, pages: int, names: dict[str, str] | None = None) -> None:
    """ER-03 — 보드 1장에 find_job 1 · get_board_layers 1 · check_job_stackup 1 · get_volume_result 1 · get_odb_download 1 ·
    odbhub_list_parts 100행씩. 표준 적층 자재를 get_stackup 으로 읽는 것(부록 A material 행의 '또는')만 한 번 더 허락한다."""
    names = {"find_job": "find_job", "get_board_layers": "get_board_layers", "check_job_stackup": "check_job_stackup",
             "get_volume_result": "get_volume_result", "get_odb_download": "get_odb_download",
             "list_parts": "odbhub_list_parts", **(names or {})}
    want = collections.Counter({names[t]: (pages if t == "list_parts" else 1) for t in STAGE1_TOOLS})
    got = _recipe(calls)
    assert {k: got[k] for k in want} == dict(want), f"ER-03 호출 처방과 다르다 — {dict(got)}"
    extra = got - want
    assert set(extra) <= {"get_stackup"} and extra.get("get_stackup", 0) <= 1, f"처방 밖 호출 — {dict(extra)}"
    foreign = [c for c in calls if c.backend != ODB]
    assert foreign == [], f"odb-hub 가 아닌 백엔드의 도구를 불렀다 — {[(c.name, c.backend) for c in foreign]}"
    assert not {c.tool for c in calls} & FORBIDDEN_IN_STAGE1
    for c in calls:
        if c.tool == "find_job":
            assert c.args.get("query") == board.job_id, c      # 부록 A name 행 — find_job(query=<job_id>)
        elif c.tool != "get_stackup":
            assert c.args.get("job_id") == board.job_id, c
    listed = [c.args for c in calls if c.tool == "list_parts"]
    assert sorted(int(a.get("page") or 1) for a in listed) == list(range(1, pages + 1)), listed
    # 분류 안 된 부품을 범주로 거르면 오류다(OH-02) — 1단계는 분류된 부품을 양면 다(side 비움) 읽는다.
    assert all(str(a.get("category") or "") != "Unknown" and not a.get("side") for a in listed), listed


def _ecad_schema_errors(ir: dict) -> list[str]:
    """ecad 노드 · 소스가 rr_ir.v1.json 정의(노드 kind · degraded 어휘 · layer type · side)를 지키나.

    봉투 전체는 보지 않는다 — mcad 없는 스냅샷은 gates.G1 ~ G3.pass 가 null 이라 그 칸의 스키마(boolean)와 이미 어긋난다(ECAD 와
    무관한 기존 사정이고 dyna 단독 스냅샷도 같다).
    """
    schema = json.loads((Path(ir_builder.__file__).parent / "schemas" / "rr_ir.v1.json").read_text(encoding="utf-8"))
    node = Draft7Validator({"$ref": "#/definitions/node", "definitions": schema["definitions"]})
    source = Draft7Validator({"$ref": "#/definitions/source", "definitions": schema["definitions"]})
    errors = [f"{n['kind']} {n['canon_key']}: {e.message}"
              for n in ir["nodes"] if n["domain"] == "ecad" for e in node.iter_errors(n)]
    errors += [f"source: {e.message}" for e in source.iter_errors(_ecad_source(ir))]
    return sorted(errors)[:10]


def _carries(obj, wanted) -> bool:
    """attrs 어딘가(중첩 포함)에 그 값이 실려 있나 — 문자열은 같음, 수는 1e-6 안."""
    if isinstance(obj, dict):
        return any(_carries(v, wanted) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(_carries(v, wanted) for v in obj)
    if isinstance(wanted, float) and isinstance(obj, (int, float)) and not isinstance(obj, bool):
        return abs(float(obj) - wanted) < 1e-6
    return obj == wanted


# ================================================================ 가짜가 요청서 실측 수를 그대로 냈나(이 시험은 main 에서도 통과한다)
def test_the_fake_reproduces_the_measured_board_numbers():
    """부록 A · B 의 수 — 보드 1 은 층 35 · 동박 10 · 5종 23행 · 목록 748 · 배치 924(8쪽), 보드 2 는 5종 19행 · 528 · 702."""
    assert (len(B1.layers), len(B1.copper), len(B1.five)) == (35, 10, 23)
    assert (len(B1.parts), B1.placed("top") + B1.placed("bottom"), -(-len(B1.parts) // LIST_PARTS_PAGE_CAP)) == (748, 924, 8)
    assert (len(B2.five), len(B2.parts), B2.placed("top") + B2.placed("bottom")) == (19, 528, 702)
    # 5종 행 두께 합 = total_thickness_mm × 1000(부록 A ecad_stackup_total 행 — 두 보드 모두 같았다).
    assert B1.total_um == pytest.approx(B1.stackup["thickness_mm"] * 1000) == pytest.approx(800.0)
    assert B2.total_um == pytest.approx(B2.stackup["thickness_mm"] * 1000) == pytest.approx(630.0)
    assert all(b.job_id == b.sha256[:16] and re.fullmatch(r"[0-9a-f]{16}", b.job_id) for b in BOARDS)
    gw = FakeGateway(map=gateway_map())
    assert gw._find_job(MODEL_A)["truncated"] is False and len(gw._find_job(MODEL_A)["jobs"]) == 3
    assert gw._find_job("PRJ-GAMMA")["truncated"] is True and len(gw._find_job("PRJ-GAMMA")["jobs"]) == FIND_JOB_CAP
    assert gw._list_parts(B1, {"job_id": B1.job_id, "page_size": 5000})["page_size"] == LIST_PARTS_PAGE_CAP
    assert "error" in gw._list_parts(B1, {"job_id": B1.job_id, "category": "Unknown"})
    assert {"odbhub_list_parts", "odbhub_list_jobs", "find_job", "list_parts", "list_jobs"} <= set(gateway_map())


# ================================================================ ER-02 — 발견은 /tools-map 의 백엔드 odb-hub 와 원래 이름으로
@pytest.mark.parametrize("variant", ["request", "both"])
def test_discovery_binds_ecad_by_backend_and_original_name(box, variant):
    """1단계 도구 여섯이 백엔드 odb-hub 에 다 있으면 ecad 는 contract_only 가 아니라 실제 상태(ready)다 — list_parts 는
    게이트웨이 이름 odbhub_list_parts 로 보인다. 같은 이름을 내는 StepForge 의 mcad 발견은 그대로 산다."""
    box.gw.map = gateway_map(variant)
    rows = {r["kind"]: r for r in adapters_registry.discover_adapters(force=True)}
    ecad = rows["ecad"]
    assert (ecad["status"], ecad["tools_ok"], ecad["tools_missing"]) == ("ready", True, []), ecad
    assert ecad["app_key"] == ODB, ecad
    assert (rows["mcad"]["status"], rows["mcad"]["app_key"]) == ("ready", SF), rows["mcad"]


@pytest.mark.parametrize("case", ["download_only_on_another_backend", "contract_names_only"])
def test_ecad_is_not_bound_to_other_backends_or_to_the_contract_names(box, case):
    """ecad 를 이름 집합으로 찾지 않는다 — odb-hub 에 없는 도구를 남의 백엔드가 같은 이름으로 내도, 계약 4이름이 어딘가에 있어도
    ecad 는 준비되지 않았다. 빠진 것은 원래 이름으로 적히고, 캡처도 남의 백엔드 도구를 부르지 않는다."""
    if case == "download_only_on_another_backend":
        box.gw.map = gateway_map(odb_missing=("get_odb_download",), others={"get_odb_download": OTHER})
    else:
        box.gw.map = {**gateway_map(odb_missing=ODB_TOOLS), **{name: "heax-legacy_odb" for name in CONTRACT_TOOLS}}
    ecad = next(r for r in adapters_registry.discover_adapters(force=True) if r["kind"] == "ecad")
    assert ecad["status"] != "ready" and ecad["tools_ok"] is False, ecad
    missing = set(ecad["tools_missing"])
    if case == "download_only_on_another_backend":
        assert "get_odb_download" in missing, ecad
    else:
        # StepForge 의 list_parts 를 odb-hub 의 것으로 셈하지 않는다.
        assert {"find_job", "get_board_layers", "check_job_stackup", "get_volume_result", "get_odb_download"} <= missing
        assert missing & {"list_parts", "odbhub_list_parts"}, ecad
    try:
        _capture(box, _ecad_ref(B1.job_id))
    except AppError:
        pass        # ecad 가 준비되지 않았다고 캡처를 거절해도 된다 — 요지는 남의 도구를 부르지 않는 것이다.
    foreign = [(c.name, c.backend) for c in box.gw.calls if c.backend != ODB]
    assert foreign == [], foreign


def test_attaching_a_board_makes_a_linked_ecad_card(box):
    """ER-01 · ER-02 — odb-hub 도구가 다 보이는 게이트웨이에서 ecad 소스 카드(job_id)를 붙이면 카드가 '연결됨' 이다."""
    project_id = _new_project(box, "ECAD-CARD")
    added = _attach(box, project_id, _ecad_ref(B1.job_id))
    assert added["ok"] is True and added["probe"]["reachable"] is True, added
    assert added["probe"]["status"] == "linked", added
    card = next(s for s in routes._project_sources(project_id) if s["kind"] == "ecad")
    assert card["ref"] == _ecad_ref(B1.job_id) and card["status"] == "linked", card


# ================================================================ 6절 1단계 캡처 — 통과 기준
def test_stage1_capture_loads_one_board_its_layers_and_classified_components(box):
    """ECAD 보드를 붙인 과제를 캡처하면 missing.ecad_absent 가 없고, component 노드 수는 odbhub_list_parts 의 total,
    layer 노드 수는 get_board_layers 를 5종으로 거른 행 수다. 넷 노드와 component→net 엣지는 2단계라 없다."""
    cap = _capture(box, _ecad_ref(B1.job_id))
    ir = cap.ir
    assert ir["missing"]["ecad_absent"] is False and ir["missing"]["ecad_capture_failed"] is False, ir["missing"]
    assert "ecad_absent" not in _ecad_source(ir)["degraded"] and "ecad_absent" not in cap.out["degraded"]
    assert len(_nodes(ir, "board")) == 1
    assert len(_nodes(ir, "layer")) == len(B1.five) == 23
    assert len(_nodes(ir, "component")) == len(B1.parts) == 748
    assert _nodes(ir, "net") == [] and [e for e in ir["edges"] if e["kind"] == "net"] == []
    assert ir["ir_version"] == "1.1"
    # 동결된 봉투가 자기 계약(rr_ir.v1.json — 노드 kind · degraded 어휘)을 지킨다.
    assert _ecad_schema_errors(ir) == []
    # 캡처가 그 보드를 실제로 읽었으니 카드는 연결됨이고 캡처 성공이 적힌다.
    card = next(s for s in routes._project_sources(cap.project_id) if s["kind"] == "ecad")
    assert card["status"] == "linked" and str(card["probe"].get("detail") or "").startswith("capture_ok"), card


@pytest.mark.parametrize("variant", ["request", "both"])
def test_stage1_reads_one_board_with_the_er03_recipe_under_gateway_names(box, variant):
    """보드 1 은 find_job 1 · get_board_layers 1 · check_job_stackup 1 · get_volume_result 1 · get_odb_download 1 ·
    odbhub_list_parts 8쪽이다(서버가 page_size 를 100 으로 줄인다). 원장의 도구 이름도 게이트웨이 실이름이다."""
    box.gw.map = gateway_map(variant)
    cap = _capture(box, _ecad_ref(B1.job_id))
    _assert_recipe(cap.calls, B1, pages=8)
    logged = collections.Counter(c["tool"] for c in ir_builder.load_calls(box.store, cap.out["snapshot_id"],
                                                                          include_response=False)
                                 if c["source_kind"] == "ecad")
    assert logged == _recipe(cap.calls), logged
    assert "list_parts" not in logged and all(c["ok"] for c in ir_builder.load_calls(
        box.store, cap.out["snapshot_id"], include_response=False) if c["source_kind"] == "ecad")


# ================================================================ 부록 A — 칸마다 옮기기 · 유도
def test_board_node_carries_the_appendix_a_board_fields(box):
    """board — 이름은 project · model · board_type · revision 으로 엮고(job_name · step_name 은 쓰지 않는다), 두께는
    total_thickness_mm 와 verdict, 층수는 동박층 수(layer_count 35 아님), 해시는 get_odb_download.sha256 이다. 넷 수 · 형식 판 ·
    외곽 원점은 지어내지 않는다."""
    cap = _capture(box, _ecad_ref(B1.job_id))
    board = _board(cap.ir)
    attrs = board["attrs"]
    name = str(attrs.get("name") or board["label"])
    assert all(part in name for part in (PROJECT_A, MODEL_A, "Main", "0.7")), name
    assert "designodb" not in name.lower() and "pcb" not in name.lower(), name
    ref = _ecad_source(cap.ir)["ref"]
    assert B1.job_id in {attrs.get("board_id"), attrs.get("job_id"), ref.get("board_id"), ref.get("job_id")}, (attrs, ref)
    assert _ecad_source(cap.ir)["source_hash"] == B1.sha256
    assert attrs.get("thickness") == pytest.approx(0.8) and _carries(attrs, "standard"), attrs
    assert attrs.get("layer_count") == 10, attrs
    assert attrs.get("n_components") in (len(B1.parts), B1.placed("top") + B1.placed("bottom")), attrs
    assert attrs.get("n_nets") is None and attrs.get("odb_version") is None, attrs
    bbox = attrs.get("outline_bbox")
    assert bbox is None or all(v is None for v in list(bbox)[:2]), f"외곽 원점을 지어냈다 — {bbox}"
    assert _carries(attrs, 107.18) and _carries(attrs, 72.97), "외곽 폭 · 높이(get_volume_result.board)가 없다"
    assert attrs.get("units", "mm") == "mm", attrs


def test_layer_nodes_follow_physical_order_the_five_types_and_the_standard_stackup(box):
    """layer — 5종으로 거른 뒤 물리 순서로 번호를 매기고, 타입은 5종 어휘로, 두께는 thickness_um(µm, 실크 null) 그대로,
    자재는 표준 적층과 맞을 때 check_job_stackup 에서 온다. 동박 무게는 없다."""
    cap = _capture(box, _ecad_ref(B1.job_id))
    layers = sorted(_nodes(cap.ir, "layer"), key=lambda n: n["attrs"]["idx"])
    assert len(layers) == len(B1.five), f"layer 노드 {len(layers)}건 — 5종 행은 {len(B1.five)}건"
    idx = [n["attrs"]["idx"] for n in layers]
    assert idx[0] in (0, 1) and idx == list(range(idx[0], idx[0] + len(B1.five))), idx
    assert [n["attrs"]["name"] for n in layers] == [r["name"] for r in B1.five]
    assert [n["attrs"]["type"] for n in layers] == [FIVE[r["type"]] for r in B1.five]
    assert [n["attrs"]["thickness"] for n in layers] == [r["thickness_um"] for r in B1.five]
    assert [n["attrs"].get("material") for n in layers] == B1.materials()
    assert all(n["attrs"].get("copper_weight") is None for n in layers)


def test_component_nodes_carry_list_parts_fields_without_coordinates_or_nets(box):
    """component — refdes · part_number(part_name) · footprint(pkg_name) · side · pin_count 는 그대로, 좌표 · 회전 · 넷 · 값은
    1단계에 없고, 높이는 면마다 큰 부품 10개(get_volume_result.largest_items)만 있다."""
    cap = _capture(box, _ecad_ref(B1.job_id))
    comps = {n["attrs"]["refdes"]: n["attrs"] for n in _nodes(cap.ir, "component")}
    assert set(comps) == {p["refdes"] for p in B1.parts}
    wrong = [p["refdes"] for p in B1.parts
             if (comps[p["refdes"]].get("part_number"), comps[p["refdes"]].get("footprint"),
                 comps[p["refdes"]].get("side"), comps[p["refdes"]].get("pin_count"))
             != (p["part_name"], p["pkg_name"], p["side"], p["pin_count"])]
    assert wrong == [], wrong[:5]
    made_up = [r for r, a in comps.items()
               if any(a.get(k) is not None for k in ("x", "y", "rot", "value")) or a.get("nets") not in (None, [])]
    assert made_up == [], made_up[:5]
    heights = B1.heights()
    assert {r: comps[r].get("height") for r in heights} == heights
    assert [r for r, a in comps.items() if r not in heights and a.get("height") is not None] == []


def test_stage1_leaves_the_er04_markers_and_fabricates_nothing(box):
    """ER-04 — 지금 도구로 못 채우는 칸은 표지로 남는다. 보드를 실었으니 부재가 아니고, 허브가 mm 로 주니 mil 환산이 없고,
    적층이 표준이니 자재 불일치도 없다. 캡처 응답의 degraded 에도 같은 표지가 실린다."""
    cap = _capture(box, _ecad_ref(B1.job_id))
    degraded = set(_ecad_source(cap.ir)["degraded"])
    assert STAGE1_MARKERS - degraded == set(), sorted(STAGE1_MARKERS - degraded)
    assert degraded & (NEVER_IN_STAGE1 | {"stackup_material_unmatched"}) == set(), sorted(degraded)
    assert STAGE1_MARKERS <= set(cap.out["degraded"]), cap.out["degraded"]


def test_a_non_standard_stackup_has_no_material_and_says_so(box):
    """보드 2(non_standard) — 5종 19행 · 분류된 부품 528(6쪽), 자재는 비고 stackup_material_unmatched 가 선다. 두께에는
    non_standard verdict 가 함께 실린다."""
    cap = _capture(box, _ecad_ref(B2.job_id))
    _assert_recipe(cap.calls, B2, pages=6)
    layers = sorted(_nodes(cap.ir, "layer"), key=lambda n: n["attrs"]["idx"])
    assert len(layers) == 19 and len(_nodes(cap.ir, "component")) == 528
    assert [n["attrs"].get("material") for n in layers] == [None] * 19
    degraded = set(_ecad_source(cap.ir)["degraded"])
    assert (STAGE1_MARKERS | {"stackup_material_unmatched"}) <= degraded, sorted(degraded)
    assert not degraded & NEVER_IN_STAGE1, sorted(degraded)
    attrs = _board(cap.ir)["attrs"]
    assert attrs.get("thickness") == pytest.approx(0.63) and _carries(attrs, "non_standard"), attrs
    assert attrs.get("layer_count") == 8, attrs
    assert _ecad_schema_errors(cap.ir) == []


@pytest.mark.parametrize("board", [B1, B2], ids=["board1", "board2"])
def test_ecad_stackup_total_is_the_sum_of_the_five_type_rows(box, board):
    """ecad_stackup_total — 5종 행 두께 합 = total_thickness_mm × 1000(µm)이다(부록 A)."""
    cap = _capture(box, _ecad_ref(board.job_id))
    assert _stackup_total_um(cap.ir) == pytest.approx(board.total_um)


def test_power_ground_copper_maps_to_plane(box):
    """type — POWER_GROUND 는 plane 이다(부록 A type 행). 층 타입에서 읽고 층 이름에서 읽지 않는다."""
    cap = _capture(box, _ecad_ref(B3.job_id))
    types = {n["attrs"]["name"]: n["attrs"]["type"] for n in _nodes(cap.ir, "layer")}
    assert len(types) == len(B3.five) == 19
    assert (types["plane_2"], types["plane_7"], types["signal_1"], types["dielectric_1"]) == (
        "plane", "plane", "signal", "dielectric")


# ================================================================ ER-02 — 게이트웨이 이름은 바뀐다
@pytest.mark.parametrize("variant", ["request", "both"])
def test_capture_follows_new_gateway_prefixes(box, variant):
    """다른 앱이 find_job · get_board_layers 를 들여 odb-hub 쪽이 odbhub_find_job · odbhub_get_board_layers 로 바뀐 날에도
    캡처는 odb-hub 의 도구만 부르고 같은 보드를 싣는다."""
    box.gw.map = gateway_map(variant, others={"find_job": OTHER, "get_board_layers": OTHER})
    cap = _capture(box, _ecad_ref(B1.job_id))
    _assert_recipe(cap.calls, B1, pages=8,
                   names={"find_job": "odbhub_find_job", "get_board_layers": "odbhub_get_board_layers"})
    assert (len(_nodes(cap.ir, "layer")), len(_nodes(cap.ir, "component"))) == (23, 748)
    assert MODEL_A in str(_board(cap.ir)["attrs"].get("name") or _board(cap.ir)["label"])


# ================================================================ ER-01 — 보드는 사람이 고른다
@pytest.mark.parametrize("model", [MODEL_A, MODEL_B], ids=["three_candidates", "single_match"])
def test_no_board_is_picked_by_model_name_and_the_chosen_revision_is_loaded(box, model):
    """job_id 없이 이름만 든 ecad 카드는 어떤 보드도 싣지 않는다(후보가 하나뿐이어도). 사람이 후보에서 고른 job_id 를 붙이면
    바로 그 판이 실린다 — 같은 모델의 첫 후보(0.7)가 아니라 고른 0.8 이다."""
    project_id = _new_project(box, f"ECAD-NAME-{model}")
    ir = None
    try:
        _attach(box, project_id, {"model": model, "project": PROJECT_A if model == MODEL_A else PROJECT_B})
        out = routes.create_snapshot(project_id, routes.SnapshotBody(label="DV1"), ident=box.ident)
        ir = ir_builder.load_ir(box.store, out["snapshot_id"])
    except AppError:
        pass        # job_id 가 없다고 붙이기나 캡처를 거절해도 된다.
    per_board = [(c.name, c.args) for c in box.gw.calls if c.backend == ODB and c.tool != "find_job"]
    assert per_board == [], per_board[:3]
    if ir is not None:
        assert [n for n in ir["nodes"] if n["domain"] == "ecad"] == []
        assert ir["missing"]["ecad_absent"] is True, ir["missing"]

    cap = _capture(box, _ecad_ref(B1R8.job_id), code="ECAD-PICKED")
    _assert_recipe(cap.calls, B1R8, pages=9)
    assert len(_nodes(cap.ir, "component")) == len(B1R8.parts) == 812
    assert "0.8" in str(_board(cap.ir)["attrs"].get("name") or _board(cap.ir)["label"])
    assert _ecad_source(cap.ir)["source_hash"] == B1R8.sha256


def test_board_search_shows_every_find_job_candidate_for_a_human_to_pick(box, client):
    """ER-01 — 고를 때는 find_job 결과를 사람에게 보인다. 같은 모델의 다른 판(0.7 · 0.8)과 다른 보드 역할(Sub)이 다 후보로
    나오고 고를 칸(과제 · 모델 · 보드 역할 · 판)이 있다. find_job 이 10개에서 자르면 truncated 가 그대로 온다."""
    project_id = _new_project(box, "ECAD-SEARCH")
    box.gw.calls.clear()
    body = _board_search(client, box.ident, project_id, MODEL_A)
    rows = _candidates(body)
    assert {r["job_id"] for r in rows} == {B1.meta["job_id"], B1R8.meta["job_id"], SUB1["job_id"]}, rows
    for row in rows:
        source = next(j for j in JOBS if j["job_id"] == row["job_id"])
        assert {k: row.get(k) for k in ("project", "model", "board_type", "revision")} == {
            k: source[k] for k in ("project", "model", "board_type", "revision")}, row
    assert not (isinstance(body, dict) and body.get("truncated")), body
    assert [(c.name, c.args.get("query")) for c in box.gw.calls] == [("find_job", MODEL_A)]
    # 고르기 전에는 보드를 읽지 않는다.
    assert not [c for c in box.gw.calls if c.tool != "find_job"]

    wide = _board_search(client, box.ident, project_id, "PRJ-GAMMA")
    assert len(_candidates(wide)) == FIND_JOB_CAP and isinstance(wide, dict) and wide.get("truncated") is True, wide


# ================================================================ ER-05 — 계약 문서가 지금 도구 · 발견 방식 · 두 단계를 말한다
def test_the_contract_doc_names_the_current_tools_discovery_and_two_stages():
    """앱 리포의 docs/odb-adapter-contract.md — '게이트웨이 백엔드가 없다' · '어댑터 코드는 없다' 는 이제 사실이 아니다.
    1단계 도구 이름 · /tools-map 의 백엔드 odb-hub 로 찾는 발견 · 두 단계 · ER-04 표지를 적는다."""
    text = (REPO_ROOT / "docs" / "odb-adapter-contract.md").read_text(encoding="utf-8")
    assert "게이트웨이 백엔드가 없다" not in text and "어댑터 코드는 없다" not in text
    for name in ("find_job", "get_board_layers", "check_job_stackup", "get_volume_result", "get_odb_download",
                 "odbhub_list_parts", "/tools-map", "odb-hub", "1단계", "2단계"):
        assert name in text, name
    assert [m for m in sorted(ER04_MARKERS) if m not in text] == []
