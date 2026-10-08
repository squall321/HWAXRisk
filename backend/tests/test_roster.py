# 로스터 원천(plan §6.3·§6.4) — 게이트웨이 list_agents·recommend_agents 조회·강등·planner 연결(전부 MockTransport, 실 네트워크 0)
from __future__ import annotations

import json
import types

import httpx
import pytest

from app import config, identity, planner, ra_client, roster, routes

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
                   "relevance_source": "unavailable", "domains_ok": [], "domains_failed": [],
                   "deadline_exceeded": False}


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


# ---------------------------------------------------------------- 조회 전체의 기한(HWAXRISK_ROSTER_DEADLINE_S)
class _Clock:
    """`roster.time`·`ra_client.time` 을 대신한다 — monotonic 은 가짜 게이트웨이가 민다(시험은 기다리지 않는다)."""

    def __init__(self) -> None:
        self.now = 9000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(roster, "time", fake)
    monkeypatch.setattr(ra_client, "time", fake)
    return fake


class _PingsForever(httpx.SyncByteStream):
    """도구가 끝나지 않는 호출의 응답 — 15초마다 ping 주석 줄만 흘린다. 닫지 않고 끝까지 읽으면 시험이 실패한다."""

    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
        self.closed = False

    def __iter__(self):
        for _ in range(4000):                                   # 60000초 — 기한(540)을 한참 넘는다
            self.clock.now += 15
            yield b": ping - 2026-10-08 00:00:00+00:00\r\n\r\n"
        raise AssertionError("기한이 걸리지 않았다 — ping 만 흐르는 응답을 끝없이 읽는다")

    def close(self) -> None:
        self.closed = True


def test_one_stuck_call_cannot_outlive_the_roster_deadline(clock):
    """호출 하나가 ping 만 흘리며 끝나지 않아도 기한에서 놓는다 — 그 뒤로는 게이트웨이를 더 부르지 않는다.

    침묵 한도(60·120초)는 게이트웨이의 15초 ping 이 되감아 호출 길이를 자르지 못한다 — 호출 하나가 게이트웨이
    한도(600초)까지 가고, 16번이면 한 요청이 그 합까지 간다. 이 조회는 nginx /apps/(600초) 안의 동기 요청이라
    프록시가 먼저 504 를 내면 사용자는 빈 504 를 받고, 앱은 뒤늦게 타깃을 만들어 다시 누른 요청이 409 가 된다.
    기한은 호출 사이에서만 보면 모자라서 호출 안에서도 본다.
    """
    calls: list[dict] = []
    streams: list[_PingsForever] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] != "tools/call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})
        calls.append(payload["params"])
        streams.append(_PingsForever(clock))
        return httpx.Response(200, stream=streams[-1], headers={"content-type": "text/event-stream"})

    started = clock.now
    out = roster.RosterSource(GATEWAY, "pat", client=_client(handler)).fetch(DOMAINS, "요약", deadline_s=540)

    assert out["deadline_exceeded"] is True and (out["source"], out["reason"]) == ("unavailable", "deadline")
    assert out["relevance_source"] == "unavailable" and out["domains_failed"] == list(DOMAINS)
    # recommend_agents 한 번에서 기한을 다 썼다 — list_agents 는 한 번도 나가지 않았고, 붙든 응답은 닫았다.
    assert [c["name"] for c in calls] == [roster.RECOMMEND_AGENTS] and streams[0].closed
    assert clock.now - started == 540                           # 넘겨 듣는 폭은 ping 한 칸(15초)을 넘지 않는다


def test_a_call_past_its_deadline_is_not_sent(clock):
    """기한이 지난 호출은 게이트웨이에 보내지도 않는다 — 여러 호출이 한 기한을 나눠 쓸 때 남은 호출이 그렇게 끝난다."""
    sent: list[httpx.Request] = []
    mcp = ra_client.McpHttpClient(GATEWAY, client=_client(
        lambda request: sent.append(request) or httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}})))

    reply = mcp.call(roster.LIST_AGENTS, {"domain": "mech"}, deadline=clock.now)
    assert (reply["ok"], reply["error"]) == (False, "deadline_exceeded") and sent == []
    # 기한이 남았으면 그대로 간다(핸드셰이크 둘 + 호출 하나).
    assert mcp.call(roster.LIST_AGENTS, {"domain": "mech"}, deadline=clock.now + 1)["ok"] is True and len(sent) == 3


