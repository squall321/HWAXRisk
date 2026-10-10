# 스트림 수집과 좌석 귀속 — 엔진이 주는 발언 원문(say_full)·지식카드 집계를 받고, 카드·실패 조회·브리프 메아리를 도구 성공으로 세지 않는다(WP1 S13 · R-43~R-45 · R-63 · P-10)
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app import engine_client, narrative, runner
from tests.conftest import REPO_ROOT

SEATS = ["mech-a", "rel-b", "therm-c"]


def _frames_fixture() -> Path:
    """엔진이 실제 스트림에서 뜬 프레임 예제(형제 리포). 형제가 없을 때만 건너뛴다 — 있는데 파일이 없으면 실패다."""
    engine = Path(os.environ.get("HWAX_AGENT_SERVER_REPO") or REPO_ROOT.parent / "HWAXAgentServer")
    if not engine.is_dir():
        pytest.skip(f"엔진 리포가 곁에 없다(HWAX_AGENT_SERVER_REPO 또는 ../HWAXAgentServer) — {engine}")
    path = engine / "tests" / "fixtures" / "risk_contract" / "panel_frames.jsonl"
    if not path.is_file():
        pytest.fail(f"엔진 리포는 곁에 있는데 프레임 예제가 없다 — {path}")
    return path


def _frames(path: Path) -> list[tuple[str, dict]]:
    return [(row["event"], row["data"]) for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())]


def test_engine_frames_are_collected_and_attributed_by_the_new_rules():
    """엔진이 낸 프레임 그대로 — 발언은 줄이지 않은 원문(say_full)이고, 좌석마다 지식카드 적중 수가 서며, 지식카드·실패한
    조회는 도구 성공이 아니고, 브리프 메아리(`챗 정리 · …`)는 귀속률 분모에 들지 않는다."""
    frames = _frames(_frames_fixture())
    full = {d["persona"]: d["say_full"] for name, d in frames if d.get("kind") == "turn" and d.get("say_full")}
    result = engine_client.collect_stream(iter(frames))
    assert full and {t["persona"]: t["say"] for t in result["turns"] if t["persona"] in full} == full
    attribution = runner.attribute_events(result["events"], SEATS)
    seats = attribution["seats"]
    assert (seats["mech-a"]["tool_calls_ok"], seats["mech-a"]["used_tool"], seats["mech-a"]["knowledge_hits_n"]) == \
        (1, True, 2)
    assert seats["mech-a"]["knowledge_seen"] is True
    assert (seats["rel-b"]["tool_calls_ok"], seats["rel-b"]["tool_calls_failed"], seats["rel-b"]["used_tool"]) == \
        (0, 1, False)
    assert seats["rel-b"]["knowledge_hits_n"] == 0
    assert (seats["therm-c"]["knowledge_hits_n"], seats["therm-c"]["knowledge_degraded"]) == (0, True)
    assert seats["therm-c"]["used_tool"] is False
    # 조회 1 + 좌석 근거 3(도구 결과 · 실패 · 지식카드) — 메아리는 빠진다.
    assert (attribution["attributable"], attribution["attributed"]) == (4, 4)
    assert attribution["knowledge_queries"] == {"mech-a": "question", "rel-b": "question", "therm-c": "question"}


def test_turn_prefers_say_full_and_old_frames_keep_say():
    """줄인 발언(say)과 원문(say_full)이 갈리면 원문을 받는다 — 줄이지 않은 발언·옛 엔진은 say 그대로다(R-63)."""
    tail = " 마지막으로 c:aaaaaaaaaaaa 를 본다."
    long_say = "관점 " * 1300 + tail
    frames = [("delib", {"kind": "turn", "round": 1, "persona": "mech-a", "say": long_say[:560],
                         "say_full": long_say, "say_full_chars": len(long_say)}),
              ("delib", {"kind": "turn", "round": 1, "persona": "rel-b", "say": "짧은 발언"}),
              ("done", {})]
    turns = engine_client.collect_stream(iter(frames))["turns"]
    assert [t["say"] for t in turns] == [long_say, "짧은 발언"]


