# 카드 0장 전문가의 긴 문서 검색(재설계 M3 C3-12 · M3.md 4.4.4 · #38 · #39) — 검색어 · search_only · 못 물은 검색의 인프라 다시 내기와 상한
"""카드 0장 전문가(`rig.ZERO_CARDS`)의 카드 밖 호출만 `extra.search` 를 싣는다. 가짜 엔진의 `search_states` 가 meta.search.state 를
차례로 낸다(예제 result_offcard_search_* 의 모양)."""
from __future__ import annotations

import json

import pytest

from app import expert_report, review_cells, review_runner, units
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

ZERO = rig.ZERO_CARDS


@pytest.fixture()
def store(tmp_path, monkeypatch, risk_store):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_review_filter="off")
    return risk_store


def _run(store, states: list[str], *, agents=(ZERO,)) -> tuple[str, str, FakeReviewEngine, str]:
    key = rig.target(store)
    first = units.load_units(store, key)[0]["unit_id"]
    job_id = rig.job(store, key, scope={"agents": list(agents), "unit_ids": [first]})
    fake = FakeReviewEngine(rig.packs())
    fake.search_states = list(states)
    rig.Rig(store, fake).finish(job_id)
    return key, first, fake, job_id


def _offcards(fake: FakeReviewEngine, agent: str) -> list[dict]:
    return [c["body"] for c in fake.calls("run") if c["body"]["kind"] == "offcard" and c["body"]["expert"]["key"] == agent]


def _cell(store, key: str, unit_id: str, agent: str = ZERO) -> dict:
    return dict(store.query_one("SELECT * FROM rr_review_cells WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                                (key, unit_id, agent)))


def test_queries_are_the_unit_title_and_its_change_lines_within_600_chars():
    """검색어는 코드가 짓는다 — 단위 제목, 변경 줄 몸통을 600자까지 ' · ' 로 이은 것(같으면 하나 · 비면 단위 id)."""
    unit = {"unit_id": "u-1", "title": "부품 A — 부품 1 · 계면 2", "lines": [{"text": "두께  0.8→0.6"}, {"text": "x" * 700}]}
    assert review_runner.search_queries(unit) == ["부품 A — 부품 1 · 계면 2", "두께 0.8→0.6"]
    assert review_runner.search_queries({"unit_id": "u-2", "title": "", "lines": [{"text": "y" * 900}]}) == ["y" * 600]
    assert review_runner.search_queries({"unit_id": "u-3", "title": "", "lines": []}) == ["u-3"]


def test_only_the_zero_card_expert_asks_and_an_excerpt_makes_the_cell_search_only(store):
    """카드 0장 전문가의 카드 밖 호출만 extra.search 를 싣는다(카드가 있는 전문가 · 배경뿐 전문가는 싣지 않는다 — A5). 발췌를 실은 답이면
    셀의 basis 는 search_only 이고 보고서 단위 줄에 '긴 문서 발췌 n건', 롤업은 카드 0장(no_cards)이다."""
    key, unit_id, fake, job_id = _run(store, ["ok"], agents=(ZERO, rig.SEAL, rig.BACKGROUND_ONLY))
    assert rig.state(store, job_id) == "completed"
    zero = _offcards(fake, ZERO)
    payload = units.review_payload(store, key, unit_id, ZERO)
    assert zero and all(b["extra"]["search"] == {"queries": review_runner.search_queries(payload)} for b in zero)
    assert all("search" not in b["extra"] for a in (rig.SEAL, rig.BACKGROUND_ONLY) for b in _offcards(fake, a))
    cell = _cell(store, key, unit_id)
    assert cell["basis"] == "search_only"
    assert json.loads(cell["extras_json"])["offcard"]["search"] == {
        "state": "ok", "hits_n": 1, "used_n": 1, "search_failed": False, "queries": review_runner.search_queries(payload)}
    assert review_cells.expert_tally(store, key, ZERO)["role_only_only"] is True
    assert review_cells.closure_cells(store, key)["no_cards"] == {
        "experts": 1, "cells": 1, "by_basis": {"role_only": 0, "search_only": 1, "search_failed": 0}}
    report = expert_report.render_report_md(expert_report.build_report(store, key, ZERO))
    assert "긴 문서 발췌 1건" in report


def test_an_empty_scope_answer_is_role_only_and_is_not_retried(store):
    """묶인 자료가 0건(empty_scope)이면 물어본 것이다 — 다시 내지 않고 role_only 로 받는다."""
    key, unit_id, fake, _job = _run(store, ["empty_scope"])
    assert len(_offcards(fake, ZERO)) == 1 and _cell(store, key, unit_id)["basis"] == "role_only"
    assert json.loads(_cell(store, key, unit_id)["extras_json"])["offcard"]["search"]["search_failed"] is False


def test_a_failed_search_is_reissued_as_infra_three_times_then_taken_as_role_only_with_a_mark(store):
    """못 물은 검색(state failed)은 같은 호출을 인프라로(차감 없이 · 차단기 밖) SEARCH_RETRIES 번 다시 낸다. 그 뒤에도 못 물으면 답을
    role_only 로 받고 셀에 search_failed 를 적는다 — 셀은 막히지 않고 잡은 completed, 보고서 단위 줄에 그 표지가 선다."""
    key, unit_id, fake, job_id = _run(store, ["failed"])
    assert rig.state(store, job_id) == "completed"
    assert len(_offcards(fake, ZERO)) == review_runner.SEARCH_RETRIES + 1
    rows = [dict(r) for r in store.query("SELECT state, outcome_class, error_code, request_hash FROM rr_review_calls"
                                        " WHERE target_key = ? AND agent_key = ? AND kind = 'offcard' ORDER BY started_at",
                                        (key, ZERO))]
    assert [(r["state"], r["error_code"]) for r in rows] == [("infra_fail", "search_failed")] * 3 + [("ok", None)]
    assert len({r["request_hash"] for r in rows}) == 1                   # 같은 호출을 다시 냈다
    cell = _cell(store, key, unit_id)
    assert (cell["state"], cell["basis"], cell["charged"]) == ("reviewed", "role_only", 0)
    assert json.loads(cell["extras_json"])["offcard"]["search"]["search_failed"] is True
    assert rig.progress(store, job_id)["breaker"]["trips"] == 0
    assert review_cells.closure_cells(store, key)["no_cards"]["by_basis"] == {"role_only": 1, "search_only": 0,
                                                                              "search_failed": 1}
    report = expert_report.render_report_md(expert_report.build_report(store, key, ZERO))
    assert "긴 문서 검색 못 함(search_failed" in report


def test_a_search_that_recovers_on_a_retry_is_not_marked_failed(store):
    """두 번 못 물은 뒤 세 번째에 찾았으면 search_only 이고 search_failed 표지가 없다(표지는 받은 답에 검색이 없을 때만)."""
    key, unit_id, fake, _job = _run(store, ["failed", "failed", "ok"])
    cell = _cell(store, key, unit_id)
    assert len(_offcards(fake, ZERO)) == 3 and cell["basis"] == "search_only"
    assert json.loads(cell["extras_json"])["offcard"]["search"]["search_failed"] is False
