# 완결 판정(재설계 M3 S3-8) — cells 대상의 레벨·잔여·표기·사람 확인·캐시가 원장에서 서는지 본다(잔여가 남으면 맨 C3 가 없다)
"""입력은 생산자다 — 대상·단위는 합성 쌍 → 라우트, 셀·판정·보고서는 가짜 검토 엔진을 꽂은 M2 검토 루프, 쟁점은 S3-6 선정,
쟁점 패널은 러너가 가짜 쟁점 패널 엔진으로 돈다. 셀 몫(`review_cells.closure_cells`)은 셀 꾸러미가 합쳐지기 전이라, 거르기 표본처럼
M2 원장으로 만들 수 없는 칸만 M3.md 4.10 의 모양 그대로 대역으로 꽂는다(`_with_filter`).
"""
from __future__ import annotations

import sqlite3
import time

import pytest
from pydantic import ValidationError

from app import closure, config, registry, review_cells, review_runner, routes, runner, units
from app.errors import AppError
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.synth.issue_panel_engine import IssuePanelEngine

OWNER = rig.OWNER
SEAL = rig.SEAL
EDITOR = "editor@example.com"
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}
NO_ROWS = {"code": "no_rows", "message": "판정 행이 하나도 없다(가짜)", "infra": False, "retryable": False}


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _rid(alias: str) -> str:
    return str(CARDS[alias]["record_id"])


# 카드 묶음이 있는 전문가만의 로스터 — 배경 카드뿐·0장 전문가는 basis='cards' 셀이 없어 그 영역의 깊이(have)에 들지 않는다(X1-04).
CARD_ROSTER = tuple(r for r in rig.ROSTER if r["key"] in rig.CARD_EXPERTS)


def _full_grid(store, *, verdicts=None, error_cells=None, roster=rig.ROSTER) -> str:
    """로스터 전원 × 검토 대상 단위 전부를 검토 루프로 끝까지 — 대상 키."""
    key = rig.target(store, roster)
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {_rid(a): v for a, v in (verdicts or {}).items()}
    fake.mechs = {_rid(a): ("interface.clearance", "") for a in (verdicts or {})}
    fake.error_cells = dict(error_cells or {})
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)
    registry.merge(store, key)
    return key


def _residual(result: dict, item: str) -> dict | None:
    return next((q for q in result["qualifiers"] if q["item"] == item), None)


# ---------------------------------------------------------------- 표기
def test_the_label_is_the_bare_level_only_without_residuals():
    """잔여가 0 일 때만 맨 레벨 이름이다 — 있으면 괄호 안에 ' · ' 로, 오르지 못한 머리는 따로."""
    assert closure.level_label("C2", []) == "C2"
    assert closure.level_label("C3", ["2차 영향 미실행(넘김 0건 표만)", "결손 사냥 미실행"]) == \
        "C3(2차 영향 미실행(넘김 0건 표만) · 결손 사냥 미실행)"
    assert closure.level_label("C2", ["실패 1셀"], head="C2 · C3 대기") == "C2 · C3 대기(실패 1셀)"


