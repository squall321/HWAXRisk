# 로스터 원천 — 게이트웨이 MCP `list_agents`·`recommend_agents` 로 전문가 풀을 조회해 planner.freeze_roster 입력을 만든다(plan §6.3·§6.4)
from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from app import config, identity
from app.adapters.base import source_timeout
from app.common import now_epoch
from app.ra_client import DEADLINE_EXCEEDED, DEFAULT_TIMEOUT, McpHttpClient
from app.runner import CREDENTIAL_MARGIN_S

# 게이트웨이 도구 2종만 부른다(plan §6.3). 여기 없는 이름은 이 모듈이 호출하지 않는다.
LIST_AGENTS = "list_agents"
RECOMMEND_AGENTS = "recommend_agents"

RECOMMEND_TOP_K = 60          # plan §6.3 — recommend_agents(q=…, top 60)
QUERY_TEXT_MAX = 500          # plan §6.3 — summary_text 앞 500자

# 타깃 응답 `roster_source` 어휘. 'unset' 은 조회도 본문도 없던 P0 값이라 여기서는 쓰지 않는다.
SOURCE_GATEWAY = "gateway"
SOURCE_BODY = "body.agents"
SOURCE_UNAVAILABLE = "unavailable"

# relevance 출처 표기 — 강등해도 예외를 내지 않고 이 값으로 남긴다(plan §6.3, 순서는 agent_key asc 로 결정론 유지).
RELEVANCE_GATEWAY = "recommend_agents"
RELEVANCE_UNAVAILABLE = "unavailable"
RELEVANCE_NO_QUERY = "no_query"

# 테스트가 httpx.MockTransport 를 꽂는 자리. None 이면 실제 네트워크.
_gateway_transport: httpx.BaseTransport | None = None


def set_transport(transport: httpx.BaseTransport | None) -> httpx.BaseTransport | None:
    """게이트웨이 전송을 갈아 끼우고 직전 값을 돌려준다(테스트 전용 — 실 네트워크 대신 MockTransport)."""
    global _gateway_transport
    previous = _gateway_transport
    _gateway_transport = transport
    return previous


def _cfg(settings: Any | None) -> Any:
    return config.settings if settings is None else settings


# ---------------------------------------------------------------- 응답 파싱(게이트웨이 실측 형상)
def _agent_key(item: Mapping[str, Any]) -> str:
    """전문가 키 — `list_agents`·`recommend_agents` 는 `agent_type` 으로 준다(정찰 실측)."""
    for field in ("agent_type", "key", "agent_key"):
        value = item.get(field)
        if value:
            return str(value).strip()
    return ""


def _rows(payload: Any) -> list[Mapping[str, Any]]:
    """`{'result': [...]}`·`{'agents': [...]}`·배열 원문 셋 다 받는다(MCP 래핑이 판마다 다르다)."""
    if isinstance(payload, Mapping):
        for field in ("result", "agents", "items"):
            value = payload.get(field)
            if isinstance(value, list):
                payload = value
                break
        else:
            return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, Mapping)]


def parse_agent_list(payload: Any, domain: str) -> list[dict]:
    """`list_agents` 응답 → [{key, domain}]. domain 필드가 있으면 그것을 쓰고 없으면 질의한 도메인이다(plan §6.3)."""
    out: list[dict] = []
    seen: set[str] = set()
    for row in _rows(payload):
        key = _agent_key(row)
        if not key or key in seen:
            continue
        seen.add(key)
        dom = str(row.get("domain") or "").strip().lower() or domain
        out.append({"key": key, "domain": dom})
    return out


def parse_recommendations(payload: Any) -> dict[str, float]:
    """`recommend_agents` 응답 → {agent_key: score}. 목록 밖 전문가는 호출자가 0 으로 둔다(plan §6.3)."""
    scores: dict[str, float] = {}
    for row in _rows(payload):
        key = _agent_key(row)
        if not key:
            continue
        raw = row.get("score")
        value = float(raw) if isinstance(raw, (int, float)) else 0.0
        if value > scores.get(key, float("-inf")):
            scores[key] = value
    return scores


