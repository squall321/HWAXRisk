# E2E 스모크 — 실 어댑터 계약(MockTransport 위 가짜 StepForge·KooRemapper)과 FakePanelEngine 으로 과제→소스→스냅샷→게이트→2차 스냅샷→same-as→diff→타깃→편성→패널→원자→등록부→완결→브리프→export 왕복을 외부 호출 0 으로 한 번 흘린다(plan §9 통과 기준)
from __future__ import annotations

import collections
import copy
import dataclasses
import json

import httpx
import pytest

from app import brief as brief_module
from app import config
from app import diff as diff_module, export, identity, ir_builder, narrative, planner, registry, routes, sameas
from app import state as state_module
from app.adapters import registry as adapters_registry
from app.adapters.base import RestGetClient
from app.common import sha256_hex
from app.errors import AppError
from app.ra_client import McpHttpClient
from app.risk_store import RiskStore
from tests import test_adapters as recon
from tests.conftest import FIXTURES_DIR

OWNER = "e2e@example.com"
PROJECT_CODE = "M22E2E"

# 로스터 씨앗 — 도메인 5종(Settings 화이트리스트 안)·도메인당 2석. Tier B 는 도메인별 rank 1 만 앉힌다.
ROSTER_DOMAINS = ("mech", "sim", "xd", "rel", "disp")


# ---------------------------------------------------------------- 외부 호출 금지(통과 기준: 외부 호출 0)
@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """실제 소켓으로 나가는 httpx 전송을 전부 막는다. 이 파일의 어떤 단계도 네트워크를 쓰지 않는다."""
    def _blocked(*_args, **_kwargs):
        raise AssertionError("E2E 스모크는 외부 호출을 하지 않는다.")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _blocked)


@pytest.fixture(autouse=True)
def seeded_discovery():
    """소스 등록은 어댑터 가용성을 게이트웨이에 묻는다 — 그 답을 미리 캐시에 넣어 호출 없이 진행한다.

    발견 결과를 지어내지 않고 실제 형태 그대로 넣는다(도구가 다 보이는 정상 상태).
    """
    from app.adapters import dyna as dyna_adapter
    from app.adapters import mcad
    from app.adapters import registry as adapters_registry

    tools = {name: "heax-step_forge" for name in mcad.REQUIRED_TOOLS}
    tools.update({name: "heax-kooremapper_mcp" for name in dyna_adapter.REQUIRED_TOOLS})

    def handler(request):
        return httpx.Response(200, json={"map": tools})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        adapters_registry.discover_adapters(client=http, force=True)
    finally:
        http.close()
    yield
    adapters_registry.reset_discovery_cache()


@pytest.fixture
def ident() -> identity.Identity:
    return identity.Identity(email=OWNER, display_name="E2E", role="user", organization="qa",
                             anonymous=False, source="bearer")


