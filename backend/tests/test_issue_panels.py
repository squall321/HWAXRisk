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

from app import brief, config, issues, registry, review_runner, routes, runner, units
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
    """S3-6 ⑧ — 끝난 쟁점은 근거(제기자·반대자·주장값)가 그대로면 다시 골라도 그대로다. 새 제기자가 서면(상한에 자리가 있을 때)
    queued 로 돌아가되 앞 패널의 결과는 새 패널이 바꿀 때까지 둔다(review1 H3 — 무엇이 바뀌었나는 reraised_json)."""
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
    assert (_issue(store, key, anchor)["state"], _issue(store, key, anchor)["reraised_json"]) == ("resolved", None)
    _review(store, key, ("mech-syn-0",), [unit], verdicts={"K01": ("yes", "FAIL")})
    registry.merge(store, key)
    _select(store, monkeypatch, tmp_path, key, cap=2)
    again = _issue(store, key, anchor)
    assert again["state"] == "queued" and again["basis_hash"] != resolved["basis_hash"] and again["outcome"] == "upheld"
    assert json.loads(again["reraised_json"])["raisers_added"] == ["mech-syn-0"]


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


# ---------------------------------------------------------------- 반대 검토 1차(review1)
REARGUE = "패널 판정 — 근거 바뀜, 다시 토의 필요"


def _retry_ok(store, key: str, agent: str, unit: str, *, verdict: str = "OK") -> None:
    """사람의 다시(셀 꾸러미 처분) — 그 셀을 K01 OK 로 다시 본다(제기자가 빠진다). verdict='FAIL' 이면 새 제기자가 선다."""
    cell = dict(store.query_one("SELECT unit_id, agent_key, state FROM rr_review_cells WHERE target_key = ? AND agent_key = ?"
                                " AND unit_id = ?", (key, agent, unit)))
    made = review_runner.dispose_cells(store, key, action="retry", rows=[cell], decided_by=OWNER, owner_sub=OWNER,
                                       note="다시 본다", force=True, start=True, consent=True, consent_source="web")
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {_rid("K01"): ("yes", verdict)}
    fake.mechs = {_rid("K01"): MECH} if verdict == "FAIL" else {}
    rig.Rig(store, fake).finish(made["job"]["job_id"])
    registry.merge(store, key)


def test_a_resolved_issue_keeps_its_panel_verdict_when_its_evidence_changes_and_the_cap_is_full(store, monkeypatch,
                                                                                                 tmp_path):
    """H3(결정) — 패널이 결과를 낸 쟁점은 다시 고를 때 상한으로 밀려나지 않고 결과·패널을 잃지 않는다. 근거가 바뀌면 결과를 두고
    reraised_json 에 무엇이 언제 바뀌었는지 적으며, 등록부는 패널 덮어쓰기(before_issue 포함)를 그대로 두고 '패널 판정 — 근거 바뀜,
    다시 토의 필요' 를 단다. 보고서는 그 쟁점을 미토의가 아니라 그 표기로 싣는다."""
    from app import synth

    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key, cap=1)
    _run_issues(store, config.settings, IssuePanelEngine(store, {"*": {"severity": "치명", "judgement": "FAIL"}}), key)
    decided = _issue(store, key, anchor)
    assert (decided["state"], decided["outcome"]) == ("resolved", "escalated")
    _retry_ok(store, key, "mech-syn-0", unit)
    issues.select_issues(store, key, selected_round=2)
    after = _issue(store, key, anchor)
    assert (after["state"], after["outcome"], after["panel_id"]) == ("resolved", "escalated", decided["panel_id"])
    assert after["outcome_json"] == decided["outcome_json"] and after["basis_hash"] == decided["basis_hash"]
    reraised = json.loads(after["reraised_json"])
    assert reraised["round"] == 2 and reraised["at"] >= decided["updated_at"] and reraised["basis_hash"] != after["basis_hash"]
    assert reraised["raisers_removed"] == ["mech-syn-0"]
    issues.select_issues(store, key, selected_round=3)                          # 같은 바뀐 근거 — 처음 적은 것 그대로
    assert json.loads(_issue(store, key, anchor)["reraised_json"]) == reraised
    registry.merge(store, key)
    row = _row(store, key, anchor)
    assert (row["severity"], row["judgement"]) == ("치명", "FAIL") and row["merged"]["before_issue"]["judgement"] == "WARNING"
    assert (row["merged"].get("issue_reraised") or {}).get("label") == REARGUE
    report = synth.report_source(store, key, version=synth.assemble_report(store, key, trigger="manual")["version_no"])
    summary = "\n".join(t for p in report["pages"] if p["kind"] == "summary" for b in synth.BLOCKS for t in p["blocks"][b])
    line = next(t for t in summary.split("\n") if f"reg:{anchor}" in t)
    assert REARGUE in line and "미토의" not in line


