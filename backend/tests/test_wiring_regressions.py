# 배선 회귀 시험 — 대역 없이 실모듈로 도는 러너 한 바퀴·MCP planned 회수·G6 타깃 차단·events[] 검증·소유권(plan §6.7.2·§6.11·§3.2.2·§8.2.3)
from __future__ import annotations

import dataclasses
import json

import pytest

from app import common, config, identity, narrative, planner, registry, routes, runner

def _enc(pat: str) -> str:
    """저장 열 portal_pat_enc 는 Fernet 암호문이다(plan §8.2.7) — 픽스처도 같은 형식으로 넣는다."""
    return identity.encrypt_pat(pat).decode("ascii")

from app.errors import AppError

OWNER = "owner@example.com"
OTHER = "other@example.com"


# ---------------------------------------------------------------- 원장 준비
def _agents(sizes: dict[str, int]) -> list[dict]:
    return [
        {"key": f"{dom}-a{i:03d}", "domain": dom, "relevance": (n - i) / 100.0}
        for dom, n in sizes.items()
        for i in range(n)
    ]


def _seed(store, *, owner: str = OWNER, target_key: str = "diff:d1") -> str:
    now = common.now_epoch()
    store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
        " VALUES ('p1', ?, 'PRJ-1', '회귀 과제', ?, ?)", (owner, now, now))
    store.execute(
        "INSERT INTO rr_diffs(id, target_project_id, base_project_id, target_snapshot_id, base_snapshot_id,"
        " owner_sub, diff_version, diff_json, summary_text, created_at)"
        " VALUES ('d1', 'p1', 'p0', 's1', 's0', ?, '1.0', '{}', ?, ?)",
        (owner, "구조 3건·치수 2건이 바뀌었다.", now))
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, external_sync_json,"
        " report_ids_json, level, created_at, updated_at)"
        " VALUES (?, ?, 'diff', 'd1', 'p1', 'h1', '{}', '[]', 'C0', ?, ?)", (target_key, owner, now, now))
    planner.freeze_roster(store, target_key, owner,
                          _agents({"mech": 2, "sim": 2, "rel": 1, "xd": 1, "pcb": 1}))
    store.upsert_credential(owner, _enc("pat-secret"), "sub-1", owner, "[]", common.now_epoch() + 30 * 86400)
    return target_key


DECISION = "판정 본문.\n```json\n{\"schema\": \"risk_spec\"}\n```"


