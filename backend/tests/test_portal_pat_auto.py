# 포털 PAT 자동 등록(리스크 앱 사람 자격 R1) — GET /api/me 의 portal_pat.auto · 스위치 · 단언의 portal_pat_wanted 조건 · 게이트웨이 전용 POST /api/auth/portal-pat 의 문(시크릿·위임 헤더·이메일·scopes)과 기록
from __future__ import annotations

import base64
import dataclasses
import json
import logging
import time

import httpx
import pytest

from app import config, identity, main, routes
from app.common import now_epoch
from app.risk_store import get_store

TOKEN = "heax_pat_test_fake_erin"
EMAIL = "erin@example.com"
USER = {"id": 9, "email": EMAIL, "display_name": "Erin", "role": "member", "organization": "cae"}
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SECRET = "portal-pat-test-gateway-secret"
GW = {"X-Heax-Gateway-Secret": SECRET, "X-Hwax-Delegate-Email": EMAIL,
      # Caddy 가 덮어 싣는 허브 관리자 이메일 — 이 문은 이것을 읽지 않는다.
      "X-Heax-User-Email": "hub-admin@example.com", "X-Heax-Client": "hwax-mcp-gateway"}


def _jwt(**claims) -> str:
    """서명은 가짜다(포털 확인은 MockTransport 가 대신한다). 기본 클레임은 게이트웨이 교환이 주는 정상 PAT."""
    payload = {"sub": "u-erin", "email": EMAIL, "aud": ["mcp-gateway"], "scope": "api", "scopes": ["read"],
               "jti": "jti-erin-1", "groups": ["cae"], "exp": int(time.time()) + 90 * 86400, **claims}
    seg = lambda obj: base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")  # noqa: E731
    return f"{seg({'alg': 'RS256', 'typ': 'JWT'})}.{seg(payload)}.fakesig"


def _clean() -> None:
    store = get_store()
    store.delete_credential(EMAIL)
    store.execute("DELETE FROM _user_prefs WHERE owner_sub = ?", (EMAIL,))


@pytest.fixture
def box(monkeypatch):
    """heax 는 TOKEN 만 erin, 포털 /agent/conversations 는 portal_ok 에 따라 200/401, 게이트웨이 시크릿은 SECRET."""
    log = {"portal": [], "portal_ok": True}

    def heax(req: httpx.Request) -> httpx.Response:
        if req.headers.get("authorization") == f"Bearer {TOKEN}":
            return httpx.Response(200, json=USER)
        return httpx.Response(401)

    def portal(req: httpx.Request) -> httpx.Response:
        log["portal"].append(req.headers.get("authorization"))
        return httpx.Response(200 if log["portal_ok"] else 401, json={"conversations": []})

    monkeypatch.setattr(identity, "_transport", httpx.MockTransport(heax))
    monkeypatch.setattr(routes, "_portal_transport", httpx.MockTransport(portal))
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: SECRET)
    identity.reset_cache()
    _clean()
    yield log
    _clean()
    identity.reset_cache()


def _register(pat: str | None = None, *, exp_in: int = 90 * 86400) -> None:
    """등록된 행을 직접 만든다(화면·게이트웨이 길을 거치지 않는 상태 준비)."""
    get_store().upsert_credential(EMAIL, identity.encrypt_pat(pat or _jwt()).decode("ascii"), "u-erin", EMAIL, "[]",
                                  now_epoch() + exp_in, pat_scopes_json='["read"]', pat_jti="jti-erin-0")


def _auto(client) -> dict:
    return client.get("/api/me", headers=AUTH).json()["portal_pat"]["auto"]


