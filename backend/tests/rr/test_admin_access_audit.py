# 관리자 접근 감사(사용자 결정 11-01 '쓰기 표시 + 읽기 하루 한 줄' · 계획서대로) — 관리자 우회로만 든 쓰기의 감사 행에는 표시, 우회로만 지난 쓰기 문 · 읽기 문은 관리자 · 과제 · 날마다 한 줄
"""포털 plan §5.2.1 '멤버십' 행 — `identity.role ∈ risk_admin_roles` 는 멤버 행 없이 editor 로 통과하며 그 접근도 rr_audit 에 남는다. 앱은
쓰기 문(MB-14)과 웹 읽기 문(OI-5)에 관리자 우회를 두었지만 어느 쪽도 남기지 않았다 — 관리자의 쓰기는 감사 행의 행위자로만 남아 구성원의
쓰기와 가를 수 없었고 읽기는 흔적이 없었다(context-notes OI-5 · OI-7). 사용자 결정 11-01 이 고른 안이 이 파일의 계약이다.

- 쓰기 — 관리자가 아니었다면 막혔을 쓰기(구성원이 아니거나 그 쓰기에 모자란 역할)가 남기는 감사 행마다 after 의 `via` 칸이 "admin" 이다.
  조회(`GET /projects/{id}/audit` · `GET /targets/{key}/audit`)는 그 칸을 entry.via 로 올린다. 구성원으로도 할 수 있는 쓰기에는 싣지 않는다.
- 쓰기 문 — 관리자 우회로만 지난 쓰기 문마다 (관리자, 과제, 한국 날) 많아야 한 행이다(scope project · action admin.write · after {day}). 문
  안에서 쓰므로 어느 쓰기 길도 건너뛰지 못한다 — 그 쓰기가 제 감사 행을 남기든 아니든, 문을 지난 뒤 거절되든(422 · 409) 같다(AA-8).
- 읽기 — 관리자 우회로만 열린 읽기마다 (관리자, 과제, 한국 날) 많아야 한 행이다(scope project · action admin.read · after {day}). 쓰기는 한
  문장(INSERT … SELECT … WHERE NOT EXISTS)이라 함께 든 읽기도 둘을 쓰지 않는다. 구성원(주인 포함) · 발견 목록 · MCP 는 남기지 않는다.
- 사람 개입으로 세는 곳(대상 감사 · 통합 보고서 '사람 개입 요약')에 두 줄은 들지 않는다 — 과제 이력에만 이름표와 함께 선다.

  실행:  .venv/bin/python -m pytest tests/rr/test_admin_access_audit.py
"""
from __future__ import annotations

import calendar
import dataclasses
import json
import time
from collections.abc import Callable
from typing import Any

import pytest

import app.mcp_server as srv
from app import brief as brief_module
from app import closure, common, export, field_source, identity, registry, review_runner, routes, runner
from tests import factories
from tests import test_external_llm_jobs as external
from tests.rr import test_member_reads as member_reads
from tests.rr import test_review1_stranger as stranger
from tests.rr import test_review1_stranger_recall as recall
from tests.rr.test_member_reads import ADMIN, ADMIN_GET_EXEMPT, MEMBERS, _body, _Field, _forge
from tests.rr.test_review1_stranger import CASES, GET_CASES, GET_EXPECT, OTHER, OWNER, PREPARE, P, _answer, _mcp
from tests.rr.test_review1_stranger_recall import K, _registry, _snapshot_of
from tests.rr.test_review1_stranger_recall import _target as _snap_target
from tests.synth import review_rig as rig
from tests.test_human_control_audit import _summary
from tests.test_review_cells import _target as _review_target

# 원장 픽스처 — 남 시험 표의 원장(검토 → 쟁점 → 종합) 사본에 편집자 · 보기를 들인 것, 두 과제(앞 · 뒤 리비전), 유사 · 선례의 주인 쪽 원장.
template = stranger.template
ledger = stranger.ledger
members = member_reads.members
two_projects = member_reads.two_projects
world = recall.world


def _who(email: str, *, role: str = "admin", source: str = "cookie") -> identity.Identity:
    return dataclasses.replace(factories.ident(email), role=role, source=source)


ADMIN_EDITOR = _who("admin-editor@example.com")          # 관리자이면서 편집자 구성원
ADMIN_VIEWER = _who("admin-viewer@example.com")          # 관리자이면서 보기 구성원
ADMIN_OWNER = _who(OWNER)                                # 제 과제의 관리자


def _add(store, project_id: str, email: str, role: str) -> None:
    routes.put_members(project_id, routes.MembersBody(members=[routes.MemberItem(email=email, role=role)]),
                       ident=factories.ident(OWNER))


# ---------------------------------------------------------------- 관리자 접근 줄 — 날은 한국 표준시(UTC+9)
KST = 9 * 3600
DAY = 86400
ACCESS = ("admin.read", "admin.write")


def _kst_day(at: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(at + KST))


def _access_rows(store, action: str) -> list[dict]:
    """관리자 접근 줄(열람 admin.read · 쓰기 문 admin.write) — 적힌 차례."""
    return [dict(r) for r in store.query(
        "SELECT owner_sub, actor, actor_verified, channel, scope, subject_id, project_id, before_json, after_json, reason, at"
        " FROM rr_audit WHERE action = ? ORDER BY at, rowid", (action,))]


def _read_rows(store) -> list[dict]:
    return _access_rows(store, "admin.read")


def _read_projects(store) -> list[str]:
    return [r["project_id"] for r in _read_rows(store)]


def _write_projects(store) -> list[str]:
    return [r["project_id"] for r in _access_rows(store, "admin.write")]


def _on_days(start: int, calls: list[Callable[[], Any]]) -> None:
    """부름마다 하루씩(KST 날) 넘기며 부른다 — 한 날 한 줄이라 갈래마다 따로 보이게."""
    previous = common.set_clock(lambda: start)
    try:
        for n, call in enumerate(calls):
            common.set_clock(lambda n=n: start + n * DAY)
            call()
    finally:
        common.set_clock(previous)


# ---------------------------------------------------------------- 쓰기 — 관리자 우회로만 든 쓰기의 감사 행에 표시
@dataclasses.dataclass
class World:
    store: Any
    monkeypatch: Any
    ids: dict
    project: str | None = None


