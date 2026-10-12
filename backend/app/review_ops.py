# 카드 대조 검토의 실패 분류·백오프·보류 코드·차단기 판정(M2.md §4.4 · m2-wp3b S2) — 순수 함수, 저장소·네트워크 없음
"""엔진·포털·앱이 내는 오류 코드를 셀과 잡이 할 일로 옮기는 표의 유일한 구현이다.

- 분류표는 M2.md §4.4 가 정본이다. 표에 없는 코드는 내용 탓이고 원문을 그대로 남긴다. 엔진 오류 프레임의 `infra` 비트는
  보지 않는다(표가 이긴다 — `llm_timeout` 처럼 설계서끼리 부류가 갈린 코드를 이 표 한 자리에서 정한다).
- 셀의 실패 부류는 셋(인프라·내용 탓·기다림)이다. `job` 은 셀을 차감 없이 놓고 잡을 보류하는 갈래, `pack` 은 그 전문가의
  카드 묶음을 다시 받는 갈래, `cancelled` 는 사람의 정지·취소·앱 종료다.
- 기다림은 어디에도 세지 않는다 — 셀의 호출 수·연속 인프라 실패·차단기 창 어디에도 들지 않는다(P-02(1)).
- 백오프 흩뿌림은 난수가 아니라 해시로 정한다. 같은 셀·같은 연속 횟수면 재기동 뒤에도 같은 값이다.
- 손잡이(호출 벽시계·읽기 한도·내용 탓 한도)는 여기 두지 않는다. 그 값은 설정이 읽고, 이 모듈은 그 이름만 `knob` 으로 알린다.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.common import sha256_hex

# ---------------------------------------------------------------- 부류
WAIT = "wait"
INFRA = "infra"
CONTENT = "content"
JOB = "job"
PACK = "pack"
CANCELLED = "cancelled"
OK = "ok"                        # 성공한 호출의 부류(호출 원장 outcome_class) — classify 는 내지 않는다.

# ---------------------------------------------------------------- 상수(실측 M2 파일럿으로 다시 정한다)
WAIT_DEFAULT_S = 30              # 자리 없음 응답에 retry_after_s 가 없을 때(엔진 CARD_REVIEW_RETRY_AFTER_S·포털 429 의 값)
BACKOFF_BASE_S = 30              # 인프라 백오프 min(30·2^(n−1), 900)초
BACKOFF_CAP_S = 900
BACKOFF_SPREAD = 0.2             # ±20% — 해시로 정한다
BREAKER_WINDOW = 20              # 끝난 호출 최근 20건
BREAKER_MIN = 10                 # 10건 미만이면 판정하지 않는다
BREAKER_INFRA_TRIP = 10          # 인프라 10건 이상 → llm_outage
PACK_RETRY_BASE_S = 60           # 카드 묶음 재시도 60초부터 두 배, 상한 1,800초
PACK_RETRY_CAP_S = 1800
PACK_RETRY_MAX = 6               # 502·503 이 이어지면 6번 뒤 셀 failed('pack_unavailable')
AGENT_NOT_FOUND_MAX = 3          # 404 agent_not_found 는 3번 뒤 셀 failed('agent_not_found')
CTX_FALLBACK_HOLD_S = 600        # 창 출처 fallback 이 이만큼 이어지면 잡 보류 ctx_unknown
CHECK_DISAGREE_MAX = 5           # 서버·앱 인용 대조 불일치가 잡에서 이 수를 넘으면 contract 보류(X1-21)

# 앱이 스스로 내는 코드의 고칠 손잡이(엔진 코드의 손잡이는 오류 프레임의 knob 이 알린다).
_APP_KNOBS: dict[str, str] = {
    "review_timeout": "HWAXRISK_REVIEW_CALL_TIMEOUT_S",
    "engine_silent": "HWAXRISK_REVIEW_READ_TIMEOUT_S",
}


@dataclass(frozen=True)
class HoldRule:
    """잡 보류 코드 하나의 재개 규칙. `delays_s` 는 보류 n 번째의 다시 재는 간격이고 끝 값을 되풀이한다."""

    auto: bool
    delays_s: tuple[int, ...] = ()
    resume_on: str | None = None     # 시계가 아니라 조건으로 재개한다(ctx_unknown — 창 출처가 server·env 로 돌아오면)


# 보류 코드표 — 자동 재개가 없는 것은 사람이 고치고 재개한다.
HOLD_CODES: dict[str, HoldRule] = {
    "user": HoldRule(auto=False),                    # 사람의 정지
    "credential": HoldRule(auto=False),              # 사용자 PAT 를 더 쓸 수 없다 — 서비스 계정으로 내려가지 않는다
    "content_fail_rate": HoldRule(auto=False),       # 차단기 — 내용 탓이 절반 이상
    "contract": HoldRule(auto=False),                # 앱과 엔진의 요청 계약이 어긋났다
    "ctx_too_small": HoldRule(auto=False),           # 창이 모자란다 — 다시 쪼개지 않는다(D-22)
    "llm_misconfigured": HoldRule(auto=False),       # 에이전트 서버의 LLM 설정(키·모델 이름)
    "llm_outage": HoldRule(auto=True, delays_s=(300, 600, 1200, 2400, 3600)),
    "aidh_unreachable": HoldRule(auto=True, delays_s=(300, 1800)),
    "agent_outdated": HoldRule(auto=True, delays_s=(300,)),
    "ctx_unknown": HoldRule(auto=True, resume_on="ctx_source"),
}


@dataclass(frozen=True)
class Outcome:
    """오류 하나를 셀과 잡이 할 일로 옮긴 것.

    - `code` 는 받은 코드 원문이다(표에 없는 코드도 그대로).
    - `charge` 는 셀의 내용 탓 수(`charged`)를 하나 올리나다. 한도에 닿으면 셀은 `failed(fail_code)` 다.
    - `hold_code` 는 `job` 부류에서 잡을 멈출 보류 코드다.
    - `retry_after_s` 는 `wait` 부류의 대기다.
    - `fail_code`·`max_tries` 는 셀이 끝내 실패할 때의 코드와 `pack` 부류의 재시도 횟수다.
    """

    code: str
    klass: str
    charge: bool = False
    hold_code: str | None = None
    retry_after_s: int | None = None
    knob: str | None = None
    fail_code: str | None = None
    max_tries: int | None = None


# ---------------------------------------------------------------- 분류표(M2.md §4.4)
_WAIT_CODES = frozenset({"review_busy", "engine_busy"})
_INFRA_CODES = frozenset({
    "llm_unreachable", "llm_timeout", "llm_error",
    "agent_unreachable", "agent_5xx", "agent_timeout", "agent_stream_idle", "portal_unreachable", "portal_5xx",
    "engine_stream_cut", "engine_silent", "restart", "store_write_failed",
})
_CONTENT_CODES = frozenset({"no_rows", "truncated_empty", "llm_rejected", "cards_unjudged", "review_parse_failed"})
_HOLD_BY_CODE: dict[str, str] = {
    "llm_misconfigured": "llm_misconfigured",
    "context_overflow": "ctx_too_small", "over_budget": "ctx_too_small", "ctx_too_small": "ctx_too_small",
    "oversize": "ctx_too_small",                      # plan 의 oversize — 앱이 ctx_too_small 로 멈춘다
    "ctx_unknown": "ctx_unknown",                     # 창 출처 fallback 이 CTX_FALLBACK_HOLD_S 이어졌다(앱)
    "credential_rejected": "credential", "credential_missing": "credential", "credential_expired": "credential",
    "pat_unavailable": "credential",
    "agent_outdated": "agent_outdated",               # 404 — 에이전트 서버·포털에 카드 대조 경로가 없다
    "unknown_fields": "contract", "rev_mismatch": "contract",
    "denied": "contract", "bad_request": "contract", "empty_unit": "contract", "unsupported_unit_kind": "contract",
    "deck_too_large": "contract",
}
# 카드 묶음 조회 실패 — 그 전문가 묶음만 다시 받는다(재시도 횟수, 다 쓰면 셀의 실패 코드).
_PACK_CODES: dict[str, tuple[int, str]] = {
    "card_fetch_failed": (PACK_RETRY_MAX, "pack_unavailable"),
    "card_list_failed": (PACK_RETRY_MAX, "pack_unavailable"),
    "card_list_unstable": (PACK_RETRY_MAX, "pack_unavailable"),
    "tools_unavailable": (PACK_RETRY_MAX, "pack_unavailable"),
    "agent_not_found": (AGENT_NOT_FOUND_MAX, "agent_not_found"),
}
# 코드 없이 상태만 온 응답(본문이 JSON 이 아닌 502·429 등)의 코드.
_CODE_BY_STATUS: dict[int, str] = {
    401: "credential_rejected", 403: "denied", 404: "agent_outdated", 409: "rev_mismatch", 422: "bad_request",
    429: "engine_busy",
}


def classify(code: str | None, *, http_status: int | None = None, retry_after_s: int | float | None = None,
             knob: str | None = None, timeouts_before: int = 0) -> Outcome:
    """오류 코드 하나를 부류로 옮긴다(M2.md §4.4 의 표).

    - `http_status` 는 코드가 비었을 때만 본다(5xx 는 `portal_5xx`, 표에 없는 상태는 `http_<상태>` 로 내용 탓).
    - `retry_after_s` 는 기다림 부류에서만 쓰고, 없거나 0 이하면 `WAIT_DEFAULT_S` 다.
    - `knob` 은 오류 프레임이 알린 손잡이다. 없으면 앱이 내는 코드의 손잡이를 채운다.
    - `timeouts_before` 는 같은 호출이 앞서 앱의 호출 벽시계(`review_timeout`)에 걸린 횟수다. 처음은 인프라, 두 번째부터 내용 탓이다.
    """
    name = str(code or "").strip()
    if not name and http_status is not None:
        status = int(http_status)
        name = _CODE_BY_STATUS.get(status) or ("portal_5xx" if 500 <= status <= 599 else f"http_{status}")
    name = name or "unknown"
    knob = knob or _APP_KNOBS.get(name)

    if name == "cancelled":
        return Outcome(code=name, klass=CANCELLED)
    if name in _WAIT_CODES:
        wait = int(retry_after_s) if retry_after_s is not None and retry_after_s > 0 else WAIT_DEFAULT_S
        return Outcome(code=name, klass=WAIT, retry_after_s=wait, knob=knob)
    if name == "review_timeout":
        if timeouts_before >= 1:
            return Outcome(code=name, klass=CONTENT, charge=True, knob=knob, fail_code=name)
        return Outcome(code=name, klass=INFRA, knob=knob)
    if name in _INFRA_CODES:
        return Outcome(code=name, klass=INFRA, knob=knob)
    if name in _HOLD_BY_CODE:
        return Outcome(code=name, klass=JOB, hold_code=_HOLD_BY_CODE[name], knob=knob)
    if name in _PACK_CODES:
        tries, fail_code = _PACK_CODES[name]
        return Outcome(code=name, klass=PACK, knob=knob, fail_code=fail_code, max_tries=tries)
    # 표에 있는 내용 탓 코드와 표에 없는 코드 — 원문을 남기고 셀에 센다.
    return Outcome(code=name, klass=CONTENT, charge=True, knob=knob, fail_code=name)


# ---------------------------------------------------------------- 백오프
def backoff_s(infra_streak: int, *, salt: str) -> int:
    """연속 인프라 실패 n 번째의 대기 — min(30·2^(n−1), 900)초에 ±20% 흩뿌림, 900초를 넘지 않는다.

    흩뿌림은 `salt`(셀 키 등)와 n 의 해시로 정한다 — 같은 인자면 같은 값이고, 셀마다 달라 한꺼번에 다시 나가지 않는다.
    n 이 1 미만이면 0 이다(실패가 없으면 기다리지 않는다).
    """
    n = int(infra_streak)
    if n < 1:
        return 0
    base = BACKOFF_BASE_S * 2 ** min(n - 1, 16)
    base = min(base, BACKOFF_CAP_S)
    fraction = int(sha256_hex(f"{salt}|{n}")[:8], 16) / 0xFFFFFFFF          # [0, 1]
    spread = base * (1.0 + BACKOFF_SPREAD * (2.0 * fraction - 1.0))
    return min(int(round(spread)), BACKOFF_CAP_S)


def pack_retry_s(attempt: int) -> int:
    """카드 묶음 재시도 n 번째의 대기 — 60초부터 두 배, 1,800초 상한(흩뿌림 없음)."""
    n = max(int(attempt), 1)
    return min(PACK_RETRY_BASE_S * 2 ** min(n - 1, 16), PACK_RETRY_CAP_S)


# ---------------------------------------------------------------- 보류
def hold_delay_s(hold_code: str, hold_n: int) -> int | None:
    """보류 n 번째(1 부터)의 다시 재는 간격. 시계로 재개하지 않는 코드(사람이 재개·조건 재개·모르는 코드)는 None 이다."""
    rule = HOLD_CODES.get(hold_code)
    if rule is None or not rule.auto or not rule.delays_s:
        return None
    index = min(max(int(hold_n), 1), len(rule.delays_s)) - 1
    return rule.delays_s[index]


# ---------------------------------------------------------------- 차단기
def breaker_verdict(recent: Iterable[str | None]) -> str | None:
    """끝난 호출의 부류(새것 먼저)에서 차단기 판정 — None · 'llm_outage' · 'content_fail_rate'.

    기다림·사람의 취소·아직 끝나지 않은 호출(None)은 세지 않는다. 남은 것의 최근 20건이 10건 이상일 때만 본다 —
    인프라가 10건 이상이면 `llm_outage`(자동 재개), 아니고 내용 탓이 절반 이상이면 `content_fail_rate`(사람이 재개)다.
    """
    counted: list[str] = []
    for klass in recent:
        if not klass or klass in (WAIT, CANCELLED):
            continue
        counted.append(klass)
        if len(counted) == BREAKER_WINDOW:
            break
    if len(counted) < BREAKER_MIN:
        return None
    if sum(1 for k in counted if k == INFRA) >= BREAKER_INFRA_TRIP:
        return "llm_outage"
    if 2 * sum(1 for k in counted if k == CONTENT) >= len(counted):
        return "content_fail_rate"
    return None
