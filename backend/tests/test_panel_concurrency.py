# 패널 잡 동시 실행 — 동시 2 잡이 제 패널을 둘까지 함께 돌린다(섞여 흐르는 두 스트림 · 하나 실패 · 도중 멈춤/취소 · 재기동 복구 · 429 · 하루 상한 · 수확 체감 · Claude 1 · 불변식)
"""사용자 결정 10-31 — 잡 만들기 칸 '동시 실행 ≤2'(POST /targets/{key}/jobs 의 concurrency)는 저장만 되고 러너가 읽지 않았다(RD-5). 이제
러너가 잡마다 제 자리 수(`runner.job_slots`)까지 패널을 함께 돌린다. 결정과 까닭은 리포 context-notes 'CC-1' 부터다.

- 전역 자리(HWAXRISK_CONCURRENCY — 러너 세마포어)는 늘지 않는다. 잡 하나가 그 자리를 둘까지 쓸 뿐이고, 둘째 자리는 첫 패널을 기다리는
  잡이 없을 때만이다(CC-1 · CC-3).
- 편성은 틱 스레드에서 한 줄로(CC-4), 잡의 도는 패널은 러너가 센다(패널 행에 잡 열이 없다 — CC-2).
- 잡이 running 을 떠나면 그 잡의 도는 패널이 다 닫힌다 — 사람의 멈춤 · 취소 · 보류 · 실패. 취소는 패널이 다 닫힌 뒤 cancelled(CC-6).
- 형제가 도는 동안의 하루 상한 · 수확 체감 · 둘째 패널의 엔진 자리 없음은 잡을 멈추지 않고 둘째 자리만 막는다(CC-7 · CC-8).

시험의 엔진은 진짜 엔진 클라이언트(PortalPanelEngine)를 가짜 포털(httpx.MockTransport)에 물린 것이다 — 패널마다 스트림 하나를 시험이
줄 단위로 흘린다(`_Stream`). 러너도 진짜(RiskRunner)이고 틱은 손으로 부른다(루프 스레드는 띄우지 않는다). narrative · registry 는 실모듈이다.

  실행:  .venv/bin/python -m pytest tests/test_panel_concurrency.py
"""
from __future__ import annotations

import dataclasses
import json
import queue
import threading
import time

import httpx
import pytest

from app import common, config, engine_client, identity, planner, routes, runner
from tests import factories
from tests.test_runner_panel import FakePanelEngine, fake_narrative, fake_registry

OWNER = "owner@example.com"
# ECAD 밖 아홉 영역 · 영역마다 두 명 — Tier A(영역 대표)는 9석이라 패널 둘(5석 + 4석)이다.
DOMAINS = ("xd", "sim", "cam", "rel", "disp", "mech", "sh", "std", "material")
DECISION = "판정 본문.\n```json\n{\"schema\": \"risk_spec\"}\n```"
WAIT_S = 30.0


# ---------------------------------------------------------------- 원장
def _seed(store, target_key: str = "diff:d1", project_id: str = "p1") -> str:
    now = common.now_epoch()
    store.execute("INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at) VALUES (?, ?, ?, '동시 과제', ?, ?)",
                  (project_id, OWNER, f"PRJ-{project_id}", now, now))
    diff_id = f"d-{project_id}"
    store.execute(
        "INSERT INTO rr_diffs(id, target_project_id, base_project_id, target_snapshot_id, base_snapshot_id, owner_sub,"
        " diff_version, diff_json, summary_text, created_at) VALUES (?, ?, 'p0', ?, ?, ?, '1.0', '{}', ?, ?)",
        (diff_id, project_id, f"s1-{project_id}", f"s0-{project_id}", OWNER, "구조 3건·치수 2건이 바뀌었다.", now))
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, external_sync_json,"
        " report_ids_json, level, created_at, updated_at) VALUES (?, ?, 'diff', ?, ?, 'h1', '{}', '[]', 'C0', ?, ?)",
        (target_key, OWNER, diff_id, project_id, now, now))
    planner.freeze_roster(store, target_key, OWNER, [
        {"key": f"{dom}-a{i:03d}", "domain": dom, "relevance": (2 - i) / 100.0} for dom in DOMAINS for i in range(2)])
    if store.get_credential(OWNER) is None:
        store.upsert_credential(OWNER, identity.encrypt_pat("pat-secret").decode("ascii"), "sub-1", OWNER, "[]",
                                common.now_epoch() + 30 * 86400)
    return target_key


def _cfg(tmp_path, **kw):
    return dataclasses.replace(config.settings, data_dir=tmp_path, risk_concurrency=2, **kw)


def _job(store, job_id: str) -> dict:
    return dict(store.query_one("SELECT state, pause_reason, state_by, hold_code, error, concurrency, panels_done,"
                                " progress_json FROM rr_jobs WHERE id = ?", (job_id,)))


def _panels(store, target_key: str) -> list[dict]:
    rows = store.query("SELECT id, panel_no, status, error, retry, conv_id, seats_json FROM rr_panels WHERE target_key = ?"
                       " ORDER BY panel_no", (target_key,))
    return [{**dict(r), "seats": [s["key"] for s in json.loads(r["seats_json"])]} for r in rows]


def _coverage(store, target_key: str) -> dict[str, tuple[str, int]]:
    return {r["agent_key"]: (r["status"], int(r["retry"] or 0)) for r in store.query(
        "SELECT agent_key, status, retry FROM rr_coverage WHERE target_key = ?", (target_key,))}


def _tier_a(store, target_key: str) -> set[str]:
    return {r["agent_key"] for r in store.query(
        "SELECT agent_key FROM rr_roster WHERE target_key = ? AND rank_in_domain = 1", (target_key,))}


def _until(check, what: str, timeout: float = WAIT_S) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.01)
    raise AssertionError(f"{timeout}초 안에 오지 않았다 — {what}")


def _ident(email: str = OWNER):
    return dataclasses.replace(factories.ident(email), source="bearer")


# ---------------------------------------------------------------- 가짜 포털 · 스트림
def _frame(name: str, data: dict) -> bytes:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


PING = _frame("ping", {"idle_s": 15})


