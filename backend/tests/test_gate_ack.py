# 게이트 ack 라우트(POST·DELETE)와 409 gate_blocked 기계 판독 계약 시험 — plan §3.2.2·§8.2.3·§2.12
from __future__ import annotations

import json

import pytest

from app import common, routes, state as st
from app.errors import AppError

OWNER = "owner@example.com"


def _ident(email: str | None = OWNER):
    return type("I", (), {"anonymous": email is None, "email": email,
                          "to_dict": lambda self: {"email": email}})()


def _seed_snapshot(store, snapshot_id: str, gates: dict, *, blocked: int = 0) -> None:
    now = common.now_epoch()
    store.execute(
        "INSERT OR IGNORE INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
        " VALUES ('p1', ?, 'PRJ-1', '게이트 과제', ?, ?)", (OWNER, now, now))
    store.execute(
        "INSERT INTO rr_snapshots(id, owner_sub, project_id, ir_version, ir_hash, ir_json, source_ids_json,"
        " kinds_json, node_count, edge_count, created_at) VALUES (?, ?, 'p1', '1.0', ?, '{}', '[]', ?, 0, 0, ?)",
        (snapshot_id, OWNER, f"h-{snapshot_id}", json.dumps(["mcad"]), now))
    store.execute(
        "INSERT INTO rr_states(snapshot_id, owner_sub, state_json, feature_json, rule_hits_json,"
        " character_seed_json, gates_json, blocked, computed_at) VALUES (?, ?, '{}', '{}', '[]', '[]', ?, ?, ?)",
        (snapshot_id, OWNER, json.dumps(gates), blocked, now))


def _gates(**overrides) -> dict:
    base = {key: {"key": key, "count": 0, "threshold": 0, "pass": True, "reason": None,
                  "blocking": key == "G6", "effect": "none", "ack_by": None, "ack_at": None,
                  "ack_reason": None, "detail": []} for key in ("G1", "G2", "G3", "G4", "G5", "G6")}
    for key, patch in overrides.items():
        base[key] = {**base[key], **patch}
    return base


