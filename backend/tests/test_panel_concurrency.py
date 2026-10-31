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
def _seed(store) -> str:
    """합성 diff 대상 하나 — 생산자 경로(factories.make_diff_target — 과제 · 스냅샷 둘 · diff · 대상 · 로스터 동결)다. 부를 때마다 새 과제 ·
    새 대상이다. 잡 주인의 포털 PAT 도 둔다(러너 자격)."""
    target_key = factories.make_diff_target(store, 3, owner=OWNER, agents=[
        {"key": f"{dom}-a{i:03d}", "domain": dom, "relevance": round(0.9 - 0.1 * i, 3)} for dom in DOMAINS for i in range(2)]
    ).target_key
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


def test_a_sibling_closed_by_another_panels_immediate_stop_says_why(rig, monkeypatch):
    """한 패널의 결과를 원장에 앉히지 못하면(persist_error — 미루지 않는 멈춤, CC-18) 잡이 곧바로 멈추고 형제도 닫힌다 — 그 패널의 글은
    '사용자가 …' 가 아니라 잡이 멈춘 까닭이다."""
    from app import registry

    store = rig.store
    target_key = _seed(store)
    job_id = _panel_job(store, target_key, rig.cfg)
    rig.tick()
    first = rig.portal.stream(1)
    rig.tick()
    second = rig.portal.stream(2)
    broken = _panels(store, target_key)[1]["id"]
    real = registry.merge_panel

    def merge_panel(store_, panel_id):
        if panel_id == broken:
            raise RuntimeError("병합 실패(시험)")
        return real(store_, panel_id)

    monkeypatch.setattr(registry, "merge_panel", merge_panel)
    second.finish()
    assert first.closed.wait(WAIT_S)
    rig.settle(job_id, 0)
    job = _job(store, job_id)
    assert (job["state"], job["state_by"]) == ("paused", "code:persist_error")
    panels = _panels(store, target_key)
    assert panels[1]["error"].startswith("persist_error: RuntimeError: 병합 실패(시험)")
    assert panels[0]["error"].startswith("cancelled: 잡이 멈췄다(persist_error) — 진행 중 패널을 닫았다"), panels[0]["error"]
    assert {_coverage(store, target_key)[key] for key in panels[0]["seats"]} == {("pending", 0)}
    assert store.query("SELECT action FROM rr_audit WHERE scope = 'job' AND subject_id = ?", (job_id,)) == []


def test_a_job_that_fails_on_engine_errors_waits_for_its_running_sibling(rig):
    """둘째 자리의 패널이 엔진 실패로 셋 잇달아 닫히면(연속 실패 — 종전 규칙) 잡은 실패로 끝나지만, 도는 형제는 닫지 않는다 — 새 자리는 주지
    않고 형제가 끝나면 failed 다(CC-18 — 형제의 결과는 원장에 남는다). 그동안 잡 행 error 가 까닭을 보인다."""
    store = rig.store
    target_key = _seed(store)
    job_id = _panel_job(store, target_key, rig.cfg)
    rig.tick()
    first = rig.portal.stream(1)
    for n in (2, 3, 4):
        rig.tick()
        rig.portal.stream(n).fail("llm_error")
        rig.settle(job_id, 1)
    job = _job(store, job_id)
    assert job["state"] == "running" and not first.closed.is_set()
    assert (job["error"] or "").startswith("engine_fail_streak — 같은 잡의 다른 패널이 돌고 있어"), job["error"]
    rig.tick()
    assert len(rig.portal.streams) == 4                                   # 새 자리 없음
    first.finish()
    rig.settle(job_id, 0)
    job = _job(store, job_id)
    assert (job["state"], job["error"]) == ("failed", "engine_fail_streak")
    assert [p["status"] for p in _panels(store, target_key)] == ["done", "error", "error", "error"]


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


class _InFlight(FakePanelEngine):
    """도는 형제 — 엔진 호출 도중에(스트림이 흐르는 사이 — 시작 전 물음은 이미 지났다) `during` 을 부른 뒤 끝난다(raise_error 를 주면 그
    실패로). 러너 없이 '형제가 도는 동안 다른 패널이 닫힌다' 를 한 스레드로 짓는다."""

    def __init__(self, during, **kwargs) -> None:
        super().__init__(**kwargs)
        self.during = during

    def run(self, delib_opts, *, owner_sub=None):
        self.during()
        return super().run(delib_opts, owner_sub=owner_sub)


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


