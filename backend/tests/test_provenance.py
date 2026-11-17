# 원천의 출처 표지(RK-06) 시험 — 앱이 가진 값만(지어내지 않는다) · 모르는 칸은 까닭 · 이른 사본 · 빈/옛 앱 키 · 운영 아닌 env · 요소 없는 파트 경고, 스냅샷 · 등록부 · 단면 자리 · 길잡이 응답에 붙는다
"""HWAXPortal docs/request-1117 RK-06. 스냅샷은 실 어댑터 꼴의 픽스처(factories.fixture_adapter_results)를 고쳐 얼린다 — 검출 흔적 없음 · 앱 키 · 환경 표지 ·
덱 파트 수 · 캡처가 얼린 출처 칸(sources[].provenance — StepForge D-706 의 단계 · 판 · 사본 단계, KooRemapper DF-14 의 요소 id 충돌 · 빠진 파트,
리포트 환경)만 바꾼다. 그 칸이 없는 옛 캡처는 null 과 까닭이고, 덱 판은 DynaForge 가 아직 내지 않아 늘 모름이다.

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
             env: str | None = None, parts_declared: int | None = None, mcad_marks: dict | None = None, mcad_extra: dict | None = None,
             dyna_marks: dict | None = None, report_env: dict | None = None) -> list[dict]:
    results = copy.deepcopy(factories.fixture_adapter_results())
    mcad, dyna = results[0]["source"], results[1]["source"]
    if mcad_marks is not None:
        mcad["provenance"] = mcad_marks
    if mcad_extra is not None:
        mcad["app_version"] = {"version": "0.9.0", "captured_via": "heaxstep_forge_system_status", "extra": mcad_extra}
    if dyna_marks is not None:
        dyna["provenance"] = dyna_marks
    if report_env is not None:
        results[2]["source"]["provenance"] = {"report_environment": report_env}
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
    assert mcad["stage"] is None and mcad["revision"] is None and set(mcad["unknown"]) >= {"stage", "revision", "env", "copy_stage"}
    assert "얼리지 않았다" in mcad["unknown"]["stage"]                    # 그 칸을 얼리기 전의 캡처(옛 스냅샷)는 모름이다
    assert mcad["signals"] == {"detect_absent": False, "interfaces": 2, "leaf_instances": 3, "degraded": []}
    assert dyna["app_key"] == "heax-kooremapper_mcp" and dyna["deck_file"] == "assembled_tied.k"
    assert (dyna["env"], dyna["env_raw"]) == ("prod", "production") and mcad["env"] == "unknown"     # 게이트웨이 낱말(사용자 결정 D5)
    assert dyna["elements_read"] == 9800 and dyna["elements_declared"] is None and "elements_declared" in dyna["unknown"]
    assert dyna["element_id_collisions"] is None and "얼리지 않았다" in dyna["unknown"]["element_id_collisions"]
    assert (dyna["parts_declared"], dyna["parts_read"]) == (2, 2) and dyna["report_ids"] is None
    assert out["ecad"] == {"attached": False}
    assert _codes(out) == []
    checks = {c["check"]: c["status"] for c in out["checks"]}
    assert checks == {"mcad_stage": "unknown", "mcad_copy": "unknown", "dyna_app_key": "ok", "dyna_env": "ok", "deck_elements": "unknown",
                      "deck_parts_missing": "unknown", "dyna_parts": "ok", "dyna_report_env": "unknown", "revision_match": "unknown"}
    # StepForge 단계 · 판 · 환경과 DynaForge 요소 id 충돌은 그 앱이 이미 낸다 — needs 에는 아직 안 내는 것만 남는다.
    assert {n["for"] for n in out["needs"]} == {"dyna.deck_version", "dyna.instance"}


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
    # 와이어가 모자라면 짧은 꼴(경고 코드 · 검사 상태)이다(반대 검토 M5 — _fit_provenance).
    shown = snap["provenance"]
    assert shown == direct or (shown["brief"] and shown["warnings"] == _codes(direct)), shown
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


PARSED_COPY = {"detail_read": True, "stage": "파싱까지", "stage_code": "parsed",
               "revision": {"decided": True, "rev_label": "REV-B", "rev_seq": 2, "model_key": "MODEL-A", "task_code": "TASK-A",
                            "status": "current"},
               "copy_stage": {"project_id": "001a02ba21cd51064a68c35", "how_far": "parsed", "how_far_words": "파싱까지",
                              "steps_done": ["parsed"], "more_advanced": "sf-copy-2", "why": "이 과제는 파싱까지다", "copies_n": 1},
               "copy_stage_via": "rest"}
SF_EXTRA = {"app": "step_forge", "build": {"sha": "93918cf1", "at": None, "source": "git-workdir"}, "env": "dev", "env_raw": "development",
            "instance": {"server": "srv-token-1", "pid": 4242, "host": "box-a"}}


def test_a_parsed_only_copy_with_a_more_advanced_sibling_is_named_from_the_frozen_stepforge_marks(ledger_box):
    """StepForge D-706 — 과제 상세가 단계 · 판 · 사본 단계를 냈고 캡처가 얼렸다. 파싱까지만 된 사본이면 경고 · 더 진행된 사본이 있으면 그 id 를 댄다
    (좌석이 파싱까지만 된 사본을 읽고 MCAD 를 null 로 결론 낸 함정). 환경은 게이트웨이 낱말과 원래 낱말 둘 다다."""
    project_id, _ = _project_with(ledger_box, _results(mcad_marks=PARSED_COPY, mcad_extra=SF_EXTRA, env="production"), "PROV-SF")
    out = provenance.project_provenance(ledger_box.store, project_id)
    mcad = out["mcad"]
    assert (mcad["stage"], mcad["stage_code"]) == ("파싱까지", "parsed") and mcad["revision"]["rev_label"] == "REV-B"
    assert mcad["copy_stage"]["more_advanced"] == "sf-copy-2"
    assert (mcad["env"], mcad["env_raw"], mcad["instance"]["host"], mcad["build"]["sha"]) == ("dev", "development", "box-a", "93918cf1")
    assert not {"stage", "revision", "copy_stage", "env"} & set(mcad["unknown"])
    assert _codes(out) == ["mcad_early_stage", "mcad_more_advanced_copy"]
    early = next(w for w in out["warnings"] if w["code"] == "mcad_early_stage")
    assert early["evidence"]["stage_code"] == "parsed"
    copy_warning = next(w for w in out["warnings"] if w["code"] == "mcad_more_advanced_copy")
    assert copy_warning["evidence"]["more_advanced"] == "sf-copy-2" and copy_warning["evidence"]["via"] == "rest"
    checks = {c["check"]: c for c in out["checks"]}
    assert checks["mcad_stage"]["status"] == "warn" and checks["mcad_copy"]["status"] == "warn"
    # 판 대조는 두 쪽 다 값이 있을 때만이다 — 덱 판은 DynaForge 가 아직 내지 않는다.
    assert checks["revision_match"]["status"] == "unknown" and "덱 판을 모른다" in checks["revision_match"]["why"]
    assert "MCAD 판을 모른다" not in checks["revision_match"]["why"]


def test_the_app_stage_wins_over_the_signals_and_a_stepforge_without_env_says_why(ledger_box):
    marks = {**PARSED_COPY, "stage": "검출까지", "stage_code": "detected",
             "copy_stage": {**PARSED_COPY["copy_stage"], "how_far": "detected", "more_advanced": None, "why": "가장 진행됐다"}}
    no_env = {**{k: v for k, v in SF_EXTRA.items() if k not in ("env", "env_raw")}, "env": None, "env_raw": None,
              "env_why": "배포 설정 STEPFORGE_ENV 가 없다"}
    project_id, _ = _project_with(ledger_box, _results(detect_absent=True, interfaces=0, mcad_marks=marks, mcad_extra=no_env), "PROV-SF2")
    out = provenance.project_provenance(ledger_box.store, project_id)
    checks = {c["check"]: c["status"] for c in out["checks"]}
    assert checks["mcad_stage"] == "ok" and checks["mcad_copy"] == "ok" and "mcad_early_stage" not in _codes(out)
    assert out["mcad"]["env"] == "unknown" and "STEPFORGE_ENV" in out["mcad"]["unknown"]["env"]
    # MCP 만의 캡처(과제 상세 없음) — 사본 단계가 MCP 답에 없으면 '없다' 가 아니라 모른다.
    mcp_only = {"detail_read": False, "stage": None, "stage_code": None, "revision": None, "copy_stage": None, "copy_stage_via": None}
    other, _ = _project_with(ledger_box, _results(mcad_marks=mcp_only), "PROV-SF3")
    got = provenance.project_provenance(ledger_box.store, other)["mcad"]["unknown"]
    assert "과제 상세(REST)를 읽지 못했다" in got["stage"] and "더 진행된 사본이 있을 때만" in got["copy_stage"]


def test_the_revision_check_compares_only_when_both_sides_have_a_value(ledger_box, monkeypatch):
    """덱 판은 DynaForge 가 아직 내지 않는다 — 대조를 켜는 자리만 본다(덱 쪽에 값이 생기면 정한 MCAD 판의 이름과 견준다)."""
    real = provenance._dyna

    def with_deck(label):
        def fake(*args, **kwargs):
            out = real(*args, **kwargs)
            out["deck_version"] = label
            return out
        return fake

    project_id, _ = _project_with(ledger_box, _results(mcad_marks=PARSED_COPY), "PROV-REV")
    monkeypatch.setattr(provenance, "_dyna", with_deck("REV-C"))
    out = provenance.project_provenance(ledger_box.store, project_id)
    assert "revision_mismatch" in _codes(out) and {c["check"]: c["status"] for c in out["checks"]}["revision_match"] == "warn"
    monkeypatch.setattr(provenance, "_dyna", with_deck("REV-B"))
    assert {c["check"]: c["status"] for c in provenance.project_provenance(ledger_box.store, project_id)["checks"]}["revision_match"] == "ok"
    undecided = {**PARSED_COPY, "revision": {"decided": False, "rev_label": None, "rev_seq": None, "model_key": None, "task_code": "TASK-A",
                                             "status": None}}
    other, _ = _project_with(ledger_box, _results(mcad_marks=undecided), "PROV-REV2")
    check = next(c for c in provenance.project_provenance(ledger_box.store, other)["checks"] if c["check"] == "revision_match")
    assert check["status"] == "unknown" and "decided false" in check["why"]


def test_deck_element_id_collisions_and_missing_parts_are_warned_and_old_files_stay_unknown(ledger_box):
    """KooRemapper DF-14 — 같은 번호의 뒤 카드에 덮여 잃은 요소 · 요소가 다 빠져 목록에 없는 파트(파트 944개를 잃은 함정). 덱에 적힌 요소 수는 읽은
    요소 + 잃은 요소다. 11-17 전에 올린 파일은 둘 다 null 이라 0 이 아니라 모름이다. 리포트 환경이 운영이 아니면 경고다."""
    project_id, _ = _project_with(ledger_box, _results(env="production", dyna_marks={"element_id_collisions": 120, "parts_missing": 3},
                                                       report_env={"r1": "dev"}), "PROV-DF")
    out = provenance.project_provenance(ledger_box.store, project_id)
    dyna = out["dyna"]
    assert (dyna["element_id_collisions"], dyna["parts_missing"], dyna["elements_declared"]) == (120, 3, 9800 + 120)
    assert {"dyna_element_id_collisions", "dyna_parts_missing", "dyna_report_env_not_production"} <= set(_codes(out))
    assert dyna["report_environment"] == {"r1": "dev"} and dyna["unknown"]["deck_version"].startswith("DynaForge 가 덱 판")
    checks = {c["check"]: c["status"] for c in out["checks"]}
    assert (checks["deck_elements"], checks["deck_parts_missing"], checks["dyna_report_env"]) == ("warn", "warn", "warn")
    clean, _ = _project_with(ledger_box, _results(env="production", dyna_marks={"element_id_collisions": 0, "parts_missing": 0},
                                                  report_env={"r1": "prod"}), "PROV-DF2")
    ok = provenance.project_provenance(ledger_box.store, clean)
    assert {c["check"]: c["status"] for c in ok["checks"]}["deck_elements"] == "ok" and ok["dyna"]["elements_declared"] == 9800
    assert not {"dyna_element_id_collisions", "dyna_parts_missing", "dyna_report_env_not_production"} & set(_codes(ok))
    old, _ = _project_with(ledger_box, _results(dyna_marks={"element_id_collisions": None, "parts_missing": None}), "PROV-DF3")
    stale = provenance.project_provenance(ledger_box.store, old)["dyna"]
    assert stale["element_id_collisions"] is None and "0 이 아니라 모른다" in stale["unknown"]["element_id_collisions"]
