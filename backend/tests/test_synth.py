# 영역 요약과 종합 보고서(재설계 M3 S3-9) — 요약 서술만 LLM 이고 표·수는 코드이며, LLM 이 죽어도 보고서 판이 서는지 본다
"""입력은 생산자다 — 원장은 가짜 검토 엔진을 꽂은 M2 검토 루프(tests/synth/review_rig.py)와 S3-6 선정·S3-7 쟁점 패널(가짜 쟁점
패널 엔진), 요약은 종합 잡(`synth.create_synth_job`)을 `SynthWorker.tick` 으로 끝까지 돌린 것이다(가짜 요약 엔진 —
tests/synth/fake_summary_engine.py). 엔진의 정확한 출력 모양 단언(C14)은 tests/test_summary_contract.py 에 있다.
"""
from __future__ import annotations

import json
import re

import pytest

from app import closure, common, config, issues, registry, runner, synth, units
from app.runner import EngineRejected
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.fake_summary_engine import FakeSummaryEngine
from tests.synth.issue_panel_engine import IssuePanelEngine

OWNER = rig.OWNER
SEAL = rig.SEAL
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _rid(alias: str) -> str:
    return str(CARDS[alias]["record_id"])


def _ledger(store, *, issues_too: bool = False, monkeypatch=None, tmp_path=None) -> str:
    """격자 전부를 검토 루프로(K01 FAIL) — 쟁점까지면 쟁점 패널도 돈다."""
    key = rig.target(store)
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {_rid("K01"): ("yes", "FAIL"), _rid("K02"): ("yes", "WARNING")}
    fake.mechs = {_rid("K01"): ("interface.clearance", ""), _rid("K02"): ("mechanical.drop_stress", "")}
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)
    registry.merge(store, key)
    if issues_too:
        rig.configure(monkeypatch, store, tmp_path, risk_issue_panel_cap=2, risk_issue_panel_hard_cap=2)
        issues.select_issues(store, key, selected_round=1, cells_hash=closure.closing_hash(store, key))
        issues.create_issues_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
        engine = IssuePanelEngine(store, {"*": {"severity": "치명", "judgement": "FAIL"}})
        while (job := runner.claim_next_job(store, config.settings, engine=engine)) is not None:
            if runner.run_panel(store, config.settings, engine, job)["status"] == "no_panel":
                break
    return key


def _drive(store, engine, key: str, *, limit: int = 200) -> list[dict]:
    """종합 잡 하나를 끝까지 — tick 한 번이 요약 호출 하나(또는 계획·조립 한 걸음)."""
    synth.create_synth_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    worker = synth.SynthWorker(store, config.settings, engine)
    steps = []
    for _ in range(limit):
        step = worker.tick()
        steps.append(step)
        if step["step"] in ("completed", "idle", "hold", "draining"):
            break
    return steps


def _summaries(store, key: str) -> dict:
    return {(r["scope_kind"], r["scope_key"]): r for r in synth.latest_summaries(store, key)}


def _page_text(report: dict, kind: str | None = None) -> str:
    return "\n".join(t for p in report["pages"] if kind is None or p["kind"] == kind
                     for b in synth.BLOCKS for t in p["blocks"][b])


