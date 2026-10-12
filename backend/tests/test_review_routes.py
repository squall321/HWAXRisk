# 카드 대조 검토 REST(재설계 M2 S12) — 진행판 review 칸·셀·전문가·보고서·검토 잡 만들기의 응답 칸을 못 박고(웹 화면 세션의 계약), 원장은 검토 루프가 가짜 엔진으로 만든 것이다
"""입력은 생산자다 — 대상·단위는 합성 쌍 → 실제 캡처·diff → 단위 빌드, 검토 잡은 REST 라우트(`POST /targets/{key}/jobs`
mode='reviews'), 셀·판정·호출·보고서는 가짜 엔진을 꽂은 검토 루프(S8)와 마감(S9·S10)이 쓴다(tests/synth/review_rig.py).
진행판의 품질 칸은 운영처럼 루프의 품질 훅(review_quality.progress_hook)이 60초마다 넣은 값을 읽는다.

아래 칸 집합은 웹 화면(다른 세션)이 읽는 이름이다. 바꾸면 그쪽과 같이 바꾼다.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app import expert_report, review_quality, review_runner, routes
from app.errors import AppError
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

OWNER = rig.OWNER
SEAL = rig.SEAL
EDITOR = "editor@example.com"
VIEWER = "viewer@example.com"
OTHER = "other@example.com"

# ---------------------------------------------------------------- 응답 칸(스냅샷)
PANEL_COVERAGE_KEYS = {"target_key", "job", "roster_size", "by_domain", "by_status", "strong", "unseated_n", "level",
                       "close_level", "flow", "units"}                      # S12 전 진행판 칸 — 그대로다(D-24)
REVIEW_KEYS = {"units", "cells", "experts", "cards", "quality", "order", "job"}
REVIEW_CELLS_KEYS = {"total", "by_state", "by_basis", "in_scope", "out_of_scope_pending", "failed_open"}
REVIEW_EXPERTS_KEYS = {"total", "by_state"}
ORDER_KEYS = {"order", "agent_key", "domain", "rank_in_domain", "tier", "deferred", "input_gaps", "state", "cards_total",
              "checkable_n"}
JOB_KEYS = {"id", "mode", "state", "hold_code", "hold_until", "hold_n", "error", "credential_email", "scope", "phase",
            "progress", "waiting", "signal"}
JOB_PROGRESS_KEYS = {"packs", "experts", "cells", "calls", "breaker", "server"}
WORKER_KEYS = {"agent_key", "purpose", "unit_id", "call_kind", "variant", "deck_id", "started_at", "last_frame_at",
               "last_event_at", "last_step", "frame_idle_s", "event_idle_s"}
QUALITY_KEYS = {"job_id", "computed_at", "title", "text", "policy_version", "ledger_hash", "out_of_bounds", "unchecked"}
CARDS_KEYS = {"denominator", "lines", "residual", "experts_without_pack", "cells_without_pack", "invariant"}
CELLS_PAGE_KEYS = {"target_key", "total", "limit", "offset", "rows"}       # + next_offset(남았을 때)
CELL_ROW_KEYS = [
    "target_key", "unit_id", "agent_key", "owner_sub", "domain", "unit_seq", "state", "route", "route_forced", "basis",
    "run_id", "heartbeat_at", "priority", "tries", "charged", "infra_streak", "not_before", "error_code", "error_class",
    "error", "knob", "credential_kind", "model", "llm_calls", "tokens_in", "tokens_out", "elapsed_ms", "truncated",
    "rows_expected", "rows_missing", "stamp", "soft_over", "cards_expected", "cards_judged", "n_fail", "n_warning", "n_ok",
    "n_na", "n_undetermined", "n_disputed", "n_flipped", "n_offcard", "offcard_state", "offcard_capped", "quote_ok",
    "quote_n", "refs_ok", "refs_n", "bg_full_n", "bg_title_only_n", "unit_hash", "pack_hash", "input_hash", "prompt_rev",
    "verify_rev", "status_source", "decided_by", "decided_at", "decide_note", "reopened_n", "started_at", "finished_at",
    "created_at", "updated_at"]
CELL_DETAIL_KEYS = {"target_key", "unit_id", "agent_key", "cell", "verdicts", "calls"}
CELL_JSON_COLUMNS = {"route_json", "extras_json", "mechs_json", "handoffs_json", "sample_json"}   # 셀 하나에만 — 값으로 편다
EXPERT_ROW_KEYS = [
    "target_key", "agent_key", "owner_sub", "domain", "rank_in_domain", "tier", "review_order", "review_id", "state",
    "claimed_at", "run_id", "not_before", "pack_hash", "pack_status", "pack_error", "pack_attempts", "pack_frozen_at",
    "card_basis", "limits_rev", "sweep_state", "cells_total", "report_hash", "report_bytes", "revision", "opinion_id",
    "findings_n", "coverage_status", "model", "prompt_rev", "norm_rev", "verify_rev", "error", "finalized_at", "created_at",
    "updated_at", "cards", "cells"]
PACK_COUNT_KEYS = {"cards_total", "checkable_n", "background_n", "unrenderable_n"}
REPORT_META_KEYS = {"target_key", "agent_key", "state", "version", "report_hash", "finalized_at", "coverage_status",
                    "opinion_id", "review_id", "state_why"}
REPORT_PAGE_KEYS = REPORT_META_KEYS | {"format", "part", "unit_id", "pages_total", "page_no", "page"}   # + next_page
PAGE_KEYS = {"page_no", "kind", "title", "blocks"}
REVIEW_JOB_KEYS = {"job_id", "mode", "cells_total", "cells_in_scope", "experts_in_scope", "units", "calls_estimate",
                   "credential"}                                            # + credential_note(미리 알릴 것이 있을 때)


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    monkeypatch.setattr(review_runner, "QUALITY_HOOK", review_quality.progress_hook)    # main 의 lifespan 이 꽂는 그대로
    return risk_store


def _rid(alias: str) -> str:
    return next(c["record_id"] for c in fre.load("pack_ok.json")["cards"] if c["alias"] == alias)


def _reviewed(store) -> tuple[str, str, FakeReviewEngine]:
    """카드 대조 대상 하나에 REST 로 세운 검토 잡(카드 전문가 둘)을 가짜 엔진으로 끝까지 — K01 은 260자 인용의 FAIL 이다."""
    key = rig.target(store)
    rig.pat(store)
    job = routes.create_job(key, routes.JobBody(mode="reviews", scope={"agents": [SEAL, "mech-syn-0"]}, consent=True),
                            ident=factories.ident(OWNER))
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {_rid("K01"): ("yes", "FAIL")}
    fake.long_quote = {"K01"}
    rig.Rig(store, fake).finish(job["job_id"])
    assert rig.state(store, job["job_id"]) == "completed"
    return key, job["job_id"], fake


def _project_id(store, key: str) -> str:
    return store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]


def _refused(fn, *args, **kwargs) -> AppError:
    with pytest.raises(AppError) as exc:
        fn(*args, **kwargs)
    return exc.value


# ---------------------------------------------------------------- 진행판 review 칸
def test_a_panels_target_gains_only_a_null_review(store):
    """D-24 — 셀 원장이 없는 패널 방식 대상의 진행판은 S12 전의 칸 그대로에 review: null 하나만 더해진다."""
    synth = factories.make_diff_target(store, 3)
    coverage = routes.coverage_payload(synth.target_key, owner_sub=OWNER)
    assert set(coverage) == PANEL_COVERAGE_KEYS | {"review"} and coverage["review"] is None
    assert coverage["flow"] == "panels"


def test_a_cells_target_shows_the_review_order_before_any_job(store):
    """카드 대조 대상은 검토 잡 전에도 review 칸을 낸다 — 셀 0 · 잡 없음 · 카드 폭포·품질 없음, 검토 순서는 로스터 전원(영역 · 영역 안
    순위 · tier · 입력 결손)이고 묶음을 얼리기 전이라 카드 수는 None 이다(파일럿 9명을 사람이 고른다 — #24)."""
    key = rig.target(store)
    review = routes.coverage_payload(key, owner_sub=OWNER)["review"]
    assert set(review) == REVIEW_KEYS
    assert set(review["cells"]) == REVIEW_CELLS_KEYS and set(review["experts"]) == REVIEW_EXPERTS_KEYS
    assert (review["units"], review["cells"]["total"], review["experts"]["total"]) == (5, 0, 0)
    assert (review["job"], review["cards"], review["quality"]) == (None, None, None)
    assert all(set(row) == ORDER_KEYS for row in review["order"])
    assert [(r["agent_key"], r["domain"], r["rank_in_domain"], r["tier"]) for r in review["order"]] == [
        (SEAL, "mech", 1, "A"), (rig.BACKGROUND_ONLY, "sim", 1, "A"), ("xd-syn-0", "xd", 1, "A"),
        ("mech-syn-0", "mech", 2, "C"), (rig.ZERO_CARDS, "sim", 2, "C"), ("xd-syn-1", "xd", 2, "C")]
    assert {(r["state"], r["cards_total"], r["checkable_n"], tuple(r["input_gaps"])) for r in review["order"]} == {
        (None, None, None, ())}


def test_after_a_job_the_review_block_reads_the_progress_board_without_counting_the_ledger_again(store, monkeypatch):
    """검토 잡 뒤의 review 칸 — 잡 한 줄(보류 열·단계·진행판·기다림, 끝난 잡은 signal None), 카드 폭포와 품질 요약은 루프가 진행판에
    넣은 값이고, 검토 순서에 머리 상태와 얼린 묶음의 카드 수가 실린다. 진행판을 읽는 동안 품질 수치를 다시 세지 않는다(#16)."""
    key, job_id, _fake = _reviewed(store)
    monkeypatch.setattr(review_quality, "compute", lambda *a, **k: pytest.fail("진행판이 품질 수치를 다시 셌다"))
    review = routes.coverage_payload(key, owner_sub=OWNER)["review"]
    job = review["job"]
    assert set(job) == JOB_KEYS and set(job["progress"]) == JOB_PROGRESS_KEYS
    assert (job["id"], job["mode"], job["state"], job["phase"], job["signal"]) == (job_id, "reviews", "completed",
                                                                                  "completed", None)
    assert (job["hold_code"], job["hold_until"], job["hold_n"], job["error"], job["waiting"]) == (None, None, 0, None, None)
    assert job["scope"] == {"agents": [SEAL, "mech-syn-0"]} and job["credential_email"] == OWNER
    assert set(review["quality"]) == QUALITY_KEYS and review["quality"]["job_id"] == job_id
    board = json.loads(rig.job_row(store, job_id)["progress_json"])["quality"]
    assert review["quality"]["text"] == board["text"] and review["cards"] == board["json"]["cards"]
    assert set(review["cards"]) == CARDS_KEYS and review["cards"]["invariant"]["holds"] is True
    assert (review["cells"]["total"], review["cells"]["by_state"]["reviewed"], review["cells"]["out_of_scope_pending"]) == (
        30, 10, 20)
    assert review["cells"]["in_scope"]["job_id"] == job_id
    seal = next(r for r in review["order"] if r["agent_key"] == SEAL)
    assert (seal["state"], seal["cards_total"], seal["checkable_n"]) == ("ready", 10, 6)
    assert {(r["state"], r["cards_total"]) for r in review["order"] if r["agent_key"] not in (SEAL, "mech-syn-0")} == {
        ("planned", None)}


def test_a_running_review_job_carries_each_workers_last_signal(store, monkeypatch):
    """도는 검토 잡 — signal.workers 는 도는 호출마다의 마지막 신호이고 *_idle_s 는 그 시각에서 지금까지의 초다(서버 시계)."""
    import dataclasses
    import threading

    from app import config

    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_concurrency=1))
    key = rig.target(store)
    rig.pat(store)
    job_id = routes.create_job(key, routes.JobBody(mode="reviews", scope={"agents": [SEAL]}, consent=True),
                               ident=factories.ident(OWNER))["job_id"]
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    gate = threading.Event()
    fake.hold_runs = {2: gate}
    r = rig.Rig(store, fake)
    r.tick()
    r.tick(wait=False)
    rig.wait_for(lambda: fake.runs == 2)
    try:
        job = routes.coverage_payload(key, owner_sub=OWNER)["review"]["job"]
        assert job["state"] == "running" and job["signal"] is not None
        (worker,) = job["signal"]["workers"]
        assert set(worker) == WORKER_KEYS and worker["agent_key"] == SEAL and worker["call_kind"] == "verdict"
        assert worker["frame_idle_s"] is None or worker["frame_idle_s"] >= 0
    finally:
        gate.set()
        r.loop.join(30)
    r.finish(job_id)


