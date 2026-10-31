# 과제 상세 · 목록을 구성원에게 여는 읽기 시험(화면 세션 10-31 청할 것 1 · 2) — 메타 열 · 멤버 표 · 스냅샷 머리 판 칸 · 카드 내 역할
"""화면 세션(가지 wt1031/riskfe — context-notes FE-14 끝)은 과제 상세 · 목록이 주지 않는 칸을 '모름' 으로 보이고 청할 것을 남겼다. 과제
상세는 주인 검사(`_project_row`)라 편집자 · 보기가 열지 못했고, 목록은 소유 과제만이었다. 이 파일은 생산자 경로(라우트 · 동결 잡 ·
freeze_snapshot)로 만든 원장 위에서 그 칸과 구성원 읽기를 본다. 남(구성원이 아닌 사람)은 있는 과제와 없는 과제가 같은 404 다(남 숨김) —
경로 전체의 남 시험은 tests/rr/test_review1_stranger.py 의 표가 맡는다.

  실행:  .venv/bin/python -m pytest tests/test_project_reads.py
"""
from __future__ import annotations

import pytest

import app.mcp_server as srv
from app import ir_builder, routes
from app.adapters import registry as adapters_registry
from app.errors import AppError
from tests import factories
from tests import test_adapters as recon
from tests.test_e2e_smoke import FakeSourceApps, no_network, seeded_discovery  # noqa: F401 — autouse 픽스처

OWNER = factories.OWNER
EDITOR = "editor@example.com"
VIEWER = "viewer@example.com"
STRANGER = "stranger@example.com"


