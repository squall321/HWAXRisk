# 패널이 끝까지 닿는다 — 같은 타깃의 패널 여럿이 저장·회계·등록부까지 가는지 생산자 경유 입력과 실모듈 러너로 본다(WP1 S1·S2·S3)
"""입력은 손으로 쓴 원장 행이 아니라 생산자다 — 과제·스냅샷·타깃은 `tests/factories.py`, 좌석은 편성기, 좌석 상태는
`planner.apply_seat_results` 를 실제로 거친 것이다(반대 검토 WP1 P-01 의 3). 엔진만 대역이다(LLM·네트워크 없음).
"""
from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import httpx
import pytest

from app import common, config, identity, narrative, planner, runner
from app.errors import AppError
from tests import factories

OWNER = factories.OWNER
ADVERSARY = planner.ADVERSARY_KEY
DECISION = "판정 본문.\n```json\n{\"schema\": \"risk_spec\"}\n```"


class LedgerEngine:
    """포털 SSE 캡처와 같은 모양만 돌려주는 엔진 대역. 반대석은 실 엔진처럼 엔진이 스스로 앉힌다.

    `silent_first` 면 첫 패널의 첫 좌석이 한 마디도 하지 않는다(발언 0 좌석). `decisions` 는 패널마다의 결정문이다.
    """

    def __init__(self, *, silent_first: bool = False, decisions: list[str] | None = None,
                 fail_first: Exception | None = None, turn_events: bool = False) -> None:
        self.silent_first = silent_first
        self.turn_events = turn_events
        self.decisions = list(decisions or [])
        self.fail_first = fail_first
        self.calls: list[list[str]] = []

    def health(self) -> dict:
        return {"model": "glm-fake", "provider": "vllm", "endpoint_host": "127.0.0.1", "engine_rev": "rev1"}

    def run(self, delib_opts, *, owner_sub=None):
        keys = [p["key"] for p in delib_opts["personas"]]
        self.calls.append(keys)
        if self.fail_first is not None and len(self.calls) == 1:
            raise self.fail_first
        silent = {keys[0]} if self.silent_first and len(self.calls) == 1 else set()
        speakers = [k for k in keys if k not in silent] + [ADVERSARY]
        decision = self.decisions[len(self.calls) - 1] if len(self.calls) <= len(self.decisions) else DECISION
        return {
            "decision_text": decision,
            "turns": [{"round": r, "persona": k, "say": f"{k} 라운드 {r} 발언"} for r in (1, 2) for k in speakers],
            "events": [{"kind": "personas", "personas": [{"key": k} for k in keys + [ADVERSARY]]}]
            + ([{"kind": "turn", "persona": k, "round": r} for r in (1, 2) for k in keys] if self.turn_events else []),
            "conv_id": f"conv-{len(self.calls)}", "report_id": len(self.calls), "call_path": "portal",
            "credential": "owner",
        }


@pytest.fixture
def no_network(monkeypatch):
    """브리프의 필드 근거 호출이 dev 박스의 실 게이트웨이에 닿지 않게 연결 오류로 답한다.

    막은 요청의 URL 을 돌려준다 — 가드가 시험 끝까지 서 있었는지 시험이 본다. 이 가드는 같은 함수 범위의 monkeypatch 라
    `monkeypatch.undo()` 한 번에 함께 풀린다 — 스텁 하나를 걷을 때는 `monkeypatch.context()` 나 원래 함수를 다시 앉힌다.
    """
    refused: list[str] = []

    def _refused(*args, **_kwargs):
        refused.append(str(args[-1].url))
        raise httpx.ConnectError("시험은 외부를 부르지 않는다.", request=args[-1])

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refused)
    return refused


def _make_ledger(store, tmp_path, domains, per_domain: int) -> SimpleNamespace:
    project_id = factories.make_project(store)
    snapshot = factories.make_snapshot(store, project_id, factories.fixture_adapter_results(), label="DV1")
    target_key = factories.make_target(store, "snap", snapshot["snapshot_id"],
                                       agents=factories.agents(domains, per_domain=per_domain))
    store.upsert_credential(OWNER, identity.encrypt_pat("pat-secret").decode("ascii"), "sub-1", OWNER, "[]",
                            common.now_epoch() + 30 * 86400)
    return SimpleNamespace(store=store, target_key=target_key,
                           cfg=dataclasses.replace(config.settings, data_dir=tmp_path))


@pytest.fixture
def ledger(risk_store, tmp_path, no_network):
    """과제 → 스냅샷 → 타깃(로스터 15명) → 러너 자격. 반환 (store, target_key, cfg)."""
    return _make_ledger(risk_store, tmp_path, ("mech", "sim", "xd", "rel", "cam"), 3)


def _job(ledger) -> str:
    return runner.create_job(ledger.store, ledger.target_key, "C", owner_sub=OWNER, consent=True,
                             settings=ledger.cfg)["job_id"]


def _run(ledger, engine) -> dict:
    job = runner.claim_next_job(ledger.store, ledger.cfg)
    assert job is not None, "집을 잡이 없다"
    return runner.run_panel(ledger.store, ledger.cfg, engine, job)


def _opinions(store, target_key: str, agent_key: str) -> list[tuple]:
    return [(r["panel_no"], r["cycle"], r["origin"], r["turns_n"]) for r in store.query(
        "SELECT p.panel_no, o.cycle, o.origin, json_array_length(json_extract(o.opinion_json, '$.turns')) AS turns_n"
        " FROM rr_seat_opinions o JOIN rr_panels p ON p.id = o.panel_id"
        " WHERE o.target_key = ? AND o.agent_key = ? ORDER BY p.panel_no", (target_key, agent_key))]


def _coverage(store, target_key: str, agent_key: str) -> dict:
    return dict(store.query_one(
        "SELECT status, retry, cycle, panel_id, opinion_id FROM rr_coverage WHERE target_key = ? AND agent_key = ?",
        (target_key, agent_key)))


# ---------------------------------------------------------------- S1 — 같은 타깃의 두 번째 패널(R-1 · WP4 0b)
def test_three_panels_of_one_target_all_close_done(ledger):
    """반대석은 패널마다 앉는다 — 원장 밖 좌석의 회차는 100000 + panel_no 라 패널 셋이 서로 부딪치지 않는다."""
    _job(ledger)
    engine = LedgerEngine()
    outs = [_run(ledger, engine) for _ in range(3)]
    assert [o["status"] for o in outs] == ["done", "done", "done"], outs
    assert _opinions(ledger.store, ledger.target_key, ADVERSARY) == [
        (1, 100001, "adversary", 2), (2, 100002, "adversary", 2), (3, 100003, "adversary", 2)]
    assert planner.check_invariants(ledger.store, ledger.target_key) == []


# ---------------------------------------------------------------- S1 — 발언 0 원장 좌석(WP1 P-01)
def test_a_ledger_seat_that_never_spoke_sits_again_and_saves(ledger):
    """한 패널에서 한 마디도 못 한 원장 좌석은 의견 행을 남기지 않는다 — 다음 패널에 같은 회차로 다시 앉아 저장된다."""
    _job(ledger)
    engine = LedgerEngine(silent_first=True)
    first = _run(ledger, engine)
    silent = engine.calls[0][0]
    assert first["status"] == "done"
    assert _coverage(ledger.store, ledger.target_key, silent)["status"] == "pending"
    assert _opinions(ledger.store, ledger.target_key, silent) == []

    second = _run(ledger, engine)
    assert silent in engine.calls[1], "발언 0 좌석이 다음 패널에 다시 앉아야 이 시험이 선다"
    assert second["status"] == "done", second
    assert _opinions(ledger.store, ledger.target_key, silent) == [(2, 1, "primary", 2)]
    cov = _coverage(ledger.store, ledger.target_key, silent)
    assert cov["status"] in ("done", "done_weak") and cov["retry"] == 1
    assert planner.check_invariants(ledger.store, ledger.target_key) == []


def test_a_seat_the_stream_heard_speak_keeps_its_opinion_row(ledger):
    """발언 글(turns)이 비어도 스트림이 그 좌석의 발언 프레임을 봤으면 원장은 종결로 읽는다 — 그 좌석은 의견 행을 갖는다
    (종결 좌석에 opinion_id 가 없으면 원장 불변식 (3) 이 깨진다)."""
    _job(ledger)
    engine = LedgerEngine(silent_first=True, turn_events=True)
    first = _run(ledger, engine)
    quiet = engine.calls[0][0]
    assert first["status"] == "done"
    cov = _coverage(ledger.store, ledger.target_key, quiet)
    # 발언 글이 없으니 마지막 입장도 없다 — 종전처럼 기권(abstain)으로 종결된다.
    assert cov["status"] == "abstain" and cov["opinion_id"]
    assert _opinions(ledger.store, ledger.target_key, quiet) == [(1, 1, "primary", 0)]
    assert planner.check_invariants(ledger.store, ledger.target_key) == []


