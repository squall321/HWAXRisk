# 로스터 원천(plan §6.3·§6.4) — 게이트웨이 list_agents·recommend_agents 조회·강등·planner 연결(전부 MockTransport, 실 네트워크 0)
from __future__ import annotations

import json
import types

import httpx
import pytest

from app import config, identity, planner, roster, routes

OWNER = "roster@example.com"

def _enc(pat: str) -> str:
    """저장 열 portal_pat_enc 는 Fernet 암호문이다(plan §8.2.7) — 픽스처도 같은 형식으로 넣는다."""
    return identity.encrypt_pat(pat).decode("ascii")

GATEWAY = "https://gw.test/mcp"
DOMAINS = ("mech", "sim", "xd")

# 게이트웨이 실측 응답 형상 — list_agents 는 {'result': [{agent_type, name, common_tags}]},
# recommend_agents 는 {'query', 'agents': [{agent_type, score, …}], …} 다.
CATALOG = {
    "mech": ["mech-frame", "mech-surface-treatment"],
    "sim": ["sim-drop", "sim-thermal"],
    "xd": ["xd-assembly"],
}
SCORES = {"mech-frame": 2.6, "sim-drop": 2.35, "xd-assembly": 0.5}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _boom(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"자격 없이 게이트웨이 호출이 나갔다: {request.url}")


def _rpc_ok(result: dict) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def _gateway_handler(calls: list[dict] | None = None, *, fail: set[str] | None = None,
                     fail_domains: set[str] | None = None):
    """list_agents·recommend_agents 를 흉내 내는 MockTransport 핸들러."""
    fail = fail or set()
    fail_domains = fail_domains or set()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] != "tools/call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        params = payload["params"]
        if calls is not None:
            calls.append(params)
        name, args = params["name"], params["arguments"]
        if name in fail:
            return httpx.Response(500, text="gateway down")
        if name == roster.RECOMMEND_AGENTS:
            agents = [{"agent_type": key, "name": key, "score": score} for key, score in SCORES.items()]
            return _rpc_ok({"structuredContent": {"query": args["q"], "agents": agents}})
        if name == roster.LIST_AGENTS:
            domain = args["domain"]
            if domain in fail_domains:
                return _rpc_ok({"isError": True, "content": [{"type": "text", "text": "boom"}]})
            rows = [{"agent_type": key, "name": key, "common_tags": [domain]}
                    for key in CATALOG.get(domain, [])]
            return _rpc_ok({"structuredContent": {"result": rows}})
        raise AssertionError(f"계약 밖 도구를 불렀다: {name}")

    return handler


# ---------------------------------------------------------------- 응답 파싱
def test_parse_agent_list_reads_agent_type_and_falls_back_to_queried_domain():
    rows = roster.parse_agent_list({"result": [{"agent_type": "mech-frame"},
                                               {"agent_type": "mech-frame"},          # 중복은 한 번만
                                               {"agent_type": "pcb-stackup", "domain": "PCB"},
                                               {"name": "키 없음"}]}, "mech")
    assert rows == [{"key": "mech-frame", "domain": "mech"},
                    {"key": "pcb-stackup", "domain": "pcb"}]


def test_parse_agent_list_accepts_bare_list_and_agents_envelope():
    assert roster.parse_agent_list([{"agent_type": "sim-drop"}], "sim") == [{"key": "sim-drop", "domain": "sim"}]
    assert roster.parse_agent_list({"agents": [{"key": "xd-a"}]}, "xd") == [{"key": "xd-a", "domain": "xd"}]
    assert roster.parse_agent_list({"note": "형상이 다르다"}, "mech") == []


def test_parse_recommendations_maps_score_by_agent_key():
    scores = roster.parse_recommendations(
        {"agents": [{"agent_type": "mech-frame", "score": 2.6},
                    {"agent_type": "mech-frame", "score": 1.0},        # 큰 쪽을 남긴다
                    {"agent_type": "sim-drop"},                        # score 없으면 0.0
                    {"score": 9.9}]})
    assert scores == {"mech-frame": 2.6, "sim-drop": 0.0}


