# external_sync 상태기계(plan §5.5.3)와 외부 클라이언트 배선 — RA·AIDataHub 호출 형식·unavailable 강등(전부 MockTransport, 실 네트워크 0)
from __future__ import annotations

import json

import httpx
import pytest

from app import common
from app.adh_client import (EXTERNAL_SOURCE, IMPORT_PATH, MEMORY_AGENT, AdhClient, make_external_id)
from app.ra_client import (RA_READ_TOOLS, RA_WRITE_TOOLS, SYNC_BASE_DELAY,
                           SYNC_CHANNELS, SYNC_MAX_ATTEMPTS, SYNC_MAX_DELAY, WRITE_SECRET_KEY, McpHttpClient, RaClient,
                           complete_sync_ops, empty_sync, load_external_sync, mark_unavailable,
                           note_sync_failure, parse_external_sync, queue_sync_ops, resync, save_external_sync, set_aside_sync_ops,
                           sender_status, set_sync_state, sync_badge, sync_summary)

OWNER = "me@example.com"
TARGET = "diff:d1"
NOW = 1_700_000_000


@pytest.fixture
def frozen_clock():
    """now_epoch 를 고정해 next_at 백오프를 정확히 비교한다."""
    previous = common.set_clock(lambda: NOW)
    yield NOW
    common.set_clock(previous)


@pytest.fixture
def target_store(risk_store):
    """external_sync 를 붙일 타깃 1행이 있는 빈 저장소."""
    risk_store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("p_now", OWNER, "DV2", 100, 100))
    risk_store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, level,"
        " external_sync_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (TARGET, OWNER, "diff", "d1", "p_now", "h1", "C0",
         json.dumps(empty_sync(), ensure_ascii=False), 200, 200))
    return risk_store


def _sync_json(store) -> dict:
    row = store.query_one("SELECT external_sync_json FROM rr_targets WHERE target_key = ?", (TARGET,))
    return json.loads(row["external_sync_json"])


# ---------------------------------------------------------------- 상태기계(§5.5.3)
def test_empty_sync_has_both_channels_pending():
    sync = empty_sync()
    assert set(sync) == set(SYNC_CHANNELS) == {"ra", "adh"}
    for entry in sync.values():
        assert entry == {"state": "pending", "attempts": 0, "next_at": 0, "last_error": None,
                         "done_at": None, "pending_ops": []}


def test_load_external_sync_normalizes_partial_and_broken_json(target_store):
    target_store.execute("UPDATE rr_targets SET external_sync_json = ? WHERE target_key = ?",
                         ('{"ra": {"state": "done", "attempts": 2}}', TARGET))
    sync = load_external_sync(target_store, TARGET)
    assert sync["ra"]["state"] == "done" and sync["ra"]["attempts"] == 2
    assert sync["ra"]["pending_ops"] == []                 # 빠진 키는 기본값으로 채운다
    assert sync["adh"] == empty_sync()["adh"]

    target_store.execute("UPDATE rr_targets SET external_sync_json = ? WHERE target_key = ?",
                         ("깨진 json", TARGET))
    assert load_external_sync(target_store, TARGET) == empty_sync()


def test_save_external_sync_is_byte_stable(target_store):
    save_external_sync(target_store, TARGET, empty_sync())
    first = target_store.query_one(
        "SELECT external_sync_json FROM rr_targets WHERE target_key = ?", (TARGET,))["external_sync_json"]
    save_external_sync(target_store, TARGET, empty_sync())
    second = target_store.query_one(
        "SELECT external_sync_json FROM rr_targets WHERE target_key = ?", (TARGET,))["external_sync_json"]
    assert first == second


