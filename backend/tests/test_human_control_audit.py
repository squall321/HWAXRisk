# 사람이 심사의 길을 바꾸는 조작 셋(잡 제어 · 등록부 status · verdict 확정)이 rr_audit 에 남는지 — 사용자 결정 10-31(plan §8.2.3)
"""정본 plan §8.2.3 은 잡 제어(`POST /jobs/{id}/pause|resume|cancel`) · 등록부 status(`PUT /registry/{cluster}/status`) · verdict 확정
(`PUT /targets/{key}/verdict`)을 감사하라 하는데 종전 코드는 주체를 각 표(rr_jobs.state_by · rr_registry_status_log · rr_targets.verdict_by)에만
적었다 — 대상 감사(`GET /targets/{key}/audit`)와 통합 보고서 minutes 의 '사람 개입 요약' 에는 셋이 늘 없었다(context-notes BL-4). 사용자 결정
10-31 로 셋을 남긴다.

- 행위자는 부른 사람이다 — owner_sub · actor 둘 다(다른 감사 행과 같다, `routes._audit`). 입구는 신원 출처(쿠키 web · Bearer rest · 게이트웨이
  위임 mcp — mcp 는 actor_verified 0).
- 자리는 `registry.target_audit_clause` 가 그 대상의 것으로 고르는 꼴이다 — 잡은 scope job · 잡 id, 등록부는 scope registry ·
  '<대상>#<클러스터>', verdict 는 scope target · 대상 열쇠. 셋 다 그 대상의 과제 id 를 싣는다(과제 감사에도 선다).
- 행에는 코드 어휘(잡 상태 · 보류 코드 · 등록부 status · 상태 기록 seq · 판정 값)만 싣는다. 사람이 쓴 글(등록부 note · evidence_ref,
  verdict note)은 싣지 않는다 — 그 글은 원래 자리(상태 기록 · 대상 행)에 그대로 있다.
- 코드가 일으킨 전이(일일 상한 · 집기 · 취소의 마감 · 코드 보류 · 엔진 쪽 멈춤 A24)는 사람 행위가 아니라 남기지 않는다 — 코드의 정지 ·
  보류는 잡 행의 state_by 에 'code:…' 를 적고, 집기 · 취소의 마감은 주체를 적지 않는다(state_by 는 앞 값 그대로).
"""
from __future__ import annotations

import asyncio
import dataclasses
import json

import pytest

import app.mcp_server as srv
from app import config, registry, routes, runner
from app.common import now_epoch
from app.errors import AppError
from tests import factories
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.test_project_patch import _human_body
from tests.test_wiring_regressions import OTHER, OWNER, _portal_engine, _seed, _sse

TARGET = "diff:d1"
CONTROL = ("job.pause", "job.resume", "job.cancel")
# 사람이 쓴 글의 표지 — 상태 기록 · 대상 행에는 남고 감사 행에는 어디에도 실리지 않아야 한다.
NOTE = "자유글 표지 note-7f3a — 사람이 쓴 메모"
EVIDENCE = "rpt:자유글-표지-e9c1"


def _ident(email: str = OWNER, *, source: str = "bearer"):
    return dataclasses.replace(factories.ident(email), source=source)


def _call(name: str, /, **kwargs) -> dict:
    out = getattr(srv, name)(**kwargs)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def _rows(store, *actions: str) -> list[dict]:
    """그 action 들의 감사 행 — 적힌 차례."""
    marks = ",".join("?" * len(actions))
    out = []
    for row in store.query("SELECT owner_sub, actor, actor_verified, channel, scope, subject_id, project_id, action,"
                           f" before_json, after_json, reason FROM rr_audit WHERE action IN ({marks}) ORDER BY at, rowid",
                           actions):
        item = dict(row)
        item["before"], item["after"] = json.loads(item.pop("before_json")), json.loads(item.pop("after_json"))
        out.append(item)
    return out


def _audit_text(store) -> str:
    return json.dumps([dict(r) for r in store.query("SELECT * FROM rr_audit")], ensure_ascii=False)


def _summary(store, target_key: str) -> list[str]:
    """통합 보고서 minutes 의 '[사람 개입 요약]' 줄."""
    lines = "\n".join(registry.build_report(store, target_key)["blocks"]["minutes"]).split("\n")
    start = lines.index("[사람 개입 요약]") + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("[")), len(lines))
    return lines[start:end]


def _job(store, job_id: str) -> dict:
    return dict(store.query_one("SELECT state, state_by, hold_code FROM rr_jobs WHERE id = ?", (job_id,)))


