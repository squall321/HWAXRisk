# 의장 결정문 서술 처리 — parse_risk_spec·정규화(§4.2)·cites 검증(§4.4)·원자 펼침(§4.3·§4.6)·좌석 의견 추출(§4.5)
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from jsonschema import Draft7Validator

from app import render
from app.common import canonical_json, now_epoch, parse_ref
from app.errors import AppError
from app.taxonomy import load_taxonomy

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "risk_spec.v1.json"

# hwax-sim-deliberate.js parseSimSpec 의 펜스 정규식과 동일. 마지막 펜스를 쓴다(plan §4.2.2).
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```")


def _last_balanced_block(s: str) -> str | None:
    """텍스트 끝의 마지막 '}' 에서 역방향으로 중괄호를 세어 짝 '{' 까지의 블록을 돌려준다(중첩 JSON 방어)."""
    end = s.rfind("}")
    if end == -1:
        return None
    depth = 0
    for i in range(end, -1, -1):
        ch = s[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0:
                return s[i:end + 1]
    return None


def parse_risk_spec(text: str) -> dict | None:
    """결정문 텍스트에서 risk_spec JSON 을 뽑는다. 실패는 None(예외 없음, 비치명).

    (1) 마지막 ```json 펜스 → (2) 없거나 깨지면 텍스트 끝에서 역방향 마지막 균형 중괄호 블록
    → (3) dict 이고 schema=='risk_spec' 이 아니면 None.
    """
    s = "" if text is None else str(text)
    obj = None
    fences = _FENCE_RE.findall(s)
    if fences:
        try:
            obj = json.loads(fences[-1])
        except json.JSONDecodeError:
            obj = None  # 펜스 파싱 실패 → 균형 스캔 폴백
    if obj is None:
        block = _last_balanced_block(s)
        if block is None:
            return None
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            return None
    if not isinstance(obj, dict) or obj.get("schema") != "risk_spec":
        return None
    return obj


@lru_cache(maxsize=1)
def _validator() -> Draft7Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def validate_risk_spec(obj: dict) -> list[str]:
    """app/schemas/risk_spec.v1.json 으로 검증한 오류 메시지 목록(빈 리스트 = 통과). 경로 순으로 정렬."""
    errors = sorted(_validator().iter_errors(obj), key=lambda e: list(e.absolute_path))
    out = []
    for err in errors:
        path = "/".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"{path}: {err.message}")
    return out


# ================================================================ 상수(plan §4.2.2 · §4.3 · §4.6)
NORMALIZE_VERSION = "risk_spec-norm-1.0"

FACETS: tuple[str, ...] = (
    "intent", "constraint", "anomaly", "lineage", "vulnerability", "strength", "tradeoff", "unknown",
)

# enum 목록. 목록 밖 값은 invalid_enum 에 보존하고 taxonomy.enum_defaults 로 채운다(§4.2.2 1).
_ENUMS: dict[str, tuple[str, ...]] = {
    "direction": ("risk", "improvement", "neutral"),
    "severity": ("경미", "중대", "치명"),
    "judgement": ("OK", "WARNING", "FAIL", "undetermined"),
    "detectability.level": ("sim-detectable", "test-only", "field-only", "unknown"),
    "evidence_grade": ("측정", "문헌·규격", "도구예측", "경험칙"),
    "precedent": ("in_range", "out_of_range", "none"),
    "polarity": ("observation", "inference", "hypothesis"),
    "confidence": ("high", "medium", "low"),
    "verdict": ("go", "conditional", "no-go", "undetermined"),
    "status": ("open",),
}
_GRADE_RANK: dict[str, int] = {"경험칙": 1, "도구예측": 2, "문헌·규격": 3, "측정": 4}
_SEV3: dict[str, int] = {"경미": 1, "중대": 2, "치명": 3}
_SEV_JUDGEMENT: dict[str, tuple[str, ...]] = {"경미": ("OK", "WARNING"), "중대": ("WARNING", "FAIL"), "치명": ("FAIL",)}
_SEV_DEFAULT_JUDGEMENT: dict[str, str] = {"경미": "OK", "중대": "WARNING", "치명": "FAIL"}
_TRIGGER_RE = re.compile(r"^((env|load|time|mfg|use)\.[a-z_]+|none)$")
_CHANGE_KINDS: tuple[str, ...] = (
    "dimension", "placement", "topology", "material", "type", "count",
    "discretization", "result", "load_path", "consistency", "electrical", "none",
)

# §4.3.4 feature_snapshot 복사 상한.
FEATURE_SNAPSHOT_PER_REF = 12
FEATURE_SNAPSHOT_PER_FINDING = 40

# §4.3.3 precedent — cites 원천 속성명 → feature_vector 차원 이름.
# 표에 없는 이름이라도 코퍼스가 그 이름의 경계를 알고 있으면 그대로 대조한다(아래 pass-through) —
# 예측 도구(predict_sed 등)가 내는 값은 IR 형상 속성이 아니라서 이 표에 미리 적을 수 없기 때문이다(§7.6).
_FEATURE_OF_ATTR: dict[str, str] = {
    "min_gap": "min_gap",
    "penetration_depth": "max_pen_depth",
    "volume": "total_volume",
    "total_volume": "total_volume",
    "n_leaf": "n_leaf",
    "n_files": "n_files",
    "thin_ratio": "thin_ratio",
    "orphan_ratio": "orphan_ratio",
    "cross_file_ratio": "cross_file_ratio",
}

# §4.5 cited_refs 추출 정규식.
_CITED_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\[?((?:p|e|c):[0-9a-f]{12})\]?"),
    re.compile(r"\[?(d:[A-Za-z0-9_]+)\]?"),
    re.compile(r"(sig:[A-Za-z0-9_.\[\]]+?)(?=[\s\]·,]|$)"),
    re.compile(r"(name:[^\s|\]]+\|[^\s\]]+)"),
    re.compile(r"\[?((?:narr|reg|card|rule):[^\s\]]+)\]?"),
    re.compile(r"\[?(gate:G\d)\]?"),
    re.compile(r"\[?(tool:conv:[^\s\]#]+#\d+)\]?"),
)
_CHARACTER_SENTENCE_RE = re.compile(r"성격|성향|철학|경향|의도")
# §4.4.2 (1) 수치 토큰 — 식별자 안의 숫자(corner_45·F2·DV2)는 앞 글자 조건으로 제외한다.
_NUMBER_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_.])([-+]?\d+(?:\.\d+)?)\s?(mm²|mm³|mm|MPa|G|%)?")


@lru_cache(maxsize=1)
def _taxonomy() -> dict:
    return load_taxonomy()


@lru_cache(maxsize=1)
def _mechanism_index() -> tuple[dict[str, dict], dict[str, str]]:
    """(code → 항목, 동의어/detail → code) 색인. merged_into 는 대상 코드로 접는다."""
    axis = (_taxonomy().get("axes") or {}).get("mechanism") or []
    by_code: dict[str, dict] = {}
    alias: dict[str, str] = {}
    for item in axis:
        code = str(item.get("code") or "")
        if not code:
            continue
        by_code[code] = item
        alias[code] = code
        detail = str(item.get("detail") or "")
        if detail:
            alias.setdefault(detail, code)
        label = str(item.get("label") or "")
        if label:
            alias.setdefault(label, code)
    for code, item in by_code.items():
        merged = item.get("merged_into")
        if merged and merged in by_code:
            alias[code] = str(merged)
    for word, code in (_taxonomy().get("synonyms") or {}).items():
        alias[str(word)] = str(code)
    return by_code, alias


def _enum_default(name: str) -> Any:
    return (_taxonomy().get("enum_defaults") or {}).get(name)


def _dom_of(agent_key: str) -> str:
    """좌석 키 접두 도메인 — 'mech-housing-structure' → 'mech'."""
    return str(agent_key or "").split("-", 1)[0]


# ================================================================ 스코프 해석기(plan §4.4.1 검증 스코프)
@dataclass
class SpecContext:
    """risk_spec 정규화·cites 검증이 보는 스코프. 없는 채널은 None·빈 값으로 두면 강등 플래그로 표기된다."""

    panel_id: str = ""
    target_key: str = ""
    project_id: str = ""
    owner_sub: str = ""
    kind: str = "diff"                                   # snap | diff
    snapshot_ids: tuple[str, ...] = ()                   # pair 면 (base, target)
    diff_id: str = ""
    ir_hash: str = ""
    store: Any = None
    states: dict = field(default_factory=dict)           # snapshot_id -> rr_state.state_json
    irs: dict = field(default_factory=dict)              # snapshot_id -> rr_ir(nodes·edges·dims_named·warnings·rollups)
    diff: dict = field(default_factory=dict)             # rr_diff.diff_json
    conv_id: str = ""
    activity: list = field(default_factory=list)         # conv_store activity(tool:conv: 해석)
    call_ids: frozenset = frozenset()                    # rr_snapshot_calls.call_id
    brief_refs: frozenset = frozenset()                  # 이번 브리프에 실린 narr:·reg: id 집합
    brief_known: bool = False                            # False 면 narr:·reg: 는 미검증으로 둔다
    external_check: Callable[[str], Any] | None = None   # card:·rpt:·inc: 존재 확인(없으면 미검증)
    test_run_reports: frozenset = frozenset()            # RA test_run 문서인 rpt: id(측정 등급 조건)
    active_rules: frozenset = frozenset()
    corpus: dict = field(default_factory=dict)           # {'n': int, 'per_feature': {name: {'min':…, 'max':…}}}
    rollup_prefixes: dict = field(default_factory=dict)  # path_prefix -> asm_key
    seats: tuple = ()                                    # 이번 패널 착석 키
    versions: dict = field(default_factory=dict)         # taxonomy_version·rule_version·ir_version·diff_version·planner_version

    # ------------------------------------------------ 조회
    def field_evidence(self, kind: str, key: str, product_code: str | None = None) -> dict | None:
        """`voc:`·`paper:` 해석 — 이 타깃의 브리프가 **블록에 실은** 항목이어야 한다.

        정본이 두 갈래로 적은 것(§0.2.1 '브리프 E10 블록에 실린 것만' · §5.6.2 '원장에 남아 해석된다')은
        같은 뜻이다 — 브리프가 부른 원문 원장이 곧 실린 것의 목록이다(`rr_brief_calls`). 다만 '부른 것' 과
        '실린 것' 은 다르다. 원문에는 이슈가 수십 건 와도 블록은 상위 카테고리 3 + 문헌 2 만 싣는다.
        원문 전체를 근거로 삼으면 블록에 없던 이슈를 인용해도 측정 등급이 붙는다(이슈 키는 연번이라
        추측이 쉽다). 그래서 조립과 같은 선택 규칙(`brief.rendered_field_items`)을 통과한 항목만 인정한다.

        `voc:` 는 제품코드까지 대조한다 — 원장 행은 특정 `product_code` 로 부른 응답이므로, 코드가 다른
        인용을 통과시키면 남의 제품 필드 이력이 이 제품의 근거로 선다.
        행 수를 자르지 않는다 — `search_scholar` 의 질의문은 성격 태그·mechanism 이 쌓이면 바뀌어
        `args_hash` 마다 새 행이 생기고, 몇 행만 보면 **예전 패널의 `paper:` 인용이 뒤늦게 dangling** 이 된다.
        """
        return find_field_item(self.store, kind, key, product_code=product_code, target_key=self.target_key)

    def requirement(self, name: str) -> dict | None:
        """`req:<name>` 해석 — 이 과제의 rr_requirements 행. 좌석 계약(std)이 이 인용을 필수로 요구한다.

        정본은 범위를 못 박는다 — "`rr_requirements(project_id, status ∈ candidate|confirmed)` 에 있는지
        확인하고 없으면 `dangling=true` + 등급 강등"(§4.3.1 requirement_ref). `waived` 는 **과제가
        포기한 요구**라 인용 근거가 아니다. 걸러내지 않으면 포기한 한계를 인용해 등급이 측정으로 오른다.
        UNIQUE 가 `(project_id, kind, name)` 이라 같은 이름이 kind 마다 있을 수 있다 — 정렬 없이 한 행만
        집으면 어느 kind 가 잡히는지 비결정이고, `standard` 는 등급이 다르므로(§2.8b) 등급까지 흔들린다.
        """
        rows = self._rows(
            "SELECT id, name, kind, op, value_json, unit, status, source_ref FROM rr_requirements"
            " WHERE project_id = ? AND name = ? AND status IN ('candidate','confirmed')"
            " ORDER BY kind LIMIT 1", (self.project_id, name))
        return dict(rows[0]) if rows else None

    def _rows(self, sql: str, params: Sequence) -> list:
        if self.store is None:
            return []
        return self.store.query(sql, params)

    def _scope_ids(self) -> tuple[str, ...]:
        return tuple(sid for sid in self.snapshot_ids if sid)

    def node(self, nid: str) -> dict | None:
        """스코프 스냅샷의 IR 노드. 없으면 None."""
        bare = nid.split(":", 1)[-1]
        for sid in self._scope_ids():
            nodes = ((self.irs.get(sid) or {}).get("nodes")) or {}
            hit = nodes.get(nid) or nodes.get(bare)
            if isinstance(hit, dict):
                return hit
        for sid in self._scope_ids():
            rows = self._rows(
                "SELECT snapshot_id, nid, kind, source_kind, name, name_norm, ckey, dn, asm_key,"
                " material_norm, volume, attrs_json FROM rr_ir_nodes WHERE snapshot_id = ? AND nid IN (?, ?)",
                (sid, nid, bare),
            )
            if rows:
                return _row_to_node(rows[0])
        return None

    def edge(self, eid: str) -> dict | None:
        """스코프 스냅샷의 IR 엣지. 없으면 None."""
        bare = eid.split(":", 1)[-1]
        for sid in self._scope_ids():
            edges = ((self.irs.get(sid) or {}).get("edges")) or {}
            hit = edges.get(eid) or edges.get(bare)
            if isinstance(hit, dict):
                return hit
        for sid in self._scope_ids():
            rows = self._rows(
                "SELECT snapshot_id, eid, kind, kind_family, a, b, ck_a, ck_b, subject_key, status, attrs_json"
                " FROM rr_ir_edges WHERE snapshot_id = ? AND eid IN (?, ?)",
                (sid, eid, bare),
            )
            if rows:
                return _row_to_edge(rows[0])
        return None

    def nodes_by_name(self, name_norm: str) -> list[dict]:
        """name_norm 이 같은 스코프 노드 전부(다의 판정용)."""
        out: list[dict] = []
        seen: set[str] = set()
        for sid in self._scope_ids():
            nodes = ((self.irs.get(sid) or {}).get("nodes")) or {}
            for nid, node in nodes.items():
                if isinstance(node, dict) and str(node.get("name_norm") or "") == name_norm:
                    key = str(node.get("ckey") or node.get("dn") or nid)
                    if key not in seen:
                        seen.add(key)
                        out.append({**node, "nid": node.get("nid") or nid})
            rows = self._rows(
                "SELECT snapshot_id, nid, kind, source_kind, name, name_norm, ckey, dn, asm_key,"
                " material_norm, volume, attrs_json FROM rr_ir_nodes WHERE snapshot_id = ? AND name_norm = ?",
                (sid, name_norm),
            )
            for row in rows:
                node = _row_to_node(row)
                key = str(node.get("ckey") or node.get("dn") or node.get("nid"))
                if key not in seen:
                    seen.add(key)
                    out.append(node)
        return out

    def edge_between(self, nid_a: str, nid_b: str) -> dict | None:
        """두 노드를 잇는 스코프 엣지(정렬 무관)."""
        pair = {nid_a, nid_b}
        for sid in self._scope_ids():
            edges = ((self.irs.get(sid) or {}).get("edges")) or {}
            for eid, edge in edges.items():
                if isinstance(edge, dict) and {edge.get("a"), edge.get("b")} == pair:
                    return {**edge, "eid": edge.get("eid") or eid}
            rows = self._rows(
                "SELECT snapshot_id, eid, kind, kind_family, a, b, ck_a, ck_b, subject_key, status, attrs_json"
                " FROM rr_ir_edges WHERE snapshot_id = ? AND ((a = ? AND b = ?) OR (a = ? AND b = ?))",
                (sid, nid_a, nid_b, nid_b, nid_a),
            )
            if rows:
                return _row_to_edge(rows[0])
        return None

    def diff_item(self, cid: str) -> dict | None:
        """rr_diff 의 어느 층에든 있는 cid 항목."""
        diff = self.diff or {}
        for bucket in (diff.get("structural") or {}).values():
            for item in bucket if isinstance(bucket, list) else ():
                if isinstance(item, dict) and item.get("cid") == cid:
                    return item
        for bucket in (diff.get("parametric") or {}).values():
            for item in bucket if isinstance(bucket, list) else ():
                if isinstance(item, dict) and item.get("cid") == cid:
                    return item
        for item in (diff.get("semantic") or {}).get("events") or ():
            if isinstance(item, dict) and item.get("cid") == cid:
                return item
        if self.store is not None and self.diff_id:
            rows = self._rows(
                "SELECT diff_id, cid, layer, code, change_kind, subject_key, ckeys_json, magnitude, unit, rel,"
                " confidence, design_relevant, unconfirmed, excluded_reason, text"
                " FROM rr_diff_events WHERE diff_id = ? AND cid = ?",
                (self.diff_id, cid),
            )
            if rows:
                return dict(rows[0])
        return None

    def dim(self, name: str) -> dict | None:
        """명명 치수 — IR dims_named 또는 diff dims_delta."""
        for sid in self._scope_ids():
            dims = ((self.irs.get(sid) or {}).get("dims_named")) or {}
            if name in dims:
                entry = dims[name]
                return entry if isinstance(entry, dict) else {"value": entry, "name": name}
        for item in ((self.diff or {}).get("parametric") or {}).get("dims_delta") or ():
            if isinstance(item, dict) and item.get("name") == name:
                return item
        return None

    def signal(self, key: str) -> dict | None:
        for state in self.states.values():
            signal = (state.get("signals") or {}).get(key)
            if isinstance(signal, dict):
                return signal
        return None

    def gate(self, name: str) -> dict | None:
        for state in self.states.values():
            gate = (state.get("gates") or {}).get(name)
            if isinstance(gate, dict):
                return gate
        g7 = ((self.diff or {}).get("comparability") or {}).get("G7")
        if name == "G7" and isinstance(g7, dict):
            return g7
        return None

    def rule(self, rule_id: str) -> dict | None:
        for state in self.states.values():
            for hit in state.get("rule_hits") or ():
                if isinstance(hit, dict) and hit.get("rule") == rule_id:
                    return hit
        return {"rule": rule_id} if rule_id in self.active_rules else None

    def warning(self, code: str, ref_to: str | None) -> dict | None:
        for sid in self._scope_ids():
            for item in ((self.irs.get(sid) or {}).get("warnings")) or ():
                if not isinstance(item, dict) or item.get("code") != code:
                    continue
                if ref_to and str(item.get("ref") or item.get("ref_to") or "") != ref_to:
                    continue
                return item
        return None

    def activity_item(self, idx: int) -> dict | None:
        if 0 <= idx < len(self.activity):
            item = self.activity[idx]
            return item if isinstance(item, dict) else {"result_preview": str(item)}
        return None


def _row_to_node(row: Any) -> dict:
    node = dict(row)
    attrs = node.pop("attrs_json", None)
    if attrs:
        try:
            node.update(json.loads(attrs))
        except (TypeError, json.JSONDecodeError):
            pass
    return node


def _row_to_edge(row: Any) -> dict:
    edge = dict(row)
    attrs = edge.pop("attrs_json", None)
    if attrs:
        try:
            edge.update(json.loads(attrs))
        except (TypeError, json.JSONDecodeError):
            pass
    return edge


def name_norm(text: Any) -> str:
    """이름 정규화. ir_builder 구현이 있으면 그것을 쓰고 없으면 대문자·영숫자 폴백을 쓴다."""
    try:
        from app import ir_builder  # 지연 임포트 — 빌더 간 순환을 만들지 않는다.

        fn = getattr(ir_builder, "name_norm", None)
        if callable(fn):
            return str(fn(text))
    except ImportError:
        pass
    s = str(text or "").strip().upper()
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    return s.strip("_")


# ================================================================ §4.4 cites — 존재 검증·quote 대조·근거 등급
def find_field_item(store, kind: str, key: str, *, product_code: str | None = None,
                    target_key: str | None = None, owner_sub: str | None = None) -> dict | None:
    """`voc:`·`paper:` 한 건을 `rr_brief_calls` 원장에서 찾는다(§5.6.2).

    `SpecContext.field_evidence`(타깃 스코프)와 `GET /api/refs/{ref}`(소유자 스코프)가 **같은 규칙**을
    쓰게 하려고 모듈 함수로 둔다 — 두 곳이 갈리면 인용은 해석되는데 REST 는 404 가 되거나 그 반대가 된다.
    """
    import gzip  # noqa: PLC0415 — 이 경로에서만 쓴다.

    from app import brief as brief_module  # noqa: PLC0415 — 순환 import 회피(brief 는 narrative 를 쓴다).

    if store is None:
        return None
    tool = "get_top_issues" if kind == "voc" else "search_scholar"
    where = ["tool = ?", "ok = 1"]
    params: list = [tool]
    if target_key is not None:
        where.insert(0, "target_key = ?")
        params.insert(0, target_key)
    if owner_sub is not None:
        where.append("owner_sub = ?")
        params.append(owner_sub)
    rows = store.query(
        f"SELECT result_gz, args_json FROM rr_brief_calls WHERE {' AND '.join(where)}"
        " ORDER BY fetched_at DESC", tuple(params))
    wanted = ("issue_key",) if kind == "voc" else ("record_id", "doi")
    for row in rows:
        if product_code is not None:
            args = json.loads(row["args_json"]) if row["args_json"] else {}
            if str((args or {}).get("product_code") or "") != product_code:
                continue
        try:
            payload = json.loads(gzip.decompress(row["result_gz"]).decode("utf-8"))
        except (OSError, TypeError, ValueError):
            continue
        for item in brief_module.rendered_field_items(payload, kind):
            if any(str(item.get(w) or "") == key for w in wanted):
                return dict(item)
    return None


def canonical_text_for(ref: str, ctx: SpecContext) -> str | None:
    """참조 하나의 정규 표기(§3.4.1). 만들 수 없으면 None 이고 quote 대조 (2) 는 건너뛴다."""
    info = parse_ref(ref)
    if info is None:
        return None
    kind = info["kind"]
    if kind == "c":
        item = ctx.diff_item(info["ref"]) or ctx.diff_item(info["id"])
        if item is None:
            return None
        return render.event_text(item) if item.get("code") else render.param_text(item)
    if kind == "sig":
        signal = ctx.signal(info["key"])
        return render.signal_text(info["key"], signal) if signal is not None else None
    if kind == "d":
        entry = ctx.dim(info["name"])
        if entry is None:
            return None
        text = entry.get("text")
        if isinstance(text, str) and text:
            return text
        if "before" in entry or "after" in entry:
            return f"{info['name']} " + render.fmt_change(entry.get("before"), entry.get("after"), entry.get("unit") or "mm")
        return f"{info['name']}={render.fmt_value(entry.get('value'), entry.get('unit') or 'mm')}"
    if kind in ("p", "e"):
        obj = ctx.node(info["ref"]) if kind == "p" else ctx.edge(info["ref"])
        if obj is None:
            return None
        text = obj.get("text")
        return text if isinstance(text, str) and text else None
    if kind == "rule":
        hit = ctx.rule(info["rule_id"])
        if hit is None:
            return None
        return (hit.get("found") or {}).get("text")
    if kind == "gate":
        gate = ctx.gate(info["gate"])
        if gate is None:
            return None
        return f"{info['gate']} {'pass' if gate.get('pass') else 'fail'}({gate.get('count', 0)})"
    if kind == "warn":
        item = ctx.warning(info["code"], info.get("ref_to"))
        if item is None:
            return None
        message = item.get("message")
        return render.quote_source(message) if message else info["code"]
    if kind == "tool" and "conv_id" in info:
        item = ctx.activity_item(int(info["idx"]))
        if item is None:
            return None
        preview = item.get("result_preview")
        return str(preview) if preview is not None else None
    if kind in ("voc", "paper"):
        # 좌석이 읽은 것은 E10 줄 그 자체다 — 조립과 같은 함수로 줄을 만들어 대조한다. 분기가 없으면
        # quote 대조가 건너뛰어지고, **아무도 대조할 수 없는 외부 근거**라 지어낸 인용문이 가장 잘
        # 먹히는 자리가 된다(VOC 원문은 사람이 눈으로 확인할 방법이 없다).
        from app import brief as brief_module  # noqa: PLC0415 — 순환 import 회피(brief 는 narrative 를 쓴다).

        if kind == "voc":
            item = ctx.field_evidence("voc", info["issue_key"], info["product_code"])
            return (brief_module.field_evidence_line(item, "voc", product_code=info["product_code"])
                    if item is not None else None)
        item = ctx.field_evidence("paper", info["paper_id"])
        return brief_module.field_evidence_line(item, "paper") if item is not None else None
    if kind == "req":
        # 요구의 한계값이 정규 표기다 — 좌석이 `req:` 를 인용하며 한계를 다르게 적는 것을 잡는다
        # (§4.4.2 가 존재하는 이유가 그 실패다). `standard` 는 한계가 없어 조항·제목이 표기다(§2.8b).
        row = ctx.requirement(info["name"])
        if row is None:
            return None
        try:
            value = json.loads(row["value_json"]) if row.get("value_json") else None
        except (TypeError, ValueError):
            value = None
        if str(row.get("kind") or "") == "standard":
            meta = value if isinstance(value, Mapping) else {}
            parts = [info["name"], str(meta.get("clause") or ""), str(meta.get("title") or "")]
            return " ".join(p for p in parts if p)
        if row.get("op") is None:
            return f"{info['name']} {canonical_json(value)}"
        return f"{info['name']} {row['op']} {canonical_json(value)} {row.get('unit') or ''}".strip()
    return None


# 심의 엔진의 근거 항목 표지 — `[e:N]`, 호출자 키가 가면 `[e:N|E3]`(엔진 `_EV_CITE_RE` 와 같은 모양이고, 대괄호는
# JSON 필드 안에서 빠질 수 있다). §0.2.1 의 참조가 아니다 — IR 엣지는 `e:<12hex>` 라 `parse_ref` 가 먼저 가른다.
_ENGINE_MARKER_RE = re.compile(r"^\[?e:\d+(?:\|[A-Za-z0-9_.-]{1,24})?\]?$")
ENGINE_MARKER = "engine_marker"


def _resolve_one(ref: str, ctx: SpecContext, raised_by: Sequence[str]) -> dict:
    """참조 하나의 존재 검증. {ok, reason, payload, verified}. verified=False 는 채널 부재(강등 아님)."""
    info = parse_ref(ref)
    if info is None:
        reason = ENGINE_MARKER if _ENGINE_MARKER_RE.match(ref) else "malformed"
        return {"ok": False, "reason": reason, "payload": None, "verified": True}
    kind = info["kind"]
    if kind == "p":
        node = ctx.node(info["ref"])
        return {"ok": node is not None, "reason": None if node else "not_in_scope", "payload": node, "verified": True}
    if kind == "e":
        edge = ctx.edge(info["ref"])
        return {"ok": edge is not None, "reason": None if edge else "not_in_scope", "payload": edge, "verified": True}
    if kind == "c":
        item = ctx.diff_item(info["ref"]) or ctx.diff_item(info["id"])
        return {"ok": item is not None, "reason": None if item else "not_in_scope", "payload": item, "verified": True}
    if kind == "d":
        entry = ctx.dim(info["name"])
        return {"ok": entry is not None, "reason": None if entry else "not_in_scope", "payload": entry, "verified": True}
    if kind == "sig":
        signal = ctx.signal(info["key"])
        return {"ok": signal is not None, "reason": None if signal else "not_in_scope", "payload": signal, "verified": True}
    if kind == "gate":
        gate = ctx.gate(info["gate"])
        return {"ok": gate is not None, "reason": None if gate else "not_in_scope", "payload": gate, "verified": True}
    if kind == "rule":
        hit = ctx.rule(info["rule_id"])
        return {"ok": hit is not None, "reason": None if hit else "not_in_scope", "payload": hit, "verified": True}
    if kind == "req":
        row = ctx.requirement(info["name"])
        return {"ok": row is not None, "reason": None if row else "not_in_scope", "payload": row, "verified": True}
    if kind in ("voc", "paper"):
        item = (ctx.field_evidence("voc", info["issue_key"], info["product_code"]) if kind == "voc"
                else ctx.field_evidence("paper", info["paper_id"]))
        return {"ok": item is not None, "reason": None if item else "not_in_scope",
                "payload": item, "verified": True}
    if kind == "warn":
        item = ctx.warning(info["code"], info.get("ref_to"))
        return {"ok": item is not None, "reason": None if item else "not_in_scope", "payload": item, "verified": True}
    if kind == "name":
        return _resolve_name(info, ctx)
    if kind == "tool":
        if "conv_id" in info:
            item = ctx.activity_item(int(info["idx"]))
            if item is None:
                return {"ok": False, "reason": "activity_missing", "payload": None, "verified": bool(ctx.activity)}
            persona = str(item.get("persona") or item.get("agent_key") or "")
            if persona and raised_by and persona not in raised_by:
                return {"ok": False, "reason": "persona_mismatch", "payload": item, "verified": True}
            return {"ok": True, "reason": None, "payload": item, "verified": True}
        known = bool(ctx.call_ids)
        return {"ok": info["call_id"] in ctx.call_ids, "reason": None if info["call_id"] in ctx.call_ids else "not_in_scope",
                "payload": None, "verified": known}
    if kind in ("narr", "reg"):
        if not ctx.brief_known:
            return {"ok": True, "reason": None, "payload": None, "verified": False}
        present = info["ref"] in ctx.brief_refs
        return {"ok": present, "reason": None if present else "not_in_brief", "payload": None, "verified": True}
    if kind in ("card", "rpt", "inc"):
        if ctx.external_check is None:
            return {"ok": True, "reason": None, "payload": None, "verified": False}
        present = ctx.external_check(info["ref"])
        if present is None:
            return {"ok": True, "reason": None, "payload": None, "verified": False}
        return {"ok": bool(present), "reason": None if present else "not_found", "payload": None, "verified": True}
    return {"ok": False, "reason": "unknown_scheme", "payload": None, "verified": True}


def _resolve_name(info: dict, ctx: SpecContext) -> dict:
    """name:A|B → name_norm 으로 nid 쌍 → eid. 어느 쪽이든 다의면 dangling(name_ambiguous)."""
    nodes_a = ctx.nodes_by_name(name_norm(info["a"]))
    nodes_b = ctx.nodes_by_name(name_norm(info["b"]))
    if not nodes_a or not nodes_b:
        return {"ok": False, "reason": "not_in_scope", "payload": None, "verified": True}
    if len(nodes_a) > 1 or len(nodes_b) > 1:
        return {"ok": False, "reason": "name_ambiguous", "payload": None, "verified": True}
    edge = ctx.edge_between(str(nodes_a[0].get("nid") or ""), str(nodes_b[0].get("nid") or ""))
    if edge is None:
        return {"ok": False, "reason": "not_in_scope", "payload": None, "verified": True}
    return {"ok": True, "reason": None, "payload": edge, "verified": True, "resolved": edge.get("eid")}


def _number_tokens(text: str) -> list[str]:
    masked = render.mask_neutral(text or "")
    return [m.group(1) for m in _NUMBER_TOKEN_RE.finditer(masked)]


def resolve_cites(cites: Sequence[dict], ctx: SpecContext, *, claim: str = "", warrant: str = "",
                  raised_by: Sequence[str] = ()) -> dict:
    """cites 를 존재 검증(§4.4.1)·quote 대조(§4.4.2)한다. 버리지 않고 플래그로 보존한다."""
    rows: list[dict] = []
    dangling: list[str] = []
    quote_mismatch: list[str] = []
    unverified: list[str] = []
    grade_refs: list[str] = []
    resolved_refs: list[str] = []

    for cite in cites or ():
        if not isinstance(cite, dict):
            continue
        raw = str(cite.get("ref") or "").strip()
        info = parse_ref(raw)
        ref = info["ref"] if info else raw
        quote = str(cite.get("quote") or "")
        outcome = _resolve_one(ref, ctx, raised_by)
        row = {
            "ref": ref,
            "quote": quote,
            "ref_type": info["kind"] if info else "unknown",
            "ok": bool(outcome["ok"]),
            "dangling_reason": outcome["reason"],
            "verified": bool(outcome["verified"]),
            "quote_mismatch": False,
            "grade_ok": False,
            "canonical": None,
        }
        # `req:` 는 kind 마다 등급이 다르다(§2.8b — standard 만 문헌·규격). 등급 함수가 payload 를
        # 받지 않으므로 필요한 한 칸만 행에 싣는다.
        if info and info["kind"] == "req" and isinstance(outcome.get("payload"), Mapping):
            row["req_kind"] = str(outcome["payload"].get("kind") or "")
        if not outcome["ok"]:
            # 엔진의 근거 표지는 dangling 으로 세지 않는다. dangling 은 '실재하지 않는 것을 가리켰다' 는 표시인데
            # (§0.2.1 (2)) 표지는 엔진이 브리프 항목에 붙이고 결정문에 적으라고 시킨 번호다 — 세면 그 지시를 따른
            # 패널마다 dangling 이 오르고 진짜 지어낸 참조가 그 속에 묻힌다. 참조가 아니므로 등급에도 세지 않는다
            # (아래 grade_ok 는 그대로 False 다).
            if outcome["reason"] != ENGINE_MARKER:
                dangling.append(ref)
        else:
            if not outcome["verified"]:
                unverified.append(ref)
            resolved_refs.append(str(outcome.get("resolved") or ref))
            canonical = canonical_text_for(ref, ctx)
            row["canonical"] = canonical
            if canonical is not None and quote and quote not in canonical:
                row["quote_mismatch"] = True
                quote_mismatch.append(ref)
            else:
                row["grade_ok"] = True
                grade_refs.append(ref)
        row["payload"] = outcome.get("payload")
        rows.append(row)

    # (1) claim·warrant 의 수치 토큰이 quote 안에 문자 그대로 있어야 한다.
    quotes = " ".join(row["quote"] for row in rows)
    unquoted = sorted({token for token in _number_tokens(f"{claim} {warrant}") if token not in quotes})
    if unquoted and rows:
        for row in rows:
            if row["ok"] and not row["quote_mismatch"]:
                row["quote_mismatch"] = True
                quote_mismatch.append(row["ref"])

    return {
        "cites": rows,
        "dangling": sorted(set(dangling)),
        "quote_mismatch": sorted(set(quote_mismatch)),
        "unverified": sorted(set(unverified)),
        "unquoted_numbers": unquoted,
        "grade_refs": grade_refs,
        "resolved_refs": resolved_refs,
    }


def evidence_grade_from_cites(resolved: dict, ctx: SpecContext | None = None) -> str:
    """§4.4.3 표 — dangling·quote_mismatch 가 아닌 cites 만 세어 등급을 판정한다."""
    kinds: list[tuple[str, str]] = []
    # `req:` 중 kind='standard' 는 측정이 아니다 — 정본 §2.8b 는 "`standard` kind 만 예외이며 등급은
    # 측정이 아니라 문헌·규격, `source_ref` 종류를 따른다" 고 적는다. 규격 번호를 인용한 것은 실측이
    # 아니라 문헌이다. 이 예외가 없으면 요구 행 하나만 등록돼 있어도 전 클러스터가 측정으로 오른다.
    standards: list[str] = []
    for row in resolved.get("cites") or ():
        if not row.get("ok") or not row.get("grade_ok"):
            continue
        if str(row.get("ref_type")) == "req" and str(row.get("req_kind") or "") == "standard":
            standards.append(str(row.get("ref")))
            continue
        kinds.append((str(row.get("ref_type")), str(row.get("ref"))))
    test_runs = ctx.test_run_reports if ctx else frozenset()
    for ref_type, ref in kinds:
        if ref_type in ("inc", "req", "voc"):
            return "측정"
        if ref_type == "rpt" and ref.split(":", 1)[-1] in test_runs:
            return "측정"
    if standards or any(ref_type in ("card", "paper") for ref_type, _ in kinds):
        return "문헌·규격"
    if any(ref_type in ("tool", "sig", "c", "e", "p", "d", "rule", "rpt", "narr", "reg", "gate", "warn", "name")
           for ref_type, _ in kinds):
        return "도구예측"
    return "경험칙"


def feature_snapshot_from_cites(resolved: dict) -> dict:
    """§4.3.4 — cites 가 가리키는 원천 값을 {ref: {attr: value}} 로 동결한다(ref 당 12 · finding 당 40)."""
    out: dict[str, dict] = {}
    total = 0
    for row in resolved.get("cites") or ():
        if not row.get("ok"):
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        copied: dict[str, Any] = {}
        for key in sorted(payload):
            if total >= FEATURE_SNAPSHOT_PER_FINDING or len(copied) >= FEATURE_SNAPSHOT_PER_REF:
                break
            value = payload[key]
            if isinstance(value, bool) or not isinstance(value, (int, float, str)) or value is None:
                continue
            if key in ("attrs_json", "ckeys_json", "text"):
                continue
            copied[key] = value
            total += 1
        if copied:
            out[row["ref"]] = copied
    return out


def precedent_from_snapshot(feature_snapshot: dict, ctx: SpecContext) -> tuple[str, int]:
    """§4.3.3 — feature_vector 22차원과 대응하는 값을 코퍼스 [min, max] 와 대조한다."""
    corpus = ctx.corpus or {}
    corpus_n = int(corpus.get("n") or 0)
    per_feature = corpus.get("per_feature") or {}
    if corpus_n < 5 or not per_feature:
        return "none", corpus_n
    compared = False
    for attrs in feature_snapshot.values():
        for attr, value in attrs.items():
            # 표에 없으면 attr 이름 그대로 코퍼스에 있는지 본다 — 예측 도구 결과의 자리다(§7.6).
            feature = _FEATURE_OF_ATTR.get(attr, attr)
            if feature not in per_feature:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            bounds = per_feature[feature] or {}
            low, high = bounds.get("min"), bounds.get("max")
            if low is None or high is None:
                continue
            compared = True
            if value < low or value > high:
                return "out_of_range", corpus_n
    return ("in_range" if compared else "none"), corpus_n


# ================================================================ §4.3.2 subject_key · cluster_key
def _iface_alias(ckeys: Sequence[str], ctx: SpecContext) -> tuple[str, str] | None:
    """rr_iface_alias 에 별칭이 있으면 정규 쌍을 돌려준다."""
    if ctx.store is None or len(ckeys) != 2:
        return None
    alias_key = "|".join(sorted(ckeys))
    rows = ctx.store.query(
        "SELECT alias_key, canonical_a, canonical_b FROM rr_iface_alias WHERE alias_key = ?", (alias_key,)
    )
    if not rows:
        return None
    row = rows[0]
    return str(row["canonical_a"]), str(row["canonical_b"])


def _dim_canonical_name(name: str, ctx: SpecContext) -> str:
    """rr_dim_vocab 정규명으로 접는다(동의어 사전에 있으면). 없으면 원문."""
    if ctx.store is None:
        return name
    rows = ctx.store.query("SELECT name, synonyms_json FROM rr_dim_vocab", ())
    for row in rows:
        if str(row["name"]) == name:
            return name
        try:
            synonyms = json.loads(row["synonyms_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            synonyms = []
        if name in synonyms:
            return str(row["name"])
    return name


def resolve_subject(subject: dict, ctx: SpecContext) -> dict:
    """§4.2.2 4단계·§4.3.2 — names → ckey/asm_key 해석 후 subject_key 산출."""
    subject = dict(subject or {})
    names = [str(n) for n in (subject.get("names") or []) if str(n)]
    ckeys = [str(c) for c in (subject.get("ckeys") or []) if str(c)]
    asm_key = subject.get("asm_key")
    warnings: list[str] = []

    # 의장이 명명 치수·서브어셈블리를 names 에 접두로 쓴 경우.
    if len(names) == 1 and names[0].startswith("dim:"):
        name = _dim_canonical_name(names[0][4:], ctx)
        return {"ckeys": [], "names": [f"dim:{name}"], "asm_key": None,
                "subject_key": f"dim:{name}", "unresolved": False, "warnings": warnings}
    if len(names) == 1 and names[0].startswith("asm:"):
        asm_key = names[0][4:]
    if asm_key:
        known = not ctx.rollup_prefixes or asm_key in set(ctx.rollup_prefixes.values())
        if not known:
            warnings.append(f"asm_key 가 rollups 에 없다 — {asm_key}")
            return {"ckeys": [], "names": names, "asm_key": None, "subject_key": "",
                    "unresolved": True, "warnings": warnings}
        return {"ckeys": [], "names": names, "asm_key": asm_key, "subject_key": f"asm:{asm_key}",
                "unresolved": False, "warnings": warnings}

    # ckey 를 직접 쓴 경우는 존재 검증만 한다.
    if ckeys:
        missing = [ck for ck in ckeys if not _ckey_exists(ck, ctx)]
        if missing:
            warnings.append("스코프에 없는 ckey — " + ", ".join(missing))
    else:
        for name in names[:2]:
            hits = ctx.nodes_by_name(name_norm(name))
            distinct = sorted({str(h.get("ckey")) for h in hits if h.get("ckey")})
            if len(distinct) == 1:
                ckeys.append(distinct[0])
            elif len(distinct) > 1:
                warnings.append(f"이름이 다의라 미해석 — {name}")

    if len(ckeys) == 2:
        alias = _iface_alias(ckeys, ctx)
        pair = sorted(alias) if alias else sorted(ckeys)
        return {"ckeys": pair, "names": names, "asm_key": None, "subject_key": "|".join(pair),
                "unresolved": False, "warnings": warnings}
    if len(ckeys) == 1:
        return {"ckeys": ckeys, "names": names, "asm_key": None, "subject_key": ckeys[0],
                "unresolved": False, "warnings": warnings}

    # 파트로 풀리지 않은 이름 1개는 서브어셈블리 경로와 대조한다(§4.2.2 4).
    if len(names) == 1 and ctx.rollup_prefixes:
        normalized = name_norm(names[0])
        for prefix, key in ctx.rollup_prefixes.items():
            if name_norm(prefix) == normalized:
                return {"ckeys": [], "names": names, "asm_key": key, "subject_key": f"asm:{key}",
                        "unresolved": False, "warnings": warnings}
    return {"ckeys": ckeys, "names": names, "asm_key": None, "subject_key": "",
            "unresolved": True, "warnings": warnings}


def _ckey_exists(ckey: str, ctx: SpecContext) -> bool:
    for sid in ctx.snapshot_ids:
        nodes = ((ctx.irs.get(sid) or {}).get("nodes")) or {}
        if any(isinstance(n, dict) and n.get("ckey") == ckey for n in nodes.values()):
            return True
    if ctx.store is None:
        return True  # 스코프를 못 보면 존재 검증을 하지 않는다(강등도 하지 않는다).
    for sid in ctx.snapshot_ids:
        if ctx.store.query_one(
            "SELECT nid FROM rr_ir_nodes WHERE snapshot_id = ? AND ckey = ? LIMIT 1", (sid, ckey)
        ):
            return True
    return False


def cluster_key_of(mechanism: str, mechanism_detail: str, subject_key: str, change_kind: str) -> str:
    """§4.3.2 — sha1(mechanism|mechanism_detail|subject_key|change_kind)[:12]. 도메인·좌석·ir_refs 는 넣지 않는다."""
    payload = f"{mechanism}|{mechanism_detail}|{subject_key}|{change_kind}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


# ================================================================ §4.2.2 정규화
def _fix_enum(value: Any, name: str, path: str, invalid: list[dict]) -> Any:
    allowed = _ENUMS[name]
    if isinstance(value, str) and value in allowed:
        return value
    invalid.append({"path": path, "field": name, "value": value})
    default = _enum_default(name)
    return default if default in allowed else allowed[-1]


def _normalize_mechanism(finding: dict, path: str, warnings: list[str], curation: list[dict]) -> None:
    """§4.2.2 2단계 — 택소노미 동의어 사전으로 mechanism·mechanism_detail 을 정규화한다."""
    by_code, alias = _mechanism_index()
    mechanism = str(finding.get("mechanism") or "")
    detail = str(finding.get("mechanism_detail") or "")
    candidates = [f"{mechanism}.{detail}", detail, mechanism, str(finding.get("mechanism_free") or "")]
    for candidate in candidates:
        if not candidate:
            continue
        code = alias.get(candidate)
        if code and code in by_code:
            finding["mechanism"] = str(by_code[code].get("mechanism") or code.split(".", 1)[0])
            finding["mechanism_detail"] = str(by_code[code].get("detail") or code.split(".", 1)[-1])
            return
    original = f"{mechanism}.{detail}".strip(".")
    finding["mechanism"] = mechanism if mechanism in {"thermal", "mechanical", "interface", "electrical", "material", "process"} else "process"
    finding["mechanism_detail"] = "unclassified"
    finding["mechanism_free"] = original
    warnings.append(f"{path}: 택소노미에 없는 메커니즘 — {original}")
    curation.append({"kind": "unclassified_code", "payload": {"axis": "mechanism", "value": original, "path": path}})


def _normalize_finding(finding: dict, path: str, ctx: SpecContext, *, is_gain: bool,
                       invalid: list[dict], warnings: list[str], curation: list[dict]) -> dict:
    finding = dict(finding)
    finding["direction"] = "improvement" if is_gain else _fix_enum(finding.get("direction"), "direction", path, invalid)
    if is_gain and finding.get("direction") != "improvement":
        warnings.append(f"{path}: gains 는 direction=improvement 로 보정했다.")

    _normalize_mechanism(finding, path, warnings, curation)

    change_kind = str(finding.get("change_kind") or "")
    if change_kind not in _CHANGE_KINDS:
        invalid.append({"path": path, "field": "change_kind", "value": finding.get("change_kind")})
        finding["change_kind"] = "none"
    trigger = str(finding.get("trigger_condition") or "")
    if not _TRIGGER_RE.match(trigger):
        _, alias = _mechanism_index()
        invalid.append({"path": path, "field": "trigger_condition", "value": finding.get("trigger_condition")})
        finding["trigger_condition"] = "none"
        if trigger:
            finding["trigger_text"] = str(finding.get("trigger_text") or trigger)[:120]

    # 3. severity ↔ judgement 정합.
    finding["severity"] = _fix_enum(finding.get("severity"), "severity", path, invalid)
    finding["judgement"] = _fix_enum(finding.get("judgement"), "judgement", path, invalid)
    allowed = _SEV_JUDGEMENT[finding["severity"]]
    if finding["judgement"] not in allowed and finding["judgement"] != "undetermined":
        warnings.append(f"{path}: severity={finding['severity']} 와 judgement={finding['judgement']} 조합을 보정했다.")
        finding["judgement"] = _SEV_DEFAULT_JUDGEMENT[finding["severity"]]
    finding["sev3"] = _SEV3[finding["severity"]]

    detectability = dict(finding.get("detectability") or {})
    detectability["level"] = _fix_enum(detectability.get("level"), "detectability.level", f"{path}/detectability", invalid)
    detectability["tool"] = str(detectability.get("tool") or "")
    if detectability["level"] == "sim-detectable" and not detectability["tool"]:
        warnings.append(f"{path}: sim-detectable 인데 tool 이 없어 unknown 으로 보정했다.")
        detectability["level"] = "unknown"
    finding["detectability"] = detectability
    # 저장 시 status 는 open 이 정본이다 — 단 하나, 패널에서 기각된 원자는 그 사실을 보존한다(plan §4.7.1).
    finding["status"] = "rejected_in_panel" if str(finding.get("status") or "").strip() == "rejected_in_panel" else "open"

    # 4·5. subject 해석과 subject_key.
    subject = resolve_subject(finding.get("subject") or {}, ctx)
    warnings.extend(f"{path}: {w}" for w in subject["warnings"])
    finding["subject"] = {"ckeys": subject["ckeys"], "names": subject["names"], "asm_key": subject["asm_key"]}
    finding["subject_key"] = subject["subject_key"]
    finding["subject_unresolved"] = subject["unresolved"]

    # 6. cites 검증.
    raised_by = [str(k) for k in (finding.get("raised_by") or []) if str(k)]
    resolved = resolve_cites(finding.get("cites") or (), ctx, claim=str(finding.get("claim") or ""),
                             warrant=str(finding.get("warrant") or ""), raised_by=raised_by)
    finding["dangling"] = resolved["dangling"]
    finding["quote_mismatch"] = resolved["quote_mismatch"]
    finding["unverified_refs"] = resolved["unverified"]
    finding["unquoted_numbers"] = resolved["unquoted_numbers"]

    claimed = _fix_enum(finding.get("evidence_grade"), "evidence_grade", path, invalid)
    computed = evidence_grade_from_cites(resolved, ctx)
    finding["evidence_grade_claimed"] = claimed
    finding["evidence_grade"] = computed if _GRADE_RANK[claimed] > _GRADE_RANK[computed] else claimed

    # 7·8. precedent 와 feature_snapshot.
    finding["feature_snapshot"] = feature_snapshot_from_cites(resolved)
    precedent, corpus_n = precedent_from_snapshot(finding["feature_snapshot"], ctx)
    finding["precedent"] = precedent
    finding["precedent_corpus_n"] = corpus_n

    finding["tool_call_refs"] = _resolve_tool_calls(finding.get("tool_calls") or (), raised_by, ctx)
    finding["cluster_key"] = cluster_key_of(
        finding["mechanism"], finding["mechanism_detail"], finding["subject_key"], finding["change_kind"]
    )
    if raised_by:
        expected = _dom_of(raised_by[0])
        if expected and finding.get("domain") and expected not in (finding["domain"], "delib", "chair"):
            warnings.append(f"{path}: domain={finding.get('domain')} 이 raised_by 접두({expected})와 다르다.")
    if ctx.seats:
        outsiders = [k for k in raised_by if k not in ctx.seats and k != "chair"]
        if outsiders:
            warnings.append(f"{path}: 착석 집합 밖 좌석 — {', '.join(outsiders)}; 첫 키만 인정한다.")
    finding["_resolved_cites"] = resolved["cites"]
    finding["taxonomy_version"] = ctx.versions.get("taxonomy_version") or _taxonomy().get("taxonomy_version")
    for key in ("rule_version", "ir_version", "diff_version", "planner_version"):
        if ctx.versions.get(key):
            finding[key] = ctx.versions[key]
    return finding


def _resolve_tool_calls(tool_calls: Sequence[str], raised_by: Sequence[str], ctx: SpecContext) -> list[str]:
    """의장이 적은 도구명을 activity 인덱스로 대응해 tool:conv:<conv_id>#<idx> 를 만든다(대응 실패는 버린다)."""
    if not ctx.activity or not ctx.conv_id:
        return []
    used: set[int] = set()
    out: list[str] = []
    for entry in tool_calls:
        tool = str(entry or "").split("(", 1)[0].strip()
        if not tool:
            continue
        for idx, item in enumerate(ctx.activity):
            if idx in used or not isinstance(item, dict):
                continue
            if str(item.get("tool") or "") != tool:
                continue
            persona = str(item.get("persona") or item.get("agent_key") or "")
            if persona and raised_by and persona not in raised_by:
                continue
            used.add(idx)
            out.append(f"tool:conv:{ctx.conv_id}#{idx}")
            break
    return out


