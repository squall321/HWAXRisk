# narrative 카드 갈래 시험(m2-wp3b S4) — 얼린 묶음으로 card: 를 찾고 인용을 다시 대조하며 등급·수치·본문 비노출을 지킨다
"""카드 묶음(`card_pack`)이 없는 스코프는 지금 동작 그대로여야 한다(D-19 · D-24 — `test_atoms`·`test_cite_scope`·옛 타깃 골든이
그것을 지킨다). 이 파일은 묶음이 있는 스코프(`review_scope`)의 갈래를 본다. 카드는 엔진 계약 예제 `pack_ok.json` 이다."""
from __future__ import annotations

import copy
import json

import pytest

from app import cardpack, narrative
from app.common import canonical_json
from app.narrative import resolve_cites
from tests import factories
from tests.conftest import FIXTURES_DIR
from tests.test_atoms import first_finding, make_ctx, make_finding, make_spec

CONTRACT = FIXTURES_DIR / "card_review" / "contract"
AGENT = "mech-test-seal"
PACK = json.loads((CONTRACT / "pack_ok.json").read_text(encoding="utf-8"))
VIEW = cardpack.view_of(PACK)
K01 = "DOC-CCT-MECH-2026-0000000101"      # heuristic · 규격 있음 → 경험칙
K04 = "DOC-CCT-MECH-2026-0000000103"      # fact · 규격·출처 → 문헌·규격
K01_S1 = "정적 접착 실링 부위의 유효 접착폭은 최악 공차 누적에서도 0.8"          # 강조 기호를 뺀 1절 인용
K01_S2 = "후면 커버와 미들프레임 사이의 PSA 테이프 접착 계면에 적용한다."
K04_QUOTE = PACK["cards"][3]["sections"][0]["text"][:30]


def _ctx(**overrides):
    return make_ctx(card_pack=VIEW.record_cards, **overrides)


def _only(resolved: dict) -> dict:
    [row] = resolved["cites"]
    return row


# ---------------------------------------------------------------- 묶음이 없으면 지금 동작
def test_without_a_pack_card_refs_keep_the_old_path():
    row = _only(resolve_cites([{"ref": f"card:{K01}", "quote": K01_S1}], make_ctx()))
    assert (row["ok"], row["verified"], row["payload"], row["canonical"], row["quote_mismatch"]) == (
        True, False, None, None, False)
    assert "card_grade" not in row                                # 옛 길의 행 모양이 한 칸도 바뀌지 않는다
    assert narrative.canonical_text_for(f"card:{K01}", make_ctx()) is None


def test_panel_scope_defaults_carry_no_pack():
    ctx = make_ctx()
    assert (ctx.card_pack, ctx.card_scope, ctx.number_corpus) == (None, None, None)


# ---------------------------------------------------------------- 묶음에서 찾기
@pytest.mark.parametrize("ref,reason", [
    ("card:DOC-NOT-IN-PACK", "not_in_pack"),
    (f"card:{K01}#9", "section_not_in_card"),
])
def test_a_card_outside_the_pack_is_dangling(ref, reason):
    resolved = resolve_cites([{"ref": ref, "quote": ""}], _ctx())
    assert (_only(resolved)["dangling_reason"], resolved["dangling"]) == (reason, [ref])


def test_a_card_outside_the_scope_is_dangling():
    resolved = resolve_cites([{"ref": f"card:{K01}", "quote": ""}], _ctx(card_scope=frozenset({K04})))
    assert _only(resolved)["dangling_reason"] == "not_in_scope"


def test_the_payload_is_the_card_label_not_its_body():
    row = _only(resolve_cites([{"ref": f"card:{K04}#1", "quote": K04_QUOTE}], _ctx()))
    assert row["payload"] == {"record_id": K04, "card_id": "TSL-S-001", "type": "standard-summary",
                              "confidence": "fact", "grade": "문헌·규격"}
    assert (row["ok"], row["verified"], row["canonical"]) == (True, True, None)


def test_canonical_text_is_the_card_text_or_the_named_section():
    ctx = _ctx()
    assert narrative.canonical_text_for(f"card:{K01}", ctx) == cardpack.card_text(VIEW.record_cards[K01])
    assert narrative.canonical_text_for(f"card:{K01}#2", ctx) == PACK["cards"][0]["sections"][1]["text"]
    assert narrative.canonical_text_for(f"card:{K01}#9", ctx) is None
    assert narrative.canonical_text_for("card:DOC-NOT-IN-PACK", ctx) is None


