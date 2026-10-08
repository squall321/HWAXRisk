# IR 하나를 읽어 게이트 G1~G6·signals·character_seed·feature_vector·rule_hits 를 결정론으로 계산해 rr_states 에 저장한다(plan §3.2)
from __future__ import annotations

import json
import math
import re
from typing import Any, Mapping, Sequence

from app.common import canonical_json, now_epoch, sha256_hex
from app.errors import AppError
from app.taxonomy import load_json, version_of

__all__ = [
    "STATE_VERSION",
    "FEATURE_NAMES",
    "FEATURE_TRANSFORMS",
    "build_state",
    "compute_gates",
    "compute_signals",
    "compute_character_seed",
    "compute_feature_vector",
    "evaluate_rules",
    "load_seed_rules",
    "load_active_rules",
    "save_state",
    "load_state",
    "compute_state_for_snapshot",
]

STATE_VERSION = "1.0"

# feature_vector 22차원 고정 순서(plan §3.2.5). 순서·이름·변환은 state_version 이 바뀌어야 바뀐다.
FEATURE_NAMES: tuple[str, ...] = (
    "n_leaf", "n_files", "n_tied", "n_touching", "n_clearance", "n_interference",
    "orphan_ratio", "cross_file_ratio", "bbox_x", "bbox_y", "bbox_z", "total_volume",
    "n_materials", "material_null_ratio", "thin_ratio", "median_gap", "min_gap", "max_pen_depth",
    "n_dyna_pids", "n_dyna_contacts", "shell_ratio", "n_ecad_cmp",
)
FEATURE_TRANSFORMS: tuple[str, ...] = (
    "log1p", "log1p", "log1p", "log1p", "log1p", "log1p",
    "id", "id", "log1p", "log1p", "log1p", "log1p",
    "log1p", "id", "id", "log1p", "log1p", "log1p",
    "log1p", "log1p", "id", "log1p",
)

# 계면 kind 와 '닿음' kind(plan §2.9 — clearance 는 접촉이 아니다).
_IFACE_KINDS: tuple[str, ...] = ("tied", "touching", "clearance", "interference")
_TOUCHING_KINDS: frozenset[str] = frozenset({"tied", "touching", "interference", "geometric", "contact"})
_STATUS_FAMILIES: frozenset[str] = frozenset({"iface", "contact"})
_GAP_BINS: tuple[float, ...] = (0.0, 0.01, 0.05, 0.1, 0.2, 0.5)
_THIN_MM = 0.3
_COORD_WARNINGS: frozenset[str] = frozenset({"suspect_coordinate_systems", "files_all_overlap"})
_TOP_K = 10


# ---------------------------------------------------------------- render.py 위임(정규 표기·린터)
def _render():
    """render.py 가 붙어 있으면 그 모듈, 아니면 None. 정규 표기는 표시용이라 없으면 최소 표기로 대신한다."""
    try:
        from app import render  # noqa: PLC0415 — 선택 의존이라 지연 임포트한다.
    except ImportError:
        return None
    return render


def _text(key: str, record: Mapping[str, Any], fallback: str) -> str:
    render = _render()
    fn = getattr(render, "signal_text", None) if render else None
    if fn is None:
        return fallback
    return str(fn(key, record))


# ---------------------------------------------------------------- 작은 도구
def _rec(kind: str, value: Any, unit: str | None, refs: Sequence[str], text: str,
         derived_from: Sequence[str] = (), known: bool = True) -> dict:
    return {
        "kind": kind, "value": value, "unit": unit, "refs": list(refs),
        "text": text, "derived_from": list(derived_from), "known": bool(known),
    }


