# hwax-risk MCP 서버 — 도구 26종(발견 7 + 원장 7 + Claude 입구 12)은 REST 와 같은 함수를 부르는 접점이다(§6.11, LLM 을 부르지 않는다)
from __future__ import annotations

import logging
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app import entry, routes
from app.errors import AppError

log = logging.getLogger("hwax_risk.mcp")

_INSTRUCTIONS = """HWAX Risk Review — 설계 리스크 심사 앱의 MCP 서버. 심의 엔진이 아니라 원장 접점이다(LLM 을 부르지 않는다).

시작은 risk_list_projects 다 — 나머지 도구가 전부 id(project_id·snapshot_id·diff_id·target_key·panel_id)를
인자로 받는데, 그 id 를 알아낼 길이 이것뿐이다.

발견: risk_list_projects(과제·타깃·최근 스냅샷 id) · risk_similar_projects · risk_get_precedents(선례)
조회: risk_get_snapshot(part=ir|state|nodes|edges|calls|rule_hits) · risk_get_diff(part=lines 는 변경 줄 전부 — 크면 limit·offset 으로 나눠) ·
      risk_get_registry · risk_claims_for_ref · risk_get_coverage(진행판·좌석) · risk_list_panels · risk_get_panel_transcript
어휘: risk_taxonomy — severity·judgement·direction 의 허용값(추측해서 넣으면 422 다)
심사: risk_get_brief(열쇠는 brief_token, tier 'A' 는 웹 전용 — 결과를 낼 신원에게만 연다) · risk_submit_panel_result(engine='mcp' 는
      evidence_only 등급) · risk_add_finding — 둘 다 쓰기라 아래 신원 규칙을 따르고 actor 는 신원이 아니다(표기)

입구(Claude 에서 과제를 올리고 심사를 시작한다 — 심사는 앱 러너가 돌리고 결과는 웹에 그대로 보인다): risk_next_step 부터.
어디까지 왔고 무엇이 막혔고(고칠 곳 포함) 다음에 무엇을 부르나를 한 번에 준다. 쓰기는 risk_create_project · risk_add_source ·
risk_capture_snapshot · risk_ack_gate · risk_decide_sameas · risk_create_diff · risk_open_target · risk_start_job ·
risk_job_action · risk_repersist_panel 이고, 무엇을 어디에 쓸지 사용자에게 확인한 뒤 부른다. 같은 호출을 두 번 해도 같은 행이다. 신원은 도달한
자격이 정한다(자칭 actor 없음) — 쓰기는 게이트웨이 위임으로 확인된 신원일 때만 하고, 아니면 delegation_required 로 까닭을 말한다.
동의 인자(consent)는 사용자에게 받은 뒤에만 true 로 준다 — risk_next_step 의 next 는 그것을 채워 주지 않는다.
PAT 는 인자로 받지 않는다 — 러너 자격은 웹 설정 화면에서 등록한다."""