@dataclasses.dataclass(frozen=True)
class Write:
    world: str                                   # ledger(검토 → 쟁점 → 종합 원장 사본) · box(빈 원장)
    need: str                                    # 문이 요구하는 역할 — editor · owner · author(작성자 또는 과제 주인)
    call: Callable[[World, identity.Identity], Any]
    actions: tuple[str, ...]                     # 그 쓰기가 남기는 감사 행
    prepare: Callable[[World], Any] | None = None


NEW_VIEWER = "new-viewer@example.com"
LEDGER_PAIR = "pk:left|pk:right"
FINDING = {"mechanism": "interface", "claim": "관리자가 본 간극", "cites": [{"ref": "c:5b0e11aa22bb", "quote": "배치"}]}


def _intra(w: World, decision: str) -> list[dict]:
    return [{"decision": decision, "scope": "intra", "pair_key": w.project, "a": "s:a", "b": "s:b"}]


def _fail_gate(w: World) -> None:
    """대상 스냅샷의 G1 을 거짓으로 — ack 는 거짓 게이트에만 붙는다(원장의 게이트는 다 지났다)."""
    row = w.store.query_one("SELECT gates_json FROM rr_states WHERE snapshot_id = ?", (w.ids["target_snapshot"],))
    gates = json.loads(row["gates_json"])
    gates["G1"].update({"pass": False, "count": 2, "effect": "mark"})
    w.store.execute("UPDATE rr_states SET gates_json = ? WHERE snapshot_id = ?", (json.dumps(gates), w.ids["target_snapshot"]))


def _ack_gate(w: World, who) -> Any:
    return routes.post_gate_ack(w.ids["target_snapshot"], "G1", routes.GateAckBody(reason="확인했다"), ident=who)


def _close_ack(w: World, who) -> Any:
    item = next(q for q in closure.refresh(w.store, w.ids["target"])["qualifiers"] if q["item"] == "issues_untried")
    return routes.post_closure_ack(w.ids["target"], "issues_untried",
                                   routes.CloseAckBody(reason="넘긴다", basis_hash=item["basis_hash"]), ident=who)


def _untried_issue(w: World) -> str:
    return w.store.query_one("SELECT issue_id FROM rr_issues WHERE target_key = ? AND state = 'untried_cap' ORDER BY issue_id"
                             " LIMIT 1", (w.ids["target"],))["issue_id"]


def _merge(w: World, who) -> Any:
    return routes.put_registry_merge(w.ids["cluster"], routes.RegistryMergeBody(into=w.ids["cluster2"], target_key=w.ids["target"]),
                                     ident=who)


def _stub_repersist(w: World) -> None:
    """다시 앉히는 본체(러너)는 대역이다 — 감사 행은 라우트가 러너의 답 뒤에 쓴다(test_mcp_audit_actor 와 같다)."""
    w.monkeypatch.setattr(runner, "repersist_panel", lambda _store, _settings, pid: {
        "panel_id": pid, "status": "done", "level": "C1", "findings_n": 0})
    w.monkeypatch.setattr(runner, "abandon_repersist", lambda _store, pid: {
        "panel_id": pid, "status": "error", "error": "persist_abandoned: 시험", "abandoned": True})


def _panels_target(w: World) -> None:
    synth = factories.make_diff_target(w.store, 3)
    w.project, w.ids["target"] = synth.project_id, synth.target_key


def _owner_job(w: World) -> None:
    _panels_target(w)
    w.ids["job"] = routes.create_job(w.ids["target"], routes.JobBody(tier="B"), ident=factories.ident(OWNER))["job_id"]


def _claude_panels(w: World) -> None:
    _panels_target(w)
    external._probe(w.monkeypatch, external._external_fake())


def _deferred(flow: str) -> Callable[[World], None]:
    """ECAD 에 기대는 보류 좌석(pcb-syn-1 — ecad_absent)이 있는 대상."""
    def prepare(w: World) -> None:
        w.ids["target"] = _review_target(w.store, agents=factories.agents(), flow=flow)
        w.project = w.store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (w.ids["target"],))["project_id"]
    return prepare


def _pending_seat(w: World) -> str:
    return w.store.query_one("SELECT agent_key FROM rr_coverage WHERE target_key = ? AND status = 'pending' ORDER BY agent_key"
                             " LIMIT 1", (w.ids["target"],))["agent_key"]