def _ratio(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return round(float(numerator) / float(denominator), 3)


def _num_key(value: Any) -> tuple:
    """None 을 항상 뒤로 보내는 정렬 키(오름차순 기준)."""
    return (value is None, value if value is not None else 0.0)


def _attr(item: Mapping[str, Any], name: str, default: Any = None) -> Any:
    return (item.get("attrs") or {}).get(name, default)


def _live_edges(ir: Mapping[str, Any]) -> list[dict]:
    return [e for e in ir.get("edges") or [] if e.get("status") != "rejected"]


def _leaves(ir: Mapping[str, Any]) -> list[dict]:
    return [n for n in ir.get("nodes") or [] if n.get("domain") == "mcad" and n.get("kind") == "part"]


def _diag(dims: Sequence[float] | None) -> float | None:
    if not dims or any(d is None for d in dims):
        return None
    return math.sqrt(sum(float(d) ** 2 for d in dims))


def _bbox_union(leaves: Sequence[Mapping[str, Any]]) -> list[float] | None:
    boxes = [_attr(n, "bbox_world") for n in leaves if _attr(n, "bbox_world")]
    boxes = [b for b in boxes if b and len(b) == 6 and all(v is not None for v in b)]
    if not boxes:
        return None
    lo = [min(float(b[i]) for b in boxes) for i in range(3)]
    hi = [max(float(b[i + 3]) for b in boxes) for i in range(3)]
    return [round(hi[i] - lo[i], 3) for i in range(3)]


def _source(ir: Mapping[str, Any], kind: str) -> dict | None:
    for source in ir.get("sources") or []:
        if source.get("kind") == kind:
            return source
    return None


def _gate_word(record: Mapping[str, Any]) -> str:
    """게이트 한 칸의 표기 — pass · n/a(사유) · fail(건수[, ack])(plan §2.12)."""
    if record.get("pass") is True:
        return "pass"
    if record.get("pass") is None:
        return "n/a(" + str(record.get("reason") or "unknown") + ")"
    ack = "ack 있음" if record.get("ack") or record.get("ack_by") else "ack 없음"
    return "fail(" + str(record.get("count")) + ", " + ack + ")"


def _rule_word(hit: Mapping[str, Any]) -> str:
    """규칙 한 칸의 표기 — pass · 평가 불가(사유) · fail(N건)(plan §3.2.6)."""
    if hit.get("evaluable") is False or hit.get("pass") is None:
        return "평가 불가(" + str(hit.get("not_evaluable_reason") or "unknown") + ")"
    if hit.get("pass"):
        return "pass"
    return "fail(" + str((hit.get("found") or {}).get("count")) + "건)"


def _names(ir_index: Mapping[str, Mapping[str, Any]], edge: Mapping[str, Any]) -> str:
    a = ir_index.get(edge.get("a") or "", {}).get("label") or edge.get("a") or ""
    b = ir_index.get(edge.get("b") or "", {}).get("label") or edge.get("b") or ""
    return f"{a}↔{b}"


# ---------------------------------------------------------------- 게이트 G1~G6(plan §2.12·§3.2.2)
# pass=null 의 사유는 이 5종뿐이다(plan §2.12 표). pass ∈ true|false 이면 reason 은 null 이다.
GATE_NULL_REASONS: tuple[str, ...] = (
    "mcad_absent", "capture_partial", "unit_only", "warnings_unavailable", "unit_unknown",
)
# G6 의 unknown_blocking — pass=null 이면서 차단을 유지하는 유일한 사유(plan §2.12).
UNKNOWN_BLOCKING_REASON = "unit_unknown"


def is_blocked(gates: Mapping[str, Any] | None) -> bool:
    """`blocked = (G6.pass is False) or (G6.pass is None and G6.reason == 'unit_unknown')`(plan §2.12)."""
    g6 = (gates or {}).get("G6") or {}
    if not isinstance(g6, Mapping):
        return False
    if g6.get("pass") is False:
        return True
    return g6.get("pass") is None and g6.get("reason") == UNKNOWN_BLOCKING_REASON


def gates_hash(gates: Mapping[str, Any] | None) -> str:
    """게이트 판정만의 지문(ack 3필드 제외, sha256[:12]). ack 로는 안 바뀌고 판정이 재계산으로 바뀌면 바뀐다."""
    stripped = {
        key: {k: v for k, v in dict(record).items() if k not in ("ack_by", "ack_at", "ack_reason")}
        for key, record in sorted((gates or {}).items()) if isinstance(record, Mapping)
    }
    return sha256_hex(canonical_json(stripped))[:12]


def blocked_reason(gates: Mapping[str, Any] | None) -> str | None:
    """차단 사유 — `unit_mismatch`(pass=false) 또는 `unit_unknown`(unknown_blocking). 차단이 아니면 None."""
    g6 = (gates or {}).get("G6") or {}
    if not isinstance(g6, Mapping):
        return None
    if g6.get("pass") is False:
        return "unit_mismatch"
    if g6.get("pass") is None and g6.get("reason") == UNKNOWN_BLOCKING_REASON:
        return UNKNOWN_BLOCKING_REASON
    return None


def compute_gates(ir: Mapping[str, Any], *, acks: Mapping[str, Mapping[str, Any]] | None = None) -> dict:
    """게이트 6종을 IR 필드에서 직접 계산한다. blocking 은 G6 뿐이고 ack 가 붙어도 pass 는 false 로 남는다.

    `pass` 는 3값(true|false|null)이고 null 은 '검문할 입력이 통째로 없다' 이며 `reason` 에 사유를 적는다 —
    pass 로 세지 않는다(plan §2.12 '입력이 없을 때의 pass=null').
    """
    acks = dict(acks or {})
    leaves = _leaves(ir)
    edges = _live_edges(ir)
    warnings = list(ir.get("warnings") or [])
    n_leaf = len(leaves)
    missing = dict(ir.get("missing") or {})
    mcad_source = _source(ir, "mcad")
    mcad_degraded = set((mcad_source or {}).get("degraded") or ())
    all_degraded = {code for s in ir.get("sources") or [] for code in (s.get("degraded") or ())}
    mcad_absent = bool(missing.get("mcad_absent")) or mcad_source is None
    capture_partial = bool(missing.get("iface_kinds_absent")) or "capture_partial" in all_degraded
    # tree.warnings 는 REST 전용이라 mcp_degraded 면 입력이 0 이다 — 0 건을 '경고 없음' 으로 읽지 않는다(§2.12).
    warnings_unavailable = (not mcad_absent) and "mcp_degraded" in mcad_degraded

    def gate(key: str, count: int | None, threshold: float | None, passed: bool | None, effect: str,
             detail: Sequence[Any], blocking: bool = False, reason: str | None = None) -> dict:
        ack = acks.get(key) or {}
        value = None if passed is None else bool(passed)
        return {
            "key": key, "count": count, "threshold": threshold, "pass": value,
            "reason": reason if value is None else None,
            "blocking": bool(blocking), "effect": "none" if value is True else effect,
            "ack_by": ack.get("by"), "ack_at": ack.get("at"), "ack_reason": ack.get("reason"),
            "detail": list(detail),
        }

    anon = [n for n in leaves if {"auto_named", "duplicate_name"} & set(n.get("status_flags") or [])]
    g1_threshold = float(max(5, 0.10 * n_leaf))
    g1 = gate("dup_or_anon_names", len(anon), g1_threshold, len(anon) <= g1_threshold, "mark",
              [n["nid"] for n in anon[:_TOP_K]])

    pending = [s for s in ir.get("same_as") or [] if s.get("status") == "pending"]
    conflicts = [w for w in warnings if w.get("code") == "sameas_conflict"]
    g2_count = len(pending) + len(conflicts)
    g2 = gate("sameas_pending", g2_count, 0, g2_count == 0, "mark",
              [s.get("a") for s in pending[:_TOP_K]] + [w.get("ref") for w in conflicts[:_TOP_K]])

    unconfirmed = [e for e in edges if e.get("kind") == "interference" and e.get("status") == "auto"]
    # 간섭은 mcad 검출 산출이라 mcad 가 없거나 kind 가 통째로 빠지면 '없음' 이 아니라 '검문 불가' 다(§2.12).
    g3_reason = "mcad_absent" if mcad_absent else ("capture_partial" if capture_partial else None)
    g3 = gate("iface_unconfirmed", None if g3_reason else len(unconfirmed), 0,
              None if g3_reason else not unconfirmed, "mark",
              [] if g3_reason else [e["eid"] for e in unconfirmed[:_TOP_K]], reason=g3_reason)

    coord = [w for w in warnings if w.get("code") in _COORD_WARNINGS]
    g4_reason = "mcad_absent" if mcad_absent else ("warnings_unavailable" if warnings_unavailable else None)
    g4 = gate("coordinate", None if g4_reason else len(coord), 0,
              None if g4_reason else not coord, "degrade_cross_file",
              [] if g4_reason else [f"warn:{w.get('code')}#{w.get('ref')}" for w in coord[:_TOP_K]],
              reason=g4_reason)

    scoped = any(s.get("scope") is not None for s in ir.get("sources") or [])
    out_of_scope = [n for n in leaves if "scope_out" in (n.get("status_flags") or [])] if scoped else []
    g5 = gate("partial_scope", len(out_of_scope), 0, not out_of_scope, "mark_partial",
              [n["nid"] for n in out_of_scope[:_TOP_K]])

    g6_count = 0
    g6_detail: list[Any] = []
    mcad = mcad_source or {}
    dyna = _source(ir, "dyna")
    ecad = _source(ir, "ecad")
    # (a) tree.warnings unit_mismatch·(b) mcad unit_system 은 둘 다 mcad REST 전용 입력이다.
    for w in warnings:
        if w.get("code") == "unit_mismatch":
            g6_count += 1
            g6_detail.append(f"warn:unit_mismatch#{w.get('ref')}")
    if not mcad_absent:
        unit_system = (mcad.get("ref") or {}).get("unit_system")
        if unit_system is not None and str(unit_system) != "mm":
            g6_count += 1
            g6_detail.append(f"unit_system={unit_system}")
        # (c) dyna↔mcad 대각비는 mcad 가 있을 때만 계산한다. 계산 불가면 unknown 이고 계수 0 이다.
        dyna_diag = _diag(((dyna or {}).get("stats") or {}).get("size"))
        mcad_diag = _diag(_bbox_union(leaves))
        if dyna_diag and mcad_diag:
            ratio = dyna_diag / mcad_diag
            if not (0.95 <= ratio <= 1.05):
                g6_count += 1
                g6_detail.append(f"dyna/mcad 대각비 {round(ratio, 3)}")
    if "unit_conversion_failed" in ((ecad or {}).get("degraded") or []):
        g6_count += 1
        g6_detail.append("ecad unit_conversion_failed")

    g6_reason: str | None = None
    if warnings_unavailable:
        # mcad 는 있는데 REST /tree 를 못 읽었다 — (a)·(b) 입력이 통째로 없다. 차단은 유지한다(unknown_blocking).
        g6_reason = UNKNOWN_BLOCKING_REASON
    elif mcad_absent and dyna is None and ecad is None:
        # dyna·ecad 단위 검문 입력조차 없다 — 검문 대상 자체가 없다.
        g6_reason = "unit_only"
    g6 = gate("unit_scale", None if g6_reason else g6_count, 0,
              None if g6_reason else g6_count == 0, "block",
              [] if g6_reason else g6_detail, blocking=True, reason=g6_reason)

    return {"G1": g1, "G2": g2, "G3": g3, "G4": g4, "G5": g5, "G6": g6}


# ---------------------------------------------------------------- signals(plan §3.2.3)
def compute_signals(ir: Mapping[str, Any], gates: Mapping[str, Mapping[str, Any]]) -> dict:
    """단일 과제 서술의 인용 단위 `sig:<key>` 를 IR 에서 결정론으로 만든다. 값이 없으면 known=false 이고 0 이 아니다."""
    nodes = list(ir.get("nodes") or [])
    index = {n["nid"]: n for n in nodes}
    edges = _live_edges(ir)
    leaves = _leaves(ir)
    missing = dict(ir.get("missing") or {})
    signals: dict[str, dict] = {}

    def put(key: str, record: dict) -> None:
        record["text"] = _text(key, record, record["text"])
        signals[key] = record

    # --- counts
    files = [n for n in nodes if n.get("domain") == "mcad" and n.get("kind") == "file"]
    assemblies = [n for n in nodes if n.get("domain") == "mcad" and n.get("kind") == "assembly"]
    n_leaf = len(leaves)
    put("counts.files", _rec("count", len(files), None, [], f"files={len(files)}"))
    put("counts.leaf", _rec("count", n_leaf, None, [], f"leaf={n_leaf}"))
    put("counts.assemblies", _rec("count", len(assemblies), None, [], f"assemblies={len(assemblies)}"))

    by_kind = {k: [e for e in edges if e.get("kind") == k] for k in _IFACE_KINDS}
    for kind in _IFACE_KINDS:
        put(f"counts.edges.{kind}", _rec("count", len(by_kind[kind]), None, [], f"{kind}={len(by_kind[kind])}"))

    status_edges = [e for e in edges if e.get("kind_family") in _STATUS_FAMILIES]
    put("counts.edges.total", _rec("count", len(status_edges), None, [], f"edges={len(status_edges)}"))
    for status in ("auto", "confirmed", "manual", "manual_ledger"):
        n = sum(1 for e in status_edges if e.get("status") == status)
        put(f"counts.edges.status.{status}", _rec("count", n, None, [], f"status={status} {n}"))

    orphan_total = sum(int(r.get("orphan_leaf") or 0) for r in (ir.get("rollups") or {}).get("by_assembly") or [] if int(r.get("depth") or 0) == 1)
    touching_nids = {x for e in edges if e.get("kind") in _TOUCHING_KINDS for x in [e.get("a"), e.get("b"), *(e.get("members") or [])] if x}
    orphan_nodes = [n for n in leaves if n["nid"] not in touching_nids]
    if not orphan_total:
        orphan_total = len(orphan_nodes)
    put("counts.orphans", _rec("count", orphan_total, None, [n["nid"] for n in orphan_nodes[:_TOP_K]], f"orphans={orphan_total}"))

    cross_file_edges = [e for e in edges if _attr(e, "cross_file")]
    put("counts.cross_file", _rec("count", len(cross_file_edges), None, [], f"cross_file={len(cross_file_edges)}"))

    auto_named = [n for n in leaves if "auto_named" in (n.get("status_flags") or [])]
    duplicate = [n for n in leaves if "duplicate_name" in (n.get("status_flags") or [])]
    put("counts.auto_named", _rec("count", len(auto_named), None, [n["nid"] for n in auto_named[:_TOP_K]], f"auto_named={len(auto_named)}"))
    put("counts.duplicate_names", _rec("count", len(duplicate), None, [n["nid"] for n in duplicate[:_TOP_K]], f"duplicate_names={len(duplicate)}"))

    materials = [(_attr(n, "material") or "").strip().lower() for n in leaves]
    distinct = sorted({m for m in materials if m})
    material_null = sum(1 for m in materials if not m)
    put("counts.materials_distinct", _rec("count", len(distinct), None, [], f"materials_distinct={len(distinct)}"))
    put("counts.material_null", _rec("count", material_null, None, [], f"material_null={material_null}"))

    dyna_known = not missing.get("dyna_absent", True)
    dyna_pids = [n for n in nodes if n.get("domain") == "dyna" and n.get("kind") == "pid"]
    contacts_by_type: dict[str, int] = {}
    for e in edges:
        if e.get("kind") == "contact":
            key = str(_attr(e, "contact_type") or "unknown")
            contacts_by_type[key] = contacts_by_type.get(key, 0) + 1
    single_surface = sum(1 for e in edges if e.get("kind") == "scope")
    put("counts.dyna.pids", _rec("count", len(dyna_pids) if dyna_known else None, None, [],
                                 f"dyna pid={len(dyna_pids)}" if dyna_known else "dyna absent", known=dyna_known))
    put("counts.dyna.contacts_by_type", _rec("table", dict(sorted(contacts_by_type.items())) if dyna_known else None, None, [],
                                             canonical_json(dict(sorted(contacts_by_type.items()))) if dyna_known else "dyna absent",
                                             known=dyna_known))
    put("counts.dyna.single_surface", _rec("count", single_surface if dyna_known else None, None, [],
                                           f"single_surface={single_surface}" if dyna_known else "dyna absent", known=dyna_known))

    ecad_known = not missing.get("ecad_absent", True)
    components = [n for n in nodes if n.get("domain") == "ecad" and n.get("kind") == "component"]
    nets = [n for n in nodes if n.get("domain") == "ecad" and n.get("kind") == "net"]
    put("counts.ecad.components", _rec("count", len(components) if ecad_known else None, None, [],
                                       f"components={len(components)}" if ecad_known else "ecad absent", known=ecad_known))
    put("counts.ecad.nets", _rec("count", len(nets) if ecad_known else None, None, [],
                                 f"nets={len(nets)}" if ecad_known else "ecad absent", known=ecad_known))

    # --- ratios
    iface_total = sum(len(by_kind[k]) for k in _IFACE_KINDS)
    tied_ratio = _ratio(len(by_kind["tied"]), iface_total)
    put("ratios.tied_ratio", _rec("ratio", tied_ratio, None, [],
                                  f"tied_ratio={tied_ratio} (tied {len(by_kind['tied'])} / {iface_total})" if tied_ratio is not None else "tied_ratio 미측정",
                                  known=tied_ratio is not None))
    for key, num, den, label in (
        ("ratios.orphan_ratio", orphan_total, n_leaf, "orphan_ratio"),
        ("ratios.unconfirmed_ratio", sum(1 for e in status_edges if e.get("status") == "auto"), len(status_edges), "unconfirmed_ratio"),
        ("ratios.cross_file_ratio", len(cross_file_edges), len(status_edges), "cross_file_ratio"),
        ("ratios.auto_named_ratio", len(auto_named), n_leaf, "auto_named_ratio"),
        ("ratios.material_null_ratio", material_null, n_leaf, "material_null_ratio"),
    ):
        value = _ratio(num, den)
        put(key, _rec("ratio", value, None, [], f"{label}={value} ({num} / {den})" if value is not None else f"{label} 미측정",
                      known=value is not None))

    thin = [n for n in leaves if _attr(n, "min_dim") is not None and float(_attr(n, "min_dim")) < _THIN_MM]
    thin_ratio = _ratio(len(thin), n_leaf)
    put("ratios.thin_ratio", _rec("ratio", thin_ratio, None, [n["nid"] for n in thin[:_TOP_K]],
                                  f"thin_ratio={thin_ratio} (min_dim 근사, < {_THIN_MM} mm {len(thin)} / {n_leaf})" if thin_ratio is not None else "thin_ratio 미측정",
                                  known=thin_ratio is not None))

    dyna_all = [n for n in nodes if n.get("domain") == "dyna"]
    mapped = sum(1 for n in dyna_all if index.get(n.get("dn") or "", {}).get("domain") == "mcad")
    coverage = _ratio(mapped, len(dyna_all)) if dyna_known else None
    put("ratios.sameas_coverage", _rec("ratio", coverage, None, [],
                                       f"sameas_coverage={coverage} ({mapped} / {len(dyna_all)})" if coverage is not None else "dyna absent",
                                       known=dyna_known and coverage is not None))

    # --- scale
    bbox = _bbox_union(leaves)
    world_known = bbox is not None and not missing.get("world_transform_absent", False)
    put("scale.bbox_world", _rec("vec", bbox, "mm", [],
                                 f"bbox_world={bbox} mm" if world_known else "bbox_world 미측정(world_transform 없음)",
                                 known=world_known))
    diag = _diag(bbox) if world_known else None
    put("scale.diag", _rec("scalar", round(diag, 3) if diag is not None else None, "mm", [],
                           f"diag={round(diag, 3)} mm" if diag is not None else "diag 미측정", known=diag is not None))
    volumes = [float(_attr(n, "volume")) for n in leaves if _attr(n, "volume") is not None]
    volume_known = bool(volumes) and not missing.get("volume_null", False)
    total_volume = round(sum(volumes), 4) if volume_known else None
    put("scale.total_volume", _rec("scalar", total_volume, "mm3", [],
                                   f"total_volume={total_volume} mm³" if volume_known else "total_volume 미측정", known=volume_known))

    unsourced = [n for n in leaves if _attr(n, "density") is None or not _attr(n, "density_unit")]
    mass_known = bool(leaves) and not unsourced and volume_known
    mass = round(sum(float(_attr(n, "density")) * float(_attr(n, "volume")) for n in leaves), 4) if mass_known else None
    put("scale.mass_est", _rec("scalar", mass, "density_unit·mm3", [],
                               f"mass_est={mass}" if mass_known else f"mass_est=미측정 (밀도 출처 없음 {len(unsourced)}건)",
                               known=mass_known))

    # --- top 표(G4 fail 이면 cross_file 엣지를 제외한다 — plan §3.2.2 degrade_cross_file)
    drop_cross_file = gates.get("G4", {}).get("pass") is False

    def edge_row(e: Mapping[str, Any]) -> dict:
        a, b = index.get(e.get("a") or "", {}), index.get(e.get("b") or "", {})
        return {
            "eid": e["eid"], "ckA": a.get("ckey"), "ckB": b.get("ckey"), "names": _names(index, e),
            "penetration_depth": _attr(e, "penetration_depth"),
            "lower_bound": bool(_attr(e, "penetration_depth_is_lower_bound", True)),
            "min_gap": _attr(e, "min_gap"), "contact_area_est": _attr(e, "contact_area_est"),
            "status": e.get("status"), "cross_file": bool(_attr(e, "cross_file")),
        }

    def top_edges(kind: str, attr: str, reverse: bool) -> list[dict]:
        picked = [e for e in by_kind.get(kind, []) if not (drop_cross_file and _attr(e, "cross_file"))]
        rows = [edge_row(e) for e in picked if _attr(e, attr) is not None]
        rows.sort(key=lambda r: (_num_key(r[attr]), r["eid"]), reverse=reverse)
        return rows[:_TOP_K]

    interference = top_edges("interference", "penetration_depth", True)
    put("top.interference", _rec("top", interference, "mm", [r["eid"] for r in interference],
                                 " · ".join(
                                     f"{r['names']} interference penetration_depth"
                                     f"{'≥' if r['lower_bound'] else '='}{r['penetration_depth']} mm"
                                     f"{'(lower_bound)' if r['lower_bound'] else ''}"
                                     f"{' status=auto(미확정 초안)' if r['status'] == 'auto' else ''} [e:{r['eid'][2:]}]"
                                     for r in interference) or "interference 없음"))
    tight = top_edges("clearance", "min_gap", False)
    put("top.tight_clearance", _rec("top", tight, "mm", [r["eid"] for r in tight],
                                    " · ".join(f"{r['names']} min_gap={r['min_gap']} mm [e:{r['eid'][2:]}]" for r in tight) or "clearance 없음"))
    band = top_edges("tied", "contact_area_est", True)
    put("top.tied_band_area", _rec("top", band, "mm2", [r["eid"] for r in band],
                                   " · ".join(f"{r['names']} contact_area_est={r['contact_area_est']} mm²(밴드면적) [e:{r['eid'][2:]}]" for r in band) or "tied 없음"))

    def top_nodes(attr: str, reverse: bool) -> list[dict]:
        rows = [
            {"nid": n["nid"], "name": n.get("label"), "ckey": n.get("ckey"), attr: _attr(n, attr)}
            for n in leaves if _attr(n, attr) is not None
        ]
        rows.sort(key=lambda r: (_num_key(r[attr]), r["nid"]), reverse=reverse)
        return rows[:_TOP_K]

    thin_parts = top_nodes("min_dim", False)
    put("top.thin_parts", _rec("top", thin_parts, "mm", [r["nid"] for r in thin_parts],
                               " · ".join(f"{r['name']} min_dim={r['min_dim']} mm [p:{r['nid'][2:]}]" for r in thin_parts) or "min_dim 미측정"))
    top_volume = top_nodes("volume", True)
    put("top.volume", _rec("top", top_volume, "mm3", [r["nid"] for r in top_volume],
                           " · ".join(f"{r['name']} volume={r['volume']} mm³ [p:{r['nid'][2:]}]" for r in top_volume) or "volume 미측정"))

    degree: dict[str, int] = {n["nid"]: 0 for n in leaves}
    for e in edges:
        if e.get("kind") == "clearance" or e.get("kind_family") not in _STATUS_FAMILIES:
            continue
        for nid in [e.get("a"), e.get("b"), *(e.get("members") or [])]:
            if nid in degree:
                degree[nid] += 1
    degree_rows = sorted(
        ({"nid": nid, "name": index[nid].get("label"), "degree": d} for nid, d in degree.items()),
        key=lambda r: (-r["degree"], r["nid"]),
    )[:_TOP_K]
    put("top.degree", _rec("top", degree_rows, None, [r["nid"] for r in degree_rows],
                           " · ".join(f"{r['name']} degree={r['degree']} [p:{r['nid'][2:]}]" for r in degree_rows) or "리프 없음"))

    # --- hist
    gaps = [float(_attr(e, "min_gap")) for e in edges
            if e.get("kind") in ("clearance", "touching", "tied") and _attr(e, "min_gap") is not None]
    counts = [0] * (len(_GAP_BINS) + 1)
    for gap in gaps:
        placed = False
        for i in range(len(_GAP_BINS) - 1):
            if _GAP_BINS[i] <= gap < _GAP_BINS[i + 1]:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1 if gap >= _GAP_BINS[-1] else 0] += 1
    hist = {"bins": list(_GAP_BINS), "counts": counts, "n": len(gaps)}
    put("hist.gap_mm", _rec("hist", hist, "mm", [], f"gap_mm bins={list(_GAP_BINS)} counts={counts}", known=bool(gaps)))

    degree_hist = {"0": 0, "1": 0, "2": 0, "3": 0, "4+": 0}
    for d in degree.values():
        degree_hist["4+" if d >= 4 else str(d)] += 1
    put("hist.degree", _rec("hist", degree_hist, None, [], f"degree {canonical_json(degree_hist)}"))

    # --- rollup · results · warnings · dims · gates
    rollup_rows = [dict(r, asm_key=r.get("path_prefix")) for r in (ir.get("rollups") or {}).get("by_assembly") or []]
    put("rollup.by_assembly", _rec("table", rollup_rows, None, [], f"by_assembly {len(rollup_rows)}행"))

    results = ir.get("results")
    if results:
        report_refs = [f"dyna:rpt:{rid}" for rid in results.get("report_ids") or []]
        part_risk = sorted(
            (dict(r) for r in results.get("part_risk") or []),
            key=lambda r: (_num_key((r.get("worst_stress") or {}).get("value")), str(r.get("pid"))),
            reverse=True,
        )[:_TOP_K]
        put("results.part_risk_top", _rec("top", part_risk, "MPa", [r.get("nid") for r in part_risk if r.get("nid")] + report_refs,
                                          " · ".join(
                                              f"pid {r.get('pid')} worst_stress={(r.get('worst_stress') or {}).get('value')} MPa"
                                              for r in part_risk) or "part_risk 없음"))
        findings = [dict(f) for f in results.get("findings") or []]
        put("results.findings", _rec("table", findings, None, report_refs,
                                     " · ".join(f"«{f.get('title')}»" for f in findings) or "findings 없음"))
        energy = sorted(
            (dict(e) for e in results.get("energy_edges") or []),
            key=lambda e: (_num_key(e.get("total_work")), str(e.get("name"))), reverse=True,
        )[:_TOP_K]
        put("results.load_path_top", _rec("top", energy, None, report_refs,
                                          " · ".join(f"{e.get('name')} total_work={e.get('total_work')}" for e in energy) or "energy_edges 없음"))
        yield_stress = ((results.get("sim_params") or {}).get("yield_stress"))
        if yield_stress:
            over = sorted(
                (
                    {"nid": r.get("nid"), "pid": r.get("pid"),
                     "ratio": round(float((r.get("worst_stress") or {}).get("value")) / float(yield_stress), 3)}
                    for r in results.get("part_risk") or []
                    if (r.get("worst_stress") or {}).get("value") is not None
                ),
                key=lambda r: (-r["ratio"], str(r["pid"])),
            )[:_TOP_K]
            put("results.over_yield", _rec("top", over, None, [r["nid"] for r in over if r.get("nid")],
                                           " · ".join(f"pid {r['pid']} worst_stress/yield={r['ratio']}" for r in over) or "over_yield 없음"))
        else:
            put("results.over_yield", _rec("top", None, None, [], "yield_stress 미기재로 미측정", known=False))
    else:
        for key in ("results.part_risk_top", "results.findings", "results.load_path_top", "results.over_yield"):
            put(key, _rec("table", None, None, [], "결과 리포트 없음", known=False))

    by_code: dict[str, dict] = {}
    for w in ir.get("warnings") or []:
        code = str(w.get("code"))
        row = by_code.setdefault(code, {"n": 0, "first": f"«{w.get('message')}»", "severity": w.get("severity")})
        row["n"] += 1
    put("warnings.by_code", _rec("table", dict(sorted(by_code.items())), None,
                                 [f"warn:{w.get('code')}#{w.get('ref')}" for w in (ir.get("warnings") or [])[:_TOP_K]],
                                 " · ".join(f"{code} {row['n']}건" for code, row in sorted(by_code.items())) or "warnings 없음"))

    dims = [dict(d) for d in ir.get("dims_named") or []]
    put("dims_named", _rec("table", dims, None, [f"d:{d['name']}" for d in dims],
                           " · ".join(
                               f"{d['name']}={d['value'] if d['value'] is not None else '미측정'}"
                               f"{(' ' + d['unit']) if d['value'] is not None else ''}"
                               for d in dims) or "dims_named 없음"))

    # pass 는 3값 그대로 싣는다 — `bool()` 로 접으면 검문하지 못한 게이트(null)가 false 가 되어 표기까지
    # `fail(None, ack 없음)` 으로 나갔다. 표기는 사유(`n/a(<reason>)`)가 있는 게이트 원본에서 만든다(plan §2.12).
    summary = {
        key: {"pass": None if g["pass"] is None else bool(g["pass"]), "count": g["count"],
              "ack": bool(g.get("ack_by"))}
        for key, g in sorted(gates.items())
    }
    put("gates.summary", _rec("table", summary, None, [f"gate:{k}" for k in sorted(gates)],
                              " · ".join(f"{k} {_gate_word(g)}" for k, g in sorted(gates.items()))))
    return signals