def _normalize_character(character: dict, spec: dict, ctx: SpecContext, *,
                         invalid: list[dict], warnings: list[str], curation: list[dict]) -> dict:
    """§4.6 — facet 8종 보충·태그 보정·na_reason 자동 부여."""
    character = dict(character or {})
    character["one_liner"] = str(character.get("one_liner") or "")[:140]
    given = {}
    for facet in character.get("facets") or ():
        if isinstance(facet, dict) and facet.get("facet") in FACETS:
            given[str(facet["facet"])] = dict(facet)

    findings_cids = _cite_refs_of(spec.get("findings") or ())
    gains_cids = _cite_refs_of(spec.get("gains") or ())
    corpus_n = int((ctx.corpus or {}).get("n") or 0)
    ecad_absent = any((state.get("missing") or {}).get("ecad_absent") for state in ctx.states.values())

    facets: list[dict] = []
    for name in FACETS:
        facet = given.get(name) or {"facet": name, "statements": [], "na_reason": None}
        facet["facet"] = name
        statements = []
        for index, statement in enumerate(facet.get("statements") or ()):
            if not isinstance(statement, dict):
                continue
            statements.append(_normalize_statement(statement, name, f"character/{name}/{index}", ctx,
                                                   invalid=invalid, warnings=warnings, curation=curation))
        if name == "unknown" and ecad_absent and not any(s.get("by") == ["code"] for s in statements):
            statements.append(_auto_ecad_statement(len(statements) + 1, ctx))
        facet["statements"] = statements
        facet["na_reason"] = facet.get("na_reason") or None
        if not statements:
            facet["na_reason"] = facet["na_reason"] or _auto_na_reason(name, spec, ctx, corpus_n)
        else:
            facet["na_reason"] = None
            if name == "vulnerability" and not (_cite_refs_of_statements(statements) & findings_cids):
                warnings.append("character/vulnerability: findings 와 cites 를 공유하지 않는다.")
            if name == "strength" and not (_cite_refs_of_statements(statements) & gains_cids):
                warnings.append("character/strength: gains 와 cites 를 공유하지 않는다.")
            if name == "tradeoff" and len(statements) < 2:
                warnings.append("character/tradeoff: statements 가 2 미만이라 단면만 기술이다.")
        facets.append(facet)
    character["facets"] = facets
    return character


