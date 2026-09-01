#!/usr/bin/env python3
# AIDataHub 부트스트랩 — doc_type 3종·의사 에이전트 1을 게이트웨이 MCP 로 멱등 생성한다(plan §5.4.1·§5.4.7)
"""실행자 셸 전용 스크립트다. 앱 런타임(`adh_client.py`)은 이 파일을 부르지 않는다.

    HWAXRISK_AIDH_API_KEY=… HWAXRISK_PORTAL_PAT=… \\
        python backend/scripts/bootstrap_adh.py [--base <게이트웨이 MCP 엔드포인트>] [--apply]

절차(RA 부트스트랩과 같은 방식).
 (1) `list_doc_types` · `list_agents` 로 현재 목록을 읽는다.
 (2) 아래 상수표(DOC_TYPES · AGENT)와 대조해 **없는 것만** 생성 후보로 만든다.
 (3) 있는 것의 정의가 다르면 `drift` 로 보고만 하고 `patch_agent` · 갱신 계열은 절대 부르지 않는다.
 (4) 기본은 dry-run 이고 `--apply` 일 때만 doc_type → 에이전트 순서로 생성한다.
 (5) `{created, skipped, drift, …}` JSON 을 내고 drift 가 있으면 종료 코드 2 다.

자격 둘. `HWAXRISK_AIDH_API_KEY` 는 도구 인자 `api_key`(AIDH `X-API-Key` 평문)이고
`HWAXRISK_PORTAL_PAT` 는 게이트웨이 호출 헤더 `Authorization: Bearer …` 다(plan §5.4.1).

종료 코드. 0 정상 · 1 호출 실패 · 2 drift 있음 · 3 자격 없음(호출 0건).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

# 실행자 셸에서 `python backend/scripts/bootstrap_adh.py` 로 돌 때 앱 패키지를 찾게 한다
# (streamable-http MCP 전송은 app.ra_client.McpHttpClient 하나만 쓴다 — 중복 구현하지 않는다).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ra_client import DEFAULT_TIMEOUT, McpHttpClient  # noqa: E402

API_KEY_ENV = "HWAXRISK_AIDH_API_KEY"
PORTAL_PAT_ENV = "HWAXRISK_PORTAL_PAT"
GATEWAY_ENV = "HWAXRISK_GATEWAY_MCP"
DEFAULT_GATEWAY = "http://127.0.0.1:9110/mcp"

# 읽기 2종·쓰기 2종. 여기 없는 도구는 부르지 않는다(`bind_records_to_agent`·`patch_agent` 호출 금지).
READ_TOOLS = ("list_doc_types", "list_agents")
WRITE_TOOLS = ("create_doc_type", "create_agent")

# ---------------------------------------------------------------- doc_type 3종(plan §5.4.1)
DOC_TYPES: tuple[dict, ...] = (
    {"code": "risk_review_opinion", "name": "리스크 심사 좌석 의견",
     "description": "HWAX 리스크 심사에서 전문가 좌석 1석이 타깃 1개에 대해 남긴 서술(코드 추출, LLM 재요약 없음)",
     "expected_sections": ["대상과 변화 요약", "관점(도메인) 평가", "리스크 목록", "개선되는 점",
                           "권고·추가 확인", "과제 성격(정성)", "반박·소수의견"],
     "mode": "llm_context"},
    {"code": "risk_review_panel", "name": "리스크 심사 패널 결정문",
     "description": "HWAX 리스크 심사 패널 1건의 의장 결정문 8항목과 risk_spec(코드 조립, LLM 재요약 없음)",
     "expected_sections": ["심사 대상과 비교 축", "변경 원장", "도메인별 리스크 판정", "개선되는 점",
                           "과제 성격 서술", "교차 도메인 상호작용", "확인 필요·미지영역",
                           "합의·소수의견·신뢰도", "risk_spec"],
     "mode": "llm_context"},
    {"code": "project_character", "name": "과제 성격",
     "description": "HWAX 리스크 심사가 과제 1건에 누적한 정성 성격 서술(스냅샷·패널이 늘 때마다 UPSERT)",
     "expected_sections": ["과제 개요·소스", "관찰 태그와 유사 과제", "설계 의도", "제약", "이례성",
                           "계보", "취약 계면", "강점", "맞교환", "미지", "판정 이력", "다음 확인"],
     "mode": "llm_context"},
)

# ---------------------------------------------------------------- 의사 에이전트 1(plan §5.4.7)
AGENT: dict = {
    "agent_type": "risk-review-memory", "name": "리스크 심사 기억", "domain": "xd",
    "description": "HWAX 리스크 심사 좌석 의견·패널 결정문·과제 성격 레코드의 회수 범위"
                   "(의사 에이전트, 좌석으로 착석하지 않음)",
    "common_tags": ["hwax-risk-review"],
}

# drift 로 볼 정의 필드 — `list_doc_types`·`list_agents` 가 돌려주는 것만 대조한다.
DOC_TYPE_FIELDS = ("name", "description", "expected_sections")
AGENT_FIELDS = ("name", "description", "common_tags")


class BootstrapError(RuntimeError):
    """AIDataHub 호출이 실패했다. 되돌리지 않고 종료 코드 1 로 끝낸다."""


def _rows(payload: Any, key: str) -> list[dict]:
    """도구 결과에서 행 목록을 뽑는다 — `{<key>: [...]}` · `{result: [...]}` · 목록 그대로."""
    if isinstance(payload, Mapping):
        for field in (key, "result", "items"):
            value = payload.get(field)
            if isinstance(value, list):
                payload = value
                break
        else:
            return []
    if not isinstance(payload, list):
        return []
    return [row for row in payload if isinstance(row, Mapping)]


def _norm(field: str, value: Any) -> Any:
    """대조용 정규화 — 태그는 정렬 목록, 섹션은 순서를 지킨 목록으로 본다."""
    if field == "common_tags":
        return sorted(str(v) for v in value or [])
    if field == "expected_sections":
        return [str(v) for v in value or []]
    return value if value is not None else ""


def _diff(kind: str, name: str, planned: Mapping[str, Any], actual: Mapping[str, Any],
          fields: Sequence[str]) -> list[dict]:
    """계획표와 실제 정의의 차이를 drift 줄로 만든다. 고치지 않는다 — 보고만 한다."""
    out = []
    for field in fields:
        want = _norm(field, planned.get(field))
        got = _norm(field, actual.get(field))
        if want != got:
            out.append({"kind": kind, "name": name, "field": field, "planned": want, "actual": got})
    return out


def _call(mcp: McpHttpClient, name: str, arguments: Mapping[str, Any]) -> Any:
    if name not in READ_TOOLS + WRITE_TOOLS:
        raise BootstrapError(f"계약에 없는 도구입니다: {name}")
    reply = mcp.call(name, arguments)
    if not reply.get("ok"):
        raise BootstrapError(f"{name} — {reply.get('error')}: {reply.get('detail') or reply.get('reason')}")
    return reply.get("result")


def survey(mcp: McpHttpClient, api_key: str) -> dict:
    """현재 doc_type·에이전트 목록을 읽는다(읽기만 한다)."""
    doc_types = {str(row.get("code")): row
                 for row in _rows(_call(mcp, "list_doc_types", {"api_key": api_key}), "doc_types")}
    agents = {str(row.get("agent_type")): row
              for row in _rows(_call(mcp, "list_agents", {}), "agents")}
    return {"doc_types": doc_types, "agents": agents}


def build_plan(mcp: McpHttpClient, api_key: str) -> tuple[dict, dict, list[dict]]:
    """(생성 후보, 건너뛴 수, drift) — 이 함수는 읽기 도구만 부른다."""
    existing = survey(mcp, api_key)
    todo: dict[str, list] = {"doc_types": [], "agents": []}
    skipped = {"doc_types": 0, "agents": 0}
    drift: list[dict] = []

    for doc_type in DOC_TYPES:
        actual = existing["doc_types"].get(doc_type["code"])
        if actual is None:
            todo["doc_types"].append(doc_type)
            continue
        skipped["doc_types"] += 1
        drift.extend(_diff("doc_type", doc_type["code"], doc_type, actual, DOC_TYPE_FIELDS))

    actual = existing["agents"].get(AGENT["agent_type"])
    if actual is None:
        todo["agents"].append(AGENT)
    else:
        skipped["agents"] += 1
        drift.extend(_diff("agent", AGENT["agent_type"], AGENT, actual, AGENT_FIELDS))

    return todo, skipped, drift


def apply_plan(mcp: McpHttpClient, api_key: str, todo: Mapping[str, list]) -> dict:
    """doc_type → 에이전트 순서로 생성한다. 이미 있는 것은 후보에 없으므로 재호출도 없다."""
    created = {"doc_types": 0, "agents": 0}
    for doc_type in todo["doc_types"]:
        result = _call(mcp, "create_doc_type", {"doc_type": doc_type, "api_key": api_key})
        _require_created(result, f"create_doc_type({doc_type['code']})")
        created["doc_types"] += 1
    for agent in todo["agents"]:
        result = _call(mcp, "create_agent", {"agent": agent, "api_key": api_key})
        _require_created(result, f"create_agent({agent['agent_type']})")
        created["agents"] += 1
    return created


def _require_created(result: Any, what: str) -> None:
    """AIDataHub 쓰기 도구는 실패도 200 으로 `{status:'error'}` 를 준다 — 그것도 실패로 본다."""
    status = result.get("status") if isinstance(result, Mapping) else None
    if status != "created":
        raise BootstrapError(f"{what} — {json.dumps(result, ensure_ascii=False)[:300]}")


def report(mode: str, todo: Mapping[str, list], skipped: Mapping[str, int], drift: Sequence[dict],
           created: Mapping[str, int] | None) -> dict:
    """`{created, skipped, drift}` 중심의 결과 JSON."""
    return {
        "mode": mode,
        "created": dict(created or {"doc_types": 0, "agents": 0}),
        "candidates": {
            "doc_types": [d["code"] for d in todo["doc_types"]],
            "agents": [a["agent_type"] for a in todo["agents"]],
        },
        "skipped": dict(skipped),
        "drift": list(drift),
    }


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AIDataHub doc_type 3종·의사 에이전트 1 부트스트랩(멱등, dry-run 기본) — plan §5.4.1")
    parser.add_argument("--base", default=os.environ.get(GATEWAY_ENV) or DEFAULT_GATEWAY,
                        help=f"게이트웨이 MCP 엔드포인트(기본 {GATEWAY_ENV} 또는 {DEFAULT_GATEWAY})")
    parser.add_argument("--apply", action="store_true", help="실제로 생성한다(기본은 dry-run)")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="HTTP 타임아웃(초)")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, client: Any = None,
         mcp: McpHttpClient | None = None) -> int:
    args = _parse_args(argv)
    api_key = (os.environ.get(API_KEY_ENV) or "").strip()
    portal_pat = (os.environ.get(PORTAL_PAT_ENV) or "").strip()
    missing = [name for name, value in ((API_KEY_ENV, api_key), (PORTAL_PAT_ENV, portal_pat)) if not value]
    if missing:
        print(f"자격이 없습니다 — env {' · '.join(missing)} 를 설정하고 다시 실행하세요.\n"
              f"  {API_KEY_ENV} 는 도구 인자 api_key(AIDH X-API-Key), "
              f"{PORTAL_PAT_ENV} 는 게이트웨이 Authorization 헤더입니다.\n"
              "자격이 없으므로 AIDataHub 를 한 번도 부르지 않고 종료합니다.", file=sys.stderr)
        return 3

    own_mcp = mcp is None
    if mcp is None:
        mcp = McpHttpClient(args.base, headers={"Authorization": f"Bearer {portal_pat}"},
                            client=client, timeout=args.timeout)
    try:
        todo, skipped, drift = build_plan(mcp, api_key)
        created = apply_plan(mcp, api_key, todo) if args.apply else None
    except BootstrapError as exc:
        print(f"부트스트랩 실패 — {exc}", file=sys.stderr)
        return 1
    finally:
        if own_mcp:
            mcp.close()

    print(json.dumps(report("apply" if args.apply else "dry-run", todo, skipped, drift, created),
                     ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
