# ReportArchive KG 인스턴스 쓰기·읽기를 게이트웨이 MCP 로 부르는 래퍼(plan §5.3.5) + 대기 op 를 보내는 쪽(RK-01) + external_sync 상태기계(§5.5.3)
from __future__ import annotations

import json
import re
import time
from collections import Counter
from typing import Any, Callable, Mapping, Sequence

import httpx

from app import config
from app.common import canonical_json, http_client, new_uuid, now_epoch, parse_ref

# 응답 침묵 한도다 — 호출 길이의 상한이 아니다. 게이트웨이가 도구가 도는 동안 15초마다 ping 을 흘리므로 이 값은
# 죽은 게이트웨이만 잡고, 호출 길이는 게이트웨이의 GATEWAY_CALL_TIMEOUT 이 정한다(호출 길이를 묶으려면 기한을 준다).
DEFAULT_TIMEOUT = 60.0
# `call()` 이 기한 초과에 돌려주는 error 값.
DEADLINE_EXCEEDED = "deadline_exceeded"
# MCP streamable-http 프로토콜 버전(mcp>=1.10 서버가 받는 값).
PROTOCOL_VERSION = "2025-06-18"

# plan §5.3.5 표의 지식 그래프 쓰기 4종 + 읽기 4종. 여기 없는 도구는 부르지 않는다 — 보고서 도구는 이 클라이언트(박스 쓰기 PAT)의
# 계약 밖이다. 보고서는 사람 이름이다(사용자 결정 10-31 D-1 — 종합 보고서는 포털 챗 PAT 길, FU-D17).
RA_WRITE_TOOLS = ("create_object", "update_object", "add_object_alias", "link_objects")
RA_READ_TOOLS = ("get_object", "search_objects", "get_subgraph", "list_object_types")

# external_sync 재시도 규칙(plan §5.5.3) — next_at = now + min(15분 × 2^attempts, 6시간), attempts ≥ 8 이면 unavailable.
SYNC_BASE_DELAY = 15 * 60
SYNC_MAX_DELAY = 6 * 3600
SYNC_MAX_ATTEMPTS = 8
SYNC_CHANNELS = ("ra", "adh")


# ---------------------------------------------------------------- MCP streamable-http 전송
class _DeadlineExceeded(httpx.ReadTimeout):
    """호출에 정해 둔 벽시계 기한이 지났다 — 상대가 조용했던 것(침묵 한도)과 가른다. 올릴 손잡이가 서로 다르다."""


class McpHttpClient:
    """streamable-http MCP 엔드포인트에 JSON-RPC 로 tools/call 하는 최소 클라이언트.

    httpx.Client 를 주입받는다 — 테스트는 MockTransport 를 실은 Client 를 넣어 실제 네트워크 없이 돈다.
    어떤 실패도 예외로 올리지 않고 {'ok': False, 'error': …} 로 돌려준다(외부 반영은 비치명이다).

    `timeout` 은 바이트 사이 침묵 한도다. 게이트웨이는 도구가 도는 동안 15초마다 ping 주석 줄을 흘리므로, 15초를
    넘는 값은 죽은 게이트웨이만 잡고 호출 길이는 자르지 못한다. 호출 길이를 묶으려면 `deadline_s`(POST 한 건의
    벽시계 기한, 초)를 주거나 `call(..., deadline=)` 에 여러 호출이 나눠 쓰는 기한(monotonic 시각)을 준다 —
    넘기면 `error` 가 'deadline_exceeded' 다. 둘 다 없으면 기한 없이 종전 길로 간다.
    """

    def __init__(self, endpoint: str, *, headers: Mapping[str, str] | None = None,
                 client: httpx.Client | None = None, timeout: float = DEFAULT_TIMEOUT,
                 deadline_s: float | None = None) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.deadline_s = deadline_s
        self._headers = dict(headers or {})
        self._client = client
        self._owns_client = client is None
        self._session_id: str | None = None
        self._next_id = 0

    # -- 내부 ---------------------------------------------------------------
    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = http_client(timeout=self.timeout)
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
    def _decode(text: str, content_type: str) -> dict | None:
        """application/json 과 text/event-stream 을 모두 받아 마지막 JSON-RPC 객체를 돌려준다."""
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

    def _post(self, payload: dict, deadline: float | None = None) -> dict:
        """JSON-RPC 한 건을 보낸다. 기한이 걸려 있으면 응답을 스트림으로 읽으며 줄마다 경과를 본다.

        httpx 의 한도는 침묵만 재서, ping 을 흘리는 게이트웨이에서는 한도 20초로 34초짜리 호출이 그대로 돌아온다
        (실측). 그래서 기한이 걸린 호출은 줄(ping 주석 줄 포함)이 올 때마다 시계를 본다 — 넘겨 듣는 폭은 ping 한 칸
        (15초)이다. 침묵 한도도 남은 기한을 넘지 않게 줄여, ping 조차 없는 상대는 기한에 맞춰 끊는다.
        """
        content = canonical_json(payload).encode("utf-8")
        if deadline is None and self.deadline_s is not None:
            deadline = time.monotonic() + self.deadline_s
        if deadline is None:
            response = self._http().post(self.endpoint, headers=self._base_headers(), content=content,
                                         timeout=self.timeout)
            return self._reply(response, response.text)
        left = deadline - time.monotonic()
        if left <= 0:
            raise _DeadlineExceeded("호출 기한 초과(보내지 않았다)")
        idle = httpx.Timeout(self.timeout)
        within = httpx.Timeout(connect=left if idle.connect is None else min(idle.connect, left),
                               read=left if idle.read is None else min(idle.read, left),
                               write=idle.write, pool=idle.pool)
        try:
            with self._http().stream("POST", self.endpoint, headers=self._base_headers(), content=content,
                                     timeout=within) as response:
                lines: list[str] = []
                for line in response.iter_lines():
                    if time.monotonic() >= deadline:
                        raise _DeadlineExceeded("호출 기한 초과", request=response.request)
                    lines.append(line)
                return self._reply(response, "\n".join(lines))
        except _DeadlineExceeded:
            raise
        except httpx.TimeoutException as exc:
            # 줄인 침묵 한도가 기한과 함께 걸렸다 — 기한이 남았으면 그것은 죽은 상대다(그대로 올린다).
            if time.monotonic() < deadline:
                raise
            raise _DeadlineExceeded(f"호출 기한 초과({type(exc).__name__})") from exc

    def _reply(self, response: httpx.Response, text: str) -> dict:
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        if response.status_code >= 400:
            return {"ok": False, "error": f"http_{response.status_code}",
                    "detail": text[:500], "status": response.status_code}
        if response.status_code == 202:
            return {"ok": True, "result": {}}
        message = self._decode(text, response.headers.get("content-type", ""))
        if message is None:
            return {"ok": False, "error": "unparsable_response", "detail": text[:500]}
        if isinstance(message, dict) and message.get("error"):
            return {"ok": False, "error": "rpc_error", "detail": message["error"]}
        return {"ok": True, "result": (message or {}).get("result") or {}}

    def _handshake(self, deadline: float | None = None) -> dict:
        if self._session_id is not None:
            return {"ok": True, "result": {}}
        reply = self._post({
            "jsonrpc": "2.0", "id": self._rpc_id(), "method": "initialize",
            "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                       "clientInfo": {"name": "hwax_risk", "version": "1"}},
        }, deadline)
        if not reply["ok"]:
            return reply
        # 세션 헤더를 주지 않는 서버(단순 JSON-RPC)에서도 재핸드셰이크를 반복하지 않게 표시만 남긴다.
        if self._session_id is None:
            self._session_id = ""
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, deadline)
        return {"ok": True, "result": {}}

    @staticmethod
    def _unwrap(result: Mapping[str, Any]) -> Any:
        """tools/call 결과에서 구조화 값을 꺼낸다 — structuredContent > text(JSON) > text 원문.

        text 블록이 여럿이면(목록을 돌려주는 도구를 항목마다 블록 하나로 내는 서버) 전부 읽는다 — 블록마다 JSON 이면 그
        값들의 목록, 아니면 글을 줄바꿈으로 잇는다. 종전에는 첫 블록만 읽어 목록의 둘째 항목부터 말없이 버렸다.
        """
        if not isinstance(result, Mapping):
            return result
        if result.get("structuredContent") is not None:
            return result["structuredContent"]
        content = result.get("content")
        texts = [b.get("text") for b in content if isinstance(b, Mapping) and b.get("type") == "text"] \
            if isinstance(content, list) else []
        if not texts:
            return result
        parsed = []
        for text in texts:
            try:
                parsed.append(json.loads(text))
            except (TypeError, ValueError):
                parsed = None
                break
        if len(texts) == 1:
            return parsed[0] if parsed is not None else texts[0]
        return parsed if parsed is not None else "\n".join(str(t) for t in texts)

    # -- 공개 ---------------------------------------------------------------
    def call(self, name: str, arguments: Mapping[str, Any] | None = None, *,
             deadline: float | None = None) -> dict:
        """도구 하나를 부른다. 성공 {'ok': True, 'result': …}, 실패 {'ok': False, 'error': …}.

        `deadline` 은 이 호출이 끝나야 하는 monotonic 시각이다 — 여러 호출이 한 기한을 나눠 쓸 때 준다(명단 조회).
        """
        try:
            handshake = self._handshake(deadline)
            if not handshake["ok"]:
                return handshake
            reply = self._post({
                "jsonrpc": "2.0", "id": self._rpc_id(), "method": "tools/call",
                "params": {"name": name, "arguments": dict(arguments or {})},
            }, deadline)
        except _DeadlineExceeded as exc:
            return {"ok": False, "error": DEADLINE_EXCEEDED, "detail": str(exc)}
        except httpx.HTTPError as exc:
            return {"ok": False, "error": "transport_error", "detail": f"{type(exc).__name__}: {exc}"}
        if not reply["ok"]:
            return reply
        result = reply["result"] if isinstance(reply["result"], Mapping) else {}
        if result.get("isError"):
            return {"ok": False, "error": "tool_error", "detail": self._unwrap(result)}
        return {"ok": True, "result": self._unwrap(result)}

    def list_tools(self, *, deadline: float | None = None) -> dict:
        """도구 목록(tools/list — 이름 · inputSchema). 성공 {'ok': True, 'result': [도구…]}(nextCursor 쪽을 끝까지 잇는다), 실패는
        call 과 같은 {'ok': False, 'error': …}. 근거 꾸러미 B 층이 인자 키를 스키마와 대조한다(W2-03 (c))."""
        tools: list = []
        cursor: str | None = None
        try:
            handshake = self._handshake(deadline)
            if not handshake["ok"]:
                return handshake
            for _ in range(100):
                params = {"cursor": cursor} if cursor else {}
                reply = self._post({"jsonrpc": "2.0", "id": self._rpc_id(), "method": "tools/list", "params": params},
                                   deadline)
                if not reply["ok"]:
                    return reply
                result = reply["result"] if isinstance(reply["result"], Mapping) else {}
                tools.extend(t for t in result.get("tools") or () if isinstance(t, Mapping))
                cursor = result.get("nextCursor") or None
                if not cursor:
                    break
        except _DeadlineExceeded as exc:
            return {"ok": False, "error": DEADLINE_EXCEEDED, "detail": str(exc)}
        except httpx.HTTPError as exc:
            return {"ok": False, "error": "transport_error", "detail": f"{type(exc).__name__}: {exc}"}
        return {"ok": True, "result": tools}

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None


