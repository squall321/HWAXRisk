# IR 어댑터 베이스 — 기술자(IrAdapter)·계약 타입(Probe·AdapterResult)·Principal·REST GET 클라이언트·CallRecorder(모든 소스 호출을 rr_snapshot_calls 초안으로 남긴다)
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Protocol, Sequence, TypedDict

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
    # 도구 이름이 두 백엔드에 다 있어 좁히지 못한 경우 `ambiguous_tool_name`(plan §2.13.2).
    warnings: list[str]
    candidates: list[str]


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


def tool_matches(name: str, want: str) -> bool:
    """게이트웨이는 이름 충돌 시 `backend_key.replace('-','')+'_'` 접두를 양쪽에 붙인다 — suffix 로 맞춘다(recon §4 8항)."""
    return name == want or name.endswith(f"_{want}")


def resolve_tool_name(want: str, names: Sequence[str]) -> str:
    """맨이름 하나 → 게이트웨이 **실이름**(접두 포함형). 못 찾거나 다의면 맨이름 그대로.

    정본 §2.13.2 는 "그렇게 얻은 게이트웨이 실이름(접두 포함형 그대로)을 **호출 인자와**
    `rr_snapshot_calls.tool` 에 적는다" 고 적고 통과 기준 (23)(a)가 그 둘을 함께 검사한다.
    그런데 suffix 매칭은 probe 에서만 쓰였고 호출은 맨이름으로 나갔다 — 게이트웨이가 이름 충돌로 접두를
    붙이는 순간 그 호출들이 **조용히 전멸한다.** probe 는 도구를 찾았다고 보고하므로(suffix 로 찾으니까)
    실패가 어댑터 쪽에서만 나고 원인이 이름이라는 단서가 없다.

    판정은 `tool_matches` 와 같은 규칙이다 — 두 곳이 갈리면 probe 가 찾은 도구를 호출이 못 찾는다.
    다의면 아무 쪽이나 고르지 않는다 — 남의 백엔드를 부르는 것보다 맨이름으로 실패하는 편이 낫고,
    그 상태는 probe 의 `ambiguous_tool_name` 이 이미 드러낸다.
    """
    hits = sorted(n for n in names if tool_matches(n, want))
    if want in hits:
        return want
    return hits[0] if len(hits) == 1 else want


class CallRecorder:
    """어댑터의 모든 소스 호출을 실행하고 rr_snapshot_calls 행 초안으로 모은다(plan §2.11.4).

    call_id 는 ir_builder.record_calls 와 같은 공식 `<snapshot_id[:8]>-<seq:03d>` 로 미리 매긴다.
    그래서 provenance.call_id 가 동결 후의 실제 행 id 와 일치한다(스냅샷 id 를 캡처 전에 정한다는 전제).
    """

    def __init__(self, snapshot_id: str, *, mcp: ToolChannel | None = None,
                 rest: RestGetClient | None = None, start_seq: int = 1,
                 tool_names: Sequence[str] = ()) -> None:
        self.snapshot_id = snapshot_id
        self.mcp = mcp
        self.rest = rest
        # 게이트웨이가 노출하는 실이름들 — 비면 맨이름으로 부른다(발견 실패가 캡처를 막지 않는다).
        self.tool_names = tuple(tool_names)
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
            # 정본 §2.13.2 — 발견으로 얻은 **게이트웨이 실이름**(접두 포함형)을 호출 인자와
            # `rr_snapshot_calls.tool` 에 적는다. 맨이름으로 부르면 게이트웨이가 이름 충돌로 접두를
            # 붙이는 순간 호출이 조용히 전멸한다(probe 는 suffix 로 찾으니 '도구 있음' 으로 보고한다).
            real = resolve_tool_name(tool, self.tool_names) if self.tool_names else tool
            reply = self.mcp.call(real, args) if self.mcp is not None else {"ok": False, "error": "no_channel"}
            logged_tool = real
        else:
            raise ValueError(f"모르는 채널 — {channel!r}. 'mcp' 또는 'rest' 뿐이다.")
        duration_ms = int((time.monotonic() - began) * 1000)
        call_id = self._next_call_id()
        ok = bool(reply.get("ok"))
        error = None if ok else str(reply.get("error") or "unknown_error")
        # 응답 계약 검사(§2.13.1) — 위반은 예외가 아니라 행에 남는 표기다.
        # 계약표는 맨이름 키다 — 실이름으로 찾으면 전부 '계약 없는 도구' 가 되어 검사가 조용히 꺼진다.
        contract = check_contract(tool, reply.get("result")) if ok else {
            "contract_ok": None, "missing": [], "type_mismatch": []}
        self.calls.append({
            "source_kind": source_kind, "app_key": app_key, "channel": channel, "tool": logged_tool,
            "args": args, "response": reply.get("result") if ok else None, "ok": ok,
            "http_status": reply.get("http_status"), "started_at": started, "duration_ms": duration_ms,
            "error": error, "contract_ok": contract["contract_ok"],
            "contract_missing": sorted(set(contract["missing"]) | set(contract["type_mismatch"])),
        })
        return {"ok": ok, "result": reply.get("result"), "call_id": call_id,
                "http_status": reply.get("http_status"), "error": error,
                "contract_ok": contract["contract_ok"], "contract_missing": contract["missing"]}

    def call_ids(self, source_kind: str | None = None) -> list[str]:
        """지금까지 남긴 call_id 목록(kind 로 거를 수 있다). AdapterResult.call_ids 의 값이다."""
        out = []
        for index, call in enumerate(self.calls):
            if source_kind is not None and call["source_kind"] != source_kind:
                continue
            out.append(f"{self.snapshot_id[:8]}-{self._start_seq + index:03d}")
        return out


