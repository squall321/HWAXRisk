# GET /api/me(익명·인증·box) · PUT /api/me/portal-pat — 익명 401, 422 4종(pat_email_mismatch·pat_audience·pat_expiring·pat_invalid), 정상 1행, null 삭제 0행 + 자격 Fernet 암복호·scopes/jti 계약(plan §8.2.7)
from __future__ import annotations

import base64
import dataclasses
import json
import time

import httpx
import pytest

from app import config, identity, routes
from app.errors import AppError
from app.risk_store import get_store

TOKEN = "heax_pat_test_fake_bob"
USER = {"id": 3, "email": "bob@example.com", "display_name": "Bob", "role": "member", "organization": "cae"}
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _fake_jwt(**claims) -> str:
    """서명은 가짜(포털 검증은 MockTransport 가 대신한다). 기본 클레임은 정상 등록 조건."""
    payload = {"sub": "u-bob", "email": "bob@example.com", "aud": ["mcp-gateway", "heax-hub"], "scope": "api",
               "scopes": ["read"], "jti": "fake-jti-bob", "groups": ["cae", "risk"],
               "exp": int(time.time()) + 30 * 86400, **claims}
    seg = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")  # noqa: E731
    return f"{seg({'alg': 'HS256', 'typ': 'JWT'})}.{seg(payload)}.fakesig"


def _rows() -> list[dict]:
    """_user_credentials 의 신원 열만 읽는다 — PAT 저장 열 이름(portal_pat_enc)은 store DDL 소관이라 여기서 묶지 않는다."""
    store = get_store()
    with store._lock:
        return [dict(r) for r in store.conn.execute(
            "SELECT owner_sub, pat_sub, pat_email, pat_groups_json, pat_exp, registered_at"
            " FROM _user_credentials").fetchall()]


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
    assert set(body["box"]) == {"hostname", "secrets_valid", "cred_key_present"}
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
    assert rows[0]["owner_sub"] == "bob@example.com"
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


# ---------------------------------------------------------------- 자격 암호화(plan §8.2.7) — identity.* 단위
FAKE_PAT = "fake.portal.pat-for-tests"


def _claims(**over) -> dict:
    return {"scopes": ["read"], "jti": "fake-jti-bob", **over}


def test_encrypt_decrypt_round_trip():
    blob = identity.encrypt_pat(FAKE_PAT)
    assert isinstance(blob, bytes) and FAKE_PAT.encode() not in blob  # 원문이 암호문에 남지 않는다.
    assert identity.decrypt_pat(blob) == FAKE_PAT
    assert identity.encrypt_pat(FAKE_PAT) != blob  # Fernet 은 매번 다른 IV 를 쓴다.
    assert identity.decrypt_pat(None) is None and identity.decrypt_pat(b"") is None
    assert identity.decrypt_pat(b"garbage") is None


def test_decrypt_after_key_rotation_is_none(monkeypatch):
    """키를 갈아 끼우면 옛 행은 복호 불가 — 호출자는 자격 (a) 로 강등한다(전원 재등록 정책)."""
    blob = identity.encrypt_pat(FAKE_PAT)
    other = base64.urlsafe_b64encode(b"rotated-fake-key-32bytes-padding")
    monkeypatch.setattr(config, "load_cred_key", lambda **kw: other)
    assert identity.decrypt_pat(blob) is None


@pytest.mark.parametrize("key", [None, b"not-a-fernet-key"], ids=["absent", "malformed"])
def test_encrypt_without_usable_key_is_cred_key_absent(monkeypatch, key):
    monkeypatch.setattr(config, "load_cred_key", lambda **kw: key)
    with pytest.raises(AppError) as excinfo:
        identity.encrypt_pat(FAKE_PAT)
    assert excinfo.value.code == "cred_key_absent" and excinfo.value.http_status == 422
    assert FAKE_PAT not in excinfo.value.message  # 오류 메시지에도 원문은 없다.
    assert identity.decrypt_pat(b"anything") is None


@pytest.mark.parametrize("scopes", [["read", "write"], ["write"], [], None, "read"],
                         ids=["read_write", "write", "empty", "missing", "not_a_list"])
def test_pat_scope_too_broad(scopes):
    with pytest.raises(AppError) as excinfo:
        identity.pat_scopes(_claims(scopes=scopes))
    assert excinfo.value.code == "pat_scope_too_broad" and excinfo.value.http_status == 422


