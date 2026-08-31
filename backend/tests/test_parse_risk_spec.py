# parse_risk_spec(펜스 우선 → 마지막 균형 중괄호 → 실패 None)·validate_risk_spec(스키마 오류 목록) — 합성 6 케이스 + 결정문 픽스처 .md 6종
from __future__ import annotations

import copy
import json

import pytest

from app.narrative import parse_risk_spec, validate_risk_spec
from tests.conftest import FIXTURES_DIR

# 결정문 픽스처 .md → (파싱 결과가 dict 인가, 최소 validate 오류 수). None 케이스는 오류 수 없음.
MD_CASES = [
    ("fence_ok", True, 0),        # 마지막 ```json 펜스
    ("brace_only", True, 0),      # 펜스 없음 — 앞 문단 미끼 {"note":…} 를 지나 끝의 균형 블록만
    ("broken", False, None),      # 펜스 안 JSON 깨짐 → 균형 스캔도 실패 → None
    ("other_schema", False, None),  # schema=='sim_spec' → None
    ("facet7", True, 1),          # facets 7개 — 파싱은 되고 validate 오류
    ("enum_bad", True, 3),        # severity·judgement·verdict enum 위반 3건
]


@pytest.mark.parametrize("name,is_dict,min_errors", MD_CASES, ids=[c[0] for c in MD_CASES])
def test_markdown_fixtures(name, is_dict, min_errors):
    text = (FIXTURES_DIR / "risk_spec" / f"{name}.md").read_text(encoding="utf-8")
    got = parse_risk_spec(text)
    if not is_dict:
        assert got is None
        return
    assert isinstance(got, dict) and got["schema"] == "risk_spec"
    errors = validate_risk_spec(got)
    if min_errors == 0:
        assert errors == []
    else:
        assert len(errors) >= min_errors, errors

PROSE = (
    "(1) 대상과 범위 — F7-DV1 → F7-DV2 diff 를 본다.\n"
    "(3) F1 UTG↔HOUSING_FRONT clearance 가 0.350→0.180 mm 로 줄었다 [c:7d21aa00bb11].\n"
    "(8) 판정 후보는 conditional 이다.\n"
)


def _fence(obj: dict) -> str:
    return "```json\n" + json.dumps(obj, ensure_ascii=False, indent=1) + "\n```"


@pytest.fixture(scope="module")
def valid_spec() -> dict:
    """schemas 빌더의 유효 risk_spec 픽스처(tests/fixtures/risk_spec/valid*) 중 첫 번째. 없으면 실패."""
    files = sorted(p for p in (FIXTURES_DIR / "risk_spec").rglob("*.json") if "invalid" not in str(p.relative_to(FIXTURES_DIR)))
    assert files, f"유효 risk_spec 픽스처가 없다: {FIXTURES_DIR / 'risk_spec'}"
    obj = json.loads(files[0].read_text(encoding="utf-8"))
    assert obj.get("schema") == "risk_spec"
    return obj


# ---------------------------------------------------------------- 파싱 경로

def test_last_json_fence_is_parsed(valid_spec):
    decoy = {"schema": "risk_spec", "version": "0.0", "note": "앞선 펜스"}
    text = PROSE + _fence(decoy) + "\n\n최종 규격.\n" + _fence(valid_spec) + "\n끝."
    got = parse_risk_spec(text)
    assert got == valid_spec, "마지막 ```json 펜스가 우선이어야 한다"


def test_balanced_braces_without_fence(valid_spec):
    text = PROSE + "\n기계판독 규격은 다음과 같다.\n" + json.dumps(valid_spec, ensure_ascii=False) + "\n이상."
    assert parse_risk_spec(text) == valid_spec


def test_broken_braces_return_none():
    text = PROSE + '{"schema": "risk_spec", "version": "1.0", "scope": {"kind": "diff"'
    assert parse_risk_spec(text) is None
    assert parse_risk_spec("") is None
    assert parse_risk_spec("중괄호가 전혀 없는 산문") is None


def test_other_schema_returns_none():
    sim = {"schema": "sim_spec", "version": "1.0", "parameters": [], "outputs": []}
    assert parse_risk_spec(PROSE + _fence(sim)) is None
    assert parse_risk_spec(PROSE + json.dumps(sim)) is None
    assert parse_risk_spec(_fence({"version": "1.0"})) is None


# ---------------------------------------------------------------- 검증 경로

def test_valid_fixture_passes_validation(valid_spec):
    assert validate_risk_spec(valid_spec) == []


def test_seven_facets_parse_but_fail_validation(valid_spec):
    spec = copy.deepcopy(valid_spec)
    facets = spec["character"]["facets"]
    assert len(facets) == 8
    facets.pop()
    got = parse_risk_spec(PROSE + _fence(spec))
    assert got is not None and len(got["character"]["facets"]) == 7
    errors = validate_risk_spec(got)
    assert errors and all(isinstance(e, str) for e in errors)


def test_enum_violation_fails_validation(valid_spec):
    spec = copy.deepcopy(valid_spec)
    spec["verdict"] = "maybe"
    got = parse_risk_spec(PROSE + _fence(spec))
    assert got is not None and got["verdict"] == "maybe"
    errors = validate_risk_spec(got)
    assert errors and any("maybe" in e or "verdict" in e for e in errors)
