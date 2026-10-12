# 검토 품질 수치(재설계 M2 · m2-wp3b S11) — 검토 루프가 가짜 엔진으로 만든 작은 원장에서 수치마다 손으로 센 값과 같은지, 문면의 수가 json 의 수인지, 린터·표본 미달·옛 대상 한 줄·binom_upper 를 본다
"""원장은 전부 생산자가 쓴다 — 대상은 합성 쌍 → 실제 캡처·diff → 단위 빌드, 팩은 엔진 계약 예제에서 전문가만 바꾼 것, 셀·판정·
호출 행은 검토 루프(S8)가 가짜 엔진을 상대로 돌며 쓴다(tests/synth/review_rig.py). 기대값은 시나리오에서 손으로 센 수다.

로스터(rig.ROSTER) — 카드 전문가 넷(점검 6 · 배경 4 · 본문 없음 1 = 11장), 배경 카드뿐 하나(배경 4 · 본문 없음 1 = 5장),
0장 하나. 단위 다섯. 계약 예제 팩의 별칭은 K01~K06 이 점검, K07~K10 이 배경이다.
"""
from __future__ import annotations

import dataclasses
import json
import math
import re
from fractions import Fraction

import pytest

from app import audit, config, render, review_quality, review_runner, units
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

SEAL = rig.SEAL
NO_ROWS = {"code": "no_rows", "message": "판정 행이 하나도 없다(가짜)", "infra": False, "retryable": False}


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _records() -> dict[str, str]:
    return {c["alias"]: c["record_id"] for c in fre.load("pack_ok.json")["cards"]}


def _unit_ids(store, key: str) -> list[str]:
    return [u["unit_id"] for u in units.load_units(store, key)]


def _rd(metric: dict) -> tuple:
    return metric["num"], metric["den"]


def _full(store):
    """전원 × 단위 다섯. 카드별 대본 — K01 은 fwd·rev·단독 모두 FAIL, K02 는 rev 만 WARNING(fwd·rev 갈림 → 단독 OK → 변형
    갈림이라 실효 보류), K04 는 지어낸 인용(엔진도 not_found), K06 은 해당 없음(no·na). 셀 (xd-syn-1, 다섯째 단위)은 늘 내용 탓
    오류라 두 번 차감되어 failed 다. 훑기는 첫 단위를 rel=no 로 답한다."""
    key = rig.target(store)
    job_id = rig.job(store, key)
    rec = _records()
    order = _unit_ids(store, key)
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {rec["K01"]: ("yes", "FAIL"), rec["K06"]: ("no", "na")}
    fake.rev_verdicts = {rec["K02"]: ("yes", "WARNING")}
    fake.invented_quote = {"K04"}
    fake.error_cells = {("xd-syn-1", order[4]): NO_ROWS}
    fake.sweep_rel = {order[0]: "no"}
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    return key, job_id, fake, order


def _small(store, monkeypatch):
    """SEAL 하나 × 단위 둘(범위) — 묶음 K=5 라 점검 묶음은 [K01~K05]·[K06](1장 묶음은 rev 를 건너뛰고 단독으로 — X1-20), 카드 밖
    상한 2(늘 닿아 '이것 말고 더' 3번), 첫 run 둘은 관문 즉답(기다림), K05 는 엔진만 ok 라 속인 인용(서버·앱 갈림). 카드별 대본 —
    K01 은 fwd·rev FAIL 인데 단독이 OK(걸림→걸림 없음, 변형 갈림이라 실효 보류), K02 는 rev 만 WARNING(갈려 단독이 OK — 보류),
    K03 은 인용도 변경 줄도 싣지 않고, K04 는 해당 없음, K06 은 fwd 해당 없음인데 단독이 WARNING(걸림 없음→걸림). 첫 단위의 첫 fwd 는 출력 상한에 걸려 마지막 행
    (K05)이 빠지고 재질의가 채운다. 둘째 단위의 첫 fwd 는 절단을 모른다(finish_reason 없음). 자리 대기는 늘 1.5초다."""
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_concurrency=1))
    key = rig.target(store)
    order = _unit_ids(store, key)
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": order[:2]})
    rec = _records()
    limits = fre.load("limits_1m.json")
    limits["verdict"]["k"] = 5
    limits["offcard"]["findings_max"] = 2
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")}, limits=limits)
    fake.verdicts = {rec["K01"]: ("yes", "FAIL"), rec["K04"]: ("no", "na"), rec["K06"]: ("no", "na")}
    fake.rev_verdicts = {rec["K02"]: ("yes", "WARNING")}
    fake.solo_verdicts = {rec["K01"]: ("yes", "OK"), rec["K06"]: ("yes", "WARNING")}
    fake.lying_quote = {"K05"}
    fake.no_quote = {"K03"}
    fake.no_refs = {"K03"}
    fake.offcard_findings = 2
    fake.busy_n = 2
    fake.queued_ms = 1500
    fake.sweep_rel = {order[0]: "no"}
    fake.truncate = {("verdict", "fwd", order[0]): "length", ("verdict", "fwd", order[1]): "unknown"}
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    return key, job_id, fake, order


def _nearest_rank(values: list[int], p: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(1, math.ceil(p * len(ordered))) - 1] / 1000.0, 3)


