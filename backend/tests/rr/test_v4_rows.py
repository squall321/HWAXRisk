# v4 새 표의 이양·폐기 등록과 행 단위 반출·이양·폐기(재설계 M2 C1) — 행은 C2 의 생산자로만 만든다(손 INSERT 금지)
"""C1 은 표와 등록만 넣었다. 단위 행의 생산자(`units.compute`·`units.persist`)는 C2a 에 섰고 셀 원장의 생산자(잡·루프)는 C2b 다.

생산자가 아직 없는 행의 시험은 자리표시로 두어 생산자가 생기면 스스로 붉어지게 한다 — 전제(생산자 함수)가 없을 때만 기대한
실패이고, 전제가 서면 몸통의 어떤 실패도 그대로 실패다. 통과하면 strict 라 XPASS 로 붉으니 표식을 지운다.
"""
from __future__ import annotations

import ast
import gzip
import json
import re
from pathlib import Path

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


# ---------------------------------------------------------------- 단위 행(C2a 의 생산자 units.compute·units.persist)
def _all_text(store: RiskStore, table: str, where: str, params: tuple) -> str:
    cols = [r["name"] for r in store.query(f"PRAGMA table_info({table})")]
    parts: list[str] = []
    for row in store.query(f"SELECT {', '.join(cols)} FROM {table} WHERE {where}", params):
        for value in row:
            if isinstance(value, bytes):
                value = gzip.decompress(value).decode("utf-8", "replace")
            parts.append("" if value is None else str(value))
    return "\n".join(parts)


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


def test_every_exported_row_passes_through_the_export_view(risk_store, monkeypatch):
    """반출 줄은 전부 export._export_view 를 지난다(RC-7) — 판정 행 인용을 200자로 줄이는 규칙(M2.md 2절)이 그 한 함수에 걸려 있어,
    _select 에서 그 호출이 빠지면 규칙이 조용히 꺼진다. 판정 행의 생산자(C2b)가 서기 전이라 단위 행으로 배선을 본다 — 표지를 다는
    뷰로 바꿔 끼우면 모든 줄에 그 표의 표지가 있다(인용 줄이기의 왕복은 판정 행 생산자가 서는 커밋이 본다)."""
    synth = factories.make_diff_target(risk_store, 40)
    units.build_units(risk_store, synth.target_key, built_by=OWNER)
    real = export._export_view

    def marked(table: str, row: dict) -> dict:
        return {**real(table, row), "_viewed": table}

    monkeypatch.setattr(export, "_export_view", marked)
    lines = [json.loads(line) for line in list(export.iter_lines(risk_store, OWNER, 0))[1:]]
    assert {"rr_unit_builds", "rr_units"} <= {item["table"] for item in lines}
    assert [item["table"] for item in lines if item["row"].get("_viewed") != item["table"]] == []


# ---------------------------------------------------------------- 판정 행을 고쳐 쓰면 updated_at 을 올린다(since 반출 — 앞으로의 위험 2)
_VERDICT_UPDATE = re.compile(r"\bUPDATE\s+rr_card_verdicts\s+SET\b(?P<sets>.*)", re.I | re.S)
_VERDICT_REWRITE = re.compile(r"\b(?:INSERT\s+OR\s+REPLACE|REPLACE)\s+INTO\s+rr_card_verdicts\b"
                              r"|\bINTO\s+rr_card_verdicts\b.*\bON\s+CONFLICT\b.*\bDO\s+UPDATE\b", re.I | re.S)
_RECOMPUTED = ("is_effective", "agree", "split")


