# v5 새 표의 반출·이양·폐기 등록과 행 단위 반출 변환(재설계 M3 S3-1) — 행은 각 표의 생산자 걸음으로만 만든다(손 INSERT 금지)
"""S3-1 은 표와 등록·반출 변환만 넣는다. 새 표 행의 생산자는 뒤 걸음에 선다 — 등록부의 카드 인용은 S3-4(`registry.finding_scope` — 섰다),
쟁점은 S3-6(`issues.select_issues` — 섰다), 쟁점 패널은 S3-7, 완결 확인은 S3-8, 요약·보고서 판은 S3-9, 근거 꾸러미 실호출은 셀 꾸러미
C3-12(`unit_live.ensure`)다. 생산자가 아직 없는 행 시험은 자리표시(strict xfail)로 두었다가 그 걸음이 서면 표식을 지우고 그
생산자에 다시 묶는다(M3.md 4.2 끝 · m3-synthesis S3-1) — 등록부·쟁점 둘은 묶였다.
"""
from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from typing import Any

from app import export, issues, registry, routes, units
from app.risk_store import RiskStore
from tests import factories
from tests.rr import v4_build
from tests.rr.test_v4_upgrade import _thaw
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig

OWNER = factories.OWNER
HEIR = "heir@example.com"
V5_OWNED = ("rr_issues", "rr_summaries", "rr_reports", "rr_close_acks", "rr_unit_live")
BY_TARGET = "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"


# ---------------------------------------------------------------- 등록
def test_v5_tables_are_registered_for_transfer_and_purge():
    """새 표 다섯은 이양이 owner_sub 를 옮기고(타깃 경유) 폐기가 원문 열을 비운다 — 쟁점의 근거·결과·좌석·재제기, 요약의 서술·대조,
    보고서 판의 쪽(빈 쪽 목록 gzip — NOT NULL), 완결 확인의 사유, 근거 꾸러미의 근거 줄·호출 계획·못 받은 사유. 대상의 완결 캐시도
    비운다(대상 행은 과제를 직접 가리킨다 — 이양은 TRANSFER_PROJECT_TABLES 가 한다)."""
    moved = dict(routes.TRANSFER_DERIVED)
    blanked = dict(routes.PURGE_BLANK_SQL)
    assert len(moved) == len(routes.TRANSFER_DERIVED) and len(blanked) == len(routes.PURGE_BLANK_SQL)
    for table in V5_OWNED:
        assert moved.get(table) == BY_TARGET, table
        assert blanked.get(table, "").startswith(f"UPDATE {table} SET ") and blanked[table].endswith(BY_TARGET), table
    for table, sets in {
        "rr_issues": ("basis_json = ''", "outcome_json = NULL", "seats_json = NULL", "reraised_json = NULL"),
        "rr_summaries": ("output_json = NULL", "checks_json = NULL"),
        "rr_reports": (f"pages_gz = X'{routes._EMPTY_PAGES_GZ.hex()}'", "pages_n = 0"),
        "rr_close_acks": ("ack_reason = '[purged]'",),
        "rr_unit_live": ("lines_gz = NULL", "plan_json = '[]'", "gaps_json = NULL"),
        "rr_targets": ("closure_json = NULL",),
    }.items():
        for clause in sets:
            assert clause in blanked.get(table, ""), (table, clause)
    assert blanked["rr_targets"].endswith("WHERE project_id = ?") and "rr_targets" in routes.TRANSFER_PROJECT_TABLES
    assert gzip.compress(b"[]", mtime=0) == routes._EMPTY_PAGES_GZ        # 빈 쪽 목록 · 같은 바이트(시각 0)


