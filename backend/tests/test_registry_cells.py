# 등록부 병합의 cells 갈래(재설계 M3 S3-4) — 카드 대조 finding 을 cells 대상에서만 읽고, 지지를 전문가·영역·단위·검증으로 세며, hold 가 가린 주장값과 분포를 같은 줄에 남긴다
"""입력은 생산자다 — 대상·단위는 합성 쌍 → 라우트, 카드 판정·finding 은 가짜 엔진을 꽂은 M2 검토 루프(tests/synth/review_rig.py),
패널 원장은 러너가 가짜 패널 엔진(legacy_build.LegacyEngine)으로 돈 것이다. 패널 대상의 바이트 동일은
tests/rr/test_panel_registry_bytes.py 가 얼린 기준선으로 본다.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import re
from pathlib import Path

import httpx
import pytest

from app import config, registry, routes, runner, units
from tests import factories
from tests.rr import legacy_build as legacy
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine

OWNER = rig.OWNER
SEAL = rig.SEAL
APP = Path(__file__).resolve().parents[1] / "app"
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}
MECH = ("interface.clearance", "")


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _rid(alias: str) -> str:
    return str(CARDS[alias]["record_id"])


def _review(store, key: str, experts, unit_id: str, *, verdict: tuple[str, str], invented: bool = False) -> None:
    """그 전문가들이 한 단위를 끝까지 — 카드 K01 을 `verdict` 로 보고 같은 메커니즘을 단다(한 클러스터에 모이게)."""
    job_id = rig.job(store, key, scope={"agents": list(experts), "unit_ids": [unit_id]})
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {_rid("K01"): verdict}
    fake.mechs = {_rid("K01"): MECH}
    if invented:
        fake.invented_quote = {"K01"}
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)


def _card_row(store, key: str) -> dict:
    """K01 의 카드 대조 finding 이 모인 등록부 행(병합 뒤)."""
    registry.merge(store, key)
    rows = [r for r in registry.registry_rows(store, key)
            if any(fid for fid in r["merged"].get("member_ids", ()) if "#F" in fid)]
    (row,) = [r for r in rows if r["direction"] == "risk" and r["mechanism"] == "interface"]
    return row


# ---------------------------------------------------------------- 지지 수 · 주장값 · 분포 · 주의 등급
def test_cells_rows_count_experts_domains_units_and_verified_and_keep_the_claimed_fail_under_hold(store):
    """전문가 넷(mech 둘 · xd 둘)이 같은 클러스터를 내면 지지는 전문가 4 · 영역 2 · 단위 1 이고, support 는 전문가 수다(패널 수가
    아니다 — m-16). mech 둘은 FAIL(인용 대조 통과), xd 둘은 WARNING 이다 — hold 로 행은 중대/WARNING 이지만 주장값은 FAIL · FAIL
    전문가 2 · 그 가운데 검증 2 이고 분포가 판정별·영역별로 남는다. 검증된 FAIL 주장이라 주의 등급 A 다."""
    key = rig.target(store)
    unit = units.load_units(store, key)[0]["unit_id"]
    _review(store, key, (SEAL, "mech-syn-0"), unit, verdict=("yes", "FAIL"))
    _review(store, key, ("xd-syn-0", "xd-syn-1"), unit, verdict=("yes", "WARNING"))
    row = _card_row(store, key)
    assert (row["support_experts"], row["support_domains"], row["support_units"], row["support_verified"]) == (4, 2, 1, 4)
    assert row["support"] == 4
    assert (row["severity"], row["judgement"]) == ("중대", "WARNING")
    claimed = row["merged"]["claimed"]
    assert (claimed["judgement"], claimed["severity"], claimed["fail_experts"], claimed["verified_fail_experts"]) == (
        "FAIL", "중대", 2, 2)
    distribution = row["merged"]["distribution"]
    assert distribution["by_judgement_claimed"] == {"FAIL": 2, "WARNING": 2}
    assert distribution["raisers_by_domain"] == {"mech": 2, "xd": 2}
    assert row["merged"]["unit_ids"] == [unit]
    assert row["attention"] == "A"
    assert store.query_one("SELECT attention FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
                           (key, row["cluster_key"]))["attention"] == "A"


def test_an_unverified_fail_claim_does_not_raise_the_attention(store):
    """카드 인용이 카드에 없는(대조 실패 — quote_mismatch) FAIL 주장은 주의 등급을 올리지 않는다(X1-18 (1)) — 주장값은 FAIL 로 남고
    카드로 검증된 FAIL 은 0 이며, 행은 중대라 B 다. 변경 줄 인용은 대조를 지나므로 support_verified 에는 든다(인용 하나라도)."""
    key = rig.target(store)
    unit = units.load_units(store, key)[0]["unit_id"]
    _review(store, key, (SEAL, "xd-syn-0"), unit, verdict=("yes", "FAIL"), invented=True)
    row = _card_row(store, key)
    assert (row["merged"]["claimed"]["judgement"], row["merged"]["claimed"]["verified_fail_experts"]) == ("FAIL", 0)
    assert (row["support_verified"], row["support_domains"]) == (2, 2)
    assert row["attention"] == "B"


def test_a_cells_target_contributes_nothing_to_the_cross_project_statistics(store):
    """cells 대상은 M3 동안 rr_delta_contrib 에 기여하지 않는다(M3 #57) — 병합해도 그 대상의 기여 행이 없다."""
    key = rig.target(store)
    unit = units.load_units(store, key)[0]["unit_id"]
    _review(store, key, (SEAL,), unit, verdict=("yes", "FAIL"))
    out = registry.merge(store, key)
    assert out["flow"] == "cells" and out["clusters"] >= 1
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_delta_contrib WHERE target_key = ?", (key,))["n"] == 0


def test_a_human_decision_on_a_cells_row_records_the_domain_baseline_and_moves_the_attention(store):
    """사람이 닫으면 기준선에 영역 수(support_domains_at_decision)가 같이 남고(P-17-10), 기각으로 닫힌 행은 주의 등급 D 다."""
    key = rig.target(store)
    unit = units.load_units(store, key)[0]["unit_id"]
    _review(store, key, (SEAL, "xd-syn-0"), unit, verdict=("yes", "FAIL"))
    row = _card_row(store, key)
    registry.set_status(store, row["cluster_key"], "dismissed", owner_sub=OWNER, target_key=key, evidence_ref="rpt:1")
    after = store.query_one("SELECT status_basis_json, attention FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
                            (key, row["cluster_key"]))
    assert json.loads(after["status_basis_json"])["support_domains_at_decision"] == 2
    assert after["attention"] == "D"
    registry.merge(store, key)                                      # 다시 병합해도 사람의 상태로 센다
    assert store.query_one("SELECT attention FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
                           (key, row["cluster_key"]))["attention"] == "D"


def test_a_re_raise_on_a_cells_target_is_compared_by_domains():
    """재제기 비교 — cells 행은 영역 수로 견주고, 기준선이 영역 수를 모르면 옛 지지 수와 견준다. 패널 행은 지금처럼 support 다."""
    row = {"sev3": 2, "support": 9, "support_domains": 2, "evidence_grade": "경험칙"}
    basis = {"sev3_at_decision": 2, "support_at_decision": 1, "grade_at_decision": "경험칙", "support_domains_at_decision": 2}
    assert registry._is_stronger(row, basis, flow="cells") is None
    assert registry._is_stronger(row, basis) == {"sev3": 0, "support": 8, "grade": 0}
    older = {k: v for k, v in basis.items() if k != "support_domains_at_decision"}
    assert registry._is_stronger(row, older, flow="cells") == {"sev3": 0, "support": 1, "grade": 0}


# ---------------------------------------------------------------- 패널을 돌린 뒤 cells 로 바꾼 대상 — 비교 보기
def _panel_spec(store, key: str):
    return legacy.spec_builder(store, key, lambda k: str(k).split("-", 1)[0])


# 병합이 다시 세는 옛 열(v5 의 새 일곱 칸 빼고) — 패널 finding 만으로 센 등록부를 견줄 때.
M2_COLUMNS = [c for c in registry._MERGE_OWNED_COLUMNS if not c.startswith(("support_", "attention", "issue_"))]


def _panel_target(store, tmp_path, monkeypatch) -> tuple[str, dict]:
    """패널 대상 하나를 러너로 돌린다(가짜 패널 엔진) — (대상 키, 등록부 옛 열)."""
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request",
                        lambda *a, **_k: (_ for _ in ()).throw(httpx.ConnectError("외부 없음", request=a[-1])))
    synth = factories.make_diff_target(store, 40, open_target=False)
    key = routes.create_target(routes.TargetBody(kind="diff", ref_id=synth.diff_id, consent=True, flow="panels",
                                                 agents=[dict(r) for r in rig.ROSTER]), ident=factories.ident(OWNER))["target_key"]
    rig.pat(store)
    cfg = dataclasses.replace(config.settings, data_dir=tmp_path)
    runner.create_job(store, key, "A", owner_sub=OWNER, consent=True, settings=cfg)
    engine = legacy.LegacyEngine(_panel_spec(store, key))
    while (job := runner.claim_next_job(store, cfg)) is not None:
        runner.run_panel(store, cfg, engine, job)
    before = {r["cluster_key"]: {c: r[c] for c in M2_COLUMNS if c in r} for r in registry.registry_rows(store, key)}
    assert before
    return key, before


