# 편집자 쓰기 · 대응 결정 시험(사용자 결정 10-31) — 대응 결정은 두 과제의 주인 · 편집자만 하고 남의 원장 행을 뒤집지 못한다, 쓰기 경로마다 주인 · 편집자 · 보기 · 남
"""대응 결정(POST /sameas/decide 의 confirm · reject)은 pair_key 의 과제(intra 는 하나, pair 는 둘 다)의 주인 · 편집자만 한다 — 행은 그 과제
주인의 원장에 서고(키 전파도 그 주인으로 돈다) 결정한 사람은 decided_by 다. 이미 다른 사람의 행이 그 자리에 있으면 덮지 않고 거절한다(조용히
넘기지 않는다). 종전에는 upsert 에 주인 거름이 없어 그 네 값(scope · pair_key · 두 stable 키)을 아는 누구나 주인의 행을 뒤집었다(MB-11 — 구성원
읽기가 보기에게 그 값을 열었다).

  실행:  .venv/bin/python -m pytest tests/rr/test_editor_writes.py
"""
from __future__ import annotations

import json

import pytest

import app.mcp_server as srv
from app import routes
from tests import factories
from tests.rr.test_member_reads import EDITOR, ONE_SIDE, OTHER, OWNER, VIEWER, two_projects  # noqa: F401 — 두 과제 픽스처
from tests.rr.test_review1_stranger import _answer, _mcp

ONE_SIDE_EDITOR = "one-side-editor@example.com"      # 대상 과제만의 편집자


@pytest.fixture
def world(request):
    """두 과제 원장(tests/rr/test_member_reads.py 의 two_projects) — 앞 · 뒤 리비전, 편집자 · 보기는 두 과제의 구성원이다."""
    return request.getfixturevalue("two_projects")


def _ledger_row(store, pair_key: str) -> dict | None:
    row = store.query_one("SELECT owner_sub, status, decided_by FROM rr_sameas WHERE pair_key = ?", (pair_key,))
    return dict(row) if row is not None else None


def _pending(w: dict) -> tuple[dict, dict]:
    """주인이 본 대응표와 그 pending 한 줄의 확정 결정."""
    table = routes.get_sameas(base=w["base"], target=w["target"], ident=factories.ident(OWNER))
    row = table["pairs"][0]
    return table, {"decision": "confirm", "scope": "pair", "pair_key": table["pair_key"], "a_stable": row["a_stable"],
                   "b_stable": row["b_stable"], "snapshot_id": w["target"]}


def test_a_viewer_or_a_stranger_cannot_flip_the_owners_sameas_decision(world):
    """주인이 확정한 대응을 보기 구성원이 같은 네 값으로 reject 하면 403 role_insufficient, 남은 없는 과제와 같은 404 이고 주인의 행은
    그대로다(주인 · 확정 · 정한 사람). 종전에는 보기의 reject 가 200 이고 행이 rejected · decided_by=보기로 뒤집혔다(원장 사본 탐침 — MB-11)."""
    w = world
    table, item = _pending(w)
    routes.post_sameas_decide([item], ident=factories.ident(OWNER))
    decided = _ledger_row(w["store"], table["pair_key"])
    assert decided == {"owner_sub": OWNER, "status": "confirmed", "decided_by": OWNER}
    reject = {**item, "decision": "reject"}
    viewer = _answer(lambda: routes.post_sameas_decide([reject], ident=factories.ident(VIEWER)))
    assert (viewer[0], viewer[1]) == ("role_insufficient", 403), viewer[:3]
    stranger = _answer(lambda: routes.post_sameas_decide([reject], ident=factories.ident(OTHER)))
    assert (stranger[0], stranger[1]) == ("E404", 404), stranger[:3]
    assert _ledger_row(w["store"], table["pair_key"]) == decided
    assert routes.get_sameas(base=w["base"], target=w["target"], ident=factories.ident(OWNER))["pending_n"] == 0


@pytest.mark.parametrize("side", ["base_project", "target_project"])
def test_a_pair_decision_needs_editor_or_owner_on_both_projects(world, side):
    """pair 결정은 두 과제 모두의 주인 · 편집자여야 한다 — 그 결정이 두 과제의 노드를 잇고 두 과제 사이 비교의 대응이 된다(plan §2.6.1 ·
    §2.6.2 — pair_key 는 정렬한 두 과제 id). 한쪽 과제만의 편집자는 다른 과제의 구성원이 아니라 그 과제가 없는 것과 같은 404 다(어느 쪽이든)."""
    w = world
    other = "target_project" if side == "base_project" else "base_project"
    routes.put_members(w[side], routes.MembersBody(members=[routes.MemberItem(email=ONE_SIDE_EDITOR, role="editor")]),
                       ident=factories.ident(OWNER))
    table, item = _pending(w)
    one_side = _answer(lambda: routes.post_sameas_decide([item], ident=factories.ident(ONE_SIDE_EDITOR)))
    assert (one_side[0], one_side[1]) == ("E404", 404) and w[other] in one_side[2], one_side[:3]
    assert _ledger_row(w["store"], table["pair_key"]) is None


def test_a_pair_over_two_owners_cannot_be_written_to_one_ledger(world):
    """두 과제의 주인이 다르면(편집자가 두 사람의 과제를 다 편집한다) 그 결정을 적을 한 원장이 없어 422 pair_owners_differ 다."""
    w = world
    elsewhere = factories.make_project(w["store"], owner=OTHER, code="OTHER-DV")
    routes.put_members(elsewhere, routes.MembersBody(members=[routes.MemberItem(email=EDITOR, role="editor")]),
                       ident=factories.ident(OTHER))
    key = "|".join(sorted([w["target_project"], elsewhere]))
    got = _answer(lambda: routes.post_sameas_decide([{"decision": "confirm", "scope": "pair", "pair_key": key, "a": "s:a",
                                                      "b": "s:b"}], ident=factories.ident(EDITOR)))
    assert (got[0], got[1]) == ("pair_owners_differ", 422), got[:3]
    assert _ledger_row(w["store"], key) is None


