#!/usr/bin/env python3
# ReportArchive 온톨로지 부트스트랩 — 신규 6축·12관계를 멱등 생성하고 정의 차이는 drift 로 보고만 한다(plan §5.3.1~§5.3.4)
"""실행자 셸 전용 스크립트다. 앱 런타임(`ra_client.py`)은 이 파일도 `RA_ADMIN_PAT` 도 부르지 않는다.

    RA_ADMIN_PAT=rat_… python backend/scripts/bootstrap_ra_ontology.py --base <RA REST 오리진> [--apply]

절차(plan §5.3.4).
 (1) `GET /api/entity-types` · `GET /api/relation-types` 로 현재 목록을 읽는다.
 (2) 아래 상수표(AXES · PROPS · RELATIONS · REL_PROPS)와 대조해 **없는 것만** 생성 후보로 만든다.
 (3) 있는 것의 정의가 다르면 `drift` 로 보고만 하고 update 계열(PATCH)은 절대 부르지 않는다.
 (4) 기본은 dry-run 이고 `--apply` 일 때만 축 → 축 속성 → 관계 종류 → 관계 속성 순서로 생성한다.
 (5) `{created, skipped, drift, …}` JSON 을 내고 drift 가 있으면 종료 코드 2 다.
 (6) 기존 축·관계는 읽기만 한다 — `--apply` 는 전후 덤프를 비교해 무변경을 함께 보고한다.

종료 코드. 0 정상 · 1 호출·인자 실패 · 2 drift 있음 · 3 자격(RA_ADMIN_PAT) 없음(호출 0건).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Mapping, Sequence

import httpx

CRED_ENV = "RA_ADMIN_PAT"
DEFAULT_TIMEOUT = 30.0


def _enum(*pairs: tuple[str, str]) -> list[dict]:
    """`enum_options` — RA 는 `[{value,label}]` 를 받는다(plan §5.3.3)."""
    return [{"value": value, "label": label} for value, label in pairs]


def _prop(key: str, label: str, data_type: str, sort_order: int, **extra: Any) -> dict:
    """`PropertyDefCreate` 한 줄. required·multi 는 RA 기본값(False)을 그대로 쓴다."""
    row: dict[str, Any] = {"key": key, "label": label, "data_type": data_type,
                           "required": False, "multi": False, "sort_order": sort_order}
    row.update(extra)
    return row


# 15 도메인(assets/taxonomy.v1.json axes.domain 과 코드 동일).
_DOMAINS = _enum(
    ("xd", "XD(외관·조립 설계)"), ("sim", "해석(CAE)"), ("cam", "카메라 모듈"), ("rel", "신뢰성"),
    ("soc", "SoC·프로세서"), ("disp", "디스플레이 모듈"), ("mech", "기구 구조"), ("pcb", "PCB"),
    ("rf", "RF·안테나"), ("passive", "수동 소자"), ("pwr", "전원·배터리"), ("sh", "SH"),
    ("mem", "메모리"), ("std", "규격·표준"), ("material", "재료"),
)
# 투영 범위 공통 속성(plan §5.1 원칙 9) — 네 record 축이 같은 두 속성을 갖는다.
_VISIBILITY = _enum(("private", "비공개"), ("org", "조직 공개"))

# ---------------------------------------------------------------- 축 6(plan §5.3.1)
AXES: tuple[dict, ...] = (
    {"slug": "expert", "label": "전문가", "icon": "expert", "multi": False, "sort_order": 100,
     "description": "HWAX 리스크 심사 — 심의 좌석에 앉는 전문가 에이전트(값·코드 모두 agent_key)",
     "kind_class": "reference"},
    {"slug": "design_snapshot", "label": "설계 스냅샷", "icon": "snapshot", "multi": False, "sort_order": 110,
     "description": "HWAX 리스크 심사 — 소스 앱을 한 시점에 동결한 설계 IR 헤더(원본은 hwax_risk 앱 DB rr_snapshots)",
     "kind_class": "record"},
    {"slug": "design_diff", "label": "설계 diff", "icon": "diff", "multi": False, "sort_order": 120,
     "description": "HWAX 리스크 심사 — 스냅샷 두 개를 비교한 변경 원장 헤더(원본은 앱 DB rr_diffs)",
     "kind_class": "record"},
    {"slug": "assessment", "label": "심사 판정", "icon": "assessment", "multi": False, "sort_order": 130,
     "description": "HWAX 리스크 심사 — 좌석 1석이 타깃 1개에 남긴 판정 헤더(서술 본문은 AIDataHub 의견 레코드)",
     "kind_class": "record"},
    {"slug": "risk_finding", "label": "리스크 항목", "icon": "risk", "multi": False, "sort_order": 140,
     "description": "HWAX 리스크 심사 — 등록부 클러스터 1건(원자는 앱 DB rr_findings, 대표 claim 만 statement 에 담는다)",
     "kind_class": "record"},
    {"slug": "design_trait", "label": "설계 성격", "icon": "trait", "multi": False, "sort_order": 150,
     "description": "HWAX 리스크 심사 — 과제 성격 통제 어휘 태그(char:<axis>:<value>)",
     "kind_class": "reference"},
)

# ---------------------------------------------------------------- 축 속성(plan §5.3.1)
PROPS: dict[str, tuple[dict, ...]] = {
    "expert": (
        _prop("domain", "도메인", "text", 1),
        _prop("adh_agent_type", "AIDataHub agent_type", "text", 2, help="value 와 같은 값이다."),
        _prop("active", "활성", "bool", 3),
    ),
    "design_snapshot": (
        _prop("source", "소스", "enum", 1,
              enum_options=_enum(("mcad", "MCAD(StepForge)"), ("dyna", "Dyna(DynaForge)"),
                                 ("ecad", "ECAD(ODB hub)"), ("merged", "병합")),
              required=True, help="kinds 가 2개 이상이면 merged"),
        _prop("captured_at", "동결 시각", "date", 2),
        _prop("ir_version", "IR 버전", "text", 3),
        _prop("ir_hash", "IR 해시", "text", 4),
        _prop("node_count", "노드 수", "number", 5),
        _prop("edge_count", "엣지 수", "number", 6),
        _prop("portal_snapshot_id", "앱 스냅샷 id", "text", 7),
        _prop("blocked", "차단", "bool", 8),
        _prop("missing", "결손", "text", 9, help="콤마 목록"),
        _prop("owner", "소유자", "text", 10),
        _prop("visibility", "공개 범위", "enum", 11, enum_options=_VISIBILITY),
        _prop("summary", "요약", "longtext", 12, help="rr_state 요약 ≤2000, 판단어 린터 통과분"),
    ),
    "design_diff": (
        _prop("base_snapshot", "기준 스냅샷", "entity_ref", 1,
              ref_type_slug="design_snapshot", required=True),
        _prop("target_snapshot", "대상 스냅샷", "entity_ref", 2,
              ref_type_slug="design_snapshot", required=True),
        _prop("pair_kind", "비교 종류", "enum", 3,
              enum_options=_enum(("same_project_revision", "같은 과제 개정"),
                                 ("cross_project", "다른 과제"))),
        _prop("added", "추가", "number", 4),
        _prop("removed", "삭제", "number", 5),
        _prop("changed", "변경", "number", 6),
        _prop("semantic_events", "의미 이벤트", "number", 7),
        _prop("tol_parity", "공차 패리티", "bool", 8),
        _prop("result_parity", "결과 패리티", "bool", 9),
        _prop("portal_diff_id", "앱 diff id", "text", 10),
        _prop("owner", "소유자", "text", 11),
        _prop("visibility", "공개 범위", "enum", 12, enum_options=_VISIBILITY),
        _prop("summary", "요약", "longtext", 13, help="summary_text 앞 2000자"),
    ),
    "assessment": (
        _prop("coverage_key", "커버리지 키", "text", 1),
        _prop("expert_key", "좌석 키", "text", 2),
        _prop("domain", "도메인", "text", 3),
        _prop("origin", "좌석 유래", "enum", 4,
              enum_options=_enum(("primary", "정석"), ("counter", "반대석"))),
        _prop("stance", "입장", "enum", 5,
              enum_options=_enum(("agree", "동의"), ("conditional", "조건부"),
                                 ("oppose", "반대"), ("abstain", "기권"))),
        _prop("panel_verdict", "패널 판정", "enum", 6,
              enum_options=_enum(("go", "진행"), ("conditional", "조건부"),
                                 ("no-go", "중단"), ("undetermined", "미정"))),
        _prop("panel_id", "패널 id", "text", 7),
        _prop("panel_no", "패널 회차", "number", 8),
        _prop("reviewed_at", "심사 시각", "date", 9),
        _prop("tool_calls_ok", "성공 도구 호출", "number", 10),
        _prop("cited_ir", "IR 인용", "bool", 11),
        _prop("engine", "엔진", "enum", 12, enum_options=_enum(("web", "웹"), ("mcp", "MCP"))),
        _prop("owner", "소유자", "text", 13),
        _prop("visibility", "공개 범위", "enum", 14, enum_options=_VISIBILITY),
        _prop("record_id", "AIDataHub 레코드 id", "text", 15),
    ),
    "risk_finding": (
        _prop("cluster_key", "클러스터 키", "text", 1),
        _prop("direction", "방향", "enum", 2,
              enum_options=_enum(("risk", "리스크"), ("improvement", "개선"), ("neutral", "중립"))),
        _prop("severity", "심각도", "enum", 3,
              enum_options=_enum(("경미", "경미"), ("중대", "중대"), ("치명", "치명"))),
        _prop("judgement", "판정", "enum", 4,
              enum_options=_enum(("OK", "OK"), ("WARNING", "WARNING"), ("FAIL", "FAIL"),
                                 ("undetermined", "미정"))),
        _prop("domain", "도메인", "enum", 5, enum_options=_DOMAINS),
        _prop("mechanism", "메커니즘", "enum", 6,
              enum_options=_enum(("thermal", "열"), ("mechanical", "기계"), ("interface", "계면"),
                                 ("electrical", "전기"), ("material", "재료"), ("process", "공정"))),
        _prop("mechanism_detail", "메커니즘 상세", "text", 7),
        _prop("change_kind", "변경 종류", "enum", 8,
              enum_options=_enum(("dimension", "치수"), ("placement", "배치"), ("topology", "위상"),
                                 ("material", "재료"), ("type", "교체"), ("count", "개수"),
                                 ("discretization", "이산화"), ("result", "결과"),
                                 ("load_path", "하중 경로"), ("consistency", "정합"),
                                 ("electrical", "전기"), ("none", "없음"))),
        _prop("evidence_grade", "근거 등급", "enum", 9,
              enum_options=_enum(("measured", "측정"), ("literature", "문헌·규격"),
                                 ("tool_predicted", "도구예측"), ("heuristic", "경험칙"))),
        _prop("precedent", "선례", "enum", 10,
              enum_options=_enum(("in_range", "코퍼스 범위 안"), ("out_of_range", "코퍼스 범위 밖"),
                                 ("none", "비교 불가"))),
        _prop("status", "상태", "enum", 11,
              enum_options=_enum(("open", "미결"), ("verified", "검증됨"), ("dismissed", "기각"),
                                 ("mitigated", "완화됨"), ("superseded", "대체됨"))),
        _prop("support", "지지", "number", 12),
        _prop("contested", "반박", "number", 13),
        _prop("subject_key", "대상 키", "text", 14),
        _prop("owner", "소유자", "text", 15),
        _prop("visibility", "공개 범위", "enum", 16, enum_options=_VISIBILITY),
        _prop("statement", "대표 진술", "longtext", 17, help="대표 finding claim 원문 ≤600"),
        _prop("portal_registry_key", "앱 등록부 키", "text", 18),
        _prop("opinion_record_id", "의견 레코드 id", "text", 19),
    ),
    "design_trait": (
        _prop("axis", "축", "text", 1),
        _prop("token", "토큰", "text", 2),
        _prop("vocab_version", "어휘 버전", "text", 3),
        _prop("status", "상태", "enum", 4,
              enum_options=_enum(("vocab", "통제 어휘"), ("proposed", "승격 후보"))),
    ),
}

# ---------------------------------------------------------------- 관계 12(plan §5.3.2, 전부 directed·비추이)
def _relation(slug: str, label: str, inverse_label: str, src: Sequence[str], dst: Sequence[str],
              sort_order: int, description: str, *, acyclic: bool = False) -> dict:
    return {"slug": slug, "label": label, "inverse_label": inverse_label,
            "directed": True, "transitive": False, "acyclic": acyclic,
            "src_axis_slugs": list(src), "dst_axis_slugs": list(dst),
            "sort_order": sort_order, "description": description}


RELATIONS: tuple[dict, ...] = (
    _relation("snapshot_of", "스냅샷 대상", "스냅샷", ["design_snapshot"], ["project"], 100,
              "스냅샷이 속한 과제."),
    _relation("derived_from", "파생 원본", "파생본", ["design_snapshot"], ["design_snapshot"], 101,
              "스냅샷 계보(재캡처·부분 갱신).", acyclic=True),
    _relation("diff_of", "비교 대상", "비교됨", ["design_diff"], ["design_snapshot"], 102,
              "design_diff 가 base/target 스냅샷을 가리킨다. 관계 속성 role 로 구분"),
    _relation("assesses", "심사 대상", "심사됨", ["assessment"],
              ["project", "design_snapshot", "design_diff"], 103,
              "좌석 판정이 가리키는 심사 대상."),
    _relation("assessed_by", "심사자", "심사함", ["assessment"], ["expert"], 104,
              "좌석 판정을 남긴 전문가."),
    _relation("raised_by", "제기 판정", "제기함", ["risk_finding"], ["assessment"], 105,
              "리스크 항목을 제기한 좌석 판정."),
    _relation("concerns", "대상", "관련 리스크", ["risk_finding"],
              ["part", "model", "failure_mode", "defect"], 106,
              "리스크 항목이 가리키는 기존 축(부품·모델·고장모드·결함)."),
    _relation("mitigated_by", "완화 diff", "완화함", ["risk_finding"], ["design_diff"], 107,
              "리스크 항목을 완화한 설계 변경."),
    _relation("verified_by", "검증 근거", "검증함", ["risk_finding"], ["incident", "test_run"], 108,
              "리스크 항목을 확증한 사고·시험 라벨."),
    _relation("refuted_by", "반증 근거", "반증함", ["risk_finding"], ["incident", "test_run"], 109,
              "리스크 항목을 반증한 사고·시험 라벨."),
    _relation("exhibits", "성격", "발현 과제", ["project", "design_snapshot"], ["design_trait"], 110,
              "과제·스냅샷이 보이는 정성 성격 태그."),
    _relation("revision_of", "후속 과제", "선행 과제", ["project"], ["project"], 111,
              "과제 계보(모델 축 supersedes/variant_of 와 별개)", acyclic=True),
)

_LABEL_PROPS = (
    _prop("label_id", "라벨 id", "text", 1),
    _prop("match_score", "일치 점수", "number", 2),
    _prop("source", "출처", "enum", 3,
          enum_options=_enum(("incident", "사고"), ("test_run", "시험"), ("voc", "VOC"),
                             ("sim", "해석"), ("expert_review", "전문가 검토"), ("manual", "수동"))),
)

REL_PROPS: dict[str, tuple[dict, ...]] = {
    "diff_of": (
        _prop("role", "역할", "enum", 1, required=True,
              enum_options=_enum(("base", "기준"), ("target", "대상"))),
    ),
    "verified_by": _LABEL_PROPS,
    "refuted_by": _LABEL_PROPS,
    "exhibits": (
        _prop("support", "지지 패널 수", "number", 1),
        _prop("origin", "유래", "enum", 2,
              enum_options=_enum(("auto", "자동"), ("seat", "좌석"), ("chair", "의장"))),
    ),
}

PLANNED_AXES = tuple(a["slug"] for a in AXES)
PLANNED_RELATIONS = tuple(r["slug"] for r in RELATIONS)

# drift 로 볼 정의 필드. 라벨·설명 중 설명은 산문이라 대조하지 않는다.
TYPE_FIELDS = ("label", "multi", "kind_class")
RELATION_FIELDS = ("label", "directed", "transitive", "acyclic", "src_axis_slugs", "dst_axis_slugs")
PROP_FIELDS = ("data_type", "required", "multi", "enum_options", "ref_type_slug")
_FIELD_DEFAULTS = {"multi": False, "required": False, "directed": True, "transitive": False,
                   "acyclic": False, "kind_class": "reference", "ref_type_slug": None}


class BootstrapError(RuntimeError):
    """RA 호출이 실패했다. 어떤 것도 되돌리지 않고 종료 코드 1 로 끝낸다."""


# ---------------------------------------------------------------- RA 관리 REST
class RaAdminRest:
    """`Authorization: Bearer <RA_ADMIN_PAT>` 로 RA 관리 REST 를 직접 부르는 최소 클라이언트.

    httpx.Client 를 주입받는다 — 테스트는 MockTransport 를 실은 Client 를 넣어 실 네트워크 없이 돈다.
    """

    def __init__(self, base: str, token: str, *, client: httpx.Client | None = None,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base = (base or "").rstrip("/")
        self.timeout = timeout
        self._token = token
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def get(self, path: str) -> Any:
        try:
            response = self._client.get(self.base + path, headers=self._headers(), timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise BootstrapError(f"GET {path} — {type(exc).__name__}: {exc}") from exc
        return self._data(response, "GET", path)

    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        try:
            response = self._client.post(self.base + path, headers=self._headers(),
                                         json=dict(payload), timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise BootstrapError(f"POST {path} — {type(exc).__name__}: {exc}") from exc
        return self._data(response, "POST", path)

    @staticmethod
    def _data(response: httpx.Response, method: str, path: str) -> Any:
        """RA 응답 봉투 `{success, data}` 에서 data 를 꺼낸다."""
        if response.status_code >= 400:
            raise BootstrapError(f"{method} {path} — HTTP {response.status_code}: {response.text[:300]}")
        try:
            body = response.json()
        except ValueError as exc:
            raise BootstrapError(f"{method} {path} — JSON 이 아닙니다: {response.text[:200]}") from exc
        if isinstance(body, Mapping) and "data" in body:
            return body["data"]
        return body

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def _items(data: Any) -> list[dict]:
    """`{items: [...]}` 또는 목록 그대로에서 dict 행만 뽑는다."""
    if isinstance(data, Mapping):
        data = data.get("items")
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, Mapping)]


def _norm(field: str, value: Any) -> Any:
    """대조용 정규화 — enum 은 값 집합, 축 제약은 정렬 목록으로 본다."""
    if field == "enum_options":
        return sorted(str(o.get("value") if isinstance(o, Mapping) else o) for o in value or [])
    if field in ("src_axis_slugs", "dst_axis_slugs"):
        return sorted(str(v) for v in value or [])
    return value


def _diff(kind: str, name: str, planned: Mapping[str, Any], actual: Mapping[str, Any],
          fields: Sequence[str]) -> list[dict]:
    """계획표와 실제 정의의 차이를 drift 줄로 만든다. 고치지 않는다 — 보고만 한다."""
    out = []
    for field in fields:
        want = _norm(field, planned.get(field, _FIELD_DEFAULTS.get(field)))
        got = _norm(field, actual.get(field, _FIELD_DEFAULTS.get(field)))
        if want != got:
            out.append({"kind": kind, "name": name, "field": field, "planned": want, "actual": got})
    return out


def survey(rest: RaAdminRest) -> dict:
    """현재 축·관계 목록을 읽는다(읽기만 한다)."""
    types = {str(row.get("slug")): row for row in _items(rest.get("/api/entity-types"))}
    relations = {str(row.get("slug")): row for row in _items(rest.get("/api/relation-types"))}
    return {"types": types, "relations": relations}


def fingerprint(existing: Mapping[str, Any]) -> str:
    """계획표 밖(기존 15축·17관계) 정의의 덤프 — `--apply` 전후를 비교해 무변경을 확인한다."""
    rows: list[list[Any]] = []
    for slug, row in sorted(existing["types"].items()):
        if slug in PLANNED_AXES:
            continue
        rows.append(["entity_type", slug] + [_norm(f, row.get(f)) for f in TYPE_FIELDS])
    for slug, row in sorted(existing["relations"].items()):
        if slug in PLANNED_RELATIONS:
            continue
        rows.append(["relation_type", slug] + [_norm(f, row.get(f)) for f in RELATION_FIELDS])
    return json.dumps(rows, ensure_ascii=False, sort_keys=True)


def build_plan(rest: RaAdminRest) -> tuple[dict, dict, dict, list[dict]]:
    """(현재 목록, 생성 후보, 건너뛴 수, drift) — 이 함수는 GET 만 부른다."""
    existing = survey(rest)
    todo: dict[str, list] = {"types": [], "props": [], "relations": [], "rel_props": []}
    skipped = {"types": 0, "props": 0, "relations": 0, "rel_props": 0}
    drift: list[dict] = []

    for axis in AXES:
        slug = axis["slug"]
        actual = existing["types"].get(slug)
        if actual is None:
            todo["types"].append(axis)
            todo["props"].extend({"axis": slug, "type_id": None, "prop": p} for p in PROPS.get(slug, ()))
            continue
        skipped["types"] += 1
        drift.extend(_diff("entity_type", slug, axis, actual, TYPE_FIELDS))
        type_id = actual.get("id")
        have = {str(p.get("key")): p for p in _items(rest.get(f"/api/entity-types/{type_id}/properties"))}
        for prop in PROPS.get(slug, ()):
            got = have.get(prop["key"])
            if got is None:
                todo["props"].append({"axis": slug, "type_id": type_id, "prop": prop})
            else:
                skipped["props"] += 1
                drift.extend(_diff("property", f"{slug}.{prop['key']}", prop, got, PROP_FIELDS))

    for relation in RELATIONS:
        slug = relation["slug"]
        actual = existing["relations"].get(slug)
        if actual is None:
            todo["relations"].append(relation)
            todo["rel_props"].extend({"relation": slug, "prop": p} for p in REL_PROPS.get(slug, ()))
            continue
        skipped["relations"] += 1
        drift.extend(_diff("relation_type", slug, relation, actual, RELATION_FIELDS))
        have = {str(p.get("key")): p for p in _items(rest.get(f"/api/relation-types/{slug}/properties"))}
        for prop in REL_PROPS.get(slug, ()):
            got = have.get(prop["key"])
            if got is None:
                todo["rel_props"].append({"relation": slug, "prop": prop})
            else:
                skipped["rel_props"] += 1
                drift.extend(_diff("relation_property", f"{slug}.{prop['key']}", prop, got, PROP_FIELDS))

    return existing, todo, skipped, drift


def apply_plan(rest: RaAdminRest, todo: Mapping[str, list]) -> dict:
    """축 → 축 속성 → 관계 종류 → 관계 속성 순서로 생성한다(관계가 축 slug 를 참조하므로 순서 고정)."""
    created = {"types": 0, "props": 0, "relations": 0, "rel_props": 0}
    new_ids: dict[str, Any] = {}
    for axis in todo["types"]:
        data = rest.post("/api/entity-types", axis)
        new_ids[axis["slug"]] = data.get("id") if isinstance(data, Mapping) else None
        created["types"] += 1
    for entry in todo["props"]:
        type_id = entry["type_id"] if entry["type_id"] is not None else new_ids.get(entry["axis"])
        if type_id is None:
            raise BootstrapError(f"축 {entry['axis']} 의 type_id 를 알 수 없어 속성을 만들 수 없습니다.")
        rest.post(f"/api/entity-types/{type_id}/properties", entry["prop"])
        created["props"] += 1
    for relation in todo["relations"]:
        rest.post("/api/relation-types", relation)
        created["relations"] += 1
    for entry in todo["rel_props"]:
        rest.post(f"/api/relation-types/{entry['relation']}/properties", entry["prop"])
        created["rel_props"] += 1
    return created


def report(mode: str, todo: Mapping[str, list], skipped: Mapping[str, int], drift: Sequence[dict],
           created: Mapping[str, int] | None, existing_unchanged: bool | None) -> dict:
    """`{created, skipped, drift}` 중심의 결과 JSON(plan §5.3.4 (5))."""
    return {
        "mode": mode,
        "created": dict(created or {"types": 0, "props": 0, "relations": 0, "rel_props": 0}),
        "candidates": {
            "types": [a["slug"] for a in todo["types"]],
            "props": [f"{e['axis']}.{e['prop']['key']}" for e in todo["props"]],
            "relations": [r["slug"] for r in todo["relations"]],
            "rel_props": [f"{e['relation']}.{e['prop']['key']}" for e in todo["rel_props"]],
        },
        "skipped": dict(skipped),
        "drift": list(drift),
        "existing_unchanged": existing_unchanged,
    }


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ReportArchive 온톨로지 부트스트랩(멱등, dry-run 기본) — plan §5.3.4")
    parser.add_argument("--base", default="", help="RA REST 오리진(예 https://ra.example.com)")
    parser.add_argument("--apply", action="store_true", help="실제로 생성한다(기본은 dry-run)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP 타임아웃(초)")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, client: httpx.Client | None = None) -> int:
    args = _parse_args(argv)
    token = (os.environ.get(CRED_ENV) or "").strip()
    if not token:
        print(f"자격이 없습니다 — env {CRED_ENV}(RA 시스템관리자 rat_ 토큰)를 설정하고 다시 실행하세요.\n"
              f"  {CRED_ENV}=rat_… python backend/scripts/bootstrap_ra_ontology.py --base <RA REST 오리진> [--apply]\n"
              "자격이 없으므로 RA 를 한 번도 부르지 않고 종료합니다.", file=sys.stderr)
        return 3
    if not args.base.strip():
        print("--base <RA REST 오리진> 이 필요합니다(예 --base https://ra.example.com).", file=sys.stderr)
        return 1

    rest = RaAdminRest(args.base.strip(), token, client=client, timeout=args.timeout)
    try:
        existing, todo, skipped, drift = build_plan(rest)
        created = None
        existing_unchanged = None
        if args.apply:
            created = apply_plan(rest, todo)
            existing_unchanged = fingerprint(survey(rest)) == fingerprint(existing)
            if not existing_unchanged:
                drift.append({"kind": "preexisting", "name": "entity_types+relation_types",
                              "field": "dump", "planned": "unchanged", "actual": "changed"})
    except BootstrapError as exc:
        print(f"부트스트랩 실패 — {exc}", file=sys.stderr)
        return 1
    finally:
        rest.close()

    print(json.dumps(report("apply" if args.apply else "dry-run", todo, skipped, drift,
                            created, existing_unchanged),
                     ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
