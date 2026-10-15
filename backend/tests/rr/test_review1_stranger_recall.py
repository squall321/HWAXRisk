# 반대 검토 1차(review1) 남 숨김 훑기 셋째 — 좌석 기억(E7) · 유사 과제 네 경로 · 선례 · E6 이 남의 과제를 싣지도, 있다는 것을 드러내지도 않는다(D45 · D46)
"""주인(OWNER)의 과제 다섯과 주인이 구성원(viewer)인 동료의 과제 하나를 생산자 경로(라우트 · freeze_snapshot)로 세워 답을 받아 두고,
남(STRANGER)의 과제 · 대상 · 좌석 의견 · 비공개 등록부 행 · 서술 적중을 더한 뒤의 답이 그것과 같은지 본다 — 남의 것이 목록에 없을
뿐 아니라 수(corpus_n · 벡터 문턱 · E6 의 n_projects) · 순위(빈칸) · 좌석 줄의 채움으로도 새지 않는다. 같은 답이 '둘 다 비었다' 로
통과하지 않게 주인의 것과 구성원 과제의 것이 실리는지 따로 본다.

D46 — 조직 공개로 연 남의 등록부 행은 그 행으로만 선다(E6 은 그 과제의 성격 진술을 싣지 않는다). MCP 로 부른 구성원에게 다른 과제는
소유자와 그 사람 둘 다 볼 수 있는 것만이다. 과제 거름을 밝히지 않은 AIDataHub 클라이언트로는 전체 색인을 찾지 않는다.

좌석 의견 · 등록부 행 · 성격 진술은 손으로 쓴다 — 생산자는 패널 한 판 전부이고, 읽는 칸만 채운다(test_brief 와 같은 방식).
"""
from __future__ import annotations

import json
from typing import Any

import pytest

import app.mcp_server as srv
from app import brief, registry, routes
from app.adh_client import AdhClient
from tests import factories

OWNER = factories.OWNER
COLLEAGUE = "colleague@example.com"
STRANGER = "stranger@example.com"
MEMBER = "member@example.com"
# 좌석 셋 — 주인의 의견이 있는 좌석 · 구성원 과제(동료 소유)의 의견만 있는 좌석 · 남의 의견만 있는 좌석. 남의 의견은 셋 모두에 더 새로 단다.
SEATS = ("mech-syn-0", "mech-syn-1", "mech-syn-2")
K = 20          # 벡터 상위 k 가 모두를 싣는 크기 — 남이 순위에 밀려 우연히 빠지는 일이 없다(MCP 상한도 20)


class _Adh:
    """서술 경로의 AIDataHub 흉내 — 과제 거름을 밝히되 받은 적중을 그대로 돌려준다(거름을 어긴 색인 — 받은 쪽의 거름을 본다)."""
    available = True
    supports_project_filter = True

    def __init__(self, hits: list[dict]) -> None:
        self.hits = hits

    def hybrid_search(self, q: str, **kwargs: Any) -> dict:
        return {"ok": True, "result": list(self.hits)}


class _Recorder:
    """AIDataHub 흉내 — 부른 찾기와 인자를 적는다. 과제 거름을 밝히는지(`supports_project_filter`)는 만들 때 고른다."""
    available = True

    def __init__(self, *, filtered: bool, hits: list[dict]) -> None:
        self.supports_project_filter = filtered
        self.hits = hits
        self.calls: list[tuple[str, dict]] = []

    def hybrid_search(self, q: str, **kwargs: Any) -> dict:
        self.calls.append(("hybrid_search", kwargs))
        return {"ok": True, "result": list(self.hits)}

    def agent_search(self, agent_type: str, q: str, **kwargs: Any) -> dict:
        self.calls.append(("agent_search", kwargs))
        return {"ok": True, "result": [{"record_id": "rec-adh-memory", "summary": "색인에서 온 기억",
                                        "content": {"meta": {"portal": {"opinion_id": "op-adh", "finding_id": "pan-adh#F1"}}}}]}


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


def _members(project_id: str, owner: str, *emails: str) -> None:
    """`routes.put_members` — 그 과제에 viewer 를 더한다."""
    routes.put_members(project_id, routes.MembersBody(members=[routes.MemberItem(email=e, role="viewer") for e in emails]),
                       ident=factories.ident(owner))


def _snapshot_of(store, project_id: str) -> str:
    return store.query_one("SELECT id FROM rr_snapshots WHERE project_id = ?", (project_id,))["id"]


