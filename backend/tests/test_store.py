# RiskStore — user_version==1·rr_ 표 전수(plan §5.2.2 DDL)+살림 2표·migrate 멱등·기존 DB pre-migrate 사본·코드보다 높은 user_version 예외
from __future__ import annotations

import re
import sqlite3

import pytest

from app.errors import AppError
from app.risk_store import MIGRATIONS, RiskStore, _DDL_V1_SQL

# plan §5.2.2 A~H 의 CREATE TABLE 이름 — 본문에 실린 표는 41개(A 계획 33표 + 소유·수명주기·사람 개입 4 + 계보·출처 2 + 입력·부분 실패 2).
DDL_TABLES = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", _DDL_V1_SQL)
HOUSEKEEPING = {"_schema_migrations", "_user_credentials"}
# §5.2 가 '41 표' 로 세는 근거 — 33 표 위에 v1 으로 더해진 8 표.
ADDED_IN_41 = {"rr_project_members", "rr_gate_acks", "rr_registry_status_log", "rr_audit",
               "rr_panel_calls", "rr_cluster_alias", "rr_requirements", "rr_snapshot_jobs"}


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


def test_ddl_v1_is_the_full_plan_schema():
    assert MIGRATIONS[-1][0] == 1
    assert len(DDL_TABLES) == 41 and len(set(DDL_TABLES)) == 41
    assert all(n.startswith("rr_") for n in DDL_TABLES)
    assert DDL_TABLES[0] == "rr_projects" and DDL_TABLES[-1] == "rr_id_map"
    assert "rr_delta_contrib" in DDL_TABLES
    assert ADDED_IN_41 <= set(DDL_TABLES)


def test_migrate_creates_v1_tables(risk_store, tmp_path):
    db_path = tmp_path / "risk_review.db"
    assert db_path.exists()
    tables = _tables(db_path)
    rr = {t for t in tables if t.startswith("rr_")}
    assert rr == set(DDL_TABLES)
    assert len(rr) == 41
    assert HOUSEKEEPING <= tables
    assert tables - rr - HOUSEKEEPING <= {"sqlite_sequence"}
    assert _columns(db_path, "_schema_migrations") == {"version", "applied_at", "app_version"}
    # 평문 열 portal_pat 은 폐기 — 값은 portal_pat_enc(BLOB) 하나뿐이다(plan §8.2.7).
    assert _columns(db_path, "_user_credentials") == {
        "owner_sub", "portal_pat_enc", "pat_sub", "pat_email", "pat_groups_json", "pat_scopes_json",
        "pat_jti", "pat_exp", "revoked_at", "revoked_seen_at", "registered_at"}
    assert risk_store.schema_version() == 1
    assert risk_store.tables() == sorted(DDL_TABLES)


def test_journal_mode_is_wal(risk_store):
    assert risk_store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_migrate_is_idempotent(risk_store, tmp_path):
    before = _tables(tmp_path / "risk_review.db")
    risk_store.migrate()
    risk_store.migrate()
    assert risk_store.schema_version() == 1
    assert _tables(tmp_path / "risk_review.db") == before
    con = sqlite3.connect(tmp_path / "risk_review.db")
    try:
        rows = con.execute("SELECT version, app_version FROM _schema_migrations").fetchall()
    finally:
        con.close()
    assert rows == [(1, "0.1.0")]
    # 멱등 재적용은 기존 DB 라도 pre-migrate 사본을 만들지 않는다(적용할 버전이 없다).
    assert not list(tmp_path.glob("risk_review.db.pre-migrate-*"))


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
    assert not list(tmp_path.glob("persist.db.pre-migrate-*"))


def test_existing_db_gets_pre_migrate_copy(tmp_path):
    """기존 DB(user_version 0, 표 없음)에 v1 을 적용하면 적용 직전 사본 risk_review.db.pre-migrate-<ts> 가 남는다."""
    path = tmp_path / "risk_review.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE legacy_marker(x INTEGER)")
    con.commit()
    con.close()

    store = RiskStore(path)
    store.open()
    assert store.migrate() == 1
    store.close()

    copies = list(tmp_path.glob("risk_review.db.pre-migrate-*"))
    assert len(copies) == 1
    assert re.fullmatch(r"risk_review\.db\.pre-migrate-\d+", copies[0].name)
    copy_tables = _tables(copies[0])
    assert "legacy_marker" in copy_tables and not any(t.startswith("rr_") for t in copy_tables)
    assert "legacy_marker" in _tables(path) and "rr_projects" in _tables(path)