class _Stream(httpx.SyncByteStream):
    """패널 하나의 심의 스트림 — 시험이 줄을 하나씩 흘린다. 그 사이에는 ping 만 흐른다(러너는 프레임마다 멈춤을 묻는다). `quiet` 를 세우면
    ping 도 멎는다(그동안 러너는 그 패널에서 멈춤을 듣지 못한다 — 닫히는 데 시간이 걸리는 패널). 닫히면(러너가 놓으면) 그친다."""

    def __init__(self, body: dict) -> None:
        self.body = body
        self.keys = [p["key"] for p in body["delib_opts"]["personas"]]
        self.lines: queue.Queue = queue.Queue()
        self.opened = threading.Event()
        self.closed = threading.Event()
        self.ended = threading.Event()
        self.quiet = threading.Event()

    def __iter__(self):
        self.opened.set()
        deadline = time.monotonic() + 120              # 시험의 안전판 — 잊힌 스트림도 끝난다
        try:
            while not self.closed.is_set() and time.monotonic() < deadline:
                try:
                    item = self.lines.get(timeout=0.02)
                except queue.Empty:
                    if not self.quiet.is_set():
                        yield PING
                    continue
                if item is None:
                    return
                yield item
        finally:
            self.ended.set()

    def close(self) -> None:
        self.closed.set()

    def say(self, name: str, data: dict) -> None:
        self.lines.put(_frame(name, data))

    def step(self, text: str) -> None:
        self.say("status", {"step": text})

    def finish(self) -> None:
        """좌석마다 조회 한 번 · 세 라운드 발언 · 결정문 — 엔진이 실제로 내는 순서다."""
        for key in self.keys:
            self.say("status", {"step": f"{key} 조회: list_interfaces", "tool": "list_interfaces"})
            self.say("delib", {"kind": "evidence", "source": f"{key} · list_interfaces", "text": "…", "included": True})
        for rnd in (1, 2, 3):
            for key in self.keys:
                self.say("delib", {"kind": "turn", "round": rnd, "persona": key, "say": f"{key} {rnd}라운드", "stance": "agree"})
        self.say("delib", {"kind": "decision", "text": DECISION})
        self.say("done", {})
        self.lines.put(None)

    def fail(self, code: str, message: str = "엔진이 실패했다(시험)") -> None:
        self.say("error", {"code": code, "message": message})
        self.say("done", {})
        self.lines.put(None)


class _Portal:
    """가짜 포털 — 대화 생성 · 에이전트 서버 /health · /agent/chat(부를 때마다 새 스트림)."""

    def __init__(self) -> None:
        self.streams: list[_Stream] = []
        self.conversations = 0
        self.cond = threading.Condition()

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == engine_client.CONVERSATIONS_PATH:
            with self.cond:
                self.conversations += 1
                return httpx.Response(200, json={"id": f"conv-{self.conversations}"})
        if request.url.path != engine_client.CHAT_PATH:
            return httpx.Response(200, json={"model": "glm-fake"})          # 에이전트 서버 /health
        stream = _Stream(json.loads(request.content.decode()))
        with self.cond:
            self.streams.append(stream)
            self.cond.notify_all()
        return httpx.Response(200, stream=stream, headers={"content-type": "text/event-stream"})

    def stream(self, n: int) -> _Stream:
        """n 번째로 열린 스트림(1부터) — 열릴 때까지 기다린다."""
        with self.cond:
            assert self.cond.wait_for(lambda: len(self.streams) >= n, timeout=WAIT_S), f"{n} 번째 스트림이 열리지 않았다"
            stream = self.streams[n - 1]
        assert stream.opened.wait(WAIT_S), f"{n} 번째 스트림을 러너가 읽지 않는다"
        return stream

    def close_all(self) -> None:
        with self.cond:
            for stream in self.streams:
                stream.closed.set()


class _Rig:
    def __init__(self, store, cfg, portal: _Portal, rr: runner.RiskRunner) -> None:
        self.store, self.cfg, self.portal, self.rr = store, cfg, portal, rr

    def tick(self) -> None:
        self.rr._panel_tick()

    def settle(self, job_id: str, n: int) -> None:
        """그 잡으로 도는 워커가 n 개가 될 때까지(워커가 끝나야 러너가 그 패널을 놓는다)."""
        _until(lambda: len(self.rr._running_of(job_id)) == n, f"잡의 워커 {n} 개")

    def free_slots(self) -> int:
        held = 0
        while self.rr._sem.acquire(blocking=False):
            held += 1
        for _ in range(held):
            self.rr._sem.release()
        return held


@pytest.fixture
def rig(risk_store, tmp_path, monkeypatch):
    """진짜 러너 + 진짜 엔진 클라이언트 + 가짜 포털(전역 자리 2). 러너는 프레임마다 잡 행을 읽고(취소 · 멈춤을 바로 듣는다) 신호도 프레임마다
    적는다(패널별 칸을 견줄 수 있게)."""
    monkeypatch.setattr(runner, "STOP_POLL_INTERVAL_S", 0)
    monkeypatch.setattr(runner, "PROGRESS_WRITE_INTERVAL_S", 0)
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    cfg = _cfg(tmp_path)
    portal = _Portal()
    engine = engine_client.PortalPanelEngine(risk_store, cfg, transport=httpx.MockTransport(portal.handler))
    rr = runner.RiskRunner(risk_store, cfg, engine)
    try:
        yield _Rig(risk_store, cfg, portal, rr)
    finally:
        portal.close_all()
        rr.stop()


def _panel_job(store, target_key: str, cfg, *, concurrency: int = 2, tier: str = "A") -> str:
    return runner.create_job(store, target_key, tier, owner_sub=OWNER, settings=cfg, concurrency=concurrency)["job_id"]


