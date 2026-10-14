# GET /api/me(익명·인증·box) · PUT /api/me/portal-pat — 익명 401, 422 4종(pat_email_mismatch·pat_audience·pat_expiring·pat_invalid), 정상 1행, null 삭제 0행 + 자격 Fernet 암복호·scopes/jti 계약(plan §8.2.7)
from __future__ import annotations

import base64
import dataclasses
import json
import re
import stat
import subprocess
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
    # 익명에게는 판정과 까닭의 code 만 — 글(고칠 명령)·키 이름·호스트 이름·포털 주소는 싣지 않는다(SEC-6).
    assert set(body["box"]) == {"secrets_valid", "reasons"} and body["box"]["secrets_valid"] is False
    assert body["box"]["reasons"] and all(set(r) == {"code"} for r in body["box"]["reasons"])
    assert set(body) == {"email", "display_name", "role", "organization", "anonymous", "source", "portal_pat", "box"}
    # 로그인한 사람은 그대로 다 본다 — portal_base 는 진단값이다(틀리면 PAT 등록·패널이 전부 실패하는데 화면에 안 보이면 사람이
    # 토큰을 의심한다, 2026-09-30 실측).
    box = client.get("/api/me", headers=AUTH).json()["box"]
    assert set(box) == {"hostname", "secrets_valid", "cred_key_present", "cred_key_source", "reasons", "portal_base"}
    assert box["portal_base"].startswith("http") and all({"code", "message", "fix"} <= set(r) for r in box["reasons"])


def test_me_authenticated_without_pat(client, wired):
    body = client.get("/api/me", headers=AUTH).json()
    assert body["email"] == "bob@example.com" and body["anonymous"] is False and body["source"] == "bearer"
    # 등록이 없어도 객체다 — 자동 등록 칸(auto)이 '없음' 을 말한다(리스크 앱 사람 자격 R1).
    assert body["portal_pat"]["registered"] is False and body["portal_pat"]["auto"]["due_reason"] == "absent"


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
    assert client.get("/api/me", headers=AUTH).json()["portal_pat"]["registered"] is False


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


# ---------------------------------------------------------------- 박스 자격(리스크 앱 사람 자격 R5)
FERNET_KEY = base64.urlsafe_b64encode(b"k" * 32).decode()      # 시험용 고정 키(형식만 맞다)


def _secrets_file(data_dir, **values: str) -> None:
    path = data_dir / "secrets.env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    path.chmod(0o600)


def _codes(box: dict) -> list[str]:
    return [r["code"] for r in box["reasons"]]


def test_box_needs_only_the_cred_key_and_says_what_each_missing_optional_key_closes(tmp_path):
    """필수는 HWAXRISK_CRED_KEY 하나다 — 그것이 secrets.env 에 있으면 선택 키가 하나도 없어도 secrets_valid 다(종전에는 다섯 키를
    다 필수로 세어 쓰지 않는 RA 쓰기·AIDataHub 키 때문에 어느 박스든 경고였다). 없는 선택 키는 정보로 남고 무엇이 닫히는지 말한다."""
    _secrets_file(tmp_path, HWAXRISK_CRED_KEY=FERNET_KEY)
    box = config.box_assessment(box_match=True, data_dir=tmp_path, env={})
    assert box["secrets_valid"] is True and box["cred_key_source"] == "secrets"
    assert _codes(box) == ["missing_optional"]
    optional = box["reasons"][0]
    assert optional["keys"] == list(config.OPTIONAL_SECRET_KEYS)
    for key in config.OPTIONAL_SECRET_KEYS:
        assert f"{key}: {config.OPTIONAL_KEY_EFFECTS[key]}" in optional["message"]
    assert FERNET_KEY not in json.dumps(box)                       # 값은 싣지 않는다
    # 선택 키를 다 넣으면 까닭이 없다. 게이트웨이 시크릿·백업 키는 환경변수로 줘도 있는 것이다(그렇게 읽는다).
    _secrets_file(tmp_path, HWAXRISK_CRED_KEY=FERNET_KEY, HWAXRISK_PORTAL_PAT="p", HWAXRISK_PORTAL_PAT_RW="p",
                  HWAXRISK_HEAX_SERVICE_PAT="p", HWAXRISK_AIDH_API_KEY="p")
    env = {"HWAXRISK_BACKUP_KEY": "age1x", "HWAXRISK_HEAX_GATEWAY_SECRET": "s"}
    assert config.box_assessment(box_match=True, data_dir=tmp_path, env=env)["reasons"] == []
    # 파일에서만 읽는 키는 환경변수로 줘도 없는 것이다 — 앱이 그 값을 읽지 않는다.
    _secrets_file(tmp_path, HWAXRISK_CRED_KEY=FERNET_KEY)
    box = config.box_assessment(box_match=True, data_dir=tmp_path, env={"HWAXRISK_PORTAL_PAT": "p", **env})
    assert box["reasons"][0]["keys"] == ["HWAXRISK_PORTAL_PAT", "HWAXRISK_PORTAL_PAT_RW", "HWAXRISK_HEAX_SERVICE_PAT",
                                         "HWAXRISK_AIDH_API_KEY"]


