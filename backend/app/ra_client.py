# ReportArchive KG 인스턴스 쓰기·읽기를 게이트웨이 MCP 로 부르는 래퍼(plan §5.3.5) + external_sync 상태기계(§5.5.3)
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

import httpx

from app.common import canonical_json, now_epoch

# 게이트웨이 호출 타임아웃(GATEWAY_CALL_TIMEOUT 120 s) 아래로 잡는다.
DEFAULT_TIMEOUT = 60.0
# MCP streamable-http 프로토콜 버전(mcp>=1.10 서버가 받는 값).
PROTOCOL_VERSION = "2025-06-18"

# plan §5.3.5 표의 쓰기 4종 + 읽기 4종 + 보고서 2종. 여기 없는 도구는 부르지 않는다.
RA_WRITE_TOOLS = ("create_object", "update_object", "add_object_alias", "link_objects")
RA_READ_TOOLS = ("get_object", "search_objects", "get_subgraph", "list_object_types")
RA_REPORT_TOOLS = ("get_report", "update_report_draft")

# external_sync 재시도 규칙(plan §5.5.3) — next_at = now + min(15분 × 2^attempts, 6시간), attempts ≥ 8 이면 unavailable.
SYNC_BASE_DELAY = 15 * 60
SYNC_MAX_DELAY = 6 * 3600
SYNC_MAX_ATTEMPTS = 8
SYNC_CHANNELS = ("ra", "adh")


