# 반대 검토 1차(review1) 남의 것 숨김 — 라우터의 쓰기 경로 전부와 MCP 도구 전부가 남에게 과제 id · 대상 열쇠를 흘리지 않고 없는 것과 같은 답이다(L2 · 조정자 추가 1)
"""경로 목록은 라우터(`routes.router`)에서, 도구 목록은 MCP 서버(`mcp.list_tools`)에서 뽑는다 — 이 시험의 표가 그 둘과 같아야 한다(새
경로·도구가 남 시험 없이 들어오지 않는다). 표의 한 칸은 (부르는 함수, 부르는 사람이 준 id 의 이름) 이거나 남의 것을 가리키는 인자가
없는 까닭(면제)이다. 남(구성원이 아닌 사람)이 주인의 것을 가리켜 부른 답은 ① 과제 id 를 싣지 않고 ② 대상 열쇠는 부른 사람이 준 때만
싣고 ③ 없는 id 로 부른 답과 (준 id 를 지운 뒤) 같다. 주인이 같은 인자로 부르면 404 · not_visible 이 아니다(404 가 인자 탓이 아니다).

원장은 생산자 경로다 — 검토 → 쟁점 → 종합은 test_review1_closure 의 사슬이 세우고, 요구 · 사람 finding 은 주인의 라우트가, 큐레이션
큐는 라벨 훅(metrics.record_label — 야간 잡의 입구)이 세운다. 모듈마다 한 번 세운 원장 디렉터리를 시험마다 복사해 쓴다(주인의 쓰기가
다른 칸에 새지 않는다).
"""
from __future__ import annotations

import asyncio
import json
import shutil
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.routing import APIRoute

import app.mcp_server as srv
from app import export, metrics, routes
from app.errors import AppError
from app.risk_store import RiskStore
from tests import factories
from tests.rr.test_review1_closure import _chained
from tests.synth import review_rig as rig

OWNER = rig.OWNER
OTHER = "stranger@example.com"
CAPS = {"risk_issue_panel_cap": 1, "risk_issue_panel_hard_cap": 1}


# ---------------------------------------------------------------- 원장
def _ids(store: RiskStore, key: str) -> dict[str, str]:
    target = store.query_one("SELECT project_id, ref_id FROM rr_targets WHERE target_key = ?", (key,))
    diff = store.query_one("SELECT base_snapshot_id, target_snapshot_id FROM rr_diffs WHERE id = ?", (target["ref_id"],))
    project = store.query_one("SELECT code FROM rr_projects WHERE id = ?", (target["project_id"],))
    owner = factories.ident(OWNER)
    with factories.routes_store(store):
        requirement = routes.post_requirements(target["project_id"], [routes.RequirementItem(
            kind="scenario", name="drop_1_2m_corner", value_json={"taxonomy_key": "deep", "required": True})],
            ident=owner)["rows"][0]["id"]
        human = routes.create_human_finding(key, routes.HumanFindingBody(
            mechanism="interface", claim="사람이 본 간극", cites=[{"ref": "c:5b0e11aa22bb", "quote": "배치"}]), ident=owner)
    # 라벨은 카드 대조 원자에 붙지 않는다(학습 · 지표 거름) — 쟁점 패널 원자에 붙인다.
    panel_finding = store.query_one("SELECT finding_id FROM rr_findings WHERE target_key = ? AND source_kind = 'issue_panel'"
                                    " LIMIT 1", (key,))["finding_id"]
    queue = metrics.record_label(store, finding_id=panel_finding, source="sim", outcome="confirmed",
                                 evidence_ref="rpt:후속")["queue_id"]
    # 별칭 병합은 같은 family_key 의 두 클러스터끼리다.
    family = store.query_one("SELECT family_key FROM rr_registry WHERE target_key = ? GROUP BY family_key HAVING COUNT(*) > 1"
                             " ORDER BY family_key LIMIT 1", (key,))["family_key"]
    clusters = [r["cluster_key"] for r in store.query("SELECT cluster_key FROM rr_registry WHERE target_key = ? AND"
                                                       " family_key = ? ORDER BY cluster_key", (key, family))]
    return {
        "project": target["project_id"], "code": project["code"], "target": key, "diff": target["ref_id"],
        "base_snapshot": diff["base_snapshot_id"], "target_snapshot": diff["target_snapshot_id"],
        "job": store.query_one("SELECT id FROM rr_jobs WHERE target_key = ? AND mode = 'reviews'", (key,))["id"],
        "issue": store.query_one("SELECT issue_id FROM rr_issues WHERE target_key = ? LIMIT 1", (key,))["issue_id"],
        "panel": store.query_one("SELECT id FROM rr_panels WHERE target_key = ? AND kind = 'issue'", (key,))["id"],
        "cluster": clusters[0], "cluster2": clusters[1], "requirement": requirement,
        "human_finding": human["finding_id"], "panel_finding": panel_finding, "queue": queue,
        "ref": store.query_one("SELECT ref FROM rr_claim_refs WHERE target_key = ? ORDER BY ref LIMIT 1", (key,))["ref"],
    }


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    """모듈 한 번 — 사슬(검토 → 쟁점 → 종합)을 끝까지 돈 주인의 원장 디렉터리와 그 안의 id 들."""
    mp = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp("stranger-ledger")
    store = RiskStore(root / "risk_review.db")
    store.open()
    store.migrate()
    try:
        rig.configure(mp, store, root, **CAPS)
        ids = _ids(store, _chained(store))
    finally:
        store.close()
        mp.undo()
    return root, ids