# ---------------------------------------------------------------- 두 패널이 함께 돈다
def test_a_concurrency_two_job_runs_two_of_its_panels_at_once_and_their_streams_interleave(rig, monkeypatch):
    """동시 2 잡은 제 패널 둘을 함께 돌린다 — 좌석이 겹치지 않고(9석 = 5 + 4), 두 스트림이 섞여 흘러도 신호 · 결과가 제 패널에 앉고,
    늦게 시작한 패널이 먼저 끝나도 셈(panels_done · 좌석 · 불변식)이 맞는다. 남은 좌석이 없어도 형제가 도는 동안은 잡을 끝내지 않는다."""
    store = rig.store
    target_key = _seed(store)
    job_id = _panel_job(store, target_key, rig.cfg)
    assert _job(store, job_id)["concurrency"] == 2

    rig.tick()
    first = rig.portal.stream(1)
    rig.tick()
    second = rig.portal.stream(2)
    rig.tick()                                             # 전역 자리 둘이 다 찼다 — 셋째는 없다
    assert len(rig.portal.streams) == 2 and rig.free_slots() == 0
    panels = _panels(store, target_key)
    assert [(p["panel_no"], p["status"]) for p in panels] == [(1, "running"), (2, "running")]
    seats = [set(p["seats"]) for p in panels]
    assert not seats[0] & seats[1] and seats[0] | seats[1] == _tier_a(store, target_key) and len(seats[0]) == 5
    assert {k: v for k, v in _coverage(store, target_key).items() if k in seats[0] | seats[1]} == {
        k: ("running", 0) for k in seats[0] | seats[1]}
    assert planner.check_invariants(store, target_key) == []
    # 엔진에 간 좌석도 패널마다 제 것이다(반대석은 엔진이 더한다).
    assert set(first.keys) == seats[0] and set(second.keys) == seats[1]

    # 두 스트림이 섞여 흐른다 — 신호는 패널마다 제 칸에 선다.
    first.step("1라운드 · 첫 패널")
    second.step("1라운드 · 둘째 패널")
    first.step("2라운드 · 첫 패널")

    def steps() -> dict:
        board = routes.coverage_payload(target_key)["job"]
        return {s["panel_no"]: s["last_step"] for s in board["signals"]}

    _until(lambda: steps() == {1: "2라운드 · 첫 패널", 2: "1라운드 · 둘째 패널"}, "패널마다의 신호")
    board = routes.coverage_payload(target_key)["job"]
    assert [s["panel_no"] for s in board["signals"]] == [1, 2]
    assert board["signal"] is not None and board["signal"]["panel_id"] in {p["id"] for p in panels}
    assert set(json.loads(_job(store, job_id)["progress_json"])[runner.PROGRESS_PANELS_KEY]) == {p["id"] for p in panels}

    # 늦게 시작한 패널이 먼저 끝난다 — 첫 패널은 그대로 돈다. 첫 패널은 잠시 조용하다(맨 위 신호는 끝난 둘째 패널의 것으로 남는다).
    first.quiet.set()
    time.sleep(0.2)
    second.finish()
    rig.settle(job_id, 1)
    assert [p["status"] for p in _panels(store, target_key)] == ["running", "done"]
    assert _job(store, job_id)["panels_done"] == 1 and not first.closed.is_set()
    board = routes.coverage_payload(target_key)["job"]
    assert json.loads(_job(store, job_id)["progress_json"])["panel_id"] == panels[1]["id"]      # 맨 위 칸은 닫힌 패널의 것
    assert [s["panel_no"] for s in board["signals"]] == [1] and board["signal"]["panel_no"] == 1  # signal 은 도는 패널로 선다
    # 남은 좌석이 없지만 형제가 돈다 — 둘째 자리는 편성할 것이 없어 집지 않고(틱마다 잡 행을 다시 쓰지 않는다) 잡을 끝내지 않는다.
    assert runner.claim_next_job(store, rig.cfg, running=rig.rr._running_of) is None
    rig.tick()
    assert len(rig.portal.streams) == 2 and _job(store, job_id)["state"] == "running"
    # 집기가 본 남은 좌석이 편성 전에 사라져도(사람의 좌석 넘기기 · MCP 편성과의 경합) 형제가 돌면 잡을 끝내지 않는다.
    with monkeypatch.context() as race:
        race.setattr(planner, "has_pending", lambda *a, **k: True)
        rig.tick()
    assert len(rig.portal.streams) == 2 and _job(store, job_id)["state"] == "running"

    first.quiet.clear()
    first.finish()
    rig.settle(job_id, 0)
    rig.tick()                                             # 첫 자리 — 남은 좌석이 없고 도는 형제도 없다: 잡을 끝낸다
    job = _job(store, job_id)
    assert (job["state"], job["panels_done"]) == ("completed", 2)
    assert json.loads(job["progress_json"])[runner.PROGRESS_PANELS_KEY] == {}
    assert [(p["panel_no"], p["status"]) for p in _panels(store, target_key)] == [(1, "done"), (2, "done")]
    assert {v for k, v in _coverage(store, target_key).items() if k in seats[0] | seats[1]} == {("done", 0)}
    # 의견은 패널마다 제 좌석 + 반대석이다(남의 패널 이름으로 앉지 않았다).
    for panel, keys in zip(panels, seats):
        rows = store.query("SELECT agent_key FROM rr_seat_opinions WHERE panel_id = ?", (panel["id"],))
        assert {r["agent_key"] for r in rows} - {planner.ADVERSARY_KEY} == keys
    assert planner.check_invariants(store, target_key) == []


def test_concurrency_one_keeps_one_panel_per_target(rig):
    """동시 1(기본) 잡은 종전 그대로다 — 대상에 도는 패널이 있으면 둘째 틱은 아무것도 집지 않고, 잡 행에 패널별 칸이 없다."""
    store = rig.store
    target_key = _seed(store)
    job_id = _panel_job(store, target_key, rig.cfg, concurrency=1)
    rig.tick()
    first = rig.portal.stream(1)
    first.step("1라운드")
    _until(lambda: json.loads(_job(store, job_id)["progress_json"] or "{}").get("last_step") == "1라운드", "신호")
    rig.tick()
    assert len(rig.portal.streams) == 1 and rig.free_slots() == 1
    assert runner.PROGRESS_PANELS_KEY not in json.loads(_job(store, job_id)["progress_json"])
    first.finish()
    rig.settle(job_id, 0)
    assert runner.PROGRESS_PANELS_KEY not in json.loads(_job(store, job_id)["progress_json"])


