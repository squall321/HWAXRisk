# RiskStore — user_version==1·rr_ 표 전수(plan §5.2.2 DDL)+살림 2표·migrate 멱등·기존 DB pre-migrate 사본·코드보다 높은 user_version 예외
from __future__ import annotations

import re
import sqlite3

import pytest

from app.errors import AppError
from app.risk_store import MIGRATIONS, RiskStore, _DDL_V1_SQL

LATEST = MIGRATIONS[-1][0]

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
    # v1 은 정본 §5.2.2 DDL 전문 41표 그대로다 — 뒤 버전이 붙어도 이 집합은 바뀌지 않는다.
    assert MIGRATIONS[0][0] == 1
    assert len(DDL_TABLES) == 41 and len(set(DDL_TABLES)) == 41
    assert all(n.startswith("rr_") for n in DDL_TABLES)
    assert DDL_TABLES[0] == "rr_projects" and DDL_TABLES[-1] == "rr_id_map"
    assert "rr_delta_contrib" in DDL_TABLES
    assert ADDED_IN_41 <= set(DDL_TABLES)


def test_v2_adds_the_brief_call_ledger_and_keeps_v1_data(tmp_path):
    """v2 는 CREATE TABLE 하나다(허용 연산) — 기존 v1 DB 는 데이터를 유지한 채 올라간다."""
    from app.risk_store import MIGRATIONS as MIG

    assert [v for v, _ in MIG] == [1, 2]
    # 허용 연산만 쓴다(plan §5.2.5 (6)) — ALTER 로 CHECK 를 고치는 문장이 없다.
    for _, statements in MIG[1:]:
        for sql in statements:
            head = sql.strip().upper()
            assert head.startswith(("CREATE TABLE IF NOT EXISTS", "ALTER TABLE", "CREATE INDEX IF NOT EXISTS"))
            if head.startswith("ALTER TABLE"):
                assert " ADD COLUMN " in head

    db = tmp_path / "risk_review.db"
    store = RiskStore(db)
    store.open()
    store.migrate()
    store.execute("INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
                  " VALUES ('P1','u','F7','F7',1,1)")
    store.close()

    again = RiskStore(db)
    again.open()
    again.migrate()
    try:
        assert again.query_one("PRAGMA user_version")["user_version"] == 2
        assert again.query_one("SELECT COUNT(*) AS n FROM rr_projects")["n"] == 1
        assert again.query("SELECT name FROM sqlite_master WHERE name = 'rr_brief_calls'", ())
        assert [r["version"] for r in again.query(
            "SELECT version FROM _schema_migrations ORDER BY version", ())] == [1, 2]
    finally:
        again.close()


def test_migrate_creates_v1_tables(risk_store, tmp_path):
    db_path = tmp_path / "risk_review.db"
    assert db_path.exists()
    tables = _tables(db_path)
    rr = {t for t in tables if t.startswith("rr_")}
    # v1 표 41개는 정본 §5.2.2 전문 그대로이고, 뒤 버전이 더한 표(v2 rr_brief_calls)가 그 위에 붙는다.
    assert set(DDL_TABLES) <= rr
    assert len(DDL_TABLES) == 41
    assert rr - set(DDL_TABLES) == {"rr_brief_calls"}
    assert HOUSEKEEPING <= tables
    assert tables - rr - HOUSEKEEPING <= {"sqlite_sequence"}
    assert _columns(db_path, "_schema_migrations") == {"version", "applied_at", "app_version"}
    # 평문 열 portal_pat 은 폐기 — 값은 portal_pat_enc(BLOB) 하나뿐이다(plan §8.2.7).
    assert _columns(db_path, "_user_credentials") == {
        "owner_sub", "portal_pat_enc", "pat_sub", "pat_email", "pat_groups_json", "pat_scopes_json",
        "pat_jti", "pat_exp", "revoked_at", "revoked_seen_at", "registered_at"}
    assert risk_store.schema_version() == LATEST
    # v1 표 41개는 그대로 있고 v2 가 더한 표가 뒤에 붙는다.
    assert set(DDL_TABLES) <= set(risk_store.tables())