@pytest.fixture
def ledger(template, tmp_path, monkeypatch):
    root, ids = template
    data = tmp_path / "data"
    shutil.copytree(root, data)
    store = RiskStore(data / "risk_review.db")
    store.open()
    store.migrate()
    rig.configure(monkeypatch, store, data, **CAPS)
    yield store, ids
    store.close()


# ---------------------------------------------------------------- REST 표
Call = Callable[[dict, Any], Any]
P = "/api"
EXEMPT: dict[tuple[str, str], str] = {
    ("POST", P + "/auth/sso"): "로그인 — 부르는 사람 자신의 SSO 단언뿐, 남의 것을 가리키는 인자가 없다",
    ("POST", P + "/auth/portal-pat"): "게이트웨이의 PAT 교환 — 부르는 사람 자신의 자격뿐이다",
    ("PUT", P + "/me/portal-pat"): "자기 설정(포털 PAT 등록)",
    ("PUT", P + "/me/portal-pat-auto"): "자기 설정(PAT 자동 발급 스위치)",
    ("POST", P + "/meta/metrics/recompute"): "자기 지표 다시 세기 — 과제 · 대상 인자가 없다",
    ("POST", P + "/vocab/synonyms"): "관리자 전용 공용 어휘 — 과제 · 대상 인자가 없다(남에게는 403)",
    ("POST", P + "/vocab/stop-tokens"): "관리자 전용 공용 어휘 — 과제 · 대상 인자가 없다(남에게는 403)",
    ("POST", P + "/import"): ("본문 행의 PK 는 부르는 사람이 준 값이다 — 남의 행과 PK 가 겹치면 그 줄만 owner_conflict 로 눕히고 값은 싣지"
                              " 않는다(test_the_import_answer_names_only_the_supplied_key)"),
}


def _create_project(ids: dict, ident) -> Any:
    return routes.create_project(routes.ProjectBody(code=f"p-{uuid.uuid4().hex[:8]}", name="남의 과제", classification="internal",
                                                    predecessor_project_id=ids["project"]), ident=ident)


def _inherit(ids: dict, ident) -> Any:
    mine = routes.create_project(routes.ProjectBody(code=f"p-{uuid.uuid4().hex[:8]}", name="내 과제",
                                                    classification="internal"), ident=ident)
    return routes.post_requirements_inherit(mine["id"], routes.InheritBody(from_project_id=ids["project"]), ident=ident)


