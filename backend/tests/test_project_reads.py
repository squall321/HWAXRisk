# 과제 상세 · 목록을 구성원에게 여는 읽기 시험(화면 세션 10-31 청할 것 1 · 2) — 메타 열 · 멤버 표 · 스냅샷 머리 판 칸 · 카드 내 역할
"""화면 세션(가지 wt1031/riskfe — context-notes FE-14 끝)은 과제 상세 · 목록이 주지 않는 칸을 '모름' 으로 보이고 청할 것을 남겼다. 과제
상세는 주인 검사(`_project_row`)라 편집자 · 보기가 열지 못했고, 목록은 소유 과제만이었다. 이 파일은 생산자 경로(라우트 · 동결 잡 ·
freeze_snapshot)로 만든 원장 위에서 그 칸과 구성원 읽기를 본다. 남(구성원이 아닌 사람)은 있는 과제와 없는 과제가 같은 404 다(남 숨김) —
경로 전체의 남 시험은 tests/rr/test_review1_stranger.py 의 표가 맡는다.

  실행:  .venv/bin/python -m pytest tests/test_project_reads.py
"""
from __future__ import annotations

import json

import pytest

import app.mcp_server as srv
from app import export, ir_builder, routes
from app.adapters import registry as adapters_registry
from app.errors import AppError
from app.risk_store import RiskStore
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


# ---------------------------------------------------------------- 3. 들여오기가 남의 과제에 매달리지 않는다(반대 검토 10-31 High)
MCAD_ONLY = "adapter_mcad_basic.json"


def _import(store, who: str, lines: list[dict]) -> dict:
    """그 사람의 JSONL 들여오기(POST /api/import 본체) — 첫 줄은 이 박스의 반출 머리다."""
    body = "\n".join(json.dumps(line, ensure_ascii=False) for line in [export.header_line(store), *lines])
    return export.import_jsonl(store, who, body)


def _first_ckey(store, snapshot_id: str) -> str:
    return store.query_one("SELECT ckey FROM rr_ir_nodes WHERE snapshot_id = ? AND ckey IS NOT NULL ORDER BY ckey LIMIT 1",
                           (snapshot_id,))["ckey"]


