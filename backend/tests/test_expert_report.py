# 전문가 보고서(m2-wp3b S10) — 코드 조립의 바이트 재현·점검표 무생략·200자 인용 표시·린터·쪽 나누기·묶음 실패 보고서를 루프의 원장으로 본다
"""입력은 생산자다 — 대상·단위는 합성 쌍 → 실제 캡처·diff → 단위 빌드, 판정·호출 원장과 마감(보고서를 얼린다)은 가짜 엔진을 꽂은
검토 루프(S8·S9)가 쓴다(tests/synth/review_rig.py). 보고서는 LLM 을 부르지 않으므로 같은 원장이면 같은 바이트다.
"""
from __future__ import annotations

import base64
import gzip
import json
import sys
import types

import pytest

from app import common, expert_report, export, render, units
from app.common import canonical_json
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

OWNER = rig.OWNER
SEAL = rig.SEAL


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _rid(alias: str) -> str:
    return next(c["record_id"] for c in fre.load("pack_ok.json")["cards"] if c["alias"] == alias)


def _unit_ids(store, key: str) -> list[str]:
    return [u["unit_id"] for u in units.load_units(store, key)]


def _run(store, key: str, *, scope, step: int = 61, **switches) -> FakeReviewEngine:
    job_id = rig.job(store, key, scope=scope)
    fake = FakeReviewEngine(rig.packs())
    for name, value in switches.items():
        setattr(fake, name, value)
    rig.Rig(store, fake).finish(job_id, step=step)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)
    return fake


def _rich(store, key: str, *, agents=(SEAL, rig.BACKGROUND_ONLY, rig.ZERO_CARDS), unit_ids=None) -> None:
    """걸림·보류·해당 없음·긴 인용·카드 밖 지적·넘김·필요 정보·메커니즘이 다 든 원장."""
    _run(store, key, scope={"agents": list(agents), **({"unit_ids": unit_ids} if unit_ids else {})},
         verdicts={_rid("K01"): ("yes", "FAIL"), _rid("K02"): ("yes", "WARNING"), _rid("K03"): ("unknown", "undetermined"),
                   _rid("K05"): ("no", "na")},
         long_quote={"K02"}, offcard_findings=1, handoff_to="rel", seen=["interface.seal_compression"],
         need="개스킷 홈 깊이 공차")


SECTION_BLOCKS = {"# 전문가 보고서": "background", "## 본 범위": "background", "## 카드 점검표": "results",
                  "## 배경 카드": "results", "## 판정하지 못한 카드": "results", "## 단위별 분석": "results",
                  "## 카드 밖 지적": "results", "## 올린 finding": "results", "## 다른 영역으로 넘김": "recommendation",
                  "## 필요한 추가 정보": "recommendation", "## 따져 본 메커니즘": "minutes", "## 검토 품질": "minutes"}


def _head(store, key: str, agent: str) -> dict:
    return dict(store.query_one("SELECT * FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?", (key, agent)))


# ---------------------------------------------------------------- 조립
def test_the_report_reassembles_to_the_same_bytes_and_the_revision_moves_only_when_it_changes(store):
    """마감이 얼린 보고서와 같은 원장으로 다시 조립한 보고서가 바이트로 같다(판번호·만든 시각은 JSON 에 없다 — m-07). 해시가
    같으면 판은 그대로이고, 둘째 잡이 단위를 더 보고 다시 마감하면 판이 하나 오른다."""
    key = rig.target(store)
    first, second = _unit_ids(store, key)[:2]
    _rich(store, key, agents=(SEAL,), unit_ids=[first])
    head = _head(store, key, SEAL)
    frozen = expert_report.load_report(store, key, SEAL)
    assert head["revision"] == 1 and head["report_bytes"] == len(canonical_json(frozen).encode("utf-8"))
    assert gzip.decompress(head["report_gz"]) == canonical_json(frozen).encode("utf-8")
    assert not {"revision", "finalized_at", "updated_at", "created_at"} & set(frozen["head"])
    again = expert_report.prepare(store, key, SEAL)
    assert canonical_json(again.report) == canonical_json(frozen)
    assert canonical_json(expert_report.build_report(store, key, SEAL)) == canonical_json(frozen)
    assert expert_report._report_columns(store, again.ledger, again.report, again.summary,
                                         now=common.now_epoch())["revision"] == 1
    assert again.summary == head["summary_md"]

    _rich(store, key, agents=(SEAL,), unit_ids=[second])
    later = _head(store, key, SEAL)
    assert (later["revision"], later["report_hash"] != head["report_hash"]) == (2, True)
    assert {u["unit_id"] for u in expert_report.load_report(store, key, SEAL)["scope"]["units"]
            if u["state"] == "reviewed"} == {first, second}


