# 실패 셀 처분(재설계 M3 C3-4) — 다시·force 다시·넘김 REST · Claude 입구(risk_job_action) · 처분이 세우는 잡 · 원장 롤업 표(m3-cells 3.9)
"""실패 셀은 손으로 만들지 않는다 — 가짜 엔진의 결함 스위치(그 셀의 run 이 늘 no_rows · 카드 묶음 502 여섯 번)로 검토 루프가 만든다
(tests/synth/review_rig.py). 처분은 REST 함수(`routes.post_cells_retry` · `post_cells_skip`)와 MCP 도구로 부른다.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from app import closure, config, expert_report, identity, planner, review_cells, routes
from app.errors import AppError
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.test_review_mcp import _as_bearer, _call, _project_with_source

OWNER = rig.OWNER
SEAL = rig.SEAL
PEER = "xd-syn-1"
NO_ROWS = {"code": "no_rows", "message": "판정 행이 하나도 없다(가짜)", "infra": False, "retryable": False}
ME = factories.ident(OWNER)


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _cells(store, key: str, agent: str) -> dict[str, dict]:
    return {r["unit_id"]: dict(r) for r in store.query(
        "SELECT * FROM rr_review_cells WHERE target_key = ? AND agent_key = ? ORDER BY unit_seq", (key, agent))}


def _head(store, key: str, agent: str) -> dict:
    return dict(store.query_one("SELECT * FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?", (key, agent)))


def _seat(store, key: str, agent: str) -> tuple[str, str | None]:
    row = store.query_one("SELECT status, reason FROM rr_coverage WHERE target_key = ? AND agent_key = ?", (key, agent))
    return row["status"], row["reason"]


def _audits(store, action: str) -> list[dict]:
    return [dict(r) for r in store.query("SELECT actor, actor_verified, channel, scope, subject_id, after_json, reason"
                                         " FROM rr_audit WHERE action = ? ORDER BY at", (action,))]


def _pack_error(name: str) -> tuple[int, dict]:
    sample = fre.load("pack_errors.json")[name]
    return sample["status"], sample["body"]


def _refused(fn, *args, **kwargs) -> AppError:
    """거절(AppError)을 돌려준다 — 거절하지 않았으면 단언 실패다(변이 검사가 '죽음' 으로 세는 실패의 모양)."""
    try:
        fn(*args, **kwargs)
    except AppError as exc:
        return exc
    raise AssertionError(f"{getattr(fn, '__name__', fn)} 가 거절하지 않았다")


def _failed_target(store):
    """SEAL · PEER 를 범위로 돈 잡 — PEER 의 첫 단위만 셀의 run 이 늘 no_rows 라 failed(no_rows)로 끝난다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL, PEER]})
    unit_ids = list(_cells(store, key, SEAL))
    fake = FakeReviewEngine(rig.packs())
    fake.error_cells = {(PEER, unit_ids[0]): NO_ROWS}
    r = rig.Rig(store, fake)
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed"
    return key, job_id, unit_ids, fake, r


