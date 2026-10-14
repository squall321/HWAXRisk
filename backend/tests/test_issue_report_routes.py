# 쟁점·종합 보고서의 REST 와 MCP 한 벌(재설계 M3 S3-10) — 웹과 Claude 가 같은 함수로 읽고 와이어 한도 안에서 쪽으로 받는지 본다
"""입력은 생산자다 — 원장은 가짜 검토 엔진의 M2 루프, 쟁점은 S3-6 선정과 S3-7 쟁점 패널(가짜 쟁점 패널 엔진), 보고서 판은
synth.assemble_report 와 종합 잡(가짜 요약 엔진). 남의 과제는 새 경로 전부 404, MCP 는 not_visible 이다.
"""
from __future__ import annotations

import pytest

import app.mcp_server as srv
from app import closure, config, issues, registry, routes, runner, synth
from app.errors import AppError
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.issue_panel_engine import IssuePanelEngine

OWNER = rig.OWNER
OTHER = "other@example.com"
EDITOR = "editor@example.com"
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}
ISSUE_KEYS = {"issue_id", "rank", "types", "p_class", "priority", "anchor_cluster_key", "unit_id", "state", "state_reason",
              "outcome", "outcome_json", "distribution", "panel_id", "seats", "selected_round", "attempts", "charged"}


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_issue_panel_cap=2, risk_issue_panel_hard_cap=2)
    return risk_store


def _ledger(store, *, run_issues: bool = True) -> str:
    key = rig.target(store)
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {str(CARDS["K01"]["record_id"]): ("yes", "FAIL")}
    fake.mechs = {str(CARDS["K01"]["record_id"]): ("interface.clearance", "")}
    rig.Rig(store, fake).finish(job_id)
    registry.merge(store, key)
    issues.select_issues(store, key, selected_round=1, cells_hash=closure.closing_hash(store, key))
    if run_issues:
        issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
        engine = IssuePanelEngine(store, {"*": {"severity": "중대", "judgement": "FAIL"}})
        while (job := runner.claim_next_job(store, config.settings, engine=engine)) is not None:
            if runner.run_panel(store, config.settings, engine, job)["status"] == "no_panel":
                break
    return key


def _project(store, key: str) -> str:
    return store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]


# ---------------------------------------------------------------- 쟁점
def test_the_issue_list_has_the_contract_fields_filters_and_pages(store):
    """GET /targets/{key}/issues — 행 칸이 계약(3.11) 그대로이고 근거 원문은 싣지 않는다(분포만). 상태·등급·유형으로 거르고 limit 뒤는
    next_offset 으로 이어 받으면 전부다. 상한 칸은 기본·하드·돌린 수다."""
    key = _ledger(store)
    out = routes.issues_payload(key, owner_sub=OWNER)
    assert out["rows"] and all(set(r) == ISSUE_KEYS for r in out["rows"])
    assert out["cap"] == {"base": 2, "hard": 2, "run": 2} and out["total"] == len(out["rows"])
    assert all("basis" not in r and isinstance(r["distribution"]["raisers"], int) for r in out["rows"])
    done = routes.issues_payload(key, owner_sub=OWNER, state="resolved")["rows"]
    assert done and {r["state"] for r in done} == {"resolved"} and all(r["seats"] for r in done)
    held = routes.issues_payload(key, owner_sub=OWNER, type="held_fail")["rows"]
    assert held and all("held_fail" in r["types"] for r in held)
    collected, offset = [], 0
    while True:
        page = routes.issues_payload(key, owner_sub=OWNER, limit=1, offset=offset)
        collected += [r["issue_id"] for r in page["rows"]]
        if "next_offset" not in page:
            break
        offset = page["next_offset"]
    assert collected == [r["issue_id"] for r in out["rows"]]


def test_a_person_queues_an_untried_issue_or_skips_one_with_a_reason_and_an_audit_row(store):
    """PUT /issues/{id} — 편집자 이상, 사유 필수(422), 편성·도는 쟁점은 409. queue 는 상한 밖 쟁점을 대기로 올리고 쟁점 잡을 세운다
    (상한을 넘기는 사람의 결정), skip 은 skipped(완결 잔여 '미토의' 에 든다). 행위마다 rr_audit 한 행."""
    key = _ledger(store, run_issues=False)
    rows = issues.issue_rows(store, key)
    untried = next(r for r in rows if r["state"] == "untried_cap")
    queued = next(r for r in rows if r["state"] == "queued")
    with factories.routes_store(store):
        with pytest.raises(AppError) as blank:
            routes.put_issue(untried["issue_id"], routes.IssueActionBody(action="queue", reason=" "),
                             ident=factories.ident(OWNER))
        assert blank.value.http_status == 422
        with pytest.raises(AppError) as other:
            routes.put_issue(untried["issue_id"], routes.IssueActionBody(action="queue", reason="봐야 한다"),
                             ident=factories.ident(OTHER))
        assert other.value.http_status == 404
        out = routes.put_issue(untried["issue_id"], routes.IssueActionBody(action="queue", reason="상한을 넘겨 본다"),
                               ident=factories.ident(OWNER))
        assert out["state"] == "queued" and out["job_id"]
        skipped = routes.put_issue(queued["issue_id"], routes.IssueActionBody(action="skip", reason="다음 리비전에서 본다"),
                                   ident=factories.ident(OWNER))
        assert skipped["state"] == "skipped"
    after = {r["issue_id"]: r for r in issues.issue_rows(store, key)}
    assert (after[untried["issue_id"]]["state"], after[untried["issue_id"]]["status_source"]) == ("queued", "human")
    actions = sorted(r["action"] for r in store.query("SELECT action FROM rr_audit WHERE subject_id = ? AND action LIKE"
                                                      " 'issue.%'", (key,)))
    assert actions == ["issue.queue", "issue.skip"]
    assert any(q["item"] == "issues_untried" for q in closure.close_level_cells(store, key, persist=False)["qualifiers"])
    job = runner.claim_next_job(store, config.settings)                    # 대기 쟁점을 러너가 편성해 돌린다
    panel = issues.plan_issue_panel(store, key, job=job)
    issues.start_issue_panel(store, panel["id"])
    with factories.routes_store(store), pytest.raises(AppError) as busy:
        routes.put_issue(panel["issue_id"], routes.IssueActionBody(action="skip", reason="그만"),
                         ident=factories.ident(OWNER))
    assert busy.value.http_status == 409


