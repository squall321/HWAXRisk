# 사람 finding 의 mechanism · domain 을 risk_taxonomy 어휘로 서버가 검사한다(A18 — 오타가 등록부 묶음 열쇠를 쪼개지 않게)
"""`POST /targets/{key}/findings`(MCP risk_add_finding 도 같은 함수)는 mechanism · domain 을 택소노미 어휘와 맞춘다 — 밖이면 422
taxonomy_invalid 와 허용값이고 아무것도 쓰지 않는다. mechanism 은 대분류 · 'unclassified' · 코드('<대분류>.<세부>' — 웹 폼이 보내는
꼴)를 받고, 코드는 패널 원자와 같은 꼴(대분류 + 세부)로 나눠 적는다 — 그대로 두면 같은 메커니즘이 다른 묶음 열쇠로 갈린다.
"""
from __future__ import annotations

import pytest

import app.mcp_server as srv
from app import routes, taxonomy
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
