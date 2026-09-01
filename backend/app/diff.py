# 두 스냅샷의 3층 diff(구조·파라메트릭·의미, §3.3)·변경 임계 v1·comparability/G7 판정과 rr_diffs·rr_diff_events 저장
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Callable, Mapping, Sequence

from . import sameas
from . import state as state_module
from .common import R, canonical_json, new_uuid, now_epoch
from .errors import AppError

__all__ = [
    "DIFF_VERSION",
    "EXCLUDED_REASONS",
    "PARAM_RULES",
    "RANK",
    "cid_for",
    "comparability",
    "check_pair_blocked",
    "changed_ckeys",
    "compute_diff",
    "create_diff",
    "get_diff",
]

DIFF_VERSION = "1.0"

# §3.3.6 제외 사유 어휘. 제외된 항목은 diff_json 에 수치와 함께 남고 의미 이벤트만 만들지 않는다.
EXCLUDED_REASONS: tuple[str, ...] = (
    "tol_differs", "tol_unknown", "result_kind_differs", "sim_params_differ", "unit_scale",
    "partial_scope", "suspect_coords", "null_one_side", "sameas_pending", "bridge_stale",
)

# §2.4 kind 강도 순위(StepForge compare_interfaces 규약). geometric 은 touching 과 같은 1.
RANK: dict[str, int] = {"interference": 3, "tied": 2, "touching": 1, "geometric": 1, "clearance": 0}

# tol(공차 설정)에 종속하는 계면 파라메트릭 항목(§3.2.2 G7 effect).
TOL_DEPENDENT: tuple[str, ...] = ("min_gap", "contact_area_est", "band_width",
                                  "penetration_depth", "penetration_volume")
RESULT_METRICS: tuple[str, ...] = ("worst_stress", "worst_g", "worst_disp")

# §3.3.4 변경 임계 v1. mode — AND(절대·상대 둘 다) · rel(상대만) · abs(절대만).
PARAM_RULES: dict[str, dict] = {
    "bbox_def_dims":   {"abs": 0.02,  "rel": 0.005, "mode": "AND", "unit": "mm",  "round": "length"},
    "bbox_world_dims": {"abs": 0.02,  "rel": 0.005, "mode": "AND", "unit": "mm",  "round": "length"},
    "centroid_world":  {"abs": 0.02,  "rel": 0.005, "mode": "AND", "unit": "mm",  "round": "length"},
    "min_dim":         {"abs": 0.02,  "rel": 0.02,  "mode": "AND", "unit": "mm",  "round": "length"},
    "volume":          {"abs": None,  "rel": 0.01,  "mode": "rel", "unit": "mm3", "round": "volume"},
    "area":            {"abs": None,  "rel": 0.01,  "mode": "rel", "unit": "mm2", "round": "area"},
    "min_gap":         {"abs": 0.005, "rel": 0.10,  "mode": "AND", "unit": "mm",  "round": "length"},
    "contact_area_est": {"abs": None, "rel": 0.20,  "mode": "AND", "unit": "mm2", "round": "area"},
    "band_width":      {"abs": None,  "rel": 0.20,  "mode": "AND", "unit": "mm",  "round": "length"},
    "penetration_depth": {"abs": 0.001, "rel": None, "mode": "abs", "unit": "mm", "round": "length"},
    "penetration_volume": {"abs": 1e-6, "rel": 0.05, "mode": "AND", "unit": "mm3", "round": "volume"},
    "material.E":      {"abs": None,  "rel": 0.01,  "mode": "rel", "unit": None,  "round": None},
    "material.rho":    {"abs": None,  "rel": 0.01,  "mode": "rel", "unit": None,  "round": None},
    "material.sigy":   {"abs": None,  "rel": 0.01,  "mode": "rel", "unit": None,  "round": None},
    "material.nu":     {"abs": None,  "rel": 0.01,  "mode": "rel", "unit": None,  "round": None},
    "fs":              {"abs": 0.01,  "rel": None,  "mode": "abs", "unit": None,  "round": "fs"},
    "n_elems":         {"abs": None,  "rel": 0.20,  "mode": "rel", "unit": None,  "round": None},
    "worst_stress":    {"abs": None,  "rel": 0.05,  "mode": "rel", "unit": "MPa", "round": "stress"},
    "worst_g":         {"abs": None,  "rel": 0.05,  "mode": "rel", "unit": "G",   "round": "acceleration"},
    "worst_disp":      {"abs": None,  "rel": 0.05,  "mode": "rel", "unit": "mm",  "round": "length"},
}
DIM_DEFAULT_TOL = (0.02, 0.01)          # dims_named 기본 임계(§3.3.4 마지막 행).

_AXES = ("x", "y", "z")


# ---------------------------------------------------------------- 작은 유틸
def cid_for(layer: str, code_or_attr: str, key_a: str = "", key_b: str = "", attr: str = "") -> str:
    """§3.3.2 — `c: + sha1(layer|code_or_attr|key_a|key_b|attr)[:12]`. dn 을 키로 쓰므로 재계산해도 같다."""
    payload = f"{layer}|{code_or_attr}|{key_a}|{key_b}|{attr}"
    return "c:" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _attrs(item: Mapping[str, Any]) -> Mapping[str, Any]:
    value = item.get("attrs")
    return value if isinstance(value, Mapping) else {}


