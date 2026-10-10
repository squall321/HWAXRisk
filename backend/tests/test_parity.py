# 엔진 파리티(plan §8.3.1) — 포털 리포(env HWAX_PORTAL_REPO, 없으면 형제 ../HWAXPortal)가 곁에 있으면 PY/JS/JSON 문자열 동일 검사, 없을 때만 skip
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import BACKEND_DIR, REPO_ROOT

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
    """포털·엔진 리포의 파리티 대상 파일. 리포가 곁에 없을 때만 건너뛴다.

    형제가 곁에 있는데 파일·상수를 못 찾으면 건너뛰지 않고 실패한다 — 이름이 바뀐 것이고, 건너뛰면 좌석 계약만 고친
    리스크 리포 커밋이 이 리포의 시험으로는 영영 잡히지 않는다(WP5b 2.6절). 같은 폴백을 `test_wiring_regressions` 가 쓴다.
    """
    portal = Path(os.environ.get("HWAX_PORTAL_REPO") or REPO_ROOT.parent / "HWAXPortal")
    if not portal.is_dir():
        pytest.skip(f"포털 리포가 곁에 없다(HWAX_PORTAL_REPO 또는 ../HWAXPortal) — {portal}")
    py = portal.parent / "HWAXAgentServer" / "deliberation.py"
    js = portal / "infra" / "pipeline" / "hwax-deliberate.js"
    if not py.is_file() or not js.is_file():
        pytest.fail(f"포털 리포는 곁에 있는데 엔진 파일이 없다({py} · {js}) — 경로가 바뀌었으면 이 시험을 같이 고친다")
    tree = ast.parse(py.read_text(encoding="utf-8"))
    items = _dict_value(tree, "_CHAIR_ITEMS", "risk-review")
    if not items:
        pytest.fail("deliberation.py 에 _CHAIR_ITEMS['risk-review'] 가 없다 — 이름이 바뀌었으면 이 시험을 같이 고친다")
    return portal, py, js, tree, items


def test_chair_parity_script_if_present(engine_files):
    """포털 scripts/check_chair_parity.py 가 정본 검사다(exit 0). 포털이 곁에 있는데 검사기가 없으면 실패다."""
    portal, py, js, _, _ = engine_files
    script = portal / "scripts" / "check_chair_parity.py"
    if not script.is_file():
        pytest.fail(f"포털 리포에 파리티 검사기가 없다 — {script}")
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