def test_a_reraised_resolved_issue_goes_back_to_a_panel_when_the_cap_has_room_and_the_new_verdict_replaces_the_old(
        store, monkeypatch, tmp_path):
    """H3(결정) — 상한에 자리가 있으면 근거가 바뀐 결과 쟁점은 새 패널로 다시 줄을 선다. 그동안 등록부는 옛 패널 덮어쓰기를 그대로
    두고, 새 패널의 결과가 옛 결과를 바꾼다(그때 다시 토의 표기는 내려간다)."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key, cap=1)
    _run_issues(store, config.settings, IssuePanelEngine(store, {"*": {"severity": "치명", "judgement": "FAIL"}}), key)
    first_panel = _issue(store, key, anchor)["panel_id"]
    _retry_ok(store, key, "mech-syn-0", unit)
    _select(store, monkeypatch, tmp_path, key, cap=2)
    queued = _issue(store, key, anchor)
    assert (queued["state"], queued["outcome"], queued["panel_id"]) == ("queued", "escalated", first_panel)
    registry.merge(store, key)
    assert (_row(store, key, anchor)["severity"], _row(store, key, anchor)["judgement"]) == ("치명", "FAIL")
    issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    job = runner.claim_next_job(store, config.settings)
    panel = issues.plan_issue_panel(store, key, job=job)                        # 새 패널이 편성된 동안(panel_id 가 새 패널)
    assert _issue(store, key, anchor)["panel_id"] == panel["id"]
    registry.merge(store, key)
    assert (_row(store, key, anchor)["severity"], _row(store, key, anchor)["judgement"]) == ("치명", "FAIL")
    runner._release_panel(store, panel)
    _run_issues_existing(store, IssuePanelEngine(store, {"*": "unparseable"}), limit=1)   # 결정문을 못 읽어도 앞 결과는 둔다
    held = _issue(store, key, anchor)
    assert (held["state"], held["outcome"], held["charged"]) == ("queued", "escalated", 1)
    _run_issues_existing(store, IssuePanelEngine(store, {"*": {"severity": "중대", "judgement": "WARNING"}}))
    done = _issue(store, key, anchor)
    assert done["state"] == "resolved" and done["panel_id"] != first_panel and done["reraised_json"] is None
    assert json.loads(done["outcome_json"])["panel_id"] == done["panel_id"]
    row = _row(store, key, anchor)
    assert (row["severity"], row["judgement"]) == ("중대", "WARNING") and "issue_reraised" not in row["merged"]


def test_a_human_queue_or_skip_survives_reselection_even_above_the_cap(store, monkeypatch, tmp_path):
    """L1(결정) — 사람의 올리기·건너뛰기(status_source='human')는 자동 다시 고르기보다 앞선다 — 상한 밖으로 올린 쟁점도 다시 고르기가
    untried_cap 으로 되돌리지 않는다(상한은 자동 선정의 몫이다)."""
    from tests import factories

    key, unit_ids = _ledger(store, units_n=2)
    _select(store, monkeypatch, tmp_path, key, cap=1)
    rows = issues.issue_rows(store, key)
    over = next(r for r in rows if r["state"] == "untried_cap")
    with factories.routes_store(store):
        routes.put_issue(over["issue_id"], routes.IssueActionBody(action="queue", reason="상한을 넘겨 본다"),
                         ident=factories.ident(OWNER))
    issues.select_issues(store, key, selected_round=2)
    kept = next(r for r in issues.issue_rows(store, key) if r["issue_id"] == over["issue_id"])
    assert (kept["state"], kept["status_source"]) == ("queued", "human")
    _run_issues_existing(store, IssuePanelEngine(store))                       # 사람이 올린 쟁점을 패널이 판정했다 — 결정은 끝났다
    judged = next(r for r in issues.issue_rows(store, key) if r["issue_id"] == over["issue_id"])
    assert (judged["state"], judged["status_source"]) == ("resolved", "code")


def test_an_in_flight_issue_of_a_cancelled_job_is_untried_not_left_queued(store, monkeypatch, tmp_path):
    """H4 — 사람이 쟁점 잡을 취소하는 사이 도는 패널이 있으면, 다른 자리의 집기가 잡을 cancelled 로 닫고 대기 쟁점을 미토의로 옮긴
    뒤 그 패널이 닫히며 쟁점을 대기로 되돌렸다 — 살아 있는 잡이 없어 영영 '쟁점 진행' 이었다. 잡이 살아 있지 않으면 놓인 쟁점은
    untried_cap(chain_cancelled) 다."""
    key, unit_ids = _ledger(store, units_n=2)
    _select(store, monkeypatch, tmp_path, key, cap=2)
    job = issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    claimed = runner.claim_next_job(store, config.settings)
    panel = issues.plan_issue_panel(store, key, job=claimed)
    issues.start_issue_panel(store, panel["id"])
    runner.cancel_job(store, job["job_id"], by=OWNER)
    assert runner.claim_next_job(store, config.settings) is None                       # 둘째 자리 — 잡을 cancelled 로 닫는다
    runner._release_panel(store, panel)                                                # 도는 패널이 스트림을 닫고 놓인다
    issue = next(r for r in issues.issue_rows(store, key) if r["issue_id"] == panel["issue_id"])
    assert (issue["state"], issue["state_reason"]) == ("untried_cap", "chain_cancelled")
    assert [r["state"] for r in issues.issue_rows(store, key) if r["state"] in ("queued", "planned", "running")] == []


def test_a_pat_failure_pauses_the_issue_job_with_a_credential_hold_and_keeps_the_issues_queued(store, monkeypatch,
                                                                                                tmp_path):
    """M1(결정) — 쟁점 잡의 자격 실패(PatUnavailable)는 잡을 보류 credential 로 멈춘다(검토 잡과 같다). 대기 쟁점은 대기 그대로(차감
    없음)이고 사슬은 멈춘 동안 종합으로 넘어가지 않는다. 다시 이어 돌면 끝까지 가고 그때 종합이 선다."""
    from app import chain

    key, unit_ids = _ledger(store, units_n=2)
    _select(store, monkeypatch, tmp_path, key, cap=2)
    queued = sorted(r["issue_id"] for r in issues.issue_rows(store, key) if r["state"] == "queued")
    job = issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    engine = IssuePanelEngine(store, {"*": runner.PatUnavailable("koo@example.com 의 PAT 가 만료됐다(가짜)")})
    claimed = runner.claim_next_job(store, config.settings, engine=engine)
    out = runner.run_panel(store, config.settings, engine, claimed)
    row = store.query_one("SELECT state, hold_code, error FROM rr_jobs WHERE id = ?", (job["job_id"],))
    assert (row["state"], row["hold_code"]) == ("paused", "credential") and row["error"].startswith("pat_unavailable: ")
    assert out["status"] == "paused"
    issues_now = {r["issue_id"]: r for r in issues.issue_rows(store, key)}
    assert sorted(i for i, r in issues_now.items() if r["state"] == "queued") == queued
    assert all(issues_now[i]["charged"] == 0 for i in queued)
    assert chain.sweep(store)["made"] == []
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_jobs WHERE target_key = ? AND mode = 'synth'", (key,))["n"] == 0
    runner.resume_job(store, job["job_id"], by=OWNER)
    assert store.query_one("SELECT hold_code FROM rr_jobs WHERE id = ?", (job["job_id"],))["hold_code"] is None
    _run_issues_existing(store, IssuePanelEngine(store, {"*": runner.EngineError("엔진이 터졌다")}), limit=2)
    assert store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job["job_id"],))["state"] != "failed"   # 자격 보류는 세지 않는다
    _run_issues_existing(store, IssuePanelEngine(store))
    assert store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job["job_id"],))["state"] == "completed"


def _run_issues_existing(store, engine, *, limit: int = 10) -> None:
    for _ in range(limit):
        job = runner.claim_next_job(store, config.settings, engine=engine)
        if job is None:
            return
        runner.run_panel(store, config.settings, engine, job)


def test_an_issue_job_that_really_fails_releases_its_queued_issues_as_untried(store, monkeypatch, tmp_path):
    """M1(결정) — 정말로 실패로 끝난 쟁점 잡(배선 결손 따위)은 남은 대기 쟁점을 untried_cap(job_failed) 로 놓아 미토의로 보이게 한다."""
    from types import SimpleNamespace

    key, unit_ids = _ledger(store, units_n=2)
    _select(store, monkeypatch, tmp_path, key, cap=2)
    queued = [r["issue_id"] for r in issues.issue_rows(store, key) if r["state"] == "queued"]
    assert queued
    issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    job = runner.claim_next_job(store, config.settings)
    out = runner.run_panel(store, config.settings, IssuePanelEngine(store), job, registry_mod=SimpleNamespace())
    assert out["status"] == "missing_interface"
    rows = {r["issue_id"]: r for r in issues.issue_rows(store, key)}
    assert {(rows[i]["state"], rows[i]["state_reason"]) for i in queued} == {("untried_cap", "job_failed")}


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


@pytest.mark.parametrize("when", ["answer", "before_persist"])
def test_an_issue_panel_that_ends_after_a_purge_writes_nothing_back(store, monkeypatch, tmp_path, when):
    """L6(결정) — 폐기(purge) 뒤에 끝난 쟁점 패널의 결과는 버린다 — 패널 원문(결정문 · 결과 원문 · 도구 호출)도, 쟁점 패널 finding 도,
    쟁점의 결과도 쓰지 않는다(같은 트랜잭션에서 과제의 폐기 상태를 본다). 패널에는 까닭만 남는다. 엔진이 답을 낸 뒤 원장에 앉히기
    직전(종료 모델 재확인 사이)에 폐기돼도 같다."""
    from tests import factories

    key, (unit,) = _ledger(store)
    _select(store, monkeypatch, tmp_path, key, cap=1)
    project_id = store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]
    code = store.query_one("SELECT code FROM rr_projects WHERE id = ?", (project_id,))["code"]

    def purge() -> None:
        with factories.routes_store(store):
            routes.purge_project(project_id, routes.PurgeBody(code=code, reason="폐기 시험"), ident=factories.ident(OWNER))

    class PurgingEngine(IssuePanelEngine):
        answered = False

        def run(self, delib_opts, *, owner_sub=None):
            out = super().run(delib_opts, owner_sub=owner_sub)
            self.answered = True
            if when == "answer":
                purge()
            return out

        def health(self):
            if when == "before_persist" and self.answered and not getattr(self, "purged", False):
                self.purged = True
                purge()
            return super().health()

    results = _run_issues(store, config.settings, PurgingEngine(store, {"*": {"severity": "치명", "judgement": "FAIL"}}), key)
    panel_id = results[0]["panel_id"]
    assert results[0]["status"] == "purged"
    panel = store.query_one("SELECT status, error, decision_text, risk_spec_json, result_gz FROM rr_panels WHERE id = ?",
                            (panel_id,))
    assert (panel["status"], panel["decision_text"], panel["risk_spec_json"]) == ("error", None, None)
    # 결과 원문(result_gz)은 폐기 전에 엔진이 답했으면 그때 적힌 것이다 — 폐기가 그 열을 비우는 것은 폐기 쪽(routes.PURGE_BLANK_SQL,
    # 둘째 단계) 몫이다. 폐기 뒤의 답은 적지 않는다.
    if when == "answer":
        assert panel["result_gz"] is None
    assert panel["error"].startswith("project_purged")
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_findings WHERE panel_id = ?", (panel_id,))["n"] == 0
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_panel_calls WHERE panel_id = ? AND result_gz IS NOT NULL",
                           (panel_id,))["n"] == 0
    issue = next(r for r in issues.issue_rows(store, key) if r["panel_id"] == panel_id)
    assert (issue["outcome"], issue["state"], issue["state_reason"]) == (None, "untried_cap", "chain_cancelled")


def test_a_requeued_resolved_issue_released_without_a_live_job_returns_to_its_verdict(store, monkeypatch, tmp_path):
    """H3 · H4 — 다시 줄을 선 결과 쟁점은 잡이 취소돼 놓여도(도는 패널이 닫힌 뒤든 대기 중이든) 미토의가 아니라 그 결과 쟁점으로
    돌아간다 — 결과를 잃지 않는다. 다시 줄을 섰다가 후보에서 빠져도 물러나지(withdrawn) 않고 결과 쟁점으로 돌아간다."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key, cap=1)
    _run_issues(store, config.settings, IssuePanelEngine(store, {"*": {"severity": "치명", "judgement": "FAIL"}}), key)
    _retry_ok(store, key, "mech-syn-0", unit)
    _select(store, monkeypatch, tmp_path, key, cap=2)
    assert _issue(store, key, anchor)["state"] == "queued"
    job = issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    claimed = runner.claim_next_job(store, config.settings)
    panel = issues.plan_issue_panel(store, key, job=claimed)
    issues.start_issue_panel(store, panel["id"])
    runner.cancel_job(store, job["job_id"], by=OWNER)
    assert runner.claim_next_job(store, config.settings) is None
    runner._release_panel(store, panel)
    back = _issue(store, key, anchor)
    assert (back["state"], back["outcome"]) == ("resolved", "escalated")
    _select(store, monkeypatch, tmp_path, key, cap=3)                           # 자리가 있어 다시 줄을 선다
    queued = _issue(store, key, anchor)
    assert queued["state"] == "queued"
    _retry_ok(store, key, "xd-syn-0", unit, verdict="FAIL")                   # 줄을 선 채 근거가 또 바뀐다 — 새 근거만 다시 적는다
    issues.select_issues(store, key, selected_round=4)
    refreshed = _issue(store, key, anchor)
    assert (refreshed["state"], refreshed["outcome"]) == ("queued", "escalated")
    assert refreshed["basis_hash"] != queued["basis_hash"] and "xd-syn-0" in [r["agent_key"] for r in refreshed["basis"]["raisers"]]
    _retry_ok(store, key, "xd-syn-0", unit)
    _retry_ok(store, key, rig.SEAL, unit)                                       # 마지막 제기자도 OK — 후보에서 빠진다
    issues.select_issues(store, key, selected_round=5)
    gone = _issue(store, key, anchor)
    assert (gone["state"], gone["outcome"]) == ("resolved", "escalated")


