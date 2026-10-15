# 스키마 v4 원장 얼리기(재설계 M3 S3-1) — v5 블록 직전 코드로 얼린 v3 원장을 v4 로 올리고 M2 검토 루프로 셀·판정·보고서를 채운 DB 를 만든다
"""v5 이행 시험(`tests/rr/test_v5_upgrade.py`)이 여는 `tests/fixtures/v4/` 의 둘을 만든다.

- `risk_review.v4.db.gz` — 스키마 v4 DB. 합성 자료만 있다. 얼린 v3 원장(`tests/fixtures/v3` — 패널 대상 둘)을 v4 로 올린 위에
  카드 대조(`flow='cells'`) 대상 둘을 더한다. `reviewed` 는 M2 검토 루프가 끝까지 돈 대상(셀·카드 판정·호출 원장·전문가 보고서·
  카드 대조 finding·원장 마감 — 가짜 엔진 대본이 카드 둘을 FAIL·WARNING 으로 본다), `review_queued` 는 아직 집히지 않은 검토 잡이
  걸린 대상이다. v3 에서 온 `queued` 패널 잡도 그대로 집히지 않은 채 남는다 — 오른 DB 에서 두 러너가 그 잡들을 끝내는지 본다.
- `manifest.json` — 역할마다 target_key 와 시험이 집는 id, 얼린 코드.

cae00 의 실제 원장은 M2 코드가 쓴 v4 DB 다. 그 모양을 v5 블록 직전 코드의 생산자 경로로 만든다 — 대상·단위는 라우트
(`create_target(flow='cells')`), 셀·판정·보고서는 검토 루프(`tests/synth/review_rig.py` — 가짜 엔진을 꽂은 `ReviewLoop`)다.
원장 행을 손으로 INSERT 하지 않는다. 자격 행(`_user_credentials`·`_user_prefs`)은 얼리기 전에 지운다 — 시험이 사람 자격을 다시
등록한다(얼린 DB 에 암호문이 남지 않게).

**검토·패널 경로가 v5 열을 읽거나 쓰지 않는 코드에서만 돈다** — `risk_store.MIGRATIONS` 를 v4 까지로 잘라 DB 를 열기 때문에,
생산자가 v5 열(`rr_registry.support_*`·`rr_panels.kind`·`rr_targets.closure_json` …)을 건드리는 판(재설계 M3 S3-4 이후)에서는
'no such column' 으로 멈춘다. 그 뒤에 다시 만들어야 하면 이 파일이 처음 들어온 커밋을 꺼내 그 안에서 돌린다(새 코드로 만들면
'옛 DB 를 새 코드로 연다' 는 시험이 빈 시험이 된다 — legacy_build·v3_build 와 같은 규칙).

    cd backend && <리스크 venv>/bin/python -m tests.rr.v4_build --out tests/fixtures/v4
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from tests.rr import legacy_build as legacy
from tests.rr import v3_build

BACKEND_DIR = Path(__file__).resolve().parents[2]
V4_DIR = BACKEND_DIR / "tests" / "fixtures" / "v4"
DB_GZ = "risk_review.v4.db.gz"
FROZEN_SCHEMA = 4
# 가짜 엔진 대본 — 엔진 계약 예제 팩(pack_ok)의 점검 카드 둘을 걸리게 한다. 판정 행·단독 재질의·finding 이 원장에 남는다.
FLAGGED = {"DOC-CCT-MECH-2026-0000000101": ("yes", "FAIL"), "DOC-CCT-MECH-2026-0000000108": ("yes", "WARNING")}
# 합성 쌍의 크기 — 대본 셋짜리(부품 12개)다. 40건 쌍이면 스냅샷·diff 가 DB 의 대부분이라 픽스처가 세 배(약 900KB)로 커진다.
SYNTH_SIZE = 3


def _cells_target(store, review_rig, factories, routes) -> str:
    """카드 대조 대상 — review_rig.target 과 같은 입구(라우트 create_target(flow='cells'))에 작은 합성 쌍을 넣는다."""
    synth = factories.make_diff_target(store, SYNTH_SIZE, open_target=False)
    return routes.create_target(routes.TargetBody(kind="diff", ref_id=synth.diff_id, consent=True, flow="cells",
                                                  agents=[dict(r) for r in review_rig.ROSTER]),
                                ident=factories.ident(review_rig.OWNER))["target_key"]


def build(out_dir: Path) -> dict:
    data_dir = Path(tempfile.mkdtemp(prefix="rr-v4-build-"))
    try:
        return _build(data_dir, out_dir)
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


def _build(data_dir: Path, out_dir: Path) -> dict:
    os.environ["HWAXRISK_DATA_DIR"] = str(data_dir)
    for key in ("HEAX_DATA_DIR", "ROOT_PATH"):
        os.environ.pop(key, None)
    legacy._block_network()                                        # 검토 루프는 MockTransport 라 막힌 소켓을 지나지 않는다
    app = legacy._import_app()
    import pytest  # noqa: PLC0415 — 검토 시험대가 설정을 바꿔 끼우는 손(MonkeyPatch)만 빌린다

    from app import risk_store as store_module  # noqa: PLC0415
    from tests import factories  # noqa: PLC0415
    from tests.synth import fake_review_engine as fre  # noqa: PLC0415
    from tests.synth import review_rig  # noqa: PLC0415

    if [v for v, _ in store_module.MIGRATIONS][:FROZEN_SCHEMA] != list(range(1, FROZEN_SCHEMA + 1)):
        raise SystemExit("이 코드의 MIGRATIONS 앞머리가 v1~v4 가 아니다 — 얼릴 판을 다시 확인하라.")
    store_module.MIGRATIONS = store_module.MIGRATIONS[:FROZEN_SCHEMA]   # 이 프로세스에서만 — v4 DB 를 연다

    work = data_dir / "work"
    work.mkdir()
    db = work / "risk_review.db"
    with gzip.open(v3_build.V3_DIR / v3_build.DB_GZ, "rb") as src, open(db, "wb") as dst:
        shutil.copyfileobj(src, dst)
    v3_manifest = json.loads((v3_build.V3_DIR / "manifest.json").read_text(encoding="utf-8"))
    store = app["RiskStore"](db)
    store.open()
    if store.migrate() != FROZEN_SCHEMA:
        raise SystemExit(f"v{FROZEN_SCHEMA} 로 열리지 않았다.")
    try:
        with pytest.MonkeyPatch.context() as mp:
            review_rig.configure(mp, store, data_dir)
            reviewed: dict = {"target_key": _cells_target(store, review_rig, factories, app["routes"])}
            reviewed["job_id"] = review_rig.job(store, reviewed["target_key"])
            fake = fre.FakeReviewEngine(review_rig.packs())
            fake.verdicts.update(FLAGGED)
            review_rig.Rig(store, fake).finish(reviewed["job_id"])
            if review_rig.state(store, reviewed["job_id"]) != "completed":
                raise SystemExit(f"검토 잡이 끝나지 않았다 — {review_rig.job_row(store, reviewed['job_id'])}")
            queued: dict = {"target_key": _cells_target(store, review_rig, factories, app["routes"])}
            queued["job_id"] = review_rig.job(store, queued["target_key"])
        counts = {table: int(store.query_one(f"SELECT COUNT(*) AS n FROM {table} WHERE target_key = ?",
                                             (reviewed["target_key"],))["n"])
                  for table in ("rr_review_cells", "rr_card_verdicts", "rr_review_calls", "rr_expert_reports",
                                "rr_findings", "rr_coverage")}
        counts["card_findings"] = int(store.query_one(
            "SELECT COUNT(*) AS n FROM rr_findings WHERE target_key = ? AND source_kind = 'card_review'",
            (reviewed["target_key"],))["n"])
        if not counts["card_findings"] or not counts["rr_card_verdicts"]:
            raise SystemExit(f"카드 대조 finding·판정 행이 없다 — {counts}")
        store.execute("DELETE FROM _user_credentials")
        store.execute("DELETE FROM _user_prefs")
    finally:
        store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store.close()

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(db, "rb") as src, open(out_dir / DB_GZ, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            shutil.copyfileobj(src, gz)
    manifest = {"frozen_commit": v3_build._head(), "schema_version": FROZEN_SCHEMA, "owner": review_rig.OWNER,
                "service_pat_canary": review_rig.SERVICE_PAT, "reviewed_counts": counts,
                "targets": {**v3_manifest["targets"], "reviewed": reviewed, "review_queued": queued}}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                           encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="스키마 v4 원장 픽스처를 만든다(검토·패널 경로가 v5 열을 모르는 코드에서만).")
    parser.add_argument("--out", type=Path, default=V4_DIR, help="쓸 디렉터리(기본 tests/fixtures/v4)")
    args = parser.parse_args(argv)
    manifest = build(args.out)
    print(json.dumps({role: t["target_key"] for role, t in manifest["targets"].items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
