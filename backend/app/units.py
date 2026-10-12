# 변경 diff 의 세 층 항목을 검토 단위로 나누고 줄 구조·요약·목록 글·해시·불변식을 결정적으로 만든다(LLM·네트워크 없음)
"""리스크 심사 재설계 WP2 의 단위 순수 핵심(M2 걸음 U1).

- 원천은 `rr_diffs.diff_json` 의 구조·파라메트릭·의미 세 층이다. 항목 하나가 줄 하나이고 어느 줄도 자르거나 빼지 않는다
  (운영 창 1,048,576 토큰 — 단위 크기는 줄 수로만 가르고 글자는 센다, D-21·D-22).
- 항목은 단위 하나만 소유한다. 다른 단위에는 문맥 줄로 다시 보일 수 있다(셈에 넣지 않는다).
- 줄 몸통은 `brief.e2_line` 과 같은 식 `split_trailing_refs(humanize_refs(text, name_index))` 를 위생에 통과시킨 글이다 —
  `risk_get_diff(part='lines')` 에서 옮긴 글과 글자까지 같다.
- 소스 앱에서 온 문자열(부품명·재질·조립 키·치수 이름)은 요약·목록 글·제목 어디서나 `sanitize_source_text(…, limit=0)` 를
  거쳐 «» 안에 선다(W2-10). 린터 적중은 빌드 실패가 아니라 그 줄만 다시 감싼다(`flags.lint_fallback`).
- 저장·REST·손잡이는 이 모듈 밖(M2 단계 C)이다. 여기 함수는 DB 에 쓰지 않는다 — `_ir_view` 만 읽는다.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Iterator, Mapping, Sequence

from . import brief, render
from .common import canonical_json, sha256_hex

__all__ = [
    "BUILDER_VERSION",
    "EXCLUDED_POLICY",
    "UNIT_KINDS",
    "UnitCaps",
    "build_diff_units",
    "check_invariants",
    "collect_diff_items",
    "digest_of",
    "evidence_lines",
    "manifest_item_of",
    "partition",
    "payload_of",
    "render_unit",
    "unit_hash",
    "unit_lines",
    "refs_of",
    "view_of",
    "walk_cids",
]

BUILDER_VERSION = "units-1.0"
UNIT_KINDS: tuple[str, ...] = ("bundle", "boundary", "global", "excluded")
LAYERS: tuple[str, ...] = ("semantic", "structural", "parametric")

# 제외 사유의 처리(설계서 3.4.1 의 권고값). 목록에 없는 사유는 '검토에 싣는다' 쪽(caveat)으로 떨어진다 —
# diff 는 EXCLUDED_REASONS 10종 밖의 source_drift·capture_partial 도 실제로 붙인다(사유 어휘를 닫힌 집합으로 믿지 않는다).
EXCLUDED_POLICY: dict[str, tuple[str, ...]] = {
    "caveat": ("tol_unknown", "tol_differs", "null_one_side", "result_kind_differs", "sim_params_differ"),
    "none": ("partial_scope", "capture_partial", "source_drift", "not_design_relevant", "incomparable_same",
             "null_both"),
}
_NOT_DESIGN = ("not_design_relevant", "status_changed")

# 알려진 버킷 — 그 밖의 자리에서 나온 cid 항목은 '모르는 버킷' 으로 전역 단위가 소유한다.
_KNOWN_BUCKETS: frozenset[tuple[str, ...]] = frozenset({
    ("structural", "node_changes"), ("structural", "hierarchy_moves"), ("structural", "edge_changes"),
    ("structural", "dyna", "scope_changed"),
    ("parametric", "node_params"), ("parametric", "edge_params"), ("parametric", "materials"),
    ("parametric", "dims_delta"), ("parametric", "result_delta"), ("parametric", "rollup_delta"),
    ("semantic", "events"),
})
_NODE_OP_KIND = {"added": "count", "removed": "count", "split": "count", "merged": "count", "replaced": "type",
                 "moved_in_tree": "topology"}
_PART_STATUS = {"added": "추가", "removed": "삭제", "replaced": "교체", "split": "분할", "merged": "병합",
                "moved_in_tree": "조립 이동"}
_ROLLUP_FIELDS = ("n_leaf", "edges_internal", "edges_external", "orphan_leaf")
_ROLLUP_LABEL = {"n_leaf": "리프", "edges_internal": "내부 계면", "edges_external": "외부 계면", "orphan_leaf": "고아 리프"}
# 전역 단위의 구획 순서(W2-01) — 명명 치수 → 롤업(최상위 접두별) → scope → 모르는 버킷 → 그 밖.
_SECTIONS: tuple[str, ...] = ("dims", "rollup", "scope", "unknown", "other")
_SECTION_LABEL = {"dims": "명명 치수", "rollup": "롤업", "scope": "접촉 범위", "unknown": "모르는 버킷",
                  "other": "부품 미상"}
_FMT_KIND = {"mm": "length", "mm2": "area", "mm3": "volume", "MPa": "stress", "G": "acceleration", "rank": "rank"}
_SAFE_WORD = re.compile(r"^[A-Za-z0-9_.#:\[\]\-]+$")
_NID = re.compile(r"p:[0-9a-f]{12}")
_GROUP_MIN = 4                 # 동형 묶음 표기 — 한 단위 안에서 같은 변화가 이만큼이면 요약 렌더에서 접는다(3.6.3)
_GROUP_ROW = 8                 # 접은 줄의 한 줄당 참조 수


@dataclass(frozen=True)
class UnitCaps:
    """단위 크기(줄 수). 글자 수 상한은 없다(D-21). 손잡이 배선은 M2 단계 C 다 — 여기 값은 코드 기본값이다."""

    target_lines: int = 20        # 형제 조립을 채워 넣는 목표 크기
    max_lines: int = 40           # 단위 하나의 변경 줄 상한(부품 원자 하나가 넘으면 쪼개지 않고 atom_oversize)
    small_lines: int = 15         # 검토 줄 합이 이 이하면 단위 하나로 낸다
    units_max: int = 60           # 검토 대상 단위 수의 경고선(넘으면 status='oversize')


# ---------------------------------------------------------------- 작은 유틸
def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _s(value: Any) -> str:
    return "" if value is None else str(value)


def _count(value: Any) -> str:
    """롤업 칸 값 — 그 조립이 한쪽 스냅샷에 없으면 None 이다('없음')."""
    return "없음" if value is None else str(value)


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _q(text: Any) -> str:
    """원천 문자열 한 칸 → «위생 통과본»(자르지 않는다). 인젝션 어휘면 «[suspect_text …]»."""
    return render.sanitize_source_text(text, "label", limit=0)


def _word(value: Any) -> str:
    """코드가 «» 밖에 쓰는 어휘 칸(코드·사유·계면 종류) — 생산자 어휘 꼴이면 그대로, 아니면 위생을 거쳐 «» 안에 둔다."""
    text = _s(value)
    return text if text and _SAFE_WORD.match(text) else _q(text)


# ---------------------------------------------------------------- 독립 순회(U1 의 기준)
def walk_cids(diff_obj: Mapping[str, Any]) -> dict[str, list[str]]:
    """cid → [그 cid 가 놓인 경로]. 세 층 아래를 끝까지 내려가며 `cid` 키를 가진 dict 를 센다 — 수집 코드와 로직을 나누지 않는다.

    경로는 'structural.node_changes' 처럼 키 이름을 점으로 잇고 리스트 첨자는 적지 않는다(같은 경로에 둘이면 둘 다 남는다).
    """
    out: dict[str, list[str]] = {}

    def visit(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, Mapping):
            cid = value.get("cid")
            if isinstance(cid, str) and cid:
                out.setdefault(cid, []).append(".".join(path))
            for key in sorted(value, key=str):
                if isinstance(value[key], (Mapping, list, tuple)):
                    visit(value[key], path + (str(key),))
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item, path)

    for layer in LAYERS:
        visit(diff_obj.get(layer) or {}, (layer,))
    return {cid: sorted(paths) for cid, paths in sorted(out.items())}


def _same_value(item: Mapping[str, Any]) -> bool:
    """값이 같은데 표지가 붙은 항목 — 양쪽 다 미측정(`null_one_side` 인데 둘 다 None), 값이 같은 비교 불가(관통 깊이 하한 둘)."""
    return item.get("flag") in ("null_one_side", "incomparable") and item.get("before") == item.get("after")


def _non_change(item: Mapping[str, Any]) -> bool:
    """단위에 싣지 않는 cid 항목 — 임계 밑(noise)과 수치가 하나도 안 바뀐 롤업 행(설계서 3.4.1 — 롤업은 바뀐 칸이 있는 행만
    항목이다). 회계에만 센다. 값이 같은 표지 항목(`_same_value`)은 여기 들지 않는다 — 제외 단위가 `incomparable_same`·
    `null_both` 사유로 소유한다(설계서 3.4.1 의 klass 표, RA-9 — 어느 단위에도 없는 cid 를 두지 않는다)."""
    if item.get("flag") == "noise":
        return True
    pairs = [v for v in item.values() if isinstance(v, Mapping) and set(v) == {"before", "after"}]
    return bool(pairs) and "before" not in item and all(p["before"] == p["after"] for p in pairs)


# ---------------------------------------------------------------- 항목 수집(설계서 3.4.1)
def _strings(value: Any) -> Iterator[str]:
    """한 값에 든 문자열 전부(인젝션 이름 찾기용)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)


def _item(ref: str, layer: str, bucket: str, code: str, change_kind: str, src: Mapping[str, Any], **extra: Any) -> dict:
    item = {
        "ref": ref, "layer": layer, "bucket": bucket, "code": code, "change_kind": change_kind,
        "attr": None, "before": src.get("before"), "after": src.get("after"),
        "delta": src.get("delta"), "rel": src.get("rel_delta"), "unit": src.get("unit"),
        "flag": src.get("flag"), "excluded_reason": src.get("excluded_reason"),
        "design_relevant": src.get("design_relevant") is not False, "nd_reason": None,
        "confidence": src.get("confidence"), "unconfirmed": bool(src.get("unconfirmed")),
        "lower_bound": bool(src.get("lower_bound")), "caveat": src.get("caveat"),
        "derived_from": [str(x) for x in (src.get("derived_from") or ()) if x],
        "text": _s(src.get("text")), "anchors_raw": [], "asm": None, "section": None,
        "family": None, "op": None, "kind_from": None, "kind_to": None, "bucket_unknown": False, "names_raw": [],
    }
    item.update(extra)
    return item


def _param_kind(attr: str) -> str:
    base = attr.split("[")[0]
    if base in ("centroid_world", "bbox_world_dims"):
        return "placement"
    if base.startswith("material."):
        return "material"
    if base == "n_elems":
        return "discretization"
    if base == "fs":
        return "parameter"
    return "dimension"


def _klass(item: Mapping[str, Any]) -> tuple[str, str | None]:
    """(klass, 사유) — active · caveat · excluded · non_design(설계서 3.4.1 표)."""
    if _same_value(item):                                  # 바뀐 값이 없다 — 검토할 것이 없고 제외 단위에 사유와 함께 남는다
        return "excluded", "incomparable_same" if item.get("flag") == "incomparable" else "null_both"
    if not item["design_relevant"]:
        return "non_design", item.get("nd_reason") or "not_design_relevant"
    reason = item.get("excluded_reason")
    if reason:
        if reason in EXCLUDED_POLICY["none"]:
            return "excluded", str(reason)
        return "caveat", str(reason)                     # caveat 목록 또는 모르는 사유
    if item.get("flag") == "incomparable":                 # 값이 다른 비교 불가 — 값이 같으면 위에서 제외로 갔다
        return "caveat", "incomparable"
    return "active", None


