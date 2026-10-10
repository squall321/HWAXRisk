# 브리프 칸의 길이·건수 — 위생 상한과 선택 상한이 프로파일 배수로 늘고, 남는 자름은 원문 길이·남은 수를 밝힌다(절단 전수 조사 — 리스크 앱 B4·B8·B10·B11·B17·D1)
from __future__ import annotations

import json

from app import brief, identity, registry, render, routes
from tests import factories

WIDE = brief.web_profile(500_000)


def _precedent_target(store, claim: str) -> str:
    """다른 과제의 타깃에 사람이 올린 선례(주체 = 이 타깃 IR 의 부품) — 주체 경로로 이 타깃 E5+ 에 회수된다."""
    target = factories.make_diff_target(store, 40)
    prev = factories.make_diff_target(store, 3)
    subject = sorted(k for k in brief._subject_keys(store, target.target_snapshot_id) if "|" not in k)[0]
    ident = identity.Identity(email=factories.OWNER, display_name="사람", role="user", organization="qa",
                              anonymous=False, source="bearer")
    with factories.routes_store(store):
        routes.create_human_finding(prev.target_key, routes.HumanFindingBody(
            mechanism="mechanical", mechanism_detail="drop_stress", change_kind="dimension", subject_key=subject,
            subject_names=["HOOK_LATCH"], severity="중대", judgement="FAIL", claim=claim,
            cites=[{"ref": target.diff["semantic"]["events"][0]["cid"], "quote": "두께"}]), ident=ident)
    registry.invalidate(store, prev.target_key, target.target_key, [subject], mark_unraised=True)
    return target.target_key


def _line_with(result: str, needle: str) -> str:
    return next(ln for ln in result.split("\n") if needle in ln)


def test_a_long_precedent_claim_is_cut_with_its_length_on_a_small_window_and_whole_on_a_wide_one(risk_store):
    """선례 주장은 위생의 claim 상한(160자)에 묶여 말없이 끊겼다 — 바닥에서는 원문 길이를 밝히고, 넓은 창에서는 다 싣는다."""
    claim = "사람이 본 두께 변화 — " + "낙하 시 힌지 모서리 응력이 집중되는 구간이 넓어진다 " * 20
    key = _precedent_target(risk_store, claim)
    norm = render.norm_quote(claim)
    legacy = next(e for e in brief.build_brief(risk_store, key, shield_lint=True)["evidence"] if e["key"] == "E5")
    line = _line_with(legacy["result"], "] reg:")
    assert f"…({len(norm)}자 중 160자)" in line, line[-80:]
    wide = next(e for e in brief.build_brief(risk_store, key, shield_lint=True, profile=WIDE)["evidence"]
                if e["key"] == "E5")
    assert render.QUOTE_OPEN + norm + render.QUOTE_CLOSE in _line_with(wide["result"], "] reg:")


def test_rule_refs_beyond_the_floor_are_counted(risk_store):
    """발화한 규칙의 참조는 바닥에서 앞 3개만 싣고 남은 수를 밝힌다(종전 말없이) — 넓은 창에서는 전부다."""
    synth = factories.make_diff_target(risk_store, 40)
    ctx = brief._target_context(risk_store, synth.target_key)
    hits = json.loads(ctx["state"]["rule_hits_json"])
    fired = next(h for h in hits if h.get("pass") is False)
    fired["found"]["refs"] = [f"e:{i:012x}" for i in range(9)]
    ctx = {**ctx, "state": {**dict(ctx["state"]), "rule_hits_json": json.dumps(hits)}}
    legacy = brief._item_e9(ctx)["result"]
    assert "외 6건" in _line_with(legacy, f"rule:{fired['rule']}")
    wide = _line_with(brief._item_e9(ctx, WIDE)["result"], f"rule:{fired['rule']}")
    assert all(f"e:{i:012x}" in wide for i in range(9)) and "외 " not in wide


def test_a_long_warning_message_says_how_much_was_cut(risk_store):
    """IR 경고 문구가 위생의 message 상한(350자)을 넘으면 그 사실을 줄에 밝힌다 — 넓은 창에서는 다 싣는다."""
    project_id = factories.make_project(risk_store)
    results = factories.fixture_adapter_results()
    message = "이름이 자동 생성됐다 " * 60
    results[0]["warnings"] = [{"severity": "WARNING", "code": "auto_named", "ref": "a_stack.step#P9", "message": message}]
    snap = factories.make_snapshot(risk_store, project_id, results, label="DV1")
    key = factories.make_target(risk_store, "snap", snap["snapshot_id"], agents=factories.agents())
    norm = render.norm_quote(message)
    legacy = next(e for e in brief.build_brief(risk_store, key)["evidence"] if e["key"] == "E9")["result"]
    assert f"…({len(norm)}자 중 350자)" in _line_with(legacy, "warn:auto_named")
    wide = next(e for e in brief.build_brief(risk_store, key, profile=WIDE)["evidence"] if e["key"] == "E9")["result"]
    assert render.QUOTE_OPEN + norm + render.QUOTE_CLOSE in _line_with(wide, "warn:auto_named")


def test_every_contest_note_of_a_rejected_precedent_is_carried():
    """기각 선례 줄은 기각 사유를 전부 잇는다 — 종전에는 첫 건만 실려 두 번째 사유부터 좌석이 몰랐다."""
    row = {"merged_json": json.dumps({"subject_names": ["A", "B"],
                                      "contest_notes": [{"note": "첫 기각 사유"}, {"note": "둘째 기각 사유"}]}),
           "subject_key": "ck:1", "target_key": "diff:" + "0" * 32, "cluster_key": "k", "mechanism": "m",
           "mechanism_detail": "d", "status": "rejected", "rejected": 2, "support": 0, "status_source": "code"}
    line = brief._negative_line(row)
    assert "첫 기각 사유" in line and "둘째 기각 사유" in line


def test_reference_tokens_keep_whole_names(risk_store):
    """참조 토큰(`[d:<name>]`)의 이름은 자르지 않는다 — 잘린 이름의 토큰은 아무것도 가리키지 않는다."""
    name = "dim_" + "x" * 150
    assert brief._ref_name(name) == name