def test_journal_mode_is_wal(risk_store):
    assert risk_store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_migrate_is_idempotent(risk_store, tmp_path):
    before = _tables(tmp_path / "risk_review.db")
    risk_store.migrate()
    risk_store.migrate()
    assert risk_store.schema_version() == LATEST
    assert _tables(tmp_path / "risk_review.db") == before
    con = sqlite3.connect(tmp_path / "risk_review.db")
    try:
        rows = con.execute("SELECT version, app_version FROM _schema_migrations").fetchall()
    finally:
        con.close()
    assert rows == [(v, "0.1.0") for v, _ in MIGRATIONS]
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
    assert s2.schema_version() == LATEST
    s2.migrate()
    assert s2.schema_version() == LATEST
    s2.close()
    assert not list(tmp_path.glob("persist.db.pre-migrate-*"))


def test_existing_db_gets_pre_migrate_copy(tmp_path):
    """기존 DB(user_version 0, 표 없음)에 v1 을 적용하면 적용 직전 사본 risk_review.db.pre-migrate-v0-<ts> 가 남는다.

    이름에 출발 버전이 든다 — 디스크를 비우는 사람이 어느 사본이 옛 코드와 맞는지 이름으로 안다(X2-01)."""
    path = tmp_path / "risk_review.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE legacy_marker(x INTEGER)")
    con.commit()
    con.close()

    store = RiskStore(path)
    store.open()
    assert store.migrate() == LATEST
    store.close()

    copies = list(tmp_path.glob("risk_review.db.pre-migrate-*"))
    assert len(copies) == 1
    assert re.fullmatch(r"risk_review\.db\.pre-migrate-v0-\d+", copies[0].name)
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


# ---------------------------------------------------------------- 이행 규약과 안전 묶음(WP5a R3 · 반대 검토 X2-01·X2-02)
# 한 번 나간 버전의 DDL 은 고치지 않는다 — cae00 은 그 버전을 이미 적용했고 다시 돌리지 않는다(WP5a 3.2.1 마지막 규약).
# 새 버전을 더하면 그 커밋이 여기에 해시를 같이 적는다(적지 않으면 아래 시험이 붉다).
PUSHED_DDL_SHA256 = {
    1: "95298128f33e533a21a9bbdfb4aab46a9f0af096585f1e5932cc035887e09492",
    2: "162c36361ed98a7fb6d8cc195ab0e1c0fabe1ef448ec7e785f2311e2843bfea5",
}
SHARED_TABLES = {"rr_dim_vocab", "rr_delta_priors", "rr_rules", "rr_metrics"}


def _ddl_sha(statements) -> str:
    import hashlib

    return hashlib.sha256("\n".join(statements).encode("utf-8")).hexdigest()


def test_every_version_keeps_the_ddl_it_shipped_with():
    assert {v: _ddl_sha(s) for v, s in MIGRATIONS} == PUSHED_DDL_SHA256


