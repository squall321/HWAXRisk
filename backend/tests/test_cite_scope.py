# 인용 검증의 스코프와 대조 — 브리프가 실은 참조는 저장 때 해석되고, 대조는 정규화·값으로 하며, 확인 안 된 인용은 등급을 올리지 못한다(WP1 S12 · R-36·R-38~R-42)
from __future__ import annotations

import json

import pytest

from app import brief, character, narrative, render, routes, runner
from app.common import parse_ref
from tests import factories
from tests.test_atoms import CID_GAP, make_ctx


def _frozen_panel(store, target_key: str) -> tuple[dict, list[dict]]:
    """편성기 패널 + 러너와 같은 조립(`prior_evidence`)을 그 패널에 동결한다 — 좌석이 받은 브리프다."""
    panel = factories.plan_panel(store, target_key, "A")
    evidence = narrative.prior_evidence(store, target_key, seats=panel["seats"], panel_id=panel["id"])
    runner.freeze_brief(store, panel, evidence)
    return panel, evidence


@pytest.fixture
def no_field(monkeypatch):
    from app import field_source

    monkeypatch.setattr(field_source, "for_target", lambda *a, **k: None)


def test_refs_shown_in_the_brief_resolve_at_persist(risk_store, no_field):
    """브리프가 실은 참조 전부가 그 패널의 저장 스코프(`_panel_scope`)에서 해석된다 — 종전에는 스코프가 IR 을 싣지 않아
    E9 의 `warn:` 과 snap 타깃의 `d:` 가 늘 dangling 이었다(R-38). 새 참조 스킴을 브리프에 실으면 이 시험이 그것도 본다."""
    for kind in ("diff", "snap"):
        project_id = factories.make_project(risk_store)
        factories.make_dim(risk_store, project_id, "plate1_t", "node[asm=a_stack/stack_asm/plate_1].attrs.min_dim")
        results = factories.fixture_adapter_results()
        results[0]["warnings"] = [{"severity": "WARNING", "code": "auto_named", "ref": "a_stack.step#PART_9",
                                   "message": "이름이 자동 생성됐다"}]
        base = factories.make_snapshot(risk_store, project_id, results, label="DV1")
        revised = json.loads(json.dumps(results))
        next(n for n in revised[0]["nodes"] if n.get("label") == "PLATE_1")["attrs"]["min_dim"] *= 0.7
        target = factories.make_snapshot(risk_store, project_id, revised, label="DV2",
                                         captured_at=factories.CAPTURED_AT + 86400)
        ref_id = (factories.make_diff(risk_store, base["snapshot_id"], target["snapshot_id"])["diff_id"]
                  if kind == "diff" else target["snapshot_id"])
        key = factories.make_target(risk_store, kind, ref_id, agents=factories.agents())
        panel, evidence = _frozen_panel(risk_store, key)
        refs = narrative.cited_refs_in("\n".join(str(e.get("result") or "") for e in evidence))
        kinds = {parse_ref(r)["kind"] for r in refs}
        assert {"warn", "d"} <= kinds, (kind, refs)
        ctx = narrative._panel_scope(risk_store, panel["id"])[3]
        bad = {r: narrative._resolve_one(r, ctx, ()) for r in refs}
        assert {r: o["reason"] for r, o in bad.items() if not o["ok"]} == {}, kind


def test_narr_and_reg_refs_are_checked_against_the_frozen_brief(risk_store, no_field):
    """동결본이 있는 패널은 `narr:`·`reg:` 를 그 브리프의 참조로 대조한다 — 실린 것은 검증, 없는 것은 dangling(R-42).
    동결본이 없으면(옛 패널) 종전대로 미검증이다."""
    synth = factories.make_diff_target(risk_store, 3)
    panel, evidence = _frozen_panel(risk_store, synth.target_key)
    ctx = narrative._panel_scope(risk_store, panel["id"])[3]
    assert ctx.brief_known is True and ctx.brief_refs == frozenset(brief.collect_refs(evidence))
    outside = narrative._resolve_one("narr:" + "0" * 32 + "#F1", ctx, ())
    assert (outside["ok"], outside["reason"], outside["verified"]) == (False, "not_in_brief", True)
    risk_store.execute("UPDATE rr_panels SET brief_gz = NULL WHERE id = ?", (panel["id"],))
    old = narrative._panel_scope(risk_store, panel["id"])[3]
    assert old.brief_known is False and narrative._resolve_one("narr:" + "0" * 32 + "#F1", old, ())["verified"] is False


