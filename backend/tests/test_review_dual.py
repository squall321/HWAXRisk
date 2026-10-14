# 걸린 것만 이중 판정(재설계 M3 C3-9) — 걸린 별칭만 rev · 하나면 단독 · 1순위는 보정용 전량 · 무작위 뒤집기 자동 켬을 검토 루프 끝까지 본다
"""가짜 엔진의 걸림 스위치(카드 0·1·3장)로 셀마다 낸 rev·단독 호출을 센다. 워커 하나 — 검토 순서가 1순위를 먼저 집어 보정이 먼저 선다.

- 팩은 엔진 계약 예제(pack_ok — 점검 카드 6장, K=8 이라 묶음 하나)이고 단위는 시험대의 첫 단위 하나로 좁힌다.
- 거르기는 끈다(분류는 test_review_filter.py).
"""
from __future__ import annotations

import json

import pytest

from app import review_cells, review_quality, review_verify, units
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

MECH1, MECH2 = "mech-syn-0", "mech-syn-1"
ROSTER: tuple[dict, ...] = ({"key": MECH1, "domain": "mech", "relevance": 0.99},
                            {"key": MECH2, "domain": "mech", "relevance": 0.9})


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_review_concurrency=1, risk_review_filter="off",
                  risk_review_dual="flagged")
    return risk_store


def _packs() -> dict[str, dict]:
    ok = fre.load("pack_ok.json")
    return {r["key"]: fre.derive_pack(ok, r["key"], name=r["key"], domain=r["domain"]) for r in ROSTER}


def _record(alias: str) -> str:
    return next(str(c["record_id"]) for c in fre.load("pack_ok.json")["cards"] if c["alias"] == alias)


def _runs(fake: FakeReviewEngine, agent: str, variant: str) -> list[dict]:
    return [r["body"] for r in fake.calls("run") if r["body"]["expert"]["key"] == agent and r["body"]["kind"] == "verdict"
            and r["body"]["variant"] == variant]


def _sample(store, key: str, agent: str) -> dict:
    """그 전문가의 범위 안 첫 셀(단위 순서)의 sample_json."""
    row = store.query_one("SELECT sample_json FROM rr_review_cells WHERE target_key = ? AND agent_key = ? AND run_id IS NOT NULL"
                          " ORDER BY unit_seq LIMIT 1", (key, agent))
    return json.loads(row["sample_json"] or "{}")


def _run(store, fake: FakeReviewEngine, *, agents=None, one_unit: bool = True) -> tuple[str, str]:
    key = rig.target(store, ROSTER)
    unit_id = units.load_units(store, key)[0]["unit_id"]
    job_id = rig.job(store, key, scope={**({"unit_ids": [unit_id]} if one_unit else {}),
                                        **({"agents": agents} if agents else {})})
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    assert review_cells.review_invariants(store, key) == []
    return key, unit_id