# ---------------------------------------------------------------- 셀
def test_the_cells_list_is_the_grid_in_review_order_with_s1_columns_filters_and_paging(store):
    """GET /targets/{key}/cells — 격자 전부(로스터 6 × 단위 5)를 검토 순서 → 단위 순번으로, 행 열은 S1 이름 그대로(JSON 열·선점 없음).
    agent_key·unit_id·domain·state 로 거르고 limit·offset·next_offset 으로 나눠 받으며 나눠 받은 것을 이으면 한 번에 받은 것과 같다."""
    key, job_id, _fake = _reviewed(store)
    ident = factories.ident(OWNER)
    full = routes.get_cells(key, ident=ident)
    assert set(full) == CELLS_PAGE_KEYS and (full["total"], full["limit"], full["offset"]) == (30, 500, 0)
    assert all(list(row) == CELL_ROW_KEYS for row in full["rows"])
    order = [r["agent_key"] for r in routes.coverage_payload(key, owner_sub=OWNER)["review"]["order"]]
    assert [r["agent_key"] for r in full["rows"]] == [a for a in order for _ in range(5)]
    assert [r["unit_seq"] for r in full["rows"][:5]] == [1, 2, 3, 4, 5]
    rows, offset = [], 0
    while True:
        page = routes.get_cells(key, limit=7, offset=offset, ident=ident)
        rows += page["rows"]
        if "next_offset" not in page:
            break
        offset = page["next_offset"]
    assert rows == full["rows"]
    assert routes.get_cells(key, agent_key=SEAL, ident=ident)["total"] == 5
    reviewed = routes.get_cells(key, state="reviewed", ident=ident)
    assert reviewed["total"] == 10 and {r["run_id"] for r in reviewed["rows"]} == {job_id}
    assert routes.get_cells(key, domain="mech", ident=ident)["total"] == 10
    first = full["rows"][0]["unit_id"]
    assert routes.get_cells(key, unit_id=first, ident=ident)["total"] == 6
    assert routes.get_cells(key, limit=10_000, ident=ident)["limit"] == routes.CELL_LIST_LIMIT_MAX
    assert _refused(routes.get_cells, key, state="done", ident=ident).http_status == 422


