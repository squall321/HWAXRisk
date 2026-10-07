# 데이터 경로 우선순위(HWAXRISK_DATA_DIR > HEAX_DATA_DIR > <리포>/data)·DB 파일명·디렉터리 생성·쓰기 불가 기동 중단·Settings 기본값(plan §8.2.6)·secrets.env·cred.key
from __future__ import annotations

import importlib
import os
import stat
from pathlib import Path

import pytest

from app import config

_ENV_KEYS = ("HWAXRISK_DATA_DIR", "HEAX_DATA_DIR", "ROOT_PATH", "PORT", "HOST",
             "HWAXRISK_PORTAL_BASE", "HWAXRISK_CONCURRENCY", "HWAXRISK_ADH_TEAM",
             "HWAXRISK_MAX_LEAF", "HWAXRISK_MAX_INTERFACES", "HWAXRISK_SNAPSHOT_BUDGET_S",
             "HWAXRISK_MCAD_DOMAINS", "HWAXRISK_SOURCE_DRIFT_BLOCK", "HWAXRISK_FIELD_EVIDENCE_LINES",
             "HWAXRISK_BRIEF_TOKEN_TTL_S", "HWAXRISK_PAT_REQUIRE_READ_ONLY", "HWAXRISK_PAT_REVOCATION_POLL_S",
             "HWAXRISK_ADMIN_ROLES", "HWAXRISK_EXPORT_ALLOWED_GROUPS", "HWAXRISK_EXPORT_RETAIN_DAYS",
             "HWAXRISK_PRIOR_INCLUDE_HUMAN", "HWAXRISK_SUSPECT_TEXT_BLOCK",
             "HWAXRISK_RECALL_REQUIRE_VERIFIED_ACTOR", "HWAXRISK_NEG_PRECEDENT_LINES",
             "HWAXRISK_CLUSTER_DUP_SCAN", "HWAXRISK_PANEL_TIMEOUT_S", "HWAXRISK_ENGINE_READ_TIMEOUT_S",
             "HWAXRISK_CREDENTIAL_MARGIN_S")


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
    # §8.2.6 이 더한 17행.
    assert s.risk_admin_roles == ("admin",)
    assert s.risk_export_allowed_groups == ()
    assert s.risk_export_retain_days == 30
    assert s.risk_prior_include_human is True
    assert s.risk_suspect_text_block is True
    assert s.risk_recall_require_verified_actor is True
    assert s.risk_neg_precedent_lines == 6
    assert s.risk_cluster_dup_scan is True
    assert s.risk_max_leaf == 1500
    assert s.risk_max_interfaces == 6000
    assert s.risk_snapshot_budget_s == 180
    assert s.risk_mcad_domains == ("mech", "cam", "xd", "disp", "sh")
    assert s.risk_source_drift_block is False
    assert s.risk_field_evidence_lines == 5
    assert s.risk_brief_token_ttl_s == 900
    assert s.risk_pat_require_read_only is True
    assert s.risk_pat_revocation_poll_s == 60
    # 시간 한도 — 코드 기본값이 넉넉한 값이어야 한다(SIF 는 cleanenv 라 env 가 매니페스트로만 닿는다).
    assert s.risk_panel_timeout_s == 43200
    assert s.risk_engine_read_timeout_s == 54000
    assert s.risk_credential_margin_s == 0                    # 0 = 벽시계에서 유도


def test_time_limits_are_layered_and_follow_their_knobs(tmp_path, reload_config):
    """안쪽 한도가 바깥보다 작다 — 그리고 손잡이를 바꾸면 그것을 감싸는 자격 여유가 따라간다.

    여유가 1800초 고정이던 동안 감싸야 할 패널 벽시계(2400초)보다 작았다. 이웃 리포의 값은 여기 숫자로 적는다 —
    한쪽만 바꾸면 순서가 뒤집힌다(포털 AGENT_STREAM_IDLE_TIMEOUT_S 46800 · nginx NGINX_AGENT_READ_TIMEOUT 50400 ·
    엔진 2×DELIB_TIMEOUT_S+8 = 3608, 요청 상한 2×DELIB_TIMEOUT_MAX_S+8 = 28808 · PAT 등록 하한 86400).
    """
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path))
    s = mod.settings
    assert 3608 < 28808 < mod.panel_timeout_s(s) == 43200
    assert mod.panel_timeout_s(s) < 46800 < 50400 < s.risk_engine_read_timeout_s
    assert mod.panel_timeout_s(s) < mod.credential_margin_s(s) == 47400 < 86400

    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_PANEL_TIMEOUT_S="21600",
                        HWAXRISK_ENGINE_READ_TIMEOUT_S="60000")
    s = mod.settings
    assert (mod.panel_timeout_s(s), s.risk_engine_read_timeout_s) == (21600, 60000)
    assert mod.credential_margin_s(s) == 21600 + 3600 + 600
    # 벽시계를 끄면(0) 재지 않는다.
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_PANEL_TIMEOUT_S="0")
    assert mod.panel_timeout_s(mod.settings) == 0
    # 그때 여유는 기본 벽시계로 셈한다 — 끝없는 실행을 감쌀 여유는 없다.
    assert mod.credential_margin_s(mod.settings) == 47400
    # 여유를 따로 정하면 유도값 대신 그 값이다.
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_CREDENTIAL_MARGIN_S="7200")
    assert mod.credential_margin_s(mod.settings) == 7200


