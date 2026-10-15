# 카드 대조 검토의 마감(m2-wp3b S9) — finding 승격·의견 행·원장 마감과 패널 경로 격리(D-24)를 검토 루프가 만든 원장으로 본다
"""입력은 생산자다 — 대상·단위는 합성 쌍 → 실제 캡처·diff → 단위 빌드, 판정·호출 원장은 가짜 엔진을 꽂은 검토 루프(S8)가 쓰고,
마감은 그 루프의 `finalize_expert` 가 돈다(tests/synth/review_rig.py). 패널 원장은 러너가 실모듈로 돌린 패널이다(엔진만 대역).
"""
from __future__ import annotations

import ast
import dataclasses
import json
import re
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft7Validator

from app import cardpack, common, config, expert_report, export, metrics, narrative, nightly, planner, registry, routes, runner, units
from app.common import canonical_json
from tests import factories
from tests.rr import legacy_build as legacy
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

OWNER = rig.OWNER
SEAL = rig.SEAL
APP = Path(__file__).resolve().parents[1] / "app"
SCHEMA = json.loads((APP / "schemas" / "seat_opinion.v1.json").read_text(encoding="utf-8"))
UID_RE = re.compile(r"^[0-9a-f]{32}#[FG][0-9]+$")


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _rid(alias: str) -> str:
    return next(c["record_id"] for c in fre.load("pack_ok.json")["cards"] if c["alias"] == alias)


def _run(store, key: str | None = None, *, scope=None, verdicts=None, rev=None, offcard: int = 0,
         **switches) -> tuple[str, str, FakeReviewEngine]:
    """검토 잡 하나를 가짜 엔진으로 끝까지 — (대상, 잡, 가짜 엔진)."""
    key = key or rig.target(store)
    job_id = rig.job(store, key, scope=scope)
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {_rid(a): v for a, v in (verdicts or {}).items()}
    fake.rev_verdicts = {_rid(a): v for a, v in (rev or {}).items()}
    fake.offcard_findings = offcard
    for name, value in switches.items():
        setattr(fake, name, value)
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)
    return key, job_id, fake


def _findings(store, key: str, agent: str | None = None) -> list[dict]:
    sql = "SELECT * FROM rr_findings WHERE target_key = ?" + (" AND agent_key = ?" if agent else "")
    rows = [dict(r) for r in store.query(sql + " ORDER BY agent_key, unit_id", (key, agent) if agent else (key,))]
    for row in rows:
        row["json"] = json.loads(row["finding_json"])
    return rows


def _head(store, key: str, agent: str) -> dict:
    return dict(store.query_one("SELECT * FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?", (key, agent)))


def _unit_ids(store, key: str) -> list[str]:
    return [u["unit_id"] for u in units.load_units(store, key)]


def _card_bodies() -> list[str]:
    """얼린 카드의 절 글 가운데 인용(앞 40자)보다 긴 것 — finding·반출에 통째로 실리면 안 된다(P-06)."""
    return [str(s["text"]) for c in fre.load("pack_ok.json")["cards"] for s in c["sections"] if len(str(s["text"])) > 40]


# ---------------------------------------------------------------- 승격
def test_flagged_cards_on_one_change_fold_into_one_finding_held_at_warning(store):
    """같은 전문가의 카드 셋(FAIL·WARNING·FAIL)이 같은 변경 · 같은 메커니즘이면 단위마다 finding 하나에 cards[] 셋이다. hold 정책 —
    등록부로 갈 값은 WARNING · 중대이고 원래 판정은 judgement_claimed 에 FAIL 로 남는다. 패널 자리는 비고 출처 넷이 차며 회수
    자격은 0 이다(등록부 병합은 검토 잡 끝의 사슬 몫이다 — 재설계 M3 S3-5, tests/test_chain.py). 근거 문장에 카드 참조·인용이 있어도 수치 대조가 깨지지 않고(P-05) finding 글에 카드 본문이
    없다(P-06). 걸린 줄은 같은 메커니즘 코드를 단다(cr-verdict-2 — 메커니즘이 없으면 cells 대상에서는 카드마다 갈린다, M3 S3-3 ·
    tests/test_review_mech.py)."""
    key, _job, _fake = _run(store, scope={"agents": [SEAL]},
                            verdicts={"K01": ("yes", "FAIL"), "K02": ("yes", "WARNING"), "K03": ("yes", "FAIL")},
                            mechs={_rid(a): ("interface.clearance", "") for a in ("K01", "K02", "K03")})
    review_id = _head(store, key, SEAL)["review_id"]
    rows = _findings(store, key)
    assert sorted(r["unit_id"] for r in rows) == sorted(_unit_ids(store, key))
    for row in rows:
        fj = row["json"]
        assert [c["alias"] for c in fj["cards"]] == ["K01", "K02", "K03"]
        assert [c["judgement"] for c in fj["cards"]] == ["FAIL", "WARNING", "FAIL"]
        assert (row["severity"], row["judgement"], fj["judgement_claimed"], fj["severity_claimed"]) == (
            "중대", "WARNING", "FAIL", "중대")
        assert (row["panel_id"], row["source_kind"], row["source_id"], row["agent_key"], row["unit_id"]) == (
            None, "card_review", review_id, SEAL, fj["unit_ids"][0])
        assert (row["origin"], row["status"], row["recall_eligible"], fj["raised_by"]) == ("llm", "open", 0, [SEAL])
        assert UID_RE.match(row["claim_uid"]) and row["finding_id"] == row["claim_uid"]
        assert row["claim_uid"] == expert_report.claim_uid_of(review_id, "risk", row["cluster_key"], row["unit_id"])
        assert fj["warrant"].startswith(f"근거 카드 [card:{_rid('K01')}] «")
        assert (fj["unquoted_numbers"], fj["quote_mismatch"], fj["dangling"]) == ([], [], [])
        assert fj["cites"][0] == {"ref": f"card:{_rid('K01')}", "quote": fj["cites"][0]["quote"]}
        assert not any("canonical" in c for c in fj["_resolved_cites"] if c["ref_type"] == "card")
        assert not [body for body in _card_bodies() if body in row["finding_json"]]
    refs = {r["ref"] for r in store.query("SELECT ref FROM rr_claim_refs WHERE claim_uid = ?", (rows[0]["claim_uid"],))}
    assert {f"card:{_rid(a)}" for a in ("K01", "K02", "K03")} <= refs
    assert routes.claims_for_ref(f"card:{_rid('K01')}", owner_sub=OWNER)["claims"]      # '이 카드를 근거로 든 지적'