def test_queue_then_complete_moves_pending_to_done(target_store, frozen_clock):
    op = {"op": "create_object", "type_slug": "assessment", "code": "op1", "payload_ref": "opinion:op1"}
    queue_sync_ops(target_store, TARGET, "ra", [op, dict(op)])          # 같은 op 는 한 번만 쌓인다
    sync = _sync_json(target_store)
    assert sync["ra"]["state"] == "pending" and sync["ra"]["pending_ops"] == [op]

    complete_sync_ops(target_store, TARGET, "ra", [op])
    sync = _sync_json(target_store)
    assert sync["ra"]["state"] == "done"
    assert sync["ra"]["pending_ops"] == [] and sync["ra"]["done_at"] == NOW
    assert sync["adh"]["state"] == "pending"                            # 채널은 독립이다


def test_new_ops_after_done_return_to_pending(target_store, frozen_clock):
    op1 = {"op": "import", "external_id": "opinion:a"}
    op2 = {"op": "import", "external_id": "opinion:b"}
    queue_sync_ops(target_store, TARGET, "adh", [op1])
    complete_sync_ops(target_store, TARGET, "adh", [op1])
    assert _sync_json(target_store)["adh"]["state"] == "done"

    queue_sync_ops(target_store, TARGET, "adh", [op2])
    entry = _sync_json(target_store)["adh"]
    assert entry["state"] == "pending" and entry["done_at"] is None and entry["pending_ops"] == [op2]


def test_note_sync_failure_backs_off_exponentially(target_store, frozen_clock):
    for attempts in range(1, SYNC_MAX_ATTEMPTS):
        note_sync_failure(target_store, TARGET, "ra", f"http_500#{attempts}")
        entry = _sync_json(target_store)["ra"]
        assert entry["attempts"] == attempts
        assert entry["state"] == "pending"
        assert entry["next_at"] == NOW + min(SYNC_BASE_DELAY * (2 ** attempts), SYNC_MAX_DELAY)
        assert entry["last_error"] == f"http_500#{attempts}"
    assert _sync_json(target_store)["ra"]["next_at"] - NOW == SYNC_MAX_DELAY     # 6시간 상한


def test_eighth_failure_degrades_to_unavailable(target_store, frozen_clock):
    for _ in range(SYNC_MAX_ATTEMPTS):
        note_sync_failure(target_store, TARGET, "adh", "http_401")
    entry = _sync_json(target_store)["adh"]
    assert entry["attempts"] == SYNC_MAX_ATTEMPTS == 8
    assert entry["state"] == "unavailable" and entry["next_at"] == 0


def test_queue_does_not_revive_an_unavailable_channel(target_store, frozen_clock):
    mark_unavailable(target_store, TARGET, "ra", "no_credential")
    queue_sync_ops(target_store, TARGET, "ra", [{"op": "link_objects"}])
    entry = _sync_json(target_store)["ra"]
    assert entry["state"] == "unavailable"                  # 재동기 전에는 pending 으로 돌아가지 않는다
    assert entry["pending_ops"] == [{"op": "link_objects"}]  # op 는 잃지 않는다


def test_queue_keeps_a_withheld_channel_withheld(target_store, frozen_clock):
    """보류는 조직 공개로 풀 때까지다 — 새 op 가 쌓여도 pending 으로 돌아가지 않는다(§5.5.3 '새 패널 종료' 행)."""
    set_sync_state(target_store, TARGET, "ra", "withheld")
    queue_sync_ops(target_store, TARGET, "ra", [{"op": "link", "n": 1}])
    entry = _sync_json(target_store)["ra"]
    assert entry["state"] == "withheld" and entry["pending_ops"] == [{"op": "link", "n": 1}]
    assert sync_badge(load_external_sync(target_store, TARGET)).startswith("RA 반영: withheld(1)")


def test_resync_restores_both_channels(target_store, frozen_clock):
    mark_unavailable(target_store, TARGET, "ra", "no_credential")
    note_sync_failure(target_store, TARGET, "adh", "http_500")
    resync(target_store, TARGET)
    for channel in SYNC_CHANNELS:
        entry = _sync_json(target_store)[channel]
        assert entry["state"] == "pending"
        assert entry["attempts"] == 0 and entry["next_at"] == 0 and entry["last_error"] is None


