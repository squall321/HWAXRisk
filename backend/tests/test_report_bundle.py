# 판정표 → 보고 묶음(RK-05) 시험 — 등록된 facts 틀의 키를 코드마다 전부 채우고(빈 키는 null 과 까닭) · 표기 규칙 · 그림 · 출처 층 · 숫자 원장 참조 · cite · 내보내기 기록
"""HWAXPortal docs/request-1117 RK-05. 요청서의 facts 키 24개는 일부만 알려져 과제 고유 낱말이 섞인다 — 틀은 데이터로 등록하고(context-notes R-2) 이 시험은
합성 키(id · area · part · grade · cad.use · cad.pair …)로 꼴만 본다.

  실행:  .venv/bin/python -m pytest tests/test_report_bundle.py
"""
from __future__ import annotations

import pytest

from app import labels, ledger_routes
from app.errors import AppError
from tests import factories
from tests import ledger_support
from tests.ledger_support import CODES, OWNER, STRANGER, VIEWER, call, seed_ledger

ledger_box = ledger_support.ledger_box          # 판정표 시험 상자(tests/ledger_support.py)를 이 모듈에도 건다

FACTS = {"keys": [
    {"key": "id", "from": "@code"}, {"key": "area", "from": None}, {"key": "part", "from": "부품"}, {"key": "mode", "from": "고장 모드"},
    {"key": "grade", "from": "최종 등급"}, {"key": "evidence_types", "from": "근거 유형"}, {"key": "status", "from": "상태"},
    {"key": "cad.use", "from": None}, {"key": "cad.pair", "from": "@figures"}, {"key": "cad.caption", "from": "비고"},
    {"key": "sources", "from": "@sources"}, {"key": "numbers", "from": "@numbers"}, {"key": "rev", "from": "@version"},
]}


def _seed(box) -> None:
    seed_ledger(box)
    owner = factories.ident(OWNER)
    ledger_routes.put_template(box.target_key, "facts", FACTS, ident=owner)
    ledger_routes.put_numbers(box.target_key, ledger_routes.NumbersBody(numbers=[{"name": "합성 응력", "value": 412.5, "unit": "MPa"}]),
                              ident=owner)
    ledger_routes.post_version(box.target_key, ledger_routes.BuildBody(base_version=2, layers=[
        {"name": "수치 비고", "order": 70, "source_file": "numbers.csv", "rows": {"R-005": {"비고": "응력 412.5 MPa · R-005 확인"}}}]),
        ident=owner)


def test_every_key_is_filled_for_every_code_and_empty_keys_say_why(ledger_box):
    _seed(ledger_box)
    out = ledger_routes.get_report_bundle(ledger_box.target_key, 3, ident=factories.ident(VIEWER))
    assert next(iter(out)) == "notice" and out["version"] == 3 and out["template_version"] == 1
    assert out["counts"]["codes"] == len(CODES) + 1 == len(out["facts"])
    for item in out["facts"]:
        facts = item["facts"]
        assert set(facts) == {"id", "area", "part", "mode", "grade", "evidence_types", "status", "cad", "sources", "numbers", "rev"}
        assert set(facts["cad"]) == {"use", "pair", "caption"} and facts["id"] == item["code"] and facts["rev"] == "v3"
        nulls = {k for k in ("area", "part", "mode", "grade", "evidence_types", "status", "sources", "numbers") if facts[k] is None}
        nulls |= {f"cad.{k}" for k, v in facts["cad"].items() if v is None}
        assert nulls == set(item["null_reasons"]), item
        assert item["null_reasons"]["area"] == "facts 틀에 원장 칸 대응이 없다" and "cad.use" in item["null_reasons"]
    r005 = next(i for i in out["facts"] if i["code"] == "R-005")
    assert r005["facts"]["grade"] == "[등급 C조]" and r005["facts"]["evidence_types"] == "유형⑤"   # 표기 규칙(RK-07)
    assert r005["facts"]["cad"]["pair"] == ["fig-04"] and r005["facts"]["numbers"][0]["name"] == "합성 응력"
    assert [(s["version"], s["layer"]) for s in r005["facts"]["sources"]] == [
        (1, "기준 행"), (2, "앞 회차 행"), (2, "뒤 회차 행"), (2, "수기 수정"), (3, "수치 비고")]
    r001 = next(i for i in out["facts"] if i["code"] == "R-001")
    assert r001["facts"]["cad"]["caption"] is None and r001["null_reasons"]["cad.caption"] == "원장 칸 '비고' 이 이 코드에서 비었다"
    assert r001["null_reasons"]["numbers"] == "이 코드의 칸 글에 숫자 원장의 값이 나오지 않는다"
    assert out["label_check"]["violations_n"] == 0 and labels.check_obj([i["facts"] for i in out["facts"]]) == []
    assert {"version": 3, "order": 70, "layer": "수치 비고", "source_file": "numbers.csv"} in out["sources"]
    assert out["numbers"] == [{"name": "합성 응력", "revision": "", "value_text": "412.5", "unit": "MPa", "metric_key": None,
                               "source_file": None, "line": None}]