def test_one_failing_panel_leaves_its_sibling_running_and_its_seats_go_to_a_new_panel(rig):
    """한 패널이 엔진 실패로 닫혀도(좌석 차감 — 종전 실패 그대로) 형제는 그대로 돌고, 돌아온 좌석은 다음 틱의 둘째 자리가 새 패널로 돈다."""
    store = rig.store
    target_key = _seed(store)
    job_id = _panel_job(store, target_key, rig.cfg)
    rig.tick()
    first = rig.portal.stream(1)
    rig.tick()
    second = rig.portal.stream(2)
    failed_seats = set(second.keys)

    second.fail("llm_error")
    rig.settle(job_id, 1)
    panels = _panels(store, target_key)
    assert [(p["status"], p["retry"]) for p in panels] == [("running", 0), ("error", 1)]
    assert panels[1]["error"].startswith("engine_error: llm_error")
    assert {_coverage(store, target_key)[k] for k in failed_seats} == {("pending", 1)}
    assert _job(store, job_id)["state"] == "running" and not first.closed.is_set()

    rig.tick()                                             # 둘째 자리 — 돌아온 좌석으로 새 패널
    third = rig.portal.stream(3)
    assert set(third.keys) == failed_seats
    assert [p["panel_no"] for p in _panels(store, target_key)] == [1, 2, 3]
    first.finish()
    third.finish()
    rig.settle(job_id, 0)
    rig.tick()
    job = _job(store, job_id)
    assert (job["state"], job["panels_done"]) == ("completed", 2)
    assert runner._error_streak(store, target_key) == 0


@pytest.mark.parametrize("action", ["pause", "cancel"])
def test_a_pause_or_cancel_closes_both_running_panels_with_one_audit_row(rig, action):
    """사람의 멈춤 · 취소는 그 잡의 도는 패널 둘을 다 닫는다(좌석 차감 없음). 취소는 두 패널이 다 닫힌 뒤에야 cancelled 다 — 늦게 닫히는
    패널이 있는 동안은 cancelling 이다. 감사 행은 사람의 조작 하나에 한 행이다(패널이 닫히며 더 쓰지 않는다)."""
    store = rig.store
    target_key = _seed(store)
    job_id = _panel_job(store, target_key, rig.cfg)
    rig.tick()
    first = rig.portal.stream(1)
    rig.tick()
    second = rig.portal.stream(2)
    second.quiet.set()                                     # 이 패널은 프레임이 오지 않아 멈춤을 아직 듣지 못한다

    out = routes.job_action(job_id, action, ident=_ident())
    assert out["state"] == ("paused" if action == "pause" else "cancelling")
    assert first.closed.wait(WAIT_S)
    rig.settle(job_id, 1)
    rig.tick()
    assert _job(store, job_id)["state"] == ("paused" if action == "pause" else "cancelling")   # 늦은 패널이 아직 돈다
    assert len(rig.portal.streams) == 2

    second.quiet.clear()
    assert second.closed.wait(WAIT_S)
    rig.settle(job_id, 0)
    rig.tick()
    assert _job(store, job_id)["state"] == ("paused" if action == "pause" else "cancelled")
    said = "일시정지했다" if action == "pause" else "취소했다"
    for panel in _panels(store, target_key):
        assert panel["status"] == "error" and panel["retry"] == 0
        assert panel["error"].startswith(f"cancelled: 사용자가 잡을 {said} — 진행 중 패널을 닫았다"), panel["error"]
    assert set(_coverage(store, target_key).values()) == {("pending", 0)}
    rows = store.query("SELECT action FROM rr_audit WHERE scope = 'job' AND subject_id = ?", (job_id,))
    assert [r["action"] for r in rows] == [f"job.{action}"]
    assert runner._error_streak(store, target_key) == 0

    if action == "pause":
        # 재개하면 두 자리가 다시 찬다(좌석은 차감 없이 그대로 다시 돈다).
        assert routes.job_action(job_id, "resume", ident=_ident())["state"] == "queued"
        rig.tick()
        rig.portal.stream(3)
        rig.tick()
        rig.portal.stream(4)
        assert [p["status"] for p in _panels(store, target_key)] == ["error", "error", "running", "running"]


def test_a_sibling_closed_by_another_panels_code_pause_says_why(rig):
    """한 패널의 의장 실패(chair_failed)가 잡을 멈추면 형제 패널도 닫힌다 — 그 패널의 글은 '사용자가 …' 가 아니라 잡이 멈춘 까닭이다."""
    store = rig.store
    target_key = _seed(store)
    job_id = _panel_job(store, target_key, rig.cfg)
    rig.tick()
    first = rig.portal.stream(1)
    rig.tick()
    second = rig.portal.stream(2)

    second.fail("chair_failed", "의장이 결정문을 내지 못했다")
    assert first.closed.wait(WAIT_S)
    rig.settle(job_id, 0)
    job = _job(store, job_id)
    assert (job["state"], job["state_by"]) == ("paused", "code:chair_failed")
    panels = _panels(store, target_key)
    assert panels[1]["error"].startswith("chair_failed: 의장이 결정문을 내지 못했다")
    assert panels[0]["error"].startswith("cancelled: 잡이 멈췄다(chair_failed) — 진행 중 패널을 닫았다"), panels[0]["error"]
    assert set(_coverage(store, target_key).values()) == {("pending", 0)}
    assert store.query("SELECT action FROM rr_audit WHERE scope = 'job' AND subject_id = ?", (job_id,)) == []


