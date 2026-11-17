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
    assert call("risk_ledger_overview", target_key=ledger_box.target_key)["error"] == "E404"        # 구성원만 — REST 와 같은 거절
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
    assert store.query_one("SELECT notice FROM rr_ledger_versions WHERE version = 2")["notice"] == "[purged]"
    # 회수된 과제의 대상은 쓰지도 읽지도 않는다 — 비운 틀을 읽다 500 이 나지 않고 같은 409 다(반대 검토 L2).
    owner, viewer = factories.ident(OWNER), factories.ident(VIEWER)
    code, status = _refused(ledger_routes.post_layer, ledger_box.target_key,
                            ledger_routes.LayerBody(name="회수 뒤 층", order=99, rows={"R-001": {"비고": "x"}}), ident=owner)
    assert (code, status) == ("project_purged", 409)
    for read in (lambda: ledger_routes.get_ledger(ledger_box.target_key, ident=viewer),
                 lambda: ledger_routes.get_version_diff(ledger_box.target_key, 2, ident=viewer),
                 lambda: ledger_routes.get_version_export(ledger_box.target_key, 2, fmt="csv", ident=viewer),
                 lambda: ledger_routes.get_report_bundle(ledger_box.target_key, 2, ident=viewer),
                 lambda: ledger_routes.post_numbers_check(ledger_box.target_key, ledger_routes.NumbersCheckBody(text="1"), ident=viewer)):
        assert _refused(read) == ("project_purged", 409)
    ledger_box.act_as(VIEWER)
    for tool, args in (("risk_ledger_overview", {}), ("risk_ledger_diff", {"version": 2}), ("risk_ledger_export", {"version": 2}),
                       ("risk_numbers_check", {"text": "1"}), ("risk_export_report_bundle", {})):
        assert call(tool, target_key=ledger_box.target_key, **args)["error"] == "project_purged", tool


def test_purge_blanks_the_number_ledger_keys_and_the_bundle(ledger_box):
    seed_ledger(ledger_box)
    owner = factories.ident(OWNER)
    ledger_routes.put_numbers(ledger_box.target_key, ledger_routes.NumbersBody(
        numbers=[{"name": "합성 응력", "value": 412.5, "unit": "MPa", "revision": "r2", "metric_key": "MET-SYN"}],
        forbidden=[{"code": "R-001", "value": 9.9, "unit": "mm", "reason": "합성 금지"}]), ident=owner)
    bundle = ledger_routes.post_evidence_bundle(ledger_box.target_key, ledger_routes.BundleBody(
        template={"name": "틀", "caps": {"부품": 2000}, "total_cap": 2000}), ident=owner)["bundle_id"]
    routes.purge_project(ledger_box.project_id, routes.PurgeBody(code="LEDGER-1", reason="시험 회수"), ident=owner)
    store = ledger_box.store
    number = dict(store.query_one("SELECT name, revision, value_text, unit, metric_key FROM rr_ledger_numbers"))
    assert number["name"].startswith("[purged:") and number == {**number, "revision": "", "value_text": "0", "unit": None, "metric_key": None}
    ban = dict(store.query_one("SELECT code, value_text, unit, reason FROM rr_ledger_forbidden"))
    assert ban["value_text"].startswith("[purged:") and (ban["unit"], ban["reason"]) == (None, "[purged]")
    assert _refused(ledger_routes.get_evidence_bundle, bundle, ident=factories.ident(VIEWER)) == ("project_purged", 409)


def test_the_csv_export_guards_formula_cells_unless_raw_is_asked(ledger_box):
    """반대 검토 L1 — 스프레드시트가 수식으로 읽는 글 칸(=, +, @, - 뒤 글)을 ' 로 막고 그 수를 말한다. 수 글(-0.3)은 그대로, raw=true 면 원장 그대로다."""
    seed_ledger(ledger_box)
    owner = factories.ident(OWNER)
    ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=2, layers=[{"name": "수식", "order": 60, "rows": {
        "R-001": {"비고": "=HYPERLINK(\"x\")"}, "R-002": {"비고": "+1+1"}, "R-003": {"비고": "@SUM(A1)"}, "R-004": {"비고": "-0.3"},
        "R-005": {"비고": "-PART"}}}]), ident=owner)
    guarded = ledger_routes.get_version_export(ledger_box.target_key, 3, fmt="csv", ident=owner)
    rows = {line[0]: line for line in csv.reader(io.StringIO(guarded.body.decode("utf-8")))}
    assert guarded.headers["X-Formula-Guarded"] == "4"
    assert [rows[c][8] for c in ("R-001", "R-002", "R-003", "R-004", "R-005")] == [
        "'=HYPERLINK(\"x\")", "'+1+1", "'@SUM(A1)", "-0.3", "'-PART"]
    raw = ledger_routes.get_version_export(ledger_box.target_key, 3, fmt="csv", raw=True, ident=owner)
    assert raw.headers["X-Formula-Guarded"] == "0" and "\n" + "R-001" in raw.body.decode("utf-8")
    assert {line[0]: line for line in csv.reader(io.StringIO(raw.body.decode("utf-8")))}["R-001"][8] == "=HYPERLINK(\"x\")"
    ledger_box.act_as(OWNER)
    page = call("risk_ledger_export", target_key=ledger_box.target_key, version=3, fmt="csv")
    assert page["formula_guarded"] == 4 and page["raw"] is False