def test_the_bundle_carries_a_cite_a_stable_rb_id_and_each_export_is_logged(ledger_box):
    _seed(ledger_box)
    first = ledger_routes.get_report_bundle(ledger_box.target_key, 3, ident=factories.ident(VIEWER))
    again = ledger_routes.get_report_bundle(ledger_box.target_key, 3, ident=factories.ident(OWNER))
    assert first["report_bundle_id"] == again["report_bundle_id"] and first["report_bundle_id"].startswith("rb_")
    assert first["cite"] == {"source_platform": "hwax_risk", "source_kind": "risk_report_bundle", "source_id": first["report_bundle_id"],
                             "source_version": "v3/c1", "scope": {"target_key": ledger_box.target_key, "codes": [*CODES, "R-013"]}}
    logged = ledger_box.store.query("SELECT kind, version, template_version, rows_n, actor, sha256 FROM rr_ledger_exports"
                                    " ORDER BY created_at, export_id")
    assert sorted((r["kind"], r["version"], r["template_version"], r["rows_n"], r["actor"]) for r in logged) == [
        ("report_bundle", 3, 1, 13, OWNER), ("report_bundle", 3, 1, 13, VIEWER)]


def test_a_missing_facts_template_is_said(ledger_box):
    seed_ledger(ledger_box)
    with pytest.raises(AppError) as exc:
        ledger_routes.get_report_bundle(ledger_box.target_key, 2, ident=factories.ident(OWNER))
    assert exc.value.code == "ledger_facts_template_missing" and exc.value.http_status == 409
    with pytest.raises(AppError) as exc:
        ledger_routes.put_template(ledger_box.target_key, "facts", {"keys": [{"key": "x", "from": "없는 칸"}]}, ident=factories.ident(OWNER))
    assert exc.value.http_status == 422


def test_mcp_pages_the_facts_and_logs_once_per_call(ledger_box):
    _seed(ledger_box)
    owner = factories.ident(OWNER)
    rows = {f"R-{i:03d}": {"비고": "긴 비고 " * 200} for i in range(1, 60)}
    ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=3, layers=[
        {"name": "긴 층", "order": 90, "rows": rows}]), ident=owner)
    ledger_box.act_as(VIEWER)
    first = call("risk_export_report_bundle", target_key=ledger_box.target_key, version=4)
    assert 0 < len(first["facts"]) < first["counts"]["codes"] and first["next_offset"]
    rest = call("risk_export_report_bundle", target_key=ledger_box.target_key, version=4, offset=first["next_offset"])
    assert rest["report_bundle_id"] == first["report_bundle_id"] and rest["facts"][0]["code"] != first["facts"][0]["code"]
    assert ledger_box.store.query_one("SELECT COUNT(*) AS n FROM rr_ledger_exports WHERE kind = 'report_bundle'")["n"] == 2
    assert "codes" not in first["cite"]["scope"] and first["sources"] and rest["sources"] == [] and rest["sources_total"] == len(first["sources"])
    assert all(f["code"] in {i["code"] for i in rest["facts"]} for f in rest["figures"])
    ledger_box.act_as(STRANGER)
    assert call("risk_export_report_bundle", target_key=ledger_box.target_key)["error"] == "E404"


def test_mcp_pages_deliver_every_figure_source_and_number_for_400_codes(ledger_box):
    """반대 검토 2차 2 — 쪽 안에서 와이어에 맞추느라 facts 를 자르기 전에 그림 · 출처 · 숫자 목록이 먼저 비었다. 코드 400개(코드마다 그림 둘 · 긴
    비고 · 숫자 원장 값)에서 쪽을 다 받으면 그림은 빠짐없이 그 쪽 코드의 것으로 · 출처 층과 숫자 참조는 첫 쪽에 다 온다."""
    _seed(ledger_box)
    owner = factories.ident(OWNER)
    ledger_routes.put_numbers(ledger_box.target_key, ledger_routes.NumbersBody(numbers=[
        {"name": f"합성 수치 {i:02d}", "value": 7000 + i, "unit": "MPa"} for i in range(60)]), ident=owner)
    new = [f"R-{i:04d}" for i in range(1, 401)]
    layers = [{"name": f"합성 층 {n:02d}", "order": 100 + n, "source_file": f"part-{n:02d}.csv",
               "rows": {code: {"그림": f"fig-{code}-a; fig-{code}-b", "비고": f"값 {7000 + i % 60} MPa " + "긴 비고 " * 40}
                        for i, code in enumerate(new) if i % 30 == n}} for n in range(30)]
    ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=3, layers=layers), ident=owner)
    ledger_box.act_as(VIEWER)
    from app import mcp_server as srv

    full = ledger_routes.get_report_bundle(ledger_box.target_key, 4, ident=factories.ident(VIEWER))
    assert len(full["figures"]) > 800 and len(full["numbers"]) == 60 and len(full["sources"]) > 30
    pages, offset = [], 0
    while True:
        out = call("risk_export_report_bundle", target_key=ledger_box.target_key, version=4, offset=offset)
        assert srv._wire_chars(out) <= srv.MCP_RESULT_CHARS and out["facts"]
        codes = {i["code"] for i in out["facts"]}
        assert all(f["code"] in codes for f in out["figures"]) and len(out["figures"]) <= srv.LIST_CAP
        assert "figures_total" not in out
        pages.append(out)
        if "next_offset" not in out:
            break
        offset = out["next_offset"]
    assert len(pages) >= 5
    assert [i["code"] for p in pages for i in p["facts"]] == [i["code"] for i in full["facts"]]
    assert [f for p in pages for f in p["figures"]] == full["figures"]
    assert pages[0]["sources"] == full["sources"] and pages[0]["numbers"] == full["numbers"]
    assert "sources_total" not in pages[0] and "numbers_total" not in pages[0]
    assert all(p["sources"] == [] and p["sources_total"] == len(full["sources"]) and p["numbers_total"] == 60 for p in pages[1:])