# ---------------------------------------------------------------- 레벨 사다리
def test_a_cells_target_climbs_with_its_ledger_and_never_shows_a_bare_level(store, monkeypatch, tmp_path):
    """검토 전 C0(격자 결손) → 대표 셀만 닫히면 C1(열린 셀 · 쟁점 선정 전) → 격자를 다 돌면 사슬이 쟁점을 고르고(S3-5) P1 쟁점이
    도는 동안 C1(쟁점 진행) → 쟁점 패널이 끝나면 C2. 종합 보고서 판이 없어 C3 는 아니다(후속 낡음). 어느 단계든 표기는 맨 레벨
    이름이 아니다 — 2차 영향·결손 사냥 미실행이 늘 붙는다. 문지기(registry.close_level)가 cells 대상에 이 판정을 쓴다."""
    rig.configure(monkeypatch, store, tmp_path, risk_issue_panel_cap=48, risk_issue_panel_hard_cap=48)
    key = rig.target(store)
    before = registry.close_level(store, key, persist=False)
    assert before["flow"] == "cells" and before["level"] == "C0" and "격자 결손" in before["level_label"]   # 검토 잡 전
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {_rid("K01"): ("yes", "FAIL")}                       # sim 은 카드 없는 영역 — 깊이를 막지 않는다(D-35)
    fake.mechs = {_rid("K01"): ("interface.clearance", "")}
    reps = [r["key"] for r in rig.ROSTER if r["key"] in (rig.SEAL, rig.BACKGROUND_ONLY, "xd-syn-0")]
    job_id = rig.job(store, key, scope={"agents": reps})
    rig.Rig(store, fake).finish(job_id)
    first = registry.close_level(store, key)
    assert (first["level"], first["c1"], first["c2"]) == ("C1", True, False)
    assert "열린 셀" in first["level_label"] and "후속 낡음(쟁점 선정 전)" in first["level_label"]
    job_id = rig.job(store, key)
    rig.Rig(store, fake).finish(job_id)
    waiting = registry.close_level(store, key)
    assert waiting["counts"]["cells"]["actual"] == waiting["counts"]["cells"]["expected"] > 0
    assert waiting["counts"]["issues"]["p1"]["open"] >= 1 and waiting["level"] == "C1" and "쟁점 진행" in waiting["level_label"]
    engine = IssuePanelEngine(store)
    while (job := runner.claim_next_job(store, config.settings, engine=engine)) is not None:
        if runner.run_panel(store, config.settings, engine, job)["status"] == "no_panel":
            break
    done = registry.close_level(store, key)
    assert (done["level"], done["c2"], done["c3"]) == ("C2", True, False)
    assert "후속 낡음(종합 전)" in done["level_label"] and "카드 없는 영역 — 역할 판단만 · sim" in done["level_label"]
    for result in (before, first, waiting, done):
        assert result["level_label"] != result["level"]
        assert "결손 사냥 미실행" in result["level_label"] and "2차 영향 미실행" in result["level_label"]
    cached = closure.cached(store, key)
    assert cached["level_label"] == done["level_label"]
    assert store.query_one("SELECT level, level_label FROM rr_targets WHERE target_key = ?", (key,))["level_label"] == \
        done["level_label"]


def test_the_stored_level_never_drops_and_a_lower_count_is_reported_as_regressed(store):
    """저장 레벨은 내려가지 않는다 — 지금 계산이 낮으면 level_current 와 regressed 로 알린다(X1-24). 사람이 대표 셀을 다시 열면(셀
    처분 — 잡은 세우지 않는다) 그 셀이 열린 동안 계산은 C0 이다."""
    key = _full_grid(store)                               # 쟁점 없음 → 사슬이 곧바로 종합 잡(쟁점 단계 신선) → C2
    assert registry.close_level(store, key)["level"] == "C2"
    job_id = rig.job(store, key)                         # 같은 격자를 다시 — 셀은 그대로 닫혀 있다
    assert rig.state(store, job_id) in ("queued", "running", "completed")
    again = registry.close_level(store, key)
    assert again["level"] == "C2"
    runner.cancel_job(store, job_id, by=OWNER)
    rep = store.query_one("SELECT unit_id, agent_key, state FROM rr_review_cells WHERE target_key = ? AND agent_key = ?"
                          " ORDER BY unit_seq LIMIT 1", (key, SEAL))
    review_runner.dispose_cells(store, key, action="retry", rows=[dict(rep)], decided_by=OWNER, owner_sub=OWNER,
                                note="다시 본다", force=True, start=False)
    reopened = registry.close_level(store, key)
    assert (reopened["level"], reopened["level_current"], reopened["regressed"]) == ("C2", "C0", True)
    assert "재개방 1셀" in reopened["level_label"]


