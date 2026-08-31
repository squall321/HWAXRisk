# REST 라우터 /api — /meta(앱·스키마·신원) · /meta/taxonomy · /meta/adapters · /meta/vocab (P0 읽기 전용)
from __future__ import annotations

from fastapi import APIRouter, Request

from app import config, taxonomy
from app.identity import resolve_identity
from app.risk_store import get_store

router = APIRouter(prefix="/api", tags=["meta"])

# P0 어댑터 현황 — 실연동은 P1(mcad)·P2(dyna), ecad 는 ODB 계약만(docs/odb-adapter-contract.md).
ADAPTERS: list[dict] = [
    {"kind": "mcad", "app": "heax-step_forge", "status": "planned"},
    {"kind": "dyna", "app": "heax-kooremapper_mcp", "status": "planned"},
    {"kind": "ecad", "app": None, "status": "contract_only"},
]


def meta_payload(request: Request | None = None) -> dict:
    """/meta 본문. request 가 없으면(MCP 도구) identity 를 뺀다."""
    settings = config.settings
    payload = {
        "app_id": settings.APP_ID,
        "version": settings.APP_VERSION,
        "data_dir": str(settings.DATA_DIR),
        "schema_version": get_store().schema_version(),
        "root_path": settings.ROOT_PATH,
    }
    if request is not None:
        payload["identity"] = resolve_identity(request)
    return payload


@router.get("/meta")
def get_meta(request: Request) -> dict:
    return meta_payload(request)


@router.get("/meta/taxonomy")
def get_taxonomy() -> dict:
    return taxonomy.load_taxonomy()


@router.get("/meta/adapters")
def get_adapters() -> list[dict]:
    return ADAPTERS


@router.get("/meta/vocab")
def get_vocab() -> dict:
    return {"asset_version": taxonomy.ASSET_VERSION, "assets": taxonomy.vocab_index()}
