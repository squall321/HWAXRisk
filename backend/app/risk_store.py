# 앱 DB(SQLite) 저장소 — RiskStore(stdlib sqlite3 + Lock), 버전 마이그레이션, P0 골격 4표(plan §5.2.2 A·B)
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from app import config
from app.errors import AppError

# owner_sub 컬럼의 값은 heax 사용자 이메일(소문자)이다. 원천은 heax `GET /api/v1/auth/me` 되묻기(P1, plan §5.2.1·§8.2.8)이며
# X-Heax-User-* 헤더는 service 모드 앱에 복사되지 않고 위조 가능하므로 원천으로 쓰지 않는다.
# DDL 은 plan §5.2.2 의 rr_projects · rr_sources · rr_snapshots · rr_snapshot_calls 정의를 그대로 옮겼다.
_DDL_V1: list[str] = [
    """CREATE TABLE IF NOT EXISTS rr_projects (
  id TEXT PRIMARY KEY, owner_sub TEXT NOT NULL,
  code TEXT NOT NULL, name TEXT, stage TEXT,
  predecessor_project_id TEXT,                  -- 계보(UI 입력) → RA revision_of
  adh_team TEXT, adh_group TEXT,                -- 사용자 확인값, 자동 채움 금지
  ra_entity_id INTEGER, adh_character_record_id TEXT,
  character_status TEXT CHECK(character_status IN ('seed','panel','confirmed')) DEFAULT 'seed',
  created_at INTEGER, updated_at INTEGER,
  UNIQUE(owner_sub, code))""",
    """CREATE TABLE IF NOT EXISTS rr_sources (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('mcad','dyna','dyna_result','ecad')),
  app_key TEXT, ref_json TEXT NOT NULL, ref_key TEXT NOT NULL,   -- ref_key = kind:app_key:정렬 ref 문자열
  bridge_declared INTEGER DEFAULT 0, probe_json TEXT, probe_at INTEGER,
  adapter_version TEXT, created_at INTEGER,
  UNIQUE(project_id, ref_key))""",
    """CREATE TABLE IF NOT EXISTS rr_snapshots (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  ir_version TEXT NOT NULL, ir_hash TEXT NOT NULL,
  ir_json TEXT NOT NULL,                        -- rr_ir 원본(유일)
  source_ids_json TEXT NOT NULL,                -- [{kind, app_key, ref, hash, tool_version, tol_params}]
  kinds_json TEXT NOT NULL,                     -- ['mcad','dyna',…]
  node_count INTEGER, edge_count INTEGER, missing_json TEXT, warnings_n INTEGER,
  degraded TEXT,                                -- null | 'mcp_degraded'
  adapter_versions_json TEXT, ra_entity_id INTEGER, adh_digest_record_id TEXT,
  created_at INTEGER,
  UNIQUE(project_id, ir_hash))""",
    "CREATE INDEX IF NOT EXISTS ix_rr_snapshots_project ON rr_snapshots(project_id, created_at)",
    """CREATE TABLE IF NOT EXISTS rr_snapshot_calls (                -- 행 정의는 plan §2.11.4
  call_id TEXT PRIMARY KEY,                     -- '<snapshot_id[:8]>-<seq:03d>'
  snapshot_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  seq INTEGER NOT NULL, source_kind TEXT NOT NULL, app_key TEXT,
  channel TEXT NOT NULL CHECK(channel IN ('mcp','rest')), tool TEXT NOT NULL,
  args_json TEXT, args_hash TEXT, ok INTEGER NOT NULL DEFAULT 1, http_status INTEGER,
  response_sha256 TEXT, response_gz BLOB, response_bytes INTEGER,
  started_at INTEGER, duration_ms INTEGER, error TEXT)""",
    "CREATE INDEX IF NOT EXISTS ix_rr_calls_snapshot ON rr_snapshot_calls(snapshot_id, seq)",
]

# 버전 오름차순. 한 버전 = 한 트랜잭션. 허용 연산은 CREATE TABLE IF NOT EXISTS · ADD COLUMN · CREATE INDEX IF NOT EXISTS 뿐(plan §5.2.5 (6)).
MIGRATIONS: list[tuple[int, list[str]]] = [(1, _DDL_V1)]


class RiskStore:
    """앱 프로세스 하나가 소유하는 SQLite 저장소. REST·MCP·러너가 같은 인스턴스와 Lock 을 공유한다."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise AppError("E300", "저장소가 열려 있지 않습니다 — open() 을 먼저 호출하세요.")
        return self._conn

    def open(self) -> None:
        """연결을 연다(멱등). WAL 켜고 외래키는 끈다(외래키는 문자열 계약, DB 제약으로 강제하지 않는다)."""
        if self._conn is not None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=OFF")
        self._conn = conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def migrate(self) -> int:
        """PRAGMA user_version(정본) 보다 높은 버전만 순서대로 적용한다(멱등). 이력은 schema_migrations 표에 남긴다. 적용 후 버전을 돌려준다."""
        with self._lock:
            conn = self.conn
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL)"
            )
            conn.commit()
            current = self._schema_version_unlocked()
            latest = MIGRATIONS[-1][0]
            if current > latest:
                raise AppError(
                    "E300",
                    f"DB 스키마 버전({current})이 앱 코드({latest})보다 높습니다 — 앱을 갱신하세요.",
                )
            for version, statements in MIGRATIONS:
                if version <= current:
                    continue
                try:
                    conn.execute("BEGIN")
                    for sql in statements:
                        conn.execute(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                        (version, int(time.time())),
                    )
                    conn.execute(f"PRAGMA user_version = {int(version)}")
                    conn.commit()
                except sqlite3.Error as exc:
                    conn.rollback()
                    raise AppError("E300", f"마이그레이션 v{version} 실패: {exc}") from exc
            return self._schema_version_unlocked()

    def _schema_version_unlocked(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def schema_version(self) -> int:
        """PRAGMA user_version 의 스키마 버전(미적용이면 0, plan §5.2.5 (6))."""
        with self._lock:
            return self._schema_version_unlocked()

    def tables(self) -> list[str]:
        """rr_ 접두 표 이름(정렬)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'rr_%' ORDER BY name"
            ).fetchall()
        return [r["name"] for r in rows]

    def health(self) -> dict:
        """{ok, db_path, schema_version, tables} — /api/health·MCP risk_health 공용."""
        try:
            return {
                "ok": True,
                "db_path": str(self.db_path),
                "schema_version": self.schema_version(),
                "tables": self.tables(),
            }
        except (AppError, sqlite3.Error) as exc:
            return {"ok": False, "db_path": str(self.db_path), "schema_version": 0,
                    "tables": [], "error": str(exc)}


# ---------------------------------------------------------------- 프로세스 단일 인스턴스
# REST 핸들러·MCP 도구가 같은 인스턴스를 쓴다. DB 경로가 바뀌면(테스트가 HWAX_RISK_DATA_DIR 를 바꾼 경우) 다시 연다.
_store: RiskStore | None = None
_store_lock = threading.Lock()


def get_store() -> RiskStore:
    """현재 설정의 DB 경로에 대한 열린·마이그레이션된 RiskStore 를 돌려준다."""
    global _store
    db_path = config.settings.DB_PATH
    with _store_lock:
        if _store is None or _store.db_path != db_path:
            if _store is not None:
                _store.close()
            store = RiskStore(db_path)
            store.open()
            store.migrate()
            _store = store
        return _store


def close_store() -> None:
    """프로세스 단일 인스턴스를 닫는다(lifespan 종료용)."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
            _store = None
