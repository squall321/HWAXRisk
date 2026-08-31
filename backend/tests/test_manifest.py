# .portal/manifest.yaml — HEAXHub 매니페스트 스키마(schema_version 별 파일) 검증 + hwax_risk 확정값
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft7Validator

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

    # 루트 `mcp` 와 `source.ref` 는 게이트웨이·스캐너 확장 키로 v2 스키마에 없다(thermal_shock_mcp·
    # materialtwin-web 도 같은 형태로 등록됨, plan §8.2.2). 그 둘만 떼어 내고 나머지는 엄격히 검증한다.
    stripped = copy.deepcopy(manifest)
    stripped.pop("mcp", None)
    if isinstance(stripped.get("source"), dict):
        stripped["source"].pop("ref", None)
    errors = [f"{'.'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
              for e in Draft7Validator(schema).iter_errors(stripped)]
    assert errors == []


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


def test_build_launch_permissions_resources(manifest):
    assert manifest["build"]["type"] == "python_venv"
    assert manifest["build"]["stack"] == "fastapi_react"
    assert str(manifest["build"]["python_version"]) == "3.12"
    launch = manifest["launch"]
    assert launch["mode"] == "service"
    assert launch["env"] == {"PYTHONNOUSERSITE": "1"}
    assert launch["health_check"] == {"type": "http", "path": "/api/health"}
    assert "restart_policy" in launch
    assert manifest["permissions"]["visibility"] == "team"
    assert manifest["resources"] == {"cpu": 1, "memory_gb": 1, "gpu": False}


def test_source_and_mcp(manifest):
    assert manifest["source"] == {"type": "git", "url": "https://github.com/squall321/HWAXRisk.git", "ref": "main"}
    mcp = manifest["mcp"]
    assert mcp["expose"] is True
    assert mcp["path"] == "/mcp"
    assert mcp["transport"] == "streamable_http"


def test_description_mentions_tools_and_paths(manifest):
    desc = manifest["description"]
    for token in ("risk_health", "risk_get_taxonomy", "risk_get_meta", "/apps/hwax_risk/mcp", "/api/health",
                  "/apps/hwax_risk/api", "risk_review.db", "HWAX_RISK_DATA_DIR"):
        assert token in desc, f"description 에 {token} 이 없다"
