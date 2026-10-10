# 데이터 디렉터리 러너 잠금(WP5a R2) — 같은 데이터 디렉터리에 프로세스가 둘 떠도 러너·재기동 복구는 잠금을 쥔 하나만 돈다
"""HEAXHub 는 헬스가 2초 안에 안 오면 같은 인스턴스 안에 서버를 하나 더 띄운다(같은 데이터 디렉터리·같은 포트). 둘째가
재기동 복구를 돌리면 첫째가 돌리는 패널을 error('restart') 로 닫고 좌석을 되돌려 같은 좌석이 두 번 돈다.
단위 시험은 잠금과 러너를, 마지막 시험은 실제 uvicorn 프로세스 셋을 같은 디렉터리로 띄워 운영 모양(같은 포트 포함)을 본다.
하네스는 띄운 PID 만 내린다(포트·이름으로 내리지 않는다).
"""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from app import planner, runner
from app.risk_store import RiskStore
from tests import factories
from tests.conftest import BACKEND_DIR


def _wait(predicate, timeout: float, what: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(f"{timeout}초 안에 {what} 가 오지 않았다")


def _running_panel(store) -> tuple[str, str]:
    """생산자 경유 타깃에 편성기가 연 패널을 running 으로 둔다(첫째 프로세스가 돌리는 패널의 자리)."""
    project_id = factories.make_project(store)
    snapshot = factories.make_snapshot(store, project_id, factories.fixture_adapter_results(), label="DV1")
    target_key = factories.make_target(store, "snap", snapshot["snapshot_id"], agents=factories.agents())
    panel = factories.plan_panel(store, target_key, "C")
    planner.start_panel_seats(store, panel["id"])
    return target_key, panel["id"]


def _panel_status(store, panel_id: str) -> tuple[str, str | None]:
    row = store.query_one("SELECT status, error FROM rr_panels WHERE id = ?", (panel_id,))
    return row["status"], row["error"]


# ---------------------------------------------------------------- 잠금
def test_only_one_process_holds_the_lock_and_a_loser_writes_nothing(tmp_path):
    from app.runlock import RunnerLock

    first, second = RunnerLock(tmp_path), RunnerLock(tmp_path)
    assert first.acquire() is True and first.held()
    written = (tmp_path / "runner.lock").read_text(encoding="utf-8")
    assert json.loads(written)["pid"] == os.getpid()

    assert second.acquire() is False and not second.held()
    assert second.holder()["boot_id"] == first.holder()["boot_id"]
    second.release()                                              # 못 쥔 쪽의 종료가 주인을 건드리지 않는다
    assert (tmp_path / "runner.lock").read_text(encoding="utf-8") == written

    first.release()
    assert (tmp_path / "runner.lock").exists()                    # 지우지 않는다 — 지우면 다음이 새 inode 를 잡는다
    assert second.acquire() is True and second.holder()["boot_id"] != json.loads(written)["boot_id"]
    second.release()


def test_a_runner_without_the_lock_neither_recovers_nor_loops_until_it_gets_it(risk_store, tmp_path, monkeypatch):
    from app import runlock

    monkeypatch.setattr(runlock, "RETRY_S", 0.2)
    target_key, panel_id = _running_panel(risk_store)
    other = runlock.RunnerLock(tmp_path)
    assert other.acquire()
    rr = runner.RiskRunner(risk_store, None, engine=None, lock=runlock.RunnerLock(tmp_path))
    rr.start()
    try:
        time.sleep(0.6)
        assert _panel_status(risk_store, panel_id) == ("running", None)
        assert not any(t["alive"] for t in rr.status()["threads"])
        other.release()                                           # 첫째가 죽었다 — 커널이 잠금을 푼다
        _wait(lambda: _panel_status(risk_store, panel_id)[0] == "error", 5, "이어받은 러너의 재기동 복구")
        assert _panel_status(risk_store, panel_id) == ("error", runner.RESTART_CODE)
        _wait(lambda: all(t["alive"] for t in rr.status()["threads"]), 5, "러너 루프")
    finally:
        rr.stop()
    assert rr.lock.held() is False


def test_health_says_when_another_process_holds_the_runner_lock(client, tmp_path, monkeypatch):
    from app import main
    from app.runlock import RunnerLock

    other, mine = RunnerLock(tmp_path), RunnerLock(tmp_path)
    assert other.acquire() and not mine.acquire()
    monkeypatch.setattr(main.app.state, "runner_lock", mine)
    assert "runner_lock_held" in client.get("/api/health").json().get("warnings", [])
    other.release()
    assert mine.acquire()
    assert "runner_lock_held" not in client.get("/api/health").json().get("warnings", [])
    mine.release()


# ---------------------------------------------------------------- 실제 프로세스 — 운영 모양
def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serve(data_dir: Path, port: int, log_path: Path) -> subprocess.Popen:
    dead = f"http://127.0.0.1:{_free_port()}"                     # 아무것도 듣지 않는 주소 — 박스의 실 서비스에 닿지 않는다
    env = {**os.environ, "HWAXRISK_DATA_DIR": str(data_dir), "HWAXRISK_RUNNER_LOCK_RETRY_S": "0.5",
           "HWAXRISK_PORTAL_BASE": dead, "HWAXRISK_HEAX_BASE": dead, "HWAXRISK_GATEWAY_MCP": dead + "/mcp",
           "HWAXRISK_AIDH_BASE": dead, "HWAXRISK_PAT_REVOCATION_POLL_S": "0"}
    env.pop("HEAX_DATA_DIR", None)
    with open(log_path, "ab") as log:
        return subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(BACKEND_DIR), env=env, stdout=log, stderr=subprocess.STDOUT)