def test_diminishing_returns_wait_for_the_running_sibling(risk_store, tmp_path, monkeypatch):
    """수확 체감 — 첫 패널이 끝날 때 형제가 돌면 잡을 멈추지 않고(멈추면 형제가 닫힌다) 둘째 자리만 막는다. 마지막 형제가 끝날 때 멈춘다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    # Tier C(전원 18석) — 두 패널을 앉혀도 좌석이 남는다(둘째 자리를 막는 것이 남은 좌석이 아니라 수확 체감이게).
    job_id = runner.create_job(risk_store, target_key, "C", owner_sub=OWNER, settings=cfg, concurrency=2, consent=True)["job_id"]
    job, first, second = _seat_two(risk_store, cfg, target_key, job_id)
    assert planner.has_pending(risk_store, target_key, "C")
    # 수확 체감 판정 자체(최근 패널 셋의 new_clusters)는 test_runner_panel 이 본다 — 여기서는 그 판정이 섰을 때 형제를 어떻게 다루나다.
    monkeypatch.setattr(runner, "_diminishing", lambda store, target_key: True)
    rec: dict = {}
    dull = {"narrative_mod": fake_narrative(rec), "registry_mod": fake_registry(rec, level="C1", new_clusters=0)}

    def first_completes_meanwhile():
        assert runner.run_panel(risk_store, cfg, FakePanelEngine(), job, panel=first, **dull)["status"] == "done"
        assert _job(risk_store, job_id)["state"] == "running"                     # 형제(둘째)가 돈다 — 멈추지 않는다
        assert _claim(risk_store, cfg, {job_id: {second["id"]}}) is None          # 둘째 자리는 막힌다

    assert runner.run_panel(risk_store, cfg, _InFlight(first_completes_meanwhile), job, panel=second, **dull)["status"] == "done"
    assert [p["status"] for p in _panels(risk_store, target_key)] == ["done", "done"]
    row = _job(risk_store, job_id)
    assert (row["state"], row["pause_reason"], row["error"]) == ("paused", "diminishing", None)


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

    other = _seed(risk_store)
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
    other_target = _seed(risk_store)
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
    assert made["concurrency_note"] == "동시 2 를 청했지만 잡 상한(2)과 박스의 전역 자리 수(HWAXRISK_CONCURRENCY 1)로 묶여 동시 1 로 돈다"
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
    for status in ("error", "error", "running", "error"):                     # panel_no 1 · 2 · 3 · 4(Tier C 18석이라 넷이 선다)
        panel = planner.plan_next_panel(risk_store, target_key, "C")
        risk_store.execute("UPDATE rr_panels SET status = ?, error = ? WHERE id = ?",
                           (status, "engine_error: 연결 끊김" if status == "error" else None, panel["id"]))
    assert runner._error_streak(risk_store, target_key) == runner.ENGINE_FAIL_STREAK


# ---------------------------------------------------------------- 반대 검토 10-31 고침(F1 ~ F10 — context-notes CC-16 부터)
def _tier_c_job(store, target_key: str, cfg, *, concurrency: int = 2) -> str:
    return runner.create_job(store, target_key, "C", owner_sub=OWNER, settings=cfg, concurrency=concurrency,
                             consent=True)["job_id"]


def _quiet(level: str = "C0") -> dict:
    rec: dict = {}
    return {"narrative_mod": fake_narrative(rec), "registry_mod": fake_registry(rec, level=level, new_clusters=0)}


def test_f1_a_second_slot_claim_does_not_overwrite_the_stop_its_sibling_wrote_meanwhile(rig, monkeypatch):
    """F1 — 둘째 자리를 집는 사이(그 사이에 비우기 물음 /health 가 있다) 첫 패널이 의장 실패로 잡을 멈추면, 집기는 그 멈춤을 덮지 않고(잡 행
    error 를 지우지 않는다) 둘째 패널을 편성하지 않는다 — 집기의 쓰기는 읽은 상태 그대로일 때만 선다. 종전에는 error 가 NULL 로 지워지고 둘째
    스트림이 열렸다(엔진은 그 심의를 분리 태스크로 끝까지 돌린다)."""
    store = rig.store
    target_key = _seed(store)
    job_id = _tier_c_job(store, target_key, rig.cfg)
    rig.tick()
    first = rig.portal.stream(1)
    real = rig.rr.engine.drain_state

    def sibling_stops_meanwhile():
        first.fail("chair_failed", "의장이 결정문을 내지 못했다")
        _until(lambda: _job(store, job_id)["state"] == "paused", "첫 패널이 잡을 멈춘다")
        return real()

    monkeypatch.setattr(rig.rr.engine, "drain_state", sibling_stops_meanwhile)
    rig.tick()
    job = _job(store, job_id)
    assert (job["state"], job["state_by"]) == ("paused", "code:chair_failed")
    assert (job["error"] or "").startswith("chair_failed: 의장이 결정문을 내지 못했다"), job["error"]
    assert len(rig.portal.streams) == 1, "둘째 패널이 섰다"
    assert [p["status"] for p in _panels(store, target_key)] == ["error"]


def test_f1_a_panel_planned_before_a_stop_is_never_sent_to_the_engine(risk_store, tmp_path):
    """F1 — 편성된 뒤(브리프를 짓는 사이) 잡이 멈췄거나 형제가 끝나면 멈출 참이 된 패널은 엔진에 보내지 않는다 — 포털 대화도 만들지 않고 시작
    못 한 것으로 닫는다(좌석 차감 없음). 보낸 뒤에야 들으면 엔진은 그 심의를 분리 태스크로 끝까지 돈다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _tier_c_job(risk_store, target_key, cfg)
    job, first, second = _seat_two(risk_store, cfg, target_key, job_id)
    runner.pause_job(risk_store, job_id, by=OWNER)                              # 사람이 멈췄다
    engine = FakePanelEngine()
    out = runner.run_panel(risk_store, cfg, engine, job, panel=second)
    assert engine.calls == [] and out["error"].startswith(
        "cancelled: 사용자가 잡을 일시정지했다 — 엔진에 보내기 전에 닫았다"), out
    assert {_coverage(risk_store, target_key)[s["key"]] for s in second["seats"]} == {("pending", 0)}

    other = _seed(risk_store)
    job_id = _tier_c_job(risk_store, other, cfg)
    job, first, second = _seat_two(risk_store, cfg, other, job_id)
    stop = runner.EngineNoDecision("chair_failed", "의장이 결정문을 내지 못했다")
    assert runner.run_panel(risk_store, cfg, FakePanelEngine(raise_error=stop), job, panel=first)["status"] == "error"
    assert _job(risk_store, job_id)["state"] == "running"                        # 둘째가 원장에서 돈다 — 미뤘다
    engine = FakePanelEngine()
    out = runner.run_panel(risk_store, cfg, engine, job, panel=second)            # 둘째가 이제야 엔진 앞에 왔다
    assert engine.calls == [] and out["error"].startswith("cancelled: 잡이 멈출 참이다(chair_failed)"), out
    row = _job(risk_store, job_id)
    assert (row["state"], row["state_by"]) == ("paused", "code:chair_failed")     # 마지막 형제가 닫혀 미룬 멈춤이 섰다


