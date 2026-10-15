# 배치 러너(plan §6.7·§8.2.9) — panel_loop 이 잡을 집어 패널을 편성·실행하고 SSE 귀속·커버리지·등록부로 넘긴다. 엔진은 주입식(PanelEngine)
from __future__ import annotations

import gzip
import inspect
import json
import logging
import re
import sqlite3
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import httpx

from app import brief, config, planner, review_ops, taxonomy
from app.common import canonical_json, http_client, new_uuid, now_epoch, sha256_hex
from app.errors import AppError

log = logging.getLogger("hwax_risk.runner")

# (스레드명, 폴링 주기 초). sync_loop 은 PAT 폐기 대조(§8.2.7)를 돌리고 external_sync 재시도(§5.5.3)는 P4 배선,
# nightly_loop(§7.7 야간 잡) 본문은 P6 에서 채운다. review_loop 은 카드 대조 검토 잡의 틱이다(재설계 M2 · m2-wp3b S8 —
# review_runner.ReviewLoop). synth_loop 은 종합 잡(영역 요약 → 과제 종합 → 보고서 판)의 틱이다(재설계 M3 S3-9 — synth.SynthWorker,
# 요약 호출은 틱마다 하나씩 차례로). chain_loop 은 끊긴 잡 사슬 메우기다(S3-5 — chain.sweep, 끝난 단계에 다음 잡이 없으면 하나).
_LOOPS: tuple[tuple[str, float], ...] = (("panel_loop", 5.0), ("sync_loop", 60.0), ("nightly_loop", 60.0),
                                         ("review_loop", 2.0), ("synth_loop", 5.0), ("chain_loop", 30.0))

# 좌석 귀속 정규식(plan §0.2.3·§6.7 7단계). SSE 스트림과 POST /api/panels/{id}/complete 의 events[] 에 같은 식을 쓴다.
STATUS_LOOKUP_RE = re.compile(r"^(?P<key>\S+) 조회: (?P<tool>\S+)$")
EVIDENCE_SEP = " · "
# 엔진 근거 카드의 source 중 좌석 근거가 아닌 것 — 브리프 항목의 메아리(`챗 정리 · <원천>`)와 지식카드 주입(`<키> · 지식카드`).
ENGINE_ECHO_PREFIX = "챗 정리"
KNOWLEDGE_SOURCE = "지식카드"

# 짧은 호출(스냅샷 캡처·필드 근거·명단 조회)에 사용자 PAT 를 쓰려면 남아 있어야 하는 수명. 패널은 이 값이 아니라
# config.credential_margin_s(패널 벽시계에서 유도)를 쓴다 — 이 값 하나로 패널까지 재던 동안 여유가 벽시계보다 작았다.
CREDENTIAL_MARGIN_S = 1800
ENGINE_FAIL_STREAK = 3             # 연속 3패널 error → 잡 failed
DIMINISHING_WINDOW = 3             # 최근 3패널이 신규 클러스터 <1 이면 수확 체감 정지
QUALITY_TOOL_USE_MIN = 0.8
QUALITY_IR_CITE_MIN = 0.5
QUALITY_ADVERSARY_OVERREJECT = 0.6
# 앱이 스트림을 놓은 사유(EngineStreamLost.code) — 패널 벽시계 · 줄 사이 침묵 · 중간 절단 · 사람의 취소·정지.
# 엔진·좌석의 실패가 아니다.
STREAM_LOST_CODES: tuple[str, ...] = ("panel_timeout", "engine_silent", "engine_stream_cut", "cancelled")
# 도는 패널이 잡의 취소·정지를 듣는 간격(초) — 프레임마다 잡 행을 읽으면 15초 ping 이 DB 를 두드린다. 한도가 아니라 주기다.
STOP_POLL_INTERVAL_S = 5
# 도는 패널을 닫게 하는 잡 상태와 패널에 적는 말. 패널이 도는 동안 이 상태로 가는 길은 사람의 조작뿐이다
# (자동 정지는 패널이 닫힌 뒤에 일어난다).
STOP_JOB_STATES: dict[str, str] = {"cancelling": "사용자가 잡을 취소했다", "cancelled": "사용자가 잡을 취소했다",
                                   "paused": "사용자가 잡을 일시정지했다"}
# 앱이 재기동해 닫은 패널의 error 문구. 스트림을 놓은 것과 같은 부류다 — 엔진·좌석의 실패가 아니고, 앱만 다시 떴으면
# 엔진 쪽 심의는 분리 태스크로 계속 돈다.
RESTART_CODE = "restart"
# 엔진이 라운드를 다 돌리고도 결정문을 내지 못해 error 로 끝낸 사유(error 프레임의 code) — 좌석은 전부 발언했다.
NO_DECISION_CODES: tuple[str, ...] = ("chair_failed",)
# 엔진이 받아 주지 않아 시작도 못 한 패널의 사유 — 포털 429 대기 예산 소진 · 그 대기 중의 앱 종료. 심의는 한 줄도 돌지 않았다.
UNSTARTED_CODES: tuple[str, ...] = ("engine_busy", "stopped")
# 브리프를 조립하지 못해 엔진에 보내지도 못한 패널의 사유(WP1 R-4 · P-13). 좌석 탓이 아니다 — 종전에는 좌석을 차감해,
# 결정론인 조립 실패(같은 입력이면 같은 자리에서 다시 멈춘다) 세 번에 좌석이 skipped 로 굳고 잡이 engine_fail_streak 로 죽었다.
# brief_error = 결정론(린터·단언·키·형) → 잡을 멈춘다. brief_retry = 일시 장애(DB 잠금·연결·파일) → 다시 편성하되 같은 타깃에서
# BRIEF_RETRY_MAX 번 이어지면 멈춘다.
BRIEF_ERROR_CODE = "brief_error"
BRIEF_RETRY_CODE = "brief_retry"
BRIEF_RETRY_MAX = 3
BRIEF_TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (sqlite3.OperationalError, httpx.HTTPError, OSError)
# 엔진은 끝났는데 그 결과를 원장에 앉히지 못한 패널(WP1 R-2). 결과 원문은 패널(rr_panels.result_gz)에 먼저 적혀 있어
# `POST /api/panels/{id}/repersist` 로 다시 앉힌다 — 좌석·엔진 탓이 아니다. 재기동이 저장 도중을 끊었으면 'persist_error: restart'.
# 그런 패널이 남은 타깃은 다시 저장하거나 포기하기 전까지 새 패널을 편성하지 않는다(awaiting_repersist, RR-ADV-1).
PERSIST_ERROR_CODE = "persist_error"
# 사람이 다시 저장을 포기한 패널(`…/repersist?discard=1`) — 엔진 결과는 패널에 남고 좌석은 다음 패널에서 다시 돈다.
PERSIST_ABANDONED_CODE = "persist_abandoned"
# 자격(사용자 PAT)이 없어 시작하지 못한 쟁점 패널 — 잡은 보류 credential 로 멈춘다(재설계 M3 review1 M1).
CREDENTIAL_HOLD_CODE = "credential_hold"
# 외부 응답자 길(Claude 길 X-2)이 닫혔거나 동의 · 신원 칸이 엔진에 닿지 않아 시작하지 못한 쟁점 패널 — 잡은 보류 external_config 로 멈춘다.
EXTERNAL_CONFIG_HOLD = "external_config"
# 좌석 재시도와 연속 실패(ENGINE_FAIL_STREAK)에 세지 않는 패널 error 코드 — 좌석 탓이 아닌 중단이다. 세면 좌석과
# 무관한 일 세 번에 그 좌석이 skipped 로 굳고 잡이 죽는다.
UNCHARGED_CODES: tuple[str, ...] = (*STREAM_LOST_CODES, RESTART_CODE, *NO_DECISION_CODES, *UNSTARTED_CODES,
                                    BRIEF_ERROR_CODE, BRIEF_RETRY_CODE, PERSIST_ERROR_CODE, PERSIST_ABANDONED_CODE,
                                    CREDENTIAL_HOLD_CODE, EXTERNAL_CONFIG_HOLD)
# 다시 저장을 기다리는 타깃의 잡이 줄에서 기다리는 까닭(잡 행 error) — 집으면 지운다.
REPERSIST_PENDING_CODE = "repersist_pending"
PROGRESS_WRITE_INTERVAL_S = 60     # 도는 패널의 '마지막 신호' 를 잡 행에 적는 간격 — 줄마다 적으면 15초 ping 이 DB 를 두드린다

# 러너 정본 경로가 부르는 모듈 함수(없으면 잡을 집지 않고 error 로 강등한다 — 반쪽 저장 방지).
REQUIRED_NARRATIVE = ("prior_evidence", "parse_risk_spec", "persist_panel_result")
REQUIRED_REGISTRY = ("merge_panel", "close_level", "build_consolidated_report")


class PanelEngine(Protocol):
    """심의 엔진 클라이언트(배선 담당 구현). 러너는 이 한 메서드만 부른다.

    run(delib_opts, owner_sub=None) -> {decision_text, turns, conv_id, events, credential?, call_path?}
      · turns  = [{round, persona, say, stance?, position?}]
      · events = 압축 로그 [{kind: 'status'|'evidence'|'personas'|'turn'|'warning'|'error', step?, tool?, source?, personas?}]
                 (None 이면 좌석 귀속 불가 — tool_calls_ok·used_tool 은 null 로 남는다)
    선택 메서드 health() -> {model, vllm?, engine_rev?, endpoint_host?} 가 있으면 D6 model_json 을 채운다.
    선택 인자 run(..., on_progress=) 를 받는 엔진에는 러너가 콜백을 준다 — 프레임이 올 때마다
    {last_frame_at, last_event_at, last_step, frames} 로 부르면 러너가 잡 행에 '마지막 신호' 를 적는다.
    선택 인자 run(..., conversation=) 를 받는 엔진에는 러너가 429 뒤의 재시도에 `EngineBusy.conversation` 을
    되돌려 준다 — 앞 시도가 만든 포털 대화를 다시 쓰라는 뜻이다.
    선택 인자 run(..., should_stop=) 를 받는 엔진에는 러너가 물음 함수를 준다 — 프레임마다 불러 사유(문자열)가
    돌아오면 스트림을 닫고 EngineStreamLost('cancelled') 로 올린다(사람이 그 잡을 취소·정지했다).
    선택 인자 run(..., on_conversation=) 를 받는 엔진에는 러너가 콜백을 준다 — 포털 대화를 만들면 스트림 전에 불러 그
    conv_id 를 곧바로 패널에 적는다(스트림 도중에 앱이 죽어도 재기동 복구가 그 연결을 지킨다, D48).
    포털 429 는 EngineBusy, 앱이 스트림을 놓은 것은 EngineStreamLost, 의장이 결정문을 못 낸 것은 EngineNoDecision,
    그 밖의 실패는 EngineError 로 올린다.
    """

    def run(self, delib_opts: Mapping[str, Any], *, owner_sub: str | None = None) -> Mapping[str, Any]: ...


class ReviewEngine(Protocol):
    """카드 대조 엔진 클라이언트(m2-wp3b S7 · M2.md 4.2~4.4). 검토 러너가 부르는 넷과 서버 관문 조회 하나다. 포털 대화를 만들지 않는다.

    자격은 부를 때마다 `email` 의 사람이 등록한 포털 PAT 하나다(사용자 결정 3 — 서비스 계정으로 내려가지 않는다).
      · limits(email=)        -> GET /card-review/limits 응답(M2.md 4.2)
      · pack(agent_key, email=) -> 그 전문가의 팩(cardpack.check_pack 이 보는 모양)
      · plan(body, email=)    -> {limits_rev, verdict_decks, sweep_decks, manifest_pages, oversize, soft_over, pair_over}
      · run(body, email=, on_progress=, should_stop=) -> result 프레임(M2.md 4.3) 그대로
      · health()              -> 패널 health() 에 card_review{capable, active, limit, limit_reason, request_worst_s, error}
    자리 없음(포털 429 engine_busy · 관문 review_busy · 503 ctx_unknown)은 EngineBusy(retry_after_s, code), 자격은
    PatUnavailable(code), 앱이 스트림을 놓은 것(engine_silent · engine_stream_cut · review_timeout · cancelled)은
    EngineStreamLost, 그 밖의 거절과 error 프레임은 EngineRejected(code) 다. 부류는 review_ops.classify 가 정한다.
    on_progress 는 프레임마다 {last_frame_at, last_event_at, last_step, frames} 로 불리고, should_stop 이 사유를 돌려주면
    스트림을 닫는다(닫으면 엔진이 그 LLM 호출을 거둔다).
    """

    def limits(self, *, email: str) -> Mapping[str, Any]: ...

    def pack(self, agent_key: str, *, email: str) -> Mapping[str, Any]: ...

    def plan(self, body: Mapping[str, Any], *, email: str) -> Mapping[str, Any]: ...

    def run(self, body: Mapping[str, Any], *, email: str, on_progress: Any = None,
            should_stop: Any = None) -> Mapping[str, Any]: ...

    def health(self) -> Mapping[str, Any]: ...


class EngineBusy(Exception):
    """엔진 슬롯이 없다(포털 agent_semaphore 429). 러너가 대기 후 다시 묻는다 — 엔진도 좌석도 실패한 것이 아니다.

    대기 예산(`HWAXRISK_ENGINE_BUSY_MAX_WAIT_S`)을 다 쓰면 좌석 재시도와 연속 실패에 세지 않고 잡을 멈춘다
    (run_panel). `conversation` 은 그 시도가 만든 포털 대화 (대화 id, 만든 자격 표기)다 — 러너가 재시도에 그대로
    되돌려 준다. 다시 쓰지 않으면 패널 하나가 빈 대화를 시도 수만큼 남긴다. 대화를 못 만들었으면 None 이다.

    카드 대조 경로(ReviewEngine)의 자리 없음도 이 예외다 — 포털 429 `engine_busy`, 엔진 관문 `review_busy`(429·스트림의 error
    프레임), 창 조회 중의 503 `ctx_unknown`. `retry_after_s` 는 그 응답이 알린 대기를 `review_ops.classify` 가 [1, 3600]초로 묶은
    값이고 `code` 는 받은 코드다. 패널 경로는 둘 다 None 이다.
    """

    def __init__(self, *args: Any, conversation: tuple[str, str] | None = None, retry_after_s: int | None = None,
                 code: str | None = None) -> None:
        super().__init__(*args)
        self.conversation = conversation
        self.retry_after_s = retry_after_s
        self.code = code


class EngineError(Exception):
    """엔진 호출이 실패했다(연결·타임아웃·error 이벤트). 패널은 error 로 닫힌다."""