def test_one_cell_has_every_verdict_row_and_its_calls_without_result_bodies(store):
    """GET /targets/{key}/cells/{unit_id}/{agent_key} — 셀 행 + 판정 행 전부(변형별) + 호출 목록. 카드 인용은 보고서·반출과 같이 판정당
    200자이고 원래 길이를 cq_chars 에 적으며(사용자 결정 1), 호출에는 result 본문이 없다. JSON 열은 값으로 편다."""
    key, _job_id, _fake = _reviewed(store)
    unit = routes.get_cells(key, agent_key=SEAL, ident=factories.ident(OWNER))["rows"][0]["unit_id"]
    out = routes.get_cell(key, unit, SEAL, ident=factories.ident(OWNER))
    assert set(out) == CELL_DETAIL_KEYS
    assert set(out["cell"]) == set(CELL_ROW_KEYS) | CELL_JSON_COLUMNS
    assert isinstance(out["cell"]["extras_json"], dict) and "lease_owner" not in out["cell"]
    count = store.query_one("SELECT COUNT(*) AS n FROM rr_card_verdicts WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                            (key, unit, SEAL))["n"]
    assert len(out["verdicts"]) == count and {v["variant"] for v in out["verdicts"]} >= {"fwd", "rev", "solo"}
    k01 = [v for v in out["verdicts"] if v["alias"] == "K01"]
    assert k01 and {(len(v["cq"]), v["cq_chars"]) for v in k01} == {(200, 260)}
    stored = store.query_one("SELECT cq FROM rr_card_verdicts WHERE target_key = ? AND unit_id = ? AND agent_key = ?"
                             " AND alias = 'K01' AND variant = 'fwd'", (key, unit, SEAL))["cq"]
    assert len(stored) == 260                                               # 박스 안 원문은 그대로다
    calls = store.query_one("SELECT COUNT(*) AS n FROM rr_review_calls WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                            (key, unit, SEAL))["n"]
    assert len(out["calls"]) == calls and all("result_gz" not in c for c in out["calls"])
    assert all(isinstance(c["quality_json"], dict) and isinstance(c["cards_json"], list) for c in out["calls"])
    assert _refused(routes.get_cell, key, unit, "nobody", ident=factories.ident(OWNER)).http_status == 404


# ---------------------------------------------------------------- 전문가
def test_the_experts_list_is_review_order_with_pack_card_counts_and_cell_states(store):
    """GET /targets/{key}/experts — 머리 행(보고서 본문·계획·훑기·요약 글·선점 없음) + 얼린 묶음의 카드 수(묶음 전이면 None) + 셀
    상태별 수. domain·state 로 거른다."""
    key, _job_id, _fake = _reviewed(store)
    ident = factories.ident(OWNER)
    out = routes.get_experts(key, ident=ident)
    assert set(out) == {"target_key", "total", "experts"} and out["total"] == 6
    assert all(list(row) == EXPERT_ROW_KEYS for row in out["experts"])
    assert [r["review_order"] for r in out["experts"]] == [1, 2, 3, 4, 5, 6]
    seal = out["experts"][0]
    assert seal["agent_key"] == SEAL and seal["state"] == "ready" and seal["report_hash"]
    assert seal["cards"] == {"cards_total": 10, "checkable_n": 6, "background_n": 4, "unrenderable_n": 1}
    assert set(seal["cards"]) == PACK_COUNT_KEYS
    assert seal["cells"] == {"total": 5, "by_state": {"pending": 0, "running": 0, "reviewed": 5, "na_irrelevant": 0,
                                                       "no_input": 0, "failed": 0, "skipped": 0}}
    assert {(r["state"], r["cards"]) for r in out["experts"] if r["agent_key"] not in (SEAL, "mech-syn-0")} == {
        ("planned", None)}
    assert [r["agent_key"] for r in routes.get_experts(key, state="ready", ident=ident)["experts"]] == [SEAL, "mech-syn-0"]
    assert routes.get_experts(key, domain="xd", ident=ident)["total"] == 2
    assert _refused(routes.get_experts, key, state="done", ident=ident).http_status == 422


# ---------------------------------------------------------------- 보고서
def test_the_report_comes_in_pages_that_join_to_the_full_markdown_and_as_the_frozen_json(store):
    """GET /targets/{key}/experts/{agent_key}/report — md 쪽(기본 part=summary · page 1, next_page 로 이어 받는다)을 다 이으면 그 part
    의 마크다운 전체다(자르지 않는다). format=json 은 마감 때 얼린 보고서 그대로다. 단위 하나로 좁히고, 판이 바뀌면 409 다."""
    key, _job_id, _fake = _reviewed(store)
    ident = factories.ident(OWNER)
    report = expert_report.load_report(store, key, SEAL)
    first = routes.get_expert_report(key, SEAL, ident=ident)
    assert set(first) == REPORT_PAGE_KEYS | {"next_page"} and set(first["page"]) == PAGE_KEYS
    assert (first["format"], first["part"], first["page_no"], first["version"], first["state"]) == ("md", "summary", 1, 1,
                                                                                                 "ready")
    for part in expert_report.PARTS:
        for chars in (expert_report.PAGE_CHARS, 400):
            texts, page = [], 1
            while page:
                out = routes.expert_report_payload(key, SEAL, owner_sub=OWNER, part=part, page=page, page_chars=chars)
                texts += [t for block in expert_report.BLOCKS for t in out["page"]["blocks"][block]]
                page = out.get("next_page")
            assert "\n".join(texts) == expert_report.render_report_md(report, part=part), (part, chars)
    assert out["pages_total"] > 3 and set(out) == REPORT_PAGE_KEYS                     # 마지막 쪽에는 next_page 가 없다
    unit = report["scope"]["units"][0]["unit_id"]
    texts, page = [], 1
    while page:
        one = routes.get_expert_report(key, SEAL, part="cards", unit_id=unit, page=page, ident=ident)
        texts += [t for block in expert_report.BLOCKS for t in one["page"]["blocks"][block]]
        page = one.get("next_page")
    narrowed = "\n".join(texts)
    assert one["unit_id"] == unit and narrowed == expert_report.render_report_md(report, part="cards", unit_id=unit)
    assert narrowed != expert_report.render_report_md(report, part="cards")          # 다른 단위의 점검표 줄이 빠졌다
    as_json = routes.get_expert_report(key, SEAL, format="json", ident=ident)
    assert set(as_json) == REPORT_META_KEYS | {"format", "report"} and as_json["report"] == report
    assert routes.get_expert_report(key, SEAL, version=1, ident=ident)["version"] == 1
    moved = _refused(routes.get_expert_report, key, SEAL, version=0, ident=ident)
    assert (moved.code, moved.http_status, moved.detail) == ("report_version_moved", 409, {"version": 1, "asked": 0})
    for kwargs in ({"page": 0}, {"page": 99}, {"format": "pdf"}, {"format": "json", "part": "full"}, {"part": "nope"}):
        assert _refused(routes.get_expert_report, key, SEAL, ident=ident, **kwargs).http_status == 422, kwargs
    assert _refused(routes.get_expert_report, key, SEAL, unit_id="u-000000000000", ident=ident).http_status == 404
    assert _refused(routes.get_expert_report, key, rig.ZERO_CARDS, ident=ident).http_status == 404     # 마감 전


def test_the_review_reads_are_owner_only_and_hide_other_targets(store):
    """읽기는 지금 관례(`_target_row(target_key, owner_sub)`) — 남의 대상은 넷 모두 404 다."""
    key, _job_id, _fake = _reviewed(store)
    other = factories.ident(OTHER)
    unit = routes.get_cells(key, ident=factories.ident(OWNER))["rows"][0]["unit_id"]
    for fn, args in ((routes.get_cells, (key,)), (routes.get_cell, (key, unit, SEAL)), (routes.get_experts, (key,)),
                     (routes.get_expert_report, (key, SEAL)), (routes.get_coverage, (key,))):
        assert _refused(fn, *args, ident=other).http_status == 404, fn.__name__


# ---------------------------------------------------------------- 검토 잡 만들기
def test_the_job_body_keeps_panel_and_review_fields_apart():
    """mode=panels 는 tier 가 필요하고 scope 를 받지 않는다. mode=reviews 는 tier·modifiers·concurrency 를 받지 않는다(범위는 scope,
    동시 수는 박스 손잡이) — 준 칸을 조용히 버리지 않는다(m-11 — tier 는 reviews 에서 생략한다)."""
    assert routes.JobBody(tier="A").mode == "panels"
    assert routes.JobBody(mode="reviews").tier is None
    assert routes.JobBody(mode="reviews", modifiers=[], scope={"agents": [SEAL]}).scope == {"agents": [SEAL]}
    for bad in ({}, {"tier": "A", "scope": {}}, {"mode": "reviews", "tier": "A"}, {"mode": "reviews", "concurrency": 1},
                {"mode": "reviews", "modifiers": ["voi"]}, {"mode": "cells"}):
        with pytest.raises(ValidationError):
            routes.JobBody(**bad)


def test_an_editor_makes_a_review_job_through_the_jobs_route_and_it_is_audited(store):
    """POST /targets/{key}/jobs mode='reviews' — editor 가 만들고(viewer 403 · 남 404) 응답은 create_review_job 의 것이다. 잡 행의
    owner_sub 는 대상 소유자, 동의 입구는 CONSENT_SOURCES(Bearer → api), rr_audit(scope='job', action='job.create') 한 행이 남는다."""
    key = rig.target(store)
    rig.pat(store)
    project_id = _project_id(store, key)
    routes.put_members(project_id, routes.MembersBody(members=[routes.MemberItem(email=EDITOR, role="editor"),
                                                               routes.MemberItem(email=VIEWER, role="viewer")]),
                       ident=factories.ident(OWNER))
    body = routes.JobBody(mode="reviews", scope={"domains": ["xd"]}, consent=True)
    assert _refused(routes.create_job, key, body, ident=factories.ident(VIEWER)).http_status == 403
    assert _refused(routes.create_job, key, body, ident=factories.ident(OTHER)).http_status == 404
    out = routes.create_job(key, body, ident=factories.ident(EDITOR))
    assert set(out) == REVIEW_JOB_KEYS and (out["mode"], out["cells_in_scope"], out["experts_in_scope"]) == ("reviews", 10, 2)
    row = rig.job_row(store, out["job_id"])
    params = json.loads(row["params_json"])
    assert (row["owner_sub"], row["mode"], params["requester"], params["consent_source"]) == (OWNER, "reviews", EDITOR, "api")
    audit = [dict(r) for r in store.query("SELECT actor, channel, scope, subject_id, project_id, action, after_json FROM rr_audit"
                                          " WHERE action = 'job.create'")]
    assert len(audit) == 1 and audit[0]["actor"] == EDITOR
    assert (audit[0]["channel"], audit[0]["scope"], audit[0]["subject_id"], audit[0]["project_id"]) == (
        "rest", "job", out["job_id"], project_id)
    after = json.loads(audit[0]["after_json"])
    assert after == {"mode": "reviews", "target_key": key, "scope": {"domains": ["xd"]}, "cells_in_scope": 10,
                     "experts_in_scope": 2, "calls_estimate": out["calls_estimate"], "consent": True, "consent_source": "api"}
    again = _refused(routes.create_job, key, body, ident=factories.ident(OWNER))
    assert (again.code, again.http_status) == ("review_job_exists", 409)
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_audit WHERE action = 'job.create'")["n"] == 1