def _auto_na_reason(facet: str, spec: dict, ctx: SpecContext, corpus_n: int) -> str:
    if facet == "anomaly" and corpus_n < 5:
        return "비교 불가(코퍼스 n<5)"
    if facet == "lineage" and ctx.kind == "snap" and not ctx.brief_refs:
        return "선행 과제 미지정"
    if facet == "strength" and not (spec.get("gains") or ()):
        return "개선 항목 없음"
    if facet == "unknown" and not (spec.get("open_items") or ()):
        return "미지 항목 없음"
    return "좌석 미기재"


def _auto_ecad_statement(index: int, ctx: SpecContext) -> dict:
    ref = "sig:counts.ecad.components"
    signal = ctx.signal("counts.ecad.components")
    quote = render.signal_text("counts.ecad.components", signal) if signal else ""
    return {
        "id": f"C{index}",
        "facet": "unknown",
        "text": "ECAD 부재로 pcb·pwr·rf·soc·passive·mem 관점 미평가 [" + ref + "]",
        "polarity": "observation",
        "by": ["code"],
        "cites": [{"ref": ref, "quote": quote}] if quote else [{"ref": ref, "quote": ""}],
        "tags": ["char:analysis:ecad_absent"],
        "confidence": "high",
        "_auto": True,
    }


