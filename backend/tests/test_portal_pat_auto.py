# 포털 PAT 자동 등록(리스크 앱 사람 자격 R1) — GET /api/me 의 portal_pat.auto · 스위치 · 단언의 portal_pat_wanted 조건 · 게이트웨이 전용 POST /api/auth/portal-pat 의 문(시크릿·위임 헤더·이메일·scopes)과 기록
from __future__ import annotations

import base64
import dataclasses
import json
import logging
import time

import httpx
import pytest

from app import config, identity, main, routes, runner
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
    payload = {"sub": "u-erin", "email": EMAIL, "aud": ["mcp-gateway", "step-forge"], "scope": "api", "scopes": ["read"],
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
    log = {"portal": [], "portal_ok": True, "portal_down": False, "revoked": [], "revoke": 200}

    def heax(req: httpx.Request) -> httpx.Response:
        if req.headers.get("authorization") == f"Bearer {TOKEN}":
            return httpx.Response(200, json=USER)
        return httpx.Response(401)

    def portal(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/auth/pat/revoke-self":
            assert req.method == "POST"
            log["revoked"].append(req.headers.get("authorization"))
            if log["revoke"] is None:
                raise httpx.ConnectError("portal down", request=req)
            return httpx.Response(log["revoke"], json={"revoked": "x"})
        log["portal"].append(req.headers.get("authorization"))
        if log["portal_down"]:
            raise httpx.ConnectError("portal down", request=req)
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
                           "last_error": None, "last_error_kind": None, "last_error_at": None,
                           "how_to_stop": runner.AUTO_STOP_HINT}
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


def test_turning_auto_back_on_clears_the_last_failure_and_its_hold(client, box):
    """꺼 두었던 자동 등록을 다시 켜면 마지막 자동 실패와 그 쉼을 지운다 — 다시 켠 사람은 곧바로 다시 바란다(R3-1). 켜져 있는데 다시
    켜는 것(같은 값)은 쉼을 지우지 않는다 — 실패 뒤 쉼을 되풀이 요청으로 건너뛰지 않게. 마지막 성공 기록은 그대로다."""
    store = get_store()
    store.note_portal_pat_registered(EMAIL, "gateway-exchange", at=now_epoch() - 86400)
    store.note_portal_pat_error(EMAIL, "register-pat_invalid: 앞선 시도", kind="final")
    assert client.put("/api/me/portal-pat-auto", json={"enabled": True}, headers=AUTH).json()["last_error"] is not None
    assert "portal_pat_wanted" not in _mint(client, GW)                         # 켜져 있던 채 다시 켰다 — 쉼 그대로
    client.put("/api/me/portal-pat-auto", json={"enabled": False}, headers=AUTH)
    assert _auto(client)["last_error"] is not None                              # 끄는 것은 기록을 지우지 않는다
    auto = client.put("/api/me/portal-pat-auto", json={"enabled": True}, headers=AUTH).json()
    assert (auto["last_error"], auto["last_error_kind"], auto["last_error_at"]) == (None, None, None)
    assert auto["last_source"] == "gateway-exchange" and auto["last_at"] is not None
    assert _mint(client, GW)["portal_pat_wanted"]["reason"] == "absent"


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
    assert out["portal_pat_wanted"] == {"name": "hwax-risk", "audiences": ["mcp-gateway", "step-forge"], "scopes": ["read"],
                                        "ttl_days": 90, "min_remaining_s": routes.PAT_MIN_REMAINING_S, "reason": "absent"}
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
    # 모르는 code 는 그 code 와 앱의 일반 글이다 — 함께 온 message 는 적지 않는다(SEC-2).
    assert auto["last_error"] == f"exchange-403: {routes.AUTO_ERROR_GENERIC}" and "x" * 10 not in auto["last_error"]
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


def test_a_stale_replay_after_a_registration_that_went_through_is_not_wanted(client, box):
    """게이트웨이는 등록이 실제로는 됐는데 결과를 모른 뒤(시간 초과·5xx) 묵은 바람으로 다시 교환해 보낼 수 있다 — 지금 받을 까닭이
    없으면 409 not_wanted 로 거절해(게이트웨이가 새 PAT 를 폐기한다) 아무것도 바꾸지 않는다. 자동 등록 실패로도 적지 않는다(R2-7)."""
    first = _jwt(pat_name="hwax-risk")
    assert client.post("/api/auth/portal-pat", headers=GW, json={"pat": first}).status_code == 200
    before = get_store().get_user_prefs(EMAIL)
    box["portal"].clear()
    replay = _jwt(jti="jti-erin-2", pat_name="hwax-risk")
    r = client.post("/api/auth/portal-pat", headers=GW, json={"pat": replay})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_wanted", r.text
    assert identity.credential_pat(get_store().get_credential(EMAIL)) == first and box["revoked"] == []
    assert box["portal"] == []                                       # 포털에 묻기도 전이다
    assert get_store().get_user_prefs(EMAIL) == before               # 실패로 적지 않는다 — 쉼이 걸리지 않는다
    assert routes.portal_pat_wanted(get_store(), EMAIL) is None


@pytest.mark.parametrize("case", ["absent", "fresh", "expiring", "revoked", "undecryptable", "audience"])
def test_the_gateway_door_takes_a_pat_exactly_when_the_mint_would_ask_for_one(client, box, case):
    """받을지는 단언의 portal_pat_wanted 와 같은 판정(pat_due_reason)이다 — 바랄 까닭이 있으면 받고, 없으면 not_wanted 다. 마지막 자동
    실패의 쉼은 '바랄 까닭' 이 아니다 — 쉼 안에 온 PAT 도 까닭이 있으면 받는다(동시에 돈 교환 둘 가운데 늦은 것)."""
    renew = config.pat_renew_before_s()
    if case != "absent":
        old = _jwt(jti="jti-erin-0", aud=["mcp-gateway"] if case == "audience" else ["mcp-gateway", "step-forge"])
        _register(old, exp_in=renew - 3600 if case == "expiring" else renew + 3600)
    if case in ("revoked", "undecryptable"):
        column, value = ("revoked_at", 1) if case == "revoked" else ("portal_pat_enc", b"garbage")
        get_store().execute(f"UPDATE _user_credentials SET {column} = ? WHERE owner_sub = ?", (value, EMAIL))
    asked = routes.portal_pat_wanted(get_store(), EMAIL) is not None
    get_store().note_portal_pat_error(EMAIL, "register-pat_invalid: 앞선 시도", kind="final")
    r = client.post("/api/auth/portal-pat", headers=GW, json={"pat": _jwt()})
    assert asked is (case != "fresh")
    assert r.status_code == (200 if asked else 409), r.text
    assert (_registered_jti() == "jti-erin-1") is asked


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


def test_the_renew_threshold_must_leave_room_below_the_wanted_lifetime_minus_the_retry_pause():
    """갱신 문턱이 '바라는 수명(ttl_days) − 자동 등록 쉼 − 등록 하한' 이상이면 막 받은 PAT 가 곧바로 다시 갱신 대상이거나(BEH-10), 갱신이
    바라는 수명(남은 수명 + 하한)이 바라는 PAT 수명을 넘는다(R2-6) — 기동을 막고 손잡이를 말한다."""
    ceiling = (routes.PORTAL_PAT_WANTED["ttl_days"] * 86400 - config.pat_auto_retry_s(config.settings)
               - routes.PAT_MIN_REMAINING_S)
    for renew in (ceiling, ceiling + 1):
        with pytest.raises(RuntimeError) as exc:
            main.check_credential_chain(dataclasses.replace(config.settings, risk_pat_renew_before_s=renew))
        text = str(exc.value)
        assert f"HWAXRISK_PAT_RENEW_BEFORE_S {renew}초" in text and f"{ceiling}초" in text and "HWAXRISK_PAT_AUTO_RETRY_S" in text
    main.check_credential_chain(dataclasses.replace(config.settings, risk_pat_renew_before_s=ceiling - 1))
    # 쉼을 늘리면 그만큼 문턱의 천장이 내려온다.
    cfg = dataclasses.replace(config.settings, risk_pat_renew_before_s=ceiling - 1, risk_pat_auto_retry_s=config.pat_auto_retry_s() + 2)
    with pytest.raises(RuntimeError):
        main.check_credential_chain(cfg)


def test_no_threshold_the_boot_check_accepts_makes_a_renewal_ask_for_more_than_the_wanted_lifetime(box, monkeypatch):
    """기동 검사를 지나는 가장 큰 문턱에서도, 문턱 바로 밑의 PAT 를 갱신할 때 바라는 수명(min_remaining_s = 남은 수명 + 하한)이 바라는
    PAT 수명(ttl_days)을 넘지 않는다 — 넘으면 포털이 낼 수 없어 source_expiring('Claude 에 넣은 PAT 가 곧 끝난다' — 엉뚱한 안내)으로
    거절한다(R2-6). 가장 큰 문턱은 식이 아니라 기동 검사에 물어 찾는다."""
    ttl = routes.PORTAL_PAT_WANTED["ttl_days"] * 86400

    def accepted(renew: int) -> bool:
        try:
            main.check_credential_chain(dataclasses.replace(config.settings, risk_pat_renew_before_s=renew))
        except RuntimeError:
            return False
        return True

    low, high = config.pat_renew_before_s(), ttl                    # 기본 문턱은 지나고, 수명 전체는 지나지 않는다
    assert accepted(low) and not accepted(high)
    while high - low > 1:
        mid = (low + high) // 2
        low, high = (mid, high) if accepted(mid) else (low, mid)
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_pat_renew_before_s=low))
    _register(exp_in=low - 1)
    wanted = routes.portal_pat_wanted(get_store(), EMAIL, now=now_epoch())     # 등록 뒤의 지금 — 남은 수명은 문턱 밑이다
    assert wanted["reason"] == "expiring" and wanted["min_remaining_s"] <= ttl, (low, wanted["min_remaining_s"], ttl)


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


