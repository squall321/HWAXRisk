# 검토 루프(재설계 M2 · m2-wp3b S8) — 실제 단위·엔진 계약 예제 팩·가짜 엔진으로 전문가 세션·기다림·차단기·보류·재기동 이어 돌기를 본다
"""입력은 전부 생산자다 — 대상은 합성 쌍 → 실제 캡처·diff → 단위 빌드, 팩은 엔진 계약 예제에서 전문가만 바꾼 것, 원장 행은 루프가
쓴다(tests/synth/review_rig.py). 엔진은 실제 `PortalReviewEngine` 에 가짜 엔진의 MockTransport 를 꽂은 것이라 앱이 받는 예외·부류는
운영과 같은 길을 지난다. 시계는 손으로 민다.
"""
from __future__ import annotations

import dataclasses
import json
import threading

import pytest

from app import cardpack, config, planner, review_cells, review_ops, runner, units
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

OWNER = rig.OWNER
SEAL = rig.SEAL


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _cells(store, key: str, agent: str | None = None) -> list[dict]:
    sql = "SELECT * FROM rr_review_cells WHERE target_key = ?" + (" AND agent_key = ?" if agent else "")
    return [dict(r) for r in store.query(sql + " ORDER BY agent_key, unit_seq", (key, agent) if agent else (key,))]


def _head(store, key: str, agent: str) -> dict:
    return dict(store.query_one("SELECT * FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?", (key, agent)))


def _calls(store, job_id: str, **where) -> list[dict]:
    sql = "SELECT * FROM rr_review_calls WHERE run_id = ?" + "".join(f" AND {k} = ?" for k in where)
    return [dict(r) for r in store.query(sql + " ORDER BY started_at, rowid", (job_id, *where.values()))]


def _unit_ids(store, key: str) -> list[str]:
    return [u["unit_id"] for u in units.load_units(store, key)]


def _runs(fake: FakeReviewEngine) -> list[dict]:
    return [r["body"] for r in fake.calls("run")]


# ---------------------------------------------------------------- 끝까지
def test_six_experts_over_every_unit_finish_with_every_card_read_and_no_conversation(store, monkeypatch):
    """전문가 6명(카드 넷 · 배경 카드뿐 하나 · 0장 하나) × 단위 다섯 — 잡이 completed, 격자 전부 reviewed(무엇으로 봤나가 cards ·
    background · role_only 로 갈린다), 호출 원장의 ok 수가 머리에 얼린 계획대로이고 다른 결말이 없다. 포털 대화로 가는 요청은 0건,
    모든 요청의 자격은 사용자 PAT 다(서비스 PAT 0회). 모든 카드가 어느 호출에 한 번은 본문으로 실렸다(P-03). 패널 규칙에 닿지
    않는다 — 일일 패널 상한 1 인 박스에서 한 대상에 카드 대조 호출이 동시에 둘 이상 돌고 rr_panels 는 0행이다."""
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_daily_panel_cap=1))
    key = rig.target(store)
    job_id = rig.job(store, key)
    packs = rig.packs()
    fake = FakeReviewEngine(packs)
    fake.delay_s = 0.05
    r = rig.Rig(store, fake)
    r.finish(job_id)

    assert rig.state(store, job_id) == "completed" and rig.job_row(store, job_id)["error"] is None
    cells = _cells(store, key)
    assert len(cells) == len(rig.ROSTER) * len(_unit_ids(store, key)) == 30
    assert {c["state"] for c in cells} == {"reviewed"}
    assert {(c["charged"], c["infra_streak"]) for c in cells} == {(0, 0)}
    basis = {a: {c["basis"] for c in cells if c["agent_key"] == a} for a in packs}
    assert basis == {**{a: {"cards"} for a in rig.CARD_EXPERTS}, rig.BACKGROUND_ONLY: {"background"},
                     rig.ZERO_CARDS: {"role_only"}}
    assert all(c["cards_judged"] == c["cards_expected"] == 6 for c in cells if c["basis"] == "cards")
    assert review_cells.review_invariants(store, key) == []
    assert {_head(store, key, a)["state"] for a in packs} == {"ready"}
    # 원장(rr_coverage)은 마감(S9)이 의견 행과 함께 닫는다 — 카드로 검증된 근거가 있으면 done, 배경 카드뿐·0장은 done_weak.
    ledger = {r_["agent_key"]: (r_["status"], r_["reason"]) for r_ in store.query(
        "SELECT agent_key, status, reason FROM rr_coverage WHERE target_key = ?", (key,))}
    assert ledger == {**{a: ("done", None) for a in rig.CARD_EXPERTS},
                      rig.BACKGROUND_ONLY: ("done_weak", "no_verified_cite"), rig.ZERO_CARDS: ("done_weak", "no_cards")}

    calls = _calls(store, job_id)
    assert {c["state"] for c in calls} == {"ok"}
    assert len(calls) == rig.planned_calls(store, key, job_id) == len(fake.calls("run"))
    assert [r_["path"] for r_ in fake.requests if "conversations" in r_["path"] or r_["path"].endswith("/chat")] == []
    assert {r_["authorization"] for r_ in fake.requests if r_["path"] != "/health"} == {f"Bearer pat-{OWNER}"}
    assert not any(rig.SERVICE_PAT in str(r_["authorization"]) for r_ in fake.requests)
    for agent, pack in packs.items():
        # P-03 — 셀마다 카드 밖 호출이 배경 카드 전부를 본문 그대로 싣고(훑기에 실린 것으로 갈음하지 않는다), 점검 카드는 그 단위의
        # 판정 호출에 본문 그대로 실린다.
        background = [c for c in pack["cards"] if not c.get("checkable")]
        checkable = [c for c in pack["cards"] if c.get("checkable")]
        for unit_id in _unit_ids(store, key):
            bodies = [b for b in _runs(fake) if b["expert"]["key"] == agent and (b.get("unit") or {}).get("unit_id") == unit_id]
            offcard = [b for b in bodies if b["kind"] == "offcard"]
            assert len(offcard) == 1 and sorted(offcard[0]["cards"], key=lambda c: c["alias"]) == background, (agent, unit_id)
            judged = [c for b in bodies if b["kind"] == "verdict" for c in b["cards"]]
            assert all(card in judged for card in checkable), (agent, unit_id)
    assert fake.max_active >= 2
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_panels")["n"] == 0
    assert config.settings.risk_daily_panel_cap == 1

    progress = rig.progress(store, job_id)
    assert progress["phase"] == "completed" and progress["workers"] == []
    assert progress["cells"]["by_state"]["reviewed"] == 30 and progress["cells"]["failed"] == 0
    assert progress["calls"]["ok"] == len(calls) and progress["breaker"]["trips"] == 0
    assert progress["packs"] == {"total": 6, "todo": 0, "ok": 5, "empty": 1, "error": 0, "blocked": 0}


def _one(store, monkeypatch) -> None:
    """워커 하나 — 호출 차례를 그대로 볼 수 있게."""
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_concurrency=1))


def test_an_expert_session_sweeps_then_runs_every_deck_over_every_unit_before_the_next_deck(store, monkeypatch):
    """전문가 세션의 차례 — 훑기 → fwd(묶음 먼저 · 단위 나중) → rev(같은 차례) → 단독 → 카드 밖(단위마다). 묶음 둘(K=4 → 4장·2장),
    fwd 의 cards 는 그 묶음 그대로이고 digest 는 나머지 카드다. 카드 밖 호출은 배경 카드 전부를 본문으로, known 은 그 셀의 실효
    판정이다. 같은 묶음의 fwd 와 rev 는 cards 가 같다(뒤집기는 엔진 몫 — M2.md 5절 #19)."""
    _one(store, monkeypatch)
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    limits = fre.load("limits_1m.json")
    limits["verdict"]["k"] = 4
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")}, limits=limits)
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"

    order = _unit_ids(store, key)
    decks = [["K01", "K02", "K03", "K04"], ["K05", "K06"]]
    background = ["K07", "K08", "K09", "K10"]
    seen = [(b["kind"], b["variant"], (b.get("unit") or {}).get("unit_id"), [c["alias"] for c in b["cards"]])
            for b in _runs(fake)]
    expected = ([("sweep", None, None, decks[0] + decks[1] + background)]
                + [("verdict", "fwd", u, d) for d in decks for u in order]
                + [("verdict", "rev", u, d) for d in decks for u in order]
                + [("offcard", None, u, background) for u in order])
    assert seen == expected
    fwd = next(b for b in _runs(fake) if b["variant"] == "fwd")
    assert [d["alias"] for d in fwd["digest"]] == ["K05", "K06", *background]
    # run 의 기대 판은 그 종류의 판이다(엔진 RunExpect — RB3-6)
    assert fwd["expect"] == {"prompt_rev": limits["prompt_rev"]["verdict"],
                             "limits_rev_kind": limits["limits_rev_by_kind"]["verdict"]}
    offcard = [b for b in _runs(fake) if b["kind"] == "offcard"][0]
    assert [d["alias"] for d in offcard["digest"]] == decks[0] + decks[1]
    assert [k["alias"] for k in offcard["extra"]["known"]] == decks[0] + decks[1]
    assert [c for c in offcard["cards"]] == [c for c in fre.load("pack_ok.json")["cards"] if c["alias"] in background]
    calls = _calls(store, job_id)
    assert [(c["kind"], c["variant"], c["deck_id"] is not None) for c in calls][:3] == [
        ("sweep", None, True), ("verdict", "fwd", True), ("verdict", "fwd", True)]
    head = _head(store, key, SEAL)
    assert head["sweep_state"] == "done" and json.loads(head["sweep_json"])["cards_unseen"] == []
    assert {c["state"] for c in _cells(store, key, SEAL)} == {"reviewed"}


def test_a_job_on_a_finished_scope_makes_no_call(store, monkeypatch):
    """멱등 — 끝난 범위로 다시 만든 잡은 카드 묶음도 run 도 부르지 않고 completed 다."""
    key = rig.target(store)
    first = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    r = rig.Rig(store, fake)
    r.finish(first)
    before = (len(fake.calls("run")), len(fake.calls("pack")), len(fake.calls("plan")))
    snapshot = _cells(store, key)

    second = rig.job(store, key, scope={"agents": [SEAL]})
    r.finish(second)
    assert rig.state(store, second) == "completed"
    assert (len(fake.calls("run")), len(fake.calls("pack")), len(fake.calls("plan"))) == before
    assert _cells(store, key) == snapshot and _calls(store, second) == []


def test_a_restart_in_the_middle_of_a_call_reruns_only_that_call_without_charging(store, monkeypatch):
    """재기동 — 다섯째 run(넷째 단위의 fwd)이 도는 중에 프로세스가 죽은 것과 같은 자리(재기동 복구)에서 새 러너가 이어 돈다. 끊긴
    호출만 aborted('restart')로 남고 다시 나간다 — run 은 계획 + 1, 셀의 charged·infra_streak 0, 사람 손 없이 completed. 죽은
    프로세스의 호출이 뒤늦게 끝나도 선점을 잃어 아무것도 쓰지 않는다."""
    _one(store, monkeypatch)
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    gate = threading.Event()
    fake.hold_runs = {5: gate}
    first = rig.Rig(store, fake, boot_id="boot-a")
    first.tick()                                           # 묶음 받기
    first.tick(wait=False)                                 # 세션 — 다섯째 run 에서 선다
    rig.wait_for(lambda: fake.runs == 5)
    cut = store.query_one("SELECT call_id, unit_id FROM rr_review_calls WHERE state = 'running'")
    assert cut is not None

    assert review_cells.recover_running(store) == {"cells": 5, "experts": 1, "calls": 1}
    assert rig.state(store, job_id) == "running"
    second = rig.Rig(store, fake, clock=first.clock, boot_id="boot-b")
    second.finish(job_id)
    assert rig.state(store, job_id) == "completed"
    done = (_cells(store, key, SEAL), _calls(store, job_id))

    gate.set()
    first.loop.join(30)                                    # 죽은 프로세스의 늦은 끝 — 아무것도 쓰지 않는다
    assert (_cells(store, key, SEAL), _calls(store, job_id)) == done
    row = store.query_one("SELECT state, outcome_class, error_code FROM rr_review_calls WHERE call_id = ?", (cut["call_id"],))
    assert tuple(row) == ("aborted", "cancelled", "restart")
    assert len(fake.calls("run")) == rig.planned_calls(store, key, job_id) + 1
    assert [c["state"] for c in _calls(store, job_id)].count("ok") == rig.planned_calls(store, key, job_id)
    assert {(c["state"], c["charged"], c["infra_streak"]) for c in _cells(store, key, SEAL)} == {("reviewed", 0, 0)}
    assert review_cells.review_invariants(store, key) == []


