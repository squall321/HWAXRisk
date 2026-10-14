# 카드 원문 카나리아(재설계 M3 C3-13 · WP5b C12 ①의 셀 몫) — 인용되지 않는 절에 심은 CANARY-<hex> 가 한 바퀴(거르기 · 표본 · 입력 결손 · 처분 · 다시 마감) 뒤 어느 응답 · 반출 · 로그 · 감사에도 없다
"""합성 카드마다 인용되지 않는 절(가짜 엔진은 첫 절만 인용한다)을 하나 더해 `CANARY-<hex>` 를 심는다(text_sha · chars 는 엔진의
식으로 다시 센다 — 묶음 무결성 검사를 지난다). 원장은 생산자 경로다 — 거르기 시험의 로스터(std 3 · mech 2 · 회로 mem 2 — 입력 결손)를
검토 루프로 돌려 경계 단위가 걸러지고 잡 끝 보충 표본이 다시 열고, mem 은 입력 결손 호출, mech 2순위의 셀 하나는 내용 탓 실패 →
사람의 다시(REST) → 새 잡 → 다시 마감. 있어도 되는 곳은 얼린 묶음(rr_card_packs)과 엔진에 간 프롬프트뿐이다(WP5b 3.10.1)."""
from __future__ import annotations

import asyncio
import gzip
import json
import logging

import pytest

import app.mcp_server as srv
from app import cardpack, entry, export, expert_report, relevance, review_cells, review_quality, routes
from tests import factories
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.test_review_filter import MECH2, MEM1, ROSTER, _packs, _quiet, _units

OWNER = rig.OWNER
CANARY = "CANARY-5e1f0a9c"
NO_ROWS = {"code": "no_rows", "message": "판정 행이 하나도 없다(가짜)", "infra": False, "retryable": False}


def _planted(pack: dict) -> dict:
    """카드마다 맨 뒤에 인용되지 않는 절을 더한다 — text_sha · chars · chars_total 은 다시 센다."""
    out = json.loads(json.dumps(pack))
    for card in out["cards"]:
        extra = f"부록 — {CANARY} 이 절은 어느 판정에도 인용되지 않는다(시험용 카나리아)."
        card["sections"].append({"sid": "9", "title": "부록", "text": extra})
        card["text_sha"] = cardpack.text_sha(card["sections"])
        card["chars"] = int(card["chars"]) + len(extra)
    out["chars_total"] = sum(int(c["chars"]) for c in out["cards"])
    return out


