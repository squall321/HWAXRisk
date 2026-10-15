# 완결 판정 결정표(재설계 M3 S3-12 C11) — cells 대상의 레벨·표기가 원장 상태마다 표대로인지 생산자 경로(검토 루프·잡 사슬·셀 처분)로 본다
"""원장은 손 INSERT 없이 만든다 — 대상은 라우트, 셀·판정·보고서는 가짜 검토 엔진의 검토 루프, 쟁점 → 종합은 검토 잡 끝의 잡 사슬
(S3-5)이 세운 잡을 러너(가짜 쟁점 패널 엔진)와 종합 워커(가짜 요약 엔진)가 돈다. 셀을 다시 여는 것은 셀 꾸러미의 처분
(`review_runner.dispose_cells` — 사람의 다시), 확인은 `closure.ack_residual` 이다. cells 대상의 마감 레벨은 C3(D-34)이고, C2 마감은
M2 때 연 cells 대상(그때는 패널 손잡이 C2 를 얼렸다)으로 만든다 — 마감 레벨을 고르는 길이 없어 그 한 칸만 손으로 적는다.

행은 m3-synthesis S3-12 C11 의 ②~⑬ 이다. ①(단위 0)은 단위가 안 서면 대상이 panels 로 열려 cells 판정에 오지 않는다(W2-05 —
tests/test_target_flow.py). ⑭(거른 셀 표본)·C-a(단조)·C-e(옛 타깃)는 tests/test_closure.py 에 있다.
"""
from __future__ import annotations

import pytest

from app import closure, config, planner, review_runner, runner, synth, units
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.fake_summary_engine import FakeSummaryEngine
from tests.synth.issue_panel_engine import IssuePanelEngine

OWNER = rig.OWNER
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}
TAIL = "2차 영향 미실행(넘김 0건 표만) · 결손 사냥 미실행"
GAP = "mem-syn-0"                                                        # 회로(mem) — 합성 쌍에 ECAD 가 없어 입력 결손이다
GAP_ROSTER = (*rig.ROSTER, {"key": GAP, "domain": "mem", "relevance": 0.9})
CIRCUIT = ("pcb", "pwr", "rf", "soc", "passive", "mem")
CIRCUIT_ROSTER = (*rig.ROSTER, *({"key": f"{d}-syn-0", "domain": d, "relevance": 0.9} for d in CIRCUIT))


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_issue_panel_cap=48, risk_issue_panel_hard_cap=48)
    return risk_store


def _fake(roster=rig.ROSTER, *, no_input: dict | None = None) -> FakeReviewEngine:
    fake = FakeReviewEngine(rig.packs(roster))
    fake.verdicts = {str(CARDS["K01"]["record_id"]): ("yes", "FAIL")}
    fake.mechs = {str(CARDS["K01"]["record_id"]): ("interface.clearance", "")}
    fake.noinput_q1 = dict(no_input or {})
    return fake


def _review(store, key: str, scope=None, *, fake: FakeReviewEngine | None = None) -> str:
    job_id = rig.job(store, key, scope=scope)
    rig.Rig(store, fake or _fake()).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)
    return job_id


def _issues(store) -> None:
    """사슬이 세운 쟁점 잡을 러너가 끝까지(가짜 쟁점 패널 엔진) — 끝나면 사슬이 종합 잡을 세운다."""
    engine = IssuePanelEngine(store)
    while (job := runner.claim_next_job(store, config.settings, engine=engine)) is not None:
        runner.run_panel(store, config.settings, engine, job)


def _synth(store) -> None:
    worker = synth.SynthWorker(store, config.settings, FakeSummaryEngine())
    for _ in range(300):
        if worker.tick()["step"] == "idle":
            return
    raise AssertionError("종합 잡이 300틱 안에 끝나지 않았다")


def _ack_all(store, key: str) -> dict:
    result = closure.refresh(store, key)
    for item in [q for q in result["qualifiers"] if q["blocking"] and not q["acked"]]:
        closure.ack_residual(store, key, item["item"], reason="결정표 — 이 잔여는 넘긴다", by=OWNER,
                             basis_hash=item["basis_hash"])
    return closure.refresh(store, key)