def test_an_old_zero_turn_row_does_not_block_the_reseat(ledger):
    """7248651 이 남긴 '발언 0 원장 행' 이 있는 DB 에서도 그 좌석이 다시 앉아 저장된다(옛 행은 지운다 — 담긴 것이 없다)."""
    _job(ledger)
    engine = LedgerEngine(silent_first=True)
    first = _run(ledger, engine)
    silent = engine.calls[0][0]
    if not _opinions(ledger.store, ledger.target_key, silent):
        # 지금 생산자는 이 행을 만들지 않는다 — 7248651 이 쓰던 모양 그대로 심는다(같은 패널의 다른 좌석 행에서 본뜬다).
        model = dict(ledger.store.query_one(
            "SELECT * FROM rr_seat_opinions WHERE panel_id = ? AND origin = 'primary' LIMIT 1", (first["panel_id"],)))
        body = json.loads(model["opinion_json"])
        opinion_id = narrative._opinion_id(first["panel_id"], silent, 1)
        body.update({"opinion_id": opinion_id, "agent_key": silent, "domain": planner.domain_of(silent), "turns": [],
                     "final_stance": "abstain", "raised_finding_ids": [], "contested_finding_ids": [],
                     "character_sentences": [], "excerpt_for_rag": "", "cited_refs": [],
                     "cited_refs_resolved": []})
        factories.seed_raw(ledger.store, "rr_seat_opinions", {
            **model, "opinion_id": opinion_id, "agent_key": silent, "domain": body["domain"], "cycle": 1,
            "opinion_json": common.canonical_json(body), "final_stance": "abstain", "excerpt_for_rag": "",
            "cited_refs_json": "[]", "raised_finding_ids_json": "[]"},
            reason="7248651 의 persist_panel_result 가 발언 0 원장 좌석에도 남기던 의견 행 — 지금 생산자는 만들지 않는다")
    assert _opinions(ledger.store, ledger.target_key, silent) == [(1, 1, "primary", 0)]

    second = _run(ledger, engine)
    assert silent in engine.calls[1]
    assert second["status"] == "done", second
    assert _opinions(ledger.store, ledger.target_key, silent) == [(2, 1, "primary", 2)]


def test_a_seat_that_spoke_in_a_panel_without_a_decision_keeps_its_words(ledger):
    """결정문 없이 끝난 패널의 좌석은 발언이 있어도 실패로 돌아간다 — 다시 앉을 때 앞 패널의 발언은 그 패널 기록에 남는다."""
    _job(ledger)
    engine = LedgerEngine(decisions=[""])
    first = _run(ledger, engine)
    seats = engine.calls[0]
    assert first["status"] == "done" and first["coverage"] == {"pending": 5}

    second = _run(ledger, engine)
    assert set(engine.calls[1]) == set(seats)
    assert second["status"] == "done", second
    for key in seats:
        # 앞 패널의 행은 원장 밖 회차(100000 + 1)로 비켜서 남고, 원장 회차 1 은 두 번째 패널의 것이다.
        (old, new) = _opinions(ledger.store, ledger.target_key, key)
        assert (old[:2], old[3], new[:2], new[3]) == ((1, 100001), 2, (2, 1), 2)
        assert old[2] == new[2] and old[2] in ("primary", "counter")
        assert _coverage(ledger.store, ledger.target_key, key)["status"] in ("done", "done_weak")
    assert planner.check_invariants(ledger.store, ledger.target_key) == []


def test_an_opinion_the_ledger_already_took_is_not_overwritten(ledger):
    """좌석 원장이 받은 의견(그 좌석의 결과)과 같은 회차를 다른 패널이 쓰려 하면 좌석 이름을 단 409 로 멈춘다 — 덮지 않는다."""
    _job(ledger)
    engine = LedgerEngine(fail_first=runner.EngineError("엔진이 끊겼다"))
    first = _run(ledger, engine)
    assert first["status"] == "error"
    second = _run(ledger, engine)
    assert second["status"] == "done" and set(engine.calls[1]) == set(engine.calls[0])
    taken = {key: _opinions(ledger.store, ledger.target_key, key) for key in engine.calls[0]}

    with pytest.raises(AppError) as exc:
        narrative.persist_panel_result(
            ledger.store, first["panel_id"], decision_text=DECISION, spec=None,
            turns=[{"round": 1, "persona": k, "say": "늦게 온 발언"} for k in engine.calls[0]])
    assert exc.value.code == "seat_opinion_conflict" and exc.value.http_status == 409
    assert any(key in exc.value.message for key in engine.calls[0])
    assert {key: _opinions(ledger.store, ledger.target_key, key) for key in engine.calls[0]} == taken


# ---------------------------------------------------------------- S3 — 브리프 조립 실패는 좌석 탓이 아니다(WP1 R-4 · P-13)
def _job_row(store, job_id: str) -> dict:
    return dict(store.query_one("SELECT state, state_by, error FROM rr_jobs WHERE id = ?", (job_id,)))


def _seat_retries(store, target_key: str) -> dict[str, int]:
    return {r["agent_key"]: int(r["retry"] or 0) for r in store.query(
        "SELECT agent_key, retry FROM rr_coverage WHERE target_key = ? AND status != 'deferred'", (target_key,))}


def test_a_brief_that_cannot_be_built_pauses_the_job_without_charging(ledger, monkeypatch):
    """브리프 조립은 결정론이다 — 같은 입력이면 같은 자리에서 다시 멈춘다. 좌석을 깎지 않고 잡을 멈춘다(사람이 고친 뒤 재개)."""
    from app.errors import AppError as _AppError

    def lint_fails(*_args, **_kwargs):
        raise _AppError("E500", "브리프 판단어 린터 위반 1건", http_status=500)

    monkeypatch.setattr(narrative, "prior_evidence", lint_fails)
    job_id = _job(ledger)
    engine = LedgerEngine()
    for attempt in range(3):
        out = _run(ledger, engine)
        assert out["status"] == "error" and out["error"].startswith("brief_error: AppError"), out
        job = _job_row(ledger.store, job_id)
        assert job["state"] == "paused" and job["state_by"] == "code:brief_error", job
        assert "결정론" in job["error"]
        assert runner.claim_next_job(ledger.store, ledger.cfg) is None       # 멈춘 잡은 집지 않는다
        runner.resume_job(ledger.store, job_id, by=OWNER)
    assert set(_seat_retries(ledger.store, ledger.target_key).values()) == {0}
    assert engine.calls == []                                              # 엔진은 한 번도 불리지 않았다
    assert planner.check_invariants(ledger.store, ledger.target_key) == []


