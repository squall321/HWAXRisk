# 선형 훑기 시험(반대 검토 H1) — _fence_blocks 가 옛 펜스 정규식 findall 과 글자까지 같고, 펜스 · 수 · 사번 · id 꼴을 1 MB 의 나쁜 글에서도 곧 끝낸다
"""narrative._FENCE_RE(``` 펜스 정규식)는 '```{}x' 반복 글에서, 옛 숫자 정규식은 '111,111,…' 글에서, 옛 사번 정규식은 '사번' 뒤 긴 빈칸에서 길이의 제곱으로
느려져 2백만 자 입력(결정문 글 · 숫자 점검 글)이 서버를 붙들었다. 펜스는 같은 결과를 내는 한 번 훑기(_fence_blocks)로 바꿨고 — 짧은 무작위 글 수천 개와
손 사례로 옛 정규식과 같음을 잰다 — 수 · 사번은 선형 꼴로 바꿨다.

  실행:  .venv/bin/python -m pytest tests/test_fence_blocks.py
"""
from __future__ import annotations

import random
import time

import pytest

from app import ledger_numbers, narrative, pii

ALPHABET = ["`", "{", "}", "j", "s", "o", "n", " ", "\n", "x"]
TOKENS = ["```", "json", "{", "}", " ", "\n", "x", "`", "j", "\t", "``", "{}", "```json", " "]
HAND = [
    "", "```", "``````", "```{}```", "```json{}```", "```json {}```", "```json\n{\"a\": 1}\n```", "```{ ``` }```", "````{}````",
    "```{}x```{}```", "```{}``` ```{}```", "```js{}```", "```json json{}```", "``` {} ```", "```{\n```", "```{}}```", "```{{}}```",
    "```json\n{}\n``` 그리고 ```{\"b\": 2}```", "x```{} \n ```y```{}```", "```{```}```", "```{} ```", "```json {}```",
    "```\n{\"schema\": \"risk_spec\"}\n```\n\n```json\n{\"schema\": \"risk_spec\", \"v\": 2}\n```",
]


def _old(s: str) -> list[str]:
    return narrative._FENCE_RE.findall(s)


@pytest.mark.parametrize("text", HAND)
def test_hand_cases_match_the_old_regex(text):
    assert narrative._fence_blocks(text) == _old(text)


def test_thousands_of_random_short_strings_match_the_old_regex():
    rng = random.Random(1117)
    for _ in range(6000):
        s = "".join(rng.choice(ALPHABET) for _ in range(rng.randint(0, 24)))
        assert narrative._fence_blocks(s) == _old(s), repr(s)
    for _ in range(6000):
        s = "".join(rng.choice(TOKENS) for _ in range(rng.randint(0, 14)))
        assert narrative._fence_blocks(s) == _old(s), repr(s)


def test_parse_risk_spec_reads_the_same_fence():
    text = "앞 글 ```json\n{\"schema\": \"risk_spec\", \"n\": 1}\n``` 사이 ```{\"schema\": \"risk_spec\", \"n\": 2}```"
    assert narrative.parse_risk_spec(text) == {"schema": "risk_spec", "n": 2}


def _seconds(fn) -> float:
    started = time.perf_counter()
    fn()
    return time.perf_counter() - started


MB = 1_000_000


@pytest.mark.parametrize("name,text", [
    ("fence ```{}x", "```{}x" * (MB // 6)),
    ("fence ``` space", ("```" + " " * 40) * (MB // 43)),
    ("fence json{", "```json{" * (MB // 8)),
])
def test_the_fence_scan_is_linear_on_hostile_text(name, text):
    assert _seconds(lambda: narrative._fence_blocks(text)) < 1.5, name
    assert _seconds(lambda: narrative.parse_risk_spec(text)) < 3.0, name


@pytest.mark.parametrize("name,text", [
    ("number 111,", "111," * (MB // 4) + "1111"),
    ("number 1,", "1," * (MB // 2)),
    ("number dots", "1." * (MB // 2)),
    ("id ab-", "ab-" * (MB // 3) + "-"),
    ("id a1_", "a1_" * (MB // 3)),
])
def test_number_and_id_scans_are_linear_on_hostile_text(name, text):
    def run() -> int:
        inside = ledger_numbers._IdSpans([m.span(1) for m in ledger_numbers._ID_RE.finditer(text)])
        return sum(1 for start, *_ in ledger_numbers.numbers_in(text) if not inside.covers(start))

    assert _seconds(run) < 3.0, name


@pytest.mark.parametrize("text", ["사번" + " " * MB, ("사번 " + " " * 50) * (MB // 53), "employee id" + " " * MB])
def test_the_employee_pattern_is_linear(text):
    assert _seconds(lambda: pii.mask_text(text)) < 1.5


@pytest.mark.parametrize("text,want", [
    ("412.5 MPa", [("412.5", "MPa")]),
    ("1,234.5 mm 와 0.65mm", [("1,234.5", "mm"), ("0.65", "mm")]),
    ("1,2,3", [("1", None), ("2", None), ("3", None)]),
    ("값 1, 2, 3 이다", [("1", None), ("2", None), ("3", None)]),
    ("판 1.2.3 · 조항 4.1.2", []),
    ("-0.3 과 2.4e-3 s", [("-0.3", None), ("2.4e-3", "s")]),
    ("R-001 · U1001 · 2차", [("001", None), ("2", None)]),    # 글자에 붙은 수는 수가 아니고, 하이픈 뒤(R-001)는 부르는 쪽이 id 자리로 뺀다
    ("111,1111", [("111", None), ("1111", None)]),
])
def test_the_number_tokenizer_cuts_values_and_units(text, want):
    assert [(value, unit) for _s, _e, value, unit in ledger_numbers.numbers_in(text)] == want
