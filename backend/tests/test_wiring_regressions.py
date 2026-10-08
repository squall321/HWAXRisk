# 배선 회귀 시험 — 대역 없이 실모듈로 도는 러너 한 바퀴·MCP planned 회수·G6 타깃 차단·events[] 검증·소유권(plan §6.7.2·§6.11·§3.2.2·§8.2.3)
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from app import common, config, engine_client, identity, narrative, planner, registry, routes, runner
from tests.conftest import REPO_ROOT

def _enc(pat: str) -> str:
    """저장 열 portal_pat_enc 는 Fernet 암호문이다(plan §8.2.7) — 픽스처도 같은 형식으로 넣는다."""
    return identity.encrypt_pat(pat).decode("ascii")

from app.errors import AppError

OWNER = "owner@example.com"
OTHER = "other@example.com"


# ---------------------------------------------------------------- 원장 준비
def _agents(sizes: dict[str, int]) -> list[dict]:
    return [
        {"key": f"{dom}-a{i:03d}", "domain": dom, "relevance": (n - i) / 100.0}
        for dom, n in sizes.items()
        for i in range(n)
    ]


def _seed(store, *, owner: str = OWNER, target_key: str = "diff:d1") -> str:
    now = common.now_epoch()
    store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
        " VALUES ('p1', ?, 'PRJ-1', '회귀 과제', ?, ?)", (owner, now, now))
    store.execute(
        "INSERT INTO rr_diffs(id, target_project_id, base_project_id, target_snapshot_id, base_snapshot_id,"
        " owner_sub, diff_version, diff_json, summary_text, created_at)"
        " VALUES ('d1', 'p1', 'p0', 's1', 's0', ?, '1.0', '{}', ?, ?)",
        (owner, "구조 3건·치수 2건이 바뀌었다.", now))
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, external_sync_json,"
        " report_ids_json, level, created_at, updated_at)"
        " VALUES (?, ?, 'diff', 'd1', 'p1', 'h1', '{}', '[]', 'C0', ?, ?)", (target_key, owner, now, now))
    planner.freeze_roster(store, target_key, owner,
                          _agents({"mech": 2, "sim": 2, "rel": 1, "xd": 1, "pcb": 1}))
    store.upsert_credential(owner, _enc("pat-secret"), "sub-1", owner, "[]", common.now_epoch() + 30 * 86400)
    return target_key


DECISION = "판정 본문.\n```json\n{\"schema\": \"risk_spec\"}\n```"


class RealEngine:
    """실모듈 경로 회귀용 엔진 대역 — SSE 캡처와 같은 모양만 돌려준다(LLM·네트워크 없음)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.owner_subs: list[str | None] = []

    def health(self) -> dict:
        return {"model": "glm-fake", "provider": "vllm", "endpoint_host": "127.0.0.1", "engine_rev": "rev1"}

    def run(self, delib_opts, *, owner_sub=None):
        self.calls.append(dict(delib_opts))
        self.owner_subs.append(owner_sub)
        keys = [p["key"] for p in delib_opts["personas"]]
        events: list[dict] = [{"kind": "personas", "personas": [{"key": k} for k in keys]}]
        for key in keys:
            events.append({"kind": "status", "step": f"{key} 조회: list_interfaces", "tool": "list_interfaces"})
            events.append({"kind": "evidence", "source": f"{key} · list_interfaces"})
        return {
            "decision_text": DECISION,
            "turns": [{"round": r, "persona": k, "say": f"{k} 라운드 {r}"} for r in (1, 2) for k in keys],
            "events": events, "conv_id": "conv-1", "report_id": 7,
            "call_path": "portal", "credential": "owner",
        }


# ---------------------------------------------------------------- 러너 정본 경로(대역 주입 금지)
def test_runner_interfaces_exist_on_real_modules():
    """운영 배선(main.py)은 실모듈을 그대로 쓴다 — 결손이 있으면 패널 1건도 완주하지 못한다."""
    assert runner.missing_interfaces() == []


def test_run_panel_completes_with_real_modules(risk_store, tmp_path):
    """narrative·registry 대역을 주입하지 않고 run_panel 을 한 바퀴 돌린다(plan §6.7.2)."""
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    job = runner.claim_next_job(risk_store, cfg)

    engine = RealEngine()
    out = runner.run_panel(risk_store, cfg, engine, job)

    assert out["status"] == "done" and out["parsed"] is True
    assert out["coverage"] == {"done": 5}
    # 러너 자격 (b) — 잡 owner 가 엔진까지 간다(plan §6.7 3단계).
    assert engine.owner_subs == [OWNER]
    # 패널 벽시계(plan §6.10.2)는 delib_opts 에 싣지 않는다 — 엔진의 timeout_s 는 LLM 호출 한 번의
    # 타임아웃이고 포털은 상한 초과를 422 로 막는다. 벽시계는 엔진 클라이언트가 스트림에서 잰다.
    assert "timeout_s" not in engine.calls[0] and config.panel_timeout_s(cfg) == 43200
    # 근거 항목마다 키가 엔진까지 간다 — 러너가 다시 끼우는 E0c 도 빠지지 않는다(엔진이 `[e:N|E3]` 으로 찍는다).
    assert [e["key"] for e in engine.calls[0]["evidence"]] == [
        "E0", "E0c", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9"]

    panel = risk_store.query_one(
        "SELECT status, risk_spec_parsed, quality_json FROM rr_panels WHERE id = ?", (out["panel_id"],))
    assert panel["status"] == "done" and panel["risk_spec_parsed"] == 1
    assert json.loads(panel["quality_json"])["credential"] == "owner"

    # 서술 저장이 실제로 앉았다 — 좌석 5 + 반대석 1.
    assert risk_store.query_one(
        "SELECT COUNT(*) AS n FROM rr_seat_opinions WHERE panel_id = ?", (out["panel_id"],))["n"] == 6
    assert planner.check_invariants(risk_store, target_key) == []
    assert risk_store.query_one("SELECT panels_done FROM rr_jobs WHERE id = ?", (job_id,))["panels_done"] == 1


def test_report_panel_line_names_the_seats_and_sums_their_tool_results(risk_store, tmp_path):
    """통합 보고서 [패널] 줄에 좌석 키와 tool_calls_ok 합이 실린다(plan §4.7.3 minutes 행).

    좌석은 seats_json 의 `key` 인데 `agent_key` 를 읽었고, tool_calls_ok 는 쓰는 곳이 없는 패널 quality 키에서
    읽었다. 그래서 패널이 몇 건이 돌든 이 줄은 `seats=[None,None,…] tool_calls_ok=None` 이었다 — 사람이 보는
    보고서에서 어느 좌석이 앉았고 도구 근거가 몇 건인지가 통째로 비어 있었다.
    """
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    out = runner.run_panel(risk_store, cfg, RealEngine(), runner.claim_next_job(risk_store, cfg))

    seats = [s["key"] for s in json.loads(risk_store.query_one(
        "SELECT seats_json FROM rr_panels WHERE id = ?", (out["panel_id"],))["seats_json"])]
    minutes = "\n".join(registry.build_report(risk_store, target_key)["blocks"]["minutes"]).split("\n")
    line = next(row for row in minutes if row.startswith("panel_no=1 "))
    assert len(seats) == 5 and f"seats=[{','.join(seats)}] " in line
    assert "tool_calls_ok=5 " in line                    # RealEngine — 좌석 다섯이 한 번씩 조회에 성공했다


def test_report_panel_line_says_unknown_when_the_seats_have_no_tool_ledger(risk_store, monkeypatch):
    """MCP 길(evidence_only)은 좌석 도구 호출을 세지 못한다 — 합을 0 으로 적으면 '안 썼다' 로 읽힌다."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    routes.complete_panel(panel["id"], engine="mcp", decision_text=DECISION, actor=OWNER, owner_sub=OWNER,
                          turns=[{"round": 1, "persona": s["key"], "say": "발언"} for s in panel["seats"]])

    minutes = "\n".join(registry.build_report(risk_store, target_key)["blocks"]["minutes"]).split("\n")
    line = next(row for row in minutes if row.startswith(f"panel_no={panel['panel_no']} "))
    assert "tool_calls_ok=None " in line and "seats=[None" not in line


