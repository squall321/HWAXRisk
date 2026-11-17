# 결정 → 판정표 층(RK-03) 시험 — 결정 JSON · 결정문 글 · 심의 job_id(가짜 게이트웨이 채널)를 칸 대응으로 옮기고 칸마다 filled · empty · conflict · no_source, 표결 · 합의 문장 대조
"""HWAXPortal docs/request-1117 RK-03 · contracts.md §3. 엔진이 decision_json 꼴을 아직 내지 않는 판(11-17 dev — view 는 full · summary 뿐)이면 summary 의
결정문 글을 쪽마다 이어 읽는다. 결정 항목의 코드 칸 · 등급 칸은 합성 꼴이다(risk_spec 항목은 칸을 더 받는다).

  실행:  .venv/bin/python -m pytest tests/test_ledger_decision.py
"""
from __future__ import annotations

import json

import pytest

from app import ledger, ledger_decision, ledger_routes
from app.errors import AppError
from tests import factories
from tests.ledger_support import OWNER, STRANGER, VIEWER, call, ledger_box, seed_ledger  # noqa: F401

MAPPING = {"code_field": "code", "fields": {"grade": "최종 등급", "owner_domain": "결정 출처", "claim": "비고", "subject.part": "부품"}}
SPEC = {"schema": "risk_spec", "version": "1.0", "findings": [
    {"id": "F1", "code": "R-001", "grade": "A", "owner_domain": "mech", "claim": "합성 주장 하나", "subject": {}},
    {"id": "F2", "code": "R-005", "grade": "B", "owner_domain": "", "claim": "합성 주장 둘", "subject": {"part": "PART-E"}},
    {"id": "F3", "grade": "C", "claim": "코드가 없는 항목"},
    {"id": "F4", "code": "R-020", "grade": "C", "owner_domain": "pcb", "claim": "새 코드", "subject": {"part": "PART-N"}},
]}
TEXT = "## 결정\n전원 합의로 아래와 같이 정한다.\n\n```json\n" + json.dumps(SPEC, ensure_ascii=False) + "\n```\n"


def _apply(box, **body) -> dict:
    return ledger_routes.post_layer_from_decision(box.target_key, ledger_routes.DecisionBody(**body), ident=factories.ident(OWNER))


def _status(out: dict) -> dict[tuple[str, str], str]:
    return {(c["code"], c["column"]): c["status"] for c in out["cells"]}


def test_a_decision_text_maps_onto_cells_with_four_statuses_and_becomes_a_layer(ledger_box):
    seed_ledger(ledger_box)
    out = _apply(ledger_box, decision_text=TEXT, mapping=MAPPING)
    status = _status(out)
    assert status[("R-001", "최종 등급")] == "filled"            # 앞 값 A 와 같다
    assert status[("R-001", "결정 출처")] == "conflict"          # 앞 값 '앞 회차' 와 다르다
    assert status[("R-001", "부품")] == "no_source"              # subject 에 part 가 없다
    assert status[("R-005", "결정 출처")] == "empty"
    assert status[("R-005", "최종 등급")] == "conflict"          # 앞 값(v2) C
    assert out["counts"] == {"filled": 8, "empty": 1, "conflict": 2, "no_source": 1}
    assert out["items_n"] == 4 and out["items_without_code"] == ["findings[2] F3"] and out["codes_new"] == ["R-020"]
    assert out["version_compared"] == 2 and out["source"] == {"kind": "decision_text", "votes_known": False}
    # 표결이 없으니 합의 문장을 견주지 못한다 — 그렇다고 말한다.
    assert out["tally"] is None and out["consistency"]["consensus_claim"] == "전원 합의로 아래와 같이 정한다."
    assert out["consistency"]["match"] is None and any("표결을 모른다" in n for n in out["notes"])
    layer = out["layer"]
    assert layer["origin"] == "decision" and layer["order"] == 60 and layer["source_file"] == "decision_text"
    assert layer["meta"]["counts"] == out["counts"]
    rows = ledger.layer_row(ledger_box.store, ledger_box.target_key, out["layer_id"])
    assert json.loads(rows["rows_json"])["R-005"] == {"최종 등급": "B", "비고": "합성 주장 둘", "부품": "PART-E"}
    built = ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=2, layers=[out["layer_id"]]),
                                       ident=factories.ident(OWNER))
    assert built["grade_changed_codes"] == ["R-005"]             # C → B


