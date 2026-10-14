# 359명 규모(재설계 M3 C3-11) — 합성 로스터 359명(영역 15 · 회로 110 · 카드 0장 3)의 셀 원장에서 셈·진행판·완결 몫·품질이 제때 서고 MCP 응답이 와이어 한도 안에 쪽으로 다 온다
"""원장은 생산자 경로로 만든다 — 대상은 라우트(359명 로스터), 셀은 검토 잡의 격자(plan_cells), 일부 전문가는 가짜 엔진의 검토 루프로
끝까지 돈다(나머지 셀은 범위 밖 대기). 기본은 시험대의 단위 다섯(셀 1,795 — 합성 40줄은 단위 크기 손잡이로 셋을 만들 수 없어 다섯과
둘 사이를 오간다, 다섯을 쓴다)이고 `RR_FULL=1` 이면 단위를 잘게 세워 20개(셀 7,180 — 전원 격자)로 같은 단언을 본다. 시간 단언은 세 번 잰 가운데 가장 빠른 값이다(바쁜 박스의 흔들림을 덜어 낸다).
"""
from __future__ import annotations

import asyncio
import os
import time

import pytest

import app.mcp_server as srv
from app import review_cells, review_quality, review_runner, routes
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

OWNER = rig.OWNER
FULL = os.environ.get("RR_FULL") == "1"
# 영역 크기(합 359) — 회로 6영역 110명(입력 결손), 나머지 9영역 249명. xd 가 가장 크다(셀의 약 3분의 1).
SIZES = {"xd": 122, "mech": 40, "sim": 20, "rel": 15, "disp": 12, "cam": 12, "sh": 10, "std": 10, "material": 8,
         "pcb": 30, "pwr": 20, "rf": 20, "soc": 15, "passive": 15, "mem": 10}
ZERO_CARDS = ("sim-z-0", "sh-z-0", "cam-z-0")
RUN = ("mech-0", "mech-1", "xd-0", "pcb-1")                       # 끝까지 도는 전문가(1순위 · 2순위 · 입력 결손 2순위)


def _roster() -> list[dict]:
    out = []
    for domain, size in SIZES.items():
        for i in range(size):
            out.append({"key": f"{domain}-{i}", "domain": domain, "relevance": round(0.99 - i * 0.001, 3)})
    out += [{"key": key, "domain": key.split("-")[0], "relevance": 0.5} for key in ZERO_CARDS]
    drop = {f"{k.split('-')[0]}-{SIZES[k.split('-')[0]] - 1}" for k in ZERO_CARDS}     # 합 359 를 지킨다
    return [r for r in out if r["key"] not in drop]


def _packs(roster) -> dict[str, dict]:
    ok, empty = fre.load("pack_ok.json"), fre.load("pack_empty.json")
    return {r["key"]: (fre.derive_pack(empty, r["key"], name=r["key"], domain=r["domain"], keep="none") if r["key"] in ZERO_CARDS
                       else fre.derive_pack(ok, r["key"], name=r["key"], domain=r["domain"])) for r in roster}


@pytest.fixture(scope="module")
def scale(tmp_path_factory):
    """모듈 한 번 — 359명 대상 · 검토 잡(범위 넷)을 끝까지 돈 원장. 반환 (store, key, job_id, roster)."""
    from app.risk_store import RiskStore

    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("scale")
    store = RiskStore(tmp / "risk.db")
    store.open()
    store.migrate()
    caps = {"risk_unit_target_lines": 8, "risk_unit_max_lines": 15, "risk_units_small_lines": 6} if FULL else {}
    rig.configure(mp, store, tmp, risk_review_concurrency=4, **caps)
    mp.setattr(review_runner, "QUALITY_HOOK", review_quality.progress_hook)     # main 의 lifespan 이 꽂는 그대로(진행판의 품질 칸)
    roster = _roster()
    assert len(roster) == 359 and sum(1 for r in roster if r["domain"] in ("pcb", "pwr", "rf", "soc", "passive", "mem")) == 110
    key = rig.target(store, roster)
    job_id = rig.job(store, key, scope={"agents": list(RUN)})
    fake = FakeReviewEngine(_packs(roster))
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    yield store, key, job_id, roster
    mp.undo()
    store.close()


def _fastest(fn, n: int = 3) -> tuple[float, object]:
    best, out = float("inf"), None
    for _ in range(n):
        tick = time.perf_counter()
        out = fn()
        best = min(best, time.perf_counter() - tick)
    return best, out