def test_long_job_memo_reaches_the_seats_cut_and_the_panel_says_so(risk_store, tmp_path):
    """잡 메모가 M 상한을 넘으면 좌석은 앞부분만 받는다 — 그 사실이 잡 생성 응답과 패널 quality 에 남는다.

    실모듈 한 바퀴다. 브리프 10항목 + 좌석 계약 + 메모가 12칸을 정확히 채우므로 지금 편성으로는
    칸을 넘겨 빠지는 항목이 없다는 것도 같이 본다.
    """
    from app import brief

    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    memo = "배터리 모서리 간극부터 보라. " + "나" * 1483
    created = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg, user_memo=memo)
    job = runner.claim_next_job(risk_store, cfg)

    engine = RealEngine()
    out = runner.run_panel(risk_store, cfg, engine, job)
    sent = engine.calls[0]["evidence"]
    assert [e["key"] for e in sent] == list(brief.ITEM_ORDER) and len(sent) == planner.MAX_EVIDENCE
    assert "배터리 모서리 간극부터 보라." in sent[-1]["result"]

    quality = json.loads(risk_store.query_one(
        "SELECT quality_json FROM rr_panels WHERE id = ?", (out["panel_id"],))["quality_json"])
    assert quality["user_memo_cut"]["chars"] == 1500 and 200 < quality["user_memo_cut"]["kept"] < 1500
    assert "user_memo_cut" in quality["flags"] and "user_memo_cut" in out["quality_flags"]
    assert "evidence_dropped" not in quality["flags"] and "evidence_dropped" not in quality
    # 메모를 쓴 사람에게는 잡을 만드는 그 자리에서 알린다.
    assert created["user_memo_cut"] == quality["user_memo_cut"]


def test_short_job_memo_leaves_no_cut_record(risk_store, tmp_path):
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    created = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg,
                                user_memo="이 계면을 먼저 보라")
    out = runner.run_panel(risk_store, cfg, RealEngine(), runner.claim_next_job(risk_store, cfg))
    quality = json.loads(risk_store.query_one(
        "SELECT quality_json FROM rr_panels WHERE id = ?", (out["panel_id"],))["quality_json"])
    assert "user_memo_cut" not in created and "user_memo_cut" not in quality
    assert "user_memo_cut" not in quality["flags"]


def test_a_job_without_a_memo_does_not_borrow_another_jobs_memo(risk_store, tmp_path):
    """메모 없이 만든 잡의 패널에는 M 이 실리지 않는다 — 같은 타깃의 다른 잡 메모를 빌려 오지 않는다.

    러너가 '메모 없음' 을 None 으로 넘기면 브리프는 그것을 잡이 없는 길(미리보기·MCP)로 읽어 그 타깃의 가장
    최근 잡 메모를 찾는다. 앞 잡이 도는 중에 메모를 단 잡을 하나 더 만들면, 앞 잡의 좌석이 남의 메모를 받았다.
    """
    from app import brief

    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    now = {"t": common.now_epoch()}
    previous = common.set_clock(lambda: now["t"])
    try:
        first = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
        now["t"] += 60
        runner.create_job(risk_store, target_key, "B", owner_sub=OWNER, settings=cfg, user_memo="뒤에 만든 잡의 메모")
        job = runner.claim_next_job(risk_store, cfg)
        assert job["id"] == first and job["params"]["user_memo"] is None
        engine = RealEngine()
        out = runner.run_panel(risk_store, cfg, engine, job)
    finally:
        common.set_clock(previous)

    assert out["status"] == "done"
    assert "user_memo" not in [e["source"] for e in engine.calls[0]["evidence"]]
    assert "뒤에 만든 잡의 메모" not in json.dumps(engine.calls[0]["evidence"], ensure_ascii=False)
    # 잡이 없는 미리보기·MCP 길은 종전대로 그 타깃의 최근 잡 메모를 읽는다.
    preview = brief.build_brief(risk_store, target_key)
    assert "뒤에 만든 잡의 메모" in preview["evidence"][preview["keys"].index("M")]["result"]


def test_brief_payload_names_what_did_not_fit_the_slots(risk_store, monkeypatch):
    """REST·MCP 브리프도 칸을 넘겨 빠진 항목을 그 패널 옆에 적는다 — 호출자가 받은 근거를 전부라고 읽지 않게."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)

    whole = routes.brief_payload(target_key, "B", owner_sub=OWNER)["panels"][0]
    assert "evidence_dropped" not in whole                      # 지금 편성으로는 12칸 안이다
    assert len(whole["delib_opts"]["evidence"]) == 11           # 브리프 10 + 좌석 계약(이 타깃에는 메모가 없다)

    monkeypatch.setattr(planner, "MAX_EVIDENCE", 10)
    tight = routes.brief_payload(target_key, "B", owner_sub=OWNER)["panels"][0]
    assert tight["evidence_dropped"] == ["E9"]
    assert [e["key"] for e in tight["delib_opts"]["evidence"]] == [
        "E0", "E0c", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"]


def test_run_panel_rolls_seats_back_when_interface_is_missing(risk_store, tmp_path, monkeypatch):
    """결손 인터페이스로는 잡을 집지 않는다 — 패널 running·좌석 running 고착이 생기지 않는다."""
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    job = runner.claim_next_job(risk_store, cfg)

    monkeypatch.delattr(narrative, "persist_panel_result")
    out = runner.run_panel(risk_store, cfg, RealEngine(), job)

    assert out["status"] == "missing_interface"
    assert "narrative.persist_panel_result" in out["missing"]
    assert risk_store.query("SELECT id FROM rr_panels") == []
    assert {r["status"] for r in risk_store.query(
        "SELECT status FROM rr_coverage WHERE target_key = ?", (target_key,))} == {"pending"}
    assert risk_store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"] == "failed"


def test_daily_cap_applies_under_a_fixed_clock(risk_store, tmp_path):
    """'지금' 을 common.now_epoch 한 곳에서 읽는다 — 시계를 고정해도 일일 상한이 걸린다."""
    fixed = {"t": common.now_epoch()}
    previous = common.set_clock(lambda: fixed["t"])
    try:
        target_key = _seed(risk_store)
        cfg = dataclasses.replace(config.settings, data_dir=tmp_path, risk_daily_panel_cap=1)
        job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
        panel = planner.plan_next_panel(risk_store, target_key, "A", settings=cfg)
        risk_store.execute("UPDATE rr_panels SET status = 'done' WHERE id = ?", (panel["id"],))

        assert runner.claim_next_job(risk_store, cfg) is None
        row = risk_store.query_one("SELECT state, pause_reason FROM rr_jobs WHERE id = ?", (job_id,))
        assert (row["state"], row["pause_reason"]) == ("paused", "daily_cap")
    finally:
        common.set_clock(previous)


# ---------------------------------------------------------------- 앱 → 포털 본문 계약(plan §6.7.1 (A))
def _sse(*frames: tuple[str, dict]) -> str:
    return "".join(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n" for name, data in frames)


def _portal_engine(store, cfg, seen: dict, stream):
    """실 엔진 클라이언트(PortalPanelEngine)를 가짜 포털에 물린다 — 앱이 `/agent/chat` 에 보내는 본문을 붙잡는다."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == engine_client.CONVERSATIONS_PATH:
            return httpx.Response(200, json={"id": "conv-1"})
        if request.url.path != engine_client.CHAT_PATH:
            return httpx.Response(200, json={"model": "glm-fake"})          # agent-server /health
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(200, content=stream() if callable(stream) else stream,
                              headers={"content-type": "text/event-stream"})

    return engine_client.PortalPanelEngine(store, cfg, transport=httpx.MockTransport(handler))


def _panel_body(risk_store, tmp_path) -> dict:
    """러너 한 바퀴를 실모듈로 돌려, 포털이 실제로 받는 요청 본문을 돌려준다."""
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg, user_memo="이 계면을 먼저 보라")
    seen: dict = {}
    engine = _portal_engine(risk_store, cfg, seen, _sse(("delib", {"kind": "decision", "text": DECISION}),
                                                         ("done", {})))
    out = runner.run_panel(risk_store, cfg, engine, runner.claim_next_job(risk_store, cfg))
    assert out["status"] == "done", out
    return seen["body"]