def _normalize_statement(statement: dict, facet: str, path: str, ctx: SpecContext, *,
                         invalid: list[dict], warnings: list[str], curation: list[dict]) -> dict:
    statement = dict(statement)
    statement["facet"] = facet
    statement["text"] = str(statement.get("text") or "")[:240]
    statement["polarity"] = _fix_enum(statement.get("polarity"), "polarity", path, invalid)
    statement["confidence"] = _fix_enum(statement.get("confidence"), "confidence", path, invalid)
    statement["by"] = [str(b) for b in (statement.get("by") or []) if str(b)] or ["chair"]

    vocab = _character_vocab()
    tags: list[str] = []
    free = 0
    for tag in statement.get("tags") or ():
        text = str(tag)
        if text.startswith("x:"):
            free += 1
            if free <= int(vocab.get("free_max_per_narrative") or 3):
                tags.append(text)
                curation.append({"kind": "x_tag_promote", "payload": {"tag": text, "path": path}})
            continue
        parts = text.split(":", 2)
        axis_key = ":".join(parts[:2])
        value = parts[2] if len(parts) > 2 else ""
        allowed = (vocab.get("axes") or {}).get(axis_key)
        if isinstance(allowed, list) and value not in allowed:
            moved = "x:" + re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
            warnings.append(f"{path}: 어휘 밖 태그 {text} 를 {moved} 로 옮겼다.")
            free += 1
            if free <= int(vocab.get("free_max_per_narrative") or 3):
                tags.append(moved)
                curation.append({"kind": "x_tag_promote", "payload": {"tag": moved, "path": path}})
            continue
        tags.append(text)
    statement["tags"] = tags

    resolved = resolve_cites(statement.get("cites") or (), ctx, claim=statement["text"], raised_by=statement["by"])
    statement["dangling"] = resolved["dangling"]
    statement["quote_mismatch"] = resolved["quote_mismatch"]
    statement["_resolved_cites"] = resolved["cites"]
    return statement