# loopback 바인드 + Caddy 경계 전제로 Host 검증(DNS rebinding 보호)은 끈다(LaminateAnalyzerMCP 선례).
# streamable_http_path 는 기본 '/mcp' — main.py 가 streamable_http_app() 의 Route('/mcp') 를 메인 라우터에 이식해
# exact /mcp 로 매칭된다(Mount('/mcp') 는 trailing slash 없는 /mcp 를 307 으로 돌려 MCP 클라이언트가 못 따라간다 — 실측).
mcp = FastMCP(
    "hwax-risk",
    instructions=_INSTRUCTIONS,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

# 조회 상한(plan §8.2.5 표) — nodes/edges 500 · diff events 500 · 등록부 200 · 주장 100. 한 번에 주는 양이다 — 넘치면
# next_offset 을 offset 으로 주어 나머지를 받는다(diff lines 는 상한 없이 거른 것 전부다).
NODE_LIMIT = 500
EVENT_LIMIT = 500
REGISTRY_LIMIT = 200
CLAIM_LIMIT = 100


def _request() -> Any:
    """이번 /mcp 요청(starlette Request). 요청 밖(직접 함수 호출·테스트)이면 None 이다."""
    try:
        return mcp.get_context().request_context.request
    except (AttributeError, LookupError, ValueError):
        return None


def _caller() -> dict:
    """이번 /mcp 요청의 caller(§8.2.5 ①) — 도달한 Authorization 만 신원이고 자칭 `actor` 는 신원이 아니다."""
    # 요청 밖에서는 열지 않는다 — service 는 조직 공개 과제만 본다.
    return routes.mcp_caller(_request())


def _guarded(fn, *args: Any, **kwargs: Any) -> dict:
    """REST 와 같은 함수를 부르고 AppError 는 dict 오류로 눕힌다(MCP 도구는 예외 대신 JSON 을 돌려준다).

    `detail` 은 REST 본문이 최상위에 싣는 기계 판독 칸이다(409 gate_blocked 의 {gates, reason} · model_too_large 의
    크기 · gates_hash_stale 의 현재 해시 · 입구의 고칠 곳 `fix`). 종전에는 버려 MCP 호출자가 '왜' 를 몰랐다.
    """
    try:
        return fn(*args, **kwargs)
    except AppError as exc:
        out = {"error": exc.code, "message": exc.message}
        if exc.detail:
            out["detail"] = exc.detail
        return out
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


async def _entry(fn, **kwargs: Any) -> dict:
    """입구 12종 공통 — 이 요청의 신원으로 `entry` 본체를 부르되, 본체는 스레드에서 돈다.

    FastMCP 는 동기 도구를 이벤트 루프 위에서 그대로 부른다(mcp 1.29 func_metadata). 캡처(수십 초~수 분)·명단 조회
    (최대 540초)가 루프를 붙들면 그동안 /api/health·REST·다른 MCP 호출이 멎고, HEAXHub 의 2초 헬스 검사가 앱을 다시
    띄운다(작업 지시서 A-13). 요청 객체만 루프에서 집고 신원 해석부터 스레드에서 한다.
    """
    request = _request()

    def call() -> dict:
        return fn(routes.mcp_identity(request), **kwargs)

    call.__name__ = getattr(fn, "__name__", "entry")
    return await anyio.to_thread.run_sync(lambda: _guarded(call))


@mcp.tool()
def risk_list_projects() -> dict:
    """여기서 시작한다 — 볼 수 있는 심사 과제 목록(targets[]=target_key · last_snapshot_id · 커버리지 · level)."""
    # 다른 도구가 전부 id 를 인자로 받는데 그 id 를 알아낼 길이 이것뿐이다(발견 도구 부재가 나머지를 잠근다).
    return _guarded(lambda: routes.projects_payload(
        project_ids=routes.visible_projects(_caller())))


@mcp.tool()
def risk_get_coverage(target_key: str, with_seats: bool = True, domain: str | None = None) -> dict:
    """심사 진행판 — 도메인별 상태·미착석 수·완결 레벨·잡 상태와 좌석 행(with_seats=False 면 카운트만)."""
    # '더 돌려야 하나, 끝났나' 의 근거. 등록부는 판정 행만 주고 좌석이 몇 개 비었는지는 말하지 않는다.
    def call() -> dict:
        owner_sub = routes.mcp_scope_owner("target", target_key, _caller())
        out = routes.coverage_payload(target_key, owner_sub=owner_sub)
        if with_seats:
            out["seats"] = routes.seats_payload(target_key, domain, owner_sub=owner_sub)["seats"]
        return out

    return _guarded(call)


@mcp.tool()
def risk_list_panels(target_key: str) -> dict:
    """이 타깃에서 이미 돈 패널 목록(좌석·라운드·엔진·품질·보고서 id) — panel_id 의 출처다."""
    return _scoped("target", target_key, routes.panels_payload, target_key)


@mcp.tool()
def risk_get_panel_transcript(panel_id: str) -> dict:
    """패널 한 건의 좌석 발언·결정문·risk_spec — 보충 회차 전에 읽어 중복 제기를 막는다."""
    return _scoped("panel", panel_id, routes.panel_transcript_payload, panel_id)


@mcp.tool()
def risk_taxonomy() -> dict:
    """통제 어휘 — mechanism·severity·judgement·direction·domain 허용값(추측해 넣으면 422 다)."""
    return _guarded(lambda: {
        "taxonomy": routes.taxonomy.load_taxonomy(),
        "asset_version": routes.taxonomy.ASSET_VERSION,
        "vocab": routes.taxonomy.vocab_index(),
        "promotable_axes": routes.character.promotable_axes(),
    })


@mcp.tool()
def risk_get_precedents(diff_id: str) -> dict:
    """선례 — 같은 subject 의 과거 판정과 델타 선례(이 변경이 전에도 문제였나)."""
    return _scoped("diff", diff_id, lambda d, *, owner_sub: routes.brief_module.precedents(
        routes.get_store(), d, owner_sub=owner_sub), diff_id)


@mcp.tool()
def risk_similar_projects(project_id: str, k: int = 5) -> dict:
    """비슷한 과제 top-k — 계보·벡터·서술·subject 네 경로별로 따로 준다(섞지 않는다)."""
    return _scoped("project", project_id, lambda pid, *, owner_sub: routes.brief_module.similar_projects(
        routes.get_store(), pid, max(1, min(20, int(k))), owner_sub=owner_sub), project_id)


@mcp.tool()
def risk_get_snapshot(snapshot_id: str, part: str, offset: int = 0) -> dict:
    """스냅샷 조회(part ∈ ir|state|nodes|edges|calls|rule_hits, nodes·edges 는 한 번에 500 + truncated 이고 next_offset 을 offset 으로 주면 이어 받는다)."""
    limit = NODE_LIMIT if part in ("nodes", "edges") else None
    return _scoped("snapshot", snapshot_id, routes.snapshot_part, snapshot_id, part, limit=limit, offset=offset)


@mcp.tool()
def risk_get_diff(diff_id: str, part: str, change_kind: str | None = None, q: str | None = None,
                  offset: int = 0, limit: int | None = None) -> dict:
    """diff 조회(part ∈ diff|summary|events|lines) — lines 는 브리프 변경 목록과 같은 줄 전부라 변경이 많으면 limit·offset 으로 나눠 받는다(Claude Code 는 MCP 결과가 약 25,000토큰을 넘으면 본문 대신 파일 저장 안내를 준다), change_kind(쉼표로 여럿)·q(이름·코드)로 거르고 offset 은 0 부터, events 는 한 번에 ≤500 이고 next_offset 으로 이어 받는다."""
    if part == "events" and limit is None:
        limit = EVENT_LIMIT
    return _scoped("diff", diff_id, routes.diff_part, diff_id, part, limit=limit, offset=offset,
                   change_kind=change_kind, q=q)


@mcp.tool()
def risk_get_registry(target_key: str, status: str | None = None, severity: str | None = None,
                      domain: str | None = None, offset: int = 0) -> dict:
    """타깃 등록부(rr_registry 행 한 번에 200 + verdict 후보) 조회, status·severity·domain 으로 거르고 next_offset 을 offset 으로 주면 이어 받는다."""
    return _scoped("target", target_key, routes.registry_payload, target_key, status=status,
                   severity=severity, domain=domain, limit=REGISTRY_LIMIT, offset=offset)


@mcp.tool()
def risk_claims_for_ref(ref: str, offset: int = 0) -> dict:
    """참조(ref 문법 §0.2.1)에 앵커된 주장 목록(rr_claim_refs 조인 한 번에 100) 조회, next_offset 을 offset 으로 주면 이어 받는다."""
    # 단일 id 가 아니라 역색인이라 문지기 대신 caller 가 보는 과제 집합으로 결과를 좁힌다(§8.2.5 ②).
    return _guarded(lambda: routes.claims_for_ref(
        ref, limit=CLAIM_LIMIT, projects=routes.visible_projects(_caller()), offset=offset))


@mcp.tool()
def risk_get_brief(target_key: str, brief_token: str, tier: str = "B") -> dict:
    """토큰의 패널 브리프 1건 조회(panels[0].delib_opts.evidence 가 근거 E0~E9 이고 항목의 result_chars 는 옮겨 적기 대조용 원문 길이, 옛 한도에 잘린 것은 brief_clipped·brief_notice) — 열쇠는 brief_token 이고 결과를 낼 수 있는 신원(게이트웨이 위임으로 확인된 그 패널 소유자)에게만 열며 tier='A' 는 웹 전용."""
    if tier == "A":
        return {"error": "tier_a_web_only"}

    def call() -> dict:
        # 토큰의 쓰임은 이 신원의 결과 제출(risk_submit_panel_result)뿐이다 — 제출이 거절될 신원이면 동결·패널 품질을 쓰기 전에
        # 제출과 같은 코드로 거절한다. 종전에는 토큰만 대조해 브리프를 내주고, 몇 시간 심의 뒤 제출에서야 거절됐다(RV-1).
        owner_sub = entry.require_delegate(routes.mcp_identity(_request()))
        # 그다음은 UI·REST 가 발급한 토큰 대조다 — 불일치·만료는 {error:'brief_token_invalid'}(§8.2.5), 남의 패널 토큰은 E404.
        return routes.brief_by_token(target_key, brief_token, tier, owner_sub=owner_sub)

    return _guarded(call)


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
    evidence_omitted: list[dict] | None = None,
) -> dict:
    """패널 결과 제출(REST POST /api/panels/{id}/complete 와 같은 함수, 게이트웨이 위임으로 확인된 그 패널 소유자만 낸다, actor 는 미검증 표기, evidence_omitted=[{source,text}] 는 좌석에 못 간 근거)."""
    def call() -> dict:
        # 소유권은 도달한 위임 신원이 정한다 — 자칭 actor 를 열쇠로 쓰면 남이 actor=<소유자> 로 남의 패널을 종결한다(SEC-5).
        owner_sub = entry.require_delegate(routes.mcp_identity(_request()))
        return routes.complete_panel(
            panel_id, engine=engine, decision_text=decision_text, turns=list(turns or []),
            report_id=report_id, conv_id=None, events=None, model=model,
            # 심의가 좌석에 주지 못한 근거(본문 없음 · 건수 · 예산 초과). 종전엔 받을 자리가 없어 오케스트레이터의
            # 반환값에만 남았고, 얹어 보내도 말없이 버려졌다. 웹 러너가 엔진 카드를 적는 자리에 같이 남긴다.
            evidence_omitted=evidence_omitted,
            # actor 는 호출자 신고값이라 quality_json 표기로만 남고 회수 격리(actor_verified=false)도 종전 그대로다(§6.11).
            actor=actor, actor_verified=False, owner_sub=owner_sub,
        )

    return _guarded(call)


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
    """사람 finding 등록(REST POST /api/targets/{key}/findings 와 같은 함수, 작성자는 게이트웨이 위임으로 확인된 신원이고 actor 는 신원이 아니다, 인용 0건은 422)."""
    body = routes.HumanFindingBody(
        direction=direction, domain=domain, mechanism=mechanism, mechanism_detail=mechanism_detail,
        change_kind=change_kind, subject_key=subject_key, subject_names=list(subject_names or []),
        severity=severity, judgement=judgement, claim=claim, warrant=warrant, cites=list(cites or []),
    )

    def call() -> dict:
        # 작성자·소유권은 도달한 위임 신원이다 — actor 는 옛 계약이라 받지만 쓰지 않는다(SEC-5).
        ident = routes.mcp_identity(_request())
        entry.require_delegate(ident)
        return routes.create_human_finding(target_key, body, ident=ident)

    return _guarded(call)