@pytest.fixture
def wired(risk_store, monkeypatch):
    """라우트 본문이 이 테스트의 빈 DB 를 보게 한다(라우트는 모듈 전역 get_store 를 부른다)."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    return risk_store


# ---------------------------------------------------------------- 가짜 어댑터(adapters/*.py 의 capture 자리)
def _fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / "ir" / name).read_text(encoding="utf-8"))


class FakeSourceApps:
    """정찰(recon) 실측 응답 형상을 그대로 돌려주는 가짜 StepForge·KooRemapper.

    실 어댑터(app/adapters/*.py)가 이 응답 위에서 돌므로 계약이 깨지면 이 스모크가 먼저 깨진다.
    전송은 httpx.MockTransport 뿐이라 소켓으로 나가는 호출이 하나도 없다.
    """

    def __init__(self) -> None:
        self.rest = copy.deepcopy(recon.REST_ROUTES)
        self.tools = copy.deepcopy(dict(
            recon.MCP_TOOLS_FULL,
            inspect_file=recon.INSPECT_FILE,
            material_usage={"materials": []},
            section_contact_usage={"sections": []},
            corpus_summary={"sessions": 12},
            report_summary={"id": "r1", "kind": "sphere", "label": "낙하", "summary": "낙하 12케이스 요약",
                            "n_cases": 12, "sim_params": {"unit_system": "mm-kg-ms", "drop_height": 1.2}},
            report_part_risk={"report_id": "r1", "kind": "sphere", "parts": [
                {"part_id": "1", "part_name": "Stack\\PLATE_1",
                 "worst_stress": {"value": 210.0, "case_key": "0deg"}, "worst_g": {"value": 900.0},
                 "worst_disp": None, "min_safety_factor": None}]},
            report_findings=[],
            report_worst_cases=[{"case_key": "0deg", "identity": {"angle": 0}, "max_stress": 210.0,
                                 "max_g": 900.0, "max_disp": 1.1, "min_safety_factor": None}],
            report_energy_flow={"edges": []},
        ))
        self.rest_seen: list[str] = []
        self.mcp_seen: list[tuple[str, dict]] = []

    # ---- 2차 스냅샷용 설계 변경 — PLATE_2 두께 1.0→1.4 mm · PLATE_1 재질 교체 · tied 간극 0.00→0.35 mm.
    def revise(self) -> None:
        tree = self.rest[f"{recon.BASE}/tree"]
        s2 = tree["shape_defs"]["s2"]
        s2["bbox"][5] = 1.4
        s2["volume"] = 2800.0
        tree["shape_defs"]["s1"]["material"] = "AZ91D"
        for part in self.rest[f"{recon.BASE}/parts"]["parts"]:
            if part["shape_def_id"] == "s2":
                part["bbox"][5] = 1.4
                part["volume"] = 2800.0
        self.tools["list_interfaces"]["interfaces"][0]["min_gap"] = 0.35
        self.tools["interface_graph"]["edges"][0]["min_gap"] = 0.35

    # ---- 전송(MockTransport). 계약에 없는 도구·경로는 소스 앱처럼 오류로 돌려준다.
    def _mcp_handler(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}},
                                  headers={"mcp-session-id": "sess-e2e"})
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        name = payload["params"]["name"]
        self.mcp_seen.append((name, payload["params"]["arguments"]))
        if name not in self.tools:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {
                "isError": True, "content": [{"type": "text", "text": f"unknown tool: {name}"}]}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                         "result": {"structuredContent": self.tools[name]}})

    def _rest_handler(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "GET", "어댑터는 소스 앱에 GET 만 한다."
        assert request.headers["authorization"] == "Bearer service-pat"
        self.rest_seen.append(request.url.path)
        body = self.rest.get(request.url.path)
        if body is None:
            return httpx.Response(404, json={"detail": "not found"})
        return httpx.Response(200, json=body)

    def channels(self) -> dict:
        """routes.create_snapshot 이 부르는 clients_from_settings 의 반환 형상."""
        return {
            "mcp": McpHttpClient("https://gw.test/mcp", headers={"Authorization": "Bearer portal-pat"},
                                 client=httpx.Client(transport=httpx.MockTransport(self._mcp_handler))),
            "rest": RestGetClient("https://heax.test", "service-pat",
                                  client=httpx.Client(transport=httpx.MockTransport(self._rest_handler))),
            "portal_pat": "portal-pat",
            "service_pat": "service-pat",
        }


# ---------------------------------------------------------------- 가짜 심의 엔진(engine_client 의 자리)
class FakePanelEngine:
    """delib_opts 를 받아 결정문·turns·events 를 돌려주는 시험 엔진. LLM 도 네트워크도 부르지 않는다."""

    def __init__(self, spec_builder) -> None:
        self._spec_builder = spec_builder
        self.calls: list[dict] = []

    def health(self) -> dict:
        return {"runtime": "fake", "model": "fake-model-1", "captured": "health_snapshot"}

    def run(self, delib_opts: dict, *, owner_sub: str | None = None) -> dict:
        self.calls.append(delib_opts)
        seats = [p["key"] for p in delib_opts["personas"]]
        spec = self._spec_builder(seats)
        decision_text = (
            "[검증 대상 — 결론 아님] 두께 증가와 간극 확대가 낙하 응력·조립 공차에 미치는 영향을 좌석별로 검토했다.\n"
            "F1 · F2 · G1 을 아래 규격에 담는다.\n\n"
            "```json\n" + json.dumps(spec, ensure_ascii=False) + "\n```"
        )
        turns = [{"persona": key, "round": r, "text": f"{key} 라운드 {r} 발언"}
                 for r in (1, 2) for key in seats]
        events = [{"kind": "personas", "personas": [{"key": k} for k in seats]}]
        for key in seats:
            events.append({"kind": "status", "step": f"{key} 조회: list_interfaces"})
            events.append({"kind": "evidence", "source": f"{key} · list_interfaces", "result": "계면 2건"})
        events.extend({"kind": "turn", "persona": t["persona"]} for t in turns)
        return {"decision_text": decision_text, "turns": turns, "events": events,
                "conv_id": "conv-e2e-0001", "report_id": 4242, "call_path": "portal"}


# ---------------------------------------------------------------- risk_spec 생성기(의장 결정문 뒤 json 펜스)
_FACETS = ("intent", "constraint", "anomaly", "lineage", "vulnerability", "strength", "tradeoff", "unknown")


def _risk_spec(*, target_key: str, project_id: str, snapshot_ids: tuple[str, str], diff_id: str,
               ir_hash: str, thickness: dict, material: dict, seats):
    """실제 스냅샷·diff 의 값만 쓴 risk_spec — 주체 ckey 와 cites 는 의미 이벤트에서 그대로 가져온다."""
    domains = [planner.domain_of(k) for k in seats]

    def finding(fid, direction, domain, seat, mechanism, detail, event, claim):
        return {
            "id": fid, "direction": direction, "domain": domain,
            "mechanism": mechanism, "mechanism_detail": detail, "change_kind": event["change_kind"],
            "subject": {"ckeys": list(event["subject"]["ckeys"]), "names": []},
            "trigger_condition": "none",
            "severity": "중대" if direction == "risk" else "경미",
            "judgement": "WARNING" if direction == "risk" else "OK",
            "detectability": {"level": "sim-detectable", "tool": "report_part_risk"},
            "evidence_grade": "도구예측", "precedent": "none",
            "cites": [{"ref": event["cid"], "quote": event["text"]}],
            "tool_calls": [], "claim": claim,
            "warrant": "diff 의미 이벤트가 같은 방향의 수치 변화를 낸다.",
            "resolving_check": {"kind": "sim", "ref": "낙하 해석 재실행"},
            "owner_domain": domain, "raised_by": [seat], "contested_by": [], "contest_note": "",
            "status": "open",
        }

    return {
        "schema": "risk_spec", "version": "1.0", "taxonomy_version": "1.0",
        "scope": {"kind": "diff", "target_key": target_key, "project_refs": [project_id],
                  "ir_refs": list(snapshot_ids), "diff_ref": diff_id, "ir_hash": ir_hash},
        "findings": [
            finding("F1", "risk", "mech", seats[0], "mechanical", "drop_stress", thickness,
                    "PLATE_2 두께가 1.0→1.4 mm 로 늘어 적층 높이 여유가 줄어든다."),
            finding("F2", "risk", "mech", seats[0], "interface", "interference", material,
                    "BRACKET_L 재질 교체로 접합부 강성 가정이 바뀐다."),
        ],
        "gains": [
            finding("G1", "improvement", "mech", seats[0], "mechanical", "drop_stress", thickness,
                    "두께 증가로 굽힘 강성이 올라간다."),
        ],
        "cross_domain": [], "open_items": [],
        "character": {"one_liner": "두께·재질 변경 1건씩의 개정 스냅샷.",
                      "facets": [{"facet": f, "statements": [], "na_reason": "좌석 미기재"} for f in _FACETS]},
        "coverage": {"seats": [{"key": k, "domain": planner.domain_of(k), "origin": "primary"} for k in seats],
                     "domains_seated": sorted(set(domains)), "domains_missing": []},
        "verdict": "undetermined", "verdict_conditions": [],
        "evidence_profile": {"tool": 3, "card": 0, "precedent": {"verified": 0, "dismissed": 0},
                             "heuristic": 0, "measured": 0},
    }


# ================================================================ 본 흐름
def test_e2e_full_flow(wired, ident, monkeypatch, tmp_path):
    """계획 §9 의 한 바퀴 — 어느 단계도 외부를 부르지 않고 원장이 이어진다."""
    store = wired

    # ── 1. 과제 생성(POST /api/projects).
    project = routes.create_project(
        routes.ProjectBody(code=PROJECT_CODE, name="E2E 스모크 과제", stage="DV1",
                           classification="internal"), ident=ident)
    project_id = project["id"]
    assert store.query_one("SELECT code FROM rr_projects WHERE id = ?", (project_id,))["code"] == PROJECT_CODE

    # ── 2. 소스 연결(POST /api/projects/{id}/sources) — 어댑터가 planned 라 probe 는 unreachable 이 정상이다.
    #     ref 는 정찰 실측 계약 그대로다(mcad=stepforge_project_id·detect_job_id, dyna=session_id·file_id·sha256).
    source_refs = {
        "mcad": {"stepforge_project_id": recon.SF_PROJECT, "detect_job_id": "01JDET"},
        "dyna": {"session_id": "01JSES", "file_id": "01JFIL", "sha256": recon.KSHA},
        "dyna_result": {"report_ids": ["r1"]},
    }
    for kind, app_key in (("mcad", recon.APP_KEY), ("dyna", recon.DYNA_APP_KEY),
                          ("dyna_result", recon.DYNA_APP_KEY)):
        added = routes.add_source(project_id, routes.SourceBody(kind=kind, app_key=app_key, ref=source_refs[kind]),
                                  ident=ident)
        assert added["ok"] is True
        assert added["probe"]["status"] in ("linked", "unreachable")
    assert len(routes._project_sources(project_id)) == 3
    # 연결 시점의 probe 를 적어 둔다 — 아래 3단계가 이 값을 **갱신**하는지가 요지다(측정값에 나이가 생기면 안 된다).
    probe_before = {s["kind"]: s["status"] for s in routes._project_sources(project_id)}

    # ── 3. 스냅샷(POST /api/projects/{id}/snapshots). 라우트가 실 어댑터를 부른다 — 더는 501 이 아니다.
    apps = FakeSourceApps()
    monkeypatch.setattr(adapters_registry, "clients_from_settings", lambda *a, **k: apps.channels())
    first = routes.create_snapshot(project_id, routes.SnapshotBody(label="DV1"), ident=ident)
    assert set(first) >= {"snapshot_id", "ir_hash", "reused", "partial", "blocked", "gates_summary", "degraded"}
    assert first["reused"] is False and len(first["ir_hash"]) == 64
    # 실제로 소스 앱을 찔렀다 — REST 5경로 + MCP 도구 호출. /interfaces 는 StepForge REST 에 실재하고
    # (app/rest.py `/projects/{project_id}/interfaces`) MCP 판에 없는 행 id·truncation 을 준다.
    assert apps.rest_seen == [recon.BASE, f"{recon.BASE}/tree", f"{recon.BASE}/artifacts/graph/",
                              f"{recon.BASE}/parts", f"{recon.BASE}/interfaces"]
    # REST 가 살아 있으면 계면은 REST 1회로 받고 MCP list_interfaces 4회는 부르지 않는다(정찰 §4 1항의 예산).
    seen_mcp = {name for name, _ in apps.mcp_seen}
    assert seen_mcp >= {"job_status", "interface_graph", "inspect_file", "report_summary"}
    assert "list_interfaces" not in seen_mcp
    # 방금 200 으로 읽은 소스를 카드가 계속 'unreachable' 이라 적지 않는다 — 캡처 성공이 도달 측정이다.
    # (어댑터 발견 배선이 **연결 시점**의 같은 거짓말을 고쳤고, 이쪽은 시간이 지나면 되살아나던 쪽이다.)
    probe_after = {s["kind"]: s["status"] for s in routes._project_sources(project_id)}
    assert all(status == "linked" for status in probe_after.values()), (probe_before, probe_after)
    detail = next(s["probe"]["detail"] for s in routes._project_sources(project_id) if s["kind"] == "mcad")
    assert detail.startswith("capture_ok calls=")
    ir_first = ir_builder.load_ir(store, first["snapshot_id"])
    assert {n["domain"] for n in ir_first["nodes"]} == {"mcad", "dyna"}
    assert store.query_one("SELECT node_count FROM rr_snapshots WHERE id = ?",
                           (first["snapshot_id"],))["node_count"] == len(ir_first["nodes"])
    # 결과층 오버레이는 nid 로 붙는다 — pid 1(Stack\PLATE_1) 위에 낙하 결과가 얹혔다.
    overlaid = [n for n in ir_first["nodes"] if (n["attrs"].get("results") or {}).get("worst_stress")]
    assert [n["local_key"] for n in overlaid] == ["1"]
    # 캡처 호출은 전부 원장에 남고 인용 주소(tool:<call_id>)가 실재한다.
    calls = ir_builder.load_calls(store, first["snapshot_id"], include_response=False)
    assert f"GET /apps/step_forge/api/projects/{recon.SF_PROJECT}/tree" in {c["tool"] for c in calls}
    # `GET /api/refs/tool:<call_id>` 는 메타가 아니라 보관한 gzip 원문을 돌려준다(plan §2.11.2·§0.9 P1-8).
    with_response = ir_builder.load_calls(store, first["snapshot_id"])
    sample = next(c for c in with_response if "response" in c)
    resolved = routes.get_ref(f"tool:{sample['call_id']}", ident=ident)
    assert resolved["ref_type"] == "tool" and resolved["resolved"] is True
    payload = resolved["payload"]
    assert payload["response_available"] is True and payload["response_truncated"] is False
    assert payload["response"] == sample["response"]
    assert sha256_hex(payload["response_text"]) == payload["response_sha256"]

    # ── 4. state 게이트 — 동결이 rr_states 를 함께 쓴다(G1~G6 판정 + 요약문).
    state = state_module.load_state(store, first["snapshot_id"])
    assert set(state["gates"]) == {"G1", "G2", "G3", "G4", "G5", "G6"}
    assert first["gates_summary"] == {k: v["pass"] for k, v in state["gates"].items()}
    # 소스가 단위(mm)를 주고 계면이 confirmed 라 차단은 없다.
    assert state["gates"]["G6"]["pass"] is True
    assert state["blocked"] is False and state["summary_text"].startswith("[대상]")
    assert store.query_one("SELECT blocked FROM rr_states WHERE snapshot_id = ?",
                           (first["snapshot_id"],))["blocked"] == 0

    # ── 5. 두 번째 스냅샷 — 같은 소스 앱이 개정판을 돌려준다(두께 1.0→1.4 · 재질 교체 · 간극 0.00→0.35).
    apps.revise()
    second = routes.create_snapshot(project_id, routes.SnapshotBody(label="DV2"), ident=ident)
    assert second["reused"] is False
    assert second["ir_hash"] != first["ir_hash"]
    # 결정론 — 소스 응답이 그대로면 같은 ir_hash 가 나와 앞 스냅샷을 재사용한다(§2.5).
    repeat = routes.create_snapshot(project_id, routes.SnapshotBody(label="DV2 재캡처"), ident=ident)
    assert repeat["ir_hash"] == second["ir_hash"] and repeat["reused"] is True
    assert repeat["snapshot_id"] == second["snapshot_id"]

    # ── 6. same-as — 두 스냅샷의 노드가 전부 대응한다(GET /api/sameas).
    review = routes.get_sameas(base=first["snapshot_id"], target=second["snapshot_id"], ident=ident)
    assert review["pending_n"] == 0 and review["G2"]["pass"] is True
    ir_base = ir_builder.load_ir(store, first["snapshot_id"])
    ir_target = ir_builder.load_ir(store, second["snapshot_id"])
    links = sameas.resolve(ir_base["nodes"], ir_target["nodes"], ir_base["edges"], ir_target["edges"], "pair", {})
    # 불변식은 '기저 노드가 하나도 안 빠지고 대응된다' 이지 특정 개수가 아니다. 개수는 구성으로 고정한다 —
    # mcad 3(어셈블리 + 기하 있는 파트 2. BRACKET_L 은 parts 응답에 없어 missing_geometry 로 빠진다) + dyna 3.
    assert len(links) == len(ir_base["nodes"])
    by_domain = collections.Counter(n["domain"] for n in ir_base["nodes"])
    assert by_domain == {"mcad": 3, "dyna": 3}
    assert {link["status"] for link in links} == {"auto"}

    # ── 7. diff(POST /api/diffs) — 3층 + 의미 이벤트.
    created = routes.create_diff(
        routes.DiffBody(base_snapshot_id=first["snapshot_id"], target_snapshot_id=second["snapshot_id"]), ident=ident)
    diff_id = created["diff_id"]
    diff_obj = diff_module.get_diff(store, diff_id, owner_sub=OWNER, part="diff")
    assert diff_obj["pair_kind"] == "same_project_revision"
    assert diff_obj["comparability"]["G7"]["pass"] is True
    events = diff_obj["semantic"]["events"]
    assert events, "설계 변경 3건이 의미 이벤트를 내야 한다."
    codes = {e["code"] for e in events}
    assert "part.material_changed" in codes
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_diff_events WHERE diff_id = ?",
                           (diff_id,))["n"] == len(events)

    # ── 8. summary_text — 등록부·브리프가 읽는 정본 요약(GET /api/diffs/{id}?part=summary).
    summary = routes.diff_part(diff_id, "summary", owner_sub=OWNER)
    assert summary["summary_text"].startswith("[대상]")
    assert "[의미]" in summary["summary_text"]
    assert summary["summary_text"] == diff_obj["summary_text"]

    # ── 9. 타깃(POST /api/targets) — 로스터 동결까지.
    agents = [{"key": f"{domain}-agent-{i}", "domain": domain, "relevance": 0.9 - 0.1 * i}
              for domain in ROSTER_DOMAINS for i in range(2)]
    target = routes.create_target(
        routes.TargetBody(kind="diff", ref_id=diff_id, consent=True, agents=agents), ident=ident)
    target_key = target["target_key"]
    assert target_key == f"diff:{diff_id}"
    assert target["roster_size"] == len(agents) and target["roster_source"] == "body.agents"
    assert [t["tier"] for t in target["tier_plan"]] == ["A", "B", "C"]
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_coverage WHERE target_key = ?",
                           (target_key,))["n"] == len(agents)

    # ── 10. 편성 + 브리프 조립(GET /api/targets/{key}/brief) — planned 패널이 없으면 그 자리에서 1건 편성한다.
    payload = routes.brief_payload(target_key, "B", owner_sub=OWNER)
    assert payload["keys"] == ["E0", "E0c", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9"]
    assert payload["budget"]["dropped"] == 0
    assert len(payload["panels"]) == 1
    panel_id = payload["panels"][0]["panel_id"]
    delib_opts = payload["panels"][0]["delib_opts"]
    seats = [p["key"] for p in delib_opts["personas"]]
    # Tier B 는 도메인별 rank 1 만 앉힌다.
    assert sorted(seats) == sorted(f"{d}-agent-0" for d in ROSTER_DOMAINS)
    assert delib_opts["chair_template"] == planner.CHAIR_TEMPLATE
    assert delib_opts["question"].startswith(f"[리스크심사 {PROJECT_CODE} {target_key}]")
    assert "mcad " in delib_opts["question"] and "dyna " in delib_opts["question"]
    # E0c(좌석 계약)는 브리프에서 빼고 build_delib_opts 가 다시 끼운다 — 항목 수는 같다.
    assert [e["source"] for e in delib_opts["evidence"]][1] == "seat_contract"
    assert len(delib_opts["evidence"]) == len(payload["evidence"])

    panel = routes._planned_panel(store.query_one(
        "SELECT id, target_key, owner_sub, panel_no, tier, seats_json, modifiers_json, rounds, budget_json, status"
        " FROM rr_panels WHERE id = ?", (panel_id,)))
    assert panel["status"] == "planned"

    # ── 10b. brief_token — REST 발급본으로만 MCP risk_get_brief 가 열린다(plan §8.2.5).
    from app import mcp_server

    assert "brief_token" not in payload["panels"][0]           # MCP 반환에는 토큰을 싣지 않는다
    issued = routes.brief_payload(target_key, "B", owner_sub=OWNER, issue_token=True)
    token = issued["panels"][0]["brief_token"]
    assert token and store.query_one(
        "SELECT brief_token_hash FROM rr_panels WHERE id = ?", (panel_id,))["brief_token_hash"] == \
        routes.brief_token_hash(token)
    assert mcp_server.risk_get_brief(target_key, token)["panels"][0]["panel_id"] == panel_id
    assert mcp_server.risk_get_brief(target_key, token + "x")["error"] == "brief_token_invalid"
    assert mcp_server.risk_get_brief(target_key, "")["error"] == "brief_token_invalid"
    # 과제가 mcp_visibility='private'(기본값)이라 읽기 4종은 존재를 숨긴다(§5.1 원칙 9).
    assert mcp_server.risk_get_snapshot(first["snapshot_id"], "ir")["error"] == "not_visible"
    assert mcp_server.risk_get_registry(target_key)["error"] == "not_visible"
    store.execute("UPDATE rr_projects SET mcp_visibility = 'org' WHERE id = ?", (project_id,))
    assert mcp_server.risk_get_snapshot(first["snapshot_id"], "ir")["ir_hash"]
    assert mcp_server.risk_get_registry(target_key)["target_key"] == target_key
    store.execute("UPDATE rr_projects SET mcp_visibility = 'private' WHERE id = ?", (project_id,))

    # ── 11. 패널 실행 — 좌석 running 전환 후 FakePanelEngine 이 결정문을 돌려준다.
    assert planner.start_panel_seats(store, panel_id) == len(seats)
    assert store.query_one("SELECT status FROM rr_panels WHERE id = ?", (panel_id,))["status"] == "running"

    # 좌석이 인용할 주소는 diff 가 실제로 낸 의미 이벤트에서 가져온다(지어낸 ref 없음).
    by_code = {e["code"]: e for e in events}
    thickness, material = by_code["part.thickness_changed"], by_code["part.material_changed"]
    assert thickness["change_kind"] == "dimension" and material["change_kind"] == "material"

    engine = FakePanelEngine(lambda seat_keys: _risk_spec(
        target_key=target_key, project_id=project_id,
        snapshot_ids=(first["snapshot_id"], second["snapshot_id"]), diff_id=diff_id,
        ir_hash=second["ir_hash"], thickness=thickness, material=material, seats=seat_keys))
    result = engine.run(delib_opts)
    assert len(engine.calls) == 1 and engine.calls[0] is delib_opts

    # ── 12. risk_spec 파싱 — 결정문 뒤 json 펜스를 앱 단일 파서가 읽는다.
    parsed_spec = narrative.parse_risk_spec(result["decision_text"])
    assert parsed_spec is not None and parsed_spec["schema"] == "risk_spec"
    assert narrative.validate_risk_spec(parsed_spec) == []

    # ── 13. 원자 + 등록부 병합 + 완결 판정(POST /api/panels/{id}/complete).
    #     대역 없이 실제 narrative.persist_panel_result 를 태운다 — 배선이 켜졌다는 증거다(§6.7.2 8단계).
    assert callable(getattr(narrative, "persist_panel_result", None))
    completed = routes.complete_panel(
        panel_id, engine="web", decision_text=result["decision_text"], turns=result["turns"],
        report_id=result["report_id"], conv_id=result["conv_id"], events=result["events"],
        model="fake-model-1", actor=OWNER, actor_verified=True, owner_sub=OWNER)

    assert completed["parsed"] is True
    assert completed["coverage_updated"] is True and "persisted" not in completed
    assert completed["attribution_rate"] == 1.0
    assert completed["engine"] == "web" and completed["tool_mode"] == "tools"

    # 원자 — findings 2 + gains 1 이 전부 해석돼 rr_findings 에 앉는다.
    atom_rows = store.query(
        "SELECT finding_id, direction, subject_key, cluster_key, finding_json FROM rr_findings WHERE panel_id = ?"
        " ORDER BY finding_id", (panel_id,))
    assert len(atom_rows) == 3
    atoms = [json.loads(r["finding_json"]) for r in atom_rows]
    assert all(a["subject_key"] and not a["subject_unresolved"] for a in atoms)
    assert all(not a.get("dangling") for a in atoms), "cites 는 실제 diff cid 라 dangling 이 없어야 한다."
    assert {r["subject_key"] for r in atom_rows} == {thickness["subject_key"], material["subject_key"]}
    # 좌석 의견 행도 같은 경로에서 앉는다(발언이 있는 좌석만).
    opinion_seats = {r["agent_key"] for r in store.query(
        "SELECT agent_key FROM rr_seat_opinions WHERE panel_id = ? ORDER BY agent_key", (panel_id,))}
    assert set(seats) <= opinion_seats

    # 등록부 — improvement 는 risk 와 다른 행으로 묶인다(.imp 접미).
    assert completed["findings_n"] == 3
    rows = registry.registry_rows(store, target_key)
    assert len(rows) == completed["clusters"] == 3
    assert any(r["cluster_key"].endswith(registry.IMPROVEMENT_SUFFIX) for r in rows)
    assert {r["direction"] for r in rows} == {"risk", "improvement"}
    assert all(r["status"] == "open" for r in rows)

    # 병합은 멱등이다 — 같은 원장을 다시 병합해도 행 수·내용이 같다.
    again = registry.merge(store, target_key)
    assert again["clusters"] == 3
    assert [dict(r) for r in registry.registry_rows(store, target_key)] == [dict(r) for r in rows]

    # 완결 판정 — 15 도메인 중 5 도메인만 앉혀 C0 이 정답이다(레벨은 단조 증가).
    level = registry.close_level(store, target_key)
    assert completed["level"] == level["level"] == "C0"
    assert level["c1"] is False and level["roster_size"] == len(agents)
    assert level["status_counts"]["done"] == len(seats)
    assert all(level["detail"]["domains_terminal"][d] == 1 for d in ROSTER_DOMAINS)
    assert level["detail"]["strong_ratio"] == 1.0 and level["detail"]["spec_parse_failed"] == 0

    # 좌석 회계 — 착석 5석이 done 으로 닫히고 나머지는 pending 이다.
    coverage = planner.coverage_summary(store, target_key)
    assert coverage["by_status"]["done"] == len(seats)
    assert coverage["by_status"]["pending"] == len(agents) - len(seats)
    assert planner.check_invariants(store, target_key) == []

    # ── 14. 브리프 재조립 — 패널 결과(E5 등록부·E7 좌석 기억)가 실린 상태로 다시 조립된다.
    after = brief_module.build_brief(store, target_key, seats=panel["seats"], panel_id=panel_id, owner_sub=OWNER)
    assert after["meta"]["dropped"] == 0 and after["meta"]["budget_used"] <= after["meta"]["budget"]
    assert after["keys"] == payload["keys"]
    e0 = next(i for i, k in zip(after["evidence"], after["keys"]) if k == "E0")
    # 첫 줄은 프레이밍이고 그다음이 헤더다 — 모델 출처(D6)가 헤더에 붙는다.
    assert f"target_key={target_key}" in e0["result"].splitlines()[1]
    assert "model=fake-model-1" in e0["result"].splitlines()[1]
    e1 = next(i for i, k in zip(after["evidence"], after["keys"]) if k == "E1")
    assert e1["source"] == "rr_diff" and "[의미]" in e1["result"]
    # E5 는 '선행' 등록부(계보·유사 과제)라 이번 패널이 만든 행은 담지 않는다 — 첫 심사라 0건이 정답이다.
    e5 = next(i for i, k in zip(after["evidence"], after["keys"]) if k == "E5")
    assert "선행 등록부 없음" in e5["result"]
    # 조립은 결정론이다 — 같은 원장에서 두 번 조립하면 같은 항목이 나온다.
    assert brief_module.build_brief(store, target_key, seats=panel["seats"], panel_id=panel_id,
                                    owner_sub=OWNER)["evidence"] == after["evidence"]

    # 패널 행 최종 상태.
    final = store.query_one(
        "SELECT status, engine, tool_mode, risk_spec_parsed, conv_id, report_id, model_json, quality_json"
        " FROM rr_panels WHERE id = ?", (panel_id,))
    assert final["status"] == "done" and final["risk_spec_parsed"] == 1
    assert final["conv_id"] == "conv-e2e-0001" and final["report_id"] == 4242
    assert json.loads(final["model_json"])["model"] == "fake-model-1"
    assert json.loads(final["quality_json"])["actor_verified"] is True

    # ── 15. 이동(GET /api/export → POST /api/import) — 한 바퀴가 만든 원장이 빈 상자로 그대로 건너간다.
    body = "".join(export.iter_lines(store, OWNER, 0, data_dir=tmp_path))
    head = json.loads(body.splitlines()[0])
    assert head["schema_version"] == store.schema_version()
    tables = {json.loads(line)["table"] for line in body.splitlines()[1:]}
    assert {"rr_projects", "rr_sources", "rr_snapshots", "rr_snapshot_calls", "rr_diffs", "rr_targets",
            "rr_panels", "rr_findings", "rr_registry"} <= tables

    other = RiskStore(tmp_path / "moved" / "risk_review.db")
    other.open()
    other.migrate()
    try:
        moved = export.import_jsonl(other, OWNER, body)
        assert moved["conflicts"] == [] and moved["inserted"] == len(body.splitlines()) - 1
        # 왕복은 행 수·해시가 같아야 한다(BLOB 캡처 응답 포함).
        assert export.row_digest(other, OWNER) == export.row_digest(store, OWNER)
        assert bytes(other.query_one("SELECT response_gz FROM rr_snapshot_calls WHERE call_id = ?",
                                     (calls[0]["call_id"],))["response_gz"]) == \
               bytes(store.query_one("SELECT response_gz FROM rr_snapshot_calls WHERE call_id = ?",
                                     (calls[0]["call_id"],))["response_gz"])
        # 두 번째 들여오기는 멱등이다.
        again_moved = export.import_jsonl(other, OWNER, body)
        assert again_moved["inserted"] == 0 and again_moved["conflicts"] == []
    finally:
        other.close()


# ================================================================ 스냅샷 라우트의 어댑터 계약
def test_snapshot_route_calls_the_adapter_instead_of_501(wired, ident, monkeypatch):  # noqa: ARG001
    """소스 카드 ref 가 비면 어댑터가 그 자리에서 422 를 낸다 — 라우트는 더는 not_implemented 가 아니다."""
    project = routes.create_project(routes.ProjectBody(code="M22REF", name="ref 누락 과제", stage="DV1",
                                                       classification="internal"),
                                    ident=ident)
    routes.add_source(project["id"], routes.SourceBody(kind="mcad", app_key=recon.APP_KEY, ref={}), ident=ident)
    apps = FakeSourceApps()
    monkeypatch.setattr(adapters_registry, "clients_from_settings", lambda *a, **k: apps.channels())

    with pytest.raises(AppError) as err:
        routes.create_snapshot(project["id"], routes.SnapshotBody(label="빈 ref"), ident=ident)
    assert err.value.http_status == 422 and err.value.code != "not_implemented"
    assert "stepforge_project_id" in err.value.message
    assert apps.rest_seen == [] and apps.mcp_seen == []


# ================================================================ 결정론(통과 기준 (4))
def test_ir_hash_is_stable_for_the_same_input(risk_store):
    """같은 어댑터 결과면 라벨·captured_at 이 달라도 ir_hash 가 같다(§2.5 결정론)."""
    mcad = _fixture("adapter_mcad_basic.json")
    dyna = _fixture("adapter_dyna_basic.json")
    common_kwargs = dict(project_id="P-DET", owner_sub=OWNER, iface_ledger=[], sameas_ledger={},
                         dim_defs=[], dim_vocab={})
    first = ir_builder.build_ir(adapter_results=[copy.deepcopy(mcad), copy.deepcopy(dyna)],
                               label="DV1", captured_at=1756600000, **common_kwargs)
    second = ir_builder.build_ir(adapter_results=[copy.deepcopy(mcad), copy.deepcopy(dyna)],
                                 label="추출 2회차", captured_at=1799999999, **common_kwargs)
    assert first["ir_hash"] == second["ir_hash"]
    assert first["snapshot_id"] != second["snapshot_id"] or first["captured_at"] != second["captured_at"]


def test_seats_json_is_stable_for_the_same_roster(tmp_path):
    """같은 로스터·같은 Settings 면 두 번 편성해도 seats_json 이 같다(§6.6.2 결정론)."""
    from app.risk_store import RiskStore

    agents = [{"key": f"{domain}-agent-{i}", "domain": domain, "relevance": 0.9 - 0.1 * i}
              for domain in ROSTER_DOMAINS for i in range(3)]
    seats_json = []
    for run in ("a", "b"):
        store = RiskStore(tmp_path / f"{run}.db")
        store.open()
        store.migrate()
        try:
            store.execute(
                "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, level,"
                " close_level, external_sync_json, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,'C0','C2','{}',?,?)",
                ("diff:" + "0" * 32, OWNER, "diff", "0" * 32, "P-DET", "a" * 12, 1, 1))
            planner.freeze_roster(store, "diff:" + "0" * 32, OWNER, agents)
            panel = planner.plan_next_panel(store, "diff:" + "0" * 32, "B")
            seats_json.append(panel["seats_json"])
        finally:
            store.close()
    assert seats_json[0] == seats_json[1]
    assert json.loads(seats_json[0]) == sorted(json.loads(seats_json[0]), key=lambda s: (s["domain"], s["key"]))


def test_the_three_new_first_class_refs_resolve_over_rest(wired, ident, monkeypatch):
    """정본 P5 통과 기준 (14) — E10 줄의 `voc:`·`paper:` 가 `GET /api/refs/{ref}` 로 **200 해석**된다.

    `req:` 도 같다(좌석 std 계약의 필수 인용 원천). 분기가 없으면 인용 해석은 통과하는데 REST 는 404 라
    화면·보고서에서 dangling 으로 보인다 — 인용과 REST 가 같은 규칙을 쓰는지까지 여기서 고정한다.
    """
    from app import brief as brief_module
    from app import field_source

    store = wired
    monkeypatch.setattr(routes, "get_store", lambda: store)
    project_id = routes.create_project(
        routes.ProjectBody(code="M22REF", name="참조 해석", stage="DV1", classification="internal",
                           product_code="F7-2024"), ident=ident)["id"]
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash,"
        " external_sync_json, created_at, updated_at)"
        " VALUES ('snap:SR','" + OWNER + "','snap','SR',?,'h1','{}',1,1)", (project_id,))
    store.execute(
        "INSERT INTO rr_requirements(id, project_id, owner_sub, kind, name, op, value_json, unit, status,"
        " created_at, updated_at) VALUES ('R1',?,?,'dim_limit','thickness','gte','0.3','mm','confirmed',1,1)",
        (project_id, OWNER))

    class _Stub:
        def call(self, name, args):
            if name == "get_top_issues":
                return {"ok": True, "result": {"issues": [
                    {"issue_key": "ISS-1", "category": "파손", "n": 4, "text": "힌지"}]}}
            return {"ok": True, "result": {"papers": [
                {"doi": "10.1000/xyz", "title": "drop", "abstract": "stress"}]}}

    store.execute("INSERT INTO rr_character(id, project_id, owner_sub, facet, tag, tags_json, statement,"
                  " polarity, by_json, support_panels, support_targets, recall_eligible, needs_review,"
                  " status, created_at, updated_at)"
                  " VALUES ('C1',?,?,'intent','char:structure:thin_stack','[]','s','observation','[]',"
                  "2,1,1,0,'panel',1,1)", (project_id, OWNER))
    ctx = brief_module._target_context(store, "snap:SR")
    lines = brief_module._field_evidence_lines(store, ctx, field_source.FieldSource(_Stub()))
    assert any(ln.startswith("voc:F7-2024#ISS-1") for ln in lines), lines

    for ref, kind in (("voc:F7-2024#ISS-1", "voc"), ("paper:10.1000/xyz", "paper"),
                      ("req:thickness", "req")):
        out = routes.get_ref(ref, ident=ident)
        assert (out["ref_type"], out["resolved"]) == (kind, True), ref
        assert out["payload"], ref

    # 지어낸 인용은 REST 도 404 다 — 해석과 REST 가 같은 규칙을 쓴다는 뜻이다.
    for bad in ("voc:F7-2024#ISS-9", "paper:10.1000/nope", "req:nope"):
        with pytest.raises(AppError) as exc:
            routes.get_ref(bad, ident=ident)
        assert exc.value.http_status == 404, bad


def test_reusing_a_snapshot_does_not_restamp_it_with_the_new_job(wired, ident, monkeypatch):
    """같은 모델을 두 번 캡처하면 두 번째는 재사용이다 — 그때 남의 스냅샷에 이번 잡을 덮어쓰지 않는다.

    스냅샷은 불변이고(§2.1) `job_id`·`capture_partial` 은 **자기를 만든 잡**을 가리킨다. 여러 잡이 한
    스냅샷을 재사용하므로 그 방향은 `rr_snapshot_jobs.snapshot_id` 가 맡는다.
    """
    store = wired
    project_id = routes.create_project(
        routes.ProjectBody(code="M22REUSE", name="재사용", stage="DV1", classification="internal"),
        ident=ident)["id"]
    routes.add_source(project_id, routes.SourceBody(
        kind="mcad", app_key=recon.APP_KEY,
        ref={"stepforge_project_id": recon.SF_PROJECT, "detect_job_id": "01JDET"}), ident=ident)
    apps = FakeSourceApps()
    monkeypatch.setattr(adapters_registry, "clients_from_settings", lambda *a, **k: apps.channels())

    first = routes.create_snapshot(project_id, routes.SnapshotBody(label="DV1"), ident=ident)
    second = routes.create_snapshot(project_id, routes.SnapshotBody(label="다시"), ident=ident)
    assert second["reused"] is True and second["snapshot_id"] == first["snapshot_id"]
    assert second["job_id"] != first["job_id"]
    row = store.query_one("SELECT job_id FROM rr_snapshots WHERE id = ?", (first["snapshot_id"],))
    assert row["job_id"] == first["job_id"]
    # 두 번째 잡도 자기가 어느 스냅샷을 재사용했는지는 남긴다 — 연결이 사라지는 게 아니다.
    assert store.query_one("SELECT snapshot_id FROM rr_snapshot_jobs WHERE id = ?",
                           (second["job_id"],))["snapshot_id"] == first["snapshot_id"]


# ---------------------------------------------------------------- 스냅샷 잡 상태기계(plan §2.11.3 · §0.9 P1-22)
def test_snapshot_job_records_its_state_and_guards_the_model_size(wired, ident, monkeypatch):
    """정상 캡처는 done 1행, 상한 초과는 409 + failed 1행(호출 원문은 snapshot_id NULL 로 남는다)."""
    store = wired
    project = routes.create_project(
        routes.ProjectBody(code="M22JOB", name="잡 상태기계", stage="DV1", classification="internal"),
        ident=ident)
    project_id = project["id"]
    for kind, app_key, ref in (("mcad", recon.APP_KEY,
                                {"stepforge_project_id": recon.SF_PROJECT, "detect_job_id": "01JDET"}),):
        routes.add_source(project_id, routes.SourceBody(kind=kind, app_key=app_key, ref=ref), ident=ident)

    apps = FakeSourceApps()
    monkeypatch.setattr(adapters_registry, "clients_from_settings", lambda *a, **k: apps.channels())
    out = routes.create_snapshot(project_id, routes.SnapshotBody(label="DV1"), ident=ident)
    job = store.query_one(
        "SELECT id, state, snapshot_id, calls_n, calls_failed_n, budget_s, started_at, finished_at"
        " FROM rr_snapshot_jobs WHERE id = ?", (out["job_id"],))
    assert job["state"] == out["job_state"] == "done"
    assert job["snapshot_id"] == out["snapshot_id"] and job["calls_n"] > 0
    assert job["started_at"] and job["finished_at"]
    assert store.query_one("SELECT job_id FROM rr_snapshots WHERE id = ?",
                           (out["snapshot_id"],))["job_id"] == out["job_id"]

    # 상한 초과 — 409 model_too_large 이고 그 잡은 failed 로 남으며 호출 원문은 스냅샷 없이 보존된다.
    small = dataclasses.replace(config.settings, risk_max_leaf=1, risk_max_interfaces=1)
    monkeypatch.setattr(config, "settings", small)
    apps.revise()
    with pytest.raises(AppError) as exc:
        routes.create_snapshot(project_id, routes.SnapshotBody(label="DV2"), ident=ident)
    assert (exc.value.code, exc.value.http_status) == ("model_too_large", 409)
    # 시간 예산은 집행하지 않으므로 문구에 적지 않는다 — '예산 600 s' 는 600초에 끊긴다고 읽혔다.
    assert "allow_large=true" in exc.value.message and "예산" not in exc.value.message
    assert exc.value.detail["budget_s"] == routes.LARGE_BUDGET_S
    failed = store.query_one(
        "SELECT id, state, snapshot_id, error_json FROM rr_snapshot_jobs WHERE state = 'failed'")
    assert failed is not None and failed["snapshot_id"] is None
    assert json.loads(failed["error_json"])["stage"] == "model_size"
    orphan_calls = store.query(
        "SELECT call_id, snapshot_id FROM rr_snapshot_calls WHERE job_id = ?", (failed["id"],))
    assert orphan_calls and all(c["snapshot_id"] is None for c in orphan_calls)

    # allow_large 재요청은 예산 600 s 로 통과한다.
    allowed = routes.create_snapshot(
        project_id, routes.SnapshotBody(label="DV2", allow_large=True), ident=ident)
    assert allowed["job_state"] in ("done", "partial")
    assert store.query_one("SELECT budget_s FROM rr_snapshot_jobs WHERE id = ?",
                           (allowed["job_id"],))["budget_s"] == routes.LARGE_BUDGET_S

    # 재기동 마감 — running 인 채 남은 행은 failed(error_json.stage='restart')다.
    store.execute("UPDATE rr_snapshot_jobs SET state = 'running' WHERE id = ?", (allowed["job_id"],))
    assert routes.close_stale_snapshot_jobs(store) == 1
    closed = store.query_one(
        "SELECT state, error_json FROM rr_snapshot_jobs WHERE id = ?", (allowed["job_id"],))
    assert closed["state"] == "failed" and json.loads(closed["error_json"])["stage"] == "restart"