def test_a_passing_brief_failure_retries_and_pauses_on_the_third(ledger, monkeypatch, no_network):
    """잠금·연결 같은 일시 장애는 멈추지 않고 다시 편성한다 — 좌석은 깎지 않고, 같은 타깃에서 세 번 이어지면 그때 멈춘다."""
    import sqlite3

    def locked(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    job_id = _job(ledger)
    engine = LedgerEngine()
    states = []
    # 장애 스텁만 걷는다 — monkeypatch.undo() 는 같은 범위의 no_network 가드까지 풀어 마지막 패널이 실 게이트웨이를 불렀다.
    with monkeypatch.context() as patch:
        patch.setattr(narrative, "prior_evidence", locked)
        for attempt in range(3):
            out = _run(ledger, engine)
            assert out["status"] == "error" and out["error"].startswith("brief_retry: OperationalError"), out
            states.append(_job_row(ledger.store, job_id)["state"])
    assert states == ["running", "running", "paused"]
    assert _job_row(ledger.store, job_id)["state_by"] == "code:brief_retry"
    assert set(_seat_retries(ledger.store, ledger.target_key).values()) == {0}

    # 장애가 풀렸다 — 재개하면 이어 돈다.
    runner.resume_job(ledger.store, job_id, by=OWNER)
    assert _run(ledger, engine)["status"] == "done"
    # 브리프의 필드 근거가 게이트웨이 도구 지도를 물었다 — 그 요청은 가드에 막혀야 한다(시험 PAT 로 실 게이트웨이를 부르지 않는다).
    assert any(url.endswith("/tools-map") for url in no_network), no_network


# ---------------------------------------------------------------- S2 — 결과 선저장 · persist_error · 다시 저장 · 재기동 복구(WP1 R-2 · R-5 · P-05 · P-18)
def _panel(store, panel_id: str) -> dict:
    return dict(store.query_one(
        "SELECT status, error, decision_text, conv_id, report_id, result_gz, result_hash, quality_json"
        " FROM rr_panels WHERE id = ?", (panel_id,)))


def _seats_of(store, panel_id: str) -> list[str]:
    return [s["key"] for s in json.loads(store.query_one(
        "SELECT seats_json FROM rr_panels WHERE id = ?", (panel_id,))["seats_json"])]


def _seat_rows(store, target_key: str, keys) -> dict[str, tuple]:
    return {k: (r["status"], r["retry"], r["panel_id"]) for k in keys for r in [store.query_one(
        "SELECT status, retry, panel_id FROM rr_coverage WHERE target_key = ? AND agent_key = ?", (target_key, k))]}


@pytest.fixture
def merge_breaks(monkeypatch):
    """등록부 병합이 터진다(디스크·잠금 같은 저장 단계의 실패 자리) — 되돌리면 낫는다."""
    from app import registry

    real = registry.merge_panel
    state = {"broken": True}

    def merge_panel(store, panel_id):
        if state["broken"]:
            raise RuntimeError("디스크가 찼다")
        return real(store, panel_id)

    monkeypatch.setattr(registry, "merge_panel", merge_panel)
    return state


def test_a_save_that_fails_closes_the_panel_and_keeps_the_engine_result(ledger, merge_breaks):
    """저장이 터져도 패널은 running 에 굳지 않는다 — 엔진 결과는 패널에 먼저 저장되고, 좌석은 깎이지 않고, 잡은 멈춘다."""
    job_id = _job(ledger)
    out = _run(ledger, LedgerEngine())
    assert out["status"] == "error" and out["error"].startswith("persist_error: RuntimeError: 디스크가 찼다"), out
    panel = _panel(ledger.store, out["panel_id"])
    assert panel["status"] == "error" and panel["result_gz"] is not None and len(panel["result_hash"]) == 12
    assert panel["decision_text"] == DECISION and panel["conv_id"] == "conv-1" and panel["report_id"] == 1
    keys = _seats_of(ledger.store, out["panel_id"])
    assert set(_seat_rows(ledger.store, ledger.target_key, keys).values()) == {("pending", 0, None)}
    # 반쪽 저장이 없다 — 의견·원자는 한 트랜잭션이라 같이 물러났다.
    assert ledger.store.query_one("SELECT COUNT(*) AS n FROM rr_seat_opinions WHERE panel_id = ?",
                                  (out["panel_id"],))["n"] == 0
    job = _job_row(ledger.store, job_id)
    assert job["state"] == "paused" and job["state_by"] == "code:persist_error"
    assert f"/api/panels/{out['panel_id']}/repersist" in job["error"] and "차감하지 않았다" in job["error"]
    stored = json.loads(__import__("gzip").decompress(panel["result_gz"]))
    assert stored["job_id"] == job_id and stored["decision_text"] == DECISION and len(stored["turns"]) == 12
    assert stored["model_json"]["model"] == "glm-fake" and "brief_hash" in stored["frozen"]


def test_repersist_after_the_cause_is_fixed_closes_the_panel_done(ledger, merge_breaks):
    """원인을 고친 뒤 다시 저장하면 처음 저장과 같은 길(귀속·원장·등록부·품질)로 done 이 된다. 잡 상태는 건드리지 않는다."""
    job_id = _job(ledger)
    out = _run(ledger, LedgerEngine())
    merge_breaks["broken"] = False
    again = runner.repersist_panel(ledger.store, ledger.cfg, out["panel_id"])
    assert again["status"] == "done" and again["panel_id"] == out["panel_id"]
    panel = _panel(ledger.store, out["panel_id"])
    assert panel["status"] == "done" and panel["error"] is None
    assert json.loads(panel["quality_json"])["brief_hash"]
    keys = _seats_of(ledger.store, out["panel_id"])
    assert {s for s, _, _ in _seat_rows(ledger.store, ledger.target_key, keys).values()} <= {"done", "done_weak"}
    assert _opinions(ledger.store, ledger.target_key, ADVERSARY) == [(1, 100001, "adversary", 2)]
    job = dict(ledger.store.query_one("SELECT state, panels_done FROM rr_jobs WHERE id = ?", (job_id,)))
    assert job == {"state": "paused", "panels_done": 1}
    assert planner.check_invariants(ledger.store, ledger.target_key) == []


def test_a_repersist_that_fails_again_leaves_the_seats_free(ledger, merge_breaks):
    """다시 저장이 또 터지면 좌석 재점유까지 같이 물러난다 — 좌석이 running 에 굳어 편성기가 못 집는 일이 없다(P-05)."""
    _job(ledger)
    out = _run(ledger, LedgerEngine())
    with pytest.raises(AppError) as exc:
        runner.repersist_panel(ledger.store, ledger.cfg, out["panel_id"])
    assert exc.value.code == "persist_failed" and exc.value.http_status == 422 and "디스크가 찼다" in exc.value.message
    keys = _seats_of(ledger.store, out["panel_id"])
    assert set(_seat_rows(ledger.store, ledger.target_key, keys).values()) == {("pending", 0, None)}
    assert _panel(ledger.store, out["panel_id"])["status"] == "error"


def test_repersist_refuses_when_the_seats_have_moved_on(ledger, merge_breaks):
    """좌석이 다른 패널로 간 뒤에는 다시 저장하지 않는다 — 그 좌석의 의견이 남의 패널 이름으로 들어간다(R-5).

    좌석은 다시 저장을 포기한 뒤에야 다른 패널로 간다 — 그 전에는 재개해도 그 타깃을 편성하지 않는다(RR-ADV-1).
    """
    job_id = _job(ledger)
    out = _run(ledger, LedgerEngine())
    merge_breaks["broken"] = False
    runner.abandon_repersist(ledger.store, out["panel_id"])
    runner.resume_job(ledger.store, job_id, by=OWNER)
    engine = LedgerEngine()
    assert _run(ledger, engine)["status"] == "done"
    with pytest.raises(AppError) as exc:
        runner.repersist_panel(ledger.store, ledger.cfg, out["panel_id"])
    assert exc.value.code == "seats_moved" and exc.value.http_status == 409
    assert {m["agent_key"] for m in exc.value.detail["moved"]} & set(engine.calls[0])
    assert _panel(ledger.store, out["panel_id"])["result_gz"] is not None


# ---------------------------------------------------------------- 다시 저장을 기다리는 타깃은 편성하지 않는다(RR-ADV-1)
def test_another_job_on_the_target_waits_for_the_repersist(ledger, merge_breaks):
    """같은 타깃의 다른 잡이 그 좌석을 가져가면 저장해 둔 결과는 영영 다시 앉지 못한다(seats_moved) — 다시 저장(또는 포기)
    전에는 그 타깃의 잡을 집지 않는다. 잡은 queued 로 남고(완료로 닫지 않는다) 까닭이 잡 행에 적힌다. 다시 저장하면 이어 돈다."""
    _job(ledger)
    out = _run(ledger, LedgerEngine())
    second = _job(ledger)                                            # 웹의 잡 만들기에는 중복 검사가 없다
    merge_breaks["broken"] = False                                   # 원인은 고쳤고 사람은 아직 다시 저장하지 않았다
    assert runner.claim_next_job(ledger.store, ledger.cfg) is None
    waiting = _job_row(ledger.store, second)
    assert waiting["state"] == "queued" and waiting["error"].startswith("repersist_pending"), waiting
    assert f"/api/panels/{out['panel_id']}/repersist" in waiting["error"] and "discard=1" in waiting["error"]

    assert runner.repersist_panel(ledger.store, ledger.cfg, out["panel_id"])["status"] == "done"
    engine = LedgerEngine()
    assert _run(ledger, engine)["status"] == "done"
    assert not set(engine.calls[0]) & set(_seats_of(ledger.store, out["panel_id"]))   # 다시 앉은 좌석은 다시 돌지 않는다
    assert _job_row(ledger.store, second)["error"] is None                            # 집으면 기다린 까닭을 지운다


def test_after_a_restart_a_queued_job_on_the_target_waits_for_the_repersist(ledger, monkeypatch):
    """재기동 복구는 running 잡만 멈춘다 — 같은 타깃에 줄 서 있던 잡이 곧바로 그 좌석을 가져가면 안 된다. 복구 문구도
    '재개하면 이어 돈다' 가 아니라 다시 저장(또는 포기) 먼저다."""
    jobs = (_job(ledger), _job(ledger))

    def crash(*_args, **_kwargs):
        raise _Crash()

    with monkeypatch.context() as patch, pytest.raises(_Crash):
        patch.setattr(runner, "_complete_panel", crash)
        _run(ledger, LedgerEngine())
    runner.recover_running_panels(ledger.store)
    panel_id = ledger.store.query_one("SELECT id FROM rr_panels WHERE error LIKE 'persist_error%'")["id"]
    assert runner.claim_next_job(ledger.store, ledger.cfg) is None
    rows = {job_id: _job_row(ledger.store, job_id) for job_id in jobs}
    assert sorted(r["state"] for r in rows.values()) == ["paused", "queued"]
    paused = next(r for r in rows.values() if r["state"] == "paused")
    assert "재개하면 이어 돈다" not in paused["error"] and "다시 저장(또는 포기) 먼저" in paused["error"], paused
    assert f"/api/panels/{panel_id}/repersist" in paused["error"]

    assert runner.repersist_panel(ledger.store, ledger.cfg, panel_id)["status"] == "done"
    assert _run(ledger, LedgerEngine())["status"] == "done"          # 다시 저장한 뒤에는 줄 선 잡이 이어 돈다


def test_resuming_before_the_repersist_does_not_take_the_seats(ledger, merge_breaks):
    """화면의 복구 버튼(재개)이나 잡 문구대로 재개해도 결과를 잃지 않는다 — 잡은 줄에서 기다리고, 다시 저장하면 이어 돈다."""
    job_id = _job(ledger)
    out = _run(ledger, LedgerEngine())
    assert "다시 저장(또는 포기) 먼저" in _job_row(ledger.store, job_id)["error"]
    merge_breaks["broken"] = False
    runner.resume_job(ledger.store, job_id, by=OWNER)
    assert runner.claim_next_job(ledger.store, ledger.cfg) is None
    assert runner.repersist_panel(ledger.store, ledger.cfg, out["panel_id"])["status"] == "done"
    assert _run(ledger, LedgerEngine())["status"] == "done"


def test_abandoning_the_repersist_frees_the_target_and_keeps_the_result(ledger, merge_breaks):
    """같은 결과로 다시 저장이 되풀이해 실패하면 사람이 포기할 길이 있어야 한다 — 없으면 그 타깃은 영영 멈춘다.
    포기는 error 를 'persist_abandoned' 로 바꾸고 감사 행을 남긴다. 엔진 결과는 패널에 남고, 좌석은 다음 패널에서 다시 돈다."""
    from app import routes

    job_id = _job(ledger)
    out = _run(ledger, LedgerEngine())
    with pytest.raises(AppError) as exc:
        runner.repersist_panel(ledger.store, ledger.cfg, out["panel_id"])      # 원인이 그대로라 또 실패한다
    assert exc.value.code == "persist_failed"
    with factories.routes_store(ledger.store):
        with pytest.raises(AppError) as exc:
            routes.post_panel_repersist(out["panel_id"], discard=True, ident=factories.ident("stranger@example.com"))
        assert exc.value.http_status == 404
        body = routes.post_panel_repersist(out["panel_id"], discard=True, ident=factories.ident(OWNER))
    assert body["status"] == "error" and body["abandoned"] is True
    assert body["error"].startswith("persist_abandoned:") and "디스크가 찼다" in body["error"]
    panel = _panel(ledger.store, out["panel_id"])
    assert panel["error"] == body["error"] and panel["result_gz"] is not None and panel["decision_text"] == DECISION
    audit = ledger.store.query_one("SELECT actor, scope, action FROM rr_audit WHERE subject_id = ?", (out["panel_id"],))
    assert dict(audit) == {"actor": OWNER, "scope": "panel", "action": "panel.repersist_discard"}
    assert runner._uncharged_code(body["error"]) == "persist_abandoned"        # 좌석·엔진 탓이 아니다(연속 실패에 세지 않는다)
    with pytest.raises(AppError) as exc:
        runner.abandon_repersist(ledger.store, out["panel_id"])               # 이미 포기했다
    assert (exc.value.code, exc.value.http_status) == ("not_awaiting_repersist", 409)

    merge_breaks["broken"] = False
    runner.resume_job(ledger.store, job_id, by=OWNER)
    engine = LedgerEngine()
    assert _run(ledger, engine)["status"] == "done"
    assert set(engine.calls[0]) == set(_seats_of(ledger.store, out["panel_id"]))   # 같은 좌석이 다시 돌았다
    assert planner.check_invariants(ledger.store, ledger.target_key) == []


def test_the_brief_preview_does_not_plan_over_a_result_that_awaits_repersist(ledger, merge_breaks):
    """웹 브리프 탭(GET /targets/{key}/brief)은 planned 패널이 없으면 그 자리에서 편성한다 — 그 편성이 다시 저장을 기다리는
    패널의 좌석을 가져가면 탭을 열기만 해도 결과를 잃는다. 기다리는 동안은 편성하지 않고 그 까닭을 싣는다."""
    from app import routes

    _job(ledger)
    out = _run(ledger, LedgerEngine())
    merge_breaks["broken"] = False
    with factories.routes_store(ledger.store):
        brief = routes.get_brief(ledger.target_key, tier="C", ident=factories.ident(OWNER))
    assert brief["panels"] == []
    assert [p["panel_id"] for p in brief["repersist_pending"]] == [out["panel_id"]]
    assert runner.repersist_panel(ledger.store, ledger.cfg, out["panel_id"])["status"] == "done"


def test_the_guide_says_repersist_first_while_a_result_waits(ledger, merge_breaks):
    """길잡이(risk_next_step)가 '재개하면 이어 돈다' 만 말하면 그대로 따른 사람이 결과를 잃었다 — 다시 저장(또는 포기)
    먼저이고 그 전에는 재개해도 이 타깃은 기다린다고 말한다. 다음 걸음의 맨 앞은 다시 저장(risk_repersist_panel)이고
    막힘의 고칠 곳에 그 도구와 웹 REST 경로를 함께 싣는다."""
    from app import entry, routes

    job_id = _job(ledger)
    out = _run(ledger, LedgerEngine())
    project_id = ledger.store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?",
                                        (ledger.target_key,))["project_id"]
    with factories.routes_store(ledger.store):
        routes.add_source(project_id, routes.SourceBody(kind="mcad", ref={"stepforge_project_id": "SF-1"}),
                          ident=factories.ident(OWNER))
        guide = entry.next_step(factories.ident(OWNER), project_id=project_id)
    assert guide["where"] == "paused", guide
    first, step = guide["next"][:2]
    assert first["tool"] == "risk_repersist_panel" and first["args"] == {"panel_id": out["panel_id"]} and first["write"]
    assert step["tool"] == "risk_job_action" and step["args"] == {"job_id": job_id, "action": "resume"}
    assert "다시 저장(또는 포기) 먼저" in step["why"] and "재개해도 이 타깃은 기다린다" in step["why"], step
    blocked = {b["code"]: b for b in guide["blocked"]}
    assert "risk_repersist_panel" in blocked["repersist_pending"]["fix"]
    assert f"/api/panels/{out['panel_id']}/repersist" in blocked["repersist_pending"]["fix"]
    assert blocked["repersist_pending"]["panels"] == [out["panel_id"]]