def test_f1_claim_notes_do_not_overwrite_a_stop_written_meanwhile(risk_store, tmp_path, monkeypatch):
    """F1 — 집기가 줄에서 기다리는 까닭(자격 없음 · 비우기 · 다시 저장 대기)을 잡 행 error 에 적을 때도 읽은 상태 그대로일 때만 쓴다 — 그
    사이 형제가 잡을 멈추며 적은 글을 덮지 않는다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _tier_c_job(risk_store, target_key, cfg)
    job = _claim(risk_store, cfg)
    first, _ = runner.plan_job_panel(risk_store, cfg, job)

    def sibling_stops_then_no_credential(*args, **kwargs):
        runner._stop_job(risk_store, job, first, cfg, state="paused", by="code:chair_failed", error="chair_failed: 형제의 글")
        return None, "자격 없음(시험)"

    monkeypatch.setattr(runner, "resolve_job_credential", sibling_stops_then_no_credential)
    assert _claim(risk_store, cfg, {job_id: {first["id"]}}) is None
    row = _job(risk_store, job_id)
    assert (row["state"], row["error"]) == ("paused", "chair_failed: 형제의 글")


@pytest.mark.parametrize("action", ["cancel", "pause"])
def test_f8_a_first_slot_claim_does_not_overwrite_a_human_stop_made_meanwhile(risk_store, tmp_path, monkeypatch, action):
    """F8(종전부터) — 줄 선 잡을 집는 사이(자격을 고르는 사이) 사람이 취소 · 정지하면 집기가 그것을 running 으로 덮지 않는다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _panel_job(risk_store, target_key, cfg, concurrency=1)
    real = runner.resolve_job_credential

    def human_acts_meanwhile(*args, **kwargs):
        (runner.cancel_job if action == "cancel" else runner.pause_job)(risk_store, job_id, by=OWNER)
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "resolve_job_credential", human_acts_meanwhile)
    assert runner.claim_next_job(risk_store, cfg) is None
    assert _job(risk_store, job_id)["state"] == ("cancelled" if action == "cancel" else "paused")


