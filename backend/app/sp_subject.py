# 과제 주제(SP 허브 과제 key · 차수)의 꼴과 확인 — 차수는 stage 를 읽을 때 정규화하고, key 는 그 사람의 PAT 로 스스로 부른 풀이의 결과 행에서만 받는다(과제 인사이트 그래프 M2b)
"""HWAXPortal docs/project-insight-graph contracts.md §9 · PLAN §4.3 · §4.6 · §4.7 'M2b'.

**차수.** 새 칸 없이 `rr_projects.stage` 다 — 읽을 때 `norm_round(stage)` 가 개발 단계 코드 열한 개(`STAGES`) 가운데 하나면 그것, 아니면
None(차수 모름)이다. 규칙은 에이전트 서버 `delib_subject.norm_round` 와 같다 — NFKC(전각 → 반각) → 유니코드 White_Space 글자 빼기 → 소문자 →
열한 코드에 있을 때만. 하이픈을 빼지 않고 '2차' · 'C2' · '양산' · 리스크 앱 웹 폼이 받는 'dv' · 'pre1' 을 코드로 읽지 않는다 — 원천이 그
대응을 적지 않았다(PLAN §4.6). tests/test_sp_subject.py 가 형제 리포(../HWAXAgentServer/delib_subject.py)의 원문과 견준다.

과제 만들기(`POST /api/projects` · MCP `risk_create_project`)의 stage 는 종전대로 글이다 — 거르면 웹 폼의 'dv' · 'pre1' 이 422 가 된다(포털
context-notes PG-33). 꼴에 안 맞는 옛 stage 는 읽을 때 차수 모름이다. 코드로 적는 길은 `PUT /api/projects/{id}/sp-subject` 의 round 다.

**SP 과제 key.** 부르는 쪽이 준 key 는 근거가 아니다(사용자 결정 A13 · PLAN §4.3). 리스크 앱이 그 사람의 등록된 포털 PAT 로 게이트웨이 호출 전용
별칭 `heaxstep_forge_find_plm_task` 를 스스로 불러(`confirm`) 결과 행(`tasks[]`) 가운데 `key` 가 글자 그대로 같은 행이 꼭 하나이고 그 행이
비활성(`active` 거짓)이 아닐 때만 적는다 — 에이전트 `delib_subject.confirm` 과 같은 규칙. 질의를 되실은 `query` 칸은 근거로 보지 않는다(운영
허브는 과제명이 key 라 그 칸이 늘 같다). 확인하지 못한 까닭에는 결과 행의 key 를 싣지 않는다 — 그 까닭은 감사 · 화면에 남아 StepForge 허가가
없는 사람이 볼 수 있다(PLAN §6.2).
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from typing import Any

from app.common import now_epoch, sha256_hex
from app.errors import AppError
from app.ra_client import DEADLINE_EXCEEDED

# 개발 단계 코드 열한 개 — dv · pv 는 차수(1 · 2 · 3 · r)가 있어야 하고 pre · pra · mp 에는 없다(DynaForge 정본 규칙 · AIDataHub eng_meta 와 같은
# 어휘 — 에이전트 delib_subject.STAGES 와 글자까지 같다).
STAGES = ("pre", "dv1", "dv2", "dv3", "dvr", "pv1", "pv2", "pv3", "pvr", "pra", "mp")
# 찾기 거름의 '차수 모름' 칸 — stage 가 꼴에 맞지 않는(또는 빈) 과제만이다(어느 차수에도 섞지 않는다, 사용자 결정 11-02 PG-17 ①).
ROUND_UNKNOWN = "unknown"
# 쓰기 본문의 글자 상한 — 에이전트 delib_subject 의 SP_TASK_MAX · ROUND_MAX 와 같다.
SP_TASK_MAX, ROUND_MAX = 200, 40

# 풀이 도구 — StepForge find_plm_task(허브 코어 API 거울에서 과제코드 · 별칭 · 과제명 · 모델 · 프로젝트로 찾는다 — 결과 행마다 key). 게이트웨이의
# 호출 전용 별칭(<백엔드 키에서 하이픈 뺀 것>_<도구>)으로 부른다 — 노출 이름은 박스마다 다르고(겹치면 접두가 붙는다) 별칭은 늘 선다(에이전트
# delib_subject.RESOLVER_CALL 과 같은 이름이다).
RESOLVER_APP, RESOLVER_TOOL = "heax-step_forge", "find_plm_task"
# 결과 행 수 — 활성이고 글자가 같은 행이 앞이다. full=true 는 StepForge 챗 접기를 끈다(행 · 칸을 줄이지 않는다).
RESOLVE_LIMIT = 50
# 한 번 부르는 기한(초) — 사람이 기다리는 쓰기 안이다(에이전트 RESOLVE_TIMEOUT_S 와 같다). 넘으면 확인하지 못한 것이다.
RESOLVE_TIMEOUT_S = 20.0
# 후보 힌트 — 과제에 붙은 기구 CAD 원천(StepForge 프로젝트)의 과제 정보. 그 plm_task 는 받는 앱의 한 판정으로 푼 행이라 보일 후보일 뿐 확인이
# 아니다(PLAN §4.3 '기구 CAD 에서').
PROJECT_META_TOOL = "get_project_meta"


def gateway_alias(app_key: str, tool: str) -> str:
    """게이트웨이의 호출 전용 별칭 `<백엔드 키(하이픈 뺌)>_<원래 이름>` — 이름이 겹쳐 접두가 붙든 아니든 늘 그 백엔드로 간다."""
    return f"{app_key.replace('-', '')}_{tool}"


RESOLVER_CALL = gateway_alias(RESOLVER_APP, RESOLVER_TOOL)

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


# ---------------------------------------------------------------- SP 과제 key — 그 사람의 PAT 로 스스로 부른 풀이의 결과 행에서만
def pat_absent_error() -> AppError:
    """그 사람의 포털 PAT 가 없어(없음 · 폐기 · 풀리지 않음 · 곧 끝남) 풀이를 부르지 않는다 — 409 `sp_pat_absent`. 박스 읽기 PAT 로 내려가지
    않는다(ECAD 보드 찾기 · 붙이기 확인과 같은 자격 — 그 사람이 StepForge 를 볼 수 있는지는 게이트웨이가 그 사람의 PAT 로 가른다)."""
    return AppError("sp_pat_absent",
                    "그 사람의 포털 PAT 가 없거나 곧 끝나 허브 과제 풀이를 부르지 않습니다 — SP 과제는 그 사람의 PAT 로 부른 풀이의 결과 행에서만"
                    " 적습니다(박스 읽기 PAT 로 내려가지 않습니다). 웹 설정 화면에서 포털 PAT 를 등록하거나 Claude 에서 hwax_risk 도구를 다시 불러"
                    " 자동 등록한 뒤 다시 합니다.", 409, detail={"fix": "portal_pat", "tool": RESOLVER_CALL})


def not_confirmed_error(key: str, why: str) -> AppError:
    """확인하지 못했다 — 422 `sp_task_not_confirmed`(적지 않는다). 까닭(`why`)에는 결과 행의 key 를 싣지 않는다."""
    return AppError("sp_task_not_confirmed", f"SP 과제 key {key!r} 를 확인하지 못해 적지 않았습니다 — {why}", 422,
                    detail={"why": why, "tool": RESOLVER_CALL})


def _failure(reply: dict) -> str:
    """풀이를 부르지 못한 까닭 — 기한 넘김 · 도구 오류(그 글 200자) · 그 밖(전송 · HTTP · 읽지 못한 답)."""
    error = str(reply.get("error") or "unknown_error")
    if error == DEADLINE_EXCEEDED:
        return f"허브 과제 풀이({RESOLVER_TOOL})가 {RESOLVE_TIMEOUT_S:g}초 안에 답하지 않았다 — 확인하지 못했다"
    if error == "tool_error":
        detail = reply.get("detail")
        text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False, default=str)
        return f"허브 과제 풀이({RESOLVER_TOOL})가 오류로 답했다 — {' '.join(text.split())[:200]}"
    return f"허브 과제 풀이({RESOLVER_TOOL})를 부르지 못했다({error})"


def fingerprint(result: Any) -> str:
    """풀이 답(구조화 값)의 지문 — 열쇠 정렬 · 공백 없는 JSON 의 sha256(반출 원문 지문 rr_brief_calls.sha256 과 같은 꼴). NaN 이 든 답도
    지문을 낸다(canonical_json 은 그런 값을 거절한다)."""
    return sha256_hex(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str))


def confirm(channel: Any, key: str) -> dict:
    """그 사람의 채널(`McpHttpClient` — 그 사람의 포털 PAT)로 풀이를 한 번 불러 key 를 확인한다 — 확인이면 풀이 지문 {tool, at, sha256},
    아니면 422 `sp_task_not_confirmed`(까닭). 질의를 되실은 칸 · 부분 일치 · 과제코드 · 별칭으로 걸린 행(key 가 다르다) · 같은 key 둘 이상 ·
    비활성 행 · 부르지 못함 · 도구 오류 · 읽지 못한 답 · 기한 넘김은 모두 확인이 아니다(에이전트 delib_subject.confirm 과 같은 규칙)."""
    try:
        reply = channel.call(RESOLVER_CALL, {"query": key, "limit": RESOLVE_LIMIT, "full": True},
                             deadline=time.monotonic() + RESOLVE_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 — 부르지 못하면 확인하지 못한 것이다(적지 않는다)
        raise not_confirmed_error(key, f"허브 과제 풀이({RESOLVER_TOOL})를 부르지 못했다({type(exc).__name__})") from exc
    if not reply.get("ok"):
        raise not_confirmed_error(key, _failure(reply))
    result = reply.get("result")
    if not isinstance(result, dict):
        raise not_confirmed_error(key, f"허브 과제 풀이({RESOLVER_TOOL})의 답을 객체로 읽지 못했다")
    tasks = result.get("tasks")
    rows = [r for r in tasks if isinstance(r, dict)] if isinstance(tasks, list) else []
    exact = [r for r in rows if r.get("key") == key]
    if len(exact) == 1 and exact[0].get("active") is False:
        # 허브에서 지워졌거나 합쳐진 과제(거울은 비활성 행도 낸다). 합쳐진 곳(merged_into)의 key 는 싣지 않는다 — 아래와 같은 까닭이다.
        raise not_confirmed_error(key, f"허브에서 비활성인 과제다({str(exact[0].get('gone_reason') or '까닭 모름')[:40]}) —"
                                       f" {RESOLVER_TOOL} 로 지금 산 과제를 찾아 그 key 로 단다")
    if len(exact) == 1:
        return {"tool": RESOLVER_CALL, "at": now_epoch(), "sha256": fingerprint(result)}
    if exact:
        why = f"풀이 결과에 key 가 글자 그대로 같은 행이 {len(exact)}개다 — 고르지 않는다"
    else:
        cause = str((result.get("why") or {}).get("cause") or "") if isinstance(result.get("why"), dict) else ""
        why = (f"풀이 결과 {len(rows)}행 가운데 key 가 글자 그대로 같은 행이 없다" + (f"(풀이의 까닭 {cause})" if cause else "")
               + f" — {RESOLVER_TOOL} 로 찾아 결과 행의 key(운영 허브는 과제명 — 과제코드가 아니다)를 그대로 주면 확인된다")
    raise not_confirmed_error(key, why)