# ================================================================ Claude 입구(PLAN M1 · context-notes D-23)
# 실사용 팀은 Claude 에서 MCP 로 심의를 돌린다. 위 14종은 읽기와 결과 제출뿐이라 Claude 에서는 과제를 올리거나 심사를 시작할
# 수 없었고, 그래서 Claude 로 돈 심사가 원장에 한 건도 없었다. 아래 12종은 웹 화면이 부르는 REST 라우트를 같은 신원으로
# 감싼다(남의 과제는 라우트의 소유권 검사가 막는다). 심사는 앱의 러너가 돌리고 Claude 는 시작하고 지켜본다.
# 신원은 도달한 자격(게이트웨이 위임 단언·개인 Bearer)이고 자칭 actor 는 없다. 쓰기는 그 가운데 게이트웨이 위임으로 확인된
# 단언(X-Hwax-Delegate-Email 로 발급)일 때만 한다(entry.require_delegate). 비밀(PAT)은 인자로 받지 않는다.
# 같은 호출을 두 번 해도 같은 행이다 — 게이트웨이의 사람별 길은 실패하면 한 번 더 부른다.
@mcp.tool()
async def risk_next_step(project_id: str | None = None) -> dict:
    """Claude 입구의 길잡이(읽기 전용) — 과제가 어느 단계(소스·캡처·리비전·same-as·비교·심사 대상·명단·잡·결과)이고 무엇이 막혔는지(고칠 곳 fix)와 다음에 부를 도구·인자(next)를 한 번에 준다, project_id 없이 부르면 내 과제 목록이고 acting_as 는 이 호출이 누구로 해석됐는지다."""
    return await _entry(entry.next_step, project_id=project_id)