class RealEngine:
    """실모듈 경로 회귀용 엔진 대역 — SSE 캡처와 같은 모양만 돌려준다(LLM·네트워크 없음)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.owner_subs: list[str | None] = []

    def health(self) -> dict:
        return {"model": "glm-fake", "provider": "vllm", "endpoint_host": "127.0.0.1", "engine_rev": "rev1"}

    def run(self, delib_opts, *, owner_sub=None):
        self.calls.append(dict(delib_opts))
        self.owner_subs.append(owner_sub)
        keys = [p["key"] for p in delib_opts["personas"]]
        events: list[dict] = [{"kind": "personas", "personas": [{"key": k} for k in keys]}]
        for key in keys:
            events.append({"kind": "status", "step": f"{key} 조회: list_interfaces", "tool": "list_interfaces"})
            events.append({"kind": "evidence", "source": f"{key} · list_interfaces"})
        return {
            "decision_text": DECISION,
            "turns": [{"round": r, "persona": k, "say": f"{k} 라운드 {r}"} for r in (1, 2) for k in keys],
            "events": events, "conv_id": "conv-1", "report_id": 7,
            "call_path": "portal", "credential": "owner",
        }


# ---------------------------------------------------------------- 러너 정본 경로(대역 주입 금지)
def test_runner_interfaces_exist_on_real_modules():
    """운영 배선(main.py)은 실모듈을 그대로 쓴다 — 결손이 있으면 패널 1건도 완주하지 못한다."""
    assert runner.missing_interfaces() == []


def test_run_panel_completes_with_real_modules(risk_store, tmp_path):
    """narrative·registry 대역을 주입하지 않고 run_panel 을 한 바퀴 돌린다(plan §6.7.2)."""
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    job = runner.claim_next_job(risk_store, cfg)

    engine = RealEngine()
    out = runner.run_panel(risk_store, cfg, engine, job)

    assert out["status"] == "done" and out["parsed"] is True
    assert out["coverage"] == {"done": 5}
    # 러너 자격 (b) — 잡 owner 가 엔진까지 간다(plan §6.7 3단계).
    assert engine.owner_subs == [OWNER]
    # 벽시계 상한 40분이 delib_opts 에 실린다(plan §6.10.2).
    assert engine.calls[0]["timeout_s"] == runner.PANEL_TIMEOUT_S == 2400
    # 근거 항목마다 키가 엔진까지 간다 — 러너가 다시 끼우는 E0c 도 빠지지 않는다(엔진이 `[e:N|E3]` 으로 찍는다).
    assert [e["key"] for e in engine.calls[0]["evidence"]] == [
        "E0", "E0c", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9"]

    panel = risk_store.query_one(
        "SELECT status, risk_spec_parsed, quality_json FROM rr_panels WHERE id = ?", (out["panel_id"],))
    assert panel["status"] == "done" and panel["risk_spec_parsed"] == 1
    assert json.loads(panel["quality_json"])["credential"] == "owner"

    # 서술 저장이 실제로 앉았다 — 좌석 5 + 반대석 1.
    assert risk_store.query_one(
        "SELECT COUNT(*) AS n FROM rr_seat_opinions WHERE panel_id = ?", (out["panel_id"],))["n"] == 6
    assert planner.check_invariants(risk_store, target_key) == []
    assert risk_store.query_one("SELECT panels_done FROM rr_jobs WHERE id = ?", (job_id,))["panels_done"] == 1


def test_run_panel_rolls_seats_back_when_interface_is_missing(risk_store, tmp_path, monkeypatch):
    """결손 인터페이스로는 잡을 집지 않는다 — 패널 running·좌석 running 고착이 생기지 않는다."""
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    job = runner.claim_next_job(risk_store, cfg)

    monkeypatch.delattr(narrative, "persist_panel_result")
    out = runner.run_panel(risk_store, cfg, RealEngine(), job)

    assert out["status"] == "missing_interface"
    assert "narrative.persist_panel_result" in out["missing"]
    assert risk_store.query("SELECT id FROM rr_panels") == []
    assert {r["status"] for r in risk_store.query(
        "SELECT status FROM rr_coverage WHERE target_key = ?", (target_key,))} == {"pending"}
    assert risk_store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"] == "failed"


def test_daily_cap_applies_under_a_fixed_clock(risk_store, tmp_path):
    """'지금' 을 common.now_epoch 한 곳에서 읽는다 — 시계를 고정해도 일일 상한이 걸린다."""
    fixed = {"t": common.now_epoch()}
    previous = common.set_clock(lambda: fixed["t"])
    try:
        target_key = _seed(risk_store)
        cfg = dataclasses.replace(config.settings, data_dir=tmp_path, risk_daily_panel_cap=1)
        job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
        panel = planner.plan_next_panel(risk_store, target_key, "A", settings=cfg)
        risk_store.execute("UPDATE rr_panels SET status = 'done' WHERE id = ?", (panel["id"],))

        assert runner.claim_next_job(risk_store, cfg) is None
        row = risk_store.query_one("SELECT state, pause_reason FROM rr_jobs WHERE id = ?", (job_id,))
        assert (row["state"], row["pause_reason"]) == ("paused", "daily_cap")
    finally:
        common.set_clock(previous)


# ---------------------------------------------------------------- MCP 경로(plan §6.11)
def test_mcp_submit_closes_a_planned_panel(risk_store, monkeypatch):
    """planned 패널이 MCP 제출로 done 이 되고 좌석 원장이 일관되게 닫힌다(§6.11 L1·L2)."""
    import app.mcp_server as srv

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    assert panel is not None and panel["status"] == "planned"

    out = srv.risk_submit_panel_result(
        panel_id=panel["id"], engine="mcp", decision_text=DECISION,
        turns=[{"round": 1, "persona": s["key"], "say": "발언"} for s in panel["seats"]],
        report_id=None, actor=OWNER)

    assert "error" not in out, out
    assert out["engine"] == "mcp" and out["tool_mode"] == "evidence_only"
    row = risk_store.query_one(
        "SELECT status, engine, tool_mode, quality_json FROM rr_panels WHERE id = ?", (panel["id"],))
    assert row["status"] == "done"
    assert json.loads(row["quality_json"])["actor_verified"] is False
    assert planner.check_invariants(risk_store, target_key) == []
    assert {r["status"] for r in risk_store.query(
        "SELECT status FROM rr_coverage WHERE panel_id = ?", (panel["id"],))} <= {"done", "done_weak"}


def test_mcp_submit_rejects_other_owner(risk_store, monkeypatch):
    """actor 가 패널 owner 가 아니면 남의 원장을 닫을 수 없다."""
    import app.mcp_server as srv

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    assert srv.risk_submit_panel_result(
        panel_id=panel["id"], engine="mcp", decision_text=DECISION, turns=[],
        report_id=None, actor=OTHER)["error"] == "E404"
    assert risk_store.query_one(
        "SELECT status FROM rr_panels WHERE id = ?", (panel["id"],))["status"] == "planned"


# ---------------------------------------------------------------- 재제출(plan §8.2.3·§6.11)
def test_resubmit_without_events_keeps_attribution_and_engine(risk_store, monkeypatch):
    """events[] 가 없으면 귀속 값과 기존 engine·tool_mode 를 그대로 둔다."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    keys = [s["key"] for s in panel["seats"]]
    events = [{"kind": "personas", "personas": [{"key": k} for k in keys]}]
    for key in keys:
        events.append({"kind": "status", "step": f"{key} 조회: list_interfaces"})
        events.append({"kind": "evidence", "source": f"{key} · list_interfaces"})

    first = routes.complete_panel(panel["id"], engine="mcp", decision_text=DECISION, turns=[],
                                  events=events, actor=OWNER, owner_sub=OWNER)
    assert first["attribution_rate"] == 1.0

    again = routes.complete_panel(panel["id"], engine="web", decision_text=DECISION, turns=[],
                                  events=None, actor=OWNER, actor_verified=True, owner_sub=OWNER)
    assert again["attribution_rate"] == 1.0          # 지워지지 않는다
    assert again["engine"] == "mcp" and again["tool_mode"] == "evidence_only"   # 재제출은 기존 값을 지킨다
    quality = json.loads(risk_store.query_one(
        "SELECT quality_json FROM rr_panels WHERE id = ?", (panel["id"],))["quality_json"])
    assert quality["attribution_rate"] == 1.0 and quality["extra_seats"] == []