def test_a_cred_key_given_by_env_or_path_counts_as_present(tmp_path):
    """env·path 로 준 키도 있는 것이다 — 종전 판정은 secrets.env 파일만 봐서 env 로 준 CRED_KEY 를 '없음' 으로 셌다."""
    box = config.box_assessment(box_match=True, data_dir=tmp_path, env={"HWAXRISK_CRED_KEY": FERNET_KEY})
    assert (box["secrets_valid"], box["cred_key_source"]) == (True, "env")
    key_file = tmp_path / "outside.key"
    key_file.write_text(FERNET_KEY, encoding="utf-8")
    box = config.box_assessment(box_match=True, data_dir=tmp_path, env={"HWAXRISK_CRED_KEY_PATH": str(key_file)})
    assert (box["secrets_valid"], box["cred_key_source"]) == (True, "path")
    # 가리키는 파일이 없으면 path 가 아니다(load_cred_key 도 그 길을 건너뛴다).
    box = config.box_assessment(box_match=True, data_dir=tmp_path, env={"HWAXRISK_CRED_KEY_PATH": str(tmp_path / "x")})
    assert box["cred_key_source"] == "absent"


def test_box_reasons_name_a_missing_cred_key_and_a_host_mismatch(tmp_path):
    box = config.box_assessment(box_match=True, data_dir=tmp_path, env={})
    assert box["secrets_valid"] is False and box["cred_key_source"] == "absent"
    assert _codes(box)[:1] == ["missing_required"]
    required = box["reasons"][0]
    assert required["keys"] == ["HWAXRISK_CRED_KEY"]
    assert f"`{config.CRED_KEY_NEW_COMMAND}`" in required["fix"] and str(tmp_path) not in required["fix"]
    # 이관 직후 첫 기동 — 키가 있어도 secrets_valid 가 아니다.
    _secrets_file(tmp_path, HWAXRISK_CRED_KEY=FERNET_KEY)
    box = config.box_assessment(box_match=False, data_dir=tmp_path, env={})
    assert box["secrets_valid"] is False and _codes(box)[0] == "host_mismatch"
    assert "HWAXRISK_CRED_KEY" in box["reasons"][0]["fix"]


def test_a_cred_key_fallback_is_a_reason_with_the_copy_the_same_value_fix(tmp_path):
    """cred.key 폴백은 동작하지만 secrets_valid 가 아니다 — 고칠 곳은 '같은 값을 옮기라' 이고 그 명령은 값을 화면에 찍지 않는다.
    새 키를 넣으면 등록된 PAT 가 풀리지 않는다는 말이 함께 있어야 한다(Fernet 키가 바뀌면 portal_pat_enc 가 안 풀린다)."""
    key = config.load_cred_key(tmp_path)                            # 앱이 만드는 개발용 폴백
    box = config.box_assessment(box_match=True, data_dir=tmp_path, env={})
    assert box["secrets_valid"] is False and box["cred_key_source"] == "dev_fallback"
    assert _codes(box)[0] == "cred_key_dev_fallback"
    fix = box["reasons"][0]["fix"]
    assert f"`{config.CRED_KEY_MOVE_COMMAND}`" in fix and str(tmp_path) not in fix
    assert "새 키를 만들어 넣으면" in fix and "다시 띄운다" in fix
    assert key.decode() not in json.dumps(box)
    # 같은 값을 secrets.env 로 옮기면 출처가 secrets 이고 폴백 까닭이 사라진다 — 옮긴 키로 옛 암호문이 그대로 풀린다.
    from cryptography.fernet import Fernet

    old = Fernet(key).encrypt(FAKE_PAT.encode())
    _secrets_file(tmp_path, HWAXRISK_CRED_KEY=key.decode())
    box = config.box_assessment(box_match=True, data_dir=tmp_path, env={})
    assert box["cred_key_source"] == "secrets" and "cred_key_dev_fallback" not in _codes(box)
    assert box["secrets_valid"] is True
    assert Fernet(config.load_cred_key(tmp_path, create=False)).decrypt(old).decode() == FAKE_PAT


