# 구성원 읽기 표(사용자 결정 10-31 — 계획서대로 구성원도 읽는다) — 과제에 딸린 것을 읽는 REST 경로 · MCP 읽기 도구 전부를 주인 · 편집자 · 보기 · 남으로 걷는다
"""경로 목록은 남 시험 표(tests/rr/test_review1_stranger.py 의 GET_CASES — 라우터의 읽기 경로 전부와 같음을 그 파일이 지킨다)를 그대로
쓴다. 편집자 · 보기는 주인과 같은 답(글 전체 — 부른 사람에 매인 칸만 뺀다)을 받고, 남은 없는 것과 같은 답이다. 표에서 빼는 경로 ·
도구는 까닭을 적는다. 원장은 남 시험 표와 같은 생산자 사슬(검토 → 쟁점 → 종합)이고 주인이 put_members 로 편집자 · 보기를 들인다(포털
plan §9.2 (14) 두 계정 시나리오 — 구성원은 스냅샷 · 타깃 · 등록부를 읽는다).

구성원 길은 그 과제 주인의 행만 고른다 — 하위 표의 owner_sub 는 과제 주인의 복제라, 주인이 다른 행은 고침 전의 들여오기가 남긴 것이다
(RD-10). 그런 행은 구성원 길(REST · MCP)로 읽히지도 목록에 서지도 않고, 주인 아닌 사람의 owner 멤버 행은 MCP 에서도 역할이 아니다.
쓰기는 그대로다 — 보기는 제 행만 쓰는 두 경로 말고는 어느 쓰기 경로도 지나지 못한다.

  실행:  .venv/bin/python -m pytest tests/rr/test_member_reads.py
"""
from __future__ import annotations

import copy
import json
from typing import Any

import pytest

import app.mcp_server as srv
from app import brief as brief_module
from app import field_source, routes, runner
from tests import factories
from tests.rr.test_review1_stranger import (CASES, GET_CASES, GET_EXPECT, MCP_CASES, MCP_EXEMPT, OTHER, OWNER, P, _answer,
                                            _mcp, ledger, template)  # noqa: F401 — 원장 픽스처 둘을 이 모듈에서 쓴다

EDITOR = "editor@example.com"
VIEWER = "viewer@example.com"
MEMBERS = (EDITOR, VIEWER)

# 구성원이 주인과 같은 답을 받지 않는 읽기 — 까닭이 있는 것만.
MEMBER_GET_EXEMPT: dict[tuple[str, str], str] = {
    ("GET", P + "/targets/{target_key}/brief"): (
        "읽기가 아니다 — 패널을 편성하고 패널마다 brief_token 을 새로 낸다(앞서 복사한 토큰이 무효가 된다). 토큰은 결과를 낼 사람의 열쇠라"
        " 쓰기 문(그 대상 과제의 편집자 이상 — MB-14)이다 — 보기는 403"),
}
# 부른 사람에 매인 칸 — 구성원과 주인의 답이 이 칸에서만 갈린다.
CALLER_FIELDS: dict[tuple[str, str], tuple[str, ...]] = {
    ("GET", P + "/part-keys/{ckey}"): ("mine",),
}

# MCP — 읽기 도구는 구성원이 주인과 같은 답을 받는다. 구성원이 주인과 같은 답을 받지 않는 것과 쓰기 도구는 까닭과 함께 따로 적는다(새
# 도구는 셋 가운데 하나로 들어와야 한다).
MCP_READS: tuple[str, ...] = (
    "risk_get_coverage", "risk_list_panels", "risk_get_panel_transcript", "risk_get_precedents", "risk_similar_projects",
    "risk_get_snapshot", "risk_get_diff", "risk_get_registry", "risk_claims_for_ref", "risk_get_sameas", "risk_get_units",
    "risk_get_cells", "risk_get_expert_report", "risk_get_issues", "risk_get_report",
)
MCP_MEMBER_EXEMPT: dict[str, str] = {
    "risk_get_brief": ("브리프 토큰의 패널을 동결하고 패널 품질을 쓴다 — 결과를 낼 수 있는 사람(그 대상 과제의 주인 · 편집자, MB-14)만이고"
                       " 보기는 role_insufficient 다(RV-1 — tests/rr/test_editor_writes.py)"),
    "risk_next_step": ("주인의 진행 길잡이 — 주인 과제의 단계만 걷는다. 편집자도 그 쓰기(소스 · 캡처 · 대상 · 잡)를 하게 됐지만(MB-14)"
                       " 길잡이는 넓히지 않았다(남긴 것)"),
}
MCP_WRITES: tuple[str, ...] = (
    "risk_create_project", "risk_submit_panel_result", "risk_add_finding", "risk_add_source", "risk_capture_snapshot",
    "risk_ack_gate", "risk_decide_sameas", "risk_create_diff", "risk_open_target", "risk_start_job", "risk_job_action",
    "risk_repersist_panel", "risk_set_ecad_board",
)
# 보기가 지나는 쓰기 — 남의 것을 가리키지 않고 부른 사람 자신의 행을 쓴다. 대응 결정은 그 과제의 주인 · 편집자만 하게 돼(MB-13) 이 표에서
# 빠졌다.
VIEWER_WRITES_OWN: dict[tuple[str, str], str] = {
    ("POST", P + "/projects"): "제 과제를 만든다(앞 과제가 구성원 과제라 계보가 선다 — 남이면 404)",
    ("POST", P + "/projects/{project_id}/requirements/inherit"): (
        "제 과제로 승계한다 — 원본은 보기가 읽는 구성원 과제이고 쓰는 것은 제 과제의 요구다(MB-14)"),
}


