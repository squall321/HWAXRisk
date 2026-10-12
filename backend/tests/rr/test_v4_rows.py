# v4 새 표의 이양·폐기 등록과 행 단위 반출·이양·폐기(재설계 M2 C1) — 행은 C2 의 생산자로만 만든다(손 INSERT 금지)
"""C1 은 표와 등록만 넣는다. 새 표에 행을 넣는 생산자(`units.compute`·`units.persist`, 셀 원장의 잡·루프)는 C2 가 짓는다.

행이 든 시험은 아래 자리표시처럼 생산자가 생기면 스스로 붉어지게 둔다 — 전제(생산자 함수)가 없을 때만 기대한 실패이고,
전제가 서면 몸통의 어떤 실패도 그대로 실패다. 통과하면 strict 라 XPASS 로 붉으니 표식을 지운다.
"""
from __future__ import annotations

import gzip
import json

import pytest

from app import export, routes, units
from app.risk_store import RiskStore
from tests import factories

OWNER = factories.OWNER
HEIR = "heir@example.com"
V4_OWNED = ("rr_unit_builds", "rr_units", "rr_expert_reports", "rr_review_cells", "rr_card_verdicts", "rr_review_calls")


class C2ProducerMissing(Exception):
    """C2 의 생산자가 아직 없다 — 자리표시 시험의 기대한 실패는 이것 하나다."""


def _require(module, *names: str) -> None:
    missing = [n for n in names if not hasattr(module, n)]
    if missing:
        raise C2ProducerMissing(f"{module.__name__}.{', '.join(missing)}")


def test_v4_tables_are_registered_for_transfer_and_purge():
    """새 표 여섯은 이양이 owner_sub 를 옮기고 폐기가 원문 열을 비운다. 셀·머리의 폐기는 선점도 비운다(늦은 쓰기 0행 — m-10).
    카드 묶음은 소유자가 없는 박스 지역 사본이라 어디에도 없다."""
    moved = dict(routes.TRANSFER_DERIVED)
    blanked = dict(routes.PURGE_BLANK_SQL)
    assert len(moved) == len(routes.TRANSFER_DERIVED) and len(blanked) == len(routes.PURGE_BLANK_SQL)
    for table in V4_OWNED:
        assert moved[table] == "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)", table
        assert blanked[table].startswith(f"UPDATE {table} SET ") and blanked[table].endswith(moved[table]), table
    for table in ("rr_expert_reports", "rr_review_cells"):
        assert "lease_owner = NULL" in blanked[table], table
    for column in ("cq", "why", "need", "path", "mech_free", "check_text", "conds_json", "checks_json"):
        assert f"{column} = NULL" in blanked["rr_card_verdicts"], column
    assert "result_gz = NULL" in blanked["rr_review_calls"]
    assert "rr_card_packs" not in moved and "rr_card_packs" not in blanked


# ---------------------------------------------------------------- 자리표시 — C2 의 생산자가 생기면 붉어진다
C2_UNITS = pytest.mark.xfail(strict=True, raises=C2ProducerMissing,
                             reason="C2 producer — units.compute·units.persist(m2-wp2 걸음 5)가 생기면 이 표식을 지운다")


def _all_text(store: RiskStore, table: str, where: str, params: tuple) -> str:
    cols = [r["name"] for r in store.query(f"PRAGMA table_info({table})")]
    parts: list[str] = []
    for row in store.query(f"SELECT {', '.join(cols)} FROM {table} WHERE {where}", params):
        for value in row:
            if isinstance(value, bytes):
                value = gzip.decompress(value).decode("utf-8", "replace")
            parts.append("" if value is None else str(value))
    return "\n".join(parts)


@C2_UNITS
def test_unit_rows_round_trip_move_with_the_owner_and_purge_to_no_source_text(risk_store, tmp_path):
    """단위 행 — 반출 → 빈 DB 들여오기에서 BLOB 까지 같고, 이양이 소유자를 옮기며, 폐기 뒤 어느 열에도 부품·재질 이름이
    없다(W2-22). 행은 실제 빌드(units.compute → units.persist)로 만든다."""
    _require(units, "compute", "persist")
    synth = factories.make_diff_target(risk_store, 40)
    built = units.compute(risk_store, "diff", synth.diff_id, owner_sub=OWNER, caps=units.UnitCaps())
    units.persist(risk_store, synth.target_key, OWNER, built, built_by=OWNER)
    scope = ("target_key = ?", (synth.target_key,))
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_unit_builds WHERE target_key = ?", scope[1])["n"] == 1
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_units WHERE target_key = ?", scope[1])["n"] > 0

    dest = RiskStore(tmp_path / "dest" / "risk_review.db")
    dest.open()
    dest.migrate()
    try:
        export.import_jsonl(dest, OWNER, "".join(export.iter_lines(risk_store, OWNER, 0)))
        here, there = export.row_digest(dest, OWNER), export.row_digest(risk_store, OWNER)
        assert {t: here[t] for t in ("rr_unit_builds", "rr_units")} == {t: there[t] for t in ("rr_unit_builds", "rr_units")}
    finally:
        dest.close()

    names = {r["name"] for r in risk_store.query(
        "SELECT name FROM rr_ir_nodes WHERE snapshot_id IN (?, ?) AND name IS NOT NULL",
        (synth.base_snapshot_id, synth.target_snapshot_id)) if len(r["name"]) >= 4}
    names |= {r["m"] for r in risk_store.query(
        "SELECT material_norm AS m FROM rr_ir_nodes WHERE snapshot_id IN (?, ?) AND material_norm IS NOT NULL",
        (synth.base_snapshot_id, synth.target_snapshot_id)) if len(r["m"]) >= 4}
    assert names and any(n in _all_text(risk_store, "rr_units", *scope) for n in names), "심은 이름이 단위에 없다"
    code = risk_store.query_one("SELECT code FROM rr_projects WHERE id = ?", (synth.project_id,))["code"]
    with factories.routes_store(risk_store):
        routes.transfer_project(synth.project_id, routes.TransferBody(to_email=HEIR, reason="담당 교체"),
                                ident=factories.ident(OWNER))
        for table in ("rr_unit_builds", "rr_units"):
            assert risk_store.query_one(f"SELECT COUNT(*) AS n FROM {table} WHERE target_key = ? AND owner_sub <> ?",
                                        (synth.target_key, HEIR))["n"] == 0, table
        routes.purge_project(synth.project_id, routes.PurgeBody(code=code, reason="정리"), ident=factories.ident(HEIR))
    for table in ("rr_unit_builds", "rr_units"):
        text = _all_text(risk_store, table, *scope)
        assert [n for n in sorted(names) if n in text] == [], table
    assert json.loads(risk_store.query_one(
        "SELECT unit_ids_json FROM rr_unit_builds WHERE target_key = ?", scope[1])["unit_ids_json"])  # 정체는 남는다