def test_set_aside_ops_leave_the_queue_and_resync_puts_them_back_in_front(target_store, frozen_clock):
    """따로 둔 op(그 op 에만 걸린 영구 거절)는 큐에서 빠져 dead_ops 에 까닭과 함께 있다 — 큐가 비면 done 이다. 재동기가 큐 앞으로 되돌린다
    (따로 둔 op 는 큐에 남은 어느 op 보다 앞선 것이라 원래 순서다). 같은 꼴의 op 는 한 번만 되돌린다."""
    a, b, c = {"op": "merge_object", "n": 1}, {"op": "link", "n": 2}, {"op": "link", "n": 3}
    queue_sync_ops(target_store, TARGET, "ra", [a, b])
    set_aside_sync_ops(target_store, TARGET, "ra", [{"op": a, "error": "value_collision: 겹침"}])
    entry = _sync_json(target_store)["ra"]
    assert entry["state"] == "pending" and entry["pending_ops"] == [b]
    assert entry["dead_ops"] == [{"op": a, "error": "value_collision: 겹침", "at": NOW}]
    set_aside_sync_ops(target_store, TARGET, "ra", [{"op": b, "error": "rejected: 축"}, {"op": a, "error": "value_collision: 또"}])
    entry = _sync_json(target_store)["ra"]
    assert entry["state"] == "done" and entry["pending_ops"] == []
    assert [(d["op"], d["error"]) for d in entry["dead_ops"]] == [(a, "value_collision: 또"), (b, "rejected: 축")]

    queue_sync_ops(target_store, TARGET, "ra", [c, a])                  # 같은 꼴의 op 가 다시 쌓였다
    set_aside_sync_ops(target_store, TARGET, "ra", [{"op": c, "error": "rejected: 꼴"}])
    assert _sync_json(target_store)["ra"]["pending_ops"] == [a]        # 이번에 따로 둔 것만 뺀다 — 예전 것과 같은 꼴이어도 새로 쌓인 op 는 남는다
    resync(target_store, TARGET)
    entry = _sync_json(target_store)["ra"]
    assert entry["state"] == "pending" and entry["pending_ops"] == [a, b, c] and entry["dead_ops"] == []


def test_the_external_sync_summary_says_why_nothing_is_sent(target_store, frozen_clock):
    """RA 보내는 쪽은 박스 쓰기 PAT 가 있어야 켜진다(RK-01) — 없으면 요약은 그 까닭(credential_missing:<키>)과 대기 건수, '보낸 것
    없음' 을 말한다(조용한 pending 이 아니다). AIDataHub 반입은 아직 보내는 쪽이 없어 sender_unwired 그대로다(R3 · U-4)."""
    queue_sync_ops(target_store, TARGET, "ra", [{"op": "create_object", "n": 1}, {"op": "create_object", "n": 2}])
    off = sender_status(secrets={"HWAXRISK_PORTAL_PAT": "read-only"})
    summary = sync_summary(load_external_sync(target_store, TARGET), status=off)
    assert summary == {
        "ra": {"state": "pending", "pending_ops": 2, "dead_ops": 0, "reason": f"credential_missing:{WRITE_SECRET_KEY}",
               "message": f"RA 반영 안 됨 — 박스에 RA 쓰기 자격({WRITE_SECRET_KEY})이 없어 보내는 쪽이 꺼져 있다. 대기 2건,"
                          " 보낸 것 없음.",
               # 거두기 셈(RK-01 거두기 — 사용자 결정 10-31 (가))은 RA 채널에 늘 실린다(객체 수 — RA 에 이미 없던 것은 따로 센다).
               "retracted": 0, "retract_absent": 0, "retract_pending": 0, "retract_failed": 0, "retract_reasons": {}},
        "adh": {"state": "pending", "pending_ops": 0, "dead_ops": 0, "reason": "sender_unwired",
                "message": "AIDataHub 반영 안 됨 — 보내는 쪽이 아직 배선되지 않았다(M4). 대기 0건, 보낸 것 없음."}}
    assert sync_summary(parse_external_sync("깨진 글"), status=off) == sync_summary(empty_sync(), status=off)
    # 설정 없이 부르면 지금 박스(시험 데이터 디렉터리 — secrets.env 없음)로 잰다.
    assert sync_summary(load_external_sync(target_store, TARGET)) == summary


