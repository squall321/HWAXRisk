# hwax-risk MCP 서버 — 도구 7종(plan §0.5.2 시그니처)은 REST 와 같은 함수를 부르는 원장 접점이다(§6.11, LLM 을 부르지 않는다)
from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app import routes
from app.errors import AppError

log = logging.getLogger("hwax_risk.mcp")

_INSTRUCTIONS = """HWAX Risk Review — 설계 리스크 심사 앱의 MCP 서버. 도구 7종은 심의 엔진이 아니라 원장 접점이다 —
조회 4종(risk_get_snapshot · risk_get_diff · risk_get_registry · risk_claims_for_ref) · 브리프 공급(risk_get_brief,
tier 'A' 는 웹 전용) · 결과 회수(risk_submit_panel_result, engine='mcp' 는 evidence_only 등급으로 기록) ·
사람 finding 등록(risk_add_finding, actor 는 미검증 표기)."""

# loopback 바인드 + Caddy 경계 전제로 Host 검증(DNS rebinding 보호)은 끈다(LaminateAnalyzerMCP 선례).
# streamable_http_path 는 기본 '/mcp' — main.py 가 streamable_http_app() 의 Route('/mcp') 를 메인 라우터에 이식해
# exact /mcp 로 매칭된다(Mount('/mcp') 는 trailing slash 없는 /mcp 를 307 으로 돌려 MCP 클라이언트가 못 따라간다 — 실측).
mcp = FastMCP(
    "hwax-risk",
    instructions=_INSTRUCTIONS,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# 조회 상한(plan §8.2.5 표) — nodes/edges 500 · diff events 500 · 등록부 200 · 주장 100.
NODE_LIMIT = 500
EVENT_LIMIT = 500
REGISTRY_LIMIT = 200
CLAIM_LIMIT = 100


def _owner(actor: str | None) -> str:
    """게이트웨이 신고 `actor`(이메일)를 쓰기 도구의 소유권 검사 키로 쓴다(§6.11).

    actor 가 없으면 어떤 행에도 맞지 않는 빈 문자열이라 쓰기가 E404 다 — 최종 사용자를 해석할 수 없는 호출에
    남의 원장을 고치게 두지 않는다. 읽기 범위는 이 값으로 정하지 않는다(§5.1 원칙 9 — `_caller()` 를 쓴다).
    """
    return str(actor or "").strip().lower()


def _caller() -> dict:
    """이번 /mcp 요청의 caller(§8.2.5 ①) — 도달한 Authorization 만 신원이고 자칭 `actor` 는 신원이 아니다."""
    try:
        request = mcp.get_context().request_context.request
    except (AttributeError, LookupError, ValueError):
        # 요청 밖(직접 함수 호출·테스트)에서는 열지 않는다 — service 는 조직 공개 과제만 본다.
        request = None
    return routes.mcp_caller(request)


def _guarded(fn, *args: Any, **kwargs: Any) -> dict:
    """REST 와 같은 함수를 부르고 AppError 는 dict 오류로 눕힌다(MCP 도구는 예외 대신 JSON 을 돌려준다)."""
    try:
        return fn(*args, **kwargs)
    except AppError as exc:
        return {"error": exc.code, "message": exc.message}
    except Exception:  # noqa: BLE001 — 게이트웨이 세션을 끊지 않는다.
        # 상세(SQL 문·경로·다른 사용자 키)는 로그에만 남긴다 — 응답은 인증 경계 밖으로 나간다.
        log.exception("MCP 도구 실패: %s", getattr(fn, "__name__", fn))
        return {"error": "internal_error", "message": "내부 오류 — 서버 로그를 확인하세요."}


def _scoped(kind: str, key: str, fn, *args: Any, **kwargs: Any) -> dict:
    """읽기 4종 공통 — caller 범위 밖이면 `{error:'not_visible'}`, 안이면 그 행 owner 로 REST 와 같은 함수를 부른다."""
    def call() -> dict:
        owner_sub = routes.mcp_scope_owner(kind, key, _caller())
        return fn(*args, owner_sub=owner_sub, **kwargs)

    return _guarded(call)


@mcp.tool()
def risk_get_snapshot(snapshot_id: str, part: str) -> dict:
    """스냅샷 조회(part ∈ ir|state|nodes|edges|calls, nodes·edges 는 상위 500 + truncated)."""
    limit = NODE_LIMIT if part in ("nodes", "edges") else None
    return _scoped("snapshot", snapshot_id, routes.snapshot_part, snapshot_id, part, limit=limit)


@mcp.tool()
def risk_get_diff(diff_id: str, part: str) -> dict:
    """diff 조회(part ∈ diff|summary|events, events 는 ≤500 + truncated)."""
    limit = EVENT_LIMIT if part == "events" else None
    return _scoped("diff", diff_id, routes.diff_part, diff_id, part, limit=limit)


@mcp.tool()
def risk_get_registry(target_key: str, status: str | None = None, severity: str | None = None,
                      domain: str | None = None) -> dict:
    """타깃 등록부(rr_registry 행 ≤200 + verdict 후보) 조회, status·severity·domain 으로 거른다."""
    return _scoped("target", target_key, routes.registry_payload, target_key, status=status,
                   severity=severity, domain=domain, limit=REGISTRY_LIMIT)


@mcp.tool()
def risk_claims_for_ref(ref: str) -> dict:
    """참조(ref 문법 §0.2.1)에 앵커된 주장 목록(rr_claim_refs 조인 ≤100) 조회."""
    # 단일 id 가 아니라 역색인이라 문지기 대신 caller 가 보는 과제 집합으로 결과를 좁힌다(§8.2.5 ②).
    return _guarded(lambda: routes.claims_for_ref(
        ref, limit=CLAIM_LIMIT, projects=routes.visible_projects(_caller())))


@mcp.tool()
def risk_get_brief(target_key: str, brief_token: str, tier: str = "B") -> dict:
    """패널 브리프(panels·evidence E0~E9·budget) 조회 — 열쇠는 brief_token 이고 tier='A' 는 웹 전용."""
    if tier == "A":
        return {"error": "tier_a_web_only"}
    # caller 판정이 아니라 UI·REST 가 발급한 토큰 대조다 — 불일치·만료는 {error:'brief_token_invalid'}(§8.2.5).
    return _guarded(routes.brief_by_token, target_key, brief_token, tier)


@mcp.tool()
def risk_submit_panel_result(
    panel_id: str,
    engine: str,
    decision_text: str,
    turns: list[dict],
    report_id: int | None = None,
    *,
    actor: str,
    model: str | None = None,
) -> dict:
    """패널 결과 제출(REST POST /api/panels/{id}/complete 와 같은 함수, actor 는 미검증 표기)."""
    return _guarded(
        routes.complete_panel, panel_id, engine=engine, decision_text=decision_text, turns=list(turns or []),
        report_id=report_id, conv_id=None, events=None, model=model,
        # actor 는 게이트웨이 신고값이라 owner_sub 를 바꾸지 않고 quality_json 표기로만 남는다(§6.11).
        # 다만 소유권 검사에는 쓴다 — 아무나 남의 panel_id 를 종결하면 원장이 오염된다.
        actor=actor, actor_verified=False, owner_sub=_owner(actor),
    )


@mcp.tool()
def risk_add_finding(
    target_key: str,
    claim: str,
    cites: list[dict],
    *,
    actor: str,
    direction: str = "risk",
    domain: str | None = None,
    mechanism: str = "unclassified",
    mechanism_detail: str | None = None,
    change_kind: str | None = None,
    subject_key: str | None = None,
    subject_names: list[str] | None = None,
    severity: str | None = None,
    judgement: str | None = None,
    warrant: str | None = None,
) -> dict:
    """사람 finding 등록(REST POST /api/targets/{key}/findings 와 같은 함수, 인용 0건은 422)."""
    body = routes.HumanFindingBody(
        direction=direction, domain=domain, mechanism=mechanism, mechanism_detail=mechanism_detail,
        change_kind=change_kind, subject_key=subject_key, subject_names=list(subject_names or []),
        severity=severity, judgement=judgement, claim=claim, warrant=warrant, cites=list(cites or []),
    )
    email = _owner(actor)
    ident = routes.identity.Identity(email=email, display_name=email, role="user", organization=None,
                                     anonymous=not email, source="mcp")
    return _guarded(routes.create_human_finding, target_key, body, ident=ident)