def test_the_v5_purge_statements_run_on_a_risen_v4_ledger(tmp_path):
    """폐기 문장이 실제 v5 원장에서 돈다 — 얼린 v4 원장(M2 검토 루프가 채운 대상)을 올린 뒤 그 과제를 폐기하면 오류 없이 끝나고,
    대상의 완결 캐시가 비며 카드 대조 finding 글이 빈다(v5 문장이 앞 판의 문장을 막지 않는다)."""
    store = RiskStore(_thaw(v4_build.V4_DIR / v4_build.DB_GZ, tmp_path))
    store.open()
    store.migrate()
    manifest = json.loads((v4_build.V4_DIR / "manifest.json").read_text(encoding="utf-8"))
    key = manifest["targets"]["reviewed"]["target_key"]
    owner = manifest["owner"]
    try:
        project_id = store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]
        code = store.query_one("SELECT code FROM rr_projects WHERE id = ?", (project_id,))["code"]
        with factories.routes_store(store):
            out = routes.purge_project(project_id, routes.PurgeBody(code=code, reason="정리"), ident=factories.ident(owner))
        blanked = out["purge_report"]["layers"]["db"]["blanked"]
        assert set(V5_OWNED) | {"rr_targets"} <= set(blanked)
        assert blanked["rr_targets"] == 1 and all(blanked[t] == 0 for t in V5_OWNED)     # 새 표는 아직 빈 표다
        assert store.query_one("SELECT closure_json FROM rr_targets WHERE target_key = ?", (key,))["closure_json"] is None
        assert {r["finding_json"] for r in store.query(
            "SELECT finding_json FROM rr_findings WHERE target_key = ? AND source_kind = 'card_review'", (key,))} == {""}
    finally:
        store.close()


# ---------------------------------------------------------------- 반출 변환 — 쟁점 패널의 브리프는 박스 밖으로 나가지 않는다
def test_an_issue_panel_brief_never_leaves_the_box_while_coverage_briefs_still_do(tmp_path):
    """종전 패널(coverage)의 브리프는 반출에 그대로 실린다(패널 대상 바이트 동일 — D-24). 쟁점 패널(kind='issue')의 브리프에는
    카드 절 원문(I6)이 들어 있어 반출이 비운다 — 브리프 해시는 남는다. 쟁점 패널 행의 생산자(S3-7)는 아직 없어, 실제 패널 행(얼린
    v4 원장의 done 패널)을 그 종류만 바꿔 반출 변환에 넣는다."""
    store = RiskStore(_thaw(v4_build.V4_DIR / v4_build.DB_GZ, tmp_path))
    store.open()
    store.migrate()
    try:
        owner = store.query_one("SELECT owner_sub FROM rr_panels WHERE brief_gz IS NOT NULL LIMIT 1")["owner_sub"]
        lines = [json.loads(line) for line in list(export.iter_lines(store, owner, 0))[1:]]
        panels = [item["row"] for item in lines if item["table"] == "rr_panels"]
        briefed = [p for p in panels if p.get("brief_gz")]
        assert briefed and {p["kind"] for p in panels} == {"coverage"}
        local = store.query_one("SELECT brief_gz FROM rr_panels WHERE id = ?", (briefed[0]["id"],))["brief_gz"]
        assert export._decode(briefed[0]["brief_gz"]) == local                  # 종전 패널은 그대로 나간다
        as_issue = export._export_view("rr_panels", {**briefed[0], "kind": "issue"})
        assert as_issue["brief_gz"] is None and as_issue["brief_hash"] == briefed[0]["brief_hash"]
        assert {k: v for k, v in as_issue.items() if k != "brief_gz"} == {
            k: v for k, v in {**briefed[0], "kind": "issue"}.items() if k != "brief_gz"}
    finally:
        store.close()


# ---------------------------------------------------------------- 반출 변환 — 등록부·쟁점의 카드 인용(생산자 걸음이 서면 묶는다)
def _card_quotes(value: Any) -> Iterator[tuple[str, Any]]:
    """JSON 안의 카드 인용 전부 — (인용 글, 원래 길이 칸)."""
    if isinstance(value, list):
        for item in value:
            yield from _card_quotes(item)
    elif isinstance(value, dict):
        if str(value.get("ref") or "").startswith("card:") and isinstance(value.get("quote"), str):
            yield value["quote"], value.get("quote_chars")
        if isinstance(value.get("cq"), str):
            yield value["cq"], value.get("cq_chars")
        for item in value.values():
            yield from _card_quotes(item)


def _exported(store: RiskStore, owner: str = OWNER) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for line in list(export.iter_lines(store, owner, 0))[1:]:
        item = json.loads(line)
        out.setdefault(item["table"], []).append(item["row"])
    return out


