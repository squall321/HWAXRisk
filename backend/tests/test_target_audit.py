# 대상 단위 감사 조회(GET /targets/{key}/audit, plan §8.2.3) — 그 대상의 사람 행위만, 구성원(viewer 이상)만 읽는다
"""과제 단위 감사(`GET /projects/{id}/audit`)만 있던 자리에 대상 단위를 더한다. 감사 표에는 대상 열이 없어 행위의 자리(scope ·
subject_id)로 그 대상의 행을 가린다 — 규칙은 `registry.target_audit_clause` 하나이고 통합 보고서의 '사람 개입 요약' 도 같은 조각을
센다(test_brief_exclude 가 그 수를 본다). 구성원이 아닌 남에게는 없는 대상과 같은 404 다(남 숨김 — test_review1_stranger 의 표에도
있다).
"""
from __future__ import annotations

from collections import Counter

import pytest

from app import planner, registry, routes
from app.common import now_epoch
from app.errors import AppError
from tests import factories
from tests.test_project_patch import _submit
from tests.test_wiring_regressions import _agents, _seed

OWNER = "owner@example.com"
VIEWER = "viewer@example.com"
OTHER = "stranger@example.com"
TARGET = "diff:d1"


def _audit(store, *, at: int, **kw) -> str:
    audit_id = routes._audit(store, OWNER, **kw)
    store.execute("UPDATE rr_audit SET at = ? WHERE id = ?", (at, audit_id))
    return audit_id