def _portal_backend() -> Path | None:
    """포털 리포의 backend/ — 환경변수 HWAX_PORTAL_REPO 가 먼저고, 없으면 형제 리포(../HWAXPortal)다."""
    backend = Path(os.environ.get("HWAX_PORTAL_REPO") or REPO_ROOT.parent / "HWAXPortal") / "backend"
    return backend if (backend / "app" / "agent" / "routes.py").is_file() else None


# 포털의 요청 모델(ChatRequest · DelibOpts)로 본문을 검증한다. 선언 안 된 키는 포털이 에러 없이 버리므로
# (model_dump(exclude_none=True)) 통과 여부와 함께 '무엇이 떨어졌나' 도 돌려받는다.
_PORTAL_VALIDATE = """
import json, sys
from pydantic import ValidationError
from app.agent.routes import ChatRequest
body = json.load(sys.stdin)
try:
    request = ChatRequest.model_validate(body)
except ValidationError as exc:
    print(json.dumps({"errors": [[".".join(str(x) for x in e["loc"]), e["msg"]] for e in exc.errors()]}))
else:
    kept = request.delib_opts.model_dump(exclude_none=True)
    print(json.dumps({"errors": [], "dropped": sorted(set(body["delib_opts"]) - set(kept))}))
"""


def test_runner_never_sends_a_per_call_timeout_as_the_panel_wall_clock(risk_store, tmp_path):
    """포털 리포가 곁에 없어도 도는 판 — 문서로 적힌 경계만 본다(포털 `DelibOpts.timeout_s` 는 10~1800, 엔진도 같다).

    러너는 패널 벽시계 40분(2400)을 `timeout_s` 로 실어 보냈다. 포털은 그 값을 422 로 거절하므로 앱 → 포털
    길의 패널은 하나도 돌지 못하고 세 번째에 잡이 `engine_fail_streak` 로 죽는다.
    """
    opts = _panel_body(risk_store, tmp_path)["delib_opts"]
    assert "timeout_s" not in opts
    assert "question" not in opts and opts["chair_template"] == planner.CHAIR_TEMPLATE


def test_the_whole_request_body_is_accepted_by_the_portal_model(risk_store, tmp_path):
    """러너가 보내는 본문 전체를 포털의 실제 요청 모델에 넣어 본다 — 하나라도 경계를 넘으면 패널이 전부 422 다.

    포털 모델은 이 리포 것이 아니라 형제 리포에서 불러온다(같은 venv, 별도 프로세스 — 두 리포 다 최상위
    패키지 이름이 `app` 이다). 형제 리포가 없는 박스(앱 SIF 빌드 등)에서는 건너뛴다.
    """
    backend = _portal_backend()
    if backend is None:
        pytest.skip("포털 리포가 곁에 없다(HWAX_PORTAL_REPO 또는 ../HWAXPortal) — 문서 경계 시험만 돈다")
    body = _panel_body(risk_store, tmp_path)
    r = subprocess.run([sys.executable, "-c", _PORTAL_VALIDATE], input=json.dumps(body), cwd=backend,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        pytest.skip(f"포털 모델을 이 venv 로 불러오지 못했다 — {r.stderr.strip()[-300:]}")
    verdict = json.loads(r.stdout)
    assert verdict["errors"] == [], f"포털이 러너 본문을 422 로 거절한다 — {verdict['errors']}"
    # 통과해도 선언 안 된 키는 포털이 말없이 버린다 — 러너가 실은 손잡이가 엔진까지 가는지도 같이 본다.
    assert verdict["dropped"] == []


def test_a_panel_past_its_wall_clock_is_closed_without_charging_the_seats(risk_store, tmp_path):
    """벽시계를 넘긴 패널은 error 로 닫히되 좌석 재시도를 차감하지 않고 잡을 멈춘다(plan §6.10.2 · §6.7.2 9단계).

    엔진이 줄을 계속 보내는 한 읽기 타임아웃은 걸리지 않는다 — 벽시계를 앱이 재지 않으면 패널 하나가
    러너 자리와 그 타깃의 직렬 순서를 끝없이 붙든다. 다만 끊어도 엔진은 그 심의를 끝까지 돌린다 — 종전에는
    5초 뒤 같은 좌석을 다시 편성해 같은 심의가 엔진에 겹쳤고, 좌석은 제 탓이 아닌 일로 재시도를 잃었다.
    """
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    now = {"t": common.now_epoch()}
    previous = common.set_clock(lambda: now["t"])

    def slow_stream():
        yield _sse(("status", {"step": "심의 시작"})).encode()
        now["t"] += config.panel_timeout_s(cfg) + 1     # 12시간이 지났고, 엔진은 여전히 줄을 보낸다
        yield _sse(("status", {"step": "아직 도는 중"})).encode()
        yield _sse(("delib", {"kind": "decision", "text": DECISION}), ("done", {})).encode()

    try:
        out = runner.run_panel(risk_store, cfg, _portal_engine(risk_store, cfg, {}, slow_stream),
                               runner.claim_next_job(risk_store, cfg))
        assert out["status"] == "error" and out["error"].startswith("panel_timeout: 패널이 43200초"), out
        panel = risk_store.query_one(
            "SELECT status, error, conv_id, retry FROM rr_panels WHERE id = ?", (out["panel_id"],))
        assert panel["status"] == "error" and "HWAXRISK_PANEL_TIMEOUT_S" in panel["error"]
        # 엔진에서 계속 돌 수 있는 그 심의의 대화가 패널 행에 남는다 — 끊긴 뒤의 발언은 거기에만 있다.
        assert panel["conv_id"] == "conv-1" and "conv_id=conv-1" in panel["error"] and panel["retry"] == 0
        seats = risk_store.query("SELECT status, retry FROM rr_coverage WHERE target_key = ?", (target_key,))
        assert {(r["status"], r["retry"]) for r in seats} == {("pending", 0)}
        job = risk_store.query_one("SELECT state, pause_reason, error, state_by FROM rr_jobs WHERE id = ?", (job_id,))
        assert (job["state"], job["pause_reason"], job["state_by"]) == ("paused", None, "code:panel_timeout")
        assert job["error"] == panel["error"] + " — 잡을 멈췄다(좌석 재시도는 차감하지 않았다). 재개하면 이어 돈다"
        # 멈춘 잡은 다시 편성되지 않는다 — 엔진에 같은 심의가 겹치지 않는다. 사람이 재개하면 이어 돈다.
        assert runner.claim_next_job(risk_store, cfg) is None
        assert runner.resume_job(risk_store, job_id, by=OWNER)["state"] == "queued"
        resumed = runner.claim_next_job(risk_store, cfg)
        assert resumed["id"] == job_id and resumed["state"] == "running"
        assert risk_store.query_one("SELECT error FROM rr_jobs WHERE id = ?", (job_id,))["error"] is None
    finally:
        common.set_clock(previous)


def test_lost_streams_do_not_count_toward_the_engine_fail_streak(risk_store, tmp_path):
    """앱이 스트림을 놓은 패널은 연속 실패에 세지 않는다 — 진짜 엔진 실패 세 번이라야 잡이 죽는다."""
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]

    class Engine:
        def __init__(self) -> None:
            self.errors: list[Exception] = []

        def run(self, delib_opts, *, owner_sub=None):
            raise self.errors.pop(0)

    engine = Engine()
    engine.errors = [runner.EngineError("연결 끊김"),
                     runner.EngineStreamLost("engine_stream_cut", "스트림이 중간에 끊겼다", conv_id="conv-7"),
                     runner.EngineStreamLost("engine_silent", "포털 스트림이 조용했다" + " 긴 사유" * 400),
                     runner.EngineError("연결 끊김"), runner.EngineError("연결 끊김")]
    states = []
    for _ in range(5):
        job = runner.claim_next_job(risk_store, cfg)
        out = runner.run_panel(risk_store, cfg, engine, job)
        assert out["status"] == "error"
        row = risk_store.query_one("SELECT state, error FROM rr_jobs WHERE id = ?", (job_id,))
        worst = risk_store.query_one(
            "SELECT MAX(retry) AS n FROM rr_coverage WHERE target_key = ?", (target_key,))["n"]
        states.append((row["state"], (row["error"] or "").split(":")[0], worst))
        if row["state"] == "paused":
            # 사유가 아무리 길어도 '멈췄고 차감하지 않았다' 는 말이 잘리지 않는다.
            assert len(out["error"]) <= 400 and row["error"].endswith("재개하면 이어 돈다")
            runner.resume_job(risk_store, job_id, by=OWNER)

    # 진짜 실패 1 → 놓친 스트림 2(멈춤) → 진짜 실패 2·3 에서야 engine_fail_streak. 셋째 값은 좌석 재시도의
    # 최댓값이다 — 놓친 스트림에서는 오르지 않는다(올랐다면 셋째 패널에서 좌석이 skipped 로 굳었다).
    assert states == [("running", "", 1), ("paused", "engine_stream_cut", 1), ("paused", "engine_silent", 1),
                      ("running", "", 2), ("failed", "engine_fail_streak", 3)]
    lost = risk_store.query_one(
        "SELECT conv_id, retry FROM rr_panels WHERE target_key = ? AND error LIKE 'engine_stream_cut%'", (target_key,))
    assert (lost["conv_id"], lost["retry"]) == ("conv-7", 0)


