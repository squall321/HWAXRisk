# 어댑터 레지스트리 — P0 고정 목록(/api/meta/adapters)과 게이트웨이 /tools-map 발견(GatewayRegistry), 그리고 kind 별 캡처 오케스트레이션(capture_all, plan §2.11.3·§2.13.2)
from __future__ import annotations

from typing import Any, Mapping, Sequence

import httpx

from app import ir_builder
from app.adapters import dyna as dyna_adapter
from app.adapters import ecad_stub, mcad
from app.adapters.base import DEFAULT_TIMEOUT, CallRecorder, IrAdapter, Principal, Probe, RestGetClient
from app.common import new_uuid
from app.errors import AppError

# P0 고정 목록. 게이트웨이 /tools-map 도구명 집합으로 kind 를 바인딩하는 발견 로직(plan §8.2.11)은 GatewayRegistry 가 한다.
ADAPTERS: tuple[IrAdapter, ...] = (
    IrAdapter(kind="mcad", app_key="heax-step_forge", status="planned"),
    IrAdapter(kind="dyna", app_key="heax-kooremapper_mcp", status="planned"),
    IrAdapter(kind="ecad", app_key=None, status="contract_only"),
)

# kind → 그 백엔드에 다 보여야 하는 도구 집합(plan §2.13.2).
REQUIRED_TOOLS: dict[str, tuple[str, ...]] = {
    "mcad": mcad.REQUIRED_TOOLS,
    "dyna": dyna_adapter.REQUIRED_TOOLS,
    "dyna_result": dyna_adapter.DynaResultAdapter.required_tools,
    "ecad": ecad_stub.REQUIRED_TOOLS,
}
# 캡처 순서 — dyna_result 는 dyna 뒤에 와야 pid→nid 를 넘겨받는다.
CAPTURE_ORDER: tuple[str, ...] = ("mcad", "dyna", "dyna_result", "ecad")
DISCOVERY_TIMEOUT = 10.0


def list_adapters() -> list[dict]:
    """/api/meta/adapters 본문 — [{kind, app, status}]."""
    return [a.to_dict() for a in ADAPTERS]


def default_app_key(kind: str) -> str | None:
    return next((a.app_key for a in ADAPTERS if a.kind == kind.split("_")[0]), None)


def tool_matches(name: str, want: str) -> bool:
    """게이트웨이는 이름 충돌 시 `backend_key.replace('-','')+'_'` 접두를 양쪽에 붙인다 — suffix 로 맞춘다(recon §4 8항)."""
    return name == want or name.endswith(f"_{want}")


def gateway_http_base(gateway_mcp_url: str) -> str:
    """`…:9110/mcp` → `…:9110`. /tools-map·/health 는 MCP 경로가 아니라 루트에 있다."""
    base = (gateway_mcp_url or "").rstrip("/")
    return base[: -len("/mcp")] if base.endswith("/mcp") else base


class GatewayRegistry:
    """게이트웨이 /tools-map 을 읽어 kind 별 app_key 와 도구 가용성을 발견한다. 실패는 예외가 아니라 빈 지도다."""

    def __init__(self, gateway_mcp_url: str, *, token: str | None = None,
                 client: httpx.Client | None = None, timeout: float = DISCOVERY_TIMEOUT) -> None:
        self.base = gateway_http_base(gateway_mcp_url)
        self._token = token or ""
        self._client = client
        self._owns_client = client is None
        self.timeout = timeout
        self._map: dict[str, str] | None = None
        self._error: str | None = None
        # kind → 다의 후보 목록(plan §2.13.2 ambiguous_tool_name).
        self._ambiguous: dict[str, list[str]] = {}

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def load(self) -> dict[str, str]:
        """`{도구명: 백엔드키}` 지도. 한 번만 읽고 캐시한다."""
        if self._map is not None:
            return self._map
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = self._http().get(f"{self.base}/tools-map", headers=headers, timeout=self.timeout)
            body = response.json() if response.status_code < 400 else {}
            if response.status_code >= 400:
                self._error = f"http_{response.status_code}"
        except (httpx.HTTPError, ValueError) as exc:
            self._error = f"{type(exc).__name__}"
            body = {}
        raw = body.get("map") if isinstance(body, Mapping) else None
        self._map = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, Mapping) else {}
        return self._map

    def app_key_for(self, kind: str, preferred: str | None = None) -> str | None:
        """도구 집합으로 백엔드를 찾는다. 후보가 여럿이면 사용자가 고른 preferred(rr_sources.app_key)로 좁힌다.

        preferred 로도 좁혀지지 않으면 아무 백엔드나 고르지 않고 None 을 돌려준다 — 그 상태는
        `probe.reachable=false` + `warnings ∋ ambiguous_tool_name` 로 드러난다(plan §2.13.2).
        """
        wants = REQUIRED_TOOLS.get(kind, ())
        tools = self.load()
        candidates: dict[str, set[str]] = {}
        for name, backend in tools.items():
            for want in wants:
                if tool_matches(name, want):
                    candidates.setdefault(backend, set()).add(want)
        full = sorted(b for b, found in candidates.items() if len(found) == len(wants))
        if preferred and preferred in full:
            return preferred
        if len(full) == 1:
            return full[0]
        if len(full) > 1:
            self._ambiguous[kind] = full
            return None
        if preferred and preferred in candidates:
            return preferred
        return None

    def probe(self, kind: str, app_key: str | None = None) -> Probe:
        """plan §2.13.1 Probe. rest_ok 는 게이트웨이가 알 수 없는 값이라 None 이다(REST 는 캡처가 실증한다)."""
        wants = REQUIRED_TOOLS.get(kind, ())
        self._ambiguous.pop(kind, None)
        resolved = self.app_key_for(kind, app_key or default_app_key(kind))
        tools = self.load()
        present, missing = [], []
        for want in wants:
            found = any(tool_matches(name, want) and (resolved is None or backend == resolved)
                        for name, backend in tools.items())
            (present if found else missing).append(want)
        warnings = ["ambiguous_tool_name"] if kind in self._ambiguous else []
        return {"kind": kind, "app_key": resolved, "reachable": bool(resolved) and not missing,
                "tools_present": present, "tools_missing": missing, "rest_ok": None,
                "gateway_error": self._error, "warnings": warnings,
                "candidates": self._ambiguous.get(kind, [])}

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None


