# 검토 단위의 REST·MCP·대상 생성 훅(재설계 M2 U5) — 대상은 실제 routes.create_target 으로, 단위는 실제 빌드로 연다
"""cells 로 연 대상은 단위가 서야 그 방식이 되고, 안 서면(현황·자기 비교·계산 실패·저장 실패) 옛 흐름(panels)으로 열리며
까닭이 flow_fallback 에 실린다 — 대상을 못 여는 일은 없다(PLAN 4절 '흐름 결정', W2-05·W2-24). panels 대상은 생성 때 단위를
세지 않는다. 입력은 전부 공장(make_diff_target · make_diff)과 라우트를 거친 생산자 산출이다.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import time

import pytest

import app.mcp_server as srv
from app import config, routes, units
from app.errors import AppError
from tests import factories
from tests.test_mcp_brief_relay import CLAUDE_MCP_RESULT_CHARS

OWNER = factories.OWNER
OTHER = "other@example.com"


@pytest.fixture
def store(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    return risk_store


@pytest.fixture
def review_on(monkeypatch):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_enabled=True))


def _open(kind: str, ref_id: str, flow: str, *, owner: str = OWNER) -> dict:
    return routes.create_target(routes.TargetBody(kind=kind, ref_id=ref_id, consent=True, flow=flow,
                                                  agents=factories.agents()), ident=factories.ident(owner))


def _flow(store, target_key: str) -> str:
    return store.query_one("SELECT flow FROM rr_targets WHERE target_key = ?", (target_key,))["flow"]


def _builds(store, target_key: str) -> list[dict]:
    return [dict(r) for r in store.query("SELECT rev, status, error, reason FROM rr_unit_builds WHERE target_key = ?"
                                         " ORDER BY rev", (target_key,))]


# ---------------------------------------------------------------- cells 로 열기
def test_a_cells_target_opens_with_its_units_and_shows_its_flow_everywhere(store, review_on):
    """cells 로 연 대상 — 응답에 flow·단위 요약, 원장에 방식 열과 빌드 rev 1. 목록·진행판·단위 REST 가 같은 값을 보인다.
    로스터·Tier 계획은 panels 대상과 같은 규칙으로 선다(M2 는 동결 규칙을 바꾸지 않는다)."""
    synth = factories.make_diff_target(store, 40, open_target=False)
    started = time.monotonic()
    out = _open("diff", synth.diff_id, "cells")
    assert time.monotonic() - started < 5                      # 단위 계산은 로스터 기한(540초) 앞의 ms 단위다(X2-10 의 2)
    key = out["target_key"]
    oracle = units.compute(store, "diff", synth.diff_id, owner_sub=OWNER)
    assert out["flow"] == "cells" and "flow_fallback" not in out
    assert out["units"] == {
        "rev": 1, "status": "ok", "blocked_by": None, "n": len(oracle["units"]),
        "reviewable_n": oracle["stats"]["units"]["reviewable"], "lines_total": oracle["stats"]["lines_total"],
        "by_kind": {k: oracle["stats"]["units"][k] for k in units.UNIT_KINDS},
        "excluded_by_reason": oracle["stats"]["excluded_by_reason"]}
    assert out["roster_size"] == len(factories.agents()) and [t["tier"] for t in out["tier_plan"]] == ["A", "B", "C"]
    assert _flow(store, key) == "cells" and _builds(store, key) == [
        {"rev": 1, "status": "ok", "error": None, "reason": "target_open"}]

    ident = factories.ident(OWNER)
    listed = routes.list_targets(ident=ident)["targets"]
    assert [(t["target_key"], t["flow"]) for t in listed] == [(key, "cells")]
    coverage = routes.coverage_payload(key, owner_sub=OWNER)
    assert coverage["flow"] == "cells"
    assert coverage["units"] == {"rev": 1, "status": "ok", "reviewable_n": out["units"]["reviewable_n"]}
    listing = routes.get_units(key, ident=ident)
    assert listing == {**units.manifest(store, key), "flow": "cells"} and listing["total"] == out["units"]["n"]
    first = listing["units"][0]["unit_id"]
    assert routes.get_target_unit(key, first, "evidence", ident=ident) == units.get_unit(store, key, first, "evidence")
    assert routes.get_units(key, offset=1, limit=1, ident=ident)["units"] == listing["units"][1:2]
    # 같은 입력의 재빌드는 아무것도 쓰지 않는다 — 다시 세우는 쓰기는 editor 의 것이다.
    again = routes.post_units(key, routes.UnitsBody(reason="다시"), ident=ident)
    assert (again["rev"], again["changed"]) == (1, False)
    with pytest.raises(AppError) as exc:
        routes.get_units(key, ident=factories.ident(OTHER))
    assert exc.value.http_status == 404
    with pytest.raises(AppError) as exc:
        routes.post_units(key, routes.UnitsBody(), ident=factories.ident(OTHER))
    assert exc.value.http_status == 404


def test_the_switch_off_box_refuses_cells_and_writes_nothing(store):
    """새 흐름의 스위치(HWAXRISK_REVIEW_ENABLED)가 꺼진 박스에서 cells 로 열면 409 review_disabled — 켜는 자리를 말하고 대상을
    만들지 않는다. panels 는 그대로 열린다."""
    synth = factories.make_diff_target(store, 3, open_target=False)
    with pytest.raises(AppError) as exc:
        _open("diff", synth.diff_id, "cells")
    assert (exc.value.code, exc.value.http_status) == ("review_disabled", 409)
    assert exc.value.detail["knob"] == "HWAXRISK_REVIEW_ENABLED" and "knobs.env" in exc.value.message
    assert store.query("SELECT target_key FROM rr_targets") == [] and store.query("SELECT rev FROM rr_unit_builds") == []
    assert _open("diff", synth.diff_id, "panels")["flow"] == "panels"


def test_a_panels_target_never_computes_units_until_asked(store, review_on, monkeypatch):
    """panels 대상은 생성 때 단위를 세지 않는다(units.compute 를 한 번도 부르지 않는다). 진행판·단위 목록은 '없음' 이고, 재려면
    POST /targets/{key}/units 를 따로 부른다 — 그래도 방식은 panels 그대로다."""
    synth = factories.make_diff_target(store, 40, open_target=False)
    calls: list[tuple] = []
    real = units.compute
    monkeypatch.setattr(units, "compute", lambda *a, **k: calls.append(a) or real(*a, **k))
    out = _open("diff", synth.diff_id, "panels")
    key = out["target_key"]
    assert calls == [] and out["flow"] == "panels" and "units" not in out and "flow_fallback" not in out
    assert routes.coverage_payload(key, owner_sub=OWNER)["units"] == {"status": "none"}
    assert routes.get_units(key, ident=factories.ident(OWNER))["status"] == "none"
    built = routes.post_units(key, routes.UnitsBody(reason="M0-c 실측"), ident=factories.ident(OWNER))
    assert (built["rev"], built["status"], built["changed"]) == (1, "ok", True) and len(calls) == 1
    assert _flow(store, key) == "panels"
    assert routes.coverage_payload(key, owner_sub=OWNER)["units"]["status"] == "ok"


@pytest.mark.parametrize("case", ["snap", "self_diff", "compute_error"])
def test_cells_opens_on_panels_when_the_units_do_not_stand(store, review_on, monkeypatch, case):
    """단위가 서지 않으면 panels 로 열고 까닭을 싣는다 — 현황 대상(snap_not_supported) · 자기 비교(검토 대상 0 — empty, XU8) ·
    계산 실패(compute_error). 대상·로스터는 그대로 남고 빌드 행은 쓰지 않는다."""
    synth = factories.make_diff_target(store, 3, open_target=False)
    if case == "snap":
        kind, ref_id, reason = "snap", synth.target_snapshot_id, "snap_not_supported"
    elif case == "self_diff":
        kind, reason = "diff", "empty"
        ref_id = factories.make_diff(store, synth.base_snapshot_id, synth.base_snapshot_id)["diff_id"]
    else:
        kind, ref_id, reason = "diff", synth.diff_id, "compute_error"

        def boom(*_args, **_kwargs):
            raise RuntimeError("빌더 결함")

        monkeypatch.setattr(units, "build_diff_units", boom)
    out = _open(kind, ref_id, "cells")
    assert out["flow"] == "panels" and out["flow_fallback"] == {"from": "cells", "reason": reason}
    assert "units" not in out and out["roster_size"] == len(factories.agents())
    assert _flow(store, out["target_key"]) == "panels" and _builds(store, out["target_key"]) == []


def test_a_persist_failure_still_opens_the_target_on_panels(store, review_on, monkeypatch):
    """단위를 얹다가 던지면 대상은 panels 로 열린 채 남고(아직 아무것도 안 돌았다) 실패한 빌드 행이 까닭과 함께 남는다(W2-24).
    응답은 200 이다 — 타깃·로스터 트랜잭션은 이미 닫혔다."""
    synth = factories.make_diff_target(store, 40, open_target=False)
    real = units.persist
    seen = {"n": 0}

    def flaky(*args, **kwargs):
        seen["n"] += 1
        if seen["n"] == 1:
            raise RuntimeError("디스크가 찼다")
        return real(*args, **kwargs)

    monkeypatch.setattr(units, "persist", flaky)
    out = _open("diff", synth.diff_id, "cells")
    key = out["target_key"]
    assert out["flow"] == "panels" and out["flow_fallback"] == {"from": "cells", "reason": "persist_error"}
    assert out["roster_size"] == len(factories.agents()) and "units" not in out
    assert _flow(store, key) == "panels"
    assert _builds(store, key) == [{"rev": 1, "status": "failed", "error": "persist_error: RuntimeError: 디스크가 찼다",
                                    "reason": "target_open"}]
    assert store.query("SELECT unit_id FROM rr_units WHERE target_key = ?", (key,)) == []
    assert units.active_build(store, key) is None


# ---------------------------------------------------------------- MCP risk_get_units
def test_risk_get_units_pages_what_rest_returns_and_hides_other_projects(store, review_on, monkeypatch):
    """MCP 도구는 REST 와 같은 함수다 — 목록·단위 하나를 나눠 주고 next_offset 으로 다 받으면 REST 와 같다. 쪽마다 FastMCP 가
    실제로 내는 글(들여쓰기 2 JSON text 블록)이 Claude Code 의 MCP 결과 상한(25,000자) 안이다(RC-2 — 압축 JSON 으로 센 예산
    20,000자의 첫 쪽이 와이어로는 25,977자였다). 남의 대상은 not_visible, 인자 짝이 틀리면 E100 이다."""
    synth = factories.make_diff_target(store, 150, open_target=False)
    key = _open("diff", synth.diff_id, "cells")["target_key"]
    factories.act_as_delegate(monkeypatch, OWNER)
    sizes: list[int] = []

    def gather(**kwargs) -> tuple[dict, list[dict]]:
        pages, offset = [], 0
        while offset is not None:
            blocks = asyncio.run(srv.mcp.call_tool("risk_get_units", {"target_key": key, "offset": offset, **kwargs}))
            assert isinstance(blocks, list) and len(blocks) == 1, blocks
            sizes.append(len(blocks[0].text))
            page = json.loads(blocks[0].text)
            assert "error" not in page, page
            pages.append(page)
            offset = page.get("next_offset")
        return pages[0], pages

    rest = routes.get_units(key, ident=factories.ident(OWNER))
    head, pages = gather()
    assert len(pages) > 1 and [u for p in pages for u in p["units"]] == rest["units"]
    assert {k: head[k] for k in ("flow", "rev", "status", "total")} == {k: rest[k] for k in ("flow", "rev", "status", "total")}
    unit = max(rest["units"], key=lambda u: u["evidence_chars"] or 0)
    for part, fields in (("lines", ("lines", "context")), ("evidence", ("evidence",))):
        whole = routes.get_target_unit(key, unit["unit_id"], part, ident=factories.ident(OWNER))
        _head, got = gather(unit_id=unit["unit_id"], part=part)
        for field in fields:
            assert [x for p in got for x in p[field]] == whole[field], (part, field)
    assert sizes and max(sizes) <= CLAUDE_MCP_RESULT_CHARS, f"risk_get_units 와이어 {max(sizes):,}자"
    assert srv.risk_get_units(key, part="summary")["error"] == "E100"
    assert srv.risk_get_units(key, unit_id=unit["unit_id"])["error"] == "E100"
    assert srv.risk_get_units(key, unit_id=unit["unit_id"], part="nope")["error"] == "E100"
    factories.act_as_delegate(monkeypatch, OTHER)
    assert srv.risk_get_units(key)["error"] == "not_visible"
