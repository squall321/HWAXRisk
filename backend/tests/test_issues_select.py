# 쟁점 선정(재설계 M3 S3-6) — hold 가 가린 FAIL·단독 중대·갈린 판정을 코드가 고르고 상한 밖도 행으로 남기는지 본다
"""입력은 생산자다 — 대상·단위는 합성 쌍 → 라우트, 카드 판정·finding·셀 신고는 가짜 엔진을 꽂은 M2 검토 루프
(tests/synth/review_rig.py), 등록부는 registry.merge 다. 전문가마다 같은 카드 묶음에 FAIL·WARNING·OK 를 섞는다(대본은 잡마다).
끝난 쟁점의 다시 고르기(⑧)와 회차를 넘는 상한 누적(⑨)은 쟁점 패널(S3-7)이 쟁점을 끝내야 서므로 tests/test_issue_panels.py 가 본다.
"""
from __future__ import annotations

import random

import pytest

from app import issues, registry, routes, units
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

OWNER = rig.OWNER
SEAL = rig.SEAL
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}
MECH = ("interface.clearance", "")
CODE = "interface.clearance"


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _rid(alias: str) -> str:
    return str(CARDS[alias]["record_id"])


def _review(store, key: str, experts, unit_ids, *, verdicts: dict[str, tuple[str, str]] | None = None,
            invented: bool = False, seen: tuple[str, ...] = ()) -> None:
    """그 전문가들이 단위들을 끝까지 — 대본에 없는 카드는 applies=yes·OK, 대본 카드는 같은 메커니즘을 단다."""
    job_id = rig.job(store, key, scope={"agents": list(experts), "unit_ids": list(unit_ids)})
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {_rid(a): v for a, v in (verdicts or {}).items()}
    fake.mechs = {_rid(a): MECH for a in (verdicts or {})}
    fake.seen = list(seen)
    if invented:
        fake.invented_quote = set(verdicts or ())
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)


def _units(store, key: str) -> list[str]:
    return [u["unit_id"] for u in units.load_units(store, key)]


def _k01_row(store, key: str, unit_id: str) -> dict:
    """그 단위에서 K01 카드 대조 finding 이 모인 리스크 행."""
    registry.merge(store, key)
    fids = {str(r["finding_id"]) for r in store.query(
        "SELECT finding_id FROM rr_findings WHERE target_key = ? AND unit_id = ? AND source_kind = 'card_review'"
        " AND mechanism = 'interface'", (key, unit_id))}
    (row,) = [r for r in registry.registry_rows(store, key)
              if r["direction"] == "risk" and fids & set(r["merged"].get("member_ids") or ())]
    return row


def _issue(store, key: str, anchor: str) -> dict:
    (row,) = [r for r in issues.issue_rows(store, key) if r["anchor_cluster_key"] == anchor]
    return row


# ---------------------------------------------------------------- 유형 · 등급
def test_a_fail_the_hold_hid_is_a_held_fail_p1_issue_with_the_ok_reviewers_as_opposers(store):
    """① 둘이 FAIL(인용 대조 통과)로 본 클러스터는 등록부 값이 hold 로 중대/WARNING 이어도 held_fail·P1 이다. 같은 단위·같은 변경
    줄에 OK 를 낸 둘이 반대 측이다(제기자 자신의 다른 OK 는 반대가 아니다)."""
    key = rig.target(store)
    unit = _units(store, key)[0]
    _review(store, key, (SEAL, "mech-syn-0"), [unit], verdicts={"K01": ("yes", "FAIL")})
    _review(store, key, ("xd-syn-0", "xd-syn-1"), [unit])
    row = _k01_row(store, key, unit)
    assert (row["severity"], row["judgement"]) == ("중대", "WARNING")
    out = issues.select_issues(store, key, selected_round=1)
    issue = _issue(store, key, row["cluster_key"])
    assert "held_fail" in issue["types"] and issue["p_class"] == "P1" and issue["state"] == "queued"
    assert [r["agent_key"] for r in issue["basis"]["raisers"]] == sorted((SEAL, "mech-syn-0"))
    assert [o["agent_key"] for o in issue["basis"]["opposers"]] == ["xd-syn-0", "xd-syn-1"]
    assert issue["basis"]["claimed"]["judgement"] == "FAIL" and issue["basis"]["distribution"]["opposers"] == 2
    assert issue["issue_id"] == issues.issue_id_of(key, row["cluster_key"]) and issue["unit_id"] == unit
    assert out["by_class"]["P1"] >= 1 and out["queued"] == out["candidates"]
    after = store.query_one("SELECT issue_id, issue_state FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
                            (key, row["cluster_key"]))
    assert (after["issue_id"], after["issue_state"]) == (issue["issue_id"], "queued")