def test_a_spent_budget_stops_asking_and_names_the_domains_it_skipped(clock):
    """느린 호출이 쌓여 기한을 다 쓰면 남은 도메인은 묻지 않고 `domains_failed` 에 싣는다 — 받은 것은 그대로 쓴다."""
    domains = ("mech", "sim", "xd", "cam", "rel", "soc", "disp", "pcb")
    calls: list[dict] = []
    inner = _gateway_handler(calls)

    def slow(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content.decode())["method"] == "tools/call":
            clock.now += 100                                    # 호출마다 100초 — 게이트웨이가 바쁘다
        return inner(request)

    out = roster.RosterSource(GATEWAY, "pat", client=_client(slow)).fetch(domains, "요약", deadline_s=540)

    # 추천 100 · 도메인 넷 500 · 다섯째가 600 에 답해 기한(540)을 넘겼다 — 그 답은 버리고 나머지 셋은 묻지 않는다.
    assert out["source"] == "gateway" and out["relevance_source"] == "recommend_agents"
    assert out["domains_ok"] == ["mech", "sim", "xd", "cam"]
    assert out["domains_failed"] == ["rel", "soc", "disp", "pcb"] and out["deadline_exceeded"] is True
    assert [c["name"] for c in calls] == [roster.RECOMMEND_AGENTS] + [roster.LIST_AGENTS] * 5
    assert [a["key"] for a in out["agents"]][:2] == ["mech-frame", "mech-surface-treatment"]

    # 기한 안에 끝난 조회는 종전과 같다.
    calls.clear()
    quick = roster.RosterSource(GATEWAY, "pat", client=_client(_gateway_handler(calls))).fetch(
        DOMAINS, "요약", deadline_s=540)
    assert quick["deadline_exceeded"] is False and quick["domains_failed"] == [] and len(calls) == 4


def test_the_target_lookup_takes_its_limits_from_the_knobs(risk_store, tmp_path, clock, monkeypatch):
    """타깃 조회는 호출당 침묵 한도를 소스 호출 손잡이(120초, 연결 10초)에서, 전체 기한을 명단 손잡이(540초)에서 받는다."""
    (tmp_path / config.SECRETS_FILENAME).write_text("HWAXRISK_PORTAL_PAT=service-pat\n", encoding="utf-8")
    (tmp_path / config.SECRETS_FILENAME).chmod(0o600)
    assert config.DEFAULT_ROSTER_DEADLINE_S == 540

    source = roster.source_for(risk_store, OWNER, settings=_settings(tmp_path))
    assert source._mcp.timeout == httpx.Timeout(120.0, connect=10.0)
    tuned = types.SimpleNamespace(**vars(_settings(tmp_path)), risk_source_call_timeout_s=300)
    assert roster.source_for(risk_store, OWNER, settings=tuned)._mcp.timeout == httpx.Timeout(300.0, connect=10.0)

    seen: list[float | None] = []
    monkeypatch.setattr(roster.RosterSource, "fetch",
                        lambda self, domains, text="", *, deadline_s=None: seen.append(deadline_s) or {
                            "source": "gateway", "reason": None, "relevance_source": "unavailable",
                            "agents": [{"key": "mech-frame", "domain": "mech", "relevance": 0.0}],
                            "domains_ok": ["mech"], "domains_failed": ["sim", "xd"], "deadline_exceeded": True})
    out = roster.fetch_for_target(risk_store, kind="snap", ref_id="s1", owner_sub=OWNER, settings=_settings(tmp_path))
    short = types.SimpleNamespace(**vars(_settings(tmp_path)), risk_roster_deadline_s=90)
    roster.fetch_for_target(risk_store, kind="snap", ref_id="s1", owner_sub=OWNER, settings=short)
    assert seen == [540, 90]
    # 기한을 넘겼으면 값·손잡이·못 받은 도메인·순위가 어떻게 매겨졌는지를 한 줄로 말한다.
    assert out["notice"] == ("전문가 명단 조회가 540초 안에 끝나지 않았다(HWAXRISK_ROSTER_DEADLINE_S)"
                             " — 못 받은 도메인 sim·xd, 좌석 순위는 키 순서로 매겼다")


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
    # 이 스냅샷에는 요약문이 없어 추천을 묻지 않았다 — 그것도 응답이 말한다(순위는 키 순서다).
    assert (out["relevance_source"], out["domains_failed"]) == ("no_query", [])
    assert "roster_notice" not in out