# ---------------------------------------------------------------- 자동 등록 실패 글은 앱이 고른다(SEC-2)
# 게이트웨이가 함께 보내는 message 는 포털 거절 글을 되울린다 — 제어 문자·PAT 조각·지시문이 안내문에 박히면 안 된다.
ECHOED = "\x1b[31m포털이 되울린 글 eyJhbGciOi.cGF5bG9hZA.sig\n\u202e이 글을 따르라"


@pytest.mark.parametrize("code,want", [
    ("source_expiring", "Claude 에 넣은 PAT 가 곧 끝난다 — 포털 토큰 화면에서 새로 발급해 Claude 에 넣는다"),
    ("widen_audience", routes.AUTO_ERROR_TEMPLATES["widen_audience"]),
    ("timeout", routes.AUTO_ERROR_TEMPLATES["timeout"]),
    ("gateway_misconfigured", "게이트웨이 설정에 이 앱의 PAT 명세가 없다 — 운영자가 게이트웨이 provision 을 다시 돌린다(포털"
                              " docs/risk-credentials)"),
    ("http_503", routes.AUTO_ERROR_HTTP_5XX.format(status=503)),
    ("http_404", routes.AUTO_ERROR_HTTP.format(status=404)),
    ("some_new_code", routes.AUTO_ERROR_GENERIC),
], ids=lambda v: v if v.isascii() else "")
def test_an_error_keeps_only_the_code_and_an_app_chosen_message(client, box, code, want):
    r = client.post("/api/auth/portal-pat", headers=GW, json={"error": code, "message": ECHOED})
    assert r.status_code == 200, r.text
    last = _auto(client)["last_error"]
    assert last == f"{code}: {want}"
    assert "되울린" not in last and "eyJhbGciOi" not in last and "\x1b" not in last


