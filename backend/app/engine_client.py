# 심의 엔진 클라이언트 — 포털 /agent/chat 의 SSE 를 러너 계약 {decision_text, turns, conv_id, events} 로 옮기고, 카드 대조는 대화 없이 /agent/card-review/* 를 부른다(plan §6.7.1 (A) · m2-wp3b S7)
from __future__ import annotations

import copy
import json
import logging
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from typing import Any
from urllib.parse import urlsplit

import httpx

from app import cardpack, config, identity, review_ops, taxonomy
from app.common import http_client, now_epoch

# 프로토콜·예외의 정본은 러너다(러너가 이 모듈을 import 하지 않으므로 순환이 없다).
from app.runner import (
    NO_DECISION_CODES, EngineBusy, EngineError, EngineNoDecision, EngineRejected, EngineStreamLost, PanelEngine,
    PatUnavailable, ReviewEngine, pat_unavailable_guidance,
)

log = logging.getLogger("hwax_risk.engine")

__all__ = [
    "PanelEngine", "PortalPanelEngine", "PatUnavailable",
    "build_engine", "parse_sse", "collect_stream",
    "ReviewEngine", "PortalReviewEngine", "build_review_engine", "collect_review_stream", "review_outcome",
    "run_body", "review_domains", "review_mechanisms",
]

# agent-server 는 '/심의 ' 로 시작하는 message 만 심의 파이프라인으로 보낸다(deliberation.DELIBERATE_TRIGGERS).
DELIBERATE_TRIGGER = "/심의 "
CHAT_PATH = "/agent/chat"
CONVERSATIONS_PATH = "/agent/conversations"
# 포털이 아직 conv kind 'risk-review' 를 받지 않는다(ConvCreate.kind 는 chat|deliberation) — 대화 생성은 비치명이라 'deliberation' 으로 만든다.
CONVERSATION_KIND = "deliberation"
CONVERSATION_SOURCE = "web"
CONVERSATION_TITLE_MAX = 200

CONNECT_TIMEOUT_S = 10.0               # 죽은 포털 감지 — 짧게 둔다
HEALTH_TIMEOUT_S = 2.0
# 스트림의 쓰기·풀 대기. 읽기(줄 사이 침묵) 한도를 물려받지 않는다 — 그 값은 15시간이라, 물려주면 본문 송신이
# 막힌 것도 15시간을 기다린다. 읽기 한도와 대화 생성 한도는 설정이다(config.DEFAULT_ENGINE_READ_TIMEOUT_S 외).
WRITE_TIMEOUT_S = 30.0
POOL_TIMEOUT_S = 30.0
DEFAULT_AGENT_URL = "http://127.0.0.1:9009"

FIELD_MAX = 200                        # 진행판에 싣는 마지막 단계 글의 상한(화면 표시 — 저장 경로는 자르지 않는다)
# 자격 강등 경고 — 계획 문구(_pat_degraded)와 agent-server 실제 코드(credential_degraded) 둘 다 받는다.
PAT_DEGRADED_CODES = ("_pat_degraded", "credential_degraded")
# 포털 릴레이가 에이전트 서버의 침묵 한도(AGENT_STREAM_IDLE_TIMEOUT_S)로 구독을 끊으며 보내는 error 코드.
# 침묵 한도 셋 중 가장 안쪽이라 이것이 먼저 온다 — 앱이 재는 침묵과 같은 사정이다(엔진은 계속 돌 수 있다).
PORTAL_STREAM_IDLE_CODE = "agent_stream_idle"


# PatUnavailable 의 정본도 러너다 — 자격 (a)(b) 부재와 포털 401/403 이 같은 처리로 모인다(plan §6.7.1 폴백 규칙).


# ---------------------------------------------------------------- SSE 파싱(포털 frame 규약 `event: <name>\ndata: <json>\n\n`)
def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict]]:
    """SSE 줄 스트림을 (event, data dict) 로 푼다. data 가 JSON 이 아니면 {'raw': …} 로 둔다."""
    event = "message"
    chunks: list[str] = []
    for raw in lines:
        line = str(raw).rstrip("\r")
        if line == "":
            if chunks:
                yield event, _payload("\n".join(chunks))
            event, chunks = "message", []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            chunks.append(line[len("data:"):].lstrip())
    if chunks:
        yield event, _payload("\n".join(chunks))


def _payload(text: str) -> dict:
    try:
        value = json.loads(text)
    except ValueError:
        return {"raw": text}
    return value if isinstance(value, dict) else {"value": value}


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


class _StreamWatch:
    """스트림 한 건이 어디까지 왔나 — 끊을 때 경과·마지막 단계·conv_id 를 말하고, 도는 동안 러너에 신호를 넘긴다."""

    def __init__(self, conv_id: str | None, on_progress: Callable[[Mapping[str, Any]], None] | None = None) -> None:
        self.conv_id = conv_id
        self.started = now_epoch()
        self.frames = 0
        self.last_step = ""
        self.last_event_at: int | None = None
        self._on_progress = on_progress

    def frame(self, name: str, data: Mapping[str, Any]) -> None:
        """프레임 하나를 센다. ping 은 연결이 살아 있다는 신호일 뿐 심의가 나아간 것이 아니다."""
        now = now_epoch()
        self.frames += 1
        if name != "ping":
            self.last_event_at = now
            if name == "status" and data.get("step"):
                self.last_step = str(data["step"])[:FIELD_MAX]
        if self._on_progress is not None:
            self._on_progress({"last_frame_at": now, "last_event_at": self.last_event_at,
                               "last_step": self.last_step, "frames": self.frames})

    def lost(self, code: str, message: str) -> EngineStreamLost:
        """앱이 스트림을 놓았다는 예외 — 어느 사유든 '엔진은 계속 돌 수 있다' 와 그 심의의 대화를 같이 말한다."""
        return EngineStreamLost(
            code, f"{message} — 경과 {now_epoch() - self.started}초, 마지막 단계 {self.last_step or '없음'}."
                  f" 엔진 쪽 심의는 계속 돌 수 있다(conv_id={self.conv_id or '없음'})", conv_id=self.conv_id)