WRITES: dict[str, Write] = {
    "member.put": Write("ledger", "owner", lambda w, who: routes.put_members(w.project, routes.MembersBody(
        members=[routes.MemberItem(email=NEW_VIEWER, role="viewer")]), ident=who), ("member.put",)),
    "project.transfer": Write("ledger", "owner", lambda w, who: routes.transfer_project(w.project, routes.TransferBody(
        to_email="heir@example.com", reason="넘긴다"), ident=who), ("project.transfer",)),
    "project.purge": Write("ledger", "owner", lambda w, who: routes.purge_project(w.project, routes.PurgeBody(
        code=w.ids["code"], reason="지운다"), ident=who), ("project.purge",)),
    "requirement.decide": Write("ledger", "editor", lambda w, who: routes.put_requirement(
        w.ids["requirement"], routes.RequirementDecision(status="confirmed"), ident=who), ("requirement.decide",)),
    "rekey(iface-ledger)": Write("ledger", "editor", lambda w, who: routes.put_iface_ledger(
        w.project, [routes.LedgerItem(pair_key=LEDGER_PAIR, status="rejected")], ident=who), ("rekey",),
        prepare=lambda w: routes.put_iface_ledger(w.project, [routes.LedgerItem(pair_key=LEDGER_PAIR, status="confirmed")],
                                                  ident=factories.ident(OWNER))),
    "rekey(sameas)": Write("ledger", "editor", lambda w, who: routes.post_sameas_decide(_intra(w, "reject"), ident=who),
                           ("rekey",), prepare=lambda w: routes.post_sameas_decide(_intra(w, "confirm"),
                                                                                   ident=factories.ident(OWNER))),
    "gate.ack": Write("ledger", "editor", _ack_gate, ("gate.ack",), prepare=_fail_gate),
    "gate.ack(revoke)": Write("ledger", "editor", lambda w, who: routes.delete_gate_ack(
        w.ids["target_snapshot"], "G1", ident=who), ("gate.ack",),
        prepare=lambda w: (_fail_gate(w), _ack_gate(w, factories.ident(OWNER)))),
    "close.ack": Write("ledger", "owner", _close_ack, ("close.ack",)),
    "close.ack.revoke": Write("ledger", "owner", lambda w, who: routes.delete_closure_ack(
        w.ids["target"], "issues_untried", ident=who), ("close.ack.revoke",),
        prepare=lambda w: _close_ack(w, factories.ident(OWNER))),
    "issue.skip": Write("ledger", "editor", lambda w, who: routes.put_issue(_untried_issue(w), routes.IssueActionBody(
        action="skip", reason="넘긴다"), ident=who), ("issue.skip",)),
    "verdict.final": Write("ledger", "editor", lambda w, who: routes.put_verdict(
        w.ids["target"], routes.VerdictBody(verdict="go"), ident=who), ("verdict.final",)),
    "registry.status": Write("ledger", "editor", lambda w, who: routes.put_registry_status(
        w.ids["cluster"], routes.RegistryStatusBody(status="mitigated", note="막았다", target_key=w.ids["target"]), ident=who),
        ("registry.status",)),
    "registry.merge": Write("ledger", "editor", _merge, ("registry.merge",)),
    "registry.merge.revoke": Write("ledger", "editor", lambda w, who: routes.delete_registry_merge(
        w.ids["cluster"], target_key=w.ids["target"], ident=who), ("registry.merge.revoke",),
        prepare=lambda w: _merge(w, factories.ident(OWNER))),
    "panel.repersist": Write("ledger", "editor", lambda w, who: routes.post_panel_repersist(w.ids["panel"], ident=who),
                             ("panel.repersist",), prepare=_stub_repersist),
    "panel.repersist_discard": Write("ledger", "editor", lambda w, who: routes.post_panel_repersist(
        w.ids["panel"], discard=True, ident=who), ("panel.repersist_discard",), prepare=_stub_repersist),
    "finding.create": Write("ledger", "editor", lambda w, who: routes.create_human_finding(
        w.ids["target"], routes.HumanFindingBody(**FINDING), ident=who), ("finding.create",)),
    "finding.update": Write("ledger", "author", lambda w, who: routes.update_human_finding(
        w.ids["human_finding"], routes.HumanFindingBody(**{**FINDING, "claim": "고친 간극"}), ident=who), ("finding.update",)),
    "finding.delete": Write("ledger", "author", lambda w, who: routes.delete_human_finding(w.ids["human_finding"], ident=who),
                            ("finding.delete",)),
    "cells.retry": Write("ledger", "editor", lambda w, who: routes.post_cells_retry(w.ids["target"], routes.CellsRetryBody(
        filter={}, reason="다시 본다", force=True, start=False), ident=who), ("cells.retry",)),
    "target.flow": Write("box", "editor", lambda w, who: routes.post_target_flow(
        w.ids["target"], routes.FlowBody(to="cells", reason="파일럿"), ident=who), ("target.flow",), prepare=_panels_target),
    "job.pause": Write("box", "editor", lambda w, who: routes.job_action(w.ids["job"], "pause", ident=who), ("job.pause",),
                       prepare=_owner_job),
    "job.cancel": Write("box", "editor", lambda w, who: routes.job_action(w.ids["job"], "cancel", ident=who), ("job.cancel",),
                        prepare=_owner_job),
    "brief.exclude": Write("box", "editor", lambda w, who: routes.create_job(
        w.ids["target"], routes.JobBody(tier="B", exclude_evidence=["E6"]), ident=who), ("brief.exclude",),
        prepare=_panels_target),
    "job.create(claude panels)": Write("box", "editor", lambda w, who: routes.create_job(
        w.ids["target"], routes.JobBody(tier="B", llm="claude", consent_external=True), ident=who), ("job.create",),
        prepare=_claude_panels),
    "job.create(reviews)": Write("box", "editor", lambda w, who: routes.create_job(
        w.ids["target"], routes.JobBody(mode="reviews", consent=True), ident=who), ("coverage.undefer", "job.create"),
        prepare=_deferred("cells")),
    "coverage.skip": Write("box", "editor", lambda w, who: routes.put_coverage(
        w.ids["target"], _pending_seat(w), routes.CoverageBody(status="skipped", reason="넘긴다"), ident=who),
        ("coverage.skip",), prepare=_panels_target),
    "coverage.undefer": Write("box", "editor", lambda w, who: routes.post_undefer(
        w.ids["target"], routes.UndeferBody(reason="회로 전문가도 앉힌다"), ident=who), ("coverage.undefer",),
        prepare=_deferred("panels")),
}
# 부른 사람 — 구성원이 아닌 관리자는 늘 표시, 편집자 구성원인 관리자는 편집자 쓰기에 표시 없음(주인 쓰기 · 작성자 쓰기에는 표시), 제 과제의
# 관리자는 표시 없음.
CALLERS = {"admin": ADMIN, "admin-editor": ADMIN_EDITOR, "admin-owner": ADMIN_OWNER}


def _expected_via(need: str, caller: str) -> str | None:
    if caller == "admin":
        return "admin"
    if caller == "admin-editor":
        return "admin" if need in ("owner", "author") else None
    return None


def _world(request, monkeypatch, kind: str) -> World:
    if kind == "ledger":
        store, ids = request.getfixturevalue("members")
        return World(store, monkeypatch, dict(ids), ids["project"])
    store = request.getfixturevalue("risk_store")
    rig.configure(monkeypatch, store, request.getfixturevalue("tmp_path"))
    for email in sorted({OWNER, *(who.email for who in CALLERS.values())}):
        rig.pat(store, email)            # 잡의 자격 — Claude 길은 반출에 동의한 사람(부른 사람)의 PAT 로만 돈다
    return World(store, monkeypatch, {})


def _rows_after(store, mark: int, *, access: bool = False) -> list[dict]:
    """그 뒤에 선 감사 행 — 기본은 그 쓰기의 제 행(관리자 접근 줄을 뺀다), `access` 면 접근 줄만."""
    rows = []
    for row in store.query("SELECT rowid, actor, action, project_id, after_json FROM rr_audit WHERE rowid > ? ORDER BY rowid",
                           (mark,)):
        if (row["action"] in ACCESS) != access:
            continue
        after = json.loads(row["after_json"]) if row["after_json"] else None
        rows.append({"actor": row["actor"], "action": row["action"], "project_id": row["project_id"],
                     "via": after.get("via") if isinstance(after, dict) else None})
    return rows


def _last(store) -> int:
    return int(store.query_one("SELECT COALESCE(MAX(rowid), 0) AS n FROM rr_audit")["n"])


@pytest.mark.parametrize(("name", "caller"), [(name, caller) for name, write in WRITES.items()
                                              for caller in ("admin", "admin-editor", *(("admin-owner",) if write.need != "editor"
                                                                                        else ()))],
                         ids=lambda v: v)
