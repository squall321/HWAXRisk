# MCP 도구 인자 설명 — 인자마다 inputSchema 설명이 있고, 상한 · 허용값은 코드에서 읽으며, 설명을 달아도 인자 계약(필수 · 기본값 · 형 · 순서)은 그대로다
"""클라이언트 LLM 은 도구 설명과 함께 인자마다 inputSchema 의 description 을 본다(게이트웨이 인자 설명 점수판 — 포털
docs/improvement-1015 6번). 설명이 없으면 값을 이름으로 짐작하고, 손으로 옮겨 적은 상한은 코드가 바뀌면 낡는다.

인자 계약의 고정본(fixtures/mcp_arg_contract.json)은 설명을 달기 전 main 에서 뜬 것이다 — 인자를 일부러 바꿀 때만(도구 · 인자를
더하거나 기본값을 바꿀 때) 그 파일을 함께 고친다. 설명 글만 바꾸는 일로는 고칠 필요가 없다.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import re
import typing
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError

import app.mcp_server as srv
from app import (brief, common, entry, expert_report, issues, narrative, planner, registry, review_cells, review_runner,
                 routes, runner, synth, units)
from app.adapters import dyna as dyna_adapter

CONTRACT = Path(__file__).resolve().parent / "fixtures" / "mcp_arg_contract.json"
_HANGUL = re.compile(r"[가-힣]")


def _schemas() -> dict[str, dict]:
    return {t.name: t.inputSchema for t in asyncio.run(srv.mcp.list_tools())}


def _desc(schemas: dict, tool: str, arg: str) -> str:
    return schemas[tool]["properties"][arg]["description"]


def _max_len(model, field: str) -> int:
    """REST 본문 모델이 그 칸에 건 글자 상한 — 설명이 이 값을 말해야 한다."""
    return next(m.max_length for m in model.model_fields[field].metadata if getattr(m, "max_length", None) is not None)


def _literal(model, field: str) -> tuple[str, ...]:
    """REST 본문 모델의 Literal 칸이 받는 값."""
    return tuple(typing.get_args(model.model_fields[field].annotation))


def test_모든_도구의_인자에_설명이_있다():
    """새 인자를 더하고 설명을 빼먹으면 여기서 걸린다. 설명은 한국어이고 한 줄이며 마침표로 끝난다(쌍점으로 끝내지 않는다)."""
    schemas = _schemas()
    missing, style = [], []
    for name, schema in schemas.items():
        for arg, prop in (schema.get("properties") or {}).items():
            desc = (prop.get("description") or "").strip()
            if not desc:
                missing.append(f"{name}.{arg}")
            elif not (_HANGUL.search(desc) and desc.endswith(".") and "\n" not in desc):
                style.append(f"{name}.{arg}: {desc}")
    assert not missing, missing
    assert not style, style


# (도구, 인자, 설명에 든 글) — 기대 글을 코드 상수에서 만든다. 설명에 수를 손으로 적어 두면 상수가 바뀌는 날 여기서 걸린다.
LIMITS = [
    ("risk_get_snapshot", "part", f"최대 {srv.NODE_LIMIT}행"),
    ("risk_get_diff", "limit", f"events 는 {srv.EVENT_LIMIT}건"),
    ("risk_get_registry", "offset", f"최대 {srv.REGISTRY_LIMIT}행"),
    ("risk_claims_for_ref", "offset", f"최대 {srv.CLAIM_LIMIT}건"),
    ("risk_similar_projects", "k", f"1~{srv.SIMILAR_K_MAX} 사이로"),
    ("risk_get_cells", "limit", f"1~{routes.CELL_LIST_LIMIT_MAX} 사이로"),
    ("risk_get_cells", "limit", f"{srv.MCP_RESULT_CHARS:,}자"),
    ("risk_get_issues", "limit", f"1~{routes.ISSUE_LIST_MAX} 사이로"),
    ("risk_get_issues", "limit", f"{srv.MCP_RESULT_CHARS:,}자"),
    ("risk_get_coverage", "order_offset", f"1~{routes.REVIEW_ORDER_TOP})"),
    ("risk_get_coverage", "seat_offset", f"{srv.MCP_RESULT_CHARS:,}자"),
    ("risk_get_units", "offset", f"{srv.UNITS_PAGE_CHARS:,}자"),
    ("risk_job_action", "reason", f"{routes.REASON_MIN}~{routes.REASON_MAX}자"),
    ("risk_ack_gate", "reason", f"최대 {routes.GATE_ACK_REASON_MAX}자"),
    ("risk_open_target", "reason", f"최대 {_max_len(routes.FlowBody, 'reason')}자"),
    ("risk_create_project", "code", f"최대 {_max_len(routes.ProjectBody, 'code')}자"),
    ("risk_create_project", "name", f"최대 {_max_len(routes.ProjectBody, 'name')}자"),
    ("risk_add_finding", "claim", f"최대 {_max_len(routes.HumanFindingBody, 'claim')}자"),
    ("risk_capture_snapshot", "report_ids", f"최대 {dyna_adapter.MAX_REPORTS}건"),
]


@pytest.mark.parametrize("tool,arg,want", LIMITS, ids=[f"{t}.{a}" for t, a, _ in LIMITS])
def test_인자_설명의_상한은_코드_상수에서_읽는다(tool, arg, want):
    desc = _desc(_schemas(), tool, arg)
    assert want in desc, (want, desc)


def test_유사_과제_k_는_main_의_상한_그대로_상수로_죈다(monkeypatch):
    """main 의 손으로 적은 20 을 상수로 옮겼다 — 값과 죄는 동작이 같다(설명이 그 상수를 읽는다)."""
    assert srv.SIMILAR_K_MAX == 20
    seen: list[int] = []
    monkeypatch.setattr(routes, "mcp_scope_owner", lambda kind, key, caller: "owner@a")
    monkeypatch.setattr(routes, "visible_projects", lambda caller: [])
    monkeypatch.setattr(routes.brief_module, "similar_projects", lambda store, pid, k, **kw: seen.append(k) or {})
    for k in (0, 5, srv.SIMILAR_K_MAX + 7):
        srv.risk_similar_projects("p1", k)
    assert seen == [1, 5, srv.SIMILAR_K_MAX]


def _word(value: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])", text) is not None


# (도구, 인자, 코드가 받는 값) — 설명이 그 값을 다 말한다. 상수에서 읽은 설명도, 뜻을 붙이느라 손으로 적은 설명(잡 조작 · 심사 방식 ·
# 잡 종류 · 발언 stance · 검토 단위 쪽)도 코드의 값과 여기서 맞춘다 — 코드에 값이 늘면 설명이 따라와야 통과한다.
VOCAB = [
    ("risk_taxonomy", "part", routes.TAXONOMY_PARTS),
    ("risk_get_snapshot", "part", routes.SNAPSHOT_PARTS),
    ("risk_get_diff", "part", routes.DIFF_PARTS),
    ("risk_get_diff", "change_kind", brief.KIND_PRIORITY),
    ("risk_get_registry", "severity", routes.HUMAN_SEVERITIES),
    ("risk_get_registry", "attention", tuple(registry.ATTENTION_ORDER)),
    ("risk_claims_for_ref", "ref", common.REF_SCHEMES),
    ("risk_get_brief", "tier", planner.TIERS),
    ("risk_submit_panel_result", "turns", narrative._STANCES),
    ("risk_add_finding", "direction", routes.HUMAN_DIRECTIONS),
    ("risk_add_finding", "severity", routes.HUMAN_SEVERITIES),
    ("risk_add_finding", "judgement", routes.HUMAN_JUDGEMENTS),
    ("risk_create_project", "classification", routes.CLASSIFICATIONS),
    ("risk_add_source", "kind", routes.SOURCE_KINDS),
    ("risk_add_source", "ref", tuple(key for keys in entry.REF_REQUIRED.values() for key in keys)),
    ("risk_ack_gate", "gate", tuple(k for k in routes.GATE_KEYS if k != "G6")),
    ("risk_open_target", "flow", _literal(routes.TargetBody, "flow")),
    ("risk_start_job", "tier", planner.TIERS),
    ("risk_start_job", "modifiers", planner.MODIFIER_WHITELIST + planner.DEFAULT_MODIFIERS),
    ("risk_start_job", "mode", _literal(routes.JobBody, "mode")),
    ("risk_start_job", "scope", review_runner.SCOPE_KEYS),
    ("risk_start_job", "llm", runner.LLM_CHOICES),
    ("risk_job_action", "action", (*routes.JOB_ACTIONS, *entry._DISPOSE_ACTIONS)),
    ("risk_job_action", "filter",
     tuple(k for k in review_cells.SELECTOR_FILTER_KEYS if k != "job_id") + review_cells.CELL_STATES),
    ("risk_repersist_panel", "panel_id", (runner.REPERSIST_PENDING_CODE,)),
    ("risk_get_units", "part", ("manifest", *units.UNIT_PARTS)),
    ("risk_get_cells", "state", review_cells.CELL_STATES),
    ("risk_get_expert_report", "part", expert_report.PARTS),
    ("risk_get_issues", "p_class", tuple(issues.P_ORDER)),
    ("risk_get_report", "part", synth.PARTS),
]


@pytest.mark.parametrize("tool,arg,values", VOCAB, ids=[f"{t}.{a}" for t, a, _ in VOCAB])
def test_인자_설명의_허용값은_코드의_값과_같다(tool, arg, values):
    desc = _desc(_schemas(), tool, arg)
    absent = [v for v in values if not _word(v, desc)]
    assert values and not absent, (absent, desc)


def test_등록부_상태_거름의_허용값은_원장의_CHECK_와_같다(risk_store):
    """등록부 상태는 상수가 아니라 표의 CHECK 에만 있다 — 설명에 손으로 적은 목록을 원장과 맞춘다."""
    sql = risk_store.query_one("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'rr_registry'")["sql"]
    check = re.search(r"status TEXT NOT NULL CHECK\(status IN \(([^)]*)\)\)", sql)
    assert check is not None, sql
    values = re.findall(r"'([a-z_]+)'", check.group(1))
    desc = _desc(_schemas(), "risk_get_registry", "status")
    absent = [v for v in values if not _word(v, desc)]
    assert values and not absent, (absent, desc)


def _contract_now() -> dict[str, dict]:
    out = {}
    for tool in asyncio.run(srv.mcp.list_tools()):
        props = tool.inputSchema.get("properties") or {}
        out[tool.name] = {
            "params": [[p.name, p.kind.name] for p in inspect.signature(getattr(srv, tool.name)).parameters.values()],
            "required": sorted(tool.inputSchema.get("required") or []),
            "properties": {name: {k: v for k, v in prop.items() if k != "description"} for name, prop in props.items()},
        }
    return out


def test_설명을_달아도_인자_계약은_고정본_그대로다():
    """설명은 스키마의 글만 더한다 — 필수 · 기본값 · 형 · 매개변수 순서와 종류(키워드 전용 포함)가 움직이면 기존 호출이 깨진다.

    인자를 일부러 바꿨다면 실패 글의 JSON(지금 값 — null 은 그 도구가 사라졌다는 뜻)을 고정본의 그 도구 자리에 옮긴다."""
    want = json.loads(CONTRACT.read_text(encoding="utf-8"))["tools"]
    got = _contract_now()
    changed = {name: got.get(name) for name in dict.fromkeys([*want, *got]) if got.get(name) != want.get(name)}
    assert list(got) == list(want) and not changed, json.dumps(changed, ensure_ascii=False)


# 동의 인자 — 사용자에게 받은 뒤에만 참이고 길잡이도 에이전트도 채우지 않는다(SEC-4 · Claude 길 X-2).
CONSENT_ARGS = [("risk_open_target", "consent"), ("risk_start_job", "consent"), ("risk_start_job", "consent_external"),
                ("risk_job_action", "consent")]


@pytest.mark.parametrize("tool,arg", CONSENT_ARGS, ids=[f"{t}.{a}" for t, a in CONSENT_ARGS])
def test_동의_인자는_사용자에게_받은_뒤에만_참이라고_말한다(tool, arg):
    desc = _desc(_schemas(), tool, arg)
    assert "동의를 받은 뒤에만" in desc or "동의한 뒤에만" in desc, desc
    assert "자동으로 채우지 않" in desc, desc


@pytest.mark.parametrize("value", ["true", 1])
def test_반출_동의는_설명을_단_뒤에도_JSON_참만_받는다(value):
    """StrictBool 이 Annotated 안에서도 엄격하다 — 글자 'true' · 1 은 도구에 닿기 전에 검증 오류다(형은 boolean 그대로)."""
    with pytest.raises(ToolError, match="consent_external"):
        asyncio.run(srv.mcp.call_tool("risk_start_job", {"target_key": "diff:d1", "consent_external": value}))