def test_f8_the_midnight_resume_does_not_overwrite_a_cancel(risk_store, tmp_path, monkeypatch):
    """F8 — 하루 상한으로 멈춘 잡을 자정 뒤 집기가 다시 줄 세울 때, 그 사이 사람이 취소했으면 덮지 않는다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _panel_job(risk_store, target_key, cfg, concurrency=1)
    risk_store.execute("UPDATE rr_jobs SET state = 'paused', pause_reason = 'daily_cap', updated_at = 0 WHERE id = ?", (job_id,))
    real = runner._set_job

    def set_job(store, job_id_, state, **kwargs):
        if state == "queued" and job_id_ == job_id and _job(risk_store, job_id)["state"] == "paused":
            runner.cancel_job(risk_store, job_id, by=OWNER)                     # 사람 — 집기가 읽은 뒤 · 쓰기 전
        return real(store, job_id_, state, **kwargs)

    monkeypatch.setattr(runner, "_set_job", set_job)
    assert runner.claim_next_job(risk_store, cfg) is None
    assert _job(risk_store, job_id)["state"] == "cancelled"


def test_f2_a_human_pause_beats_a_deferred_stop(risk_store, tmp_path):
    """F2 — 미뤄 둔 멈춤이 있는 잡을 사람이 멈추면 마지막 형제가 닫힐 때 그 멈춤을 덮어쓰지 않는다(주체 · 까닭은 사람의 것 그대로)."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _tier_c_job(risk_store, target_key, cfg)
    job, first, second = _seat_two(risk_store, cfg, target_key, job_id)
    stop = runner.EngineNoDecision("chair_failed", "의장이 결정문을 내지 못했다")

    def second_stops_then_a_human_pauses():
        runner.run_panel(risk_store, cfg, FakePanelEngine(raise_error=stop), job, panel=second)
        assert _job(risk_store, job_id)["state"] == "running"                   # 미뤘다
        runner.pause_job(risk_store, job_id, by=OWNER)

    runner.run_panel(risk_store, cfg, _InFlight(second_stops_then_a_human_pauses), job, panel=first, **_quiet())
    row = _job(risk_store, job_id)
    assert (row["state"], row["pause_reason"], row["state_by"]) == ("paused", "user", OWNER)
    assert runner.DEFERRED_KEY not in json.loads(row["progress_json"] or "{}")


def test_f8_a_daily_cap_pause_does_not_overwrite_a_cancel(risk_store, tmp_path, monkeypatch):
    """F8 — 집기가 하루 상한으로 잡을 멈출 때도 그 사이 사람이 취소했으면 덮지 않는다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path, risk_daily_panel_cap=0)
    job_id = _panel_job(risk_store, target_key, cfg, concurrency=1)

    def human_cancels_meanwhile(store, target_key_):
        runner.cancel_job(risk_store, job_id, by=OWNER)
        return 0

    monkeypatch.setattr(runner, "_panels_today", human_cancels_meanwhile)
    assert runner.claim_next_job(risk_store, cfg) is None
    assert _job(risk_store, job_id)["state"] == "cancelled"


def test_f2_a_leftover_deferred_stop_is_applied_by_the_next_claim(risk_store, tmp_path):
    """F2 — 러너가 그 잡의 패널을 다 놓았는데 미뤄 둔 멈춤이 남았으면(마지막으로 닫힌 것이 다른 길의 패널 · 옮기다 실패) 다음 집기가 그
    멈춤을 옮긴다 — 새 패널을 주지 않는다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _tier_c_job(risk_store, target_key, cfg)
    job = _claim(risk_store, cfg)
    body = {runner.DEFERRED_KEY: {"state": "paused", "by": "code:chair_failed", "reason": None,
                                  "error": "chair_failed: 남은 멈춤(시험)", "panel_id": "p-gone", "at": 0}}
    risk_store.execute("UPDATE rr_jobs SET progress_json = ? WHERE id = ?", (json.dumps(body), job_id))
    assert job["state"] == "running" and _claim(risk_store, cfg) is None
    row = _job(risk_store, job_id)
    assert (row["state"], row["state_by"], row["error"]) == ("paused", "code:chair_failed", "chair_failed: 남은 멈춤(시험)")
    assert runner.DEFERRED_KEY not in json.loads(row["progress_json"])


def test_f2_a_human_resume_drops_a_leftover_deferred_stop(risk_store, tmp_path):
    """F2 — 남은 미뤄 둔 멈춤이 있는 잡을 사람이 멈췄다 재개하면 그 멈춤은 걷힌다 — 다음 집기가 그것을 다시 세워 사람의 재개를 뒤집지
    않는다(사람의 뜻이 이긴다)."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _tier_c_job(risk_store, target_key, cfg)
    _claim(risk_store, cfg)
    body = {runner.DEFERRED_KEY: {"state": "paused", "by": "code:chair_failed", "reason": None,
                                  "error": "chair_failed: 남은 멈춤(시험)", "panel_id": "p-gone", "at": 0}}
    risk_store.execute("UPDATE rr_jobs SET progress_json = ? WHERE id = ?", (json.dumps(body), job_id))
    runner.pause_job(risk_store, job_id, by=OWNER)
    runner.resume_job(risk_store, job_id, by=OWNER)
    assert _claim(risk_store, cfg)["id"] == job_id and _job(risk_store, job_id)["state"] == "running"


def test_f3_a_deferred_failure_wins_over_the_last_siblings_own_stop(risk_store, tmp_path):
    """F3 — 형제가 도는 동안 미룬 실패(연속 실패)는, 그 형제가 제 일(의장 실패)로 잡을 멈추며 끝나도 실패로 남는다 — 실패가 멈춤을 이긴다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _tier_c_job(risk_store, target_key, cfg)
    job = _claim(risk_store, cfg)
    first, _ = runner.plan_job_panel(risk_store, cfg, job)

    def three_siblings_fail_meanwhile():
        for _ in range(runner.ENGINE_FAIL_STREAK):
            again = _claim(risk_store, cfg, {job_id: {first["id"]}})
            panel, _ = runner.plan_job_panel(risk_store, cfg, again, siblings=True)
            runner.run_panel(risk_store, cfg, FakePanelEngine(raise_error=runner.EngineError("연결 끊김")), again, panel=panel)
        assert _job(risk_store, job_id)["state"] == "running"                   # 미룬 실패 — 형제(첫 패널)가 돈다

    stop = runner.EngineNoDecision("chair_failed", "의장이 결정문을 내지 못했다")
    out = runner.run_panel(risk_store, cfg, _InFlight(three_siblings_fail_meanwhile, raise_error=stop), job, panel=first)
    assert out["error"].startswith("chair_failed: ")
    row = _job(risk_store, job_id)
    assert (row["state"], row["error"]) == ("failed", "engine_fail_streak")