# ---------------------------------------------------------------- 포털 429(동시 실행 자리 없음) 대기(plan §6.7.2 6단계)
class _Clock:
    """러너의 `time` 을 대신하는 가짜 시계 — sleep 은 자지 않고 monotonic 만 민다(대기 예산은 monotonic 으로 잰다)."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def __getattr__(self, name: str):
        return getattr(time, name)                  # 그 밖(localtime·time …)은 진짜 시계다


class _NoSlot:
    """자리가 끝내 나지 않는 엔진 — 부를 때마다 429 다."""

    def __init__(self) -> None:
        self.calls = 0

    def run(self, delib_opts, *, owner_sub=None):
        self.calls += 1
        raise runner.EngineBusy("포털 agent_semaphore 초과(429)")


BUSY_ERROR = ("engine_busy: 포털 동시 실행 자리(MAX_CONCURRENT_CHATS)를 3600초 기다렸지만 나지 않았다"
              "(HWAXRISK_ENGINE_BUSY_MAX_WAIT_S)")


def test_a_panel_that_never_got_an_engine_slot_pauses_the_job_without_charging(risk_store, tmp_path, monkeypatch):
    """포털이 429 만 주면 대기 예산(3600초)까지 기다리고, 다 쓰면 좌석을 차감하지 않고 잡을 멈춘다.

    429 는 '자리가 없다' 는 빠르고 분명한 답이다 — 좌석도 엔진도 실패하지 않았고 심의는 한 줄도 돌지 않았다.
    종전에는 30초 × 10회 = 5분 만에 `engine_busy` 를 엔진 실패로 닫아 좌석을 차감했다. 심의가 SSE 자리를 몇 시간씩
    쥐는 지금은 5분 넘게 자리가 안 나는 일이 드물지 않은데, 그런 패널 셋이면 한 번도 앉아 보지 못한 좌석이
    skipped 로 굳고 잡이 engine_fail_streak 로 죽었다. 예산은 자격 여유가 429 몫으로 잡아 둔 시간과 같은 값이다.
    """
    clock = _Clock()
    monkeypatch.setattr(runner, "time", clock)
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    engine = _NoSlot()

    for _ in range(3):
        out = runner.run_panel(risk_store, cfg, engine, runner.claim_next_job(risk_store, cfg))
        assert (out["status"], out["error"]) == ("error", BUSY_ERROR), out
        panel = risk_store.query_one("SELECT status, error, retry FROM rr_panels WHERE id = ?", (out["panel_id"],))
        assert (panel["status"], panel["error"], panel["retry"]) == ("error", BUSY_ERROR, 0)
        seats = risk_store.query("SELECT status, retry FROM rr_coverage WHERE target_key = ?", (target_key,))
        assert {(r["status"], r["retry"]) for r in seats} == {("pending", 0)}
        job = risk_store.query_one("SELECT state, pause_reason, error, state_by FROM rr_jobs WHERE id = ?", (job_id,))
        assert (job["state"], job["pause_reason"], job["state_by"]) == ("paused", None, "code:engine_busy")
        assert job["error"] == BUSY_ERROR + " — 잡을 멈췄다(좌석 재시도는 차감하지 않았다). 재개하면 이어 돈다"
        # 멈춘 잡은 집히지 않는다 — 사람이 재개해야 다시 자리를 묻는다.
        assert runner.claim_next_job(risk_store, cfg) is None
        runner.resume_job(risk_store, job_id, by=OWNER)

    # 패널마다 30초씩 정확히 예산만큼 기다렸다 — 마지막 물음 뒤에 한 번 더 자지 않는다(종전 루프는 잤다).
    assert set(clock.slept) == {30} and sum(clock.slept) == 3 * 3600 and engine.calls == 3 * 121
    assert runner._error_streak(risk_store, target_key) == 0
    # 기다리는 예산이 곧 자격 여유가 429 몫으로 잡은 시간이다 — 둘이 따로 놀면 기다리는 사이 PAT 가 만료된다.
    assert config.engine_busy_max_wait_s(cfg) == 3600
    assert config.credential_margin_s(cfg) == config.panel_timeout_s(cfg) + 3600 + config.CREDENTIAL_SLACK_S
    assert not hasattr(runner, "ENGINE_BUSY_MAX_RETRY")


def test_the_engine_slot_wait_follows_its_knobs_and_shows_on_the_board(risk_store, tmp_path, monkeypatch):
    """간격·예산은 손잡이를 따르고, 기다리는 동안 진행판(잡 행의 마지막 신호)에 '엔진 자리 대기 n회째' 가 보인다.

    종전에는 기다리는 내내 패널이 running 으로만 보였다 — 도는 것인지 자리를 기다리는 것인지 알 수 없었다.
    """
    clock = _Clock()
    monkeypatch.setattr(runner, "time", clock)
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path, risk_engine_busy_wait_s=7,
                              risk_engine_busy_max_wait_s=20)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    assert config.credential_margin_s(cfg) == config.panel_timeout_s(cfg) + 20 + config.CREDENTIAL_SLACK_S

    # 자리가 끝내 안 나면 예산(20초)에서 그친다 — 마지막 대기는 남은 만큼만이다.
    out = runner.run_panel(risk_store, cfg, _NoSlot(), runner.claim_next_job(risk_store, cfg))
    assert out["error"].startswith("engine_busy: 포털 동시 실행 자리(MAX_CONCURRENT_CHATS)를 20초 기다렸지만"), out
    assert clock.slept == [7, 7, 6]
    runner.resume_job(risk_store, job_id, by=OWNER)
    clock.slept.clear()
    seen: list[str] = []

    class Engine(RealEngine):
        def run(self, delib_opts, *, owner_sub=None, on_progress=None):
            signal = json.loads(risk_store.query_one(
                "SELECT progress_json FROM rr_jobs WHERE id = ?", (job_id,))["progress_json"])
            seen.append(signal["last_step"])
            if len(seen) <= 2:
                raise runner.EngineBusy("포털 agent_semaphore 초과(429)")
            return super().run(delib_opts, owner_sub=owner_sub)

    out = runner.run_panel(risk_store, cfg, Engine(), runner.claim_next_job(risk_store, cfg))
    assert out["status"] == "done", out
    assert seen == ["", "엔진 자리 대기 1회째", "엔진 자리 대기 2회째"] and clock.slept == [7, 7]


def test_a_shutdown_during_the_engine_slot_wait_does_not_charge_the_seats(risk_store, tmp_path):
    """자리를 기다리던 중에 앱이 내려가면 그 패널은 시작도 못 한 것이다 — 좌석을 차감하지 않고 잡도 멈추지 않는다."""
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    stop = threading.Event()
    stop.set()

    out = runner.run_panel(risk_store, cfg, _NoSlot(), runner.claim_next_job(risk_store, cfg), stop=stop)
    assert out["status"] == "error" and out["error"].startswith("stopped: "), out
    panel = risk_store.query_one("SELECT status, retry FROM rr_panels WHERE id = ?", (out["panel_id"],))
    assert (panel["status"], panel["retry"]) == ("error", 0)
    seats = risk_store.query("SELECT status, retry FROM rr_coverage WHERE target_key = ?", (target_key,))
    assert {(r["status"], r["retry"]) for r in seats} == {("pending", 0)}
    assert runner._error_streak(risk_store, target_key) == 0
    # 겹칠 심의가 없으니 멈추지 않는다 — 다시 뜨면 기동 복구가 이 잡을 줄 세운다(도는 패널이 없는 running 잡).
    assert risk_store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"] == "running"
    assert runner.recover_running_panels(risk_store) == {"recovered": 0, "paused": 0}
    assert risk_store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"] == "queued"


def test_retries_after_429_reuse_the_one_portal_conversation(risk_store, tmp_path, monkeypatch):
    """429 뒤의 재시도는 앞 시도가 만든 포털 대화를 다시 쓴다 — 패널 하나가 빈 대화를 시도 수만큼 남기지 않는다.

    엔진 클라이언트는 본문을 보내기 전에 대화부터 만든다. 종전에는 시도마다 새로 만들어, 429 를 열 번 받은 패널이
    빈 '[리스크심사] …' 대화 열 개를 남겼고 패널 행은 그중 어느 것도 가리키지 않았다. 예산이 한 시간이면 120개다.
    """
    monkeypatch.setattr(runner, "time", _Clock())
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    created: list[str] = []
    chats: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == engine_client.CONVERSATIONS_PATH:
            created.append(f"conv-{len(created) + 1}")
            return httpx.Response(200, json={"id": created[-1]})
        if request.url.path != engine_client.CHAT_PATH:
            return httpx.Response(200, json={"model": "glm-fake"})          # agent-server /health
        chats.append(json.loads(request.content.decode()).get("conversation_id"))
        if len(chats) <= 2:
            return httpx.Response(429, text="too many")
        return httpx.Response(200, content=_sse(("delib", {"kind": "decision", "text": DECISION}), ("done", {})),
                              headers={"content-type": "text/event-stream"})

    engine = engine_client.PortalPanelEngine(risk_store, cfg, transport=httpx.MockTransport(handler))
    out = runner.run_panel(risk_store, cfg, engine, runner.claim_next_job(risk_store, cfg))
    assert out["status"] == "done", out
    assert created == ["conv-1"] and chats == ["conv-1", "conv-1", "conv-1"]
    assert risk_store.query_one(
        "SELECT conv_id FROM rr_panels WHERE id = ?", (out["panel_id"],))["conv_id"] == "conv-1"


# ---------------------------------------------------------------- 취소·정지가 도는 패널에 닿는다(plan §6.7.2 · §0.6)
class _EndlessPings(httpx.SyncByteStream):
    """끝나지 않는 심의의 스트림 — ping 만 흘린다. 닫히면 그치고, 닫지 않아도 PINGS_MAX 에서 그친다(시험의 안전판)."""

    PINGS_MAX = 3000

    def __init__(self) -> None:
        self.sent = 0
        self.flowing = threading.Event()
        self.closed = threading.Event()

    def __iter__(self):
        while self.sent < self.PINGS_MAX and not self.closed.is_set():
            self.sent += 1
            if self.sent >= 3:
                self.flowing.set()
            time.sleep(0.005)
            yield b'event: ping\ndata: {"idle_s": 15}\n\n'

    def close(self) -> None:
        self.closed.set()


def _streaming_runner(store, tmp_path, monkeypatch):
    """실 러너 + 실 엔진 클라이언트를, ping 만 흘리는 가짜 포털에 물린다(동시 2). 취소는 프레임마다 묻게 한다."""
    monkeypatch.setattr(runner, "STOP_POLL_INTERVAL_S", 0)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path, risk_concurrency=2)
    streams: list[_EndlessPings] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == engine_client.CONVERSATIONS_PATH:
            return httpx.Response(200, json={"id": "conv-9"})
        if request.url.path != engine_client.CHAT_PATH:
            return httpx.Response(200, json={"model": "glm-fake"})          # agent-server /health
        streams.append(_EndlessPings())
        return httpx.Response(200, stream=streams[-1], headers={"content-type": "text/event-stream"})

    engine = engine_client.PortalPanelEngine(store, cfg, transport=httpx.MockTransport(handler))
    return runner.RiskRunner(store, cfg, engine), cfg, streams


def _free_slots(rr) -> int:
    held = 0
    while rr._sem.acquire(blocking=False):
        held += 1
    for _ in range(held):
        rr._sem.release()
    return held


@pytest.mark.parametrize("action", ["cancel", "pause"])
def test_cancel_or_pause_closes_the_panel_that_is_streaming(risk_store, tmp_path, monkeypatch, action):
    """취소·일시정지는 도는 패널의 스트림을 닫는다 — 러너 자리와 그 타깃의 직렬 순서가 곧바로 풀린다.

    종전에는 둘 다 패널 경계에서만 들었다. 벽시계가 12시간이 되면서, 잘못 낸 잡을 취소해도 그 패널이 최대 12시간
    러너 자리 하나와 타깃 순서를 붙들었다 — 같은 타깃의 새 잡은 그동안 집히지 않고, 그런 패널 둘이면 모든 타깃이
    선다. 닫힌 패널은 좌석 탓이 아니므로 차감하지 않는다. 엔진 쪽 심의는 계속 돌 수 있다(그 대화를 패널이 가리킨다).
    """
    target_key = _seed(risk_store)
    rr, cfg, streams = _streaming_runner(risk_store, tmp_path, monkeypatch)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    try:
        rr._panel_tick()
        worker = rr._workers[0]
        for _ in range(6000):                                   # 워커가 대화를 만들고 스트림을 열 때까지
            if streams:
                break
            time.sleep(0.01)
        assert streams and streams[0].flowing.wait(60), "패널이 스트림까지 가지 못했다"
        assert _free_slots(rr) == 1

        (runner.cancel_job if action == "cancel" else runner.pause_job)(risk_store, job_id, by=OWNER)
        worker.join(60)
        assert not worker.is_alive(), "취소·정지 뒤에도 워커가 스트림을 읽고 있다"
        # 스트림을 끝까지 읽고 끝난 것이 아니라 닫았다.
        assert streams[0].closed.is_set() and streams[0].sent < _EndlessPings.PINGS_MAX
    finally:
        for stream in streams:
            stream.closed.set()
        rr.stop()

    panel = risk_store.query_one(
        "SELECT status, error, retry, conv_id FROM rr_panels WHERE target_key = ?", (target_key,))
    assert (panel["status"], panel["retry"], panel["conv_id"]) == ("error", 0, "conv-9")
    said = "취소했다" if action == "cancel" else "일시정지했다"
    assert panel["error"].startswith(f"cancelled: 사용자가 잡을 {said} — 진행 중 패널을 닫았다 — 경과 ")
    assert "엔진 쪽 심의는 계속 돌 수 있다(conv_id=conv-9)" in panel["error"]
    seats = risk_store.query("SELECT status, retry FROM rr_coverage WHERE target_key = ?", (target_key,))
    assert {(r["status"], r["retry"]) for r in seats} == {("pending", 0)}
    assert _free_slots(rr) == 2 and runner._error_streak(risk_store, target_key) == 0

    job = risk_store.query_one("SELECT state, pause_reason FROM rr_jobs WHERE id = ?", (job_id,))
    if action == "cancel":
        # 닫으면서 사람의 취소를 덮지 않는다 — 다음 편성에서 cancelled 가 되고, 같은 타깃의 새 잡이 바로 집힌다.
        # (새 잡은 앞 잡이 cancelled 가 된 뒤에 만든다 — 같은 초에 만든 두 잡의 순서는 id 라 정해지지 않는다.)
        assert job["state"] == "cancelling" and runner.claim_next_job(risk_store, cfg) is None
        assert risk_store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"] == "cancelled"
        again = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
        assert runner.claim_next_job(risk_store, cfg)["id"] == again
    else:
        assert (job["state"], job["pause_reason"]) == ("paused", "user")
        assert runner.claim_next_job(risk_store, cfg) is None
        runner.resume_job(risk_store, job_id, by=OWNER)
        assert runner.claim_next_job(risk_store, cfg)["id"] == job_id


def test_a_cancel_is_heard_while_waiting_for_an_engine_slot(risk_store, tmp_path, monkeypatch):
    """엔진 자리를 기다리는 중의 취소도 듣는다 — 한 시간 예산을 다 기다린 뒤가 아니다. 좌석은 차감하지 않는다."""
    clock = _Clock()
    monkeypatch.setattr(runner, "time", clock)
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]

    class Engine(_NoSlot):
        def run(self, delib_opts, *, owner_sub=None):
            if self.calls == 2:
                runner.cancel_job(risk_store, job_id, by=OWNER)
            super().run(delib_opts, owner_sub=owner_sub)

    engine = Engine()
    out = runner.run_panel(risk_store, cfg, engine, runner.claim_next_job(risk_store, cfg))
    assert out["status"] == "error" and out["error"].startswith("cancelled: 사용자가 잡을 취소했다"), out
    assert engine.calls == 3 and clock.slept == [30, 30]          # 취소한 뒤로는 기다리지도 다시 묻지도 않는다
    panel = risk_store.query_one("SELECT status, retry FROM rr_panels WHERE id = ?", (out["panel_id"],))
    assert (panel["status"], panel["retry"]) == ("error", 0)
    seats = risk_store.query("SELECT status, retry FROM rr_coverage WHERE target_key = ?", (target_key,))
    assert {(r["status"], r["retry"]) for r in seats} == {("pending", 0)}
    # 사람의 취소를 paused(engine_busy)로 덮지 않는다.
    assert risk_store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"] == "cancelling"
    assert runner.claim_next_job(risk_store, cfg) is None
    assert risk_store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"] == "cancelled"


CHAIR_KNOB = "DELIB_TIMEOUT_S · 요청 timeout_s(상한 DELIB_TIMEOUT_MAX_S) · 의장 재호출 DELIB_CHAIR_RETRIES"
NO_DECISION_TEXT = "■ 의장 결정문 없음 — 좌석별 마지막 입장.\n• mech-a000: 간극이 좁다"


def test_a_chair_that_never_decided_pauses_the_job_and_keeps_the_pointers(risk_store, tmp_path):
    """의장이 끝내 결정문을 못 낸 패널 — 좌석은 차감하지 않고, 엔진이 남긴 것을 패널에 적고, 잡을 멈춘다.

    좌석은 전부 발언했고 실패한 것은 맨 끝의 의장 호출(대개 LLM 호출 한도)이다. 종전에는 엔진 실패로 세어 5초 뒤
    같은 좌석을 다시 편성했다 — 몇 시간짜리 패널이 같은 한도로 세 번 돌고 좌석은 skipped 로 굳어 잡이 죽는데,
    패널 행에는 대화도 보고서도 설정 이름도 남지 않았다. 러너는 timeout_s 를 싣지 않으므로 고칠 값은 엔진 박스의
    설정 하나다.
    """
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]
    chats: list[int] = []

    def stream() -> str:
        chats.append(1)
        # 엔진이 실제로 내는 순서다 — 발언 … decision{chair_failed} → outcome → result → error{code, message, knob} → done.
        return _sse(
            ("delib", {"kind": "turn", "round": 3, "persona": "mech-a000", "say": "간극이 좁다", "stance": "oppose"}),
            ("delib", {"kind": "decision", "text": NO_DECISION_TEXT, "chair_failed": True}),
            ("delib", {"kind": "outcome", "report_id": 4242}),
            ("result", {"type": "text", "content": NO_DECISION_TEXT}),
            ("error", {"code": "chair_failed", "knob": CHAIR_KNOB,
                       "message": "의장이 결정문을 내지 못했다 — LLM 호출이 1,800초 안에 끝나지 않았다. " + "긴 사유 " * 200}),
            ("done", {}))

    out = runner.run_panel(risk_store, cfg, _portal_engine(risk_store, cfg, {}, stream),
                           runner.claim_next_job(risk_store, cfg))
    assert out["status"] == "error", out
    panel = risk_store.query_one(
        "SELECT status, error, conv_id, report_id, retry, decision_text FROM rr_panels WHERE id = ?", (out["panel_id"],))
    # 사유가 아무리 길어도 손잡이 이름은 잘리지 않고 끝에 남는다. 코드가 맨 앞이라야 연속 실패 셈이 건너뛴다.
    assert panel["error"].startswith("chair_failed: 의장이 결정문을 내지 못했다") and len(panel["error"]) <= 400
    assert panel["error"].endswith(f" — 설정 {CHAIR_KNOB}")
    # 그 심의의 발언 전부는 포털 대화와 엔진이 저장한 보고서에 있다 — 패널이 둘 다 가리킨다.
    assert (panel["status"], panel["conv_id"], panel["report_id"], panel["retry"]) == ("error", "conv-1", 4242, 0)
    assert panel["decision_text"] == NO_DECISION_TEXT
    seats = risk_store.query("SELECT status, retry FROM rr_coverage WHERE target_key = ?", (target_key,))
    assert {(r["status"], r["retry"]) for r in seats} == {("pending", 0)}
    job = risk_store.query_one("SELECT state, pause_reason, error, state_by FROM rr_jobs WHERE id = ?", (job_id,))
    assert (job["state"], job["pause_reason"], job["state_by"]) == ("paused", None, "code:chair_failed")
    assert job["error"] == panel["error"] + (" — 잡을 멈췄다(좌석 재시도는 차감하지 않았다)."
                                              " 엔진 박스의 그 설정을 올린 뒤 재개하면 이어 돈다")
    # 멈춘 잡은 다시 편성되지 않는다 — 같은 몇 시간짜리 패널이 같은 한도로 곧바로 다시 돌지 않는다.
    assert runner.claim_next_job(risk_store, cfg) is None and len(chats) == 1
    assert runner.resume_job(risk_store, job_id, by=OWNER)["state"] == "queued"


def test_chair_failures_do_not_count_toward_the_engine_fail_streak(risk_store, tmp_path):
    """결정문 없이 끝난 패널은 연속 실패에 세지 않는다 — 그 앞뒤의 진짜 엔진 실패 셋이라야 잡이 죽는다."""
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]

    class Engine:
        def __init__(self) -> None:
            self.errors: list[Exception] = []

        def run(self, delib_opts, *, owner_sub=None):
            raise self.errors.pop(0)

    engine = Engine()
    engine.errors = [runner.EngineError("연결 끊김"),
                     runner.EngineNoDecision("chair_failed", "의장이 결정문을 내지 못했다"),
                     runner.EngineError("연결 끊김"), runner.EngineError("연결 끊김")]
    states = []
    for _ in range(4):
        out = runner.run_panel(risk_store, cfg, engine, runner.claim_next_job(risk_store, cfg))
        assert out["status"] == "error"
        row = risk_store.query_one("SELECT state, error FROM rr_jobs WHERE id = ?", (job_id,))
        worst = risk_store.query_one(
            "SELECT MAX(retry) AS n FROM rr_coverage WHERE target_key = ?", (target_key,))["n"]
        states.append((row["state"], (row["error"] or "").split(":")[0], worst))
        if row["state"] == "paused":
            # 엔진이 설정 이름을 싣지 않았으면(옛 엔진) 없는 설정을 가리키지 않는다.
            assert row["error"].endswith("잡을 멈췄다(좌석 재시도는 차감하지 않았다). 재개하면 이어 돈다")
            runner.resume_job(risk_store, job_id, by=OWNER)
    assert states == [("running", "", 1), ("paused", "chair_failed", 1), ("running", "", 2),
                      ("failed", "engine_fail_streak", 3)]


def test_a_cancel_made_while_the_stream_was_lost_is_not_overwritten(risk_store, tmp_path):
    """패널이 도는 사이 사람이 취소했으면 스트림을 놓쳐도 잡을 paused 로 덮지 않는다 — 다음 편성에서 cancelled 다."""
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)["job_id"]

    class Engine:
        def run(self, delib_opts, *, owner_sub=None):
            runner.cancel_job(risk_store, job_id, by=OWNER)
            raise runner.EngineStreamLost("panel_timeout", "패널이 벽시계를 넘겼다")

    job = runner.claim_next_job(risk_store, cfg)
    assert runner.run_panel(risk_store, cfg, Engine(), job)["status"] == "error"
    assert risk_store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"] == "cancelling"
    assert runner.claim_next_job(risk_store, cfg) is None
    assert risk_store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"] == "cancelled"


# ---------------------------------------------------------------- MCP 경로(plan §6.11)
def test_mcp_submit_closes_a_planned_panel(risk_store, monkeypatch):
    """planned 패널이 MCP 제출로 done 이 되고 좌석 원장이 일관되게 닫힌다(§6.11 L1·L2)."""
    import app.mcp_server as srv

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    assert panel is not None and panel["status"] == "planned"

    out = srv.risk_submit_panel_result(
        panel_id=panel["id"], engine="mcp", decision_text=DECISION,
        turns=[{"round": 1, "persona": s["key"], "say": "발언"} for s in panel["seats"]],
        report_id=None, actor=OWNER)

    assert "error" not in out, out
    assert out["engine"] == "mcp" and out["tool_mode"] == "evidence_only"
    row = risk_store.query_one(
        "SELECT status, engine, tool_mode, quality_json FROM rr_panels WHERE id = ?", (panel["id"],))
    assert row["status"] == "done"
    assert json.loads(row["quality_json"])["actor_verified"] is False
    assert planner.check_invariants(risk_store, target_key) == []
    assert {r["status"] for r in risk_store.query(
        "SELECT status FROM rr_coverage WHERE panel_id = ?", (panel["id"],))} <= {"done", "done_weak"}


def test_mcp_submit_rejects_other_owner(risk_store, monkeypatch):
    """actor 가 패널 owner 가 아니면 남의 원장을 닫을 수 없다."""
    import app.mcp_server as srv

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    assert srv.risk_submit_panel_result(
        panel_id=panel["id"], engine="mcp", decision_text=DECISION, turns=[],
        report_id=None, actor=OTHER)["error"] == "E404"
    assert risk_store.query_one(
        "SELECT status FROM rr_panels WHERE id = ?", (panel["id"],))["status"] == "planned"


def test_mcp_submit_records_the_evidence_that_never_reached_the_seats(risk_store, monkeypatch):
    """MCP 오케스트레이터(hwax-risk-review.js)가 '좌석에 못 간 근거' 를 제출에 실어 보내면 패널에 남는다.

    자리는 웹 러너가 엔진 카드를 옮겨 적는 곳과 같다(`quality_json.engine_withheld` · 같은 이름의 플래그).
    종전엔 도구에 받을 인자가 없어 그 목록이 워크플로 반환값에만 있었다 — 원장을 보는 사람은 그 패널의 좌석이
    브리프 일부만 보고 판정했다는 것을 알 길이 없었고, 모르는 인자를 얹어 보내면 도구가 말없이 버렸다.
    """
    import asyncio

    import app.mcp_server as srv

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    counted = "본문이 있는 근거 14건 중 뒤쪽 2건은 건수 상한(12건)을 넘겨 좌석에 주지 않았다."
    args = {
        "panel_id": panel["id"], "engine": "mcp", "decision_text": DECISION, "report_id": None, "actor": OWNER,
        "turns": [{"round": 1, "persona": s["key"], "say": "발언"} for s in panel["seats"]],
        # 워크플로가 돌려받는 모양 그대로다 — [{source, count, text}].
        "evidence_omitted": [
            {"source": "사전 근거 건수 초과", "count": 2, "text": counted},
            {"source": "사전 근거 예산 초과", "count": 1, "text": "가" * (routes.EVENT_FIELD_MAX + 100)},
        ],
    }

    def quality() -> dict:
        return json.loads(risk_store.query_one(
            "SELECT quality_json FROM rr_panels WHERE id = ?", (panel["id"],))["quality_json"])

    # 게이트웨이가 부르는 길(MCP 프로토콜)로 낸다 — 도구 스키마가 그 인자를 받아야 한다.
    asyncio.run(srv.mcp.call_tool("risk_submit_panel_result", args))
    assert risk_store.query_one("SELECT status FROM rr_panels WHERE id = ?", (panel["id"],))["status"] == "done"
    assert quality()["engine_withheld"] == [
        f"사전 근거 건수 초과 — {counted}",
        # 긴 사유는 거절하지 않고 러너 길과 같은 상한에서 자른다 — 사유 문장 때문에 패널 결과가 못 들어가면 안 된다.
        "사전 근거 예산 초과 — " + "가" * routes.EVENT_FIELD_MAX,
    ]
    assert quality()["flags"].count("engine_withheld") == 1
    # 이 신고는 events[] 가 아니다. events[] 로 읽으면 좌석 귀속을 다시 세어, 도구 경로가 없는 이 길의
    # used_tool 이 '모름(null)' 에서 '안 썼다(false)' 로 바뀐다.
    assert "attribution_rate" not in quality()
    assert {json.loads(r["quality_json"])["used_tool"] for r in risk_store.query(
        "SELECT quality_json FROM rr_seat_opinions WHERE panel_id = ?", (panel["id"],))} == {None}

    # 같은 카드를 REST events[] 로 낸 것과 줄 모양이 같다(표기는 한 벌이다).
    assert quality()["engine_withheld"][0] == runner.withheld_by_engine(
        [{"kind": "evidence", "source": "사전 근거 건수 초과", "included": False, "note": counted}])[0]

    # 인자 없이 다시 내도 지워지지 않는다.
    again = srv.risk_submit_panel_result(panel_id=panel["id"], engine="mcp", decision_text=DECISION,
                                         turns=args["turns"], report_id=None, actor=OWNER)
    assert "error" not in again, again
    assert len(quality()["engine_withheld"]) == 2 and quality()["flags"].count("engine_withheld") == 1


# ---------------------------------------------------------------- 재제출(plan §8.2.3·§6.11)
def test_resubmit_without_events_keeps_attribution_and_engine(risk_store, monkeypatch):
    """events[] 가 없으면 귀속 값과 기존 engine·tool_mode 를 그대로 둔다."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    keys = [s["key"] for s in panel["seats"]]
    events = [{"kind": "personas", "personas": [{"key": k} for k in keys]}]
    for key in keys:
        events.append({"kind": "status", "step": f"{key} 조회: list_interfaces"})
        events.append({"kind": "evidence", "source": f"{key} · list_interfaces"})

    first = routes.complete_panel(panel["id"], engine="mcp", decision_text=DECISION, turns=[],
                                  events=events, actor=OWNER, owner_sub=OWNER)
    assert first["attribution_rate"] == 1.0

    again = routes.complete_panel(panel["id"], engine="web", decision_text=DECISION, turns=[],
                                  events=None, actor=OWNER, actor_verified=True, owner_sub=OWNER)
    assert again["attribution_rate"] == 1.0          # 지워지지 않는다
    assert again["engine"] == "mcp" and again["tool_mode"] == "evidence_only"   # 재제출은 기존 값을 지킨다
    quality = json.loads(risk_store.query_one(
        "SELECT quality_json FROM rr_panels WHERE id = ?", (panel["id"],))["quality_json"])
    assert quality["attribution_rate"] == 1.0 and quality["extra_seats"] == []