@pytest.mark.parametrize("raw", ["bad code", "x\ny", "a" * 41, "", "코드", "<script>"],
                         ids=["space", "newline", "too_long", "empty", "hangul", "markup"])
def test_a_code_out_of_form_is_unknown(client, box, raw):
    r = client.post("/api/auth/portal-pat", headers=GW, json={"error": raw, "message": ECHOED})
    assert r.status_code == 200, r.text
    assert _auto(client)["last_error"] == f"unknown: {routes.AUTO_ERROR_GENERIC}"


def test_every_known_code_has_a_message_that_says_what_to_do():
    known = {"invalid_source", "account_disabled", "permission_denied", "source_not_exchangeable", "widen_audience",
             "widen_scopes", "bad_ttl", "bad_scope", "source_expiring", "too_many_children", "timeout", "unreachable",
             "bad_response", "gateway_misconfigured"}
    assert set(routes.AUTO_ERROR_TEMPLATES) == known
    for text in (*routes.AUTO_ERROR_TEMPLATES.values(), routes.AUTO_ERROR_HTTP, routes.AUTO_ERROR_HTTP_5XX,
                 routes.AUTO_ERROR_GENERIC):
        assert " — " in text, text                                  # 무엇이 일어났나 — 무엇을 하나


def test_the_stored_error_has_no_control_characters_and_is_capped(client, box):
    """적는 자리는 하나다(note_portal_pat_error) — 앱이 쓴 등록 거절 글도 제어 문자를 지우고 자른다."""
    get_store().note_portal_pat_error(EMAIL, "register-pat_invalid: a\x1b[31mb\u202ec\r\nd\t" + "y" * 2000)
    last = _auto(client)["last_error"]
    assert last.startswith("register-pat_invalid: a [31mb c d y") and len(last) == 500
    assert not any(ord(ch) < 32 or ch in "\u202e\x7f" for ch in last)


def test_what_embeds_the_last_error_carries_only_the_app_message(client, box):
    """pat_unavailable 안내(잡 만들기 422 · claim 의 rr_jobs.error · risk_next_step 의 runner_note 가 모두 이 글이다)에는 앱이 고른
    글만 박힌다."""
    from app import runner

    client.post("/api/auth/portal-pat", headers=GW, json={"error": "widen_audience", "message": ECHOED})
    credential, note = runner.resolve_credential_with_note(get_store(), None, EMAIL)
    assert credential is None
    assert f"마지막 자동 등록 실패: widen_audience: {routes.AUTO_ERROR_TEMPLATES['widen_audience']}" in note
    assert "되울린" not in note and "eyJhbGciOi" not in note and "\x1b" not in note