class EngineStreamLost(EngineError):
    """앱이 스트림을 놓았다 — 패널 벽시계·줄 사이 침묵·중간 절단·사람의 취소·정지(`code` ∈ STREAM_LOST_CODES).

    엔진이 실패한 것이 아니다. 엔진은 심의를 분리 태스크로 돌려 구독이 끊겨도 끝까지 간다 — 그래서 패널은
    error 로 닫되 좌석 재시도와 연속 실패에 세지 않고 잡을 멈춘다(run_panel). `conv_id` 는 그 심의의 포털
    대화다(끊긴 뒤의 발언은 거기에만 남는다).
    """

    def __init__(self, code: str, message: str, *, conv_id: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.conv_id = conv_id


class EngineNoDecision(EngineError):
    """엔진이 라운드를 끝까지 돌렸는데 의장이 결정문을 내지 못했다(`code` ∈ NO_DECISION_CODES).

    좌석은 전부 발언했다 — 실패한 것은 맨 끝의 의장 호출(대개 LLM 호출 한도)이다. 엔진은 좌석별 마지막 입장을
    결과로 내리고 회의록을 보고서로 저장한 뒤 error 로 끝낸다. 그래서 패널은 error 로 닫되 좌석 재시도와 연속
    실패에 세지 않고, 엔진이 남긴 것(`conv_id`·`report_id`·`decision_text`)을 패널에 적고 잡을 멈춘다(run_panel).
    `knob` 은 엔진이 알린 설정 이름이다 — 엔진은 화면에 뜨는 글(message)에 이름을 넣지 않고 따로 싣는다. `cause` 는 외부 응답자
    심의(Claude 길 X-2)가 의장이 못 낸 까닭으로 싣는 코드다(external_worker_absent 따위 — 없으면 None).
    """

    def __init__(self, code: str, message: str, *, knob: str | None = None, conv_id: str | None = None,
                 report_id: Any = None, turns: Sequence[Mapping[str, Any]] = (), decision_text: str = "",
                 cause: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.knob = knob
        self.conv_id = conv_id
        self.report_id = report_id
        self.turns = list(turns)
        self.decision_text = decision_text
        self.cause = cause


class EngineRejected(EngineError):
    """카드 대조 엔진·포털 중계가 코드를 실어 거절했다 — 스트림 전 응답(4xx·5xx), 스트림의 error 프레임, 포털에 닿지 못한 것.

    `code` 는 받은 코드 원문이다(코드가 없는 응답은 상태로 정한 이름 — `review_ops.classify`, 연결 실패는 `portal_unreachable`).
    셀과 잡이 할 일은 `review_ops.classify(code)` 가 정한다 — `infra`·`retryable` 은 엔진이 실어 보낸 비트 그대로 남기되 분류에는
    쓰지 않는다(표가 이긴다). `knob` 은 엔진이 알린 고칠 설정이고 `detail` 은 받은 본문이다(스트림 전 응답이면 HTTP 상태 `http_status` 를
    더한다 — 엔진 error 프레임의 `status` 는 LLM 서버의 상태라 이름을 가른다).
    """

    def __init__(self, code: str, message: str, *, infra: bool | None = None, retryable: bool | None = None,
                 knob: str | None = None, detail: Mapping[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.infra = infra
        self.retryable = retryable
        self.knob = knob
        self.detail = dict(detail or {})


class PatUnavailable(Exception):
    """러너 자격 문제(자격 없음·포털 401/403). 폴백하지 않고 잡을 `error='pat_unavailable'` 로 멈춘다(plan §6.7.1).

    `code` 는 카드 대조 경로가 싣는 사유다 — `pat_unavailable`(등록한 PAT 가 없다·폐기·복호 실패) · `credential_expired`(남은 수명이
    `config.review_credential_margin_s` 이하) · `credential_rejected`·`credential_missing`(포털·엔진이 거절). 전부
    `review_ops.classify` 의 `credential` 보류다(서비스 계정으로 내려가지 않는다 — 사용자 결정 3). 패널 경로는 기본값을 둔다.
    """

    def __init__(self, *args: Any, code: str = "pat_unavailable") -> None:
        super().__init__(*args)
        self.code = code


# ---------------------------------------------------------------- 좌석 귀속(plan §6.7 7단계)
def attribute_events(
    events: Sequence[Mapping[str, Any]] | None,
    seat_keys: Sequence[str],
    *,
    adversary_key: str = planner.ADVERSARY_KEY,
) -> dict:
    """status/evidence/personas/turn 이벤트를 좌석에 귀속한다.

    status.step 이 '<key> 조회: <tool>' 이면 시도(tool_calls_n). evidence.source 의 ' · ' 앞이 좌석 키면 —
    `<key> · 지식카드` 는 받았다는 표시(knowledge_seen)일 뿐 도구 성공이 아니고, `included` 가 False 면 실패
    (tool_calls_failed — `<key> · 자유 조회 실패` 등), True 거나 키가 없으면 성공(tool_calls_ok, 종전). 엔진이 브리프 항목을
    되울리는 `챗 정리 · <원천>` 은 좌석 근거가 아니라 귀속 셈에 넣지 않는다(WP1 R-44·R-45·P-10). 지식카드 상태줄의 집계
    (status.knowledge)는 좌석의 knowledge_hits_n·knowledge_degraded 가 된다(R-43) — 보고가 없던 좌석은 None(미측정)이다.
    events 가 None 이면 귀속 불가 — 좌석마다 tool_calls_n/ok·used_tool 을 None 으로 둔다(C2 strong 비율 분모 제외).
    """
    known = set(seat_keys) | {adversary_key}

    def fresh() -> dict:
        return {"tool_calls_n": 0, "tool_calls_ok": 0, "tool_calls_failed": 0, "used_tool": False, "turns_n": 0,
                "tool_calls": [], "knowledge_seen": False, "knowledge_hits_n": None}

    seats: dict[str, dict] = {key: fresh() for key in list(seat_keys) + [adversary_key]}
    if events is None:
        for key in seats:
            seats[key].update({"tool_calls_n": None, "tool_calls_ok": None, "tool_calls_failed": None,
                               "used_tool": None})
        return {"seats": seats, "extra_seats": [], "personas_seen": [], "attribution_rate": None,
                "attributable": 0, "attributed": 0, "lookups": 0, "knowledge_queries": {}}

    personas_seen: list[str] = []
    attributable = attributed = lookups = 0
    activity_idx = 0
    knowledge_queries: dict[str, str] = {}
    for event in events:
        kind = str(event.get("kind") or event.get("event") or "")
        if kind == "personas":
            for item in event.get("personas") or ():
                key = item.get("key") if isinstance(item, Mapping) else item
                if key and str(key) not in personas_seen:
                    personas_seen.append(str(key))
            continue
        if kind == "turn":
            key = str(event.get("persona") or "")
            if key in seats:
                seats[key]["turns_n"] += 1
            continue
        if kind == "status":
            knowledge = event.get("knowledge")
            if isinstance(knowledge, Mapping) and knowledge.get("persona"):
                key = str(knowledge["persona"])
                if key in known:
                    seat = seats.setdefault(key, fresh())
                    hits = knowledge.get("hits")
                    seat["knowledge_hits_n"] = int(hits) if isinstance(hits, int) and not isinstance(hits, bool) else None
                    seat["knowledge_degraded"] = bool(knowledge.get("degraded"))
                    knowledge_queries[key] = str(knowledge.get("query") or "")
                continue
            match = STATUS_LOOKUP_RE.match(str(event.get("step") or ""))
            if not match:
                continue
            attributable += 1
            lookups += 1
            key, tool = match.group("key"), match.group("tool")
            idx = activity_idx
            activity_idx += 1
            if key in known:
                attributed += 1
                seats.setdefault(key, fresh())
                seats[key]["tool_calls_n"] += 1
                seats[key]["tool_calls"].append({"tool": tool or event.get("tool"), "activity_idx": idx})
            continue
        if kind == "evidence":
            source = str(event.get("source") or "")
            if EVIDENCE_SEP not in source:
                continue                                  # E0~E9·지정 도구 주입은 좌석 귀속 없음(공용)
            key, rest = (part.strip() for part in source.split(EVIDENCE_SEP, 1))
            if key == ENGINE_ECHO_PREFIX:
                continue                                  # 엔진의 브리프 메아리 — 좌석 근거가 아니다(R-45)
            attributable += 1
            if key in known:
                attributed += 1
                seat = seats.setdefault(key, fresh())
                if rest == KNOWLEDGE_SOURCE:
                    seat["knowledge_seen"] = True         # 받았다는 표시 — 좌석이 도구를 부른 것이 아니다(R-44)
                elif event.get("included") is False:
                    seat["tool_calls_failed"] += 1
                else:
                    seat["tool_calls_ok"] += 1
    for state in seats.values():
        if state["tool_calls_ok"] is not None:
            state["used_tool"] = state["tool_calls_ok"] >= 1
    extra = [k for k in personas_seen if k not in known]
    return {
        "seats": seats,
        "extra_seats": extra,
        "personas_seen": personas_seen,
        "attribution_rate": (attributed / attributable) if attributable else None,
        "attributable": attributable,
        "attributed": attributed,
        "lookups": lookups,
        # 좌석별 지식카드 검색어의 출처('caller' · 'question') — 앱이 검색어를 보냈는데 'question' 이면 옛 포털이 키를 버렸다.
        "knowledge_queries": knowledge_queries,
    }


def withheld_by_engine(events: Sequence[Mapping[str, Any]] | None) -> list[str]:
    """엔진이 화면 카드로만 띄우고 좌석에는 주지 않은 것 — `evidence.included=false` 중 좌석 귀속이 아닌 카드.

    엔진은 사전 근거를 예산·건수 초과나 빈 본문 때문에 못 실으면 그 사실을 카드 한 장으로 알린다(`source` 가
    무엇을, `note` 가 몇 건을). 배치 러너의 스트림은 아무도 보고 있지 않다 — 패널에 옮겨 적지 않으면 그 카드는
    누구에게도 닿지 않는다. 좌석 귀속 카드(`<key> · …`)는 여기서 다루지 않는다.
    """
    out: list[str] = []
    for event in events or ():
        source = str(event.get("source") or "")
        if str(event.get("kind") or "") != "evidence" or event.get("included") is not False \
                or not source or EVIDENCE_SEP in source:
            continue
        line = f"{source} — {event['note']}" if event.get("note") else source
        if event.get("knob"):
            line += f" (설정 {event['knob']})"      # 엔진은 어느 값을 올리라는 말을 사유가 아니라 knob 으로 따로 싣는다
        if line not in out:
            out.append(line)
    return out


# ---------------------------------------------------------------- 러너 자격(plan §6.7 3단계)
# 패널은 사람 자격으로만 돈다 — 요청자 → 타깃 owner 의 등록된 포털 PAT 이고 서비스 PAT 로 내려가지 않는다(리스크 앱 사람 자격 U-3,
# 카드 대조 D-26 과 같은 규칙). 서비스 시야(조직 공개 과제만)로 돈 패널은 겉으로 정상인데 결과가 그 사람의 기대와 다르다.
_CREDENTIAL_FALLBACK = {"owner": "타깃 소유자의 PAT 로 돈다", None: "쓸 자격이 없어 패널을 시작하지 않는다"}
# 웹 설정 화면의 버튼 이름(entry.SETTINGS_BUTTON 과 같은 글자 — 러너는 entry 를 import 하지 않는다).
_SETTINGS_BUTTON = "포털에서 발급해 등록"


# 자동 등록을 멈추는 길 — 켜져 있는 동안은 지우거나 포털에서 폐기한 PAT 도 Claude 에서 hwax_risk 도구를 부를 때 다시 만든다(의도다
# — Claude 만 쓰는 사람에게는 다시 켤 스위치가 없다, D3). 멈추는 길은 설정의 자동 등록 스위치인데 화면에 아직 없다 — 그때까지는
# 운영자가 앱 데이터 DB 의 _user_prefs 에서 끈다(포털 절차서 AUTO_SWITCH_RUNBOOK). 운영자가 그 사람으로 API 를 부를 길은 없어 말하지
# 않는다(R3-4). 지금 있는 길만 말한다(웹 자동 등록도 아직 없다, R2-8). GET /api/me 의 portal_pat.auto.how_to_stop 과
# pat_unavailable 안내가 같이 말한다.
AUTO_SWITCH_RUNBOOK = "포털 docs/risk-review-redesign/server-setup-m1.md §7-2"
AUTO_STOP_HINT = ("자동 등록이 켜져 있는 동안은 등록된 PAT 를 지우거나 포털에서 폐기해도 Claude 에서 hwax_risk 도구를 부를 때 다시"
                  " 만든다 — 멈추는 길은 설정의 자동 등록 스위치다(곧 생긴다 — 그때까지는 운영자가 앱 데이터 DB 에서 끈다,"
                  f" {AUTO_SWITCH_RUNBOOK}).")


def pat_unavailable_guidance(store: Any, email: str | None) -> str:
    """사람 자격이 없을 때의 안내 — 자동 등록이 어떻게 일어나는지 · 직접 등록하는 곳 · 멈추는 길 · 그 사람의 마지막 자동 등록
    실패(U-3 · R1 · D3)."""
    text = ("패널은 사람 자격(포털 PAT)으로만 돈다 — 서비스 계정으로 내려가지 않는다. Claude 에서 hwax_risk 도구를 아무거나 부르면"
            " 자동으로 등록된다(게이트웨이가 그 사람의 PAT 를 좁혀 받아 넘긴다). 웹 리스크 앱 설정 화면의"
            f" '{_SETTINGS_BUTTON}' 으로 직접 등록할 수도 있다.")
    get_prefs = getattr(store, "get_user_prefs", None)
    prefs = get_prefs(email) if email and callable(get_prefs) else None
    if prefs and not prefs.get("portal_pat_auto"):
        text += (" 이 사람은 자동 등록을 꺼 두어 Claude 로 불러도 등록되지 않는다 — 설정 화면의 버튼으로 등록하거나 자동 등록을 다시"
                 f" 켠다(설정의 스위치는 곧 생긴다 — 그때까지는 운영자가 앱 데이터 DB 에서 켠다, {AUTO_SWITCH_RUNBOOK}).")
    else:
        text += f" {AUTO_STOP_HINT}"
    if prefs and prefs.get("auto_error"):
        text += f" 마지막 자동 등록 실패: {prefs['auto_error']}"
    return text


def _registered_pat(store: Any, email: str | None) -> tuple[dict | None, int]:
    """그 사람이 등록한 포털 PAT 의 (자격 행, 남은 수명 초). 복호되지 않으면(키 없음·폐기 표기·손상) 행은 None 이다."""
    if not email:
        return None, 0
    from app import identity  # noqa: PLC0415 — identity 는 config 만 읽으므로 지연 import 로 순환을 피한다.

    row = store.get_credential(email)
    if not (row and identity.credential_pat(row)):
        return None, 0
    return row, int(row.get("pat_exp") or 0) - now_epoch()


def resolve_credential_with_note(store: Any, settings: Any | None, owner_sub: str | None,
                                 requester_sub: str | None = None) -> tuple[dict | None, str | None]:
    """`resolve_credential` 의 본체 — (자격, 사유). 자격이 있으면 사유는 요청자 PAT 를 수명 때문에 건너뛰었을 때만 있고, 자격이
    없으면(None) 사유는 늘 있다 — 무엇이 모자라고 어떻게 받는지(`pat_unavailable_guidance`).

    사용자 PAT 는 남은 수명이 `config.credential_margin_s`(패널 벽시계 + 429 대기 + 600초)를 넘을 때만 쓴다 —
    패널 도중에 만료될 토큰으로는 시작하지 않는다. 서비스 PAT 로는 내려가지 않는다(U-3) — 종전에는 모자라면 말없이 서비스 계정
    시야로 돌아 만든 사람은 까닭을 몰랐다.
    """
    cfg = config.settings if settings is None else settings
    margin = config.credential_margin_s(cfg)
    short: tuple[str, int] | None = None

    def note(kind: str | None) -> str | None:
        if short is None:
            return None
        return (f"{short[0]} 의 PAT 남은 수명 {max(short[1], 0) / 3600:.1f}시간이 필요 {margin / 3600:.1f}시간"
                f"(HWAXRISK_CREDENTIAL_MARGIN_S = 패널 벽시계 + 대기 + 600초)에 못 미쳐 {_CREDENTIAL_FALLBACK[kind]}")

    order = [("requester", requester_sub)] if requester_sub and requester_sub != owner_sub else []
    for kind, email in (*order, ("owner", owner_sub)):
        row, left = _registered_pat(store, email)
        if row is None:
            continue
        if left > margin:
            found = note(kind)
            return ({"kind": kind, "email": row.get("pat_email") or email},
                    found + " — 포털에서 PAT 를 다시 발급해 등록하라" if found else None)
        short = short or (str(email), left)
    who = [e for _, e in (*order, ("owner", owner_sub)) if e]
    why = note(None) or (f"{' · '.join(who) or '(사람 없음)'} 의 쓸 수 있는 포털 PAT 가 없어(등록 없음·폐기·복호 불가)"
                         f" {_CREDENTIAL_FALLBACK[None]}")
    return None, f"{why} — {pat_unavailable_guidance(store, who[0] if who else None)}"


def resolve_credential(store: Any, settings: Any | None, owner_sub: str | None,
                       requester_sub: str | None = None) -> dict | None:
    """(c) 잡을 만든 사람 → (b) 타깃 owner 의 등록된 포털 PAT 순으로 자격을 정한다. 둘 다 없으면 None — 서비스 계정으로 내려가지
    않는다(U-3).

    동료(editor)가 남의 과제에 잡을 만들 수 있게 되면서 '누구 자격으로 돌았나' 가 갈린다 — 첫 적중의
    email 을 `rr_jobs.credential_email` 에 적어 진행판·감사가 그 사실을 본다(plan §0.1.6·§6.7 3단계).
    시크릿 값은 돌려주지 않는다(엔진 클라이언트가 같은 규칙으로 다시 읽는다). 반환은 {kind, email?}.
    """
    return resolve_credential_with_note(store, settings, owner_sub, requester_sub)[0]


# ---------------------------------------------------------------- 판단 LLM(Claude 길 X-2 — 포털 docs/risk-claude-engine)
# 잡의 선택은 glm(없음과 같다) · claude 이고 엔진에는 external 로 보낸다(engine_client 가 옮긴다). 잡 params 의 칸 — `llm`(claude 잡에만
# 있다) · `consent_external`{by, at, source}(누가 · 언제 · 어느 입구로 반출에 동의했나) · `llm_mismatch`(claude 잡인데 외부 응답자 답이
# 아니었던 호출 · 패널 수). 사슬이 세우는 쟁점 · 종합 잡은 앞 잡의 llm 과 동의 기록을 물려받는다. GLM 잡에는 칸이 하나도 없다.
LLM_GLM = "glm"
LLM_CLAUDE = "claude"
LLM_CHOICES: tuple[str, ...] = (LLM_GLM, LLM_CLAUDE)
ENGINE_EXTERNAL = "external"
EXTERNAL_WORKFLOW = "hwax-risk-claude"     # 잡 주인이 Claude Code 에서 돌리는 워크플로(포털 infra/pipeline — X-3)
JUDGE_CLAUDE = "Claude(외부, 사용자 신고 모델)"   # 보고서 · 품질 글의 '판단 LLM' — 모델은 잡 주인이 Claude Code 에서 고른 것이다


def job_llm(params: Mapping[str, Any] | None) -> str | None:
    """잡의 판단 LLM 선택 — claude 면 'claude', 그 밖(칸 없음 · glm)은 None(GLM, 종전)."""
    return LLM_CLAUDE if (params or {}).get("llm") == LLM_CLAUDE else None


def llm_params(llm: str | None, consent: Mapping[str, Any] | None) -> dict:
    """잡 params(와 응답)에 넣을 칸 — claude 면 {llm, consent_external}, GLM 이면 {}(종전 params 와 같은 바이트)."""
    if llm != LLM_CLAUDE:
        return {}
    return {"llm": LLM_CLAUDE, "consent_external": dict(consent or {})}


def external_consenter(params: Mapping[str, Any] | None) -> str | None:
    """claude 잡에서 반출에 동의한 사람 — 그 잡의 엔진 호출(카드 대조 · 요약 · 쟁점 패널)은 이 사람의 PAT 로만 돈다(과제는 그 사람의
    Claude Code 워크플로가 집는다). GLM 잡 · 기록이 없으면 None."""
    if job_llm(params) is None:
        return None
    consent = (params or {}).get("consent_external")
    who = consent.get("by") if isinstance(consent, Mapping) else None
    return str(who) if who else None


def resolve_job_credential(store: Any, settings: Any | None, owner_sub: str | None, requester_sub: str | None,
                           params: Mapping[str, Any] | None) -> tuple[dict | None, str | None]:
    """쟁점 · 종합 잡의 자격 — GLM 은 `resolve_credential_with_note`(요청자 → 대상 소유자) 그대로다. claude 잡은 동의한 사람의 PAT
    하나만 본다 — 대상 소유자의 PAT 로도 서비스 계정으로도 내려가지 않는다(엔진의 과제는 호출 신원의 줄에 서고 그 사람의 워크플로만
    집는다 — 남의 PAT 로 돌면 아무도 집지 못하거나 동의하지 않은 사람의 Claude 로 나간다). kind 는 그 사람이 대상 소유자면 owner, 아니면
    requester 다(러너가 그 사람의 sub 를 엔진에 넘긴다)."""
    if job_llm(params) is None:
        return resolve_credential_with_note(store, settings, owner_sub, requester_sub)
    who = external_consenter(params)
    credential, note = resolve_credential_with_note(store, settings, who)
    if credential is not None:
        return {**credential, "kind": "owner" if who == owner_sub else "requester"}, note
    return None, (f"{note} — Claude 길은 반출에 동의한 사람({who or '기록 없음'})의 PAT 로만 돈다(대상 소유자 · 서비스 계정으로"
                  " 내려가지 않는다)")


def note_llm_mismatch(store: Any, job_id: str) -> None:
    """claude 잡의 답이 외부 응답자 답이 아니었다 — 잡 params 의 `llm_mismatch` 셈을 하나 올린다(한 문장 — 워커 여럿이 겹쳐도 잃지
    않는다). 잡 행 · 진행판이 이 셈을 보이고, 보고서 · 품질 글은 그 호출 · 패널의 표지를 센다."""
    store.execute("UPDATE rr_jobs SET params_json = json_set(COALESCE(params_json, '{}'), '$.llm_mismatch',"
                  " COALESCE(json_extract(params_json, '$.llm_mismatch'), 0) + 1), updated_at = ? WHERE id = ?",
                  (now_epoch(), job_id))


# ---------------------------------------------------------------- delib_opts 조립(plan §6.6.4)
def _delib_apps() -> list[str]:
    """자유조회 스코프 앱키(≤3) — 앱명을 하드코딩하지 않고 adapters/registry 가 발견한 값을 쓴다."""
    from app.adapters.registry import ADAPTERS

    keys: list[str] = []
    for adapter in ADAPTERS:
        if adapter.app_key and adapter.app_key not in keys:
            keys.append(adapter.app_key)
    return keys[:planner.MAX_APPS]


_CONTRACT_CUT_FMT = " …({chars}자 중 {kept}자)"


def seat_contract_evidence(domains: Sequence[str], cap: int | None = None) -> dict:
    """E0c — 이번 패널 착석 도메인의 좌석 계약 행. 대화 기록·MCP 경로 이중화.

    라인 전체(`brief.evidence_line`)가 E0c 상한(`cap`, 안 주면 바닥 표의 값) 안이다 — 브리프가 그 칸의 자리를 이 표의
    몫으로 비워 둔다. 행은 하나도 빼지 않는다. 다 안 들어가면 긴 행부터 같은 몫으로 줄이고 줄인 행 끝에 원문 길이를
    적는다(WP1 R-18 — 종전에는 행마다 200자에서 말없이 끊고, 합이 1,000자를 넘는 다섯째 도메인 행을 통째로 뺐다).
    """
    contract = taxonomy.load_json("seat-contract").get("contract", {})
    seen: list[str] = []
    for dom in domains:
        if dom not in seen:
            seen.append(dom)
    rows = [(dom, str(contract.get(dom) or "")) for dom in seen]
    rows = [(dom, row) for dom, row in rows if row]
    item = {"source": "seat_contract", "tool": "seat-contract.v1", "args": ",".join(seen), "result": "", "key": "E0c"}
    room = (brief.CAPS["E0c"] if cap is None else cap) - brief.line_overhead(item) - max(0, len(rows) - 1)
    kept_len = {dom: len(row) for dom, row in rows}
    if sum(kept_len.values()) > room:
        # 짧은 행은 통째로 두고 남은 자리를 긴 행들이 같은 몫으로 나눈다(물 채우기). 표식 길이는 그 몫 안이다.
        left = max(0, room)
        for index, (dom, row) in enumerate(sorted(rows, key=lambda r: len(r[1]))):
            share = left // (len(rows) - index)
            kept_len[dom] = min(len(row), share)
            left -= kept_len[dom]
    lines: list[str] = []
    for dom, row in rows:
        if kept_len[dom] >= len(row):
            lines.append(row)
            continue
        mark = _CONTRACT_CUT_FMT.format(chars=len(row), kept=kept_len[dom])
        body = max(0, kept_len[dom] - len(mark))
        lines.append(row[:body] + _CONTRACT_CUT_FMT.format(chars=len(row), kept=body))
    item["result"] = "\n".join(lines)
    return item


# ---------------------------------------------------------------- 좌석이 그 diff 를 여는가(WP1 P-06 · SEC-3)
# 좌석은 게이트웨이를 거쳐 이 앱을 부르고, 게이트웨이는 잡 자격의 이메일로 사람별 단언을 받아 온다(`routes.post_auth_sso`).
# 위임 헤더(X-Hwax-Delegate-Email)를 보내지 않는 옛 게이트웨이면 HEAXHub Caddy 가 그 이메일을 게이트웨이 서비스 토큰의 주인
# (heax 첫 관리자)으로 덮어, 좌석은 누구 자격이든 그 관리자로 보인다. 앱은 게이트웨이의 판을 물을 길이 없으므로 발급 요청이 위임
# 헤더를 실었는지를 받을 때마다 적고 마지막 것을 지금 게이트웨이의 판으로 읽는다. 자리는 rr_metrics 다 — 품질 카드의 지표 표에
# 그대로 보이고, 지표 재계산(같은 period 의 옛 자리를 지운다)은 period 가 무엇이든 이 행을 지우지 않는다(metrics.KEPT_ROWS ·
# 로그인한 누구나 period 'live' 로 재계산을 부를 수 있다 — RV-3).
GATEWAY_MINT_ROW = ("live", "global", "gateway_sso", "sso_mint_delegated")


def note_gateway_mint(store: Any, *, delegated: bool) -> None:
    """게이트웨이의 단언 발급 요청 1건을 적는다 — value 는 마지막 요청이 위임 헤더를 실었나(1·0), n 은 받은 수다."""
    store.execute(
        "INSERT INTO rr_metrics(period, dimension, key, metric, value, n, computed_at) VALUES (?, ?, ?, ?, ?, 1, ?)"
        " ON CONFLICT(period, dimension, key, metric) DO UPDATE SET value = excluded.value, n = n + 1,"
        " computed_at = excluded.computed_at",
        (*GATEWAY_MINT_ROW, 1.0 if delegated else 0.0, now_epoch()))


def gateway_mint_seen(store: Any) -> dict | None:
    """마지막으로 받은 게이트웨이 발급 요청 `{delegated, at}` — 위임 헤더를 실었나와 받은 시각. 한 번도 받지 않았으면 None."""
    row = store.query_one(
        "SELECT value, computed_at FROM rr_metrics WHERE period = ? AND dimension = ? AND key = ? AND metric = ?",
        GATEWAY_MINT_ROW)
    if row is None or row["value"] is None:
        return None
    return {"delegated": bool(row["value"]), "at": int(row["computed_at"] or 0)}


def gateway_delegates(store: Any) -> bool | None:
    """마지막으로 받은 게이트웨이 발급 요청이 위임 헤더를 실었나 — 한 번도 받지 않았으면 None."""
    seen = gateway_mint_seen(store)
    return None if seen is None else seen["delegated"]


# 좌석이 그 diff 를 못 여는 까닭 — 패널 품질 `diff_ref_withheld` 에 그대로 남는다. 열릴지 확인하지 못해 싣기는 한 까닭
# (gateway_unseen·gateway_folded_stale)은 패널 품질 `gateway_unverified` 로 간다(RV-3).
DIFF_REF_WHY = {
    "diff_absent": "diff 나 그 과제가 원장에 없다.",
    # 패널은 이제 서비스 계정으로 돌지 않는다(U-3) — 그 전에 서비스 자격으로 집힌 옛 잡·사람 없는 자격에서만 나온다.
    "service_credential": ("잡 자격에 사람이 없다(서비스 계정 — 패널이 사람 자격으로만 돌기 전의 잡) — 좌석은 조직 공개"
                           "(mcp_visibility='org') 과제만 연다. 소유자나 잡을 만든 사람의 포털 PAT 가 등록되면 그 사람 자격으로 돈다."),
    "not_member": "잡 자격의 사람이 이 과제의 소유자도 구성원도 아니다.",
    "gateway_sso_off": ("이 앱에 게이트웨이 SSO 시크릿(HWAXRISK_HEAX_GATEWAY_SECRET)이 없다 — 사람별 단언 발급(POST /api/auth/sso)이"
                        " 404 이고 단언도 검증되지 않아, 좌석은 늘 서비스 세션(heax 첫 관리자)으로 보여 이 과제를 not_visible 로 받는다."
                        " 운영자가 게이트웨이의 사람별 위임(per_user_sso.hwax_risk)과 이 앱의 같은 시크릿을 설정하면 다음 패널부터"
                        " 싣는다."),
    "gateway_unseen": ("이 앱에 게이트웨이 시크릿은 있지만 사람별 단언 발급(POST /api/auth/sso)을 아직 받은 적이 없다 — 좌석이 잡"
                       " 자격의 사람으로 보일지 모르지만 diff_id 는 싣는다(게이트웨이 쪽에 per_user_sso.hwax_risk 가 없거나 시크릿이"
                       " 다르면 좌석은 서비스 세션의 heax 첫 관리자로 보여 그 호출이 not_visible 일 수 있다). 좌석의 첫 호출이 발급을"
                       " 일으켜 다음 패널부터 판정한다."),
    "gateway_folded_stale": ("마지막 발급 기록은 위임 헤더 없는 옛 판이었지만 단언 수명보다 오래됐다 — 게이트웨이가 그 단언을 이미 버려"
                             " 좌석의 다음 호출이 새로 발급받으므로, 지금의 판을 모른 채 diff_id 를 싣는다. 그 발급이 다음 패널부터"
                             " 판정한다."),
    "gateway_folded": ("게이트웨이가 위임 헤더(X-Hwax-Delegate-Email)를 보내지 않는 옛 판이다 — HEAXHub Caddy 가 좌석의 이메일을"
                       " 게이트웨이 서비스 토큰의 주인(heax 첫 관리자)으로 덮어, 좌석이 이 과제를 not_visible 로 받는다. 게이트웨이를"
                       " 그 헤더를 싣는 판으로 올리면 다음 발급부터 열린다."),
}


def diff_ref_withheld(store: Any, diff_id: str, credential_kind: str | None, email: str | None) -> dict | None:
    """좌석이 이 패널 자격으로 `risk_get_diff` 를 못 여는 까닭 `{reason, why}` — 열 수 있으면 None(WP1 P-06 · SEC-3).

    MCP 문지기(`routes.mcp_scope_owner`)와 같은 규칙이다 — diff 의 두 과제가 모두 보여야 한다. 조직 공개 과제는 좌석이 누구로
    보이든 열린다. 아니면 좌석이 사람 자격(owner·requester)의 이메일로 보여야 하고 그 사람이 소유자·구성원이어야 한다 — 좌석이
    그 이메일로 보이는 것은 게이트웨이가 위임 헤더를 싣는 판일 때뿐이다(위 절). 못 여는 자격에 diff_id 를 실으면 엔진이 그 도구를
    맨 앞에 세우고 안내하는데 좌석의 호출은 not_visible 로 떨어진다(isError 가 아니라 게이트웨이 감사에도 실패로 남지 않는다).

    발급 기록이 없거나 단언 수명보다 오래된 옛 판 기록이면 열릴지 모르는 것이라 막지 않는다 — `shipped: True` 를 단 까닭을 돌려주고
    러너는 diff_id 를 싣되 패널 품질 `gateway_unverified` 로 남긴다(RV-3). 다만 앱의 게이트웨이 시크릿이 비면 발급 길이 닫혀
    기록이 영영 생기지 않으므로 '아직 모른다' 가 아니라 '못 연다'(gateway_sso_off)로 막는다(3차 검토 발견 3).
    """
    def withheld(reason: str) -> dict:
        return {"reason": reason, "why": DIFF_REF_WHY[reason]}

    def unverified(reason: str) -> dict:
        # 막지 않는다 — 막으면 좌석이 이 앱을 사람별로 부를 계기가 없어 판정 자료(발급 기록)가 끝내 생기지 않는다(RV-3).
        return {**withheld(reason), "shipped": True}

    row = store.query_one("SELECT base_project_id, target_project_id FROM rr_diffs WHERE id = ?", (diff_id,))
    if row is None:
        return withheld("diff_absent")
    private = False
    for project_id in {row["base_project_id"], row["target_project_id"]}:
        project = store.query_one("SELECT owner_sub, mcp_visibility FROM rr_projects WHERE id = ?", (project_id,))
        if project is None:
            return withheld("diff_absent")
        if project["mcp_visibility"] == "org":
            continue
        if credential_kind == "service" or not email:
            return withheld("service_credential")
        if project["owner_sub"] != email and store.query_one(
                "SELECT 1 FROM rr_project_members WHERE project_id = ? AND email = ?", (project_id, email)) is None:
            return withheld("not_member")
        private = True
    if private:
        # 시크릿이 비면 /api/auth/sso 가 404 이고 단언 검증도 실패한다 — 좌석은 늘 서비스 세션이고 발급 기록은 생길 수 없다. 기록
        # 없음(gateway_unseen)으로 읽어 실으면 개인 과제 diff 패널마다 좌석의 호출이 not_visible 로 떨어진다(3차 검토 발견 3).
        if not config.heax_gateway_secret():
            return withheld("gateway_sso_off")
        seen = gateway_mint_seen(store)
        if seen is None:
            return unverified("gateway_unseen")
        if not seen["delegated"]:
            # 단언 수명이 지난 옛 판 기록은 지금의 판을 말하지 못한다 — 게이트웨이를 올린 뒤 아무도 사람별로 부르지 않으면 영영 남았다.
            if now_epoch() - seen["at"] > int(config.settings.sso_ttl_s):
                return unverified("gateway_folded_stale")
            return withheld("gateway_folded")
    return None


def panel_question(store: Any, target_key: str, *, digest: Mapping[str, Any] | None = None,
                   diff_ref: bool = False) -> str:
    """질문 문자열(plan §6.6.4) — 과제코드·target_key·소스 id·변경 요지. 좌석 조회 단계의 문맥이다.

    변경 요지(`brief.change_digest`)가 있으면 그것을 싣는다 — 종전에는 요약 앞 200자(식별자뿐인 [대상] 줄)라 좌석이 무엇이
    바뀌었는지 모른 채 도구를 골랐다(WP1 R-24). 요지가 비면(이벤트 0건) 종전 문장이고 요약 첫 줄을 자르지 않는다.
    `diff_ref` 면 diff 타깃 문장에 `diff_id=<id>` 를 싣는다 — 엔진은 이 표식(`_RISK_DIFF_MARK`)이 있을 때만 좌석 도구에
    `risk_get_diff` 를 앞세우고 변경 전체를 보라고 안내한다(P-06). 좌석 자격이 그 diff 를 못 열면 싣지 않는다.
    """
    target = store.query_one(
        "SELECT target_key, kind, ref_id, project_id, base_project_id FROM rr_targets WHERE target_key = ?",
        (target_key,),
    )
    if target is None:
        raise AppError("E404", f"타깃이 없습니다: {target_key}", 404)

    def code_of(project_id: str | None) -> str:
        if not project_id:
            return "-"
        row = store.query_one("SELECT code FROM rr_projects WHERE id = ?", (project_id,))
        return row["code"] if row else project_id

    if target["kind"] == "diff":
        row = store.query_one("SELECT summary_text FROM rr_diffs WHERE id = ?", (target["ref_id"],))
        head = "기준 %s 대비 변경" % code_of(target["base_project_id"])
        if diff_ref:
            head += f"(diff_id={target['ref_id']})"
    else:
        row = store.query_one("SELECT summary_text FROM rr_states WHERE snapshot_id = ?", (target["ref_id"],))
        head = "현황"
    if digest is None:
        digest = brief.change_digest(store, target_key)

    parts: list[str] = []
    for source in store.query(
        "SELECT kind, ref_json FROM rr_sources WHERE project_id = ? ORDER BY kind ASC, id ASC", (target["project_id"],)
    ):
        try:
            ref = json.loads(source["ref_json"] or "{}")
        except ValueError:
            ref = {}
        if not isinstance(ref, dict):
            continue
        pairs = " ".join(f"{k}={ref[k]}" for k in sorted(ref) if ref[k] not in (None, "", [], {}))
        if pairs:
            parts.append(f"{source['kind']} {pairs}")

    if digest.get("text"):
        tail = f"변경 요지: {digest['text']}"
    else:
        summary = (row["summary_text"] if row and row["summary_text"] else "").split("\n", 1)[0]
        tail = f"{'diff' if target['kind'] == 'diff' else '현황'} 요약 첫 줄: {summary}"
    return (
        f"[리스크심사 {code_of(target['project_id'])} {target_key}] {head}이 각 도메인에서 어떤 리스크와 개선을 "
        f"낳는가를 도구 근거로 판정하라. 소스 {'; '.join(parts) if parts else '(등록된 소스 없음)'}. {tail}"
    )


def fit_evidence_slots(evidence: Sequence[Mapping[str, Any]]) -> tuple[list, list[str]]:
    """근거를 MAX_EVIDENCE 칸에 맞춘다 — (실을 것, 빠진 항목의 키).

    종전에는 `evidence[:12]` 가 13번째부터를 말없이 버렸다. 좌석 계약(E0c)은 브리프를 재고 난 뒤에 끼우고
    사용자 메모는 맨 끝에 붙으므로, 한 칸만 넘쳐도 가장 먼저 떨어지는 것이 사람이 직접 쓴 메모였다. 메모는
    12번째 칸의 주인이다(plan §6.6.3) — 넘치면 메모 앞의 항목이 뒤에서부터 빠지고, 빠진 키를 돌려준다.
    """
    items = list(evidence)
    if len(items) <= planner.MAX_EVIDENCE:
        return items, []
    memo = next((e for e in items if e.get("source") == "user_memo"), None)
    rest = [e for e in items if e is not memo]
    room = planner.MAX_EVIDENCE - (0 if memo is None else 1)
    return rest[:room] + ([] if memo is None else [memo]), \
        [str(e.get("key") or e.get("source") or "?") for e in rest[room:]]


def build_delib_opts(
    store: Any,
    settings: Any | None,
    panel: Mapping[str, Any],
    *,
    evidence: Sequence[Mapping[str, Any]] | None = None,
    user_memo: str | None = None,
    narrative_mod: Any | None = None,
    loss: dict | None = None,
    profile: Any | None = None,
    diff_ref: bool = False,
) -> dict:
    """패널 1건의 delib_opts(plan §6.6.4). human_note·continue_summary·non_negotiables·search_sources·
    stop_after_round·build_plan 은 절대 싣지 않는다(불변식 extra_seats == ∅ 의 전제). voc 는 반대로
    항상 'off' 로 싣는다 — 빼면 엔진 기본값 'auto' 가 되살아난다.

    `loss` 를 주면 좌석에 못 간 것을 거기 적는다 — `evidence_dropped`(12칸을 넘겨 빠진 항목 키)와
    `user_memo_cut`(메모를 다 못 실었을 때 `{chars, kept}`), `brief_shielded`(판단어·인젝션에 걸려 «» 로 싸거나
    자리표시자로 바꾼 줄), `brief_clipped`(항목마다 상한에 잘린 줄 수). 없으면 비어 있다. 호출자가 패널에 남긴다.
    `profile` 은 브리프의 크기다(`brief.web_profile` · `brief.PROFILE_MCP`, 안 주면 바닥) — 좌석 계약표(E0c)도 그 상한에 맞춘다.
    질문과 지식카드 검색어(`knowledge_query`)는 같은 변경 요지에서 나온다(WP1 S11) — 요지의 길이는 프로파일 배수로 는다.
    검색어가 포털 상한(600자)을 넘어 잘렸으면 `loss["knowledge_query_cut"]` 에 남는다. `diff_ref` 는 `panel_question` 의 것이다."""
    profile = profile or brief.PROFILE_LEGACY
    seats = panel["seats"]
    if panel.get("kind") == "issue":
        return _issue_delib_opts(store, panel, user_memo=user_memo, loss=loss, profile=profile)
    if evidence is None:
        module = narrative_mod
        if module is None:
            from app import narrative as module  # noqa: PLC0415 — 순환 import 회피(narrative 는 러너를 import 한다)
        build = getattr(module, "prior_evidence", None)
        if not callable(build):
            raise AppError("not_implemented", "narrative.prior_evidence 가 없습니다 — 브리프를 조립할 수 없습니다.", 501)
        brief_meta: dict = {}
        evidence = list(build(store, panel["target_key"], user_memo=user_memo,
                              seats=seats, panel_id=panel["id"], meta_out=brief_meta, profile=profile))
        if loss is not None and brief_meta.get("shielded"):
            loss["brief_shielded"] = list(brief_meta["shielded"])
        # E10(현장 VOC·문헌)을 서비스 PAT 로 물었으면 그 패널 브리프에 남긴다 — 사람 자격이 없어 내려간 짧은 조회다(U-3).
        if loss is not None and brief_meta.get("field_credential") == "service":
            loss["field_credential"] = "service"
        # E0c 는 아래에서 제 좌석 계약표로 갈아 끼운다 — 브리프 쪽 E0c 의 절단은 좌석이 받은 것이 아니라 옮기지 않는다.
        clipped = {k: v for k, v in (brief_meta.get("clipped") or {}).items() if k != "E0c"}
        if loss is not None and clipped:
            loss["brief_clipped"] = clipped
    else:
        evidence = list(evidence)
    # E0(스코프·게이트) 바로 뒤가 E0c 좌석 계약표다.
    evidence.insert(1 if evidence else 0, seat_contract_evidence([s["domain"] for s in seats], profile.cap("E0c")))
    if user_memo and not any(e.get("source") == "user_memo" for e in evidence):
        # 브리프가 M 을 빼고 돌아온 경우의 폴백 — 같은 조립(`memo_result`)으로 그 상한까지 싣고 잘렸으면 원문 길이를 적는다.
        evidence.append({"source": "user_memo", "tool": "note", "args": panel["target_key"],
                         "result": brief.memo_result(panel["target_key"], user_memo, profile.cap("M")), "key": "M"})
    evidence, dropped = fit_evidence_slots(evidence)
    if loss is not None:
        if dropped:
            loss["evidence_dropped"] = dropped
        cut = brief.memo_cut(next((e for e in evidence if e.get("source") == "user_memo"), None))
        if cut:
            loss["user_memo_cut"] = cut

    digest = brief.change_digest(store, panel["target_key"], max_chars=profile.inner(brief.DIGEST_CHARS))
    knowledge_query, query_cut = brief.knowledge_query_of(digest)
    if loss is not None and query_cut:
        loss["knowledge_query_cut"] = query_cut
    opts = {
        "chair_template": planner.CHAIR_TEMPLATE,
        "modifiers": list(panel["modifiers"]),
        "rounds": int(panel["rounds"]),
        "free_tools": planner.FREE_TOOLS,
        "tool_budget": planner.TOOL_BUDGET,
        "personas": [{"key": s["key"], "role": "", "origin": s["origin"]} for s in seats],
        "tools": list(panel["tools"]),
        "apps": _delib_apps(),
        # 엔진의 자동 VOC 환기를 끈다. 안 실으면 기본값 'auto' 라, 질문(diff 요약 첫 줄·소스 id 가 실린다)에
        # 엔진의 불량 화두 낱말(이슈·품질·불만·휨·발열 …)이 하나라도 있으면 SignalForge 를 부른다 — 환기 여부가
        # 요약 문구에 달리고, S26U 실사용에서는 심사마다 걸렸다. 필드 이력의 정본은 브리프 E5 의 E10 블록이다 —
        # `voc:` 인용은 거기 실린 것만 해석되므로(§0.2.1) 환기가 따로 넣은 VOC 는 인용해도 dangling 이고,
        # 소급 심사에서는 그 뒤에 생긴 이슈가 새어 든다.
        "voc": "off",
        "evidence": evidence,
        # timeout_s 는 싣지 않는다. 엔진에서 그 값은 패널 벽시계가 아니라 **LLM 호출 한 번**의 타임아웃이고
        # (엔진이 제 상한으로 다시 죈다) 포털 스키마는 상한 초과를 422 로 막는다 — 그때의 벽시계 40분(2400)을 여기
        # 실어 보내던 동안(상한은 1800초였다) 앱 → 포털 길의 패널은 전부 'HTTP 422' 로 닫혔다. 호출당 타임아웃은
        # 박스 설정(DELIB_TIMEOUT_S)의 몫이고, 패널 벽시계(HWAXRISK_PANEL_TIMEOUT_S)는 엔진 클라이언트가 스트림에서 잰다.
        "question": panel_question(store, panel["target_key"], digest=digest, diff_ref=diff_ref),
        # 앱이 띄운 심의다(M3 #26) — 엔진 관문은 사람이 띄운 심의(started_by ≠ app)만 카드 대조 절반 사유로 센다.
        "started_by": STARTED_BY_APP,
    }
    # 좌석 지식카드 검색어 — 안 주면 엔진이 질문 전체로 찾는다(종전). 변경이 없으면 키를 싣지 않는다.
    if knowledge_query:
        opts["knowledge_query"] = knowledge_query
    return opts


# 앱이 띄운 패널의 표지(포털 DelibOpts.started_by — Literal["human","app"]).
STARTED_BY_APP = "app"


def _issue_delib_opts(store: Any, panel: Mapping[str, Any], *, user_memo: str | None, loss: dict | None,
                      profile: Any) -> dict:
    """쟁점 패널의 delib_opts(M3 S3-7) — 근거는 `brief.build_issue_brief`(I1 → I4 → … → M, 좌석 계약 I0c 를 둘째 칸에), 질문은
    `issues.issue_question`, 지정 도구 없음, 3라운드 고정(panel_budget 을 쓰지 않는다), 보고서 저장 없음(save_report 0 — X3),
    검색어는 질문 그대로. `loss` 에는 브리프의 절단·방패와 12칸을 넘겨 빠진 항목을 적는다."""
    from app import issues  # noqa: PLC0415 — issues 는 이 모듈을 쓴다.

    # 편성이 실어 준 쟁점이 정본이다(없으면 — 다시 조립하는 길 — 그 쟁점 행).
    issue = panel.get("issue") or next(i for i in issues.issue_rows(store, panel["target_key"])
                                       if i["issue_id"] == panel["issue_id"])
    built = brief.build_issue_brief(store, panel["target_key"], issue, seats=panel["seats"], panel_id=panel["id"],
                                    profile=profile, user_memo=user_memo or None)
    evidence = list(built["evidence"])
    seat_item = {**seat_contract_evidence([s["domain"] for s in panel["seats"]], profile.cap("E0c")),
                 "key": brief.ISSUE_SEAT_KEY}
    evidence.insert(1 if evidence else 0, seat_item)
    evidence, dropped = fit_evidence_slots(evidence)
    if loss is not None:
        if dropped:
            loss["evidence_dropped"] = dropped
        if built["meta"].get("clipped"):
            loss["brief_clipped"] = dict(built["meta"]["clipped"])
        if built["meta"].get("shielded"):
            loss["brief_shielded"] = list(built["meta"]["shielded"])
    question = issues.issue_question(store, issue)
    return {
        "chair_template": planner.CHAIR_TEMPLATE,
        "modifiers": list(panel["modifiers"]),
        "rounds": issues.ISSUE_ROUNDS,
        "free_tools": planner.FREE_TOOLS,
        "tool_budget": planner.TOOL_BUDGET,
        "personas": [{"key": s["key"], "role": "", "origin": s["origin"]} for s in panel["seats"]],
        "tools": [],
        "apps": _delib_apps(),
        "voc": "off",
        "evidence": evidence,
        "question": question,
        "knowledge_query": question[:brief.KNOWLEDGE_QUERY_MAX],
        "save_report": 0,
        "started_by": STARTED_BY_APP,
    }


# ---------------------------------------------------------------- 패널 실행 원문·브리프 동결(plan §6.7.2 7단계·§5.6.1)
def brief_hashes(evidence: Sequence[Mapping[str, Any]], keys: Sequence[str] | None = None) -> dict:
    """브리프 항목별 해시 표 `{키: sha256[:12]}` — 다음 패널의 brief_drift 비교 기준이다.

    항목의 `key`(E0·E1 …)는 해시에 넣지 않는다. 이름표이지 내용이 아니다 — 넣으면 키를 싣기 전에 동결한
    패널과 견줄 때 내용이 그대로인데도 전 항목이 달라진 것으로 적힌다.
    """
    out: dict[str, str] = {}
    for index, item in enumerate(evidence):
        key = str((keys or [])[index]) if keys and index < len(keys) else str(item.get("source") or index)
        out[key] = sha256_hex(canonical_json({k: v for k, v in dict(item).items() if k != "key"}))[:12]
    return out


def freeze_brief(store: Any, panel: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]],
                 keys: Sequence[str] | None = None) -> dict:
    """패널이 실제로 받은 evidence 전문을 gzip 으로 동결한다(brief_gz·brief_hash·brief_item_hashes_json).

    브리프는 시변 조립물이라 원문이 없으면 quote·인용 재현이 불가하다. 같은 타깃의 이전 패널과 항목 해시를
    비교해 실제로 달라진 키만 `quality_json.brief_drift[]` 로 남긴다(plan §5.6.1).
    """
    payload = canonical_json(list(evidence))
    blob = gzip.compress(payload.encode("utf-8"))
    digest = sha256_hex(payload)[:12]
    item_hashes = brief_hashes(evidence, keys)
    previous = store.query_one(
        "SELECT brief_item_hashes_json FROM rr_panels WHERE target_key = ? AND id != ?"
        " AND brief_item_hashes_json IS NOT NULL ORDER BY panel_no DESC LIMIT 1",
        (panel["target_key"], panel["id"]))
    drift: list[str] = []
    if previous is not None:
        try:
            before = json.loads(previous["brief_item_hashes_json"] or "{}")
        except ValueError:
            before = {}
        drift = sorted(k for k in set(before) | set(item_hashes) if before.get(k) != item_hashes.get(k))
    store.execute(
        "UPDATE rr_panels SET brief_gz = ?, brief_hash = ?, brief_item_hashes_json = ? WHERE id = ?",
        (blob, digest, canonical_json(item_hashes), panel["id"]))
    return {"brief_hash": digest, "items": len(item_hashes), "brief_drift": drift}


def load_brief(store: Any, panel_id: str) -> dict:
    """동결한 브리프를 재조립 없이 되돌려준다(GET /api/panels/{id}/brief 의 본체)."""
    row = store.query_one(
        "SELECT id, target_key, owner_sub, brief_gz, brief_hash, brief_item_hashes_json"
        " FROM rr_panels WHERE id = ?", (panel_id,))
    if row is None:
        raise AppError("E404", f"패널을 찾지 못했습니다 — {panel_id}.", 404)
    if row["brief_gz"] is None:
        raise AppError("brief_absent", "이 패널에는 동결한 브리프가 없습니다.", 404)
    evidence = json.loads(gzip.decompress(row["brief_gz"]).decode("utf-8"))
    return {"panel_id": row["id"], "target_key": row["target_key"], "brief_hash": row["brief_hash"],
            "evidence": evidence,
            "item_hashes": json.loads(row["brief_item_hashes_json"] or "{}")}


def record_panel_calls(store: Any, panel: Mapping[str, Any], events: Sequence[Mapping[str, Any]] | None,
                       *, source: str = "events", conv_id: str | None = None) -> int:
    """좌석 도구 호출 원문을 rr_panel_calls 에 seq 순으로 남긴다(포털 대화가 아니라 이 표가 정본이다).

    `status` 는 시도, 뒤따르는 `evidence` 는 그 결과다. `text` 가 없으면 `result_gz=NULL` 이고 해시도 없다
    (그 인용은 §4.4.2 대조에서 `quote_unverifiable` 이 된다).
    """
    if not events:
        return 0
    store.execute("DELETE FROM rr_panel_calls WHERE panel_id = ?", (panel["id"],))
    seat_keys = {str(s.get("key")) for s in panel.get("seats") or ()}
    rows: list[tuple] = []
    pending: dict[str, dict] = {}
    seq = 0
    activity_idx = 0
    now = now_epoch()
    for event in events:
        kind = str(event.get("kind") or "")
        if kind == "status":
            match = STATUS_LOOKUP_RE.match(str(event.get("step") or ""))
            if not match:
                continue
            key, tool = match.group("key"), match.group("tool") or str(event.get("tool") or "")
            pending[key] = {"tool": tool, "activity_idx": activity_idx}
            activity_idx += 1
            continue
        if kind != "evidence":
            continue
        source_text = str(event.get("source") or "")
        key = source_text.split(EVIDENCE_SEP, 1)[0].strip() if EVIDENCE_SEP in source_text else ""
        opened = pending.pop(key, None)
        tool = (opened or {}).get("tool") or (
            source_text.split(EVIDENCE_SEP, 1)[1].strip() if EVIDENCE_SEP in source_text else source_text)
        seq += 1
        text = event.get("text") if isinstance(event.get("text"), str) else None
        blob = gzip.compress(text.encode("utf-8")) if text else None
        rows.append((
            f"{str(panel['id'])[:8]}-{seq:03d}", panel["id"], panel["target_key"], panel["owner_sub"],
            seq, key if key in seat_keys else None, None, source, tool, None, None, 1,
            blob, len(text.encode("utf-8")) if text else None, sha256_hex(text) if text else None,
            conv_id, (opened or {}).get("activity_idx"), now, None, None,
        ))
    if rows:
        store.executemany(
            "INSERT OR REPLACE INTO rr_panel_calls(call_id, panel_id, target_key, owner_sub, seq, agent_key,"
            " round, source, tool, app_key, args_text, ok, result_gz, result_bytes, sha256, conv_id,"
            " activity_idx, started_at, duration_ms, error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows)
    return len(rows)


# ---------------------------------------------------------------- 잡(plan §6.4.3·§8.2.3)
def _job_params(job: Mapping[str, Any]) -> dict:
    """잡 dict 의 params — 러너가 집은 잡은 `params`(이미 푼 것), 다시 저장의 잡은 행의 `params_json` 이다. 둘 다 없으면 {}."""
    if isinstance(job.get("params"), Mapping):
        return dict(job["params"])
    return _params(job) if "params_json" in job else {}


def _params(row: Mapping[str, Any]) -> dict:
    try:
        value = json.loads(row["params_json"] or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _local_midnight(ts: float | None = None) -> int:
    """서버 로컬 시각 기준 오늘 00:00 의 epoch 초(일일 상한·자동 재개 판정용).

    '지금' 은 앱 전체가 `common.now_epoch` 한 곳에서 읽는다 — time.time() 을 직접 읽으면 시계를 고정한
    시험·재현에서 rr_panels.created_at 과 기준이 어긋나 일일 상한이 영영 걸리지 않는다.
    """
    lt = time.localtime(ts if ts is not None else now_epoch())
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)))


def create_job(
    store: Any,
    target_key: str,
    tier: str,
    *,
    owner_sub: str,
    modifiers: Sequence[str] | None = None,
    user_memo: str | None = None,
    concurrency: int = 1,
    consent: bool = False,
    settings: Any | None = None,
    requester_sub: str | None = None,
    consent_source: str | None = None,
) -> dict:
    """배치 잡 1건을 만든다(POST /api/targets/{key}/jobs). Tier C 는 consent 필수, 러너 자격이 없으면 422.

    `requester_sub` 는 잡을 만든 사람이다(동료 editor 일 수 있다) — 자격은 요청자 → 타깃 owner 의 포털 PAT 이고(서비스 계정으로
    내려가지 않는다, U-3) 첫 적중의 email 이 `rr_jobs.credential_email` 에 남는다(plan §0.1.6).
    `consent_source` 는 동의가 들어온 입구다 — 'web'(웹 화면) · 'mcp'(Claude, 게이트웨이 위임 단언) · 'api'(개인 heax PAT Bearer 로
    부른 REST) · 'close_level'(C3 자동 후속).
    동의가 없으면 params 에는 None 으로 남는다(RV-7).
    """
    cfg = config.settings if settings is None else settings
    if tier not in planner.TIERS:
        raise AppError("E100", f"모르는 tier — {tier!r}. 허용 {list(planner.TIERS)}.", 422)
    panel_job_gate(store, target_key, tier)
    if tier == "C" and not consent:
        raise AppError("E100", "Tier C 는 consent:true 명시 승인이 필요합니다.", 422)
    credential, credential_note = resolve_credential_with_note(store, cfg, owner_sub, requester_sub)
    if credential is None:
        raise AppError("pat_unavailable", credential_note or pat_unavailable_guidance(store, requester_sub or owner_sub), 422)

    plan = planner.tier_plan(store, target_key, settings=cfg)
    row = next(t for t in plan["tiers"] if t["tier"] == tier)
    job_id = new_uuid()
    now = now_epoch()
    params = {
        "tier": tier,
        "modifiers": list(planner.resolve_modifiers(modifiers)),
        # 메모는 자르지 않고 저장한다 — 좌석에 갈 때 브리프 M 이 그 패널의 상한에 맞추고 잘렸으면 원문 길이를 밝힌다.
        # 종전에는 저장에서 2,000자로 말없이 끊어 넓은 창의 패널도 앞 2,000자만 받았다.
        "user_memo": (str(user_memo) if user_memo else None),
        "consent": bool(consent),
        # 동의가 어느 입구에서 왔나 — consent:true 만으로는 사람이 웹에서 누른 것과 에이전트가 넣은 것이 갈리지 않았다(RV-7).
        "consent_source": consent_source if consent else None,
        "credential": credential["kind"],
        "requester": requester_sub,
    }
    with store.tx():
        # 방식 바꾸기(routes.post_target_flow)와 겹치지 않게 같은 트랜잭션 안에서 문을 다시 본다 — 확인과 쓰기 사이에 대상이
        # cells 로 바뀌면 패널 잡이 카드 대조 대상에 선다.
        panel_job_gate(store, target_key, tier)
        store.execute(
            "INSERT INTO rr_jobs(id, target_key, owner_sub, tier, state, concurrency, params_json, credential_email,"
            " panels_done, panels_total, created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, 0, ?, ?, ?)",
            (job_id, target_key, owner_sub, tier, max(1, min(int(concurrency), int(cfg.risk_concurrency))),
             canonical_json(params), credential.get("email"), row["panels"], now, now),
        )
    out = {
        "job_id": job_id,
        "panels_planned": row["panels"],
        "llm_calls_estimate": {"low": row["llm_calls_low"], "high": row["llm_calls_high"]},
        "credential": credential["kind"],
        "credential_email": credential.get("email"),
    }
    # 등록한 PAT 가 있는데 수명 때문에 다른 자격으로 돈다 — 만든 사람에게 그 자리에서 알린다.
    if credential_note:
        out["credential_note"] = credential_note
    # 메모가 M 상한(또는 위 2,000자)을 넘으면 좌석은 앞부분만 받는다 — 패널이 돌기 전에, 쓴 사람에게 알린다.
    cut = brief.memo_cut({"result": brief.memo_result(target_key, user_memo)}) if user_memo else None
    if cut:
        out["user_memo_cut"] = cut
    return out


# 카드 대조(flow='cells') 대상에서 막는 패널 Tier — 쟁점 패널(M3 의 tier 'I')은 그 대상에서 도는 것이라 막지 않는다(D-24).
FLOW_GATED_TIERS: tuple[str, ...] = ("A", "B", "C")
# 살아 있는 잡의 상태(사람이 재개·취소할 수 있는 것까지).
LIVE_JOB_STATES: tuple[str, ...] = ("queued", "running", "paused", "cancelling")
# 패널 러너·진행판·브리프가 보는 잡 — mode 가 NULL(v4 전 행)이거나 panels 인 것. 검토 잡(reviews)은 그 러너의 것이다.
PANEL_JOBS_SQL = "COALESCE(mode, 'panels') = 'panels'"
# rr_jobs.mode 의 어휘(NULL = panels). v4 의 열 주석은 굳은 블록이라 넓힌 어휘는 여기와 v5 머리 주석에 적는다(M3.md 4.1) —
# issues 는 쟁점 패널 잡, synth 는 영역 요약·종합 잡이다(재설계 M3 의 잡 사슬). 공개 REST 의 mode 는 panels·reviews 그대로다.
JOB_MODES: tuple[str, ...] = ("panels", "reviews", "issues", "synth")
# 패널 러너가 집고 멈추고 취소를 닫는 잡 — 종전 패널 잡과 쟁점 잡(M3 S3-7, 쟁점 패널을 한 줄로 돈다). PANEL_JOBS_SQL 은 넓히지 않는다
# — 진행판·길잡이·검토 잡 문지기가 그것을 '패널 Tier 잡' 으로 읽는다(쟁점 잡은 tier 가 없다).
PANEL_RUNNER_MODES: tuple[str, ...] = ("panels", "issues")
RUNNER_JOBS_SQL = "COALESCE(mode, 'panels') IN ('panels', 'issues')"
# 에이전트 서버 비우기(update-all — M3.md 4.7 · #50) 동안 패널(coverage·쟁점)을 집지 않는다 — 잡은 줄에서 기다리고 이 말이 잡 행에 선다.
DRAIN_CODE = "draining"


def panel_job_gate(store: Any, target_key: str, tier: str) -> None:
    """패널 잡의 문지기 — 사용자 잡과 C3 자동 후속(_finish_job)이 둘 다 create_job 을 지나므로 여기 둔다(라우트가 아니라).

    카드 대조 대상(flow='cells')의 Tier A·B·C 는 422 `flow_mismatch`, 그 대상에 살아 있는 검토 잡이 있으면 409
    `review_job_running` 이다(한 대상의 두 방식이 같은 좌석·LLM 을 동시에 쓰지 않게, 재설계 M2 S6).
    """
    row = store.query_one("SELECT flow FROM rr_targets WHERE target_key = ?", (target_key,))
    if row is not None and row["flow"] == "cells" and tier in FLOW_GATED_TIERS:
        raise AppError("flow_mismatch", f"이 대상은 카드 대조(flow='cells') 방식이다 — Tier {tier} 패널 잡을 세우지 않는다."
                       f" 패널로 보려면 검토 잡이 서기 전에 방식을 panels 로 되돌린다(POST /api/targets/{target_key}/flow).", 422,
                       detail={"flow": "cells", "tier": tier})
    live = store.query_one(
        f"SELECT id, state FROM rr_jobs WHERE target_key = ? AND mode = 'reviews' AND state IN ({','.join('?' * len(LIVE_JOB_STATES))})"
        " ORDER BY created_at DESC LIMIT 1", (target_key, *LIVE_JOB_STATES))
    if live is not None:
        raise AppError("review_job_running", f"이 대상에는 살아 있는 카드 대조 검토 잡({live['id']}, {live['state']})이 있다 —"
                       " 그 잡이 끝나거나 취소된 뒤 패널 잡을 세운다.", 409, detail={"job_id": live["id"], "state": live["state"]})


def _set_job(store: Any, job_id: str, state: str, *, reason: str | None = None, error: str | None = None,
             by: str | None = None, hold: Mapping[str, Any] | None = None) -> dict:
    """잡 상태 전이 1건. `by` 는 주체다 — 사람은 email, 자동 정지는 'code:diminishing'·'code:daily_cap'(plan §0.6),
    엔진·좌석 탓이 아닌 중단으로 멈춘 것은 'code:<UNCHARGED_CODES 의 사유>' 다.

    `hold` 는 검토 잡의 보류 열({code, until, n?}) — 주면 같은 문장에서 hold_code·hold_until(·hold_n)을 쓴다. 패널 잡은 주지
    않는다(그 열을 건드리지 않는다 — 패널 경로의 문장은 종전 그대로다)."""
    now = now_epoch()
    actor = by or (f"code:{reason}" if reason in ("diminishing", "daily_cap") else None)
    sets, params = ["state = ?", "pause_reason = ?", "error = ?"], [state, reason, error]
    if actor:
        sets += ["state_by = ?", "state_at = ?"]
        params += [actor, now]
    if hold is not None:
        sets += ["hold_code = ?", "hold_until = ?"]
        params += [hold.get("code"), hold.get("until")]
        if "n" in hold:
            sets.append("hold_n = ?")
            params.append(int(hold["n"]))
    store.execute(f"UPDATE rr_jobs SET {', '.join(sets)}, updated_at = ? WHERE id = ?", (*params, now, job_id))
    out = {"job_id": job_id, "state": state, "pause_reason": reason, "state_by": actor, "state_at": now}
    if hold is not None:
        out.update({"hold_code": hold.get("code"), "hold_until": hold.get("until")})
    return out


# 사람의 재개·취소가 검토 잡의 보류 열 셋을 비우는 값(P-10 · X4-25).
_HOLD_CLEARED = {"code": None, "until": None, "n": 0}


def _job_row(store: Any, job_id: str) -> Any:
    row = store.query_one("SELECT state, COALESCE(mode, 'panels') AS mode, hold_code, target_key FROM rr_jobs WHERE id = ?",
                          (job_id,))
    if row is None:
        raise AppError("E404", f"잡이 없습니다: {job_id}", 404)
    return row


def pause_job(store: Any, job_id: str, *, reason: str = "user", by: str | None = None) -> dict:
    """일시정지(reason ∈ diminishing|daily_cap|user). 도는 패널이 있으면 그 스트림을 닫는다(`_stop_reader`) —
    패널 경계까지 기다리지 않는다. 닫힌 패널의 좌석은 차감 없이 pending 으로 돌아가고 재개하면 다시 편성된다.

    검토 잡은 사람의 정지가 보류 열을 hold_code='user'·hold_until=NULL 로 덮고, 코드가 멈춘(보류 코드가 사람이 아닌) paused
    에도 듣는다 — 사람이 멈춘 잡은 자동 재개가 다시 줄에 세우지 않는다(재설계 M2 S6, P-10)."""
    row = _job_row(store, job_id)
    if row["mode"] not in PANEL_RUNNER_MODES:
        if not (row["state"] in ("queued", "running") or (row["state"] == "paused" and row["hold_code"] != "user")):
            raise AppError("E100", f"일시정지할 수 없는 상태입니다 — {row['state']}.", 409)
        return _set_job(store, job_id, "paused", reason="user", by=by, hold={"code": "user", "until": None})
    if row["state"] not in ("queued", "running"):
        raise AppError("E100", f"일시정지할 수 없는 상태입니다 — {row['state']}.", 409)
    return _set_job(store, job_id, "paused", reason=reason, by=by)


def resume_job(store: Any, job_id: str, *, by: str | None = None) -> dict:
    """재개 — 멈춘 잡을 줄에 다시 세운다. 검토 잡은 보류 열 셋(hold_code·hold_until·hold_n)을 비운다."""
    row = _job_row(store, job_id)
    if row["state"] != "paused":
        raise AppError("E100", f"재개할 수 없는 상태입니다 — {row['state']}.", 409)
    # 보류 열은 검토 잡 · 종합 잡과, 자격 보류로 멈춘 쟁점 잡(review1 M1)만 쓴다 — 재개하면 비운다(종전 패널 잡은 늘 비어 있다).
    clear = row["mode"] not in PANEL_RUNNER_MODES or row["hold_code"] is not None
    return _set_job(store, job_id, "queued", by=by, hold=_HOLD_CLEARED if clear else None)


def cancel_job(store: Any, job_id: str, *, by: str | None = None) -> dict:
    """취소. 도는 잡은 cancelling 이 되고, 도는 패널이 그것을 듣고 스트림을 닫은 뒤 다음 편성에서 cancelled 가 된다.

    종전에는 패널이 끝까지 갔다 — 벽시계가 12시간이라 취소한 잡의 패널이 러너 자리와 그 타깃의 직렬 순서를 최대
    12시간 붙들었다. 닫는 것은 앱의 구독이다. 엔진 쪽 심의는 분리 태스크라 끝까지 돌 수 있다.

    검토 잡은 보류 열 셋을 비우고, 그 잡의 전문가·셀이 아직 도는(running) 동안은 상태와 상관없이 cancelling 이다 — paused 라도
    코드 보류는 도는 호출을 닫지 않는다(M2.md 5절 #13). 루프가 도는 것이 0 이 될 때 cancelled 로 닫고 진행판을 끝낸다. 그 사이
    잡이 살아 있어 새 잡이 그 셀을 범위에서 잃지 않는다(반대 검토 R3A-1). 도는 것이 없으면 곧바로 cancelled 이고 진행판을 끝난
    모양(phase cancelled · 워커 없음)으로 적는다. 그 뒤 트랜잭션 밖에서 그 잡이 건드린 전문가 보고서를 다시 짓는다(M3C-81 —
    review_runner.refresh_cancelled, 전문가마다 제 트랜잭션).
    """
    row = _job_row(store, job_id)
    if row["state"] in ("cancelled", "completed", "failed"):
        return {"job_id": job_id, "state": row["state"], "pause_reason": None}
    if row["mode"] in PANEL_RUNNER_MODES:
        state = "cancelling" if row["state"] == "running" else "cancelled"
        out = _set_job(store, job_id, state, by=by)
        if state == "cancelled" and row["mode"] == "issues":
            _untry_after_cancel(store, row["target_key"])
        return out
    from app import review_runner  # noqa: PLC0415 — review_runner 는 이 모듈을 import 한다.

    with store.tx():
        # 확인과 쓰기 사이에 루프가 전문가를 쥐지 않게(선점은 잡이 running 일 때만 서고 같은 트랜잭션 잠금을 쓴다) 한 트랜잭션으로.
        row = _job_row(store, job_id)
        if row["state"] in ("cancelled", "completed", "failed"):
            return {"job_id": job_id, "state": row["state"], "pause_reason": None}
        busy = review_runner.in_flight(store, job_id=job_id)
        if busy["heads"] or busy["cells"]:
            return _set_job(store, job_id, "cancelling", by=by, hold=_HOLD_CLEARED)
        out = _set_job(store, job_id, "cancelled", by=by, hold=_HOLD_CLEARED)
        review_runner.close_progress(store, job_id, "cancelled")
    review_runner.refresh_cancelled(store, job_id)
    return out


def _untry_after_cancel(store: Any, target_key: str) -> None:
    """사람이 취소한 쟁점 잡 — 남은 대기 쟁점은 `untried_cap(chain_cancelled)` 다(지우지 않는다 — 보고서 '미토의')."""
    from app import issues  # noqa: PLC0415 — issues 는 이 모듈을 쓴다.

    issues.untry_queued(store, target_key, "chain_cancelled")


def _panels_today(store: Any, target_key: str) -> int:
    """오늘 편성한 종전 패널(`kind='coverage'`) 수 — 쟁점 패널은 하루 상한에 세지 않는다(M3 #27)."""
    row = store.query_one(
        "SELECT COUNT(*) AS n FROM rr_panels WHERE target_key = ? AND created_at >= ? AND kind = 'coverage'",
        (target_key, _local_midnight()),
    )
    return int(row["n"] or 0) if row else 0


def engine_drain(engine: Any) -> bool:
    """에이전트 서버가 비우는 중인가 — 엔진의 `drain_state()`(`/health` 의 `drain.on` · `draining`, M3.md 4.7). 그 칸을 모르는
    엔진(옛 판·대역)이나 물음이 실패하면 거짓이다 — 비우기 신호를 못 읽었다고 러너를 세우지 않는다(종전 동작)."""
    probe = getattr(engine, "drain_state", None)
    if not callable(probe):
        return False
    try:
        state = probe()
    except Exception:  # noqa: BLE001 — 위 설명대로다.
        log.warning("에이전트 서버 비우기 상태를 읽지 못했다 — 비우지 않는 것으로 보고 이어 간다", exc_info=True)
        return False
    return bool(isinstance(state, Mapping) and state.get("on"))


def claim_next_job(store: Any, settings: Any | None = None, *, engine: Any | None = None) -> dict | None:
    """다음에 패널을 돌릴 잡 1건을 집는다. 타깃당 직렬·일일 상한·자격·취소·비우기를 여기서 판정한다.

    패널 잡과 쟁점 잡만 본다(`rr_jobs.mode` 가 NULL·panels·issues — 한 표에 카드 대조 검토 잡이 같이 산다, 재설계 M2 S6). 검토 잡은
    그 러너가 집고 멈추고 취소를 닫는다. 그래도 다른 잡이 집히면 패널 러너로 돌리지 않고 예외로 드러낸다. 쟁점 잡은 하루 상한으로
    멈추지 않는다(M3 #27). `engine` 을 주면 에이전트 서버가 비우는 중(`drain.on` — 범위와 상관없이)인지 보고, 그동안 패널을 집지
    않는다(#50 — 잡은 줄에서 기다린다).
    """
    cfg = config.settings if settings is None else settings
    midnight = _local_midnight()
    draining: bool | None = None
    for row in store.query(
        "SELECT id, target_key, owner_sub, tier, state, pause_reason, params_json, panels_done, updated_at"
        f" FROM rr_jobs WHERE state = 'paused' AND pause_reason = 'daily_cap' AND {PANEL_JOBS_SQL}"
        " ORDER BY created_at ASC, id ASC"
    ):
        if int(row["updated_at"] or 0) < midnight:
            _set_job(store, row["id"], "queued")

    for row in store.query(
        "SELECT id, target_key, owner_sub, tier, state, params_json, panels_done, panels_total, error,"
        " COALESCE(mode, 'panels') AS mode"
        f" FROM rr_jobs WHERE state IN ('queued', 'running', 'cancelling') AND {RUNNER_JOBS_SQL}"
        " ORDER BY created_at ASC, id ASC"
    ):
        job = dict(row)
        last_error = job.pop("error")
        if job["mode"] not in PANEL_RUNNER_MODES:
            raise RuntimeError(f"패널 러너가 패널 잡이 아닌 잡({job['id']})을 집었다 — claim_next_job 의 mode 거름을 본다.")
        if job["state"] == "cancelling":
            _set_job(store, job["id"], "cancelled")
            if job["mode"] == "issues":
                _untry_after_cancel(store, job["target_key"])
            continue
        busy = store.query_one(
            "SELECT id FROM rr_panels WHERE target_key = ? AND status = 'running' LIMIT 1", (job["target_key"],)
        )
        if busy is not None:
            continue
        waiting = awaiting_repersist(store, job["target_key"])
        if waiting:
            # 다시 저장을 기다리는 패널의 좌석은 pending 으로 돌아와 있다 — 이 잡이 편성하면 그 좌석을 가져가 저장해 둔
            # 결과가 영영 다시 앉지 못한다(seats_moved). 잡은 queued 그대로 건너뛰고(완료로 닫지 않는다) 까닭을 잡 행에 적는다.
            note = repersist_pending_note(waiting)
            if last_error != note:
                store.execute("UPDATE rr_jobs SET error = ?, updated_at = ? WHERE id = ?", (note, now_epoch(), job["id"]))
            continue
        if job["mode"] == "panels" and _panels_today(store, job["target_key"]) >= int(cfg.risk_daily_panel_cap):
            _set_job(store, job["id"], "paused", reason="daily_cap")
            continue
        if engine is not None:
            if draining is None:
                draining = engine_drain(engine)
            if draining:
                note = (f"{DRAIN_CODE}: 에이전트 서버가 비우는 중이다(update-all) — 새 패널을 집지 않는다."
                        " 비우기가 끝나면 이어 돈다")
                if last_error != note:
                    store.execute("UPDATE rr_jobs SET error = ?, updated_at = ? WHERE id = ?", (note, now_epoch(), job["id"]))
                continue
        credential, credential_note = resolve_job_credential(
            store, cfg, job["owner_sub"], _params(row).get("requester"), _params(row))
        if credential is None:
            # 멈춘 잡은 5초마다 다시 판정된다 — 글이 바뀔 때만 쓴다(위의 다시 저장 대기와 같다). 매번 쓰면 updated_at 이 늘
            # 지금이라 '언제부터 멈췄나' 가 보이지 않고 쓰기만 쌓인다.
            note = "pat_unavailable" + (f": {credential_note}" if credential_note else "")
            if last_error != note:
                store.execute("UPDATE rr_jobs SET error = ?, updated_at = ? WHERE id = ?", (note, now_epoch(), job["id"]))
            continue
        if job["state"] != "running":
            _set_job(store, job["id"], "running")
            job["state"] = "running"
        job["params"] = _params(row)
        job["credential"] = credential["kind"]
        job["credential_email"] = credential.get("email")
        # 요청자 PAT 를 수명 때문에 건너뛰고 타깃 owner 의 것으로 돌면 그 사유를 잡 행에 남긴다(진행판의 '오류' 줄) — 좌석이
        # 누구 시야로 조회했는지 보이게 한다. 건너뛴 것이 없으면 지난 사유를 지운다.
        store.execute("UPDATE rr_jobs SET credential_email = ?, error = ? WHERE id = ?",
                      (credential.get("email"), credential_note, job["id"]))
        return job
    return None


# ---------------------------------------------------------------- 재기동 복구(plan §6.7.2 끝 문단)
def _repersist_hint(panel_id: str) -> str:
    """다시 저장하는 길 — 화면에 그 버튼이 생기기 전까지 사람이 부를 수 있는 REST 경로를 문구에 적는다(포기하는 길과 함께)."""
    return f"'다시 저장'(POST /api/panels/{panel_id}/repersist — 포기하려면 같은 경로에 ?discard=1)"


# 다시 저장 전에 재개하거나 다른 잡을 세운 사람에게 하는 말 — 그 타깃은 편성되지 않고 기다린다.
REPERSIST_FIRST = "다시 저장(또는 포기) 먼저 — 그 전에는 재개해도 이 타깃은 기다린다"


def awaits_repersist(panel: Mapping[str, Any]) -> bool:
    """패널 행 하나({status, error, has_result})가 다시 저장을 기다리는가 — `repersist_panel` 의 전제다(결과 없는 패널은 다시
    저장할 것이 없다). 등록부의 C2 셈도 이 술어를 쓴다."""
    return (panel["status"] == "error" and bool(panel["has_result"])
            and _uncharged_code(panel["error"]) == PERSIST_ERROR_CODE)


def awaiting_repersist(store: Any, target_key: str) -> list[dict]:
    """다시 저장을 기다리는 패널 — 엔진 결과가 패널에 있고(result_gz) persist_error 로 닫혔다(awaits_repersist).

    이런 패널이 남은 타깃은 새 패널을 편성하지 않는다(러너 집기·브리프 미리보기). 그 패널은 좌석을 차감 없이 pending 으로
    돌려놓았으므로 새 패널이 그 좌석을 가져가면 다시 저장이 영영 seats_moved 로 거절되고, 몇 시간짜리 결과를 버린 채 같은
    좌석을 다시 돌린다(RR-ADV-1). 좌석 하나하나를 후보에서 빼지 않고 타깃을 기다리게 한다 — 남은 좌석이 전부 묶이면
    편성기가 None 을 내 잡이 좌석이 pending 인 채 completed 로 닫힌다. 막힘은 다시 저장이나 포기(abandon_repersist)로 풀린다.
    """
    rows = store.query(
        "SELECT id, panel_no, status, error, result_gz IS NOT NULL AS has_result FROM rr_panels"
        " WHERE target_key = ? AND status = 'error' AND result_gz IS NOT NULL ORDER BY panel_no", (target_key,))
    return [{"id": r["id"], "panel_no": r["panel_no"], "error": r["error"]} for r in rows if awaits_repersist(r)]


def repersist_pending_note(waiting: Sequence[Mapping[str, Any]]) -> str:
    """다시 저장을 기다리는 타깃의 잡이 줄에서 기다리는 까닭 — 잡 행 error 와 길잡이 막힘이 같은 글을 쓴다."""
    panels = " · ".join(f"패널 {p['id']}(#{p['panel_no']}) 은 {_repersist_hint(p['id'])} 로 다시 앉힌다" for p in waiting)
    return (f"{REPERSIST_PENDING_CODE}: 이 타깃에는 엔진 결과가 다시 저장을 기다리는 패널이 있다 — {panels}."
            " 그 전에는 이 타깃에 새 패널을 편성하지 않는다(잡은 줄에서 기다린다)")


def abandon_repersist(store: Any, panel_id: str) -> dict:
    """다시 저장을 포기한다 — `POST /api/panels/{id}/repersist?discard=1` 의 본체.

    error 를 'persist_abandoned: …' 로 바꿔(앞 사유는 뒤에 남긴다) 그 타깃이 다시 편성되게 한다. 엔진 결과(result_gz)·결정문·
    대화 번호는 패널에 그대로 남고, 좌석은 이미 차감 없이 pending 이라 다음 패널에서 다시 돈다. 같은 결과로 다시 저장이
    되풀이해 실패할 때(persist_failed)의 탈출구다 — 이 길이 없으면 그 타깃은 영영 멈춘다.
    오류 — 404 E404·result_absent · 409 not_awaiting_repersist(persist_error 로 닫힌 패널이 아니다 — 이미 포기·저장했다).
    """
    row = store.query_one("SELECT status, error, result_gz IS NOT NULL AS has_result FROM rr_panels WHERE id = ?",
                          (panel_id,))
    if row is None:
        raise AppError("E404", f"패널을 찾을 수 없습니다 — {panel_id}.", 404)
    if not row["has_result"]:
        raise AppError("result_absent", "이 패널에는 저장된 엔진 결과가 없다 — 다시 저장을 기다리는 패널이 아니다.", 404)
    if row["status"] != "error" or _uncharged_code(row["error"]) != PERSIST_ERROR_CODE:
        raise AppError("not_awaiting_repersist", f"다시 저장을 기다리는 패널이 아니다 — {row['status']}"
                       + (f": {row['error']}" if row["error"] else "") + ".", 409)
    error = (f"{PERSIST_ABANDONED_CODE}: 사람이 다시 저장을 포기했다 — 엔진 결과는 패널에 남고 좌석은 다음 패널에서 다시 돈다."
             f" 앞 사유 — {row['error']}")
    store.execute("UPDATE rr_panels SET error = ? WHERE id = ? AND status = 'error'", (error, panel_id))
    _release_panel(store, panel_id, charge=False)         # 쟁점 패널이면 그 쟁점을 대기로(종전 패널 좌석은 이미 pending)
    return {"panel_id": panel_id, "status": "error", "error": error, "abandoned": True}


def _release_panel(store: Any, panel: Mapping[str, Any] | str, *, charge: bool = True) -> None:
    """결과 없이 닫힌 패널의 자리를 되돌린다 — 종전 패널은 좌석(planner.fail_panel_seats, `charge` 면 재시도 차감), 쟁점 패널은 그
    쟁점을 대기로(차감 없음 — 엔진·스트림·재기동은 쟁점 탓이 아니다, 3.7 실패 표). 쟁점 패널은 좌석 원장을 건드리지 않는다 — 같은
    대상의 검토 좌석이 running 이어도 되돌리지 않는다."""
    panel_id = panel if isinstance(panel, str) else str(panel["id"])
    row = store.query_one("SELECT kind FROM rr_panels WHERE id = ?", (panel_id,))
    if row is not None and row["kind"] == "issue":
        from app import issues  # noqa: PLC0415 — issues 는 이 모듈을 쓴다.

        issues.release_issue(store, panel_id, charge=False)
        return
    planner.fail_panel_seats(store, panel_id, reason="engine_fail", charge=charge)


def recover_running_panels(store: Any) -> dict:
    """이전 기동이 남긴 running 패널을 error('restart') 로 닫고 좌석을 차감 없이 pending 으로 되돌린다.

    재기동은 좌석 탓도 엔진 탓도 아니다. 앱만 다시 떴으면 엔진은 그 심의를 분리 태스크로 끝까지 돌리고 있다 —
    그래서 스트림을 놓은 패널(_close_panel_stream_lost)과 같이 다룬다. 종전에는 좌석 retry 를 올리고 잡을 곧바로
    queued 로 돌려, 기동 직후 첫 틱이 같은 좌석을 엔진에 다시 보냈다(같은 심의가 공유 LLM 에 겹쳐 돈다). 재배포
    세 번이면 좌석이 skipped 로 굳었다 — 벽시계가 12시간이라 패널 도중의 재기동은 드문 일이 아니다.
    엔진 결과가 이미 패널에 저장된(result_gz) running 패널은 저장 도중에 끊긴 것이다 — 엔진은 끝났으므로 다시 돌리지
    않고 'persist_error: restart' 로 닫아 다시 저장을 기다린다(WP1 R-2). 그 타깃은 다시 저장(또는 포기)하기 전까지
    편성되지 않는다(awaiting_repersist) — 같은 타깃에 줄 선 잡도 그 좌석을 가져가지 않는다.
    패널이 끊긴 잡은 멈춘다(사람이 재개하면 이어 돈다 — 결과가 저장된 패널이 있으면 다시 저장이 먼저다). 패널 사이에 있던
    잡(running 인데 도는 패널이 없다)은 겹칠 심의가 없으니 queued 로 돌린다. cancelling 은 건드리지 않는다 — 다음 편성에서
    cancelled 가 된다.
    """
    rows = store.query(
        "SELECT id, target_key, kind, conv_id, result_gz IS NOT NULL AS has_result FROM rr_panels WHERE status = 'running'"
        " ORDER BY created_at ASC")
    now = now_epoch()
    cut_targets: dict[str, list[str]] = {}
    for row in rows:
        # 결과가 저장된 쟁점 패널은 쟁점을 running 그대로 둔다 — 다시 저장(repersist)이 resolve_issue 까지 한다(3.7 실패 표).
        if not (row["has_result"] and row["kind"] == "issue"):
            _release_panel(store, row["id"], charge=False)
        # 스트림 전에 적어 둔 포털 대화(D48)는 그대로 두고 error 에도 적는다 — 그 대화를 찾아 무시하거나 닫을 수 있게.
        conv = f"포털 대화 {row['conv_id']}" if row["conv_id"] else ""
        if row["has_result"]:
            error = (f"{PERSIST_ERROR_CODE}: {RESTART_CODE} — 앱이 결과를 원장에 앉히던 중에 재기동했다. 엔진 결과는 패널에"
                     f" 저장돼 있다 — {_repersist_hint(row['id'])} 로 다시 앉힌다" + (f" ({conv})" if conv else ""))
        elif conv:
            error = f"{RESTART_CODE}: {conv} 에 그 심의가 남아 있다 — 엔진이 그 대화에 계속 쓸 수 있으니 찾아 무시하거나 닫는다"
        else:
            error = RESTART_CODE
        store.execute("UPDATE rr_panels SET status = 'error', error = ?, ended_at = ? WHERE id = ?",
                      (error, now, row["id"]))
        saved = cut_targets.setdefault(row["target_key"], [])
        if row["has_result"]:
            saved.append(row["id"])
    paused = 0
    # 패널 잡만 — 도는 검토 잡은 그 러너의 복구가 맡는다(여기서 queued 로 돌리면 선점한 셀과 어긋난다, 재설계 M2 S6).
    for job in store.query(f"SELECT id, target_key FROM rr_jobs WHERE state = 'running' AND {RUNNER_JOBS_SQL}"):
        if job["target_key"] in cut_targets:
            saved = cut_targets[job["target_key"]]
            # 결과가 저장된 패널이 있으면 '재개하면 이어 돈다' 를 말하지 않는다 — 그대로 따른 사람이 다시 저장 전에 재개해
            # 그 좌석이 새 패널로 가면 결과를 잃었다(지금은 재개해도 다시 저장 전에는 편성되지 않는다).
            tail = (" " + " ".join(f"엔진 결과가 저장된 패널 {pid} 은 {_repersist_hint(pid)} 로 다시 앉힌다." for pid in saved)
                    + f" {REPERSIST_FIRST}") if saved else " 재개하면 이어 돈다"
            # 사유는 잡의 error 에 적는다(pause_reason 은 CHECK 로 세 값만 받는다).
            _set_job(store, job["id"], "paused", by=f"code:{RESTART_CODE}",
                     error=f"{RESTART_CODE}: 앱이 재기동해 도는 패널을 닫았다 — 엔진 쪽 심의는 계속 돌 수 있다."
                           " 잡을 멈췄다(좌석 재시도는 차감하지 않았다)." + tail)
            paused += 1
        else:
            _set_job(store, job["id"], "queued")
    return {"recovered": len(rows), "paused": paused}


# ---------------------------------------------------------------- 패널 1건(plan §6.7.2 1~12단계)
def seat_contract_rev() -> str:
    """seat-contract.v1.json 의 sha256[:12](D6 model_json.seat_contract_rev, plan §6.7.2 1단계)."""
    from app.common import sha256_hex  # noqa: PLC0415

    return sha256_hex(taxonomy.asset_path("seat-contract").read_bytes())[:12]


def snapshot_model(engine: Any, *, llm: str | None = None) -> dict:
    """엔진이 health() 를 노출하면 D6 model_json 스냅샷을 만든다(없으면 captured='unavailable').

    plan §6.7.2 1단계의 출처 스냅샷이다 — 정상이면 `captured='health_snapshot'`, 불통·미노출이면
    `captured='unavailable'`·`model='unknown'` 이고 어느 경우에도 예외를 올리지 않는다.
    `llm='claude'`(Claude 길 X-2)면 판단 LLM 이 외부 응답자다 — `llm: external` 을 달고 근거 예산(`evid_budget`)을 /health 의
    `external_llm.evid_budget`(외부 창에서 유도한 것 — `engine_client.external_health`)으로 둔다. 그 길을 열지 않은 박스 · 불통이면
    None 이라 브리프가 바닥 프로파일로 떨어진다. GLM 은 종전 그대로다.
    """
    external = {"llm": ENGINE_EXTERNAL} if llm == LLM_CLAUDE else {}
    probe = getattr(engine, "health", None)
    if not callable(probe):
        return {"runtime": "agent-server", "captured": "unavailable", "model": "unknown",
                "seat_contract_rev": seat_contract_rev(), **external}
    try:
        info = dict(probe() or {})
    except Exception as exc:  # noqa: BLE001 — /health 불통은 비치명이고 패널은 그대로 진행한다.
        log.warning("엔진 health 조회 실패(비치명): %s", exc)
        return {"runtime": "agent-server", "captured": "unavailable", "model": "unknown",
                "seat_contract_rev": seat_contract_rev(), **external}
    out = {
        "runtime": "agent-server",
        "provider": info.get("provider") or "vllm",
        "model": info.get("model") or "unknown",
        "endpoint_host": info.get("endpoint_host"),
        "captured": "health_snapshot",
        "engine_rev": info.get("engine_rev") or info.get("version"),
        "vllm": info.get("vllm"),
        "sampling": info.get("sampling"),
        # chair_rev 는 엔진(deliberation.py) 상수의 해시다 — 엔진 /health 가 실어 보내면 그대로 적고,
        # 안 보내면 null 이다(앱에는 원문이 없어 스스로 계산하지 못한다, §6.7.2 1단계).
        "chair_rev": info.get("chair_rev"),
        "seat_contract_rev": seat_contract_rev(),
        # 엔진이 제 모델 창에서 유도한 근거 예산(자) — 러너가 브리프 크기를 정한다(`brief.web_profile`). 옛 엔진은 null.
        "evid_budget": info.get("evid_budget"),
    }
    if external:
        block = info.get("external_llm") if isinstance(info.get("external_llm"), Mapping) else {}
        budget = block.get("evid_budget")
        out.update(external, evid_budget=budget if isinstance(budget, int) and not isinstance(budget, bool) else None)
    return out


def _quality(
    panel: Mapping[str, Any],
    attribution: Mapping[str, Any],
    extracted: Mapping[str, Any],
    *,
    credential: str,
    call_path: str,
    new_clusters: int,
    llm_calls: int,
    cap: int,
    parsed: bool,
    pat_degraded: bool,
) -> dict:
    """rr_panels.quality_json(plan §6.5.5) — 비율·분포·flags."""
    seat_keys = [s["key"] for s in panel["seats"]]
    seats = extracted.get("seats") or []
    by_key = {s.get("agent_key"): s for s in seats}
    attributable = [k for k in seat_keys if (attribution["seats"].get(k) or {}).get("used_tool") is not None]
    used = [k for k in attributable if attribution["seats"][k]["used_tool"]]
    cited_ir = [k for k in seat_keys if (by_key.get(k) or {}).get("cited_ir")]
    findings_total = int(extracted.get("findings_total") or 0)
    rejects = int(extracted.get("adversary_rejects") or 0)

    tool_use_rate = (len(used) / len(attributable)) if attributable else None
    ir_cite_rate = (len(cited_ir) / len(seat_keys)) if seat_keys else None
    reject_rate = (rejects / findings_total) if findings_total else 0.0

    flags: list[str] = []
    if tool_use_rate is not None and tool_use_rate < QUALITY_TOOL_USE_MIN:
        flags.append("low_tool_use")
    if ir_cite_rate is not None and ir_cite_rate < QUALITY_IR_CITE_MIN:
        flags.append("low_ir_cite")
    if rejects == 0:
        flags.append("adversary_silent")
    if reject_rate > QUALITY_ADVERSARY_OVERREJECT:
        flags.append("adversary_overreject")
    if extracted.get("header_mismatch"):
        flags.append("header_mismatch")
    if not parsed:
        flags.append("spec_parse_failed")
    if llm_calls > cap:
        flags.append("over_budget")
    if attribution["extra_seats"]:
        flags.append("rescreen_seats")
    if extracted.get("coverage_mismatch"):
        flags.append("coverage_mismatch")

    return {
        "tool_use_rate": tool_use_rate,
        "ir_cite_rate": ir_cite_rate,
        "grade_dist": extracted.get("grade_dist") or {},
        "adversary_reject_rate": reject_rate,
        "attribution_rate": attribution["attribution_rate"],
        "new_clusters": new_clusters,
        "llm_calls_observed": llm_calls,
        "pat_degraded": pat_degraded,
        "credential": credential,
        "call_path": call_path,
        "extra_seats": list(attribution["extra_seats"]),
        "flags": flags,
    }


def _finish_job(store: Any, job: Mapping[str, Any], settings: Any) -> dict:
    """Tier 범위 소진 — 잡을 completed 로 닫고, close_level 이 C3 이면 Tier B 뒤에 Tier C 를 자동 큐잉한다. 쟁점 잡(M3 S3-5)은
    대기 쟁점이 바닥난 것이고 사슬이 종합 잡을 잇는다."""
    _set_job(store, job["id"], "completed")
    if job.get("mode") == "issues":
        from app import chain  # noqa: PLC0415 — chain 은 종합·쟁점을 거쳐 무겁다.

        follow = chain.safe(chain.on_issues_closed, store, job) or {}
        return {"job_state": "completed", "next_job": follow.get("job_id") if follow.get("created") else None}
    target = store.query_one("SELECT owner_sub, close_level FROM rr_targets WHERE target_key = ?", (job["target_key"],))
    close_level = (target["close_level"] if target and target["close_level"] else settings.risk_default_close_level)
    if job["tier"] == "B" and close_level == "C3":
        try:
            # 자격은 B 잡과 같은 사람 순서다(요청자 → 타깃 owner) — 서비스 계정으로 내려가지 않으므로(U-3) owner 만 넘기면
            # 요청자 자격으로 돈 B 잡의 후속이 멈춘다.
            follow = create_job(
                store, job["target_key"], "C", owner_sub=job["owner_sub"],
                modifiers=(job.get("params") or {}).get("modifiers"),
                user_memo=(job.get("params") or {}).get("user_memo"),
                consent=True, settings=settings, consent_source="close_level",
                requester_sub=(job.get("params") or {}).get("requester"),
            )
        except AppError as exc:
            if exc.code not in FOLLOW_UP_REFUSALS:
                raise
            # 문지기가 자동 후속을 막았다 — 끝난 잡은 completed 그대로 두고 까닭을 그 잡에 적는다(조용히 사라지지 않게).
            store.execute("UPDATE rr_jobs SET error = ? WHERE id = ?",
                          (f"{exc.code}: C3 자동 후속 Tier C 를 세우지 않았다 — {exc.message}", job["id"]))
            return {"job_state": "completed", "next_job": None, "next_job_refused": exc.code}
        return {"job_state": "completed", "next_job": follow["job_id"]}
    return {"job_state": "completed", "next_job": None}


# C3 자동 후속을 막는 문지기의 코드 — 이것만 받아 잡을 completed 로 닫는다(그 밖의 실패는 종전대로 올린다). 사람 자격이 없는
# 것(pat_unavailable)도 그렇다 — 서비스 계정으로 내려가지 않으므로(U-3) 끝난 B 잡을 실패로 바꾸지 않고 까닭만 적는다.
FOLLOW_UP_REFUSALS: tuple[str, ...] = ("flow_mismatch", "review_job_running", "pat_unavailable")


def _diminishing(store: Any, target_key: str) -> bool:
    """최근 3패널이 각각 신규 클러스터 <1 이면 수확 체감(호출자는 C1 충족까지 확인한다)."""
    rows = store.query(
        "SELECT quality_json FROM rr_panels WHERE target_key = ? AND status = 'done' AND kind = 'coverage'"
        " ORDER BY panel_no DESC LIMIT ?",
        (target_key, DIMINISHING_WINDOW),
    )
    if len(rows) < DIMINISHING_WINDOW:
        return False
    for row in rows:
        try:
            quality = json.loads(row["quality_json"] or "{}")
        except ValueError:
            return False
        if int(quality.get("new_clusters") or 0) >= 1:
            return False
    return True


def _uncharged_code(error: Any) -> str | None:
    """패널 error 문구가 좌석 재시도·연속 실패에 세지 않는 중단(스트림을 놓았다 · 재기동 · 결정문 없음 · 시작 못 함)이면
    그 코드(UNCHARGED_CODES), 아니면 None."""
    code = str(error or "").split(":", 1)[0].strip()
    return code if code in UNCHARGED_CODES else None


def _error_streak(store: Any, target_key: str) -> int:
    """가장 최근부터 연속으로 error 로 닫힌 패널 수(ENGINE_FAIL_STREAK 에서 멈춘다).

    앱이 스트림을 놓았거나 재기동이 끊었거나 의장만 결정문을 못 냈거나 엔진 자리가 없어 시작도 못 한 패널은 세지
    않고 건너뛴다 — 그 패널 때문에 진짜 실패 두 번이 세 번으로 세져 잡이 죽으면 안 된다.
    """
    streak = 0
    for row in store.query(
        "SELECT status, error FROM rr_panels WHERE target_key = ? ORDER BY panel_no DESC", (target_key,)
    ):
        if row["status"] != "error":
            break
        if _uncharged_code(row["error"]):
            continue
        streak += 1
        if streak >= ENGINE_FAIL_STREAK:
            break
    return streak


def missing_interfaces(narrative_mod: Any | None = None, registry_mod: Any | None = None) -> list[str]:
    """러너 정본 경로가 부르는 모듈 함수 중 실재하지 않는 것의 이름(정상이면 빈 목록).

    대역을 주입하지 않은 운영 배선에서도 이 검사가 먼저 돌아 '패널만 running 에 고착' 을 막는다.
    """
    if narrative_mod is None:
        from app import narrative as narrative_mod  # noqa: PLC0415
    if registry_mod is None:
        from app import registry as registry_mod  # noqa: PLC0415
    out = [f"narrative.{n}" for n in REQUIRED_NARRATIVE if not callable(getattr(narrative_mod, n, None))]
    out += [f"registry.{n}" for n in REQUIRED_REGISTRY if not callable(getattr(registry_mod, n, None))]
    return out


def run_panel(
    store: Any,
    settings: Any,
    engine: PanelEngine,
    job: Mapping[str, Any],
    *,
    narrative_mod: Any | None = None,
    registry_mod: Any | None = None,
    stop: threading.Event | None = None,
) -> dict:
    """패널 1건을 편성·실행·회수한다(plan §6.7.2). 반환 {panel_id|None, status, ...}."""
    params = job.get("params") or {}
    missing = missing_interfaces(narrative_mod, registry_mod)
    if missing:
        # 배선이 덜 된 채 좌석을 앉히면 패널이 running 에 고착돼 그 타깃이 영영 편성되지 않는다.
        log.error("러너 인터페이스 결손 %s — 잡 %s 를 집지 않는다", missing, job.get("id"))
        _set_job(store, job["id"], "failed", error="missing_interface: " + ",".join(missing))
        if job.get("mode") == "issues":
            _issue_job_failed(store, job, "job_failed")
        return {"panel_id": None, "status": "missing_interface", "missing": missing}

    issue_job = job.get("mode") == "issues"
    # 판단 LLM(Claude 길 X-2) — 사슬이 물려준 claude 쟁점 잡이면 패널이 외부 응답자로 돈다(좌석 도구 없는 evidence_only — 엔진이 강제)
    llm = job_llm(params)
    if issue_job:
        # 쟁점 잡(M3 S3-7) — 대기 쟁점 하나의 패널. 좌석 원장을 쓰지 않는다(편성 전후 rr_coverage 그대로).
        from app import issues  # noqa: PLC0415 — issues 는 이 모듈을 쓴다.

        panel = issues.plan_issue_panel(store, job["target_key"], job=job, settings=settings)
    else:
        panel = planner.plan_next_panel(
            store, job["target_key"], job["tier"], modifiers=params.get("modifiers"), settings=settings
        )
    if panel is None:
        return {"panel_id": None, "status": "no_panel", **_finish_job(store, job, settings)}

    if issue_job:
        issues.start_issue_panel(store, panel["id"])
    else:
        planner.start_panel_seats(store, panel["id"])
    try:
        model_json = snapshot_model(engine, llm=llm)
        # 브리프 크기는 엔진이 이 패널을 시작할 때 알려 준 근거 예산에서 정한다(WP1 S9) — 패널마다 다시 읽으므로 엔진 창이
        # 바뀌거나 창을 아직 못 물어본 가정값이 바로잡히면 다음 패널부터 따라간다. claude 잡은 외부 창의 예산이다(GLM 1M 창으로 지은
        # 브리프가 Claude 로 가지 않게 — snapshot_model 이 /health 의 external_llm.evid_budget 을 둔다).
        profile = brief.web_profile(model_json.get("evid_budget"))
        model_json["brief_profile"] = {"name": profile.name, "budget": profile.budget}
        target = store.query_one("SELECT kind, ref_id FROM rr_targets WHERE target_key = ?", (job["target_key"],))
        loss: dict = {}
        if target is not None and target["kind"] == "diff":
            withheld = diff_ref_withheld(
                store, target["ref_id"], job.get("credential"),
                params.get("requester") if job.get("credential") == "requester" else job.get("owner_sub"))
            if withheld and withheld.get("shipped"):
                # 표식은 싣되 좌석이 잡 자격의 사람으로 보일지 확인하지 못했다 — 좌석의 not_visible 을 읽을 실마리로 남긴다(RV-3).
                loss["gateway_unverified"] = {k: v for k, v in withheld.items() if k != "shipped"}
            elif withheld:
                # 질문에 diff_id 표식이 없는 까닭 — 변경 목록(E2)은 그대로 실리지만 '변경 전체 보기' 가 왜 없었는지를 패널에 남긴다.
                loss["diff_ref_withheld"] = withheld
        diff_ref = bool(target is not None and target["kind"] == "diff" and "diff_ref_withheld" not in loss)
        store.execute("UPDATE rr_panels SET model_json = ? WHERE id = ?", (canonical_json(model_json), panel["id"]))
        delib_opts = build_delib_opts(
            # 메모 없는 잡은 None 이 아니라 빈 문자열로 넘긴다 — None 은 '잡이 없는 길' 이라 브리프가 그 타깃의
            # 최근 잡 메모를 찾아 싣는다(같은 타깃에 메모를 단 잡이 또 있으면 그 메모가 이 패널에 실린다).
            store, settings, panel, user_memo=params.get("user_memo") or "", narrative_mod=narrative_mod, loss=loss,
            profile=profile, diff_ref=diff_ref,
        )
        if llm is not None:
            # 외부 응답자 심의 — 엔진은 동의 표지가 JSON true 여야 과제를 만든다(사람의 동의는 검토 잡을 만들 때 받아 잡에 물려 왔다)
            delib_opts = {**delib_opts, "llm": ENGINE_EXTERNAL, "consent_external": True}
        # 브리프는 시변 조립물이라 이 패널이 실제로 받은 전문을 동결한다(§5.6.1).
        frozen = {**freeze_brief(store, panel, delib_opts["evidence"]), **loss,
                  # 검색어를 실어 보냈는가 — 엔진 상태줄이 '질문으로 찾았다' 고 하면 중간(옛 포털)이 키를 버린 것이다.
                  "knowledge_query_sent": bool(delib_opts.get("knowledge_query"))}
    except Exception as exc:  # noqa: BLE001 — 브리프 조립 실패도 좌석을 pending 으로 되돌리고 닫는다.
        log.exception("패널 %s 브리프 조립 실패", panel["id"])
        return _close_panel_brief_failed(store, panel, job, exc)

    result: Mapping[str, Any] | None = None
    error: str | None = None
    # 러너 자격 (b)(c) 사용자 PAT 를 쓰려면 그 사람의 sub 가 엔진까지 가야 한다(plan §6.7 3단계). 잡이 요청자
    # 자격으로 집혔으면 요청자를 넘긴다 — 늘 타깃 owner 를 넘기던 동안 잡 행은 '요청자 자격' 이라 적고 엔진은
    # owner(없으면 서비스) PAT 로 돌았다.
    # claude 잡은 반출에 동의한 사람의 PAT 로만 돈다 — 그 사람의 워크플로만 과제를 집는다(대상 소유자 · 서비스로 내려가지 않는다)
    credential_sub = external_consenter(params) or (
        params.get("requester") if job.get("credential") == "requester" else job.get("owner_sub"))
    optional: dict = {}
    run_params = _run_parameters(engine)
    if "on_progress" in run_params:
        optional["on_progress"] = _progress_writer(store, job, panel)
        optional["on_progress"]({})                 # 첫 줄이 오기 전부터 '시작했고 아직 신호가 없다' 가 보인다
    # 포털 429(동시 실행 자리 없음)는 간격을 두고 다시 묻되 총 예산까지만 기다린다. 종전에는 30초 × 10회(5분)였고
    # 다 쓰면 엔진 실패로 닫아 좌석을 차감했다 — 심의가 SSE 자리를 몇 시간씩 쥐는 지금은 5분 넘게 자리가 안 나는
    # 일이 드물지 않아, 한 번도 앉아 보지 못한 좌석이 skipped 로 굳고 잡이 engine_fail_streak 로 죽었다.
    busy_wait_s, busy_budget_s = config.engine_busy_wait_s(settings), config.engine_busy_max_wait_s(settings)
    busy_n, busy_until = 0, 0.0
    # 사람이 이 잡을 취소·정지했는가 — 스트림을 읽는 엔진과 아래 대기 루프가 같은 물음을 쓴다.
    should_stop = _stop_reader(store, job)
    if "should_stop" in run_params:
        optional["should_stop"] = should_stop
    if "on_conversation" in run_params:
        # 포털 대화가 생기면 스트림 전에 패널에 적는다 — 종전에는 패널 끝 · 잡힌 오류에서만 적어, 스트림 도중에 앱이 죽으면(SIGKILL)
        # 패널은 conv_id 없이 error('restart') 로 남고 엔진이 계속 쓰는 그 대화는 고아가 됐다(M3 단계 D 리허설, D48).
        optional["on_conversation"] = lambda conv_id: store.execute(
            "UPDATE rr_panels SET conv_id = ? WHERE id = ?", (conv_id, panel["id"]))
    while True:
        try:
            result = engine.run(delib_opts, owner_sub=credential_sub, **optional)
            break
        except EngineBusy as busy:
            busy_n += 1
            if busy_n == 1:
                busy_until = time.monotonic() + busy_budget_s
            conv_id = busy.conversation[0] if busy.conversation else None
            why = should_stop()
            if why:
                # 자리를 기다리는 중의 취소·정지 — 예산(기본 한 시간)을 다 기다린 뒤에 듣지 않는다. 잡은 사람이
                # 이미 옮겼으므로 건드리지 않는다.
                return _close_panel_unstarted(
                    store, panel, job, "cancelled", conv_id=conv_id, pause=False,
                    error=f"cancelled: {why} — 엔진 자리를 기다리던 패널을 닫았다(심의는 시작되지 않았다)")
            left = busy_until - time.monotonic()
            if left <= 0:
                return _close_panel_unstarted(
                    store, panel, job, "engine_busy", conv_id=conv_id, pause=True,
                    error=f"engine_busy: 포털 동시 실행 자리(MAX_CONCURRENT_CHATS)를 {busy_budget_s}초 기다렸지만"
                          " 나지 않았다(HWAXRISK_ENGINE_BUSY_MAX_WAIT_S)")
            if "conversation" in run_params:
                optional["conversation"] = busy.conversation  # 앞 시도가 만든 대화를 다시 쓴다(시도마다 만들지 않는다)
            if "on_progress" in optional:
                # 기다리는 동안 패널은 running 으로만 보인다 — 도는 것과 자리를 기다리는 것이 진행판에서 갈리게 한다.
                optional["on_progress"]({"last_step": f"엔진 자리 대기 {busy_n}회째"}, force=True)
            # 남은 예산보다 길게 자지 않는다 — 마지막 물음이 예산의 끝에 온다.
            if stop is None:
                time.sleep(min(busy_wait_s, left))
            elif stop.wait(min(busy_wait_s, left)):
                return _close_panel_unstarted(
                    store, panel, job, "stopped", conv_id=conv_id, pause=False,
                    error="stopped: 엔진 자리를 기다리던 중에 앱이 내려갔다 — 심의는 시작되지 않았다"
                          "(좌석 재시도는 차감하지 않았다)")
        except PatUnavailable as exc:
            if issue_job:
                return _hold_issue_job_for_credential(store, panel, job, exc)
            # 자격 문제는 폴백·재시도 대상이 아니다 — 잡을 멈추고 좌석을 되돌린다(plan §6.7.1).
            out = _close_panel_error(store, panel, job, f"pat_unavailable: {exc}", settings)
            _set_job(store, job["id"], "failed", error="pat_unavailable")
            return {**out, "error": "pat_unavailable"}
        except EngineStreamLost as exc:
            return _close_panel_stream_lost(store, panel, job, exc)
        except EngineNoDecision as exc:
            return _close_panel_no_decision(store, panel, job, exc)
        except EngineRejected as exc:
            # 외부 응답자 길이 닫혔거나 동의 · 신원 칸이 엔진에 닿지 않았다(collect_stream — Claude 길 X-2) — 심의는 시작도 안 했다.
            # 설정 문제라 같은 패널을 다시 내도 같다 — 쟁점 잡을 설정 보류로 멈춘다(차감 없음).
            if issue_job and exc.code in review_ops.EXTERNAL_CONFIG_CODES:
                return _hold_issue_job(store, panel, job, EXTERNAL_CONFIG_HOLD, str(exc))
            error = f"engine_error: {exc}"
            break
        except EngineError as exc:
            error = f"engine_error: {exc}"
            break
        except Exception as exc:  # noqa: BLE001 — 어떤 예외든 패널만 error 로 닫고 러너는 계속 돈다.
            log.exception("패널 %s 엔진 호출 실패", panel["id"])
            error = f"{type(exc).__name__}: {exc}"
            break

    if result is None:
        return _close_panel_error(store, panel, job, error or "engine_error", settings)
    # 엔진 결과를 원장에 앉히기 전에 패널에 먼저 적는다 — 저장이 터져도 몇 시간짜리 결과가 메모리와 함께 사라지지 않는다.
    saved = save_panel_result(store, panel, job, result, frozen=frozen, model_json=model_json)
    try:
        return _complete_panel(
            store, settings, panel, job, result, model_json,
            narrative_mod=narrative_mod, registry_mod=registry_mod, engine=engine, frozen_brief=frozen,
        )
    except Exception as exc:  # noqa: BLE001 — 저장 실패는 패널만 persist_error 로 닫고 러너는 계속 돈다.
        log.exception("패널 %s 저장 실패", panel["id"])
        return _close_panel_persist_error(store, panel, job, exc, result_saved=saved, result=result)


def save_panel_result(store: Any, panel: Mapping[str, Any], job: Mapping[str, Any], result: Mapping[str, Any], *,
                      frozen: Mapping[str, Any] | None = None, model_json: Mapping[str, Any] | None = None) -> bool:
    """엔진이 돌려준 결과 원문을 패널(rr_panels.result_gz)에 적는다 — 자기 트랜잭션이다. 적었으면 True.

    원장 저장(_complete_panel)이 실패해도 이 원문으로 다시 앉힌다(repersist_panel). 그때 처음 저장과 같은 길을 가려면
    러너의 지역 값이던 것 — 잡 id·자격, 브리프 동결의 손실 기록(frozen), 시작 때의 모델 스냅샷 — 도 같이 둔다(P-05).
    적지 못해도 패널은 계속 간다(로그를 남기고 False — 저장이 실패하면 잡 문구가 포털 대화를 가리킨다).
    """
    payload = {"v": 1, "job_id": job.get("id"), "job_credential": job.get("credential"), **dict(result),
               "frozen": dict(frozen or {}), "model_json": dict(model_json or {})}
    try:
        text = canonical_json(payload)
        with store.tx():
            # 폐기된 과제의 결과 원문은 패널에도 남기지 않는다(review1 L6 — 폐기가 비운 칸을 늦은 쓰기가 다시 채운다).
            if _target_purged(store, panel["target_key"]):
                return False
            store.execute(
                "UPDATE rr_panels SET result_gz = ?, result_hash = ?, result_saved_at = ? WHERE id = ?",
                (gzip.compress(text.encode("utf-8")), sha256_hex(text)[:12], now_epoch(), panel["id"]))
        return True
    except Exception:  # noqa: BLE001 — 위 설명대로다.
        log.exception("패널 %s 엔진 결과를 패널에 적지 못했다", panel["id"])
        return False


def load_panel_result(store: Any, panel_id: str) -> dict | None:
    """save_panel_result 가 적은 원문(없으면 None)."""
    row = store.query_one("SELECT result_gz FROM rr_panels WHERE id = ?", (panel_id,))
    if row is None or row["result_gz"] is None:
        return None
    return json.loads(gzip.decompress(row["result_gz"]).decode("utf-8"))


def _pause_running_job(store: Any, job: Mapping[str, Any], code: str, error: str) -> None:
    """잡이 아직 running 이면 멈춘다 — 그 사이 사람이 취소했으면(cancelling) 그 전이를 덮지 않는다."""
    row = store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job["id"],))
    if row is not None and row["state"] == "running":
        _set_job(store, job["id"], "paused", by=f"code:{code}", error=error)