# ---------------------------------------------------------------- character_seed(plan §3.2.4)
def _dsl_value(ref: str, signals: Mapping[str, Any], gates: Mapping[str, Any], ir: Mapping[str, Any]) -> Any:
    if ref.startswith("sig:"):
        record = signals.get(ref[4:])
        return record.get("value") if record else None
    if ref.startswith("gate:"):
        key, _, field = ref[5:].partition(".")
        gate = gates.get(key) or {}
        return gate.get(field or "pass")
    if ref.startswith("missing."):
        return (ir.get("missing") or {}).get(ref[len("missing."):])
    return None


def _cmp(value: Any, op: str, expected: Any) -> bool:
    if op == "exists":
        return value is not None
    if value is None:
        return False
    if op == "eq":
        return value == expected
    if op == "ne":
        return value != expected
    if op == "in":
        return value in (expected or [])
    if op == "between":
        low, high = expected
        return float(low) <= float(value) <= float(high)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if op == "gte":
        return float(value) >= float(expected)
    if op == "lte":
        return float(value) <= float(expected)
    raise AppError("E100", f"모르는 조건 연산자 — {op!r}.", http_status=400)


def compute_character_seed(ir: Mapping[str, Any], signals: Mapping[str, Any], gates: Mapping[str, Any]) -> list[dict]:
    """결정론 성격 씨앗(assets/character-seed-rules.v1.json). 축 char:philosophy 는 씨앗이 내지 않는다."""
    doc = load_json("character-seed-rules")
    index = {n["nid"]: n for n in ir.get("nodes") or []}
    leaves = _leaves(ir)
    edges = _live_edges(ir)
    seeds: list[dict] = []

    def value(key: str) -> Any:
        record = signals.get(key)
        return record.get("value") if record else None

    for rule in doc.get("rules") or []:
        if rule.get("scope") != "snap":
            continue
        rule_id = rule.get("rule")
        tag = rule.get("tag")
        dsl = rule.get("dsl")
        cites = list(rule.get("cites") or [])

        if dsl:
            all_ok = all(_cmp(_dsl_value(c["ref"], signals, gates, ir), c["op"], c.get("value")) for c in dsl.get("all") or [])
            any_conds = dsl.get("any") or []
            any_ok = (not any_conds) or any(_cmp(_dsl_value(c["ref"], signals, gates, ir), c["op"], c.get("value")) for c in any_conds)
            if all_ok and any_ok:
                text = " ".join(
                    f"{c['ref']}={_dsl_value(c['ref'], signals, gates, ir)}" for c in dsl.get("all") or []
                ) or rule.get("condition") or ""
                seeds.append({"tag": tag, "rule": rule_id, "cites": cites, "text": text})
            continue

        if rule_id == "seed.structure.fastener_dense":
            pattern = re.compile(rule.get("pattern") or "")
            hits = [n for n in leaves if pattern.search(n.get("name_norm") or "")]
            if leaves and len(hits) >= float(rule.get("ratio_gte") or 0) * len(leaves):
                seeds.append({"tag": tag, "rule": rule_id,
                              "cites": ["sig:counts.leaf"] + [n["nid"] for n in hits[:_TOP_K]],
                              "text": f"체결 부품 {len(hits)} / leaf {len(leaves)}"})
        elif rule_id == "seed.structure.adhesive_dependent":
            pattern = re.compile(rule.get("pattern") or "")
            hits = {n["nid"] for n in leaves if pattern.search(n.get("name_norm") or "")}
            tied = [e for e in edges if e.get("kind") == "tied"]
            touched = [e for e in tied if e.get("a") in hits or e.get("b") in hits]
            if hits and tied and len(touched) >= float(rule.get("tied_ratio_gte") or 0) * len(tied):
                seeds.append({"tag": tag, "rule": rule_id, "cites": [e["eid"] for e in touched[:_TOP_K]],
                              "text": f"접착 리프 {len(hits)} · 관련 tied {len(touched)} / tied {len(tied)}"})
        elif rule_id == "seed.structure.rigid_frame_load_path":
            degree_rows = value("top.degree") or []
            volume_rows = (value("top.volume") or [])[: int(rule.get("volume_top_k") or 3)]
            top_volume_nids = {r["nid"] for r in volume_rows}
            threshold = float(rule.get("degree_ratio_gte") or 0) * len(leaves)
            for row in degree_rows:
                if row["degree"] >= threshold and row["nid"] in top_volume_nids and leaves:
                    seeds.append({"tag": tag, "rule": rule_id, "cites": [row["nid"]],
                                  "text": f"{row['name']} degree={row['degree']} / leaf {len(leaves)}"})
                    break
        elif rule_id == "seed.interface.top_interference":
            # 별칭 원장(rr_iface_alias)이 붙기 전까지 alias 는 양끝 name_norm 을 정렬해 잇는다(plan §3.2.4).
            for row in (value("top.interference") or [])[: int(rule.get("top_k") or 3)]:
                edge = next((e for e in edges if e["eid"] == row["eid"]), None)
                if edge is None:
                    continue
                name_a = index.get(edge.get("a") or "", {}).get("name_norm") or "x"
                name_b = index.get(edge.get("b") or "", {}).get("name_norm") or "x"
                alias = "_".join(sorted([name_a, name_b]))
                seeds.append({"tag": f"char:interface:{alias}", "rule": rule_id, "cites": [row["eid"]],
                              "text": f"{row['names']} penetration_depth={row['penetration_depth']} mm"})
        elif rule_id in ("seed.tolerance.tight", "seed.tolerance.loose", "seed.tolerance.moderate"):
            clearance = [e for e in edges if e.get("kind") == "clearance" and _attr(e, "min_gap") is not None]
            if not clearance:
                continue
            tight_n = sum(1 for e in clearance if float(_attr(e, "min_gap")) <= 0.1)
            loose_n = sum(1 for e in clearance if float(_attr(e, "min_gap")) >= 0.3)
            is_tight = tight_n / len(clearance) >= 0.3
            is_loose = loose_n / len(clearance) >= 0.5
            if rule_id == "seed.tolerance.tight" and is_tight:
                seeds.append({"tag": tag, "rule": rule_id, "cites": ["sig:hist.gap_mm"],
                              "text": f"min_gap≤0.1 mm {tight_n} / clearance {len(clearance)}"})
            elif rule_id == "seed.tolerance.loose" and is_loose:
                seeds.append({"tag": tag, "rule": rule_id, "cites": ["sig:hist.gap_mm"],
                              "text": f"min_gap≥0.3 mm {loose_n} / clearance {len(clearance)}"})
            elif rule_id == "seed.tolerance.moderate" and not is_tight and not is_loose and len(clearance) >= int(rule.get("clearance_gte") or 3):
                seeds.append({"tag": tag, "rule": rule_id, "cites": ["sig:hist.gap_mm"],
                              "text": f"clearance {len(clearance)}건, tight·loose 조건 미충족"})
    return seeds