# ---------------------------------------------------------------- 한 바퀴
def test_every_roster_domain_gets_a_summary_and_the_report_head_equals_the_closure_counts(store):
    """로스터 영역 15개 전부에 요약 행이 서고, 행 0 인 영역은 LLM 없이 code_only(no_rows) 다. 과제 종합 뒤 보고서 판(synth_done — 앞
    판은 검토 잡 끝의 사슬이 세운 코드 조립 판이다)이 서고, 머리의 수(counts_json)가 같은 시점의 closure.cell_counts 와 같다. 서술이
    다 붙어 narrative_state full 이다."""
    key = _ledger(store)
    engine = FakeSummaryEngine()
    steps = _drive(store, engine, key)
    assert steps[-1]["step"] == "completed", steps[-3:]
    rows = _summaries(store, key)
    domains = list(config.settings.risk_roster_domains)
    assert {k for k in rows if k[0] == "domain"} == {("domain", d) for d in domains} and len(domains) == 15
    no_rows = sorted(k[1] for k, r in rows.items() if r["state"] == "code_only" and r["state_reason"] == "no_rows")
    called = sorted(b["summary"]["scope"]["key"] for b in engine.requests)
    assert called == sorted([d for d in domains if d not in no_rows] + ["-"]) and no_rows
    assert all(r["state"] == "done" for k, r in rows.items() if k[1] not in no_rows)
    report = synth.report_source(store, key)
    chained = store.query_one("SELECT COUNT(*) AS n FROM rr_reports WHERE target_key = ? AND trigger <> 'synth_done'", (key,))["n"]
    assert chained >= 1
    assert (report["version_no"], report["trigger"], report["narrative_state"]) == (chained + 1, "synth_done", "full")
    fresh = {k: v for k, v in closure.cell_counts(store, key).items() if not k.startswith("_")}
    assert report["counts"] == json.loads(json.dumps(fresh))
    # 근거 등급이 전부 경험칙인 원장이라 지금처럼 [가설 단계] 가 앞에 붙는다.
    assert report["title"] == f"[가설 단계] 리스크 심사 보고서 v{chained + 1} [{report['level_label']}] — {key}"
    assert [p["kind"] for p in report["pages"]] == ["summary"] + ["domain"] * 15 + ["mechanisms", "appendix"]
    appendix = [t for t in report["pages"][-1]["blocks"]["minutes"] if t.startswith("- ")]
    assert len(appendix) == len(rig.ROSTER)
    head = _page_text(report, "summary")
    assert "서술은 LLM(요약 서기), 근거는 아래 표다" in head and "결손 사냥 미실행" in head
    assert "검토 품질(이 판의 고정본)" in head
    # 호출 원장 — 요약 호출 한 건마다 한 행(kind summary · agent synth).
    calls = store.query("SELECT kind, agent_key, state FROM rr_review_calls WHERE target_key = ? AND kind = 'summary'", (key,))
    assert len(calls) == len(engine.requests) and {(c["agent_key"], c["state"]) for c in calls} == {("synth", "ok")}


def test_the_request_is_the_engines_summary_body_and_rows_are_whole_quoted_and_within_the_line_limit(store):
    """요청은 엔진 summary 본문 그대로(expert null · 카드·단위 없음 · 기대 판) — 행 한 줄 400자 안, 그 영역이 제기에 참여한 행
    전부, 꼭 다룰 행은 주의 A, 종합 호출의 영역 요약 글(앞 단계 LLM)은 «» 안이다. 카드 절 원문은 어느 요약 본문에도 없다."""
    key = _ledger(store)
    engine = FakeSummaryEngine()
    _drive(store, engine, key)
    mech = next(b for b in engine.requests if b["summary"]["scope"]["key"] == "mech")
    assert mech["expert"] is None and mech["expect"] == {"prompt_rev": "cr-summary-2", "limits_rev_kind": "fake-sum-1"}
    want = {f"reg:{r['cluster_key']}" for r in registry.registry_rows(store, key) if "mech" in r["merged"]["domains"]}
    assert {r["ref"] for r in mech["summary"]["rows"]} == want
    attention = {f"reg:{r['cluster_key']}": r["attention"] for r in registry.registry_rows(store, key)}
    assert mech["summary"]["must_cover"] and all(attention[c] == "A" for c in mech["summary"]["must_cover"])
    assert all(len(r["text"]) <= 400 for b in engine.requests for r in b["summary"]["rows"])
    target = next(b for b in engine.requests if b["summary"]["scope"]["kind"] == "target")
    domains = next(b for b in target["summary"]["blocks"] if b["name"] == "domains")
    assert all(re.fullmatch(r"\[[a-z]+\] (머리|걸림) «[^«»]*»", line) for line in domains["text"].split("\n"))
    sections = [s["text"] for c in CARDS.values() for s in c["sections"]]
    blob = json.dumps(engine.requests, ensure_ascii=False)
    assert not any(text.split("\n")[0][:20] in blob for text in sections)


