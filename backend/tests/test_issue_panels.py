# 쟁점 패널(재설계 M3 S3-7) — 쟁점 하나를 지금 심의 엔진의 작은 패널로 판정하고 결과로 등록부 닻 행을 덮되 원래 분포를 남기는지 본다
"""입력은 생산자다 — 쟁점은 S3-6 의 선정(`issues.select_issues`)이 M2 검토 루프 원장(가짜 검토 엔진)에서 고른 것, 쟁점 잡은
`issues.create_issues_job`, 패널은 러너(`runner.claim_next_job` → `runner.run_panel`)가 가짜 쟁점 패널 엔진
(tests/synth/issue_panel_engine.py)으로 돈다. 사람이 닫는 것은 `registry.set_status`, 재제출은 `routes.complete_panel` 이다.
"""
from __future__ import annotations

import gzip
import hashlib
import json

import pytest

from app import brief, config, issues, registry, routes, runner, units
from app.common import canonical_json
from app.errors import AppError
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.issue_panel_engine import IssuePanelEngine

OWNER = rig.OWNER
SEAL = rig.SEAL
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}
MECH = ("interface.clearance", "")


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _rid(alias: str) -> str:
    return str(CARDS[alias]["record_id"])


def _review(store, key: str, experts, unit_ids, *, verdicts=None) -> None:
    job_id = rig.job(store, key, scope={"agents": list(experts), "unit_ids": list(unit_ids)})
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {_rid(a): v for a, v in (verdicts or {}).items()}
    fake.mechs = {_rid(a): MECH for a in (verdicts or {})}
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)


def _ledger(store, *, units_n: int = 1) -> tuple[str, list[str]]:
    """held_fail 쟁점이 서는 cells 원장 — 단위마다 둘이 K01 을 FAIL(인용 대조 통과)로, 둘이 OK 로 본다. (대상, 단위들)."""
    key = rig.target(store)
    unit_ids = [u["unit_id"] for u in units.load_units(store, key)[:units_n]]
    _review(store, key, (SEAL, "mech-syn-0"), unit_ids, verdicts={"K01": ("yes", "FAIL")})
    _review(store, key, ("xd-syn-0", "xd-syn-1"), unit_ids)
    registry.merge(store, key)
    return key, unit_ids


def _k01_anchor(store, key: str, unit_id: str) -> str:
    fids = {str(r["finding_id"]) for r in store.query(
        "SELECT finding_id FROM rr_findings WHERE target_key = ? AND unit_id = ? AND source_kind = 'card_review'"
        " AND mechanism = 'interface'", (key, unit_id))}
    (row,) = [r for r in registry.registry_rows(store, key)
              if r["direction"] == "risk" and fids & set(r["merged"].get("member_ids") or ())]
    return str(row["cluster_key"])


def _issue(store, key: str, anchor: str) -> dict:
    (row,) = [i for i in issues.issue_rows(store, key) if i["anchor_cluster_key"] == anchor]
    return row


def _row(store, key: str, cluster: str) -> dict:
    (row,) = [r for r in registry.registry_rows(store, key) if r["cluster_key"] == cluster]
    return row


def _run_issues(store, cfg, engine, key: str, *, limit: int = 10) -> list[dict]:
    """쟁점 잡 하나를 끝까지 — 러너가 집을 때마다 패널 한 건."""
    issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    out = []
    for _ in range(limit):
        job = runner.claim_next_job(store, cfg, engine=engine)
        if job is None:
            break
        out.append(runner.run_panel(store, cfg, engine, job))
        if out[-1]["status"] == "no_panel":
            break
    return out


def _resubmit(panel_id: str, result: dict) -> dict:
    """POST /panels/{id}/complete(재제출) — 쟁점 패널은 cells 대상에서도 받는다(거절되면 그 자리에서 시험이 실패한다)."""
    try:
        return routes.complete_panel(panel_id, engine="web", decision_text=result["decision_text"], turns=result["turns"],
                                     owner_sub=OWNER)
    except AppError as exc:
        pytest.fail(f"쟁점 패널 재제출이 거절됐다 — {exc.code}: {exc.message}")


def _coverage_hash(store) -> str:
    rows = [dict(r) for r in store.query("SELECT * FROM rr_coverage ORDER BY target_key, agent_key")]
    return hashlib.sha256(canonical_json(rows).encode()).hexdigest()