def test_an_editor_decides_into_the_owners_ledger_and_the_rekey_runs_for_the_owner(world):
    """편집자의 결정은 과제 주인의 원장 행이 된다(owner_sub 주인 · decided_by 편집자) — 그 주인의 대응표 · 비교가 읽는 원장이다. 주인이 확정한
    것을 편집자가 reject 하면 확정을 뒤집는 키 전파(rekey)가 행의 주인으로 돌고 감사 행의 행위자는 편집자다."""
    w = world
    store = w["store"]
    table, item = _pending(w)
    routes.post_sameas_decide([item], ident=factories.ident(EDITOR))
    assert _ledger_row(store, table["pair_key"]) == {"owner_sub": OWNER, "status": "confirmed", "decided_by": EDITOR}
    assert routes.get_sameas(base=w["base"], target=w["target"], ident=factories.ident(OWNER))["pending_n"] == 0
    out = routes.post_sameas_decide([{**item, "decision": "reject"}], ident=factories.ident(EDITOR))
    assert out["results"][0]["rekey"] is not None
    assert _ledger_row(store, table["pair_key"]) == {"owner_sub": OWNER, "status": "rejected", "decided_by": EDITOR}
    audit = [dict(r) for r in store.query("SELECT actor, owner_sub, subject_id FROM rr_audit WHERE action = 'rekey'")]
    assert [(a["actor"], a["subject_id"].split(":")[0]) for a in audit] == [(EDITOR, "sameas")], audit


def test_a_foreign_ledger_row_on_the_same_key_is_refused_not_overwritten(world):
    """그 네 값 자리에 이미 다른 사람의 행이 있으면(고침 전의 길로 남이 먼저 쓴 행) 주인의 결정도 그 행을 덮지 않고 409 로 거절한다 — 조용히
    넘기지 않는다. 남의 행은 그대로다."""
    w = world
    table, item = _pending(w)
    factories.seed_raw(w["store"], "rr_sameas", {
        "id": "sa-foreign", "owner_sub": OTHER, "scope": "pair", "pair_key": table["pair_key"], "a_stable": min(
            item["a_stable"], item["b_stable"]), "b_stable": max(item["a_stable"], item["b_stable"]), "method": "manual",
        "score": 1.0, "status": "rejected", "decided_by": OTHER, "decided_at": 1},
        reason="고침 전의 대응 결정이 남긴 남의 행 — 이제 결정은 그 과제의 주인 · 편집자만 하고 남의 행을 덮지 않는다")
    for who in (OWNER, EDITOR):
        got = _answer(lambda who=who: routes.post_sameas_decide([item], ident=factories.ident(who)))
        assert (got[0], got[1]) == ("sameas_row_foreign", 409), (who, got[:3])
        assert OTHER not in got[2], got[2]                      # 남의 이메일을 흘리지 않는다
    assert _ledger_row(w["store"], table["pair_key"]) == {"owner_sub": OTHER, "status": "rejected", "decided_by": OTHER}


def test_the_mcp_decision_tool_follows_the_same_rule(world, monkeypatch):
    """MCP risk_decide_sameas 도 같은 문이다 — 편집자는 주인의 원장에 결정하고 보기는 role_insufficient 다(웹 라우트를 그대로 부른다)."""
    w = world
    table, item = _pending(w)
    decisions = [{"a_stable": item["a_stable"], "b_stable": item["b_stable"], "decision": "confirm"}]
    factories.act_as_delegate(monkeypatch, VIEWER)
    assert _mcp(lambda: srv.risk_decide_sameas(base_snapshot_id=w["base"], target_snapshot_id=w["target"],
                                               decisions=decisions))[0] == "role_insufficient"
    factories.act_as_delegate(monkeypatch, EDITOR)
    out = json.loads(_mcp(lambda: srv.risk_decide_sameas(base_snapshot_id=w["base"], target_snapshot_id=w["target"],
                                                         decisions=decisions))[2])
    assert out["updated"] == 1, out
    assert _ledger_row(w["store"], table["pair_key"]) == {"owner_sub": OWNER, "status": "confirmed", "decided_by": EDITOR}


@pytest.mark.parametrize("scope", ["intra", "pair"])
def test_a_decision_key_that_names_no_known_project_is_the_missing_answer(world, scope):
    """pair_key 가 이 박스에 없는 과제를 가리키면 남의 과제와 같은 404 다(있는지를 흘리지 않는다). 열쇠 꼴이 scope 와 맞지 않으면(pair 인데 과제
    하나 · intra 인데 둘) 400 이다."""
    w = world
    key = "no-such-project" if scope == "intra" else f"no-such-project|{w['target_project']}"
    got = _answer(lambda: routes.post_sameas_decide([{"decision": "confirm", "scope": scope, "pair_key": key, "a": "s:a",
                                                      "b": "s:b"}], ident=factories.ident(OWNER)))
    assert (got[0], got[1]) == ("E404", 404), got[:3]
    malformed = w["target_project"] if scope == "pair" else f"{w['base_project']}|{w['target_project']}"
    bad = _answer(lambda: routes.post_sameas_decide([{"decision": "confirm", "scope": scope, "pair_key": malformed,
                                                      "a": "s:a", "b": "s:b"}], ident=factories.ident(OWNER)))
    assert (bad[0], bad[1]) == ("E100", 400), bad[:3]