def _close_panel_persist_error(store: Any, panel: Mapping[str, Any], job: Mapping[str, Any], exc: Exception, *,
                               result_saved: bool, result: Mapping[str, Any]) -> dict:
    """엔진 결과를 원장에 앉히지 못한 패널을 닫는다 — 좌석은 차감 없이 pending, 잡은 멈춘다(WP1 R-2).

    저장은 한 트랜잭션이라 실패하면 반쪽 없이 물러나 있다. 패널에는 결정문·대화·보고서 번호를 적어 두고, 엔진 결과
    원문(result_gz)이 있으면 원인을 고친 뒤 다시 저장한다. 커밋이 끝난 뒤의 예외면(패널이 이미 done) 패널과 좌석을
    건드리지 않는다 — 좌석은 이미 종결이라 뒤집으면 다시 저장도 영영 409 다(P-18). 그때는 잡만 멈춘다.
    """
    why = f"{type(exc).__name__}: {exc}"
    row = store.query_one("SELECT status FROM rr_panels WHERE id = ?", (panel["id"],))
    if row is not None and row["status"] == "done":
        log.error("패널 %s 는 저장됐지만 그 뒤 처리에서 멈췄다 — %s", panel["id"], why)
        _pause_running_job(store, job, PERSIST_ERROR_CODE,
                           f"{PERSIST_ERROR_CODE}: 패널 {panel['id']} 은 원장에 저장됐지만 그 뒤 처리에서 멈췄다({why})."
                           " 잡을 멈췄다 — 재개하면 이어 돈다")
        return {"panel_id": panel["id"], "status": "done", "error": f"{PERSIST_ERROR_CODE}: {why}"}
    if panel.get("kind") != "issue":       # 쟁점 패널의 쟁점은 running 그대로 — 다시 저장이 resolve_issue 까지 한다
        planner.fail_panel_seats(store, panel["id"], reason="engine_fail", charge=False)
    error = f"{PERSIST_ERROR_CODE}: {why}"
    store.execute(
        "UPDATE rr_panels SET status = 'error', error = ?, decision_text = ?, conv_id = ?, report_id = ?,"
        " ended_at = ? WHERE id = ?",
        (error, str(result.get("decision_text") or "") or None, result.get("conv_id"), result.get("report_id"),
         now_epoch(), panel["id"]))
    if result_saved:
        kept = f"엔진 결과는 패널에 저장돼 있다 — 원인을 고친 뒤 {_repersist_hint(panel['id'])} 로 다시 앉힌다"
        then = f". {REPERSIST_FIRST}"
    else:
        kept = f"엔진 결과를 패널에 저장하지 못했다 — 포털 대화 {result.get('conv_id')} 에 발언이 남아 있다"
        then = ""
    _pause_running_job(store, job, PERSIST_ERROR_CODE,
                       f"{PERSIST_ERROR_CODE}: 패널 결과를 원장에 앉히지 못했다({why}). {kept}."
                       " 잡을 멈췄다(좌석 재시도는 차감하지 않았다)" + then)
    return {"panel_id": panel["id"], "status": "error", "error": error}


