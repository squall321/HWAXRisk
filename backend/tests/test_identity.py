# identity.current — Bearer→bearer · 쿠키→cookie · 위조 X-Heax-User-Email 무시 · 토큰 없음→anonymous · 같은 토큰 10회에 /auth/me 실호출 1회(MockTransport)
from __future__ import annotations

import httpx
import pytest
from starlette.requests import Request

from app import identity

FAKE_TOKEN = "heax_pat_test_fake_alice"
FAKE_USER = {"id": 7, "email": "Alice@Example.com", "display_name": "Alice", "role": "member", "organization": "cae"}


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "method": "GET", "path": "/api/me", "headers": raw, "query_string": b""}
    return Request(scope)


@pytest.fixture
def heax(monkeypatch):
    """heax /api/v1/auth/me 가짜 — 호출 횟수를 세고, Bearer 가 FAKE_TOKEN 이면 200, 아니면 401."""
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v1/auth/me"
        calls.append(req.headers.get("authorization", ""))
        if req.headers.get("authorization") == f"Bearer {FAKE_TOKEN}":
            return httpx.Response(200, json=FAKE_USER)
        return httpx.Response(401, json={"detail": "invalid token"})

    monkeypatch.setattr(identity, "_transport", httpx.MockTransport(handler))
    identity.reset_cache()
    yield calls
    identity.reset_cache()


def test_bearer_source(heax):
    ident = identity.current(_request({"Authorization": f"Bearer {FAKE_TOKEN}"}))
    assert ident.email == "alice@example.com" and ident.anonymous is False and ident.source == "bearer"
    assert ident.display_name == "Alice" and ident.role == "member" and ident.organization == "cae"
    assert set(ident.to_dict()) == {"email", "display_name", "role", "organization", "anonymous", "source"}


def test_cookie_source(heax):
    ident = identity.current(_request({"Cookie": f"{identity.COOKIE_NAME}={FAKE_TOKEN}"}))
    assert ident.email == "alice@example.com" and ident.source == "cookie"


def test_bearer_wins_over_cookie(heax):
    ident = identity.current(_request({"Authorization": f"Bearer {FAKE_TOKEN}",
                                       "Cookie": f"{identity.COOKIE_NAME}=heax_pat_test_other"}))
    assert ident.source == "bearer" and ident.email == "alice@example.com"


def test_forged_header_is_ignored(heax):
    forged = {"X-Heax-User-Email": "mallory@example.com", "X-Heax-User-Name": "Mallory"}
    assert identity.current(_request(forged)) == identity.ANONYMOUS
    ident = identity.current(_request({**forged, "Authorization": f"Bearer {FAKE_TOKEN}"}))
    assert ident.email == "alice@example.com"


def test_no_token_is_anonymous(heax):
    ident = identity.current(_request())
    assert ident.anonymous is True and ident.email is None and ident.source == "none"
    assert heax == []


def test_rejected_token_is_anonymous(heax):
    ident = identity.current(_request({"Authorization": "Bearer heax_pat_test_bogus"}))
    assert ident.anonymous is True and ident.source == "none"
    assert len(heax) == 1


def test_same_token_ten_calls_one_upstream_call(heax):
    for _ in range(10):
        ident = identity.current(_request({"Authorization": f"Bearer {FAKE_TOKEN}"}))
        assert ident.email == "alice@example.com"
    assert len(heax) == 1
    identity.reset_cache()
    identity.current(_request({"Authorization": f"Bearer {FAKE_TOKEN}"}))
    assert len(heax) == 2


def test_upstream_down_is_anonymous_and_not_cached(monkeypatch):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(identity, "_transport", httpx.MockTransport(handler))
    identity.reset_cache()
    for _ in range(2):
        assert identity.current(_request({"Authorization": f"Bearer {FAKE_TOKEN}"})) == identity.ANONYMOUS
    assert len(calls) == 2


def test_me_endpoint_uses_identity(client, heax):
    assert client.get("/api/me").json()["anonymous"] is True
    body = client.get("/api/me", headers={"Authorization": f"Bearer {FAKE_TOKEN}",
                                          "X-Heax-User-Email": "mallory@example.com"}).json()
    assert body["email"] == "alice@example.com" and body["source"] == "bearer"
