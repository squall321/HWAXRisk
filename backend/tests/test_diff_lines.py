# risk_get_diff 의 part='lines'·거름·이어 받기 — 좌석이 브리프 E2 에서 빠진 변경을 같은 줄 모양으로 받는다(WP1 S14 · R-30)
from __future__ import annotations

import asyncio
import json

import app.mcp_server as srv
from app import brief, routes
from tests import factories


def _lines(payload: dict) -> list[str]:
    text = payload.get("lines") or ""
    return text.split("\n") if text else []


def _events(store, diff_id: str) -> list:
    return store.query(
        "SELECT cid, layer, code, change_kind, subject_key, magnitude, unit, rel, confidence, design_relevant,"
        " unconfirmed, excluded_reason, text FROM rr_diff_events WHERE diff_id = ?", (diff_id,))


def test_old_diff_parts_answer_as_before(risk_store):
    """특성화 — 새 인자를 주지 않은 종전 호출(diff·summary·events, MCP 상한 500)은 같은 응답이다."""
    synth = factories.make_diff_target(risk_store, 40)
    with factories.routes_store(risk_store):
        events = routes.diff_part(synth.diff_id, "events", owner_sub=factories.OWNER)
        capped = routes.diff_part(synth.diff_id, "events", owner_sub=factories.OWNER, limit=5)
        summary = routes.diff_part(synth.diff_id, "summary", owner_sub=factories.OWNER)
        whole = routes.diff_part(synth.diff_id, "diff", owner_sub=factories.OWNER)
    assert set(events) == {"diff_id", "events"} and len(events["events"]) == len(_events(risk_store, synth.diff_id))
    assert [e["cid"] for e in events["events"]] == [r["cid"] for r in risk_store.query(
        "SELECT cid FROM rr_diff_events WHERE diff_id = ? ORDER BY code, cid", (synth.diff_id,))]
    assert capped["events"] == events["events"][:5] and capped["truncated"] is True
    assert summary["diff_id"] == synth.diff_id and "summary_text" in summary
    assert whole["diff_version"] and "semantic" in whole


def test_lines_are_the_brief_e2_lines_in_the_same_order(risk_store):
    """part='lines' 는 E2 와 같은 줄을 `event_order` 순으로 전부 준다 — 브리프에 실린 줄은 그 앞부분과 글자까지 같다."""
    synth = factories.make_diff_target(risk_store, 40)
    rows = _events(risk_store, synth.diff_id)
    names = brief.name_index(risk_store, (synth.base_snapshot_id, synth.target_snapshot_id))
    expected = [brief.e2_line(r, names) for r in brief.event_order(rows)]
    with factories.routes_store(risk_store):
        out = routes.diff_part(synth.diff_id, "lines", owner_sub=factories.OWNER)
    assert out["total"] == out["matched"] == out["returned"] == len(rows) > 20
    assert out["truncated"] is False and out["offset"] == 0
    assert _lines(out) == expected
    assert out["by_kind"] == brief.event_counts(rows)["by_kind"]
    # 브리프 E2 의 실린 줄은 이 목록의 앞부분이다(좌석이 옮겨 적은 줄로 이어 받는다).
    built = brief.build_brief(risk_store, synth.target_key, shield_lint=True)
    e2 = next(i for i in built["evidence"] if i["key"] == "E2")["result"].split("\n")
    shown = [line for line in e2[1:] if line.startswith("[c:")]
    assert shown and shown == expected[:len(shown)]


def test_lines_filter_by_kind_and_text_and_page_from_zero(risk_store):
    """change_kind(쉼표로 여럿)·q(이름·코드, 대소문자 무시)로 거르고, offset 은 거른 목록 안의 자리다(P-06 의 2번)."""
    synth = factories.make_diff_target(risk_store, 40)
    with factories.routes_store(risk_store):
        everything = _lines(routes.diff_part(synth.diff_id, "lines", owner_sub=factories.OWNER))
        kinds = routes.diff_part(synth.diff_id, "lines", owner_sub=factories.OWNER, change_kind="dimension,material")
        assert kinds["matched"] == len(_lines(kinds)) and 0 < kinds["matched"] < len(everything)
        assert set(_lines(kinds)) <= set(everything)
        assert [line for line in everything if line in set(_lines(kinds))] == _lines(kinds)   # 순서 보존

        word = everything[0].split("«", 1)[1].split()[0].strip("»")
        found = routes.diff_part(synth.diff_id, "lines", owner_sub=factories.OWNER, q=word.lower())
        assert found["matched"] >= 1 and all(word.casefold() in line.casefold() for line in _lines(found))

        first = routes.diff_part(synth.diff_id, "lines", owner_sub=factories.OWNER, change_kind="dimension,material",
                                 limit=3)
        rest = routes.diff_part(synth.diff_id, "lines", owner_sub=factories.OWNER, change_kind="dimension,material",
                                offset=3)
        assert first["returned"] == 3 and first["truncated"] is True and first["next_offset"] == 3
        assert _lines(first) + _lines(rest) == _lines(kinds)
        assert rest["truncated"] is False and "next_offset" not in rest


