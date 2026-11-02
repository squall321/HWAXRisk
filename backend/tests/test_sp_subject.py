# 과제 주제(SP 과제 key · 차수) 시험 — 차수 정규화가 에이전트 서버와 같은 규칙인지 형제 리포의 원문에 대고 견준다(과제 인사이트 그래프 M2b)
"""HWAXPortal docs/project-insight-graph contracts §9 · PLAN §4.6.

  · 차수는 NFKC · 유니코드 White_Space 빼기 · 소문자만 하고 개발 단계 코드 열한 개에 글자 그대로 있을 때만이다 — 에이전트 서버
    `delib_subject.norm_round` 와 같은 규칙이어야 포털 과제 보기의 (과제, 차수) 칸에서 두 원천이 만난다. 형제 리포의 원문(리포 루트의
    `../HWAXAgentServer/delib_subject.py`)에서 STAGES · _SPACE_RE · norm_round 를 떼어 그 자리에서 돌려 견준다(없으면 건너뛴다).

  실행:  .venv/bin/python -m pytest tests/test_sp_subject.py
"""
from __future__ import annotations

import ast
import re
import unicodedata

import pytest

from app import sp_subject
from app.errors import AppError
from tests.conftest import REPO_ROOT

AGENT_SOURCE = REPO_ROOT.parent / "HWAXAgentServer" / "delib_subject.py"
AGENT_NAMES = {"STAGES", "_SPACE_RE", "norm_round"}


def _agent() -> dict:
    """형제 리포 원문의 STAGES · _SPACE_RE · norm_round 만 떼어 돌린 이름표 — 모듈을 import 하지 않는다(그 모듈이 쓰는 다른 이름이 이 venv 에
    없어도 견줄 수 있게). 원문이 없으면 건너뛴다."""
    if not AGENT_SOURCE.is_file():
        pytest.skip(f"형제 리포의 원문이 없다 — {AGENT_SOURCE}")
    tree = ast.parse(AGENT_SOURCE.read_text(encoding="utf-8"), filename=str(AGENT_SOURCE))
    body = [node for node in tree.body
            if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in AGENT_NAMES for t in node.targets))
            or (isinstance(node, ast.FunctionDef) and node.name in AGENT_NAMES)]
    found = {t.id for node in body if isinstance(node, ast.Assign) for t in node.targets if isinstance(t, ast.Name)} | {
        node.name for node in body if isinstance(node, ast.FunctionDef)}
    assert found == AGENT_NAMES, f"에이전트 원문에서 {sorted(AGENT_NAMES - found)} 를 찾지 못했다 — 이름이 바뀌었으면 이 시험을 고친다"
    names: dict = {"re": re, "unicodedata": unicodedata}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(AGENT_SOURCE), "exec"), names)  # noqa: S102 — 형제 리포의 순수 함수 하나
    return names


# 코드로 읽히는 것 · 아닌 것이 섞인 까다로운 입력 — 에이전트 시험의 묶음에 전각 숫자 · 로마 숫자 · 원 숫자(NFKC 가 숫자로 편다) · 공백이 아닌
# 보이지 않는 글자(BOM · 폭 없는 공백 · 이음 · 몽골 모음 구분 · 소프트 하이픈 · 정보 분리)를 더했다.
TRICKY = [
    "dv1", "DV1", " Dv 2 ", "ＤＶ１", "ｐｖｒ", "PRE", "mp", "M P", "pra", "dvr", "pv3", "　dv3　", "dv 1", "dv\u00851",
    "\tdv\n2\r", "pv 1", "Ｍｐ", "ＤＶＲ", "dv①", "ⅾⅴ1", "dv 1", " pre", "pv 2", "dv 1", "ＰＲＡ　",
    "2차", "C2", "c2", "양산", "선행", "DV", "dv", "pre1", "pv4", "dv-1", "dv_1", "dv0", "mp1", "", "  ", "dv1차", "PV 1차",
    "dv1﻿", "﻿pv2", "dv\u001f1", "dv\u001c1", "dv​1", "dv‍1", "dv⁠1", "dv᠎1", "dv­1",
    "D́V1", "PV-1", "pv1.", "ｄｖ－１",
]


