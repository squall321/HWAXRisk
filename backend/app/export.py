# 박스 간 이관(dev↔cae00) — GET /api/export JSONL 생성(첫 줄 헤더 + §5.2.2 A→H 표 순서 {table,row})과 POST /api/import 병합(사람 확정이 자동을 이김, 충돌은 conflicts[])
from __future__ import annotations

import base64
import hashlib
import json
import re
import socket
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator

from app import config
from app.errors import AppError
from app.risk_store import MIGRATIONS, RiskStore

EXPORTS_DIRNAME = "exports"
# 살림 표 2개는 rr_ 접두가 아니라서 표 목록에 애초에 들어오지 않는다(plan §5.2.5 (6)·§8.2.3).
_CREATE_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+(rr_\w+)", re.IGNORECASE)


def _table_order() -> tuple[str, ...]:
    """plan §5.2.2 A→H 표 순서 — MIGRATIONS 의 DDL 문장에 나온 차례 그대로다(별도 하드코딩 목록을 두지 않는다)."""
    out: list[str] = []
    for _version, statements in MIGRATIONS:
        for sql in statements:
            hit = _CREATE_TABLE_RE.search(sql)
            if hit is not None and hit.group(1) not in out:
                out.append(hit.group(1))
    return tuple(out)


TABLE_ORDER: tuple[str, ...] = _table_order()

# owner_sub 열이 없는 공용 표 — 소유자 스코프가 없으므로 들여올 때 병합하지 않는다(남의 박스 규칙·지표가
# 이 박스 전역 판정을 갈아치우는 것을 막는다. rr_rules 는 state.load_active_rules 의 입력이다).
# rr_delta_priors 는 rr_delta_contrib 합으로만 채우는 파생 표라 들여올 이유도 없다(plan §4.7.1 '증분 += 없음').
GLOBAL_TABLES: tuple[str, ...] = ("rr_dim_vocab", "rr_delta_priors", "rr_rules", "rr_metrics")

# since 비교 열(앞의 열이 NULL 이면 뒤의 열을 본다). 빈 튜플은 시각 열이 없는 자식 표 — since 와 무관하게 전부 싣는다
# (부모보다 적게 싣는 쪽이 위험하고, import 는 행 단위 멱등이라 더 싣는 비용은 바이트뿐이다).
_SINCE_COLS: dict[str, tuple[str, ...]] = {
    "rr_projects": ("updated_at", "created_at"),
    "rr_sources": ("created_at",),
    "rr_snapshots": ("created_at",),
    "rr_snapshot_calls": ("started_at",),
    "rr_ir_nodes": (),
    "rr_ir_edges": (),
    "rr_part_keys": ("updated_at", "created_at"),
    "rr_sameas": ("decided_at",),
    "rr_iface_ledger": ("decided_at",),
    "rr_dim_vocab": ("created_at",),
    "rr_dim_defs": ("updated_at", "created_at"),
    "rr_states": ("computed_at",),
    "rr_diffs": ("created_at",),
    "rr_diff_events": (),
    "rr_targets": ("updated_at", "created_at"),
    "rr_roster": ("frozen_at",),
    "rr_coverage": ("updated_at", "started_at"),
    "rr_panels": ("created_at",),
    "rr_jobs": ("updated_at", "created_at"),
    "rr_seat_opinions": ("created_at",),
    "rr_findings": ("updated_at", "created_at"),
    "rr_registry": ("updated_at",),
    "rr_claim_refs": (),
    "rr_character": ("updated_at", "created_at"),
    "rr_iface_alias": ("updated_at", "created_at"),
    "rr_delta_priors": ("updated_at",),
    "rr_delta_contrib": ("updated_at",),
    "rr_labels": ("labeled_at", "occurred_at"),
    "rr_patterns": ("updated_at", "created_at"),
    "rr_rules": ("created_at",),
    "rr_metrics": ("computed_at",),
    "rr_curation_queue": ("created_at",),
    "rr_id_map": ("ra_synced_at", "adh_synced_at"),
}


def _human_rank(table: str, row: dict) -> int:
    """사람이 확정한 행이면 1, 자동·후보면 0.

    plan §5.2.5 (7)① 이 사람 확정으로 못박은 자리만 본다 — 원장 4표(rr_sameas · rr_iface_ledger · rr_part_keys ·
    rr_iface_alias) · rr_targets.verdict_final · rr_registry.status · 큐레이션 결정(rr_curation_queue).
    """
    decided_by = str(row.get("decided_by") or "")
    human_decision = bool(decided_by) and not decided_by.startswith("code:")
    if table == "rr_sameas" or table == "rr_iface_ledger":
        return 1 if human_decision else 0
    if table == "rr_part_keys":
        return 1 if human_decision and row.get("status") in ("confirmed", "merged") else 0
    if table == "rr_iface_alias":
        return 1 if row.get("source") == "human" else 0
    if table == "rr_targets":
        return 1 if row.get("verdict_final") else 0
    if table == "rr_registry":
        return 1 if row.get("status") in ("verified", "dismissed", "mitigated") else 0
    if table == "rr_curation_queue":
        return 1 if row.get("status") in ("done", "rejected") else 0
    return 0


