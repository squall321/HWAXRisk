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
    assert fwd["expect"] == {"prompt_rev": limits["prompt_rev"]["verdict"], "limits_rev": limits["limits_rev"]}
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
    """내용 탓 실패가 절반을 넘으면 content_fail_rate 로 멈추고, 시계를 아무리 밀어도 스스로 돌아오지 않는다(사람이 재개한다)."""
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

    runner.resume_job(store, job_id, by=OWNER)                      # 사람이 재개하면 이어 돈다
    fake.error_n = 0
    r.finish(job_id, step=1000)
    assert rig.state(store, job_id) == "completed"


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
    assert rig.progress(store, job_id)["waiting"] == {"reason": "ctx_fallback", "since": start, "retry_at": start + 600}
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
    """계획의 oversize — 다시 쪼개지 않고 ctx_too_small 로 멈춘다(D-22). 그 단위와 이 박스의 창을 적고, 시계로 재개하지 않는다."""
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
    assert fake.runs == 0 and {(c["state"], c["charged"]) for c in _cells(store, key, SEAL)} == {("pending", 0)}
    r.clock.advance(100_000)
    r.tick()
    assert rig.state(store, job_id) == "paused"


def test_a_window_too_small_for_any_call_holds_ctx_too_small_before_any_call(store, monkeypatch):
    """limits 의 runnable 이 거짓(창 4,096 토큰) — 카드 묶음도 run 도 부르지 않고 ctx_too_small 이며 필요한 창을 적는다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")}, limits=fre.load("limits_ctx_too_small.json"))
    r = rig.Rig(store, fake)
    r.tick()
    row = rig.job_row(store, job_id)
    assert (row["state"], row["hold_code"]) == ("paused", "ctx_too_small")
    assert "11,246" in row["error"] and fake.runs == 0 and fake.calls("pack") == []


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
