# 대상 단위 감사 조회(GET /targets/{key}/audit, plan §8.2.3) — 그 대상의 사람 행위만, 구성원(viewer 이상)만 읽는다
"""과제 단위 감사(`GET /projects/{id}/audit`)만 있던 자리에 대상 단위를 더한다. 감사 표에는 대상 열이 없어 행위의 자리(scope ·
subject_id)로 그 대상의 행을 가린다 — 규칙은 `registry.target_audit_clause` 하나이고 통합 보고서의 '사람 개입 요약' 도 같은 조각을
센다(test_brief_exclude 가 그 수를 본다). 구성원이 아닌 남에게는 없는 대상과 같은 404 다(남 숨김 — test_review1_stranger 의 표에도
있다).
"""
from __future__ import annotations

import json
from collections import Counter

import pytest

from app import planner, registry, routes
from app.common import now_epoch
from app.errors import AppError
from tests import factories
from tests.test_project_patch import _human_body, _submit
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


def _queue_merge(store, owner: str, key_a: str) -> str:
    """야간 스캔이 그 소유자의 큐에 올리는 근접 중복 쌍 한 항목(nightly.scan_cluster_merge 의 payload 꼴)."""
    queue_id = f"q-merge-{owner.split('@', 1)[0]}"
    store.execute("INSERT INTO rr_curation_queue(id, owner_sub, kind, payload_json, status, created_at)"
                  " VALUES (?, ?, 'cluster_merge', ?, 'open', 1)",
                  (queue_id, owner, json.dumps({"a": key_a, "b": "0123456789ab", "family_key": "f", "score": 0.9})))
    return queue_id


def test_registry_actions_on_a_shared_cluster_key_stay_with_their_owner_and_target(risk_store):
    """클러스터 열쇠는 내용 해시라 대상 · 소유자를 가로질러 같다(rr_registry 의 열쇠는 (target_key, cluster_key)). 남이 자기 대상의
    같은 열쇠에 한 공개 토글 · 큐 결정(사유 글)은 이 대상의 감사에도 보고서의 '사람 개입 요약' 에도 실리지 않는다. 대상을 골라 한 공개
    토글은 그 대상의 것이고, 대상을 고르지 않은 소유자 단위 행위(큐 결정)는 그 소유자의 대상마다 실린다."""
    store = risk_store
    _seed(store, owner=OWNER)                                       # p1 · diff:d1
    now = now_epoch()
    for project_id, owner, target_key in (("p2", OTHER, "snap:z9"), ("p3", OWNER, "snap:mine2")):
        store.execute("INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
                      " VALUES (?, ?, ?, '과제', ?, ?)", (project_id, owner, f"PRJ-{project_id}", now, now))
        store.execute("INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, external_sync_json,"
                      " report_ids_json, level, created_at, updated_at) VALUES (?, ?, 'snap', ?, ?, 'h', '{}', '[]', 'C0', ?, ?)",
                      (target_key, owner, target_key.split(":", 1)[1], project_id, now, now))
    # 웹 폼 꼴(코드 · 대상 없음) — 세 대상의 사람 finding 이 같은 cluster_key 를 갖는다.
    body = _human_body(mechanism="thermal.cte_mismatch", mechanism_detail=None, change_kind=None, subject_key=None)
    with factories.routes_store(store):
        keys = {routes.create_human_finding(target_key, body, ident=factories.ident(who))["cluster_key"]
                for target_key, who in ((TARGET, OWNER), ("snap:z9", OTHER), ("snap:mine2", OWNER))}
        assert len(keys) == 1
        (key,) = keys
        # 남 — 자기 대상의 같은 열쇠에 공개 토글과 큐 결정(사유 글).
        routes.put_registry_visibility(key, routes.RegistryVisibilityBody(visibility="org"), ident=factories.ident(OTHER))
        routes.put_curation(_queue_merge(store, OTHER, key),
                            routes.CurationDecisionBody(decision="reject", reason="남의 과제 내부 사정 메모"),
                            ident=factories.ident(OTHER))
        # 나 — 다른 내 대상을 골라 한 공개 토글(그 대상의 것)과 대상을 고르지 않은 큐 결정(내 대상마다).
        routes.put_registry_visibility(key, routes.RegistryVisibilityBody(visibility="org", target_key="snap:mine2"),
                                       ident=factories.ident(OWNER))
        routes.put_curation(_queue_merge(store, OWNER, key), routes.CurationDecisionBody(decision="reject", reason="내 결정"),
                            ident=factories.ident(OWNER))
        mine = routes.get_target_audit(TARGET, ident=factories.ident(OWNER))
        mine_too = routes.get_target_audit("snap:mine2", ident=factories.ident(OWNER))
        theirs = routes.get_target_audit("snap:z9", ident=factories.ident(OTHER))

    def seen(out: dict) -> list[tuple]:
        return sorted((e["action"], e["actor"], e["subject_id"], e["reason"]) for e in out["entries"])

    assert seen(mine) == sorted([("finding.create", OWNER, f"{TARGET}#H1", None), ("curation.decide", OWNER, key, "내 결정")])
    assert seen(mine_too) == sorted([("finding.create", OWNER, "snap:mine2#H1", None),
                                     ("registry.visibility", OWNER, f"snap:mine2#{key}", None),
                                     ("curation.decide", OWNER, key, "내 결정")])
    assert seen(theirs) == sorted([("finding.create", OTHER, "snap:z9#H1", None), ("registry.visibility", OTHER, key, None),
                                   ("curation.decide", OTHER, key, "남의 과제 내부 사정 메모")])
    # 보고서의 '사람 개입 요약' 도 같은 조각이다 — 남의 토글 · 결정과 다른 대상을 고른 토글을 세지 않는다.
    assert registry.target_audit_counts(store, TARGET) == {"curation.decide": 1, "finding.create": 1}
    minutes = registry.build_report(store, TARGET)["blocks"]["minutes"]
    summary = "\n".join(minutes).split("[사람 개입 요약]", 1)[1].strip().split("\n")
    assert summary == ["curation.decide=1", "finding.create=1"]