def _collect(diff_obj: Mapping[str, Any]) -> tuple[list[dict], dict]:
    """(항목, 건너뛴 수). 알려진 버킷은 이름으로 훑고, 그 밖의 자리에서 나온 cid 항목은 모르는 버킷 항목이 된다."""
    structural = diff_obj.get("structural") or {}
    parametric = diff_obj.get("parametric") or {}
    semantic = diff_obj.get("semantic") or {}
    items: list[dict] = []
    skipped = {"noise": 0, "rollup_unchanged": 0}

    def skip(src: Mapping[str, Any]) -> bool:
        if not _non_change(src):
            return False
        skipped["noise" if src.get("flag") == "noise" else "rollup_unchanged"] += 1
        return True

    def rows(bucket: Any) -> list[Mapping[str, Any]]:
        return [src for src in (bucket or ()) if isinstance(src, Mapping) and src.get("cid")]

    node_cids: set[str] = set()
    for src in rows(structural.get("node_changes")):
        node_cids.add(src["cid"])
        op = _s(src.get("op"))
        items.append(_item(src["cid"], "structural", "node_changes", f"node.{op}", _NODE_OP_KIND.get(op, "topology"),
                           src, op=op, anchors_raw=[src.get("dn")], names_raw=list(_strings(src.get("label")))))
    for src in rows(structural.get("edge_changes")):
        family, op = _s(src.get("kind_family")), _s(src.get("op"))
        # hier(part_of) 항목은 자식 부품의 원자에 싣는다 — 조립 노드↔부품 쌍이 경계 단위를 만들지 않게(W2-02).
        anchors = [src.get("dn_b")] if family == "hier" else [src.get("dn_a"), src.get("dn_b")]
        change_kind = "contact_type" if (family == "contact" and op == "kind_changed") else "topology"
        item = _item(src["cid"], "structural", "edge_changes", f"edge.{family}.{op}", change_kind, src,
                     family=family, op=op, kind_from=src.get("kind_from"), kind_to=src.get("kind_to"),
                     anchors_raw=anchors, before=src.get("kind_from"), after=src.get("kind_to"))
        if op == "status_changed":
            item.update(design_relevant=False, nd_reason="status_changed",
                        before=src.get("status_from"), after=src.get("status_to"))
        items.append(item)
    for src in rows((structural.get("dyna") or {}).get("scope_changed")):
        items.append(_item(src["cid"], "structural", "dyna.scope_changed", "scope.changed", "topology", src,
                           section="scope", before=src.get("dns_before"), after=src.get("dns_after")))
    for src in rows(parametric.get("node_params")):
        if skip(src):
            continue
        attr = _s(src.get("attr"))
        item = _item(src["cid"], "parametric", "node_params", f"param.{attr.split('[')[0]}", _param_kind(attr), src,
                     attr=attr, anchors_raw=[src.get("dn")])
        if not item["design_relevant"]:
            item["nd_reason"] = "not_design_relevant"
        items.append(item)
    for src in rows(parametric.get("edge_params")):
        if skip(src):
            continue
        attr = _s(src.get("attr"))
        items.append(_item(src["cid"], "parametric", "edge_params", f"param.{attr}", _param_kind(attr), src,
                           attr=attr, family=src.get("kind_family"), anchors_raw=[src.get("dn_a"), src.get("dn_b")]))
    for src in rows(parametric.get("materials")):
        if skip(src):
            continue
        field = _s(src.get("field"))
        items.append(_item(src["cid"], "parametric", "materials", f"param.material.{field}", "material", src,
                           attr=f"material.{field}", anchors_raw=[src.get("dn")],
                           names_raw=list(_strings([src.get("before"), src.get("after")]))))
    for src in rows(parametric.get("dims_delta")):
        if skip(src):
            continue
        items.append(_item(src["cid"], "parametric", "dims_delta", "param.dim", "dimension", src,
                           attr=_s(src.get("name")), section="dims", names_raw=list(_strings(src.get("name")))))
    for src in rows(parametric.get("result_delta")):
        if skip(src):
            continue
        metric = _s(src.get("metric") or src.get("attr"))
        items.append(_item(src["cid"], "parametric", "result_delta", f"param.{metric}", "result", src,
                           attr=metric, anchors_raw=[src.get("dn")]))
    for src in rows(parametric.get("rollup_delta")):
        if skip(src):
            continue
        prefix = _s(src.get("path_prefix") or src.get("asm_key"))
        before = {f: src[f].get("before") for f in _ROLLUP_FIELDS if isinstance(src.get(f), Mapping)}
        after = {f: src[f].get("after") for f in _ROLLUP_FIELDS if isinstance(src.get(f), Mapping)}
        # 몸통은 단위가 짓는다 — 생산자 글은 리프 수만 적어(`asm:… 리프 7→7`) 계면·고아 리프만 바뀐 행이 '바뀐 것 없는 변경' 으로
        # 보였다(RA-5). 바뀐 칸만 적는다. 롤업은 의미 이벤트가 아니라 risk_get_diff 줄 대조 대상이 아니다.
        text = f"asm:{prefix} " + " · ".join(f"{_ROLLUP_LABEL[f]} {_count(before[f])}→{_count(after[f])}"
                                              for f in _ROLLUP_FIELDS if f in before and before[f] != after[f])
        items.append(_item(src["cid"], "parametric", "rollup_delta", "param.rollup", "topology", src,
                           before=before, after=after, asm=prefix, section="rollup", names_raw=[prefix], text=text))
    for src in rows(semantic.get("events")):
        magnitude = src.get("magnitude") if isinstance(src.get("magnitude"), Mapping) else {}
        subject = src.get("subject") if isinstance(src.get("subject"), Mapping) else {}
        dns = [str(x) for x in (subject.get("dns") or ()) if x is not None]
        code = _s(src.get("code"))
        asm = dns[0][len("asm:"):] if dns and dns[0].startswith("asm:") else None
        section = ("dims" if code.startswith("dim.") else "scope" if code == "contact.scope_changed"
                   else "rollup" if asm is not None else "other")
        item = _item(src["cid"], "semantic", "events", code, _s(src.get("change_kind")) or "none", src,
                     delta=magnitude.get("value"), rel=magnitude.get("rel"), unit=magnitude.get("unit"),
                     anchors_raw=dns, asm=asm, section=section,
                     names_raw=list(_strings([subject.get("names"), src.get("before"), src.get("after")])))
        if not item["design_relevant"]:
            item["nd_reason"] = "not_design_relevant"
        items.append(item)

    # 모르는 버킷 — 알려진 자리 밖에서 나온 cid 항목. hierarchy_moves 는 node_changes 와 같은 dict 라 건너뛴다.
    def scan(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, Mapping):
            cid = value.get("cid")
            if isinstance(cid, str) and cid:
                if path not in _KNOWN_BUCKETS and not skip(value):
                    layer, rest = path[0], ".".join(path[1:]) or path[0]
                    items.append(_item(cid, layer, rest, f"{layer}.{rest}", "none", value, section="unknown",
                                       bucket_unknown=True, names_raw=list(_strings(value.get("text")))))
                elif path == ("structural", "hierarchy_moves") and cid not in node_cids:
                    items.append(_item(cid, "structural", "hierarchy_moves", "node.moved_in_tree", "topology", value,
                                       op="moved_in_tree", anchors_raw=[value.get("dn")]))
                return
            for key in sorted(value, key=str):
                if isinstance(value[key], (Mapping, list, tuple)):
                    scan(value[key], path + (str(key),))
        elif isinstance(value, (list, tuple)):
            for entry in value:
                scan(entry, path)

    for layer in LAYERS:
        scan(diff_obj.get(layer) or {}, (layer,))

    for item in items:
        item["klass"], item["reason"] = _klass(item)
    items.sort(key=lambda i: (LAYERS.index(i["layer"]) if i["layer"] in LAYERS else 9, i["ref"], i["bucket"],
                              i["text"]))
    return items, skipped


def collect_diff_items(diff_obj: Mapping[str, Any]) -> list[dict]:
    """diff 세 층을 한 가지 모양의 항목 목록으로 편다(noise·바뀌지 않은 롤업만 뺀다). 결정적 순서다."""
    return _collect(diff_obj)[0]


# ---------------------------------------------------------------- 보기(IR 두 벌)
def view_of(base_ir: Mapping[str, Any] | None, target_ir: Mapping[str, Any] | None, *,
            names: Mapping[str, str] | None = None,
            base_rule_hits: Sequence[Mapping[str, Any]] | None = None,
            target_rule_hits: Sequence[Mapping[str, Any]] | None = None,
            base_degraded: Sequence[str] | None = None, target_degraded: Sequence[str] | None = None) -> dict:
    """단위 빌드와 동결 발췌가 읽는 보기 — 두 스냅샷의 IR 노드·엣지·해석 결과, 규칙 적중, 강등 표지와 이름 색인. 순수 함수다.

    `names` 를 안 주면 IR 노드의 이름(label)으로 `brief.name_index` 와 같은 규칙(뒤 스냅샷이 이긴다)으로 만든다 —
    `rr_ir_nodes.name` 이 노드 label 이라 저장소에서 읽은 색인과 같다. 강등 표지를 안 주면 IR 소스들의 `degraded` 합집합이다
    (`rr_snapshots.degraded_json` 과 같은 규칙). IR 이 없으면(폐기 — `ir_json=''`) 그 쪽은 `present=False` 다.
    """
    def side(ir: Mapping[str, Any] | None, hits, degraded) -> dict:
        ir = ir or {}
        nodes = [dict(n) for n in (ir.get("nodes") or ()) if isinstance(n, Mapping) and n.get("nid")]
        edges = [dict(e) for e in (ir.get("edges") or ()) if isinstance(e, Mapping) and e.get("eid")]
        results = ir.get("results") if isinstance(ir.get("results"), Mapping) else {}
        if degraded is None:
            degraded = [x for source in (ir.get("sources") or ()) if isinstance(source, Mapping)
                        for x in (source.get("degraded") or ())]
        return {"present": bool(ir) and bool(nodes or ir.get("sources")), "nodes": nodes, "edges": edges,
                "part_risk": [dict(r) for r in (results.get("part_risk") or ()) if isinstance(r, Mapping)],
                "rule_hits": [dict(h) for h in (hits or ()) if isinstance(h, Mapping)],
                "degraded": sorted({str(x) for x in degraded if x})}

    base = side(base_ir, base_rule_hits, base_degraded)
    target = side(target_ir, target_rule_hits, target_degraded)
    if names is None:
        index: dict[str, str] = {}
        for node in sorted(base["nodes"], key=lambda n: str(n["nid"])) + sorted(target["nodes"], key=lambda n: str(n["nid"])):
            if node.get("label"):
                index[str(node["nid"])] = str(node["label"])
        names = index
    return {"names": dict(names), "base": base, "target": target}


def _json(text: Any, default: Any) -> Any:
    if text is None or text == "":
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _ir_view(store, base_sid: str | None, target_sid: str | None) -> dict:
    """저장소에서 두 스냅샷의 IR(`rr_snapshots.ir_json`)·강등 표지(`degraded_json`)·규칙 적중(`rr_states.rule_hits_json`)과
    이름 색인(`brief.name_index`)을 읽어 `view_of` 로 넘긴다. 읽기만 한다. 폐기된 IR(`ir_json=''`)은 없는 쪽으로 읽힌다."""
    def load(sid: str | None) -> tuple[Mapping[str, Any] | None, list, list | None]:
        if not sid:
            return None, [], None
        row = store.query_one("SELECT ir_json, degraded_json FROM rr_snapshots WHERE id = ?", (sid,))
        state = store.query_one("SELECT rule_hits_json FROM rr_states WHERE snapshot_id = ?", (sid,))
        hits = _json(state["rule_hits_json"], []) if state is not None else []
        if row is None:
            return None, hits if isinstance(hits, list) else [], None
        degraded = _json(row["degraded_json"], [])
        return (_json(row["ir_json"], None), hits if isinstance(hits, list) else [],
                degraded if isinstance(degraded, list) else [])

    base_ir, base_hits, base_degraded = load(base_sid)
    target_ir, target_hits, target_degraded = load(target_sid)
    return view_of(base_ir, target_ir, names=brief.name_index(store, (base_sid, target_sid)),
                   base_rule_hits=base_hits, target_rule_hits=target_hits,
                   base_degraded=base_degraded, target_degraded=target_degraded)


