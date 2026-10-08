# 어댑터 원시 응답을 rr_ir 봉투로 조립하고 ir_hash 를 계산해 rr_snapshots·rr_snapshot_calls 에 동결 저장한다(plan §2.2~§2.11)
from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import sqlite3
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from app.common import R, canonical_json, new_uuid, now_epoch, sha256_hex
from app.errors import AppError
from app.taxonomy import load_json, version_of

__all__ = [
    "IR_VERSION",
    "IrSource",
    "sha1_hex",
    "name_norm",
    "name_norm_canon",
    "geom_fp",
    "geom_bucket",
    "material_norm",
    "canonical_part_key",
    "asm_key_of",
    "make_nid",
    "make_eid",
    "kind_family_of",
    "round_attrs",
    "compute_ir_hash",
    "build_ir",
    "build_rollups",
    "evaluate_dims",
    "freeze_snapshot",
    "record_calls",
    "load_calls",
    "load_ir",
    "resolve_ckey",
]

IR_VERSION = "1.0"
IR_VERSION_ECAD = "1.1"

SOURCE_KINDS: tuple[str, ...] = ("mcad", "dyna", "dyna_result", "ecad")

# 엣지 kind → kind_family(plan §2.4).
KIND_FAMILY: dict[str, str] = {
    "tied": "iface", "touching": "iface", "clearance": "iface",
    "interference": "iface", "geometric": "iface",
    "contact": "contact", "scope": "contact",
    "part_of": "hier", "bridge": "bridge", "load_path": "load_path", "net": "net",
}
# 방향 kind 는 끝점을 정렬하지 않는다(plan §2.4).
DIRECTED_KINDS: frozenset[str] = frozenset({"part_of", "load_path", "net"})
# 계면 강도 순위(plan §2.4 — diff 의 coupling 방향 판정용).
IFACE_STRENGTH: dict[str, int] = {"interference": 3, "tied": 2, "touching": 1, "geometric": 1, "clearance": 0}
# '닿음' 으로 세는 kind(clearance 제외 — StepForge graph.py 규약, plan §2.9).
TOUCHING_KINDS: frozenset[str] = frozenset({"tied", "touching", "interference", "geometric", "contact"})

# 원장 재적용 우선순위(plan §2.10) — 숫자가 클수록 세다.
_STATUS_RANK: dict[str, int] = {"auto": 0, "confirmed": 1, "manual": 2, "manual_ledger": 3, "rejected": 4}

# name_norm_canon 시드 어휘(plan §2.7.1). rr_dim_vocab 이 있으면 그쪽이 정본이고 이 표는 폴백이다.
SEED_STOP_TOKENS: tuple[str, ...] = ("rev", "ver", "new", "old", "final", "tmp", "copy")
SEED_SYNONYMS: dict[str, str] = {
    "board": "pcb", "main_board": "pcb", "mainboard": "pcb", "pba": "pcb",
    "batt": "battery", "bat": "battery", "cell": "battery",
    "disp": "display", "lcd": "display", "oled": "display", "panel": "display",
    "hsg": "housing", "case": "housing", "cover": "housing",
    "brkt": "bracket", "bkt": "bracket",
    "adhesive": "tape", "adh": "tape", "psa": "tape",
    "scr": "screw", "bolt": "screw",
    "frm": "frame", "chassis": "frame",
    "shield": "shield_can", "can": "shield_can", "emi_can": "shield_can",
    "fpc": "fpcb", "flex": "fpcb",
}

# 두께·치수 표기 토큰(plan §2.7.1 2단계).
_DIM_TOKEN_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d+(_\d+)?t$"),
    re.compile(r"^t\d+(_\d+)?$"),
    re.compile(r"^\d+(_\d+)?mm$"),
)

# attrs 반올림 규칙(plan §2.11.1 R()). 키가 걸리면 그 하위 트리 전체에 같은 kind 를 적용한다.
ATTR_ROUNDING: dict[str, str] = {
    # 길이 0.001 mm
    "bbox_def": "length", "size_def": "length", "size_sorted": "length", "bbox_world": "length",
    "centroid_def": "length", "centroid_world": "length", "min_dim": "length", "bbox_min": "length",
    "bbox_max": "length", "size": "length", "min_gap": "length", "band_width": "length",
    "penetration_depth": "length", "gap_min": "length", "gap_avg": "length", "worst_disp": "length",
    "thickness": "length", "height": "length", "proj": "length",
    # 면적·부피 4 유효자리
    "area": "area", "area_ext": "area", "contact_area_est": "area",
    "volume": "volume", "penetration_volume": "volume",
    # 비율·정렬도 0.001
    "normal_align": "ratio", "score": "ratio",
    # fs 0.01
    "fs": "fs", "min_safety_factor": "fs",
    # 응력 0.1 MPa · 가속도 0.1 G
    "worst_stress": "stress", "sigy": "stress", "peak_force": "stress", "total_work": "stress",
    "worst_g": "acceleration",
}


# ---------------------------------------------------------------- 어댑터 계약(plan §2.13.1)
@runtime_checkable
class IrSource(Protocol):
    """소스 kind 하나를 읽어 AdapterResult dict 를 돌려주는 어댑터. 구현은 adapters/ 담당이고 여기서는 주입만 받는다.

    capture() 결과 dict 의 키는 `{source, nodes, edges, warnings, degraded, call_ids}` 이고
    선택으로 `results`(dyna_result) · `missing`(어댑터가 아는 결측 플래그) 를 더 실을 수 있다.
    노드·엣지의 nid·eid·ckey 는 어댑터가 아니라 이 모듈이 붙인다.
    """

    kind: str
    version: str

    def discover(self, registry: Any) -> Mapping[str, Any]:
        ...

    def capture(self, ref: Mapping[str, Any], principal: Any, recorder: Any) -> Mapping[str, Any]:
        ...