def test_env_overrides_with_hwaxrisk_prefix(tmp_path, reload_config):
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), ROOT_PATH="/apps/hwax_risk", PORT="8123",
                        HWAXRISK_PORTAL_BASE="http://portal.test:1", HWAXRISK_CONCURRENCY="1",
                        HWAXRISK_ADH_TEAM="team-x")
    s = mod.settings
    assert s.root_path == "/apps/hwax_risk" and s.port == 8123
    assert s.portal_base == "http://portal.test:1"
    assert s.risk_concurrency == 1
    assert s.adh_team == "team-x"


def test_new_settings_env_overrides(tmp_path, reload_config):
    """§8.2.6 신규 17행의 형 변환 — 정수·csv·불리언."""
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_MAX_LEAF="40", HWAXRISK_MAX_INTERFACES="90",
                        HWAXRISK_SNAPSHOT_BUDGET_S="600", HWAXRISK_MCAD_DOMAINS="mech, xd ",
                        HWAXRISK_SOURCE_DRIFT_BLOCK="true", HWAXRISK_FIELD_EVIDENCE_LINES="0",
                        HWAXRISK_BRIEF_TOKEN_TTL_S="60", HWAXRISK_PAT_REQUIRE_READ_ONLY="0",
                        HWAXRISK_PAT_REVOCATION_POLL_S="5", HWAXRISK_ADMIN_ROLES="admin,curator",
                        HWAXRISK_EXPORT_ALLOWED_GROUPS="cae,risk", HWAXRISK_EXPORT_RETAIN_DAYS="7",
                        HWAXRISK_PRIOR_INCLUDE_HUMAN="no", HWAXRISK_SUSPECT_TEXT_BLOCK="off",
                        HWAXRISK_RECALL_REQUIRE_VERIFIED_ACTOR="False", HWAXRISK_NEG_PRECEDENT_LINES="2",
                        HWAXRISK_CLUSTER_DUP_SCAN="0")
    s = mod.settings
    assert (s.risk_max_leaf, s.risk_max_interfaces, s.risk_snapshot_budget_s) == (40, 90, 600)
    assert s.risk_mcad_domains == ("mech", "xd")
    assert s.risk_source_drift_block is True
    assert (s.risk_field_evidence_lines, s.risk_brief_token_ttl_s, s.risk_pat_revocation_poll_s) == (0, 60, 5)
    assert s.risk_pat_require_read_only is False
    assert s.risk_admin_roles == ("admin", "curator") and s.risk_export_allowed_groups == ("cae", "risk")
    assert s.risk_export_retain_days == 7 and s.risk_neg_precedent_lines == 2
    assert s.risk_prior_include_human is False and s.risk_suspect_text_block is False
    assert s.risk_recall_require_verified_actor is False and s.risk_cluster_dup_scan is False


def test_bool_env_falls_back_on_garbage(tmp_path, reload_config):
    """알 수 없는 값은 기본값 — 오타가 조용히 보안 스위치를 끄지 않게 한다."""
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_PAT_REQUIRE_READ_ONLY="maybe",
                        HWAXRISK_SOURCE_DRIFT_BLOCK="")
    assert mod.settings.risk_pat_require_read_only is True
    assert mod.settings.risk_source_drift_block is False


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


def test_cred_key_is_created_0600_and_reused(tmp_path, caplog):
    """없으면 만들고(0600·Fernet 키 형식), 두 번째 호출은 같은 키를 돌려준다(plan §8.2.7)."""
    path = config.cred_key_path(tmp_path)
    assert path.name == "cred.key" and not path.exists()
    with caplog.at_level("INFO", logger="hwax_risk.config"):
        key = config.load_cred_key(tmp_path)
    assert key is not None and len(key) == 44  # 32 바이트의 urlsafe base64.
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert key.decode() not in caplog.text  # 키 값은 로그에 싣지 않는다.
    assert config.load_cred_key(tmp_path) == key
    from cryptography.fernet import Fernet

    assert Fernet(key).decrypt(Fernet(key).encrypt(b"x")) == b"x"


def test_cred_key_absent_without_create(tmp_path):
    assert config.load_cred_key(tmp_path, create=False) is None
    assert not config.cred_key_path(tmp_path).exists()


def test_cred_key_warns_on_loose_mode(tmp_path, caplog):
    key = config.load_cred_key(tmp_path)
    config.cred_key_path(tmp_path).chmod(0o644)
    with caplog.at_level("WARNING", logger="hwax_risk.config"):
        assert config.load_cred_key(tmp_path) == key
    assert "0600" in caplog.text and key.decode() not in caplog.text


def test_cred_key_unwritable_dir_returns_none(tmp_path):
    """읽기 전용 데이터 루트(SIF rootfs 등)에서는 None — 호출자가 422 cred_key_absent 로 거부한다."""
    if os.geteuid() == 0:
        pytest.skip("root 는 쓰기 권한 검사를 우회한다")
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        assert config.load_cred_key(ro) is None
    finally:
        ro.chmod(0o700)


def test_cred_key_defaults_to_settings_data_dir():
    assert config.cred_key_path() == Path(config.settings.data_dir) / "cred.key"
