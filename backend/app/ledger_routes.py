# 판정표 원장 REST(RK-01 ~ RK-06) — 대상의 구성원이 읽고 편집자 이상이 쓴다(routes 의 _target_reader · _target_writer 문을 그대로 지난다)
"""HWAXPortal docs/request-1117 · contracts.md. MCP 도구(app/mcp_server.py)도 같은 함수를 부른다 — 읽기는 `owner_sub` 를 받는 본체(MCP 는
`mcp_scope_owner` 가 고른 그 행의 주인), 쓰기는 `ident` 를 받는 라우트(MCP 는 entry 가 위임 신원을 확인한 뒤 같은 함수)다.

읽기는 그 대상의 과제 구성원(보기 이상 — 관리자는 열람 줄), 쓰기는 편집자 이상이다. 남 · 없는 대상은 같은 404 다(남 숨김). 감사 행
(rr_audit)은 남기지 않는다 — 화면 이력 탭의 이름표가 없는 행위는 코드만 보인다(test_audit_action_labels). 쓴 사람 · 시각은 원장 표의 created_by ·
created_at, 내보내기는 rr_ledger_exports 에 남는다.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app import config, evidence_bundle, identity, ledger, ledger_decision, ledger_numbers, provenance, ra_client, routes
from app.adapters import base as adapters_base
from app.errors import AppError

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- 문
def target_owner(target_key: str, owner_sub: str) -> str:
    """읽기 본체의 첫 줄 — 그 owner 의 대상이 아니면 404(routes._target_row 와 같은 답)."""
    routes._target_row(target_key, owner_sub)
    return owner_sub


def reader(target_key: str, ident: identity.Identity) -> str:
    """REST 읽기 — 구성원이면 대상 주인, 아니면 부른 사람(본체의 주인 검사가 404 를 낸다)."""
    return routes._target_reader(target_key, routes._require_user(ident), admin=routes._admin_reader(ident))


def writer(target_key: str, ident: identity.Identity) -> tuple[str, str]:
    """REST 쓰기 — (쓸 행의 주인, 쓴 사람). 보기는 403 role_insufficient, 남 · 없는 대상은 404 다."""
    owner = routes._target_writer(target_key, ident)
    routes._target_row(target_key, owner)
    return owner, routes._require_user(ident)


# ---------------------------------------------------------------- RK-01 판정표 — 틀 · 층 · 판 · 비교 · 내보내기
def overview_payload(target_key: str, *, owner_sub: str) -> dict:
    target_owner(target_key, owner_sub)
    return ledger.overview(routes.get_store(), target_key)


@router.get("/targets/{target_key}/ledger")
def get_ledger(target_key: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """대상의 판정표 원장 한눈 — 틀 판 · 판 목록 · 쓰지 않은 층 · 근거 묶음 · 숫자 원장 수 · 최근 내보내기."""
    return overview_payload(target_key, owner_sub=reader(target_key, ident))


@router.put("/targets/{target_key}/ledger/templates/{kind}")
def put_template(target_key: str, kind: str, body: dict = Body(...),
                 ident: identity.Identity = Depends(identity.current)) -> dict:
    """틀 한 판 적기(columns · facts · decision_map) — 같은 몸이면 지금 판(created false). 편집자 이상."""
    owner, actor = writer(target_key, ident)
    return ledger.put_template(routes.get_store(), target_key, owner, kind, body, actor=actor)


class LayerBody(BaseModel):
    name: str = Field(max_length=ledger.NAME_MAX)
    order: int
    rows: dict[str, dict[str, Any]]
    source_file: str | None = Field(default=None, max_length=ledger.SOURCE_FILE_MAX)


@router.post("/targets/{target_key}/ledger/layers")
def post_layer(target_key: str, body: LayerBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """덮어쓰기 층 하나 쌓기 — 판은 아직 바뀌지 않는다(판 짓기가 차례대로 덮는다). 편집자 이상."""
    owner, actor = writer(target_key, ident)
    return ledger.put_layer(routes.get_store(), target_key, owner, name=body.name, order=body.order, rows=body.rows,
                            source_file=body.source_file, actor=actor)


class BuildBody(BaseModel):
    base_version: int | None = None
    layers: list[str | dict[str, Any]] = Field(min_length=1, max_length=ledger.BUILD_LAYERS_MAX)
    colset_version: int | None = None


@router.post("/targets/{target_key}/ledger/versions")
def post_version(target_key: str, body: BuildBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """판 짓기 — 기준 판 위에 층들을 차례대로 덮는다(같은 입력이면 지은 판, created false). 편집자 이상."""
    owner, actor = writer(target_key, ident)
    return ledger.build_version(routes.get_store(), target_key, owner, base_version=body.base_version, layers=body.layers,
                                colset_version=body.colset_version, actor=actor)


def diff_payload(target_key: str, version: int, base: int | None = None, *, owner_sub: str) -> dict:
    target_owner(target_key, owner_sub)
    return ledger.diff_versions(routes.get_store(), target_key, version, base)


@router.get("/targets/{target_key}/ledger/versions/{version}/diff")
def get_version_diff(target_key: str, version: int, base: int | None = None,
                     ident: identity.Identity = Depends(identity.current)) -> dict:
    """판 비교 — 바뀐 코드 · 칸 · 앞뒤 값 · 든 · 빠진 코드 · 등급이 바뀐 코드 수. base 를 안 주면 그 판의 기준 판."""
    return diff_payload(target_key, version, base, owner_sub=reader(target_key, ident))


def export_page(target_key: str, version: int | None, fmt: str, *, owner_sub: str, offset: int = 0,
                limit: int | None = None) -> dict:
    """내보내기 한 쪽(기록 없이) — 표(머리 · 칸 · 코드 차례의 행)를 꼴대로 싣는다. offset · limit 은 행 쪽이다(MCP 가 와이어 상한 안에 나눈다 —
    쪽마다 보안 문구 · 칸 머리가 앞에 선다). `body` 는 기록의 지문을 잴 글이다(내보내기 기록 — note_page)."""
    target_owner(target_key, owner_sub)
    if fmt not in ledger.EXPORT_FORMATS:
        raise ledger._bad(f"fmt 는 {list(ledger.EXPORT_FORMATS)} 가운데 하나다 — {fmt!r}.")
    table = ledger.export_table(routes.get_store(), target_key, version)
    codes = list(table["rows"])
    start = max(0, int(offset or 0))
    page = codes[start:] if limit is None else codes[start:start + max(1, int(limit))]
    out: dict[str, Any] = {"notice": table["notice"], "target_key": target_key, "version": table["version"], "format": fmt,
                           "rows_n": len(codes), "offset": start, "page_rows": len(page)}
    if fmt == "csv":
        out["text"] = ledger.table_csv(table, page)
    else:
        out["table"] = ledger.table_json(table, page)
    if start + len(page) < len(codes):
        out["next_offset"] = start + len(page)
    return out


def note_page(out: dict, *, owner_sub: str, actor: str) -> dict:
    """내보낸 쪽 하나의 기록(rr_ledger_exports) — 답에 export_id 를 싣는다."""
    body = out["text"] if out["format"] == "csv" else ledger.canonical_json(out["table"])
    out["export_id"] = ledger.note_export(routes.get_store(), out["target_key"], owner_sub, version=out["version"], kind=out["format"],
                                          rows_n=out["page_rows"], body=body, actor=actor)
    return out


@router.get("/targets/{target_key}/ledger/versions/{version}/export")
def get_version_export(target_key: str, version: int, fmt: str = Query("csv"),
                       ident: identity.Identity = Depends(identity.current)) -> Any:
    """판 내보내기 — csv(첫 줄 보안 문구 · 둘째 줄 칸 머리) 또는 json(첫 칸 notice). 기록이 남는다."""
    owner = reader(target_key, ident)
    out = note_page(export_page(target_key, version, fmt, owner_sub=owner), owner_sub=owner, actor=routes._require_user(ident))
    if fmt == "csv":
        return PlainTextResponse(out["text"], media_type="text/csv; charset=utf-8",
                                 headers={"X-Export-Id": out["export_id"]})
    return out["table"]


# ---------------------------------------------------------------- RK-02 근거 묶음
class BundleBody(BaseModel):
    version: int | None = None
    codes: list[str] | None = Field(default=None, max_length=ledger.LAYER_ROWS_MAX)
    template: dict[str, Any]
    mask: bool = True


@router.post("/targets/{target_key}/evidence-bundles")
def post_evidence_bundle(target_key: str, body: BundleBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """근거 묶음 만들기(contracts §1) — 엔진 상한을 넘으면 422 와 까닭. 같은 입력이면 같은 묶음(created false). 편집자 이상."""
    owner, actor = writer(target_key, ident)
    return evidence_bundle.build(routes.get_store(), target_key, owner, version=body.version, codes=body.codes,
                                 template=body.template, mask=body.mask, actor=actor)


def _bundle_missing(bundle_id: str) -> AppError:
    return AppError("E404", f"근거 묶음을 찾을 수 없습니다 — {bundle_id}.", 404)


def bundle_payload(bundle_id: str, *, owner_sub: str) -> dict:
    """받기 본체 — 그 묶음의 대상이 owner 의 것이 아니면 없는 묶음과 같은 404 다."""
    row = evidence_bundle.bundle_row(routes.get_store(), bundle_id)
    if row is None:
        raise _bundle_missing(bundle_id)
    try:
        target_owner(row["target_key"], owner_sub)
    except AppError:
        raise _bundle_missing(bundle_id) from None
    return evidence_bundle.payload(row)


def bundle_target(bundle_id: str) -> str | None:
    row = evidence_bundle.bundle_row(routes.get_store(), bundle_id)
    return None if row is None else str(row["target_key"])


@router.get("/evidence-bundles/{bundle_id}")
def get_evidence_bundle(bundle_id: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """근거 묶음 받기 — {bundle_id, target_key, version, fingerprint, evidence}. evidence 를 고치지 않고 deliberate_start(evidence=…) 에 넣는다.
    그 대상의 구성원이 읽는다."""
    target_key = bundle_target(bundle_id)
    if target_key is None:
        raise _bundle_missing(bundle_id)
    return bundle_payload(bundle_id, owner_sub=reader(target_key, ident))


# ---------------------------------------------------------------- RK-06 원천의 출처 표지
def snapshot_provenance(snapshot_id: str) -> dict | None:
    """그 스냅샷의 과제 · 그 스냅샷의 출처 표지(문은 부르는 쪽 — 스냅샷을 읽은 사람에게만 붙인다)."""
    store = routes.get_store()
    row = store.query_one("SELECT project_id FROM rr_snapshots WHERE id = ?", (snapshot_id,))
    return None if row is None else provenance.project_provenance(store, row["project_id"], snapshot_id=snapshot_id)


def target_provenance(target_key: str) -> dict | None:
    """그 대상의 스냅샷(snap 은 그 스냅샷, diff 는 뒤 스냅샷)의 출처 표지(문은 부르는 쪽)."""
    return provenance.target_provenance(routes.get_store(), target_key)


def provenance_payload(project_id: str, snapshot_id: str | None = None, *, owner_sub: str) -> dict:
    """출처 표지 본체 — 그 owner 의 과제가 아니면 404, 준 스냅샷이 그 과제의 것이 아니면 404 다."""
    routes._project_row(project_id, owner_sub)
    store = routes.get_store()
    if snapshot_id is not None and store.query_one("SELECT 1 FROM rr_snapshots WHERE id = ? AND project_id = ?",
                                                   (snapshot_id, project_id)) is None:
        raise AppError("E404", f"스냅샷을 찾을 수 없습니다 — {snapshot_id}.", 404)
    return provenance.project_provenance(store, project_id, snapshot_id=snapshot_id)


@router.get("/projects/{project_id}/provenance")
def get_provenance(project_id: str, snapshot_id: str | None = None, ident: identity.Identity = Depends(identity.current)) -> dict:
    """원천의 출처 표지 — StepForge 과제 · 단계 신호 · 판, DynaForge 앱 키 · 환경 · 덱 · 요소 · 파트 수, ODB 보드 · revision 과 모르는 칸의 까닭 ·
    경고(이른 사본 · 빈 앱 키 · 옛 앱 키 · 운영 아닌 환경 · 요소 없는 파트 · 판 불일치). 그 과제의 구성원이 읽는다."""
    email = routes._require_user(ident)
    return provenance_payload(project_id, snapshot_id,
                              owner_sub=routes._project_reader(project_id, email, admin=routes._admin_reader(ident)))


# ---------------------------------------------------------------- RK-03 결정 → 판정표 층
DECISION_TEXT_MAX = 2_000_000


class DecisionBody(BaseModel):
    decision_json: dict[str, Any] | None = None
    decision_text: str | None = Field(default=None, max_length=DECISION_TEXT_MAX)
    job_id: str | None = Field(default=None, max_length=80)
    mapping: dict[str, Any] | None = None
    mapping_version: int | None = None
    version: int | None = None
    layer_name: str | None = Field(default=None, max_length=ledger.NAME_MAX)
    layer_order: int | None = None


def decision_pat_absent_error() -> AppError:
    return AppError("decision_pat_absent",
                    "그 사람의 포털 PAT 가 없거나 곧 끝나 심의 결과를 읽지 않습니다 — 심의 결과는 그 사람의 PAT 로만 읽습니다(박스 읽기 PAT 로 내려가지"
                    " 않습니다). 웹 설정 화면에서 포털 PAT 를 등록하거나 Claude 에서 hwax_risk 도구를 다시 불러 자동 등록한 뒤 다시 합니다.", 409,
                    detail={"fix": "portal_pat"})


def decision_channel(email: str) -> Any:
    """심의 결과를 읽는 게이트웨이 MCP 채널 — 부른 사람의 등록된 포털 PAT 하나(없으면 게이트웨이에 아무것도 보내기 전에 409)."""
    portal_pat = routes._person_pat(email)
    if portal_pat is None:
        raise decision_pat_absent_error()
    return ra_client.McpHttpClient(config.settings.gateway_mcp, headers={"Authorization": f"Bearer {portal_pat}"},
                                   timeout=adapters_base.source_timeout(config.settings))


@router.post("/targets/{target_key}/ledger/layers/from-decision")
def post_layer_from_decision(target_key: str, body: DecisionBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """결정 → 판정표 층(RK-03) — 결정 JSON · 결정문 글 · 심의 job_id 가운데 하나를 칸 대응으로 원장 칸에 옮겨 층 하나로 쌓는다(판은 아직 바뀌지
    않는다). 칸마다 filled · empty · conflict · no_source, 표결 · 합의 문장 대조가 답에 실린다. 편집자 이상 — job_id 는 부른 사람의 PAT 로 읽는다."""
    owner, actor = writer(target_key, ident)
    store = routes.get_store()
    ledger_decision.resolve_mapping(store, target_key, body.mapping, body.mapping_version)     # 대응이 없으면 게이트웨이를 부르기 전에 409
    decision, source = ledger_decision.read_decision(decision_json=body.decision_json, decision_text=body.decision_text,
                                                     job_id=body.job_id, channel_factory=lambda: decision_channel(actor))
    return ledger_decision.apply(store, target_key, owner, decision=decision, source=source, mapping=body.mapping,
                                 mapping_version=body.mapping_version, version=body.version, layer_name=body.layer_name,
                                 layer_order=body.layer_order, actor=actor)


# ---------------------------------------------------------------- RK-04 숫자 원장 · 금지값 점검
class NumbersBody(BaseModel):
    numbers: list[dict[str, Any]] = Field(default_factory=list, max_length=ledger_numbers.NUMBERS_MAX)
    forbidden: list[dict[str, Any]] = Field(default_factory=list, max_length=ledger_numbers.FORBIDDEN_MAX)


@router.put("/targets/{target_key}/numbers")
def put_numbers(target_key: str, body: NumbersBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """숫자 원장 · 금지값을 통째로 갈아 쓴다(같은 몸이면 changed false). 편집자 이상."""
    owner, actor = writer(target_key, ident)
    return ledger_numbers.put(routes.get_store(), target_key, owner, numbers=body.numbers, forbidden=body.forbidden, actor=actor)


class NumbersCheckBody(BaseModel):
    text: str | None = Field(default=None, max_length=ledger_numbers.TEXT_MAX)
    bundle_id: str | None = Field(default=None, max_length=80)
    code: str | None = Field(default=None, max_length=ledger.CODE_MAX)


def numbers_check_payload(target_key: str, body: NumbersCheckBody, *, owner_sub: str) -> dict:
    target_owner(target_key, owner_sub)
    return ledger_numbers.check(routes.get_store(), target_key, text=body.text, bundle_id=body.bundle_id, code=body.code)


@router.post("/targets/{target_key}/numbers/check")
def post_numbers_check(target_key: str, body: NumbersCheckBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """글 · 근거 묶음의 수를 숫자 원장 · 금지값과 대조한다(읽기 — 쓰지 않는다) — 원장에 없는 수 · 금지값 쓰임 · 단위 불일치 · 원장에 없는 id 꼴의
    수와 위치. 그 대상의 구성원이 부른다."""
    return numbers_check_payload(target_key, body, owner_sub=reader(target_key, ident))
