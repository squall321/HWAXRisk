# 요구 여유의 상태 — 동결이 요구를 대조해 rr_states 에 싣고(sig:req.margin · missing.req_*) 요구를 고치면 그 과제 스냅샷의 상태를 다시 센다(plan §2.8b · P1 (20))
"""종전에는 동결(`ir_builder.freeze_snapshot`)이 `build_state(ir)` 만 불러 요구를 대조하지 않았고, 요구를 고쳐도 아무 곳도
`compute_state_for_snapshot` 을 부르지 않아 스냅샷 화면의 요구 여유 표가 늘 비었다(화면 세션 FE-11 · FE-14 청할 것 4 · BE-10).
입력은 생산자다 — 과제 · 치수는 라우트, 스냅샷은 `freeze_snapshot`, 요구는 REST 라우트(등록 · 상태 · 승계)다.
"""
from __future__ import annotations

import json
import threading

import pytest

from app import routes
from app import state as state_module
from tests import factories

OWNER = factories.OWNER
DIMS = {  # 이름 → 추출식(어댑터 픽스처의 plate_1 은 1.2 mm · plate_2 는 1.0 mm — test_req_brief 와 같다)
    "plate1_t": "node[asm=a_stack/stack_asm/plate_1].attrs.min_dim",
    "plate2_t": "node[asm=a_stack/stack_asm/plate_2].attrs.min_dim",
}
PLATE1_LTE = {"kind": "dim_limit", "name": "plate1_t", "op": "lte", "value_json": 1.0, "unit": "mm"}   # 1.0 − 1.2 = −0.2
PLATE2_GTE = {"kind": "dim_limit", "name": "plate2_t", "op": "gte", "value_json": 0.9, "unit": "mm"}   # 1.0 − 0.9 = +0.1


def _project(store) -> str:
    project_id = factories.make_project(store)
    for name, extractor in DIMS.items():
        factories.make_dim(store, project_id, name, extractor)
    return project_id


def _post(store, project_id: str, items: list[dict]) -> dict:
    with factories.routes_store(store):
        return routes.post_requirements(project_id, [routes.RequirementItem(**i) for i in items], ident=factories.ident(OWNER))


def _margins(store, snapshot_id: str) -> list[tuple[str, float | None, str]]:
    signal = state_module.load_state(store, snapshot_id)["signals"]["req.margin"]
    return [(r["name"], r["margin"], r["status"]) for r in signal["value"]]


def _r007(store, snapshot_id: str):
    return {h["rule"]: h["pass"] for h in state_module.load_state(store, snapshot_id)["rule_hits"]}["R-007"]


def test_freezing_a_snapshot_counts_the_requirement_margins_into_its_state(risk_store):
    """요구를 등록한 뒤 얼린 스냅샷의 상태에 `req.margin` 이 여유 오름차순으로 서고(손으로 센 값), 요구 결측이 아니며 R-007(여유 ≤0)이
    걸린다. 스냅샷 화면이 읽는 `GET /snapshots/{id}?part=state` 가 같은 값이다. 요구는 IR 에 들지 않는다(ir_json 에 req 가 없다)."""
    project_id = _project(risk_store)
    _post(risk_store, project_id, [PLATE2_GTE, PLATE1_LTE])
    snap = factories.make_snapshot(risk_store, project_id, factories.fixture_adapter_results(), label="DV1")
    sid = snap["snapshot_id"]
    assert _margins(risk_store, sid) == [("plate1_t", -0.2, "candidate"), ("plate2_t", 0.1, "candidate")]
    state = state_module.load_state(risk_store, sid)
    assert state["missing"]["req_absent"] is False and state["signals"]["req.margin"]["known"] is True
    assert _r007(risk_store, sid) is False                                    # 위반이 하나 있다(plate1_t)
    with factories.routes_store(risk_store):
        served = routes.snapshot_part(sid, "state", owner_sub=OWNER)
    assert served["signals"]["req.margin"] == state["signals"]["req.margin"]
    ir_json = risk_store.query_one("SELECT ir_json FROM rr_snapshots WHERE id = ?", (sid,))["ir_json"]
    assert "req.margin" not in ir_json and "req_absent" not in ir_json


