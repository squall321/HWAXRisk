# runner.py 패널 1건 시험 — 좌석 귀속·delib_opts·잡 자격(pat_unavailable)·FakePanelEngine 완주(plan §6.7)
from __future__ import annotations

import dataclasses
import json
import types

import pytest

from app import config, identity, planner, runner

def _enc(pat: str) -> str:
    """저장 열 portal_pat_enc 는 Fernet 암호문이다(plan §8.2.7) — 픽스처도 같은 형식으로 넣는다."""
    return identity.encrypt_pat(pat).decode("ascii")

from app.common import now_epoch
from app.errors import AppError

OWNER = "u@x"
ADVERSARY = planner.ADVERSARY_KEY


# ---------------------------------------------------------------- 원장 준비
def agents(sizes: dict[str, int]) -> list[dict]:
    return [
        {"key": f"{dom}-a{i:03d}", "domain": dom, "relevance": (n - i) / 100.0}
        for dom, n in sizes.items()
        for i in range(n)
    ]


def make_project(store, project_id: str = "p1", code: str = "PRJ-1") -> None:
    now = now_epoch()
    store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, OWNER, code, "테스트 과제", now, now),
    )


def make_target(store, target_key: str = "t1", *, kind: str = "diff", report_ids: list | None = None) -> str:
    now = now_epoch()
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, external_sync_json,"
        " report_ids_json, level, created_at, updated_at) VALUES (?, ?, ?, 'diff-1', 'p1', 'h1', '{}', ?, 'C0', ?, ?)",
        (target_key, OWNER, kind, json.dumps(report_ids or []), now, now),
    )
    return target_key


def seeded(store, sizes: dict[str, int] | None = None) -> str:
    make_project(store)
    target_key = make_target(store)
    store.execute(
        "INSERT INTO rr_diffs(id, target_project_id, base_project_id, target_snapshot_id, base_snapshot_id,"
        " owner_sub, diff_version, diff_json, summary_text, created_at)"
        " VALUES ('diff-1', 'p1', 'p0', 's1', 's0', ?, '1.0', '{}', ?, ?)",
        (OWNER, "구조 3건·치수 2건이 바뀌었다.", now_epoch()),
    )
    planner.freeze_roster(store, target_key, OWNER, agents(sizes or {"mech": 2, "sim": 2, "rel": 1, "xd": 1, "pcb": 1}))
    return target_key


def give_credential(store, owner_sub: str = OWNER) -> None:
    store.upsert_credential(
        owner_sub, _enc("pat-secret"), "sub-1", "u@x", json.dumps(["hwax-risk"]),
        now_epoch() + 30 * 86400,
    )


def coverage(store, target_key: str) -> dict[str, dict]:
    return {
        r["agent_key"]: dict(r)
        for r in store.query(
            "SELECT agent_key, status, retry, opinion_id, model, panel_id FROM rr_coverage WHERE target_key = ?",
            (target_key,),
        )
    }


# ---------------------------------------------------------------- 테스트 대역
class FakePanelEngine:
    """SSE 캡처 결과와 같은 형태({decision_text, turns, conv_id, events})를 돌려주는 심의 엔진 대역."""

    def __init__(self, seat_keys: list[str] | None = None, *, raise_error: Exception | None = None) -> None:
        self.seat_keys = seat_keys or []
        self.raise_error = raise_error
        self.calls: list[dict] = []
        self.owner_subs: list[str | None] = []
        self.health_calls = 0
        self.evidence_sent: list[dict] = []
        self.last_events: list[dict] = []

    def health(self) -> dict:
        self.health_calls += 1
        return {"model": "glm-fake", "provider": "vllm", "endpoint_host": "127.0.0.1", "engine_rev": "rev1"}

    def run(self, delib_opts, *, owner_sub=None):
        self.calls.append(dict(delib_opts))
        self.owner_subs.append(owner_sub)
        if self.raise_error is not None:
            raise self.raise_error
        keys = [p["key"] for p in delib_opts["personas"]]
        turns = [{"round": r, "persona": key, "say": f"{key} 라운드 {r} 발언"} for r in (1, 2, 3) for key in keys]
        events: list[dict] = [{"kind": "personas", "personas": [{"key": k} for k in keys + [ADVERSARY]]}]
        for key in keys:
            events.append({"kind": "status", "step": f"{key} 조회: list_interfaces", "tool": "list_interfaces"})
            events.append({"kind": "evidence", "source": f"{key} · list_interfaces", "text": "…"})
        events.append({"kind": "evidence", "source": "rr_diff", "text": "공용 근거"})
        # 브리프로 보낸 prior_evidence 는 항목마다 채택 사실을 되돌려준다(plan §5.6 '드롭 0' 확인용).
        self.evidence_sent = list(delib_opts.get("evidence") or [])
        for item in self.evidence_sent:
            events.append({"kind": "evidence", "source": str(item.get("source") or ""), "included": True})
        self.last_events = events
        return {
            "decision_text": "판정문 본문.\n```json\n{}\n```",
            "turns": turns,
            "events": events,
            "conv_id": "conv-1",
            "report_id": 77,
            "call_path": "portal",
        }