def _finding(store, finding_id: str, target_key: str, project_id: str, owner: str, cluster_key: str) -> None:
    """패턴 원자 하나 — learning.collect_atoms 가 읽는 칸만."""
    store.execute(
        "INSERT INTO rr_findings(finding_id, claim_uid, target_key, panel_id, project_id, owner_sub, direction, subject_key,"
        " cluster_key, finding_json, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (finding_id, finding_id, target_key, f"pan-{finding_id}", project_id, owner, "risk", "ck:pattern", cluster_key,
         json.dumps({"claim": f"{finding_id} 의 주장"}), "open", 1))


def _pattern(store, pattern_id: str, owner: str, cluster_key_norm: str, visibility: str) -> None:
    store.execute(
        "INSERT INTO rr_patterns(id, owner_sub, visibility, cluster_key_norm, status, n_projects, precision, created_at,"
        " updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (pattern_id, owner, visibility, cluster_key_norm, "candidate", 2, 0.5, 1, 1))


@pytest.fixture
def world(risk_store, monkeypatch):
    """주인 쪽 원장 — 주인의 과제 P(심사 대상) · P-1~P-4, 주인이 viewer 인 동료의 과제 SHARED, 의견 둘, P 의 subject 위 주인의 등록부 행과
    SHARED 위 동료의 비공개 행(구성원이어도 남의 비공개 행은 등록부 거름(owner_sub · 조직 공개) 밖이다 — owner_sub 없는 호출도 같다)."""
    store = risk_store
    monkeypatch.setattr(routes, "get_store", lambda: store)
    project, snapshot = _project(store, OWNER, "P-NOW")
    mine = [_project(store, OWNER, f"P-{n}")[0] for n in range(1, 5)]
    shared, shared_snapshot = _project(store, COLLEAGUE, "C-SHARED")
    _members(shared, COLLEAGUE, OWNER)
    mine_target = _target(store, _snapshot_of(store, mine[0]), OWNER)
    _opinion(store, "op-mine", mine_target, OWNER, SEATS[0], 100)
    shared_target = _target(store, shared_snapshot, COLLEAGUE)
    _opinion(store, "op-shared", shared_target, COLLEAGUE, SEATS[1], 100)
    subject = store.query_one("SELECT subject_key FROM rr_ir_edges WHERE snapshot_id = ? AND subject_key IS NOT NULL"
                              " ORDER BY subject_key LIMIT 1", (snapshot,))["subject_key"]
    _registry(store, mine_target, OWNER, "clu-mine", subject)
    _registry(store, shared_target, COLLEAGUE, "clu-shared-private", subject)
    return {"store": store, "project": project, "target": _target(store, snapshot, OWNER), "mine": mine,
            "shared": shared, "subject": subject, "mine_target": mine_target}


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


def _build(world: dict, adh: Any = None) -> dict:
    return brief.build_brief(world["store"], world["target"], adh=adh,
                             seats=[{"key": key, "domain": "mech", "origin": "primary"} for key in SEATS])


def _item(built: dict, key: str) -> dict:
    return built["evidence"][built["keys"].index(key)]


def _e7(world: dict) -> tuple[dict, dict]:
    built = _build(world)
    return _item(built, "E7"), built


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


# ---------------------------------------------------------------- E6(D46 — 조직 공개 행은 그 행으로만 · 수는 보이는 과제만)
def test_e6_carries_no_character_of_a_project_that_came_in_by_an_org_shared_row(world):
    """남이 조직 공개로 연 등록부 행은 subject 경로 · merged · E5 에 그 행으로 선다(남이 연 것). 그러나 그 행으로 merged 에 든 남의 과제의
    성격 진술은 E6 에 싣지 않고, E6 의 n_projects 는 타깃 소유자가 볼 수 있는 과제만 센다 — 남을 더하기 전과 같은 E6 이다."""
    store, project = world["store"], world["project"]
    before = _item(_build(world), "E6")
    stranger = _add_stranger(world)
    registry.set_visibility(store, "clu-x", "org", owner_sub=STRANGER)
    store.execute(
        "INSERT INTO rr_character(id, project_id, owner_sub, facet, tag, statement, by_json, support_panels, status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("ch-x", stranger["project"], STRANGER, "intent", "char:intent:x", "남의 과제의 설계 의도", json.dumps([SEATS[0]]), 3,
         "confirmed", 1, 1))
    # 브리프의 merged 는 상위 5 라 남의 과제가 동점 순서로 빠질 수 있다 — 모두를 싣는 k 의 merged 로 E6 을 따로 조립해 그 과제가
    # merged 에 든 경우를 반드시 본다.
    similar = brief.similar_projects(store, project, K, owner_sub=OWNER)
    e6 = brief._item_e6(store, similar, brief._target_context(store, world["target"]))
    built = _build(world)

    assert [stranger["project"] in e["project_ids"] for e in similar["subject"]] == [True]
    assert stranger["project"] in {e["project_id"] for e in similar["merged"]}
    assert f"reg:{stranger['target']}#clu-x" in _item(built, "E5")["result"]
    assert e6["result"] == _item(built, "E6")["result"] == before["result"]
    assert before["result"].split("\n")[1:] == ["[유사 과제 성격 진술 없음 — 코퍼스 n_projects=6]"]


