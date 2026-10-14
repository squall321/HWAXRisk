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
             "HWAXRISK_CREDENTIAL_MARGIN_S", "HWAXRISK_PORTAL_CALL_TIMEOUT_S", "HWAXRISK_SOURCE_CALL_TIMEOUT_S",
             "HWAXRISK_ENGINE_BUSY_WAIT_S", "HWAXRISK_ENGINE_BUSY_MAX_WAIT_S", "HWAXRISK_FIELD_TIMEOUT_S",
             "HWAXRISK_ROSTER_DEADLINE_S", *(k.env for k in config.BOX_KNOBS))


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
    assert s.risk_portal_call_timeout_s == 30
    assert s.risk_source_call_timeout_s == 120
    assert s.risk_engine_busy_wait_s == 30
    assert s.risk_engine_busy_max_wait_s == 3600
    assert s.risk_field_timeout_s == 20
    assert s.risk_roster_deadline_s == 540


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
    # 명단 조회는 nginx /apps/ (proxy_read_timeout 600초) 안의 동기 요청이다 — 넘겨 듣는 폭(게이트웨이 ping 한 칸
    # 15초)을 더해도 프록시보다 먼저 스스로 끝나야 한다.
    assert 15 < s.risk_roster_deadline_s == 540 and s.risk_roster_deadline_s + 15 < 600

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
    # 429 대기 예산을 올리면 자격 여유가 같은 폭으로 따라간다 — 여유가 그 몫을 따로 적어 두던 동안에는
    # 기다리는 시간만 늘어 대기 중에 PAT 가 만료될 수 있었다.
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_ENGINE_BUSY_MAX_WAIT_S="7200",
                        HWAXRISK_ENGINE_BUSY_WAIT_S="10")
    assert (mod.engine_busy_wait_s(mod.settings), mod.engine_busy_max_wait_s(mod.settings)) == (10, 7200)
    assert mod.credential_margin_s(mod.settings) == 43200 + 7200 + 600
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_PORTAL_CALL_TIMEOUT_S="45")
    assert mod.settings.risk_portal_call_timeout_s == 45
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_SOURCE_CALL_TIMEOUT_S="300")
    assert mod.settings.risk_source_call_timeout_s == 300
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_FIELD_TIMEOUT_S="45")
    assert mod.settings.risk_field_timeout_s == 45
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_ROSTER_DEADLINE_S="300")
    assert mod.settings.risk_roster_deadline_s == 300


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


# ---------------------------------------------------------------- 카드 대조 검토 손잡이(재설계 M2.md 4.5)
REVIEW_DEFAULTS = {
    "HWAXRISK_REVIEW_ENABLED": False, "HWAXRISK_UNIT_TARGET_LINES": 20, "HWAXRISK_UNIT_MAX_LINES": 40,
    "HWAXRISK_UNITS_SMALL_LINES": 15, "HWAXRISK_UNITS_MAX": 60, "HWAXRISK_REVIEW_CONCURRENCY": 4,
    "HWAXRISK_REVIEW_CALL_TIMEOUT_S": 18000, "HWAXRISK_REVIEW_READ_TIMEOUT_S": 300, "HWAXRISK_REVIEW_MAX_CHARGED": 2,
    "HWAXRISK_REVIEW_CONSENT_CALLS": 1500, "HWAXRISK_REVIEW_MAX_CALLS": 30000,
    # 재설계 M3.md 4.5 의 거르기 손잡이(C3-6)
    "HWAXRISK_REVIEW_FILTER": "on", "HWAXRISK_FILTER_AUDIT_PCT": 5,
    "HWAXRISK_REVIEW_DUAL": "flagged", "HWAXRISK_REVIEW_DUAL_NEG_PCT": 10,     # 이중 판정(C3-9 — M3.md 4.5, #32)
}


def _knobs_file(data_dir: Path, text: str) -> None:
    (data_dir / "knobs.env").write_text(text, encoding="utf-8")


def test_review_knobs_default_to_the_plan_table(tmp_path, reload_config):
    """손잡이의 코드 기본값은 M2.md 4.5 · M3.md 4.5 표 그대로이고, 아무것도 적지 않은 박스는 출처가 전부 default 다."""
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path))
    knobs = mod.review_knobs(mod.settings)
    assert {name: k["value"] for name, k in knobs.items()} == REVIEW_DEFAULTS
    assert {k["source"] for k in knobs.values()} == {"default"}
    assert mod.review_enabled(mod.settings) is False


