# 엔진 파리티(plan §8.3.1) — env HWAX_PORTAL_REPO 와 deliberation.py 의 _CHAIR_ITEMS['risk-review'] 가 있을 때만 PY/JS/JSON 문자열 동일 검사, 아니면 skip
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import BACKEND_DIR

SEAT_CONTRACT = BACKEND_DIR / "app" / "assets" / "seat-contract.v1.json"
DOC_TITLE = "리스크 심사 보고서"


def _dict_value(tree: ast.Module, name: str, key: str) -> str | None:
    """모듈 최상위 `name = {...}` 에서 key 의 문자열 값(암시적 연결 포함)을 꺼낸다. 없으면 None."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets) \
                and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and k.value == key:
                    try:
                        return ast.literal_eval(v) if isinstance(v, (ast.Constant, ast.Dict)) else None
                    except ValueError:
                        return None
    return None


@pytest.fixture(scope="module")
def engine_files():
    portal = os.environ.get("HWAX_PORTAL_REPO")
    if not portal:
        pytest.skip("HWAX_PORTAL_REPO 미설정 — P0 엔진 additive 미착수")
    portal = Path(portal)
    py = portal.parent / "HWAXAgentServer" / "deliberation.py"
    js = portal / "infra" / "pipeline" / "hwax-deliberate.js"
    if not py.is_file() or not js.is_file():
        pytest.skip(f"엔진 파일 없음({py} · {js}) — P0 엔진 additive 미착수")
    tree = ast.parse(py.read_text(encoding="utf-8"))
    items = _dict_value(tree, "_CHAIR_ITEMS", "risk-review")
    if not items:
        pytest.skip("deliberation.py 에 _CHAIR_ITEMS['risk-review'] 없음 — P0 엔진 additive 미착수")
    return portal, py, js, tree, items


def test_chair_parity_script_if_present(engine_files):
    """포털 scripts/check_chair_parity.py 가 있으면 그것이 정본 검사다(exit 0)."""
    portal, py, js, _, _ = engine_files
    script = portal / "scripts" / "check_chair_parity.py"
    if not script.is_file():
        pytest.skip("scripts/check_chair_parity.py 미작성 — P0 엔진 additive 미착수")
    r = subprocess.run([sys.executable, str(script), "--py", str(py), "--js", str(js), "--contract", str(SEAT_CONTRACT)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_strings_identical_in_py_js_json(engine_files):
    """결정문 항목·제목·좌석 계약 16 문자열이 PY/JS/JSON 에 바이트 동일하게 존재한다."""
    _, _, js, tree, items = engine_files
    js_text = js.read_text(encoding="utf-8")
    assert isinstance(items, str) and items in js_text, "CHAIR_ITEMS['risk-review'] 가 JS 에 바이트 동일하게 없다"
    assert DOC_TITLE in js_text and DOC_TITLE in ast.unparse(tree)

    contract = json.loads(SEAT_CONTRACT.read_text(encoding="utf-8"))["contract"]
    assert len(contract) == 16 and "_common" in contract
    py_contract = _dict_value(tree, "_RISK_SEAT_CONTRACT", "_common")
    assert py_contract == contract["_common"]
    for key, text in contract.items():
        assert _dict_value(tree, "_RISK_SEAT_CONTRACT", key) == text, f"PY 좌석 계약 불일치: {key}"
        assert text in js_text, f"JS 좌석 계약 불일치: {key}"
