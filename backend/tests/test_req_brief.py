# 요구 대조의 브리프 · 원자 저장 — E0 요구 한 줄 · E3 limit/margin 두 열과 여유 차례 · 여유 ≤0 인 요구의 OK 보정(plan §2.8b · §5.6.1 · P1 (20))
from __future__ import annotations

import json

import pytest

from app import brief, narrative, requirements
from tests import factories

DIMS = {  # 이름 → 추출식(어댑터 픽스처의 plate_1 은 1.2 mm · plate_2 는 1.0 mm)
    "plate1_t": "node[asm=a_stack/stack_asm/plate_1].attrs.min_dim",
    "plate2_t": "node[asm=a_stack/stack_asm/plate_2].attrs.min_dim",
    "plate2_copy_t": "node[asm=a_stack/stack_asm/plate_2].attrs.min_dim",
}


@pytest.fixture
def no_field(monkeypatch):
    from app import field_source

    monkeypatch.setattr(field_source, "for_target", lambda *a, **k: None)


def _item(built: dict, key: str) -> list[str]:
    return built["evidence"][built["keys"].index(key)]["result"].split("\n")[1:]


def _project(store, dims=DIMS) -> str:
    project_id = factories.make_project(store)
    for name, extractor in dims.items():
        factories.make_dim(store, project_id, name, extractor)
    return project_id


def _snap_target(store, project_id: str, results=None, *, label: str = "DV1") -> tuple[str, dict]:
    snap = factories.make_snapshot(store, project_id, results or factories.fixture_adapter_results(), label=label)
    key = factories.make_target(store, "snap", snap["snapshot_id"], agents=factories.agents())
    return key, snap


def _requirements(store, project_id: str, items) -> None:
    requirements.upsert_requirements(store, project_id, factories.OWNER, items)


# ---------------------------------------------------------------- E0 요구 한 줄
def test_e0_says_no_requirements_when_the_project_has_none(risk_store, no_field):
    """요구 0건 과제의 E0 는 `요구 미등록` 한 줄을 싣는다 — 좌석 계약이 판정 옆에 '내 경험 기준' 을 적게 하는 신호다(§2.8b (4))."""
    key, _ = _snap_target(risk_store, _project(risk_store))
    e0 = _item(brief.build_brief(risk_store, key, strict_lint=True), "E0")
    assert "요구 미등록" in e0, e0
    # 짧고 E0 에만 있는 줄이라 소스 id 줄보다 앞이다 — 상한에 걸리면 소스 줄이 먼저 잘린다.
    assert e0.index("요구 미등록") < next(i for i, line in enumerate(e0) if line.startswith("소스 "))


def test_e0_summarises_dim_limits_with_the_smallest_margin_and_scenarios(risk_store, no_field):
    """`요구 dim_limit n · 최소 여유 ±m 단위 [req:<이름>] · 시나리오 a/b` — 여유는 손으로 센 값과 같다."""
    project_id = _project(risk_store)
    _requirements(risk_store, project_id, [
        {"kind": "dim_limit", "name": "plate1_t", "op": "lte", "value_json": 1.0, "unit": "mm"},   # 1.0 − 1.2 = −0.2
        {"kind": "dim_limit", "name": "plate2_t", "op": "gte", "value_json": 0.9, "unit": "mm"},   # 1.0 − 0.9 = +0.1
        {"kind": "scenario", "name": "drop_corner", "value_json": {"taxonomy_key": "deep", "required": True}},
    ])
    key, _ = _snap_target(risk_store, project_id)
    e0 = _item(brief.build_brief(risk_store, key, strict_lint=True), "E0")
    assert "요구 dim_limit 2 · 최소 여유 −0.2 mm [req:plate1_t] · 시나리오 0/1" in e0, e0
    assert "요구 미등록" not in e0


def test_e0_says_unmeasured_not_zero_when_no_margin_is_known(risk_store, no_field):
    """한계만 있고 그 치수가 이 스냅샷에 없으면 `최소 여유 미측정` 이다 — 0 으로 두지 않는다."""
    project_id = _project(risk_store, {})
    factories.make_dim(risk_store, project_id, "ghost_t", "node[asm=a_stack/stack_asm/nowhere].attrs.min_dim")
    _requirements(risk_store, project_id, [
        {"kind": "dim_limit", "name": "ghost_t", "op": "lte", "value_json": 2.0, "unit": "mm"}])
    key, _ = _snap_target(risk_store, project_id)
    e0 = _item(brief.build_brief(risk_store, key, strict_lint=True), "E0")
    assert "요구 dim_limit 1 · 최소 여유 미측정 · 시나리오 0/0" in e0, e0