def _mint(client, headers: dict) -> dict:
    r = client.post("/api/auth/sso", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _credential_rows() -> int:
    return get_store().query_one("SELECT COUNT(*) AS n FROM _user_credentials WHERE owner_sub = ?", (EMAIL,))["n"]


# ---------------------------------------------------------------- GET /api/me · 스위치 · PUT 의 source
def test_me_says_a_pat_is_due_when_none_is_registered(client, box):
    """등록이 없어도 portal_pat 은 객체다(registered false) — auto 가 '없음' 을 말해야 화면이 받아 등록한다."""
    pat = client.get("/api/me", headers=AUTH).json()["portal_pat"]
    assert pat["registered"] is False and pat["email"] is None
    assert pat["auto"] == {"enabled": True, "due": True, "due_reason": "absent", "last_source": None, "last_at": None,
                           "last_error": None, "last_error_at": None}
    # 익명에는 자동 칸이 없다(누구의 것도 아니다).
    assert client.get("/api/me").json()["portal_pat"] is None


@pytest.mark.parametrize("case,reason", [("fresh", None), ("expiring", "expiring"), ("revoked", "revoked"),
                                         ("undecryptable", "undecryptable")])
def test_due_reason_follows_the_registered_row(client, box, case, reason):
    renew = config.pat_renew_before_s()
    _register(exp_in=renew - 3600 if case == "expiring" else renew + 3600)
    if case == "revoked":
        get_store().execute("UPDATE _user_credentials SET revoked_at = 1 WHERE owner_sub = ?", (EMAIL,))
    if case == "undecryptable":
        get_store().execute("UPDATE _user_credentials SET portal_pat_enc = ? WHERE owner_sub = ?", (b"garbage", EMAIL))
    auto = _auto(client)
    assert (auto["due"], auto["due_reason"]) == (reason is not None, reason)


def test_the_switch_turns_auto_off_and_on(client, box):
    r = client.put("/api/me/portal-pat-auto", json={"enabled": False}, headers=AUTH)
    assert r.status_code == 200 and r.json()["enabled"] is False and r.json()["due_reason"] == "absent"
    assert _auto(client)["enabled"] is False
    assert client.put("/api/me/portal-pat-auto", json={"enabled": True}, headers=AUTH).json()["enabled"] is True
    assert client.put("/api/me/portal-pat-auto", json={"enabled": False}).status_code == 401


def test_put_records_the_source_and_clears_the_last_auto_error(client, box):
    get_store().note_portal_pat_error(EMAIL, "exchange-403: 원 PAT 가 기록되지 않았다")
    assert _auto(client)["last_error"].startswith("exchange-403")
    r = client.put("/api/me/portal-pat", json={"pat": _jwt(), "source": "web"}, headers=AUTH)
    assert r.status_code == 200, r.text
    auto = _auto(client)
    assert auto["last_source"] == "web" and abs(auto["last_at"] - now_epoch()) < 60
    assert auto["last_error"] is None and auto["last_error_at"] is None and auto["due"] is False
    # 출처를 주지 않으면 사람이 누른 것(manual)이다. 모르는 출처는 받지 않는다 — gateway-exchange 는 게이트웨이 문으로만 적힌다.
    client.put("/api/me/portal-pat", json={"pat": _jwt(jti="jti-erin-2")}, headers=AUTH)
    assert _auto(client)["last_source"] == "manual"
    r = client.put("/api/me/portal-pat", json={"pat": _jwt(), "source": "gateway-exchange"}, headers=AUTH)
    assert r.status_code == 422 and r.json()["error"]["code"] == "E100"
    assert _auto(client)["last_source"] == "manual"


# ---------------------------------------------------------------- 단언의 portal_pat_wanted
def test_a_delegated_mint_asks_for_a_pat_only_when_one_is_due(client, box):
    out = _mint(client, GW)
    assert out["portal_pat_wanted"] == {"name": "hwax-risk", "audiences": ["mcp-gateway"], "scopes": ["read"],
                                        "ttl_days": 90}
    assert set(out) == {"access_token", "token_type", "expires_in", "portal_pat_wanted"}
    _register(exp_in=config.pat_renew_before_s() + 3600)            # 갱신 문턱보다 넉넉하다 — 바라지 않는다
    assert "portal_pat_wanted" not in _mint(client, GW)


def test_a_mint_without_the_delegate_header_never_asks(client, box):
    """종전 헤더(X-Heax-User-Email — Caddy 가 허브 관리자로 덮는다)로 발급한 단언에는 어떤 경우에도 싣지 않는다."""
    folded = {k: v for k, v in GW.items() if k != "X-Hwax-Delegate-Email"}
    folded["X-Heax-User-Email"] = EMAIL                             # 그 이메일의 PAT 가 없어도(due) 바라지 않는다
    out = _mint(client, folded)
    assert "portal_pat_wanted" not in out and set(out) == {"access_token", "token_type", "expires_in"}


def test_auto_off_and_a_recent_failure_hold_the_ask(client, box):
    store = get_store()
    store.set_portal_pat_auto(EMAIL, False)
    assert "portal_pat_wanted" not in _mint(client, GW)
    store.set_portal_pat_auto(EMAIL, True)
    retry = config.pat_auto_retry_s()
    store.note_portal_pat_error(EMAIL, "exchange-502: 포털이 답하지 않았다", at=now_epoch() - retry + 600)
    assert "portal_pat_wanted" not in _mint(client, GW)              # 쉼 안이다
    store.note_portal_pat_error(EMAIL, "exchange-502: 포털이 답하지 않았다", at=now_epoch() - retry - 1)
    assert "portal_pat_wanted" in _mint(client, GW)                  # 쉼이 지났다


def test_an_expiring_pat_is_not_asked_for_again_right_after_an_auto_registration(client, box):
    """원 PAT 의 남은 수명이 문턱보다 짧으면 교환 PAT 도 그만큼이라 등록 직후에도 expiring 이다 — 단언마다 교환하지 않게 쉼을 둔다."""
    _register(exp_in=config.pat_renew_before_s() - 3600)
    store = get_store()
    store.note_portal_pat_registered(EMAIL, "gateway-exchange")
    assert "portal_pat_wanted" not in _mint(client, GW)
    store.note_portal_pat_registered(EMAIL, "gateway-exchange", at=now_epoch() - config.pat_auto_retry_s() - 1)
    assert "portal_pat_wanted" in _mint(client, GW)


# ---------------------------------------------------------------- POST /api/auth/portal-pat — 문
def test_portal_pat_is_404_without_a_secret_even_for_a_broken_body(client, box, monkeypatch):
    """시크릿이 없는 박스에서는 존재도 알리지 않는다 — 본문을 읽기 전에 문을 본다(깨진 본문도 404)."""
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: "")
    assert client.post("/api/auth/portal-pat", headers=GW, json={"pat": _jwt()}).status_code == 404
    assert client.post("/api/auth/portal-pat", headers=GW, content=b"{not json").status_code == 404
    assert _credential_rows() == 0 and box["portal"] == []