CASES: dict[tuple[str, str], tuple[Call, tuple[str, ...]]] = {
    ("POST", P + "/projects"): (_create_project, ("project",)),
    ("PATCH", P + "/projects/{project_id}"): (
        lambda i, who: routes.patch_project(i["project"], routes.ProjectPatchBody(lifecycle="closed"), ident=who), ("project",)),
    ("PUT", P + "/projects/{project_id}/members"): (
        lambda i, who: routes.put_members(i["project"], routes.MembersBody(members=[], remove=[]), ident=who), ("project",)),
    ("POST", P + "/projects/{project_id}/transfer"): (
        lambda i, who: routes.transfer_project(i["project"], routes.TransferBody(to_email=OTHER, reason="넘겨 본다"),
                                               ident=who), ("project",)),
    ("POST", P + "/projects/{project_id}/purge"): (
        lambda i, who: routes.purge_project(i["project"], routes.PurgeBody(code="틀린-코드", reason="지워 본다"), ident=who),
        ("project",)),
    ("POST", P + "/projects/{project_id}/sources"): (
        lambda i, who: routes.add_source(i["project"], routes.SourceBody(kind="mcad", ref={"stepforge_project_id": "sf-x"}),
                                         ident=who), ("project",)),
    ("POST", P + "/projects/{project_id}/snapshots"): (
        lambda i, who: routes.create_snapshot(i["project"], routes.SnapshotBody(kinds=["mcad"]), ident=who), ("project",)),
    ("POST", P + "/projects/{project_id}/dims"): (
        lambda i, who: routes.add_dim(i["project"], routes.DimBody(name="gap_x", kind="gap", extractor="manual"),
                                      ident=who), ("project",)),
    ("POST", P + "/projects/{project_id}/requirements"): (
        lambda i, who: routes.post_requirements(i["project"], [], ident=who), ("project",)),
    ("PUT", P + "/requirements/{requirement_id}"): (
        lambda i, who: routes.put_requirement(i["requirement"], routes.RequirementDecision(status="confirmed"), ident=who),
        ("requirement",)),
    ("POST", P + "/projects/{project_id}/requirements/inherit"): (_inherit, ("project",)),
    ("PUT", P + "/projects/{project_id}/iface-ledger"): (
        lambda i, who: routes.put_iface_ledger(i["project"], [], ident=who), ("project",)),
    ("POST", P + "/snapshots/{snapshot_id}/gates/{gate}/ack"): (
        lambda i, who: routes.post_gate_ack(i["target_snapshot"], "G1", routes.GateAckBody(reason="넘겨 본다"), ident=who),
        ("target_snapshot",)),
    ("DELETE", P + "/snapshots/{snapshot_id}/gates/{gate}/ack"): (
        lambda i, who: routes.delete_gate_ack(i["target_snapshot"], "G1", ident=who), ("target_snapshot",)),
    ("POST", P + "/sameas/decide"): (
        lambda i, who: routes.post_sameas_decide([{"decision": "confirm", "scope": "intra", "a": "s:a", "b": "s:b",
                                                   "pair_key": i["project"]}], ident=who), ("project",)),
    ("POST", P + "/diffs"): (
        lambda i, who: routes.create_diff(routes.DiffBody(base_snapshot_id=i["base_snapshot"],
                                                          target_snapshot_id=i["target_snapshot"]), ident=who),
        ("base_snapshot", "target_snapshot")),
    ("POST", P + "/targets"): (
        lambda i, who: routes.create_target(routes.TargetBody(kind="diff", ref_id=i["diff"], consent=True), ident=who),
        ("diff",)),
    ("POST", P + "/targets/{target_key}/refresh_roster"): (
        lambda i, who: routes.refresh_roster(i["target"], routes.RosterBody(agents=[]), ident=who), ("target",)),
    ("POST", P + "/targets/{target_key}/units"): (
        lambda i, who: routes.post_units(i["target"], routes.UnitsBody(), ident=who), ("target",)),
    ("POST", P + "/targets/{target_key}/flow"): (
        lambda i, who: routes.post_target_flow(i["target"], routes.FlowBody(to="panels", reason="바꿔 본다"), ident=who),
        ("target",)),
    ("POST", P + "/targets/{target_key}/jobs"): (
        lambda i, who: routes.create_job(i["target"], routes.JobBody(mode="reviews"), ident=who), ("target",)),
    ("POST", P + "/jobs/{job_id}/{action}"): (lambda i, who: routes.job_action(i["job"], "pause", ident=who), ("job",)),
    ("PUT", P + "/targets/{target_key}/coverage/{agent_key}"): (
        lambda i, who: routes.put_coverage(i["target"], rig.SEAL, routes.CoverageBody(status="deferred", reason="미뤄 본다"),
                                           ident=who), ("target",)),
    ("POST", P + "/targets/{target_key}/undefer"): (
        lambda i, who: routes.post_undefer(i["target"], routes.UndeferBody(reason="풀어 본다"), ident=who), ("target",)),
    ("POST", P + "/targets/{target_key}/cells/retry"): (
        lambda i, who: routes.post_cells_retry(i["target"], routes.CellsRetryBody(filter={}, reason="다시 열어 본다"),
                                               ident=who), ("target",)),
    ("POST", P + "/targets/{target_key}/cells/skip"): (
        lambda i, who: routes.post_cells_skip(i["target"], routes.CellsSkipBody(filter={}, reason="넘겨 본다"), ident=who),
        ("target",)),
    ("POST", P + "/targets/{target_key}/closure/acks/{item}"): (
        lambda i, who: routes.post_closure_ack(i["target"], "issues_untried", routes.CloseAckBody(reason="넘겨 본다"),
                                               ident=who), ("target",)),
    ("DELETE", P + "/targets/{target_key}/closure/acks/{item}"): (
        lambda i, who: routes.delete_closure_ack(i["target"], "issues_untried", ident=who), ("target",)),
    ("PUT", P + "/issues/{issue_id}"): (
        lambda i, who: routes.put_issue(i["issue"], routes.IssueActionBody(action="skip", reason="넘겨 본다"), ident=who),
        ("issue",)),
    ("POST", P + "/targets/{target_key}/report"): (
        lambda i, who: routes.post_report(i["target"], routes.ReportBody(), ident=who), ("target",)),
    ("PUT", P + "/targets/{target_key}/verdict"): (
        lambda i, who: routes.put_verdict(i["target"], routes.VerdictBody(verdict="hold"), ident=who), ("target",)),
    ("PUT", P + "/registry/{cluster_key:path}/status"): (
        lambda i, who: routes.put_registry_status(i["cluster"], routes.RegistryStatusBody(status="mitigated", note="막았다"),
                                                  ident=who), ("cluster",)),
    ("PUT", P + "/registry/{cluster_key:path}/merge"): (
        lambda i, who: routes.put_registry_merge(i["cluster"], routes.RegistryMergeBody(into=i["cluster2"],
                                                                                         reason="cluster_merge"), ident=who),
        ("cluster",)),
    ("DELETE", P + "/registry/{cluster_key:path}/merge"): (
        lambda i, who: routes.delete_registry_merge(i["cluster"], ident=who), ("cluster",)),
    ("PUT", P + "/registry/{cluster_key:path}/visibility"): (
        lambda i, who: routes.put_registry_visibility(i["cluster"], routes.RegistryVisibilityBody(visibility="org"),
                                                      ident=who), ("cluster",)),
    ("POST", P + "/targets/{target_key}/resync"): (lambda i, who: routes.post_resync(i["target"], ident=who), ("target",)),
    ("POST", P + "/panels/{panel_id}/complete"): (
        lambda i, who: routes.post_panel_complete(i["panel"], routes.PanelCompleteBody(engine="web", decision_text="결정",
                                                                                       turns=[]), ident=who), ("panel",)),
    ("POST", P + "/panels/{panel_id}/repersist"): (
        lambda i, who: routes.post_panel_repersist(i["panel"], ident=who), ("panel",)),
    ("POST", P + "/targets/{target_key}/findings"): (
        lambda i, who: routes.create_human_finding(i["target"], routes.HumanFindingBody(
            mechanism="interface", claim="남이 적어 본다", cites=[{"ref": "c:5b0e11aa22bb", "quote": "배치"}]), ident=who),
        ("target",)),
    ("PUT", P + "/findings/{finding_id}"): (
        lambda i, who: routes.update_human_finding(i["human_finding"], routes.HumanFindingBody(
            mechanism="interface", claim="고쳐 본다", cites=[{"ref": "c:5b0e11aa22bb", "quote": "배치"}]), ident=who),
        ("human_finding",)),
    ("DELETE", P + "/findings/{finding_id}"): (
        lambda i, who: routes.delete_human_finding(i["human_finding"], ident=who), ("human_finding",)),
    ("POST", P + "/findings/{finding_id}/labels"): (
        lambda i, who: routes.post_finding_label(i["panel_finding"], routes.LabelBody(outcome="confirmed", evidence_ref="rpt:x",
                                                                                       source="expert_review"), ident=who),
        ("panel_finding",)),
    ("PUT", P + "/curation/{queue_id}"): (
        lambda i, who: routes.put_curation(i["queue"], routes.CurationDecisionBody(decision="confirmed", reason="확인"),
                                           ident=who), ("queue",)),
}