def _durations(store, key: str, label: str | None = None) -> list[int]:
    rows = store.query("SELECT kind, variant, duration_ms FROM rr_review_calls WHERE target_key = ? AND state = 'ok'", (key,))
    return [r["duration_ms"] for r in rows
            if label is None or (f"verdict/{r['variant']}" if r["kind"] == "verdict" else r["kind"]) == label]


def _prompt_chars(fake: FakeReviewEngine, skip) -> int:
    """받은 run 본문의 글자 수 합 — 가짜가 meta.prompt_chars 를 세는 그대로(답을 받은 run 만)."""
    return sum(len(json.dumps(body, ensure_ascii=False)) for body in (r["body"] for r in fake.calls("run")) if not skip(body))


def _python_bytes(store, table: str, where: str, params: tuple) -> int:
    """표의 행 바이트를 파이썬으로 다시 센다 — 글은 UTF-8, BLOB 은 바이트, 정수는 그 글자 수."""
    total = 0
    for row in store.query(f"SELECT * FROM {table} WHERE {where}", params):
        for value in dict(row).values():
            if value is None:
                continue
            total += len(value) if isinstance(value, bytes) else len(str(value).encode("utf-8"))
    return total


# ---------------------------------------------------------------- binom_upper
def _exact_cdf(k: int, n: int, p: float) -> float:
    q = Fraction(p)
    return float(sum(Fraction(math.comb(n, i)) * q ** i * (1 - q) ** (n - i) for i in range(k + 1)))


def test_binom_upper_matches_closed_forms_the_spec_examples_and_the_exact_binomial():
    """닫힌 꼴(k=0 → 1−α^(1/n), k=n−1 → (1−α)^(1/n), k=n → 1), WP5b 3.11.3 문면 예의 상한(0/59 4.95% · 2/59 10.3% ·
    3/120 6.3%), 그리고 작은 n 전부에서 상한 자리의 정확 이항 누적이 α 이고 그 바로 아래는 α 보다 크다(유리수로 센다)."""
    for n in (1, 2, 29, 59, 1000):
        assert audit.binom_upper(0, n) == pytest.approx(1 - 0.05 ** (1 / n), abs=1e-12)
        assert audit.binom_upper(n, n) == 1.0
        if n > 1:
            assert audit.binom_upper(n - 1, n) == pytest.approx(0.95 ** (1 / n), abs=1e-9)
    assert round(audit.binom_upper(0, 59) * 100, 2) == 4.95
    assert round(audit.binom_upper(2, 59) * 100, 1) == 10.3
    assert round(audit.binom_upper(3, 120) * 100, 1) == 6.3
    for n in range(1, 31):
        for k in range(n):
            bound = audit.binom_upper(k, n)
            assert k / n < bound < 1
            assert _exact_cdf(k, n, bound) == pytest.approx(0.05, abs=1e-9), (k, n)
            assert _exact_cdf(k, n, bound - 1e-6) > 0.05, (k, n)
    assert audit.binom_upper(0, 0) is None
    for bad in ((-1, 5), (6, 5), (1.0, 5), (True, 5)):
        with pytest.raises(ValueError):
            audit.binom_upper(*bad)


def test_a_rate_is_none_below_min_n_and_the_upper_bound_threshold_reads_the_95_percent_bound():
    """비율 하나 — min_n 미만은 값·상한·within 이 None(n 은 den 에 남는다, 0 으로 적지 않는다). upper_max 기준은 점추정이 아니라
    95% 상한과 견준다 — 2/59 는 점추정 3.4% 지만 상한 10.3% 라 기준(5%) 밖이고, 0/59 는 상한 4.95% 라 안이다. max·min 은 값과 견준다."""
    policy = review_quality.load_policy()
    neg_pos = review_quality.rate(2, 59, policy=policy, key="flips.solo_neg_pos", upper=True)
    assert neg_pos == {"value": round(2 / 59, 6), "num": 2, "den": 59, "min_n": 59,
                       "upper95": round(audit.binom_upper(2, 59), 6), "threshold": {"upper_max": 0.05}, "within": False}
    assert review_quality.rate(0, 59, policy=policy, key="flips.solo_neg_pos", upper=True)["within"] is True
    assert review_quality.rate(1, 58, policy=policy, key="flips.solo_neg_pos", upper=True) == {
        "value": None, "num": 1, "den": 58, "min_n": 59, "upper95": None, "threshold": {"upper_max": 0.05}, "within": None}
    assert review_quality.rate(3, 30, policy=policy, key="flips.order")["within"] is True           # 10% 는 기준 안
    assert review_quality.rate(4, 30, policy=policy, key="flips.order")["within"] is False
    assert review_quality.rate(4, 5, policy=policy, key="citation.quote.clear")["within"] is True   # 80% 는 기준 안
    assert review_quality.rate(3, 5, policy=policy, key="citation.quote.clear")["within"] is False
    assert review_quality.rate(0, 0, policy=policy) == {"value": None, "num": 0, "den": 0}


