# 인바운드 신원 해석 — Authorization Bearer(우선) 또는 쿠키 heax_access_token 을 heax GET /api/v1/auth/me 로 되묻고 sha256(token) TTL 60 s 캐시(plan §8.2.8) + 사용자 포털 PAT 자격 Fernet 암복호(plan §8.2.7)
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Request

from app import config
from app.errors import AppError

log = logging.getLogger("hwax_risk.identity")

COOKIE_NAME = "heax_access_token"
CACHE_TTL_S = 60.0
HEAX_TIMEOUT_S = 2.0

# X-Heax-User-* 헤더는 어느 경로에서도 읽지 않는다 — service 모드 Caddy 라우트는 copy_identity 가 없어 운영에서 도착하지 않고,
# 클라이언트가 위조해 보낸 동명 헤더는 그대로 통과한다(plan §8.2.8). 정본은 heax /auth/me 되묻기뿐이다.


@dataclass(frozen=True)
class Identity:
    """호출자 신원. source 는 토큰 출처(bearer | cookie | none), anonymous 는 토큰이 없거나 heax 가 거부한 경우."""

    email: str | None
    display_name: str | None
    role: str | None
    organization: str | None
    anonymous: bool
    source: str
    # 호출자가 가져온 heax 토큰 원문. 사용자가 시작한 캡처에서 소스 앱(StepForge) REST 를 **그 사람 자격으로**
    # 읽는 데만 쓴다 — 별도 서비스 PAT 없이도 REST 채널이 살아난다(plan §2.13.2 의 대안 경로).
    # to_dict 에서 빼서 응답·로그로 새지 않게 한다. 무인 배치(러너)는 이 값이 없어 서비스 PAT 를 쓴다.
    token: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("token", None)      # 신원 응답에 토큰을 절대 싣지 않는다.
        return d


ANONYMOUS = Identity(email=None, display_name=None, role=None, organization=None, anonymous=True, source="none",
                     token=None)

# sha256(token) → (만료 monotonic 시각, heax 사용자 dict 또는 None(401)). 연결 실패는 캐시하지 않는다.
_cache: dict[str, tuple[float, dict | None]] = {}
_cache_lock = threading.Lock()
# 테스트가 httpx.MockTransport 를 꽂는 자리. None 이면 실제 네트워크.
_transport: httpx.BaseTransport | None = None


def reset_cache() -> None:
    """캐시 비우기 — main.py lifespan ⑤ 가 기동 시 부른다."""
    with _cache_lock:
        _cache.clear()


def _token_from(request: Request) -> tuple[str | None, str]:
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer " and auth[7:].strip():
        return auth[7:].strip(), "bearer"
    cookie = (request.cookies.get(COOKIE_NAME) or "").strip()
    if cookie:
        return cookie, "cookie"
    return None, "none"


def _fetch_me(token: str) -> dict | None:
    """heax /api/v1/auth/me — 200 이면 사용자 dict, 401/403 이면 None, 그 밖(5xx·불통)은 예외."""
    url = f"{config.settings.heax_api.rstrip('/')}/api/v1/auth/me"
    with httpx.Client(transport=_transport, timeout=HEAX_TIMEOUT_S) as client:
        r = client.get(url, headers={"Authorization": f"Bearer {token}"})
    if r.status_code in (401, 403):
        return None
    r.raise_for_status()
    body = r.json()
    return body if isinstance(body, dict) else None


def _lookup(token: str) -> dict | None:
    key = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
    try:
        user = _fetch_me(token)
    except (httpx.HTTPError, ValueError) as exc:
        # 값(토큰)은 로그하지 않는다. 불통은 캐시하지 않고 이번 요청만 익명으로 본다.
        log.warning("heax /auth/me 되묻기 실패(%s): %s", type(exc).__name__, exc)
        return None
    with _cache_lock:
        _evict_locked()
        _cache[key] = (time.monotonic() + CACHE_TTL_S, user)
    return user


# 401 도 캐시하므로(user=None) 서로 다른 무효 Bearer 를 계속 보내면 항목이 무한히 쌓인다 — 상한을 둔다.
CACHE_MAX = 5000


def _evict_locked() -> None:
    """만료 항목을 걷어내고, 그래도 상한을 넘으면 가장 이른 만료부터 버린다(락은 호출자가 잡는다)."""
    if len(_cache) < CACHE_MAX:
        return
    now = time.monotonic()
    for key in [k for k, hit in _cache.items() if hit[0] <= now]:
        _cache.pop(key, None)
    if len(_cache) < CACHE_MAX:
        return
    for key, _hit in sorted(_cache.items(), key=lambda kv: kv[1][0])[:len(_cache) - CACHE_MAX + 1]:
        _cache.pop(key, None)


def current(request: Request) -> Identity:
    """FastAPI Depends 용 — Bearer > 쿠키 순으로 토큰을 잡아 heax 에 되묻는다. 토큰 없음·401·불통은 anonymous."""
    token, source = _token_from(request)
    if token is None:
        return ANONYMOUS
    user = _lookup(token)
    if not user or not user.get("email"):
        return ANONYMOUS
    return Identity(
        email=str(user["email"]).strip().lower(),
        display_name=user.get("display_name"),
        role=user.get("role"),
        organization=user.get("organization"),
        anonymous=False,
        source=source,
        token=token,
    )


