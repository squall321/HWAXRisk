# E2E 스모크 — 가짜 어댑터·FakePanelEngine 으로 과제→소스→스냅샷→게이트→2차 스냅샷→same-as→diff→타깃→편성→패널→원자→등록부→완결→브리프를 외부 호출 0 으로 한 번 흘린다(plan §9 통과 기준)
from __future__ import annotations

import copy
import json

import httpx
import pytest

from app import brief as brief_module
from app import common, diff as diff_module, identity, ir_builder, narrative, planner, registry, routes, sameas
from app import state as state_module
from app.errors import AppError
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


class FakeAdapter:
    """IrSource 프로토콜의 시험용 구현 — 네트워크 대신 픽스처 AdapterResult 를 돌려준다."""

    version = "1.0-fake"

    def __init__(self, kind: str, result: dict) -> None:
        self.kind = kind
        self._result = result
        self.captures = 0

    def discover(self, registry_map):  # noqa: ARG002 — 프로토콜 서명만 맞춘다.
        return {"kind": self.kind, "app_key": self._result["source"].get("app_key")}

    def capture(self, ref, principal, recorder):  # noqa: ARG002
        self.captures += 1
        return copy.deepcopy(self._result)


def _revised_mcad(base: dict) -> dict:
    """2차 스냅샷용 설계 변경 — PLATE_2 두께 1.0→1.4 mm · BRACKET_L 재질 교체 · tied 간극 0.00→0.35 mm."""
    revised = copy.deepcopy(base)
    for node in revised["nodes"]:
        if node["canon_key"].endswith("PLATE_2"):
            attrs = node["attrs"]
            attrs["bbox_def"][5] = 1.4
            attrs["bbox_world"][5] = 1.4
            attrs["size_def"][2] = 1.4
            attrs["size_sorted"][2] = 1.4
            attrs["min_dim"] = 1.4
            attrs["volume"] = 3500.0
        elif node["canon_key"].endswith("BRACKET_L"):
            node["attrs"]["material"] = "AL6061"
    for edge in revised["edges"]:
        if edge["kind"] == "tied":
            edge["attrs"]["min_gap"] = 0.35
    return revised


def _freeze(store, adapters, *, label: str, project_id: str, captured_at: int) -> dict:
    """어댑터 capture 결과를 모아 IR 을 동결한다 — POST /projects/{id}/snapshots 가 501 인 동안의 우회 배선이다."""
    results = [a.capture({}, None, None) for a in adapters]
    return ir_builder.freeze_snapshot(store, project_id=project_id, owner_sub=OWNER, label=label,
                                      adapter_results=results, captured_at=captured_at)


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


# ---------------------------------------------------------------- narrative.persist_panel_result 대역
def _spec_context(store, panel, target_key: str, project_id: str, snapshot_ids, diff_id: str) -> narrative.SpecContext:
    irs = {}
    for sid in snapshot_ids:
        ir = ir_builder.load_ir(store, sid)
        irs[sid] = {
            "nodes": {n["nid"]: {**n, **(n.get("attrs") or {})} for n in ir["nodes"]},
            "edges": {e["eid"]: {**e, **(e.get("attrs") or {})} for e in ir["edges"]},
            "dims_named": ir.get("dims_named") or [],
            "rollups": ir.get("rollups") or {},
            "warnings": ir.get("warnings") or [],
        }
    row = store.query_one("SELECT diff_json FROM rr_diffs WHERE id = ?", (diff_id,))
    return narrative.SpecContext(
        panel_id=panel["id"], target_key=target_key, project_id=project_id, owner_sub=OWNER,
        kind="diff", snapshot_ids=tuple(snapshot_ids), diff_id=diff_id, store=store,
        irs=irs, diff=json.loads(row["diff_json"]),
        seats=tuple(s["key"] for s in panel["seats"]),
    )