def verdict_rewrites_without_touch(sources: dict[str, str]) -> list[str]:
    """판정 행의 is_effective·agree·split 을 고쳐 쓰는 SQL 가운데 updated_at 을 같이 쓰지 않는 것('파일:줄').

    UPDATE 는 SET 절을 본다 — 그 셋 가운데 하나를 쓰거나 SET 절을 글로 볼 수 없으면(f-문자열 자리·'SET ' 뒤를 이어 붙인다)
    updated_at 이 그 글에 있어야 한다. 행을 통째로 다시 쓰는 REPLACE·ON CONFLICT DO UPDATE 는 늘 있어야 한다. 처음 쓰는 INSERT 는
    보지 않는다(updated_at NULL 이면 since 반출이 created_at 을 본다)."""
    found: list[tuple[str, int]] = []
    for name, text in sources.items():
        tree = ast.parse(text)
        inner = {id(v) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for v in node.values}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in inner:
                sql = node.value
            elif isinstance(node, ast.JoinedStr):
                sql = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
            else:
                continue
            hit = _VERDICT_UPDATE.search(sql)
            if hit is not None:
                sets = re.split(r"\bWHERE\b", hit.group("sets"), flags=re.I)[0]
                rewrites = "{}" in sets or not sets.strip() or any(re.search(rf"\b{c}\b", sets) for c in _RECOMPUTED)
                clause = sets
            else:
                rewrites, clause = _VERDICT_REWRITE.search(sql) is not None, sql
            if rewrites and "updated_at" not in clause:
                found.append((name, node.lineno))
    return [f"{name}:{line}" for name, line in sorted(found)]


def test_rewriting_a_verdict_row_bumps_its_updated_at():
    """판정 행은 rev·solo 결과가 온 뒤 fwd 행의 is_effective·agree·split 을 고쳐 쓴다(C2b) — 그 문장은 updated_at 을 같이 올린다.
    since 반출은 updated_at → created_at 순으로 보므로(export._SINCE_COLS) 올리지 않으면 고침이 반출에서 빠진다. 앱 소스 전부를
    훑는다(트리거는 마이그레이션 허용 연산 밖이라 쓰지 않는다)."""
    assert export._SINCE_COLS["rr_card_verdicts"] == ("updated_at", "created_at")
    app_dir = Path(export.__file__).resolve().parent
    sources = {p.relative_to(app_dir.parent).as_posix(): p.read_text(encoding="utf-8") for p in sorted(app_dir.rglob("*.py"))}
    assert any("UPDATE rr_card_verdicts SET" in text for text in sources.values()), "폐기 문장을 못 찾았다 — 가드가 죽었다"
    assert verdict_rewrites_without_touch(sources) == []


def test_the_verdict_touch_guard_actually_catches_rewrites():
    planted = {"planted.py": "\n".join((
        'a = "UPDATE rr_card_verdicts SET is_effective = ?, split = ? WHERE target_key = ?"',
        'b = "UPDATE rr_card_verdicts SET agree = ?, updated_at = ? WHERE target_key = ?"',
        'c = f"UPDATE rr_card_verdicts SET {sets} WHERE target_key = ?"',
        'd = "UPDATE rr_card_verdicts SET " + ", ".join(cols)',
        'e = "UPDATE rr_card_verdicts SET cq = NULL WHERE split = 1"',
        'f = "INSERT OR REPLACE INTO rr_card_verdicts(target_key) VALUES (?)"',
        'g = ("INSERT INTO rr_card_verdicts(target_key) VALUES (?)"',
        '     " ON CONFLICT(target_key) DO UPDATE SET is_effective = excluded.is_effective")',
        'h = "INSERT INTO rr_card_verdicts(target_key, created_at) VALUES (?, ?)"',
        'i = f"UPDATE rr_card_verdicts SET is_effective = {x}, updated_at = {now} WHERE k = ?"',
    ))}
    assert verdict_rewrites_without_touch(planted) == ["planted.py:1", "planted.py:3", "planted.py:4", "planted.py:6",
                                                       "planted.py:7"]


def _caps(monkeypatch, **values) -> None:
    import dataclasses

    from app import config

    names = {"target_lines": "risk_unit_target_lines", "max_lines": "risk_unit_max_lines",
             "small_lines": "risk_units_small_lines"}
    monkeypatch.setattr(config, "settings", dataclasses.replace(
        config.settings, **{names[k]: v for k, v in values.items()}))


