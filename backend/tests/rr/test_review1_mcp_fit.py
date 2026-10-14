# 반대 검토 1차(review1) 쪽 받기 몫 — 쪽을 잇는 안정 열쇠와 ledger_rev(L3), 제기자가 많은 등록부 행도 MCP 와이어 안에 오고 쪽이 이어진다(H5)
"""원장은 생산자 경로다 — 검토 → 쟁점 → 종합은 test_review1_closure 의 사슬(가짜 검토 엔진 · 가짜 쟁점 패널 엔진 · 가짜 요약 엔진)이
세운다. 쪽은 REST 본체(routes.issues_payload · registry_payload — MCP 가 같은 함수를 쓴다)로 받고, 쪽 사이의 원장 변화는 사람의 쟁점
결정(routes.put_issue)과 등록부 상태 표기(routes.put_registry_status)다. 제기자가 많은 행은 한 영역 전문가 40명이 같은 단위를 같은
카드로 FAIL 로 본 검토 잡(가짜 검토 엔진)이 세운다.
"""
from __future__ import annotations

import pytest

import app.mcp_server as srv
from app import issues, registry, routes, units
from tests import factories
from tests.rr.test_review1_closure import _chained
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

OWNER = rig.OWNER
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}
CROWD = tuple({"key": f"mech-c-{i}", "domain": "mech", "relevance": round(0.95 - i * 0.001, 3)} for i in range(40))


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


def test_a_registry_row_raised_by_a_crowd_fits_the_wire_and_the_pages_still_join(store, monkeypatch):
    """H5 — 제기자가 많은 행은 merged_json(merged 와 같은 내용)과 merged 의 긴 목록(원자 id · 제기자)으로 혼자 와이어를 넘어, 한 행 쪽도
    본문과 next_offset 을 함께 잃었다(359명에서 4만 자). MCP 행은 merged_json 을 빼고, 한 행이 혼자 넘으면 긴 목록을 앞 몇 개와 원래
    길이(merged.lists_total)로 준다 — 쪽마다 상한 안이고 next_offset 으로 이으면 전 행이다. REST 행은 그대로다."""
    roster = rig.ROSTER + CROWD
    key = rig.target(store, roster)
    unit = units.load_units(store, key)[0]["unit_id"]
    job_id = rig.job(store, key, scope={"agents": [r["key"] for r in CROWD], "unit_ids": [unit]})
    fake = FakeReviewEngine(rig.packs(roster))
    fake.verdicts = {str(CARDS["K01"]["record_id"]): ("yes", "FAIL")}
    rig.Rig(store, fake).finish(job_id)
    registry.merge(store, key)
    whole = {r["cluster_key"]: r for r in routes.registry_payload(key, owner_sub=OWNER)["rows"]}
    crowded = max(whole.values(), key=lambda r: len(r["merged"]["member_ids"]))
    assert len(crowded["merged"]["member_ids"]) == 40 and "merged_json" in crowded                 # REST 는 그대로
    limit = 5_000
    assert srv._wire_chars({k: v for k, v in crowded.items() if k != "merged_json"}) > limit        # 한 행이 혼자 넘는다
    monkeypatch.setattr(srv, "MCP_RESULT_CHARS", limit)
    factories.act_as_delegate(monkeypatch, OWNER)
    pages = _pages(lambda offset: srv.risk_get_registry(key, offset=offset))
    assert all(srv._wire_chars(p) <= limit for p in pages), [srv._wire_chars(p) for p in pages]
    got = {r["cluster_key"]: r for p in pages for r in p["rows"]}
    assert set(got) == set(whole) and sum(len(p["rows"]) for p in pages) == len(whole)
    assert not any("merged_json" in r for r in got.values())
    slim = got[crowded["cluster_key"]]["merged"]
    assert slim.get("lists_total", {}).get("member_ids") == 40 and len(slim["member_ids"]) < 40
    assert slim["member_ids"] == crowded["merged"]["member_ids"][:len(slim["member_ids"])]