@mcp.tool()
async def risk_create_project(code: str, name: str, classification: str, stage: str | None = None,
                              predecessor_project_id: str | None = None, product_code: str | None = None,
                              adh_scope: dict | None = None) -> dict:
    """심사 과제 만들기 — 쓰기: 사용자에게 과제 코드·이름·등급(classification=internal|confidential, 반출 경계)을 확인한 뒤 부른다, 웹 POST /api/projects 와 같은 함수이고 호출자 소유라 그 사람의 웹 과제 목록에 그대로 뜬다, 같은 code 를 다시 보내면 기존 과제를 돌려준다(created:false), 새 리비전이 소스 앱의 다른 프로젝트면 predecessor_project_id 로 앞 과제를 잇는다."""
    return await _entry(entry.create_project, code=code, name=name, classification=classification, stage=stage,
                        predecessor_project_id=predecessor_project_id, product_code=product_code,
                        adh_scope=adh_scope)


@mcp.tool()
async def risk_add_source(project_id: str, kind: str, ref: dict, app_key: str | None = None,
                          bridge_declared: bool = False) -> dict:
    """과제에 소스 연결 — 쓰기: 어느 과제에 어떤 소스를 붙일지 사용자에게 확인한 뒤 부른다, kind=mcad ref={stepforge_project_id, detect_job_id?}(StepForge) · dyna ref={session_id, file_id}(DynaForge, 본인 세션) · dyna_result ref={report_ids[]}, 같은 소스는 기존 행을 돌려주고 같은 kind 의 다른 소스는 거절한다(캡처는 종류마다 하나만 읽고 소스는 지울 수 없다)."""
    return await _entry(entry.add_source, project_id=project_id, kind=kind, ref=ref, app_key=app_key,
                        bridge_declared=bridge_declared)


