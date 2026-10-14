# 셀 원장·상태기계·검토 잡 만들기·원장 닫기(재설계 M2 · m2-wp3b S5) — 대상·단위·로스터·팩은 실제 생산자로 만든다
"""대상은 공장(`make_diff_target`) → 라우트(`create_target(flow='cells')` — 단위 빌드까지), 로스터는 `list_agents` 모양의 명단,
카드 묶음은 엔진이 만든 계약 예제(`pack_ok.json`·`pack_empty.json`)를 `cardpack.freeze_pack` 으로 얼린 것, 판정 행은 엔진 계약
요청·결과 짝(`req_verdict_fwd.json`·`result_verdict_ok.json` — 그 요청에 실린 카드로 재대조)을 앱의 회계(`review_verify.accept_rows`)에
지난 것이다. 원장 행은 손으로 넣지 않는다.

계약 예제의 판정은 계약 예제의 단위(`c:ab12cd34ef56`)를 짚는다. 이 대상의 단위를 짚은 판정이 필요할 때는 가짜 엔진(S7)이 하듯
받은 단위의 줄 참조를 돌려준 답으로 바꾼다(`_answer`) — 원래 참조 그대로면 그 단위의 참조가 아니어서 검증된 근거가 아니다.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import threading

import httpx
import pytest

from app import cardpack, config, identity, narrative, planner, review_cells, review_ops, review_runner, routes, runner
from app import relevance, review_verify, units
from app.common import now_epoch
from app.errors import AppError
from app.review_cells import IllegalTransition
from app.risk_store import RiskStore
from tests import factories
from tests.conftest import FIXTURES_DIR

OWNER = factories.OWNER
PEER = "peer@example.com"
SEAL = "mech-test-seal"                      # 계약 예제 팩의 전문가 — 영역 1순위(Tier A)로 앉힌다
CONTRACT = FIXTURES_DIR / "card_review" / "contract"
BOOT = "boot-test"
# ECAD 에 기대는 영역이 없는 로스터(합성 쌍에는 회로 소스가 없다 — M2 는 입력 결손 전문가를 범위에 받지 않는다).
ROSTER = [{"key": SEAL, "domain": "mech", "relevance": 0.99}, *factories.agents(("mech", "sim", "xd"), 2)]


def _load(name: str) -> dict:
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, data_dir=tmp_path,
                                                               risk_review_enabled=True))
    cardpack.clear_cache()
    return risk_store


def _target(store, *, agents=ROSTER, flow: str = "cells", seed: int | None = None) -> str:
    synth = factories.make_diff_target(store, 40, seed=seed, open_target=False)
    out = routes.create_target(routes.TargetBody(kind="diff", ref_id=synth.diff_id, consent=True, flow=flow,
                                                 agents=list(agents)), ident=factories.ident(OWNER))
    return out["target_key"]


def _pat(store, email: str = OWNER, *, life_s: int = 30 * 86400) -> None:
    """웹 설정 화면이 남기는 것과 같은 자격 행(Fernet 암호문)."""
    store.upsert_credential(email, identity.encrypt_pat(f"pat-{email}").decode("ascii"), "sub", email, "[]",
                            now_epoch() + life_s)


def _job(store, key: str, scope=None, **kwargs) -> dict:
    _pat(store)
    kwargs.setdefault("consent", True)
    return review_runner.create_review_job(store, key, owner_sub=OWNER, requester_sub=OWNER, scope=scope,
                                           consent_source="web", settings=config.settings, **kwargs)


def _running(store, job: dict) -> dict:
    runner._set_job(store, job["job_id"], "running")
    return {"id": job["job_id"]}


def _refused(fn, *args, **kwargs) -> AppError:
    with pytest.raises(AppError) as exc:
        fn(*args, **kwargs)
    return exc.value


def _cells(store, key: str) -> list[dict]:
    return [dict(r) for r in store.query("SELECT * FROM rr_review_cells WHERE target_key = ? ORDER BY agent_key, unit_seq",
                                         (key,))]


def _cell(store, key: str, unit_id: str, agent: str) -> dict:
    return dict(store.query_one("SELECT * FROM rr_review_cells WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                                (key, unit_id, agent)))


def _head(store, key: str, agent: str) -> dict:
    return dict(store.query_one("SELECT * FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?", (key, agent)))


def _coverage(store, key: str, agent: str) -> dict:
    return dict(store.query_one("SELECT status, reason, panel_id, opinion_id, origin, tier FROM rr_coverage"
                                " WHERE target_key = ? AND agent_key = ?", (key, agent)))


def _unit_ids(store, key: str) -> list[str]:
    return [u["unit_id"] for u in units.load_units(store, key)]


def _freeze(store, name: str) -> dict:
    return cardpack.freeze_pack(store, _load(name), agent_key=SEAL)


def _with_pack(store, job: dict, key: str, pack: str) -> dict:
    """묶음 갈래로 SEAL 을 쥐고 계약 예제 팩을 얼려 머리에 묶은 뒤 놓는다 — 루프(S8)의 묶음 걸음과 같은 차례다."""
    head = review_cells.claim_next_expert(store, job, boot_id=BOOT, purpose="pack")
    assert head["agent_key"] == SEAL
    frozen = _freeze(store, pack)
    status = "ok" if frozen["cards_total"] else "empty"
    assert review_cells.record_pack(store, key, SEAL, lease_owner=head["lease_owner"], status=status,
                                    pack_hash=frozen["pack_hash"], card_basis=frozen["card_basis"])
    assert review_cells.release_expert(store, key, SEAL, lease_owner=head["lease_owner"]) == {"released": True,
                                                                                               "cells": 0}
    return frozen


def _start(store, key: str, unit_id: str, lease: str, *, pack_hash: str | None = None, prompt_rev: str = "p1") -> dict:
    payload = units.review_payload(store, key, unit_id, SEAL)
    digest = review_cells.cell_input_hash(unit_hash=payload["unit_hash"], evidence_sha=payload["evidence_sha"],
                                          pack_hash=pack_hash, prompt_rev=prompt_rev, limits_rev="l1")
    cell = review_cells.start_cell(store, key, unit_id, SEAL, lease_owner=lease, input_hash=digest, pack_hash=pack_hash,
                                   prompt_rev=prompt_rev, verify_rev=review_verify.VERIFY_REV)
    assert cell is not None and cell["state"] == "running" and cell["lease_owner"] == lease
    return cell


def _call(unit_id: str | None, call_id: str, *, kind: str = "offcard", aliases=(), state: str = "ok", **extra) -> dict:
    return {"call_id": call_id, "kind": kind, "unit_id": unit_id, "state": state, "cards_json": json.dumps(list(aliases)),
            "outcome_class": "ok" if state == "ok" else None, **extra}


def _answer(result: dict, unit_refs: list[str]) -> dict:
    """계약 결과를 이 단위에 대한 답으로 — 가짜 엔진(S7)처럼 받은 단위의 줄 참조를 짚게 한다(판정·인용은 그대로)."""
    out = copy.deepcopy(result)
    for row in out["rows"]:
        if row.get("refs"):
            row["refs"] = unit_refs[:1]
    return out


def _verdicts(store, key: str, unit_id: str, frozen: dict, *, own_refs: bool) -> tuple[dict, list[dict]]:
    """계약 fwd 요청의 카드를 이 단위에 대조한 행 — (호출 원장 행, 판정 행)."""
    request = _load("req_verdict_fwd.json")
    aliases = [c["alias"] for c in request["cards"]]
    refs = sorted(units.unit_refs(store, key, unit_id))
    result = _answer(_load("result_verdict_ok.json"), refs) if own_refs else _load("result_verdict_ok.json")
    # 계약 결과는 그 요청에 실린 카드로 대조한 것이다 — 재대조도 그 카드로 한다(test_review_verify 와 같다).
    pack = cardpack.view_of({"agent_key": SEAL, "cards": request["cards"]})
    accepted = review_verify.accept_rows(result, kind="verdict", sent_aliases=aliases, pack=pack,
                                         unit_refs=units.unit_refs(store, key, unit_id), variant="fwd")
    assert accepted["missing"] == [] and accepted["dropped"] == []
    call = _call(unit_id, f"rc-{unit_id}-fwd", kind="verdict", aliases=aliases, variant="fwd", deck_id="v1",
                 tokens_in=1000, tokens_out=200, duration_ms=1500, attempts=1)
    return call, accepted["rows"]


def _review_unit(store, key: str, unit_id: str, lease: str, frozen: dict | None, *, own_refs: bool = True) -> dict:
    """셀 하나를 끝까지 — 시작 → (카드가 있으면 대조 호출) → 카드 밖 호출 → 정산."""
    _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"] if frozen else None)
    if frozen and frozen["cards_total"]:
        call, rows = _verdicts(store, key, unit_id, frozen, own_refs=own_refs)
        assert review_cells.begin_call(store, key, SEAL, lease_owner=lease, call={**call, "state": "running"})
        out = review_cells.write_call_result(store, key, SEAL, lease_owner=lease, call=call, verdicts=rows,
                                             cell={"basis": "cards", "cards_expected": len(rows), "truncated": 0})
        assert out == {"written": True, "call_id": call["call_id"], "cell_state": "running"}
    basis = "role_only" if not frozen or not frozen["cards_total"] else "cards"
    extra = {} if basis == "cards" else {"cards_expected": 0, "cards_judged": 0}
    out = review_cells.write_call_result(store, key, SEAL, lease_owner=lease, call=_call(unit_id, f"rc-{unit_id}-off"),
                                         cell={"basis": basis, "offcard_state": "done", **extra})
    assert out["written"] and out["cell_state"] == "running"
    return review_cells.settle_cell(store, key, unit_id, SEAL, lease_owner=lease)


def _opinion(key: str) -> str:
    """S9 가 쓸 검토 의견의 id — 검토 대역의 회차(500 + 원장 cycle 1)."""
    return narrative._opinion_id(review_cells.review_id_of(key, SEAL), SEAL, 501)


def _stop(store, job: dict) -> None:
    """도는 검토 잡을 사람이 멈추고 취소한다(멈춘 잡은 곧바로 cancelled 다 — 도는 잡의 cancelling 은 루프가 닫는다)."""
    runner.pause_job(store, job["id"], by=OWNER)
    runner.cancel_job(store, job["id"], by=OWNER)


# ---------------------------------------------------------------- 격자(X1-27)
def test_the_grid_is_the_whole_roster_times_the_reviewable_units_and_planning_again_changes_nothing(store):
    """격자는 로스터 전원 × 활성 빌드의 검토 대상 단위다 — ECAD 에 기대는데 ECAD 가 없는 전문가·deferred 좌석도 칸이 있다(분모는
    범위와 상관없다). 머리는 review_order 의 사본이고 review_id 는 hex32 다. 두 번 불러도 같은 행이다."""
    key = _target(store, agents=factories.agents())          # pcb 2명 — 1순위는 입력 결손, 2순위는 deferred 좌석
    order = planner.review_order(store, key)
    unit_rows = units.load_units(store, key)
    assert {r["agent_key"] for r in order if r["input_gaps"]} == {"pcb-syn-0", "pcb-syn-1"}
    assert _coverage(store, key, "pcb-syn-1")["status"] == "deferred"

    plan = review_cells.plan_cells(store, key)
    assert plan == {"experts": len(order), "units": len(unit_rows), "heads_new": len(order),
                    "cells_new": len(order) * len(unit_rows), "cells_total": len(order) * len(unit_rows),
                    "cells_dropped": 0}
    cells = _cells(store, key)
    assert {(c["unit_id"], c["agent_key"]) for c in cells} == {(u["unit_id"], r["agent_key"])
                                                                for u in unit_rows for r in order}
    seq = {u["unit_id"]: (u["seq"], u["unit_hash"]) for u in unit_rows}
    assert all(c["state"] == "pending" and (c["unit_seq"], c["unit_hash"]) == seq[c["unit_id"]] and c["run_id"] is None
               and c["owner_sub"] == OWNER for c in cells)
    heads = {h["agent_key"]: h for h in map(dict, store.query("SELECT * FROM rr_expert_reports WHERE target_key = ?",
                                                                (key,)))}
    for row in order:
        head = heads[row["agent_key"]]
        assert (head["tier"], head["review_order"], head["rank_in_domain"], head["domain"], head["state"],
                head["pack_status"], head["cells_total"]) == (row["tier"], row["order"], row["rank_in_domain"],
                                                              row["domain"], "planned", "todo", len(unit_rows))
        assert head["review_id"] == review_cells.review_id_of(key, row["agent_key"]) and len(head["review_id"]) == 32
        int(head["review_id"], 16)
    again = review_cells.plan_cells(store, key)
    assert (again["heads_new"], again["cells_new"], again["cells_dropped"]) == (0, 0, 0)
    assert _cells(store, key) == cells
    assert review_cells.review_invariants(store, key) == [] and planner.check_invariants(store, key) == []


# ---------------------------------------------------------------- 전이표
def test_every_move_goes_through_the_tables_and_moves_off_them_raise(store):
    """표에 없는 전이는 DB 를 보기 전에 IllegalTransition 이다 — skipped 는 failed 에서만 간다(pending → skipped 없음), 종결 셀은
    해당 없음으로 옮겨지지 않는다. 표의 전이는 실제 행에서 한 칸씩 움직인다."""
    for machine, states, table in (("cell", review_cells.CELL_STATES, review_cells.CELL_TRANSITIONS),
                                   ("expert", review_cells.EXPERT_STATES, review_cells.EXPERT_TRANSITIONS)):
        assert {s for pair in table for s in pair} <= set(states)
        for src in states:
            for dst in states:
                if (src, dst) not in table:
                    with pytest.raises(IllegalTransition):
                        review_cells._move(store, machine, src, dst, where="1 = 0")
    assert {src for src, dst in review_cells.CELL_TRANSITIONS if dst == "skipped"} == {"failed"}
    with pytest.raises(IllegalTransition):
        review_cells._move(store, "cell", "reviewed", "na_irrelevant", where="1 = 0")
    with pytest.raises(IllegalTransition):
        review_cells._move(store, "cell", ("pending", "failed"), "skipped", where="1 = 0")

    key = _target(store)
    review_cells.plan_cells(store, key)
    one, two = _unit_ids(store, key)[:2]
    pk = "target_key = ? AND unit_id = ? AND agent_key = ?"
    for unit_id, walk in ((one, ("running", "pending", "failed", "skipped")), (two, ("running", "reviewed"))):
        state = "pending"
        for nxt in walk:
            assert review_cells._move(store, "cell", state, nxt, where=pk, params=(key, unit_id, SEAL)) == 1, (state, nxt)
            state = nxt
        assert _cell(store, key, unit_id, SEAL)["state"] == walk[-1]
    state = "planned"
    for nxt in ("running", "planned", "blocked", "planned", "running", "ready", "planned", "running", "partial",
                "planned", "running", "blocked"):
        assert review_cells._move(store, "expert", state, nxt, where="target_key = ? AND agent_key = ?",
                                  params=(key, SEAL)) == 1, (state, nxt)
        state = nxt
    assert review_cells._move(store, "expert", "planned", "running", where="target_key = ? AND agent_key = ?",
                              params=(key, SEAL)) == 0              # 이미 blocked — 바뀐 행 0


# ---------------------------------------------------------------- 범위는 집지 않는 것으로만(X1-27)
def test_a_review_job_plans_the_whole_grid_but_only_claims_its_scope(store):
    """범위(영역 mech)는 격자를 줄이지 않는다 — 70칸 전부가 서고 범위 안 30칸과 그 전문가 셋에만 잡 id 가 찍힌다. 잡이 running 이
    아니면 아무도 집히지 않고, 묶음이 없는 전문가는 카드 대조 갈래로 집히지 않으며, 묶음 갈래는 review_order 순서로 범위 안만
    집는다."""
    key = _target(store)
    job = _job(store, key, scope={"domains": ["mech"]})
    unit_ids = _unit_ids(store, key)
    mech = [r["agent_key"] for r in planner.review_order(store, key) if r["domain"] == "mech"]
    assert (job["cells_total"], job["cells_in_scope"], job["experts_in_scope"], job["units"]) == (
        len(ROSTER) * len(unit_ids), 3 * len(unit_ids), 3, len(unit_ids))
    stamped = {(c["unit_id"], c["agent_key"]) for c in _cells(store, key) if c["run_id"] == job["job_id"]}
    assert stamped == {(u, a) for u in unit_ids for a in mech}
    assert {r["agent_key"] for r in store.query("SELECT agent_key FROM rr_expert_reports WHERE target_key = ?"
                                                " AND run_id = ?", (key, job["job_id"]))} == set(mech)
    summary = review_cells.review_summary(store, key)
    assert summary["cells"]["in_scope"]["total"] == 30 and summary["cells"]["out_of_scope_pending"] == 40
    assert summary["experts"]["by_state"]["planned"] == len(ROSTER)

    assert review_cells.claim_next_expert(store, boot_id=BOOT, purpose="pack") is None           # 잡이 아직 queued
    live = _running(store, job)
    assert review_cells.claim_next_expert(store, live, boot_id=BOOT) is None                     # 묶음이 todo
    claimed = [review_cells.claim_next_expert(store, live, boot_id=BOOT, purpose="pack") for _ in range(4)]
    assert [c and c["agent_key"] for c in claimed] == [*mech, None]
    leases = [c["lease_owner"] for c in claimed[:3]]
    assert len(set(leases)) == 3 and all(lease.startswith(f"{BOOT}:") and len(lease) == len(BOOT) + 33
                                         for lease in leases)
    assert all(_head(store, key, a)["state"] == "running" for a in mech)
    assert review_cells.review_invariants(store, key) == [] and planner.check_invariants(store, key) == []


def test_two_workers_claiming_at_once_get_the_expert_once(store, tmp_path):
    """두 연결(다른 프로세스와 같은 자리)이 같은 순간에 같은 전문가를 집으면 하나만 얻는다 — 'planned' 조건의 UPDATE 다."""
    key = _target(store)
    live = _running(store, _job(store, key, scope={"agents": [SEAL]}))
    other = RiskStore(store.db_path)
    other.open()
    try:
        gate = threading.Barrier(2)
        got: list = []

        def grab(conn):
            gate.wait()
            got.append(review_cells.claim_next_expert(conn, live, boot_id=f"b{id(conn)}", purpose="pack"))

        threads = [threading.Thread(target=grab, args=(s,)) for s in (store, other)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        other.close()
    assert sorted(bool(g) for g in got) == [False, True]
    winner = next(g for g in got if g)
    assert _head(store, key, SEAL)["lease_owner"] == winner["lease_owner"]


def test_claims_take_turns_between_live_review_jobs(store):
    """검토 잡끼리 차례가 있다 — 잡을 주지 않으면 도는 전문가가 가장 적은 잡부터 집는다(P-09). 먼저 만든 잡이 자리를 다 쓰지 않는다."""
    first = _target(store)
    second = _target(store)
    jobs = {first: _running(store, _job(store, first, scope={"domains": ["mech"]})),
            second: _running(store, _job(store, second, scope={"domains": ["mech"]}))}
    got = [review_cells.claim_next_expert(store, boot_id=BOOT, purpose="pack") for _ in range(7)]
    order = [g and g["target_key"] for g in got]
    assert {order[0], order[1]} == {first, second} and order[:6] == order[:2] * 3 and order[6] is None
    assert all(g["run_id"] == jobs[g["target_key"]]["id"] for g in got[:6])


# ---------------------------------------------------------------- 셀 하나의 일생 · 원장 닫기(close_review_seat)
def test_a_cards_free_expert_reviews_by_role_and_its_seat_closes_done_weak_no_cards(store):
    """카드 0장 전문가(빈 묶음)는 셀마다 카드 밖 호출 하나로 reviewed(basis role_only)다. 열린 셀이 남은 동안 원장은 pending 이고
    (planner 불변식 그대로), 다 닫히면 done_weak(no_cards) 로 닫힌다 — 의견 id · 검토 id · origin · tier 가 함께 적힌다."""
    key = _target(store)
    job = _job(store, key, scope={"agents": [SEAL]})
    live = _running(store, job)
    frozen = _with_pack(store, live, key, "pack_empty.json")
    assert (_head(store, key, SEAL)["pack_status"], _head(store, key, SEAL)["card_basis"]) == ("empty", "none")
    head = review_cells.claim_next_expert(store, live, boot_id=BOOT)
    lease = head["lease_owner"]
    unit_ids = _unit_ids(store, key)
    first = _review_unit(store, key, unit_ids[0], lease, frozen)
    assert first == {"written": True, "state": "reviewed"}
    early = planner.close_review_seat(store, key, SEAL, review_id=head["review_id"], opinion_id=_opinion(key))
    assert early == {"updated": False, "status": "pending", "reason": None, "why": "open_cells"}
    assert planner.check_invariants(store, key) == [] and review_cells.review_invariants(store, key) == []
    for unit_id in unit_ids[1:]:
        assert _review_unit(store, key, unit_id, lease, frozen)["state"] == "reviewed"
    cell = _cell(store, key, unit_ids[0], SEAL)
    assert (cell["basis"], cell["tries"], cell["lease_owner"], cell["cards_expected"], cell["cards_judged"]) == (
        "role_only", 1, None, 0, 0)
    summary = review_cells.review_summary(store, key)
    assert summary["cells"]["by_basis"] == {"cards": 0, "background": 0, "role_only": len(unit_ids)}
    assert summary["cells"]["in_scope"]["by_state"]["reviewed"] == len(unit_ids)

    closed = planner.close_review_seat(store, key, SEAL, review_id=head["review_id"], opinion_id=_opinion(key))
    assert closed == {"updated": True, "status": "done_weak", "reason": "no_cards"}
    assert _coverage(store, key, SEAL) == {"status": "done_weak", "reason": "no_cards", "panel_id": head["review_id"],
                                           "opinion_id": _opinion(key), "origin": "primary", "tier": "A"}
    again = planner.close_review_seat(store, key, SEAL, review_id=head["review_id"], opinion_id=_opinion(key))
    assert again["updated"] is True and _coverage(store, key, SEAL)["status"] == "done_weak"     # 같은 검토의 다시 마감
    assert planner.check_invariants(store, key) == [] and review_cells.review_invariants(store, key) == []


def test_verified_card_verdicts_close_done_and_a_failed_cell_makes_it_done_weak_partial(store):
    """카드 대조 판정이 그 단위의 줄을 짚고 인용이 얼린 원문에 있으면(검증된 근거 — X1-05) 원장은 done 이다. 같은 전문가에게
    실패 셀이 하나라도 남으면 done 이 아니라 done_weak(partial:<n>) 다(m-01)."""
    done_key = _target(store, seed=21)
    partial_key = _target(store, seed=22)
    for key in (done_key, partial_key):
        live = _running(store, _job(store, key, scope={"agents": [SEAL]}))
        frozen = _with_pack(store, live, key, "pack_ok.json")
        lease = review_cells.claim_next_expert(store, live, boot_id=BOOT)["lease_owner"]
        unit_ids = _unit_ids(store, key)
        last = unit_ids[-1] if key == partial_key else None
        for unit_id in unit_ids:
            if unit_id == last:
                _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"])
                out = review_cells.settle_cell(store, key, unit_id, SEAL, lease_owner=lease, fail_code="call_cap")
                assert out == {"written": True, "state": "failed", "code": "call_cap"}
                continue
            assert _review_unit(store, key, unit_id, lease, frozen) == {"written": True, "state": "reviewed"}
        verdict = dict(store.query_one(
            "SELECT * FROM rr_card_verdicts WHERE target_key = ? AND unit_id = ? AND agent_key = ? AND record_id = ?",
            (key, unit_ids[0], SEAL, "DOC-CCT-MECH-2026-0000000101")))
        assert (verdict["is_effective"], verdict["applies"], verdict["quote_ok"], verdict["refs_ok"], verdict["call_id"],
                verdict["owner_sub"], verdict["deck_id"]) == (1, "yes", 1, 1, f"rc-{unit_ids[0]}-fwd", OWNER, "v1")
        cell = _cell(store, key, unit_ids[0], SEAL)
        assert (cell["cards_judged"], cell["cards_expected"], cell["n_ok"], cell["quote_ok"], cell["refs_ok"],
                cell["tries"], cell["tokens_in"], cell["llm_calls"]) == (8, 8, 8, 8, 8, 2, 1000, 1)
        assert review_cells.review_invariants(store, key) == [] and planner.check_invariants(store, key) == []
    done = planner.close_review_seat(store, done_key, SEAL, review_id=review_cells.review_id_of(done_key, SEAL),
                                     opinion_id=_opinion(done_key), model="glm-fake")
    assert done == {"updated": True, "status": "done", "reason": None}
    partial = planner.close_review_seat(store, partial_key, SEAL,
                                        review_id=review_cells.review_id_of(partial_key, SEAL),
                                        opinion_id=_opinion(partial_key))
    assert partial == {"updated": True, "status": "done_weak", "reason": "partial:1"}
    assert review_cells.review_summary(store, partial_key)["cells"]["failed_open"] == 1


def test_quotes_that_pass_but_point_at_another_units_lines_are_not_verified(store):
    """인용이 얼린 원문에 있어도 판정이 짚은 줄이 이 단위의 것이 아니면 검증된 근거가 아니다 — done_weak(no_verified_cite)."""
    key = _target(store)
    live = _running(store, _job(store, key, scope={"agents": [SEAL]}))
    frozen = _with_pack(store, live, key, "pack_ok.json")
    lease = review_cells.claim_next_expert(store, live, boot_id=BOOT)["lease_owner"]
    for unit_id in _unit_ids(store, key):
        assert _review_unit(store, key, unit_id, lease, frozen, own_refs=False)["state"] == "reviewed"
    rows = store.query("SELECT DISTINCT quote_ok, refs_ok FROM rr_card_verdicts WHERE target_key = ?", (key,))
    assert [tuple(r) for r in rows] == [(1, 0)]
    closed = planner.close_review_seat(store, key, SEAL, review_id=review_cells.review_id_of(key, SEAL),
                                       opinion_id=_opinion(key))
    assert closed == {"updated": True, "status": "done_weak", "reason": "no_verified_cite"}


def test_a_seat_is_not_closed_with_out_of_scope_cells_failures_only_on_a_panel_target_or_elsewhere(store):
    """닫지 않는 길 넷 — 범위 밖 pending 이 남았다(P-04: 단위로 좁힌 잡), reviewed 0 이고 실패뿐(X1-23), 사람이 이미 넘긴 좌석
    (패널이 닫은 행·deferred·carried 와 같이 건드리지 않는다), 패널 대상에 얹은 검토(M2.md 5절 #8)."""
    key = _target(store)
    unit_ids = _unit_ids(store, key)
    live = _running(store, _job(store, key, scope={"agents": [SEAL], "unit_ids": unit_ids[:1]}))
    frozen = _with_pack(store, live, key, "pack_empty.json")
    lease = review_cells.claim_next_expert(store, live, boot_id=BOOT)["lease_owner"]
    assert _review_unit(store, key, unit_ids[0], lease, frozen)["state"] == "reviewed"
    assert review_cells.release_expert(store, key, SEAL, lease_owner=lease)["released"]
    assert review_cells.claim_next_expert(store, live, boot_id=BOOT) is None          # 범위 안에 집을 셀이 없다
    out = planner.close_review_seat(store, key, SEAL, review_id=review_cells.review_id_of(key, SEAL),
                                    opinion_id=_opinion(key))
    assert (out["updated"], out["why"], out["status"]) == (False, "open_cells", "pending")

    peer = "sim-syn-0"
    review_cells.fail_open_cells(store, key, peer, code="pack_unavailable", error="팩 502 여섯 번")
    assert review_cells.expert_tally(store, key, peer)["failed"] == len(unit_ids)
    out = planner.close_review_seat(store, key, peer, review_id=review_cells.review_id_of(key, peer), opinion_id="x" * 32)
    assert (out["updated"], out["why"]) == (False, f"failed_open:{len(unit_ids)}")    # 사유가 열린 실패 수를 단다(m3-cells 3.9)

    _stop(store, live)                                                  # 남은 단위를 다음 잡이 돈다
    live = _running(store, _job(store, key, scope={"agents": [SEAL]}))
    lease = review_cells.claim_next_expert(store, live, boot_id=BOOT)["lease_owner"]
    for unit_id in unit_ids[1:]:
        assert _review_unit(store, key, unit_id, lease, frozen)["state"] == "reviewed"
    planner.skip_seat(store, key, SEAL, "사람이 넘김", decided_by=OWNER)
    out = planner.close_review_seat(store, key, SEAL, review_id=review_cells.review_id_of(key, SEAL),
                                    opinion_id=_opinion(key))
    assert (out["updated"], out["why"], out["status"]) == (False, "closed_elsewhere", "skipped")

    panel_key = _target(store, flow="panels", seed=31)
    routes.post_units(panel_key, routes.UnitsBody(), ident=factories.ident(OWNER))
    live = _running(store, _job(store, panel_key, scope={"agents": [SEAL]}))
    frozen = _with_pack(store, live, panel_key, "pack_empty.json")
    lease = review_cells.claim_next_expert(store, live, boot_id=BOOT)["lease_owner"]
    for unit_id in _unit_ids(store, panel_key):
        _review_unit(store, panel_key, unit_id, lease, frozen)
    out = planner.close_review_seat(store, panel_key, SEAL, review_id=review_cells.review_id_of(panel_key, SEAL),
                                    opinion_id=_opinion(panel_key))
    assert (out["updated"], out["why"], _coverage(store, panel_key, SEAL)["status"]) == (False, "flow_panels", "pending")
    assert review_cells.review_invariants(store, key) == [] and review_cells.review_invariants(store, panel_key) == []
    with pytest.raises(AppError):
        planner.close_review_seat(store, key, SEAL, review_id=review_cells.review_id_of(key, SEAL), opinion_id="")


# ---------------------------------------------------------------- 결말과 선점(늦은 쓰기)
def test_a_late_write_after_a_restart_changes_nothing(store):
    """재기동 복구 — 셀 running → pending, 전문가 running → planned, 호출 running → aborted('restart'), 차감·백오프 없음, 검토 잡은
    running 그대로. 그 뒤 옛 선점으로 오는 결과·정산·놓음·시작은 0행이다."""
    key = _target(store)
    job = _job(store, key, scope={"agents": [SEAL]})
    live = _running(store, job)
    frozen = _with_pack(store, live, key, "pack_ok.json")
    lease = review_cells.claim_next_expert(store, live, boot_id=BOOT)["lease_owner"]
    unit_id = _unit_ids(store, key)[0]
    _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"])
    call, rows = _verdicts(store, key, unit_id, frozen, own_refs=True)
    assert review_cells.begin_call(store, key, SEAL, lease_owner=lease, call={**call, "state": "running"})

    assert review_cells.recover_running(store) == {"cells": 1, "experts": 1, "calls": 1}
    cell = _cell(store, key, unit_id, SEAL)
    assert (cell["state"], cell["lease_owner"], cell["charged"], cell["infra_streak"], cell["not_before"]) == (
        "pending", None, 0, 0, None)
    assert (_head(store, key, SEAL)["state"], _head(store, key, SEAL)["lease_owner"]) == ("planned", None)
    row = store.query_one("SELECT state, outcome_class, error_code FROM rr_review_calls WHERE call_id = ?",
                          (call["call_id"],))
    assert tuple(row) == ("aborted", "cancelled", "restart")
    assert store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job["job_id"],))["state"] == "running"

    before = (_cells(store, key), _head(store, key, SEAL))
    assert review_cells.write_call_result(store, key, SEAL, lease_owner=lease, call=call, verdicts=rows) == {
        "written": False, "call_id": call["call_id"]}
    sweep = {"call_id": "rc-sweep-late", "kind": "sweep", "state": "ok", "cards_json": "[]"}   # 셀이 없는 머리 몫 호출
    assert review_cells.write_call_result(store, key, SEAL, lease_owner=lease, call=sweep,
                                          head={"sweep_state": "done"}) == {"written": False, "call_id": "rc-sweep-late"}
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_review_calls WHERE call_id = 'rc-sweep-late'")["n"] == 0
    assert review_cells.settle_cell(store, key, unit_id, SEAL, lease_owner=lease)["written"] is False
    assert review_cells.release_expert(store, key, SEAL, lease_owner=lease) == {"released": False, "cells": 0}
    assert review_cells.start_cell(store, key, unit_id, SEAL, lease_owner=lease, input_hash="x") is None
    assert not review_cells.begin_call(store, key, SEAL, lease_owner=lease, call=call)
    assert (_cells(store, key), _head(store, key, SEAL)) == before
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_card_verdicts WHERE target_key = ?", (key,))["n"] == 0
    assert store.query_one("SELECT state FROM rr_review_calls WHERE call_id = ?", (call["call_id"],))["state"] == "aborted"
    assert review_cells.review_invariants(store, key) == []