def test_scope_carries_rollups_and_versions(risk_store, no_field):
    """스코프가 서브어셈블리 접두와 IR 판을 싣는다 — 종전에는 비어 서브어셈블리 주체가 검증 없이 통과했다(R-42)."""
    synth = factories.make_diff_target(risk_store, 3)
    panel, _ = _frozen_panel(risk_store, synth.target_key)
    ctx = narrative._panel_scope(risk_store, panel["id"])[3]
    ir = json.loads(risk_store.query_one("SELECT ir_json FROM rr_snapshots WHERE id = ?",
                                         (synth.target_snapshot_id,))["ir_json"])
    prefixes = {row["path_prefix"] for row in (ir.get("rollups") or {}).get("by_assembly") or ()}
    assert prefixes and prefixes <= set(ctx.rollup_prefixes)
    assert ctx.versions.get("ir_version") == ir["ir_version"]


def test_get_ref_with_snapshot_scope_reads_real_ir_shape(risk_store):
    """REST 참조 해석이 실제 IR 모양(목록)을 편다 — 종전에는 목록에 `.get` 을 불러 AttributeError 였다(R-39)."""
    project_id = factories.make_project(risk_store)
    factories.make_dim(risk_store, project_id, "plate1_t", "node[asm=a_stack/stack_asm/plate_1].attrs.min_dim")
    snap = factories.make_snapshot(risk_store, project_id, factories.fixture_adapter_results(), label="DV1")
    ir = json.loads(risk_store.query_one("SELECT ir_json FROM rr_snapshots WHERE id = ?",
                                         (snap["snapshot_id"],))["ir_json"])
    view = narrative.scope_ir(ir)
    assert isinstance(view["nodes"], dict) and isinstance(view["dims_named"], dict)
    assert narrative.scope_ir(view) == view                                    # 이미 편 모양은 그대로
    with factories.routes_store(risk_store):
        out = routes.get_ref("d:plate1_t", snapshot_id=snap["snapshot_id"], ident=factories.ident())
    assert out["payload"]["text"].startswith("plate1_t=")


def test_unverified_refs_never_raise_the_grade():
    """확인 못 한 인용(채널 부재 — inc:·rpt:·card: 의 외부 확인, 동결본 없는 narr:·reg:)은 등급을 올리지 못한다. 버리지는
    않는다(unverified_refs 에 남는다). 지어낸 `inc:` 번호 하나로 최고 등급이 붙던 구멍이다(R-36)."""
    blind = make_ctx()
    for ref in ("inc:obj1", "rpt:RPT1", "card:does-not-exist", "narr:" + "1" * 32 + "#F1"):
        resolved = narrative.resolve_cites([{"ref": ref, "quote": ""}], blind)
        assert resolved["unverified"] == [ref] and resolved["dangling"] == []
        assert narrative.evidence_grade_from_cites(resolved, blind) == "경험칙", ref
    # 확인된 인용은 종전 등급 그대로다.
    seen = make_ctx(external_check=lambda _ref: True)
    assert narrative.evidence_grade_from_cites(
        narrative.resolve_cites([{"ref": "inc:obj1", "quote": ""}], seen), seen) == "측정"
    mixed = narrative.resolve_cites([{"ref": "inc:obj1", "quote": ""}, {"ref": CID_GAP, "quote": ""}], blind)
    assert narrative.evidence_grade_from_cites(mixed, blind) == "도구예측"