def _select(store, monkeypatch, tmp_path, key: str, *, cap: int = 1, **knobs) -> dict:
    """쟁점을 cap 건만 돌게 — 손잡이로 상한을 줄인다(나머지는 untried_cap)."""
    rig.configure(monkeypatch, store, tmp_path, risk_issue_panel_cap=cap, risk_issue_panel_hard_cap=cap, **knobs)
    return issues.select_issues(store, key, selected_round=1)


# ---------------------------------------------------------------- 한 바퀴
def test_an_issue_panel_runs_off_the_ledger_and_upholds_the_anchor_without_touching_the_seat_ledger(store, monkeypatch,
                                                                                                   tmp_path):
    """① 편성 전후 rr_coverage 표 전체가 같다. 패널은 kind='issue'·tier 'I'·issue_id, 좌석은 제기·반대 석이고 원장 밖 회차다. 결과가
    주장값과 같은 심각도면 upheld 이고 등록부 닻 행이 그 값으로 서며 원래 값이 before_issue 에 남는다."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key)
    issue = _issue(store, key, anchor)
    assert issue["state"] == "queued"
    before = _coverage_hash(store)
    engine = IssuePanelEngine(store, {issue["issue_id"]: {"severity": "중대", "judgement": "FAIL"}})
    results = _run_issues(store, config.settings, engine, key)
    assert results[0]["status"] == "done", results
    assert _coverage_hash(store) == before
    panel = store.query_one("SELECT kind, tier, issue_id, seats_json, status FROM rr_panels WHERE id = ?",
                            (results[0]["panel_id"],))
    assert (panel["kind"], panel["tier"], panel["issue_id"], panel["status"]) == ("issue", "I", issue["issue_id"], "done")
    roles = {s["key"]: s["issue_role"] for s in json.loads(panel["seats_json"])}
    assert roles == {SEAL: "raiser", "mech-syn-0": "raiser", "xd-syn-0": "opposer", "xd-syn-1": "opposer"}
    cycles = {r["cycle"] for r in store.query("SELECT cycle FROM rr_seat_opinions WHERE panel_id = ?",
                                              (results[0]["panel_id"],))}
    assert cycles and all(c > 100000 for c in cycles)
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_character WHERE id LIKE ?",
                           (f"{results[0]['panel_id']}#%",))["n"] == 0       # 성격 진술을 앉히지 않는다
    done = _issue(store, key, anchor)
    assert (done["state"], done["outcome"]) == ("resolved", "upheld")
    row = _row(store, key, anchor)
    assert (row["judgement"], row["issue_state"], row["issue_id"]) == ("FAIL", "upheld", issue["issue_id"])
    assert (row["merged"].get("before_issue") or {}).get("judgement") == "WARNING"
    assert results[-1]["status"] == "no_panel" and results[-1]["job_state"] == "completed"
    # 쟁점 해결 뒤 완결 캐시가 새로 써졌다(S3-8 — 러너의 close_level 이 cells 대상이면 closure 를 쓴다).
    cache = store.query_one("SELECT level_label, closure_at FROM rr_targets WHERE target_key = ?", (key,))
    assert cache["closure_at"] and "결손 사냥 미실행" in cache["level_label"]


# ---------------------------------------------------------------- 좌석 · 근거 · 질문(② ③ ④ ⑩)
def test_the_same_expert_sits_in_two_issue_panels_and_each_gets_its_own_off_ledger_cycle(store, monkeypatch, tmp_path):
    """② 같은 전문가를 쟁점 패널 둘에 앉혀도 저장된다 — 회차가 패널 번호로 갈린다(원장 밖 회차)."""
    key, unit_ids = _ledger(store, units_n=2)
    _select(store, monkeypatch, tmp_path, key, cap=2)
    results = _run_issues(store, config.settings, IssuePanelEngine(store), key)
    panels = [r["panel_id"] for r in results if r.get("panel_id")]
    assert len(panels) == 2 and all(r["status"] == "done" for r in results if r.get("panel_id"))
    cycles = [store.query_one("SELECT cycle FROM rr_seat_opinions WHERE panel_id = ? AND agent_key = ?",
                              (p, SEAL))["cycle"] for p in panels]
    assert len(set(cycles)) == 2 and all(c > 100000 for c in cycles)


def test_the_issue_brief_keeps_its_order_quotes_only_the_cited_card_section_and_passes_the_strict_linter(
        store, monkeypatch, tmp_path):
    """③ 근거 순서가 I1 → I4 → I5 → I6 → I2 → I3 → I0 → I7 → I8 이고(러너가 I0c 를 둘째 칸에), I6 에는 인용이 맞은 절만 있다 —
    카드의 다른 절(카나리아)은 브리프 어디에도 없고 동결된 brief_gz 에도 없다. 판단어 린터를 strict 로 지난다.
    ④ 질문에 부품 이름과 메커니즘 이름이 있다. ⑩ 보고서 저장 없음·3라운드·지정 도구 없음·started_by app·검색어는 질문."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key)
    issue = _issue(store, key, anchor)
    seats = issues.seats_for(store, key, issue)
    built = brief.build_issue_brief(store, key, issue, seats=seats, strict_lint=True)
    assert built["keys"] == ["I1", "I4", "I5", "I6", "I2", "I3", "I0", "I7", "I8"]
    quoted = {(r["record_id"], r["section_id"]) for r in store.query(
        "SELECT record_id, section_id FROM rr_card_verdicts WHERE target_key = ? AND is_effective = 1 AND quote_ok = 1"
        " AND agent_key IN (?, ?) AND record_id = ?", (key, SEAL, "mech-syn-0", _rid("K01")))}
    assert quoted
    sections = {str(s["sid"]): s["text"] for s in CARDS["K01"]["sections"]}
    canaries = [text for sid, text in sections.items() if (_rid("K01"), sid) not in quoted]
    i6 = next(e["result"] for e in built["evidence"] if e["key"] == "I6")
    assert any(f"[card:{rid}#{sid}]" in i6 for rid, sid in quoted)
    blob = json.dumps(built["evidence"], ensure_ascii=False)
    assert canaries and not any(text.split("\n")[0][:20] in blob for text in canaries)
    engine = IssuePanelEngine(store)
    results = _run_issues(store, config.settings, engine, key)
    opts = engine.calls[0]
    assert [e["key"] for e in opts["evidence"]] == ["I1", "I0c", "I4", "I5", "I6", "I2", "I3", "I0", "I7", "I8"]
    assert (opts["save_report"], opts["rounds"], opts["tools"], opts["started_by"]) == (0, 3, [], "app")
    assert opts["knowledge_query"] == opts["question"] and len(opts["question"]) <= issues.QUESTION_MAX
    row = _row(store, key, anchor)
    names = issues.part_names(store, row)
    assert names and not any(n.startswith("ck:") for n in names)          # 주체 ckey 의 표시 이름(부품 이름)
    assert "간극" in opts["question"] and all(n in opts["question"] for n in names)
    frozen = store.query_one("SELECT brief_gz FROM rr_panels WHERE id = ?", (results[0]["panel_id"],))["brief_gz"]
    text = gzip.decompress(frozen).decode("utf-8")
    assert not any(t.split("\n")[0][:20] in text for t in canaries)