def repersist_panel(store: Any, settings: Any, panel_id: str, *, narrative_mod: Any | None = None,
                    registry_mod: Any | None = None) -> dict:
    """persist_error 로 닫힌 패널을 저장된 엔진 결과로 다시 앉힌다 — `POST /api/panels/{id}/repersist` 의 본체.

    처음 저장과 같은 길(_complete_panel — 귀속·원장·등록부·품질)을 가되 셋이 다르다(P-05). 좌석 재점유와 저장을 바깥
    트랜잭션 하나로 묶어, 또 실패하면 재점유까지 물러난다(422 persist_failed — 좌석이 running 에 굳지 않는다). 잡 상태는
    건드리지 않는다(panels_done 만 올린다 — 멈춘 잡이 되살아나거나 도는 패널이 '사용자 일시정지' 로 끊기지 않는다).
    엔진에 모델을 다시 묻지 않는다(며칠 뒤의 모델을 '도중 변경' 으로 적지 않는다).
    오류 — 404 E404(패널 없음)·result_absent(저장된 결과 없음) · 409 not_error · target_busy(그 타깃에 도는 패널) ·
    seats_moved({moved:[{agent_key, status, panel_id}]}) · 422 persist_failed.
    """
    row = store.query_one(
        "SELECT id, target_key, owner_sub, panel_no, tier, seats_json, budget_json, status, kind, issue_id,"
        " result_gz IS NOT NULL AS has_result FROM rr_panels WHERE id = ?", (panel_id,))
    if row is None:
        raise AppError("E404", f"패널을 찾을 수 없습니다 — {panel_id}.", 404)
    if row["status"] != "error":
        raise AppError("not_error", f"패널이 error 가 아니다 — {row['status']}.", 409)
    if not row["has_result"]:
        raise AppError("result_absent", "이 패널에는 저장된 엔진 결과가 없다 — 다시 저장할 것이 없다.", 404)
    busy = store.query_one("SELECT id FROM rr_panels WHERE target_key = ? AND status = 'running' LIMIT 1",
                           (row["target_key"],))
    if busy is not None:
        raise AppError("target_busy", f"이 타깃에 도는 패널({busy['id']})이 있다 — 끝난 뒤 다시 저장한다.", 409)
    stored = load_panel_result(store, panel_id) or {}
    try:
        budget = json.loads(row["budget_json"] or "{}")
    except ValueError:
        budget = {}
    panel = {"id": row["id"], "target_key": row["target_key"], "owner_sub": row["owner_sub"],
             "panel_no": row["panel_no"], "tier": row["tier"],
             "seats": [s for s in json.loads(row["seats_json"] or "[]") if isinstance(s, dict)],
             "tools": list((budget or {}).get("tools_planned") or []), "kind": row["kind"], "issue_id": row["issue_id"]}
    job_row = store.query_one("SELECT id, target_key, owner_sub, tier, params_json, COALESCE(mode, 'panels') AS mode"
                              " FROM rr_jobs WHERE id = ?", (stored.get("job_id"),))
    job = {**(dict(job_row) if job_row is not None else {"id": stored.get("job_id")}),
           "credential": stored.get("job_credential")}
    result = {k: v for k, v in stored.items() if k not in ("v", "job_id", "job_credential", "frozen", "model_json")}
    try:
        with store.tx():
            # 쟁점 패널은 좌석 원장을 쓰지 않는다 — 되찾을 좌석이 없다(쟁점은 running 그대로 기다렸다).
            reclaimed = (planner.reclaim_panel_seats(store, panel_id) if row["kind"] != "issue"
                         else {"reclaimed": [], "moved": []})
            if reclaimed["moved"]:
                raise AppError("seats_moved", "좌석이 이미 다른 데 가 있다 — 이 패널의 결과로 다시 앉히지 않는다"
                               " (엔진 결과는 패널에 그대로 남는다).", 409, detail={"moved": reclaimed["moved"]})
            out = _complete_panel(store, settings, panel, job, result, dict(stored.get("model_json") or {}),
                                  narrative_mod=narrative_mod, registry_mod=registry_mod, engine=None,
                                  frozen_brief=stored.get("frozen") or None, touch_job=False)
            store.execute("UPDATE rr_panels SET error = NULL WHERE id = ?", (panel_id,))
    except AppError as exc:
        if exc.code == "seats_moved":
            raise
        raise AppError("persist_failed", f"다시 저장하지 못했다 — {exc.code}: {exc.message}", 422) from exc
    except Exception as exc:  # noqa: BLE001 — 무엇이 터졌든 바깥 트랜잭션이 재점유까지 물렸다.
        log.exception("패널 %s 다시 저장 실패", panel_id)
        raise AppError("persist_failed", f"다시 저장하지 못했다 — {type(exc).__name__}: {exc}", 422) from exc
    findings = store.query_one("SELECT COUNT(*) AS n FROM rr_findings WHERE panel_id = ?"
                               # 카드 대조 거름 그대로(M3 S3-4) — 패널 범위·패널 브리프의 자리라 cells 대상에서 돌지 않거나 카드 finding 은 panel_id 가 없어 안 걸린다
                               " AND COALESCE(source_kind, '') <> 'card_review'", (panel_id,))
    return {**out, "findings_n": int(findings["n"] or 0)}