def test_an_imported_membership_row_cannot_open_someone_elses_project(wired):
    """들여오기는 본문의 owner_sub 가 부른 사람이면 받았다 — 그런데 project_id 는 부르는 쪽이 적는 값이라, 남의 과제 id 를 적은 멤버 행
    하나로 그 과제의 구성원(owner 까지)이 돼 상세 · 목록 · 키 대장을 읽고 이양까지 했다. 이제 그 줄은 parent_not_owned 로 눕고 과제는 남에게
    그대로 없는 과제다. 없는 과제 id 도 같은 까닭이다(있는지를 흘리지 않는다). 같은 본문의 제 과제 줄은 들어가고(표 차례로 쓴다 — 과제 줄이
    뒤에 와도 된다), 제 과제라도 남의 이메일로 적은 owner 행은 owner_row_immutable 이다(소유는 이양만이 바꾼다)."""
    store = wired
    victim = _shared_project("VICTIM-1")
    sid = factories.make_snapshot(store, victim, [factories.adapter_fixture(MCAD_ONLY)], label="동결")["snapshot_id"]
    ckey = _first_ckey(store, sid)
    row = {"owner_sub": STRANGER, "email": STRANGER, "added_by": STRANGER, "added_at": 1, "updated_at": 1}
    own = {"id": "p-stranger-own", "owner_sub": STRANGER, "code": "OWN-1", "name": "제 과제", "classification": "internal",
           "created_at": 1, "updated_at": 1}
    out = _import(store, STRANGER, [
        {"table": "rr_project_members", "row": {**row, "project_id": victim, "role": "owner"}},
        {"table": "rr_project_members", "row": {**row, "project_id": "p-nowhere", "role": "viewer"}},
        {"table": "rr_project_members", "row": {**row, "project_id": own["id"], "role": "owner"}},
        {"table": "rr_project_members", "row": {**row, "project_id": own["id"], "email": EDITOR, "role": "owner"}},
        {"table": "rr_project_members", "row": {**row, "project_id": own["id"], "email": VIEWER, "role": "viewer"}},
        {"table": "rr_projects", "row": own},
    ])
    assert [(c["table"], c["key"], c["reason"]) for c in out["conflicts"]] == [
        ("rr_project_members", f"{victim}|{STRANGER}", "parent_not_owned"),
        ("rr_project_members", f"p-nowhere|{STRANGER}", "parent_not_owned"),
        ("rr_project_members", f"{own['id']}|{EDITOR}", "owner_row_immutable")]
    assert (out["inserted"], out["skipped"]) == (3, 3)                  # 제 과제 · 제 owner 행 · 보기 멤버
    assert all(set(c) == {"table", "key", "reason"} for c in out["conflicts"])   # 준 열쇠 말고 주인의 값은 싣지 않는다

    stranger = factories.ident(STRANGER)
    theirs = _refused(lambda: routes.get_project(victim, ident=stranger))
    gone = _refused(lambda: routes.get_project("no-such-project", ident=stranger))
    assert (theirs[0], theirs[1], theirs[2].replace(victim, "<id>")) == (gone[0], gone[1], gone[2].replace("no-such-project", "<id>"))
    assert routes.project_role(victim, STRANGER) is None
    assert [(c["id"], c["my_role"]) for c in routes.list_projects(ident=stranger)["projects"]] == [(own["id"], "owner")]
    assert _refused(lambda: routes.get_part_key(ckey, ident=stranger))[:2] == ("E404", 404)
    assert _refused(lambda: routes.transfer_project(victim, routes.TransferBody(to_email=STRANGER, reason="가로채기"),
                                                    ident=stranger))[:2] == ("E404", 404)
    assert sorted((m["email"], m["role"]) for m in routes.get_project(victim, ident=factories.ident(OWNER))["members"]) == sorted(
        [(OWNER, "owner"), (EDITOR, "editor"), (VIEWER, "viewer")])
    # 제 과제의 들어간 멤버 행은 그대로 선다 — 보기 멤버가 그 과제를 연다.
    assert routes.get_project(own["id"], ident=factories.ident(VIEWER))["project"]["code"] == "OWN-1"
    assert routes.project_role(own["id"], EDITOR) is None


def test_an_owner_member_row_of_anyone_but_the_owner_grants_nothing(wired):
    """owner 는 과제 행의 주인 열(신원 앵커)만 정한다 — 주인 아닌 사람의 owner 멤버 행(고침 전의 들여오기가 남겼을 수 있는 행)은 역할이
    아니다. 종전에는 그 행만으로 상세 · 목록(내 역할 owner) · 이양이 열렸다."""
    store = wired
    victim = _shared_project("VICTIM-2")
    factories.seed_raw(store, "rr_project_members", {
        "project_id": victim, "owner_sub": STRANGER, "email": STRANGER, "role": "owner", "added_by": STRANGER,
        "added_at": 1, "updated_at": 1},
        reason="고침 전의 들여오기가 남긴 남의 owner 멤버 행 — 이제 들여오기는 parent_not_owned 로 막고 put_members 는 owner 를 받지 않는다")
    stranger = factories.ident(STRANGER)
    assert routes.project_role(victim, STRANGER) is None
    assert _refused(lambda: routes.get_project(victim, ident=stranger))[:2] == ("E404", 404)
    assert routes.list_projects(ident=stranger)["projects"] == []
    assert _refused(lambda: routes.transfer_project(victim, routes.TransferBody(to_email=STRANGER, reason="가로채기"),
                                                    ident=stranger))[:2] == ("E404", 404)
    assert store.query_one("SELECT owner_sub FROM rr_projects WHERE id = ?", (victim,))["owner_sub"] == OWNER


