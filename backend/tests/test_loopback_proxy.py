# 루프백 주소는 프록시를 타지 않는다(WP5a R10) — 죽은 프록시 변수가 걸린 환경에서 실제 소켓으로 루프백 호출이 그대로 되는지 본다
"""HEAXHub 는 앱 컨테이너에 프록시 변수 여덟을 물려준다. 이 앱이 부르는 포털·에이전트 서버·AIDataHub·게이트웨이·heax 는
같은 박스의 루프백인데, NO_PROXY 에 기대면 그 값이 빠진 박스에서 루프백 호출이 사내 프록시로 나가 실패한다.
trust_env=False 는 허브가 넣어 준 사내 CA(SSL_CERT_FILE)까지 꺼서 https 대상(RA)을 깨므로 쓰지 않는다(반대 검토 P-17).
"""
from __future__ import annotations

import json
import re
import socket
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from tests.conftest import BACKEND_DIR

PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 — http.server 의 이름이다.
        body = json.dumps({"revoked": ["jti-1"], "email": "who@example.com", "path": self.path}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture
def loopback_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def dead_proxy(monkeypatch):
    """아무것도 듣지 않는 프록시를 환경에 건다(NO_PROXY 는 비운다) — 프록시를 타면 연결이 거절된다."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{sock.getsockname()[1]}"
    for name in PROXY_VARS:
        monkeypatch.setenv(name, dead)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    return dead


def test_the_dead_proxy_really_catches_a_plain_client(loopback_server, dead_proxy):
    """대조 — 이 환경에서 맨 httpx.Client 는 프록시로 나가 실패한다(시험이 빈 시험이 아니다)."""
    with pytest.raises(httpx.HTTPError):
        with httpx.Client(timeout=3) as client:
            client.get(loopback_server + "/plain")


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_the_app_client_reaches_loopback_past_a_dead_proxy(loopback_server, dead_proxy, host):
    from app.common import http_client

    with http_client(timeout=3) as client:
        r = client.get(loopback_server.replace("127.0.0.1", host) + "/direct")
    assert r.status_code == 200 and r.json()["path"] == "/direct"


def test_the_app_client_still_sends_other_hosts_through_the_proxy(dead_proxy):
    """루프백만 뺀다 — 다른 주소는 종전대로 프록시 변수를 따른다(사내 CA 변수도 그대로 읽는다)."""
    from app.common import http_client

    with http_client(timeout=3) as client:
        assert client._transport_for_url(httpx.URL("https://ra.example.com/x")) is not client._transport
        assert client._transport_for_url(httpx.URL("http://127.0.0.1:9/x")) is client._transport
        assert client._transport_for_url(httpx.URL("http://localhost:9/x")) is client._transport


def test_the_runner_portal_and_heax_calls_reach_loopback_past_a_dead_proxy(loopback_server, dead_proxy,
                                                                            monkeypatch):
    """운영 경로 셋 — PAT 폐기 대조(러너) · PAT 등록 검증(라우트) · 신원 되묻기(identity)."""
    import dataclasses

    from app import config, identity, routes, runner

    assert runner.fetch_revoked_jtis(types.SimpleNamespace(portal_base=loopback_server)) == ["jti-1"]
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, portal_base=loopback_server,
                                                                heax_api=loopback_server))
    routes._verify_with_portal("pat-secret")                       # 200 이면 아무 일도 없다(닿지 못하면 502)
    assert identity._fetch_me("token")["email"] == "who@example.com"


def test_no_module_builds_its_own_http_client():
    """새 호출 자리가 맨 httpx.Client 로 돌아가지 않게 막는다 — 클라이언트는 common.http_client 하나로만 만든다."""
    offenders = []
    for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
        if path.name == "common.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bhttpx\.(Client|AsyncClient)\(", line):
                offenders.append(f"{path.relative_to(BACKEND_DIR)}:{number}")
    assert offenders == []