def test_the_checklist_has_a_row_for_every_checkable_card_on_every_card_unit_with_the_quote_to_compare(store):
    """점검표 — 점검 카드 × 카드로 본 단위마다 실효 판정 한 행이고 생략이 없다(행 수 == 실효 판정 행 수). 행마다 card:<record_id>
    #<section_id> 와 재대조 표기(quote_ok)를 실어 사람이 인용을 카드 원문과 견줄 수 있다. 200자를 넘는 인용은 200자만 싣고 원래
    길이를 적으며, 마크다운에 '…(cq N자 중 200자)' 가 붙는다. 넘긴 줄·필요 정보·메커니즘·카드 밖 지적이 각 절에 오고, 판정 행·
    카드 밖 줄은 그것이 들어간 finding 을 가리킨다."""
    key = rig.target(store)
    _rich(store, key, agents=(SEAL,))
    report = expert_report.load_report(store, key, SEAL)
    effective = store.query_one("SELECT COUNT(*) AS n FROM rr_card_verdicts WHERE target_key = ? AND agent_key = ?"
                                " AND is_effective = 1", (key, SEAL))["n"]
    rows = [r for card in report["checklist"] for r in card["rows"]]
    assert len(rows) == effective == 6 * len(_unit_ids(store, key)) and not any(r.get("missing") for r in rows)
    assert [c["alias"] for c in report["checklist"]] == ["K01", "K02", "K03", "K04", "K05", "K06"]
    for row in rows:
        assert row["quote_ref"].startswith(f"card:{report['checklist'][0]['record_id'][:8]}")
        assert row["quote_ok"] in (0, 1) and len(row["cq"]) <= expert_report.QUOTE_SHOW
    k02 = next(c for c in report["checklist"] if c["alias"] == "K02")["rows"]
    assert {(len(r["cq"]), r["cq_chars"], r["quote_ok"]) for r in k02} == {(200, 260, 0)}
    k01 = next(c for c in report["checklist"] if c["alias"] == "K01")["rows"]
    assert all(r["quote_ref"] == f"card:{_rid('K01')}#1" and r["quote_ok"] == 1 and r["finding_id"] for r in k01)
    md = expert_report.render_report_md(report)
    assert "…(cq 260자 중 200자)" in md and fre.LONG_QUOTE not in md
    assert [u["FAIL"] for u in report["by_unit"]] == [["K01"]] * len(_unit_ids(store, key))
    assert {(h["source"], h["to"]) for h in report["handoff"]} == {("sweep", "rel"), ("off_card", "rel")}
    needs = {x["text"]: x["from"] for u in report["needs_info"] for x in u["items"]}
    assert set(needs) == {fre.NEED, "개스킷 홈 깊이 공차"} and needs["개스킷 홈 깊이 공차"] == ["off_card"]
    assert {tuple(m["seen"]) for m in report["mechanisms"]} == {("interface.seal_compression",)}
    assert all(f["finding_id"] for f in report["off_card"])
    assert [u["record_id"] for u in report["unjudged_cards"]] == [fre.load("pack_ok.json")["unrenderable"][0]["record_id"]]
    assert [c["alias"] for c in report["background"]] == ["K07", "K08", "K09", "K10"]
    assert report["quality"] == {"status": "pending", "reason": "review_quality_absent"}


