# hwax-risk MCP 서버 — 도구 29종(발견 7 + 원장 7 + Claude 입구 12 + 검토 단위 1 + 카드 대조 검토 2)은 REST 와 같은 함수를 부르는 접점이다(§6.11, LLM 을 부르지 않는다)
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated, Any

import anyio
import pydantic_core
from mcp.server.fastmcp import FastMCP
from pydantic import Field, StrictBool
from mcp.server.transport_security import TransportSecuritySettings

from app import brief, common, entry, expert_report, issues, planner, registry, review_cells, review_runner, routes, runner, synth
from app.adapters import dyna as dyna_adapter
from app.errors import AppError

log = logging.getLogger("hwax_risk.mcp")

_INSTRUCTIONS = """HWAX Risk Review — 설계 리스크 심사 앱의 MCP 서버. 심의 엔진이 아니라 원장 접점이다(LLM 을 부르지 않는다).

시작은 risk_list_projects 다 — 나머지 도구가 전부 id(project_id·snapshot_id·diff_id·target_key·panel_id)를
인자로 받는데, 그 id 를 알아낼 길이 이것뿐이다.

발견: risk_list_projects(과제·타깃·최근 스냅샷 id) · risk_similar_projects · risk_get_precedents(선례)
조회: risk_get_snapshot(part=ir|state|nodes|edges|calls|rule_hits) · risk_get_diff(part=lines 는 변경 줄 전부 — 크면 limit·offset 으로 나눠) ·
      risk_get_registry · risk_claims_for_ref · risk_get_coverage(진행판·좌석) · risk_list_panels · risk_get_panel_transcript ·
      risk_get_units(카드 대조의 검토 단위 — 목록·요약·줄·동결 근거, 크면 next_offset 으로 나눠) ·
      risk_get_cells(카드 대조 셀 격자 — 전문가 × 단위의 상태·판정 수, 크면 next_offset 으로 나눠) ·
      risk_get_expert_report(전문가 보고서 — 마크다운 쪽, next_page 로 이어 받으며 쪽을 다 이으면 part='full' 과 같다) ·
      risk_get_issues(카드 대조 대상의 쟁점 — 유형·등급·상태·결과·분포, 쟁점 패널은 웹 러너가 돌린다 — Claude 에서는 지켜본다) ·
      risk_get_report(종합 보고서 판 — 완결 표기·잔여·영역 요약·쟁점 결과, part=summary|domains|mechanisms|appendix|full 의 쪽)
어휘: risk_taxonomy — severity·judgement·direction 의 허용값(추측해서 넣으면 422 다)
심사: risk_get_brief(열쇠는 brief_token, tier 'A' 는 웹 전용 — 결과를 낼 신원에게만 연다) · risk_submit_panel_result(engine='mcp' 는
      evidence_only 등급) · risk_add_finding — 둘 다 쓰기라 아래 신원 규칙을 따르고 actor 는 신원이 아니다(표기)

입구(Claude 에서 과제를 올리고 심사를 시작한다 — 심사는 앱 러너가 돌리고 결과는 웹에 그대로 보인다): risk_next_step 부터.
어디까지 왔고 무엇이 막혔고(고칠 곳 포함) 다음에 무엇을 부르나를 한 번에 준다. 쓰기는 risk_create_project · risk_add_source ·
risk_capture_snapshot · risk_ack_gate · risk_decide_sameas · risk_create_diff · risk_open_target · risk_start_job ·
risk_job_action · risk_repersist_panel 이고, 무엇을 어디에 쓸지 사용자에게 확인한 뒤 부른다. 같은 호출을 두 번 해도 같은 행이다. 신원은 도달한
자격이 정한다(자칭 actor 없음) — 쓰기는 게이트웨이 위임으로 확인된 신원일 때만 하고, 아니면 delegation_required 로 까닭을 말한다.
동의 인자(consent)는 사용자에게 받은 뒤에만 true 로 준다 — risk_next_step 의 next 는 그것을 채워 주지 않는다.
카드 대조(flow='cells') 대상의 검토는 risk_start_job(mode='reviews', scope={agents:[…]}) 하나로 세운다 — 범위의 전문가는
risk_next_step 의 facts.review_order(영역마다 영역 안 순위 1~3 의 영역·순위·tier·입력 결손 — 전부는
risk_get_coverage(order_offset=0) 쪽)를 보고 사용자가 고른다(코드가 고르지 않는다). 지켜보기는
risk_get_coverage(review 칸) · risk_get_cells, 결과는 risk_get_expert_report 다.
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
# 유사 과제 k 의 상한 — risk_similar_projects 가 1 과 이 값 사이로 죈다(인자 설명도 이 값을 읽는다).
SIMILAR_K_MAX = 20
# 검토 단위 조회 한 번의 글자 예산(항목의 압축 JSON 으로 센 첫 값) — 자르지 않고 나눈다(next_offset). 실제로 나가는 글은 FastMCP
# 가 들여쓰기 2 JSON 으로 낸 것이라 압축 셈보다 약 1.3배 길다 — _fit_wire 가 그 글을 재서 MCP_RESULT_CHARS 안에 들 때까지 줄인다.
UNITS_PAGE_CHARS = 20000
# Claude Code 가 MCP 결과로 받는 글의 상한(약 25,000토큰)을 글자로 보수 환산한 값 — 넘으면 본문 대신 'result exceeds maximum
# allowed tokens' 를 받는다(tests/test_mcp_brief_relay.py 의 CLAUDE_MCP_RESULT_CHARS 와 같은 값).
MCP_RESULT_CHARS = 25_000


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


def _max_len(model: Any, field: str) -> int:
    """REST 본문 모델이 그 칸에 건 글자 상한(`Field(max_length=…)`) — 인자 설명에 수를 손으로 옮겨 적지 않는다."""
    return next(m.max_length for m in model.model_fields[field].metadata if getattr(m, "max_length", None) is not None)


# 인자 설명(inputSchema 의 description) — 클라이언트 LLM 은 도구 설명과 함께 인자마다 이 글을 본다(게이트웨이 인자 설명 점수판, 포털
# docs/improvement-1015 6번). 상한 · 허용값은 코드 상수에서 읽는다 — 손으로 적은 수는 낡는다. 긴 규칙은 도구 설명을 가리킨다.
# 상수가 없거나 뜻을 붙이느라 손으로 적은 허용값(잡 조작 · 심사 방식 · 발언 stance · 등록부 상태 …)은
# tests/test_mcp_arg_descriptions.py 가 코드의 값과 맞춘다. 동의 인자(consent · consent_external)는 사용자에게 받은 뒤에만 참이다.
_A_DOMAIN_CODE = "risk_taxonomy 의 domain — 예 xd · sim"
_A_TARGET_KEY = "심사 대상 열쇠 'diff:<diff_id>' · 'snap:<snapshot_id>'(risk_list_projects 의 targets · risk_open_target 응답의 target_key)."
_A_PROJECT_ID = "과제 id(risk_list_projects 의 projects[].id · risk_create_project 응답의 id)."
_A_SNAPSHOT_ID = ("스냅샷 id(risk_list_projects 의 last_snapshot_id · risk_next_step 의 facts.snapshots[].id · risk_capture_snapshot "
                  "응답의 snapshot_id).")
_A_DIFF_ID = "변경 비교 id(risk_create_diff 응답의 diff_id · risk_next_step 의 facts.diff.id · 대상 열쇠 'diff:<id>' 의 뒤)."
_A_PANEL_ID = "패널 id(risk_list_panels 의 panels[].id)."
_A_NEXT_OFFSET = "건너뛸 행 수(0부터) — 앞 응답의 next_offset 을 그대로 준다."
_A_REPORT_PAGE = "받을 쪽(1부터) — 앞 응답의 next_page 를 준다. 범위 밖이면 422 다."
_A_REPORT_VERSION = "둘째 쪽부터 첫 쪽 응답의 version 을 준다 — 그사이 판이 바뀌었으면 409 report_version_moved 이고 처음 쪽부터 다시 받는다."
# 발견 · 조회
_A_WITH_SEATS = "거짓이면 좌석 행 없이 진행판의 수만 준다."
_A_COV_DOMAIN = f"좌석 행을 이 영역 코드({_A_DOMAIN_CODE})로 거른다. 진행판의 수는 거르지 않는다."
_A_ORDER_OFFSET = (f"카드 대조 대상의 검토 순서 전부를 이 자리(0부터)부터 쪽으로 받는다 — 좌석 행 없이, 다음 쪽은 next_order_offset 이다. "
                   f"비우면 영역마다 앞 순위(최대 1~{routes.REVIEW_ORDER_TOP})만 싣고, 검토 순서가 없는 대상(패널 방식)에 주면 422 다.")
_A_SEAT_OFFSET = f"건너뛸 좌석 행 수(0부터) — 앞 응답의 next_seat_offset 을 준다. 한 쪽은 MCP 결과 상한({MCP_RESULT_CHARS:,}자) 안이다."
_A_PANEL_KIND = "패널 종류로 거른다 — coverage(좌석을 채우는 패널) · issue(쟁점 패널). 비우면 전부다."
_A_TAX_PART = f"볼 쪽 — {' · '.join(routes.TAXONOMY_PARTS)}(무엇이 드는지는 도구 설명). 그 밖은 422 다."
_A_TAX_OFFSET = "mechanism · mech_owners 의 행을 건너뛸 수(0부터) — 앞 응답의 next_offset 을 준다. index · maps 에는 쓰지 않는다."
_A_SIMILAR_K = f"과제 수 — 벡터 · 서술 경로와 합친 목록(merged)에 건다(계보 · subject 경로는 아니다). 1~{SIMILAR_K_MAX} 사이로 죈다."
_A_SNAP_PART = f"볼 쪽 — {' · '.join(routes.SNAPSHOT_PARTS)}. nodes · edges 는 한 번에 최대 {NODE_LIMIT}행씩 준다."
_A_SNAP_OFFSET = "nodes · edges 의 행을 건너뛸 수(0부터) — truncated 면 응답의 next_offset 을 준다. 다른 쪽에는 쓰지 않는다."
_A_DIFF_PART = f"볼 쪽 — {' · '.join(routes.DIFF_PARTS)}. lines 는 브리프 변경 목록(E2)과 같은 줄이다."
_A_CHANGE_KIND = (f"lines 만 — 변경 종류로 거른다(쉼표로 여럿). 값은 {' · '.join(brief.KIND_PRIORITY)} 이고 응답의 by_kind 열쇠와 "
                  "같다.")
_A_DIFF_Q = "lines 만 — 줄 글(이름으로 바꾼 뒤)에 든 부분 문자열로 거른다(대소문자 무시)."
_A_DIFF_OFFSET = "lines · events 를 건너뛸 수(0부터 — lines 는 거른 목록 안의 자리) — 앞 응답의 next_offset 을 준다."
_A_DIFF_LIMIT = (f"lines · events 의 한 번 몫. 비우면 lines 는 거른 것 전부, events 는 {EVENT_LIMIT}건이다 — 변경이 많으면 limit 으로 "
                 "나눠 받는다(MCP 결과 상한).")
_A_REG_STATUS = ("등록부 상태로 거른다 — open · rejected_in_panel · verified · dismissed · mitigated · superseded 가운데 하나"
                 "(정확히 같은 값).")
_A_REG_SEVERITY = f"심각도로 거른다 — {' · '.join(routes.HUMAN_SEVERITIES)}(risk_taxonomy 의 severity)."
_A_REG_DOMAIN = f"영역 코드로 거른다 — 제기 원자의 영역이나 대표의 소유 영역({_A_DOMAIN_CODE})."
_A_REG_OFFSET = (f"건너뛸 행 수(0부터) — 앞 쪽의 next_offset 을 준다. 한 쪽은 최대 {REGISTRY_LIMIT}행이고 MCP 결과 상한을 넘으면 더 "
                 "줄인다. ledger_rev 가 앞 쪽과 다르면 0 부터 다시 받는다.")
_A_ATTENTION = f"주의 등급으로 거른다 — {' · '.join(registry.ATTENTION_ORDER)}(쉼표로 여럿, 대소문자 무시)."
_A_REG_UNIT = "이 검토 단위가 제기에 든 행만(risk_get_units 의 unit_id)."
_A_REF = (f"참조 하나 '<스킴>:<본문>'(대괄호는 있어도 된다) — 스킴은 {' · '.join(common.REF_SCHEMES)} 이고 p · e · c 는 소문자 16진 "
          "12자리다(예 p:0123456789ab). 문법에 맞지 않으면 422 다.")
_A_CLAIM_OFFSET = f"건너뛸 주장 수(0부터) — 한 번에 최대 {CLAIM_LIMIT}건이고 truncated 면 응답의 next_offset 을 준다."
# 심사 — 브리프 · 결과 제출 · 사람 finding
_A_BRIEF_TARGET = "토큰을 받은 패널 방식 대상의 열쇠('diff:<id>' · 'snap:<id>'). 카드 대조 대상은 422 cells_flow_web_only 다."
_A_BRIEF_TOKEN = ("패널 브리프 열쇠 — 사용자가 웹 앱 화면(REST GET /api/targets/{key}/brief 의 panels[].brief_token)에서 복사해 준다. "
                  "그 패널 하나에만 맞고, 박스 설정 HWAXRISK_BRIEF_TOKEN_TTL_S 초가 지나면 brief_token_invalid 다.")
_A_BRIEF_TIER = f"Tier({' · '.join(planner.TIERS)}) — A 대표 패널은 웹 러너 전용이라 tier_a_web_only 를 돌려준다."
_A_SUBMIT_PANEL = ("결과를 낼 패널 id — risk_get_brief 응답의 panels[0].panel_id. 내 패널이고 planned · running(다시 내기는 done · "
                   "error)이어야 한다.")
_A_ENGINE = ("엔진 표기 — mcp(Claude 에서 돈 심의 — 좌석 도구 호출 경로가 없어 evidence_only 등급) · web. 그 밖은 422 이고, 다시 내면 "
             "처음 저장한 값이 남는다.")
_A_DECISION = ("의장 결정문 전문 — 끝의 ```json 펜스(없으면 마지막 중괄호 블록)에 schema 가 'risk_spec' 인 객체가 있어야 판정 원자가 "
               "앉는다. 못 읽으면 좌석 의견만 남고 spec_parse_failed 로 표시된다.")
_A_TURNS = ("좌석 발언 [{persona(좌석 키), round, say, position?, stance?}] — persona 가 빈 항목은 세지 않고 stance 는 agree · "
            "conditional · oppose · abstain(그 밖은 conditional)이다. 엔진 심의면 deliberate_transcript(full=true) 의 발언을 옮긴다.")
_A_REPORT_ID = "심의가 Report Archive 에 남긴 보고서 id(정수, 선택) — 패널 행에 적는다."
_A_SUBMIT_ACTOR = ("자칭 표기(필수, 신원이 아니다) — 패널 · 좌석 의견의 품질 칸(actor)에 표기로만 남고 actor_verified 는 거짓이다. "
                   "소유는 게이트웨이 위임으로 확인된 신원이 정한다.")
_A_MODEL = "심의에 쓴 모델 이름(호출자 신고, 선택) — mcp 결과에서 비우면 unknown 으로 적는다."
_A_OMITTED = "좌석에 못 간 근거 [{source, text}](선택) — 패널 품질의 engine_withheld 줄로 남는다."
_A_CLAIM = f"주장(필수, 최대 {_max_len(routes.HumanFindingBody, 'claim')}자) — 비면 422 다."
_A_CITES = ("인용 [{ref, quote}] — ref 가 든 항목이 1건 이상이어야 한다(아니면 422 cites_required). ref 문법은 risk_claims_for_ref 의 "
            "ref 와 같고, 문법 밖 ref 는 dangling 으로 남는다.")
_A_FINDING_ACTOR = "옛 계약의 자칭 표기(필수) — 받기만 하고 쓰지 않는다. 작성자는 게이트웨이 위임으로 확인된 신원이다."
_A_DIRECTION = f"방향 — {' · '.join(routes.HUMAN_DIRECTIONS)}."
_A_FINDING_DOMAIN = f"영역 코드(선택, {_A_DOMAIN_CODE}) — 검사하지 않고 그대로 적는다."
_A_MECHANISM = ("메커니즘 계열(risk_taxonomy 의 mechanism 행의 mechanism 칸 — 예 thermal · mechanical) — 검사하지 않고, 세부 · 대상 · "
                "변경 종류와 함께 등록부 묶음 열쇠(cluster_key)가 된다.")
_A_MECH_DETAIL = "메커니즘 세부(선택, 같은 행의 detail — 예 cte_mismatch)."
_A_FINDING_CHANGE = "변경 종류(선택, risk_taxonomy 의 change_kind — 예 dimension · topology)."
_A_SUBJECT_KEY = ("대상 열쇠(선택) — 패널 finding 과 같은 꼴(부품 ckey · 두 ckey 를 '|' 로 이은 계면 · asm:<조립 키> · dim:<치수 이름>)"
                  "이면 같은 등록부 행으로 묶인다. 풀지 않고 그대로 쓴다.")
_A_SUBJECT_NAMES = "대상 이름(선택, 표시용) — ckey 로 풀지 않고 그대로 적는다."
_A_SEVERITY = f"심각도 — {' · '.join(routes.HUMAN_SEVERITIES)}(비우면 경미)."
_A_JUDGEMENT = f"판정 — {' · '.join(routes.HUMAN_JUDGEMENTS)}(비우면 undetermined)."
_A_WARRANT = "논거(선택) — 인용이 주장을 어떻게 받치는지 적는다."
# Claude 입구
_A_NEXT_PROJECT = "과제 id(risk_list_projects 의 projects[].id). 비우면 내가 소유한 과제 목록과 새 과제 만들기 안내를 준다."
_A_CODE = (f"과제 코드(필수, 최대 {_max_len(routes.ProjectBody, 'code')}자) — 같은 사람이 같은 코드를 다시 보내면 기존 과제를 "
           "돌려준다(created:false).")
_A_NAME = f"과제 이름(필수, 최대 {_max_len(routes.ProjectBody, 'name')}자)."
_A_CLASSIFICATION = f"등급 — {' · '.join(routes.CLASSIFICATIONS)}(필수 — 반출 경계라 사용자가 고른다)."
_A_STAGE = "개발 단계(선택) — 웹 폼의 규약은 pre · dv · pv · pra · mp 뒤에 1 · 2 · 3 · r 을 붙인 꼴(예 dv2)이고, 이 도구는 검사하지 않는다."
_A_PREDECESSOR = ("앞 리비전 과제의 id(선택, risk_list_projects 의 id) — 부른 사람이 구성원인 과제여야 한다(아니면 E404). 이 과제에 앞 "
                  "캡처가 없으면 길잡이가 그 과제(내 것)의 최신 스냅샷을 비교의 앞으로 쓴다.")
_A_PRODUCT_CODE = "제품 코드(선택) — 브리프의 현장(VOC) 근거를 이 코드로 찾는다. 비우면 앞 과제(내 것)의 코드를 [전작] 으로 쓴다."
_A_ADH_SCOPE = "AIDataHub 범위 {team, group}(선택) — 사용자가 확인한 값을 과제 행에 그대로 적고 자동으로 채우지 않는다."
_A_SOURCE_KIND = (f"소스 종류 — {' · '.join(routes.SOURCE_KINDS)}(ecad 는 아직 어댑터 계약만 있다). 과제마다 종류당 하나이고 다른 "
                  "소스면 409 source_kind_taken 이다(소스는 지울 수 없다).")
_A_SOURCE_REF = ("소스 위치 객체 — " + " · ".join(f"{kind} {{{', '.join(keys)}}}" for kind, keys in entry.REF_REQUIRED.items())
                 + " 는 필수 키다(빠지면 422). mcad 는 detect_job_id(계면 검출 잡)를, dyna_result 는 report_ids[] 를 받는다.")
_A_APP_KEY = "소스 앱의 허브 앱 키(선택) — 비우면 게이트웨이 실측(/meta/adapters), 못 읽으면 어댑터 기본값으로 웹과 같게 고른다."
_A_BRIDGE = "'브리지 선언' 표기 — 소스 행에 그대로 적히기만 하고 지금 코드는 캡처 · 대응표 계산에 쓰지 않는다."
_A_LABEL = "스냅샷 이름표(선택) — 비우면 snap-<epoch 초> 다."
_A_KINDS = "읽을 소스 종류 목록(값은 risk_add_source 의 kind) — 비우면 붙은 소스 전부를 읽는다."
_A_REPORT_IDS = (f"dyna_result 소스로 읽을 결과 리포트 id(선택, 최대 {dyna_adapter.MAX_REPORTS}건 — 넘으면 앞의 것만 "
                 "읽는다) — 주면 소스 ref 의 report_ids 를 덮는다.")
_A_DETECT_FILE = ("dyna 소스의 검출(detect) 결과 파일 id(선택, 그 DynaForge 세션 안) — 소스 ref 에 없을 때 써서 기하 간섭 엣지를 더 "
                  "읽는다.")
_A_ALLOW_LARGE = ("참이면 리프 · 계면 수가 박스 상한(HWAXRISK_MAX_LEAF · HWAXRISK_MAX_INTERFACES)을 넘어도 동결한다 — 거짓이면 넘을 때 "
                  "409 model_too_large 다. 사용자 확인 뒤에만 참으로 준다.")
_A_GATE = (f"게이트 — {' · '.join(k for k in routes.GATE_KEYS if k != 'G6')} 가운데 통과하지 않은 것(pass 가 false · null). G6 · "
           "차단 게이트는 422 gate_blocking, 통과한 게이트는 422 gate_passing 이다.")
_A_GATE_REASON = f"사유(필수, 최대 {routes.GATE_ACK_REASON_MAX}자) — 공백뿐이면 422 reason_required 다."
_A_GATES_HASH = ("읽은 게이트 판정의 지문(선택) — 주면 그사이 재계산됐을 때 409 gates_hash_stale 로 막는다(지금 값은 그 오류의 "
                 "detail.gates_hash · 앞 ack 응답의 gates_hash).")
_A_BASE_SNAP = "앞 리비전의 스냅샷 id(risk_next_step 의 facts.pair.base_snapshot_id) — 내 스냅샷이어야 한다."
_A_TARGET_SNAP = "새 리비전의 스냅샷 id(risk_next_step 의 facts.pair.target_snapshot_id) — 내 스냅샷이어야 한다."
_A_DECISIONS = ("확정할 대응 [{a_stable, b_stable, decision}](1건 이상) — a_stable · b_stable 은 risk_get_sameas 의 pairs 행 그대로, "
                "decision 은 confirm · reject 다. evidence 를 더하면 함께 남는다.")
_A_OPEN_KIND = "대상 종류 — diff(변경 심사, ref_id 는 diff_id) · snap(현황 심사, ref_id 는 snapshot_id)."
_A_REF_ID = "kind 가 가리키는 id — diff 면 risk_create_diff 의 diff_id, snap 이면 스냅샷 id 다. 대상 열쇠는 '<kind>:<ref_id>' 가 된다."
_A_OPEN_CONSENT = ("사용자가 이 대상을 열기로 동의한 뒤에만 true — 이미 연 대상을 돌려받을 때도 true 여야 한다(아니면 422). 자동으로 "
                   "채우지 않는다(risk_next_step 의 next 도 채워 주지 않는다).")
_A_FLOW = ("심사 방식 — panels(영역을 섞은 패널 3라운드) · cells(전문가별 카드 대조). 새 대상은 비우면 panels 로 열고, 이미 연 대상은 "
           "비우면 그대로 두며 다르게 주면 방식을 바꾼다.")
_A_FLOW_REASON = (f"이미 연 대상의 방식을 바꿀 때 감사에 남는 사유(선택, 최대 {_max_len(routes.FlowBody, 'reason')}자). 새 대상을 열 "
                  "때는 쓰지 않는다.")
_A_TIER = (f"패널 Tier — {' · '.join(planner.TIERS)}(mode=panels 에 필수, 누적이다 — A 영역 대표 → B → C 전원). mode=reviews 에 주면 "
           "422 다.")
_A_JOB_CONSENT = ("사용자가 범위와 비용에 동의한 뒤에만 true — Tier C 와, 호출 추정이 박스 문턱(HWAXRISK_REVIEW_CONSENT_CALLS)을 넘는 "
                  "검토 잡에 든다. 자동으로 채우지 않는다.")
_A_MODIFIERS = (f"얹을 심의 층(mode=panels 만) — {' · '.join(planner.MODIFIER_WHITELIST)} 가운데이고, 밖의 이름은 버리며 "
                f"{' · '.join(planner.DEFAULT_MODIFIERS)} 은 늘 든다. 검토 잡에 비지 않은 목록을 주면 422 다.")
_A_USER_MEMO = ("잡에 남기는 사람 메모(선택) — 패널 잡이면 좌석 브리프의 M 항목으로 간다. 자르지 않고 저장하고, 브리프 상한을 넘으면 "
                "앞부분만 가며 응답의 user_memo_cut 이 알린다.")
_A_CONCURRENCY = ("패널 잡의 동시 패널 수(mode=panels 만) — 1 과 박스 상한(HWAXRISK_CONCURRENCY) 사이로 죈다. 검토 잡에 1 이 아닌 값을 "
                  "주면 422 다.")
_A_MODE = "잡 종류 — panels(Tier 패널 잡) · reviews(카드 대조 대상의 전문가별 검토 잡 — 범위는 scope)."
_A_SCOPE = (f"검토 잡의 범위(mode=reviews 만) — {{{', '.join(review_runner.SCOPE_KEYS)}}} 칸마다 비지 않은 목록이고 칸끼리는 AND, 뺀 "
            "칸은 전부다. 전문가는 risk_next_step 의 facts.review_order 를 보고 사용자가 고르며, 모르는 칸 · 이 대상에 없는 값은 422 "
            "scope_invalid 다.")
_A_LLM = (f"판단 LLM — {' · '.join(runner.LLM_CHOICES)}(비우면 glm). claude 는 mode=reviews 에만 받고 consent_external 이 든다"
          "(반출 경고는 도구 설명).")
_A_CONSENT_EXTERNAL = ("Claude 반출 동의 — 반출 사실(도구 설명)을 사용자에게 보이고 동의를 받은 뒤에만 JSON true 를 준다(글자 'true' · "
                       "1 은 거절한다). 자동으로 채우지 않고, 패널 잡에 주면 422 다.")
_A_JOB_ID = ("잡 id — risk_start_job 응답의 job_id · risk_get_coverage 의 job.id(패널 잡) · review.job.id(검토 잡) · risk_next_step "
             "의 facts.job.id.")
_A_ACTION = ("조작 — pause(일시정지) · resume(재개) · cancel(취소 — 되돌릴 수 없다) · retry_failed · skip_failed(검토 잡의 failed "
             "셀을 다시 열거나 사유와 함께 넘긴다).")
_A_ACTION_REASON = (f"retry_failed · skip_failed 의 사유 — {routes.REASON_MIN}~{routes.REASON_MAX}자이고 skip_failed 에는 필수다. 다른 "
                    "action 에 주면 422 다.")
_A_CELL_FILTER = ("retry_failed · skip_failed 의 셀 거름 {"
                  + ", ".join(f"{k}?" for k in review_cells.SELECTOR_FILTER_KEYS if k != "job_id")
                  + f"}}(state 는 {' · '.join(review_cells.CELL_STATES)} 가운데) — job_id 는 이 잡으로 못 박힌다. 다른 action 에 주면 "
                  "422 다.")
_A_ACTION_CONSENT = ("retry_failed · resume 의 동의 — consent_required 를 받으면 범위와 비용을 사용자에게 보이고 동의를 받은 뒤에만 "
                     "true 로 다시 부른다(자동으로 채우지 않는다). 다른 action 에 주면 422 다.")
_A_REPERSIST_PANEL = f"다시 앉힐 패널 id — risk_next_step 의 blocked({runner.REPERSIST_PENDING_CODE}) 의 panels 에 있다."
_A_DISCARD = "참이면 다시 저장을 포기한다 — 엔진 결과는 패널에 남고 좌석은 다음 패널에서 다시 돈다. 같은 결과로 되풀이해 실패할 때만 쓴다."
# 카드 대조 — 검토 단위 · 셀 · 전문가 보고서
_A_UNITS_UNIT = "검토 단위 id(part='manifest' 의 units[].unit_id) — summary · lines · evidence 에 필수이고 manifest 에 주면 422 다."
_A_UNITS_PART = ("manifest(활성 빌드의 단위 목록) · summary(그 단위의 요약 글) · lines(변경 줄 — 소유 + 문맥) · evidence(동결 근거). "
                 "그 밖은 422 다.")
_A_UNITS_OFFSET = (f"건너뛸 항목 수(0부터 — manifest 는 단위, 나머지는 줄 · 근거 행) — 앞 응답의 next_offset 을 준다. 한 번에 약 "
                   f"{UNITS_PAGE_CHARS:,}자다.")
_A_CELL_AGENT = "이 전문가 키의 셀만(risk_get_coverage 의 review.order · 좌석 행의 agent_key)."
_A_CELL_UNIT = "이 검토 단위의 셀만(risk_get_units 의 unit_id)."
_A_CELL_STATE = f"셀 상태로 거른다 — {' · '.join(review_cells.CELL_STATES)}. 그 밖은 422 다."
_A_CELL_LIMIT = (f"한 번에 줄 행 수 — 1~{routes.CELL_LIST_LIMIT_MAX} 사이로 죄고, MCP 결과 상한({MCP_RESULT_CHARS:,}자)을 넘으면 더 "
                 "줄인다(남은 것은 next_offset).")
_A_CELL_JOB = "그 검토 잡 범위의 셀만 — risk_start_job(mode='reviews') 응답의 job_id · risk_get_coverage 의 review.job.id."
_A_EXPERT_AGENT = ("전문가 키(필수, risk_get_coverage 의 review.order · 좌석 행의 agent_key) — 그 전문가 보고서가 마감됐어야 한다"
                   "(아니면 E404).")
_A_EXPERT_PART = f"보고서 부분 — {' · '.join(expert_report.PARTS)}(무엇이 드는지는 도구 설명). 그 밖은 422 다."
_A_EXPERT_UNIT = "한 단위의 줄만(선택, risk_get_units 의 unit_id) — 그 보고서 범위에 없는 단위면 E404 다."
# 쟁점 · 종합 보고서
_A_ISSUE_STATE = "쟁점 상태로 거른다(쉼표로 여럿 — 값은 도구 설명의 상태 목록이고 모르는 값은 0건이다)."
_A_P_CLASS = f"쟁점 등급 — {' · '.join(issues.P_ORDER)} 가운데 하나."
_A_ISSUE_LIMIT = (f"한 번에 줄 행 수 — 1~{routes.ISSUE_LIST_MAX} 사이로 죄고, MCP 결과 상한({MCP_RESULT_CHARS:,}자)을 넘으면 더 줄인다"
                  "(남은 것은 next_offset).")
_A_ISSUE_OFFSET = "건너뛸 행 수(0부터, 쟁점 id 순) — 앞 쪽의 next_offset 을 준다. ledger_rev 가 앞 쪽과 다르면 0 부터 다시 받는다."
_A_SYNTH_PART = f"보고서 부분 — {' · '.join(synth.PARTS)}(무엇이 드는지는 도구 설명). 그 밖은 422 다."


@mcp.tool()
def risk_list_projects() -> dict:
    """여기서 시작한다 — 볼 수 있는 심사 과제 목록(targets[]=target_key · last_snapshot_id · 커버리지 · level)."""
    # 다른 도구가 전부 id 를 인자로 받는데 그 id 를 알아낼 길이 이것뿐이다(발견 도구 부재가 나머지를 잠근다).
    return _guarded(lambda: routes.projects_payload(
        project_ids=routes.visible_projects(_caller())))


@mcp.tool()
def risk_get_coverage(target_key: Annotated[str, Field(description=_A_TARGET_KEY)],
                      with_seats: Annotated[bool, Field(description=_A_WITH_SEATS)] = True,
                      domain: Annotated[str | None, Field(description=_A_COV_DOMAIN)] = None,
                      order_offset: Annotated[int | None, Field(description=_A_ORDER_OFFSET)] = None,
                      seat_offset: Annotated[int, Field(description=_A_SEAT_OFFSET)] = 0) -> dict:
    """심사 진행판 — 도메인별 상태·미착석 수·완결 레벨·잡 상태와 좌석 행(with_seats=False 면 카운트만, 좌석이 많으면 seat_offset 부터 한 번에 약 2만 5천 자씩 주고 next_seat_offset 으로 이어 받는다), 카드 대조 대상의 review 칸은 검토 순서를 영역마다 영역 안 순위 1~3 만 싣고(review.order_page 에 전체 셈) order_offset 을 주면 그 자리부터 검토 순서 전부를 쪽으로 준다(좌석 행 없이, next_order_offset 으로 이어 받는다), 완결 잔여(qualifiers)의 목록 칸(미토의 쟁점 문장 · 몰린 칸 · 쟁점 id 따위)은 앞 5개와 수(<칸>_n)만 준다(전부는 웹 REST GET /api/targets/{key}/closure)."""
    # '더 돌려야 하나, 끝났나' 의 근거. 등록부는 판정 행만 주고 좌석이 몇 개 비었는지는 말하지 않는다.
    # 359명 로스터에서 검토 순서 전부(약 9만 자)·좌석 행 전부(약 12만 자)는 MCP 결과 상한을 넘어 본문을 잃는다(R3B-1) — 둘 다
    # 자르지 않고 쪽으로 나눈다. REST 진행판은 전부를 싣는다.
    def call() -> dict:
        owner_sub = routes.mcp_scope_owner("target", target_key, _caller())
        out = routes.coverage_payload(target_key, owner_sub=owner_sub)
        review = out.get("review")
        if review is not None and review.get("job") is not None:
            review["job"] = routes.mcp_job_brief(review["job"])     # 범위 · 워커는 수와 앞 몇(반대 검토 MEDIUM 12)
        if out.get("qualifiers") is not None:
            out["qualifiers"] = routes.mcp_qualifiers(out["qualifiers"])     # 잔여의 목록 칸도 앞 몇과 수(review1 M9)
        if order_offset is not None:
            if review is None:
                raise AppError("E100", "order_offset 은 카드 대조 대상의 검토 순서 쪽이다 — 이 대상에는 검토 순서가 없다.", 422)
            full = list(review["order"])
            return _fit_list(lambda take: {**out, "review": {**review, **routes.review_order_page(full, order_offset, take)}},
                             len(full), lambda page: len(page["review"]["order"]))
        seats = routes.seats_payload(target_key, domain, owner_sub=owner_sub)["seats"] if with_seats else []

        def seat_page(take: int) -> dict:
            skip = max(0, int(seat_offset))
            rows = seats[skip:skip + take]
            page = {**out, "seats": rows}
            if skip or skip + len(rows) < len(seats):
                page["seats_page"] = {"total": len(seats), "offset": skip, "shown": len(rows)}
                if skip + len(rows) < len(seats):
                    page["next_seat_offset"] = skip + len(rows)
            return page

        # 359명에서는 좌석을 한 줄로 줄여도 진행판의 나머지(검토 순서 요약 · 품질 칸)만으로 상한을 넘는다(재설계 M3 C3-11 — 운영처럼
        # 품질 칸을 꽂은 규모 시험에서 26,579자) — 검토 순서 요약을 영역마다 앞 순위 3 → 2 → 1 명으로 줄인다(_fit_guide 와 같은
        # 규칙, 전부는 order_offset 쪽).
        full = list(review["order"]) if review is not None else []
        for top in range(routes.REVIEW_ORDER_TOP, 0, -1):
            if review is not None:
                review.update(routes.review_order_brief(full, top=top))
            page = _fit_list(seat_page, len(seats), lambda page: len(page["seats"])) if with_seats else out
            if review is None or _wire_chars(page) <= MCP_RESULT_CHARS:
                break
        return page

    return _guarded(call)


@mcp.tool()
def risk_list_panels(target_key: Annotated[str, Field(description=_A_TARGET_KEY)],
                     kind: Annotated[str | None, Field(description=_A_PANEL_KIND)] = None) -> dict:
    """이 타깃에서 이미 돈 패널 목록(좌석·라운드·엔진·품질·보고서 id · kind coverage|issue · 쟁점 패널이면 issue_id) — panel_id 의 출처다, kind 로 거른다."""
    def panels(key: str, *, owner_sub: str) -> dict:
        return routes.panels_payload(key, owner_sub=owner_sub, kind=kind)

    return _scoped("target", target_key, panels, target_key)


@mcp.tool()
def risk_get_panel_transcript(panel_id: Annotated[str, Field(description=_A_PANEL_ID)]) -> dict:
    """패널 한 건의 좌석 발언·결정문·risk_spec — 보충 회차 전에 읽어 중복 제기를 막는다."""
    return _scoped("panel", panel_id, routes.panel_transcript_payload, panel_id)


@mcp.tool()
def risk_taxonomy(part: Annotated[str, Field(description=_A_TAX_PART)] = "index",
                  offset: Annotated[int, Field(description=_A_TAX_OFFSET)] = 0) -> dict:
    """통제 어휘 — severity·judgement·direction·domain 등 허용값(추측해 넣으면 422 다), part='index' 는 메커니즘 밖의 축 전부·어휘 색인·메커니즘 → 영역 배정표의 머리(review_status — 승인 전이면 draft), part='mechanism' 은 메커니즘 행, 'mech_owners' 는 배정표 행(owners·related), 'maps' 는 동의어·실패 사상이고, 행 쪽은 약 2만 5천 자씩 주어 남으면 next_offset 을 offset 으로 주고 이어 받는다(자르지 않는다)."""
    def call() -> dict:
        if part in ("mechanism", "mech_owners"):
            total = routes.taxonomy_payload(part, offset=0)["total"]
            return _fit_rows(lambda take: routes.taxonomy_payload(part, offset=offset, limit=take), max(1, total))
        return routes.taxonomy_payload(part, offset=offset)

    return _guarded(call)


@mcp.tool()
def risk_get_precedents(diff_id: Annotated[str, Field(description=_A_DIFF_ID)]) -> dict:
    """선례 — 같은 subject 의 과거 판정과 델타 선례(이 변경이 전에도 문제였나)."""
    # 다른 과제의 행은 소유자와 실제로 부른 사람 둘 다 볼 수 있는 과제의 것만이다(D46) — 범위 판정 · 쓰기는 그대로 소유자로 돈다(D44).
    return _scoped("diff", diff_id, lambda d, *, owner_sub: routes.brief_module.precedents(
        routes.get_store(), d, owner_sub=owner_sub, caller_projects=set(routes.visible_projects(_caller()))), diff_id)


@mcp.tool()
def risk_similar_projects(project_id: Annotated[str, Field(description=_A_PROJECT_ID)],
                          k: Annotated[int, Field(description=_A_SIMILAR_K)] = 5) -> dict:
    """비슷한 과제 top-k — 계보·벡터·서술·subject 네 경로별로 따로 준다(섞지 않는다)."""
    # 다른 과제는 소유자와 실제로 부른 사람 둘 다 볼 수 있는 것만이다(D46) — 구성원이 소유자만 보는 과제를 알게 되지 않는다.
    return _scoped("project", project_id, lambda pid, *, owner_sub: routes.brief_module.similar_projects(
        routes.get_store(), pid, max(1, min(SIMILAR_K_MAX, int(k))), owner_sub=owner_sub,
        caller_projects=set(routes.visible_projects(_caller()))), project_id)


@mcp.tool()
def risk_get_snapshot(snapshot_id: Annotated[str, Field(description=_A_SNAPSHOT_ID)],
                      part: Annotated[str, Field(description=_A_SNAP_PART)],
                      offset: Annotated[int, Field(description=_A_SNAP_OFFSET)] = 0) -> dict:
    """스냅샷 조회(part ∈ ir|state|nodes|edges|calls|rule_hits, nodes·edges 는 한 번에 500 + truncated 이고 next_offset 을 offset 으로 주면 이어 받는다)."""
    limit = NODE_LIMIT if part in ("nodes", "edges") else None
    return _scoped("snapshot", snapshot_id, routes.snapshot_part, snapshot_id, part, limit=limit, offset=offset)


@mcp.tool()
def risk_get_diff(diff_id: Annotated[str, Field(description=_A_DIFF_ID)],
                  part: Annotated[str, Field(description=_A_DIFF_PART)],
                  change_kind: Annotated[str | None, Field(description=_A_CHANGE_KIND)] = None,
                  q: Annotated[str | None, Field(description=_A_DIFF_Q)] = None,
                  offset: Annotated[int, Field(description=_A_DIFF_OFFSET)] = 0,
                  limit: Annotated[int | None, Field(description=_A_DIFF_LIMIT)] = None) -> dict:
    """diff 조회(part ∈ diff|summary|events|lines) — lines 는 브리프 변경 목록과 같은 줄 전부라 변경이 많으면 limit·offset 으로 나눠 받는다(Claude Code 는 MCP 결과가 약 25,000토큰을 넘으면 본문 대신 파일 저장 안내를 준다), change_kind(쉼표로 여럿)·q(이름·코드)로 거르고 offset 은 0 부터, events 는 한 번에 ≤500 이고 next_offset 으로 이어 받는다."""
    if part == "events" and limit is None:
        limit = EVENT_LIMIT
    return _scoped("diff", diff_id, routes.diff_part, diff_id, part, limit=limit, offset=offset,
                   change_kind=change_kind, q=q)


@mcp.tool()
def risk_get_registry(target_key: Annotated[str, Field(description=_A_TARGET_KEY)],
                      status: Annotated[str | None, Field(description=_A_REG_STATUS)] = None,
                      severity: Annotated[str | None, Field(description=_A_REG_SEVERITY)] = None,
                      domain: Annotated[str | None, Field(description=_A_REG_DOMAIN)] = None,
                      offset: Annotated[int, Field(description=_A_REG_OFFSET)] = 0,
                      attention: Annotated[str | None, Field(description=_A_ATTENTION)] = None,
                      unit_id: Annotated[str | None, Field(description=_A_REG_UNIT)] = None) -> dict:
    """타깃 등록부(rr_registry 행 한 번에 최대 200 + verdict 후보) 조회, status·severity·domain·attention(주의 등급 A·B·C·D — 쉼표로 여럿)·unit_id 로 거르고 한 번에 약 2만 5천 자 안에서 주어 남으면 next_offset 을 offset 으로 주고 이어 받는다(자르지 않는다), 쪽은 (family_key, cluster_key) 순이고 쪽마다 ledger_rev(거른 목록 전체의 지문)가 오니 앞 쪽과 다르면 그사이 원장이 바뀐 것이라 offset 0 부터 다시 받는다, 카드 대조 대상의 행에는 지지 수 넷(전문가·영역·단위·검증)·주의 등급·쟁점 상태와 merged.claimed(hold 전 주장값)·distribution 이 있다, 행에 merged_json 은 없고(merged 와 같은 내용) 한 행이 혼자 상한을 넘으면 merged 의 긴 목록을 앞 몇 개와 원래 길이(merged.lists_total)로 준다(전부는 웹 REST GET /api/targets/{key}/registry)."""
    def rows(key: str, *, owner_sub: str) -> dict:
        def page(take: int, keep: int | None = None) -> dict:
            out = routes.registry_payload(key, owner_sub=owner_sub, status=status, severity=severity, domain=domain,
                                          attention=attention, unit_id=unit_id, limit=take, offset=offset)
            return {**out, "rows": [_registry_row(r, keep) for r in out["rows"]]}

        out = _fit_rows(page, REGISTRY_LIMIT)
        for keep in REGISTRY_LIST_KEEP:
            if _wire_chars(out) <= MCP_RESULT_CHARS:
                break
            out = page(len(out["rows"]), keep)          # 한 행이 혼자 넘는다 — 그 행의 긴 목록을 줄인다(next_offset 은 그대로)
        return out

    return _scoped("target", target_key, rows, target_key)


# 등록부 MCP 행 — merged_json 은 merged 와 같은 내용이라 빼고(행 길이의 4할), 한 행이 혼자 와이어를 넘으면 merged 의 긴 목록(원자 id ·
# 제기자 · 인용 …)을 앞 몇 개로 줄이고 원래 길이를 merged.lists_total 에 적는다(review1 H5 — 359명에서 제기자 240명 행 하나가 4만 자라
# 본문과 next_offset 을 함께 잃었다). 전부는 REST GET /api/targets/{key}/registry 다(행 모양 그대로).
REGISTRY_LIST_KEEP: tuple[int, ...] = (20, 5, 1, 0)


def _registry_row(row: dict, keep: int | None) -> dict:
    out = {k: v for k, v in row.items() if k != "merged_json"}
    merged = row.get("merged")
    if keep is None or not isinstance(merged, dict):
        return out
    slim, totals = {}, {}
    for name, value in merged.items():
        if isinstance(value, list) and len(value) > keep:
            slim[name], totals[name] = value[:keep], len(value)
        else:
            slim[name] = value
    return {**out, "merged": {**slim, "lists_total": totals} if totals else slim}


@mcp.tool()
def risk_claims_for_ref(ref: Annotated[str, Field(description=_A_REF)],
                        offset: Annotated[int, Field(description=_A_CLAIM_OFFSET)] = 0) -> dict:
    """참조(ref 문법 §0.2.1)에 앵커된 주장 목록(rr_claim_refs 조인 한 번에 100) 조회, next_offset 을 offset 으로 주면 이어 받는다."""
    # 단일 id 가 아니라 역색인이라 문지기 대신 caller 가 보는 과제 집합으로 결과를 좁힌다(§8.2.5 ②).
    return _guarded(lambda: routes.claims_for_ref(
        ref, limit=CLAIM_LIMIT, projects=routes.visible_projects(_caller()), offset=offset))


@mcp.tool()
def risk_get_brief(target_key: Annotated[str, Field(description=_A_BRIEF_TARGET)],
                   brief_token: Annotated[str, Field(description=_A_BRIEF_TOKEN)],
                   tier: Annotated[str, Field(description=_A_BRIEF_TIER)] = "B") -> dict:
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
    panel_id: Annotated[str, Field(description=_A_SUBMIT_PANEL)],
    engine: Annotated[str, Field(description=_A_ENGINE)],
    decision_text: Annotated[str, Field(description=_A_DECISION)],
    turns: Annotated[list[dict], Field(description=_A_TURNS)],
    report_id: Annotated[int | None, Field(description=_A_REPORT_ID)] = None,
    *,
    actor: Annotated[str, Field(description=_A_SUBMIT_ACTOR)],
    model: Annotated[str | None, Field(description=_A_MODEL)] = None,
    evidence_omitted: Annotated[list[dict] | None, Field(description=_A_OMITTED)] = None,
) -> dict:
    """패널 결과 제출(REST POST /api/panels/{id}/complete 와 같은 함수, 게이트웨이 위임으로 확인된 그 패널 소유자만 낸다, actor 는 미검증 표기, evidence_omitted=[{source,text}] 는 좌석에 못 간 근거)."""
    def call() -> dict:
        # 소유권은 도달한 위임 신원이 정한다 — 자칭 actor 를 열쇠로 쓰면 남이 actor=<소유자> 로 남의 패널을 종결한다(SEC-5).
        owner_sub = entry.require_delegate(routes.mcp_identity(_request()))
        routes._panel_row(panel_id, owner_sub)       # 남의 패널은 없는 패널과 같다 — 종류도 말하지 않는다(남 숨김 훑기)
        # 쟁점 패널(M3 S3-7)은 웹 러너가 돌리고 고쳐 다시 내는 것도 웹·REST 다 — Claude 에서는 지켜본다(risk_get_issues).
        if routes.panel_kind(panel_id) == "issue":
            return {"error": "issue_panel_web_only",
                    "message": "쟁점 패널은 웹 러너가 돌린다 — Claude 에서는 risk_get_issues 로 지켜본다."}
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
    target_key: Annotated[str, Field(description=_A_TARGET_KEY)],
    claim: Annotated[str, Field(description=_A_CLAIM)],
    cites: Annotated[list[dict], Field(description=_A_CITES)],
    *,
    actor: Annotated[str, Field(description=_A_FINDING_ACTOR)],
    direction: Annotated[str, Field(description=_A_DIRECTION)] = "risk",
    domain: Annotated[str | None, Field(description=_A_FINDING_DOMAIN)] = None,
    mechanism: Annotated[str, Field(description=_A_MECHANISM)] = "unclassified",
    mechanism_detail: Annotated[str | None, Field(description=_A_MECH_DETAIL)] = None,
    change_kind: Annotated[str | None, Field(description=_A_FINDING_CHANGE)] = None,
    subject_key: Annotated[str | None, Field(description=_A_SUBJECT_KEY)] = None,
    subject_names: Annotated[list[str] | None, Field(description=_A_SUBJECT_NAMES)] = None,
    severity: Annotated[str | None, Field(description=_A_SEVERITY)] = None,
    judgement: Annotated[str | None, Field(description=_A_JUDGEMENT)] = None,
    warrant: Annotated[str | None, Field(description=_A_WARRANT)] = None,
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
async def risk_next_step(project_id: Annotated[str | None, Field(description=_A_NEXT_PROJECT)] = None) -> dict:
    """Claude 입구의 길잡이(읽기 전용) — 과제가 어느 단계(소스·캡처·리비전·same-as·비교·심사 대상·명단·잡·결과)이고 무엇이 막혔는지(고칠 곳 fix)와 다음에 부를 도구·인자(next)를 한 번에 준다, project_id 없이 부르면 내 과제 목록이고 acting_as 는 이 호출이 누구로 해석됐는지다."""
    return _fit_guide(await _entry(entry.next_step, project_id=project_id))


@mcp.tool()
async def risk_create_project(code: Annotated[str, Field(description=_A_CODE)],
                              name: Annotated[str, Field(description=_A_NAME)],
                              classification: Annotated[str, Field(description=_A_CLASSIFICATION)],
                              stage: Annotated[str | None, Field(description=_A_STAGE)] = None,
                              predecessor_project_id: Annotated[str | None, Field(description=_A_PREDECESSOR)] = None,
                              product_code: Annotated[str | None, Field(description=_A_PRODUCT_CODE)] = None,
                              adh_scope: Annotated[dict | None, Field(description=_A_ADH_SCOPE)] = None) -> dict:
    """심사 과제 만들기 — 쓰기: 사용자에게 과제 코드·이름·등급(classification=internal|confidential, 반출 경계)을 확인한 뒤 부른다, 웹 POST /api/projects 와 같은 함수이고 호출자 소유라 그 사람의 웹 과제 목록에 그대로 뜬다, 같은 code 를 다시 보내면 기존 과제를 돌려준다(created:false), 새 리비전이 소스 앱의 다른 프로젝트면 predecessor_project_id 로 앞 과제를 잇는다."""
    return await _entry(entry.create_project, code=code, name=name, classification=classification, stage=stage,
                        predecessor_project_id=predecessor_project_id, product_code=product_code,
                        adh_scope=adh_scope)


@mcp.tool()
async def risk_add_source(project_id: Annotated[str, Field(description=_A_PROJECT_ID)],
                          kind: Annotated[str, Field(description=_A_SOURCE_KIND)],
                          ref: Annotated[dict, Field(description=_A_SOURCE_REF)],
                          app_key: Annotated[str | None, Field(description=_A_APP_KEY)] = None,
                          bridge_declared: Annotated[bool, Field(description=_A_BRIDGE)] = False) -> dict:
    """과제에 소스 연결 — 쓰기: 어느 과제에 어떤 소스를 붙일지 사용자에게 확인한 뒤 부른다, kind=mcad ref={stepforge_project_id, detect_job_id?}(StepForge) · dyna ref={session_id, file_id}(DynaForge, 본인 세션) · dyna_result ref={report_ids[]}, 같은 소스는 기존 행을 돌려주고 같은 kind 의 다른 소스는 거절한다(캡처는 종류마다 하나만 읽고 소스는 지울 수 없다)."""
    return await _entry(entry.add_source, project_id=project_id, kind=kind, ref=ref, app_key=app_key,
                        bridge_declared=bridge_declared)


@mcp.tool()
async def risk_capture_snapshot(project_id: Annotated[str, Field(description=_A_PROJECT_ID)],
                                label: Annotated[str | None, Field(description=_A_LABEL)] = None,
                                kinds: Annotated[list[str] | None, Field(description=_A_KINDS)] = None,
                                report_ids: Annotated[list[int] | None, Field(description=_A_REPORT_IDS)] = None,
                                detect_result_file_id: Annotated[str | None, Field(description=_A_DETECT_FILE)] = None,
                                allow_large: Annotated[bool, Field(description=_A_ALLOW_LARGE)] = False) -> dict:
    """소스를 읽어 스냅샷 동결 — 쓰기: 어느 과제를 캡처할지 사용자에게 확인한 뒤 부른다, 수십 초~수 분 걸리고 같은 내용이면 기존 스냅샷을 돌려준다(reused), 게이트 결과(blocked·gates_summary)를 함께 준다, 게이트웨이 시간 한도에 끊기면 다시 부르지 말고 risk_next_step 으로 확인한다."""
    return await _entry(entry.capture_snapshot, project_id=project_id, label=label, kinds=kinds,
                        report_ids=report_ids, detect_result_file_id=detect_result_file_id, allow_large=allow_large)


@mcp.tool()
async def risk_ack_gate(snapshot_id: Annotated[str, Field(description=_A_SNAPSHOT_ID)],
                        gate: Annotated[str, Field(description=_A_GATE)],
                        reason: Annotated[str, Field(description=_A_GATE_REASON)],
                        gates_hash: Annotated[str | None, Field(description=_A_GATES_HASH)] = None) -> dict:
    """실패한 비차단 게이트(G1~G5·G7)에 사유 남기기 — 쓰기: 사유를 사용자에게 확인한 뒤 부른다, 진행을 막지 않는 표기라 판정 pass 는 그대로이고 G6(단위·크기)은 차단이라 ack 할 수 없다(소스를 고쳐 재캡처), 같은 ack 는 한 행이다."""
    return await _entry(entry.ack_gate, snapshot_id=snapshot_id, gate=gate, reason=reason, gates_hash=gates_hash)


@mcp.tool()
async def risk_get_sameas(base_snapshot_id: Annotated[str, Field(description=_A_BASE_SNAP)],
                          target_snapshot_id: Annotated[str, Field(description=_A_TARGET_SNAP)]) -> dict:
    """두 스냅샷 사이 같은 부품 대응표(읽기 전용) — 정하지 못한(pending)·충돌·퍼지 매칭 행과 a_stable·b_stable 을 준다, risk_decide_sameas 전에 읽어 사용자에게 보인다."""
    return await _entry(entry.get_sameas, base_snapshot_id=base_snapshot_id, target_snapshot_id=target_snapshot_id)


@mcp.tool()
async def risk_decide_sameas(base_snapshot_id: Annotated[str, Field(description=_A_BASE_SNAP)],
                             target_snapshot_id: Annotated[str, Field(description=_A_TARGET_SNAP)],
                             decisions: Annotated[list[dict], Field(description=_A_DECISIONS)]) -> dict:
    """same-as 확정 — 쓰기: 어느 대응을 confirm|reject 할지 사용자에게 확인한 뒤 부른다, decisions=[{a_stable, b_stable, decision}] 이고 열쇠(scope·pair_key)는 도구가 채운다, 변경 비교를 만들기 전에 해야 그 비교에 반영된다, 같은 결정은 다시 보내도 한 행이다."""
    return await _entry(entry.decide_sameas, base_snapshot_id=base_snapshot_id,
                        target_snapshot_id=target_snapshot_id, decisions=decisions)


@mcp.tool()
async def risk_create_diff(base_snapshot_id: Annotated[str, Field(description=_A_BASE_SNAP)],
                           target_snapshot_id: Annotated[str, Field(description=_A_TARGET_SNAP)]) -> dict:
    """두 스냅샷의 변경 비교 만들기 — 쓰기: 어느 두 스냅샷(base=이전 리비전·target=새 리비전)을 비교할지 사용자에게 확인한 뒤 부른다, 같은 쌍이면 저장된 비교를 돌려주고(created:false) G6 으로 막힌 스냅샷이면 gate_blocked 다."""
    return await _entry(entry.create_diff, base_snapshot_id=base_snapshot_id, target_snapshot_id=target_snapshot_id)


@mcp.tool()
async def risk_open_target(kind: Annotated[str, Field(description=_A_OPEN_KIND)],
                           ref_id: Annotated[str, Field(description=_A_REF_ID)],
                           consent: Annotated[bool, Field(description=_A_OPEN_CONSENT)] = False,
                           flow: Annotated[str | None, Field(description=_A_FLOW)] = None,
                           reason: Annotated[str | None, Field(description=_A_FLOW_REASON)] = None) -> dict:
    """심사 대상 열기 — 쓰기: 무엇을 어느 방식으로 심사할지 사용자에게 확인한 뒤 부른다(동의를 받아 consent=true), kind=diff(변경 심사, ref_id=diff_id)|snap(현황 심사, ref_id=snapshot_id), flow=panels(영역을 섞은 패널 3라운드, 기본)|cells(전문가별 카드 대조 — 단위가 안 서면 panels 로 열고 flow_fallback 에 까닭), 전문가 명단을 고정하고 Tier 별 패널 수를 준다, 이미 연 내 대상이면 그것을 돌려주고(flow 가 다르면 방식을 바꾼다 — reason 은 감사에 남는다) 명단이 비었으면 그 자리에서 다시 받는다."""
    return await _entry(entry.open_target, kind=kind, ref_id=ref_id, consent=consent, flow=flow, reason=reason)


@mcp.tool()
async def risk_start_job(target_key: Annotated[str, Field(description=_A_TARGET_KEY)],
                         tier: Annotated[str | None, Field(description=_A_TIER)] = None,
                         consent: Annotated[bool, Field(description=_A_JOB_CONSENT)] = False,
                         modifiers: Annotated[list[str] | None, Field(description=_A_MODIFIERS)] = None,
                         user_memo: Annotated[str | None, Field(description=_A_USER_MEMO)] = None,
                         concurrency: Annotated[int, Field(description=_A_CONCURRENCY)] = 1,
                         mode: Annotated[str, Field(description=_A_MODE)] = "panels",
                         scope: Annotated[dict | None, Field(description=_A_SCOPE)] = None,
                         llm: Annotated[str | None, Field(description=_A_LLM)] = None,
                         consent_external: Annotated[StrictBool | None, Field(description=_A_CONSENT_EXTERNAL)] = None) -> dict:
    """심사 잡 시작 — 쓰기: 범위와 비용(패널 수·LLM 호출 추정)을 사용자에게 확인한 뒤 부른다(Tier C 와 호출 추정이 큰 검토는 consent=true), mode=panels(기본 — tier 필수, Tier 는 누적이다 A 도메인 대표 → B → C 전원)|reviews(카드 대조 대상의 전문가별 카드 대조 — tier·modifiers·concurrency 없이 scope={agents·domains·tiers·unit_ids} 로 범위를 주고, 전문가는 risk_next_step 의 facts.review_order 를 보고 사용자가 고른다), 심사는 앱 러너가 돌리고 결과는 웹에 그대로 보인다, 같은 대상의 살아 있는 잡(panels 는 같은 Tier)이 있으면 그것을 돌려주고, 자격이 없으면 웹 설정 화면에서 등록하라는 fix 로 답한다. llm=glm(기본 — 빼도 같다)|claude(검토 잡만 — 판단 LLM 이 사용자 본인의 Claude Code 워크플로 hwax-risk-claude 다): 이 잡의 지식카드·설계 변경 원문과, 사슬이 이어 도는 쟁점 패널·종합 요약의 입력(이 대상 전체의 등록부 행·쟁점·요약 — 다른 사람의 검토 결과도 든다)이 Claude(외부)로 나갑니다 — 사용자에게 그 사실을 보이고 동의를 받은 뒤에만 consent_external=true(JSON 참 — 글자 'true' · 1 은 받지 않는다)를 더한다(동의 없이 true 를 채우지 않는다 · 없으면 consent_external_required), 이 박스의 에이전트 서버가 그 길을 열지 않았으면 external_llm_unavailable, 잡은 동의한 사람의 PAT 로만 돌고 그 사람이 Claude Code 에서 워크플로를 돌려야 나아간다(멈추면 보류 external_worker), 사슬이 잇는 쟁점·종합 잡도 같은 선택과 동의를 물려받는다(쟁점 잡은 그 사슬이 고른 쟁점만 — 다른 사람의 GLM 일 · 사람이 올린 쟁점 · 보고서 다시 내기는 GLM 잡으로 간다), mode=panels 에는 llm=claude · consent_external 을 받지 않는다(422)."""
    return await _entry(entry.start_job, target_key=target_key, tier=tier, consent=consent, modifiers=modifiers,
                        user_memo=user_memo, concurrency=concurrency, mode=mode, scope=scope, llm=llm,
                        consent_external=consent_external)


@mcp.tool()
async def risk_job_action(job_id: Annotated[str, Field(description=_A_JOB_ID)],
                          action: Annotated[str, Field(description=_A_ACTION)],
                          reason: Annotated[str | None, Field(description=_A_ACTION_REASON)] = None,
                          filter: Annotated[dict | None, Field(description=_A_CELL_FILTER)] = None,
                          consent: Annotated[bool, Field(description=_A_ACTION_CONSENT)] = False) -> dict:
    """심사 잡 일시정지·재개·취소(action=pause|resume|cancel)와 검토 잡의 실패 셀 처분(action=retry_failed|skip_failed) — 쓰기: 사용자에게 확인한 뒤 부른다(취소는 되돌릴 수 없다), 이미 그 상태면 그대로 돌려주고(changed:false), 앱 재기동으로 멈춘 잡은 resume 해야 이어 돈다. 처분은 그 잡이 찍은 failed 셀을 다시 열거나 사유 reason(4~300자, 넘김은 필수)과 함께 넘긴다 — filter{agent_key?, unit_id?, domain?, error_code?} 로 좁히고, 응답 keys 는 50개까지이고 keys_total 이 전부의 수다. 다시가 세울 검토 잡의 호출 추정이 동의 문턱을 넘으면 consent_required 다 — 범위와 비용을 사용자에게 보이고 동의를 받은 뒤에만 consent=true 로 다시 부른다(REST 의 consent 와 같은 뜻, retry_failed · resume 만). 검토 잡이 다시 연 셀의 몫을 넘어 멈췄으면(hold consent_extra — 진행판 reopened_extra 가 셀 수 · 추정 호출을 준다) 재개에도 같은 동의가 든다, 동의하지 않으면 skip_failed 에 filter={'state':'pending'} 로 그 셀을 넘기고(여유 안이면 잡이 이어 돈다), 잡 상한(hold max_calls)은 동의로 풀리지 않는다."""
    return await _entry(entry.job_action, job_id=job_id, action=action, reason=reason, filter=filter, consent=consent)


@mcp.tool()
async def risk_repersist_panel(panel_id: Annotated[str, Field(description=_A_REPERSIST_PANEL)],
                               discard: Annotated[bool, Field(description=_A_DISCARD)] = False) -> dict:
    """저장 실패한 패널 다시 저장 — 쓰기: 사용자에게 확인한 뒤 부른다, 엔진 결과는 남았는데 원장에 앉히지 못해 persist_error 로 닫힌 패널을 그 결과로 다시 앉힌다(risk_next_step 의 blocked repersist_pending 이 panel_id 를 준다), 그 전에는 재개해도 이 대상에 새 패널이 편성되지 않는다, 같은 결과로 되풀이해 실패하면 discard=true 로 포기한다(엔진 결과는 패널에 남고 좌석은 다음 패널에서 다시 돈다)."""
    return await _entry(entry.repersist_panel, panel_id=panel_id, discard=discard)


# ================================================================ 검토 단위(재설계 M2 U5 — 카드 대조의 단위, 읽기)
def _wire_chars(out: Any) -> int:
    """FastMCP 가 이 결과로 실제로 내는 글의 글자 수 — 구조화 출력이 없는 도구의 dict 는 들여쓰기 2 JSON text 블록 하나다
    (mcp.server.fastmcp.utilities.func_metadata._convert_to_content 와 같은 직렬화)."""
    return len(pydantic_core.to_json(out, fallback=str, indent=2).decode())


def _fit_wire(page: Callable[[int], dict]) -> dict:
    """`page(글자 예산)` 의 와이어 글이 MCP_RESULT_CHARS 안에 들 때까지 예산을 줄여 다시 나눈다(RC-2) — 머리 칸(stats·invariants)과
    들여쓰기까지 실제로 나가는 글로 잰다. 자르지 않는다 — 항목 하나가 혼자 넘으면 그 하나는 싣는다(예산 1 은 한 항목 쪽이다)."""
    budget = UNITS_PAGE_CHARS
    out = page(budget)
    size = _wire_chars(out)
    while size > MCP_RESULT_CHARS and budget > 1:
        budget = max(1, budget * MCP_RESULT_CHARS // size - 1)
        out = page(budget)
        size = _wire_chars(out)
    return out


@mcp.tool()
def risk_get_units(target_key: Annotated[str, Field(description=_A_TARGET_KEY)],
                   unit_id: Annotated[str | None, Field(description=_A_UNITS_UNIT)] = None,
                   part: Annotated[str, Field(description=_A_UNITS_PART)] = "manifest",
                   offset: Annotated[int, Field(description=_A_UNITS_OFFSET)] = 0) -> dict:
    """검토 단위 조회(카드 대조가 전문가마다 도는 단위) — part='manifest' 는 활성 빌드의 단위 목록(seq·종류·제목·목록 글·변경 줄 수), unit_id 와 part ∈ summary|lines|evidence 는 그 단위의 요약 글·변경 줄(소유 + 문맥)·동결 근거이고, 한 번에 약 2만 자씩 주어 남으면 next_offset 을 offset 으로 주고 이어 받는다(자르지 않는다), 단위가 없는 대상은 status 'none' 이다."""
    def manifest(key: str, *, owner_sub: str) -> dict:
        if unit_id:
            raise AppError("E100", "unit_id 를 주면 part 는 summary|lines|evidence 중 하나다.", 422)
        return _fit_wire(lambda budget: routes.units_payload(key, owner_sub=owner_sub, offset=offset,
                                                             budget_chars=budget))

    def one(key: str, *, owner_sub: str) -> dict:
        if not unit_id:
            raise AppError("E100", f"part={part!r} 는 unit_id 가 필요하다 — 목록은 part='manifest' 다.", 422)
        return _fit_wire(lambda budget: routes.unit_payload(key, unit_id, part, owner_sub=owner_sub, offset=offset,
                                                            budget_chars=budget))

    return _scoped("target", target_key, manifest if part == "manifest" else one, target_key)


# ================================================================ 카드 대조 검토(재설계 M2 S12 — 셀 격자 · 전문가 보고서, 읽기)
def _fit_rows(page: Callable[[int], dict], limit: int) -> dict:
    """`page(행 수)` 의 와이어 글이 MCP_RESULT_CHARS 안에 들 때까지 행 수를 줄인다 — 줄인 만큼은 next_offset 으로 이어 받는다(자르지
    않는다). 행 하나가 혼자 넘으면 그 하나는 싣는다."""
    take = max(1, min(int(limit), routes.CELL_LIST_LIMIT_MAX))
    out = page(take)
    size = _wire_chars(out)
    while size > MCP_RESULT_CHARS and len(out["rows"]) > 1:
        n = len(out["rows"])
        take = max(1, min(n - 1, n * MCP_RESULT_CHARS // size))
        out = page(take)
        size = _wire_chars(out)
    return out


def _fit_list(page: Callable[[int], dict], total: int, shown: Callable[[dict], int]) -> dict:
    """`page(행 수)` 의 와이어 글이 MCP_RESULT_CHARS 안에 들 때까지 행 수를 줄인다(R3B-1 — 진행판의 검토 순서 쪽·좌석 행). 줄인 만큼은
    다음 offset 으로 이어 받는다(자르지 않는다). 행 하나가 혼자 넘으면 그 하나는 싣는다."""
    take = max(1, int(total))
    out = page(take)
    size = _wire_chars(out)
    while size > MCP_RESULT_CHARS and shown(out) > 1:
        n = shown(out)
        take = max(1, min(n - 1, n * MCP_RESULT_CHARS // size))
        out = page(take)
        size = _wire_chars(out)
    return out


def _fit_guide(out: dict) -> dict:
    """길잡이 답이 MCP_RESULT_CHARS 를 넘으면 facts.review_order 를 영역마다 앞 순위 2명 → 1명으로 줄인다(R3B-1 — 영역이 많은
    로스터). 줄인 셈은 facts.review_order_page 에 적고, 전부는 risk_get_coverage(order_offset=0) 쪽이다."""
    facts = out.get("facts") if isinstance(out, dict) else None
    if not isinstance(facts, dict) or not isinstance(facts.get("review_order"), list):
        return out
    rows, meta = facts["review_order"], dict(facts.get("review_order_page") or {})
    top = int(meta.get("top_per_domain") or routes.REVIEW_ORDER_TOP)
    while _wire_chars(out) > MCP_RESULT_CHARS and top > 1:
        top -= 1
        rows = [r for r in rows if isinstance(r.get("rank_in_domain"), int) and r["rank_in_domain"] <= top]
        meta.update(shown=len(rows), top_per_domain=top)
        if len(rows) < int(meta.get("total") or 0):
            meta["next_order_offset"] = 0
        out = {**out, "facts": {**facts, "review_order": rows, "review_order_page": meta}}
    return out


@mcp.tool()
def risk_get_cells(target_key: Annotated[str, Field(description=_A_TARGET_KEY)],
                   agent_key: Annotated[str | None, Field(description=_A_CELL_AGENT)] = None,
                   unit_id: Annotated[str | None, Field(description=_A_CELL_UNIT)] = None,
                   state: Annotated[str | None, Field(description=_A_CELL_STATE)] = None,
                   limit: Annotated[int, Field(description=_A_CELL_LIMIT)] = 200,
                   offset: Annotated[int, Field(description=_A_NEXT_OFFSET)] = 0,
                   job_id: Annotated[str | None, Field(description=_A_CELL_JOB)] = None) -> dict:
    """카드 대조 셀 조회(읽기 전용) — 격자(전문가 × 검토 단위)의 셀마다 상태·무엇으로 봤나(basis)·판정 수(n_fail·n_warning…)·카드 수·절단·인용 대조·실패 까닭을 검토 순서로 준다, agent_key·unit_id·state·job_id(그 검토 잡 범위의 셀만 — 로스터 전원 격자에서 지켜볼 셀)로 거르고, 한 번에 약 2만 자 안에서 limit 행까지 주어 남으면 next_offset 을 offset 으로 주고 이어 받는다(자르지 않는다), 판정 행 자체는 risk_get_expert_report 가 준다."""
    def cells(key: str, *, owner_sub: str) -> dict:
        return _fit_rows(lambda take: routes.cells_payload(key, owner_sub=owner_sub, agent_key=agent_key, unit_id=unit_id,
                                                           state=state, limit=take, offset=offset,
                                                           columns=routes.CELL_BRIEF_COLUMNS, job_id=job_id), limit)

    return _scoped("target", target_key, cells, target_key)


def _page_fragments(page: dict) -> int:
    return sum(len(texts) for texts in (page.get("blocks") or {}).values())


def _report_page_chars(meta: dict, report: dict, *, part: str, unit_id: str | None) -> int:
    """MCP 쪽의 글자 크기 — 이 보고서의 쪽 전부가 와이어(들여쓰기 2 JSON) MCP_RESULT_CHARS 안에 들 때까지 줄인다. 쪽 번호가 부르는
    쪽마다 달라지지 않게 쪽 전부로 정한다(같은 보고서면 같은 크기). 조각 하나가 혼자 넘는 쪽은 자르지 않고 그대로 둔다."""
    chars = expert_report.PAGE_CHARS
    while True:
        pages = routes.expert_report_render(report, part=part, unit_id=unit_id, page_chars=chars)
        over = [size for n, page in enumerate(pages, start=1) if _page_fragments(page) > 1
                and (size := _wire_chars(routes.expert_report_envelope(meta, pages, n, part=part, unit_id=unit_id)))
                > MCP_RESULT_CHARS]
        if not over or chars <= 1:
            return chars
        chars = max(1, min(chars - 1, chars * MCP_RESULT_CHARS // max(over) - 1))


@mcp.tool()
def risk_get_expert_report(target_key: Annotated[str, Field(description=_A_TARGET_KEY)],
                           agent_key: Annotated[str, Field(description=_A_EXPERT_AGENT)],
                           part: Annotated[str, Field(description=_A_EXPERT_PART)] = "summary",
                           unit_id: Annotated[str | None, Field(description=_A_EXPERT_UNIT)] = None,
                           page: Annotated[int, Field(description=_A_REPORT_PAGE)] = 1,
                           version: Annotated[int | None, Field(description=_A_REPORT_VERSION)] = None) -> dict:
    """전문가 보고서 읽기(읽기 전용) — 카드 대조 검토가 마감 때 조립한 전문가 한 명의 보고서를 마크다운 쪽으로 준다, part=summary(머리·본 범위·올린 finding·검토 품질)|units(단위별 분석·카드 밖 지적·넘김·필요 정보·메커니즘)|cards(카드 점검표·배경 카드·판정 못 한 카드)|full, unit_id 로 한 단위만, 한 쪽은 약 2만 5천 자 안이고 next_page 를 page 로 주어 이어 받는다(본문을 자르지 않는다 — 쪽을 차례로 이으면 그 part 전체다), 둘째 쪽부터는 첫 쪽 응답의 version 을 version 으로 주면 그사이 다시 마감돼 판이 바뀐 경우 report_version_moved 로 알려 다른 판의 쪽이 섞이지 않는다(그때는 처음 쪽부터 다시), 카드 인용은 판정당 200자이고 원래 길이를 적는다."""
    def report(key: str, *, owner_sub: str) -> dict:
        meta, body = routes.expert_report_source(key, agent_key, owner_sub=owner_sub)
        routes.check_report_version(meta, version)
        chars = _report_page_chars(meta, body, part=part, unit_id=unit_id)
        pages = routes.expert_report_render(body, part=part, unit_id=unit_id, page_chars=chars)
        return routes.expert_report_envelope(meta, pages, page, part=part, unit_id=unit_id)

    return _scoped("target", target_key, report, target_key)


# ================================================================ 쟁점 · 종합 보고서(재설계 M3 S3-10 — 읽기 둘)
ISSUE_LIMIT = 100


@mcp.tool()
def risk_get_issues(target_key: Annotated[str, Field(description=_A_TARGET_KEY)],
                    state: Annotated[str | None, Field(description=_A_ISSUE_STATE)] = None,
                    p_class: Annotated[str | None, Field(description=_A_P_CLASS)] = None,
                    limit: Annotated[int, Field(description=_A_ISSUE_LIMIT)] = ISSUE_LIMIT,
                    offset: Annotated[int, Field(description=_A_ISSUE_OFFSET)] = 0) -> dict:
    """쟁점 목록(읽기 전용, 카드 대조 대상) — 쟁점마다 유형(held_fail·solo_severe·split_verdict)·등급(P1~P3)·순위·상태(queued·planned·running·resolved·inconclusive·untried_cap·withdrawn·skipped)·결과(upheld·downgraded·escalated·rejected·undetermined)·원래 분포(제기·반대 수, 주장 판정별)·좌석과 상한(cap.base·hard·run)을 준다, state(쉼표로 여럿)·p_class 로 거르고 한 번에 약 2만 5천 자 안에서 limit 행까지 주어 남으면 next_offset 을 offset 으로 주고 이어 받는다(자르지 않는다), 쪽은 쟁점 id 순이고 쪽마다 ledger_rev(거른 목록 전체의 지문)가 오니 앞 쪽과 다르면 그사이 원장이 바뀐 것이라 offset 0 부터 다시 받는다, 쟁점은 웹 러너가 돌린다 — Claude 에서는 지켜본다(올리기·건너뛰기는 웹 화면)."""
    def rows(key: str, *, owner_sub: str) -> dict:
        return _fit_rows(lambda take: routes.issues_payload(key, owner_sub=owner_sub, state=state, p_class=p_class,
                                                            limit=take, offset=offset), limit)

    return _scoped("target", target_key, rows, target_key)


def _synthesis_page_chars(meta: dict, report: dict, *, part: str) -> int:
    """종합 보고서 MCP 쪽의 글자 크기 — 그 판의 쪽 전부가 와이어 MCP_RESULT_CHARS 안에 들 때까지 줄인다(같은 판이면 같은 크기, 조각
    하나가 혼자 넘는 쪽은 자르지 않는다 — risk_get_expert_report 와 같은 규칙)."""
    chars = routes.REPORT_PAGE_CHARS
    while True:
        pages = routes.report_render(report, part=part, page_chars=chars)
        over = [size for n, page in enumerate(pages, start=1) if _page_fragments(page) > 1
                and (size := _wire_chars(routes.report_envelope(meta, pages, n, part=part))) > MCP_RESULT_CHARS]
        if not over or chars <= 1:
            return chars
        chars = max(1, min(chars - 1, chars * MCP_RESULT_CHARS // max(over) - 1))


@mcp.tool()
def risk_get_report(target_key: Annotated[str, Field(description=_A_TARGET_KEY)],
                    part: Annotated[str, Field(description=_A_SYNTH_PART)] = "summary",
                    version: Annotated[int | None, Field(description=_A_REPORT_VERSION)] = None,
                    page: Annotated[int, Field(description=_A_REPORT_PAGE)] = 1) -> dict:
    """종합 보고서 읽기(읽기 전용, 카드 대조 대상) — 그 판(rr_reports — 앱 사본이 정본)의 마크다운 쪽, part=summary(완결 표기·잔여·수·종합 서술·주의 A·B·쟁점 결과·미토의 쟁점·품질 블록)|domains(영역 15쪽 — 영역 요약 서술과 행)|mechanisms|appendix(전문가 색인)|full, 한 쪽은 약 2만 5천 자 안이고 next_page 를 page 로 주어 이어 받는다(본문을 자르지 않는다 — 쪽을 다 이으면 그 part 전체다), 둘째 쪽부터는 첫 쪽 응답의 version 을 주면 그사이 새 판이 서도 report_version_moved 로 알려 다른 판의 쪽이 섞이지 않는다, 판이 없으면 report_absent(웹 화면이나 REST 로 만든다)."""
    def report(key: str, *, owner_sub: str) -> dict:
        meta, body = routes.report_source(key, owner_sub=owner_sub)
        routes.check_report_version(meta, version)
        if part not in synth.PARTS:
            raise AppError("E100", f"part 는 {list(synth.PARTS)} 가운데 하나다 — {part!r}.", 422)
        chars = _synthesis_page_chars(meta, body, part=part)
        return routes.report_envelope(meta, routes.report_render(body, part=part, page_chars=chars), page, part=part)

    return _scoped("target", target_key, report, target_key)