# ---------------------------------------------------------------- 조합 검토 M1 · M2 · L1 · L2 · L3(D-52 — 다시 토의)
REPANEL_FAILED = REARGUE + "(새 패널 결정 못 함)"


def _escalated_then_reraised(store, monkeypatch, tmp_path, *, requeue: bool) -> tuple[str, str, str, IssuePanelEngine]:
    """패널이 치명/FAIL 로 올린 쟁점의 제기자가 빠진다(근거 바뀜) — requeue 면 상한에 자리가 있어 다시 줄을 선다. (대상, 닻, 옛 패널, 엔진)."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key, cap=1)
    engine = IssuePanelEngine(store, {"*": {"severity": "치명", "judgement": "FAIL"}})
    _run_issues(store, config.settings, engine, key)
    first = _issue(store, key, anchor)
    assert (first["state"], first["outcome"]) == ("resolved", "escalated")
    _retry_ok(store, key, "mech-syn-0", unit)
    _select(store, monkeypatch, tmp_path, key, cap=2 if requeue else 1)
    assert _issue(store, key, anchor)["state"] == ("queued" if requeue else "resolved")
    return key, anchor, str(first["panel_id"]), engine


def test_an_unparseable_resubmission_with_no_live_job_does_not_leave_the_issue_queued(store, monkeypatch, tmp_path):
    """M1 — 쟁점 잡이 끝난 뒤 그 패널을 읽을 수 없는 결정문으로 다시 내도(POST /panels/{id}/complete) 쟁점이 잡 없는 대기로 남지
    않는다 — 다시 줄 세우는 모든 길이 살아 있는 잡을 본다. 앞 결과가 있으면 그 결과 쟁점으로 돌아간다."""
    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key)
    engine = IssuePanelEngine(store)
    _run_issues(store, config.settings, engine, key)
    decided = _issue(store, key, anchor)
    assert decided["state"] == "resolved"
    bad = IssuePanelEngine(store, {decided["issue_id"]: "unparseable"}).run(engine.calls[-1])
    _resubmit(str(decided["panel_id"]), bad)
    after = _issue(store, key, anchor)
    assert (after["state"], after["outcome"]) == ("resolved", decided["outcome"])


def test_a_failed_repanel_keeps_the_old_verdict_and_says_so_and_a_requeue_resets_charged(store, monkeypatch, tmp_path):
    """M2 — 다시 줄을 선 결과 쟁점의 새 패널이 결정하지 못하면(읽을 수 없는 결정문 둘) 옛 판정이 남는다 — 등록부 덮어쓰기(before_issue
    포함)와 보고서 줄이 옛 판정 그대로고 '패널 판정 — 근거 바뀜, 다시 토의 필요(새 패널 결정 못 함)' 로 보인다. 다시 줄 세우기는
    charged 를 0 으로 돌린다(앞 패널의 실패를 새 근거의 몫으로 세지 않는다)."""
    from app import synth

    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key, cap=1)
    issue_id = _issue(store, key, anchor)["issue_id"]
    engine = IssuePanelEngine(store, {issue_id: "unparseable"})
    _run_issues(store, config.settings, engine, key, limit=1)
    assert _issue(store, key, anchor)["charged"] == 1
    engine.script[issue_id] = {"severity": "치명", "judgement": "FAIL"}
    _run_issues(store, config.settings, engine, key)
    assert (_issue(store, key, anchor)["outcome"], _issue(store, key, anchor)["charged"]) == ("escalated", 1)
    _retry_ok(store, key, "mech-syn-0", unit)
    _select(store, monkeypatch, tmp_path, key, cap=3)                           # 상한은 이 대상이 돌린 패널 둘을 센다
    assert (_issue(store, key, anchor)["state"], _issue(store, key, anchor)["charged"]) == ("queued", 0)
    _run_issues_existing(store, IssuePanelEngine(store, {"*": "unparseable"}), limit=1)
    assert (_issue(store, key, anchor)["state"], _issue(store, key, anchor)["charged"]) == ("queued", 1)
    _run_issues_existing(store, IssuePanelEngine(store, {"*": "unparseable"}), limit=1)
    held = _issue(store, key, anchor)
    assert (held["state"], held["outcome"]) == ("resolved", "escalated")
    assert json.loads(held["reraised_json"]).get("new_panel_failed")
    registry.merge(store, key)
    row = _row(store, key, anchor)
    assert (row["severity"], row["judgement"]) == ("치명", "FAIL") and row["merged"]["before_issue"]["judgement"] == "WARNING"
    assert row["merged"]["issue_reraised"]["label"] == REPANEL_FAILED
    report = synth.report_source(store, key, version=synth.assemble_report(store, key, trigger="manual")["version_no"])
    summary = "\n".join(t for p in report["pages"] if p["kind"] == "summary" for b in synth.BLOCKS for t in p["blocks"][b])
    line = next(t for t in summary.split("\n") if f"reg:{anchor}" in t)
    assert REPANEL_FAILED in line and "판정 못 함" not in line.replace(REPANEL_FAILED, "")


def test_resubmitting_the_old_panel_does_not_clear_the_reargue_mark_or_dequeue(store, monkeypatch, tmp_path):
    """L1 — 근거가 바뀌어 다시 줄을 선 쟁점에 옛 패널을 다시 내도(POST /panels/{id}/complete) 다시 토의 표기가 내려가지 않고 대기에서
    빠지지 않는다 — 표기는 새 패널이 결정할 때만 내려간다(옛 판정을 새 근거에 붙이지 않는다)."""
    key, anchor, old_panel, engine = _escalated_then_reraised(store, monkeypatch, tmp_path, requeue=True)
    before = _issue(store, key, anchor)
    again = IssuePanelEngine(store, {"*": {"severity": "중대", "judgement": "WARNING"}}).run(engine.calls[-1])
    _resubmit(old_panel, again)
    after = _issue(store, key, anchor)
    assert (after["state"], after["outcome"], after["outcome_json"]) == ("queued", "escalated", before["outcome_json"])
    assert after["reraised_json"] == before["reraised_json"]


def test_evidence_back_at_the_panel_basis_clears_the_mark_and_is_not_queued_again(store, monkeypatch, tmp_path):
    """L2 — 바뀐 근거가 패널 때 근거로 돌아오면 다시 토의 표기가 내려가고 상한에 자리가 있어도 다시 줄 서지 않는다(같은 패널을 또 돌리지
    않는다). 다시 줄을 서 있던 쟁점도 옛 판정의 결과 쟁점으로 돌아간다."""
    for requeue in (False, True):
        store.execute("DELETE FROM rr_issues")
        key, anchor, old_panel, _engine = _escalated_then_reraised(store, monkeypatch, tmp_path, requeue=requeue)
        unit = _issue(store, key, anchor)["unit_id"]
        _retry_ok(store, key, "mech-syn-0", unit, verdict="FAIL")              # 빠졌던 제기자가 돌아온다 — 패널 때 근거
        _select(store, monkeypatch, tmp_path, key, cap=3)
        back = _issue(store, key, anchor)
        assert (back["state"], back["outcome"], back["reraised_json"], back["panel_id"]) == (
            "resolved", "escalated", None, old_panel), requeue


def test_the_reargue_mark_rides_the_issue_rows_and_the_summary_input(store, monkeypatch, tmp_path):
    """L3 — 다시 토의 표기는 쟁점 행(REST · MCP 같은 함수)과 요약 입력(등록부 행 줄 · 쟁점 블록)에도 선다 — 종전에는 그냥
    resolved/escalated 로 보였다."""
    from app import closure, synth

    key, anchor, _old, _engine = _escalated_then_reraised(store, monkeypatch, tmp_path, requeue=False)
    registry.merge(store, key)
    (row,) = [r for r in routes.issues_payload(key, owner_sub=OWNER)["rows"] if r["anchor_cluster_key"] == anchor]
    assert (row.get("reargue") or {}).get("label") == REARGUE
    built = synth.summary_input(store, key, "target", key, limits=None, counts=closure.cell_counts(store, key))
    text = json.dumps(built["summary"], ensure_ascii=False)
    issue_lines = next(b["text"] for b in built["summary"]["blocks"] if b["name"] == "issues")
    assert REARGUE in next(line for line in issue_lines.split("\n") if f"reg:{anchor}" in line)
    assert REARGUE in next(r["text"] for r in built["summary"]["rows"] if r["ref"] == f"reg:{anchor}"), text[:500]


def test_a_repanel_that_judges_undetermined_keeps_the_old_verdict_and_says_so(store, monkeypatch, tmp_path):
    """M2 — 다시 줄을 선 결과 쟁점의 새 패널이 판정 못 함(undetermined)을 내도 옛 판정(outcome · 그 판정의 패널)이 남고 표기에
    '새 패널 결정 못 함' 이 붙는다 — 결정하지 못한 패널은 옛 판정을 지우지 않는다."""
    key, anchor, old_panel, _engine = _escalated_then_reraised(store, monkeypatch, tmp_path, requeue=True)
    _run_issues(store, config.settings, IssuePanelEngine(store, {"*": {"severity": "치명", "judgement": "undetermined"}}), key,
                limit=1)
    held = _issue(store, key, anchor)
    assert (held["state"], held["outcome"], json.loads(held["outcome_json"])["panel_id"]) == ("resolved", "escalated", old_panel)
    assert json.loads(held["reraised_json"])["new_panel_failed"]["reason"] == "no_decision"
    registry.merge(store, key)
    assert _row(store, key, anchor)["merged"]["issue_reraised"]["label"] == REPANEL_FAILED


def test_a_charged_release_at_the_limit_keeps_the_old_verdict(store, monkeypatch, tmp_path):
    """M2 — 내용 탓 놓기(release_issue charge)가 한도에 닿아도 판정이 있던 쟁점은 옛 판정을 둔다(지금 러너는 차감 없이 놓지만 함수의
    약속이 같아야 한다 — 차감으로 부르는 날 M2 가 조용히 돌아오지 않게)."""
    key, anchor, _old, _engine = _escalated_then_reraised(store, monkeypatch, tmp_path, requeue=True)
    issue_id = _issue(store, key, anchor)["issue_id"]
    store.execute("UPDATE rr_issues SET state = 'running', panel_id = 'p-new', charged = 1 WHERE issue_id = ?", (issue_id,))
    out = issues.release_issue(store, "p-new", charge=True, reason="engine_content")
    held = _issue(store, key, anchor)
    assert (out["state"], held["state"], held["outcome"]) == ("resolved", "resolved", "escalated")
    assert json.loads(held["reraised_json"])["new_panel_failed"]["reason"] == "engine_content"


def test_a_human_requeue_resets_charged(store, monkeypatch, tmp_path):
    """M2 — 사람이 끝난 쟁점을 다시 줄 세우면(PUT /issues queue) charged 가 0 이다 — 앞 시도의 실패를 새 회차의 몫으로 세지 않는다."""
    from tests import factories

    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key, cap=1)
    _run_issues(store, config.settings, IssuePanelEngine(store, {"*": "unparseable"}), key, limit=2)
    spent = _issue(store, key, anchor)
    assert (spent["state"], spent["charged"]) == ("inconclusive", 2)
    with factories.routes_store(store):
        routes.put_issue(spent["issue_id"], routes.IssueActionBody(action="queue", reason="다시 본다"),
                         ident=factories.ident(OWNER))
    again = _issue(store, key, anchor)
    assert (again["state"], again["charged"]) == ("queued", 0)


# ---------------------------------------------------------------- I6 — 제기 · 반대 측 카드 절이 번갈아 선다(재설계 D-57)
def _side_cards(raisers: list[tuple[str, str]], opposers: list[tuple[str, str]]) -> list[dict]:
    """`_issue_side` 가 cards_out 에 싣는 꼴 — 제기 측(SEAL)과 반대 측(xd-syn-0)이 인용한 (별칭, 절)."""
    return ([{"agent_key": SEAL, "record_id": _rid(a), "section_id": s, "quote_ok": 1, "side": "제기"} for a, s in raisers]
            + [{"agent_key": "xd-syn-0", "record_id": _rid(a), "section_id": s, "quote_ok": 1, "side": "반대"}
               for a, s in opposers])


def _tags(text: str) -> list[str]:
    import re  # noqa: PLC0415
    return re.findall(r"\[card:([^\]#]+)#(\w+)\]", text)


def test_the_cited_card_sections_alternate_between_raisers_and_opposers(store):
    """제기 측을 다 세운 뒤 반대 측을 세우면 칸이 넘칠 때 반대 측 카드가 먼저 빠진다 — 측마다 차례는 그대로 두고 번갈아 세운다."""
    key, _units = _ledger(store)
    cards = _side_cards([("K01", "1"), ("K03", "1"), ("K05", "1")], [("K04", "1"), ("K06", "1")])
    item, scope = brief._issue_i6(store, key, cards)
    want = [(_rid(a), s) for a, s in (("K01", "1"), ("K04", "1"), ("K03", "1"), ("K06", "1"), ("K05", "1"))]
    assert [tuple(t) for t in _tags(item["result"])] == want
    assert set(scope) == {_rid(a) for a in ("K01", "K03", "K04", "K05", "K06")}, "인용 검증 범위는 순서와 무관하게 전부"


def test_an_overflowing_i6_keeps_the_opposers_and_skips_only_the_long_section(store, monkeypatch, tmp_path):
    """좁은 창에서 I6 이 넘친다 — ① 반대 측 절이 남는다(번갈아 선다) ② 칸보다 긴 절 하나는 그 줄만 빠지고 뒤의 절은 남는다
    (종전은 거기서 멈춰 틀 줄과 '…(n줄 생략)' 만 남았다) ③ 빠진 줄 수는 절단 원장(meta.clipped.I6)에 그대로 선다."""
    from app import cardpack  # noqa: PLC0415

    key, (unit,) = _ledger(store)
    anchor = _k01_anchor(store, key, unit)
    _select(store, monkeypatch, tmp_path, key)
    issue = _issue(store, key, anchor)
    seats = issues.seats_for(store, key, issue)
    raisers = [("K01", "1"), ("K01", "2"), ("K01", "3"), ("K03", "1"), ("K05", "1")]
    opposers = [("K04", "1"), ("K06", "1")]

    def fake_side(_store, _key, item_key, _people, *, role, judgement, cards_out):
        cards_out += _side_cards(raisers, []) if role == "제기" else _side_cards([], opposers)
        return {"key": item_key, "args": "-", "result": brief._body("issue_verdicts", [f"{role} 판정 줄"])}

    real_load = cardpack.load_for
    long_rid = _rid("K01")

    def load_with_a_long_first_section(st, tk, agent):
        pack = real_load(st, tk, agent)
        if pack is None or agent != SEAL:
            return pack
        cards = {rid: dict(card) for rid, card in pack.record_cards.items()}
        cards[long_rid]["sections"] = [({**s, "text": "긴 절 " * 400} if str(s.get("sid")) == "1" else s)
                                       for s in cards[long_rid].get("sections") or ()]
        import types  # noqa: PLC0415
        return types.SimpleNamespace(record_cards=cards)

    monkeypatch.setattr(brief, "_issue_side", fake_side)
    monkeypatch.setattr(cardpack, "load_for", load_with_a_long_first_section)
    monkeypatch.setitem(brief.ISSUE_CAPS, "I6", 900)          # 좁은 창 흉내 — 보통 절 서너 줄만 든다
    built = brief.build_issue_brief(store, key, issue, seats=seats)
    i6 = next(e["result"] for e in built["evidence"] if e["key"] == "I6")
    tags = [tuple(t) for t in _tags(i6)]
    assert (long_rid, "1") not in tags, "칸보다 긴 절은 빠진다"
    assert (_rid("K04"), "1") in tags and (_rid("K06"), "1") in tags, f"반대 측 절이 남는다 — {tags}"
    assert tags[:2] == [(_rid("K04"), "1"), (long_rid, "2")], "긴 줄 하나만 건너뛰고 차례대로 잇는다"
    clipped = built["meta"]["clipped"]["I6"]
    assert clipped["omitted"] >= 1 and clipped["kept"] + clipped["omitted"] == clipped["lines"]
    assert i6.rstrip().endswith(f"…({clipped['omitted']}줄 생략)")


def test_clip_lines_n_skip_long_jumps_one_line_but_never_the_frame():
    text = "\n".join(["틀 줄", "x" * 100, "가", "나"])
    assert brief.clip_lines_n(text, 30) == ("틀 줄\n…(3줄 생략)", 3), "종전 — 긴 줄에서 멈춘다"
    assert brief.clip_lines_n(text, 30, skip_long=True) == ("틀 줄\n가\n나\n…(1줄 생략)", 1)
    head_long = "\n".join(["y" * 100, "가"])
    assert brief.clip_lines_n(head_long, 30, skip_long=True) == brief.clip_lines_n(head_long, 30), "틀 줄이 안 들면 종전처럼"