def test_call_seconds_are_nearest_rank_percentiles_of_duration_ms():
    """호출 초는 가까운 순위 백분위다 — 작은 쪽부터 ceil(p·n) 번째(보간 없음). p95 는 기준(900초)과 견주고 표본 0 이면 값이 없다."""
    policy = review_quality.load_policy()
    four = review_quality.seconds_stat([4000, 1000, 3000, 2000], policy=policy)
    assert (four["n"], four["p50"]["value"], four["p95"]["value"], four["max"]["value"]) == (4, 2.0, 4.0, 4.0)
    twenty = review_quality.seconds_stat([s * 1000 for s in range(20, 0, -1)], policy=policy)
    assert (twenty["p50"]["value"], twenty["p95"]["value"], twenty["max"]["value"]) == (10.0, 19.0, 20.0)
    assert twenty["p95"]["within"] is True and twenty["p95"]["threshold"] == {"max": 900}
    slow = review_quality.seconds_stat([1234, 901_000], policy=policy)
    assert (slow["p50"]["value"], slow["p95"]["value"], slow["p95"]["within"]) == (1.234, 901.0, False)
    empty = review_quality.seconds_stat([], policy=policy)
    assert empty == {"n": 0, "p50": {"value": None, "n": 0}, "max": {"value": None, "n": 0},
                     "p95": {"value": None, "n": 0, "threshold": {"max": 900}, "within": None}}


# ---------------------------------------------------------------- 전원 원장
def test_every_metric_of_the_full_grid_equals_the_hand_count(store):
    key, job_id, fake, order = _full(store)
    res = review_quality.compute(store, key)

    assert (res["policy_version"], res["model"], res["limits_rev"]) == ("rq-1", "fake-glm", "21349c51")
    assert res["prompt_rev"] == "offcard=cr-offcard-1,sweep=cr-sweep-1,verdict=cr-verdict-1"
    assert res["revs"]["mixed"] is False

    # 격자 — 6 × 5 = 30칸, 실패 셀 하나, 검토 29 를 바탕별로(카드 대조 4×5−1 · 배경뿐 5 · 역할만 5 — X1-04).
    grid = res["grid"]
    assert (grid["experts"], grid["units"], grid["expected"], grid["cells"], grid["missing"], grid["extra"]) == (
        6, 5, 30, 30, 0, 0)
    assert grid["by_state"] == {"pending": 0, "running": 0, "reviewed": 29, "na_irrelevant": 0, "no_input": 0,
                                "failed": 1, "skipped": 0}
    assert grid["reviewed_by_basis"] == {"cards": 19, "background": 5, "role_only": 5}
    assert (grid["in_scope"]["job_id"], grid["in_scope"]["total"]) == (job_id, 30)
    assert (grid["out_of_scope_pending"], grid["failed_open"]) == (0, 1)
    assert grid["expert_states"]["by_state"] == {"planned": 0, "running": 0, "ready": 5, "partial": 1, "blocked": 0}
    assert _rd(grid["form_only"]) == (0, 19) and grid["form_only"]["value"] == 0.0

    # 카드 폭포 — 분모 (카드 전문가 4 × 11장 + 배경뿐 5장) × 단위 5 = 245. 판정 받음 19칸 × 점검 6, 배경 본문 (19 + 5) × 4,
    # 본문 없음 (19 + 5) × 1, 실패 칸 1 × 11. judged/expected 는 불변식 칸에만 있다(X1-03).
    cards = res["cards"]
    assert cards["denominator"] == (4 * 11 + 5) * 5 == 245
    lines = {name: m["num"] for name, m in cards["lines"].items()}
    assert lines == {"judged": 114, "unjudged": 0, "background_full": 96, "background_title_only": 0,
                     "background_unsent": 0, "no_body": 24, "failed": 11, "open": 0, "out_of_scope": 0, "filtered": 0,
                     "no_input": 0}
    assert {m["den"] for m in cards["lines"].values()} == {245} and cards["residual"] == 0
    assert cards["lines"]["judged"]["value"] == round(114 / 245, 6)
    assert (cards["experts_without_pack"], cards["cells_without_pack"]) == (0, 0)
    assert cards["invariant"] == {"judged": 114, "expected": 114, "holds": True}

    # 받은 호출 110 = 훑기 5(카드가 있는 전문가 다섯 × 묶음 1 × 쪽 1) + fwd 19 + rev 19 + 단독 38(K01 걸림 · K02 갈림) + 카드 밖 29.
    trunc = res["truncation"]
    assert _rd(trunc["calls"]) == (0, 110) and trunc["calls"]["within"] is True
    assert _rd(trunc["calls_unknown"]) == (0, 110)
    assert (_rd(trunc["cells"]), _rd(trunc["cells_unknown"]), _rd(trunc["soft_over"])) == ((0, 29), (0, 29), (0, 110))
    assert trunc["offcard_capped"] == {"cells": 0, "hits": 0}
    assert trunc["dropped_over_cap"] == {"rows": 0, "offcard_calls": 29, "offcard_calls_unknown": 0}

    # 인용 — 실효 114행 = 걸림(K01) 19 · 보류(K02 갈림) 19 · 걸림 없음(K03~K06) 76. K04 의 지어낸 인용이 걸림 없음에서 19를 깎는다.
    cite = res["citation"]
    assert {k: _rd(m) for k, m in cite["quote"].items()} == {"flagged": (19, 19), "clear": (57, 76), "hold": (19, 19),
                                                              "all": (95, 114)}
    assert cite["quote"]["flagged"]["within"] is True and cite["quote"]["clear"]["within"] is False
    assert _rd(cite["refs"]) == (95, 95)          # applies='yes' 실효 행 = K01~K05 × 19(K06 은 해당 없음)
    assert cite["check_disagree"] == 0

    # 뒤집힘 — 순서: 카드 전부가 6장 묶음이라 rev 를 받았고 K02 만 다르다(19/114). 단독: 바탕이 걸림인 K01 19장이 그대로,
    # K02 는 fwd·rev 가 갈려 단독이 가른 카드라 두 비율에서 빠진다. 걸림 없음 바탕의 단독은 없다(미측정).
    flips = res["flips"]
    assert _rd(flips["order"]) == (19, 114) and flips["order"]["value"] == round(19 / 114, 6)
    assert flips["order"]["upper95"] == round(audit.binom_upper(19, 114), 6) and flips["order"]["within"] is False
    assert _rd(flips["solo_pos_neg"]) == (0, 19) and flips["solo_pos_neg"]["upper95"] == round(audit.binom_upper(0, 19), 6)
    assert flips["solo_neg_pos"] == {"value": None, "num": 0, "den": 0, "min_n": 59, "upper95": None,
                                     "threshold": {"upper_max": 0.05}, "within": None}
    assert flips["solo_disputed"] == {"cards": 19, "pos": 0, "neg": 19, "hold": 0}
    assert (flips["solo_base_hold"], flips["solo_only"]) == (0, 0)
    assert _rd(flips["split"]) == (19, 114)

    secs = res["seconds"]
    assert {label: s["n"] for label, s in secs["kinds"].items()} == {"sweep": 5, "verdict/fwd": 19, "verdict/rev": 19,
                                                                      "verdict/solo": 38, "offcard": 29}
    for label, stat in [*secs["kinds"].items(), ("all", secs["all"])]:
        values = _durations(store, key, None if label == "all" else label)
        assert (stat["p50"]["value"], stat["p95"]["value"], stat["max"]["value"]) == (
            _nearest_rank(values, 0.5), _nearest_rank(values, 0.95), round(max(values) / 1000, 3)), label
        assert stat["p95"]["within"] is True
    assert secs["queued"]["n"] == 0 and secs["queued"]["p50"]["value"] is None
    assert secs["waits"]["total"] == 0

    # 실측 — 칸 호출 107 = fwd 19 + 실패 셀의 fwd 2 + rev 19 + 단독 38 + 카드 밖 29, 호출이 간 칸 30.
    pilot = res["pilot"]
    assert _rd(pilot["calls_per_cell"]) == (107, 30) and pilot["calls_per_cell"]["value"] == round(107 / 30, 6)
    assert _rd(pilot["positive"]) == (19, 114)
    assert _rd(pilot["sweep_irrelevant"]) == (5, 25) and pilot["sweep_irrelevant"]["used_for_routing"] is False
    assert pilot["tokens"] == {"in": 110 * 1000, "out": 110 * 100, "calls": 110, "calls_unknown": 0}
    failed_cell = ("xd-syn-1", order[4])
    chars = _prompt_chars(fake, lambda b: (b["expert"]["key"], (b.get("unit") or {}).get("unit_id")) == failed_cell)
    assert pilot["chars_per_token"] == {"value": round(chars / 110_000, 6), "num": chars, "den": 110_000, "calls": 110,
                                        "basis": "attempts=1"}
    tables = pilot["bytes"]["tables"]
    assert list(tables) == ["rr_unit_builds", "rr_units", "rr_expert_reports", "rr_review_cells", "rr_card_verdicts",
                            "rr_review_calls", "rr_card_packs"]
    for table in ("rr_unit_builds", "rr_units", "rr_expert_reports", "rr_review_cells", "rr_card_verdicts",
                  "rr_review_calls"):
        assert tables[table] == _python_bytes(store, table, "target_key = ?", (key,)) > 0, table
    packs = store.query("SELECT DISTINCT agent_key, pack_hash FROM rr_expert_reports WHERE target_key = ?"
                        " AND pack_hash IS NOT NULL", (key,))
    assert tables["rr_card_packs"] == sum(_python_bytes(store, "rr_card_packs", "agent_key = ? AND pack_key = ?",
                                                        (p["agent_key"], p["pack_hash"])) for p in packs)
    assert pilot["bytes"]["total"] == sum(tables.values())

    assert res["out_of_bounds"] == ["citation.quote.clear", "flips.order"]
    assert res["unchecked"] == ["flips.solo_neg_pos"]
    assert review_quality.compute(store, key) == res          # 같은 원장이면 같은 dict(시각 없음 — S10 보고서 바이트)


