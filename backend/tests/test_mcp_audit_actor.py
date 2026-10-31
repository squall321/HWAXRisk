# MCP 도구가 남기는 감사 행은 전부 입구 mcp · actor_verified 0 인지 — 게이트웨이 위임 신원은 앱이 확인한 신원이 아니다(사용자 결정 10-31)
"""DDL 의 rr_audit.actor_verified 는 'MCP 경로의 actor 는 0'(plan §6.11)이고 입구는 신원 출처에서 정한다(`routes.AUDIT_CHANNELS` — 쿠키
web · Bearer rest · 게이트웨이 위임 mcp). 잡 제어 · 보류 풀기 · 셀 처분 행은 그렇게 적었는데, 같은 MCP 입구의 다른 쓰기는 입구만 적고
행위자 검증을 빠뜨리거나(잡 만들기 · 브리프 제외 · 방식 바꾸기 · ECAD 보드) 둘 다 기본값(rest · 1)으로 적었다(게이트 ack · 사람 finding ·
패널 다시 저장 · 포기 · same-as reject 의 키 전파). 사람 조작 감사 작업이 남긴 줄(context-notes AU-7 'MCP 로 만든 잡의 job.create 는
actor_verified 1') — 사용자 결정 10-31 로 고친다.

MCP 쓰기 도구마다 그 도구를 위임 신원으로 불러 남은 행이 (mcp, 0) 인지, 같은 조작을 웹(쿠키) · REST(Bearer)로 하면 (web, 1) · (rest, 1)
인지 본다 — 모든 행을 0 으로 적는 고침이 지나가지 않게.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

import app.mcp_server as srv
from app import ir_builder, routes, runner, sameas
from tests import factories
from tests import test_ecad_person_pat as ecad
from tests import test_external_llm_jobs as external
from tests import test_rekey
from tests.synth import review_rig as rig
from tests.test_gate_ack import _gates, _seed_snapshot

OWNER = factories.OWNER
# ECAD 시험대(게이트웨이 대역 한 곳 — 찾기 · 붙이기 확인이 그 사람의 PAT 로 간다). 픽스처 이름은 이 모듈의 이름이다.
ecad_box = ecad.box


def _call(name: str, /, **kwargs) -> dict:
    out = getattr(srv, name)(**kwargs)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def _web(email: str = OWNER):
    """웹 화면의 신원(쿠키)."""
    return dataclasses.replace(factories.ident(email), source="cookie")


def _rows(store, *actions: str) -> list[tuple]:
    """그 action 들의 감사 행(action, 입구, 행위자 검증, 행위자) — 적힌 차례."""
    marks = ",".join("?" * len(actions))
    return [(r["action"], r["channel"], r["actor_verified"], r["actor"]) for r in store.query(
        "SELECT action, channel, actor_verified, actor FROM rr_audit"
        f" WHERE action IN ({marks}) ORDER BY at, rowid", actions)]


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def test_jobs_made_through_mcp_write_unverified_mcp_rows(store, monkeypatch):
    """risk_start_job — 검토 잡 · Claude 패널 잡의 job.create 와 브리프 제외의 brief.exclude 는 (mcp, 0) 이다(같은 입구의 잡 제어 · 보류
    풀기 행과 같다). 같은 잡을 REST 로 만들면 (rest, 1) 이다."""
    rig.pat(store)
    external._probe(monkeypatch, external._external_fake())
    cells = rig.target(store)
    panels = factories.make_diff_target(store, 3).target_key
    factories.act_as_delegate(monkeypatch, OWNER)

    review = _call("risk_start_job", target_key=cells, mode="reviews", scope={"agents": [rig.SEAL]}, consent=True)
    claude = _call("risk_start_job", target_key=panels, tier="A", llm="claude", consent_external=True,
                   exclude_evidence=["E7"])
    assert review["created"] is True and claude["created"] is True and claude["llm"] == "claude", (review, claude)
    routes.create_job(panels, routes.JobBody(tier="B", llm="claude", consent_external=True, exclude_evidence=["E6"]),
                      ident=factories.ident(OWNER))

    assert _rows(store, "job.create", "brief.exclude") == [
        ("job.create", "mcp", 0, OWNER), ("brief.exclude", "mcp", 0, OWNER), ("job.create", "mcp", 0, OWNER),
        ("brief.exclude", "rest", 1, OWNER), ("job.create", "rest", 1, OWNER)]


def test_a_flow_switch_through_mcp_writes_an_unverified_mcp_row(store, monkeypatch):
    """risk_open_target(flow=…) 가 연 대상의 방식을 바꾸면 target.flow 는 (mcp, 0) 이다 — 웹에서 되돌리면 (web, 1)."""
    synth = factories.make_diff_target(store, 3)
    factories.act_as_delegate(monkeypatch, OWNER)

    switched = _call("risk_open_target", kind="diff", ref_id=synth.diff_id, consent=True, flow="cells", reason="파일럿")
    assert switched["flow_change"]["changed"] is True, switched
    routes.post_target_flow(synth.target_key, routes.FlowBody(to="panels", reason="되돌림"), ident=_web())

    assert _rows(store, "target.flow") == [("target.flow", "mcp", 0, OWNER), ("target.flow", "web", 1, OWNER)]


def test_an_ecad_board_set_through_mcp_writes_unverified_mcp_rows(ecad_box, monkeypatch):
    """risk_set_ecad_board 의 붙이기 · 떼기는 project.ecad_board (mcp, 0) 이다 — REST 로 다시 붙이면 (rest, 1)."""
    ecad._register(ecad_box.store)
    project_id = ecad._project("AUDIT-ECAD")
    factories.act_as_delegate(monkeypatch, ecad.OWNER)

    assert _call("risk_set_ecad_board", project_id=project_id, odb_job_id=ecad.JOB_STD)["changed"] is True
    assert _call("risk_set_ecad_board", project_id=project_id, odb_job_id=None)["removed"] == 1
    routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id=ecad.JOB_STD), ident=ecad.WEB)

    assert _rows(ecad_box.store, "project.ecad_board") == [("project.ecad_board", "mcp", 0, ecad.OWNER)] * 2 + [
        ("project.ecad_board", "rest", 1, ecad.OWNER)]


def test_a_gate_ack_through_mcp_writes_an_unverified_mcp_row(store, monkeypatch):
    """risk_ack_gate 의 gate.ack 는 (mcp, 0) 이다 — 종전에는 입구도 검증도 기본값(rest · 1)이었다. 웹에서 붙인 ack 는 (web, 1)."""
    who = "owner@example.com"                       # test_gate_ack 시드의 스냅샷 주인
    fail = {"pass": False, "count": 2, "effect": "mark"}
    _seed_snapshot(store, "s1", _gates(G1=fail, G3=fail))
    factories.act_as_delegate(monkeypatch, who)

    assert _call("risk_ack_gate", snapshot_id="s1", gate="G3", reason="Claude 에서 확인함")["ack_by"] == who
    routes.post_gate_ack("s1", "G1", routes.GateAckBody(reason="웹에서 확인함"), ident=_web(who))

    assert _rows(store, "gate.ack") == [("gate.ack", "mcp", 0, who), ("gate.ack", "web", 1, who)]


def test_a_human_finding_added_through_mcp_writes_an_unverified_mcp_row(store, monkeypatch):
    """risk_add_finding 의 finding.create 는 (mcp, 0) 이다 — 작성자는 위임 신원이지만 앱이 확인한 신원은 아니다. REST 로 내면 (rest, 1)."""
    target_key = factories.make_diff_target(store, 3).target_key
    factories.act_as_delegate(monkeypatch, OWNER)
    finding = {"claim": "조립 시 간극이 부족해 보인다", "cites": [{"ref": "p:0123456789ab", "quote": "«PLATE_1»"}],
               "direction": "risk", "domain": "mech", "mechanism": "interface", "mechanism_detail": "clearance"}

    made = _call("risk_add_finding", target_key=target_key, actor="whoever@example.com", **finding)
    assert "error" not in made, made
    routes.create_human_finding(target_key, routes.HumanFindingBody(**finding), ident=factories.ident(OWNER))

    assert _rows(store, "finding.create") == [("finding.create", "mcp", 0, OWNER), ("finding.create", "rest", 1, OWNER)]


def test_a_repersist_and_its_discard_through_mcp_write_unverified_mcp_rows(store, monkeypatch):
    """risk_repersist_panel 의 다시 저장 · 포기는 panel.repersist · panel.repersist_discard (mcp, 0) 이다. 다시 앉히는 본체(러너)는 이
    시험의 몫이 아니라 대역이다 — 감사 행은 라우트가 러너의 답 뒤에 쓴다. 웹에서 하면 (web, 1)."""
    target_key = factories.make_diff_target(store, 3).target_key
    panel_id = factories.plan_panel(store, target_key, "A")["id"]
    monkeypatch.setattr(runner, "repersist_panel", lambda _store, _settings, pid: {
        "panel_id": pid, "status": "done", "level": "C1", "findings_n": 0})
    monkeypatch.setattr(runner, "abandon_repersist", lambda _store, pid: {
        "panel_id": pid, "status": "error", "error": "persist_abandoned: 시험", "abandoned": True})
    factories.act_as_delegate(monkeypatch, OWNER)

    assert _call("risk_repersist_panel", panel_id=panel_id)["status"] == "done"
    assert _call("risk_repersist_panel", panel_id=panel_id, discard=True)["abandoned"] is True
    routes.post_panel_repersist(panel_id, ident=_web())

    assert _rows(store, "panel.repersist", "panel.repersist_discard") == [
        ("panel.repersist", "mcp", 0, OWNER), ("panel.repersist_discard", "mcp", 0, OWNER),
        ("panel.repersist", "web", 1, OWNER)]


def test_a_same_as_reject_through_mcp_writes_an_unverified_mcp_rekey_row(store, monkeypatch):
    """risk_decide_sameas 가 확정을 reject 로 뒤집으면 키 전파(rekey.run)가 rr_audit(rekey) 한 행을 쓴다 — 그 행도 (mcp, 0) 이다(종전에는
    입구 rest · 검증 1 이 글자로 박혀 있었다). 웹에서 같은 뒤집기를 하면 (web, 1)."""
    synth = factories.make_diff_target(store, 3)
    base = ir_builder.load_ir(store, synth.base_snapshot_id)["nodes"]
    later = ir_builder.load_ir(store, synth.target_snapshot_id)["nodes"]
    first, second = ((sameas.stable_key(base[i]), sameas.stable_key(later[i])) for i in (0, 1))
    pair = {"base_snapshot_id": synth.base_snapshot_id, "target_snapshot_id": synth.target_snapshot_id}
    factories.act_as_delegate(monkeypatch, OWNER)

    for decision in ("confirm", "reject"):
        out = _call("risk_decide_sameas", **pair, decisions=[{"a_stable": first[0], "b_stable": first[1],
                                                               "decision": decision}])
        assert out.get("updated") == 1, out
    pair_key = f"{synth.project_id}|{synth.project_id}"
    for decision in ("confirm", "reject"):
        routes.post_sameas_decide([{"decision": decision, "scope": "pair", "pair_key": pair_key,
                                    "a_stable": second[0], "b_stable": second[1],
                                    "snapshot_id": synth.target_snapshot_id}], ident=_web())

    assert _rows(store, "rekey") == [("rekey", "mcp", 0, OWNER), ("rekey", "web", 1, OWNER)]


def test_one_decide_request_carries_its_entrance_to_every_rekey_it_runs(store):
    """POST /sameas/decide 의 입구는 그 요청의 키 전파 행 전부에 같다 — MCP 가 닿지 않는 키 병합 · 풀기 · 계면 별칭 철회도 웹에서 하면
    (web, 1) 이다(종전에는 셋 다 기본값 rest 였다). 같은 조작을 REST(Bearer)로 하면 (rest, 1)."""
    test_rekey._world(store)
    store.execute("INSERT INTO rr_iface_alias(alias_key, canonical_a, canonical_b, owner_sub, aliases_json, source, score)"
                  " VALUES (?,?,?,?,'[]','auto',1.0)", (f"{test_rekey.X}|{test_rekey.Z}", test_rekey.X, test_rekey.Z, OWNER))

    routes.post_sameas_decide([{"decision": "merge_key", "ckey_from": test_rekey.Y, "ckey_into": test_rekey.X},
                               {"decision": "unmerge_key", "ckey": test_rekey.Y},
                               {"decision": "revoke_iface_alias", "alias_key": f"{test_rekey.X}|{test_rekey.Z}"}],
                              ident=_web())
    routes.post_sameas_decide([{"decision": "merge_key", "ckey_from": test_rekey.W, "ckey_into": test_rekey.X}],
                              ident=factories.ident(OWNER))

    assert _rows(store, "rekey") == [("rekey", "web", 1, OWNER)] * 3 + [("rekey", "rest", 1, OWNER)]