# 주인의 것이 있어야 그 경로가 뜻이 있는 칸 — 주인이 먼저 한다(별칭을 걷으려면 별칭이, 확인을 취소하려면 확인이 있어야 한다).
PREPARE: dict[tuple[str, str], Callable[[dict, RiskStore], Any]] = {
    ("DELETE", P + "/registry/{cluster_key:path}/merge"): lambda i, store: routes.put_registry_merge(
        i["cluster"], routes.RegistryMergeBody(into=i["cluster2"], reason="cluster_merge"), ident=factories.ident(OWNER)),
    ("DELETE", P + "/targets/{target_key}/closure/acks/{item}"): lambda i, store: _owner_ack(i, store),
}
# 남이 받는 답 — 기본은 없는 것과 같은 404 다. 남의 것을 읽지 않고 제 행만 쓰는 경로는 성공한다(그 답에도 주인의 값이 없다).
EXPECT: dict[tuple[str, str], int] = {("POST", P + "/projects"): 200, ("POST", P + "/sameas/decide"): 200}


def _owner_ack(ids: dict, store: RiskStore) -> Any:
    from app import closure  # noqa: PLC0415

    item = next(q for q in closure.refresh(store, ids["target"])["qualifiers"] if q["item"] == "issues_untried")
    return routes.post_closure_ack(ids["target"], "issues_untried",
                                   routes.CloseAckBody(reason="넘긴다", basis_hash=item["basis_hash"]),
                                   ident=factories.ident(OWNER))