def _close_panel_error(store: Any, panel: Mapping[str, Any], job: Mapping[str, Any], error: str, settings: Any) -> dict:
    _release_panel(store, panel)
    now = now_epoch()
    store.execute(
        "UPDATE rr_panels SET status = 'error', error = ?, retry = retry + 1, ended_at = ? WHERE id = ?",
        (error, now, panel["id"]),
    )
    if _error_streak(store, panel["target_key"]) >= ENGINE_FAIL_STREAK:
        _set_job(store, job["id"], "failed", error="engine_fail_streak")
        if job.get("mode") == "issues":
            # 쟁점 잡이 연속 오류로 실패하면 남은 대기 쟁점은 untried_cap(engine_fail) — 지우지 않는다(3.7 실패 표).
            _issue_job_failed(store, job, "engine_fail")
    return {"panel_id": panel["id"], "status": "error", "error": error}


def _issue_job_failed(store: Any, job: Mapping[str, Any], reason: str) -> None:
    """정말로 실패로 끝난 쟁점 잡 — 남은 대기 쟁점을 `untried_cap(reason)` 로 놓아 미토의로 보이게 하고(연속 오류는 engine_fail, 그
    밖은 job_failed — review1 M1), 사슬은 종합을 잇는다(P-08 ② — 코드 조립 판과 미토의 잔여가 남는다)."""
    from app import chain, issues  # noqa: PLC0415 — issues 는 이 모듈을 쓴다.

    issues.untry_queued(store, job["target_key"], reason)
    chain.safe(chain.on_issues_closed, store, job)


