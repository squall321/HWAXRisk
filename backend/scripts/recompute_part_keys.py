#!/usr/bin/env python3
# rr_dim_vocab 메이저 승급 후 rr_part_keys 재계산(멱등·dry-run 기본) — 기존 스냅샷의 ckey·ir_hash 는 건드리지 않는다(plan §2.7.1)
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, ir_builder, routes  # noqa: E402
from app.common import canonical_json, now_epoch  # noqa: E402
from app.risk_store import RiskStore  # noqa: E402

DECIDED_BY = "code:vocab_recompute"


def plan_rows(store: RiskStore) -> list[dict]:
    """현재 사전으로 다시 만든 name_norm_canon 이 달라진 rr_part_keys 행 목록(쓰지 않는다)."""
    vocab = routes._vocab_row(store)
    synonyms = {**ir_builder.SEED_SYNONYMS, **(vocab["synonyms"] or {})}
    stop_tokens = tuple({*ir_builder.SEED_STOP_TOKENS, *(vocab["stop_tokens"] or ())})
    out: list[dict] = []
    for row in store.query(
        "SELECT ckey, owner_sub, status, name_norm_canon, geom_bucket, material_norm, vocab_version"
        " FROM rr_part_keys WHERE status != 'merged' ORDER BY ckey", ()
    ):
        after = ir_builder.name_norm_canon(str(row["name_norm_canon"]), stop_tokens=stop_tokens,
                                           synonyms=synonyms)
        if after == row["name_norm_canon"]:
            continue
        new_ckey = ir_builder.canonical_part_key(after, str(row["geom_bucket"]), str(row["material_norm"]))
        if new_ckey == row["ckey"]:
            continue
        out.append({"ckey": new_ckey, "merged_into": str(row["ckey"]), "owner_sub": str(row["owner_sub"]),
                    "name_norm_canon_before": str(row["name_norm_canon"]), "name_norm_canon_after": after,
                    "geom_bucket": str(row["geom_bucket"]), "material_norm": str(row["material_norm"]),
                    "from_vocab_version": row["vocab_version"], "to_vocab_version": vocab["vocab_version"]})
    return out


def apply_rows(store: RiskStore, rows: list[dict], *, vocab_version: str) -> int:
    """별칭 행만 더한다(INSERT OR IGNORE) — 사람이 만든 행·confirmed 행은 건드리지 않는다."""
    written = 0
    now = now_epoch()
    with store.tx():
        for row in rows:
            existing = store.query_one("SELECT ckey, status FROM rr_part_keys WHERE ckey = ?", (row["ckey"],))
            if existing is not None:
                continue                     # confirmed·사람 병합 행은 그대로 둔다(§2.7.3 같은 규칙)
            store.execute(
                "INSERT OR IGNORE INTO rr_part_keys(ckey, owner_sub, status, merged_into, name_norm_canon,"
                " geom_bucket, material_norm, vocab_version, decided_by, decided_at, merge_evidence_json,"
                " created_at, updated_at) VALUES (?,?, 'merged', ?,?,?,?,?,?,?,?,?,?)",
                (row["ckey"], row["owner_sub"], row["merged_into"], row["name_norm_canon_after"],
                 row["geom_bucket"], row["material_norm"], vocab_version, DECIDED_BY, now,
                 canonical_json({k: row[k] for k in ("from_vocab_version", "to_vocab_version",
                                                     "name_norm_canon_before", "name_norm_canon_after")}),
                 now, now),
            )
            written += 1
        # 재계산이 돌았음을 사전 행에 남긴다 — health 의 vocab_recompute_pending 이 내려간다.
        vocab = routes._vocab_row(store)
        routes._save_vocab(store, synonyms=vocab["synonyms"], stop_tokens=vocab["stop_tokens"],
                           version=vocab["vocab_version"], owner_sub=DECIDED_BY, recomputed_at=now)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="rr_part_keys 재계산(기본 dry-run)")
    parser.add_argument("--apply", action="store_true", help="실제로 별칭 행을 쓴다(기본은 dry-run)")
    parser.add_argument("--data-dir", default=None, help="데이터 디렉터리(기본 Settings)")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else config.settings.data_dir
    store = RiskStore(data_dir / "risk_review.db")
    store.open()
    store.migrate()
    try:
        rows = plan_rows(store)
        vocab_version = routes._vocab_row(store)["vocab_version"]
        written = apply_rows(store, rows, vocab_version=vocab_version) if args.apply else 0
        print(json.dumps({"planned": len(rows), "written": written, "applied": bool(args.apply),
                          "vocab_version": vocab_version}, ensure_ascii=False))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
