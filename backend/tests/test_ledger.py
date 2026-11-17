# 판정표 원장(RK-01) 시험 — 칸 정의 판 · 층 다섯의 덮어쓰기 차례(뒤 층이 이긴다 · 덮은 앞 값) · 판 비교(등급 바뀐 코드 수) · csv/json 내보내기(첫 줄 보안 문구) · 문(구성원 읽기 · 편집자 쓰기)
"""HWAXPortal docs/request-1117 RK-01. 합성 자료(tests/ledger_support.py)로 요청서의 꼴을 재현한다 — 층 다섯(기준 행 → 앞 회차 → 뒤 회차 → 수기
수정 → 이어하기 결과), 뒤 층이 이기고 덮은 앞 값이 칸마다 남으며 등급이 바뀐 코드를 센다. PC 의 실제 판정표 대조는 PC 수용 절차의 몫이다.

  실행:  .venv/bin/python -m pytest tests/test_ledger.py
"""
from __future__ import annotations

import csv
import io
import json

import pytest

from app import export, ledger, ledger_routes, routes
from app.errors import AppError
from tests import factories
from tests import ledger_support
from tests.ledger_support import CODES, COLUMNS, EDITOR, OWNER, STRANGER, VIEWER, call, seed_ledger

ledger_box = ledger_support.ledger_box          # 판정표 시험 상자(tests/ledger_support.py)를 이 모듈에도 건다


def _refused(fn, *args, **kwargs) -> tuple[str, int]:
    with pytest.raises(AppError) as exc:
        fn(*args, **kwargs)
    return exc.value.code, exc.value.http_status


def test_five_layers_overwrite_in_order_and_keep_every_overwritten_value(ledger_box):
    """뒤 층이 이긴다 — R-005 의 최종 등급은 앞 회차 A → 뒤 회차 B → 수기 C 로 덮여 C 이고, 덮은 칸마다 그 앞 값이 차례대로 남는다. 새 코드
    (이어하기의 R-013)는 행이 늘고, 행 수는 행으로 센다."""
    built = seed_ledger(ledger_box)
    v2 = built["v2"]
    assert v2["created"] is True and v2["version"] == 2 and v2["based_on"] == 1 and v2["rows_n"] == len(CODES) + 1
    assert [(x["name"], x["order"], x["cells"], x["changed"], x["new_codes"]) for x in v2["layers"]] == [
        ("앞 회차 행", 20, 5, 3, 0), ("뒤 회차 행", 30, 4, 3, 0), ("수기 수정", 40, 3, 3, 0), ("이어하기 결과", 50, 4, 4, 1)]
    rows = ledger.version_rows(ledger_box.store, ledger_box.target_key, 2)
    assert rows["R-005"]["최종 등급"] == "C" and rows["R-005"]["결정 출처"] == "수기"
    assert rows["R-004"]["최종 등급"] == "A" and rows["R-004"]["결정 출처"] == "뒤 회차"
    assert rows["R-013"] == {"부품": "PART-Z", "최종 등급": "B", "결정 출처": "이어하기"}
    trail = ledger_box.store.query(
        "SELECT layer_name, layer_order, source_file, value_json, prev_json FROM rr_ledger_cells"
        " WHERE target_key = ? AND version = 2 AND code = 'R-005' AND col = '최종 등급' ORDER BY seq", (ledger_box.target_key,))
    assert [(r["layer_name"], r["layer_order"], r["source_file"], json.loads(r["prev_json"]), json.loads(r["value_json"]))
            for r in trail] == [("앞 회차 행", 20, "round-a.csv", "B", "A"), ("뒤 회차 행", 30, "round-b.csv", "A", "B"),
                                ("수기 수정", 40, "manual-fix.csv", "B", "C")]
    new_cell = ledger_box.store.query_one("SELECT prev_json FROM rr_ledger_cells WHERE target_key = ? AND version = 2"
                                          " AND code = 'R-013' AND col = '부품'", (ledger_box.target_key,))
    assert new_cell["prev_json"] is None
    # 등급 칸(1차 · 최종) 가운데 하나라도 바뀐 코드 — 두 판에 다 있는 코드만 센다(R-013 은 추가다).
    assert v2["grade_changed_n"] == 2 and v2["grade_changed_codes"] == ["R-005", "R-007"]