def test_stored_character_grades_are_not_recomputed_with_the_stricter_rule():
    """엄격해진 등급 규칙은 이미 저장된 것에 소급하지 않는다(사용자 결정 D-19) — 과제 성격 프로파일은 저장된 cites 로 읽을
    때마다 등급을 다시 내므로, 그 길은 종전 표 그대로다."""
    assert character.evidence_grade_of([{"ref": "card:rec1"}]) == "문헌·규격"
    assert character.evidence_grade_of([{"ref": "inc:obj1"}]) == "측정"


def _card_decision(target_key: str, seat_key: str) -> str:
    """확인 채널이 없는 `card:` 하나를 인용하고 '문헌·규격' 을 주장하는 finding 한 건의 결정문."""
    from tests.test_project_patch import _finding_spec

    spec = _finding_spec(target_key, seat_key)
    spec["findings"][0].update(cites=[{"ref": "card:REC-1", "quote": ""}], evidence_grade="문헌·규격")
    return "F1 낙하 시 상단 리브에 응력이 집중된다.\n\n```json\n" + json.dumps(spec, ensure_ascii=False) + "\n```\n"


def _panel_grades(store, panel_id: str, target_key: str) -> tuple[list[str], list[str]]:
    findings = store.query("SELECT evidence_grade FROM rr_findings WHERE panel_id = ?", (panel_id,))
    clusters = store.query("SELECT evidence_grade FROM rr_registry WHERE target_key = ?", (target_key,))
    return [r["evidence_grade"] for r in findings], [r["evidence_grade"] for r in clusters]


def test_resubmitting_a_panel_saved_before_the_stricter_rule_keeps_its_grades(risk_store, monkeypatch):
    """업그레이드 전에 done 으로 저장된 패널을 다시 제출해도(파싱 보정 등) 엄격해진 등급 규칙(확인 못 한 card:·inc:·rpt: 는
    세지 않는다 — R-36)이 그 패널에 소급되지 않는다(사용자 결정 D-19 · BQ-6). 종전에는 재제출의 저장이 새 규칙으로 등급을 다시
    내 '문헌·규격' 이 '경험칙' 으로 내려가고, 병합이 클러스터 등급을 다시 계산해 사람이 확정한 판정 옆의 숫자가 움직였다."""
    from app import planner

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    synth = factories.make_diff_target(risk_store, 3)
    panel = planner.plan_next_panel(risk_store, synth.target_key, "B")
    decision = _card_decision(synth.target_key, panel["seats"][0]["key"])
    turns = [{"round": 1, "persona": s["key"], "say": "발언"} for s in panel["seats"]]

    def submit() -> None:
        routes.complete_panel(panel["id"], engine="mcp", decision_text=decision, turns=turns, actor="syn",
                              owner_sub=factories.OWNER)

    # 업그레이드 전의 저장 — 그때 규칙(확인 못 한 인용도 셌다)으로 등급을 내고, 품질에는 규칙 판 표식이 없다.
    real = narrative.evidence_grade_from_cites
    with monkeypatch.context() as patch:
        patch.setattr(narrative, "evidence_grade_from_cites", lambda resolved, ctx=None: real(
            {**resolved, "cites": [{k: v for k, v in row.items() if k != "verified"} for row in resolved["cites"]]},
            ctx))
        submit()
    quality = json.loads(risk_store.query_one("SELECT quality_json FROM rr_panels WHERE id = ?",
                                              (panel["id"],))["quality_json"])
    quality.pop("grade_rules", None)
    risk_store.execute("UPDATE rr_panels SET quality_json = ? WHERE id = ?", (json.dumps(quality), panel["id"]))
    before = _panel_grades(risk_store, panel["id"], synth.target_key)
    assert before == (["문헌·규격"], ["문헌·규격"]), before

    submit()
    assert _panel_grades(risk_store, panel["id"], synth.target_key) == before
    stamped = json.loads(risk_store.query_one("SELECT quality_json FROM rr_panels WHERE id = ?",
                                              (panel["id"],))["quality_json"])
    assert stamped["grade_rules"] == narrative.GRADE_RULES_LEGACY        # 다음 재제출도 그 판이다


