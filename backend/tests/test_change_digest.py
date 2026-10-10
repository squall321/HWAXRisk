# 변경 요지 — 질문·지식카드 검색어가 변경 내용을 싣는다, diff_id 표식은 좌석이 그 diff 를 열 수 있을 때만(WP1 S11 · R-24·R-26 · P-06)
from __future__ import annotations

import json

from app import brief, config, planner, runner
from tests import factories


def test_every_event_code_has_a_phrase():
    """스키마가 허용하는 의미 이벤트 코드 전부가 구절표에 있다 — 없으면 질문에 코드 문자열이 그대로 선다."""
    schema = json.loads((factories._SCHEMAS / "rr_diff.v1.json").read_text(encoding="utf-8"))
    codes = schema["definitions"]["event"]["properties"]["code"]["enum"]
    assert sorted(set(codes) - set(brief.CHANGE_PHRASES)) == []


def test_panel_question_names_changed_parts(risk_store):
    """질문 끝이 '요약 첫 줄'(식별자뿐인 [대상] 줄 앞 200자)이 아니라 변경 요지다 — 부품 이름(«» 안)과 변화 구절이 선다."""
    synth = factories.make_diff_target(risk_store, 40)
    digest = brief.change_digest(risk_store, synth.target_key)
    question = runner.panel_question(risk_store, synth.target_key)
    assert digest["source"] == "rr_diff" and digest["text"] and f"변경 요지: {digest['text']}" in question
    assert "요약 첫 줄" not in question
    assert len(digest["text"]) <= brief.DIGEST_CHARS
    # 바닥(600자)에서는 다 못 싣고 남은 수를 종류별로 센다 — 조용히 빼지 않는다.
    assert digest["shown"] < digest["n_events"] and f"… 외 {digest['n_events'] - digest['shown']}건(" in digest["text"]
    first = digest["text"].split("; ")[0]
    assert first.startswith("«") and "»" in first
    # 넓은 창의 요지는 변경 전부다.
    wide = brief.change_digest(risk_store, synth.target_key, max_chars=brief.web_profile(500_000).inner(brief.DIGEST_CHARS))
    assert wide["shown"] == wide["n_events"] and "… 외 " not in wide["text"]


def test_question_without_changes_keeps_the_old_sentence_whole(risk_store):
    """이벤트 0건(자기 자신과의 비교) — 종전 꼴로 떨어지되 요약 첫 줄을 200자에서 끊지 않는다."""
    synth = factories.make_diff_target(risk_store, 3)
    same = factories.make_diff(risk_store, synth.target_snapshot_id, synth.target_snapshot_id)
    key = factories.make_target(risk_store, "diff", same["diff_id"], agents=factories.agents())
    assert brief.change_digest(risk_store, key)["source"] == "empty"
    first = risk_store.query_one("SELECT summary_text FROM rr_diffs WHERE id = ?",
                                 (same["diff_id"],))["summary_text"].split("\n")[0]
    assert runner.panel_question(risk_store, key).endswith(f"diff 요약 첫 줄: {first}")


def test_snap_question_digests_interferences_and_fired_rules(risk_store):
    project_id = factories.make_project(risk_store)
    snap = factories.make_snapshot(risk_store, project_id, factories.fixture_adapter_results(), label="DV1")
    key = factories.make_target(risk_store, "snap", snap["snapshot_id"], agents=factories.agents())
    digest = brief.change_digest(risk_store, key)
    assert digest["source"] == "rr_state" and "간섭" in digest["text"] and "규칙 R-001" in digest["text"], digest
    assert "변경 요지: " in runner.panel_question(risk_store, key)


def test_knowledge_query_rides_in_delib_opts_inside_the_portal_limit(risk_store):
    """지식카드 검색어(delib_opts.knowledge_query)는 변경 요지의 낱말이고 값 하나 600자 안이다 — 넘으면 포털이 요청 전체를
    422 로 거절한다. 잘랐으면 그 사실이 loss 에 남는다(R-26)."""
    synth = factories.make_diff_target(risk_store, 40)
    panel = planner.plan_next_panel(risk_store, synth.target_key, "A")
    loss: dict = {}
    opts = runner.build_delib_opts(risk_store, config.settings, panel, evidence=[], loss=loss)
    digest = brief.change_digest(risk_store, synth.target_key)
    query = opts["knowledge_query"]
    assert query and len(query) <= brief.KNOWLEDGE_QUERY_MAX
    assert digest["plain"].startswith(query)
    assert loss["knowledge_query_cut"] == {"chars": len(digest["plain"]), "kept": len(query)}
    # 변경이 없으면 키를 싣지 않는다(엔진은 종전대로 질문으로 찾는다).
    same = factories.make_diff(risk_store, synth.target_snapshot_id, synth.target_snapshot_id)
    key = factories.make_target(risk_store, "diff", same["diff_id"], agents=factories.agents())
    empty = runner.build_delib_opts(risk_store, config.settings, planner.plan_next_panel(risk_store, key, "A"),
                                    evidence=[])
    assert "knowledge_query" not in empty


def test_diff_id_mark_rides_only_when_the_seats_can_open_the_diff(risk_store):
    """`diff_id=<id>` 는 좌석 자격으로 그 diff 가 보일 때만 싣는다 — 사람 자격(소유자)은 보이고, 서비스 자격은 과제가 조직
    공개일 때만이다. 못 여는 자격에 실으면 엔진이 도구를 앞세우고 안내한 호출이 not_visible 로 떨어진다(P-06)."""
    synth = factories.make_diff_target(risk_store, 3)
    mark = f"diff_id={synth.diff_id}"
    assert runner.seats_can_read_diff(risk_store, synth.diff_id, "owner", factories.OWNER)
    assert not runner.seats_can_read_diff(risk_store, synth.diff_id, "service", None)
    assert not runner.seats_can_read_diff(risk_store, synth.diff_id, "requester", "stranger@example.com")
    risk_store.execute("UPDATE rr_projects SET mcp_visibility = 'org' WHERE id = ?", (synth.project_id,))
    assert runner.seats_can_read_diff(risk_store, synth.diff_id, "service", None)
    assert mark in runner.panel_question(risk_store, synth.target_key, diff_ref=True)
    assert "diff_id=" not in runner.panel_question(risk_store, synth.target_key)
