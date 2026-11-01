# 관리자 접근 감사(사용자 결정 11-01 '쓰기 표시 + 읽기 하루 한 줄') — 관리자 우회로만 든 쓰기의 감사 행에는 표시
"""포털 plan §5.2.1 '멤버십' 행 — `identity.role ∈ risk_admin_roles` 는 멤버 행 없이 editor 로 통과하며 그 접근도 rr_audit 에 남는다. 앱은
쓰기 문(MB-14)과 웹 읽기 문(OI-5)에 관리자 우회를 두었지만 어느 쪽도 남기지 않았다 — 관리자의 쓰기는 감사 행의 행위자로만 남아 구성원의
쓰기와 가를 수 없었고 읽기는 흔적이 없었다(context-notes OI-5 · OI-7). 사용자 결정 11-01 이 고른 안이 이 파일의 계약이다.

- 쓰기 — 관리자가 아니었다면 막혔을 쓰기(구성원이 아니거나 그 쓰기에 모자란 역할)가 남기는 감사 행마다 after 의 `via` 칸이 "admin" 이다.
  조회(`GET /projects/{id}/audit` · `GET /targets/{key}/audit`)는 그 칸을 entry.via 로 올린다. 구성원으로도 할 수 있는 쓰기에는 싣지 않는다.

  실행:  .venv/bin/python -m pytest tests/rr/test_admin_access_audit.py
"""
from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from typing import Any

import pytest

from app import closure, identity, review_runner, routes, runner
from tests import factories
from tests import test_external_llm_jobs as external
from tests.rr import test_member_reads as member_reads
from tests.rr import test_review1_stranger as stranger
from tests.rr.test_member_reads import ADMIN, _forge
from tests.rr.test_review1_stranger import OTHER, OWNER
from tests.synth import review_rig as rig
from tests.test_review_cells import _target as _review_target

# 원장 픽스처 — 남 시험 표의 원장(검토 → 쟁점 → 종합) 사본에 편집자 · 보기를 들인 것, 두 과제(앞 · 뒤 리비전).
template = stranger.template
ledger = stranger.ledger
members = member_reads.members
two_projects = member_reads.two_projects


def _who(email: str, *, role: str = "admin", source: str = "cookie") -> identity.Identity:
    return dataclasses.replace(factories.ident(email), role=role, source=source)


ADMIN_EDITOR = _who("admin-editor@example.com")          # 관리자이면서 편집자 구성원
ADMIN_VIEWER = _who("admin-viewer@example.com")          # 관리자이면서 보기 구성원
ADMIN_OWNER = _who(OWNER)                                # 제 과제의 관리자


def _add(store, project_id: str, email: str, role: str) -> None:
    routes.put_members(project_id, routes.MembersBody(members=[routes.MemberItem(email=email, role=role)]),
                       ident=factories.ident(OWNER))


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


def _rows_after(store, mark: int) -> list[dict]:
    rows = []
    for row in store.query("SELECT rowid, actor, action, after_json FROM rr_audit WHERE rowid > ? ORDER BY rowid", (mark,)):
        after = json.loads(row["after_json"]) if row["after_json"] else None
        rows.append({"actor": row["actor"], "action": row["action"],
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
    못 한다). 제 과제의 관리자는 표시가 없다. 행위자는 늘 부른 사람이다."""
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
    assert sorted(r["action"] for r in rows) == sorted(write.actions), rows
    assert {(r["actor"], r["via"]) for r in rows} == {(who.email, _expected_via(write.need, caller))}, rows


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


def test_a_viewer_admin_writes_by_the_bypass(members):
    """보기 구성원인 관리자의 편집자 쓰기는 관리자이기 때문에 든 것이다(보기는 403) — 표시다."""
    store, ids = members
    _add(store, ids["project"], ADMIN_VIEWER.email, "viewer")
    mark = _last(store)
    routes.put_verdict(ids["target"], routes.VerdictBody(verdict="go"), ident=ADMIN_VIEWER)
    assert [(r["action"], r["via"]) for r in _rows_after(store, mark)] == [("verdict.final", "admin")]


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