def test_each_expert_raises_its_own_finding_in_a_shared_cluster(store):
    """카드 전문가 넷이 같은 단위에서 같은 카드를 걸면 cluster_key 는 같고 finding 은 전문가마다 하나다 — raised_by 는 서로 다른
    한 명씩이고 claim_uid 머리는 그 전문가의 review_id 다(지지 수를 전문가 수로 셀 WP4 의 바탕)."""
    key = rig.target(store)
    unit = _unit_ids(store, key)[0]
    _run(store, key, scope={"agents": list(rig.CARD_EXPERTS), "unit_ids": [unit]}, verdicts={"K01": ("yes", "FAIL")})
    rows = _findings(store, key)
    assert sorted(r["agent_key"] for r in rows) == sorted(rig.CARD_EXPERTS)
    assert len({r["cluster_key"] for r in rows}) == 1 and len({r["claim_uid"] for r in rows}) == 4
    for row in rows:
        assert row["json"]["raised_by"] == [row["agent_key"]]
        assert row["claim_uid"].split("#")[0] == _head(store, key, row["agent_key"])["review_id"] == row["source_id"]


def test_a_card_the_variants_split_on_becomes_an_undetermined_finding(store):
    """fwd 는 걸림 없음, rev 는 FAIL 인 카드 — 단독 재질의가 걸림 없음이어도 실효는 undetermined(split)이고 finding 으로 오른다
    (X1-14). 판정은 undetermined 그대로, 심각도는 원래 FAIL 의 중대, 원래 판정은 judgement_claimed 에 있다."""
    key = rig.target(store)
    unit = _unit_ids(store, key)[0]
    _run(store, key, scope={"agents": [SEAL], "unit_ids": [unit]}, rev={"K01": ("yes", "FAIL")})
    eff = store.query_one("SELECT variant, judgement, split FROM rr_card_verdicts WHERE target_key = ? AND record_id = ?"
                          " AND is_effective = 1", (key, _rid("K01")))
    assert (eff["variant"], eff["judgement"], eff["split"]) == ("solo", "OK", 1)          # 행은 solo 의 답, 실효는 split
    assert store.query_one("SELECT n_undetermined FROM rr_review_cells WHERE target_key = ? AND agent_key = ?"
                           " AND unit_id = ?", (key, SEAL, unit))["n_undetermined"] == 1
    (row,) = _findings(store, key)
    assert (row["judgement"], row["severity"], row["json"]["judgement_claimed"], row["json"]["split"]) == (
        "undetermined", "중대", "FAIL", True)
    assert [c["alias"] for c in row["json"]["cards"]] == ["K01"]


def test_off_card_rows_become_findings_and_an_unclassified_text_is_queued_once_per_target(store):
    """카드 밖 f 줄이 finding 이 된다(카드 근거 없음 — 등급 경험칙, 판정 WARNING · 중대). 택소노미 밖 메커니즘 원문은 그 대상에서
    한 번만 큐에 오른다 — 전문가 둘 × 단위 다섯이 같은 말을 올려도 큐는 한 줄이고, 야간 미분류 스캔은 검토 finding 을 다시 올리지
    않는다."""
    key, _job, _fake = _run(store, scope={"agents": [rig.ZERO_CARDS, rig.BACKGROUND_ONLY]}, offcard=2)
    rows = _findings(store, key)
    assert len(rows) == 2 * len(_unit_ids(store, key))
    for row in rows:
        fj = row["json"]
        assert (fj["off_card"], fj["off_card_n"], fj["cards"], row["direction"]) == (True, 2, [], "risk")
        assert (row["judgement"], row["severity"], row["evidence_grade"]) == ("WARNING", "중대", "경험칙")
        assert (row["mechanism_detail"], row["mechanism_free"], fj["judgement_claimed"]) == ("unclassified", "계면 박리", None)
    queued = [json.loads(r["payload_json"]) for r in store.query(
        "SELECT payload_json FROM rr_curation_queue WHERE kind = 'unclassified_code'")]
    assert [(q["mechanism_free"], q["target_key"], q["source_kind"]) for q in queued] == [("계면 박리", key, "card_review")]
    assert nightly.scan_unclassified(store, now=common.now_epoch()) == {"n_unclassified": 0, "queued": 0}


def test_an_untitled_off_card_row_is_kept_with_a_fallback_title_and_becomes_a_finding(store):
    """반대 검토 2차 HIGH 1(a) · D-46 — 엔진의 _check_f 는 제목을 묻지 않는다(RB-1 이 제목 없는 f 줄을 다룬다). 앱이 제목 없는 카드 밖
    f 줄을 버려(no_title) 카드 밖 걸림이 결과에서 사라졌다 — 셀은 reviewed · n_offcard 0 · finding 0, 흔적은 호출 원장의 dropped
    뿐이었다. 경로로 제목을 대신하고 title_fallback 표지를 단다(q1 과 같은 규칙)."""
    key, _job, _fake = _run(store, scope={"agents": [rig.ZERO_CARDS]}, offcard=1, offcard_title="")
    cells = [dict(r) for r in store.query("SELECT n_offcard, extras_json FROM rr_review_cells WHERE target_key = ?"
                                          " AND agent_key = ?", (key, rig.ZERO_CARDS))]
    assert cells and all(c["n_offcard"] == 1 for c in cells)
    row = json.loads(cells[0]["extras_json"])["offcard"]["findings"][0]
    assert (row["title"], row.get("title_fallback")) == ("변경 줄의 계면", True)
    assert len(_findings(store, key, rig.ZERO_CARDS)) == len(_unit_ids(store, key))
    dropped = [json.loads(r["quality_json"])["app"]["dropped"] for r in store.query(
        "SELECT quality_json FROM rr_review_calls WHERE target_key = ? AND kind = 'offcard' AND state = 'ok'", (key,))]
    assert dropped and all("no_title" not in d for d in dropped)