# ---------------------------------------------------------------- 카드 0·1·3장 걸림
@pytest.mark.parametrize("hits", [0, 1, 3])
def test_only_flagged_aliases_get_a_second_judgement_and_rank_one_calibrates_the_whole_deck(store, hits):
    """flagged — 걸림 0 인 묶음은 rev 0 · 단독 0, 걸림 하나면 rev 0 · 그 카드 단독 1, 둘 이상이면 그 별칭만 실은 rev 1(나머지 카드는
    제목 목록으로 내린다)과 걸린 카드마다 단독 1. 안 걸린 카드는 단독으로 새지 않는다. 1순위 셀은 보정이라 묶음 전체를 rev 한다.
    1순위 밖 셀에는 무작위 뒤집기 표지(꺼짐 · 안 뽑힘)가 남는다."""
    flagged = [f"K0{i}" for i in range(1, hits + 1)]
    fake = FakeReviewEngine(_packs())
    fake.verdicts = {_record(a): ("yes", "FAIL") for a in flagged}
    key, _unit = _run(store, fake)
    checkable = [c["alias"] for c in fre.load("pack_ok.json")["cards"] if c.get("checkable")]

    revs = _runs(fake, MECH2, "rev")
    assert len(revs) == (1 if hits >= 2 else 0)
    if revs:
        assert [c["alias"] for c in revs[0]["cards"]] == flagged
        assert [d["alias"] for d in revs[0]["digest"]][:len(checkable) - hits] == [a for a in checkable if a not in flagged]
    assert sorted(c["alias"] for b in _runs(fake, MECH2, "solo") for c in b["cards"]) == flagged
    assert _sample(store, key, MECH2)["dual_neg"] == {"on": False, "picked": False}

    (calib,) = _runs(fake, MECH1, "rev")                                     # 1순위 — 보정용 묶음 전체
    assert [c["alias"] for c in calib["cards"]] == checkable
    assert sorted(c["alias"] for b in _runs(fake, MECH1, "solo") for c in b["cards"]) == flagged
    assert "dual_neg" not in _sample(store, key, MECH1)
    eff = {r["alias"]: r["judgement"] for r in store.query(
        "SELECT alias, judgement FROM rr_card_verdicts WHERE target_key = ? AND agent_key = ? AND is_effective = 1",
        (key, MECH2))}
    assert eff == {a: ("FAIL" if a in flagged else "OK") for a in checkable}


def test_the_all_mode_and_an_m2_job_rev_every_deck(store, monkeypatch):
    """all(M2 동작) — 묶음마다 rev 하나(1순위 밖 셀도). knobs 에 dual 칸이 없는 M2 잡도 all 로 돈다. 무작위 뒤집기 표지는 없다."""
    fake = FakeReviewEngine(_packs())
    key = rig.target(store, ROSTER)
    unit_id = units.load_units(store, key)[0]["unit_id"]
    job_id = rig.job(store, key, scope={"unit_ids": [unit_id]})
    row = store.query_one("SELECT params_json FROM rr_jobs WHERE id = ?", (job_id,))
    params = json.loads(row["params_json"])
    for name in ("dual", "dual_calib", "dual_neg_pct"):
        params["knobs"].pop(name)
    store.execute("UPDATE rr_jobs SET params_json = ? WHERE id = ?", (json.dumps(params), job_id))
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    assert len(_runs(fake, MECH2, "rev")) == len(_runs(fake, MECH1, "rev")) == 1
    assert "dual_neg" not in _sample(store, key, MECH2)


# ---------------------------------------------------------------- 무작위 뒤집기 자동 켬(#32)
@pytest.mark.parametrize(("rev_flip", "scope_rank1", "state"), [(True, True, "on"), (False, True, "off"),
                                                                 (True, False, "unmeasured")])
def test_random_reverse_turns_on_when_the_calibration_flips_more_than_five_percent(store, monkeypatch, rev_flip,
                                                                                   scope_rank1, state):
    """보정 모집단(1순위 셀 — 묶음 전체 rev)에서 fwd 가 걸림 없음인데 rev 가 걸림인 카드의 비율이 5% 를 넘으면(6장 가운데 1장)
    1순위가 다 닫힌 뒤의 셀은 걸림 없는 묶음을 무작위로 rev 한다(비율 100% 로 둬 반드시 뽑힌다) — 표지 on · picked. 뒤집힘이
    없으면 꺼짐이고, 1순위가 범위 밖이라 보정이 없으면(1순위 셀이 열려 있다) 미측정이라 켜지지 않는다. 1순위 셀은 잡 범위와
    상관없이 대상의 검토 단위 전부라 단위를 좁히지 않는다. 켜짐은 원장에서 유도한다."""
    import dataclasses

    from app import config

    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_dual_neg_pct=100))
    fake = FakeReviewEngine(_packs())
    if rev_flip:
        fake.rev_verdicts = {_record("K01"): ("yes", "FAIL")}
    key, _unit = _run(store, fake, agents=None if scope_rank1 else [MECH2], one_unit=False)
    on = state == "on"
    n_units = len(units.load_units(store, key))
    samples = [json.loads(r["sample_json"])["dual_neg"] for r in store.query(
        "SELECT sample_json FROM rr_review_cells WHERE target_key = ? AND agent_key = ?", (key, MECH2))]
    assert samples == [{"on": on, "picked": on}] * n_units
    assert len(_runs(fake, MECH2, "rev")) == (n_units if on else 0)
    if on:
        assert [c["alias"] for c in _runs(fake, MECH2, "rev")[0]["cards"]] == [
            c["alias"] for c in fre.load("pack_ok.json")["cards"] if c.get("checkable")]
    # 한 번 켜진 대상은 꺼지지 않는다 — 원장에 켜진 셀이 하나라도 있으면 그 뒤 세션도 켠다
    rows = [dict(r) for r in store.query("SELECT unit_id, agent_key, record_id, variant, judgement FROM rr_card_verdicts"
                                         " WHERE target_key = ? AND agent_key = ?", (key, MECH1))]
    assert review_verify.dual_neg_state(rows, tier_a_closed=scope_rank1)["state"] == state