def test_the_ra_summary_reason_follows_the_channel_state(target_store, frozen_clock):
    """켜진 박스의 RA 요약 — 대기 · 재시도 대기 · 멈춤 · 보류 · 끝 · 없음이 reason 낱말과 글로 갈린다(last_error 의 앞 낱말)."""
    on = sender_status(secrets={WRITE_SECRET_KEY: "rw"})

    def ra():
        return sync_summary(load_external_sync(target_store, TARGET), status=on)["ra"]

    assert ra()["reason"] == "idle"
    queue_sync_ops(target_store, TARGET, "ra", [{"op": "link", "n": 1}])
    assert ra()["reason"] == "queued" and "대기 1건" in ra()["message"]
    note_sync_failure(target_store, TARGET, "ra", "transient: create_object — 게이트웨이 HTTP 503 upstream")
    assert ra()["reason"] == "transient" and "HTTP 503" in ra()["message"] and "실패 1회" in ra()["message"]
    mark_unavailable(target_store, TARGET, "ra", "forbidden: create_object — 시스템 관리자 권한이 필요합니다.")
    assert ra()["reason"] == "forbidden" and "재동기" in ra()["message"] and "시스템 관리자" in ra()["message"]
    mark_unavailable(target_store, TARGET, "ra", "no_credential")              # 종전 꼴의 글은 거절로 읽고 글을 그대로 싣는다
    assert ra()["reason"] == "rejected" and "no_credential" in ra()["message"]
    set_sync_state(target_store, TARGET, "ra", "withheld")
    assert ra()["reason"] == "withheld" and "조직 공개" in ra()["message"]
    set_sync_state(target_store, TARGET, "ra", "done")
    assert ra()["reason"] == "sent"


def test_set_sync_state_rejects_unknown_channel(target_store):
    with pytest.raises(ValueError):
        set_sync_state(target_store, TARGET, "kg", "done")
    with pytest.raises(ValueError):
        queue_sync_ops(target_store, TARGET, "kg", [])


def test_sync_badge_text(target_store, frozen_clock):
    assert sync_badge(empty_sync()) == "RA 반영: pending · AIDataHub 반영: pending"
    queue_sync_ops(target_store, TARGET, "ra", [{"op": "a"}, {"op": "b"}])
    mark_unavailable(target_store, TARGET, "adh", "no_credential")
    badge = sync_badge(load_external_sync(target_store, TARGET))
    assert badge == "RA 반영: pending(2) · AIDataHub 반영: unavailable"


# ---------------------------------------------------------------- MCP 전송(MockTransport)
def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _boom(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"자격 없이 외부 호출이 나갔다: {request.url}")


def _rpc_ok(result: dict) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def test_mcp_client_handshakes_then_calls_tool():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        seen.append(payload)
        assert request.headers["mcp-protocol-version"] == "2025-06-18"
        if payload["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}},
                                  headers={"mcp-session-id": "sess-1"})
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        assert request.headers["mcp-session-id"] == "sess-1"
        return _rpc_ok({"structuredContent": {"objects": [{"id": 7}]}})

    mcp = McpHttpClient("https://gw.test/mcp", headers={"Authorization": "Bearer pat"},
                        client=_client(handler))
    reply = mcp.call("search_objects", {"type_slug": "project"})
    assert reply == {"ok": True, "result": {"objects": [{"id": 7}]}}
    assert [p["method"] for p in seen] == ["initialize", "notifications/initialized", "tools/call"]
    assert seen[-1]["params"] == {"name": "search_objects", "arguments": {"type_slug": "project"}}

    mcp.call("get_object", {"id": 7})                       # 세션이 살아 있으면 재핸드셰이크는 없다
    assert [p["method"] for p in seen].count("initialize") == 1