def _make_persist(ctx: narrative.SpecContext):
    """rr_findings·좌석 회계까지 저장하는 대역. 앱의 narrative.persist_panel_result 는 아직 없다(배선 메모)."""
    captured: dict = {}

    def persist(store, panel_id, *, decision_text, spec, turns, attribution, actor=None):  # noqa: ARG001
        normalized = narrative.normalize_risk_spec(spec or {}, ctx, prose=decision_text)
        captured["normalized"] = normalized
        atoms = normalized["spec"]["findings"] + normalized["spec"]["gains"]
        now = common.now_epoch()
        for index, atom in enumerate(atoms):
            store.execute(
                "INSERT INTO rr_findings(finding_id, claim_uid, target_key, panel_id, project_id, owner_sub,"
                " visibility, direction, domain, mechanism, mechanism_detail, change_kind, subject_key, ckeys_json,"
                " severity, sev3, judgement, detectability, detect_tool, evidence_grade, precedent, cluster_key,"
                " finding_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"{panel_id}-{index}", atom["claim_uid"], ctx.target_key, panel_id, ctx.project_id, OWNER,
                    "private", atom["direction"], atom["domain"], atom["mechanism"], atom["mechanism_detail"],
                    atom["change_kind"], atom["subject_key"], common.canonical_json(atom["subject"]["ckeys"]),
                    atom["severity"], atom["sev3"], atom["judgement"], atom["detectability"]["level"],
                    atom["detectability"]["tool"], atom["evidence_grade"], atom["precedent"], atom["cluster_key"],
                    common.canonical_json(atom), now,
                ),
            )
        seats = []
        for key in ctx.seats:
            state = attribution["seats"].get(key) or {}
            seats.append({"agent_key": key, "opinion_id": f"{panel_id}:{key}",
                          "turns_n": int(state.get("turns_n") or 0),
                          "cited_refs_n": 1, "abstained": False})
        return {"seats": seats, "findings": len(atoms)}

    return persist, captured


