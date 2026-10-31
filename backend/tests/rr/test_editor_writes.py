# 편집자 쓰기 · 대응 결정 시험(사용자 결정 10-31) — 대응 결정은 두 과제의 주인 · 편집자만 하고 남의 원장 행을 뒤집지 못한다, 쓰기 경로마다 주인 · 편집자 · 보기 · 남
"""대응 결정(POST /sameas/decide 의 confirm · reject)은 pair_key 의 과제(intra 는 하나, pair 는 둘 다)의 주인 · 편집자만 한다 — 행은 그 과제
주인의 원장에 서고(키 전파도 그 주인으로 돈다) 결정한 사람은 decided_by 다. 이미 다른 사람의 행이 그 자리에 있으면 덮지 않고 거절한다(조용히
넘기지 않는다). 종전에는 upsert 에 주인 거름이 없어 그 네 값(scope · pair_key · 두 stable 키)을 아는 누구나 주인의 행을 뒤집었다(MB-11 — 구성원
읽기가 보기에게 그 값을 열었다).

쓰기 경로 표(MB-14 — '계획서대로 편집자도 쓴다')는 남 시험 표(tests/rr/test_review1_stranger.py 의 CASES — 라우터의 쓰기 경로 전부와 같음을
그 파일이 지킨다)를 셋으로 가른다 — 계획서가 편집자에게 연 쓰기(편집자는 주인과 같은 답 · 감사 행의 행위자는 편집자 · 행은 주인의 원장),
주인(· 관리자 · 작성자)만 남긴 쓰기(편집자 · 보기는 거절되고 원장이 그대로다), 제 행만 쓰는 쓰기(보기도 지난다). 보기는 어느 과제 쓰기도
지나지 못하고(403 role_insufficient) 남은 없는 것과 같은 404 다. MCP 쓰기 도구도 같은 셋이다.

  실행:  .venv/bin/python -m pytest tests/rr/test_editor_writes.py
"""
from __future__ import annotations

import json
import shutil
from typing import Any

import pytest

import app.mcp_server as srv
from app import identity, routes
from app.adapters import registry as adapters_registry
from app.common import now_epoch
from app.errors import AppError
from app.risk_store import RiskStore
from tests import factories
from tests.rr.test_member_reads import (EDITOR, MCP_WRITES, ONE_SIDE, OTHER, OWNER, VIEWER, VIEWER_WRITES_OWN,  # noqa: F401
                                        _forge, two_projects)
from tests.rr.test_review1_stranger import CAPS, CASES, MCP_CASES, P, PREPARE, _answer, _mcp, template  # noqa: F401
from tests.synth import review_rig as rig

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