# ---------------------------------------------------------------- 다시
def test_retry_reopens_only_the_failed_cell_and_the_job_it_makes_asks_the_engine_again(store):
    """다시 — 기본은 failed 만(나머지는 not_failed 로 세고 손대지 않는다). 시도 수·차감을 비우고 reopened_n + 1, route_forced
    human_retry, 사람 표기 열. 살아 있는 잡이 없으면 그 셀의 (전문가, 단위)로 검토 잡을 세운다(created). 다시 연 셀은 앞 시도의 호출
    답을 다시 쓰지 않고 엔진을 다시 부른다 — 결함이 걷히면 reviewed 이고 그 전문가가 다시 마감된다."""
    key, job_id, unit_ids, fake, r = _failed_target(store)
    failed = _cells(store, key, PEER)[unit_ids[0]]
    assert (failed["state"], failed["error_code"], failed["charged"]) == ("failed", "no_rows", 2)
    assert "risk_job_action" in rig.job_row(store, job_id)["error"]                      # 잡 error 가 처분 길을 말한다
    assert (_head(store, key, PEER)["state"], _seat(store, key, PEER)) == ("partial", ("done_weak", "partial:1"))
    revision = _head(store, key, PEER)["revision"]

    out = routes.post_cells_retry(key, routes.CellsRetryBody(filter={"job_id": job_id}), ident=ME)
    assert (out["matched"], out["retried"], out["not_failed"], out["keys"], out["keys_total"], out["experts"]) == (
        2 * len(unit_ids), 1, 2 * len(unit_ids) - 1, [[unit_ids[0], PEER]], 1, 1)
    assert out["changed"] is True and out["job"]["action"] == "created" and out["audit_id"]
    cell = _cells(store, key, PEER)[unit_ids[0]]
    assert {k: cell[k] for k in ("state", "tries", "charged", "infra_streak", "error_code", "reopened_n", "route_forced",
                                 "status_source", "decided_by", "decide_note", "run_id")} == {
        "state": "pending", "tries": 0, "charged": 0, "infra_streak": 0, "error_code": None, "reopened_n": 1,
        "route_forced": review_cells.HUMAN_RETRY, "status_source": "human", "decided_by": OWNER, "decide_note": None,
        "run_id": out["job"]["job_id"]}
    assert _head(store, key, PEER)["state"] == "planned"
    audit = _audits(store, "cells.retry")
    assert len(audit) == 1 and (audit[0]["scope"], audit[0]["subject_id"], audit[0]["channel"]) == ("coverage", key, "rest")
    after = json.loads(audit[0]["after_json"])
    assert (after["n"], after["keys"], after["selector"], after["job"]["action"]) == (
        1, [[unit_ids[0], PEER]], {"filter": {"job_id": job_id}}, "created")

    fake.error_cells = {}
    before = len([b for b in fake.calls("run") if (b["body"].get("unit") or {}).get("unit_id") == unit_ids[0]
                  and b["body"]["expert"]["key"] == PEER])
    r.finish(out["job"]["job_id"])
    assert rig.state(store, out["job"]["job_id"]) == "completed"
    assert _cells(store, key, PEER)[unit_ids[0]]["state"] == "reviewed"
    after_n = len([b for b in fake.calls("run") if (b["body"].get("unit") or {}).get("unit_id") == unit_ids[0]
                   and b["body"]["expert"]["key"] == PEER])
    assert after_n > before                                                           # 캐시가 아니라 엔진을 다시 불렀다
    head = _head(store, key, PEER)
    assert head["state"] == "ready" and head["revision"] == revision + 1 and _seat(store, key, PEER) == ("done", None)
    assert review_cells.review_invariants(store, key) == []
    again = routes.post_cells_retry(key, routes.CellsRetryBody(filter={"job_id": job_id}), ident=ME)
    assert (again["changed"], again["retried"], again["job"]) == (False, 0, {"action": "none"})
    assert len(_audits(store, "cells.retry")) == 1                                   # 바꾼 것이 없으면 감사도 없다


def test_a_retried_cell_never_replays_the_answers_of_its_first_run(store):
    """다시 연 셀은 시도 수가 0 으로 돌아가지만 요청 열쇠에 다시 연 횟수가 들어 앞 실행의 같은 시도 답(엔진이 카드 하나를 빼먹은 답 —
    호출은 ok 라 원장에 남아 있다)을 다시 쓰지 않는다. 엔진이 고쳐진 뒤 다시 돌리면 reviewed 다(앞 답을 다시 썼다면 또 failed)."""
    key = rig.target(store)
    unit_id = review_cells.active_unit_ids(store, key)[0]
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]})
    fake = FakeReviewEngine(rig.packs())
    fake.skip_cards = {"K02"}
    r = rig.Rig(store, fake)
    r.finish(job_id)
    cell = _cells(store, key, SEAL)[unit_id]
    assert (cell["state"], cell["error_code"]) == ("failed", "cards_unjudged")
    fake.skip_cards = set()
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[unit_id, SEAL]]), ident=ME)
    r.finish(out["job"]["job_id"])
    assert _cells(store, key, SEAL)[unit_id]["state"] == "reviewed"