def test_lines_on_a_blocked_or_empty_diff_say_why(risk_store):
    """이벤트가 0건이면 빈 목록과 함께 E2 와 같은 문구(차단 · 변화 없음)를 준다 — 빈 응답을 '변경 없음' 으로 읽지 않게."""
    synth = factories.make_diff_target(risk_store, 3)
    same = factories.make_diff(risk_store, synth.target_snapshot_id, synth.target_snapshot_id)
    with factories.routes_store(risk_store):
        out = routes.diff_part(same["diff_id"], "lines", owner_sub=factories.OWNER)
    assert out["total"] == 0 and out["lines"] == "" and out["note"].startswith("[의미 이벤트")


def test_lines_respect_ownership(risk_store):
    synth = factories.make_diff_target(risk_store, 3)
    with factories.routes_store(risk_store):
        try:
            routes.diff_part(synth.diff_id, "lines", owner_sub="someone@else")
        except routes.AppError as exc:
            assert exc.code == "E404"
        else:
            raise AssertionError("남의 diff 줄을 돌려줬다")


def test_mcp_risk_get_diff_takes_the_filters(risk_store, monkeypatch):
    """도구 수는 그대로이고 risk_get_diff 가 거름·이어 받기 인자를 받는다. 종전 인자 둘만 주면 종전과 같다."""
    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    props = tools["risk_get_diff"].inputSchema["properties"]
    assert set(props) == {"diff_id", "part", "change_kind", "q", "offset", "limit"}
    assert set(tools["risk_get_diff"].inputSchema["required"]) == {"diff_id", "part"}
    assert "lines" in tools["risk_get_diff"].description

    synth = factories.make_diff_target(risk_store, 40)
    risk_store.execute("UPDATE rr_projects SET mcp_visibility = 'org' WHERE id = ?", (synth.project_id,))
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    out = srv.risk_get_diff(synth.diff_id, "lines", change_kind="dimension", offset=1)
    assert "error" not in out, out
    with factories.routes_store(risk_store):
        direct = routes.diff_part(synth.diff_id, "lines", owner_sub=factories.OWNER, change_kind="dimension")
    assert _lines(out) == _lines(direct)[1:]
    # 종전 호출 — events 는 상한 500 이고 넘치지 않으면 truncated=False 다.
    events = srv.risk_get_diff(synth.diff_id, "events")
    assert events["truncated"] is False and len(events["events"]) == len(_events(risk_store, synth.diff_id))
    json.dumps(out, ensure_ascii=False)


def test_mcp_events_page_past_the_cap(risk_store, monkeypatch):
    """events 의 상한(500)은 한 번에 주는 양이다 — offset 으로 나머지를 받는다(종전에는 501번째부터 받을 길이 없었다)."""
    synth = factories.make_diff_target(risk_store, 40)
    risk_store.execute("UPDATE rr_projects SET mcp_visibility = 'org' WHERE id = ?", (synth.project_id,))
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(srv, "EVENT_LIMIT", 7)
    first = srv.risk_get_diff(synth.diff_id, "events")
    second = srv.risk_get_diff(synth.diff_id, "events", offset=7)
    total = len(_events(risk_store, synth.diff_id))
    assert first["truncated"] is True and len(first["events"]) == 7 and first["total"] == total
    assert first["next_offset"] == 7 and second["events"][0]["cid"] != first["events"][0]["cid"]
    assert [e["cid"] for e in first["events"] + second["events"]][:14] == \
        [e["cid"] for e in srv.risk_get_diff(synth.diff_id, "events", limit=14)["events"]]


def test_mcp_snapshot_nodes_and_registry_page_past_their_caps(risk_store, monkeypatch):
    """nodes·edges(500)·등록부(200)·주장(100)의 상한은 한 번에 주는 양이다 — next_offset 으로 나머지를 받는다(M1)."""
    synth = factories.make_diff_target(risk_store, 40)
    risk_store.execute("UPDATE rr_projects SET mcp_visibility = 'org'")
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(srv, "NODE_LIMIT", 10)
    first = srv.risk_get_snapshot(synth.target_snapshot_id, "nodes")
    second = srv.risk_get_snapshot(synth.target_snapshot_id, "nodes", offset=first["next_offset"])
    every = [n["nid"] for n in routes.snapshot_part(synth.target_snapshot_id, "nodes", owner_sub=factories.OWNER)["nodes"]]
    assert first["truncated"] is True and first["next_offset"] == 10
    assert [n["nid"] for n in first["nodes"] + second["nodes"]] == every[:20]
    with factories.routes_store(risk_store):
        reg = routes.registry_payload(synth.target_key, owner_sub=factories.OWNER, limit=0)
        refs = routes.claims_for_ref(synth.diff["semantic"]["events"][0]["cid"], owner_sub=factories.OWNER, limit=0)
    assert reg["total"] == len(routes.registry_payload(synth.target_key, owner_sub=factories.OWNER)["rows"])
    assert "next_offset" not in refs or refs["next_offset"] == 0