# ---------------------------------------------------------------- 쓰기 경로 표 — 주인 · 편집자 · 보기 · 남(MB-14)
# 계획서가 편집자에게 연 쓰기 — plan §8.2.3 '쓰기는 require_role(editor)(폐기 · 이양 · 멤버십은 owner)' 과 행마다의 '(editor)', §0.6 의 편집자
# (스냅샷 · 타깃 · 잡 · status · 사람 finding). 편집자는 주인과 같은 답이고 보기는 403 role_insufficient 다.
EDITOR_WRITES: frozenset[tuple[str, str]] = frozenset({
    ("PATCH", P + "/projects/{project_id}"),
    ("POST", P + "/projects/{project_id}/sources"),
    ("POST", P + "/projects/{project_id}/snapshots"),
    ("POST", P + "/projects/{project_id}/dims"),
    ("POST", P + "/projects/{project_id}/requirements"),
    ("PUT", P + "/requirements/{requirement_id}"),
    ("PUT", P + "/projects/{project_id}/iface-ledger"),
    ("POST", P + "/snapshots/{snapshot_id}/gates/{gate}/ack"),
    ("DELETE", P + "/snapshots/{snapshot_id}/gates/{gate}/ack"),
    ("POST", P + "/sameas/decide"),
    ("POST", P + "/diffs"),
    ("POST", P + "/targets"),
    ("POST", P + "/targets/{target_key}/refresh_roster"),
    ("POST", P + "/targets/{target_key}/units"),
    ("POST", P + "/targets/{target_key}/flow"),
    ("POST", P + "/targets/{target_key}/jobs"),
    ("POST", P + "/jobs/{job_id}/{action}"),
    ("PUT", P + "/targets/{target_key}/coverage/{agent_key}"),
    ("POST", P + "/targets/{target_key}/undefer"),
    ("POST", P + "/targets/{target_key}/cells/retry"),
    ("POST", P + "/targets/{target_key}/cells/skip"),
    ("PUT", P + "/issues/{issue_id}"),
    ("POST", P + "/targets/{target_key}/report"),
    ("PUT", P + "/targets/{target_key}/verdict"),
    ("PUT", P + "/registry/{cluster_key:path}/status"),
    ("PUT", P + "/registry/{cluster_key:path}/merge"),
    ("DELETE", P + "/registry/{cluster_key:path}/merge"),
    ("POST", P + "/panels/{panel_id}/complete"),
    ("POST", P + "/panels/{panel_id}/repersist"),
    ("POST", P + "/targets/{target_key}/findings"),
    ("POST", P + "/findings/{finding_id}/labels"),
})
# 계획서가 주인(· 관리자 · 작성자)에게 남긴 쓰기 — 편집자 · 보기의 상태와 까닭. 404 는 그 경로가 부른 사람의 행만 고르는 것이다(주인의 행이
# 없는 것과 같다 — 화면은 404 를 '소유자 불일치' 로 보인다, plan §8.2.4).
OWNER_ONLY: dict[tuple[str, str], tuple[int, str]] = {
    ("PUT", P + "/projects/{project_id}/members"): (403, "멤버십은 owner(plan §8.2.3)"),
    ("POST", P + "/projects/{project_id}/transfer"): (403, "이양은 owner 또는 관리자(plan §8.2.3)"),
    ("POST", P + "/projects/{project_id}/purge"): (403, "폐기는 owner 또는 관리자(plan §8.2.3)"),
    ("PUT", P + "/projects/{project_id}/ecad-board"): (
        404, "ECAD 보드 붙이기는 과제 주인만 — 그 사람 토큰으로 ODB 허브를 부른다(포털 ecad-1031 요청 · 사용자 결정 10-31)"),
    ("DELETE", P + "/projects/{project_id}/ecad-board"): (404, "ECAD 보드 떼기도 붙이기와 같은 문"),
    ("POST", P + "/targets/{target_key}/closure/acks/{item}"): (403, "완결 잔여 확인은 과제 소유자와 관리자(재설계 M3 — 편집자 403)"),
    ("DELETE", P + "/targets/{target_key}/closure/acks/{item}"): (403, "확인 취소도 확인과 같은 문"),
    ("PUT", P + "/registry/{cluster_key:path}/visibility"): (404, "등록부 조직 공개 토글은 소유자 전용(P6-8 — 공개 범위는 owner 의 몫)"),
    ("POST", P + "/targets/{target_key}/resync"): (403, "외부 동기 되돌리기는 소유자 전용(plan §8.2.3)"),
    ("PUT", P + "/curation/{queue_id}"): (404, "큐레이션 결정은 과제 owner 또는 관리자(plan §8.2.3)"),
    ("PUT", P + "/findings/{finding_id}"): (
        403, "사람 finding 고치기는 작성자 본인 또는 과제 owner(plan §8.2.3) — 이 표의 finding 은 주인이 썼다"),
    ("DELETE", P + "/findings/{finding_id}"): (403, "지우기도 고치기와 같은 문(작성자 본인 또는 과제 owner)"),
}
# 표의 부름이 편집자 길을 다 보이지 못하는 칸 — 주인 · 편집자에게 같은 부름이다. 등록부 셋은 대상을 준다(대상 없이 부르면 부른 사람 자신의
# 행이라 고를 주인이 없다 — 화면은 늘 대상을 싣는다). 게이트는 이 스냅샷에서 실제로 진 G3 이고, 치수 · 판정 · 대상 · 계면 원장 · 잡 멈춤은
# 받는 값으로 성공 길을 본다(남 시험 표의 부름은 빈 목록 · 어휘 밖 값 · 끝난 잡이라 사람 칸을 쓰지 않는다).
EDITOR_CALLS: dict[tuple[str, str], Any] = {
    ("POST", P + "/snapshots/{snapshot_id}/gates/{gate}/ack"): lambda i, who: routes.post_gate_ack(
        i["target_snapshot"], "G3", routes.GateAckBody(reason="확인했다"), ident=who),
    ("DELETE", P + "/snapshots/{snapshot_id}/gates/{gate}/ack"): lambda i, who: routes.delete_gate_ack(
        i["target_snapshot"], "G3", ident=who),
    ("POST", P + "/projects/{project_id}/dims"): lambda i, who: routes.add_dim(
        i["project"], routes.DimBody(name="gap_x", kind="gap", extractor="const: 1.5"), ident=who),
    ("POST", P + "/targets"): lambda i, who: routes.create_target(routes.TargetBody(
        kind="snap", ref_id=i["target_snapshot"], consent=True, agents=[dict(r) for r in rig.ROSTER]), ident=who),
    ("PUT", P + "/targets/{target_key}/verdict"): lambda i, who: routes.put_verdict(
        i["target"], routes.VerdictBody(verdict="go", note="좋다"), ident=who),
    ("PUT", P + "/registry/{cluster_key:path}/status"): lambda i, who: routes.put_registry_status(
        i["cluster"], routes.RegistryStatusBody(status="mitigated", note="막았다", target_key=i["target"]), ident=who),
    ("PUT", P + "/registry/{cluster_key:path}/merge"): lambda i, who: routes.put_registry_merge(
        i["cluster"], routes.RegistryMergeBody(into=i["cluster2"], reason="cluster_merge", target_key=i["target"]), ident=who),
    ("DELETE", P + "/registry/{cluster_key:path}/merge"): lambda i, who: routes.delete_registry_merge(
        i["cluster"], target_key=i["target"], ident=who),
    ("PUT", P + "/projects/{project_id}/iface-ledger"): lambda i, who: routes.put_iface_ledger(
        i["project"], [routes.LedgerItem(pair_key="e:pair-1", status="confirmed", note="확정")], ident=who),
    ("POST", P + "/jobs/{job_id}/{action}"): lambda i, who: routes.job_action(i["live_job"], "pause", ident=who),
}
# 그 칸이 뜻이 있으려면 주인이 먼저 해 둔 것(걷을 ack · 멈출 잡 — 남 시험 표의 PREPARE 에 더한다).
EDITOR_PREPARE: dict[tuple[str, str], Any] = {
    **PREPARE,
    ("DELETE", P + "/snapshots/{snapshot_id}/gates/{gate}/ack"): lambda i, store: routes.post_gate_ack(
        i["target_snapshot"], "G3", routes.GateAckBody(reason="확인했다"), ident=factories.ident(OWNER)),
    # 원장의 잡은 다 끝나 멈출 것이 없다 — 주인이 검토 잡 하나를 세워 둔다(멈춤이 state_by · 감사 행을 쓴다).
    ("POST", P + "/jobs/{job_id}/{action}"): lambda i, store: i.update(live_job=routes.create_job(
        i["target"], routes.JobBody(mode="reviews"), ident=factories.ident(OWNER))["job_id"]),
}