def test_imported_rows_cannot_hang_snapshot_heads_or_a_target_on_someone_elses_project(wired):
    """스냅샷 · 동결 잡 · 게이트 확인 · 배치 잡 행을 남의 과제 · 스냅샷 · 대상에 매달거나, 제 과제의 대상으로 남의 스냅샷을 가리키는(그
    상태를 브리프로 읽는) 줄은 parent_not_owned 다 — 주인 · 구성원의 과제 상세에 남이 지은 이름 · 판이 서지 않고, 남이 세운 잡이 주인의
    대상 줄에 서지 않는다. 스냅샷 없는 호출 원문은 그 동결 잡이 범위다(없는 잡도 같은 까닭)."""
    store = wired
    victim = _shared_project("VICTIM-3")
    sid = factories.make_snapshot(store, victim, [factories.adapter_fixture(MCAD_ONLY)], label="동결")["snapshot_id"]
    victim_target = factories.make_target(store, "snap", sid, agents=factories.agents())
    own = routes.create_project(routes.ProjectBody(code="OWN-3", name="제 과제", classification="internal"),
                                ident=factories.ident(STRANGER))["id"]
    out = _import(store, STRANGER, [
        {"table": "rr_snapshots", "row": {
            "id": "f" * 32, "project_id": victim, "owner_sub": STRANGER, "ir_version": "1", "ir_hash": "h" * 12,
            "ir_json": "{}", "source_ids_json": "[]", "kinds_json": "[\"mcad\"]", "node_count": 1, "edge_count": 0,
            "warnings_n": 0, "degraded_json": "[]", "app_versions_json": "{\"mcad\": {\"version\": \"9.9\"}}",
            "adapter_versions_json": "{}", "job_id": "e" * 32, "created_at": 2_000_000_000}},
        {"table": "rr_snapshot_jobs", "row": {
            "id": "e" * 32, "project_id": victim, "owner_sub": STRANGER, "label": "주입한 이름", "kinds_json": "[\"mcad\"]",
            "state": "done", "snapshot_id": "f" * 32, "created_at": 2_000_000_000}},
        {"table": "rr_gate_acks", "row": {
            "snapshot_id": sid, "gate": "G3", "owner_sub": STRANGER, "ack_by": OWNER, "ack_at": 1, "ack_reason": "주입한 확인",
            "gates_hash": "0123456789ab"}},
        {"table": "rr_gate_acks", "row": {
            "snapshot_id": "s-nowhere", "gate": "G1", "owner_sub": STRANGER, "ack_by": STRANGER, "ack_at": 1,
            "ack_reason": "미리 심은 확인", "gates_hash": "0123456789ab"}},
        {"table": "rr_targets", "row": {
            "target_key": "snap:forged", "owner_sub": STRANGER, "kind": "snap", "ref_id": sid, "project_id": own,
            "ir_hash": "h", "level": "C0", "external_sync_json": "{}", "created_at": 1, "updated_at": 1}},
        {"table": "rr_jobs", "row": {
            "id": "job-forged", "target_key": victim_target, "owner_sub": STRANGER, "tier": "A", "state": "queued",
            "created_at": 1, "updated_at": 1}},
        {"table": "rr_jobs", "row": {
            "id": "job-planted", "target_key": "snap:nowhere", "owner_sub": STRANGER, "tier": "A", "state": "queued",
            "created_at": 1, "updated_at": 1}},
        {"table": "rr_snapshot_calls", "row": {
            "call_id": "c-forged-001", "job_id": "job-nowhere", "snapshot_id": None, "owner_sub": STRANGER, "seq": 1,
            "source_kind": "mcad", "channel": "rest", "tool": "/tree", "ok": 1, "started_at": 1}},
    ])
    assert out["inserted"] == 0
    # 남의 것과 아직 없는 것(뒤에 주인이 옮겨 올 대상 · 스냅샷에 미리 심는 줄)은 같은 까닭이다.
    assert [(c["table"], c["reason"]) for c in out["conflicts"]] == [
        ("rr_snapshots", "parent_not_owned"), ("rr_snapshot_jobs", "parent_not_owned"),
        ("rr_snapshot_calls", "parent_not_owned"), ("rr_gate_acks", "parent_not_owned"), ("rr_gate_acks", "parent_not_owned"),
        ("rr_targets", "parent_not_owned"), ("rr_jobs", "parent_not_owned"), ("rr_jobs", "parent_not_owned")]
    for who in (OWNER, VIEWER):
        page = routes.get_project(victim, ident=factories.ident(who))
        assert [(h["id"], h["label"]) for h in page["snapshots"]] == [(sid, None)], who
        assert page["jobs"] == [], who
    assert routes.get_snapshot(sid, part="state", ident=factories.ident(OWNER))["gates"]["G3"]["ack_by"] is None
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_jobs WHERE target_key = ?", (victim_target,))["n"] == 0