def fake_narrative(recorder: dict) -> types.SimpleNamespace:
    """narrative 대역 — 러너가 부르는 세 함수만 갖춘다(실물은 배선 담당이 채운다)."""

    def prior_evidence(store, target_key, *, user_memo=None, seats=None, panel_id=None, exclude=()):
        recorder["prior_evidence"] = {"target_key": target_key, "user_memo": user_memo}
        return [{"source": "rr_state", "tool": "gates", "args": target_key, "result": "G1 pass"}]

    def parse_risk_spec(text):
        return {"findings": [{"id": "F1"}]} if "```json" in text else None

    def persist_panel_result(store, panel_id, *, decision_text, spec, turns, attribution, actor=None):
        recorder["persist"] = {"panel_id": panel_id, "spec": spec, "turns": len(turns),
                               "attribution": attribution}
        panel = store.query_one("SELECT seats_json FROM rr_panels WHERE id = ?", (panel_id,))
        seats = json.loads(panel["seats_json"])
        return {
            "seats": [
                {"agent_key": s["key"], "opinion_id": f"op-{i}", "turns_n": 3, "cited_refs_n": 2,
                 "cited_ir": i < 3, "abstained": False}
                for i, s in enumerate(seats)
            ],
            "findings_total": 3,
            "adversary_rejects": 1,
            "grade_dist": {"A": 2, "B": 1},
        }

    return types.SimpleNamespace(
        prior_evidence=prior_evidence, parse_risk_spec=parse_risk_spec, persist_panel_result=persist_panel_result
    )


def fake_registry(recorder: dict, *, level: str = "C0", raised: bool = False,
                  new_clusters: int = 2) -> types.SimpleNamespace:
    def merge_panel(store, panel_id):
        recorder["merge_panel"] = panel_id
        return {"new_clusters": new_clusters}

    def close_level(store, target_key, **kwargs):
        return {"level": level, "raised": raised}

    def build_consolidated_report(store, target_key, lvl):
        recorder["report"] = (target_key, lvl)
        return {"ok": True}

    return types.SimpleNamespace(
        merge_panel=merge_panel, close_level=close_level, build_consolidated_report=build_consolidated_report
    )


# ---------------------------------------------------------------- 좌석 귀속(plan §6.7 7단계)
def test_attribute_events_counts_attempts_and_successes():
    seats = ["mech-a", "sim-b"]
    events = [
        {"kind": "personas", "personas": [{"key": "mech-a"}, {"key": "sim-b"}, {"key": ADVERSARY}]},
        {"kind": "status", "step": "mech-a 조회: list_interfaces"},
        {"kind": "evidence", "source": "mech-a · list_interfaces", "text": "…"},
        {"kind": "status", "step": "sim-b 조회: interface_graph"},     # 빈 결과 — evidence 없음
        {"kind": "evidence", "source": "rr_state", "text": "공용 E0"},  # 좌석 귀속 없음
        {"kind": "turn", "persona": "mech-a", "say": "…"},
        {"kind": "turn", "persona": "sim-b", "say": "…"},
    ]
    out = runner.attribute_events(events, seats)
    assert out["seats"]["mech-a"]["tool_calls_n"] == 1
    assert out["seats"]["mech-a"]["tool_calls_ok"] == 1
    assert out["seats"]["mech-a"]["used_tool"] is True
    assert out["seats"]["mech-a"]["tool_calls"] == [{"tool": "list_interfaces", "activity_idx": 0}]
    # 빈 결과 호출은 status 만 나오므로 tool_calls_n ≥ tool_calls_ok 가 유지된다.
    assert (out["seats"]["sim-b"]["tool_calls_n"], out["seats"]["sim-b"]["tool_calls_ok"]) == (1, 0)
    assert out["seats"]["sim-b"]["used_tool"] is False
    assert out["seats"][ADVERSARY]["used_tool"] is False
    assert out["seats"]["mech-a"]["turns_n"] == 1
    assert out["extra_seats"] == []
    assert out["attribution_rate"] == 1.0 and (out["attributable"], out["attributed"]) == (3, 3)


def test_attribute_events_marks_extra_seats_and_unattributed():
    out = runner.attribute_events(
        [
            {"kind": "personas", "personas": [{"key": "mech-a"}, {"key": "새좌석-x"}]},
            {"kind": "status", "step": "새좌석-x 조회: list_interfaces"},
        ],
        ["mech-a"],
    )
    assert out["extra_seats"] == ["새좌석-x"]
    assert (out["attributable"], out["attributed"]) == (1, 0)
    assert out["attribution_rate"] == 0.0


def test_attribute_events_without_events_is_unattributable():
    out = runner.attribute_events(None, ["mech-a"])
    assert out["seats"]["mech-a"]["used_tool"] is None
    assert out["seats"]["mech-a"]["tool_calls_n"] is None
    assert out["attribution_rate"] is None