def test_me_box_carries_the_reasons_and_the_key_source(client, wired):
    body = client.get("/api/me", headers=AUTH).json()
    box = body["box"]
    assert box["cred_key_source"] in ("secrets", "env", "path", "dev_fallback", "absent")
    assert isinstance(box["reasons"], list) and all(set(r) >= {"code", "message", "fix"} for r in box["reasons"])
    blocking = {"host_mismatch", "missing_required", "cred_key_dev_fallback"}
    assert box["secrets_valid"] is not any(r["code"] in blocking for r in box["reasons"])


# ---------------------------------------------------------------- 키 명령은 안전한 셸 한 줄이다(BEH-7)
def _snippet(fix: str) -> str:
    found = re.findall(r"`([^`]+)`", fix)
    assert len(found) == 1, fix
    return found[0]


def _sh(snippet: str, cwd) -> subprocess.CompletedProcess:
    """데이터 디렉터리에서 돈다 — 명령은 경로를 박지 않는다."""
    return subprocess.run(["bash", "-c", snippet], cwd=cwd, capture_output=True, text=True, timeout=30)


def _reason(box: dict, code: str) -> dict:
    return next(r for r in box["reasons"] if r["code"] == code)


def test_the_new_key_command_writes_one_valid_fernet_key_without_printing_it(tmp_path):
    """python 없이 32바이트 난수를 urlsafe base64 로 만든다 — Fernet 이 받는 키다. 끝 줄바꿈이 없는 secrets.env 의 마지막 줄에 붙지
    않고, 0600 이며, 이미 값이 있는 키 줄이 있으면 아무것도 바꾸지 않는다(키를 갈면 등록된 PAT 가 전부 안 풀린다)."""
    from cryptography.fernet import Fernet

    snippet = _snippet(_reason(config.box_assessment(box_match=True, data_dir=tmp_path, env={}), "missing_required")["fix"])
    # 키는 urlsafe 글자만 쓴다 — 32바이트 난수 하나가 '+'·'/' 를 품을 확률이 74% 쯤이라 열여섯 번 만들어 본다(놓칠 확률 1e-9 밑).
    for n in range(16):
        fresh = tmp_path / f"fresh{n}"
        fresh.mkdir()
        assert _sh(snippet, fresh).returncode == 0
        made = config.load_secrets(fresh)["HWAXRISK_CRED_KEY"]
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}=", made), made
        Fernet(made)
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("HWAXRISK_BACKUP_KEY=age1x", encoding="utf-8")         # 끝 줄바꿈이 없다
    secrets_file.chmod(0o644)
    out = _sh(snippet, tmp_path)
    assert out.returncode == 0, out.stderr
    loaded = config.load_secrets(tmp_path)
    key = loaded["HWAXRISK_CRED_KEY"]
    assert len(base64.urlsafe_b64decode(key)) == 32
    token = Fernet(key).encrypt(b"pat")
    assert Fernet(key).decrypt(token) == b"pat"
    assert loaded["HWAXRISK_BACKUP_KEY"] == "age1x"                                 # 붙지 않았다
    assert key not in out.stdout + out.stderr and "넣었다" in out.stdout
    assert stat.S_IMODE(secrets_file.stat().st_mode) == 0o600
    box = config.box_assessment(box_match=True, data_dir=tmp_path, env={})
    assert box["cred_key_source"] == "secrets" and "missing_required" not in _codes(box)
    # 다시 돌려도 바꾸지 않는다 — 앞뒤 빈칸이 있는 키 줄도 있는 것이다(앱이 그렇게 읽는다).
    before = secrets_file.read_bytes()
    out = _sh(snippet, tmp_path)
    assert out.returncode == 0 and "이미 있다" in out.stdout and secrets_file.read_bytes() == before
    secrets_file.write_text("  HWAXRISK_CRED_KEY = " + key + "\n", encoding="utf-8")
    before = secrets_file.read_bytes()
    assert "이미 있다" in _sh(snippet, tmp_path).stdout and secrets_file.read_bytes() == before


