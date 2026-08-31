# hwax-risk MCP 서버 — FastMCP 읽기 전용 도구 3종(risk_health · risk_get_taxonomy · risk_get_meta), main.py 가 Route('/mcp') 로 이식
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.api import meta_payload
from app.risk_store import get_store
from app.taxonomy import load_taxonomy

_INSTRUCTIONS = """HWAX Risk Review — 설계 리스크 심사 앱의 MCP 서버(P0 스캐폴드, 읽기 전용).
- risk_health: 저장소 상태(DB 경로·스키마 버전·표 목록).
- risk_get_taxonomy: 리스크 택소노미 v1(8축·failure_map·voc_map).
- risk_get_meta: 앱 id·버전·데이터 경로·스키마 버전·root_path."""

# loopback 바인드 + Caddy 경계 전제로 Host 검증(DNS rebinding 보호)은 끈다(ThermalShockMCP 와 동일).
# streamable_http_path 는 기본 '/mcp' — main.py 가 streamable_http_app() 의 Route('/mcp') 를 메인 라우터에 이식해
# exact /mcp 로 매칭된다(Mount('/mcp') 는 trailing slash 없는 /mcp 를 307 으로 돌려 MCP 클라이언트가 못 따라간다 — 실측).
mcp = FastMCP(
    "hwax-risk",
    instructions=_INSTRUCTIONS,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
def risk_health() -> dict:
    """앱 저장소 상태를 돌려준다 — ok·db_path·schema_version·rr_ 표 목록."""
    return get_store().health()


@mcp.tool()
def risk_get_taxonomy() -> dict:
    """리스크 택소노미 v1(docs/taxonomy.v1.json) 전체를 돌려준다."""
    return load_taxonomy()


@mcp.tool()
def risk_get_meta() -> dict:
    """앱 메타(app_id·version·data_dir·schema_version·root_path)를 돌려준다 — REST /api/meta 와 같고 identity 만 없다."""
    return meta_payload()