def test_the_grid_board_closure_and_quality_stand_in_time(scale):
    """plan_cells 1초 · 진행판 review 칸 0.5초 · 완결 몫 0.5초 · 품질 수치 2초 안 — 격자는 로스터 × 검토 대상 단위이고 불변식이
    빈다."""
    store, key, job_id, roster = scale
    units_n = len(review_cells.active_unit_ids(store, key))
    assert units_n == (20 if FULL else 5)
    plan_s, plan = _fastest(lambda: review_cells.plan_cells(store, key))
    assert plan["cells_total"] == 359 * units_n and plan["cells_new"] == 0 and plan_s < 1.0, plan_s
    board_s, board = _fastest(lambda: routes.review_payload(store, key, "cells"))
    assert board["cells"]["total"] == 359 * units_n and board_s < 0.5, board_s
    closure_s, closure = _fastest(lambda: review_cells.closure_cells(store, key))
    assert closure["grid"] == {"roster": 359, "units": units_n, "expected": 359 * units_n, "actual": 359 * units_n}
    assert closure["invariants"] == [] and closure_s < 0.5, closure_s
    quality_s, quality = _fastest(lambda: review_quality.compute(store, key))
    assert quality["grid"]["experts"] == 359 and quality_s < 2.0, quality_s


def _guide(store, key: str) -> dict:
    """길잡이(risk_next_step) — 합성 과제는 소스 행 없이 스냅샷을 만들어 길잡이가 소스 단계에서 멈춘다. 소스를 잠시 붙여 대상
    단계(셀 진행판 · 검토 잡 칸)까지 걷게 하고 뗀다(모듈 원장을 다른 시험과 나눈다)."""
    project_id = store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]
    routes.add_source(project_id, routes.SourceBody(kind="mcad", ref={"stepforge_project_id": "sf-scale"}),
                      ident=factories.ident(OWNER))
    try:
        return _call("risk_next_step", project_id=project_id)
    finally:
        store.execute("DELETE FROM rr_sources WHERE project_id = ? AND json_extract(ref_json, '$.stepforge_project_id') ="
                      " 'sf-scale'", (project_id,))


def _call(name: str, /, **kwargs) -> dict:
    out = getattr(srv, name)(**kwargs)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def test_every_mcp_answer_fits_the_wire_and_its_pages_add_up(scale, monkeypatch):
    """R3B-1 — 359명에서도 MCP 응답 하나가 와이어 25,000자 안이고 쪽을 이으면 전부다: 진행판(기본 · 검토 순서 쪽 · 좌석 쪽), 길잡이,
    셀 격자, 실패 셀 다시(retry_failed — 바꿀 것이 없는 잡), 전문가 보고서의 part 마다."""
    store, key, job_id, roster = scale
    factories.act_as_delegate(monkeypatch, OWNER)
    limit = srv.MCP_RESULT_CHARS
    assert rig.progress(store, job_id).get("quality")                            # 운영처럼 품질 칸이 실린 진행판
    brief = _call("risk_get_coverage", target_key=key)
    assert srv._wire_chars(brief) <= limit and brief["seats"]
    assert brief["review"]["order_page"]["top_per_domain"] < 3                    # 줄여서 들었다(영역 15 × 앞 3명은 넘는다)
    assert srv._wire_chars(_call("risk_get_coverage", target_key=key, with_seats=False)) <= limit
    order, offset = [], 0
    while offset is not None:
        page = _call("risk_get_coverage", target_key=key, order_offset=offset)
        assert srv._wire_chars(page) <= limit
        order += page["review"]["order"]
        offset = page["review"]["order_page"].get("next_order_offset")
    assert [r["agent_key"] for r in order] == [r["agent_key"] for r in routes.review_order_payload(store, key)]
    seats, offset = 0, 0
    while offset is not None:
        page = _call("risk_get_coverage", target_key=key, seat_offset=offset)
        assert srv._wire_chars(page) <= limit
        seats += len(page.get("seats") or ())
        offset = page.get("next_seat_offset")
    guide = _guide(store, key)
    assert guide["where"] != "sources" and srv._wire_chars(guide) <= limit             # 대상 단계까지 걸은 길잡이
    rows, offset, total = 0, 0, None
    while offset is not None:
        page = _call("risk_get_cells", target_key=key, offset=offset)
        assert srv._wire_chars(page) <= limit
        rows += len(page["rows"])
        total = page["total"]
        offset = page.get("next_offset")
    assert rows == total == len(review_cells.active_unit_ids(store, key)) * 359
    out = _call("risk_job_action", job_id=job_id, action="retry_failed", reason="규모 시험의 다시")
    assert srv._wire_chars(out) <= limit
    for part in ("summary", "units", "cards", "full"):
        page_no, body = 1, []
        while page_no is not None:
            page = _call("risk_get_expert_report", target_key=key, agent_key="xd-0", part=part, page=page_no)
            assert srv._wire_chars(page) <= limit, (part, page_no)
            body.append(page["page"])
            page_no = page.get("next_page")
        assert len(body) == page["pages_total"] and all(body)