# ---------------------------------------------------------------- 조회 컴포넌트
class RosterSource:
    """게이트웨이 MCP 로스터 조회. 자격이 없으면 아무 호출도 하지 않고 빈 로스터로 강등한다.

    어떤 실패도 예외로 올리지 않는다 — 호출자는 `source == 'unavailable'` 을 그대로 응답에 싣는다.
    """

    def __init__(self, endpoint: str, token: str | None, *, client: httpx.Client | None = None,
                 timeout: float | httpx.Timeout = DEFAULT_TIMEOUT, mcp: McpHttpClient | None = None) -> None:
        self.endpoint = endpoint
        self._token = token or ""
        self._mcp = mcp
        if self._mcp is None and self._token and endpoint:
            self._mcp = McpHttpClient(endpoint, headers={"Authorization": f"Bearer {self._token}"},
                                      client=client, timeout=timeout)

    @property
    def available(self) -> bool:
        """포털 PAT 가 있고 전송 객체가 준비됐는가."""
        return bool(self._token) and self._mcp is not None

    @staticmethod
    def _empty(reason: str) -> dict:
        return {"source": SOURCE_UNAVAILABLE, "reason": reason, "agents": [],
                "relevance_source": RELEVANCE_UNAVAILABLE, "domains_ok": [], "domains_failed": [],
                "deadline_exceeded": False}

    def fetch(self, domains: Sequence[str], query_text: str = "", *,
              top_k: int = RECOMMEND_TOP_K, deadline_s: float | None = None) -> dict:
        """도메인마다 `list_agents(compact, domain)` 로 키를 모으고 `recommend_agents` 점수를 relevance 로 붙인다.

        반환 `agents` 는 `planner.freeze_roster` 가 받는 [{key, domain, relevance}] 다 —
        `target_key` 는 그 함수의 인자이고 `rank_in_domain` 은 그 함수가 (relevance desc, key asc) 로 매긴다.

        `deadline_s` 는 이 조회 전체의 벽시계 기한이다. 호출 사이에서만 보면 모자란다 — 침묵 한도는 게이트웨이의
        ping 이 되감아 호출 하나가 게이트웨이 한도(600초)까지 간다. 그래서 같은 기한을 모든 호출에 넘긴다
        (McpHttpClient 가 줄마다 보고, 기한이 지난 호출은 보내지도 않는다). 다 썼으면 남은 도메인이
        `domains_failed` 에 실리고 `deadline_exceeded` 가 참이다 — 받은 만큼은 그대로 돌려준다.
        """
        if not self.available:
            return self._empty("no_credential")
        deadline = None if deadline_s is None else time.monotonic() + deadline_s
        within = {} if deadline is None else {"deadline": deadline}
        expired = False

        scores: dict[str, float] = {}
        relevance_source = RELEVANCE_NO_QUERY
        text = (query_text or "").strip()[:QUERY_TEXT_MAX]
        if text:
            reply = self._mcp.call(RECOMMEND_AGENTS, {"q": text, "top_k": int(top_k)}, **within)
            if reply.get("ok"):
                scores = parse_recommendations(reply.get("result"))
                relevance_source = RELEVANCE_GATEWAY
            else:
                relevance_source = RELEVANCE_UNAVAILABLE
                expired = reply.get("error") == DEADLINE_EXCEEDED

        agents: list[dict] = []
        seen: set[str] = set()
        domains_ok: list[str] = []
        domains_failed: list[str] = []
        for domain in domains:
            reply = self._mcp.call(LIST_AGENTS, {"compact": True, "domain": domain}, **within)
            if not reply.get("ok"):
                domains_failed.append(domain)
                expired = expired or reply.get("error") == DEADLINE_EXCEEDED
                continue
            domains_ok.append(domain)
            for row in parse_agent_list(reply.get("result"), domain):
                if row["key"] in seen:
                    continue
                seen.add(row["key"])
                agents.append({"key": row["key"], "domain": row["domain"],
                               "relevance": float(scores.get(row["key"], 0.0))})
        if not domains_ok:
            if expired:
                return {**self._empty("deadline"), "domains_failed": domains_failed, "deadline_exceeded": True}
            return self._empty("gateway_error")
        return {"source": SOURCE_GATEWAY, "reason": None, "agents": agents,
                "relevance_source": relevance_source,
                "domains_ok": domains_ok, "domains_failed": domains_failed, "deadline_exceeded": expired}

    def close(self) -> None:
        if self._mcp is not None:
            self._mcp.close()