def test_a_project_without_requirements_freezes_with_an_empty_margin_table_and_req_absent(risk_store):
    """요구 0건 — 표는 빈 표(known=false)이고 missing.req_absent 이며 R-007 은 평가 불가(null)다. 화면은 '요구 미등록' 을 보인다."""
    project_id = _project(risk_store)
    sid = factories.make_snapshot(risk_store, project_id, factories.fixture_adapter_results(), label="DV1")["snapshot_id"]
    state = state_module.load_state(risk_store, sid)
    assert state["signals"]["req.margin"]["value"] == [] and state["signals"]["req.margin"]["known"] is False
    assert state["missing"]["req_absent"] is True and _r007(risk_store, sid) is None


def test_editing_requirements_recounts_every_snapshot_of_the_project_and_keeps_the_gate_acks(risk_store, monkeypatch):
    """요구를 고치면(등록 · 상태 · 승계) 그 과제 스냅샷 전부의 상태를 다시 센다 — ir_json · ir_hash 는 바이트 그대로이고 computed_at 이
    오른다(P1 (20)). 사람이 붙인 게이트 ack 는 다시 센 상태에도 남는다(gates_json 을 통째로 덮어 쓰므로 빼면 사라진다). 다른 과제의
    스냅샷은 건드리지 않는다."""
    project_id = _project(risk_store)
    first = factories.make_snapshot(risk_store, project_id, factories.fixture_adapter_results(), label="DV1")["snapshot_id"]
    results = factories.fixture_adapter_results()
    factories.set_thickness(results, "PLATE_2", 0.8)                           # 두 번째 스냅샷의 plate_2 는 0.8 mm
    second = factories.make_snapshot(risk_store, project_id, results, label="DV2")["snapshot_id"]
    other_project = _project(risk_store)
    other = factories.make_snapshot(risk_store, other_project, factories.fixture_adapter_results(), label="DV1")["snapshot_id"]
    with factories.routes_store(risk_store):
        ack = routes.post_gate_ack(first, "G3", routes.GateAckBody(reason="간섭은 다음 리비전에서 확정한다"),
                                   ident=factories.ident(OWNER))
    before = {sid: dict(risk_store.query_one("SELECT ir_json, ir_hash FROM rr_snapshots WHERE id = ?", (sid,)))
              for sid in (first, second)}
    computed = {sid: risk_store.query_one("SELECT computed_at FROM rr_states WHERE snapshot_id = ?", (sid,))["computed_at"]
                for sid in (first, second, other)}
    later = max(computed.values()) + 10
    monkeypatch.setattr(state_module, "now_epoch", lambda: later)

    _post(risk_store, project_id, [PLATE1_LTE, PLATE2_GTE])                     # 등록
    assert _margins(risk_store, first) == [("plate1_t", -0.2, "candidate"), ("plate2_t", 0.1, "candidate")]
    assert [(n, m) for n, m, _ in _margins(risk_store, second)] == [("plate1_t", -0.2), ("plate2_t", -0.1)]
    assert _r007(risk_store, first) is False
    for sid in (first, second):
        row = risk_store.query_one("SELECT ir_json, ir_hash FROM rr_snapshots WHERE id = ?", (sid,))
        assert dict(row) == before[sid]                                          # 요구는 IR 을 바꾸지 않는다
        assert risk_store.query_one("SELECT computed_at FROM rr_states WHERE snapshot_id = ?", (sid,))["computed_at"] == later
    assert risk_store.query_one("SELECT computed_at FROM rr_states WHERE snapshot_id = ?", (other,))["computed_at"] == \
        computed[other]                                                          # 다른 과제는 그대로
    gates = json.loads(risk_store.query_one("SELECT gates_json FROM rr_states WHERE snapshot_id = ?", (first,))["gates_json"])
    assert (gates["G3"]["ack_by"], gates["G3"]["ack_at"], gates["G3"]["ack_reason"]) == (
        OWNER, ack["ack_at"], "간섭은 다음 리비전에서 확정한다")
    assert state_module.gates_hash(gates) == ack["gates_hash"]                  # 판정은 그대로라 ack 는 낡지 않는다
    assert state_module.load_state(risk_store, first)["gates"]["G3"]["ack_by"] == OWNER

    with factories.routes_store(risk_store):                                    # 상태 — waived 는 대조하지 않는다
        listed = routes.get_requirements(project_id, ident=factories.ident(OWNER))["requirements"]
        plate1 = next(r for r in listed if r["name"] == "plate1_t")
        routes.put_requirement(plate1["id"], routes.RequirementDecision(status="waived", waive_reason="다음 판에서 보강"),
                               ident=factories.ident(OWNER))
    assert [n for n, _, _ in _margins(risk_store, first)] == ["plate2_t"]
    assert _r007(risk_store, first) is True                                     # 남은 요구는 여유가 있다

    with factories.routes_store(risk_store):                                    # 승계 — 원본 과제의 요구가 들어온다
        routes.post_requirements(other_project, [routes.RequirementItem(**PLATE1_LTE)], ident=factories.ident(OWNER))
        fresh = _project(risk_store)
        sid = factories.make_snapshot(risk_store, fresh, factories.fixture_adapter_results(), label="DV1")["snapshot_id"]
        assert _margins(risk_store, sid) == []
        routes.post_requirements_inherit(fresh, routes.InheritBody(from_project_id=other_project),
                                         ident=factories.ident(OWNER))
    assert _margins(risk_store, sid) == [("plate1_t", -0.2, "candidate")]