# ---------------------------------------------------------------- E3 두 열 · 여유 오름차순
def test_e3_carries_limit_and_margin_columns_in_margin_order(risk_store, no_field):
    """요구가 걸린 줄이 여유 오름차순으로 먼저(위반 → 여유 → 미측정), 요구 없는 치수는 뒤에 두 열이 `—` 다.

    여유는 손으로 센 값이다 — lte 1.0 에 1.2 면 −0.2(위반), gte 0.9 에 1.0 이면 +0.1(여유). 이 스냅샷에 치수가 없는 요구도 줄 하나로
    서고 여유는 `미측정` 이다(0 이 아니다 — 0 이면 위반 줄들 사이로 끼었을 것이다).
    """
    project_id = _project(risk_store)
    factories.make_dim(risk_store, project_id, "ghost_t", "node[asm=a_stack/stack_asm/nowhere].attrs.min_dim")
    _requirements(risk_store, project_id, [
        {"kind": "dim_limit", "name": "plate2_t", "op": "gte", "value_json": 0.9, "unit": "mm"},
        {"kind": "dim_limit", "name": "ghost_t", "op": "lte", "value_json": 2.0, "unit": "mm"},
        {"kind": "dim_limit", "name": "plate1_t", "op": "lte", "value_json": 1.0, "unit": "mm"},
    ])
    key, _ = _snap_target(risk_store, project_id)
    e3 = _item(brief.build_brief(risk_store, key, strict_lint=True), "E3")
    assert len(e3) == 4, e3
    assert e3[0].startswith("[d:plate1_t] «plate1_t=1.200 mm»") and \
        e3[0].endswith(" | limit=lte 1.0 mm [req:plate1_t] | margin=−0.2 mm(위반)"), e3
    assert e3[1].startswith("[d:plate2_t] «plate2_t=1.000 mm»") and \
        e3[1].endswith(" | limit=gte 0.9 mm [req:plate2_t] | margin=+0.1 mm(여유)"), e3
    assert e3[2] == "[d:ghost_t] «ghost_t=미측정» method=«measured» | limit=lte 2.0 mm [req:ghost_t] | margin=미측정", e3
    assert e3[3].startswith("[d:plate2_copy_t] ") and e3[3].endswith(" | limit=— | margin=—"), e3


def test_e3_margin_in_a_diff_uses_the_target_value_and_lists_requirements_without_a_dim(risk_store, no_field):
    """diff 의 여유는 뒤 스냅샷 값으로 센다 — 1.2 → 0.84 에 gte 0.9 면 0.84 − 0.9 = −0.06(위반). 치수 정의가 없는 요구도 실린다."""
    project_id = _project(risk_store, {"plate1_t": DIMS["plate1_t"]})
    factories.make_dim(risk_store, project_id, "spare_t", "node[asm=a_stack/stack_asm/plate_2].attrs.min_dim")
    risk_store.execute("DELETE FROM rr_dim_defs WHERE project_id = ? AND name = 'spare_t'", (project_id,))
    _requirements(risk_store, project_id, [
        {"kind": "dim_limit", "name": "plate1_t", "op": "gte", "value_json": 0.9, "unit": "mm"},
        {"kind": "dim_limit", "name": "spare_t", "op": "lte", "value_json": 3.0, "unit": "mm"},
    ])
    results = factories.fixture_adapter_results()
    revised = json.loads(json.dumps(results))
    factories.set_thickness(revised, "PLATE_1", 0.84)
    base = factories.make_snapshot(risk_store, project_id, results, label="DV1")
    target = factories.make_snapshot(risk_store, project_id, revised, label="DV2",
                                     captured_at=factories.CAPTURED_AT + 86400)
    diff = factories.make_diff(risk_store, base["snapshot_id"], target["snapshot_id"])
    key = factories.make_target(risk_store, "diff", diff["diff_id"], agents=factories.agents())
    built = brief.build_brief(risk_store, key, strict_lint=True)
    e3 = _item(built, "E3")
    assert e3[0].startswith("[d:plate1_t] ") and e3[0].endswith(
        " | limit=gte 0.9 mm [req:plate1_t] | margin=−0.06 mm(위반)"), e3
    assert e3[1] == "치수 없음 «spare_t» | limit=lte 3.0 mm [req:spare_t] | margin=미측정", e3
    assert "요구 dim_limit 2 · 최소 여유 −0.06 mm [req:plate1_t] · 시나리오 0/0" in _item(built, "E0")