def _flagged_cells_target(store: RiskStore, monkeypatch, tmp_path, *, experts: tuple[str, ...]) -> str:
    """검토 루프로 카드 대조 대상 하나를 끝까지 — 점검 카드 전부가 FAIL 이고 인용은 카드에 없는 260자 글이다(가짜 엔진 대본)."""
    review_rig.configure(monkeypatch, store, tmp_path)
    key = review_rig.target(store)
    unit_id = units.load_units(store, key)[0]["unit_id"]
    job_id = review_rig.job(store, key, scope={"agents": list(experts), "unit_ids": [unit_id]})
    packs = review_rig.packs()
    fake = fre.FakeReviewEngine(packs)
    checkable = [c for c in packs[review_rig.SEAL]["cards"] if c.get("checkable")]
    fake.verdicts.update({str(c["record_id"]): ("yes", "FAIL") for c in checkable})
    fake.long_quote = {f"K{n:02d}" for n in range(1, len(checkable) + 1)}
    review_rig.Rig(store, fake).finish(job_id)
    assert review_rig.state(store, job_id) == "completed"
    return key


def test_the_registry_and_issue_clipper_cuts_card_quotes_like_the_m2_clippers_at_any_depth(risk_store, monkeypatch,
                                                                                          tmp_path):
    """등록부 merged_json·쟁점 basis_json 의 줄이기는 M2 의 두 줄이기 — 카드 대조 finding(`_clip_finding`)과 판정 행 cq — 와 같은
    결과다(둘은 반출 왕복 시험이 본다 — 정본을 오라클로). 입력은 검토 루프가 만든 실제 카드 대조 finding 과 판정 행(인용 260자)이다.
    등록부·쟁점 행의 생산자(S3-4·S3-6) 전이라, 그 행들이 품을 자리(목록 안 · 깊은 칸)에 넣어 깊이와 상관없이 줄어드는지 본다."""
    key = _flagged_cells_target(risk_store, monkeypatch, tmp_path, experts=(review_rig.SEAL,))
    findings = [json.loads(r["finding_json"]) for r in risk_store.query(
        "SELECT finding_json FROM rr_findings WHERE target_key = ? AND source_kind = 'card_review'", (key,))]
    long_cites = [c for f in findings for c in f["cites"] if c["ref"].startswith("card:") and len(c["quote"]) > 200]
    assert long_cites and all(c["quote"] == fre.LONG_QUOTE for c in long_cites)
    for finding in findings:
        expected = export._clip_finding(finding)
        got = export._clip_card_text({"members": [finding], "before_issue": {"rep": finding}})
        for clipped in (got["members"][0], got["before_issue"]["rep"]):
            assert clipped["cites"] == expected["cites"]
            assert (clipped["warrant"], clipped.get("warrant_chars")) == (expected["warrant"], expected.get("warrant_chars"))
        assert all(len(text) <= export.EXPORT_CQ_MAX for text, _ in _card_quotes(got))
    verdicts = [dict(r) for r in risk_store.query(
        "SELECT cq, cq_chars FROM rr_card_verdicts WHERE target_key = ? AND cq IS NOT NULL", (key,))]
    assert any(len(v["cq"]) > 200 for v in verdicts)
    for verdict in verdicts:
        expected = export._export_view("rr_card_verdicts", dict(verdict))
        got = export._clip_card_text({"raisers": [{"agent_key": review_rig.SEAL, **verdict}]})["raisers"][0]
        assert (got["cq"], got.get("cq_chars")) == (expected["cq"], expected["cq_chars"])
    # 반출 뷰가 두 표의 그 열에 이 줄이기를 건다 — 등록부 행은 finding 의 인용·근거 문장을 그대로 옮겨 싣는다(registry._merge_cluster).
    merged = {"cites": [c for f in findings for c in f["cites"]], "warrant": findings[0]["warrant"]}
    basis = {"raisers": [{"agent_key": review_rig.SEAL, **v} for v in verdicts], "refs": merged["cites"]}
    for table, column, value in (("rr_registry", "merged_json", merged), ("rr_issues", "basis_json", basis)):
        out = export._export_view(table, {"target_key": key, column: json.dumps(value, ensure_ascii=False)})
        assert json.loads(out[column]) == export._clip_card_text(value), table
        assert all(len(text) <= export.EXPORT_CQ_MAX for text, _ in _card_quotes(json.loads(out[column]))), table


