# external_sync 상태기계(plan §5.5.3)와 외부 클라이언트 배선 — RA·AIDataHub 호출 형식·unavailable 강등(전부 MockTransport, 실 네트워크 0)
from __future__ import annotations

import json

import httpx
import pytest

from app import common
from app.adh_client import (EXTERNAL_SOURCE, IMPORT_PATH, MEMORY_AGENT, AdhClient, make_external_id)
from app.ra_client import (RA_READ_TOOLS, RA_REPORT_TOOLS, RA_WRITE_TOOLS, SYNC_BASE_DELAY,
                           SYNC_CHANNELS, SYNC_MAX_ATTEMPTS, SYNC_MAX_DELAY, McpHttpClient, RaClient,
                           complete_sync_ops, empty_sync, load_external_sync, mark_unavailable,
                           note_sync_failure, queue_sync_ops, resync, save_external_sync,
                           set_sync_state, sync_badge)

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


def test_resync_restores_both_channels(target_store, frozen_clock):
    mark_unavailable(target_store, TARGET, "ra", "no_credential")
    note_sync_failure(target_store, TARGET, "adh", "http_500")
    resync(target_store, TARGET)
    for channel in SYNC_CHANNELS:
        entry = _sync_json(target_store)[channel]
        assert entry["state"] == "pending"
        assert entry["attempts"] == 0 and entry["next_at"] == 0 and entry["last_error"] is None


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
    assert ra.get_object(7) == {"ok": False, "error": "unavailable", "reason": "no_credential"}
    assert ra.upsert_props(7, {"a": 1}) == {"ok": False, "error": "unavailable",
                                            "reason": "no_credential"}


def test_ra_client_only_calls_contracted_tools():
    ra = RaClient("https://gw.test/mcp", "pat", client=_client(_boom))
    assert ra.call_tool("delete_object", {}) == {"ok": False, "error": "tool_not_contracted",
                                                 "detail": "delete_object"}
    assert set(RA_WRITE_TOOLS + RA_READ_TOOLS + RA_REPORT_TOOLS) == {
        "create_object", "update_object", "add_object_alias", "link_objects",
        "get_object", "search_objects", "get_subgraph", "list_object_types",
        "get_report", "update_report_draft"}


def test_ra_upsert_props_merges_current_properties():
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] != "tools/call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        calls.append(payload["params"])
        if payload["params"]["name"] == "get_object":
            return _rpc_ok({"structuredContent": {"object": {"properties": {"a": 1, "b": 2}}}})
        return _rpc_ok({"structuredContent": {"ok": True}})

    ra = RaClient("https://gw.test/mcp", "pat", client=_client(handler))
    assert ra.upsert_props(7, {"b": 9, "c": 3})["ok"] is True
    assert [c["name"] for c in calls] == ["get_object", "update_object"]
    assert calls[1]["arguments"] == {"id": 7, "properties": {"a": 1, "b": 9, "c": 3}}


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
    """재동기는 타깃 소유자만 — 다른 신원은 (E403, 403) 이다."""
    from app import routes
    from app.errors import AppError

    monkeypatch.setattr(routes, "get_store", lambda: target_store)
    ident = type("I", (), {"anonymous": False, "email": "other@example.com", "role": None,
                           "to_dict": lambda self: {}})()
    with pytest.raises(AppError) as exc:
        routes.post_resync(TARGET, ident=ident)
    assert (exc.value.code, exc.value.http_status) == ("E403", 403)

    owner = type("I", (), {"anonymous": False, "email": OWNER, "role": None,
                           "to_dict": lambda self: {}})()
    assert set(routes.post_resync(TARGET, ident=owner)) == set(SYNC_CHANNELS)