def _reps(store, key: str) -> list[str]:
    best: dict[str, dict] = {}
    for row in planner.review_order(store, key):
        if row["domain"] not in best or row["rank_in_domain"] < best[row["domain"]]["rank_in_domain"]:
            best[row["domain"]] = row
    return [r["agent_key"] for r in best.values()]


def _cell(store, key: str, agent: str, *, state: str | None = None) -> dict:
    sql = "SELECT unit_id, agent_key, state FROM rr_review_cells WHERE target_key = ? AND agent_key = ?"
    args: tuple = (key, agent)
    if state:
        sql, args = sql + " AND state = ?", (*args, state)
    return dict(store.query_one(sql + " ORDER BY unit_seq LIMIT 1", args))


def _reopen(store, key: str, cell: dict, *, start: bool) -> dict:
    """사람의 다시(셀 꾸러미 처분 — force 면 reviewed·no_input 도 연다). start 면 그 셀 범위의 검토 잡을 세운다."""
    return review_runner.dispose_cells(store, key, action="retry", rows=[cell], decided_by=OWNER, owner_sub=OWNER,
                                       note="결정표 — 다시 본다", force=True, start=start, consent=True,
                                       consent_source="web")


def _residual(result: dict, item: str) -> dict:
    return next(q for q in result["qualifiers"] if q["item"] == item)


# ---------------------------------------------------------------- ② ~ ⑦
def test_row2_an_incomplete_grid_is_c0(store):
    """② 격자 결손(검토 잡 전 — 셀 0 · 기대 로스터 × 단위) → C0, 표기에 '격자 결손 N셀'."""
    key = rig.target(store)
    result = closure.close_level_cells(store, key, persist=False)
    expected = len(rig.ROSTER) * len(units.load_units(store, key))
    assert (result["level"], result["close_level"], result["c1"]) == ("C0", "C3", False)
    assert result["level_label"].startswith(f"C0(격자 결손 {expected}셀") and result["level_label"].endswith(f"{TAIL})")


def test_row3_open_representative_cells_are_c0_and_row4_closed_ones_are_c1(store):
    """③ 대표(영역 순위 1) 셀이 열려 있으면 C0 · '열린 셀 N'. ④ 대표 셀이 다 닫히고 나머지가 열려 있으면 C1 · '열린 셀 N'. 좁은
    범위라 사슬은 판(reviews_partial)만 세운다."""
    key = rig.target(store)
    reps = _reps(store, key)
    others = [r["key"] for r in rig.ROSTER if r["key"] not in reps]
    _review(store, key, scope={"agents": others[:1]})
    third = closure.close_level_cells(store, key, persist=False)
    assert third["level"] == "C0" and "열린 셀" in third["level_label"]
    _review(store, key, scope={"agents": reps})
    fourth = closure.close_level_cells(store, key, persist=False)
    open_cells = fourth["unseated_n"]
    assert (fourth["level"], fourth["c1"], fourth["c2"]) == ("C1", True, False) and open_cells > 0
    assert f"열린 셀 {open_cells}" in fourth["level_label"]
    assert {r["mode"] for r in store.query("SELECT mode FROM rr_jobs WHERE target_key = ?", (key,))} == {"reviews"}


def test_row5_tier_b_depth_fresh_issues_and_no_open_p1_are_c2(store):
    """⑤ 격자 전부 닫힘 → 사슬이 쟁점을 지금 셀 지문으로 고르고 쟁점 잡을 세운다. P1 이 도는 동안은 C1, 다 끝나면 C2. 마감 레벨 C3
    대상이라 종합 판 전에는 '후속 낡음(종합 전)' 이 붙는다(맨 C2 가 아니다)."""
    key = rig.target(store)
    _review(store, key)
    running = closure.cached(store, key)
    assert running["level"] == "C1" and running["counts"]["issues"]["p1"]["open"] >= 1
    _issues(store)
    result = closure.refresh(store, key)
    assert (result["level"], result["c2"], result["c3"]) == ("C2", True, False)
    assert result["level_label"].startswith("C2(") and "후속 낡음(종합 전)" in result["level_label"]


