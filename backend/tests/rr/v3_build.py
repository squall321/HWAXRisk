# 스키마 v3 원장 얼리기(재설계 M2 C1) — v4 블록 직전 코드로 패널 결과 원문(rr_panels.result_gz)이 든 v3 DB 를 만든다
"""v4 이행 시험(`tests/rr/test_v4_upgrade.py`)이 여는 `tests/fixtures/v3/` 의 둘을 만든다.

- `risk_review.v3.db.gz` — 스키마 v3 DB. 합성 자료만 있고 타깃 둘을 담는다.
  `done` 은 러너가 Tier A·Tier C 잡을 끝까지 돈 타깃(엔진 결과 원문이 든 done 패널), `queued` 는 아직 집히지 않은
  Tier A 잡이 걸린 타깃이다 — 오른 DB 에서 러너가 그 잡을 집어 끝내는지 본다.
- `manifest.json` — 역할마다 target_key 와 시험이 집는 id, 얼린 코드.

cae00 의 실제 원장은 M1 코드가 쓴 v3 DB 다. 그 모양을 지금 코드의 생산자 경로로 만든다 — 과제·스냅샷·diff·타깃은
`legacy_build._open_target`(라우트·`ir_builder.freeze_snapshot`·`create_diff`), 패널은 러너(`create_job` →
`claim_next_job` → `run_panel`)다. 원장 행을 손으로 INSERT 하지 않는다.

**패널 경로가 v4 열을 읽거나 쓰지 않는 코드에서만 돈다** — `risk_store.MIGRATIONS` 를 v3 까지로 잘라 DB 를 열기 때문에,
생산자가 v4 열(`rr_targets.flow`·`rr_jobs.mode` …)을 건드리는 판(재설계 M2 C2 이후)에서는 'no such column' 으로 멈춘다.
그 뒤에 다시 만들어야 하면 이 파일이 처음 들어온 커밋을 꺼내 그 안에서 돌린다(새 코드로 만들면 '옛 DB 를 새 코드로 연다'
는 시험이 빈 시험이 된다 — legacy_build 와 같은 규칙).

    cd backend && <리스크 venv>/bin/python -m tests.rr.v3_build --out tests/fixtures/v3
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tests.rr import legacy_build as legacy

BACKEND_DIR = Path(__file__).resolve().parents[2]
V3_DIR = BACKEND_DIR / "tests" / "fixtures" / "v3"
DB_GZ = "risk_review.v3.db.gz"
FROZEN_SCHEMA = 3
ROLES = ("done", "queued")
OWNER = legacy.OWNER
# 서비스 PAT 는 임시 데이터 디렉터리의 secrets.env 에만 둔다. 얼린 DB 에 이 문자열이 보이면 시험이 붉다.
SERVICE_PAT_CANARY = "v3-fixture-canary-pat"


def _head() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=BACKEND_DIR, capture_output=True,
                             text=True, check=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def _panel_ids(store, target_key: str) -> list[str]:
    return [r["id"] for r in store.query(
        "SELECT id FROM rr_panels WHERE target_key = ? ORDER BY panel_no", (target_key,))]


def build(out_dir: Path) -> dict:
    data_dir = Path(tempfile.mkdtemp(prefix="rr-v3-build-"))
    try:
        return _build(data_dir, out_dir)
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


def _build(data_dir: Path, out_dir: Path) -> dict:
    os.environ["HWAXRISK_DATA_DIR"] = str(data_dir)
    for key in ("HEAX_DATA_DIR", "ROOT_PATH"):
        os.environ.pop(key, None)
    secrets = data_dir / "secrets.env"
    secrets.write_text(f"HWAXRISK_PORTAL_PAT={SERVICE_PAT_CANARY}\n", encoding="utf-8")
    secrets.chmod(0o600)
    legacy._block_network()
    app = legacy._import_app()
    from app import identity  # noqa: PLC0415
    from app import risk_store as store_module  # noqa: PLC0415

    if [v for v, _ in store_module.MIGRATIONS][:FROZEN_SCHEMA] != list(range(1, FROZEN_SCHEMA + 1)):
        raise SystemExit("이 코드의 MIGRATIONS 앞머리가 v1~v3 이 아니다 — 얼릴 판을 다시 확인하라.")
    store_module.MIGRATIONS = store_module.MIGRATIONS[:FROZEN_SCHEMA]   # 이 프로세스에서만 — v3 DB 를 연다

    routes, runner = app["routes"], app["runner"]
    cfg = app["config"].settings
    work = data_dir / "work"
    store = app["RiskStore"](work / "risk_review.db")
    store.open()
    if store.migrate() != FROZEN_SCHEMA:
        raise SystemExit(f"v{FROZEN_SCHEMA} 로 열리지 않았다.")
    routes.get_store = lambda: store                                # 라우트는 모듈 전역 저장소를 부른다
    ident = identity.Identity(email=OWNER, display_name="v3 원장", role="user", organization="qa",
                              anonymous=False, source="bearer")
    try:
        # done — Tier A 잡과 Tier C 잡을 러너가 끝까지 돈 타깃. 패널마다 엔진 결과 원문(v3 의 result_gz)이 남는다.
        done = legacy._open_target(app, store, ident, "V3-DONE")
        done["job_ids"] = [legacy._run_one_job(app, store, cfg, done["target_key"], tier) for tier in ("A", "C")]
        done["panel_ids"] = _panel_ids(store, done["target_key"])

        # queued — 아직 집히지 않은 Tier A 잡이 걸린 타깃.
        queued = legacy._open_target(app, store, ident, "V3-QUEUED")
        queued["job_id"] = runner.create_job(store, queued["target_key"], "A", owner_sub=OWNER, consent=False,
                                             settings=cfg)["job_id"]
        result_gz_n = int(store.query_one(
            "SELECT COUNT(*) AS n FROM rr_panels WHERE result_gz IS NOT NULL")["n"])
        if result_gz_n == 0 or len(done["panel_ids"]) < 2:
            raise SystemExit(f"패널 결과 원문이 든 done 패널이 모자라다 — 패널 {done['panel_ids']}, result_gz {result_gz_n}")
    finally:
        store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store.close()

    out_dir.mkdir(parents=True, exist_ok=True)
    with open(work / "risk_review.db", "rb") as src, open(out_dir / DB_GZ, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            shutil.copyfileobj(src, gz)
    manifest = {"frozen_commit": _head(), "schema_version": FROZEN_SCHEMA, "owner": OWNER,
                "result_gz_n": result_gz_n, "targets": {"done": done, "queued": queued}}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                           encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="스키마 v3 원장 픽스처를 만든다(패널 경로가 v4 열을 모르는 코드에서만).")
    parser.add_argument("--out", type=Path, default=V3_DIR, help="쓸 디렉터리(기본 tests/fixtures/v3)")
    args = parser.parse_args(argv)
    manifest = build(args.out)
    print(json.dumps({role: t["target_key"] for role, t in manifest["targets"].items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