def test_submitted_events_relay_what_the_engine_withheld(risk_store, monkeypatch):
    """회수 경로(REST)도 같다 — events[] 에 실려 온 '좌석에 주지 않았다' 카드를 패널에 남기고, 재제출이 지우지 않는다."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    events = [{"kind": "evidence", "source": "사전 근거 건수 초과", "included": False,
               "note": "근거 14건 중 12건만 실었다."}]

    routes.complete_panel(panel["id"], engine="mcp", decision_text=DECISION, turns=[],
                          events=events, actor=OWNER, owner_sub=OWNER)
    routes.complete_panel(panel["id"], engine="mcp", decision_text=DECISION, turns=[],
                          events=None, actor=OWNER, owner_sub=OWNER)

    quality = json.loads(risk_store.query_one(
        "SELECT quality_json FROM rr_panels WHERE id = ?", (panel["id"],))["quality_json"])
    assert quality["engine_withheld"] == ["사전 근거 건수 초과 — 근거 14건 중 12건만 실었다."]
    assert quality["flags"].count("engine_withheld") == 1


def test_spec_parse_failure_sets_flag(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    out = routes.complete_panel(panel["id"], engine="mcp", decision_text="펜스 없는 산문", turns=[],
                                actor=OWNER, owner_sub=OWNER)
    assert out["parsed"] is False
    quality = json.loads(risk_store.query_one(
        "SELECT quality_json FROM rr_panels WHERE id = ?", (panel["id"],))["quality_json"])
    assert "spec_parse_failed" in quality["flags"]


# ---------------------------------------------------------------- events[] 검증(plan §8.2.3)
def test_events_validation_and_truncation():
    with pytest.raises(AppError) as exc:
        routes._check_events([{"kind": "없는종류"}])
    assert exc.value.http_status == 422

    with pytest.raises(AppError) as exc:
        routes._check_events([{"kind": "status", "step": "x" * (routes.EVENT_FIELD_MAX + 1)}])
    assert exc.value.http_status == 422

    checked, truncated = routes._check_events([{"kind": "status", "step": "s"}] * (routes.EVENTS_MAX + 5))
    assert len(checked) == routes.EVENTS_MAX and truncated is True
    assert routes._check_events(None) == (None, False)


# ---------------------------------------------------------------- G6 차단(plan §3.2.2)
def test_create_target_is_blocked_by_g6(risk_store, monkeypatch):
    """단위가 어긋난 스냅샷(G6 fail) 위에는 심사 타깃을 열 수 없다 — diff 생성 409 와 같은 규칙."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    now = common.now_epoch()
    risk_store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
        " VALUES ('p1', ?, 'PRJ-1', '차단 과제', ?, ?)", (OWNER, now, now))
    risk_store.execute(
        "INSERT INTO rr_snapshots(id, owner_sub, project_id, ir_version, ir_hash, ir_json, source_ids_json,"
        " kinds_json, node_count, edge_count, created_at)"
        " VALUES ('sblk', ?, 'p1', '1.0', 'h1', '{}', '[]', ?, 0, 0, ?)",
        (OWNER, json.dumps(["mcad"]), now))
    risk_store.execute(
        "INSERT INTO rr_states(snapshot_id, owner_sub, state_json, feature_json, rule_hits_json,"
        " character_seed_json, gates_json, blocked, computed_at)"
        " VALUES ('sblk', ?, '{}', '{}', '[]', '[]', ?, 1, ?)",
        (OWNER, json.dumps({"G6": {"pass": False, "reason": "unit_scale"}}), now))

    ident = type("I", (), {"anonymous": False, "email": OWNER, "to_dict": lambda self: {"email": OWNER}})()
    with pytest.raises(AppError) as exc:
        routes.create_target(routes.TargetBody(kind="snap", ref_id="sblk", consent=True), ident=ident)
    assert (exc.value.code, exc.value.http_status) == ("gate_blocked", 409)
    assert exc.value.detail["reason"] == "unit_mismatch" and "target" in exc.value.detail["gates"]
    assert "G6" in exc.value.message
    assert risk_store.query("SELECT target_key FROM rr_targets") == []