@pytest.fixture
def members(request):
    """남 시험 표의 원장 사본 + 주인이 들인 편집자 · 보기. 대상에 RA 보고서 포인터를 하나 달아 보고서 목록도 빈 목록이 아니게 한다."""
    store, ids = request.getfixturevalue("ledger")
    routes.put_members(ids["project"], routes.MembersBody(members=[routes.MemberItem(email=EDITOR, role="editor"),
                                                                  routes.MemberItem(email=VIEWER, role="viewer")]),
                       ident=factories.ident(OWNER))
    store.execute("UPDATE rr_targets SET report_ids_json = '[\"rpt-member-1\"]' WHERE target_key = ?", (ids["target"],))
    return store, ids


def _body(answer: tuple, drop: tuple[str, ...] = ()) -> Any:
    """답의 글을 값으로 — 부른 사람에 매인 칸(`drop`)은 뺀다."""
    value = json.loads(answer[2])
    return {k: v for k, v in value.items() if k not in drop} if isinstance(value, dict) else value


# ---------------------------------------------------------------- REST 읽기 표
def test_the_member_table_is_the_stranger_reading_table_less_its_written_exemptions():
    """구성원 표의 경로 == 남 시험 표의 읽기 경로(과제에 딸린 것을 받는 경로 전부 — 그 표가 라우터와 같음을 지킨다) − 까닭을 적은 면제."""
    assert set(MEMBER_GET_EXEMPT) <= set(GET_CASES) and all(MEMBER_GET_EXEMPT.values())
    assert set(CALLER_FIELDS) <= set(GET_CASES) - set(MEMBER_GET_EXEMPT)


@pytest.mark.parametrize("case", sorted(set(GET_CASES) - set(MEMBER_GET_EXEMPT)), ids=lambda c: f"{c[0]} {c[1][len(P):]}")
def test_editors_and_viewers_read_what_the_owner_reads(members, case):
    """편집자 · 보기는 주인과 같은 답(200, 글 전체)이다 — 종전에는 과제 상세 · 목록 · 멤버 · 이력 · 키 대장 · 원장 참조 말고는 없는 것과 같은
    404 였다(스냅샷 · 대상 · 진행판 · 성격 · 유사 · 요구 · 등록부 · 패널 · 보고서). 남은 그대로 없는 것과 같은 답이다(과제로 거르는 목록은
    빈 목록)."""
    store, ids = members
    call, _supplied = GET_CASES[case]
    drop = CALLER_FIELDS.get(case, ())
    owner = _answer(lambda: call(ids, factories.ident(OWNER)))
    assert owner[1] == 200, (case, owner)
    for who in MEMBERS:
        got = _answer(lambda who=who: call(ids, factories.ident(who)))
        assert got[1] == 200, (case, who, got[:3])
        assert _body(got, drop) == _body(owner, drop), (case, who)
    stranger = _answer(lambda: call(ids, factories.ident(OTHER)))
    assert stranger[1] == GET_EXPECT.get(case, 404), (case, stranger[:3])
    if case in GET_EXPECT:                                     # 과제로 거르는 목록 — 남에게는 빈 목록이다
        assert _body(stranger)["total"] == 0 and _body(owner)["total"] > 0, (case, owner[2][:200])


def test_the_brief_is_a_write_that_editors_get_and_viewers_do_not(members):
    """면제한 브리프(패널 편성 · 토큰 발급)는 쓰기 문이다(MB-14) — 편집자는 주인과 같은 답(이 카드 대조 대상은 422 웹 전용)이고, 보기는 403
    role_insufficient, 남은 없는 대상과 같은 404 다. 보기 · 남의 부름은 패널 · 토큰을 세우지 않는다."""
    store, ids = members
    before = [dict(r) for r in store.query("SELECT id, status, brief_token_hash FROM rr_panels ORDER BY id")]
    owner = _answer(lambda: routes.get_brief(ids["target"], ident=factories.ident(OWNER)))
    assert owner[1] != 404, owner                              # 카드 대조 대상이라 주인은 422(웹 전용)다 — 404 가 아니다
    editor = _answer(lambda: routes.get_brief(ids["target"], ident=factories.ident(EDITOR)))
    assert (editor[0], editor[1]) == (owner[0], owner[1]), editor[:3]
    viewer = _answer(lambda: routes.get_brief(ids["target"], ident=factories.ident(VIEWER)))
    assert (viewer[0], viewer[1]) == ("role_insufficient", 403), viewer[:3]
    missing = _answer(lambda: routes.get_brief("no-such-target", ident=factories.ident(OTHER)))
    theirs = _answer(lambda: routes.get_brief(ids["target"], ident=factories.ident(OTHER)))
    assert (theirs[0], theirs[1], theirs[2].replace(ids["target"], "<t>")) == (
        missing[0], missing[1], missing[2].replace("no-such-target", "<t>")), theirs[:3]
    assert [dict(r) for r in store.query("SELECT id, status, brief_token_hash FROM rr_panels ORDER BY id")] == before