def test_row6_a_c2_target_waits_for_its_blocking_residuals_and_closes_after_the_acks(store):
    """⑥ 마감 레벨 C2 대상(M2 때 연 cells 대상) — 막음 잔여가 남으면 'C2 · 마감 대기(…)', 전부 확인하면 C2(closed)(…) 이고 저장
    레벨이 오른다."""
    key = rig.target(store)
    store.execute("UPDATE rr_targets SET close_level = 'C2' WHERE target_key = ?", (key,))   # M2 때 얼린 패널 손잡이 값
    _review(store, key)
    _issues(store)
    waiting = closure.refresh(store, key)
    assert any(q["blocking"] for q in waiting["qualifiers"])
    assert (waiting["level"], waiting["level_label"][:len("C2 · 마감 대기(")]) == ("C2", "C2 · 마감 대기(")
    closed = _ack_all(store, key)
    assert closed["level"] == "C2(closed)" and closed["level_label"].startswith("C2(closed)(")
    assert store.query_one("SELECT level FROM rr_targets WHERE target_key = ?", (key,))["level"] == "C2(closed)"


def test_row7_everything_closed_with_acked_residuals_and_a_fresh_report_is_c3_and_row11_one_open_cell_is_not(store):
    """⑦ 전원 종결 · 쟁점 끝 · 종합 판이 지금 지문으로 섰다(사슬이 사람 손 없이) · 막음 잔여는 'C2 · C3 대기(…)' 로 기다리다 전부
    확인하면 저장 C3, 표기는 `C3(… · 2차 영향 미실행 · 결손 사냥 미실행)` — 맨 C3 는 M3 에서 나오지 않는다. ⑪ 이어 셀 하나가 다시
    열리면(잡 없이 pending) 확인과 상관없이 지금 계산은 C3 가 아니고(저장 레벨은 그대로 · regressed) '열린 셀 1' 이다."""
    key = rig.target(store)
    _review(store, key)
    _issues(store)
    _synth(store)
    waiting = closure.refresh(store, key)
    assert waiting["detail"]["fresh"] == {**waiting["detail"]["fresh"], "issues": True, "report": True}
    assert any(q["blocking"] and not q["acked"] for q in waiting["qualifiers"])
    assert waiting["level_label"].startswith("C2 · C3 대기(")
    done = _ack_all(store, key)
    assert (done["level"], done["c3"]) == ("C3", True)
    assert done["level_label"].startswith("C3(") and done["level_label"].endswith(f"{TAIL})")
    assert done["level_label"] != "C3"

    _reopen(store, key, _cell(store, key, "xd-syn-1", state="reviewed"), start=False)
    reopened = _ack_all(store, key)                                       # 낡은 확인이 있어도 다시 확인한다 — 그래도 C3 가 아니다
    assert all(q["acked"] for q in reopened["qualifiers"] if q["blocking"])
    assert (reopened["level"], reopened["c3"], reopened["regressed"]) == ("C3", False, True)
    assert reopened["level_current"] != "C3" and "열린 셀 1" in reopened["level_label"]