def test_mcp_client_reads_sse_and_text_content():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] != "tools/call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        body = json.dumps({"jsonrpc": "2.0", "id": 2,
                           "result": {"content": [{"type": "text", "text": '{"n": 3}'}]}})
        return httpx.Response(200, text=f"event: message\ndata: {body}\n\n",
                              headers={"content-type": "text/event-stream"})

    mcp = McpHttpClient("https://gw.test/mcp", client=_client(handler))
    assert mcp.call("get_subgraph", {}) == {"ok": True, "result": {"n": 3}}


def test_mcp_client_maps_failures_without_raising():
    def http_401(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    reply = McpHttpClient("https://gw.test/mcp", client=_client(http_401)).call("get_object", {})
    assert reply["ok"] is False and reply["error"] == "http_401" and reply["status"] == 401

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    reply = McpHttpClient("https://gw.test/mcp", client=_client(refused)).call("get_object", {})
    assert reply["ok"] is False and reply["error"] == "transport_error"

    def tool_error(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] != "tools/call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        return _rpc_ok({"isError": True, "content": [{"type": "text", "text": "축 제약 위반"}]})

    reply = McpHttpClient("https://gw.test/mcp", client=_client(tool_error)).call("link_objects", {})
    assert reply["ok"] is False and reply["error"] == "tool_error" and reply["detail"] == "축 제약 위반"


# ---------------------------------------------------------------- RaClient(§5.3.5)
def test_ra_client_without_pat_is_unavailable_and_silent():
    ra = RaClient("https://gw.test/mcp", None, client=_client(_boom))
    assert ra.available is False
    assert ra.get_object("risk_finding", 7) == {"ok": False, "error": "unavailable", "reason": "no_credential"}
    assert ra.upsert_props("risk_finding", 7, {"a": 1}) == {"ok": False, "error": "unavailable",
                                                            "reason": "no_credential"}


def test_ra_client_only_calls_contracted_tools():
    """계약은 지식 그래프 쓰기 4종 + 읽기 4종이다 — 보고서 도구는 박스 PAT 클라이언트의 계약 밖이다(보고서는 사람 이름, 사용자 결정 10-31)."""
    ra = RaClient("https://gw.test/mcp", "pat", client=_client(_boom))
    for name in ("delete_object", "get_report", "update_report_draft"):
        assert ra.call_tool(name, {}) == {"ok": False, "error": "tool_not_contracted", "detail": name}
    assert set(RA_WRITE_TOOLS + RA_READ_TOOLS) == {
        "create_object", "update_object", "add_object_alias", "link_objects",
        "get_object", "search_objects", "get_subgraph", "list_object_types"}


def test_ra_upsert_props_merges_current_properties():
    """RA MCP 의 인자 이름 그대로(get_object(type, id) · update_object(object_id, …)) 게이트웨이 별칭으로 부른다 — 가린 값은 되쓰지 않는다."""
    calls: list[dict] = []
    current = {"a": 1, "b": 2}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] != "tools/call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        calls.append(payload["params"])
        if payload["params"]["name"] == "reportarchive_get_object":
            return _rpc_ok({"structuredContent": {"type": "risk_finding", "id": "7", "properties": current}})
        return _rpc_ok({"structuredContent": {"updated": True}})

    ra = RaClient("https://gw.test/mcp", "pat", client=_client(handler))
    assert ra.upsert_props("risk_finding", 7, {"b": 9, "c": 3})["ok"] is True
    assert [c["name"] for c in calls] == ["reportarchive_get_object", "reportarchive_update_object"]
    assert calls[0]["arguments"] == {"type": "risk_finding", "id": "7"}
    assert calls[1]["arguments"] == {"object_id": 7, "properties": {"a": 1, "b": 9, "c": 3}}

    # 바뀔 것이 없으면 부르지 않는다 · 가린 칸은 patch 가 채우면 그 값, 못 채우면 보내지 않는다.
    calls.clear()
    assert ra.upsert_props("risk_finding", 7, {"a": 1}) == {"ok": True, "result": {"unchanged": True}}
    current.update({"owner": "[가림:이름]", "memo": "연락 [가림:메일]"})
    assert ra.upsert_props("risk_finding", 7, {"owner": "me@example.com"}) == {
        "ok": False, "error": "masked_readback", "detail": ["memo"]}
    assert [c["name"] for c in calls] == ["reportarchive_get_object", "reportarchive_get_object"]


