# 잡 브리프 제외(B31 — POST jobs 의 exclude_evidence)와 통합 보고서 minutes 의 '사람 개입 요약'(plan §8.2.3 · §4.7.3 · P4 (13))
"""사람은 패널 잡의 브리프에서 항목을 뺄 수만 있고 더할 수 없다(헌법 P1). `exclude_evidence` 는 잡의 params_json 에 남고, 그 잡의
패널 브리프에서 빠지며, 패널마다 rr_panels.evidence_excluded_json 에 적히고, rr_audit(action='brief.exclude') 한 행이 남는다 — 종전에는
본문 모델에 칸이 없어 조용히 버려졌다. 통합 보고서 minutes 의 '사람 개입 요약' 은 그 대상의 rr_audit 를 action 별로 센 수와 같다.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json

import pytest
from pydantic import ValidationError

import app.mcp_server as srv
from app import brief, config, planner, registry, routes, runner
from app.errors import AppError
from tests import factories
from tests.test_project_patch import _human_body
from tests.test_wiring_regressions import OWNER, RealEngine, _seed


def _ident(email: str = OWNER):
    return factories.ident(email)


def _job(target_key: str, **body) -> dict:
    return routes.create_job(target_key, routes.JobBody(**{"tier": "B", **body}), ident=_ident())


def _params(store, job_id: str) -> dict:
    return json.loads(store.query_one("SELECT params_json FROM rr_jobs WHERE id = ?", (job_id,))["params_json"])


def _audits(store, action: str) -> list[dict]:
    return [dict(r) for r in store.query("SELECT scope, subject_id, project_id, action, after_json FROM rr_audit"
                                         " WHERE action = ? ORDER BY at, id", (action,))]


@pytest.fixture
def seeded(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    return risk_store, _seed(risk_store)


def test_a_panel_job_keeps_the_exclusion_and_audits_it_once(seeded):
    store, target_key = seeded

    out = _job(target_key, exclude_evidence=["E8", "E6", "E6"])

    # 항목 차례(ITEM_ORDER)로 겹침 없이 남긴다.
    assert _params(store, out["job_id"])["exclude_evidence"] == ["E6", "E8"]
    assert out["exclude_evidence"] == ["E6", "E8"]
    rows = _audits(store, "brief.exclude")
    assert [(r["scope"], r["subject_id"], r["project_id"]) for r in rows] == [("job", out["job_id"], "p1")]
    assert json.loads(rows[0]["after_json"]) == {"target_key": target_key, "tier": "B", "exclude_evidence": ["E6", "E8"]}
    # 빼지 않은 잡은 칸도 감사도 없다(종전 그대로).
    plain = _job(target_key, tier="C", consent=True)
    assert "exclude_evidence" not in _params(store, plain["job_id"]) and "exclude_evidence" not in plain
    assert len(_audits(store, "brief.exclude")) == 1


@pytest.mark.parametrize("given, invalid", [(["E0"], ["E0"]), (["E0c"], ["E0c"]), (["E1"], ["E1"]), (["M"], ["M"]),
                                            (["E6", "reg:diff:x#c0ffee000001"], ["reg:diff:x#c0ffee000001"]),
                                            (["e6"], ["e6"])])
def test_only_excludable_item_keys_are_taken(seeded, given, invalid):
    """필수 항목(E0 · E0c · E1) · 잡 메모(M) · 항목 키가 아닌 것은 422 이고 잡도 감사도 생기지 않는다(조용히 버리지 않는다)."""
    store, target_key = seeded
    with pytest.raises(AppError) as exc:
        _job(target_key, exclude_evidence=given)
    assert (exc.value.code, exc.value.http_status) == ("exclude_evidence_invalid", 422)
    assert exc.value.detail == {"invalid": invalid, "allowed": list(brief.EXCLUDABLE_ITEMS)}
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_jobs")["n"] == 0
    assert _audits(store, "brief.exclude") == []


def test_a_review_job_does_not_take_an_exclusion():
    with pytest.raises(ValidationError, match="exclude_evidence"):
        routes.JobBody(mode="reviews", exclude_evidence=["E6"])
    routes.JobBody(mode="reviews", exclude_evidence=[])          # 빈 목록은 준 것이 아니다


def test_the_jobs_panels_run_without_the_excluded_items(seeded, tmp_path):
    store, target_key = seeded
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    job_id = runner.create_job(store, target_key, "A", owner_sub=OWNER, settings=cfg, exclude_evidence=["E6", "E8"])["job_id"]
    engine = RealEngine()

    out = runner.run_panel(store, cfg, engine, runner.claim_next_job(store, cfg))

    assert out["status"] == "done" and _params(store, job_id)["exclude_evidence"] == ["E6", "E8"]
    assert [e["key"] for e in engine.calls[0]["evidence"]] == ["E0", "E0c", "E1", "E2", "E3", "E4", "E5", "E7", "E9"]
    panel = store.query_one("SELECT evidence_excluded_json FROM rr_panels WHERE id = ?", (out["panel_id"],))
    assert json.loads(panel["evidence_excluded_json"]) == ["E6", "E8"]
    assert [e["key"] for e in runner.load_brief(store, out["panel_id"])["evidence"]] == [
        "E0", "E0c", "E1", "E2", "E3", "E4", "E5", "E7", "E9"]


def test_a_job_without_exclusions_leaves_the_panel_column_empty(seeded, tmp_path):
    store, target_key = seeded
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(store, target_key, "A", owner_sub=OWNER, settings=cfg)
    out = runner.run_panel(store, cfg, RealEngine(), runner.claim_next_job(store, cfg))
    assert store.query_one("SELECT evidence_excluded_json FROM rr_panels WHERE id = ?",
                           (out["panel_id"],))["evidence_excluded_json"] is None


def test_the_c3_follow_up_keeps_the_exclusion_of_the_job_it_follows(seeded, tmp_path):
    """닫힘 레벨 C3 의 자동 후속 Tier C 는 앞 잡의 메모 · 층과 함께 사람이 뺀 항목도 물려받는다 — 후속 패널도 그 항목 없이 돌고 패널마다
    적힌다. 물려받은 것은 params 의 exclude_evidence_from(앞 잡 id)이 말한다. 감사 행은 사람이 만든 앞 잡의 한 행 그대로다(후속은 코드가
    세운 잡이라 사람 행위가 아니다)."""
    store, target_key = seeded
    store.execute("UPDATE rr_targets SET close_level = 'C3' WHERE target_key = ?", (target_key,))
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    first = _job(target_key, exclude_evidence=["E6", "E8"], modifiers=["toulmin"], user_memo="메모")
    job = dict(store.query_one("SELECT id, target_key, tier, owner_sub, params_json FROM rr_jobs WHERE id = ?", (first["job_id"],)))
    job["params"] = json.loads(job.pop("params_json"))

    follow = runner._finish_job(store, job, cfg)["next_job"]

    params = _params(store, follow)
    assert (params["tier"], params["consent_source"]) == ("C", "close_level")
    assert (params["exclude_evidence"], params["exclude_evidence_from"]) == (["E6", "E8"], first["job_id"])
    assert (params["modifiers"], params["user_memo"]) == (["toulmin"], "메모")
    claimed = runner.claim_next_job(store, cfg)
    assert claimed["id"] == follow
    engine = RealEngine()
    out = runner.run_panel(store, cfg, engine, claimed)
    assert out["status"] == "done"
    assert [e["key"] for e in engine.calls[0]["evidence"]] == ["E0", "E0c", "E1", "E2", "E3", "E4", "E5", "E7", "E9", "M"]
    panel = store.query_one("SELECT evidence_excluded_json FROM rr_panels WHERE id = ?", (out["panel_id"],))
    assert json.loads(panel["evidence_excluded_json"]) == ["E6", "E8"]
    assert [r["subject_id"] for r in _audits(store, "brief.exclude")] == [first["job_id"]]


def test_the_mcp_entry_takes_the_exclusion_and_says_when_a_live_job_differs(seeded, monkeypatch):
    store, target_key = seeded
    factories.act_as_delegate(monkeypatch, OWNER)

    made = asyncio.run(srv.risk_start_job(target_key=target_key, tier="B", exclude_evidence=["E7"]))
    again = asyncio.run(srv.risk_start_job(target_key=target_key, tier="B", exclude_evidence=["E6"]))
    bad = asyncio.run(srv.risk_start_job(target_key=target_key, tier="B", exclude_evidence=["E0"]))
    review = asyncio.run(srv.risk_start_job(target_key=target_key, mode="reviews", exclude_evidence=["E6"]))

    assert made["created"] is True and _params(store, made["job_id"])["exclude_evidence"] == ["E7"]
    assert _audits(store, "brief.exclude")[0]["subject_id"] == made["job_id"]
    # 같은 Tier 의 살아 있는 잡을 돌려준다 — 제외가 다르면 differs 로 말하고 바꾸지 않는다. 살아 있는 잡이 무엇을 빼는지 함께 싣는다.
    assert again["created"] is False and again["job_id"] == made["job_id"] and again["differs"] == ["exclude_evidence"]
    assert again["exclude_evidence"] == ["E7"]
    # 제외를 주지 않은 호출도 살아 있는 잡을 받는다 — differs 는 없지만 그 잡이 E7 을 뺀다는 것은 보인다(보통 브리프라고 읽지 않게).
    plain = asyncio.run(srv.risk_start_job(target_key=target_key, tier="B"))
    assert plain["created"] is False and "differs" not in plain and plain["exclude_evidence"] == ["E7"]
    assert bad["error"] == "exclude_evidence_invalid"
    assert review["error"] == "E100" and "exclude_evidence" in review["message"]


# ---------------------------------------------------------------- 통합 보고서 minutes(plan §4.7.3 · P4 (13))
def _minutes(store, target_key: str) -> list[str]:
    return "\n".join(registry.build_report(store, target_key)["blocks"]["minutes"]).split("\n")


def _section(lines: list[str], head: str) -> list[str]:
    start = lines.index(head) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("[")), len(lines))
    return lines[start:end]


def test_the_human_intervention_summary_equals_the_targets_audit(seeded):
    """P4 (13) — 사람 개입 요약이 그 대상 rr_audit 의 action 별 수와 같고, 사람이 넘긴 좌석 칸에 decided_by 가 붙는다."""
    store, target_key = seeded
    assert _section(_minutes(store, target_key), "[사람 개입 요약]") == ["(없음)"]

    agent = store.query_one("SELECT agent_key, domain FROM rr_coverage WHERE target_key = ? ORDER BY agent_key", (target_key,))
    routes.put_coverage(target_key, agent["agent_key"], routes.CoverageBody(status="skipped", reason="이번 판에는 불참"),
                        ident=_ident())
    _job(target_key, exclude_evidence=["E6"])
    routes.create_human_finding(target_key, _human_body(), ident=_ident())
    routes._audit(store, OWNER, scope="snapshot", subject_id="s1", action="gate.ack")      # 이 diff 의 뒤 스냅샷
    routes._audit(store, OWNER, scope="target", subject_id="diff:other", action="target.flow")   # 남의 대상 — 세지 않는다

    lines = _minutes(store, target_key)

    by_route = {}
    for entry in routes.get_target_audit(target_key, ident=_ident())["entries"]:
        by_route[entry["action"]] = by_route.get(entry["action"], 0) + 1
    assert by_route == {"brief.exclude": 1, "coverage.skip": 1, "finding.create": 1, "gate.ack": 1}
    assert _section(lines, "[사람 개입 요약]") == [f"{action}={n}" for action, n in sorted(by_route.items())]
    grid = next(ln for ln in _section(lines, "[커버리지 도메인×상태]") if ln.startswith(f"{agent['domain']} · "))
    assert f"skipped=1(decided_by: {OWNER})" in grid
    assert planner.coverage_summary(store, target_key)["by_status"].get("skipped") == 1