# ---------------------------------------------------------------- 소유권(plan §8.2.3)
def test_anonymous_write_is_401_and_other_owner_is_404(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)

    anon = type("I", (), {"anonymous": True, "email": None, "to_dict": lambda self: {}})()
    with pytest.raises(AppError) as exc:
        routes.create_job(target_key, routes.JobBody(tier="A"), ident=anon)
    assert exc.value.http_status == 401

    other = type("I", (), {"anonymous": False, "email": OTHER, "to_dict": lambda self: {"email": OTHER}})()
    with pytest.raises(AppError) as exc:
        routes.get_coverage(target_key, ident=other)
    assert (exc.value.code, exc.value.http_status) == ("E404", 404)


# ---------------------------------------------------------------- registry 러너 접점
def test_merge_panel_counts_new_clusters(risk_store):
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    out = registry.merge_panel(risk_store, panel["id"])
    assert out["panel_id"] == panel["id"] and out["new_clusters"] == 0
    with pytest.raises(AppError):
        registry.merge_panel(risk_store, "없는패널")


# ---------------------------------------------------------------- 결정론(plan §3.1 원칙 1·§2.6.3)
def test_state_json_does_not_carry_the_clock(risk_store):
    """같은 (ir_hash, rule_version) 이면 rr_states.state_json 이 같다 — 시각은 열에만 남는다."""
    from app import state as state_module

    now = common.now_epoch()
    risk_store.execute(
        "INSERT INTO rr_snapshots(id, owner_sub, project_id, ir_version, ir_hash, ir_json, source_ids_json,"
        " kinds_json, node_count, edge_count, created_at)"
        " VALUES ('s1', ?, 'p1', '1.0', 'h1', '{}', '[]', ?, 0, 0, ?)", (OWNER, json.dumps(["mcad"]), now))
    ir = {"snapshot_id": "s1", "ir_hash": "h1", "project_id": "p1", "nodes": [], "edges": [],
          "dims_named": [], "warnings": [], "rollups": {}, "missing": {}, "versions": {}}
    first = state_module.build_state(ir, computed_at=1_000_000)
    second = state_module.build_state(ir, computed_at=2_000_000)
    state_module.save_state(risk_store, first, owner_sub=OWNER)
    stored_first = risk_store.query_one("SELECT state_json FROM rr_states WHERE snapshot_id = 's1'")["state_json"]
    state_module.save_state(risk_store, second, owner_sub=OWNER)
    row = risk_store.query_one("SELECT state_json, computed_at FROM rr_states WHERE snapshot_id = 's1'")
    assert row["state_json"] == stored_first
    assert row["computed_at"] == 2_000_000
    assert state_module.load_state(risk_store, "s1")["computed_at"] == 2_000_000