def test_portal_pat_refuses_a_wrong_secret(client, box):
    for headers in ({**GW, "X-Heax-Gateway-Secret": "wrong"}, {k: v for k, v in GW.items() if k != "X-Heax-Gateway-Secret"}):
        r = client.post("/api/auth/portal-pat", headers=headers, json={"pat": _jwt()})
        assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"
    r = client.post("/api/auth/portal-pat", headers=GW | {"X-Heax-Gateway-Secret": "wrong"}, json={"error": "x"})
    assert r.status_code == 401
    assert _credential_rows() == 0 and box["portal"] == [] and _auto(client)["last_error"] is None


def test_portal_pat_requires_the_delegate_header_and_never_falls_back_to_the_caddy_email(client, box):
    """X-Hwax-Delegate-Email 이 없으면 거절한다 — X-Heax-User-Email 은 Caddy 를 거치면 허브 관리자다. 그 이메일로도, 그 PAT 의
    이메일로도 등록하지 않는다."""
    headers = {k: v for k, v in GW.items() if k != "X-Hwax-Delegate-Email"}
    for user_email in ("hub-admin@example.com", EMAIL):
        r = client.post("/api/auth/portal-pat", headers={**headers, "X-Heax-User-Email": user_email}, json={"pat": _jwt()})
        assert r.status_code == 403 and r.json()["error"]["code"] == "delegation_required"
    r = client.post("/api/auth/portal-pat", headers={**GW, "X-Hwax-Delegate-Email": "not-an-email"}, json={"pat": _jwt()})
    assert r.status_code == 401 and r.json()["error"]["code"] == "bad_email"
    assert _credential_rows() == 0 and box["portal"] == []
    assert get_store().query_one("SELECT COUNT(*) AS n FROM _user_credentials WHERE owner_sub = ?",
                                 ("hub-admin@example.com",))["n"] == 0