def test_outcomes_move_the_cell_by_their_class(store):
    """인프라는 차감 없이 pending + 백오프(셀이 다 백오프 중이면 그 전문가를 집지 않는다), 내용 탓은 한도(2)까지 차감한 뒤 failed,
    잡 보류는 차감 없이 pending, 기다림은 셀을 놓지 않고 호출 수에도 세지 않는다. 같은 호출을 두 번 적어도 한 번 센다."""
    key = _target(store)
    unit_id = _unit_ids(store, key)[0]
    live = _running(store, _job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]}))
    frozen = _with_pack(store, live, key, "pack_ok.json")
    lease = review_cells.claim_next_expert(store, live, boot_id=BOOT)["lease_owner"]
    now = now_epoch()

    def run(call_id: str, outcome, **kwargs):
        return review_cells.write_call_result(store, key, SEAL, lease_owner=lease, outcome=outcome, now=now,
                                              call=_call(unit_id, call_id, kind="verdict", state=kwargs.pop("state", "ok"),
                                                         error="사유"), **kwargs)

    _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"])
    assert run("c-wait", review_ops.classify("review_busy"), state="aborted")["cell_state"] == "running"
    assert _cell(store, key, unit_id, SEAL)["tries"] == 0
    assert run("c-ok", None)["cell_state"] == "running"
    assert run("c-ok", None)["cell_state"] == "running"                       # 같은 호출을 다시 적어도
    assert _cell(store, key, unit_id, SEAL)["tries"] == 1                     # 한 번 센다

    assert run("c-infra", review_ops.classify("llm_unreachable"), state="infra_fail")["cell_state"] == "pending"
    cell = _cell(store, key, unit_id, SEAL)
    salt = "|".join((key, unit_id, SEAL))
    assert (cell["infra_streak"], cell["charged"], cell["error_class"], cell["error_code"], cell["lease_owner"]) == (
        1, 0, "infra", "llm_unreachable", None)
    assert cell["not_before"] == now + review_ops.backoff_s(1, salt=salt)
    assert review_cells.release_expert(store, key, SEAL, lease_owner=lease)["released"]
    assert review_cells.claim_next_expert(store, live, boot_id=BOOT, now=now) is None     # 그 셀이 백오프 중이다
    head = review_cells.claim_next_expert(store, live, boot_id=BOOT, now=cell["not_before"])
    lease = head["lease_owner"]

    _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"])
    assert run("c-job", review_ops.classify("credential_expired"), state="content_fail")["cell_state"] == "pending"
    assert (_cell(store, key, unit_id, SEAL)["charged"], _cell(store, key, unit_id, SEAL)["error_class"]) == (0, "job")
    _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"])
    assert run("c-bad1", review_ops.classify("no_rows"), state="content_fail")["cell_state"] == "pending"
    assert _cell(store, key, unit_id, SEAL)["charged"] == 1
    _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"])
    assert run("c-bad2", review_ops.classify("no_rows"), state="content_fail")["cell_state"] == "failed"
    cell = _cell(store, key, unit_id, SEAL)
    # 연속 인프라 실패는 성공해야 0 이 된다(내용 탓·잡 보류는 그 수를 건드리지 않는다).
    assert (cell["state"], cell["charged"], cell["error_code"], cell["tries"], cell["infra_streak"]) == (
        "failed", 2, "no_rows", 5, 1)
    assert review_cells.review_invariants(store, key) == []


