# .portal/manifest.yaml — HEAXHub 매니페스트 스키마(v2) 검증(허용 오류는 루트 mcp·source.ref 2건) + plan §8.2.2 확정값
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft7Validator

from app import config
from tests.conftest import REPO_ROOT

MANIFEST_PATH = REPO_ROOT / ".portal" / "manifest.yaml"
HEAX_SCHEMAS = Path("/home/koopark/claude/HEAXHub/schemas")
# HEAXHub manifest_validator.py 와 같은 분기 — v1 은 manifest.schema.json, v2 는 manifest.schema.v2.json.
SCHEMA_BY_VERSION = {1: HEAX_SCHEMAS / "manifest.schema.json", 2: HEAX_SCHEMAS / "manifest.schema.v2.json"}


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST_PATH.exists(), f"매니페스트가 없다: {MANIFEST_PATH}"
    m = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(m, dict)
    return m


def test_validates_against_heax_schema(manifest):
    version = int(manifest.get("schema_version", 1))
    schema_path = SCHEMA_BY_VERSION.get(version)
    if schema_path is None or not schema_path.exists():
        pytest.skip(f"HEAXHub 매니페스트 스키마가 없다: {schema_path}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # 루트 `mcp` 와 `source.ref` 는 게이트웨이·스캐너 확장 키로 v2 스키마에 없다(thermal_shock_mcp·materialtwin-web 도
    # 같은 형태로 등록됨, plan §8.2.2). 엄격 검증의 허용 오류는 정확히 이 2건이다.
    errors = sorted(f"{'.'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
                    for e in Draft7Validator(schema).iter_errors(manifest))
    assert errors == [
        "<root>: Additional properties are not allowed ('mcp' was unexpected)",
        "source: Additional properties are not allowed ('ref' was unexpected)",
    ]


def test_identity_values(manifest):
    assert manifest["schema_version"] == 2
    assert manifest["id"] == "hwax_risk"
    assert manifest["name"] == "HWAX Risk Review"
    assert manifest["version"] == "0.1.0"
    assert manifest["owner"] == "cae-automation"
    assert manifest["status"] == "beta"
    assert manifest["app_type"] == "web_app"
    assert manifest["execution_target"] == "linux_runner"
    assert manifest["description"].strip()
    assert isinstance(manifest.get("tags"), list) and manifest["tags"]


def test_build_launch_permissions_resources(manifest, tmp_path):
    assert manifest["build"]["type"] == "python_venv"
    assert manifest["build"]["stack"] == "fastapi_react"
    assert str(manifest["build"]["python_version"]) == "3.12"
    launch = manifest["launch"]
    assert launch["mode"] == "service"
    # HWAXRISK_DATA_DIR 은 넣지 않는다 — HEAX 런처의 HEAX_DATA_DIR 폴백만 쓴다(호스트 실행 시 /data 오지정 방지).
    # 반대로 HWAXRISK_PORTAL_BASE 는 **반드시** 여기 있어야 한다 — 코드 기본값이 dev vite 포트라
    # 빠지면 PAT 등록·폐기 대조·무인 패널이 전부 502 가 되고 토큰 탓처럼 보인다(context-notes D36).
    # HEAXHub `.env` 의 APPTAINERENV_* 는 `.env` 를 소싱하지 않은 재배포에서 조용히 빠지므로 대안이 못 된다.
    assert launch["env"] == {"PYTHONNOUSERSITE": "1", "HWAXRISK_PORTAL_BASE": "http://127.0.0.1:8088"}
    code_default = config.load_settings(env={"HWAXRISK_DATA_DIR": str(tmp_path)}).portal_base
    assert launch["env"]["HWAXRISK_PORTAL_BASE"] != code_default, (
        "매니페스트가 코드 기본값과 같아지면 이 고정이 아무것도 막지 못한다")
    assert launch["health_check"] == {"type": "http", "path": "/api/health"}
    assert "restart_policy" in launch
    assert manifest["permissions"]["visibility"] == "company"
    assert manifest["resources"] == {"cpu": 1, "memory_gb": 2, "gpu": False}


def test_source_and_mcp(manifest):
    assert manifest["source"] == {"type": "git", "url": "https://github.com/squall321/HWAXRisk.git", "ref": "main"}
    mcp = manifest["mcp"]
    assert mcp["expose"] is True
    assert mcp["path"] == "/mcp"
    assert mcp["transport"] == "streamable_http"
    assert mcp["allowed_groups"] == []
    assert "risk_get_brief" in mcp["description"] and "risk_submit_panel_result" in mcp["description"]


def test_description_mentions_tools_and_paths(manifest):
    desc = manifest["description"]
    for token in ("risk_get_snapshot", "risk_get_diff", "risk_get_registry", "risk_claims_for_ref", "risk_get_brief",
                  "risk_submit_panel_result", "/apps/hwax_risk/mcp", "/api/health", "/apps/hwax_risk/api",
                  "risk_review.db", "HWAXRISK_DATA_DIR"):
        assert token in desc, f"description 에 {token} 이 없다"
    for stale in ("risk_health", "risk_get_taxonomy", "risk_get_meta", "HWAX_RISK_", "/api/v1", "hwax_risk.db"):
        assert stale not in desc, f"description 에 옛 표기 {stale} 가 남아 있다"