def _hold_issue_job_for_credential(store: Any, panel: Mapping[str, Any], job: Mapping[str, Any], exc: Exception) -> dict:
    """쟁점 잡의 자격 실패(PatUnavailable — 포털 401 따위)는 잡을 보류 credential 로 멈춘다(검토 잡과 같다, review1 M1). 패널은
    시작하지 못한 것처럼 닫고(차감 없음 · 연속 오류에 세지 않는다) 쟁점은 대기로 돌린다 — 멈춘 잡이 살아 있어 사슬은 종합으로 넘어가지
    않는다. 사람이 포털에서 PAT 를 등록하고 재개하면 이어 돈다(길잡이는 pat_unavailable 막힘과 등록 방법을 말한다)."""
    _release_panel(store, panel, charge=False)
    store.execute("UPDATE rr_panels SET status = 'error', error = ?, ended_at = ? WHERE id = ?",
                  (f"{CREDENTIAL_HOLD_CODE}: 쓸 수 있는 사용자 PAT 가 없어 쟁점 패널을 시작하지 못했다 — {exc}", now_epoch(),
                   panel["id"]))
    row = store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job["id"],))
    if row is not None and row["state"] == "running":
        _set_job(store, job["id"], "paused", by="code:credential", error=f"pat_unavailable: {exc}",
                 hold={"code": "credential", "until": None})
    return {"panel_id": panel["id"], "status": "paused", "error": "pat_unavailable"}


