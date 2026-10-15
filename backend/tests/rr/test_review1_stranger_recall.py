# 반대 검토 1차(review1) 남 숨김 훑기 셋째 — 좌석 기억(E7)과 유사 과제 네 경로(함수 · REST · MCP)가 남의 과제를 싣지도, 있다는 것을 드러내지도 않는다(D45)
"""주인(OWNER)의 과제 다섯과 주인이 구성원(viewer)인 동료의 과제 하나를 생산자 경로(라우트 · freeze_snapshot)로 세워 답을 받아 두고,
남(STRANGER)의 과제 · 대상 · 좌석 의견 · 비공개 등록부 행 · 서술 적중을 더한 뒤의 답이 그것과 같은지 본다 — 남의 것이 목록에 없을
뿐 아니라 수(corpus_n · 벡터 문턱) · 순위(빈칸) · 좌석 줄의 채움으로도 새지 않는다. 같은 답이 '둘 다 비었다' 로 통과하지 않게 주인의
것과 구성원 과제의 것이 실리는지 따로 본다.

좌석 의견과 등록부 행은 손으로 쓴다 — 생산자는 패널 한 판 전부이고, E7 · subject 경로가 읽는 칸만 채운다(test_brief 와 같은 방식).
"""
from __future__ import annotations

import json
from typing import Any

import pytest

import app.mcp_server as srv
from app import brief, routes
from tests import factories

OWNER = factories.OWNER
COLLEAGUE = "colleague@example.com"
STRANGER = "stranger@example.com"
# 좌석 셋 — 주인의 의견이 있는 좌석 · 구성원 과제(동료 소유)의 의견만 있는 좌석 · 남의 의견만 있는 좌석. 남의 의견은 셋 모두에 더 새로 단다.
SEATS = ("mech-syn-0", "mech-syn-1", "mech-syn-2")
K = 20          # 벡터 상위 k 가 모두를 싣는 크기 — 남이 순위에 밀려 우연히 빠지는 일이 없다(MCP 상한도 20)


class _Adh:
    """서술 경로의 AIDataHub 흉내 — 받은 적중을 그대로 돌려준다(실 호출 0)."""
    available = True

    def __init__(self, hits: list[dict]) -> None:
        self.hits = hits

    def hybrid_search(self, q: str, **kwargs: Any) -> dict:
        return {"ok": True, "result": list(self.hits)}


def _hit(record_id: str, project_id: str | None) -> dict:
    return {"record_id": record_id, "section_id": "2",
            "tags": ["hwax-risk-review", *([f"hwax:project:{project_id}"] if project_id else [])]}


def _project(store, owner: str, code: str) -> tuple[str, str]:
    """과제 하나와 그 스냅샷(상태 · 특징 벡터까지) — (과제 id, 스냅샷 id)."""
    project_id = factories.make_project(store, owner=owner, code=code)
    snap = factories.make_snapshot(store, project_id, factories.fixture_adapter_results(), label=code, owner=owner)
    return project_id, snap["snapshot_id"]


def _target(store, snapshot_id: str, owner: str) -> str:
    return factories.make_target(store, "snap", snapshot_id, agents=factories.agents(("mech",), len(SEATS)), owner=owner)


def _opinion(store, opinion_id: str, target_key: str, owner: str, agent_key: str, created_at: int) -> None:
    store.execute(
        "INSERT INTO rr_seat_opinions(opinion_id, target_key, panel_id, owner_sub, agent_key, domain, origin, cycle,"
        " opinion_json, final_stance, raised_finding_ids_json, excerpt_for_rag, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (opinion_id, target_key, f"pan-{opinion_id}", owner, agent_key, "mech", "primary", 1, "{}", "conditional",
         json.dumps([f"pan-{opinion_id}#F1"]), f"{opinion_id} 의 발췌", created_at))


