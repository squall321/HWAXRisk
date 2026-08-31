# IR 어댑터 베이스 — 기술자(IrAdapter)·계약 타입(Probe·AdapterResult)·Principal·REST GET 클라이언트·CallRecorder(모든 소스 호출을 rr_snapshot_calls 초안으로 남긴다)
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol, TypedDict

import httpx

# 소스 호출 타임아웃. 게이트웨이 GATEWAY_CALL_TIMEOUT(120 s) 아래로 잡는다.
DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class IrAdapter:
    """소스 kind 하나를 rr_ir 로 읽는 어댑터의 기술자. 캡처 로직은 P1 부터 서브클래스가 채운다."""

    kind: str
    app_key: str | None
    status: str

    def to_dict(self) -> dict:
        """/api/meta/adapters 한 항목 {kind, app, status}."""
        d = asdict(self)
        return {"kind": d["kind"], "app": d["app_key"], "status": d["status"]}


class Probe(TypedDict):
    """discover() 결과 — 게이트웨이에서 본 이 kind 의 가용성(plan §2.13.1)."""

    kind: str
    app_key: str | None
    reachable: bool
    tools_present: list[str]
    tools_missing: list[str]
    rest_ok: bool | None
    # 게이트웨이 자체가 불통이면 그 사유를 싣는다 — '앱이 없다' 와 '게이트웨이가 죽었다' 를 가른다(plan 강등 표기 원칙).
    gateway_error: str | None


class AdapterResult(TypedDict, total=False):
    """capture() 결과 — ir_builder.build_ir 이 그대로 받는 한 소스분 원시 결과(plan §2.13.1)."""

    source: dict
    nodes: list
    edges: list
    warnings: list
    degraded: list[str]
    call_ids: list[str]
    results: dict | None
    missing: dict


@dataclass(frozen=True)
class Principal:
    """캡처 주체. 토큰 값은 응답·로그 어디에도 싣지 않고 헤더로만 나간다."""

    owner_sub: str
    portal_pat: str | None = None    # 게이트웨이 MCP 호출용(사용자 포털 PAT 또는 앱 PAT).
    service_pat: str | None = None   # heax Caddy REST GET 용 서비스 PAT.


class ToolChannel(Protocol):
    """MCP 전송 계약 — ra_client.McpHttpClient 가 그대로 만족한다."""

    def call(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict:
        ...


class SourceAdapter:
    """소스 어댑터의 공통 뼈대. 순수 함수이며 DB 에 쓰지 않고 호출은 전부 recorder 를 거친다."""

    kind: str = ""
    version: str = "0.0"
    required_tools: tuple[str, ...] = ()

    def discover(self, registry: Any) -> Probe:
        raise NotImplementedError

    def capture(self, ref: Mapping[str, Any], principal: Principal | None,
                recorder: "CallRecorder") -> AdapterResult:
        raise NotImplementedError


class RestGetClient:
    """heax Caddy REST 의 GET 전용 클라이언트(Authorization: Bearer 서비스 PAT).

    메서드는 GET 뿐이다 — 어댑터는 소스 앱에 쓰지 않는다(plan §2.1 6). 어떤 실패도 예외로 올리지 않고
    {'ok': False, 'error': …} 로 돌려주며, 판단은 호출자가 degraded 코드로 표기한다.
    """

    def __init__(self, base_url: str, token: str | None, *, client: httpx.Client | None = None,
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self._token = token or ""
        self._client = client
        self._owns_client = client is None
        self.timeout = timeout

    @property
    def available(self) -> bool:
        """서비스 PAT 와 base 가 둘 다 있어야 REST 채널이 산다(없으면 mcp_degraded 경로)."""
        return bool(self._token) and bool(self.base_url)

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict:
        """GET {base}{path}. 성공 {'ok': True, 'result': …, 'http_status': 200}."""
        if not self.available:
            return {"ok": False, "error": "no_credential", "http_status": None}
        url = f"{self.base_url}{path}"
        try:
            response = self._http().get(
                url, params=dict(params or {}), timeout=self.timeout,
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            return {"ok": False, "error": f"transport_error: {type(exc).__name__}", "http_status": None}
        if response.status_code >= 400:
            return {"ok": False, "error": f"http_{response.status_code}", "http_status": response.status_code,
                    "detail": response.text[:200]}
        try:
            return {"ok": True, "result": response.json(), "http_status": response.status_code}
        except ValueError:
            return {"ok": False, "error": "unparsable_response", "http_status": response.status_code}

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None


class CallRecorder:
    """어댑터의 모든 소스 호출을 실행하고 rr_snapshot_calls 행 초안으로 모은다(plan §2.11.4).

    call_id 는 ir_builder.record_calls 와 같은 공식 `<snapshot_id[:8]>-<seq:03d>` 로 미리 매긴다.
    그래서 provenance.call_id 가 동결 후의 실제 행 id 와 일치한다(스냅샷 id 를 캡처 전에 정한다는 전제).
    """

    def __init__(self, snapshot_id: str, *, mcp: ToolChannel | None = None,
                 rest: RestGetClient | None = None, start_seq: int = 1) -> None:
        self.snapshot_id = snapshot_id
        self.mcp = mcp
        self.rest = rest
        self.calls: list[dict] = []
        self._start_seq = int(start_seq)
        self._seq = int(start_seq)

    @property
    def rest_available(self) -> bool:
        return self.rest is not None and self.rest.available

    @property
    def mcp_available(self) -> bool:
        return self.mcp is not None

    def _next_call_id(self) -> str:
        call_id = f"{self.snapshot_id[:8]}-{self._seq:03d}"
        self._seq += 1
        return call_id

    def call(self, channel: str, tool: str, args: Mapping[str, Any] | None = None, *,
             source_kind: str, app_key: str | None = None) -> dict:
        """채널 하나를 호출하고 원문을 남긴다. 반환 {'ok', 'result'|'error', 'call_id', 'http_status'}."""
        args = dict(args or {})
        started = int(time.time())
        began = time.monotonic()
        if channel == "rest":
            reply = self.rest.get(tool, args) if self.rest is not None else {"ok": False, "error": "no_channel"}
            logged_tool = f"GET {tool}"
        elif channel == "mcp":
            reply = self.mcp.call(tool, args) if self.mcp is not None else {"ok": False, "error": "no_channel"}
            logged_tool = tool
        else:
            raise ValueError(f"모르는 채널 — {channel!r}. 'mcp' 또는 'rest' 뿐이다.")
        duration_ms = int((time.monotonic() - began) * 1000)
        call_id = self._next_call_id()
        ok = bool(reply.get("ok"))
        error = None if ok else str(reply.get("error") or "unknown_error")
        self.calls.append({
            "source_kind": source_kind, "app_key": app_key, "channel": channel, "tool": logged_tool,
            "args": args, "response": reply.get("result") if ok else None, "ok": ok,
            "http_status": reply.get("http_status"), "started_at": started, "duration_ms": duration_ms,
            "error": error,
        })
        return {"ok": ok, "result": reply.get("result"), "call_id": call_id,
                "http_status": reply.get("http_status"), "error": error}

    def call_ids(self, source_kind: str | None = None) -> list[str]:
        """지금까지 남긴 call_id 목록(kind 로 거를 수 있다). AdapterResult.call_ids 의 값이다."""
        out = []
        for index, call in enumerate(self.calls):
            if source_kind is not None and call["source_kind"] != source_kind:
                continue
            out.append(f"{self.snapshot_id[:8]}-{self._start_seq + index:03d}")
        return out