def test_knobs_env_overrides_the_default_and_the_environment_overrides_knobs_env(tmp_path, reload_config):
    """순서는 환경변수 > $DATA_DIR/knobs.env > 코드 기본값이고 출처가 값마다 남는다. 빈 값은 적지 않은 것이다."""
    _knobs_file(tmp_path, "# 박스마다 켠다\nHWAXRISK_REVIEW_ENABLED=1\nHWAXRISK_UNITS_MAX=80\n"
                          "HWAXRISK_REVIEW_READ_TIMEOUT_S=600\nHWAXRISK_REVIEW_MAX_CALLS=\nOTHER=1\n")
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_UNITS_MAX="90", HWAXRISK_REVIEW_CONCURRENCY=" ")
    s = mod.settings
    assert (s.risk_review_enabled, s.risk_units_max, s.risk_review_read_timeout_s) == (True, 90, 600)
    assert (s.risk_review_concurrency, s.risk_review_max_calls) == (4, 30000)
    knobs = mod.review_knobs(s)
    assert knobs["HWAXRISK_REVIEW_ENABLED"] == {"value": True, "source": "knobs.env"}
    assert knobs["HWAXRISK_UNITS_MAX"] == {"value": 90, "source": "env"}
    assert knobs["HWAXRISK_REVIEW_READ_TIMEOUT_S"] == {"value": 600, "source": "knobs.env"}
    assert knobs["HWAXRISK_REVIEW_CONCURRENCY"]["source"] == "default"
    assert knobs["HWAXRISK_REVIEW_MAX_CALLS"]["source"] == "default"
    assert "OTHER" not in knobs
    # 줄 끝 주석은 떼고 읽는다 — 종전에는 '1  # 파일럿' 이 모르는 낱말이라 스위치가 조용히 꺼졌다(RC-5).
    _knobs_file(tmp_path, "HWAXRISK_REVIEW_ENABLED=1  # 파일럿\nHWAXRISK_UNITS_MAX=80 # 9명\nHWAXRISK_REVIEW_MAX_CALLS=# 나중에\n")
    s = reload_config(HWAXRISK_DATA_DIR=str(tmp_path)).settings
    assert (s.risk_review_enabled, s.risk_units_max, s.risk_review_max_calls) == (True, 80, 30000)


def test_a_switch_word_that_is_not_on_or_off_stops_the_boot_and_says_where(tmp_path):
    """켜기 스위치에 켜기·끄기 낱말이 아닌 값이 있으면 기동을 막는다(RC-5) — 종전에는 모르는 낱말이 기본값(꺼짐)이라 오타 하나로
    스위치가 조용히 꺼졌고, 환경변수의 오타가 파일의 true 를 덮어 껐다. 낱말은 대소문자를 가리지 않는다."""
    _knobs_file(tmp_path, "HWAXRISK_REVIEW_ENABLED=maybe\n")
    with pytest.raises(RuntimeError) as exc:
        config.load_settings(env={"HWAXRISK_DATA_DIR": str(tmp_path)})
    assert "HWAXRISK_REVIEW_ENABLED='maybe'" in str(exc.value) and str(tmp_path / "knobs.env") in str(exc.value)
    _knobs_file(tmp_path, "HWAXRISK_REVIEW_ENABLED=true\n")
    with pytest.raises(RuntimeError) as exc:
        config.load_settings(env={"HWAXRISK_DATA_DIR": str(tmp_path), "HWAXRISK_REVIEW_ENABLED": "enable"})
    assert "HWAXRISK_REVIEW_ENABLED='enable'" in str(exc.value) and "환경변수" in str(exc.value)
    for word, on in (("ON", True), ("Yes", True), ("off", False), ("0", False)):
        got = config.load_settings(env={"HWAXRISK_DATA_DIR": str(tmp_path), "HWAXRISK_REVIEW_ENABLED": word})
        assert got.risk_review_enabled is on, word


def test_a_choice_knob_takes_only_its_words_and_says_where(tmp_path):
    """선택지 손잡이(재설계 M3 C3-6 의 HWAXRISK_REVIEW_FILTER)는 그 낱말만 받는다 — 대소문자는 가리지 않고, 밖의 값은 기동을 막으며
    어느 자리의 어느 손잡이인지와 고를 낱말을 말한다(불리언과 같은 규율 — 오타가 조용히 기본값으로 돌지 않는다)."""
    for word, want in (("shadow", "shadow"), ("OFF", "off"), ("On", "on")):
        got = config.load_settings(env={"HWAXRISK_DATA_DIR": str(tmp_path), "HWAXRISK_REVIEW_FILTER": word})
        assert got.risk_review_filter == want, word
    def boot_error(env: dict) -> str:
        try:
            config.load_settings(env=env)
        except RuntimeError as exc:
            return str(exc)
        return ""                                     # 기동했다 — 아래 단언이 실패한다

    _knobs_file(tmp_path, "HWAXRISK_REVIEW_FILTER=shadows\n")
    text = boot_error({"HWAXRISK_DATA_DIR": str(tmp_path)})
    assert "HWAXRISK_REVIEW_FILTER='shadows'" in text and str(tmp_path / "knobs.env") in text
    assert "off · shadow · on" in text
    text = boot_error({"HWAXRISK_DATA_DIR": str(tmp_path / "x"), "HWAXRISK_REVIEW_FILTER": "1"})
    assert "HWAXRISK_REVIEW_FILTER='1'" in text and "환경변수" in text
    assert config.load_settings(env={"HWAXRISK_DATA_DIR": str(tmp_path / "y"),
                                     "HWAXRISK_REVIEW_DUAL": "ALL"}).risk_review_dual == "all"
    assert "flagged · all" in boot_error({"HWAXRISK_DATA_DIR": str(tmp_path / "y"), "HWAXRISK_REVIEW_DUAL": "flag"})