def test_spec_parse_failure_sets_flag(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    out = routes.complete_panel(panel["id"], engine="mcp", decision_text="펜스 없는 산문", turns=[],
                                actor=OWNER, owner_sub=OWNER)
    assert out["parsed"] is False
    quality = json.loads(risk_store.query_one(
        "SELECT quality_json FROM rr_panels WHERE id = ?", (panel["id"],))["quality_json"])
    assert "spec_parse_failed" in quality["flags"]


# ---------------------------------------------------------------- events[] 검증(plan §8.2.3)
def test_events_validation_and_truncation():
    with pytest.raises(AppError) as exc:
        routes._check_events([{"kind": "없는종류"}])
    assert exc.value.http_status == 422

    with pytest.raises(AppError) as exc:
        routes._check_events([{"kind": "status", "step": "x" * (routes.EVENT_FIELD_MAX + 1)}])
    assert exc.value.http_status == 422

    checked, truncated = routes._check_events([{"kind": "status", "step": "s"}] * (routes.EVENTS_MAX + 5))
    assert len(checked) == routes.EVENTS_MAX and truncated is True
    assert routes._check_events(None) == (None, False)


# ---------------------------------------------------------------- G6 차단(plan §3.2.2)
def test_create_target_is_blocked_by_g6(risk_store, monkeypatch):
    """단위가 어긋난 스냅샷(G6 fail) 위에는 심사 타깃을 열 수 없다 — diff 생성 409 와 같은 규칙."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    now = common.now_epoch()
    risk_store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
        " VALUES ('p1', ?, 'PRJ-1', '차단 과제', ?, ?)", (OWNER, now, now))
    risk_store.execute(
        "INSERT INTO rr_snapshots(id, owner_sub, project_id, ir_version, ir_hash, ir_json, source_ids_json,"
        " kinds_json, node_count, edge_count, created_at)"
        " VALUES ('sblk', ?, 'p1', '1.0', 'h1', '{}', '[]', ?, 0, 0, ?)",
        (OWNER, json.dumps(["mcad"]), now))
    risk_store.execute(
        "INSERT INTO rr_states(snapshot_id, owner_sub, state_json, feature_json, rule_hits_json,"
        " character_seed_json, gates_json, blocked, computed_at)"
        " VALUES ('sblk', ?, '{}', '{}', '[]', '[]', ?, 1, ?)",
        (OWNER, json.dumps({"G6": {"pass": False, "reason": "unit_scale"}}), now))

    ident = type("I", (), {"anonymous": False, "email": OWNER, "to_dict": lambda self: {"email": OWNER}})()
    with pytest.raises(AppError) as exc:
        routes.create_target(routes.TargetBody(kind="snap", ref_id="sblk", consent=True), ident=ident)
    assert (exc.value.code, exc.value.http_status) == ("gate_blocked", 409)
    assert exc.value.detail["reason"] == "unit_mismatch" and "target" in exc.value.detail["gates"]
    assert "G6" in exc.value.message
    assert risk_store.query("SELECT target_key FROM rr_targets") == []


# ---------------------------------------------------------------- 소유권(plan §8.2.3)
def test_anonymous_write_is_401_and_other_owner_is_404(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)

    anon = type("I", (), {"anonymous": True, "email": None, "to_dict": lambda self: {}})()
    with pytest.raises(AppError) as exc:
        routes.create_job(target_key, routes.JobBody(tier="A"), ident=anon)
    assert exc.value.http_status == 401

    other = type("I", (), {"anonymous": False, "email": OTHER, "to_dict": lambda self: {"email": OTHER}})()
    with pytest.raises(AppError) as exc:
        routes.get_coverage(target_key, ident=other)
    assert (exc.value.code, exc.value.http_status) == ("E404", 404)


# ---------------------------------------------------------------- registry 러너 접점
def test_merge_panel_counts_new_clusters(risk_store):
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    out = registry.merge_panel(risk_store, panel["id"])
    assert out["panel_id"] == panel["id"] and out["new_clusters"] == 0
    with pytest.raises(AppError):
        registry.merge_panel(risk_store, "없는패널")


# ---------------------------------------------------------------- 결정론(plan §3.1 원칙 1·§2.6.3)
def test_state_json_does_not_carry_the_clock(risk_store):
    """같은 (ir_hash, rule_version) 이면 rr_states.state_json 이 같다 — 시각은 열에만 남는다."""
    from app import state as state_module

    now = common.now_epoch()
    risk_store.execute(
        "INSERT INTO rr_snapshots(id, owner_sub, project_id, ir_version, ir_hash, ir_json, source_ids_json,"
        " kinds_json, node_count, edge_count, created_at)"
        " VALUES ('s1', ?, 'p1', '1.0', 'h1', '{}', '[]', ?, 0, 0, ?)", (OWNER, json.dumps(["mcad"]), now))
    ir = {"snapshot_id": "s1", "ir_hash": "h1", "project_id": "p1", "nodes": [], "edges": [],
          "dims_named": [], "warnings": [], "rollups": {}, "missing": {}, "versions": {}}
    first = state_module.build_state(ir, computed_at=1_000_000)
    second = state_module.build_state(ir, computed_at=2_000_000)
    state_module.save_state(risk_store, first, owner_sub=OWNER)
    stored_first = risk_store.query_one("SELECT state_json FROM rr_states WHERE snapshot_id = 's1'")["state_json"]
    state_module.save_state(risk_store, second, owner_sub=OWNER)
    row = risk_store.query_one("SELECT state_json, computed_at FROM rr_states WHERE snapshot_id = 's1'")
    assert row["state_json"] == stored_first
    assert row["computed_at"] == 2_000_000
    assert state_module.load_state(risk_store, "s1")["computed_at"] == 2_000_000


def test_hungarian_tiebreak_perturbation_is_not_separable():
    """선형 섭동은 어떤 완전배정에서도 합이 같아 동점을 못 깬다 — 제곱 섭동은 실제로 가른다."""
    from app import sameas

    nb = 2
    den = float(nb * nb + 1)
    def pert(i, j):
        return 1e-9 * ((i * nb + j) ** 2) / (den * den)

    identity = pert(0, 0) + pert(1, 1)
    swap = pert(0, 1) + pert(1, 0)
    assert identity != swap, "분리형 섭동이면 두 배정의 합이 같아 최적해가 유일하지 않다"

    cost = [[0.4 + pert(i, j) for j in range(2)] for i in range(2)]
    chosen = sameas._hungarian(cost)
    # 최적해가 유일하므로 솔버(scipy/동봉 JV)와 무관하게 같은 배정이 나온다.
    assert chosen == [0, 1] if identity < swap else chosen == [1, 0]
    assert sameas._hungarian(cost) == chosen


def test_model_changed_midrun_is_flagged(risk_store, tmp_path):
    """시작·종료 /health 의 model 이 다르면 quality.flags 에 남는다(D6, plan §6.7.2 7단계)."""
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    job = runner.claim_next_job(risk_store, cfg)

    class DriftingEngine(RealEngine):
        def __init__(self) -> None:
            super().__init__()
            self.n = 0

        def health(self) -> dict:
            self.n += 1
            return {"model": f"glm-{self.n}", "provider": "vllm"}

    out = runner.run_panel(risk_store, cfg, DriftingEngine(), job)
    assert out["status"] == "done"
    row = risk_store.query_one(
        "SELECT quality_json, model_json FROM rr_panels WHERE id = ?", (out["panel_id"],))
    assert "model_changed_midrun" in json.loads(row["quality_json"])["flags"]
    model = json.loads(row["model_json"])
    assert model["model"] == "glm-1" and model["model_end"] == "glm-2"
    assert model["seat_contract_rev"] == runner.seat_contract_rev()