# ---------------------------------------------------------------- 기다림 · 차단기
@pytest.mark.parametrize("limit", [4, 8])
def test_eight_workers_never_exceed_the_servers_gate_limit(store, monkeypatch, limit):
    """재설계 M3 C3-10 — 앱 워커 기본은 8(D-34)이고, 엔진 관문 limit(/health — 심의가 돌면 4)을 넘겨 띄우지 않는다. 6명 잡이 limit
    4 면 동시에 넷까지, 8 이면 넷을 넘는다."""
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_concurrency=8))
    assert config.settings.risk_review_concurrency == 8
    key = rig.target(store)
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(rig.packs())
    fake.gate_limit = limit
    fake.delay_s = 0.05
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    assert fake.max_active <= limit and (fake.max_active > 4) == (limit == 8)


def test_review_busy_waits_without_counting_anything(store, monkeypatch):
    """서버 관문이 동시 2 를 넘는 run 에 review_busy 로 답한다 — 기다림은 아무것도 세지 않는다(P-02(5)). 셀의 tries·infra_streak·
    charged 가 0 을 지나지 않고, 차단기는 닫힌 채이며 잡은 completed 다. 기다린 호출은 원장에 wait 로 남는다(품질 수치가 따로 센다)."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": list(rig.CARD_EXPERTS)})
    fake = FakeReviewEngine(rig.packs())
    fake.busy_over, fake.retry_after_s, fake.delay_s = 2, 1, 0.05
    rig.Rig(store, fake).finish(job_id)

    assert rig.state(store, job_id) == "completed"
    row = rig.job_row(store, job_id)
    assert (row["hold_code"], row["hold_n"]) == (None, 0)
    waits = _calls(store, job_id, state="wait")
    assert waits and {(w["outcome_class"], w["error_code"]) for w in waits} == {("wait", "review_busy")}
    cells = [c for c in _cells(store, key) if c["agent_key"] in rig.CARD_EXPERTS]
    assert {(c["state"], c["charged"], c["infra_streak"]) for c in cells} == {("reviewed", 0, 0)}
    assert sum(c["tries"] for c in cells) == len([c for c in _calls(store, job_id, state="ok") if c["unit_id"]])
    assert rig.progress(store, job_id)["breaker"] == {"state": "closed", "trips": 0, "hold_until": None, "since": None}
    assert 2 <= fake.max_active <= fake.busy_over


def test_an_infra_streak_opens_the_breaker_and_a_half_open_resume_finishes_without_charging(store, monkeypatch):
    """인프라 실패가 이어지면 차단기가 llm_outage 로 잡을 멈추고(300초 뒤 재개), 시계가 그 전이면 그대로다. 시계를 밀면 반쯤 열려
    워커 하나만 뜬다 — 그 첫 호출이 또 인프라 실패면 더 긴 간격(600초)으로 다시 멈추고, 성공하면 보류 열을 비워 원래대로 돈다.
    어느 셀도 차감되지 않는다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": list(rig.CARD_EXPERTS)})
    fake = FakeReviewEngine(rig.packs())
    fake.error_n = 1000
    r = rig.Rig(store, fake)
    r.run(lambda: rig.state(store, job_id) == "paused", step=1000)
    row = rig.job_row(store, job_id)
    assert (row["hold_code"], row["hold_n"], row["pause_reason"]) == ("llm_outage", 1, None)
    tripped = rig.progress(store, job_id)["breaker"]
    assert tripped["state"] == "open" and tripped["trips"] == 1 and row["hold_until"] == tripped["since"] + 300
    infra = [c for c in _calls(store, job_id) if c["outcome_class"] == "infra"]
    assert review_ops.BREAKER_INFRA_TRIP <= len(infra) <= review_ops.BREAKER_INFRA_TRIP + 3

    r.clock.t = row["hold_until"] - 1
    r.tick()
    assert rig.state(store, job_id) == "paused"
    r.clock.t = row["hold_until"]
    assert r.tick()["started"] == 1                                 # 반쯤 연 재개 — 워커 하나, 그 호출이 또 실패
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"], row["hold_n"], row["hold_until"]) == (
        "paused", "llm_outage", 2, r.clock() + 600)

    fake.error_n = 0                                               # 장애가 걷혔다
    r.clock.t = row["hold_until"]
    assert r.tick(wait=False)["started"] == 1
    assert rig.job_row(store, job_id)["hold_code"] == "llm_outage"
    r.loop.join(60)
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"], row["hold_n"], row["error"]) == ("running", None, 0, None)
    assert rig.progress(store, job_id)["breaker"]["state"] == "closed"
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed"
    cells = [c for c in _cells(store, key) if c["agent_key"] in rig.CARD_EXPERTS]
    assert {(c["state"], c["charged"]) for c in cells} == {("reviewed", 0)}