# ---------------------------------------------------------------- 대조 · 실패
def test_a_missing_must_cover_is_reasked_once_with_the_notes_and_then_closes_code_only(store):
    """엔진의 missing 이 남으면 지적을 실어 한 번 다시 묻고(checks 블록), 그래도면 code_only(checks_failed) — 보고서 그 쪽에
    '서술 없음 — 까닭' 이 크게 선다. 한 번 다시 물어 채워지면 done 이다."""
    key = _ledger(store)
    engine = FakeSummaryEngine({"mech": "missing", "xd": "missing_once"})
    _drive(store, engine, key)
    rows = _summaries(store, key)
    assert (rows[("domain", "mech")]["state"], rows[("domain", "mech")]["state_reason"]) == ("code_only", "checks_failed")
    assert rows[("domain", "xd")]["state"] == "done"
    asked = [b for b in engine.requests if b["summary"]["scope"]["key"] == "mech"]
    assert len(asked) == 2 and any(b["name"] == "checks" for b in asked[1]["summary"]["blocks"])
    report = synth.report_source(store, key)
    assert report["narrative_state"] == "partial"
    mech_page = next(p for p in report["pages"] if p["title"] == "영역 mech")
    assert any("서술 없음" in t and "checks_failed" in t for t in mech_page["blocks"]["results"])
    assert any("mech 요약은 서술 없이 코드 조립본이다" in t for t in report["pages"][0]["blocks"]["background"])


@pytest.mark.parametrize("plan", ["nums", "outside"])
def test_unsourced_numbers_and_refs_outside_the_input_are_caught_by_the_app(store, plan):
    """엔진이 수의 출처를 못 댄 줄(checks.nums_unsourced)과 입력 밖 참조는 앱의 대조가 잡는다 — 두 번 그러면 code_only(checks_failed)."""
    key = _ledger(store)
    _drive(store, FakeSummaryEngine({"mech": plan}), key)
    row = _summaries(store, key)[("domain", "mech")]
    checks = json.loads(row["checks_json"])
    assert (row["state"], row["state_reason"]) == ("code_only", "checks_failed")
    assert (checks["nums_unsourced"] if plan == "nums" else checks["refs_outside"])


def test_over_budget_and_an_unrunnable_box_close_code_only_without_breaking_the_report(store):
    """over_budget(그 요약만 — LLM 0회, 다시 쪼개지 않는다)은 code_only(ctx_too_small) 이고, runnable.summary=false 면 아무것도
    부르지 않고 전부 code_only(ctx_too_small) 다. 어느 쪽이든 보고서 판은 선다(서술 없음 — 까닭)."""
    key = _ledger(store)
    _drive(store, FakeSummaryEngine({"mech": "over_budget"}), key)
    assert _summaries(store, key)[("domain", "mech")]["state_reason"] == "ctx_too_small"
    other = _ledger(store)
    engine = FakeSummaryEngine()
    engine.runnable = False
    steps = _drive(store, engine, other)
    assert steps[-1]["step"] == "completed" and engine.requests == []
    rows = _summaries(store, other)
    assert {r["state_reason"] for r in rows.values() if r["state"] == "code_only"} <= {"no_rows", "ctx_too_small"}
    report = synth.report_source(store, other)
    assert report["narrative_state"] == "none" and "이 박스의 창이 요약 입력을 담지 못한다" in _page_text(report, "summary")


def test_infra_failures_exhaust_to_code_only_and_content_failures_after_two(store, monkeypatch, tmp_path):
    """인프라 탓은 HWAXRISK_SUMMARY_INFRA_MAX(6)번 뒤 code_only(infra_exhausted), 내용 탓은 HWAXRISK_SUMMARY_MAX_CHARGED(2)번 뒤
    code_only(content_fail) — 백오프는 시계로 민다. 보고서 판은 선다."""
    clock = rig.Clock()
    key = _ledger(store)
    engine = FakeSummaryEngine({"mech": EngineRejected("llm_unreachable", "LLM 불통(가짜)", infra=True, retryable=True),
                                "xd": EngineRejected("no_rows", "행 없음(가짜)")})
    synth.create_synth_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    worker = synth.SynthWorker(store, config.settings, engine, clock=clock)
    for _ in range(400):
        step = worker.tick()
        if step["step"] == "completed":
            break
        clock.advance(1000)
    rows = _summaries(store, key)
    mech, xd = rows[("domain", "mech")], rows[("domain", "xd")]
    assert (mech["state_reason"], mech["infra_streak"]) == ("infra_exhausted", config.settings.risk_summary_infra_max)
    assert (xd["state_reason"], xd["charged"]) == ("content_fail", config.settings.risk_summary_max_charged)
    assert synth.report_source(store, key) is not None