def test_the_lists_without_a_project_filter_carry_the_member_projects(members):
    """홈의 비교 · 대상 · 보고서 탭(과제 거름 없이)도 과제 목록처럼 소유 ∪ 구성원 과제다 — 구성원은 주인과 같은 줄을 받는다."""
    store, ids = members
    reads = {"diffs": routes.list_diffs, "targets": routes.list_targets, "reports": routes.list_reports}
    for name, read in reads.items():
        owner = _answer(lambda read=read: read(ident=factories.ident(OWNER)))
        assert owner[1] == 200 and _body(owner)["total"] > 0, (name, owner[2][:200])
        for who in MEMBERS:
            assert _body(_answer(lambda read=read, who=who: read(ident=factories.ident(who)))) == _body(owner), (name, who)
        assert _body(_answer(lambda read=read: read(ident=factories.ident(OTHER))))["total"] == 0, name


def test_member_refs_resolve_in_the_snapshot_and_diff_scope(members):
    """스냅샷 · 비교 스코프의 참조(게이트 · 변경 항목)도 구성원이 연다 — 종전에는 스코프를 주인으로만 봐(D50 '그대로 둔 것') 구성원이
    404 였다. 남은 없는 스냅샷 · 비교와 같은 404 다."""
    store, ids = members
    cid = store.query_one("SELECT cid FROM rr_diff_events WHERE diff_id = ? ORDER BY cid LIMIT 1", (ids["diff"],))["cid"]
    scoped = {
        "gate": lambda i, who: routes.get_ref("gate:G1", snapshot_id=i["target_snapshot"], ident=who),
        "change": lambda i, who: routes.get_ref(cid, diff_id=i["diff"], ident=who),
    }
    for name, call in scoped.items():
        owner = _answer(lambda call=call: call(ids, factories.ident(OWNER)))
        assert owner[1] == 200, (name, owner[:3])
        for who in MEMBERS:
            got = _answer(lambda call=call, who=who: call(ids, factories.ident(who)))
            assert got[1] == 200, (name, who, got[:3])
            assert _body(got) == _body(owner), (name, who)
        theirs = _answer(lambda call=call: call(ids, factories.ident(OTHER)))
        gone = _answer(lambda call=call: call({**ids, "target_snapshot": "no-such-snapshot", "diff": "no-such-diff"},
                                              factories.ident(OTHER)))
        assert theirs[1] == 404 and (theirs[0], theirs[2].replace(ids["target_snapshot"], "<s>").replace(ids["diff"], "<d>")) == (
            gone[0], gone[2].replace("no-such-snapshot", "<s>").replace("no-such-diff", "<d>")), (name, theirs[:3])


# ---------------------------------------------------------------- MCP 읽기 도구
def test_every_mcp_tool_is_a_member_read_an_exempt_read_or_a_write():
    """MCP 도구 == 읽기 ∪ 면제 ∪ 쓰기 ∪ 남 시험의 면제(인자 없는 목록 · 어휘) — 새 도구는 이 셋 가운데 하나로 들어와야 한다."""
    names = set(MCP_READS) | set(MCP_MEMBER_EXEMPT) | set(MCP_WRITES)
    assert len(names) == len(MCP_READS) + len(MCP_MEMBER_EXEMPT) + len(MCP_WRITES) and all(MCP_MEMBER_EXEMPT.values())
    assert names == set(MCP_CASES) and not names & set(MCP_EXEMPT)


@pytest.mark.parametrize("name", MCP_READS)
def test_editors_and_viewers_get_the_owners_answer_from_every_mcp_read_tool(members, monkeypatch, name):
    """MCP 읽기 도구도 편집자 · 보기에게 주인과 같은 답이다 — 대응표(risk_get_sameas)는 웹 라우트를 그대로 부르는 입구라 종전에는
    구성원이 E404 였다."""
    store, ids = members
    call, _supplied = MCP_CASES[name]
    factories.act_as_delegate(monkeypatch, OWNER)
    owner = _mcp(lambda: call(ids))
    assert owner[0] == "ok", (name, owner[2][:300])
    for who in MEMBERS:
        factories.act_as_delegate(monkeypatch, who)
        got = _mcp(lambda: call(ids))
        assert (got[0], _body(got)) == ("ok", _body(owner)), (name, who, got[2][:300])


def test_the_mcp_project_list_gives_members_their_role(members, monkeypatch):
    """MCP 과제 목록(발견)도 구성원 과제를 싣고 카드의 내 역할은 부른 사람의 것이다."""
    store, ids = members
    for who, role in ((OWNER, "owner"), (EDITOR, "editor"), (VIEWER, "viewer")):
        factories.act_as_delegate(monkeypatch, who)
        assert [(c["id"], c["my_role"]) for c in srv.risk_list_projects()["projects"]] == [(ids["project"], role)], who


# ---------------------------------------------------------------- 남이 그 과제에 매단 행(고침 전의 들여오기 — RD-10)
def _forge(store, ids: dict) -> tuple[str, str]:
    """남이 주인의 과제에 매단 스냅샷 · 대상 행 하나씩(주인의 행을 본뜨고 열쇠 · 주인만 바꾼다) — (스냅샷 id, 대상 열쇠)."""
    snapshot = dict(store.query_one("SELECT * FROM rr_snapshots WHERE id = ?", (ids["target_snapshot"],)))
    snapshot.update(id="f" * 32, owner_sub=OTHER, ir_hash="f" * 12)        # (과제, ir_hash) 는 유일하다
    # IR 은 주인의 스냅샷(합성기가 생산자 경로로 언 것) 그대로다 — 계면 attrs.note 의 null 도 계약 안이다(MB-17).
    factories.seed_raw(store, "rr_snapshots", snapshot,
                       reason="고침 전의 들여오기가 남긴 남의 스냅샷 행 — 이제 들여오기는 parent_not_owned 로 막는다(RD-10)")
    target = dict(store.query_one("SELECT * FROM rr_targets WHERE target_key = ?", (ids["target"],)))
    target.update(target_key="snap:forged-by-other", kind="snap", ref_id="f" * 32, owner_sub=OTHER)
    factories.seed_raw(store, "rr_targets", target,
                       reason="고침 전의 들여오기가 남긴 남의 대상 행 — 이제 들여오기는 parent_not_owned 로 막는다(RD-10)")
    return "f" * 32, "snap:forged-by-other"


