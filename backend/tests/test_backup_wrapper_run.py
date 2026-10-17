# 암호화 백업 래퍼를 실제로 돌린다 — 이 앱만 박스별 칸으로, 키가 있으면 평문을 빼 달라고, 경로는 리포에서 유도(10-17 결정 2)
#
# 가짜 허브 루트(HEAXHUB_ROOT)에 데이터 폴더와 대역 appdata-to-drive.sh(받은 환경을 적는다)를 두고, age 는 대역(받은 평문을 그대로
# 남긴다 — 그 사본이 앱이 쓰는 중인 WAL 의 행까지 담았는지 본다)이다. 실제 Drive · 실제 키는 쓰지 않는다.
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backup-to-drive.sh"

_FAKE_AGE = r'''#!/usr/bin/env bash
# age -r <키> -o <출력> <입력> — 입력을 '보았다' 폴더에 남기고 출력에는 표시만 쓴다
out=""; in=""
while [ $# -gt 0 ]; do case "$1" in -r) shift 2 ;; -o) out="$2"; shift 2 ;; *) in="$1"; shift ;; esac; done
cp "$in" "$AGE_SEEN/$(basename "$in")"
printf 'age-encrypted\n' > "$out"
'''

_FAKE_HUB = r'''#!/usr/bin/env bash
printf 'ONLY=%s\nCHANNEL=%s\nEXCL=%s\n' "${HEAX_APPDATA_ONLY:-}" "${HEAX_APPDATA_CHANNEL:-}" "${HEAX_BACKUP_EXCLUDE:-}" > "$HUB_SEEN"
'''


@pytest.fixture()
def box(tmp_path):
    heax = tmp_path / "HEAXHub"
    data = heax / "var/app_data/hwax_risk"
    data.mkdir(parents=True)
    (heax / "deploy/apptainer").mkdir(parents=True)
    (heax / "deploy/apptainer/appdata-to-drive.sh").write_text(_FAKE_HUB)
    (heax / "deploy/apptainer/appdata-to-drive.sh").chmod(0o755)
    shim = tmp_path / "bin"
    shim.mkdir()
    seen = tmp_path / "age-seen"
    seen.mkdir()

    def run(*args, key=True, age=True, **env):
        if key:
            (data / "secrets.env").write_text("HWAXRISK_BACKUP_KEY=age1testrecipient\n")
        if age:
            (shim / "age").write_text(_FAKE_AGE)
            (shim / "age").chmod(0o755)
        full = {"PATH": f"{shim}:/usr/bin:/bin", "HOME": str(tmp_path), "HEAXHUB_ROOT": str(heax), "HWAX_BOX": "testbox",
                "AGE_SEEN": str(seen), "HUB_SEEN": str(tmp_path / "hub-seen"), **env}
        r = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=60, env=full)
        hub = {}
        if (tmp_path / "hub-seen").exists():
            hub = dict(ln.split("=", 1) for ln in (tmp_path / "hub-seen").read_text().splitlines())
        return r, hub
    return run, data, seen


def _live_db(data: Path) -> sqlite3.Connection:
    c = sqlite3.connect(data / "risk_review.db")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE t (x INTEGER)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(2, 12)])
    c.commit()                                                 # 앱이 쥐고 있다 — 새 행은 -wal 에만 있다
    return c


def test_경로는_리포에서_유도한다():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "/home/" not in src, "박스 절대경로가 박혀 있다 — cae00(~/Projects)에서 조용히 깨진다"


def test_키가_있으면_암호_사본을_만들고_이_앱만_박스별_칸으로_평문은_빼_달라고_한다(box):
    run, data, seen = box
    app = _live_db(data)
    (data / "exports").mkdir()
    (data / "exports/1.jsonl").write_text("{}")
    try:
        r, hub = run()
    finally:
        app.close()
    assert r.returncode == 0, r.stdout + r.stderr
    assert (data / "risk_review.db.age").read_text() == "age-encrypted\n" and (data / "exports.tar.age").exists()
    assert hub == {"ONLY": "hwax_risk", "CHANNEL": "risk-backup/testbox",
                   "EXCL": "hwax_risk/risk_review.db hwax_risk/exports"}, hub
    n = sqlite3.connect(seen / "risk_review.db").execute("SELECT count(*) FROM t").fetchone()[0]
    assert n == 11, f"암호화한 사본이 WAL 의 행을 빠뜨렸다({n}행)"
    assert "backup_unencrypted" not in r.stdout


def test_키가_없으면_age_없이도_돌고_평문을_빼_달라고_하지_않는다(box):
    """키가 없을 때도 평문을 빼면 DB 가 아예 안 실린다 — 예전 그대로였다."""
    run, data, _ = box
    sqlite3.connect(data / "risk_review.db").close()
    r, hub = run(key=False, age=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "backup_unencrypted" in r.stdout and hub["EXCL"] == "" and hub["ONLY"] == "hwax_risk"


def test_허브가_올리지_않는_폴더면_멈춘다(box, tmp_path):
    run, data, _ = box
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "secrets.env").write_text("HWAXRISK_BACKUP_KEY=age1testrecipient\n")
    r, hub = run(key=False, HWAXRISK_DATA_DIR=str(other))
    assert r.returncode == 1 and "허브의 var/app_data/hwax_risk 가 아니다" in r.stdout, r.stdout + r.stderr
    assert hub == {}


def test_환경이_없으면_허브의_데이터_폴더를_쓴다(box):
    run, data, _ = box
    (data / "origin.json").write_text("{}")
    r, _ = run("--dry-run")
    assert r.returncode == 0 and f"data_dir={data}" in r.stdout and "origin.json" in r.stdout, r.stdout + r.stderr