# ---------------------------------------------------------------- 조회·강등
def test_without_credential_no_call_goes_out_and_source_is_unavailable():
    source = roster.RosterSource(GATEWAY, None, client=_client(_boom))
    assert source.available is False
    out = source.fetch(DOMAINS, "요약")
    assert out == {"source": "unavailable", "reason": "no_credential", "agents": [],
                   "relevance_source": "unavailable", "domains_ok": [], "domains_failed": []}


def test_fetch_collects_pool_per_domain_and_attaches_relevance():
    calls: list[dict] = []
    source = roster.RosterSource(GATEWAY, "pat", client=_client(_gateway_handler(calls)))
    out = source.fetch(DOMAINS, " [대상] DV2 " + "x" * 800)

    assert out["source"] == "gateway" and out["relevance_source"] == "recommend_agents"
    assert out["domains_ok"] == list(DOMAINS) and out["domains_failed"] == []
    assert out["agents"] == [
        {"key": "mech-frame", "domain": "mech", "relevance": 2.6},
        {"key": "mech-surface-treatment", "domain": "mech", "relevance": 0.0},   # 추천 목록 밖은 0
        {"key": "sim-drop", "domain": "sim", "relevance": 2.35},
        {"key": "sim-thermal", "domain": "sim", "relevance": 0.0},
        {"key": "xd-assembly", "domain": "xd", "relevance": 0.5},
    ]
    # 호출은 recommend_agents 1회 + 도메인당 list_agents 1회이고 질의문은 500자로 잘린다.
    assert [c["name"] for c in calls] == [roster.RECOMMEND_AGENTS] + [roster.LIST_AGENTS] * 3
    assert len(calls[0]["arguments"]["q"]) == roster.QUERY_TEXT_MAX == 500
    assert calls[0]["arguments"]["top_k"] == roster.RECOMMEND_TOP_K == 60
    assert [c["arguments"] for c in calls[1:]] == [{"compact": True, "domain": d} for d in DOMAINS]


def test_recommend_failure_degrades_relevance_but_keeps_the_pool():
    source = roster.RosterSource(GATEWAY, "pat",
                                 client=_client(_gateway_handler(fail={roster.RECOMMEND_AGENTS})))
    out = source.fetch(DOMAINS, "요약")
    assert out["source"] == "gateway" and out["relevance_source"] == "unavailable"
    assert {a["relevance"] for a in out["agents"]} == {0.0}
    assert len(out["agents"]) == 5


def test_empty_query_skips_recommend_agents():
    calls: list[dict] = []
    source = roster.RosterSource(GATEWAY, "pat", client=_client(_gateway_handler(calls)))
    out = source.fetch(("mech",), "   ")
    assert out["relevance_source"] == "no_query"
    assert [c["name"] for c in calls] == [roster.LIST_AGENTS]


def test_partial_domain_failure_keeps_the_rest_and_reports_it():
    source = roster.RosterSource(GATEWAY, "pat",
                                 client=_client(_gateway_handler(fail_domains={"sim"})))
    out = source.fetch(DOMAINS, "요약")
    assert out["source"] == "gateway"
    assert out["domains_ok"] == ["mech", "xd"] and out["domains_failed"] == ["sim"]
    assert [a["key"] for a in out["agents"]] == ["mech-frame", "mech-surface-treatment", "xd-assembly"]


def test_gateway_down_degrades_to_empty_roster_without_raising():
    source = roster.RosterSource(GATEWAY, "pat", client=_client(_gateway_handler(fail={roster.LIST_AGENTS})))
    out = source.fetch(DOMAINS, "요약")
    assert out["source"] == "unavailable" and out["reason"] == "gateway_error" and out["agents"] == []


def test_transport_error_is_not_raised():
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    out = roster.RosterSource(GATEWAY, "pat", client=_client(refused)).fetch(DOMAINS, "요약")
    assert out["source"] == "unavailable" and out["reason"] == "gateway_error"


