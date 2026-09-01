#!/usr/bin/env python3
# 택소노미 재매핑 잡 — mechanism_detail 을 다른 값으로 옮길 때 별칭 행만 더한다(멱등·dry-run 기본, plan §7.7·§4.3.2)
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import learning  # noqa: E402
from app.risk_store import RiskStore  # noqa: E402

# 재매핑 본체는 app.learning 에 있다 — 이 파일은 dry-run 기본의 얇은 CLI 다.
plan_remap = learning.plan_remap
apply_remap = learning.apply_remap
DECIDED_BY = learning.REMAP_DECIDED_BY


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="택소노미 재매핑(기본 dry-run)")
    parser.add_argument("--mechanism", required=True)
    parser.add_argument("--from-detail", required=True)
    parser.add_argument("--to-detail", required=True)
    parser.add_argument("--apply", action="store_true", help="별칭 행을 실제로 쓴다(기본은 dry-run)")
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args(argv)

    from app import config

    data_dir = Path(args.data_dir) if args.data_dir else config.settings.data_dir
    store = RiskStore(data_dir / "risk_review.db")
    store.open()
    store.migrate()
    try:
        rows = plan_remap(store, mechanism=args.mechanism, from_detail=args.from_detail,
                          to_detail=args.to_detail)
        applied = apply_remap(store, rows) if args.apply else {"aliases_written": 0}
        print(json.dumps({"planned": len(rows), "applied": bool(args.apply), **applied},
                         ensure_ascii=False))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
