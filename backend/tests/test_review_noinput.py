# 입력 결손 호출(재설계 M3 C3-3) — ECAD 가 없는 대상의 회로 전문가 셀이 noinput 한 번으로 닫히고 finding·보고서·품질에 실리는 것을 검토 루프 끝까지 본다
"""m3-cells 3.6 의 정산표 네 줄 · 다시 묻기 · 엔진 미지원 보류 · 모자란 답의 차감을 가짜 엔진과 실제 단위로 본다.

- 대상은 시험대(review_rig)의 합성 40건 → 단위 다섯이다. 합성 쌍에는 회로 소스가 없어 `mem` 영역 전문가는 입력 결손이다.
- 거르기는 끈다(분류는 test_review_filter.py) — 셀마다 입력 결손 호출이 그대로 돈다.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from app import config, expert_report, review_cells, review_quality, review_runner, units
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

MECH1 = "mech-syn-0"
MEM1, MEM2, MEM0 = "mem-syn-0", "mem-syn-1", "mem-syn-2"          # 회로(mem) — 1·2순위는 카드, 3순위는 카드 0장
ROSTER: tuple[dict, ...] = (
    {"key": MECH1, "domain": "mech", "relevance": 0.99},
    {"key": MEM1, "domain": "mem", "relevance": 0.99}, {"key": MEM2, "domain": "mem", "relevance": 0.9},
    {"key": MEM0, "domain": "mem", "relevance": 0.8},
)


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path, risk_review_concurrency=1, risk_review_filter="off")
    return risk_store


def _packs(roster) -> dict[str, dict]:
    ok, empty = fre.load("pack_ok.json"), fre.load("pack_empty.json")
    return {r["key"]: (fre.derive_pack(empty, r["key"], name="카드 0장", domain=r["domain"], keep="none") if r["key"] == MEM0
                       else fre.derive_pack(ok, r["key"], name=r["key"], domain=r["domain"])) for r in roster}


def _units(store, key: str) -> list[dict]:
    return units.load_units(store, key)


def _cell(store, key: str, unit_id: str, agent: str) -> dict:
    row = dict(store.query_one("SELECT * FROM rr_review_cells WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                               (key, unit_id, agent)))
    row["extras"] = json.loads(row["extras_json"]) if row["extras_json"] else {}
    return row


def _bodies(fake: FakeReviewEngine, agent: str, kind: str, unit_id: str | None = None) -> list[dict]:
    return [r["body"] for r in fake.calls("run") if r["body"]["expert"]["key"] == agent and r["body"]["kind"] == kind
            and (unit_id is None or (r["body"].get("unit") or {}).get("unit_id") == unit_id)]


# ---------------------------------------------------------------- 정산표 네 줄 · finding · 보고서 · 품질
def test_input_gap_cells_close_with_one_noinput_call_each_by_the_four_settle_rows(store):
    """회로 전문가 셀은 카드 대조·카드 밖 대신 단위마다 입력 결손 호출 한 번이다(훑기는 결측 블록을 싣는다). 정산표 — 영향 있음 →
    reviewed(impact) · 영향 모름 → no_input(unknown) · 전부 없음 + 확인할 항목 → no_input(request) · 전부 없음 + 까닭만 →
    reviewed(none). basis 는 noinput, 계획 카드 수는 비고 불변식이 지난다. 요청은 카드 전부(훑기 k 에 걸린 것 먼저)·전 카드 제목·
    영역 실마리를 단 결측 블록이다. 영향 줄이 finding(input_gap · judgement_claimed WARNING)이 되고 보고서에 입력 결손 절과 '입력이
    오면 확인할 것' 이 실리며 품질 폭포는 그 칸을 '입력 결손 호출로 본 칸' 으로 센다. 원장은 done_weak(input_gap:ecad_absent)다.
    카드 0장 회로 전문가는 역할만으로 같은 호출을 낸다. 카드 전문가는 종전대로다."""
    key = rig.target(store, ROSTER)
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(_packs(ROSTER))
    us = _units(store, key)
    b0, b1, b2 = (u["unit_id"] for u in us if u["kind"] == "bundle")
    boundary, glob = (next(u["unit_id"] for u in us if u["kind"] == k) for k in ("boundary", "global"))
    fake.noinput_q1 = {b0: ["yes", "no"], b1: ["unknown", "no"], b2: ["no"], boundary: ["no"]}
    fake.noinput_q2 = {b2: ["보드 고정점 주변 부품 배치"], boundary: [("", "입력이 와도 같다")]}   # 까닭만(자료 칸이 차 있어도)
    fake.sweep_k = {b0: ["K08"]}                                   # 배경 카드 하나 — 입력 결손 호출이 먼저 싣는다
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    assert review_cells.review_invariants(store, key) == []

    want = {b0: ("reviewed", "impact"), b1: ("no_input", "unknown"), b2: ("no_input", "request"),
            boundary: ("reviewed", "none"), glob: ("reviewed", "impact")}
    for agent in (MEM1, MEM2, MEM0):
        cells = {u: _cell(store, key, u, agent) for u in want}
        assert {u: (c["state"], c["extras"]["noinput"]["outcome"]) for u, c in cells.items()} == want, agent
        assert {(c["basis"], c["cards_expected"], c["charged"]) for c in cells.values()} == {("noinput", None, 0)}
        assert {c["extras"]["noinput"]["asks"] for c in cells.values()} == {1}
        assert len(_bodies(fake, agent, "noinput")) == 5
        assert _bodies(fake, agent, "verdict") == [] and _bodies(fake, agent, "offcard") == []
        assert dict(store.query_one("SELECT status, reason FROM rr_coverage WHERE target_key = ? AND agent_key = ?",
                                    (key, agent))) == {"status": "done_weak", "reason": "input_gap:ecad_absent"}
        head = dict(store.query_one("SELECT state, prompt_rev FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?",
                                    (key, agent)))
        assert head == {"state": "ready", "prompt_rev": review_runner.prompt_key(fake.limits(), review_runner.GAP_KINDS)}
    assert _bodies(fake, MECH1, "noinput") == [] and len(_bodies(fake, MECH1, "offcard")) == 5

    pack = _packs(ROSTER)[MEM2]
    order = [c["alias"] for c in pack["cards"]]
    (first,) = _bodies(fake, MEM2, "noinput", b0)
    assert [c["alias"] for c in first["cards"]] == ["K08"] + [a for a in order if a != "K08"]   # 훑기 k 에 걸린 것 먼저
    assert [d["alias"] for d in first["digest"]] == order and first["extra"]["known"] == []
    assert first["expect"]["prompt_rev"] == fake.base_limits["prompt_rev"]["noinput"]
    assert first["unit"]["missing"][0]["kind"] == "ecad"
    assert first["unit"]["missing"][0]["note"].endswith("이 영역이 볼 것 — 언더필·스택업.")
    (sweep,) = _bodies(fake, MEM2, "sweep")
    assert sweep["extra"]["missing"] == [{"kind": m["kind"], "note": m["note"]} for m in first["unit"]["missing"]]
    assert "missing" not in _bodies(fake, MECH1, "sweep")[0]["extra"]
    (role_only,) = _bodies(fake, MEM0, "noinput", b0)
    assert (role_only["cards"], role_only["digest"]) == ([], [])

    ledger = expert_report.load_ledger(store, key, MEM2)
    findings = expert_report.build_findings(store, ledger)["findings"]
    assert findings and {(f["input_gap"], f["off_card"], f["judgement_claimed"], f["judgement"]) for f in findings} == {
        (True, False, "WARNING", "WARNING")}
    assert {f["unit_ids"][0] for f in findings} == {b0, glob}
    report = expert_report.load_report(store, key, MEM2)
    gap = report["input_gap"]
    assert (gap["gaps"], gap["domain"], gap["hint"]) == (["ecad_absent"], "mem", "언더필·스택업")
    assert {u["unit_id"]: (u["state"], u["outcome"]) for u in gap["units"]} == want
    impact = next(u for u in gap["units"] if u["unit_id"] == b0)["impacts"]
    assert [(x["impact"], bool(x["finding_id"])) for x in impact] == [("yes", True), ("no", False)]
    assert impact[0]["record_id"] == next(c["record_id"] for c in pack["cards"] if c["alias"] == "K08")
    assert impact[0]["quote_ok"] == 1
    needs = {n["unit_id"]: n["items"] for n in report["needs_info"]}
    assert needs[b2] == [{"text": "보드 고정점 주변 부품 배치 — ECAD 배치·스택업", "from": ["noinput"]}]
    assert boundary not in needs
    text = expert_report.render_report_md(report, part="units")
    assert "## 입력 결손 — «ecad_absent» · 영역 «mem» · 이 영역이 볼 것 «언더필·스택업»" in text
    assert "결측 입력이 와야 볼 수 있다(입력 결손)" in text and "입력이 오면 확인할 것 «보드 고정점 주변 부품 배치»" in text
    assert expert_report.load_report(store, key, MECH1)["input_gap"] is None

    quality = review_quality.compute(store, key, agent_key=MEM2)
    total = len(pack["cards"]) + len(pack.get("unrenderable") or ())
    lines = {name: m["num"] for name, m in quality["cards"]["lines"].items()}
    assert (lines["noinput_reviewed"], lines["no_input"], lines["unjudged"], lines["judged"]) == (3 * total, 2 * total, 0, 0)
    assert quality["cards"]["residual"] == 0 and quality["cards"]["invariant"]["holds"] is True
    assert quality["grid"]["reviewed_by_basis"]["noinput"] == 3

    # 불변식이 입력 결손 결과 없는 입력 결손 셀을 잡는다
    store.execute("UPDATE rr_review_cells SET extras_json = '{}' WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                  (key, b0, MEM2))
    assert review_cells.review_invariants(store, key) == [f"(G4) 입력 결손 셀 {b0}×{MEM2} 에 입력 결손 결과가 없다."]


def test_maybe_more_asks_again_with_the_titles_so_far_at_most_three_more_times(store):
    """답이 maybe_more 면 받은 q1 제목을 known 에 실어 '이것 말고 더' 를 다시 묻는다 — 최대 3번 더(호출 넷). 다시 물은 답의 같은
    항목(q2)은 한 번만 남고, 제목은 다 다르게 쌓인다."""
    roster = (ROSTER[1],)
    key = rig.target(store, roster)
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(_packs(roster))
    unit_id = _units(store, key)[0]["unit_id"]
    fake.noinput_more = {unit_id: 5}
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    calls = _bodies(fake, MEM1, "noinput", unit_id)
    assert len(calls) == 4
    assert [len(c["extra"]["known"]) for c in calls] == [0, 2, 4, 6]
    assert [k["why"] for k in calls[2]["extra"]["known"]] == [f"보드 근접 계면 간극 축소 {n}" for n in range(1, 5)]
    assert {k["judgement"] for k in calls[1]["extra"]["known"]} == {"yes"}
    got = _cell(store, key, unit_id, MEM1)["extras"]["noinput"]
    assert [r["title"] for r in got["q1"]] == [f"보드 근접 계면 간극 축소 {n}" for n in range(1, 9)]
    assert [r["item"] for r in got["q2"]] == ["보드 고정점 주변 부품 배치", "근접 계면의 네트 경로"]
    assert (got["asks"], got["more"], got["outcome"]) == (4, "yes", "impact")
    others = [u["unit_id"] for u in _units(store, key)[1:]]
    assert {len(_bodies(fake, MEM1, "noinput", u)) for u in others} == {1}


def test_the_same_impact_said_again_is_kept_once(store):
    """다시 물은 답이 앞 답의 영향을 같은 제목으로 되풀이하면 한 번만 남는다(받은 q1 제목 기준)."""
    roster = (ROSTER[1],)
    key = rig.target(store, roster)
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(_packs(roster))
    unit_id = _units(store, key)[0]["unit_id"]
    fake.noinput_more = {unit_id: 1}
    fake.noinput_same_titles = True
    rig.Rig(store, fake).finish(job_id)
    assert len(_bodies(fake, MEM1, "noinput", unit_id)) == 2
    got = _cell(store, key, unit_id, MEM1)["extras"]["noinput"]
    assert [r["title"] for r in got["q1"]] == ["보드 근접 계면 간극 축소 1", "보드 근접 계면 간극 축소 2"]
    assert got["asks"] == 2


def test_an_engine_that_does_not_know_noinput_holds_the_job_without_charging(store, monkeypatch):
    """엔진의 limits.kinds 에 noinput 이 없으면 그 호출을 내지 않고 잡을 agent_outdated(300초 자동 재개)로 멈춘다 — 입력 결손 셀은
    차감 없이 pending 이고 카드 전문가는 이어 돈 셈이다. 엔진이 올라오면 저절로 이어 돌아 끝난다."""
    key = rig.target(store, ROSTER[:2])
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(_packs(ROSTER[:2]))
    fake.base_limits["kinds"] = ["sweep", "verdict", "offcard"]
    r = rig.Rig(store, fake)
    r.run(lambda: rig.state(store, job_id) == "paused")
    row = rig.job_row(store, job_id)
    assert row["hold_code"] == "agent_outdated" and "noinput" in row["error"]
    cells = [_cell(store, key, u["unit_id"], MEM1) for u in _units(store, key)]
    assert {(c["state"], c["charged"], c["tries"]) for c in cells} == {("pending", 0, 0)}
    assert _bodies(fake, MEM1, "noinput") == [] and _bodies(fake, MEM1, "sweep") == []
    fake.base_limits["kinds"] = ["sweep", "verdict", "offcard", "noinput", "summary"]
    r.run(lambda: rig.state(store, job_id) == "completed")
    assert {_cell(store, key, u["unit_id"], MEM1)["state"] for u in _units(store, key)} == {"reviewed"}


def test_a_short_or_cut_answer_is_a_content_failure_charged_to_the_cell(store, monkeypatch):
    """q2 가 한 줄도 없는 답은 결과를 낼 수 없어 내용 탓 실패(noinput_incomplete)다 — 한도(2)에서 failed. 마지막 답이 잘린 채
    끝났으면(finish_reason length · more 줄 없음) output_truncated 로 한 번 차감되고 다음 시도에서 닫힌다. 보충이 다 받아 낸 답은
    잘린 것이 아니다."""
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_max_charged=2))
    roster = (ROSTER[1],)
    key = rig.target(store, roster)
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(_packs(roster))
    first, second, third = (u["unit_id"] for u in _units(store, key)[:3])
    fake.noinput_q2 = {first: []}
    fake.truncate = {("noinput", None, second): "length", ("noinput", None, third): "repaired"}
    rig.Rig(store, fake).finish(job_id)
    short = _cell(store, key, first, MEM1)
    assert (short["state"], short["error_code"], short["charged"]) == ("failed", "noinput_incomplete", 2)
    assert len(_bodies(fake, MEM1, "noinput", first)) == 2
    cut = _cell(store, key, second, MEM1)
    assert (cut["state"], cut["charged"], cut["extras"]["noinput"]["outcome"]) == ("reviewed", 1, "impact")
    states = [c["output_truncated"] for c in store.query(
        "SELECT output_truncated FROM rr_review_calls WHERE target_key = ? AND unit_id = ? AND kind = 'noinput'"
        " ORDER BY started_at, rowid", (key, second))]
    assert states == [1, 0]
    # 첫 시도가 잘렸지만 보충이 끝까지 낸 답(마지막 finish_reason stop · more 줄 있음)은 잘린 답이 아니다 — 차감 없이 닫힌다
    repaired = _cell(store, key, third, MEM1)
    assert (repaired["state"], repaired["charged"], repaired["truncated"]) == ("reviewed", 0, 0)
    assert review_cells.review_invariants(store, key) == []


def test_a_contested_impact_stands_and_the_report_names_the_retraction_and_its_path(store):
    """검증된 철회가 입력 결손 q1(영향 있음)을 다퉜다(엔진 RB3-1 — result_noinput_contested 의 모양, contested_by 에 path · l): 영향은
    서고(셀 impact · finding), 보고서 입력 결손 절에 철회의 판정 · 이유 · 경로가 «» 안에 실린다."""
    key = rig.target(store, ROSTER)
    first = _units(store, key)[0]["unit_id"]
    job_id = rig.job(store, key, scope={"agents": [MEM1], "unit_ids": [first]})
    fake = FakeReviewEngine(_packs(ROSTER))
    fake.noinput_q1 = {first: ["yes"]}
    fake.contested = {"K01": {"verdict": ["no"], "cq": "철회가 댄 카드 문장", "quote": "ok",
                              "why": "결측 입력이 없어도 이 카드의 조건은 이 변경과 겹치지 않는다", "attempt": 2,
                              "path": "보드 고정점 → 근접 계면", "l": ["L01"]}}
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    cell = _cell(store, key, first, MEM1)
    assert json.loads(cell["extras_json"])["noinput"]["outcome"] == "impact"
    report = expert_report.load_report(store, key, MEM1)
    impact = report["input_gap"]["units"][0]["impacts"][0]
    contested = impact.get("contested") or {}
    assert (contested.get("path"), contested.get("l")) == ("보드 고정점 → 근접 계면", ["L01"])
    text = expert_report.render_report_md(report, part="units")
    assert ("검증된 철회가 이 영향을 다퉜다(영향은 선다) — «no» «결측 입력이 없어도 이 카드의 조건은 이 변경과 겹치지 않는다»"
            " · 경로 «보드 고정점 → 근접 계면»") in text