def test_ra_client_sends_the_ra_mcp_argument_names():
    """래퍼의 인자 이름은 RA MCP 서명 그대로다(ReportArchive mcp_server — dev 사본 3ece194 기준). 종전에는 get_object 에 type 이 없고
    update_object · add_object_alias 가 object_id 대신 id · entity_id, get_subgraph 가 entity_id 대신 id 를 보내 RA 가 받지 않았을 것이다."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] != "tools/call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        calls.append(payload["params"])
        return _rpc_ok({"structuredContent": {"ok": True}})

    ra = RaClient("https://gw.test/mcp", "pat", client=_client(handler))
    ra.get_object("incident", 5)
    ra.get_subgraph("12", ["exhibits"], depth=2)
    ra.create_object("design_trait", "char:a:b", "char:a:b", {"axis": "a"}, description="d")
    ra.update_object("12", {"status": "vocab"})
    ra.add_object_alias("12", "별칭")
    ra.link_objects(1, 2, "exhibits", properties={"support": 2})
    assert calls == [
        {"name": "reportarchive_get_object", "arguments": {"type": "incident", "id": "5"}},
        {"name": "reportarchive_get_subgraph", "arguments": {"entity_id": 12, "relations": ["exhibits"], "depth": 2}},
        {"name": "reportarchive_create_object", "arguments": {"type_slug": "design_trait", "value": "char:a:b",
                                                              "code": "char:a:b", "properties": {"axis": "a"},
                                                              "description": "d"}},
        {"name": "reportarchive_update_object", "arguments": {"object_id": 12, "properties": {"status": "vocab"}}},
        {"name": "reportarchive_add_object_alias", "arguments": {"object_id": 12, "alias": "별칭"}},
        {"name": "reportarchive_link_objects", "arguments": {"src_id": 1, "dst_id": 2, "relation": "exhibits",
                                                             "properties": {"support": 2}}}]


def test_ra_update_object_sends_only_the_fields_it_is_given():
    """거두기(RK-01)는 RA update_object 의 value · description 을 쓴다(ReportArchive mcp_server — dev 사본 3ece194: object_id · value · code ·
    description · properties, None 인 칸은 RA MCP 가 뺀다). 넘긴 칸만 싣고, 빈 설명은 빈 글 그대로 보낸다(RA 가 설명을 비운다)."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] != "tools/call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        calls.append(payload["params"]["arguments"])
        return _rpc_ok({"structuredContent": {"updated": True}})

    ra = RaClient("https://gw.test/mcp", "pat", client=_client(handler))
    ra.update_object("12", value="비공개@p1", description="")
    ra.update_object(13, {"visibility": "private"}, value="비공개@t#c")
    assert calls == [{"object_id": 12, "value": "비공개@p1", "description": ""},
                     {"object_id": 13, "value": "비공개@t#c", "properties": {"visibility": "private"}}]


def test_a_withheld_channel_whose_queue_empties_settles_done(target_store, frozen_clock):
    """보류(withheld) 대상이 거두기 op 만 남았다가 그것을 다 보내면 보류할 것이 없다 — done 이다(대기 0건인 보류로 남지 않는다)."""
    retract = {"op": "retract", "reason": "private", "kind": "project", "portal_id": "p_now", "project_id": "p_now", "by": OWNER}
    queue_sync_ops(target_store, TARGET, "ra", [retract])
    set_sync_state(target_store, TARGET, "ra", "withheld")
    complete_sync_ops(target_store, TARGET, "ra", [retract])
    entry = _sync_json(target_store)["ra"]
    assert entry["state"] == "done" and entry["pending_ops"] == []


