# 축별 표기 규칙(RK-07) — 등급 · 증거 유형 · 주의 등급 · 판정의 글자를 축 낱말이 붙은 표시 글로 바꾸고, 축 낱말 없는 단독 대문자 A ~ J 를 센다
"""등급(A · B · C) · 증거 유형(A ~ J) · 앱 주의 등급(A ~ D)이 같은 글자를 써서 좌석이 축을 섞어 읽고 엉뚱한 반박을 냈다(HWAXPortal
docs/request-1117 RK-07). 표기는 데이터다 — `assets/labels.v1.json`. 근거 묶음(RK-02) · 보고 묶음(RK-05)은 이 모듈의 `label_value` 로 칸 값을
적고 `check_text` 로 남은 단독 대문자를 센다(0 건이 목표다).

단독 대문자 — 앞뒤가 영문 · 숫자 · `_` · `.` · `-` 가 아닌 A ~ J 한 글자다(코드 `R-001` · 키 `VRD-COND` · 낱말 `CAD` 는 단독이 아니다). 바로
앞이나 뒤에 축 낱말(등급 · 주의 · 유형 · 판정, 사이에 빈칸 하나까지 · 앞의 `[` 는 건너뛴다)이 붙으면 축이 적힌 것이라 세지 않는다.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app import taxonomy

LABELS_ASSET = "labels"
AXES: tuple[str, ...] = ("grade", "type", "attention", "verdict")
_STANDALONE = re.compile(r"(?<![A-Za-z0-9_.\-])([A-J])(?![A-Za-z0-9_.\-])")
CONTEXT_CHARS = 16
VIOLATION_SAMPLES_MAX = 50


def load_labels() -> dict:
    return taxonomy.load_json(LABELS_ASSET)


def axis_words() -> tuple[str, ...]:
    return tuple(str(a.get("word")) for a in (load_labels().get("axes") or {}).values() if a.get("word"))


def labels_payload() -> dict:
    """`risk_taxonomy(part="labels")` · `GET /api/taxonomy/labels` — 축마다 {낱말, 뜻, 값 → 표시 글}과 판정의 SP 키, 검사 규칙."""
    doc = load_labels()
    axes = {}
    for name in AXES:
        axis = dict((doc.get("axes") or {}).get(name) or {})
        axes[name] = {k: axis[k] for k in ("word", "meaning", "values", "sp_keys", "sp_keys_status", "sp_keys_note") if k in axis}
    return {"labels_version": doc.get("labels_version"), "note": doc.get("note"), "axes": axes,
            "check": {"rule": "축 낱말(" + " · ".join(axis_words()) + ") 없이 홀로 선 대문자 A ~ J 를 센다 — 근거 묶음 · 보고 묶음은 0 건이 목표다.",
                      "letters": "A-J"}}


def _normal(axis: str, raw: Any) -> str | None:
    """칸 값 → 그 축의 값 열쇠(모르는 값이면 None). 등급 · 유형 · 주의는 대문자 한 글자(뒤의 '조' · 앞의 축 낱말은 떼고 본다), 판정은
    risk_spec verdict 낱말이나 SP 키 그대로다."""
    values = ((load_labels().get("axes") or {}).get(axis) or {}).get("values") or {}
    text = str(raw).strip()
    if not text:
        return None
    if text in values:
        return text
    for key, shown in values.items():
        if text == shown:
            return key
    if axis == "verdict":
        lowered = text.lower()
        return lowered if lowered in values else None
    word = ((load_labels().get("axes") or {}).get(axis) or {}).get("word") or ""
    core = text.strip("[] ")
    if word and core.startswith(word):
        core = core[len(word):].strip()
    if core.endswith("조"):
        core = core[:-1].strip()
    core = core.upper()
    return core if core in values else None


def label_value(axis: str | None, raw: Any) -> tuple[Any, bool]:
    """(표시 글, 바꿨나) — 축이 없거나 빈 값이면 그대로(False), 그 축이 모르는 값이면 그대로(False)다(지어내지 않는다)."""
    if not axis or raw is None or (isinstance(raw, str) and not raw.strip()):
        return raw, False
    key = _normal(axis, raw)
    if key is None:
        return raw, False
    return ((load_labels().get("axes") or {}).get(axis) or {})["values"][key], True


def _axis_near(text: str, start: int, end: int, words: tuple[str, ...]) -> bool:
    before = text[max(0, start - 6):start].rstrip("[ ")
    after = text[end:end + 4].lstrip(" ")
    return any(before.endswith(w) for w in words) or any(after.startswith(w) for w in words)


def check_text(text: str, *, path: str = "") -> list[dict]:
    """축 낱말 없는 단독 대문자 A ~ J — [{path, offset, line, col, letter, context}]."""
    words = axis_words()
    out: list[dict] = []
    for m in _STANDALONE.finditer(text or ""):
        if _axis_near(text, m.start(), m.end(), words):
            continue
        out.append(_violation(text, m, path))
    return out


def check_obj(value: Any, *, path: str = "") -> list[dict]:
    """글 · 목록 · 객체 안의 모든 글(객체 열쇠는 보지 않는다 — 꼴이 정한 이름이다)을 훑는다."""
    if isinstance(value, str):
        return check_text(value, path=path)
    if isinstance(value, Mapping):
        return [v for k, item in value.items() for v in check_obj(item, path=f"{path}.{k}" if path else str(k))]
    if isinstance(value, (list, tuple)):
        return [v for i, item in enumerate(value) for v in check_obj(item, path=f"{path}[{i}]")]
    return []


def check_summary(violations: list[dict]) -> dict:
    return {"violations_n": len(violations), "violations": violations[:VIOLATION_SAMPLES_MAX],
            "truncated": max(0, len(violations) - VIOLATION_SAMPLES_MAX)}


def scan_summary(value: Any) -> dict:
    """check_summary(check_obj(value)) 와 같은 꼴 — 다 세되 보기 행은 앞 VIOLATION_SAMPLES_MAX 개만 짓는다(큰 묶음에서 행을 다 짓지 않는다)."""
    words = axis_words()
    samples: list[dict] = []
    count = 0

    def walk(item: Any, path: str) -> None:
        nonlocal count
        if isinstance(item, str):
            for m in _STANDALONE.finditer(item):
                if _axis_near(item, m.start(), m.end(), words):
                    continue
                count += 1
                if len(samples) < VIOLATION_SAMPLES_MAX:
                    samples.append(_violation(item, m, path))
        elif isinstance(item, Mapping):
            for k, v in item.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(item, (list, tuple)):
            for i, v in enumerate(item):
                walk(v, f"{path}[{i}]")

    walk(value, "")
    return {"violations_n": count, "violations": samples, "truncated": max(0, count - len(samples))}


def _violation(text: str, m: re.Match, path: str) -> dict:
    line = text.count("\n", 0, m.start()) + 1
    col = m.start() - (text.rfind("\n", 0, m.start()) + 1) + 1
    ctx = text[max(0, m.start() - CONTEXT_CHARS):m.end() + CONTEXT_CHARS].replace("\n", " ")
    return {"path": path, "offset": m.start(), "line": line, "col": col, "letter": m.group(1), "context": ctx}
