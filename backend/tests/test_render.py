# render.py 시험 — 판단어 린터 사전 17항의 양성·예외 문장, 정규 표기 원자, 섹션 순서·예산, summarize 결정론(plan §3.4)
from __future__ import annotations

import copy
import json
import math

import pytest

from app import render
from app.render import (
    JUDGEMENT_LEXICON,
    LEXICON_VERSION,
    MINUS,
    SUMMARY_MAX,
    JudgementLintError,
    assert_clean,
    fmt_change,
    fmt_iface,
    fmt_label,
    fmt_num,
    fmt_pct,
    fmt_refs,
    fmt_signed,
    fmt_value,
    lint_text,
    mask_neutral,
    quote_source,
    render_summary,
    signal_text,
    strip_quoted,
    summarize,
)
from tests.conftest import FIXTURES_DIR

# plan §3.4.3 사전표. (id, 잡혀야 하는 문장, 예외로 통과해야 하는 문장|None).
# 예외 문장은 allow 정규식 또는 부정 전방탐색으로 빠져나가는 자리를 그대로 옮긴 것이다.
LEXICON_CASES: list[tuple[str, str, str | None]] = [
    ("L01", "위험 구간이 3건 있다.", None),
    ("L02", "리스크가 커졌다.", "리스크 심사 대상이다."),
    ("L03", "개선 항목 1건.", None),
    ("L04", "악화 추세다.", None),
    ("L05", "안전 여유가 남았다.", "안전율=1.20"),
    ("L06", "문제 지점 2곳.", None),
    ("L07", "양호하다.", None),
    ("L08", "취약 계면이다.", None),
    ("L09", "심각 수준이다.", "경고 코드 3건"),
    ("L10", "재확인이 필요하다.", "재검사 필요"),
    ("L11", "부족 구간이다.", None),
    ("L12", "결과가 좋다.", None),
    ("L13", "강성이 저하 경향이다.", None),
    ("L14", "오류 3건.", "status=failed"),
    ("L15", "중대 등급이다.", "severity=중대"),
    ("L16", "FAIL 이다.", "judgement=FAIL"),
    ("L17", "판단 근거가 없다.", "상태 평가 표"),
]

LEXICON_IDS = [item["id"] for item in JUDGEMENT_LEXICON]

SNAP_SECTIONS = ["대상", "게이트", "구조", "상위 계면", "치수", "재료", "Dyna", "규칙", "씨앗", "결측"]
DIFF_SECTIONS = ["대상", "비교가능성", "구조", "의미", "치수", "재료", "결과", "씨앗"]