# ---------------------------------------------------------------- 응답 계약·소스 앱 버전(plan §2.13.1)
# 도구 → 그 응답에 반드시 있어야 하는 JSON 포인터와 기대 타입. 파서 갱신을 설계 변경과 가르는 자리다.
RESPONSE_CONTRACT: dict[str, dict[str, str]] = {
    "project_tree": {"/summary": "object"},
    "list_parts": {"/parts": "array"},
    "list_interfaces": {"/interfaces": "array"},
    "interface_graph": {"/edges": "array"},
    "part_mesh_map": {"/rows": "array"},
    "report_summary": {"/id": "any"},
}
_TYPE_OF = {"object": dict, "array": list, "string": str, "number": (int, float), "boolean": bool}


def _pointer(payload: Any, pointer: str) -> tuple[bool, Any]:
    """JSON 포인터 한 칸 해석 — (존재, 값)."""
    current = payload
    for token in [t for t in str(pointer).split("/") if t]:
        if not isinstance(current, Mapping) or token not in current:
            return False, None
        current = current[token]
    return True, current


def check_contract(tool: str, payload: Any, contract: Mapping[str, Mapping[str, str]] | None = None) -> dict:
    """도구 응답이 계약을 지키는지 본다(plan §2.13.1).

    반환 `{contract_ok, missing[], type_mismatch[]}` — 계약이 없으면 `contract_ok=None`(검사 대상 아님)이다.
    위반은 예외가 아니라 표기다: 호출자가 `warnings.source_schema_drift` + `degraded.schema_drift` 로 남긴다.
    """
    table = dict(contract or RESPONSE_CONTRACT)
    spec = None
    for name, pointers in table.items():
        if tool == name or tool.endswith(f"_{name}"):
            spec = pointers
            break
    if spec is None:
        return {"contract_ok": None, "missing": [], "type_mismatch": []}
    missing: list[str] = []
    mismatch: list[str] = []
    for pointer, kind in spec.items():
        found, value = _pointer(payload, pointer)
        if not found:
            missing.append(pointer)
            continue
        expected = _TYPE_OF.get(kind)
        if expected is not None and not isinstance(value, expected):
            mismatch.append(pointer)
    return {"contract_ok": not missing and not mismatch, "missing": missing, "type_mismatch": mismatch}


# kind → 그 앱의 버전을 읽는 도구(plan §2.2 app_version 행). 못 읽으면 version=null 이고 degraded 다.
SYSTEM_STATUS_TOOL: dict[str, str] = {
    "mcad": "heaxstep_forge_system_status",
    "dyna": "heaxkooremapper_mcp_system_status",
    "dyna_result": "heaxkooremapper_mcp_system_status",
}
UNKNOWN_APP_VERSION: dict[str, Any] = {"version": None, "captured_via": None, "extra": None}


def probe_app_version(recorder: Any, kind: str, *, app_key: str | None = None) -> dict:
    """소스 앱 버전을 1회 읽는다 — 실패해도 캡처를 멈추지 않고 `version=null` 로 남긴다(plan §2.2).

    이 값은 `ir_hash` 입력이 아니다 — 소스 앱 배포가 설계 변경으로 보이면 안 된다(§3.3.6 이 쌍에서 비교한다).
    """
    tool = SYSTEM_STATUS_TOOL.get(kind)
    if not tool or recorder is None or not bool(getattr(recorder, "mcp_available", False)):
        return dict(UNKNOWN_APP_VERSION)
    reply = recorder.call("mcp", tool, {}, source_kind=kind, app_key=app_key)
    if not reply.get("ok"):
        return dict(UNKNOWN_APP_VERSION)
    body = reply.get("result")
    if not isinstance(body, Mapping):
        return dict(UNKNOWN_APP_VERSION)
    app_block = body.get("app") if isinstance(body.get("app"), Mapping) else {}
    version = body.get("version") or body.get("app_version") or app_block.get("version")
    extra = {k: body[k] for k in ("build", "commit", "started_at", "schema_version") if k in body}
    return {"version": str(version) if version else None, "captured_via": tool if version else None,
            "extra": extra or None}
