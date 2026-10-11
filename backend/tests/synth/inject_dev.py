# dev 원장에 합성 다건 변경 과제(과제·명명 치수·스냅샷 둘·diff)를 넣는다 — M1 dev 나갈 기준의 실 LLM 패널용, 운영 박스에서 쓰지 않는다
"""시험 공장(`factories.make_diff_target`)을 실제 데이터 디렉터리에 그대로 돌린다. 심사 대상·명단·잡은 만들지 않는다 —
명단은 실제 AIDataHub 에서 받아야 하므로 Claude 입구(`risk_next_step` → `risk_open_target` → `risk_start_job`)나 웹으로 연다.

사용(backend 에서 — 앱이 떠 있어도 된다. 러너 잠금은 쥐지 않고 이행도 하지 않는다).

    .venv/bin/python -m tests.synth.inject_dev --data-dir <앱 데이터 디렉터리> --owner <과제 주인 email> [--size 40]

- DB 가 없거나 스키마가 이 코드와 다르면 아무것도 쓰지 않고 멈춘다(이행은 앱이 기동 때 한다).
- 과제 코드는 `DEVSEED-<크기>-<씨앗>` 이고, 같은 코드가 이미 있으면 멈춘다(씨앗을 바꿔 다시 부른다).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.risk_store import MIGRATIONS, RiskStore
from tests import factories
from tests.synth import scripts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="inject_dev", description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", required=True, type=Path)
    ap.add_argument("--owner", required=True, help="과제 주인 email — Claude 입구가 위임으로 확인하는 신원과 같아야 한다")
    ap.add_argument("--size", type=int, default=40, choices=scripts.SIZES)
    ap.add_argument("--seed", type=int, default=scripts.SEED)
    args = ap.parse_args(argv)

    db = args.data_dir / "risk_review.db"
    if not db.is_file():
        print(f"멈춤 — {db} 가 없다(새 DB 를 만들지 않는다)", file=sys.stderr)
        return 2
    store = RiskStore(db)
    store.open()
    try:
        want = MIGRATIONS[-1][0]
        have = store.schema_version()
        if have != want:
            print(f"멈춤 — DB 스키마 {have} ≠ 코드 {want}. 앱을 이 코드로 먼저 띄워 이행한다", file=sys.stderr)
            return 2
        code = f"DEVSEED-{args.size}-{args.seed}"
        if store.query_one("SELECT 1 AS x FROM rr_projects WHERE owner_sub = ? AND code = ?", (args.owner, code)):
            print(f"멈춤 — {args.owner} 에게 {code} 과제가 이미 있다(--seed 를 바꾼다)", file=sys.stderr)
            return 2
        t = factories.make_diff_target(store, args.size, seed=args.seed, owner=args.owner, open_target=False,
                                       project={"code": code, "name": f"합성 다건 변경 {args.size}건(dev 나갈 기준)"})
    finally:
        store.close()
    print(json.dumps({"project_id": t.project_id, "code": code, "base_snapshot_id": t.base_snapshot_id,
                      "target_snapshot_id": t.target_snapshot_id, "diff_id": t.diff_id,
                      "changes": len(t.manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