# ---------------------------------------------------------------- 잔여 · 확인
def test_a_failed_cell_is_a_blocking_residual_that_only_the_owner_can_ack_with_a_reason_and_the_current_hash(store,
                                                                                                            monkeypatch):
    """실패 셀은 막음 잔여다. 확인은 소유자·관리자만(편집자 403), 사유 필수(422), 확인 시점의 basis_hash 가 다르면 409, 막음 잔여가
    아니면 422 ack_not_allowed. 확인·취소마다 rr_audit 한 행이고 캐시가 새로 써진다. 취소는 행을 지우지 않는다."""
    order = None
    key = rig.target(store)
    order = [u["unit_id"] for u in units.load_units(store, key)]
    job_id = rig.job(store, key)
    fake = FakeReviewEngine(rig.packs())
    fake.error_cells = {("xd-syn-1", order[-1]): NO_ROWS}
    rig.Rig(store, fake).finish(job_id)
    registry.merge(store, key)
    result = closure.refresh(store, key)
    failed = _residual(result, "failed")
    assert failed and failed["blocking"] and failed["n"] == 1 and not failed["acked"]
    assert "실패 1셀" in result["level_label"]
    project_id = store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]
    with factories.routes_store(store):
        routes.put_members(project_id, routes.MembersBody(members=[routes.MemberItem(email=EDITOR, role="editor")]),
                           ident=factories.ident(OWNER))
        with pytest.raises(AppError) as denied:
            routes.post_closure_ack(key, "failed", routes.CloseAckBody(reason="재시도 무의미", basis_hash=failed["basis_hash"]),
                                    ident=factories.ident(EDITOR))
        assert denied.value.http_status == 403
        with pytest.raises(AppError) as blank:
            routes.post_closure_ack(key, "failed", routes.CloseAckBody(reason="  ", basis_hash=failed["basis_hash"]),
                                    ident=factories.ident(OWNER))
        assert blank.value.http_status == 422
        with pytest.raises(ValidationError):
            routes.CloseAckBody(reason="가" * 301, basis_hash=failed["basis_hash"])
        with pytest.raises(AppError) as moved:
            routes.post_closure_ack(key, "failed", routes.CloseAckBody(reason="재시도 무의미", basis_hash="000000000000"),
                                    ident=factories.ident(OWNER))
        assert (moved.value.http_status, moved.value.code) == (409, "residual_changed")
        with pytest.raises(AppError) as label_only:
            routes.post_closure_ack(key, "mech_not_run", routes.CloseAckBody(reason="M4", basis_hash="x"),
                                    ident=factories.ident(OWNER))
        assert (label_only.value.http_status, label_only.value.code) == (422, "ack_not_allowed")
        audits = store.query_one("SELECT COUNT(*) AS n FROM rr_audit WHERE subject_id = ? AND action LIKE 'close.ack%'",
                                 (key,))["n"]
        assert audits == 0
        out = routes.post_closure_ack(key, "failed", routes.CloseAckBody(reason="그 단위는 입력이 비어 다시 돌려도 같다",
                                                                         basis_hash=failed["basis_hash"]),
                                      ident=factories.ident(OWNER))
        assert out["basis_n"] == 1
        payload = routes.closure_payload(key, owner_sub=OWNER)
        assert _residual(payload, "failed")["acked"] and [a["state"] for a in payload["acks"]] == ["valid"]
        assert payload["level_label"] == out["level_label"]
        routes.delete_closure_ack(key, "failed", ident=factories.ident(OWNER))
        payload = routes.closure_payload(key, owner_sub=OWNER)
        assert not _residual(payload, "failed")["acked"] and [a["state"] for a in payload["acks"]] == ["revoked"]
    actions = [r["action"] for r in store.query("SELECT action FROM rr_audit WHERE subject_id = ? AND action LIKE"
                                                " 'close.ack%' ORDER BY at, action", (key,))]
    assert sorted(actions) == ["close.ack", "close.ack.revoke"]
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_close_acks WHERE target_key = ?", (key,))["n"] == 1
    # 같은 초에 다시 확인해도 이력 행이 겹치지 않는다(ack_at 이 키의 일부 — 취소 뒤 곧바로 다시 확인). 시계를 첫 확인의 초에 묶는다.
    first_at = store.query_one("SELECT ack_at FROM rr_close_acks WHERE target_key = ?", (key,))["ack_at"]
    monkeypatch.setattr(closure.common, "now_epoch", lambda: first_at)
    try:
        again = closure.ack_residual(store, key, "failed", reason="다시 확인한다", by=OWNER, basis_hash=failed["basis_hash"])
    except sqlite3.IntegrityError as exc:
        pytest.fail(f"같은 초의 두 번째 확인이 이력 키에 부딪쳤다 — {exc}")
    assert again["ack_at"] == first_at + 1
    assert _residual(closure.refresh(store, key), "failed")["acked"]