def test_a_decision_json_with_votes_flags_a_unanimity_claim_that_the_tally_contradicts(ledger_box):
    seed_ledger(ledger_box)
    engine = {"job_id": "dj-1", "job": "risk-review", "template": "risk-review",
              "decision_json": {"risk_spec": SPEC, "votes": {"tally": {"찬성": 3, "조건부": 1, "반대": 0}}, "cites": []},
              "consistency": {"consensus_claim": "전원 합의로 정한다", "tally": {}, "match": None, "note": ""}}
    out = _apply(ledger_box, decision_json=engine, mapping=MAPPING)
    assert out["tally"] == {"agree": 3, "conditional": 1, "oppose": 0}
    assert out["consistency"]["match"] is False and out["consistency"]["dissent"] == 1
    assert out["source"]["kind"] == "decision_json" and out["source"]["votes_known"] is True
    agreed = _apply(ledger_box, decision_json={"risk_spec": SPEC, "votes": {"tally": {"agree": 4}}}, mapping=MAPPING,
                    layer_name="합의 반영")
    assert agreed["consistency"]["match"] is None                 # 결정 JSON 에는 문장이 없다 — 견줄 합의 문장이 없다
    assert ledger_decision.consistency("이견 없이 정했다", {"agree": 4, "conditional": 0, "oppose": 0})["match"] is True


@pytest.mark.parametrize("text", ["전원 합의로 결정한다", "만장일치로 정했다", "좌석 모두 동의했다", "Agreed unanimously."])
def test_unanimity_phrases_are_found(text):
    assert ledger_decision.consensus_claim(text) is not None


def test_a_mapping_is_required_and_exactly_one_decision_input(ledger_box):
    seed_ledger(ledger_box)
    with pytest.raises(AppError) as exc:
        _apply(ledger_box, decision_text=TEXT)
    assert exc.value.code == "ledger_decision_map_missing"
    ledger_routes.put_template(ledger_box.target_key, "decision_map", MAPPING, ident=factories.ident(OWNER))
    assert _apply(ledger_box, decision_text=TEXT)["mapping_version"] == 1
    with pytest.raises(AppError) as exc:
        _apply(ledger_box, decision_text=TEXT, job_id="job-1")
    assert exc.value.http_status == 422
    with pytest.raises(AppError) as exc:
        _apply(ledger_box, decision_text="risk_spec 이 없는 결정문")
    assert exc.value.code == "decision_unparsable"
    with pytest.raises(AppError) as exc:
        _apply(ledger_box, decision_text=TEXT, mapping={"fields": {"grade": "없는 칸"}})
    assert exc.value.http_status == 422


class FakeGateway:
    """게이트웨이 deliberate_result 대역 — 11-17 엔진처럼 view=decision_json 을 모르면 도구 오류, summary 는 쪽 둘이다."""

    def __init__(self, *, knows_json: bool = False, refuse: bool = False) -> None:
        self.knows_json, self.refuse = knows_json, refuse
        self.calls: list[dict] = []
        self.closed = False

    def call(self, name: str, args: dict, deadline: float | None = None) -> dict:
        self.calls.append({"name": name, **args})
        if self.refuse:
            text = "read_only: 'deliberate_result' — 읽기 전용 토큰(scopes 에 read 만)은 조회 도구만 부른다."
            return {"ok": False, "error": "tool_error", "detail": text, "refusal": {"reason": "read-only", "tool": "deliberate_result",
                                                                                 "message": text}}
        if args.get("view") == "decision_json":
            if not self.knows_json:
                return {"ok": False, "error": "tool_error", "detail": "view 는 full · summary 가운데 하나다 — 받은 값: 'decision_json'"}
            return {"ok": True, "result": {"job_id": args["job_id"], "decision_json": {"risk_spec": SPEC,
                                                                                       "votes": {"tally": {"agree": 2, "oppose": 1}}}}}
        half = len(TEXT) // 2
        if args.get("part", 1) == 1:
            return {"ok": True, "result": {"job_id": args["job_id"], "view": "summary", "decision": TEXT[:half],
                                           "votes": {"tally": {"agree": 2, "conditional": 1, "oppose": 0, "abstain": 0, "total": 3}},
                                           "page": {"part": 1, "parts": 2, "next": {"job_id": args["job_id"], "view": "summary", "part": 2}}}}
        return {"ok": True, "result": {"job_id": args["job_id"], "decision": TEXT[half:], "page": {"part": 2, "parts": 2, "next": None}}}

    def close(self) -> None:
        self.closed = True