def test_the_same_build_twice_is_the_same_version_and_order_ties_are_refused(ledger_box):
    built = seed_ledger(ledger_box)
    owner = factories.ident(OWNER)
    layer_ids = [x["layer_id"] for x in built["v2"]["layers"]]
    again = ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=1, layers=list(reversed(layer_ids))),
                                       ident=owner)
    assert again["created"] is False and again["version"] == 2           # 목록 차례가 아니라 order 가 차례다
    tie = {"name": "겹친 차례", "order": 20, "rows": {"R-001": {"비고": "x"}}}
    code, status = _refused(ledger_routes.post_version, ledger_box.target_key,
                            ledger_routes.BuildBody(base_version=1, layers=[layer_ids[0], tie]), ident=owner)
    assert (code, status) == ("E100", 422)


def test_a_layer_with_a_column_outside_the_definition_is_refused_and_columns_are_data(ledger_box):
    owner = factories.ident(OWNER)
    code, status = _refused(ledger_routes.post_layer, ledger_box.target_key,
                            ledger_routes.LayerBody(name="층", order=1, rows={"R-001": {"비고": "x"}}), ident=owner)
    assert (code, status) == ("ledger_columns_missing", 409)
    first = ledger_routes.put_template(ledger_box.target_key, "columns", COLUMNS, ident=owner)
    assert first["version"] == 1 and first["created"] is True
    assert ledger_routes.put_template(ledger_box.target_key, "columns", COLUMNS, ident=owner)["created"] is False
    with pytest.raises(AppError) as exc:
        ledger_routes.post_layer(ledger_box.target_key, ledger_routes.LayerBody(name="층", order=1, rows={"R-001": {"없는 칸": 1}}),
                                 ident=owner)
    assert exc.value.code == "ledger_unknown_columns" and exc.value.detail["unknown_columns"] == ["없는 칸"]
    # 칸을 더한 새 칸 정의 판 — 판 번호가 오르고 그 칸을 받는다.
    wider = {**COLUMNS, "columns": [*COLUMNS["columns"], {"name": "추가 칸", "order": 10}]}
    assert ledger_routes.put_template(ledger_box.target_key, "columns", wider, ident=owner)["version"] == 2
    assert ledger_routes.post_layer(ledger_box.target_key, ledger_routes.LayerBody(name="층", order=1, rows={"R-001": {"추가 칸": 1}}),
                                    ident=owner)["colset_version"] == 2


@pytest.mark.parametrize("name", ["FAIL 사유", "치명 여부", "ok"])
def test_a_column_named_with_a_judgement_word_is_refused(ledger_box, name):
    """근거 칸 이름에 판정 낱말을 쓰면 좌석이 그 이름을 판정으로 인용한다(요청서 RK-02 함정) — 칸 정의에서 받지 않는다."""
    body = {"columns": [{"name": name, "order": 1}]}
    assert _refused(ledger_routes.put_template, ledger_box.target_key, "columns", body, ident=factories.ident(OWNER)) == ("E100", 422)


