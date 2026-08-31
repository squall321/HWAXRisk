# GET /api/me(익명·인증·box) · PUT /api/me/portal-pat — 익명 401, 422 4종(pat_email_mismatch·pat_audience·pat_expiring·pat_invalid), 정상 1행, null 삭제 0행
from __future__ import annotations

import base64
import json
import time

import httpx
import pytest

from app import identity, routes
from app.risk_store import get_store

TOKEN = "heax_pat_test_fake_bob"
USER = {"id": 3, "email": "bob@example.com", "display_name": "Bob", "role": "member", "organization": "cae"}
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _fake_jwt(**claims) -> str:
    """서명은 가짜(포털 검증은 MockTransport 가 대신한다). 기본 클레임은 정상 등록 조건."""
    payload = {"sub": "u-bob", "email": "bob@example.com", "aud": ["mcp-gateway", "heax-hub"], "scope": "api",
               "groups": ["cae", "risk"], "exp": int(time.time()) + 30 * 86400, **claims}
    seg = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")  # noqa: E731
    return f"{seg({'alg': 'HS256', 'typ': 'JWT'})}.{seg(payload)}.fakesig"


def _rows() -> list[dict]:
    store = get_store()
    with store._lock:
        return [dict(r) for r in store.conn.execute("SELECT * FROM _user_credentials").fetchall()]


@pytest.fixture
def wired(monkeypatch):
    """heax 는 TOKEN 만 200, 포털 /agent/conversations 는 portal_ok 에 따라 200/401. 호출 기록을 돌려준다."""
    log = {"heax": 0, "portal": [], "portal_ok": True}

    def heax(req: httpx.Request) -> httpx.Response:
        log["heax"] += 1
        if req.headers.get("authorization") == f"Bearer {TOKEN}":
            return httpx.Response(200, json=USER)
        return httpx.Response(401)

    def portal(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/agent/conversations" and req.url.params.get("limit") == "1"
        log["portal"].append(req.headers.get("authorization"))
        return httpx.Response(200 if log["portal_ok"] else 401, json={"conversations": []})

    monkeypatch.setattr(identity, "_transport", httpx.MockTransport(heax))
    monkeypatch.setattr(routes, "_portal_transport", httpx.MockTransport(portal))
    identity.reset_cache()
    get_store().delete_credential("bob@example.com")
    yield log
    get_store().delete_credential("bob@example.com")
    identity.reset_cache()


def _error(r) -> str:
    assert r.status_code == 422, r.text
    body = r.json()
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message"}
    return body["error"]["code"]


def test_me_anonymous(client, wired):
    body = client.get("/api/me").json()
    assert body["anonymous"] is True and body["email"] is None and body["source"] == "none"
    assert body["portal_pat"] is None
    assert set(body["box"]) == {"hostname", "secrets_valid"}
    assert isinstance(body["box"]["hostname"], str) and body["box"]["secrets_valid"] is False
    assert set(body) == {"email", "display_name", "role", "organization", "anonymous", "source", "portal_pat", "box"}


def test_me_authenticated_without_pat(client, wired):
    body = client.get("/api/me", headers=AUTH).json()
    assert body["email"] == "bob@example.com" and body["anonymous"] is False and body["source"] == "bearer"
    assert body["portal_pat"] is None


def test_put_anonymous_is_401(client, wired):
    r = client.put("/api/me/portal-pat", json={"pat": _fake_jwt()})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    assert wired["portal"] == []


def test_put_email_mismatch(client, wired):
    r = client.put("/api/me/portal-pat", json={"pat": _fake_jwt(email="carol@example.com")}, headers=AUTH)
    assert _error(r) == "pat_email_mismatch"


@pytest.mark.parametrize("claims", [{"aud": ["heax-hub"]}, {"aud": "portal"}, {"scope": "chat"}],
                         ids=["aud_missing_gateway", "aud_string_other", "scope_not_api"])
def test_put_audience(client, wired, claims):
    r = client.put("/api/me/portal-pat", json={"pat": _fake_jwt(**claims)}, headers=AUTH)
    assert _error(r) == "pat_audience"


def test_put_expiring(client, wired):
    r = client.put("/api/me/portal-pat", json={"pat": _fake_jwt(exp=int(time.time()) + 3600)}, headers=AUTH)
    assert _error(r) == "pat_expiring"
    assert wired["portal"] == []


def test_put_invalid_rejected_by_portal(client, wired):
    wired["portal_ok"] = False
    r = client.put("/api/me/portal-pat", json={"pat": _fake_jwt()}, headers=AUTH)
    assert _error(r) == "pat_invalid"
    assert len(wired["portal"]) == 1 and _rows() == []


def test_put_not_a_jwt(client, wired):
    r = client.put("/api/me/portal-pat", json={"pat": "not-a-jwt"}, headers=AUTH)
    assert _error(r) == "pat_invalid"


def test_register_then_delete(client, wired):
    pat = _fake_jwt()
    r = client.put("/api/me/portal-pat", json={"pat": pat}, headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["registered"] is True and body["email"] == "bob@example.com" and body["groups"] == ["cae", "risk"]
    assert isinstance(body["exp"], int)
    assert wired["portal"] == [f"Bearer {pat}"]

    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["owner_sub"] == "bob@example.com" and rows[0]["portal_pat"] == pat
    assert rows[0]["pat_sub"] == "u-bob" and json.loads(rows[0]["pat_groups_json"]) == ["cae", "risk"]

    me = client.get("/api/me", headers=AUTH).json()
    assert me["portal_pat"]["email"] == "bob@example.com" and me["portal_pat"]["registered"] is True
    assert pat not in json.dumps(me)  # PAT 값은 응답에 싣지 않는다.

    # 재등록은 UPSERT — 여전히 1행.
    client.put("/api/me/portal-pat", json={"pat": _fake_jwt(groups=["cae"])}, headers=AUTH)
    assert len(_rows()) == 1 and json.loads(_rows()[0]["pat_groups_json"]) == ["cae"]

    r = client.put("/api/me/portal-pat", json={"pat": None}, headers=AUTH)
    assert r.status_code == 200 and r.json() == {"registered": False, "email": None, "groups": [], "exp": None}
    assert _rows() == []
    assert client.get("/api/me", headers=AUTH).json()["portal_pat"] is None


def test_box_mismatch_hides_credentials(client, wired, monkeypatch):
    from app.main import app

    client.put("/api/me/portal-pat", json={"pat": _fake_jwt()}, headers=AUTH)
    assert len(_rows()) == 1
    monkeypatch.setattr(app.state, "box_match", False)
    assert client.get("/api/me", headers=AUTH).json()["portal_pat"] is None