def test_settling_needs_every_card_no_truncation_and_the_off_card_call(store):
    """정산 — 판정 카드가 계획보다 적거나, 절단이 남았거나, 카드 밖 호출이 끝나지 않았으면 reviewed 가 아니다. 더 부를 호출이 있으면
    그대로 두고, 없으면 내용 탓으로 센다. 절단을 모르면(NULL) 막지 않는다(X1-22)."""
    key = _target(store)
    unit_id = _unit_ids(store, key)[0]
    live = _running(store, _job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]}))
    frozen = _with_pack(store, live, key, "pack_ok.json")
    lease = review_cells.claim_next_expert(store, live, boot_id=BOOT)["lease_owner"]
    _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"])
    call, rows = _verdicts(store, key, unit_id, frozen, own_refs=True)
    review_cells.write_call_result(store, key, SEAL, lease_owner=lease, call=call, verdicts=rows[:5],
                                   cell={"basis": "cards", "cards_expected": 8, "truncated": 1})
    out = review_cells.settle_cell(store, key, unit_id, SEAL, lease_owner=lease, more_calls=True)
    assert out == {"written": True, "state": "running",
                   "missing": ["cards_unjudged", "output_truncated", "offcard_incomplete"]}
    out = review_cells.settle_cell(store, key, unit_id, SEAL, lease_owner=lease, samples_done=False)
    assert (out["state"], out["code"]) == ("pending", "cards_unjudged")
    assert _cell(store, key, unit_id, SEAL)["charged"] == 1

    _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"])
    review_cells.write_call_result(store, key, SEAL, lease_owner=lease, call={**call, "call_id": "rc-again"},
                                   verdicts=rows, cell={"truncated": None, "offcard_state": "done"})
    assert review_cells.settle_cell(store, key, unit_id, SEAL, lease_owner=lease) == {"written": True,
                                                                                      "state": "reviewed"}
    assert review_cells.review_invariants(store, key) == []