def test_coverage_panels_carry_the_app_mark_too(store, tmp_path, monkeypatch):
    """#26 — 앱이 띄운 패널은 종전 패널도 started_by 'app' 을 싣는다(엔진 관문이 사람 심의로 세지 않게). 보고서 저장 칸은 싣지 않는다."""
    from tests.test_registry_cells import _panel_target

    key, _old = _panel_target(store, tmp_path, monkeypatch)
    panel = store.query_one("SELECT id FROM rr_panels WHERE target_key = ?", (key,))
    assert panel is not None
    opts = runner.build_delib_opts(store, config.settings, {
        **dict(store.query_one("SELECT id, target_key, owner_sub, panel_no, tier FROM rr_panels WHERE id = ?",
                               (panel["id"],))),
        "seats": json.loads(store.query_one("SELECT seats_json FROM rr_panels WHERE id = ?", (panel["id"],))["seats_json"]),
        "modifiers": ["toulmin"], "rounds": 3, "tools": []}, user_memo="")
    assert opts.get("started_by") == "app" and "save_report" not in opts


# ---------------------------------------------------------------- 닻 맞춤 · 결과 다섯 갈래(⑤ ⑥)
def test_an_atom_that_differs_from_the_anchor_only_in_its_key_is_pinned_to_the_anchor(store, monkeypatch, tmp_path):
    """⑤ 닻과 주체·메커니즘 대분류가 같은데 세부만 다른 원자는 닻에 붙고 계산값이 cluster_key_computed 에 남는다."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key)
    issue = _issue(store, key, anchor)
    engine = IssuePanelEngine(store, {issue["issue_id"]: {"detail": "clearance_close", "severity": "중대",
                                                          "judgement": "FAIL"}})
    results = _run_issues(store, config.settings, engine, key)
    (atom,) = store.query("SELECT cluster_key, source_kind, source_id, unit_id, finding_json FROM rr_findings"
                          " WHERE panel_id = ?", (results[0]["panel_id"],))
    assert (atom["cluster_key"], atom["source_kind"], atom["source_id"], atom["unit_id"]) == (
        anchor, "issue_panel", results[0]["panel_id"], unit)
    computed = json.loads(atom["finding_json"])["cluster_key_computed"]
    assert computed and computed != anchor
    assert (_issue(store, key, anchor)["state"], _issue(store, key, anchor)["outcome"]) == ("resolved", "upheld")


@pytest.mark.parametrize(("plan", "state", "outcome", "severity", "judgement"), [
    ({"severity": "경미", "judgement": "WARNING"}, "resolved", "downgraded", "경미", "WARNING"),
    ({"severity": "치명", "judgement": "FAIL"}, "resolved", "escalated", "치명", "FAIL"),
    ({"severity": "중대", "judgement": "WARNING"}, "resolved", "upheld", "중대", "WARNING"),
    ({"status": "rejected_in_panel"}, "resolved", "rejected", "중대", "WARNING"),
    ({"direction": "improvement", "severity": "경미", "judgement": "OK"}, "resolved", "rejected", "중대", "WARNING"),
    ({"judgement": "undetermined"}, "inconclusive", "undetermined", "중대", "WARNING"),
    ({"subject": "other"}, "inconclusive", "undetermined", "중대", "WARNING"),
])
def test_the_five_outcomes_set_the_issue_and_the_anchor_row(store, monkeypatch, tmp_path, plan, state, outcome,
                                                          severity, judgement):
    """⑥ 결과 다섯 갈래가 3.6 표대로이고 등록부 닻 행이 3.5 표대로다 — upheld·downgraded·escalated 는 패널 원자의 값으로 덮고
    원래 값(중대/WARNING · 주장값 · 지지 수)을 before_issue 에 남긴다. rejected 는 코드 상태 rejected_in_panel 이고 지지 수는 남는다.
    undetermined(판정 없음 · 닻에 붙은 원자 없음)는 행을 덮지 않는다. 닻에 붙지 않은 원자의 새 클러스터는 지지 0 이다(쟁점 패널
    원자는 이미 센 사람을 다시 앉힌 것이다)."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key)
    issue = _issue(store, key, anchor)
    before = _row(store, key, anchor)
    _run_issues(store, config.settings, IssuePanelEngine(store, {issue["issue_id"]: plan}), key)
    done = _issue(store, key, anchor)
    assert (done["state"], done["outcome"]) == (state, outcome)
    row = _row(store, key, anchor)
    assert (row["severity"], row["judgement"]) == (severity, judgement)
    assert row["issue_state"] == (outcome if state != "inconclusive" else "undetermined")
    if outcome in ("upheld", "downgraded", "escalated"):
        kept = row["merged"].get("before_issue") or {}
        assert (kept.get("severity"), kept.get("judgement"), kept.get("support_experts")) == ("중대", "WARNING", 2)
        assert (kept.get("claimed") or {}).get("judgement") == "FAIL"
    else:
        assert "before_issue" not in row["merged"]
    if outcome == "rejected":
        assert row["status"] == "rejected_in_panel" and row["support_experts"] == before["support_experts"] == 2
    if plan.get("subject") == "other":
        assert done["state_reason"] == "no_matching_atom"
        orphan = [r for r in registry.registry_rows(store, key) if r["cluster_key"] not in
                  {x["cluster_key"] for x in registry.registry_rows(store, key) if x["merged"].get("claimed", {}).get(
                      "fail_experts") or x["support_experts"]}]
        assert orphan and all((r["support_experts"], r["support"]) == (0, 0) for r in orphan)


