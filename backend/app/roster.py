# 로스터 원천 — 게이트웨이 MCP `list_agents`·`recommend_agents` 로 전문가 풀을 조회해 planner.freeze_roster 입력을 만든다(plan §6.3·§6.4)
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from app import config, identity
from app.common import now_epoch
from app.ra_client import DEFAULT_TIMEOUT, McpHttpClient
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
                 timeout: float = DEFAULT_TIMEOUT, mcp: McpHttpClient | None = None) -> None:
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
                "relevance_source": RELEVANCE_UNAVAILABLE, "domains_ok": [], "domains_failed": []}

    def fetch(self, domains: Sequence[str], query_text: str = "", *,
              top_k: int = RECOMMEND_TOP_K) -> dict:
        """도메인마다 `list_agents(compact, domain)` 로 키를 모으고 `recommend_agents` 점수를 relevance 로 붙인다.

        반환 `agents` 는 `planner.freeze_roster` 가 받는 [{key, domain, relevance}] 다 —
        `target_key` 는 그 함수의 인자이고 `rank_in_domain` 은 그 함수가 (relevance desc, key asc) 로 매긴다.
        """
        if not self.available:
            return self._empty("no_credential")

        scores: dict[str, float] = {}
        relevance_source = RELEVANCE_NO_QUERY
        text = (query_text or "").strip()[:QUERY_TEXT_MAX]
        if text:
            reply = self._mcp.call(RECOMMEND_AGENTS, {"q": text, "top_k": int(top_k)})
            if reply.get("ok"):
                scores = parse_recommendations(reply.get("result"))
                relevance_source = RELEVANCE_GATEWAY
            else:
                relevance_source = RELEVANCE_UNAVAILABLE

        agents: list[dict] = []
        seen: set[str] = set()
        domains_ok: list[str] = []
        domains_failed: list[str] = []
        for domain in domains:
            reply = self._mcp.call(LIST_AGENTS, {"compact": True, "domain": domain})
            if not reply.get("ok"):
                domains_failed.append(domain)
                continue
            domains_ok.append(domain)
            for row in parse_agent_list(reply.get("result"), domain):
                if row["key"] in seen:
                    continue
                seen.add(row["key"])
                agents.append({"key": row["key"], "domain": row["domain"],
                               "relevance": float(scores.get(row["key"], 0.0))})
        if not domains_ok:
            return self._empty("gateway_error")
        return {"source": SOURCE_GATEWAY, "reason": None, "agents": agents,
                "relevance_source": relevance_source,
                "domains_ok": domains_ok, "domains_failed": domains_failed}

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
    return RosterSource(getattr(cfg, "gateway_mcp", ""), credential(store, owner_sub, settings=cfg),
                        client=client, mcp=mcp)


def fetch_for_target(store: Any, *, kind: str, ref_id: str, owner_sub: str | None,
                     settings: Any | None = None, client: httpx.Client | None = None,
                     mcp: McpHttpClient | None = None) -> dict:
    """타깃 1건의 로스터 원천 조회 — 도메인은 Settings `risk_roster_domains`, 질의문은 그 타깃의 summary_text."""
    cfg = _cfg(settings)
    owned: httpx.Client | None = None
    if client is None and mcp is None and _gateway_transport is not None:
        owned = client = httpx.Client(transport=_gateway_transport, timeout=DEFAULT_TIMEOUT)
    source = source_for(store, owner_sub, settings=cfg, client=client, mcp=mcp)
    try:
        return source.fetch(cfg.risk_roster_domains, query_text(store, kind, ref_id))
    finally:
        source.close()
        if owned is not None:
            owned.close()
