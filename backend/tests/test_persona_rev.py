# 좌석 페르소나 판 — 로스터 동결의 role_sha · persona_rev, 의견 행의 판 사본, nightly 스탬프, E7 [이전 정의] 접두(plan §5.2.2 · §5.6.1 · §7.7)
from __future__ import annotations

import hashlib

import pytest

from app import brief, narrative, nightly, planner, registry
from tests import factories
from tests.test_brief import SEATS, _item, seed_diff_target

ROLE_A = "기구 낙하 해석 전문가 — 하우징 리브와 계면 간극을 본다"
ROLE_B = "기구 낙하 해석 전문가 — 하우징 리브 · 계면 간극 · 체결부를 본다"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def no_field(monkeypatch):
    from app import field_source

    monkeypatch.setattr(field_source, "for_target", lambda *a, **k: None)


def _roster(store, target_key: str) -> dict[str, dict]:
    return {r["agent_key"]: dict(r) for r in store.query(
        "SELECT agent_key, role_sha, persona_rev FROM rr_roster WHERE target_key = ?", (target_key,))}


# ---------------------------------------------------------------- 로스터 동결
def test_persona_stamp_is_the_role_hash_and_its_short_form():
    """role_sha = 원본 role 글의 sha256[:12], persona_rev = 그 앞 7자. 글이 없거나 공백뿐이면 둘 다 모른다(None)."""
    assert planner.persona_stamp(ROLE_A) == (_sha(ROLE_A)[:12], _sha(ROLE_A)[:7])
    assert planner.persona_stamp(ROLE_A) != planner.persona_stamp(ROLE_B)
    assert planner.persona_stamp("") == planner.persona_stamp("  \n") == planner.persona_stamp(None) == (None, None)


def test_freezing_and_refreshing_the_roster_fill_role_sha_and_persona_rev(risk_store):
    """새 로스터 행에 두 칸이 선다 — 역할 글은 원천 행의 role(또는 description)이고, 없는 좌석은 NULL 이다(빈 글의 해시로 적지 않는다).
    덧붙이기(refresh)도 같은 칸을 채우고 기존 행은 그대로다."""
    risk_store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, external_sync_json,"
        " created_at, updated_at) VALUES ('snap:t1', ?, 'snap', 's1', 'p1', 'h', '{}', 1, 1)", (factories.OWNER,))
    planner.freeze_roster(risk_store, "snap:t1", factories.OWNER, [
        {"key": "mech-a", "domain": "mech", "relevance": 0.9, "role": ROLE_A},
        {"key": "sim-b", "domain": "sim", "relevance": 0.5, "description": ROLE_B},
        {"key": "xd-c", "domain": "xd", "relevance": 0.1},
    ])
    rows = _roster(risk_store, "snap:t1")
    assert (rows["mech-a"]["role_sha"], rows["mech-a"]["persona_rev"]) == (_sha(ROLE_A)[:12], _sha(ROLE_A)[:7])
    assert (rows["sim-b"]["role_sha"], rows["sim-b"]["persona_rev"]) == (_sha(ROLE_B)[:12], _sha(ROLE_B)[:7])
    assert (rows["xd-c"]["role_sha"], rows["xd-c"]["persona_rev"]) == (None, None)

    planner.refresh_roster(risk_store, "snap:t1", [
        {"key": "mech-a", "domain": "mech", "relevance": 0.9, "role": ROLE_B},          # 기존 행은 불변
        {"key": "rel-d", "domain": "rel", "relevance": 0.3, "role": ROLE_B},
    ])
    rows = _roster(risk_store, "snap:t1")
    assert rows["mech-a"]["persona_rev"] == _sha(ROLE_A)[:7]
    assert (rows["rel-d"]["role_sha"], rows["rel-d"]["persona_rev"]) == (_sha(ROLE_B)[:12], _sha(ROLE_B)[:7])


def test_the_nightly_stamp_carries_a_persona_rev(risk_store):
    """§7.7 버전 스탬프의 persona_rev 가 더는 늘 NULL 이 아니다 — 로스터가 판을 갖는다."""
    risk_store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, external_sync_json,"
        " created_at, updated_at) VALUES ('snap:t1', ?, 'snap', 's1', 'p1', 'h', '{}', 1, 1)", (factories.OWNER,))
    planner.freeze_roster(risk_store, "snap:t1", factories.OWNER, [
        {"key": "mech-a", "domain": "mech", "relevance": 0.9, "role": ROLE_A},
        {"key": "sim-b", "domain": "sim", "relevance": 0.5, "role": ROLE_B}])
    assert nightly.version_stamp(risk_store, target_key="snap:t1")["persona_rev"] == _sha(ROLE_A)[:7]


