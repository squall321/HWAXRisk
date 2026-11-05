# 외부 사례 DB(SIREN)의 지정 도구를 리스크 패널에 싣는다 — 손잡이 · 게이트웨이 지도 · 남은 자리 · 미연결 표지(HWAXPortal docs/siren-delib RK-12)
"""HWAXPortal docs/siren-delib RK-12 · 사용자 결정 11-06.

  · 보통 패널은 지정 도구 상한(6)의 남은 자리만큼, 쟁점 패널은 상한까지 HWAXRISK_CASE_TOOLS 차례(기본 SIREN 의 그룹 목록 → 사례 검색 → 사례 카드)로
    싣는다 — 게이트웨이 /tools-map 이 그 이름을 내놓을 때만(SIREN 이 없는 박스는 그대로).
  · 잡 주인의 토큰이 없거나(401) 그쪽 한도(429)에 걸리면 엔진이 경고(conn_unregistered · conn_rate_limited)를 낸다 — 엔진 클라이언트가 이름 ·
    백엔드 · 도구를 받아 두고, 러너가 패널 품질 표지로 옮기고, 보고서 쟁점 줄이 '○○ 미연결' 로 보인다.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import config, engine_client, planner, runner, synth
from app.adapters import registry as adapters_registry
from tests.test_planner import make_target

SIREN = ("siren_list_groups", "siren_search_cases", "siren_get_case")
GW_MAP = {**{n: "siren" for n in SIREN}, "list_interfaces": "heax-step_forge"}


# ---------------------------------------------------------------- 손잡이
def test_case_tools_knob_default_off_custom_and_file(tmp_path):
    values, sources = config.load_review_knobs(tmp_path, env={})
    assert values["risk_case_tools"] == config.DEFAULT_CASE_TOOLS == SIREN
    assert ("HWAXRISK_CASE_TOOLS", "default") in sources
    assert config.load_review_knobs(tmp_path, env={"HWAXRISK_CASE_TOOLS": "OFF"})[0]["risk_case_tools"] == ()
    got = config.load_review_knobs(tmp_path, env={"HWAXRISK_CASE_TOOLS": " a_x, b.y ,a_x "})[0]["risk_case_tools"]
    assert got == ("a_x", "b.y"), "차례 그대로 · 겹친 이름은 하나"
    (tmp_path / config.KNOBS_FILENAME).write_text("HWAXRISK_CASE_TOOLS=siren_search_cases  # 시험\n", encoding="utf-8")
    values, sources = config.load_review_knobs(tmp_path, env={})
    assert values["risk_case_tools"] == ("siren_search_cases",) and ("HWAXRISK_CASE_TOOLS", "knobs.env") in sources


@pytest.mark.parametrize("raw", ["bad name", "a,b,c,d,e,f,g", "x;y", ",,,"])
def test_case_tools_knob_rejects_bad_values(tmp_path, raw):
    with pytest.raises(RuntimeError, match="HWAXRISK_CASE_TOOLS"):
        config.load_review_knobs(tmp_path, env={"HWAXRISK_CASE_TOOLS": raw})


def test_runtime_lists_the_panel_knob():
    cfg = SimpleNamespace(risk_case_tools=SIREN, knob_sources=(("HWAXRISK_CASE_TOOLS", "default"),))
    assert config.panel_knobs(cfg) == {"HWAXRISK_CASE_TOOLS": {"value": list(SIREN), "source": "default"}}


# ---------------------------------------------------------------- 남은 자리 · 게이트웨이 지도
def test_case_tools_keeps_the_knob_order_only_what_the_gateway_has_and_the_room():
    cfg = SimpleNamespace(risk_case_tools=SIREN)
    assert planner.case_tools(3, settings=cfg, tool_map=GW_MAP) == list(SIREN)
    assert planner.case_tools(2, settings=cfg, tool_map=GW_MAP) == ["siren_list_groups", "siren_search_cases"]
    assert planner.case_tools(0, settings=cfg, tool_map=GW_MAP) == []
    partial = {"siren_get_case": "siren", "siren_search_cases": "siren"}
    assert planner.case_tools(6, settings=cfg, tool_map=partial) == ["siren_search_cases", "siren_get_case"]
    assert planner.case_tools(6, settings=cfg, tool_map={}) == [], "SIREN 이 없는 박스(dev)는 그대로"
    assert planner.case_tools(6, settings=SimpleNamespace(risk_case_tools=()), tool_map=GW_MAP) == [], "off"


def test_planning_and_the_cost_estimate_never_ask_the_gateway(risk_store, monkeypatch):
    """계획 · 과제 만들기의 비용 어림은 게이트웨이를 묻지 않는다(외부 호출 0 시험의 전제) — SIREN 은 러너가 패널을 띄울 때 붙인다."""
    def _boom(**_k):
        raise AssertionError("계획이 게이트웨이를 물었다")
    monkeypatch.setattr(adapters_registry, "gateway_tool_map", _boom)
    diff2 = make_target(risk_store, "d2", kind="diff", report_ids=[11, 12])
    assert planner.planned_tools(risk_store, diff2) == ["list_interfaces", "interface_graph", "report_part_risk", "compare_reports"]


def _launch(risk_store, tmp_path, monkeypatch, gw_map):
    """보통 패널 하나를 러너로 띄워 엔진이 받은 delib_opts 와 패널 품질을 돌려준다(tests/test_runner_panel 의 대역)."""
    import dataclasses
    import json as _json

    from tests.test_runner_panel import OWNER, FakePanelEngine, fake_narrative, fake_registry, give_credential, seeded

    monkeypatch.setattr(adapters_registry, "gateway_tool_map", lambda **_k: dict(gw_map))
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    job = runner.claim_next_job(risk_store, cfg)
    engine, recorder = FakePanelEngine(), {}
    out = runner.run_panel(risk_store, cfg, engine, job, narrative_mod=fake_narrative(recorder), registry_mod=fake_registry(recorder))
    row = risk_store.query_one("SELECT budget_json, quality_json FROM rr_panels WHERE id = ?", (out["panel_id"],))
    return engine.calls[0], _json.loads(row["budget_json"]), _json.loads(row["quality_json"])


def test_a_coverage_panel_gets_the_case_tools_in_the_remaining_slots_when_it_is_launched(risk_store, tmp_path, monkeypatch):
    sent, budget, quality = _launch(risk_store, tmp_path, monkeypatch, GW_MAP)
    planned = budget["tools_planned"]
    room = planner.MAX_TOOLS - len(planned)
    assert room > 0, "시험 전제 — 남은 자리가 있다"
    assert sent["tools"] == [*planned, *SIREN[:room]], "계획한 도구 뒤에 손잡이 차례대로 · 상한 6 안"
    assert len(sent["tools"]) <= planner.MAX_TOOLS
    assert quality["case_tools"] == list(SIREN[:room]) and "case_tools" not in quality["flags"], "기록이지 표지가 아니다"


def test_without_siren_on_the_gateway_the_panel_is_unchanged(risk_store, tmp_path, monkeypatch):
    sent, budget, quality = _launch(risk_store, tmp_path, monkeypatch, {"list_interfaces": "heax-step_forge"})
    assert sent["tools"] == budget["tools_planned"] and "case_tools" not in quality


# ---------------------------------------------------------------- 미연결 · 한도 초과 표지
def _frames(*warnings):
    return [*(("warning", w) for w in warnings), ("delib", {"kind": "decision", "text": "결정"}), ("done", {})]


def test_engine_client_keeps_names_of_conn_warnings_and_runner_turns_them_into_flags():
    got = engine_client.collect_stream(_frames(
        {"code": "conn_unregistered", "message": "외부 연결 siren …", "backends": ["siren"], "labels": ["SIREN"],
         "tools": ["siren_list_groups", "siren_search_cases"]},
        {"code": "conn_rate_limited", "message": "…", "backends": ["siren"], "tools": ["siren_get_case"]},
        {"code": "other_warning", "message": "x", "backends": ["nope"]}))
    warns = [e for e in got["events"] if e["kind"] == "warning"]
    assert warns[0]["labels"] == ["SIREN"] and warns[0]["tools"] == ["siren_list_groups", "siren_search_cases"]
    assert "backends" not in warns[2], "외부 연결 경고가 아니면 칸을 옮기지 않는다"
    notes = runner.conn_notes(got["events"])
    assert notes == {"conn_unregistered": ["SIREN"], "conn_rate_limited": ["siren"]}, "이름이 없으면 백엔드 키"
    assert runner.conn_notes([{"kind": "warning", "code": "conn_unregistered"}]) == {"conn_unregistered": ["?"]}
    assert runner.conn_notes([]) == {}


def test_issue_report_line_says_which_case_db_was_not_connected():
    assert synth._panel_conn('{"conn_unregistered": ["SIREN"], "flags": ["conn_unregistered"]}') == " · 외부 사례: SIREN 미연결"
    assert synth._panel_conn('{"conn_rate_limited": ["SIREN"]}') == " · 외부 사례: SIREN 한도 초과"
    assert synth._panel_conn("{}") == "" and synth._panel_conn(None) == ""


# ---------------------------------------------------------------- 띄울 때의 판정 — Claude 잡 · 호출 상한 · 못 읽은 지도(반대 검토 11-06)
def _panel(est_high=95, seats=6, rounds=3):
    return {"budget": {"est_high": est_high}, "seats": [{}] * seats, "rounds": rounds}


def test_case_tools_plan_skips_claude_jobs_and_says_why():
    cfg = SimpleNamespace(risk_case_tools=SIREN, risk_panel_llm_cap=120)
    assert planner.case_tools_plan(_panel(), ["a", "b"], settings=cfg, claude=True, tool_map=GW_MAP) == ([], planner.CASE_SKIP_CLAUDE)
    assert planner.case_tools_plan(_panel(), ["a", "b"], settings=cfg, tool_map=GW_MAP) == (list(SIREN), "")


def test_case_tools_plan_keeps_the_panel_call_cap():
    """예산 문이 이미 상한 곁으로 줄인 패널에는 싣지 않는다 — 도구 하나가 인자 짓기 LLM 을 두 번까지 부른다(2T)."""
    cfg = SimpleNamespace(risk_case_tools=SIREN, risk_panel_llm_cap=99)
    assert planner.case_tools_plan(_panel(est_high=95), ["a"] * 4, settings=cfg, tool_map=GW_MAP) == (list(SIREN[:2]), "")
    assert planner.case_tools_plan(_panel(est_high=97), ["a"] * 4, settings=cfg, tool_map=GW_MAP) == (list(SIREN[:1]), "")
    assert planner.case_tools_plan(_panel(est_high=98), ["a"] * 4, settings=cfg, tool_map=GW_MAP) == ([], planner.CASE_SKIP_CAP)
    # 쟁점 패널(예산식이 없다)은 좌석 · 라운드로 어림한다
    issue = {"budget": {"rounds_planned": 3, "tools_planned": []}, "seats": [{}] * 4, "rounds": 3}
    cfg = SimpleNamespace(risk_case_tools=SIREN, risk_panel_llm_cap=120)
    assert planner.case_tools_plan(issue, [], settings=cfg, tool_map=GW_MAP) == (list(SIREN), "")


def test_case_tools_plan_tells_an_unread_gateway_from_an_absent_siren():
    cfg = SimpleNamespace(risk_case_tools=SIREN, risk_panel_llm_cap=120)
    assert planner.case_tools_plan(_panel(), [], settings=cfg, tool_map={}) == ([], planner.CASE_SKIP_UNREAD)
    assert planner.case_tools_plan(_panel(), [], settings=cfg, tool_map={"list_interfaces": "x"}) == ([], ""), "없는 박스는 적지 않는다"
    assert planner.case_tools_plan(_panel(), [], settings=SimpleNamespace(risk_case_tools=(), risk_panel_llm_cap=120),
                                   tool_map=GW_MAP) == ([], ""), "손잡이 off"