def test_portal_pat_refuses_a_pat_of_another_person(client, box):
    r = client.post("/api/auth/portal-pat", headers=GW, json={"pat": _jwt(email="mallory@example.com")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "pat_email_mismatch"
    assert _credential_rows() == 0 and box["portal"] == []
    assert get_store().query_one("SELECT COUNT(*) AS n FROM _user_credentials WHERE owner_sub = ?",
                                 ("mallory@example.com",))["n"] == 0
    # 걸린 까닭은 마지막 자동 실패로 남는다 — 쉼이 걸려 단언마다 다시 바라지 않는다.
    assert _auto(client)["last_error"].startswith("register-pat_email_mismatch")
    assert "portal_pat_wanted" not in _mint(client, GW)


@pytest.mark.parametrize("scopes", [["read", "write"], ["write"], [], None], ids=["read_write", "write", "empty", "missing"])
def test_portal_pat_takes_read_only_scopes_even_when_the_box_relaxes_put(client, box, monkeypatch, scopes):
    """게이트웨이가 바란 것은 scopes ['read'] 다 — 웹 등록의 읽기 전용 스위치(HWAXRISK_PAT_REQUIRE_READ_ONLY)를 꺼 둔 박스에서도
    그보다 넓은 PAT 는 받지 않는다. 포털에 묻기 전에 거절한다."""
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_pat_require_read_only=False))
    claims = {"scopes": scopes} if scopes is not None else {}
    pat = _jwt(**claims)
    if scopes is None:
        payload = json.loads(base64.urlsafe_b64decode(pat.split(".")[1] + "=="))
        payload.pop("scopes")
        seg = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        pat = ".".join([pat.split(".")[0], seg, "fakesig"])
    r = client.post("/api/auth/portal-pat", headers=GW, json={"pat": pat})
    assert r.status_code == 422 and r.json()["error"]["code"] == "pat_scope_too_broad"
    assert _credential_rows() == 0 and box["portal"] == []


@pytest.mark.parametrize("claims,code", [({"aud": ["heax-hub"]}, "pat_audience"),
                                         ({"exp": int(time.time()) + 3600}, "pat_expiring")])
def test_portal_pat_runs_the_same_checks_as_put(client, box, claims, code):
    r = client.post("/api/auth/portal-pat", headers=GW, json={"pat": _jwt(**claims)})
    assert r.status_code == 422 and r.json()["error"]["code"] == code
    assert _credential_rows() == 0


def test_portal_pat_asks_the_portal_and_refuses_what_it_rejects(client, box):
    box["portal_ok"] = False
    pat = _jwt()
    r = client.post("/api/auth/portal-pat", headers=GW, json={"pat": pat})
    assert r.status_code == 422 and r.json()["error"]["code"] == "pat_invalid"
    assert box["portal"] == [f"Bearer {pat}"] and _credential_rows() == 0