# ---------------------------------------------------------------- 자격(plan §6.7 3단계)
def test_resolve_credential_prefers_owner_then_service(risk_store, tmp_path):
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    assert runner.resolve_credential(risk_store, cfg, OWNER) is None

    give_credential(risk_store)
    assert runner.resolve_credential(risk_store, cfg, OWNER) == {"kind": "owner", "email": "u@x"}

    # 만료가 코앞이면 (b) 를 쓰지 않는다.
    risk_store.upsert_credential(OWNER, _enc("pat"), "sub-1", "u@x", "[]", now_epoch() + 60)
    assert runner.resolve_credential(risk_store, cfg, OWNER) is None

    secrets = tmp_path / "secrets.env"
    secrets.write_text("HWAXRISK_PORTAL_PAT=svc-pat\n", encoding="utf-8")
    secrets.chmod(0o600)
    # 서비스 자격의 email 은 'service' 로 기록한다(rr_jobs.credential_email 이 사람 계정과 구분된다).
    assert runner.resolve_credential(risk_store, cfg, OWNER) == {"kind": "service", "email": "service"}


def test_resolve_credential_tries_the_requester_before_the_target_owner(risk_store, tmp_path):
    """(c) 요청자 → (b) 타깃 owner → (a) 서비스 3단이고 첫 적중의 email 이 정본이다(plan §0.1.6)."""
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    peer = "peer@x"

    # 둘 다 없음 → None.
    assert runner.resolve_credential(risk_store, cfg, OWNER, peer) is None

    # 요청자만 있음 → requester.
    risk_store.upsert_credential(peer, _enc("pat-peer"), "sub-2", peer, "[]", now_epoch() + 30 * 86400)
    assert runner.resolve_credential(risk_store, cfg, OWNER, peer) == {"kind": "requester", "email": peer}

    # 둘 다 있음 → 요청자가 먼저다.
    give_credential(risk_store)
    assert runner.resolve_credential(risk_store, cfg, OWNER, peer)["kind"] == "requester"

    # 요청자 자격이 만료되면 타깃 owner 로 내려간다.
    risk_store.upsert_credential(peer, _enc("pat-peer"), "sub-2", peer, "[]", now_epoch() + 60)
    assert runner.resolve_credential(risk_store, cfg, OWNER, peer) == {"kind": "owner", "email": "u@x"}


def test_create_job_records_the_credential_email(risk_store, tmp_path):
    target_key = seeded(risk_store)
    peer = "peer@x"
    risk_store.upsert_credential(peer, _enc("pat-peer"), "sub-2", peer, "[]", now_epoch() + 30 * 86400)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    out = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg, requester_sub=peer)
    assert out["credential"] == "requester" and out["credential_email"] == peer
    row = risk_store.query_one("SELECT credential_email, owner_sub FROM rr_jobs WHERE id = ?", (out["job_id"],))
    assert row["credential_email"] == peer and row["owner_sub"] == OWNER


def test_create_job_without_credential_is_pat_unavailable(risk_store, tmp_path):
    target_key = seeded(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    with pytest.raises(AppError) as exc:
        runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    assert (exc.value.code, exc.value.http_status) == ("pat_unavailable", 422)
    assert risk_store.query("SELECT id FROM rr_jobs") == []


def test_create_job_records_plan_and_guards_tier_c(risk_store, tmp_path):
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)

    with pytest.raises(AppError) as exc:
        runner.create_job(risk_store, target_key, "C", owner_sub=OWNER, settings=cfg)
    assert exc.value.code == "E100"                       # Tier C 는 consent 필수
    with pytest.raises(AppError):
        runner.create_job(risk_store, target_key, "Z", owner_sub=OWNER, settings=cfg)

    out = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, modifiers=["voi"],
                            user_memo="메모", settings=cfg)
    plan = {t["tier"]: t for t in planner.tier_plan(risk_store, target_key, settings=cfg)["tiers"]}["A"]
    assert out["panels_planned"] == plan["panels"]
    assert out["llm_calls_estimate"] == {"low": plan["llm_calls_low"], "high": plan["llm_calls_high"]}
    assert out["credential"] == "owner"

    row = risk_store.query_one(
        "SELECT state, tier, params_json, panels_total, concurrency FROM rr_jobs WHERE id = ?", (out["job_id"],)
    )
    assert (row["state"], row["tier"], row["panels_total"]) == ("queued", "A", plan["panels"])
    params = json.loads(row["params_json"])
    assert params["modifiers"] == ["voi", "toulmin"] and params["credential"] == "owner"
    assert params["user_memo"] == "메모" and params["consent"] is False


def test_claim_next_job_marks_pat_unavailable_and_keeps_state(risk_store, tmp_path):
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]

    risk_store.delete_credential(OWNER)                   # 자격이 사라졌다
    assert runner.claim_next_job(risk_store, cfg) is None
    row = risk_store.query_one("SELECT state, error FROM rr_jobs WHERE id = ?", (job_id,))
    assert (row["state"], row["error"]) == ("queued", "pat_unavailable")

    give_credential(risk_store)                           # 자격이 생기면 다음 주기에 집는다
    job = runner.claim_next_job(risk_store, cfg)
    assert job["id"] == job_id and job["state"] == "running" and job["credential"] == "owner"
    assert job["params"]["tier"] == "A"


