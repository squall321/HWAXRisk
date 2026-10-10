# 시험이 이 박스의 실 원장을 열지 않는지 — 기동(lifespan)이 연 저장소 파일을 sqlite 에 직접 물어 확인한다(WP5b C1)
"""conftest 가 `HWAXRISK_DATA_DIR` 을 세션 임시 디렉터리로 고정한다. 그 고정이 빠지면 시험이 기본 경로(`<리포>/data`
또는 `HEAX_DATA_DIR`)의 실 원장에 쓴다 — 포털·에이전트 서버에서 시험 기록이 운영 원장에 섞인 전례가 둘 있다.
설정값이 아니라 sqlite 가 실제로 연 파일을 본다.
"""
from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app import config
from app.adapters.registry import GatewayRegistry
from app.risk_store import get_store


def test_the_suite_data_dir_is_a_temp_dir(session_data_dir):
    assert Path(os.environ["HWAXRISK_DATA_DIR"]) == session_data_dir
    assert config.settings.data_dir.resolve() == session_data_dir.resolve()
    assert Path(tempfile.gettempdir()).resolve() in session_data_dir.resolve().parents
    assert "HEAX_DATA_DIR" not in os.environ


def test_the_store_the_app_opened_lives_in_it(client, session_data_dir):
    opened = Path(get_store().conn.execute("PRAGMA database_list").fetchone()[2]).resolve()
    assert session_data_dir.resolve() in opened.parents, opened
    # conftest 의 고정이 없었다면 열렸을 자리 — 그 아래가 아니어야 한다.
    real = config.resolve_data_dir({k: v for k, v in os.environ.items() if k != "HWAXRISK_DATA_DIR"}).resolve()
    assert real not in opened.parents and real != opened.parent, (real, opened)


# ---------------------------------------------------------------- 실전송 가드(R-FLOOR-3)
def test_the_box_services_are_refused_for_the_whole_session():
    """시험은 이 박스의 운영 서비스를 부르지 않는다 — 앱 설정의 게이트웨이·포털 포트는 연결 단계에서 거절된다. 픽스처 없이 도는
    시험과 `monkeypatch.undo()` 로 풀린 no_network 뒤에서도 그렇다(시험 PAT 가 dev 의 실 게이트웨이 /tools-map 에 닿던 길)."""
    for url in (config.settings.gateway_mcp, config.settings.portal_base):
        with socket.socket() as sock, pytest.raises(ConnectionRefusedError, match="실전송 가드"):
            sock.connect(("127.0.0.1", urlsplit(url).port))
    registry = GatewayRegistry(config.settings.gateway_mcp, token="pat-secret")
    try:
        assert registry.load() == {}                       # 앱은 '닿지 않음'(빈 지도)으로 읽는다
    finally:
        registry.close()
    with socket.socket() as sock, pytest.raises(ConnectionRefusedError, match="루프백 밖"):
        sock.connect(("192.0.2.1", 80))                    # 문서용 주소(RFC 5737) — 루프백 밖은 전부 거절한다


def test_a_server_the_test_starts_on_a_temp_port_stays_reachable():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=2):
            pass