# ---------------------------------------------------------------- 보고서
def test_the_report_reads_by_pages_and_a_moved_version_is_409(store):
    """GET /targets/{key}/report — 판이 없으면 404 report_absent. 판이 서면 md 쪽(next_page 로 이어 받으면 part 전체), json 은 쪽 전체,
    version 이 지금 판과 다르면 409 report_version_moved. POST 는 코드 조립 판(refresh_summaries=false — 내용이 같으면 그 판 그대로)이나
    종합 잡(true)."""
    with pytest.raises(AppError) as absent:
        routes.report_payload(rig.target(store), owner_sub=OWNER)                     # 검토 전 — 사슬이 판을 세우기 전
    assert absent.value.code == "report_absent"
    key = _ledger(store)
    chained = synth.report_source(store, key)["version_no"]                           # 사슬이 세운 판(검토 · 쟁점 끝)
    with factories.routes_store(store):
        made = routes.post_report(key, routes.ReportBody(refresh_summaries=False), ident=factories.ident(OWNER))
        job = routes.post_report(key, routes.ReportBody(refresh_summaries=True), ident=factories.ident(OWNER))
    assert made["version_no"] == chained + int(made["created"]) and job["job_id"]
    assert store.query_one("SELECT mode FROM rr_jobs WHERE id = ?", (job["job_id"],))["mode"] == "synth"
    report = synth.report_source(store, key)
    first = routes.report_payload(key, owner_sub=OWNER, part="full")
    pages, page = [first], first
    while "next_page" in page:
        page = routes.report_payload(key, owner_sub=OWNER, part="full", page=page["next_page"], version=first["version"])
        pages.append(page)
    joined = "\n".join(t for p in pages for b in synth.BLOCKS for t in p["page"]["blocks"][b])
    assert joined == synth.render_report_md(report, part="full")
    whole = routes.report_payload(key, owner_sub=OWNER, format="json")
    assert whole["pages"] == report["pages"] and whole["level_label"] == report["level_label"]
    with pytest.raises(AppError) as moved:
        routes.report_payload(key, owner_sub=OWNER, version=first["version"] + 5)
    assert (moved.value.http_status, moved.value.code) == (409, "report_version_moved")


def test_new_paths_hide_another_owners_target(store):
    """남의 과제 — 새 REST 경로(쟁점 · 보고서 · 완결)는 404, MCP 새 읽기 도구는 not_visible 이다."""
    key = _ledger(store, run_issues=False)
    synth.assemble_report(store, key, trigger="manual")
    for call in (lambda: routes.issues_payload(key, owner_sub=OTHER), lambda: routes.report_payload(key, owner_sub=OTHER),
                 lambda: routes.closure_payload(key, owner_sub=OTHER)):
        with pytest.raises(AppError) as hidden:
            call()
        assert hidden.value.http_status == 404


def test_issue_panels_carry_their_kind_and_issue_in_the_panel_list(store):
    """패널 목록에 kind·issue_id 가 있고 kind 로 거른다 — 쟁점 패널 재제출은 MCP 에서 issue_panel_web_only 다."""
    key = _ledger(store)
    panels = routes.panels_payload(key, owner_sub=OWNER)["panels"]
    assert panels and {p["kind"] for p in panels} == {"issue"} and all(p["issue_id"] for p in panels)
    assert routes.panels_payload(key, owner_sub=OWNER, kind="coverage")["panels"] == []
    assert routes.panel_kind(panels[0]["id"]) == "issue"


# ---------------------------------------------------------------- 어휘 쪽
def test_the_taxonomy_comes_in_parts_under_the_wire_limit_with_the_mech_owner_table():
    """risk_taxonomy — 한 번에 와이어 25,000자 안이다(전부 한 번이면 3만 자를 넘는다). index 는 메커니즘 밖의 축과 배정표 머리
    (review_status), mechanism·mech_owners 는 행 쪽이고 이으면 전부다."""
    from app import taxonomy

    index = srv.risk_taxonomy()
    assert srv._wire_chars(index) <= srv.MCP_RESULT_CHARS and "mechanism" not in index["axes"]
    assert index["mech_owners"]["review_status"] in ("draft", "approved") and index["mechanism_count"] >= 52
    for part, total in (("mechanism", len(taxonomy.load_taxonomy()["axes"]["mechanism"])),
                        ("mech_owners", len(taxonomy.mech_owners()))):
        rows, offset = [], 0
        while True:
            page = srv.risk_taxonomy(part=part, offset=offset)
            assert srv._wire_chars(page) <= srv.MCP_RESULT_CHARS
            rows += page["rows"]
            if "next_offset" not in page:
                break
            offset = page["next_offset"]
        assert len(rows) == total
    owners = srv.risk_taxonomy(part="mech_owners")["rows"][0]
    assert set(owners) >= {"code", "owners", "related"}
    assert "error" in srv.risk_taxonomy(part="nope")