def test_claim_next_job_respects_serial_and_daily_cap(risk_store, tmp_path):
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]

    panel = planner.plan_next_panel(risk_store, target_key, "A", settings=cfg)
    planner.start_panel_seats(risk_store, panel["id"])     # 같은 타깃에 running 패널이 있으면 건너뛴다
    assert runner.claim_next_job(risk_store, cfg) is None

    risk_store.execute("UPDATE rr_panels SET status = 'done' WHERE id = ?", (panel["id"],))
    capped = dataclasses.replace(cfg, risk_daily_panel_cap=1)
    assert runner.claim_next_job(risk_store, capped) is None
    row = risk_store.query_one("SELECT state, pause_reason FROM rr_jobs WHERE id = ?", (job_id,))
    assert (row["state"], row["pause_reason"]) == ("paused", "daily_cap")


def test_job_state_transitions(risk_store, tmp_path):
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]

    assert runner.pause_job(risk_store, job_id, reason="user")["state"] == "paused"
    with pytest.raises(AppError) as exc:
        runner.pause_job(risk_store, job_id)
    assert exc.value.http_status == 409
    assert runner.resume_job(risk_store, job_id)["state"] == "queued"
    with pytest.raises(AppError):
        runner.resume_job(risk_store, job_id)
    assert runner.cancel_job(risk_store, job_id)["state"] == "cancelled"
    assert runner.cancel_job(risk_store, job_id)["state"] == "cancelled"      # 멱등
    with pytest.raises(AppError) as exc:
        runner.pause_job(risk_store, "없는잡")
    assert exc.value.code == "E404"


# ---------------------------------------------------------------- delib_opts(plan §6.6.4)
def test_build_delib_opts_shape_and_forbidden_keys(risk_store):
    target_key = seeded(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "A")
    recorder: dict = {}
    opts = runner.build_delib_opts(
        risk_store, config.settings, panel, user_memo="사용자 메모", narrative_mod=fake_narrative(recorder)
    )

    assert opts["chair_template"] == "risk-review"
    assert opts["modifiers"] == ["toulmin"] and opts["rounds"] == panel["rounds"]
    assert (opts["free_tools"], opts["tool_budget"]) == (planner.FREE_TOOLS, planner.TOOL_BUDGET)
    assert [p["key"] for p in opts["personas"]] == [s["key"] for s in panel["seats"]]
    assert all(p["role"] == "" for p in opts["personas"])
    assert [p["origin"] for p in opts["personas"]] == [s["origin"] for s in panel["seats"]]
    assert opts["tools"] == panel["tools"]
    assert len(opts["apps"]) <= planner.MAX_APPS and "heax-step_forge" in opts["apps"]
    assert len(opts["evidence"]) <= planner.MAX_EVIDENCE

    # E0 바로 뒤가 좌석 계약표(E0c)이고, 사용자 메모는 마지막 슬롯이다.
    assert opts["evidence"][1]["source"] == "seat_contract"
    assert opts["evidence"][1]["tool"] == "seat-contract.v1"
    assert opts["evidence"][-1] == {"source": "user_memo", "tool": "note", "result": "사용자 메모", "key": "M"}
    assert opts["evidence"][1]["key"] == "E0c"
    assert recorder["prior_evidence"] == {"target_key": target_key, "user_memo": "사용자 메모"}

    for forbidden in ("human_note", "continue_summary", "non_negotiables", "search_sources",
                      "stop_after_round", "build_plan"):
        assert forbidden not in opts

    assert target_key in opts["question"] and "PRJ-1" in opts["question"]
    assert "구조 3건" in opts["question"]


def test_delib_opts_turn_off_the_engines_automatic_voc_recall(risk_store, tmp_path):
    """자동 VOC 환기를 끈 채로 엔진까지 간다 — 안 실으면 엔진 기본값 'auto' 가 리스크 심사마다 SignalForge 를 부른다."""
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    job = runner.claim_next_job(risk_store, cfg)

    recorder: dict = {}
    engine = FakePanelEngine()
    runner.run_panel(risk_store, cfg, engine, job,
                     narrative_mod=fake_narrative(recorder), registry_mod=fake_registry(recorder))

    assert engine.calls[0]["voc"] == "off"


# ---------------------------------------------------------------- 근거 12칸(planner.MAX_EVIDENCE)
def _keyed(keys: list[str]) -> list[dict]:
    return [{"source": f"src_{k}", "tool": "t", "args": "a", "result": f"{k} 본문", "key": k} for k in keys]