# ---------------------------------------------------------------- 원자 저장 — 여유 ≤0 인 요구에 OK 는 undetermined
def _req_finding(fid: str, name: str, judgement: str, quote: str) -> dict:
    return {
        "id": fid, "direction": "risk", "domain": "mech", "mechanism": "mechanical", "mechanism_detail": "drop_stress",
        "change_kind": "dimension", "subject": {"ckeys": [], "names": [f"dim:{name}"]}, "trigger_condition": "load.drop",
        "severity": "경미", "judgement": judgement, "detectability": {"level": "test-only", "tool": ""},
        "evidence_grade": "측정", "precedent": "none", "cites": [{"ref": f"req:{name}", "quote": quote}],
        "tool_calls": [], "claim": f"{name} 한계 대조", "warrant": "등록된 요구 한계", "resolving_check": {"kind": "test", "ref": ""},
        "owner_domain": "mech", "raised_by": ["mech-syn-0"], "contested_by": [], "contest_note": "", "status": "open"}


def test_ok_on_a_violated_requirement_is_saved_as_undetermined(risk_store, no_field):
    """여유 ≤0 인 요구를 가리키며 judgement=OK 로 낸 원자는 undetermined 로 보정되고 parse_warnings 1건이다(P1 (20)).
    여유가 남은 요구의 OK 는 그대로다. 저장 행에 무슨 요구를 어겼나(requirement_ref)가 선다."""
    project_id = _project(risk_store)
    _requirements(risk_store, project_id, [
        {"kind": "dim_limit", "name": "plate1_t", "op": "lte", "value_json": 1.0, "unit": "mm"},   # 여유 −0.2
        {"kind": "dim_limit", "name": "plate2_t", "op": "gte", "value_json": 0.9, "unit": "mm"},   # 여유 +0.1
    ])
    key, _ = _snap_target(risk_store, project_id)
    panel = factories.plan_panel(risk_store, key, "A")
    spec = {"schema": "risk_spec", "version": "1.0", "scope": {"kind": "snap", "target_key": key},
            "findings": [_req_finding("F1", "plate1_t", "OK", "plate1_t lte 1.0 mm"),
                         _req_finding("F2", "plate2_t", "OK", "plate2_t gte 0.9 mm")],
            "gains": [], "cross_domain": [], "open_items": [], "verdict": "conditional", "verdict_conditions": [],
            "character": {"one_liner": "", "facets": []}, "coverage": {}, "evidence_profile": {}}
    out = narrative.persist_panel_result(risk_store, panel["id"], decision_text="F1 F2", spec=spec)

    rows = {r["claim_uid"].split("#")[1]: dict(r) for r in risk_store.query(
        "SELECT claim_uid, judgement, requirement_ref, finding_json FROM rr_findings WHERE panel_id = ?", (panel["id"],))}
    assert (rows["F1"]["judgement"], rows["F1"]["requirement_ref"]) == ("undetermined", "req:plate1_t")
    assert (rows["F2"]["judgement"], rows["F2"]["requirement_ref"]) == ("OK", "req:plate2_t")
    corrected = [w for w in out["parse_warnings"] if "undetermined 로 보정" in w]
    assert len(corrected) == 1 and corrected[0].startswith("findings/0: req:plate1_t "), out["parse_warnings"]
    assert json.loads(rows["F1"]["finding_json"])["judgement"] == "undetermined"


def test_findings_without_a_requirement_cite_keep_their_bytes(risk_store, no_field):
    """요구 인용이 없는 원자는 그대로다 — 빈 requirement_ref 칸이 finding_json 에 생기지 않는다(다른 원자의 바이트를 바꾸지 않는다)."""
    project_id = _project(risk_store)
    key, _ = _snap_target(risk_store, project_id)
    ctx = narrative._target_scope(risk_store, key)[1]
    finding = {**_req_finding("F1", "plate1_t", "OK", ""), "cites": []}
    out = narrative.normalize_risk_spec({"findings": [finding]}, narrative.SpecContext(**ctx))
    assert "requirement_ref" not in out["spec"]["findings"][0]