def _watched(frames: Iterable[tuple[str, dict]], wall_s: int, watch: _StreamWatch,
             should_stop: Callable[[], str | None] | None = None, *, wall_code: str = "panel_timeout",
             wall_knob: str = "HWAXRISK_PANEL_TIMEOUT_S", what: str = "패널") -> Iterator[tuple[str, dict]]:
    """프레임마다 진행을 적고 패널 벽시계를 본다 — 시작에서 `wall_s` 초를 넘겼으면 `EngineStreamLost` 로 끊는다(plan §6.10.2).

    벽시계의 코드·손잡이·무엇이 넘겼나(`wall_code`·`wall_knob`·`what`)는 부르는 쪽이 정한다 — 기본값이 패널 것이고(문구 한 글자도
    바뀌지 않는다), 카드 대조 호출은 `review_timeout`·`HWAXRISK_REVIEW_CALL_TIMEOUT_S`·'카드 대조 호출' 을 준다.

    읽기 타임아웃은 줄 사이 침묵만 잰다. 엔진이 상태 줄을 계속 보내는 한 걸리지 않아서, 벽시계를 따로 재지
    않으면 패널 하나가 러너 자리와 그 타깃의 직렬 순서를 끝없이 붙든다. 엔진에는 패널 전체를 재는 손잡이가
    없다(`timeout_s` 는 LLM 호출 한 번의 타임아웃이다) — 그래서 앱이 잰다. 프레임이 오지 않는 동안은 볼 수 없다.
    그 구간은 읽기 타임아웃이 끊는다(엔진이 15초마다 ping 을 흘리므로 살아 있는 스트림은 15초마다 본다).
    `wall_s` 가 0 이면 재지 않는다.

    포털이 침묵 한도로 구독을 끊었다는 error 프레임은 **벽시계보다 먼저** 가려 엔진 실패와 갈라 올린다. 그 프레임은
    포털이 46800초를 조용히 기다린 뒤에야 오므로 늘 벽시계(43200초)를 넘긴 뒤다 — 벽시계를 줄 단계에서 먼저 보던
    동안에는 이 갈래에 닿지 못했고, 13시간 조용했던 엔진이 '패널이 벽시계를 넘겼다' 로 적혀 올려도 낫지 않는
    손잡이(HWAXRISK_PANEL_TIMEOUT_S)를 가리켰다. 그 밖의 늦은 프레임(결정문·다른 error)은 그대로 벽시계 초과다.

    `should_stop` 은 러너가 준 물음이다 — 사람이 그 잡을 취소·정지했으면 사유를 돌려준다. 그때 여기서 올린 예외가
    `with client.stream(...)` 을 빠져나가며 응답을 닫는다. 벽시계가 12시간이라, 이 물음이 없으면 취소가 그만큼
    늦게 닿는다.
    """
    for name, data in frames:
        if name == "error" and str(data.get("code") or "") == PORTAL_STREAM_IDLE_CODE:
            raise watch.lost("engine_silent", f"{PORTAL_STREAM_IDLE_CODE}: {data.get('message') or ''}".strip())
        if wall_s and now_epoch() > watch.started + wall_s:
            raise watch.lost(wall_code, f"{what}이 {wall_s}초({wall_knob})를 넘겼다")
        why = should_stop() if should_stop is not None else None
        if why:
            raise watch.lost("cancelled", f"{why} — 진행 중 {what}을 닫았다")
        watch.frame(name, data)
        yield name, data


def collect_stream(frames: Iterable[tuple[str, dict]]) -> dict:
    """심의 SSE 프레임을 러너 계약 dict 로 모은다(plan §6.7.2 7단계 표).

    반환 {decision_text, turns, events, report_id, pat_degraded}. `error` 프레임은 EngineError 로 올린다 — 의장이
    결정문을 못 낸 것(NO_DECISION_CODES)은 그때까지 받은 것을 실은 EngineNoDecision 으로 가른다.

    자르지 않는다(WP1 S13 · 사용자 지침 가). 발언은 엔진이 줄이기 전의 원문(`say_full`)을 받는다 — `say` 는 회의 버블용으로
    줄인 글이라 뒤쪽 인용이 좌석 원장에서 사라졌다(R-63). 엔진이 '못 실었다' 고 알린 사유와 고칠 설정(`knob`)도 통째로
    남긴다(종전 200자 · knob 버림). events 는 건수 상한(400)에서 말없이 멈추지 않는다 — 뒤 좌석의 도구 사용이 0 으로 세졌다.
    지식카드 상태줄의 집계(`knowledge` — 좌석·실은 줄 수·강등·검색어 출처)를 남겨 좌석 귀속이 읽는다(R-43).
    """
    decision_text = ""
    result_text = ""
    turns: list[dict] = []
    events: list[dict] = []
    report_id: Any = None
    pat_degraded = False
    error: str | None = None
    error_code = ""
    error_knob: str | None = None

    def add(event: Mapping[str, Any]) -> None:
        events.append(dict(event))

    for name, data in frames:
        if name == "status":
            item = {"kind": "status", "step": _text(data.get("step")) or "", "tool": _text(data.get("tool"))}
            knowledge = data.get("knowledge")
            if isinstance(knowledge, Mapping) and knowledge.get("persona"):
                item["knowledge"] = {k: knowledge.get(k) for k in ("persona", "hits", "degraded", "query")}
            add(item)
        elif name == "delib":
            kind = str(data.get("kind") or "")
            if kind == "turn":
                full = data.get("say_full")
                turns.append({
                    "round": data.get("round"),
                    "persona": data.get("persona"),
                    "say": str(full if isinstance(full, str) and full else (data.get("say") or "")),
                    "stance": data.get("stance"),
                    "position": data.get("position"),
                })
                add({"kind": "turn", "persona": _text(data.get("persona")), "round": data.get("round")})
            elif kind == "evidence":
                # included 는 세 값이다 — 엔진은 늘 싣지만 없는 근거(REST·MCP 로 들어온 옛 events)를 실패로 읽지 않게 그대로 둔다.
                item = {"kind": "evidence", "source": _text(data.get("source")) or "",
                        "included": data.get("included") if isinstance(data.get("included"), bool) else None}
                # 엔진이 좌석에 주지 않았다고 알린 카드는 사유 문장과 고칠 설정을 같이 남긴다 — 러너가 패널에 옮겨 적는다
                # (runner.withheld_by_engine). 실린 근거의 본문은 싣지 않는다 — events[] 는 압축 로그다.
                if item["included"] is False and data.get("text"):
                    item["note"] = _text(data.get("text"))
                if item["included"] is False and data.get("knob"):
                    item["knob"] = _text(data.get("knob"))
                add(item)
            elif kind == "personas":
                add({"kind": "personas", "personas": [
                    {"key": _text(p.get("key")), "origin": _text(p.get("origin"))}
                    for p in (data.get("personas") or ()) if isinstance(p, Mapping)
                ]})
            elif kind == "decision":
                decision_text = str(data.get("text") or "")
            elif kind == "outcome":
                report_id = data.get("report_id")
        elif name == "result":
            if isinstance(data.get("content"), str):
                result_text = data["content"]
        elif name == "warning":
            code = str(data.get("code") or "")
            if code in PAT_DEGRADED_CODES:
                pat_degraded = True
            warning = {"kind": "warning", "code": code}
            for key in ("message", "knob"):
                if data.get(key):
                    warning[key] = _text(data.get(key))
            add(warning)
        elif name == "error":
            error_code = str(data.get("code") or "error")
            error = str(data.get("message") or "")
            # 엔진은 화면에 뜨는 글에 설정 이름을 넣지 않고 knob 으로 따로 싣는다 — 버리면 어느 값을 올릴지 모른다.
            error_knob = _text(data.get("knob"))
        elif name == "done":
            break

    if error is not None:
        if error_code in NO_DECISION_CODES:
            # 이 프레임은 맨 끝에 온다 — 발언·보고서 번호·결정문 자리의 글(좌석별 마지막 입장)을 다 받은 뒤다.
            raise EngineNoDecision(error_code, error, knob=error_knob, report_id=report_id, turns=turns,
                                   decision_text=decision_text or result_text)
        raise EngineError(f"{error_code}: {error}".strip() + (f" — 설정 {error_knob}" if error_knob else ""))
    return {
        "decision_text": decision_text or result_text,
        "turns": turns,
        "events": events,
        "report_id": report_id,
        "pat_degraded": pat_degraded,
    }