# ---------------------------------------------------------------- feature_vector(plan §3.2.5)
def compute_feature_vector(ir: Mapping[str, Any], signals: Mapping[str, Any]) -> dict:
    """22차원 고정 순서 벡터. known=false 차원은 거리 계산에서 마스킹되므로 값은 null 이다."""
    def sig(key: str) -> tuple[Any, bool]:
        record = signals.get(key)
        if record is None:
            return None, False
        return record.get("value"), bool(record.get("known"))

    missing = dict(ir.get("missing") or {})
    n_leaf, _ = sig("counts.leaf")
    tight = (signals.get("top.tight_clearance") or {}).get("value") or []
    interference = (signals.get("top.interference") or {}).get("value") or []
    dyna_absent = bool(missing.get("dyna_absent", True))
    dyna_pids = [n for n in ir.get("nodes") or [] if n.get("domain") == "dyna" and n.get("kind") == "pid"]

    gaps: list[float] = []
    for e in _live_edges(ir):
        if e.get("kind") in ("clearance", "touching", "tied") and _attr(e, "min_gap") is not None:
            gaps.append(float(_attr(e, "min_gap")))
    median_gap = None
    if gaps:
        ordered = sorted(gaps)
        mid = len(ordered) // 2
        median_gap = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0

    contacts_by_type, _ = sig("counts.dyna.contacts_by_type")
    shell = sum(1 for n in dyna_pids if _attr(n, "elem_class") == "shell")

    raw: list[tuple[Any, bool]] = [
        (n_leaf, True),
        sig("counts.files"),
        sig("counts.edges.tied"),
        sig("counts.edges.touching"),
        sig("counts.edges.clearance"),
        sig("counts.edges.interference"),
        sig("ratios.orphan_ratio"),
        sig("ratios.cross_file_ratio"),
        ((signals.get("scale.bbox_world") or {}).get("value") or [None, None, None])[0],
        ((signals.get("scale.bbox_world") or {}).get("value") or [None, None, None])[1],
        ((signals.get("scale.bbox_world") or {}).get("value") or [None, None, None])[2],
        sig("scale.total_volume"),
        sig("counts.materials_distinct"),
        sig("ratios.material_null_ratio"),
        sig("ratios.thin_ratio"),
        (median_gap, bool(gaps)),
        ((tight[0]["min_gap"] if tight else None), bool(tight)),
        ((interference[0]["penetration_depth"] if interference else None), bool(interference)),
        ((len(dyna_pids) if not dyna_absent else None), not dyna_absent),
        ((sum((contacts_by_type or {}).values()) if not dyna_absent else None), not dyna_absent),
        ((round(shell / len(dyna_pids), 3) if dyna_pids else None), (not dyna_absent) and bool(dyna_pids)),
        sig("counts.ecad.components"),
    ]
    # bbox 3축은 튜플이 아니라 원값이 들어오므로 known 을 봉투 플래그로 맞춘다.
    world_known = bool((signals.get("scale.bbox_world") or {}).get("known"))
    for i in (8, 9, 10):
        raw[i] = (raw[i], world_known)

    values: list[Any] = []
    known: list[bool] = []
    for (value, is_known), transform in zip(raw, FEATURE_TRANSFORMS):
        if not is_known or value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            values.append(None)
            known.append(False)
            continue
        v = float(value)
        values.append(round(math.log1p(v), 6) if transform == "log1p" and v >= 0 else round(v, 6))
        known.append(True)
    return {"version": "fv-1.0", "names": list(FEATURE_NAMES), "values": values,
            "known": known, "transform": list(FEATURE_TRANSFORMS)}