def test_a_content_spike_opens_the_breaker_and_it_does_not_resume_by_itself(store, monkeypatch):
    """내용 탓 실패가 절반을 넘으면 content_fail_rate 로 멈추고, 시계를 아무리 밀어도 스스로 돌아오지 않는다(사람이 재개한다). 진행판의
    차단기는 open 이고, 사람이 재개하면 첫 틱에 closed 로 돌아와 끝까지 closed 다(반대 검토 R3A-11 — 재개가 보류 열을 비워 반쯤 연
    재개의 첫 성공이 닫을 자리가 없었다)."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": list(rig.CARD_EXPERTS)})
    fake = FakeReviewEngine(rig.packs())
    fake.error_n = 200
    fake.error = {"code": "no_rows", "message": "답에 행이 하나도 없다(가짜)", "infra": False, "retryable": False}
    r = rig.Rig(store, fake)
    r.run(lambda: rig.state(store, job_id) == "paused", step=1000)
    row = rig.job_row(store, job_id)
    assert (row["hold_code"], row["hold_until"]) == ("content_fail_rate", None)
    for _ in range(3):
        r.clock.advance(100_000)
        r.tick()
    assert rig.state(store, job_id) == "paused"
    assert {c["outcome_class"] for c in _calls(store, job_id)} <= {"content", "ok"}
    assert rig.progress(store, job_id)["breaker"]["state"] == "open"

    runner.resume_job(store, job_id, by=OWNER)                      # 사람이 재개하면 이어 돈다
    fake.error_n = 0
    r.tick()
    assert rig.progress(store, job_id)["breaker"]["state"] == "closed"
    r.finish(job_id, step=1000)
    assert rig.state(store, job_id) == "completed"
    breaker = rig.progress(store, job_id)["breaker"]
    assert (breaker["state"], breaker["trips"], breaker["hold_until"]) == ("closed", 1, None)


# ---------------------------------------------------------------- 사람의 손
def _stalled(store, monkeypatch, nth: int) -> tuple[str, str, FakeReviewEngine, rig.Rig, threading.Event]:
    _one(store, monkeypatch)
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    gate = threading.Event()
    fake.hold_runs = {nth: gate}
    r = rig.Rig(store, fake)
    r.tick()
    r.tick(wait=False)
    rig.wait_for(lambda: fake.runs == nth)
    return key, job_id, fake, r, gate


def test_a_human_pause_closes_the_running_call_and_resume_carries_on(store, monkeypatch):
    """사람의 정지는 도는 호출을 닫는다 — 그 호출은 aborted(cancelled)이고 셀은 차감 없이 pending, 다음 호출은 나가지 않는다. 재개하면
    닫힌 호출부터 다시 돌아 completed 다."""
    key, job_id, fake, r, gate = _stalled(store, monkeypatch, 3)
    runner.pause_job(store, job_id, by=OWNER)
    gate.set()
    r.loop.join(30)
    closed = _calls(store, job_id, state="aborted")
    assert [(c["outcome_class"], c["error_code"]) for c in closed] == [("cancelled", "cancelled")]
    assert {(c["state"], c["charged"], c["tries"] > 0) for c in _cells(store, key, SEAL)} >= {("pending", 0, True)}
    runs = fake.runs
    for _ in range(3):
        r.clock.advance(1000)
        r.tick()
    assert fake.runs == runs and rig.state(store, job_id) == "paused"

    runner.resume_job(store, job_id, by=OWNER)
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed"
    assert {(c["state"], c["charged"]) for c in _cells(store, key, SEAL)} == {("reviewed", 0)}


def test_a_cancel_closes_the_running_call_and_the_job_ends_cancelled(store, monkeypatch):
    """취소 — 도는 호출을 닫고(cancelling) 도는 전문가가 없어지면 다음 틱이 cancelled 로 닫는다. 셀은 차감 없이 pending 이다."""
    key, job_id, fake, r, gate = _stalled(store, monkeypatch, 4)
    runner.cancel_job(store, job_id, by=OWNER)
    assert rig.state(store, job_id) == "cancelling"
    gate.set()
    r.loop.join(30)
    r.tick()
    assert rig.state(store, job_id) == "cancelled"
    assert rig.progress(store, job_id)["phase"] == "cancelled"
    assert {(c["state"], c["charged"], c["lease_owner"]) for c in _cells(store, key, SEAL) if c["state"] != "reviewed"} == {
        ("pending", 0, None)}
    assert _head(store, key, SEAL)["state"] == "planned"
    assert review_cells.review_invariants(store, key) == []


def test_a_cancel_of_a_held_job_with_a_call_in_flight_waits_for_it_and_the_next_job_reviews_every_cell(store, monkeypatch):
    """반대 검토 R3A-1 — 코드 보류(llm_outage)는 도는 호출을 닫지 않으므로 paused 인 잡에도 워커가 쥔 전문가·셀이 있다. 그 잡의
    취소는 곧바로 cancelled 가 아니라 cancelling 이고(살아 있는 잡이라 새 잡은 409 review_job_exists), 워커가 놓은 뒤 루프가
    cancelled 로 닫는다 — 진행판은 phase cancelled · 워커 없음 · 기다림 없음이다. 곧이어 만든 새 잡은 범위의 셀을 하나도 잃지 않고
    끝까지 돌아 completed 다(옛 길은 셀이 옛 잡 id 를 단 채 놓여 새 잡이 호출 0회로 completed 였다)."""
    from app import review_runner
    from app.errors import AppError

    key, first, fake, r, gate = _stalled(store, monkeypatch, 3)
    assert r.loop.hold(first, "llm_outage", "다른 워커의 인프라 실패로 차단기가 열렸다", breaker=True)
    assert runner.cancel_job(store, first, by=OWNER)["state"] == "cancelling"
    with pytest.raises(AppError) as refused:
        rig.job(store, key, scope={"agents": [SEAL]})
    assert (refused.value.code, refused.value.http_status) == ("review_job_exists", 409)
    gate.set()
    r.loop.join(30)
    r.tick()
    assert rig.state(store, first) == "cancelled"
    board = rig.progress(store, first)
    assert (board["phase"], board["workers"], board["waiting"]) == ("cancelled", [], None)
    assert review_runner.in_flight(store, target_key=key) == {"heads": 0, "cells": 0}

    second = rig.job(store, key, scope={"agents": [SEAL]})
    r.finish(second)
    assert rig.state(store, second) == "completed" and rig.job_row(store, second)["error"] is None
    assert {(c["state"], c["run_id"]) for c in _cells(store, key, SEAL)} == {("reviewed", second)}
    assert _head(store, key, SEAL)["state"] == "ready" and _calls(store, second)
    assert review_cells.review_invariants(store, key) == []


def test_a_job_closed_outside_the_loop_refuses_a_new_job_while_its_call_runs_and_released_cells_are_adopted(
        store, monkeypatch):
    """반대 검토 R3A-1 — 루프를 거치지 않고 닫힌 잡(과제 폐기처럼 잡 행을 곧바로 cancelled 로 쓰는 길)의 워커가 아직 셀을 쥐고
    있으면 새 잡은 409 review_in_flight 다. 그 문을 지나 선 잡(문이 생기기 전의 경합과 같은 자리)이 있어도 옛 잡 id 를 단 채 나중에
    놓인 범위 안 셀은 루프가 그 잡의 것으로 거둔다 — 새 잡은 셀을 다 돌아 completed 이고 호출 0회로 끝나지 않는다."""
    from app import review_runner
    from app.errors import AppError

    key, first, fake, r, gate = _stalled(store, monkeypatch, 3)
    # 워커가 첫 프레임(status)을 읽은 뒤에 잡 행을 닫는다 — 멈춤 물음은 프레임마다 묻고 다음 프레임은 문(gate)이 열려야 온다.
    rig.wait_for(lambda: any(w.get("last_step") for w in r.loop.progress(first).payload()["workers"]))
    store.execute("UPDATE rr_jobs SET state = 'cancelled' WHERE id = ?", (first,))
    with pytest.raises(AppError) as refused:
        rig.job(store, key, scope={"agents": [SEAL]})
    assert (refused.value.code, refused.value.http_status) == ("review_in_flight", 409)
    assert refused.value.detail == {"heads": 1, "cells": 5}

    monkeypatch.setattr(review_runner, "_refuse_live_jobs", lambda store, target_key: None)
    second = rig.job(store, key, scope={"agents": [SEAL]})
    assert {c["run_id"] for c in _cells(store, key, SEAL)} == {first}      # 쥔 셀이라 범위가 찍히지 않았다
    gate.set()
    r.loop.join(30)
    assert {(c["state"], c["run_id"]) for c in _cells(store, key, SEAL)} == {("pending", first)}
    r.finish(second)
    assert rig.state(store, second) == "completed" and rig.job_row(store, second)["error"] is None
    assert {(c["state"], c["run_id"]) for c in _cells(store, key, SEAL)} == {("reviewed", second)}
    assert _head(store, key, SEAL)["state"] == "ready"
    assert review_cells.review_invariants(store, key) == []


def test_a_real_purge_while_a_call_runs_refuses_a_new_job_until_the_worker_closes_and_then_its_rows_are_released(
        store, monkeypatch):
    """단계 D 리허설(실제 배선)에서 찾은 것 — 실제 과제 폐기(`routes.purge_project`)는 잡을 루프 밖에서 곧바로 cancelled 로 쓰고 셀·머리의
    선점을 비운다(m-10 — 늦은 쓰기를 버린다). 그러면 워커의 호출 닫기·놓기도 선점이 맞지 않아 0행이라 머리·셀·호출이 재기동까지
    running 으로 남고, 그 대상의 새 잡은 영영 409 review_in_flight 였다(문구는 '워커가 놓을 때까지 기다렸다가' 라고 말한다). 워커가 그
    호출을 닫으면 제 잡의 주인 없는 행만 놓는다 — 상태만 옮기고 글 열은 쓰지 않는다(m-10 은 그대로다)."""
    from app import review_runner, routes
    from app.errors import AppError
    from tests import factories

    key, job_id, fake, r, gate = _stalled(store, monkeypatch, 3)
    rig.wait_for(lambda: any(w.get("last_step") for w in r.loop.progress(job_id).payload()["workers"]))
    project = store.query_one("SELECT p.id, p.code FROM rr_targets t JOIN rr_projects p ON p.id = t.project_id"
                              " WHERE t.target_key = ?", (key,))
    with factories.routes_store(store):
        routes.purge_project(project["id"], routes.PurgeBody(code=project["code"], reason="정리"), ident=factories.ident(OWNER))
    assert rig.state(store, job_id) == "cancelled"
    with pytest.raises(AppError) as refused:                # 워커가 아직 그 호출을 쥐고 있다(R3A-1)
        rig.job(store, key, scope={"agents": [SEAL]})
    assert refused.value.code == "review_in_flight"

    gate.set()
    r.loop.join(30)
    assert review_runner.in_flight(store, target_key=key) == {"heads": 0, "cells": 0}
    calls = _calls(store, job_id)
    assert "running" not in {c["state"] for c in calls}
    assert [(c["outcome_class"], c["error_code"]) for c in calls if c["state"] == "aborted"] == [("cancelled", "cancelled")]
    assert {(c["state"], c["charged"], c["lease_owner"]) for c in _cells(store, key, SEAL)} == {("pending", 0, None)}
    # m-10 — 늦게 끝난 호출의 글은 적히지 않았다(폐기가 비운 그대로다).
    assert {(c["extras_json"], c["route_json"], c["error"]) for c in _cells(store, key, SEAL)} == {(None, None, None)}
    head = _head(store, key, SEAL)
    assert (head["state"], head["lease_owner"], head["sweep_json"], head["report_gz"], head["summary_md"]) == (
        "planned", None, None, None, None)


def test_a_job_that_takes_over_an_expert_whose_cells_closed_before_its_finalize_finalizes_it(store, monkeypatch):
    """반대 검토 R3A-1 의 변형 — 셀을 다 닫고 마감(finalize_expert) 전에 멈춘 전문가(planned)를 그 잡이 취소된 뒤 새 잡이 범위에
    넣으면, 새 잡은 셀이 앞 잡의 것이어도 그 전문가를 마감한다(호출 없이). 잡을 곧바로 닫는 취소(도는 것이 없다)도 진행판을 끝난
    모양으로 적는다(R3A-11)."""
    from app import review_runner

    _one(store, monkeypatch)
    key = rig.target(store)
    first = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    r = rig.Rig(store, fake)
    real = review_runner.finalize_expert
    monkeypatch.setattr(review_runner, "finalize_expert", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("마감 도중 결함")))
    r.tick()                                                # 묶음
    r.tick()                                                # 세션 — 셀을 다 닫고 마감에서 넘어진다
    assert {c["state"] for c in _cells(store, key, SEAL)} == {"reviewed"}
    assert (_head(store, key, SEAL)["state"], _head(store, key, SEAL)["error"]) == ("planned", "internal_error")
    monkeypatch.setattr(review_runner, "finalize_expert", real)
    assert runner.cancel_job(store, first, by=OWNER)["state"] == "cancelled"
    board = rig.progress(store, first)
    assert (board["phase"], board["workers"], board["waiting"]) == ("cancelled", [], None)
    runs = fake.runs

    second = rig.job(store, key, scope={"agents": [SEAL]})
    r.finish(second)
    assert rig.state(store, second) == "completed" and fake.runs == runs
    assert _head(store, key, SEAL)["state"] == "ready"
    assert review_cells.review_invariants(store, key) == []


def test_a_human_pause_over_a_code_hold_stays_when_the_clock_passes(store, monkeypatch):
    """코드 보류(llm_outage) 위에 사람이 정지를 누르면 사람의 정지가 이긴다 — hold_code='user' 이고 재개 시각이 지나도 그대로다
    (P-10 · M2.md 5절 #23)."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": list(rig.CARD_EXPERTS)})
    fake = FakeReviewEngine(rig.packs())
    fake.error_n = 12
    r = rig.Rig(store, fake)
    r.run(lambda: rig.state(store, job_id) == "paused", step=1000)
    assert rig.job_row(store, job_id)["hold_code"] == "llm_outage"
    runner.pause_job(store, job_id, by=OWNER)
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"], row["hold_until"], row["pause_reason"]) == ("paused", "user", None, "user")
    for _ in range(3):
        r.clock.advance(10_000)
        r.tick()
    assert rig.state(store, job_id) == "paused" and rig.job_row(store, job_id)["hold_code"] == "user"


# ---------------------------------------------------------------- 범위 · 카드 묶음
def test_a_unit_scoped_job_closes_the_expert_partial_and_leaves_the_ledger_pending(store, monkeypatch):
    """scope.unit_ids — 그 단위만 돌고 잡은 completed, 전문가는 범위 밖 pending 이 남아 partial 로 마감된다(P-04 — 마감 자리
    `finalize_expert` 는 돈다). 원장은 범위 밖 셀이 남아 닫히지 않는다(pending)."""
    key = rig.target(store)
    picked = _unit_ids(store, key)[:2]
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": picked})
    rig.Rig(store, FakeReviewEngine({SEAL: fre.load("pack_ok.json")})).finish(job_id)

    assert rig.state(store, job_id) == "completed"
    cells = {c["unit_id"]: c for c in _cells(store, key, SEAL)}
    assert {u for u, c in cells.items() if c["state"] == "reviewed"} == set(picked)
    assert {c["state"] for u, c in cells.items() if u not in picked} == {"pending"}
    assert _head(store, key, SEAL)["state"] == "partial"
    assert store.query_one("SELECT status FROM rr_coverage WHERE target_key = ? AND agent_key = ?", (key, SEAL))["status"] \
        == "pending"
    assert planner.check_invariants(store, key) == []


def _pack_error(name: str) -> tuple[int, dict]:
    sample = fre.load("pack_errors.json")[name]
    return sample["status"], sample["body"]


def test_one_experts_pack_502_fails_only_their_cells_after_six_tries(store, monkeypatch):
    """한 전문가의 카드 묶음이 502(card_fetch_failed)로 이어진다 — 60초부터 두 배로 6번 받아 보고 그 사람의 범위 안 셀만
    failed('pack_unavailable'), 머리는 blocked 다. 나머지는 reviewed 이고 잡은 completed(실패 셀 수를 error 에)."""
    key = rig.target(store)
    agents = [SEAL, "xd-syn-1"]
    job_id = rig.job(store, key, scope={"agents": agents})
    fake = FakeReviewEngine(rig.packs())
    fake.pack_errors = {"xd-syn-1": _pack_error("card_fetch_failed")}
    rig.Rig(store, fake).finish(job_id, step=2000)

    assert rig.state(store, job_id) == "completed"
    assert len([c for c in fake.calls("pack") if c["body"]["agent_key"] == "xd-syn-1"]) == review_ops.PACK_RETRY_MAX
    head = _head(store, key, "xd-syn-1")
    assert (head["state"], head["pack_status"], head["pack_error"]) == ("blocked", "error", "card_fetch_failed")
    assert {(c["state"], c["error_code"]) for c in _cells(store, key, "xd-syn-1")} == {("failed", "pack_unavailable")}
    assert {c["state"] for c in _cells(store, key, SEAL)} == {"reviewed"}
    assert "pack_unavailable 5" in rig.job_row(store, job_id)["error"]
    assert rig.progress(store, job_id)["cells"]["failed"] == 5
    assert review_cells.review_invariants(store, key) == []


def test_a_pack_class_error_on_a_run_keeps_its_pack_backoff_through_the_release(store, monkeypatch):
    """반대 검토 R3A-9 — 판정 호출이 묶음 부류 오류(card_fetch_failed)로 끝나면 머리에 묶음 백오프(60초)를 적고 놓는다. 놓기가 그
    백오프를 지우지 않는다 — 시계가 그대로면 다음 틱이 다시 집지 않고, 60초 뒤 다시 받아 끝까지 간다."""
    _one(store, monkeypatch)
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    r = rig.Rig(store, fake)
    r.tick()                                                # 묶음
    fake.error_n = 1
    fake.error = {"code": "card_fetch_failed", "message": "카드 조회 실패(가짜)", "infra": True, "retryable": True}
    r.tick()
    head = _head(store, key, SEAL)
    assert (head["state"], head["pack_status"], head["pack_error"], head["error"]) == (
        "planned", "error", "card_fetch_failed", "pack:card_fetch_failed")
    assert head["not_before"] == r.clock() + review_ops.pack_retry_s(1)
    runs = fake.runs
    r.tick()
    assert fake.runs == runs and fake.calls("pack")[1:] == []           # 백오프 안 — 다시 집지 않는다
    r.clock.advance(review_ops.pack_retry_s(1))
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed" and {c["state"] for c in _cells(store, key, SEAL)} == {"reviewed"}


def test_pack_infra_failures_back_off_without_spending_the_pack_budget(store, monkeypatch):
    """반대 검토 R3A-7 — 카드 묶음 받기의 인프라 실패(포털이 중계한 502 agent_unreachable)는 묶음 재시도 한도(6)를 깎지 않는다.
    머리 백오프(연달은 수만큼 길어진다 — 여덟째는 상한 근처)로만 놓고 묶음 시도 수는 0 이다. 회복하면 셀이 실패 없이 끝난다(§4.4 의
    인프라는 '차감 없음 · 백오프' — 실패 셀을 다시 여는 길이 M2 에는 없으므로 영구 실패가 되지 않게)."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.pack_errors[SEAL] = [(502, {"code": "agent_unreachable", "message": "에이전트 서버 재기동 중(가짜)"})] * 8
    r = rig.Rig(store, fake)
    r.run(lambda: len(fake.calls("pack")) == 8, step=1000)
    head = _head(store, key, SEAL)
    assert (head["state"], head["pack_attempts"], head["error"]) == ("planned", 0, "infra:agent_unreachable")
    assert head["not_before"] - r.clock() >= 720                      # backoff_s(8) — 30초에서 두 배씩, 900초 상한 ±20%
    assert json.loads(head["stats_json"])["pack"]["infra_streak"] == 8
    r.finish(job_id, step=1000)
    assert rig.state(store, job_id) == "completed" and rig.job_row(store, job_id)["error"] is None
    assert {(c["state"], c["error_code"]) for c in _cells(store, key, SEAL)} == {("reviewed", None)}
    assert "infra_streak" not in json.loads(_head(store, key, SEAL)["stats_json"])["pack"]


def test_every_expert_failing_the_pack_with_502_holds_the_job_aidh_unreachable(store, monkeypatch):
    """범위 안 전원의 카드 묶음이 502 면 전문가를 하나씩 실패시키지 않고 잡을 aidh_unreachable 로 멈춘다(300초 뒤 다시). 셀은
    차감·실패 없이 pending 이다."""
    key = rig.target(store)
    agents = [SEAL, "xd-syn-1"]
    job_id = rig.job(store, key, scope={"agents": agents})
    fake = FakeReviewEngine(rig.packs())
    fake.pack_errors = {a: _pack_error("card_list_unstable") for a in agents}
    r = rig.Rig(store, fake)
    r.run(lambda: rig.state(store, job_id) == "paused", step=0, ticks=5)
    row = rig.job_row(store, job_id)
    assert (row["hold_code"], row["hold_until"] - r.clock()) == ("aidh_unreachable", 300)
    assert {(c["state"], c["charged"]) for a in agents for c in _cells(store, key, a)} == {("pending", 0)}

    fake.pack_errors = {}
    r.run(lambda: rig.state(store, job_id) == "completed", step=301)        # 300초 뒤 반쯤 열려 다시 받고 끝까지
    assert rig.job_row(store, job_id)["hold_code"] is None


def test_a_zero_card_answer_then_thirty_cards_is_taken_as_thirty(store, monkeypatch):
    """P-08 — 카드 0장 응답 한 번을 '카드 결손 전문가' 로 굳히지 않는다. 다시 받은 30장 묶음이 ok 이고 셀은 그 카드로 돈다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    ok = fre.load("pack_ok.json")
    thirty = fre.derive_pack(ok, SEAL, copies=30)
    fake = FakeReviewEngine({SEAL: ok})
    fake.pack_sequence = {SEAL: [fre.derive_pack(ok, SEAL, keep="none"), thirty]}
    rig.Rig(store, fake).finish(job_id)

    assert rig.state(store, job_id) == "completed"
    head = _head(store, key, SEAL)
    assert (head["pack_status"], head["card_basis"], head["pack_attempts"]) == ("ok", "cards", 0)
    assert json.loads(head["stats_json"])["pack"] == {"zero_streak": 0, "was_nonempty": False, "cards_n": 30}
    checkable = thirty["checkable_n"]
    assert {(c["state"], c["cards_judged"], c["cards_expected"]) for c in _cells(store, key, SEAL)} == {
        ("reviewed", checkable, checkable)}


def test_a_frozen_pack_missing_on_this_box_is_fetched_again(store, monkeypatch):
    """얼린 묶음이 이 박스에 없다(다른 박스에서 들여온 원장 — 묶음은 반출하지 않는다, M2.md 5절 #22) — 세션이 PackMissing 을 보고
    다시 받아 얼린 뒤 이어 돈다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    r = rig.Rig(store, fake)
    r.tick()                                                # 묶음 받기만
    assert _head(store, key, SEAL)["pack_status"] == "ok" and fake.runs == 0
    # 들여온 박스와 같은 자리 — 머리는 묶음 열쇠를 가리키는데 rr_card_packs 에는 그 행이 없다(행을 지울 뿐 손으로 넣지 않는다).
    store.execute("DELETE FROM rr_card_packs WHERE agent_key = ?", (SEAL,))
    cardpack.clear_cache()
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed"
    assert len(fake.calls("pack")) == 2
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_card_packs WHERE agent_key = ?", (SEAL,))["n"] == 1
    assert {c["state"] for c in _cells(store, key, SEAL)} == {"reviewed"}


# ---------------------------------------------------------------- 창
def test_a_window_outage_that_recovers_leaves_no_stale_waiting_on_a_running_job(store, monkeypatch):
    """반대 검토 R3A-10 — 창 조회가 포털이 중계한 agent_unreachable 로 실패하는 동안 진행판은 waiting{reason:'agent_unreachable',
    source:'loop'} 이고 새 호출을 내지 않는다. 회복해 워커가 도는 동안에는 그 기다림이 진행판에 남지 않는다(도는 잡이 '기다림' 으로
    보이지 않게)."""
    _one(store, monkeypatch)
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.limits_error = (502, {"code": "agent_unreachable", "message": "에이전트 서버에 연결하지 못했다(가짜)"})
    gate = threading.Event()
    fake.hold_runs = {2: gate}
    r = rig.Rig(store, fake)
    r.tick()
    down = rig.progress(store, job_id)["waiting"]
    assert (down["reason"], down["source"]) == ("agent_unreachable", "loop") and fake.calls("pack") == []
    fake.limits_error = None
    r.clock.advance(61)
    r.tick()                                                # 묶음
    r.tick(wait=False)                                      # 세션 — 둘째 run 에서 선다
    rig.wait_for(lambda: fake.runs == 2)
    board = rig.progress(store, job_id)
    assert board["waiting"] is None and len(board["workers"]) == 1
    gate.set()
    r.loop.join(30)
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed"


def test_a_fallback_window_waits_and_after_600_seconds_holds_ctx_unknown_until_the_server_knows(store, monkeypatch):
    """창 출처 fallback — 새 호출을 내지 않고 기다리며(progress.waiting ctx_fallback) 600초가 이어지면 ctx_unknown 으로 멈춘다(무엇을
    적을지 — 에이전트 서버의 창 설정). 창이 server 로 돌아오면 스스로 재개해 끝까지 간다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.ctx_source = "fallback"
    r = rig.Rig(store, fake)
    start = r.clock()
    r.tick()
    assert rig.state(store, job_id) == "running" and fake.runs == 0
    assert rig.progress(store, job_id)["waiting"] == {"reason": "ctx_fallback", "since": start, "retry_at": start + 600,
                                                      "source": "loop"}
    r.clock.advance(599)
    r.tick()
    assert rig.state(store, job_id) == "running" and fake.runs == 0
    r.clock.advance(1)
    r.tick()
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"], row["hold_until"]) == ("paused", "ctx_unknown", None)
    assert "LLM_CONTEXT_TOKENS" in row["error"]
    r.clock.advance(61)
    r.tick()
    assert rig.state(store, job_id) == "paused"             # 창을 아직 모른다

    fake.ctx_source = "server"
    r.clock.advance(61)
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed" and rig.job_row(store, job_id)["hold_code"] is None


def test_an_oversize_unit_holds_ctx_too_small_and_is_never_split(store, monkeypatch):
    """계획의 oversize — 다시 쪼개지 않고 ctx_too_small 로 멈춘다(D-22). 그 단위와 이 박스의 창을 적고, 시계로 재개하지 않는다. 고칠
    곳은 막히지 않은 길이다(반대 검토 R3A-12) — 창이 큰 LLM 의 박스에서 재개하거나 손잡이를 줄여 새 대상을 연다. 검토 잡이 선 이
    대상의 단위 재빌드는 409 units_in_use 라 '단위를 다시 세운 뒤 재개' 를 권하지 않는다."""
    key = rig.target(store)
    unit_id = _unit_ids(store, key)[2]
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.oversize_units = {unit_id}
    r = rig.Rig(store, fake)
    r.run(lambda: rig.state(store, job_id) == "paused", ticks=5)
    row = rig.job_row(store, job_id)
    assert (row["hold_code"], row["hold_until"]) == ("ctx_too_small", None)
    assert unit_id in row["error"] and "1,048,576" in row["error"]
    assert "새 대상을 연다" in row["error"] and "LLM_CONTEXT_TOKENS" in row["error"] and "다시 세운 뒤" not in row["error"]
    assert fake.runs == 0 and {(c["state"], c["charged"]) for c in _cells(store, key, SEAL)} == {("pending", 0)}
    r.clock.advance(100_000)
    r.tick()
    assert rig.state(store, job_id) == "paused"
    from app.errors import AppError
    with pytest.raises(AppError) as refused:                # 손잡이를 줄여 이 대상을 다시 세우는 길은 막혀 있다
        units.build_units(store, key, built_by=OWNER, reason="R3A-12",
                          caps=units.UnitCaps(target_lines=10, max_lines=20, small_lines=5, units_max=60))
    assert refused.value.code == "units_in_use"


def test_a_window_too_small_for_any_call_holds_ctx_too_small_before_any_call(store, monkeypatch):
    """limits 의 runnable 이 거짓(창 4,096 토큰) — 카드 묶음도 run 도 부르지 않고 ctx_too_small 이며 필요한 창을 적는다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")}, limits=fre.load("limits_ctx_too_small.json"))
    r = rig.Rig(store, fake)
    r.tick()
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"]) == ("paused", "ctx_too_small")
    need = fre.load("limits_ctx_too_small.json")["ctx_too_small"]["need_ctx_tokens"]      # 계약 예제가 정한 필요 창
    assert f"{need:,}" in row["error"] and fake.runs == 0 and fake.calls("pack") == []


@pytest.mark.parametrize(("by_kind", "words"), [
    ({"sweep": "output_cap", "verdict": "output_cap", "offcard": "output_cap", "noinput": "output_cap"},
     ("sweep·verdict·offcard·noinput 까닭 output_cap", "CARD_REVIEW_MAX_TOKENS(없으면 DELIB_MAX_TOKENS)를 5,200 토큰 이상으로 올린")),
    ({"sweep": "output_too_large", "verdict": "output_too_large", "offcard": "output_too_large", "noinput": "output_too_large"},
     ("까닭 output_too_large", "출력 상한이 창보다 크다", "줄인 뒤 재개한다")),
    ({"sweep": "window", "verdict": "output_cap", "offcard": "output_cap", "noinput": "output_cap"},
     ("sweep 까닭 window", "verdict·offcard·noinput 까닭 output_cap", "창이 12,700 토큰 이상인 LLM", "5,200 토큰 이상으로")),
])
def test_a_ctx_too_small_hold_names_its_reason_and_the_knob_to_fix(store, monkeypatch, by_kind, words):
    """엔진의 ctx_too_small 까닭(RB3-14 — 셀 종류마다 reason_by_kind)마다 보류 글이 고칠 손잡이를 말한다 — 출력 상한이 행 한 줄도
    못 내면 출력 상한을 필요한 값 이상으로 올리고(창을 키워도 소용없다), 출력 상한이 창보다 크면 줄인다. 창이 모자라면(window)
    필요한 창과 창 손잡이다. 까닭이 같은 종류는 한 문장으로 묶인다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    limits = fre.load("limits_ctx_too_small.json")
    limits["ctx_too_small"] = {"reason": "window", "reason_by_kind": by_kind, "need_ctx_tokens": 12700,
                               "need_max_tokens": 5200, "message": "엔진의 말(가짜)"}
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")}, limits=limits)
    rig.Rig(store, fake).tick()
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"]) == ("paused", "ctx_too_small")
    assert all(w in row["error"] for w in words), row["error"]
    assert "엔진의 말(가짜)" in row["error"] and fake.runs == 0


def test_a_box_that_cannot_run_only_the_summary_keeps_reviewing_cells(store, monkeypatch):
    """ctx_too_small 은 셀이 부르는 종류(cell_kinds)만 본다 — 요약(summary)만 못 도는 박스는 셀 일을 멈추지 않는다(M3.md 4.3). 셀 종류
    하나라도 못 돌면 지금처럼 멈춘다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    limits = fre.load("limits_1m.json")
    limits["runnable"] = {**limits["runnable"], "summary": False}
    rig.Rig(store, FakeReviewEngine({SEAL: fre.load("pack_ok.json")}, limits=limits)).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    other = rig.target(store, seed=5)
    held = rig.job(store, other, scope={"agents": [SEAL]})
    limits["runnable"] = {**limits["runnable"], "noinput": False}
    r = rig.Rig(store, FakeReviewEngine({SEAL: fre.load("pack_ok.json")}, limits=limits))
    r.tick()
    assert (rig.job_row(store, held)["state"], rig.job_row(store, held)["hold_code"]) == ("paused", "ctx_too_small")


def test_a_pair_over_unit_runs_that_decks_cards_solo(store, monkeypatch):
    """pair_over — 묶음째로는 창을 넘는 (묶음, 단위) 짝의 카드를 그 단위에 하나씩 solo 로 돌린다(fwd·rev 없음). 셀은 reviewed 다."""
    _one(store, monkeypatch)
    key = rig.target(store)
    unit_id = _unit_ids(store, key)[1]
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.pair_over_units = {unit_id}
    rig.Rig(store, fake).finish(job_id)

    assert rig.state(store, job_id) == "completed"
    verdicts = [(b["variant"], [c["alias"] for c in b["cards"]]) for b in _runs(fake)
                if b["kind"] == "verdict" and b["unit"]["unit_id"] == unit_id]
    assert verdicts == [("solo", [a]) for a in ["K01", "K02", "K03", "K04", "K05", "K06"]]
    cell = next(c for c in _cells(store, key, SEAL) if c["unit_id"] == unit_id)
    assert (cell["state"], cell["cards_judged"]) == ("reviewed", 6)
    rows = store.query("SELECT DISTINCT variant FROM rr_card_verdicts WHERE target_key = ? AND unit_id = ?", (key, unit_id))
    assert [r_["variant"] for r_ in rows] == ["solo"]


def test_solo_asks_cover_flips_flags_and_single_card_decks(store, monkeypatch):
    """단독 재질의 — fwd 와 rev 가 갈린 카드(K05), 실효가 걸림인 카드(K04 WARNING), 같은 본문이라 rev 를 건너뛴 1장 묶음(K06 —
    X1-20, agree NULL)을 카드마다 한 번 묻는다. 앞 판정은 싣지 않는다(known 비움). 실효는 solo 이고 셀은 reviewed 다."""
    _one(store, monkeypatch)
    key = rig.target(store)
    unit_id = _unit_ids(store, key)[0]
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]})
    limits = fre.load("limits_1m.json")
    limits["verdict"]["k"] = 5
    pack = fre.load("pack_ok.json")
    record = {c["alias"]: c["record_id"] for c in pack["cards"]}
    fake = FakeReviewEngine({SEAL: pack}, limits=limits)
    fake.verdicts = {record["K04"]: ("yes", "WARNING")}
    fake.rev_verdicts = {record["K05"]: ("yes", "FAIL")}
    rig.Rig(store, fake).finish(job_id)

    assert rig.state(store, job_id) == "completed"
    solos = [b for b in _runs(fake) if b["variant"] == "solo"]
    assert [[c["alias"] for c in b["cards"]] for b in solos] == [["K04"], ["K05"], ["K06"]]
    assert all(b["extra"]["known"] == [] for b in solos)
    assert [b["variant"] for b in _runs(fake) if b["kind"] == "verdict"].count("rev") == 1      # 1장 묶음은 rev 없음
    rows = {(r_["alias"], r_["variant"]): dict(r_) for r_ in store.query(
        "SELECT alias, variant, judgement, is_effective, agree FROM rr_card_verdicts WHERE target_key = ? AND unit_id = ?",
        (key, unit_id))}
    assert rows[("K06", "solo")]["is_effective"] == 1 and rows[("K06", "fwd")]["agree"] is None
    assert rows[("K05", "fwd")]["agree"] == 0 and rows[("K05", "solo")]["is_effective"] == 1
    assert rows[("K04", "solo")]["is_effective"] == 1
    cell = next(c for c in _cells(store, key, SEAL) if c["unit_id"] == unit_id)
    assert (cell["state"], cell["n_warning"], cell["cards_judged"]) == ("reviewed", 1, 6)
    offcard = next(b for b in _runs(fake) if b["kind"] == "offcard")
    assert offcard["extra"]["known"][0]["alias"] == "K04"                          # 걸림 먼저


# ---------------------------------------------------------------- 자격 · 차례 · 상한
def test_a_portal_rejecting_the_users_pat_holds_credential_and_the_service_pat_is_never_sent(store, monkeypatch):
    """도중에 포털이 사용자 PAT 를 거절한다(401) — 잡은 credential 로 멈추고 고칠 곳(PAT 다시 발급 · 서비스 계정으로 내려가지 않는다)을
    error 에 적는다. 셀은 차감 없이 pending 이고, 데이터 디렉터리에 서비스 PAT 가 있어도 어떤 요청에도 실리지 않는다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    r = rig.Rig(store, fake)
    r.tick()                                                # 묶음은 받았다
    fake.credential_expired = True
    r.run(lambda: rig.state(store, job_id) == "paused", ticks=5)
    row = rig.job_row(store, job_id)
    assert (row["hold_code"], row["hold_until"]) == ("credential", None)
    assert "PAT 를 다시 발급" in row["error"] and "서비스 계정으로 내려가지 않" in row["error"]
    assert {(c["state"], c["charged"]) for c in _cells(store, key, SEAL)} == {("pending", 0)}
    assert not any(rig.SERVICE_PAT in str(r_["authorization"]) for r_ in fake.requests)
    r.clock.advance(100_000)
    r.tick()
    assert rig.state(store, job_id) == "paused"             # 자동 재개 없음 — 사람이 PAT 를 등록하고 재개한다

    fake.credential_expired = False
    runner.resume_job(store, job_id, by=OWNER)
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed"


def test_a_credential_failure_that_would_fill_the_breaker_window_still_holds_credential(store, monkeypatch):
    """반대 검토 R3A-8 — 내용 탓 다섯 · 성공 넷 뒤 아홉째 run 이 도는 사이 PAT 가 폐기돼 열째 호출이 자격 오류다. 그 호출이 차단기
    창의 열째가 되어도 차단기를 먼저 보지 않는다 — 잡은 credential 이고 고칠 곳(포털에서 PAT 를 다시 발급해 등록) 문구를 싣는다.
    차단기(content_fail_rate)가 먼저 걸린 뒤에 온 자격 오류도 그 보류를 덮는다. 사람의 정지는 덮지 않는다."""
    _one(store, monkeypatch)
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.error_n = 5
    fake.error = {"code": "no_rows", "message": "행이 없다(가짜)", "infra": False, "retryable": False}
    gate = threading.Event()
    fake.hold_runs = {9: gate}
    r = rig.Rig(store, fake)
    r.tick()
    r.tick()
    r.tick(wait=False)
    rig.wait_for(lambda: fake.runs == 9)
    store.delete_credential(OWNER)                              # 도는 사이 PAT 가 폐기됐다
    gate.set()
    r.loop.join(30)
    classes = [c["outcome_class"] for c in _calls(store, job_id)]
    assert classes == ["content"] * 5 + ["ok"] * 4 + ["job"]
    assert review_ops.breaker_verdict(classes[::-1]) == "content_fail_rate"   # 차단기를 먼저 봤다면 걸렸을 창이다
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"]) == ("paused", "credential")
    assert row["error"].startswith("카드 대조 호출(mech-test-seal): pat_unavailable") and "PAT 를 다시 발급해 등록" in row["error"]

    second = rig.job(store, rig.target(store, seed=3), scope={"agents": [SEAL]})
    store.execute("UPDATE rr_jobs SET state = 'running' WHERE id = ?", (second,))
    assert r.loop.hold(second, "content_fail_rate", "차단기(시험)", breaker=True)
    assert r.loop.hold(second, "credential", "창 조회: pat_unavailable — 시험")
    assert rig.job_row(store, second)["hold_code"] == "credential"
    runner.pause_job(store, second, by=OWNER)
    assert not r.loop.hold(second, "credential", "사람의 정지 위에는 걸지 않는다")
    assert rig.job_row(store, second)["hold_code"] == "user"


def test_a_pat_too_close_to_expiry_holds_credential_without_sending_anything(store, monkeypatch):
    """남은 수명이 검토 여유(호출 벽시계 + 600초) 이하인 PAT — 요청을 하나도 보내지 않고 credential 로 멈춘다(서비스 PAT 로 내려가지
    않는다 — 사용자 결정 3)."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    rig.pat(store, life_s=600)
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    rig.Rig(store, fake).tick()
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"]) == ("paused", "credential")
    assert "credential_expired" in row["error"] and "서비스 계정으로 내려가지 않" in row["error"]
    assert [r_ for r_ in fake.requests if r_["path"] != "/health"] == []


def test_a_slow_window_probe_never_reholds_a_resumed_job_with_its_old_credential_error(store, monkeypatch):
    """반대 검토 R3A-3 (가) — PAT 가 사라져 credential 로 멈춘 잡을 사람이 PAT 를 다시 등록하고 재개했는데 창 조회 왕복이 탐침
    한도를 넘는다. 틱은 지난 탐침의 오류를 다시 쓰지 않는다 — 잡은 running 그대로 이번 틱에 새 호출을 내지 않고(모름 — 기다린다),
    새 답이 온 뒤 이어 돌아 completed 다. 사람은 재개를 한 번만 한다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    r = rig.Rig(store, fake)
    r.loop.probe_join_s = 0.05
    store.delete_credential(OWNER)                              # PAT 가 사라졌다(폐기·삭제)
    r.tick()
    assert (rig.state(store, job_id), rig.job_row(store, job_id)["hold_code"]) == ("paused", "credential")
    rig.pat(store)                                              # 사람이 PAT 를 다시 등록하고 재개한다
    runner.resume_job(store, job_id, by=OWNER)
    fake.limits_delay_s = 0.3                                   # 새 탐침이 탐침 한도(시험 0.05초 · 운영 1초)를 넘는다
    r.clock.advance(5)
    r.tick()
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"], row["error"]) == ("running", None, None)
    assert fake.calls("pack") == [] and len(fake.calls("limits")) == 1
    fake.limits_delay_s = 0.0
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed"


def test_a_job_is_never_held_with_another_jobs_credential_error(store, monkeypatch):
    """반대 검토 R3A-3 (나) — 잡 둘, A 의 자격 사람(요청자)만 PAT 가 사라졌고 창 조회 왕복이 탐침 한도를 넘는다. A 는 자기 자격의
    오류로 credential 이고, B 는 A 의 오류(다른 사람의 이메일이 든 글)로 멈추지 않고 제 자격으로 물은 답을 기다렸다가 completed 다."""
    from app import review_runner

    ghost = "ghost@example.com"
    key_a, key_b = rig.target(store), rig.target(store, seed=7)
    rig.pat(store, ghost)
    job_a = review_runner.create_review_job(store, key_a, owner_sub=OWNER, requester_sub=ghost, scope={"agents": [SEAL]},
                                            consent=True, consent_source="web", settings=config.settings)["job_id"]
    job_b = rig.job(store, key_b, scope={"agents": [SEAL]})
    assert json.loads(rig.job_row(store, job_a)["params_json"])["credential"]["email"] == ghost
    store.delete_credential(ghost)
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.limits_delay_s = 0.3
    r = rig.Rig(store, fake)
    r.loop.probe_join_s = 0.05
    r.tick()
    a, b = rig.job_row(store, job_a), rig.job_row(store, job_b)
    assert (a["state"], a["hold_code"]) == ("paused", "credential") and ghost in a["error"]
    assert (b["state"], b["hold_code"], b["error"]) == ("running", None, None)
    fake.limits_delay_s = 0.0
    r.finish(job_b)
    b = rig.job_row(store, job_b)
    assert b["state"] == "completed" and ghost not in (b["error"] or "") and ghost not in b["progress_json"]


def test_two_live_jobs_take_turns(store, monkeypatch):
    """P-09 — 살아 있는 검토 잡이 둘이면 워커 자리를 번갈아 받는다(한 잡이 자리를 다 쓰지 않는다)."""
    _one(store, monkeypatch)
    first_key, second_key = rig.target(store), rig.target(store, seed=7)
    first, second = rig.job(store, first_key, scope={"agents": [SEAL]}), rig.job(store, second_key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    r = rig.Rig(store, fake)
    order: list[str] = []
    start = r.loop._start_worker

    def recording(job, head, purpose):
        order.append(job["id"])
        start(job, head, purpose)

    monkeypatch.setattr(r.loop, "_start_worker", recording)
    r.run(lambda: {rig.state(store, j) for j in (first, second)} == {"completed"})
    assert len(order) >= 4 and set(order[:2]) == {first, second}
    assert all(a != b for a, b in zip(order[:4], order[1:4]))


def test_a_cell_that_reaches_the_call_cap_fails_call_cap(store, monkeypatch):
    """셀당 호출 수 상한(m-02) — 빠진 카드를 끝내 받지 못해 재질의가 이어지면 상한에서 failed('call_cap') 이다(상한은 시험에서 줄인다)."""
    from app import review_runner

    monkeypatch.setattr(review_runner, "CALL_CAP_FACTOR", 1)
    monkeypatch.setattr(review_runner, "CALL_CAP_BASE", -4)          # 3 × (…) 대신 1 × (2·1 + 6 − 4) = 4
    key = rig.target(store)
    unit_id = _unit_ids(store, key)[0]
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.skip_cards = {"K02"}
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    cell = next(c for c in _cells(store, key, SEAL) if c["unit_id"] == unit_id)
    assert (cell["state"], cell["error_code"], cell["tries"]) == ("failed", "call_cap", 4)
    assert "call_cap 1" in rig.job_row(store, job_id)["error"]


@pytest.mark.parametrize(("kind", "variant", "cut", "charged", "cell_cut", "ledger_cut"), [
    ("offcard", None, "repaired", 0, 0, 1),
    ("offcard", None, "length", 1, 0, 1),
    ("offcard", None, "unknown", 0, None, None),
    ("verdict", "fwd", "length", 0, 0, 1),
])
def test_a_cut_counts_by_what_was_lost_and_an_off_card_answer_by_its_final_attempt(store, monkeypatch, kind, variant, cut,
                                                                                  charged, cell_cut, ledger_cut):
    """반대 검토 R3A-4 — 셀의 절단. 판정 호출이 잘려도 빠진 카드를 재질의로 다 받았으면 잃은 것이 없다(0). 카드 밖 호출은 마지막
    시도로 가린다 — 첫 시도가 잘렸지만 보충이 끝까지 낸 답(repaired, 엔진 quality.truncated 는 참)은 잘리지 않은 것이라 새 시도 없이
    reviewed 이고, 꼬리(more 줄)를 잃은 채 끝난 답(length)은 그 시도를 내용 탓으로 차감해 새 시도가 판정을 다시 낸다(그 시도의 답은
    멀쩡하다). 절단을 모르는 답(unknown)은 NULL 이고 정산을 막지 않는다. 호출 원장의 output_truncated 는 어느 갈래든 엔진 값 그대로다."""
    _one(store, monkeypatch)
    key = rig.target(store)
    unit_id = _unit_ids(store, key)[0]
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.truncate = {(kind, variant, unit_id): cut}
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed" and rig.job_row(store, job_id)["error"] is None
    cell = next(c for c in _cells(store, key, SEAL) if c["unit_id"] == unit_id)
    assert (cell["state"], cell["charged"], cell["truncated"]) == ("reviewed", charged, cell_cut)
    decks = len(json.loads(_head(store, key, SEAL)["plan_json"])["plan"]["verdict_decks"])
    assert len(_calls(store, job_id, kind="verdict", variant="fwd", seq=0)) == decks * (1 + charged)
    assert _calls(store, job_id, kind=kind)[0]["output_truncated"] == ledger_cut


def test_a_verdict_cut_whose_card_is_never_judged_leaves_the_cell_cut(store, monkeypatch):
    """반대 검토 R3A-5(M3) — 판정 호출마다 출력 상한에 걸리고 그 호출에 실린 카드 하나를 어느 변형·재질의도 끝내 판정하지 못하면
    셀의 절단은 1 이다 — 정산이 그 셀을 reviewed 로 세지 않고(나갈 기준 1 '절단 0'), 두 시도 뒤 failed 다. (잘린 판정이라도 그 카드를
    rev·재질의가 받았으면 잃은 것이 없다 — 가짜의 rev 는 거꾸로 판정해 fwd 가 잃은 끝 카드를 받으므로 엔진이 늘 빼먹는 카드를 둔다.)"""
    _one(store, monkeypatch)
    key = rig.target(store)
    unit_id = _unit_ids(store, key)[0]
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]})
    pack = fre.load("pack_ok.json")
    fake = FakeReviewEngine({SEAL: pack})
    fake.truncated = True
    fake.skip_cards = {next(c["alias"] for c in pack["cards"] if c.get("checkable"))}
    rig.Rig(store, fake).finish(job_id)
    cell = next(c for c in _cells(store, key, SEAL) if c["unit_id"] == unit_id)
    assert (cell["state"], cell["truncated"], cell["charged"]) == ("failed", 1, 2)
    assert cell["cards_judged"] < cell["cards_expected"]


