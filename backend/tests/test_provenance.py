# 원천의 출처 표지(RK-06) 시험 — 앱이 가진 값만(지어내지 않는다) · 모르는 칸은 까닭 · 이른 사본 · 빈/옛 앱 키 · 운영 아닌 env · 요소 없는 파트 경고, 스냅샷 · 등록부 · 단면 자리 · 길잡이 응답에 붙는다
"""HWAXPortal docs/request-1117 RK-06. 스냅샷은 실 어댑터 꼴의 픽스처(factories.fixture_adapter_results)를 고쳐 얼린다 — 검출 흔적 없음 · 앱 키 · 환경 표지 ·
덱 파트 수만 바꾼다. 원천 앱이 내지 않는 칸(StepForge 단계 · 판, 덱에 적힌 요소 수 · 덱 판)은 늘 null 과 까닭이다(11-17 dev 소스 대조).

  실행:  .venv/bin/python -m pytest tests/test_provenance.py
"""
from __future__ import annotations

import copy
import types

import pytest

from app import ledger_routes, provenance, routes
from app.adapters import base as adapters_base
from app.errors import AppError
from tests import factories
from tests import ledger_support
from tests.ledger_support import OWNER, STRANGER, VIEWER, call

ledger_box = ledger_support.ledger_box          # 판정표 시험 상자(tests/ledger_support.py)를 이 모듈에도 건다


def _results(*, detect_absent: bool = False, interfaces: int | None = None, dyna_app_key: str | None = "heax-kooremapper_mcp",
             env: str | None = None, parts_declared: int | None = None) -> list[dict]:
    results = copy.deepcopy(factories.fixture_adapter_results())
    mcad, dyna = results[0]["source"], results[1]["source"]
    if detect_absent:
        mcad["degraded"] = sorted({*mcad.get("degraded", []), "detect_absent"})
    if interfaces is not None:
        mcad["stats"]["interfaces"] = interfaces
    dyna["app_key"] = dyna_app_key
    if env is not None:
        dyna["app_version"] = {"version": "0.1.0", "captured_via": "heaxkooremapper_mcp_system_status", "extra": {"env": env}}
    if parts_declared is not None:
        dyna["stats"]["parts"] = parts_declared
    return results


def _project_with(box, results: list[dict], code: str) -> tuple[str, str]:
    project_id = factories.make_project(box.store, owner=OWNER, code=code)
    routes.put_members(project_id, routes.MembersBody(members=[routes.MemberItem(email=VIEWER, role="viewer")]),
                       ident=factories.ident(OWNER))
    snap = factories.make_snapshot(box.store, project_id, results, label="DV1", owner=OWNER)
    return project_id, snap["snapshot_id"]


def _codes(out: dict) -> list[str]:
    return [w["code"] for w in out["warnings"]]


def test_a_healthy_capture_carries_what_the_apps_returned_and_names_what_they_did_not(ledger_box):
    project_id, snapshot_id = _project_with(ledger_box, _results(env="production"), "PROV-OK")
    out = ledger_routes.get_provenance(project_id, ident=factories.ident(VIEWER))
    assert out["basis"] == "snapshot" and out["snapshot_id"] == snapshot_id
    mcad, dyna = out["mcad"], out["dyna"]
    assert mcad["stepforge_project_id"] == "001a02ba21cd51064a68c35" and mcad["detect_job_id"] == "01JDET"
    assert mcad["stage"] is None and mcad["revision"] is None and set(mcad["unknown"]) >= {"stage", "revision", "env"}
    assert mcad["signals"] == {"detect_absent": False, "interfaces": 2, "leaf_instances": 3, "degraded": []}
    assert dyna["app_key"] == "heax-kooremapper_mcp" and dyna["deck_file"] == "assembled_tied.k"
    assert (dyna["env"], dyna["env_raw"]) == ("prod", "production") and mcad["env"] == "unknown"     # 게이트웨이 낱말(사용자 결정 D5)
    assert dyna["elements_read"] == 9800 and dyna["elements_declared"] is None and "elements_declared" in dyna["unknown"]
    assert (dyna["parts_declared"], dyna["parts_read"]) == (2, 2) and dyna["report_ids"] is None
    assert out["ecad"] == {"attached": False}
    assert _codes(out) == []
    checks = {c["check"]: c["status"] for c in out["checks"]}
    assert checks == {"mcad_stage": "unknown", "dyna_app_key": "ok", "dyna_env": "ok", "deck_elements": "unknown",
                      "dyna_parts": "ok", "revision_match": "unknown"}
    assert {n["for"] for n in out["needs"]} >= {"mcad.stage", "mcad.revision", "dyna.elements_declared", "dyna.deck_version"}