def test_a_job_that_fails_on_engine_errors_closes_its_running_sibling(rig):
    """둘째 자리의 패널이 엔진 실패로 셋 잇달아 닫히면(연속 실패 — 종전 규칙) 잡이 failed 다. 그때 도는 형제도 닫힌다(좌석 차감 없음) —
    실패로 끝난 잡 밑에서 몇 시간 더 돌지 않는다. 그 패널의 글은 잡이 실패로 끝난 까닭이다."""
    store = rig.store
    target_key = _seed(store)
    job_id = _panel_job(store, target_key, rig.cfg)
    rig.tick()
    first = rig.portal.stream(1)
    for n in (2, 3, 4):
        rig.tick()
        rig.portal.stream(n).fail("llm_error")
        rig.settle(job_id, 1 if n < 4 else 0)
    assert first.closed.wait(WAIT_S)
    rig.settle(job_id, 0)
    job = _job(store, job_id)
    assert (job["state"], job["error"]) == ("failed", "engine_fail_streak")
    panels = _panels(store, target_key)
    assert [p["status"] for p in panels] == ["error"] * 4
    assert panels[0]["retry"] == 0 and panels[0]["error"].startswith(
        "cancelled: 잡이 실패로 끝났다(engine_fail_streak) — 진행 중 패널을 닫았다"), panels[0]["error"]
    assert {_coverage(store, target_key)[key] for key in panels[0]["seats"]} == {("pending", 0)}


# ---------------------------------------------------------------- 집기 · 편성(러너 없이 — 러너가 넘기는 도는 패널을 손으로 준다)
def _claim(store, cfg, running: dict[str, set[str]] | None = None):
    return runner.claim_next_job(store, cfg, running=lambda job_id: (running or {}).get(job_id, set()))


def _seat_two(store, cfg, target_key: str, job_id: str) -> tuple[dict, dict, dict]:
    """동시 2 잡의 두 자리를 러너처럼 집고 편성한다 — (잡, 첫 패널, 둘째 패널). 두 패널은 running 이다(엔진은 부르지 않았다)."""
    job = _claim(store, cfg)
    first, _ = runner.plan_job_panel(store, cfg, job)
    again = _claim(store, cfg, {job_id: {first["id"]}})
    assert again is not None and again["id"] == job_id
    second, _ = runner.plan_job_panel(store, cfg, again, siblings=True)
    return job, first, second


class _Killed(BaseException):
    """SIGKILL 흉내 — 러너의 except Exception 을 지나 그대로 올라간다(닫는 코드는 돌지 않는다)."""


class _DiesMidStream(FakePanelEngine):
    def run(self, delib_opts, *, owner_sub=None, on_conversation=None):
        if on_conversation is not None:
            on_conversation(f"conv-killed-{len(self.calls) + 1}")
        self.calls.append(dict(delib_opts))
        raise _Killed()


def test_restart_recovery_closes_both_running_panels_and_pauses_the_job_once(risk_store, tmp_path):
    """두 패널이 도는 중에 앱이 죽었다 — 기동 복구가 둘 다 restart 로 닫고(좌석 차감 없음 · 대화는 패널에 남는다) 잡을 한 번 멈춘다.
    재개하면 새 러너가 두 자리를 다시 채운다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _panel_job(risk_store, target_key, cfg)
    job, first, second = _seat_two(risk_store, cfg, target_key, job_id)
    engine = _DiesMidStream()
    for panel in (first, second):
        with pytest.raises(_Killed):
            runner.run_panel(risk_store, cfg, engine, job, panel=panel)
    assert [p["status"] for p in _panels(risk_store, target_key)] == ["running", "running"]

    assert runner.recover_running_panels(risk_store) == {"recovered": 2, "paused": 1}
    panels = _panels(risk_store, target_key)
    assert [(p["status"], p["retry"], p["conv_id"]) for p in panels] == [
        ("error", 0, "conv-killed-1"), ("error", 0, "conv-killed-2")]
    assert all(p["error"].startswith("restart: ") for p in panels)
    assert set(_coverage(risk_store, target_key).values()) == {("pending", 0)}
    row = _job(risk_store, job_id)
    assert (row["state"], row["state_by"]) == ("paused", "code:restart")

    runner.resume_job(risk_store, job_id, by=OWNER)
    _job2, third, fourth = _seat_two(risk_store, cfg, target_key, job_id)
    assert {s["key"] for s in third["seats"]} | {s["key"] for s in fourth["seats"]} == _tier_a(risk_store, target_key)


class _Clock:
    """러너의 `time` 대역 — sleep 은 자지 않고 monotonic 만 민다."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def __getattr__(self, name: str):
        return getattr(time, name)


class _NoSlot:
    def run(self, delib_opts, *, owner_sub=None):
        raise runner.EngineBusy("포털 agent_semaphore 초과(429)")


def test_an_engine_slot_that_never_comes_for_the_second_panel_does_not_pause_the_job(risk_store, tmp_path, monkeypatch):
    """둘째 패널이 엔진 자리(포털 429)를 예산 내내 못 얻었다 — 첫 패널이 돌고 있으니 잡을 멈추지 않는다(멈추면 잘 도는 첫 패널까지 닫힌다).
    둘째 패널만 시작 못 한 것으로 닫고(좌석 차감 없음), 그 대상의 둘째 자리는 예산 동안 · 그때 돌던 첫 패널이 도는 동안 쉰다(곧바로 또 한
    시간을 기다리지 않는다)."""
    monkeypatch.setattr(runner, "time", _Clock())
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path, risk_engine_busy_wait_s=30, risk_engine_busy_max_wait_s=90)
    # Tier C(전원 18석) — 패널 셋을 앉혀도 좌석이 남는다(끝에서 둘째 자리를 다시 묻는 것이 남은 좌석에 막히지 않게).
    job_id = runner.create_job(risk_store, target_key, "C", owner_sub=OWNER, settings=cfg, concurrency=2, consent=True)["job_id"]
    job = runner.claim_next_job(risk_store, cfg)
    first = planner.plan_next_panel(risk_store, target_key, "C", settings=cfg)       # 첫 패널이 돈다(엔진은 부르지 않았다)
    planner.start_panel_seats(risk_store, first["id"])

    out = runner.run_panel(risk_store, cfg, _NoSlot(), job)                          # 둘째 패널 — 자리가 끝내 안 난다
    row = _job(risk_store, job_id)
    assert (row["state"], row["state_by"]) == ("running", None), "형제가 도는데 잡을 멈췄다 — 그 패널까지 닫힌다"
    assert out["status"] == "error" and out["error"].startswith("engine_busy: ") and \
        out["error"].endswith(runner.ENGINE_BUSY_SIBLING_NOTE), out
    assert [(p["status"], p["retry"]) for p in _panels(risk_store, target_key)] == [("running", 0), ("error", 0)]
    second = _panels(risk_store, target_key)[1]
    assert {_coverage(risk_store, target_key)[key] for key in second["seats"]} == {("pending", 0)}

    assert _claim(risk_store, cfg, {job_id: {first["id"]}}) is None          # 둘째 자리는 예산 동안 쉰다
    assert _job(risk_store, job_id)["state"] == "running"
    start = common.now_epoch()
    clock = {"now": start + 10}
    previous = common.set_clock(lambda: clock["now"])
    try:
        # 그때 돌던 첫 패널이 예산 안에 끝나고 새 패널이 섰다 — 예산이 지나기 전에는 둘째 자리를 다시 묻지 않는다.
        risk_store.execute("UPDATE rr_panels SET status = 'done' WHERE id = ?", (first["id"],))
        job = _claim(risk_store, cfg)
        assert job["id"] == job_id
        third, _ = runner.plan_job_panel(risk_store, cfg, job)
        assert _claim(risk_store, cfg, {job_id: {third["id"]}}) is None
        clock["now"] = start + 91                                            # 예산(90초)이 지났다 — 다시 묻는다
        assert _claim(risk_store, cfg, {job_id: {third["id"]}})["id"] == job_id
    finally:
        common.set_clock(previous)


