# REST 라우터 /api(plan §8.2.3 의 P0 몫) — GET /me · PUT /me/portal-pat · /meta/taxonomy · /meta/adapters · /meta/vocab, 신원은 Depends(identity.current)
from __future__ import annotations

import base64
import json
import time

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app import config, identity, taxonomy
from app.adapters.registry import list_adapters
from app.errors import AppError
from app.risk_store import get_store

router = APIRouter(prefix="/api")

PORTAL_TIMEOUT_S = 3.0
PAT_MIN_REMAINING_S = 86400
# 테스트가 httpx.MockTransport 를 꽂는 자리. None 이면 실제 네트워크.
_portal_transport: httpx.BaseTransport | None = None


class PortalPatBody(BaseModel):
    pat: str | None


def _pat_summary(row: dict | None) -> dict | None:
    """_user_credentials 행 → {registered, email, groups[], exp}. PAT 값은 싣지 않는다."""
    if row is None:
        return None
    try:
        groups = json.loads(row.get("pat_groups_json") or "[]")
    except ValueError:
        groups = []
    return {"registered": True, "email": row.get("pat_email"), "groups": groups, "exp": row.get("pat_exp")}


def _require_user(ident: identity.Identity) -> str:
    if ident.anonymous or not ident.email:
        raise AppError("unauthorized", "인증된 사용자만 호출할 수 있습니다.", 401)
    return ident.email


def _decode_jwt_payload(pat: str) -> dict:
    """서명 검증 없이 payload 만 디코드한다(서명 검증은 포털 몫 — 아래 /agent/conversations 호출이 대신한다)."""
    parts = pat.split(".")
    if len(parts) != 3:
        raise AppError("pat_invalid", "포털 PAT 형식이 아닙니다(JWT 3분절).", 422)
    try:
        segment = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(segment.encode("ascii")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError("pat_invalid", "포털 PAT payload 를 읽을 수 없습니다.", 422) from exc
    if not isinstance(payload, dict):
        raise AppError("pat_invalid", "포털 PAT payload 가 객체가 아닙니다.", 422)
    return payload


def _verify_with_portal(pat: str) -> None:
    url = f"{config.settings.portal_base.rstrip('/')}/agent/conversations?limit=1"
    try:
        with httpx.Client(transport=_portal_transport, timeout=PORTAL_TIMEOUT_S) as client:
            r = client.get(url, headers={"Authorization": f"Bearer {pat}"})
    except httpx.HTTPError as exc:
        raise AppError("pat_invalid", f"포털 검증 호출 실패({type(exc).__name__}).", 422) from exc
    if r.status_code != 200:
        raise AppError("pat_invalid", f"포털이 PAT 를 거부했습니다(HTTP {r.status_code}).", 422)


@router.get("/me")
def get_me(request: Request, ident: identity.Identity = Depends(identity.current)) -> dict:
    """{email, display_name, role, organization, anonymous, portal_pat|null, box{hostname, secrets_valid}}."""
    state = request.app.state
    payload = ident.to_dict()
    portal_pat = None
    # 박스 불일치(이관 직후)면 _user_credentials 전부 무효(plan §5.2.5 (5)).
    if not ident.anonymous and state.box_match:
        portal_pat = _pat_summary(get_store().get_credential(ident.email))
    payload["portal_pat"] = portal_pat
    payload["box"] = {"hostname": state.hostname, "secrets_valid": state.secrets_valid}
    return payload


@router.put("/me/portal-pat")
def put_portal_pat(body: PortalPatBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """사용자 포털 PAT 등록(러너 자격 (b)). null 은 삭제. 검증 순서 — email → aud/scope → exp → 포털 실호출."""
    owner_sub = _require_user(ident)
    store = get_store()
    if body.pat is None:
        store.delete_credential(owner_sub)
        return {"registered": False, "email": None, "groups": [], "exp": None}

    claims = _decode_jwt_payload(body.pat)
    email = str(claims.get("email") or "").strip().lower()
    if email != owner_sub:
        raise AppError("pat_email_mismatch", "PAT 의 email 이 현재 사용자와 다릅니다.", 422)
    aud = claims.get("aud")
    aud_list = aud if isinstance(aud, list) else [aud]
    if "mcp-gateway" not in aud_list or claims.get("scope") != "api":
        raise AppError("pat_audience", "PAT 의 aud 에 mcp-gateway 가 없거나 scope 가 api 가 아닙니다.", 422)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp - time.time() < PAT_MIN_REMAINING_S:
        raise AppError("pat_expiring", "PAT 만료까지 24 시간 미만입니다.", 422)
    _verify_with_portal(body.pat)

    groups = claims.get("groups") if isinstance(claims.get("groups"), list) else []
    store.upsert_credential(owner_sub, body.pat, claims.get("sub"), email, json.dumps(groups, ensure_ascii=False), int(exp))
    return {"registered": True, "email": email, "groups": groups, "exp": int(exp)}


@router.get("/meta/taxonomy")
def get_taxonomy() -> dict:
    return taxonomy.load_taxonomy()


@router.get("/meta/adapters")
def get_adapters() -> list[dict]:
    return list_adapters()


@router.get("/meta/vocab")
def get_vocab() -> dict:
    return {"asset_version": taxonomy.ASSET_VERSION, "assets": taxonomy.vocab_index()}