# ---------------------------------------------------------------- 의견 행 · 원장
def test_the_opinion_row_is_a_complete_seat_opinion_in_the_review_band_and_closes_the_cells_ledger(store):
    """의견 행은 seat_opinion.v1 을 통과하고(필수 칸 전부) 패널 자리가 review_id, 회차가 501 이다. 걸림이 있으면 conditional,
    아무것도 안 걸린 역할만의 전문가는 agree 다. 요약은 1,500자 안이고 excerpt_for_rag·turns[0]·머리의 summary_md 가 같은 글이다.
    flow='cells' 대상이라 원장이 닫히고(검증된 근거 — done, 카드 0장 — done_weak), 모델 층화가 review_id 로 그 모델을 찾는다."""
    key, _job, _fake = _run(store, scope={"agents": [SEAL, rig.ZERO_CARDS]}, verdicts={"K02": ("yes", "WARNING")})
    validator = Draft7Validator(SCHEMA)
    assert narrative.REVIEW_CYCLE_BASE < narrative.NONLEDGER_CYCLE_BASE
    stance = {}
    for agent in (SEAL, rig.ZERO_CARDS):
        head = _head(store, key, agent)
        row = store.query_one("SELECT * FROM rr_seat_opinions WHERE panel_id = ?", (head["review_id"],))
        opinion = json.loads(row["opinion_json"])
        assert list(validator.iter_errors(opinion)) == []
        assert (row["cycle"], opinion["cycle"], opinion["panel_id"], row["origin"]) == (501, 501, head["review_id"], "primary")
        assert row["opinion_id"] == narrative._opinion_id(head["review_id"], agent, 501) == head["opinion_id"]
        assert opinion["excerpt_for_rag"] == opinion["turns"][0]["say_excerpt"] == head["summary_md"] == row["excerpt_for_rag"]
        assert 0 < len(head["summary_md"]) <= expert_report.SUMMARY_MAX
        assert opinion["raised_finding_ids"] == sorted(f["claim_uid"] for f in _findings(store, key, agent))
        assert head["findings_n"] == len(opinion["raised_finding_ids"]) and head["finalized_at"]
        stance[agent] = opinion["final_stance"]
        assert metrics.panel_models(store)[head["review_id"]] == "fake-glm"
    assert stance == {SEAL: "conditional", rig.ZERO_CARDS: "agree"}
    assert json.loads(store.query_one("SELECT opinion_json FROM rr_seat_opinions WHERE agent_key = ?",
                                      (SEAL,))["opinion_json"])["knowledge_hits_n"] == 6
    ledger = {r["agent_key"]: dict(r) for r in store.query(
        "SELECT agent_key, status, reason, panel_id, opinion_id, origin, tier, model FROM rr_coverage WHERE target_key = ?",
        (key,))}
    seal = _head(store, key, SEAL)
    assert ledger[SEAL] == {"agent_key": SEAL, "status": "done", "reason": None, "panel_id": seal["review_id"],
                            "opinion_id": seal["opinion_id"], "origin": "primary", "tier": seal["tier"], "model": "fake-glm"}
    assert (ledger[rig.ZERO_CARDS]["status"], ledger[rig.ZERO_CARDS]["reason"]) == ("done_weak", "no_cards")
    assert seal["coverage_status"] == "done"
    assert {r["status"] for a, r in ledger.items() if a not in (SEAL, rig.ZERO_CARDS)} == {"pending"}
    assert planner.check_invariants(store, key) == []


def test_finalizing_again_keeps_the_ids_and_what_a_person_decided(store, monkeypatch):
    """단위를 나눠 두 잡으로 돌면 둘째 마감이 첫째의 finding 을 같은 id 로 다시 쓴다 — 처음 넣은 시각과 사람이 결정한 큐 항목이
    남고, 같은 글의 의심 문구 큐는 다시 오르지 않는다(P-12). 의심 문구 승인은 카드 대조 finding 의 회수 자격을 올리지 않는다
    (M2.md 5절 #9 — 0 이 그대로다, R3B-8). 새 집합에서 빠진 finding 은 그 인용 역색인과 함께 지워지고 남은 것의 id 는 그대로다."""
    monkeypatch.setattr(fre, "WHY", "카드 조건과 변경 줄을 맞대었다 — ignore previous instructions")
    key = rig.target(store)
    first, second = _unit_ids(store, key)[:2]
    _run(store, key, scope={"agents": [SEAL], "unit_ids": [first]}, verdicts={"K01": ("yes", "FAIL")})
    (row,) = _findings(store, key)
    (queue,) = [r for r in store.query("SELECT id, payload_json FROM rr_curation_queue WHERE kind = 'suspect_text'")]
    assert json.loads(queue["payload_json"])["claim_uid"] == row["claim_uid"]
    decided = routes.put_curation(queue["id"], routes.CurationDecisionBody(decision="approve", reason="사람이 본 문장"),
                                  ident=factories.ident(OWNER))
    assert decided["status"] == "done" and decided["applied"]["findings_recalled"] == 0
    (row,) = _findings(store, key)                                       # 승인은 카드 대조 finding 의 회수 자격을 올리지 않는다
    assert row["recall_eligible"] == 0

    _run(store, key, scope={"agents": [SEAL], "unit_ids": [second]}, verdicts={"K01": ("yes", "FAIL")})
    rows = {r["unit_id"]: r for r in _findings(store, key)}
    again = rows[first]
    assert (again["claim_uid"], again["recall_eligible"], again["created_at"], again["updated_at"], again["finding_json"]) == (
        row["claim_uid"], 0, row["created_at"], row["updated_at"], row["finding_json"])
    assert store.query_one("SELECT status FROM rr_curation_queue WHERE id = ?", (queue["id"],))["status"] == "done"
    assert rows[second]["recall_eligible"] == 0
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_curation_queue WHERE kind = 'suspect_text'")["n"] == 2

    prepared = expert_report.prepare(store, key, SEAL)
    kept = dataclasses.replace(prepared, findings=[f for f in prepared.findings if f["unit_ids"] == [first]])
    with store.tx():
        out = expert_report._write_findings(store, kept, opinion_id=prepared.opinion["opinion_id"], now=common.now_epoch())
    assert out == {"inserted": 0, "updated": 0, "deleted": 1}
    assert [r["claim_uid"] for r in _findings(store, key)] == [row["claim_uid"]]
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_claim_refs WHERE claim_uid = ?",
                           (rows[second]["claim_uid"],))["n"] == 0