@pytest.fixture
def wired(risk_store, monkeypatch):
    """라우트 본문이 이 시험의 빈 DB 를 보게 한다(라우트는 모듈 전역 get_store 를 부른다)."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    return risk_store


def _refused(call) -> tuple[str, int, str]:
    with pytest.raises(AppError) as exc:
        call()
    return exc.value.code, exc.value.http_status, exc.value.message


def _shared_project(code: str = "READS-1") -> str:
    """주인의 과제 하나 — 등급 confidential · 제품 연결 하나 · 편집자와 보기 멤버."""
    owner = factories.ident(OWNER)
    project_id = routes.create_project(routes.ProjectBody(
        code=code, name="읽기 과제", stage="DV1", classification="confidential",
        product_refs_json=[{"kind": "product_code", "value": "SM-X100"}]), ident=owner)["id"]
    routes.put_members(project_id, routes.MembersBody(members=[
        routes.MemberItem(email=EDITOR, role="editor"), routes.MemberItem(email=VIEWER, role="viewer")]), ident=owner)
    return project_id


# ---------------------------------------------------------------- 1. GET /projects/{id}
def test_members_read_the_project_detail_with_its_meta_members_and_snapshot_heads(wired, monkeypatch):
    """편집자 · 보기도 과제 상세를 연다(주인 검사 → 구성원 검사). 과제 행은 메타 열을 싣고(코퍼스 제외는 bool · 제품 연결은 배열), 멤버
    표는 {email, role}, 스냅샷 머리는 이름(그 스냅샷을 만든 동결 잡의 label) · 앱 판 · 어댑터 판 · 강등 표지 전부를 싣는다. 대상 · 잡은
    부른 사람이 아니라 과제의 주인(신원 앵커)으로 고른다 — 구성원이 열어도 주인의 대상이 보인다."""
    store = wired
    owner = factories.ident(OWNER)
    project_id = _shared_project()
    routes.patch_project(project_id, routes.ProjectPatchBody(corpus_excluded=True, excluded_reason="fixture",
                                                             lifecycle="shipped"), ident=owner)
    routes.add_source(project_id, routes.SourceBody(
        kind="mcad", app_key=recon.APP_KEY,
        ref={"stepforge_project_id": recon.SF_PROJECT, "detect_job_id": "01JDET"}), ident=owner)
    apps = FakeSourceApps()
    monkeypatch.setattr(adapters_registry, "clients_from_settings", lambda *a, **k: apps.channels())
    captured = routes.create_snapshot(project_id, routes.SnapshotBody(label="DV1"), ident=owner)["snapshot_id"]
    # 동결 잡을 거치지 않은 스냅샷(손 픽스처 — 강등 표지가 있다)은 이름이 없다.
    by_hand = factories.make_snapshot(store, project_id, factories.fixture_adapter_results(), label="손")["snapshot_id"]
    target_key = factories.make_target(store, "snap", captured, agents=factories.agents())

    for who, role in ((OWNER, "owner"), (EDITOR, "editor"), (VIEWER, "viewer")):
        page = routes.get_project(project_id, ident=factories.ident(who))
        project = page["project"]
        assert (project["classification"], project["lifecycle"], project["mcp_visibility"], project["status"]) == (
            "confidential", "shipped", "private", "active"), who
        assert project["closed_at"] is not None
        assert project["corpus_excluded"] is True and project["excluded_reason"] == "fixture"   # 0/1 이 아니라 bool
        assert project["product_code"] == "SM-X100" and project["predecessor_product_code"] is None
        assert project["product_refs_json"] == [{"kind": "product_code", "value": "SM-X100"}]
        assert sorted((m["email"], m["role"]) for m in page["members"]) == sorted(
            [(OWNER, "owner"), (EDITOR, "editor"), (VIEWER, "viewer")])
        assert all(set(m) == {"email", "role"} for m in page["members"])
        assert [t["target_key"] for t in page["targets"]] == [target_key], role
        heads = {s["id"]: s for s in page["snapshots"]}
        assert set(heads) == {captured, by_hand}
        assert (heads[captured]["label"], heads[by_hand]["label"]) == ("DV1", None)
        for sid, head in heads.items():
            ir = ir_builder.load_ir(store, sid)
            assert head["app_versions"] == {s["kind"]: (s.get("app_version") or {}) for s in ir["sources"]}
            assert head["adapter_versions"] == ir["versions"]["adapter_versions"]
            assert head["degraded_json"] == sorted({d for s in ir["sources"] for d in s.get("degraded") or []})
            # 호환 열은 그대로 — 강등 표지의 첫 값이다.
            assert head["degraded"] == (head["degraded_json"][0] if head["degraded_json"] else None)
        assert heads[by_hand]["degraded_json"], "손 픽스처는 강등 표지가 있다 — 목록 전체가 실려야 한다"

    # 남은 없는 과제와 같은 404 다(과제가 있다는 것도 흘리지 않는다).
    theirs = _refused(lambda: routes.get_project(project_id, ident=factories.ident(STRANGER)))
    gone = _refused(lambda: routes.get_project("no-such-project", ident=factories.ident(STRANGER)))
    assert theirs[:2] == ("E404", 404)
    assert (theirs[0], theirs[1], theirs[2].replace(project_id, "<id>")) == (
        gone[0], gone[1], gone[2].replace("no-such-project", "<id>"))


# ---------------------------------------------------------------- 2. GET /projects
def test_the_project_list_carries_meta_and_my_role_and_lists_the_member_projects(wired, monkeypatch):
    """목록은 부른 사람이 소유하거나 구성원인 과제다(조직 공개만으로는 들지 않는다). 카드마다 등급 · 수명 주기 · 코퍼스 제외(bool) · 내 역할."""
    store = wired
    owner = factories.ident(OWNER)
    shared = _shared_project()
    routes.patch_project(shared, routes.ProjectPatchBody(corpus_excluded=True, excluded_reason="duplicate"), ident=owner)
    own = routes.create_project(routes.ProjectBody(code="EDITOR-OWN", name="편집자 과제", classification="internal"),
                                ident=factories.ident(EDITOR))["id"]
    # 남의 조직 공개 과제는 웹 목록에 들지 않는다(구성원이 아니다).
    public = routes.create_project(routes.ProjectBody(code="PUB-1", name="공개 과제", classification="internal"),
                                   ident=factories.ident(STRANGER))["id"]
    routes.patch_project(public, routes.ProjectPatchBody(mcp_visibility="org"), ident=factories.ident(STRANGER))

    # 멤버 표에 owner 행이 없는 과제도 주인에게는 owner 다(project_role 과 같은 판정 — 주인 열이 먼저다).
    factories.seed_raw(store, "rr_projects", {
        "id": "p-legacy", "owner_sub": EDITOR, "code": "LEGACY-1", "name": "옛 과제", "classification": "internal",
        "created_at": 1, "updated_at": 1},
        reason="owner 멤버 행이 없는 과제 — create_project 는 owner 행을 늘 함께 써서 생산자로 만들 수 없다(행 일부만 옮겨 온 과제)")

    cards = {c["id"]: c for c in routes.list_projects(ident=factories.ident(EDITOR))["projects"]}
    assert set(cards) == {shared, own, "p-legacy"}
    assert (cards[shared]["my_role"], cards[own]["my_role"], cards["p-legacy"]["my_role"]) == ("editor", "owner", "owner")
    assert (cards[shared]["classification"], cards[own]["classification"]) == ("confidential", "internal")
    assert (cards[shared]["lifecycle"], cards[own]["lifecycle"]) == ("active", "active")
    assert cards[shared]["corpus_excluded"] is True and cards[own]["corpus_excluded"] is False   # 0/1 이 아니라 bool
    assert [(c["id"], c["my_role"]) for c in routes.list_projects(ident=factories.ident(VIEWER))["projects"]] == [
        (shared, "viewer")]
    assert [(c["id"], c["my_role"]) for c in routes.list_projects(ident=owner)["projects"]] == [(shared, "owner")]
    assert [c["id"] for c in routes.list_projects(ident=factories.ident("nobody@example.com"))["projects"]] == []

    # MCP 목록(볼 수 있는 과제 — 조직 공개 포함)도 같은 함수다 — 내 역할은 부른 사람의 것이고 구성원이 아닌 공개 과제는 null 이다.
    factories.act_as_delegate(monkeypatch, EDITOR)
    mcp = {c["id"]: c["my_role"] for c in srv.risk_list_projects()["projects"]}
    assert mcp == {shared: "editor", own: "owner", "p-legacy": "owner", public: None}