@pytest.mark.parametrize("variant", ["fwd", "solo"])
def test_a_byte_identical_reask_goes_to_the_engine_not_the_request_cache(store, monkeypatch, variant):
    """재질의가 앞 호출과 바이트로 같은 본문이어도 엔진으로 간다 — 요청 캐시(request_hash)는 같은 시도의 같은 차례(seq)에서 이미
    받은 답만 돌려준다(재기동 뒤 이어 돌기). 차례가 빠지면 1장 묶음의 빠진 카드 재질의(fwd)와 단독 재질의(solo)가 앞 답(카드가
    빠진 답)을 그대로 받아, 단독은 표본 미달로 차감되고 셀이 처음부터 다시 돈다(S11 이 찾았다).
    fwd — 묶음 K=1 이라 첫 fwd 가 [K01] 하나이고 출력 상한에 걸려 그 행이 빠진다. solo — K01 이 FAIL 이라 단독으로 묻고 첫 단독이 잘린다."""
    _one(store, monkeypatch)
    key = rig.target(store)
    unit_id = _unit_ids(store, key)[0]
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]})
    pack = fre.load("pack_ok.json")
    limits = fre.load("limits_1m.json")
    if variant == "fwd":
        limits["verdict"]["k"] = 1
    fake = FakeReviewEngine({SEAL: pack}, limits=limits)
    if variant == "solo":
        fake.verdicts = {next(c["record_id"] for c in pack["cards"] if c["alias"] == "K01"): ("yes", "FAIL")}
    fake.truncate = {("verdict", variant, unit_id): "length"}
    rig.Rig(store, fake).finish(job_id)

    assert rig.state(store, job_id) == "completed"
    asked = [b for b in _runs(fake) if b["kind"] == "verdict" and b["variant"] == variant
             and [c["alias"] for c in b["cards"]] == ["K01"]]
    assert len(asked) == 2 and asked[0] == asked[1]                      # 같은 본문 두 번 — 둘째는 캐시가 아니라 엔진이 답했다
    cell = next(c for c in _cells(store, key, SEAL) if c["unit_id"] == unit_id)
    assert (cell["state"], cell["charged"], cell["error_code"]) == ("reviewed", 0, None)
    assert [b["variant"] for b in _runs(fake) if b["kind"] == "verdict"].count("fwd") == (7 if variant == "fwd" else 1)
    row = store.query_one("SELECT judgement FROM rr_card_verdicts WHERE target_key = ? AND unit_id = ? AND alias = 'K01'"
                          " AND variant = ?", (key, unit_id, variant))
    assert row is not None