def test_a_concurrency_one_job_still_pauses_on_engine_busy_even_with_another_paths_panel_running(risk_store, tmp_path,
                                                                                                 monkeypatch):
    """동시 1 잡은 종전 그대로다 — 같은 대상에 다른 길(MCP 보충 회차)의 패널이 돌아도 그것을 형제로 읽지 않는다. 엔진 자리를 예산 내내 못
    얻으면 잡을 멈춘다(종전)."""
    monkeypatch.setattr(runner, "time", _Clock())
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path, risk_engine_busy_wait_s=30, risk_engine_busy_max_wait_s=90)
    job_id = _panel_job(risk_store, target_key, cfg, concurrency=1)
    job = runner.claim_next_job(risk_store, cfg)
    mcp = planner.plan_next_panel(risk_store, target_key, "A", settings=cfg)          # 다른 길의 패널이 돈다
    planner.start_panel_seats(risk_store, mcp["id"])
    out = runner.run_panel(risk_store, cfg, _NoSlot(), job)
    assert out["error"].startswith("engine_busy: ") and runner.ENGINE_BUSY_SIBLING_NOTE not in out["error"]
    row = _job(risk_store, job_id)
    assert (row["state"], row["state_by"]) == ("paused", "code:engine_busy")


def test_a_box_that_does_not_wait_for_engine_slots_does_not_pile_up_second_panels(risk_store, tmp_path, monkeypatch):
    """대기 예산 0(자리를 기다리지 않는 박스) — 둘째 패널은 첫 429 에 닫히고, 그때 돌던 첫 패널이 도는 동안은 예산이 지나도 둘째 자리를 다시
    잡지 않는다(틱마다 패널 행이 쌓이지 않는다). 그 패널이 닫힌 뒤 새로 시작한 패널의 둘째 자리는 다시 묻는다."""
    monkeypatch.setattr(runner, "time", _Clock())
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path, risk_engine_busy_max_wait_s=0)
    job_id = runner.create_job(risk_store, target_key, "C", owner_sub=OWNER, settings=cfg, concurrency=2, consent=True)["job_id"]
    job, first, second = _seat_two(risk_store, cfg, target_key, job_id)
    out = runner.run_panel(risk_store, cfg, _NoSlot(), job, panel=second)
    assert out["error"].startswith("engine_busy: ") and _job(risk_store, job_id)["state"] == "running"
    later = common.now_epoch() + 600
    previous = common.set_clock(lambda: later)
    try:
        assert _claim(risk_store, cfg, {job_id: {first["id"]}}) is None              # 그때 돌던 첫 패널이 아직 돈다
        risk_store.execute("UPDATE rr_panels SET status = 'done' WHERE id = ?", (first["id"],))
        job = _claim(risk_store, cfg)
        third, _ = runner.plan_job_panel(risk_store, cfg, job)                       # 첫 패널이 닫힌 뒤 새로 시작한 패널
        assert _claim(risk_store, cfg, {job_id: {third["id"]}})["id"] == job_id
    finally:
        common.set_clock(previous)


def test_the_daily_cap_blocks_the_second_slot_without_pausing_the_running_panel(risk_store, tmp_path):
    """하루 상한에 닿았다 — 첫 패널이 도는 동안은 둘째 자리만 막고 잡을 멈추지 않는다(멈추면 그 패널이 닫힌다). 도는 패널이 없을 때의
    첫 자리가 종전대로 daily_cap 으로 멈춘다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path, risk_daily_panel_cap=1)
    job_id = _panel_job(risk_store, target_key, cfg)
    job = _claim(risk_store, cfg)
    first, _ = runner.plan_job_panel(risk_store, cfg, job)
    assert _claim(risk_store, cfg, {job_id: {first["id"]}}) is None
    assert (_job(risk_store, job_id)["state"], _job(risk_store, job_id)["pause_reason"]) == ("running", None)

    risk_store.execute("UPDATE rr_panels SET status = 'done' WHERE id = ?", (first["id"],))
    assert _claim(risk_store, cfg) is None
    row = _job(risk_store, job_id)
    assert (row["state"], row["pause_reason"]) == ("paused", "daily_cap")


def test_diminishing_returns_wait_for_the_running_sibling(risk_store, tmp_path):
    """수확 체감 — 첫 패널이 끝날 때 형제가 돌면 잡을 멈추지 않고(멈추면 형제가 닫힌다) 둘째 자리만 막는다. 마지막 형제가 끝날 때 멈춘다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    # Tier C(전원 18석) — 두 패널을 앉혀도 좌석이 남는다(둘째 자리를 막는 것이 남은 좌석이 아니라 수확 체감이게).
    job_id = runner.create_job(risk_store, target_key, "C", owner_sub=OWNER, settings=cfg, concurrency=2, consent=True)["job_id"]
    job, first, second = _seat_two(risk_store, cfg, target_key, job_id)
    assert planner.has_pending(risk_store, target_key, "C")
    now = common.now_epoch()
    for n in range(runner.DIMINISHING_WINDOW):
        risk_store.execute(
            "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, seats_json, status, quality_json, created_at)"
            " VALUES (?, ?, ?, ?, '[]', 'done', ?, ?)", (f"old-{n}", target_key, OWNER, 90 + n, '{"new_clusters": 0}', now))
    rec: dict = {}
    dull = {"narrative_mod": fake_narrative(rec), "registry_mod": fake_registry(rec, level="C1", new_clusters=0)}

    assert runner.run_panel(risk_store, cfg, FakePanelEngine(), job, panel=first, **dull)["status"] == "done"
    assert _job(risk_store, job_id)["state"] == "running"
    assert [p["status"] for p in _panels(risk_store, target_key) if not str(p["id"]).startswith("old-")] == ["done", "running"]
    assert _claim(risk_store, cfg, {job_id: {second["id"]}}) is None              # 둘째 자리는 막힌다

    assert runner.run_panel(risk_store, cfg, FakePanelEngine(), job, panel=second, **dull)["status"] == "done"
    row = _job(risk_store, job_id)
    assert (row["state"], row["pause_reason"]) == ("paused", "diminishing")