@lru_cache(maxsize=1)
def _character_vocab() -> dict:
    from app.taxonomy import load_json

    return load_json("character-vocab")


def _cite_refs_of(items: Iterable[dict]) -> set[str]:
    out: set[str] = set()
    for item in items or ():
        for cite in (item or {}).get("cites") or ():
            if isinstance(cite, dict) and cite.get("ref"):
                out.add(str(cite["ref"]))
    return out


def _cite_refs_of_statements(statements: Iterable[dict]) -> set[str]:
    return _cite_refs_of(statements)


_PROSE_ID_RE = re.compile(r"^\s*([FGCXO]\d+)", re.MULTILINE)


def normalize_risk_spec(spec: dict, ctx: SpecContext | None = None, *, prose: str = "",
                        opinions: Sequence[dict] = ()) -> dict:
    """§4.2.2 의 정규화 10단계. 원본을 고치지 않고 정규화 사본과 플래그를 함께 돌려준다."""
    ctx = ctx or SpecContext()
    spec = json.loads(json.dumps(spec or {}, ensure_ascii=False))
    invalid: list[dict] = []
    warnings: list[str] = []
    curation: list[dict] = []
    flags: list[str] = []

    scope = dict(spec.get("scope") or {})
    target_key = str(scope.get("target_key") or ctx.target_key or "")
    if target_key and scope.get("kind") and not target_key.startswith(f"{scope['kind']}:"):
        flags.append("spec_parse_failed")
        warnings.append(f"scope.kind={scope.get('kind')} 가 target_key 접두와 다르다.")
    spec["scope"] = scope

    spec["findings"] = [
        _normalize_finding(f, f"findings/{i}", ctx, is_gain=False, invalid=invalid, warnings=warnings, curation=curation)
        for i, f in enumerate(spec.get("findings") or ()) if isinstance(f, dict)
    ]
    spec["gains"] = [
        _normalize_finding(g, f"gains/{i}", ctx, is_gain=True, invalid=invalid, warnings=warnings, curation=curation)
        for i, g in enumerate(spec.get("gains") or ()) if isinstance(g, dict)
    ]

    cross_domain = []
    for index, item in enumerate(spec.get("cross_domain") or ()):
        if not isinstance(item, dict):
            continue
        item = dict(item)
        if item.get("from_domain") == item.get("to_domain"):
            warnings.append(f"cross_domain/{index}: from_domain 과 to_domain 이 같다.")
        item["path"] = str(item.get("path") or "")[:400]
        resolved = resolve_cites(item.get("cites") or (), ctx, claim=item["path"],
                                 raised_by=[str(k) for k in item.get("raised_by") or ()])
        item["dangling"] = resolved["dangling"]
        item["quote_mismatch"] = resolved["quote_mismatch"]
        item["_resolved_cites"] = resolved["cites"]
        cross_domain.append(item)
    spec["cross_domain"] = cross_domain

    open_items = []
    for index, item in enumerate(spec.get("open_items") or ()):
        if not isinstance(item, dict):
            continue
        item = dict(item)
        item["question"] = str(item.get("question") or "")[:200]
        check = dict(item.get("resolving_check") or {})
        if check.get("kind") not in ("tool", "sim", "test", "field"):
            invalid.append({"path": f"open_items/{index}/resolving_check", "field": "kind", "value": check.get("kind")})
            check["kind"] = "tool"
        check["ref"] = str(check.get("ref") or "")
        item["resolving_check"] = check
        open_items.append(item)
    spec["open_items"] = open_items

    spec["character"] = _normalize_character(spec.get("character") or {}, spec, ctx,
                                             invalid=invalid, warnings=warnings, curation=curation)
    facets_filled = sum(1 for f in spec["character"]["facets"] if f.get("statements"))

    spec["verdict"] = _fix_enum(spec.get("verdict"), "verdict", "verdict", invalid)
    spec["verdict_conditions"] = [str(c) for c in (spec.get("verdict_conditions") or []) if str(c)]

    coverage = dict(spec.get("coverage") or {})
    if ctx.seats:
        declared = {str((s or {}).get("key")) for s in coverage.get("seats") or () if isinstance(s, dict)}
        if declared and declared != set(ctx.seats):
            flags.append("coverage_mismatch")
            warnings.append("coverage.seats 가 SSE personas 와 다르다.")
    spec["coverage"] = coverage

    computed = _compute_evidence_profile(spec, opinions)
    claimed = spec.get("evidence_profile") or {}
    if _profile_mismatch(claimed, computed):
        flags.append("header_mismatch")
    spec["evidence_profile_computed"] = computed

    # 10. 전역 id.
    if ctx.panel_id:
        for finding in spec["findings"] + spec["gains"]:
            finding["claim_uid"] = f"{ctx.panel_id}#{finding.get('id')}"
        for facet in spec["character"]["facets"]:
            for statement in facet["statements"]:
                statement["claim_uid"] = f"{ctx.panel_id}#{statement.get('id')}"
        for item in spec["cross_domain"]:
            item["claim_uid"] = f"{ctx.panel_id}#{item.get('id')}"
        for item in spec["open_items"]:
            item["claim_uid"] = f"{ctx.panel_id}#{item.get('id')}"

    # §4.2.3 산문과 spec 의 id 대조.
    if prose:
        prose_ids = set(_PROSE_ID_RE.findall(prose))
        spec_ids = {str(x.get("id")) for x in spec["findings"] + spec["gains"] + spec["cross_domain"] + spec["open_items"]}
        for facet in spec["character"]["facets"]:
            spec_ids.update(str(s.get("id")) for s in facet["statements"])
        for only in sorted(prose_ids - spec_ids):
            warnings.append(f"prose_only_id {only}")
        for only in sorted(spec_ids - prose_ids):
            warnings.append(f"spec_only_id {only}")

    if any(f.get("evidence_grade") == "경험칙" for f in spec["findings"]) and not spec["findings"]:
        flags.append("low_ir_cite")

    return {
        "spec": spec,
        "invalid_enum": invalid,
        "parse_warnings": warnings,
        "curation": curation,
        "quality": {
            "flag": sorted(set(flags)),
            "facets_filled": f"{facets_filled}/8",
            "evidence_profile_computed": computed,
            "normalize_version": NORMALIZE_VERSION,
        },
        "ok": "spec_parse_failed" not in flags,
    }