# ================================================================ 본 흐름
def test_e2e_full_flow(wired, ident, monkeypatch):
    """계획 §9 의 한 바퀴 — 어느 단계도 외부를 부르지 않고 원장이 이어진다."""
    store = wired

    # ── 1. 과제 생성(POST /api/projects).
    project = routes.create_project(
        routes.ProjectBody(code=PROJECT_CODE, name="E2E 스모크 과제", stage="DV1"), ident=ident)
    project_id = project["id"]
    assert store.query_one("SELECT code FROM rr_projects WHERE id = ?", (project_id,))["code"] == PROJECT_CODE

    # ── 2. 소스 연결(POST /api/projects/{id}/sources) — 어댑터가 planned 라 probe 는 unreachable 이 정상이다.
    for kind, app_key in (("mcad", "heax-step_forge"), ("dyna", "heax-kooremapper_mcp")):
        added = routes.add_source(project_id, routes.SourceBody(kind=kind, app_key=app_key, ref={"f": kind}),
                                  ident=ident)
        assert added["ok"] is True
        assert added["probe"]["status"] in ("linked", "unreachable")
    assert len(routes._project_sources(project_id)) == 2

    # ── 3. 스냅샷(IR 동결). 라우트는 어댑터 capture 부재로 아직 501 이고, 동결 자체는 가짜 어댑터로 돈다.
    with pytest.raises(AppError) as not_impl:
        routes.create_snapshot(project_id, routes.SnapshotBody(label="DV1", kinds=["mcad"]), ident=ident)
    assert not_impl.value.http_status == 501

    mcad = FakeAdapter("mcad", _fixture("adapter_mcad_basic.json"))
    dyna = FakeAdapter("dyna", _fixture("adapter_dyna_basic.json"))
    first = _freeze(store, [mcad, dyna], label="DV1", project_id=project_id, captured_at=1756600000)
    assert first["reused"] is False and mcad.captures == 1 and dyna.captures == 1
    assert len(first["ir_hash"]) == 64
    assert store.query_one("SELECT node_count, edge_count FROM rr_snapshots WHERE id = ?",
                           (first["snapshot_id"],))["node_count"] == 7

    # ── 4. state 게이트 — 동결이 rr_states 를 함께 쓴다(G1~G6 판정 + 요약문).
    state = state_module.load_state(store, first["snapshot_id"])
    assert set(state["gates"]) == {"G1", "G2", "G3", "G4", "G5", "G6"}
    assert first["gates_summary"] == {k: bool(v["pass"]) for k, v in state["gates"].items()}
    # 픽스처는 계면 1건이 auto(미확정)라 G3 만 fail 이고, G6(단위)가 살아 있어 차단은 아니다.
    assert state["gates"]["G3"]["pass"] is False and state["gates"]["G6"]["pass"] is True
    assert state["blocked"] is False and state["summary_text"].startswith("[대상]")
    assert store.query_one("SELECT blocked FROM rr_states WHERE snapshot_id = ?",
                           (first["snapshot_id"],))["blocked"] == 0

    # ── 5. 두 번째 스냅샷 — 같은 과제의 개정판(두께·재질·간극 변경).
    mcad2 = FakeAdapter("mcad", _revised_mcad(_fixture("adapter_mcad_basic.json")))
    dyna2 = FakeAdapter("dyna", _fixture("adapter_dyna_basic.json"))
    second = _freeze(store, [mcad2, dyna2], label="DV2", project_id=project_id, captured_at=1756700000)
    assert second["reused"] is False
    assert second["ir_hash"] != first["ir_hash"]

    # ── 6. same-as — 두 스냅샷의 노드가 전부 대응한다(GET /api/sameas).
    review = routes.get_sameas(base=first["snapshot_id"], target=second["snapshot_id"], ident=ident)
    assert review["pending_n"] == 0 and review["G2"]["pass"] is True
    ir_base = ir_builder.load_ir(store, first["snapshot_id"])
    ir_target = ir_builder.load_ir(store, second["snapshot_id"])
    links = sameas.resolve(ir_base["nodes"], ir_target["nodes"], ir_base["edges"], ir_target["edges"], "pair", {})
    assert len(links) == len(ir_base["nodes"]) == 7
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
    assert "mcad f=mcad" in delib_opts["question"] and "dyna f=dyna" in delib_opts["question"]
    # E0c(좌석 계약)는 브리프에서 빼고 build_delib_opts 가 다시 끼운다 — 항목 수는 같다.
    assert [e["source"] for e in delib_opts["evidence"]][1] == "seat_contract"
    assert len(delib_opts["evidence"]) == len(payload["evidence"])

    panel = routes._planned_panel(store.query_one(
        "SELECT id, target_key, owner_sub, panel_no, tier, seats_json, modifiers_json, rounds, budget_json, status"
        " FROM rr_panels WHERE id = ?", (panel_id,)))
    assert panel["status"] == "planned"

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
    ctx = _spec_context(store, panel, target_key, project_id,
                        (first["snapshot_id"], second["snapshot_id"]), diff_id)
    persist, captured = _make_persist(ctx)
    monkeypatch.setattr(narrative, "persist_panel_result", persist, raising=False)

    completed = routes.complete_panel(
        panel_id, engine="web", decision_text=result["decision_text"], turns=result["turns"],
        report_id=result["report_id"], conv_id=result["conv_id"], events=result["events"],
        model="fake-model-1", actor=OWNER, actor_verified=True, owner_sub=OWNER)

    assert completed["parsed"] is True
    assert completed["coverage_updated"] is True and "persisted" not in completed
    assert completed["attribution_rate"] == 1.0
    assert completed["engine"] == "web" and completed["tool_mode"] == "tools"

    # 원자 — findings 2 + gains 1 이 전부 해석돼 rr_findings 에 앉는다.
    normalized = captured["normalized"]
    assert normalized["ok"] is True and "spec_parse_failed" not in normalized["quality"]["flag"]
    atoms = normalized["spec"]["findings"] + normalized["spec"]["gains"]
    assert len(atoms) == 3
    assert all(a["subject_key"] and not a["subject_unresolved"] for a in atoms)
    assert all(not a["dangling"] for a in atoms), "cites 는 실제 diff cid 라 dangling 이 없어야 한다."
    assert {a["subject_key"] for a in atoms} == {thickness["subject_key"], material["subject_key"]}
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_findings WHERE panel_id = ?", (panel_id,))["n"] == 3

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