def _panel_job(target_key: str) -> str:
    return routes.create_job(target_key, routes.JobBody(tier="B"), ident=_ident())["job_id"]


@pytest.fixture
def seeded(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    return risk_store, _seed(risk_store)


# ---------------------------------------------------------------- 잡 제어
def test_pause_resume_cancel_each_leave_one_row_that_the_target_audit_and_the_summary_count(seeded):
    """조작마다 rr_audit(scope job · 그 잡 id · 그 과제) 한 행 — 행위자는 부른 사람, 입구는 신원 출처, 앞 · 뒤는 잡 상태와 보류 코드뿐이다.
    그 대상의 감사와 보고서 '사람 개입 요약' 이 세 줄을 센다(종전에는 rr_jobs.state_by 에만 남아 둘 다 비었다)."""
    store, target_key = seeded
    job_id = _panel_job(target_key)

    assert routes.job_action(job_id, "pause", ident=_ident(source="cookie"))["state"] == "paused"
    assert routes.job_action(job_id, "resume", ident=_ident())["state"] == "queued"
    assert routes.job_action(job_id, "cancel", ident=_ident())["state"] == "cancelled"

    rows = _rows(store, *CONTROL)
    assert [(r["action"], r["channel"], r["before"], r["after"]) for r in rows] == [
        ("job.pause", "web", {"state": "queued", "hold_code": None}, {"state": "paused", "hold_code": None}),
        ("job.resume", "rest", {"state": "paused", "hold_code": None}, {"state": "queued", "hold_code": None}),
        ("job.cancel", "rest", {"state": "queued", "hold_code": None}, {"state": "cancelled", "hold_code": None})]
    assert {(r["owner_sub"], r["actor"], r["actor_verified"], r["scope"], r["subject_id"], r["project_id"], r["reason"])
            for r in rows} == {(OWNER, OWNER, 1, "job", job_id, "p1", None)}
    entries = routes.get_target_audit(target_key, ident=_ident())["entries"]
    assert sorted(e["action"] for e in entries) == sorted(CONTROL)
    assert _summary(store, target_key) == ["job.cancel=1", "job.pause=1", "job.resume=1"]


def test_refused_or_idle_job_control_leaves_no_row(seeded):
    """바꾼 것이 없는 조작(끝난 잡의 취소)과 거절된 조작(멈출 수 없는 상태 409 · 남의 잡 404 · 모르는 조작 404)은 행을 남기지 않는다."""
    store, target_key = seeded
    job_id = _panel_job(target_key)
    routes.job_action(job_id, "cancel", ident=_ident())
    assert len(_rows(store, *CONTROL)) == 1

    assert routes.job_action(job_id, "cancel", ident=_ident())["state"] == "cancelled"
    for action, ident, status in (("pause", _ident(), 409), ("resume", _ident(), 409), ("cancel", _ident(OTHER), 404),
                                  ("stop", _ident(), 404)):
        with pytest.raises(AppError) as refused:
            routes.job_action(job_id, action, ident=ident)
        assert refused.value.http_status == status, action
    assert len(_rows(store, *CONTROL)) == 1


def test_mcp_job_control_is_an_unverified_mcp_actor_and_a_repeat_writes_nothing(seeded, monkeypatch):
    """MCP risk_job_action 은 같은 라우트 함수다 — 게이트웨이 위임 신원이 행위자이고 입구는 mcp · actor_verified 0 이다(MCP 길의 감사 행과
    같다). 이미 그 상태인 조작(changed:false)은 아무것도 바꾸지 않아 행이 없다."""
    store, target_key = seeded
    job_id = _panel_job(target_key)
    factories.act_as_delegate(monkeypatch, OWNER)

    first = _call("risk_job_action", job_id=job_id, action="pause")
    again = _call("risk_job_action", job_id=job_id, action="pause")

    assert (first["changed"], again["changed"]) == (True, False)
    (row,) = _rows(store, *CONTROL)
    assert (row["action"], row["actor"], row["owner_sub"], row["channel"], row["actor_verified"]) == (
        "job.pause", OWNER, OWNER, "mcp", 0)


def test_a_review_jobs_rows_carry_the_hold_a_person_puts_or_clears(risk_store, monkeypatch, tmp_path):
    """검토 잡 — 코드가 건 보류(LLM 장애)는 사람 행위가 아니라 행이 없다. 그 위에 사람이 멈추면 상태는 paused 그대로이고 보류 코드만 user 로
    덮는다(자동 재개가 다시 세우지 않는다 — P-10) — 그것도 사람의 정지라 한 행이다. 재개는 보류를 비우고, 취소는 제 트랜잭션 밖에서 전문가
    보고서를 다시 짓는 길(M3C-81)이어도 한 행이다."""
    rig.configure(monkeypatch, risk_store, tmp_path)
    key = rig.target(risk_store)
    job_id = rig.job(risk_store, key)
    loop = rig.Rig(risk_store, FakeReviewEngine(rig.packs())).loop
    assert loop.hold(job_id, "llm_outage", "LLM 이 닿지 않는다(시험)")
    assert _job(risk_store, job_id)["state_by"] == "code:llm_outage" and _rows(risk_store, *CONTROL) == []
    me = factories.ident(rig.OWNER)

    routes.job_action(job_id, "pause", ident=me)
    routes.job_action(job_id, "resume", ident=me)
    assert routes.job_action(job_id, "cancel", ident=me)["state"] == "cancelled"

    rows = _rows(risk_store, *CONTROL)
    assert [(r["action"], r["before"], r["after"]) for r in rows] == [
        ("job.pause", {"state": "paused", "hold_code": "llm_outage"}, {"state": "paused", "hold_code": "user"}),
        ("job.resume", {"state": "paused", "hold_code": "user"}, {"state": "queued", "hold_code": None}),
        ("job.cancel", {"state": "queued", "hold_code": None}, {"state": "cancelled", "hold_code": None})]
    assert {(r["subject_id"], r["actor"], r["channel"]) for r in rows} == {(job_id, rig.OWNER, "rest")}
    counts = registry.target_audit_counts(risk_store, key)
    assert {action: counts.get(action) for action in CONTROL} == {action: 1 for action in CONTROL}


def test_cancelling_a_review_job_again_while_its_call_is_in_flight_writes_no_second_row(risk_store, monkeypatch, tmp_path):
    """도는 호출이 있는 검토 잡의 취소는 cancelling 으로 기다린다(R3A-1). 그동안 다시 취소하면 러너는 같은 전이를 다시 쓸 뿐 잡의 상태 ·
    보류는 그대로라 행이 없다 — 행은 사람이 잡을 바꾼 조작마다다."""
    rig.configure(monkeypatch, risk_store, tmp_path)
    key = rig.target(risk_store)
    job_id = rig.job(risk_store, key, scope={"agents": [rig.SEAL]})
    # 워커가 그 잡의 전문가 머리를 쥐고 호출 중이다(루프가 세우는 상태 — test_review_loop 의 cancelling 시험과 같은 자리)
    risk_store.execute("UPDATE rr_expert_reports SET state = 'running', lease_owner = 'worker' WHERE target_key = ?"
                       " AND agent_key = ?", (key, rig.SEAL))
    me = factories.ident(rig.OWNER)

    assert routes.job_action(job_id, "cancel", ident=me)["state"] == "cancelling"
    assert routes.job_action(job_id, "cancel", ident=me)["state"] == "cancelling"

    assert [(r["action"], r["before"], r["after"]) for r in _rows(risk_store, *CONTROL)] == [
        ("job.cancel", {"state": "queued", "hold_code": None}, {"state": "cancelling", "hold_code": None})]


def test_a_cancel_that_finds_the_job_already_finished_writes_nothing(seeded, monkeypatch):
    """확인과 취소 사이에 러너가 잡을 끝냈으면(completed) 취소는 아무것도 쓰지 않는다 — 앞(queued)과 뒤(completed)가 달라도 사람이 바꾼
    것이 아니라 행이 없다(러너가 쓴 전이만 센다 — 결과의 state_at)."""
    store, target_key = seeded
    job_id = _panel_job(target_key)
    real = runner.cancel_job

    def finished_first(store_, job_id_, **kwargs):
        runner._set_job(store_, job_id_, "completed")          # 루프가 마지막 패널을 닫았다
        return real(store_, job_id_, **kwargs)

    monkeypatch.setitem(routes.JOB_ACTIONS, "cancel", finished_first)
    assert routes.job_action(job_id, "cancel", ident=_ident())["state"] == "completed"
    assert _rows(store, *CONTROL) == []


def test_runner_transitions_are_not_human_actions_and_leave_no_row(seeded, tmp_path):
    """코드가 일으킨 전이는 감사하지 않는다(rr_audit 는 사람 행위 한정 — plan §0.6). 일일 상한 정지 · 집기(queued → running) · 사람이 건
    취소의 마감(cancelling → cancelled) · 엔진 쪽 멈춤(A24 — 포털 화면에서 사람이 심의를 멈춰도 잡을 멈추는 것은 러너의 반응이고 state_by 는
    code:cancelled 다)이 그렇다. 사람의 재개 · 취소만 한 행씩이다."""
    store, target_key = seeded
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = _panel_job(target_key)

    assert runner.claim_next_job(store, dataclasses.replace(cfg, risk_daily_panel_cap=0)) is None
    assert _job(store, job_id)["state"] == "paused"                                   # 코드 — 일일 상한
    routes.job_action(job_id, "resume", ident=_ident())                               # 사람
    assert runner.claim_next_job(store, cfg)["id"] == job_id                          # 코드 — 집기
    assert routes.job_action(job_id, "cancel", ident=_ident())["state"] == "cancelling"   # 사람
    assert runner.claim_next_job(store, cfg) is None                                  # 코드 — 취소의 마감
    assert _job(store, job_id)["state"] == "cancelled"

    second = _panel_job(target_key)
    engine = _portal_engine(store, cfg, {}, _sse(
        ("delib", {"kind": "stage", "stage": "r1", "run_id": "0a1b2c3d4e5f6a7b"}),
        ("delib", {"kind": "cancelled", "by": OWNER, "run_id": "0a1b2c3d4e5f6a7b", "message": "사람이 멈췄다(시험)"}),
        ("done", {})))
    out = runner.run_panel(store, cfg, engine, runner.claim_next_job(store, cfg))
    assert out["status"] == "error" and _job(store, second) == {"state": "paused", "state_by": "code:cancelled",
                                                                "hold_code": None}

    rows = _rows(store, *CONTROL)
    assert [(r["action"], r["subject_id"], r["before"]["state"], r["after"]["state"]) for r in rows] == [
        ("job.resume", job_id, "paused", "queued"), ("job.cancel", job_id, "running", "cancelling")]


# ---------------------------------------------------------------- 등록부 status
def _shared_cluster(store) -> str:
    """같은 클러스터 열쇠의 사람 finding 셋 — 내 대상 둘(diff:d1 · snap:mine2)과 남의 대상 하나(snap:z9). 웹 폼 꼴(코드 · 대상 없음)이라
    cluster_key 에 대상이 없다(test_target_audit 의 BL-8 시험과 같은 원장)."""
    _seed(store, owner=OWNER)
    now = now_epoch()
    for project_id, owner, target_key in (("p2", OTHER, "snap:z9"), ("p3", OWNER, "snap:mine2")):
        store.execute("INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
                      " VALUES (?, ?, ?, '과제', ?, ?)", (project_id, owner, f"PRJ-{project_id}", now, now))
        store.execute("INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, external_sync_json,"
                      " report_ids_json, level, created_at, updated_at) VALUES (?, ?, 'snap', ?, ?, 'h', '{}', '[]', 'C0', ?, ?)",
                      (target_key, owner, target_key.split(":", 1)[1], project_id, now, now))
    body = _human_body(mechanism="thermal.cte_mismatch", mechanism_detail=None, change_kind=None, subject_key=None)
    keys = {routes.create_human_finding(target_key, body, ident=_ident(who))["cluster_key"]
            for target_key, who in ((TARGET, OWNER), ("snap:z9", OTHER), ("snap:mine2", OWNER))}
    assert len(keys) == 1
    return keys.pop()


def test_registry_status_leaves_one_row_per_changed_row_on_that_target_without_the_written_text(risk_store, monkeypatch):
    """바뀐 (대상, 클러스터) 행마다 rr_audit(scope registry · '<대상>#<클러스터>' · 그 대상의 과제) 한 행 — 앞 · 뒤는 status 와 상태 기록 seq
    뿐이고 사람이 쓴 note · evidence_ref 는 싣지 않는다(상태 기록에 그대로 있다). 대상을 고르지 않은 전이는 그 열쇠의 내 행 전부를 바꾸므로
    내 대상마다 한 행이고, 남의 같은 열쇠 행과 남의 대상 감사에는 닿지 않는다(BL-8 과 같은 규칙)."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    store = risk_store
    key = _shared_cluster(store)

    routes.put_registry_status(key, routes.RegistryStatusBody(status="mitigated", note=NOTE, target_key=TARGET),
                               ident=_ident(source="cookie"))
    routes.put_registry_status(key, routes.RegistryStatusBody(status="verified", evidence_ref=EVIDENCE, note=NOTE),
                               ident=_ident())
    routes.put_registry_status(key, routes.RegistryStatusBody(status="dismissed", evidence_ref=EVIDENCE),
                               ident=_ident(OTHER))
    with pytest.raises(AppError) as refused:
        routes.put_registry_status(key, routes.RegistryStatusBody(status="verified"), ident=_ident())
    assert refused.value.code == "evidence_required"

    rows = _rows(store, "registry.status")
    assert [(r["actor"], r["subject_id"], r["project_id"], r["channel"], r["before"], r["after"]) for r in rows] == [
        (OWNER, f"{TARGET}#{key}", "p1", "web", {"status": "open"}, {"status": "mitigated", "status_log_seq": 1}),
        (OWNER, f"{TARGET}#{key}", "p1", "rest", {"status": "mitigated"}, {"status": "verified", "status_log_seq": 2}),
        (OWNER, f"snap:mine2#{key}", "p3", "rest", {"status": "open"}, {"status": "verified", "status_log_seq": 1}),
        (OTHER, f"snap:z9#{key}", "p2", "rest", {"status": "open"}, {"status": "dismissed", "status_log_seq": 1})]
    assert {(r["owner_sub"] == r["actor"], r["scope"], r["actor_verified"], r["reason"]) for r in rows} == {
        (True, "registry", 1, None)}
    # 사람이 쓴 글은 감사 행 어디에도 없고 원래 자리(상태 기록)에 그대로 있다.
    assert NOTE not in _audit_text(store) and EVIDENCE not in _audit_text(store)
    logged = store.query_one("SELECT note, evidence_ref FROM rr_registry_status_log WHERE target_key = ? AND seq = 2",
                             (TARGET,))
    assert (logged["note"], logged["evidence_ref"]) == (NOTE, EVIDENCE)

    def seen(target_key: str, who: str) -> list[tuple[str, str]]:
        return sorted((e["action"], e["actor"]) for e in routes.get_target_audit(target_key, ident=_ident(who))["entries"])

    assert seen(TARGET, OWNER) == [("finding.create", OWNER), ("registry.status", OWNER), ("registry.status", OWNER)]
    assert seen("snap:mine2", OWNER) == [("finding.create", OWNER), ("registry.status", OWNER)]
    assert seen("snap:z9", OTHER) == [("finding.create", OTHER), ("registry.status", OTHER)]
    assert _summary(store, TARGET) == ["finding.create=1", "registry.status=2"]
    assert [e["subject_id"] for e in routes.get_project_audit("p1", action="registry.status", ident=_ident())["entries"]] \
        == [f"{TARGET}#{key}"] * 2


# ---------------------------------------------------------------- verdict 확정
def test_each_verdict_confirmation_leaves_a_row_without_the_note(seeded):
    """확정마다 rr_audit(scope target · 대상 열쇠 · 그 과제) 한 행 — 앞 · 뒤는 판정 값뿐이고 메모는 싣지 않는다(rr_targets.verdict_note 에
    있다). 같은 값으로 다시 확정해도 사람의 확정이라 한 행이다(확정한 사람 · 시각이 다시 찍힌다). 어휘 밖(422)과 남의 대상(404)은 아무것도
    쓰지 않는다."""
    store, target_key = seeded

    routes.put_verdict(target_key, routes.VerdictBody(verdict="go", note=NOTE), ident=_ident(source="cookie"))
    routes.put_verdict(target_key, routes.VerdictBody(verdict="conditional", note=NOTE), ident=_ident())
    routes.put_verdict(target_key, routes.VerdictBody(verdict="conditional"), ident=_ident())
    for verdict, ident, status in (("maybe", _ident(), 422), ("no-go", _ident(OTHER), 404)):
        with pytest.raises(AppError) as refused:
            routes.put_verdict(target_key, routes.VerdictBody(verdict=verdict, note=NOTE), ident=ident)
        assert refused.value.http_status == status, verdict

    rows = _rows(store, "verdict.final")
    assert [(r["channel"], r["before"], r["after"]) for r in rows] == [
        ("web", {"verdict_final": None}, {"verdict_final": "go"}),
        ("rest", {"verdict_final": "go"}, {"verdict_final": "conditional"}),
        ("rest", {"verdict_final": "conditional"}, {"verdict_final": "conditional"})]
    assert {(r["owner_sub"], r["actor"], r["actor_verified"], r["scope"], r["subject_id"], r["project_id"], r["reason"])
            for r in rows} == {(OWNER, OWNER, 1, "target", target_key, "p1", None)}
    assert NOTE not in _audit_text(store)
    assert [e["action"] for e in routes.get_target_audit(target_key, ident=_ident())["entries"]] == ["verdict.final"] * 3
    assert _summary(store, target_key) == ["verdict.final=3"]