# ---------------------------------------------------------------- 사용자 포털 PAT 자격 암호화(plan §8.2.7)
# _user_credentials.portal_pat_enc 는 Fernet(AES128-CBC+HMAC) 암호문이고 키는 $DATA_DIR/cred.key 뿐이다.
# 원문은 호출 직전 메모리에서만 복호하며 로그·응답·GET /me 어디에도 싣지 않는다(plan §5.1 원칙 10).
READ_ONLY_SCOPES = ["read"]


def _cipher(*, create: bool) -> Fernet | None:
    """cred.key 로 만든 Fernet. 키가 없거나 형식이 깨졌으면 None(키 값은 로그하지 않는다)."""
    key = config.load_cred_key(create=create)
    if not key:
        return None
    try:
        return Fernet(key)
    except (ValueError, TypeError):
        log.warning("cred.key 가 Fernet 키 형식이 아닙니다: %s", config.cred_key_path())
        return None


def encrypt_pat(pat: str) -> bytes:
    """PAT 원문 → portal_pat_enc BLOB. 키를 읽지도 만들지도 못하면 422 `cred_key_absent`(평문 폴백 없음)."""
    cipher = _cipher(create=True)
    if cipher is None:
        raise AppError("cred_key_absent", "자격 암호화 키(cred.key)가 없어 PAT 를 저장할 수 없습니다.", 422)
    return cipher.encrypt(pat.encode("utf-8"))


def decrypt_pat(blob: bytes | str | None) -> str | None:
    """portal_pat_enc → PAT 원문. 키 없음·키 교체·손상은 None 이고 호출자는 자격 (a) 로 강등한다(plan §8.2.7)."""
    if not blob:
        return None
    cipher = _cipher(create=False)
    if cipher is None:
        return None
    raw = blob.encode("utf-8") if isinstance(blob, str) else bytes(blob)
    try:
        return cipher.decrypt(raw).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError):
        log.warning("저장된 PAT 를 복호할 수 없습니다(키 교체 또는 손상).")
        return None


def pat_scopes(claims: Mapping[str, Any]) -> list[str]:
    """PAT 클레임의 scopes 를 정규화한다. `risk_pat_require_read_only` 면 `['read']` 만 통과(422 `pat_scope_too_broad`).

    이 검사는 **발급 메타데이터 확인이고 런타임 강제가 아니다** — 포털도 게이트웨이도 요청 경로에서 scopes 를
    보지 않으므로 `scopes:['read']` PAT 로도 쓰기 도구가 열린다(plan §5.1 원칙 10 의 '집행될 때만 참' 단서).
    근본 해결은 포털·게이트웨이의 scopes 강제이고 plan §10 #17 ② 결정 사항이다.
    """
    raw = claims.get("scopes")
    scopes = [str(s).strip().lower() for s in raw if str(s).strip()] if isinstance(raw, list) else []
    if config.settings.risk_pat_require_read_only and scopes != READ_ONLY_SCOPES:
        raise AppError(
            "pat_scope_too_broad",
            "이 앱에는 scopes 가 ['read'] 인 PAT 만 등록할 수 있습니다(현재 %s)." % (scopes or "없음"),
            422,
        )
    return scopes


def credential_record(claims: Mapping[str, Any], pat: str) -> dict:
    """PUT /me/portal-pat 가 `_user_credentials` 에 넣을 값을 만든다 — scopes 검사 → jti 추출 → Fernet 암호화 순.

    반환 `{portal_pat_enc: bytes, pat_scopes_json: str, pat_jti: str, scopes: list[str]}` —
    `scopes`·`pat_jti` 는 응답에 실어도 되지만 PAT 원문은 어디에도 싣지 않는다.
    422 `pat_scope_too_broad` · 422 `pat_invalid`(jti 없음 — 폐기 대조 불가) · 422 `cred_key_absent`.
    """
    scopes = pat_scopes(claims)
    jti = str(claims.get("jti") or "").strip()
    if not jti:
        raise AppError("pat_invalid", "PAT 에 jti 클레임이 없어 폐기 대조를 할 수 없습니다.", 422)
    return {
        "portal_pat_enc": encrypt_pat(pat),
        "pat_scopes_json": json.dumps(scopes, ensure_ascii=False),
        "pat_jti": jti,
        "scopes": scopes,
    }


def credential_pat(row: Mapping[str, Any] | None) -> str | None:
    """`_user_credentials` 행에서 쓸 수 있는 PAT 원문을 꺼낸다 — 행 없음·`revoked_at` 표기·복호 실패는 None.

    러너·어댑터·로스터가 자격 (b) 를 잡는 유일한 경로다. None 이면 자격 (a)(앱 PAT)로 강등한다.
    암호문은 `RiskStore.get_credential()` 이 경계에서 `portal_pat` 로 이름을 바꿔 주므로 두 키를 다 받는다.
    """
    if not row or row.get("revoked_at"):
        return None
    return decrypt_pat(row.get("portal_pat_enc") or row.get("portal_pat"))