def _mutating_routes() -> set[tuple[str, str]]:
    return {(method, route.path) for route in routes.router.routes if isinstance(route, APIRoute)
            for method in route.methods if method in ("POST", "PUT", "PATCH", "DELETE")}


def _answer(call: Callable[[], Any]) -> tuple:
    """(갈래, 상태, 글, 비교 글) — AppError 는 (코드, HTTP, 글과 detail), 성공은 ('ok', 200, 본문, 본문의 칸 이름 — 새로 만든 id ·
    시각은 부를 때마다 다르다)."""
    try:
        out = call()
    except AppError as exc:
        text = exc.message + json.dumps(exc.detail or {}, ensure_ascii=False, sort_keys=True, default=str)
        return exc.code, exc.http_status, text, text
    return "ok", 200, json.dumps(out, ensure_ascii=False, sort_keys=True, default=str), json.dumps(
        sorted(out) if isinstance(out, dict) else type(out).__name__)


# 없는 값 — 문법이 있는 칸(참조)은 문법에 맞는 없는 값이다(문법 오류로 먼저 갈리지 않게).
MISSING_VALUES = {"ref": "c:000000000000"}


def _missing(ids: dict, supplied: tuple[str, ...]) -> dict:
    return {**ids, **{name: MISSING_VALUES.get(name, f"no-such-{name.replace('_', '-')}") for name in supplied}}