def test_a_requirement_saved_while_a_snapshot_freezes_lands_in_that_snapshots_state(risk_store, monkeypatch):
    """동결이 요구 원장을 읽은 뒤 스냅샷을 넣기 전에 다른 요청(다른 스레드)이 요구를 저장해도 새 스냅샷의 상태에 그 요구가 선다 — 원장
    읽기와 스냅샷 넣기가 한 트랜잭션이라 요구 편집(같은 트랜잭션에서 그 과제 스냅샷을 다시 센다)과 줄을 선다(반대 검토 10-31). 종전에는
    원장을 트랜잭션 앞에서 읽어, 그 틈에 커밋된 요구는 아직 없는 새 스냅샷을 다시 세지 못했고 그 스냅샷의 req.margin · R-007 이 다음 요구
    편집까지 낡았다."""
    project_id = _project(risk_store)
    _post(risk_store, project_id, [PLATE2_GTE])
    real = state_module.build_state
    editors: list[threading.Thread] = []
    errors: list[BaseException] = []

    def save_requirement() -> None:
        try:
            _post(risk_store, project_id, [PLATE1_LTE])
        except BaseException as exc:  # noqa: BLE001 — 시험 스레드의 실패를 본 스레드로 넘긴다
            errors.append(exc)

    def edit_in_between(ir, **kwargs):
        # 동결의 freeze_state 가 원장을 읽은(req 를 센) 뒤 상태를 짓기 전이다 — 첫 부름 한 번만 다른 요청을 끼운다. 그 요청이 동결의
        # 트랜잭션 잠금에 막히면(고친 뒤) 기다림이 시간을 넘기고 동결이 이어 간다.
        if not editors:
            editors.append(threading.Thread(target=save_requirement))
            editors[0].start()
            editors[0].join(timeout=1.0)
        return real(ir, **kwargs)

    monkeypatch.setattr(state_module, "build_state", edit_in_between)
    sid = factories.make_snapshot(risk_store, project_id, factories.fixture_adapter_results(), label="DV1")["snapshot_id"]
    editors[0].join(timeout=30)
    assert not editors[0].is_alive() and errors == []
    assert _margins(risk_store, sid) == [("plate1_t", -0.2, "candidate"), ("plate2_t", 0.1, "candidate")]
    assert _r007(risk_store, sid) is False


def test_a_refused_requirement_edit_recounts_nothing(risk_store, monkeypatch):
    """검사에 걸린 요구 편집(422 · 400)은 아무 행도 쓰지 않고 상태도 다시 세지 않는다 — 요구 원장과 상태가 한 트랜잭션이다."""
    project_id = _project(risk_store)
    sid = factories.make_snapshot(risk_store, project_id, factories.fixture_adapter_results(), label="DV1")["snapshot_id"]
    before = risk_store.query_one("SELECT computed_at, state_json FROM rr_states WHERE snapshot_id = ?", (sid,))
    monkeypatch.setattr(state_module, "now_epoch", lambda: int(before["computed_at"]) + 10)
    from app.errors import AppError

    with pytest.raises(AppError) as refused:
        _post(risk_store, project_id, [PLATE1_LTE, {**PLATE2_GTE, "unit": "cm"}])
    assert refused.value.code == "unit_mismatch"
    after = risk_store.query_one("SELECT computed_at, state_json FROM rr_states WHERE snapshot_id = ?", (sid,))
    assert dict(after) == dict(before)
