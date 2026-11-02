# 과제 주제(SP 허브 과제 key · 차수)의 꼴 — 차수는 rr_projects.stage 를 읽을 때 개발 단계 코드로 정규화한다(과제 인사이트 그래프 M2b)
"""HWAXPortal docs/project-insight-graph contracts.md §9 · PLAN §4.6 · §4.7 'M2b'.

**차수.** 새 칸 없이 `rr_projects.stage` 다 — 읽을 때 `norm_round(stage)` 가 개발 단계 코드 열한 개(`STAGES`) 가운데 하나면 그것, 아니면
None(차수 모름)이다. 규칙은 에이전트 서버 `delib_subject.norm_round` 와 같다 — NFKC(전각 → 반각) → 유니코드 White_Space 글자 빼기 → 소문자 →
열한 코드에 있을 때만. 하이픈을 빼지 않고 '2차' · 'C2' · '양산' · 리스크 앱 웹 폼이 받는 'dv' · 'pre1' 을 코드로 읽지 않는다 — 원천이 그
대응을 적지 않았다(PLAN §4.6). tests/test_sp_subject.py 가 형제 리포(../HWAXAgentServer/delib_subject.py)의 원문과 견준다.

과제 만들기(`POST /api/projects` · MCP `risk_create_project`)의 stage 는 종전대로 글이다 — 거르면 웹 폼의 'dv' · 'pre1' 이 422 가 된다(포털
context-notes PG-33). 꼴에 안 맞는 옛 stage 는 읽을 때 차수 모름이다. 코드로 적는 길은 `PUT /api/projects/{id}/sp-subject` 의 round 다.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.errors import AppError

# 개발 단계 코드 열한 개 — dv · pv 는 차수(1 · 2 · 3 · r)가 있어야 하고 pre · pra · mp 에는 없다(DynaForge 정본 규칙 · AIDataHub eng_meta 와 같은
# 어휘 — 에이전트 delib_subject.STAGES 와 글자까지 같다).
STAGES = ("pre", "dv1", "dv2", "dv3", "dvr", "pv1", "pv2", "pv3", "pvr", "pra", "mp")
# 찾기 거름의 '차수 모름' 칸 — stage 가 꼴에 맞지 않는(또는 빈) 과제만이다(어느 차수에도 섞지 않는다, 사용자 결정 11-02 PG-17 ①).
ROUND_UNKNOWN = "unknown"
# 쓰기 본문의 글자 상한 — 에이전트 delib_subject 의 ROUND_MAX 와 같다.
ROUND_MAX = 40

# 차수 정규화가 빼는 '공백' — 유니코드 White_Space 성질의 글자 그대로다(에이전트 delib_subject._SPACE_RE 와 같은 묶음 — 파이썬 str.split 은
# 정보 분리 문자 U+001C ~ U+001F 까지, JS 의 \s 는 BOM 까지 공백으로 읽어 갈렸다).
_SPACE_RE = re.compile("[\u0009-\u000d \u0085   -     　]+")


def norm_round(value: Any) -> str | None:
    """차수 글 → 코드(STAGES) · 아니면 None(차수 모름). NFKC · 공백(_SPACE_RE) 빼기 · 소문자만 하고 글자 그대로 견준다."""
    if not isinstance(value, str):
        return None
    text = _SPACE_RE.sub("", unicodedata.normalize("NFKC", value)).lower()
    return text if text in STAGES else None


def _not_a_round(raw: str, allowed: tuple[str, ...]) -> AppError:
    return AppError("round_invalid",
                    f"round {raw[:ROUND_MAX]!r} 는 차수가 아닙니다 — {' · '.join(allowed)} 가운데 하나입니다(전각 · 공백 · 대소문자만 맞춥니다 —"
                    " 'dv' · 'pre1' · '2차' · 'C2' · '양산' 은 차수가 아닙니다).", 422, detail={"allowed": list(allowed)})


def parse_round(raw: Any) -> str | None:
    """쓰기의 round — 비었으면(None · 빈 글) None 이라 stage 를 그대로 두고, 열한 코드면 그 코드, 아니면 422 round_invalid."""
    if raw is None or not str(raw).strip():
        return None
    code = norm_round(raw)
    if code is None:
        raise _not_a_round(str(raw), STAGES)
    return code


def parse_round_filter(raw: Any) -> str | None:
    """찾기의 round 거름 — 비었으면 None(모든 차수), 'unknown' · '모름' 이면 ROUND_UNKNOWN(차수 모름만), 열한 코드면 그 코드, 아니면 422 —
    아무것도 안 걸리는 거름을 말없이 돌려주지 않는다(에이전트 delib_subject.parse_filter 와 같은 규칙)."""
    if raw is None or not str(raw).strip():
        return None
    if str(raw).strip().lower() in (ROUND_UNKNOWN, "모름"):
        return ROUND_UNKNOWN
    code = norm_round(raw)
    if code is None:
        raise _not_a_round(str(raw), (*STAGES, ROUND_UNKNOWN))
    return code