def test_an_ack_goes_stale_when_the_residual_set_changes(store):
    """확인 뒤 집합이 바뀌면(실패가 하나 는다) 그 확인은 낡아 다시 받는다 — 표기에 그 잔여가 다시 막음으로 선다."""
    key = rig.target(store)
    order = [u["unit_id"] for u in units.load_units(store, key)]
    job_id = rig.job(store, key, scope={"agents": ["xd-syn-1"], "unit_ids": order[-1:]})
    fake = FakeReviewEngine(rig.packs())
    fake.error_cells = {("xd-syn-1", order[-1]): NO_ROWS, ("xd-syn-0", order[-1]): NO_ROWS}
    rig.Rig(store, fake).finish(job_id)
    failed = _residual(closure.refresh(store, key), "failed")
    closure.ack_residual(store, key, "failed", reason="첫 실패는 넘긴다", by=OWNER, basis_hash=failed["basis_hash"])
    assert _residual(closure.refresh(store, key), "failed")["acked"]
    job_id = rig.job(store, key, scope={"agents": ["xd-syn-0"], "unit_ids": order[-1:]})
    rig.Rig(store, fake).finish(job_id)
    after = _residual(closure.refresh(store, key), "failed")
    assert after["n"] == 2 and not after["acked"] and after["ack"]["state"] == "stale"


def test_undetermined_applies_above_a_fifth_block_and_below_only_label(store):
    """보류(적용 판정 가운데 applies=unknown · judgement=undetermined)가 20% 를 넘으면 막음, 아니면 표기(#52)."""
    many = _full_grid(store, verdicts={a: ("unknown", "undetermined") for a in ("K01", "K02", "K03", "K04", "K05", "K06")})
    held = _residual(closure.close_level_cells(store, many, persist=False), "undetermined")
    assert held and held["ratio"] > closure.UNDETERMINED_MAX and held["blocking"]
    few = _full_grid(store, verdicts={"K01": ("unknown", "undetermined")})
    light = _residual(closure.close_level_cells(store, few, persist=False), "undetermined")
    assert light and light["ratio"] <= closure.UNDETERMINED_MAX and not light["blocking"]


def _with_filter(monkeypatch, store, key: str, *, floor_met: bool, upper95: float | None, off: bool = False) -> None:
    """셀 몫의 거르기 칸만 M3.md 4.10 모양 그대로 덮는다(나머지는 셀 원장 그대로) — 거르기는 셀 꾸러미(C3-6·C3-7)가 낸다."""
    real = closure._cells_from_ledger(store, key)

    def provider(_store, _key):
        return {**{k: v for k, v in real.items() if k != "_rows"},
                "filtered": {"n": 40, "would_filter": 40, "by_domain": {"xd": 40},
                             "audit": {"sampled": 12, "floor_met": floor_met, "risk_miss": 0, "relevance_miss": 1,
                                       "undetermined": 0, "kept": 12, "upper95": upper95, "upper95_conservative": upper95},
                             "shadow": False, "widened": 0, "off": off}}

    monkeypatch.setattr(review_cells, "closure_cells", provider, raising=False)


@pytest.mark.parametrize(("floor_met", "upper95", "off", "blocking"), [
    (True, 0.012, False, False), (False, 0.012, False, True), (True, 0.08, False, True), (True, 0.01, True, True)])
def test_filtered_cells_are_a_label_unless_the_sample_fell_short_or_the_bound_is_wide(store, monkeypatch, floor_met,
                                                                                      upper95, off, blocking):
    """거름은 표기다 — 표본 하한을 못 채웠거나 놓침 95% 상한이 5% 를 넘거나 거르기가 꺼졌다 켜졌으면 막음."""
    key = _full_grid(store)
    _with_filter(monkeypatch, store, key, floor_met=floor_met, upper95=upper95, off=off)
    result = closure.close_level_cells(store, key, persist=False)
    item = _residual(result, "filtered")
    assert item["n"] == 40 and item["blocking"] is blocking
    assert "거름 40셀(표본 12 · 놓친 걸림 0 · 95% 상한" in result["level_label"]