def test_every_table_of_every_version_follows_the_conventions(risk_store, tmp_path):
    """전 버전의 rr_ 표 — owner_sub 가 있거나 공용 표 넷 중 하나 · 전부 PK · v1 뒤에 더한 표에는 CHECK 가 없다."""
    db_path = tmp_path / "risk_review.db"
    created = {v: re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", "\n".join(s)) for v, s in MIGRATIONS}
    tables = [t for names in created.values() for t in names]
    assert tables and len(tables) == len(set(tables))
    con = sqlite3.connect(db_path)
    try:
        for table in tables:
            info = con.execute(f"PRAGMA table_info({table})").fetchall()
            assert any(row[5] for row in info), f"{table} 에 PK 가 없다 — 들여오기가 500 이다"
            assert table in SHARED_TABLES or "owner_sub" in {row[1] for row in info}, table
    finally:
        con.close()
    for version, statements in MIGRATIONS[1:]:
        assert not any("CHECK(" in s.upper().replace(" ", "") for s in statements), (
            f"v{version} — 어휘 열에 CHECK 를 걸면 어휘 확장이 허용 연산 밖이 된다")


def _v_next(monkeypatch, *statements: str) -> int:
    """코드에 아직 없는 다음 버전을 시험 안에서만 물린다."""
    from app import risk_store as store_module

    nxt = LATEST + 1
    monkeypatch.setattr(store_module, "MIGRATIONS", [*MIGRATIONS, (nxt, list(statements))])
    return nxt


def _latest_db(path) -> None:
    store = RiskStore(path)
    store.open()
    store.migrate()
    store.execute("INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
                  " VALUES ('P1','u','F7','F7',1,1)")
    store.close()


def test_a_failing_migration_retried_leaves_one_copy(tmp_path, monkeypatch):
    """허브는 헬스가 안 오면 45초마다 다시 띄운다 — 실패하는 이행을 세 번 돌려도 사본은 하나다(X2-01)."""
    from app import risk_store as store_module

    db = tmp_path / "risk_review.db"
    _latest_db(db)
    _v_next(monkeypatch, "ALTER TABLE rr_no_such_table ADD COLUMN x TEXT")
    clock = iter(range(1_800_000_000, 1_800_100_000, 45))           # 다시 띄울 때마다 45초가 흐른다
    monkeypatch.setattr(store_module.time, "time", lambda: float(next(clock)))
    for _ in range(3):
        store = RiskStore(db)
        store.open()
        with pytest.raises(AppError) as exc:
            store.migrate()
        assert exc.value.code == "E300" and f"v{LATEST + 1}" in exc.value.message
        assert store.schema_version() == LATEST
        store.close()
    copies = sorted(p.name for p in tmp_path.glob("risk_review.db.pre-migrate-*"))
    assert len(copies) == 1 and re.fullmatch(rf"risk_review\.db\.pre-migrate-v{LATEST}-\d+", copies[0]), copies


def test_a_db_changed_since_its_copy_gets_a_new_copy(tmp_path, monkeypatch):
    """같은 출발 버전이어도 그 뒤에 쓴 것이 있으면 옛 사본으로 대신하지 않는다(되돌린 DB 위에서 다시 오르는 경우)."""
    import os

    db = tmp_path / "risk_review.db"
    _latest_db(db)
    stale = tmp_path / f"risk_review.db.pre-migrate-v{LATEST}-1000"
    stale.write_bytes(b"older")
    os.utime(stale, ns=(1_000_000_000, 1_000_000_000))
    _v_next(monkeypatch, "ALTER TABLE rr_panels ADD COLUMN probe_x TEXT")
    store = RiskStore(db)
    store.open()
    try:
        assert store.migrate() == LATEST + 1
    finally:
        store.close()
    copies = sorted(tmp_path.glob(f"risk_review.db.pre-migrate-v{LATEST}-*"))
    assert len(copies) == 2 and stale in copies
    fresh = next(p for p in copies if p != stale)
    con = sqlite3.connect(fresh)
    try:
        assert con.execute("SELECT COUNT(*) FROM rr_projects").fetchone()[0] == 1
        assert con.execute("PRAGMA user_version").fetchone()[0] == LATEST
    finally:
        con.close()


def test_two_stores_raising_one_db_at_once_both_succeed_with_one_copy(tmp_path, monkeypatch):
    """겹쳐 뜬 둘째 프로세스가 같은 이행을 다시 돌리지 않는다 — ADD COLUMN 은 두 번 돌면 죽는다(X2-02)."""
    import threading
    import time as time_module

    from app import risk_store as store_module

    db = tmp_path / "risk_review.db"
    _latest_db(db)
    nxt = _v_next(monkeypatch, "ALTER TABLE rr_panels ADD COLUMN probe_y TEXT")
    real_copy = store_module.shutil.copy2
    first_copy_started = threading.Event()

    def slow_copy(src, dst, *args, **kwargs):           # 첫째가 사본을 뜨는 동안 둘째가 들어온다.
        first_copy_started.set()
        time_module.sleep(0.5)
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(store_module.shutil, "copy2", slow_copy)
    results: dict[str, object] = {}

    def run(name: str) -> None:
        store = RiskStore(db)
        store.open()
        try:
            results[name] = store.migrate()
        except Exception as exc:  # noqa: BLE001 — 실패를 결과로 모은다.
            results[name] = exc
        finally:
            store.close()

    first = threading.Thread(target=run, args=("first",))
    first.start()
    assert first_copy_started.wait(5)
    second = threading.Thread(target=run, args=("second",))
    second.start()
    first.join(10)
    second.join(10)
    assert results == {"first": nxt, "second": nxt}
    assert len(list(tmp_path.glob("risk_review.db.pre-migrate-*"))) == 1
    assert "probe_y" in _columns(db, "rr_panels")


def test_prune_keeps_the_newest_two_of_each_kind(tmp_path):
    from app.risk_store import prune_backups

    db = tmp_path / "risk_review.db"
    db.write_bytes(b"live")
    names = [f"risk_review.db.pre-migrate-v1-{ts}" for ts in (100, 300, 200)]
    names += ["risk_review.db.pre-migrate-50"]                      # 옛 이름(출발 버전 없음)도 같은 갈래다
    names += [f"risk_review.db.pre-merge-{ts}" for ts in ("20260901-000000Z", "20261001-000000Z", "20260915-000000Z")]
    names += ["risk_review.db.pre-migrate-v1-400.tmp", "other.db.pre-merge-20200101-000000Z"]
    for name in names:
        (tmp_path / name).write_bytes(b"x")
    removed = prune_backups(db)
    left = sorted(p.name for p in tmp_path.iterdir() if p.name != "risk_review.db")
    assert left == ["other.db.pre-merge-20200101-000000Z",
                    "risk_review.db.pre-merge-20260915-000000Z", "risk_review.db.pre-merge-20261001-000000Z",
                    "risk_review.db.pre-migrate-v1-200", "risk_review.db.pre-migrate-v1-300"]
    assert sorted(removed) == sorted(set(names) - set(left))


def test_prune_does_not_remove_a_copy_of_the_version_being_raised(tmp_path):
    from app.risk_store import prune_backups

    db = tmp_path / "risk_review.db"
    db.write_bytes(b"live")
    for name in ("risk_review.db.pre-migrate-v2-10", "risk_review.db.pre-migrate-v3-20",
                 "risk_review.db.pre-migrate-v3-30"):
        (tmp_path / name).write_bytes(b"x")
    prune_backups(db, protect_version=2)
    assert sorted(p.name for p in tmp_path.glob("*.pre-migrate-*")) == [
        "risk_review.db.pre-migrate-v2-10", "risk_review.db.pre-migrate-v3-20", "risk_review.db.pre-migrate-v3-30"]


def test_no_room_for_the_copy_stops_before_raising(tmp_path, monkeypatch):
    """사본을 뜰 자리가 없으면 복사도 이행도 하지 않고 사유를 말하며 멈춘다 — 반쯤 쓴 사본을 남기지 않는다."""
    from app import risk_store as store_module

    db = tmp_path / "risk_review.db"
    _latest_db(db)
    _v_next(monkeypatch, "ALTER TABLE rr_panels ADD COLUMN probe_z TEXT")
    monkeypatch.setattr(store_module.shutil, "disk_usage",
                        lambda _path: store_module.shutil._ntuple_diskusage(10**9, 10**9 - 10, 10))
    store = RiskStore(db)
    store.open()
    try:
        with pytest.raises(AppError) as exc:
            store.migrate()
        assert exc.value.code == "E300" and "여유" in exc.value.message
        assert store.schema_version() == LATEST
    finally:
        store.close()
    assert not list(tmp_path.glob("risk_review.db.pre-migrate-*"))
