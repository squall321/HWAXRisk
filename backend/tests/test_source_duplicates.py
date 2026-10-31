# 같은 원천을 두 과제에 붙일 때의 알림(duplicate_of, plan §8.2.3) — 막지 않고 알리되 부른 사람이 구성원인 과제만 싣는다
"""`POST /projects/{id}/sources` 는 같은 `ref_key` 를 가진 다른 과제가 있으면 등록은 그대로 하고 응답의 `duplicate_of` 로 알린다 —
같은 CAD 를 두 관점으로 심사하는 것이 정당할 수 있어 막지 않는다(plan §8.2.3). 싣는 것은 부른 사람이 구성원(소유 · 멤버)인 과제뿐이다
— 남의 과제는 목록에도 수로도 드러내지 않는다(context-notes D45 '구성원은 하나').
"""
from __future__ import annotations

import json

import app.mcp_server as srv
from app import routes
from tests import factories

OWNER = factories.OWNER
OTHER = "stranger@example.com"
REF = {"stepforge_project_id": "sf-dup-1"}


def _add(store, project_id: str, who: str, ref: dict | None = None) -> dict:
    with factories.routes_store(store):
        return routes.add_source(project_id, routes.SourceBody(kind="mcad", ref=dict(ref or REF)),
                                 ident=factories.ident(who))


def _source(store, project_id: str) -> dict:
    return dict(store.query_one(
        "SELECT s.created_at, s.ref_key, p.code FROM rr_sources s JOIN rr_projects p ON p.id = s.project_id"
        " WHERE s.project_id = ?", (project_id,)))


def test_the_same_source_on_a_second_project_is_reported_and_still_registered(risk_store):
    first = factories.make_project(risk_store)
    second = factories.make_project(risk_store)
    assert "duplicate_of" not in _add(risk_store, first, OWNER)

    out = _add(risk_store, second, OWNER)

    before = _source(risk_store, first)
    assert out["ok"] is True
    assert out["duplicate_of"] == [{"project_id": first, "code": before["code"], "owner_sub": OWNER,
                                    "created_at": before["created_at"]}]
    # 막지 않는다 — 두 과제에 같은 ref_key 의 소스 행이 하나씩 선다.
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_sources WHERE ref_key = ?",
                                (before["ref_key"],))["n"] == 2
    # 같은 과제에 같은 소스를 다시 붙여도(갱신) 자기 과제는 싣지 않는다.
    assert [d["project_id"] for d in _add(risk_store, second, OWNER)["duplicate_of"]] == [first]
    # 다른 원천이면 알림이 없다.
    assert "duplicate_of" not in _add(risk_store, second, OWNER, {"stepforge_project_id": "sf-other"})


def test_a_strangers_project_is_neither_named_nor_counted(risk_store):
    mine = factories.make_project(risk_store)
    _add(risk_store, mine, OWNER)
    theirs = factories.make_project(risk_store, owner=OTHER)

    out = _add(risk_store, theirs, OTHER)

    assert "duplicate_of" not in out
    assert mine not in json.dumps(out, ensure_ascii=False)


def test_a_member_is_told_about_the_project_they_belong_to(risk_store):
    shared = factories.make_project(risk_store)
    _add(risk_store, shared, OWNER)
    with factories.routes_store(risk_store):
        routes.put_members(shared, routes.MembersBody(members=[routes.MemberItem(email=OTHER, role="viewer")]),
                           ident=factories.ident(OWNER))
    theirs = factories.make_project(risk_store, owner=OTHER)

    out = _add(risk_store, theirs, OTHER)

    assert [(d["project_id"], d["owner_sub"]) for d in out["duplicate_of"]] == [(shared, OWNER)]


def test_the_mcp_entry_carries_the_same_notice(risk_store, monkeypatch):
    """MCP risk_add_source 는 같은 라우트를 감싼다 — 알림이 그대로 실린다."""
    import asyncio

    first = factories.make_project(risk_store)
    second = factories.make_project(risk_store)
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    factories.act_as_delegate(monkeypatch, OWNER)

    made = asyncio.run(srv.risk_add_source(project_id=first, kind="mcad", ref=dict(REF)))
    out = asyncio.run(srv.risk_add_source(project_id=second, kind="mcad", ref=dict(REF)))

    assert "error" not in made and "duplicate_of" not in made, made
    assert "error" not in out, out
    assert [d["project_id"] for d in out["duplicate_of"]] == [first]