def _strip(text: str, values: dict, supplied: tuple[str, ...]) -> str:
    for name in supplied:
        text = text.replace(values[name], f"<{name}>")
    return text


def _normal(answer: tuple, values: dict, supplied: tuple[str, ...]) -> tuple:
    return answer[0], answer[1], _strip(answer[3], values, supplied)


def _no_leak(text: str, ids: dict, supplied: tuple[str, ...]) -> None:
    """준 id 를 지운 글에 과제 id · 대상 열쇠가 없다(준 id 가 대상 열쇠를 품으면 — 사람 finding id — 그것은 준 것이다)."""
    text = _strip(text, ids, supplied)
    for name in ("project", "target"):
        assert ids[name] not in text, (name, text[:300])


def test_every_mutating_route_in_the_router_is_in_this_table():
    """라우터의 쓰기 경로 == 이 표(시험 칸 + 면제) — 새 경로가 남 시험 없이 들어오지 않는다."""
    assert not set(CASES) & set(EXEMPT)
    assert _mutating_routes() == set(CASES) | set(EXEMPT)


@pytest.mark.parametrize("case", sorted(CASES), ids=lambda c: f"{c[0]} {c[1][len(P):]}")
def test_a_stranger_gets_the_missing_answer_on_every_mutating_route(ledger, case):
    """남이 주인의 것을 가리켜 쓰면 과제 id 를 싣지 않고(대상 열쇠는 준 때만) 없는 id 로 부른 답과 같다. 주인으로는 404 가 아니다."""
    store, ids = ledger
    call, supplied = CASES[case]
    if case in PREPARE:
        PREPARE[case](ids, store)
    stranger = factories.ident(OTHER)
    theirs = _answer(lambda: call(ids, stranger))
    gone = _missing(ids, supplied)
    missing = _answer(lambda: call(gone, stranger))
    _no_leak(theirs[2], ids, supplied)
    assert theirs[1] == EXPECT.get(case, 404), theirs
    assert _normal(theirs, ids, supplied) == _normal(missing, gone, supplied)
    mine = _answer(lambda: call(ids, factories.ident(OWNER)))
    assert mine[1] != 404, (case, mine)


def test_the_import_answer_names_only_the_supplied_key(ledger):
    """면제한 들여오기 — 남이 주인의 대상 행과 PK 가 같은 줄을 들여오면 그 줄만 owner_conflict 로 눕고, 답에는 준 열쇠 말고 주인의 값
    (과제 id)이 없다. 주인의 행은 그대로다."""
    store, ids = ledger
    row = dict(store.query_one("SELECT * FROM rr_targets WHERE target_key = ?", (ids["target"],)))
    head = next(iter(export.iter_lines(store, OTHER, 0)))                  # 남의 반출 머리(빈 원장)
    line = json.dumps({"table": "rr_targets", "row": {**row, "owner_sub": OTHER, "project_id": "p-stranger"}},
                      ensure_ascii=False, default=str)

    class _Body:
        async def body(self) -> bytes:
            return (head.rstrip("\n") + "\n" + line + "\n").encode("utf-8")

    out = asyncio.run(routes.post_import(_Body(), ident=factories.ident(OTHER)))
    text = json.dumps(out, ensure_ascii=False)
    assert ids["project"] not in text and [c["reason"] for c in out["conflicts"]] == ["owner_conflict"]
    assert store.query_one("SELECT owner_sub, project_id FROM rr_targets WHERE target_key = ?", (ids["target"],))["project_id"] == (
        ids["project"])