def _dig(obj: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(obj, Mapping):
            return None
        obj = obj.get(key)
    return obj


def _by_nid(nodes: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(n.get("nid")): n for n in nodes if n.get("nid")}


def _dn(node: Mapping[str, Any] | None, fallback: str = "") -> str:
    if node is None:
        return fallback
    return str(node.get("dn") or node.get("nid") or fallback)


def _label(node: Mapping[str, Any] | None) -> str:
    if node is None:
        return ""
    text = str(node.get("label") or node.get("name_norm") or node.get("nid") or "")
    flags = node.get("status_flags")
    if isinstance(flags, (list, tuple)) and "auto_named" in flags:
        text += "(auto_named)"
    return text


def _scope_out(node: Mapping[str, Any] | None) -> bool:
    flags = (node or {}).get("status_flags")
    return bool(isinstance(flags, (list, tuple)) and "scope_out" in flags)


def _bbox_dims(bbox: Any) -> list[float] | None:
    """`[xmin,ymin,zmin,xmax,ymax,zmax]` 를 3축 치수로 편다. 값이 온전하지 않으면 None."""
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 6:
        return None
    vals = [_num(v) for v in bbox]
    if any(v is None for v in vals):
        return None
    return [float(vals[i + 3]) - float(vals[i]) for i in range(3)]  # type: ignore[arg-type]


def _diag(node: Mapping[str, Any] | None) -> float | None:
    """노드 bbox 대각 길이(mm). contact_area_est·band_width 의 절대 하한 계산에 쓴다."""
    if node is None:
        return None
    at = _attrs(node)
    dims = at.get("size_def") if isinstance(at.get("size_def"), (list, tuple)) else _bbox_dims(at.get("bbox_def"))
    if not dims:
        dims = at.get("size") if isinstance(at.get("size"), (list, tuple)) else None
    if not dims:
        return None
    vals = [_num(v) for v in dims]
    if any(v is None for v in vals):
        return None
    return math.sqrt(sum(float(v) ** 2 for v in vals))  # type: ignore[arg-type]


def _gate_fail(state: Mapping[str, Any] | None, key: str) -> bool:
    gate = _dig(state or {}, "gates", key)
    return isinstance(gate, Mapping) and gate.get("pass") is False


def _source(ir: Mapping[str, Any], kind: str) -> Mapping[str, Any] | None:
    for source in ir.get("sources") or []:
        if isinstance(source, Mapping) and source.get("kind") == kind:
            return source
    return None


# ---------------------------------------------------------------- 정규 표기(§3.4.1)
# render.py 가 정규 표기의 정본이다. 아직 없거나 해당 함수가 없으면 같은 형식 규칙으로 여기서 만든다.
def _render_module():
    try:
        from . import render  # type: ignore
    except ImportError:
        return None
    return render


def _fmt(value: Any, round_kind: str | None) -> str:
    if value is None:
        return "미측정"
    num = _num(value)
    if num is None:
        return str(value)
    if round_kind is None:
        return f"{num:g}"
    rounded = R(num, round_kind)
    if round_kind == "length":
        return f"{rounded:.3f}"
    if round_kind == "area":
        return f"{rounded:.1f}"
    if round_kind == "stress":
        return f"{rounded:.0f}"
    if round_kind == "fs":
        return f"{rounded:.2f}"
    if round_kind == "acceleration":
        return f"{rounded:.1f}"
    return f"{rounded:g}"


def _fmt_rel(rel: float | None) -> str:
    if rel is None:
        return ""
    sign = "−" if rel < 0 else "+"
    return f" ({sign}{abs(rel) * 100:.1f}%)"


def _param_text(subject: str, attr: str, before: Any, after: Any, unit: str | None,
                rel: float | None, round_kind: str | None, cid: str, suffix: str = "") -> str:
    """`PLATE_1 bbox_dz 1.20→1.00 mm (−16.7%) [c:3fa2…]` 형식(§3.3.4·§3.4.1)."""
    unit_text = f" {unit}" if unit else ""
    head = f"{subject} {attr} {_fmt(before, round_kind)}→{_fmt(after, round_kind)}{unit_text}"
    return f"{head}{_fmt_rel(rel)}{suffix} [{cid}]"


# ---------------------------------------------------------------- comparability · G7(§3.3.6·§2.12)
def comparability(base_ir: Mapping[str, Any], target_ir: Mapping[str, Any],
                  base_state: Mapping[str, Any] | None = None,
                  target_state: Mapping[str, Any] | None = None) -> dict:
    """잣대 동일성을 데이터로 남긴다(§3.1 원칙 5). 항목을 버리지 않고 사유를 붙이기 위한 판정이다."""
    base_mcad, target_mcad = _source(base_ir, "mcad") or {}, _source(target_ir, "mcad") or {}
    base_tol, target_tol = base_mcad.get("tol_config_hash"), target_mcad.get("tol_config_hash")
    tol_keys_known = bool(base_tol) and bool(target_tol)
    if not tol_keys_known:
        tol_parity: bool | None = None                 # §3.2.2 — 한쪽이라도 못 얻으면 null 이다.
    else:
        tol_parity = base_tol == target_tol

    base_results, target_results = base_ir.get("results"), target_ir.get("results")
    base_kind = _dig(base_results, "kind") if isinstance(base_results, Mapping) else None
    target_kind = _dig(target_results, "kind") if isinstance(target_results, Mapping) else None
    base_params = _dig(base_results, "sim_params_hash") if isinstance(base_results, Mapping) else None
    target_params = _dig(target_results, "sim_params_hash") if isinstance(target_results, Mapping) else None
    result_present = isinstance(base_results, Mapping) or isinstance(target_results, Mapping)
    result_both = isinstance(base_results, Mapping) and isinstance(target_results, Mapping)
    # 양쪽 다 결과가 없으면 견줄 잣대 자체가 없다 — parity 는 true 이고 result_delta 가 비어 있을 뿐이다.
    # (한쪽에만 있으면 result_kind_differs 다.)
    result_parity = (not result_present) or bool(result_both and base_kind == target_kind
                                                 and base_params == target_params)
    if not result_present:
        result_reason = None
    elif not result_both:
        result_reason = "result_kind_differs"
    elif base_kind != target_kind:
        result_reason = "result_kind_differs"
    elif base_params != target_params:
        result_reason = "sim_params_differ"
    else:
        result_reason = None

    # --- 소스 5키(plan §3.3.6 표). 전부 false 여도 diff 생성을 막지 않는다 — 막는 것은 G6 하나다.
    base_sources = {str(x.get("kind")): x for x in (base_ir.get("sources") or ()) if isinstance(x, Mapping)}
    target_sources = {str(x.get("kind")): x for x in (target_ir.get("sources") or ()) if isinstance(x, Mapping)}
    common_kinds = sorted(set(base_sources) & set(target_sources))
    app_version_parity: bool | None = True
    for kind in common_kinds:
        left = ((base_sources[kind].get("app_version") or {}).get("version"))
        right = ((target_sources[kind].get("app_version") or {}).get("version"))
        if left is None or right is None:
            app_version_parity = None if app_version_parity is not False else False
            continue
        if left != right:
            app_version_parity = False
    if not common_kinds:
        app_version_parity = None

    base_adapters = dict(_dig(base_ir, "versions", "adapter_versions") or {})
    target_adapters = dict(_dig(target_ir, "versions", "adapter_versions") or {})
    adapter_parity = all(base_adapters.get(k) == target_adapters.get(k) for k in common_kinds) \
        if common_kinds else True

    drift_kinds = sorted({kind for kind, source in list(base_sources.items()) + list(target_sources.items())
                          if "schema_drift" in (source.get("degraded") or ())})
    source_schema_parity = not drift_kinds

    def _capture_ok(ir: Mapping[str, Any]) -> bool:
        missing = ir.get("missing") or {}
        failed = [k for k in missing if str(k).endswith("_capture_failed") and missing[k]]
        return not ir.get("capture_partial") and not ir.get("partial") and not failed

    capture_parity = _capture_ok(base_ir) and _capture_ok(target_ir)
    primary_source_parity = base_ir.get("primary_source") == target_ir.get("primary_source")

    base_scope = (base_mcad or {}).get("scope")
    target_scope = (target_mcad or {}).get("scope")
    detail: list[str] = []
    if tol_parity is None:
        detail.append("reason=tol_unknown")
    for source in (base_mcad, target_mcad):
        keys = source.get("tol_known_keys")
        if isinstance(keys, (list, tuple)) and len(keys) == 4:
            detail.append("reason=tol_keys_partial(4)")
            break

    count = (0 if tol_parity is True else 1) + (0 if result_parity else 1)
    if result_reason:
        detail.append(f"reason={result_reason}")
    effect = "none" if count == 0 else "exclude_by_reason"
    return {
        "tol_parity": tol_parity,
        "tol_keys_known": tol_keys_known,
        "unit_parity": (base_ir.get("units") or {}) == (target_ir.get("units") or {}),
        "result_parity": result_parity,
        "result_present": result_present,
        "result_reason": result_reason,
        "scope_parity": base_scope == target_scope,
        "coordinate_ok": not (_gate_fail(base_state, "G4") or _gate_fail(target_state, "G4")),
        "partial_any": bool(base_ir.get("partial")) or bool(target_ir.get("partial")),
        "ir_version_parity": base_ir.get("ir_version") == target_ir.get("ir_version"),
        "app_version_parity": app_version_parity,
        "adapter_parity": adapter_parity,
        "source_schema_parity": source_schema_parity,
        "source_schema_drift_kinds": drift_kinds,
        "capture_parity": capture_parity,
        "primary_source_parity": primary_source_parity,
        "G7": {"key": "yardstick_parity", "count": count, "threshold": 0, "pass": count == 0,
               "blocking": False, "effect": effect, "detail": sorted(set(detail))},
        "base_blocked": bool((base_state or {}).get("blocked")),
        "target_blocked": bool((target_state or {}).get("blocked")),
    }


def check_pair_blocked(base_state: Mapping[str, Any] | None,
                       target_state: Mapping[str, Any] | None) -> dict | None:
    """G6 차단이면 `{gates, reason}` 을 돌려준다(호출자가 409 `gate_blocked` 로 끝낸다, §2.12·§8.2.3).

    `reason ∈ unit_mismatch | unit_unknown` — 뒤가 `pass=null` 인 unknown_blocking 이다.
    """
    blocked: dict[str, Any] = {}
    reasons: list[str] = []
    for role, state in (("base", base_state), ("target", target_state)):
        gates = (state or {}).get("gates") or {}
        reason = state_module.blocked_reason(gates)
        if reason is None and not (state or {}).get("blocked"):
            continue
        blocked[role] = _dig(state or {}, "gates", "G6")
        reasons.append(reason or "unit_mismatch")
    if not blocked:
        return None
    # 둘 다 차단이면 unit_mismatch(고칠 수 있는 쪽)를 앞세운다 — 화면 안내 문구가 갈린다.
    reason = "unit_mismatch" if "unit_mismatch" in reasons else reasons[0]
    return {"gates": blocked, "reason": reason}


# ---------------------------------------------------------------- 대응(§3.3.1 correspondence)
_MATCH_METHODS = ("ledger", "pid_map", "exact_path", "fingerprint", "name_norm", "fuzzy", "manual")


def _correspondence(base_nodes, target_nodes, links) -> dict:
    base_by, target_by = _by_nid(base_nodes), _by_nid(target_nodes)
    matched: list[dict] = []
    used_base: set[str] = set()
    used_target: set[str] = set()
    pending_n = 0
    method_counts = {m: 0 for m in _MATCH_METHODS}
    for link in sorted(links, key=lambda link: (str(link.get("a")), str(link.get("b")))):
        status = str(link.get("status") or "")
        score = float(link.get("score") or 0.0)
        if status == "pending":
            pending_n += 1
            continue
        if status == "rejected":
            continue
        if not (status == "confirmed" or (status == "auto" and score >= sameas.AUTO_SCORE)):
            continue
        a, b = str(link.get("a") or ""), str(link.get("b") or "")
        if a not in base_by or b not in target_by or a in used_base or b in used_target:
            continue
        used_base.add(a)
        used_target.add(b)
        method = str(link.get("method") or "")
        if method in method_counts:
            method_counts[method] += 1
        base_node, target_node = base_by[a], target_by[b]
        matched.append({
            "dn": _dn(base_node, a), "nid_base": a, "nid_target": b,
            "ckey": base_node.get("ckey") or target_node.get("ckey"),
            "method": method, "score": score, "status": status,
        })
    unmatched_base = sorted(n for n in base_by if n not in used_base)
    unmatched_target = sorted(n for n in target_by if n not in used_target)
    return {"matched": matched, "unmatched_base": unmatched_base, "unmatched_target": unmatched_target,
            "pending_n": pending_n, "method_counts": method_counts}


def _confidence(method: str, edge_status: str | None = None, *,
                lower_bound: bool = False, cross_file_suspect: bool = False) -> str:
    """§3.3.5 confidence 규칙. 판단이 아니라 대응·상태의 재서술이다."""
    if lower_bound or cross_file_suspect or method == "fuzzy":
        return "low"
    if method in ("fingerprint", "name_norm"):
        return "medium"
    if edge_status == "auto":
        return "medium"
    if method in ("ledger", "pid_map", "exact_path", "manual"):
        return "high"
    return "medium"


# ---------------------------------------------------------------- 파라메트릭 판정(§3.3.4)
def _classify(before: Any, after: Any, rule: Mapping[str, Any],
              abs_floor: float | None = None) -> tuple[str, float | None, float | None]:
    """(flag, delta, rel_delta). null 은 미측정이므로 0 으로 치환하지 않는다(§3.1 원칙 2)."""
    b, a = _num(before), _num(after)
    if b is None or a is None:
        return ("null_one_side", None, None)
    delta = a - b
    rel = (delta / abs(b)) if b else None
    floor = rule.get("abs") if abs_floor is None else abs_floor
    ok_abs = True if floor is None else abs(delta) >= float(floor)
    if rule.get("rel") is None:
        ok_rel = True
    elif rel is None:
        ok_rel = delta != 0.0
    else:
        ok_rel = abs(rel) >= float(rule["rel"])
    mode = rule.get("mode", "AND")
    if mode == "AND":
        changed = ok_abs and ok_rel
    elif mode == "rel":
        changed = ok_rel
    else:
        changed = ok_abs
    return ("changed" if changed else "noise", delta, rel)


def _param_item(layer_key: str, subject: str, subject_label: str, attr: str,
                before: Any, after: Any, rule: Mapping[str, Any], *,
                key_a: str, key_b: str = "", abs_floor: float | None = None,
                excluded_reason: str | None = None, extra: Mapping[str, Any] | None = None,
                text_attr: str | None = None, text_suffix: str = "") -> dict:
    flag, delta, rel = _classify(before, after, rule, abs_floor)
    if flag == "null_one_side" and excluded_reason is None:
        excluded_reason = "null_one_side"
    cid = cid_for("parametric", layer_key, key_a, key_b, attr)
    item = {
        "cid": cid, "subject_key": subject, "attr": attr,
        "before": before, "after": after,
        "delta": None if delta is None else R(delta, rule["round"]) if rule.get("round") else delta,
        "rel_delta": None if rel is None else round(rel, 6),
        "unit": rule.get("unit"), "flag": flag, "lower_bound": False,
        "excluded_reason": excluded_reason, "size_pct": None,
        "text": _param_text(subject_label, text_attr or attr, before, after, rule.get("unit"),
                            rel, rule.get("round"), cid, text_suffix),
    }
    if extra:
        item.update(dict(extra))
    return item


# ---------------------------------------------------------------- 구조층(§3.3.3)
def _edge_key(edge: Mapping[str, Any], dn_of: Mapping[str, str]) -> tuple[str, str, str]:
    """(kind_family, 정렬한 dn 쌍) — 끝점 dn 을 사상한 뒤 정렬해 base·target 엣지를 잇는다."""
    family = str(edge.get("kind_family") or "")
    a = dn_of.get(str(edge.get("a") or ""), str(edge.get("a") or ""))
    b = dn_of.get(str(edge.get("b") or ""), str(edge.get("b") or ""))
    if family in ("hier", "load_path", "net"):          # 방향 kind 는 정렬하지 않는다(§2.4 eid 규칙).
        return (family, a, b)
    first, second = sorted((a, b))
    return (family, first, second)


def _degree_no_clearance(edges: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """clearance 를 뺀 차수(§3.3.3 orphans_delta · graph.py 규약)."""
    degree: dict[str, int] = {}
    for edge in edges:
        if str(edge.get("kind_family") or "") not in ("iface", "contact"):
            continue
        if str(edge.get("kind") or "") == "clearance" or str(edge.get("status") or "") == "rejected":
            continue
        ends = [edge.get("a"), edge.get("b")]
        members = edge.get("members")
        if isinstance(members, (list, tuple)):
            ends.extend(members)
        for nid in {str(x) for x in ends if x}:
            degree[nid] = degree.get(nid, 0) + 1
    return degree


def _neighborhood(nid: str, edges: Sequence[Mapping[str, Any]]) -> set[str]:
    out: set[str] = set()
    for edge in edges:
        if str(edge.get("kind_family") or "") not in ("iface", "contact"):
            continue
        if str(edge.get("kind") or "") == "clearance":
            continue
        a, b = str(edge.get("a") or ""), str(edge.get("b") or "")
        if a == nid:
            out.add(b)
        elif b == nid:
            out.add(a)
    return out


# ---------------------------------------------------------------- 본체
def compute_diff(base_ir: Mapping[str, Any], target_ir: Mapping[str, Any], *,
                 base_state: Mapping[str, Any] | None = None,
                 target_state: Mapping[str, Any] | None = None,
                 links: Sequence[Mapping[str, Any]] | None = None,
                 pair_kind: str = "same_project_revision",
                 dim_tols: Mapping[str, tuple] | None = None,
                 project_id: str | None = None,
                 diff_id: str | None = None,
                 created_at: int | None = None) -> dict:
    """rr_ir 두 개로 §3.3 규격의 rr_diff 봉투를 만든다. LLM 개입 없는 결정론 산출이고 판단을 담지 않는다.

    `links` 는 §2.6 pair 스코프 대응이다(없으면 `sameas.resolve` 로 만든다).
    G6 차단 여부는 호출자가 `check_pair_blocked` 로 먼저 본다 — 여기서는 comparability 에 표기만 한다.
    """
    base_nodes = list(base_ir.get("nodes") or [])
    target_nodes = list(target_ir.get("nodes") or [])
    base_edges = [e for e in (base_ir.get("edges") or []) if str(e.get("status") or "") != "rejected"]
    target_edges = [e for e in (target_ir.get("edges") or []) if str(e.get("status") or "") != "rejected"]

    if links is None:
        links = sameas.resolve(base_nodes, target_nodes, base_edges, target_edges, "pair", None)

    comp = comparability(base_ir, target_ir, base_state, target_state)
    corr = _correspondence(base_nodes, target_nodes, links)
    base_by, target_by = _by_nid(base_nodes), _by_nid(target_nodes)

    # base·target 노드를 하나의 dn 으로 접는다 — 엣지 조인과 cid 의 키다.
    dn_of: dict[str, str] = {}
    method_of: dict[str, str] = {}
    target_to_base: dict[str, str] = {}
    for m in corr["matched"]:
        dn_of[m["nid_base"]] = m["dn"]
        dn_of[m["nid_target"]] = m["dn"]
        method_of[m["dn"]] = m["method"]
        target_to_base[m["nid_target"]] = m["nid_base"]
    for nid, node in base_by.items():
        dn_of.setdefault(nid, _dn(node, nid))
    for nid, node in target_by.items():
        dn_of.setdefault(nid, _dn(node, nid))

    ckey_of: dict[str, str | None] = {}
    for m in corr["matched"]:
        ckey_of[m["dn"]] = m["ckey"]
    for nid, node in list(base_by.items()) + list(target_by.items()):
        ckey_of.setdefault(dn_of[nid], node.get("ckey"))

    g2_fail = _gate_fail(base_state, "G2") or _gate_fail(target_state, "G2") or corr["pending_n"] > 0
    g4_fail = not comp["coordinate_ok"]
    g5_fail = _gate_fail(base_state, "G5") or _gate_fail(target_state, "G5") or comp["partial_any"]

    structural = _structural(base_by, target_by, base_edges, target_edges, corr, dn_of, ckey_of,
                             comp, g4_fail, g5_fail)
    parametric = _parametric(base_by, target_by, base_edges, target_edges, corr, dn_of, ckey_of,
                             base_ir, target_ir, comp, dim_tols or {}, g5_fail)
    semantic = _semantic(structural, parametric, corr, dn_of, ckey_of, method_of,
                         base_by, target_by, comp, g2_fail, g4_fail)

    _apply_source_parity(comp, structural, parametric, semantic)

    events = semantic["events"]
    kinds: dict[str, int] = {}
    for event in events:
        kinds[event["change_kind"]] = kinds.get(event["change_kind"], 0) + 1
    confidences: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for event in events:
        confidences[event["confidence"]] = confidences.get(event["confidence"], 0) + 1

    # 파서 세대가 섞인 수치 변화를 설계 성향으로 학습하지 않는다(plan §3.3.6 마지막 문단).
    character_seed = [] if comp["app_version_parity"] is False else _change_style_seed(events)

    all_params = (parametric["node_params"] + parametric["edge_params"] + parametric["dims_delta"]
                  + parametric["result_delta"])
    stats = {
        "nodes_added": sum(1 for c in structural["node_changes"] if c["op"] == "added"),
        "nodes_removed": sum(1 for c in structural["node_changes"] if c["op"] == "removed"),
        "nodes_matched": len(corr["matched"]),
        "edges_added": sum(1 for c in structural["edge_changes"] if c["op"] == "added"),
        "edges_removed": sum(1 for c in structural["edge_changes"] if c["op"] == "removed"),
        "edges_kind_changed": sum(1 for c in structural["edge_changes"] if c["op"] == "kind_changed"),
        "params_changed": sum(1 for p in all_params if p["flag"] == "changed" and not p["excluded_reason"]),
        "params_noise": sum(1 for p in all_params if p["flag"] == "noise"),
        "params_excluded": sum(1 for p in all_params if p["excluded_reason"]),
        "events": len(events),
        "events_by_change_kind": dict(sorted(kinds.items())),
        "events_by_confidence": confidences,
        "excluded_by_reason": _excluded_counts(structural, parametric),
    }

    diff = {
        "diff_version": DIFF_VERSION,
        "diff_id": diff_id or "",
        "project_id": project_id or target_ir.get("project_id") or "",
        "pair_kind": pair_kind,
        "base": {"snapshot_id": base_ir.get("snapshot_id"), "ir_hash": base_ir.get("ir_hash"),
                 "label": base_ir.get("label")},
        "target": {"snapshot_id": target_ir.get("snapshot_id"), "ir_hash": target_ir.get("ir_hash"),
                   "label": target_ir.get("label")},
        "taxonomy_version": _dig(target_ir, "versions", "taxonomy_version"),
        "rule_version": (target_state or {}).get("rule_version"),
        "comparability": comp,
        "correspondence": corr,
        "structural": structural,
        "parametric": parametric,
        "semantic": semantic,
        "character_seed": character_seed,
        "stats": stats,
        "summary_text": "",
        "summary_status": "ok",
        "created_at": created_at if created_at is not None else now_epoch(),
    }
    diff["summary_text"], diff["summary_status"] = _summary_text(diff)
    return diff


def changed_ckeys(diff_obj: Mapping[str, Any],
                  resolve: Callable[[str], str] | None = None) -> list[str]:
    """§6.5 2 — 이 diff 가 건드린 유효 ckey 목록(정렬). stale·carried 판정의 입력이다.

    모으는 곳은 `node_changes` · `edge_changes` 의 두 끝점 · 파라메트릭 `changed` 항목 · `dims_delta` 다.
    `excluded_reason` 이 붙은 항목은 잣대가 달라 비교가 성립하지 않으므로 넣지 않고(§3.3.6),
    `design_relevant=false`(mesh.density_changed·status_changed 유래)도 뺀다(§3.3.5).
    `resolve` 를 주면 `merged_into` 를 해석한 유효 ckey 로 접는다(§5.9.1 resolve_ckey).
    """
    out: set[str] = set()

    def add(value: Any) -> None:
        if not value:
            return
        key = str(value)
        out.add(str(resolve(key)) if resolve else key)

    structural = diff_obj.get("structural") or {}
    for change in structural.get("node_changes") or []:
        if change.get("excluded_reason"):
            continue
        add(change.get("ckey"))
    for change in structural.get("edge_changes") or []:
        if change.get("excluded_reason") or change.get("op") == "status_changed":
            continue
        add(change.get("ckey_a"))
        add(change.get("ckey_b"))

    parametric = diff_obj.get("parametric") or {}
    for key in ("node_params", "edge_params", "materials", "dims_delta", "result_delta"):
        for item in parametric.get(key) or []:
            if item.get("excluded_reason") or item.get("design_relevant") is False:
                continue
            if item.get("flag") != "changed":
                continue
            add(item.get("ckey"))
            add(item.get("ckey_a"))
            add(item.get("ckey_b"))
    return sorted(out)


def _excluded_counts(structural: Mapping[str, Any], parametric: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in list(structural["edge_changes"]) + list(parametric["node_params"]) \
            + list(parametric["edge_params"]) + list(parametric["dims_delta"]) \
            + list(parametric["result_delta"]):
        reason = item.get("excluded_reason")
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


# ---------------------------------------------------------------- 구조층
def _structural(base_by, target_by, base_edges, target_edges, corr, dn_of, ckey_of,
                comp, g4_fail, g5_fail) -> dict:
    node_changes: list[dict] = []
    unmatched_base = list(corr["unmatched_base"])
    unmatched_target = list(corr["unmatched_target"])

    # replaced — removed X·added Y 가 1홉 이웃을 ≥50% 공유하고 fuzzy 점수 0.5~0.7(§3.3.3).
    replaced_pairs: list[tuple[str, str, float]] = []
    used_b: set[str] = set()
    used_t: set[str] = set()
    candidates: list[tuple[float, str, str]] = []
    for b_nid in unmatched_base:
        nb = {dn_of.get(x, x) for x in _neighborhood(b_nid, base_edges)}
        for t_nid in unmatched_target:
            nt = {dn_of.get(x, x) for x in _neighborhood(t_nid, target_edges)}
            if not nb and not nt:
                continue
            share = len(nb & nt) / max(1, len(nb | nt))
            if share < 0.5:
                continue
            score = sameas.score_pair(base_by[b_nid], target_by[t_nid], nb, nt)["score"]
            if 0.5 <= score < sameas.PENDING_SCORE:
                candidates.append((score, b_nid, t_nid))
    for score, b_nid, t_nid in sorted(candidates, key=lambda t: (-t[0], t[1], t[2])):
        if b_nid in used_b or t_nid in used_t:
            continue
        used_b.add(b_nid)
        used_t.add(t_nid)
        replaced_pairs.append((b_nid, t_nid, score))

    # split / merged — 같은 name_norm_canon 안에서 1↔n 이고 부피 합이 2% 안(§3.3.3).
    split_groups, merged_groups = _split_merge(base_by, target_by,
                                               [n for n in unmatched_base if n not in used_b],
                                               [n for n in unmatched_target if n not in used_t])
    for group in split_groups:
        used_b.add(group["base"])
        used_t.update(group["targets"])
    for group in merged_groups:
        used_t.add(group["target"])
        used_b.update(group["bases"])

    for b_nid, t_nid, score in replaced_pairs:
        base_node, target_node = base_by[b_nid], target_by[t_nid]
        dn = dn_of.get(b_nid, b_nid)
        node_changes.append(_node_change("replaced", dn, b_nid, t_nid, base_node, target_node,
                                         base_edges, dn_of, ckey_of, "fuzzy", score))
    for group in split_groups:
        b_nid = group["base"]
        dn = dn_of.get(b_nid, b_nid)
        change = _node_change("split", dn, b_nid, None, base_by[b_nid], None,
                              base_edges, dn_of, ckey_of, "fuzzy", None)
        change["nids_target"] = group["targets"]
        node_changes.append(change)
    for group in merged_groups:
        t_nid = group["target"]
        dn = dn_of.get(t_nid, t_nid)
        change = _node_change("merged", dn, None, t_nid, None, target_by[t_nid],
                              target_edges, dn_of, ckey_of, "fuzzy", None)
        change["nids_base"] = group["bases"]
        node_changes.append(change)

    for nid in unmatched_base:
        if nid in used_b:
            continue
        node_changes.append(_node_change("removed", dn_of.get(nid, nid), nid, None, base_by[nid], None,
                                         base_edges, dn_of, ckey_of, "", None,
                                         excluded_reason="partial_scope" if (g5_fail and _scope_out(base_by[nid])) else None))
    for nid in unmatched_target:
        if nid in used_t:
            continue
        node_changes.append(_node_change("added", dn_of.get(nid, nid), None, nid, None, target_by[nid],
                                         target_edges, dn_of, ckey_of, "", None,
                                         excluded_reason="partial_scope" if (g5_fail and _scope_out(target_by[nid])) else None))

    # moved_in_tree — 같은 dn 의 parent asm_key 가 다르다.
    hierarchy_moves: list[dict] = []
    for m in corr["matched"]:
        base_node, target_node = base_by[m["nid_base"]], target_by[m["nid_target"]]
        if base_node.get("asm_key") == target_node.get("asm_key"):
            continue
        change = _node_change("moved_in_tree", m["dn"], m["nid_base"], m["nid_target"],
                              base_node, target_node, base_edges, dn_of, ckey_of, m["method"], m["score"])
        change["asm_key_from"] = base_node.get("asm_key")
        change["asm_key_to"] = target_node.get("asm_key")
        node_changes.append(change)
        hierarchy_moves.append(change)

    node_changes.sort(key=lambda c: c["cid"])

    # --- 엣지
    base_index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for edge in base_edges:
        base_index.setdefault(_edge_key(edge, dn_of), edge)
    target_index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for edge in target_edges:
        target_index.setdefault(_edge_key(edge, dn_of), edge)

    edge_changes: list[dict] = []
    for key in sorted(set(base_index) | set(target_index)):
        before, after = base_index.get(key), target_index.get(key)
        change = _edge_change(key, before, after, base_by, target_by, dn_of, ckey_of,
                              comp, g4_fail, g5_fail)
        if change is not None:
            edge_changes.append(change)
    edge_changes.sort(key=lambda c: c["cid"])

    base_degree = _degree_no_clearance(base_edges)
    target_degree = _degree_no_clearance(target_edges)
    base_orphans = sorted({dn_of.get(n, n) for n in base_by if base_degree.get(n, 0) == 0})
    target_orphans = sorted({dn_of.get(n, n) for n in target_by if target_degree.get(n, 0) == 0})
    orphans_delta = {
        "base": base_orphans, "target": target_orphans,
        "became_orphan": sorted(set(target_orphans) - set(base_orphans)),
        "left_orphan": sorted(set(base_orphans) - set(target_orphans)),
    }

    dyna = _dyna_structural(edge_changes, base_edges, target_edges, dn_of)
    return {"node_changes": node_changes, "edge_changes": edge_changes,
            "orphans_delta": orphans_delta, "hierarchy_moves": hierarchy_moves, "dyna": dyna}


def _node_change(op, dn, nid_base, nid_target, base_node, target_node, edges, dn_of, ckey_of,
                 method, score, excluded_reason=None) -> dict:
    node = target_node if target_node is not None else base_node
    nid = nid_target or nid_base or dn
    neighborhood = sorted({ckey_of.get(dn_of.get(x, x)) or dn_of.get(x, x)
                           for x in _neighborhood(str(nid), edges)})
    cid = cid_for("structural", op, dn, "", "")
    return {
        "cid": cid, "op": op, "dn": dn, "nid_base": nid_base, "nid_target": nid_target,
        "ckey": ckey_of.get(dn), "label": _label(node), "kind": (node or {}).get("kind"),
        "domain": (node or {}).get("domain"), "neighborhood_1hop": neighborhood,
        "correspondence_method": method or None, "correspondence_score": score,
        "excluded_reason": excluded_reason,
        "confidence": _confidence(method or "", None),
        "text": f"{_label(node)} {op} [{cid}]",
    }


def _split_merge(base_by, target_by, free_base, free_target) -> tuple[list[dict], list[dict]]:
    """같은 name_norm_canon 그룹에서 1↔n 이고 부피 합 오차 ≤2% 인 분할·병합을 찾는다."""
    def canon(node) -> str:
        return str(node.get("name_norm_canon") or node.get("name_norm") or "")

    groups: dict[str, tuple[list[str], list[str]]] = {}
    for nid in free_base:
        groups.setdefault(canon(base_by[nid]), ([], []))[0].append(nid)
    for nid in free_target:
        groups.setdefault(canon(target_by[nid]), ([], []))[1].append(nid)

    splits: list[dict] = []
    merges: list[dict] = []
    for key in sorted(groups):
        bases, targets = groups[key]
        if not key or not bases or not targets:
            continue
        b_vols = [_num(_dig(base_by[n], "attrs", "volume")) for n in sorted(bases)]
        t_vols = [_num(_dig(target_by[n], "attrs", "volume")) for n in sorted(targets)]
        if any(v is None for v in b_vols) or any(v is None for v in t_vols):
            continue
        b_sum, t_sum = sum(b_vols), sum(t_vols)  # type: ignore[arg-type]
        if b_sum <= 0 or abs(t_sum - b_sum) / b_sum > 0.02:
            continue
        if len(bases) == 1 and len(targets) >= 2:
            splits.append({"base": sorted(bases)[0], "targets": sorted(targets)})
        elif len(targets) == 1 and len(bases) >= 2:
            merges.append({"target": sorted(targets)[0], "bases": sorted(bases)})
    return splits, merges


def _edge_change(key, before, after, base_by, target_by, dn_of, ckey_of, comp, g4_fail, g5_fail) -> dict | None:
    family, dn_a, dn_b = key
    kind_from = str(before.get("kind")) if before is not None else None
    kind_to = str(after.get("kind")) if after is not None else None
    status_from = str(before.get("status")) if before is not None else None
    status_to = str(after.get("status")) if after is not None else None
    cross_file = bool(_dig(after or before or {}, "attrs", "cross_file"))

    if before is None and after is None:
        return None
    if before is None:
        op = "added"
    elif after is None:
        op = "removed"
    elif kind_from != kind_to:
        op = "kind_changed"
    elif status_from != status_to:
        op = "status_changed"
    else:
        return None

    excluded_reason = None
    if g5_fail:
        for dn in (dn_a, dn_b):
            b, t = None, None
            for nid, node in base_by.items():
                if dn_of.get(nid) == dn:
                    b = node
                    break
            for nid, node in target_by.items():
                if dn_of.get(nid) == dn:
                    t = node
                    break
            if _scope_out(b) or _scope_out(t):
                excluded_reason = "partial_scope"
                break
    if excluded_reason is None and family == "iface" and comp["tol_parity"] is not True:
        # clearance 의 등장·소멸은 tol 에 종속한다(§3.3.5 iface.clearance_* 비고).
        if "clearance" in (kind_from, kind_to) and op in ("added", "removed"):
            excluded_reason = "tol_differs" if comp["tol_parity"] is False else "tol_unknown"

    rank_from = RANK.get(kind_from or "", None)
    rank_to = RANK.get(kind_to or "", None)
    rank_delta = None if (rank_from is None or rank_to is None) else rank_to - rank_from
    cid = cid_for("structural", f"edge.{op}", dn_a, dn_b, family)
    status = status_to or status_from
    confidence = _confidence("", status, cross_file_suspect=g4_fail and cross_file)
    suffix = " (cross_file, 좌표계 의심)" if (g4_fail and cross_file) else ""
    if status == "auto" and (kind_to or kind_from) == "interference":
        suffix += " status=auto(미확정 초안)"
    text = f"{dn_a}↔{dn_b} {family} {op}"
    if op == "kind_changed":
        text += f" {kind_from}→{kind_to} (rank {rank_from}→{rank_to})"
    elif op == "status_changed":
        text += f" {status_from}→{status_to}"
    return {
        "cid": cid, "op": op, "kind_family": family,
        "eid_base": (before or {}).get("eid"), "eid_target": (after or {}).get("eid"),
        "dn_a": dn_a, "dn_b": dn_b, "ckey_a": ckey_of.get(dn_a), "ckey_b": ckey_of.get(dn_b),
        "kind_from": kind_from, "kind_to": kind_to,
        "rank_from": rank_from, "rank_to": rank_to, "rank_delta": rank_delta,
        "status_from": status_from, "status_to": status_to,
        "cross_file": cross_file, "excluded_reason": excluded_reason, "confidence": confidence,
        "text": f"{text}{suffix} [{cid}]",
    }


def _dyna_structural(edge_changes, base_edges, target_edges, dn_of) -> dict:
    contacts_added = [c["cid"] for c in edge_changes
                      if c["kind_family"] == "contact" and c["op"] == "added"]
    contacts_removed = [c["cid"] for c in edge_changes
                        if c["kind_family"] == "contact" and c["op"] == "removed"]

    def scope_map(edges) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for edge in edges:
            if str(edge.get("kind") or "") != "scope":
                continue
            at = _attrs(edge)
            index = at.get("contact_index")
            if index is None:
                continue
            members = [str(m) for m in (edge.get("members") or [])]
            out[int(index)] = {"pids": sorted(members),
                               "dns": sorted({dn_of.get(m, m) for m in members})}
        return out

    base_scopes, target_scopes = scope_map(base_edges), scope_map(target_edges)
    scope_changed = []
    for index in sorted(set(base_scopes) | set(target_scopes)):
        before = base_scopes.get(index, {"pids": [], "dns": []})
        after = target_scopes.get(index, {"pids": [], "dns": []})
        if before["dns"] == after["dns"]:
            continue
        cid = cid_for("structural", "contact.scope_changed", str(index), "", "")
        scope_changed.append({"cid": cid, "contact_index": index,
                              "pids_before": before["pids"], "pids_after": after["pids"],
                              "dns_before": before["dns"], "dns_after": after["dns"],
                              "text": f"contact#{index} scope 멤버 {len(before['dns'])}→{len(after['dns'])} [{cid}]"})
    return {"contacts_added": contacts_added, "contacts_removed": contacts_removed,
            "scope_changed": scope_changed}


# ---------------------------------------------------------------- 파라메트릭층
def _node_attr_values(node: Mapping[str, Any]) -> dict[str, Any]:
    """노드에서 임계표가 보는 값들을 뽑는다. 없으면 None(미측정)이다."""
    at = _attrs(node)
    out: dict[str, Any] = {}
    size_def = at.get("size_def") if isinstance(at.get("size_def"), (list, tuple)) else _bbox_dims(at.get("bbox_def"))
    if not size_def and isinstance(at.get("size"), (list, tuple)):
        size_def = at.get("size")
    world = _bbox_dims(at.get("bbox_world"))
    centroid = at.get("centroid_world") if isinstance(at.get("centroid_world"), (list, tuple)) else None
    for i, axis in enumerate(_AXES):
        out[f"bbox_def_dims[{i}]"] = _num(size_def[i]) if size_def and len(size_def) > i else None
        out[f"bbox_world_dims[{i}]"] = _num(world[i]) if world and len(world) > i else None
        out[f"centroid_world[{i}]"] = _num(centroid[i]) if centroid and len(centroid) > i else None
    out["min_dim"] = _num(at.get("min_dim"))
    out["volume"] = _num(at.get("volume"))
    out["area"] = _num(at.get("area")) if at.get("area") is not None else _num(at.get("area_ext"))
    out["n_elems"] = _num(at.get("n_elems"))
    material = at.get("material") if isinstance(at.get("material"), Mapping) else {}
    for field in ("E", "rho", "sigy", "nu"):
        out[f"material.{field}"] = _num(material.get(field))
    return out


_NODE_ATTRS: tuple[str, ...] = tuple(
    [f"bbox_def_dims[{i}]" for i in range(3)]
    + [f"bbox_world_dims[{i}]" for i in range(3)]
    + [f"centroid_world[{i}]" for i in range(3)]
    + ["min_dim", "volume", "area", "n_elems", "material.E", "material.rho", "material.sigy", "material.nu"]
)


def _rule_for_node_attr(attr: str) -> dict:
    base = attr.split("[")[0]
    return PARAM_RULES[base]


def _text_attr(attr: str) -> str:
    if attr.startswith("bbox_def_dims["):
        return f"bbox_d{_AXES[int(attr[-2])]}"
    if attr.startswith("bbox_world_dims["):
        return f"bbox_world_d{_AXES[int(attr[-2])]}"
    if attr.startswith("centroid_world["):
        return f"centroid_world_{_AXES[int(attr[-2])]}"
    return attr


def _size_pct(volume: float | None, volumes: Sequence[float]) -> int | None:
    """target 스냅샷 안에서의 volume 백분위(0~100). 미세 파트가 상대 순위를 독점하는 것을 표에서 가려낸다."""
    if volume is None or not volumes:
        return None
    below = sum(1 for v in volumes if v <= volume)
    return int(round(100.0 * below / len(volumes)))


def _parametric(base_by, target_by, base_edges, target_edges, corr, dn_of, ckey_of,
                base_ir, target_ir, comp, dim_tols, g5_fail) -> dict:
    target_volumes = sorted(v for v in (_num(_dig(n, "attrs", "volume")) for n in target_by.values())
                            if v is not None)

    node_params: list[dict] = []
    materials: list[dict] = []
    for m in sorted(corr["matched"], key=lambda x: x["dn"]):
        base_node, target_node = base_by[m["nid_base"]], target_by[m["nid_target"]]
        before_vals, after_vals = _node_attr_values(base_node), _node_attr_values(target_node)
        label = _label(target_node)
        excluded = "partial_scope" if (g5_fail and (_scope_out(base_node) or _scope_out(target_node))) else None
        size_pct = _size_pct(after_vals["volume"], target_volumes)
        for attr in _NODE_ATTRS:
            before, after = before_vals[attr], after_vals[attr]
            if before is None and after is None:
                continue
            rule = _rule_for_node_attr(attr)
            item = _param_item("node", ckey_of.get(m["dn"]) or m["dn"], label, attr, before, after, rule,
                               key_a=m["dn"], excluded_reason=excluded, text_attr=_text_attr(attr),
                               extra={"dn": m["dn"], "ckey": ckey_of.get(m["dn"]),
                                      "design_relevant": attr != "n_elems"})
            item["size_pct"] = size_pct
            node_params.append(item)
        materials.extend(_material_changes(m["dn"], ckey_of.get(m["dn"]), base_node, target_node, label))

    edge_params = _edge_params(base_edges, target_edges, base_by, target_by, dn_of, ckey_of, comp, g5_fail)
    dims_delta = _dims_delta(base_ir, target_ir, dim_tols)
    result_delta = _result_delta(base_ir, target_ir, dn_of, ckey_of, comp)
    rollup_delta = _rollup_delta(base_ir, target_ir)

    node_params.sort(key=lambda p: p["cid"])
    materials.sort(key=lambda p: p["cid"])
    return {"node_params": node_params, "edge_params": edge_params, "materials": materials,
            "dims_delta": dims_delta, "result_delta": result_delta, "rollup_delta": rollup_delta}


_MATERIAL_FIELDS = ("name", "material_norm", "mid", "keyword", "match_basis")


def _material_value(node: Mapping[str, Any], field: str) -> Any:
    at = _attrs(node)
    if field == "material_norm":
        return node.get("material_norm") or sameas.material_norm_of(node)
    material = at.get("material")
    if isinstance(material, Mapping):
        if field == "match_basis":
            return _dig(material, "db", "match_basis")
        return material.get(field)
    if field == "name":
        return at.get("material")
    return None


def _material_changes(dn, ckey, base_node, target_node, label) -> list[dict]:
    out: list[dict] = []
    for field in _MATERIAL_FIELDS:
        before, after = _material_value(base_node, field), _material_value(target_node, field)
        if before == after or (before is None and after is None):
            continue
        cid = cid_for("parametric", "material", dn, "", field)
        out.append({"cid": cid, "dn": dn, "ckey": ckey, "field": field,
                    "before": before, "after": after, "flag": "changed",
                    "excluded_reason": None, "design_relevant": True,
                    "text": f"{label} material.{field} {before}→{after} [{cid}]"})
    return out


def _edge_params(base_edges, target_edges, base_by, target_by, dn_of, ckey_of, comp, g5_fail) -> list[dict]:
    base_index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for edge in base_edges:
        base_index.setdefault(_edge_key(edge, dn_of), edge)
    target_index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for edge in target_edges:
        target_index.setdefault(_edge_key(edge, dn_of), edge)

    tol_reason = None
    if comp["tol_parity"] is False:
        tol_reason = "tol_differs"
    elif comp["tol_parity"] is None:
        tol_reason = "tol_unknown"

    items: list[dict] = []
    for key in sorted(set(base_index) & set(target_index)):
        family, dn_a, dn_b = key
        before_edge, after_edge = base_index[key], target_index[key]
        ba, aa = _attrs(before_edge), _attrs(after_edge)
        subject = "|".join(sorted([ckey_of.get(dn_a) or dn_a, ckey_of.get(dn_b) or dn_b]))
        label = f"{dn_a}↔{dn_b}"
        node_a = next((n for nid, n in target_by.items() if dn_of.get(nid) == dn_a), None) \
            or next((n for nid, n in base_by.items() if dn_of.get(nid) == dn_a), None)
        node_b = next((n for nid, n in target_by.items() if dn_of.get(nid) == dn_b), None) \
            or next((n for nid, n in base_by.items() if dn_of.get(nid) == dn_b), None)
        diags = [d for d in (_diag(node_a), _diag(node_b)) if d is not None]
        d_small = min(diags) if diags else None

        attr_list = ["min_gap", "contact_area_est", "band_width", "penetration_depth", "penetration_volume"] \
            if family == "iface" else ["fs"]
        for attr in attr_list:
            before, after = _num(ba.get(attr)), _num(aa.get(attr))
            if before is None and after is None:
                continue
            rule = PARAM_RULES[attr]
            abs_floor = None
            if attr == "contact_area_est" and d_small is not None:
                abs_floor = 0.01 * d_small ** 2
            elif attr == "band_width" and d_small is not None:
                abs_floor = 0.05 * d_small
            reason = tol_reason if (attr in TOL_DEPENDENT and tol_reason) else None
            if g5_fail and (_scope_out(node_a) or _scope_out(node_b)):
                reason = "partial_scope"
            suffix = ""
            lower_bound = bool(ba.get("penetration_depth_is_lower_bound")) or \
                bool(aa.get("penetration_depth_is_lower_bound"))
            if attr == "penetration_depth" and lower_bound:
                suffix = " (lower_bound)"
            if attr == "contact_area_est":
                suffix += "(밴드면적)"
            item = _param_item("edge", subject, label, attr, before, after, rule,
                               key_a=dn_a, key_b=dn_b, abs_floor=abs_floor,
                               excluded_reason=reason, text_suffix=suffix,
                               extra={"eid_base": before_edge.get("eid"), "eid_target": after_edge.get("eid"),
                                      "dn_a": dn_a, "dn_b": dn_b,
                                      "ckey_a": ckey_of.get(dn_a), "ckey_b": ckey_of.get(dn_b),
                                      "kind_family": family, "design_relevant": True})
            if attr == "penetration_depth":
                item["lower_bound"] = lower_bound
                if bool(ba.get("penetration_depth_is_lower_bound")) and \
                        bool(aa.get("penetration_depth_is_lower_bound")):
                    item["flag"] = "incomparable"
            items.append(item)
    items.sort(key=lambda p: p["cid"])
    return items


def _dims_delta(base_ir, target_ir, dim_tols) -> list[dict]:
    def index(ir) -> dict[str, Mapping[str, Any]]:
        out: dict[str, Mapping[str, Any]] = {}
        for row in ir.get("dims_named") or []:
            if isinstance(row, Mapping) and row.get("name"):
                out[str(row["name"])] = row
        return out

    base_index, target_index = index(base_ir), index(target_ir)
    items: list[dict] = []
    for name in sorted(set(base_index) | set(target_index)):
        before_row, after_row = base_index.get(name, {}), target_index.get(name, {})
        tol_abs, tol_rel = dim_tols.get(name, DIM_DEFAULT_TOL)
        rule = {"abs": tol_abs if tol_abs is not None else DIM_DEFAULT_TOL[0],
                "rel": tol_rel if tol_rel is not None else DIM_DEFAULT_TOL[1],
                "mode": "AND", "unit": after_row.get("unit") or before_row.get("unit"), "round": "length"}
        item = _param_item("dim", f"dim:{name}", f"dim:{name}", "value",
                           before_row.get("value"), after_row.get("value"), rule,
                           key_a=f"dim:{name}",
                           extra={"name": name, "method": after_row.get("method") or before_row.get("method"),
                                  "null_reason": after_row.get("null_reason"), "design_relevant": True})
        item["text"] = item["text"].replace("dim:%s value" % name, name, 1) + f" [d:{name}]"
        items.append(item)
    return items


def _result_delta(base_ir, target_ir, dn_of, ckey_of, comp) -> list[dict]:
    base_results = base_ir.get("results") if isinstance(base_ir.get("results"), Mapping) else None
    target_results = target_ir.get("results") if isinstance(target_ir.get("results"), Mapping) else None
    if base_results is None or target_results is None:
        return []
    reason = None if comp["result_parity"] else comp["result_reason"]

    def index(results) -> dict[str, Mapping[str, Any]]:
        out: dict[str, Mapping[str, Any]] = {}
        for row in results.get("part_risk") or []:
            if isinstance(row, Mapping) and row.get("nid"):
                out[dn_of.get(str(row["nid"]), str(row["nid"]))] = row
        return out

    base_index, target_index = index(base_results), index(target_results)
    items: list[dict] = []
    for dn in sorted(set(base_index) & set(target_index)):
        before_row, after_row = base_index[dn], target_index[dn]
        for metric in RESULT_METRICS:
            before_raw, after_raw = before_row.get(metric), after_row.get(metric)
            before = _num(before_raw.get("value")) if isinstance(before_raw, Mapping) else _num(before_raw)
            after = _num(after_raw.get("value")) if isinstance(after_raw, Mapping) else _num(after_raw)
            if before is None and after is None:
                continue
            rule = PARAM_RULES[metric]
            item = _param_item("result", ckey_of.get(dn) or dn, dn, metric, before, after, rule,
                               key_a=dn, key_b=metric, excluded_reason=reason,
                               extra={"dn": dn, "ckey": ckey_of.get(dn),
                                      "pid_before": before_row.get("pid"), "pid_after": after_row.get("pid"),
                                      "metric": metric,
                                      "case_key_before": _dig(before_raw, "case_key") if isinstance(before_raw, Mapping) else None,
                                      "case_key_after": _dig(after_raw, "case_key") if isinstance(after_raw, Mapping) else None,
                                      "kind": target_results.get("kind"), "design_relevant": True})
            items.append(item)
    items.sort(key=lambda p: p["cid"])
    return items


def _rollup_delta(base_ir, target_ir) -> list[dict]:
    def index(ir) -> dict[str, Mapping[str, Any]]:
        out: dict[str, Mapping[str, Any]] = {}
        for row in _dig(ir, "rollups", "by_assembly") or []:
            if isinstance(row, Mapping) and row.get("path_prefix"):
                out[str(row["path_prefix"])] = row
        return out

    base_index, target_index = index(base_ir), index(target_ir)
    items: list[dict] = []
    for prefix in sorted(set(base_index) | set(target_index)):
        before, after = base_index.get(prefix, {}), target_index.get(prefix, {})

        def total(row, field) -> int | None:
            value = row.get(field)
            if isinstance(value, Mapping):
                return sum(int(v) for v in value.values() if isinstance(v, int))
            return None

        cid = cid_for("parametric", "rollup", f"asm:{prefix}", "", "")
        items.append({
            "cid": cid, "asm_key": prefix, "path_prefix": prefix,
            "n_leaf": {"before": before.get("n_leaf"), "after": after.get("n_leaf")},
            "edges_internal": {"before": total(before, "edges_internal"), "after": total(after, "edges_internal")},
            "edges_external": {"before": total(before, "edges_external"), "after": total(after, "edges_external")},
            "orphan_leaf": {"before": before.get("orphan_leaf"), "after": after.get("orphan_leaf")},
            "excluded_reason": None, "design_relevant": True,
            "text": f"asm:{prefix} 리프 {before.get('n_leaf')}→{after.get('n_leaf')} [{cid}]",
        })
    return items


# ---------------------------------------------------------------- 의미층(§3.3.5)
def _event(code: str, change_kind: str, *, dns: Sequence[str], ckeys: Sequence[Any],
           subject_key: str, names: Sequence[str], before: Any = None, after: Any = None,
           magnitude: Mapping[str, Any] | None = None, derived_from: Sequence[str] = (),
           eids: Mapping[str, Any] | None = None, neighborhood: Mapping[str, Any] | None = None,
           confidence: str = "high", design_relevant: bool = True, unconfirmed: bool = False,
           lower_bound: bool = False, excluded_reason: str | None = None, text: str = "") -> dict:
    key_a = str(dns[0]) if dns else ""
    key_b = str(dns[1]) if len(dns) > 1 else ""
    cid = cid_for("semantic", code, key_a, key_b, "")
    return {
        "cid": cid, "code": code, "change_kind": change_kind,
        "subject": {"dns": list(dns), "ckeys": list(ckeys), "eids": dict(eids or {}), "names": list(names)},
        "subject_key": subject_key,
        "before": before, "after": after,
        "magnitude": dict(magnitude) if magnitude else {"value": None, "unit": None, "rel": None},
        "derived_from": list(derived_from),
        "neighborhood": dict(neighborhood or {"k": 1, "ckeys": []}),
        "confidence": confidence, "design_relevant": design_relevant,
        "unconfirmed": unconfirmed, "lower_bound": lower_bound,
        "excluded_reason": excluded_reason,
        "text": f"{text or code} [{cid}]",
    }


def _semantic(structural, parametric, corr, dn_of, ckey_of, method_of, base_by, target_by,
              comp, g2_fail, g4_fail) -> dict:
    if g2_fail:
        # G2 fail 의 effect 는 block_semantic — 구조·파라메트릭층은 남기고 의미 이벤트만 만들지 않는다(§3.2.2).
        return {"blocked_by": "G2", "events": []}

    events: list[dict] = []

    def subject_part(dn: str) -> str:
        return ckey_of.get(dn) or dn

    def method(dn: str) -> str:
        return method_of.get(dn, "")

    # --- 구조 유래
    for change in structural["node_changes"]:
        if change["excluded_reason"]:
            continue
        dn = change["dn"]
        code_map = {"added": ("part.added", "count"), "removed": ("part.removed", "count"),
                    "replaced": ("part.replaced", "type"), "split": ("part.split", "count"),
                    "merged": ("part.merged", "count"), "moved_in_tree": ("part.tree_moved", "topology")}
        if change["op"] not in code_map:
            continue
        code, change_kind = code_map[change["op"]]
        confidence = _confidence(change.get("correspondence_method") or "")
        if change["op"] == "replaced" and confidence == "high":
            confidence = "medium"
        events.append(_event(code, change_kind, dns=[dn], ckeys=[change["ckey"]],
                             subject_key=subject_part(dn), names=[change["label"]],
                             derived_from=[change["cid"]], confidence=confidence,
                             neighborhood={"k": 1, "ckeys": change["neighborhood_1hop"]},
                             text=f"{change['label']} {code}"))

    for change in structural["edge_changes"]:
        if change["excluded_reason"] or change["op"] == "status_changed":
            continue
        family = change["kind_family"]
        dn_a, dn_b = change["dn_a"], change["dn_b"]
        subject_key = "|".join(sorted([ckey_of.get(dn_a) or dn_a, ckey_of.get(dn_b) or dn_b]))
        common = dict(dns=[dn_a, dn_b], ckeys=[change["ckey_a"], change["ckey_b"]],
                      subject_key=subject_key, names=[dn_a, dn_b],
                      eids={"base": change["eid_base"], "target": change["eid_target"]},
                      derived_from=[change["cid"]], confidence=change["confidence"])
        if family == "iface":
            kind_from, kind_to = change["kind_from"], change["kind_to"]
            if change["op"] == "added":
                code = "iface.clearance_appeared" if kind_to == "clearance" else "iface.added"
                if kind_to != "clearance" and (RANK.get(kind_to or "", 0) < 1):
                    continue
                events.append(_event(code, "topology", before=None, after=kind_to,
                                     text=f"{dn_a}↔{dn_b} {code} ({kind_to})", **common))
            elif change["op"] == "removed":
                code = "iface.clearance_cleared" if kind_from == "clearance" else "iface.removed"
                if kind_from != "clearance" and (RANK.get(kind_from or "", 0) < 1):
                    continue
                events.append(_event(code, "topology", before=kind_from, after=None,
                                     text=f"{dn_a}↔{dn_b} {code} ({kind_from})", **common))
            else:                                     # kind_changed
                if kind_to == "interference":
                    code = "iface.interference_new"
                elif kind_from == "interference":
                    code = "iface.interference_cleared"
                elif (change["rank_delta"] or 0) > 0:
                    code = "iface.rank_up"
                elif (change["rank_delta"] or 0) < 0:
                    code = "iface.rank_down"
                else:
                    continue
                events.append(_event(code, "topology", before=kind_from, after=kind_to,
                                     magnitude={"value": change["rank_delta"], "unit": "rank", "rel": None},
                                     unconfirmed=(change["status_to"] == "auto"),
                                     text=f"{dn_a}↔{dn_b} kind {kind_from}→{kind_to} "
                                          f"(rank {change['rank_from']}→{change['rank_to']})",
                                     **common))
        elif family == "contact":
            if change["op"] == "added":
                events.append(_event("contact.added", "topology", text=f"{dn_a}↔{dn_b} contact.added", **common))
            elif change["op"] == "removed":
                events.append(_event("contact.removed", "topology", text=f"{dn_a}↔{dn_b} contact.removed", **common))
            else:
                events.append(_event("contact.type_changed", "contact_type",
                                     before=change["kind_from"], after=change["kind_to"],
                                     text=f"{dn_a}↔{dn_b} contact.type_changed", **common))

    for scope in structural["dyna"]["scope_changed"]:
        events.append(_event("contact.scope_changed", "topology",
                             dns=[f"contact#{scope['contact_index']}"], ckeys=[],
                             subject_key=f"contact#{scope['contact_index']}",
                             names=[f"contact#{scope['contact_index']}"],
                             before=len(scope["dns_before"]), after=len(scope["dns_after"]),
                             derived_from=[scope["cid"]], text=scope["text"].rsplit(" [", 1)[0]))

    # --- 파라메트릭 유래(노드)
    by_dn: dict[str, dict[str, dict]] = {}
    for item in parametric["node_params"]:
        by_dn.setdefault(item["dn"], {})[item["attr"]] = item
    for dn in sorted(by_dn):
        attrs = by_dn[dn]
        if any(a.get("excluded_reason") for a in attrs.values()):
            continue
        node_b, node_t = None, None
        for nid, node in base_by.items():
            if dn_of.get(nid) == dn:
                node_b = node
                break
        for nid, node in target_by.items():
            if dn_of.get(nid) == dn:
                node_t = node
                break
        label = _label(node_t or node_b)
        ckey = ckey_of.get(dn)
        conf = _confidence(method(dn))
        bbox_items = [attrs.get(f"bbox_def_dims[{i}]") for i in range(3)]
        bbox_changed = [x for x in bbox_items if x and x["flag"] == "changed"]
        bbox_noise = all((x is None or x["flag"] == "noise") for x in bbox_items)
        world_items = [attrs.get(f"bbox_world_dims[{i}]") for i in range(3)]
        world_changed = [x for x in world_items if x and x["flag"] == "changed"]
        centroid_items = [attrs.get(f"centroid_world[{i}]") for i in range(3)]
        centroid_deltas = [abs(x["delta"]) for x in centroid_items if x and x["delta"] is not None]
        centroid_shift = math.sqrt(sum(d ** 2 for d in centroid_deltas)) if centroid_deltas else None
        centroid_known = any(x is not None and x["flag"] != "null_one_side" for x in centroid_items)

        thickness = attrs.get("min_dim")
        if thickness and thickness["flag"] == "changed":
            events.append(_event("part.thickness_changed", "dimension", dns=[dn], ckeys=[ckey],
                                 subject_key=ckey or dn, names=[label],
                                 before=thickness["before"], after=thickness["after"],
                                 magnitude={"value": thickness["delta"], "unit": "mm",
                                            "rel": thickness["rel_delta"]},
                                 derived_from=[thickness["cid"]], confidence=conf,
                                 text=thickness["text"].rsplit(" [", 1)[0] + " (min_dim 근사)"))
        elif bbox_changed and (centroid_shift is None or centroid_shift < 0.05 or not centroid_known):
            first = bbox_changed[0]
            events.append(_event("part.resized", "dimension", dns=[dn], ckeys=[ckey],
                                 subject_key=ckey or dn, names=[label],
                                 before=first["before"], after=first["after"],
                                 magnitude={"value": first["delta"], "unit": "mm", "rel": first["rel_delta"]},
                                 derived_from=[x["cid"] for x in bbox_changed], confidence=conf,
                                 text=first["text"].rsplit(" [", 1)[0]))

        diag = _diag(node_t or node_b)
        move_floor = max(0.05, 0.002 * diag) if diag else 0.05
        if bbox_noise and centroid_shift is not None and centroid_shift >= move_floor:
            events.append(_event("part.moved", "placement", dns=[dn], ckeys=[ckey],
                                 subject_key=ckey or dn, names=[label],
                                 magnitude={"value": R(centroid_shift, "length"), "unit": "mm", "rel": None},
                                 derived_from=[x["cid"] for x in centroid_items if x], confidence=conf,
                                 text=f"{label} centroid_world 이동 {R(centroid_shift, 'length'):.3f} mm"))
        if bbox_noise and world_changed:
            events.append(_event("part.rotated", "placement", dns=[dn], ckeys=[ckey],
                                 subject_key=ckey or dn, names=[label],
                                 derived_from=[x["cid"] for x in world_changed], confidence=conf,
                                 text=f"{label} bbox_world_dims 변화(bbox_def noise)"))

        n_elems = attrs.get("n_elems")
        if n_elems and n_elems["flag"] == "changed":
            events.append(_event("mesh.density_changed", "discretization", dns=[dn], ckeys=[ckey],
                                 subject_key=ckey or dn, names=[label],
                                 before=n_elems["before"], after=n_elems["after"],
                                 magnitude={"value": n_elems["delta"], "unit": None, "rel": n_elems["rel_delta"]},
                                 derived_from=[n_elems["cid"]], confidence=conf, design_relevant=False,
                                 text=n_elems["text"].rsplit(" [", 1)[0]))
        material_num = [attrs.get(f"material.{f}") for f in ("E", "rho", "sigy")]
        material_changed = [x for x in material_num if x and x["flag"] == "changed"]
        material_rows = [m for m in parametric["materials"] if m["dn"] == dn]
        if material_changed or material_rows:
            events.append(_event("part.material_changed", "material", dns=[dn], ckeys=[ckey],
                                 subject_key=ckey or dn, names=[label],
                                 before=(material_rows[0]["before"] if material_rows else None),
                                 after=(material_rows[0]["after"] if material_rows else None),
                                 derived_from=[x["cid"] for x in material_changed] + [m["cid"] for m in material_rows],
                                 confidence=conf,
                                 text=(material_rows[0]["text"].rsplit(" [", 1)[0] if material_rows
                                       else f"{label} material 수치 변경")))

        # cross.bridge_stale — mcad 치수 변경인데 같은 클러스터의 dyna pid 가 전부 noise 다(§3.3.5).
        if (thickness and thickness["flag"] == "changed") or bbox_changed:
            if node_t is not None and str(node_t.get("domain")) == "mcad":
                dyna_all_noise = _dyna_noise(dn, dn_of, base_by, target_by, by_dn)
                if dyna_all_noise:
                    events.append(_event("cross.bridge_stale", "consistency", dns=[dn], ckeys=[ckey],
                                         subject_key=ckey or dn, names=[label], confidence="medium",
                                         text=f"{label} mcad 치수 변경, 같은 클러스터 dyna pid 는 bbox·n_elems noise"))

    # --- 파라메트릭 유래(엣지)
    edge_codes = {"min_gap": ("iface.gap_changed", "dimension"),
                  "contact_area_est": ("iface.band_area_changed", "dimension"),
                  "penetration_depth": ("iface.penetration_changed", "dimension"),
                  "fs": ("contact.friction_changed", "parameter")}
    for item in parametric["edge_params"]:
        if item["flag"] != "changed" or item["excluded_reason"]:
            continue
        mapping = edge_codes.get(item["attr"])
        if mapping is None:
            continue
        code, change_kind = mapping
        dn_a, dn_b = item["dn_a"], item["dn_b"]
        events.append(_event(code, change_kind, dns=[dn_a, dn_b],
                             ckeys=[item["ckey_a"], item["ckey_b"]], subject_key=item["subject_key"],
                             names=[dn_a, dn_b],
                             eids={"base": item.get("eid_base"), "target": item.get("eid_target")},
                             before=item["before"], after=item["after"],
                             magnitude={"value": item["delta"], "unit": item["unit"], "rel": item["rel_delta"]},
                             derived_from=[item["cid"]],
                             confidence=_confidence("", None, lower_bound=bool(item["lower_bound"])),
                             lower_bound=bool(item["lower_bound"]),
                             text=item["text"].rsplit(" [", 1)[0]))

    # --- 명명 치수·롤업·결과
    for item in parametric["dims_delta"]:
        if item["flag"] == "changed" and not item["excluded_reason"]:
            events.append(_event("dim.named_changed", "dimension", dns=[item["subject_key"]], ckeys=[],
                                 subject_key=item["subject_key"], names=[item["name"]],
                                 before=item["before"], after=item["after"],
                                 magnitude={"value": item["delta"], "unit": item["unit"], "rel": item["rel_delta"]},
                                 derived_from=[item["cid"]],
                                 text=item["text"].rsplit(" [c:", 1)[0]))
        elif item["flag"] == "null_one_side" and item["before"] is not None and item["after"] is None:
            # §3.3.5 는 `ref 소실` 만 이 코드로 낸다 — 양쪽 다 null 이면 소실이 아니라서 self-diff 가 0 건이어야 한다.
            events.append(_event("dim.named_unmeasured", "consistency", dns=[item["subject_key"]], ckeys=[],
                                 subject_key=item["subject_key"], names=[item["name"]],
                                 before=item["before"], after=item["after"],
                                 derived_from=[item["cid"]],
                                 text=f"{item['name']} 미측정 (null_reason={item.get('null_reason')})"))

    for item in parametric["rollup_delta"]:
        internal = item["edges_internal"]
        external = item["edges_external"]

        def moved(pair) -> bool:
            b, a = pair.get("before"), pair.get("after")
            return b is not None and a is not None and abs(a - b) >= 1

        if moved(internal) or moved(external):
            events.append(_event("asm.rollup_changed", "topology", dns=[f"asm:{item['asm_key']}"], ckeys=[],
                                 subject_key=f"asm:{item['asm_key']}", names=[item["asm_key"]],
                                 before=internal.get("before"), after=internal.get("after"),
                                 derived_from=[item["cid"]],
                                 text=f"asm:{item['asm_key']} edges_internal "
                                      f"{internal.get('before')}→{internal.get('after')} · external "
                                      f"{external.get('before')}→{external.get('after')}"))

    if comp["result_parity"]:
        for item in parametric["result_delta"]:
            if item["flag"] != "changed" or item["excluded_reason"]:
                continue
            events.append(_event("result.part_metric_shift", "result", dns=[item["dn"], item["metric"]],
                                 ckeys=[item["ckey"]], subject_key=item["subject_key"],
                                 names=[item["dn"]], before=item["before"], after=item["after"],
                                 magnitude={"value": item["delta"], "unit": item["unit"], "rel": item["rel_delta"]},
                                 derived_from=[item["cid"]],
                                 text=item["text"].rsplit(" [", 1)[0]))

    if g4_fail:
        for event in events:
            if event["confidence"] != "low" and event["code"].startswith("iface."):
                event["confidence"] = "low"

    events.sort(key=lambda e: (e["code"], e["cid"]))
    return {"blocked_by": None, "events": events}


def _dyna_noise(dn, dn_of, base_by, target_by, by_dn) -> bool:
    """같은 dn 클러스터에 dyna pid 가 있고 그 bbox·n_elems 가 전부 noise 인지."""
    dyna_present = any(str(n.get("domain")) == "dyna" and dn_of.get(nid) == dn
                       for nid, n in list(base_by.items()) + list(target_by.items()))
    if not dyna_present:
        return False
    attrs = by_dn.get(dn, {})
    watched = [attrs.get(f"bbox_def_dims[{i}]") for i in range(3)] + [attrs.get("n_elems")]
    seen = [x for x in watched if x]
    return bool(seen) and all(x["flag"] == "noise" for x in seen)


# 파라메트릭 버킷이 어느 소스에서 온 수치인지(plan §3.3.6 소스 5키의 적용 범위).
_BUCKET_SOURCE: dict[str, str] = {
    "node_params": "mcad", "edge_params": "mcad", "materials": "mcad",
    "dims_delta": "mcad", "rollup_delta": "mcad", "result_delta": "dyna_result",
}
_CONFIDENCE_DOWN = {"high": "medium", "medium": "low", "low": "low"}


def _apply_source_parity(comp: dict, structural: dict, parametric: dict, semantic: dict) -> None:
    """소스 5키의 효과를 층에 적용한다(plan §3.3.6 표). 항목을 지우지 않고 사유·주의만 붙인다."""
    def buckets() -> list[tuple[str, list]]:
        return [(name, parametric.get(name) or []) for name in _BUCKET_SOURCE]

    if not comp.get("source_schema_parity", True):
        drift = set(comp.get("source_schema_drift_kinds") or ())
        for name, items in buckets():
            if _BUCKET_SOURCE[name] not in drift:
                continue
            for item in items:
                if isinstance(item, dict) and not item.get("excluded_reason"):
                    item["excluded_reason"] = "source_drift"

    if not comp.get("capture_parity", True):
        for _name, items in buckets():
            for item in items:
                if isinstance(item, dict) and not item.get("excluded_reason"):
                    item["excluded_reason"] = "capture_partial"
        for change in structural.get("edge_changes") or ():
            if isinstance(change, dict) and not change.get("excluded_reason"):
                change["excluded_reason"] = "capture_partial"
        # 부분 캡처에서 '간섭 0' 이 '해소' 로 읽히지 않게 의미 이벤트를 만들지 않는다.
        semantic["events"] = []
        semantic["blocked_by"] = semantic.get("blocked_by") or "capture_partial"

    if not comp.get("primary_source_parity", True):
        for item in parametric.get("rollup_delta") or ():
            if isinstance(item, dict) and not item.get("excluded_reason"):
                item["excluded_reason"] = "partial_scope"

    if comp.get("app_version_parity") is False or comp.get("adapter_parity") is False:
        # 소스 앱·어댑터 세대가 다르면 제외가 아니라 주의(caveat)다 — 정상 리비전 비교를 죽이지 않는다.
        for _name, items in buckets():
            for item in items:
                if isinstance(item, dict):
                    item["caveat"] = "parser_differs"
        for event in semantic.get("events") or ():
            if isinstance(event, dict):
                event["caveat"] = "parser_differs"
                event["confidence"] = _CONFIDENCE_DOWN.get(str(event.get("confidence")), "low")


def _change_style_seed(events: Sequence[Mapping[str, Any]]) -> list[dict]:
    """§3.2.4 `char:change_style:<v>` — 의미 이벤트 change_kind 최빈값의 재서술이다(결론이 아니다)."""
    mapping = {"dimension": "dimension_tuning", "topology": "topology_change",
               "material": "material_swap", "placement": "placement_shift"}
    counts: dict[str, int] = {}
    for event in events:
        kind = str(event.get("change_kind") or "")
        if kind in mapping:
            counts[kind] = counts.get(kind, 0) + 1
    if not counts:
        return []
    top = sorted(counts.items(), key=lambda t: (-t[1], t[0]))[0][0]
    cites = [e["cid"] for e in events if e.get("change_kind") == top][:3]
    return [{"tag": f"char:change_style:{mapping[top]}", "cites": cites,
             "text": f"change_kind {top} {counts[top]}건"}]


# ---------------------------------------------------------------- summary_text(§3.4.2)
def _summary_text(diff: Mapping[str, Any]) -> tuple[str, str]:
    """정본 생성기는 render.py 다. 없으면 같은 섹션 순서로 최소 표기를 만든다(판단어 없음)."""
    render = _render_module()
    builder = getattr(render, "diff_summary_text", None) if render is not None else None
    if callable(builder):
        result = builder(diff)
        if isinstance(result, tuple):
            return (str(result[0]), str(result[1]))
        return (str(result), "ok")

    comp = diff["comparability"]
    stats = diff["stats"]
    base, target = diff["base"], diff["target"]
    lines = [
        f"[대상] base {base.get('label') or ''} {str(base.get('snapshot_id') or '')[:8]}"
        f" ir_hash={str(base.get('ir_hash') or '')[:12]} · target {target.get('label') or ''}"
        f" {str(target.get('snapshot_id') or '')[:8]} ir_hash={str(target.get('ir_hash') or '')[:12]}"
        f" partial={comp['partial_any']}",
        f"[비교가능성] tol_parity={comp['tol_parity']} result_parity={comp['result_parity']}"
        f" unit_parity={comp['unit_parity']} scope_parity={comp['scope_parity']}"
        f" coordinate_ok={comp['coordinate_ok']} G7 {'pass' if comp['G7']['pass'] else 'fail'}"
        f" pending_n={diff['correspondence']['pending_n']} [gate:G7]",
        f"[구조] +{stats['nodes_added']}파트 −{stats['nodes_removed']}파트 · 계면 +{stats['edges_added']}"
        f" −{stats['edges_removed']} · kind 변경 {stats['edges_kind_changed']}",
    ]
    for event in diff["semantic"]["events"][:5]:
        suffix = " (confidence=low)" if event["confidence"] == "low" else ""
        lines.append(f"[의미] {event['text']}{suffix}")
    if diff["semantic"]["blocked_by"]:
        lines.append(f"[의미] 생성 차단 [gate:{diff['semantic']['blocked_by']}]")
    for item in diff["parametric"]["dims_delta"]:
        lines.append(f"[치수] {item['text']}")
    for item in diff["parametric"]["materials"]:
        lines.append(f"[재료] {item['text']}")
    if comp["result_parity"]:
        for item in diff["parametric"]["result_delta"][:5]:
            if item["flag"] == "changed":
                lines.append(f"[결과] {item['text']}")
    elif comp["result_reason"]:
        lines.append(f"[결과] 결과 비교 제외({comp['result_reason']})")
    for reason, count in (stats.get("excluded_by_reason") or {}).items():
        lines.append(f"[제외] {reason} {count}건")
    for seed in diff["character_seed"]:
        lines.append(f"[씨앗] {seed['tag']}")
    text = "\n".join(lines)
    return (text[:2000], "ok")


# ---------------------------------------------------------------- 저장(§3.1 · §5.2.2)
def _load_ir(store, snapshot_id: str, owner_sub: str) -> tuple[dict, dict]:
    row = store.query_one(
        "SELECT id, project_id, owner_sub, ir_json FROM rr_snapshots WHERE id=? AND owner_sub=?",
        (snapshot_id, owner_sub),
    )
    if row is None:
        raise AppError("E404", f"스냅샷이 없습니다 — {snapshot_id}.", 404)
    try:
        ir = json.loads(row["ir_json"])
    except (TypeError, ValueError) as exc:
        raise AppError("E300", f"rr_snapshots.ir_json 을 읽을 수 없습니다 — {snapshot_id}.", 500) from exc
    state_row = store.query_one(
        "SELECT snapshot_id, state_json, blocked FROM rr_states WHERE snapshot_id=? AND owner_sub=?",
        (snapshot_id, owner_sub),
    )
    state: dict = {}
    if state_row is not None and state_row["state_json"]:
        try:
            state = json.loads(state_row["state_json"])
        except (TypeError, ValueError):
            state = {}
        state.setdefault("blocked", bool(state_row["blocked"]))
    ir.setdefault("snapshot_id", row["id"])
    ir.setdefault("project_id", row["project_id"])
    return ir, state


def _pair_kind(store, base_project_id: str, target_project_id: str, owner_sub: str) -> str:
    """같은 과제이거나 `predecessor_project_id` 체인으로 이어져 있으면 same_project_revision."""
    if base_project_id == target_project_id:
        return "same_project_revision"
    current = target_project_id
    for _ in range(sameas.MERGE_CHAIN_MAX):
        row = store.query_one(
            "SELECT id, predecessor_project_id FROM rr_projects WHERE id=? AND owner_sub=?",
            (current, owner_sub),
        )
        if row is None or not row["predecessor_project_id"]:
            break
        current = str(row["predecessor_project_id"])
        if current == base_project_id:
            return "same_project_revision"
    return "cross_project"


def _dim_tols(store) -> dict[str, tuple]:
    rows = store.query("SELECT name, tol_abs, tol_rel FROM rr_dim_vocab", ())
    return {str(r["name"]): (r["tol_abs"], r["tol_rel"]) for r in rows}


def create_diff(store, base_snapshot_id: str, target_snapshot_id: str, *, owner_sub: str,
                pair_kind: str | None = None) -> dict:
    """`POST /api/diffs` 본체 — 두 스냅샷으로 rr_diff 를 만들고 `rr_diffs`·`rr_diff_events` 에 저장한다.

    G6 로 차단된 스냅샷이면 409(`AppError('E409')`)로 끝나고 diff 행은 생기지 않는다(§3.3.1).
    같은 (base, target) 이 이미 있으면 저장된 행을 그대로 돌려준다(UNIQUE 제약, 결정론이라 재계산과 같다).
    """
    # self-diff(같은 스냅샷 둘)는 허용한다 — 이벤트 0·changed 0 이 통과 기준이다(§3.3.5).
    base_ir, base_state = _load_ir(store, base_snapshot_id, owner_sub)
    target_ir, target_state = _load_ir(store, target_snapshot_id, owner_sub)

    blocked = check_pair_blocked(base_state, target_state)
    if blocked is not None:
        raise AppError("gate_blocked", f"게이트 G6 로 차단된 스냅샷입니다(reason={blocked['reason']}).",
                       409, detail=blocked)

    existing = store.query_one(
        "SELECT id FROM rr_diffs WHERE base_snapshot_id=? AND target_snapshot_id=? AND owner_sub=?",
        (base_snapshot_id, target_snapshot_id, owner_sub),
    )
    if existing is not None:
        return get_diff(store, str(existing["id"]), owner_sub=owner_sub, part="diff")

    base_project = str(base_ir.get("project_id") or "")
    target_project = str(target_ir.get("project_id") or "")
    kind = pair_kind or _pair_kind(store, base_project, target_project, owner_sub)

    links = sameas.resolve(list(base_ir.get("nodes") or []), list(target_ir.get("nodes") or []),
                           list(base_ir.get("edges") or []), list(target_ir.get("edges") or []),
                           "pair", sameas.load_ledger(store, "pair",
                                                      "|".join(sorted([base_project, target_project])),
                                                      owner_sub))
    diff_id = new_uuid()
    diff = compute_diff(base_ir, target_ir, base_state=base_state, target_state=target_state,
                        links=links, pair_kind=kind, dim_tols=_dim_tols(store),
                        project_id=target_project, diff_id=diff_id)

    # 결정론 검증용 해시 — 시각·id 를 뺀 본문의 sha256(§3.1 원칙 1).
    body = {k: v for k, v in diff.items() if k not in ("diff_id", "created_at")}
    diff_hash = hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()

    with store.tx():
        store.execute(
            "INSERT INTO rr_diffs (id, owner_sub, base_snapshot_id, target_snapshot_id,"
            " base_project_id, target_project_id, pair_kind, diff_version, diff_json, summary_text,"
            " summary_status, stats_json, comparability_json, gates_json, diff_hash, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (diff_id, owner_sub, base_snapshot_id, target_snapshot_id, base_project, target_project,
             kind, DIFF_VERSION, canonical_json(diff), diff["summary_text"], diff["summary_status"],
             canonical_json(diff["stats"]), canonical_json(diff["comparability"]),
             canonical_json({"G7": diff["comparability"]["G7"]}), diff_hash, diff["created_at"]),
        )
        store.executemany(
            "INSERT OR REPLACE INTO rr_diff_events (diff_id, cid, owner_sub, layer, code, change_kind,"
            " subject_key, ckeys_json, magnitude, unit, rel, confidence, design_relevant, unconfirmed,"
            " excluded_reason, text) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            list(_event_rows(diff, diff_id, owner_sub)),
        )
    return diff


def _event_rows(diff: Mapping[str, Any], diff_id: str, owner_sub: str):
    """의미 이벤트를 펼침 표 행으로 편다(구조·파라메트릭 항목은 diff_json 안에만 산다)."""
    for event in diff["semantic"]["events"]:
        magnitude = event.get("magnitude") or {}
        yield (
            diff_id, event["cid"], owner_sub, "semantic", event["code"], event["change_kind"],
            event["subject_key"], canonical_json(event["subject"].get("ckeys") or []),
            _num(magnitude.get("value")), magnitude.get("unit"), _num(magnitude.get("rel")),
            event["confidence"], 1 if event["design_relevant"] else 0,
            1 if event["unconfirmed"] else 0, event["excluded_reason"], event["text"],
        )


def get_diff(store, diff_id: str, *, owner_sub: str, part: str = "diff") -> dict:
    """`GET /api/diffs/{id}?part=diff|summary|events`."""
    if part not in ("diff", "summary", "events"):
        raise AppError("E100", f"part 는 diff|summary|events 여야 합니다 — {part!r}.", 400)
    row = store.query_one(
        "SELECT id, base_snapshot_id, target_snapshot_id, base_project_id, target_project_id,"
        " pair_kind, diff_version, diff_json, summary_text, summary_status, stats_json,"
        " comparability_json, diff_hash, created_at FROM rr_diffs WHERE id=? AND owner_sub=?",
        (diff_id, owner_sub),
    )
    if row is None:
        raise AppError("E404", f"diff 가 없습니다 — {diff_id}.", 404)
    if part == "summary":
        return {"diff_id": row["id"], "summary_text": row["summary_text"],
                "summary_status": row["summary_status"],
                "stats": json.loads(row["stats_json"]) if row["stats_json"] else {},
                "comparability": json.loads(row["comparability_json"]) if row["comparability_json"] else {},
                "diff_hash": row["diff_hash"], "created_at": row["created_at"]}
    if part == "events":
        events = store.query(
            "SELECT diff_id, cid, layer, code, change_kind, subject_key, ckeys_json, magnitude, unit,"
            " rel, confidence, design_relevant, unconfirmed, excluded_reason, text"
            " FROM rr_diff_events WHERE diff_id=? AND owner_sub=? ORDER BY code, cid",
            (diff_id, owner_sub),
        )
        return {"diff_id": row["id"], "events": [dict(e) for e in events]}
    try:
        return json.loads(row["diff_json"])
    except (TypeError, ValueError) as exc:
        raise AppError("E300", f"rr_diffs.diff_json 을 읽을 수 없습니다 — {diff_id}.", 500) from exc
