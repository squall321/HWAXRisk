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


# ---------------------------------------------------------------- MCP 브리프 예산 ↔ JS 파이프라인(WP1 S9 · R-51)
def _js_number(js_text: str, pattern: str) -> float:
    import re

    found = re.search(pattern, js_text)
    if found is None:
        pytest.fail(f"hwax-deliberate.js 에서 근거 상한 식을 찾지 못했다({pattern}) — 식이 바뀌었으면 이 시험과 "
                    "brief.PROFILE_MCP 를 같이 고친다")
    return float(found.group(1))


def test_mcp_profile_is_the_js_pipeline_limits(engine_files):
    """MCP 보충 경로의 브리프 크기(`brief.PROFILE_MCP`)가 JS 가 기본 창에서 유도하는 근거 상한과 같다.

    JS 가 창(ctxTokens)·출력 몫·비율·바닥을 바꾸면 이 시험이 붉어진다 — 앱이 옛 크기로 보내면 JS 가 뒤 항목을 통째로 빼거나
    (앱이 더 크다) 좌석이 받을 수 있는 것을 앱이 미리 잘라 버린다(앱이 더 작다). 실제 JS 소스에서 식의 수를 읽는다.
    """
    from app import brief

    _, _, js, _, _ = engine_files
    text = js.read_text(encoding="utf-8")
    ctx = _js_number(text, r"const CTX_TOKENS = Math\.max\(16384, Math\.round\(Number\(A\.ctxTokens\) \|\| (\d+)\)\)")
    reserve = _js_number(text, r"const PROMPT_ROOM = Math\.max\(0, CTX_TOKENS - (\d+)\)")
    share, floor = (_js_number(text, r"const EV_BUDGET = roomShare\(([\d.]+), \d+\)"),
                    _js_number(text, r"const EV_BUDGET = roomShare\([\d.]+, (\d+)\)"))
    item_share, item_floor = (_js_number(text, r"const EV_ITEM_MAX = roomShare\(([\d.]+), \d+\)"),
                              _js_number(text, r"const EV_ITEM_MAX = roomShare\([\d.]+, (\d+)\)"))
    wide, narrow = (_js_number(text, r"const EV_MAX_ITEMS = EV_BUDGET > \d+ \? (\d+) : \d+"),
                    _js_number(text, r"const EV_MAX_ITEMS = EV_BUDGET > \d+ \? \d+ : (\d+)"))
    room = max(0, ctx - reserve)
    ev_budget = max(floor, int(room * share))
    ev_item = max(item_floor, int(room * item_share))
    ev_items = wide if ev_budget > floor else narrow
    assert (brief.PROFILE_MCP.budget, brief.PROFILE_MCP.item_result_max, brief.PROFILE_MCP.max_items) == \
        (ev_budget, ev_item, ev_items)
    # 바닥은 앱과 JS 가 같은 값이다(작은 창의 종전 크기).
    assert (floor, item_floor, narrow) == (brief.ENGINE_BUDGET, brief.CLAMP_RESULT, brief.EVIDENCE_MAX_ITEMS)
    # JS 는 줄마다 `[e:N|KEY] ` 를 붙여 예산에 센다 — 12항목의 그 머리까지 더해도 넘지 않는다(Σ 상한 = 예산 × 10600/11000).
    caps = sum(brief.PROFILE_MCP.cap(k) for k in brief.ITEM_ORDER)
    heads = sum(len(f"[e:{n}|{key}] ") for n, key in enumerate(brief.ITEM_ORDER, start=1))
    assert caps + heads <= ev_budget
    # 곁 필드 상한도 같은 값이다(앱이 그 안으로 만들어 보내면 JS 가 다시 끊지 않는다).
    assert "const EV_SRC_MAX = 200, EV_TOOL_MAX = 80, EV_ARGS_MAX = 1200" in text
    assert (brief.CLAMP_SOURCE, brief.CLAMP_TOOL, brief.CLAMP_ARGS) == (200, 80, 1200)


def test_question_carries_the_engines_diff_mark(engine_files, risk_store):
    """앱 질문의 `diff_id=<id>` 가 엔진이 찾는 표식(`deliberation._RISK_DIFF_MARK`)과 글자까지 같다 — 한쪽만 바꾸면 엔진의
    `risk_get_diff` 고정과 변경 전체 안내가 말없이 꺼진다(WP1 S11 · workorder-c 5절 4). 엔진 소스의 실제 상수를 읽는다."""
    from app import runner
    from tests import factories

    _, py, _, tree, _ = engine_files
    found = [node.value for node in tree.body
             if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_RISK_DIFF_MARK"
                                                     for t in node.targets)]
    if not found or not isinstance(found[0], ast.Constant) or not isinstance(found[0].value, str):
        pytest.fail(f"{py} 에 문자열 상수 _RISK_DIFF_MARK 가 없다 — 이름이 바뀌었으면 이 시험과 runner.panel_question 을 같이 고친다")
    mark = found[0].value
    synth = factories.make_diff_target(risk_store, 3)
    question = runner.panel_question(risk_store, synth.target_key, diff_ref=True)
    assert f"{mark}{synth.diff_id}" in question