# ---------------------------------------------------------------- (A) 포털 경로
class PortalPanelEngine:
    """앱 → 포털 `POST {HWAXRISK_PORTAL_BASE}/agent/chat`(SSE) — plan §6.7.1 확정 경로 (A).

    자격은 러너가 넘긴 사람(잡이 요청자 자격으로 집혔으면 요청자, 아니면 타깃 owner)이 등록한 포털 PAT 하나다
    (runner.resolve_credential 과 같은 규칙·같은 수명 여유). 없으면 `PatUnavailable` 이고 요청을 하나도 보내지 않는다 — 서비스
    계정 PAT 로 내려가지 않는다(U-3). 좌석 도구 스코핑은 포털이 검증한 PAT 의 groups 로 강제된다 — 앱은 그룹을 자칭하지 않는다.
    """

    def __init__(self, store: Any, settings: Any, *, transport: httpx.BaseTransport | None = None,
                 owner_sub: str | None = None) -> None:
        self.store = store
        self.settings = settings
        self.owner_sub = owner_sub
        # 테스트가 httpx.MockTransport 를 꽂는 자리. None 이면 실제 네트워크.
        self.transport = transport

    # -- 자격 -----------------------------------------------------------------
    def _credential(self, owner_sub: str | None) -> dict:
        if owner_sub and self.store is not None:
            row = self.store.get_credential(owner_sub)
            # 복호는 identity 가 한다 — 키 없음·폐기 표기·손상은 None 이다(§8.2.7).
            pat = identity.credential_pat(row)
            if pat and int(row.get("pat_exp") or 0) > now_epoch() + config.credential_margin_s(self.settings):
                try:
                    groups = json.loads(row.get("pat_groups_json") or "[]")
                except ValueError:
                    groups = []
                return {"kind": "owner", "pat": pat, "email": row.get("pat_email"),
                        "groups": groups if isinstance(groups, list) else []}
        # 서비스 PAT 가 설정돼 있어도 쓰지 않는다(U-3) — 서비스 시야로 돈 패널은 겉으로 정상인데 결과가 그 사람의 것이 아니다.
        raise PatUnavailable(f"패널 자격이 없습니다 — {owner_sub or '(사람 없음)'} 의 포털 PAT 가 없거나 쓸 수 없거나 남은 수명이"
                             f" 패널 여유 {config.credential_margin_s(self.settings)}초에 못 미칩니다. "
                             + pat_unavailable_guidance(self.store, owner_sub))

    def _base(self) -> str:
        return str(self.settings.portal_base).rstrip("/")

    def _client(self, timeout: httpx.Timeout | float) -> httpx.Client:
        return http_client(transport=self.transport, timeout=timeout)

    # -- 4단계 대화 생성(비치명) ------------------------------------------------
    def create_conversation(self, pat: str, title: str) -> str | None:
        """포털 대화 1건. 4xx·연결 실패면 None 이고 패널은 그대로 진행한다(plan §6.7.2 4단계).

        한도는 5초였다 — 부하 걸린 포털이 그 안에 답하지 못하면 패널이 대화 없이 돌아, 몇 시간짜리 심의의 발언이
        포털에 한 줄도 남지 않았다(끊겼을 때 부분 결과가 남는 자리는 거기뿐이다). 죽은 포털은 connect 가 잡는다.
        """
        body = {"title": str(title)[:CONVERSATION_TITLE_MAX], "kind": CONVERSATION_KIND,
                "source": CONVERSATION_SOURCE}
        limit = float(getattr(self.settings, "risk_portal_call_timeout_s", config.DEFAULT_PORTAL_CALL_TIMEOUT_S))
        try:
            with self._client(httpx.Timeout(limit, connect=CONNECT_TIMEOUT_S)) as client:
                r = client.post(self._base() + CONVERSATIONS_PATH, json=body,
                                headers={"Authorization": f"Bearer {pat}"})
        except httpx.TimeoutException as exc:
            log.warning("대화 생성 %g초 초과(HWAXRISK_PORTAL_CALL_TIMEOUT_S, %s) — 이 패널은 포털 대화 없이 돈다",
                        limit, type(exc).__name__)
            return None
        except httpx.HTTPError as exc:
            log.warning("대화 생성 실패(비치명): %s", type(exc).__name__)
            return None
        if r.status_code != 200:
            log.warning("대화 생성 거부(비치명): HTTP %s", r.status_code)
            return None
        try:
            return str(r.json().get("id") or "") or None
        except ValueError:
            return None

    # -- 1단계 model 스냅샷 ----------------------------------------------------
    def health(self) -> dict:
        """agent-server `GET /health` — runner.snapshot_model 이 D6 model_json 을 채운다. 불통이면 예외."""
        return self._health_view(self._health_info())

    def _health_info(self) -> dict:
        """agent-server `GET /health` 의 본문 그대로(객체). 불통이면 예외."""
        base = str(getattr(self.settings, "agent_url", "") or DEFAULT_AGENT_URL).rstrip("/")
        with self._client(HEALTH_TIMEOUT_S) as client:
            r = client.get(base + "/health")
        r.raise_for_status()
        info = r.json()
        if not isinstance(info, dict):
            raise EngineError("agent-server /health 응답이 객체가 아닙니다.")
        return info

    def drain_state(self) -> dict:
        """에이전트 서버 비우기(M3.md 4.7) — `/health` 의 `drain{on, scope, until, …}` 와 `draining`. 러너는 `on` 이면 범위와
        상관없이 패널을 집지 않는다(#50). 그 칸이 없는 옛 서버면 `on: false` 다. 불통이면 예외(러너가 비우지 않는 것으로 본다)."""
        info = self._health_info()
        drain = info.get("drain") if isinstance(info.get("drain"), Mapping) else {}
        return {"on": bool(drain.get("on") or info.get("draining")), "scope": drain.get("scope"),
                "until": drain.get("until"), "reason": drain.get("reason")}

    @staticmethod
    def _health_view(info: Mapping[str, Any]) -> dict:
        """/health 본문 → 패널 model_json 의 칸."""
        vllm = info.get("vllm")
        endpoint_host = None
        if isinstance(vllm, str) and "://" in vllm:
            endpoint_host = urlsplit(vllm).hostname
        elif isinstance(vllm, Mapping):
            base_url = str(vllm.get("base_url") or "")
            endpoint_host = urlsplit(base_url).hostname if "://" in base_url else None
        return {
            "model": info.get("model") or "unknown",
            "provider": info.get("provider") or "vllm",
            "endpoint_host": endpoint_host,
            "engine_rev": info.get("engine_rev") or info.get("version"),
            # 좌석 계약(chair) 상수의 해시·샘플링 설정은 엔진만 안다 — 실어 보내면 그대로 옮긴다(§6.7.2 1단계).
            "chair_rev": info.get("chair_rev"),
            "sampling": info.get("sampling"),
            "vllm": vllm,
            # 엔진이 제 모델 창에서 유도한 근거 예산(자, 1백만 토큰 창이면 천장 500,000) — 브리프 크기의 원천이다(WP1 S9).
            # 정수가 아니면(옛 엔진) None — 러너가 바닥 프로파일로 떨어진다.
            "evid_budget": (info.get("evid_budget") if isinstance(info.get("evid_budget"), int)
                            and not isinstance(info.get("evid_budget"), bool) else None),
        }

    # -- 6·7단계 엔진 호출·SSE 캡처 ---------------------------------------------
    def run(self, delib_opts: Mapping[str, Any], *, owner_sub: str | None = None,
            on_progress: Callable[[Mapping[str, Any]], None] | None = None,
            conversation: tuple[str, str] | None = None,
            should_stop: Callable[[], str | None] | None = None) -> dict:
        """패널 1건을 돌리고 {decision_text, turns, conv_id, events, …} 를 돌려준다.

        429(포털 agent_semaphore 초과)는 `EngineBusy` 라 러너가 대기 후 다시 묻는다 — 그때 러너는 그 예외의
        `conversation`(대화 id, 만든 자격)을 되돌려 주고, 같은 자격이면 그 대화를 다시 쓴다. 연결 실패·error 프레임은
        `EngineError` 다. 앱이 스트림을 놓은 것(패널 벽시계·줄 사이 침묵·중간 절단, 그리고 `should_stop` 이 알린
        취소·정지)은 `EngineStreamLost` 로 가른다 — 그때 엔진은 심의를 계속 돌릴 수 있다. 의장이 결정문을 못 낸 것은
        `EngineNoDecision` 이고 그 심의의 대화를 실어 올린다. 자격이 없으면 `PatUnavailable` 이다.
        """
        opts = {k: v for k, v in dict(delib_opts).items() if k != "question"}
        question = str(delib_opts.get("question") or "")
        credential = self._credential(owner_sub if owner_sub is not None else self.owner_sub)
        # 429 뒤의 재시도는 앞 시도가 만든 대화를 다시 쓴다 — 시도마다 만들면 패널 하나가 빈 대화를 시도 수만큼 남긴다.
        # 다만 그 사이 자격이 바뀌었으면(그 사람이 PAT 를 다시 등록했다) 새로 만든다 —
        # 포털은 남의 대화에 저장하는 것을 말없이 건너뛰어, 그대로 쓰면 이 패널의 발언이 포털에 남지 않는다.
        made_by = f"{credential['kind']}:{credential['email'] or ''}"
        if conversation and conversation[1] == made_by:
            conv_id: str | None = conversation[0]
        else:
            conv_id = self.create_conversation(credential["pat"], f"[리스크심사] {question[:160]}")

        # 줄 사이 침묵 한도. 종전에는 '엔진 호출당 타임아웃 1800 + 60' 으로 유도했다 — LLM 시도 한 번만 가정한 값이라
        # 엔진이 SDK 재시도를 하거나 박스의 호출 한도를 올리면 건강한 패널을 끊었다. 이제는 죽은 스트림만 잡는
        # 마지막 그물이다(엔진이 15초마다 ping 을 흘린다). 0 이면 끈다.
        read_s = float(getattr(self.settings, "risk_engine_read_timeout_s", config.DEFAULT_ENGINE_READ_TIMEOUT_S))
        timeout = httpx.Timeout(connect=CONNECT_TIMEOUT_S, read=read_s or None,
                                write=WRITE_TIMEOUT_S, pool=POOL_TIMEOUT_S)
        wall_s = config.panel_timeout_s(self.settings)
        watch = _StreamWatch(conv_id, on_progress)
        streaming = False
        body: dict[str, Any] = {
            "message": DELIBERATE_TRIGGER + question,
            "history": [],
            "delib_opts": opts,
        }
        if conv_id:
            body["conversation_id"] = conv_id
        headers = {"Authorization": f"Bearer {credential['pat']}", "Accept": "text/event-stream"}

        try:
            with self._client(timeout) as client:
                with client.stream("POST", self._base() + CHAT_PATH, json=body, headers=headers) as response:
                    if response.status_code == 429:
                        raise EngineBusy("포털 agent_semaphore 초과(429)",
                                         conversation=(conv_id, made_by) if conv_id else None)
                    if response.status_code in (401, 403):
                        response.read()
                        # 자격 문제라 폴백하지 않는다 — 잡을 pat_unavailable 로 멈춘다(plan §6.7.1 폴백 규칙).
                        raise PatUnavailable(f"포털이 러너 자격을 거부했습니다 — HTTP {response.status_code}")
                    if response.status_code >= 400:
                        response.read()
                        raise EngineError(f"포털이 심의를 거부했습니다 — HTTP {response.status_code}")
                    streaming = True
                    result = collect_stream(_watched(parse_sse(response.iter_lines()), wall_s, watch, should_stop))
        except PatUnavailable:
            raise
        except EngineNoDecision as exc:
            exc.conv_id = conv_id                  # 그 심의의 발언 전부가 남은 포털 대화다
            raise
        except httpx.ReadTimeout as exc:
            raise watch.lost(
                "engine_silent", f"포털 스트림이 {read_s:g}초 동안 조용했다(HWAXRISK_ENGINE_READ_TIMEOUT_S)") from exc
        except httpx.HTTPError as exc:
            # 응답이 흐르던 중의 끊김은 엔진까지 간 심의다 — 연결조차 못 한 것(아래 EngineError)과 가른다.
            if streaming and isinstance(exc, (httpx.RemoteProtocolError, httpx.ReadError)):
                raise watch.lost(
                    "engine_stream_cut", f"스트림이 중간에 끊겼다({type(exc).__name__}, nginx"
                    " NGINX_AGENT_READ_TIMEOUT 또는 포털·에이전트 서버 재기동)") from exc
            raise EngineError(f"포털 /agent/chat 호출 실패({type(exc).__name__})") from exc

        result["conv_id"] = conv_id
        if conv_id is None:
            result["conv_missing"] = True
        result["call_path"] = "portal"
        result["credential"] = credential["kind"]
        if credential["groups"]:
            result["call_groups"] = list(credential["groups"])
        return result