def test_ra_401_is_recorded_as_unavailable_on_the_target(target_store, frozen_clock):
    """게이트웨이 401 은 예외가 아니라 채널 강등이다(§5.5.3 pending → unavailable)."""
    ra = RaClient("https://gw.test/mcp", "pat",
                  client=_client(lambda request: httpx.Response(401, text="no")))
    queue_sync_ops(target_store, TARGET, "ra", [{"op": "create_object", "code": "op1"}])
    reply = ra.create_object("assessment", "의견", "op1")
    assert reply["ok"] is False and reply["error"] == "http_401"

    mark_unavailable(target_store, TARGET, "ra", reply["error"])
    entry = _sync_json(target_store)["ra"]
    assert entry["state"] == "unavailable" and entry["last_error"] == "http_401"
    assert entry["pending_ops"] == [{"op": "create_object", "code": "op1"}]
    assert sync_badge(load_external_sync(target_store, TARGET)).startswith("RA 반영: unavailable")


# ---------------------------------------------------------------- AdhClient(§5.4)
def test_adh_without_api_key_is_unavailable_and_silent():
    adh = AdhClient("https://adh.test", None, client=_client(_boom))
    assert adh.available is False
    assert adh.import_records([{"_external_id": "opinion:a"}]) == {
        "ok": False, "error": "unavailable", "reason": "no_credential"}
    assert adh.hybrid_search("q")["error"] == "unavailable"


def test_adh_import_uses_rest_upsert_contract():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params)
        seen["key"] = request.headers.get("x-api-key")
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"records": [{"_external_id": "opinion:diff:d1:mech:1",
                                                      "record_id": "rec-1"}]})

    adh = AdhClient("https://adh.test", "k1", client=_client(handler))
    external_id = make_external_id("opinion", target_key="diff:d1", agent_key="mech", cycle=1)
    reply = adh.import_records([{"_external_id": external_id, "doc_type": "risk_review_opinion"}])

    assert seen["path"] == IMPORT_PATH == "/api/records/import"
    assert seen["query"] == {"external_source": EXTERNAL_SOURCE} == {"external_source": "hwax-risk"}
    assert seen["key"] == "k1"
    assert seen["body"]["dry_run"] is False
    assert seen["body"]["records"][0]["_external_id"] == "opinion:diff:d1:mech:1"
    assert adh.record_ids(reply) == {"opinion:diff:d1:mech:1": "rec-1"}


def test_adh_import_maps_http_error_without_raising():
    adh = AdhClient("https://adh.test", "k1",
                    client=_client(lambda request: httpx.Response(500, text="boom")))
    reply = adh.import_records([{"_external_id": "opinion:a"}])
    assert reply == {"ok": False, "error": "http_500", "detail": "boom", "status": 500}
    assert adh.import_records([]) == {"ok": True, "result": {"records": []}}      # 호출 자체가 없다


def test_make_external_id_contract():
    assert make_external_id("panel", panel_id="pan1") == "panel:pan1"
    assert make_external_id("character", project_id="p_now") == "character:p_now"
    assert make_external_id("pattern", pattern_id="P-017") == "pattern:P-017"
    assert make_external_id("digest", snapshot_id="s_tgt") == "digest:s_tgt"
    with pytest.raises(ValueError):
        make_external_id("opinion", target_key="diff:d1", agent_key="mech")      # cycle 누락
    with pytest.raises(ValueError):
        make_external_id("unknown", id="x")