def test_hungarian_tiebreak_perturbation_is_not_separable():
    """선형 섭동은 어떤 완전배정에서도 합이 같아 동점을 못 깬다 — 제곱 섭동은 실제로 가른다."""
    from app import sameas

    nb = 2
    den = float(nb * nb + 1)
    def pert(i, j):
        return 1e-9 * ((i * nb + j) ** 2) / (den * den)

    identity = pert(0, 0) + pert(1, 1)
    swap = pert(0, 1) + pert(1, 0)
    assert identity != swap, "분리형 섭동이면 두 배정의 합이 같아 최적해가 유일하지 않다"

    cost = [[0.4 + pert(i, j) for j in range(2)] for i in range(2)]
    chosen = sameas._hungarian(cost)
    # 최적해가 유일하므로 솔버(scipy/동봉 JV)와 무관하게 같은 배정이 나온다.
    assert chosen == [0, 1] if identity < swap else chosen == [1, 0]
    assert sameas._hungarian(cost) == chosen


def test_model_changed_midrun_is_flagged(risk_store, tmp_path):
    """시작·종료 /health 의 model 이 다르면 quality.flags 에 남는다(D6, plan §6.7.2 7단계)."""
    target_key = _seed(risk_store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(risk_store, target_key, "A", owner_sub=OWNER, settings=cfg)
    job = runner.claim_next_job(risk_store, cfg)

    class DriftingEngine(RealEngine):
        def __init__(self) -> None:
            super().__init__()
            self.n = 0

        def health(self) -> dict:
            self.n += 1
            return {"model": f"glm-{self.n}", "provider": "vllm"}

    out = runner.run_panel(risk_store, cfg, DriftingEngine(), job)
    assert out["status"] == "done"
    row = risk_store.query_one(
        "SELECT quality_json, model_json FROM rr_panels WHERE id = ?", (out["panel_id"],))
    assert "model_changed_midrun" in json.loads(row["quality_json"])["flags"]
    model = json.loads(row["model_json"])
    assert model["model"] == "glm-1" and model["model_end"] == "glm-2"
    assert model["seat_contract_rev"] == runner.seat_contract_rev()