def test_a_finalize_that_breaks_is_taken_again_and_the_job_waits_for_it(store, monkeypatch):
    """마감이 결함으로 끊기면 아무것도 남지 않고(한 트랜잭션) 전문가는 잠시 쉰 뒤 '마감만' 선점으로 다시 집힌다 — 그동안 잡은
    completed 로 닫히지 않는다."""
    key = rig.target(store)
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": _unit_ids(store, key)[:1]})
    r = rig.Rig(store, FakeReviewEngine(rig.packs()))
    real = expert_report.prepare
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("마감 결함")
        return real(*args, **kwargs)

    monkeypatch.setattr(expert_report, "prepare", flaky)
    for _ in range(6):
        r.tick()
        if calls:
            break
        r.clock.advance(61)
    head = _head(store, key, SEAL)
    assert (head["state"], head["error"], head["opinion_id"]) == ("planned", "internal_error", None)
    r.tick()
    assert rig.state(store, job_id) == "running"
    r.finish(job_id)
    head = _head(store, key, SEAL)
    assert (head["state"], head["error"], len(calls)) == ("partial", None, 2) and head["opinion_id"]
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_seat_opinions WHERE panel_id = ?", (head["review_id"],))["n"] == 1


# ---------------------------------------------------------------- D-24 — 패널 경로는 검토 finding 을 읽지 않는다
def _panel_spec(store, key: str):
    """그 diff 의 의미 이벤트(주체 ckey 가 있는 것) 둘을 인용하는 risk_spec — 좌석 목록 → spec."""
    target = store.query_one("SELECT ref_id, project_id, ir_hash FROM rr_targets WHERE target_key = ?", (key,))
    diff = store.query_one("SELECT id, base_snapshot_id, target_snapshot_id, diff_json FROM rr_diffs WHERE id = ?",
                           (target["ref_id"],))
    events = [e for e in json.loads(diff["diff_json"])["semantic"]["events"] if e["subject"]["ckeys"]][:2]
    domain_of = {r["key"]: r["domain"] for r in rig.ROSTER}

    def spec(seats: list[str]) -> dict:
        seat = seats[0]

        def finding(fid: str, direction: str, detail: str, event: dict) -> dict:
            return {"id": fid, "direction": direction, "domain": domain_of.get(seat, "mech"), "mechanism": "mechanical",
                    "mechanism_detail": detail, "change_kind": event["change_kind"],
                    "subject": {"ckeys": list(event["subject"]["ckeys"]), "names": []}, "trigger_condition": "none",
                    "severity": "중대" if direction == "risk" else "경미",
                    "judgement": "FAIL" if direction == "risk" else "OK",
                    "detectability": {"level": "sim-detectable", "tool": "report_part_risk"}, "evidence_grade": "도구예측",
                    "precedent": "none", "cites": [{"ref": event["cid"], "quote": event["text"]}], "tool_calls": [],
                    "claim": "변경 이벤트가 낙하 응력 경로를 바꾼다.", "warrant": "diff 의미 이벤트가 그 경로를 짚는다.",
                    "resolving_check": {"kind": "sim", "ref": "낙하 해석 재실행"}, "owner_domain": domain_of.get(seat, "mech"),
                    "raised_by": [seat], "contested_by": [], "contest_note": "", "status": "open"}

        facets = ("intent", "constraint", "anomaly", "lineage", "vulnerability", "strength", "tradeoff", "unknown")
        return {"schema": "risk_spec", "version": "1.0", "taxonomy_version": "1.0",
                "scope": {"kind": "diff", "target_key": key, "project_refs": [target["project_id"]],
                          "ir_refs": [diff["base_snapshot_id"], diff["target_snapshot_id"]], "diff_ref": diff["id"],
                          "ir_hash": target["ir_hash"]},
                "findings": [finding("F1", "risk", "drop_stress", events[0]), finding("F2", "risk", "drop_stress", events[1])],
                "gains": [finding("G1", "improvement", "drop_stress", events[0])], "cross_domain": [], "open_items": [],
                "character": {"one_liner": "합성 변경 쌍.",
                              "facets": [{"facet": f, "statements": [], "na_reason": "좌석 미기재"} for f in facets]},
                "coverage": {"seats": [{"key": k, "domain": domain_of.get(k, "mech"), "origin": "primary"} for k in seats],
                             "domains_seated": sorted({domain_of.get(k, "mech") for k in seats}), "domains_missing": []},
                "verdict": "no-go", "verdict_conditions": [],
                "evidence_profile": {"tool": 2, "card": 0, "precedent": {"verified": 0, "dismissed": 0}, "heuristic": 0,
                                     "measured": 0}}
    return spec


def _panel_view(store, key: str, monkeypatch) -> str:
    """패널 경로가 내는 것 — 등록부 병합의 반환·행·선례 기여, 완결 레벨, 판정 후보, 원장. 시각은 한 값으로 묶어 바이트로 견준다."""
    with monkeypatch.context() as m:
        m.setattr(common, "now_epoch", lambda: 1_800_000_000)
        merged = registry.merge(store, key)
        rows = [dict(r) for r in store.query("SELECT * FROM rr_registry WHERE target_key = ? ORDER BY cluster_key", (key,))]
        contrib = [dict(r) for r in store.query("SELECT * FROM rr_delta_contrib WHERE target_key = ? ORDER BY 1, 2, 3",
                                                (key,))]
        level = registry.close_level(store, key, persist=False)
        candidate = registry.verdict_candidate(store, key)
    coverage = [dict(r) for r in store.query("SELECT * FROM rr_coverage WHERE target_key = ? ORDER BY agent_key", (key,))]
    return canonical_json({"merge": merged, "registry": rows, "contrib": contrib, "close_level": level,
                           "candidate": candidate, "coverage": coverage})


