# 실패 셀 처분(재설계 M3 C3-4) — 다시·force 다시·넘김 REST · Claude 입구(risk_job_action) · 처분이 세우는 잡 · 원장 롤업 표(m3-cells 3.9)
"""실패 셀은 손으로 만들지 않는다 — 가짜 엔진의 결함 스위치(그 셀의 run 이 늘 no_rows · 카드 묶음 502 여섯 번)로 검토 루프가 만든다
(tests/synth/review_rig.py). 처분은 REST 함수(`routes.post_cells_retry` · `post_cells_skip`)와 MCP 도구로 부른다.
"""
from __future__ import annotations

import dataclasses
import inspect
import json

import pytest

import app.mcp_server as srv
from app import closure, config, expert_report, identity, planner, review_cells, review_runner, routes
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


def test_a_live_job_that_does_not_cover_a_waiting_retry_never_finalizes_that_expert(store):
    """반대 검토 3차 MEDIUM 2 · 3 · D-47 — 잡의 몫은 범위로 찍힌 머리와 그 잡에 묶인 셀의 전문가다. 다시 연 셀이 살아 있는 잡의 범위
    밖이라 다음 잡을 기다리면(waiting) 그 잡은 그 전문가를 마감하지 않는다 — 그 잡에 묶인 열린 셀이 없다는 것만으로 남의 전문가를
    마감하면 기다리는 셀을 둔 채 머리가 partial 로 닫힌다."""
    key, job_id, unit_ids, fake, r = _failed_target(store)
    other = rig.job(store, key, scope={"agents": [SEAL]})
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[unit_ids[0], PEER]]), ident=ME)
    assert out["job"]["action"] == "waiting" and _head(store, key, PEER)["state"] == "planned"
    r.finish(other)
    assert rig.state(store, other) == "completed"
    assert (_head(store, key, PEER)["state"], _cells(store, key, PEER)[unit_ids[0]]["run_id"]) == ("planned", job_id)


def test_a_retry_covered_by_a_live_job_is_adopted(store):
    key, job_id, unit_ids, fake, r = _failed_target(store)
    live = rig.job(store, key, scope={"agents": [PEER, SEAL]})
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[unit_ids[0], PEER]]), ident=ME)
    assert (out["job"]["action"], out["job"]["job_id"], out["job"]["adopted"]) == ("adopted", live, 1)
    assert _cells(store, key, PEER)[unit_ids[0]]["run_id"] == live and _head(store, key, PEER)["run_id"] == live
    fake.error_cells = {}
    r.finish(live)
    assert _cells(store, key, PEER)[unit_ids[0]]["state"] == "reviewed"


@pytest.mark.parametrize("floor,hold", [(30, None), (2, "consent_extra")])
def test_a_retry_spilled_into_a_live_job_counts_against_its_reopen_allowance(store, monkeypatch, floor, hold):
    """반대 검토 4차 MEDIUM 2 · D-49 — 사람의 다시가 살아 있는 잡에 얹힌 셀(그 잡을 만들 때 failed 라 그 잡의 추정 밖이다)은 다시 연 셀의
    몫에 든다 — 진행판 reopened_extra 가 그 셀을 세고, 여유를 넘으면 그 잡이 consent_extra 로 멈춘다(응답 job.hold). 종전에는 그 잡의
    추정 · 동의 어디에도 셈해지지 않았다."""
    monkeypatch.setattr(review_runner, "REOPEN_FLOOR_CALLS", floor, raising=False)
    key, job_id, unit_ids, fake, r = _failed_target(store)
    live = rig.job(store, key, scope={"agents": [PEER, SEAL]})
    out = routes.post_cells_retry(key, routes.CellsRetryBody(cells=[[unit_ids[0], PEER]]), ident=ME)
    assert (out["job"]["action"], out["job"].get("hold")) == ("adopted", hold)
    row = store.query_one("SELECT id, state, hold_code, hold_until, hold_n, error, credential_email, params_json, progress_json"
                          " FROM rr_jobs WHERE id = ?", (live,))
    extra = routes._review_job_payload(dict(row))["progress"].get("reopened_extra") or {}
    assert (extra.get("unconsented"), extra.get("hold")) == ({"cells": 1, "calls_est": 5.25}, hold)
    assert rig.state(store, live) == ("paused" if hold else "queued")


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
    assert [u["why"] for u in report["scope"]["unseen"]] == [{"code": "skipped", "text": "입력이 와야 본다", "by": OWNER,
                                                              "hits": 0, "hits_by": {"card": 0, "offcard": 0, "noinput": 0}}]
    assert routes.coverage_payload(key, owner_sub=OWNER)["review"]["dispositions"] == {"retried": 0, "skipped": 1}
    assert len(_audits(store, "cells.skip")) == 1