def test_force_retry_reopens_reviewed_cells_with_a_reason_and_runs_them_on_the_new_revision(store):
    """force — reviewed 셀도 다시 연다(사유 필수 · 판정 행을 같은 트랜잭션에서 지운다). 엔진 판이 오른 뒤 끝난 M2 파일럿 셀을 새 판으로
    다시 보는 길이다(m3-engine-ops A12) — 머리의 prompt_rev 가 새 판이고 보고서 판이 오른다."""
    key, job_id, unit_ids, fake, r = _failed_target(store)
    target_cell = [[unit_ids[1], SEAL]]
    refused = _refused(routes.post_cells_retry, key, routes.CellsRetryBody(cells=target_cell, force=True), ident=ME)
    assert refused.code == "reason_required"
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_card_verdicts WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                           (key, unit_ids[1], SEAL))["n"] > 0
    plain = routes.post_cells_retry(key, routes.CellsRetryBody(cells=target_cell, reason="force 없는 다시"), ident=ME)
    assert (plain["retried"], plain["not_failed"], plain["changed"]) == (0, 1, False)    # reviewed 는 force 없이는 그대로
    revision = _head(store, key, SEAL)["revision"]
    fake.base_limits["prompt_rev"] = {**fake.base_limits["prompt_rev"], "verdict": "cr-verdict-2"}
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=target_cell, force=True, reason="새 판으로 다시 본다"),
                                  ident=ME)
    assert (out["retried"], out["job"]["action"]) == (1, "created")
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_card_verdicts WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                           (key, unit_ids[1], SEAL))["n"] == 0
    assert _cells(store, key, SEAL)[unit_ids[1]]["decide_note"] == "새 판으로 다시 본다"
    r.finish(out["job"]["job_id"])
    assert _cells(store, key, SEAL)[unit_ids[1]]["state"] == "reviewed"
    head = _head(store, key, SEAL)
    assert "verdict=cr-verdict-2" in head["prompt_rev"] and head["revision"] == revision + 1


def test_a_retry_that_needs_consent_changes_nothing(store, monkeypatch):
    """처분이 세울 잡이 동의 문턱을 넘는데 consent 가 없으면 아무것도 바꾸기 전에 422 consent_required 다 — 셀·머리·감사·잡 그대로."""
    key, job_id, unit_ids, _fake, _r = _failed_target(store)
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_consent_calls=0))
    refused = _refused(routes.post_cells_retry, key, routes.CellsRetryBody(filter={"job_id": job_id}), ident=ME)
    assert refused.code == "consent_required"
    assert _cells(store, key, PEER)[unit_ids[0]]["state"] == "failed" and _head(store, key, PEER)["state"] == "partial"
    assert _audits(store, "cells.retry") == [] and store.query_one("SELECT COUNT(*) AS n FROM rr_jobs")["n"] == 1
    out = routes.post_cells_retry(key, routes.CellsRetryBody(filter={"job_id": job_id}, consent=True), ident=ME)
    assert out["job"]["action"] == "created"
    stay = routes.post_cells_retry(key, routes.CellsRetryBody(filter={"job_id": job_id}, start=False), ident=ME)
    assert stay["changed"] is False                                                    # 이미 다시 열렸다


def test_a_retried_cell_a_live_job_does_not_cover_waits_for_the_next_job(store):
    """살아 있는 검토 잡이 그 셀을 덮지 않으면 다음 잡을 기다린다(waiting — 잡을 새로 세우지 않는다). 다음 잡이 그 셀을 범위로 집는다."""
    key, job_id, unit_ids, fake, r = _failed_target(store)
    other = rig.job(store, key, scope={"agents": [SEAL]})
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[unit_ids[0], PEER]]), ident=ME)
    assert (out["job"]["action"], out["job"]["job_id"], out["job"]["waiting"]) == ("waiting", other, 1)
    assert _cells(store, key, PEER)[unit_ids[0]]["run_id"] == job_id
    routes.job_action(other, "cancel", ident=ME)
    covering = rig.job(store, key, scope={"agents": [PEER]})
    assert _cells(store, key, PEER)[unit_ids[0]]["run_id"] == covering
    fake.error_cells = {}
    r.finish(covering)
    assert _cells(store, key, PEER)[unit_ids[0]]["state"] == "reviewed"
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_jobs")["n"] == 3