def _compute_evidence_profile(spec: dict, opinions: Sequence[dict]) -> dict:
    """§4.2.4 — 좌석 회계와 finding cites 로 evidence_profile 을 코드가 다시 센다."""
    tool = sum(int((o or {}).get("tool_calls_ok") or 0) for o in opinions or ())
    card = sum(int((o or {}).get("knowledge_hits_n") or 0) for o in opinions or ())
    heuristic = 0
    measured = 0
    for finding in list(spec.get("findings") or ()) + list(spec.get("gains") or ()):
        cites = finding.get("_resolved_cites") or []
        usable = [c for c in cites if c.get("ok")]
        if not usable:
            heuristic += 1
        if any(str(c.get("ref_type")) in ("inc", "rpt") for c in usable):
            measured += 1
    verified = sum(1 for f in (spec.get("findings") or ()) if f.get("status") == "verified")
    dismissed = sum(1 for f in (spec.get("findings") or ()) if f.get("status") == "dismissed")
    return {"tool": tool, "card": card, "precedent": {"verified": verified, "dismissed": dismissed},
            "heuristic": heuristic, "measured": measured}


def _profile_mismatch(claimed: dict, computed: dict) -> bool:
    for key in ("tool", "card", "heuristic", "measured"):
        code_value = int(computed.get(key) or 0)
        try:
            chair_value = int((claimed or {}).get(key) or 0)
        except (TypeError, ValueError):
            return True
        if abs(chair_value - code_value) > max(2, 0.3 * code_value):
            return True
    return False


# ================================================================ 브리프 조립·패널 결과 저장(plan §5.6.2·§6.7.2 8단계)

# 좌석 발언·의장 산문에서 뽑는 참조 토큰(§0.2.1 문법, brief._REF_TOKEN 과 같은 식).
CITED_REF_RE = re.compile(r"\b(?:reg|narr|rule|c|d|sig|warn|gate|p|e|rpt|inc|card):[^\s\]|]+")
# IR·상태층을 가리키는 스킴 — quality.ir_cite_rate 의 분자다(§6.5.5).
IR_REF_KINDS = frozenset({"p", "e", "c", "d", "sig", "warn", "gate", "rule"})
EXCERPT_FOR_RAG_MAX = 1500          # rr_seat_opinions.excerpt_for_rag 상한(§5.2.2 F)
# seat_opinion.character_sentences — 성격을 드러낸 문장만 발췌한다(plan §4.5, ≤5문장·각 ≤240자).
CHARACTER_SENTENCES_MAX = 5
CHARACTER_SENTENCE_MAX = 240
_CHARACTER_RE = re.compile(r"성격|성향|철학|경향|의도")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|[\n]+")


