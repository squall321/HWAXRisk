# 심의 엔진 클라이언트 — 포털 /agent/chat 의 SSE 를 러너 계약 {decision_text, turns, conv_id, events} 로 옮긴다(plan §6.7.1 (A))
from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

from app import config, identity
from app.common import now_epoch

# 프로토콜·예외의 정본은 러너다(러너가 이 모듈을 import 하지 않으므로 순환이 없다).
from app.runner import CREDENTIAL_MARGIN_S, EngineBusy, EngineError, EngineStreamLost, PanelEngine, PatUnavailable

log = logging.getLogger("hwax_risk.engine")

__all__ = [
    "PanelEngine", "PortalPanelEngine", "PatUnavailable",
    "build_engine", "parse_sse", "collect_stream",
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
CONV_TIMEOUT_S = 5.0
HEALTH_TIMEOUT_S = 2.0
# 스트림의 쓰기·풀 대기. 읽기(줄 사이 침묵) 한도를 물려받지 않는다 — 그 값은 15시간이라, 물려주면 본문 송신이
# 막힌 것도 15시간을 기다린다. 읽기 한도는 설정이다(config.DEFAULT_ENGINE_READ_TIMEOUT_S).
WRITE_TIMEOUT_S = 30.0
POOL_TIMEOUT_S = 30.0
DEFAULT_AGENT_URL = "http://127.0.0.1:9009"

SAY_MAX = 2000                         # seat_opinion.turns[].say_excerpt 상한(plan §6.7.2 7단계)
EVENTS_MAX = 400                       # events[] 상한(plan §8.2.3 POST /panels/{id}/complete)
FIELD_MAX = 200                        # events[] 문자열 필드 상한
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


def _cut(value: Any, limit: int = FIELD_MAX) -> str | None:
    if value is None:
        return None
    return str(value)[:limit]


class _StreamWatch:
    """스트림 한 건이 어디까지 왔나 — 끊을 때 경과·마지막 단계·conv_id 를 말한다."""

    def __init__(self, conv_id: str | None) -> None:
        self.conv_id = conv_id
        self.started = now_epoch()
        self.last_step = ""

    def frame(self, name: str, data: Mapping[str, Any]) -> None:
        if name == "status" and data.get("step"):
            self.last_step = str(data["step"])[:FIELD_MAX]

    def lost(self, code: str, message: str) -> EngineStreamLost:
        """앱이 스트림을 놓았다는 예외 — 어느 사유든 '엔진은 계속 돌 수 있다' 와 그 심의의 대화를 같이 말한다."""
        return EngineStreamLost(
            code, f"{message} — 경과 {now_epoch() - self.started}초, 마지막 단계 {self.last_step or '없음'}."
                  f" 엔진 쪽 심의는 계속 돌 수 있다(conv_id={self.conv_id or '없음'})", conv_id=self.conv_id)


def _within_wall_clock(lines: Iterable[str], wall_s: int, watch: _StreamWatch) -> Iterator[str]:
    """줄이 올 때마다 벽시계를 본다 — 시작에서 `wall_s` 초를 넘겼으면 `EngineStreamLost` 로 끊는다(plan §6.10.2).

    읽기 타임아웃은 줄 사이 침묵만 잰다. 엔진이 상태 줄을 계속 보내는 한 걸리지 않아서, 벽시계를 따로 재지
    않으면 패널 하나가 러너 자리와 그 타깃의 직렬 순서를 끝없이 붙든다. 엔진에는 패널 전체를 재는 손잡이가
    없다(`timeout_s` 는 LLM 호출 한 번의 타임아웃이다) — 그래서 앱이 잰다. 줄이 오지 않는 동안은 볼 수 없다.
    그 구간은 읽기 타임아웃이 끊는다(엔진이 15초마다 ping 을 흘리므로 살아 있는 스트림은 15초마다 본다).
    `wall_s` 가 0 이면 재지 않는다.
    """
    for line in lines:
        if wall_s and now_epoch() > watch.started + wall_s:
            raise watch.lost("panel_timeout", f"패널이 {wall_s}초(HWAXRISK_PANEL_TIMEOUT_S)를 넘겼다")
        yield line


def _watched(frames: Iterable[tuple[str, dict]], watch: _StreamWatch) -> Iterator[tuple[str, dict]]:
    """프레임마다 마지막 단계를 적는다. 포털이 침묵 한도로 구독을 끊었다는 error 프레임은 엔진 실패와 갈라 올린다."""
    for name, data in frames:
        if name == "error" and str(data.get("code") or "") == PORTAL_STREAM_IDLE_CODE:
            raise watch.lost("engine_silent", f"{PORTAL_STREAM_IDLE_CODE}: {data.get('message') or ''}".strip())
        watch.frame(name, data)
        yield name, data


def collect_stream(frames: Iterable[tuple[str, dict]]) -> dict:
    """심의 SSE 프레임을 러너 계약 dict 로 모은다(plan §6.7.2 7단계 표).

    반환 {decision_text, turns, events, report_id, pat_degraded}. `error` 프레임은 EngineError 로 올린다.
    """
    decision_text = ""
    result_text = ""
    turns: list[dict] = []
    events: list[dict] = []
    report_id: Any = None
    pat_degraded = False
    error: str | None = None

    def add(event: Mapping[str, Any]) -> None:
        if len(events) < EVENTS_MAX:
            events.append(dict(event))

    for name, data in frames:
        if name == "status":
            add({"kind": "status", "step": _cut(data.get("step")) or "", "tool": _cut(data.get("tool"))})
        elif name == "delib":
            kind = str(data.get("kind") or "")
            if kind == "turn":
                turns.append({
                    "round": data.get("round"),
                    "persona": data.get("persona"),
                    "say": str(data.get("say") or "")[:SAY_MAX],
                    "stance": data.get("stance"),
                    "position": data.get("position"),
                })
                add({"kind": "turn", "persona": _cut(data.get("persona")), "round": data.get("round")})
            elif kind == "evidence":
                item = {"kind": "evidence", "source": _cut(data.get("source")) or "",
                        "included": bool(data.get("included"))}
                # 엔진이 좌석에 주지 않았다고 알린 카드는 사유 문장을 같이 남긴다 — 러너가 패널에 옮겨 적는다
                # (runner.withheld_by_engine). 실린 근거의 본문은 싣지 않는다 — events[] 는 압축 로그다.
                if not item["included"] and data.get("text"):
                    item["note"] = _cut(data.get("text"))
                add(item)
            elif kind == "personas":
                add({"kind": "personas", "personas": [
                    {"key": _cut(p.get("key")), "origin": _cut(p.get("origin"))}
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
            add({"kind": "warning", "code": _cut(code)})
        elif name == "error":
            error = f"{data.get('code') or 'error'}: {data.get('message') or ''}".strip()
        elif name == "done":
            break

    if error:
        raise EngineError(error)
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

    자격은 (b) 타깃 owner 가 등록한 포털 PAT → (a) 서비스 계정 PAT 순이고(runner.resolve_credential 과 같은 규칙),
    둘 다 없으면 `PatUnavailable` 이다. 좌석 도구 스코핑은 포털이 검증한 PAT 의 groups 로 강제된다 — 앱은 그룹을 자칭하지 않는다.
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
            # 복호는 identity 가 한다 — 키 없음·폐기 표기·손상은 None 이고 그때는 자격 (a) 로 강등한다(§8.2.7).
            pat = identity.credential_pat(row)
            if pat and int(row.get("pat_exp") or 0) > now_epoch() + CREDENTIAL_MARGIN_S:
                try:
                    groups = json.loads(row.get("pat_groups_json") or "[]")
                except ValueError:
                    groups = []
                return {"kind": "owner", "pat": pat, "email": row.get("pat_email"),
                        "groups": groups if isinstance(groups, list) else []}
        secrets = config.load_secrets(self.settings.data_dir)
        pat = secrets.get("HWAXRISK_PORTAL_PAT")
        if pat:
            return {"kind": "service", "pat": pat, "email": None, "groups": []}
        raise PatUnavailable("러너 자격이 없습니다 — 서비스 PAT 또는 owner 포털 PAT 를 등록하세요.")

    def _base(self) -> str:
        return str(self.settings.portal_base).rstrip("/")

    def _client(self, timeout: httpx.Timeout | float) -> httpx.Client:
        return httpx.Client(transport=self.transport, timeout=timeout)

    # -- 4단계 대화 생성(비치명) ------------------------------------------------
    def create_conversation(self, pat: str, title: str) -> str | None:
        """포털 대화 1건. 4xx·연결 실패면 None 이고 패널은 그대로 진행한다(plan §6.7.2 4단계)."""
        body = {"title": str(title)[:CONVERSATION_TITLE_MAX], "kind": CONVERSATION_KIND,
                "source": CONVERSATION_SOURCE}
        try:
            with self._client(CONV_TIMEOUT_S) as client:
                r = client.post(self._base() + CONVERSATIONS_PATH, json=body,
                                headers={"Authorization": f"Bearer {pat}"})
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
        base = str(getattr(self.settings, "agent_url", "") or DEFAULT_AGENT_URL).rstrip("/")
        with self._client(HEALTH_TIMEOUT_S) as client:
            r = client.get(base + "/health")
        r.raise_for_status()
        info = r.json()
        if not isinstance(info, dict):
            raise EngineError("agent-server /health 응답이 객체가 아닙니다.")
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
        }

    # -- 6·7단계 엔진 호출·SSE 캡처 ---------------------------------------------
    def run(self, delib_opts: Mapping[str, Any], *, owner_sub: str | None = None) -> dict:
        """패널 1건을 돌리고 {decision_text, turns, conv_id, events, …} 를 돌려준다.

        429(포털 agent_semaphore 초과)는 `EngineBusy` 라 러너가 대기 후 재시도하고, 연결 실패·error 프레임은
        `EngineError` 다. 앱이 스트림을 놓은 것(패널 벽시계·줄 사이 침묵·중간 절단)은 `EngineStreamLost` 로
        가른다 — 그때 엔진은 심의를 계속 돌릴 수 있다. 자격이 없으면 `PatUnavailable` 이다.
        """
        opts = {k: v for k, v in dict(delib_opts).items() if k != "question"}
        question = str(delib_opts.get("question") or "")
        credential = self._credential(owner_sub if owner_sub is not None else self.owner_sub)
        conv_id = self.create_conversation(credential["pat"], f"[리스크심사] {question[:160]}")

        # 줄 사이 침묵 한도. 종전에는 '엔진 호출당 타임아웃 1800 + 60' 으로 유도했다 — LLM 시도 한 번만 가정한 값이라
        # 엔진이 SDK 재시도를 하거나 박스의 호출 한도를 올리면 건강한 패널을 끊었다. 이제는 죽은 스트림만 잡는
        # 마지막 그물이다(엔진이 15초마다 ping 을 흘린다). 0 이면 끈다.
        read_s = float(getattr(self.settings, "risk_engine_read_timeout_s", config.DEFAULT_ENGINE_READ_TIMEOUT_S))
        timeout = httpx.Timeout(connect=CONNECT_TIMEOUT_S, read=read_s or None,
                                write=WRITE_TIMEOUT_S, pool=POOL_TIMEOUT_S)
        wall_s = config.panel_timeout_s(self.settings)
        watch = _StreamWatch(conv_id)
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
                        raise EngineBusy("포털 agent_semaphore 초과(429)")
                    if response.status_code in (401, 403):
                        response.read()
                        # 자격 문제라 폴백하지 않는다 — 잡을 pat_unavailable 로 멈춘다(plan §6.7.1 폴백 규칙).
                        raise PatUnavailable(f"포털이 러너 자격을 거부했습니다 — HTTP {response.status_code}")
                    if response.status_code >= 400:
                        response.read()
                        raise EngineError(f"포털이 심의를 거부했습니다 — HTTP {response.status_code}")
                    streaming = True
                    result = collect_stream(_watched(
                        parse_sse(_within_wall_clock(response.iter_lines(), wall_s, watch)), watch))
        except PatUnavailable:
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
        result["call_path"] = "portal"
        result["credential"] = credential["kind"]
        if credential["groups"]:
            result["call_groups"] = list(credential["groups"])
        return result


def build_engine(store: Any, settings: Any) -> PortalPanelEngine:
    """main.py lifespan 이 러너에 주입하는 기본 엔진(경로 (A))."""
    return PortalPanelEngine(store, settings)