@pytest.fixture
def ledger(risk_store, monkeypatch):
    """대상 diff:d1(과제 p1 · diff d1 — 앞 s0 · 뒤 s1) 과 같은 과제의 다른 대상 diff:d10 에 사람 행위를 고루 적는다."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    _seed(risk_store, owner=OWNER)
    now = now_epoch()
    risk_store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, external_sync_json,"
        " report_ids_json, level, created_at, updated_at) VALUES ('diff:d10', ?, 'diff', 'd10', 'p1', 'h10', '{}', '[]',"
        " 'C0', ?, ?)", (OWNER, now, now))
    planner.freeze_roster(risk_store, "diff:d10", OWNER, _agents({"mech": 1}))
    panel = planner.plan_next_panel(risk_store, TARGET, "B")
    # 패널 결과 하나 — 그 finding · 등록부 클러스터를 가리키는 행(큐 결정 · 공개 토글)도 이 대상의 것이다.
    finding = _submit(risk_store, panel, "web", TARGET)
    risk_store.execute(
        "INSERT INTO rr_jobs(id, target_key, owner_sub, tier, state, created_at, updated_at)"
        " VALUES ('job-mine', ?, ?, 'B', 'queued', ?, ?), ('job-other', 'diff:d10', ?, 'B', 'queued', ?, ?)",
        (TARGET, OWNER, now, now, OWNER, now, now))
    mine = [
        dict(scope="target", subject_id=TARGET, project_id="p1", action="target.flow", at=100),
        dict(scope="coverage", subject_id=f"{TARGET}#mech-a000", project_id="p1", action="coverage.skip", at=110),
        dict(scope="coverage", subject_id=TARGET, project_id="p1", action="coverage.undefer", at=120),
        dict(scope="registry", subject_id=f"{TARGET}#c0ffee000001", action="registry.merge", at=130),
        dict(scope="snapshot", subject_id="s1", action="gate.ack", at=140),
        dict(scope="snapshot", subject_id="s0", action="gate.ack", at=150),
        dict(scope="job", subject_id="job-mine", project_id="p1", action="brief.exclude", at=160),
        dict(scope="panel", subject_id=panel["id"], project_id="p1", action="panel.repersist", at=170),
        # 지운 사람 finding 은 rr_findings 에 없다 — 대상 열쇠 접두로 이 대상의 것이다.
        dict(scope="finding", subject_id=f"{TARGET}#H1", project_id="p1", action="finding.delete", at=180),
        dict(scope="finding", subject_id=finding["finding_id"], action="curation.decide", at=185),
        dict(scope="registry", subject_id=finding["cluster_key"], action="registry.visibility", at=187),
    ]
    theirs = [
        dict(scope="target", subject_id="diff:d10", project_id="p1", action="target.flow", at=105),
        # 'diff:d1' 로 시작하지만 다른 대상이다 — 접두는 '#' 까지 본다.
        dict(scope="coverage", subject_id="diff:d10#mech-a000", project_id="p1", action="coverage.skip", at=115),
        dict(scope="job", subject_id="job-other", project_id="p1", action="brief.exclude", at=165),
        dict(scope="snapshot", subject_id="s9", action="gate.ack", at=145),
        dict(scope="finding", subject_id="other-panel#F1", action="curation.decide", at=186),
        dict(scope="registry", subject_id="c0ffeec0ffee", action="registry.visibility", at=188),
        # 과제 단위 행은 과제 감사의 몫이다.
        dict(scope="project", subject_id="p1", project_id="p1", action="member.put", at=190),
    ]
    for row in mine + theirs:
        _audit(risk_store, **row)
    return risk_store, mine


def _seen(out: dict) -> set[tuple[str, str, str]]:
    return {(e["scope"], e["subject_id"], e["action"]) for e in out["entries"]}


def test_a_member_reads_only_this_targets_human_actions(ledger):
    store, mine = ledger
    with factories.routes_store(store):
        routes.put_members("p1", routes.MembersBody(members=[routes.MemberItem(email=VIEWER, role="viewer")]),
                           ident=factories.ident(OWNER))
        owner = routes.get_target_audit(TARGET, ident=factories.ident(OWNER))
        viewer = routes.get_target_audit(TARGET, ident=factories.ident(VIEWER))

    want = {(r["scope"], r["subject_id"], r["action"]) for r in mine}
    assert _seen(owner) == want and owner["total"] == len(mine) == 11
    assert viewer["entries"] == owner["entries"]
    # 최근 것이 먼저이고 칸은 과제 감사와 같다.
    assert [e["at"] for e in owner["entries"]] == sorted((r["at"] for r in mine), reverse=True)
    assert set(owner["entries"][0]) == {"id", "actor", "actor_verified", "channel", "scope", "subject_id", "project_id",
                                        "action", "before", "after", "reason", "at"}
    # 보고서의 '사람 개입 요약' 이 세는 수와 같은 조각이다.
    assert registry.target_audit_counts(store, TARGET) == dict(Counter(r["action"] for r in mine))


def test_a_stranger_gets_the_missing_target_answer(ledger):
    store, _mine = ledger
    with factories.routes_store(store), pytest.raises(AppError) as theirs:
        routes.get_target_audit(TARGET, ident=factories.ident(OTHER))
    with factories.routes_store(store), pytest.raises(AppError) as gone:
        routes.get_target_audit("diff:no-such", ident=factories.ident(OTHER))
    assert (theirs.value.code, theirs.value.http_status) == ("E404", 404)
    assert theirs.value.message.replace(TARGET, "<t>") == gone.value.message.replace("diff:no-such", "<t>")


def test_filters_and_the_limit_ceiling(ledger):
    store, _mine = ledger
    with factories.routes_store(store):
        acks = routes.get_target_audit(TARGET, action="gate.ack", ident=factories.ident(OWNER))
        late = routes.get_target_audit(TARGET, since=150, ident=factories.ident(OWNER))
        window = routes.get_target_audit(TARGET, since=110, until=130, ident=factories.ident(OWNER))
        page = routes.get_target_audit(TARGET, limit=2, offset=1, ident=factories.ident(OWNER))
        wide = routes.get_target_audit(TARGET, limit=10_000, ident=factories.ident(OWNER))

    assert _seen(acks) == {("snapshot", "s1", "gate.ack"), ("snapshot", "s0", "gate.ack")} and acks["total"] == 2
    assert [e["at"] for e in late["entries"]] == [187, 185, 180, 170, 160, 150]
    assert [e["at"] for e in window["entries"]] == [130, 120, 110]
    assert [e["at"] for e in page["entries"]] == [185, 180] and page["total"] == 11
    assert wide["limit"] == routes.TARGET_AUDIT_LIMIT_MAX == 200