def build_engine(store: Any, settings: Any) -> PortalPanelEngine:
    """main.py lifespan 이 러너에 주입하는 기본 엔진(경로 (A))."""
    return PortalPanelEngine(store, settings)


# ---------------------------------------------------------------- 카드 대조(M2.md 4.2~4.4 · m2-wp3b S7) — 대화 없이 card-review 넷
REVIEW_PATH = "/agent/card-review"
# 단발 셋(limits·pack·plan)의 읽기 한도 — 포털 단발 한도(AGENT_UNARY_TIMEOUT_S 600초)보다 조금 크게 둬 포털의 504 agent_timeout 이
# 먼저 온다(그쪽이 고칠 손잡이를 말한다). 이 한도에 걸린 것은 포털이 멈춘 것이다.
REVIEW_UNARY_READ_S = 660.0
REVIEW_WHAT = "카드 대조 호출"
REVIEW_WALL_CODE = "review_timeout"
REVIEW_WALL_KNOB = "HWAXRISK_REVIEW_CALL_TIMEOUT_S"
REVIEW_READ_KNOB = "HWAXRISK_REVIEW_READ_TIMEOUT_S"


class _ReviewWatch(_StreamWatch):
    """카드 대조 스트림 한 건 — 대화가 없고, 닫으면 엔진이 그 LLM 호출을 거둔다(분리 태스크가 아니다)."""

    def __init__(self, on_progress: Callable[[Mapping[str, Any]], None] | None = None) -> None:
        super().__init__(None, on_progress)

    def frame(self, name: str, data: Mapping[str, Any]) -> None:
        # 엔진의 status 는 {step:"attempt", n} 이다 — 몇 번째 시도인지까지 마지막 단계로 적는다(보충 시도가 보이게).
        if name == "status" and data.get("step") and data.get("n") is not None:
            data = {**data, "step": f"{data['step']} {data['n']}"}
        super().frame(name, data)

    def lost(self, code: str, message: str) -> EngineStreamLost:
        return EngineStreamLost(
            code, f"{message} — 경과 {now_epoch() - self.started}초, 마지막 단계 {self.last_step or '없음'}."
                  " 스트림을 닫았으므로 엔진은 그 LLM 호출을 거둔다")


