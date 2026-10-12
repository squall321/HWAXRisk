# v4 이행(재설계 M2 C1) — 얼린 옛 원장 둘(v2 옛 타깃 · 패널 결과 원문이 든 v3)이 행을 그대로 둔 채 v4 로 오르고, 오른 원장에서 패널 경로가 그대로 돈다
"""cae00 의 원장은 M1 코드가 쓴 v3 DB 다. v4 블록이 그 원장을 한 번에 한 사본으로 올리고 옛 행의 값을 한 칸도 바꾸지 않는지,
오른 원장에 걸린 옛 잡을 러너가 집어 끝내는지를 본다(D-24 — 두 방식 비교 동안 패널 경로는 그대로다).

v2 원장은 `tests/fixtures/legacy`(legacy_build), v3 원장은 `tests/fixtures/v3`(v3_build — v4 블록 직전 코드)다.
"""
from __future__ import annotations

import dataclasses
import gzip
import json
import shutil
import sqlite3
from pathlib import Path

import httpx
import pytest

from app import config, planner, routes, runner
from app.risk_store import MIGRATIONS, RiskStore
from tests.rr import legacy_build as legacy
from tests.rr import v3_build
from tests.rr.test_legacy_flow import _IPV4, _SECRET_SHAPES, _all_text

LATEST = MIGRATIONS[-1][0]
V3_MANIFEST = json.loads((v3_build.V3_DIR / "manifest.json").read_text(encoding="utf-8"))
FROZEN = {"v2": (legacy.LEGACY_DIR / legacy.DB_GZ, legacy.FROZEN_SCHEMA),
          "v3": (v3_build.V3_DIR / v3_build.DB_GZ, v3_build.FROZEN_SCHEMA)}
V4_TABLES = ("rr_unit_builds", "rr_units", "rr_expert_reports", "rr_review_cells", "rr_card_verdicts", "rr_card_packs",
             "rr_review_calls")


def _thaw(gz_path: Path, directory: Path) -> Path:
    db = directory / "risk_review.db"
    with gzip.open(gz_path, "rb") as src, open(db, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return db


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _rows(con: sqlite3.Connection, table: str, cols: list[str]) -> list[tuple]:
    return con.execute(f"SELECT {', '.join(_q(c) for c in cols)} FROM {_q(table)} ORDER BY rowid").fetchall()


def _snapshot(db: Path) -> dict[str, tuple[list[str], list[tuple]]]:
    """표마다 (열 이름, rowid 순 행 전부) — BLOB 은 바이트 그대로 비교된다."""
    con = sqlite3.connect(db)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'")]
        out = {}
        for table in tables:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({_q(table)})")]
            out[table] = (cols, _rows(con, table, cols))
        return out
    finally:
        con.close()


def _user_version(db: Path) -> int:
    con = sqlite3.connect(db)
    try:
        return int(con.execute("PRAGMA user_version").fetchone()[0])
    finally:
        con.close()


@pytest.fixture
def no_network(monkeypatch):
    """러너·브리프가 게이트웨이를 부르면 연결 오류로 답한다 — 시험이 dev 박스의 실 게이트웨이에 닿지 않게."""
    def _refused(*args, **_kwargs):
        raise httpx.ConnectError("시험은 외부를 부르지 않는다.", request=args[-1])

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refused)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refused)