def test_a_retry_covered_by_a_live_job_is_adopted(store):
    key, job_id, unit_ids, fake, r = _failed_target(store)
    live = rig.job(store, key, scope={"agents": [PEER, SEAL]})
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[unit_ids[0], PEER]]), ident=ME)
    assert (out["job"]["action"], out["job"]["job_id"], out["job"]["adopted"]) == ("adopted", live, 1)
    assert _cells(store, key, PEER)[unit_ids[0]]["run_id"] == live and _head(store, key, PEER)["run_id"] == live
    fake.error_cells = {}
    r.finish(live)
    assert _cells(store, key, PEER)[unit_ids[0]]["state"] == "reviewed"


# ---------------------------------------------------------------- 넘김
def test_skip_needs_a_reason_and_the_expert_closes_again_with_the_skip_in_the_report(store):
    """넘김 — failed 만 skipped(사유 4~300자 필수). 살아 있는 잡이 없으면 마감 잡(돌 셀 0)이 서서 그 전문가를 다시 마감하고, 보고서
    '보지 못한 것' 에 '넘김 — 사유' 가 남으며 원장은 done_weak(partial:1)다."""
    key, job_id, unit_ids, fake, r = _failed_target(store)
    for reason in ("", "짧다"):
        assert _refused(routes.post_cells_skip, key, routes.CellsSkipBody(filter={"job_id": job_id}, reason=reason),
                        ident=ME).code == "reason_required"
    assert closure.cached(store, key) is None
    out = routes.post_cells_skip(key, routes.CellsSkipBody(filter={"job_id": job_id}, reason="입력이 와야 본다"), ident=ME)
    assert (out["skipped"], out["job"]["action"], out["job"]["calls_estimate"]["high"]) == (1, "created", 0)
    # 처분은 완결 판정 캐시를 새로 쓴다 — 넘긴 셀이 셈과 잔여에 들어 있다(M3 병합 메모 3)
    cached = closure.cached(store, key)
    assert cached["status_counts"]["skipped"] == 1 and "skipped" in [q["item"] for q in cached["qualifiers"]]
    cell = _cells(store, key, PEER)[unit_ids[0]]
    assert (cell["state"], cell["decided_by"], cell["decide_note"]) == ("skipped", OWNER, "입력이 와야 본다")
    calls = len(fake.calls("run"))
    r.finish(out["job"]["job_id"])
    assert len(fake.calls("run")) == calls                                            # 마감 잡은 엔진을 부르지 않는다
    assert _head(store, key, PEER)["state"] == "ready" and _seat(store, key, PEER) == ("done_weak", "partial:1")
    report = expert_report.load_report(store, key, PEER)
    assert [u["why"] for u in report["scope"]["unseen"]] == [{"code": "skipped", "text": "입력이 와야 본다", "by": OWNER}]
    assert routes.coverage_payload(key, owner_sub=OWNER)["review"]["dispositions"] == {"retried": 0, "skipped": 1}
    assert len(_audits(store, "cells.skip")) == 1