# ---------------------------------------------------------------- planner 연결(§6.3 rank 규칙)
def test_fetched_rows_feed_freeze_roster_and_rank_by_relevance(risk_store):
    _target(risk_store, "snap:s1", kind="snap", ref_id="s1")
    source = roster.RosterSource(GATEWAY, "pat", client=_client(_gateway_handler()))
    fetched = source.fetch(DOMAINS, "요약")

    out = planner.freeze_roster(risk_store, "snap:s1", OWNER, fetched["agents"])
    assert out["roster_size"] == 5 and out["deferred"] == 0
    rows = risk_store.query(
        "SELECT agent_key, domain, relevance, rank_in_domain FROM rr_roster WHERE target_key = ?"
        " ORDER BY domain, rank_in_domain", ("snap:s1",))
    assert [(r["domain"], r["rank_in_domain"], r["agent_key"]) for r in rows] == [
        ("mech", 1, "mech-frame"), ("mech", 2, "mech-surface-treatment"),
        ("sim", 1, "sim-drop"), ("sim", 2, "sim-thermal"),
        ("xd", 1, "xd-assembly")]
    assert rows[0]["relevance"] == pytest.approx(2.6)


# ---------------------------------------------------------------- 자격·질의문
def _settings(tmp_path, domains=DOMAINS):
    return types.SimpleNamespace(gateway_mcp=GATEWAY, data_dir=tmp_path, risk_roster_domains=domains)


def test_credential_prefers_owner_pat_then_service_pat(risk_store, tmp_path):
    cfg = _settings(tmp_path)
    assert roster.credential(risk_store, OWNER, settings=cfg) == ""

    secrets = tmp_path / config.SECRETS_FILENAME
    secrets.write_text("HWAXRISK_PORTAL_PAT=service-pat\n", encoding="utf-8")
    secrets.chmod(0o600)
    assert roster.credential(risk_store, OWNER, settings=cfg) == "service-pat"

    far = 2_000_000_000
    risk_store.upsert_credential(OWNER, _enc("owner-pat"), "sub", OWNER, "[]", far)
    assert roster.credential(risk_store, OWNER, settings=cfg) == "owner-pat"

    risk_store.upsert_credential(OWNER, _enc("expired-pat"), "sub", OWNER, "[]", 1)
    assert roster.credential(risk_store, OWNER, settings=cfg) == "service-pat"   # 만료된 owner PAT 는 쓰지 않는다


