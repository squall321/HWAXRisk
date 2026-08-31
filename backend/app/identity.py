# 인바운드 신원 해석 — X-Heax-User-Email 헤더를 미검증 표기(header_unverified)로 읽고, 없으면 anonymous(P0)
from __future__ import annotations

from fastapi import Request

# 헤더명은 HEAXHub backend/app/api/v1/authz.py 의 응답 헤더 그대로다(X-Heax-User-Email). authz 는 그룹 헤더를 내지 않으므로
# groups 는 항상 빈 목록이다.
# 주의(plan §5.2.1·§8.2.8): launch.mode=service 앱의 Caddy 라우트는 forward_auth 에 copy_identity 가 없어 이 헤더가 운영에서
# 도착하지 않고, 클라이언트가 보낸 같은 이름의 헤더는 제거되지 않고 통과한다. 그래서 값을 신뢰하지 않고 source 를
# 'header_unverified' 로 표기한다 — 정본 신원은 heax GET /api/v1/auth/me 되묻기이며 쓰기 API 가 생기는 P1 에서 넣는다.
HEADER_EMAIL = "X-Heax-User-Email"


def resolve_identity(request: Request) -> dict:
    """{email, groups, source} — source 는 'header_unverified'(미검증 헤더값) 또는 'anonymous'."""
    email = (request.headers.get(HEADER_EMAIL) or "").strip().lower()
    if not email:
        return {"email": None, "groups": [], "source": "anonymous"}
    return {"email": email, "groups": [], "source": "header_unverified"}