def test_an_unverified_fail_claim_makes_the_same_cluster_p2(store):
    """② 카드 인용이 대조를 못 지난(지어낸 인용) FAIL 만 있으면 같은 클러스터가 P2 다 — 여전히 held_fail 이다."""
    key = rig.target(store)
    unit = _units(store, key)[0]
    _review(store, key, (SEAL, "mech-syn-0"), [unit], verdicts={"K01": ("yes", "FAIL")}, invented=True)
    row = _k01_row(store, key, unit)
    assert row["merged"]["claimed"]["verified_fail_experts"] == 0
    issues.select_issues(store, key, selected_round=1)
    issue = _issue(store, key, row["cluster_key"])
    assert "held_fail" in issue["types"] and issue["p_class"] == "P2"


def test_a_single_expert_severe_cluster_is_solo_severe(store):
    """③ 한 명만 낸 중대(WARNING) 클러스터는 solo_severe(P2)이고 held_fail 이 아니다. 둘이 낸 같은 모양은 후보가 아니다."""
    key = rig.target(store)
    first, second = _units(store, key)[:2]
    _review(store, key, (SEAL,), [first], verdicts={"K01": ("yes", "WARNING")})
    _review(store, key, (SEAL, "mech-syn-0"), [second], verdicts={"K01": ("yes", "WARNING")})
    solo, pair = _k01_row(store, key, first), _k01_row(store, key, second)
    assert (solo["support_experts"], pair["support_experts"]) == (1, 2)
    issues.select_issues(store, key, selected_round=1)
    issue = _issue(store, key, solo["cluster_key"])
    assert issue["types"] == ["solo_severe"] and issue["p_class"] == "P2"
    assert not [r for r in issues.issue_rows(store, key) if r["anchor_cluster_key"] == pair["cluster_key"]]


def test_two_ok_reviewers_who_declared_the_mechanism_make_a_split_verdict_and_one_does_not(store):
    """④ 같은 단위·같은 변경 줄에 OK·인용 대조 통과를 낸 다른 전문가가 둘이고 그 셀 신고에 같은 메커니즘 코드가 있으면
    split_verdict 다. 한 명이면 아니다(held_fail 은 그대로). 신고가 없는 OK 는 반대 측이지만 split 반대자가 아니다."""
    key = rig.target(store)
    first, second = _units(store, key)[:2]
    for unit, ok_experts in ((first, ("xd-syn-0", "xd-syn-1")), (second, ("xd-syn-0",))):
        _review(store, key, (SEAL,), [unit], verdicts={"K01": ("yes", "FAIL")})
        _review(store, key, ok_experts, [unit], seen=(CODE,))
    _review(store, key, ("mech-syn-0",), [second])                                    # 신고 없는 OK
    split, lone = _k01_row(store, key, first), _k01_row(store, key, second)
    assert (split["mechanism"], split["mechanism_detail"]) == ("interface", "clearance")
    issues.select_issues(store, key, selected_round=1)
    got = _issue(store, key, split["cluster_key"])
    assert got["types"] == ["held_fail", "solo_severe", "split_verdict"]
    assert [(o["agent_key"], o["split"]) for o in got["basis"]["opposers"]] == [("xd-syn-0", True), ("xd-syn-1", True)]
    other = _issue(store, key, lone["cluster_key"])
    assert "split_verdict" not in other["types"] and "held_fail" in other["types"]
    assert [(o["agent_key"], o["split"]) for o in other["basis"]["opposers"]] == [("mech-syn-0", False), ("xd-syn-0", True)]
    # 반대자 수가 우선순위에 든다(1 + 0.1·min(반대자, 3)) — split 반대자 둘(신고 없는 OK 는 그 단위에 없다).
    assert got["priority"] == issues.issue_priority(split, got["types"], 2) > issues.issue_priority(split, got["types"], 0)


# ---------------------------------------------------------------- 상한 · 순서
@pytest.mark.parametrize(("p1", "p2", "queued_p1", "queued_p2"), [(30, 0, 30, 0), (60, 0, 48, 0), (10, 30, 10, 14)])
def test_the_cap_runs_p1_up_to_48_first_and_fills_24_with_the_rest(p1, p2, queued_p1, queued_p2):
    """⑤ `n_run = min(P1, 48) + max(0, 24 − min(P1, 48))` — 상한 셈은 순수 함수다(등급 표지만 본다)."""
    ordered = [{"p_class": "P1", "anchor_cluster_key": f"a{i:03d}"} for i in range(p1)]
    ordered += [{"p_class": "P2", "anchor_cluster_key": f"b{i:03d}"} for i in range(p2)]
    run, out = issues.allocate_cap(ordered, cap=24, hard_cap=48)
    assert (sum(k.startswith("a") for k in run), sum(k.startswith("b") for k in run)) == (queued_p1, queued_p2)
    assert len(run) + len(out) == p1 + p2 and not run & out
    run2, _ = issues.allocate_cap(ordered, cap=24, hard_cap=48, used_p1=20, used_other=0)    # 이미 돈 20건을 뺀다
    assert sum(k.startswith("a") for k in run2) == min(p1, 28)