# ---------------------------------------------------------------- 키 계산(plan §2.7)
def sha1_hex(text: str) -> str:
    """UTF-8 sha1 소문자 hex(40자). nid·eid·ckey·geom_fp 의 절단 입력이다."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _sig(value: float | int | None, digits: int) -> float | None:
    """유효자리 반올림(geom_fp 전용). None 은 None 이다."""
    if value is None:
        return None
    if not math.isfinite(float(value)):
        raise ValueError(f"geom_fp: 유한하지 않은 값 — {value!r}.")
    v = float(value)
    if v == 0:
        return 0.0
    exponent = math.floor(math.log10(abs(v)))
    factor = 10 ** (digits - 1 - exponent)
    return float(round(v * factor) / factor)


_RE_TRAILING_SEQ = re.compile(r"#\d+$")
_RE_TRAILING_INSTANCE = re.compile(r"_\d+$")
_RE_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def name_norm(label: str, *, auto_named: bool = False) -> str:
    """표시명 정규화(plan §2.7.1) — 소문자 → `#\\d+$` 제거 → auto_named 면 `_\\d+$` 제거 → 구분자 뒤만 → 비영숫자 `_` → 양끝 `_` 제거."""
    text = (label or "").strip().lower()
    text = _RE_TRAILING_SEQ.sub("", text)
    if auto_named:
        text = _RE_TRAILING_INSTANCE.sub("", text)
    for sep in ("\\", "/"):
        if sep in text:
            text = text.rsplit(sep, 1)[1]
    text = _RE_NON_ALNUM.sub("_", text)
    return text.strip("_")


def name_norm_canon(
    normalized: str,
    *,
    project_codes: Sequence[str] = (),
    stop_tokens: Sequence[str] = SEED_STOP_TOKENS,
    synonyms: Mapping[str, str] | None = None,
) -> str:
    """과제 무관 정규명(plan §2.7.1) — 과제 코드·불용어 제거 → 두께 토큰 제거 → 동의어 치환 → 재결합. 비면 원문을 그대로 쓴다."""
    tokens = [t for t in (normalized or "").split("_") if t]
    if not tokens:
        return normalized or ""
    drop = {c.strip().lower() for c in project_codes if c} | {s.strip().lower() for s in stop_tokens if s}
    tokens = [t for t in tokens if t not in drop]

    # 두께·치수 토큰은 인접 두 토큰이 합쳐져야 규칙에 맞는 경우(`1_5t`)가 있어 왼쪽부터 2토큰 창으로 본다.
    kept: list[str] = []
    i = 0
    while i < len(tokens):
        pair = f"{tokens[i]}_{tokens[i + 1]}" if i + 1 < len(tokens) else None
        if pair is not None and any(rx.match(pair) for rx in _DIM_TOKEN_RES):
            i += 2
            continue
        if any(rx.match(tokens[i]) for rx in _DIM_TOKEN_RES):
            i += 1
            continue
        kept.append(tokens[i])
        i += 1
    tokens = kept

    table = dict(SEED_SYNONYMS if synonyms is None else synonyms)
    if tokens:
        # 머리 토큰 치환. 별칭이 여러 토큰(`main_board`)일 수 있어 긴 접두부터 본다.
        for width in (3, 2, 1):
            if width > len(tokens):
                continue
            head = "_".join(tokens[:width])
            if head in table:
                tokens = [t for t in table[head].split("_") if t] + tokens[width:]
                break
    out = "_".join(tokens)
    return out or (normalized or "")


def geom_fp(
    *,
    kind: str | None,
    size: Sequence[float] | None,
    volume: float | None,
    area: float | None,
    centroid_offset: Sequence[float] | None,
) -> str | None:
    """기하 지문(plan §2.7.2) — sha1(kind, sorted(round(size,2)), sig(volume,3), sig(area,3), round(offset,2))[:16]. 기하가 없으면 None."""
    if not size or all(s is None for s in size):
        return None
    dims = sorted(round(float(s), 2) for s in size if s is not None)
    offset: Any = "na"
    if centroid_offset is not None and all(c is not None for c in centroid_offset):
        offset = [round(float(c), 2) for c in centroid_offset]
    payload = [
        kind or "na",
        dims,
        _sig(volume, 3) if volume is not None else "na",
        _sig(area, 3) if area is not None else "na",
        offset,
    ]
    return sha1_hex(canonical_json(payload))[:16]


def geom_bucket(size_sorted: Sequence[float] | None, volume: float | None) -> str:
    """ckey 의 기하 버킷(plan §2.7.3) — size 3축 0.5 mm 버킷 + 부피 5% 로그 버킷(`@v?` 는 부피 미상)."""
    dims = []
    for s in size_sorted or ():
        if s is None:
            dims.append("?")
        else:
            dims.append(str(round(float(s) / 0.5) * 0.5))
    head = "x".join(dims) if dims else "?"
    if volume:
        tail = str(round(math.log(float(volume)) / math.log(1.05)))
    else:
        tail = "?"
    return f"{head}@v{tail}"


def material_norm(value: str | None) -> str:
    """재질 정규화(plan §2.7.3) — 동의어 치환 후 첫 토큰, 없으면 'na'."""
    normalized = name_norm(value or "")
    if not normalized:
        return "na"
    canon = name_norm_canon(normalized)
    first = canon.split("_")[0] if canon else ""
    return first or "na"


def canonical_part_key(canon_name: str, bucket: str, material: str) -> str:
    """canonical_part_key(plan §2.7.3) — `ck:` + sha1(name_norm_canon|geom_bucket|material_norm)[:12]."""
    return "ck:" + sha1_hex(f"{canon_name}|{bucket}|{material}")[:12]


_RE_FILE_EXT = re.compile(r"\.[a-z0-9]{1,5}$")


def asm_key_of(
    path: str,
    *,
    project_name: str | None = None,
    drop_leaf: bool = True,
    project_codes: Sequence[str] = (),
    synonyms: Mapping[str, str] | None = None,
) -> str:
    """mcad path → asm_key(plan §2.7.4) — 프로젝트명 제거 · 세그먼트 `#\\d+$` 제거 · name_norm_canon 적용 · `/` 결합.

    파일 세그먼트(`a_stack.step`)는 확장자를 떼고 정규화한다(계획 예 `a_stack/stack_asm`).
    drop_leaf=True 면 리프 이름을 뺀 부모 체인을 돌려준다.
    """
    segments = [s for s in (path or "").split("/") if s]
    if project_name:
        pn = project_name.strip()
        if segments and segments[0] == pn:
            segments = segments[1:]
    if drop_leaf and segments:
        segments = segments[:-1]
    out: list[str] = []
    for seg in segments:
        seg = _RE_TRAILING_SEQ.sub("", seg)
        seg = _RE_FILE_EXT.sub("", seg)
        canon = name_norm_canon(name_norm(seg), project_codes=project_codes, synonyms=synonyms)
        if canon:
            out.append(canon)
    return "/".join(out)


def make_nid(canon_key: str) -> str:
    """노드 id(plan §2.3) — `p:` + sha1(canon_key)[:12]. 소스가 노드 번호를 재부여해도 불변이다."""
    return "p:" + sha1_hex(canon_key)[:12]


def make_eid(kind_family: str, a: str, b: str | None, *, directed: bool = False) -> str:
    """엣지 id(plan §2.4) — `e:` + sha1(kind_family|정렬한 끝점)[:12]. 방향 kind 는 정렬하지 않는다."""
    ends = [a, b or ""]
    if not directed:
        ends = sorted(ends)
    return "e:" + sha1_hex(kind_family + "|" + "|".join(ends))[:12]


def kind_family_of(kind: str) -> str:
    """엣지 kind → kind_family. 모르는 kind 는 E100 이다(조용히 통과시키면 eid 가 흔들린다)."""
    try:
        return KIND_FAMILY[kind]
    except KeyError as exc:
        raise AppError("E100", f"모르는 엣지 kind — {kind!r}. 허용 {sorted(KIND_FAMILY)}.", http_status=400) from exc


# ---------------------------------------------------------------- ir_hash(plan §2.11.1)
def round_attrs(obj: Any, kind: str | None = None) -> Any:
    """attrs 를 §2.11.1 반올림 규칙으로 접는다. 키가 규칙표에 걸리면 그 하위 트리 전체에 같은 kind 를 적용한다."""
    if isinstance(obj, Mapping):
        # 자식 키가 규칙표에 없으면 상속받은 kind 를 그대로 물려준다(리스트 가지와 같은 규칙).
        return {str(k): round_attrs(v, ATTR_ROUNDING.get(str(k), kind)) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_attrs(v, kind) for v in obj]
    if kind is None or obj is None or isinstance(obj, bool) or not isinstance(obj, (int, float)):
        return obj
    return R(obj, kind)


def compute_ir_hash(ir: Mapping[str, Any]) -> str:
    """ir_hash(plan §2.11.1) — 노드·엣지·확정 same_as·dims_named 만 정렬해 정규 JSON 으로 해싱한다.

    provenance·captured_at·snapshot_id·sources[].stats·봉투 context·warnings·rollups·gates·character_seed·
    feature_vector 는 입력에 없다. 그래서 같은 소스·같은 잣대·같은 원장이면 재추출해도 같은 값이 나온다.
    """
    nodes = sorted(
        (
            {
                "nid": n["nid"], "canon_key": n["canon_key"], "domain": n["domain"], "kind": n["kind"],
                "name_norm": n["name_norm"], "name_norm_canon": n["name_norm_canon"],
                "ckey": n.get("ckey"), "dn": n.get("dn"), "asm_key": n.get("asm_key"),
                "status_flags": sorted(n.get("status_flags") or []),
                "attrs": round_attrs(n.get("attrs") or {}),
            }
            for n in ir.get("nodes") or []
        ),
        key=lambda x: x["nid"],
    )
    edges = sorted(
        (
            {
                "eid": e["eid"], "kind": e["kind"], "a": e["a"], "b": e.get("b"),
                "members": sorted(e.get("members") or []),
                "status": e.get("status"), "attrs": round_attrs(e.get("attrs") or {}),
            }
            for e in ir.get("edges") or []
        ),
        key=lambda x: x["eid"],
    )
    same_as = sorted(
        ({"a": s["a"], "b": s["b"], "method": s["method"]} for s in ir.get("same_as") or [] if s.get("status") == "confirmed"),
        key=lambda x: (x["a"], x["b"]),
    )
    dims = sorted(
        (
            {"name": d["name"], "value": R(d.get("value"), "length"), "unit": d.get("unit"), "method": d.get("method")}
            for d in ir.get("dims_named") or []
        ),
        key=lambda x: x["name"],
    )
    return sha256_hex(canonical_json({"nodes": nodes, "edges": edges, "same_as": same_as, "dims_named": dims}))


# ---------------------------------------------------------------- 조립 보조
def _as_list(value: Any) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _dig(obj: Any, path: str) -> Any:
    """점 표기 경로로 dict 를 판다. 중간에 끊기면 None."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        elif isinstance(cur, (list, tuple)) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def _mcad_path(canon_key: str) -> str:
    """mcad canon_key(`mcad:/a_stack.step/...`) 에서 path 부분만."""
    return canon_key[5:] if canon_key.startswith("mcad:") else canon_key


def _node_geom_fp(node: Mapping[str, Any]) -> str | None:
    """도메인별 geom_fp 입력을 골라 지문을 만든다(plan §2.7.2)."""
    attrs = node.get("attrs") or {}
    domain = node.get("domain")
    if domain == "mcad":
        bbox = attrs.get("bbox_def")
        centroid = attrs.get("centroid_def")
        offset = None
        if bbox and len(bbox) == 6 and centroid and len(centroid) == 3 and all(v is not None for v in list(bbox) + list(centroid)):
            center = [(bbox[i] + bbox[i + 3]) / 2.0 for i in range(3)]
            offset = [centroid[i] - center[i] for i in range(3)]
        return geom_fp(
            kind=attrs.get("shape_kind"),
            size=attrs.get("size_def") or attrs.get("size_sorted"),
            volume=attrs.get("volume"),
            area=attrs.get("area"),
            centroid_offset=offset,
        )
    if domain == "dyna":
        if node.get("kind") != "pid":
            return None
        return geom_fp(
            kind=attrs.get("elem_class"),
            size=attrs.get("size_sorted") or attrs.get("size"),
            volume=attrs.get("volume"),
            area=attrs.get("area_ext"),
            centroid_offset=None,
        )
    if domain == "ecad" and node.get("kind") == "component":
        footprint = attrs.get("footprint")
        if not footprint:
            return None
        return sha1_hex(canonical_json([str(footprint), attrs.get("pin_count")]))[:16]
    return None