def test_a_defect_in_a_session_releases_the_expert_with_a_pause_instead_of_stranding_it(store, monkeypatch):
    """세션 코드의 결함(예기치 않은 예외)이 루프를 죽이거나 전문가를 running 으로 붙들지 않는다 — 놓고 잠시(INTERNAL_BACKOFF_S) 쉰
    뒤 다시 집힌다."""
    from app import review_runner

    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    r = rig.Rig(store, fake)
    r.tick()                                                # 묶음
    real = review_runner._Session.run
    monkeypatch.setattr(review_runner._Session, "run", lambda self: (_ for _ in ()).throw(RuntimeError("결함")))
    r.tick()
    head = _head(store, key, SEAL)
    assert (head["state"], head["lease_owner"], head["error"]) == ("planned", None, "internal_error")
    assert head["not_before"] == r.clock() + review_runner.INTERNAL_BACKOFF_S
    monkeypatch.setattr(review_runner._Session, "run", real)
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed"


def test_a_deterministic_defect_on_a_cell_is_charged_every_third_time_and_never_loops_forever(store, monkeypatch):
    """반대 검토 R3A-2 — 받은 판정을 앱이 다루다 늘 같은 자리에서 넘어지는 결함(합성 — accept_rows 가 verdict 에서 늘 예외)이
    한도 없이 60초마다 되풀이되지 않는다. 넘어질 때마다 원장에 running 으로 남은 호출 행을 aborted('internal_error')로 닫고(예외 글을
    싣는다) 그 셀의 연달은 결함을 센다 — 셋째마다 내용 탓으로 차감해 둘째 차감에서 failed('internal_error')이고 잡은 completed 다.
    엔진 호출은 훑기 하나와 판정 여섯(결함 셋 × 시도 둘)뿐이다."""
    from app import review_verify

    _one(store, monkeypatch)
    key = rig.target(store)
    unit_id = _unit_ids(store, key)[0]
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    real = review_verify.accept_rows

    def broken(result, *, kind, **kwargs):
        if kind == "verdict":
            raise ValueError("결정적 결함(합성) — 같은 답이면 늘 같은 자리에서 난다")
        return real(result, kind=kind, **kwargs)

    monkeypatch.setattr(review_verify, "accept_rows", broken)
    r = rig.Rig(store, fake)
    r.finish(job_id, ticks=40)
    assert rig.state(store, job_id) == "completed" and "internal_error 1" in rig.job_row(store, job_id)["error"]
    cell = next(c for c in _cells(store, key, SEAL) if c["unit_id"] == unit_id)
    assert (cell["state"], cell["error_code"], cell["error_class"], cell["charged"], cell["tries"]) == (
        "failed", "internal_error", "content", 2, 6)
    calls = _calls(store, job_id)
    assert [c for c in calls if c["state"] == "running"] == []
    aborted = [c for c in calls if c["error_code"] == "internal_error"]
    assert len(aborted) == 6 and {(c["state"], c["outcome_class"]) for c in aborted} == {("aborted", "content")}
    assert aborted[0]["error"].startswith("ValueError: 결정적 결함(합성)")
    assert [b["kind"] for b in _runs(fake)] == ["sweep"] + ["verdict"] * 6
    assert review_cells.review_invariants(store, key) == []