def test_skipping_a_pack_blocked_experts_cells_finalizes_it_without_a_pack_and_closes_the_seat_skipped(store):
    """카드 묶음을 끝내 못 받은 전문가(blocked — 셀이 전부 failed(pack_unavailable))의 셀을 넘기면 마감 잡이 묶음 없이 그 전문가를
    마감한다(묶음을 다시 받지 않는다). reviewed 0 · 넘김만 남은 전문가의 원장은 skipped(cells_skipped:n) 다(m3-cells 3.9 의 7번)."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL, PEER]})
    fake = FakeReviewEngine(rig.packs())
    fake.pack_errors = {PEER: _pack_error("card_fetch_failed")}
    r = rig.Rig(store, fake)
    r.finish(job_id, step=2000)
    n = len(_cells(store, key, PEER))
    assert _head(store, key, PEER)["state"] == "blocked"
    assert {c["state"] for c in _cells(store, key, PEER).values()} == {"failed"}
    out = routes.post_cells_skip(key, routes.CellsSkipBody(cells=[[u, PEER] for u in _cells(store, key, PEER)],
                                                           reason="이 전문가의 카드가 아직 없다"), ident=ME)
    assert (out["skipped"], out["job"]["action"]) == (n, "created")
    assert _head(store, key, PEER)["state"] == "planned"
    packs = len(fake.calls("pack"))
    r.finish(out["job"]["job_id"])
    assert rig.state(store, out["job"]["job_id"]) == "completed" and len(fake.calls("pack")) == packs
    assert _seat(store, key, PEER) == ("skipped", f"cells_skipped:{n}")
    assert _head(store, key, PEER)["state"] == "ready"
    assert {u["why"]["code"] for u in expert_report.load_report(store, key, PEER)["scope"]["unseen"]} == {"skipped"}


def test_retrying_pack_failed_cells_fetches_the_pack_again(store):
    """묶음 실패로 진 셀의 다시는 묶음부터 받는다 — 막힌 머리가 planned 로 돌아가고 묶음 시도 수·백오프가 빈다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL, PEER]})       # 범위 전원이 묶음 실패면 잡 보류(aidh) — 둘을 둔다
    fake = FakeReviewEngine(rig.packs())
    fake.pack_errors = {PEER: _pack_error("card_fetch_failed")}
    r = rig.Rig(store, fake)
    r.finish(job_id, step=2000)
    assert _head(store, key, PEER)["state"] == "blocked"
    out = routes.post_cells_retry(key, routes.CellsRetryBody(filter={"agent_key": PEER}), ident=ME)
    head = _head(store, key, PEER)
    assert (head["state"], head["pack_attempts"], head["not_before"]) == ("planned", 0, None)
    fake.pack_errors = {}
    packs = len(fake.calls("pack"))
    r.finish(out["job"]["job_id"])
    assert len(fake.calls("pack")) == packs + 1
    assert {c["state"] for c in _cells(store, key, PEER).values()} == {"reviewed"}


# ---------------------------------------------------------------- 고르기 · 권한
def test_the_selector_is_one_of_cells_or_filter_and_never_narrows_silently(store):
    key, job_id, unit_ids, _fake, _r = _failed_target(store)
    for body in (routes.CellsRetryBody(), routes.CellsRetryBody(cells=[[unit_ids[0], PEER]], filter={"job_id": job_id}),
                 routes.CellsRetryBody(filter={"team": "x"}), routes.CellsRetryBody(filter={"state": "lost"}),
                 routes.CellsRetryBody(cells=[[unit_ids[0]]]), routes.CellsRetryBody(cells=["u-1"]),
                 routes.CellsRetryBody(cells=[["u-000000000000", PEER]])):
        refused = _refused(routes.post_cells_retry, key, body, ident=ME)
        assert (refused.code, refused.http_status) == ("cells_selector_invalid", 422), body
    assert _cells(store, key, PEER)[unit_ids[0]]["state"] == "failed"
    stranger = factories.ident("stranger@example.com")
    assert _refused(routes.post_cells_retry, key, routes.CellsRetryBody(filter={"job_id": job_id}),
                    ident=stranger).http_status in (403, 404)