# ---------------------------------------------------------------- MCP 구성원(D46 — 다른 과제는 소유자와 부른 사람 둘 다 보는 것만)
def test_mcp_lists_only_projects_both_the_owner_and_the_calling_member_can_see(world, monkeypatch):
    """P 의 viewer 가 MCP 로 부르면 유사 과제 · 선례의 다른 과제는 주인과 그 사람이 둘 다 볼 수 있는 것만이다 — 주인만 보는 과제는
    목록에도, 수(corpus_n)에도, 계보의 걸음 수에도 드러나지 않는다(그 사람이 볼 수 있는 과제라도 숨긴 과제를 건너야 닿으면 싣지 않는다).
    같은 인자로 주인이 부르면 주인의 시야 그대로다."""
    store, project, mine = world["store"], world["project"], world["mine"]
    owner = factories.ident(OWNER)
    step1 = routes.create_project(routes.ProjectBody(code="P-NEXT", name="다음 리비전", classification="internal",
                                                     predecessor_project_id=project), ident=owner)["id"]
    step2 = routes.create_project(routes.ProjectBody(code="P-NEXT2", name="그다음 리비전", classification="internal",
                                                     predecessor_project_id=step1), ident=owner)["id"]
    for seen_by_member in (project, mine[0], step2):
        _members(seen_by_member, OWNER, MEMBER)
    _registry(store, _target(store, _snapshot_of(store, mine[1]), OWNER), OWNER, "clu-hidden", world["subject"])
    diff_id = factories.make_diff(store, _snapshot_of(store, mine[0]), _snapshot_of(store, project))["diff_id"]
    hidden = [*mine[1:], world["shared"], step1]

    factories.act_as_delegate(monkeypatch, MEMBER)
    similar = srv.risk_similar_projects(project_id=project, k=K)
    found = srv.risk_get_precedents(diff_id=diff_id)
    assert [pid for pid in hidden if pid in json.dumps([similar, found])] == []
    assert (similar["corpus_n"], similar["vector"], similar["lineage"]) == (2, [], [])
    assert [(e["project_ids"], e["n_registry"]) for e in similar["subject"]] == [([mine[0]], 1)]
    assert [c["cluster_key"] for c in found["clusters"]] == ["clu-mine"]

    factories.act_as_delegate(monkeypatch, OWNER)
    owners = srv.risk_similar_projects(project_id=project, k=K)
    assert owners["corpus_n"] == 6 and [(e["project_id"], e["hops"]) for e in owners["lineage"]] == [(step1, 1), (step2, 2)]
    assert sorted(c["cluster_key"] for c in srv.risk_get_precedents(diff_id=diff_id)["clusters"]) == ["clu-hidden", "clu-mine"]


# ---------------------------------------------------------------- AIDataHub(D46 — 과제 거름 없이는 찾지 않는다)
def test_aidatahub_recall_is_skipped_without_a_project_filter_and_carries_one_otherwise(world):
    """과제 거름을 밝히지 않은 AIDataHub 클라이언트를 넘기면(배선하면) 서술 경로와 좌석 기억 2차 경로는 찾지 않고 까닭을 남긴다 — 전체
    색인을 찾지 않는다. 지금의 실 클라이언트(AdhClient)도 거름을 밝히지 않는다. 거름을 밝힌 클라이언트의 찾기마다 타깃 소유자가 볼 수
    있는 과제 목록이 간다(남의 과제가 있는 원장이라 그 목록이 코퍼스 전체와 갈린다)."""
    store, project = world["store"], world["project"]
    _add_stranger(world)
    unfiltered = _Recorder(filtered=False, hits=[_hit("r-mine1", world["mine"][0])])
    similar = brief.similar_projects(store, project, K, adh=unfiltered)
    built = _build(world, unfiltered)

    assert unfiltered.calls == []
    assert similar["text"] == [] and similar["reason"]["text"].startswith("adh_unscoped")
    assert built["meta"]["external_search"] == "adh_unscoped" and "외부 검색 가용=false" in _item(built, "E0")["result"]
    assert _item(built, "E7")["result"].split("\n")[3] == "[mech-syn-2: 이전 발언 없음]"
    assert not getattr(AdhClient, "supports_project_filter", False)

    filtered = _Recorder(filtered=True, hits=[_hit("r-mine1", world["mine"][0])])
    brief.similar_projects(store, project, K, adh=filtered)
    built = _build(world, filtered)
    visible = sorted([project, *world["mine"], world["shared"]])
    assert sorted({name for name, _kwargs in filtered.calls}) == ["agent_search", "hybrid_search"]
    assert [kwargs.get("project_ids") for _name, kwargs in filtered.calls] == [visible] * len(filtered.calls)
    assert _item(built, "E7")["result"].split("\n")[3].startswith("narr:op-adh#pan-adh#F1 | mech-syn-2 | adh/")


