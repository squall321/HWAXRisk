# 전문가 보고서(m2-wp3b S10) — 코드 조립의 바이트 재현·점검표 무생략·200자 인용 표시·린터·쪽 나누기·묶음 실패 보고서를 루프의 원장으로 본다
"""입력은 생산자다 — 대상·단위는 합성 쌍 → 실제 캡처·diff → 단위 빌드, 판정·호출 원장과 마감(보고서를 얼린다)은 가짜 엔진을 꽂은
검토 루프(S8·S9)가 쓴다(tests/synth/review_rig.py). 보고서는 LLM 을 부르지 않으므로 같은 원장이면 같은 바이트다.
"""
from __future__ import annotations

import base64
import copy
import gzip
import json

import pytest

from app import cardpack, common, expert_report, export, render, review_quality, routes, units
from app.common import canonical_json
from app.risk_store import RiskStore
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
    assert [u["FAIL"] for u in report["by_unit"]] == [[_rid("K01")]] * len(_unit_ids(store, key))   # record_id 가 열쇠(R3B-2)
    assert {(h["source"], h["to"]) for h in report["handoff"]} == {("sweep", "rel"), ("off_card", "rel")}
    needs = {x["text"]: x["from"] for u in report["needs_info"] for x in u["items"]}
    assert set(needs) == {fre.NEED, "개스킷 홈 깊이 공차"} and needs["개스킷 홈 깊이 공차"] == ["off_card"]
    assert {tuple(m["seen"]) for m in report["mechanisms"]} == {("interface.seal_compression",)}
    assert all(f["finding_id"] for f in report["off_card"])
    assert [u["record_id"] for u in report["unjudged_cards"]] == [fre.load("pack_ok.json")["unrenderable"][0]["record_id"]]
    assert [c["alias"] for c in report["background"]] == ["K07", "K08", "K09", "K10"]
    quality = report["quality"]
    assert quality["status"] == "measured" and quality["text"] == review_quality.block(store, key, agent_key=SEAL)["text"]
    assert quality["json"] == review_quality.compute(store, key, agent_key=SEAL)


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


def test_the_quality_section_comes_from_the_quality_module(store):
    """품질 절은 품질 수치 모듈(S11)의 전문가 몫 계산(compute(…, agent_key=…))과 문면(block)이다 — 요약에도 그 문면이 실린다.
    전문가 한 명 범위에서는 머리 상태(마감 순간에 바뀐다)를 싣지 않아 다시 조립해도 바이트가 같다(m-07)."""
    key = rig.target(store)
    _run(store, key, scope={"agents": [SEAL], "unit_ids": _unit_ids(store, key)[:1]})
    report = expert_report.load_report(store, key, SEAL)
    want = review_quality.block(store, key, agent_key=SEAL)
    assert report["quality"] == {"status": "measured", "json": review_quality.compute(store, key, agent_key=SEAL),
                                 "text": want["text"]}
    assert report["quality"]["json"]["grid"]["expert_states"] is None
    assert want["text"] in expert_report.render_report_md(report, part="summary")


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


# ---------------------------------------------------------------- 묶음이 바뀐 원장(R3B-2)
def _dropped_pack(pack: dict) -> tuple[dict, dict]:
    """첫 카드(K01)가 빠지고 나머지 별칭이 하나씩 당겨진 묶음 — 그사이 카드 저장소가 바뀐 박스. (새 묶음, 빠진 카드)."""
    changed = copy.deepcopy(pack)
    dropped = changed["cards"].pop(0)
    width = fre.alias_width(len(changed["cards"]))
    for i, card in enumerate(changed["cards"], 1):
        card["alias"] = f"K{i:0{width}d}"
    changed["cards_total"] = len(changed["cards"])
    changed["listed_total"] = len(changed["cards"]) + len(changed.get("unrenderable") or ())
    changed["checkable_n"] = sum(1 for c in changed["cards"] if c.get("checkable"))
    changed["chars_total"] = sum(int(c.get("chars") or 0) for c in changed["cards"])
    return changed, dropped


def _imported(store) -> None:
    """들여온 박스처럼 — 얼린 묶음이 없다(묶음은 반출하지 않는다, M2.md 5절 #22)."""
    store.execute("DELETE FROM rr_card_packs WHERE agent_key = ?", (SEAL,))
    cardpack.clear_cache()