# ---------------------------------------------------------------- rule_hits(plan §3.2.6)
def load_seed_rules() -> list[dict]:
    """assets/rules-seed.v1.json 의 시드 7종(사람이 손으로 쓴 규칙 — R-007 요구 여유 포함)."""
    doc = load_json("rules-seed")
    version = str(doc.get("version") or "rules-1.0")
    return [dict(r, rule_version=version) for r in doc.get("rules") or [] if r.get("status", "active") == "active"]


def load_active_rules(store) -> list[dict]:
    """rr_rules 의 active 규칙. 행이 없으면 시드 자산으로 돌아간다."""
    rows = store.query(
        "SELECT id, rule_version, condition_json, severity, why_it_matters, fix_hint, source, status"
        " FROM rr_rules WHERE status = 'active' ORDER BY id", (),
    )
    if not rows:
        return load_seed_rules()
    out = []
    for row in rows:
        condition = json.loads(row["condition_json"] or "{}")
        out.append({
            "id": row["id"], "name": row["id"], "severity": row["severity"], "status": row["status"],
            "rule_version": row["rule_version"],
            "condition_json": condition.get("condition_json", condition),
            "aggregate": condition.get("aggregate") or {"count_gte": 1},
            "why_it_matters": row["why_it_matters"], "fix_hint": row["fix_hint"] or "",
        })
    return out