def test_the_expert_scope_counts_one_expert_and_the_experts_add_up_to_the_target(store):
    """전문가 범위(S10 이 부른다) — SEAL 하나의 5칸, 그리고 로스터 전원의 전문가 범위 셈을 더하면 대상 범위 셈이다."""
    key, _job_id, _fake, _order = _full(store)
    res = review_quality.compute(store, key, agent_key=SEAL)
    assert (res["agent_key"], res["grid"]["experts"], res["grid"]["cells"]) == (SEAL, 1, 5)
    assert res["grid"]["reviewed_by_basis"] == {"cards": 5, "background": 0, "role_only": 0}
    assert res["cards"]["denominator"] == 55
    assert {n: m["num"] for n, m in res["cards"]["lines"].items() if m["num"]} == {
        "judged": 30, "background_full": 20, "no_body": 5}
    assert {k: _rd(m) for k, m in res["citation"]["quote"].items()} == {"flagged": (5, 5), "clear": (15, 20),
                                                                         "hold": (5, 5), "all": (25, 30)}
    assert _rd(res["flips"]["order"]) == (5, 30) and res["flips"]["order"]["value"] == round(5 / 30, 6)  # n = min_n 30
    assert _rd(res["pilot"]["calls_per_cell"]) == (25, 5)           # fwd 5 + rev 5 + 단독 10 + 카드 밖 5
    assert res["seconds"]["kinds"]["sweep"]["n"] == 1
    # 전문가 범위는 머리(rr_expert_reports)를 세지 않는다 — S10 이 이 수를 실은 보고서를 머리에 쓰므로, 세면 같은 원장에서도 다시
    # 마감할 때마다 앞 보고서의 바이트가 수에 들어가 보고서가 바뀐다(m-07).
    assert list(res["pilot"]["bytes"]["tables"]) == ["rr_review_cells", "rr_card_verdicts", "rr_review_calls", "rr_card_packs"]
    assert res["pilot"]["bytes"]["tables"]["rr_review_calls"] == _python_bytes(
        store, "rr_review_calls", "target_key = ? AND agent_key = ?", (key, SEAL))

    whole = review_quality.compute(store, key)
    parts = [review_quality.compute(store, key, agent_key=a["key"]) for a in rig.ROSTER]
    assert sum(p["cards"]["denominator"] for p in parts) == whole["cards"]["denominator"]
    for name in review_quality.WATERFALL:
        assert sum(p["cards"]["lines"][name]["num"] for p in parts) == whole["cards"]["lines"][name]["num"], name
    for path in (("citation", "quote", "all"), ("citation", "refs"), ("flips", "order"), ("flips", "split"),
                 ("truncation", "calls"), ("pilot", "positive")):
        def at(d, p=path):
            for k in p:
                d = d[k]
            return d
        assert (sum(at(p)["num"] for p in parts), sum(at(p)["den"] for p in parts)) == _rd(at(whole)), path
    hashes = {p["ledger_hash"] for p in parts} | {whole["ledger_hash"]}
    assert len(hashes) == len(parts) + 1 and all(re.fullmatch(r"[0-9a-f]{16}", h) for h in hashes)   # 범위마다 다른 원장
    text = review_quality.block(store, key, agent_key=SEAL)["text"]
    assert text.startswith(f"[검토 품질 — 코드 계측 · 전문가 «{SEAL}» · 기준판 rq-1")
    assert render.lint_text(text)["ok"]