# ---------------------------------------------------------------- 자격·질의문
def credential(store: Any, owner_sub: str | None, *, settings: Any | None = None) -> str:
    """(b) 타깃 owner 의 포털 PAT → (a) 서비스 PAT 순(runner.resolve_credential 과 같은 규칙). 없으면 빈 문자열."""
    cfg = _cfg(settings)
    if owner_sub and store is not None:
        row = store.get_credential(owner_sub)
        # 복호는 identity 가 한다 — 키 없음·폐기 표기·손상은 None 이라 자격 (a) 로 내려간다(plan §8.2.7).
        pat = identity.credential_pat(row)
        if pat and int(row.get("pat_exp") or 0) > now_epoch() + CREDENTIAL_MARGIN_S:
            return pat
    return config.load_secrets(cfg.data_dir).get("HWAXRISK_PORTAL_PAT", "")


def query_text(store: Any, kind: str, ref_id: str) -> str:
    """`recommend_agents` 질의문 — snap 은 rr_states, diff 는 rr_diffs 의 summary_text 앞 500자(plan §6.3)."""
    if kind == "diff":
        row = store.query_one("SELECT summary_text FROM rr_diffs WHERE id = ?", (ref_id,))
    else:
        row = store.query_one("SELECT summary_text FROM rr_states WHERE snapshot_id = ?", (ref_id,))
    text = (row["summary_text"] if row is not None else "") or ""
    return str(text)[:QUERY_TEXT_MAX]


def source_for(store: Any, owner_sub: str | None, *, settings: Any | None = None,
               client: httpx.Client | None = None, mcp: McpHttpClient | None = None) -> RosterSource:
    """Settings·자격으로 RosterSource 를 만든다. 자격이 없으면 available=False 인 객체가 나온다."""
    cfg = _cfg(settings)
    # 호출당 침묵 한도는 소스 호출 손잡이(HWAXRISK_SOURCE_CALL_TIMEOUT_S, 연결 10초)를 쓴다 — 죽은 게이트웨이를 잡는
    # 값이고, 조회 전체의 길이는 fetch 의 기한이 묶는다.
    return RosterSource(getattr(cfg, "gateway_mcp", ""), credential(store, owner_sub, settings=cfg),
                        client=client, mcp=mcp, timeout=source_timeout(cfg))


def _deadline_notice(fetched: Mapping[str, Any], deadline_s: float) -> str:
    """기한을 넘긴 조회의 안내 한 줄 — 값·손잡이, 못 받은 도메인, 그리고 순위가 어떻게 매겨졌는지."""
    notice = f"전문가 명단 조회가 {deadline_s:g}초 안에 끝나지 않았다(HWAXRISK_ROSTER_DEADLINE_S)"
    parts: list[str] = []
    if fetched.get("domains_failed"):
        parts.append("못 받은 도메인 " + "·".join(fetched["domains_failed"]))
    if fetched.get("agents") and fetched.get("relevance_source") == RELEVANCE_UNAVAILABLE:
        parts.append("좌석 순위는 키 순서로 매겼다")
    return notice + (" — " + ", ".join(parts) if parts else "")


def fetch_for_target(store: Any, *, kind: str, ref_id: str, owner_sub: str | None,
                     settings: Any | None = None, client: httpx.Client | None = None,
                     mcp: McpHttpClient | None = None) -> dict:
    """타깃 1건의 로스터 원천 조회 — 도메인은 Settings `risk_roster_domains`, 질의문은 그 타깃의 summary_text."""
    cfg = _cfg(settings)
    owned: httpx.Client | None = None
    if client is None and mcp is None and _gateway_transport is not None:
        owned = client = httpx.Client(transport=_gateway_transport, timeout=source_timeout(cfg))
    source = source_for(store, owner_sub, settings=cfg, client=client, mcp=mcp)
    # 이 조회는 타깃을 여는 HTTP 요청 안에서 동기로 돈다 — nginx /apps/(600초)가 빈 504 를 내기 전에 스스로 끝낸다.
    # 종전에는 기한이 없어, 프록시가 먼저 끊으면 앱은 뒤늦게 타깃을 만들고 다시 누른 요청이 409 가 됐다.
    deadline_s = float(getattr(cfg, "risk_roster_deadline_s", config.DEFAULT_ROSTER_DEADLINE_S))
    try:
        fetched = source.fetch(cfg.risk_roster_domains, query_text(store, kind, ref_id), deadline_s=deadline_s)
        if fetched["deadline_exceeded"]:
            fetched["notice"] = _deadline_notice(fetched, deadline_s)
        return fetched
    finally:
        source.close()
        if owned is not None:
            owned.close()