def _exported(store: RiskStore, since: int) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for line in list(export.iter_lines(store, OWNER, since))[1:]:
        item = json.loads(line)
        out.setdefault(item["table"], []).append(item["row"])
    return out


T1, T2 = 1_900_000_000, 1_900_086_400          # 두 빌드의 시각 — 합성 과제의 다른 행(현재 시각·캡처 시각)보다 뒤다


def test_a_since_export_carries_only_the_unit_rows_written_after_it(risk_store, monkeypatch):
    """반출의 since 열 — 빌드 머리는 쓴 시각(built_at), 단위는 처음 쓴 시각(created_at)이다. 상한을 바꾼 둘째 빌드 뒤의 반출에는
    둘째 rev 머리와 그때 처음 쓴 단위만 실리고, since 0 은 둘 다 싣는다."""
    synth = factories.make_diff_target(risk_store, 40)
    monkeypatch.setattr(units, "now_epoch", lambda: T1)
    units.build_units(risk_store, synth.target_key, built_by=OWNER)
    first = {uid for uid, _ in units.active_build(risk_store, synth.target_key)["unit_ids"]}
    _caps(monkeypatch, target_lines=8, max_lines=12, small_lines=4)
    monkeypatch.setattr(units, "now_epoch", lambda: T2)
    units.build_units(risk_store, synth.target_key, built_by=OWNER)
    second = {uid for uid, _ in units.active_build(risk_store, synth.target_key)["unit_ids"]}
    assert first and second and not first & second

    later = _exported(risk_store, T2)
    assert [r["rev"] for r in later["rr_unit_builds"]] == [2]
    assert {r["unit_id"] for r in later["rr_units"]} == second
    everything = _exported(risk_store, 0)
    assert [r["rev"] for r in everything["rr_unit_builds"]] == [1, 2]
    assert {r["unit_id"] for r in everything["rr_units"]} == first | second


def test_imported_rows_never_let_an_older_rev_become_the_active_build(risk_store, tmp_path, monkeypatch):
    """활성 빌드는 '살아 있는 status 의 가장 큰 rev' 라 들여온 행이 옛 rev 를 되살리지 않는다(W2-13 e) — 옛 rev 만 있는 박스에
    새 rev 를 들여오면 새 rev 가 활성이고, 그 뒤에 옛 반출을 다시 들여와도 그대로다. 들여온 박스의 단위·엔진 몫 unit 은 원본과 같다."""
    synth = factories.make_diff_target(risk_store, 40)
    monkeypatch.setattr(units, "now_epoch", lambda: T1)
    units.build_units(risk_store, synth.target_key, built_by=OWNER)
    old_export = "".join(export.iter_lines(risk_store, OWNER, 0))

    dest = RiskStore(tmp_path / "dest" / "risk_review.db")
    dest.open()
    dest.migrate()
    try:
        export.import_jsonl(dest, OWNER, old_export)
        assert units.active_build(dest, synth.target_key)["rev"] == 1

        _caps(monkeypatch, target_lines=8, max_lines=12, small_lines=4)
        monkeypatch.setattr(units, "now_epoch", lambda: T2)
        units.build_units(risk_store, synth.target_key, built_by=OWNER)
        result = export.import_jsonl(dest, OWNER, "".join(export.iter_lines(risk_store, OWNER, T2)))
        assert result["conflicts"] == [] and result["inserted"] > 1
        assert units.active_build(dest, synth.target_key)["rev"] == 2

        again = export.import_jsonl(dest, OWNER, old_export)
        assert again["inserted"] == 0 and again["conflicts"] == []
        here = units.active_build(dest, synth.target_key)
        there = units.active_build(risk_store, synth.target_key)
        assert here["rev"] == 2 and here["unit_ids"] == there["unit_ids"]
        assert units.load_units(dest, synth.target_key) == units.load_units(risk_store, synth.target_key)
    finally:
        dest.close()