# ---------------------------------------------------------------- Claude 입구
def test_risk_job_action_retries_and_skips_the_jobs_failed_cells_for_a_delegated_identity_only(store, monkeypatch):
    """새 도구 없이 risk_job_action 의 retry_failed·skip_failed 다. 그 잡이 찍은 셀이 기본 집합이고 filter 로 좁힌다. 위임 단언 없는
    Bearer 는 delegation_required, 감사 행은 channel mcp · actor_verified 0 이다."""
    key, job_id, unit_ids, _fake, _r = _failed_target(store)
    _as_bearer(monkeypatch, OWNER)
    assert _call("risk_job_action", job_id=job_id, action="retry_failed")["error"] == "delegation_required"
    factories.act_as_delegate(monkeypatch, OWNER)
    narrowed = _call("risk_job_action", job_id=job_id, action="retry_failed", filter={"agent_key": SEAL})
    assert (narrowed["changed"], narrowed["retried"]) == (False, 0)
    assert _call("risk_job_action", job_id=job_id, action="skip_failed")["error"] == "reason_required"
    assert _call("risk_job_action", job_id=job_id, action="pause", reason="x" * 10)["error"] == "E100"
    out = _call("risk_job_action", job_id=job_id, action="skip_failed", reason="Claude 에서 넘긴다")
    assert (out["skipped"], out["keys"]) == (1, [[unit_ids[0], PEER]])
    audit = _audits(store, "cells.skip")[0]
    assert (audit["channel"], audit["actor_verified"], audit["reason"]) == ("mcp", 0, "Claude 에서 넘긴다")
    assert _call("risk_job_action", job_id="no-such-job", action="retry_failed")["error"] == "not_visible"   # 남의 잡과 같은 답(C3-13)


def test_the_guide_offers_retry_and_skip_after_a_job_ends_with_failed_cells(store, monkeypatch):
    key, job_id, _unit_ids, _fake, _r = _failed_target(store)
    factories.act_as_delegate(monkeypatch, OWNER)
    steps = _call("risk_next_step", project_id=_project_with_source(store, key))["next"]
    actions = [(s["tool"], s["args"].get("action")) for s in steps if s["tool"] == "risk_job_action"]
    assert actions == [("risk_job_action", "retry_failed"), ("risk_job_action", "skip_failed")]


# ---------------------------------------------------------------- 원장 롤업(m3-cells 3.9 — 처음 맞는 줄)
def _tally(**kw) -> dict:
    base = {"open": 0, "reviewed": 0, "failed": 0, "skipped": 0, "no_input": 0, "filtered": 0, "verified": False,
            "role_only_only": False, "noinput_only": False}
    return {**base, **kw}


@pytest.mark.parametrize(("tally", "expected"), [
    (_tally(open=1, reviewed=3, verified=True), (None, "open_cells")),                                    # 1
    (_tally(reviewed=2, noinput_only=True), ("done_weak", "input_gap:ecad_absent")),                      # 2
    (_tally(reviewed=2, noinput_only=True, failed=1, skipped=1), ("done_weak", "input_gap:ecad_absent;partial:2")),
    (_tally(reviewed=2, failed=1, verified=True), ("done_weak", "partial:1")),                           # 3
    (_tally(reviewed=2, skipped=2, verified=True), ("done_weak", "partial:2")),
    (_tally(reviewed=2, verified=True), ("done", None)),                                                  # 4
    (_tally(reviewed=2, role_only_only=True), ("done_weak", "no_cards")),                                 # 5
    (_tally(reviewed=2), ("done_weak", "no_verified_cite")),
    (_tally(failed=3, skipped=1, no_input=1), (None, "failed_open:3")),                                   # 6
    (_tally(skipped=2, no_input=1, filtered=1), ("skipped", "cells_skipped:2")),                          # 7
    (_tally(no_input=4, filtered=1), ("abstain", "no_input:ecad_absent")),                                # 8
    (_tally(filtered=5), ("abstain", "filtered:5")),                                                      # 9
    (_tally(), (None, "nothing_reviewed")),
])
def test_the_review_rollup_table(tally, expected):
    assert planner.review_rollup(tally) == expected
    status = expected[0]
    assert status is None or status in planner.REVIEW_CLOSE_STATUSES


def test_identity_source_of_the_audit_follows_the_entry(store):
    """REST 처분의 감사 행은 그 입구의 channel 이다 — 쿠키(웹)면 web, Bearer 면 rest."""
    key, job_id, _unit_ids, _fake, _r = _failed_target(store)
    web = identity.Identity(email=OWNER, display_name="합성", role="user", organization="qa", anonymous=False, source="cookie")
    routes.post_cells_skip(key, routes.CellsSkipBody(filter={"job_id": job_id}, reason="웹 화면에서 넘긴다"), ident=web)
    assert [(a["channel"], a["actor_verified"]) for a in _audits(store, "cells.skip")] == [("web", 1)]
