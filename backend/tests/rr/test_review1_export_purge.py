# 반대 검토 1차(review1) 반출·폐기·들여오기 몫 — 쟁점 패널이 옮긴 카드 글의 반출 상한(M6), 폐기가 등록부·패널 결과 원문을 비우는지(M7 · result_gz), 들여오기가 사람의 취소·결정을 잃지 않는지(L4)
"""원장은 생산자 경로다 — 대상은 라우트(rig.target), 검토는 가짜 검토 엔진의 루프, 쟁점 → 종합은 검토 잡 끝의 사슬이 세운 잡을 러너(가짜
쟁점 패널 엔진 — 좌석이 카드 절을 옮겨 적는 대본 card_quote)와 종합 워커(가짜 요약 엔진)가 돈다. 반출은 export.iter_lines,
들여오기는 export.import_jsonl, 폐기는 routes.purge_project, 확인·취소는 closure, 사람의 쟁점 결정은 routes.put_issue 다.
"""
from __future__ import annotations

import gzip
import json

import pytest

from app import config, export, routes, runner, synth
from app.risk_store import RiskStore
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.fake_summary_engine import FakeSummaryEngine
from tests.synth.issue_panel_engine import IssuePanelEngine

OWNER = rig.OWNER
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}
SECTION = ("좌석이 카드 절을 통째로 옮겨 적은 글이다 — 박스 밖으로는 판정당 200자만 나간다. " * 8)[:390]


@pytest.fixture
def chained(risk_store, monkeypatch, tmp_path):
    """검토 → 쟁점 패널(카드 절 390자를 옮겨 적은 결정문) → 종합 → 판까지 돈 원장 — 대상 열쇠."""
    rig.configure(monkeypatch, risk_store, tmp_path, risk_issue_panel_cap=2, risk_issue_panel_hard_cap=2)
    key = rig.target(risk_store)
    job_id = rig.job(risk_store, key)
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {str(CARDS["K01"]["record_id"]): ("yes", "FAIL")}
    fake.mechs = {str(CARDS["K01"]["record_id"]): ("interface.clearance", "")}
    rig.Rig(risk_store, fake).finish(job_id)
    card = {"ref": f"card:{CARDS['K01']['record_id']}#{CARDS['K01']['sections'][0]['sid']}", "quote": SECTION}
    engine = IssuePanelEngine(risk_store, {"*": {"severity": "치명", "judgement": "FAIL", "card_quote": card}})
    while (job := runner.claim_next_job(risk_store, config.settings, engine=engine)) is not None:
        runner.run_panel(risk_store, config.settings, engine, job)
    # 요약 서기가 행 글(카드 절)을 서술에 옮겨 적었다 — 보고서 판 쪽의 «» 서술에 실린다.
    worker = synth.SynthWorker(risk_store, config.settings, FakeSummaryEngine({"*": {"para": f"이 범위의 근거 «{SECTION}»"}}))
    for _ in range(300):
        if worker.tick()["step"] == "idle":
            break
    assert synth.report_source(risk_store, key)["trigger"] == "synth_done"
    return key


def _exported(store: RiskStore, owner: str = OWNER) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for line in list(export.iter_lines(store, owner, 0))[1:]:
        item = json.loads(line)
        out.setdefault(item["table"], []).append(item["row"])
    return out


def _texts(value) -> list[str]:
    """반출 값 안의 글 전부(JSON 글은 풀고, gzip·base64 블롭은 풀어서)."""
    if isinstance(value, dict):
        if set(value) == {"__b64__"}:
            import base64

            try:
                return _texts(gzip.decompress(base64.b64decode(value["__b64__"])).decode("utf-8"))
            except OSError:
                return []
        return [t for v in value.values() for t in _texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in _texts(v)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return [value]
        return [value] if isinstance(parsed, str) else _texts(parsed) + [value]
    return []


def test_a_purge_blanks_the_registry_and_the_panels_raw_engine_result(risk_store, chained):
    """M7 · 새로 본 것 — 폐기가 등록부 merged_json(카드 인용 · 쟁점 패널 주장 · 근거 문장)과 패널의 엔진 결과 원문(result_gz — 결정문 ·
    발언이 든다)을 비운다. 반출에도 그 글이 남지 않는다. 행과 해시·수는 남는다."""
    key = chained
    project_id = risk_store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]
    code = risk_store.query_one("SELECT code FROM rr_projects WHERE id = ?", (project_id,))["code"]
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_panels WHERE target_key = ? AND result_gz IS NOT NULL",
                                (key,))["n"] > 0
    with factories.routes_store(risk_store):
        routes.purge_project(project_id, routes.PurgeBody(code=code, reason="정리"), ident=factories.ident(OWNER))
    registry_rows = risk_store.query("SELECT merged_json, severity FROM rr_registry WHERE target_key = ?", (key,))
    assert registry_rows and {r["merged_json"] for r in registry_rows} == {"{}"} and all(r["severity"] for r in registry_rows)
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_panels WHERE target_key = ? AND result_gz IS NOT NULL",
                                (key,))["n"] == 0
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_panels WHERE target_key = ? AND result_hash IS NOT NULL",
                                (key,))["n"] > 0