# ---------------------------------------------------------------- 인용 재대조와 등급
def test_a_heuristic_card_quote_is_rule_of_thumb_and_a_sourced_fact_card_is_literature():
    ctx = _ctx(external_check=lambda _ref: True)
    heuristic = resolve_cites([{"ref": f"card:{K01}", "quote": K01_S1}], ctx)
    assert (_only(heuristic)["quote_mismatch"], _only(heuristic)["card_grade"]) == (False, "경험칙")
    assert narrative.evidence_grade_from_cites(heuristic, ctx) == "경험칙"
    fact = resolve_cites([{"ref": f"card:{K04}", "quote": K04_QUOTE}], ctx)
    assert (_only(fact)["quote_mismatch"], _only(fact)["card_grade"]) == (False, "문헌·규격")
    assert narrative.evidence_grade_from_cites(fact, ctx) == "문헌·규격"


@pytest.mark.parametrize("ref,quote", [
    (f"card:{K04}", "이 문장은 카드 본문 어디에도 없는 지어낸 인용 문장이다"),     # 지어낸 인용
    (f"card:{K04}", K04_QUOTE[:14]),                                             # 14자 — 하한 밑
    (f"card:{K04}", K01_S1),                                                     # 다른 카드의 문장
    (f"card:{K01}#2", K01_S1),                                                   # 적은 절이 아닌 절의 문장
])
def test_a_quote_not_in_the_frozen_text_does_not_raise_the_grade(ref, quote):
    ctx = _ctx()
    resolved = resolve_cites([{"ref": ref, "quote": quote}], ctx)
    row = _only(resolved)
    assert (row["quote_mismatch"], row["grade_ok"], row["card_grade"]) == (True, False, None)
    assert resolved["quote_mismatch"] == [ref] and narrative.evidence_grade_from_cites(resolved, ctx) == "경험칙"


def test_markdown_marks_and_shaken_space_still_match():
    shaken = "  후면\n 커버와 미들프레임   사이의 PSA 테이프 접착 계면에 적용한다. "
    row = _only(resolve_cites([{"ref": f"card:{K01}#2", "quote": shaken}], _ctx()))
    assert (row["quote_mismatch"], row["card_grade"]) == (False, "경험칙")


def test_an_empty_quote_card_cite_exists_but_grades_nothing():
    ctx = _ctx()
    resolved = resolve_cites([{"ref": f"card:{K04}", "quote": ""}], ctx)
    row = _only(resolved)
    assert (row["ok"], row["grade_ok"], row["card_grade"]) == (True, True, None)
    assert narrative.evidence_grade_from_cites(resolved, ctx) == "경험칙"


# ---------------------------------------------------------------- 수치 대조(P-05)
CORPUS = cardpack.card_text(VIEW.record_cards[K01]) + "\n후면 커버 PSA 폭 1.2 → 0.9 mm"


@pytest.mark.parametrize("record_ref", [f"card:{K01}", "card:MIS-R-001", f"card:{K01}#1"])
def test_card_reference_shapes_in_the_warrant_are_not_numbers(record_ref):
    """warrant 의 참조 표기([card:…])는 수치로 읽히지 않는다 — record_id·card_id 모양(…-0000000101 · MIS-R-001) 모두."""
    ctx = _ctx(number_corpus=CORPUS)
    resolved = resolve_cites([{"ref": f"card:{K01}", "quote": K01_S1}], ctx,
                             claim="PSA 폭이 1.2 에서 0.9 mm 로 줄어 하한 0.8 mm 에 가깝다",
                             warrant=f"근거 카드 [{record_ref}] «{K01_S1}»")
    assert resolved["unquoted_numbers"] == [] and resolved["quote_mismatch"] == []


def test_a_missing_number_is_listed_without_failing_the_quotes():
    """말뭉치에 없는 수치는 unquoted_numbers 에만 — 통과한 인용 전부를 불일치로 만들지 않는다. '15' 는 '0.15' 에 걸리지 않는다."""
    ctx = _ctx(number_corpus="유효 폭 0.15 mm")
    resolved = resolve_cites([{"ref": f"card:{K01}", "quote": K01_S1}], ctx, claim="폭 15 mm", warrant="")
    assert resolved["unquoted_numbers"] == ["15"]
    assert resolved["quote_mismatch"] == [] and _only(resolved)["card_grade"] == "경험칙"
    legacy = resolve_cites([{"ref": f"card:{K01}", "quote": K01_S1}], _ctx(), claim="폭 15 mm", warrant="")
    assert legacy["quote_mismatch"] == [f"card:{K01}"]                 # 말뭉치가 없으면 지금 식 그대로


# ---------------------------------------------------------------- 정규화한 finding 에 카드 본문이 없다(P-06)
def test_a_normalized_card_finding_carries_no_card_body():
    finding = first_finding(make_spec(findings=[make_finding(
        cites=[{"ref": f"card:{K01}#1", "quote": K01_S1}], evidence_grade="문헌·규격",
        claim="PSA 폭이 줄어 하한에 가깝다", warrant=f"근거 카드 [card:{K01}] «{K01_S1}»")]), _ctx())
    dumped = json.dumps(finding, ensure_ascii=False)
    for section in PACK["cards"][0]["sections"][1:]:
        assert section["text"] not in dumped
    assert K01_S2 not in dumped
    [row] = finding["_resolved_cites"]
    assert row["canonical"] is None and set(row["payload"]) == {"record_id", "card_id", "type", "confidence", "grade"}
    assert finding["evidence_grade"] == "경험칙" and finding["evidence_grade_claimed"] == "문헌·규격"
    assert finding["dangling"] == [] and finding["quote_mismatch"] == []