# ---------------------------------------------------------------- 노드 색인(diff 의 dn 이름공간)
class _Nodes:
    """diff 의 dn → 두 스냅샷의 노드. dn 은 diff.compute_diff 와 같은 규칙으로 접는다(대응한 짝은 base 의 dn)."""

    def __init__(self, diff_obj: Mapping[str, Any], view: Mapping[str, Any]) -> None:
        base = {str(n["nid"]): n for n in view["base"]["nodes"]}
        target = {str(n["nid"]): n for n in view["target"]["nodes"]}
        dn_of: dict[str, str] = {}
        matched = (diff_obj.get("correspondence") or {}).get("matched") or ()
        for m in sorted((m for m in matched if isinstance(m, Mapping) and m.get("dn")),
                        key=lambda m: (str(m.get("nid_base")), str(m.get("nid_target")))):
            dn_of[str(m.get("nid_base"))] = str(m["dn"])
            dn_of[str(m.get("nid_target"))] = str(m["dn"])
        for nid, node in list(base.items()) + list(target.items()):
            dn_of.setdefault(nid, str(node.get("dn") or nid))
        self.dn_of = dn_of
        self.by_dn: dict[str, dict[str, list[dict]]] = {}
        for side, table in (("base", base), ("target", target)):
            for nid in sorted(table):
                self.by_dn.setdefault(dn_of[nid], {"base": [], "target": []})[side].append(table[nid])
        self.names = view["names"]

    def known(self, dn: Any) -> bool:
        return isinstance(dn, str) and dn.startswith("p:") and dn in self.by_dn

    def ranked(self, dn: str, side: str) -> list[dict]:
        nodes = (self.by_dn.get(dn) or {}).get(side) or []
        return sorted(nodes, key=lambda n: (n.get("domain") != "mcad", n.get("kind") != "part", str(n["nid"])))

    def node(self, dn: str) -> dict | None:
        for side in ("target", "base"):
            ranked = self.ranked(dn, side)
            if ranked:
                return ranked[0]
        return None

    def asm(self, dn: str) -> str:
        """조립 키 — target 노드의 asm_key, 없으면 base 것, 그것도 없으면 '~<소스>'(설계서 3.4.2)."""
        for side in ("target", "base"):
            for node in self.ranked(dn, side):
                if node.get("asm_key"):
                    return str(node["asm_key"])
        return f"~{(self.node(dn) or {}).get('domain') or 'unknown'}"

    def dkey(self, dn: str) -> str:
        return str((self.node(dn) or {}).get("ckey") or dn)

    def name(self, dn: str) -> str:
        node = self.node(dn)
        if node is not None and node.get("label"):
            return str(node["label"])
        return str(self.names.get(dn) or dn)

    def source(self, dn: str) -> str:
        return str((self.node(dn) or {}).get("domain") or "-")

    def nids(self, dn: str, side: str) -> list[str]:
        return [str(n["nid"]) for n in self.ranked(dn, side)]

    def material(self, dn: str, side: str) -> str | None:
        for node in self.ranked(dn, side):
            value = _material_of(node)
            if value:
                return value
        return None


def _material_of(node: Mapping[str, Any]) -> str | None:
    """노드의 재질 원문 — mcad 는 문자열, dyna 는 {db:{tag,name}, kfile:{name}, name}."""
    material = (node.get("attrs") or {}).get("material")
    if isinstance(material, str):
        return material or None
    if isinstance(material, Mapping):
        db = material.get("db") if isinstance(material.get("db"), Mapping) else {}
        kfile = material.get("kfile") if isinstance(material.get("kfile"), Mapping) else {}
        value = db.get("tag") or db.get("name") or kfile.get("name") or material.get("name")
        return str(value) if value else None
    return None


def _neighbors(view: Mapping[str, Any], nodes: _Nodes) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """(1홉 이웃, 근접) — iface·contact 엣지(clearance 제외)와 clearance 엣지를 dn 으로 접는다(diff._neighborhood 규약)."""
    near: dict[str, set[str]] = {}
    adj: dict[str, set[str]] = {}
    for side in ("base", "target"):
        for edge in view[side]["edges"]:
            if str(edge.get("kind_family") or "") not in ("iface", "contact") or edge.get("status") == "rejected":
                continue
            a = nodes.dn_of.get(str(edge.get("a") or ""))
            b = nodes.dn_of.get(str(edge.get("b") or ""))
            if not a or not b or a == b:
                continue
            table = near if str(edge.get("kind") or "") == "clearance" else adj
            table.setdefault(a, set()).add(b)
            table.setdefault(b, set()).add(a)
    return adj, near


# ---------------------------------------------------------------- 줄 몸통(브리프 E2 와 같은 식)
def _clean_body(item: Mapping[str, Any], names: Mapping[str, str], suspects: dict[str, dict]) -> tuple[str, bool]:
    """(위생 통과 몸통 — «» 없이, 이름 칸만 자리표시자로 다시 조립했나). 몸통 식은 `brief.e2_line` 과 같다.

    인젝션 어휘에 걸리면 그 줄만 다시 조립한다 — 걸린 원천 문자열(이름) 자리만 `[suspect_text <sha1>]` 이고 속성·
    before→after·단위는 코드가 쓴 글로 남는다(지금 E2 는 줄 전체가 자리표시자다, 설계서 3.6.2). 걸린 원문은 `suspects` 에 모인다.
    """
    text = item["text"]
    body = render.split_trailing_refs(render.humanize_refs(text, names))[0] if text else item["code"]
    inner = render.sanitize_source_text(body, "note", limit=0)[1:-1]
    if not inner.startswith("[suspect_text "):
        return inner, False

    def note(payload: Mapping[str, Any]) -> None:
        suspects.setdefault(str(payload.get("sha1")), dict(payload))

    candidates = set(item.get("names_raw") or ())
    candidates.update(str(names[nid]) for nid in _NID.findall(text or "") if names.get(nid))
    candidates.update(str(names[a]) for a in item.get("anchors_raw") or () if isinstance(a, str) and names.get(a))
    rebuilt = body
    for name in sorted((c for c in candidates if c), key=lambda c: (-len(c), c)):
        clean = render.sanitize_source_text(name, "label", limit=0, on_suspect=note)
        if clean.startswith(render.QUOTE_OPEN + "[suspect_text ") and name in rebuilt:
            rebuilt = rebuilt.replace(name, clean[1:-1])
    return render.sanitize_source_text(rebuilt, "note", limit=0, on_suspect=note)[1:-1], True


def _direction(item: Mapping[str, Any]) -> str | None:
    """'increase' · 'decrease' · 'none'(같다) · None(방향이 없는 변화 — 추가·삭제·이동 거리)."""
    before, after = _num(item.get("before")), _num(item.get("after"))
    if before is not None and after is not None:
        diff = after - before
    elif item.get("unit") == "rank" and _num(item.get("delta")) is not None:
        diff = float(item["delta"])
    else:
        return None
    return "increase" if diff > 0 else "decrease" if diff < 0 else "none"


def _order_row(item: Mapping[str, Any]) -> dict:
    """`brief.event_order` 가 읽는 행 모양으로 옮긴다 — 의미 이벤트·파라메트릭 항목 모두 (rel, magnitude=Δ)."""
    return {"change_kind": item["change_kind"], "design_relevant": 1 if item["design_relevant"] else 0,
            "rel": _num(item.get("rel")), "magnitude": _num(item.get("delta")), "cid": item["ref"], "_item": item}


# ---------------------------------------------------------------- 묶기(설계서 3.4.3)
@dataclass
class _Leaf:
    scope: str                    # 표시 범위 — 조립 접두, '<접두>/.'(직속 부품), '<접두>#n'(BFS 조각), 형제 채움이면 무리 접두
    path: str                     # 부품 전부를 담는 조립 접두(경계 단위의 공통 접두 계산용)
    parent: str                   # 형제 채우기의 무리(이 잎을 가른 접두)
    parts: list[str]
    whole: bool                   # 접두 아래 전부를 담았나(롤업 항목을 소유할 수 있나)
    rule: str = "asm"
    asm_atoms: tuple = ()
    merged: tuple = ()


def _segs(asm: str) -> list[str]:
    return [s for s in asm.split("/") if s] if asm else []


def _within(prefix: str, scope: str) -> bool:
    return scope == "" or prefix == scope or prefix.startswith(scope + "/")


def _join(prefix: str, seg: str) -> str:
    return f"{prefix}/{seg}" if prefix else seg