# ---------------------------------------------------------------- ⑧ ~ ⑩ 입력 결손
def test_rows8_to_10_an_input_gap_waits_for_its_ack_and_one_more_no_input_cell_makes_the_ack_stale(store):
    """⑧ 전원 종결 · 입력 결손 미확인 → 'C2 · C3 대기(입력 결손 …)'. ⑨ 확인하면 C3(입력 결손 … · …). ⑩ 확인 뒤 입력 결손 셀이 하나
    더 생기면(사람이 다시 연 회로 셀이 이번에는 no_input) 그 확인은 낡아 다시 대기이고, 저장 레벨은 C3 그대로 · regressed 다."""
    key = rig.target(store, GAP_ROSTER)
    unit_ids = [u["unit_id"] for u in units.load_units(store, key)]
    kept = unit_ids[0]                                                    # 이 단위만 영향 있음(reviewed) — 나머지는 영향 모름
    no_input = {u: ["unknown"] for u in unit_ids if u != kept}
    _review(store, key, fake=_fake(GAP_ROSTER, no_input=no_input))
    _issues(store)
    _synth(store)
    waiting = closure.refresh(store, key)
    gap = _residual(waiting, "input_gap")
    assert (gap["blocking"], gap["acked"], gap["n"], gap["experts"]) == (True, False, len(unit_ids) - 1, 1)
    assert waiting["c3"] is False and waiting["level_label"].startswith("C2 · C3 대기(")
    assert f"입력 결손 1명·{len(unit_ids) - 1}셀(mem)" in waiting["level_label"]

    done = _ack_all(store, key)
    assert (done["level"], done["c3"]) == ("C3", True)
    assert done["level_label"].startswith(f"C3(입력 결손 1명·{len(unit_ids) - 1}셀(mem) · ")

    made = _reopen(store, key, {"unit_id": kept, "agent_key": GAP, "state": "reviewed"}, start=True)
    rig.Rig(store, _fake(GAP_ROSTER, no_input={u: ["unknown"] for u in unit_ids})).finish(made["job"]["job_id"])
    _issues(store)
    _synth(store)
    stale = closure.refresh(store, key)
    gap = _residual(stale, "input_gap")
    assert (gap["n"], gap["acked"]) == (len(unit_ids), False)
    assert (stale["level"], stale["level_current"], stale["regressed"], stale["c3"]) == ("C3", "C2", True, False)
    assert stale["level_label"].startswith(f"C2 · C3 대기(입력 결손 1명·{len(unit_ids)}셀(mem)")
    assert store.query_one("SELECT level FROM rr_targets WHERE target_key = ?", (key,))["level"] == "C3"


def test_row12_whole_circuit_domains_without_input_name_the_domains_at_c1_and_c2(store):
    """⑫ 회로 6영역 전원이 no_input 이면 C1 · C2 표기에 입력 결손과 그 영역 이름이 선다(X1-02 — 영역 전원 결손은 잔여다)."""
    key = rig.target(store, CIRCUIT_ROSTER)
    unit_ids = [u["unit_id"] for u in units.load_units(store, key)]
    fake = _fake(CIRCUIT_ROSTER, no_input={u: ["unknown"] for u in unit_ids})
    _review(store, key, scope={"agents": _reps(store, key)}, fake=fake)
    named = f"입력 결손 6명·{6 * len(unit_ids)}셀({'·'.join(sorted(CIRCUIT))})"
    first = closure.refresh(store, key)
    assert first["level"] == "C1" and named in first["level_label"]
    _review(store, key, fake=fake)
    _issues(store)
    second = closure.refresh(store, key)
    assert second["level"] == "C2" and named in second["level_label"]
    assert _residual(second, "input_gap")["domains"] == sorted(CIRCUIT)


# ---------------------------------------------------------------- ⑬ 다시 열린 셀
def test_row13_a_cell_reopened_after_the_selection_makes_the_issue_stage_stale_until_the_chain_runs_again(store):
    """⑬ 쟁점 선정 뒤 셀이 다시 열려 재검토에 들면 후속 낡음이다 — C2 가 거짓이고 표기에 '후속 낡음(재검토 1셀)'. 그 검토 잡이 끝나면
    사슬이 지금 지문으로 다시 고르고(새 사슬 잡이 그때의 다시 연 횟수를 얼린다) C2 로 돌아온다. 그 뒤 또 다시 열면 그 뒤의 것만 센다."""
    key = rig.target(store)
    _review(store, key)
    _issues(store)
    _synth(store)
    assert closure.refresh(store, key)["c2"] is True
    made = _reopen(store, key, _cell(store, key, "xd-syn-1", state="reviewed"), start=True)
    stale = closure.refresh(store, key)
    assert (stale["c1"], stale["c2"]) == (True, False)
    assert "후속 낡음(재검토 1셀)" in stale["level_label"] and "열린 셀 1" in stale["level_label"]
    rig.Rig(store, _fake()).finish(made["job"]["job_id"])
    _issues(store)
    again = closure.refresh(store, key)
    assert (again["c2"], again["detail"]["fresh"]["issues"]) == (True, True) and "후속 낡음(재검토" not in again["level_label"]
    _reopen(store, key, _cell(store, key, "mech-syn-0", state="reviewed"), start=False)  # 다시 고른 뒤의 재검토만 센다
    assert "후속 낡음(재검토 1셀)" in closure.refresh(store, key)["level_label"]