@pytest.fixture(scope="module")
def state() -> dict:
    return json.loads((FIXTURES_DIR / "rr_state" / "valid_clean.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def diff() -> dict:
    return json.loads((FIXTURES_DIR / "rr_diff" / "valid_pair_kind.json").read_text(encoding="utf-8"))


def _sections(text: str) -> list[str]:
    return [line.split("]", 1)[0][1:] for line in text.split("\n") if line.startswith("[")]


# ---------------------------------------------------------------- 판단어 린터(plan §3.4.3)

def test_lexicon_covers_the_plan_table():
    """사전 항목과 시험표가 1:1 이어야 한다 — 항목이 늘면 시험도 늘어야 한다."""
    assert LEXICON_IDS == [case[0] for case in LEXICON_CASES]


@pytest.mark.parametrize("lex_id,bad,ok", LEXICON_CASES, ids=[c[0] for c in LEXICON_CASES])
def test_lexicon_entry_catches_its_own_word(lex_id, bad, ok):
    result = lint_text(bad, "t")
    assert result["ok"] is False, f"{lex_id} 가 {bad!r} 를 놓쳤다"
    assert lex_id in {v["id"] for v in result["violations"]}
    assert result["lexicon_version"] == LEXICON_VERSION
    if ok is not None:
        allowed = lint_text(ok, "t")
        assert allowed["ok"] is True, f"{lex_id} 예외 문장이 걸렸다 — {allowed['violations']}"


def test_quoted_source_is_not_linted():
    """«…» 원문 인용 안의 금지어는 위반이 아니다."""
    raw = "위험 구간 재검사 필요"
    assert lint_text(raw)["ok"] is False
    assert lint_text("[대상] 노트 " + quote_source(raw))["ok"] is True


def test_reference_and_tag_tokens_are_not_linted():
    line = ("[구조] [c:7d21a0b1c2d3] [sig:counts.leaf] [gate:G3] [rule:R-001]"
            " char:analysis:no_dyna x:stack_budget")
    assert lint_text(line)["ok"] is True


def test_mask_neutral_preserves_length_and_newlines():
    text = "가«위험»나\n다[c:7d21a0b1c2d3]라"
    masked = mask_neutral(text)
    assert len(masked) == len(text)
    assert masked.count("\n") == text.count("\n")
    assert "위험" not in masked and "c:7d21a0b1c2d3" not in masked


def test_strip_quoted_removes_quoted_span():
    assert strip_quoted("앞 " + quote_source("위험") + " 뒤") == "앞  뒤"


def test_quote_source_is_idempotent():
    once = quote_source("면 접촉")
    assert quote_source(once) == once
    assert quote_source(None) == quote_source("")


def test_violation_record_shape_and_order():
    result = lint_text("[의미] 위험\n[치수] 개선")
    assert result["violations"] == [
        {"section": "의미", "line_no": 1, "token": "위험", "id": "L01"},
        {"section": "치수", "line_no": 2, "token": "개선", "id": "L03"},
    ]


def test_section_argument_is_used_when_no_tag():
    result = lint_text("위험", "snap")
    assert [v["section"] for v in result["violations"]] == ["snap"]


def test_assert_clean_raises_with_violations():
    assert assert_clean("[구조] 파일 1 · 리프 3") == "[구조] 파일 1 · 리프 3"
    with pytest.raises(JudgementLintError) as exc:
        assert_clean("[구조] 취약 계면", "snap")
    assert exc.value.lexicon_version == LEXICON_VERSION
    assert [v["id"] for v in exc.value.violations] == ["L08"]


# ---------------------------------------------------------------- 정규 표기 원자(plan §3.4.1)

def test_display_precision_by_kind():
    assert fmt_num(0.35) == "0.350"                 # 길이 mm 소수 3자리
    assert fmt_num(12.34, "area") == "12.3"         # 면적 mm² 소수 1자리
    assert fmt_num(3000.0, "volume") == "3000"      # 부피 유효 3자리
    assert fmt_num(0.5, "ratio") == "0.50"          # 비율 소수 2자리
    assert fmt_num(412.4, "stress") == "412"        # 응력 MPa 정수
    assert fmt_num(3, "count") == "3"


def test_missing_values_render_as_미측정():
    assert fmt_num(None) == "미측정"
    assert fmt_num(math.nan) == "미측정"
    assert fmt_value(None, "mm") == "미측정"
    assert signal_text("counts.files", None) == "counts.files=미측정"


def test_signed_and_percent_use_unicode_minus():
    assert MINUS == "−"
    assert fmt_signed(-0.17) == MINUS + "0.170"
    assert fmt_signed(0.17) == "+0.170"
    assert fmt_pct(0.136) == "(+13.6%)"
    assert fmt_pct(-0.486) == f"({MINUS}48.6%)"
    assert fmt_pct(None) == ""


def test_lower_bound_and_change_notation():
    assert fmt_value(0.05, "mm", lower_bound=True) == "≥0.050 mm(lower_bound)"
    assert fmt_change(0.35, 0.18, "mm") == f"0.350→0.180 mm ({MINUS}48.6%)"
    assert fmt_change("tied", "touching") == "tied→touching"
    assert fmt_change(None, 0.18, "mm").startswith("미측정→")


def test_label_iface_and_refs():
    assert fmt_label("PLATE_1") == "PLATE_1"
    assert fmt_label("PLATE_1", True) == "PLATE_1(auto_named)"
    assert fmt_iface("PLATE_2", "PLATE_1") == "PLATE_1↔PLATE_2"
    assert fmt_iface("PLATE_1", "PLATE_2") == fmt_iface("PLATE_2", "PLATE_1")
    assert fmt_refs("c:aa", ["d:bb", "c:aa"], None, "") == "[c:aa] [d:bb]"


def test_item_text_fields_are_canonical(state, diff):
    """signal·param·event 는 text 가 있으면 그것이 정본이다."""
    signal = state["signals"]["counts.leaf"]
    assert signal_text("counts.leaf", signal) == signal["text"]
    item = diff["parametric"]["edge_params"][0]
    assert render.param_text(item) == item["text"]
    event = diff["semantic"]["events"][0]
    assert render.event_text(event) == event["text"]
    assert render.param_text(None) == "" and render.event_text(None) == ""


def test_param_text_falls_back_to_fields():
    item = {"name": "utg_edge_gap", "attr": "min_gap", "before": 0.35, "after": 0.18,
            "unit": "mm", "cid": "c:7d21a0b1c2d3"}
    assert render.param_text(item) == (
        f"utg_edge_gap min_gap 0.350→0.180 mm ({MINUS}48.6%) [c:7d21a0b1c2d3]"
    )


# ---------------------------------------------------------------- summary_text 조립(plan §3.2.7 · §3.4.2)

def test_snap_summary_sections_and_budget(state):
    text = summarize(state, "snap", {"project_code": "M22", "sources": {"mcad": "heax-step_forge"}})
    assert _sections(text) == SNAP_SECTIONS
    assert len(text) <= SUMMARY_MAX
    assert "mcad=heax-step_forge" in text and "dyna=absent" in text
    assert "G3 fail(1, ack 없음)" in text and "[gate:G3]" in text
    assert lint_text(text)["ok"] is True


def test_diff_summary_sections_and_budget(diff):
    text = summarize(diff, "diff", {"sources": {"mcad": "heax-step_forge"}})
    assert _sections(text) == DIFF_SECTIONS
    assert len(text) <= SUMMARY_MAX
    assert "result_parity=null" in text
    assert "결과 비교 제외(result_kind_differs)" in text
    assert lint_text(text)["ok"] is True


def test_summary_is_deterministic(state, diff):
    ctx = {"project_code": "M22", "sources": {"mcad": "heax-step_forge"}}
    assert summarize(state, "snap", ctx) == summarize(state, "snap", ctx)
    assert summarize(diff, "diff", {}) == summarize(diff, "diff", {})


def test_summarize_rejects_unknown_kind(state):
    with pytest.raises(ValueError):
        summarize(state, "pair")


def test_section_folds_when_over_its_limit(state):
    """섹션 상한을 넘으면 그 섹션 안에서 '… 외 N건' 으로 접는다(총량은 2000자 이하)."""
    payload = copy.deepcopy(state)
    filler = "PLATE_1 min_gap 0.000 mm " * 8
    for index in (1, 2, 3):
        payload["signals"][f"top.interference[{index}]"] = {
            "kind": "length", "value": 0.05, "unit": "mm", "refs": [],
            "text": f"iface{index} {filler}", "known": True,
        }
    text = summarize(payload, "snap", {})
    iface_line = next(line for line in text.split("\n") if line.startswith("[상위 계면]"))
    assert "… 외 2건" in iface_line
    assert len(text) <= SUMMARY_MAX


def test_judgement_word_from_source_data_raises(state):
    """코드가 조립한 문장에 판단어가 새면 렌더러 결함이므로 예외다."""
    payload = copy.deepcopy(state)
    payload["character_seed"] = [{"tag": "위험 경로"}]
    with pytest.raises(JudgementLintError) as exc:
        summarize(payload, "snap", {})
    assert [(v["section"], v["id"]) for v in exc.value.violations] == [("씨앗", "L01")]


def test_render_summary_downgrades_instead_of_raising(state):
    payload = copy.deepcopy(state)
    payload["character_seed"] = [{"tag": "위험 경로"}]
    got = render_summary(payload, "snap", {})
    assert got["summary_text"] == ""
    assert got["summary_status"] == "lint_failed"
    assert got["lexicon_version"] == LEXICON_VERSION
    assert got["violations"] and got["violations"][0]["id"] == "L01"


def test_render_summary_ok_path(state):
    got = render_summary(state, "snap", {"project_code": "M22"})
    assert got["summary_status"] == "ok"
    assert got["violations"] == []
    assert got["summary_text"].startswith("[대상]")