def test_diff_names_changed_codes_columns_before_after_and_counts_rows_not_lines(ledger_box):
    """값 안의 줄바꿈은 행 수를 바꾸지 않는다(요청서 함정 — 파일 줄을 행으로 셌다)."""
    seed_ledger(ledger_box)
    owner = factories.ident(OWNER)
    ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=2, layers=[
        {"name": "여러 줄 비고", "order": 60, "rows": {"R-003": {"비고": "첫 줄\n둘째 줄\n셋째 줄"}}}]), ident=owner)
    diff = ledger_routes.get_version_diff(ledger_box.target_key, 3, ident=factories.ident(VIEWER))
    assert diff["rows_n"] == {"base": 13, "version": 13} and diff["changed_cells_n"] == 1
    assert diff["changes"] == [{"code": "R-003", "column": "비고", "before": "", "after": "첫 줄\n둘째 줄\n셋째 줄"}]
    full = ledger_routes.get_version_diff(ledger_box.target_key, 2, base=1, ident=factories.ident(VIEWER))
    assert full["codes_added"] == ["R-013"] and full["codes_removed"] == []
    assert full["grade_changed_n"] == 2 and full["grade_columns"] == ["1차 등급", "최종 등급"]
    assert {(c["code"], c["column"]) for c in full["changes"]} >= {("R-005", "최종 등급"), ("R-002", "비고")}
    assert [c for c in full["changes"] if c["code"] == "R-005" and c["column"] == "최종 등급"][0] == {
        "code": "R-005", "column": "최종 등급", "before": "B", "after": "C"}


def test_csv_and_json_exports_start_with_the_notice_and_round_trip_the_cells(ledger_box):
    seed_ledger(ledger_box)
    viewer = factories.ident(VIEWER)
    response = ledger_routes.get_version_export(ledger_box.target_key, 2, fmt="csv", ident=viewer)
    text = response.body.decode("utf-8")
    lines = list(csv.reader(io.StringIO(text)))
    assert lines[0] == [ledger.NOTICE_DEFAULT]
    assert lines[1] == ["코드", *[c["name"] for c in COLUMNS["columns"]]]
    assert len(lines) - 2 == 13 and lines[2][0] == "R-001" and lines[-1][0] == "R-013"
    rows = ledger.version_rows(ledger_box.store, ledger_box.target_key, 2)
    for line in lines[2:]:
        want = rows[line[0]]
        assert line[1:] == ["" if want.get(c["name"]) is None else want[c["name"]] for c in COLUMNS["columns"]]
    table = ledger_routes.get_version_export(ledger_box.target_key, 2, fmt="json", ident=viewer)
    assert next(iter(table)) == "notice" and table["rows_n"] == 13 and table["rows"][4]["최종 등급"] == "C"
    logged = ledger_box.store.query("SELECT kind, version, rows_n, actor FROM rr_ledger_exports ORDER BY created_at, export_id")
    assert sorted((r["kind"], r["version"], r["rows_n"], r["actor"]) for r in logged) == [
        ("csv", 2, 13, VIEWER), ("json", 2, 13, VIEWER)]
    with pytest.raises(AppError):
        ledger_routes.get_version_export(ledger_box.target_key, 2, fmt="xlsx", ident=viewer)


def test_members_read_editors_write_and_strangers_see_nothing(ledger_box):
    seed_ledger(ledger_box)
    assert ledger_routes.get_ledger(ledger_box.target_key, ident=factories.ident(VIEWER))["latest_version"] == 2
    assert _refused(ledger_routes.get_ledger, ledger_box.target_key, ident=factories.ident(STRANGER)) == ("E404", 404)
    body = ledger_routes.LayerBody(name="보기 층", order=99, rows={"R-001": {"비고": "x"}})
    assert _refused(ledger_routes.post_layer, ledger_box.target_key, body, ident=factories.ident(VIEWER)) == ("role_insufficient", 403)
    assert _refused(ledger_routes.post_layer, ledger_box.target_key, body, ident=factories.ident(STRANGER)) == ("E404", 404)
    made = ledger_routes.post_layer(ledger_box.target_key, body, ident=factories.ident(EDITOR))
    row = ledger_box.store.query_one("SELECT owner_sub, created_by FROM rr_ledger_layers WHERE layer_id = ?", (made["layer_id"],))
    assert dict(row) == {"owner_sub": OWNER, "created_by": EDITOR}       # 행은 과제 주인의 것, 쓴 사람은 편집자
    overview = ledger_routes.get_ledger(ledger_box.target_key, ident=factories.ident(OWNER))
    assert [x["used"] for x in overview["layers"] if x["layer_id"] == made["layer_id"]] == [False]