def test_pat_scopes_read_only_passes():
    assert identity.pat_scopes(_claims()) == ["read"]
    assert identity.pat_scopes(_claims(scopes=[" READ "])) == ["read"]


def test_pat_scopes_gate_can_be_turned_off(monkeypatch):
    relaxed = dataclasses.replace(config.settings, risk_pat_require_read_only=False)
    monkeypatch.setattr(config, "settings", relaxed)
    assert identity.pat_scopes(_claims(scopes=["read", "write"])) == ["read", "write"]


def test_credential_record_carries_scopes_and_jti():
    rec = identity.credential_record(_claims(), FAKE_PAT)
    assert set(rec) == {"portal_pat_enc", "pat_scopes_json", "pat_jti", "scopes"}
    assert rec["scopes"] == ["read"] and json.loads(rec["pat_scopes_json"]) == ["read"]
    assert rec["pat_jti"] == "fake-jti-bob"
    assert identity.decrypt_pat(rec["portal_pat_enc"]) == FAKE_PAT
    assert FAKE_PAT not in json.dumps({k: str(v) for k, v in rec.items()})


def test_credential_record_requires_jti():
    with pytest.raises(AppError) as excinfo:
        identity.credential_record(_claims(jti=""), FAKE_PAT)
    assert excinfo.value.code == "pat_invalid" and excinfo.value.http_status == 422


def test_credential_pat_honors_revocation():
    blob = identity.encrypt_pat(FAKE_PAT)
    assert identity.credential_pat({"portal_pat_enc": blob, "revoked_at": None}) == FAKE_PAT
    assert identity.credential_pat({"portal_pat_enc": blob, "revoked_at": 1}) is None
    assert identity.credential_pat({"portal_pat_enc": None}) is None
    assert identity.credential_pat(None) is None
    # RiskStore.get_credential() 은 암호문을 portal_pat 키로 준다(경계 이름 바꾸기).
    assert identity.credential_pat({"portal_pat": blob.decode(), "revoked_at": None}) == FAKE_PAT


def test_box_mismatch_hides_credentials(client, wired, monkeypatch):
    from app.main import app

    client.put("/api/me/portal-pat", json={"pat": _fake_jwt()}, headers=AUTH)
    assert len(_rows()) == 1
    monkeypatch.setattr(app.state, "box_match", False)
    assert client.get("/api/me", headers=AUTH).json()["portal_pat"] is None


def test_an_unreachable_portal_is_not_reported_as_a_bad_pat(monkeypatch):
    """설정 문제를 토큰 문제로 번역하지 않는다(2026-09-30 실측에서 이것 때문에 막혀 있었다).

    `HWAXRISK_PORTAL_BASE` 기본값 `127.0.0.1:5283` 은 포털 vite 개발 포트라 실제 박스에서 죽어 있고
    오리진은 nginx `:8088` 이다. 둘을 같은 `pat_invalid` 로 접으면 화면이 "값을 다시 복사하거나 새로
    발급하세요" 로 번역해 사용자가 멀쩡한 토큰을 몇 번이고 다시 발급한다.
    """
    import httpx

    from app import routes

    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(routes, "_portal_transport", httpx.MockTransport(dead))

    with pytest.raises(AppError) as exc:
        routes._verify_with_portal("pat-value")

    assert exc.value.code == "portal_unreachable", "닿지 못한 것을 PAT 탓으로 적었다"
    assert exc.value.http_status == 502, "502 여야 한다 — 422 는 '입력이 잘못됐다' 는 뜻이다"
    assert "HWAXRISK_PORTAL_BASE" in exc.value.message, "고칠 곳을 가리키지 않는다"


def test_a_portal_that_rejects_the_pat_still_reports_pat_invalid(monkeypatch):
    """포털이 실제로 거부한 경우는 그대로 `pat_invalid` 다 — 구분이 반대로 뭉개지지 않게 함께 고정한다."""
    import httpx

    from app import routes

    monkeypatch.setattr(routes, "_portal_transport",
                        httpx.MockTransport(lambda r: httpx.Response(401, json={"detail": "no"})))

    with pytest.raises(AppError) as exc:
        routes._verify_with_portal("pat-value")

    assert (exc.value.code, exc.value.http_status) == ("pat_invalid", 422)