def test_the_stages_and_the_space_class_are_the_agents_letter_for_letter():
    """열한 코드(차례까지)와 빼는 공백 글자 묶음(정규식 글 그대로)이 에이전트 서버의 것과 같다."""
    agent = _agent()
    assert sp_subject.STAGES == agent["STAGES"]
    assert sp_subject._SPACE_RE.pattern == agent["_SPACE_RE"].pattern


def test_norm_round_answers_like_the_agent_on_tricky_inputs():
    """같은 입력에 같은 답이다 — 글이 아닌 값도(None · 수 · 바이트 · 목록). 묶음에는 코드로 읽히는 것과 아닌 것이 둘 다 있다."""
    agent = _agent()["norm_round"]
    for raw in [*TRICKY, None, 1, b"dv1", ["dv1"]]:
        assert sp_subject.norm_round(raw) == agent(raw), repr(raw)
    answers = {sp_subject.norm_round(raw) for raw in TRICKY}
    assert None in answers and {"dv1", "dv2", "pvr", "mp", "pra"} <= answers


@pytest.mark.parametrize("raw,want", [
    ("dv1", "dv1"), ("DV1", "dv1"), (" Dv 2 ", "dv2"), ("ＤＶ１", "dv1"), ("ｐｖｒ", "pvr"), ("PRE", "pre"), ("M P", "mp"),
    ("　dv3　", "dv3"), ("dv 1", "dv1"), ("\tdv\n2\r", "dv2"), ("pv 1", "pv1"), ("dv①", "dv1"),
])
def test_norm_round_keeps_only_width_space_and_case_folding(raw, want):
    assert sp_subject.norm_round(raw) == want


@pytest.mark.parametrize("raw", ["2차", "C2", "양산", "선행", "DV", "dv", "pre1", "pv4", "dv-1", "dv_1", "mp1", "", "dv1﻿",
                                 "dv\u001f1", "dv​1", "PV-1"])
def test_anything_else_is_round_unknown(raw):
    """하이픈 · 밑줄을 빼지 않고 '2차' · 'C2' · '양산' · 웹 폼의 'dv' · 'pre1' 을 코드로 읽지 않는다 — 공백이 아닌 글자(BOM · 정보 분리 ·
    폭 없는 공백)도 빼지 않는다(PLAN §4.6)."""
    assert sp_subject.norm_round(raw) is None


def test_the_write_round_is_a_code_or_nothing():
    """쓰기의 round — 비면 stage 를 그대로 두고(None), 코드면 그 코드, 아니면 422 round_invalid(허용값을 detail 에)."""
    assert sp_subject.parse_round(None) is None and sp_subject.parse_round("") is None and sp_subject.parse_round("  ") is None
    assert sp_subject.parse_round(" ＤＶ２ ") == "dv2" and sp_subject.parse_round("MP") == "mp"
    for raw in ("dv", "pre1", "2차", "C2", "unknown", "모름"):
        with pytest.raises(AppError) as err:
            sp_subject.parse_round(raw)
        assert (err.value.code, err.value.http_status, err.value.detail) == (
            "round_invalid", 422, {"allowed": list(sp_subject.STAGES)}), raw


def test_the_find_round_filter_takes_codes_and_unknown_only():
    """찾기의 round — 비면 모든 차수(None), unknown · 모름 은 차수 모름 칸, 코드는 그 코드, 아니면 422(아무것도 안 걸리는 거름을 말없이
    돌려주지 않는다)."""
    assert sp_subject.parse_round_filter(None) is None and sp_subject.parse_round_filter(" ") is None
    assert sp_subject.parse_round_filter("UNKNOWN") == sp_subject.parse_round_filter("모름") == sp_subject.ROUND_UNKNOWN
    assert sp_subject.parse_round_filter("Pv1") == "pv1"
    with pytest.raises(AppError) as err:
        sp_subject.parse_round_filter("C2")
    assert (err.value.code, err.value.http_status) == ("round_invalid", 422)
    assert err.value.detail == {"allowed": [*sp_subject.STAGES, sp_subject.ROUND_UNKNOWN]}