def test_query_text_reads_summary_of_state_or_diff(risk_store):
    risk_store.execute(
        "INSERT INTO rr_states(snapshot_id, owner_sub, state_json, feature_json, gates_json,"
        " summary_text, summary_status, computed_at) VALUES (?,?,?,?,?,?,?,?)",
        ("s1", OWNER, "{}", "{}", "{}", "[대상] 스냅샷 요약 " + "가" * 800, "ok", 100))
    text = roster.query_text(risk_store, "snap", "s1")
    assert text.startswith("[대상] 스냅샷 요약") and len(text) == roster.QUERY_TEXT_MAX

    risk_store.execute(
        "INSERT INTO rr_diffs(id, owner_sub, base_snapshot_id, target_snapshot_id, base_project_id,"
        " target_project_id, pair_kind, diff_version, diff_json, summary_text, summary_status, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("d1", OWNER, "s0", "s1", "p", "p", "same_project_revision", "1", "{}", "[대상] diff 요약", "ok", 100))
    assert roster.query_text(risk_store, "diff", "d1") == "[대상] diff 요약"
    assert roster.query_text(risk_store, "diff", "없음") == ""


# ---------------------------------------------------------------- 라우트 배선(§8.2.3)
def _target(store, target_key: str, *, kind: str, ref_id: str) -> None:
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, level,"
        " external_sync_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (target_key, OWNER, kind, ref_id, "p1", "h1", "C0", "{}", 100, 100))


@pytest.fixture
def ident() -> identity.Identity:
    return identity.Identity(email=OWNER, display_name="R", role="user", organization="qa",
                             anonymous=False, source="bearer")


@pytest.fixture
def wired(risk_store, monkeypatch):
    """라우트 본문이 이 테스트의 빈 DB 를 보게 하고, Settings 도메인을 3종으로 줄인다."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(config, "settings", types.SimpleNamespace(
        **{**vars(config.settings), "risk_roster_domains": DOMAINS, "gateway_mcp": GATEWAY}))
    return risk_store


@pytest.fixture
def gateway_transport(request):
    """roster 모듈 전역 전송을 MockTransport 로 바꾼다(테스트 종료 시 복원)."""
    def install(handler) -> None:
        previous = roster.set_transport(httpx.MockTransport(handler))
        request.addfinalizer(lambda: roster.set_transport(previous))

    return install


def _snapshot(store) -> None:
    store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, created_at, updated_at) VALUES (?,?,?,?,?)",
        ("p1", OWNER, "M22", 100, 100))
    store.execute(
        "INSERT INTO rr_snapshots(id, owner_sub, project_id, ir_version, ir_hash, ir_json,"
        " source_ids_json, kinds_json, node_count, edge_count, missing_json, warnings_n, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("s1", OWNER, "p1", "1", "h1", "{}", "[]", json.dumps(["mcad"]), 3, 2, "{}", 0, 100))


def test_create_target_uses_the_gateway_when_body_agents_are_absent(wired, ident, gateway_transport):
    _snapshot(wired)
    wired.upsert_credential(OWNER, _enc("owner-pat"), "sub", OWNER, "[]", 2_000_000_000)
    gateway_transport(_gateway_handler())

    out = routes.create_target(routes.TargetBody(kind="snap", ref_id="s1", consent=True), ident=ident)
    assert out["roster_source"] == "gateway" and out["roster_size"] == 5
    assert [t["tier"] for t in out["tier_plan"]] == ["A", "B", "C"]
    assert wired.query_one("SELECT COUNT(*) AS n FROM rr_coverage WHERE target_key = ?",
                           ("snap:s1",))["n"] == 5


def test_create_target_prefers_body_agents_over_the_gateway(wired, ident, gateway_transport):
    _snapshot(wired)
    wired.upsert_credential(OWNER, _enc("owner-pat"), "sub", OWNER, "[]", 2_000_000_000)
    gateway_transport(_boom)                     # 본문이 있으면 게이트웨이를 부르지 않는다

    out = routes.create_target(
        routes.TargetBody(kind="snap", ref_id="s1", consent=True,
                          agents=[{"key": "mech-frame", "domain": "mech", "relevance": 1.0}]), ident=ident)
    assert out["roster_source"] == "body.agents" and out["roster_size"] == 1


def test_create_target_without_credential_degrades_to_empty_roster(wired, ident, gateway_transport):
    _snapshot(wired)
    gateway_transport(_boom)                     # 자격이 없으면 호출 자체가 없다

    out = routes.create_target(routes.TargetBody(kind="snap", ref_id="s1", consent=True), ident=ident)
    assert out["roster_source"] == "unavailable"
    assert out["roster_size"] == 0 and out["tier_plan"] is None and out["cost_estimate"] is None
    assert wired.query_one("SELECT roster_frozen_at FROM rr_targets WHERE target_key = ?",
                           ("snap:s1",))["roster_frozen_at"] is None


def test_refresh_roster_fetches_the_gateway_and_appends_only_new_keys(wired, ident, gateway_transport):
    _target(wired, "snap:s1", kind="snap", ref_id="s1")
    planner.freeze_roster(wired, "snap:s1", OWNER, [{"key": "mech-frame", "domain": "mech", "relevance": 2.6}])
    wired.upsert_credential(OWNER, _enc("owner-pat"), "sub", OWNER, "[]", 2_000_000_000)
    gateway_transport(_gateway_handler())

    out = routes.refresh_roster("snap:s1", routes.RosterBody(), ident=ident)
    assert out == {"added_pending": 4, "roster_source": "gateway"}
    rows = wired.query("SELECT agent_key, rank_in_domain FROM rr_roster WHERE target_key = ? AND domain = 'mech'"
                       " ORDER BY rank_in_domain", ("snap:s1",))
    assert [(r["agent_key"], r["rank_in_domain"]) for r in rows] == [
        ("mech-frame", 1), ("mech-surface-treatment", 2)]        # 기존 rank 는 불변


def test_refresh_roster_without_credential_reports_unavailable(wired, ident, gateway_transport):
    _target(wired, "snap:s1", kind="snap", ref_id="s1")
    gateway_transport(_boom)
    assert routes.refresh_roster("snap:s1", routes.RosterBody(), ident=ident) == {
        "added_pending": 0, "roster_source": "unavailable"}