# ---------------------------------------------------------------- RA 래퍼
# 게이트웨이의 호출 전용 별칭 `<백엔드 키(하이픈 뺌)>_<원래 이름>` — 맨 이름은 다른 백엔드에 같은 이름이 붙으면 둘 다 접두가 붙어 바뀌고
# (노출 이름이 제3자 앱의 가동 여부로 뒤집힌다 — 게이트웨이 bdd05b2), 별칭은 겹침과 무관하게 늘 RA 로 간다. 계약 이름(RA_*_TOOLS)은 맨 이름이다.
GATEWAY_ALIAS_PREFIX = "reportarchive_"
# 가린 값의 표지 — 게이트웨이가 나가는 응답의 사람 이름 · 메일 · 계정 꼴을 `[가림:<종류>]` 로 바꾼다(HWAXPortal docs/request-1027 HG-20).
MASK_MARK = "[가림:"


def is_masked(value: Any) -> bool:
    """게이트웨이가 가린 값인가(글 · 목록 · 객체 안까지)."""
    if isinstance(value, str):
        return MASK_MARK in value
    if isinstance(value, Mapping):
        return any(is_masked(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(is_masked(v) for v in value)
    return False


class RaClient:
    """앱 → 게이트웨이 MCP `reportarchive` 도구 래퍼. RA 토큰은 보유하지 않는다(포털 PAT 만 쓴다).

    자격이 없으면 어떤 호출도 하지 않고 {'ok': False, 'error': 'unavailable'} 로 조용히 지나간다. 인자 이름은 RA MCP 의 것이다
    (ReportArchive mcp_server — get_object(type, id) · update_object(object_id, …) · link_objects(src_id, dst_id, relation, …)).
    `gate` 는 부를 때마다 묻는 문이다 — 거짓이면 부르지 않고 {'ok': False, 'error': 'closed'} 다(보내는 쪽이 보내는 도중 과제가 조직
    공개를 떠났는지 · 폐기됐는지 본다).
    """

    def __init__(self, endpoint: str, token: str | None, *, client: httpx.Client | None = None,
                 timeout: float = DEFAULT_TIMEOUT, mcp: McpHttpClient | None = None,
                 deadline_s: float | None = None, gate: Callable[[], bool] | None = None) -> None:
        self.endpoint = endpoint
        self._token = token or ""
        self._gate = gate
        self._mcp = mcp
        if self._mcp is None and self._token:
            self._mcp = McpHttpClient(endpoint, headers={"Authorization": f"Bearer {self._token}"},
                                      client=client, timeout=timeout, deadline_s=deadline_s)

    @property
    def available(self) -> bool:
        """포털 PAT 가 있고 전송 객체가 준비됐는가(§5.5.3 unavailable 판정의 첫 조건)."""
        return bool(self._token) and self._mcp is not None

    def _unavailable(self, reason: str = "no_credential") -> dict:
        return {"ok": False, "error": "unavailable", "reason": reason}

    def call_tool(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict:
        if not self.available:
            return self._unavailable()
        if name not in RA_WRITE_TOOLS + RA_READ_TOOLS:
            return {"ok": False, "error": "tool_not_contracted", "detail": name}
        if self._gate is not None and not self._gate():
            return {"ok": False, "error": "closed"}
        return self._mcp.call(GATEWAY_ALIAS_PREFIX + name, arguments)

    # -- 읽기 ---------------------------------------------------------------
    def get_object(self, type_slug: str, object_id: int | str) -> dict:
        """RA 는 축 slug 와 id 로 지목하고 축이 다르면 없는 것으로 답한다(`객체를 찾을 수 없습니다`)."""
        return self.call_tool("get_object", {"type": type_slug, "id": str(object_id)})

    def search_objects(self, **kwargs: Any) -> dict:
        return self.call_tool("search_objects", kwargs)

    def get_subgraph(self, object_id: int | str, relations: Sequence[str], depth: int = 3) -> dict:
        return self.call_tool("get_subgraph",
                              {"entity_id": int(object_id), "relations": list(relations), "depth": depth})

    def list_object_types(self) -> dict:
        return self.call_tool("list_object_types", {})

    # -- 쓰기 4종 -----------------------------------------------------------
    def create_object(self, type_slug: str, value: str, code: str,
                      properties: Mapping[str, Any] | None = None, *, description: str | None = None) -> dict:
        """같은 code 로 재호출해도 안전하다(RA 가 resolve_existing 으로 created:false 를 돌려준다).

        RA 의 resolve_existing 은 code 가 맞는 객체가 없으면 value(대소문자 무시) · 별칭으로 찾는다 — 돌려준 객체의 code 가 다르면
        값이 겹친 남의 객체다(부르는 쪽이 code 를 견준다)."""
        args: dict[str, Any] = {"type_slug": type_slug, "value": value, "code": code,
                                "properties": dict(properties or {})}
        if description:
            args["description"] = description
        return self.call_tool("create_object", args)

    def update_object(self, object_id: int | str, properties: Mapping[str, Any] | None = None, *,
                      value: str | None = None, description: str | None = None) -> dict:
        """넘긴 칸만 바뀐다(RA update_object — value · description · properties). properties 는 통째로 교체한다 — 부분 갱신은
        upsert_props 를 쓴다. description 에 빈 글을 넘기면 RA 가 설명을 비운다(RA MCP 는 None 인 칸만 뺀다). value 를 바꾸면 RA 가 같은
        축의 값 겹침을 본다('이미 같은 값이 있습니다')."""
        args: dict[str, Any] = {"object_id": int(object_id)}
        if value is not None:
            args["value"] = value
        if description is not None:
            args["description"] = description
        if properties is not None:
            args["properties"] = dict(properties)
        return self.call_tool("update_object", args)

    def upsert_props(self, type_slug: str, object_id: int | str, patch: Mapping[str, Any], *,
                     current: Mapping[str, Any] | None = None) -> dict:
        """get_object 로 현재 속성을 읽어 patch 를 병합한 뒤 update_object 로 보낸다(§5.3.5 멱등 규칙).

        `current` 는 이미 읽은 객체(get_object 답 · create_object 의 object)다 — 주면 다시 읽지 않는다. 게이트웨이가 가린 값
        (`[가림:…]`)은 되쓰지 않는다 — update_object 는 통째 교체라 그대로 보내면 가린 글이 RA 원본을 덮는다. patch 가 그 칸을 채우면
        patch 값이 들어가고, 못 채우는 칸이 남으면 보내지 않고 {'ok': False, 'error': 'masked_readback', 'detail': [칸]} 이다.
        병합한 결과가 지금 속성과 같으면 부르지 않는다({'ok': True, 'result': {'unchanged': True}}).
        """
        if not self.available:
            return self._unavailable()
        if current is None:
            reply = self.get_object(type_slug, object_id)
            if not reply.get("ok"):
                return reply
            current = reply.get("result") if isinstance(reply.get("result"), Mapping) else {}
        props = dict(current.get("properties") or {}) if isinstance(current.get("properties"), Mapping) else {}
        lost = sorted(k for k, v in props.items() if is_masked(v) and k not in patch)
        if lost:
            return {"ok": False, "error": "masked_readback", "detail": lost}
        merged = {**props, **dict(patch)}
        if merged == props:
            return {"ok": True, "result": {"unchanged": True}}
        return self.update_object(object_id, merged)

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
        return self.call_tool("add_object_alias", {"object_id": int(entity_id), "alias": alias})

    def close(self) -> None:
        if self._mcp is not None:
            self._mcp.close()


# RA 지식 그래프 쓰기 전용 자격. 읽기용 HWAXRISK_PORTAL_PAT(scopes ['read'])와 절대 섞지 않는다(plan §8.2.7).
WRITE_SECRET_KEY = "HWAXRISK_PORTAL_PAT_RW"


def ra_client_from_settings(settings, secrets: Mapping[str, str] | None = None, *,
                            client: httpx.Client | None = None, deadline_s: float | None = None,
                            gate: Callable[[], bool] | None = None) -> RaClient:
    """Settings·secrets.env 로 RaClient 를 만든다 — 쓰기 키 `HWAXRISK_PORTAL_PAT_RW` 만 쓴다(§5.1 원칙 10).

    이 클라이언트는 create_object·update_object·add_object_alias·link_objects 를 부르므로 좌석 자유조회가 쓰는 읽기 전용 PAT 로는
    열지 않는다. 보고서 도구는 계약 밖이다(보고서는 사람 이름 — 사용자 결정 10-31). 키가 없으면 available=False 인 객체가 나온다 —
    보내는 쪽(RaSender)은 그때 꺼져 있고 sync_summary 가 그 사실(credential_missing)을 말한다.
    """
    token = (secrets or {}).get(WRITE_SECRET_KEY)
    return RaClient(getattr(settings, "gateway_mcp", ""), token, client=client, deadline_s=deadline_s, gate=gate)


# ---------------------------------------------------------------- 보내는 쪽(RK-01 — 사용자 결정 10-31 D-1 (가))
# external_sync.ra 에 쌓인 op(라벨 상태 병합 · verified_by|refuted_by 연결 — metrics, X태그 승격의 design_trait · exhibits —
# character)를 RA 도구 호출로 옮긴다. 자격은 박스 쓰기 PAT 하나다 — 사람이 없는 배경 잡이라 사람의 등록 PAT(_user_credentials)도
# 읽기 PAT 도 쓰지 않는다. RA 에 적히는 주인은 그 PAT 의 계정이고, 누가 했는지는 앱 DB 의 owner_sub 가 맡는다(plan §5.3.5).
# 키는 틱마다 다시 읽는다 — 넣으면 재기동 없이 다음 동기 주기부터 켜지고, 없으면 아무것도 부르지 않는다.
SENDER_CHANNELS = ("ra",)
# 호출 한 건의 벽시계 기한(초) — 게이트웨이의 RA 호출 한도(GATEWAY_CALL_TIMEOUT, plan §5.3.5 120 s)와 같다. 넘기면 transient 다.
SEND_DEADLINE_S = 120.0
# 한 동기 주기(sync_loop 60초)에 보내는 대상 수 · 벽시계 초의 상한 — 넘으면 남은 대상은 상태 그대로 다음 주기로 미룬다. 처음 키를 넣은 박스 ·
# 오래 보류됐다 풀린 과제의 대상 수백 개를 한 틱에 비우는 동안 같은 루프의 PAT 폐기 대조(60초)가 멈추지 않게 한다.
SEND_TICK_MAX_TARGETS = 50
SEND_TICK_BUDGET_S = 30.0
LABEL_RELATIONS = ("verified_by", "refuted_by")
# verified_by · refuted_by 의 dst 축(plan §5.3.2). 라벨 근거 `inc:<RA 객체 id>` 가 이 축의 객체일 때만 잇는다.
LABEL_DST_TYPES = ("incident", "test_run")
# 다시 보내 볼 HTTP 상태 — 그 밖의 4xx 는 고치기 전에는 같은 답이다.
_RETRY_HTTP = frozenset({408, 425, 429})
_HTTP_5XX_RX = re.compile(r"\bHTTP 5\d\d\b")
# 실패 사유 낱말(sync_summary 의 reason) — 이 낱말로 last_error 를 `<낱말>: <글>` 꼴로 적는다. transient 만 백오프로 다시 보낸다.
# 채널 전체가 막히는 실패(unauthorized · read_only · forbidden · tool_missing · ontology_missing · 게이트웨이의 그 밖 4xx)는 그 대상을 곧바로
# unavailable 로 멈춘다. op 하나에만 걸린 영구 거절(RA 의 거절 · value_collision · masked_readback · 꼴이 틀린 op)은 그 op 만 dead_ops 에
# 까닭과 함께 따로 두고 대상의 나머지 op 를 계속 보낸다 — 멈추면 그 op 가 맨 앞에 남아 대상의 RA 채널이 영영 막힌다. 둘 다 사람이 고친 뒤 '재동기'.
FAIL_TEXT: dict[str, str] = {
    "unauthorized": "게이트웨이 · RA 가 박스 쓰기 PAT 를 받지 않는다(만료 · 폐기 · 다른 박스의 토큰)",
    "read_only": "박스 쓰기 PAT 가 읽기 전용이다(scopes 에 write 가 없다)",
    "forbidden": "그 PAT 의 계정에 RA 쓰기 권한이 없다(RA 시스템 관리자 · 포털 권한표 · 외부 연결 등록을 본다)",
    "tool_missing": "게이트웨이에 RA 도구가 없다(RA 백엔드가 붙어 있지 않다)",
    "ontology_missing": "RA 에 리스크 축 · 관계가 없다(bootstrap_ra_ontology.py --apply 를 아직 돌리지 않았다)",
    "masked_readback": "게이트웨이가 가린 속성 값을 되쓰게 되어 멈췄다(통째 교체라 가린 글이 RA 원본을 덮는다)",
    "value_collision": "RA 가 같은 code 대신 값이 겹친 다른 객체를 돌려줬다",
    "id_mismatch": "사상된 RA id 의 객체가 이 앱의 것이 아니다(값이 @<code> 로 끝나지 않는다 — 다른 박스에서 들여온 사상이거나 RA 에서 바뀌었다)",
    "rejected": "RA 가 이 op 를 받지 않았다",
    "transient": "여러 번 보내지 못했다(게이트웨이 · RA 불통 · 시간 초과)",
}
# RA 에 잇지 않기로 한 op 의 까닭 — 큐에서는 빼고 건수와 마지막 까닭을 채널에 남긴다(skipped_n · last_skip).
SKIP_TEXT: dict[str, str] = {
    "evidence_not_ra_object": "라벨 근거가 RA 사고 · 시험 객체(inc:<RA 객체 id>)가 아니다",
    "evidence_not_incident_or_test_run": "근거로 적은 RA 객체가 사고 · 시험이 아니거나 없다",
    "registry_absent": "그 finding 이 실린 등록부 행이 없다",
    "project_purged": "과제가 폐기됐다 — 폐기 뒤에는 RA 에 새로 보내지 않는다(이미 나간 객체는 거두기 op 가 거둔다)",
}

# 거두기(RK-01 — 사용자 결정 10-31 (가)). 과제가 조직 공개를 떠나거나(비공개) 폐기 · 이양되면 RA 에 나간 객체(과제 · 등록부 risk_finding)마다
# 거두기 op 를 쌓는다 — {op: retract, reason, kind(rr_id_map 의 portal_kind), portal_id, project_id, by(그렇게 한 사람)}. 보류(withheld) ·
# 폐기를 건너뛰어 나가고(폐기된 과제의 보낼 op 는 버린다), 다시 표기할 꼴은 op 가 아니라 **보낼 때의 정본 범위**로 정한다(원칙 3) — 조직
# 공개가 아니거나 폐기면 거둔 꼴, 조직 공개면 나간 꼴(이양 뒤의 owner · 다시 연 과제). 그래서 큐의 같은 꼴 버림 · 순서와 상관없이 마지막에
# 나간 op 가 정본을 따른다.
# RA 의 객체 모델(dev 사본 3ece194)이 허락하는 것만 한다 — MCP 쓰기는 create · update · alias · link 넷뿐이라 객체를 지우거나 연결을 끊지
# 못하고, 엔티티 상태(deprecated)도 MCP update 가 넘기지 않는다. update 로 바꿀 수 있는 value · description · properties(통째 교체,
# 빈 값은 RA 가 뺀다)로 거둔다.
RETRACT_OP = "retract"
# private · purged 는 거두기, owner · org 는 다시 표기(이양 뒤 owner · 다시 연 과제)다 — 셋 다 보낼 때의 정본 범위로 꼴을 고른다.
RETRACT_REASONS = ("private", "purged", "owner", "org")
PULL_BACK_REASONS = ("private", "purged")
# 거둔 꼴의 value 머리 — value 는 RA 가 비워 두지 못하므로(최소 1자) 과제 코드 · 메커니즘을 뺀 '비공개@<code>' 로 바꾼다(축 안 유니크는 code 가 맡는다).
RETRACT_HEAD = "비공개"
RETRACT_TYPES = {"project": "project", "registry": "risk_finding"}
# 거둔 꼴에서 risk_finding 이 빼는 속성 — 앱의 투영이 채운 칸이다(지금은 owner · status, M4 의 패널 투영이 채울 칸이 생기면 여기에 더한다 —
# test_the_retracted_form_drops_every_property_the_projection_writes 가 _registry_object 의 칸과 견준다). 되짚을 열쇠 둘과 visibility 는 거둔 꼴이
# 다시 쓴다. RA 에서 따로 단 칸(운영자 · 다른 도구)은 그대로 둔다 — 게이트웨이가 가려 읽힌 칸만 뺀다(통째 교체라 가린 글을 되쓰면 원본을 덮는다).
RETRACT_DROP_KEYS = ("owner", "status")
# 누가 닫았는지 모르는 뒤처리(폐기 보고서 · 가시성 토글에 행위자가 없다 — 들여온 과제 등)의 감사 행위자 — 검증되지 않은 행위자로 적는다.
SYSTEM_ACTOR = "system"


def sender_status(settings=None, secrets: Mapping[str, str] | None = None) -> dict:
    """RA 보내는 쪽의 지금 상태 — {on, reason, message}. 박스 쓰기 PAT 가 있으면 켜져 있다(그 밖의 자격은 보지 않는다)."""
    cfg = config.settings if settings is None else settings
    values = config.load_secrets(cfg.data_dir) if secrets is None else secrets
    if (values.get(WRITE_SECRET_KEY) or "").strip():
        return {"on": True, "reason": "wired",
                "message": f"RA 보내는 쪽 켜짐 — 박스 쓰기 PAT({WRITE_SECRET_KEY})로 게이트웨이를 거쳐 RA 지식 그래프에 쓴다."}
    return {"on": False, "reason": f"credential_missing:{WRITE_SECRET_KEY}",
            "message": (f"RA 보내는 쪽 꺼짐 — 박스에 RA 쓰기 자격({WRITE_SECRET_KEY})이 없다. secrets.env 에 넣으면 다음 동기"
                        " 주기부터 나간다(재기동은 필요 없다).")}


class _Stop(Exception):
    """op 하나를 보내다 멈춘 까닭 — code 는 FAIL_TEXT 의 낱말이다. retry 면 백오프, op_only 면 그 op 만 따로 두고 다음 op 로 간다,
    둘 다 아니면 그 대상을 unavailable 로 멈춘다. code 'closed' 는 보내는 도중 과제가 닫혔다는 표지다(부르지 않았다)."""

    def __init__(self, code: str, detail: str, *, retry: bool = False, op_only: bool = False) -> None:
        super().__init__(detail)
        self.code = code
        self.retry = retry
        self.op_only = op_only
        self.text = f"{code}: {' '.join(str(detail).split())[:240]}"


def _flat(value: Any) -> str:
    if isinstance(value, (Mapping, list, tuple)):
        try:
            return canonical_json(value)
        except (TypeError, ValueError):
            return str(value)
    return "" if value is None else str(value)


def _gateway_refusal(tool: str, text: str) -> _Stop:
    """게이트웨이가 isError 로 돌려준 글 — 거절 넷은 사람이 고칠 것이고, 나머지(백엔드 불통 · 시간 초과 · 위임 실패)는 다시 보낸다."""
    if text.startswith("read_only:"):
        return _Stop("read_only", f"{tool} — {text}")
    if text.startswith("forbidden:"):
        return _Stop("forbidden", f"{tool} — {text}")
    if text.startswith("unknown tool:"):
        return _Stop("tool_missing", f"{tool} — {text}")
    if "등록되어 있지 않습니다" in text:          # 위임이 꺼진 박스 — 포털 외부 연결에 그 계정의 RA 토큰이 없다
        return _Stop("forbidden", f"{tool} — {text}")
    return _Stop("transient", f"{tool} — {text}", retry=True)


def _ra_refusal(tool: str, payload: Mapping[str, Any]) -> _Stop:
    """RA 가 성공 답 안에 실은 {'error': …} — RA MCP 는 HTTP 상태를 글로만 넘긴다(ReportArchive mcp_server._unwrap). 관리자 · 온톨로지 ·
    토큰 글은 채널 전체이고, 객체를 못 찾음 · 그 밖의 거절(관계 축 제약 · enum · 길이 · 닫힌 축)은 그 op 에만 걸린 것이다."""
    text = " ".join(f"{payload.get('error')} {_flat(payload.get('detail'))}".split())
    if "시스템 관리자" in text:                 # 온톨로지 쓰기는 시스템 관리자 전용(require_system_admin)
        return _Stop("forbidden", f"{tool} — {text}")
    if "알 수 없는 타입" in text:
        return _Stop("ontology_missing", f"{tool} — {text}")
    if "찾을 수 없습니다" in text:
        return _Stop("not_found", f"{tool} — {text}", op_only=True)
    if "이미 같은 값이 있습니다" in text:          # value 를 바꾸는 update_object 의 같은 축 값 겹침(RA update_entity)
        return _Stop("value_collision", f"{tool} — {text}", op_only=True)
    if "토큰" in text or "인증" in text:
        return _Stop("unauthorized", f"{tool} — {text}")
    if "Internal server error" in text or _HTTP_5XX_RX.search(text):
        return _Stop("transient", f"{tool} — {text}", retry=True)
    return _Stop("rejected", f"{tool} — {text}", op_only=True)


def _result(reply: Mapping[str, Any], tool: str) -> dict:
    """도구 답 → 값. 실패면 _Stop 을 던진다 — 전송 · 게이트웨이 · RA 세 층의 실패를 사유 낱말로 가른다."""
    if not reply.get("ok"):
        error, detail = str(reply.get("error") or ""), _flat(reply.get("detail"))
        if error == "http_401":
            raise _Stop("unauthorized", f"{tool} — 게이트웨이 HTTP 401 {detail}")
        if error == "http_403":
            raise _Stop("forbidden", f"{tool} — 게이트웨이 HTTP 403 {detail}")
        if error.startswith("http_"):
            status = int(reply.get("status") or 0)
            retry = status >= 500 or status in _RETRY_HTTP
            raise _Stop("transient" if retry else "rejected", f"{tool} — 게이트웨이 HTTP {status} {detail}", retry=retry)
        if error in ("transport_error", DEADLINE_EXCEEDED, "unparsable_response"):
            raise _Stop("transient", f"{tool} — {error} {detail}", retry=True)
        if error == "tool_error":
            raise _gateway_refusal(tool, detail)
        if error == "masked_readback":                                  # 그 객체의 속성에만 걸린 것이다
            raise _Stop("masked_readback", f"{tool} — 가린 칸 {detail}", op_only=True)
        if error == "closed":
            raise _Stop("closed", f"{tool} — 보내는 도중 과제가 조직 공개를 떠났거나 폐기됐다(부르지 않았다)")
        raise _Stop("rejected", f"{tool} — {error} {detail}")          # rpc_error(인자 꼴) · tool_not_contracted
    payload = reply.get("result")
    if isinstance(payload, Mapping) and payload.get("error"):
        raise _ra_refusal(tool, payload)
    if not isinstance(payload, Mapping):
        raise _Stop("rejected", f"{tool} — 객체가 아닌 답 {_flat(payload)[:120]}")
    return dict(payload)


def _props(op: Mapping[str, Any]) -> dict:
    """op 의 속성 — 값이 없는 칸은 싣지 않는다(RA 속성 스키마가 null 을 받지 않을 수 있다)."""
    return {k: v for k, v in dict(op.get("props") or {}).items() if v is not None}


def _value(head: str, code: str) -> str:
    """value(≤255)는 축 안에서 대소문자 무시 유니크라 code 를 꼬리에 단다 — plan §5.3.1 의 꼴만으로는 같은 과제의 다른 대상 · 같은 과제
    코드의 다른 주인과 겹쳐, code 가 맞는 객체가 없을 때 RA 가 값이 겹친 남의 객체를 돌려준다(resolve_existing)."""
    return f"{head[:max(0, 254 - len(code))]}@{code}"


def _finding_object(store, project: Mapping[str, Any], finding_id: Any) -> dict | None:
    """라벨 op 의 finding → 그 finding 이 실린 등록부 행의 RA risk_finding(plan §5.3.1 — 단위는 등록부 클러스터, code
    `<target_key>#<cluster_key>`). 행을 고르는 규칙은 registry.merge 와 같다(별칭을 거친 대표 키 · improvement 는 접미 행)."""
    from app import learning, registry  # noqa: PLC0415 — 둘 다 무겁고 metrics 가 이 모듈을 먼저 부른다.

    # 라벨 op 를 낸 쪽(metrics._finding_row)과 같은 거름 — 카드 대조 원자에는 라벨이 붙지 않는다(M2 #20).
    row = store.query_one(
        "SELECT target_key, cluster_key, owner_sub, direction FROM rr_findings WHERE finding_id = ?"
        " AND COALESCE(source_kind, '') <> 'card_review'", (str(finding_id or ""),))
    if row is None:
        return None
    base = learning.resolve_cluster_key(store, str(row["cluster_key"]), owner_sub=str(row["owner_sub"])) or str(row["cluster_key"])
    key = base + registry.IMPROVEMENT_SUFFIX if row["direction"] == "improvement" else base
    reg = _registry_row(store, str(row["target_key"]), key)
    return None if reg is None else _registry_object(project, reg)


def _registry_row(store, target_key: str, cluster_key: str) -> Mapping[str, Any] | None:
    return store.query_one(
        "SELECT target_key, cluster_key, owner_sub, mechanism, mechanism_detail, status FROM rr_registry"
        " WHERE target_key = ? AND cluster_key = ?", (target_key, cluster_key))


def _registry_object(project: Mapping[str, Any], reg: Mapping[str, Any]) -> dict:
    """등록부 행 → RA risk_finding 의 나간 꼴(value · 앱이 쥔 속성 · 보낼 때의 status)."""
    code = f"{reg['target_key']}#{reg['cluster_key']}"
    head = f"{project['code']}@{reg['mechanism'] or 'unclassified'}.{reg['mechanism_detail'] or 'unclassified'}"
    # 원칙 9 의 투영 범위 표기(owner · visibility)와 되짚을 열쇠만 앱이 쥔다 — 나머지 투영 속성은 패널 때 쓰는 쪽(M4)의 몫이다.
    owned = {"cluster_key": reg["cluster_key"], "portal_registry_key": code, "owner": project["owner_sub"],
             "visibility": project["mcp_visibility"]}
    return {"type_slug": "risk_finding", "code": code, "value": _value(head, code), "owned": owned,
            "kind": "registry", "portal_id": code, "owner_sub": reg["owner_sub"], "status": reg["status"],
            "mirror": ("UPDATE rr_registry SET ra_entity_id = ? WHERE target_key = ? AND cluster_key = ?",
                       (reg["target_key"], reg["cluster_key"]))}


def _trait_object(op: Mapping[str, Any], owner_sub: str) -> dict:
    """X태그 승격 op 의 통제 태그 → RA design_trait(value = code = `char:<axis>:<value>`, plan §5.3.1). 어휘 객체라 주인이 따로 없다."""
    tag = str(op.get("tag") or "")
    parts = tag.split(":", 2)
    if len(parts) != 3 or parts[0] != "char" or not parts[1] or not parts[2]:
        raise _Stop("rejected", f"설계 성격 태그가 char:<축>:<값> 꼴이 아니다 — {tag!r}", op_only=True)
    return {"type_slug": "design_trait", "code": tag, "value": tag, "owned": {"axis": parts[1], "token": parts[2]},
            "kind": "trait", "portal_id": tag, "owner_sub": owner_sub, "mirror": None}


def _project_object(project: Mapping[str, Any]) -> dict:
    """과제 → RA project(code = 과제 id, plan §5.3.5 ①). 속성은 싣지 않는다 — 기존 축이라 앱이 정한 속성이 없다."""
    code = str(project["id"])
    return {"type_slug": "project", "code": code, "value": _value(str(project["code"]), code), "owned": {},
            "description": f"HWAX 리스크 심사 과제 — {project['name'] or project['code']}",
            "kind": "project", "portal_id": code, "owner_sub": project["owner_sub"],
            "mirror": ("UPDATE rr_projects SET ra_entity_id = ? WHERE id = ?", (code,))}


def _mapped_id(store, obj: Mapping[str, Any]) -> int | None:
    row = store.query_one("SELECT ra_entity_id FROM rr_id_map WHERE portal_kind = ? AND portal_id = ?",
                          (obj["kind"], obj["portal_id"]))
    return int(row["ra_entity_id"]) if row is not None and row["ra_entity_id"] is not None else None


def _record_id(store, obj: Mapping[str, Any], ra_id: int) -> None:
    """rr_id_map 의 RA 칸과 원본 표의 ra_entity_id(조회 편의용 중복)를 함께 적는다(plan §5.5.2) — AIDataHub 칸은 건드리지 않는다."""
    with store.tx():
        store.execute(
            "INSERT INTO rr_id_map(portal_kind, portal_id, owner_sub, ra_entity_id, ra_type_slug, ra_synced_at)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(portal_kind, portal_id) DO UPDATE SET"
            " ra_entity_id = excluded.ra_entity_id, ra_type_slug = excluded.ra_type_slug, ra_synced_at = excluded.ra_synced_at",
            (obj["kind"], obj["portal_id"], obj["owner_sub"], ra_id, obj["type_slug"], now_epoch()))
        if obj.get("mirror"):
            sql, params = obj["mirror"]
            store.execute(sql, (ra_id, *params))


def _ensure(store, ra: RaClient, obj: Mapping[str, Any], patch: Mapping[str, Any] | None = None) -> int:
    """객체의 RA id. rr_id_map 에 있으면 get_object 로 살아 있는지 보고, 없으면(또는 RA 에서 사라졌으면) code 로 create_object 한다.
    patch 가 있으면(merge_object) 앱이 쥔 속성과 함께 그 객체의 지금 속성에 병합해 update_object 로 보낸다(upsert_props)."""
    want = {k: v for k, v in {**obj["owned"], **dict(patch or {})}.items() if v is not None}
    ra_id, current = _mapped_id(store, obj), None
    if ra_id is not None:
        try:
            current = _result(ra.get_object(obj["type_slug"], ra_id), "get_object")
        except _Stop as stop:
            if stop.code != "not_found":
                raise
            ra_id = None
    if ra_id is None:
        made = _result(ra.create_object(obj["type_slug"], obj["value"], obj["code"], want,
                                        description=obj.get("description")), "create_object")
        current = made.get("object") if isinstance(made.get("object"), Mapping) else {}
        if str(current.get("code") or "").casefold() != obj["code"].casefold() or current.get("id") is None:
            raise _Stop("value_collision", f"create_object — code {obj['code']} 대신 id {current.get('id')} ·"
                                           f" code {current.get('code')!r} 가 돌아왔다(값 {obj['value']!r})", op_only=True)
        ra_id = int(current["id"])
        if made.get("created"):
            _record_id(store, obj, ra_id)
            return ra_id
    if patch is not None:
        _result(ra.upsert_props(obj["type_slug"], ra_id, want, current=current), "update_object")
    _record_id(store, obj, ra_id)
    return ra_id


def _label_dst(ra: RaClient, evidence_ref: Any) -> int | str:
    """라벨 근거 → verified_by · refuted_by 의 dst(RA 사고 · 시험 객체 id). 그런 객체가 아니면 잇지 않고 까닭 낱말을 돌려준다 —
    concerns → part 를 RA 에 part 가 있을 때만 잇는 것(plan §5.3.5 ⑥)과 같은 규칙이다. 사고 · 시험 객체를 만들지 않는다."""
    ref = parse_ref(str(evidence_ref or ""))
    oid = str((ref or {}).get("object_id") or "")
    if not ref or ref.get("kind") != "inc" or not oid.isdigit():
        return "evidence_not_ra_object"
    for type_slug in LABEL_DST_TYPES:
        try:
            _result(ra.get_object(type_slug, oid), "get_object")
        except _Stop as stop:
            if stop.code == "not_found":
                continue
            raise
        return int(oid)
    return "evidence_not_incident_or_test_run"


def _send_op(store, ra: RaClient, target: Mapping[str, Any], projects: Mapping[str, Mapping[str, Any]],
             op: Mapping[str, Any]) -> str | None:
    """op 하나 → RA 도구 호출. 보냈으면 None, RA 에 잇지 않기로 했으면 그 까닭 낱말(SKIP_TEXT), 멈춰야 하면 _Stop 을 던진다."""
    kind, what = op.get("op"), op.get("type") or op.get("relation")
    project = projects[str(op.get("project_id") or target["project_id"])]
    if kind == "merge_object" and what == "risk_finding":
        obj = _finding_object(store, project, op.get("finding_id"))
        if obj is None:
            return "registry_absent"
        # status 는 보낼 때의 등록부 값이다(원칙 3 — 투영은 정본을 따라간다). 라벨의 병합 op 는 라벨마다 달라(머리의 label_id) 큐가 줄이거나
        # complete 가 함께 지우지 않지만, op 에 적힌 값은 라벨 때의 값이라 따로 둔 op 를 재동기로 늦게 보내면 그 사이 나간 새 값을 덮는다.
        # 그때의 등록부 값을 실으면 어느 op 가 마지막에 나가도 RA 가 앱과 같다.
        patch = _props(op)
        if obj["status"]:
            patch["status"] = obj["status"]
        _ensure(store, ra, obj, patch)
        return None
    if kind == "merge_object" and what == "design_trait":
        _ensure(store, ra, _trait_object(op, str(target["owner_sub"])), _props(op))
        return None
    if kind == "link" and what in LABEL_RELATIONS:
        obj = _finding_object(store, project, op.get("finding_id"))
        if obj is None:
            return "registry_absent"
        dst = _label_dst(ra, op.get("evidence_ref"))
        if isinstance(dst, str):
            return dst
        _result(ra.link_objects(_ensure(store, ra, obj), dst, str(what), properties=_props(op)), "link_objects")
        return None
    if kind == "link" and what == "exhibits":
        src = _ensure(store, ra, _project_object(project))
        dst = _ensure(store, ra, _trait_object(op, str(target["owner_sub"])))
        _result(ra.link_objects(src, dst, "exhibits", properties=_props(op)), "link_objects")
        return None
    raise _Stop("rejected", f"모르는 op — {kind}:{what}", op_only=True)


def is_retract_op(op: Any) -> bool:
    return isinstance(op, Mapping) and op.get("op") == RETRACT_OP


def _pulls_back(op: Any) -> bool:
    """거두기(비공개 · 폐기)로 쌓인 op 인가 — 요약 · 폐기 보고서가 센다. 이양 · 다시 공개의 다시 표기는 세지 않는다."""
    return is_retract_op(op) and op.get("reason") in PULL_BACK_REASONS


def _retract_key(op: Mapping[str, Any]) -> str:
    return f"{op.get('kind')}:{op.get('portal_id')}"


def _retract_id(store, kind: str, code: str) -> int | None:
    """거둘 객체의 RA id — rr_id_map(정본)이 없으면 원본 표의 ra_entity_id(조회 편의용 중복)를 본다."""
    found = _mapped_id(store, {"kind": kind, "portal_id": code})
    if found is not None:
        return found
    if kind == "project":
        row = store.query_one("SELECT ra_entity_id FROM rr_projects WHERE id = ?", (code,))
    else:
        target_key, _, cluster_key = code.partition("#")
        row = store.query_one("SELECT ra_entity_id FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
                              (target_key, cluster_key))
    return int(row["ra_entity_id"]) if row is not None and row["ra_entity_id"] is not None else None


def _retract_op(store, ra: RaClient, op: Mapping[str, Any]) -> dict:
    """거두기 op 하나 → RA 객체 하나를 보낼 때의 정본 범위로 다시 표기한다. 결과 {op, form, outcome, ra_id, type[, dropped]}.

    - 거둔 꼴(과제가 조직 공개가 아니거나 폐기) — value 를 '비공개@<code>' 로, 과제는 설명을 비우고, risk_finding 은 앱의 투영이 채운 칸
      (RETRACT_DROP_KEYS — owner · status)을 빼고 visibility=private · 되짚을 열쇠 둘을 쓴다. RA 에서 따로 단 칸은 그대로 둔다 — 다만 게이트웨이가
      가려 읽힌 칸은 되쓸 수 없어(통째 교체라 가린 글이 원본을 덮는다) 뺀다(공개 범위가 앞선다 — 뺀 칸 이름은 결과의 dropped).
    - 나간 꼴(조직 공개) — value · 과제 설명을 되돌리고 risk_finding 은 지금 속성에 owner · visibility=org · 보낼 때의 등록부 status 를 병합한다.
    outcome 은 retracted(거뒀다) · remarked(다시 표기했다) · unchanged(이미 그 꼴이라 부르지 않았다) · absent(RA 에 그 객체가 없다 — 거둘 것이
    없다). 사상된 id 의 객체 값이 @<code> 로 끝나지 않으면 남의 객체라 쓰지 않는다(id_mismatch — 그 op 만 따로 둔다).
    """
    kind, code = str(op.get("kind") or ""), str(op.get("portal_id") or "")
    type_slug = RETRACT_TYPES.get(kind)
    if type_slug is None or not code or (kind == "registry" and "#" not in code):
        raise _Stop("rejected", f"거두기 op 의 꼴이 틀렸다 — {kind}:{code}", op_only=True)
    project = store.query_one("SELECT id, owner_sub, code, name, status, mcp_visibility FROM rr_projects WHERE id = ?",
                              (str(op.get("project_id") or ""),))
    form = "shared" if project is not None and project["status"] != "purged" and project["mcp_visibility"] == "org" \
        else "retracted"
    result = {"op": dict(op), "form": form, "type": type_slug, "ra_id": None}
    ra_id = _retract_id(store, kind, code)
    if ra_id is None:
        return {**result, "outcome": "absent"}
    result["ra_id"] = ra_id
    try:
        current = _result(ra.get_object(type_slug, ra_id), "get_object")
    except _Stop as stop:
        if stop.code != "not_found":
            raise
        return {**result, "outcome": "absent"}
    label = str(current.get("label") or "")
    if not label.casefold().endswith(f"@{code}".casefold()):
        raise _Stop("id_mismatch", f"get_object — {type_slug} id {ra_id} 의 값 {label[:120]!r} 이 @{code} 로 끝나지 않는다",
                    op_only=True)
    props = dict(current.get("properties") or {}) if isinstance(current.get("properties"), Mapping) else {}
    description: str | None = None
    properties: dict | None = None
    if form == "retracted":
        value = _value(RETRACT_HEAD, code)
        if kind == "project":
            description = ""
        else:
            own = {"cluster_key": code.partition("#")[2], "portal_registry_key": code, "visibility": "private"}
            foreign = {k: v for k, v in props.items() if k not in own and k not in RETRACT_DROP_KEYS}
            masked = sorted(k for k, v in foreign.items() if is_masked(v))
            properties = {**{k: v for k, v in foreign.items() if k not in masked}, **own}
            if masked:
                result["dropped"] = masked
    elif kind == "project":
        shared = _project_object(project)
        value, description = shared["value"], shared["description"]
    else:
        target_key, _, cluster_key = code.partition("#")
        reg = _registry_row(store, target_key, cluster_key)
        if reg is None:
            raise _Stop("rejected", f"다시 표기할 등록부 행이 없다 — {code}", op_only=True)
        shared = _registry_object(project, reg)
        want = {k: v for k, v in {**shared["owned"], "status": shared["status"]}.items() if v is not None}
        lost = sorted(k for k, v in props.items() if is_masked(v) and k not in want)
        if lost:
            raise _Stop("masked_readback", f"update_object — 가린 칸 {lost}", op_only=True)
        value, properties = shared["value"], {**props, **want}
    if description is None and value == label and (properties is None or properties == props):
        return {**result, "outcome": "unchanged"}
    _result(ra.update_object(ra_id, properties, value=value, description=description), "update_object")
    return {**result, "outcome": "retracted" if form == "retracted" else "remarked"}


def _projects(store, ids: Sequence[str]) -> dict[str, Mapping[str, Any] | None]:
    return {pid: store.query_one("SELECT id, owner_sub, code, name, status, mcp_visibility FROM rr_projects WHERE id = ?", (pid,))
            for pid in ids}


def _closed(target: Mapping[str, Any] | None, projects: Mapping[str, Mapping[str, Any] | None]) -> dict | None:
    """대상과 그 op 가 가리키는 과제가 지금 보낼 수 없으면 그 결과, 보낼 수 있으면 None — 대상 · 과제가 없으면 거절(멈춤), 폐기면
    {'purged': True}(보낼 op 는 버린다 — _drop_purged), 조직 공개가 아니면 보류."""
    if target is None or any(p is None for p in projects.values()):
        return {"error": "rejected: 대상이나 그 과제가 없다 — RA 에 올리지 않는다", "retry": False}
    if any(p["status"] == "purged" for p in projects.values()):
        return {"purged": True}
    if any(p["mcp_visibility"] != "org" for p in projects.values()):
        return {"hold": "withheld"}
    return None


def _drop_purged(out: dict, ops: Sequence[Mapping[str, Any]]) -> dict:
    """폐기된 과제의 보낼 op 를 큐에서 뺀다 — 'RA 에 잇지 않은 것'(project_purged)으로 센다. 폐기 뒤에는 RA 에 새로 보내지 않고 되살리는 길도
    없다. 종전에는 대상을 rejected 로 멈춰(unavailable) 폐기가 쌓은 거두기 op 까지 멈춘 큐에 갇혔다(RK-01 거두기 반대 검토)."""
    out.setdefault("done", []).extend(ops)
    out.setdefault("skipped", []).extend(["project_purged"] * len(ops))
    return out


class RaSender:
    """retry_external_sync 의 전송기 — 타깃 하나의 external_sync.ra 대기 op 를 순서대로 RA 도구 호출로 보내고 결과를 dict 로 돌려준다.

    결과 — done(큐에서 뺄 op: 보냈거나 RA 에 잇지 않기로 한 것) · skipped(그 가운데 잇지 않은 것의 까닭 낱말) · dead(그 op 에만 걸린 영구
    거절 — {op, error}, 큐에서 빼 따로 둔다) · retracts(나간 거두기 op 의 결과 — _retract_op) · hold('withheld' — 과제가 조직 공개가 아니다,
    plan §5.5.3) · error('<낱말>: <글>' — 채널 전체가 막혔다, 그 op 와 뒤의 op 는 큐에 남는다) · retry(참이면 백오프, 거짓이면 unavailable) ·
    off(자격이 없어 아무것도 부르지 않았다). 상태 전이는 retry_external_sync 가 한다. 과제의 가시성 · 폐기는 틱 머리와 **호출마다** 다시 본다 —
    보내는 도중 비공개로 돌리거나 폐기하면 다음 호출부터 하지 않는다(원칙 9). 거두기 op 만은 그 문을 지나지 않는다 — 닫힌 과제에서도 큐 순서대로
    나가고(앞에 쌓인 보낼 op 는 비공개면 보류, 폐기면 버린다 — project_purged), 열린 과제에서는 앞에 쌓인 op 다음에 나간다. 폐기로는 대상을
    멈추지 않는다 — 멈추면 폐기가 쌓은 거두기 op(보내는 도중 · 이 틱의 스냅숏 뒤에 쌓인 것)가 멈춘 큐에 갇힌다. 호출마다 새 MCP 세션을 연다 —
    게이트웨이가 다시 뜨면 묵은 세션 id 는 받지 않는다.
    """

    channels = SENDER_CHANNELS
    # 한 틱의 크기 — nightly.retry_external_sync 가 읽는다(대상 수 · 벽시계 초).
    tick_max_targets = SEND_TICK_MAX_TARGETS
    tick_budget_s = SEND_TICK_BUDGET_S

    def __init__(self, settings, *, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client          # 시험이 MockTransport 를 싣는다. None 이면 부를 때마다 새 연결이다.

    def off_reason(self) -> str | None:
        """꺼져 있으면 그 까닭(sync_summary 의 reason 과 같은 낱말), 켜져 있으면 None."""
        status = sender_status(self.settings)
        return None if status["on"] else status["reason"]

    def __call__(self, store, target_key: str, channel: str, ops: Sequence[Mapping[str, Any]]) -> dict:
        target = store.query_one("SELECT target_key, owner_sub, project_id FROM rr_targets WHERE target_key = ?",
                                 (target_key,))
        ids = sorted({str(target["project_id"]) if target is not None else "",
                      *(str(op["project_id"]) for op in ops if op.get("project_id"))})
        projects = _projects(store, ids)
        closed = _closed(target, projects)
        # 거두기 op 는 보류 · 폐기를 건너뛴다(사용자 결정 10-31 (가)) — 닫힌 과제면 거두기 op 만 보낸다. 나머지는 비공개면 큐에 그대로(보류),
        # 폐기면 버린다(부르지 않는다). 대상 · 과제가 없으면 멈춘다.
        if closed is not None and (target is None or not any(is_retract_op(op) for op in ops)):
            return _drop_purged({}, ops) if closed.get("purged") else closed
        gated = [True]                     # 지금 보내는 op 가 문을 지나야 하는가 — 거두기 op 는 닫힌 과제에도 나간다

        def still_open() -> bool:
            return not gated[0] or _closed(target, _projects(store, ids)) is None

        ra = ra_client_from_settings(self.settings, config.load_secrets(self.settings.data_dir), client=self._client,
                                     deadline_s=SEND_DEADLINE_S, gate=still_open)
        if not ra.available:
            return {"off": sender_status(self.settings)["reason"]}
        done: list[Mapping[str, Any]] = []
        skipped: list[str] = []
        dead: list[dict] = []
        retracts: list[dict] = []
        held = closed is not None          # 닫혔다 — 여기서부터 거두기 op 만 보낸다
        try:
            for op in ops:
                retract = is_retract_op(op)
                if held and not retract:
                    continue
                gated[0] = not retract
                try:
                    if retract:
                        retracts.append(_retract_op(store, ra, op))
                        skip = None
                    else:
                        skip = _send_op(store, ra, target, projects, op)
                except _Stop as stop:
                    if stop.code == "closed":
                        held = True
                        continue
                    # 여기까지 올라온 not_found(찾았던 객체가 잇는 사이에 사라졌다)는 거절과 같다 — 낱말은 FAIL_TEXT 안에서만 쓴다.
                    text = stop.text if stop.code in FAIL_TEXT else f"rejected: {stop.text}"
                    if stop.op_only:
                        dead.append({"op": dict(op), "error": text})
                        continue
                    return {"done": done, "skipped": skipped, "dead": dead, "retracts": retracts, "error": text,
                            "retry": stop.retry}
                done.append(op)
                if skip:
                    skipped.append(skip)
        finally:
            ra.close()
        out = {"done": done, "skipped": skipped, "dead": dead, "retracts": retracts}
        set_aside = [item["op"] for item in dead]
        left = [op for op in ops if not is_retract_op(op) and op not in done and op not in set_aside]
        if held and left:
            # 남은 op 는 보류(비공개)이거나 버린다(폐기 — 멈추면 폐기가 쌓은 거두기 op 가 갇힌다). 그 사이 다시 열렸으면 보류하지 않는다 — 보류는
            # 공개 토글만 풀어 그대로 두면 영영 멈춘다.
            now_closed = _closed(target, _projects(store, ids)) or {}
            if now_closed.get("purged"):
                _drop_purged(out, left)
            else:
                out.update(now_closed)
        return out


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
    return parse_external_sync(row["external_sync_json"] if row is not None else None)


def parse_external_sync(raw: Any) -> dict:
    """external_sync_json 글 → 두 채널이 모두 있는 dict(깨진 글·빠진 채널은 초기값)."""
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
    """새 op 를 쌓는다. done 이었어도 pending 으로 돌아가고, unavailable · withheld 는 그대로다(§5.5.3 마지막 전이 — 보류는 조직 공개로
    풀 때까지, 멈춤은 재동기까지)."""
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
    if entry["state"] not in ("unavailable", "withheld") and entry.get("pending_ops"):
        entry["state"] = "pending"
        entry["done_at"] = None
    save_external_sync(store, target_key, sync)
    return sync


def _settle(entry: dict) -> None:
    """큐가 빈 pending 채널을 done 으로 옮긴다. 보류(withheld)도 같다 — 거두기 op 만 남았던 비공개 대상이 그것을 다 보내면 보류할 것이 없다."""
    if not entry.get("pending_ops") and entry["state"] in ("pending", "withheld"):
        entry["state"] = "done"
        entry["attempts"] = 0
        entry["next_at"] = 0
        entry["done_at"] = now_epoch()


def complete_sync_ops(store, target_key: str, channel: str,
                      ops: Sequence[Mapping[str, Any]]) -> dict:
    """보낸 op 를 큐에서 지운다. 큐가 비면 done 으로 옮긴다."""
    sync = load_external_sync(store, target_key)
    entry = sync[channel]
    done = {canonical_json(dict(op)) for op in ops}
    entry["pending_ops"] = [op for op in entry.get("pending_ops") or []
                            if canonical_json(dict(op)) not in done]
    _settle(entry)
    save_external_sync(store, target_key, sync)
    return sync


def set_aside_sync_ops(store, target_key: str, channel: str, dead: Sequence[Mapping[str, Any]]) -> dict:
    """그 op 에만 걸린 영구 거절({op, error})을 큐에서 빼 dead_ops 에 까닭 · 시각과 함께 둔다 — 대상의 나머지 op 는 계속 나간다. 같은 꼴의
    op 가 이미 있으면 까닭만 새로 적는다. 큐가 비면 done 이다. 재동기(resync)가 큐 앞으로 되돌린다."""
    sync = load_external_sync(store, target_key)
    entry = sync[channel]
    kept = list(entry.get("dead_ops") or [])
    where = {canonical_json(dict(item.get("op") or {})): i for i, item in enumerate(kept)}
    for item in dead:
        op = dict(item.get("op") or {})
        row = {"op": op, "error": str(item.get("error") or ""), "at": now_epoch()}
        key = canonical_json(op)
        if key in where:
            kept[where[key]] = row
        else:
            where[key] = len(kept)
            kept.append(row)
    entry["dead_ops"] = kept
    gone = {canonical_json(dict(item.get("op") or {})) for item in dead}
    entry["pending_ops"] = [op for op in entry.get("pending_ops") or [] if canonical_json(dict(op)) not in gone]
    _settle(entry)
    save_external_sync(store, target_key, sync)
    return sync


def note_sync_skips(store, target_key: str, channel: str, reasons: Sequence[str]) -> dict:
    """RA 에 잇지 않기로 한 op 의 건수와 마지막 까닭(SKIP_TEXT 낱말)을 채널에 더한다 — op 는 큐에서 빠지지만 조용히 사라지지 않는다."""
    sync = load_external_sync(store, target_key)
    entry = sync[channel]
    if reasons:
        entry["skipped_n"] = int(entry.get("skipped_n") or 0) + len(reasons)
        entry["last_skip"] = str(reasons[-1])
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
    """타깃 화면 '재동기' — unavailable 두 채널을 pending(attempts=0, next_at=0) 으로 되돌리고, 따로 둔 op(dead_ops)를 큐 앞으로 되돌린다.
    따로 둔 op 는 큐에 남은 어느 op 보다 앞선 것이라(op 는 순서대로 보내고 걸린 자리에서 뺀다) 앞에 두어야 원래 순서다. 같은 꼴은 한 번만."""
    sync = load_external_sync(store, target_key)
    for channel in SYNC_CHANNELS:
        entry = sync[channel]
        revived = [dict(item["op"]) for item in entry.get("dead_ops") or [] if isinstance(item, Mapping) and item.get("op")]
        if revived:
            seen: set[str] = set()
            merged = []
            for op in revived + list(entry.get("pending_ops") or []):
                key = canonical_json(dict(op))
                if key not in seen:
                    seen.add(key)
                    merged.append(op)
            entry["pending_ops"] = merged
            entry["dead_ops"] = []
        entry["state"] = "pending"
        entry["attempts"] = 0
        entry["next_at"] = 0
        entry["last_error"] = None
    save_external_sync(store, target_key, sync)
    return sync


# ---------------------------------------------------------------- 거두기(RK-01 — 사용자 결정 10-31 (가))
def projected_objects(store, project_id: str) -> list[tuple[str, str, str]]:
    """그 과제에서 RA 로 나간 객체 — (kind, portal_id, 거두기 op 를 둘 대상). rr_id_map(정본)과 원본 표의 ra_entity_id(조회 편의용 중복)를
    함께 본다. 등록부 risk_finding 은 그 행의 대상에, 과제 객체는 과제의 첫 대상(만든 순서 — 새 대상이 생겨도 바뀌지 않는다)에 둔다. 성격
    태그(design_trait)는 과제를 가로지르는 어휘 객체라 거두지 않는다."""
    targets = [str(r["target_key"]) for r in store.query(
        "SELECT target_key FROM rr_targets WHERE project_id = ? ORDER BY created_at, target_key", (project_id,))]
    if not targets:
        return []
    out: list[tuple[str, str, str]] = []
    sent = store.query_one(
        "SELECT (SELECT COUNT(*) FROM rr_id_map WHERE portal_kind = 'project' AND portal_id = ? AND ra_entity_id IS NOT NULL)"
        " + (SELECT COUNT(*) FROM rr_projects WHERE id = ? AND ra_entity_id IS NOT NULL) AS n", (project_id, project_id))
    if sent is not None and int(sent["n"] or 0):
        out.append(("project", project_id, targets[0]))
    rows = store.query(
        "SELECT m.portal_id AS code FROM rr_id_map m JOIN rr_targets t"
        " ON substr(m.portal_id, 1, length(t.target_key) + 1) = t.target_key || '#'"
        " WHERE m.portal_kind = 'registry' AND m.ra_entity_id IS NOT NULL AND t.project_id = ?"
        " UNION SELECT r.target_key || '#' || r.cluster_key FROM rr_registry r JOIN rr_targets t ON t.target_key = r.target_key"
        " WHERE r.ra_entity_id IS NOT NULL AND t.project_id = ? ORDER BY 1", (project_id, project_id))
    out += [("registry", str(r["code"]), str(r["code"]).partition("#")[0]) for r in rows]
    return out


def queue_retracts(store, project_id: str, reason: str, *, by: str) -> int:
    """과제의 RA 객체마다 거두기 op 를 쌓고 그 수를 돌려준다(같은 트랜잭션에서 부른다 — 비공개 전환 · 폐기 · 이양 · 다시 공개).

    private · purged 는 나간 객체 전부, owner 는 owner 속성이 있는 등록부 risk_finding 만, org 는 거둔 꼴로 남은 것(대상의 retracted · absent)만이다.
    op 는 큐 끝에 붙어 앞에 쌓인 보낼 op 다음에 나가고, 같은 꼴은 한 번만 쌓인다(queue_sync_ops). 보류(withheld)인 대상도 그대로 두지만
    거두기 op 가 있으면 동기 주기가 집는다(nightly.retry_external_sync). 거두기(private · purged)는 그 대상을 다음 동기 주기에 집히게 한다
    (_due_now — 앞선 보내기의 백오프를 물려받지 않는다). 채널 전체가 막혀 멈춘(unavailable) 대상은 재동기까지 기다린다.
    """
    if reason not in RETRACT_REASONS:
        raise ValueError(f"모르는 거두기 까닭: {reason!r}")
    if reason == "org":
        picked = []
        for row in store.query("SELECT target_key FROM rr_targets WHERE project_id = ? ORDER BY target_key", (project_id,)):
            entry = load_external_sync(store, str(row["target_key"]))["ra"]
            for key in sorted({*(entry.get("retracted") or {}), *(entry.get("absent") or {})}):
                kind, _, code = key.partition(":")
                picked.append((kind, code, str(row["target_key"])))
    else:
        picked = [item for item in projected_objects(store, project_id) if reason != "owner" or item[0] == "registry"]
    by_target: dict[str, list[dict]] = {}
    for kind, code, target_key in picked:
        by_target.setdefault(target_key, []).append({"op": RETRACT_OP, "reason": reason, "kind": kind, "portal_id": code,
                                                     "project_id": project_id, "by": by})
    for target_key, ops in by_target.items():
        queue_sync_ops(store, target_key, "ra", ops)
        if reason in PULL_BACK_REASONS:
            _due_now(store, target_key)
    return len(picked)


def _due_now(store, target_key: str) -> None:
    """거두기를 쌓은 대상을 다음 동기 주기에 집히게 한다 — 앞선 보내기의 재시도 백오프(next_at — 최대 6시간)를 물려받지 않는다(RK-01 거두기
    반대 검토). 한 번 바로 보내 보고 실패하면 종전 백오프다. 재시도를 다 써서(transient 8회) 멈춘 대상도 한 번 되살린다 — RA 가 돌아왔으면
    재동기 없이 거둔다(attempts 는 그대로라 또 실패하면 곧바로 다시 멈춘다). 채널 전체가 막힌 멈춤(관리자 아님 · 토큰 · 도구 · 온톨로지 ·
    게이트웨이 거절)은 그대로 둔다 — 고치기 전에는 같은 거절이다(재동기를 기다린다)."""
    sync = load_external_sync(store, target_key)
    entry = sync["ra"]
    now = now_epoch()
    if entry["state"] == "pending" and int(entry.get("next_at") or 0) > now:
        entry["next_at"] = now
    elif entry["state"] == "unavailable" and fail_word(entry.get("last_error")) == "transient":
        entry["state"] = "pending"
        entry["next_at"] = now
    else:
        return
    save_external_sync(store, target_key, sync)


def _audit_retract(store, op: Mapping[str, Any], after: Mapping[str, Any]) -> None:
    """거두기 op 하나의 결과를 rr_audit 에 한 행 남긴다 — 행위자는 그 op 를 쌓게 한 사람(비공개 전환 · 폐기 · 이양 · 다시 공개를 한 사람, REST)이고
    뒤따라 쌓은 op 는 과제를 닫거나 연 사람이다(_closing_actor). 누군지 모르면(op 의 by 가 비었다) 'system' 을 검증되지 않은 행위자로 적는다 —
    사람이 한 것으로 적지 않는다(종전에는 과제 소유자를 검증된 행위자로 적었다). 거둔 꼴이면 'ra.retract', 나간 꼴로 다시 표기했으면 'ra.remark'.
    과제 객체는 과제 범위, risk_finding 은 등록부 범위(<target_key>#<cluster_key>)."""
    project_id = str(op.get("project_id") or "")
    actor = str(op.get("by") or "")
    retracted = (after.get("form") == "retracted") if after.get("form") else _pulls_back(op)
    store.execute(
        "INSERT INTO rr_audit(id, owner_sub, actor, actor_verified, channel, scope, subject_id, project_id, action, before_json,"
        " after_json, reason, at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (new_uuid(), actor or SYSTEM_ACTOR, actor or SYSTEM_ACTOR, 1 if actor else 0, "rest",
         "project" if op.get("kind") == "project" else "registry",
         str(op.get("portal_id") or ""), project_id, "ra.retract" if retracted else "ra.remark", None,
         canonical_json(dict(after)), str(op.get("reason") or ""), now_epoch()))


def record_retracts(store, target_key: str, outcome: Mapping[str, Any]) -> None:
    """전송기 결과의 거두기 몫을 적는다(retry_external_sync 의 트랜잭션 안) — 대상의 retracted(지금 거둔 꼴인 객체 → 시각) · absent(거두려니 RA 에
    없던 객체 → 시각)를 고치고, 거두기 op 마다(나갔거나 RA 가 받지 않아 따로 둔 것) rr_audit 한 행을 남긴다. 그다음 과제의 지금 범위와 어긋난 채
    남을 객체에 op 를 뒤따라 쌓고 — 닫힌 과제는 거두지 않은 객체(_catch_up_retracts), 열린 과제는 이 대상에 거둔 꼴로 남은 객체
    (_catch_up_remarks) — 폐기된 과제면 폐기 보고서의 RA 층을 다시 짓는다."""
    applied = [item for item in outcome.get("retracts") or () if isinstance(item, Mapping) and is_retract_op(item.get("op"))]
    refused = [item for item in outcome.get("dead") or () if isinstance(item, Mapping) and is_retract_op(item.get("op"))]
    if applied or refused:
        sync = load_external_sync(store, target_key)
        entry = sync["ra"]
        marks = {name: dict(entry.get(name) or {}) for name in ("retracted", "absent")}
        for item in applied:
            key = _retract_key(item["op"])
            for kept in marks.values():
                kept.pop(key, None)
            if item.get("form") == "retracted":                          # 거두려니 RA 에 없던 것은 거둔 것과 따로 센다
                marks["absent" if item.get("outcome") == "absent" else "retracted"][key] = now_epoch()
            after = {"kind": item["op"].get("kind"), "type": item.get("type"), "ra_entity_id": item.get("ra_id"),
                     "form": item.get("form"), "outcome": item.get("outcome")}
            if item.get("dropped"):
                after["dropped"] = list(item["dropped"])
            _audit_retract(store, item["op"], after)
        for item in refused:
            _audit_retract(store, item["op"], {"kind": item["op"].get("kind"), "outcome": "failed",
                                               "error": fail_word(item.get("error"))})
        for name, kept in marks.items():
            if kept:
                entry[name] = kept
            else:
                entry.pop(name, None)
        save_external_sync(store, target_key, sync)
    row = store.query_one("SELECT p.id AS id, p.status AS status, p.mcp_visibility AS visibility FROM rr_targets t"
                          " JOIN rr_projects p ON p.id = t.project_id WHERE t.target_key = ?", (target_key,))
    if row is None:
        return
    if row["status"] == "purged" or row["visibility"] != "org":
        _catch_up_retracts(store, str(row["id"]), "purged" if row["status"] == "purged" else "private")
    else:
        _catch_up_remarks(store, target_key, str(row["id"]))
    if row["status"] == "purged":
        refresh_purge_report(store, str(row["id"]))


def _project_ra_entries(store, project_id: str) -> dict[str, dict]:
    return {str(r["target_key"]): load_external_sync(store, str(r["target_key"]))["ra"] for r in store.query(
        "SELECT target_key FROM rr_targets WHERE project_id = ? ORDER BY target_key", (project_id,))}


def _retract_states(entries: Mapping[str, Mapping[str, Any]]) -> dict[str, tuple[str, str | None]]:
    """대상 채널들(대상 → RA 채널)에 걸친 객체마다의 거두기 처지 {'<kind>:<portal_id>': (처지, 까닭 낱말)}. 차례는 대기 > 못 거둠 > 거둠 > 없음이고
    한 객체는 한 처지에만 든다 — 요약(retract_counts)과 폐기 보고서(purge_ra_layer)가 같은 차례로 센다.

    - 대기는 언제 나가는지로 셋이다 — pending(다음 동기 주기) · waiting(재시도 대기 — 마지막 시도가 실패해 백오프 중이고 저절로 다시 보낸다,
      까닭은 그 실패의 낱말) · stopped(채널이 멈췄다 — 그 사유 낱말, 고친 뒤 재동기).
    - failed(RA 가 받지 않아 따로 뒀다 — 그 까닭 낱말) · retracted(지금 거둔 꼴이다) · absent(거두려니 RA 에 없었다 — 거둘 것이 없다).
    거두기(비공개 · 폐기)로 쌓인 op 만 대기 · 못 거둠으로 센다 — 이양 · 다시 공개의 다시 표기는 세지 않는다. 표에 없는 객체는 아직 아무 처지도
    아니다(none — 쌓이지 않았다)."""
    now = now_epoch()
    waits: dict[str, tuple[str, str | None]] = {}
    failed: dict[str, str] = {}
    retracted: set[str] = set()
    absent: set[str] = set()
    for entry in entries.values():
        if entry.get("state") == "unavailable":
            wait: tuple[str, str | None] = ("stopped", fail_word(entry.get("last_error")))
        elif entry.get("state") == "pending" and int(entry.get("next_at") or 0) > now:
            wait = ("waiting", fail_word(entry.get("last_error")) if entry.get("last_error") else None)
        else:
            wait = ("pending", None)
        for op in entry.get("pending_ops") or ():
            if _pulls_back(op) and (_retract_key(op) not in waits or wait[0] == "stopped"):
                waits[_retract_key(op)] = wait
        for item in entry.get("dead_ops") or ():
            if isinstance(item, Mapping) and _pulls_back(item.get("op")):
                failed[_retract_key(item["op"])] = fail_word(item.get("error"))
        retracted.update(entry.get("retracted") or {})
        absent.update(entry.get("absent") or {})
    out: dict[str, tuple[str, str | None]] = {key: ("absent", None) for key in absent}
    out.update({key: ("retracted", None) for key in retracted})
    out.update({key: ("failed", why) for key, why in failed.items()})
    out.update(waits)
    return out


def _closing_actor(store, project_id: str, reason: str) -> str:
    """뒤따라 쌓는 op 의 행위자 — 과제를 지금 범위로 만든 사람이다. 폐기면 폐기 보고서의 by(관리자일 수 있다), 비공개 · 다시 공개면 가시성을
    마지막으로 바꾼 사람(mcp_visibility_by). 모르면 빈 글이다(감사 행은 'system' — 검증되지 않은 행위자, _audit_retract)."""
    row = store.query_one("SELECT mcp_visibility_by, purge_report_json FROM rr_projects WHERE id = ?", (project_id,))
    if row is None:
        return ""
    if reason != "purged":
        return str(row["mcp_visibility_by"] or "")
    try:
        report = json.loads(row["purge_report_json"] or "{}")
    except (TypeError, ValueError):
        return ""
    return str(report.get("by") or "") if isinstance(report, Mapping) else ""


def _catch_up_retracts(store, project_id: str, reason: str) -> int:
    """닫힌 과제(비공개 · 폐기)에 거둔 꼴도 아니고 거두기 op 도 없는 RA 객체가 있으면 거두기 op 를 쌓는다 — 비공개로 돌리거나 폐기하는 순간 RA 에
    만드는 호출이 나가 있었으면 그 객체의 id 는 거두기 op 를 쌓은 뒤에야 적혀 빠진다. 받지 않아 따로 둔 것은 다시 쌓지 않는다(재동기를 기다린다).
    행위자는 과제를 닫은 사람이다(_closing_actor — 사람이 한 것을 동기 주기가 마저 한다). 종전에는 비워 두어 감사 행이 과제 소유자를 검증된
    행위자로 적었다 — 관리자가 폐기했어도 소유자였다(RK-01 거두기 반대 검토)."""
    states = _retract_states(_project_ra_entries(store, project_id))
    missing = [(kind, code, target_key) for kind, code, target_key in projected_objects(store, project_id)
               if f"{kind}:{code}" not in states]
    if not missing:
        return 0
    by = _closing_actor(store, project_id, reason)
    by_target: dict[str, list[dict]] = {}
    for kind, code, target_key in missing:
        by_target.setdefault(target_key, []).append({"op": RETRACT_OP, "reason": reason, "kind": kind, "portal_id": code,
                                                     "project_id": project_id, "by": by})
    for target_key, ops in by_target.items():
        queue_sync_ops(store, target_key, "ra", ops)
    return len(missing)


def _catch_up_remarks(store, target_key: str, project_id: str) -> int:
    """열린(조직 공개) 과제의 이 대상에 거둔 꼴로 남은 객체(retracted · absent)가 있는데 그것을 다룰 거두기 op 가 큐에도 따로 둔 것에도 없으면
    다시 표기 op(reason org)를 쌓는다 — 다시 여는 순간 그 대상의 거두기가 나가 있었으면(과제를 읽은 뒤 · 결과를 적기 전) 다시 열기의
    queue_retracts('org') 는 아직 적히지 않은 그 객체를 집지 못하고, 그대로면 과제는 조직 공개인데 RA 는 거둔 꼴로 굳는다(RK-01 거두기 반대
    검토). 행위자는 다시 연 사람(mcp_visibility_by)이다. 거둔 꼴의 표시는 그 객체의 op 가 나간 대상에만 있으므로 이 대상만 본다."""
    entry = load_external_sync(store, target_key)["ra"]
    marked = {*(entry.get("retracted") or {}), *(entry.get("absent") or {})}
    if not marked:
        return 0
    handled = {_retract_key(op) for op in entry.get("pending_ops") or () if is_retract_op(op)}
    handled |= {_retract_key(item["op"]) for item in entry.get("dead_ops") or ()
                if isinstance(item, Mapping) and is_retract_op(item.get("op"))}
    missing = sorted(marked - handled)
    if not missing:
        return 0
    by = _closing_actor(store, project_id, "org")
    queue_sync_ops(store, target_key, "ra", [{"op": RETRACT_OP, "reason": "org", "kind": key.partition(":")[0],
                                              "portal_id": key.partition(":")[2], "project_id": project_id, "by": by}
                                             for key in missing])
    return len(missing)


def purge_ra_layer(store, project_id: str) -> dict:
    """폐기 보고서 remaining 의 RA 층 — 나간 객체 수(objects)와 거둔 수(retracted) · RA 에 이미 없던 수(absent) · 거두기 대기(retract_pending) ·
    못 거둔 수(retract_failed — 따로 뒀거나 쌓이지 않았다), 재시도 대기 · 멈춘 채널 · 못 거둔 객체의 까닭 낱말별 수(reasons). reason 낱말은
    nothing_sent(나간 것이 없다) · retract_pending · retract_failed · retracted(다 거뒀거나 RA 에 이미 없다) 가운데 하나다(종전의 not_retracted 를
    갈음한다). 글은 기다리는 거두기가 언제 나가는지를 채널 상태로 말한다 — 다음 동기 주기 · 재시도 대기(저절로) · 멈춤(고친 뒤 재동기)."""
    objects = projected_objects(store, project_id)
    states = _retract_states(_project_ra_entries(store, project_id))
    tally: Counter = Counter()
    reasons: Counter = Counter()
    for kind, code, _target in objects:
        state, why = states.get(f"{kind}:{code}", ("none", None))
        tally[state] += 1
        if state in ("waiting", "stopped", "failed") and why:
            reasons[why] += 1
        elif state == "none":
            reasons["not_queued"] += 1
    n = len(objects)
    retracted, absent = tally["retracted"], tally["absent"]
    pending = tally["pending"] + tally["waiting"] + tally["stopped"]
    failed = tally["failed"] + tally["none"]
    words = " · ".join(f"{name} {count}" for name, count in sorted(reasons.items()))
    if not n:
        word, detail = "nothing_sent", "RA 로 나간 객체가 없다 — 폐기 뒤에는 새로 보내지 않는다."
    else:
        word = "retract_pending" if pending else "retract_failed" if failed else "retracted"
        detail = f"RA 에 나간 객체 {n}개(과제 · 등록부 risk_finding) 가운데 {retracted}개를 거뒀다"
        detail += (f" — 값을 '{RETRACT_HEAD}@<code>' 로 바꾸고 과제는 설명을 비웠으며 risk_finding 은 앱이 채운 owner · status 를 빼고"
                   " visibility=private 로 바꿨다(RA 에서 따로 단 속성은 둔다 — 가려 읽힌 것만 뺀다)." if retracted else ".")
        if absent:
            detail += f" {absent}개는 RA 에 이미 없어 거둘 것이 없었다(RA 에서 지워졌다)."
        if tally["pending"]:
            detail += f" {tally['pending']}개는 거두기를 기다린다 — 다음 동기 주기에 나간다."
        if tally["waiting"]:
            detail += f" {tally['waiting']}개는 거두기를 기다린다 — 마지막 시도가 실패해 재시도 대기다(다음 시도는 저절로 한다)."
        if tally["stopped"]:
            detail += (f" {tally['stopped']}개는 거두기를 기다린다 — 그 대상의 RA 채널이 멈췄다. 까닭을 고친 뒤 대상 화면의 '재동기' 로"
                       " 다시 보낸다.")
        if failed:
            detail += f" {failed}개는 거두지 못했다 — 까닭을 고친 뒤 대상 화면의 '재동기' 로 다시 보낸다."
        if words:
            detail += f" 까닭 — {words}."
        detail += (" 객체 자체와 연결(exhibits · verified_by · refuted_by)은 RA MCP 에 지우거나 끊는 도구가 없어 남는다(RA 코드 무수정)."
                   " 폐기 뒤에는 새로 보내지 않는다.")
    return {"layer": "ra", "reason": word, "objects": n, "retracted": retracted, "absent": absent, "retract_pending": pending,
            "retract_failed": failed, "reasons": dict(sorted(reasons.items())), "detail": detail}


def refresh_purge_report(store, project_id: str) -> None:
    """폐기된 과제의 purge_report_json 에서 RA 층을 지금 셈으로 바꿔 적는다 — 거두기는 폐기 응답 뒤 동기 주기에 나가므로 보고서가 따라간다."""
    row = store.query_one("SELECT status, purge_report_json FROM rr_projects WHERE id = ?", (project_id,))
    if row is None or row["status"] != "purged" or not row["purge_report_json"]:
        return
    try:
        report = json.loads(row["purge_report_json"])
    except (TypeError, ValueError):
        return
    if not isinstance(report, dict):
        return
    layer = purge_ra_layer(store, project_id)
    remaining = [item for item in report.get("remaining") or [] if isinstance(item, Mapping)]
    at = next((i for i, item in enumerate(remaining) if item.get("layer") == "ra"), None)
    if at is None:
        remaining.append(layer)
    else:
        remaining[at] = layer
    report["remaining"] = remaining
    store.execute("UPDATE rr_projects SET purge_report_json = ? WHERE id = ?", (canonical_json(report), project_id))


def retract_counts(entry: Mapping[str, Any]) -> dict:
    """RA 채널의 거두기 셈(요약의 칸) — 객체 수다. retracted(지금 거둔 꼴) · retract_absent(거두려니 RA 에 없었다) · retract_pending(거두기
    (비공개 · 폐기) op 가 큐에 있다 — 다음 주기 · 재시도 대기 · 멈춘 채널) · retract_failed(RA 가 받지 않아 따로 뒀다) · retract_reasons(못 거둔
    것의 까닭 낱말별 수). 한 객체는 한 칸에만 든다 — 폐기 보고서와 같은 차례(대기 > 못 거둠 > 거둠 > 없음)다(_retract_states). 종전에는 거둔 뒤
    다시 받지 않은 객체를 거둔 수와 못 거둔 수에 함께 셌다."""
    states = _retract_states({"": entry})
    tally = Counter(state for state, _why in states.values())
    failed = [why for state, why in states.values() if state == "failed"]
    return {"retracted": tally["retracted"], "retract_absent": tally["absent"],
            "retract_pending": tally["pending"] + tally["waiting"] + tally["stopped"],
            "retract_failed": tally["failed"], "retract_reasons": dict(sorted(Counter(failed).items()))}


SYNC_LABELS = {"ra": "RA", "adh": "AIDataHub"}


def _error_parts(last_error: Any) -> tuple[str | None, str]:
    """last_error `<낱말>: <글>` → (낱말, 글). 낱말이 FAIL_TEXT 에 없으면(종전 꼴 'send 실패' · 'http_500' …) (None, 전체 글)."""
    text = str(last_error or "")
    code, _, detail = text.partition(": ")
    return (code, detail) if code in FAIL_TEXT else (None, text)


def fail_word(last_error: Any) -> str:
    """last_error 의 사유 낱말 — FAIL_TEXT 밖의 글(종전 꼴 · 예외 글)은 요약처럼 'rejected' 로 읽는다(야간 재시도의 경고 줄이 센다)."""
    return _error_parts(last_error)[0] or "rejected"


def _ra_summary(entry: Mapping[str, Any], state: str, n: int, status: Mapping[str, Any]) -> tuple[str, str]:
    """RA 채널의 (reason, message) — 보류 · 끝 · 꺼짐 · 멈춤 · 재시도 대기 · 대기 · 없음 순으로 하나를 고른다. 따로 둔 op 는 어느 상태에서나
    글 끝에 건수와 마지막 까닭을 단다(요약의 dead_ops 칸이 건수다)."""
    skipped = int(entry.get("skipped_n") or 0)
    tail = (f" RA 에 잇지 않은 것 {skipped}건 — 마지막 까닭: {SKIP_TEXT.get(str(entry.get('last_skip')), entry.get('last_skip'))}."
            if skipped else "")
    dead = [item for item in entry.get("dead_ops") or [] if isinstance(item, Mapping)]
    if dead:
        code, detail = _error_parts(dead[-1].get("error"))
        why = f"{code} — {FAIL_TEXT[code]}" if code else "rejected"
        tail += (f" RA 가 받지 않아 따로 둔 op {len(dead)}건 — 마지막 까닭: {why}{f' ({detail})' if detail else ''}. 고친 뒤 '재동기' 로"
                 f" 다시 보낸다(대상의 나머지 op 는 계속 나간다).")
    counts = retract_counts(entry)
    if counts["retracted"] or counts["retract_pending"] or counts["retract_failed"] or counts["retract_absent"]:
        why = " · ".join(f"{word} {count}" for word, count in counts["retract_reasons"].items())
        gone = f" · RA 에 이미 없던 것 {counts['retract_absent']}개" if counts["retract_absent"] else ""
        tail += (f" 거두기(비공개 · 폐기) — RA 에서 거둔 객체 {counts['retracted']}개 · 대기 {counts['retract_pending']}건 ·"
                 f" 못 거둔 것 {counts['retract_failed']}건{f'({why})' if why else ''}{gone}.")
    if state == "withheld":
        held = sum(1 for op in entry.get("pending_ops") or () if not is_retract_op(op))
        return "withheld", (f"RA 반영 보류 — 과제가 조직 공개가 아니라(mcp_visibility=private) RA 에 올리지 않는다. 조직 공개로 바꾸면"
                            f" 대기 {held}건이 순서대로 나간다.{tail}")
    if state == "done":
        return "sent", f"RA 반영 끝 — 대기 0건.{tail}"
    if not status.get("on"):
        return str(status.get("reason")), (f"RA 반영 안 됨 — 박스에 RA 쓰기 자격({WRITE_SECRET_KEY})이 없어 보내는 쪽이 꺼져 있다."
                                           f" 대기 {n}건, 보낸 것 없음.{tail}")
    code, detail = _error_parts(entry.get("last_error"))
    why = f" — {detail}" if detail else ""
    if state == "unavailable":
        return code or "rejected", (f"RA 반영 멈춤 — {FAIL_TEXT[code or 'rejected']}{why}. 대기 {n}건은 큐에 남아 있다 — 고친 뒤"
                                    f" '재동기' 로 다시 보낸다.{tail}")
    if entry.get("last_error"):
        return code or "transient", (f"RA 반영 재시도 대기 — 마지막 시도가 실패했다{why}. 대기 {n}건, 실패"
                                     f" {int(entry.get('attempts') or 0)}회 — 다음 시도는 저절로 한다.{tail}")
    if n:
        return "queued", f"RA 반영 대기 {n}건 — 다음 동기 주기에 보낸다.{tail}"
    return "idle", f"RA 로 보낼 것이 아직 없다 — 대기 0건.{tail}"


def sync_summary(sync: Mapping[str, Any], *, status: Mapping[str, Any] | None = None) -> dict:
    """과제·대상 응답·진행판(risk_get_coverage)·길잡이(risk_next_step)가 싣는 반영 요약 — {ra|adh: {state, pending_ops, dead_ops, reason, message}}.

    RA 는 보내는 쪽(RaSender)이 붙어 있어 reason 이 실제 상태다 — withheld(과제 비공개) · sent · credential_missing:<키>(박스 쓰기 PAT
    없음 — 보내는 쪽이 꺼져 있다) · FAIL_TEXT 의 낱말(멈춤 · 재시도 대기 — last_error 의 앞 낱말) · queued · idle. 종전에는 늘
    'sender_unwired' 였다. `status` 는 sender_status() 의 답이다(없으면 지금 secrets.env 로 잰다). AIDataHub 반입은 아직 보내는 쪽이
    없어 'sender_unwired' 그대로다(M4). `pending_ops` 는 건수다(op 본문은 GET /api/reports 의 ra_state·재동기 응답이 준다). `dead_ops` 는
    RA 가 받지 않아 따로 둔 op 의 건수다 — reason 이 sent 여도 0 이 아니면 RA 에 가지 않은 것이 있다(화면은 이 칸을 경고로 그린다).
    RA 채널에는 거두기 셈(retract_counts — 객체 수: retracted · retract_absent · retract_pending · retract_failed · retract_reasons)이 늘
    함께 실린다.
    """
    ra_status = sender_status() if status is None else status
    out: dict[str, dict] = {}
    for channel in SYNC_CHANNELS:
        entry = sync.get(channel) or {}
        n = len(entry.get("pending_ops") or [])
        state = str(entry.get("state") or "pending")
        if channel == "ra":
            reason, message = _ra_summary(entry, state, n, ra_status)
        else:
            reason = "sender_unwired"
            message = f"{SYNC_LABELS[channel]} 반영 안 됨 — 보내는 쪽이 아직 배선되지 않았다(M4). 대기 {n}건, 보낸 것 없음."
        out[channel] = {"state": state, "pending_ops": n, "dead_ops": len(entry.get("dead_ops") or []),
                        "reason": reason, "message": message}
        if channel == "ra":
            out[channel].update(retract_counts(entry))
    return out


def sync_badge(sync: Mapping[str, Any]) -> str:
    """타깃 화면·통합 보고서 헤더 표기 — `RA 반영: done|pending(n)|unavailable|withheld(n) · AIDataHub 반영: …`(§5.5.3)."""
    labels = {"ra": "RA 반영", "adh": "AIDataHub 반영"}
    parts = []
    for channel in SYNC_CHANNELS:
        entry = sync.get(channel) or {}
        state = str(entry.get("state") or "pending")
        n = len(entry.get("pending_ops") or [])
        parts.append(f"{labels[channel]}: {state}" + (f"({n})" if state in ("pending", "withheld") and n else ""))
    return " · ".join(parts)
