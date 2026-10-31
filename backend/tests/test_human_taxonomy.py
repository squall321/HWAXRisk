# 사람 finding 의 mechanism · domain 을 risk_taxonomy 어휘로 서버가 검사한다(A18 — 오타가 등록부 묶음 열쇠를 쪼개지 않게)
"""`POST /targets/{key}/findings`(MCP risk_add_finding 도 같은 함수)는 mechanism · domain 을 택소노미 어휘와 맞춘다 — 밖이면 422
taxonomy_invalid 와 허용값이고 아무것도 쓰지 않는다. mechanism 은 대분류 · 'unclassified' · 코드('<대분류>.<세부>' — 웹 폼이 보내는
꼴)를 받고, 코드는 패널 원자와 같은 꼴(대분류 + 세부)로 나눠 적는다 — 그대로 두면 같은 메커니즘이 다른 묶음 열쇠로 갈린다.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import app.mcp_server as srv
from app import registry, routes, taxonomy
from app.errors import AppError
from tests import factories
from tests.test_project_patch import OWNER, _human_body, _ident, _seeded_target


def _create(target_key: str, **over) -> dict:
    return routes.create_human_finding(target_key, _human_body(**over), ident=_ident())


def _row(store, finding_id: str) -> dict:
    return dict(store.query_one("SELECT mechanism, mechanism_detail, domain, cluster_key FROM rr_findings WHERE finding_id = ?",
                                (finding_id,)))


def _human_n(store) -> int:
    return store.query_one("SELECT COUNT(*) AS n FROM rr_findings WHERE origin = 'human'")["n"]


def test_a_mechanism_outside_the_taxonomy_is_422_with_the_allowed_values(risk_store, monkeypatch):
    target_key = _seeded_target(risk_store, monkeypatch)
    for typo in ("interfase", "interface.clearanse", "Interface", ""):
        with pytest.raises(AppError) as exc:
            _create(target_key, mechanism=typo, mechanism_detail=None)
        assert (exc.value.code, exc.value.http_status) == ("taxonomy_invalid", 422), typo
        assert exc.value.detail["field"] == "mechanism" and exc.value.detail["value"] == typo
        assert exc.value.detail["allowed"] == ["unclassified", *taxonomy.mechanism_majors()]
        assert "interface.clearance" in exc.value.detail["codes"]
    assert _human_n(risk_store) == 0


def test_a_domain_outside_the_taxonomy_is_422_with_the_allowed_values(risk_store, monkeypatch):
    target_key = _seeded_target(risk_store, monkeypatch)
    with pytest.raises(AppError) as exc:
        _create(target_key, domain="mechh")
    assert (exc.value.code, exc.value.http_status) == ("taxonomy_invalid", 422)
    domains = [d["code"] for d in taxonomy.load_taxonomy()["axes"]["domain"]]
    assert exc.value.detail == {"field": "domain", "value": "mechh", "allowed": domains}
    assert _human_n(risk_store) == 0


def test_unclassified_majors_and_no_domain_pass_as_before(risk_store, monkeypatch):
    target_key = _seeded_target(risk_store, monkeypatch)
    loose = _create(target_key, mechanism="unclassified", mechanism_detail=None, domain=None)
    exact = _create(target_key)
    assert _row(risk_store, loose["finding_id"]) == {"mechanism": "unclassified", "mechanism_detail": None, "domain": None,
                                                    "cluster_key": loose["cluster_key"]}
    assert _row(risk_store, exact["finding_id"])["mechanism"] == "interface"


def test_the_code_form_is_written_as_major_and_detail(risk_store, monkeypatch):
    """웹 폼은 코드를 mechanism 에 싣는다 — 대분류 + 세부로 나눠 적어 대분류 꼴(MCP)과 같은 묶음 열쇠가 된다."""
    target_key = _seeded_target(risk_store, monkeypatch)
    coded = _create(target_key, mechanism="interface.clearance", mechanism_detail=None)
    split = _create(target_key)                                   # mechanism='interface' · mechanism_detail='clearance'
    assert _row(risk_store, coded["finding_id"]) == _row(risk_store, split["finding_id"])
    assert coded["cluster_key"] == split["cluster_key"]
    # 코드의 세부와 다른 세부를 같이 주면 어느 쪽인지 고르지 않는다.
    with pytest.raises(AppError) as exc:
        _create(target_key, mechanism="interface.clearance", mechanism_detail="tied")
    assert exc.value.code == "taxonomy_invalid"
    assert exc.value.detail == {"field": "mechanism_detail", "value": "tied", "allowed": ["clearance"]}


def test_the_mcp_tool_answers_the_same_422(risk_store, monkeypatch):
    target_key = _seeded_target(risk_store, monkeypatch)
    factories.act_as_delegate(monkeypatch, OWNER)
    out = srv.risk_add_finding(target_key=target_key, claim="간극이 좁다", cites=[{"ref": "p:0123456789ab", "quote": "q"}],
                               actor=OWNER, mechanism="thermall", domain="mech")
    assert out["error"] == "taxonomy_invalid" and out["detail"]["field"] == "mechanism"
    assert "thermal" in out["detail"]["allowed"]
    assert _human_n(risk_store) == 0


def _rekey_script():
    """backend/scripts/rekey_human_codes.py — 실행자 셸 전용 파일이라 모듈로 읽어 온다(test_bootstrap_scripts 와 같은 길)."""
    path = Path(__file__).resolve().parent.parent / "scripts" / "rekey_human_codes.py"
    spec = importlib.util.spec_from_file_location("hwaxrisk_scripts_rekey_human_codes", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_code_form_rows_from_before_the_check_join_the_split_form_through_an_alias(risk_store, monkeypatch):
    """A18 전 입구는 웹 폼의 코드 꼴을 mechanism 에 그대로 적었다 — 그 행이 남은 대상에서는 같은 위험의 새 finding 이 다른 묶음 열쇠의
    등록부 행에 선다. 한 번 도는 재열쇠(scripts/rekey_human_codes.py — dry-run 기본)는 finding 행의 cluster_key 를 고치지 않고(plan
    §4.3.2 삽입 시 동결) 그 소유자의 별칭(옛 열쇠 → 대분류 + 세부 열쇠) 한 행을 세운 뒤 그 열쇠의 사람 finding 이 있는 대상을 모두 다시
    병합한다 — 같은 위험의 finding 이 한 행에 든다. 코드와 다른 세부를 같이 적은 행은 코드가 고르지 않고 알린다. 다시 돌려도 새 별칭이
    없고, 사람이 철회한 별칭도 되살리지 않는다."""
    target_key = _seeded_target(risk_store, monkeypatch, extra="diff:d2")
    split = routes.human_mechanism
    monkeypatch.setattr(routes, "human_mechanism", lambda mechanism, detail: (mechanism, detail))   # A18 전 입구
    legacy = _create(target_key, mechanism="interface.clearance", mechanism_detail=None)
    legacy_too = routes.create_human_finding("diff:d2", _human_body(mechanism="interface.clearance", mechanism_detail=None),
                                             ident=_ident())
    tied = _create(target_key, mechanism="interface.clearance", mechanism_detail="tied", subject_key="sk:2")
    monkeypatch.setattr(routes, "human_mechanism", split)
    fresh = _create(target_key, mechanism="interface.clearance", mechanism_detail=None)
    assert legacy["cluster_key"] == legacy_too["cluster_key"] != fresh["cluster_key"]
    script = _rekey_script()

    plan = script.plan_rows(risk_store)

    assert sorted((r["finding_id"], r["old_cluster_key"], r["new_cluster_key"]) for r in plan["rows"]) == sorted([
        (legacy["finding_id"], legacy["cluster_key"], fresh["cluster_key"]),
        (legacy_too["finding_id"], legacy["cluster_key"], fresh["cluster_key"])])
    assert plan["skipped"] == [{"finding_id": tied["finding_id"], "mechanism": "interface.clearance", "mechanism_detail": "tied",
                                "reason": "detail_differs"}]
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_cluster_alias")["n"] == 0      # 계획은 쓰지 않는다

    out = script.apply_rows(risk_store, plan["rows"])

    assert out == {"aliases_written": 1, "targets_merged": sorted([target_key, "diff:d2"])}
    for key, members in ((target_key, {legacy["finding_id"], fresh["finding_id"]}), ("diff:d2", {legacy_too["finding_id"]})):
        row = risk_store.query_one("SELECT human_n, merged_json FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
                                   (key, fresh["cluster_key"]))
        assert row["human_n"] == len(members) and members <= set(json.loads(row["merged_json"])["member_ids"])
    assert _row(risk_store, legacy["finding_id"])["cluster_key"] == legacy["cluster_key"]       # 삽입 시 동결
    assert script.apply_rows(risk_store, script.plan_rows(risk_store)["rows"]) == {"aliases_written": 0, "targets_merged": []}
    # 사람이 철회한 별칭은 다시 돌려도 되살리지 않는다.
    registry.revoke_cluster_alias(risk_store, legacy["cluster_key"], owner_sub=OWNER)
    assert script.apply_rows(risk_store, script.plan_rows(risk_store)["rows"]) == {"aliases_written": 0, "targets_merged": []}
    assert risk_store.query_one("SELECT revoked_at FROM rr_cluster_alias")["revoked_at"] is not None