@pytest.mark.parametrize("live", [False, True])
def test_a_skipped_cells_lines_say_skip_and_its_reason_never_out_of_scope(store, live):
    """반대 검토 3차 LOW 7 · D-47 — 넘긴 셀의 보고서 줄(본 범위의 단위 줄 · 보지 못한 것)은 '넘김 — «사유»' 다. 넘김을 마감하는 잡(새로
    선 마감 잡이든 살아 있던 잡이든)의 범위와 그 셀의 잡 결속이 달라도 '이 검토 잡의 범위 밖' 이라 적지 않는다 — 종전에는 넘긴 셀마다
    단위 줄이 '넘김 · 이 검토 잡의 범위 밖', 보지 못한 것이 '넘김 «skipped» «사유»' 였다."""
    key, job_id, unit_ids, fake, r = _failed_target(store)
    running = rig.job(store, key, scope={"agents": [SEAL]}) if live else None
    out = routes.post_cells_skip(key, routes.CellsSkipBody(cells=[[unit_ids[0], PEER]], reason="입력이 와야 본다"), ident=ME)
    assert out["job"]["action"] == ("adopted" if live else "created")
    r.finish(running or out["job"]["job_id"])
    assert _head(store, key, PEER)["state"] == "ready"                      # 넘김을 실은 보고서로 다시 마감됐다
    md = expert_report.render_report_md(expert_report.load_report(store, key, PEER))
    # 본 범위 절(단위 줄 · 보지 못한 것) — 단위별 분석 · 메커니즘 절의 '넘김 — 일부만 판정' 표지(4차 MEDIUM 1)는 따로 본다
    lines = [ln for ln in _md_section(md, "본 범위").splitlines() if ln.startswith("- 단위 ") and "넘김" in ln]
    assert len(lines) == 2 and all(ln.endswith(" — 넘김 — «입력이 와야 본다»") for ln in lines)
    assert "범위 밖" not in "".join(lines)


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


def _stance(store, key: str, agent: str) -> tuple[str, str, str] | None:
    """(rr_seat_opinions.final_stance, 의견 json 의 final_stance, turns[0].stance) — 의견 행이 없으면 None."""
    row = store.query_one("SELECT final_stance, opinion_json FROM rr_seat_opinions WHERE target_key = ? AND agent_key = ?",
                          (key, agent))
    if row is None:
        return None
    opinion = json.loads(row["opinion_json"])
    return row["final_stance"], opinion["final_stance"], opinion["turns"][0]["stance"]


def _md_section(md: str, head: str) -> str:
    return md.split(f"## {head}")[1].split("\n## ")[0]