def test_rows_someone_else_hung_on_the_project_are_not_read_through_membership(members, monkeypatch):
    """구성원 길은 과제 주인의 행만 고른다 — 남이 주인의 과제에 매단 스냅샷 · 대상은 구성원에게 REST 로도 MCP 로도 없는 것과 같고 목록에
    서지 않는다. 종전 MCP 문지기는 과제만 보고 행의 주인으로 읽어 구성원 · 조직 공개로 그 남의 행을 내주었다. 그 행을 들여온 사람
    자신은 제 행을 그대로 읽는다(오늘의 주인 길)."""
    store, ids = members
    forged_snapshot, forged_target = _forge(store, ids)
    for who in (OWNER, *MEMBERS):
        assert _answer(lambda who=who: routes.get_snapshot(forged_snapshot, ident=factories.ident(who)))[1] == 404, who
        assert _answer(lambda who=who: routes.get_coverage(forged_target, ident=factories.ident(who)))[1] == 404, who
        listed = [t["target_key"] for t in routes.list_targets(project_id=ids["project"], ident=factories.ident(who))["targets"]]
        assert listed == [ids["target"]], (who, listed)
        factories.act_as_delegate(monkeypatch, who)
        assert _mcp(lambda: srv.risk_get_snapshot(snapshot_id=forged_snapshot, part="ir"))[0] == "not_visible", who
        assert _mcp(lambda: srv.risk_get_coverage(target_key=forged_target))[0] == "not_visible", who
    assert _answer(lambda: routes.get_snapshot(forged_snapshot, ident=factories.ident(OTHER)))[1] == 200


def test_an_owner_member_row_of_a_non_owner_opens_nothing_over_mcp(members, monkeypatch):
    """owner 는 과제 행의 주인 열만 정한다(project_role · RD-10) — MCP 의 볼 수 있는 과제도 같은 판정이다. 주인 아닌 사람의 owner 멤버 행
    (고침 전의 들여오기가 남겼을 수 있는 행)으로는 MCP 목록에도 과제가 서지 않고 그 과제의 스냅샷 · 대상을 읽지 못한다(종전에는 그 행
    하나로 읽혔다)."""
    store, ids = members
    factories.seed_raw(store, "rr_project_members", {
        "project_id": ids["project"], "owner_sub": OTHER, "email": OTHER, "role": "owner", "added_by": OTHER,
        "added_at": 1, "updated_at": 1},
        reason="고침 전의 들여오기가 남긴 남의 owner 멤버 행 — 이제 들여오기는 parent_not_owned 로 막고 put_members 는 owner 를 받지 않는다")
    factories.act_as_delegate(monkeypatch, OTHER)
    assert srv.risk_list_projects()["projects"] == []
    assert _mcp(lambda: srv.risk_get_snapshot(snapshot_id=ids["target_snapshot"], part="state"))[0] == "not_visible"
    assert _mcp(lambda: srv.risk_get_coverage(target_key=ids["target"]))[0] == "not_visible"
    assert routes.visible_projects({"kind": "user", "email": OTHER}) == []
    # 웹 목록 · 읽기도 같은 판정이다(project_role · 구성원 행은 편집자 · 보기만).
    stranger = factories.ident(OTHER)
    for read in (routes.list_targets, routes.list_diffs, routes.list_reports):
        assert _body(_answer(lambda read=read: read(ident=stranger)))["total"] == 0, read.__name__
    assert _answer(lambda: routes.get_coverage(ids["target"], ident=stranger))[1] == 404


def test_the_brief_and_the_seat_diff_ref_do_not_read_an_owner_row_of_a_non_owner_as_membership(members):
    """브리프의 구성원 판정(E6 유사 · E7 좌석 기억 · E8 선례 코퍼스 · 계보 — brief._member · _MEMBER_OF)과 러너가 좌석에 diff_id 를 실을지
    가르는 판정(runner.diff_ref_withheld)도 project_role 과 같은 규칙이다 — owner 는 과제 행의 주인 열만 정하고 구성원 행은 편집자 · 보기만
    이다(RD-10). 종전에는 멤버 행이면 역할을 보지 않아, 주인 아닌 사람의 owner 멤버 행(고침 전의 들여오기)으로 그 사람의 대상 브리프가 이
    과제의 의견 · 성격 · 선례를 읽었고 그 사람 자격의 좌석에 이 과제의 diff 를 열 수 있다고 보았다."""
    store, ids = members
    factories.seed_raw(store, "rr_project_members", {
        "project_id": ids["project"], "owner_sub": OTHER, "email": OTHER, "role": "owner", "added_by": OTHER,
        "added_at": 1, "updated_at": 1},
        reason="고침 전의 들여오기가 남긴 남의 owner 멤버 행 — 이제 들여오기는 parent_not_owned 로 막고 put_members 는 owner 를 받지 않는다")
    assert not brief_module._member(store, ids["project"], OTHER)
    assert ids["project"] not in brief_module._member_project_ids(store, OTHER)
    for who in (OWNER, *MEMBERS):
        assert brief_module._member(store, ids["project"], who), who
        assert ids["project"] in brief_module._member_project_ids(store, who), who
    assert (runner.diff_ref_withheld(store, ids["diff"], "user", OTHER) or {}).get("reason") == "not_member"
    for who in (OWNER, *MEMBERS):
        assert (runner.diff_ref_withheld(store, ids["diff"], "user", who) or {}).get("reason") != "not_member", who