def partition(atoms: Mapping[tuple, Sequence[Mapping[str, Any]]], nodes: _Nodes, adj: Mapping[str, set[str]],
              caps: UnitCaps, *, target_lines: int) -> list[dict]:
    """원자 → 단위 뼈대 [{kind, scope_key, path, atoms[], rule, merged}]. 순수 계산이고 입력 순서와 무관하다.

    원자 열쇠 — ('P', dn) 부품 · ('Q', dn_a, dn_b) 쌍 · ('A', 접두) 조립(롤업) · ('G', 구획, 머리 참조) 전역.
    1) 조립 키 접두로 재귀 분할(넘치면 다음 조각, 평평하면 BFS 순서로 target_lines 마다) 2) 같은 무리의 작은 잎을 이어 붙임
    3) 단위를 가로지르는 쌍은 공통 접두마다 경계 단위 4) 전역 원자(+어디에도 안 든 조립 원자)는 구획 순으로 global#n.
    부품 원자 하나가 max_lines 를 넘으면 쪼개지 않고 그 부품만으로 단위 하나다(`atom_oversize` — 정확도 상한이라 실패가 아니다).
    """
    lines = {key: len(items) for key, items in atoms.items()}
    own: dict[str, int] = {}
    pairs: dict[str, list[tuple]] = {}
    parts: set[str] = set()
    for key in atoms:
        if key[0] == "P":
            own[key[1]] = own.get(key[1], 0) + lines[key]
            parts.add(key[1])
        elif key[0] == "Q":
            parts.update(key[1:3])
            for end in key[1:3]:
                pairs.setdefault(end, []).append(key)
    asm_keys = sorted(k for k in atoms if k[0] == "A")
    segs = {p: _segs(nodes.asm(p)) for p in parts}

    def dkey(p: str) -> tuple:
        return (nodes.dkey(p), p)

    def inner_pairs(members: set[str]) -> list[tuple]:
        found: set[tuple] = set()
        for p in members:
            found.update(k for k in pairs.get(p, ()) if k[1] in members and k[2] in members)
        return sorted(found)

    def load(members: set[str], scope: str | None) -> int:
        n = sum(own.get(p, 0) for p in members) + sum(lines[k] for k in inner_pairs(members))
        if scope is not None:
            n += sum(lines[k] for k in asm_keys if _within(k[1], scope))
        return n

    def bfs_chunks(prefix: str, path: str, parent: str, members: list[str]) -> list[_Leaf]:
        member_set = set(members)
        graph: dict[str, set[str]] = {p: set() for p in members}
        for key in inner_pairs(member_set):
            graph[key[1]].add(key[2])
            graph[key[2]].add(key[1])
        for p in members:
            graph[p].update(q for q in adj.get(p, ()) if q in member_set and q != p)
        order: list[str] = []
        seen: set[str] = set()
        for start in sorted(members, key=dkey):
            if start in seen:
                continue
            seen.add(start)
            queue = [start]
            while queue:
                current = queue.pop(0)
                order.append(current)
                for nb in sorted(graph[current] - seen, key=dkey):
                    seen.add(nb)
                    queue.append(nb)
        chunks: list[list[str]] = []
        current_chunk: list[str] = []
        for p in order:
            if current_chunk and load(set(current_chunk) | {p}, None) > target_lines:
                chunks.append(current_chunk)
                current_chunk = [p]
            else:
                current_chunk.append(p)
        if current_chunk:
            chunks.append(current_chunk)
        return [_Leaf(scope=f"{prefix}#{i}", path=path, parent=parent, parts=sorted(chunk, key=dkey), whole=False,
                      rule="atom_oversize" if (len(chunk) == 1 and own.get(chunk[0], 0) > caps.max_lines) else "bfs")
                for i, chunk in enumerate(chunks)]

    def split(prefix: str, depth: int, parent: str, members: list[str]) -> list[_Leaf]:
        if not members:
            return []
        if load(set(members), prefix) <= caps.max_lines:
            return [_Leaf(scope=prefix, path=prefix, parent=parent, parts=sorted(members, key=dkey), whole=True)]
        groups: dict[str, list[str]] = {}
        direct: list[str] = []
        for p in members:
            if len(segs[p]) > depth:
                groups.setdefault(segs[p][depth], []).append(p)
            else:
                direct.append(p)
        if not direct and len(groups) == 1:
            seg = next(iter(groups))
            return split(_join(prefix, seg), depth + 1, parent, members)
        if not groups:                                        # 평평하다 — BFS 순서로 자른다(조각끼리만 다시 잇는다)
            return bfs_chunks(prefix, prefix, prefix, direct)
        out: list[_Leaf] = []
        if direct:
            scope = f"{prefix}/." if prefix else "."
            if load(set(direct), None) <= caps.max_lines:
                out.append(_Leaf(scope=scope, path=prefix, parent=prefix, parts=sorted(direct, key=dkey), whole=False))
            else:
                out.extend(bfs_chunks(scope, prefix, scope, direct))
        for seg in sorted(groups):
            out.extend(split(_join(prefix, seg), depth + 1, prefix, groups[seg]))
        return out

    leaves = split("", 0, "", sorted(parts, key=dkey))
    # 조립 원자 — 그 접두를 통째로 담은 잎이 있으면 그 잎이, 없으면 전역이 소유한다.
    asm_home: dict[tuple, int] = {}
    for key in asm_keys:
        for i, leaf in enumerate(leaves):
            if leaf.whole and _within(key[1], leaf.scope):
                asm_home[key] = i
                break
    for i, leaf in enumerate(leaves):
        leaf.asm_atoms = tuple(k for k in asm_keys if asm_home.get(k) == i)

    # 2) 형제 채우기 — 같은 무리의 잎을 범위 순으로 target_lines 까지 잇는다(next-fit).
    by_parent: dict[str, list[_Leaf]] = {}
    for leaf in leaves:
        by_parent.setdefault(leaf.parent, []).append(leaf)
    filled: list[_Leaf] = []
    for parent in sorted(by_parent):
        current: _Leaf | None = None
        for leaf in sorted(by_parent[parent], key=lambda x: x.scope):
            if current is None:
                current = leaf
                continue
            merged_parts = set(current.parts) | set(leaf.parts)
            merged_asm = current.asm_atoms + leaf.asm_atoms
            if ("atom_oversize" not in (current.rule, leaf.rule)
                    and load(merged_parts, None) + sum(lines[k] for k in merged_asm) <= target_lines):
                current = _Leaf(scope=parent, path=parent, parent=parent, parts=sorted(merged_parts, key=dkey),
                                whole=False, rule="sibling", asm_atoms=merged_asm,
                                merged=(current.merged or (current.scope,)) + (leaf.scope,))
            else:
                filled.append(current)
                current = leaf
        if current is not None:
            filled.append(current)

    unit_of: dict[str, int] = {}
    skeletons: list[dict] = []
    for i, leaf in enumerate(filled):
        members = set(leaf.parts)
        for p in leaf.parts:
            unit_of[p] = i
        keys = [("P", p) for p in leaf.parts if ("P", p) in atoms] + inner_pairs(members) + list(leaf.asm_atoms)
        skeletons.append({"kind": "bundle", "scope_key": leaf.scope, "path": leaf.path, "atoms": keys,
                          "rule": leaf.rule, "merged": list(leaf.merged)})

    def fill(keys: Sequence[tuple]) -> list[list[tuple]]:
        groups: list[list[tuple]] = []
        current_group: list[tuple] = []
        n = 0
        for key in keys:
            if current_group and n + lines[key] > target_lines:
                groups.append(current_group)
                current_group, n = [], 0
            current_group.append(key)
            n += lines[key]
        if current_group:
            groups.append(current_group)
        return groups

    def rule_of(group: Sequence[tuple], default: str) -> str:
        return "atom_oversize" if (len(group) == 1 and lines[group[0]] > caps.max_lines) else default

    # 3) 경계 — 두 끝이 다른 단위인 쌍 원자. 두 단위 범위의 공통 접두마다 target_lines 까지(next-fit).
    by_prefix: dict[str, list[tuple]] = {}
    for key in sorted(k for k in atoms if k[0] == "Q"):
        u, v = unit_of[key[1]], unit_of[key[2]]
        if u == v:
            continue
        common: list[str] = []
        for x, y in zip(_segs(skeletons[u]["path"]), _segs(skeletons[v]["path"])):
            if x != y:
                break
            common.append(x)
        by_prefix.setdefault("/".join(common), []).append(key)
    # 같은 두 묶음 사이의 쌍을 이어 세운다. 열쇠는 묶음의 범위 키다(해시 id 가 아니다) — 묶음 하나의 소유 참조가 바뀌어 그 id 가
    # 바뀌어도 다른 경계 무리의 순서가 흔들리지 않는다(id 에 상한 지문을 넣은 RA-2 뒤로 해시 순서가 경계 분할 전체를 바꿨다).
    # 범위 키가 같은 묶음(같은 무리의 형제 채움)은 첫 부품 키로 가른다.
    bundle_keys = [(s["scope_key"], s["path"], min((nodes.dkey(p) for k in s["atoms"] if k[0] in ("P", "Q")
                                                    for p in k[1:3]), default="")) for s in skeletons]
    for prefix in sorted(by_prefix):
        keys = sorted(by_prefix[prefix],
                      key=lambda k: (tuple(sorted((bundle_keys[unit_of[k[1]]], bundle_keys[unit_of[k[2]]]))),
                                     tuple(sorted((nodes.dkey(k[1]), nodes.dkey(k[2])))), k))
        for i, group in enumerate(fill(keys)):
            skeletons.append({"kind": "boundary", "scope_key": f"boundary:{prefix}#{i}", "path": prefix,
                              "atoms": group, "rule": rule_of(group, "boundary"), "merged": []})

    # 4) 전역 — 구획 순(명명 치수 → 롤업은 최상위 접두별 → scope → 모르는 버킷 → 그 밖). 소유 항목 0건이면 만들지 않는다(W2-07).
    def global_key(key: tuple) -> tuple:
        if key[0] == "A":
            return (_SECTIONS.index("rollup"), (_segs(key[1]) or [""])[0], key[1], "")
        return (_SECTIONS.index(key[1]) if key[1] in _SECTIONS else len(_SECTIONS), "", "", key[2])

    global_keys = sorted([k for k in atoms if k[0] == "G"] + [k for k in asm_keys if k not in asm_home],
                         key=global_key)
    for i, group in enumerate(fill(global_keys)):
        skeletons.append({"kind": "global", "scope_key": f"global#{i}", "path": "", "atoms": group,
                          "rule": rule_of(group, "section"), "merged": []})
    return skeletons


def _caps_key(caps: UnitCaps) -> str:
    """분할 상한 넷의 지문 — sha1(canonical_json(asdict(caps)))[:8]. unit_id 에 든다."""
    return _sha1(canonical_json(asdict(caps)))[:8]


# 단계 C(m2-wp2 걸음 5 `units.persist`)는 단위 행을 (target_key, unit_id) 로 내용 주소 저장한다(INSERT OR IGNORE — 한 번 쓰고
# 고치지 않는다). 그러려면 한 타깃 안에서 unit_id 가 단위의 전부를 정해야 한다. 소유 참조만으로는 모자라다 — 범위 키(BFS 조각
# 번호)·문맥 줄의 소유 단위·링크·전역 단위 목록·요약 글은 다른 단위들이 어떻게 나뉘었는지에 기대고, 분할은 상한 넷(UnitCaps)과
# 빌더 판에 기댄다(RA-2). 그래서 둘을 id 에 넣는다. 타깃의 diff·IR 은 불변이므로 같은 상한·같은 판이면 같은 단위가 같은 id 로
# 다시 나오고, 상한을 바꾸면 모든 단위가 새 id 를 받는다(옛 행은 옛 rev 의 것으로 남고 활성 rev 의 문맥이 옛 행을 가리키지 않는다).
def _unit_id(kind: str, refs: Sequence[str], caps: UnitCaps) -> str:
    """'u-' + sha1(builder 판|상한 지문|종류|정렬한 소유 참조)[:12] — 참조 스킴처럼 보이지 않게 'u-' 다(W2-18)."""
    return "u-" + _sha1(f"{BUILDER_VERSION}|{_caps_key(caps)}|{kind}|" + "\n".join(sorted(refs)))[:12]


# ---------------------------------------------------------------- 줄 구조(설계서 3.6.2)
def unit_lines(items: Sequence[Mapping[str, Any]], alias_of: Mapping[str, str] | None = None) -> list[dict]:
    """한 단위의 항목 → 줄 구조 [{ref, text, code, alias, layer, klass, direction, caveat, conf, derived_of, group, …}].

    항목 하나에 한 줄이다(W2-17) — 동형 묶음은 `group` 열쇠로만 표시하고 접는 것은 요약 렌더에서만 한다. 순서는
    `brief.event_order` 를 원자 단위로 쓴다 — 원자마다 대표 줄(그 원자에서 event_order 가 맨 앞에 세우는 줄)로 원자를 세우고,
    원자 안은 이벤트 → 그 파생 줄 → 이벤트 없는 원자료(|rel| 큰 순 → 참조 순)다. 설계 변경이 아닌 줄은 맨 뒤다.
    항목에는 빌드가 붙인 `_atom`·`_anchors`·`_body` 가 있어야 한다. 줄의 `_item` 은 빌드 안에서만 쓰고 끝에 뗀다.
    """
    alias_of = alias_of or {}
    by_atom: dict[Any, list[Mapping[str, Any]]] = {}
    for item in items:
        by_atom.setdefault(item["_atom"], []).append(item)

    def rest_key(i: Mapping[str, Any]) -> tuple:
        rel = _num(i.get("rel"))
        return (0 if rel is not None else 1, -abs(rel or 0.0), i["ref"], i["text"])

    def inner_order(group: Sequence[Mapping[str, Any]]) -> list[tuple[Mapping[str, Any], str | None]]:
        events = [r["_item"] for r in brief.event_order([_order_row(i) for i in group if i["layer"] == "semantic"])]
        rest = sorted((i for i in group if i["layer"] != "semantic"), key=rest_key)
        out: list[tuple[Mapping[str, Any], str | None]] = []
        used: set[int] = set()
        for event in events:
            out.append((event, None))
            derived = set(event["derived_from"])
            for item in rest:
                if id(item) not in used and item["ref"] in derived:
                    out.append((item, event["ref"]))
                    used.add(id(item))
        out.extend((i, None) for i in rest if id(i) not in used)
        return out

    reps = [(_order_row(ordered[0][0]), ordered) for ordered in (inner_order(g) for g in by_atom.values())]
    position = {id(row): n for n, row in enumerate(brief.event_order([row for row, _ in reps]))}
    reps.sort(key=lambda r: position[id(r[0])])

    lines: list[dict] = []
    for _row, ordered in reps:
        for item, derived_of in ordered:
            anchors = item["_anchors"]
            klass = item["klass"]
            lines.append({
                "ref": item["ref"], "text": item["_body"], "code": item["code"],
                "alias": "↔".join(alias_of[a] for a in anchors if a in alias_of),
                "layer": item["layer"], "klass": klass, "direction": _direction(item),
                "caveat": item["reason"] if klass != "active" else item.get("caveat"),
                "conf": item.get("confidence"), "derived_of": derived_of, "group": None,
                "unconfirmed": item["unconfirmed"], "lower_bound": item["lower_bound"],
                "section": item.get("section"), "bucket_unknown": item["bucket_unknown"], "_item": item,
            })
    keys = [canonical_json([line["code"], line["_item"].get("attr"), line["_item"].get("before"),
                            line["_item"].get("after"), line["_item"].get("unit"), _num(line["_item"].get("delta"))])
            for line in lines]
    counts: dict[str, int] = {}
    for key in keys:
        counts[key] = counts.get(key, 0) + 1
    for line, key in zip(lines, keys):
        if counts[key] >= _GROUP_MIN:
            line["group"] = "grp-" + _sha1(key)[:8]
    return lines


def unit_hash(items: Sequence[Mapping[str, Any]]) -> str:
    """값만 바뀌어도 달라지는 단위 해시 — sha256(canonical_json([{ref, before, after, flag, excluded_reason, text}]))[:16].
    cid 공식에는 값이 없어 값이 바뀐 것을 가리는 것은 이 해시다."""
    rows = sorted(canonical_json({"ref": i["ref"], "before": i.get("before"), "after": i.get("after"),
                                  "flag": i.get("flag"), "excluded_reason": i.get("excluded_reason"),
                                  "text": i.get("text")}) for i in items)
    return sha256_hex("[" + ",".join(rows) + "]")[:16]


# ---------------------------------------------------------------- 렌더(사람·패널·REST 용 — 앱이 감싼다)
def _clean_lines(lines: Sequence[str]) -> tuple[list[str], int]:
    """줄마다 판단어 린터 — 걸리면 그 줄만 «» 로 다시 감싼다(render.shield_line). (줄, 다시 감싼 줄 수)."""
    out: list[str] = []
    fallback = 0
    for line in lines:
        if render.lint_text(line)["ok"]:
            out.append(line)
        else:
            out.append(render.shield_line(line)[0])
            fallback += 1
    return out, fallback