def test_a_cell_whose_input_changed_starts_over_and_one_that_did_not_keeps_its_verdicts(store):
    """셀 입력의 지문(unit_hash | evidence_sha | pack_hash | prompt_rev | limits_rev)이 같으면 다시 시작해도 판정이 남고, 다르면
    그 셀의 판정 행과 셈을 비우고 처음부터 돈다(reopened_n + 1)."""
    key = _target(store)
    unit_id = _unit_ids(store, key)[0]
    live = _running(store, _job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]}))
    frozen = _with_pack(store, live, key, "pack_ok.json")
    lease = review_cells.claim_next_expert(store, live, boot_id=BOOT)["lease_owner"]

    def verdict_n() -> int:
        return store.query_one("SELECT COUNT(*) AS n FROM rr_card_verdicts WHERE target_key = ?", (key,))["n"]

    _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"])
    call, rows = _verdicts(store, key, unit_id, frozen, own_refs=True)
    review_cells.write_call_result(store, key, SEAL, lease_owner=lease, call=call, verdicts=rows,
                                   cell={"cards_expected": 8})
    review_cells.write_call_result(store, key, SEAL, lease_owner=lease, call=_call(unit_id, "rc-x", state="infra_fail"),
                                   outcome=review_ops.classify("engine_stream_cut"))
    assert verdict_n() == 8 and _cell(store, key, unit_id, SEAL)["cards_judged"] == 8
    _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"])
    cell = _cell(store, key, unit_id, SEAL)
    assert (verdict_n(), cell["reopened_n"], cell["cards_judged"], cell["infra_streak"]) == (8, 0, 8, 1)
    review_cells.write_call_result(store, key, SEAL, lease_owner=lease, call=_call(unit_id, "rc-y", state="infra_fail"),
                                   outcome=review_ops.classify("engine_stream_cut"))
    _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"], prompt_rev="p2")
    cell = _cell(store, key, unit_id, SEAL)
    assert (verdict_n(), cell["reopened_n"], cell["cards_judged"], cell["cards_expected"], cell["tries"],
            cell["infra_streak"], cell["prompt_rev"]) == (0, 1, None, None, 0, 0, "p2")