def test_a_review_layered_on_a_panels_target_leaves_its_registry_as_it_was(store, tmp_path, monkeypatch):
    """패널 대상에 M2 방식으로 검토를 얹어도(흐름 panels 그대로 — M2 #3) 등록부는 패널 finding 만 센다(#7·#20) — 병합 뒤 행 집합과
    옛 열이 얹기 전과 같고, 주장값이 실린 행이 없다."""
    key, before = _panel_target(store, tmp_path, monkeypatch)
    with factories.routes_store(store):
        routes.post_units(key, routes.UnitsBody(reason="검토 얹기"), ident=factories.ident(OWNER))
    unit = units.load_units(store, key)[0]["unit_id"]
    _review(store, key, (SEAL, "xd-syn-0"), unit, verdict=("yes", "FAIL"))
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_findings WHERE target_key = ? AND source_kind = 'card_review'",
                           (key,))["n"] >= 2
    out = registry.merge(store, key)
    assert out["flow"] == "panels"
    rows = registry.registry_rows(store, key)
    assert {r["cluster_key"]: {c: r[c] for c in M2_COLUMNS if c in r} for r in rows} == before
    assert not any(r["merged"].get("claimed") for r in rows)


def test_a_target_switched_to_cells_merges_both_sources_and_the_panels_view_matches_the_old_registry(store, tmp_path,
                                                                                                     monkeypatch):
    """패널을 돌린 대상(flow='panels')을 cells 로 바꾸고 카드 대조를 얹으면 등록부가 두 출처를 한 장으로 합친다(카드 finding 행이
    선다). `GET …/registry?source=panels` 는 저장 없이 패널 finding 만으로 다시 센 보기라 바꾸기 전 등록부의 옛 열과 같다."""
    key, before = _panel_target(store, tmp_path, monkeypatch)
    routes.post_target_flow(key, routes.FlowBody(to="cells", reason="카드 대조 얹기"), ident=factories.ident(OWNER))
    unit = units.load_units(store, key)[0]["unit_id"]
    _review(store, key, (SEAL,), unit, verdict=("yes", "FAIL"))
    registry.merge(store, key)
    merged = registry.registry_rows(store, key)
    assert any(r["merged"].get("claimed") for r in merged)                  # 카드 대조 finding 이 등록부에 들었다
    assert all(r["support"] == r["support_experts"] for r in merged)       # cells 대상의 support 는 전문가 수다(m-16)
    view = routes.registry_payload(key, owner_sub=OWNER, source="panels")["rows"]
    got = {r["cluster_key"]: {c: r.get(c) for c in before.get(r["cluster_key"], {})} for r in view}
    assert got == before
    with pytest.raises(Exception):
        routes.registry_payload(key, owner_sub=OWNER, source="cards")


