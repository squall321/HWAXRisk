# 인바운드 신원 해석 — Authorization Bearer(우선) 또는 쿠키 heax_access_token 을 heax GET /api/v1/auth/me 로 되묻고 sha256(token) TTL 60 s 캐시(plan §8.2.8)
from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import asdict, dataclass

import httpx
from fastapi import Request

from app import config

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

    def to_dict(self) -> dict:
        return asdict(self)


ANONYMOUS = Identity(email=None, display_name=None, role=None, organization=None, anonymous=True, source="none")

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
        _cache[key] = (time.monotonic() + CACHE_TTL_S, user)
    return user


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
    )
