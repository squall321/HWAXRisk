# AIDataHub 반영 — REST import UPSERT(_external_id)·MCP 회수 도구(hybrid_search·tag_search·agent_search), 자격은 X-API-Key(plan §5.4)
from __future__ import annotations

from typing import Any, Mapping, Sequence

import httpx

from app.ra_client import DEFAULT_TIMEOUT, McpHttpClient

# 레코드에 붙는 범위 태그(plan §8.2.5 ②) — 소유자와 가시성. 조직 검색은 `hwax:vis:org` 만 본다.
OWNER_TAG_PREFIX = "hwax:owner:"
VISIBILITY_TAG_PREFIX = "hwax:vis:"


def with_scope_tags(record: Mapping[str, Any], *, owner_sub: str | None,
                    visibility: str | None) -> dict:
    """레코드에 소유자·가시성 태그를 붙인다(기존 같은 접두 태그는 갈아 끼운다 — 토글 재부착의 자리)."""
    row = dict(record)
    tags = [str(t) for t in (row.get("tags") or [])
            if not str(t).startswith((OWNER_TAG_PREFIX, VISIBILITY_TAG_PREFIX))]
    if owner_sub:
        tags.append(f"{OWNER_TAG_PREFIX}{owner_sub}")
    if visibility:
        tags.append(f"{VISIBILITY_TAG_PREFIX}{visibility}")
    row["tags"] = sorted(set(tags))
    return row


# import 는 REST 만 쓴다 — MCP import_record 는 _external_id 를 받지 못해 재실행 시 중복을 만든다(plan §5.4.2).
IMPORT_PATH = "/api/records/import"
# 이 값이 섞이면 external_id_map 이 같은 _external_id 를 두 레코드로 만든다(A 계획의 'hwax-portal' 폐기).
EXTERNAL_SOURCE = "hwax-risk"
# 회수 도구는 AIDataHub 자체 MCP(streamable-http) 에 있다.
MCP_PATH = "/mcp"

# doc_type 5종(plan §5.4.1). 부트스트랩은 backend/scripts/bootstrap_adh.py 가 따로 한다.
DOC_TYPES = ("risk_review_opinion", "risk_review_panel", "project_character",
             "risk_pattern_card", "design_snapshot_digest")
# 레코드 agents 는 항상 이 의사 에이전트 하나다 — 실 전문가 키를 넣으면 그 전문가의 일반 심의가 오염된다(§5.4.7).
MEMORY_AGENT = "risk-review-memory"
# 공통 태그 접두(§5.4.2).
TAG_ROOT = "hwax-risk-review"


def make_external_id(kind: str, **parts: Any) -> str:
    """`_external_id` 규약(plan §5.4.2) — 재실행 UPSERT 의 유일 키다.

    opinion:<target_key>:<agent_key>:<cycle> · panel:<panel_id> · character:<project_id> ·
    pattern:<pattern_id> · digest:<snapshot_id>.
    """
    def need(key: str) -> str:
        value = parts.get(key)
        if value is None or str(value) == "":
            raise ValueError(f"make_external_id({kind!r}): {key} 가 필요합니다.")
        return str(value)

    if kind == "opinion":
        return f"opinion:{need('target_key')}:{need('agent_key')}:{need('cycle')}"
    if kind == "panel":
        return f"panel:{need('panel_id')}"
    if kind == "character":
        return f"character:{need('project_id')}"
    if kind == "pattern":
        return f"pattern:{need('pattern_id')}"
    if kind == "digest":
        return f"digest:{need('snapshot_id')}"
    raise ValueError(f"make_external_id(): 모르는 kind — {kind!r}.")