# ---------------------------------------------------------------- MCP 표
MCP_EXEMPT: dict[str, str] = {
    "risk_list_projects": "발견 — id 인자가 없다(남의 과제가 목록에 없는지는 아래 시험이 본다)",
    "risk_taxonomy": "공용 어휘 — id 인자가 없다",
    "risk_create_project": "새 과제 — 앞 과제(predecessor_project_id)는 REST POST /projects 칸과 같은 함수다",
}
MCP_CASES: dict[str, tuple[Callable[[dict], Any], tuple[str, ...]]] = {
    "risk_get_coverage": (lambda i: srv.risk_get_coverage(target_key=i["target"]), ("target",)),
    "risk_list_panels": (lambda i: srv.risk_list_panels(target_key=i["target"]), ("target",)),
    "risk_get_panel_transcript": (lambda i: srv.risk_get_panel_transcript(panel_id=i["panel"]), ("panel",)),
    "risk_get_precedents": (lambda i: srv.risk_get_precedents(diff_id=i["diff"]), ("diff",)),
    "risk_similar_projects": (lambda i: srv.risk_similar_projects(project_id=i["project"]), ("project",)),
    "risk_get_snapshot": (lambda i: srv.risk_get_snapshot(snapshot_id=i["target_snapshot"], part="state"), ("target_snapshot",)),
    "risk_get_diff": (lambda i: srv.risk_get_diff(diff_id=i["diff"], part="summary"), ("diff",)),
    "risk_get_registry": (lambda i: srv.risk_get_registry(target_key=i["target"]), ("target",)),
    "risk_claims_for_ref": (lambda i: srv.risk_claims_for_ref(ref=i["ref"]), ("ref",)),
    "risk_get_brief": (lambda i: srv.risk_get_brief(target_key=i["target"], brief_token="t-0"), ("target",)),
    "risk_submit_panel_result": (lambda i: srv.risk_submit_panel_result(panel_id=i["panel"], engine="mcp", decision_text="결정",
                                                                        turns=[], actor=OTHER), ("panel",)),
    "risk_add_finding": (lambda i: srv.risk_add_finding(target_key=i["target"], claim="남이 적어 본다",
                                                        cites=[{"ref": "c:5b0e11aa22bb", "quote": "배치"}], actor=OTHER),
                         ("target",)),
    "risk_next_step": (lambda i: srv.risk_next_step(project_id=i["project"]), ("project",)),
    "risk_add_source": (lambda i: srv.risk_add_source(project_id=i["project"], kind="mcad", ref={"stepforge_project_id": "sf"}),
                        ("project",)),
    "risk_capture_snapshot": (lambda i: srv.risk_capture_snapshot(project_id=i["project"]), ("project",)),
    "risk_ack_gate": (lambda i: srv.risk_ack_gate(snapshot_id=i["target_snapshot"], gate="G1", reason="넘겨 본다"),
                      ("target_snapshot",)),
    "risk_get_sameas": (lambda i: srv.risk_get_sameas(base_snapshot_id=i["base_snapshot"],
                                                      target_snapshot_id=i["target_snapshot"]),
                        ("base_snapshot", "target_snapshot")),
    "risk_decide_sameas": (lambda i: srv.risk_decide_sameas(base_snapshot_id=i["base_snapshot"],
                                                            target_snapshot_id=i["target_snapshot"], decisions=[]),
                           ("base_snapshot", "target_snapshot")),
    "risk_create_diff": (lambda i: srv.risk_create_diff(base_snapshot_id=i["base_snapshot"],
                                                        target_snapshot_id=i["target_snapshot"]),
                         ("base_snapshot", "target_snapshot")),
    "risk_open_target": (lambda i: srv.risk_open_target(kind="diff", ref_id=i["diff"], consent=True), ("diff",)),
    "risk_start_job": (lambda i: srv.risk_start_job(target_key=i["target"], mode="reviews"), ("target",)),
    "risk_job_action": (lambda i: srv.risk_job_action(job_id=i["job"], action="pause"), ("job",)),
    "risk_repersist_panel": (lambda i: srv.risk_repersist_panel(panel_id=i["panel"]), ("panel",)),
    "risk_get_units": (lambda i: srv.risk_get_units(target_key=i["target"]), ("target",)),
    "risk_get_cells": (lambda i: srv.risk_get_cells(target_key=i["target"]), ("target",)),
    "risk_get_expert_report": (lambda i: srv.risk_get_expert_report(target_key=i["target"], agent_key=rig.SEAL), ("target",)),
    "risk_get_issues": (lambda i: srv.risk_get_issues(target_key=i["target"]), ("target",)),
    "risk_get_report": (lambda i: srv.risk_get_report(target_key=i["target"]), ("target",)),
}