def test_the_registry_payload_filters_by_attention_and_unit_and_orders_cells_rows_by_attention(store):
    """cells 대상의 등록부 조회 — 주의 등급(쉼표로 여럿)·단위로 거르고, 주의 등급 → 우선순위 → 영역 수 순이다."""
    key = rig.target(store)
    first, second = [u["unit_id"] for u in units.load_units(store, key)[:2]]
    _review(store, key, (SEAL, "mech-syn-0"), first, verdict=("yes", "FAIL"))
    _review(store, key, (SEAL,), second, verdict=("yes", "WARNING"))
    registry.merge(store, key)
    rows = routes.registry_payload(key, owner_sub=OWNER)["rows"]
    order = [registry.ATTENTION_ORDER[r["attention"]] for r in rows]
    assert order == sorted(order) and len(set(r["attention"] for r in rows)) >= 1
    only = routes.registry_payload(key, owner_sub=OWNER, unit_id=second)["rows"]
    assert only and all(second in r["merged"]["unit_ids"] for r in only)
    attention = rows[0]["attention"]
    picked = routes.registry_payload(key, owner_sub=OWNER, attention=f"{attention.lower()},Z")["rows"]
    assert picked and {r["attention"] for r in picked} == {attention}


# ---------------------------------------------------------------- 카드 대조 거름 자리 래칫(S3-4 ⑥)
# app 안에서 `card_review'` 글자로 카드 대조 finding 을 거르는 자리 — 대상 범위로 읽는 셋은 흐름으로 가르는 조각 하나(FINDING_SCOPE_SQL)를
# 쓰고, 나머지는 까닭이 있어 그대로 둔다(주석이 그 자리에 있다). 새 자리를 넣으면 여기에 까닭과 함께 적어야 한다.
CARD_REVIEW_SITES: dict[tuple[str, str], str] = {
    ("registry.py", "<module>"): "FINDING_SCOPE_SQL — 흐름으로 가른다(패널 대상만 거른다)",
    ("registry.py", "finding_scope"): "FINDING_SCOPE_SQL 의 표 별칭 판",
    ("registry.py", "_load_findings"): "include_card=False — '패널만 본 등록부' 비교 보기",
    ("registry.py", "_minutes_lines"): "패널 범위(panel_id)",
    ("narrative.py", "persist_panel_result"): "패널 범위(panel_id)",
    ("runner.py", "repersist_panel"): "패널 범위(panel_id)",
    ("brief.py", "scholar_query"): "패널 브리프",
    ("learning.py", "<module>"): "과제 가로지르는 학습 — M2 #9",
    ("learning.py", "on_label"): "과제 가로지르는 학습 — M2 #9",
    ("learning.py", "_sample_claims"): "과제 가로지르는 학습 — M2 #9",
    ("learning.py", "mine_patterns"): "과제 가로지르는 학습 — M2 #9",
    ("metrics.py", "_finding_row"): "과제 가로지르는 지표 — M2 #9",
    ("metrics.py", "precedents_by_model"): "과제 가로지르는 지표 — M2 #9",
    ("metrics.py", "distinct_models"): "과제 가로지르는 지표 — M2 #9",
    ("metrics.py", "_load_atoms"): "과제 가로지르는 지표 — M2 #9",
    ("metrics.py", "sync_labels"): "과제 가로지르는 지표 — M2 #9",
    ("nightly.py", "scan_unclassified"): "야간 미분류 스캔 — M2 #9",
    ("routes.py", "_next_human_claim_uid"): "사람 finding 순번 — 카드 finding 이 걸릴 수 없다",
    ("routes.py", "put_curation"): "의심 문구 회수 — M2 #9",
    ("export.py", "clip_queue_payload"): "독스트링(거름 아님)",
    ("expert_report.py", "<module>"): "모듈 독스트링(거름 아님)",
}


def _sites(source: str) -> set[str]:
    out: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.where = ["<module>"]

        def visit_FunctionDef(self, node: ast.AST) -> None:
            self.where.append(node.name)
            self.generic_visit(node)
            self.where.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str) and "card_review'" in node.value:
                out.add(self.where[-1])

    Visitor().visit(ast.parse(source))
    return out


def test_every_card_review_filter_site_is_classified():
    found = {(path.name, fn) for path in sorted(APP.rglob("*.py")) for fn in _sites(path.read_text(encoding="utf-8"))}
    assert found == set(CARD_REVIEW_SITES), sorted(found ^ set(CARD_REVIEW_SITES))
    # 대상 범위로 읽는 세 자리는 흐름 조각을 쓴다(글자 거름이 아니다).
    registry_src = (APP / "registry.py").read_text(encoding="utf-8")
    assert re.search(r"def _contested_marking_done.*?FINDING_SCOPE_SQL", registry_src, re.S)
    assert "registry_module.FINDING_SCOPE_SQL" in (APP / "routes.py").read_text(encoding="utf-8")
