# 데이터 경로 우선순위(HWAX_RISK_DATA_DIR > HEAX_DATA_DIR > <리포>/data)·DB 파일명·디렉터리 생성·쓰기 불가 기동 중단·기본 설정값
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

from app import config


@pytest.fixture
def reload_config(monkeypatch):
    """env 를 바꾼 뒤 app.config 를 다시 읽는 헬퍼. 테스트 뒤에는 원래 env 로 한 번 더 reload 해 복원한다."""
    def _reload(**env: str | None):
        for key in ("HWAX_RISK_DATA_DIR", "HEAX_DATA_DIR", "ROOT_PATH", "PORT", "HOST"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            if value is not None:
                monkeypatch.setenv(key, value)
        return importlib.reload(config)

    yield _reload
    monkeypatch.undo()
    importlib.reload(config)


def test_hwax_risk_data_dir_wins_over_heax(tmp_path, reload_config):
    a, b = tmp_path / "a", tmp_path / "b"
    mod = reload_config(HWAX_RISK_DATA_DIR=str(a), HEAX_DATA_DIR=str(b))
    assert Path(mod.settings.DATA_DIR) == a
    assert Path(mod.settings.DB_PATH) == a / "risk_review.db"


def test_heax_data_dir_fallback(tmp_path, reload_config):
    b = tmp_path / "b"
    mod = reload_config(HEAX_DATA_DIR=str(b))
    assert Path(mod.settings.DATA_DIR) == b
    assert Path(mod.settings.DB_PATH) == b / "risk_review.db"


def test_repo_data_fallback():
    """폴백 경로는 resolve_data_dir 로만 단언한다 — load_settings 는 mkdir 부작용으로 실제 리포에 data/ 를 만든다."""
    repo_root = Path(config.__file__).resolve().parent.parent.parent  # backend/app/config.py → 리포 루트
    assert (repo_root / "backend" / "app").is_dir() and (repo_root / "docs").is_dir()
    assert config.resolve_data_dir(env={}) == repo_root / "data"
    assert config.resolve_data_dir(env={"HEAX_DATA_DIR": ""}) == repo_root / "data"


def test_unwritable_data_dir_aborts(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root 는 쓰기 권한 검사를 우회한다")
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        with pytest.raises(RuntimeError):
            config.load_settings(env={"HWAX_RISK_DATA_DIR": str(ro)})
    finally:
        ro.chmod(0o700)


def test_data_dir_is_created(tmp_path, reload_config):
    target = tmp_path / "nested" / "data"
    assert not target.exists()
    mod = reload_config(HWAX_RISK_DATA_DIR=str(target))
    assert Path(mod.settings.DATA_DIR) == target
    assert target.is_dir()


def test_defaults_and_root_path(tmp_path, reload_config):
    mod = reload_config(HWAX_RISK_DATA_DIR=str(tmp_path))
    s = mod.settings
    assert s.APP_ID == "hwax_risk"
    assert isinstance(s.APP_VERSION, str) and s.APP_VERSION
    assert s.ROOT_PATH == ""
    assert s.HOST == "127.0.0.1"
    assert int(s.PORT) == 8000

    mod = reload_config(HWAX_RISK_DATA_DIR=str(tmp_path), ROOT_PATH="/apps/hwax_risk", PORT="8123")
    assert mod.settings.ROOT_PATH == "/apps/hwax_risk"
    assert int(mod.settings.PORT) == 8123