def test_a_verdict_must_belong_to_the_call_and_the_writer_takes_no_unknown_column(store):
    """저장된 판정의 카드는 그 호출에 실은 카드다(나갈 기준 2) — 싣지 않은 카드의 판정·모르는 열·상태 열은 쓰기 전에 거절하고
    아무것도 남기지 않는다."""
    key = _target(store)
    unit_id = _unit_ids(store, key)[0]
    live = _running(store, _job(store, key, scope={"agents": [SEAL], "unit_ids": [unit_id]}))
    frozen = _with_pack(store, live, key, "pack_ok.json")
    lease = review_cells.claim_next_expert(store, live, boot_id=BOOT)["lease_owner"]
    _start(store, key, unit_id, lease, pack_hash=frozen["pack_hash"])
    call, rows = _verdicts(store, key, unit_id, frozen, own_refs=True)
    for bad in ({**call, "cards_json": json.dumps(["K01"])}, {**call, "nonsense": 1}):
        with pytest.raises(ValueError):
            review_cells.write_call_result(store, key, SEAL, lease_owner=lease, call=bad, verdicts=rows)
    with pytest.raises(ValueError):
        review_cells.write_call_result(store, key, SEAL, lease_owner=lease, call=call, cell={"state": "reviewed"})
    with pytest.raises(ValueError):
        review_cells.write_call_result(store, key, SEAL, lease_owner=lease, call=call, head={"lease_owner": "x"})
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_review_calls WHERE target_key = ?", (key,))["n"] == 0
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_card_verdicts WHERE target_key = ?", (key,))["n"] == 0


