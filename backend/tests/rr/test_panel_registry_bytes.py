# 패널 대상의 등록부·완결 레벨 바이트 동일(재설계 M3 S3-4 회귀 가드, D-24) — 얼린 옛 원장 셋의 패널 대상을 지금 코드로 병합·판정한 값이 M2 코드가 낸 기준선과 같다
"""M3 는 `flow='cells'` 대상에서만 등록부 병합(M2 #7·#20)과 완결 판정을 바꾼다. 패널 대상(flow='panels')은 병합이 다시 계산하는 옛
열 · merged_json · status · 판정 후보와 `close_level` 의 M2 키가 한 칸도 바뀌지 않아야 한다(새 열·새 키는 더해져도 된다).

기준선 `tests/fixtures/panel_registry_golden.json` 은 v5 블록 뒤 · S3-4 앞 코드(M2 의 병합·판정 본문 그대로)로 이 파일이 만든다 —
얼린 원장(v2 legacy · v3 · v4)의 행만 읽으므로 같은 코드면 같은 값이다(시각·새 id 없음). 다시 만들 일이 있으면 그 커밋을 꺼내
`python -m tests.rr.test_panel_registry_bytes --write` 로 만든다(새 코드로 만들면 시험이 빈 시험이 된다).
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import sys
import tempfile
from pathlib import Path

from app import registry
from app.risk_store import RiskStore
from tests.rr import legacy_build, v3_build, v4_build

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "panel_registry_golden.json"
FROZEN = {"v2": legacy_build.LEGACY_DIR / legacy_build.DB_GZ, "v3": v3_build.V3_DIR / v3_build.DB_GZ,
          "v4": v4_build.V4_DIR / v4_build.DB_GZ}
# M2 의 병합이 다시 계산하던 열(registry._MERGE_OWNED_COLUMNS 의 M2 판)과 사람·코드 상태.
M2_ROW_COLUMNS = ("merged_json", "support", "contested", "direction", "mechanism", "mechanism_detail", "change_kind",
                  "subject_key", "severity", "sev3", "judgement", "evidence_grade", "precedent", "weak_subject", "priority",
                  "rejected", "human_n", "family_key", "status", "status_source")


def _thaw(gz_path: Path, directory: Path) -> RiskStore:
    db = directory / "risk_review.db"
    with gzip.open(gz_path, "rb") as src, open(db, "wb") as dst:
        shutil.copyfileobj(src, dst)
    store = RiskStore(db)
    store.open()
    store.migrate()
    return store


def panel_view(store: RiskStore) -> dict:
    """패널 대상마다 — 병합 뒤 등록부 행(M2 열) · 판정 후보 · close_level(persist=False) 전부."""
    out: dict = {}
    for target in store.query("SELECT target_key FROM rr_targets WHERE flow = 'panels' ORDER BY target_key"):
        key = str(target["target_key"])
        merged = registry.merge(store, key)
        rows = [dict(r) for r in store.query(
            f"SELECT cluster_key, {', '.join(M2_ROW_COLUMNS)} FROM rr_registry WHERE target_key = ? ORDER BY cluster_key",
            (key,))]
        out[key] = {"merge": {k: merged[k] for k in ("findings", "clusters", "verdict_candidate")},
                    "rows": rows, "close_level": registry.close_level(store, key, persist=False)}
    return out


def build() -> dict:
    out: dict = {}
    for name, gz_path in FROZEN.items():
        with tempfile.TemporaryDirectory(prefix="rr-panel-bytes-") as tmp:
            store = _thaw(gz_path, Path(tmp))
            try:
                out[name] = panel_view(store)
            finally:
                store.close()
    return out


def _project(golden: object, current: object) -> object:
    """기준선에 있는 키만 지금 값에서 뽑는다(새 키는 더해져도 된다 — 있던 키의 값만 본다)."""
    if isinstance(golden, dict) and isinstance(current, dict):
        return {k: _project(v, current.get(k)) for k, v in golden.items()}
    if isinstance(golden, list) and isinstance(current, list) and len(golden) == len(current):
        return [_project(g, c) for g, c in zip(golden, current)]
    return current


def test_panel_targets_keep_their_m2_registry_rows_verdict_and_close_level(tmp_path):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(golden) == set(FROZEN)
    current = build()
    for name in FROZEN:
        assert golden[name] and sum(len(t["rows"]) for t in golden[name].values()) > 0, f"{name} — 빈 시험이다"
        assert _project(golden[name], current[name]) == golden[name], name
    # 빈 시험이 아니다 — 등록부 행이 든 패널 대상이 있다.
    assert sum(len(t["rows"]) for ledger in golden.values() for t in ledger.values()) >= 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="패널 대상 등록부·완결 레벨 기준선을 만든다(S3-4 앞 코드에서만).")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    data = build()
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if args.write:
        GOLDEN.write_text(text, encoding="utf-8")
    print(json.dumps({n: {k: len(v["rows"]) for k, v in t.items()} for n, t in data.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
