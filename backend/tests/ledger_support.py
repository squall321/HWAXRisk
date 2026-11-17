# 판정표 원장 시험의 공용 상자 — 빈 DB 위에 과제 · 구성원(편집자 · 보기) · 스냅샷 대상과 합성 칸 정의 · 층 다섯을 생산자 함수로 세운다
"""HWAXPortal docs/request-1117 RK-01 ~ RK-06 의 시험이 같이 쓴다. 과제 자료(과제 · 모델 · 부품 · 넷 이름)는 쓰지 않는다 — 코드는 R-001 꼴,
부품은 PART-A 꼴의 합성 값이다. 층 다섯은 요청서의 덮어쓰기 꼴(기준 행 → 앞 회차 행 → 뒤 회차 행 → 수기 수정 → 이어하기 결과)을 따른다."""
from __future__ import annotations

import asyncio
import types

import pytest
from starlette.requests import Request

import app.mcp_server as srv
from app import config, identity, routes
from tests import factories

OWNER = "ledger-owner@example.com"
EDITOR = "ledger-editor@example.com"
VIEWER = "ledger-viewer@example.com"
STRANGER = "ledger-stranger@example.com"
SSO_SECRET = "ledger-test-gateway-secret"

COLUMNS = {"columns": [
    {"name": "부품", "order": 1},
    {"name": "고장 모드", "order": 2},
    {"name": "1차 등급", "order": 3, "grade": True},
    {"name": "최종 등급", "order": 4, "grade": True},
    {"name": "근거 유형", "order": 5, "axis": "type"},
    {"name": "상태", "order": 6, "sp_key": True},
    {"name": "결정 출처", "order": 7},
    {"name": "비고", "order": 8},
    {"name": "그림", "order": 9, "figure": True},
], "code_label": "코드"}

CODES = [f"R-{i:03d}" for i in range(1, 13)]
BASE_ROWS = {code: {"부품": f"PART-{chr(65 + i % 6)}", "고장 모드": f"합성 모드 {i}", "1차 등급": "ABC"[i % 3],
                    "최종 등급": "ABC"[i % 3], "근거 유형": "ABCDEFGHIJ"[i % 10], "상태": "STS-OPEN", "결정 출처": "기준",
                    "비고": "", "그림": f"fig-{i:02d}"}
             for i, code in enumerate(CODES)}
# 덮어쓰기 층 넷(기준 판 위) — 같은 칸을 여러 층이 덮으면 차례가 큰 층이 이긴다.
LAYERS = [
    {"name": "앞 회차 행", "order": 20, "source_file": "round-a.csv",
     "rows": {"R-001": {"최종 등급": "A", "결정 출처": "앞 회차"}, "R-002": {"최종 등급": "B"}, "R-004": {"최종 등급": "C"},
              "R-005": {"최종 등급": "A"}}},
    {"name": "뒤 회차 행", "order": 30, "source_file": "round-b.csv",
     "rows": {"R-004": {"최종 등급": "A", "결정 출처": "뒤 회차"}, "R-005": {"최종 등급": "B"}, "R-006": {"최종 등급": "C"}}},
    {"name": "수기 수정", "order": 40, "source_file": "manual-fix.csv",
     "rows": {"R-002": {"비고": "수기 확인"}, "R-005": {"최종 등급": "C", "결정 출처": "수기"}}},
    {"name": "이어하기 결과", "order": 50, "source_file": "continue.csv",
     "rows": {"R-007": {"최종 등급": "C"}, "R-013": {"부품": "PART-Z", "최종 등급": "B", "결정 출처": "이어하기"}}},
]


def request_as(email: str | None) -> Request:
    headers = []
    if email:
        headers.append((identity.SSO_HEADER.encode(), factories.delegated_assertion(email).encode()))
    return Request({"type": "http", "method": "POST", "path": "/mcp", "headers": headers, "query_string": b""})


def call(tool: str, /, **kwargs) -> dict:
    out = getattr(srv, tool)(**kwargs)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


class LedgerBox(types.SimpleNamespace):
    def act_as(self, email: str | None) -> None:
        request = request_as(email)
        self.monkeypatch.setattr(srv, "_request", lambda: request)


@pytest.fixture
def ledger_box(risk_store, monkeypatch):
    """과제(주인) · 편집자 · 보기 구성원 · 스냅샷 대상 하나. 라우트는 이 DB 를 본다."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: SSO_SECRET)
    project_id = factories.make_project(risk_store, owner=OWNER, code="LEDGER-1")
    routes.put_members(project_id, routes.MembersBody(members=[
        routes.MemberItem(email=EDITOR, role="editor"), routes.MemberItem(email=VIEWER, role="viewer")]),
        ident=factories.ident(OWNER))
    snap = factories.make_snapshot(risk_store, project_id, factories.fixture_adapter_results(), label="DV1", owner=OWNER)
    target_key = factories.make_target(risk_store, "snap", snap["snapshot_id"], agents=factories.agents(), owner=OWNER)
    return LedgerBox(store=risk_store, monkeypatch=monkeypatch, project_id=project_id, snapshot_id=snap["snapshot_id"],
                     target_key=target_key)


def seed_ledger(box) -> dict:
    """칸 정의 · 기준 판(v1 — 기준 행 한 층) · 둘째 판(v2 — 층 넷)을 라우트로 짓는다."""
    from app import ledger_routes

    owner = factories.ident(OWNER)
    ledger_routes.put_template(box.target_key, "columns", COLUMNS, ident=owner)
    v1 = ledger_routes.post_version(box.target_key, ledger_routes.BuildBody(
        layers=[{"name": "기준 행", "order": 10, "rows": BASE_ROWS, "source_file": "base.csv"}]), ident=owner)
    v2 = ledger_routes.post_version(box.target_key, ledger_routes.BuildBody(base_version=v1["version"], layers=LAYERS), ident=owner)
    return {"v1": v1, "v2": v2}