def adapter_for(kind: str, app_key: str | None = None):
    """kind 하나에 대응하는 어댑터 인스턴스. 모르는 kind 는 E100 이다."""
    if kind == "mcad":
        return mcad.McadAdapter(app_key)
    if kind == "dyna":
        return dyna_adapter.DynaAdapter(app_key)
    if kind == "dyna_result":
        return dyna_adapter.DynaResultAdapter(app_key)
    if kind == "ecad":
        return ecad_stub.EcadStubAdapter(app_key)
    raise AppError("E100", f"모르는 소스 kind — {kind!r}.", http_status=422)


def capture_all(*, sources: Sequence[Mapping[str, Any]], principal: Principal,
                mcp_client: Any = None, rest_client: RestGetClient | None = None,
                snapshot_id: str | None = None, kinds: Sequence[str] | None = None,
                report_ids: Sequence[Any] | None = None,
                detect_result_file_id: str | None = None) -> dict:
    """등록된 소스 카드를 kind 순서로 캡처한다(plan §2.11.3 1~5단계).

    반환 `{snapshot_id, results, calls, probes}`. snapshot_id 를 미리 정하는 이유는 provenance.call_id 가
    동결 후 rr_snapshot_calls 의 실제 id 와 같아야 하기 때문이다(CallRecorder 참조).
    mcad 소스가 없으면 409 다 — mcad 없는 스냅샷은 만들지 않는다.
    """
    sid = snapshot_id or new_uuid()
    by_kind: dict[str, dict] = {}
    for row in sources:
        kind = str(row.get("kind") or "")
        if kind in CAPTURE_ORDER and kind not in by_kind:
            by_kind[kind] = dict(row)
    wanted = [k for k in CAPTURE_ORDER if (kinds is None or k in kinds or k == "ecad")]
    if not [k for k in wanted if k in by_kind]:
        # mcad 가 없어도 dyna 단독 스냅샷은 만든다(plan §2.2 primary_source) — 소스가 아예 0 일 때만 막는다.
        raise AppError("source_unreachable",
                       "연결된 소스가 없습니다 — 소스를 먼저 연결하세요.", http_status=409)

    recorder = CallRecorder(sid, mcp=mcp_client, rest=rest_client)
    results: list[dict] = []
    dyna_source_hash: str | None = None
    pid_to_nid: dict[str, str] = {}
    for kind in wanted:
        row = by_kind.get(kind)
        if kind == "ecad":
            results.append(adapter_for("ecad").capture({}, principal, recorder))
            continue
        if row is None:
            continue
        ref = dict(row.get("ref") or {})
        if kind == "dyna" and detect_result_file_id:
            ref.setdefault("detect_result_file_id", detect_result_file_id)
        if kind == "dyna_result":
            if report_ids:
                ref["report_ids"] = list(report_ids)
            if dyna_source_hash and not ref.get("dyna_source_hash"):
                ref["dyna_source_hash"] = dyna_source_hash
            if pid_to_nid:
                ref.setdefault("pid_to_nid", pid_to_nid)
        result = adapter_for(kind, row.get("app_key")).capture(ref, principal, recorder)
        results.append(dict(result))
        if kind == "dyna":
            dyna_source_hash = (result.get("source") or {}).get("source_hash")
            # 결과층 오버레이는 nid 로 붙는다 — nid 는 canon_key 만으로 정해지므로 여기서 미리 계산한다.
            pid_to_nid = {str(n.get("local_key")): ir_builder.make_nid(str(n.get("canon_key")))
                          for n in result.get("nodes") or [] if n.get("kind") == "pid"}
    return {"snapshot_id": sid, "results": results, "calls": recorder.calls}


def clients_from_settings(settings, secrets: Mapping[str, str] | None = None, *,
                          portal_pat: str | None = None, http_client: httpx.Client | None = None,
                          timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Settings·secrets.env 로 캡처 채널을 만든다 — 게이트웨이 MCP(포털 PAT)와 heax REST(서비스 PAT).

    포털 PAT 가 없으면 mcp_client 는 None 이고, 서비스 PAT 가 없으면 REST 채널이 죽어 mcp_degraded 로 간다.
    """
    from app.ra_client import McpHttpClient  # noqa: PLC0415 — 순환 임포트를 피하려 지연 임포트한다.

    secrets = dict(secrets or {})
    token = portal_pat or secrets.get("HWAXRISK_PORTAL_PAT")
    service_pat = secrets.get("HWAXRISK_HEAX_SERVICE_PAT")
    mcp_client = None
    if token:
        mcp_client = McpHttpClient(getattr(settings, "gateway_mcp", ""),
                                   headers={"Authorization": f"Bearer {token}"},
                                   client=http_client, timeout=timeout)
    rest_client = RestGetClient(getattr(settings, "heax_base", ""), service_pat,
                                client=http_client, timeout=timeout)
    return {"mcp": mcp_client, "rest": rest_client, "portal_pat": token, "service_pat": service_pat}