def test_a_deterministic_defect_outside_any_cell_holds_the_job_contract_on_the_third(store, monkeypatch):
    """반대 검토 R3A-2 — 셀 밖(머리 몫 — 여기서는 마감)에서 늘 넘어지는 결함은 셋째에 잡을 contract 로 멈추고 예외 글을 싣는다(자동
    재개 없음). 그동안 엔진을 다시 부르지 않는다. 사람이 고치고 재개하면 이어 돌아 completed 다."""
    from app import review_runner

    _one(store, monkeypatch)
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    r = rig.Rig(store, fake)
    real = review_runner.finalize_expert
    tries: list[int] = []

    def broken(*args, **kwargs):
        tries.append(1)
        raise RuntimeError("마감 결함(합성)")

    monkeypatch.setattr(review_runner, "finalize_expert", broken)
    r.run(lambda: rig.state(store, job_id) == "paused", ticks=20)
    row = rig.job_row(store, job_id)
    assert (row["hold_code"], row["hold_until"], len(tries)) == ("contract", None, review_runner.INTERNAL_STRIKES)
    assert "RuntimeError: 마감 결함(합성)" in row["error"]
    assert {c["state"] for c in _cells(store, key, SEAL)} == {"reviewed"} and _head(store, key, SEAL)["state"] == "planned"
    runs = fake.runs
    for _ in range(3):
        r.clock.advance(1000)
        r.tick()
    assert rig.state(store, job_id) == "paused" and len(tries) == review_runner.INTERNAL_STRIKES

    monkeypatch.setattr(review_runner, "finalize_expert", real)
    runner.resume_job(store, job_id, by=OWNER)
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed" and fake.runs == runs
    assert _head(store, key, SEAL)["state"] == "ready"


