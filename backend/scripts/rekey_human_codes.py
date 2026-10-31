#!/usr/bin/env python3
# A18 전 코드 꼴 mechanism 으로 적힌 사람 finding 을 대분류 + 세부 꼴 묶음 열쇠에 별칭으로 잇고 그 대상을 다시 병합한다(멱등 · dry-run 기본)
"""A18(사람 finding 의 mechanism · domain 을 택소노미 어휘로 검사)부터 입구는 웹 폼의 코드 꼴('thermal.cte_mismatch')을 대분류 +
세부('thermal' · 'cte_mismatch')로 나눠 적는다. 그 전에 코드 꼴 그대로 적힌 행은 다른 묶음 열쇠(cluster_key)라, 그 행이 남은 대상에서는
같은 위험의 새 사람 finding · 패널 원자와 다른 등록부 행에 선다. finding 행의 cluster_key 는 삽입 시 동결이라(plan §4.3.2 1) 고치지 않고
그 소유자의 별칭(rr_cluster_alias, 옛 열쇠 → 정본 꼴 열쇠)만 더한 뒤 그 열쇠의 사람 finding 이 있는 대상을 다시 병합한다. 코드의 세부와 다른
mechanism_detail 을 같이 적은 행은 어느 쪽이 맞는지 코드가 고를 수 없어 건너뛰고 알린다(지금 입구라면 422 다). 사람이 이미 다른 곳으로
이었거나 철회한 옛 열쇠의 별칭은 건드리지 않는다. cae00 배치 한 번 — 먼저 dry-run 으로 수를 보고 `--apply` 로 쓴다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, narrative, registry, taxonomy  # noqa: E402
from app.errors import AppError  # noqa: E402
from app.risk_store import RiskStore  # noqa: E402

DECIDED_BY = "code:human_code_rekey"


def plan_rows(store: RiskStore) -> dict:
    """옮길 사람 finding 과 그 정본 꼴 열쇠(쓰지 않는다) — {rows, skipped}."""
    codes = {str(item["code"]): item for item in taxonomy.load_taxonomy()["axes"]["mechanism"]}
    rows: list[dict] = []
    skipped: list[dict] = []
    for row in store.query(
            "SELECT finding_id, target_key, owner_sub, cluster_key, mechanism, mechanism_detail, subject_key, change_kind"
            " FROM rr_findings WHERE origin = 'human' ORDER BY finding_id", ()):
        item = codes.get(str(row["mechanism"] or ""))
        if item is None:
            continue
        major, detail = str(item["mechanism"]), str(item["detail"])
        given = str(row["mechanism_detail"] or "")
        if given not in ("", detail):
            skipped.append({"finding_id": row["finding_id"], "mechanism": row["mechanism"], "mechanism_detail": given,
                            "reason": "detail_differs"})
            continue
        new_key = narrative.cluster_key_of(major, detail, str(row["subject_key"] or ""), str(row["change_kind"] or ""))
        if new_key == row["cluster_key"]:
            continue
        rows.append({"finding_id": row["finding_id"], "target_key": row["target_key"], "owner_sub": row["owner_sub"],
                     "old_cluster_key": row["cluster_key"], "new_cluster_key": new_key,
                     "from": {"mechanism": row["mechanism"], "mechanism_detail": given},
                     "to": {"mechanism": major, "mechanism_detail": detail}})
    return {"rows": rows, "skipped": skipped}


def apply_rows(store: RiskStore, rows: list[dict]) -> dict:
    """별칭 행만 더하고(소유자마다 · 옛 열쇠 하나에 한 행 — 별칭은 그 소유자의 대상 전부에 듣는다) 그 열쇠의 사람 finding 이 있는 대상을
    다시 병합한다. 그 소유자의 별칭 행이 이미 있는 옛 열쇠는 건드리지 않는다 — 이 스크립트가 이은 것(2회 실행에 새 별칭 0)이든 사람이 다른
    곳으로 이었거나 철회한 것이든 사람의 결정을 덮지 않는다. 체인 상한 · 순환(add_cluster_alias 의 409)도 건너뛴다."""
    written: set[tuple[str, str]] = set()
    with store.tx():
        for row in rows:
            owner, old_key = row["owner_sub"], row["old_cluster_key"]
            if (owner, old_key) in written or store.query_one(
                    "SELECT 1 FROM rr_cluster_alias WHERE owner_sub = ? AND old_cluster_key = ?", (owner, old_key)):
                continue
            try:
                registry.add_cluster_alias(store, old_key, row["new_cluster_key"], owner_sub=owner, reason="taxonomy_major",
                                           evidence={"from": row["from"], "to": row["to"], "by": DECIDED_BY})
            except AppError:
                continue
            written.add((owner, old_key))
    targets = sorted({row["target_key"] for row in rows if (row["owner_sub"], row["old_cluster_key"]) in written})
    for target_key in targets:
        registry.merge(store, target_key)
    return {"aliases_written": len(written), "targets_merged": targets}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="코드 꼴 사람 finding 재열쇠(기본 dry-run)")
    parser.add_argument("--apply", action="store_true", help="별칭 행을 실제로 쓰고 대상을 다시 병합한다(기본은 dry-run)")
    parser.add_argument("--data-dir", default=None, help="데이터 디렉터리(기본 Settings)")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else config.settings.data_dir
    store = RiskStore(data_dir / "risk_review.db")
    store.open()
    store.migrate()
    try:
        plan = plan_rows(store)
        applied = apply_rows(store, plan["rows"]) if args.apply else {"aliases_written": 0, "targets_merged": []}
        print(json.dumps({"planned": len(plan["rows"]), "skipped": plan["skipped"], "applied": bool(args.apply), **applied},
                         ensure_ascii=False))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