# ---------------------------------------------------------------- MCP streamable-http 전송
class McpHttpClient:
    """streamable-http MCP 엔드포인트에 JSON-RPC 로 tools/call 하는 최소 클라이언트.

    httpx.Client 를 주입받는다 — 테스트는 MockTransport 를 실은 Client 를 넣어 실제 네트워크 없이 돈다.
    어떤 실패도 예외로 올리지 않고 {'ok': False, 'error': …} 로 돌려준다(외부 반영은 비치명이다).
    """

    def __init__(self, endpoint: str, *, headers: Mapping[str, str] | None = None,
                 client: httpx.Client | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self._headers = dict(headers or {})
        self._client = client
        self._owns_client = client is None
        self._session_id: str | None = None
        self._next_id = 0

    # -- 내부 ---------------------------------------------------------------
    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def _rpc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _base_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
            **self._headers,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    @staticmethod
    def _decode(response: httpx.Response) -> dict | None:
        """application/json 과 text/event-stream 을 모두 받아 마지막 JSON-RPC 객체를 돌려준다."""
        text = response.text
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            last = None
            for line in text.splitlines():
                if not line.startswith("data:"):
                    continue
                try:
                    last = json.loads(line[len("data:"):].strip())
                except ValueError:
                    continue
            return last
        try:
            return json.loads(text)
        except ValueError:
            return None

    def _post(self, payload: dict) -> dict:
        response = self._http().post(self.endpoint, headers=self._base_headers(),
                                     content=canonical_json(payload).encode("utf-8"),
                                     timeout=self.timeout)
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        if response.status_code >= 400:
            return {"ok": False, "error": f"http_{response.status_code}",
                    "detail": response.text[:500], "status": response.status_code}
        if response.status_code == 202:
            return {"ok": True, "result": {}}
        message = self._decode(response)
        if message is None:
            return {"ok": False, "error": "unparsable_response", "detail": response.text[:500]}
        if isinstance(message, dict) and message.get("error"):
            return {"ok": False, "error": "rpc_error", "detail": message["error"]}
        return {"ok": True, "result": (message or {}).get("result") or {}}

    def _handshake(self) -> dict:
        if self._session_id is not None:
            return {"ok": True, "result": {}}
        reply = self._post({
            "jsonrpc": "2.0", "id": self._rpc_id(), "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": "hwax_risk", "version": "1"}},
        })
        if not reply["ok"]:
            return reply
        # 세션 헤더를 주지 않는 서버(단순 JSON-RPC)에서도 재핸드셰이크를 반복하지 않게 표시만 남긴다.
        if self._session_id is None:
            self._session_id = ""
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        return {"ok": True, "result": {}}

    @staticmethod
    def _unwrap(result: Mapping[str, Any]) -> Any:
        """tools/call 결과에서 구조화 값을 꺼낸다 — structuredContent > text(JSON) > text 원문."""
        if not isinstance(result, Mapping):
            return result
        if result.get("structuredContent") is not None:
            return result["structuredContent"]
        content = result.get("content")
        if isinstance(content, list) and content:
            first = content[0]
            if isinstance(first, Mapping) and first.get("type") == "text":
                text = first.get("text")
                try:
                    return json.loads(text)
                except (TypeError, ValueError):
                    return text
        return result

    # -- 공개 ---------------------------------------------------------------
    def call(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict:
        """도구 하나를 부른다. 성공 {'ok': True, 'result': …}, 실패 {'ok': False, 'error': …}."""
        try:
            handshake = self._handshake()
            if not handshake["ok"]:
                return handshake
            reply = self._post({
                "jsonrpc": "2.0", "id": self._rpc_id(), "method": "tools/call",
                "params": {"name": name, "arguments": dict(arguments or {})},
            })
        except httpx.HTTPError as exc:
            return {"ok": False, "error": "transport_error", "detail": f"{type(exc).__name__}: {exc}"}
        if not reply["ok"]:
            return reply
        result = reply["result"] if isinstance(reply["result"], Mapping) else {}
        if result.get("isError"):
            return {"ok": False, "error": "tool_error", "detail": self._unwrap(result)}
        return {"ok": True, "result": self._unwrap(result)}

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None


# ---------------------------------------------------------------- RA 래퍼
class RaClient:
    """앱 → 게이트웨이 MCP `reportarchive` 도구 래퍼. RA 토큰은 보유하지 않는다(포털 PAT 만 쓴다).

    자격이 없으면 어떤 호출도 하지 않고 {'ok': False, 'error': 'unavailable'} 로 조용히 지나간다.
    """

    def __init__(self, endpoint: str, token: str | None, *, client: httpx.Client | None = None,
                 timeout: float = DEFAULT_TIMEOUT, mcp: McpHttpClient | None = None) -> None:
        self.endpoint = endpoint
        self._token = token or ""
        self._mcp = mcp
        if self._mcp is None and self._token:
            self._mcp = McpHttpClient(endpoint, headers={"Authorization": f"Bearer {self._token}"},
                                      client=client, timeout=timeout)

    @property
    def available(self) -> bool:
        """포털 PAT 가 있고 전송 객체가 준비됐는가(§5.5.3 unavailable 판정의 첫 조건)."""
        return bool(self._token) and self._mcp is not None

    def _unavailable(self, reason: str = "no_credential") -> dict:
        return {"ok": False, "error": "unavailable", "reason": reason}

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict:
        if not self.available:
            return self._unavailable()
        if name not in RA_WRITE_TOOLS + RA_READ_TOOLS + RA_REPORT_TOOLS:
            return {"ok": False, "error": "tool_not_contracted", "detail": name}
        return self._mcp.call(name, arguments)

    # -- 읽기 ---------------------------------------------------------------
    def get_object(self, object_id: int | str) -> dict:
        return self.call_tool("get_object", {"id": object_id})

    def search_objects(self, **kwargs: Any) -> dict:
        return self.call_tool("search_objects", kwargs)

    def get_subgraph(self, object_id: int | str, relations: Sequence[str], depth: int = 3) -> dict:
        return self.call_tool("get_subgraph",
                              {"id": object_id, "relations": list(relations), "depth": depth})

    def list_object_types(self) -> dict:
        return self.call_tool("list_object_types", {})

    # -- 쓰기 4종 -----------------------------------------------------------
    def create_object(self, type_slug: str, value: str, code: str,
                      properties: Mapping[str, Any] | None = None) -> dict:
        """같은 code 로 재호출해도 안전하다(RA 가 resolve_existing 으로 created:false 를 돌려준다)."""
        return self.call_tool("create_object", {"type_slug": type_slug, "value": value, "code": code,
                                                "properties": dict(properties or {})})

    def update_object(self, object_id: int | str, properties: Mapping[str, Any]) -> dict:
        """properties 를 통째로 교체한다 — 부분 갱신은 upsert_props 를 쓴다."""
        return self.call_tool("update_object", {"id": object_id, "properties": dict(properties)})

    def upsert_props(self, object_id: int | str, patch: Mapping[str, Any]) -> dict:
        """get_object 로 현재 속성을 읽어 patch 를 병합한 뒤 update_object 로 보낸다(§5.3.5 멱등 규칙)."""
        if not self.available:
            return self._unavailable()
        current = self.get_object(object_id)
        if not current.get("ok"):
            return current
        payload = current.get("result") or {}
        obj = payload.get("object") if isinstance(payload, Mapping) and "object" in payload else payload
        props = dict((obj or {}).get("properties") or {}) if isinstance(obj, Mapping) else {}
        props.update(dict(patch))
        return self.update_object(object_id, props)

    def link_objects(self, src_id: int | str, dst_id: int | str, relation: str, *,
                     properties: Mapping[str, Any] | None = None,
                     evidence_report_id: int | str | None = None) -> dict:
        """UNIQUE(src,dst,relation) 이라 재호출은 속성·근거만 갱신한다. 축 제약 위반은 error 로 오고 재시도하지 않는다."""
        args: dict[str, Any] = {"src_id": src_id, "dst_id": dst_id, "relation": relation}
        if properties:
            args["properties"] = dict(properties)
        if evidence_report_id is not None:
            args["evidence_report_id"] = evidence_report_id
        return self.call_tool("link_objects", args)

    def add_object_alias(self, entity_id: int | str, alias: str) -> dict:
        """같은 축 안 정규화 유니크. 이미 그 엔티티의 별칭이면 멱등, 다른 엔티티와 충돌하면 error 다."""
        return self.call_tool("add_object_alias", {"entity_id": entity_id, "alias": alias})

    # -- 보고서 -------------------------------------------------------------
    def get_report(self, report_id: int | str) -> dict:
        return self.call_tool("get_report", {"report_id": report_id})

    def update_report_draft(self, report_id: int | str, patch: Mapping[str, Any]) -> dict:
        """전체 교체 API 라 호출자가 get_report 결과와 합쳐서 보낸다(§5.3.5 ⑧)."""
        return self.call_tool("update_report_draft", {"report_id": report_id, **dict(patch)})

    def close(self) -> None:
        if self._mcp is not None:
            self._mcp.close()


def ra_client_from_settings(settings, secrets: Mapping[str, str] | None = None, *,
                            client: httpx.Client | None = None) -> RaClient:
    """Settings·secrets.env 로 RaClient 를 만든다. PAT 가 없으면 available=False 인 객체가 나온다."""
    token = (secrets or {}).get("HWAXRISK_PORTAL_PAT")
    return RaClient(getattr(settings, "gateway_mcp", ""), token, client=client)


# ---------------------------------------------------------------- external_sync 상태기계(§5.5.3)
# 두 외부 채널(ra·adh)이 같은 rr_targets.external_sync_json 한 칸을 나눠 쓰므로 헬퍼는 여기 한 곳에 둔다.
def empty_sync() -> dict:
    """새 타깃의 초기값 — 두 채널 모두 pending, 대기 op 없음."""
    return {channel: {"state": "pending", "attempts": 0, "next_at": 0, "last_error": None,
                      "done_at": None, "pending_ops": []} for channel in SYNC_CHANNELS}


def load_external_sync(store, target_key: str) -> dict:
    """rr_targets.external_sync_json 을 읽어 두 채널이 모두 있는 dict 로 정규화한다."""
    row = store.query_one(
        "SELECT external_sync_json FROM rr_targets WHERE target_key = ?", (target_key,))
    raw = row["external_sync_json"] if row is not None else None
    try:
        parsed = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        parsed = {}
    out = empty_sync()
    if isinstance(parsed, dict):
        for channel in SYNC_CHANNELS:
            if isinstance(parsed.get(channel), dict):
                out[channel].update(parsed[channel])
    return out


def save_external_sync(store, target_key: str, sync: Mapping[str, Any]) -> int:
    """정규 JSON 으로 되쓴다(같은 상태면 같은 바이트)."""
    return store.execute(
        "UPDATE rr_targets SET external_sync_json = ?, updated_at = ? WHERE target_key = ?",
        (canonical_json(dict(sync)), now_epoch(), target_key),
    )


def set_sync_state(store, target_key: str, channel: str, state: str, *,
                   error: str | None = None) -> dict:
    """상태를 직접 옮긴다 — done 은 pending_ops 를 비우고 done_at 을 찍는다."""
    if channel not in SYNC_CHANNELS:
        raise ValueError(f"모르는 external_sync 채널: {channel!r}")
    sync = load_external_sync(store, target_key)
    entry = sync[channel]
    entry["state"] = state
    entry["last_error"] = error
    if state == "done":
        entry["pending_ops"] = []
        entry["attempts"] = 0
        entry["next_at"] = 0
        entry["done_at"] = now_epoch()
    elif state == "pending" and error is None:
        entry["attempts"] = 0
        entry["next_at"] = 0
    save_external_sync(store, target_key, sync)
    return sync


def mark_unavailable(store, target_key: str, channel: str, reason: str) -> dict:
    """자격 없음·게이트웨이 실패·401/403 — 예외 없이 표기만 하고 지나간다(§5.5.3)."""
    return set_sync_state(store, target_key, channel, "unavailable", error=reason)


def queue_sync_ops(store, target_key: str, channel: str, ops: Sequence[Mapping[str, Any]]) -> dict:
    """새 op 를 쌓는다. done 이었어도 pending 으로 돌아간다(§5.5.3 마지막 전이)."""
    if channel not in SYNC_CHANNELS:
        raise ValueError(f"모르는 external_sync 채널: {channel!r}")
    sync = load_external_sync(store, target_key)
    entry = sync[channel]
    existing = {canonical_json(op) for op in entry.get("pending_ops") or []}
    for op in ops:
        text = canonical_json(dict(op))
        if text not in existing:
            existing.add(text)
            entry.setdefault("pending_ops", []).append(dict(op))
    if entry["state"] != "unavailable" and entry.get("pending_ops"):
        entry["state"] = "pending"
        entry["done_at"] = None
    save_external_sync(store, target_key, sync)
    return sync


def complete_sync_ops(store, target_key: str, channel: str,
                      ops: Sequence[Mapping[str, Any]]) -> dict:
    """보낸 op 를 큐에서 지운다. 큐가 비면 done 으로 옮긴다."""
    sync = load_external_sync(store, target_key)
    entry = sync[channel]
    done = {canonical_json(dict(op)) for op in ops}
    entry["pending_ops"] = [op for op in entry.get("pending_ops") or []
                            if canonical_json(dict(op)) not in done]
    if not entry["pending_ops"] and entry["state"] == "pending":
        entry["state"] = "done"
        entry["attempts"] = 0
        entry["next_at"] = 0
        entry["done_at"] = now_epoch()
    save_external_sync(store, target_key, sync)
    return sync


def note_sync_failure(store, target_key: str, channel: str, error: str) -> dict:
    """실패 1회 — attempts+1, next_at 지수 백오프, attempts ≥ 8 이면 unavailable(§5.5.3)."""
    sync = load_external_sync(store, target_key)
    entry = sync[channel]
    entry["attempts"] = int(entry.get("attempts") or 0) + 1
    entry["last_error"] = error
    if entry["attempts"] >= SYNC_MAX_ATTEMPTS:
        entry["state"] = "unavailable"
        entry["next_at"] = 0
    else:
        entry["state"] = "pending"
        entry["next_at"] = now_epoch() + min(SYNC_BASE_DELAY * (2 ** entry["attempts"]), SYNC_MAX_DELAY)
    save_external_sync(store, target_key, sync)
    return sync


def resync(store, target_key: str) -> dict:
    """타깃 화면 '재동기' — unavailable 두 채널을 pending(attempts=0, next_at=0) 으로 되돌린다."""
    sync = load_external_sync(store, target_key)
    for channel in SYNC_CHANNELS:
        entry = sync[channel]
        entry["state"] = "pending"
        entry["attempts"] = 0
        entry["next_at"] = 0
        entry["last_error"] = None
    save_external_sync(store, target_key, sync)
    return sync


def sync_badge(sync: Mapping[str, Any]) -> str:
    """타깃 화면·통합 보고서 헤더 표기 — `RA 반영: done|pending(n)|unavailable · AIDataHub 반영: …`."""
    labels = {"ra": "RA 반영", "adh": "AIDataHub 반영"}
    parts = []
    for channel in SYNC_CHANNELS:
        entry = sync.get(channel) or {}
        state = str(entry.get("state") or "pending")
        n = len(entry.get("pending_ops") or [])
        parts.append(f"{labels[channel]}: {state}" + (f"({n})" if state == "pending" and n else ""))
    return " · ".join(parts)
