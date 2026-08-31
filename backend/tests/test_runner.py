# RiskRunner 골격 — start/stop·status() 의 스레드 3개(panel_loop·sync_loop·nightly_loop)·lifespan 배선
from __future__ import annotations

import time

from app.runner import RiskRunner

THREADS = ["panel_loop", "sync_loop", "nightly_loop"]


def test_start_status_stop():
    runner = RiskRunner(store=None, settings=None)
    status = runner.status()
    assert [t["name"] for t in status["threads"]] == THREADS
    assert all(t["alive"] is False and t["last_tick"] is None for t in status["threads"])

    runner.start()
    try:
        time.sleep(0.05)
        status = runner.status()
        assert [t["name"] for t in status["threads"]] == THREADS
        assert all(t["alive"] is True for t in status["threads"])
        assert all(isinstance(t["last_tick"], float) for t in status["threads"])
    finally:
        t0 = time.monotonic()
        runner.stop()
    assert time.monotonic() - t0 < 2.0
    assert all(t["alive"] is False for t in runner.status()["threads"])
    runner.stop()  # 멱등


def test_lifespan_wires_runner_and_box_state(client):
    from app.main import app

    status = app.state.runner.status()
    assert [t["name"] for t in status["threads"]] == THREADS
    assert all(t["alive"] for t in status["threads"])
    assert isinstance(app.state.hostname, str) and app.state.hostname
    assert app.state.box_match is True
    assert app.state.secrets_valid is False  # 테스트 데이터 루트에는 secrets.env 가 없다.
    # /api/health 형식은 고정이고 러너 상태를 싣지 않는다.
    assert set(client.get("/api/health").json()) == {"ok", "app_version", "schema_version"}


def test_origin_json_written(client, session_data_dir):
    import json

    origin = json.loads((session_data_dir / "origin.json").read_text(encoding="utf-8"))
    assert set(origin) == {"hostname", "app_version", "schema_version", "written_at"}
    assert origin["app_version"] == "0.1.0" and origin["schema_version"] == 1