def _hold_issue_job(store: Any, panel: Mapping[str, Any], job: Mapping[str, Any], hold_code: str, why: str) -> dict:
    """쟁점 잡을 코드 보류로 멈춘다(Claude 길 X-2 — external_config) — 자격 보류와 같은 길이다: 패널은 시작하지 못한 것처럼 닫고(차감
    없음 · 연속 오류에 세지 않는다 — 패널 error 가 UNCHARGED 코드로 시작한다) 쟁점은 대기로 돌린다. 멈춘 잡이 살아 있어 사슬은 종합으로
    넘어가지 않는다. 사람이 고치고 재개하면 이어 돈다."""
    _release_panel(store, panel, charge=False)
    store.execute("UPDATE rr_panels SET status = 'error', error = ?, ended_at = ? WHERE id = ?",
                  (f"{hold_code}: 쟁점 패널을 시작하지 못했다 — {why}", now_epoch(), panel["id"]))
    row = store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job["id"],))
    if row is not None and row["state"] == "running":
        _set_job(store, job["id"], "paused", by=f"code:{hold_code}", error=f"{hold_code}: {why}",
                 hold={"code": hold_code, "until": None})
    return {"panel_id": panel["id"], "status": "paused", "error": hold_code}


def _close_panel_stream_lost(store: Any, panel: Mapping[str, Any], job: Mapping[str, Any],
                             lost: EngineStreamLost) -> dict:
    """앱이 스트림을 놓은 패널을 닫는다 — 좌석 재시도와 연속 실패에 세지 않고 잡을 멈춘다.

    엔진은 구독이 끊겨도 심의를 끝까지 돌린다. 종전에는 이 패널도 엔진 실패로 세어 5초 뒤 같은 좌석을 다시
    편성했다 — 같은 심의가 엔진에 겹쳐 돌아 공유 LLM 부하가 배가 되고(연속 3패널이면 잡이 죽으니 셋까지),
    좌석은 제 탓이 아닌 일로 세 번째에 skipped 로 굳었다. 그래서 좌석은 차감 없이 pending 으로 돌리고 잡을
    멈춘다. 사유는 잡의 error 에 적는다(pause_reason 은 CHECK 로 세 값만 받는다). 사람이 재개하면 이어 돈다.
    """
    error = str(lost)
    _release_panel(store, panel, charge=False)
    store.execute(
        "UPDATE rr_panels SET status = 'error', error = ?, conv_id = ?, ended_at = ? WHERE id = ?",
        (error, lost.conv_id, now_epoch(), panel["id"]),
    )
    # 그 사이 사람이 취소했으면(cancelling) 그 전이를 덮지 않는다 — 다음 편성에서 cancelled 가 된다.
    row = store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job["id"],))
    if row is not None and row["state"] == "running":
        _set_job(store, job["id"], "paused", by=f"code:{lost.code}",
                 error=f"{error} — 잡을 멈췄다(좌석 재시도는 차감하지 않았다). 재개하면 이어 돈다")
    return {"panel_id": panel["id"], "status": "error", "error": error}


def _close_panel_unstarted(store: Any, panel: Mapping[str, Any], job: Mapping[str, Any], code: str, *,
                           error: str, conv_id: str | None, pause: bool) -> dict:
    """엔진이 받아 주지 않아 시작도 못 한 패널을 닫는다 — 좌석 재시도와 연속 실패에 세지 않는다.

    `code` 는 UNSTARTED_CODES 이거나, 자리를 기다리던 중에 사람이 잡을 취소·정지했으면 'cancelled' 다.

    좌석은 차감 없이 pending 으로 돌린다. `pause` 면 잡을 멈춘다 — 자리가 한 시간째 안 나는 포털에 곧바로 다시
    편성해 봐야 같은 대기를 되풀이할 뿐이다(사람이 재개하면 이어 돈다). 앱이 내려가며 그친 대기는 멈추지 않는다 —
    겹칠 심의가 없으니 다시 뜨면 기동 복구가 그 잡을 줄 세운다. `conv_id` 는 대기 중에 만들어 둔 빈 대화다.
    """
    _release_panel(store, panel, charge=False)
    store.execute(
        "UPDATE rr_panels SET status = 'error', error = ?, conv_id = ?, ended_at = ? WHERE id = ?",
        (error, conv_id, now_epoch(), panel["id"]),
    )
    if pause:
        # 그 사이 사람이 취소했으면(cancelling) 그 전이를 덮지 않는다 — 다음 편성에서 cancelled 가 된다.
        row = store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job["id"],))
        if row is not None and row["state"] == "running":
            _set_job(store, job["id"], "paused", by=f"code:{code}",
                     error=f"{error} — 잡을 멈췄다(좌석 재시도는 차감하지 않았다). 재개하면 이어 돈다")
    return {"panel_id": panel["id"], "status": "error", "error": error}


def _brief_retry_streak(store: Any, target_key: str) -> int:
    """가장 최근부터 연속으로 brief_retry 로 닫힌 패널 수 — 닫힌 패널(done·error)만 본다(지금 닫는 패널은 running 이다)."""
    streak = 0
    for row in store.query(
        "SELECT status, error FROM rr_panels WHERE target_key = ? AND status IN ('done', 'error')"
        " ORDER BY panel_no DESC", (target_key,)
    ):
        if row["status"] != "error" or _uncharged_code(row["error"]) != BRIEF_RETRY_CODE:
            break
        streak += 1
    return streak


def _close_panel_brief_failed(store: Any, panel: Mapping[str, Any], job: Mapping[str, Any], exc: Exception) -> dict:
    """브리프 조립이 실패한 패널을 닫는다 — 엔진에 보내지도 않았으므로 좌석 재시도와 연속 실패에 세지 않는다(WP1 R-4 · P-13).

    브리프 조립은 결정론이라 그대로 다시 돌리면 같은 자리에서 멈춘다 — 린터 위반·단언·키·형 오류는 `brief_error` 로
    닫고 잡을 멈춘다(사람이 원인을 고친 뒤 재개한다). DB 잠금·연결·파일 같은 일시 장애는 `brief_retry` 로 닫고 멈추지 않는다
    (5초 뒤 다시 편성돼 저절로 넘어간다). 같은 타깃에서 BRIEF_RETRY_MAX 번 이어지면 그때 멈춘다 — 밤새 같은 장애를 돌지 않는다.
    """
    why = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, BRIEF_TRANSIENT_ERRORS):
        streak = _brief_retry_streak(store, panel["target_key"]) + 1
        pause = streak >= BRIEF_RETRY_MAX
        tail = (f" — 같은 타깃에서 {streak}번 이어졌다" if pause
                else f" — 일시 장애로 보고 다시 편성한다({streak}/{BRIEF_RETRY_MAX})")
        return _close_panel_unstarted(store, panel, job, BRIEF_RETRY_CODE, conv_id=None, pause=pause,
                                      error=f"{BRIEF_RETRY_CODE}: {why}{tail}")
    return _close_panel_unstarted(
        store, panel, job, BRIEF_ERROR_CODE, conv_id=None, pause=True,
        error=f"{BRIEF_ERROR_CODE}: {why} — 브리프 조립은 결정론이라 그대로 다시 돌리면 같은 자리에서 멈춘다."
              " 원인을 고친 뒤 재개한다")


def _close_panel_no_decision(store: Any, panel: Mapping[str, Any], job: Mapping[str, Any],
                             failed: EngineNoDecision) -> dict:
    """의장이 결정문을 못 낸 패널을 닫는다 — 좌석 재시도와 연속 실패에 세지 않고, 엔진이 남긴 것을 적고 잡을 멈춘다.

    종전에는 엔진 실패로 세어 5초 뒤 같은 좌석을 다시 편성했다 — 몇 시간짜리 패널이 같은 호출 한도로 세 번 돌고
    (끝마다 의장 대기 최대 2×(2×DELIB_TIMEOUT_S+8)초), 좌석은 제 탓이 아닌 일로 skipped 로 굳어 잡이 죽었다.
    엔진이 저장한 보고서와 대화는 패널 어디에도 적히지 않았다. 러너는 timeout_s 를 싣지 않으므로 고칠 값은 엔진
    박스의 설정 하나다 — 그 이름(knob)을 문구 끝에 붙인다(엔진 사유도 자르지 않는다). error 는 코드로 시작해야 한다
    (`_error_streak` 이 맨 앞의 코드로 가른다).
    """
    tail = f" — 설정 {failed.knob}" if failed.knob else ""
    error = str(failed) + tail
    _release_panel(store, panel, charge=False)
    # 발언 전부는 포털 대화(conv_id)와 엔진이 저장한 보고서(report_id)에 있다 — 패널에는 그 둘과, 엔진이 결정문
    # 자리에 내린 글(좌석별 마지막 입장)을 남긴다. 발언을 담을 열은 없다(스트림을 놓은 패널도 같다).
    store.execute(
        "UPDATE rr_panels SET status = 'error', error = ?, conv_id = ?, report_id = ?, decision_text = ?,"
        " ended_at = ? WHERE id = ?",
        (error, failed.conv_id, failed.report_id, failed.decision_text or None, now_epoch(), panel["id"]),
    )
    # 그 사이 사람이 취소했으면(cancelling) 그 전이를 덮지 않는다 — 다음 편성에서 cancelled 가 된다.
    row = store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job["id"],))
    if row is not None and row["state"] == "running":
        if failed.cause in review_ops.EXTERNAL_WORKER_CODES:
            # 외부 응답자 심의의 의장이 과제를 받을 워커가 없어 못 냈다(Claude 길 X-2) — 엔진이 이미 기다림 한도와 의장 재호출을 다
            # 썼다. 사람이 잡 주인의 Claude Code 워크플로를 다시 돌리고 재개한다(시계로 저절로 재개하지 않는다).
            _set_job(store, job["id"], "paused", by=f"code:{failed.cause}", hold={"code": "external_worker", "until": None},
                     error=f"{error} — 잡을 멈췄다(보류 external_worker · 좌석 재시도는 차감하지 않았다). 잡 주인의 Claude Code 에서"
                           f" 워크플로 {EXTERNAL_WORKFLOW} 를 그 사람의 PAT 로 (다시) 돌린 뒤 재개한다")
            return {"panel_id": panel["id"], "status": "error", "error": error}
        how = "엔진 박스의 그 설정을 올린 뒤 재개하면 이어 돈다" if failed.knob else "재개하면 이어 돈다"
        _set_job(store, job["id"], "paused", by=f"code:{failed.code}",
                 error=f"{error} — 잡을 멈췄다(좌석 재시도는 차감하지 않았다). {how}")
    return {"panel_id": panel["id"], "status": "error", "error": error}


def _run_parameters(engine: Any) -> Mapping[str, Any]:
    """`engine.run` 이 받는 인자 이름 — 선택 인자(on_progress)를 받는 엔진에만 그것을 넘기려고 본다."""
    try:
        return inspect.signature(engine.run).parameters
    except (TypeError, ValueError):
        return {}


def _stop_reader(store: Any, job: Mapping[str, Any]):
    """도는 패널이 '사람이 이 잡을 취소·정지했나' 를 묻는 함수 — 그랬으면 패널에 적을 말을, 아니면 None 을 돌려준다.

    잡 행이 정본이다(따로 깃발을 두지 않는다 — cancel_job·pause_job 은 행만 고친다). 잡 행은
    STOP_POLL_INTERVAL_S 간격으로만 읽는다. 엔진은 프레임마다 묻고 프레임은 ping 덕에 15초 안에 오므로, 취소는
    15초 + 이 간격 안에 닿는다(heartbeat 가 없는 옛 엔진에서는 다음 줄이 올 때다). 읽지 못하면 None 이다 —
    조회 한 번이 실패했다고 몇 시간짜리 패널을 닫지 않는다.
    """
    last: dict = {"read_at": None, "why": None}

    def should_stop() -> str | None:
        now = time.monotonic()
        if last["read_at"] is not None and now - last["read_at"] < STOP_POLL_INTERVAL_S:
            return last["why"]
        last["read_at"] = now
        try:
            row = store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job["id"],))
        except Exception:  # noqa: BLE001 — 위 설명대로다.
            log.exception("잡 %s 상태 조회 실패(비치명) — 패널은 계속 돈다", job.get("id"))
            return last["why"]
        last["why"] = STOP_JOB_STATES.get(row["state"]) if row is not None else None
        return last["why"]

    return should_stop


def _progress_writer(store: Any, job: Mapping[str, Any], panel: Mapping[str, Any]):
    """도는 패널의 '마지막 신호' 를 `rr_jobs.progress_json` 에 적는 콜백(PROGRESS_WRITE_INTERVAL_S 간격).

    패널 벽시계가 몇 시간이라 `status='running'` 과 시작 시각만으로는 도는 것과 멈춘 것을 가를 수 없다.
    `last_frame_at` 은 ping 을 포함한 아무 프레임(연결이 살아 있다), `last_event_at`·`last_step` 은 ping 이 아닌
    프레임(심의가 나아가고 있다)이다. 적는 데 실패해도 패널은 계속 돈다.
    """
    head = {"panel_id": panel["id"], "panel_no": panel.get("panel_no"), "started_at": now_epoch()}
    if panel.get("kind") == "issue":
        # 쟁점 패널의 수확 알림(issue_yield_low — 3.12)은 패널이 바뀌어도 진행판에 남는다(이 머리가 진행 줄마다 실린다).
        from app import issues  # noqa: PLC0415 — issues 는 이 모듈을 쓴다.

        advice = issues.yield_advice(store, panel["target_key"])
        if advice:
            head["advice"] = advice
    last: dict = {"written_at": None}

    def note(frame: Mapping[str, Any], *, force: bool = False) -> None:
        now = now_epoch()
        # `force` 는 러너가 직접 적는 줄이다(엔진 자리 대기) — 간격을 건너뛰고, 간격 셈도 건드리지 않는다. 건드리면
        # 자리가 난 뒤 첫 프레임이 '방금 적었다' 에 걸려, 도는 패널이 최대 1분 '대기' 로 보인다.
        if not force:
            if last["written_at"] is not None and now - last["written_at"] < PROGRESS_WRITE_INTERVAL_S:
                return
            last["written_at"] = now
        body = {**head, "last_frame_at": None, "last_event_at": None, "last_step": "", "frames": 0, **frame}
        try:
            store.execute("UPDATE rr_jobs SET progress_json = ? WHERE id = ?", (canonical_json(body), job["id"]))
        except Exception:  # noqa: BLE001 — 진행 표시를 못 적었다고 몇 시간짜리 패널을 버리지 않는다.
            log.exception("패널 %s 진행 기록 실패(비치명)", panel["id"])

    return note


def _note_issue_yield(store: Any, job: Mapping[str, Any], target_key: str) -> None:
    """쟁점 패널이 끝날 때마다 잡 진행판의 `advice` 를 맞춘다 — 최근 다섯이 전부 기각·불명이면 issue_yield_low, 아니면 지운다.
    잡을 멈추지 않는다(멈춤은 사람이 정한다 — 3.12)."""
    from app import issues  # noqa: PLC0415 — issues 는 이 모듈을 쓴다.

    advice = issues.yield_advice(store, target_key)
    row = store.query_one("SELECT progress_json FROM rr_jobs WHERE id = ?", (job["id"],))
    body = json.loads(row["progress_json"] or "{}") if row is not None else {}
    if body.get("advice") == advice or (advice is None and "advice" not in body):
        return
    if advice:
        body["advice"] = advice
        log.warning("쟁점 잡 %s: 최근 쟁점 패널 %s건이 전부 기각·불명이다(issue_yield_low) — 멈춤은 사람이 정한다", job["id"],
                    issues.YIELD_WINDOW)
    else:
        body.pop("advice", None)
    store.execute("UPDATE rr_jobs SET progress_json = ? WHERE id = ?", (canonical_json(body), job["id"]))


PURGED_PANEL_ERROR = "project_purged: 과제가 폐기돼 늦게 끝난 패널 결과를 버렸다(원장·패널에 쓰지 않았다)"


def _target_purged(store: Any, target_key: str) -> bool:
    """폐기 상태는 늘 실제 원장에서 본다 — 주입한 대역 registry 가 아니라(review1 L6)."""
    from app import registry  # noqa: PLC0415 — registry 는 이 모듈을 거쳐 무겁다.

    return registry.target_purged(store, target_key)


def _close_panel_purged(store: Any, panel: Mapping[str, Any]) -> dict:
    """폐기된 과제의 패널을 결과 없이 닫는다 — 자리는 차감 없이 되돌리고(쟁점 패널이면 그 쟁점은 잡이 없어 미토의로) 패널에는 까닭만."""
    _release_panel(store, panel, charge=False)
    store.execute("UPDATE rr_panels SET status = 'error', error = ?, ended_at = ? WHERE id = ?",
                  (PURGED_PANEL_ERROR, now_epoch(), panel["id"]))
    log.warning("패널 %s: 과제가 폐기돼 늦게 끝난 결과를 버렸다", panel["id"])
    return {"panel_id": panel["id"], "status": "purged"}


