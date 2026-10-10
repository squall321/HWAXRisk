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
                 fail_first: Exception | None = None) -> None:
        self.silent_first = silent_first
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
            "events": [{"kind": "personas", "personas": [{"key": k} for k in keys + [ADVERSARY]]}],
            "conv_id": f"conv-{len(self.calls)}", "report_id": len(self.calls), "call_path": "portal",
            "credential": "owner",
        }


@pytest.fixture
def no_network(monkeypatch):
    """브리프의 필드 근거 호출이 dev 박스의 실 게이트웨이에 닿지 않게 연결 오류로 답한다."""
    def _refused(*args, **_kwargs):
        raise httpx.ConnectError("시험은 외부를 부르지 않는다.", request=args[-1])

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refused)


@pytest.fixture
def ledger(risk_store, tmp_path, no_network):
    """과제 → 스냅샷 → 타깃(로스터 15명) → 러너 자격. 반환 (store, target_key, cfg)."""
    project_id = factories.make_project(risk_store)
    snapshot = factories.make_snapshot(risk_store, project_id, factories.fixture_adapter_results(), label="DV1")
    target_key = factories.make_target(risk_store, "snap", snapshot["snapshot_id"],
                                       agents=factories.agents(("mech", "sim", "xd", "rel", "cam"), per_domain=3))
    risk_store.upsert_credential(OWNER, identity.encrypt_pat("pat-secret").decode("ascii"), "sub-1", OWNER, "[]",
                                 common.now_epoch() + 30 * 86400)
    return SimpleNamespace(store=risk_store, target_key=target_key,
                           cfg=dataclasses.replace(config.settings, data_dir=tmp_path))


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
