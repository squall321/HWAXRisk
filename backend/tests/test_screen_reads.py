# 화면 읽기 칸 시험(화면 세션 10-31 청할 것) — 스냅샷 상태의 지금 ack · 키 대장 읽기 · 대응표 pair_key · 진행판 패널 잡 signals
"""화면 세션(가지 wt1031/riskfe — context-notes FE-14 · FE-30 끝)은 서버가 주지 않는 칸을 '모름' 으로 보이거나 화면이 지어 썼다. 이 파일은
그 칸들이 서버 답에 서는지를 생산자 경로(라우트 · freeze_snapshot · 러너)로 만든 원장 위에서 본다. 남(구성원이 아닌 사람)은 있는 것과
없는 것이 같은 404 다(남 숨김) — 경로 전체의 남 시험은 tests/rr/test_review1_stranger.py 의 표가 맡는다.

  실행:  .venv/bin/python -m pytest tests/test_screen_reads.py
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from app import config, routes, runner, sameas
from app.common import now_epoch
from app.errors import AppError
from tests import factories
from tests.test_runner_panel import OWNER as PANEL_OWNER
from tests.test_runner_panel import FakePanelEngine, fake_narrative, fake_registry, give_credential, seeded
from tests.test_sameas import mcad

OWNER = factories.OWNER
EDITOR = "editor@example.com"
VIEWER = "viewer@example.com"
STRANGER = "stranger@example.com"
MCAD_ONLY = "adapter_mcad_basic.json"


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


def _node_ckeys(store, snapshot_id: str) -> list[str]:
    """그 스냅샷 노드가 단 정규 키(겹침 없이, 정렬)."""
    return [r["ckey"] for r in store.query(
        "SELECT DISTINCT ckey FROM rr_ir_nodes WHERE snapshot_id = ? AND ckey IS NOT NULL ORDER BY ckey", (snapshot_id,))]


# ---------------------------------------------------------------- 3. GET /snapshots/{id}?part=state
def test_the_snapshot_state_carries_the_live_gate_acks_and_the_gates_hash(wired):
    """상태는 동결 때의 원문이라 ack 를 다시 싣지 않았다 — 이제 게이트마다 지금 살아 있는(취소되지 않은) ack 의 누가 · 언제 · 사유와
    판정 지문(gates_hash — ack 를 붙여도 바뀌지 않는다)을 싣는다. 취소하면 내려간다."""
    store = wired
    owner = factories.ident(OWNER)
    project_id = factories.make_project(store)
    sid = factories.make_snapshot(store, project_id, [factories.adapter_fixture(MCAD_ONLY)], label="ack")["snapshot_id"]

    before = routes.get_snapshot(sid, part="state", ident=owner)
    assert before["gates"]["G3"]["pass"] is False                     # 확인 안 된 간섭 — ack 할 수 있는 fail
    assert all(g["ack_by"] is None for g in before["gates"].values())
    acked = routes.post_gate_ack(sid, "G3", routes.GateAckBody(reason="계면 확인 뒤 진행"), ident=owner)

    state = routes.get_snapshot(sid, part="state", ident=owner)
    g3 = state["gates"]["G3"]
    assert (g3["ack_by"], g3["ack_at"], g3["ack_reason"], g3["pass"]) == (OWNER, acked["ack_at"], "계면 확인 뒤 진행", False)
    assert all(g["ack_by"] is None for key, g in state["gates"].items() if key != "G3")
    assert state["gates_hash"] == acked["gates_hash"] == before["gates_hash"]
    # 화면이 읽은 지문을 그대로 실어 다시 ack 해도 낡았다고(409) 하지 않는다.
    again = routes.post_gate_ack(sid, "G3", routes.GateAckBody(reason="다시 확인", gates_hash=state["gates_hash"]),
                                 ident=owner)
    assert routes.get_snapshot(sid, part="state", ident=owner)["gates"]["G3"]["ack_reason"] == again["ack_reason"]
    # MCP risk_get_snapshot(part='state') 도 같은 함수다.
    assert routes.snapshot_part(sid, "state", owner_sub=OWNER)["gates"]["G3"]["ack_by"] == OWNER

    routes.delete_gate_ack(sid, "G3", ident=owner)
    revoked = routes.get_snapshot(sid, part="state", ident=owner)["gates"]["G3"]
    assert (revoked["ack_by"], revoked["ack_at"], revoked["ack_reason"]) == (None, None, None)


def test_a_gate_ack_left_on_an_older_judgement_or_on_a_pair_is_not_carried(wired):
    """ack 는 단 때의 판정 지문을 품는다(rr_gate_acks.gates_hash) — 판정이 바뀐 뒤의 ack 는 낡은 것이라 지금 게이트에 싣지 않는다. 비교(diff)
    스코프의 ack(diff_id 가 선 행)도 스냅샷 게이트의 ack 가 아니다."""
    store = wired
    project_id = factories.make_project(store)
    sid = factories.make_snapshot(store, project_id, [factories.adapter_fixture(MCAD_ONLY)], label="stale")["snapshot_id"]
    current = routes.get_snapshot(sid, part="state", ident=factories.ident(OWNER))["gates_hash"]
    factories.seed_raw(store, "rr_gate_acks", {
        "snapshot_id": sid, "gate": "G3", "owner_sub": OWNER, "diff_id": None, "ack_by": OWNER, "ack_at": now_epoch(),
        "ack_reason": "앞 판정에 단 ack", "gates_hash": "0123456789ab"},
        reason="판정이 바뀐 뒤의 ack — 게이트를 다시 세는 길(compute_state_for_snapshot)을 부르는 곳이 지금 없어 생산자로 만들 수 없다")
    factories.seed_raw(store, "rr_gate_acks", {
        "snapshot_id": sid, "gate": "G1", "owner_sub": OWNER, "diff_id": "diff-x", "ack_by": OWNER, "ack_at": now_epoch(),
        "ack_reason": "비교에 단 ack", "gates_hash": current},
        reason="비교 스코프 ack — diff_id 를 싣는 ack 생산자가 아직 없다(스키마는 G7 · pair 게이트 몫으로 둔다)")
    state = routes.get_snapshot(sid, part="state", ident=factories.ident(OWNER))
    assert state["gates"]["G3"]["ack_by"] is None and state["gates_hash"] == current != "0123456789ab"
    assert state["gates"]["G1"]["ack_by"] is None


def test_the_gate_summary_signal_and_the_summary_line_follow_the_live_ack(wired):
    """게이트에서 만든 글 — gates.summary 신호(값마다 ack · 글)와 summary_text 의 [게이트] 줄 — 도 얹은 ack 를 따른다. 종전에는 게이트 표가
    'fail(1) · ack' 인 같은 답의 신호 · 요약이 'G3 fail(1, ack 없음)' 이었다('단발 심사 열기' 가 그 요약을 복사한다). 다른 줄과 저장된 상태
    원문(동결 때 그대로)은 바뀌지 않는다."""
    store = wired
    owner = factories.ident(OWNER)
    project_id = factories.make_project(store)
    sid = factories.make_snapshot(store, project_id, [factories.adapter_fixture(MCAD_ONLY)], label="ack")["snapshot_id"]

    def gate_lines(state: dict) -> list[str]:
        return [line for line in state["summary_text"].split("\n") if line.startswith("[게이트] ")]

    def other_lines(state: dict) -> list[str]:
        return [line for line in state["summary_text"].split("\n") if not line.startswith("[게이트] ")]

    frozen = routes.get_snapshot(sid, part="state", ident=owner)
    assert frozen["signals"]["gates.summary"]["value"]["G3"] == {"pass": False, "count": 1, "ack": False}
    routes.post_gate_ack(sid, "G3", routes.GateAckBody(reason="계면 확인 뒤 진행"), ident=owner)

    state = routes.get_snapshot(sid, part="state", ident=owner)
    summary = state["signals"]["gates.summary"]
    assert summary["value"]["G3"] == {"pass": False, "count": 1, "ack": True}
    assert "G3 fail(1, ack 있음)" in summary["text"] and "ack 없음" not in summary["text"]
    assert gate_lines(state) == ["[게이트] " + summary["text"]]
    assert other_lines(state) == other_lines(frozen)
    stored = json.loads(store.query_one("SELECT state_json FROM rr_states WHERE snapshot_id = ?", (sid,))["state_json"])
    assert "G3 fail(1, ack 없음)" in stored["summary_text"]
    assert stored["signals"]["gates.summary"]["value"]["G3"]["ack"] is False
    # MCP risk_get_snapshot(part='state') 도 같은 함수다.
    assert routes.snapshot_part(sid, "state", owner_sub=OWNER)["signals"]["gates.summary"]["text"] == summary["text"]

    routes.delete_gate_ack(sid, "G3", ident=owner)
    revoked = routes.get_snapshot(sid, part="state", ident=owner)
    assert revoked["signals"]["gates.summary"] == frozen["signals"]["gates.summary"]
    assert revoked["summary_text"] == frozen["summary_text"]


def test_a_gate_ack_row_of_anyone_but_the_snapshot_owner_is_not_carried(wired):
    """ack 라우트는 스냅샷 주인만 쓴다 — 주인이 다른 ack 행(고침 전의 들여오기가 남의 스냅샷 id 로 남겼을 수 있는 행)은 게이트 · 신호 ·
    요약에 싣지 않는다(그 사람이 ack_by 를 주인의 이메일로 적어도)."""
    store = wired
    project_id = factories.make_project(store)
    sid = factories.make_snapshot(store, project_id, [factories.adapter_fixture(MCAD_ONLY)], label="남 ack")["snapshot_id"]
    current = routes.get_snapshot(sid, part="state", ident=factories.ident(OWNER))["gates_hash"]
    factories.seed_raw(store, "rr_gate_acks", {
        "snapshot_id": sid, "gate": "G3", "owner_sub": STRANGER, "diff_id": None, "ack_by": OWNER, "ack_at": now_epoch(),
        "ack_reason": "남이 적은 확인", "gates_hash": current},
        reason="고침 전의 들여오기가 남의 스냅샷 id 로 남긴 ack 행 — 이제 들여오기는 parent_not_owned 로 막는다")
    state = routes.get_snapshot(sid, part="state", ident=factories.ident(OWNER))
    assert state["gates"]["G3"]["ack_by"] is None
    assert state["signals"]["gates.summary"]["value"]["G3"]["ack"] is False


# ---------------------------------------------------------------- 4. GET /part-keys/{ckey}
def test_the_part_key_ledger_read_gives_the_key_state_to_its_owner_and_members(wired):
    """키 대장 한 행 — {ckey, status, merged_into, display_name, aliases[], decided_by, decided_at}. 주인은 다 보고, 그 키가 든 과제의
    구성원은 자기가 구성원인 과제의 별칭만 본다. 남과 없는 키는 같은 404 다."""
    store = wired
    owner = factories.ident(OWNER)
    shared = _shared_project()
    elsewhere = factories.make_project(store, code="OWNER-ONLY")       # 주인의 다른 과제 — 편집자 · 보기는 구성원이 아니다
    results = [factories.adapter_fixture(MCAD_ONLY)]
    sid = factories.make_snapshot(store, shared, results, label="공유")["snapshot_id"]
    factories.make_snapshot(store, elsewhere, results, label="주인만")
    first, second = _node_ckeys(store, sid)[:2]

    out = routes.get_part_key(first, ident=owner)
    assert set(out) == {"ckey", "status", "merged_into", "display_name", "aliases", "decided_by", "decided_at", "mine"}
    assert (out["ckey"], out["status"], out["merged_into"], out["display_name"]) == (first, "candidate", None, None)
    assert out["mine"] is True
    assert (out["decided_by"], out["decided_at"]) == (None, None)
    assert {a["project_id"] for a in out["aliases"]} == {shared, elsewhere}
    for who in (EDITOR, VIEWER):
        seen = routes.get_part_key(first, ident=factories.ident(who))
        assert {a["project_id"] for a in seen["aliases"]} == {shared}, who
        assert seen["mine"] is False, who                               # 주인의 원장 행이다 — 그 사람의 결정은 404 다
        assert elsewhere not in json.dumps(seen, ensure_ascii=False)

    routes.post_sameas_decide([{"decision": "rename_key", "ckey": first, "display_name": "보호 필름"},
                               {"decision": "merge_key", "ckey_from": second, "ckey_into": first}], ident=owner)
    named = routes.get_part_key(first, ident=factories.ident(EDITOR))
    assert (named["display_name"], named["decided_by"]) == ("보호 필름", OWNER) and named["decided_at"] is not None
    merged = routes.get_part_key(second, ident=factories.ident(VIEWER))
    assert (merged["status"], merged["merged_into"], merged["decided_by"]) == ("merged", first, OWNER)

    theirs = _refused(lambda: routes.get_part_key(first, ident=factories.ident(STRANGER)))
    gone = _refused(lambda: routes.get_part_key("ck:000000000000", ident=factories.ident(STRANGER)))
    assert theirs[:2] == ("E404", 404)
    assert (theirs[0], theirs[1], theirs[2].replace(first, "<k>")) == (gone[0], gone[1], gone[2].replace("ck:000000000000", "<k>"))
    assert _refused(lambda: routes.get_part_key("ck:000000000000", ident=owner))[:2] == ("E404", 404)


def test_the_part_key_read_says_the_row_is_not_mine_after_a_transfer(wired):
    """원장 행은 그 키를 처음 적립한 사람의 것이고 이양은 옮기지 않는다(TRANSFER_PROJECT_TABLES 에 rr_part_keys 가 없다 — 키는 과제가 아니라
    사람의 원장이다). 이양받은 새 주인은 그 과제의 키 행을 읽지만 mine=false 다 — 키 결정(이름 · 병합 · 되돌리기 · 확정)은 주인의 행만
    고쳐 새 주인의 결정은 404 이고, 새 주인의 유효 키 해석은 그 병합을 따르지 않는다. 화면은 mine 으로 결정을 잠근다(상태로 가르지 않는다)."""
    store = wired
    owner = factories.ident(OWNER)
    project_id = _shared_project("XFER-1")
    sid = factories.make_snapshot(store, project_id, [factories.adapter_fixture(MCAD_ONLY)], label="동결")["snapshot_id"]
    first, second = _node_ckeys(store, sid)[:2]
    routes.post_sameas_decide([{"decision": "merge_key", "ckey_from": second, "ckey_into": first}], ident=owner)
    routes.transfer_project(project_id, routes.TransferBody(to_email=EDITOR, reason="이양"), ident=owner)

    seen = routes.get_part_key(second, ident=factories.ident(EDITOR))
    assert (seen["status"], seen["merged_into"], seen["decided_by"], seen["mine"]) == ("merged", first, OWNER, False)
    assert sameas.resolve_ckey(store, second, EDITOR) == second
    for decision in ({"decision": "unmerge_key", "ckey": second}, {"decision": "confirm_key", "ckey": second},
                     {"decision": "rename_key", "ckey": second, "display_name": "새 이름"},
                     {"decision": "merge_key", "ckey_from": second, "ckey_into": first}):
        assert _refused(lambda: routes.post_sameas_decide([decision], ident=factories.ident(EDITOR)))[:2] == ("E404", 404)
    # 옛 주인(이제 편집자)에게는 여전히 제 행이다.
    assert routes.get_part_key(second, ident=owner)["mine"] is True


def test_the_part_key_read_unfolds_aliases_that_carry_merge_proposals(wired):
    """다른 과제와의 결정론 대응은 별칭 열에 병합 제안을 더해 객체({items, merged_candidates})로 바꾼다(sameas.inherit_ckeys cross_project) —
    읽기는 그 안의 별칭 목록을 편다(제안은 싣지 않는다)."""
    store = wired
    base = [mcad("b1", "/x/film", "film", (10.0, 5.0, 0.08), 4.0)]
    target = [mcad("t1", "/y/film", "film", (10.0, 5.0, 0.06), 3.0)]
    sameas.assign_ckeys(store, base, [], owner_sub=OWNER, project_id="p1", snapshot_id="s1")
    target_ckey = sameas.assign_ckeys(store, target, [], owner_sub=OWNER, project_id="p9", snapshot_id="s9")["ckeys"]["t1"]
    applied = sameas.inherit_ckeys(store, [{"a": "b1", "b": "t1", "method": "name_norm", "score": 0.95, "status": "auto"}],
                                   base, target, owner_sub=OWNER, pair_kind="cross_project",
                                   base_snapshot_id="s1", target_snapshot_id="s9")
    assert [a["action"] for a in applied] == ["proposed"]
    out = routes.get_part_key(target_ckey, ident=factories.ident(OWNER))
    assert (out["status"], [(a["project_id"], a["label"]) for a in out["aliases"]]) == ("candidate", [("p9", target[0]["label"])])


# ---------------------------------------------------------------- 5. GET /sameas
def test_the_sameas_table_names_the_pair_key_its_ledger_is_read_with(wired):
    """대응표가 원장을 읽는 열쇠(정렬한 두 과제 id 를 '|' 로 이은 것)를 답 머리에 싣는다 — 화면이 서버 글의 꼴로 짓지 않게."""
    store = wired
    a = factories.make_project(store, code="PAIR-A")
    b = factories.make_project(store, code="PAIR-B")
    results = factories.fixture_adapter_results()
    base = factories.make_snapshot(store, a, results, label="A")["snapshot_id"]
    target = factories.make_snapshot(store, b, results, label="B")["snapshot_id"]
    out = routes.get_sameas(base=base, target=target, ident=factories.ident(OWNER))
    assert out["pair_key"] == "|".join(sorted([a, b]))
    assert routes.get_sameas(base=target, target=base, ident=factories.ident(OWNER))["pair_key"] == out["pair_key"]


# ---------------------------------------------------------------- 6. GET /targets/{key}/coverage — job.signals
def test_the_panel_job_on_the_board_lists_one_signal_per_running_panel(risk_store, tmp_path, monkeypatch):
    """진행판 패널 잡의 `signals` 는 지금 도는 그 잡의 패널마다 한 줄이다(`signal` 은 호환으로 그대로). 러너는 대상마다 패널을 하나씩만
    돌린다(claim_next_job 의 도는 패널 검사 · planner 불변식 2) — 그래서 지금은 많아야 한 줄이고 그 줄은 `signal` 과 같다."""
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: "runner-panel-gateway-secret")
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = seeded(risk_store)
    give_credential(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=PANEL_OWNER, settings=cfg)
    job = runner.claim_next_job(risk_store, cfg)
    queued = routes.coverage_payload(target_key)["job"]
    assert (queued["signal"], queued["signals"]) == (None, [])
    board: list[dict] = []

    class StreamingEngine(FakePanelEngine):
        def run(self, delib_opts, *, owner_sub=None, on_progress=None):
            on_progress({"last_frame_at": now_epoch(), "last_event_at": now_epoch(), "last_step": "1라운드", "frames": 1},
                        force=True)
            board.append(routes.coverage_payload(target_key)["job"])
            return super().run(delib_opts, owner_sub=owner_sub)

    out = runner.run_panel(risk_store, cfg, StreamingEngine(), job,
                           narrative_mod=fake_narrative({}), registry_mod=fake_registry({}))
    assert out["status"] == "done"
    (running,) = board
    assert running["signal"] is not None and running["signal"]["panel_id"] == out["panel_id"]
    assert running["signals"] == [running["signal"]]
    closed = routes.coverage_payload(target_key)["job"]
    assert (closed["signal"], closed["signals"]) == (None, [])
