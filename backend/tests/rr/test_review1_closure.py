# 반대 검토 1차(review1) 완결 판정 몫 — 종합 뒤 쟁점 결과가 바뀐 판으로 C3 를 세우지 않고(M3), 확인이 판을 세우며(M4), 카드 없는 전문가가 섞인 영역의 깊이(M5), 다시 토의를 기다리는 쟁점의 잔여(H3)
"""원장은 생산자 경로다 — 대상은 라우트(rig.target), 검토는 가짜 검토 엔진의 루프, 쟁점 → 종합은 검토 잡 끝의 사슬이 세운 잡을
러너(가짜 쟁점 패널 엔진)와 종합 워커(가짜 요약 엔진)가 돈다. 사람의 쟁점 올리기는 routes.put_issue, 확인·취소는 REST
(routes.post_closure_ack · delete_closure_ack)다.
"""
from __future__ import annotations

import json

import pytest

from app import closure, config, entry, issues, registry, review_runner, routes, runner, synth, units
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.fake_summary_engine import FakeSummaryEngine
from tests.synth.issue_panel_engine import IssuePanelEngine

OWNER = rig.OWNER
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}
REARGUE = registry.REARGUE_LABEL


def _fake(**verdicts) -> FakeReviewEngine:
    fake = FakeReviewEngine(rig.packs(MIXED_ROSTER))
    fake.verdicts = {str(CARDS["K01"]["record_id"]): (verdicts.get("applies", "yes"), verdicts.get("judgement", "FAIL"))}
    fake.mechs = {str(CARDS["K01"]["record_id"]): ("interface.clearance", "")}
    return fake


# sim 영역에 카드로 본 전문가 하나와 카드 0장 전문가 하나 — 깊이가 카드로 본 전문가만 세는지(M5).
MIXED_ROSTER = tuple(r for r in rig.ROSTER if r["domain"] != "sim") + (
    {"key": "sim-carded-0", "domain": "sim", "relevance": 0.95}, {"key": rig.ZERO_CARDS, "domain": "sim", "relevance": 0.8})


def _issues(store, script=None) -> None:
    engine = IssuePanelEngine(store, script or {"*": {"severity": "치명", "judgement": "FAIL"}})
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
    with factories.routes_store(store):
        for item in [q for q in result["qualifiers"] if q["blocking"] and not q["acked"]]:
            routes.post_closure_ack(key, item["item"], routes.CloseAckBody(reason="이 잔여는 넘긴다",
                                                                           basis_hash=item["basis_hash"]),
                                    ident=factories.ident(OWNER))
    return closure.refresh(store, key)


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_issue_panel_cap=1, risk_issue_panel_hard_cap=1)
    return risk_store


def _chained(store) -> str:
    key = rig.target(store, MIXED_ROSTER)
    job_id = rig.job(store, key)
    rig.Rig(store, _fake()).finish(job_id)
    _issues(store)
    _synth(store)
    return key


def test_a_domain_whose_carded_experts_meet_depth_is_not_blocked_by_its_cardless_one(store):
    """M5(결정) — 깊이의 분모·분자는 카드로 본 전문가만 센다. 카드로 본 전문가와 카드 0장 전문가가 섞인 영역(sim)은 카드로 본
    전문가가 깊이를 채우면 막히지 않고, 카드 없는 전문가는 그 영역의 막지 않는 잔여 depth_no_cards 에 이름이 선다. 종전에는
    카드 없는 전문가가 분모에만 들어 모든 확인 뒤에도 C1 에 묶였다."""
    key = _chained(store)
    done = _ack_all(store, key)
    depth = done["detail"]["depth"]["sim"]
    assert (depth["active"], depth["have"], depth["need"]) == (1, 1, 1), depth
    assert done["c2"] is True and done["level"] == "C3", done["level_label"]
    gap = next(q for q in done["qualifiers"] if q["item"] == "depth_no_cards")
    assert gap["blocking"] is False and gap["mixed"] == {"sim": 1} and "sim(그중 1명)" in gap["label"]