def test_f4_an_automatic_stop_never_overwrites_an_earlier_human_cancel(risk_store, tmp_path, monkeypatch):
    """F4 — 패널이 도는 사이 사람이 취소한 잡(cancelling)에 그 패널의 자동 정지(수확 체감)가 paused 를 덮어쓰지 않는다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _panel_job(risk_store, target_key, cfg, concurrency=1)
    job = runner.claim_next_job(risk_store, cfg)
    monkeypatch.setattr(runner, "_diminishing", lambda store, target_key: True)
    human = _InFlight(lambda: runner.cancel_job(risk_store, job_id, by=OWNER))
    assert runner.run_panel(risk_store, cfg, human, job, **_quiet("C1"))["status"] == "done"
    assert _job(risk_store, job_id)["state"] == "cancelling"


def test_f2_a_deferred_diminishing_pause_lands_even_when_the_last_sibling_fails(risk_store, tmp_path, monkeypatch):
    """F2 — 형제가 도는 동안 미룬 수확 체감 정지는 마지막 형제가 어떻게 끝나든(여기서는 엔진 실패) 그때 선다. 종전에는 마지막 형제가 done 으로
    끝날 때만 다시 판정해, 실패로 끝나면 잡이 running 으로 남아 다음 첫 자리가 새 패널을 편성했다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _tier_c_job(risk_store, target_key, cfg)
    job, first, second = _seat_two(risk_store, cfg, target_key, job_id)
    monkeypatch.setattr(runner, "_diminishing", lambda store, target_key: True)

    def first_completes_meanwhile():
        assert runner.run_panel(risk_store, cfg, FakePanelEngine(), job, panel=first, **_quiet("C1"))["status"] == "done"
        assert _job(risk_store, job_id)["state"] == "running"                   # 형제가 돈다 — 미룬다

    out = runner.run_panel(risk_store, cfg, _InFlight(first_completes_meanwhile, raise_error=runner.EngineError("연결 끊김")),
                           job, panel=second, **_quiet("C1"))
    assert out["status"] == "error" and out["error"].startswith("engine_error: ")
    row = _job(risk_store, job_id)
    assert (row["state"], row["pause_reason"], row["state_by"]) == ("paused", "diminishing", "code:diminishing")
    assert _claim(risk_store, cfg) is None


