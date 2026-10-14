# 셀 꾸러미 경로의 남의 대상 숨김(재설계 M3 C3-13 · WP5b C12) — 라우터에서 뽑은 셀 경로 전부가 남에게 404 이고 MCP 처분 · 읽기가 범위 밖에 not_visible 이다
"""경로 목록은 라우터(`routes.router`)에서 뽑는다 — `/api/targets/{target_key}/` 아래 첫 마디가 셀 꾸러미의 것(cells · experts ·
undefer · units)인 경로 전부가 이 시험의 표에 있어야 한다. 새 경로를 넣고 표를 잊으면 첫 시험이 붉다. 원장은 생산자 경로(검토 루프
가짜 엔진 — 시험대 review_rig)다."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import pytest
from fastapi.routing import APIRoute

import app.mcp_server as srv
from app import routes
from app.errors import AppError
from tests import factories
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

OWNER = rig.OWNER
OTHER = "intruder@example.com"
PREFIX = "/api/targets/{target_key}/"
CELL_SEGMENTS = ("cells", "experts", "undefer", "units")

Call = Callable[[str, str, object], object]
CASES: dict[tuple[str, str], Call] = {
    ("POST", PREFIX + "undefer"): lambda key, unit, ident: routes.post_undefer(
        key, routes.UndeferBody(reason="남의 대상의 보류를 풀어 본다"), ident=ident),
    ("POST", PREFIX + "cells/retry"): lambda key, unit, ident: routes.post_cells_retry(
        key, routes.CellsRetryBody(filter={}, reason="남의 대상의 셀을 다시 열어 본다"), ident=ident),
    ("POST", PREFIX + "cells/skip"): lambda key, unit, ident: routes.post_cells_skip(
        key, routes.CellsSkipBody(filter={}, reason="남의 대상의 셀을 넘겨 본다"), ident=ident),
    ("GET", PREFIX + "cells"): lambda key, unit, ident: routes.get_cells(key, ident=ident),
    ("GET", PREFIX + "cells/{unit_id}/{agent_key}"): lambda key, unit, ident: routes.get_cell(key, unit, rig.SEAL,
                                                                                              ident=ident),
    ("GET", PREFIX + "experts"): lambda key, unit, ident: routes.get_experts(key, ident=ident),
    ("GET", PREFIX + "experts/{agent_key}/report"): lambda key, unit, ident: routes.get_expert_report(key, rig.SEAL,
                                                                                                     ident=ident),
    ("POST", PREFIX + "units"): lambda key, unit, ident: routes.post_units(key, routes.UnitsBody(), ident=ident),
    ("GET", PREFIX + "units"): lambda key, unit, ident: routes.get_units(key, ident=ident),
    ("GET", PREFIX + "units/{unit_id}"): lambda key, unit, ident: routes.get_target_unit(key, unit, ident=ident),
}


def _cell_routes() -> set[tuple[str, str]]:
    out: set[tuple[str, str]] = set()
    for route in routes.router.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(PREFIX):
            continue
        if route.path[len(PREFIX):].split("/")[0] in CELL_SEGMENTS:
            out |= {(method, route.path) for method in route.methods}
    return out


@pytest.fixture
def reviewed(risk_store, monkeypatch, tmp_path):
    """SEAL 하나를 끝까지 돈 카드 대조 대상 — (대상, 첫 단위, 잡)."""
    rig.configure(monkeypatch, risk_store, tmp_path)
    key = rig.target(risk_store)
    job_id = rig.job(risk_store, key, scope={"agents": [rig.SEAL]})
    rig.Rig(risk_store, FakeReviewEngine(rig.packs())).finish(job_id)
    assert rig.state(risk_store, job_id) == "completed"
    unit = routes.get_cells(key, ident=factories.ident(OWNER))["rows"][0]["unit_id"]
    return key, unit, job_id


def test_every_cell_route_in_the_router_is_in_this_table():
    """라우터의 셀 꾸러미 경로 == 이 표 — 새 경로가 남의 대상 시험 없이 들어오지 않는다."""
    assert _cell_routes() == set(CASES)


@pytest.mark.parametrize("case", sorted(CASES), ids=lambda c: f"{c[0]} {c[1][len(PREFIX):]}")
def test_another_persons_target_is_404_on_every_cell_route(reviewed, case):
    """남(과제 구성원이 아닌 사람)이 부르면 쓰기 · 읽기 모두 404 다(있는지조차 말하지 않는다). 주인이 같은 인자로 부르면 404 가
    아니다 — 404 가 인자 탓이 아니다."""
    key, unit, _job = reviewed
    call = CASES[case]
    with pytest.raises(AppError) as refused:
        call(key, unit, factories.ident(OTHER))
    assert refused.value.http_status == 404
    try:
        call(key, unit, factories.ident(OWNER))
    except AppError as exc:
        assert exc.http_status != 404, (case, exc.code)


def _call(name: str, /, **kwargs) -> dict:
    out = getattr(srv, name)(**kwargs)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def test_mcp_dispositions_and_reads_are_not_visible_outside_the_callers_scope(reviewed, monkeypatch, risk_store):
    """MCP — 남의 잡의 실패 셀 처분(risk_job_action retry_failed · skip_failed)과 남의 대상의 셀 · 전문가 보고서 읽기가 not_visible 이다
    (주인으로는 보인다). 처분은 아무 셀도 바꾸지 않는다."""
    key, unit, job_id = reviewed
    before = [dict(r) for r in risk_store.query("SELECT * FROM rr_review_cells WHERE target_key = ? ORDER BY unit_id, agent_key",
                                                (key,))]
    factories.act_as_delegate(monkeypatch, OTHER)
    for action in ("retry_failed", "skip_failed"):
        refused = _call("risk_job_action", job_id=job_id, action=action, reason="남의 잡을 처분해 본다")
        assert refused["error"] == "not_visible" and key not in json.dumps(refused, ensure_ascii=False)   # 대상 열쇠를 흘리지 않는다
        missing = _call("risk_job_action", job_id="no-such-job", action=action, reason="없는 잡을 처분해 본다")
        assert missing["error"] == refused["error"]                                                  # 없는 잡과 같은 답
    assert _call("risk_get_cells", target_key=key)["error"] == "not_visible"
    assert _call("risk_get_expert_report", target_key=key, agent_key=rig.SEAL)["error"] == "not_visible"
    assert [dict(r) for r in risk_store.query("SELECT * FROM rr_review_cells WHERE target_key = ? ORDER BY unit_id, agent_key",
                                              (key,))] == before
    factories.act_as_delegate(monkeypatch, OWNER)
    assert _call("risk_get_cells", target_key=key)["rows"]
    assert "error" not in _call("risk_job_action", job_id=job_id, action="retry_failed", reason="주인의 처분")