def test_claude_entry_repersists_the_waiting_panel_as_the_delegate(ledger, merge_breaks):
    """다시 저장이 REST 뿐이라 Claude 로 돌린 심사는 저장이 한 번 실패하면 Claude 에서 풀 수 없었다(10-11 dev 실주행 —
    7B 의장 출력의 모양 오류로 첫 패널이 persist_error). 입구 도구는 위임 신원으로만 쓰고 REST 와 같은 함수를 부른다."""
    from app import entry

    _job(ledger)
    out = _run(ledger, LedgerEngine())
    merge_breaks["broken"] = False
    delegate = dataclasses.replace(factories.ident(OWNER), source="sso", delegated=True)
    with factories.routes_store(ledger.store):
        with pytest.raises(AppError) as exc:
            entry.repersist_panel(factories.ident(OWNER), panel_id=out["panel_id"])
        assert exc.value.code == "delegation_required"
        done = entry.repersist_panel(delegate, panel_id=out["panel_id"])
    assert done["status"] == "done"
    assert runner.awaiting_repersist(ledger.store, ledger.target_key) == []


def test_repersist_needs_an_error_panel_with_a_saved_result_on_an_idle_target(ledger, merge_breaks):
    _job(ledger)
    out = _run(ledger, LedgerEngine())
    merge_breaks["broken"] = False
    busy = factories.plan_panel(ledger.store, ledger.target_key, "C")
    planner.start_panel_seats(ledger.store, busy["id"])
    with pytest.raises(AppError) as exc:
        runner.repersist_panel(ledger.store, ledger.cfg, out["panel_id"])
    assert (exc.value.code, exc.value.http_status) == ("target_busy", 409)
    runner.recover_running_panels(ledger.store)                      # 도는 패널을 닫는 생산자 — 결과 없는 error 패널이 된다
    assert _panel(ledger.store, busy["id"])["status"] == "error"
    with pytest.raises(AppError) as exc:
        runner.repersist_panel(ledger.store, ledger.cfg, busy["id"])
    assert (exc.value.code, exc.value.http_status) == ("result_absent", 404)
    assert runner.repersist_panel(ledger.store, ledger.cfg, out["panel_id"])["status"] == "done"
    with pytest.raises(AppError) as exc:
        runner.repersist_panel(ledger.store, ledger.cfg, out["panel_id"])
    assert (exc.value.code, exc.value.http_status) == ("not_error", 409)


class _Crash(BaseException):
    """프로세스가 저장 도중에 죽었다(재기동 전의 마지막 순간)."""


def test_a_restart_during_the_save_does_not_run_the_panel_again(ledger, monkeypatch):
    """엔진은 이미 끝났다 — 결과가 저장된 running 패널은 다시 돌리지 않고 persist_error 로 닫아 다시 저장을 기다린다."""
    job_id = _job(ledger)

    def crash(*_args, **_kwargs):
        raise _Crash()

    with monkeypatch.context() as patch, pytest.raises(_Crash):    # 스텁만 걷는다 — undo() 는 no_network 까지 푼다
        patch.setattr(runner, "_complete_panel", crash)
        _run(ledger, LedgerEngine())
    panel_id = ledger.store.query_one("SELECT id FROM rr_panels WHERE status = 'running'")["id"]
    assert _panel(ledger.store, panel_id)["result_gz"] is not None

    runner.recover_running_panels(ledger.store)
    panel = _panel(ledger.store, panel_id)
    assert panel["status"] == "error" and panel["error"].startswith("persist_error: restart")
    job = _job_row(ledger.store, job_id)
    assert job["state"] == "paused" and f"/api/panels/{panel_id}/repersist" in job["error"]
    assert set(_seat_retries(ledger.store, ledger.target_key).values()) == {0}
    assert runner.repersist_panel(ledger.store, ledger.cfg, panel_id)["status"] == "done"


def test_a_failure_after_the_commit_leaves_the_done_panel_alone(ledger, monkeypatch):
    """저장이 커밋된 뒤의 예외로 done 패널을 error 로 뒤집지 않는다 — 좌석은 이미 종결이다(P-18)."""
    from app import registry

    job_id = _job(ledger)
    real_close = registry.close_level
    monkeypatch.setattr(registry, "close_level", lambda store, key, **kw: {**real_close(store, key, **kw),
                                                                          "level": "C1"})

    def broken(*_args, **_kwargs):
        raise RuntimeError("수확 체감 판정이 터졌다")

    monkeypatch.setattr(runner, "_diminishing", broken)
    out = _run(ledger, LedgerEngine())
    assert out["status"] == "done", out
    panel = _panel(ledger.store, out["panel_id"])
    assert panel["status"] == "done" and panel["error"] is None
    keys = _seats_of(ledger.store, out["panel_id"])
    assert {s for s, _, _ in _seat_rows(ledger.store, ledger.target_key, keys).values()} <= {"done", "done_weak"}
    job = _job_row(ledger.store, job_id)
    assert job["state"] == "paused" and "수확 체감 판정이 터졌다" in job["error"]


def test_resubmitting_an_error_panel_updates_the_ledger(ledger):
    """error 로 닫힌 패널을 다시 제출하면 좌석을 그 패널로 되찾아 원장을 고친다 — 종전에는 원장은 그대로이고
    coverage_updated 만 참이었다(R-5). 좌석이 다른 패널로 갔으면 409 다."""
    from app import routes

    _job(ledger)
    first = _run(ledger, LedgerEngine(fail_first=runner.EngineError("엔진이 끊겼다")))
    keys = _seats_of(ledger.store, first["panel_id"])
    assert {s for s, _, _ in _seat_rows(ledger.store, ledger.target_key, keys).values()} == {"pending"}
    turns = [{"round": r, "persona": k, "say": f"{k} 라운드 {r} 발언"} for r in (1, 2) for k in keys]
    with factories.routes_store(ledger.store):
        out = routes.complete_panel(first["panel_id"], engine="mcp", decision_text=DECISION, turns=turns,
                                    actor=OWNER, owner_sub=OWNER)
        assert out["coverage_updated"] is True
        assert {s for s, _, _ in _seat_rows(ledger.store, ledger.target_key, keys).values()} <= {"done", "done_weak"}
        again = routes.complete_panel(first["panel_id"], engine="mcp", decision_text=DECISION, turns=turns,
                                      actor=OWNER, owner_sub=OWNER)
        assert again["coverage_updated"] is False                     # 이미 종결 — 원장은 바뀌지 않았다
    assert planner.check_invariants(ledger.store, ledger.target_key) == []