def _line_tail(line: Mapping[str, Any]) -> str:
    parts = []
    if line.get("direction") == "decrease":
        parts.append("감소")
    elif line.get("direction") == "increase":
        parts.append("증가")
    if line.get("conf"):
        parts.append(f"conf={_word(line['conf'])}")
    if line.get("unconfirmed"):
        parts.append("unconfirmed")
    if line.get("lower_bound"):
        parts.append("lower_bound")
    if line.get("klass") == "caveat":
        parts.append(f"단서={_word(line['caveat'])}")
    elif line.get("klass") in ("excluded", "non_design"):
        parts.append(f"제외={_word(line['caveat'])}")
    elif line.get("caveat"):
        parts.append(f"caveat={_word(line['caveat'])}")
    return (" " + " ".join(parts)) if parts else ""


def _scope_label(unit: Mapping[str, Any]) -> str:
    scope = unit.get("scope_key") or ""
    if unit["kind"] in ("global", "excluded"):
        return scope
    if unit["kind"] == "boundary":
        return f"경계 {_q(unit['path'])}" if unit.get("path") else "경계 최상위"
    merged = (unit.get("flags") or {}).get("split", {}).get("merged")
    if merged:
        return " · ".join(_q(x) for x in merged)
    return _q(scope) if scope else "전체"


def _render(unit: Mapping[str, Any]) -> tuple[str, int]:
    lines = unit["lines"]
    out = [(f"[검토 단위 · {unit['unit_id']} · {unit['kind']} · 범위 {_scope_label(unit)} · 변경 줄 {len(lines)} · "
            f"부품 {len(unit['parts'])} · 계면 {unit['n_ifaces']}]"), f"[요약] {unit['synopsis']}"]
    out.extend(f"[주의] {note}" for note in unit["notices"])
    if unit["parts"]:
        out.append("[부품]")
        for part in unit["parts"]:
            before, after = part["material_before"], part["material_after"]
            material = (_q(after or before) if before == after or not (before and after)
                        else f"{_q(before)}→{_q(after)}") if (before or after) else "미상"
            out.append(f"{part['alias']} [{part['dn']}] {_q(part['name'])} 재질={material} 조립={_q(part['asm'])} "
                       f"소스={_word(part['source'])} 상태={part['status']}")
    out.append("[변경]")
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for line in lines:
        if line.get("group"):
            groups.setdefault(line["group"], []).append(line)
    emitted: set[str] = set()
    n = 0
    for line in lines:
        group = line.get("group")
        if group:
            if group in emitted:
                continue
            emitted.add(group)
            members = groups[group]
            n += 1
            out.append(f"C{n:02d} {_word(line['code'])} 같은 변화 {len(members)}건 — 첫 줄 «{line['text']}»"
                       f"{_line_tail(line)}")
            cells = [f"{member['alias'] or '-'}[{member['ref']}]" for member in members]
            for i in range(0, len(cells), _GROUP_ROW):
                out.append("  ↳ " + " · ".join(cells[i:i + _GROUP_ROW]))
        elif line.get("derived_of"):
            out.append(f"  ↳ [{line['ref']}] 원자료 «{line['text']}»{_line_tail(line)}")
        else:
            n += 1
            label = _word(line["code"]) if line["layer"] == "semantic" else f"(이벤트 없음) {_word(line['code'])}"
            alias = f" {line['alias']}" if line.get("alias") else ""
            out.append(f"C{n:02d} [{line['ref']}] {label}{alias} «{line['text']}»{_line_tail(line)}")
    context = unit["context"]["lines"]
    if context:
        out.append("[문맥]")
        role_label = {"boundary": "경계", "reference": "참고", "rollup": "롤업"}
        for line in context:
            tail = ""
            if line.get("reason"):
                tail = " — 설계 변경 아님" if line["reason"] in _NOT_DESIGN else f" — 제외 사유={_word(line['reason'])}"
            out.append(f"{role_label.get(line['role'], line['role'])} [{line['ref']}] {_word(line['code'])} "
                       f"«{line['text']}»{tail} (소유 {line['owner_unit']})")
    cleaned, fallback = _clean_lines(out)
    return "\n".join(cleaned), fallback


def render_unit(unit: Mapping[str, Any]) -> str:
    """전량 요약 — 줄 구조의 렌더(잘림 없음). 순번은 박지 않는다(`n/N` 은 읽을 때 붙인다, W2-13 c).

    원천 문자열은 전부 «» 안이고 코드가 «» 밖에 쓰는 낱말은 린터 어휘 밖이다. 그래도 걸리는 줄은 그 줄만 다시 감싼다.
    """
    return _render(unit)[0]


def _fmt_delta(value: float, unit: str | None, attr: str | None) -> str:
    kind = "fs" if attr == "fs" else _FMT_KIND.get(unit or "", "length" if unit else "count")
    return render.fmt_signed(value, kind)


def _synopsis(lines: Sequence[Mapping[str, Any]]) -> str:
    """[요약] 줄 — 종류별 건수와 방향, 이벤트 없는 원자료 수, 단서 수. 코드가 쓴 글뿐이다."""
    kinds: dict[str, list[int]] = {}
    for line in lines:
        kind = line["_item"]["change_kind"]
        counts = kinds.setdefault(kind if kind in brief.KIND_PRIORITY else "none", [0, 0, 0])
        counts[0] += 1
        counts[1] += line["direction"] == "decrease"
        counts[2] += line["direction"] == "increase"
    order = list(brief.KIND_PRIORITY)
    parts = []
    for kind in sorted(kinds, key=order.index):
        n, dec, inc = kinds[kind]
        dirs = " · ".join(x for x in (f"감소 {dec}" if dec else "", f"증가 {inc}" if inc else "") if x)
        parts.append(f"{kind} {n}" + (f"({dirs})" if dirs else ""))
    extra = []
    lower = sum(1 for line in lines if line["layer"] != "semantic" and not line["derived_of"])
    if lower:
        extra.append(f"이벤트 없는 원자료 {lower}")
    caveats = sum(1 for line in lines if line["klass"] == "caveat")
    if caveats:
        extra.append(f"단서 {caveats}")
    return " · ".join(parts) + (" | " + " · ".join(extra) if extra else "")


def digest_of(unit: Mapping[str, Any]) -> str:
    """단위 목록 항목의 글(전수 훑기가 본다) — 범위·건수 · 종류별 건수와 방향 · 재질 · 수치 범위 · 계면 전이 · 부품 이름 전부.

    고정 상한이 없다(설계서의 780자 상한은 D-21 로 뺐다). 이름 칸도 위생을 거쳐 «» 안이다(W2-19).
    """
    lines = unit["lines"]
    out = [f"범위 {_scope_label(unit)} · 변경 {len(lines)}줄 · 부품 {len(unit['parts'])} · 계면 {unit['n_ifaces']}",
           unit["synopsis"]]
    materials = []
    for part in unit["parts"]:
        before, after = part["material_before"], part["material_after"]
        if before and after and before != after:
            materials.append(f"{_q(before)}→{_q(after)}")
        elif before or after:
            materials.append(_q(after or before))
    if materials:
        out.append("재질 " + " · ".join(sorted(set(materials))))
    ranges: dict[tuple, list[float]] = {}
    for line in lines:
        item = line["_item"]
        delta = _num(item.get("delta"))
        if item["layer"] == "parametric" and delta is not None:
            ranges.setdefault((_s(item.get("attr")), _s(item.get("unit")), line["klass"] == "caveat"), []).append(delta)
    cells = []
    for (attr, unit_name, caveat), values in sorted(ranges.items()):
        lo, hi = min(values), max(values)
        span = _fmt_delta(lo, unit_name, attr) + ("" if lo == hi else "~" + _fmt_delta(hi, unit_name, attr))
        cells.append(f"{_word(attr) if attr else '값'} {span}{(' ' + unit_name) if unit_name else ''}"
                     + (" 단서" if caveat else ""))
    if cells:
        out.append("수치 " + " · ".join(cells))
    transitions: dict[str, int] = {}
    for line in lines:
        item = line["_item"]
        if item["bucket"] != "edge_changes" or item.get("family") == "hier":
            continue
        if item.get("op") == "kind_changed":
            key = f"{_word(item.get('kind_from'))}→{_word(item.get('kind_to'))}"
        elif item.get("op") in ("added", "removed"):
            key = f"{'추가' if item['op'] == 'added' else '삭제'} {_word(item.get('kind_to') or item.get('kind_from'))}"
        else:
            continue
        transitions[key] = transitions.get(key, 0) + 1
    if transitions:
        out.append("계면 " + " · ".join(f"{k} {v}" for k, v in sorted(transitions.items())))
    if unit["parts"]:
        out.append("부품 " + " · ".join(_q(part["name"]) for part in unit["parts"]))
    return _clean_lines([" | ".join(out)])[0][0]


def _title(unit: Mapping[str, Any]) -> str:
    if unit["kind"] == "global":
        sections = sorted({line.get("section") or "other" for line in unit["lines"]},
                          key=lambda s: _SECTIONS.index(s) if s in _SECTIONS else len(_SECTIONS))
        title = "전역 — " + " · ".join(_SECTION_LABEL.get(s, "기타") for s in sections)
    elif unit["kind"] == "excluded":
        title = "제외 — " + " · ".join(_word(r) for r in sorted({line["caveat"] or "-" for line in unit["lines"]}))
    else:
        title = f"{_scope_label(unit)} — 부품 {len(unit['parts'])} · 계면 {unit['n_ifaces']}"
    return _clean_lines([title])[0][0]