def test_one_experts_pack_502_does_not_hold_the_others_reviews(tmp_path, monkeypatch, risk_store):
    """전문가 단위 단계(C3-11) — 한 전문가의 카드 묶음이 502 를 여섯 번 내는 동안에도 묶음을 받은 다른 전문가의 셀은 검토로 집혀
    돈다(잡 전체를 pack 단계로 묶지 않는다). 그 전문가만 blocked · 셀 failed(pack_unavailable)이고 잡은 completed 다."""
    rig.configure(monkeypatch, risk_store, tmp_path, risk_review_concurrency=1)
    key = rig.target(risk_store)
    job_id = rig.job(risk_store, key, scope={"agents": [rig.SEAL, "xd-syn-1"]})
    fake = FakeReviewEngine(rig.packs())
    fake.pack_errors = {"xd-syn-1": [(502, {"code": "card_fetch_failed", "message": "카드 조회 실패(가짜)"})] * 8}
    r = rig.Rig(risk_store, fake)
    r.tick()                                                        # 둘 다 묶음 — xd-syn-1 은 502
    reviewed_before_xd_gave_up = []
    for _ in range(40):
        r.clock.advance(61)
        r.tick()
        seal = {c["state"] for c in risk_store.query("SELECT state FROM rr_review_cells WHERE target_key = ? AND agent_key = ?",
                                                      (key, rig.SEAL))}
        xd_head = risk_store.query_one("SELECT state FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?",
                                       (key, "xd-syn-1"))["state"]
        reviewed_before_xd_gave_up.append((seal == {"reviewed"}, xd_head))
        if rig.state(risk_store, job_id) == "completed":
            break
    assert rig.state(risk_store, job_id) == "completed"
    assert any(done and head != "blocked" for done, head in reviewed_before_xd_gave_up)   # 묶음 재시도 중에 검토가 끝났다
    states = {c["state"] for c in risk_store.query("SELECT state FROM rr_review_cells WHERE target_key = ? AND agent_key = ?",
                                                    (key, "xd-syn-1"))}
    assert states == {"failed"}


def test_a_running_all_agents_job_with_eight_workers_still_fits_the_wire(scale, monkeypatch):
    """반대 검토 MEDIUM 12(사용자 결정) — 잡이 도는 중이면 진행판의 잡 칸에 범위(scope — 전문가 359명 이름)와 워커 여덟의 신호가
    실린다. MCP 답(risk_get_coverage 기본 · risk_next_step)은 그 둘을 수와 앞 몇 이름으로 줄여 25,000자 안이다(REST 는 그대로다)."""
    from app import review_runner as rr
    from app import runner

    store, key, _job, roster = scale
    agents = [r["key"] for r in roster]
    job_id = rig.job(store, key, scope={"agents": agents})
    runner._set_job(store, job_id, "running")
    progress = rr.JobProgress(store, job_id, clock=lambda: 1_000_000)
    for n, agent in enumerate(agents[:8]):
        progress.worker(f"w{n}", agent_key=agent, purpose="review", unit_id=f"u-{n:012d}", call_kind="verdict",
                        variant="fwd", deck_id=f"d-{n}", started_at=1_000_000, last_frame_at=1_000_000,
                        last_event_at=1_000_000, last_step="attempt 1 · 판정 묶음을 읽는 중 " * 3)
    factories.act_as_delegate(monkeypatch, OWNER)
    rest = routes.coverage_payload(key, owner_sub=OWNER)["review"]["job"]
    assert len(rest["scope"]["agents"]) == 359 and len(rest["signal"]["workers"]) == 8      # REST 는 전부를 싣는다
    coverage = _call("risk_get_coverage", target_key=key)
    guide = _guide(store, key)
    assert srv._wire_chars(coverage) <= srv.MCP_RESULT_CHARS, srv._wire_chars(coverage)
    assert srv._wire_chars(guide) <= srv.MCP_RESULT_CHARS, srv._wire_chars(guide)        # 줄이지 않으면 27,921자였다
    for job in (coverage["review"]["job"], guide["facts"]["review_job"]):
        assert job["scope"].get("agents_n") == 359 and len(job["scope"]["agents"]) <= 5
        assert job["signal"].get("workers_n") == 8 and len(job["signal"]["workers"]) <= 3
    runner._set_job(store, job_id, "cancelled")