def _complete_panel(
    store: Any,
    settings: Any,
    panel: Mapping[str, Any],
    job: Mapping[str, Any],
    result: Mapping[str, Any],
    model_json: Mapping[str, Any],
    *,
    narrative_mod: Any | None,
    registry_mod: Any | None,
    engine: Any,
    frozen_brief: Mapping[str, Any] | None = None,
    touch_job: bool = True,
) -> dict:
    """엔진 결과를 원장에 앉힌다(plan §6.7.2 7~12단계). `touch_job=False` 는 다시 저장(repersist_panel)의 길이다 —
    잡의 panels_done 만 올리고 상태(수확 체감 정지)는 건드리지 않는다. `engine=None` 이면 모델을 다시 묻지 않는다."""
    if narrative_mod is None:
        from app import narrative as narrative_mod  # noqa: PLC0415
    if registry_mod is None:
        from app import registry as registry_mod  # noqa: PLC0415

    seat_keys = [s["key"] for s in panel["seats"]]
    decision_text = str(result.get("decision_text") or "")
    turns = list(result.get("turns") or [])
    events = result.get("events")
    attribution = attribute_events(events, seat_keys)

    with store.tx():
        # 폐기된 과제의 패널은 늦게 끝나도 원장에 쓰지 않는다 — 같은 트랜잭션에서 폐기 상태를 본다(재설계 M3 review1 L6).
        if _target_purged(store, panel["target_key"]):
            return _close_panel_purged(store, panel)
        # 좌석 도구 호출 원문은 포털 대화가 아니라 이 표가 정본이다(§6.7.2 7단계).
        record_panel_calls(store, panel, events, source="sse", conv_id=result.get("conv_id"))

    spec = narrative_mod.parse_risk_spec(decision_text)
    parsed = spec is not None
    now = now_epoch()

    # 종료 직후 model 스냅샷 재확인(D6 — 시작값이 정본, 재실행 없음).
    model_final = dict(model_json)
    model_changed = False
    if engine is not None and model_json.get("captured") == "health_snapshot":
        after = snapshot_model(engine)
        if after.get("captured") == "health_snapshot" and (
            after.get("model") != model_json.get("model") or after.get("vllm") != model_json.get("vllm")
        ):
            model_final["model_end"] = after.get("model")
            model_changed = True

    # 8~12단계를 한 트랜잭션으로 묶는다 — 중간 실패 시 'done 인데 finding 0·좌석 running' 반쪽 저장이 남지 않는다.
    with store.tx():
        if _target_purged(store, panel["target_key"]):
            return _close_panel_purged(store, panel)
        store.execute(
            "UPDATE rr_panels SET status = 'done', decision_text = ?, risk_spec_json = ?, risk_spec_parsed = ?,"
            " conv_id = ?, report_id = ?, model_json = ?, ended_at = ? WHERE id = ?",
            (decision_text, canonical_json(spec) if parsed else None, 1 if parsed else 0,
             result.get("conv_id"), result.get("report_id"), canonical_json(model_final), now, panel["id"]),
        )

        extracted = narrative_mod.persist_panel_result(
            store, panel["id"], decision_text=decision_text, spec=spec, turns=turns,
            attribution=attribution, actor=None,
        )
        # 발언 수는 turns[] 가 정본이다(events 에 turn 이 없는 캡처도 있다 — §6.7 7단계 표).
        turns_by_seat: dict[str, int] = {}
        for turn in turns:
            key = str(turn.get("persona") or "")
            if key:
                turns_by_seat[key] = turns_by_seat.get(key, 0) + 1

        seat_results = []
        for seat in extracted.get("seats") or []:
            key = seat.get("agent_key")
            if key not in seat_keys:
                continue
            state = attribution["seats"].get(key) or {}
            seat_results.append({
                "agent_key": key,
                "opinion_id": seat.get("opinion_id"),
                "turns_n": max(
                    int(seat.get("turns_n") or 0),
                    turns_by_seat.get(key, 0),
                    int(state.get("turns_n") or 0),
                ),
                "used_tool": state.get("used_tool"),
                "cited_refs_n": int(seat.get("cited_refs_n") or 0),
                "abstained": bool(seat.get("abstained")),
            })
        issue_panel = panel.get("kind") == "issue"
        if issue_panel:
            # 쟁점 패널은 좌석 원장을 쓰지 않는다 — 결과로 쟁점을 정하고(resolve_issue), 병합이 그 결과로 닻 행을 덮는다(3.5).
            from app import issues  # noqa: PLC0415 — issues 는 이 모듈을 쓴다.

            coverage = {"by_status": {}}
            resolved = issues.resolve_issue(store, panel["id"], settings=settings)
        else:
            coverage = planner.apply_seat_results(
                store, panel["id"], seat_results, decision_ok=bool(decision_text), model=model_final.get("model")
            )

        merged = registry_mod.merge_panel(store, panel["id"])
        new_clusters = int((merged or {}).get("new_clusters") or 0)
        escalated = list((merged or {}).get("escalated") or ())

        llm_calls = len(turns) + attribution["lookups"] * 3 + len(panel["tools"]) + 3
        # 실제로 어느 자격으로 돌았는지는 엔진이 안다 — 잡의 사전 판정은 폴백값이다. 다만 엔진은 넘겨받은 사람의
        # PAT 를 'owner' 로만 부르므로, 러너가 요청자를 넘겼으면 그것은 요청자 자격이다.
        credential = str(result.get("credential") or job.get("credential") or "service")
        if credential == "owner" and job.get("credential") == "requester":
            credential = "requester"
        quality = _quality(
            panel, attribution, extracted,
            credential=credential,
            call_path=str(result.get("call_path") or "portal"),
            new_clusters=new_clusters,
            llm_calls=llm_calls,
            cap=int(settings.risk_panel_llm_cap),
            parsed=parsed,
            pat_degraded=bool(result.get("pat_degraded")),
        )
        if model_changed and "model_changed_midrun" not in quality["flags"]:
            quality["flags"].append("model_changed_midrun")
        # 이 저장이 쓴 근거 등급 규칙의 판 — 이 패널을 다시 낼 때 같은 판으로 등급을 낸다(BQ-6 · D-19). 없으면 업그레이드 전 패널로 읽힌다.
        if getattr(narrative_mod, "GRADE_RULES", None):
            quality["grade_rules"] = narrative_mod.GRADE_RULES
        if frozen_brief and frozen_brief.get("brief_drift"):
            quality["brief_drift"] = list(frozen_brief["brief_drift"])
        if frozen_brief and frozen_brief.get("brief_hash"):
            quality["brief_hash"] = frozen_brief["brief_hash"]
        # 12칸을 넘겨 빠진 근거와 다 못 실은 메모, 판단어로 «» 에 싸인 줄, 상한에 잘린 줄, 좌석이 못 열어 싣지 않은 diff_id 표식,
        # 싣기는 했지만 좌석이 열 수 있을지 확인하지 못한 표식 — 좌석은 받은 것이 전부라고 믿고 판정했으므로 패널에 남긴다.
        for lost in ("evidence_dropped", "user_memo_cut", "brief_shielded", "brief_clipped", "knowledge_query_cut",
                     "diff_ref_withheld", "gateway_unverified"):
            if frozen_brief and frozen_brief.get(lost):
                quality[lost] = frozen_brief[lost]
                quality["flags"].append(lost)
        # 앱이 지식카드 검색어를 실어 보냈는데 엔진이 질문으로 찾았다 — 옛 포털과 섞였을 때의 유일한 신호다(workorder-c 5절 1).
        ignored = sorted(k for k, q in (attribution.get("knowledge_queries") or {}).items() if q == "question")
        if frozen_brief and frozen_brief.get("knowledge_query_sent") and ignored:
            quality["knowledge_query_ignored"] = ignored
            quality["flags"].append("knowledge_query_ignored")
        # 엔진이 좌석에 주지 않았다고 카드로 알린 것(예산·건수 초과 등)도 같은 자리에 옮겨 적는다.
        withheld = withheld_by_engine(events)
        if withheld:
            quality["engine_withheld"] = withheld
            quality["flags"].append("engine_withheld")
        if escalated and "registry_escalated" not in quality["flags"]:
            # 사람이 닫았던 행이 더 강한 근거로 재제기됐다 — 사람이 다시 볼 자리다(plan §4.7.1).
            quality["flags"].append("registry_escalated")
            quality["escalated_clusters"] = escalated
        if result.get("call_groups"):
            quality["call_groups"] = list(result["call_groups"])
        # 포털 대화를 못 만든 채 돌았다 — 포털에 이 패널의 발언이 남지 않았다(끊겼다면 부분 결과도 없다).
        if result.get("conv_missing"):
            quality["flags"].append("conversation_absent")
        if job_llm(_job_params(job)) is not None:
            # claude 잡의 패널(Claude 길 X-2) — 무엇이 돌았나는 엔진 result 프레임의 llm 이 정본이다. external 이면 판단 LLM 을 적고
            # 좌석 도구가 없던 등급(tool_mode evidence_only)을 패널에 남긴다. 아니면(중계가 llm 을 버려 이 박스의 LLM 으로 돌았다)
            # Claude 로 적지 않고 llm_mismatch 를 단다(잡에도 셈을 올린다).
            if result.get("llm") == ENGINE_EXTERNAL:
                quality["llm"] = ENGINE_EXTERNAL
                if result.get("tool_mode") in ("tools", "evidence_only"):
                    store.execute("UPDATE rr_panels SET tool_mode = ? WHERE id = ?", (result["tool_mode"], panel["id"]))
            else:
                quality["flags"].append("llm_mismatch")
                quality["llm_mismatch"] = {"want": ENGINE_EXTERNAL, "got": result.get("llm")}
                note_llm_mismatch(store, job["id"])
        store.execute(
            "UPDATE rr_panels SET quality_json = ?, llm_calls = ? WHERE id = ?",
            (canonical_json(quality), llm_calls, panel["id"]),
        )
        store.execute(
            "UPDATE rr_jobs SET panels_done = panels_done + 1, updated_at = ? WHERE id = ?", (now, job["id"])
        )

        level = registry_mod.close_level(store, panel["target_key"])
        # 쟁점 패널(cells 대상)의 보고서 판은 종합 보고서(S3-9)의 몫이다 — 패널 통합 보고서를 조립하지 않는다.
        if level.get("raised") and not issue_panel:
            # 보고서는 원장에서 다시 만들 수 있는 파생물이다 — 조립이 터져도 패널 저장을 무르지 않고 패널에 표를 남긴다.
            # (조립은 읽기뿐이라 트랜잭션 안에서 받아도 반쪽 쓰기가 없다.)
            try:
                registry_mod.build_consolidated_report(store, panel["target_key"], level["level"])
            except Exception as exc:  # noqa: BLE001 — 위 설명대로다.
                log.exception("패널 %s 뒤 통합 보고서 조립 실패(%s)", panel["id"], level["level"])
                quality["flags"].append("report_build_failed")
                quality["report_build_error"] = f"{type(exc).__name__}: {exc}"
                store.execute("UPDATE rr_panels SET quality_json = ? WHERE id = ?",
                              (canonical_json(quality), panel["id"]))

    # 연속 2패널 over_budget 이면 이후 패널을 rounds 2 로(적응은 앞으로만) — budget_json 에 남긴다.
    if "over_budget" in quality["flags"]:
        log.info("패널 %s over_budget(llm_calls=%s)", panel["id"], llm_calls)
    if (touch_job and not issue_panel and level.get("level") not in (None, "C0")
            and _diminishing(store, panel["target_key"])):
        _set_job(store, job["id"], "paused", reason="diminishing")
    if touch_job and issue_panel:
        _note_issue_yield(store, job, panel["target_key"])

    return {
        "panel_id": panel["id"],
        "status": "done",
        "parsed": parsed,
        "coverage": coverage["by_status"],
        "new_clusters": new_clusters,
        "llm_calls": llm_calls,
        "level": level.get("level"),
        "quality_flags": quality["flags"],
        **({"issue": resolved} if issue_panel else {}),
    }


# ---------------------------------------------------------------- 스레드
# ---------------------------------------------------------------- PAT 폐기 대조(plan §8.2.7·§0.6 '자격 최소 권한')
REVOKED_PATH = "/auth/pat/revoked.json"
REVOKED_TIMEOUT_S = 3.0
# 테스트가 httpx.MockTransport 를 꽂는 자리. None 이면 실제 네트워크.
_revoked_transport: Any | None = None


def fetch_revoked_jtis(settings) -> list[str] | None:
    """포털 `GET /auth/pat/revoked.json` → `{"revoked":[jti…]}`. 형식이 아니거나 실패면 None(직전 목록 유지)."""
    base = str(getattr(settings, "portal_base", "") or "").rstrip("/")
    if not base:
        return None
    try:
        with http_client(transport=_revoked_transport, timeout=REVOKED_TIMEOUT_S) as client:
            r = client.get(base + REVOKED_PATH)
        if r.status_code != 200:
            log.warning("PAT 폐기 목록 조회 실패(HTTP %s) — 직전 목록을 유지한다.", r.status_code)
            return None
        body = r.json()
    except Exception as exc:  # noqa: BLE001 — 네트워크·파싱 실패는 비치명적이다(값은 로그하지 않는다).
        log.warning("PAT 폐기 목록 조회 실패(%s) — 직전 목록을 유지한다.", type(exc).__name__)
        return None
    revoked = body.get("revoked") if isinstance(body, dict) else None
    if not isinstance(revoked, list):
        log.warning("PAT 폐기 목록 형식이 {'revoked':[jti…]} 가 아니다 — 직전 목록을 유지한다.")
        return None
    return [str(j) for j in revoked if str(j).strip()]


def poll_revoked_pats(store, settings, *, now: int | None = None) -> dict:
    """적중한 `pat_jti` 행에 `revoked_at` 을 찍는다 — 강등은 패널 경계에서 credential_pat 이 None 을 돌려 일어난다.

    응답이 계약 형식이 아니거나 조회가 실패하면 아무 행도 건드리지 않는다(조용한 전체 강등 금지).
    """
    jtis = fetch_revoked_jtis(settings)
    if not jtis:
        return {"checked": 0, "revoked": 0}
    stamp = now_epoch() if now is None else now
    marks = ",".join("?" for _ in jtis)
    rows = store.query(
        f"SELECT owner_sub FROM _user_credentials WHERE pat_jti IN ({marks}) AND revoked_at IS NULL", jtis)
    for row in rows:
        store.execute(
            "UPDATE _user_credentials SET revoked_at = ?, revoked_seen_at = ? WHERE owner_sub = ?",
            (stamp, stamp, row["owner_sub"]))
    return {"checked": len(jtis), "revoked": len(rows)}


class RiskRunner:
    """main.py lifespan 이 start()/stop() 하는 객체. 엔진 클라이언트는 주입식이고 러너는 직접 LLM 을 부르지 않는다."""

    def __init__(
        self,
        store,
        settings,
        engine: PanelEngine | None = None,
        *,
        narrative_mod: Any | None = None,
        registry_mod: Any | None = None,
        external_sync_send: Any | None = None,
        lock: Any | None = None,
        review_engine: ReviewEngine | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.engine = engine
        self.narrative_mod = narrative_mod
        self.registry_mod = registry_mod
        # 데이터 디렉터리 러너 잠금(runlock.RunnerLock). None 이면 잠금 없이 돈다(시험·단독 실행). 운영 배선(main.py)은
        # 늘 준다 — 같은 데이터 디렉터리에 프로세스가 둘 떠도 러너·재기동 복구는 쥔 하나만 돈다(WP5a R2).
        self.lock = lock
        self._begin_lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._workers: list[threading.Thread] = []
        self._last_tick: dict[str, float | None] = {name: None for name, _ in _LOOPS}
        self._last_revocation_poll = 0.0
        # 외부 반영 전송기(주입식). None 이면 재시도 틱은 due 만 세고 아무것도 보내지 않는다(§5.5.3).
        self.external_sync_send = external_sync_send
        concurrency = int(getattr(settings, "risk_concurrency", 1) or 1) if settings is not None else 1
        self._sem = threading.Semaphore(max(1, concurrency))
        # 카드 대조 검토 잡의 루프(주입식 엔진 — None 이면 틱이 아무것도 하지 않는다). 동시 수는 HWAXRISK_REVIEW_CONCURRENCY 와 서버
        # 관문 limit 가운데 작은 것이고 패널 세마포어와 따로 센다. 선점 표지(lease_owner)의 머리는 러너 잠금의 boot_id 다.
        from app import review_runner  # noqa: PLC0415 — review_runner 는 이 모듈을 import 한다.

        self.review_engine = review_engine
        self._review = review_runner.ReviewLoop(store, settings, review_engine, stop=self._stop,
                                                boot_id=getattr(lock, "boot_id", None))
        # 종합 잡(M3 S3-9) — 요약은 카드 대조와 같은 포털 중계·엔진 관문을 지난다(같은 엔진 클라이언트). 엔진이 없으면 틱이 쉰다.
        from app import synth  # noqa: PLC0415 — synth 는 이 모듈을 거쳐 무겁다.

        self._synth = synth.SynthWorker(store, settings, review_engine, stop=self._stop)

    # ------------------------------------------------------------ 루프
    def _loop(self, name: str, interval: float) -> None:
        while not self._stop.is_set():
            self._last_tick[name] = time.time()
            if name == "panel_loop":
                try:
                    self._panel_tick()
                except Exception:  # noqa: BLE001 — 한 번의 실패가 스레드를 죽이지 않게 한다.
                    log.exception("panel_loop tick 실패")
            elif name == "sync_loop":
                try:
                    self._revocation_tick()
                except Exception:  # noqa: BLE001 — 폐기 대조 실패는 비치명적이다.
                    log.exception("sync_loop 폐기 대조 실패")
                try:
                    self._external_sync_tick()
                except Exception:  # noqa: BLE001 — 외부 반영 재시도 실패도 러너를 죽이지 않는다.
                    log.exception("sync_loop external_sync 재시도 실패")
            elif name == "review_loop":
                try:
                    self._review.tick()
                except Exception:  # noqa: BLE001 — 한 번의 실패가 스레드를 죽이지 않게 한다.
                    log.exception("review_loop tick 실패")
            elif name == "synth_loop":
                try:
                    self._synth.tick()
                except Exception:  # noqa: BLE001 — 한 번의 실패가 스레드를 죽이지 않게 한다.
                    log.exception("synth_loop tick 실패")
            elif name == "chain_loop":
                try:
                    from app import chain  # noqa: PLC0415 — chain 은 종합·쟁점을 거쳐 무겁다.

                    chain.sweep(self.store)
                except Exception:  # noqa: BLE001 — 한 번의 실패가 스레드를 죽이지 않게 한다.
                    log.exception("chain_loop sweep 실패")
            self._stop.wait(interval)

    def _revocation_tick(self) -> None:
        """포털 폐기 목록을 `risk_pat_revocation_poll_s` 주기로 대조한다(plan §8.2.7 '폐기 대조')."""
        if self.store is None or self.settings is None:
            return
        period = float(getattr(self.settings, "risk_pat_revocation_poll_s", 0) or 0)
        if period <= 0:
            return
        now = time.time()
        if now - self._last_revocation_poll < period:
            return
        self._last_revocation_poll = now
        poll_revoked_pats(self.store, self.settings)

    def _external_sync_tick(self) -> dict:
        """`next_at` 이 지난 pending 채널을 1회 재시도한다(plan §5.5.3 — sync_loop 주기 60 s).

        전송기(`send`)는 주입식이라 러너 자체는 외부를 열지 않는다. 없으면 due 만 세고 지나간다.
        """
        if self.store is None or self.settings is None:
            return {"due": 0, "sent": 0, "skipped": "store 없음"}
        from app import nightly  # noqa: PLC0415 — nightly 는 runner 를 import 하지 않는다.

        return nightly.retry_external_sync(self.store, now=now_epoch(), send=self.external_sync_send)

    def _panel_tick(self) -> None:
        """잡 1건을 집어 패널 1건을 돌릴 워커를 띄운다(세마포어 risk_concurrency, 타깃당 직렬)."""
        if self.store is None or self.settings is None or self.engine is None or self._stop.is_set():
            return
        self._workers = [t for t in self._workers if t.is_alive()]
        if not self._sem.acquire(blocking=False):
            return
        started = False
        try:
            job = claim_next_job(self.store, self.settings, engine=self.engine)
            if job is None:
                return
            worker = threading.Thread(
                target=self._run_worker, args=(job,), name=f"panel-{str(job['id'])[:8]}", daemon=True
            )
            started = True
            worker.start()
            self._workers.append(worker)
        finally:
            if not started:
                self._sem.release()

    def _run_worker(self, job: Mapping[str, Any]) -> None:
        try:
            run_panel(
                self.store, self.settings, self.engine, job,
                narrative_mod=self.narrative_mod, registry_mod=self.registry_mod, stop=self._stop,
            )
        except Exception:  # noqa: BLE001 — 잡 하나의 실패로 러너가 멈추지 않는다.
            log.exception("패널 실행 실패(job=%s)", job.get("id"))
        finally:
            self._sem.release()

    # ------------------------------------------------------------ 수명
    def start(self) -> None:
        """러너 잠금을 쥐면 재기동 복구와 루프를 시작한다. 못 쥐면 REST·MCP 만 열린 채로 두고 runlock.RETRY_S 마다
        다시 잡아 본다 — 쥔 프로세스가 죽으면 커널이 잠금을 풀어 이어받는다. 못 쥔 프로세스가 복구를 돌리면 쥔
        프로세스가 돌리는 패널을 닫고 좌석을 되돌려 같은 좌석이 두 번 돈다."""
        if self._threads:
            return
        self._stop.clear()
        if self.lock is None or self.lock.acquire():
            self._begin()
            return
        from app import runlock  # noqa: PLC0415 — 재시도 간격은 부를 때 읽는다(시험이 줄인다).

        log.warning("러너 잠금(%s)을 다른 프로세스가 쥐고 있다(%s) — 이 프로세스는 REST·MCP 만 연다. 러너 루프와 재기동"
                    " 복구는 돌지 않고 %s초마다 다시 잡아 본다.", self.lock.path, self.lock.holder(), runlock.RETRY_S)
        waiter = threading.Thread(target=self._await_lock, name="runner_lock", daemon=True)
        waiter.start()
        self._threads.append(waiter)

    def _await_lock(self) -> None:
        from app import runlock  # noqa: PLC0415

        while not self._stop.wait(runlock.RETRY_S):
            if self.lock.acquire():
                log.info("러너 잠금을 이어받았다 — 재기동 복구와 러너 루프를 시작한다")
                self._begin()
                return

    def _begin(self) -> None:
        """재기동 복구 → 루프 스레드. 잠금을 쥔 뒤에만 부른다(기동 때 또는 이어받을 때)."""
        with self._begin_lock:
            if self._stop.is_set():
                return
            if self.store is not None:
                try:
                    recover_running_panels(self.store)
                    # 카드 대조 검토도 같은 자리에서 — 셀 running → pending, 전문가 running → planned, 호출 running →
                    # aborted('restart'). 차감·백오프 없이 검토 잡은 running 그대로 다음 틱이 이어 돈다(잠금을 쥔 프로세스만 — m2-wp3b S8).
                    from app import review_cells  # noqa: PLC0415 — review_cells 는 planner 를 거쳐 무겁다.

                    review_cells.recover_running(self.store)
                    # 종합 잡의 요약 호출도 — running 요약 → pending(차감 없음, review1 H2).
                    from app import synth  # noqa: PLC0415 — synth 는 이 모듈을 거쳐 무겁다.

                    synth.recover_running(self.store)
                    # 스냅샷 잡도 같은 자리에서 마감한다 — running 인 채 남으면 영영 진행판에 걸린다(§2.11.3).
                    from app import routes as routes_module  # noqa: PLC0415 — routes 는 runner 를 import 한다.

                    routes_module.close_stale_snapshot_jobs(self.store)
                except Exception:  # noqa: BLE001 — 복구 실패가 기동을 막지 않는다.
                    log.exception("재기동 복구 실패")
            for name, interval in _LOOPS:
                t = threading.Thread(target=self._loop, args=(name, interval), name=name, daemon=True)
                t.start()
                self._threads.append(t)

    def stop(self) -> None:
        """Event 를 세우고 스레드당 최대 2 s(패널 워커는 5 s)만 join 한 뒤 러너 잠금을 놓는다(파일은 지우지 않는다)."""
        self._stop.set()
        with self._begin_lock:
            threads = list(self._threads)
        for t in threads:
            if t is not threading.current_thread():
                t.join(timeout=2.0)
        for t in self._workers:
            t.join(timeout=5.0)
        # 검토 워커는 멈춤 물음(should_stop_review)이 러너 종료를 보고 스트림을 닫는다 — 셀은 차감 없이 pending 으로 돌아간다.
        self._review.join(timeout=5.0)
        self._threads = []
        self._workers = [t for t in self._workers if t.is_alive()]
        if self.lock is not None:
            self.lock.release()

    def status(self) -> dict:
        """{threads: [{name, alive, last_tick}]} — /api/health 에는 싣지 않는다(형식 고정)."""
        alive = {t.name: t.is_alive() for t in self._threads}
        return {
            "threads": [
                {"name": name, "alive": alive.get(name, False), "last_tick": self._last_tick[name]}
                for name, _ in _LOOPS
            ]
        }