def test_resubmitting_an_error_panel_whose_seats_moved_is_refused(ledger):
    from app import routes

    _job(ledger)
    engine = LedgerEngine(fail_first=runner.EngineError("엔진이 끊겼다"))
    first = _run(ledger, engine)
    assert _run(ledger, engine)["status"] == "done"
    keys = _seats_of(ledger.store, first["panel_id"])
    with factories.routes_store(ledger.store), pytest.raises(AppError) as exc:
        routes.complete_panel(first["panel_id"], engine="mcp", decision_text=DECISION,
                              turns=[{"round": 1, "persona": k, "say": "늦은 발언"} for k in keys],
                              actor=OWNER, owner_sub=OWNER)
    assert (exc.value.code, exc.value.http_status) == ("seats_moved", 409)


def test_the_repersist_route_needs_an_editor_and_leaves_an_audit_row(ledger, merge_breaks):
    from app import routes

    _job(ledger)
    out = _run(ledger, LedgerEngine())
    merge_breaks["broken"] = False
    assert any(getattr(r, "path", "") == "/api/panels/{panel_id}/repersist" for r in routes.router.routes)
    with factories.routes_store(ledger.store):
        with pytest.raises(AppError) as exc:
            routes.post_panel_repersist(out["panel_id"], ident=factories.ident("stranger@example.com"))
        assert exc.value.http_status == 404
        body = routes.post_panel_repersist(out["panel_id"], ident=factories.ident(OWNER))
    assert body["status"] == "done" and body["panel_id"] == out["panel_id"] and "findings_n" in body
    audit = ledger.store.query_one("SELECT actor, scope, action FROM rr_audit WHERE subject_id = ?", (out["panel_id"],))
    assert dict(audit) == {"actor": OWNER, "scope": "panel", "action": "panel.repersist"}


def test_the_export_leaves_the_engine_result_behind(ledger, merge_breaks):
    """엔진 결과 원문은 반출 묶음에 싣지 않는다 — 받은 쪽은 다시 저장할 일이 없다(P-19)."""
    from app import export

    _job(ledger)
    out = _run(ledger, LedgerEngine())
    rows = [json.loads(line) for line in export.iter_lines(ledger.store, OWNER)][1:]
    panels = [r["row"] for r in rows if r["table"] == "rr_panels"]
    assert [p["id"] for p in panels] == [out["panel_id"]]
    assert "result_gz" not in panels[0] and panels[0]["result_hash"]


# ---------------------------------------------------------------- C2 의 파싱 실패 셈(RR-ADV-3)
def test_a_panel_closed_without_a_decision_is_not_a_parse_failure(ledger, monkeypatch):
    """일시 장애(brief_retry)·엔진 실패로 결정문 없이 닫힌 error 패널은 파싱 실패가 아니다 — 그 좌석은 다음 패널에서 다시 돈다.
    C2 의 '미해결 spec_parse_failed 0' 에 세면 그 패널 하나로 C2 가 영원히 거짓이다(푸는 '제외' 표기를 쓰는 길도 없다).
    통합 보고서의 품질 플래그도 그 패널을 파싱 실패로 적지 않는다."""
    import sqlite3

    from app import registry

    real = narrative.prior_evidence
    calls: list[int] = []

    def locked_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return real(*args, **kwargs)

    _job(ledger)
    engine = LedgerEngine(fail_first=runner.EngineError("엔진이 끊겼다"))
    with monkeypatch.context() as patch:
        patch.setattr(narrative, "prior_evidence", locked_once)
        assert _run(ledger, engine)["error"].startswith("brief_retry")
        assert _run(ledger, engine)["error"].startswith("engine_error")
        assert _run(ledger, engine)["status"] == "done"
    assert [(r["status"], r["risk_spec_parsed"]) for r in ledger.store.query(
        "SELECT status, risk_spec_parsed FROM rr_panels WHERE target_key = ? ORDER BY panel_no", (ledger.target_key,))
    ] == [("error", 0), ("error", 0), ("done", 1)]
    assert registry.close_level(ledger.store, ledger.target_key, persist=False)["detail"]["spec_parse_failed"] == 0
    minutes = registry.build_report(ledger.store, ledger.target_key)["blocks"]["minutes"]
    assert not [line for line in minutes if "spec_parse_failed" in line], minutes


def test_a_result_that_awaits_repersist_holds_c2_until_it_is_saved_or_abandoned(ledger, merge_breaks):
    """다시 저장을 기다리는 패널은 결정문이 아직 원장에 앉지 않았다 — 그동안은 C2 를 막고(그 결과 없이 마감되지 않게),
    포기하면 빠진다(좌석은 다음 패널에서 다시 돈다)."""
    from app import registry

    _job(ledger)
    out = _run(ledger, LedgerEngine())
    assert registry.close_level(ledger.store, ledger.target_key, persist=False)["detail"]["spec_parse_failed"] == 1
    runner.abandon_repersist(ledger.store, out["panel_id"])
    assert registry.close_level(ledger.store, ledger.target_key, persist=False)["detail"]["spec_parse_failed"] == 0



# ---------------------------------------------------------------- S15 — 완결 레벨이 오르면 통합 보고서를 조립한다(R-47 · raised 분기만)
@pytest.fixture
def all_domains(risk_store, tmp_path, no_network, monkeypatch):
    """로스터 15 영역 × 2명. ECAD 영역도 보류하지 않게 해 Tier A 대표 패널 셋으로 C1 이 서게 한다(C1 = 전 영역 종결 + A 셋)."""
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_ecad_domains=()))
    return _make_ledger(risk_store, tmp_path, config.settings.risk_roster_domains, 2)


def test_a_level_raise_builds_the_consolidated_report(all_domains, monkeypatch):
    """close_level 이 '올랐다' 를 말해야 러너가 통합 보고서를 조립한다 — 그 키가 없어 분기가 죽어 있었다."""
    from app import registry

    calls: list[tuple] = []
    real = registry.build_consolidated_report

    def spy(store, target_key, level=None):
        calls.append((target_key, level))
        return real(store, target_key, level)

    monkeypatch.setattr(registry, "build_consolidated_report", spy)
    runner.create_job(all_domains.store, all_domains.target_key, "A", owner_sub=OWNER, settings=all_domains.cfg)
    outs = [_run(all_domains, LedgerEngine()) for _ in range(3)]
    assert [o["level"] for o in outs] == ["C0", "C0", "C1"], outs
    assert calls == [(all_domains.target_key, "C1")]
    assert registry.close_level(all_domains.store, all_domains.target_key, persist=False)["raised"] is False


def test_a_report_that_cannot_be_built_does_not_undo_the_panel(all_domains, monkeypatch):
    """보고서는 원장에서 다시 만들 수 있는 파생물이다 — 조립이 터져도 패널·좌석·레벨은 그대로 앉고 패널에 표가 남는다."""
    from app import registry

    def broken(*_args, **_kwargs):
        raise RuntimeError("보고서 조립이 터졌다")

    monkeypatch.setattr(registry, "build_consolidated_report", broken)
    runner.create_job(all_domains.store, all_domains.target_key, "A", owner_sub=OWNER, settings=all_domains.cfg)
    outs = [_run(all_domains, LedgerEngine()) for _ in range(3)]
    assert [(o["status"], o["level"]) for o in outs] == [("done", "C0"), ("done", "C0"), ("done", "C1")], outs
    quality = json.loads(_panel(all_domains.store, outs[-1]["panel_id"])["quality_json"])
    assert "report_build_failed" in quality["flags"] and "보고서 조립이 터졌다" in quality["report_build_error"]
    assert all_domains.store.query_one("SELECT level FROM rr_targets WHERE target_key = ?",
                                       (all_domains.target_key,))["level"] == "C1"


def test_a_claude_submission_that_fails_to_save_leaves_the_planned_panel_planned(ledger, monkeypatch):
    """Claude(MCP) 회수 길도 저장이 터지면 반쪽 없이 물러난다 — 미리 편성된 패널은 planned·좌석 assigned 그대로라 다시 낼 수
    있다. 종전에는 좌석을 running 으로 옮기는 일이 트랜잭션 밖이라 패널·좌석이 running 에 굳어 그 타깃이 재기동까지 멈췄다."""
    from app import registry, routes

    panel = factories.plan_panel(ledger.store, ledger.target_key, "C")
    keys = [s["key"] for s in panel["seats"]]

    def broken(*_args, **_kwargs):
        raise RuntimeError("디스크가 찼다")

    turns = [{"round": r, "persona": k, "say": f"{k} 라운드 {r} 발언"} for r in (1, 2) for k in keys]
    # 스텁만 걷는다 — undo() 는 no_network 가드까지 푼다.
    with monkeypatch.context() as patch, factories.routes_store(ledger.store), pytest.raises(RuntimeError):
        patch.setattr(registry, "merge", broken)
        routes.complete_panel(panel["id"], engine="mcp", decision_text=DECISION, turns=turns,
                              actor=OWNER, owner_sub=OWNER)
    assert _panel(ledger.store, panel["id"])["status"] == "planned"
    assert {s for s, _, _ in _seat_rows(ledger.store, ledger.target_key, keys).values()} == {"assigned"}

    with factories.routes_store(ledger.store):
        out = routes.complete_panel(panel["id"], engine="mcp", decision_text=DECISION, turns=turns,
                                    actor=OWNER, owner_sub=OWNER)
    assert out["coverage_updated"] is True and _panel(ledger.store, panel["id"])["status"] == "done"
    assert planner.check_invariants(ledger.store, ledger.target_key) == []