def test_the_rows_a_write_leaves_say_whether_only_the_admin_bypass_let_it_in(name, caller, request, monkeypatch):
    """감사 행을 남기는 쓰기마다 — 구성원이 아닌 관리자의 행은 via "admin" 이다(그 쓰기가 남기는 행 전부 — 잡 만들기가 함께 푸는 보류 좌석의
    coverage.undefer 까지). 편집자 구성원인 관리자는 편집자 쓰기에 표시가 없고(구성원으로도 한다) 주인 쓰기 · 작성자 쓰기에는 표시다(편집자는
    못 한다). 제 과제의 관리자는 표시가 없다. 행위자는 늘 부른 사람이다. 표시가 선 쓰기는 그 문이 그 과제의 관리자 쓰기 줄(admin.write) 하나를
    함께 남기고, 표시가 없는 쓰기는 남기지 않는다(AA-8)."""
    write = WRITES[name]
    w = _world(request, monkeypatch, write.world)
    if write.prepare is not None:
        write.prepare(w)
    who = CALLERS[caller]
    if caller == "admin-editor":
        _add(w.store, w.project, who.email, "editor")
    mark = _last(w.store)
    write.call(w, who)
    rows = _rows_after(w.store, mark)
    expected = _expected_via(write.need, caller)
    assert sorted(r["action"] for r in rows) == sorted(write.actions), rows
    assert {(r["actor"], r["via"]) for r in rows} == {(who.email, expected)}, rows
    access = [(r["action"], r["actor"], r["project_id"]) for r in _rows_after(w.store, mark, access=True)]
    assert [a for a in access if a[0] == "admin.write"] == ([("admin.write", who.email, w.project)] if expected else []), access


def test_an_admin_who_wrote_the_finding_changes_it_as_its_author(members):
    """사람 finding 고치기 · 지우기는 작성자 또는 과제 주인이다 — 편집자 구성원인 관리자가 제가 올린 finding 을 고치면 작성자로 한 것이라
    표시가 없다(올림도 편집자 쓰기라 없다). 보기로 내려간 뒤에는 작성자여도 편집자 문을 관리자라서 지나므로 표시다."""
    store, ids = members
    _add(store, ids["project"], ADMIN_EDITOR.email, "editor")
    mark = _last(store)
    made = routes.create_human_finding(ids["target"], routes.HumanFindingBody(**FINDING), ident=ADMIN_EDITOR)
    routes.update_human_finding(made["finding_id"], routes.HumanFindingBody(**{**FINDING, "claim": "고친 간극"}), ident=ADMIN_EDITOR)
    _add(store, ids["project"], ADMIN_EDITOR.email, "viewer")        # 보기로 내려간 작성자
    routes.update_human_finding(made["finding_id"], routes.HumanFindingBody(**{**FINDING, "claim": "또 고친 간극"}),
                                ident=ADMIN_EDITOR)
    routes.delete_human_finding(made["finding_id"], ident=ADMIN_EDITOR)
    assert [(r["action"], r["via"]) for r in _rows_after(store, mark) if r["action"].startswith("finding.")] == [
        ("finding.create", None), ("finding.update", None), ("finding.update", "admin"), ("finding.delete", "admin")]
    # 관리자 쓰기 줄은 보기로 내려간 뒤의 고치기가 편집자 문을 우회로 지날 때 하나다(지우기는 같은 날이라 더 없다)
    assert _write_projects(store) == [ids["project"]]


def test_a_viewer_admin_passes_each_editor_door_by_the_bypass(members, monkeypatch):
    """보기 구성원인 관리자의 편집자 쓰기는 관리자이기 때문에 든 것이다(보기는 403) — 그 감사 행은 표시이고, 편집자 문마다(쓰기 문 `_writer` ·
    대상 편집자 문 · 다시 저장의 문 · 대응 결정의 과제 편집자 문) 관리자 쓰기 줄이 선다. 문마다 따로 보이게 날을 바꿔 가며 부른다."""
    store, ids = members
    _add(store, ids["project"], ADMIN_VIEWER.email, "viewer")
    w = World(store, monkeypatch, dict(ids), ids["project"])
    _stub_repersist(w)
    mark = _last(store)
    _on_days(calendar.timegm((2026, 11, 3, 3, 0, 0)), [                  # 2026-11-03 12:00 KST 부터
        lambda: routes.put_verdict(ids["target"], routes.VerdictBody(verdict="go"), ident=ADMIN_VIEWER),
        lambda: routes.create_human_finding(ids["target"], routes.HumanFindingBody(**FINDING), ident=ADMIN_VIEWER),
        lambda: routes.post_panel_repersist(ids["panel"], ident=ADMIN_VIEWER),
        lambda: routes.post_sameas_decide(_intra(w, "confirm"), ident=ADMIN_VIEWER),
    ])
    assert [(r["action"], r["via"]) for r in _rows_after(store, mark)] == [
        ("verdict.final", "admin"), ("finding.create", "admin"), ("panel.repersist", "admin")]
    assert [(r["project_id"], json.loads(r["after_json"])["day"], r["channel"]) for r in _access_rows(store, "admin.write")] == [
        (ids["project"], day, "web") for day in ("2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06")]


def test_a_non_admin_is_never_marked_even_on_its_own_row_hung_on_someone_elses_project(members):
    """표시는 관리자에게만이다 — 남이 주인의 과제에 매단 제 대상(RD-10)에 그 남이 쓰는 것은 행 주인의 길이라(그 과제의 역할 없이 지난다)
    표시가 없다."""
    store, ids = members
    _forged_snapshot, forged_target = _forge(store, ids)
    mark = _last(store)
    routes.put_verdict(forged_target, routes.VerdictBody(verdict="go"), ident=factories.ident(OTHER))
    assert [(r["action"], r["actor"], r["via"]) for r in _rows_after(store, mark)] == [("verdict.final", OTHER, None)]