# ---------------------------------------------------------------- 범위를 좁힌 원장(절단 · 기다림 · 표본 미달)
def test_every_metric_of_a_scoped_ledger_with_truncation_waits_and_small_samples_equals_the_hand_count(store, monkeypatch):
    key, job_id, fake, order = _small(store, monkeypatch)
    res = review_quality.compute(store, key)

    # 격자 — 30칸 가운데 범위(SEAL × 단위 둘)만 검토, 나머지 28칸은 범위 밖 대기. SEAL 은 범위 밖 대기가 남아 일부 마감(P-04).
    grid = res["grid"]
    assert grid["by_state"]["reviewed"] == 2 and grid["by_state"]["pending"] == 28
    assert grid["reviewed_by_basis"] == {"cards": 2, "background": 0, "role_only": 0}
    assert grid["in_scope"]["total"] == 2 and grid["in_scope"]["by_state"]["reviewed"] == 2
    assert grid["out_of_scope_pending"] == 28
    assert grid["expert_states"]["by_state"] == {"planned": 5, "running": 0, "ready": 0, "partial": 1, "blocked": 0}
    assert _rd(grid["form_only"]) == (0, 2)       # 칸마다 K06 이 단독에서 WARNING

    # 카드 폭포 — 묶음을 얼린 것은 SEAL 뿐(나머지 다섯은 범위 밖이라 묶음을 받지 않았다 — 25칸은 분모 밖).
    cards = res["cards"]
    assert cards["denominator"] == 11 * 5
    assert {n: m["num"] for n, m in cards["lines"].items() if m["num"]} == {
        "judged": 12, "background_full": 8, "no_body": 2, "out_of_scope": 33}
    assert (cards["experts_without_pack"], cards["cells_without_pack"], cards["residual"]) == (5, 25, 0)

    # 받은 호출 22 = 훑기 1 + fwd 5(묶음 둘 × 칸 2 + 잘린 fwd 의 빠진 카드 재질의 1) + rev 2(5장 묶음 × 칸 2) + 단독 6(칸마다
    # K01 걸림 · K02 갈림 · K06 1장 묶음) + 카드 밖 8(칸마다 4 — 상한에 늘 닿는다). 기다림 2 는 받은 호출이 아니다.
    trunc = res["truncation"]
    assert _rd(trunc["calls"]) == (1, 22) and trunc["calls"]["within"] is False
    assert _rd(trunc["calls_unknown"]) == (1, 22)
    assert _rd(trunc["cells"]) == (0, 2)          # 잘린 fwd 의 빠진 카드(K05)를 재질의로 채웠다 — 잃은 것이 없다
    assert _rd(trunc["cells_unknown"]) == (1, 2)  # 둘째 칸은 절단을 모르는 호출이 있다(NULL — 0 으로 치지 않는다, X1-22)
    assert trunc["offcard_capped"] == {"cells": 2, "hits": 8}
    assert trunc["dropped_over_cap"] == {"rows": 0, "offcard_calls": 8, "offcard_calls_unknown": 0}
    calls = {r["output_truncated"]: r["n"] for r in store.query(
        "SELECT output_truncated, COUNT(*) AS n FROM rr_review_calls WHERE target_key = ? AND state = 'ok'"
        " GROUP BY output_truncated", (key,))}
    assert calls == {None: 1, 0: 20, 1: 1}
    reask = store.query("SELECT cards_json FROM rr_review_calls WHERE target_key = ? AND kind = 'verdict' AND variant = 'fwd'"
                        " AND seq = 1", (key,))
    assert [r["cards_json"] for r in reask] == ['["K05"]']

    # 인용 — 실효 12행 = 걸림(K06) 2 · 보류(K01·K02 갈림) 4 · 걸림 없음(K03·K04·K05) 6. 걸림 없음에서 K05 의 속인 인용과 K03 의
    # 빈 인용이 각 2를 깎는다(인용이 없는 행도 분모에 든다 — X1-06). 서버·앱 갈림은 K05 행을 받은 호출(첫 칸 재질의 · 둘째 칸
    # fwd · rev 2)마다 하나씩 4건이다(잘린 fwd 는 K05 행이 없다). 참조 — yes 실효(K01·K02·K03·K05·K06 × 2) 가운데 K03 이 깎는다.
    cite = res["citation"]
    assert {k: _rd(m) for k, m in cite["quote"].items()} == {"flagged": (2, 2), "clear": (2, 6), "hold": (4, 4),
                                                              "all": (8, 12)}
    quotes = [r["quote_ok"] for r in store.query("SELECT quote_ok FROM rr_card_verdicts WHERE target_key = ?"
                                                 " AND is_effective = 1", (key,))]
    assert quotes.count(None) == 2               # K03 — 인용 없음(NULL)이 분모에서 빠지지 않았다
    assert _rd(cite["refs"]) == (8, 10) and cite["check_disagree"] == 4

    # 뒤집힘 — 순서: rev 를 받은 5장 묶음의 카드 10장 가운데 K02 2장이 다르다 — 표본 10 은 min_n 30 미달. 단독: 바탕(fwd)이
    # 걸림인 K01 2장이 걸림 없음으로(2/2), 걸림 없음 바탕(1장 묶음 K06) 2장이 걸림으로 — 표본 2 는 min_n 59 미달이라 값이 없다.
    # K02 는 fwd·rev 가 갈려 단독이 가른 카드라 두 비율 밖에 따로 센다.
    flips = res["flips"]
    assert flips["order"] == {"value": None, "num": 2, "den": 10, "min_n": 30, "upper95": None,
                              "threshold": {"max": 0.1}, "within": None}
    assert _rd(flips["solo_pos_neg"]) == (2, 2) and flips["solo_pos_neg"]["value"] == 1.0
    assert flips["solo_pos_neg"]["upper95"] == 1.0
    assert flips["solo_neg_pos"] == {"value": None, "num": 2, "den": 2, "min_n": 59, "upper95": None,
                                     "threshold": {"upper_max": 0.05}, "within": None}
    assert flips["solo_disputed"] == {"cards": 2, "pos": 0, "neg": 2, "hold": 0}
    assert (flips["solo_base_hold"], flips["solo_only"]) == (0, 0) and _rd(flips["split"]) == (4, 12)

    secs = res["seconds"]
    assert {label: s["n"] for label, s in secs["kinds"].items()} == {"sweep": 1, "verdict/fwd": 5, "verdict/rev": 2,
                                                                      "verdict/solo": 6, "offcard": 8}
    assert {k: secs["queued"][k]["value"] for k in ("p50", "p95", "max")} == {"p50": 1.5, "p95": 1.5, "max": 1.5}
    assert secs["queued"]["n"] == 22 and "threshold" not in secs["queued"]["p95"]
    assert secs["waits"] == {"sweep": 2, "verdict/fwd": 0, "verdict/rev": 0, "verdict/solo": 0, "offcard": 0, "total": 2}

    pilot = res["pilot"]
    assert _rd(pilot["calls_per_cell"]) == (21, 2) and pilot["calls_per_cell"]["value"] == 10.5
    assert _rd(pilot["positive"]) == (2, 12)
    assert _rd(pilot["sweep_irrelevant"]) == (1, 5)            # SEAL 의 훑기가 단위 다섯 전부를 답했다(범위 밖 단위 포함)
    assert pilot["tokens"] == {"in": 22_000, "out": 2_200, "calls": 22, "calls_unknown": 0}
    busy = fake.calls("run")[:2]
    chars = _prompt_chars(fake, lambda b: any(b is r["body"] for r in busy))
    assert _rd(pilot["chars_per_token"]) == (chars, 22_000)

    assert res["out_of_bounds"] == ["truncation.calls", "citation.quote.clear"]
    assert res["unchecked"] == ["flips.order", "flips.solo_neg_pos"]