def _character_sentences(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """좌석 발언에서 성격·성향·철학·경향·의도를 말한 문장만 뽑는다(§5.6.3 E7 좌석 개인 기억의 입력)."""
    out: list[str] = []
    for row in rows:
        for sentence in _SENTENCE_SPLIT_RE.split(str(row.get("say_excerpt") or "")):
            text = sentence.strip()
            if not text or not _CHARACTER_RE.search(text):
                continue
            text = text[:CHARACTER_SENTENCE_MAX]
            if text not in out:
                out.append(text)
            if len(out) >= CHARACTER_SENTENCES_MAX:
                return out
    return out
SAY_EXCERPT_MAX = 2000              # seat_opinion.turns[].say_excerpt 상한(§6.7.2 7단계)
ABSTAIN_PREFIX = "판정 불가"        # §6.8.2 — 최종 발언이 이 말로 시작하면 abstain 이다.
_STANCES = ("agree", "conditional", "oppose", "abstain")


def cited_refs_in(text: Any) -> list[str]:
    """문자열에서 참조 목록을 등장 순서로 뽑는다(중복 제거, 문법에 맞지 않는 토큰은 버린다)."""
    out: list[str] = []
    seen: set[str] = set()
    for token in CITED_REF_RE.findall(str(text or "")):
        info = parse_ref(token)
        if info is None or info["ref"] in seen:
            continue
        seen.add(info["ref"])
        out.append(info["ref"])
    return out


def prior_evidence(store, target_key: str, *, user_memo: str | None = None,
                   seats: Sequence[dict] | None = None, panel_id: str | None = None,
                   exclude: Sequence[str] = ()) -> list[dict]:
    """다음 패널의 `delib_opts.evidence` 를 §5.6.1 예산표대로 조립한다(항목 본체는 `brief.build_brief`).

    E0c(좌석 계약)는 `runner.build_delib_opts` 가 다시 끼우므로 여기서는 빼고 돌려준다 — 같은 조립 결과를
    웹 러너는 delib_opts 로, MCP L2 는 `risk_get_brief` 응답으로 받는다(§5.6). user_memo(지금 도는 잡의
    메모)는 브리프에 그대로 넘겨 M 으로 싣는다 — 브리프가 rr_jobs 에서 찾게 두면 그 타깃의 최근 잡 메모가
    실린다. M 이 빠진 채 돌아온 경우(제외)에만 마지막 슬롯에 붙인다.
    """
    from app import brief as brief_module  # noqa: PLC0415 — 순환 import 회피(brief 는 narrative 를 쓴다).

    from app import field_source  # noqa: PLC0415 — 선택 채널이라 지연 import 한다.

    # 조립 경로는 strict_lint 다 — 판단어가 섞인 브리프를 엔진에 보내느니 E500 으로 멈춘다(plan §5.6.2).
    # E10 조회 채널은 없으면 None 이다(그 블록만 결측 문구가 되고 조립은 완주한다).
    field = field_source.for_target(store, target_key)
    try:
        built = brief_module.build_brief(store, target_key, seats=seats, panel_id=panel_id,
                                        exclude=tuple(exclude), field=field, strict_lint=True,
                                        user_memo=user_memo)
    finally:
        # 채널은 자기 httpx.Client 를 소유한다 — 닫지 않으면 브리프 조립마다 소켓이 샌다.
        if field is not None:
            field.close()
    items = [item for item, key in zip(built["evidence"], built["keys"]) if key != "E0c"]
    if user_memo and not any(str(i.get("source")) == "user_memo" for i in items):
        items.append({"source": "user_memo", "tool": "note", "args": target_key,
                      "result": str(user_memo)[:2000], "key": "M"})
    return items


def _opinion_id(panel_id: str, agent_key: str, cycle: int) -> str:
    """결정론 opinion_id(hex32) — 같은 패널·좌석·cycle 이면 재제출해도 같은 id 다(seat_opinion.v1 pattern)."""
    return hashlib.sha256(f"{panel_id}|{agent_key}|{cycle}".encode("utf-8")).hexdigest()[:32]


def _panel_scope(store, panel_id: str) -> tuple[dict, dict, list[dict], SpecContext]:
    """패널 행·타깃 행·seats 와 cites 검증 스코프(SpecContext)를 만든다."""
    panel = store.query_one(
        "SELECT id, target_key, owner_sub, panel_no, tier, seats_json, conv_id, chair_template, model_json"
        " FROM rr_panels WHERE id = ?", (panel_id,))
    if panel is None:
        raise AppError("E404", f"패널을 찾을 수 없습니다 — {panel_id}.", 404)
    target = store.query_one(
        "SELECT target_key, owner_sub, kind, ref_id, project_id, base_project_id, ir_hash"
        " FROM rr_targets WHERE target_key = ?", (panel["target_key"],))
    if target is None:
        raise AppError("E404", f"타깃을 찾을 수 없습니다 — {panel['target_key']}.", 404)

    snapshot_ids: tuple[str, ...] = ()
    diff_id = ""
    diff: dict = {}
    if target["kind"] == "diff":
        row = store.query_one(
            "SELECT id, base_snapshot_id, target_snapshot_id, diff_json FROM rr_diffs WHERE id = ?",
            (target["ref_id"],))
        if row is not None:
            diff_id = str(row["id"])
            snapshot_ids = (str(row["base_snapshot_id"]), str(row["target_snapshot_id"]))
            try:
                loaded = json.loads(row["diff_json"] or "{}")
            except ValueError:
                loaded = {}
            diff = loaded if isinstance(loaded, dict) else {}
    else:
        snapshot_ids = (str(target["ref_id"]),)

    states: dict = {}
    for sid in snapshot_ids:
        row = store.query_one("SELECT state_json FROM rr_states WHERE snapshot_id = ?", (sid,))
        if row is None:
            continue
        try:
            value = json.loads(row["state_json"] or "{}")
        except ValueError:
            continue
        if isinstance(value, dict):
            states[sid] = value

    try:
        seats = json.loads(panel["seats_json"] or "[]")
    except ValueError:
        seats = []
    seats = [s for s in seats if isinstance(s, dict)]

    ctx = SpecContext(
        panel_id=str(panel["id"]), target_key=str(target["target_key"]),
        project_id=str(target["project_id"] or ""), owner_sub=str(panel["owner_sub"] or ""),
        kind=str(target["kind"]), snapshot_ids=snapshot_ids, diff_id=diff_id,
        ir_hash=str(target["ir_hash"] or ""), store=store, states=states, diff=diff,
        conv_id=str(panel["conv_id"] or ""), seats=tuple(str(s.get("key")) for s in seats),
    )
    return dict(panel), dict(target), seats, ctx


def _seat_turns(turns: Sequence[Mapping[str, Any]]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for index, turn in enumerate(turns or ()):
        if not isinstance(turn, Mapping):
            continue
        key = str(turn.get("persona") or "")
        if not key:
            continue
        stance = str(turn.get("stance") or "")
        grouped.setdefault(key, []).append({
            "round": int(turn.get("round") or (len(grouped.get(key, [])) + 1)),
            "say_excerpt": str(turn.get("say") or "")[:SAY_EXCERPT_MAX],
            "position": str(turn.get("position") or ""),
            "stance": stance if stance in _STANCES else "conditional",
            "non_negotiable": "",
            "_seq": index,
        })
    return grouped


def _final_stance(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "abstain"
    last = rows[-1]
    say = str(last.get("say_excerpt") or "").lstrip()
    if say.startswith(ABSTAIN_PREFIX):
        return "abstain"
    return str(last.get("stance") or "conditional")


def _atom_seat_index(atoms: Sequence[Mapping[str, Any]]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """좌석 키 → 제기한 claim_uid 목록 / 기각한 claim_uid 목록."""
    raised: dict[str, list[str]] = {}
    contested: dict[str, list[str]] = {}
    for atom in atoms:
        uid = str(atom.get("claim_uid") or "")
        for key in atom.get("raised_by") or ():
            raised.setdefault(str(key), []).append(uid)
        for key in atom.get("contested_by") or ():
            contested.setdefault(str(key), []).append(uid)
    return raised, contested


# 원자 본문에서 저장형 인젝션을 찾는 자리(plan §3.4.1). 적중이면 그 finding 은 회수 후보에서 빠지고(recall_eligible=0)
# 원문은 rr_curation_queue(kind='suspect_text') 로 간다 — 사람이 승인하면 되돌아온다.
SUSPECT_FIELDS: tuple[str, ...] = ("claim", "warrant", "statement", "title", "mechanism_free",
                                  "trigger_condition", "contest_note")


def suspect_hit(atom: Mapping[str, Any]) -> dict | None:
    """원자 본문 필드 중 인젝션 어휘에 걸린 첫 자리의 큐 payload(없으면 None)."""
    for name in SUSPECT_FIELDS:
        value = atom.get(name)
        if not isinstance(value, str) or not value:
            continue
        lexicon_id = render.injection_hit(value)
        if lexicon_id is not None:
            return {"sha1": render.source_sha1(value), "raw": value, "lexicon_id": lexicon_id,
                    "lexicon_version": render.INJECTION_VERSION, "field": name}
    return None


def persist_panel_result(store, panel_id: str, *, decision_text: str = "", spec: Mapping[str, Any] | None = None,
                         turns: Sequence[Mapping[str, Any]] = (), attribution: Mapping[str, Any] | None = None,
                         actor: str | None = None) -> dict:
    """패널 1건의 서술을 앱 DB 에 앉힌다(plan §6.7.2 8단계) — rr_seat_opinions·rr_findings·rr_claim_refs·rr_character.

    파싱 실패(`spec is None`)면 findings 없이 좌석 의견만 저장한다. 같은 패널을 다시 제출하면 그 패널이 만든
    행을 지우고 다시 앉히므로 멱등이다. 반환은 러너·라우트가 커버리지·품질에 쓰는 요약이다 —
    `{seats[{agent_key, opinion_id, turns_n, cited_refs_n, cited_ir, abstained}], findings_total,
      adversary_rejects, grade_dist, header_mismatch, coverage_mismatch, parse_warnings}`.
    """
    from app import planner  # noqa: PLC0415 — 반대석 키 상수(planner 는 narrative 를 import 하지 않는다).

    panel, target, seats, ctx = _panel_scope(store, panel_id)
    attribution = dict(attribution or {"seats": {}, "extra_seats": []})
    attr_seats = dict(attribution.get("seats") or {})
    grouped = _seat_turns(turns)

    normalized = normalize_risk_spec(dict(spec or {}), ctx, prose=decision_text or "")
    body = normalized["spec"]
    atoms = list(body.get("findings") or []) + list(body.get("gains") or [])
    if spec is None:
        atoms = []
    raised_by_seat, contested_by_seat = _atom_seat_index(atoms)

    owner_sub = str(panel["owner_sub"] or target["owner_sub"] or "")
    target_key = str(panel["target_key"])
    project_id = str(target["project_id"] or "")
    snapshot_id = ctx.snapshot_ids[-1] if ctx.snapshot_ids else None
    now = now_epoch()
    versions = {k: (atoms[0].get(k) if atoms else None) for k in ("rule_version", "ir_version", "diff_version")}
    # D6 — 좌석 의견 안에 그 패널이 쓴 모델 이름 사본을 둔다(plan §4.5, rr_panels.model_json.model).
    try:
        panel_model = (json.loads(panel["model_json"] or "{}") or {}).get("model")
    except (TypeError, ValueError):
        panel_model = None

    # 좌석 목록 = seats_json 5석 + (발언·귀속이 있는) 반대석·추가 좌석.
    roster: list[tuple[str, str, str]] = [
        (str(s.get("key")), str(s.get("domain") or _dom_of(str(s.get("key")))), str(s.get("origin") or "primary"))
        for s in seats
    ]
    known = {key for key, _, _ in roster}
    for key in list(grouped) + [k for k in attr_seats if k not in known]:
        if key in known or not key:
            continue
        known.add(key)
        origin = "adversary" if key == planner.ADVERSARY_KEY else "new"
        roster.append((key, "delib" if origin == "adversary" else _dom_of(key), origin))

    cycles = {
        r["agent_key"]: int(r["cycle"] or 1)
        for r in store.query("SELECT agent_key, cycle FROM rr_coverage WHERE target_key = ?", (target_key,))
    }

    out_seats: list[dict] = []
    opinion_rows: list[tuple] = []
    for agent_key, domain, origin in roster:
        cycle = cycles.get(agent_key, 1)
        opinion_id = _opinion_id(panel_id, agent_key, cycle)
        rows = grouped.get(agent_key) or []
        state = dict(attr_seats.get(agent_key) or {})
        my_atoms = [a for a in atoms if str(a.get("claim_uid")) in set(raised_by_seat.get(agent_key) or ())]

        refs: list[str] = []
        for row in rows:
            for ref in cited_refs_in(row.get("say_excerpt")):
                if ref not in refs:
                    refs.append(ref)
        for atom in my_atoms:
            for cite in atom.get("_resolved_cites") or ():
                ref = str(cite.get("ref") or "")
                if ref and ref not in refs:
                    refs.append(ref)
        resolved_refs = [r for r in refs if (parse_ref(r) or {}).get("kind")]
        cited_ckeys = sorted({
            ck for atom in my_atoms for ck in ((atom.get("subject") or {}).get("ckeys") or ())
            if str(ck).startswith("ck:")
        })
        cited_ir = any((parse_ref(r) or {}).get("kind") in IR_REF_KINDS for r in refs)
        grades = [str(a.get("evidence_grade") or "") for a in my_atoms if a.get("evidence_grade")]
        dangling_n = sum(len(a.get("dangling") or ()) for a in my_atoms)
        final_stance = _final_stance(rows)

        opinion = {
            "opinion_id": opinion_id, "target_key": target_key, "panel_id": panel_id,
            "agent_key": agent_key, "domain": domain, "origin": origin, "cycle": cycle,
            "turns": [{k: v for k, v in row.items() if k != "_seq"} for row in rows],
            "final_stance": final_stance,
            "tool_calls": list(state.get("tool_calls") or []),
            "tool_calls_n": state.get("tool_calls_n"),
            "tool_calls_ok": state.get("tool_calls_ok"),
            # 지식 카드 적중을 세는 원천이 아직 없다 — 0 이라고 적으면 '없었다' 로 읽히므로 미측정(null)으로 둔다.
            "knowledge_hits_n": None,
            "model": panel_model,
            "cited_refs": refs, "cited_refs_resolved": resolved_refs, "cited_ckeys": cited_ckeys,
            "quality": {
                "used_tool": state.get("used_tool"), "cited_ir": cited_ir,
                "grade_min": (sorted(grades, key=lambda g: _GRADE_RANK.get(g, 0))[0] if grades else None),
                "dangling_n": dangling_n,
                "actor": actor, "actor_verified": False if actor else None,
            },
            "raised_finding_ids": sorted(set(raised_by_seat.get(agent_key) or ())),
            "contested_finding_ids": sorted(set(contested_by_seat.get(agent_key) or ())),
            "character_sentences": _character_sentences(rows),
            "excerpt_for_rag": "\n".join(str(r.get("say_excerpt") or "") for r in rows)[:EXCERPT_FOR_RAG_MAX],
        }
        opinion_rows.append((
            opinion_id, target_key, panel_id, owner_sub, agent_key, domain,
            origin if origin in ("primary", "counter", "adversary", "new") else "new", cycle,
            canonical_json(opinion),
            final_stance, state.get("tool_calls_n"), state.get("tool_calls_ok"), None,
            json.dumps(refs, ensure_ascii=False), json.dumps(opinion["quality"], ensure_ascii=False),
            json.dumps(opinion["raised_finding_ids"], ensure_ascii=False),
            opinion["excerpt_for_rag"], now,
        ))
        if origin in ("primary", "counter"):
            out_seats.append({
                "agent_key": agent_key, "opinion_id": opinion_id,
                "turns_n": len(rows), "cited_refs_n": len(refs), "cited_ir": cited_ir,
                "abstained": final_stance == "abstain",
            })

    with store.tx():
        store.execute("DELETE FROM rr_seat_opinions WHERE panel_id = ?", (panel_id,))
        store.executemany(
            "INSERT INTO rr_seat_opinions(opinion_id, target_key, panel_id, owner_sub, agent_key, domain, origin,"
            " cycle, opinion_json, final_stance, tool_calls_n, tool_calls_ok, knowledge_hits_n, cited_refs_json,"
            " quality_json, raised_finding_ids_json, excerpt_for_rag, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            opinion_rows,
        )

        old = [r["claim_uid"] for r in store.query(
            "SELECT claim_uid FROM rr_findings WHERE panel_id = ?", (panel_id,))]
        if old:
            store.executemany("DELETE FROM rr_claim_refs WHERE claim_uid = ?", [(uid,) for uid in old])
        store.execute("DELETE FROM rr_findings WHERE panel_id = ?", (panel_id,))

        opinion_of = {s["agent_key"]: s["opinion_id"] for s in out_seats}
        for atom in atoms:
            uid = str(atom.get("claim_uid") or "")
            raised = [str(k) for k in (atom.get("raised_by") or ())]
            suspect = suspect_hit(atom)
            store.execute(
                "INSERT INTO rr_findings(finding_id, claim_uid, target_key, panel_id, opinion_id, project_id,"
                " snapshot_id, diff_id, owner_sub, visibility, direction, domain, mechanism, mechanism_detail,"
                " mechanism_free, change_kind, subject_key, ckeys_json, trigger_condition, severity, sev3,"
                " judgement, detectability, detect_tool, evidence_grade, precedent, dangling, cluster_key,"
                " finding_json, recall_eligible, status, taxonomy_version, rule_version, ir_version, diff_version,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uid, uid, target_key, panel_id,
                    next((opinion_of[k] for k in raised if k in opinion_of), None), project_id,
                    snapshot_id, ctx.diff_id or None, owner_sub, "private",
                    str(atom.get("direction") or "risk"), str(atom.get("domain") or ""),
                    atom.get("mechanism"), atom.get("mechanism_detail"), atom.get("mechanism_free"),
                    atom.get("change_kind"), atom.get("subject_key"),
                    json.dumps((atom.get("subject") or {}).get("ckeys") or [], ensure_ascii=False),
                    atom.get("trigger_condition"), atom.get("severity"), atom.get("sev3"),
                    atom.get("judgement"), (atom.get("detectability") or {}).get("level"),
                    (atom.get("detectability") or {}).get("tool"), atom.get("evidence_grade"),
                    atom.get("precedent"), 1 if atom.get("dangling") else 0, atom.get("cluster_key"),
                    json.dumps(atom, ensure_ascii=False, sort_keys=True),
                    0 if suspect is not None else 1, "open",
                    atom.get("taxonomy_version"), versions["rule_version"], versions["ir_version"],
                    versions["diff_version"], now, now,
                ),
            )
            for cite in atom.get("_resolved_cites") or ():
                ref = str(cite.get("ref") or "")
                # 엔진의 근거 표지는 역색인에 앉히지 않는다 — 참조가 아니고, 같은 번호가 패널마다 다른 항목을
                # 가리킨다. 앉히면 dangling=1 인 행으로 남아 '지어낸 참조' 로 세어진다(원문은 finding_json.cites 에 있다).
                if not ref or cite.get("dangling_reason") == ENGINE_MARKER:
                    continue
                store.execute(
                    "INSERT OR REPLACE INTO rr_claim_refs(claim_uid, ref_type, ref, quote, owner_sub, target_key,"
                    " dangling) VALUES (?,?,?,?,?,?,?)",
                    (uid, str(cite.get("ref_type") or "unknown"), ref, str(cite.get("quote") or ""),
                     owner_sub, target_key, 0 if cite.get("ok") else 1),
                )

            if suspect is not None:
                # 같은 sha1 이 이미 열려 있으면 다시 넣지 않는다(브리프 큐 적재와 같은 규칙).
                opened = store.query_one(
                    "SELECT id FROM rr_curation_queue WHERE kind = 'suspect_text' AND status = 'open'"
                    " AND payload_json LIKE ?", (f'%"sha1":"{suspect["sha1"]}"%',))
                if opened is None:
                    from app.common import new_uuid  # noqa: PLC0415 — 이 자리에서만 쓴다.

                    store.execute(
                        "INSERT INTO rr_curation_queue(id, owner_sub, kind, payload_json, status, created_at)"
                        " VALUES (?,?, 'suspect_text', ?, 'open', ?)",
                        (new_uuid(), owner_sub,
                         canonical_json({**suspect, "claim_uid": uid, "finding_id": uid,
                                         "target_key": target_key, "panel_id": panel_id}),
                         now),
                    )

        # 성격 진술(§4.6 L2 panel 층). 같은 패널이 다시 제출되면 그 패널의 행만 갈아 끼운다.
        store.execute("DELETE FROM rr_character WHERE id LIKE ?", (f"{panel_id}#%",))
        if spec is not None and project_id:
            for facet in (body.get("character") or {}).get("facets") or ():
                for index, statement in enumerate(facet.get("statements") or ()):
                    local = str(statement.get("id") or f"{facet.get('facet')}-{index}")
                    sid = f"{panel_id}#{local}"
                    tags = list(statement.get("tags") or [])
                    store.execute(
                        "INSERT OR REPLACE INTO rr_character(id, project_id, owner_sub, facet, tag, tags_json,"
                        " statement, polarity, cites_json, by_json, first_target_key, support_panels,"
                        " support_targets, confidence, needs_review, status, created_at, updated_at)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,1,1,?,0,'panel',?,?)",
                        (sid, project_id, owner_sub, str(facet.get("facet")), tags[0] if tags else None,
                         json.dumps(tags, ensure_ascii=False), str(statement.get("text") or ""),
                         statement.get("polarity"),
                         json.dumps(statement.get("cites") or [], ensure_ascii=False),
                         json.dumps(statement.get("by") or [], ensure_ascii=False),
                         target_key, statement.get("confidence"), now, now),
                    )

    flags = list(normalized["quality"].get("flag") or ())
    grade_dist: dict[str, int] = {}
    for atom in atoms:
        grade = str(atom.get("evidence_grade") or "")
        if grade:
            grade_dist[grade] = grade_dist.get(grade, 0) + 1
    rejects = len(set(contested_by_seat.get(planner.ADVERSARY_KEY) or ()))

    return {
        "panel_id": panel_id,
        "seats": out_seats,
        "findings_total": len(atoms),
        "adversary_rejects": rejects,
        "grade_dist": grade_dist,
        "header_mismatch": "header_mismatch" in flags,
        "coverage_mismatch": "coverage_mismatch" in flags,
        "spec_parse_failed": spec is None or "spec_parse_failed" in flags,
        "parse_warnings": list(normalized.get("parse_warnings") or ()),
        "normalized": normalized,
    }