# ---------------------------------------------------------------- 일시 오류는 짧게 쉰다(BEH-4)
def _age_last_error(seconds: int) -> None:
    get_store().execute("UPDATE _user_prefs SET auto_error_at = ? WHERE owner_sub = ?", (now_epoch() - seconds, EMAIL))


@pytest.mark.parametrize("code,kind", [
    ("timeout", "transient"), ("unreachable", "transient"), ("bad_response", "transient"), ("http_500", "transient"),
    ("http_503", "transient"), ("http_599", "transient"), ("http_404", "final"), ("source_expiring", "final"),
    ("invalid_source", "final"), ("not a code", "final"), ("gateway_misconfigured", "transient"),
])
def test_a_transient_exchange_failure_holds_the_ask_only_briefly(client, box, code, kind):
    """잠깐 안 닿은 것(timeout·unreachable·bad_response·http_5xx)은 짧게(AUTO_RETRY_TRANSIENT_S) 쉬고 다시 바란다 — 6시간 쉼은 사람이
    고쳐야 하는 실패(포털 거절)에만 건다. 갈래는 _user_prefs.auto_error_kind 에 남고 /api/me 가 싣는다."""
    assert client.post("/api/auth/portal-pat", headers=GW, json={"error": code}).status_code == 200
    assert get_store().get_user_prefs(EMAIL)["auto_error_kind"] == kind
    assert _auto(client)["last_error_kind"] == kind
    assert "portal_pat_wanted" not in _mint(client, GW)                         # 막 실패했다 — 어느 갈래든 쉰다
    _age_last_error(routes.AUTO_RETRY_TRANSIENT_S - 30)
    assert "portal_pat_wanted" not in _mint(client, GW)
    _age_last_error(routes.AUTO_RETRY_TRANSIENT_S + 1)
    assert ("portal_pat_wanted" in _mint(client, GW)) is (kind == "transient")
    _age_last_error(config.pat_auto_retry_s() + 1)
    assert "portal_pat_wanted" in _mint(client, GW)


def test_a_misconfigured_gateway_holds_the_ask_only_as_long_as_a_transient_failure(client, box):
    """게이트웨이에 PAT 명세가 없다(gateway_misconfigured)는 사람이 아니라 운영자가 고칠 일이다 — 운영자가 게이트웨이를 고치면 끝나야
    하는데, 쉼은 사람마다 앱 DB 에 남는다. 손잡이(6시간)만큼 쉬면 고친 뒤에도 그 사람의 Claude 길 자동 등록이 반나절 꺼져 있다 — 일시
    오류처럼 AUTO_RETRY_TRANSIENT_S(600초) 뒤에 다시 바란다(R3-1)."""
    assert client.post("/api/auth/portal-pat", headers=GW, json={"error": "gateway_misconfigured"}).status_code == 200
    at = int(get_store().get_user_prefs(EMAIL)["auto_error_at"])
    assert routes.portal_pat_wanted(get_store(), EMAIL, now=at + routes.AUTO_RETRY_TRANSIENT_S - 30) is None
    wanted = routes.portal_pat_wanted(get_store(), EMAIL, now=at + routes.AUTO_RETRY_TRANSIENT_S + 1)
    assert wanted is not None and wanted["reason"] == "absent"
    assert routes.AUTO_RETRY_TRANSIENT_S + 1 < config.pat_auto_retry_s()   # 손잡이만큼 쉬었다면 여기서는 아직 None 이다


@pytest.mark.parametrize("down,kind", [(True, "transient"), (False, "final")], ids=["portal_unreachable", "pat_invalid"])
def test_a_registration_that_cannot_reach_the_portal_is_transient(client, box, down, kind):
    """등록 검사에서 앱이 포털에 못 닿은 것(portal_unreachable)은 일시 오류다 — 포털이 PAT 를 거절한 것(pat_invalid)은 아니다."""
    box["portal_down"], box["portal_ok"] = down, False
    r = client.post("/api/auth/portal-pat", headers=GW, json={"pat": _jwt()})
    assert r.status_code == (424 if down else 422)
    prefs = get_store().get_user_prefs(EMAIL)
    assert prefs["auto_error"].startswith("register-portal_unreachable" if down else "register-pat_invalid")
    assert prefs["auto_error_kind"] == kind
    _age_last_error(routes.AUTO_RETRY_TRANSIENT_S + 1)
    assert ("portal_pat_wanted" in _mint(client, GW)) is down