def test_a_synthesis_older_than_the_issue_results_does_not_make_c3(store):
    """M3 — 종합 판(synth_done)이 선 뒤에 사람이 상한 밖 쟁점을 올려 패널이 판정하면 등록부가 바뀐다 — 셀 지문은 그대로라도 그 종합
    판은 낡았다(registry_hash). 확인을 다 해도 C3 가 아니고 '후속 낡음(보고서 판)' 이다. 새 종합이 서면 C3 다."""
    key = _chained(store)
    untried = [r for r in issues.issue_rows(store, key) if r["state"] == "untried_cap"]
    assert untried
    with factories.routes_store(store):
        for issue in untried:
            routes.put_issue(issue["issue_id"], routes.IssueActionBody(action="queue", reason="상한을 넘겨 본다"),
                             ident=factories.ident(OWNER))
    _issues(store)                                                     # 종합 잡이 사슬로 줄을 서지만 아직 돌지 않았다
    stale = _ack_all(store, key)
    assert stale["detail"]["fresh"]["report"] is False and stale["level"] != "C3"
    assert "후속 낡음(보고서 판)" in stale["level_label"]
    _synth(store)
    fresh = _ack_all(store, key)
    assert fresh["level"] == "C3" and fresh["detail"]["fresh"]["report"] is True


def test_an_ack_and_its_revocation_each_make_a_report_version_with_the_new_label(store):
    """M4(확인 몫) — 확인 · 확인 취소마다 판(trigger ack)이 서고 그 판의 표기가 지금 완결 표기다. 종전에는 확인 뒤 완결은 C3 인데
    보고서는 확인 전 판(종합 판)을 돌려줬다."""
    key = _chained(store)
    acked = _ack_all(store, key)
    report = synth.report_source(store, key)
    assert (report["trigger"], report["level_label"]) == ("ack", acked["level_label"])
    item = next(q for q in acked["qualifiers"] if q["blocking"])
    with factories.routes_store(store):
        routes.delete_closure_ack(key, item["item"], ident=factories.ident(OWNER))
    revoked = closure.cached(store, key)
    again = synth.report_source(store, key)
    assert again["version_no"] == report["version_no"] + 1
    assert (again["trigger"], again["level_label"]) == ("ack", revoked["level_label"])


def _reraised(store) -> tuple[str, str]:
    """상한 1 · 결과 쟁점 하나의 제기자가 다시 봐서 빠진 원장 — (대상, 다시 토의를 기다리는 쟁점 id)."""
    key = rig.target(store, MIXED_ROSTER)
    unit = units.load_units(store, key)[0]["unit_id"]
    job_id = rig.job(store, key, scope={"agents": [rig.SEAL, "mech-syn-0", "xd-syn-0", "xd-syn-1"], "unit_ids": [unit]})
    rig.Rig(store, _fake()).finish(job_id)
    registry.merge(store, key)
    issues.select_issues(store, key, selected_round=1)
    issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    _issues(store)
    decided = next(r for r in issues.issue_rows(store, key) if r["state"] == "resolved")
    cell = dict(store.query_one("SELECT unit_id, agent_key, state FROM rr_review_cells WHERE target_key = ? AND agent_key = ?"
                                " AND unit_id = ?", (key, "mech-syn-0", unit)))
    made = review_runner.dispose_cells(store, key, action="retry", rows=[cell], decided_by=OWNER, owner_sub=OWNER,
                                       note="다시 본다", force=True, start=True, consent=True, consent_source="web")
    rig.Rig(store, _fake(judgement="OK")).finish(made["job"]["job_id"])
    registry.merge(store, key)
    issues.select_issues(store, key, selected_round=2)
    after = {r["issue_id"]: r for r in issues.issue_rows(store, key)}[decided["issue_id"]]
    assert after["state"] == "resolved" and json.loads(after["reraised_json"] or "null"), after
    return key, decided["issue_id"]


def test_a_reraised_verdict_that_could_not_run_again_is_a_blocking_residual_and_the_guide_names_it(store):
    """H3(결정) — 상한에 자리가 없어 다시 돌지 못한 결과 쟁점(패널 판정 — 근거 바뀜)은 조용히 남지 않는다 — 완결의 막음 잔여
    issues_reraised 로 서고(확인으로 넘길 수 있다), 길잡이도 그 표기와 다시 올리는 길(PUT /issues/{id} queue)을 말한다."""
    from tests.test_review_mcp import _delegate, _project_with_source

    key, issue_id = _reraised(store)
    project_id = _project_with_source(store, key)
    result = closure.refresh(store, key)
    item = next((q for q in result["qualifiers"] if q["item"] == "issues_reraised"), None)
    assert item is not None and item["blocking"] is True and item["n"] == 1 and REARGUE in item["label"]
    assert REARGUE in result["level_label"]
    out = entry.next_step(_delegate(), project_id=project_id)
    assert any(REARGUE in n and issue_id in n for n in out["notes"]), out["notes"]