# ---------------------------------------------------------------- 쓰기는 그대로다
@pytest.mark.parametrize("case", sorted(CASES), ids=lambda c: f"{c[0]} {c[1][len(P):]}")
def test_a_viewer_passes_no_writing_route_that_touches_the_project(members, case):
    """보기는 읽기만이다 — 쓰기 경로는 404 · 403 · 409 · 422 로 막히고(무엇으로 막히는지는 오늘 그대로다), 제 행만 쓰는 두 경로만 지난다.
    구성원 읽기를 연 것이 쓰기 문을 넓히지 않았다는 가드다."""
    store, ids = members
    call, _supplied = CASES[case]
    got = _answer(lambda: call(ids, factories.ident(VIEWER)))
    if case in VIEWER_WRITES_OWN:
        assert got[1] == 200, (case, got[:3])
        assert ids["project"] not in (json.loads(got[2]).get("id"), json.loads(got[2]).get("project_id")), case
    else:
        assert got[1] in (403, 404, 409, 422), (case, got[:3])


# ---------------------------------------------------------------- 두 과제에 걸친 것 — 대응표 · 비교
ONE_SIDE = "target-only@example.com"          # 대상 과제만의 구성원
NEW_OWNER = "new-owner@example.com"


def _rename(node: dict, new: str) -> None:
    """mcad 부품 하나의 경로 · 이름을 바꾼다 — 대응 사다리가 정하지 못해(지문 점수 0.85) 대응표에 pending 한 줄이 선다."""
    old = node["label"]
    node.update(label=new, canon_key=node["canon_key"].replace(old, new), local_key=node["local_key"].replace(old, new))


@pytest.fixture
def two_projects(risk_store, monkeypatch):
    """주인의 과제 둘(앞 · 뒤 리비전)과 그 스냅샷 — 뒤 스냅샷은 부품 하나의 경로가 바뀌었다. 편집자 · 보기는 두 과제의 구성원, ONE_SIDE 는
    뒤 과제만의 구성원이다."""
    store = risk_store
    monkeypatch.setattr(routes, "get_store", lambda: store)
    base_project = factories.make_project(store, code="TWO-DV1")
    target_project = factories.make_project(store, code="TWO-DV2")
    results = factories.fixture_adapter_results()
    renamed = copy.deepcopy(results)
    mcad = next(r for r in renamed if (r.get("source") or {}).get("kind") == "mcad")
    _rename(next(n for n in mcad["nodes"] if n.get("kind") == "part" and n.get("label") == "PLATE_1"), "NEWPART_0")
    base = factories.make_snapshot(store, base_project, results, label="DV1")["snapshot_id"]
    target = factories.make_snapshot(store, target_project, renamed, label="DV2")["snapshot_id"]
    owner = factories.ident(OWNER)
    for project_id, extra in ((base_project, ()), (target_project, (ONE_SIDE,))):
        routes.put_members(project_id, routes.MembersBody(members=[
            routes.MemberItem(email=EDITOR, role="editor"), routes.MemberItem(email=VIEWER, role="viewer"),
            *(routes.MemberItem(email=e, role="viewer") for e in extra)]), ident=owner)
    return {"store": store, "base_project": base_project, "target_project": target_project, "base": base, "target": target}


def test_the_sameas_table_reads_the_owners_pair_ledger_for_members(two_projects, monkeypatch):
    """대응표는 두 스냅샷을 다 읽는 구성원이 연다 — 쌍 원장은 그 스냅샷 주인의 것이라 주인이 정한 대응이 구성원의 표에도 선다(종전에는 구성원이
    404). 한쪽 과제만의 구성원과 남은 없는 스냅샷과 같은 404 다."""
    w = two_projects
    owner = factories.ident(OWNER)
    table = routes.get_sameas(base=w["base"], target=w["target"], ident=owner)
    assert table["pending_n"] == 1, table
    row = table["pairs"][0]
    routes.post_sameas_decide([{"decision": "confirm", "scope": "pair", "pair_key": table["pair_key"],
                                "a_stable": row["a_stable"], "b_stable": row["b_stable"], "snapshot_id": w["target"]}], ident=owner)
    decided = routes.get_sameas(base=w["base"], target=w["target"], ident=owner)
    assert decided["pending_n"] == 0 and decided["pairs"] == []
    for who in MEMBERS:
        assert routes.get_sameas(base=w["base"], target=w["target"], ident=factories.ident(who)) == decided, who
        factories.act_as_delegate(monkeypatch, who)
        assert _mcp(lambda: srv.risk_get_sameas(base_snapshot_id=w["base"], target_snapshot_id=w["target"]))[2] == json.dumps(
            decided, ensure_ascii=False, sort_keys=True, default=str), who
    missing = _answer(lambda: routes.get_sameas(base="no-such-snapshot", target=w["target"], ident=factories.ident(OTHER)))
    for who in (ONE_SIDE, OTHER):
        got = _answer(lambda who=who: routes.get_sameas(base=w["base"], target=w["target"], ident=factories.ident(who)))
        assert (got[0], got[1], got[2].replace(w["base"], "<s>")) == (missing[0], missing[1], missing[2].replace("no-such-snapshot",
                                                                                                               "<s>")), who