def _effective_n(store, key: str, agent: str) -> int:
    return store.query_one("SELECT COUNT(*) AS n FROM rr_card_verdicts WHERE target_key = ? AND agent_key = ?"
                           " AND is_effective = 1", (key, agent))["n"]


@pytest.mark.parametrize("old_pack_kept", [False, True])
def test_a_report_over_cells_judged_with_different_packs_keeps_every_verdict_under_its_own_card(store, old_pack_kept):
    """R3B-2 — 단위 1 을 묶음 P1 로 K01=FAIL 로 본 뒤 묶음이 바뀌어(K01 이 빠지고 별칭이 당겨진 P2) 단위 2 를 P2 로 본다. 보고서는
    판정 행의 카드를 그 셀을 본 묶음에서 record_id 로 찾는다 — 점검표 행 수 == 실효 판정 행 수, FAIL 은 제 카드(빠진 카드) 아래에,
    같은 별칭(K01)을 받은 다른 카드 아래에 가지 않고, part 넷 모두 렌더된다. P1 이 이 박스에 남았으면 그 카드 머리를 P1 에서
    읽고(unit_pack), 없으면 판정 행의 id 로 적는다(verdict)."""
    key = rig.target(store)
    first, second = _unit_ids(store, key)[:2]
    pack = fre.load("pack_ok.json")
    _run(store, key, scope={"agents": [SEAL], "unit_ids": [first]}, verdicts={_rid("K01"): ("yes", "FAIL")})
    _imported(store)
    changed, dropped = _dropped_pack(pack)
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [second]})
    rig.Rig(store, FakeReviewEngine({**rig.packs(), SEAL: changed})).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    if old_pack_kept:
        cardpack.freeze_pack(store, pack, agent_key=SEAL)                # 앞 묶음도 이 박스에 있다(같은 박스에서 묶음이 바뀐 경우)
        prepared = expert_report.prepare(store, key, SEAL)
        report = prepared.report
    else:
        report = expert_report.load_report(store, key, SEAL)
    rows = [r for c in report["checklist"] for r in c["rows"] if not r.get("missing")]
    assert len(rows) == _effective_n(store, key, SEAL) == 6 + 5
    by_unit = {u["unit_id"]: u for u in report["by_unit"]}
    assert by_unit[first]["FAIL"] == [dropped["record_id"]] and by_unit[second]["FAIL"] == []
    gone = next(c for c in report["checklist"] if c["record_id"] == dropped["record_id"])
    assert gone["source"] == ("unit_pack" if old_pack_kept else "verdict")
    assert gone["title"] == (dropped["title"] if old_pack_kept else None)
    assert [(r["unit_id"], r.get("judgement"), r.get("missing_why")) for r in gone["rows"]] == [
        (first, "FAIL", None), (second, None, "not_in_unit_pack")]
    now_k01 = next(c for c in report["checklist"] if c["alias"] == "K01")
    assert now_k01["record_id"] == _rid("K02") and now_k01["source"] == "pack"
    assert {r["unit_id"]: r["alias"] for r in now_k01["rows"]} == {first: "K02", second: "K01"}
    assert {u["unit_id"]: u["pack_state"] for u in report["scope"]["units"] if u["state"] == "reviewed"} == {
        first: "earlier" if old_pack_kept else "absent", second: "current"}
    for part in expert_report.PARTS:
        md = expert_report.render_report_md(report, part=part)
        assert render.lint_text(md)["violations"] == [], part
    units_md = expert_report.render_report_md(report, part="units", unit_id=first)
    fail = units_md.split("#### judgement=FAIL 1장\n", 1)[1].split("\n", 1)[0]
    assert f"card:{dropped['record_id']}" in fail and f"card:{_rid('K02')}" not in fail
    cards_md = expert_report.render_report_md(report, part="cards")
    assert "이 단위를 본 카드 묶음에서는 점검 카드가 아니었다" in cards_md and "그 단위를 본 묶음의 별칭 K02" in cards_md