def _flag(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _review_error(code: str | None, message: str, data: Mapping[str, Any], *, status: int | None = None,
                  retry_after: Any = None) -> Exception:
    """거절 하나(스트림 전 응답 또는 error 프레임) → 예외. 이름은 `review_ops.classify` 가 정한다(코드가 없으면 상태로).

    기다림 부류는 `EngineBusy`(retry_after_s 는 classify 가 묶은 값), `credential` 보류는 `PatUnavailable`(서비스 계정으로 내려가지
    않는다), 나머지는 `EngineRejected` 다 — 받은 코드 원문·엔진의 infra·retryable 비트·knob·본문을 그대로 싣는다.
    """
    wait = data.get("retry_after_s", retry_after)
    outcome = review_ops.classify(code, http_status=status, retry_after_s=wait)
    text = message or (f"HTTP {status}" if status is not None else "")
    if outcome.klass == review_ops.WAIT:
        return EngineBusy(f"{outcome.code}: {text}", retry_after_s=outcome.retry_after_s, code=outcome.code)
    if outcome.hold_code == "credential":
        return PatUnavailable(f"{outcome.code}: {text}", code=outcome.code)
    detail = {**dict(data), **({"http_status": status} if status is not None else {})}
    return EngineRejected(outcome.code, text, infra=_flag(data.get("infra")), retryable=_flag(data.get("retryable")),
                          knob=_text(data.get("knob")), detail=detail)


def _review_rejection(response: httpx.Response) -> Exception:
    """200 이 아닌 응답(본문까지 읽은 것) → 예외. 본문의 `code` 가 정본이다(최상위, 또는 FastAPI `detail` 객체 안).

    포털 403(권한 문)·401(PAT 거절)과 옛 포털의 404 는 본문이 `{detail: 글}` 이라 코드가 없다 — 상태로 가른다(D-28 ·
    `review_ops.classify` 의 상태표: 401 credential_rejected · 403 denied · 404 agent_outdated · 5xx portal_5xx).
    """
    try:
        body: Any = response.json()
    except ValueError:
        body = None
    if isinstance(body, Mapping) and isinstance(body.get("detail"), Mapping):
        body = body["detail"]
    data = dict(body) if isinstance(body, Mapping) else {}
    raw = data.get("code")
    code = raw.strip() if isinstance(raw, str) and raw.strip() else None
    message = data.get("message") or data.get("detail")
    return _review_error(code, str(message) if message else "", data, status=response.status_code,
                         retry_after=response.headers.get("retry-after"))


def collect_review_stream(frames: Iterable[tuple[str, dict]]) -> dict:
    """카드 대조 run 의 SSE 프레임 → result 프레임 그대로(M2.md 4.3). 줄이거나 고치지 않는다 — 행 회계는 review_verify 몫이다.

    status·ping 은 진행 신호일 뿐이다(`_watched` 가 센다). 첫 `error` 프레임이 결말이다(`_review_error` — 스트림의 `review_busy` 는
    기다림). `done` 없이 끝난 스트림은 `engine_stream_cut`(인프라 — 같은 호출을 다시 낸다), `done` 까지 왔는데 result 가 없거나
    `rows` 가 목록이 아니면 `review_parse_failed`(내용 탓)다.
    """
    result: Any = None
    error: Mapping[str, Any] | None = None
    done = False
    for name, data in frames:
        if name == "result" and result is None and error is None:
            result = data
        elif name == "error" and error is None:
            error = data
        elif name == "done":
            done = True
            break
    if error is not None:
        code = error.get("code")
        raise _review_error(str(code).strip() if code else None, str(error.get("message") or ""), error)
    if not done:
        raise EngineStreamLost("engine_stream_cut", "카드 대조 스트림이 done 프레임 없이 끝났다(포털·에이전트 서버 재기동 또는"
                                                    " 연결 끊김) — 같은 호출을 다시 낸다")
    if not isinstance(result, dict) or not isinstance(result.get("rows"), list):
        raise EngineRejected("review_parse_failed", "done 까지 왔는데 result 프레임이 없거나 rows 가 목록이 아니다",
                             detail={"result": result})
    return result


def review_outcome(exc: BaseException, *, timeouts_before: int = 0) -> review_ops.Outcome:
    """검토 엔진 예외 → `review_ops.classify` 의 부류(셀·잡이 할 일). 검토 러너는 이것 하나로 가른다.

    `timeouts_before` 는 같은 호출이 앞서 호출 벽시계(`review_timeout`)에 걸린 횟수다 — 두 번째부터 내용 탓이다.
    """
    if isinstance(exc, EngineBusy):
        return review_ops.classify(exc.code or "engine_busy", retry_after_s=exc.retry_after_s)
    if isinstance(exc, PatUnavailable):
        return review_ops.classify(exc.code)
    if isinstance(exc, EngineRejected):
        return review_ops.classify(exc.code, knob=exc.knob, timeouts_before=timeouts_before)
    if isinstance(exc, EngineStreamLost):
        return review_ops.classify(exc.code, timeouts_before=timeouts_before)
    raise TypeError(f"카드 대조 엔진 예외가 아니다 — {type(exc).__name__}")


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _review_health(info: Mapping[str, Any]) -> dict:
    """/health 의 카드 대조 칸(M2.md 4.1 — `review_active` · `capabilities:["card_review"]` · `card_review{…}`) → 러너가 보는 것.

    `capable` 이 거짓이면 그 에이전트 서버에 카드 대조가 없다(옛 판이거나 모듈을 못 붙였다 — 사유는 `error`). `limit` 은 서버 관문의
    지금 상한(심의가 돌면 줄어든다), `active` 는 지금 도는 카드 대조 호출 수다. 모르면 None 이다(0 으로 치지 않는다).
    """
    caps = info.get("capabilities")
    block = info.get("card_review")
    block = block if isinstance(block, Mapping) else {}
    return {"capable": isinstance(caps, list) and "card_review" in caps,
            "active": _int_or_none(info.get("review_active")),
            "limit": _int_or_none(block.get("limit")),
            "limit_reason": _text(block.get("limit_reason")),
            "request_worst_s": _int_or_none(block.get("request_worst_s")),
            "error": _text(block.get("error"))}


class PortalReviewEngine(PortalPanelEngine):
    """앱 → 포털 `/agent/card-review/{limits,pack,plan,run}` — 카드 대조(M2.md 4.2~4.4). 포털 대화를 만들지 않는다(나갈 기준 3).

    자격은 부를 때마다 `email` 의 사람이 등록한 포털 PAT 하나다(`_review_credential`). 패널 경로(`_credential`)와 달리 서비스
    PAT 로 내려가지 않는다(사용자 결정 3) — 없거나 남은 수명이 여유 밑이면 `PatUnavailable` 이고 요청을 하나도 보내지 않는다.
    포털이 그 PAT 로 신원 칸 넷(groups·user_email·user_pat·entitlements)을 덮어쓴다 — 앱은 신원을 자칭하지 않는다.
    """

    # -- 자격 -----------------------------------------------------------------
    def _review_credential(self, email: str | None) -> dict:
        """그 사람이 등록한 포털 PAT — 없거나 폐기·복호 실패면 `pat_unavailable`, 남은 수명이 `review_credential_margin_s`
        (호출 벽시계 + 600초) 이하면 `credential_expired` 다. 둘 다 `PatUnavailable` 이고 서비스 PAT 를 보지 않는다."""
        row = self.store.get_credential(email) if email and self.store is not None else None
        pat = identity.credential_pat(row)
        if not pat:
            raise PatUnavailable(f"카드 대조 자격이 없습니다 — {email or '(이메일 없음)'} 이 등록한 포털 PAT 가 없거나 쓸 수 없습니다."
                                 " 포털에서 PAT 를 다시 발급해 등록하고 재개합니다(서비스 계정으로 내려가지 않습니다).",
                                 code="pat_unavailable")
        left = int(row.get("pat_exp") or 0) - now_epoch()
        margin = config.review_credential_margin_s(self.settings)
        if left <= margin:
            raise PatUnavailable(f"카드 대조 자격의 남은 수명 {max(left, 0)}초가 여유 {margin}초(HWAXRISK_REVIEW_CALL_TIMEOUT_S"
                                 " + 600) 이하입니다 — 호출 하나가 도는 사이 만료될 수 있습니다. 포털에서 PAT 를 다시 발급해"
                                 " 등록하고 재개합니다(서비스 계정으로 내려가지 않습니다).", code="credential_expired")
        return {"pat": pat, "email": row.get("pat_email") or email}

    def _review_url(self, route: str) -> str:
        return f"{self._base()}{REVIEW_PATH}/{route}"

    # -- 단발 셋 -----------------------------------------------------------------
    def _unary(self, method: str, route: str, body: Mapping[str, Any] | None, email: str) -> dict:
        credential = self._review_credential(email)
        timeout = httpx.Timeout(REVIEW_UNARY_READ_S, connect=CONNECT_TIMEOUT_S, write=WRITE_TIMEOUT_S, pool=POOL_TIMEOUT_S)
        where = f"{REVIEW_PATH}/{route}"
        try:
            with self._client(timeout) as client:
                r = client.request(method, self._review_url(route), headers={"Authorization": f"Bearer {credential['pat']}"},
                                   json=dict(body) if body is not None else None)
        except httpx.TimeoutException as exc:
            raise EngineRejected("portal_unreachable", f"포털 {where} 가 답하지 않았다({type(exc).__name__}, 읽기 한도"
                                 f" {REVIEW_UNARY_READ_S:g}초)", infra=True, retryable=True) from exc
        except httpx.HTTPError as exc:
            raise EngineRejected("portal_unreachable", f"포털 {where} 호출 실패({type(exc).__name__})",
                                 infra=True, retryable=True) from exc
        if r.status_code != 200:
            raise _review_rejection(r)
        try:
            out = r.json()
        except ValueError:
            out = None
        if not isinstance(out, dict):
            raise EngineRejected("review_parse_failed", f"포털 {where} 의 200 응답이 JSON 객체가 아니다",
                                 detail={"http_status": 200})
        return out

    def limits(self, *, email: str) -> dict:
        """이 박스의 예산과 판(M2.md 4.2) — 응답 그대로."""
        return self._unary("GET", "limits", None, email)

    def pack(self, agent_key: str, *, email: str) -> dict:
        """그 전문가의 지식카드 전부 → 정규 팩(응답 그대로 — 확인·동결은 cardpack 몫). 엔진은 이 사람의 PAT 로만 카드를 받는다."""
        return self._unary("POST", "pack", {"agent_key": agent_key}, email)

    def plan(self, body: Mapping[str, Any], *, email: str) -> dict:
        """카드 묶음·목록 쪽 나누기. 요청은 `{cards[{alias, record_id, checkable, chars}], units[{unit_id, manifest_chars,
        body_chars}], expect?}` 이다 — `agent_key` 를 싣지 않는다(엔진 요청 모델에 그 칸이 없어 422 unknown_fields 다).

        응답에는 늘 `pair_over` 가 있다(M2.md 4.2 — 묶음째로는 창을 넘는 (묶음, 단위) 짝). 없으면 그 짝을 모르는 옛 에이전트
        서버다 — 그대로 쓰면 그 짝의 run 이 over_budget 으로 잡을 멈추므로 `agent_outdated` 로 올린다.
        """
        out = self._unary("POST", "plan", body, email)
        if not isinstance(out.get("pair_over"), list):
            raise EngineRejected("agent_outdated", "plan 응답에 pair_over 가 없다 — 묶음째로 창을 넘는 짝을 알리지 않는 옛 에이전트"
                                 " 서버다. 에이전트 서버를 카드 대조 판(cr-1, RB-7 이후)으로 올리고 다시 띄운다",
                                 detail={"http_status": 200, "keys": sorted(out)})
        return out

    # -- 스트림 --------------------------------------------------------------------
    def run(self, body: Mapping[str, Any], *, email: str,  # type: ignore[override] — 패널 run 과 다른 계약(ReviewEngine)
            on_progress: Callable[[Mapping[str, Any]], None] | None = None,
            should_stop: Callable[[], str | None] | None = None) -> dict:
        """카드 대조 호출 한 건(SSE) → result 프레임 그대로. 대화를 만들지 않고 본문에 `conversation_id` 를 싣지 않는다.

        줄 사이 침묵 한도는 `HWAXRISK_REVIEW_READ_TIMEOUT_S`(엔진 ping 15초 — 죽은 연결이 자리를 붙들지 않게), 호출 하나의
        벽시계는 `HWAXRISK_REVIEW_CALL_TIMEOUT_S` 다(엔진의 요청 최악보다 길다). 둘 다 0 이면 재지 않는다.
        """
        credential = self._review_credential(email)
        read_s = float(config.review_read_timeout_s(self.settings))
        timeout = httpx.Timeout(connect=CONNECT_TIMEOUT_S, read=read_s or None, write=WRITE_TIMEOUT_S, pool=POOL_TIMEOUT_S)
        wall_s = config.review_call_timeout_s(self.settings)
        watch = _ReviewWatch(on_progress)
        headers = {"Authorization": f"Bearer {credential['pat']}", "Accept": "text/event-stream"}
        streaming = False
        try:
            with self._client(timeout) as client:
                with client.stream("POST", self._review_url("run"), json=dict(body), headers=headers) as response:
                    if response.status_code != 200:
                        response.read()
                        raise _review_rejection(response)
                    streaming = True
                    return collect_review_stream(_watched(
                        parse_sse(response.iter_lines()), wall_s, watch, should_stop,
                        wall_code=REVIEW_WALL_CODE, wall_knob=REVIEW_WALL_KNOB, what=REVIEW_WHAT))
        except httpx.ReadTimeout as exc:
            raise watch.lost("engine_silent", f"카드 대조 스트림이 {read_s:g}초 동안 조용했다({REVIEW_READ_KNOB})") from exc
        except httpx.HTTPError as exc:
            if streaming and isinstance(exc, (httpx.RemoteProtocolError, httpx.ReadError)):
                raise watch.lost("engine_stream_cut", f"스트림이 중간에 끊겼다({type(exc).__name__} — 포털·에이전트 서버 재기동"
                                                      " 또는 연결 끊김)") from exc
            raise EngineRejected("portal_unreachable", f"포털 {REVIEW_PATH}/run 호출 실패({type(exc).__name__})",
                                 infra=True, retryable=True) from exc

    # -- 서버 관문 -------------------------------------------------------------------
    def health(self) -> dict:
        """패널 health() 에 카드 대조 칸 `card_review{capable, active, limit, limit_reason, request_worst_s, error}` 를 더한다."""
        info = self._health_info()
        return {**self._health_view(info), "card_review": _review_health(info)}


# ---------------------------------------------------------------- 카드 대조 요청 본문(M2.md 4.3 — 엔진 요청 모델의 안쪽 항목 모양)
# 엔진은 안쪽 항목까지 선언 밖 칸을 422 unknown_fields 로 거절한다(RB-4). 원장·택소노미의 행을 그대로 실으면 칸 이름이 다르다
# (택소노미 영역은 code·ecad_dependent, 메커니즘은 description·status… — 엔진은 {key, label}·{code, label} 만 받는다). 그래서 모양은
# 여기 한 곳에서 짓는다. 고르는 것(어느 카드·단위·이미 낸 판정을 실을지)은 검토 루프 몫이다. 단위(`units.review_payload`)·목록 쪽
# (`units.manifest_items`)·카드(`cardpack.cards_for`)는 생산자 출력 그대로 싣는다 — 줄이거나 칸을 걸러 맞추지 않는다(C7 시험이
# 엔진의 검증기로 본다).
def review_domains(cfg: Any = None) -> list[dict]:
    """`extra.domains` — 로스터 영역(`HWAXRISK_ROSTER_DOMAINS`, 기본 15개)을 택소노미 라벨과 함께 `{key, label}` 로. 택소노미의
    `code` 를 `key` 로 보낸다(엔진 DomainItem — h 줄의 `to` 가 고르는 닫힌 집합). 택소노미에 없는 영역은 라벨 없이 싣는다."""
    cfg = config.settings if cfg is None else cfg
    labels = {str(d.get("code")): d.get("label") for d in taxonomy.load_taxonomy()["axes"]["domain"]}
    return [{"key": code, **({"label": str(labels[code])} if labels.get(code) else {})}
            for code in getattr(cfg, "risk_roster_domains", ())]


def review_mechanisms() -> list[dict]:
    """`extra.mechanisms` — 택소노미 메커니즘 가운데 active 인 것을 `{code, label}` 로(f 줄 mech·m 줄 seen 이 고르는 닫힌 집합)."""
    return [{"code": str(m["code"]), "label": str(m.get("label") or "")}
            for m in taxonomy.load_taxonomy()["axes"]["mechanism"] if m.get("status", "active") == "active"]


def run_body(kind: str, *, target_key: str, pack: cardpack.FrozenPack, cards: Sequence[str] = (),
             variant: str | None = None, digest: Sequence[str] = (), unit: Mapping[str, Any] | None = None,
             manifest: Sequence[Mapping[str, Any]] = (), known: Sequence[Mapping[str, Any]] = (),
             expect: Mapping[str, Any] | None = None, cfg: Any = None) -> dict:
    """카드 대조 run 요청 하나(M2.md 4.3). 신원 칸 넷은 싣지 않는다(포털이 덮어쓴다).

    - `pack` — 얼린 팩. `expert` 는 그 팩의 {agent_key, name, domain, role}, `cards` 는 별칭 순서대로 팩 항목 그대로
      (`cardpack.cards_for` — rev 도 뒤집지 않는다, 엔진이 뒤집는다), `digest` 는 별칭의 {alias, type, title, record_id, card_id}.
    - `unit` 은 `units.review_payload` 의 출력, `manifest` 는 `units.manifest_items` 의 한 쪽이다 — 둘 다 그대로 싣는다.
    - `known` 은 이미 낸 판정 행에서 {alias, judgement, why} 만(엔진 KnownItem), `extra.domains`·`mechanisms` 는 위 둘이다.
    - `expect` 는 준 것만 싣는다(엔진은 실린 판만 견준다).
    """
    body: dict[str, Any] = {
        "kind": kind, "variant": variant, "target_key": target_key,
        "expert": {"key": pack.agent_key, "name": str(pack.raw.get("name") or ""),
                   "domain": str(pack.raw.get("domain") or ""), "role": pack.role},
        "cards": cardpack.cards_for(pack, cards),
        "digest": [{"alias": alias, "type": _text(pack.cards[alias].get("type")),
                    "title": _text(pack.cards[alias].get("title")), "record_id": _text(pack.cards[alias].get("record_id")),
                    "card_id": _text(pack.cards[alias].get("card_id"))} for alias in digest],
        "unit": copy.deepcopy(dict(unit)) if unit is not None else None,
        "manifest": [copy.deepcopy(dict(item)) for item in manifest],
        "extra": {"domains": review_domains(cfg), "mechanisms": review_mechanisms(),
                  "known": [{"alias": str(row.get("alias") or ""), "judgement": _text(row.get("judgement")),
                             "why": _text(row.get("why"))} for row in known]},
    }
    if expect:
        body["expect"] = {k: expect[k] for k in ("prompt_rev", "limits_rev") if expect.get(k) is not None}
    return body


def build_review_engine(store: Any, settings: Any) -> PortalReviewEngine:
    """검토 러너(S8)에 주입하는 카드 대조 엔진 — 운영 코드에 가짜로 바꾸는 손잡이는 없다(D-15, 가짜는 tests/synth 에만)."""
    return PortalReviewEngine(store, settings)