def test_a_cover_too_large_holds_the_synth_job_as_a_contract_fault(store):
    """cover_too_large 는 앱이 cover_max 를 어긴 것이라 종합 잡을 contract 로 보류한다(#49) — 그 요약은 대기로 남는다."""
    key = _ledger(store)
    engine = FakeSummaryEngine({"*": EngineRejected("cover_too_large", "꼭 다룰 행이 상한을 넘는다(가짜)")})
    steps = _drive(store, engine, key)
    assert steps[-1] == {**steps[-1], "step": "hold", "hold": "contract"}
    job = store.query_one("SELECT state, hold_code FROM rr_jobs WHERE mode = 'synth'")
    assert (job["state"], job["hold_code"]) == ("paused", "contract")


def test_summaries_stop_only_while_the_agent_server_drains_everything(store):
    """#50 — 비우기 범위 all 이면 새 요약 호출을 내지 않고 잡 행에 까닭을 적는다. 범위 panels 면 이어 돈다."""
    key = _ledger(store)
    engine = FakeSummaryEngine()
    engine.drain = {"on": True, "scope": "all"}
    steps = _drive(store, engine, key)
    assert steps == [{"job_id": steps[0]["job_id"], "step": "draining"}] and engine.requests == []
    assert store.query_one("SELECT error FROM rr_jobs WHERE mode = 'synth'")["error"].startswith("draining")
    engine.drain = {"on": True, "scope": "panels"}
    worker = synth.SynthWorker(store, config.settings, engine)
    for _ in range(200):
        if worker.tick()["step"] == "completed":
            break
    assert engine.requests


# ---------------------------------------------------------------- 판
def test_the_same_content_makes_no_new_version_and_a_change_does(store):
    """내용이 직전 판과 같으면 새 판을 만들지 않는다 — 원장이 바뀌면(사람 확인) 다음 판이 선다."""
    key = _ledger(store)
    first = synth.assemble_report(store, key, trigger="reviews_closed")
    again = synth.assemble_report(store, key, trigger="manual")
    assert (first["created"], again["created"], again["version_no"]) == (True, False, first["version_no"])
    result = closure.refresh(store, key)
    blocking = next(q for q in result["qualifiers"] if q["blocking"])
    closure.ack_residual(store, key, blocking["item"], reason="그 잔여는 넘긴다", by=OWNER, basis_hash=blocking["basis_hash"])
    later = synth.assemble_report(store, key, trigger="ack")
    assert later["created"] and later["version_no"] == first["version_no"] + 1
    assert synth.report_source(store, key, version=first["version_no"])["trigger"] == "reviews_closed"


def test_the_report_carries_issue_results_with_their_original_distribution_and_untried_rows(store, monkeypatch, tmp_path):
    """쟁점 결과 표의 한 줄에 원래 분포와 패널 결과가 같이 있고('제기 n명(judgement=FAIL …) · 반대 n명 → 쟁점 패널 상향 …'),
    상한 밖 쟁점은 미토의 행으로 남는다(FAIL 로 본 전문가 수와 함께). 카드 대조 FAIL 수(hold 로 주의)를 판정 행에서 직접 센다."""
    key = _ledger(store, issues_too=True, monkeypatch=monkeypatch, tmp_path=tmp_path)
    out = synth.assemble_report(store, key, trigger="issues_closed")
    report = synth.report_source(store, key, version=out["version_no"])
    text = _page_text(report, "summary")
    assert "→ 쟁점 패널 상향 severity=치명 · judgement=FAIL" in text and "judgement=FAIL" in text
    untried = [i for i in issues.issue_rows(store, key) if i["state"] in closure.ISSUE_UNTRIED_STATES]
    assert untried and f"## 미토의 쟁점 {len(untried)}건" in text and "명이 FAIL 로 봤으나 미토의" in text
    fails = store.query_one("SELECT COUNT(*) AS n FROM rr_card_verdicts WHERE target_key = ? AND is_effective = 1"
                            " AND judgement = 'FAIL'", (key,))["n"]
    assert f"카드 대조가 FAIL 로 본 판정 {fails}건" in text and fails