def test_a_blocked_outcome_after_a_real_report_keeps_that_report_and_says_why_beside_it(store):
    """R3B-2 — 앞 잡이 얼린 실제 보고서(ready·partial)가 있는 전문가가 다음 잡에서 묶음을 끝내 받지 못하면(들여온 박스 · 404) 그 보고서를
    점검표 0행 보고서로 덮지 않는다. 판은 그대로이고, 막힘은 머리의 상태(blocked)와 까닭(error → REST·MCP 의 state_why)으로 곁에
    남는다. 그 보고서의 part 넷이 렌더된다."""
    key = rig.target(store)
    first, second = _unit_ids(store, key)[:2]
    _run(store, key, scope={"agents": [SEAL], "unit_ids": [first]}, verdicts={_rid("K01"): ("yes", "FAIL")})
    before = _head(store, key, SEAL)
    _imported(store)
    _run(store, key, scope={"agents": [SEAL, "mech-syn-0"], "unit_ids": [second]}, step=2000,
         pack_errors={SEAL: (404, fre.load("pack_errors.json")["agent_not_found"]["body"])})
    after = _head(store, key, SEAL)
    assert after["state"] == "blocked" and "agent_not_found" in after["error"]
    assert (after["revision"], after["report_hash"], after["report_gz"], after["summary_md"]) == (
        before["revision"], before["report_hash"], before["report_gz"], before["summary_md"])
    report = expert_report.load_report(store, key, SEAL)
    assert report["head"]["state"] == "partial" and len(report["checklist"]) == 6        # 범위 밖 단위가 남은 앞 마감
    assert next(u for u in report["by_unit"] if u["unit_id"] == first)["FAIL"] == [_rid("K01")]
    for part in expert_report.PARTS:
        expert_report.render_report_md(report, part=part)
    meta, _body = routes.expert_report_source(key, SEAL, owner_sub=OWNER)
    assert (meta["state"], meta["version"]) == ("blocked", before["revision"]) and "agent_not_found" in meta["state_why"]


# ---------------------------------------------------------------- 인용 대조 표기(R3B-4)
def test_the_quote_mark_says_why_a_quote_did_not_pass_and_never_calls_a_card_quote_a_mismatch(store, monkeypatch):
    """quote_ok = 0 하나가 덮던 갈래를 가른다 — 카드 글 그대로지만 15자 밑(short), 앱 재대조는 찾고 엔진만 못 찾음(app_only — 그
    절 번호를 단다), 엔진만 찾았다고 함(engine_only — 둘이 갈림), 둘 다 못 찾음(not_found), 둘 다 찾음(ok). 맞는 인용을 '불일치' 로
    적지 않는다."""
    key = rig.target(store)
    first = _unit_ids(store, key)[0]
    orig = FakeReviewEngine._verdict_row

    def row(self, alias, card, own, lines, *, variant=None):
        out = orig(self, alias, card, own, lines, variant=variant)
        if alias == "K01":
            out["cq"], out["checks"]["quote"], out["checks"]["quote_sid"] = str(card["sections"][0]["text"])[:12], "short", ""
        if alias == "K03":
            out["checks"]["quote"] = "not_found"                         # 카드 글 그대로인데 엔진 검사만 못 찾았다
        return out

    monkeypatch.setattr(FakeReviewEngine, "_verdict_row", row)
    _run(store, key, scope={"agents": [SEAL], "unit_ids": [first]}, invented_quote={"K02"}, lying_quote={"K04"})
    report = expert_report.load_report(store, key, SEAL)
    states = {c["alias"]: c["rows"][0]["quote_state"] for c in report["checklist"]}
    assert states == {"K01": "short", "K02": "not_found", "K03": "app_only", "K04": "engine_only", "K05": "ok", "K06": "ok"}
    assert {c["alias"]: c["rows"][0]["quote_ok"] for c in report["checklist"]} == {
        "K01": 0, "K02": 0, "K03": 0, "K04": 0, "K05": 1, "K06": 1}
    md = expert_report.render_report_md(report, part="cards")
    quote_lines = {line.split("card:", 1)[1].split(" ", 1)[0]: line for line in md.split("\n") if "  - 카드 인용 card:" in line}
    by_alias = {c["alias"]: c["rows"][0]["quote_ref"][len("card:"):] for c in report["checklist"]}
    assert "대조 하한(15자 · 실질 글자 10자) 밑이라 대조하지 않았다" in quote_lines[by_alias["K01"]]
    assert "카드 글에 없다 — 앱 재대조·엔진 검사 둘 다 찾지 못했다" in quote_lines[by_alias["K02"]]
    assert by_alias["K03"].endswith("#1") and "앱 재대조는 카드 글에서 찾았고(절 1) 엔진 검사는 찾지 못했다" in quote_lines[by_alias["K03"]]
    assert "엔진 검사는 찾았다고 했고 앱 재대조는 카드 글에서 찾지 못했다" in quote_lines[by_alias["K04"]]
    assert "앱 재대조·엔진 검사 둘 다 카드 글에서 찾았다" in quote_lines[by_alias["K05"]]
    assert "불일치" not in md and render.lint_text(md)["violations"] == []