def test_a_diff_opens_to_who_reads_both_projects_and_follows_a_full_transfer(two_projects, monkeypatch):
    """비교는 두 과제(base · target)를 다 읽는 구성원이 연다(MCP 문지기와 같은 규칙) — 대상 과제만의 구성원에게는 없는 비교와 같다. 남이
    그 두 과제를 적어 넣은 비교 행(고침 전의 들여오기)은 누구의 구성원 길로도 열리지 않고 목록에 서지 않는다. 뒤 과제만 넘기면 비교는 만든
    사람의 행으로 남아 두 과제를 읽는 구성원과 만든 사람이 그대로 열고, 앞 과제를 못 읽는 새 주인은 못 연다(오늘 그대로). 두 과제를 다
    넘기면 비교 · 그 변경 항목이 두 과제를 다 받은 사람의 행이 된다(사용자 결정 10-31 '둘 다 받은 사람에게 옮긴다', MB-15) — 새 주인 ·
    구성원 · 넘겨 준 사람(이제 두 과제의 편집자)이 열고, 새 주인이 같은 쌍을 다시 만들면 그 비교다. 종전에는 만든 사람의 제 행으로만
    열렸고(행 주인이 두 과제 어느 쪽의 주인도 아니다) 새 주인의 같은 쌍 만들기는 유일 열쇠에 걸려 500 이었다. 남이 적어 넣은 행은 따라가지
    않는다(그 남은 두 과제의 주인이었던 적이 없다)."""
    w = two_projects
    store = w["store"]
    diff_id = factories.make_diff(store, w["base"], w["target"])["diff_id"]
    factories.make_project(store, owner=OTHER, code="OTHER-OWN")       # 비교를 들여온 남도 제 과제가 있다(과제 주인이긴 하다)
    forged = dict(store.query_one("SELECT * FROM rr_diffs WHERE id = ?", (diff_id,)))
    forged.update(id="d" * 32, owner_sub=OTHER, base_snapshot_id="b" * 32, target_snapshot_id="c" * 32)   # (base, target) 는 유일하다
    # 비교 본문은 주인의 것(생산자 diff.create_diff 가 쓴 것) 그대로다 — 생산자 diff_json 이 rr_diff.v1 밖이라(최상위 pair_kind · 조립품
    # 주체 asm:… — context-notes MB-17 '남긴 것') 검증만 끈다. 이 시험이 어기려는 칸이 아니다.
    factories.seed_raw(store, "rr_diffs", forged, validate=False,
                       reason="고침 전의 들여오기가 남긴 남의 비교 행(남의 두 과제를 적었다) — 이제 들여오기는 parent_not_owned 로 막는다(RD-10) ·"
                              " 비교 본문은 주인의 것을 그대로 본뜬다")

    def reads(who: str, did: str = diff_id) -> tuple:
        return _answer(lambda: routes.get_diff(did, part="summary", ident=factories.ident(who)))

    def listed(who: str) -> list[str]:
        return [d["id"] for d in routes.list_diffs(ident=factories.ident(who))["diffs"]]

    owner = reads(OWNER)
    assert owner[1] == 200 and listed(OWNER) == [diff_id]
    for who in MEMBERS:
        got = reads(who)
        assert got[1] == 200, (who, got[:3])
        assert _body(got) == _body(owner), who
        assert listed(who) == [diff_id], who
        assert reads(who, "d" * 32)[1] == 404, who
        factories.act_as_delegate(monkeypatch, who)
        assert _mcp(lambda: srv.risk_get_diff(diff_id=diff_id, part="summary"))[0] == "ok", who
        assert _mcp(lambda: srv.risk_get_diff(diff_id="d" * 32, part="summary"))[0] == "not_visible", who
    missing = _answer(lambda: routes.get_diff("no-such-diff", part="summary", ident=factories.ident(ONE_SIDE)))
    one_side = reads(ONE_SIDE)
    assert (one_side[0], one_side[1], one_side[2].replace(diff_id, "<d>")) == (
        missing[0], missing[1], missing[2].replace("no-such-diff", "<d>")) and listed(ONE_SIDE) == []
    factories.act_as_delegate(monkeypatch, ONE_SIDE)
    assert _mcp(lambda: srv.risk_get_diff(diff_id=diff_id, part="summary"))[0] == "not_visible"

    routes.transfer_project(w["target_project"], routes.TransferBody(to_email=NEW_OWNER, reason="뒤 리비전을 넘긴다"),
                            ident=factories.ident(OWNER))
    assert store.query_one("SELECT owner_sub FROM rr_diffs WHERE id = ?", (diff_id,))["owner_sub"] == OWNER
    for who in (OWNER, *MEMBERS):
        got = reads(who)
        assert got[1] == 200, (who, got[:3])
        assert _body(got) == _body(owner), who
        assert listed(who) == [diff_id], who
    assert reads(NEW_OWNER)[1] == 404 and listed(NEW_OWNER) == []

    out = routes.transfer_project(w["base_project"], routes.TransferBody(to_email=NEW_OWNER, reason="앞 리비전도 넘긴다"),
                                  ident=factories.ident(OWNER))
    assert out["rows_updated"]["tables"]["rr_diffs"] == 1, out
    assert store.query_one("SELECT owner_sub FROM rr_diffs WHERE id = ?", (diff_id,))["owner_sub"] == NEW_OWNER
    moved = reads(NEW_OWNER)
    assert moved[1] == 200, moved[:3]
    for who in (NEW_OWNER, OWNER, *MEMBERS):
        got = reads(who)
        assert got[1] == 200 and _body(got) == _body(moved), (who, got[:3])
        assert listed(who) == [diff_id], who
        factories.act_as_delegate(monkeypatch, who)
        assert _mcp(lambda: srv.risk_get_diff(diff_id=diff_id, part="summary"))[0] == "ok", who
    assert store.query_one("SELECT owner_sub FROM rr_diffs WHERE id = ?", ("d" * 32,))["owner_sub"] == OTHER
    again = routes.create_diff(routes.DiffBody(base_snapshot_id=w["base"], target_snapshot_id=w["target"]),
                               ident=factories.ident(NEW_OWNER))
    assert again["diff_id"] == diff_id