# ---------------------------------------------------------------- 문면
_INT = r"\d{1,3}(?:,\d{3})*"          # 천 단위 쉼표가 든 정수(쉼표 뒤 공백 ', 95% 상한' 을 삼키지 않게)
_FRAG = re.compile(rf"(?P<pct>\d+\.\d)% \((?P<num>{_INT})/(?P<den>{_INT})(?:, 95% 상한 (?P<up>\d+\.\d)%)?"
                   rf"|(?<![\d.])(?P<mean>\d+\.\d{{3}}) \((?P<mnum>{_INT})/(?P<mden>{_INT})"
                   rf"|미측정\(표본 0|표본 수 미달\(n=(?P<n>{_INT})")
# 줄마다 문면에 나오는 비율·평균의 차례(json 경로). 격자 줄은 검토 수 옆에 형식만 채운 칸과 뒤집힘 상한을 단다(WP5b 규칙 3).
_LINE_PATHS = {
    "[격자]": ["grid.form_only", "flips.solo_neg_pos"],
    "[카드]": [f"cards.lines.{name}" for name in review_quality.WATERFALL],
    "[절단]": ["truncation.calls", "truncation.calls_unknown", "truncation.cells", "truncation.cells_unknown",
             "truncation.soft_over"],
    "[인용]": ["citation.quote.flagged", "citation.quote.clear", "citation.quote.hold", "citation.quote.all",
             "citation.refs"],
    "[뒤집힘]": ["flips.order", "flips.solo_pos_neg", "flips.solo_neg_pos", "flips.split"],
    "[실측]": ["pilot.calls_per_cell", "pilot.positive", "pilot.sweep_irrelevant", "pilot.chars_per_token"],
}