def test_an_imported_merge_cannot_move_my_row_onto_someone_elses_project(wired):
    """병합(사람 확정이 자동을 이긴다)도 부모 열을 고쳐 쓴다 — 내 대상 행에 판정을 실어 들여오며 그 과제 · 가리키는 스냅샷을 남의 것으로
    바꾸면 parent_not_owned 로 눕고 내 행은 그대로다."""
    store = wired
    victim = _shared_project("VICTIM-5")
    victim_sid = factories.make_snapshot(store, victim, [factories.adapter_fixture(MCAD_ONLY)], label="동결")["snapshot_id"]
    own = routes.create_project(routes.ProjectBody(code="OWN-5", name="제 과제", classification="internal"),
                                ident=factories.ident(STRANGER))["id"]
    own_sid = factories.make_snapshot(store, own, [factories.adapter_fixture(MCAD_ONLY)], label="남",
                                      owner=STRANGER)["snapshot_id"]
    target_key = factories.make_target(store, "snap", own_sid, agents=factories.agents(), owner=STRANGER)
    mine = dict(store.query_one("SELECT * FROM rr_targets WHERE target_key = ?", (target_key,)))
    out = _import(store, STRANGER, [{"table": "rr_targets", "row": {
        **mine, "project_id": victim, "ref_id": victim_sid, "verdict_final": "go"}}])
    assert (out["merged"], [(c["table"], c["key"], c["reason"]) for c in out["conflicts"]]) == (
        0, [("rr_targets", target_key, "parent_not_owned")])
    after = store.query_one("SELECT project_id, ref_id, verdict_final FROM rr_targets WHERE target_key = ?", (target_key,))
    assert (after["project_id"], after["ref_id"], after["verdict_final"]) == (own, own_sid, None)
    # 제 과제 안에서의 같은 병합은 그대로 받는다.
    kept = _import(store, STRANGER, [{"table": "rr_targets", "row": {**mine, "verdict_final": "go"}}])
    assert (kept["merged"], kept["conflicts"]) == (1, [])


def test_the_card_role_never_reads_an_owner_member_row_of_anyone_but_the_owner(wired):
    """카드의 내 역할(projects_payload — MCP 목록도 같은 함수)도 project_role 과 같다 — 주인 아닌 사람의 owner 멤버 행은 역할이 아니다."""
    store = wired
    victim = _shared_project("VICTIM-6")
    factories.seed_raw(store, "rr_project_members", {
        "project_id": victim, "owner_sub": STRANGER, "email": STRANGER, "role": "owner", "added_by": STRANGER,
        "added_at": 1, "updated_at": 1},
        reason="고침 전의 들여오기가 남긴 남의 owner 멤버 행 — 이제 들여오기는 parent_not_owned 로 막고 put_members 는 owner 를 받지 않는다")
    assert [c["my_role"] for c in routes.projects_payload(project_ids=[victim], viewer=STRANGER)["projects"]] == [None]
    assert [c["my_role"] for c in routes.projects_payload(project_ids=[victim], viewer=EDITOR)["projects"]] == ["editor"]


