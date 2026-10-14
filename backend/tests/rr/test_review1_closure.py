# 반대 검토 1차(review1) 완결 판정 몫 — 종합 뒤 쟁점 결과가 바뀐 판으로 C3 를 세우지 않고(M3), 확인이 판을 세우며(M4), 카드 없는 전문가가 섞인 영역의 깊이(M5), 다시 토의를 기다리는 쟁점의 잔여(H3)
"""원장은 생산자 경로다 — 대상은 라우트(rig.target), 검토는 가짜 검토 엔진의 루프, 쟁점 → 종합은 검토 잡 끝의 사슬이 세운 잡을
러너(가짜 쟁점 패널 엔진)와 종합 워커(가짜 요약 엔진)가 돈다. 사람의 쟁점 올리기는 routes.put_issue, 확인·취소는 REST
(routes.post_closure_ack · delete_closure_ack)다.
"""
from __future__ import annotations

import pytest

from app import closure, config, issues, routes, runner, synth
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.fake_summary_engine import FakeSummaryEngine
from tests.synth.issue_panel_engine import IssuePanelEngine

OWNER = rig.OWNER
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}


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