BRIEF_PLUS_TWO = ["E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "X1", "X2"]


def test_evidence_past_the_slot_cap_is_named_and_the_memo_keeps_its_slot(risk_store):
    """12칸을 넘는 근거는 무엇이 빠졌는지 남기고, 넘칠 때 빠지는 것은 사용자 메모가 아니다.

    종전에는 `evidence[:12]` 가 13번째부터를 말없이 버렸다. 좌석 계약(E0c)은 브리프를 재고 난 뒤에 끼우고
    메모는 맨 끝에 붙으므로, 한 칸만 넘쳐도 가장 먼저 떨어지는 것이 사람이 직접 쓴 메모였다.
    """
    target_key = seeded(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "A")

    loss: dict = {}
    opts = runner.build_delib_opts(risk_store, config.settings, panel, evidence=_keyed(BRIEF_PLUS_TWO),
                                   user_memo="이 계면을 먼저 보라", loss=loss)
    assert [e["key"] for e in opts["evidence"]] == [
        "E0", "E0c", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "M"]
    assert "이 계면을 먼저 보라" in opts["evidence"][-1]["result"]
    assert loss == {"evidence_dropped": ["X1", "X2"]}

    # 메모가 없으면 뒤에서부터 빠진다. 키 없는 항목은 source 로 적는다.
    loss = {}
    unkeyed = _keyed(BRIEF_PLUS_TWO[:-1]) + [{"source": "caller_note", "tool": "", "args": "", "result": "키 없음"}]
    opts = runner.build_delib_opts(risk_store, config.settings, panel, evidence=unkeyed, loss=loss)
    assert len(opts["evidence"]) == planner.MAX_EVIDENCE and opts["evidence"][-1]["key"] == "X1"
    assert loss == {"evidence_dropped": ["caller_note"]}

    # 12칸 안이면 남길 것이 없다.
    loss = {}
    runner.build_delib_opts(risk_store, config.settings, panel, evidence=_keyed(BRIEF_PLUS_TWO[:10]),
                            user_memo="메모", loss=loss)
    assert loss == {}


def test_run_panel_records_dropped_evidence_on_the_panel(risk_store, tmp_path):
    """빠진 근거의 키가 그 패널의 quality 에 남는다 — 좌석은 받은 것이 전부라고 믿고 판정했다."""
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg, user_memo="이 계면을 먼저 보라")
    job = runner.claim_next_job(risk_store, cfg)

    recorder: dict = {}
    crowded = fake_narrative(recorder)
    crowded.prior_evidence = lambda store, key, **kwargs: _keyed(BRIEF_PLUS_TWO)
    engine = FakePanelEngine()
    out = runner.run_panel(risk_store, cfg, engine, job,
                           narrative_mod=crowded, registry_mod=fake_registry(recorder))

    assert out["status"] == "done" and out["quality_flags"] == ["evidence_dropped"]
    quality = json.loads(risk_store.query_one(
        "SELECT quality_json FROM rr_panels WHERE id = ?", (out["panel_id"],))["quality_json"])
    assert quality["evidence_dropped"] == ["X1", "X2"] and "evidence_dropped" in quality["flags"]
    sent = engine.calls[0]["evidence"]
    assert len(sent) == planner.MAX_EVIDENCE and "이 계면을 먼저 보라" in sent[-1]["result"]


def test_run_panel_relays_what_the_engine_withheld(risk_store, tmp_path):
    """엔진이 근거를 좌석에 못 줬다고 띄운 카드가 패널 quality 에 남는다 — 배치 러너의 스트림은 아무도 안 본다."""
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    job = runner.claim_next_job(risk_store, cfg)
    notice = {"kind": "evidence", "source": "사전 근거 예산 초과", "included": False,
              "note": "근거 12건 중 뒤쪽 10건은 예산(2,000자)을 넘겨 좌석에 주지 않았다."}

    class StarvedEngine(FakePanelEngine):
        def run(self, delib_opts, *, owner_sub=None):
            result = dict(super().run(delib_opts, owner_sub=owner_sub))
            seat = delib_opts["personas"][0]["key"]
            result["events"] = list(result["events"]) + [
                notice, dict(notice),                                    # 같은 알림이 두 번 와도 한 번만 적는다
                {"kind": "evidence", "source": f"{seat} · 자유 조회 실패", "included": False, "note": "timeout"},
            ]
            return result

    recorder: dict = {}
    out = runner.run_panel(risk_store, cfg, StarvedEngine(), job,
                           narrative_mod=fake_narrative(recorder), registry_mod=fake_registry(recorder))

    assert out["quality_flags"] == ["engine_withheld"]
    quality = json.loads(risk_store.query_one(
        "SELECT quality_json FROM rr_panels WHERE id = ?", (out["panel_id"],))["quality_json"])
    assert quality["engine_withheld"] == [
        "사전 근거 예산 초과 — 근거 12건 중 뒤쪽 10건은 예산(2,000자)을 넘겨 좌석에 주지 않았다."]


def test_seat_contract_evidence_budget():
    item = runner.seat_contract_evidence(["mech", "mech", "sim", "없는도메인"])
    assert item["source"] == "seat_contract" and item["args"] == "mech,sim,없는도메인"
    assert item["key"] == "E0c"
    lines = item["result"].splitlines()
    assert len(lines) == 2                                        # 없는 도메인 줄은 실리지 않는다
    assert all(len(line) <= runner.SEAT_CONTRACT_LINE_MAX for line in lines)
    assert len(item["result"]) <= runner.SEAT_CONTRACT_TOTAL_MAX