def _registry(store, target_key: str, owner: str, cluster_key: str, subject_key: str) -> None:
    """비공개(기본값) 등록부 행 하나 — subject 경로가 읽는 칸만."""
    store.execute(
        "INSERT INTO rr_registry(target_key, cluster_key, owner_sub, merged_json, subject_key, status, updated_at)"
        " VALUES (?,?,?,?,?,?,?)", (target_key, cluster_key, owner, json.dumps({"claim": "간극"}), subject_key, "open", 1))


@pytest.fixture
def world(risk_store, monkeypatch):
    """주인 쪽 원장 — 주인의 과제 P(심사 대상) · P-1~P-4, 주인이 viewer 인 동료의 과제 SHARED, 의견 둘, P 의 subject 위 주인의 등록부 행."""
    store = risk_store
    monkeypatch.setattr(routes, "get_store", lambda: store)
    project, snapshot = _project(store, OWNER, "P-NOW")
    mine = [_project(store, OWNER, f"P-{n}")[0] for n in range(1, 5)]
    shared, shared_snapshot = _project(store, COLLEAGUE, "C-SHARED")
    routes.put_members(shared, routes.MembersBody(members=[routes.MemberItem(email=OWNER, role="viewer")]),
                       ident=factories.ident(COLLEAGUE))
    mine_target = _target(store, store.query_one("SELECT id FROM rr_snapshots WHERE project_id = ?", (mine[0],))["id"],
                          OWNER)
    _opinion(store, "op-mine", mine_target, OWNER, SEATS[0], 100)
    _opinion(store, "op-shared", _target(store, shared_snapshot, COLLEAGUE), COLLEAGUE, SEATS[1], 100)
    subject = store.query_one("SELECT subject_key FROM rr_ir_edges WHERE snapshot_id = ? AND subject_key IS NOT NULL"
                              " ORDER BY subject_key LIMIT 1", (snapshot,))["subject_key"]
    _registry(store, mine_target, OWNER, "clu-mine", subject)
    return {"store": store, "project": project, "target": _target(store, snapshot, OWNER), "mine": mine,
            "shared": shared, "subject": subject}


def _add_stranger(world: dict) -> dict:
    """남의 과제 X — 스냅샷(벡터 후보) · 대상 · 좌석 셋 모두에 주인 것보다 새 의견(순위 1위감) · P 와 같은 subject 의 비공개 등록부 행."""
    store = world["store"]
    project, snapshot = _project(store, STRANGER, "S-X")
    target = _target(store, snapshot, STRANGER)
    for n, agent in enumerate(SEATS):
        _opinion(store, f"op-x{n}", target, STRANGER, agent, 900 + n)
    # 대상 행이 없는 의견(과제를 모른다) — 가장 새롭지만 누구의 과제인지 모르니 싣지 않는다.
    _opinion(store, "op-x-orphan", "snap:gone-x", STRANGER, SEATS[2], 999)
    _registry(store, target, STRANGER, "clu-x", world["subject"])
    return {"project": project, "target": target, "code": "S-X",
            "opinions": [*(f"op-x{n}" for n in range(len(SEATS))), "op-x-orphan"]}


def _leaks(answer: Any, stranger: dict) -> list[str]:
    text = json.dumps(answer, ensure_ascii=False, default=str)
    return [value for value in (stranger["project"], stranger["target"], stranger["code"], STRANGER, *stranger["opinions"])
            if value in text]


def _e7(world: dict) -> tuple[dict, dict]:
    built = brief.build_brief(world["store"], world["target"],
                              seats=[{"key": key, "domain": "mech", "origin": "primary"} for key in SEATS])
    return built["evidence"][built["keys"].index("E7")], built