def test_org_public_projects_do_not_open_the_ledger_to_non_members_over_mcp(ledger_box):
    """사용자 결정(11-17) — 판정표 · 묶음 · 숫자 · 보고 묶음의 MCP 읽기는 구성원만이다(REST 와 같은 문 · 같은 404). 조직 공개 과제라도 열리지 않는다 —
    기존 읽기 도구(등록부)는 그대로 조직 공개로 연다."""
    seed_ledger(ledger_box)
    owner = factories.ident(OWNER)
    bundle = ledger_routes.post_evidence_bundle(ledger_box.target_key, ledger_routes.BundleBody(
        template={"name": "틀", "caps": {"부품": 2000}, "total_cap": 2000}), ident=owner)["bundle_id"]
    ledger_routes.put_template(ledger_box.target_key, "facts", {"keys": [{"key": "id", "from": "@code"}]}, ident=owner)
    ledger_box.store.execute("UPDATE rr_projects SET mcp_visibility = 'org' WHERE id = ?", (ledger_box.project_id,))
    rest = _refused(ledger_routes.get_ledger, ledger_box.target_key, ident=factories.ident(STRANGER))
    ledger_box.act_as(STRANGER)
    assert "error" not in call("risk_get_registry", target_key=ledger_box.target_key)          # 기존 도구는 조직 공개로 연다
    for tool, args in (("risk_ledger_overview", {"target_key": ledger_box.target_key}),
                       ("risk_ledger_diff", {"target_key": ledger_box.target_key, "version": 2}),
                       ("risk_ledger_export", {"target_key": ledger_box.target_key}),
                       ("risk_numbers_check", {"target_key": ledger_box.target_key, "text": "1"}),
                       ("risk_export_report_bundle", {"target_key": ledger_box.target_key}),
                       ("risk_get_evidence_bundle", {"bundle_id": bundle})):
        got = call(tool, **args)
        assert got.get("error") == rest[0] == "E404", (tool, got)
    ledger_box.act_as(VIEWER)
    assert call("risk_ledger_overview", target_key=ledger_box.target_key)["latest_version"] == 2


def test_mcp_summary_lists_are_capped_with_their_totals(ledger_box):
    """반대 검토 M5 — 쪽으로 나누지 않는 요약 목록(든 · 빠진 · 등급 바뀐 코드)이 쪽마다 되풀이되어 와이어를 넘을 수 있었다 — 앞 200개와 <칸>_total."""
    seed_ledger(ledger_box)
    owner = factories.ident(OWNER)
    ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=2, layers=[{"name": "많은 새 코드", "order": 60,
        "rows": {f"N-{i:04d}": {"비고": "새 행"} for i in range(1, 451)}}]), ident=owner)
    ledger_box.act_as(VIEWER)
    out = call("risk_ledger_diff", target_key=ledger_box.target_key, version=3)
    assert len(out["codes_added"]) == 200 and out["codes_added_total"] == 450
    from app import mcp_server as srv

    assert srv._wire_chars(out) <= srv.MCP_RESULT_CHARS


def _pages(tool: str, **args) -> list[dict]:
    from app import mcp_server as srv

    pages, offset = [], 0
    while True:
        out = call(tool, **args, offset=offset)
        assert "error" not in out, out
        assert srv._wire_chars(out) <= srv.MCP_RESULT_CHARS, (tool, offset, srv._wire_chars(out))
        pages.append(out)
        if "next_offset" not in out:
            return pages
        assert out["next_offset"] > offset
        offset = out["next_offset"]


def test_mcp_diff_summary_lists_keep_200_on_every_page_while_the_changes_page(ledger_box):
    """반대 검토 2차 1 — 요약 목록을 바뀐 칸 전부와 같이 재어 반씩 줄이던 탓에 바뀐 칸이 많으면 든 코드 목록이 비었다. 이제 요약 목록은 쪽마다 앞
    200개와 <칸>_total 이고, 바뀐 칸은 쪽으로 빠짐없이 온다."""
    seed_ledger(ledger_box)
    owner = factories.ident(OWNER)
    rows = {f"N-{i:04d}": {"비고": "새 행"} for i in range(1, 451)}
    rows.update({code: {"비고": "긴 비고 " * 900, "고장 모드": "긴 모드 " * 900} for code in CODES})
    ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=2, layers=[
        {"name": "새 코드와 긴 수정", "order": 60, "rows": rows}]), ident=owner)
    ledger_box.act_as(VIEWER)
    pages = _pages("risk_ledger_diff", target_key=ledger_box.target_key, version=3)
    rest = ledger_routes.get_version_diff(ledger_box.target_key, 3, ident=factories.ident(VIEWER))
    assert len(pages) >= 3
    for out in pages:
        assert out["codes_added"] == rest["codes_added"][:200] and out["codes_added_total"] == 450
        assert out["codes_removed"] == rest["codes_removed"] and "codes_removed_total" not in out
        assert out["changed_cells_n"] == rest["changed_cells_n"]
    assert [c for out in pages for c in out["changes"]] == rest["changes"]


