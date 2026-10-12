# 단위 탐침(tests/synth/units_probe.py)이 원장을 한 바이트도 바꾸지 않고, 그 수가 REST 로 세운 빌드(POST → GET …/units 의 stats)와 같은지 본다
"""입력은 생산자 경로다 — syn150 대본 → 어댑터 결과 쌍 → 스냅샷 둘·diff → `routes.create_target`(패널 대상, 단위 없음).
REST 는 세션 앱의 실제 경로(`POST /api/targets/{key}/units` · `GET /api/targets/{key}/units`)를 TestClient 로 부른다 — 라우트가
보는 저장소만 이 시험의 임시 DB 로 돌린다.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from app import identity, routes
from tests import factories
from tests.conftest import BACKEND_DIR
from tests.synth import units_probe

TOKEN = "heax_pat_test_fake_units_probe"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
OWNER_ME = {"id": 7, "email": factories.OWNER, "display_name": "합성", "role": "member", "organization": "qa"}


def _fingerprint(data_dir: Path) -> dict:
    """DB 본 파일과 WAL 의 해시, 그리고 디렉터리의 파일 목록. -shm 은 읽는 쪽도 표시를 쓰는 SQLite 공유 색인이라 뺀다."""
    out: dict = {"files": sorted(p.name for p in data_dir.iterdir())}
    for name in (units_probe.DB_FILENAME, f"{units_probe.DB_FILENAME}-wal"):
        path = data_dir / name
        out[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return out


def _run(capsys, *argv: str) -> tuple[int, list[dict], str]:
    rc = units_probe.main(list(argv))
    captured = capsys.readouterr()
    return rc, [json.loads(line) for line in captured.out.splitlines() if line.strip()], captured.err


@pytest.fixture
def http(client, risk_store, monkeypatch):
    """세션 앱의 REST — heax 는 TOKEN 만 과제 주인으로 받고, 라우트는 이 시험의 임시 DB 를 본다."""
    def heax(req: httpx.Request) -> httpx.Response:
        if req.headers.get("authorization") == f"Bearer {TOKEN}":
            return httpx.Response(200, json=OWNER_ME)
        return httpx.Response(401)

    monkeypatch.setattr(identity, "_transport", httpx.MockTransport(heax))
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    identity.reset_cache()
    yield client
    identity.reset_cache()


def test_탐침은_원장을_바꾸지_않고_REST_로_세운_빌드와_같은_수를_낸다(risk_store, http, capsys):
    syn = factories.make_diff_target(risk_store, 150)
    data_dir = risk_store.db_path.parent
    key = syn.target_key

    # 단위가 아직 없는 패널 대상 — 탐침은 계산만 하고 아무것도 남기지 않는다.
    before = _fingerprint(data_dir)
    rc, lines, err = _run(capsys, "--data-dir", str(data_dir), "--target-key", key)
    assert rc == 0, err
    assert _fingerprint(data_dir) == before
    assert "읽기 전용" in err and "스키마 v" in err
    assert [(x["diff_id"], x["target_key"], x["targets"], x["active_builds"]) for x in lines] == [
        (syn.diff_id, key, [key], [])]
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_unit_builds")["n"] == 0

    posted = http.post(f"/api/targets/{key}/units", headers=AUTH, json={"reason": "M0-c"})
    assert posted.status_code == 200, posted.text
    assert posted.json()["changed"] is True and posted.json()["status"] == "ok"
    listing = http.get(f"/api/targets/{key}/units", headers=AUTH)
    assert listing.status_code == 200, listing.text
    listing = listing.json()
    stats, rows = listing["stats"], listing["units"]
    assert listing["total"] == len(rows) == stats["units"]["reviewable"] + stats["units"]["excluded"]

    # 빌드가 선 원장에서도 쓰지 않고, 같은 수를 낸다.
    before = _fingerprint(data_dir)
    rc, lines, err = _run(capsys, "--data-dir", str(data_dir), "--target-key", key)
    assert rc == 0, err
    assert _fingerprint(data_dir) == before
    (line,) = lines
    assert line["status"] == "ok" and line["stats"] == stats == posted.json()["stats"]
    assert line["active_builds"] == [{"target_key": key, "rev": 1, "status": "ok", "same_input": True, "same_stats": True}]
    assert line["items"] == {"total": stats["items_total"], "by_layer": stats["by_layer"], "by_klass": stats["by_klass"]}
    assert line["lower_only_n"] == stats["lower_only_n"] > 0
    assert line["tol_unknown_n"] == stats["excluded_by_reason"].get("tol_unknown", 0)
    assert line["units"] == stats["units"] and line["units"]["reviewable"] > 1
    assert line["lines"] == {"total": stats["lines_total"], "reviewable": stats["reviewable_lines"],
                             "per_unit": stats["lines_per_unit"]}
    # 탐침의 백분위 식이 앱의 것과 같다(앱 _stats 가 오라클) — 그래야 글자 분포도 같은 식으로 읽는다.
    reviewable = [u for u in rows if u["reviewable"]]
    assert units_probe._pct([u["n_changes"] for u in reviewable]) == stats["lines_per_unit"]
    # 글자는 목록의 단위별 칸(원장 열)에서 다시 센다.
    for field in ("summary_chars", "evidence_chars"):
        assert line[field] == {"total": sum(u[field] or 0 for u in rows),
                               "per_unit": units_probe._pct([u[field] or 0 for u in reviewable])}, field
    assert line["summary_chars"]["total"] == stats["summary_chars_total"] > 0
    assert line["evidence_chars"]["per_unit"]["max"] > 0
    assert line["invariants"] == {k: len(v) if isinstance(v, list) else v for k, v in sorted(listing["invariants"].items())}
    assert line["invariants_ok"] is True
    assert isinstance(line["build_ms"], int) and line["build_ms"] >= 0
    assert {k: line["caps"][k] for k in ("target_lines", "max_lines", "small_lines", "units_max")} == {
        "target_lines": 20, "max_lines": 40, "small_lines": 15, "units_max": 60}
    assert set(line["caps_source"].values()) == {"default"}


def test_백분위는_앱과_같은_식이다():
    """정렬한 값의 int(q × n) 번째(app/units.py `_stats`). syn150 은 단위 줄 수가 고르게 20 이라 식이 틀려도 같은 값이 나온다 — 손으로 센다."""
    assert units_probe._pct(list(range(10, 0, -1))) == {"p50": 6, "p95": 10, "max": 10}
    assert units_probe._pct([3, 1, 2]) == {"p50": 2, "p95": 3, "max": 3}
    assert units_probe._pct([]) == {"p50": 0, "p95": 0, "max": 0}


def test_all_은_만든_순으로_diff_마다_한_줄이다(risk_store, capsys):
    first = factories.make_diff_target(risk_store, 3, open_target=False)
    second = factories.make_diff_target(risk_store, 3, seed=7, open_target=False)
    rc, lines, err = _run(capsys, "--data-dir", str(risk_store.db_path.parent), "--all")
    assert rc == 0, err
    assert [(x["diff_id"], x["targets"], x["status"]) for x in lines] == [
        (first.diff_id, [], "ok"), (second.diff_id, [], "ok")]
    assert "diff 2건" in err
    rc, lines, err = _run(capsys, "--data-dir", str(risk_store.db_path.parent), "--diff-id", second.diff_id)
    assert rc == 0 and [x["diff_id"] for x in lines] == [second.diff_id]


def test_손잡이는_앱과_같이_knobs_env_에서_읽는다(risk_store, capsys):
    syn = factories.make_diff_target(risk_store, 3, open_target=False)
    data_dir = risk_store.db_path.parent
    (data_dir / "knobs.env").write_text("HWAXRISK_UNIT_MAX_LINES=30  # 파일럿\n", encoding="utf-8")
    rc, (line,), err = _run(capsys, "--data-dir", str(data_dir), "--diff-id", syn.diff_id)
    assert rc == 0, err
    assert line["caps"]["max_lines"] == 30 and line["caps_source"]["HWAXRISK_UNIT_MAX_LINES"] == "knobs.env"
    assert "UNIT_MAX_LINES=30(knobs.env)" in err

    (data_dir / "knobs.env").write_text("HWAXRISK_UNIT_MAX_LINES=서른\n", encoding="utf-8")
    rc, lines, err = _run(capsys, "--data-dir", str(data_dir), "--diff-id", syn.diff_id)
    assert rc == 2 and lines == [] and "정수가 아닙니다" in err


def test_스키마가_다르면_계산하지_않는다(risk_store, monkeypatch, capsys):
    syn = factories.make_diff_target(risk_store, 3, open_target=False)
    data_dir = risk_store.db_path.parent
    from app import risk_store as risk_store_module

    monkeypatch.setattr(risk_store_module, "MIGRATIONS", [*risk_store_module.MIGRATIONS, (99, [])])
    before = _fingerprint(data_dir)
    rc, lines, err = _run(capsys, "--data-dir", str(data_dir), "--diff-id", syn.diff_id)
    assert rc == 2 and lines == [] and "코드 99" in err
    assert _fingerprint(data_dir) == before


def test_없는_DB_대상_diff_는_멈춘다(risk_store, tmp_path, capsys):
    absent = tmp_path / "absent"
    rc, lines, err = _run(capsys, "--data-dir", str(absent), "--all")
    assert rc == 2 and lines == [] and "새 DB 를 만들지 않는다" in err
    assert not absent.exists()
    data_dir = str(risk_store.db_path.parent)
    assert _run(capsys, "--data-dir", data_dir, "--target-key", "tgt-none")[0] == 2
    rc, lines, err = _run(capsys, "--data-dir", data_dir, "--diff-id", "diff:none")
    assert rc == 2 and "diff:none 가 없다" in err


def test_저장소는_쓰기를_SQLite_에서_거절한다(risk_store):
    store = units_probe.ReadOnlyStore(risk_store.db_path)
    try:
        assert not hasattr(store, "execute") and not hasattr(store, "tx")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            store.conn.execute("CREATE TABLE probe_write(a INTEGER)")
    finally:
        store.close()


def test_모듈로_띄운_새_프로세스가_데이터_디렉터리를_스스로_정한다(risk_store, tmp_path):
    """운영자가 부르는 꼴(`python -m tests.synth.units_probe`) — HWAXRISK_DATA_DIR 가 없어도 리포 안 data/ 를 만들지 않고(SIF 안에서는
    읽기 전용 루트라 실패한다) 준 디렉터리를 쓴다."""
    syn = factories.make_diff_target(risk_store, 3, open_target=False)
    env = {k: v for k, v in os.environ.items() if k not in ("HWAXRISK_DATA_DIR", "HEAX_DATA_DIR")}
    repo_data = BACKEND_DIR.parent / "data"
    existed = repo_data.exists()
    out = subprocess.run([sys.executable, "-m", "tests.synth.units_probe", "--data-dir", str(risk_store.db_path.parent),
                          "--diff-id", syn.diff_id], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["diff_id"] == syn.diff_id
    assert repo_data.exists() == existed