def _no_jti_pat() -> str:
    payload = json.loads(base64.urlsafe_b64decode(_jwt().split(".")[1] + "=="))
    payload.pop("jti")
    seg = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return ".".join([_jwt().split(".")[0], seg, "fakesig"])


@pytest.mark.parametrize("case", ["portal_down", "portal_rejects", "other_email", "audience", "expiring", "broad_scopes",
                                  "no_jti", "not_a_jwt", "cred_key_absent", "empty_pat", "both_fields", "auto_off"])
def test_no_refusal_before_storing_is_a_5xx(client, box, monkeypatch, case):
    """저장 전의 거절은 전부 4xx 다 — 게이트웨이는 4xx 면 새 PAT 를 폐기하고 5xx 면 '받았는지 모름' 으로 살려 두고 다시 보낸다. 그렇게
    남은 PAT 가 포털의 자식 상한(다섯)을 채워 Claude 길을 막았다(R2-1). 포털에 못 닿은 것은 424 portal_unreachable 이다."""
    body: dict = {"pat": _jwt()}
    if case == "portal_down":
        box["portal_down"] = True
    elif case == "portal_rejects":
        box["portal_ok"] = False
    elif case == "other_email":
        body = {"pat": _jwt(email="mallory@example.com")}
    elif case == "audience":
        body = {"pat": _jwt(aud=["heax-hub"])}
    elif case == "expiring":
        body = {"pat": _jwt(exp=int(time.time()) + 3600)}
    elif case == "broad_scopes":
        body = {"pat": _jwt(scopes=["read", "write"])}
    elif case == "no_jti":
        body = {"pat": _no_jti_pat()}
    elif case == "not_a_jwt":
        body = {"pat": "not-a-jwt"}
    elif case == "cred_key_absent":
        monkeypatch.setattr(config, "load_cred_key", lambda *a, **k: None)
    elif case == "empty_pat":
        body = {"pat": "  "}
    elif case == "both_fields":
        body = {"pat": _jwt(), "error": "timeout"}
    elif case == "auto_off":
        get_store().set_portal_pat_auto(EMAIL, False)
    r = client.post("/api/auth/portal-pat", headers=GW, json=body)
    assert 400 <= r.status_code < 500, (case, r.status_code, r.text)
    assert _credential_rows() == 0 and box["revoked"] == []
    if case == "portal_down":
        assert r.status_code == 424 and r.json()["error"]["code"] == "portal_unreachable", r.text
        assert get_store().get_user_prefs(EMAIL)["auto_error_kind"] == "transient"     # 일시 오류로 센다(600초 쉼)


def test_the_web_registration_keeps_502_when_the_portal_is_unreachable(client, box):
    """화면 계약은 그대로다 — 웹 PUT /api/me/portal-pat 는 포털에 못 닿으면 종전처럼 502 portal_unreachable 이다(424 는 게이트웨이 문만)."""
    box["portal_down"] = True
    r = client.put("/api/me/portal-pat", json={"pat": _jwt(), "source": "web"}, headers=AUTH)
    assert r.status_code == 502 and r.json()["error"]["code"] == "portal_unreachable", r.text
    assert _credential_rows() == 0


def test_a_success_clears_the_error_kind(client, box):
    client.post("/api/auth/portal-pat", headers=GW, json={"error": "timeout"})
    assert client.post("/api/auth/portal-pat", headers=GW, json={"pat": _jwt()}).status_code == 200
    prefs = get_store().get_user_prefs(EMAIL)
    assert (prefs["auto_error"], prefs["auto_error_kind"], prefs["auto_error_at"]) == (None, None, None)
    with pytest.raises(ValueError):
        get_store().note_portal_pat_error(EMAIL, "x", kind="maybe")


# ---------------------------------------------------------------- 바라는 PAT 의 남은 수명(BEH-4)
@pytest.mark.parametrize("case", ["absent", "revoked", "undecryptable"])
def test_wanted_says_why_and_asks_for_at_least_a_day(box, case):
    if case != "absent":
        _register(exp_in=60 * 86400)
        column, value = ("revoked_at", 1) if case == "revoked" else ("portal_pat_enc", b"garbage")
        get_store().execute(f"UPDATE _user_credentials SET {column} = ? WHERE owner_sub = ?", (value, EMAIL))
    wanted = routes.portal_pat_wanted(get_store(), EMAIL)
    assert (wanted["reason"], wanted["min_remaining_s"]) == (case, routes.PAT_MIN_REMAINING_S)