def test_a_clipped_engine_input_and_a_capped_cover_are_loud_in_the_report(store):
    """엔진이 몫에서 끊은 입력(meta.clipped)과 꼭 다룰 행이 cover_max 에 걸려 남은 A 행은 보고서에 크게 선다(조용히 빼지 않는다)."""
    key = _ledger(store)
    engine = FakeSummaryEngine({"mech": "clipped"}, cover_max=1)
    _drive(store, engine, key)
    report = synth.report_source(store, key)
    head = _page_text(report, "summary")
    assert "mech 요약 입력 일부가 엔진 몫에서 끊겼다" in head
    mech_page = next(p for p in report["pages"] if p["title"] == "영역 mech")
    a_rows = [r for r in registry.registry_rows(store, key) if "mech" in r["merged"]["domains"] and r["attention"] == "A"]
    if len(a_rows) > 1:
        assert any("서술은 주의 A 상위 1건" in t for t in mech_page["blocks"]["results"])
    assert len([b for b in engine.requests if b["summary"]["scope"]["key"] == "mech"][0]["summary"]["must_cover"]) <= 1


def test_the_wire_pages_rejoin_into_the_full_markdown(store):
    """와이어 쪽(render_pages)은 쪽마다 page_chars 안이고(조각 하나가 더 길면 그 조각만) 차례로 이으면 part 전체 마크다운이다."""
    key = _ledger(store)
    synth.assemble_report(store, key, trigger="manual")
    report = synth.report_source(store, key)
    for part in synth.PARTS:
        pages = synth.render_pages(report, 2_000, part=part)
        joined = "\n".join(t for p in pages for b in synth.BLOCKS for t in p["blocks"][b])
        assert joined == synth.render_report_md(report, part=part)
        assert all(sum(len(t) + 1 for b in synth.BLOCKS for t in p["blocks"][b]) - 1 <= 2_000
                   or sum(len(p["blocks"][b]) for b in synth.BLOCKS) == 1 for p in pages)
    with pytest.raises(Exception):
        synth.render_report_md(report, part="nope")


def test_rows_of_a_domain_are_never_dropped_and_a_long_claim_is_cut_with_its_length(store):
    """D-21 — 영역 행을 버리지 않는다(등록부의 그 영역 행 수 == 요청 행 수). 행 한 줄이 400자를 넘으면 주장 글만 줄이고 원래 길이를 밝힌다."""
    key = _ledger(store)
    rows = registry.registry_rows(store, key)
    counts = closure.cell_counts(store, key)
    built = synth.summary_input(store, key, "domain", "mech", limits=None, counts=counts)
    assert built["n_rows"] == sum(1 for r in rows if "mech" in r["merged"]["domains"])
    longer = {**rows[0], "merged": {**rows[0]["merged"], "claim": "가" * 900}}
    line = synth.row_line(store, longer, line_max=400)
    assert len(line) <= 400 and "(900자 중" in line
    assert units.load_units(store, key)


def test_the_report_freezes_the_quality_block_of_its_version_and_the_residual_reads_the_same_numbers(store):
    """C10 — 보고서 판은 그 판의 품질 블록을 고정본으로 싣는다(뒤에 품질이 바뀌어도 옛 판의 글은 그대로 — 판이 pages_gz 에 얼린다).
    완결의 quality 잔여는 같은 품질 수치(out_of_bounds)를 읽는다(진행판의 값 — 다시 세지 않는다)."""
    from app import review_quality

    key = _ledger(store)
    out = synth.assemble_report(store, key, trigger="manual")
    report = synth.report_source(store, key, version=out["version_no"])
    block = review_quality.block(store, key)
    minutes = report["pages"][0]["blocks"]["minutes"]
    start = minutes.index("## 검토 품질(이 판의 고정본)") + 1
    assert minutes[start:start + len(block["text"].split("\n"))] == block["text"].split("\n")
    residual = next((q for q in closure.close_level_cells(store, key, persist=False)["qualifiers"]
                     if q["item"] == "quality"), None)
    bounds = list(block["json"]["out_of_bounds"])
    assert (residual["out_of_bounds"] if residual else []) == bounds


# ---------------------------------------------------------------- 반대 검토 1차(review1) — 종합 잡의 걸림
class _Killed(BaseException):
    """앱이 요약 호출 도중에 내려간 것 — 워커의 except Exception 을 지나 틱 밖으로 나간다(재기동 흉내)."""


def _tick_until(worker, *, limit: int = 120, stop=("completed", "idle")) -> list[dict]:
    steps = []
    for _ in range(limit):
        steps.append(worker.tick())
        if steps[-1]["step"] in stop:
            break
    return steps