def test_a_diff_follows_when_both_projects_reach_one_person_by_different_routes(two_projects):
    """두 과제가 다른 길로 한 사람에게 모여도(앞 과제는 C 에게, 뒤 과제는 B 를 거쳐 C 에게) 마지막 이양에서 비교가 C 의 것이 된다 — 행 주인
    (만든 사람)이 두 과제의 앞 주인이었다(이양 감사의 앞 주인). 한쪽만 모인 동안은 만든 사람의 행 그대로다."""
    w = two_projects
    store = w["store"]
    diff_id = factories.make_diff(store, w["base"], w["target"])["diff_id"]
    via, final = "via@example.com", "final@example.com"

    def owner_of_diff() -> str:
        return store.query_one("SELECT owner_sub FROM rr_diffs WHERE id = ?", (diff_id,))["owner_sub"]

    routes.transfer_project(w["target_project"], routes.TransferBody(to_email=via, reason="뒤 리비전을 넘긴다"),
                            ident=factories.ident(OWNER))
    routes.transfer_project(w["base_project"], routes.TransferBody(to_email=final, reason="앞 리비전을 넘긴다"),
                            ident=factories.ident(OWNER))
    assert owner_of_diff() == OWNER
    routes.transfer_project(w["target_project"], routes.TransferBody(to_email=final, reason="뒤 리비전도 모은다"),
                            ident=factories.ident(via))
    assert owner_of_diff() == final
    assert _answer(lambda: routes.get_diff(diff_id, part="summary", ident=factories.ident(final)))[1] == 200


def test_a_project_transfer_takes_its_own_revision_diffs(risk_store, monkeypatch):
    """한 과제 안의 리비전 비교(앞 · 뒤 스냅샷이 같은 과제)는 그 과제를 넘기면 변경 항목과 함께 넘어간다 — 두 쪽이 다 받은 사람의 것이다.
    종전에는 이양이 비교를 옮기지 않아 새 주인의 대상(diff:…)이 옛 주인의 비교를 가리켰고 새 주인은 그 비교를 열지 못했다. 넘겨 준 사람은
    편집자로 남아 그대로 연다."""
    store = risk_store
    monkeypatch.setattr(routes, "get_store", lambda: store)
    synth = factories.make_diff_target(store, 40, owner=OWNER)
    events = store.query_one("SELECT COUNT(*) AS n FROM rr_diff_events WHERE diff_id = ?", (synth.diff_id,))["n"]
    assert events > 0
    out = routes.transfer_project(synth.project_id, routes.TransferBody(to_email=NEW_OWNER, reason="과제를 넘긴다"),
                                  ident=factories.ident(OWNER))
    assert (out["rows_updated"]["tables"]["rr_diffs"], out["rows_updated"]["tables"]["rr_diff_events"]) == (1, events), out
    assert store.query_one("SELECT owner_sub FROM rr_diffs WHERE id = ?", (synth.diff_id,))["owner_sub"] == NEW_OWNER
    assert [r["owner_sub"] for r in store.query("SELECT DISTINCT owner_sub FROM rr_diff_events WHERE diff_id = ?",
                                                (synth.diff_id,))] == [NEW_OWNER]
    for who in (NEW_OWNER, OWNER):
        assert _answer(lambda who=who: routes.get_diff(synth.diff_id, part="summary", ident=factories.ident(who)))[1] == 200