def test_a_row_a_person_closed_meanwhile_keeps_the_persons_status_whatever_the_panel_says(store, monkeypatch, tmp_path):
    """⑥ 사람이 정한 상태는 어느 경우에도 건드리지 않는다 — 쟁점이 대기하는 사이 사람이 닫은 행은 패널이 기각해도 사람의 상태다."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key)
    issue = _issue(store, key, anchor)
    registry.set_status(store, anchor, "verified", owner_sub=OWNER, target_key=key, evidence_ref="rpt:1")
    _run_issues(store, config.settings, IssuePanelEngine(store, {issue["issue_id"]: {"status": "rejected_in_panel"}}), key)
    assert _issue(store, key, anchor)["outcome"] == "rejected"
    assert _row(store, key, anchor)["status"] == "verified"


# ---------------------------------------------------------------- 실패와 재개(⑦)
def test_an_engine_that_has_no_seat_for_the_panel_sends_the_issue_back_to_the_queue_uncharged(store, monkeypatch,
                                                                                              tmp_path):
    """⑦ 엔진 관문 자리 없음 — 패널은 시작 못 함으로 닫히고 쟁점은 차감 없이 queued, 잡은 멈춘다(사람이 재개)."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key, risk_engine_busy_max_wait_s=0)
    engine = IssuePanelEngine(store, {"*": runner.EngineBusy("자리 없음")})
    results = _run_issues(store, config.settings, engine, key, limit=1)
    assert results[0]["status"] == "error" and results[0]["error"].startswith("engine_busy")
    issue = _issue(store, key, anchor)
    assert (issue["state"], issue["charged"], issue["attempts"]) == ("queued", 0, 1)
    assert store.query_one("SELECT state FROM rr_jobs WHERE mode = 'issues'")["state"] == "paused"