def test_f2_a_human_resume_drops_a_deferred_stop(risk_store, tmp_path, monkeypatch):
    """F2 — 미뤄 둔 멈춤은 사람의 재개가 걷는다 — 사람이 멈췄다 재개한 잡은 형제가 끝나도 그 멈춤을 다시 세우지 않는다(사람의 뜻이 이긴다)."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _tier_c_job(risk_store, target_key, cfg)
    job, first, second = _seat_two(risk_store, cfg, target_key, job_id)
    monkeypatch.setattr(runner, "_diminishing", lambda store, target_key: True)

    def first_completes_then_a_human_pauses_and_resumes():
        assert runner.run_panel(risk_store, cfg, FakePanelEngine(), job, panel=first, **_quiet("C1"))["status"] == "done"
        runner.pause_job(risk_store, job_id, by=OWNER)
        runner.resume_job(risk_store, job_id, by=OWNER)

    assert runner.run_panel(risk_store, cfg, _InFlight(first_completes_then_a_human_pauses_and_resumes), job, panel=second,
                            **_quiet("C1"))["status"] == "done"
    assert _job(risk_store, job_id)["state"] == "queued"
    assert _claim(risk_store, cfg)["id"] == job_id                               # 사람이 재개한 잡이 이어 돈다


def test_f3_a_chair_failure_lets_the_running_sibling_finish_then_pauses(rig):
    """F3 — 한 패널의 의장 실패(chair_failed)는 몇 시간째 잘 도는 형제를 닫지 않는다 — 새 자리는 주지 않고(좌석이 남아도) 형제가 끝나면 잡을
    멈춘다. 형제의 결과는 원장에 남는다. 종전에는 형제가 곧바로 닫혀 그 일을 잃었다."""
    store = rig.store
    target_key = _seed(store)
    job_id = _tier_c_job(store, target_key, rig.cfg)
    rig.tick()
    first = rig.portal.stream(1)
    rig.tick()
    second = rig.portal.stream(2)

    second.fail("chair_failed", "의장이 결정문을 내지 못했다")
    rig.settle(job_id, 1)
    job = _job(store, job_id)
    assert job["state"] == "running" and not first.closed.is_set()
    assert (job["error"] or "").startswith("chair_failed: 의장이 결정문을 내지 못했다"), job["error"]
    rig.tick()
    assert len(rig.portal.streams) == 2                                           # 새 자리 없음(좌석이 남았다)

    first.finish()
    rig.settle(job_id, 0)
    job = _job(store, job_id)
    assert (job["state"], job["state_by"]) == ("paused", "code:chair_failed")
    assert (job["error"] or "").startswith("chair_failed: 의장이 결정문을 내지 못했다")
    assert [p["status"] for p in _panels(store, target_key)] == ["done", "error"]
    assert store.query("SELECT action FROM rr_audit WHERE scope = 'job' AND subject_id = ?", (job_id,)) == []


@pytest.mark.parametrize("cause", ["panel_timeout", "engine_silent", "brief_error"])
def test_f3_panel_local_stops_wait_for_the_running_sibling(risk_store, tmp_path, cause):
    """F3 — 패널 하나의 일(스트림 벽시계 · 침묵 · 결정론 브리프 오류)은 형제가 도는 동안 잡을 옮기지 않고 새 자리만 막는다. 형제가 끝나면 잡을
    멈춘다(그 까닭으로)."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _tier_c_job(risk_store, target_key, cfg)
    job, first, second = _seat_two(risk_store, cfg, target_key, job_id)
    mods = _quiet()
    if cause == "brief_error":
        def prior_evidence(*args, **kwargs):
            raise ValueError("브리프 린터 위반(시험)")

        mods["narrative_mod"].prior_evidence = prior_evidence
        engine = FakePanelEngine()
    else:
        engine = FakePanelEngine(raise_error=runner.EngineStreamLost(cause, "스트림을 놓았다(시험)"))
    def second_stops_meanwhile():
        out = runner.run_panel(risk_store, cfg, engine, job, panel=second, **mods)
        assert out["status"] == "error" and out["error"].startswith(f"{cause}: "), out
        assert _job(risk_store, job_id)["state"] == "running"
        assert _claim(risk_store, cfg, {job_id: {first["id"]}}) is None          # 새 자리 없음(좌석이 남았다)

    assert runner.run_panel(risk_store, cfg, _InFlight(second_stops_meanwhile), job, panel=first, **_quiet())["status"] == "done"
    row = _job(risk_store, job_id)
    assert (row["state"], row["state_by"]) == ("paused", f"code:{cause}")
    assert (row["error"] or "").startswith(f"{cause}: ")


def test_f3_a_portal_stop_still_stops_the_whole_job_at_once(rig):
    """F3 — 사람이 포털에서 한 패널 심의를 멈추면(A24) 잡 전체를 곧바로 멈춘다(사람의 뜻 — 형제도 닫힌다). 감사 행은 그 사람의 job.pause
    하나다."""
    store = rig.store
    target_key = _seed(store)
    job_id = _tier_c_job(store, target_key, rig.cfg)
    rig.tick()
    first = rig.portal.stream(1)
    rig.tick()
    second = rig.portal.stream(2)
    second.say("delib", {"kind": "cancelled", "by": "Human@Example.com", "message": "멈췄다(시험)"})
    second.say("done", {})
    assert first.closed.wait(WAIT_S)
    rig.settle(job_id, 0)
    job = _job(store, job_id)
    assert (job["state"], job["state_by"]) == ("paused", "code:cancelled")
    panels = _panels(store, target_key)
    assert panels[0]["error"].startswith(
        "cancelled: 잡이 멈췄다(사람이 포털에서 같은 잡의 다른 패널 심의를 멈췄다) — 진행 중 패널을 닫았다"), panels[0]["error"]
    rows = store.query("SELECT action, actor, actor_verified FROM rr_audit WHERE scope = 'job' AND subject_id = ?", (job_id,))
    assert [(r["action"], r["actor"], r["actor_verified"]) for r in rows] == [("job.pause", "human@example.com", 0)]