def test_fresh_db_has_no_pre_migrate_copy(risk_store, tmp_path):
    assert not list(tmp_path.glob("risk_review.db.pre-migrate-*"))


def test_user_version_above_code_fails(tmp_path):
    path = tmp_path / "future.db"
    con = sqlite3.connect(path)
    con.execute("PRAGMA user_version = 99")
    con.commit()
    con.close()

    store = RiskStore(path)
    store.open()
    with pytest.raises(AppError) as exc:
        store.migrate()
    assert exc.value.code == "E300"
    store.close()


def test_every_rr_table_has_owner_sub_or_is_global(risk_store, tmp_path):
    """소유권 규약(§5.2.1) — owner_sub 가 없는 표는 전역 어휘·통계 표뿐이다."""
    db_path = tmp_path / "risk_review.db"
    without = {t for t in DDL_TABLES if "owner_sub" not in _columns(db_path, t)}
    assert without == {"rr_dim_vocab", "rr_delta_priors", "rr_rules", "rr_metrics"}
    assert {"id", "code", "character_status"} <= _columns(db_path, "rr_projects")
    assert {"call_id", "job_id", "snapshot_id", "seq", "channel", "tool"} <= _columns(db_path, "rr_snapshot_calls")


def test_v1_carries_the_plan_column_additions(risk_store, tmp_path):
    """§5.2.2 개정이 기존 표에 더한 열 — 표 8개 신설과 함께 이 패스가 닫아야 할 격차다."""
    db_path = tmp_path / "risk_review.db"
    assert {"classification", "lifecycle", "corpus_excluded", "status", "purged_at", "merged_into",
            "mcp_visibility", "product_code", "product_refs_json",
            "predecessor_product_code"} <= _columns(db_path, "rr_projects")
    assert {"degraded_json", "primary_source", "capture_partial", "app_versions_json",
            "job_id"} <= _columns(db_path, "rr_snapshots")
    assert {"contract_ok", "contract_missing_json", "reused_from_call_id"} <= _columns(db_path, "rr_snapshot_calls")
    assert {"origin", "author_sub", "requirement_ref", "status_source",
            "recall_eligible"} <= _columns(db_path, "rr_findings")
    assert {"status_source", "human_n", "needs_review_json", "rejected",
            "family_key"} <= _columns(db_path, "rr_registry")
    assert {"status_source", "decided_by", "decided_at"} <= _columns(db_path, "rr_coverage")
    assert {"state_by", "state_at", "credential_email"} <= _columns(db_path, "rr_jobs")
    assert {"brief_gz", "brief_hash", "brief_item_hashes_json", "brief_token_hash",
            "brief_token_exp"} <= _columns(db_path, "rr_panels")


def test_credential_value_lives_only_in_portal_pat_enc(risk_store, tmp_path):
    """등록 값은 BLOB 열 하나에만 있고 get_credential 이 문자열로 되돌린다 — 복호는 저장소 밖이다(plan §8.2.7)."""
    pat = "fake.portal.pat"  # 테스트용 가짜 값(저장소는 값을 해석하지 않는다).
    risk_store.upsert_credential("bob@example.com", pat, "u-bob", "bob@example.com", '["cae"]', 1893456000,
                                 pat_scopes_json='["read"]', pat_jti="jti-1")
    row = risk_store.query_one(
        "SELECT portal_pat_enc, pat_scopes_json, pat_jti, revoked_at FROM _user_credentials WHERE owner_sub = ?",
        ("bob@example.com",))
    assert isinstance(row["portal_pat_enc"], bytes) and row["portal_pat_enc"] == pat.encode()
    assert row["pat_scopes_json"] == '["read"]' and row["pat_jti"] == "jti-1" and row["revoked_at"] is None

    got = risk_store.get_credential("bob@example.com")
    assert got["portal_pat"] == pat and "portal_pat_enc" not in got
    assert got["pat_scopes_json"] == '["read"]' and got["revoked_seen_at"] is None
    assert risk_store.delete_credential("bob@example.com") == 1
    assert risk_store.get_credential("bob@example.com") is None