def test_mcp_tools_take_the_same_gates_and_page_within_the_wire(ledger_box):
    seed_ledger(ledger_box)
    ledger_box.act_as(None)
    assert call("risk_ledger_put_layer", target_key=ledger_box.target_key, name="층", order=1,
                rows={"R-001": {"비고": "x"}})["error"] == "delegation_required"
    ledger_box.act_as(VIEWER)
    assert call("risk_ledger_put_layer", target_key=ledger_box.target_key, name="층", order=1,
                rows={"R-001": {"비고": "x"}})["error"] == "role_insufficient"
    assert call("risk_ledger_overview", target_key=ledger_box.target_key)["latest_version"] == 2
    ledger_box.act_as(STRANGER)
    assert call("risk_ledger_overview", target_key=ledger_box.target_key)["error"] == "not_visible"
    ledger_box.act_as(EDITOR)
    out = call("risk_ledger_build", target_key=ledger_box.target_key, base_version=2,
               layers=[{"name": "MCP 층", "order": 70, "rows": {code: {"비고": "가" * 3000} for code in CODES}}])
    assert out["version"] == 3 and out["created"] is True
    first = call("risk_ledger_diff", target_key=ledger_box.target_key, version=3)
    assert first["changed_cells_n"] == len(CODES) and 0 < len(first["changes"]) < len(CODES) and first["next_offset"]
    rest = call("risk_ledger_diff", target_key=ledger_box.target_key, version=3, offset=first["next_offset"])
    assert len(first["changes"]) + sum(1 for _ in rest["changes"]) <= len(CODES)
    page = call("risk_ledger_export", target_key=ledger_box.target_key, version=3, fmt="csv")
    assert page["text"].splitlines()[0] == ledger.NOTICE_DEFAULT and page["next_offset"] < 13
    assert ledger_box.store.query_one("SELECT COUNT(*) AS n FROM rr_ledger_exports")["n"] == 1    # 쪽을 재느라 여러 번 기록하지 않는다


def test_ledger_rows_ride_the_export_and_import_with_their_target(ledger_box, tmp_path):
    """v8 표가 반출 · 들여오기로 왕복한다 — 행 수 · 해시가 같다(대상의 과제를 따라 실린다)."""
    from app.risk_store import RiskStore

    seed_ledger(ledger_box)
    body = "".join(export.iter_lines(ledger_box.store, OWNER, 0))
    other = RiskStore(tmp_path / "other.db")
    other.open()
    other.migrate()
    try:
        export.import_jsonl(other, OWNER, body)
        here, there = export.row_digest(other, OWNER), export.row_digest(ledger_box.store, OWNER)
        for table in ("rr_ledger_templates", "rr_ledger_layers", "rr_ledger_versions", "rr_ledger_rows", "rr_ledger_cells"):
            assert here[table] == there[table] and there[table][0] > 0, table
    finally:
        other.close()


def test_purge_blanks_the_ledger_text_but_keeps_the_heads(ledger_box):
    seed_ledger(ledger_box)
    routes.purge_project(ledger_box.project_id, routes.PurgeBody(code="LEDGER-1", reason="시험 회수"), ident=factories.ident(OWNER))
    store = ledger_box.store
    assert {r["cells_json"] for r in store.query("SELECT cells_json FROM rr_ledger_rows")} == {"{}"}
    assert {r["body_json"] for r in store.query("SELECT body_json FROM rr_ledger_templates")} == {"{}"}
    assert {r["source_file"] for r in store.query("SELECT source_file FROM rr_ledger_layers")} == {None}
    assert store.query_one("SELECT rows_n FROM rr_ledger_versions WHERE version = 2")["rows_n"] == 13
    # 회수된 과제의 대상에는 더 쓰지 않는다(읽기는 그대로 — 비운 글이다).
    code, status = _refused(ledger_routes.post_layer, ledger_box.target_key,
                            ledger_routes.LayerBody(name="회수 뒤 층", order=99, rows={"R-001": {"비고": "x"}}), ident=factories.ident(OWNER))
    assert (code, status) == ("project_purged", 409)