@pytest.fixture
def copies(request, tmp_path, monkeypatch):
    """남 시험 표의 원장 사본을 부를 때마다 하나(주인이 편집자 · 보기를 들였다) — 경로 · 사람마다 새 사본이라 앞 사람의 쓰기가 다음 답을
    바꾸지 않는다."""
    root, ids = request.getfixturevalue("template")
    opened: list[RiskStore] = []

    def make(name: str) -> tuple[RiskStore, dict]:
        data = tmp_path / name
        shutil.copytree(root, data)
        store = RiskStore(data / "risk_review.db")
        store.open()
        store.migrate()
        opened.append(store)
        rig.configure(monkeypatch, store, data, **CAPS)
        routes.put_members(ids["project"], routes.MembersBody(members=[routes.MemberItem(email=EDITOR, role="editor"),
                                                                      routes.MemberItem(email=VIEWER, role="viewer")]),
                           ident=factories.ident(OWNER))
        return store, dict(ids)                 # 준비(EDITOR_PREPARE)가 id 를 더해도 모듈 원장의 id 표에 새지 않는다

    yield make
    for store in opened:
        store.close()


def _tables(store: RiskStore) -> list[str]:
    return [r["name"] for r in store.query("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                                           " ORDER BY name")]


# 원장에서 빼는 표 — 신원 해석의 계측(게이트웨이 위임 단언을 해석할 때마다 rr_metrics 'gateway_sso' 를 센다)이다.
NOT_LEDGER = ("rr_metrics",)
# 사람 칸 — 그 행위를 한 사람을 적는 칸(…_by · actor · author_sub). 앞 결정자(prev_…)와 사람이 아닌 …_by(대체한 열쇠 · 대조 방식 · 막은
# 코드)는 뺀다.
NOT_PEOPLE = ("superseded_by", "matched_by", "blocked_by")


def _is_person(column: str) -> bool:
    return column in ("actor", "author_sub") or (column.endswith("_by") and column not in NOT_PEOPLE
                                                 and not column.startswith("prev_"))


def _ledger(store: RiskStore) -> dict[str, dict[Any, dict]]:
    """원장 전부 — 표마다 열쇠(주 키, 없으면 rowid) → 행."""
    out: dict[str, dict[Any, dict]] = {}
    for table in _tables(store):
        if table in NOT_LEDGER:
            continue
        pk = [c["name"] for c in sorted(store.query(f"PRAGMA table_info({table})"), key=lambda c: c["pk"]) if c["pk"]]
        rows = [dict(r) for r in store.query(f"SELECT {'' if pk else 'rowid AS _rowid_, '}* FROM {table}")]
        out[table] = {tuple(r[k] for k in pk) if pk else r.pop("_rowid_"): r for r in rows}
    return out


def _changed(before: dict, after: dict) -> list[str]:
    """바뀐 표 이름 — 거절된 쓰기는 원장을 하나도 바꾸지 않는다."""
    return [table for table in after if before.get(table) != after[table]]


def _people_written(before: dict, after: dict) -> set[tuple[str, str, str]]:
    """이 부름이 쓴 사람 칸 (표, 칸, 값) — 새 행의 사람 칸과 고친 행에서 값이 바뀐 사람 칸."""
    out = set()
    for table, rows in after.items():
        for key, row in rows.items():
            prev = before.get(table, {}).get(key)
            out |= {(table, col, val) for col, val in row.items()
                    if _is_person(col) and isinstance(val, str) and (prev is None or prev.get(col) != val)}
    return out


def _owned_by(ledger: dict, email: str) -> dict[str, int]:
    """owner_sub 칸이 그 사람인 행 수(표마다) — 편집자의 쓰기는 주인의 원장에 서므로 편집자 몫으로는 아무 행도 서지 않는다. 감사 표는 빼고
    본다 — 라우트의 감사 행은 owner_sub 와 actor 가 같은 사람(행위자)이다(`routes._audit` — 기존 편집자 길인 잡 · 사람 finding · 쟁점과 같다,
    행위자는 사람 칸으로 본다). 맨 클러스터 열쇠의 별칭 철회만 원장 주인으로 적는다(아래 시험)."""
    out = {}
    for table, rows in ledger.items():
        n = sum(1 for row in rows.values() if row.get("owner_sub") == email)
        if table != "rr_audit" and n:
            out[table] = n
    return out


def _run(copies, case: tuple[str, str], who: str, name: str) -> tuple[tuple, dict, dict]:
    """한 사본에서 한 사람이 한 칸을 부른다 — (답, 앞 원장, 뒤 원장)."""
    store, ids = copies(name)
    if case in EDITOR_PREPARE:
        EDITOR_PREPARE[case](ids, store)
    call = EDITOR_CALLS.get(case) or CASES[case][0]
    before = _ledger(store)
    got = _answer(lambda: call(ids, factories.ident(who)))
    return got, before, _ledger(store)


def _same_people(owner_run: tuple[dict, dict], editor_run: tuple[dict, dict]) -> None:
    """주인의 부름이 주인 이름을 적는 사람 칸(감사 행위자 · 정한 · 단 · 확정한 · 만든 사람 …)은 편집자의 부름에서 편집자 이름이고, 편집자의
    부름은 어느 사람 칸에도 주인 이름을 적지 않는다."""
    by_owner = {(t, c) for t, c, v in _people_written(*owner_run) if v == OWNER}
    by_editor = _people_written(*editor_run)
    assert {(t, c) for t, c, v in by_editor if v == EDITOR} == by_owner, (by_owner, by_editor)
    assert [x for x in by_editor if x[2] == OWNER] == [], by_editor


def _case_id(case: tuple[str, str]) -> str:
    return f"{case[0]} {case[1][len(P):]}"


def test_the_write_table_splits_every_mutating_route_three_ways():
    """쓰기 경로 표 == 남 시험 표의 쓰기 칸 전부(라우터의 쓰기 경로 − 면제) — 편집자에게 연 것 · 주인만 · 제 행만, 겹치지 않는다. 새 쓰기 경로는
    셋 가운데 하나로 들어와야 한다."""
    groups = (set(EDITOR_WRITES), set(OWNER_ONLY), set(VIEWER_WRITES_OWN))
    assert sum(len(g) for g in groups) == len(set().union(*groups)) and set().union(*groups) == set(CASES)
    assert set(EDITOR_CALLS) <= set(EDITOR_WRITES) and all(reason for _status, reason in OWNER_ONLY.values())


@pytest.mark.parametrize("case", sorted(EDITOR_WRITES), ids=_case_id)
def test_an_editor_writes_what_the_plan_gives_editors_and_a_viewer_does_not(copies, case):
    """편집자는 주인과 같은 답(성공이든 같은 업무 거절이든 — 쓰기 문을 지났다)이고, 주인의 부름이 사람 칸(감사 행의 행위자 · decided_by ·
    ack_by · verdict_by · built_by …)에 주인 이름을 적는 자리에 편집자 이름을 적는다. 쓴 행은 주인의 원장이다(편집자 몫 owner_sub 행이 서지
    않는다). 보기는 403 role_insufficient 이고 원장이 그대로, 남은 없는 것과 같은 404 다(그 답이 없는 id 의 답과 같은지는 남 시험 표가 본다).
    종전에는 편집자도 대부분 404(주인 행만 고르는 길)였다."""
    owner, *owner_run = _run(copies, case, OWNER, "owner")
    editor, *editor_run = _run(copies, case, EDITOR, "editor")
    assert (editor[0], editor[1]) == (owner[0], owner[1]), (owner[:3], editor[:3])
    _same_people(owner_run, editor_run)
    assert _owned_by(editor_run[1], EDITOR) == {}
    viewer, before, after = _run(copies, case, VIEWER, "viewer")
    assert (viewer[0], viewer[1]) == ("role_insufficient", 403), viewer[:3]
    assert _changed(before, after) == []
    assert _run(copies, case, OTHER, "stranger")[0][1] == 404


@pytest.mark.parametrize("case", sorted(OWNER_ONLY), ids=_case_id)
def test_what_the_plan_keeps_for_the_owner_stays_the_owners(copies, case):
    """주인(· 관리자 · 작성자)에게 남긴 쓰기는 편집자 · 보기를 표의 상태로 거절하고 원장을 바꾸지 않는다. 남은 없는 것과 같은 404 이고, 주인은 그
    문에 막히지 않는다(403 · 404 가 아니다)."""
    status, _reason = OWNER_ONLY[case]
    for who in (EDITOR, VIEWER):
        got, before, after = _run(copies, case, who, who.split("@")[0])
        assert got[1] == status, (who, got[:3])
        assert _changed(before, after) == [], who
    assert _run(copies, case, OTHER, "stranger")[0][1] == 404
    owner = _run(copies, case, OWNER, "owner")[0]
    assert owner[1] not in (403, 404), owner[:3]


@pytest.mark.parametrize("case", sorted(VIEWER_WRITES_OWN), ids=_case_id)
def test_writes_into_ones_own_project_pass_for_every_member(copies, case):
    """제 행만 쓰는 쓰기(제 과제 만들기 · 제 과제로 승계)는 편집자 · 보기도 지난다 — 원본 과제는 읽기만 한다. 남은 없는 원본과 같은 404 다."""
    for who in (OWNER, EDITOR, VIEWER):
        got = _run(copies, case, who, who.split("@")[0])[0]
        assert got[1] == 200, (who, got[:3])
    assert _run(copies, case, OTHER, "stranger")[0][1] == 404


def test_rows_someone_else_hung_on_the_project_are_not_written_through_membership(copies):
    """편집자 문은 과제 주인의 행만 연다 — 남이 주인의 과제에 매단 스냅샷 · 대상(고침 전의 들여오기 — RD-10)에는 편집자도 주인도 쓰지 못하고
    없는 것과 같은 404 다(읽기 문과 같은 규칙 — MB-2). 그 행을 들여온 사람은 제 행을 오늘처럼 쓴다."""
    store, ids = copies("forged")
    forged_snapshot, forged_target = _forge(store, ids)
    for who in (OWNER, EDITOR):
        verdict = _answer(lambda who=who: routes.put_verdict(forged_target, routes.VerdictBody(verdict="go"),
                                                             ident=factories.ident(who)))
        ack = _answer(lambda who=who: routes.post_gate_ack(forged_snapshot, "G3", routes.GateAckBody(reason="확인했다"),
                                                           ident=factories.ident(who)))
        assert (verdict[1], ack[1]) == (404, 404), (who, verdict[:3], ack[:3])
    assert _answer(lambda: routes.put_verdict(forged_target, routes.VerdictBody(verdict="go"),
                                              ident=factories.ident(OTHER)))[1] == 200


def test_an_editors_capture_reads_with_the_editors_own_credential(copies, monkeypatch):
    """편집자가 시작한 동결은 그 사람의 등록 PAT 로 읽는다(캡처 자격은 시작한 사람의 것 — 위임 다리 · ECAD 도 그 사람의 PAT) — 주인의 PAT 를
    빌리지 않는다. 동결 잡 행은 주인의 원장이다."""
    store, ids = copies("capture")
    for email in (OWNER, EDITOR):
        store.upsert_credential(email, identity.encrypt_pat(f"pat-{email}").decode("ascii"), "sub", email, "[]",
                                now_epoch() + 30 * 86400)
    seen: list[str | None] = []

    def channels(settings, secrets=None, *, portal_pat=None, **_):
        seen.append(portal_pat)
        raise AppError("source_unreachable", "시험 — 채널을 열지 않는다.", 409)

    monkeypatch.setattr(adapters_registry, "clients_from_settings", channels)
    got = _answer(lambda: routes.create_snapshot(ids["project"], routes.SnapshotBody(kinds=["mcad"]),
                                                 ident=factories.ident(EDITOR)))
    assert got[0] == "source_unreachable" and seen == [f"pat-{EDITOR}"], (got[:3], seen)
    job = store.query_one("SELECT owner_sub FROM rr_snapshot_jobs ORDER BY created_at DESC, rowid DESC LIMIT 1")
    assert job["owner_sub"] == OWNER


def test_an_editor_edits_and_deletes_only_the_findings_they_wrote(copies):
    """사람 finding 은 작성자 본인 또는 과제 owner 가 고치고 지운다(plan §8.2.3) — 편집자가 쓴 finding 은 그 편집자와 주인이 고치고, 다른 편집자는
    403 이다. 작성자가 보기로 내려가면 제 finding 도 못 고친다(보기는 쓰지 않는다)."""
    store, ids = copies("findings")
    second = "second-editor@example.com"
    routes.put_members(ids["project"], routes.MembersBody(members=[routes.MemberItem(email=second, role="editor")]),
                       ident=factories.ident(OWNER))
    body = routes.HumanFindingBody(mechanism="interface", claim="편집자가 본 간극", cites=[{"ref": "c:5b0e11aa22bb", "quote": "배치"}])
    made = routes.create_human_finding(ids["target"], body, ident=factories.ident(EDITOR))
    row = store.query_one("SELECT owner_sub, author_sub FROM rr_findings WHERE finding_id = ?", (made["finding_id"],))
    assert (row["owner_sub"], row["author_sub"]) == (OWNER, EDITOR)
    edit = routes.HumanFindingBody(mechanism="interface", claim="고쳐 적는다", cites=[{"ref": "c:5b0e11aa22bb", "quote": "배치"}])
    other = _answer(lambda: routes.update_human_finding(made["finding_id"], edit, ident=factories.ident(second)))
    assert (other[0], other[1]) == ("role_insufficient", 403), other[:3]
    assert _answer(lambda: routes.update_human_finding(made["finding_id"], edit, ident=factories.ident(EDITOR)))[1] == 200
    assert _answer(lambda: routes.update_human_finding(made["finding_id"], edit, ident=factories.ident(OWNER)))[1] == 200
    routes.put_members(ids["project"], routes.MembersBody(members=[routes.MemberItem(email=EDITOR, role="viewer")]),
                       ident=factories.ident(OWNER))
    demoted = _answer(lambda: routes.delete_human_finding(made["finding_id"], ident=factories.ident(EDITOR)))
    assert (demoted[0], demoted[1]) == ("role_insufficient", 403), demoted[:3]
    assert _answer(lambda: routes.delete_human_finding(made["finding_id"], ident=factories.ident(OWNER)))[1] == 200


def test_an_admin_writes_like_an_editor_on_any_project(copies):
    """관리자(risk_admin_roles)는 전 과제에서 편집자다(plan §0.6 — 기존 편집자 길과 같은 우회) — 구성원이 아니어도 판정을 확정하고, 행은 주인의
    것 · 확정한 사람은 관리자다."""
    store, ids = copies("admin")
    admin = identity.Identity(email="admin@example.com", display_name="관리자", role="admin", organization="qa",
                              anonymous=False, source="bearer")
    routes.put_verdict(ids["target"], routes.VerdictBody(verdict="go"), ident=admin)
    row = store.query_one("SELECT owner_sub, verdict_by FROM rr_targets WHERE target_key = ?", (ids["target"],))
    assert (row["owner_sub"], row["verdict_by"]) == (OWNER, "admin@example.com")


def test_a_diff_over_two_owners_snapshots_is_not_made(world):
    """비교 행은 한 주인의 것이라 두 스냅샷의 주인이 다르면(편집자가 두 사람의 과제를 다 편집한다) 422 pair_owners_differ 다 — 어느 한 주인의
    원장에 남의 스냅샷을 잇지 않는다."""
    w = world
    elsewhere = factories.make_project(w["store"], owner=OTHER, code="OTHER-DIFF")
    routes.put_members(elsewhere, routes.MembersBody(members=[routes.MemberItem(email=EDITOR, role="editor")]),
                       ident=factories.ident(OTHER))
    theirs = factories.make_snapshot(w["store"], elsewhere, factories.fixture_adapter_results(), label="X",
                                     owner=OTHER)["snapshot_id"]
    got = _answer(lambda: routes.create_diff(routes.DiffBody(base_snapshot_id=w["base"], target_snapshot_id=theirs),
                                             ident=factories.ident(EDITOR)))
    assert (got[0], got[1]) == ("pair_owners_differ", 422), got[:3]
    assert w["store"].query_one("SELECT COUNT(*) AS n FROM rr_diffs")["n"] == 0


def test_an_editors_alias_revoke_shows_in_the_owners_target_audit(copies):
    """별칭 철회의 감사 자리는 맨 클러스터 열쇠라 대상 감사가 '그 대상 소유자의 행위' 로 고른다(BL-8). 편집자가 대상을 주고 주인의 별칭을 걷으면
    그 행은 주인의 원장 행위로 서고(owner_sub 주인 · actor 편집자) 주인 · 구성원의 대상 감사에 보인다 — 행위자 이름으로 적으면 어느 대상
    감사에도 실리지 않았다."""
    store, ids = copies("revoke")
    routes.put_registry_merge(ids["cluster"], routes.RegistryMergeBody(into=ids["cluster2"], reason="cluster_merge"),
                              ident=factories.ident(OWNER))
    routes.delete_registry_merge(ids["cluster"], target_key=ids["target"], ident=factories.ident(EDITOR))
    row = store.query_one("SELECT owner_sub, actor, subject_id FROM rr_audit WHERE action = 'registry.merge.revoke'")
    assert (row["owner_sub"], row["actor"], row["subject_id"]) == (OWNER, EDITOR, ids["cluster"])
    for who in (OWNER, EDITOR, VIEWER):
        rows = routes.get_target_audit(ids["target"], action="registry.merge.revoke", ident=factories.ident(who))["entries"]
        assert [r["actor"] for r in rows] == [EDITOR], (who, rows)


# ---------------------------------------------------------------- MCP 쓰기 도구 — 웹과 같은 셋
MCP_EDITOR_WRITES: frozenset[str] = frozenset({
    "risk_submit_panel_result", "risk_add_finding", "risk_add_source", "risk_capture_snapshot", "risk_ack_gate",
    "risk_decide_sameas", "risk_create_diff", "risk_open_target", "risk_start_job", "risk_job_action", "risk_repersist_panel",
})
MCP_OWNER_ONLY_WRITES: dict[str, str] = {"risk_set_ecad_board": "ECAD 보드 붙이기 · 떼기는 과제 주인만(웹 라우트를 그대로 부른다)"}
MCP_OWN_WRITES: dict[str, str] = {"risk_create_project": "제 과제를 만든다(앞 과제가 구성원 과제라 계보가 선다)"}
# 표의 부름이 쓰기 문까지 가지 못하는 칸 — 빈 결정 목록은 문 앞에서 E100 이라 결정 하나를 싣고, 게이트는 실제로 진 G3 이다.
MCP_CALLS: dict[str, Any] = {
    "risk_decide_sameas": lambda i: srv.risk_decide_sameas(base_snapshot_id=i["base_snapshot"], target_snapshot_id=i["target_snapshot"],
                                                           decisions=[{"a_stable": "s:a", "b_stable": "s:b", "decision": "confirm"}]),
    "risk_ack_gate": lambda i: srv.risk_ack_gate(snapshot_id=i["target_snapshot"], gate="G3", reason="확인했다"),
}


def _run_mcp(copies, monkeypatch, name: str, who: str, label: str) -> tuple[tuple, dict, dict]:
    store, ids = copies(label)
    call = MCP_CALLS.get(name) or MCP_CASES[name][0]
    before = _ledger(store)
    factories.act_as_delegate(monkeypatch, who)
    got = _mcp(lambda: call(ids))
    return got, before, _ledger(store)


def test_the_mcp_write_tools_split_the_same_three_ways():
    """MCP 쓰기 도구 == 편집자에게 연 것 · 주인만 · 제 행만(겹치지 않는다) — 구성원 읽기 표(test_member_reads 의 MCP_WRITES)와 같은 목록이다."""
    groups = (set(MCP_EDITOR_WRITES), set(MCP_OWNER_ONLY_WRITES), set(MCP_OWN_WRITES))
    assert sum(len(g) for g in groups) == len(set().union(*groups)) and set().union(*groups) == set(MCP_WRITES)


@pytest.mark.parametrize("name", sorted(MCP_WRITES))
def test_every_mcp_write_tool_answers_members_like_its_web_route(copies, monkeypatch, name):
    """MCP 쓰기 도구도 웹 라우트와 같은 문이다 — 편집자에게 연 도구는 편집자가 주인과 같은 답(사람 칸은 편집자 이름 · 편집자 몫 행 없음)이고
    보기는 role_insufficient · 원장 그대로다. 주인만의 도구는 편집자 · 보기가 거절되고, 제 행만 쓰는 도구는 둘 다 지난다. 남은 not_visible ·
    E404 다."""
    owner, *owner_run = _run_mcp(copies, monkeypatch, name, OWNER, "owner")
    assert owner[0] not in ("not_visible", "E404", "role_insufficient"), owner[:3]
    editor, *editor_run = _run_mcp(copies, monkeypatch, name, EDITOR, "editor")
    viewer, before, after = _run_mcp(copies, monkeypatch, name, VIEWER, "viewer")
    if name in MCP_OWN_WRITES:
        assert (editor[0], viewer[0]) == ("ok", "ok"), (editor[:3], viewer[:3])
    elif name in MCP_OWNER_ONLY_WRITES:
        assert editor[0] in ("E404", "not_visible", "role_insufficient") and _changed(*editor_run) == [], editor[:3]
        assert viewer[0] in ("E404", "not_visible", "role_insufficient") and _changed(before, after) == [], viewer[:3]
    else:
        assert editor[0] == owner[0], (owner[:3], editor[:3])
        _same_people(owner_run, editor_run)
        assert _owned_by(editor_run[1], EDITOR) == {}
        assert viewer[0] == "role_insufficient" and _changed(before, after) == [], viewer[:3]
    stranger = _run_mcp(copies, monkeypatch, name, OTHER, "stranger")[0]
    assert stranger[0] in ("not_visible", "E404"), stranger[:3]


def test_an_editor_takes_the_brief_by_token_and_a_viewer_does_not(risk_store, monkeypatch):
    """MCP risk_get_brief(브리프 토큰의 패널을 동결하고 품질을 쓴다)는 결과 제출과 같은 문이다(RV-1) — 그 대상 과제의 편집자는 주인처럼 그
    패널을 받고, 보기는 role_insufficient 이고 패널이 그대로다(동결 · 품질 쓰기 없음). 남은 E404 다. 종전에는 패널 주인만 받았다."""
    store = risk_store
    monkeypatch.setattr(routes, "get_store", lambda: store)
    monkeypatch.setattr(routes.field_source, "for_target", lambda *a, **k: None)
    synth = factories.make_diff_target(store, 40, owner=OWNER)
    routes.put_members(synth.project_id, routes.MembersBody(members=[routes.MemberItem(email=EDITOR, role="editor"),
                                                                    routes.MemberItem(email=VIEWER, role="viewer")]),
                       ident=factories.ident(OWNER))
    issued = routes.brief_payload(synth.target_key, "B", owner_sub=OWNER, issue_token=True)["panels"][0]
    panel_id, token = issued["panel_id"], issued["brief_token"]

    def state() -> dict:
        return dict(store.query_one("SELECT status, quality_json, brief_gz, brief_hash FROM rr_panels WHERE id = ?", (panel_id,)))

    before = state()
    for who, code in ((VIEWER, "role_insufficient"), (OTHER, "E404")):
        factories.act_as_delegate(monkeypatch, who)
        assert srv.risk_get_brief(synth.target_key, token).get("error") == code, who
        assert state() == before, who
    factories.act_as_delegate(monkeypatch, EDITOR)
    out = srv.risk_get_brief(synth.target_key, token)
    assert [p["panel_id"] for p in out["panels"]] == [panel_id], out
    assert state()["brief_gz"] is not None