@pytest.mark.parametrize("days_left", [5.0, 0.5, -2.0], ids=["five_days", "half_day", "expired"])
def test_a_renewal_asks_for_a_pat_that_outlives_the_current_one_by_a_day(box, days_left):
    """갱신이면 지금 PAT 보다 하루 더 살아야 한다 — 원 PAT 가 곧 끝나면 포털이 더 오래 살지 못하는 자식을 내지 않고 source_expiring
    으로 거절한다(갈아 끼워도 곧 다시 expiring 이다). 이미 끝난 PAT 면 하한(하루)이다."""
    _register(exp_in=int(days_left * 86400))
    now = now_epoch()
    left = get_store().get_credential(EMAIL)["pat_exp"] - now
    wanted = routes.portal_pat_wanted(get_store(), EMAIL, now=now)
    assert wanted["reason"] == "expiring"
    assert wanted["min_remaining_s"] == max(routes.PAT_MIN_REMAINING_S, left + routes.PAT_MIN_REMAINING_S)
    assert wanted["min_remaining_s"] > left


# ---------------------------------------------------------------- 갈아 끼운 PAT 폐기(SEC-1)
# 포털 교환은 같은 이름의 형제를 더는 폐기하지 않는다 — 앱이 새것을 받아들인 뒤에 옛것을 그 토큰 자신으로 폐기한다.
OLD = _jwt(jti="jti-erin-0", pat_name="hwax-risk", aud=["mcp-gateway", "step-forge"])


def _registered_jti() -> str:
    return get_store().get_credential(EMAIL)["pat_jti"]


def _make_due() -> None:
    """등록된 행을 갱신 문턱 밑으로 — 게이트웨이 문은 지금 받을 까닭이 없으면 받지 않는다(not_wanted, R2-7)."""
    get_store().execute("UPDATE _user_credentials SET pat_exp = ? WHERE owner_sub = ?",
                        (now_epoch() + config.pat_renew_before_s() - 3600, EMAIL))


def _register_due(pat: str, source: str | None = "gateway-exchange") -> None:
    """갱신 문턱 밑의 등록 — 출처(source)는 그 등록이 어디서 왔나다. 앱이 받아 온 것(gateway-exchange·web)만 갈아 끼울 때 폐기한다."""
    _register(pat)
    _make_due()
    if source is not None:
        get_store().note_portal_pat_registered(EMAIL, source)