def test_attribution_rules_for_cards_failures_echo_and_keyless_evidence():
    """`<키> · 지식카드` 는 받았다는 표시이지 도구 성공이 아니다 · `included=false` 는 실패 · `included` 가 없는 근거
    (REST·MCP 로 들어온 옛 events)는 종전대로 성공 · `챗 정리 · …` 는 엔진의 브리프 메아리라 귀속 대상이 아니다(R-44·R-45·P-10)."""
    events = [
        {"kind": "evidence", "source": "mech-a · 지식카드", "included": True},
        {"kind": "evidence", "source": "mech-a · 자유 조회 실패", "included": False},
        {"kind": "evidence", "source": "rel-b · list_interfaces"},
        {"kind": "evidence", "source": "챗 정리 · rr_scope", "included": True},
        {"kind": "status", "step": "지식카드 1/2 — mech-a 확보",
         "knowledge": {"persona": "mech-a", "hits": 3, "degraded": False, "query": "caller"}},
    ]
    attribution = runner.attribute_events(events, ["mech-a", "rel-b"])
    seats = attribution["seats"]
    assert (seats["mech-a"]["tool_calls_ok"], seats["mech-a"]["tool_calls_failed"], seats["mech-a"]["used_tool"]) == \
        (0, 1, False)
    assert (seats["mech-a"]["knowledge_seen"], seats["mech-a"]["knowledge_hits_n"]) == (True, 3)
    assert (seats["rel-b"]["tool_calls_ok"], seats["rel-b"]["used_tool"]) == (1, True)
    assert seats["rel-b"]["knowledge_hits_n"] is None                     # 보고가 없던 좌석은 미측정
    assert (attribution["attributable"], attribution["attributed"]) == (3, 3)


def test_collect_stream_keeps_engine_notices_whole():
    """엔진이 '못 실었다' 고 알린 사유와 고칠 설정(knob)을 자르지 않고 남긴다 — 사유 뒤쪽(어느 설정을 올리라)이 200자에서
    사라졌다(C3). events 는 400건에서 말없이 멈추지 않는다(C2 — 뒤 좌석의 도구 사용이 0 으로 세졌다)."""
    note = "근거 120건 중 뒤쪽 100건은 예산을 넘겨 좌석에 주지 않았다 — " + "가" * 400
    frames = [("delib", {"kind": "evidence", "source": "사전 근거 예산 초과", "included": False, "text": note,
                         "knob": "DELIB_EVID_BUDGET — 1백만 토큰 창에서는 천장"})]
    frames += [("status", {"step": f"mech-a 조회: tool_{i}", "tool": f"tool_{i}"}) for i in range(450)]
    frames += [("delib", {"kind": "evidence", "source": "mech-a · tool_449", "included": True}), ("done", {})]
    result = engine_client.collect_stream(iter(frames))
    assert runner.withheld_by_engine(result["events"]) == \
        [f"사전 근거 예산 초과 — {note} (설정 DELIB_EVID_BUDGET — 1백만 토큰 창에서는 천장)"]
    attribution = runner.attribute_events(result["events"], ["mech-a"])
    assert attribution["seats"]["mech-a"]["tool_calls_n"] == 450 and attribution["seats"]["mech-a"]["used_tool"]


def test_persist_counts_refs_beyond_the_bubble_and_keeps_the_whole_say(risk_store):
    """발언 원문의 뒤쪽 인용까지 세고(cited_refs), 좌석 기억 발췌(excerpt_for_rag)는 전 라운드 원문이며, 화면용 발췌
    (say_excerpt)는 2,000자에서 줄이되 원문 길이를 밝힌다(R-63 · 의견 발췌 1,500자)."""
    from tests.test_persist_panel import PANEL, _seed  # noqa: PLC0415 — 같은 시드를 쓴다

    _seed(risk_store)
    seat = json.loads(risk_store.query_one("SELECT seats_json FROM rr_panels WHERE id = ?", (PANEL,))["seats_json"])[0]
    key = seat["key"]
    say1 = "1라운드 관점 " * 400 + "끝에 c:aaaaaaaaaaaa"
    say2 = "최종 입장은 조건부다. " * 200
    out = narrative.persist_panel_result(risk_store, PANEL, decision_text="", spec=None,
                                         turns=[{"round": 1, "persona": key, "say": say1},
                                                {"round": 2, "persona": key, "say": say2}],
                                         attribution={"seats": {key: {"knowledge_hits_n": 4, "turns_n": 2}}})
    row = risk_store.query_one("SELECT opinion_json, cited_refs_json, excerpt_for_rag, knowledge_hits_n"
                               " FROM rr_seat_opinions WHERE panel_id = ? AND agent_key = ?", (PANEL, key))
    opinion = json.loads(row["opinion_json"])
    assert "c:aaaaaaaaaaaa" in json.loads(row["cited_refs_json"])
    assert row["excerpt_for_rag"] == f"{say1}\n{say2}"
    turn = opinion["turns"][0]
    assert turn["say"] == say1 and len(turn["say_excerpt"]) <= narrative.SAY_EXCERPT_MAX
    assert turn["say_excerpt"].endswith("자)") and f" …(발언 {len(say1)}자 중 " in turn["say_excerpt"]
    assert say1.startswith(turn["say_excerpt"].split(" …(발언 ")[0])
    assert opinion["knowledge_hits_n"] == row["knowledge_hits_n"] == 4
    assert next(s for s in out["seats"] if s["agent_key"] == key)["cited_refs_n"] >= 1