def test_f3_a_persist_error_still_pauses_the_job_at_once(risk_store, tmp_path):
    """F3 — 결과를 원장에 앉히지 못한 패널(persist_error)은 형제가 돌아도 곧바로 잡을 멈춘다(그 대상은 다시 저장 전까지 편성되지 않는다)."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _tier_c_job(risk_store, target_key, cfg)
    job, first, second = _seat_two(risk_store, cfg, target_key, job_id)
    mods = _quiet()

    def merge_panel(store, panel_id):
        raise RuntimeError("병합 실패(시험)")

    mods["registry_mod"].merge_panel = merge_panel
    out = runner.run_panel(risk_store, cfg, FakePanelEngine(), job, panel=second, **mods)
    assert out["error"].startswith("persist_error: ")
    row = _job(risk_store, job_id)
    assert (row["state"], row["state_by"]) == ("paused", "code:persist_error")


def test_f4_a_human_cancel_racing_an_automatic_pause_is_not_lost(risk_store, tmp_path, monkeypatch):
    """F4 — 러너의 자동 정지(수확 체감)가 잡 상태를 읽고 쓰는 사이에 사람이 다른 스레드에서 취소해도 그 취소가 지지 않는다 — 읽기와 쓰기가 한
    트랜잭션이라 사람의 취소는 그 뒤에 선다. 종전에는 정지가 취소를 paused 로 덮었고 감사 행만 job.cancel 로 남았다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _panel_job(risk_store, target_key, cfg, concurrency=1)
    job = runner.claim_next_job(risk_store, cfg)
    monkeypatch.setattr(runner, "_diminishing", lambda store, target_key: True)
    real = runner._set_job
    humans: list[threading.Thread] = []

    def set_job(store, job_id_, state, **kwargs):
        if state == "paused" and kwargs.get("reason") == "diminishing" and not humans:
            human = threading.Thread(target=runner.cancel_job, args=(risk_store, job_id_), kwargs={"by": OWNER})
            humans.append(human)
            human.start()
            human.join(0.5)                       # 저장소 잠금이 막으면 여기서 기다리다 넘어간다
        return real(store, job_id_, state, **kwargs)

    monkeypatch.setattr(runner, "_set_job", set_job)
    assert runner.run_panel(risk_store, cfg, FakePanelEngine(), job, **_quiet("C1"))["status"] == "done"
    assert humans, "수확 체감 정지가 서지 않았다"
    humans[0].join(10)
    assert _job(risk_store, job_id)["state"] == "cancelled"