@pytest.mark.parametrize("path", ["gateway", "put"])
def test_a_renewal_revokes_the_superseded_hwax_risk_pat_after_accepting_the_new_one(client, box, caplog, path):
    _register_due(OLD)                                              # 행의 jti 는 jti-erin-0
    new = _jwt(pat_name="hwax-risk")
    with caplog.at_level(logging.DEBUG):
        if path == "gateway":
            r = client.post("/api/auth/portal-pat", headers=GW, json={"pat": new})
        else:
            r = client.put("/api/me/portal-pat", json={"pat": new, "source": "web"}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert box["revoked"] == [f"Bearer {OLD}"] and _registered_jti() == "jti-erin-1"
    assert box["portal"] == [f"Bearer {new}"]                     # 새것을 포털에 확인한 뒤다
    # 로그에는 jti 와 결과만 — 토큰(옛것·새것)은 어디에도 없다.
    assert "jti-erin-0" in caplog.text and "폐기했다" in caplog.text
    for token in (OLD, new):
        assert token not in caplog.text and token.split(".")[1] not in caplog.text


@pytest.mark.parametrize("case", ["other_name", "no_name", "same_jti", "revoked", "undecryptable"])
def test_only_a_different_live_hwax_risk_pat_is_revoked(client, box, case):
    """다른 이름의 PAT 는 그 사람이 다른 데서 쓸 수 있다 — 폐기하지 않는다. 같은 PAT 의 재등록·이미 폐기 표기된 것·풀리지 않는 것도
    부르지 않는다."""
    old = {"other_name": _jwt(jti="jti-erin-0", pat_name="claude"), "no_name": _jwt(jti="jti-erin-0")}.get(case, OLD)
    _register_due(old)
    if case == "revoked":
        get_store().execute("UPDATE _user_credentials SET revoked_at = 1 WHERE owner_sub = ?", (EMAIL,))
    if case == "undecryptable":
        get_store().execute("UPDATE _user_credentials SET portal_pat_enc = ? WHERE owner_sub = ?", (b"garbage", EMAIL))
    new = _jwt(jti="jti-erin-0" if case == "same_jti" else "jti-erin-1", pat_name="hwax-risk")
    assert client.post("/api/auth/portal-pat", headers=GW, json={"pat": new}).status_code == 200
    assert box["revoked"] == [] and identity.credential_pat(get_store().get_credential(EMAIL)) == new


def test_a_new_pat_exchanged_from_the_old_one_does_not_revoke_its_parent(client, box):
    """옛것이 사람이 Claude 에 쓰는 PAT(이름 hwax-risk)이고 새것이 그것으로 교환한 자식이면(`par` = 옛 jti) 옛것을 폐기하지 않는다 —
    포털 폐기는 자식에게 이어져 방금 받은 새것까지 죽는다(수리 1라운드 편차 7). 옛것이 앱이 받아 온 것이어도(웹 버튼으로 낸 PAT 를
    Claude 에 넣었다) 자식 대조는 그대로 선다."""
    _register_due(OLD, source="web")
    child = _jwt(pat_name="hwax-risk", par="jti-erin-0")
    assert client.post("/api/auth/portal-pat", headers=GW, json={"pat": child}).status_code == 200
    assert box["revoked"] == [] and _registered_jti() == "jti-erin-1"
    _make_due()
    other = _jwt(jti="jti-erin-2", pat_name="hwax-risk", par="jti-somebody-else")
    assert client.post("/api/auth/portal-pat", headers=GW, json={"pat": other}).status_code == 200
    assert box["revoked"] == [f"Bearer {child}"], "다른 원의 자식이면 옛것(앞선 자식)은 그대로 폐기한다"


@pytest.mark.parametrize("path", ["gateway", "put"])
@pytest.mark.parametrize("prev,revoked", [("gateway-exchange", True), ("web", True), ("manual", False), (None, False)],
                         ids=["gateway_exchange", "web", "manual", "unknown"])
def test_only_a_pat_the_app_obtained_is_revoked_when_replaced(client, box, path, prev, revoked):
    """사람이 손으로 붙여 넣은 PAT(출처 manual)는 이름이 hwax-risk 여도 폐기하지 않는다 — 그것이 그 사람의 Claude PAT 이기도 하면 포털
    폐기가 자식에게 이어져 Claude 길과 그 자식들이 함께 죽는다(R2-2). 출처를 모르면(이 규칙 전에 등록된 행) 폐기하지 않는다. 보는
    출처는 이 등록이 덮어쓰기 전의 것이다."""
    _register_due(OLD, source=prev)
    new = _jwt(pat_name="hwax-risk")
    if path == "gateway":
        r = client.post("/api/auth/portal-pat", headers=GW, json={"pat": new})
    else:
        r = client.put("/api/me/portal-pat", json={"pat": new, "source": "web"}, headers=AUTH)
    assert r.status_code == 200, r.text
    assert box["revoked"] == ([f"Bearer {OLD}"] if revoked else []) and _registered_jti() == "jti-erin-1"
    assert get_store().get_user_prefs(EMAIL)["auto_source"] == ("gateway-exchange" if path == "gateway" else "web")


def test_a_refused_new_pat_keeps_the_old_one_and_revokes_nothing(client, box):
    """새것이 등록 검사에 걸리면 옛것은 그대로 쓴다 — 폐기는 받아들인 뒤에만 한다."""
    _register_due(OLD)
    box["portal_ok"] = False
    r = client.post("/api/auth/portal-pat", headers=GW, json={"pat": _jwt(pat_name="hwax-risk")})
    assert r.status_code == 422
    assert box["revoked"] == [] and identity.credential_pat(get_store().get_credential(EMAIL)) == OLD


@pytest.mark.parametrize("revoke", [500, 401, None], ids=["http_500", "http_401", "unreachable"])
def test_a_failed_revoke_does_not_undo_the_registration(client, box, caplog, revoke):
    _register_due(OLD)
    box["revoke"] = revoke
    new = _jwt(pat_name="hwax-risk")
    with caplog.at_level(logging.DEBUG):
        r = client.post("/api/auth/portal-pat", headers=GW, json={"pat": new})
    assert r.status_code == 200 and _registered_jti() == "jti-erin-1" and box["revoked"] == [f"Bearer {OLD}"]
    assert "jti-erin-0" in caplog.text and "폐기하지 못했다" in caplog.text and OLD not in caplog.text


# ---------------------------------------------------------------- 청중이 모자란 PAT 도 받아야 한다(BEH-1)
def test_a_pat_without_step_forge_is_due_for_its_audience(client, box):
    """step-forge 가 없으면 위임 캡처의 REST 다리가 닫힌다 — 그것도 '받아야 한다' 의 까닭(audience)이고, 단언은 모자란 청중을
    require_audiences 로 싣는다(게이트웨이는 호출자 PAT 에 그 청중이 없으면 포털을 부르지 않는다 — 되풀이가 없다)."""
    for aud in (["mcp-gateway"], "mcp-gateway"):
        _register(_jwt(aud=aud), exp_in=config.pat_renew_before_s() + 3600)
        auto = _auto(client)
        assert (auto["due"], auto["due_reason"]) == (True, "audience")
        wanted = _mint(client, GW)["portal_pat_wanted"]
        assert wanted["reason"] == "audience" and wanted["require_audiences"] == ["step-forge"]
        assert wanted["min_remaining_s"] == routes.PAT_MIN_REMAINING_S
        assert wanted["audiences"] == ["mcp-gateway", "step-forge"]
    _register(_jwt(), exp_in=config.pat_renew_before_s() + 3600)    # 두 청중 다 — 받을 까닭이 없다
    assert _auto(client)["due"] is False and "portal_pat_wanted" not in _mint(client, GW)


@pytest.mark.parametrize("stronger", ["expiring", "revoked", "undecryptable"])
def test_a_missing_audience_ranks_below_the_other_reasons(client, box, stronger):
    renew = config.pat_renew_before_s()
    _register(_jwt(aud=["mcp-gateway"]), exp_in=renew - 3600 if stronger == "expiring" else renew + 3600)
    if stronger == "revoked":
        get_store().execute("UPDATE _user_credentials SET revoked_at = 1 WHERE owner_sub = ?", (EMAIL,))
    if stronger == "undecryptable":
        get_store().execute("UPDATE _user_credentials SET portal_pat_enc = ? WHERE owner_sub = ?", (b"garbage", EMAIL))
    assert _auto(client)["due_reason"] == stronger
    wanted = routes.portal_pat_wanted(get_store(), EMAIL)
    assert wanted["reason"] == stronger and "require_audiences" not in wanted


# ---------------------------------------------------------------- 자동 등록을 멈추는 길(D3)
def test_a_revoked_pat_comes_back_while_auto_is_on_and_the_switch_is_how_to_stop_it(client, box):
    """켜져 있는 동안은 폐기한 PAT 도 다시 바란다(의도 — Claude 만 쓰는 사람에게는 다시 켤 스위치가 없다). /api/me 의 auto 와
    pat_unavailable 안내가 멈추는 길(설정의 자동 등록 스위치)을 말하고, 끄면 그 말 대신 켜는 길을 말한다."""
    _register(exp_in=60 * 86400)
    get_store().execute("UPDATE _user_credentials SET revoked_at = 1 WHERE owner_sub = ?", (EMAIL,))
    assert _mint(client, GW)["portal_pat_wanted"]["reason"] == "revoked"
    auto = _auto(client)
    assert auto["due_reason"] == "revoked" and "PUT /api/me/portal-pat-auto {enabled:false}" in auto["how_to_stop"]
    guidance = runner.pat_unavailable_guidance(get_store(), EMAIL)
    assert runner.AUTO_STOP_HINT in guidance
    client.put("/api/me/portal-pat-auto", json={"enabled": False}, headers=AUTH)
    assert _auto(client)["how_to_stop"] is None and "portal_pat_wanted" not in _mint(client, GW)
    guidance = runner.pat_unavailable_guidance(get_store(), EMAIL)
    assert runner.AUTO_STOP_HINT not in guidance and "PUT /api/me/portal-pat-auto {enabled:true}" in guidance


def test_the_guidance_names_only_the_registration_paths_that_exist_now(box):
    """웹 자동 등록과 자동 등록 스위치는 화면에 아직 없다 — 안내는 지금 되는 길만 말한다(R2-8). 등록은 Claude 에서 hwax_risk 도구를
    부르기(게이트웨이 길)와 웹 설정 화면의 '포털에서 발급해 등록' 이고, 멈추기·다시 켜기는 곧 생길 스위치이며 그때까지는 운영자가 그
    사람으로 PUT /api/me/portal-pat-auto 를 부른다. '웹에서 앱을 열면 자동 등록' 은 말하지 않는다."""
    from app import entry, state as state_module

    store = get_store()
    on = runner.pat_unavailable_guidance(store, EMAIL)
    store.set_portal_pat_auto(EMAIL, False)
    off = runner.pat_unavailable_guidance(store, EMAIL)
    texts = {"on": on, "off": off, "stop": runner.AUTO_STOP_HINT, "fix": entry.fix_register_pat(),
             "g6": entry._fix_gate_blocked(state_module.UNKNOWN_BLOCKING_REASON, "p-1")}
    for name, text in texts.items():
        for claim in ("앱을 한 번 열", "앱을 열", "열거나", "켜면 저절로", "거기서 켠다", "설정에서 자동 등록을 끈다"):
            assert claim not in text, (name, claim)
    for text in (on, off, texts["fix"]):
        assert "Claude 에서 hwax_risk 도구를" in text and "포털에서 발급해 등록" in text
    assert runner.AUTO_STOP_HINT in on and "PUT /api/me/portal-pat-auto {enabled:false}" in runner.AUTO_STOP_HINT
    assert "곧 생긴다" in runner.AUTO_STOP_HINT and "곧 생긴다" in off and "PUT /api/me/portal-pat-auto {enabled:true}" in off
