# v5 이행(재설계 M3 S3-1) — 얼린 옛 원장 셋(v2 옛 타깃 · v3 패널 결과 원문 · M2 검토 루프가 채운 v4)이 행을 그대로 둔 채 v5 로 오르고, 오른 원장에서 패널·검토 경로가 그대로 돈다
"""cae00 의 원장은 M2 코드가 쓴 v4 DB 다(그 전 박스는 v2·v3). v5 블록이 그 원장을 한 번에 출발 버전 사본 하나로 올리고 옛 행의 값을
한 칸도 바꾸지 않는지, 옛 행이 새 열을 어떻게 읽히는지(패널은 coverage, 나머지는 빈 칸), 오른 원장에 걸린 옛 잡 — 집히지 않은 패널
잡과 검토 잡 — 을 두 러너가 집어 끝내는지를 본다(D-24 · M3.md 3절 회귀 가드).

v2 원장은 `tests/fixtures/legacy`(legacy_build), v3 은 `tests/fixtures/v3`(v3_build), v4 는 `tests/fixtures/v4`(v4_build — v5 블록 직전
코드)다. 새 표의 행은 각 표의 생산자 걸음(S3-4~S3-9 · C3-12)이 선 뒤 `tests/rr/test_v5_rows.py` 가 본다.
"""
from __future__ import annotations

import dataclasses
import json
import sqlite3

import httpx
import pytest

from app import config, planner, review_cells, routes, runner
from app.risk_store import MIGRATIONS, RiskStore
from tests.rr import legacy_build as legacy
from tests.rr import v3_build, v4_build
from tests.rr.test_legacy_flow import _IPV4, _SECRET_SHAPES, _all_text, register_job_person
from tests.rr.test_v4_upgrade import _rows, _snapshot, _thaw, _user_version
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig
from tests.test_store import V5_ADDED_COLUMNS, V5_TABLES

LATEST = MIGRATIONS[-1][0]
V4_MANIFEST = json.loads((v4_build.V4_DIR / "manifest.json").read_text(encoding="utf-8"))
FROZEN = {"v2": (legacy.LEGACY_DIR / legacy.DB_GZ, legacy.FROZEN_SCHEMA),
          "v3": (v3_build.V3_DIR / v3_build.DB_GZ, v3_build.FROZEN_SCHEMA),
          "v4": (v4_build.V4_DIR / v4_build.DB_GZ, v4_build.FROZEN_SCHEMA)}


@pytest.fixture
def no_network(monkeypatch):
    """러너·브리프가 게이트웨이를 부르면 연결 오류로 답한다 — 시험이 dev 박스의 실 게이트웨이에 닿지 않게."""
    def _refused(*args, **_kwargs):
        raise httpx.ConnectError("시험은 외부를 부르지 않는다.", request=args[-1])

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refused)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refused)


def _risen(tmp_path, frozen: str) -> RiskStore:
    store = RiskStore(_thaw(FROZEN[frozen][0], tmp_path))
    store.open()
    assert store.migrate() == LATEST
    return store


# ---------------------------------------------------------------- ① 행을 그대로 둔 채 한 사본으로 오른다
@pytest.mark.parametrize("frozen", sorted(FROZEN))
def test_a_frozen_ledger_rises_to_v5_once_keeping_every_row(tmp_path, frozen):
    gz_path, version = FROZEN[frozen]
    db = _thaw(gz_path, tmp_path)
    assert _user_version(db) == version < LATEST == 5
    before = _snapshot(db)

    for _ in range(2):                                          # 두 번째 기동은 아무것도 하지 않는다
        store = RiskStore(db)
        store.open()
        try:
            assert store.migrate() == LATEST
        finally:
            store.close()
        copies = sorted(tmp_path.glob("risk_review.db.pre-migrate-*"))
        assert len(copies) == 1 and copies[0].name.startswith(f"risk_review.db.pre-migrate-v{version}-"), copies
    assert _user_version(copies[0]) == version and _snapshot(copies[0]) == before

    after = _snapshot(db)
    con = sqlite3.connect(db)
    try:
        for table, (cols, rows) in before.items():
            assert set(cols) <= set(after[table][0]), table
            if table == "_schema_migrations":                   # 올린 판의 이력이 뒤에 붙는다
                assert _rows(con, table, cols)[:len(rows)] == rows
                assert [r[0] for r in _rows(con, table, ["version"])] == [v for v, _ in MIGRATIONS]
                continue
            assert _rows(con, table, cols) == rows, f"{table} 의 옛 행이 바뀌었다"
        # 옛 행의 새 열 — 패널은 coverage(쟁점 패널이 아니다), 나머지 새 열은 비어 있다. 새 표는 비어 있다.
        assert {r[0] for r in con.execute("SELECT DISTINCT kind FROM rr_panels")} == {"coverage"}
        for table, cols in V5_ADDED_COLUMNS.items():
            blank = [c for c in sorted(cols) if c != "kind"]
            where = " OR ".join(f"{c} IS NOT NULL" for c in blank)
            assert con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0] == 0, table
        for table in V5_TABLES:
            assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
        # 빈 시험이 아니다 — 옛 원장에 타깃·잡·finding·패널이 있고, v4 원장에는 M2 검토 루프의 원장이 있다.
        for table in ("rr_targets", "rr_jobs", "rr_findings", "rr_panels"):
            assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] > 0, table
        if version >= 4:
            counts = V4_MANIFEST["reviewed_counts"]
            key = V4_MANIFEST["targets"]["reviewed"]["target_key"]
            for table in ("rr_review_cells", "rr_card_verdicts", "rr_review_calls", "rr_expert_reports"):
                assert con.execute(f"SELECT COUNT(*) FROM {table} WHERE target_key = ?", (key,)).fetchone()[0] == (
                    counts[table]) > 0, table
            assert con.execute("SELECT COUNT(*) FROM rr_findings WHERE source_kind = 'card_review'").fetchone()[0] == (
                counts["card_findings"]) > 0
    finally:
        con.close()