def test_selection_beyond_the_cap_leaves_untried_rows_in_rank_order_whatever_the_input_order(store, monkeypatch, tmp_path):
    """⑤ 실제 원장에서 — 손잡이를 줄이면(P1 2 · 합 2) 순위 앞 P1 둘만 대기, 나머지는 untried_cap(cap) 행으로 남는다.
    ⑥ 후보를 섞어도 같은 순서다. 다시 골라도 같은 행이다(근거가 같으면 상태도 같다)."""
    rig.configure(monkeypatch, store, tmp_path, risk_issue_panel_cap=2, risk_issue_panel_hard_cap=2)
    key = rig.target(store)
    unit_ids = _units(store, key)[:4]
    _review(store, key, (SEAL,), unit_ids, verdicts={"K01": ("yes", "FAIL")})
    _review(store, key, ("mech-syn-0",), unit_ids[:2], verdicts={"K01": ("yes", "FAIL")})
    registry.merge(store, key)
    found = issues.candidates(store, key)
    assert sum(c["p_class"] == "P1" for c in found) >= 4
    shuffled = found[:]
    random.Random(7).shuffle(shuffled)
    assert sorted(shuffled, key=issues.order_key) == found
    out = issues.select_issues(store, key, selected_round=1)
    rows = issues.issue_rows(store, key)
    assert [r["rank"] for r in rows] == list(range(1, len(found) + 1))
    assert [r["anchor_cluster_key"] for r in rows] == [c["anchor_cluster_key"] for c in found]
    assert [r["state"] for r in rows[:2]] == ["queued", "queued"] and out["queued"] == 2
    assert {(r["state"], r["state_reason"]) for r in rows[2:]} == {("untried_cap", "cap")}
    assert out["untried_cap"] == len(found) - 2 and out["cap"]["used"] == {"P1": 0, "other": 0}
    before = [(r["issue_id"], r["state"], r["basis_hash"], r["rank"]) for r in rows]
    issues.select_issues(store, key, selected_round=2)
    assert [(r["issue_id"], r["state"], r["basis_hash"], r["rank"]) for r in issues.issue_rows(store, key)] == before


def test_a_row_a_person_closed_is_not_a_candidate_and_its_waiting_issue_is_withdrawn(store):
    """⑦ 사람이 닫은 행(status_source='human')은 후보가 아니다 — 대기 중이던 쟁점은 withdrawn 이고 등록부 표기도 따라간다."""
    key = rig.target(store)
    unit = _units(store, key)[0]
    _review(store, key, (SEAL,), [unit], verdicts={"K01": ("yes", "FAIL")})
    row = _k01_row(store, key, unit)
    issues.select_issues(store, key, selected_round=1)
    assert _issue(store, key, row["cluster_key"])["state"] == "queued"
    registry.set_status(store, row["cluster_key"], "dismissed", owner_sub=OWNER, target_key=key, evidence_ref="rpt:1")
    assert row["cluster_key"] not in {c["anchor_cluster_key"] for c in issues.candidates(store, key)}
    out = issues.select_issues(store, key, selected_round=2)
    assert _issue(store, key, row["cluster_key"])["state"] == "withdrawn" and out["withdrawn"] >= 1
    assert store.query_one("SELECT issue_state FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
                           (key, row["cluster_key"]))["issue_state"] == "withdrawn"


def test_a_panels_target_has_no_issues(store):
    """패널 대상에는 쟁점이 없다(3.5 끝) — 카드 대조를 얹어도(흐름 panels) 후보 0 이고 행을 만들지 않는다."""
    synth = factories.make_diff_target(store, 40, open_target=False)
    key = routes.create_target(routes.TargetBody(kind="diff", ref_id=synth.diff_id, consent=True, flow="panels",
                                                 agents=[dict(r) for r in rig.ROSTER]), ident=factories.ident(OWNER))["target_key"]
    routes.post_units(key, routes.UnitsBody(reason="검토 얹기"), ident=factories.ident(OWNER))
    unit = _units(store, key)[0]
    _review(store, key, (SEAL,), [unit], verdicts={"K01": ("yes", "FAIL")})
    registry.merge(store, key)
    out = issues.select_issues(store, key, selected_round=1)
    assert out["candidates"] == 0 and not issues.issue_rows(store, key) and out["by_type"] == {}
