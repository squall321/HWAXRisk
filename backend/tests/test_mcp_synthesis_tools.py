# MCP 쟁점·종합 보고서 도구 둘(재설계 M3 S3-10) — 359명 로스터에서도 한 응답이 와이어 25,000자 안이고 이으면 전부인지 본다
"""입력은 생산자다 — 359명 로스터의 대상은 라우트(rig.target), 판은 synth.assemble_report, 쟁점은 M2 루프 + S3-6 선정 + S3-7 쟁점
패널이다. MCP 읽기 범위는 소유자가 과제를 조직 공개로 바꾼 것(patch_project mcp_visibility='org')으로 연다.
"""
from __future__ import annotations

import pytest

import app.mcp_server as srv
from app import closure, config, issues, registry, routes, runner, synth
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.issue_panel_engine import IssuePanelEngine

OWNER = rig.OWNER
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_issue_panel_cap=3, risk_issue_panel_hard_cap=3)
    return risk_store


def _open_to_org(store, key: str) -> None:
    project_id = store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]
    with factories.routes_store(store):
        routes.patch_project(project_id, routes.ProjectPatchBody(mcp_visibility="org"), ident=factories.ident(OWNER))


def _roster_359() -> list[dict]:
    domains = list(config.settings.risk_roster_domains)
    return [{"key": f"{domains[i % len(domains)]}-big-{i:03d}", "domain": domains[i % len(domains)],
             "relevance": round(0.99 - (i // len(domains)) * 0.01, 2)} for i in range(359)]


def test_the_report_tool_pages_a_359_expert_appendix_within_the_wire_limit(store):
    """359명 로스터 대상의 판 — risk_get_report 의 쪽 전부가 와이어 25,000자 안이고 next_page 로 이으면 그 part 전체다(부록 색인 359줄).
    둘째 쪽부터 version 을 주고, 어긋나면 report_version_moved 다."""
    key = rig.target(store, _roster_359())
    synth.assemble_report(store, key, trigger="manual")
    _open_to_org(store, key)
    report = synth.report_source(store, key)
    for part in ("appendix", "full"):
        first = srv.risk_get_report(key, part=part)
        pages, page = [first], first
        while "next_page" in page:
            page = srv.risk_get_report(key, part=part, page=page["next_page"], version=first["version"])
            pages.append(page)
        assert all(srv._wire_chars(p) <= srv.MCP_RESULT_CHARS for p in pages), [srv._wire_chars(p) for p in pages]
        joined = "\n".join(t for p in pages for b in synth.BLOCKS for t in p["page"]["blocks"][b])
        assert joined == synth.render_report_md(report, part=part)
    appendix = synth.render_report_md(report, part="appendix").split("\n")
    assert sum(1 for line in appendix if line.startswith("- ")) == 359
    assert srv.risk_get_report(key, version=first["version"] + 1)["error"] == "report_version_moved"
    assert srv.risk_get_report(key, part="nope")["error"] == "E100"


def test_the_issue_tool_pages_under_a_tight_wire_limit_and_covers_every_issue(store, monkeypatch):
    """risk_get_issues — 와이어 한도를 좁혀도 한 응답이 그 안이고 next_offset 으로 이으면 쟁점 전부다(자르지 않는다)."""
    key = rig.target(store)
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {str(CARDS["K01"]["record_id"]): ("yes", "FAIL")}
    fake.mechs = {str(CARDS["K01"]["record_id"]): ("interface.clearance", "")}
    rig.Rig(store, fake).finish(job_id)
    registry.merge(store, key)
    issues.select_issues(store, key, selected_round=1, cells_hash=closure.closing_hash(store, key))
    _open_to_org(store, key)
    every = [r["issue_id"] for r in routes.issues_payload(key, owner_sub=OWNER, limit=500)["rows"]]
    assert len(every) >= 3
    monkeypatch.setattr(srv, "MCP_RESULT_CHARS", 2_500)
    got, offset = [], 0
    while True:
        page = srv.risk_get_issues(key, offset=offset)
        assert srv._wire_chars(page) <= 2_500 or len(page["rows"]) == 1
        got += [r["issue_id"] for r in page["rows"]]
        if "next_offset" not in page:
            break
        offset = page["next_offset"]
    assert got == every


def test_an_issue_panel_result_is_not_submitted_from_claude(store, monkeypatch):
    """risk_submit_panel_result — 쟁점 패널은 웹 러너가 돌리고 고쳐 다시 내는 것도 웹·REST 다(issue_panel_web_only). 위임 신원은
    tests/test_mcp_write_identity.py 가 보는 게이트웨이 단언 대신 그 문의 결과(소유자)로 세운다."""
    key = rig.target(store)
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {str(CARDS["K01"]["record_id"]): ("yes", "FAIL")}
    fake.mechs = {str(CARDS["K01"]["record_id"]): ("interface.clearance", "")}
    rig.Rig(store, fake).finish(job_id)
    registry.merge(store, key)
    issues.select_issues(store, key, selected_round=1, cells_hash=closure.closing_hash(store, key))
    issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    engine = IssuePanelEngine(store)
    runner.run_panel(store, config.settings, engine, runner.claim_next_job(store, config.settings, engine=engine))
    panel_id = store.query_one("SELECT id FROM rr_panels WHERE target_key = ? AND kind = 'issue'", (key,))["id"]
    before = dict(store.query_one("SELECT * FROM rr_panels WHERE id = ?", (panel_id,)))
    monkeypatch.setattr(srv.entry, "require_delegate", lambda _identity: OWNER)
    out = srv.risk_submit_panel_result(panel_id, "mcp", "결정문", [], actor=OWNER)
    assert out.get("error") == "issue_panel_web_only", out
    assert dict(store.query_one("SELECT * FROM rr_panels WHERE id = ?", (panel_id,))) == before