def test_a_synth_job_whose_summaries_are_all_reused_still_finishes(store):
    """H1 — 같은 입력의 종합 잡을 다시 세우면(보고서 다시 내기 · 같은 실패의 재시도) 요약은 전부 다시 쓰이는데, 그 행이 이 잡의
    것으로 표지되지 않으면 잡은 영영 '계획' 만 되풀이했다. 다시 쓴 요약도 이 잡의 것이고 잡은 끝난다(호출 0회)."""
    key = _ledger(store)
    engine = FakeSummaryEngine()
    assert _drive(store, engine, key)[-1]["step"] == "completed"
    calls = len(engine.requests)
    again = synth.create_synth_job(store, key, owner_sub=OWNER, requester_sub=OWNER)["job_id"]
    steps = _tick_until(synth.SynthWorker(store, config.settings, engine), limit=60)
    assert steps[-1] == {**steps[-1], "job_id": again, "step": "completed"}, [s["step"] for s in steps][-5:]
    assert len(engine.requests) == calls
    tagged = store.query_one("SELECT COUNT(*) AS n FROM rr_summaries WHERE target_key = ? AND run_id = ?", (key, again))["n"]
    assert tagged == len(config.settings.risk_roster_domains) + 1
    # 내용이 같은 종합 판은 새로 서지 않는다 — 자기 판 표기를 세려고 먼저 세운 판 행도 남기지 않는다(review1 M4).
    first = synth.report_source(store, key)
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_reports WHERE target_key = ? AND pages_n = 0", (key,))["n"] == 0
    assert first["trigger"] == "synth_done" and first["pages"]


def test_a_summary_cut_by_a_restart_goes_back_to_pending_and_one_stuck_target_does_not_starve_another(store, monkeypatch):
    """H2 — 요약 호출 도중 앱이 내려가면 그 행이 running 으로 남아 새 워커가 '기다림' 만 되풀이했고, 워커가 늘 가장 오래된 잡을
    집어 다른 대상의 종합 잡도 줄에 묶였다. 재기동 복구가 running 요약을 대기로(차감 없이) 돌리고, 워커는 대상마다 번갈아 집는다."""
    first, second = _ledger(store), _ledger(store)
    synth.create_synth_job(store, first, owner_sub=OWNER, requester_sub=OWNER)
    killer = FakeSummaryEngine({"mech": _Killed()})
    worker = synth.SynthWorker(store, config.settings, killer)
    with pytest.raises(_Killed):
        _tick_until(worker, limit=60)
    stuck = store.query_one("SELECT summary_id, attempts FROM rr_summaries WHERE target_key = ? AND state = 'running'",
                            (first,))
    assert stuck is not None
    later = common.now_epoch() + 60                                     # 묶인 잡이 확실히 더 오래됐다(같은 초면 id 가 가른다)
    with monkeypatch.context() as patched:
        patched.setattr(common, "now_epoch", lambda: later)
        synth.create_synth_job(store, second, owner_sub=OWNER, requester_sub=OWNER)
    engine = FakeSummaryEngine()
    steps = _tick_until(synth.SynthWorker(store, config.settings, engine), limit=120, stop=("idle",))
    done = {s["job_id"] for s in steps if s["step"] == "completed"}
    second_job = store.query_one("SELECT id FROM rr_jobs WHERE target_key = ? AND mode = 'synth'", (second,))["id"]
    assert second_job in done                                            # 묶인 대상이 있어도 다른 대상은 끝난다
    assert synth.recover_running(store) == {"summaries": 1}
    row = store.query_one("SELECT state, attempts, charged FROM rr_summaries WHERE summary_id = ?", (stuck["summary_id"],))
    assert (row["state"], row["charged"]) == ("pending", 0)
    steps = _tick_until(synth.SynthWorker(store, config.settings, engine), limit=60)
    assert steps[-1]["step"] == "completed"


def test_the_runner_recovers_cut_summaries_when_it_takes_the_lock(store, monkeypatch):
    """H2 — 러너가 잠금을 쥔 뒤의 재기동 복구(패널·검토 복구와 같은 자리)가 끊긴 요약도 되돌린다."""
    seen: list = []
    monkeypatch.setattr(synth, "recover_running", lambda s: seen.append(s) or {"summaries": 0})
    monkeypatch.setattr(runner, "_LOOPS", ())
    loop = runner.RiskRunner(store, config.settings)
    loop._begin()
    loop.stop()
    assert seen == [store]