# ---------------------------------------------------------------- 빌드
def build_diff_units(diff_obj: Mapping[str, Any], view: Mapping[str, Any], *, caps: UnitCaps | None = None) -> dict:
    """diff 하나 → 검토 단위 빌드 결과. 순수 함수다(DB·네트워크 없음). 예외는 삼키지 않는다 — 접는 것은 호출자(단계 C) 몫이다.

    반환 {builder_version, status(ok·empty·oversize·failed), error, mode(single·bundles·none), blocked_by, caps,
    units[seq 순], unit_ids[[unit_id, seq]], stats, invariants, suspects[]}. 단위는 {unit_id, seq, kind, reviewable, scope_key,
    path, title, digest, synopsis, cids, n_changes, n_parts, n_ifaces, lines[], context{lines, links, overview?}, parts[],
    notices[], flags, summary, summary_sha, summary_chars, unit_hash} 이다. `status` 는 불변식 U1·U2·U3·U6 가 깨지면 failed,
    검토 대상 단위가 0 이면 empty, units_max 를 넘으면 oversize(단위를 버리지 않는다)다.

    두 스냅샷 가운데 하나라도 IR 이 없으면(폐기 — `view[side].present` 가 거짓) 단위를 세우지 않고 `failed`·`error='ir_absent'`
    다. 노드 표가 비면 앵커가 전부 떨어져 모든 항목이 전역 단위로 가는데, 그 빌드도 불변식을 다 지나 `ok` 로 섰다(RA-8).
    """
    caps = caps or UnitCaps()
    if not (view["base"]["present"] and view["target"]["present"]):
        return {"builder_version": BUILDER_VERSION, "status": "failed", "error": "ir_absent", "mode": "none",
                "blocked_by": (diff_obj.get("semantic") or {}).get("blocked_by"),
                "caps": {**asdict(caps), "retargeted": False}, "units": [], "unit_ids": [], "stats": {},
                "invariants": {}, "suspects": []}
    items, skipped = _collect(diff_obj)
    nodes = _Nodes(diff_obj, view)
    adj, near = _neighbors(view, nodes)
    suspects: dict[str, dict] = {}
    for item in items:
        item["_anchors"] = sorted({a for a in item["anchors_raw"] if nodes.known(a)})
        item["_body"], item["_suspect"] = _clean_body(item, view["names"], suspects)
        item["_review"] = item["klass"] in ("active", "caveat")

    # 검토 이벤트의 파생 항목은 klass 가 무엇이든 그 이벤트와 같은 원자에 타고 줄에 사유가 붙는다(설계서 3.4.1 '타는' 규칙).
    rider_of: dict[str, str] = {}
    for item in items:
        if item["layer"] == "semantic" and item["_review"]:
            for ref in item["derived_from"]:
                if ref != item["ref"]:
                    rider_of.setdefault(ref, item["ref"])

    def own_atom(item: Mapping[str, Any]) -> tuple:
        anchors = item["_anchors"]
        if len(anchors) == 1:
            return ("P", anchors[0])
        if len(anchors) == 2:
            return ("Q", anchors[0], anchors[1])
        if not anchors and item.get("asm") is not None:
            return ("A", item["asm"])
        return ("G", item.get("section") or "other", item["ref"])

    event_atom = {i["ref"]: own_atom(i) for i in items if i["layer"] == "semantic" and i["_review"]}
    for item in items:
        if item["layer"] == "semantic":
            item["_atom"] = event_atom.get(item["ref"])
        elif rider_of.get(item["ref"]) in event_atom:
            item["_review"], item["_atom"] = True, event_atom[rider_of[item["ref"]]]
        else:
            item["_atom"] = own_atom(item) if item["_review"] else None
    # 같은 cid 가 두 항목(브리지 충돌)이면 같은 원자에 싣고 cids 에는 한 번만 적는다.
    by_ref: dict[str, list[dict]] = {}
    for item in items:
        by_ref.setdefault(item["ref"], []).append(item)
    dup_refs = sorted(ref for ref, group in by_ref.items() if len(group) > 1)
    for ref in dup_refs:
        head = next((i for i in by_ref[ref] if i["_review"]), None)
        if head is not None:
            for item in by_ref[ref]:
                item["_review"], item["_atom"] = True, head["_atom"]

    atoms: dict[tuple, list[dict]] = {}
    for item in items:
        if item["_review"]:
            atoms.setdefault(item["_atom"], []).append(item)
    review_n = sum(len(group) for group in atoms.values())
    retargeted = False
    if review_n == 0:
        mode, skeletons = "none", []
    elif review_n <= caps.small_lines:
        mode = "single"
        skeletons = [{"kind": "bundle", "scope_key": "", "path": "", "atoms": sorted(atoms), "rule": "single",
                      "merged": []}]
    else:
        mode = "bundles"
        skeletons = partition(atoms, nodes, adj, caps, target_lines=caps.target_lines)
        if len(skeletons) > caps.units_max and caps.target_lines < caps.max_lines:
            skeletons = partition(atoms, nodes, adj, caps, target_lines=caps.max_lines)
            retargeted = True

    # 제외 단위 — 사유 → 표시 키 순으로 max_lines 마다 자른다. 같은 참조와, 제외 쪽 이벤트와 그 파생 항목은 한 원자로
    # 둔다(한 단위 안에서 이벤트 → 파생 순으로 보인다).
    lead_of: dict[str, str] = {}
    for item in items:
        if item["layer"] == "semantic" and not item["_review"]:
            for ref in item["derived_from"]:
                lead_of.setdefault(ref, item["ref"])
    groups: dict[str, list[dict]] = {}
    for item in items:
        if not item["_review"]:
            lead = lead_of.get(item["ref"]) if item["layer"] != "semantic" else None
            groups.setdefault(lead or item["ref"], []).append(item)

    def ex_key(ref: str) -> tuple:
        head = groups[ref][0]
        anchor = head["_anchors"][0] if head["_anchors"] else ""
        return (head["reason"] or "", nodes.dkey(anchor) if anchor else "", ref)

    chunk: list[str] = []
    chunk_n = 0
    chunks: list[list[str]] = []
    for ref in sorted(groups, key=ex_key):
        if chunk and chunk_n + len(groups[ref]) > caps.max_lines:
            chunks.append(chunk)
            chunk, chunk_n = [], 0
        chunk.append(ref)
        chunk_n += len(groups[ref])
    if chunk:
        chunks.append(chunk)
    for n, refs in enumerate(chunks):
        keys = []
        for ref in refs:
            key = ("X", n, ref)
            atoms[key] = groups[ref]
            for item in groups[ref]:
                item["_atom"] = key
            keys.append(key)
        skeletons.append({"kind": "excluded", "scope_key": f"excluded#{n}", "path": "", "atoms": keys,
                          "rule": "reason", "merged": []})

    units = [_make_unit(s, atoms, nodes, diff_obj, caps) for s in skeletons]
    owner = {ref: unit["unit_id"] for unit in units for ref in unit["cids"]}
    for unit in units:
        _attach_context(unit, units, owner, nodes, adj, near)
    reviewable = [u for u in units if u["reviewable"]]
    for unit in units:
        if unit["kind"] == "global":
            # 단위 목록·총량은 소유 줄이 아니라 문맥이다(W2-01·W2-07) — 묶음 사이 조합을 보는 자리.
            unit["context"]["overview"] = {"units": [[u["unit_id"], u["kind"], u["n_changes"]]
                                                     for u in sorted(reviewable, key=lambda u: u["unit_id"])],
                                           "lines_total": sum(u["n_changes"] for u in reviewable)}
        _finish_unit(unit, diff_obj)

    order = {kind: n for n, kind in enumerate(UNIT_KINDS)}
    units.sort(key=lambda u: (order[u["kind"]], u["scope_key"], u["unit_id"]))
    for seq, unit in enumerate(units, start=1):
        unit["seq"] = seq
    built = {
        "builder_version": BUILDER_VERSION, "error": None, "mode": mode,
        "blocked_by": (diff_obj.get("semantic") or {}).get("blocked_by"),
        "caps": {**asdict(caps), "retargeted": retargeted}, "units": units,
        "unit_ids": [[u["unit_id"], u["seq"]] for u in units],
        "suspects": [suspects[k] for k in sorted(suspects)],
    }
    built["stats"] = _stats(items, skipped, units, dup_refs, diff_obj)
    for unit in units:                                    # 빌드 안에서만 쓰는 칸을 뗀다
        unit.pop("_items", None)
        for line in unit["lines"]:
            line.pop("_item", None)
    built["invariants"] = check_invariants(diff_obj, built, caps)
    if any(built["invariants"][k] for k in ("U1_unassigned", "U2_double_owned", "U3_oversize", "U6_context")):
        built["status"] = "failed"
    elif not reviewable:
        built["status"] = "empty"
    elif len(reviewable) > caps.units_max:
        built["status"] = "oversize"
    else:
        built["status"] = "ok"
    return built


def _make_unit(skeleton: Mapping[str, Any], atoms: Mapping[tuple, Sequence[dict]], nodes: _Nodes,
               diff_obj: Mapping[str, Any], caps: UnitCaps) -> dict:
    kind = skeleton["kind"]
    items = [item for key in skeleton["atoms"] for item in atoms[key]]
    lines = unit_lines(items)
    parts_seen: list[str] = []                           # 줄 순서로 처음 나온 부품부터 P1, P2 …
    for line in lines:
        for dn in line["_item"]["_anchors"]:
            if dn not in parts_seen:
                parts_seen.append(dn)
    alias = {dn: f"P{n}" for n, dn in enumerate(parts_seen, start=1)}
    for line in lines:
        line["alias"] = "↔".join(alias[a] for a in line["_item"]["_anchors"])
    structural = diff_obj.get("structural") or {}
    status_of: dict[str, set[str]] = {}
    for change in structural.get("node_changes") or ():
        if isinstance(change, Mapping) and change.get("dn") in alias:
            status_of.setdefault(str(change["dn"]), set()).add(_PART_STATUS.get(_s(change.get("op")), "변경"))
    orphans = structural.get("orphans_delta") or {}
    for key, label in (("became_orphan", "고아됨"), ("left_orphan", "고아 벗어남")):
        for dn in orphans.get(key) or ():
            if dn in alias:
                status_of.setdefault(str(dn), set()).add(label)
    parts = [{"dn": dn, "alias": alias[dn], "name": nodes.name(dn), "asm": nodes.asm(dn), "source": nodes.source(dn),
              "status": "·".join(sorted(status_of.get(dn) or {"유지"})),
              "material_before": nodes.material(dn, "base"), "material_after": nodes.material(dn, "target"),
              "nids_base": nodes.nids(dn, "base"), "nids_target": nodes.nids(dn, "target")} for dn in parts_seen]
    refs = sorted({i["ref"] for i in items})
    flags: dict[str, Any] = {"split": {"rule": skeleton["rule"]}}
    if skeleton.get("merged"):
        flags["split"]["merged"] = list(skeleton["merged"])
    if len(items) > len(refs):
        flags["dup_cid_n"] = len(items) - len(refs)
    suspect_lines = sum(1 for i in items if i["_suspect"])
    if suspect_lines:
        flags["suspect_lines"] = suspect_lines
    unknown = sum(1 for i in items if i["bucket_unknown"])
    if unknown:
        flags["bucket_unknown_n"] = unknown
    return {
        "unit_id": _unit_id(kind, refs, caps), "kind": kind, "reviewable": kind != "excluded",
        "scope_key": skeleton["scope_key"], "path": skeleton.get("path") or "", "cids": refs,
        "n_changes": len(lines), "n_parts": len(parts),
        "n_ifaces": len({tuple(i["_anchors"]) for i in items if len(i["_anchors"]) == 2}),
        "lines": lines, "parts": parts, "flags": flags, "unit_hash": unit_hash(items),
        "context": {"lines": [], "links": []}, "_items": items,
    }


def _attach_context(unit: dict, units: Sequence[dict], owner: Mapping[str, str], nodes: _Nodes,
                    adj: Mapping[str, set[str]], near: Mapping[str, set[str]]) -> None:
    """문맥 줄(셈에 넣지 않는다) — 경계: 이 단위 부품에 걸린 경계 단위 항목 · 참고: 같은 부품의 제외 항목 ·
    롤업: 이 단위 부품의 조립을 다룬 전역 롤업 항목. 문맥 줄의 참조는 반드시 다른 단위가 소유한다(U6).
    `links` 는 단위 사이 연결(경계 공유 · 1홉 이웃 · 근접)이다."""
    if not unit["reviewable"]:
        return
    mine = {p["dn"] for p in unit["parts"]}
    asms = {nodes.asm(dn) for dn in mine}
    lines: list[dict] = []
    links: dict[str, set[str]] = {}
    for other in units:
        if other is unit:
            continue
        for item in other["_items"]:
            touches = bool(set(item["_anchors"]) & mine)
            role = ("boundary" if other["kind"] == "boundary" and touches
                    else "reference" if other["kind"] == "excluded" and touches
                    else "rollup" if other["kind"] == "global" and item.get("asm") in asms else None)
            if role is None:
                continue
            lines.append({"ref": item["ref"], "text": item["_body"], "code": item["code"],
                          "owner_unit": owner[item["ref"]], "role": role,
                          "reason": item["reason"] if role == "reference" else None})
            if role == "boundary":
                links.setdefault(other["unit_id"], set()).add("boundary")
        if other["reviewable"] and other["kind"] != "global":
            theirs = {p["dn"] for p in other["parts"]}
            if any(adj.get(dn, set()) & theirs for dn in mine):
                links.setdefault(other["unit_id"], set()).add("neighbor")
            if any(near.get(dn, set()) & theirs for dn in mine):
                links.setdefault(other["unit_id"], set()).add("near")
    role_order = {"boundary": 0, "rollup": 1, "reference": 2}
    unique = {(x["role"], x["ref"], x["code"], x["text"]): x for x in lines}
    unit["context"] = {
        "lines": sorted(unique.values(), key=lambda x: (role_order[x["role"]], x["owner_unit"], x["ref"], x["code"],
                                                         x["text"])),
        "links": [{"unit_id": uid, "via": sorted(via)} for uid, via in sorted(links.items())],
    }


def _finish_unit(unit: dict, diff_obj: Mapping[str, Any]) -> None:
    """[요약]·[주의]·제목·목록 글·요약 렌더와 해시."""
    unit["synopsis"] = _synopsis(unit["lines"])
    notices = []
    semantic = diff_obj.get("semantic") or {}
    if unit["reviewable"]:
        if semantic.get("blocked_by") == "G2":
            pending = int((diff_obj.get("correspondence") or {}).get("pending_n") or 0)
            notices.append(f"의미층 차단 [gate:G2] — same-as 미확정 {pending}건. 아래는 구조·파라메트릭층 원자료다. "
                           "추가·삭제로 적힌 부품이 이름만 바뀐 같은 부품일 수 있다.")
        elif semantic.get("blocked_by"):
            notices.append(f"의미층 차단({_word(semantic['blocked_by'])}) — 파라메트릭·계면 변경은 제외 단위에 있다.")
        caveat_lines = [line for line in unit["lines"] if line["klass"] == "caveat"]
        if caveat_lines:
            reasons = ", ".join(_word(r) for r in sorted({line["caveat"] for line in caveat_lines if line["caveat"]}))
            notices.append(f"단서 변경 {len(caveat_lines)}줄 — 비교 잣대가 확인되지 않은 수치다({reasons}).")
        if unit["flags"].get("bucket_unknown_n"):
            notices.append(f"모르는 버킷 항목 {unit['flags']['bucket_unknown_n']}줄 — 이 판의 단위 생성기가 모르는 diff 자리에서 왔다.")
    unit["notices"] = notices
    unit["title"] = _title(unit)
    unit["digest"] = digest_of(unit)
    summary, fallback = _render(unit)
    if fallback:
        unit["flags"]["lint_fallback"] = fallback
    unit["summary"] = summary
    unit["summary_sha"] = sha256_hex(summary)
    unit["summary_chars"] = len(summary)