def test_adh_search_tools_send_the_documented_arguments():
    """유사 검색 호출 형식(§5.4.7·§7.3 3단계·§5.6.3 2) — MCP tools/call 인자를 그대로 본다."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/mcp"
        assert request.headers.get("x-api-key") == "k1"
        payload = json.loads(request.content.decode())
        if payload["method"] != "tools/call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        calls.append(payload["params"])
        return _rpc_ok({"structuredContent": {"items": []}})

    adh = AdhClient("https://adh.test", "k1", client=_client(handler))
    adh.hybrid_search("요약 앞 300자", top_k=5, tags=["hwax-risk-review"])
    adh.tag_search(["char:intent:thin"], limit=20)
    adh.agent_search(MEMORY_AGENT, "DV2 요약", mode="hybrid",
                     required_tags=["hwax:expert:mech-housing-structure"], top_k=3)

    assert [c["name"] for c in calls] == ["hybrid_search", "tag_search", "agent_search"]
    assert calls[0]["arguments"] == {"q": "요약 앞 300자", "top_k": 5, "tags": ["hwax-risk-review"]}
    assert calls[1]["arguments"] == {"tags": ["char:intent:thin"], "limit": 20}
    assert calls[2]["arguments"] == {
        "agent_type": "risk-review-memory", "q": "DV2 요약", "mode": "hybrid",
        "required_tags": ["hwax:expert:mech-housing-structure"],
        "retrieval_config": {"top_k": 3}}


# ---------------------------------------------------------------- 러너 재시도 틱·소유권(plan §5.5.3·§0.9 P3-14)
def test_sync_loop_retries_a_due_channel_once_within_the_period(target_store, frozen_clock):
    """다음 주기(60 s) 안에 만기 채널을 정확히 1회 재시도한다 — 만기 전에는 부르지 않는다."""
    from app import config, runner

    queue_sync_ops(target_store, TARGET, "ra", [{"op": "create_object"}])
    note_sync_failure(target_store, TARGET, "ra", "http_500")      # next_at = now + 15분
    sent: list[tuple] = []

    def send(store, target_key, channel, ops):
        sent.append((target_key, channel, tuple(canonical(ops))))
        return True

    def canonical(ops):
        return tuple(json.dumps(op, sort_keys=True) for op in ops)

    risk_runner = runner.RiskRunner(target_store, config.settings, engine=None, external_sync_send=send)
    assert risk_runner._external_sync_tick() == {"due": 0, "sent": 0, "failed": 0}
    assert sent == []                                              # 아직 만기 전이다

    entry = _sync_json(target_store)["ra"]
    common.set_clock(lambda: entry["next_at"])                     # 만기 시각으로 시계를 옮긴다
    out = risk_runner._external_sync_tick()
    assert out == {"due": 1, "sent": 1, "failed": 0}
    assert len(sent) == 1 and sent[0][0:2] == (TARGET, "ra")
    # 성공하면 대기 op 가 비고 같은 주기에 두 번 보내지 않는다.
    assert risk_runner._external_sync_tick() == {"due": 0, "sent": 0, "failed": 0}
    assert len(sent) == 1
    assert _sync_json(target_store)["ra"]["pending_ops"] == []
    common.set_clock(lambda: NOW)


def test_resync_route_rejects_a_non_owner(target_store, monkeypatch):
    """재동기는 타깃 소유자만 — 구성원이 아닌 신원은 없는 타깃과 같은 (E404, 404) 다(그 타깃이 있다는 것을 흘리지 않는다 — review1
    남 숨김 훑기, 종전에는 403 이었다). 구성원인데 소유자가 아니면 403 이다."""
    from app import routes
    from app.errors import AppError

    monkeypatch.setattr(routes, "get_store", lambda: target_store)
    ident = type("I", (), {"anonymous": False, "email": "other@example.com", "role": None,
                           "to_dict": lambda self: {}})()
    with pytest.raises(AppError) as exc:
        routes.post_resync(TARGET, ident=ident)
    with pytest.raises(AppError) as missing:
        routes.post_resync("diff:no-such-target", ident=ident)
    assert (exc.value.code, exc.value.http_status, exc.value.message.replace(TARGET, "<key>")) == (
        "E404", 404, missing.value.message.replace("diff:no-such-target", "<key>"))

    owner = type("I", (), {"anonymous": False, "email": OWNER, "role": None,
                           "to_dict": lambda self: {}})()
    assert set(routes.post_resync(TARGET, ident=owner)) == set(SYNC_CHANNELS)