def test_a_restart_mid_panel_requeues_the_issue_and_pauses_the_job(store, monkeypatch, tmp_path):
    """⑦ 재기동(recover_running_panels) — 도는 쟁점 패널은 error('restart'), 쟁점은 차감 없이 queued, 잡은 멈춘다."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key)
    issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    job = runner.claim_next_job(store, config.settings)
    panel = issues.plan_issue_panel(store, key, job=job)
    issues.start_issue_panel(store, panel["id"])
    assert _issue(store, key, anchor)["state"] == "running"
    out = runner.recover_running_panels(store)
    assert out == {"recovered": 1, "paused": 1}
    assert store.query_one("SELECT status, error FROM rr_panels WHERE id = ?", (panel["id"],))["error"] == "restart"
    issue = _issue(store, key, anchor)
    assert (issue["state"], issue["charged"]) == ("queued", 0)
    assert store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job["id"],))["state"] == "paused"


def test_an_unparseable_decision_charges_the_issue_and_the_second_makes_it_inconclusive(store, monkeypatch, tmp_path):
    """⑦ 결정문 파싱 실패 — 패널은 done·risk_spec_parsed 0, 쟁점은 내용 탓 하나(charged 1)로 대기. 한도(2)면
    inconclusive(spec_parse_failed). 그 패널을 고쳐 다시 내면(POST /panels/{id}/complete) resolve_issue 가 다시 돈다."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key)
    issue_id = _issue(store, key, anchor)["issue_id"]
    engine = IssuePanelEngine(store, {issue_id: "unparseable"})
    results = _run_issues(store, config.settings, engine, key, limit=1)
    assert store.query_one("SELECT status, risk_spec_parsed FROM rr_panels WHERE id = ?",
                           (results[0]["panel_id"],))["risk_spec_parsed"] == 0
    assert (_issue(store, key, anchor)["state"], _issue(store, key, anchor)["charged"]) == ("queued", 1)
    second = _run_issues(store, config.settings, engine, key, limit=1)
    issue = _issue(store, key, anchor)
    assert (issue["state"], issue["state_reason"], issue["charged"]) == ("inconclusive", "spec_parse_failed", 2)
    good = IssuePanelEngine(store, {issue_id: {"severity": "치명", "judgement": "FAIL"}})
    fixed = good.run(engine.calls[-1])
    _resubmit(second[0]["panel_id"], fixed)
    issue = _issue(store, key, anchor)
    assert (issue["state"], issue["outcome"]) == ("resolved", "escalated")
    assert _row(store, key, anchor)["severity"] == "치명"