def _stats(items: Sequence[Mapping[str, Any]], skipped: Mapping[str, int], units: Sequence[Mapping[str, Any]],
           dup_refs: Sequence[str], diff_obj: Mapping[str, Any]) -> dict:
    """빌드 회계(설계서 3.4.7) — 글자는 세기만 하고 어디서도 자르지 않는다."""
    by_layer: dict[str, int] = {}
    by_klass: dict[str, int] = {}
    excluded_by_reason: dict[str, int] = {}
    for item in items:
        by_layer[item["layer"]] = by_layer.get(item["layer"], 0) + 1
        by_klass[item["klass"]] = by_klass.get(item["klass"], 0) + 1
        if item["klass"] != "active" and item["reason"]:
            excluded_by_reason[item["reason"]] = excluded_by_reason.get(item["reason"], 0) + 1
    derived = {ref for item in items if item["layer"] == "semantic" for ref in item["derived_from"]}
    reviewable = [u for u in units if u["reviewable"]]
    sizes = sorted(u["n_changes"] for u in reviewable)

    def pct(q: float) -> int:
        return sizes[min(len(sizes) - 1, int(q * len(sizes)))] if sizes else 0

    return {
        "items_total": len(items), "by_layer": dict(sorted(by_layer.items())),
        "by_klass": dict(sorted(by_klass.items())),
        # 값이 같은 표지 항목은 이제 제외 단위의 줄이다 — 셈은 그 줄의 사유에서 낸다(excluded_by_reason 에도 같은 수가 있다).
        "noise_n": skipped["noise"], "null_both_n": sum(1 for i in items if i["reason"] == "null_both"),
        "incomparable_same_n": sum(1 for i in items if i["reason"] == "incomparable_same"),
        "rollup_unchanged_n": skipped["rollup_unchanged"],
        "dup_cid_n": len(dup_refs),
        # 이벤트 없는 활성 원자료 — 지금 패널 흐름에서 좌석에 가지 않던 변화의 크기다.
        "lower_only_n": sum(1 for i in items if i["layer"] != "semantic" and i["klass"] == "active"
                            and i["ref"] not in derived),
        "excluded_by_reason": dict(sorted(excluded_by_reason.items())),
        "units": {**{kind: sum(1 for u in units if u["kind"] == kind) for kind in UNIT_KINDS},
                  "reviewable": len(reviewable)},
        "lines_total": sum(u["n_changes"] for u in units),
        "reviewable_lines": sum(u["n_changes"] for u in reviewable),
        "lines_per_unit": {"p50": pct(0.5), "p95": pct(0.95), "max": sizes[-1] if sizes else 0},
        "summary_chars_total": sum(u["summary_chars"] for u in units),
        "parts_changed": len({p["dn"] for u in reviewable for p in u["parts"]}),
        "pending_sameas_n": int((diff_obj.get("correspondence") or {}).get("pending_n") or 0),
        "bucket_unknown_n": sum(1 for i in items if i["bucket_unknown"]),
        "atom_oversize_n": sum(1 for u in units if u["flags"]["split"]["rule"] == "atom_oversize"),
        "lint_fallback_n": sum(int(u["flags"].get("lint_fallback") or 0) for u in units),
        "suspect_lines_n": sum(int(u["flags"].get("suspect_lines") or 0) for u in units),
    }