def test_a_panels_target_keeps_its_panel_verdict_through_the_gate(store, tmp_path, monkeypatch):
    """패널 대상은 문지기가 지금 본문(`_close_level_panels`)을 그대로 쓰고 캐시를 쓰지 않는다(바이트 동일은 test_panel_registry_bytes)."""
    from tests.test_registry_cells import _panel_target

    key, _old = _panel_target(store, tmp_path, monkeypatch)
    assert registry.close_level(store, key, persist=False) == registry._close_level_panels(store, key, persist=False)
    assert closure.refresh(store, key)["refreshed"] is False
    assert store.query_one("SELECT closure_json FROM rr_targets WHERE target_key = ?", (key,))["closure_json"] is None


def test_refresh_on_the_largest_m2_ledger_stays_well_under_a_second(store):
    """캐시 쓰기 한 번의 시간 — M2 루프로 만들 수 있는 가장 큰 원장(로스터 6 × 단위 5)에서 잰다. 359명 규모는 단계 D 리허설이 잰다."""
    key = _full_grid(store, verdicts={"K01": ("yes", "FAIL"), "K02": ("yes", "WARNING")})
    started = time.perf_counter()
    closure.refresh(store, key)
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(("roster", "exempt", "mixed", "failing", "blocked"), [
    (rig.ROSTER, ["sim"], {}, None, []),                                           # 배경 카드뿐 + 0장 — 리그의 sim
    (CARD_ROSTER + ({"key": rig.ZERO_CARDS, "domain": "material", "relevance": 0.8},), ["material"], {}, None, []),
    # 카드 가진 영역에 0장 한 명이 섞였다 — 깊이는 카드로 본 둘만 세고(둘 다 닫혔다) 0장은 잔여에 이름만(review1 M5)
    (CARD_ROSTER + ({"key": rig.ZERO_CARDS, "domain": "mech", "relevance": 0.5},), [], {"mech": 1}, None, []),
    # 카드로 본 사람이 깊이에 못 미치면(한 명의 셀이 전부 실패) 지금처럼 막는다
    (CARD_ROSTER, [], {}, "mech-syn-0", ["mech"]),
])
def test_a_domain_whose_active_experts_all_lack_cards_is_a_label_not_a_depth_block(store, roster, exempt, mixed, failing,
                                                                                    blocked):
    """D-35 — 카드 0장 전문가는 역할만으로 답하고 보고서에 잔여로 남는다. 실제로 검토한 전문가가 전부 카드 없이 본 영역은 C2 깊이를
    막지 않고 표기 잔여 depth_no_cards('카드 없는 영역 — 역할 판단만 · <영역>')가 선다. 깊이의 분모·분자는 카드로 본 전문가만이라
    (review1 M5 — 조정자 결정) 카드 없는 사람이 섞인 영역은 카드로 본 사람들이 깊이를 채우면 막히지 않고 그 사람 수가 잔여에
    '<영역>(그중 N명)' 으로 선다. 카드로 본 사람이 깊이에 못 미치면 지금처럼 막는다(카드 없이 본 사람은 have 에 들지 않는다 — X1-04)."""
    unit_ids = None
    if failing:
        probe = rig.target(store, roster)
        unit_ids = [u["unit_id"] for u in units.load_units(store, probe)]
    key = _full_grid(store, roster=roster,
                     error_cells={(failing, u): NO_ROWS for u in unit_ids} if failing else None)
    result = closure.close_level_cells(store, key, persist=False)
    depth = result["detail"]["depth"]
    assert sorted(d for d, v in depth.items() if v.get("exempt") == "no_cards") == exempt
    for domain in blocked:
        assert "exempt" not in depth[domain] and depth[domain]["have"] < depth[domain]["need"]
        assert f"깊이 미달 {domain} {depth[domain]['have']}/{depth[domain]['need']}" in result["level_label"]
    if not blocked:
        assert "깊이 미달" not in result["level_label"]
    for domain in mixed:
        assert depth[domain]["have"] >= depth[domain]["need"] and depth[domain]["cardless"] == mixed[domain]
    item = _residual(result, "depth_no_cards")
    if exempt or mixed:
        names = exempt + [f"{d}(그중 {n}명)" for d, n in sorted(mixed.items())]
        assert item and not item["blocking"] and item["domains"] == exempt and item["mixed"] == mixed
        assert f"카드 없는 영역 — 역할 판단만 · {'·'.join(names)}" in result["level_label"]
    else:
        assert item is None