@mcp.tool()
async def risk_capture_snapshot(project_id: str, label: str | None = None, kinds: list[str] | None = None,
                                report_ids: list[int] | None = None, detect_result_file_id: str | None = None,
                                allow_large: bool = False) -> dict:
    """소스를 읽어 스냅샷 동결 — 쓰기: 어느 과제를 캡처할지 사용자에게 확인한 뒤 부른다, 수십 초~수 분 걸리고 같은 내용이면 기존 스냅샷을 돌려준다(reused), 게이트 결과(blocked·gates_summary)를 함께 준다, 게이트웨이 시간 한도에 끊기면 다시 부르지 말고 risk_next_step 으로 확인한다."""
    return await _entry(entry.capture_snapshot, project_id=project_id, label=label, kinds=kinds,
                        report_ids=report_ids, detect_result_file_id=detect_result_file_id, allow_large=allow_large)


@mcp.tool()
async def risk_ack_gate(snapshot_id: str, gate: str, reason: str, gates_hash: str | None = None) -> dict:
    """실패한 비차단 게이트(G1~G5·G7)에 사유 남기기 — 쓰기: 사유를 사용자에게 확인한 뒤 부른다, 진행을 막지 않는 표기라 판정 pass 는 그대로이고 G6(단위·크기)은 차단이라 ack 할 수 없다(소스를 고쳐 재캡처), 같은 ack 는 한 행이다."""
    return await _entry(entry.ack_gate, snapshot_id=snapshot_id, gate=gate, reason=reason, gates_hash=gates_hash)


@mcp.tool()
async def risk_get_sameas(base_snapshot_id: str, target_snapshot_id: str) -> dict:
    """두 스냅샷 사이 같은 부품 대응표(읽기 전용) — 정하지 못한(pending)·충돌·퍼지 매칭 행과 a_stable·b_stable 을 준다, risk_decide_sameas 전에 읽어 사용자에게 보인다."""
    return await _entry(entry.get_sameas, base_snapshot_id=base_snapshot_id, target_snapshot_id=target_snapshot_id)


