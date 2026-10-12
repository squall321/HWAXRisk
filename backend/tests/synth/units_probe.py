# 앱 원장을 읽기 전용으로 열어 diff 마다 검토 단위를 계산하고 수를 JSON 한 줄로 찍는 탐침 — M0-c·dev 리허설·cae00 파일럿이 같은 방법으로 잰다
"""리스크 심사 재설계 M2 걸음 U10(m2-wp2 걸음 10). 운영 코드가 아니라 시험 쪽 도구다 — 쓰는 함수는 `app.units.compute` 하나다.

사용(backend 에서 — 앱이 떠 있어도 된다. 이행·러너 잠금·쓰기가 없다).

    .venv/bin/python -m tests.synth.units_probe --data-dir <앱 데이터 디렉터리> (--all | --target-key K … | --diff-id D …)

SIF 로만 도는 박스는 떠 있는 앱 인스턴스 안에서 같은 모듈을 부른다(그 안의 데이터 디렉터리는 /data 다).

    apptainer exec --pwd /app/backend instance://heax_app_hwax_risk python -m tests.synth.units_probe --data-dir /data --all

- DB 는 SQLite `mode=ro` 로 연다. 저장소에는 읽기(`query`·`query_one`)만 있고, 무엇이 쓰려 해도 SQLite 가 거절한다. DB 파일은 한
  바이트도 바뀌지 않는다. 앱이 내려가 있어 WAL 곁 파일(-wal·-shm)이 없으면 SQLite 가 빈 곁 파일을 만든다(읽기에 필요하다).
- 스키마가 이 코드와 다르면 아무것도 계산하지 않고 멈춘다(`tests/synth/inject_dev.py` 와 같은 규율 — 이행은 앱이 기동 때 한다).
- 단위 크기 손잡이는 앱과 같은 순서(환경변수 > `<data-dir>/knobs.env` > 코드 기본값)로 읽는다. 같은 diff·같은 손잡이면
  `POST /api/targets/{key}/units` 가 세우는 빌드와 같은 수다. 그 diff 의 대상에 활성 빌드가 있으면 입력 해시·stats 가 같은지 함께 찍는다.
- diff 마다 그 diff 하나만 보는 읽기 트랜잭션 안에서 계산한다(도는 앱이 사이에 써도 한 diff 의 수는 한 시점의 것이다).

줄마다 — 항목(층·klass)·`lower_only_n`·`tol_unknown_n`·단위(종류별)·단위당 변경 줄 p50·p95·max·요약 글자·근거 글자·빌드 ms·불변식과
빌드의 `stats` 원본. 백분위는 앱의 `_stats` 와 같은 식(정렬한 값의 `int(q × n)` 번째)이고 단위당 값은 검토 대상 단위만 센다.
종료 0 계산했다(줄의 `status` 가 failed 일 수 있다) · 2 시작 전에 멈췄다(`멈춤 —` 문구).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import types
from pathlib import Path
from typing import Any, Mapping, Sequence

DB_FILENAME = "risk_review.db"          # app.config.DB_FILENAME — app 을 들이기 전에 DB 가 있는지 본다(없는 디렉터리를 만들지 않게)
CAP_KNOBS = ("HWAXRISK_UNIT_TARGET_LINES", "HWAXRISK_UNIT_MAX_LINES", "HWAXRISK_UNITS_SMALL_LINES", "HWAXRISK_UNITS_MAX")


class ReadOnlyStore:
    """`units.compute` 가 쓰는 읽기 둘만 있는 저장소 — 연결은 `mode=ro` 이고 쓰기 함수(`execute`·`tx`)가 없다."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True, timeout=30, isolation_level=None)
        self.conn.row_factory = sqlite3.Row

    def query(self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def schema_version(self) -> int:
        return int(self.conn.execute("PRAGMA user_version").fetchone()[0])

    def close(self) -> None:
        self.conn.close()


def _stop(message: str) -> int:
    print(f"멈춤 — {message}", file=sys.stderr)
    return 2


def _pct(values: Sequence[int]) -> dict:
    """{p50, p95, max} — 앱 `units._stats` 의 lines_per_unit 과 같은 식."""
    ordered = sorted(values)

    def at(q: float) -> int:
        return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else 0

    return {"p50": at(0.5), "p95": at(0.95), "max": ordered[-1] if ordered else 0}


def _chars(units: Sequence[Mapping[str, Any]], value) -> dict:
    """{total(전 단위), per_unit(검토 대상 단위의 p50·p95·max)}."""
    return {"total": sum(int(value(u) or 0) for u in units),
            "per_unit": _pct([int(value(u) or 0) for u in units if u.get("reviewable")])}


def _invariant_counts(invariants: Mapping[str, Any]) -> dict:
    return {key: len(val) if isinstance(val, list) else int(val or 0) for key, val in sorted(invariants.items())}


def probe_line(store: ReadOnlyStore, diff_id: str, *, caps, caps_source: Mapping[str, str],
               target_key: str | None = None) -> dict:
    """diff 하나의 탐침 줄. 읽기 트랜잭션 하나 안에서 계산한다."""
    from app import units  # noqa: PLC0415 — main 이 데이터 디렉터리를 정한 뒤에 들인다.

    store.conn.execute("BEGIN")
    try:
        row = store.query_one("SELECT owner_sub FROM rr_diffs WHERE id = ?", (diff_id,))
        started = time.perf_counter()
        built = units.compute(store, "diff", diff_id, owner_sub=row["owner_sub"] if row else "", caps=caps)
        build_ms = round((time.perf_counter() - started) * 1000)
        targets = [r["target_key"] for r in store.query(
            "SELECT target_key FROM rr_targets WHERE kind = 'diff' AND ref_id = ? ORDER BY created_at, target_key", (diff_id,))]
        stored = []
        for key in targets:
            active = units.active_build(store, key)
            if active is not None:
                stored.append({"target_key": key, "rev": active["rev"], "status": active["status"],
                               "same_input": active["input_hash"] == built["input_hash"],
                               "same_stats": active["stats"] == built["stats"]})
    finally:
        store.conn.execute("ROLLBACK")
    stats = built.get("stats") or {}
    evidence = built.get("evidence") or {}
    invariants = _invariant_counts(built.get("invariants") or {})
    return {
        "diff_id": diff_id, "target_key": target_key, "targets": targets,
        "status": built["status"], "error": built.get("error"), "error_detail": built.get("error_detail"),
        "mode": built.get("mode"), "blocked_by": built.get("blocked_by"), "builder_version": built.get("builder_version"),
        "caps": built.get("caps"), "caps_source": dict(caps_source),
        "items": {"total": stats.get("items_total", 0), "by_layer": stats.get("by_layer", {}),
                  "by_klass": stats.get("by_klass", {})},
        "lower_only_n": stats.get("lower_only_n", 0),
        "tol_unknown_n": (stats.get("excluded_by_reason") or {}).get("tol_unknown", 0),
        "units": stats.get("units", {}),
        "lines": {"total": stats.get("lines_total", 0), "reviewable": stats.get("reviewable_lines", 0),
                  "per_unit": stats.get("lines_per_unit", _pct([]))},
        "summary_chars": _chars(built["units"], lambda u: u.get("summary_chars")),
        "evidence_chars": _chars(built["units"], lambda u: (evidence.get(u["unit_id"]) or {}).get("chars")),
        "build_ms": build_ms,
        "invariants": invariants,
        "invariants_ok": not any(invariants.values()),
        "active_builds": stored,
        "stats": stats,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="units_probe", description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", required=True, type=Path, help="앱 데이터 디렉터리(그 안의 risk_review.db 를 읽는다)")
    pick = ap.add_mutually_exclusive_group(required=True)
    pick.add_argument("--all", action="store_true", help="원장의 diff 전부(만든 순)")
    pick.add_argument("--target-key", action="append", help="심사 대상(여러 번 줄 수 있다) — 그 대상의 diff 를 잰다")
    pick.add_argument("--diff-id", action="append", help="변경 비교 id(여러 번 줄 수 있다)")
    args = ap.parse_args(argv)

    data_dir = args.data_dir.resolve()
    db = data_dir / DB_FILENAME
    if not db.is_file():
        return _stop(f"{db} 가 없다(새 DB 를 만들지 않는다)")
    if "app.config" not in sys.modules:
        # app.config 는 들일 때 데이터 디렉터리를 정한다 — 지정이 없으면 리포 안 data/ 를 만들고, SIF 안에서는 읽기 전용 루트라 실패한다.
        os.environ["HWAXRISK_DATA_DIR"] = str(data_dir)
    from app import config, units  # noqa: PLC0415
    from app.risk_store import MIGRATIONS  # noqa: PLC0415

    store = ReadOnlyStore(db)
    try:
        want, have = MIGRATIONS[-1][0], store.schema_version()
        if have != want:
            return _stop(f"DB 스키마 {have} ≠ 코드 {want}. 앱을 이 코드로 먼저 띄워 이행한다(탐침은 이행하지 않는다)")
        try:
            knob_values, knob_sources = config.load_review_knobs(data_dir)
        except RuntimeError as exc:          # 앱도 같은 까닭으로 기동하지 않는다 — 고칠 자리를 그대로 말한다
            return _stop(str(exc))
        caps = units.caps_from_settings(types.SimpleNamespace(**knob_values))
        caps_source = {name: source for name, source in knob_sources if name in CAP_KNOBS}
        picked: list[tuple[str, str | None]] = []
        if args.all:
            picked = [(r["id"], None) for r in store.query("SELECT id FROM rr_diffs ORDER BY created_at, rowid")]
        elif args.target_key:
            for key in args.target_key:
                row = store.query_one("SELECT kind, ref_id FROM rr_targets WHERE target_key = ?", (key,))
                if row is None:
                    return _stop(f"심사 대상 {key} 가 없다")
                if row["kind"] != "diff":
                    return _stop(f"심사 대상 {key} 는 현황(snap) 대상이다 — 검토 단위는 변경 비교(diff) 대상만 선다")
                picked.append((row["ref_id"], key))
        else:
            for diff_id in args.diff_id:
                if store.query_one("SELECT 1 AS x FROM rr_diffs WHERE id = ?", (diff_id,)) is None:
                    return _stop(f"변경 비교 {diff_id} 가 없다")
                picked.append((diff_id, None))
        print(f"[원장] {db} · 스키마 v{have} · 읽기 전용 · diff {len(picked)}건 · 단위 손잡이 "
              + " · ".join(f"{name.removeprefix('HWAXRISK_')}={getattr(caps, attr)}({caps_source.get(name, 'default')})"
                           for name, attr in zip(CAP_KNOBS, ("target_lines", "max_lines", "small_lines", "units_max"))),
              file=sys.stderr)
        if not picked:
            print("[원장] 변경 비교(diff)가 하나도 없다 — 찍을 줄이 없다", file=sys.stderr)
        for diff_id, target_key in picked:
            line = probe_line(store, diff_id, caps=caps, caps_source=caps_source, target_key=target_key)
            print(json.dumps(line, ensure_ascii=False, sort_keys=True), flush=True)
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