def test_a_pair_decision_is_marked_when_either_project_needed_the_bypass(two_projects):
    """두 과제(pair) 대응 결정은 두 과제의 편집자여야 한다 — 관리자가 한 과제의 편집자일 뿐이면 다른 과제는 우회로 든 것이라 그 결정의 키 전파
    행은 표시다. 두 과제의 편집자면 표시가 없다."""
    w = two_projects
    store = w["store"]
    owner = factories.ident(OWNER)
    table = routes.get_sameas(base=w["base"], target=w["target"], ident=owner)
    row = table["pairs"][0]
    decision = {"scope": "pair", "pair_key": table["pair_key"], "a_stable": row["a_stable"], "b_stable": row["b_stable"],
                "snapshot_id": w["target"]}
    _add(store, w["target_project"], ADMIN_EDITOR.email, "editor")
    marks = []
    for both in (False, True):
        if both:
            _add(store, w["base_project"], ADMIN_EDITOR.email, "editor")
        routes.post_sameas_decide([{**decision, "decision": "confirm"}], ident=owner)
        mark = _last(store)
        routes.post_sameas_decide([{**decision, "decision": "reject"}], ident=ADMIN_EDITOR)
        marks.append([(r["action"], r["via"]) for r in _rows_after(store, mark)])
    assert marks == [[("rekey", "admin")], [("rekey", None)]]
    # 관리자 쓰기 줄은 우회로 지난 과제(앞 리비전)에만 — 편집자인 과제에는 없다
    assert _write_projects(store) == [w["base_project"]]


def test_a_disposal_hands_its_mark_to_the_review_job_it_makes(members, monkeypatch):
    """처분이 세우는 검토 잡도 그 처분의 표시를 받는다 — 그 잡이 보류 좌석을 풀면(coverage.undefer) 그 행도 관리자의 쓰기다. 오늘 생산자
    길로는 처분한 셀의 전문가에 보류 좌석이 남지 않아 그 행이 서지 않으므로 넘겨 주는 칸을 본다."""
    store, ids = members
    real = review_runner.create_review_job
    seen: list[Any] = []

    def create_review_job(*args, **kwargs):
        seen.append(kwargs.get("via"))
        return real(*args, **kwargs)

    monkeypatch.setattr(review_runner, "create_review_job", create_review_job)
    out = routes.post_cells_retry(ids["target"], routes.CellsRetryBody(filter={}, reason="다시 본다", force=True, consent=True),
                                  ident=ADMIN)
    assert out["job"]["action"] == "created" and seen == ["admin"], (out, seen)


def test_the_audit_reads_lift_the_mark_into_the_entry(members):
    """과제 감사 · 대상 감사의 줄마다 `via` 가 있다 — 표시된 행은 "admin" 이고 after 에서는 빠진다(앞 · 뒤는 그 조작의 값만). 다른 행은
    null 이다."""
    store, ids = members
    routes.put_verdict(ids["target"], routes.VerdictBody(verdict="go"), ident=ADMIN)
    owner = factories.ident(OWNER)
    for page in (routes.get_project_audit(ids["project"], ident=owner), routes.get_target_audit(ids["target"], ident=owner)):
        marked = [e for e in page["entries"] if e["via"] is not None]
        assert [(e["action"], e["actor"], e["via"], e["after"]) for e in marked] == [
            ("verdict.final", ADMIN.email, "admin", {"verdict_final": "go"})]
        assert all("via" in e for e in page["entries"])


# ---------------------------------------------------------------- 쓰기 문 — (관리자, 과제, 날) 한 줄(admin.write, AA-8)
# 라우터의 쓰기 경로 가운데 관리자 우회가 있는 쓰기 문을 지나지 않는 것 — 까닭과 함께. 나머지는 구성원이 아닌 관리자가 부르면 그 과제에 한 줄이다.
ADMIN_WRITE_EXEMPT: dict[tuple[str, str], str] = {
    ("POST", P + "/projects"): "제 과제를 만든다 — 앞 과제는 읽기 판정이라 관리자 열람 줄이다",
    ("PATCH", P + "/projects/{project_id}"): "관리자 우회가 없다(그 과제의 편집자 이상 — 구성원만, 관리자에게도 없는 과제와 같은 404)",
    ("PUT", P + "/projects/{project_id}/ecad-board"): "과제 주인만이다(관리자 우회가 없다)",
    ("DELETE", P + "/projects/{project_id}/ecad-board"): "과제 주인만이다(관리자 우회가 없다)",
    ("POST", P + "/projects/{project_id}/requirements/inherit"): (
        "받는 과제는 부른 사람 자신의 과제다 — 원본은 읽기 판정이고 관리자 우회가 없다"),
    ("PUT", P + "/registry/{cluster_key:path}/visibility"): "부른 사람 자신의 등록부 행만이다(소유자 전용 — 관리자 우회가 없다)",
    ("POST", P + "/targets/{target_key}/resync"): "대상 소유자만이다(관리자 우회가 없다)",
    ("PUT", P + "/curation/{queue_id}"): "부른 사람 자신의 큐만이다(관리자 우회가 없다)",
}
# 표의 부름이 문을 지나지 않는 꼴(대상 없이 부르면 부른 사람 자신의 행이다)인 경로 — 대상을 고른 꼴로 부른다.
ADMIN_WRITE_CALLS: dict[tuple[str, str], Callable[[dict, Any], Any]] = {
    ("PUT", P + "/registry/{cluster_key:path}/status"): lambda i, who: routes.put_registry_status(
        i["cluster"], routes.RegistryStatusBody(status="mitigated", note="막았다", target_key=i["target"]), ident=who),
    ("PUT", P + "/registry/{cluster_key:path}/merge"): lambda i, who: routes.put_registry_merge(
        i["cluster"], routes.RegistryMergeBody(into=i["cluster2"], target_key=i["target"]), ident=who),
    ("DELETE", P + "/registry/{cluster_key:path}/merge"): lambda i, who: routes.delete_registry_merge(
        i["cluster"], target_key=i["target"], ident=who),
}


def test_the_write_door_table_covers_the_router():
    """면제는 라우터의 쓰기 경로(남 시험 표 — 라우터와 같음을 그 파일이 지킨다) 안이고 까닭이 있다. 대상을 고른 꼴의 부름은 면제 밖이다."""
    assert set(ADMIN_WRITE_EXEMPT) <= set(CASES) and all(ADMIN_WRITE_EXEMPT.values())
    assert set(ADMIN_WRITE_CALLS) <= set(CASES) - set(ADMIN_WRITE_EXEMPT)