# ---------------------------------------------------------------- 패널 1건 완주(plan §6.7.2)
def test_run_panel_completes_with_fake_engine(risk_store, tmp_path):
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    job = runner.claim_next_job(risk_store, cfg)
    assert job["id"] == job_id

    recorder: dict = {}
    engine = FakePanelEngine()
    out = runner.run_panel(
        risk_store, cfg, engine, job,
        narrative_mod=fake_narrative(recorder), registry_mod=fake_registry(recorder),
    )

    assert out["status"] == "done" and out["parsed"] is True
    assert out["new_clusters"] == 2 and out["quality_flags"] == []
    assert out["coverage"] == {"done": 5}

    panel = risk_store.query_one(
        "SELECT status, decision_text, risk_spec_parsed, conv_id, report_id, llm_calls, quality_json, model_json,"
        " seats_json, started_at, ended_at FROM rr_panels WHERE id = ?", (out["panel_id"],)
    )
    assert panel["status"] == "done" and panel["risk_spec_parsed"] == 1
    assert (panel["conv_id"], panel["report_id"]) == ("conv-1", 77)
    assert panel["started_at"] and panel["ended_at"]
    seats = json.loads(panel["seats_json"])

    # 사후 표기 llm_calls = turn 수 + 좌석 조회 status × 3 + T + 3(plan §6.10.2).
    assert panel["llm_calls"] == out["llm_calls"] == 3 * len(seats) + len(seats) * 3 + 2 + 3
    model = json.loads(panel["model_json"])
    assert model["captured"] == "health_snapshot" and model["model"] == "glm-fake"
    assert engine.health_calls == 2                                # 시작·종료 스냅샷

    quality = json.loads(panel["quality_json"])
    assert quality["tool_use_rate"] == 1.0 and quality["attribution_rate"] == 1.0
    assert quality["ir_cite_rate"] == pytest.approx(3 / 5)
    assert quality["credential"] == "owner" and quality["call_path"] == "portal"
    assert quality["new_clusters"] == 2 and quality["flags"] == []
    assert quality["grade_dist"] == {"A": 2, "B": 1}

    rows = coverage(risk_store, target_key)
    for seat in seats:
        assert rows[seat["key"]]["status"] == "done"
        assert rows[seat["key"]]["opinion_id"] and rows[seat["key"]]["model"] == "glm-fake"
    assert planner.check_invariants(risk_store, target_key) == []

    assert recorder["merge_panel"] == out["panel_id"]
    assert recorder["persist"]["panel_id"] == out["panel_id"]
    assert risk_store.query_one("SELECT panels_done FROM rr_jobs WHERE id = ?", (job_id,))["panels_done"] == 1
    assert len(engine.calls) == 1 and engine.calls[0]["chair_template"] == "risk-review"


def test_engine_accepts_every_evidence_item_that_was_sent(risk_store, tmp_path):
    """보낸 prior_evidence 항목 수와 엔진 로그의 채택(included=true) 수가 같다 — 드롭 0(plan §0.9 P1-10)."""
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    job = runner.claim_next_job(risk_store, cfg)

    recorder: dict = {}
    engine = FakePanelEngine()
    runner.run_panel(risk_store, cfg, engine, job,
                     narrative_mod=fake_narrative(recorder), registry_mod=fake_registry(recorder))

    sent = engine.calls[0]["evidence"]
    assert sent, "브리프 항목이 하나도 실리지 않았다."
    accepted = [e for e in engine.last_events if e.get("kind") == "evidence" and e.get("included") is True]
    assert len(accepted) == len(sent)
    assert [e["source"] for e in accepted] == [str(item.get("source") or "") for item in sent]


def test_run_panel_flags_weak_quality_when_seats_do_not_use_tools(risk_store, tmp_path):
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    job = runner.claim_next_job(risk_store, cfg)

    class SilentEngine(FakePanelEngine):
        def run(self, delib_opts, *, owner_sub=None):
            result = dict(super().run(delib_opts, owner_sub=owner_sub))
            keys = [p["key"] for p in delib_opts["personas"]]
            result["events"] = [{"kind": "personas", "personas": [{"key": k} for k in keys]}]
            return result

    recorder: dict = {}
    narrative = fake_narrative(recorder)
    original = narrative.persist_panel_result

    def no_ir(store, panel_id, **kwargs):
        extracted = dict(original(store, panel_id, **kwargs))
        extracted["seats"] = [dict(s, cited_ir=False, cited_refs_n=0) for s in extracted["seats"]]
        extracted["adversary_rejects"] = 0
        return extracted

    narrative.persist_panel_result = no_ir
    out = runner.run_panel(risk_store, cfg, SilentEngine(), job,
                           narrative_mod=narrative, registry_mod=fake_registry(recorder))

    assert out["status"] == "done"
    assert out["coverage"] == {"done_weak": 5}                     # used_tool=false · cited_refs=∅
    assert set(out["quality_flags"]) == {"low_tool_use", "low_ir_cite", "adversary_silent"}


def test_run_panel_engine_error_returns_seats_to_pending(risk_store, tmp_path):
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    job = runner.claim_next_job(risk_store, cfg)

    recorder: dict = {}
    engine = FakePanelEngine(raise_error=runner.EngineError("연결 끊김"))
    out = runner.run_panel(risk_store, cfg, engine, job,
                           narrative_mod=fake_narrative(recorder), registry_mod=fake_registry(recorder))

    assert out["status"] == "error" and "연결 끊김" in out["error"]
    panel = risk_store.query_one(
        "SELECT status, retry, error, seats_json, ended_at FROM rr_panels WHERE id = ?", (out["panel_id"],)
    )
    assert (panel["status"], panel["retry"]) == ("error", 1)
    rows = coverage(risk_store, target_key)
    assert {r["status"] for r in rows.values()} == {"pending"}
    # 그 패널 좌석만 retry 가 올랐고 panel_id 는 지워졌다.
    for seat in json.loads(panel["seats_json"]):
        assert (rows[seat["key"]]["retry"], rows[seat["key"]]["panel_id"]) == (1, None)
    assert "merge_panel" not in recorder