# ---------------------------------------------------------------- 선례 패턴 후보(D47 — 패턴도 주인 ∩ 부른 사람)
def test_precedent_patterns_come_only_from_projects_both_the_owner_and_the_caller_can_see(world, monkeypatch):
    """선례의 pattern_candidates 는 주인의 패턴이나 조직 공개로 연 패턴이고, 조직 공개가 아니면 그 패턴을 이룬 과제(원자의 과제)가 모두
    주인과 부른 사람 둘 다 볼 수 있는 과제다 — 남의 비공개 패턴은 누구에게도, 주인만 보는 과제가 섞인 패턴은 그 과제를 못 보는 구성원에게
    드러나지 않는다. 조직 공개 패턴은 그대로다."""
    store, project, mine = world["store"], world["project"], world["mine"]
    for seen_by_member in (project, mine[0]):
        _members(seen_by_member, OWNER, MEMBER)
    hidden_target = _target(store, _snapshot_of(store, mine[1]), OWNER)
    stranger = _add_stranger(world)
    _finding(store, "f-a", world["mine_target"], mine[0], OWNER, "cl-a")          # 구성원도 보는 과제의 원자뿐
    _finding(store, "f-b1", world["mine_target"], mine[0], OWNER, "cl-b")
    _finding(store, "f-b2", hidden_target, mine[1], OWNER, "cl-b")                # 주인만 보는 과제의 원자가 섞였다
    _finding(store, "f-x", stranger["target"], stranger["project"], STRANGER, "cl-x")
    for pattern_id, owner, norm, visibility in (("P-A", OWNER, "cl-a", "private"), ("P-B", OWNER, "cl-b", "private"),
                                                ("P-O", STRANGER, "cl-o", "org"), ("P-X", STRANGER, "cl-x", "private")):
        _pattern(store, pattern_id, owner, norm, visibility)
    diff_id = factories.make_diff(store, _snapshot_of(store, mine[0]), _snapshot_of(store, project))["diff_id"]

    def patterns(email: str) -> list[str]:
        factories.act_as_delegate(monkeypatch, email)
        return [p["pattern_id"] for p in srv.risk_get_precedents(diff_id=diff_id)["pattern_candidates"]]

    assert patterns(MEMBER) == ["P-A", "P-O"]
    assert patterns(OWNER) == ["P-A", "P-B", "P-O"]


# ---------------------------------------------------------------- E8(D47 — 코퍼스 수는 보이는 과제의 타깃만)
def test_e8_counts_only_targets_of_projects_the_owner_can_see(world):
    """선례가 없는 diff 의 E8 은 '코퍼스 n_targets' 를 타깃 소유자가 볼 수 있는 과제의 타깃으로만 센다 — 남의 대상이 늘어도 같은 수다
    (E6 의 n_projects 와 같은 규칙)."""
    store, project, mine = world["store"], world["project"], world["mine"]
    diff_id = factories.make_diff(store, _snapshot_of(store, mine[0]), _snapshot_of(store, project))["diff_id"]
    target = factories.make_target(store, "diff", diff_id, agents=factories.agents(("mech",), len(SEATS)))

    def e8() -> str:
        built = brief.build_brief(store, target, seats=[{"key": key, "domain": "mech", "origin": "primary"} for key in SEATS])
        return _item(built, "E8")["result"]

    before = e8()
    _add_stranger(world)
    assert e8() == before
    assert before.split("\n")[1:] == ["[선례 없음 — 코퍼스 n_targets=4, 이 조합 첫 사례]"]    # P-1 · SHARED · P · 이 diff