@pytest.fixture
def loop(risk_store, monkeypatch, tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    rig.configure(monkeypatch, risk_store, tmp_path, risk_review_concurrency=1, risk_review_filter="on",
                  risk_filter_audit_pct=0)
    monkeypatch.setattr(relevance, "routing_approved", lambda **_: True)
    key = rig.target(risk_store, ROSTER)
    job_id = rig.job(risk_store, key)
    fake = FakeReviewEngine({k: _planted(v) for k, v in _packs(ROSTER).items()})
    fake.offcard_findings = 0
    kinds = _units(risk_store, key)
    _quiet(fake, kinds["boundary"], kinds["global"])
    fake.noinput_q1 = {kinds["boundary"]: ["no"]}
    fake.noinput_q2 = {kinds["boundary"]: [""]}
    fake.error_cells = {(MECH2, kinds["bundle"]): NO_ROWS}
    r = rig.Rig(risk_store, fake)
    r.finish(job_id)
    assert rig.state(risk_store, job_id) == "completed"
    failed = risk_store.query_one("SELECT state FROM rr_review_cells WHERE target_key = ? AND agent_key = ? AND unit_id = ?",
                                  (key, MECH2, kinds["bundle"]))["state"]
    assert failed == "failed"
    fake.error_cells = {}
    out = routes.post_cells_retry(key, routes.CellsRetryBody(filter={"job_id": job_id}, reason="카나리아 한 바퀴의 다시"),
                                  ident=factories.ident(OWNER))
    second = out["job"]["job_id"]
    r.finish(second)
    assert rig.state(risk_store, second) == "completed"
    return key, fake, kinds


def _mcp(name: str, /, **kwargs) -> dict:
    out = getattr(srv, name)(**kwargs)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def test_an_unquoted_card_section_never_leaves_the_pack_after_a_full_round(risk_store, loop, monkeypatch, caplog):
    """거르기(걸러진 셀이 있다) · 표본(보충 표본이 다시 연 셀) · 입력 결손(mem 의 셀) · 처분(다시 연 셀) · 다시 마감(그 전문가 보고서의
    판이 오른다) 뒤 — REST 응답(진행판 · 셀 격자 · 셀 하나 · 전문가 목록 · 보고서 md/json · 품질 · 완결 몫 · 길잡이) · MCP 응답 ·
    반출 · 로그 · 감사 행 어디에도 카나리아가 없다. 얼린 묶음과 엔진에 간 프롬프트에는 있다(진짜 심은 글이다)."""
    key, fake, kinds = loop
    cells = [dict(r) for r in risk_store.query("SELECT unit_id, agent_key, state, route_forced, basis, reopened_n,"
                                               " json_extract(route_json, '$.decision') AS decision"
                                               " FROM rr_review_cells WHERE target_key = ?", (key,))]
    assert any(c["decision"] == "filtered" for c in cells)                           # 거르기(보충 표본이 다시 열었다)
    assert any(c["route_forced"] == review_cells.FILTER_FLOOR for c in cells)        # 표본
    assert any(c["basis"] == review_cells.NOINPUT and c["agent_key"] == MEM1 for c in cells)    # 입력 결손
    assert any(c["agent_key"] == MECH2 and c["reopened_n"] for c in cells)           # 처분 → 다시 마감
    packs = b"".join(gzip.decompress(r["pack_gz"]) for r in risk_store.query("SELECT pack_gz FROM rr_card_packs"))
    assert CANARY.encode() in packs
    assert CANARY in json.dumps([c["body"] for c in fake.calls("run")], ensure_ascii=False)

    me = factories.ident(OWNER)
    agents = [r["key"] for r in ROSTER]
    unit_ids = [u for u in kinds.values()]
    rest = {
        "coverage": routes.get_coverage(key, ident=me),
        "cells": routes.get_cells(key, limit=500, ident=me),
        "cell": [routes.get_cell(key, u, a, ident=me) for u in unit_ids for a in agents],
        "experts": routes.get_experts(key, ident=me),
        "reports_md": [routes.get_expert_report(key, a, part="full", ident=me) for a in agents],
        "reports_json": [routes.get_expert_report(key, a, format="json", ident=me) for a in agents],
        "quality": review_quality.block(risk_store, key),
        "closure": review_cells.closure_cells(risk_store, key),
        "closure_rest": routes.closure_payload(key, owner_sub=OWNER),
        "guide": entry.next_step(me, project_id=risk_store.query_one(
            "SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]),
    }
    factories.act_as_delegate(monkeypatch, OWNER)
    mcp = {
        "coverage": _mcp("risk_get_coverage", target_key=key),
        "cells": _mcp("risk_get_cells", target_key=key, limit=500),
        "reports": [_mcp("risk_get_expert_report", target_key=key, agent_key=a, part="full") for a in agents],
    }
    rendered = {a: expert_report.render_report_md(expert_report.build_report(risk_store, key, a)) for a in agents}
    places = {
        "rest": json.dumps(rest, ensure_ascii=False, default=str),
        "mcp": json.dumps(mcp, ensure_ascii=False, default=str),
        "reports": json.dumps(rendered, ensure_ascii=False),
        "export": "".join(export.iter_lines(risk_store, OWNER, 0)),
        "log": "\n".join(r.getMessage() for when in ("setup", "call") for r in caplog.get_records(when)),
        "audit": json.dumps([dict(r) for r in risk_store.query("SELECT * FROM rr_audit")], ensure_ascii=False, default=str),
    }
    leaks = [where for where, text in places.items() if CANARY in text]
    assert leaks == []
    assert all(places.values())