# ---------------------------------------------------------------- ① 행을 그대로 둔 채 한 사본으로 오른다
@pytest.mark.parametrize("frozen", sorted(FROZEN))
def test_a_frozen_ledger_rises_to_v4_once_keeping_every_row(tmp_path, frozen):
    gz_path, version = FROZEN[frozen]
    db = _thaw(gz_path, tmp_path)
    assert _user_version(db) == version < LATEST
    before = _snapshot(db)

    for _ in range(2):                                          # 두 번째 기동은 아무것도 하지 않는다
        store = RiskStore(db)
        store.open()
        try:
            assert store.migrate() == LATEST
        finally:
            store.close()
        copies = sorted(tmp_path.glob("risk_review.db.pre-migrate-*"))
        assert len(copies) == 1 and copies[0].name.startswith(f"risk_review.db.pre-migrate-v{version}-"), copies
    # 사본은 오르기 전 원장 그대로다.
    assert _user_version(copies[0]) == version and _snapshot(copies[0]) == before

    after = _snapshot(db)
    con = sqlite3.connect(db)
    try:
        for table, (cols, rows) in before.items():
            assert set(cols) <= set(after[table][0]), table
            if table == "_schema_migrations":                   # 올린 판의 이력이 뒤에 붙는다
                assert _rows(con, table, cols)[:len(rows)] == rows
                assert [r[0] for r in _rows(con, table, ["version"])] == [v for v, _ in MIGRATIONS]
                continue
            assert _rows(con, table, cols) == rows, f"{table} 의 옛 행이 바뀌었다"
        # 옛 행의 새 열 — 대상은 패널 방식, 잡은 패널 잡(보류 없음), finding 은 패널 출처다.
        assert {r[0] for r in con.execute("SELECT DISTINCT flow FROM rr_targets")} == {"panels"}
        assert con.execute("SELECT COUNT(*) FROM rr_jobs WHERE mode IS NOT NULL OR hold_code IS NOT NULL"
                           " OR hold_until IS NOT NULL OR hold_n <> 0").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM rr_findings WHERE unit_id IS NOT NULL OR source_kind IS NOT NULL"
                           " OR source_id IS NOT NULL OR agent_key IS NOT NULL").fetchone()[0] == 0
        for table in V4_TABLES:
            assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        # 빈 시험이 아니다 — 옛 원장에 타깃·잡·finding 이 있고, v3 원장에는 패널 결과 원문이 있다.
        for table in ("rr_targets", "rr_jobs", "rr_findings"):
            assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0, table
        if version >= 3:
            assert con.execute("SELECT COUNT(*) FROM rr_panels WHERE result_gz IS NOT NULL").fetchone()[0] == (
                V3_MANIFEST["result_gz_n"]) > 0
    finally:
        con.close()


# ---------------------------------------------------------------- ② 오른 원장에서 옛 잡이 끝까지 돈다
def test_the_queued_v3_job_runs_through_the_runner_after_the_rise(tmp_path, no_network, monkeypatch):
    """v3 에서 아직 집히지 않은 Tier A 잡을 v4 러너가 집어 패널을 끝내고 잡을 닫는다. 패널 경로는 v4 표에 쓰지 않는다."""
    store = RiskStore(_thaw(FROZEN["v3"][0], tmp_path))
    store.open()
    store.migrate()
    monkeypatch.setattr(routes, "get_store", lambda: store)
    target = V3_MANIFEST["targets"]["queued"]
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    secrets = data_dir / config.SECRETS_FILENAME
    secrets.write_text("HWAXRISK_PORTAL_PAT=test-service-pat\n", encoding="utf-8")
    secrets.chmod(0o600)
    cfg = dataclasses.replace(config.settings, data_dir=data_dir)
    engine = legacy.LegacyEngine(legacy.spec_builder(store, target["target_key"], planner.domain_of))
    try:
        job = runner.claim_next_job(store, cfg)
        assert job is not None and job["id"] == target["job_id"]
        out = runner.run_panel(store, cfg, engine, job)
        assert out["status"] == "done", out
        assert planner.check_invariants(store, target["target_key"]) == []
        panel = store.query_one("SELECT status, result_gz FROM rr_panels WHERE id = ?", (out["panel_id"],))
        assert panel["status"] == "done" and panel["result_gz"] is not None

        again = runner.claim_next_job(store, cfg)
        assert again is not None and runner.run_panel(store, cfg, engine, again)["status"] == "no_panel"
        assert store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (target["job_id"],))["state"] == "completed"
        for table in V4_TABLES:
            assert store.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"] == 0, table
    finally:
        store.close()


# ---------------------------------------------------------------- ③ 얼린 v3 원장의 위생
def test_the_v3_fixture_is_a_v3_ledger_without_internal_address_or_secret(tmp_path):
    db = _thaw(FROZEN["v3"][0], tmp_path)
    assert _user_version(db) == V3_MANIFEST["schema_version"] == v3_build.FROZEN_SCHEMA
    text = _all_text(db)
    assert len(text) > 10_000                                   # 빈 DB 를 훑고 통과하지 않는다
    assert set(_IPV4.findall(text)) <= {"127.0.0.1"}
    assert v3_build.SERVICE_PAT_CANARY not in text
    assert [p.pattern for p in _SECRET_SHAPES if p.search(text)] == []