def test_the_sameas_ledger_follows_the_projects_it_belongs_to(two_projects):
    """대응 원장 행도 비교와 같은 규칙으로 따라간다 — 과제 안(intra) 행은 그 과제를 넘기면, 두 과제(pair) 행은 두 과제가 한 사람에게 모이면 그
    사람의 행이 된다. 그래야 새 주인의 대응표 · 비교가 앞 주인의 결정을 읽고 새 주인이 그 결정을 고칠 수 있다 — 종전에는 새 주인에게 결정이
    사라졌고(원장은 주인으로 읽는다) 다시 정하면 남의 행이라 409 sameas_row_foreign 이었다(MB-13 의 덮지 않기)."""
    w = two_projects
    store = w["store"]
    owner = factories.ident(OWNER)
    table = routes.get_sameas(base=w["base"], target=w["target"], ident=owner)
    row = table["pairs"][0]
    pair = {"decision": "confirm", "scope": "pair", "pair_key": table["pair_key"], "a_stable": row["a_stable"],
            "b_stable": row["b_stable"], "snapshot_id": w["target"]}
    intra = {"decision": "confirm", "scope": "intra", "pair_key": w["target_project"], "a": "s:a", "b": "s:b"}
    routes.post_sameas_decide([pair, intra], ident=owner)

    def owners() -> dict[str, str]:
        return {r["scope"]: r["owner_sub"] for r in store.query("SELECT scope, owner_sub FROM rr_sameas")}

    routes.transfer_project(w["target_project"], routes.TransferBody(to_email=NEW_OWNER, reason="뒤 리비전을 넘긴다"),
                            ident=owner)
    assert owners() == {"pair": OWNER, "intra": NEW_OWNER}
    newcomer = factories.ident(NEW_OWNER)
    assert routes.post_sameas_decide([{**intra, "decision": "reject"}], ident=newcomer)["results"][0]["status"] == "rejected"
    routes.transfer_project(w["base_project"], routes.TransferBody(to_email=NEW_OWNER, reason="앞 리비전도 넘긴다"),
                            ident=owner)
    assert owners() == {"pair": NEW_OWNER, "intra": NEW_OWNER}
    assert routes.get_sameas(base=w["base"], target=w["target"], ident=newcomer)["pending_n"] == 0
    out = routes.post_sameas_decide([{**pair, "decision": "reject"}], ident=newcomer)
    assert out["results"][0]["status"] == "rejected" and out["results"][0]["rekey"] is not None


# ---------------------------------------------------------------- 과제 스코프 없는 참조 — req · voc · paper
class _Field:
    """게이트웨이 필드 채널 흉내 — VOC 한 건 · 논문 한 건(test_e2e_smoke 의 해석 시험과 같은 꼴)."""

    def call(self, name: str, args: dict) -> dict:
        if name == "get_top_issues":
            return {"ok": True, "result": {"issues": [{"issue_key": "ISS-1", "category": "파손", "n": 4, "text": "힌지"}]}}
        return {"ok": True, "result": {"papers": [{"doi": "10.1000/xyz", "title": "drop", "abstract": "stress"}]}}


def test_requirement_voc_and_paper_refs_resolve_for_members(risk_store, monkeypatch):
    """과제 스코프가 참조 글에 없는 req · voc · paper 도 구성원이 연다 — 부른 사람의 것이 없으면 구성원인 과제(그 과제 주인의 행)의 요구 ·
    브리프 호출 원장에서 찾는다(D50 '그대로 둔 것' 을 닫았다 — 등록부 인용을 눌러 보는 구성원이 404 였다). 남은 없는 참조와 같은 404 다."""
    store = risk_store
    monkeypatch.setattr(routes, "get_store", lambda: store)
    owner = factories.ident(OWNER)
    project_id = routes.create_project(routes.ProjectBody(code="REFS-1", name="참조", stage="DV1", classification="internal",
                                                          product_code="F7-2024"), ident=owner)["id"]
    routes.put_members(project_id, routes.MembersBody(members=[routes.MemberItem(email=EDITOR, role="editor"),
                                                               routes.MemberItem(email=VIEWER, role="viewer")]), ident=owner)
    routes.post_requirements(project_id, [routes.RequirementItem(kind="scenario", name="drop_1_2m_corner",
                                                                 value_json={"taxonomy_key": "deep", "required": True})],
                             ident=owner)
    snapshot = factories.make_snapshot(store, project_id, factories.fixture_adapter_results(), label="DV1")["snapshot_id"]
    target_key = factories.make_target(store, "snap", snapshot, agents=factories.agents())
    factories.seed_raw(store, "rr_character", {
        "id": "C1", "project_id": project_id, "owner_sub": OWNER, "facet": "intent", "tag": "char:structure:thin_stack",
        "tags_json": "[]", "statement": "s", "polarity": "observation", "by_json": "[]", "support_panels": 2, "support_targets": 1,
        "recall_eligible": 1, "needs_review": 0, "status": "panel", "created_at": 1, "updated_at": 1},
        reason="문헌 검색어(scholar_query)의 성격 태그 — 생산자는 패널 한 판 전부라 읽는 칸만 손으로 쓴다(test_e2e_smoke 의 해석 시험과 같다)")
    lines = brief_module._field_evidence_lines(store, brief_module._target_context(store, target_key),
                                               field_source.FieldSource(_Field()))
    assert any(line.startswith("voc:F7-2024#ISS-1") for line in lines), lines
    for ref, absent in (("req:drop_1_2m_corner", "req:nope"), ("voc:F7-2024#ISS-1", "voc:F7-2024#ISS-9"),
                        ("paper:10.1000/xyz", "paper:10.1000/nope")):
        mine = _answer(lambda ref=ref: routes.get_ref(ref, ident=owner))
        assert mine[1] == 200, (ref, mine[:3])
        for who in MEMBERS:
            got = _answer(lambda ref=ref, who=who: routes.get_ref(ref, ident=factories.ident(who)))
            assert got[1] == 200, (ref, who, got[:3])
            assert _body(got) == _body(mine), (ref, who)
        theirs = _answer(lambda ref=ref: routes.get_ref(ref, ident=factories.ident(OTHER)))
        gone = _answer(lambda absent=absent: routes.get_ref(absent, ident=factories.ident(OTHER)))
        assert (theirs[0], theirs[1], theirs[2].replace(ref, "<r>")) == (gone[0], gone[1], gone[2].replace(absent, "<r>")), ref
