# hwax-risk MCP 서버 — FastMCP 도구 6종(plan §0.5.2 시그니처, P0 본문은 전부 not_implemented + ready_in), main.py 가 Route('/mcp') 로 이식
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

_INSTRUCTIONS = """HWAX Risk Review — 설계 리스크 심사 앱의 MCP 서버. 도구 6종은 P0 에서 시그니처만 등록돼 있고
본문은 {error:'not_implemented', ready_in:'P1|P2|P3|P5'} 를 돌려준다(risk_get_snapshot P1 · risk_get_diff P2 ·
risk_get_registry/risk_claims_for_ref/risk_submit_panel_result P3 · risk_get_brief P5)."""

# loopback 바인드 + Caddy 경계 전제로 Host 검증(DNS rebinding 보호)은 끈다(LaminateAnalyzerMCP 선례).
# streamable_http_path 는 기본 '/mcp' — main.py 가 streamable_http_app() 의 Route('/mcp') 를 메인 라우터에 이식해
# exact /mcp 로 매칭된다(Mount('/mcp') 는 trailing slash 없는 /mcp 를 307 으로 돌려 MCP 클라이언트가 못 따라간다 — 실측).
mcp = FastMCP(
    "hwax-risk",
    instructions=_INSTRUCTIONS,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


def _not_implemented(ready_in: str) -> dict:
    return {"error": "not_implemented", "ready_in": ready_in}


@mcp.tool()
def risk_get_snapshot(snapshot_id: str, part: str) -> dict:
    """스냅샷 조회(part ∈ ir|state|nodes|edges|calls) — ready_in P1."""
    return _not_implemented("P1")


@mcp.tool()
def risk_get_diff(diff_id: str, part: str) -> dict:
    """diff 조회(part ∈ diff|summary|events) — ready_in P2."""
    return _not_implemented("P2")


@mcp.tool()
def risk_get_registry(target_key: str) -> dict:
    """타깃 등록부(rr_registry 행 ≤200 + verdict 후보) 조회 — ready_in P3."""
    return _not_implemented("P3")


@mcp.tool()
def risk_claims_for_ref(ref: str) -> dict:
    """참조(ref 문법 §0.2.1)에 앵커된 주장 목록(rr_claim_refs 조인 ≤100) 조회 — ready_in P3."""
    return _not_implemented("P3")


@mcp.tool()
def risk_get_brief(target_key: str, tier: str = "B") -> dict:
    """패널 브리프(panels·evidence E0~E9·budget) 조회, tier='A' 는 웹 전용 — ready_in P5."""
    return _not_implemented("P5")


@mcp.tool()
def risk_submit_panel_result(
    panel_id: str,
    engine: str,
    decision_text: str,
    turns: list[dict],
    report_id: int | None,
    actor: str,
    model: str | None = None,
) -> dict:
    """패널 결과 제출(REST POST /api/panels/{id}/complete 와 같은 함수, actor 는 미검증 표기) — ready_in P3."""
    return _not_implemented("P3")