# ---------------------------------------------------------------- 불변식(설계서 3.4.5)
def check_invariants(diff_obj: Mapping[str, Any], built: Mapping[str, Any], caps: UnitCaps | None = None) -> dict:
    """{U1_unassigned[], U2_double_owned[], U3_oversize[], U4_lint, U5_clipped, U6_context[]} — 빈 목록·0 이 정상이다.

    U1 은 독립 순회(`walk_cids`)의 cid 가 단위 소유 참조 ∪ 변화 아님(noise·바뀌지 않은 롤업)에 다 드는지,
    U2 는 참조마다 소유 단위가 하나인지, U3 는 검토 단위의 줄 수가 max_lines 안이거나 부품 원자 하나짜리(`atom_oversize`)인지,
    U4 는 린터 대체 뒤의 위반 수, U5 는 원천 문자열 절단 수(limit=0 이라 늘 0), U6 은 문맥 줄 참조가 다른 단위 소유인지다.
    """
    caps = caps or UnitCaps(**{k: v for k, v in (built.get("caps") or {}).items() if k in UnitCaps.__dataclass_fields__})
    units = built["units"]
    owned: dict[str, set[str]] = {}
    for unit in units:
        for ref in unit["cids"]:
            owned.setdefault(ref, set()).add(unit["unit_id"])
    exempt: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            if isinstance(value.get("cid"), str) and _non_change(value):
                exempt.add(value["cid"])
            for v in value.values():
                visit(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                visit(v)

    for layer in LAYERS:
        visit(diff_obj.get(layer) or {})
    cids_of = {u["unit_id"]: set(u["cids"]) for u in units}
    return {
        "U1_unassigned": sorted(cid for cid in walk_cids(diff_obj) if cid not in owned and cid not in exempt),
        "U2_double_owned": sorted(ref for ref, owners in owned.items() if len(owners) > 1),
        "U3_oversize": sorted(u["unit_id"] for u in units
                              if u["n_changes"] > caps.max_lines and u["flags"]["split"]["rule"] != "atom_oversize"),
        "U4_lint": sum(len(render.lint_text(u[key])["violations"]) for u in units
                       for key in ("summary", "digest", "title")),
        "U5_clipped": 0,
        "U6_context": sorted({line["ref"] for u in units for line in u["context"]["lines"]
                              if line["owner_unit"] == u["unit_id"]
                              or line["ref"] not in cids_of.get(line["owner_unit"], set())}),
    }


# ---------------------------------------------------------------- 동결 발췌(근거 꾸러미 A 층, 설계서 3.8)
_DEGRADED_NOTE = {
    "interfaces_truncated": "계면 목록이 잘린 캡처다",
    "interfaces_unreadable": "계면 목록을 읽지 못한 캡처다",
    "tol_config_unknown": "공차 설정을 모르는 캡처다",
    "schema_drift": "소스 스키마가 바뀐 캡처다",
}
_EDGE_RANK = {"interference": 0, "tied": 1, "touching": 1, "geometric": 1, "contact": 1, "scope": 1, "clearance": 2}
_EDGE_FIELDS = (("min_gap", "min_gap", "mm", "length"), ("contact_area_est", "밴드 면적", "mm2", "area"),
                ("penetration_depth", "관통 깊이", "mm", "length"), ("fs", "마찰", None, "fs"))
_RESULT_FIELDS = (("worst_stress", "MPa", "stress"), ("worst_g", "G", "acceleration"), ("worst_disp", "mm", "length"),
                  ("min_safety_factor", None, "ratio"))
_EVIDENCE_HEADS = {"part": "부품 명세", "iface": "계면·접촉", "contact": "계면·접촉", "neighbor": "이웃",
                   "result": "해석 결과", "rule": "규칙 적중"}


def _change(before: Any, after: Any, unit: str | None, kind: str) -> str:
    """값 하나의 두 스냅샷 표기 — 같으면 한 번, 다르면 before→after. 없으면 '미측정'."""
    b, a = render.fmt_num(before, kind), render.fmt_num(after, kind)
    tail = f" {unit}" if unit else ""
    return f"{a}{tail}" if b == a else f"{b}→{a}{tail}"


def _scalar(value: Any) -> Any:
    return value.get("value") if isinstance(value, Mapping) else value


def _attrs(node: Mapping[str, Any] | None) -> Mapping[str, Any]:
    attrs = (node or {}).get("attrs")
    return attrs if isinstance(attrs, Mapping) else {}


def _seg(parts: Sequence[Any], *, quoted: bool, note) -> str:
    """조각 → 글. ('src', 값) 조각은 원천 문자열이라 위생을 거친다 — quoted 면 «» 안, 아니면 «» 없이(엔진이 감싼다)."""
    out = []
    for part in parts:
        if isinstance(part, tuple):
            clean = render.sanitize_source_text(part[1], "label", limit=0, on_suspect=note)
            out.append(clean if quoted else clean[1:-1])
        else:
            out.append(str(part))
    return "".join(out)


def _size_text(attrs_b: Mapping[str, Any], attrs_t: Mapping[str, Any], key: str) -> str | None:
    def dims(attrs):
        value = attrs.get(key)
        return [render.fmt_num(v, "length") for v in value] if isinstance(value, (list, tuple)) and value else None

    b, a = dims(attrs_b), dims(attrs_t)
    if b is None and a is None:
        return None
    b_txt, a_txt = "×".join(b) if b else "미측정", "×".join(a) if a else "미측정"
    return f"크기 {a_txt} mm" if b_txt == a_txt else f"크기 {b_txt}→{a_txt} mm"


def _node_line(alias: str, before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> list:
    node = after or before or {}
    ab, at = _attrs(before), _attrs(after)
    parts: list[Any] = [f"{alias} " if alias else "", ("src", node.get("label") or node.get("nid")),
                        f" {_s(node.get('domain'))} {_s(node.get('kind'))}"]
    if node.get("domain") == "dyna" and node.get("kind") == "pid":
        parts.append(f" · pid {_s(node.get('local_key'))}")
        if ab.get("n_elems") is not None or at.get("n_elems") is not None:
            parts.append(f" · 요소 {_change(ab.get('n_elems'), at.get('n_elems'), None, 'count')}")
    size = _size_text(ab, at, "size_def") or _size_text(ab, at, "size")
    if size:
        parts.append(f" · {size}")
    if ab.get("min_dim") is not None or at.get("min_dim") is not None:
        parts.append(f" · 두께 {_change(ab.get('min_dim'), at.get('min_dim'), 'mm', 'length')}")
    if ab.get("volume") is not None or at.get("volume") is not None:
        parts.append(f" · 부피 {_change(ab.get('volume'), at.get('volume'), 'mm3', 'volume')}")
    mat_b = _material_of(before) if before else None
    mat_a = _material_of(after) if after else None
    if mat_b or mat_a:
        parts.append(" · 재질 ")
        if mat_b and mat_a and mat_b != mat_a:
            parts.extend([("src", mat_b), "→", ("src", mat_a)])
        else:
            parts.append(("src", mat_a or mat_b))
    if node.get("asm_key"):
        parts.extend([" · 조립 ", ("src", node["asm_key"])])
    if before is None:
        parts.append(" · 추가")
    elif after is None:
        parts.append(" · 삭제")
    return parts


def evidence_lines(unit: Mapping[str, Any], ir_view: Mapping[str, Any]) -> dict:
    """단위 하나의 동결 근거(A 층) — 그 부품의 두 스냅샷 명세, 끼인 계면 전부(변경 없는 것 포함, clearance 는 '근접'),
    1홉 이웃, 해석 결과 행(`results.part_risk`), 규칙 적중을 IR 동결본에서 뽑는다. 네트워크를 쓰지 않고 자르지 않는다.

    반환 {unit_id, status(ok·failed·none), error, evidence[{ref, text, kind}], notes, text, sha, chars, suspects[]}.
    `ref` 는 `p:`·`e:`·`rule:` 뿐이다(새 스킴 없음 — C-8). `text` 는 «» 없이 위생을 거친 글이고(엔진이 감싼다) 렌더(`text`)는
    원천 문자열을 «» 안에 둔다. 줄 순서만 우선순위를 따른다 — 단위 부품 명세 → 바뀐 계면 → 바뀌지 않은 계면(간섭 → 접합·접촉 →
    근접, 그 안은 |min_gap| 오름차순) → 이웃 → 해석 결과 → 규칙 적중. 제외 단위는 none, IR 이 폐기된 쪽이 있으면
    failed(`ir_absent`)다. 같은 입력이면 `sha` 가 같다.
    """
    suspects: dict[str, dict] = {}

    def note(payload: Mapping[str, Any]) -> None:
        suspects.setdefault(str(payload.get("sha1")), dict(payload))

    def done(status: str, error: str | None, rows: list[tuple[str, list, str]], notes: list[str]) -> dict:
        evidence = [{"ref": ref, "text": _seg(parts, quoted=False, note=note), "kind": kind} for ref, parts, kind in rows]
        out = [f"[근거 — 동결본 발췌 · 단위 {unit['unit_id']} · 검증 대상 · 결론 아님]"]
        if error:
            out.append(f"[근거 없음 — {error}]")
        last = None
        for (ref, parts, kind) in rows:
            if _EVIDENCE_HEADS.get(kind, kind) != last:
                last = _EVIDENCE_HEADS.get(kind, kind)
                out.append(f"[{last}]")
            out.append(f"[{ref}] {_seg(parts, quoted=True, note=note)}")
        out.extend(f"[주의] {x}" for x in notes)
        text = "\n".join(_clean_lines(out)[0])
        body = {"evidence": [{"ref": r["ref"], "text": r["text"]} for r in evidence], "notes": " ".join(notes)}
        return {"unit_id": unit["unit_id"], "status": status, "error": error, "evidence": evidence,
                "notes": body["notes"], "text": text, "sha": sha256_hex(canonical_json(body)), "chars": len(text),
                "suspects": [suspects[k] for k in sorted(suspects)]}

    if not unit.get("reviewable", True):
        return done("none", None, [], [])
    if not (ir_view["base"]["present"] and ir_view["target"]["present"]):
        return done("failed", "ir_absent", [], [])

    nodes = {side: {str(n["nid"]): n for n in ir_view[side]["nodes"]} for side in ("base", "target")}
    alias_of: dict[str, str] = {}
    mine: set[str] = set()
    rows: list[tuple[str, list, str]] = []
    for part in unit.get("parts") or ():
        nids_b, nids_t = list(part.get("nids_base") or ()), list(part.get("nids_target") or ())
        mine.update(nids_b + nids_t)
        for nid in nids_b + nids_t:
            alias_of.setdefault(nid, part["alias"])
        by_key: dict[tuple, tuple[list, list]] = {}
        for side, nids in (("base", nids_b), ("target", nids_t)):
            for nid in nids:
                node = nodes[side].get(nid)
                if node is not None:
                    key = (_s(node.get("domain")), _s(node.get("kind")))
                    by_key.setdefault(key, ([], []))[0 if side == "base" else 1].append(node)
        for key in sorted(by_key):
            befores, afters = by_key[key]
            for i in range(max(len(befores), len(afters))):
                before = befores[i] if i < len(befores) else None
                after = afters[i] if i < len(afters) else None
                rows.append((str((after or before)["nid"]), _node_line(part["alias"], before, after), "part"))

    def label(nid: Any) -> str:
        node = nodes["target"].get(str(nid)) or nodes["base"].get(str(nid)) or {}
        return str(node.get("label") or nid or "")

    edges: dict[str, list] = {}
    for idx, side in enumerate(("base", "target")):
        for edge in ir_view[side]["edges"]:
            if str(edge.get("kind_family") or "") not in ("iface", "contact") or edge.get("status") == "rejected":
                continue
            ends = {str(edge.get("a") or ""), str(edge.get("b") or "")} | {str(m) for m in edge.get("members") or ()}
            if ends & mine:
                edges.setdefault(str(edge["eid"]), [None, None])[idx] = edge
    edge_rows: list[tuple[tuple, str, list, str]] = []
    neighbors: dict[str, bool] = {}
    notes: list[str] = []
    auto_interference = lower_bound = False
    for eid, (before, after) in sorted(edges.items()):
        edge = after or before
        ab, at = _attrs(before), _attrs(after)
        kind_b, kind_a = _s((before or {}).get("kind")), _s((after or {}).get("kind"))
        kind = kind_a or kind_b
        if kind == "scope":
            members_b = len((before or {}).get("members") or ())
            members_a = len((after or {}).get("members") or ())
            parts = [("src", at.get("title") or ab.get("title") or label(edge.get("a"))),
                     f" 접촉 범위 구성 {members_a}" if members_b == members_a else
                     f" 접촉 범위 구성 {members_b}→{members_a}"]
        else:
            parts = ["근접 " if kind == "clearance" else "", ("src", label(edge.get("a"))), "↔",
                     ("src", label(edge.get("b"))), " ", kind if kind_b == kind_a or not kind_b or not kind_a
                     else f"{kind_b}→{kind_a}"]
            for other in (edge.get("a"), edge.get("b")):
                if other and str(other) not in mine:
                    neighbors[str(other)] = neighbors.get(str(other), False) or kind != "clearance"
        for key, word, unit_name, fmt in _EDGE_FIELDS:
            if ab.get(key) is not None or at.get(key) is not None:
                bound = " (하한)" if key == "penetration_depth" and (ab.get("penetration_depth_is_lower_bound")
                                                                   or at.get("penetration_depth_is_lower_bound")) else ""
                lower_bound = lower_bound or bool(bound)
                parts.append(f" · {word} {_change(ab.get(key), at.get(key), unit_name, fmt)}{bound}")
        status_b, status_a = _s((before or {}).get("status")), _s((after or {}).get("status"))
        parts.append(f" · status={status_a or status_b}" if status_b == status_a or not (status_a and status_b)
                     else f" · status={status_b}→{status_a}")
        auto_interference = auto_interference or (kind == "interference" and (status_a or status_b) == "auto")
        changed = before is None or after is None or _edge_state(before) != _edge_state(after)
        state = "추가" if before is None else "삭제" if after is None else "바뀜" if changed else "변경 없음"
        parts.append(f" · {state}")
        gap = _num(at.get("min_gap") if after is not None else ab.get("min_gap"))
        order = (0 if changed else 1, _EDGE_RANK.get(kind, 1), abs(gap) if gap is not None else float("inf"), eid)
        edge_rows.append((order, "e:" + eid.split(":", 1)[-1] if not eid.startswith("e:") else eid, parts,
                          "contact" if _s(edge.get("kind_family")) == "contact" else "iface"))
    rows.extend((ref, parts, kind) for _order, ref, parts, kind in sorted(edge_rows, key=lambda r: r[0]))

    for nid in sorted(neighbors, key=lambda n: (not neighbors[n], label(n), n)):
        node = nodes["target"].get(nid) or nodes["base"].get(nid)
        if node is None:
            continue
        parts = [("src", label(nid)), " 이웃" if neighbors[nid] else " 근접 이웃",
                 f" · {_s(node.get('domain'))} {_s(node.get('kind'))}"]
        material = _material_of(node)
        if material:
            parts.extend([" · 재질 ", ("src", material)])
        if node.get("asm_key"):
            parts.extend([" · 조립 ", ("src", node["asm_key"])])
        rows.append((nid, parts, "neighbor"))

    risk = {side: {str(r.get("nid")): r for r in ir_view[side]["part_risk"] if str(r.get("nid")) in mine}
            for side in ("base", "target")}
    for nid in sorted(set(risk["base"]) | set(risk["target"])):
        before, after = risk["base"].get(nid), risk["target"].get(nid)
        row = after or before
        parts = [("src", label(nid)), f" 해석 결과 pid {_s(row.get('pid'))}"]
        for key, unit_name, fmt in _RESULT_FIELDS:
            vb, va = _scalar((before or {}).get(key)), _scalar((after or {}).get(key))
            if vb is not None or va is not None:
                parts.append(f" · {key} {_change(vb, va, unit_name, fmt)}")
        if before is None or after is None:
            parts.append(" · 추가" if before is None else " · 삭제")
        rows.append((nid, parts, "result"))

    related = {f"p:{n.split(':', 1)[-1]}" for n in mine} | {r[1] for r in edge_rows}
    hits_seen: set[tuple] = set()
    for side in ("base", "target"):
        for hit in sorted(ir_view[side]["rule_hits"], key=lambda h: (_s(h.get("rule")), _s(h.get("payload_hash")))):
            if hit.get("pass") is not False:
                continue
            found = hit.get("found") if isinstance(hit.get("found"), Mapping) else {}
            refs = {str(r) for r in list(hit.get("refs") or ()) + list(found.get("refs") or ())}
            touched = sorted(refs & related)
            if not touched or (side, _s(hit.get("rule"))) in hits_seen:
                continue
            hits_seen.add((side, _s(hit.get("rule"))))
            parts = [f"{side} {_word(hit.get('rule'))} pass=false · severity=", ("src", hit.get("severity") or "-"),
                     " · ", ("src", found.get("text") or ""), f" · 이 단위에 걸린 참조 {len(touched)}건"]
            rows.append((f"rule:{_s(hit.get('rule'))}", parts, "rule"))

    for side in ("base", "target"):
        for code in ir_view[side]["degraded"]:
            notes.append(f"{side} 스냅샷 강등 표지 {_word(code)}" + (f" — {_DEGRADED_NOTE[code]}." if code in _DEGRADED_NOTE
                                                                  else "."))
    if auto_interference:
        notes.append("interference 의 status=auto 는 미확정 초안이다.")
    if lower_bound:
        notes.append("관통 깊이의 (하한) 표기는 하한 추정치다.")
    return done("ok", None, rows, notes)


def _edge_state(edge: Mapping[str, Any]) -> tuple:
    """계면이 바뀌었는지 견주는 열쇠 — 종류·상태·수치 칸·범위 구성원 수(동결본 그대로, 임계를 쓰지 않는다)."""
    attrs = _attrs(edge)
    return (edge.get("kind"), edge.get("status"), tuple(canonical_json(attrs.get(k)) for k, *_ in _EDGE_FIELDS),
            len(edge.get("members") or ()))


# ---------------------------------------------------------------- 단계 C 가 감쌀 투영(순수)
# 저장소를 받는 계약 이름(`manifest_items(store, target_key)` · `unit_refs(store, target_key, unit_id)` ·
# `review_payload(store, target_key, unit_id, agent_key)`)은 단계 C 몫이다 — 여기 셋은 단위 dict 를 받는 순수 투영이고 그쪽이 감싼다.
def manifest_item_of(unit: Mapping[str, Any]) -> dict:
    """전수 훑기용 단위 목록 항목 `{unit_id, kind, title, text}` — text 는 목록 글(digest)이다. 글자 상한은 없다."""
    return {"unit_id": unit["unit_id"], "kind": unit["kind"], "title": unit["title"], "text": unit["digest"]}


def refs_of(unit: Mapping[str, Any], evidence: Mapping[str, Any] | None = None) -> set[str]:
    """그 단위에서 판정이 인용할 수 있는 참조 — 소유 줄 + 근거 줄. 문맥 줄은 뺀다(다른 단위 소유라 Q8 에서 떨어진다)."""
    refs = {line["ref"] for line in unit["lines"]}
    refs.update(row["ref"] for row in ((evidence or {}).get("evidence") or ()))
    return refs


def payload_of(unit: Mapping[str, Any], evidence: Mapping[str, Any] | None = None) -> dict:
    """카드 대조 요청의 `unit`(M2.md 4.3) 가운데 단위가 정하는 칸. `missing[]`·`input_gaps` 는 타깃·전문가 수준이라 단계 C 가 더한다.

    lines·context·evidence 의 text 는 «» 없이 위생을 거친 글이다(엔진이 감싼다). 줄이지 않는다.
    """
    evidence = evidence or {}
    return {
        "unit_id": unit["unit_id"], "kind": unit["kind"], "title": unit["title"], "summary": unit["synopsis"],
        "lines": [{"ref": line["ref"], "text": line["text"]} for line in unit["lines"]],
        "context": [{"ref": line["ref"], "text": line["text"], "owner_unit": line["owner_unit"]}
                    for line in unit["context"]["lines"]],
        "evidence": [{"ref": row["ref"], "text": row["text"]} for row in evidence.get("evidence") or ()],
        "notes": " ".join(x for x in [*unit.get("notices", ()), evidence.get("notes") or ""] if x),
        "unit_hash": unit["unit_hash"], "summary_sha": unit["summary_sha"],
        "evidence_sha": evidence.get("sha"), "evidence_status": evidence.get("status"),
    }