def test_project_reads_keep_to_the_owners_snapshots_sources_and_character(wired):
    """과제 상세 · 목록은 대상 · 잡처럼 스냅샷 · 소스 · 성격 태그도 과제 주인의 행만 싣는다 — 주인이 다른 행(고침 전의 들여오기가 남의
    과제 id 로 남겼을 수 있는 행)은 머리 · 카드의 마지막 스냅샷 · 소스 · 태그에 서지 않는다. 스냅샷 머리의 이름은 같은 주인의 동결 잡만
    잇는다 — 옮겨 온 스냅샷(그 동결 잡 행은 이 박스에 없다)의 잡 id 로 남이 제 과제에 동결 잡 행을 들여와도(제 과제라 받는다) 그 이름을
    달지 않는다."""
    store = wired
    victim = _shared_project("HEADS-1")
    # 주인이 다른 박스에서 옮겨 온 스냅샷 한 줄 — 동결 잡 줄은 함께 오지 않았다(잡 id 만 남는다).
    moved = {"id": "s-moved", "project_id": victim, "owner_sub": OWNER, "ir_version": "1.0", "ir_hash": "m" * 64,
             "ir_json": "{}", "source_ids_json": "[]", "kinds_json": "[\"mcad\"]", "node_count": 1, "edge_count": 0,
             "warnings_n": 0, "degraded_json": "[]", "app_versions_json": "{}", "adapter_versions_json": "{}",
             "job_id": "job-moved", "created_at": 1_800_000_000}
    assert _import(store, OWNER, [{"table": "rr_snapshots", "row": moved}])["inserted"] == 1
    own = routes.create_project(routes.ProjectBody(code="OWN-4", name="제 과제", classification="internal"),
                                ident=factories.ident(STRANGER))["id"]
    theirs = factories.make_snapshot(store, own, [factories.adapter_fixture(MCAD_ONLY)], label="남",
                                     owner=STRANGER)["snapshot_id"]
    out = _import(store, STRANGER, [{"table": "rr_snapshot_jobs", "row": {
        "id": "job-moved", "project_id": own, "owner_sub": STRANGER, "label": "주입한 이름", "kinds_json": "[\"mcad\"]",
        "state": "done", "snapshot_id": None, "created_at": 1}}])
    assert (out["inserted"], out["conflicts"]) == (1, [])
    forged = {**dict(store.query_one("SELECT * FROM rr_snapshots WHERE id = ?", (theirs,))),
              "id": "s-forged", "project_id": victim, "ir_hash": "f" * 64, "created_at": 2_000_000_000}
    left = "고침 전의 들여오기가 남의 과제 id 로 남긴 행 — 이제 들여오기가 parent_not_owned 로 막아 생산자로 만들 수 없다"
    factories.seed_raw(store, "rr_snapshots", forged, reason=left)
    factories.seed_raw(store, "rr_sources", {
        "id": "src-forged", "project_id": victim, "owner_sub": STRANGER, "kind": "mcad", "app_key": "heax-step_forge",
        "ref_json": "{}", "ref_key": "mcad:heax-step_forge:{}", "created_at": 1}, reason=left)
    factories.seed_raw(store, "rr_character", {
        "id": "char-forged", "project_id": victim, "owner_sub": STRANGER, "facet": "intent", "tag": "char:forged",
        "statement": "주입한 성격", "status": "seed", "created_at": 1, "updated_at": 1}, reason=left)

    for who in (OWNER, EDITOR):
        page = routes.get_project(victim, ident=factories.ident(who))
        assert [(h["id"], h["label"]) for h in page["snapshots"]] == [("s-moved", None)], who
        assert page["sources"] == []
        assert "char:forged" not in {t["tag"] for t in page["character_top_tags"]}
        (card,) = [c for c in routes.list_projects(ident=factories.ident(who))["projects"] if c["id"] == victim]
        assert (card["last_snapshot_id"], card["last_snapshot_at"], card["sources"]) == ("s-moved", 1_800_000_000, [])


# ---------------------------------------------------------------- 4. 들여오기는 정규 키를 선점하지 못한다(사용자 결정 10-31 '들여오기 선점만 막는다')
MOVER = "mover@example.com"
NEW_OWNER = "new-owner@example.com"


def _own_lines(tmp_path, who: str, code: str) -> list[dict]:
    """그 사람이 다른 박스에서 동결한 과제 하나의 반출 줄(머리 뺀) — 과제 · 멤버 · 스냅샷 · 노드와 그 동결이 적립한 키 원장 행."""
    scratch = RiskStore(tmp_path / f"{code}.db")
    scratch.open()
    scratch.migrate()
    try:
        project_id = factories.make_project(scratch, owner=who, code=code)
        factories.make_snapshot(scratch, project_id, [factories.adapter_fixture(MCAD_ONLY)], label="동결", owner=who)
        return [json.loads(line) for line in list(export.iter_lines(scratch, who, 0))[1:]]
    finally:
        scratch.close()


def _keys(lines: list[dict]) -> list[str]:
    return sorted(line["row"]["ckey"] for line in lines if line["table"] == "rr_part_keys")