def _derived_edge_ref(ir: Mapping[str, Any], edge: Mapping[str, Any], ref: str, mcad_kind_of: Mapping[str, str]) -> Any:
    if ref == "edge.kind":
        return edge.get("kind")
    if ref == "edge.status":
        return edge.get("status")
    if ref == "edge.min_gap":
        return _attr(edge, "min_gap")
    if ref == "edge.cross_file":
        return 1 if _attr(edge, "cross_file") else 0
    if ref == "edge.mapped_mcad_kind":
        return mcad_kind_of.get(edge["eid"])
    return _attr(edge, ref.split(".", 1)[1])


def _derived_req_ref(row: Mapping[str, Any], ref: str) -> Any:
    """`state.req.margin.<field>` — 요구 여유 표 한 행의 필드(plan §3.2.6 R-007)."""
    return row.get(ref.rsplit(".", 1)[1])


def _derived_node_ref(node: Mapping[str, Any], ref: str, degree_tied: Mapping[str, int]) -> Any:
    if ref == "node.min_dim":
        return _attr(node, "min_dim")
    if ref == "node.degree_tied":
        return degree_tied.get(node["nid"], 0)
    return _attr(node, ref.split(".", 1)[1])


# 규칙별 `evaluable=false` 조건(plan §3.2.6 표). 값은 not_evaluable_reason 어휘 3종뿐이다.
NOT_EVALUABLE_REASONS: tuple[str, ...] = ("source_absent", "degraded", "truncated")
_RULE_NEEDS_MCAD = ("R-001", "R-002", "R-003", "R-004", "R-005", "R-006")
# 요구는 IR 이 아니라 rr_requirements 에서 오므로 R-007 은 mcad 부재로 평가 불가가 되지 않는다.
_RULE_DEGRADED: dict[str, tuple[str, ...]] = {
    "R-001": ("capture_partial",),
    "R-003": ("volume_null_pre_d168",),
    "R-004": ("mcp_degraded",),
    "R-005": ("mcp_degraded",),
}
_RULE_TRUNCATED = ("R-001", "R-002")