def test_a_job_id_reads_the_summary_pages_when_the_engine_has_no_decision_json_view(ledger_box, monkeypatch):
    seed_ledger(ledger_box)
    fake = FakeGateway()
    monkeypatch.setattr(ledger_routes, "decision_channel", lambda email: fake)
    out = _apply(ledger_box, job_id="job-1", mapping=MAPPING)
    assert [(c["name"], c.get("view"), c.get("part")) for c in fake.calls] == [
        ("deliberate_result", "decision_json", None), ("deliberate_result", "summary", None), ("deliberate_result", "summary", 2)]
    assert fake.closed is True
    assert out["source"] == {"kind": "job_id", "job_id": "job-1", "view_used": "summary", "votes_known": True, "votes_source": "summary"}
    assert out["tally"]["conditional"] == 1 and out["consistency"]["match"] is False
    assert out["layer"]["source_file"] == "deliberation:job-1" and out["layer"]["name"] == "결정 반영 job-1"
    # 엔진 가지(contracts §6)의 꼴 — 영문 표결 칸(responded · total 포함)과 risk_spec null 의 parse_error.
    engine = {"job_id": "job-3", "status": "done", "view": "decision_json", "job": "risk-review", "template": "risk-review",
              "decision_json": {"risk_spec": SPEC, "votes": {"tally": {"agree": 3, "conditional": 0, "oppose": 1, "abstain": 0,
                                                                       "responded": 4, "total": 4}, "unanimous": False, "by_seat": []},
                                "cites": [{"key": "b000000.f01", "n": 2}]},
              "consistency": {"consensus_claim": None, "tally": {}, "match": None, "note": ""}}
    exact = _apply(ledger_box, decision_json=engine, mapping=MAPPING, layer_name="엔진 꼴")
    assert exact["tally"] == {"agree": 3, "conditional": 0, "oppose": 1, "abstain": 0, "responded": 4, "total": 4}
    with pytest.raises(AppError) as exc:
        _apply(ledger_box, decision_json={**engine, "decision_json": {"risk_spec": None, "votes": {}}, "parse_error": "펜스가 깨졌다"},
               mapping=MAPPING)
    assert exc.value.code == "decision_unparsable" and "펜스가 깨졌다" in exc.value.message
    newer = FakeGateway(knows_json=True)
    monkeypatch.setattr(ledger_routes, "decision_channel", lambda email: newer)
    got = _apply(ledger_box, job_id="job-2", mapping=MAPPING)
    assert got["source"]["view_used"] == "decision_json" and len(newer.calls) == 1 and got["tally"] == {"agree": 2, "oppose": 1}


def test_a_read_only_refusal_or_a_missing_pat_is_said_before_anything_is_written(ledger_box, monkeypatch):
    seed_ledger(ledger_box)
    real = ledger_routes.decision_channel
    monkeypatch.setattr(ledger_routes, "decision_channel", lambda email: FakeGateway(refuse=True))
    with pytest.raises(AppError) as exc:
        _apply(ledger_box, job_id="job-1", mapping=MAPPING)
    assert exc.value.code == "decision_job_unreadable" and "read_only:" in exc.value.message
    assert exc.value.detail["refusal"]["reason"] == "read-only"
    monkeypatch.setattr(ledger_routes, "decision_channel", real)        # 진짜 채널 — 등록된 PAT 가 없다
    with pytest.raises(AppError) as exc:
        _apply(ledger_box, job_id="job-1", mapping=MAPPING)
    assert exc.value.code == "decision_pat_absent" and exc.value.http_status == 409
    assert ledger_box.store.query_one("SELECT COUNT(*) AS n FROM rr_ledger_layers WHERE origin = 'decision'")["n"] == 0


def test_the_gates_hold_on_rest_and_mcp(ledger_box):
    seed_ledger(ledger_box)
    body = ledger_routes.DecisionBody(decision_text=TEXT, mapping=MAPPING)
    for who, code in ((VIEWER, "role_insufficient"), (STRANGER, "E404")):
        with pytest.raises(AppError) as exc:
            ledger_routes.post_layer_from_decision(ledger_box.target_key, body, ident=factories.ident(who))
        assert exc.value.code == code
    ledger_box.act_as(None)
    assert call("risk_ledger_apply_decision", target_key=ledger_box.target_key, decision_text=TEXT,
                mapping=MAPPING)["error"] == "delegation_required"
    ledger_box.act_as(OWNER)
    out = call("risk_ledger_apply_decision", target_key=ledger_box.target_key, decision_text=TEXT, mapping=MAPPING)
    assert out["counts"]["conflict"] == 2 and out["layer_id"].startswith("ly-")