def test_an_import_cannot_claim_a_part_key_no_project_of_the_caller_carries(wired, tmp_path):
    """정규 키 원장은 열쇠가 ckey 하나인 과제 공용 표라 처음 적립한 사람이 주인이다. 들여오기는 아무 ckey 의 새 행이나 받아, 남이 주인의
    키(이름 · 크기 · 재질의 해시라 짐작할 수 있다)를 주인이 적립하기 전에 쥐면 주인의 동결은 그 행을 얻지 못하고 키 결정이 다 404 였다.
    이제 새 행은 부른 사람의 과제(그 사람의 과제 · 스냅샷 · 노드)가 그 키를 쓸 때만 받고 아니면 ckey_not_referenced 다 — 관계없는 키도,
    주인의 노드가 이미 이 박스에 있는 키도, 남이 주인의 스냅샷에 매단 노드(고침 전의 들여오기)로 걸친 키도 같다. 주인은 뒤에 그대로
    적립한다."""
    store = wired
    victim_lines = _own_lines(tmp_path, OWNER, "LATER-1")
    planned = _keys(victim_lines)
    assert planned, "동결이 적립한 키가 있어야 시험이 뜻이 있다"
    own = routes.create_project(routes.ProjectBody(code="OWN-7", name="제 과제", classification="internal"),
                                ident=factories.ident(STRANGER))["id"]          # 남도 제 과제는 있다 — 그 노드는 이 키를 쓰지 않는다

    def squat(ckey: str) -> dict:
        return {"table": "rr_part_keys", "row": {
            "ckey": ckey, "owner_sub": STRANGER, "status": "confirmed", "display_name": "선점", "name_norm_canon": "x",
            "geom_bucket": "b", "material_norm": "m", "first_project_id": own, "decided_by": STRANGER, "decided_at": 1,
            "created_at": 1, "updated_at": 1}}

    # ① 주인의 과제가 아직 이 박스에 없다 — 주인이 옮겨 올(또는 동결할) 키와 관계없는 키.
    out = _import(store, STRANGER, [squat(planned[0]), squat("ck:unrelated0001")])
    assert (out["inserted"], [(c["table"], c["key"], c["reason"]) for c in out["conflicts"]]) == (
        0, [("rr_part_keys", planned[0], "ckey_not_referenced"), ("rr_part_keys", "ck:unrelated0001", "ckey_not_referenced")])
    assert all(set(c) == {"table", "key", "reason"} for c in out["conflicts"])
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_part_keys")["n"] == 0
    # ② 주인의 과제 · 노드는 먼저 옮겨 왔고 키 줄은 아직이다 — 노드가 남의 것이라 남은 쥐지 못한다. 남이 주인의 스냅샷에 매단 노드(제 이름의
    # 노드 행)로 걸쳐도 그 스냅샷 · 과제가 남의 것이 아니라 같다.
    assert _import(store, OWNER, [line for line in victim_lines if line["table"] != "rr_part_keys"])["conflicts"] == []
    victim_sid = store.query_one("SELECT id FROM rr_snapshots WHERE owner_sub = ?", (OWNER,))["id"]
    factories.seed_raw(store, "rr_ir_nodes", {"snapshot_id": victim_sid, "nid": "n-forged", "owner_sub": STRANGER, "kind": "part",
                                              "source_kind": "mcad", "name": "FORGED", "name_norm": "forged", "ckey": planned[0]},
                       reason="고침 전의 들여오기가 주인의 스냅샷에 매단 남의 노드 행 — 이제 들여오기는 parent_not_owned 로 막는다(RD-10)")
    again = _import(store, STRANGER, [squat(key) for key in planned])
    assert (again["inserted"], {c["reason"] for c in again["conflicts"]}) == (0, {"ckey_not_referenced"})
    # 주인은 제 키를 그대로 받는다 — 행의 주인이 그 사람이고 키 대장 읽기가 '내 원장 행' 이라 말한다(결정을 받는다).
    taken = _import(store, OWNER, [line for line in victim_lines if line["table"] == "rr_part_keys"])
    assert (taken["inserted"], taken["conflicts"]) == (len(planned), [])
    assert {r["owner_sub"] for r in store.query("SELECT owner_sub FROM rr_part_keys")} == {OWNER}
    assert routes.get_part_key(planned[0], ident=factories.ident(OWNER))["mine"] is True


