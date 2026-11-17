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

from app import evidence_bundle, identity, ledger, routes
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