def test_every_summary_write_stamps_updated_at(store):
    """L5 — rr_summaries.updated_at 을 적는다(계획 · 호출 시작 · 닫기)."""
    key = _ledger(store)
    _drive(store, FakeSummaryEngine(), key)
    rows = store.query("SELECT updated_at, created_at FROM rr_summaries WHERE target_key = ?", (key,))
    assert rows and all(r["updated_at"] is not None and r["updated_at"] >= r["created_at"] for r in rows)


def test_the_synth_done_report_states_its_own_level_not_stale_before_synthesis(store):
    """M4(종합 몫) — 종합 판은 자기 판(synth_done)이 서기 전의 신선도로 표기를 셌다 → 모든 종합 판의 제목·머리가 '후속 낡음(종합
    전)' 이었다. 판의 표기 = 판을 세운 뒤의 완결 표기다. 원장은 사슬이 끝까지 돈 것이다(쟁점 패널 → 종합 잡)."""
    key = _ledger(store)
    engine = IssuePanelEngine(store, {"*": {"severity": "치명", "judgement": "FAIL"}})
    while (job := runner.claim_next_job(store, config.settings, engine=engine)) is not None:
        runner.run_panel(store, config.settings, engine, job)
    assert closure.refresh(store, key)["c2"] is True
    assert _tick_until(synth.SynthWorker(store, config.settings, FakeSummaryEngine()), limit=120)[-1]["step"] == "completed"
    report = synth.report_source(store, key)
    assert report["trigger"] == "synth_done"
    after = closure.refresh(store, key)
    assert "후속 낡음(종합 전)" not in report["level_label"] and "후속 낡음(종합 전)" not in report["title"]
    assert report["level_label"] == after["level_label"] and f"[{after['level_label']}]" in report["title"]
    assert after["level_label"] in _page_text(report, "summary")


@pytest.mark.parametrize("after", ["answer", "job_fault"])
def test_an_inflight_summary_after_a_purge_writes_nothing_back(store, after):
    """L6 — 폐기(purge) 뒤에 끝난 요약 호출의 결과는 쓰지 않는다(같은 트랜잭션에서 과제의 폐기 상태를 본다). 판도 세우지 않고
    (409 project_purged), 폐기가 취소한 잡을 그 호출의 실패 갈래가 되살리지 않는다."""
    from app import routes
    from app.errors import AppError
    from tests import factories

    key = _ledger(store)
    project_id = store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]
    code = store.query_one("SELECT code FROM rr_projects WHERE id = ?", (project_id,))["code"]
    synth.create_synth_job(store, key, owner_sub=OWNER, requester_sub=OWNER)
    before = store.query_one("SELECT COUNT(*) AS n FROM rr_reports WHERE target_key = ?", (key,))["n"]

    class PurgingEngine(FakeSummaryEngine):
        def run(self, body, **kwargs):
            if not getattr(self, "purged", False):
                self.purged = True
                with factories.routes_store(store):
                    routes.purge_project(project_id, routes.PurgeBody(code=code, reason="폐기 시험"),
                                         ident=factories.ident(OWNER))
                if after == "job_fault":
                    raise EngineRejected("llm_misconfigured", "LLM 설정이 틀렸다(가짜)")
            return super().run(body, **kwargs)

    worker = synth.SynthWorker(store, config.settings, PurgingEngine())
    _tick_until(worker, limit=60)
    leaked = store.query("SELECT summary_id FROM rr_summaries WHERE target_key = ? AND output_json IS NOT NULL", (key,))
    assert [r["summary_id"] for r in leaked] == []
    calls = store.query("SELECT call_id FROM rr_review_calls WHERE target_key = ? AND kind = 'summary' AND result_gz IS NOT NULL",
                        (key,))
    assert [r["call_id"] for r in calls] == []
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_reports WHERE target_key = ?", (key,))["n"] == before
    assert store.query_one("SELECT state FROM rr_jobs WHERE target_key = ? AND mode = 'synth'", (key,))["state"] == "cancelled"
    with pytest.raises(AppError) as refused:
        synth.assemble_report(store, key, trigger="manual")
    assert (refused.value.code, refused.value.http_status) == ("project_purged", 409)