def test_a_new_job_reopens_experts_that_still_have_cells_in_its_scope(store):
    """앞 잡이 남긴 범위 밖 셀은 다음 잡의 범위가 다시 연다 — 마감된(partial) 전문가는 planned 로, 묶음을 못 받은(blocked) 전문가는
    묶음 시도 수를 비우고 planned 로 돌아온다. 이미 종결된 셀은 다시 돌지 않는다(잡 id 도 앞 잡 것이 남는다)."""
    key = _target(store)
    unit_ids = _unit_ids(store, key)
    first = _job(store, key, scope={"agents": [SEAL, "sim-syn-0"], "unit_ids": unit_ids[:1]})
    live = _running(store, first)
    frozen = _with_pack(store, live, key, "pack_empty.json")
    lease = review_cells.claim_next_expert(store, live, boot_id=BOOT)["lease_owner"]
    _review_unit(store, key, unit_ids[0], lease, frozen)
    # S9 의 마감이 하는 전이 — 범위 밖 pending 이 남은 채 마감한 전문가는 partial 이다(P-04).
    assert review_cells._move(store, "expert", "running", "partial", where="target_key = ? AND agent_key = ?"
                              " AND lease_owner = ?", params=(key, SEAL, lease), sets={"lease_owner": None}) == 1
    sim = review_cells.claim_next_expert(store, live, boot_id=BOOT, purpose="pack")
    review_cells.record_pack(store, key, "sim-syn-0", lease_owner=sim["lease_owner"], status="error",
                             error="card_fetch_failed", not_before=now_epoch() + 60)
    assert review_cells._move(store, "expert", "running", "blocked", where="target_key = ? AND agent_key = ?",
                              params=(key, "sim-syn-0"), sets={"lease_owner": None}) == 1
    _stop(store, live)

    second = _job(store, key, scope={"agents": [SEAL, "sim-syn-0"]})
    seal, sim = _head(store, key, SEAL), _head(store, key, "sim-syn-0")
    assert (seal["state"], seal["run_id"]) == ("planned", second["job_id"])
    assert (sim["state"], sim["pack_attempts"], sim["not_before"], sim["pack_status"]) == ("planned", 0, None, "error")
    reviewed = _cell(store, key, unit_ids[0], SEAL)
    assert (reviewed["state"], reviewed["run_id"]) == ("reviewed", first["job_id"])
    assert {c["run_id"] for c in _cells(store, key) if c["agent_key"] == SEAL and c["state"] == "pending"} == {
        second["job_id"]}


# ---------------------------------------------------------------- 검토 잡 만들기 — 반환·잡 행·자격
def test_the_job_row_carries_its_scope_knobs_and_the_user_credential(store):
    """반환 모양과 잡 행 — mode reviews · tier 없음 · queued · 범위 · 동의 출처 · 사용자 PAT 자격 · 실행 설정 사본(dual_rate 1.0 ·
    훑기 켬 · 거르기 손잡이와 표본 비율 · 변경 → 영역 표의 판과 만들 때의 승인 여부 · 내용 탓 한도 · 표본 소금). 패널 원장
    (rr_coverage)은 건드리지 않는다."""
    key = _target(store)
    before = [tuple(r) for r in store.query("SELECT * FROM rr_coverage WHERE target_key = ? ORDER BY agent_key", (key,))]
    out = _job(store, key, scope={"domains": ["mech", "sim"], "tiers": ["A"]}, user_memo="메모")
    assert set(out) == {"job_id", "mode", "cells_total", "cells_in_scope", "experts_in_scope", "units", "calls_estimate",
                        "credential", "undeferred"}          # 푼 보류 좌석 수(재설계 M3 C3-2)
    assert (out["mode"], out["experts_in_scope"]) == ("reviews", 2)
    assert out["calls_estimate"] == review_runner.calls_estimate(out["cells_in_scope"], 2)
    assert out["credential"]["kind"] == "owner" and out["credential"]["email"] == OWNER
    row = dict(store.query_one("SELECT * FROM rr_jobs WHERE id = ?", (out["job_id"],)))
    assert (row["mode"], row["tier"], row["state"], row["credential_email"], row["concurrency"]) == (
        "reviews", None, "queued", OWNER, config.settings.risk_review_concurrency)
    params = json.loads(row["params_json"])
    assert params["scope"] == {"tiers": ["A"], "domains": ["mech", "sim"]}
    assert (params["user_memo"], params["consent"], params["consent_source"], params["requester"]) == (
        "메모", True, "web", OWNER)
    assert params["knobs"] == {"dual_rate": 1.0, "sweep": "on", "filter": config.settings.risk_review_filter,
                               "audit_pct": config.settings.risk_filter_audit_pct,
                               "routing_rev": relevance.routing_rev(), "routing_approved": relevance.routing_approved(),
                               "max_charged": config.settings.risk_review_max_charged,
                               "sample_salt": review_verify.SAMPLE_SALT}
    assert (params["knobs"]["filter"], params["knobs"]["audit_pct"], params["knobs"]["routing_approved"]) == ("on", 5, False)
    assert params["credential"] == out["credential"] and json.loads(row["progress_json"])["mode"] == "reviews"
    assert [tuple(r) for r in store.query("SELECT * FROM rr_coverage WHERE target_key = ? ORDER BY agent_key",
                                          (key,))] == before