def not_evaluable_reason(ir: Mapping[str, Any], rule_id: str) -> str | None:
    """그 규칙의 입력이 이 스냅샷에 실재하지 않으면 사유를, 실재하면 None(plan §3.2.6).

    `pass` 만으로는 '검문했고 위반이 없다' 와 '검문할 입력이 없었다' 가 구분되지 않아 결측이 조용히
    '이상 없음' 으로 읽힌다 — 그 자리를 이 함수가 닫는다.
    """
    missing = dict(ir.get("missing") or {})
    sources = list(ir.get("sources") or [])
    degraded = {code for s in sources for code in (s.get("degraded") or ())}
    mcad_absent = bool(missing.get("mcad_absent")) or not any(s.get("kind") == "mcad" for s in sources)
    if rule_id in _RULE_NEEDS_MCAD and mcad_absent:
        return "source_absent"
    if rule_id == "R-006" and bool(missing.get("dyna_absent")):
        return "source_absent"
    if rule_id == "R-007" and bool(missing.get("req_absent")):
        return "source_absent"
    if bool(missing.get("iface_kinds_absent")) and rule_id == "R-001":
        return "degraded"
    for code in _RULE_DEGRADED.get(rule_id, ()):
        if code in degraded:
            return "degraded"
    if rule_id in _RULE_TRUNCATED and "interfaces_truncated" in degraded:
        return "truncated"
    return None


def evaluate_rules(ir: Mapping[str, Any], rules: Sequence[Mapping[str, Any]] | None = None, *,
                   req_margin: Sequence[Mapping[str, Any]] | None = None,
                   extra_missing: Mapping[str, Any] | None = None) -> list[dict]:
    """rr_rules(또는 시드)의 조건 DSL 을 IR 위에서 즉시 실행한다. 부작용 없음·결정론이며 조건이 걸리면 pass=false 다.

    `req_margin` 은 `sig:req.margin` 의 행 목록이다(R-007 의 주체). 넘기지 않으면 요구 입력이 없는 것이라
    `missing.req_absent` 로 보고 R-007 은 `pass=null` 이다 — 요구가 없는데 pass 로 세지 않는다(plan §3.2.6).
    """
    rules = list(rules if rules is not None else load_seed_rules())
    req_rows = [r for r in (req_margin or ()) if isinstance(r, Mapping)]
    missing_view = dict(ir.get("missing") or {})
    if extra_missing:
        missing_view.update(extra_missing)
    missing_view.setdefault("req_absent", not req_rows)
    reason_ir = {"missing": missing_view, "sources": list(ir.get("sources") or ())}
    edges = _live_edges(ir)
    nodes = list(ir.get("nodes") or [])
    index = {n["nid"]: n for n in nodes}
    warning_codes = [str(w.get("code")) for w in ir.get("warnings") or []]

    degree_tied: dict[str, int] = {}
    for e in edges:
        if e.get("kind") == "tied":
            for nid in (e.get("a"), e.get("b")):
                if nid:
                    degree_tied[nid] = degree_tied.get(nid, 0) + 1

    # dyna contact 쌍을 dn 으로 mcad 에 사상해 대응 mcad 계면 kind 를 찾는다(plan §3.2.6 R-006).
    mcad_iface: dict[tuple[str, str], str] = {}
    for e in edges:
        if e.get("kind_family") == "iface" and e.get("b"):
            key = tuple(sorted([e["a"], e["b"]]))
            current = mcad_iface.get(key)
            if current is None or e["kind"] == "interference":
                mcad_iface[key] = e["kind"]
    mcad_kind_of: dict[str, str | None] = {}
    for e in edges:
        if e.get("kind") != "contact" or not e.get("b"):
            continue
        dn_a = index.get(e["a"], {}).get("dn") or e["a"]
        dn_b = index.get(e["b"], {}).get("dn") or e["b"]
        mcad_kind_of[e["eid"]] = mcad_iface.get(tuple(sorted([dn_a, dn_b])))

    out: list[dict] = []
    for rule in sorted(rules, key=lambda r: str(r.get("id"))):
        condition = rule.get("condition_json") or {}
        all_conds = list(condition.get("all") or [])
        any_conds = list(condition.get("any") or [])
        aggregate = rule.get("aggregate") or {"count_gte": 1}

        global_all = [c for c in all_conds if str(c["ref"]).startswith("warnings.")]
        req_all = [c for c in all_conds if str(c["ref"]).startswith("state.req.margin.")]
        edge_all = [c for c in all_conds if str(c["ref"]).startswith("edge.")]
        node_all = [c for c in all_conds if str(c["ref"]).startswith("node.")]
        global_any = [c for c in any_conds if str(c["ref"]).startswith("warnings.")]
        subject_any = [c for c in any_conds if not str(c["ref"]).startswith("warnings.")]

        global_ok = all(any(_cmp(code, c["op"], c.get("value")) for code in warning_codes) if warning_codes
                        else _cmp(None, c["op"], c.get("value")) for c in global_all)
        if global_any:
            global_ok = global_ok and any(any(_cmp(code, c["op"], c.get("value")) for code in warning_codes) for c in global_any)

        refs: list[str] = []
        if not global_ok:
            matched: list[str] = []
        elif req_all:
            names = sorted(
                str(row.get("name"))
                for row in req_rows
                if all(_cmp(_derived_req_ref(row, c["ref"]), c["op"], c.get("value")) for c in req_all)
            )
            matched = names
            # 요구 한 건은 `req:<name>`·`[d:<name>]` 쌍으로 인용한다(plan §3.2.6 R-007).
            refs = [ref for name in names for ref in (f"req:{name}", f"d:{name}")]
        elif edge_all or (subject_any and not node_all):
            matched = []
            for e in edges:
                values_ok = all(_cmp(_derived_edge_ref(ir, e, c["ref"], mcad_kind_of), c["op"], c.get("value")) for c in edge_all)
                if values_ok and (not subject_any or any(
                        _cmp(_derived_edge_ref(ir, e, c["ref"], mcad_kind_of), c["op"], c.get("value")) for c in subject_any)):
                    matched.append(e["eid"])
            refs = sorted(matched)
            matched = refs
        elif node_all:
            matched = sorted(
                n["nid"] for n in nodes
                if all(_cmp(_derived_node_ref(n, c["ref"], degree_tied), c["op"], c.get("value")) for c in node_all)
            )
            refs = matched
        else:
            matched = sorted({f"warn:{code}#" for code in warning_codes
                              if any(_cmp(code, c["op"], c.get("value")) for c in global_all + global_any)})
            refs = matched

        count = len(matched)
        if "exists" in aggregate:
            fired = bool(global_ok and (count > 0 or (not edge_all and not node_all and any(
                any(_cmp(code, c["op"], c.get("value")) for code in warning_codes) for c in global_all))))
        else:
            fired = bool(global_ok and count >= int(aggregate.get("count_gte", 1)))

        found = {"count": count, "refs": refs, "text": f"{rule.get('name') or rule.get('id')} {count}건"}
        version = str(rule.get("rule_version") or "rules-1.0")
        reason = not_evaluable_reason(reason_ir, str(rule.get("id")))
        evaluable = reason is None
        out.append({
            "rule": str(rule.get("id")),
            "version": version,
            "severity": rule.get("severity"),
            "pass": (not fired) if evaluable else None,
            "evaluable": evaluable,
            "not_evaluable_reason": reason,
            "found": found,
            "why_it_matters": f"«{rule.get('why_it_matters') or ''}»",
            "fix_hint": f"«{rule.get('fix_hint') or ''}»",
            "payload_hash": sha256_hex(f"{rule.get('id')}|{version}|{canonical_json(found)}"),
            "refs": refs,
        })
    return out