def _health(port: int) -> dict | None:
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1.0)
    except httpx.HTTPError:
        return None
    return r.json() if r.status_code == 200 else None


def _stop(proc: subprocess.Popen, sig: int = signal.SIGTERM) -> None:
    if proc.poll() is None:
        proc.send_signal(sig)
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(5)


def test_processes_on_one_data_dir_leave_the_holders_panel_alone(tmp_path):
    data_dir = tmp_path / "data"
    store = RiskStore(data_dir / "risk_review.db")
    store.open()
    store.migrate()
    procs: list[subprocess.Popen] = []
    try:
        port_a, port_b = _free_port(), _free_port()
        first = _serve(data_dir, port_a, tmp_path / "first.log")
        procs.append(first)
        _wait(lambda: _health(port_a), 30, "첫째의 헬스")
        target_key, panel_id = _running_panel(store)               # 첫째가 돌리는 패널의 자리
        held = (data_dir / "runner.lock").read_text(encoding="utf-8")
        assert json.loads(held)["pid"] == first.pid

        # 허브가 다시 띄우는 둘째는 같은 포트를 받는다 — 기동(잠금 시도·이행·러너)을 다 돈 뒤 포트를 못 묶어 죽는다.
        same_port = _serve(data_dir, port_a, tmp_path / "same-port.log")
        procs.append(same_port)
        assert same_port.wait(30) != 0
        assert (data_dir / "runner.lock").read_text(encoding="utf-8") == held
        assert _panel_status(store, panel_id) == ("running", None)

        # 다른 포트의 둘째는 산다 — REST·MCP 만 열고 러너·복구는 돌지 않는다.
        second = _serve(data_dir, port_b, tmp_path / "second.log")
        procs.append(second)
        health = _wait(lambda: _health(port_b), 30, "둘째의 헬스")
        assert "runner_lock_held" in health.get("warnings", [])
        time.sleep(1.5)                                            # 재시도 간격(0.5초)의 세 배
        assert _panel_status(store, panel_id) == ("running", None)

        # 첫째가 죽으면(정리 없이) 커널이 잠금을 풀고 둘째가 이어받아 복구를 돈다.
        _stop(first, signal.SIGKILL)
        _wait(lambda: _panel_status(store, panel_id)[0] == "error", 15, "둘째의 재기동 복구")
        assert _panel_status(store, panel_id) == ("error", runner.RESTART_CODE)
        assert "runner_lock_held" not in (_health(port_b) or {}).get("warnings", [])
        assert json.loads((data_dir / "runner.lock").read_text(encoding="utf-8"))["pid"] == second.pid
    finally:
        for proc in procs:
            _stop(proc)
        store.close()