def test_a_box_whose_review_switch_is_off_claims_nothing_new_and_lets_the_running_call_finish(store, monkeypatch):
    """HWAXRISK_REVIEW_ENABLED=0 로 뜬 박스(스위치가 꺼진 루프)는 새 전문가·셀을 집지 않는다 — 도는 호출은 끝까지 가 ok 로 적히고
    다음 호출은 나가지 않으며 셀은 차감 없이 pending 이다. 잡은 running 그대로이고 진행판은 waiting{reason:'review_disabled'} 다.
    다시 켜면 스스로 이어 돌아 completed 다(S8 열린 물음 b)."""
    key, job_id, fake, r, gate = _stalled(store, monkeypatch, 3)
    r.loop.settings = dataclasses.replace(r.loop.settings, risk_review_enabled=False)
    gate.set()
    r.loop.join(30)
    third = _calls(store, job_id)[2]
    assert (third["state"], third["outcome_class"]) == ("ok", "ok")
    assert {(c["charged"], c["lease_owner"]) for c in _cells(store, key, SEAL)} == {(0, None)}
    assert (_head(store, key, SEAL)["state"], _head(store, key, SEAL)["error"]) == ("planned", "review_disabled")
    for _ in range(3):
        r.tick()
        r.clock.advance(61)
    assert fake.runs == 3 and rig.state(store, job_id) == "running"
    assert rig.progress(store, job_id)["waiting"]["reason"] == "review_disabled"
    r.loop.settings = dataclasses.replace(r.loop.settings, risk_review_enabled=True)
    r.finish(job_id)
    assert rig.state(store, job_id) == "completed" and rig.progress(store, job_id)["waiting"] is None
    assert {c["state"] for c in _cells(store, key, SEAL)} == {"reviewed"}


def test_a_code_hold_lets_the_running_call_finish_and_starts_no_next_call(store, monkeypatch):
    """코드 보류는 도는 호출을 닫지 않는다(M2.md 5절 #13 · P-02(4)) — 셋째 run 이 도는 중에 차단기 보류(llm_outage)가 걸려도 그
    호출은 끝까지 가 ok 로 적히고, 다음 호출은 나가지 않으며 셀은 차감 없이 pending 으로 놓인다. 사람의 정지와 다르다."""
    key, job_id, fake, r, gate = _stalled(store, monkeypatch, 3)
    assert r.loop.hold(job_id, "llm_outage", "시험이 거는 코드 보류", breaker=True)
    gate.set()
    r.loop.join(30)
    third = _calls(store, job_id)[2]
    assert (third["state"], third["outcome_class"]) == ("ok", "ok")
    assert fake.runs == 3 and _calls(store, job_id, state="aborted") == []
    assert {(c["charged"], c["lease_owner"]) for c in _cells(store, key, SEAL)} == {(0, None)}
    assert rig.state(store, job_id) == "paused" and _head(store, key, SEAL)["state"] == "planned"


@pytest.mark.parametrize("change", ["prompt", "limits", "none"])
def test_a_revision_change_mid_job_replans_and_carries_on_and_a_real_mismatch_holds_contract(store, monkeypatch, change):
    """반대 검토 R3A-6 — 도는 잡 도중 에이전트 서버가 판을 올리면(프롬프트 판만 — limits_rev 는 그대로 — 이거나 창 판) 다음 호출의
    409 rev_mismatch 는 보류가 아니다. 세션이 놓고 다음 세션이 limits 를 다시 받아 계획을 다시 짜고, 입력 지문이 바뀐 셀은 처음부터
    돌아 completed 다(사람 손 없음). 판이 그대로인데 rev_mismatch 가 오면(앱이 계약을 어겼다) 종전대로 contract 로 멈춘다."""
    from app import review_runner

    key, job_id, fake, r, gate = _stalled(store, monkeypatch, 3)
    if change == "prompt":
        fake.base_limits["prompt_rev"]["verdict"] = "cr-verdict-next"          # 지금 판(계약 예제)과 다른 판
    elif change == "limits":
        fake.limits_rev = "limits-rev-2"                                       # 판정 손잡이가 바뀌었다 — 전체 판과 verdict 판
        fake.base_limits["limits_rev_by_kind"]["verdict"] = "verdict-rev-2"
    else:
        fake.error_n = 1
        fake.error = {"code": "rev_mismatch", "message": "판이 다르다(가짜)", "infra": False, "retryable": False}
    gate.set()
    r.loop.join(30)
    r.finish(job_id)
    row = rig.job_row(store, job_id)
    if change == "none":
        assert (row["state"], row["hold_code"]) == ("paused", "contract") and "rev_mismatch" in row["error"]
        return
    assert (row["state"], row["hold_code"], row["hold_n"], row["error"]) == ("completed", None, 0, None)
    mismatched = _calls(store, job_id, error_code="rev_mismatch")
    assert [(c["state"], c["outcome_class"]) for c in mismatched] == [("aborted", "job")]
    assert len(fake.calls("plan")) == 2
    assert {(c["state"], c["reopened_n"]) for c in _cells(store, key, SEAL)} == {("reviewed", 1)}
    head = _head(store, key, SEAL)
    assert (head["prompt_rev"], head["limits_rev"]) == (review_runner.prompt_key(fake.limits(), review_runner.CARD_KINDS),
                                                        review_runner.limits_key(fake.limits(), review_runner.CARD_KINDS))


@pytest.mark.parametrize("restart", [False, True])
def test_a_summary_only_move_replans_without_restarting_any_cell(store, monkeypatch, restart):
    """#37 · RB3-6 — 엔진이 요약 손잡이·요약 판만 올리면(전역 limits_rev 와 종류별 summary 판 · summary prompt_rev 가 바뀌고 카드
    전문가가 부르는 종류의 판은 그대로) 도는 잡은 아무 일 없이 이어 돈다 — run 의 expect 가 그 종류의 판이라 rev_mismatch 가 없고,
    그 판 올림과 함께 앱이 재기동해 새 세션이 limits 를 다시 받아도 셀 지문·계획·훑기 열쇠가 그 셀이 부르는 종류의 판만 잇기 때문에
    어느 셀도 처음부터 돌지 않으며(reopened_n 0 · 입력 지문 그대로) 계획과 훑기를 다시 받지 않는다. 재기동 없이 도는 세션은 지난
    limits 그대로 다음 호출을 내는데, 그 기대 판이 종류별이라 엔진이 받아 준다."""
    from app import review_runner

    _one(store, monkeypatch)
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.base_limits["limits_rev_by_kind"] = {k: f"{k}-rev-1" for k in fake.base_limits["kinds"]}
    gate = threading.Event()
    fake.hold_runs = {3: gate}
    r = rig.Rig(store, fake)
    r.tick()
    r.tick(wait=False)
    rig.wait_for(lambda: fake.runs == 3)
    hashes = {c["unit_id"]: c["input_hash"] for c in _cells(store, key, SEAL)}
    assert None not in hashes.values()
    fake.limits_rev = "limits-rev-2"
    fake.base_limits["limits_rev_by_kind"]["summary"] = "summary-rev-2"
    fake.base_limits["prompt_rev"]["summary"] = "cr-summary-9"
    if restart:
        review_cells.recover_running(store)                                 # 판 올림과 함께 앱도 다시 떴다
        second = rig.Rig(store, fake, clock=r.clock, boot_id="boot-b")
        second.finish(job_id)
        gate.set()
        r.loop.join(30)
    else:
        gate.set()
        r.loop.join(30)
        r.finish(job_id)
    assert rig.state(store, job_id) == "completed"
    assert _calls(store, job_id, error_code="rev_mismatch") == []
    assert {(c["state"], c["reopened_n"]) for c in _cells(store, key, SEAL)} == {("reviewed", 0)}
    assert {c["unit_id"]: c["input_hash"] for c in _cells(store, key, SEAL)} == hashes
    assert len(fake.calls("plan")) == 1
    assert [b["kind"] for b in _runs(fake)].count("sweep") == len(json.loads(_head(store, key, SEAL)["plan_json"])["plan"]
                                                                   ["manifest_pages"])
    head = _head(store, key, SEAL)
    assert head["limits_rev"] == review_runner.limits_key(fake.limits(), review_runner.CARD_KINDS)
    assert head["limits_rev"] == "offcard=offcard-rev-1,sweep=sweep-rev-1,verdict=verdict-rev-1"
    assert head["prompt_rev"] == review_runner.prompt_key(fake.limits(), review_runner.CARD_KINDS)