@mcp.tool()
async def risk_decide_sameas(base_snapshot_id: str, target_snapshot_id: str, decisions: list[dict]) -> dict:
    """same-as 확정 — 쓰기: 어느 대응을 confirm|reject 할지 사용자에게 확인한 뒤 부른다, decisions=[{a_stable, b_stable, decision}] 이고 열쇠(scope·pair_key)는 도구가 채운다, 변경 비교를 만들기 전에 해야 그 비교에 반영된다, 같은 결정은 다시 보내도 한 행이다."""
    return await _entry(entry.decide_sameas, base_snapshot_id=base_snapshot_id,
                        target_snapshot_id=target_snapshot_id, decisions=decisions)


@mcp.tool()
async def risk_create_diff(base_snapshot_id: str, target_snapshot_id: str) -> dict:
    """두 스냅샷의 변경 비교 만들기 — 쓰기: 어느 두 스냅샷(base=이전 리비전·target=새 리비전)을 비교할지 사용자에게 확인한 뒤 부른다, 같은 쌍이면 저장된 비교를 돌려주고(created:false) G6 으로 막힌 스냅샷이면 gate_blocked 다."""
    return await _entry(entry.create_diff, base_snapshot_id=base_snapshot_id, target_snapshot_id=target_snapshot_id)


@mcp.tool()
async def risk_open_target(kind: str, ref_id: str, consent: bool = False) -> dict:
    """심사 대상 열기 — 쓰기: 무엇을 심사할지 사용자에게 확인한 뒤 부른다(동의를 받아 consent=true), kind=diff(변경 심사, ref_id=diff_id)|snap(현황 심사, ref_id=snapshot_id), 전문가 명단을 고정하고 Tier 별 패널 수를 준다, 이미 연 내 대상이면 그것을 돌려주고 명단이 비었으면 그 자리에서 다시 받는다."""
    return await _entry(entry.open_target, kind=kind, ref_id=ref_id, consent=consent)


@mcp.tool()
async def risk_start_job(target_key: str, tier: str, consent: bool = False, modifiers: list[str] | None = None,
                         user_memo: str | None = None, concurrency: int = 1) -> dict:
    """심사 잡 시작 — 쓰기: Tier 와 비용(패널 수·LLM 호출 추정)을 사용자에게 확인한 뒤 부른다(Tier C 는 consent=true), 심사는 앱 러너가 돌리고 결과는 웹에 그대로 보인다, Tier 는 누적이다(A 도메인 대표 → B → C 전원), 같은 대상·같은 Tier 의 살아 있는 잡이 있으면 그것을 돌려주고, 러너 자격이 없으면 웹 설정 화면에서 등록하라는 fix 로 답한다."""
    return await _entry(entry.start_job, target_key=target_key, tier=tier, consent=consent, modifiers=modifiers,
                        user_memo=user_memo, concurrency=concurrency)


@mcp.tool()
async def risk_job_action(job_id: str, action: str) -> dict:
    """심사 잡 일시정지·재개·취소(action=pause|resume|cancel) — 쓰기: 사용자에게 확인한 뒤 부른다(취소는 되돌릴 수 없다), 이미 그 상태면 그대로 돌려주고(changed:false), 앱 재기동으로 멈춘 잡은 resume 해야 이어 돈다."""
    return await _entry(entry.job_action, job_id=job_id, action=action)


@mcp.tool()
async def risk_repersist_panel(panel_id: str, discard: bool = False) -> dict:
    """저장 실패한 패널 다시 저장 — 쓰기: 사용자에게 확인한 뒤 부른다, 엔진 결과는 남았는데 원장에 앉히지 못해 persist_error 로 닫힌 패널을 그 결과로 다시 앉힌다(risk_next_step 의 blocked repersist_pending 이 panel_id 를 준다), 그 전에는 재개해도 이 대상에 새 패널이 편성되지 않는다, 같은 결과로 되풀이해 실패하면 discard=true 로 포기한다(엔진 결과는 패널에 남고 좌석은 다음 패널에서 다시 돈다)."""
    return await _entry(entry.repersist_panel, panel_id=panel_id, discard=discard)
