# 공용 pytest 픽스처 — 데이터 경로를 임시 디렉터리로 격리(HWAXRISK_DATA_DIR)하고 lifespan 이 켜진 TestClient 를 준다
from __future__ import annotations

import errno
import ipaddress
import os
import shutil
import socket
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import pytest

# 건너뜀 예산 — 훅은 tests/skip_budget.py 에 있고 여기서 이름으로 들인다(그 파일만 -p 로 따로 시험할 수 있게).
from tests.skip_budget import (  # noqa: F401
    pytest_collection_modifyitems, pytest_runtest_logreport, pytest_sessionfinish, pytest_terminal_summary)

# backend/tests/ → backend/ → 리포 루트. 매니페스트·docs 는 리포 루트, app/·fixtures 는 backend/ 기준이다.
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"

# app.config 는 import 시점에 env 를 읽으므로 테스트 모듈이 수집(import)되기 전에 env 를 고정해야 한다.
# pytest_configure 는 수집보다 먼저 실행된다 — 세션 전체가 같은 임시 데이터 디렉터리를 쓴다.
_SESSION_DATA_DIR: str | None = None

# 실전송 가드 — 시험은 이 박스의 운영 서비스도, 루프백 밖도 부르지 않는다(R-FLOOR-3). 시험 파일의 no_network 픽스처는 httpx 한
# 층이라 `monkeypatch.undo()` 한 번에 함께 풀렸고(마지막 패널이 dev 게이트웨이 /tools-map 을 시험 PAT 로 불렀다), 그 픽스처가
# 없는 시험(test_wiring_regressions 22건)과 세션 러너의 폐기 목록 조회는 처음부터 dev 의 실 게이트웨이·포털을 불렀다.
# 소켓 연결 한 곳에서 세션 내내 거절한다 — 앱 설정이 가리키는 서비스 포트와 같은 박스의 포털 백엔드·에이전트 서버 포트,
# 그리고 루프백 밖 전부다. 시험이 띄운 서버(루프백 임시 포트)는 그대로 열린다. 거절은 연결 오류라 앱은 '닿지 않음' 으로 읽는다.
_BOX_SERVICE_PORTS = (8723, 9009)          # 포털 백엔드·에이전트 서버 — 앱 설정에는 없지만 같은 박스에 떠 있다
_REAL_CONNECT = socket.socket.connect
_REAL_CONNECT_EX = socket.socket.connect_ex
_REFUSED_PORTS: set[int] = set()


def _service_ports() -> set[int]:
    """앱이 부르는 서비스 주소(env 를 고정한 뒤의 app.config)의 포트."""
    from app import config as app_config  # noqa: PLC0415 — HWAXRISK_DATA_DIR 를 고정한 뒤에 읽는다.

    s = app_config.settings
    ports = set(_BOX_SERVICE_PORTS)
    for url in (s.portal_base, s.heax_api, s.heax_base, s.gateway_mcp, s.aidh_base, s.agent_url):
        if url:
            parts = urlsplit(url)
            ports.add(parts.port or (443 if parts.scheme == "https" else 80))
    return ports


def refused_reason(address) -> str | None:
    """이 주소로의 연결을 거절하면 그 까닭, 열어 두면 None. AF_UNIX 처럼 (host, port) 가 아닌 주소는 열어 둔다."""
    if not isinstance(address, tuple) or len(address) < 2:
        return None
    host, port = str(address[0]), int(address[1])
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        return f"시험은 루프백 밖을 부르지 않는다 — {host}:{port}"
    if port in _REFUSED_PORTS:
        return f"시험은 이 박스의 운영 서비스를 부르지 않는다 — {host}:{port}"
    return None


def _guarded_connect(self, address):
    why = refused_reason(address)
    if why:
        raise ConnectionRefusedError(errno.ECONNREFUSED, f"{why} (tests/conftest.py 실전송 가드)")
    return _REAL_CONNECT(self, address)


def _guarded_connect_ex(self, address):
    return errno.ECONNREFUSED if refused_reason(address) else _REAL_CONNECT_EX(self, address)


def pytest_configure(config):
    global _SESSION_DATA_DIR
    _SESSION_DATA_DIR = tempfile.mkdtemp(prefix="hwaxrisk-test-")
    os.environ["HWAXRISK_DATA_DIR"] = _SESSION_DATA_DIR
    os.environ.pop("HEAX_DATA_DIR", None)
    os.environ.pop("ROOT_PATH", None)
    _REFUSED_PORTS.update(_service_ports())
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex


def pytest_unconfigure(config):
    socket.socket.connect = _REAL_CONNECT
    socket.socket.connect_ex = _REAL_CONNECT_EX
    if _SESSION_DATA_DIR and os.path.isdir(_SESSION_DATA_DIR):
        shutil.rmtree(_SESSION_DATA_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def session_data_dir() -> Path:
    """세션 전체가 공유하는 임시 데이터 디렉터리(HWAXRISK_DATA_DIR 값)."""
    assert _SESSION_DATA_DIR is not None
    return Path(_SESSION_DATA_DIR)


@pytest.fixture(scope="session")
def client(session_data_dir):
    """lifespan(store.open+migrate, MCP session_manager) 이 켜진 TestClient.

    FastMCP 의 StreamableHTTPSessionManager.run() 은 인스턴스당 1회만 허용되므로
    세션 스코프 하나로만 연다(P0 테스트는 전부 읽기 전용).
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def risk_store(tmp_path):
    """테스트 전용 빈 DB 위의 RiskStore(open+migrate 완료)."""
    from app.risk_store import RiskStore

    store = RiskStore(tmp_path / "risk_review.db")
    store.open()
    store.migrate()
    yield store
    store.close()


@pytest.fixture(autouse=True)
def _reset_adapter_discovery():
    """어댑터 발견은 모듈 수준 60 s 캐시라 시험 사이로 샌다 — 매 시험 앞뒤로 비운다."""
    from app.adapters import registry as adapters_registry

    adapters_registry.reset_discovery_cache()
    yield
    adapters_registry.reset_discovery_cache()