def test_an_engine_without_per_kind_revs_is_asked_with_the_global_rev(store, monkeypatch):
    """종류별 판(limits_rev_by_kind)을 내지 않는 엔진(M2)에는 run 의 expect 가 전역 limits_rev 이고 머리·셀의 판 열쇠도 전역 판
    그대로다(M2 원장과 같은 값)."""
    from app import review_runner

    _one(store, monkeypatch)
    key = rig.target(store)
    unit_id = _unit_ids(store, key)[0]
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.base_limits.pop("limits_rev_by_kind")
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    fwd = next(b for b in _runs(fake) if b["kind"] == "verdict")
    assert fwd["expect"] == {"prompt_rev": fake.base_limits["prompt_rev"]["verdict"], "limits_rev": fake.limits_rev}
    assert _head(store, key, SEAL)["limits_rev"] == fake.limits_rev
    assert review_runner.limits_key(fake.limits(), review_runner.CARD_KINDS) == fake.limits_rev


def test_the_cell_keys_take_only_the_kinds_the_cell_calls_and_fall_back_to_the_global_rev():
    """prompt_key·limits_key — 종류를 주면 그 종류만 잇는다. sweep·verdict·offcard 셋뿐인 엔진(M2)에서 카드 전문가의 prompt_key 는
    종전(종류 전부)과 같고, 종류별 창 판이 없으면 전역 limits_rev 그대로다(M2 원장의 지문이 바뀌지 않는다). 표에 빠진 종류는 전역
    판으로 메운다."""
    from app import review_runner as rr

    m2 = {"prompt_rev": {"sweep": "cr-sweep-1", "verdict": "cr-verdict-1", "offcard": "cr-offcard-1"}, "limits_rev": "g1"}
    assert rr.prompt_key(m2, rr.CARD_KINDS) == rr.prompt_key(m2) == "offcard=cr-offcard-1,sweep=cr-sweep-1,verdict=cr-verdict-1"
    assert rr.limits_key(m2, rr.CARD_KINDS) == rr.limits_key(m2) == "g1"
    m3 = {"prompt_rev": {**m2["prompt_rev"], "noinput": "cr-noinput-1", "summary": "cr-summary-1"}, "limits_rev": "g2",
          "limits_rev_by_kind": {"sweep": "s", "verdict": "v", "offcard": "o", "summary": "m"}}
    assert rr.prompt_key(m3, rr.GAP_KINDS) == "noinput=cr-noinput-1,sweep=cr-sweep-1"
    assert rr.limits_key(m3, rr.CARD_KINDS) == "offcard=o,sweep=s,verdict=v"
    assert rr.limits_key(m3, rr.GAP_KINDS) == "noinput=g2,sweep=s"
    assert rr.limits_key(m3) == "g2"


# ---------------------------------------------------------------- 반대 검토 R3A-5 — 나갈 기준을 지키는 갈래가 변이를 견디지 않게
def test_a_new_attempt_clears_the_old_attempts_verdicts_and_asks_the_engine_again(store, monkeypatch):
    """R3A-5(M18 · M24) — 첫 시도에서 K01 의 fwd(OK)와 rev(FAIL)가 갈려 단독 재질의가 FAIL 을 남겼는데, 그 시도가 정산에서 내용
    탓(카드 밖 답이 꼬리를 잃은 채 끝났다 — output_truncated)으로 끝난다. 새 시도는 앞 시도의 판정 행을 지우고(앞 시도의 단독 FAIL
    이 새 시도의 실효를 덮지 않는다) 판정 호출을 엔진에 다시 낸다(요청 캐시의 열쇠에 시도가 있어 앞 시도의 답을 받지 않는다). 새
    시도에서 fwd·rev 가 OK 로 같으면 단독을 묻지 않고 실효는 OK 다."""
    _one(store, monkeypatch)
    key = rig.target(store)
    unit_id = _unit_ids(store, key)[0]
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]})
    pack = fre.load("pack_ok.json")
    record_id = next(c["record_id"] for c in pack["cards"] if c["alias"] == "K01")
    fake = FakeReviewEngine({SEAL: pack})
    fake.rev_verdicts = {record_id: ("yes", "FAIL")}
    fake.solo_verdicts = {record_id: ("yes", "FAIL")}
    fake.truncate = {("offcard", None, unit_id): "length"}
    r = rig.Rig(store, fake)
    r.tick()                                                # 묶음
    r.tick()                                                # 첫 시도 — 정산에서 내용 탓
    cell = next(c for c in _cells(store, key, SEAL) if c["unit_id"] == unit_id)
    assert (cell["state"], cell["charged"], cell["error_code"]) == ("pending", 1, "output_truncated")
    solo = store.query_one("SELECT judgement FROM rr_card_verdicts WHERE target_key = ? AND unit_id = ? AND record_id = ?"
                           " AND variant = 'solo'", (key, unit_id, record_id))
    assert solo is not None and solo["judgement"] == "FAIL"
    fwd_before = len(_calls(store, job_id, kind="verdict", variant="fwd"))

    fake.rev_verdicts, fake.solo_verdicts = {}, {}           # 새 시도에서는 fwd·rev 가 같다
    r.finish(job_id)
    cell = next(c for c in _cells(store, key, SEAL) if c["unit_id"] == unit_id)
    assert (cell["state"], cell["charged"]) == ("reviewed", 1)
    rows = {(v["variant"], v["judgement"], v["is_effective"]) for v in store.query(
        "SELECT variant, judgement, is_effective FROM rr_card_verdicts WHERE target_key = ? AND unit_id = ? AND record_id = ?",
        (key, unit_id, record_id))}
    assert rows == {("fwd", "OK", 1), ("rev", "OK", 0)}
    assert len(_calls(store, job_id, kind="verdict", variant="fwd")) == 2 * fwd_before


def test_more_than_five_quote_check_disagreements_hold_the_job_contract(store, monkeypatch):
    """R3A-5(M26) — 엔진이 인용 대조를 ok 로 속이는 카드(lying_quote K01)는 앱의 재대조와 갈린다(check_disagree). 잡 단위로 다섯 건을
    넘으면 contract 로 멈춘다(X1-21 · 나갈 기준 2 — 인용 정규화·대조 규칙이 어긋난 채 끝까지 돌지 않는다)."""
    _one(store, monkeypatch)
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.lying_quote = {"K01"}
    r = rig.Rig(store, fake)
    r.run(lambda: rig.state(store, job_id) == "paused", ticks=10)
    row = rig.job_row(store, job_id)
    assert (row["hold_code"], row["hold_until"]) == ("contract", None) and "인용 대조" in row["error"]
    total = store.query_one("SELECT SUM(json_extract(quality_json, '$.app.check_disagree')) AS n FROM rr_review_calls"
                            " WHERE run_id = ? AND state = 'ok'", (job_id,))["n"]
    assert total == review_ops.CHECK_DISAGREE_MAX + 1


def test_a_window_whose_runnable_is_false_holds_ctx_too_small_without_a_ctx_too_small_block(store, monkeypatch):
    """R3A-5(M14) — limits 의 runnable 하나가 거짓이면(ctx_too_small 칸이 없어도) 묶음도 run 도 부르지 않고 ctx_too_small 로
    멈춘다(계약 예제 limits_ctx_too_small 은 두 칸을 함께 실어 runnable 갈래만으로는 지나지 않았다)."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    limits = fre.load("limits_1m.json")
    limits["runnable"]["offcard"] = False
    assert "ctx_too_small" not in limits
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")}, limits=limits)
    rig.Rig(store, fake).tick()
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"]) == ("paused", "ctx_too_small") and "'offcard': False" in row["error"]
    assert fake.runs == 0 and fake.calls("pack") == []


def test_a_pack_that_never_comes_fails_only_the_cells_in_the_jobs_scope(store, monkeypatch):
    """R3A-5(M27) — 단위 범위가 좁은 잡에서 한 전문가의 카드 묶음이 6번 502(card_fetch_failed)면 그 잡의 범위 안 셀만
    failed(pack_unavailable)이고 범위 밖 셀은 pending 으로 남는다(X1-27 — 범위는 셀을 덜 집는 것이다)."""
    key = rig.target(store)
    unit_ids = _unit_ids(store, key)
    job_id = rig.job(store, key, scope={"agents": [SEAL, "xd-syn-1"], "unit_ids": unit_ids[:2]})
    fake = FakeReviewEngine(rig.packs())
    fake.pack_errors = {"xd-syn-1": _pack_error("card_fetch_failed")}
    rig.Rig(store, fake).finish(job_id, step=2000)
    assert rig.state(store, job_id) == "completed" and "pack_unavailable 2" in rig.job_row(store, job_id)["error"]
    cells = {c["unit_id"]: (c["state"], c["error_code"]) for c in _cells(store, key, "xd-syn-1")}
    assert {u: cells[u] for u in unit_ids[:2]} == {u: ("failed", "pack_unavailable") for u in unit_ids[:2]}
    assert {cells[u] for u in unit_ids[2:]} == {("pending", None)}


def test_an_off_card_call_carries_the_background_cards_the_sweep_hit_first(store, monkeypatch):
    """R3A-5(M38) — 카드 밖 호출은 배경 카드를 전부 싣되 그 단위의 훑기 k 에 걸린 것을 먼저, 나머지는 팩 순서로 싣는다(P-03 ·
    M2.md 5절 #10). 가짜의 훑기가 그 단위의 k 에 K09 하나만 실으면 그 단위의 카드 밖 cards 는 K09 로 시작한다."""
    _one(store, monkeypatch)
    key = rig.target(store)
    unit_id = _unit_ids(store, key)[0]
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    fake.sweep_k = {unit_id: ["K09"]}
    rig.Rig(store, fake).finish(job_id)
    offcard = [b for b in _runs(fake) if b["kind"] == "offcard" and b["unit"]["unit_id"] == unit_id]
    assert [c["alias"] for c in offcard[0]["cards"]] == ["K09", "K07", "K08", "K10"]


def test_a_long_wait_hears_a_human_pause_between_slices(store, monkeypatch):
    """R3A-5(M46) — 자리 없음(review_busy, retry_after_s 3600)의 기다림은 WAIT_SLICE_S 씩 쪼개 그 사이 잡 상태를 본다 — 둘째 조각에서
    사람이 멈추면 그 세션은 곧바로 놓는다(3600초를 다 기다린 뒤가 아니라). 기다림은 아무것도 세지 않는다."""
    from app import review_runner

    _one(store, monkeypatch)
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    r = rig.Rig(store, fake)
    r.tick()                                                # 묶음
    fake.busy_n = 1
    fake.retry_after_s = 3600
    slices: list[float] = []

    def pause(seconds: float) -> bool:
        slices.append(seconds)
        if len(slices) == 2:
            runner.pause_job(store, job_id, by=OWNER)
        return False

    r.loop._pause = pause
    r.tick()
    assert len(slices) == 2 and set(slices) == {review_runner.WAIT_SLICE_S}
    assert rig.state(store, job_id) == "paused" and fake.runs == 1
    assert {(c["state"], c["tries"], c["charged"]) for c in _cells(store, key, SEAL)} == {("pending", 0, 0)}


def test_a_late_progress_write_does_not_overwrite_a_finished_jobs_board(store, monkeypatch):
    """R3A-5(M49) — 끝난 잡(completed)의 진행판은 늦게 온 쓰기(워커의 칸·단계 바꿈)가 덮지 않는다 — S12 진행 응답과 길잡이가 끝난
    잡을 도는 것으로 읽지 않게."""
    _one(store, monkeypatch)
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    r = rig.Rig(store, fake)
    r.finish(job_id)
    board = rig.job_row(store, job_id)["progress_json"]
    assert json.loads(board)["phase"] == "completed"
    late = r.loop.progress(job_id)                          # 늦게 끝난 워커가 쥔 진행판과 같은 길
    late.worker("late-worker", agent_key=SEAL, purpose="review", started_at=r.clock())
    late.set(phase="review", count=True)
    assert rig.job_row(store, job_id)["progress_json"] == board