# ---------------------------------------------------------------- S5 — 판단어 방패가 러너 길에서 패널 품질까지(WP1 S5-c · P-03)
def _diff_ledger(store, tmp_path, target_key: str) -> SimpleNamespace:
    store.upsert_credential(OWNER, identity.encrypt_pat("pat-secret").decode("ascii"), "sub-1", OWNER, "[]",
                            common.now_epoch() + 30 * 86400)
    return SimpleNamespace(store=store, target_key=target_key,
                           cfg=dataclasses.replace(config.settings, data_dir=tmp_path))


def test_brief_shielded_reaches_panel_quality(risk_store, tmp_path, no_network):
    """부품 이름에 판단어가 든 합성 타깃 — 러너 길의 브리프가 죽지 않고, 무엇을 «» 로 쌌는지 패널 품질에 남는다."""
    from tests.test_brief import legacy_summary

    synth = factories.make_diff_target(risk_store, 3, agents=factories.agents(("mech", "sim", "xd", "rel", "cam"), 3))
    legacy_summary(risk_store, synth.target_key)            # S10 이전 요약 — 이름이 «» 밖에 날것으로 선다
    lg = _diff_ledger(risk_store, tmp_path, synth.target_key)
    _job(lg)
    out = _run(lg, LedgerEngine())
    assert out["status"] == "done", out
    quality = json.loads(_panel(lg.store, out["panel_id"])["quality_json"])
    assert "brief_shielded" in quality["flags"]
    assert quality["brief_shielded"] and {s["item"] for s in quality["brief_shielded"]} == {"E1"}
    assert all(s["ids"] and s["line_no"] >= 2 for s in quality["brief_shielded"])


def test_second_target_of_the_same_project_runs_its_panel(risk_store, tmp_path, no_network):
    """같은 과제의 다음 리비전 — 새 타깃이 앞 타깃의 등록부 행에 stale 을 적고(`_supersede_previous_target`), 그 행이
    `[변경 주체 — 재검증 대상]` 접두를 달고 E5 에 실려도 패널이 brief_error 없이 끝난다(P-03)."""
    from tests.rr import legacy_build as legacy

    project_id = factories.make_project(risk_store)
    base_results, target_results = legacy.adapter_pair()
    # 옛 원장 빌더의 개정본은 PLATE_2 의 min_dim 만 바꾼다(7248651 에서 얼린 DB 의 모양이라 그대로 둔다) — 새 스냅샷은 실제
    # 어댑터가 내는 모양(bbox·size_def·짝 dyna 까지)으로 고쳐 쓴다(R-FLOOR-1).
    factories.set_thickness(target_results, "PLATE_2", 1.4)
    s1 = factories.make_snapshot(risk_store, project_id, base_results, label="DV1")
    s2 = factories.make_snapshot(risk_store, project_id, target_results, label="DV2",
                                 captured_at=factories.CAPTURED_AT + 86400)
    roster = factories.agents(("mech", "sim", "xd", "rel", "cam"), 3)
    first = factories.make_target(risk_store, "diff", factories.make_diff(risk_store, s1["snapshot_id"],
                                                                          s2["snapshot_id"])["diff_id"], agents=roster)
    lg = _diff_ledger(risk_store, tmp_path, first)
    first_job = _job(lg)
    out = _run(lg, legacy.LegacyEngine(legacy.spec_builder(risk_store, first, planner.domain_of)))
    assert out["status"] == "done", out
    runner.cancel_job(risk_store, first_job, by=OWNER)                 # 다음 집기가 앞 타깃의 남은 패널을 집지 않게
    assert risk_store.query("SELECT 1 FROM rr_registry WHERE target_key = ? AND status = 'open'", (first,))

    third = json.loads(json.dumps(target_results))
    by_label = {n["label"]: n for n in third[0]["nodes"]}
    factories.set_thickness(third, "PLATE_2", 1.8)
    by_label["PLATE_1"]["attrs"]["material"] = "AL6061"
    s3 = factories.make_snapshot(risk_store, project_id, third, label="DV3", captured_at=factories.CAPTURED_AT + 2 * 86400)
    # 두께가 바뀐 PLATE_2 는 리비전마다 계산 ckey(부피 버킷)가 달라진다. 자동 승계(§2.7.3 sameas.inherit_ckeys)는 지금 파이프라인
    # 어디에서도 부르지 않아(생산자 결함 — test_sameas 의 xfail 재현), 오늘 앞 타깃 행이 stale 로 서고 E5 에 subject 로 실리는
    # 길은 사람의 키 병합(POST /api/sameas/decide merge_key) 뿐이다 — 그 길로 DV2·DV3 의 키를 DV1 키에 앉힌다. 종전 입력(min_dim
    # 만)은 버킷이 그대로라 이것을 가렸다(R-FLOOR-1).
    from app import routes

    def plate2_ckey(snapshot_id: str) -> str:
        return risk_store.query_one("SELECT ckey FROM rr_ir_nodes WHERE snapshot_id = ? AND name = 'PLATE_2'",
                                    (snapshot_id,))["ckey"]

    with factories.routes_store(risk_store):
        routes.post_sameas_decide([{"decision": "merge_key", "ckey": plate2_ckey(snapshot["snapshot_id"]),
                                    "ckey_into": plate2_ckey(s1["snapshot_id"])} for snapshot in (s2, s3)],
                                  ident=factories.ident())
    second = factories.make_target(risk_store, "diff", factories.make_diff(risk_store, s2["snapshot_id"],
                                                                           s3["snapshot_id"])["diff_id"], agents=roster)
    stale = [r for r in risk_store.query("SELECT stale_json FROM rr_registry WHERE target_key = ?", (first,))
             if (json.loads(r["stale_json"] or "{}").get(second) or {}).get("stale")]
    assert stale, "앞 타깃의 등록부에 stale 이 서지 않았다 — 이 시험은 P-03 을 보지 않는다"

    lg2 = SimpleNamespace(store=risk_store, target_key=second, cfg=lg.cfg)
    runner.create_job(risk_store, second, "C", owner_sub=OWNER, consent=True, settings=lg.cfg)
    engine = legacy.LegacyEngine(legacy.spec_builder(risk_store, second, planner.domain_of))
    out = _run(lg2, engine)
    assert out["status"] == "done" and not _panel(risk_store, out["panel_id"])["error"], out
    e5 = next(e["result"] for e in engine.calls[0]["evidence"] if e.get("key") == "E5")
    assert "[변경 주체 — 재검증 대상] reg:" in e5, e5
    # 좌석 기억(E7, WP1 S8 · R-14) — 앞 타깃에서 finding 을 올린 좌석이 이번 패널에도 앉았으면 그 발언이 «» 안에 실린다.
    raisers = {r["agent_key"] for r in risk_store.query(
        "SELECT agent_key FROM rr_seat_opinions WHERE target_key = ? AND raised_finding_ids_json <> '[]'", (first,))}
    seated = [p["key"] for p in engine.calls[0]["personas"] if p["origin"] in ("primary", "counter")]
    again = sorted(raisers & set(seated))
    assert again, "앞 타깃의 제기 좌석이 이번 패널에 없다 — 이 단언은 아무것도 보지 않는다"
    e7 = next(e["result"] for e in engine.calls[0]["evidence"] if e.get("key") == "E7").split("\n")[1:]
    for key in seated:
        line = next(ln for ln in e7 if f" | {key} | " in ln or ln == f"[{key}: 이전 발언 없음]")
        assert line.startswith("narr:") == (key in again) and (key not in again or "| «" in line), (key, e7)
    # 이 브리프의 줄 모양(접두 달린 선례 · 좌석 기억 · 변경 규모 · 꼬리) 어느 것도 방패에 걸리지 않았다 — strict 로도 깨끗하다.
    quality = json.loads(_panel(risk_store, out["panel_id"])["quality_json"])
    assert "brief_shielded" not in quality["flags"], quality.get("brief_shielded")


def test_brief_clipped_reaches_panel_quality(risk_store, tmp_path, no_network):
    """변경이 상한보다 많은 타깃 — 잘린 줄 수가 패널 품질에 구조로 남는다(WP1 R-19)."""
    synth = factories.make_diff_target(risk_store, 40, agents=factories.agents(("mech", "sim", "xd", "rel", "cam"), 3))
    lg = _diff_ledger(risk_store, tmp_path, synth.target_key)
    _job(lg)
    out = _run(lg, LedgerEngine())
    assert out["status"] == "done", out
    quality = json.loads(_panel(lg.store, out["panel_id"])["quality_json"])
    assert "brief_clipped" in quality["flags"]
    e2 = quality["brief_clipped"]["E2"]
    assert e2["omitted"] > 0 and e2["kept"] + e2["omitted"] == e2["lines"] == len(synth.diff["semantic"]["events"])
    # E0c 는 러너가 제 좌석 계약표로 갈아 끼운다 — 브리프 쪽 E0c 의 절단은 좌석이 받은 것이 아니다.
    assert "E0c" not in quality["brief_clipped"], quality["brief_clipped"]


def test_three_panels_of_a_synthetic_many_change_target_close_done(risk_store, tmp_path, no_network):
    """M1 나갈 기준(dev) — 부품 이름에 판단어가 든 합성 다건 변경 타깃에서 패널 셋이 brief_error 없이 연속 done 이다
    (변경 목록의 이름·값·순서는 tests/test_brief.py 의 E2 시험이 본다)."""
    synth = factories.make_diff_target(risk_store, 40, agents=factories.agents(("mech", "sim", "xd", "rel", "cam"), 3))
    lg = _diff_ledger(risk_store, tmp_path, synth.target_key)
    _job(lg)
    engine = LedgerEngine()
    outs = [_run(lg, engine) for _ in range(3)]
    assert [o["status"] for o in outs] == ["done", "done", "done"], outs
    assert all(not _panel(risk_store, o["panel_id"])["error"] for o in outs)
    assert planner.check_invariants(risk_store, synth.target_key) == []