@pytest.mark.parametrize("name,raw", [
    ("HWAXRISK_UNIT_MAX_LINES", "0"), ("HWAXRISK_UNIT_TARGET_LINES", "-3"), ("HWAXRISK_UNITS_SMALL_LINES", "0"),
    ("HWAXRISK_UNITS_MAX", "0"), ("HWAXRISK_REVIEW_CONCURRENCY", "0"), ("HWAXRISK_REVIEW_CALL_TIMEOUT_S", "-1"),
    ("HWAXRISK_REVIEW_READ_TIMEOUT_S", "-5"), ("HWAXRISK_REVIEW_MAX_CHARGED", "0"), ("HWAXRISK_REVIEW_MAX_CALLS", "0"),
    ("HWAXRISK_REVIEW_CONSENT_CALLS", "-1"), ("HWAXRISK_FILTER_AUDIT_PCT", "-1"), ("HWAXRISK_REVIEW_DUAL_NEG_PCT", "-1"),
])
def test_a_knob_below_its_floor_stops_the_boot_and_says_where(tmp_path, name, raw):
    """정수 손잡이는 하한을 본다(RC-5) — 단위 크기·워커·한도·상한은 1 이상, 시간은 0(끔) 이상, 동의 기준은 0 이상. 종전에는
    -1 초가 '끔' 으로 돌면서 /api/meta/runtime 에는 -1 로 보였고, 단위 크기 0 은 모든 빌드를 불변식 실패로 만들었다."""
    _knobs_file(tmp_path, f"{name}={raw}\n")
    with pytest.raises(RuntimeError) as exc:
        config.load_settings(env={"HWAXRISK_DATA_DIR": str(tmp_path)})
    assert f"{name}={raw!r}" in str(exc.value) and "이상이어야" in str(exc.value) and "knobs.env" in str(exc.value)


def test_zero_still_turns_a_time_limit_off(tmp_path):
    _knobs_file(tmp_path, "HWAXRISK_REVIEW_CALL_TIMEOUT_S=0\nHWAXRISK_REVIEW_READ_TIMEOUT_S=0\nHWAXRISK_REVIEW_CONSENT_CALLS=0\n")
    got = config.load_settings(env={"HWAXRISK_DATA_DIR": str(tmp_path)})
    assert (got.risk_review_call_timeout_s, got.risk_review_read_timeout_s, got.risk_review_consent_calls) == (0, 0, 0)


def test_a_knob_that_is_not_an_integer_stops_the_boot_and_says_where(tmp_path, reload_config):
    """정수 자리에 정수가 아닌 값이 있으면 기동을 막는다 — 조용히 기본값으로 돌면 박스에 적은 값이 안 듣는 것을 아무도 모른다."""
    _knobs_file(tmp_path, "HWAXRISK_UNITS_MAX=sixty\n")
    with pytest.raises(RuntimeError) as exc:
        config.load_settings(env={"HWAXRISK_DATA_DIR": str(tmp_path)})
    assert "HWAXRISK_UNITS_MAX" in str(exc.value) and "knobs.env" in str(exc.value)
    with pytest.raises(RuntimeError) as exc:
        config.load_settings(env={"HWAXRISK_DATA_DIR": str(tmp_path / "x"), "HWAXRISK_REVIEW_CALL_TIMEOUT_S": "5h"})
    assert "HWAXRISK_REVIEW_CALL_TIMEOUT_S" in str(exc.value) and "환경변수" in str(exc.value)


def test_review_time_accessors_follow_their_knobs(tmp_path, reload_config):
    """검토 자격 여유는 호출 벽시계 + 600 이다(기다림은 호출마다 자격을 다시 골라 넣지 않는다). 벽시계를 끄면 기본 벽시계로 셈한다."""
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path))
    assert (mod.review_call_timeout_s(mod.settings), mod.review_read_timeout_s(mod.settings)) == (18000, 300)
    assert mod.review_credential_margin_s(mod.settings) == 18600 < 86400
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_REVIEW_CALL_TIMEOUT_S="0")
    assert mod.review_call_timeout_s(mod.settings) == 0 and mod.review_credential_margin_s(mod.settings) == 18600
    mod = reload_config(HWAXRISK_DATA_DIR=str(tmp_path), HWAXRISK_REVIEW_CALL_TIMEOUT_S="7200")
    assert mod.review_credential_margin_s(mod.settings) == 7800