# ---------------------------------------------------------------- 엔진이 알린 부딪침(RB3-1)
@pytest.mark.parametrize("conflicted", [["K02"], ["K02", "K03"]])
def test_an_engine_conflict_on_a_clear_row_is_treated_as_flagged(store, conflicted):
    """엔진이 fwd 의 OK 행에 같은 카드의 다른 판정과 부딪쳤다고 알리면(checks.dup_conflict — RB3-1) 그 카드는 '문제없음' 으로 믿지
    않는다 — 걸린 것처럼 두 번째 판정을 받는다. 하나면 단독, 둘이면 그 둘만 실은 rev(둘 다 OK 로 같아 단독은 없다). 다른 카드는
    그대로 한 번이다."""
    fake = FakeReviewEngine(_packs())
    fake.dup_conflict = {(MECH2, a) for a in conflicted}
    key, _unit = _run(store, fake)
    revs = _runs(fake, MECH2, "rev")
    solos = [c["alias"] for b in _runs(fake, MECH2, "solo") for c in b["cards"]]
    if len(conflicted) == 1:
        assert (revs, solos) == ([], conflicted)
    else:
        assert ([[c["alias"] for c in b["cards"]] for b in revs], solos) == ([conflicted], [])
    assert _runs(fake, MECH1, "solo") == []
    # 품질 수치와 보고서의 품질 절이 엔진이 알린 부딪침을 센다
    quality = review_quality.compute(store, key, agent_key=MECH2)
    assert quality["flips"]["engine_conflict"] == {"dup_conflict": len(conflicted), "flipped": 0, "calls": 1}
    assert f"엔진이 알린 부딪침 {len(conflicted)}줄" in review_quality.block(store, key, agent_key=MECH2)["text"]


def test_inputs_the_engine_clipped_are_counted_in_quality(store):
    """엔진이 몫에서 끊은 입력(meta.clipped — RB3-11)은 호출 원장의 앱 회계에 남고 품질 수치·문면이 그 호출 수와 입력 이름을 싣는다.
    빈 것({})은 원장에 싣지 않는다."""
    fake = FakeReviewEngine(_packs())
    fake.clipped = {"cards": {"orig_chars": 1000, "kept_chars": 500}}
    key, _unit = _run(store, fake, agents=[MECH1])
    calls = [json.loads(r["quality_json"])["app"].get("clipped") for r in store.query(
        "SELECT quality_json FROM rr_review_calls WHERE target_key = ? AND state = 'ok'", (key,))]
    assert calls and all(c == fake.clipped for c in calls)
    quality = review_quality.compute(store, key, agent_key=MECH1)
    assert quality["truncation"]["clipped"] == {"calls": len(calls), "inputs": ["cards"]}
    assert f"몫에서 끊은 입력 {len(calls)}호출(«cards»)" in review_quality.block(store, key, agent_key=MECH1)["text"]