def _node_material(node: Mapping[str, Any]) -> str:
    """material_norm 입력 선택(plan §2.7.3)."""
    attrs = node.get("attrs") or {}
    domain = node.get("domain")
    if domain == "mcad":
        return material_norm(attrs.get("material"))
    if domain == "dyna":
        mat = attrs.get("material") or {}
        db = mat.get("db") or {}
        kfile = mat.get("kfile") or {}
        return material_norm(db.get("tag") or db.get("name") or kfile.get("name") or mat.get("name"))
    if domain == "ecad":
        return material_norm(attrs.get("part_number"))
    return "na"


def _node_size_sorted(node: Mapping[str, Any]) -> list[float] | None:
    attrs = node.get("attrs") or {}
    size = attrs.get("size_sorted") or attrs.get("size_def") or attrs.get("size")
    if not size:
        return None
    vals = [float(s) for s in size if s is not None]
    return sorted(vals, reverse=True) if vals else None


def _pair_key(path_a: str, path_b: str) -> str:
    """rr_iface_ledger.pair_key — 프로젝트명을 뗀 두 path 를 정렬해 `|` 로 잇는다(plan §0.2.2)."""
    return "|".join(sorted([path_a, path_b]))


def _subject_key(ck_a: str | None, ck_b: str | None) -> str | None:
    """계면 subject_key(plan §2.7.6) — 양끝 ckey 정렬. 하나라도 없으면 None."""
    if not ck_a or not ck_b:
        return None
    return "|".join(sorted([ck_a, ck_b]))