@pytest.mark.parametrize("existing", ["HWAXRISK_CRED_KEY=\n", "# HWAXRISK_CRED_KEY=old\n", ""],
                         ids=["empty_value", "commented", "no_file_line"])
def test_an_empty_or_commented_key_line_is_not_a_key(tmp_path, existing):
    _sh_new = _snippet(_reason(config.box_assessment(box_match=True, data_dir=tmp_path, env={}), "missing_required")["fix"])
    if existing:
        (tmp_path / "secrets.env").write_text(existing, encoding="utf-8")
    assert "넣었다" in _sh(_sh_new, tmp_path).stdout
    assert config.load_secrets(tmp_path).get("HWAXRISK_CRED_KEY")


def test_the_move_command_copies_the_same_value_once_and_refuses_an_empty_cred_key(tmp_path):
    """cred.key 폴백은 같은 값을 옮긴다(새 키면 등록된 PAT 가 안 풀린다). cred.key 가 없거나 비었으면, 이미 키 줄이 있으면 아무것도
    바꾸지 않는다. 값은 화면에 찍지 않는다."""
    key = config.load_cred_key(tmp_path)
    snippet = _snippet(_reason(config.box_assessment(box_match=True, data_dir=tmp_path, env={}), "cred_key_dev_fallback")["fix"])
    secrets_file = tmp_path / "secrets.env"
    secrets_file.write_text("HWAXRISK_BACKUP_KEY=age1x", encoding="utf-8")
    out = _sh(snippet, tmp_path)
    assert out.returncode == 0 and "옮겼다" in out.stdout and key.decode() not in out.stdout + out.stderr
    loaded = config.load_secrets(tmp_path)
    assert loaded["HWAXRISK_CRED_KEY"] == key.decode() and loaded["HWAXRISK_BACKUP_KEY"] == "age1x"
    assert stat.S_IMODE(secrets_file.stat().st_mode) == 0o600
    before = secrets_file.read_bytes()
    assert "이미 있다" in _sh(snippet, tmp_path).stdout and secrets_file.read_bytes() == before
    for content in (b"", b"\n"):
        other = tmp_path / f"other{len(content)}"
        other.mkdir()
        (other / "cred.key").write_bytes(content)
        out = _sh(snippet, other)
        assert "비었다" in out.stdout and not (other / "secrets.env").exists(), (content, out.stdout)
    empty = tmp_path / "nokey"
    empty.mkdir()
    assert "없거나 비었다" in _sh(snippet, empty).stdout and not (empty / "secrets.env").exists()


# ---------------------------------------------------------------- 박스 자격 글에는 경로가 없다(SEC-6)
_ABS_PATH = re.compile(r"(?<![\w:/])/(?:home|tmp|data|var|srv|opt|etc|root|mnt|usr)\b")


@pytest.mark.parametrize("case", ["absent", "dev_fallback", "host_mismatch", "optional"])
def test_box_reason_texts_name_the_data_directory_not_its_path(tmp_path, case):
    """글은 화면에 그대로 보인다 — 절대경로 대신 '데이터 디렉터리' 라 하고, 경로는 관리자만 /api/meta/runtime 의 data_dir 로 본다."""
    if case == "dev_fallback":
        config.load_cred_key(tmp_path)
    if case in ("host_mismatch", "optional"):
        _secrets_file(tmp_path, HWAXRISK_CRED_KEY=FERNET_KEY)
    box = config.box_assessment(box_match=case != "host_mismatch", data_dir=tmp_path, env={})
    assert box["reasons"]
    text = json.dumps(box["reasons"], ensure_ascii=False)
    assert str(tmp_path) not in text and not _ABS_PATH.search(text), text
    for reason in box["reasons"]:
        if reason["code"] in ("missing_required", "cred_key_dev_fallback", "missing_optional"):
            assert config.DATA_DIR_WORDS in reason["fix"]