# ---------------------------------------------------------------- ② 오른 원장에서 옛 잡이 끝까지 돈다
def test_the_queued_panel_job_of_a_v4_ledger_runs_through_the_runner_after_the_rise(tmp_path, no_network, monkeypatch):
    """v4 원장에서 아직 집히지 않은 Tier A 패널 잡(v3 에서 온 것)을 v5 러너가 집어 패널을 끝내고 잡을 닫는다. 새 패널 행은
    coverage 패널이고(쟁점 패널이 아니다) 패널 대상에는 쟁점이 생기지 않는다."""
    store = _risen(tmp_path, "v4")
    monkeypatch.setattr(routes, "get_store", lambda: store)
    target = V4_MANIFEST["targets"]["queued"]
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    secrets = data_dir / config.SECRETS_FILENAME
    secrets.write_text("HWAXRISK_PORTAL_PAT=test-service-pat\n", encoding="utf-8")
    secrets.chmod(0o600)
    cfg = dataclasses.replace(config.settings, data_dir=data_dir)
    engine = legacy.LegacyEngine(legacy.spec_builder(store, target["target_key"], planner.domain_of))
    try:
        register_job_person(store, target["job_id"])
        job = runner.claim_next_job(store, cfg)
        assert job is not None and job["id"] == target["job_id"]
        out = runner.run_panel(store, cfg, engine, job)
        assert out["status"] == "done", out
        assert planner.check_invariants(store, target["target_key"]) == []
        panel = store.query_one("SELECT status, kind, issue_id FROM rr_panels WHERE id = ?", (out["panel_id"],))
        assert (panel["status"], panel["kind"], panel["issue_id"]) == ("done", "coverage", None)
        again = runner.claim_next_job(store, cfg)
        assert again is not None and runner.run_panel(store, cfg, engine, again)["status"] == "no_panel"
        assert store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (target["job_id"],))["state"] == "completed"
        assert store.query_one("SELECT COUNT(*) AS n FROM rr_issues")["n"] == 0
    finally:
        store.close()


def test_the_queued_review_job_of_a_v4_ledger_runs_through_the_review_loop_after_the_rise(tmp_path, monkeypatch):
    """v4 원장에서 아직 집히지 않은 검토 잡을 v5 의 검토 루프가 집어 끝까지 돈다 — 격자의 셀이 전부 닫히고 전문가 보고서가 선다.
    사람 자격은 얼린 DB 에 없어 다시 등록한다(서비스 PAT 는 쓰지 않는다)."""
    store = _risen(tmp_path, "v4")
    try:
        review_rig.configure(monkeypatch, store, tmp_path)
        review_rig.pat(store)
        target = V4_MANIFEST["targets"]["review_queued"]
        assert review_rig.state(store, target["job_id"]) == "queued"
        fake = fre.FakeReviewEngine(review_rig.packs())
        review_rig.Rig(store, fake).finish(target["job_id"])
        assert review_rig.state(store, target["job_id"]) == "completed"
        cells = store.query("SELECT state FROM rr_review_cells WHERE target_key = ?", (target["target_key"],))
        assert cells and {c["state"] for c in cells} <= set(review_cells.CELL_STATES) - {"pending", "running"}
        assert review_cells.review_invariants(store, target["target_key"]) == []
        heads = {r["state"] for r in store.query("SELECT state FROM rr_expert_reports WHERE target_key = ?",
                                                 (target["target_key"],))}
        assert heads == {"ready"}
        assert all(r["authorization"] != f"Bearer {review_rig.SERVICE_PAT}" for r in fake.requests)
    finally:
        store.close()


# ---------------------------------------------------------------- ③ 얼린 v4 원장의 위생
def test_the_v4_fixture_is_a_v4_ledger_without_internal_address_secret_or_credential(tmp_path):
    db = _thaw(FROZEN["v4"][0], tmp_path)
    assert _user_version(db) == V4_MANIFEST["schema_version"] == v4_build.FROZEN_SCHEMA
    text = _all_text(db)
    assert len(text) > 10_000                                   # 빈 DB 를 훑고 통과하지 않는다
    assert set(_IPV4.findall(text)) <= {"127.0.0.1"}
    assert V4_MANIFEST["service_pat_canary"] not in text and v3_build.SERVICE_PAT_CANARY not in text
    assert [p.pattern for p in _SECRET_SHAPES if p.search(text)] == []
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM _user_credentials").fetchone()[0] == 0
    finally:
        con.close()