def test_a_review_laid_over_a_panel_target_leaves_its_registry_and_close_level_byte_identical(store, tmp_path, monkeypatch):
    """D-24 — 패널을 돌려 등록부·선례 기여가 선 대상(flow='panels')에 카드 대조를 얹어 FAIL finding 이 같은 대상에 쌓여도 등록부
    병합의 결과·행, 완결 레벨, 판정 후보, 원장이 바이트로 같다. 원장은 닫지 않고(#8) 같은 전문가의 패널 의견(원장 회차)과 검토
    의견(501)이 함께 든다."""
    def refused(*args, **_kwargs):
        raise httpx.ConnectError("시험은 외부를 부르지 않는다.", request=args[-1])

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refused)       # 브리프의 필드 근거가 실 게이트웨이에 닿지 않게
    synth = factories.make_diff_target(store, 40, open_target=False)
    key = routes.create_target(routes.TargetBody(kind="diff", ref_id=synth.diff_id, consent=True, flow="panels",
                                                 agents=[dict(r) for r in rig.ROSTER]), ident=factories.ident(OWNER))["target_key"]
    rig.pat(store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(store, key, "C", owner_sub=OWNER, consent=True, settings=cfg)
    engine = legacy.LegacyEngine(_panel_spec(store, key))
    while (job := runner.claim_next_job(store, cfg)) is not None:
        runner.run_panel(store, cfg, engine, job)
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_registry WHERE target_key = ?", (key,))["n"] > 0
    seated = [r["agent_key"] for r in store.query("SELECT agent_key FROM rr_coverage WHERE target_key = ? AND panel_id"
                                                  " IS NOT NULL ORDER BY agent_key", (key,))]
    before = _panel_view(store, key, monkeypatch)

    units.build_units(store, key, built_by=OWNER)
    agent = SEAL if SEAL in seated else seated[0]
    _run(store, key, scope={"agents": [agent]}, verdicts={"K01": ("yes", "FAIL"), "K02": ("yes", "WARNING")}, offcard=1)
    review = _findings(store, key, agent)
    assert review and all(r["source_kind"] == "card_review" for r in review)
    assert _panel_view(store, key, monkeypatch) == before
    cycles = sorted(r["cycle"] for r in store.query("SELECT cycle FROM rr_seat_opinions WHERE target_key = ? AND agent_key = ?",
                                                    (key, agent)))
    assert cycles[-1] == 500 + store.query_one("SELECT cycle FROM rr_coverage WHERE target_key = ? AND agent_key = ?",
                                               (key, agent))["cycle"] and len(cycles) >= 2
    assert _head(store, key, agent)["coverage_status"] == store.query_one(
        "SELECT status FROM rr_coverage WHERE target_key = ? AND agent_key = ?", (key, agent))["status"]


# 패널 경로가 아닌데 rr_findings 를 읽는 자리 — 카드 대조 finding 을 일부러 읽는다. 까닭 없이 이 목록을 넓히지 않는다.
REVIEW_READERS: dict[tuple[str, str], str] = {
    ("expert_report.py", "_write_findings"): "검토 마감 자신의 finding(source_id = review_id)",
    ("routes.py", "claims_for_ref"): "risk_claims_for_ref('card:…') 가 이 카드를 근거로 든 검토 지적을 돌려준다(M2.md 5절 #18)",
    ("routes.py", "_ref_from_store"): "narr: 참조가 finding 을 id 로 짚는다 — 짚은 것을 그대로 푼다",
    ("routes.py", "_human_finding_row"): "id 로 짚은 finding — 사람 finding 이 아니면 llm_finding_immutable 로 거절한다",
    ("routes.py", "put_curation"): "큐 항목이 가리키는 finding(검토 마감이 올린 미분류 메커니즘 항목 포함)",
    ("learning.py", "plan_remap"): "택소노미 재매핑은 finding 전부의 별칭을 더한다(cluster_key 는 바이트 불변)",
    ("brief.py", "_finding_subjects"): "E7 이 다른 대상의 의견 행(검토 의견 포함 — 설계서대로 둔다)이 올린 finding 의 주체를 본다",
    ("registry.py", "_load_findings"): "거름 글이 상수 FINDING_SCOPE_SQL 에서 온다(M3 S3-4 — 카드 대조 finding 은 cells 대상만)",
    ("registry.py", "_contested_marking_done"): "거름 글이 상수 FINDING_SCOPE_SQL 에서 온다(M3 S3-4 — 위와 같은 범위)",
    ("routes.py", "_cluster_finding_ids"): "거름 글이 상수 FINDING_SCOPE_SQL 에서 온다(M3 S3-4 — 등록부와 같은 범위)",
    ("issues.py", "_card_atoms"): "카드 대조 원자만 읽는다(source_kind = 카드 대조 — 쟁점 유형의 원천, M3 S3-6)",
    ("issues.py", "_panel_atoms"): "쟁점 패널 자신의 원자(panel_id + source_kind = issue_panel — 결과 판정, M3 S3-7)",
    ("brief.py", "_issue_side"): "쟁점 근거 I4 — 제기자의 finding 을 id 로 짚는다(카드 밖 지적의 주장 줄, M3 S3-7)",
}
_READ_SQL = re.compile(r"\b(?:FROM|JOIN)\s+rr_findings\b", re.IGNORECASE)


def _findings_readers(source: str) -> list[tuple[str, int, bool]]:
    """(함수, 줄, source_kind 를 거르나) — SELECT 글 가운데 rr_findings 를 읽는 것(f-string 은 상수 조각을 이어 본다)."""
    out: list[tuple[str, int, bool]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.where = ["<module>"]

        def visit_FunctionDef(self, node: ast.AST) -> None:
            self.where.append(node.name)
            self.generic_visit(node)
            self.where.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
            self._check("".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)),
                        node.lineno)

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str):
                self._check(node.value, node.lineno)

        def _check(self, text: str, line: int) -> None:
            if _READ_SQL.search(text) and re.search(r"\bSELECT\b", text, re.IGNORECASE):
                out.append((self.where[-1], line, "source_kind" in text and "card_review" in text))

    Visitor().visit(ast.parse(source))
    return out