@pytest.mark.parametrize("case", sorted(set(CASES) - set(ADMIN_WRITE_EXEMPT)), ids=lambda c: f"{c[0]} {c[1][len(P):]}")
def test_every_write_door_an_admin_passes_only_by_the_bypass_leaves_one_row_a_day(members, case):
    """라우터의 쓰기 경로마다 — 구성원이 아닌 관리자가 두 번 부르면 그 과제의 관리자 쓰기 줄이 한 행이다. 문 안에서 쓰므로 그 쓰기가 제 감사
    행을 남기든 아니든(소스 · 동결 · 치수 · 대상 만들기 · 라벨 …), 문을 지난 뒤 422 · 409 로 거절되든 같다. 행위자 · 행 주인은 관리자, 입구는
    신원 출처(Bearer rest), 자리는 과제, 뒤 값은 그 한국 날뿐이다."""
    store, ids = members
    call = ADMIN_WRITE_CALLS.get(case) or CASES[case][0]
    if case in PREPARE:
        PREPARE[case](ids, store)
    for _ in range(2):
        _answer(lambda: call(ids, ADMIN))
    rows = _access_rows(store, "admin.write")
    assert [(r["owner_sub"], r["actor"], r["actor_verified"], r["channel"], r["scope"], r["subject_id"], r["project_id"],
             r["before_json"], r["reason"]) for r in rows] == [
        (ADMIN.email, ADMIN.email, 1, "rest", "project", ids["project"], ids["project"], None, None)], case
    assert json.loads(rows[0]["after_json"]) == {"day": _kst_day(rows[0]["at"])}


@pytest.mark.parametrize("case", sorted(ADMIN_WRITE_EXEMPT), ids=lambda c: f"{c[0]} {c[1][len(P):]}")
def test_routes_without_an_admin_write_door_leave_no_write_row(members, case):
    """면제한 경로는 관리자 우회가 있는 쓰기 문을 지나지 않는다 — 관리자가 불러도 관리자 쓰기 줄이 없다(면제의 까닭이 맞는지 본다)."""
    store, ids = members
    call, _supplied = CASES[case]
    if case in PREPARE:
        PREPARE[case](ids, store)
    _answer(lambda: call(ids, ADMIN))
    assert _access_rows(store, "admin.write") == [], case


def test_the_brief_is_a_write_door(members):
    """브리프(`GET /targets/{key}/brief`)는 GET 이지만 편성 · 토큰을 내는 쓰기 문이다 — 관리자 쓰기 줄이고 열람 줄이 아니다."""
    store, ids = members
    _answer(lambda: routes.get_brief(ids["target"], ident=ADMIN))
    assert (_write_projects(store), _read_projects(store)) == ([ids["project"]], [])


def test_a_rejected_batch_keeps_the_write_row_its_door_admitted(members):
    """대응 결정 배열은 한 트랜잭션이다 — 뒤 항목이 거절되면 앞 결정도 쓰지 않는다. 그래도 앞 항목의 문을 관리자 우회로 지난 것은 남는다(문
    판정을 그 트랜잭션 앞에서 한다 — 다른 쓰기 문과 같이 문을 지난 것이 접근이다)."""
    store, ids = members
    batch = [{"decision": "confirm", "scope": "intra", "pair_key": ids["project"], "a": "s:a", "b": "s:b"},
             {"decision": "confirm", "scope": "pair", "pair_key": "only-one", "a": "s:a", "b": "s:b"}]
    got = _answer(lambda: routes.post_sameas_decide(batch, ident=ADMIN))
    assert got[:2] == ("E100", 400), got[:3]
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_sameas WHERE pair_key = ?", (ids["project"],))["n"] == 0
    assert _write_projects(store) == [ids["project"]]


def test_a_write_row_never_counts_as_human_intervention(members):
    """관리자 쓰기 줄도 과제 단위 자리(scope project)라 대상 감사와 '사람 개입 요약' 에 들지 않는다 — 그 쓰기의 제 감사 행(표시)은 든다. 과제
    이력에는 열람 줄과 따로 선다(같은 날 읽고 써도 한 줄씩, 표시 없이 날만). 반출에는 실리지 않는다."""
    store, ids = members
    owner = factories.ident(OWNER)
    routes.get_coverage(ids["target"], ident=ADMIN)
    routes.add_dim(ids["project"], routes.DimBody(name="gap_admin", kind="gap", extractor="const:0.35", unit="mm"),
                   ident=ADMIN)                                          # 제 감사 행이 없는 쓰기
    routes.put_verdict(ids["target"], routes.VerdictBody(verdict="go"), ident=ADMIN)
    routes.get_registry(ids["target"], ident=ADMIN)
    assert (_read_projects(store), _write_projects(store)) == ([ids["project"]], [ids["project"]])
    target = [e["action"] for e in routes.get_target_audit(ids["target"], ident=owner)["entries"]]
    assert "verdict.final" in target and not set(target) & set(ACCESS), target
    counts = registry.target_audit_counts(store, ids["target"])
    assert counts.get("verdict.final") == 1 and not set(counts) & set(ACCESS), counts
    assert not [line for line in _summary(store, ids["target"]) if line.split("=")[0] in ACCESS]
    entries = routes.get_project_audit(ids["project"], ident=owner)["entries"]
    assert sorted((e["action"], e["actor"], e["via"], sorted(e["after"])) for e in entries if e["action"] in ACCESS) == [
        ("admin.read", ADMIN.email, None, ["day"]), ("admin.write", ADMIN.email, None, ["day"])]
    lines = [json.loads(line) for line in export.iter_lines(store, OWNER, 0)][1:]
    assert not [line for line in lines if line["table"] == "rr_audit" and line["row"]["action"] in ACCESS]


# ---------------------------------------------------------------- 읽기 — (관리자, 과제, 날) 한 줄
@pytest.mark.parametrize("case", sorted(set(GET_CASES) - set(ADMIN_GET_EXEMPT)), ids=lambda c: f"{c[0]} {c[1][len(P):]}")
def test_every_read_door_an_admin_opens_only_by_the_bypass_leaves_one_row_a_day(members, case):
    """관리자 읽기 표(test_member_reads 의 관리자 표 — 남 시험 표의 읽기 경로 전부 − 브리프 · 발견 목록 셋)의 경로마다, 구성원이 아닌 관리자가
    두 번 읽으면 그 과제의 열람 줄이 한 행이다 — 행위자 · 행 주인은 관리자, 입구는 신원 출처(Bearer rest), 자리는 과제, 뒤 값은 그 한국
    날뿐(사람이 쓴 글 없음)."""
    store, ids = members
    call, _supplied = GET_CASES[case]
    assert _read_rows(store) == []
    for _ in range(2):
        got = _answer(lambda: call(ids, ADMIN))
        assert got[1] == 200, (case, got[:3])
    rows = _read_rows(store)
    assert [(r["owner_sub"], r["actor"], r["actor_verified"], r["channel"], r["scope"], r["subject_id"], r["project_id"],
             r["before_json"], r["reason"]) for r in rows] == [
        (ADMIN.email, ADMIN.email, 1, "rest", "project", ids["project"], ids["project"], None, None)], case
    assert json.loads(rows[0]["after_json"]) == {"day": _kst_day(rows[0]["at"])}