class _BudgetEngine(LedgerEngine):
    """엔진 /health 가 근거 예산을 알려 주는 대역 — 받은 delib_opts 를 남긴다."""

    def __init__(self, evid_budget, **kwargs) -> None:
        super().__init__(**kwargs)
        self.evid_budget = evid_budget
        self.opts: list[dict] = []

    def health(self) -> dict:
        info = super().health()
        if self.evid_budget is not None:
            info["evid_budget"] = self.evid_budget
        return info

    def run(self, delib_opts, *, owner_sub=None):
        self.opts.append(dict(delib_opts))
        return super().run(delib_opts, owner_sub=owner_sub)


def test_panel_brief_is_sized_from_the_engine_budget(risk_store, tmp_path, no_network):
    """웹 러너는 패널마다 엔진 /health 의 evid_budget 으로 브리프 크기를 정하고 그 프로파일을 model_json 에 남긴다 —
    1백만 토큰 창(500,000자)이면 변경 전부가 좌석에 가고, 예산을 모르는 옛 엔진이면 종전 크기(11,000자)다(WP1 S9)."""
    from app import brief

    synth = factories.make_diff_target(risk_store, 40, agents=factories.agents(("mech", "sim", "xd", "rel", "cam"), 3))
    lg = _diff_ledger(risk_store, tmp_path, synth.target_key)
    _job(lg)
    wide, old = _BudgetEngine(500_000), _BudgetEngine(None)
    first, second = _run(lg, wide), _run(lg, old)
    assert first["status"] == second["status"] == "done", (first, second)
    models = [json.loads(risk_store.query_one("SELECT model_json FROM rr_panels WHERE id = ?",
                                              (o["panel_id"],))["model_json"]) for o in (first, second)]
    assert models[0]["evid_budget"] == 500_000 and models[0]["brief_profile"] == {"name": "web", "budget": 500_000}
    assert models[1]["evid_budget"] is None
    assert models[1]["brief_profile"] == {"name": "web-legacy", "budget": brief.ENGINE_BUDGET}
    n_events = len(synth.diff["semantic"]["events"])
    tail = next(e["result"] for e in wide.opts[0]["evidence"] if e["key"] == "E2").split("\n")[-1]
    assert tail.startswith(f"[전체 {n_events}건 — 실림 {n_events} · 생략 0 |"), tail
    assert sum(len(brief.evidence_line(e)) for e in wide.opts[0]["evidence"]) <= 500_000
    assert sum(len(brief.evidence_line(e)) for e in old.opts[0]["evidence"]) <= brief.ENGINE_BUDGET
    quality = json.loads(_panel(risk_store, first["panel_id"])["quality_json"])
    assert "E2" not in (quality.get("brief_clipped") or {}), quality.get("brief_clipped")


def test_runner_question_carries_the_digest_and_the_diff_mark(risk_store, tmp_path, no_network, monkeypatch):
    """웹 러너 — 소유자 자격으로 도는 패널의 질문에 변경 요지와 `diff_id=<id>` 가 실리고 지식카드 검색어가 같이 간다.
    검색어가 포털 상한에 잘렸으면 패널 품질에 남는다(WP1 S11)."""
    from app import brief

    synth = factories.make_diff_target(risk_store, 40, agents=factories.agents(("mech", "sim", "xd", "rel", "cam"), 3))
    lg = _diff_ledger(risk_store, tmp_path, synth.target_key)
    _job(lg)
    # 이 박스의 게이트웨이는 위임 헤더를 싣는 판이다(사람별 단언 발급을 받아 봤다) — 좌석이 소유자로 보여 그 diff 를 연다(SEC-3).
    # 발급을 받아 봤으니 앱에 게이트웨이 시크릿이 있다(비면 gateway_sso_off 로 막는다 · 3차 검토 발견 3).
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: GATEWAY_SECRET)
    runner.note_gateway_mint(risk_store, delegated=True)
    engine = _BudgetEngine(None)
    out = _run(lg, engine)
    assert out["status"] == "done", out
    opts = engine.opts[0]
    assert f"diff_id={synth.diff_id}" in opts["question"] and "변경 요지: «" in opts["question"]
    assert opts["knowledge_query"] and len(opts["knowledge_query"]) <= brief.KNOWLEDGE_QUERY_MAX
    quality = json.loads(_panel(risk_store, out["panel_id"])["quality_json"])
    assert "knowledge_query_cut" in quality["flags"] and quality["knowledge_query_cut"]["kept"] == len(opts["knowledge_query"])


class _KnowledgeEngine(_BudgetEngine):
    """첫 좌석에 지식카드 3줄을 실었다고 알리는 엔진 — 검색어는 질문으로 찾았다고 한다(옛 포털이 키를 버린 경우)."""

    def run(self, delib_opts, *, owner_sub=None):
        result = dict(super().run(delib_opts, owner_sub=owner_sub))
        seat = delib_opts["personas"][0]["key"]
        result["events"] = list(result["events"]) + [
            {"kind": "status", "step": f"지식카드 1/5 — {seat} 확보",
             "knowledge": {"persona": seat, "hits": 3, "degraded": False, "query": "question"}},
            {"kind": "evidence", "source": f"{seat} · 지식카드", "included": True}]
        return result


def test_knowledge_hits_reach_the_seat_opinion_and_a_dropped_query_is_flagged(risk_store, tmp_path, no_network):
    """좌석별 지식카드 적중 수가 의견 행에 서고(종전 늘 null), 카드를 받은 것이 도구 사용으로 세지지 않으며, 앱이 검색어를
    보냈는데 엔진이 질문으로 찾았으면 패널 품질에 남는다(WP1 S13 · R-43 · R-44 · workorder-c 5절 1)."""
    synth = factories.make_diff_target(risk_store, 40, agents=factories.agents(("mech", "sim", "xd", "rel", "cam"), 3))
    lg = _diff_ledger(risk_store, tmp_path, synth.target_key)
    _job(lg)
    engine = _KnowledgeEngine(None)
    out = _run(lg, engine)
    assert out["status"] == "done", out
    seat = engine.opts[0]["personas"][0]["key"]
    row = risk_store.query_one("SELECT knowledge_hits_n, tool_calls_ok, opinion_json FROM rr_seat_opinions"
                               " WHERE panel_id = ? AND agent_key = ?", (out["panel_id"], seat))
    assert row["knowledge_hits_n"] == json.loads(row["opinion_json"])["knowledge_hits_n"] == 3
    assert row["tool_calls_ok"] == 0
    others = risk_store.query("SELECT knowledge_hits_n FROM rr_seat_opinions WHERE panel_id = ? AND agent_key <> ?",
                              (out["panel_id"], seat))
    assert others and all(r["knowledge_hits_n"] is None for r in others)
    quality = json.loads(_panel(risk_store, out["panel_id"])["quality_json"])
    assert quality["knowledge_query_ignored"] == [seat] and "knowledge_query_ignored" in quality["flags"]


# ---------------------------------------------------------------- SEC-3 — diff_id 표식은 좌석이 게이트웨이를 거쳐 그 diff 를 열 때만
# 게이트웨이 heax 토큰의 주인 — provision 이 '가장 먼저 만든 heax 관리자' 에게 발급한 PAT 다. HEAXHub Caddy 의 forward_auth 는
# 앱으로 가는 X-Heax-User-Email 을 지우고 이 이메일로 다시 싣는다(proxy_manager `_forward_auth_handler(copy_identity=True)`).
FIRST_ADMIN = "first-admin@example.com"
GATEWAY_SECRET = "panel-ledger-gateway-secret"


def _gateway_assertion(delegate: str | None) -> str:
    """게이트웨이 → HEAXHub Caddy → 앱 `POST /api/auth/sso` 를 지금 배선 그대로 — 앱의 실제 발급 함수가 단언을 만든다.

    Caddy 가 X-Heax-User-Email 을 첫 관리자로 덮은 뒤다. `delegate=None` 은 위임 헤더(X-Hwax-Delegate-Email)를 보내지 않는
    옛 게이트웨이다."""
    from starlette.requests import Request

    from app import routes

    headers = [(b"x-heax-gateway-secret", GATEWAY_SECRET.encode()), (b"x-heax-user-email", FIRST_ADMIN.encode())]
    if delegate is not None:
        headers.append((b"x-hwax-delegate-email", delegate.encode()))
    request = Request({"type": "http", "method": "POST", "path": "/api/auth/sso", "headers": headers, "query_string": b""})
    return routes.post_auth_sso(request)["access_token"]


def _seat_reads_diff(monkeypatch, assertion: str, diff_id: str) -> dict:
    """좌석의 `risk_get_diff` — 게이트웨이는 받아 온 단언을 X-Heax-Sso-Assertion 에 실어 앱 /mcp 를 부른다."""
    from starlette.requests import Request

    import app.mcp_server as srv

    request = Request({"type": "http", "method": "POST", "path": "/mcp",
                       "headers": [(identity.SSO_HEADER.encode(), assertion.encode())], "query_string": b""})
    monkeypatch.setattr(srv, "_request", lambda: request)
    return srv.risk_get_diff(diff_id=diff_id, part="lines")