# ---------------------------------------------------------------- summary_text(plan §3.2.7)
def _summary_lines(ir: Mapping[str, Any], state: Mapping[str, Any]) -> list[str]:
    signals = state["signals"]
    gates = state["gates"]

    def value(key: str) -> Any:
        record = signals.get(key)
        return record.get("value") if record else None

    def text(key: str) -> str:
        record = signals.get(key)
        return record.get("text") if record else ""

    sources = {s["kind"]: s for s in ir.get("sources") or []}
    absent = ir.get("missing") or {}

    def source_word(kind: str) -> str:
        # 소스 행이 있다고 실린 것이 아니다 — ecad 계약 스텁(0.0-stub)과 자격 없이 닫힌 dyna 는 행만 남기고
        # `<kind>_absent` 로 닫는다. 행만 보고 `present` 라 적으면 같은 요약의 [결측] 줄과 반대말이 된다.
        if kind not in sources or absent.get(f"{kind}_absent"):
            return "absent"
        return sources[kind].get("source_hash") or "present"

    source_line = " ".join(f"{kind}={source_word(kind)}" for kind in ("mcad", "dyna", "dyna_result", "ecad"))
    gate_line = " · ".join(f"{key} {_gate_word(g)}" for key, g in sorted(gates.items()))
    dyna_line = "[Dyna] absent"
    if not (ir.get("missing") or {}).get("dyna_absent", True):
        dyna_line = f"[Dyna] pid {value('counts.dyna.pids')} · {text('counts.dyna.contacts_by_type')} · {text('results.part_risk_top')}"
    rules_line = " · ".join(f"{h['rule']} {_rule_word(h)} [rule:{h['rule']}]" for h in state["rule_hits"])
    missing_line = " · ".join(k for k, v in sorted((ir.get("missing") or {}).items()) if v) or "없음"
    return [
        f"[대상] 스냅샷 {ir['snapshot_id'][:8]} ir_hash={ir['ir_hash'][:12]} 소스 {source_line}",
        f"[게이트] {gate_line}",
        f"[구조] 파일 {value('counts.files')} · 리프 {value('counts.leaf')} · 어셈블리 {value('counts.assemblies')} · "
        f"엣지 tied {value('counts.edges.tied')} touching {value('counts.edges.touching')} "
        f"clearance {value('counts.edges.clearance')} interference {value('counts.edges.interference')} · "
        f"고아 {value('counts.orphans')} · cross_file {value('counts.cross_file')} [sig:counts.*]",
        f"[상위 계면] {text('top.interference')} · 근접 간극 {text('top.tight_clearance')}",
        f"[치수] {text('dims_named')}",
        f"[재료] 재질 종류 {value('counts.materials_distinct')} · 미기재 {value('counts.material_null')} [sig:counts.material_null]",
        dyna_line,
        f"[규칙] {rules_line}",
        f"[씨앗] {' · '.join(s['tag'] for s in state['character_seed']) or '없음'}",
        f"[결측] {missing_line}",
    ]


def _summary_text(ir: Mapping[str, Any], state: Mapping[str, Any]) -> tuple[str, str]:
    """summary_text 와 summary_status. render.py 가 있으면 그 생성기·린터를 쓴다(정본은 §3.4)."""
    render = _render()
    generator = getattr(render, "state_summary_text", None) if render else None
    text = str(generator(state, ir)) if generator else "\n".join(_summary_lines(ir, state))
    text = text[:2000]
    linter = getattr(render, "lint", None) if render else None
    status = "ok"
    if linter is not None:
        status = "ok" if linter(text) else "lint_failed"
    return text, status


# ---------------------------------------------------------------- 봉투 조립·저장
def build_state(
    ir: Mapping[str, Any],
    *,
    rules: Sequence[Mapping[str, Any]] | None = None,
    acks: Mapping[str, Mapping[str, Any]] | None = None,
    precedent: Mapping[str, Any] | None = None,
    computed_at: int | None = None,
    req: Mapping[str, Any] | None = None,
) -> dict:
    """rr_state 봉투 하나(state_version '1.0'). 같은 (ir_hash, rule_version) 이면 같은 값이 나온다.

    `req` 는 `requirements.compute_req_signals()` 의 결과다(`{'signals': …, 'missing': …}`). 요구는 IR 에
    복사되지 않으므로 여기서만 합쳐지고, 그래서 요구를 고쳐도 `ir_hash` 는 바이트 불변이다(plan §2.8b).
    """
    gates = compute_gates(ir, acks=acks)
    signals = compute_signals(ir, gates)
    req_signals = dict((req or {}).get("signals") or {})
    req_missing = dict((req or {}).get("missing") or {})
    signals.update(req_signals)
    margin_signal = req_signals.get("req.margin") or {}
    margin_rows = margin_signal.get("value") if isinstance(margin_signal, Mapping) else None
    seeds = compute_character_seed(ir, signals, gates)
    features = compute_feature_vector(ir, signals)
    hits = evaluate_rules(ir, rules, req_margin=margin_rows if isinstance(margin_rows, list) else None,
                          extra_missing=req_missing or None)
    versions = dict(ir.get("versions") or {})

    state = {
        "state_version": STATE_VERSION,
        "snapshot_id": ir["snapshot_id"],
        "ir_hash": ir["ir_hash"],
        "project_id": ir["project_id"],
        "rule_version": (hits[0]["version"] if hits else str(version_of(load_json("rules-seed")) or "rules-1.0")),
        "taxonomy_version": str(versions.get("taxonomy_version") or "1.0"),
        "seed_rules_version": str(versions.get("seed_rules_version") or "seed-1.0"),
        "computed_at": int(computed_at if computed_at is not None else now_epoch()),
        "blocked": is_blocked(gates),
        "gates": gates,
        "missing": {**dict(ir.get("missing") or {}), **req_missing},
        "signals": signals,
        "character_seed": seeds,
        "feature_vector": features,
        "precedent": dict(precedent or {"corpus_n": 0, "per_feature": {}, "out_of_range_count": 0}),
        "rule_hits": hits,
        "summary_text": "",
        "summary_status": "ok",
    }
    state["summary_text"], state["summary_status"] = _summary_text(ir, state)
    return state


def save_state(store, state: Mapping[str, Any], *, owner_sub: str | None = None) -> str:
    """rr_states 에 저장한다(스냅샷 1건당 1행). 같은 스냅샷을 다시 계산하면 덮어쓴다.

    `state_json` 에는 시각(`computed_at`)을 넣지 않는다 — plan §3.1 원칙 1 은 같은 (ir_hash, rule_version)
    이면 state_json 도 같아야 한다고 못박는다. 시각은 rr_states.computed_at 열에만 남고 load_state 가 되붙인다.
    """
    sub = owner_sub or state.get("owner_sub")
    if not sub:
        row = store.query_one("SELECT owner_sub FROM rr_snapshots WHERE id = ?", (state["snapshot_id"],))
        if row is None:
            raise AppError("E404", f"스냅샷을 찾을 수 없습니다 — {state['snapshot_id']}.", http_status=404)
        sub = row["owner_sub"]
    store.execute(
        "INSERT OR REPLACE INTO rr_states (snapshot_id, owner_sub, state_json, feature_json, rule_hits_json,"
        " character_seed_json, gates_json, summary_text, summary_status, blocked, state_version, rule_version,"
        " taxonomy_version, computed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            state["snapshot_id"], sub,
            canonical_json({k: v for k, v in state.items() if k != "computed_at"}),
            canonical_json(state["feature_vector"]),
            canonical_json(state["rule_hits"]), canonical_json(state["character_seed"]),
            canonical_json(state["gates"]), state["summary_text"], state["summary_status"],
            1 if state["blocked"] else 0, state["state_version"], state["rule_version"],
            state["taxonomy_version"], state["computed_at"],
        ),
    )
    return state["snapshot_id"]


def load_state(store, snapshot_id: str) -> dict | None:
    """저장된 rr_state 봉투(computed_at 은 열에서 되붙인다). 없으면 None."""
    row = store.query_one(
        "SELECT state_json, computed_at FROM rr_states WHERE snapshot_id = ?", (snapshot_id,))
    if row is None:
        return None
    state = json.loads(row["state_json"])
    if isinstance(state, dict) and "computed_at" not in state:
        state["computed_at"] = row["computed_at"]
    return state


def compute_state_for_snapshot(store, snapshot_id: str, *, rules: Sequence[Mapping[str, Any]] | None = None,
                               acks: Mapping[str, Mapping[str, Any]] | None = None, save: bool = True) -> dict:
    """동결된 IR 을 읽어 rr_state 를 계산하고(기본) 저장한다. '재해석 적용'·규칙 갱신 뒤 재계산 경로다."""
    from app import requirements  # noqa: PLC0415 — 순환 임포트를 피하려 지연 임포트한다.
    from app.ir_builder import load_ir  # noqa: PLC0415 — 순환 임포트를 피하려 지연 임포트한다.

    ir = load_ir(store, snapshot_id)
    req = requirements.compute_req_signals(store, ir["project_id"], ir)
    state = build_state(ir, rules=rules if rules is not None else load_active_rules(store), acks=acks, req=req)
    if save:
        save_state(store, state)
    return state