def test_a_resumed_job_whose_stopped_panel_is_still_closing_is_not_claimed(risk_store, tmp_path):
    """멈췄다 곧바로 재개한 잡 — 앞 패널이 아직 닫히는 중(러너가 그 패널을 놓기 전)이면 다시 집지 않는다. 다시 집으면 그 패널이 닫히며
    running 잡을 다시 멈춘다. 취소도 그 패널이 다 닫힌 뒤에 cancelled 다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _panel_job(risk_store, target_key, cfg)
    job = _claim(risk_store, cfg)
    first, _ = runner.plan_job_panel(risk_store, cfg, job)
    runner.pause_job(risk_store, job_id, by=OWNER)
    runner.resume_job(risk_store, job_id, by=OWNER)
    assert _claim(risk_store, cfg, {job_id: {first["id"]}}) is None
    assert _job(risk_store, job_id)["state"] == "queued"
    # 워커가 그 패널을 닫는다(멈춤을 들었다) — 잡은 queued 라 건드리지 않는다. 러너가 그 패널을 놓은 뒤에야 다시 집는다.
    runner._close_panel_stream_lost(risk_store, first, job, runner.EngineStreamLost("cancelled", "사용자가 잡을 일시정지했다"))
    assert _job(risk_store, job_id)["state"] == "queued"
    assert _claim(risk_store, cfg)["id"] == job_id

    runner.cancel_job(risk_store, job_id, by=OWNER)
    assert _claim(risk_store, cfg) is None and _job(risk_store, job_id)["state"] == "cancelled"   # 도는 패널이 없다 — 곧바로 마감

    other = _seed(risk_store, "diff:d2", "p2")
    later = _panel_job(risk_store, other, cfg)
    job = _claim(risk_store, cfg)
    assert job["id"] == later
    panel, _ = runner.plan_job_panel(risk_store, cfg, job)
    assert runner.cancel_job(risk_store, later, by=OWNER)["state"] == "cancelling"
    assert _claim(risk_store, cfg, {later: {panel["id"]}}) is None
    assert _job(risk_store, later)["state"] == "cancelling"                     # 그 잡의 패널이 아직 닫히는 중이다
    runner._close_panel_stream_lost(risk_store, panel, job, runner.EngineStreamLost("cancelled", "사용자가 잡을 취소했다"))
    assert _claim(risk_store, cfg) is None                                       # 러너가 그 패널을 놓았다
    assert _job(risk_store, later)["state"] == "cancelled"


def test_a_second_slot_waits_while_another_job_waits_for_its_first_panel(risk_store, tmp_path):
    """둘째 자리는 첫 패널을 기다리는 잡이 없을 때만이다 — 먼저 선 동시 2 잡이 있어도 다른 대상의 잡이 첫 자리를 먼저 받는다."""
    first_target = _seed(risk_store)
    other_target = _seed(risk_store, "diff:d2", "p2")
    cfg = _cfg(tmp_path)
    wide = _panel_job(risk_store, first_target, cfg)
    job = _claim(risk_store, cfg)
    assert job["id"] == wide
    panel, _ = runner.plan_job_panel(risk_store, cfg, job)
    narrow = _panel_job(risk_store, other_target, cfg, concurrency=1)
    taken = _claim(risk_store, cfg, {wide: {panel["id"]}})
    assert taken["id"] == narrow
    other, _ = runner.plan_job_panel(risk_store, cfg, taken)
    assert _claim(risk_store, cfg, {wide: {panel["id"]}, narrow: {other["id"]}})["id"] == wide


def test_another_jobs_running_panel_still_keeps_the_target_serial(risk_store, tmp_path):
    """대상 안에서 잡끼리는 직렬이다(종전) — 같은 대상의 다른 잡이 패널을 돌리면 동시 2 잡도 그 대상에서 패널을 집지 않는다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    older = _panel_job(risk_store, target_key, cfg, concurrency=1)
    job = _claim(risk_store, cfg)
    panel, _ = runner.plan_job_panel(risk_store, cfg, job)
    wide = _panel_job(risk_store, target_key, cfg, tier="B")
    assert _claim(risk_store, cfg, {older: {panel["id"]}}) is None
    assert _job(risk_store, wide)["state"] == "queued"