def test_registry_rows_without_card_quotes_leave_the_box_as_they_are(tmp_path):
    """패널 대상의 등록부 행(카드 인용 없음)은 반출 뷰가 손대지 않는다 — 같은 글 그대로 나간다(D-24 의 반출 쪽)."""
    store = RiskStore(_thaw(v4_build.V4_DIR / v4_build.DB_GZ, tmp_path))
    store.open()
    store.migrate()
    try:
        rows = [dict(r) for r in store.query("SELECT target_key, cluster_key, merged_json FROM rr_registry")]
        assert rows
        for row in rows:
            assert export._export_view("rr_registry", row)["merged_json"] is row["merged_json"]
    finally:
        store.close()


def test_registry_rows_of_a_cells_target_leave_the_box_with_card_quotes_cut_to_200(risk_store, monkeypatch, tmp_path):
    """M3 부터 카드 대조 finding 이 등록부에 들어온다(S3-4 생산자 — registry.merge 의 cells 병합). 등록부 merged_json 의 card: 인용과
    «» 근거 문장은 판정당 200자로 줄고 원래 길이(260)가 옆 칸에 실린다. 들여온 박스에서 다시 내보내도 원래 길이가 남는다(들이기가
    다시 부르는 병합이 들여온 finding 의 원래 길이 칸을 옮겨 싣는다)."""
    key = _flagged_cells_target(risk_store, monkeypatch, tmp_path, experts=(review_rig.SEAL,))
    registry.merge(risk_store, key)
    rows = [r for r in _exported(risk_store)["rr_registry"] if r["target_key"] == key]
    quotes = [q for r in rows for q in _card_quotes(json.loads(r["merged_json"]))]
    assert quotes and all(len(text) <= export.EXPORT_CQ_MAX for text, _ in quotes)
    assert any(chars == len(fre.LONG_QUOTE) for _, chars in quotes)
    dest = RiskStore(tmp_path / "dest" / "risk_review.db")
    dest.open()
    dest.migrate()
    try:
        export.import_jsonl(dest, OWNER, "".join(export.iter_lines(risk_store, OWNER, 0)))
        again = [q for r in _exported(dest)["rr_registry"] if r["target_key"] == key
                 for q in _card_quotes(json.loads(r["merged_json"]))]
        assert any(chars == len(fre.LONG_QUOTE) for _, chars in again)
    finally:
        dest.close()


def test_issue_rows_leave_the_box_cut_move_with_the_owner_and_purge_to_no_card_text(risk_store, monkeypatch, tmp_path):
    """쟁점(S3-6 생산자 — issues.select_issues) — 반출에서 basis_json 의 카드 인용이 200자로 줄고 원래 길이가 실린다. 이양이
    owner_sub 를 옮기고, 폐기가 근거·결과·좌석·재제기를 비운다(행과 상태는 남는다)."""
    card_experts = tuple(review_rig.CARD_EXPERTS)
    key = _flagged_cells_target(risk_store, monkeypatch, tmp_path, experts=card_experts)
    registry.merge(risk_store, key)
    issues.select_issues(risk_store, key, selected_round=1)
    rows = [r for r in _exported(risk_store).get("rr_issues", []) if r["target_key"] == key]
    quotes = [q for r in rows for q in _card_quotes(json.loads(r["basis_json"]))]
    assert rows and quotes and all(len(text) <= export.EXPORT_CQ_MAX for text, _ in quotes)
    assert any(chars == len(fre.LONG_QUOTE) for _, chars in quotes)
    project_id = risk_store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]
    code = risk_store.query_one("SELECT code FROM rr_projects WHERE id = ?", (project_id,))["code"]
    with factories.routes_store(risk_store):
        routes.transfer_project(project_id, routes.TransferBody(to_email=HEIR, reason="담당 교체"),
                                ident=factories.ident(OWNER))
        assert {r["owner_sub"] for r in risk_store.query(
            "SELECT owner_sub FROM rr_issues WHERE target_key = ?", (key,))} == {HEIR}
        routes.purge_project(project_id, routes.PurgeBody(code=code, reason="정리"), ident=factories.ident(HEIR))
    left = risk_store.query("SELECT basis_json, outcome_json, seats_json, reraised_json, state FROM rr_issues"
                            " WHERE target_key = ?", (key,))
    assert left and {(r["basis_json"], r["outcome_json"], r["seats_json"], r["reraised_json"]) for r in left} == {
        ("", None, None, None)}
    assert all(r["state"] for r in left)
