# identity.resolve_identity — X-Heax-User-* 헤더 유무에 따른 신원 해석(있으면 email, 없으면 anonymous)
from __future__ import annotations

import asyncio
import inspect

from starlette.requests import Request

from app.identity import resolve_identity

# HEAXHub authz.py 가 2xx 응답에 싣는 신원 헤더 이름(proxy_manager._IDENTITY_HEADERS 와 동일).
EMAIL_HEADER = "X-Heax-User-Email"
NAME_HEADER = "X-Heax-User-Name"


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "method": "GET", "path": "/api/meta", "headers": raw, "query_string": b""}
    return Request(scope)


def _resolve(request: Request) -> dict:
    result = resolve_identity(request)
    if inspect.iscoroutine(result):
        result = asyncio.run(result)
    return result


def test_shape_and_anonymous_without_headers():
    ident = _resolve(_request())
    assert set(ident) >= {"email", "groups", "source"}
    assert ident["source"] == "anonymous"
    assert ident["email"] in (None, "", "anonymous")
    assert isinstance(ident["groups"], list)


def test_email_from_header():
    ident = _resolve(_request({EMAIL_HEADER: "alice@example.com", NAME_HEADER: "Alice"}))
    assert ident["email"] == "alice@example.com"
    assert ident["source"] != "anonymous"
    assert isinstance(ident["groups"], list)


def test_empty_header_value_is_anonymous():
    """authz 는 익명 통과 시 헤더를 빈 값으로 복사한다 — 빈 값은 신원이 아니다."""
    ident = _resolve(_request({EMAIL_HEADER: "", NAME_HEADER: ""}))
    assert ident["source"] == "anonymous"
    assert ident["email"] in (None, "", "anonymous")


def test_meta_endpoint_reflects_headers(client):
    without = client.get("/api/meta").json()["identity"]
    assert without["email"] in (None, "", "anonymous")

    with_hdr = client.get("/api/meta", headers={EMAIL_HEADER: "bob@example.com"}).json()["identity"]
    assert with_hdr["email"] == "bob@example.com"
    assert isinstance(with_hdr["groups"], list)