def test_three_engine_errors_in_a_row_fail_the_job_and_leave_the_rest_untried(store, monkeypatch, tmp_path):
    """⑦ 연속 3패널 오류 — 잡은 failed 이고 남은 대기 쟁점은 untried_cap(engine_fail) 이다(지우지 않는다)."""
    key, unit_ids = _ledger(store, units_n=2)
    _select(store, monkeypatch, tmp_path, key, cap=2)
    engine = IssuePanelEngine(store, {"*": runner.EngineError("엔진이 터졌다")})
    _run_issues(store, config.settings, engine, key, limit=5)
    assert store.query_one("SELECT state, error FROM rr_jobs WHERE mode = 'issues'")["error"] == "engine_fail_streak"
    rows = issues.issue_rows(store, key)
    assert {(r["state"], r["state_reason"]) for r in rows if r["rank"] <= 2} == {("untried_cap", "engine_fail")}
    assert all(r["charged"] == 0 for r in rows)


def test_a_cancelled_issue_job_leaves_the_waiting_issues_untried(store, monkeypatch, tmp_path):
    """3.7 — 사람이 취소한 쟁점 잡 뒤에는 잇지 않는다. 남은 대기 쟁점은 untried_cap(chain_cancelled) 이다(지우지 않는다)."""
    key, unit_ids = _ledger(store, units_n=2)
    _select(store, monkeypatch, tmp_path, key, cap=2)
    job = issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    runner.cancel_job(store, job["job_id"], by=OWNER)
    rows = [r for r in issues.issue_rows(store, key) if r["rank"] <= 2]
    assert {(r["state"], r["state_reason"]) for r in rows} == {("untried_cap", "chain_cancelled")}
    assert store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job["job_id"],))["state"] == "cancelled"


def test_a_result_that_failed_to_persist_keeps_the_issue_running_until_the_repersist_resolves_it(store, monkeypatch,
                                                                                                 tmp_path):
    """⑦ 결과 저장 실패 — 패널 persist_error, 쟁점은 running 그대로, 잡은 멈춘다. 다시 저장(repersist_panel)이 resolve_issue 까지."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key)
    issue_id = _issue(store, key, anchor)["issue_id"]

    class Boom:
        def __getattr__(self, name):
            if name == "merge_panel":
                def fail(*_a, **_k):
                    raise RuntimeError("병합이 터졌다")
                return fail
            return getattr(registry, name)

    engine = IssuePanelEngine(store, {issue_id: {"severity": "중대", "judgement": "FAIL"}})
    issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    job = runner.claim_next_job(store, config.settings)
    out = runner.run_panel(store, config.settings, engine, job, registry_mod=Boom())
    assert out["status"] == "error" and out["error"].startswith(runner.PERSIST_ERROR_CODE)
    assert _issue(store, key, anchor)["state"] == "running"
    runner.repersist_panel(store, config.settings, out["panel_id"])
    issue = _issue(store, key, anchor)
    assert (issue["state"], issue["outcome"]) == ("resolved", "upheld")


def test_issue_jobs_do_not_stop_for_the_daily_cap_and_issue_panels_do_not_count_toward_it(store, monkeypatch, tmp_path):
    """#27 — 하루 상한은 종전 패널(kind='coverage')만 센다. 상한이 0 이어도 쟁점 잡은 멈추지 않는다."""
    key, (unit,) = _ledger(store)
    _select(store, monkeypatch, tmp_path, key, risk_daily_panel_cap=0)
    results = _run_issues(store, config.settings, IssuePanelEngine(store), key)
    assert results and results[0]["status"] == "done", results
    assert runner._panels_today(store, key) == 0
    assert store.query_one("SELECT state FROM rr_jobs WHERE mode = 'issues'")["state"] == "completed"


def test_no_panel_is_claimed_while_the_agent_server_drains(store, monkeypatch, tmp_path):
    """#50 — 에이전트 서버가 비우는 중(drain.on)이면 패널(쟁점 포함)을 집지 않고 잡 행에 까닭을 적는다. 풀리면 이어 돈다."""
    key, (unit,) = _ledger(store)
    _select(store, monkeypatch, tmp_path, key)
    engine = IssuePanelEngine(store)
    engine.drain = True
    issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    assert runner.claim_next_job(store, config.settings, engine=engine) is None
    row = store.query_one("SELECT state, error FROM rr_jobs WHERE mode = 'issues'")
    assert row["state"] == "queued" and row["error"].startswith(runner.DRAIN_CODE)
    engine.drain = False
    assert runner.claim_next_job(store, config.settings, engine=engine) is not None


