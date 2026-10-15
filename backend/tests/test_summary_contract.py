# 요약 호출의 대역 일치(재설계 M3 S3-12 C14 ②) — 앱이 보내는 요약 본문 · 가짜 요약 엔진의 답 · 앱의 대조가 엔진의 마지막 계약 예제와 같은 모양인지 본다
"""예제는 tests/fixtures/card_review/contract/ 이다(셀 꾸러미가 엔진 c4e4823 에서 복사 — 바이트 일치는 test_card_contract_copies).
엔진 클라이언트가 run_summary_*.sse 를 그대로 먹는 것은 test_engine_client_review 의 장면 재생(색인의 summary_ok · _repaired ·
_missing)이 본다. 원장은 생산자 경로다(검토 루프 → 사슬 → 종합 잡). C14 ①(쟁점 패널 SSE)은 단계 D 리허설이 실제 엔진의 프레임을
긁어 남긴 뒤 더한다.
"""
from __future__ import annotations

import json

import pytest

from app import config, synth
from tests.conftest import FIXTURES_DIR
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.fake_summary_engine import FakeSummaryEngine

CONTRACT = FIXTURES_DIR / "card_review" / "contract"
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}
EXPECT_KEYS = {"prompt_rev", "limits_rev", "limits_rev_kind"}         # run 의 expect — 보낸 칸만 견준다(M3.md 4.13)


def _load(name: str) -> dict:
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def _row_keys(rows) -> set[frozenset]:
    return {frozenset(r) for r in rows}


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def test_the_app_sends_the_summary_body_of_the_engine_example(store):
    """앱이 낸 요약 본문(영역 · 과제 종합)의 칸이 req_summary_domain 과 같다 — 위 칸 · summary{scope, rows, must_cover, blocks} ·
    행 {ref, text} · 블록 {name, title, text}. expect 는 예제의 칸을 다 싣고 계약 밖 칸이 없다."""
    example = _load("req_summary_domain.json")
    key = rig.target(store)
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {str(CARDS["K01"]["record_id"]): ("yes", "FAIL")}
    rig.Rig(store, fake).finish(job_id)
    engine = FakeSummaryEngine()
    synth.create_synth_job(store, key, owner_sub=rig.OWNER, requester_sub=rig.OWNER)
    worker = synth.SynthWorker(store, config.settings, engine)
    for _ in range(300):
        if worker.tick()["step"] == "idle":
            break
    kinds = {b["summary"]["scope"]["kind"] for b in engine.requests}
    assert kinds == {"domain", "target"}
    for body in engine.requests:
        assert set(body) == set(example) and set(body["summary"]) == set(example["summary"])
        assert set(body["summary"]["scope"]) == set(example["summary"]["scope"])
        assert _row_keys(body["summary"]["rows"]) == _row_keys(example["summary"]["rows"])
        assert _row_keys(body["summary"]["blocks"]) == _row_keys(example["summary"]["blocks"])
        assert set(example["expect"]) <= set(body["expect"]) <= EXPECT_KEYS
        assert (body["kind"], body["variant"], body["expert"]) == (example["kind"], example["variant"], example["expert"])


@pytest.mark.parametrize("plan,example", [("ok", "result_summary_ok.json"), ("missing", "result_summary_missing.json")])
def test_the_fake_summary_engine_answers_in_the_engine_examples_shape(plan, example):
    """가짜 요약 엔진이 예제 요청에 낸 답의 칸이 엔진 예제와 같다 — 위 칸 · 줄 {t, r, text, refs, from_attempt, checks{refs, text,
    nums_unsourced, coerced}} · quality · meta · extras. 빠진 must_cover 는 예제처럼 별칭(R…)이다."""
    want = _load(example)
    request = _load("req_summary_domain.json")
    got = FakeSummaryEngine({"*": plan}).run(request, email=rig.OWNER)
    assert set(got) == set(want)
    assert set(got["quality"]) == set(want["quality"]) and set(got["meta"]) == set(want["meta"])
    assert set(got["meta"]["usage"]) == set(want["meta"]["usage"]) and set(got["extras"]) == set(want["extras"])
    assert _row_keys(got["rows"]) == _row_keys(want["rows"])
    assert {frozenset(r["checks"]) for r in got["rows"]} == {frozenset(r["checks"]) for r in want["rows"]}
    assert {r["t"] for r in got["rows"]} <= set(synth.ROW_TYPES)
    assert bool(got["missing"]) == bool(want["missing"])
    assert all(m in got["meta"]["aliases"]["rows"] for m in got["missing"])
    assert all(m in want["meta"]["aliases"]["rows"] for m in want["missing"])


def test_the_app_reads_the_engine_examples_as_the_engine_meant_them():
    """앱의 대조와 옮기기가 엔진 예제를 그대로 읽는다 — ok · repaired 는 대조를 지나고, missing 은 빠진 must_cover 를 원래 참조
    (reg:…)로, 출처 없는 수가 선 줄도 짚어 다시 묻는다. 옮긴 객체의 머리·걸림·갈림·서술이 예제 줄과 같다. 빈 clipped({})는 잘림이 아니다."""
    request = _load("req_summary_domain.json")
    ok, repaired, missing = (_load(f"result_summary_{n}.json") for n in ("ok", "repaired", "missing"))
    for result in (ok, repaired):
        check = synth.check_summary(result, request["summary"])
        assert check == {"missing": [], "nums_unsourced": [], "refs_outside": [], "clipped": None, "ok": True}
    held = synth.check_summary(missing, request["summary"])
    alias = missing["meta"]["aliases"]["rows"]
    assert held["ok"] is False and held["missing"] == [alias[m] for m in missing["missing"]] == ["reg:000000000000"]
    flagged = [{"t": r["t"], "nums": r["checks"]["nums_unsourced"]} for r in missing["rows"] if r["checks"]["nums_unsourced"]]
    assert flagged and held["nums_unsourced"] == flagged                   # 예제의 출처 없는 수 줄도 그대로 짚는다
    assert synth.check_notes(held)[0] == "꼭 다룰 행 가운데 risk·conflict 줄에 없는 것: reg:000000000000"
    out = synth.to_output(ok)
    rows = {t: [r for r in ok["rows"] if r["t"] == t] for t in ("head", "risk", "conflict", "para")}
    assert out["headline"] == rows["head"][0]["text"]
    assert [(r["text"], r["refs"]) for r in out["key_risks"]] == [(r["text"], r["refs"]) for r in rows["risk"]]
    assert [(r["text"], r["refs"]) for r in out["conflicts"]] == [(r["text"], r["refs"]) for r in rows["conflict"]]
    assert out["narrative"] == "\n".join(r["text"] for r in rows["para"])