# ---------------------------------------------------------------- E7 좌석 기억
def test_seat_memory_reads_only_opinions_of_projects_the_targets_owner_can_see(world):
    """남의 의견이 더 새로워도 주인의 좌석 줄에 오르지 않는다 — 주인의 의견 · 주인이 구성원인 과제의 의견은 그대로 오르고, 남의 의견만 있는
    좌석은 남의 것으로 채우지 않고 '이전 발언 없음' 이다. E7 은 남을 더하기 전과 같고 브리프 어디에도 남의 것이 없다."""
    before, _ = _e7(world)
    stranger = _add_stranger(world)
    after, built = _e7(world)

    lines = after["result"].split("\n")[1:]
    assert lines[0].startswith("narr:op-mine#pan-op-mine#F1 | mech-syn-0 | P-1/"), lines
    assert lines[1].startswith("narr:op-shared#pan-op-shared#F1 | mech-syn-1 | C-SHARED/"), lines
    assert lines[2] == "[mech-syn-2: 이전 발언 없음]", lines
    assert after == before
    assert _leaks(built, stranger) == []


# ---------------------------------------------------------------- 유사 과제(함수 — 서술 경로와 owner_sub 없는 기본 호출까지)
def test_similar_projects_lists_only_projects_the_owner_can_see_on_every_path(world):
    """벡터 · 서술 · subject 경로가 남의 과제를 싣지 않고 corpus_n 에도 세지 않는다 — 남의 적중이 끼어든 서술 순위는 실은 것끼리 1 부터
    빈칸 없이 센다. owner_sub 를 주지 않은 호출도 그 과제의 소유자로 거른다(남의 비공개 등록부 행이 subject 에 오르지 않는다)."""
    store, project, mine, shared = world["store"], world["project"], world["mine"], world["shared"]
    hits = [_hit("r-mine1", mine[0]), _hit("r-self", project), _hit("r-shared", shared), _hit("r-none", None),
            _hit("r-mine2", mine[1])]
    before = brief.similar_projects(store, project, K, adh=_Adh(hits))
    stranger = _add_stranger(world)
    theirs = [_hit("r-x1", stranger["project"]), hits[0], _hit("r-x2", stranger["project"]), *hits[1:4],
              _hit("r-x3", stranger["project"]), hits[4]]
    after = brief.similar_projects(store, project, K, adh=_Adh(theirs))

    assert after == before
    assert _leaks(after, stranger) == []
    assert after["corpus_n"] == 6 and after["reason"]["vector"] is None          # P · P-1~P-4 · SHARED
    assert sorted(e["project_id"] for e in after["vector"]) == sorted([*mine, shared])
    assert [e["rank"] for e in after["vector"]] == [1, 2, 3, 4, 5]
    assert [(e["record_id"], e["project_id"], e["rank"]) for e in after["text"]] == [
        ("r-mine1", mine[0], 1), ("r-shared", shared, 2), ("r-mine2", mine[1], 3)]
    assert [(e["subject_key"], e["project_ids"], e["n_registry"]) for e in after["subject"]] == [
        (world["subject"], [mine[0]], 1)]


# ---------------------------------------------------------------- 유사 과제(두 입구)
def test_similar_projects_answer_the_same_on_rest_and_mcp_before_and_after_a_stranger(world, monkeypatch):
    """REST GET /projects/{id}/similar 와 MCP risk_similar_projects 의 주인 답이 남을 더하기 전과 같고 남의 것이 없다 — 주인의 과제와 구성원
    과제는 그대로 선다."""
    project = world["project"]
    factories.act_as_delegate(monkeypatch, OWNER)

    def answers() -> tuple[dict, dict]:
        return routes.get_similar(project, K, ident=factories.ident(OWNER)), srv.risk_similar_projects(project_id=project, k=K)

    before = answers()
    stranger = _add_stranger(world)
    after = answers()

    assert after == before
    for answer in after:
        assert _leaks(answer, stranger) == []
        assert answer["corpus_n"] == 6
        assert sorted(e["project_id"] for e in answer["vector"]) == sorted([*world["mine"], world["shared"]])
        assert {e["project_id"] for e in answer["merged"]} >= {world["mine"][0], world["shared"]}