# ---------------------------------------------------------------- 표 메타(PRAGMA 로 실제 스키마를 읽는다 — 'select *' 금지)
def _table_meta(store: RiskStore, table: str) -> tuple[list[str], list[str]]:
    """(컬럼 이름 cid 순, PK 컬럼 이름 pk 순). 표가 없으면 AppError E404."""
    rows = store.query(f"PRAGMA table_info({table})")
    if not rows:
        raise AppError("E404", f"표를 찾을 수 없습니다 — {table}.", 404)
    cols = [str(r["name"]) for r in rows]
    pks = [str(r["name"]) for r in sorted((r for r in rows if int(r["pk"]) > 0), key=lambda r: int(r["pk"]))]
    return cols, pks


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _encode(value: Any) -> Any:
    """sqlite 값 → JSON 값. BLOB(response_gz)만 {'__b64__': …} 로 감싼다."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__b64__": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__b64__"}:
        try:
            return base64.b64decode(str(value["__b64__"]).encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise AppError("E100", "BLOB(__b64__) 값을 디코드할 수 없습니다.", 422) from exc
    return value


def _json_line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


# ---------------------------------------------------------------- export
def read_origin(data_dir: Path | None = None) -> dict:
    """origin.json({hostname, app_version, schema_version, written_at}) — 없으면 현재 호스트로 채운다(main.py 가 기동마다 쓴다)."""
    root = config.settings.data_dir if data_dir is None else data_dir
    path = root / "origin.json"
    if path.is_file():
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(body, dict):
                return body
        except (OSError, ValueError):
            pass
    return {"hostname": socket.gethostname(), "app_version": config.APP_VERSION,
            "schema_version": None, "written_at": None}


def header_line(store: RiskStore, data_dir: Path | None = None) -> dict:
    """첫 줄 헤더 {schema_version, app_version, origin}(plan §8.2.3)."""
    return {"schema_version": store.schema_version(), "app_version": config.APP_VERSION,
            "origin": read_origin(data_dir)}


def _select(store: RiskStore, table: str, owner_sub: str, since: int) -> Iterator[dict]:
    """한 표의 소유자 행을 PK 순으로 흘린다.

    owner_sub 열이 없는 공용 표(rr_dim_vocab·rr_rules·rr_metrics·rr_delta_priors)는 소유자로 거를 수 없다 —
    그 중 visibility 열이 있는 표는 'org' 행만 싣는다(남의 사설 집계가 내 JSONL 에 따라 나가지 않게 한다).
    """
    cols, pks = _table_meta(store, table)
    sql = f"SELECT {', '.join(_quote(c) for c in cols)} FROM {table}"
    where: list[str] = []
    params: list[Any] = []
    if "owner_sub" in cols:
        where.append("owner_sub = ?")
        params.append(owner_sub)
    elif "visibility" in cols:
        where.append("visibility = 'org'")
    since_cols = [c for c in _SINCE_COLS.get(table, ()) if c in cols]
    if since > 0 and since_cols:
        expr = since_cols[0] if len(since_cols) == 1 else f"COALESCE({', '.join(since_cols)})"
        where.append(f"COALESCE({expr}, 0) >= ?")
        params.append(int(since))
    if where:
        sql += " WHERE " + " AND ".join(where)
    order = pks or cols
    sql += " ORDER BY " + ", ".join(_quote(c) for c in order)
    for row in store.query(sql, tuple(params)):
        yield {c: _encode(row[c]) for c in cols}


def iter_lines(store: RiskStore, owner_sub: str, since: int = 0, data_dir: Path | None = None) -> Iterator[str]:
    """JSONL 한 줄씩 — 첫 줄 헤더, 이어서 §5.2.2 A→H 표 순서로 {"table", "row"} 줄."""
    yield _json_line(header_line(store, data_dir))
    for table in TABLE_ORDER:
        for row in _select(store, table, owner_sub, since):
            yield _json_line({"table": table, "row": row})


def write_export_file(store: RiskStore, owner_sub: str, since: int = 0, data_dir: Path | None = None) -> Path:
    """같은 내용을 $HEAX_DATA_DIR/exports/<ts>.jsonl 에 남기고 그 경로를 돌려준다(plan §5.2.5 (1)·§8.2.3)."""
    root = config.settings.data_dir if data_dir is None else data_dir
    out_dir = root / EXPORTS_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    path = out_dir / f"{ts}.jsonl"
    seq = 1
    while path.exists():                          # 같은 초에 두 번 부르면 뒤 호출이 앞 파일을 지우지 않게 한다.
        path = out_dir / f"{ts}-{seq}.jsonl"
        seq += 1
    with path.open("w", encoding="utf-8") as fh:
        for line in iter_lines(store, owner_sub, since, data_dir):
            fh.write(line)
    return path


# ---------------------------------------------------------------- import
def _parse(text: str) -> tuple[dict, list[tuple[str, dict]]]:
    """JSONL 본문 → (헤더, [(table, row)…]). 빈 줄은 건너뛴다."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise AppError("E100", "본문이 비어 있습니다 — 첫 줄 헤더가 필요합니다(plan §8.2.3).", 422)
    try:
        head = json.loads(lines[0])
    except ValueError as exc:
        raise AppError("E100", "첫 줄이 JSON 헤더가 아닙니다.", 422) from exc
    if not isinstance(head, dict) or "schema_version" not in head:
        raise AppError("E100", "헤더에 schema_version 이 없습니다.", 422)
    rows: list[tuple[str, dict]] = []
    for no, raw in enumerate(lines[1:], start=2):
        try:
            item = json.loads(raw)
        except ValueError as exc:
            raise AppError("E100", f"{no} 번째 줄이 JSON 이 아닙니다.", 422) from exc
        if not isinstance(item, dict) or not isinstance(item.get("row"), dict) or not isinstance(item.get("table"), str):
            raise AppError("E100", f"{no} 번째 줄이 {{table, row}} 형식이 아닙니다.", 422)
        rows.append((item["table"], item["row"]))
    return head, rows