# ---------------------------------------------------------------- 의견 행의 판 사본
def test_seat_opinions_copy_the_roster_persona_rev(risk_store, no_field):
    """패널 의견 행의 persona_rev 는 그 좌석 로스터 행의 사본이다 — 로스터 밖 좌석(반대석)은 NULL 이다."""
    project_id = factories.make_project(risk_store)
    snap = factories.make_snapshot(risk_store, project_id, factories.fixture_adapter_results(), label="DV1")
    agents = [{**a, "role": f"{a['key']} 의 역할"} for a in factories.agents()]
    key = factories.make_target(risk_store, "snap", snap["snapshot_id"], agents=agents)
    panel = factories.plan_panel(risk_store, key, "A")
    seats = [s["key"] for s in panel["seats"]]
    turns = [{"persona": k, "round": 1, "say": f"{k} 발언", "stance": "conditional"}
             for k in seats + [registry.ADVERSARY_KEY]]
    narrative.persist_panel_result(risk_store, panel["id"], decision_text="", spec=None, turns=turns)

    revs = {r["agent_key"]: r["persona_rev"] for r in risk_store.query(
        "SELECT agent_key, persona_rev FROM rr_seat_opinions WHERE panel_id = ?", (panel["id"],))}
    roster = _roster(risk_store, key)
    assert {k: revs[k] for k in seats} == {k: roster[k]["persona_rev"] for k in seats}
    assert all(revs[k] == _sha(f"{k} 의 역할")[:7] for k in seats)
    assert revs[registry.ADVERSARY_KEY] is None


# ---------------------------------------------------------------- E7 [이전 정의]
def _rev(store, target_key: str, opinion_rev: str | None, roster_rev: str | None) -> None:
    store.execute("UPDATE rr_seat_opinions SET persona_rev = ? WHERE opinion_id = 'op0'", (opinion_rev,))
    store.execute(
        "INSERT OR REPLACE INTO rr_roster(target_key, agent_key, owner_sub, domain, relevance, rank_in_domain,"
        " ecad_dependent, role_sha, persona_rev, frozen_at) VALUES (?, 'mech-housing-structure', ?, 'mech', 0.9, 1, 0,"
        " NULL, ?, 1)", (target_key, "me@example.com", roster_rev))


def test_e7_prefixes_an_excerpt_spoken_under_a_previous_persona(risk_store):
    """회수한 좌석 의견의 persona_rev 가 그 좌석의 지금 로스터 판과 다르면 줄 앞에 `[이전 정의]` 가 붙고, 220자 안에서 그 길이만큼
    발췌가 준다. 판이 같으면 붙지 않는다."""
    target_key = seed_diff_target(risk_store)
    _rev(risk_store, target_key, "aaaaaaa", "bbbbbbb")
    line = _item(brief.build_brief(risk_store, target_key, strict_lint=True), "E7").split("\n")[1]
    assert line == "[이전 정의] narr:op0#pan0#F1 | mech-housing-structure | DV1/diff:d0 | «전작에서 같은 계면의 간극을 지적했다»", line

    risk_store.execute("UPDATE rr_seat_opinions SET excerpt_for_rag = ? WHERE opinion_id = 'op0'", ("간극 " * 200,))
    lines = _item(brief.build_brief(risk_store, target_key), "E7").split("\n")[1:]
    assert lines[0].startswith(brief.PRIOR_DEFINITION + "narr:op0#") and len(lines[0]) <= brief.E7_SEAT_LINE, lines[0]
    assert len(lines) == len(SEATS)

    _rev(risk_store, target_key, "bbbbbbb", "bbbbbbb")
    line = _item(brief.build_brief(risk_store, target_key), "E7").split("\n")[1]
    assert line.startswith("narr:op0#pan0#F1 | "), line


@pytest.mark.parametrize("opinion_rev, roster_rev", [(None, "bbbbbbb"), ("aaaaaaa", None), (None, None)])
def test_e7_does_not_claim_a_changed_persona_it_cannot_compare(risk_store, opinion_rev, roster_rev):
    """한쪽 판이라도 모르면(옛 의견 · 역할 글 없는 로스터) 접두를 붙이지 않는다 — 모름을 '바뀜' 으로 적지 않는다."""
    target_key = seed_diff_target(risk_store)
    _rev(risk_store, target_key, opinion_rev, roster_rev)
    line = _item(brief.build_brief(risk_store, target_key), "E7").split("\n")[1]
    assert line.startswith("narr:op0#pan0#F1 | "), line