def test_every_panel_path_reader_of_rr_findings_filters_card_review_findings():
    """M2.md 5절 #20 — rr_findings 를 읽는 SELECT 는 전부 `COALESCE(source_kind, '') <> 'card_review'` 를 건다. 일부러 검토 finding
    을 읽는 자리는 위 목록에 까닭과 함께 있다. 새 조회가 거르지 않고 생기면 여기서 붉다."""
    found: dict[tuple[str, str], list[int]] = {}
    for path in sorted(APP.rglob("*.py")):
        for function, line, filtered in _findings_readers(path.read_text(encoding="utf-8")):
            if not filtered:
                found.setdefault((path.name, function), []).append(line)
    assert sorted(found) == sorted(REVIEW_READERS), found
    readers = [r for path in APP.rglob("*.py") for r in _findings_readers(path.read_text(encoding="utf-8"))]
    assert len(readers) >= 24                       # 검토 2라운드가 센 패널 경로 조회 24곳 + 검토 쪽(줄면 이 가드가 눈을 감았다)


def test_the_reader_guard_sees_an_unfiltered_query():
    """가드가 실제로 찾는다 — 거르지 않은 SELECT(f-string 조각 포함)는 잡히고, 거른 것과 쓰기 문장은 잡히지 않는다."""
    source = ('def a(store, k):\n    return store.query(f"SELECT {cols} FROM rr_findings WHERE target_key = ?", (k,))\n'
              'def b(store):\n    return store.query("SELECT 1 FROM rr_findings WHERE COALESCE(source_kind, \'\') <> '
              '\'card_review\'")\n'
              'def c(store):\n    store.execute("DELETE FROM rr_findings WHERE panel_id = ?", ("p",))\n')
    assert [(f, ok) for f, _line, ok in _findings_readers(source)] == [("a", False), ("b", True)]


# rr_seat_opinions 를 읽는데 카드 대조 검토의 의견 행(panel_id = review_id)을 거르지 않는 자리와 그 까닭(R3B-9). 패널 경로의 판단
# (좌석 승계·등록부·지표)에 검토 의견이 섞이지 않게 한다 — 까닭 없이 이 목록을 넓히지 않는다.
OPINION_READERS: dict[tuple[str, str], str] = {
    ("brief.py", "_seat_memory_line"): "E7 좌석 기억 — 다른 대상의 의견 행(검토 의견 포함)을 읽는다(계획이 남겨 둔 예외, _finding_subjects 와 같다)",
    ("expert_report.py", "_write_opinion"): "검토 마감 자신의 의견 행(opinion_id 로 외부 반영 열을 이어받는다)",
    ("learning.py", "collect_atoms"): "opinion_id → agent_key 지도 — 찾는 쪽이 이미 거른 finding(#20)의 opinion_id 라 검토 의견은 찾아지지 않는다",
    ("metrics.py", "_load_atoms"): "opinion_id → agent_key 지도 — 찾는 쪽이 이미 거른 finding(#20)의 opinion_id 라 검토 의견은 찾아지지 않는다",
    ("narrative.py", "_release_ledger_cycles"): "원장 회차(1~)로 찾는다 — 검토 의견은 500 대역이라 같은 회차가 아니다",
    ("planner.py", "apply_carry_over"): "원장(rr_coverage.opinion_id)이 받은 의견만 — 패널 대상의 원장은 검토가 닫지 않는다(#8)",
    ("registry.py", "_minutes_lines"): "panel_id = rr_panels 행의 id — 검토 id 는 패널 id 가 아니다",
    ("routes.py", "_queue_visibility_retag"): "과제 가시성이 바뀌면 그 대상의 AIDataHub 레코드 전부(검토 의견 포함)에 태그를 다시 단다",
    ("routes.py", "panel_transcript_payload"): "panel_id = rr_panels 행(문지기가 패널 행을 먼저 본다) — 검토 id 로는 부를 수 없다",
}
_OPINION_SQL = re.compile(r"\b(?:FROM|JOIN)\s+rr_seat_opinions\b", re.IGNORECASE)


def _opinion_readers(source: str) -> list[tuple[str, int, bool]]:
    """(함수, 줄, 검토 의견을 거르나) — SELECT 글 가운데 rr_seat_opinions 를 읽는 것. 거름은 panel_id 를 그 대상의 검토 id
    (rr_expert_reports.review_id) 밖으로 두는 것이다."""
    out: list[tuple[str, int, bool]] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.where = ["<module>"]

        def visit_FunctionDef(self, node: ast.AST) -> None:
            self.where.append(node.name)
            self.generic_visit(node)
            self.where.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
            self._check("".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)),
                        node.lineno)

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str):
                self._check(node.value, node.lineno)

        def _check(self, text: str, line: int) -> None:
            if _OPINION_SQL.search(text) and re.search(r"\bSELECT\b", text, re.IGNORECASE):
                filtered = bool(re.search(r"panel_id\s+NOT\s+IN\s*\(\s*SELECT\s+review_id\s+FROM\s+rr_expert_reports", text,
                                          re.IGNORECASE))
                out.append((self.where[-1], line, filtered))

    Visitor().visit(ast.parse(source))
    return out


def test_every_panel_path_reader_of_seat_opinions_leaves_the_review_band_out():
    """R3B-9 — #20 의 가드를 의견 행으로 넓힌다. rr_seat_opinions 를 읽는 SELECT 는 검토 의견(panel_id = review_id)을 거르거나 위
    목록에 까닭과 함께 있다. 다음 리비전의 좌석 승계(_supersede_previous_target)는 거른다."""
    found: dict[tuple[str, str], list[int]] = {}
    filtered: set[tuple[str, str]] = set()
    for path in sorted(APP.rglob("*.py")):
        for function, line, ok in _opinion_readers(path.read_text(encoding="utf-8")):
            (filtered.add((path.name, function)) if ok else found.setdefault((path.name, function), []).append(line))
    assert sorted(found) == sorted(OPINION_READERS), found
    assert ("routes.py", "_supersede_previous_target") in filtered
    source = ('def a(store, k):\n    return store.query("SELECT agent_key FROM rr_seat_opinions WHERE target_key = ?", (k,))\n'
              'def b(store, k):\n    return store.query("SELECT agent_key FROM rr_seat_opinions WHERE target_key = ? AND panel_id'
              ' NOT IN (SELECT review_id FROM rr_expert_reports WHERE target_key = ?)", (k, k))\n'
              'def c(store):\n    store.execute("DELETE FROM rr_seat_opinions WHERE panel_id = ?", ("p",))\n')
    assert [(f, ok) for f, _line, ok in _opinion_readers(source)] == [("a", False), ("b", True)]