def test_the_diff_mark_rides_only_when_the_seat_identity_opens_the_diff(risk_store, tmp_path, no_network, monkeypatch):
    """좌석은 게이트웨이를 거쳐 잡 자격의 이메일로 `risk_get_diff` 를 부른다. 위임 헤더를 보내지 않는 옛 게이트웨이면 그 이메일이
    HEAXHub Caddy 에서 heax 첫 관리자로 덮여 소유자의 private 과제가 not_visible 이다 — 질문의 `diff_id=` 는 그 호출이 열릴 때만
    싣고, 못 실은 까닭은 패널 품질에 남긴다(SEC-3). 종전에는 소유자 자격이면 늘 실어, 엔진이 좌석마다 맨 앞에 세운 호출이 말없이
    not_visible 로 버려졌다."""
    from app import routes

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: GATEWAY_SECRET)
    synth = factories.make_diff_target(risk_store, 3, agents=factories.agents(("mech", "sim", "xd", "rel", "cam"), 3))
    lg = _diff_ledger(risk_store, tmp_path, synth.target_key)          # 러너 자격은 소유자가 등록한 포털 PAT 다
    _job(lg)
    engine = _BudgetEngine(None)
    mark = f"diff_id={synth.diff_id}"

    # 옛 게이트웨이 — 좌석이 받은 단언은 첫 관리자의 것이고, 그 신원으로는 소유자의 private 과제를 못 연다.
    folded = _gateway_assertion(None)
    out = _run(lg, engine)
    assert out["status"] == "done", out
    assert _seat_reads_diff(monkeypatch, folded, synth.diff_id).get("error") == "not_visible"
    assert mark not in engine.opts[0]["question"]
    quality = json.loads(_panel(risk_store, out["panel_id"])["quality_json"])
    assert quality["diff_ref_withheld"]["reason"] == "gateway_folded", quality.get("diff_ref_withheld")
    assert "X-Hwax-Delegate-Email" in quality["diff_ref_withheld"]["why"] and "diff_ref_withheld" in quality["flags"]

    # 새 게이트웨이 — 위임 헤더로 좌석이 소유자 자신으로 보인다. 다음 패널부터 표식이 실리고 그 호출이 열린다.
    delegated = _gateway_assertion(OWNER)
    out = _run(lg, engine)
    assert out["status"] == "done", out
    assert mark in engine.opts[1]["question"]
    seat = _seat_reads_diff(monkeypatch, delegated, synth.diff_id)
    assert "error" not in seat and seat["total"] > 0 and seat["lines"], seat
    quality = json.loads(_panel(risk_store, out["panel_id"])["quality_json"])
    assert "diff_ref_withheld" not in quality and "diff_ref_withheld" not in quality["flags"]


def _mint_row(store) -> dict | None:
    row = store.query_one("SELECT value, n, computed_at FROM rr_metrics WHERE period = ? AND dimension = ? AND key = ?"
                          " AND metric = ?", runner.GATEWAY_MINT_ROW)
    return None if row is None else dict(row)


def test_an_unverified_gateway_does_not_withhold_the_diff_mark_and_its_record_heals(risk_store, tmp_path, no_network,
                                                                                    monkeypatch):
    """좌석 diff 표식 판정은 '마지막 단언 발급' 기록 하나에 기댄다(SEC-3). 그 기록은 좌석이 사람별로 이 앱을 불러야 생기는데,
    표식을 빼면 좌석이 이 앱을 부를 계기가 거의 없다 — 기록이 없는 박스는 개인 과제의 diff 패널이 영영 gateway_unseen 이었고,
    옛 판 시절의 folded 는 게이트웨이를 올려도 풀리지 않았으며, 지표 재계산(period 'live')이 그 행을 지워 처음으로 되돌렸다(RV-3).

    기록이 없거나 단언 수명보다 오래된 folded 는 막지 않는다 — 표식을 싣고 패널 품질에 gateway_unverified 로 남긴다(좌석의 첫
    호출이 발급을 일으켜 다음 패널부터 판정된다). 수명 안의 folded 만 지금처럼 막는다. 재계산은 그 행을 지우지 않는다."""
    from app import metrics, routes

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: GATEWAY_SECRET)
    synth = factories.make_diff_target(risk_store, 3, agents=factories.agents(("mech", "sim", "xd", "rel", "cam"), 3))
    lg = _diff_ledger(risk_store, tmp_path, synth.target_key)
    _job(lg)
    engine = _BudgetEngine(None)
    mark = f"diff_id={synth.diff_id}"

    def quality_of(out: dict) -> dict:
        assert out["status"] == "done", out
        return json.loads(_panel(risk_store, out["panel_id"])["quality_json"])

    # (a) 발급 기록이 없는 박스 — 막지 않고 싣되, 좌석이 그 사람으로 보일지 확인하지 못했다는 것을 품질에 남긴다.
    assert _mint_row(risk_store) is None
    quality = quality_of(_run(lg, engine))
    assert mark in engine.opts[0]["question"]
    assert "diff_ref_withheld" not in quality, quality.get("diff_ref_withheld")
    assert quality["gateway_unverified"]["reason"] == "gateway_unseen" and "gateway_unverified" in quality["flags"]

    # (b) 옛 판(위임 헤더 없음)으로 방금 발급했다 — 단언 수명 안이면 좌석은 그 접힌 신원이라 지금처럼 막는다.
    _gateway_assertion(None)
    quality = quality_of(_run(lg, engine))
    assert mark not in engine.opts[1]["question"]
    assert quality["diff_ref_withheld"]["reason"] == "gateway_folded" and "gateway_unverified" not in quality
    # 수명이 지난 folded 는 지금의 판을 말하지 못한다 — 게이트웨이를 올렸어도 아무도 이 앱을 사람별로 부르지 않으면 영영 남았다.
    risk_store.execute("UPDATE rr_metrics SET computed_at = computed_at - ? WHERE period = ? AND dimension = ? AND key = ?"
                       " AND metric = ?", (config.settings.sso_ttl_s + 1, *runner.GATEWAY_MINT_ROW))
    quality = quality_of(_run(lg, engine))
    assert mark in engine.opts[2]["question"]
    assert quality["gateway_unverified"]["reason"] == "gateway_folded_stale" and "diff_ref_withheld" not in quality

    # (c) 로그인한 누구나 부르는 지표 재계산(period 'live')이 그 기록을 지우지 않는다.
    _gateway_assertion(OWNER)
    kept = _mint_row(risk_store)
    metrics.recompute(risk_store, period="live")
    assert _mint_row(risk_store) == kept and runner.gateway_delegates(risk_store) is True


def test_a_failure_to_note_the_mint_does_not_fail_the_assertion(risk_store, monkeypatch):
    """발급 기록은 러너의 판정 자료일 뿐이다 — 그 쓰기가 실패해도(잠김 등) 게이트웨이가 받을 단언 발급은 실패하지 않는다(RV-3)."""
    import sqlite3

    from app import routes

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: GATEWAY_SECRET)

    def locked(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(runner, "note_gateway_mint", locked)
    token = _gateway_assertion(OWNER)
    assert identity._verify_sso_assertion(token) == (OWNER, True)


def test_a_box_without_the_gateway_secret_withholds_the_diff_mark(risk_store, tmp_path, no_network, monkeypatch):
    """앱의 게이트웨이 시크릿이 비면(게이트웨이에 per_user_sso.hwax_risk 가 없는 박스) /api/auth/sso 가 404 라 발급 기록이 영영
    생기지 않고, 단언 검증도 그 시크릿으로 하므로 좌석은 늘 서비스 세션(heax 첫 관리자)으로 보인다. 그 박스에서 기록 없음을
    gateway_unseen 으로 읽어 diff_id 를 실으면 개인 과제 diff 패널마다 좌석이 risk_get_diff 를 불러 not_visible 을 영구히
    받는다 — 막고 까닭을 gateway_sso_off 로 남긴다. 시크릿이 있는데 기록이 없을 때만 지금처럼 gateway_unverified 로 싣는다
    (3차 검토 발견 3)."""
    from app import routes

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    secret = {"value": ""}
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: secret["value"])
    synth = factories.make_diff_target(risk_store, 3, agents=factories.agents(("mech", "sim", "xd", "rel", "cam"), 3))
    lg = _diff_ledger(risk_store, tmp_path, synth.target_key)
    _job(lg)
    engine = _BudgetEngine(None)
    mark = f"diff_id={synth.diff_id}"

    def quality_of(out: dict) -> dict:
        assert out["status"] == "done", out
        return json.loads(_panel(risk_store, out["panel_id"])["quality_json"])

    # (a) 시크릿이 없다 — 발급 길이 닫혀 있어 기록이 생길 수 없다. 표식을 막고 까닭을 남긴다.
    with pytest.raises(AppError) as closed:
        _gateway_assertion(OWNER)
    assert closed.value.http_status == 404 and _mint_row(risk_store) is None
    quality = quality_of(_run(lg, engine))
    assert mark not in engine.opts[0]["question"]
    assert quality["diff_ref_withheld"]["reason"] == "gateway_sso_off" and "gateway_unverified" not in quality
    assert "diff_ref_withheld" in quality["flags"] and "HWAXRISK_HEAX_GATEWAY_SECRET" in quality["diff_ref_withheld"]["why"]

    # (b) 시크릿이 생겼지만 아직 발급이 없다 — 좌석의 첫 호출이 발급을 일으키니 막지 않고 싣는다(RV-3 그대로).
    secret["value"] = GATEWAY_SECRET
    quality = quality_of(_run(lg, engine))
    assert mark in engine.opts[1]["question"]
    assert quality["gateway_unverified"]["reason"] == "gateway_unseen" and "diff_ref_withheld" not in quality

    # (c) 위임 판으로 발급한 뒤 시크릿을 지웠다 — 남은 기록은 위임이라 말하지만 그 단언은 더 이상 검증되지 않는다.
    token = _gateway_assertion(OWNER)
    assert runner.gateway_delegates(risk_store) is True
    secret["value"] = ""
    assert identity._verify_sso_assertion(token) is None
    quality = quality_of(_run(lg, engine))
    assert mark not in engine.opts[2]["question"]
    assert quality["diff_ref_withheld"]["reason"] == "gateway_sso_off"
