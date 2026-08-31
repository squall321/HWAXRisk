# 의장 결정문 서술 처리 — parse_risk_spec(parseSimSpec 포팅: 펜스 → 균형 중괄호 → None) + risk_spec.v1.json 검증
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft7Validator

SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "risk_spec.v1.json"

# hwax-sim-deliberate.js parseSimSpec 의 펜스 정규식과 동일. 마지막 펜스를 쓴다(plan §4.2.2).
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```")


def _last_balanced_block(s: str) -> str | None:
    """텍스트 끝의 마지막 '}' 에서 역방향으로 중괄호를 세어 짝 '{' 까지의 블록을 돌려준다(중첩 JSON 방어)."""
    end = s.rfind("}")
    if end == -1:
        return None
    depth = 0
    for i in range(end, -1, -1):
        ch = s[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0:
                return s[i:end + 1]
    return None


def parse_risk_spec(text: str) -> dict | None:
    """결정문 텍스트에서 risk_spec JSON 을 뽑는다. 실패는 None(예외 없음, 비치명).

    (1) 마지막 ```json 펜스 → (2) 없거나 깨지면 텍스트 끝에서 역방향 마지막 균형 중괄호 블록
    → (3) dict 이고 schema=='risk_spec' 이 아니면 None.
    """
    s = "" if text is None else str(text)
    obj = None
    fences = _FENCE_RE.findall(s)
    if fences:
        try:
            obj = json.loads(fences[-1])
        except json.JSONDecodeError:
            obj = None  # 펜스 파싱 실패 → 균형 스캔 폴백
    if obj is None:
        block = _last_balanced_block(s)
        if block is None:
            return None
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            return None
    if not isinstance(obj, dict) or obj.get("schema") != "risk_spec":
        return None
    return obj


@lru_cache(maxsize=1)
def _validator() -> Draft7Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def validate_risk_spec(obj: dict) -> list[str]:
    """app/schemas/risk_spec.v1.json 으로 검증한 오류 메시지 목록(빈 리스트 = 통과). 경로 순으로 정렬."""
    errors = sorted(_validator().iter_errors(obj), key=lambda e: list(e.absolute_path))
    out = []
    for err in errors:
        path = "/".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"{path}: {err.message}")
    return out