class _Union:
    """same-as 클러스터용 최소 union-find(결정론 — 대표는 뒤에서 §2.7.5 규칙으로 다시 고른다)."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


_DOMAIN_RANK = {"mcad": 0, "dyna": 1, "ecad": 2}


def _representative(nids: Sequence[str], index: Mapping[str, Mapping[str, Any]]) -> str:
    """클러스터 대표 dn(plan §2.7.5) — mcad part > dyna pid > ecad component, 같은 도메인이면 canon_key 오름차순."""
    def rank(nid: str) -> tuple:
        node = index[nid]
        return (_DOMAIN_RANK.get(node.get("domain"), 9), node.get("canon_key") or "")

    return sorted(nids, key=rank)[0]


def _default_sameas_resolve(nodes_a, nodes_b, edges_a, edges_b, scope, ledger):
    """same-as 사다리(plan §2.6)는 sameas.py 담당이다. 없으면 강등하지 않고 드러낸다."""
    try:
        from app import sameas  # noqa: PLC0415 — 모듈 간 순환을 피하려 지연 임포트한다.
    except ImportError as exc:  # pragma: no cover - sameas.py 가 붙기 전 경로
        raise AppError(
            "E500",
            "다중 도메인 스냅샷은 same-as 사다리가 필요합니다 — app/sameas.py 의 resolve() 가 없습니다.",
        ) from exc
    return sameas.resolve(nodes_a, nodes_b, edges_a, edges_b, scope, ledger)


# ---------------------------------------------------------------- 롤업(plan §2.9)
def build_rollups(nodes: Sequence[Mapping[str, Any]], edges: Sequence[Mapping[str, Any]]) -> dict:
    """rollups.by_assembly — asm_key 접두 depth 1..max 마다 리프 수·내부/외부 엣지·고아 리프를 센다.

    리프 엣지는 iface·contact family 이고 status='rejected' 는 제외한다. 고아는 clearance 를 빼고
    tied·touching·interference·geometric·contact 어디에도 끼지 않은 리프다(StepForge graph.py 규약).
    """
    leaves = [n for n in nodes if n.get("domain") == "mcad" and n.get("kind") == "part" and "scope_out" not in (n.get("status_flags") or [])]
    asm_of = {n["nid"]: (n.get("asm_key") or "") for n in leaves}

    live = [
        e for e in edges
        if e.get("status") != "rejected" and KIND_FAMILY.get(e.get("kind"), "") in ("iface", "contact")
    ]
    touching: set[str] = set()
    for e in live:
        if e.get("kind") in TOUCHING_KINDS:
            for nid in [e.get("a"), e.get("b"), *(e.get("members") or [])]:
                if nid:
                    touching.add(nid)

    prefixes: dict[str, int] = {}
    for asm in asm_of.values():
        if not asm:
            continue
        parts = asm.split("/")
        for depth in range(1, len(parts) + 1):
            prefixes["/".join(parts[:depth])] = depth

    def under(nid: str, prefix: str) -> bool:
        asm = asm_of.get(nid)
        if asm is None:
            return False
        return asm == prefix or asm.startswith(prefix + "/")

    rows = []
    for prefix in sorted(prefixes):
        members = [n["nid"] for n in leaves if under(n["nid"], prefix)]
        member_set = set(members)
        internal: dict[str, int] = {}
        external: dict[str, int] = {}
        for e in live:
            ends = [x for x in [e.get("a"), e.get("b"), *(e.get("members") or [])] if x]
            hits = sum(1 for x in ends if x in member_set)
            if hits == 0:
                continue
            bucket = internal if hits == len(ends) else external
            bucket[e["kind"]] = bucket.get(e["kind"], 0) + 1
        rows.append({
            "path_prefix": prefix,
            "depth": prefixes[prefix],
            "n_leaf": len(members),
            "edges_internal": dict(sorted(internal.items())),
            "edges_external": dict(sorted(external.items())),
            "orphan_leaf": sum(1 for nid in members if nid not in touching),
        })
    return {"by_assembly": rows}


# ---------------------------------------------------------------- dims_named(plan §2.8)
_RE_CONST = re.compile(r"^const:\s*(-?\d+(?:\.\d+)?)$")
_RE_NODE_CK = re.compile(r"^node\[ck=(ck:[0-9a-f]{12})\]\.(.+)$")
_RE_NODE_ASM = re.compile(r"^node\[asm=([^\]*]+)\]\.(.+)$")
_RE_EDGE_CK = re.compile(r"^edge\[ck=(ck:[0-9a-f]{12})\|(ck:[0-9a-f]{12})\]\.(.+)$")
_RE_EDGE_NAME = re.compile(r"^edge\[name=([^|\]]+)\|([^\]]+)\]\.(.+)$")
_RE_RESULT_CK = re.compile(r"^result\[ck=(ck:[0-9a-f]{12})\]\.(.+)$")
_RE_OVERALL = re.compile(r"^overall\.(bbox_world\.[xyz]|volume|n_leaf)$")
_RE_DERIVED = re.compile(r"^dim\(([A-Za-z0-9_]+)\)\s*([+\-*/])\s*dim\(([A-Za-z0-9_]+)\)$")
_RE_AGG = re.compile(r"^(sum|min|max)\(node\[asm=([^\]]*?)\*\]\.(.+)\)$")


def _dim_row(name: str, unit: str, method: str, extractor: str, owner_sub: str, *, value=None, ref=None, null_reason=None) -> dict:
    return {
        "name": name, "value": value, "unit": unit, "method": method,
        "ref": ref, "formula": extractor, "owner_sub": owner_sub,
        "null_reason": null_reason if value is None else None,
    }


def evaluate_dims(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    results: Mapping[str, Any] | None,
    dim_defs: Sequence[Mapping[str, Any]],
    *,
    dim_vocab: Mapping[str, Mapping[str, Any]] | None = None,
    owner_sub: str = "system",
) -> list[dict]:
    """rr_dim_defs 의 extractor 를 IR 위에서 재평가한다(plan §2.8). 값이 없으면 0 이 아니라 null + null_reason 이다."""
    vocab = dict(dim_vocab or {})
    by_nid = {n["nid"]: n for n in nodes}
    leaves = [n for n in nodes if n.get("domain") == "mcad" and n.get("kind") == "part"]

    def nodes_by_ck(ckey: str) -> list[Mapping[str, Any]]:
        return [n for n in nodes if n.get("ckey") == ckey]

    def nodes_by_asm(selector: str) -> list[Mapping[str, Any]]:
        # `<asm_key>/<name_norm_canon>` — 마지막 세그먼트가 리프 이름이다.
        prefix, _, leaf = selector.rpartition("/")
        return [
            n for n in leaves
            if (n.get("name_norm_canon") == leaf) and ((n.get("asm_key") or "") == prefix or not prefix)
        ]

    def edges_by_ck(ck_a: str, ck_b: str) -> list[Mapping[str, Any]]:
        want = _subject_key(ck_a, ck_b)
        out = []
        for e in edges:
            a, b = by_nid.get(e.get("a") or ""), by_nid.get(e.get("b") or "")
            if not a or not b:
                continue
            if _subject_key(a.get("ckey"), b.get("ckey")) == want:
                out.append(e)
        return out

    def edges_by_name(name_a: str, name_b: str) -> list[Mapping[str, Any]]:
        want = sorted([name_a.strip().lower(), name_b.strip().lower()])
        out = []
        for e in edges:
            a, b = by_nid.get(e.get("a") or ""), by_nid.get(e.get("b") or "")
            if not a or not b:
                continue
            if sorted([a.get("name_norm") or "", b.get("name_norm") or ""]) == want:
                out.append(e)
        return out

    def pick(matches: Sequence[Mapping[str, Any]], attr_path: str, ref_of: Callable[[Mapping[str, Any]], str]):
        if not matches:
            return None, None, "ref_missing"
        if len(matches) > 1:
            return None, None, "ambiguous"
        item = matches[0]
        if "scope_out" in (item.get("status_flags") or []):
            return None, ref_of(item), "scope_out"
        value = _dig(item, attr_path)
        if value is None:
            return None, ref_of(item), "attr_null"
        return value, ref_of(item), None

    node_ref = lambda n: n["nid"]  # noqa: E731 — 짧은 참조 생성기
    edge_ref = lambda e: e["eid"]  # noqa: E731

    rows: dict[str, dict] = {}
    deferred: list[Mapping[str, Any]] = []

    for definition in dim_defs:
        name = definition.get("name") or ""
        extractor = (definition.get("extractor") or "").strip()
        unit = str((vocab.get(name) or {}).get("unit") or definition.get("unit") or "mm")
        owner = definition.get("owner_sub") or owner_sub

        m = _RE_CONST.match(extractor)
        if m:
            rows[name] = _dim_row(name, unit, "declared", extractor, owner, value=float(m.group(1)))
            continue
        m = _RE_NODE_CK.match(extractor)
        if m:
            value, ref, reason = pick(nodes_by_ck(m.group(1)), m.group(2), node_ref)
            rows[name] = _dim_row(name, unit, "measured", extractor, owner, value=value, ref=ref, null_reason=reason)
            continue
        m = _RE_NODE_ASM.match(extractor)
        if m:
            value, ref, reason = pick(nodes_by_asm(m.group(1)), m.group(2), node_ref)
            rows[name] = _dim_row(name, unit, "measured", extractor, owner, value=value, ref=ref, null_reason=reason)
            continue
        m = _RE_EDGE_CK.match(extractor)
        if m:
            value, ref, reason = pick(edges_by_ck(m.group(1), m.group(2)), m.group(3), edge_ref)
            rows[name] = _dim_row(name, unit, "measured", extractor, owner, value=value, ref=ref, null_reason=reason)
            continue
        m = _RE_EDGE_NAME.match(extractor)
        if m:
            value, ref, reason = pick(edges_by_name(m.group(1), m.group(2)), m.group(3), edge_ref)
            rows[name] = _dim_row(name, unit, "measured", extractor, owner, value=value, ref=ref, null_reason=reason)
            continue
        m = _RE_RESULT_CK.match(extractor)
        if m:
            if not results:
                rows[name] = _dim_row(name, unit, "measured", extractor, owner, null_reason="ref_missing")
                continue
            targets = [n["nid"] for n in nodes_by_ck(m.group(1))]
            hits = [r for r in _as_list(results.get("part_risk")) if r.get("nid") in targets]
            value, ref, reason = None, None, "ref_missing"
            if len(hits) == 1:
                ref = hits[0].get("nid")
                raw = _dig(hits[0], m.group(2))
                if isinstance(raw, Mapping):
                    raw = raw.get("value")
                value, reason = (raw, None) if raw is not None else (None, "attr_null")
            elif len(hits) > 1:
                reason = "ambiguous"
            rows[name] = _dim_row(name, unit, "measured", extractor, owner, value=value, ref=ref, null_reason=reason)
            continue
        m = _RE_OVERALL.match(extractor)
        if m:
            what = m.group(1)
            value, reason = None, "attr_null"
            if what == "n_leaf":
                value, reason = len(leaves), None
            elif what == "volume":
                vols = [n["attrs"].get("volume") for n in leaves if (n.get("attrs") or {}).get("volume") is not None]
                value, reason = (sum(vols), None) if vols else (None, "attr_null")
            else:
                axis = "xyz".index(what[-1])
                boxes = [n["attrs"].get("bbox_world") for n in leaves if (n.get("attrs") or {}).get("bbox_world")]
                if boxes:
                    lo = min(float(b[axis]) for b in boxes)
                    hi = max(float(b[axis + 3]) for b in boxes)
                    value, reason = hi - lo, None
            rows[name] = _dim_row(name, unit, "measured", extractor, owner, value=value, null_reason=reason)
            continue
        m = _RE_AGG.match(extractor)
        if m:
            op, prefix, attr_path = m.group(1), m.group(2).rstrip("/"), m.group(3)
            picked = [
                n for n in leaves
                if (n.get("asm_key") or "") == prefix or (n.get("asm_key") or "").startswith(prefix + "/")
            ]
            values = [v for v in ( _dig(n, attr_path) for n in picked ) if isinstance(v, (int, float)) and not isinstance(v, bool)]
            refs = [n["nid"] for n in picked]
            if not values:
                rows[name] = _dim_row(name, unit, "derived", extractor, owner, ref=refs or None, null_reason="ref_missing" if not picked else "attr_null")
            else:
                agg = {"sum": sum, "min": min, "max": max}[op](values)
                rows[name] = _dim_row(name, unit, "derived", extractor, owner, value=float(agg), ref=refs)
            continue
        if _RE_DERIVED.match(extractor):
            deferred.append(definition)
            continue
        rows[name] = _dim_row(name, unit, "measured", extractor, owner, null_reason="ref_missing")

    # 파생 치수는 입력 치수가 먼저 나와야 하므로 최대 정의 수만큼 반복한다(순환은 마지막에 null 로 남는다).
    for _ in range(len(deferred) + 1):
        pending = []
        for definition in deferred:
            name = definition.get("name") or ""
            extractor = (definition.get("extractor") or "").strip()
            unit = str((vocab.get(name) or {}).get("unit") or definition.get("unit") or "mm")
            owner = definition.get("owner_sub") or owner_sub
            m = _RE_DERIVED.match(extractor)
            left, op, right = rows.get(m.group(1)), m.group(2), rows.get(m.group(3))
            if left is None or right is None:
                pending.append(definition)
                continue
            lv, rv = left.get("value"), right.get("value")
            if lv is None or rv is None:
                rows[name] = _dim_row(name, unit, "derived", extractor, owner, ref=[m.group(1), m.group(3)], null_reason="attr_null")
                continue
            if op == "/" and float(rv) == 0.0:
                rows[name] = _dim_row(name, unit, "derived", extractor, owner, ref=[m.group(1), m.group(3)], null_reason="attr_null")
                continue
            value = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b, "/": lambda a, b: a / b}[op](float(lv), float(rv))
            rows[name] = _dim_row(name, unit, "derived", extractor, owner, value=value, ref=[m.group(1), m.group(3)])
        if not pending or len(pending) == len(deferred):
            for definition in pending:
                name = definition.get("name") or ""
                unit = str((vocab.get(name) or {}).get("unit") or definition.get("unit") or "mm")
                rows[name] = _dim_row(name, unit, "derived", (definition.get("extractor") or "").strip(),
                                      definition.get("owner_sub") or owner_sub, null_reason="ref_missing")
            break
        deferred = pending

    return [rows[k] for k in sorted(rows)]


# ---------------------------------------------------------------- IR 조립(plan §2.11.3 6~8단계)
def build_ir(
    *,
    project_id: str,
    owner_sub: str,
    label: str,
    adapter_results: Sequence[Mapping[str, Any]],
    snapshot_id: str | None = None,
    derived_from: str | None = None,
    captured_at: int | None = None,
    iface_ledger: Sequence[Mapping[str, Any]] = (),
    sameas_ledger: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    dim_defs: Sequence[Mapping[str, Any]] = (),
    dim_vocab: Mapping[str, Mapping[str, Any]] | None = None,
    project_codes: Sequence[str] = (),
    synonyms: Mapping[str, str] | None = None,
    # 봉투 최상위 조직 문맥(§2.2 context.corpus_usage) — 소스 캡처가 아니라 capture_all 이 따로 모은다.
    context: Mapping[str, Any] | None = None,
    resolve_ckey_fn: Callable[[str], str] | None = None,
    sameas_resolve: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
    versions: Mapping[str, str] | None = None,
) -> dict:
    """어댑터 원시 결과를 rr_ir 봉투 하나로 조립하고 ir_hash 를 채워 돌려준다(DB 접근 없음).

    adapter_results 항목은 `{source, nodes, edges, warnings, degraded, call_ids}` 이고
    선택으로 `results`(dyna_result 결과층) · `missing`(어댑터가 아는 결측 플래그) 를 더 실을 수 있다.
    """
    captured = int(captured_at if captured_at is not None else now_epoch())
    warnings: list[dict] = []
    sources: list[dict] = []
    results: dict | None = None
    missing_declared: dict[str, bool] = {}

    seen_kinds: set[str] = set()
    raw_nodes: list[dict] = []
    raw_edges: list[dict] = []
    for result in adapter_results:
        source = dict(result.get("source") or {})
        kind = source.get("kind")
        if kind not in SOURCE_KINDS:
            raise AppError("E100", f"모르는 소스 kind — {kind!r}. 허용 {list(SOURCE_KINDS)}.", http_status=400)
        if kind in seen_kinds:
            raise AppError("E100", f"한 스냅샷에 소스 kind '{kind}' 는 최대 1건입니다(plan §2.2).", http_status=400)
        seen_kinds.add(kind)
        source.setdefault("app_key", None)
        source.setdefault("adapter_version", "0.0")
        source.setdefault("channel", None)
        source.setdefault("ref", {})
        source.setdefault("source_hash", None)
        source["degraded"] = sorted(str(d) for d in _as_list(result.get("degraded")) or _as_list(source.get("degraded")))
        source.setdefault("captured_at", captured)
        sources.append(source)
        for w in _as_list(result.get("warnings")):
            row = dict(w)
            row.setdefault("severity", "WARNING")
            row.setdefault("ref", None)
            row.setdefault("source_kind", kind)
            warnings.append(row)
        for n in _as_list(result.get("nodes")):
            raw_nodes.append(dict(n))
        for e in _as_list(result.get("edges")):
            raw_edges.append(dict(e))
        if result.get("results") is not None:
            results = dict(result["results"])
        for key, value in (result.get("missing") or {}).items():
            missing_declared[str(key)] = bool(value)

    if not sources:
        raise AppError("E100", "소스가 하나도 없는 스냅샷은 만들지 않습니다(plan §2.11.3 1단계).", http_status=409)
    sources.sort(key=lambda s: SOURCE_KINDS.index(s["kind"]))
    mcad_source = next((s for s in sources if s["kind"] == "mcad"), None)
    # mcad 없이도 스냅샷은 선다 — 그때 정본 소스는 dyna 이고 형상층 게이트는 pass=null 이다(plan §2.2·§3.2.2).
    primary_source = "mcad" if mcad_source is not None else (
        "dyna" if any(s["kind"] in ("dyna", "dyna_result") for s in sources) else "ecad")
    project_name = ((mcad_source or {}).get("ref") or {}).get("project_name") or None

    # --- 노드 정규화(nid·name_norm·name_norm_canon·geom_fp·asm_key)
    nodes: list[dict] = []
    by_canon: dict[str, dict] = {}
    for raw in raw_nodes:
        canon_key = raw.get("canon_key")
        if not canon_key:
            raise AppError("E100", f"노드에 canon_key 가 없습니다 — {raw.get('label')!r}.", http_status=400)
        if canon_key in by_canon:
            raise AppError("E100", f"canon_key 가 중복입니다 — {canon_key!r}(어댑터 버그).", http_status=400)
        flags = sorted(set(str(f) for f in _as_list(raw.get("status_flags"))))
        label_text = str(raw.get("label") or "")
        normalized = name_norm(label_text, auto_named="auto_named" in flags)
        node = {
            "nid": make_nid(canon_key),
            "canon_key": canon_key,
            "domain": raw.get("domain"),
            "kind": raw.get("kind"),
            "label": label_text,
            "local_key": str(raw.get("local_key") or ""),
            "name_norm": normalized,
            "name_norm_canon": name_norm_canon(normalized, project_codes=project_codes, synonyms=synonyms),
            "group": raw.get("group"),
            "ckey": None,
            "dn": None,
            "parent_nid": None,
            "asm_key": None,
            "attrs": dict(raw.get("attrs") or {}),
            "geom_fp": None,
            "status_flags": flags,
            "provenance": dict(raw.get("provenance") or {}),
        }
        node["geom_fp"] = _node_geom_fp(node)
        if node["domain"] == "mcad":
            node["asm_key"] = asm_key_of(
                _mcad_path(canon_key), project_name=project_name, project_codes=project_codes, synonyms=synonyms,
            )
        node["_parent_canon_key"] = raw.get("parent_canon_key")
        node["_material_norm"] = _node_material(node)
        nodes.append(node)
        by_canon[canon_key] = node

    by_nid = {n["nid"]: n for n in nodes}
    for node in nodes:
        parent_ck = node.pop("_parent_canon_key", None)
        if parent_ck and parent_ck in by_canon:
            node["parent_nid"] = by_canon[parent_ck]["nid"]
        if node["domain"] == "mcad" and node["group"] is None and node["parent_nid"]:
            node["group"] = by_nid[node["parent_nid"]]["name_norm"]

    # 동명 리프는 IR 빌더가 전역으로만 알 수 있다(plan §2.3 duplicate_name).
    seen_names: dict[str, list[str]] = {}
    for node in nodes:
        if node["domain"] == "mcad" and node["kind"] == "part":
            seen_names.setdefault(node["name_norm"], []).append(node["nid"])
    for name, nids in seen_names.items():
        if len(nids) > 1:
            for nid in nids:
                flags = set(by_nid[nid]["status_flags"])
                flags.add("duplicate_name")
                by_nid[nid]["status_flags"] = sorted(flags)

    # --- 엣지 정규화 + 원장 재적용(plan §2.10)
    ledger_by_pair = { (row.get("pair_key") or ""): dict(row) for row in iface_ledger }
    used_pairs: set[str] = set()
    edges: list[dict] = []
    seen_eids: set[str] = set()
    # dyna pid → 노드. 브리지 엣지(mcad part ↔ dyna pid)의 dyna 쪽 끝점을 여기서 푼다 — mcad 캡처는
    # K파일 sha 를 모르므로 `dyna:<sha8>:<pid>` 를 스스로 만들 수 없고 `b_pid` 로만 넘긴다(§2.5.1).
    dyna_by_pid = {str(n.get("local_key")): n for n in nodes
                   if n.get("domain") == "dyna" and n.get("kind") == "pid" and n.get("local_key") is not None}
    bridges_without_dyna = 0
    for raw in raw_edges:
        kind = str(raw.get("kind") or "")
        family = kind_family_of(kind)
        a = raw.get("a") or raw.get("a_canon_key")
        b = raw.get("b") or raw.get("b_canon_key")
        a_nid = a if isinstance(a, str) and a.startswith("p:") else (by_canon.get(a or "") or {}).get("nid")
        b_nid = b if isinstance(b, str) and b.startswith("p:") else (by_canon.get(b or "") or {}).get("nid")
        if b_nid is None and raw.get("b_pid") is not None:
            if not dyna_by_pid:
                # dyna pid 가 하나도 없는 스냅샷(K파일 미지정·자격 없음)에는 이을 상대가 없다. part_mesh 표는
                # StepForge 가 주므로 그런 스냅샷에도 메시 행 수만큼 후보가 온다 — 행마다 경고를 남기면 파트
                # 수만큼 같은 줄이 쌓이므로 건수만 세어 아래에서 한 줄로 남긴다.
                bridges_without_dyna += 1
                continue
            pid_node = dyna_by_pid.get(str(raw["b_pid"]))
            # dyna 는 있는데 그 pid 가 없으면 브리지를 만들지 않는다 — 아래 공통 경로가
            # `ambiguous_edge_endpoint` 로 남긴다(없는 노드를 가리키는 엣지를 만들지 않는다).
            b = pid_node["canon_key"] if pid_node else f"pid:{raw['b_pid']}"
            b_nid = pid_node["nid"] if pid_node else None
        if not a_nid or (b is not None and not b_nid):
            warnings.append({
                "severity": "WARNING", "code": "ambiguous_edge_endpoint",
                "message": f"엣지 끝점을 노드로 풀지 못해 제외했다 — kind={kind} a={a!r} b={b!r}",
                "ref": None, "source_kind": raw.get("domain") or "ir_builder",
            })
            continue
        members = []
        for m in _as_list(raw.get("members")) or _as_list(raw.get("members_canon_keys")):
            nid = m if isinstance(m, str) and m.startswith("p:") else (by_canon.get(m or "") or {}).get("nid")
            if nid:
                members.append(nid)
        edge = {
            "eid": make_eid(family, a_nid, b_nid, directed=kind in DIRECTED_KINDS),
            "kind": kind,
            "kind_family": family,
            "a": a_nid,
            "b": b_nid,
            "domain": raw.get("domain"),
            "status": str(raw.get("status") or "auto"),
            "attrs": dict(raw.get("attrs") or {}),
            "provenance": dict(raw.get("provenance") or {}),
        }
        if members:
            edge["members"] = sorted(members)
        if edge["eid"] in seen_eids:
            continue
        seen_eids.add(edge["eid"])

        if family == "iface" and by_nid[a_nid]["domain"] == "mcad" and b_nid and by_nid[b_nid]["domain"] == "mcad":
            pair = _pair_key(_mcad_path(by_nid[a_nid]["canon_key"]), _mcad_path(by_nid[b_nid]["canon_key"]))
            row = ledger_by_pair.get(pair)
            if row:
                used_pairs.add(pair)
                if row.get("kind_override"):
                    edge["attrs"]["kind_source"] = edge["kind"]
                    edge["kind"] = str(row["kind_override"])
                edge["status"] = "rejected" if row.get("status") == "rejected" else "manual_ledger"
                fp_a, fp_b = by_nid[a_nid].get("geom_fp"), by_nid[b_nid].get("geom_fp")
                saved = sorted([row.get("geom_fp_a") or "", row.get("geom_fp_b") or ""])
                if any(saved) and saved != sorted([fp_a or "", fp_b or ""]):
                    warnings.append({
                        "severity": "INFO", "code": "ledger_needs_review",
                        "message": f"원장 확정 이후 끝점 기하가 바뀌었다 — pair_key={pair}",
                        "ref": edge["eid"], "source_kind": "ir_builder",
                    })
        edges.append(edge)

    if bridges_without_dyna:
        warnings.append({
            "severity": "INFO", "code": "bridge_without_dyna",
            "message": f"part_mesh 표의 브리지 {bridges_without_dyna}건은 이 스냅샷에 dyna pid 가 없어 잇지 않았다.",
            "ref": None, "source_kind": "ir_builder",
        })
    for pair in sorted(set(ledger_by_pair) - used_pairs):
        warnings.append({
            "severity": "INFO", "code": "ledger_pair_absent",
            "message": f"원장 pair_key 에 해당하는 엣지가 이번 검출에 없다 — pair_key={pair}",
            "ref": None, "source_kind": "ir_builder",
        })

    # --- same-as 사다리(intra) → 클러스터 → dn·ckey(plan §2.6·§2.7.3·§2.7.5)
    domains = sorted({n["domain"] for n in nodes})
    same_as: list[dict] = []
    if len(domains) >= 2:
        resolver = sameas_resolve or _default_sameas_resolve
        # 사다리 1단계가 보는 원장은 rr_sameas(stable 키 쌍 → 행)이지 rr_iface_ledger 가 아니다(plan §2.6.2·§2.10).
        # intra 는 도메인 쌍(mcad↔dyna·mcad↔ecad·dyna↔ecad)마다 부른다 — 양쪽에 같은 목록을 넣으면
        # 자기 자신과의 대응이 taken_a·taken_b 를 소진해 name_norm·fuzzy 단계가 죽는다(sameas.resolve 계약).
        seen: set[tuple[str, str, str]] = set()
        by_domain = {d: [n for n in nodes if n["domain"] == d] for d in domains}
        for i, dom_a in enumerate(domains):
            for dom_b in domains[i + 1:]:
                if not by_domain[dom_a] or not by_domain[dom_b]:
                    continue
                for record in resolver(by_domain[dom_a], by_domain[dom_b], edges, edges, "intra", sameas_ledger):
                    item = dict(record)
                    if item.get("a") == item.get("b"):
                        continue
                    key = (str(item.get("a")), str(item.get("b")), str(item.get("method")))
                    if key in seen:
                        continue
                    seen.add(key)
                    same_as.append(item)
        same_as.sort(key=lambda r: (str(r.get("a")), str(r.get("b")), str(r.get("method"))))

    union = _Union()
    for nid in by_nid:
        union.find(nid)
    for record in same_as:
        status, score = record.get("status"), float(record.get("score") or 0.0)
        if record.get("a") in by_nid and record.get("b") in by_nid and (status == "confirmed" or (status == "auto" and score >= 0.90)):
            union.union(record["a"], record["b"])

    clusters: dict[str, list[str]] = {}
    for nid in sorted(by_nid):
        clusters.setdefault(union.find(nid), []).append(nid)

    for root, members in sorted(clusters.items()):
        domain_counts: dict[str, int] = {}
        for nid in members:
            d = by_nid[nid]["domain"]
            domain_counts[d] = domain_counts.get(d, 0) + 1
        conflict = len(members) > 1 and any(c > 1 for c in domain_counts.values())
        if conflict:
            for nid in members:
                by_nid[nid]["dn"] = nid
                by_nid[nid]["ckey"] = None
            warnings.append({
                "severity": "WARNING", "code": "sameas_conflict",
                "message": "한 클러스터에 같은 도메인 노드가 둘 이상이다 — " + " ".join(sorted(members)),
                "ref": sorted(members)[0], "source_kind": "ir_builder",
            })
            continue
        dn = _representative(members, by_nid)
        rep = by_nid[dn]
        bucket = geom_bucket(_node_size_sorted(rep), (rep.get("attrs") or {}).get("volume"))
        computed = canonical_part_key(rep["name_norm_canon"], bucket, rep["_material_norm"])
        effective = resolve_ckey_fn(computed) if resolve_ckey_fn else computed
        for nid in members:
            by_nid[nid]["dn"] = dn
            by_nid[nid]["ckey"] = effective
            by_nid[nid]["_ckey_computed"] = computed
            by_nid[nid]["_geom_bucket"] = bucket

    # --- 결과층 오버레이(plan §2.9) — 노드 투영을 통해 ir_hash 에 반영된다.
    if results:
        for row in _as_list(results.get("part_risk")):
            nid = row.get("nid")
            if nid in by_nid:
                by_nid[nid]["attrs"]["results"] = {
                    "report_id": (_as_list(results.get("report_ids")) or [None])[0],
                    "worst_stress": row.get("worst_stress"),
                    "worst_g": row.get("worst_g"),
                    "worst_disp": row.get("worst_disp"),
                    "min_safety_factor": row.get("min_safety_factor"),
                }

    # --- dims_named · rollups
    dims_named = evaluate_dims(nodes, edges, results, dim_defs, dim_vocab=dim_vocab, owner_sub=owner_sub)
    rollups = build_rollups(nodes, edges)

    # --- missing(plan §2.2)
    mcad_parts = [n for n in nodes if n["domain"] == "mcad" and n["kind"] == "part"]
    dyna_nodes = [n for n in nodes if n["domain"] == "dyna"]
    has_dyna = any(s["kind"] == "dyna" for s in sources)
    has_dyna_result = any(s["kind"] == "dyna_result" for s in sources)
    density_unsourced = any(
        (n["attrs"].get("density") is not None and not n["attrs"].get("density_unit")) for n in mcad_parts
    ) or any(((n["attrs"].get("material") or {}).get("db") is None) for n in dyna_nodes if n["kind"] == "pid")
    missing = {
        # 게이트 G3·G4·G6 과 규칙 evaluable 의 입력이다(plan §2.12·§3.2.6) — 어댑터 선언값도 이 키로 덮인다.
        "mcad_absent": not any(s["kind"] == "mcad" for s in sources),
        "iface_kinds_absent": False,
        "ecad_absent": not any(s["kind"] == "ecad" and "ecad_absent" not in s["degraded"] for s in sources),
        "dyna_absent": not has_dyna,
        "dyna_result_absent": bool(has_dyna and not results),
        "result_kind_mismatch": False,
        "world_transform_absent": bool(mcad_parts) and all(n["attrs"].get("bbox_world") is None for n in mcad_parts),
        "volume_null": bool(mcad_parts) and all(n["attrs"].get("volume") is None for n in mcad_parts),
        "material_density_unsourced": bool(density_unsourced),
        # kind 별 **필수 호출** 실패(정본 §2.2 missing 표) — 그 kind 의 노드·엣지를 하나도 만들지 않고
        # `<kind>_absent` 와 함께 선다. 어댑터가 선언하고 여기 기본값이 있어야 아래 update 를 통과한다.
        "mcad_capture_failed": False,
        "dyna_capture_failed": False,
        "ecad_capture_failed": False,
    }
    if has_dyna_result and not results:
        missing["dyna_result_absent"] = True
    # 어댑터 선언은 **기본값이 있는 키만** 통과한다 — 없는 키를 선언하면 조용히 버려지므로, 새 플래그는
    # 위 기본값에 함께 넣어야 한다(그러지 않으면 어댑터가 세운 사실이 봉투에 안 실린다).
    missing.update({k: v for k, v in missing_declared.items() if k in missing})

    partial = any(s.get("scope") is not None for s in sources)

    # --- 봉투
    ir_version = IR_VERSION_ECAD if any(n["domain"] == "ecad" for n in nodes) else IR_VERSION
    stamp = {
        "ir_version": ir_version,
        "adapter_versions": {s["kind"]: str(s.get("adapter_version") or "0.0") for s in sources},
        "taxonomy_version": str(version_of(load_json("taxonomy")) or "1.0"),
        "seed_rules_version": str(version_of(load_json("character-seed-rules")) or "seed-1.0"),
        "vocab_version": str((load_json("character-seed-rules").get("vocab_version")) or "vocab-1.0"),
    }
    stamp.update({k: str(v) for k, v in (versions or {}).items()})

    for node in nodes:
        node.pop("_material_norm", None)
        node.pop("_ckey_computed", None)
        node.pop("_geom_bucket", None)
        if node["dn"] is None:
            node["dn"] = node["nid"]

    ir = {
        "ir_version": ir_version,
        "snapshot_id": snapshot_id or new_uuid(),
        "project_id": project_id,
        "owner_sub": owner_sub,
        "label": label,
        "captured_at": captured,
        "derived_from": derived_from,
        "partial": partial,
        # 정본 소스 — mcad 가 없으면 dyna 다. ir_hash 입력이 아니라 조회·화면·게이트 분기 키다(§2.2).
        "primary_source": primary_source,
        "sources": sources,
        # 소스 밖 조직 문맥(§2.2). 소스 하위에 두면 dyna 부재 하나로 조직 집계까지 버려진다.
        # ir_hash 입력이 아니다 — compute_ir_hash 가 nodes·edges·same_as·dims_named 만 보는 허용목록이라 구조가 보장한다.
        "context": dict(context) if context else {"corpus_usage": None},
        "units": {"length": "mm", "area": "mm2", "volume": "mm3", "stress": "MPa", "accel": "G", "density": "as_in_file"},
        "nodes": sorted(nodes, key=lambda n: n["nid"]),
        "edges": sorted(edges, key=lambda e: e["eid"]),
        "same_as": sorted(same_as, key=lambda s: (s.get("a") or "", s.get("b") or "")),
        "dims_named": dims_named,
        "rollups": rollups,
        "results": results,
        "missing": missing,
        "warnings": sorted(warnings, key=lambda w: (w.get("code") or "", str(w.get("ref") or ""), w.get("message") or "")),
        "gates": {},
        "character_seed": [],
        "feature_vector": {},
        "ir_hash": "",
        "versions": stamp,
    }
    ir["ir_hash"] = compute_ir_hash(ir)
    return ir


# ---------------------------------------------------------------- 저장(plan §2.11.3 8단계·§2.11.4)
def resolve_ckey(store, ckey: str, *, owner_sub: str | None = None, max_hops: int = 5) -> str:
    """rr_part_keys.merged_into 체인을 따라 유효 ckey 를 돌려준다(plan §2.7.3, 체인 최대 5).

    owner_sub 를 주면 자기 원장만 본다 — ckey 는 내용 파생 키라 다른 사용자의 병합 체인이 내 노드 ckey 를
    갈아 끼우는 것을 막는다(sameas.resolve_ckey 와 같은 규칙).
    """
    current = ckey
    for _ in range(max_hops):
        sql = "SELECT status, merged_into FROM rr_part_keys WHERE ckey = ?"
        params: list[Any] = [current]
        if owner_sub:
            sql += " AND owner_sub = ?"
            params.append(owner_sub)
        row = store.query_one(sql, tuple(params))
        if row is None or row["status"] != "merged" or not row["merged_into"]:
            return current
        current = row["merged_into"]
    return current


def _upsert_part_keys(store, ir: Mapping[str, Any]) -> None:
    """노드가 쓴 ckey 를 rr_part_keys 원장에 candidate 로 적립하고 별칭·과제 수를 갱신한다(plan §2.7.3)."""
    now = now_epoch()
    project_id = ir["project_id"]
    owner_sub = ir["owner_sub"]
    for node in ir["nodes"]:
        ckey = node.get("ckey")
        if not ckey or node["nid"] != node.get("dn"):
            continue
        bucket = geom_bucket(_node_size_sorted(node), (node.get("attrs") or {}).get("volume"))
        # ckey 는 sha1(name_norm_canon|geom_bucket|material_norm) 이라 다른 사용자가 같은 표준 부품을 올리면
        # 악의 없이도 충돌한다 — 남의 사설 원장을 고치지 않도록 소유자까지 걸어 조회·갱신한다(plan §2.7.3).
        row = store.query_one(
            "SELECT ckey, aliases_json, first_project_id, n_projects, n_snapshots FROM rr_part_keys"
            " WHERE ckey = ? AND owner_sub = ?",
            (ckey, owner_sub),
        )
        alias = {
            "project_id": project_id, "domain": node["domain"], "label": node["label"],
            "local_key": node["local_key"], "name_norm": node["name_norm"],
        }
        if row is None:
            try:
                store.execute(
                    "INSERT INTO rr_part_keys (ckey, owner_sub, visibility, status, merged_into, display_name,"
                    " name_norm_canon, geom_bucket, material_norm, aliases_json, first_project_id, first_snapshot_id,"
                    " first_nid, n_projects, n_snapshots, created_by, created_at, updated_at)"
                    " VALUES (?,?,'private','candidate',NULL,NULL,?,?,?,?,?,?,?,1,1,?,?,?)",
                    (ckey, owner_sub, node["name_norm_canon"], bucket, _node_material(node),
                     canonical_json([alias]), project_id, ir["snapshot_id"], node["nid"], owner_sub, now, now),
                )
            except sqlite3.IntegrityError:
                # 같은 ckey 를 다른 사용자가 먼저 적립했다(PK 는 ckey 하나뿐) — 남의 행은 건드리지 않고 지나간다.
                pass
            continue
        aliases = json.loads(row["aliases_json"] or "[]")
        known_projects = {a.get("project_id") for a in aliases}
        if alias not in aliases:
            aliases.append(alias)
        n_projects = int(row["n_projects"] or 1) + (0 if project_id in known_projects else 1)
        store.execute(
            "UPDATE rr_part_keys SET aliases_json = ?, n_projects = ?, n_snapshots = ?, updated_at = ?"
            " WHERE ckey = ? AND owner_sub = ?",
            (canonical_json(sorted(aliases, key=canonical_json)), n_projects, int(row["n_snapshots"] or 1) + 1, now,
             ckey, owner_sub),
        )


def _corpus_aggregates(ir_context: Any) -> dict:
    """전사 집계에서 메타(`fetched_at`·`app_key`)를 뺀 실값만 남긴다.

    얼어 있는 값과 이번에 받은 값을 비교하는 기준이다 — `fetched_at` 은 부를 때마다 달라지므로
    그것까지 비교하면 '언제나 변했다' 가 되어 아무것도 못 알려 준다.
    """
    usage = (ir_context or {}).get("corpus_usage")
    if not isinstance(usage, Mapping):
        return {}
    return {k: v for k, v in usage.items() if k not in ("fetched_at", "app_key")}


def _corpus_fetched_at(ir_context: Any) -> int | None:
    usage = (ir_context or {}).get("corpus_usage")
    return int(usage["fetched_at"]) if isinstance(usage, Mapping) and usage.get("fetched_at") else None


def record_calls(store, snapshot_id: str | None, owner_sub: str, calls: Sequence[Mapping[str, Any]], *,
                 start_seq: int | None = None, job_id: str | None = None) -> list[str]:
    """소스 호출 원문을 rr_snapshot_calls 에 gzip 으로 남긴다(plan §2.11.4). call_id 목록을 순서대로 돌려준다.

    `call_id` 접두는 스냅샷이 아니라 **잡** id 다 — 실패한 잡에는 스냅샷이 없기 때문이다. 잡 오케스트레이션이
    아직 없는 동기 캡처 경로는 잡 하나가 곧 스냅샷 하나라 `job_id` 를 생략하고 `snapshot_id` 를 잡 식별자로 쓴다
    (`adapters.base.CallRecorder` 가 캡처 전에 매기는 call_id 와 같은 값이라 provenance.call_id 가 실제 행과 맞는다).
    """
    job = job_id or snapshot_id
    if start_seq is None:
        if snapshot_id is None:
            row = store.query_one("SELECT MAX(seq) AS m FROM rr_snapshot_calls WHERE job_id = ?", (job,))
        else:
            row = store.query_one(
                "SELECT MAX(seq) AS m FROM rr_snapshot_calls WHERE snapshot_id = ?", (snapshot_id,))
        start_seq = int(row["m"] or 0) + 1 if row else 1
    call_ids: list[str] = []
    rows = []
    for offset, call in enumerate(calls):
        seq = start_seq + offset
        call_id = f"{job[:8]}-{seq:03d}"
        response = call.get("response")
        if response is None:
            blob, sha, size = None, None, None
        else:
            text = response if isinstance(response, str) else canonical_json(response)
            data = text.encode("utf-8")
            blob, sha, size = gzip.compress(data), sha256_hex(data), len(data)
        args_json = canonical_json(call.get("args") or {})
        contract_ok = call.get("contract_ok")
        rows.append((
            call_id, job, snapshot_id, owner_sub, seq, str(call.get("source_kind") or "mcad"), call.get("app_key"),
            str(call.get("channel") or "mcp"), str(call.get("tool") or ""), args_json, sha256_hex(args_json),
            1 if call.get("ok", True) else 0, call.get("http_status"), sha, blob, size,
            None if contract_ok is None else (1 if contract_ok else 0),
            canonical_json(list(call.get("contract_missing") or ())) if call.get("contract_missing") else None,
            call.get("reused_from_call_id"),
            int(call.get("started_at") or now_epoch()), call.get("duration_ms"), call.get("error"),
        ))
        call_ids.append(call_id)
    if rows:
        store.executemany(
            "INSERT OR REPLACE INTO rr_snapshot_calls (call_id, job_id, snapshot_id, owner_sub, seq, source_kind,"
            " app_key, channel, tool, args_json, args_hash, ok, http_status, response_sha256, response_gz,"
            " response_bytes, contract_ok, contract_missing_json, reused_from_call_id, started_at,"
            " duration_ms, error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
    return call_ids


def load_calls(store, snapshot_id: str, *, include_response: bool = True) -> list[dict]:
    """rr_snapshot_calls 원문을 seq 순서로 돌려준다('재해석 적용' 이 소스 재호출 없이 6~9단계를 다시 도는 입력)."""
    rows = store.query(
        "SELECT call_id, snapshot_id, owner_sub, seq, source_kind, app_key, channel, tool, args_json, args_hash,"
        " ok, http_status, response_sha256, response_gz, response_bytes, started_at, duration_ms, error"
        " FROM rr_snapshot_calls WHERE snapshot_id = ? ORDER BY seq",
        (snapshot_id,),
    )
    out = []
    for row in rows:
        item = {
            "call_id": row["call_id"], "seq": row["seq"], "source_kind": row["source_kind"], "app_key": row["app_key"],
            "channel": row["channel"], "tool": row["tool"], "args": json.loads(row["args_json"] or "{}"),
            "ok": bool(row["ok"]), "http_status": row["http_status"], "response_sha256": row["response_sha256"],
            "response_bytes": row["response_bytes"], "started_at": row["started_at"],
            "duration_ms": row["duration_ms"], "error": row["error"],
        }
        if include_response and row["response_gz"] is not None:
            text = gzip.decompress(row["response_gz"]).decode("utf-8")
            try:
                item["response"] = json.loads(text)
            except json.JSONDecodeError:
                item["response"] = text
        out.append(item)
    return out


def load_ir(store, snapshot_id: str) -> dict:
    """동결된 rr_ir 원본을 돌려준다. 없으면 E404."""
    row = store.query_one("SELECT ir_json FROM rr_snapshots WHERE id = ?", (snapshot_id,))
    if row is None:
        raise AppError("E404", f"스냅샷을 찾을 수 없습니다 — {snapshot_id}.", http_status=404)
    return json.loads(row["ir_json"])


def _gates_summary(gates: Mapping[str, Any] | None) -> dict:
    """게이트별 pass 를 3값 그대로 싣는다 — null(검문할 입력이 없었다)은 null 이다(plan §2.12).

    `bool()` 로 접으면 검문하지 못한 게이트가 false 로 나가, 응답만 읽는 호출자가 없는 위반을 적는다
    (`sig:gates.summary` 가 같은 까닭으로 3값이 됐다 — state.compute_signals).
    """
    return {k: (None if v.get("pass") is None else bool(v.get("pass"))) for k, v in (gates or {}).items()}


def freeze_snapshot(
    store,
    *,
    project_id: str,
    owner_sub: str,
    label: str,
    adapter_results: Sequence[Mapping[str, Any]],
    calls: Sequence[Mapping[str, Any]] = (),
    derived_from: str | None = None,
    captured_at: int | None = None,
    project_codes: Sequence[str] = (),
    with_state: bool = True,
    job_id: str | None = None,
    **build_kwargs: Any,
) -> dict:
    """IR 을 조립해 동결한다(plan §2.11.3 8~9단계).

    `(project_id, ir_hash)` 가 이미 있으면 기존 스냅샷을 `reused=True` 로 돌려주고 이번 호출 로그만 덧붙인다.
    없으면 rr_snapshots + rr_ir_nodes/rr_ir_edges + rr_snapshot_calls 를 한 트랜잭션으로 넣고 rr_states 를 계산한다.
    어떤 경로도 rr_snapshots.ir_json 을 UPDATE 하지 않는다(스냅샷 불변, plan §2.1).
    """
    ledger = build_kwargs.pop("iface_ledger", None)
    if ledger is None:
        ledger = [dict(r) for r in store.query(
            "SELECT project_id, pair_key, kind_override, status, note, geom_fp_a, geom_fp_b, decided_by, decided_at"
            " FROM rr_iface_ledger WHERE project_id = ?", (project_id,),
        )]
    sameas_ledger = build_kwargs.pop("sameas_ledger", None)
    if sameas_ledger is None:
        from app import sameas as sameas_module  # noqa: PLC0415 — 순환 임포트를 피하려 지연 임포트한다.

        sameas_ledger = sameas_module.load_ledger(store, "intra", project_id, owner_sub)
    dim_defs = build_kwargs.pop("dim_defs", None)
    if dim_defs is None:
        dim_defs = [dict(r) for r in store.query(
            "SELECT project_id, name, owner_sub, extractor FROM rr_dim_defs WHERE project_id = ?", (project_id,),
        )]
    dim_vocab = build_kwargs.pop("dim_vocab", None)
    if dim_vocab is None:
        dim_vocab = {
            r["name"]: {"unit": r["unit"], "kind": r["kind"]}
            for r in store.query("SELECT name, unit, kind FROM rr_dim_vocab", ())
        }

    ir = build_ir(
        project_id=project_id,
        owner_sub=owner_sub,
        label=label,
        adapter_results=adapter_results,
        derived_from=derived_from,
        captured_at=captured_at,
        iface_ledger=ledger,
        sameas_ledger=sameas_ledger,
        dim_defs=dim_defs,
        dim_vocab=dim_vocab,
        project_codes=project_codes,
        resolve_ckey_fn=build_kwargs.pop("resolve_ckey_fn", None)
        or (lambda ck: resolve_ckey(store, ck, owner_sub=owner_sub)),
        **build_kwargs,
    )

    existing = store.query_one(
        "SELECT id FROM rr_snapshots WHERE project_id = ? AND ir_hash = ?", (project_id, ir["ir_hash"]),
    )
    if existing is not None:
        from app import state as state_module  # noqa: PLC0415 — 순환 임포트를 피하려 지연 임포트한다.

        snapshot_id = existing["id"]
        if calls:
            record_calls(store, snapshot_id, owner_sub, calls, job_id=job_id)
        frozen = load_ir(store, snapshot_id)
        return {
            "snapshot_id": snapshot_id, "ir_hash": ir["ir_hash"], "reused": True,
            "partial": bool(frozen.get("partial")),
            # 차단은 계획 식이다 — pass=false 뿐 아니라 unknown_blocking(pass=null·unit_unknown)도 차단이다(§2.12).
            "blocked": state_module.is_blocked(frozen.get("gates") or {}),
            "gates_summary": _gates_summary(frozen.get("gates")),
            "degraded": sorted({d for s in frozen.get("sources") or [] for d in s.get("degraded") or []}),
            # 전사 집계는 시변인데 스냅샷은 불변이다 — ir_json 을 갱신하지 않으므로(§2.1) 얼어 있는 값은
            # 첫 캡처 시점 값이다. 이번에 받은 값을 버리지 않고 함께 돌려주고, 언제 얼었는지와 달라졌는지를
            # 밖으로 낸다. 달라졌는지를 모르는 경우(이번 4호출이 전부 실패)는 False 가 아니라 None 이다.
            "context": dict(ir.get("context") or {}),
            "context_frozen_at": _corpus_fetched_at(frozen.get("context")),
            "context_changed": (None if not _corpus_aggregates(ir.get("context"))
                                else _corpus_aggregates(ir.get("context")) != _corpus_aggregates(frozen.get("context"))),
        }

    snapshot_id = ir["snapshot_id"]
    state: dict | None = None
    if with_state:
        from app import state as state_module  # noqa: PLC0415 — state 는 IR 을 읽으므로 조립 후에 부른다.

        state = state_module.build_state(ir)
        ir["gates"] = state["gates"]
        ir["character_seed"] = state["character_seed"]
        ir["feature_vector"] = state["feature_vector"]

    degraded = sorted({d for s in ir["sources"] for d in s.get("degraded") or []})
    with store.tx():
        store.execute(
            "INSERT INTO rr_snapshots (id, project_id, owner_sub, ir_version, ir_hash, ir_json, source_ids_json,"
            " kinds_json, node_count, edge_count, missing_json, warnings_n, degraded, degraded_json,"
            " app_versions_json, primary_source, adapter_versions_json, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                snapshot_id, project_id, owner_sub, ir["ir_version"], ir["ir_hash"], canonical_json(ir),
                canonical_json([
                    {"kind": s["kind"], "app_key": s.get("app_key"), "ref": s.get("ref"), "hash": s.get("source_hash"),
                     "adapter_version": s.get("adapter_version"), "tol_config_hash": s.get("tol_config_hash")}
                    for s in ir["sources"]
                ]),
                canonical_json([s["kind"] for s in ir["sources"]]),
                len(ir["nodes"]), len(ir["edges"]), canonical_json(ir["missing"]), len(ir["warnings"]),
                # degraded 는 호환 컬럼(첫 값)이고 배열은 degraded_json 이다(§2.2).
                (degraded[0] if degraded else None), canonical_json(list(degraded)),
                # 소스 앱 버전은 ir_hash 입력이 아니라 열로만 남는다 — pair 의 app_version_parity 가 본다.
                canonical_json({s["kind"]: (s.get("app_version") or {}) for s in ir["sources"]}),
                ir.get("primary_source"),
                canonical_json(ir["versions"]["adapter_versions"]), ir["captured_at"],
            ),
        )
        store.executemany(
            "INSERT INTO rr_ir_nodes (snapshot_id, nid, owner_sub, kind, source_kind, name, name_norm, ckey, dn,"
            " geom_fp, asm_key, material_norm, size_sorted_json, volume, attrs_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    snapshot_id, n["nid"], owner_sub, n["kind"], n["domain"], n["label"], n["name_norm"],
                    n.get("ckey"), n.get("dn"), n.get("geom_fp"), n.get("asm_key"), _node_material(n),
                    canonical_json(_node_size_sorted(n)), (n.get("attrs") or {}).get("volume"), canonical_json(n["attrs"]),
                )
                for n in ir["nodes"]
            ],
        )
        node_ck = {n["nid"]: n.get("ckey") for n in ir["nodes"]}
        store.executemany(
            "INSERT INTO rr_ir_edges (snapshot_id, eid, owner_sub, kind, kind_family, a, b, ck_a, ck_b, subject_key,"
            " status, attrs_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    snapshot_id, e["eid"], owner_sub, e["kind"], e["kind_family"], e["a"],
                    # scope 하이퍼엣지는 IR 에서 b=null 이지만 rr_ir_edges.b 는 NOT NULL 이라 빈 문자열로 눕힌다(정본은 ir_json).
                    e.get("b") or "",
                    node_ck.get(e["a"]), node_ck.get(e.get("b") or ""),
                    _subject_key(node_ck.get(e["a"]), node_ck.get(e.get("b") or "")),
                    e["status"], canonical_json(e["attrs"]),
                )
                for e in ir["edges"]
            ],
        )
        if calls:
            record_calls(store, snapshot_id, owner_sub, calls, start_seq=1, job_id=job_id)
        _upsert_part_keys(store, ir)
        if state is not None:
            from app import state as state_module  # noqa: PLC0415

            state_module.save_state(store, state, owner_sub=owner_sub)

    from app import state as blocked_module  # noqa: PLC0415 — 순환 임포트를 피하려 지연 임포트한다.

    gates = ir.get("gates") or {}
    return {
        "snapshot_id": snapshot_id,
        "ir_hash": ir["ir_hash"],
        "reused": False,
        "partial": bool(ir["partial"]),
        "blocked": blocked_module.is_blocked(gates),
        "gates_summary": _gates_summary(gates),
        "degraded": degraded,
        # 새로 언 스냅샷이라 얼어 있는 값이 곧 이번 값이다 — 재사용 분기와 키를 맞춘다.
        "context": dict(ir.get("context") or {}),
        "context_frozen_at": _corpus_fetched_at(ir.get("context")),
        "context_changed": False,
    }