def test_the_review_credential_is_a_user_pat_and_never_the_service_pat(store):
    """자격은 요청자 → 소유자의 사용자 PAT 만이고 남은 수명이 검토 여유(호출 벽시계 + 600초)를 넘어야 한다. 서비스 PAT 가 있어도
    쓰지 않고 422 pat_unavailable 이다(사용자 결정 3). 요청자 PAT 를 수명 때문에 건너뛰었거나, 높은 끝 추정 소요가 PAT 수명보다
    길면 credential_note 로 미리 말한다."""
    key = _target(store)
    (config.settings.data_dir / "secrets.env").write_text("HWAXRISK_PORTAL_PAT=svc-pat\n", encoding="utf-8")
    assert config.load_secrets(config.settings.data_dir).get("HWAXRISK_PORTAL_PAT") == "svc-pat"

    def make(**kwargs):                         # 범위는 전원(이 로스터에는 입력 결손 전문가가 없다) — 호출 추정이 크다
        return review_runner.create_review_job(store, key, owner_sub=OWNER, consent=True, settings=config.settings,
                                               **kwargs)

    refused = _refused(make)
    assert (refused.code, refused.http_status) == ("pat_unavailable", 422) and "등록된 포털 PAT 가 없다" in refused.message
    margin = config.review_credential_margin_s(config.settings)
    _pat(store, OWNER, life_s=margin - 60)
    refused = _refused(make)
    assert refused.code == "pat_unavailable" and "검토 여유" in refused.message
    _pat(store, PEER, life_s=margin - 60)
    _pat(store, OWNER, life_s=margin + 120)
    out = make(requester_sub=PEER)
    assert out["credential"]["kind"] == "owner" and out["credential"]["email"] == OWNER
    assert f"{PEER} 의 PAT" in out["credential_note"]                  # 요청자 PAT 를 건너뛰었다
    assert "credential 로 멈춘다" in out["credential_note"]           # 남은 수명이 높은 끝 추정 소요보다 짧다
    runner.cancel_job(store, out["job_id"], by=OWNER)
    _pat(store, PEER)
    out = make(requester_sub=PEER)
    assert out["credential"]["kind"] == "requester" and out["credential"]["email"] == PEER and "credential_note" not in out


# ---------------------------------------------------------------- 거절
def test_refusals_for_switch_target_units_and_live_jobs(store, monkeypatch):
    """꺼진 스위치(409 review_disabled) · 없는 대상(404) · 단위가 서지 않은 대상(422 units_absent) · 살아 있는 검토 잡(409
    review_job_exists — 취소하면 다시 만든다) · 살아 있는 패널 잡(409 panel_job_running)."""
    key = _target(store, flow="panels")
    _pat(store)

    def make(target=key, **kwargs):
        return review_runner.create_review_job(store, target, owner_sub=OWNER, scope={"agents": [SEAL]}, consent=True,
                                               settings=config.settings, **kwargs)

    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_enabled=False))
    refused = _refused(make)
    assert (refused.code, refused.http_status, refused.detail["knob"]) == ("review_disabled", 409,
                                                                            "HWAXRISK_REVIEW_ENABLED")
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_enabled=True))
    assert _refused(make, "diff:none").http_status == 404
    refused = _refused(make)
    assert (refused.code, refused.http_status, refused.detail["units"]["status"]) == ("units_absent", 422, "none")
    routes.post_units(key, routes.UnitsBody(), ident=factories.ident(OWNER))
    first = make()
    refused = _refused(make)
    assert (refused.code, refused.http_status, refused.detail["job_id"]) == ("review_job_exists", 409, first["job_id"])
    runner.cancel_job(store, first["job_id"], by=OWNER)
    second = make()
    runner.cancel_job(store, second["job_id"], by=OWNER)
    panel = runner.create_job(store, key, "A", owner_sub=OWNER, settings=config.settings)
    refused = _refused(make)
    assert (refused.code, refused.http_status, refused.detail["job_id"]) == ("panel_job_running", 409, panel["job_id"])
    runner.pause_job(store, panel["job_id"], by=OWNER)
    assert _refused(make).code == "panel_job_running"                  # 멈춘 패널 잡도 살아 있다
    runner.cancel_job(store, panel["job_id"], by=OWNER)
    assert make()["mode"] == "reviews"


def test_refusals_for_scope_and_call_budget(store, monkeypatch):
    """범위 — 모르는 칸·목록 아님·빈 목록·대상에 없는 값은 422 scope_invalid, 맞는 셀이 없으면 422 scope_empty. 호출 추정의 높은
    끝이 상한을 넘으면 409 review_too_large, 동의 문턱을 넘는데 consent 가 없으면 422 consent_required. 입력 결손 전문가는 거절하지
    않는다(재설계 M3 C3-2 — 아래 시험)."""
    key = _target(store, agents=factories.agents())
    _pat(store)

    def make(scope, *, consent=True):
        return review_runner.create_review_job(store, key, owner_sub=OWNER, scope=scope, consent=consent,
                                               settings=config.settings)

    for scope, detail in (({"teams": ["x"]}, {"unknown_keys": ["teams"]}), ({"agents": "mech-syn-0"}, {"key": "agents"}),
                          ({"domains": []}, {"key": "domains"}),
                          ({"agents": ["mech-syn-9"]}, {"key": "agents", "values": ["mech-syn-9"]}),
                          ({"unit_ids": ["u-000000000000"]}, {"key": "unit_ids", "values": ["u-000000000000"]}),
                          ({"tiers": ["D"]}, {"key": "tiers", "values": ["D"]})):
        refused = _refused(make, scope)
        assert (refused.code, refused.http_status, refused.detail) == ("scope_invalid", 422, detail), scope
    refused = _refused(make, {"tiers": ["A"], "agents": ["mech-syn-1"]})
    assert (refused.code, refused.http_status, refused.detail["experts"]) == ("scope_empty", 422, 0)

    scope = {"domains": ["mech"]}
    high = review_runner.calls_estimate(2 * len(_unit_ids(store, key)), 2)["high"]
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_max_calls=high - 1))
    refused = _refused(make, scope)
    assert (refused.code, refused.http_status, refused.detail["calls_estimate"]["high"]) == ("review_too_large", 409, high)
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_max_calls=high,
                                                               risk_review_consent_calls=high - 1))
    refused = _refused(make, scope, consent=False)
    assert (refused.code, refused.http_status, refused.detail["knob"]) == ("consent_required", 422,
                                                                            "HWAXRISK_REVIEW_CONSENT_CALLS")
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_review_cells WHERE target_key = ?", (key,))["n"] == 0
    assert make(scope)["calls_estimate"]["high"] == high


# ---------------------------------------------------------------- 전원 포함 · 보류 해제(재설계 M3 C3-2)
def _undefer_audits(store, key: str) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT actor, actor_verified, channel, scope, subject_id, action, after_json, reason FROM rr_audit"
        " WHERE subject_id = ? AND action = 'coverage.undefer' ORDER BY at", (key,))]