def _at(result: dict, path: str):
    node = result
    for key in path.split("."):
        node = node[key]
    return node


def _expected(metric: dict, *, mean: bool) -> tuple:
    if metric["value"] is None:
        return ("none", metric["den"])
    if mean:
        return ("mean", f"{metric['value']:.3f}", metric["num"], metric["den"])
    up = f"{metric['upper95'] * 100:.1f}" if metric.get("upper95") is not None else None
    return ("rate", f"{metric['value'] * 100:.1f}", metric["num"], metric["den"], up)


def _parsed(line: str) -> list[tuple]:
    out = []
    for m in _FRAG.finditer(line):
        if m.group("pct"):
            out.append(("rate", m.group("pct"), int(m.group("num").replace(",", "")),
                        int(m.group("den").replace(",", "")), m.group("up")))
        elif m.group("mean"):
            out.append(("mean", m.group("mean"), int(m.group("mnum").replace(",", "")),
                        int(m.group("mden").replace(",", ""))))
        else:
            out.append(("none", int(m.group("n").replace(",", "")) if m.group("n") else 0))
    return out


def _assert_text_is_the_json(block: dict) -> None:
    text, res = block["text"], block["json"]
    assert render.lint_text(text)["ok"], render.lint_text(text)["violations"]
    lines = {line.split("]", 1)[0] + "]": line for line in text.split("\n")[1:]}
    assert list(lines) == ["[격자]", "[카드]", "[절단]", "[인용]", "[뒤집힘]", "[호출 초]", "[실측]", "[기준]"]
    for tag, paths in _LINE_PATHS.items():
        want = [_expected(_at(res, p), mean=p in ("pilot.calls_per_cell", "pilot.chars_per_token")) for p in paths]
        assert _parsed(lines[tag]) == want, tag
    grid, cards = res["grid"], res["cards"]
    st, basis = grid["by_state"], grid["reviewed_by_basis"]
    assert lines["[격자]"].startswith(f"[격자] 칸 {grid['cells']:,} = 전문가 {grid['experts']:,} × 단위 {grid['units']:,}"
                                     f" · 검토 {st['reviewed']:,}(카드 대조 {basis['cards']:,} · 배경 카드뿐"
                                     f" {basis['background']:,} · 역할만 {basis['role_only']:,})")
    assert f" · 미완 {st['failed']:,}(처분 전 {grid['failed_open']:,}) " in lines["[격자]"]
    assert f" · 범위 밖 대기 {grid['out_of_scope_pending']:,} " in lines["[격자]"]
    assert lines["[카드]"].startswith(f"[카드] 분모 {cards['denominator']:,} = ")
    assert (f"묶음 미확보 전문가 {cards['experts_without_pack']:,}명({cards['cells_without_pack']:,}칸"
            in lines["[카드]"])
    cap = res["truncation"]["offcard_capped"]
    assert f"카드 밖 상한 닿음 {cap['cells']:,}칸({cap['hits']:,}번)" in lines["[절단]"]
    assert f"서버·앱 대조 갈림 {res['citation']['check_disagree']:,}건" in lines["[인용]"]
    secs = res["seconds"]
    for label, stat in [*secs["kinds"].items(), ("전체", secs["all"]), ("자리 대기", secs["queued"])]:
        if stat["n"]:
            m = re.search(re.escape(label) + r" p50 ([\d.]+) · p95 ([\d.]+) · 최대 ([\d.]+) \(n=([\d,]+)\)", lines["[호출 초]"])
            assert m is not None, label
            assert (float(m.group(1)), float(m.group(2)), float(m.group(3)), int(m.group(4).replace(",", ""))) == (
                stat["p50"]["value"], stat["p95"]["value"], stat["max"]["value"], stat["n"]), label
        else:
            assert f"{label} 미측정(표본 0)" in lines["[호출 초]"], label
    assert f"기다림 {secs['waits']['total']:,}건(" in lines["[호출 초]"]
    tokens, total = res["pilot"]["tokens"], res["pilot"]["bytes"]["total"]
    assert f"토큰 입력 {tokens['in']:,} · 출력 {tokens['out']:,}" in lines["[실측]"]
    assert f"새 표 바이트 {total:,}(" in lines["[실측]"]
    for table, n in res["pilot"]["bytes"]["tables"].items():
        assert f"{table} {n:,}" in lines["[실측]"]
    assert lines["[기준]"].startswith(f"[기준] 밖 {len(res['out_of_bounds'])}항")
    assert f"견주지 못한 기준 {len(res['unchecked'])}항" in lines["[기준]"] or not res["unchecked"]
    head = text.split("\n")[0]
    assert head.startswith(f"[검토 품질 — 코드 계측 · 기준판 {res['policy_version']} · 모델 «{res['model']}»")
    assert f"원장 «{res['ledger_hash']}»" in head


