# 데이터 경로 우선순위(HWAXRISK_DATA_DIR > HEAX_DATA_DIR > <리포>/data)·DB 파일명·디렉터리 생성·쓰기 불가 기동 중단·Settings 기본값(plan §8.2.6)·secrets.env
from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest

from app import config

_ENV_KEYS = ("HWAXRISK_DATA_DIR", "HEAX_DATA_DIR", "ROOT_PATH", "PORT", "HOST",
             "HWAXRISK_PORTAL_BASE", "HWAXRISK_CONCURRENCY", "HWAXRISK_ADH_TEAM")


@pytest.fixture
def reload_config(monkeypatch):
    """env 를 바꾼 뒤 app.config 를 다시 읽는 헬퍼. 테스트 뒤에는 원래 env 로 한 번 더 reload 해 복원한다."""
    def _reload(**env: str | None):
        for key in _ENV_KEYS:
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            if value is not None:
                monkeypatch.setenv(key, value)
        return importlib.reload(config)

    yield _reload
    monkeypatch.undo()
    importlib.reload(config)


def test_hwaxrisk_data_dir_wins_over_heax(tmp_path, reload_config):
    a, b = tmp_path / "a", tmp_path / "b"
    mod = reload_config(HWAXRISK_DATA_DIR=str(a), HEAX_DATA_DIR=str(b))
    assert Path(mod.settings.data_dir) == a
    assert Path(mod.settings.db_path) == a / "risk_review.db"


def test_heax_data_dir_fallback(tmp_path, reload_config):
    b = tmp_path / "b"
    mod = reload_config(HEAX_DATA_DIR=str(b))
    assert Path(mod.settings.data_dir) == b
    assert Path(mod.settings.db_path) == b / "risk_review.db"


def test_old_env_prefix_is_ignored(tmp_path, reload_config, monkeypatch):
    """폐기된 HWAX_RISK_DATA_DIR 은 읽지 않는다."""
    b = tmp_path / "b"
    monkeypatch.setenv("HWAX_RISK_DATA_DIR", str(tmp_path / "old"))
    mod = reload_config(HEAX_DATA_DIR=str(b))
    assert Path(mod.settings.data_dir) == b


def test_repo_data_fallback():
    """폴백 경로는 resolve_data_dir 로만 단언한다 — load_settings 는 mkdir 부작용으로 실제 리포에 data/ 를 만든다."""
    repo_root = Path(config.__file__).resolve().parent.parent.parent  # backend/app/config.py → 리포 루트
    assert (repo_root / "backend" / "app" / "assets").is_dir() and (repo_root / "docs").is_dir()
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
            config.load_settings(env={"HWAXRISK_DATA_DIR": str(ro)})
    finally:
        ro.chmod(0o700)


def test_data_dir_is_created(tmp_path, reload_config):
    target = tmp_path / "nested" / "data"
    assert not target.exists()
    mod = reload_config(HWAXRISK_DATA_DIR=str(target))
    assert Path(mod.settings.data_dir) == target
    assert target.is_dir()


def test_defaults_follow_plan(tmp_path, reload_config):
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path))
    s = mod.settings
    assert s.app_id == "hwax_risk" and s.app_version == "0.1.0"
    assert s.root_path == "" and s.host == "127.0.0.1" and s.port == 8000
    assert s.portal_base == "http://127.0.0.1:5283"
    assert s.heax_api == "http://127.0.0.1:4040"
    assert s.heax_base == "http://127.0.0.1:4180"
    assert s.gateway_mcp == "http://127.0.0.1:9110/mcp"
    assert s.aidh_base == "http://127.0.0.1:8001"
    assert s.agent_url == ""
    assert len(s.risk_roster_domains) == 15
    assert s.risk_ecad_domains == ("pcb", "pwr", "rf", "soc", "passive", "mem")
    assert s.risk_adjacency == ""
    assert s.risk_concurrency == 2
    assert s.risk_daily_panel_cap == 24
    assert s.risk_default_close_level == "C2"
    assert s.risk_carried_days == 90
    assert s.risk_panel_llm_cap == 120
    assert s.risk_promote_distinct_models == 1
    assert s.adh_team is None and s.adh_group is None


def test_env_overrides_with_hwaxrisk_prefix(tmp_path, reload_config):
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), ROOT_PATH="/apps/hwax_risk", PORT="8123",
                        HWAXRISK_PORTAL_BASE="http://portal.test:1", HWAXRISK_CONCURRENCY="1",
                        HWAXRISK_ADH_TEAM="team-x")
    s = mod.settings
    assert s.root_path == "/apps/hwax_risk" and s.port == 8123
    assert s.portal_base == "http://portal.test:1"
    assert s.risk_concurrency == 1
    assert s.adh_team == "team-x"


def test_load_secrets(tmp_path, caplog):
    assert config.load_secrets(tmp_path) == {}
    path = tmp_path / "secrets.env"
    path.write_text(
        "# 주석\nHWAXRISK_PORTAL_PAT=fake-portal-pat-test\n"
        "HWAXRISK_HEAX_SERVICE_PAT=heax_pat_test_fake\nHWAXRISK_AIDH_API_KEY=fake-key\nOTHER=x\n",
        encoding="utf-8")
    path.chmod(0o600)
    got = config.load_secrets(tmp_path)
    assert got == {"HWAXRISK_PORTAL_PAT": "fake-portal-pat-test",
                   "HWAXRISK_HEAX_SERVICE_PAT": "heax_pat_test_fake",
                   "HWAXRISK_AIDH_API_KEY": "fake-key"}
    assert "fake" not in caplog.text
    # 0600 이 아니면 경고만 내고 값은 로그에 싣지 않는다.
    path.chmod(0o644)
    with caplog.at_level("WARNING", logger="hwax_risk.config"):
        assert config.load_secrets(tmp_path) == got
    assert "0600" in caplog.text and "fake" not in caplog.text