def test_input_gap_experts_join_the_scope_and_their_deferred_seats_open_with_the_job(store):
    """ECAD 에 기대는데 ECAD 가 없는 전문가도 범위에 든다(422 input_gap_m3 는 없다). 카드 대조 대상이면 범위 안의 보류(deferred ·
    ecad_absent) 좌석이 잡을 만드는 트랜잭션에서 pending 으로 풀리고 감사 한 행(coverage.undefer · review_scope)이 남는다 — 풀지
    않으면 원장 마감이 그 행을 건드리지 않아 종결 어휘(deferred)로 남는다(거짓 완결)."""
    key = _target(store, agents=factories.agents())          # pcb-syn-0 은 입력 결손 1순위, pcb-syn-1 은 보류 좌석
    order = planner.review_order(store, key)
    assert {r["agent_key"] for r in order if r["input_gaps"]} == {"pcb-syn-0", "pcb-syn-1"}
    assert _coverage(store, key, "pcb-syn-1")["status"] == "deferred"

    job = _job(store, key)                                     # 범위를 빼면 로스터 전원이다
    assert (job["experts_in_scope"], job["undeferred"]) == (len(order), 1)
    seat = dict(store.query_one("SELECT status, reason, status_source, decided_by FROM rr_coverage WHERE target_key = ?"
                                " AND agent_key = 'pcb-syn-1'", (key,)))
    assert seat == {"status": "pending", "reason": None, "status_source": "human", "decided_by": OWNER}
    assert {c["agent_key"] for c in _cells(store, key) if c["run_id"] == job["job_id"]} == {r["agent_key"] for r in order}
    audits = _undefer_audits(store, key)
    assert len(audits) == 1
    audit = audits[0]
    assert (audit["actor"], audit["actor_verified"], audit["channel"], audit["scope"], audit["reason"]) == (
        OWNER, 1, "rest", "coverage", "review_scope")
    assert json.loads(audit["after_json"])["agents"] == ["pcb-syn-1"] and json.loads(audit["after_json"])["n"] == 1
    assert planner.check_invariants(store, key) == []


def test_only_deferred_seats_in_the_scope_open_and_panel_targets_keep_theirs(store):
    """범위 밖의 보류는 그대로다(감사도 없다). 패널 대상에 얹은 검토는 보류를 풀지 않는다 — 원장을 닫지 않는 길이고 패널 편성이
    바뀐다(M2.md 5절 #8). 사람이 원하면 REST 로 푼다."""
    key = _target(store, agents=factories.agents())
    job = _job(store, key, scope={"domains": ["mech"]})
    assert job["undeferred"] == 0 and _coverage(store, key, "pcb-syn-1")["status"] == "deferred"
    assert _undefer_audits(store, key) == []

    panels = _target(store, agents=factories.agents(), flow="panels", seed=7)
    units.build_units(store, panels, built_by=OWNER, reason="패널 대상에 얹은 검토")
    out = _job(store, panels, scope={"domains": ["pcb"]})
    assert out["undeferred"] == 0 and _coverage(store, panels, "pcb-syn-1")["status"] == "deferred"


def test_the_undefer_route_needs_a_reason_waits_for_live_jobs_and_says_the_level_does_not_drop(store):
    """POST /targets/{key}/undefer — 사유 4~300자(422 reason_required), 도는 잡이 있으면 409 job_live, 바꿀 것이 없으면 200 changed:false.
    푼 좌석과 감사 한 행이 남고, 응답은 저장된 레벨이 내려가지 않는다는 것과 영역 깊이를 싣는다."""
    key = _target(store, agents=factories.agents(), flow="panels")
    body = routes.UndeferBody(reason="회로 전문가도 패널에 앉힌다")
    me = factories.ident(OWNER)
    for reason in ("", "짧다", "x" * 301):
        assert _refused(routes.post_undefer, key, routes.UndeferBody(reason=reason), ident=me).code == "reason_required"
    units.build_units(store, key, built_by=OWNER, reason="패널 대상에 얹은 검토")
    job = _job(store, key, scope={"domains": ["mech"]})
    refused = _refused(routes.post_undefer, key, body, ident=me)
    assert (refused.code, refused.http_status, refused.detail["jobs"][0]["id"]) == ("job_live", 409, job["job_id"])
    runner.cancel_job(store, job["job_id"], by=OWNER)

    out = routes.post_undefer(key, body, ident=me)
    assert (out["undeferred"], out["agents"], out["agents_total"], out["changed"]) == (1, ["pcb-syn-1"], 1, True)
    assert "내려가지 않는다" in out["note"] and "pcb" in out["depth"]
    assert _coverage(store, key, "pcb-syn-1")["status"] == "pending"
    again = routes.post_undefer(key, body, ident=me)
    assert (again["undeferred"], again["changed"]) == (0, False)
    audits = _undefer_audits(store, key)
    assert [(a["channel"], a["reason"], a["actor_verified"]) for a in audits] == [("rest", body.reason, 1)]
    delegated = identity.Identity(email=OWNER, display_name="합성", role="user", organization="qa", anonymous=False,
                                  source="sso")
    seeded = _target(store, agents=factories.agents(), flow="panels", seed=8)
    routes.post_undefer(seeded, body, ident=delegated)
    assert [(a["channel"], a["actor_verified"]) for a in _undefer_audits(store, seeded)] == [("mcp", 0)]


def test_a_carried_revert_does_not_open_a_deferred_seat(store):
    """보류는 undefer 한 문으로만 풀린다 — 이월 되돌리기(PUT coverage status=pending)는 보류 좌석에 409 다."""
    key = _target(store, agents=factories.agents(), flow="panels")
    refused = _refused(planner.revert_carried, store, key, "pcb-syn-1")
    assert (refused.code, refused.http_status) == ("E100", 409)
    assert _coverage(store, key, "pcb-syn-1")["status"] == "deferred"


def test_a_target_whose_panel_awaits_repersist_refuses_a_review_job(store, monkeypatch):
    """다시 저장을 기다리는 패널이 있는 대상은 409 repersist_pending 이다 — 검토 마감이 그 패널이 pending 으로 돌려 둔 좌석을 닫으면
    다시 저장이 seats_moved 로 영영 막힌다(RR-ADV-1). 상태는 M1 의 persist_error 길(등록부 병합이 터진 패널)로 만든다."""
    from app import registry
    from tests.rr.test_panel_ledger import LedgerEngine

    def refused_http(*args, **_kwargs):
        raise httpx.ConnectError("시험은 외부를 부르지 않는다.", request=args[-1])

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refused_http)

    def merge_panel(_store, _panel_id):
        raise RuntimeError("디스크가 찼다")

    monkeypatch.setattr(registry, "merge_panel", merge_panel)
    key = _target(store, flow="panels")
    routes.post_units(key, routes.UnitsBody(), ident=factories.ident(OWNER))
    _pat(store)
    job = runner.create_job(store, key, "A", owner_sub=OWNER, settings=config.settings)
    out = runner.run_panel(store, config.settings, LedgerEngine(), runner.claim_next_job(store, config.settings))
    assert out["status"] == "error" and out["error"].startswith(runner.PERSIST_ERROR_CODE), out
    runner.cancel_job(store, job["job_id"], by=OWNER)                  # 멈춘 패널 잡을 치워도
    assert [p["id"] for p in runner.awaiting_repersist(store, key)] == [out["panel_id"]]
    refused = _refused(review_runner.create_review_job, store, key, owner_sub=OWNER, scope={"agents": [SEAL]},
                       consent=True, settings=config.settings)
    assert (refused.code, refused.http_status, refused.detail["panels"]) == ("repersist_pending", 409, [out["panel_id"]])
    runner.abandon_repersist(store, out["panel_id"])
    assert _job(store, key, scope={"agents": [SEAL]})["mode"] == "reviews"