def test_issue_panels_that_add_no_new_cluster_never_stop_the_job_as_diminishing(store, monkeypatch, tmp_path):
    """⑧ 쟁점 패널 셋이 잇달아 새 클러스터 0 이어도 잡이 diminishing 으로 멈추지 않는다(수확 체감은 종전 패널만)."""
    key, unit_ids = _ledger(store, units_n=3)
    _select(store, monkeypatch, tmp_path, key, cap=3)
    results = _run_issues(store, config.settings, IssuePanelEngine(store), key)
    done = [r for r in results if r["status"] == "done"]
    assert len(done) == 3 and all(r["new_clusters"] == 0 for r in done)
    job = store.query_one("SELECT state, pause_reason FROM rr_jobs WHERE mode = 'issues'")
    assert (job["state"], job["pause_reason"]) == ("completed", None)


def test_a_late_resubmission_of_an_old_panel_does_not_override_the_current_panels_result(store, monkeypatch, tmp_path):
    """⑨ 늦게 끝난 옛 패널의 재제출이 지금 패널의 결과를 덮지 않는다 — 쟁점의 panel_id 가 그 패널이 아니면 결과는 패널에만 남는다."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key)
    issue_id = _issue(store, key, anchor)["issue_id"]
    engine = IssuePanelEngine(store, {issue_id: "unparseable"})
    old = _run_issues(store, config.settings, engine, key, limit=1)[0]["panel_id"]
    engine.script[issue_id] = {"severity": "중대", "judgement": "FAIL"}
    _run_issues(store, config.settings, engine, key, limit=1)
    assert (_issue(store, key, anchor)["outcome"], _row(store, key, anchor)["judgement"]) == ("upheld", "FAIL")
    late = IssuePanelEngine(store, {issue_id: {"severity": "경미", "judgement": "WARNING"}}).run(engine.calls[-1])
    _resubmit(old, late)
    issue = _issue(store, key, anchor)
    assert (issue["outcome"], issue["panel_id"]) == ("upheld", engine_panel(store, issue_id))
    assert _row(store, key, anchor)["judgement"] == "FAIL"


def engine_panel(store, issue_id: str) -> str:
    return str(store.query_one("SELECT id FROM rr_panels WHERE issue_id = ? ORDER BY panel_no DESC LIMIT 1",
                               (issue_id,))["id"])


# ---------------------------------------------------------------- 다시 고르기(S3-6 ⑧ ⑨) — 끝난 쟁점이 서야 본다
def test_a_resolved_issue_comes_back_only_when_its_raisers_change(store, monkeypatch, tmp_path):
    """S3-6 ⑧ — 끝난 쟁점은 근거(제기자·반대자·주장값)가 그대로면 다시 골라도 그대로다. 새 제기자가 서면 queued 로 돌아간다."""
    key = rig.target(store)
    (unit,) = [u["unit_id"] for u in units.load_units(store, key)[:1]]
    _review(store, key, (SEAL,), [unit], verdicts={"K01": ("yes", "FAIL")})
    _review(store, key, ("xd-syn-0",), [unit])
    registry.merge(store, key)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key)
    _run_issues(store, config.settings, IssuePanelEngine(store), key)
    resolved = _issue(store, key, anchor)
    assert resolved["state"] == "resolved"
    issues.select_issues(store, key, selected_round=2)
    assert _issue(store, key, anchor)["state"] == "resolved"
    _review(store, key, ("mech-syn-0",), [unit], verdicts={"K01": ("yes", "FAIL")})
    registry.merge(store, key)
    _select(store, monkeypatch, tmp_path, key, cap=2)
    again = _issue(store, key, anchor)
    assert again["state"] == "queued" and again["basis_hash"] != resolved["basis_hash"] and again["outcome"] is None


def test_the_cap_counts_the_panels_a_target_already_ran_across_rounds(store, monkeypatch, tmp_path):
    """S3-6 ⑨ — 상한 셈이 다시 고른 회차에서도 누적이다. 상한 1 로 한 건을 돌린 뒤 다시 고르면 남은 쟁점은 여전히 상한 밖이다."""
    key, unit_ids = _ledger(store, units_n=2)
    out = _select(store, monkeypatch, tmp_path, key)
    assert (out["queued"], out["untried_cap"]) == (1, 1)
    _run_issues(store, config.settings, IssuePanelEngine(store), key)
    again = issues.select_issues(store, key, selected_round=2)
    assert again["cap"]["used"] == {"P1": 1, "other": 0} and again["queued"] == 0
    assert sorted(r["state"] for r in issues.issue_rows(store, key)) == ["resolved", "untried_cap"]


def test_issue_panels_keep_the_ledger_invariants(store, monkeypatch, tmp_path):
    """planner.check_invariants — 편성·도는 쟁점 패널은 그 쟁점의 지금 패널이고 좌석은 로스터 안이다."""
    from app import planner

    key, (unit,) = _ledger(store)
    _select(store, monkeypatch, tmp_path, key)
    issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    job = runner.claim_next_job(store, config.settings)
    panel = issues.plan_issue_panel(store, key, job=job)
    assert planner.check_invariants(store, key) == []
    store.execute("UPDATE rr_issues SET panel_id = 'elsewhere' WHERE panel_id = ?", (panel["id"],))   # 어긋남을 만든다
    assert any("(8)" in p for p in planner.check_invariants(store, key))


def test_the_issue_result_line_names_the_same_atom_as_the_outcome_and_the_registry(store, monkeypatch, tmp_path):
    """M2 — 패널이 닻에 같은 심각도의 원자를 여럿 내면(중대 FAIL · 중대 OK …) 결과 칸(outcome_json 의 판정)도 등록부·결과처럼
    (심각도, 판정) 순으로 고른다 — 종전에는 (심각도, finding id) 로 골라 보고서 줄이 등록부와 어긋났다."""
    key, unit_ids = _ledger(store, units_n=2)
    _select(store, monkeypatch, tmp_path, key, cap=2)
    script = {"*": {"severity": "중대", "judgement": "FAIL",
                    "also": [{"severity": "중대", "judgement": "OK"}] * 3 + [{"severity": "중대", "judgement": "undetermined"}]}}
    _run_issues(store, config.settings, IssuePanelEngine(store, script), key)
    registry.merge(store, key)
    done = [r for r in issues.issue_rows(store, key) if r["state"] == "resolved"]
    assert len(done) == 2
    for issue in done:
        outcome = json.loads(issue["outcome_json"])
        row = _row(store, key, issue["anchor_cluster_key"])
        assert (outcome["severity_after"], outcome["judgement_after"]) == ("중대", "FAIL") == (row["severity"], row["judgement"])


def test_an_issue_panel_that_ends_after_a_purge_writes_nothing_back(store, monkeypatch, tmp_path):
    """L6(결정) — 폐기(purge) 뒤에 끝난 쟁점 패널의 결과는 버린다 — 패널 원문(결정문 · 결과 원문 · 도구 호출)도, 쟁점 패널 finding 도,
    쟁점의 결과도 쓰지 않는다(같은 트랜잭션에서 과제의 폐기 상태를 본다). 패널에는 까닭만 남는다."""
    from tests import factories

    key, (unit,) = _ledger(store)
    _select(store, monkeypatch, tmp_path, key, cap=1)
    project_id = store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]
    code = store.query_one("SELECT code FROM rr_projects WHERE id = ?", (project_id,))["code"]

    class PurgingEngine(IssuePanelEngine):
        def run(self, delib_opts, *, owner_sub=None):
            out = super().run(delib_opts, owner_sub=owner_sub)
            with factories.routes_store(store):
                routes.purge_project(project_id, routes.PurgeBody(code=code, reason="폐기 시험"), ident=factories.ident(OWNER))
            return out

    results = _run_issues(store, config.settings, PurgingEngine(store, {"*": {"severity": "치명", "judgement": "FAIL"}}), key)
    panel_id = results[0]["panel_id"]
    assert results[0]["status"] == "purged"
    panel = store.query_one("SELECT status, error, decision_text, risk_spec_json, result_gz FROM rr_panels WHERE id = ?",
                            (panel_id,))
    assert (panel["status"], panel["decision_text"], panel["risk_spec_json"], panel["result_gz"]) == ("error", None, None, None)
    assert panel["error"].startswith("project_purged")
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_findings WHERE panel_id = ?", (panel_id,))["n"] == 0
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_panel_calls WHERE panel_id = ? AND result_gz IS NOT NULL",
                           (panel_id,))["n"] == 0
    issue = next(r for r in issues.issue_rows(store, key) if r["panel_id"] == panel_id)
    assert issue["outcome"] is None