def test_every_sentence_the_code_writes_passes_the_judgement_linter(store, monkeypatch):
    """보고서 마크다운(모든 부분)·쪽 제목·요약에 코드가 쓴 판단어가 없다 — 카드 대조·배경 카드뿐·카드 0장·묶음 실패 전문가 전부.
    전문가·카드의 글은 «» 안에 있다."""
    key = rig.target(store)
    fake_errors = {"xd-syn-1": (502, fre.load("pack_errors.json")["card_fetch_failed"]["body"])}
    _run(store, key, scope={"agents": [SEAL, rig.BACKGROUND_ONLY, rig.ZERO_CARDS, "xd-syn-1"]}, step=2000,
         verdicts={_rid("K01"): ("yes", "FAIL"), _rid("K03"): ("unknown", "undetermined")}, offcard_findings=1,
         handoff_to="rel", need="개스킷 홈 깊이 공차", pack_errors=fake_errors)
    for agent in (SEAL, rig.BACKGROUND_ONLY, rig.ZERO_CARDS, "xd-syn-1"):
        report = expert_report.load_report(store, key, agent)
        for part in expert_report.PARTS:
            md = expert_report.render_report_md(report, part=part)
            assert render.lint_text(md)["violations"] == [], (agent, part)
        assert render.lint_text(_head(store, key, agent)["summary_md"])["violations"] == [], agent
        for page in expert_report.render_pages(report, 4000):
            assert render.lint_text(page["title"])["ok"], page["title"]


def test_the_pages_join_back_into_the_full_markdown_in_the_wp4_page_shape(store):
    """쪽을 차례로 이으면 full 마크다운과 같다(블록이 바뀌는 자리에서도 끊어 한 쪽에 블록 하나). 쪽 모양은 WP4 통합 보고서 쪽
    {page_no, kind, title, blocks{background, results, recommendation, minutes}} 이고 조각 하나보다 짧은 한도에서도 조각을 자르지
    않는다. 부분(part)·단위(unit_id)로 좁힌 마크다운과 쪽도 같은 규칙이다."""
    key = rig.target(store)
    _rich(store, key, agents=(SEAL,))
    report = expert_report.load_report(store, key, SEAL)
    full = expert_report.render_report_md(report)
    for size in (expert_report.PAGE_CHARS, 2000, 50):
        pages = expert_report.render_pages(report, size)
        assert [p["page_no"] for p in pages] == list(range(1, len(pages) + 1))
        assert all(set(p["blocks"]) == set(expert_report.BLOCKS) and p["kind"] == "expert_report" for p in pages)
        assert all(sum(1 for b in p["blocks"].values() if b) == 1 for p in pages)
        joined = "\n".join(t for p in pages for b in expert_report.BLOCKS for t in p["blocks"][b])
        assert joined == full
        for page in pages:                               # 절은 제 블록에 든다(머리·범위 → background, 넘김·필요 정보 → …)
            for block, texts in page["blocks"].items():
                assert all(block == want for t in texts for head, want in SECTION_BLOCKS.items() if t.startswith(head))
        assert all(len("\n".join(t for b in p["blocks"].values() for t in b)) <= size
                   or sum(len(b) for b in p["blocks"].values()) == 1 for p in pages)
    assert len(expert_report.render_pages(report)) < len(expert_report.render_pages(report, 2000))
    unit = _unit_ids(store, key)[1]
    cards = expert_report.render_report_md(report, part="cards", unit_id=unit)
    assert cards.startswith("## 카드 점검표") and "## 단위별 분석" not in cards
    assert "- 단위 2 —" in cards and "- 단위 1 —" not in cards
    narrowed = expert_report.render_pages(report, 2000, part="units", unit_id=unit)
    assert "\n".join(t for p in narrowed for b in expert_report.BLOCKS for t in p["blocks"][b]) == \
        expert_report.render_report_md(report, part="units", unit_id=unit)
    with pytest.raises(Exception) as exc:
        expert_report.render_report_md(report, part="nope")
    assert getattr(exc.value, "code", None) == "E100"