def test_an_early_copy_an_empty_or_retired_key_a_dev_env_and_parts_without_elements_are_warned(ledger_box):
    results = _results(detect_absent=True, interfaces=0, dyna_app_key=None, env="development", parts_declared=5)
    project_id, _ = _project_with(ledger_box, results, "PROV-WARN")
    out = provenance.project_provenance(ledger_box.store, project_id)
    assert _codes(out) == ["mcad_early_stage", "dyna_app_key_empty", "dyna_env_not_production", "dyna_parts_without_elements"]
    parts = next(w for w in out["warnings"] if w["code"] == "dyna_parts_without_elements")
    assert parts["evidence"] == {"parts_declared": 5, "parts_read": 2}
    retired, _ = _project_with(ledger_box, _results(dyna_app_key="dynaforge-prod"), "PROV-OLD")
    old = provenance.project_provenance(ledger_box.store, retired)
    assert _codes(old) == ["dyna_app_key_retired"] and old["warnings"][0]["evidence"]["current"] == "heax-kooremapper_mcp"
    assert old["dyna"]["env"] == "unknown" and old["dyna"]["env_raw"] is None and "env" in old["dyna"]["unknown"]
    odd, _ = _project_with(ledger_box, _results(env="staging"), "PROV-ODD")
    strange = provenance.project_provenance(ledger_box.store, odd)["dyna"]
    assert (strange["env"], strange["env_raw"]) == ("unknown", "staging") and "staging" in strange["unknown"]["env"]


def test_without_a_snapshot_only_the_source_cards_speak(ledger_box):
    project_id = factories.make_project(ledger_box.store, owner=OWNER, code="PROV-CARD")
    # 원천 카드 한 장 — 생산자(routes.add_source)는 게이트웨이 발견을 부른다. 이 시험은 카드 읽기만 본다(시험용으로 직접 적은 행).
    ledger_box.store.execute(
        "INSERT INTO rr_sources(id, project_id, owner_sub, kind, app_key, ref_json, ref_key, created_at) VALUES (?,?,?,?,?,?,?,?)",
        ("src-1", project_id, OWNER, "mcad", "heax-step_forge", '{"stepforge_project_id":"sf-1"}', "mcad:heax-step_forge:sf-1", 1))
    out = provenance.project_provenance(ledger_box.store, project_id)
    assert out["basis"] == "source_cards" and out["snapshot_id"] is None
    assert out["mcad"]["stepforge_project_id"] == "sf-1" and out["mcad"]["signals"] is None and "signals" in out["mcad"]["unknown"]
    assert out["dyna"] == {"attached": False} and [c["check"] for c in out["checks"]] == ["mcad_stage"]


def test_the_rest_route_follows_the_project_reader_gate(ledger_box):
    project_id, snapshot_id = _project_with(ledger_box, _results(), "PROV-GATE")
    with pytest.raises(AppError) as exc:
        ledger_routes.get_provenance(project_id, ident=factories.ident(STRANGER))
    assert exc.value.http_status == 404
    with pytest.raises(AppError) as exc:
        ledger_routes.get_provenance(project_id, snapshot_id="nope", ident=factories.ident(VIEWER))
    assert exc.value.http_status == 404
    assert ledger_routes.get_provenance(project_id, snapshot_id=snapshot_id, ident=factories.ident(OWNER))["snapshot_id"] == snapshot_id


def test_snapshot_registry_and_provenance_tools_carry_it_over_mcp(ledger_box):
    """risk_get_snapshot · risk_get_registry 답에 provenance 가 붙는다(risk_get_provenance 와 같은 꼴)."""
    results = _results(detect_absent=True, interfaces=0)
    project_id, snapshot_id = _project_with(ledger_box, results, "PROV-MCP")
    target_key = factories.make_target(ledger_box.store, "snap", snapshot_id, agents=factories.agents(), owner=OWNER)
    ledger_box.act_as(VIEWER)
    direct = call("risk_get_provenance", project_id=project_id)
    assert _codes(direct) == ["mcad_early_stage"]
    snap = call("risk_get_snapshot", snapshot_id=snapshot_id, part="state")
    assert snap["provenance"] == direct
    reg = call("risk_get_registry", target_key=target_key)
    assert reg["provenance"]["snapshot_id"] == snapshot_id and _codes(reg["provenance"]) == ["mcad_early_stage"]
    ledger_box.act_as(STRANGER)
    assert call("risk_get_provenance", project_id=project_id)["error"] == "not_visible"


def test_the_guide_and_the_section_locator_carry_provenance(ledger_box):
    """길잡이(entry.next_step)와 단면 자리(웹 · MCP 같은 본체 routes.locate_payload — 보드 좌표는 게이트웨이를 부르지 않는다)에 붙는다."""
    from app import entry

    project_id, _ = _project_with(ledger_box, _results(env="development"), "PROV-GUIDE")
    out = entry.next_step(factories.ident(OWNER), project_id=project_id)
    assert out["provenance"]["dyna"]["env"] == "dev" and "dyna_env_not_production" in _codes(out["provenance"])
    located = routes.get_locate(project_id, x=1.0, y=1.0, ident=factories.ident(VIEWER))
    assert located["status"] == "unknown" and located["provenance"]["project_id"] == project_id
    assert located["provenance"] == provenance.project_provenance(ledger_box.store, project_id)


def test_the_capture_keeps_the_env_marker_the_source_app_returns():
    """DynaForge system_status 의 env 를 app_version.extra 에 남긴다 — 없으면 싣지 않는다(지어내지 않는다)."""
    replies = iter([{"ok": True, "result": {"version": "0.1.0", "env": "production"}}, {"ok": True, "result": {"version": "0.1.0"}}])
    recorder = types.SimpleNamespace(mcp_available=True, call=lambda *a, **k: next(replies))
    assert adapters_base.probe_app_version(recorder, "dyna")["extra"] == {"env": "production"}
    assert adapters_base.probe_app_version(recorder, "dyna")["extra"] is None