def test_a_verdict_that_needed_refs_and_gave_none_is_labelled_as_missing_refs(store):
    """R3B-5 — applies=yes 인데 참조가 빈 행(refs_ok 0)은 '그 단위 밖 참조가 섞였다' 가 아니라 참조를 대지 않았다고 적는다. 참조가
    필요 없는 행(해당 없음 — refs_ok NULL)은 '참조 없음', 그 단위 줄을 댄 행은 '그 단위 소속' 이다."""
    key = rig.target(store)
    first = _unit_ids(store, key)[0]
    _run(store, key, scope={"agents": [SEAL], "unit_ids": [first]}, no_refs={"K02"}, verdicts={_rid("K05"): ("no", "na")})
    report = expert_report.load_report(store, key, SEAL)
    rows = {c["alias"]: c["rows"][0] for c in report["checklist"]}
    assert (rows["K02"]["refs"], rows["K02"]["refs_ok"], rows["K05"]["refs_ok"], rows["K01"]["refs_ok"]) == ([], 0, None, 1)
    md = expert_report.render_report_md(report, part="cards")
    blocks = {c["alias"]: md.split(f"### {c['alias']} ", 1)[1].split("\n###", 1)[0] for c in report["checklist"]}
    assert "참조가 필요한 행인데 판정에 쓴 변경 줄을 대지 않았다" in blocks["K02"] and "그 단위 밖" not in blocks["K02"]
    assert "변경 줄 없음 — 참조 없음" in blocks["K05"] and "— 그 단위 소속" in blocks["K01"]


def test_line_breaks_inside_quotes_and_model_text_do_not_open_headings_or_lists(store, monkeypatch):
    """R3B-6 — 카드 인용(카드 글 그대로 두 줄, 둘째 줄이 '## ' 로 시작)과 모델 글(이유 — '- ' 로 시작하는 둘째 줄)의 줄바꿈은 마크다운에
    펼 때 ⏎ 로 접혀 새 제목·목록을 만들지 않는다. JSON 의 인용과 판정 행의 글은 그대로이고 인용은 재대조를 지난다."""
    key = rig.target(store)
    first = _unit_ids(store, key)[0]
    pack = copy.deepcopy(fre.load("pack_ok.json"))
    section = pack["cards"][0]["sections"][0]
    section["text"] = "정적 접착 실링 부위의 유효 접착폭은 최악 공차 누적에서도 0.8 mm 이상을 남긴다.\n## 폭이 줄면 코너 R 도 함께 본다."
    pack["cards"][0]["text_sha"] = cardpack.text_sha(pack["cards"][0]["sections"])
    quote = "최악 공차 누적에서도 0.8 mm 이상을 남긴다.\n## 폭이 줄면 코너 R 도"
    orig = FakeReviewEngine._verdict_row

    def row(self, alias, card, own, lines, *, variant=None):
        out = orig(self, alias, card, own, lines, variant=variant)
        if alias == "K01":
            out["cq"], out["checks"]["quote"] = quote, "ok"
            out["why"] = "조건을 맞대었다.\n- 둘째 줄이 목록처럼 보인다"
        return out

    monkeypatch.setattr(FakeReviewEngine, "_verdict_row", row)
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [first]})
    rig.Rig(store, FakeReviewEngine({**rig.packs(), SEAL: pack})).finish(job_id)
    report = expert_report.load_report(store, key, SEAL)
    k01 = next(c for c in report["checklist"] if c["alias"] == "K01")["rows"][0]
    assert (k01["cq"], k01["quote_state"], k01["why"]) == (quote, "ok", "조건을 맞대었다.\n- 둘째 줄이 목록처럼 보인다")
    for part in expert_report.PARTS:
        md = expert_report.render_report_md(report, part=part)
        assert not [line for line in md.split("\n") if line.startswith(("## 폭이", "- 둘째"))], part
        assert render.lint_text(md)["violations"] == [], part
    cards = expert_report.render_report_md(report, part="cards")
    assert "«최악 공차 누적에서도 0.8 mm 이상을 남긴다. ⏎ ## 폭이 줄면 코너 R 도»" in cards
    assert "«조건을 맞대었다. ⏎ - 둘째 줄이 목록처럼 보인다»" in cards