def test_an_expert_with_only_skipped_cells_abstains_and_its_skipped_units_never_read_as_clean(store):
    """반대 검토 4차 MEDIUM 1 · D-49(재현 P1A) — 카드 묶음을 끝내 못 받은 전문가의 셀(전부 failed)을 넘기고 마감하면 검토한 셀이 없으니
    입장은 abstain 이다(X1-15 — 검토한 셀이 없으면 abstain · 기권은 검토한 셀로만 정한다). 종전에는 넘긴 셀까지 판정한 셀로 읽어
    agree 였다. 원장(skipped · cells_skipped)과 요약(검토 0 · 넘김 n)이 그 입장과 같은 말을 한다. 단위별 분석 · 메커니즘 절은 넘긴 단위를
    숨기지 않고 '넘김 — 일부만 판정' 으로 보인다 — 'FAIL 0장 · … · 걸림 없음 0장' 으로 읽히지 않는다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL, PEER]})
    fake = FakeReviewEngine(rig.packs())
    fake.pack_errors = {PEER: _pack_error("card_fetch_failed")}
    r = rig.Rig(store, fake)
    r.finish(job_id, step=2000)
    n = len(_cells(store, key, PEER))
    out = routes.post_cells_skip(key, routes.CellsSkipBody(cells=[[u, PEER] for u in _cells(store, key, PEER)],
                                                           reason="이 전문가의 카드가 아직 없다"), ident=ME)
    r.finish(out["job"]["job_id"])
    assert _stance(store, key, PEER) == ("abstain", "abstain", "abstain")
    assert _seat(store, key, PEER) == ("skipped", f"cells_skipped:{n}")
    summary = _head(store, key, PEER)["summary_md"]
    assert "가운데 검토 0(" in summary and f" · 미완 0 · 대기 0 · 넘김 {n}(일부만 판정)." in summary
    report = expert_report.load_report(store, key, PEER)
    assert [u.get("partial_cell") for u in report["by_unit"]] == [True] * n
    assert [m.get("partial_cell") for m in report["mechanisms"]] == [True] * n
    md = expert_report.render_report_md(report)
    by_unit = _md_section(md, "단위별 분석")
    assert by_unit.count(" — 넘김 — 일부만 판정\n") == n and "#### 걸림 없음 · 해당 없음" not in by_unit
    assert _md_section(md, "따져 본 메커니즘(카드 밖 호출)").count(" — 넘김 — 일부만 판정 · 적힌 것 없음") == n


def test_skipping_the_only_failed_cell_never_turns_an_abstain_into_agree(store):
    """반대 검토 4차 MEDIUM 1 · D-49(재현 P1B) — 범위가 한 단위뿐인 전문가의 셀이 no_rows 로 실패하면(판정 행 0) 입장은 abstain 이고,
    그 셀을 넘겨도 abstain 이다 — 종전에는 넘김 하나로 agree 로 뒤집혔다(넘긴 셀은 입장을 동의로 움직이지 못한다)."""
    from app import units

    key = rig.target(store)
    unit_ids = [u["unit_id"] for u in units.load_units(store, key)]
    job_id = rig.job(store, key, scope={"agents": [PEER], "unit_ids": unit_ids[:1]})
    fake = FakeReviewEngine(rig.packs())
    fake.error_cells = {(PEER, unit_ids[0]): NO_ROWS}
    r = rig.Rig(store, fake)
    r.finish(job_id)
    assert _cells(store, key, PEER)[unit_ids[0]]["state"] == "failed"
    assert _stance(store, key, PEER) == ("abstain",) * 3
    out = routes.post_cells_skip(key, routes.CellsSkipBody(cells=[[unit_ids[0], PEER]], reason="엔진이 답을 못 낸다"), ident=ME)
    r.finish(out["job"]["job_id"])
    assert _head(store, key, PEER)["state"] == "partial" and _stance(store, key, PEER) == ("abstain",) * 3


@pytest.mark.parametrize("skipped,reviewed,before,after", [
    ("FAIL", "OK", "abstain", "oppose"),
    ("WARNING", "OK", "abstain", "conditional"),
    ("OK", "undetermined", "abstain", "abstain"),
])
def test_a_skipped_cells_candidates_only_move_a_reviewed_stance_toward_conditional_or_oppose(store, skipped, reviewed, before,
                                                                                                after):
    """반대 검토 4차 MEDIUM 1 · D-49 — 입장은 검토한 셀로 정하고(X1-15), 넘긴 셀의 걸림 후보는 그 입장을 조건부 · 반대 쪽으로만
    움직인다. ① 넘긴 셀만 있을 때(검토 0)는 걸림 후보가 있어도 기권이다 — 기권은 검토한 셀로만 정한다(그 걸림은 finding · 보고서
    '보지 못한 것' · 요약 줄로 남는다). ② 검토한 셀이 동의면 넘긴 셀의 FAIL 은 반대 · WARNING 은 조건부로 올린다. ③ 검토한 셀이 보류뿐이면
    (기권) 넘긴 셀의 걸림 없음은 동의로 바꾸지 못한다 — 종전에는 넘긴 셀의 OK 가 적용 판정에 들어 agree 였다."""
    from app import units

    key = rig.target(store)
    unit_ids = [u["unit_id"] for u in units.load_units(store, key)]
    records = [str(c["record_id"]) for c in fre.load("pack_ok.json")["cards"]]
    fake = FakeReviewEngine(rig.packs())
    fake.offcard_findings = 0
    fake.verdicts = {records[0]: ("yes", skipped)}
    fake.error_cells, fake.error_kinds = {(SEAL, unit_ids[0]): NO_ROWS}, {"offcard"}
    r = rig.Rig(store, fake)
    r.finish(rig.job(store, key, scope={"agents": [SEAL], "unit_ids": unit_ids[:1]}))
    assert _cells(store, key, SEAL)[unit_ids[0]]["state"] == "failed"
    out = routes.post_cells_skip(key, routes.CellsSkipBody(cells=[[unit_ids[0], SEAL]], reason="카드 밖 호출이 계속 실패"),
                                 ident=ME)
    r.finish(out["job"]["job_id"])
    assert _stance(store, key, SEAL) == (before,) * 3
    fake.error_cells = {}
    fake.verdicts = {rid: ("unknown", "undetermined") for rid in records} if reviewed == "undetermined" else {}
    r.finish(rig.job(store, key, scope={"agents": [SEAL], "unit_ids": unit_ids[1:2]}))
    assert _cells(store, key, SEAL)[unit_ids[1]]["state"] == "reviewed"
    assert _stance(store, key, SEAL) == (after,) * 3
    report = expert_report.load_report(store, key, SEAL)
    mine = [f for f in report["findings"] if f["unit_id"] == unit_ids[0]]
    assert [f["partial_cell"] for f in mine] == ([True] if skipped != "OK" else [])
    if mine:
        assert "· 넘긴 셀 — 일부만 판정" in _head(store, key, SEAL)["summary_md"]


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
@pytest.mark.parametrize("case", ["split", "unjudged_conflict"])
def test_a_skipped_cells_hits_are_exactly_what_its_report_carries(store, monkeypatch, case):
    """반대 검토 2차 MEDIUM 2 · D-46 — 넘긴 셀의 걸림 셈은 검토한 셀이면 보고서가 실을 것과 같다. ① 변형이 갈려 실효 undetermined 인
    카드(split)는 검토한 셀처럼 finding 후보다 — 종전 셈은 실효 FAIL · WARNING 만 보아 0 이라 점검표에도 finding 에도 없었다. ② 엔진이
    부딪침을 알린 행인데 두 번째 판정을 끝내 못 받은 카드는 갈림처럼 후보다('다툼 표지 — 두 번째 판정 못 함') — 종전에는 셈이 1 이라
    '점검표 · finding 에 남겼다' 고 말했지만 finding 은 0 이었다. 넘김 응답의 수와 보고서의 글이 실제로 실린 것과 같다."""
    from app import expert_report, units

    key = rig.target(store)
    unit_ids = [u["unit_id"] for u in units.load_units(store, key)]
    k01 = str(fre.load("pack_ok.json")["cards"][0]["record_id"])
    fake = FakeReviewEngine(rig.packs())
    if case == "split":                                  # fwd FAIL · rev OK · 단독 OK — 실효 OK 인데 걸린 변형이 있어 갈림
        fake.verdicts, fake.rev_verdicts, fake.solo_verdicts = {k01: ("yes", "FAIL")}, {k01: ("yes", "OK")}, {k01: ("yes", "OK")}
        fake.error_cells, fake.error_kinds = {(SEAL, unit_ids[0]): NO_ROWS}, {"offcard"}
    else:                                                # fwd 모름에 부딪침 표지 — 두 번째 판정(rev)이 끝내 실패
        monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_dual="flagged"))
        fake.verdicts = {k01: ("unknown", "undetermined")}
        fake.dup_conflict = {"K01"}
        fake.contested = {"K01": {"verdict": ["yes", "FAIL"], "why": "같은 카드의 다른 답", "attempt": 1, "raw": "FAILED?"}}
        fake.error_cells, fake.error_kinds = {(SEAL, unit_ids[0]): NO_ROWS}, {"verdict:rev"}
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": unit_ids[:1]})
    rig.Rig(store, fake).finish(job_id)
    assert _cells(store, key, SEAL)[unit_ids[0]]["state"] == "failed"
    out = routes.post_cells_skip(key, routes.CellsSkipBody(filter={"job_id": job_id}, reason="끝내 실패한 셀을 넘긴다"),
                                 ident=ME)
    assert (out["skipped"], out.get("hits"), (out.get("hits_by") or {}).get("card")) == (1, 1, 1)
    rig.Rig(store, fake).finish(out["job"]["job_id"])
    report = expert_report.load_report(store, key, SEAL)
    rows = [r for c in report["checklist"] for r in c["rows"] if r.get("unit_id") == unit_ids[0] and not r.get("missing")]
    held = [r for r in rows if r.get("finding_id")]
    assert len(held) == 1 and held[0].get("partial_cell")
    assert [f["unit_id"] for f in report["findings"]] == [unit_ids[0]]
    md = expert_report.render_report_md(report)
    assert "카드 판정 1건 — 점검표 · finding" in md
    if case == "unjudged_conflict":
        assert held[0].get("conflict_unjudged") and "다툼 표지 — 두 번째 판정 못 함" in md
        assert [u["unit_id"] for u in report["needs_info"]] == [unit_ids[0]]        # 그 카드의 필요한 정보 — 검토한 셀과 같은 자리


def test_a_skipped_cells_offcard_hit_becomes_a_finding_like_a_reviewed_cells(store):
    """반대 검토 3차 HIGH 1 · D-47 — 카드 밖 호출을 받은 뒤 정산에서 끝내 실패한 셀(엔진이 점검 카드 하나를 끝내 내지 않는다 —
    cards_unjudged)을 넘겨도 그 카드 밖 걸림은 검토한 셀처럼 finding 이고 카드 밖 절에 실린다(종전에는 넘긴 셀의 카드 밖 구성원을
    빼 걸림 0 · finding 0 이었다). 넘김 응답의 걸림 셈은 보고서의 구성원 함수가 실제로 낸 것이다 — 카드 밖 갈래가 저절로 선다."""
    from app import cardpack, expert_report, units

    key = rig.target(store)
    unit_ids = [u["unit_id"] for u in units.load_units(store, key)]
    fake = FakeReviewEngine(rig.packs())
    fake.offcard_findings = 1
    fake.skip_cards = {list(cardpack.view_of(fre.load("pack_ok.json")).checkable)[-1]}
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": unit_ids[:1]})
    rig.Rig(store, fake).finish(job_id)
    cell = _cells(store, key, SEAL)[unit_ids[0]]
    assert (cell["state"], cell["n_offcard"]) == ("failed", 1)
    out = routes.post_cells_skip(key, routes.CellsSkipBody(cells=[[unit_ids[0], SEAL]], reason="끝내 실패한 셀을 넘긴다"),
                                 ident=ME)
    assert (out.get("hits"), out.get("hits_by"), out.get("hits_basis")) == (1, {"card": 0, "offcard": 1, "noinput": 0},
                                                                            "members")
    rig.Rig(store, fake).finish(out["job"]["job_id"])
    report = expert_report.load_report(store, key, SEAL)
    mine = [f for f in report["findings"] if f["unit_id"] == unit_ids[0]]
    assert [(f["off_card"], f.get("partial_cell")) for f in mine] == [(True, True)]
    assert [r["unit_id"] for r in report["off_card"]] == [unit_ids[0]]
    assert "카드 밖 지적 1건 — 카드 밖 절 · finding" in expert_report.render_report_md(report)


def test_a_skip_whose_experts_pack_is_not_on_this_box_says_its_hits_are_unknown_never_zero(store):
    """반대 검토 4차 LOW 3 · D-49 — 그 전문가의 얼린 카드 묶음이 이 박스에 없으면(들여온 원장 — rr_card_packs 는 반출하지 않는다) 넘김
    응답은 걸림을 셀 수 없다. 걸림 수를 0 이라 하지 않고 모름(hits null · hits_basis pack_missing · 까닭 한 문장)이라 한다 — 종전에는
    0 이라 했는데, 마감이 묶음을 다시 받아 지은 보고서는 같은 셀에 걸림 1 · finding 1 을 실었다(D-46 — 응답과 보고서가 같아야 한다)."""
    from app import cardpack, units

    key = rig.target(store)
    unit_ids = [u["unit_id"] for u in units.load_units(store, key)]
    k01 = str(fre.load("pack_ok.json")["cards"][0]["record_id"])
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts, fake.rev_verdicts, fake.solo_verdicts = {k01: ("yes", "FAIL")}, {k01: ("yes", "OK")}, {k01: ("yes", "OK")}
    fake.error_cells, fake.error_kinds = {(SEAL, unit_ids[0]): NO_ROWS}, {"offcard"}
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": unit_ids[:1]})
    rig.Rig(store, fake).finish(job_id)
    assert _cells(store, key, SEAL)[unit_ids[0]]["state"] == "failed"
    store.execute("DELETE FROM rr_card_packs WHERE agent_key = ?", (SEAL,))       # 들여온 원장 — 이 박스에 얼린 묶음이 없다
    with cardpack._LRU_LOCK:
        cardpack._LRU.clear()
    out = routes.post_cells_skip(key, routes.CellsSkipBody(filter={"job_id": job_id}, reason="끝내 실패한 셀을 넘긴다"),
                                 ident=ME)
    assert (out["skipped"], out.get("hits"), out.get("hits_by"), out.get("hits_basis")) == (1, None, None, "pack_missing")
    assert SEAL in out.get("hits_note", "") and "0 이 아니다" in out.get("hits_note", "")
    rig.Rig(store, fake).finish(out["job"]["job_id"])
    report = expert_report.load_report(store, key, SEAL)
    (why,) = [u["why"] for u in report["scope"]["unseen"] if u["unit_id"] == unit_ids[0]]
    assert why["hits"] == 1 and sum(1 for f in report["findings"] if f["unit_id"] == unit_ids[0]) == 1


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


def test_risk_job_action_retry_carries_the_humans_consent_like_rest(store, monkeypatch):
    """반대 검토 MEDIUM 13(사용자 결정) — Claude 의 다시가 세울 잡이 동의 문턱을 넘으면 consent_required 인데 동의를 실을 칸이 없어
    길잡이가 내민 다시가 끝내 막혔다. risk_job_action 의 consent 는 REST 와 같은 뜻이다 — 없으면 아무것도 바꾸기 전에 거절, 있으면
    잡이 서고 그 잡에 동의(consent_source mcp)가 남는다. 도구 설명은 사람이 동의한 뒤에만 true 라고 말하고, 길잡이는 채워 주지 않는다."""
    key, job_id, unit_ids, _fake, _r = _failed_target(store)
    factories.act_as_delegate(monkeypatch, OWNER)
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_consent_calls=0))
    assert "consent" in inspect.signature(srv.risk_job_action).parameters
    assert "consent=true" in (srv.risk_job_action.__doc__ or "")
    assert _call("risk_job_action", job_id=job_id, action="retry_failed").get("error") == "consent_required"
    for action, extra in (("skip_failed", {"reason": "동의는 넘김의 칸이 아니다"}), ("pause", {})):
        assert _call("risk_job_action", job_id=job_id, action=action, consent=True, **extra).get("error") == "E100", action
    assert _cells(store, key, PEER)[unit_ids[0]]["state"] == "failed" and _audits(store, "cells.retry") == []
    out = _call("risk_job_action", job_id=job_id, action="retry_failed", consent=True)
    assert (out.get("retried"), (out.get("job") or {}).get("action")) == (1, "created"), out
    params = json.loads(rig.job_row(store, out["job"]["job_id"])["params_json"])
    assert (params["consent"], params["consent_source"]) == (True, "mcp")


def test_the_guide_offers_retry_and_skip_after_a_job_ends_with_failed_cells(store, monkeypatch):
    key, job_id, _unit_ids, _fake, _r = _failed_target(store)
    factories.act_as_delegate(monkeypatch, OWNER)
    steps = _call("risk_next_step", project_id=_project_with_source(store, key))["next"]
    actions = [(s["tool"], s["args"].get("action")) for s in steps if s["tool"] == "risk_job_action"]
    assert actions == [("risk_job_action", "retry_failed"), ("risk_job_action", "skip_failed")]
    retry = next(s for s in steps if s["tool"] == "risk_job_action" and s["args"]["action"] == "retry_failed")
    assert "consent" not in retry["args"] and "consent=true" in retry["why"]   # 동의는 사람이 — 길잡이는 채워 주지 않는다(MEDIUM 13)


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


def test_a_skipped_cell_keeps_its_settled_hits_in_the_report_and_findings(store):
    """반대 검토 MEDIUM 8(사용자 결정) — 판정은 받았는데 카드 밖 호출이 끝내 실패한 셀을 넘겨도 이미 정산된 걸림(실효 FAIL)은 버리지
    않는다 — 넘김 응답이 그 수(hits)를 말하고, 전문가 보고서 점검표에 '넘긴 셀 — 일부만 판정' 표지로, finding 으로 남는다."""
    from app import expert_report

    from app import units

    key = rig.target(store)
    unit_ids = [u["unit_id"] for u in units.load_units(store, key)]
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": unit_ids[:1]})
    fake = FakeReviewEngine(rig.packs())
    fail_record = str(fre.load("pack_ok.json")["cards"][0]["record_id"])
    fake.verdicts = {fail_record: ("yes", "FAIL")}
    fake.error_cells, fake.error_kinds = {(SEAL, unit_ids[0]): NO_ROWS}, {"offcard"}
    rig.Rig(store, fake).finish(job_id)
    cell = _cells(store, key, SEAL)[unit_ids[0]]
    assert cell["state"] == "failed" and cell["n_fail"] >= 1
    out = routes.post_cells_skip(key, routes.CellsSkipBody(filter={"job_id": job_id}, reason="카드 밖 호출이 계속 실패"),
                                 ident=ME)
    assert (out["skipped"], out["hits"]) == (1, 1)
    rig.Rig(store, fake).finish(out["job"]["job_id"])
    report = expert_report.load_report(store, key, SEAL)
    rows = [r for c in report["checklist"] for r in c["rows"] if r.get("unit_id") == unit_ids[0] and not r.get("missing")]
    assert rows and all(r.get("partial_cell") for r in rows)
    flagged = [r for r in rows if r["judgement"] == "FAIL"]
    assert len(flagged) == 1 and flagged[0]["finding_id"]
    assert any(f["unit_id"] == unit_ids[0] for f in report["findings"])
    assert "넘긴 셀 — 일부만 판정" in expert_report.render_report_md(report)