def test_an_expert_whose_pack_never_came_still_gets_a_report_that_says_nothing_was_seen(store):
    """카드 묶음을 끝내 받지 못한 전문가도 보고서 한 편을 갖는다(파일럿이 고른 사람마다 한 편) — 상태 blocked 와 그 까닭, 범위 안
    단위 전부가 '보지 못한 것' 이다. finding·의견 행은 없고 원장은 닫지 않는다."""
    key = rig.target(store)
    errors = {"xd-syn-1": (502, fre.load("pack_errors.json")["card_fetch_failed"]["body"])}
    _run(store, key, scope={"agents": [SEAL, "xd-syn-1"]}, step=2000, pack_errors=errors)
    head = _head(store, key, "xd-syn-1")
    assert (head["state"], head["revision"]) == ("blocked", 1)
    report = expert_report.load_report(store, key, "xd-syn-1")
    assert report["head"]["state"] == "blocked" and "card_fetch_failed" in report["head"]["why"]
    assert report["head"]["pack"] is None and report["checklist"] == [] and report["findings"] == []
    assert {(x["state"], x["why"]["code"]) for x in report["scope"]["unseen"]} == {("failed", "pack_unavailable")}
    assert len(report["scope"]["unseen"]) == len(_unit_ids(store, key))
    assert "아무 단위도 보지 않았다" in head["summary_md"]
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_seat_opinions WHERE panel_id = ?", (head["review_id"],))["n"] == 0
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_findings WHERE agent_key = ?", ("xd-syn-1",))["n"] == 0
    assert store.query_one("SELECT status FROM rr_coverage WHERE target_key = ? AND agent_key = ?",
                           (key, "xd-syn-1"))["status"] == "pending"
    assert expert_report.load_report(store, key, SEAL)["head"]["state"] == "ready"


def test_the_quality_section_comes_from_the_quality_module_when_it_is_there(store, monkeypatch):
    """품질 절은 S11 의 모듈이 있으면 그 계산(compute(…, agent_key=…))과 문면(block)을 싣고, 없으면 미측정이다(0 으로 채우지
    않는다). 모듈은 다른 걸음이 넣는다 — 여기서는 그 자리에 시험용 모듈을 앉혀 배선만 본다."""
    key = rig.target(store)
    _run(store, key, scope={"agents": [SEAL], "unit_ids": _unit_ids(store, key)[:1]})
    assert expert_report.load_report(store, key, SEAL)["quality"]["status"] == "pending"
    calls = []
    stub = types.ModuleType("app.review_quality")
    stub.compute = lambda store_, target_key, *, agent_key=None: calls.append((target_key, agent_key)) or {"cards": {
        "value": 1.0, "num": 6, "den": 6}}
    stub.block = lambda store_, target_key, *, agent_key=None: {"key": "quality", "title": "검토 품질",
                                                                 "text": "[검토 품질 — 코드 계측] 시험 문면", "json": {}}
    real = expert_report.importlib.util.find_spec
    monkeypatch.setitem(sys.modules, "app.review_quality", stub)
    monkeypatch.setattr(expert_report.importlib.util, "find_spec",
                        lambda name, *a: object() if name == "app.review_quality" else real(name, *a))
    report = expert_report.build_report(store, key, SEAL)
    assert report["quality"] == {"status": "measured", "json": {"cards": {"value": 1.0, "num": 6, "den": 6}},
                                 "text": "[검토 품질 — 코드 계측] 시험 문면"}
    assert calls == [(key, SEAL)]
    assert "[검토 품질 — 코드 계측] 시험 문면" in expert_report.render_report_md(report, part="summary")


def test_the_export_carries_the_report_with_card_quotes_at_200_and_the_summary_within_1500(store):
    """반출의 전문가 보고서(report_gz)에는 카드 인용이 판정당 200자뿐이고 원래 길이가 옆에 있다 — 보고서가 처음부터 표시 규칙대로
    조립된다(M2.md 5절 #21). 요약(summary_md)은 1,500자 안이다. 카드 절 본문은 보고서 어디에도 없다."""
    key = rig.target(store)
    _rich(store, key, agents=(SEAL,))
    rows = [json.loads(line) for line in export.iter_lines(store, OWNER)][1:]
    head = next(r["row"] for r in rows if r["table"] == "rr_expert_reports" and r["row"]["agent_key"] == SEAL)
    report = json.loads(gzip.decompress(base64.b64decode(head["report_gz"]["__b64__"])).decode("utf-8"))
    quotes = [r["cq"] for c in report["checklist"] for r in c["rows"]] + [f["q"] for f in report["off_card"] if f["q"]]
    assert quotes and max(len(q) for q in quotes) == 200
    assert {r["cq_chars"] for c in report["checklist"] for r in c["rows"] if r["cq_chars"]} == {260}
    assert len(head["summary_md"]) <= expert_report.SUMMARY_MAX
    text = json.dumps(report, ensure_ascii=False)
    bodies = [str(s["text"]) for c in fre.load("pack_ok.json")["cards"] for s in c["sections"] if len(str(s["text"])) > 40]
    assert not [b for b in bodies if b in text]
