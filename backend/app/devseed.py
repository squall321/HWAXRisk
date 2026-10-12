# 합성 설계와 변경 연산 — 어댑터 결과 수준의 합성 쌍을 만들고 그 뒤(IR·대응·diff)는 실제 생산자가 만든다(시험·dev 주입 공용)
"""리스크 심사 재설계의 합성 다건 변경 생성기 한 벌이다(WP5b C3 = WP1 S0 = WP2 걸음 1 — 셋이 따로 만들지 않는다).

- 수준은 어댑터 결과(`{source, nodes, edges, warnings, degraded, call_ids}`)다. IR·diff_json 을 손으로 쓰지 않는다 —
  `ir_builder.freeze_snapshot` → `state` → `sameas` → `diff.create_diff` 가 그 뒤를 전부 만든다.
- 연산 하나는 의미 이벤트 코드 하나를 겨냥한다. '이 연산은 이 코드를 낸다' 를 `ChangeRecord.expect_codes` 에 적는다.
  연산이 끌고 오는 코드(지운 부품의 계면 → `iface.removed`, mcad 치수만 바뀐 묶음 → `cross.bridge_stale`)도 그 연산에
  적고, 조립 단위의 엣지 수 변화(`asm.rollup_changed`)는 설계 모형에서 따로 세어 파생 기록으로 붙인다.
  기대는 대본과 설계 모형에서 나온다 — 생산자 출력을 받아 적지 않는다.
- 연산은 제가 건드리는 부품을 독점한다(`Design.claimed`). 그래서 기대 코드가 연산끼리 그대로 더해진다.
  알맞은 부품이 배경 설계에 없으면 그 연산이 base 에 부품·계면·접촉을 먼저 만든다(준비 단계).
- 크기는 대본의 연산 수다. 의미 이벤트 수는 `sum(len(r.expect_codes))` 이고 크기와 다르다(반대 검토 P-04).
- 운영 경로는 이 모듈을 import 하지 않는다(시험이 AST 로 본다).
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from app import ir_builder
from app.adapters import mcad as mcad_adapter

ADAPTER_VERSION = "1.0"
FILE_STEM = "syn_phone"
FILE = f"{FILE_STEM}.step"
CAPTURED_AT = 1756600000

# 배경 부품의 역할 낱말 — 동의어 머리(board·cover·panel·shield·case …)와 치수 토큰(t1·1t·1mm)을 피한다. 정규명이 소문자 그대로다.
ROLES = ("BRACKET", "PLATE", "FRAME", "HOLDER", "SPACER", "GASKET", "CLIP", "BOSS", "RIB", "DAMPER", "SPRING",
         "LATCH", "DECO", "SUPPORT", "SLEEVE", "GUIDE")
# 연산이 새로 만드는 부품의 역할·음절 — 배경 부품과 이름이 닮지 않게 따로 둔다(닮으면 대응이 pending 으로 서 G2 가 막는다).
OP_ROLES = ("STIFFENER", "INSERT", "WEDGE", "TAB", "PIN", "STRAP")
# 쪼개기·합치기의 부품은 연산마다 다른 역할 낱말을 쓴다 — 두 연산의 짝 없는 부품끼리 이름이 닮으면(같은 역할 + 비슷한 음절)
# 대응 점수가 0.7 을 넘어 pending 이 서고 G2 가 의미 이벤트를 통째로 막는다(무작위 대본 씨앗 27 에서 0.708 을 실측했다).
STRUCT_ROLES = ("ANCHOR", "BEZEL", "COLLAR", "DOWEL", "EYELET", "FERRULE", "GROMMET", "HUB", "JACKET", "KNOB", "LUG",
                "MOUNT", "NUT", "PAWL", "QUILL", "RIVET", "SHROUD", "TOGGLE", "VANE", "WASHER", "ZIPPER", "ARBOR",
                "BUSHING", "CAM", "DETENT", "FLANGE", "GIMBAL", "HASP", "IDLER", "JIG")
_BG_SYLLABLES = ("DA", "LO", "MI", "NU", "PE", "RA", "SO", "TI", "VU", "ZE")
_OP_SYLLABLES = ("BYX", "QOH", "JUW", "FYD", "WEQ", "HIZ", "GOJ", "DUV")
MATERIALS = ("AL6061", "SUS304", "PC", "PA66GF", "MGAZ91", "CUC1100", "TIGR5", "ABS")
# 이름에 판단어가 든 부품(브리프 판단어 린터의 L16 OK·PASS, L13 강화). 배경 설계 앞자리에 둔다.
HAZARD_NAMES = ("HOOK_LATCH", "PASSIVE_PAD", "강화유리 WINDOW")
DEFAULT_ASMS = ("DISPLAY_ASM", "REAR_ASM", "FRAME_ASM", "MAIN_PBA_ASM", "BATTERY_ASM", "CAMERA_ASM", "ANT_ASM",
                "SPK_ASM")


@dataclass(frozen=True)
class SynthSpec:
    seed: int = 20261009
    n_parts: int = 60                 # 배경 mcad 리프 수(연산이 부품을 더 만들 수 있다)
    asms: tuple[str, ...] = DEFAULT_ASMS
    asm_parts: tuple[int, ...] | None = None   # 조립 단위마다 배경 부품 수(없으면 고르게 나눈다)
    iface_per_part: float = 1.2       # 배경 계면 밀도
    boundary_ratio: float = 0.2       # 서로 다른 1단 조립 단위를 잇는 배경 계면의 비율
    twin_ratio: float = 0.35          # dyna pid 짝이 있는 배경 부품의 비율
    with_dyna: bool = True
    with_result: bool = True
    named_dims: int = 2               # 배경 명명 치수(바뀌지 않는 부품에 묶는다)
    hazards: bool = True


@dataclass(frozen=True)
class ChangeRecord:
    op: str                           # 연산 이름(= 겨냥한 코드, 또는 이벤트 없는 변화의 이름)
    expect_codes: tuple[str, ...]     # 이 연산이 내야 하는 의미 이벤트 코드(파생 포함)
    subjects: tuple[str, ...]         # 부품 이름 · 'dim:<이름>' · 'asm:<조립 단위>' · 'contact#<번호>'
    sign: int                         # +1 · -1 · 0
    unit: str | None                  # mm · rank · MPa · G · mm2 · None
    flags: frozenset[str] = frozenset()   # decrease · no_ckey · boundary · design_irrelevant · unconfirmed · lower_bound · derived · hazard · excluded:<사유>


@dataclass
class Part:
    name: str
    asm: str
    origin: list[float]               # bbox_def 최소 꼭짓점(정의 좌표 = 조립 좌표)
    size: list[float]                 # x · y · z(z 가 얇은 축)
    material: str
    shift: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])   # 조립 좌표 이동
    rotated: bool = False             # 조립 좌표에서 z 축 90° 회전(bbox_world 의 x·y 길이가 바뀐다)
    min_dim_known: bool = True
    pid: int | None = None            # dyna 짝
    n_elems: int | None = None
    result: dict | None = None        # worst_stress · worst_g · worst_disp · min_safety_factor
    dyna_box: list[float] | None = None   # dyna pid 의 bbox(최소·최대 꼭짓점) — 없으면 mcad bbox_world 를 따른다
    dyna_volume: float | None = None


@dataclass
class Iface:
    kind: str                         # tied · touching · clearance · interference
    status: str = "confirmed"
    min_gap: float | None = 0.0
    area: float | None = None
    penetration: float | None = None
    penetration_volume: float | None = None    # 부울 경로가 낸 관통 부피 — 없으면 깊이는 하한값이다(어댑터와 같다)


@dataclass
class Contact:
    kind: str                         # contact · scope
    pids: list[int]                   # contact 은 둘, scope 는 구성원
    contact_type: str = "*CONTACT_TIED_SURFACE_TO_SURFACE"
    fs: float | None = None
    title: str = ""


@dataclass
class Design:
    spec: SynthSpec
    sha: str
    parts: dict[str, Part] = field(default_factory=dict)
    ifaces: dict[tuple[str, str], Iface] = field(default_factory=dict)
    contacts: dict[int, Contact] = field(default_factory=dict)
    dims: dict[str, str] = field(default_factory=dict)        # 명명 치수 이름 → 묶인 부품
    claimed: set[str] = field(default_factory=set)
    serial: int = 0                                           # 새 이름 일련번호
    struct_n: int = 0                                         # 쪼개기·합치기 부품의 역할 낱말 차례
    next_pid: int = 1
    next_contact: int = 1

    def asm_of(self, name: str) -> str:
        return self.parts[name].asm


# ---------------------------------------------------------------- 배경 설계
def _code(n: int, syllables: Sequence[str], width: int = 3) -> str:
    out = []
    for _ in range(width):
        out.append(syllables[n % len(syllables)])
        n //= len(syllables)
    return "".join(out)


def _new_name(d: Design, role: str, *, op: bool) -> str:
    while True:
        d.serial += 1
        name = f"{role}_{_code(d.serial, _OP_SYLLABLES if op else _BG_SYLLABLES)}"
        if name not in d.parts:
            return name


def _size(rng: random.Random) -> list[float]:
    return [round(rng.uniform(8.0, 40.0), 2), round(rng.uniform(5.0, 30.0), 2), round(rng.uniform(0.4, 2.0), 2)]


def _place(d: Design, asm: str) -> list[float]:
    """조립 단위마다 띠를 하나 쓰고 그 안에 격자로 놓는다 — 겹치지 않게만 한다."""
    index = list(d.spec.asms).index(asm) if asm in d.spec.asms else len(d.spec.asms)
    j = sum(1 for p in d.parts.values() if p.asm == asm)
    return [float(index * 260 + (j % 5) * 50), float((j // 5) * 40), 0.0]


def _add_part(d: Design, rng: random.Random, asm: str, *, name: str | None = None, twin: bool = False,
              op: bool = False, size: list[float] | None = None, material: str | None = None) -> Part:
    part = Part(name=name or _new_name(d, rng.choice(OP_ROLES if op else ROLES), op=op), asm=asm,
                origin=_place(d, asm), size=list(size or _size(rng)), material=material or rng.choice(MATERIALS))
    if twin:
        _make_twin(d, rng, part)
    d.parts[part.name] = part
    return part


def _make_twin(d: Design, rng: random.Random, part: Part) -> None:
    part.pid = d.next_pid
    d.next_pid += 1
    part.n_elems = int(part.size[0] * part.size[1] * part.size[2] * 2) + 100
    part.result = {"worst_stress": round(rng.uniform(80.0, 300.0), 1), "worst_g": round(rng.uniform(30.0, 200.0), 1),
                   "worst_disp": round(rng.uniform(0.1, 1.5), 3), "min_safety_factor": round(rng.uniform(1.0, 3.0), 2)}


def _iface(rng: random.Random, kind: str) -> Iface:
    if kind in ("tied", "touching"):
        return Iface(kind=kind, min_gap=0.0, area=round(rng.uniform(40.0, 200.0), 1))
    if kind == "clearance":
        return Iface(kind=kind, min_gap=round(rng.uniform(0.25, 0.6), 3), area=None)
    return Iface(kind="interference", min_gap=0.0, area=None, penetration=0.05)


def _key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def build_design(spec: SynthSpec) -> Design:
    """배경 설계 — 부품·계면·접촉·결과·명명 치수. 아무 연산도 이 부품들을 아직 독점하지 않는다(명명 치수에 묶인 것만 예약)."""
    rng = random.Random(spec.seed)
    sha = hashlib.sha256(f"syn-k-{spec.seed}".encode()).hexdigest()
    d = Design(spec=spec, sha=sha)
    counts = list(spec.asm_parts) if spec.asm_parts else [
        spec.n_parts // len(spec.asms) + (1 if i < spec.n_parts % len(spec.asms) else 0) for i in range(len(spec.asms))]
    hazards = list(HAZARD_NAMES) if spec.hazards else []
    for asm, count in zip(spec.asms, counts):
        for _ in range(count):
            name = hazards.pop(0) if hazards else None
            twin = spec.with_dyna and name is None and rng.random() < spec.twin_ratio
            _add_part(d, rng, asm, name=name, twin=twin)
    # 계면 — 조립 단위 안에서 이웃끼리, 그리고 경계를 넘는 것 일부.
    # 판단어 이름 부품은 배경 계면에 넣지 않는다 — 다른 연산이 계면 상대로 독점하면 대본이 그 부품을 못 부른다.
    by_asm: dict[str, list[str]] = {}
    for part in d.parts.values():
        if part.name not in HAZARD_NAMES:
            by_asm.setdefault(part.asm, []).append(part.name)
    kinds = ("tied", "tied", "tied", "touching", "touching", "clearance", "clearance", "interference")
    links = int(round(spec.iface_per_part * len(d.parts) / 2))
    inner = int(round(links * (1 - spec.boundary_ratio)))
    names_by_asm = [names for names in by_asm.values() if len(names) >= 2]
    for _ in range(inner * 3):
        if len(d.ifaces) >= inner or not names_by_asm:
            break
        names = rng.choice(names_by_asm)
        a, b = rng.sample(names, 2)
        d.ifaces.setdefault(_key(a, b), _iface(rng, rng.choice(kinds)))
    asms_with_parts = [asm for asm in by_asm if by_asm[asm]]
    for _ in range((links - inner) * 3):
        if len(d.ifaces) >= links or len(asms_with_parts) < 2:
            break
        asm_a, asm_b = rng.sample(asms_with_parts, 2)
        a, b = rng.choice(by_asm[asm_a]), rng.choice(by_asm[asm_b])
        d.ifaces.setdefault(_key(a, b), _iface(rng, rng.choice(("tied", "clearance"))))
    # 접촉 — dyna 짝끼리 이웃을 잇고, 단면 자기접촉(scope) 하나.
    twins = [p for p in d.parts.values() if p.pid is not None]
    for left, right in zip(twins[::2], twins[1::2]):
        d.contacts[d.next_contact] = Contact(kind="contact", pids=[left.pid, right.pid], fs=0.2,
                                             title=f"tie_{d.next_contact}")
        d.next_contact += 1
    if len(twins) >= 3:
        d.contacts[d.next_contact] = Contact(kind="scope", pids=[p.pid for p in twins[:3]],
                                             contact_type="*CONTACT_AUTOMATIC_SINGLE_SURFACE",
                                             title=f"single_{d.next_contact}")
        d.next_contact += 1
    # 배경 명명 치수 — 바뀌지 않을 부품에 묶고 그 부품을 예약한다.
    plain = [p for p in d.parts.values() if p.pid is None and p.name not in HAZARD_NAMES]
    for i, part in enumerate(plain[:spec.named_dims]):
        d.dims[f"bg_t{i + 1}"] = part.name
        d.claimed.add(part.name)
    return d


# ---------------------------------------------------------------- 어댑터 결과
def _attrs_mcad(p: Part) -> dict:
    lo = list(p.origin)
    hi = [lo[i] + p.size[i] for i in range(3)]
    world_size = [p.size[1], p.size[0], p.size[2]] if p.rotated else list(p.size)
    center = [(lo[i] + hi[i]) / 2.0 for i in range(3)]
    w_center = [center[i] + p.shift[i] for i in range(3)]
    w_lo = [round(w_center[i] - world_size[i] / 2.0, 4) for i in range(3)]
    w_hi = [round(w_center[i] + world_size[i] / 2.0, 4) for i in range(3)]
    volume = round(p.size[0] * p.size[1] * p.size[2], 4)
    min_dim = min(p.size) if p.min_dim_known else None
    return {
        "shape_kind": "solid", "bbox_def": [*lo, *hi], "size_def": list(p.size),
        "size_sorted": sorted(p.size, reverse=True), "bbox_world": [*w_lo, *w_hi],
        "centroid_def": [round(c, 4) for c in center], "centroid_world": [round(c, 4) for c in w_center],
        "volume": volume, "area": None, "min_dim": min_dim, "material": p.material, "density": None,
        "density_unit": None, "color": None, "instance_count": 1, "has_geometry": True, "depth": 3, "solid_count": 1,
        "construction_only": False, "step_file": FILE,
    }


def _mcad_canon(p: Part) -> str:
    return f"mcad:/{FILE}/{p.asm}/{p.name}"


def _dyna_canon(d: Design, suffix: Any) -> str:
    return f"dyna:{d.sha[:8]}:{suffix}"


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _union(d: Design) -> list[float]:
    boxes = [_attrs_mcad(p)["bbox_world"] for p in d.parts.values()]
    lo = [min(b[i] for b in boxes) for i in range(3)]
    hi = [max(b[i + 3] for b in boxes) for i in range(3)]
    return [round(hi[i] - lo[i], 3) for i in range(3)]


def to_adapter_results(d: Design, *, captured_at: int = CAPTURED_AT) -> list[dict]:
    """[mcad, dyna, dyna_result] — 값의 자리와 키는 `tests/fixtures/ir/adapter_*.json` 과 같다."""
    prov = {"adapter": "mcad", "app_key": "heax-step_forge", "tool": "REST /tree", "call_id": "syn-mcad-001",
            "captured_at": captured_at}
    nodes: list[dict] = [{"canon_key": f"mcad:/{FILE}", "domain": "mcad", "kind": "file", "label": FILE,
                          "local_key": f"/{FILE_STEM}/{FILE}", "status_flags": [],
                          "attrs": {"depth": 1, "relpath": FILE}, "provenance": dict(prov)}]
    for asm in sorted({p.asm for p in d.parts.values()}):
        nodes.append({"canon_key": f"mcad:/{FILE}/{asm}", "domain": "mcad", "kind": "assembly", "label": asm,
                      "local_key": f"/{FILE_STEM}/{FILE}/{asm}", "status_flags": [],
                      "attrs": {"depth": 2, "relpath": FILE}, "provenance": dict(prov),
                      "parent_canon_key": f"mcad:/{FILE}"})
    for p in d.parts.values():
        nodes.append({"canon_key": _mcad_canon(p), "domain": "mcad", "kind": "part", "label": p.name,
                      "local_key": f"/{FILE_STEM}/{FILE}/{p.asm}/{p.name}", "status_flags": [],
                      "parent_canon_key": f"mcad:/{FILE}/{p.asm}", "attrs": _attrs_mcad(p), "provenance": dict(prov)})
    edges = []
    for (a, b), iface in sorted(d.ifaces.items()):
        edges.append({
            "kind": iface.kind, "domain": "mcad", "status": iface.status,
            "a": _mcad_canon(d.parts[a]), "b": _mcad_canon(d.parts[b]),
            "attrs": {"min_gap": iface.min_gap, "contact_area_est": iface.area, "band_width": 0.05,
                      "normal_align": None, "penetration_depth": iface.penetration,
                      "penetration_depth_is_lower_bound": iface.penetration_volume is None,
                      "penetration_volume": iface.penetration_volume,
                      "cross_file": False, "face_pairs_count": None, "note": None, "tol_config_hash": "tol-a"},
            "provenance": {"adapter": "mcad", "tool": "list_interfaces", "call_id": "syn-mcad-002",
                           "detected_at": None, "params_hash": "tol-a"},
        })
    content = _digest([nodes, edges])
    stats = {"files": 1, "leaf_instances": len(d.parts), "assemblies": len({p.asm for p in d.parts.values()}),
             "interfaces": len(edges)}
    # 실제 어댑터처럼 계면 뒤에 하이라키(part_of) 엣지를 싣는다 — 어댑터 함수를 그대로 부른다(생산자 그대로, W2-02).
    # 노드에서 유도되는 엣지라 내용 해시·계면 수에는 넣지 않는다(실제 어댑터의 stats.interfaces 도 계면 행 수다).
    edges.extend(mcad_adapter._part_of_edges(nodes))
    mcad = {
        "source": {"kind": "mcad", "app_key": "heax-step_forge", "adapter_version": ADAPTER_VERSION,
                   "channel": "rest+mcp",
                   "ref": {"stepforge_project_id": f"syn-{d.spec.seed}", "project_name": FILE_STEM,
                           "unit_system": "mm", "detect_job_id": "SYNDET",
                           "step_files": [{"relpath": FILE, "sha256": content, "header_unit": "millimetre",
                                           "schema_ap": "AUTOMOTIVE_DESIGN"}]},
                   "source_hash": f"sha-mcad-{content[:16]}", "tol_config_hash": "tol-a",
                   "tol_known_keys": ["tied_gap", "clearance_gap", "tied_area", "tied_width"], "scope": None,
                   "stats": stats, "degraded": []},
        "nodes": nodes, "edges": edges, "warnings": [], "degraded": [], "call_ids": ["syn-mcad-001", "syn-mcad-002"],
    }
    out = [mcad]
    twins = [p for p in d.parts.values() if p.pid is not None]
    if not (d.spec.with_dyna and twins):
        return out
    dprov = {"adapter": "dyna", "tool": "inspect_file", "call_id": "syn-dyna-001"}
    dnodes: list[dict] = []
    for p in twins:
        attrs = _attrs_mcad(p)
        box = p.dyna_box or attrs["bbox_world"]
        lo, hi = box[:3], box[3:]
        size = [round(hi[i] - lo[i], 4) for i in range(3)]
        dnodes.append({
            "canon_key": _dyna_canon(d, p.pid), "domain": "dyna", "kind": "pid", "label": f"Syn\\{p.name}",
            "local_key": str(p.pid), "status_flags": [],
            "attrs": {"title": f"Syn\\{p.name}", "elem_class": "solid", "n_elems": p.n_elems, "bbox_min": lo,
                      "bbox_max": hi, "size": size, "size_sorted": sorted(size, reverse=True),
                      "area_ext": round(2 * (size[0] * size[1] + size[1] * size[2] + size[0] * size[2]), 2),
                      "volume": p.dyna_volume if p.dyna_box else attrs["volume"],
                      "material": {"mid": p.pid, "keyword": "*MAT_ELASTIC", "db": {"tag": p.material, "name": p.material}},
                      "secid": None},
            "provenance": dict(dprov)})
    dedges = []
    for index, c in sorted(d.contacts.items()):
        if c.kind == "scope":
            canon = _dyna_canon(d, f"contact:{index}")
            dnodes.append({"canon_key": canon, "domain": "dyna", "kind": "contact_set", "label": c.title,
                           "local_key": str(index), "status_flags": [],
                           "attrs": {"contact_index": index, "contact_type": c.contact_type, "title": c.title,
                                     "n_members": len(c.pids)}, "provenance": dict(dprov)})
            dedges.append({"kind": "scope", "domain": "dyna", "status": "auto", "a": canon, "b": None,
                           "members": [_dyna_canon(d, pid) for pid in c.pids],
                           "attrs": {"contact_index": index, "contact_type": c.contact_type, "title": c.title},
                           "provenance": dict(dprov)})
        else:
            dedges.append({"kind": "contact", "domain": "dyna", "status": "auto",
                           "a": _dyna_canon(d, c.pids[0]), "b": _dyna_canon(d, c.pids[1]),
                           "attrs": {"contact_index": index, "contact_type": c.contact_type, "title": c.title,
                                     "fs": c.fs},
                           "provenance": dict(dprov)})
    union = _union(d)
    out.append({
        "source": {"kind": "dyna", "app_key": "heax-kooremapper_mcp", "adapter_version": ADAPTER_VERSION,
                   "channel": "mcp",
                   "ref": {"session_id": "SYNSES", "file_id": "SYNFIL", "filename": f"{FILE_STEM}.k", "sha256": d.sha},
                   "source_hash": d.sha,
                   # 파일 단위 크기는 mcad 리프 합집합과 같게 둔다 — 대각비가 0.95~1.05 를 벗어나면 G6 이 막는다.
                   "stats": {"nodes": 12000, "elements": sum(p.n_elems or 0 for p in twins), "parts": len(twins),
                             "bbox_min": [0, 0, 0], "bbox_max": union, "size": union,
                             "contacts_total": len(d.contacts), "unresolved_sides": 0},
                   "degraded": []},
        "nodes": dnodes, "edges": dedges, "warnings": [], "degraded": [], "call_ids": ["syn-dyna-001"],
    })
    if not d.spec.with_result:
        return out
    # 결과층은 nid 로 dyna pid 에 얹힌다 — 실제 어댑터 등록부(adapters/registry.py)와 같은 함수로 pid → nid 를 계산한다.
    pid_to_nid = {str(p.pid): ir_builder.make_nid(_dyna_canon(d, p.pid)) for p in twins}
    out.append({
        "source": {"kind": "dyna_result", "app_key": "heax-kooremapper_mcp", "adapter_version": ADAPTER_VERSION,
                   "channel": "mcp", "ref": {"report_ids": ["SYNRPT"], "report_kind": "sphere", "session_id": "SYNSES"},
                   "source_hash": "sha-syn-report",
                   "binding": {"bound_to_dyna_source_hash": d.sha, "method": "user_declared"}, "degraded": []},
        "nodes": [], "edges": [], "warnings": [], "degraded": [], "call_ids": ["syn-result-001"],
        "results": {
            "report_ids": ["SYNRPT"], "kind": "sphere", "sim_params_hash": "simp-syn", "summary": "합성 구 낙하",
            "parts_map": pid_to_nid,
            "part_risk": [{"nid": pid_to_nid[str(p.pid)], "pid": p.pid,
                           "worst_stress": {"value": p.result["worst_stress"], "case_key": "c1"},
                           "worst_g": p.result["worst_g"], "worst_disp": p.result["worst_disp"],
                           "min_safety_factor": p.result["min_safety_factor"]} for p in twins if p.result],
            "findings": [], "energy_edges": [], "worst_cases": [], "sim_params": {"drop_height": 1.2},
        },
    })
    return out


def dim_defs(d: Design) -> list[dict]:
    """명명 치수 정의(`routes.add_dim` 의 본문) — 묶인 부품의 min_dim 을 정규명으로 집는다(정규명은 소문자 이름이다)."""
    return [{"name": name, "kind": "thickness", "unit": "mm",
             "extractor": f"node[asm={part.lower()}].attrs.min_dim"} for name, part in sorted(d.dims.items())]


# ---------------------------------------------------------------- 연산의 부품 고르기
def _free(d: Design, *, twin: bool | None = None, asm: str | None = None, not_asm: str | None = None,
          orphan: bool | None = None, plain_name: bool = False) -> list[str]:
    linked = {n for key in d.ifaces for n in key}
    out = []
    for name, p in d.parts.items():
        # 이름에 판단어가 든 부품은 대본이 `subject` 로 부를 때만 쓴다 — 무작위로 먼저 집히면 대본이 그 부품을 못 쓴다.
        if name in d.claimed or name in HAZARD_NAMES or (twin is not None and (p.pid is not None) != twin):
            continue
        if asm is not None and p.asm != asm or not_asm is not None and p.asm == not_asm:
            continue
        if orphan is not None and (name not in linked) != orphan:
            continue
        if plain_name and not name.replace("_", "").isalnum():
            continue
        out.append(name)
    return out


def _take(d: Design, rng: random.Random, params: Mapping[str, Any], *, twin: bool | None = False,
          orphan: bool | None = None, asm: str | None = None, not_asm: str | None = None,
          plain_name: bool = False, op_part: bool = True) -> str:
    """조건에 맞는 빈 부품 하나를 독점한다. `params['subject']` 가 있으면 그 부품, 없으면 고르고, 그래도 없으면 만든다."""
    asm = asm or params.get("asm")
    if params.get("subject"):
        name = str(params["subject"])
        if name in d.claimed or name not in d.parts:
            raise ValueError(f"대본이 지정한 부품을 쓸 수 없다 — {name}")
    else:
        pool = _free(d, twin=twin, asm=asm, not_asm=not_asm, orphan=orphan, plain_name=plain_name)
        if pool:
            name = rng.choice(pool)
        else:
            target_asm = asm or rng.choice([a for a in d.spec.asms if a != not_asm])
            name = _add_part(d, rng, target_asm, twin=bool(twin), op=op_part).name
    d.claimed.add(name)
    return name


def _pair(d: Design, rng: random.Random, params: Mapping[str, Any], *, twin: bool | None = None) -> tuple[str, str]:
    """계면·접촉을 걸 빈 부품 둘. `boundary` 면 서로 다른 1단 조립 단위다(`asm_b` 로 상대 쪽을 정할 수 있다)."""
    a = _take(d, rng, params, twin=twin)
    if params.get("boundary"):
        b = _take(d, rng, {}, twin=twin, asm=params.get("asm_b"), not_asm=d.asm_of(a))
    else:
        b = _take(d, rng, {}, twin=twin, asm=d.asm_of(a))
    return _key(a, b)


def _incident(d: Design, name: str) -> list[tuple[str, str]]:
    return [key for key in d.ifaces if name in key]


def _iface_codes(d: Design, keys: Sequence[tuple[str, str]], *, removed: bool) -> tuple[str, ...]:
    """지우거나 더한 계면 엣지가 내는 코드 — clearance 는 등장·소멸, 나머지는 rank ≥1 이라 추가·삭제다."""
    out = []
    for key in keys:
        clearance = d.ifaces[key].kind == "clearance"
        if removed:
            out.append("iface.clearance_cleared" if clearance else "iface.removed")
        else:
            out.append("iface.clearance_appeared" if clearance else "iface.added")
    return tuple(out)


def _rec(op: str, codes: Sequence[str], subjects: Sequence[str], *, sign: int = 0, unit: str | None = None,
         flags: Sequence[str] = ()) -> ChangeRecord:
    return ChangeRecord(op=op, expect_codes=tuple(codes), subjects=tuple(subjects), sign=sign, unit=unit,
                        flags=frozenset(flags))


def _hazard(names: Sequence[str]) -> list[str]:
    return ["hazard"] if any(n in HAZARD_NAMES for n in names) else []


def _boundary(d: Design, key: tuple[str, str]) -> list[str]:
    return ["boundary"] if d.asm_of(key[0]) != d.asm_of(key[1]) else []


# ---------------------------------------------------------------- 연산(준비는 base 에서 고르고·만들고, 적용은 target 을 바꾼다)
Prepare = Callable[[Design, random.Random, dict], dict]
Apply = Callable[[Design, dict], ChangeRecord]


def _prep_node(twin: bool | None = False, orphan: bool | None = None, plain_name: bool = False) -> Prepare:
    """대본 인자 `twin` 이 있으면 그것으로 짝(dyna pid) 있는 부품·없는 부품을 고른다."""
    def prepare(base: Design, rng: random.Random, params: dict) -> dict:
        name = _take(base, rng, params, twin=params.get("twin", twin), orphan=orphan, plain_name=plain_name)
        return {**params, "name": name}
    return prepare


def _sign(plan: Mapping[str, Any]) -> int:
    return -1 if int(plan.get("sign", 1)) < 0 else 1


def _thickness(t: Design, plan: dict, *, op: str = "part.thickness_changed") -> ChangeRecord:
    """판 두께(z 축)를 바꾼다 — bbox·부피·min_dim 이 같이 바뀐다.

    실제 어댑터는 min_dim 을 size_def 의 최솟값으로만 낸다(adapters/mcad.py `_shape_attrs`) — min_dim 만 바뀌고 크기는 그대로인
    '국부 두께' 는 운영에서 생기지 않는 모양이라 두지 않는다(R-FLOOR-1). 짝 있는 부품이면 dyna pid 도 같은 크기로 다시 만든다
    (`dyna_box` 가 없으면 dyna 가 mcad 를 따른다 — K 파일도 고친 정상 개정).
    """
    p = t.parts[plan["name"]]
    sign = _sign(plan)
    factor = 0.75 if sign < 0 else 1.3
    p.size[2] = round(p.size[2] * factor, 3)
    return _rec(op, ("part.thickness_changed",), (p.name,), sign=sign, unit="mm",
                flags=(["decrease"] if sign < 0 else []) + _hazard([p.name]))


def _resized(t: Design, plan: dict) -> ChangeRecord:
    p = t.parts[plan["name"]]
    sign = _sign(plan)
    grow = round(p.size[0] * (0.15 if sign > 0 else -0.15), 3)
    p.size[0] = round(p.size[0] + grow, 3)
    p.origin[0] = round(p.origin[0] - grow / 2.0, 4)          # 무게중심은 그대로 둔다.
    return _rec("part.resized", ("part.resized",), (p.name,), sign=sign, unit="mm",
                flags=(["decrease"] if sign < 0 else []) + _hazard([p.name]))


def _moved(t: Design, plan: dict) -> ChangeRecord:
    p = t.parts[plan["name"]]
    p.shift = [round(p.shift[0] + 1.5, 4), round(p.shift[1] + 0.8, 4), p.shift[2]]
    return _rec("part.moved", ("part.moved",), (p.name,), sign=1, unit="mm", flags=_hazard([p.name]))


def _prep_rotated(base: Design, rng: random.Random, params: dict) -> dict:
    name = _take(base, rng, params)
    p = base.parts[name]
    if abs(p.size[0] - p.size[1]) < 2.0:                       # x·y 가 거의 같으면 돌려도 bbox_world 가 안 바뀐다.
        p.size[0] = round(p.size[1] + 6.0, 2)
    return {**params, "name": name}


def _rotated(t: Design, plan: dict) -> ChangeRecord:
    p = t.parts[plan["name"]]
    p.rotated = not p.rotated
    return _rec("part.rotated", ("part.rotated",), (p.name,), sign=0, unit=None, flags=_hazard([p.name]))


def _material(t: Design, plan: dict) -> ChangeRecord:
    p = t.parts[plan["name"]]
    p.material = next(m for m in MATERIALS if m != p.material)
    return _rec("part.material_changed", ("part.material_changed",), (p.name,), flags=_hazard([p.name]))


def _mesh(t: Design, plan: dict) -> ChangeRecord:
    p = t.parts[plan["name"]]
    sign = _sign(plan)
    p.n_elems = int(p.n_elems * (1.6 if sign > 0 else 0.6))
    return _rec("mesh.density_changed", ("mesh.density_changed",), (p.name,), sign=sign, unit=None,
                flags=["design_irrelevant"] + (["decrease"] if sign < 0 else []))


_METRIC_UNIT = {"worst_stress": "MPa", "worst_g": "G", "worst_disp": "mm"}


def _result(t: Design, plan: dict) -> ChangeRecord:
    p = t.parts[plan["name"]]
    metric = plan.get("metric", "worst_stress")
    sign = _sign(plan)
    p.result = dict(p.result)
    p.result[metric] = round(p.result[metric] * (0.75 if sign < 0 else 1.3), 3)
    return _rec("result.part_metric_shift", ("result.part_metric_shift",), (p.name,), sign=sign,
                unit=_METRIC_UNIT[metric], flags=["decrease"] if sign < 0 else [])


def _prep_bridge(base: Design, rng: random.Random, params: dict) -> dict:
    """mcad 판 두께만 바뀌고 같은 묶음의 dyna pid(K 파일)는 그대로인 부품.

    지금 생산자는 이 변화에 이동·회전을 덧붙인다(PRODUCER_MISREADS) — 크기별·무작위 대본에 넣지 않는다. 이벤트 자체는 운영에서
    나므로 그 렌더링은 통과 시험이 보고, 덧붙음은 strict xfail 재현 한 곳이 본다(RV-5).

    지금 생산자는 묶음의 대표 노드를 nid 순서로 고른다 — dyna pid 의 nid 가 mcad 보다 앞이면 이 이벤트가 사라진다
    (diff._semantic 의 `node_t`). 그 조건을 피하는 부품을 고른다. 결함은 기록에 남긴다(WP1 목록).
    """
    def mcad_first(name: str) -> bool:
        p = base.parts[name]
        return ir_builder.make_nid(_mcad_canon(p)) < ir_builder.make_nid(_dyna_canon(base, p.pid))

    asm = params.get("asm")
    pool = [n for n in _free(base, twin=True, asm=asm) if mcad_first(n)]
    while not pool:
        made = _add_part(base, rng, asm or rng.choice(base.spec.asms), twin=True, op=True)
        pool = [made.name] if mcad_first(made.name) else []
    name = params.get("subject") or rng.choice(pool)
    base.claimed.add(name)
    return {**params, "name": name}


def _bridge(t: Design, plan: dict) -> ChangeRecord:
    p = t.parts[plan["name"]]
    attrs = _attrs_mcad(p)
    p.dyna_box, p.dyna_volume = list(attrs["bbox_world"]), attrs["volume"]   # K 파일은 다시 만들지 않았다.
    rec = _thickness(t, plan, op="cross.bridge_stale")
    return _rec("cross.bridge_stale", ("part.thickness_changed", "cross.bridge_stale"), rec.subjects, sign=rec.sign,
                unit="mm", flags=rec.flags)


def _prep_dim(orphan: bool) -> Prepare:
    def prepare(base: Design, rng: random.Random, params: dict) -> dict:
        name = _take(base, rng, params, orphan=orphan, plain_name=True)
        dim = f"syn_{name.lower()}"
        base.dims[dim] = name
        return {**params, "name": name, "dim": dim}
    return prepare


def _dim_changed(t: Design, plan: dict) -> ChangeRecord:
    rec = _thickness(t, plan)
    return _rec("dim.named_changed", ("dim.named_changed", "part.thickness_changed"),
                (f"dim:{plan['dim']}", plan["name"]), sign=rec.sign, unit="mm", flags=set(rec.flags) | {"no_ckey"})


def _dim_unmeasured(t: Design, plan: dict) -> ChangeRecord:
    name = plan["name"]
    codes = ("dim.named_unmeasured", "part.removed") + _iface_codes(t, _incident(t, name), removed=True)
    for key in _incident(t, name):
        del t.ifaces[key]
    del t.parts[name]
    return _rec("dim.named_unmeasured", codes, (f"dim:{plan['dim']}", name), sign=-1, flags=["no_ckey", "decrease"])


def _prep_added(base: Design, rng: random.Random, params: dict) -> dict:
    partner = _take(base, rng, params)
    return {**params, "partner": partner}


def _added(t: Design, plan: dict) -> ChangeRecord:
    rng = random.Random(f"added-{plan['partner']}")
    asm = t.asm_of(plan["partner"])
    p = _add_part(t, rng, asm, op=True)
    t.claimed.add(p.name)
    t.ifaces[_key(p.name, plan["partner"])] = Iface(kind="tied", area=60.0)
    return _rec("part.added", ("part.added", "iface.added"), (p.name, plan["partner"]), sign=1)


def _prep_removed(base: Design, rng: random.Random, params: dict) -> dict:
    """지울 부품과 그 계면 상대까지 독점한다 — 상대를 다른 연산이 고치면 지운 계면의 기대가 그 연산과 겹친다."""
    name = _take(base, rng, params)
    for key in _incident(base, name):
        base.claimed.update(key)
    return {**params, "name": name}


def _removed(t: Design, plan: dict) -> ChangeRecord:
    name = plan["name"]
    codes = ("part.removed",) + _iface_codes(t, _incident(t, name), removed=True)
    for key in _incident(t, name):
        del t.ifaces[key]
    del t.parts[name]
    return _rec("part.removed", codes, (name,), sign=-1, flags=["decrease"] + _hazard([name]))


def _prep_replaced(base: Design, rng: random.Random, params: dict) -> dict:
    """X 를 빼고 Y 를 넣는다 — 이웃을 그대로 물려받고 이름은 반쯤, 크기는 1.5배, 재질은 다르게(대응 점수 0.5~0.7)."""
    name = _take(base, rng, params, plain_name=True)
    # 교체 판정은 clearance 를 뺀 1홉 이웃을 본다 — 닿는 계면이 하나도 없으면 교체가 아니라 삭제·추가로 읽힌다.
    if not any(base.ifaces[key].kind != "clearance" for key in _incident(base, name)):
        partner = _take(base, rng, {}, asm=base.asm_of(name))
        base.ifaces[_key(name, partner)] = Iface(kind="tied", area=80.0)
    for key in _incident(base, name):
        base.claimed.update(key)
    return {**params, "name": name}


def _replaced(t: Design, plan: dict) -> ChangeRecord:
    old = t.parts[plan["name"]]
    role, _, code = old.name.partition("_")
    new_name = f"CLAMP_{code}" if role != "CLAMP" else f"HOLDER_{code}"
    new = Part(name=new_name, asm=old.asm, origin=list(old.origin),
               size=[round(old.size[0] * 1.5, 3), round(old.size[1] * 1.5, 3), old.size[2]],
               material=next(m for m in MATERIALS if m != old.material))
    incident = _incident(t, old.name)
    codes = ["part.replaced"]
    codes.extend(_iface_codes(t, incident, removed=True))
    for key in incident:
        iface = t.ifaces.pop(key)
        other = key[0] if key[1] == old.name else key[1]
        t.ifaces[_key(new.name, other)] = iface
    codes.extend(_iface_codes(t, [_key(new.name, k[0] if k[1] == old.name else k[1]) for k in incident], removed=False))
    del t.parts[old.name]
    t.parts[new.name] = new
    t.claimed.add(new.name)
    return _rec("part.replaced", codes, (old.name, new.name))


def _halves(p: Part) -> tuple[Part, Part]:
    """같은 정규명(치수 토큰만 다른 이름)의 반쪽 둘 — 길이 축으로 나눠 부피 합이 같다.

    재질은 온전한 부품과 다르게 둔다. 같으면 반쪽↔온전 쌍의 대응 점수가 0.7 을 넘어 pending 이 서고(이름 1.0 · 재질 1.0),
    G2 가 의미 이벤트를 통째로 막는다(병합 쪽에서 0.77 을 실측했다).
    """
    half = round(p.size[0] / 2.0, 4)
    material = next(m for m in MATERIALS if m != p.material)
    first = Part(name=f"{p.name}_0_5T", asm=p.asm, origin=list(p.origin), size=[half, p.size[1], p.size[2]],
                 material=material)
    second = Part(name=f"{p.name}_1_5T", asm=p.asm, origin=[round(p.origin[0] + half, 4), p.origin[1], p.origin[2]],
                  size=[round(p.size[0] - half, 4), p.size[1], p.size[2]], material=material)
    return first, second


def _split(t: Design, plan: dict) -> ChangeRecord:
    old = t.parts.pop(plan["name"])
    for half in _halves(old):
        t.parts[half.name] = half
        t.claimed.add(half.name)
    return _rec("part.split", ("part.split",), (old.name,))


def _struct_part(base: Design, rng: random.Random, params: Mapping[str, Any]) -> str:
    """쪼개기·합치기 대상 — 계면 없는 새 부품을 연산마다 다른 역할 낱말로 만든다(대본의 `subject` 가 있으면 그것)."""
    if params.get("subject"):
        return _take(base, rng, params, orphan=True)
    n = base.struct_n
    base.struct_n += 1
    role = STRUCT_ROLES[n % len(STRUCT_ROLES)] + (STRUCT_ROLES[n // len(STRUCT_ROLES) - 1]
                                                  if n >= len(STRUCT_ROLES) else "")
    asm = params.get("asm") or rng.choice(base.spec.asms)
    name = _add_part(base, rng, asm, name=_new_name(base, role, op=True), op=True).name
    base.claimed.add(name)
    return name


def _prep_split(base: Design, rng: random.Random, params: dict) -> dict:
    return {**params, "name": _struct_part(base, rng, params)}


def _prep_merged(base: Design, rng: random.Random, params: dict) -> dict:
    """base 에 반쪽 둘을 두고 target 에서 하나로 합친다."""
    name = _struct_part(base, rng, params)
    whole = base.parts.pop(name)
    halves = _halves(whole)
    for half in halves:
        base.parts[half.name] = half
        base.claimed.add(half.name)
    return {**params, "whole": whole, "halves": [h.name for h in halves]}


def _merged(t: Design, plan: dict) -> ChangeRecord:
    for half in plan["halves"]:
        del t.parts[half]
    whole = copy.deepcopy(plan["whole"])
    t.parts[whole.name] = whole
    t.claimed.add(whole.name)
    return _rec("part.merged", ("part.merged",), (whole.name,))


def _prep_tree(base: Design, rng: random.Random, params: dict) -> dict:
    name = _take(base, rng, params, orphan=True)
    to = params.get("to") or next(a for a in base.spec.asms if a != base.asm_of(name))
    return {**params, "name": name, "to": to}


def _tree(t: Design, plan: dict) -> ChangeRecord:
    t.parts[plan["name"]].asm = plan["to"]
    return _rec("part.tree_moved", ("part.tree_moved",), (plan["name"],))


def _prep_new_iface(base: Design, rng: random.Random, params: dict) -> dict:
    a, b = _pair(base, rng, params)
    if _key(a, b) in base.ifaces:
        del base.ifaces[_key(a, b)]
    return {**params, "key": _key(a, b)}


def _prep_iface(kind: str, **extra: Any) -> Prepare:
    def prepare(base: Design, rng: random.Random, params: dict) -> dict:
        key = _pair(base, rng, params)
        base.ifaces[key] = Iface(kind=kind, min_gap=extra.get("min_gap", 0.0 if kind != "clearance" else 0.4),
                                 area=extra.get("area"), penetration=extra.get("penetration"),
                                 penetration_volume=extra.get("penetration_volume"))
        return {**params, "key": key}
    return prepare


def _iface_added(kind: str, code: str) -> Apply:
    def apply(t: Design, plan: dict) -> ChangeRecord:
        key = plan["key"]
        t.ifaces[key] = Iface(kind=kind, min_gap=0.0 if kind != "clearance" else 0.4,
                              area=90.0 if kind != "clearance" else None)
        return _rec(code, (code,), key, sign=1, flags=_boundary(t, key) + _hazard(key))
    return apply


def _iface_removed(code: str) -> Apply:
    def apply(t: Design, plan: dict) -> ChangeRecord:
        key = plan["key"]
        flags = _boundary(t, key) + _hazard(key) + ["decrease"]
        del t.ifaces[key]
        return _rec(code, (code,), key, sign=-1, flags=flags)
    return apply


def _kind_change(to: str, code: str, *, status: str = "confirmed", sign: int = 0, extra_flags: Sequence[str] = ()) -> Apply:
    def apply(t: Design, plan: dict) -> ChangeRecord:
        key = plan["key"]
        iface = t.ifaces[key]
        iface.kind, iface.status = to, status
        if to == "interference":
            iface.area, iface.penetration, iface.penetration_volume = None, 0.05, None
        elif to in ("tied", "touching"):
            iface.penetration = None
            iface.area = iface.area or 70.0
        return _rec(code, (code,), key, sign=sign, unit="rank",
                    flags=list(extra_flags) + _boundary(t, key) + (["decrease"] if sign < 0 else []))
    return apply


def _gap(t: Design, plan: dict) -> ChangeRecord:
    key, sign = plan["key"], _sign(plan)
    iface = t.ifaces[key]
    iface.min_gap = round(iface.min_gap * (0.55 if sign < 0 else 1.5), 4)
    return _rec("iface.gap_changed", ("iface.gap_changed",), key, sign=sign, unit="mm",
                flags=_boundary(t, key) + _hazard(key) + (["decrease"] if sign < 0 else []))


def _band(t: Design, plan: dict) -> ChangeRecord:
    key, sign = plan["key"], _sign(plan)
    iface = t.ifaces[key]
    iface.area = round(iface.area * (0.5 if sign < 0 else 1.6), 2)
    return _rec("iface.band_area_changed", ("iface.band_area_changed",), key, sign=sign, unit="mm2",
                flags=_boundary(t, key) + (["decrease"] if sign < 0 else []))


def _penetration(t: Design, plan: dict) -> ChangeRecord:
    key = plan["key"]
    iface = t.ifaces[key]
    # 부울 경로가 부피를 냈다 — 그때만 깊이가 하한이 아니다(어댑터 mcad.py). 한쪽이 하한이 아니어야 견준다(둘 다 하한이면 incomparable).
    iface.penetration, iface.penetration_volume = 0.02, 0.6
    return _rec("iface.penetration_changed", ("iface.penetration_changed",), key, sign=-1, unit="mm",
                flags=["lower_bound", "decrease"] + _boundary(t, key))


def _status_only(t: Design, plan: dict) -> ChangeRecord:
    t.ifaces[plan["key"]].status = "auto"
    return _rec("iface.status_changed", (), plan["key"], flags=["excluded:status_changed"])


def _clear_pair_contacts(base: Design, names: Sequence[str]) -> None:
    """두 pid 사이의 배경 접촉을 base 에서 지운다 — 같은 쌍의 접촉 엣지가 둘이면 diff 가 (kind_family, dn 쌍) 으로 하나만 본다."""
    pids = {base.parts[n].pid for n in names}
    for index in [i for i, c in base.contacts.items() if c.kind == "contact" and set(c.pids) == pids]:
        del base.contacts[index]


def _prep_contact(kind: str = "contact", members: int = 2, fs: float | None = 0.2) -> Prepare:
    def prepare(base: Design, rng: random.Random, params: dict) -> dict:
        names = [_take(base, rng, params if i == 0 else {}, twin=True) for i in range(members)]
        if kind == "contact":
            _clear_pair_contacts(base, names)
        index = base.next_contact
        base.next_contact += 1
        base.contacts[index] = Contact(kind=kind, pids=[base.parts[n].pid for n in names], fs=fs,
                                       contact_type=("*CONTACT_AUTOMATIC_SINGLE_SURFACE" if kind == "scope"
                                                     else "*CONTACT_TIED_SURFACE_TO_SURFACE"),
                                       title=f"syn_{kind}_{index}")
        extra = _take(base, rng, {}, twin=True) if kind == "scope" else None
        return {**params, "index": index, "names": names, "extra": extra}
    return prepare


def _prep_new_contact(base: Design, rng: random.Random, params: dict) -> dict:
    names = [_take(base, rng, params, twin=True), _take(base, rng, {}, twin=True)]
    _clear_pair_contacts(base, names)
    index = base.next_contact
    base.next_contact += 1
    return {**params, "index": index, "names": names}


def _contact_added(t: Design, plan: dict) -> ChangeRecord:
    pids = [t.parts[n].pid for n in plan["names"]]
    t.contacts[plan["index"]] = Contact(kind="contact", pids=pids, fs=0.2, title=f"syn_contact_{plan['index']}")
    return _rec("contact.added", ("contact.added",), tuple(plan["names"]), sign=1)


def _contact_removed(t: Design, plan: dict) -> ChangeRecord:
    del t.contacts[plan["index"]]
    return _rec("contact.removed", ("contact.removed",), tuple(plan["names"]), sign=-1, flags=["decrease"])


def _friction(t: Design, plan: dict) -> ChangeRecord:
    contact, sign = t.contacts[plan["index"]], _sign(plan)
    contact.fs = round(contact.fs + (0.15 if sign > 0 else -0.1), 3)
    return _rec("contact.friction_changed", ("contact.friction_changed",), tuple(plan["names"]), sign=sign,
                flags=["decrease"] if sign < 0 else [])


def _contact_type(t: Design, plan: dict) -> ChangeRecord:
    """접촉 종류를 바꾼다(*CONTACT_TIED… → *CONTACT_AUTOMATIC…) — 실제 개정에서 종류가 바뀌는 자리는 이 속성이다.

    지금 생산자는 이 변화를 이벤트로 내지 않는다(엣지 kind 가 contact↔scope 로 뒤집힐 때만 낸다 — 반대 검토 P-04 보충).
    그래서 크기별 대본에는 넣지 않고 따로 시험한다.
    """
    t.contacts[plan["index"]].contact_type = "*CONTACT_AUTOMATIC_SURFACE_TO_SURFACE"
    return _rec("contact.type_changed", ("contact.type_changed",), tuple(plan["names"]))


def _scope(t: Design, plan: dict) -> ChangeRecord:
    contact = t.contacts[plan["index"]]
    contact.pids = contact.pids + [t.parts[plan["extra"]].pid]
    return _rec("contact.scope_changed", ("contact.scope_changed",), (f"contact#{plan['index']}",), sign=1,
                flags=["no_ckey"])


def _noise(t: Design, plan: dict) -> ChangeRecord:
    p = t.parts[plan["name"]]
    p.size[2] = round(p.size[2] + 0.004, 4)                      # 절대 0.02 · 상대 2% 밑이라 잡음이다.
    return _rec("part.noise", (), (p.name,), flags=["excluded:noise"])


def _null_one_side(t: Design, plan: dict) -> ChangeRecord:
    p = t.parts[plan["name"]]
    p.min_dim_known = False
    return _rec("part.min_dim_unknown", (), (p.name,), flags=["excluded:null_one_side"])


OPS: dict[str, tuple[Prepare, Apply]] = {
    "part.added": (_prep_added, _added),
    "part.removed": (_prep_removed, _removed),
    "part.replaced": (_prep_replaced, _replaced),
    "part.split": (_prep_split, _split),
    "part.merged": (_prep_merged, _merged),
    "part.tree_moved": (_prep_tree, _tree),
    "iface.added": (_prep_new_iface, _iface_added("tied", "iface.added")),
    "iface.removed": (_prep_iface("tied", area=75.0), _iface_removed("iface.removed")),
    "iface.clearance_appeared": (_prep_new_iface, _iface_added("clearance", "iface.clearance_appeared")),
    "iface.clearance_cleared": (_prep_iface("clearance"), _iface_removed("iface.clearance_cleared")),
    "iface.rank_up": (_prep_iface("touching", area=65.0), _kind_change("tied", "iface.rank_up", sign=1)),
    "iface.rank_down": (_prep_iface("tied", area=65.0), _kind_change("touching", "iface.rank_down", sign=-1)),
    "iface.interference_new": (_prep_iface("tied", area=65.0),
                               _kind_change("interference", "iface.interference_new", status="auto", sign=1,
                                            extra_flags=["unconfirmed"])),
    "iface.interference_cleared": (_prep_iface("interference", penetration=0.05),
                                   _kind_change("tied", "iface.interference_cleared", sign=-1)),
    "iface.gap_changed": (_prep_iface("clearance", min_gap=0.4), _gap),
    "iface.band_area_changed": (_prep_iface("tied", area=120.0), _band),
    "iface.penetration_changed": (_prep_iface("interference", penetration=0.05), _penetration),
    "iface.status_changed": (_prep_iface("tied", area=70.0), _status_only),
    "contact.added": (_prep_new_contact, _contact_added),
    "contact.removed": (_prep_contact(), _contact_removed),
    "contact.type_changed": (_prep_contact(), _contact_type),
    "contact.friction_changed": (_prep_contact(fs=0.2), _friction),
    "contact.scope_changed": (_prep_contact(kind="scope", members=2, fs=None), _scope),
    "part.thickness_changed": (_prep_node(), _thickness),
    "part.resized": (_prep_node(), _resized),
    "part.moved": (_prep_node(), _moved),
    "part.rotated": (_prep_rotated, _rotated),
    "mesh.density_changed": (_prep_node(twin=True), _mesh),
    "part.material_changed": (_prep_node(), _material),
    "cross.bridge_stale": (_prep_bridge, _bridge),
    "dim.named_changed": (_prep_dim(orphan=None), _dim_changed),
    "dim.named_unmeasured": (_prep_dim(orphan=True), _dim_unmeasured),
    "result.part_metric_shift": (_prep_node(twin=True), _result),
    "part.noise": (_prep_node(), _noise),
    "part.min_dim_unknown": (_prep_node(), _null_one_side),
}
# 생산자 결함 둘은 뜻이 다르다(RV-5) — 커버리지 셈은 '내지 못한다' 만 운영 코드에서 뺀다. 둘 다 크기별·무작위 대본에 넣지 않는다.
# 지금 생산자가 내지 못하는 연산 — 그 코드는 운영에서도 나지 않는다(strict xfail 로 재현한다).
PRODUCER_GAPS: dict[str, str] = {
    "contact.type_changed": "diff._edge_change 는 엣지 kind 만 견준다 — contact_type 속성이 바뀌어도 이벤트가 없다",
}
# 지금 생산자가 틀리게 내는 연산 — 그 코드는 운영에서 나지만 `extra` 를 덧붙인다. 코드의 렌더링은 통과 시험이, 덧붙음은 strict
# xfail 이 본다. 덧붙음을 대본 기대(expect_codes)에 넣지 않는다 — 넣으면 생산자를 고쳐도 기대가 결함을 붙든다.
PRODUCER_MISREADS: dict[str, dict] = {
    # 실제 어댑터는 두께를 바꾸면 bbox·size_def·min_dim 을 같이 바꾼다 — 짝 있는 부품의 두께 변경(K 파일 그대로)은 전부 이 길이다.
    "cross.bridge_stale": {
        "extra": ("part.moved", "part.rotated"),
        "why": "diff._parametric 이 같은 dn 의 mcad·dyna 노드 값을 같은 cid 로 by_dn 에 덮는다 — dyna 크기가 mcad bbox 변화를"
               " 가려 짝 있는 부품의 두께 변화(K 파일 그대로)가 part.moved·part.rotated 를 덧붙인다",
    },
}


# ---------------------------------------------------------------- 조립 단위 롤업(설계 모형에서 센다)
def _rollup_counts(d: Design) -> dict[str, tuple[int, int]]:
    """접두(파일 · 파일/1단 조립 단위)마다 (내부, 외부) 계면 엣지 수 — mcad 리프 사이의 계면만 센다(dyna 접촉은 리프가 아니다)."""
    prefixes = {FILE_STEM} | {f"{FILE_STEM}/{p.asm}" for p in d.parts.values()}
    out = {}
    for prefix in prefixes:
        members = {n for n, p in d.parts.items() if prefix == FILE_STEM or f"{FILE_STEM}/{p.asm}" == prefix}
        internal = external = 0
        for a, b in d.ifaces:
            hits = (a in members) + (b in members)
            if hits == 2:
                internal += 1
            elif hits == 1:
                external += 1
        out[prefix] = (internal, external)
    return out


def rollup_records(base: Design, target: Design) -> list[ChangeRecord]:
    before, after = _rollup_counts(base), _rollup_counts(target)
    out = []
    for prefix in sorted(set(before) & set(after)):
        (bi, be), (ai, ae) = before[prefix], after[prefix]
        if abs(ai - bi) >= 1 or abs(ae - be) >= 1:
            out.append(_rec("derived:asm.rollup", ("asm.rollup_changed",), (f"asm:{prefix}",),
                            sign=1 if (ai + ae) > (bi + be) else -1, flags=["derived", "no_ckey"]))
    return out


# ---------------------------------------------------------------- 대본 적용
def apply_script(design: Design, script: Sequence[tuple[str, Mapping[str, Any]]],
                 seed: int) -> tuple[Design, Design, list[ChangeRecord]]:
    """(base, target, 기록). 준비가 전부 base 에서 끝난 뒤에 target 을 떠서 적용한다 — 연산이 서로의 준비를 보지 않는다."""
    base = copy.deepcopy(design)
    # 배경 설계와 다른 난수 줄기를 쓴다 — 같은 씨앗의 같은 줄기면 준비 단계가 만든 부품의 크기가 배경 부품과 똑같이 나와
    # 기하 지문이 겹치고, 이름이 다른 두 부품이 fingerprint 0.85(pending)로 묶여 G2 가 막는다(무작위 대본 씨앗 35 에서 실측).
    rng = random.Random(f"script-{seed}")
    plans = []
    for op, params in script:
        if op not in OPS:
            raise ValueError(f"모르는 연산 — {op!r}")
        prepare, apply = OPS[op]
        plans.append((apply, prepare(base, rng, dict(params))))
    target = copy.deepcopy(base)
    records = [apply(target, plan) for apply, plan in plans]
    return base, target, records + rollup_records(base, target)


def expected_codes(records: Sequence[ChangeRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for code in record.expect_codes:
            counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


_RANDOM_WEIGHTS: tuple[tuple[str, int], ...] = (
    ("part.moved", 12), ("part.resized", 10), ("iface.gap_changed", 12), ("part.thickness_changed", 8),
    ("part.material_changed", 3), ("iface.added", 4), ("iface.removed", 3), ("iface.clearance_appeared", 2),
    ("iface.clearance_cleared", 2), ("iface.rank_up", 2), ("iface.rank_down", 2), ("iface.interference_new", 1),
    ("iface.interference_cleared", 1), ("iface.band_area_changed", 2), ("iface.penetration_changed", 1),
    ("part.added", 2), ("part.removed", 2), ("part.replaced", 1), ("part.split", 1), ("part.merged", 1),
    ("part.tree_moved", 1), ("part.rotated", 2), ("mesh.density_changed", 3),
    ("result.part_metric_shift", 4), ("contact.added", 1), ("contact.removed", 1), ("contact.friction_changed", 1),
    ("contact.scope_changed", 1), ("dim.named_changed", 1), ("dim.named_unmeasured", 1), ("part.noise", 2),
    ("iface.status_changed", 1),
)


def random_script(n_mutations: int, seed: int) -> list[tuple[str, dict]]:
    """무작위 대본(WP1·WP2 의 다건 시험용) — 생산자가 내는 연산만, 감소·경계 변형을 섞는다."""
    rng = random.Random(seed)
    names = [op for op, _ in _RANDOM_WEIGHTS]
    weights = [w for _, w in _RANDOM_WEIGHTS]
    out = []
    for _ in range(n_mutations):
        op = rng.choices(names, weights)[0]
        params: dict = {}
        if rng.random() < 0.4:
            params["sign"] = -1
        if op.startswith("iface.") and rng.random() < 0.2:
            params["boundary"] = True
        out.append((op, params))
    return out