def test_an_error_body_records_and_registers_nothing(client, box):
    long = "x" * 5000
    r = client.post("/api/auth/portal-pat", headers=GW, json={"error": "exchange-403", "message": long})
    assert r.status_code == 200 and r.json() == {"registered": False, "recorded": True, "email": EMAIL}
    assert _credential_rows() == 0 and box["portal"] == []
    auto = _auto(client)
    assert auto["last_error"].startswith("exchange-403: x") and len(auto["last_error"]) <= 500
    assert auto["due_reason"] == "absent" and auto["last_source"] is None
    # 둘 다 실었거나 둘 다 없으면 받지 않는다 — 오류와 함께 온 pat 도 등록하지 않는다.
    for body in ({"error": "x", "pat": _jwt()}, {}, [], "x"):
        r = client.post("/api/auth/portal-pat", headers=GW, json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "E100", body
    assert _credential_rows() == 0 and box["portal"] == []


def test_portal_pat_registers_the_delegated_persons_pat_without_logging_it(client, box, caplog):
    pat = _jwt()
    with caplog.at_level(logging.DEBUG):
        r = client.post("/api/auth/portal-pat", headers=GW, json={"pat": pat})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"registered": True, "email": EMAIL, "exp": body["exp"], "jti": "jti-erin-1"}
    assert box["portal"] == [f"Bearer {pat}"]
    assert pat not in caplog.text and pat.split(".")[1] not in caplog.text
    me = client.get("/api/me", headers=AUTH).json()["portal_pat"]
    assert me["registered"] is True and me["jti"] == "jti-erin-1" and me["decryptable"] is True
    assert me["auto"]["last_source"] == "gateway-exchange" and me["auto"]["due"] is False
    assert pat not in json.dumps(me)
    # 등록된 PAT 는 러너가 쓰는 그 자격이다.
    assert identity.credential_pat(get_store().get_credential(EMAIL)) == pat


def test_portal_pat_writes_nothing_for_someone_who_turned_auto_off(client, box):
    get_store().set_portal_pat_auto(EMAIL, False)
    for body in ({"pat": _jwt()}, {"error": "exchange-500", "message": "m"}):
        r = client.post("/api/auth/portal-pat", headers=GW, json=body)
        assert r.status_code == 409 and r.json()["error"]["code"] == "portal_pat_auto_off"
    assert _credential_rows() == 0 and box["portal"] == [] and _auto(client)["last_error"] is None


# ---------------------------------------------------------------- 손잡이·기동 검사
def test_the_renew_threshold_must_exceed_the_panel_credential_margin():
    """갱신 문턱이 패널 자격 여유 이하면 자동 등록이 '아직이다' 라고 보는 PAT 로 패널이 멈춘다 — 기동을 막고 손잡이를 말한다."""
    main.check_credential_chain(config.settings)                     # 기본값(7일 > 47400초)은 지난다
    margin = config.credential_margin_s(config.settings)
    assert config.pat_renew_before_s(config.settings) == 7 * 86400 > margin
    for renew in (margin, margin - 1):
        with pytest.raises(RuntimeError) as exc:
            main.check_credential_chain(dataclasses.replace(config.settings, risk_pat_renew_before_s=renew))
        assert f"HWAXRISK_PAT_RENEW_BEFORE_S {renew}초" in str(exc.value) and f"패널 자격 여유 {margin}초" in str(exc.value)
    main.check_credential_chain(dataclasses.replace(config.settings, risk_pat_renew_before_s=margin + 1))


def test_the_pat_knobs_are_read_like_the_other_box_knobs(tmp_path):
    (tmp_path / "knobs.env").write_text("HWAXRISK_PAT_AUTO_RETRY_S=600\nHWAXRISK_PAT_RENEW_BEFORE_S=172800\n", encoding="utf-8")
    loaded = config.load_settings(env={"HWAXRISK_DATA_DIR": str(tmp_path), "HWAXRISK_PAT_RENEW_BEFORE_S": "259200"})
    assert (loaded.risk_pat_renew_before_s, loaded.risk_pat_auto_retry_s) == (259200, 600)
    assert config.pat_knobs(loaded) == {"HWAXRISK_PAT_RENEW_BEFORE_S": {"value": 259200, "source": "env"},
                                        "HWAXRISK_PAT_AUTO_RETRY_S": {"value": 600, "source": "knobs.env"}}
    (tmp_path / "knobs.env").write_text("HWAXRISK_PAT_RENEW_BEFORE_S=0\n", encoding="utf-8")
    with pytest.raises(RuntimeError) as exc:
        config.load_settings(env={"HWAXRISK_DATA_DIR": str(tmp_path)})
    assert "HWAXRISK_PAT_RENEW_BEFORE_S" in str(exc.value)