def test_an_import_takes_a_part_key_the_callers_own_snapshot_carries_already_here(wired, tmp_path):
    """부른 사람의 과제 · 스냅샷 · 노드가 이미 이 박스에 있으면(앞선 들여오기 — 두 번에 나눠 옮긴다) 그 노드가 쓰는 키의 새 행을 받는다."""
    store = wired
    lines = _own_lines(tmp_path, MOVER, "MOVE-1")
    first = _import(store, MOVER, [line for line in lines if line["table"] != "rr_part_keys"])
    assert first["conflicts"] == []
    second = _import(store, MOVER, [line for line in lines if line["table"] == "rr_part_keys"])
    assert (second["inserted"], second["conflicts"]) == (len(_keys(lines)), [])
    assert [r["ckey"] for r in store.query("SELECT ckey FROM rr_part_keys WHERE owner_sub = ? ORDER BY ckey", (MOVER,))] == _keys(lines)


def test_an_import_takes_a_part_key_its_own_snapshot_brings_in_the_same_body(wired, tmp_path):
    """같은 들여오기에서 앞서 들어가는 제 노드도 된다 — 줄은 표 차례(TABLE_ORDER — rr_ir_nodes 가 rr_part_keys 앞)로 쓰므로 키 줄을 본문
    맨 앞에 두어도 받는다."""
    store = wired
    lines = _own_lines(tmp_path, MOVER, "MOVE-2")
    keys_first = [line for line in lines if line["table"] == "rr_part_keys"] + [line for line in lines if line["table"] != "rr_part_keys"]
    out = _import(store, MOVER, keys_first)
    assert out["conflicts"] == [] and out["inserted"] == len(lines)
    assert [r["ckey"] for r in store.query("SELECT ckey FROM rr_part_keys WHERE owner_sub = ? ORDER BY ckey", (MOVER,))] == _keys(lines)


def test_a_part_key_stays_with_whoever_accrued_it_across_a_transfer_and_its_own_row_still_merges(wired):
    """이양은 키 원장 행을 옮기지 않는다(설계 — 행은 그 키를 처음 적립한 사람의 것이다, TRANSFER_PROJECT_TABLES 밖). 새 주인은 그 키의 새
    행을 들여오지 못한다(열쇠가 ckey 하나라 owner_conflict — 종전 그대로). 새 행 검사는 새 행에만 걸린다 — 과제를 넘긴 옛 주인의 행은 이제
    제 과제가 쓰지 않는 키지만 제 행의 병합(사람 확정이 자동을 이긴다)은 그대로 받는다. 병합 줄은 판정만 싣는다 — 옛 과제를 가리키는 칸
    (first_*)을 그대로 실으면 그 과제가 이제 남의 것이라 RD-10 의 parent_not_owned 다(종전 그대로)."""
    store = wired
    project_id = factories.make_project(store, code="MOVE-3")
    sid = factories.make_snapshot(store, project_id, [factories.adapter_fixture(MCAD_ONLY)], label="동결")["snapshot_id"]
    ckey = _first_ckey(store, sid)
    routes.transfer_project(project_id, routes.TransferBody(to_email=NEW_OWNER, reason="넘긴다"), ident=factories.ident(OWNER))
    assert store.query_one("SELECT owner_sub FROM rr_part_keys WHERE ckey = ?", (ckey,))["owner_sub"] == OWNER
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_ir_nodes WHERE ckey = ? AND owner_sub = ?", (ckey, OWNER))["n"] == 0
    row = dict(store.query_one("SELECT * FROM rr_part_keys WHERE ckey = ?", (ckey,)))
    theirs = _import(store, NEW_OWNER, [{"table": "rr_part_keys", "row": {**row, "owner_sub": NEW_OWNER}}])
    assert [(c["key"], c["reason"]) for c in theirs["conflicts"]] == [(ckey, "owner_conflict")]
    decided = {k: v for k, v in row.items() if not k.startswith("first_")}
    out = _import(store, OWNER, [{"table": "rr_part_keys", "row": {
        **decided, "status": "confirmed", "display_name": "커버", "decided_by": OWNER, "decided_at": 2, "updated_at": 2}}])
    assert (out["merged"], out["conflicts"]) == (1, [])
    assert dict(store.query_one("SELECT owner_sub, status, display_name FROM rr_part_keys WHERE ckey = ?", (ckey,))) == {
        "owner_sub": OWNER, "status": "confirmed", "display_name": "커버"}