# ---------------------------------------------------------------- Claude 길 · 만들기
def test_a_claude_panel_job_runs_one_panel_at_a_time(risk_store, tmp_path, monkeypatch):
    """판단 LLM 이 Claude 인 패널 잡은 동시 1 이다 — 동시 2 를 청해도 1 로 저장하고 답에 까닭을 싣는다. 옛 행(2 로 저장된 Claude 잡)도 집기가
    둘째 자리를 주지 않는다."""
    from tests import test_external_llm_jobs as X
    from tests.test_claude_panel_jobs import PEER, _peer_pat

    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: "runner-panel-gateway-secret")
    target_key = _seed(risk_store)
    _peer_pat(risk_store)
    X._probe(monkeypatch, X._external_fake())
    cfg = _cfg(tmp_path)
    made = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg, requester_sub=PEER, llm="claude",
                             consent_external=True, consent_source="web", concurrency=2)
    assert made["concurrency_note"] == runner.CLAUDE_CONCURRENCY_NOTE
    assert _job(risk_store, made["job_id"])["concurrency"] == 1
    risk_store.execute("UPDATE rr_jobs SET concurrency = 2 WHERE id = ?", (made["job_id"],))     # 옛 행
    job = _claim(risk_store, cfg)
    assert runner.job_slots(job, cfg) == 1
    panel, _ = runner.plan_job_panel(risk_store, cfg, job)
    assert _claim(risk_store, cfg, {made["job_id"]: {panel["id"]}}) is None


def test_job_slots_follow_the_box_and_keep_issue_and_claude_jobs_at_one(tmp_path):
    """잡의 자리 수 — 잡의 concurrency 를 지금의 전역 자리 수로 다시 묶는다(만든 뒤 손잡이를 낮춘 박스). 쟁점 잡(M3 — 대상 안에서 쟁점
    패널은 한 줄) · Claude 잡은 행의 값과 상관없이 1 이다. 칸이 없는 잡은 1(종전)."""
    wide, narrow = _cfg(tmp_path), dataclasses.replace(_cfg(tmp_path), risk_concurrency=1)
    panels = {"mode": "panels", "concurrency": 2, "params_json": "{}"}
    assert (runner.job_slots(panels, wide), runner.job_slots(panels, narrow)) == (2, 1)
    assert runner.job_slots({**panels, "mode": "issues"}, wide) == 1
    assert runner.job_slots({**panels, "params_json": json.dumps({"llm": "claude"})}, wide) == 1
    assert runner.job_slots({"id": "j"}, wide) == 1


def test_create_job_says_when_the_box_runs_fewer_panels_than_asked(risk_store, tmp_path):
    """청한 동시 실행이 박스의 전역 자리 수보다 크면 그 수로 죄고 답에 까닭을 싣는다(종전에는 말없이 죄었다). 청한 만큼 돌면 칸이 없다."""
    target_key = _seed(risk_store)
    narrow = dataclasses.replace(_cfg(tmp_path), risk_concurrency=1)
    made = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=narrow, concurrency=2)
    assert made["concurrency_note"] == "동시 2 를 청했지만 박스의 전역 자리 수(HWAXRISK_CONCURRENCY 1)로 묶여 동시 1 로 돈다"
    assert _job(risk_store, made["job_id"])["concurrency"] == 1
    assert "concurrency_note" not in runner.create_job(risk_store, target_key, "B", owner_sub=OWNER, settings=_cfg(tmp_path),
                                                       concurrency=2)
    assert "concurrency_note" not in runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=_cfg(tmp_path))


def test_the_c3_follow_up_tier_c_keeps_the_tier_b_jobs_concurrency(risk_store, tmp_path):
    """C3 자동 후속 Tier C 는 Tier B 잡의 동시 실행을 물려받는다(메모 · 층 · 뺀 항목과 같다 — 동시 1 잡의 후속은 종전대로 1)."""
    target_key = _seed(risk_store)
    risk_store.execute("UPDATE rr_targets SET close_level = 'C3' WHERE target_key = ?", (target_key,))
    cfg = _cfg(tmp_path)
    for concurrency in (2, 1):
        job_id = _panel_job(risk_store, target_key, cfg, tier="B", concurrency=concurrency)
        job = runner.claim_next_job(risk_store, cfg)
        risk_store.execute("UPDATE rr_coverage SET status = 'skipped', reason = '시험' WHERE target_key = ? AND status = 'pending'",
                           (target_key,))
        done = runner.run_panel(risk_store, cfg, FakePanelEngine(), job)             # 남은 좌석이 없다 — 잡이 끝나고 후속이 선다
        assert done["status"] == "no_panel" and done["job_state"] == "completed" and done["next_job"], done
        assert _job(risk_store, done["next_job"])["concurrency"] == concurrency
        runner.cancel_job(risk_store, done["next_job"], by=OWNER)
        risk_store.execute("UPDATE rr_coverage SET status = 'pending', reason = NULL WHERE target_key = ?", (target_key,))
        assert _job(risk_store, job_id)["state"] == "completed"


# ---------------------------------------------------------------- 원장 셈
def test_check_invariants_allows_as_many_running_panels_as_the_live_job_runs(risk_store, tmp_path):
    """불변식 (2) — 대상의 도는 패널은 살아 있는 잡의 자리 수까지다(동시 2 잡이면 둘). 동시 1 잡이면 종전대로 둘째가 위반이다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _panel_job(risk_store, target_key, cfg)
    for _ in range(2):
        panel = planner.plan_next_panel(risk_store, target_key, "A", settings=cfg)
        planner.start_panel_seats(risk_store, panel["id"])
    assert planner.check_invariants(risk_store, target_key) == []
    risk_store.execute("UPDATE rr_jobs SET concurrency = 1 WHERE id = ?", (job_id,))
    assert any(p.startswith("(2) 타깃당 running 패널이 2 개다(≤1") for p in planner.check_invariants(risk_store, target_key))


def test_the_engine_fail_streak_counts_across_a_running_sibling(risk_store):
    """연속 실패 셈은 도는 패널을 건너뛴다 — 실패한 패널 사이에 형제가 돌아도 셋이면 셋이다(종전에는 도는 패널에서 끊겨 끝내 셋에 닿지 않았다)."""
    target_key = _seed(risk_store)
    now = common.now_epoch()
    for no, status in ((1, "error"), (2, "error"), (3, "running"), (4, "error")):
        risk_store.execute(
            "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, seats_json, status, error, created_at)"
            " VALUES (?, ?, ?, ?, '[]', ?, ?, ?)",
            (f"p-{no}", target_key, OWNER, no, status, "engine_error: 연결 끊김" if status == "error" else None, now))
    assert runner._error_streak(risk_store, target_key) == runner.ENGINE_FAIL_STREAK
