# 2,000셀 원장의 완결 갱신 시간(재설계 M3 S3-5 · S3-8) — 로스터 400명 × 단위 5 에서 closure.refresh 와 보고서 판 조립이 제때 서는지 잰다
"""원장은 생산자 경로다 — 대상은 라우트(400명 로스터, 영역 15), 셀은 검토 잡의 격자, 검토는 가짜 검토 엔진의 루프와 검토 잡 끝의
사슬(판 · 병합)이다. 기본은 영역마다 대표 한 명이 단위 전부를 돈다(셀 75 검토 · 나머지는 범위 밖 대기 — 시험 시간). `RR_FULL=1` 이면
로스터 전원이 돈다(셀 2,000 검토 · dev 에서 약 110초). 시간 단언은 세 번 잰 가운데 가장 빠른 값이다(바쁜 박스의 흔들림을 덜어 낸다).
dev 실측(2026-10-14, 전원 검토) — refresh 0.12~0.13초 · 판 조립 0.16초.
"""
from __future__ import annotations

import os
import time

from app import closure, planner, review_quality, review_runner, synth
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

FULL = os.environ.get("RR_FULL") == "1"
SIZES = {"xd": 136, "mech": 44, "sim": 22, "rel": 17, "disp": 13, "cam": 13, "sh": 11, "std": 11, "material": 9,
         "pcb": 34, "pwr": 22, "rf": 22, "soc": 17, "passive": 17, "mem": 12}          # 합 400 — 회로 6영역 124명(입력 결손)
REFRESH_S = 1.0
ASSEMBLE_S = 2.0


def _fastest(fn, n: int = 3) -> tuple[float, object]:
    best, out = float("inf"), None
    for _ in range(n):
        tick = time.perf_counter()
        out = fn()
        best = min(best, time.perf_counter() - tick)
    return best, out


def test_refresh_and_report_assembly_stand_in_time_on_a_2000_cell_ledger(risk_store, monkeypatch, tmp_path):
    """400명 × 단위 5 = 셀 2,000 원장에서 완결 갱신(closure.refresh — 셀 셈 · 잔여 · 레벨 · 캐시 쓰기)이 1초, 보고서 판 조립이
    2초 안이다. 판의 머리 수는 같은 시점의 셀 셈이다."""
    rig.configure(monkeypatch, risk_store, tmp_path, risk_review_concurrency=8, risk_review_max_calls=10 ** 7)
    monkeypatch.setattr(review_runner, "QUALITY_HOOK", review_quality.progress_hook)     # main 의 lifespan 이 꽂는 그대로
    roster = [{"key": f"{d}-{i}", "domain": d, "relevance": round(0.99 - i * 0.001, 3)} for d, n in SIZES.items()
              for i in range(n)]
    assert len(roster) == 400
    key = rig.target(risk_store, roster)
    reps = {}
    for row in planner.review_order(risk_store, key):
        if row["domain"] not in reps or row["rank_in_domain"] < reps[row["domain"]]["rank_in_domain"]:
            reps[row["domain"]] = row
    job_id = rig.job(risk_store, key, scope=None if FULL else {"agents": [r["agent_key"] for r in reps.values()]})
    ok = fre.load("pack_ok.json")
    packs = {r["key"]: fre.derive_pack(ok, r["key"], name=r["key"], domain=r["domain"]) for r in roster}
    fake = FakeReviewEngine(packs)
    fake.verdicts = {str(c["record_id"]): ("yes", "FAIL") for c in ok["cards"][:2]}
    rig.Rig(risk_store, fake).finish(job_id, ticks=2000)
    assert rig.state(risk_store, job_id) == "completed"
    cells = risk_store.query_one("SELECT COUNT(*) AS n, SUM(state <> 'pending') AS closed FROM rr_review_cells"
                                 " WHERE target_key = ?", (key,))
    assert cells["n"] == 2000 and cells["closed"] == (2000 if FULL else 75)
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_registry WHERE target_key = ?", (key,))["n"] > 0
    refresh_s, result = _fastest(lambda: closure.refresh(risk_store, key))
    assert result["counts"]["cells"]["actual"] == 2000 and refresh_s < REFRESH_S, refresh_s
    assemble_s, report = _fastest(lambda: synth.assemble_report(risk_store, key, trigger="manual"))
    assert assemble_s < ASSEMBLE_S, assemble_s
    fresh = {k: v for k, v in closure.cell_counts(risk_store, key).items() if not k.startswith("_")}
    assert report["counts"]["cells"] == fresh["cells"]