def test_the_block_text_carries_the_json_numbers_and_passes_the_linter(store, monkeypatch):
    """문면의 수(비율·평균·표본 미달의 n·셈)는 json 의 수 그대로이고 판단어 린터를 지난다(WP5b 3.11.3 규칙 2·3·5·6). 표본 미달은
    '표본 수 미달(n=…)', 표본 0 은 '미측정(표본 0)' 이다 — 0% 로 적지 않는다."""
    key, _job, _fake, _order = _small(store, monkeypatch)
    block = review_quality.block(store, key)
    assert (block["key"], block["title"]) == ("quality", "검토 품질")
    _assert_text_is_the_json(block)
    lines = block["text"].split("\n")
    assert "뒤집힘(걸림 없음→걸림) 표본 수 미달(n=2)" in lines[1]
    assert "순서(fwd·rev 다름) 표본 수 미달(n=10)" in lines[5]
    assert lines[-1] == ("[기준] 밖 2항 — 절단(호출) 4.5% > 0.0% · 인용 대조(걸림 없음) 33.3% < 80.0% · 표본 미달로 견주지 못한"
                         " 기준 2항(순서(fwd·rev 다름), 뒤집힘(걸림 없음→걸림) 95% 상한)")


def test_the_full_grid_block_text_carries_the_json_numbers(store):
    key, _job, _fake, _order = _full(store)
    block = review_quality.block(store, key)
    _assert_text_is_the_json(block)
    assert block["text"].split("\n")[-1] == ("[기준] 밖 2항 — 인용 대조(걸림 없음) 75.0% < 80.0% · 순서(fwd·rev 다름) 16.7%"
                                             " > 10.0% · 표본 미달로 견주지 못한 기준 1항(뒤집힘(걸림 없음→걸림) 95% 상한)")


def test_a_target_without_cells_gets_one_line_and_no_zero_rates(store):
    """칸 원장이 없는 대상은 한 줄이다 — 옛 방식(panels)과 검토 잡 전의 카드 대조 대상. json 의 비율은 0 이 아니라 None 이다."""
    panels = rig.factories.make_diff_target(store, 40).target_key
    cells = rig.target(store)
    for key, line in ((panels, "[검토 품질 — 이 대상은 옛 방식이라 칸 원장이 없다]"),
                      (cells, "[검토 품질 — 이 대상은 카드 대조 방식인데 칸 원장이 아직 없다(검토 잡 전)]")):
        block = review_quality.block(store, key)
        assert block["text"] == line and render.lint_text(line)["ok"]
        res = block["json"]
        assert res["grid"]["cells"] == 0 and res["grid"]["in_scope"] is None
        assert res["truncation"]["calls"] == {"value": None, "num": 0, "den": 0, "threshold": {"max": 0.0},
                                              "within": None}
        assert res["citation"]["quote"]["all"]["value"] is None and res["pilot"]["calls_per_cell"]["value"] is None
        assert res["model"] is None and res["out_of_bounds"] == []
    assert review_quality.compute(store, cells)["grid"]["expected"] == 6 * 5      # 격자 분모는 칸이 없어도 로스터 × 단위


# ---------------------------------------------------------------- 진행판 배선
def test_the_progress_board_carries_the_quality_block_from_the_hook(store, monkeypatch):
    """진행판(progress_json)은 QUALITY_HOOK 이 낸 블록을 quality 칸에 싣는다 — 끝난 잡의 진행판은 끝난 원장의 수다."""
    monkeypatch.setattr(review_runner, "QUALITY_HOOK", review_quality.progress_hook)
    key = rig.target(store)
    before = review_quality.compute(store, key)["ledger_hash"]
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    rig.Rig(store, FakeReviewEngine({SEAL: fre.load("pack_ok.json")})).finish(job_id)
    quality = rig.progress(store, job_id)["quality"]
    assert quality["json"]["ledger_hash"] != before                   # 원장이 바뀌면 지문이 바뀐다
    assert (quality["key"], quality["job_id"]) == ("quality", job_id) and isinstance(quality["computed_at"], int)
    assert quality["json"] == review_quality.compute(store, key)
    assert quality["json"]["grid"]["by_state"]["reviewed"] == 5 and render.lint_text(quality["text"])["ok"]


def test_the_app_lifespan_plugs_the_quality_hook(client):
    assert review_runner.QUALITY_HOOK is review_quality.progress_hook


def test_the_policy_asset_names_only_metrics_compute_produces(store):
    """기준판의 열쇠는 compute 결과의 수치 경로다 — 이름이 어긋나면 기준이 조용히 안 걸린다."""
    policy = review_quality.load_policy()
    assert policy["policy_version"] == "rq-1"
    key, _job, _fake, _order = _full(store)
    res = review_quality.compute(store, key)
    for path in policy["thresholds"]:
        if path == "seconds.p95":
            assert all("threshold" in s["p95"] for s in [*res["seconds"]["kinds"].values(), res["seconds"]["all"]])
            continue
        assert _at(res, path)["threshold"] == policy["thresholds"][path], path
    for path, floor in policy["min_n"].items():
        assert _at(res, path)["min_n"] == floor, path