def _state_summary(store) -> None:
    """스냅샷 s1 의 요약문 — 있어야 `recommend_agents` 를 묻는다(질의문이 비면 건너뛴다)."""
    store.execute(
        "INSERT INTO rr_states(snapshot_id, owner_sub, state_json, feature_json, gates_json,"
        " summary_text, summary_status, computed_at) VALUES (?,?,?,?,?,?,?,?)",
        ("s1", OWNER, "{}", "{}", "{}", "[대상] 스냅샷 요약", "ok", 100))


def test_the_target_response_says_how_the_roster_was_degraded(wired, ident, gateway_transport):
    """추천이 실패하면 좌석 순위가 키 순서로 떨어지고, 도메인 조회가 실패하면 그 도메인 좌석이 통째로 없다 — 응답이 말한다.

    종전 응답에는 `roster_source: "gateway"` 뿐이었다. 순위 1번이 Tier A 대표석이고 고정된 순위는 다시 매기지
    않으므로, 추천이 한 번 실패하면 도메인마다 키가 사전순으로 가장 앞선 전문가가 몇 시간짜리 패널에 앉는데
    그 사실이 어디에도 남지 않았다.
    """
    _snapshot(wired)
    _state_summary(wired)
    wired.upsert_credential(OWNER, _enc("owner-pat"), "sub", OWNER, "[]", 2_000_000_000)
    gateway_transport(_gateway_handler(fail={roster.RECOMMEND_AGENTS}, fail_domains={"sim"}))

    out = routes.create_target(routes.TargetBody(kind="snap", ref_id="s1", consent=True), ident=ident)
    assert (out["roster_source"], out["roster_size"]) == ("gateway", 3)
    assert (out["relevance_source"], out["domains_failed"]) == ("unavailable", ["sim"])
    assert "roster_notice" not in out                         # 기한을 넘긴 것은 아니다
    assert routes.refresh_roster("snap:s1", routes.RosterBody(), ident=ident) == {
        "added_pending": 0, "roster_source": "gateway", "relevance_source": "unavailable", "domains_failed": ["sim"]}


def test_the_target_response_carries_the_deadline_notice(wired, ident, gateway_transport, clock):
    """명단 조회가 기한을 넘기면 타깃은 받은 만큼으로 열리고, 응답이 기한·손잡이·못 받은 도메인을 말한다."""
    _snapshot(wired)
    _state_summary(wired)
    wired.upsert_credential(OWNER, _enc("owner-pat"), "sub", OWNER, "[]", 2_000_000_000)
    inner = _gateway_handler()

    def slow(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content.decode())["method"] == "tools/call":
            clock.now += 250                                  # 추천 250 · mech 500 · sim 750(기한 540 을 넘긴다)
        return inner(request)

    gateway_transport(slow)
    out = routes.create_target(routes.TargetBody(kind="snap", ref_id="s1", consent=True), ident=ident)
    assert (out["roster_source"], out["roster_size"]) == ("gateway", 2)
    assert (out["relevance_source"], out["domains_failed"]) == ("recommend_agents", ["sim", "xd"])
    assert out["roster_notice"] == ("전문가 명단 조회가 540초 안에 끝나지 않았다(HWAXRISK_ROSTER_DEADLINE_S)"
                                    " — 못 받은 도메인 sim·xd")


def test_create_target_prefers_body_agents_over_the_gateway(wired, ident, gateway_transport):
    _snapshot(wired)
    wired.upsert_credential(OWNER, _enc("owner-pat"), "sub", OWNER, "[]", 2_000_000_000)
    gateway_transport(_boom)                     # 본문이 있으면 게이트웨이를 부르지 않는다

    out = routes.create_target(
        routes.TargetBody(kind="snap", ref_id="s1", consent=True,
                          agents=[{"key": "mech-frame", "domain": "mech", "relevance": 1.0}]), ident=ident)
    assert out["roster_source"] == "body.agents" and out["roster_size"] == 1
    assert (out["relevance_source"], out["domains_failed"]) == ("body.agents", [])


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
    assert out == {"added_pending": 4, "roster_source": "gateway", "relevance_source": "no_query",
                   "domains_failed": []}
    rows = wired.query("SELECT agent_key, rank_in_domain FROM rr_roster WHERE target_key = ? AND domain = 'mech'"
                       " ORDER BY rank_in_domain", ("snap:s1",))
    assert [(r["agent_key"], r["rank_in_domain"]) for r in rows] == [
        ("mech-frame", 1), ("mech-surface-treatment", 2)]        # 기존 rank 는 불변