def test_the_next_revision_carries_seats_over_on_panel_opinions_only(store, tmp_path, monkeypatch):
    """R3B-9 — 패널을 돈 대상에 카드 대조를 얹으면 검토 의견(501)도 cited_ckeys(걸린 단위의 바뀐 부품)를 싣는다. 같은 과제의 다음
    리비전을 열 때 좌석 승계(apply_carry_over)에 넘기는 인용 ckey 는 패널 의견의 것뿐이다 — 검토 의견의 ckey 가 섞이면 그 좌석이
    바뀐 부품에 걸려 승계되지 않는다(패널 쪽 원장이 검토 때문에 바뀐다, D-24)."""
    def refused(*args, **_kwargs):
        raise httpx.ConnectError("시험은 외부를 부르지 않는다.", request=args[-1])

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refused)
    synth = factories.make_diff_target(store, 40, open_target=False)
    key = routes.create_target(routes.TargetBody(kind="diff", ref_id=synth.diff_id, consent=True, flow="panels",
                                                 agents=[dict(r) for r in rig.ROSTER]), ident=factories.ident(OWNER))["target_key"]
    rig.pat(store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(store, key, "C", owner_sub=OWNER, consent=True, settings=cfg)
    engine = legacy.LegacyEngine(_panel_spec(store, key))
    while (job := runner.claim_next_job(store, cfg)) is not None:
        runner.run_panel(store, cfg, engine, job)
    seated = sorted(r["agent_key"] for r in store.query("SELECT agent_key FROM rr_coverage WHERE target_key = ? AND panel_id"
                                                        " IS NOT NULL", (key,)))
    units.build_units(store, key, built_by=OWNER)
    agent = SEAL if SEAL in seated else seated[0]
    _run(store, key, scope={"agents": [agent]}, verdicts={"K01": ("yes", "FAIL")})

    def ckeys(where: str) -> set[str]:
        return {str(k) for r in store.query(f"SELECT opinion_json FROM rr_seat_opinions WHERE target_key = ? AND agent_key = ?"
                                            f" AND {where}", (key, agent))
                for k in json.loads(r["opinion_json"]).get("cited_ckeys") or ()}

    review_id = _head(store, key, agent)["review_id"]
    review_only = ckeys(f"panel_id = '{review_id}'") - ckeys(f"panel_id <> '{review_id}'")
    assert review_only, "검토 의견이 패널 의견 밖의 ckey 를 싣지 않는다 — 이 시험은 아무것도 보지 않는다"
    seen: dict = {}
    real = planner.apply_carry_over

    def spy(store_, target_key, prev_target_key, cited_ckeys, changed_ckeys, **kwargs):
        seen.update(prev=prev_target_key, cited={a: set(v) for a, v in cited_ckeys.items()})
        return real(store_, target_key, prev_target_key, cited_ckeys, changed_ckeys, **kwargs)

    monkeypatch.setattr(planner, "apply_carry_over", spy)
    back = factories.make_diff(store, synth.target_snapshot_id, synth.base_snapshot_id)     # 다음 리비전 — 앞 대상 스냅샷에서 이어진다
    routes.create_target(routes.TargetBody(kind="diff", ref_id=back["diff_id"], consent=True, flow="panels",
                                           agents=[dict(r) for r in rig.ROSTER]), ident=factories.ident(OWNER))
    assert seen["prev"] == key
    assert seen["cited"].get(agent, set()) == ckeys(f"panel_id <> '{review_id}'") and not seen["cited"].get(agent, set()) & review_only


# ---------------------------------------------------------------- 반출(M2.md 5절 #18 · #21)
def test_the_export_clips_card_quotes_outside_the_verdict_rows_and_keeps_the_original_length(store):
    """박스 밖으로 나가는 카드 인용은 판정 행 밖에서도 200자다 — 검토 finding 의 인용·근거 문장, 인용 역색인의 card: 인용, 단독
    재질의의 조건 글, 카드 밖 줄의 배경 카드 인용. 원래 길이는 그 옆에 남고(들여온 박스에도), 카드 절 본문은 반출 어디에도 없다
    (P-06). 박스 안의 원문은 그대로다."""
    long_cond = ("카드가 요구하는 적용 조건을 길게 옮긴 글 — " * 12)[:240]
    key, _job, _fake = _run(store, scope={"agents": [SEAL]}, verdicts={"K01": ("yes", "FAIL")}, long_quote={"K01"},
                            cond_text=long_cond, offcard=1, offcard_src="K07", offcard_quote=fre.LONG_QUOTE)
    lines = [json.loads(line) for line in export.iter_lines(store, OWNER)]
    rows = {}
    for line in lines[1:]:
        rows.setdefault(line["table"], []).append(line["row"])
    finding = json.loads(next(r for r in rows["rr_findings"] if r["source_kind"] == "card_review")["finding_json"])
    card_cites = [c for c in finding["cites"] if c["ref"].startswith("card:")]
    assert card_cites and all(len(c["quote"]) <= 200 for c in card_cites)
    assert {c.get("quote_chars") for c in card_cites} == {260}
    assert finding["warrant_chars"] == [260] and len(finding["warrant"]) < 260
    refs = [r for r in rows["rr_claim_refs"] if r["ref_type"] == "card"]
    assert refs and {(len(r["quote"]), r["quote_chars"]) for r in refs} == {(200, 260)}
    conds = [c for r in rows["rr_card_verdicts"] if r["conds_json"] for c in json.loads(r["conds_json"])]
    assert conds and {(len(c["cond"]), c["cond_chars"]) for c in conds} == {(200, 240)}
    offcard = [f for r in rows["rr_review_cells"] if r["extras_json"]
               for f in json.loads(r["extras_json"])["offcard"]["findings"]]
    assert offcard and {(len(f["q"]), f["q_chars"]) for f in offcard} == {(200, 260)}
    text = "\n".join(json.dumps(line, ensure_ascii=False) for line in lines)
    assert not [body for body in _card_bodies() if body in text]
    inside = store.query_one("SELECT quote FROM rr_claim_refs WHERE ref = ?", (f"card:{_rid('K01')}",))["quote"]
    assert inside == fre.LONG_QUOTE                                     # 박스 안 원문은 그대로


# ---------------------------------------------------------------- 폐기(plan §5.2.6)
def test_a_purge_blanks_the_quotes_in_the_claim_index_card_quotes_included(store):
    """과제 폐기는 인용 역색인(rr_claim_refs)의 인용 글도 비운다 — 카드 대조 finding 의 card: 인용이 거기 원문 그대로 남아 있었다
    (판정 행의 cq 는 비우는데 같은 글이 역색인에 남던 구멍, 패널 finding 의 인용도 같은 자리다). 행·참조·원래 길이 칸은 남는다."""
    key, _job, _fake = _run(store, scope={"agents": [SEAL]}, verdicts={"K01": ("yes", "FAIL")}, long_quote={"K01"})
    refs = [dict(r) for r in store.query("SELECT ref, ref_type, quote FROM rr_claim_refs WHERE target_key = ?"
                                         " ORDER BY claim_uid, ref_type, ref", (key,))]
    assert [r for r in refs if r["ref_type"] == "card" and r["quote"] == fre.LONG_QUOTE]
    project = store.query_one("SELECT p.id, p.code FROM rr_projects p JOIN rr_targets t ON t.project_id = p.id"
                              " WHERE t.target_key = ?", (key,))
    out = routes.purge_project(project["id"], routes.PurgeBody(code=project["code"], reason="정리"),
                               ident=factories.ident(OWNER))
    assert out["purge_report"]["layers"]["db"]["blanked"]["rr_claim_refs"] == len(refs)
    after = [dict(r) for r in store.query("SELECT ref, ref_type, quote FROM rr_claim_refs WHERE target_key = ?"
                                          " ORDER BY claim_uid, ref_type, ref", (key,))]
    assert [(r["ref"], r["ref_type"]) for r in after] == [(r["ref"], r["ref_type"]) for r in refs]
    assert {r["quote"] for r in after} == {None}


# ---------------------------------------------------------------- 큐레이션 큐(R3B-3)
LINKED_SECTION = ("정적 접착 실링 부위의 유효 접착폭은 최악 공차 누적에서도 0.8 mm 이상을 남긴다. 근거 규격은 "
                  "https://std.example.com/seal/IEC-60068-2-30 의 고온 고습 시험 조건을 따른다. "
                  + "폭이 줄면 코너 R 도 함께 보고, 접착 계면의 박리 시작점을 시험 전후로 비교한다. " * 5)


def test_a_card_quote_that_trips_the_lexicon_reaches_the_queue_clipped_and_a_purge_blanks_it(store, monkeypatch):
    """카드 글에 링크(인젝션 어휘 X08)가 든 걸림 판정 — 마감이 올린 suspect_text 큐 항목의 원문 칸(raw = finding 근거 문장)에는 카드
    인용이 처음부터 200자로 실리고 원래 길이가 raw_chars 에 있다(박스 안에서도 — 큐는 박스 밖으로 나간다, 사용자 결정 1). 반출 줄도
    같고 카드 절 본문은 큐 어디에도 없다. 과제 폐기는 그 대상의 큐 원문 칸을 비운다(항목·결정 기록은 남는다)."""
    key = rig.target(store)
    first = _unit_ids(store, key)[0]
    pack = json.loads(json.dumps(fre.load("pack_ok.json")))
    card = pack["cards"][0]
    card["sections"][0]["text"] = LINKED_SECTION
    card["text_sha"] = cardpack.text_sha(card["sections"])
    fake = FakeReviewEngine({**rig.packs(), SEAL: pack})
    fake.verdicts = {card["record_id"]: ("yes", "FAIL")}
    orig = FakeReviewEngine._verdict_row

    def row(self, alias, c, own, lines, *, variant=None):
        out = orig(self, alias, c, own, lines, variant=variant)
        if alias == "K01":
            out["cq"], out["checks"]["quote"] = LINKED_SECTION[:300], "ok"   # 카드 글 그대로 300자(엔진도 찾았다)
        return out

    monkeypatch.setattr(FakeReviewEngine, "_verdict_row", row)
    job_id = rig.job(store, key, scope={"agents": [SEAL], "unit_ids": [first]})
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed"
    (queued,) = [json.loads(r["payload_json"]) for r in store.query(
        "SELECT payload_json FROM rr_curation_queue WHERE kind = 'suspect_text'")]
    assert queued["source_kind"] == "card_review" and queued["field"] == "warrant" and queued["raw_chars"] == [300]
    assert LINKED_SECTION[:201] not in queued["raw"] and f"«{LINKED_SECTION[:200]}»" in queued["raw"]
    exported = [line["row"] for line in [json.loads(x) for x in export.iter_lines(store, OWNER)][1:]]
    (line,) = [json.loads(r["payload_json"]) for r in exported if r.get("kind") == "suspect_text"]
    assert line == queued and LINKED_SECTION[:201] not in json.dumps(exported, ensure_ascii=False)

    project = store.query_one("SELECT p.id, p.code FROM rr_projects p JOIN rr_targets t ON t.project_id = p.id"
                              " WHERE t.target_key = ?", (key,))
    out = routes.purge_project(project["id"], routes.PurgeBody(code=project["code"], reason="정리"),
                               ident=factories.ident(OWNER))
    assert out["purge_report"]["layers"]["db"]["blanked"]["rr_curation_queue"] == store.query_one(
        "SELECT COUNT(*) AS n FROM rr_curation_queue WHERE json_extract(payload_json, '$.target_key') = ?", (key,))["n"] >= 1
    (after,) = [json.loads(r["payload_json"]) for r in store.query(
        "SELECT payload_json FROM rr_curation_queue WHERE kind = 'suspect_text'")]
    assert after["raw"] is None and after["sha1"] == queued["sha1"] and after["raw_chars"] == [300]
    assert all(json.loads(r["payload_json"]).get("mechanism_free") is None for r in store.query(
        "SELECT payload_json FROM rr_curation_queue WHERE kind = 'unclassified_code'"))