def test_run_panel_without_pending_completes_job(risk_store, tmp_path):
    target_key = seeded(risk_store, {"mech": 1})
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    job = runner.claim_next_job(risk_store, cfg)
    risk_store.execute(
        "UPDATE rr_coverage SET status = 'skipped', reason = '사용자' WHERE target_key = ?", (target_key,)
    )

    recorder: dict = {}
    out = runner.run_panel(risk_store, cfg, FakePanelEngine(), job,
                           narrative_mod=fake_narrative(recorder), registry_mod=fake_registry(recorder))
    assert out["panel_id"] is None and out["status"] == "no_panel"
    assert out["job_state"] == "completed" and out["next_job"] is None
    assert risk_store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"] == "completed"


def test_run_panel_pauses_the_job_when_returns_diminish(risk_store, tmp_path):
    """최근 DIMINISHING_WINDOW 패널의 new_clusters 가 0 이고 C1 이상이면 잡이 수확 체감으로 멈춘다(plan §0.9 P4-11)."""
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    job = runner.claim_next_job(risk_store, cfg)

    now = now_epoch()
    for offset in range(runner.DIMINISHING_WINDOW):
        risk_store.execute(
            "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, seats_json, status, quality_json,"
            " created_at) VALUES (?, ?, ?, ?, '[]', 'done', ?, ?)",
            (f"old-{offset}", target_key, OWNER, 90 + offset, json.dumps({"new_clusters": 0}), now),
        )

    recorder: dict = {}
    out = runner.run_panel(risk_store, cfg, FakePanelEngine(), job,
                           narrative_mod=fake_narrative(recorder),
                           registry_mod=fake_registry(recorder, level="C1", new_clusters=0))

    assert out["status"] == "done"
    row = risk_store.query_one("SELECT state, pause_reason FROM rr_jobs WHERE id = ?", (job_id,))
    assert (row["state"], row["pause_reason"]) == ("paused", "diminishing")


def test_recover_running_panels_after_restart(risk_store, tmp_path):
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    runner.claim_next_job(risk_store, cfg)
    panel = planner.plan_next_panel(risk_store, target_key, "A", settings=cfg)
    planner.start_panel_seats(risk_store, panel["id"])

    assert runner.recover_running_panels(risk_store) == {"recovered": 1}
    row = risk_store.query_one("SELECT status, error, retry FROM rr_panels WHERE id = ?", (panel["id"],))
    assert (row["status"], row["error"], row["retry"]) == ("error", "restart", 1)
    assert {r["status"] for r in coverage(risk_store, target_key).values()} == {"pending"}
    assert risk_store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"] == "queued"


# ---------------------------------------------------------------- 모델 출처 스냅샷(plan §6.7.2 1단계 · §0.9 P1-13)
class HealthEngine:
    """health() 응답만 갈아 끼우는 엔진 대역. 예외를 넣으면 /health 불통을 흉내 낸다."""

    def __init__(self, info: dict | None = None, *, raise_error: Exception | None = None) -> None:
        self._info = info
        self._raise = raise_error

    def health(self) -> dict:
        if self._raise is not None:
            raise self._raise
        return dict(self._info or {})


HEALTH_FIXTURES = {
    "정상": {
        "runtime": "agent-server", "provider": "vllm", "model": "glm-4.6",
        "endpoint_host": "h", "captured": "health_snapshot", "engine_rev": "e1", "chair_rev": "c9f1",
    },
    "변경": {
        "runtime": "agent-server", "provider": "vllm", "model": "glm-4.6-turbo",
        "endpoint_host": "h2", "captured": "health_snapshot", "engine_rev": "e2", "chair_rev": "c9f1",
    },
}


@pytest.mark.parametrize("case", list(HEALTH_FIXTURES))
def test_snapshot_model_records_the_engine_health(case):
    expect = HEALTH_FIXTURES[case]
    engine = HealthEngine({"provider": expect["provider"], "model": expect["model"],
                           "endpoint_host": expect["endpoint_host"], "engine_rev": expect["engine_rev"],
                           "chair_rev": expect["chair_rev"]})
    model = runner.snapshot_model(engine)
    for key in ("runtime", "provider", "model", "endpoint_host", "captured", "engine_rev", "chair_rev"):
        assert model[key] == expect[key], key
    assert model["seat_contract_rev"] == runner.seat_contract_rev()


def test_snapshot_model_is_unavailable_when_health_fails_or_is_missing():
    """불통·미노출 둘 다 예외 없이 captured='unavailable'·model='unknown' 이다."""
    down = runner.snapshot_model(HealthEngine(raise_error=RuntimeError("connect error")))
    assert down["captured"] == "unavailable" and down["model"] == "unknown"
    assert down["seat_contract_rev"] == runner.seat_contract_rev()

    class NoHealth:
        pass

    absent = runner.snapshot_model(NoHealth())
    assert absent["captured"] == "unavailable" and absent["model"] == "unknown"


def test_snapshot_model_leaves_chair_rev_null_when_the_engine_does_not_report_it():
    model = runner.snapshot_model(HealthEngine({"model": "glm-4.6"}))
    assert model["chair_rev"] is None and model["captured"] == "health_snapshot"