def _key_of(row: dict, pks: list[str]) -> str:
    return "|".join("" if row.get(c) is None else str(row.get(c)) for c in pks)


def _diff_cols(local: dict, incoming: dict, cols: list[str]) -> list[str]:
    return [c for c in cols if _encode(local.get(c)) != incoming.get(c, None)]


def import_jsonl(store: RiskStore, owner_sub: str, text: str) -> dict:
    """JSONL 을 병합한다 — {inserted, merged, skipped, skipped_global, recomputed_targets, conflicts[]}.

    거절(둘 다 409) — 헤더 schema_version 이 PRAGMA user_version 과 다르면 `schema_mismatch`,
    남의 owner_sub 행이 섞여 있으면 `owner_mismatch`(박스 간 이동은 자기 행만 옮긴다, plan §8.2.3 '(소유자 행만)').
    병합(plan §5.2.5 (7)④·§4.7.1) — 없으면 insert, 같으면 skip, 사람 확정이 자동을 이기고,
    양쪽이 똑같이 사람 확정인데 값이 다르면 건너뛰고 conflicts[] 에 적는다(마지막 쓰기 승리 없음).
    조회·UPDATE 는 PK 가 아니라 (PK + 호출자 owner_sub) 로 건다 — PK 만으로 걸면 본문 owner_sub 만 자기 것으로
    적어 남의 행을 통째로 덮거나(권한 상승) 충돌 응답으로 읽어낼 수 있다. 소유자가 다른 같은 PK 는
    `owner_conflict`, UNIQUE 만 겹치는 새 행은 `unique_conflict` 로 그 줄만 눕히고 나머지는 계속 병합한다.
    """
    head, items = _parse(text)
    local_version = store.schema_version()
    if head.get("schema_version") != local_version:
        raise AppError("schema_mismatch",
                       f"스키마 버전이 다릅니다 — 본문 {head.get('schema_version')!r}, 이 박스 {local_version}."
                       " 양쪽 앱을 같은 SIF 로 올린 뒤 다시 시도하세요.", 409)

    meta: dict[str, tuple[list[str], list[str]]] = {}
    for table, row in items:
        if table not in TABLE_ORDER:
            raise AppError("E100", f"알 수 없는 표입니다 — {table}.", 422)
        if table not in meta:
            meta[table] = _table_meta(store, table)
        cols = meta[table][0]
        if "owner_sub" in cols and str(row.get("owner_sub") or "") != owner_sub:
            raise AppError("owner_mismatch",
                           f"다른 소유자의 행이 들어 있습니다 — {table}.owner_sub={row.get('owner_sub')!r}.", 409)

    inserted = merged = skipped = skipped_global = 0
    conflicts: list[dict] = []
    touched_targets: set[str] = set()
    with store.tx():
        for table, row in items:
            cols, pks = meta[table]
            if "owner_sub" not in cols:            # 공용 표는 병합하지 않는다(GLOBAL_TABLES 주석 참조).
                skipped_global += 1
                continue
            if not pks:                            # v1 DDL 의 rr_* 는 전부 PK 가 있다 — 없으면 병합 키를 정할 수 없다.
                raise AppError("E300", f"{table} 에 기본키가 없어 병합할 수 없습니다.", 500)
            unknown = [c for c in row if c not in cols]
            if unknown:
                raise AppError("E100", f"{table} 에 없는 열입니다 — {', '.join(sorted(unknown))}.", 422)
            values = {c: _decode(row.get(c)) for c in cols}
            pk_where = " AND ".join(f"{_quote(c)} = ?" for c in pks)
            where = pk_where + " AND owner_sub = ?"
            key_params = tuple(values[c] for c in pks) + (owner_sub,)
            found = store.query_one(
                f"SELECT {', '.join(_quote(c) for c in cols)} FROM {table} WHERE {where}", key_params,
            )
            if found is None:
                other = store.query_one(f"SELECT owner_sub FROM {table} WHERE {pk_where}",
                                        tuple(values[c] for c in pks))
                if other is not None:              # PK 는 같은데 주인이 다르다 — 값은 한 글자도 흘리지 않는다.
                    skipped += 1
                    conflicts.append({"table": table, "key": _key_of(row, pks), "reason": "owner_conflict"})
                    continue
                try:
                    store.execute(
                        f"INSERT INTO {table}({', '.join(_quote(c) for c in cols)})"
                        f" VALUES ({', '.join('?' for _ in cols)})",
                        tuple(values[c] for c in cols),
                    )
                except sqlite3.IntegrityError:
                    # PK 는 다른데 UNIQUE 만 겹치는 행(두 박스가 같은 과제를 각자 만든 경우) — 그 줄만 눕힌다.
                    skipped += 1
                    conflicts.append({"table": table, "key": _key_of(row, pks), "reason": "unique_conflict"})
                    continue
                inserted += 1
                if table == "rr_findings":
                    touched_targets.add(str(values.get("target_key") or ""))
                continue
            local = dict(found)
            changed = _diff_cols(local, row, cols)
            if not changed:
                skipped += 1
                continue
            local_rank, incoming_rank = _human_rank(table, local), _human_rank(table, row)
            if incoming_rank > local_rank:
                # owner_sub 는 병합으로 바뀌지 않는다(소유자 이전은 이관의 일이 아니다).
                assign = [c for c in cols if c not in pks and c != "owner_sub"]
                store.execute(
                    f"UPDATE {table} SET {', '.join(f'{_quote(c)} = ?' for c in assign)} WHERE {where}",
                    tuple([values[c] for c in assign] + list(key_params)),
                )
                merged += 1
                if table == "rr_findings":
                    touched_targets.add(str(values.get("target_key") or ""))
                continue
            skipped += 1
            if incoming_rank == local_rank and local_rank > 0:
                conflicts.append({
                    "table": table, "key": _key_of(row, pks),
                    "local": {c: _encode(local.get(c)) for c in changed},
                    "incoming": {c: row.get(c) for c in changed},
                })

    # §5.2.5 (5) — import 는 별도 병합 규칙을 두지 않고 §4.7.1 등록부 병합을 그대로 재사용한다.
    # merge 는 멱등이라 커밋 뒤 타깃마다 한 번만 부르면 rr_registry·rr_delta_contrib·rr_delta_priors 가 다시 맞는다.
    recomputed = 0
    for target_key in sorted(t for t in touched_targets if t):
        from app import registry as registry_module  # noqa: PLC0415 — 순환 임포트를 피하려 지연 임포트한다.

        registry_module.merge(store, target_key, owner_sub=owner_sub)
        recomputed += 1
    return {"inserted": inserted, "merged": merged, "skipped": skipped, "skipped_global": skipped_global,
            "recomputed_targets": recomputed, "conflicts": conflicts}


def row_digest(store: RiskStore, owner_sub: str) -> dict[str, tuple[int, str]]:
    """표별 (행 수, 행 내용 sha256) — 왕복 검증용. 시각 열까지 그대로 비교한다."""
    out: dict[str, tuple[int, str]] = {}
    for table in TABLE_ORDER:
        digest = hashlib.sha256()
        count = 0
        for row in _select(store, table, owner_sub, 0):
            digest.update(_json_line({"table": table, "row": row}).encode("utf-8"))
            count += 1
        out[table] = (count, digest.hexdigest())
    return out


__all__ = ["TABLE_ORDER", "GLOBAL_TABLES", "header_line", "iter_lines", "write_export_file", "import_jsonl", "row_digest",
           "read_origin", "EXPORTS_DIRNAME"]