# ---------------------------------------------------------------- 들여온 박스에서 다시 마감(R3B-7)
def test_refinalizing_on_an_importing_box_keeps_the_original_length_of_clipped_quotes(store, monkeypatch, tmp_path):
    """반출은 카드 인용을 200자로 줄이고 원래 길이를 적는다. 들여온 박스에서 같은 전문가의 남은 단위를 돌아 다시 마감하면(#22 — 묶음은
    다시 받는다) 보고서 행·finding 인용·근거 문장·인용 역색인이 200자 글을 원문으로 여기지 않고 원래 길이(cq_chars → quote_chars ·
    warrant_chars)를 이어받는다. 그 박스에서 다시 반출해도 길이가 남는다."""
    key = rig.target(store)
    first, second = _unit_ids(store, key)[:2]
    _run(store, key, scope={"agents": [SEAL], "unit_ids": [first]}, verdicts={_rid("K01"): ("yes", "FAIL")},
         long_quote={"K01"}, cond_text=("카드가 요구하는 적용 조건을 길게 옮긴 글 — " * 12)[:240])
    dest = RiskStore(tmp_path / "dest" / "risk_review.db")
    dest.open()
    dest.migrate()
    try:
        export.import_jsonl(dest, OWNER, "".join(export.iter_lines(store, OWNER, 0)))
        (tmp_path / "destdata").mkdir()
        rig.configure(monkeypatch, dest, tmp_path / "destdata")
        _run(dest, key, scope={"agents": [SEAL], "unit_ids": [second]}, verdicts={_rid("K01"): ("yes", "FAIL")})
        rebuilt = expert_report.load_report(dest, key, SEAL)
        k01 = next(c for c in rebuilt["checklist"] if c["alias"] == "K01")
        row = next(r for r in k01["rows"] if r["unit_id"] == first)
        assert (len(row["cq"]), row["cq_chars"]) == (200, 260)
        assert {(len(c["cond"]), c["cond_chars"]) for c in row["conds"]} == {(200, 240)}
        assert "…(cq 260자 중 200자)" in expert_report.render_report_md(rebuilt, part="cards", unit_id=first)
        finding = json.loads(dest.query_one("SELECT finding_json FROM rr_findings WHERE source_kind = 'card_review'"
                                            " AND unit_id = ?", (first,))["finding_json"])
        assert [(len(c["quote"]), c.get("quote_chars")) for c in finding["cites"] if c["ref"].startswith("card:")] == [(200, 260)]
        assert finding["warrant_chars"] == [260]
        refs = [dict(r) for r in dest.query("SELECT quote, quote_chars FROM rr_claim_refs WHERE ref_type = 'card' AND claim_uid"
                                            " IN (SELECT finding_id FROM rr_findings WHERE unit_id = ?)", (first,))]
        assert [(len(r["quote"]), r["quote_chars"]) for r in refs] == [(200, 260)]
        again = [json.loads(x) for x in export.iter_lines(dest, OWNER, 0)][1:]
        out = [x["row"] for x in again if x["table"] == "rr_claim_refs" and x["row"]["ref_type"] == "card"]
        assert {(len(r["quote"]), r["quote_chars"]) for r in out} >= {(200, 260)}
        second_row = next(r for r in k01["rows"] if r["unit_id"] == second)
        assert second_row["cq_chars"] is None and len(second_row["cq"]) < 200       # 이 박스에서 본 단위는 원문 그대로다
    finally:
        dest.close()