def test_f5_recovery_and_new_panels_do_not_keep_stale_panel_signals(risk_store, tmp_path):
    """F5 — 앱이 죽어 닫힌 패널의 신호 칸이 남지 않는다 — 재기동 복구가 끊긴 잡의 칸을 비우고, 신호를 적는 쪽도 원장에서 도는 패널의 칸만
    남긴다(과제 상세의 잡 목록은 progress_json 을 그대로 편다)."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _tier_c_job(risk_store, target_key, cfg)
    job, first, second = _seat_two(risk_store, cfg, target_key, job_id)
    for panel in (first, second):
        runner._progress_writer(risk_store, job, panel, per_panel=True)({})

    def panel_ids() -> set[str]:
        return set(json.loads(_job(risk_store, job_id)["progress_json"]).get("panels") or {})

    assert panel_ids() == {first["id"], second["id"]}
    runner.recover_running_panels(risk_store)
    assert panel_ids() == set()
    # 칸이 남은 채 새 패널이 선다(옛 판이 남긴 행) — 적는 쪽이 도는 패널의 칸만 남긴다.
    body = json.loads(_job(risk_store, job_id)["progress_json"])
    body["panels"] = {first["id"]: {"panel_id": first["id"]}, "gone": {"panel_id": "gone"}}
    risk_store.execute("UPDATE rr_jobs SET progress_json = ? WHERE id = ?", (json.dumps(body), job_id))
    runner.resume_job(risk_store, job_id, by=OWNER)
    job = _claim(risk_store, cfg)
    third, _ = runner.plan_job_panel(risk_store, cfg, job)
    runner._progress_writer(risk_store, job, third, per_panel=True)({})
    assert panel_ids() == {third["id"]}


def test_f7_a_seat_taken_between_pick_and_claim_does_not_complete_the_job(risk_store, tmp_path, monkeypatch):
    """F7(종전부터) — 편성기가 고른 좌석을 선점하기 전에 사람이 그 좌석을 넘기면(선점 경합) 편성기는 None 을 낸다. 그것을 '남은 좌석 없음' 으로
    읽어 잡을 끝내지 않는다 — 좌석이 남았으면 다음 집기가 다시 편성한다."""
    target_key = _seed(risk_store)
    cfg = _cfg(tmp_path)
    job_id = _tier_c_job(risk_store, target_key, cfg, concurrency=1)
    real = planner._pick_seats
    raced: list[str] = []

    def pick_then_a_human_skips(queues, tier, adj):
        seats = real(queues, tier, adj)
        if not raced:
            raced.append(seats[0]["key"])
            planner.skip_seat(risk_store, target_key, seats[0]["key"], "사람이 넘겼다(시험)", decided_by=OWNER)
        return seats

    monkeypatch.setattr(planner, "_pick_seats", pick_then_a_human_skips)
    job = runner.claim_next_job(risk_store, cfg)
    out = runner.run_panel(risk_store, cfg, FakePanelEngine(), job, **_quiet())
    assert out["status"] == "no_panel" and _job(risk_store, job_id)["state"] == "running", out
    assert planner.has_pending(risk_store, target_key, "C")
    job = runner.claim_next_job(risk_store, cfg)
    assert runner.run_panel(risk_store, cfg, FakePanelEngine(), job, **_quiet())["status"] == "done"


def test_f10_the_server_runs_at_most_two_panels_per_job(risk_store, tmp_path):
    """F10 — 잡의 동시 실행은 둘까지다(화면 · 계약 '≤2') — 본문이 둘을 넘으면 422 이고, 박스의 전역 자리가 더 많아도 잡은 둘을 넘지 않는다."""
    from pydantic import ValidationError

    from app import entry

    for bad in (0, 3):
        with pytest.raises(ValidationError):
            routes.JobBody(tier="A", concurrency=bad)
        with pytest.raises(runner.AppError) as refused:
            entry._body(routes.JobBody, tier="A", concurrency=bad)
        assert refused.value.http_status == 422
    target_key = _seed(risk_store)
    wide = dataclasses.replace(_cfg(tmp_path), risk_concurrency=4)
    made = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=wide, concurrency=3)
    assert _job(risk_store, made["job_id"])["concurrency"] == 2
    assert runner.job_slots({"mode": "panels", "concurrency": 3, "params_json": "{}"}, wide) == 2


def test_f10_the_c3_follow_up_of_a_legacy_claude_job_runs_one_panel(risk_store, tmp_path, monkeypatch):
    """F10 — C3 자동 후속은 B 잡이 실제로 돈 자리 수(job_slots)를 물려받는다 — 2 로 저장된 옛 Claude B 잡(동시 1 로 돌았다)의 후속(GLM)은
    동시 1 이다."""
    from tests import test_external_llm_jobs as X
    from tests.test_claude_panel_jobs import PEER, _peer_pat

    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: "runner-panel-gateway-secret")
    target_key = _seed(risk_store)
    risk_store.execute("UPDATE rr_targets SET close_level = 'C3' WHERE target_key = ?", (target_key,))
    _peer_pat(risk_store)
    X._probe(monkeypatch, X._external_fake())
    cfg = _cfg(tmp_path)
    made = runner.create_job(risk_store, target_key, "B", owner_sub=OWNER, settings=cfg, requester_sub=PEER, llm="claude",
                             consent_external=True, consent_source="web")
    risk_store.execute("UPDATE rr_jobs SET concurrency = 2 WHERE id = ?", (made["job_id"],))     # 옛 행
    job = runner.claim_next_job(risk_store, cfg)
    risk_store.execute("UPDATE rr_coverage SET status = 'skipped', reason = '시험' WHERE target_key = ? AND status = 'pending'",
                       (target_key,))
    done = runner.run_panel(risk_store, cfg, FakePanelEngine(), job)
    assert done["job_state"] == "completed" and done["next_job"], done
    assert _job(risk_store, done["next_job"])["concurrency"] == 1


def _closed_panels(store, target_key: str, rows: list[tuple[str, int, str | None, str | None]]) -> list[dict]:
    """편성기로 패널을 세우고 상태 · 닫은 시각 · 오류 · 품질만 고친다(손 INSERT 없이 — 씨앗 출처 래칫)."""
    out = []
    for status, ended_at, error, quality in rows:
        panel = planner.plan_next_panel(store, target_key, "C")
        store.execute("UPDATE rr_panels SET status = ?, ended_at = ?, error = ?, quality_json = ? WHERE id = ?",
                      (status, ended_at, error, quality, panel["id"]))
        out.append(panel)
    return out


def test_f10_streaks_follow_the_close_time_not_the_panel_number(risk_store):
    """F10 — 연속 실패 셈 · 수확 체감 창은 닫힌 차례(ended_at)로 본다 — 번호가 앞인 형제가 나중에 잘 끝나면 셈이 끊기고 창에 든다."""
    target_key = _seed(risk_store)
    base = common.now_epoch()
    err = "engine_error: 연결 끊김"
    _closed_panels(risk_store, target_key, [("done", base + 30, None, '{"new_clusters": 2}'), ("error", base + 10, err, None),
                                            ("error", base + 20, err, None), ("error", base + 40, err, None)])
    assert runner._error_streak(risk_store, target_key) == 1                    # 닫힌 차례 — 4(실패) · 1(성공)에서 끊긴다
    other = _seed(risk_store)
    _closed_panels(risk_store, other, [("done", base + 40, None, '{"new_clusters": 2}'), ("done", base + 10, None, '{"new_clusters": 0}'),
                                       ("done", base + 20, None, '{"new_clusters": 0}'), ("done", base + 30, None, '{"new_clusters": 0}')])
    assert runner._diminishing(risk_store, other) is False                      # 가장 늦게 닫힌 패널이 새 클러스터를 냈다
    third = _seed(risk_store)
    retry = "brief_retry: OperationalError: 잠김(시험)"
    _closed_panels(risk_store, third, [("done", base + 30, None, None), ("error", base + 10, retry, None),
                                       ("error", base + 20, retry, None)])
    assert runner._brief_retry_streak(risk_store, third) == 0                   # 가장 늦게 닫힌 패널이 잘 끝났다