# ---------------------------------------------------------------- 패널 실행 원문·브리프 동결(plan §0.9 P3-19)
def test_panel_calls_and_frozen_brief_are_the_app_record(risk_store, tmp_path):
    """좌석 도구 호출은 rr_panel_calls 에 seq 순으로 남고, 브리프는 동결본이 그대로 나온다."""
    import gzip

    from app.common import sha256_hex

    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    job = runner.claim_next_job(risk_store, cfg)

    recorder: dict = {}
    engine = FakePanelEngine()
    out = runner.run_panel(risk_store, cfg, engine, job,
                           narrative_mod=fake_narrative(recorder), registry_mod=fake_registry(recorder))
    panel_id = out["panel_id"]

    calls = risk_store.query(
        "SELECT call_id, seq, agent_key, tool, source, result_gz, sha256 FROM rr_panel_calls"
        " WHERE panel_id = ? ORDER BY seq", (panel_id,))
    seats = json.loads(risk_store.query_one(
        "SELECT seats_json FROM rr_panels WHERE id = ?", (panel_id,))["seats_json"])
    # 좌석마다 status→evidence 한 쌍 + 공용 evidence + 브리프 항목 수만큼 기록된다.
    assert len(calls) >= len(seats)
    assert [c["seq"] for c in calls] == list(range(1, len(calls) + 1))
    assert all(c["call_id"] == f"{panel_id[:8]}-{c['seq']:03d}" for c in calls)
    assert all(c["source"] == "sse" for c in calls)
    with_text = [c for c in calls if c["result_gz"] is not None]
    assert with_text and all(
        sha256_hex(gzip.decompress(c["result_gz"]).decode("utf-8")) == c["sha256"] for c in with_text)

    frozen = runner.load_brief(risk_store, panel_id)
    assert frozen["evidence"] == engine.calls[0]["evidence"]
    assert frozen["brief_hash"] and frozen["item_hashes"]
    row = risk_store.query_one("SELECT brief_hash, brief_gz FROM rr_panels WHERE id = ?", (panel_id,))
    assert row["brief_hash"] == frozen["brief_hash"] and row["brief_gz"] is not None


def test_second_panel_reports_only_the_changed_brief_keys(risk_store):
    """같은 타깃의 두 번째 패널은 실제로 달라진 항목 키만 brief_drift 로 남긴다."""
    target_key = seeded(risk_store)
    now = now_epoch()
    panels = []
    for no in (1, 2):
        panel_id = f"pan{no}"
        risk_store.execute(
            "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, seats_json, status, created_at)"
            " VALUES (?, ?, ?, ?, '[]', 'planned', ?)", (panel_id, target_key, OWNER, no, now))
        panels.append({"id": panel_id, "target_key": target_key, "owner_sub": OWNER})

    evidence = [{"source": "rr_state", "tool": "gates", "args": target_key, "result": "G1 pass"},
                {"source": "rr_diff", "tool": "summary", "args": target_key, "result": "변경 3건"}]
    first = runner.freeze_brief(risk_store, panels[0], evidence)
    assert first["brief_drift"] == []                    # 앞 패널이 없으면 비교 대상도 없다

    changed = [{**evidence[0], "result": "G1 fail"}, evidence[1]]
    second = runner.freeze_brief(risk_store, panels[1], changed)
    assert second["brief_drift"] == ["rr_state"]         # 달라진 항목 키만 실린다
    assert second["brief_hash"] != first["brief_hash"]
    assert runner.load_brief(risk_store, "pan2")["evidence"] == changed


def test_item_keys_alone_are_not_brief_drift(risk_store):
    """항목에 키(E0·E1 …)가 붙기 전에 동결한 패널과 견줘도, 내용이 같으면 달라진 항목은 없다.

    키는 항목의 이름표이지 내용이 아니다 — 해시에 넣으면 키를 싣기 시작한 뒤 첫 패널이 전 항목을 drift 로 적는다.
    """
    target_key = seeded(risk_store)
    now = now_epoch()
    panels = []
    for no in (1, 2, 3):
        panel_id = f"pan{no}"
        risk_store.execute(
            "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, seats_json, status, created_at)"
            " VALUES (?, ?, ?, ?, '[]', 'planned', ?)", (panel_id, target_key, OWNER, no, now))
        panels.append({"id": panel_id, "target_key": target_key, "owner_sub": OWNER})

    before = [{"source": "rr_scope", "tool": "rr_targets", "args": target_key, "result": "G1 pass"},
              {"source": "rr_diff", "tool": "summary_text", "args": target_key, "result": "변경 3건"}]
    runner.freeze_brief(risk_store, panels[0], before)

    keyed = [{**before[0], "key": "E0"}, {**before[1], "key": "E1"}]
    assert runner.freeze_brief(risk_store, panels[1], keyed)["brief_drift"] == []
    # 동결본에는 키가 그대로 남는다 — 패널이 실제로 받은 것이 정본이다.
    assert runner.load_brief(risk_store, "pan2")["evidence"] == keyed

    moved = [{**keyed[0], "result": "G1 fail"}, keyed[1]]
    assert runner.freeze_brief(risk_store, panels[2], moved)["brief_drift"] == ["rr_scope"]