def test_a_panel_first_saved_now_keeps_the_current_rule_on_resubmit(risk_store, monkeypatch):
    """지금 처음 저장하는 패널은 지금 규칙이고 그 판을 품질에 남긴다 — 다시 내도 같은 규칙이다(판 표식이 있으면 옛 규칙으로
    되돌아가지 않는다)."""
    from app import planner

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    synth = factories.make_diff_target(risk_store, 3)
    panel = planner.plan_next_panel(risk_store, synth.target_key, "B")
    decision = _card_decision(synth.target_key, panel["seats"][0]["key"])
    turns = [{"round": 1, "persona": s["key"], "say": "발언"} for s in panel["seats"]]
    for _ in range(2):
        routes.complete_panel(panel["id"], engine="mcp", decision_text=decision, turns=turns, actor="syn",
                              owner_sub=factories.OWNER)
        assert _panel_grades(risk_store, panel["id"], synth.target_key) == (["경험칙"], ["경험칙"])
        quality = json.loads(risk_store.query_one("SELECT quality_json FROM rr_panels WHERE id = ?",
                                                  (panel["id"],))["quality_json"])
        assert quality["grade_rules"] == narrative.GRADE_RULES


def test_the_web_runner_stamps_the_grade_rule_it_saved_with(risk_store, tmp_path):
    """웹 러너가 저장한 패널도 등급 규칙 판을 품질에 남긴다 — 없으면 그 패널을 다시 낼 때 업그레이드 전 패널로 읽힌다."""
    run = factories.portal_panel_body(risk_store, tmp_path, 3).run
    quality = json.loads(risk_store.query_one("SELECT quality_json FROM rr_panels WHERE id = ?",
                                              (run["panel_id"],))["quality_json"])
    assert quality["grade_rules"] == narrative.GRADE_RULES


def test_number_tokens_match_by_value_not_substring():
    """수치 대조는 값으로 한다 — '5' 가 '0.15' 의 부분 문자열이라 통과하던 것을 막고, '1.2' 와 '1.200', '-16.7' 과 '−16.7' 은
    같은 수로 본다(R-41)."""
    ctx = make_ctx()
    quote = "PLATE_1↔PLATE_2 min_gap 0.000→0.018 mm"
    cite = [{"ref": CID_GAP, "quote": quote}]
    assert narrative.resolve_cites(cite, ctx, claim="간극 0.18 mm")["unquoted_numbers"] == ["0.18"]
    assert narrative.resolve_cites(cite, ctx, claim="간극 8 mm")["unquoted_numbers"] == ["8"]
    assert narrative.resolve_cites(cite, ctx, claim="간극이 0.0180 mm 로 줄었다")["unquoted_numbers"] == []
    signed = [{"ref": CID_GAP, "quote": "PLATE_1 min_dim 1.200→1.000 mm (−16.7%)"}]
    assert narrative._numbers_in("−16.7%") == narrative._numbers_in("-16.7 %")
    assert narrative.resolve_cites(signed, ctx, claim="두께가 -16.7% 줄고 1.2 mm 에서 1 mm 가 됐다")["unquoted_numbers"] == []


def test_quoting_a_brief_line_passes_the_quote_check(risk_store, no_field):
    """좌석이 브리프 줄(E2)의 «» 안 글을 옮겨 적으면 대조를 통과한다 — «»·줄바꿈·겹친 공백이 섞여도 같다(R-40)."""
    synth = factories.make_diff_target(risk_store, 40)
    panel, evidence = _frozen_panel(risk_store, synth.target_key)
    e2 = next(e for e in evidence if e["key"] == "E2")["result"].split("\n")
    line = next(ln for ln in e2 if ln.startswith("[c:") and "«" in ln)
    ref = line[1:line.index("]")]
    body = line[line.index("«") + 1:line.index("»")]
    ctx = narrative._panel_scope(risk_store, panel["id"])[3]
    for quote in (body, render.quote_source(body), body.replace(" ", "  ", 1), body.replace(" ", "\n", 1)):
        resolved = narrative.resolve_cites([{"ref": ref, "quote": quote}], ctx)
        assert resolved["quote_mismatch"] == [], (quote, resolved["cites"][0]["canonical"])