# ---------------------------------------------------------------- review_scope
def _target_with_calls(store) -> tuple[str, list[str]]:
    """스냅샷 둘(캡처 호출 원장 포함)·diff·타깃 — 전부 생산자 경로(freeze_snapshot·create_diff·create_target)."""
    project_id = factories.make_project(store)
    results = factories.fixture_adapter_results()
    calls = [{"tool": "list_parts", "args": {"q": 1}, "response": {"n": 1}}]
    base = factories.make_snapshot(store, project_id, results, label="DV1", calls=calls)
    revised = copy.deepcopy(results)
    factories.set_thickness(revised, "PLATE_1", 0.84)
    target = factories.make_snapshot(store, project_id, revised, label="DV2", calls=calls,
                                     captured_at=factories.CAPTURED_AT + 86400)
    diff = factories.make_diff(store, base["snapshot_id"], target["snapshot_id"])
    key = factories.make_target(store, "diff", diff["diff_id"], agents=factories.agents())
    ids = [r["call_id"] for r in store.query("SELECT call_id FROM rr_snapshot_calls WHERE snapshot_id IN (?, ?)",
                                             (base["snapshot_id"], target["snapshot_id"]))]
    return key, ids


def test_review_scope_is_the_target_scope_with_the_experts_pack(risk_store):
    key, snapshot_calls = _target_with_calls(risk_store)
    assert snapshot_calls
    frozen = cardpack.freeze_pack(risk_store, PACK, agent_key=AGENT)["pack_key"]
    pack = cardpack.load_pack(risk_store, AGENT, frozen)
    ctx = narrative.review_scope(risk_store, key, AGENT, "a" * 32, pack)
    _, fields = narrative._target_scope(risk_store, key)
    assert {k: getattr(ctx, k) for k in fields if k != "store"} == {k: v for k, v in fields.items() if k != "store"}
    assert (ctx.panel_id, ctx.seats, ctx.card_scope, ctx.number_corpus) == ("a" * 32, (AGENT,), None, None)
    assert ctx.card_pack is pack.record_cards and set(snapshot_calls) <= ctx.call_ids
    assert (ctx.brief_known, ctx.external_check) == (False, None)
    tool = _only(resolve_cites([{"ref": f"tool:{snapshot_calls[0]}", "quote": ""}], ctx))
    assert (tool["ok"], tool["verified"]) == (True, True)
    assert _only(resolve_cites([{"ref": "tool:not-a-call", "quote": ""}], ctx))["dangling_reason"] == "not_in_scope"


def test_evidence_bundle_calls_resolve(risk_store):
    """근거 꾸러미가 부른 호출(tool:b-…)을 인용한 finding 이 dangling 이 되지 않는다(P-07)."""
    key, _ = _target_with_calls(risk_store)
    target = risk_store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))
    factories.seed_raw(risk_store, "rr_units", {
        "target_key": key, "unit_id": "u-000000000001", "owner_sub": factories.OWNER,
        "project_id": target["project_id"], "rev_first": 1, "kind": "bundle", "unit_hash": "h", "cids_json": "[]",
        "builder_version": "units-1.0", "created_at": 1,
        "evidence_json": canonical_json({"calls": [{"call_id": "b-7c1e"}], "call_ids": ["b-8d2f"]})},
        reason="B 층 근거 꾸러미(M3)만 호출 id 를 적는다 — 단위 저장(U5)은 A 층이라 그 모양을 만들 생산자가 아직 없다")
    ctx = narrative.review_scope(risk_store, key, AGENT, "b" * 32, VIEW)
    assert {"b-7c1e", "b-8d2f"} <= ctx.call_ids
    finding = first_finding(make_spec(findings=[make_finding(
        raised_by=[AGENT], cites=[{"ref": "tool:b-7c1e", "quote": ""}, {"ref": f"card:{K04}", "quote": K04_QUOTE}])]),
        ctx)
    assert finding["dangling"] == [] and finding["unverified_refs"] == []


def test_an_expert_without_cards_has_an_empty_pack(risk_store):
    key, _ = _target_with_calls(risk_store)
    ctx = narrative.review_scope(risk_store, key, AGENT, "c" * 32, None)
    assert ctx.card_pack == {}
    assert _only(resolve_cites([{"ref": f"card:{K01}", "quote": ""}], ctx))["dangling_reason"] == "not_in_pack"
    with pytest.raises(TypeError):
        narrative.review_scope(risk_store, key, AGENT, "c" * 32, ["K01"])