def test_cap_lists_slices_shrinks_only_when_told_and_can_keep_the_newest():
    from app import mcp_server as srv

    out = {"a": list(range(300)), "b": list(range(10)), "big": "x" * 50_000}
    sliced = srv._cap_lists(out, ("a", "b"))
    assert sliced["a"] == list(range(200)) and sliced["a_total"] == 300 and sliced["b"] == list(range(10)) and "b_total" not in sliced
    newest = srv._cap_lists(out, ("a", "b"), newest=True)
    assert newest["a"] == list(range(100, 300)) and newest["a_total"] == 300 and newest["a_older_omitted"] == 100
    assert "b_older_omitted" not in newest
    shrunk = srv._cap_lists(out, ("a", "b"), fits=lambda got: len(got["a"]) + len(got["b"]) <= 60)
    assert len(shrunk["a"]) + len(shrunk["b"]) <= 60 and shrunk["a_total"] == 300 and shrunk["a"] == list(range(len(shrunk["a"])))
    again = srv._cap_lists(shrunk, ("a",), fits=lambda got: len(got["a"]) <= 10)
    assert again["a_total"] == 300                    # 이미 적힌 원래 수를 그대로 쓴다


def test_mcp_overview_keeps_the_newest_layers_and_says_how_many_older_were_left_out(ledger_box):
    """반대 검토 2차 7 — 한눈이 가장 옛 200개를 두었다. 이제 가장 새 것을 두고(와이어에 맞게 더 줄일 때도 옛 것부터 버린다) 버린 옛 것의 수를 적는다."""
    seed_ledger(ledger_box)
    owner = factories.ident(OWNER)
    for i in range(1, 251):
        ledger_routes.post_layer(ledger_box.target_key, ledger_routes.LayerBody(
            name=f"합성 층 {i:03d}", order=100 + i, rows={"R-001": {"비고": f"층 {i}"}}), ident=owner)
    ledger_box.act_as(VIEWER)
    out = call("risk_ledger_overview", target_key=ledger_box.target_key)
    from app import mcp_server as srv

    rest = ledger_routes.get_ledger(ledger_box.target_key, ident=factories.ident(VIEWER))
    kept = out["layers"]
    assert srv._wire_chars(out) <= srv.MCP_RESULT_CHARS and 0 < len(kept) <= 200
    assert kept == rest["layers"][-len(kept):] and kept[-1]["name"] == "합성 층 250"
    assert out["layers_total"] == len(rest["layers"]) and out["layers_older_omitted"] == len(rest["layers"]) - len(kept)
    assert out["versions"] == rest["versions"] and "versions_older_omitted" not in out


V8_TABLES = ("rr_ledger_templates", "rr_ledger_layers", "rr_ledger_versions", "rr_ledger_rows", "rr_ledger_cells", "rr_evidence_bundles",
             "rr_ledger_numbers", "rr_ledger_forbidden", "rr_ledger_exports")


def test_an_ownership_transfer_moves_every_ledger_row_to_the_new_owner(ledger_box):
    """반대 검토 M2 — 이양이 v8 표 아홉을 옮기지 않아 새 주인의 읽기(대상 주인의 행) · 반출에서 판정표가 사라졌다. 이양 뒤 옛 주인 행은 0 이고 새
    주인이 그대로 읽는다."""
    seed_ledger(ledger_box)
    owner = factories.ident(OWNER)
    ledger_routes.post_evidence_bundle(ledger_box.target_key, ledger_routes.BundleBody(
        template={"name": "틀", "caps": {"부품": 2000}, "total_cap": 2000}), ident=owner)
    ledger_routes.put_numbers(ledger_box.target_key, ledger_routes.NumbersBody(
        numbers=[{"name": "합성 값", "value": 1.5}], forbidden=[{"code": "*", "value": 9.9, "reason": "합성 금지값"}]), ident=owner)
    ledger_routes.get_version_export(ledger_box.target_key, 2, fmt="json", ident=owner)
    moved = dict(routes.TRANSFER_DERIVED)
    assert all(table in moved for table in V8_TABLES)
    assert all(ledger_box.store.query_one(f"SELECT COUNT(*) AS n FROM {t}")["n"] > 0 for t in V8_TABLES)
    out = routes.transfer_project(ledger_box.project_id, routes.TransferBody(to_email=EDITOR, reason="담당 교체"), ident=owner)
    for table in V8_TABLES:
        assert ledger_box.store.query_one(f"SELECT COUNT(*) AS n FROM {table} WHERE owner_sub != ?", (EDITOR,))["n"] == 0, table
        assert out["rows_updated"]["tables"].get(table), table
    assert ledger_routes.get_ledger(ledger_box.target_key, ident=factories.ident(EDITOR))["latest_version"] == 2
