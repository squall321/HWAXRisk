# RiskStore — migrate 멱등·schema_version=1·P0 4표 존재·health() 형식·owner_sub 컬럼
from __future__ import annotations

import sqlite3

from app.risk_store import RiskStore

P0_TABLES = {"rr_projects", "rr_sources", "rr_snapshots", "rr_snapshot_calls"}


def _tables(db_path) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    finally:
        con.close()
    return {r[0] for r in rows}


def _columns(db_path, table) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        return {r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()}
    finally:
        con.close()


def test_migrate_creates_v1_tables(risk_store, tmp_path):
    db_path = tmp_path / "risk_review.db"
    assert db_path.exists()
    tables = _tables(db_path)
    assert P0_TABLES <= tables
    assert "schema_migrations" in tables
    assert _columns(db_path, "schema_migrations") >= {"version", "applied_at"}
    assert risk_store.schema_version() == 1


def test_migrate_is_idempotent(risk_store, tmp_path):
    before = _tables(tmp_path / "risk_review.db")
    risk_store.migrate()
    risk_store.migrate()
    assert risk_store.schema_version() == 1
    assert _tables(tmp_path / "risk_review.db") == before
    con = sqlite3.connect(tmp_path / "risk_review.db")
    try:
        n = con.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=1").fetchone()[0]
    finally:
        con.close()
    assert n == 1


def test_schema_version_persists_across_reopen(tmp_path):
    path = tmp_path / "persist.db"
    s1 = RiskStore(path)
    s1.open()
    s1.migrate()
    s1.close()

    s2 = RiskStore(path)
    s2.open()
    assert s2.schema_version() == 1
    s2.migrate()
    assert s2.schema_version() == 1
    s2.close()


def test_every_p0_table_has_owner_sub(risk_store, tmp_path):
    db_path = tmp_path / "risk_review.db"
    for table in P0_TABLES:
        assert "owner_sub" in _columns(db_path, table), table
    assert {"id", "code", "character_status"} <= _columns(db_path, "rr_projects")
    assert {"id", "project_id", "kind", "ref_key"} <= _columns(db_path, "rr_sources")
    assert {"id", "project_id", "ir_version", "ir_hash", "ir_json"} <= _columns(db_path, "rr_snapshots")
    assert {"call_id", "snapshot_id", "seq", "channel", "tool"} <= _columns(db_path, "rr_snapshot_calls")


def test_health_shape(risk_store, tmp_path):
    h = risk_store.health()
    assert set(h) >= {"ok", "db_path", "schema_version", "tables"}
    assert h["ok"] is True
    assert str(tmp_path / "risk_review.db") == str(h["db_path"])
    assert h["schema_version"] == 1
    assert P0_TABLES <= set(h["tables"])