def test_owners_members_and_admins_who_are_members_leave_no_read_row(members):
    """구성원(주인 · 편집자 · 보기)의 읽기는 우회가 아니다 — 보기 행 하나만 있는 관리자도 구성원으로 읽는다. 표의 읽기 경로 전부(면제 포함)를
    걸어도 열람 줄이 없다."""
    store, ids = members
    _add(store, ids["project"], ADMIN_VIEWER.email, "viewer")
    for case in sorted(GET_CASES):
        call, _supplied = GET_CASES[case]
        for who in (factories.ident(OWNER), *(factories.ident(m) for m in MEMBERS), ADMIN_VIEWER):
            _answer(lambda call=call, who=who: call(ids, who))
    assert _read_rows(store) == []


def test_lists_rows_hung_by_someone_else_missing_projects_and_mcp_leave_no_read_row(members, monkeypatch):
    """발견 목록(관리자에게도 소유 ∪ 구성원 — 빈 목록) · 남이 매단 행(관리자에게도 404) · 없는 과제 · MCP(관리자 우회가 없다)는 아무것도 열지
    않아 열람 줄이 없다."""
    store, ids = members
    for case in GET_EXPECT:
        call, _supplied = GET_CASES[case]
        assert _body(_answer(lambda call=call: call(ids, ADMIN)))["total"] == 0, case
    forged_snapshot, forged_target = _forge(store, ids)
    assert _answer(lambda: routes.get_snapshot(forged_snapshot, ident=ADMIN))[1] == 404
    assert _answer(lambda: routes.get_coverage(forged_target, ident=ADMIN))[1] == 404
    assert _answer(lambda: routes.get_project("no-such-project", ident=ADMIN))[1] == 404
    _answer(lambda: routes.get_members("no-such-project", ident=ADMIN))
    _answer(lambda: routes.get_project_audit("no-such-project", ident=ADMIN))
    factories.act_as_delegate(monkeypatch, ADMIN.email)
    assert _mcp(lambda: srv.risk_get_coverage(target_key=ids["target"]))[0] == "not_visible"
    assert _read_rows(store) == []


def test_the_day_is_the_korean_calendar_day(members):
    """하루는 한국 표준시(UTC+9) 날이다 — 23:59:59 와 00:00:00 KST 는 두 날이고, 그날 09:00 KST(UTC 자정)를 넘어도 한 날이다(UTC 날이면
    아침 아홉 시에 둘로 갈린다)."""
    store, ids = members
    midnight = calendar.timegm((2026, 11, 1, 15, 0, 0))          # 2026-11-02 00:00 KST
    previous = common.set_clock(lambda: midnight - 1)
    try:
        for at in (midnight - 1, midnight, midnight + 9 * 3600 - 1, midnight + 9 * 3600 + 1, midnight + 86400 - 1):
            common.set_clock(lambda at=at: at)
            assert routes.get_project(ids["project"], ident=ADMIN)["project"]["id"] == ids["project"]
    finally:
        common.set_clock(previous)
    rows = _read_rows(store)
    assert [(r["at"], json.loads(r["after_json"])["day"]) for r in rows] == [
        (midnight - 1, "2026-11-01"), (midnight, "2026-11-02")]


def test_a_read_that_races_another_writes_no_second_row(members, monkeypatch):
    """두 읽기가 함께 들면 둘 다 '오늘 줄 없음' 을 보고 쓰려 한다 — 쓰기가 한 문장(INSERT … WHERE NOT EXISTS)이라 늦은 쪽은 아무것도 쓰지
    않는다. 앞선 확인이 '없음' 을 본 바로 뒤에 다른 요청의 줄이 커밋된 꼴을 저장소 대역으로 만든다."""
    store, ids = members
    real = store.query_one
    raced: list[bool] = []

    def query_one(sql, params=()):
        out = real(sql, params)
        today = "FROM rr_audit" in sql and ("admin.read" in sql or "admin.read" in tuple(params))   # 오늘 줄의 앞선 확인
        if today and out is None and not raced:
            raced.append(True)
            routes.get_project(ids["project"], ident=ADMIN)       # 다른 요청 — 제 확인 · 쓰기를 다 마친다
        return out

    monkeypatch.setattr(store, "query_one", query_one)
    routes.get_project(ids["project"], ident=ADMIN)
    assert raced == [True]
    assert len(_read_rows(store)) == 1


def test_the_widened_similar_and_precedents_note_each_project_they_show_only_by_the_bypass(world):
    """유사 과제 · 선례는 관리자에게 주인의 답이다(다른 과제를 관리자가 읽는 과제로 좁히지 않는다 — OI-5). 관리자가 그 과제의 구성원이어도 넓힌
    답에 실린 다른 과제는 우회로 본 것이라 그 과제마다 한 줄이다 — 구성원인 과제는 줄이 없다."""
    store, project, mine = world["store"], world["project"], world["mine"]
    owner = factories.ident(OWNER)
    step1 = routes.create_project(routes.ProjectBody(code="P-NEXT", name="다음 리비전", classification="internal",
                                                     predecessor_project_id=project), ident=owner)["id"]
    _registry(store, _snap_target(store, _snapshot_of(store, mine[1]), OWNER), OWNER, "clu-hidden", world["subject"])
    diff_id = factories.make_diff(store, _snapshot_of(store, mine[0]), _snapshot_of(store, project))["diff_id"]
    for gate_project in (project, mine[0]):
        _add(store, gate_project, ADMIN.email, "viewer")

    found = routes.get_precedents(diff_id=diff_id, ident=ADMIN)    # 선례 먼저 — 유사가 같은 과제를 먼저 남기면 선례의 줄이 가려진다
    clusters = {store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (c["target_key"],))["project_id"]
                for c in found["clusters"]}
    assert mine[1] in clusters, clusters                         # 넓힌 답이 실제로 남의 과제를 싣는다(빈손으로 지나가지 않게)
    assert sorted(_read_projects(store)) == sorted(clusters - {project, mine[0]})
    similar = routes.get_similar(project, k=K, ident=ADMIN)
    shown = (clusters | {e["project_id"] for part in ("lineage", "vector", "text", "merged") for e in similar[part]}
             | {pid for e in similar["subject"] for pid in e["project_ids"]})
    assert step1 in shown, shown
    projects = _read_projects(store)
    assert sorted(projects) == sorted(shown - {project, mine[0]}), (projects, shown)