# ---------------------------------------------------------------- ack(plan §8.2.3)
def test_ack_records_a_reason_without_flipping_pass(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    gates = _gates(G3={"pass": False, "count": 2, "effect": "mark"})
    _seed_snapshot(risk_store, "s1", gates)

    out = routes.post_gate_ack("s1", "G3", routes.GateAckBody(reason="확인 후 진행"), ident=_ident())
    assert out["ack_by"] == OWNER and out["ack_reason"] == "확인 후 진행"
    assert out["pass"] is False                          # ack 로 판정은 바뀌지 않는다(§3.2.2)

    row = risk_store.query_one("SELECT ack_by, ack_reason, gates_hash, revoked_at FROM rr_gate_acks"
                               " WHERE snapshot_id = 's1' AND gate = 'G3'")
    assert row["ack_by"] == OWNER and row["revoked_at"] is None
    stored = json.loads(risk_store.query_one(
        "SELECT gates_json FROM rr_states WHERE snapshot_id = 's1'")["gates_json"])
    assert stored["G3"]["ack_reason"] == "확인 후 진행" and stored["G3"]["pass"] is False
    assert risk_store.query_one(
        "SELECT COUNT(*) AS n FROM rr_audit WHERE action = 'gate.ack'")["n"] == 1


def test_ack_rejects_passing_blocking_and_empty_reason(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    _seed_snapshot(risk_store, "s2", _gates(G3={"pass": False, "count": 1},
                                            G6={"pass": False, "count": 1, "effect": "block"}), blocked=1)

    with pytest.raises(AppError) as passing:
        routes.post_gate_ack("s2", "G1", routes.GateAckBody(reason="사유"), ident=_ident())
    assert (passing.value.code, passing.value.http_status) == ("gate_passing", 422)

    with pytest.raises(AppError) as blocking:
        routes.post_gate_ack("s2", "G6", routes.GateAckBody(reason="사유"), ident=_ident())
    assert (blocking.value.code, blocking.value.http_status) == ("gate_blocking", 422)

    with pytest.raises(AppError) as empty:
        routes.post_gate_ack("s2", "G3", routes.GateAckBody(reason="   "), ident=_ident())
    assert (empty.value.code, empty.value.http_status) == ("reason_required", 422)


def test_ack_on_unknown_blocking_g6_is_also_refused(risk_store, monkeypatch):
    """unknown_blocking(pass=null)도 ack 대상이 아니다 — 해소는 재캡처뿐이다(§2.12)."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    _seed_snapshot(risk_store, "s3",
                   _gates(G6={"pass": None, "count": None, "reason": "unit_unknown", "effect": "block"}),
                   blocked=1)
    with pytest.raises(AppError) as exc:
        routes.post_gate_ack("s3", "G6", routes.GateAckBody(reason="넘어가겠다"), ident=_ident())
    assert exc.value.code == "gate_blocking"


def test_ack_with_a_stale_gates_hash_is_409(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    _seed_snapshot(risk_store, "s4", _gates(G4={"pass": False, "count": 3}))
    with pytest.raises(AppError) as exc:
        routes.post_gate_ack("s4", "G4", routes.GateAckBody(reason="사유", gates_hash="deadbeef0000"),
                             ident=_ident())
    assert (exc.value.code, exc.value.http_status) == ("gates_hash_stale", 409)


def test_delete_ack_revokes_instead_of_deleting(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    _seed_snapshot(risk_store, "s5", _gates(G5={"pass": False, "count": 4}))
    routes.post_gate_ack("s5", "G5", routes.GateAckBody(reason="범위 밖 리프 확인"), ident=_ident())

    out = routes.delete_gate_ack("s5", "G5", ident=_ident())
    assert out["revoked_by"] == OWNER and out["ack_reason"] is None
    row = risk_store.query_one("SELECT ack_by, revoked_by, revoked_at FROM rr_gate_acks"
                               " WHERE snapshot_id = 's5' AND gate = 'G5'")
    assert row["ack_by"] == OWNER and row["revoked_by"] == OWNER and row["revoked_at"] is not None
    stored = json.loads(risk_store.query_one(
        "SELECT gates_json FROM rr_states WHERE snapshot_id = 's5'")["gates_json"])
    assert stored["G5"]["ack_by"] is None

    with pytest.raises(AppError) as again:
        routes.delete_gate_ack("s5", "G5", ident=_ident())
    assert again.value.http_status == 404


# ---------------------------------------------------------------- 409 gate_blocked(plan §8.2.3)
def test_create_target_on_unknown_blocking_is_gate_blocked_unit_unknown(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    gates = _gates(G6={"pass": None, "count": None, "reason": "unit_unknown", "effect": "block"})
    # `blocked` 열이 0 이어도 gates_json 이 unknown_blocking 이면 차단이다(계산식이 정본, §2.12).
    _seed_snapshot(risk_store, "s6", gates, blocked=0)

    with pytest.raises(AppError) as exc:
        routes.create_target(routes.TargetBody(kind="snap", ref_id="s6", consent=True), ident=_ident())
    assert (exc.value.code, exc.value.http_status) == ("gate_blocked", 409)
    assert exc.value.detail["reason"] == "unit_unknown"
    assert exc.value.to_dict()["error"]["code"] == "gate_blocked"
    assert set(exc.value.to_dict()) == {"error", "gates", "reason"}


def test_blocked_formula_matches_the_plan():
    assert st.is_blocked(_gates(G6={"pass": False})) is True
    assert st.is_blocked(_gates(G6={"pass": None, "reason": "unit_unknown"})) is True
    assert st.is_blocked(_gates(G6={"pass": None, "reason": "unit_only"})) is False
    assert st.is_blocked(_gates()) is False
    assert st.blocked_reason(_gates(G6={"pass": False})) == "unit_mismatch"