# 남이 받는 답 — 기본은 not_visible · E404 다. 역색인은 보이는 과제로 좁혀 빈 목록이고(없는 참조와 같다), 브리프는 토큰 대조가 먼저다
# (토큰이 곧 자격이라 남의 대상 열쇠만으로는 아무것도 갈리지 않는다).
MCP_EXPECT: dict[str, str] = {"risk_claims_for_ref": "ok", "risk_get_brief": "brief_token_invalid"}


def _mcp(fn: Callable[[], Any]) -> tuple:
    out = fn()
    out = asyncio.run(out) if asyncio.iscoroutine(out) else out
    text = json.dumps(out, ensure_ascii=False, sort_keys=True, default=str)
    return str(out.get("error") or "ok"), 0, text, text


def test_every_mcp_tool_is_in_this_table():
    """MCP 도구 == 이 표(시험 칸 + 면제)."""
    names = {t.name for t in asyncio.run(srv.mcp.list_tools())}
    assert not set(MCP_CASES) & set(MCP_EXEMPT)
    assert names == set(MCP_CASES) | set(MCP_EXEMPT)


@pytest.mark.parametrize("name", sorted(MCP_CASES))
def test_a_stranger_gets_the_missing_answer_from_every_mcp_tool(ledger, monkeypatch, name):
    """남(게이트웨이 위임으로 확인된 다른 사람)이 주인의 것을 가리키면 도구 답이 과제 id 를 싣지 않고(대상 열쇠는 준 때만) 없는 id 의
    답과 같다. 주인으로는 not_visible · E404 가 아니다."""
    store, ids = ledger
    call, supplied = MCP_CASES[name]
    factories.act_as_delegate(monkeypatch, OTHER)
    theirs = _mcp(lambda: call(ids))
    gone = _missing(ids, supplied)
    missing = _mcp(lambda: call(gone))
    _no_leak(theirs[2], ids, supplied)
    assert theirs[0] in ((MCP_EXPECT[name],) if name in MCP_EXPECT else ("not_visible", "E404")), theirs
    assert _normal(theirs, ids, supplied) == _normal(missing, gone, supplied)
    factories.act_as_delegate(monkeypatch, OWNER)
    mine = _mcp(lambda: call(ids))
    assert mine[0] not in ("not_visible", "E404"), (name, mine)


def test_the_exempt_mcp_tools_do_not_name_the_owners_project_or_target(ledger, monkeypatch):
    """면제한 발견 · 어휘 · 새 과제 도구도 남에게 주인의 과제 id · 대상 열쇠를 싣지 않는다."""
    store, ids = ledger
    factories.act_as_delegate(monkeypatch, OTHER)
    for fn in (lambda: srv.risk_list_projects(), lambda: srv.risk_taxonomy(),
               lambda: srv.risk_create_project(code="stranger-mcp", name="남의 과제", classification="internal")):
        _no_leak(_mcp(fn)[2], ids, ())