def test_refs_without_a_project_scope_note_the_project_they_were_found_in(risk_store, monkeypatch):
    """과제 스코프가 참조 글에 없는 req · voc · paper 도 관리자는 전 과제에서 찾는다(OI-5) — 찾은 행의 과제에 열람 줄이 선다. 갈래마다 따로
    보이게 날(KST)을 바꿔 가며 부른다(한 날 한 줄이라 같은 날이면 첫 갈래만 보인다). 원장은 test_member_reads 의 참조 시험과 같다."""
    store = risk_store
    monkeypatch.setattr(routes, "get_store", lambda: store)
    owner = factories.ident(OWNER)
    project_id = routes.create_project(routes.ProjectBody(code="REFS-AA", name="참조", stage="DV1", classification="internal",
                                                          product_code="F7-2024"), ident=owner)["id"]
    routes.post_requirements(project_id, [routes.RequirementItem(kind="scenario", name="drop_1_2m_corner",
                                                                 value_json={"taxonomy_key": "deep", "required": True})],
                             ident=owner)
    snapshot = factories.make_snapshot(store, project_id, factories.fixture_adapter_results(), label="DV1")["snapshot_id"]
    target_key = factories.make_target(store, "snap", snapshot, agents=factories.agents())
    factories.seed_raw(store, "rr_character", {
        "id": "C1", "project_id": project_id, "owner_sub": OWNER, "facet": "intent", "tag": "char:structure:thin_stack",
        "tags_json": "[]", "statement": "s", "polarity": "observation", "by_json": "[]", "support_panels": 2, "support_targets": 1,
        "recall_eligible": 1, "needs_review": 0, "status": "panel", "created_at": 1, "updated_at": 1},
        reason="문헌 검색어(scholar_query)의 성격 태그 — 생산자는 패널 한 판 전부라 읽는 칸만 손으로 쓴다(test_member_reads 의 참조 시험과 같다)")
    brief_module._field_evidence_lines(store, brief_module._target_context(store, target_key), field_source.FieldSource(_Field()))
    noon = calendar.timegm((2026, 11, 3, 3, 0, 0))               # 2026-11-03 12:00 KST
    previous = common.set_clock(lambda: noon)
    try:
        for n, ref in enumerate(("req:drop_1_2m_corner", "voc:F7-2024#ISS-1", "paper:10.1000/xyz")):
            common.set_clock(lambda n=n: noon + n * DAY)
            assert routes.get_ref(ref, ident=ADMIN)["resolved"] is True, ref
    finally:
        common.set_clock(previous)
    assert [(r["project_id"], json.loads(r["after_json"])["day"]) for r in _read_rows(store)] == [
        (project_id, "2026-11-03"), (project_id, "2026-11-04"), (project_id, "2026-11-05")]


def test_a_predecessor_an_admin_names_by_the_bypass_is_noted(members):
    """앞 과제는 부른 사람이 구성원인 과제여야 하고 관리자는 있는 과제면 된다 — 그 과제를 우회로 가리킨 것이라 그 과제의 열람 줄이 선다.
    웹 화면(쿠키)의 관리자면 입구가 web 이다."""
    store, ids = members
    web_admin = _who(ADMIN.email)
    made = routes.create_project(routes.ProjectBody(code="ADM-NEXT", name="관리자의 다음 과제", classification="internal",
                                                    predecessor_project_id=ids["project"]), ident=web_admin)
    assert made["predecessor_project_id"] == ids["project"]
    assert [(r["project_id"], r["channel"], r["actor_verified"]) for r in _read_rows(store)] == [(ids["project"], "web", 1)]


def test_opening_a_target_on_a_diff_reads_the_diff_by_the_bypass(members):
    """대상(diff) 만들기는 그 비교를 읽는다(관리자는 우회로 읽는다 — OI-5) — 그 비교의 과제에 열람 줄이 선다(이 비교에는 대상이 이미 열려
    있어 409 지만 그 대상 열쇠까지 읽었다)."""
    store, ids = members
    got = _answer(lambda: routes.create_target(routes.TargetBody(kind="diff", ref_id=ids["diff"], consent=True), ident=ADMIN))
    assert got[:2] == ("E409", 409), got[:3]
    assert _read_projects(store) == [ids["project"]]
    assert _write_projects(store) == [ids["project"]]                 # 대상 과제의 쓰기 문(관리자 우회)도 지났다(AA-8)


# ---------------------------------------------------------------- 소비처 — 읽기는 사람 개입이 아니다
def test_a_read_row_never_counts_as_human_intervention(members):
    """대상 감사와 통합 보고서 '사람 개입 요약'(같은 조각 registry.target_audit_clause)에 열람 줄이 들지 않는다 — 과제 단위 자리(scope
    project)다. 과제 이력에는 선다(표시 없이 — 줄 자체가 관리자 열람이다). 반출에는 실리지 않는다(행 주인이 관리자다 — 다른 사람이 쓴 감사
    행과 같은 규칙)."""
    store, ids = members
    owner = factories.ident(OWNER)
    target_before = routes.get_target_audit(ids["target"], ident=owner)
    counts_before = registry.target_audit_counts(store, ids["target"])
    summary_before = _summary(store, ids["target"])

    for read in (routes.get_coverage, routes.get_registry, routes.get_report):
        read(ids["target"], ident=ADMIN)
    assert len(_read_rows(store)) == 1

    assert routes.get_target_audit(ids["target"], ident=owner) == target_before
    assert registry.target_audit_counts(store, ids["target"]) == counts_before
    assert _summary(store, ids["target"]) == summary_before
    assert not any(line.startswith("admin.read") for line in summary_before)
    entries = routes.get_project_audit(ids["project"], ident=owner)["entries"]
    read = [e for e in entries if e["action"] == "admin.read"]
    assert [(e["actor"], e["scope"], e["subject_id"], e["after"], e["via"]) for e in read] == [
        (ADMIN.email, "project", ids["project"], {"day": _kst_day(read[0]["at"])}, None)]
    lines = [json.loads(line) for line in export.iter_lines(store, OWNER, 0)][1:]
    assert not [line for line in lines if line["table"] == "rr_audit" and line["row"]["action"] == "admin.read"]