class AdhClient:
    """AIDataHub 발신 클라이언트. httpx.Client 를 주입받고 자격이 없으면 아무 호출도 하지 않는다.

    실패는 예외가 아니라 {'ok': False, 'error': …} 다 — 외부 반영은 비치명이고 §5.5.3 큐가 재시도한다.
    """

    def __init__(self, base: str, api_key: str | None, *, client: httpx.Client | None = None,
                 timeout: float = DEFAULT_TIMEOUT, mcp: McpHttpClient | None = None) -> None:
        self.base = (base or "").rstrip("/")
        self._api_key = api_key or ""
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None
        self._mcp = mcp
        if self._mcp is None and self._api_key and self.base:
            self._mcp = McpHttpClient(self.base + MCP_PATH, headers={"X-API-Key": self._api_key},
                                      client=client, timeout=timeout)

    @property
    def available(self) -> bool:
        """API 키와 베이스가 모두 있는가(§5.5.3 adh unavailable 판정의 첫 조건)."""
        return bool(self._api_key and self.base)

    def _unavailable(self, reason: str = "no_credential") -> dict:
        return {"ok": False, "error": "unavailable", "reason": reason}

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def _post_json(self, path: str, payload: Mapping[str, Any], *,
                   params: Mapping[str, Any] | None = None) -> dict:
        try:
            response = self._http().post(
                self.base + path, params=dict(params or {}), json=dict(payload),
                headers={"X-API-Key": self._api_key, "Content-Type": "application/json"},
                timeout=self.timeout,
            )
        except httpx.HTTPError as exc:
            return {"ok": False, "error": "transport_error", "detail": f"{type(exc).__name__}: {exc}"}
        if response.status_code >= 400:
            return {"ok": False, "error": f"http_{response.status_code}",
                    "detail": response.text[:500], "status": response.status_code}
        try:
            return {"ok": True, "result": response.json()}
        except ValueError:
            return {"ok": False, "error": "unparsable_response", "detail": response.text[:500]}

    # -- REST 반영 -----------------------------------------------------------
    def import_records(self, records: Sequence[Mapping[str, Any]], *, dry_run: bool = False,
                       owner_sub: str | None = None, visibility: str | None = None) -> dict:
        """`POST /api/records/import?external_source=hwax-risk` — `_external_id` 로 UPSERT 한다.

        레코드 id 는 불변이므로 재실행해도 `narr:`·`card:` 인용 대상이 바뀌지 않는다.
        `owner_sub`·`visibility` 를 주면 소유자·가시성 태그를 붙인다 — 조직 태그 검색이 비공개 과제를
        긁어 오지 않게 하는 유일한 자리다(plan §8.2.5 ②·§0.9 P3-23).
        """
        if not self.available:
            return self._unavailable()
        if not records:
            return {"ok": True, "result": {"records": []}}
        rows = [with_scope_tags(r, owner_sub=owner_sub, visibility=visibility) for r in records]
        payload = {"records": rows, "dry_run": bool(dry_run)}
        return self._post_json(IMPORT_PATH, payload, params={"external_source": EXTERNAL_SOURCE})

    def record_ids(self, reply: Mapping[str, Any]) -> dict[str, str]:
        """import 응답에서 `_external_id → record_id` 를 뽑는다(rr_id_map·adh_record_id 에 적을 값)."""
        out: dict[str, str] = {}
        result = reply.get("result") if reply.get("ok") else None
        if not isinstance(result, Mapping):
            return out
        rows = result.get("records") or result.get("items") or result.get("results") or []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            external_id = row.get("_external_id") or row.get("external_id")
            record_id = row.get("record_id") or row.get("id")
            if external_id and record_id:
                out[str(external_id)] = str(record_id)
        return out

    # -- MCP 회수 ------------------------------------------------------------
    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict:
        if not self.available or self._mcp is None:
            return self._unavailable()
        return self._mcp.call(name, arguments)

    def hybrid_search(self, q: str, *, top_k: int = 5, tags: Sequence[str] | None = None,
                      data_types: Sequence[str] | None = None,
                      exclude_tags: Sequence[str] | None = None) -> dict:
        """유사 서술 경로 (c) — summary_text 앞 300자로 찾는다(plan §5.4.7·§7.3 3단계).

        e5 코사인은 절대값을 비교하지 않고 상대 순위만 쓴다(무관한 문장도 0.89 가 정상이다).
        """
        args: dict[str, Any] = {"q": q, "top_k": top_k}
        if data_types:
            args["data_types"] = list(data_types)
        if tags:
            args["tags"] = list(tags)
        if exclude_tags:
            args["exclude_tags"] = list(exclude_tags)
        return self.call_tool("hybrid_search", args)

    def tag_search(self, tags: Sequence[str], *, limit: int = 20) -> dict:
        """성격 씨앗 태그(`char:…`)로 레코드를 찾는다(§7.3 3단계 후반)."""
        return self.call_tool("tag_search", {"tags": list(tags), "limit": limit})

    def agent_search(self, agent_type: str, q: str, *, mode: str = "hybrid",
                     required_tags: Sequence[str] | None = None, top_k: int = 3,
                     exclude_tags: Sequence[str] | None = None) -> dict:
        """좌석 개인 기억 2차 경로 — 의사 에이전트 `risk-review-memory` 안에서만 찾는다(§5.6.3 2)."""
        args: dict[str, Any] = {"agent_type": agent_type, "q": q, "mode": mode}
        if required_tags:
            args["required_tags"] = list(required_tags)
        if exclude_tags:
            args["exclude_tags"] = list(exclude_tags)
        if top_k:
            args["retrieval_config"] = {"top_k": top_k}
        return self.call_tool("agent_search", args)

    def close(self) -> None:
        if self._mcp is not None:
            self._mcp.close()
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None


def adh_client_from_settings(settings, secrets: Mapping[str, str] | None = None, *,
                             client: httpx.Client | None = None) -> AdhClient:
    """Settings·secrets.env 로 AdhClient 를 만든다. 키가 없으면 available=False 인 객체가 나온다."""
    api_key = (secrets or {}).get("HWAXRISK_AIDH_API_KEY")
    return AdhClient(getattr(settings, "aidh_base", ""), api_key, client=client)