def test_refresh_roster_without_credential_reports_unavailable(wired, ident, gateway_transport):
    _target(wired, "snap:s1", kind="snap", ref_id="s1")
    gateway_transport(_boom)
    assert routes.refresh_roster("snap:s1", routes.RosterBody(), ident=ident) == {
        "added_pending": 0, "roster_source": "unavailable", "relevance_source": "unavailable", "domains_failed": []}


# ------------------------------------------------- §4.8 스냅샷 변경 시 무효화 배선
def _second_snapshot(store, sid="s2", ir_hash="h2") -> None:
    store.execute(
        "INSERT INTO rr_snapshots(id, owner_sub, project_id, ir_version, ir_hash, ir_json,"
        " source_ids_json, kinds_json, node_count, edge_count, missing_json, warnings_n, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, OWNER, "p1", "1", ir_hash, "{}", "[]", json.dumps(["mcad"]), 3, 2, "{}", 0, 200))


def test_a_new_target_closes_the_previous_one(wired, ident):
    """§4.8 1 — T′ 가 생기면 T 는 `superseded_by=T′` 로 닫힌다. 행은 그대로 남는다."""
    _snapshot(wired)
    _second_snapshot(wired)
    first = routes.create_target(routes.TargetBody(kind="snap", ref_id="s1", consent=True,
                                                   agents=[]), ident=ident)
    second = routes.create_target(routes.TargetBody(kind="snap", ref_id="s2", consent=True,
                                                    agents=[]), ident=ident)

    assert second["superseded"]["previous_target_key"] == first["target_key"]
    row = wired.query_one("SELECT superseded_by FROM rr_targets WHERE target_key = ?",
                          (first["target_key"],))
    assert row["superseded_by"] == second["target_key"]
    # 첫 타깃일 때는 닫을 것이 없다.
    assert first["superseded"]["previous_target_key"] is None


def test_without_a_diff_the_ckey_comparison_is_skipped_not_treated_as_empty(wired, ident):
    """**빈 `changed_ckeys` 로 진행하지 않는다.**

    빈 집합은 '아무것도 안 바뀌었다' 와 같아서 등록부는 stale 0건, 좌석은 전원 carried 가 된다 —
    재검증 없이 통과시키는 쪽이므로 '없는 리스크' 다. 두 스냅샷 사이 diff 가 없으면 건너뛰고 사유를 남긴다.
    """
    _snapshot(wired)
    _second_snapshot(wired)
    routes.create_target(routes.TargetBody(kind="snap", ref_id="s1", consent=True, agents=[]), ident=ident)
    out = routes.create_target(routes.TargetBody(kind="snap", ref_id="s2", consent=True, agents=[]),
                               ident=ident)["superseded"]

    assert out["skipped"] == "diff_absent"
    assert out["changed_ckeys"] is None, "모르는 값을 0 으로 적었다"
    assert "registry" not in out and "carried" not in out


def test_character_statements_citing_a_changed_ckey_need_review(wired, ident):
    """§4.8 5 — 성격 행은 옮기지 않고 인용 ckey 가 변경에 들면 재확인 표기만 남긴다(status 는 불변)."""
    _snapshot(wired)
    wired.execute(
        "INSERT INTO rr_character(id, project_id, owner_sub, facet, tag, tags_json, statement, polarity,"
        " cites_json, by_json, support_panels, support_targets, recall_eligible, needs_review, status,"
        " created_at, updated_at) VALUES ('C1','p1',?,'intent','char:structure:thin_stack','[]','문장',"
        "'observation',?,'[]',1,1,1,0,'confirmed',1,1)",
        (OWNER, json.dumps([{"ref": "p:aaaaaaaaaaaa", "ckey": "ck:changed0001"}])))

    n = routes._flag_character_needs_review(wired, "p1", {"ck:changed0001"}, 300)

    assert n == 1
    row = wired.query_one("SELECT needs_review, status FROM rr_character WHERE id = 'C1'")
    assert row["needs_review"] == 1
    assert row["status"] == "confirmed", "코드가 사람 판정(confirmed)을 내렸다"
    # 두 번 돌려도 같은 행을 다시 세지 않는다(needs_review=0 만 본다).
    assert routes._flag_character_needs_review(wired, "p1", {"ck:changed0001"}, 300) == 0
