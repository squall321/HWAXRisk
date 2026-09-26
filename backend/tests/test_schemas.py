# 5 스키마(rr_ir·rr_state·rr_diff·risk_spec·seat_opinion) × 유효/무효 픽스처 라운드트립 — 픽스처 부재는 실패
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import validators

from tests.conftest import BACKEND_DIR, FIXTURES_DIR

SCHEMAS_DIR = BACKEND_DIR / "app" / "schemas"
SCHEMA_NAMES = ("rr_ir", "rr_state", "rr_diff", "risk_spec", "seat_opinion")


def _load_schema(name: str) -> dict:
    path = SCHEMAS_DIR / f"{name}.v1.json"
    assert path.exists(), f"스키마 파일이 없다: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _fixtures(name: str) -> tuple[list[Path], list[Path]]:
    """tests/fixtures/<name>/ 아래 JSON 을 경로에 'invalid' 가 들어가면 무효, 아니면 유효로 나눈다."""
    root = FIXTURES_DIR / name
    assert root.is_dir(), f"픽스처 디렉터리가 없다: {root}"
    valid, invalid = [], []
    for p in sorted(root.rglob("*.json")):
        (invalid if "invalid" in str(p.relative_to(root)) else valid).append(p)
    return valid, invalid


def _validator(schema: dict):
    cls = validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_is_draft07_and_strict_at_top(name):
    schema = _load_schema(name)
    assert "draft-07" in schema.get("$schema", "")
    assert schema.get("additionalProperties") is False
    assert schema.get("type") == "object"
    _validator(schema)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_valid_fixtures_roundtrip(name):
    v = _validator(_load_schema(name))
    valid, _ = _fixtures(name)
    assert len(valid) >= 2, f"{name} 유효 픽스처는 2개 이상이어야 한다"
    for path in valid:
        obj = json.loads(path.read_text(encoding="utf-8"))
        errors = [e.message for e in v.iter_errors(obj)]
        assert errors == [], f"{path.name}: {errors}"
        # 라운드트립 — 직렬화·역직렬화 후에도 통과하고 내용이 같다
        again = json.loads(json.dumps(obj, ensure_ascii=False, sort_keys=True))
        assert again == obj
        assert not list(v.iter_errors(again))


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_invalid_fixtures_are_rejected(name):
    v = _validator(_load_schema(name))
    _, invalid = _fixtures(name)
    assert len(invalid) >= 2, f"{name} 무효 픽스처는 2개 이상이어야 한다"
    for path in invalid:
        obj = json.loads(path.read_text(encoding="utf-8"))
        assert list(v.iter_errors(obj)), f"{path.name} 이 스키마를 통과했다(무효여야 한다)"


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_invalid_fixtures_are_rejected_for_their_own_reason(name):
    """'거부됐다' 만으로는 부족하다 — **왜** 거부됐는지가 픽스처 이름이 말하는 결함이어야 한다.

    `required` 에 키를 더하거나 어휘를 좁히면 무효 픽스처가 새 사유로도 거부된다. 거부 여부만 보는
    시험은 그때도 초록이라, 원래 잡으려던 결함이 사라졌는지 알 수 없다(항진명제가 버그를 가린 전례가
    이 리포에 있다 — `CORPUS_TOOLS` 순서 역전·`CONTEXT_KIND` 값). 그래서 픽스처 이름의 토큰 하나가
    실제 오류의 **경로 또는 문구**에 나타나야 한다고 못 박는다.
    """
    v = _validator(_load_schema(name))
    _, invalid = _fixtures(name)
    for path in invalid:
        obj = json.loads(path.read_text(encoding="utf-8"))
        errors = list(v.iter_errors(obj))
        assert errors, f"{path.name} 이 스키마를 통과했다(무효여야 한다)"
        where = " ".join(
            f"{'/'.join(str(x) for x in e.absolute_path)} {e.message} {e.validator}" for e in errors)
        # 이름의 꼬리 숫자는 개수다(`facet7` = 8축이어야 하는데 7축) — 떼고 본다.
        tokens = [t.rstrip("0123456789") for t in path.stem.split("_")
                  if t not in ("invalid", "to") and len(t) >= 3]
        assert any(t in where for t in tokens), (
            f"{path.name} 의 거부 사유가 이름과 무관하다 — 원래 결함이 검사되는지 알 수 없다.\n"
            f"  이름 토큰 {tokens}\n  실제 사유 {where[:300]}")


def test_total_invalid_fixtures_at_least_ten():
    """plan §9.1 통과 기준 10 — 무효 픽스처 거부 ≥10건."""
    total = sum(len(_fixtures(n)[1]) for n in SCHEMA_NAMES)
    assert total >= 10


@pytest.mark.parametrize("name,marker", [
    ("rr_ir", "ir_version"), ("rr_state", "state_version"), ("rr_diff", "diff_version"),
    ("risk_spec", "schema"), ("seat_opinion", "opinion_id"),
])
def test_top_level_required_keys(name, marker):
    schema = _load_schema(name)
    assert marker in schema.get("required", []), f"{name}.required 에 {marker} 가 없다"


def test_risk_spec_enums_follow_plan():
    schema = _load_schema("risk_spec")
    text = json.dumps(schema, ensure_ascii=False)
    for token in ("go", "conditional", "no-go", "undetermined", "risk_spec"):
        assert f'"{token}"' in text
