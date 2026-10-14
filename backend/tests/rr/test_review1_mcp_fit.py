# 반대 검토 1차(review1) 쪽 받기 몫 — 쪽을 잇는 안정 열쇠와 ledger_rev(L3)
"""원장은 생산자 경로다 — 검토 → 쟁점 → 종합은 test_review1_closure 의 사슬(가짜 검토 엔진 · 가짜 쟁점 패널 엔진 · 가짜 요약 엔진)이
세운다. 쪽은 REST 본체(routes.issues_payload · registry_payload — MCP 가 같은 함수를 쓴다)로 받고, 쪽 사이의 원장 변화는 사람의 쟁점
결정(routes.put_issue)과 등록부 상태 표기(routes.put_registry_status)다.
"""
from __future__ import annotations

import pytest

import app.mcp_server as srv
from app import issues, routes
from tests import factories
from tests.rr.test_review1_closure import _chained
from tests.synth import review_rig as rig

OWNER = rig.OWNER


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_issue_panel_cap=1, risk_issue_panel_hard_cap=1)
    return risk_store


def _pages(fetch) -> list[dict]:
    pages, offset = [], 0
    while offset is not None:
        pages.append(fetch(offset))
        offset = pages[-1].get("next_offset")
    return pages


def test_issue_pages_follow_the_issue_id_and_a_change_between_pages_moves_the_ledger_rev(store):
    """L3(결정) — 쟁점 쪽은 쟁점 id 순이고(러너가 다시 고르며 바꾸는 순위로 나누면 쪽 사이에 행이 빠지거나 겹친다) 쪽마다 ledger_rev 가
    온다. 바뀌지 않은 원장의 쪽은 같은 rev 이고 이으면 전부다. 쪽 사이에 원장이 바뀌면(사람이 쟁점 하나를 건너뛰었다) 다음 쪽의 rev
    가 앞 쪽과 달라 처음부터 다시 받을 때를 안다."""
    key = _chained(store)
    ids = sorted(r["issue_id"] for r in issues.issue_rows(store, key))
    assert len(ids) >= 3
    with factories.routes_store(store):
        pages = _pages(lambda offset: routes.issues_payload(key, owner_sub=OWNER, limit=2, offset=offset))
        assert len(pages) >= 2 and len({p.get("ledger_rev") for p in pages}) == 1 and pages[0].get("ledger_rev")
        assert [r["issue_id"] for p in pages for r in p["rows"]] == ids
        untried = next(r["issue_id"] for r in issues.issue_rows(store, key) if r["state"] == "untried_cap")
        routes.put_issue(untried, routes.IssueActionBody(action="skip", reason="이번 판에서는 넘긴다"),
                         ident=factories.ident(OWNER))
        moved = routes.issues_payload(key, owner_sub=OWNER, limit=2, offset=pages[0]["next_offset"])
    assert moved.get("ledger_rev") != pages[0]["ledger_rev"]


def test_registry_pages_follow_the_family_key_and_a_change_between_pages_moves_the_ledger_rev(store):
    """L3(결정) — 등록부를 쪽으로 받으면(MCP) (family_key, cluster_key) 순이고(주의 등급·우선순위는 병합마다 바뀐다) 쪽마다 ledger_rev
    가 온다. 쪽 사이에 사람이 한 행의 상태를 바꾸면 rev 가 달라진다."""
    key = _chained(store)
    with factories.routes_store(store):
        whole = routes.registry_payload(key, owner_sub=OWNER)
        pages = _pages(lambda offset: routes.registry_payload(key, owner_sub=OWNER, limit=3, offset=offset))
        assert len(pages) >= 2 and len({p.get("ledger_rev") for p in pages}) == 1 and pages[0].get("ledger_rev")
        family = {r["cluster_key"]: r["family_key"] or "" for r in store.query(
            "SELECT cluster_key, family_key FROM rr_registry WHERE target_key = ?", (key,))}
        got = [(family[r["cluster_key"]], r["cluster_key"]) for p in pages for r in p["rows"]]
        assert got == sorted((family[r["cluster_key"]], r["cluster_key"]) for r in whole["rows"])
        assert len(set(family.values())) > 1                                     # 묶음이 여럿이라 순서가 뜻이 있다
        routes.put_registry_status(whole["rows"][0]["cluster_key"],
                                   routes.RegistryStatusBody(status="mitigated", target_key=key, note="설계에서 막았다"),
                                   ident=factories.ident(OWNER))
        moved = routes.registry_payload(key, owner_sub=OWNER, limit=3, offset=pages[0]["next_offset"])
    assert moved.get("ledger_rev") != pages[0]["ledger_rev"]


def test_the_paging_tools_tell_the_caller_about_the_ledger_rev():
    """L3(결정) — 도구 설명이 안정 열쇠와 ledger_rev 로 다시 받는 법을 말한다."""
    import asyncio

    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    for name, order in (("risk_get_issues", "쟁점 id 순"), ("risk_get_registry", "(family_key, cluster_key) 순")):
        assert order in tools[name].description and "ledger_rev" in tools[name].description and "offset 0" in (
            tools[name].description), name
