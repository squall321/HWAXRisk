# 공용 pytest 픽스처 — 데이터 경로를 임시 디렉터리로 격리(HWAXRISK_DATA_DIR)하고 lifespan 이 켜진 TestClient 를 준다
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# backend/tests/ → backend/ → 리포 루트. 매니페스트·docs 는 리포 루트, app/·fixtures 는 backend/ 기준이다.
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"

# app.config 는 import 시점에 env 를 읽으므로 테스트 모듈이 수집(import)되기 전에 env 를 고정해야 한다.
# pytest_configure 는 수집보다 먼저 실행된다 — 세션 전체가 같은 임시 데이터 디렉터리를 쓴다.
_SESSION_DATA_DIR: str | None = None


def pytest_configure(config):
    global _SESSION_DATA_DIR
    _SESSION_DATA_DIR = tempfile.mkdtemp(prefix="hwaxrisk-test-")
    os.environ["HWAXRISK_DATA_DIR"] = _SESSION_DATA_DIR
    os.environ.pop("HEAX_DATA_DIR", None)
    os.environ.pop("ROOT_PATH", None)


def pytest_unconfigure(config):
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
