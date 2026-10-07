# 등록부 registry.py 검증 — 병합 멱등·support 집계·dissent 보존·stale/superseded·verdict 후보·완결 레벨 C1~C3·set_status 어휘(plan §4.7·§4.8·§6.9)
from __future__ import annotations

import json

import pytest

from app import common, config, registry
from app.errors import AppError

OWNER = "tester@example.com"
PROJECT = "P1"
CK_A = "ck:aaaaaaaaaaaa"
CK_B = "ck:bbbbbbbbbbbb"
CK_C = "ck:cccccccccccc"
CK_D = "ck:dddddddddddd"
CK_E = "ck:eeeeeeeeeeee"

# 로스터 15 도메인(Settings 정본, plan §0.6).
DOMAINS = tuple(config.settings.risk_roster_domains)


# ---------------------------------------------------------------- 픽스처·삽입 도우미


@pytest.fixture
def clock():
    """now_epoch 을 고정 시계로 바꾼다. tick() 으로 시간을 밀어 '쓰기 0' 을 updated_at 으로 관찰한다."""
    state = {"t": 1000}
    previous = common.set_clock(lambda: state["t"])
    yield state
    common.set_clock(previous)


def _target(store, target_key="T1", *, level="C0", close_level="C2", project_id=PROJECT, verdict_final=None):
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, level, close_level, "
        "verdict_final, external_sync_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (target_key, OWNER, "snap", "S1", project_id, "0123456789ab", level, close_level, verdict_final, "{}", 1, 1),
    )


def _finding(
    store,
    target_key,
    finding_id,
    cluster_key,
    *,
    panel_id="PN1",
    direction="risk",
    domain="mech",
    mechanism="thermal",
    mechanism_detail="warpage",
    change_kind="dimension_tuning",
    subject_key=CK_A,
    severity="중대",
    judgement="WARNING",
    detectability="test-only",
    evidence_grade="문헌·규격",
    precedent="none",
    contested_by=(),
    contest_note="",
    claim="합성 클레임",
    raised_by=("seat-a",),
    cites=(),
    resolving_checks=(),
    names=(),
    subject_unresolved=False,
    created_at=100,
):
    fj = {
        "claim": claim,
        "warrant": "합성 워런트",
        "raised_by": list(raised_by),
        "contested_by": list(contested_by),
        "contest_note": contest_note,
        "cites": [{"ref": r, "quote": ""} for r in cites],
        "resolving_checks": [{"kind": k, "ref": r} for k, r in resolving_checks],
        "feature_snapshot": {},
        "subject": {"names": list(names)},
        "subject_unresolved": subject_unresolved,
        "trigger_condition": "",
        "owner_domain": domain,
    }
    store.execute(
        "INSERT INTO rr_findings(finding_id, claim_uid, target_key, panel_id, project_id, owner_sub, visibility, "
        "direction, domain, mechanism, mechanism_detail, change_kind, subject_key, ckeys_json, severity, sev3, "
        "judgement, detectability, evidence_grade, precedent, cluster_key, finding_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            finding_id, f"{panel_id}#{finding_id}", target_key, panel_id, PROJECT, OWNER, "private",
            direction, domain, mechanism, mechanism_detail, change_kind, subject_key,
            common.canonical_json([p for p in subject_key.split("|") if p.startswith("ck:")]),
            severity, registry.SEVERITY_ORDER.get(severity, 1), judgement, detectability,
            evidence_grade, precedent, cluster_key, common.canonical_json(fj), created_at,
        ),
    )


def _reg_row(store, target_key, cluster_key, *, status="open", judgement="OK", support=1, contested=0,
             evidence_grade="측정", subject_key=CK_A, direction="risk", merged=None, stale_json=None,
             superseded_by=None, priority=1.0):
    store.execute(
        "INSERT INTO rr_registry(target_key, cluster_key, owner_sub, visibility, merged_json, support, contested, "
        "direction, mechanism, mechanism_detail, change_kind, subject_key, severity, sev3, judgement, evidence_grade, "
        "precedent, weak_subject, priority, status, stale_json, superseded_by, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (target_key, cluster_key, OWNER, "private", common.canonical_json(merged or {}), support, contested,
         direction, "thermal", "warpage", "dimension_tuning", subject_key, "중대", 2, judgement, evidence_grade,
         "none", 0, priority, status, stale_json, superseded_by, 1),
    )


def _registry_dump(store, target_key):
    return [dict(r) for r in store.query(
        "SELECT " + registry._REGISTRY_COLUMNS + " FROM rr_registry WHERE target_key = ? ORDER BY cluster_key",
        (target_key,),
    )]


def _contrib_dump(store):
    return [dict(r) for r in store.query(
        "SELECT change_kind, mechanism, mechanism_detail, target_key, owner_sub, n_raised, n_improvement, "
        "sev_hist_json, resolving_checks_json, updated_at FROM rr_delta_contrib "
        "ORDER BY change_kind, mechanism, mechanism_detail, target_key"
    )]


def _priors_dump(store):
    return [dict(r) for r in store.query(
        "SELECT change_kind, mechanism, mechanism_detail, n_raised, n_targets, n_verified, n_dismissed, "
        "n_improvement, sev_hist_json, top_resolving_checks_json, stats_version, updated_at FROM rr_delta_priors "
        "ORDER BY change_kind, mechanism, mechanism_detail"
    )]


def _merged_of(store, target_key, cluster_key):
    row = store.query_one(
        "SELECT merged_json FROM rr_registry WHERE target_key = ? AND cluster_key = ?", (target_key, cluster_key))
    return json.loads(row["merged_json"])


def _seed_coverage(store, target_key, seats):
    """seats = [(agent_key, domain, status, panel_id)] — 로스터 행과 원장 행을 한 벌로 만든다."""
    for agent, domain, status, panel_id in seats:
        store.execute(
            "INSERT INTO rr_roster(target_key, agent_key, owner_sub, domain, relevance, rank_in_domain, "
            "ecad_dependent, frozen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (target_key, agent, OWNER, domain, 1.0, 1, 0, 1),
        )
        store.execute(
            "INSERT INTO rr_coverage(target_key, agent_key, owner_sub, domain, status, panel_id, opinion_id, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (target_key, agent, OWNER, domain, status, panel_id, f"op-{agent}" if status == "done" else None, 1),
        )


def _cov_only(store, target_key, agent, domain, status):
    """로스터에 없는 원장 행(추가 좌석) 1건."""
    store.execute(
        "INSERT INTO rr_coverage(target_key, agent_key, owner_sub, domain, status, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (target_key, agent, OWNER, domain, status, 1),
    )


def _panel(store, target_key, panel_id, panel_no, *, tier="A", status="done", engine="web", tool_mode="tools",
           parsed=1, quality=None):
    store.execute(
        "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, tier, seats_json, engine, tool_mode, status, "
        "risk_spec_parsed, quality_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (panel_id, target_key, OWNER, panel_no, tier, "[]", engine, tool_mode, status, parsed,
         common.canonical_json(quality) if quality is not None else None, 1),
    )


def _tier_a_panels(store, target_key, n=3, prefix="PA"):
    """Tier A done 패널 n건(id 는 rr_panels 전역 PK 라 타깃이 여럿이면 prefix 를 나눈다)."""
    for i in range(n):
        _panel(store, target_key, f"{prefix}{i + 1}", i + 1)


def _base_seats(panel_id="PA1", status="done"):
    """15 도메인 × 1석 — C1 도메인 조건을 채우는 최소 로스터."""
    return [(f"exp-{d}", d, status, panel_id) for d in DOMAINS]


# ================================================================ §4.7.1 병합 — support·멱등


def test_merge_support_counts_panels_not_findings(risk_store, clock):
    """support = 제기 패널 수 — 같은 패널의 중복 finding 은 1로 센다(plan §4.7.1)."""
    _target(risk_store)
    _finding(risk_store, "T1", "F1", "cluster000001", panel_id="PN1")
    _finding(risk_store, "T1", "F2", "cluster000001", panel_id="PN1")
    out = registry.merge(risk_store, "T1")
    assert out["findings"] == 2 and out["clusters"] == 1 and out["inserted"] == 1
    row = risk_store.query_one(
        "SELECT support, contested FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
        ("T1", "cluster000001"))
    assert row["support"] == 1

    # 다른 패널이 같은 클러스터를 다시 제기하면 support 가 +1 이다.
    _finding(risk_store, "T1", "F3", "cluster000001", panel_id="PN2")
    clock["t"] = 2000
    out2 = registry.merge(risk_store, "T1")
    assert out2["updated"] == 1 and out2["unchanged"] == 0
    row = risk_store.query_one(
        "SELECT support, updated_at FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
        ("T1", "cluster000001"))
    assert row["support"] == 2 and row["updated_at"] == 2000


def test_merge_is_idempotent_no_write_when_values_equal(risk_store, clock):
    """같은 finding 집합으로 2회 병합하면 등록부·기여·사전 값이 바이트 동일하고 쓰기가 0이다(plan §9.4 (12))."""
    _target(risk_store)
    _finding(risk_store, "T1", "F1", "cluster000001", panel_id="PN1",
             resolving_checks=(("tool", "compute_warpage"),))
    _finding(risk_store, "T1", "F2", "cluster000002", panel_id="PN2", direction="improvement",
             subject_key=CK_B, severity="경미", judgement="OK")
    first = registry.merge(risk_store, "T1")
    assert first["inserted"] == 2 and first["updated"] == 0 and first["unchanged"] == 0
    assert first["priors_written"] >= 1

    reg_before = _registry_dump(risk_store, "T1")
    contrib_before = _contrib_dump(risk_store)
    priors_before = _priors_dump(risk_store)
    assert all(r["updated_at"] == 1000 for r in reg_before)

    clock["t"] = 5000
    second = registry.merge(risk_store, "T1")
    assert second["inserted"] == 0 and second["updated"] == 0 and second["unchanged"] == 2
    assert second["priors_written"] == 0
    assert _registry_dump(risk_store, "T1") == reg_before
    assert _contrib_dump(risk_store) == contrib_before
    assert _priors_dump(risk_store) == priors_before
    # 쓰기가 없었으므로 updated_at 이 옛 시각 그대로다.
    assert all(r["updated_at"] == 1000 for r in _registry_dump(risk_store, "T1"))
    assert all(r["updated_at"] == 1000 for r in _contrib_dump(risk_store))
    assert all(r["updated_at"] == 1000 for r in _priors_dump(risk_store))


def test_merge_splits_risk_and_improvement_rows(risk_store, clock):
    """같은 cluster_key 에 risk 와 improvement 가 섞이면 두 행으로 나뉘고 improvement 행에 접미가 붙는다(plan §4.7.1)."""
    _target(risk_store)
    _finding(risk_store, "T1", "F1", "cluster000001", panel_id="PN1", direction="risk")
    _finding(risk_store, "T1", "G1", "cluster000001", panel_id="PN1", direction="improvement")
    out = registry.merge(risk_store, "T1")
    assert out["clusters"] == 2
    keys = [r["cluster_key"] for r in _registry_dump(risk_store, "T1")]
    assert keys == ["cluster000001", "cluster000001" + registry.IMPROVEMENT_SUFFIX]
    imp = risk_store.query_one(
        "SELECT direction FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
        ("T1", "cluster000001" + registry.IMPROVEMENT_SUFFIX))
    assert imp["direction"] == "improvement"
    # 저장 키에만 접미가 붙고 원래 키는 merged_json 에 남는다.
    merged = _merged_of(risk_store, "T1", "cluster000001" + registry.IMPROVEMENT_SUFFIX)
    assert merged["cluster_key"] == "cluster000001"
    assert registry.strip_improvement_suffix("cluster000001" + registry.IMPROVEMENT_SUFFIX) == "cluster000001"


def test_merge_aggregates_worst_values_and_priority(risk_store, clock):
    """severity 최대·judgement 최악·evidence_grade 최고·precedent 최빈(동률 out_of_range)·priority 식(plan §4.7.1)."""
    _target(risk_store)
    _finding(risk_store, "T1", "F1", "cluster000001", panel_id="PN1", severity="경미", judgement="OK",
             evidence_grade="경험칙", precedent="in_range", detectability="sim-detectable")
    _finding(risk_store, "T1", "F2", "cluster000001", panel_id="PN2", severity="치명", judgement="WARNING",
             evidence_grade="측정", precedent="out_of_range", detectability="field-only", claim="치명 클레임")
    registry.merge(risk_store, "T1")
    row = risk_store.query_one(
        "SELECT severity, sev3, judgement, evidence_grade, precedent, priority, support FROM rr_registry "
        "WHERE target_key = ? AND cluster_key = ?", ("T1", "cluster000001"))
    assert (row["severity"], row["sev3"]) == ("치명", 3)
    assert row["judgement"] == "WARNING"
    assert row["evidence_grade"] == "측정"
    # in_range 1건 · out_of_range 1건 동률 → out_of_range 우선.
    assert row["precedent"] == "out_of_range"
    # priority = sev3(3) × w_det(field-only 3.0) × w_grade(측정 1.0) = 9.0, contested 없음.
    assert row["priority"] == pytest.approx(9.0)
    # 대표 finding 은 evidence_grade 최고 건이다.
    assert _merged_of(risk_store, "T1", "cluster000001")["claim"] == "치명 클레임"
    assert row["support"] == 2


def test_merge_skips_contrib_for_excluded_change_kinds(risk_store, clock):
    """change_kind ∈ {discretization, none} 은 기여 행을 만들지 않는다(plan §4.7.1 마지막 줄)."""
    _target(risk_store)
    _finding(risk_store, "T1", "F1", "cluster000001", change_kind="discretization")
    _finding(risk_store, "T1", "F2", "cluster000002", change_kind="none", subject_key=CK_B)
    registry.merge(risk_store, "T1")
    assert _contrib_dump(risk_store) == []
    assert _priors_dump(risk_store) == []


def test_merge_priors_are_recomputed_not_incremented(risk_store, clock):
    """사전은 기여 행의 합으로 재합산한다 — 두 타깃 기여 후 n_raised 합·n_targets 2(plan §4.7.1 증분 += 없음)."""
    _target(risk_store, "T1")
    _target(risk_store, "T2")
    _finding(risk_store, "T1", "F1", "cluster000001", panel_id="PN1")
    _finding(risk_store, "T2", "F2", "cluster000001", panel_id="PN2")
    registry.merge(risk_store, "T1")
    registry.merge(risk_store, "T2")
    priors = _priors_dump(risk_store)
    assert len(priors) == 1
    assert priors[0]["n_raised"] == 2 and priors[0]["n_targets"] == 2
    assert priors[0]["stats_version"] == registry.STATS_VERSION
    # 같은 타깃을 다시 병합해도 합이 그대로다(중복 가산 없음).
    registry.merge(risk_store, "T1")
    assert _priors_dump(risk_store) == priors


def test_merge_writes_verdict_candidate_to_target(risk_store, clock):
    _target(risk_store)
    _finding(risk_store, "T1", "F1", "cluster000001", judgement="FAIL", evidence_grade="측정")
    out = registry.merge(risk_store, "T1")
    assert out["verdict_candidate"] == "no-go"
    row = risk_store.query_one("SELECT verdict_candidate FROM rr_targets WHERE target_key = ?", ("T1",))
    assert row["verdict_candidate"] == "no-go"


# ================================================================ dissent(반대석 기각·소수의견) 보존


def test_contested_finding_is_preserved_not_dropped(risk_store, clock):
    """반대석이 기각을 요구해도 클러스터는 남고 contest_notes 로 이의가 보존된다(다수결로 지우지 않는다)."""
    _target(risk_store)
    _finding(risk_store, "T1", "F1", "cluster000001", panel_id="PN1", raised_by=("seat-a",))
    _finding(risk_store, "T1", "F2", "cluster000001", panel_id="PN2", raised_by=("seat-b",),
             contested_by=(registry.ADVERSARY_KEY,), contest_note="근거 수치가 도구 결과와 다르다")
    registry.merge(risk_store, "T1")
    row = risk_store.query_one(
        "SELECT support, contested, priority FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
        ("T1", "cluster000001"))
    assert row["support"] == 2 and row["contested"] == 1
    # contested 는 priority 를 ×0.8 로 낮추기만 한다 — sev3(2) × w_det(test-only 2.0) × w_grade(문헌·규격 0.8) × 0.8.
    assert row["priority"] == pytest.approx(2 * 2.0 * 0.8 * 0.8)

    merged = _merged_of(risk_store, "T1", "cluster000001")
    assert merged["member_ids"] == ["F1", "F2"]
    assert merged["raised_by"] == ["seat-a", "seat-b"]
    assert merged["contest_notes"] == [
        {"finding_id": "F2", "by": [registry.ADVERSARY_KEY], "note": "근거 수치가 도구 결과와 다르다"}
    ]
    # 재병합해도 이의 기록이 그대로다.
    registry.merge(risk_store, "T1")
    assert _merged_of(risk_store, "T1", "cluster000001")["contest_notes"] == merged["contest_notes"]


def test_fully_contested_cluster_survives_merge(risk_store, clock):
    """유일한 finding 이 기각 요구를 받아도 행은 지워지지 않는다(contested == support)."""
    _target(risk_store)
    _finding(risk_store, "T1", "F1", "cluster000001", contested_by=(registry.ADVERSARY_KEY,),
             contest_note="기각 요구")
    registry.merge(risk_store, "T1")
    row = risk_store.query_one(
        "SELECT support, contested, status FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
        ("T1", "cluster000001"))
    assert (row["support"], row["contested"], row["status"]) == (1, 1, "open")


def test_non_adversary_contest_is_noted_but_not_counted(risk_store, clock):
    """지정 반대석이 아닌 좌석의 이의는 contested 수에 들지 않지만 contest_notes 에는 남는다(plan §4.7.1)."""
    _target(risk_store)
    _finding(risk_store, "T1", "F1", "cluster000001", contested_by=("seat-rel",), contest_note="이견")
    registry.merge(risk_store, "T1")
    row = risk_store.query_one(
        "SELECT contested FROM rr_registry WHERE target_key = ? AND cluster_key = ?", ("T1", "cluster000001"))
    assert row["contested"] == 0
    assert _merged_of(risk_store, "T1", "cluster000001")["contest_notes"][0]["by"] == ["seat-rel"]


# ================================================================ §4.7.2 verdict 후보


def test_verdict_no_clusters_is_undetermined(risk_store):
    _target(risk_store)
    out = registry.verdict_candidate(risk_store, "T1")
    assert out["verdict"] == "undetermined"
    assert out["counts"]["clusters"] == 0
    assert out["reasons"] == ["클러스터 0건"]


def test_verdict_no_go_when_uncontested_fail(risk_store):
    _target(risk_store)
    _reg_row(risk_store, "T1", "c1", judgement="FAIL", support=2, contested=1)
    _reg_row(risk_store, "T1", "c2", judgement="OK")
    out = registry.verdict_candidate(risk_store, "T1")
    assert out["verdict"] == "no-go"
    assert out["counts"]["FAIL"] == 1


def test_verdict_fail_fully_contested_is_undetermined(risk_store):
    """contested < support 가 아니면 no-go 가 아니고 마지막 갈래(전부 반대석 기각)로 떨어진다."""
    _target(risk_store)
    _reg_row(risk_store, "T1", "c1", judgement="FAIL", support=2, contested=2)
    _reg_row(risk_store, "T1", "c2", judgement="OK")
    out = registry.verdict_candidate(risk_store, "T1")
    assert out["verdict"] == "undetermined"
    assert out["reasons"] == ["FAIL 클러스터가 전부 반대석 기각 상태"]


def test_verdict_conditional_and_go(risk_store):
    _target(risk_store, "T1")
    _reg_row(risk_store, "T1", "c1", judgement="WARNING")
    _reg_row(risk_store, "T1", "c2", judgement="OK")
    assert registry.verdict_candidate(risk_store, "T1")["verdict"] == "conditional"

    _target(risk_store, "T2")
    _reg_row(risk_store, "T2", "c1", judgement="OK")
    _reg_row(risk_store, "T2", "c2", judgement="OK")
    go = registry.verdict_candidate(risk_store, "T2")
    assert go["verdict"] == "go" and go["reasons"] == ["모든 클러스터 OK"]


def test_verdict_undetermined_wins_over_fail(risk_store):
    """근거 등급이 전부 경험칙이거나 undetermined 과반이면 다른 판정보다 우선한다(plan §4.7.2)."""
    _target(risk_store, "T1")
    _reg_row(risk_store, "T1", "c1", judgement="FAIL", evidence_grade="경험칙")
    _reg_row(risk_store, "T1", "c2", judgement="OK", evidence_grade="경험칙")
    heuristic = registry.verdict_candidate(risk_store, "T1")
    assert heuristic["verdict"] == "undetermined"
    assert "근거 등급이 전부 경험칙" in heuristic["reasons"]

    _target(risk_store, "T2")
    _reg_row(risk_store, "T2", "c1", judgement="undetermined")
    _reg_row(risk_store, "T2", "c2", judgement="undetermined")
    _reg_row(risk_store, "T2", "c3", judgement="FAIL")
    majority = registry.verdict_candidate(risk_store, "T2")
    assert majority["verdict"] == "undetermined"
    assert "undetermined 클러스터 과반" in majority["reasons"]


def test_verdict_counts_only_open_and_verified(risk_store):
    """dismissed·mitigated·superseded 행은 집계에서 빠진다(plan §4.7.2 표 머리말)."""
    _target(risk_store)
    _reg_row(risk_store, "T1", "c1", judgement="FAIL", status="dismissed")
    _reg_row(risk_store, "T1", "c2", judgement="WARNING", status="superseded")
    _reg_row(risk_store, "T1", "c3", judgement="FAIL", status="mitigated")
    _reg_row(risk_store, "T1", "c4", judgement="OK", status="verified")
    out = registry.verdict_candidate(risk_store, "T1")
    assert out["counts"]["clusters"] == 1
    assert out["verdict"] == "go"


# ================================================================ set_status 허용값


@pytest.mark.parametrize("status,label_needed", [("verified", True), ("dismissed", True), ("mitigated", False)])
def test_set_status_allowed_values(risk_store, clock, status, label_needed):
    """사람 전이는 status 5열 + 로그 1행을 남긴다(plan §4.7.1·§0.9 P3-15)."""
    _target(risk_store)
    _reg_row(risk_store, "T1", "c1")
    out = registry.set_status(risk_store, "c1", status, owner_sub=OWNER, evidence_ref="[rpt:12]", note="확인",
                              actor="reviewer@example.com")
    assert out["cluster_key"] == "c1" and out["status"] == status
    assert (out["updated"], out["label_needed"]) == (1, label_needed)
    assert out["status_source"] == "human" and out["decided_by"] == "reviewer@example.com"
    assert out["decided_at"] == 1000 and out["status_log_seq"] == 1
    row = risk_store.query_one(
        "SELECT status, status_source, status_decided_by, status_decided_at, status_note, status_basis_json,"
        " verified_by_json, updated_at FROM rr_registry WHERE target_key = ? AND cluster_key = ?", ("T1", "c1"))
    assert row["status"] == status and row["updated_at"] == 1000
    assert row["status_source"] == "human" and row["status_decided_by"] == "reviewer@example.com"
    assert row["status_decided_at"] == 1000
    basis = json.loads(row["status_basis_json"])
    assert basis["evidence_ref"] == "[rpt:12]" and "support_at_decision" in basis
    assert json.loads(row["verified_by_json"]) == [
        {"status": status, "by": "reviewer@example.com", "at": 1000, "evidence_ref": "[rpt:12]", "note": "확인"}
    ]
    log = risk_store.query_one(
        "SELECT seq, from_status, to_status, source, decided_by, applied FROM rr_registry_status_log"
        " WHERE target_key = 'T1' AND cluster_key = 'c1'")
    assert (log["seq"], log["from_status"], log["to_status"]) == (1, "open", status)
    assert (log["source"], log["decided_by"], log["applied"]) == ("human", "reviewer@example.com", 1)


def test_set_status_requires_a_basis(risk_store):
    """verified·dismissed·open 은 evidence_ref 없이, mitigated 는 note 없이 422 다."""
    _target(risk_store)
    _reg_row(risk_store, "T1", "c1")
    for status, code in (("verified", "evidence_required"), ("dismissed", "evidence_required"),
                         ("open", "evidence_required"), ("mitigated", "note_required")):
        with pytest.raises(AppError) as exc:
            registry.set_status(risk_store, "c1", status, owner_sub=OWNER)
        assert (exc.value.code, exc.value.http_status) == (code, 422)
    assert risk_store.query_one(
        "SELECT status FROM rr_registry WHERE cluster_key = ?", ("c1",))["status"] == "open"
    assert risk_store.query("SELECT id FROM rr_registry_status_log") == []


def test_set_status_can_reopen_a_row_with_a_basis(risk_store, clock):
    """open 되돌리기는 어휘 안이고 근거가 있으면 통과한다 — 로그 seq 는 계속 오른다."""
    _target(risk_store)
    _reg_row(risk_store, "T1", "c1")
    registry.set_status(risk_store, "c1", "dismissed", owner_sub=OWNER, evidence_ref="[rpt:12]")
    clock["t"] = 1100
    out = registry.set_status(risk_store, "c1", "open", owner_sub=OWNER, evidence_ref="[rpt:13]")
    assert out["status"] == "open" and out["status_log_seq"] == 2
    assert risk_store.query_one(
        "SELECT status, status_source FROM rr_registry WHERE cluster_key = 'c1'")["status"] == "open"


@pytest.mark.parametrize("status", ["superseded", "VERIFIED", "", "resolved"])
def test_set_status_rejects_vocabulary_outside(risk_store, status):
    _target(risk_store)
    _reg_row(risk_store, "T1", "c1")
    with pytest.raises(AppError) as exc:
        registry.set_status(risk_store, "c1", status, owner_sub=OWNER, evidence_ref="[rpt:12]")
    assert exc.value.code == "E100" and exc.value.http_status == 422
    assert risk_store.query_one(
        "SELECT status FROM rr_registry WHERE cluster_key = ?", ("c1",))["status"] == "open"


def test_set_status_unknown_cluster_or_owner_is_404(risk_store):
    _target(risk_store)
    _reg_row(risk_store, "T1", "c1")
    with pytest.raises(AppError) as missing:
        registry.set_status(risk_store, "nope", "verified", owner_sub=OWNER, evidence_ref="[rpt:12]")
    assert missing.value.code == "E404" and missing.value.http_status == 404
    with pytest.raises(AppError) as other:
        registry.set_status(risk_store, "c1", "verified", owner_sub="someone@else.com", evidence_ref="[rpt:12]")
    assert other.value.code == "E404"


def test_set_status_target_key_narrows_and_log_appends(risk_store, clock):
    """target_key 를 주면 그 타깃 행만 바뀌고, 상태 전이 기록은 누적된다."""
    _target(risk_store, "T1")
    _target(risk_store, "T2")
    _reg_row(risk_store, "T1", "c1")
    _reg_row(risk_store, "T2", "c1")
    assert registry.set_status(risk_store, "c1", "verified", owner_sub=OWNER, target_key="T1",
                               evidence_ref="[rpt:12]")["updated"] == 1
    assert risk_store.query_one(
        "SELECT status FROM rr_registry WHERE target_key = 'T2' AND cluster_key = 'c1'")["status"] == "open"

    clock["t"] = 1100
    assert registry.set_status(risk_store, "c1", "mitigated", owner_sub=OWNER, note="치구로 대체")["updated"] == 2
    log = json.loads(risk_store.query_one(
        "SELECT verified_by_json FROM rr_registry WHERE target_key = 'T1' AND cluster_key = 'c1'")["verified_by_json"])
    assert [e["status"] for e in log] == ["verified", "mitigated"]
    assert [e["at"] for e in log] == [1000, 1100]
    # 로그 seq 는 (target_key, cluster_key) 안에서 1부터 오른다.
    assert [r["seq"] for r in risk_store.query(
        "SELECT seq FROM rr_registry_status_log WHERE target_key = 'T1' AND cluster_key = 'c1' ORDER BY seq")] == [1, 2]
    # actor 를 안 주면 owner_sub 가 기록된다.
    assert log[1]["by"] == OWNER


# ================================================================ §4.8 무효화(stale · superseded · unraised)


def _invalidation_fixture(risk_store):
    """T1 의 다섯 클러스터와 T2 의 재제기 클러스터를 깔아 둔다."""
    _target(risk_store, "T1")
    _target(risk_store, "T2")
    _reg_row(risk_store, "T1", "c1", subject_key=CK_A)                      # 주체 변경 + T2 재제기
    _reg_row(risk_store, "T1", "c2", subject_key=f"{CK_B}|{CK_C}")          # 계면 한쪽 변경
    _reg_row(risk_store, "T1", "c3", subject_key="dim:utg_gap",             # cites 의 ckey 변경
             merged={"cites": [{"ref": "[p:0123456789ab]", "ckey": CK_D}]})
    _reg_row(risk_store, "T1", "c4", subject_key=CK_E)                      # 미변경
    _reg_row(risk_store, "T1", "c5", subject_key=CK_E, status="verified")   # T2 재제기지만 사람이 확정
    _reg_row(risk_store, "T2", "c1")
    _reg_row(risk_store, "T2", "c5")


def test_invalidate_marks_stale_and_superseded(risk_store, clock):
    """변경 주체를 인용한 클러스터만 stale, 재제기된 클러스터는 superseded(plan §4.8 3·6)."""
    _invalidation_fixture(risk_store)
    out = registry.invalidate(risk_store, "T1", "T2", [CK_A, CK_C, CK_D])
    assert out["changed_ckeys"] == 3
    assert out["stale"] == 3 and out["superseded"] == 1 and out["unraised"] == 0

    rows = {r["cluster_key"]: r for r in _registry_dump(risk_store, "T1")}
    assert json.loads(rows["c1"]["stale_json"]) == {"T2": {"stale": True}}
    assert json.loads(rows["c2"]["stale_json"])["T2"]["stale"] is True
    assert json.loads(rows["c3"]["stale_json"])["T2"]["stale"] is True
    # 미변경 클러스터는 표기가 붙지 않는다(행 자체를 건드리지 않는다).
    assert rows["c4"]["stale_json"] is None and rows["c4"]["updated_at"] == 1
    # 재제기 → superseded, 참조는 T′#<저장 키>.
    assert rows["c1"]["status"] == "superseded" and rows["c1"]["superseded_by"] == "T2#c1"
    # 사람이 확정한 행은 superseded 로 덮이지 않는다.
    assert rows["c5"]["status"] == "verified" and rows["c5"]["superseded_by"] is None
    # 행은 하나도 지워지지 않는다.
    assert set(rows) == {"c1", "c2", "c3", "c4", "c5"}


def test_invalidate_is_idempotent(risk_store, clock):
    _invalidation_fixture(risk_store)
    registry.invalidate(risk_store, "T1", "T2", [CK_A, CK_C, CK_D])
    before = _registry_dump(risk_store, "T1")
    clock["t"] = 9000
    again = registry.invalidate(risk_store, "T1", "T2", [CK_A, CK_C, CK_D])
    assert (again["stale"], again["superseded"], again["unraised"]) == (0, 0, 0)
    assert _registry_dump(risk_store, "T1") == before


def test_invalidate_mark_unraised(risk_store, clock):
    """T′ 에서 다시 제기되지 않은 클러스터에 unraised 를 남긴다(plan §4.8 6)."""
    _invalidation_fixture(risk_store)
    registry.invalidate(risk_store, "T1", "T2", [CK_A])
    out = registry.invalidate(risk_store, "T1", "T2", [CK_A], mark_unraised=True)
    assert out["unraised"] == 3
    rows = {r["cluster_key"]: r for r in _registry_dump(risk_store, "T1")}
    for key in ("c2", "c3", "c4"):
        assert json.loads(rows[key]["stale_json"])["T2"]["unraised"] is True
    # 재제기된 c1·확정된 c5 는 unraised 대상이 아니다.
    assert "unraised" not in json.loads(rows["c1"]["stale_json"])["T2"]
    assert rows["c5"]["stale_json"] is None
    # stale 표기는 그대로 살아 있다.
    assert json.loads(rows["c1"]["stale_json"])["T2"]["stale"] is True


def test_invalidate_resolves_ckeys_on_both_sides(risk_store, clock):
    """변경 ckey 와 클러스터 주체 모두 resolve_ckey 를 거친 유효 ckey 로 비교한다(plan §4.8 2)."""
    _target(risk_store, "T1")
    _target(risk_store, "T2")
    _reg_row(risk_store, "T1", "c1", subject_key=CK_A)
    merged_into = {"ck:999999999999": CK_A}

    plain = registry.invalidate(risk_store, "T1", "T2", ["ck:999999999999"])
    assert plain["stale"] == 0

    resolved = registry.invalidate(
        risk_store, "T1", "T2", ["ck:999999999999"], resolve_ckey=lambda ck: merged_into.get(ck, ck))
    assert resolved["stale"] == 1


def test_invalidate_supersedes_improvement_row_by_base_key(risk_store, clock):
    """improvement 접미가 붙은 행도 base 키로 재제기를 판정한다."""
    _target(risk_store, "T1")
    _target(risk_store, "T2")
    imp = "c1" + registry.IMPROVEMENT_SUFFIX
    _reg_row(risk_store, "T1", imp, direction="improvement")
    _reg_row(risk_store, "T2", "c1")
    out = registry.invalidate(risk_store, "T1", "T2", [])
    assert out["superseded"] == 1
    row = risk_store.query_one(
        "SELECT status, superseded_by FROM rr_registry WHERE target_key = 'T1' AND cluster_key = ?", (imp,))
    assert row["status"] == "superseded" and row["superseded_by"] == f"T2#{imp}"


# ================================================================ §6.9 완결 레벨 C0~C3


def test_close_level_c1_boundary_tier_a_and_domains(risk_store, clock):
    """C1 = 15 도메인 종결 ≥1 AND Tier A 패널 3건 done(plan §6.9)."""
    _target(risk_store, "T1")
    _seed_coverage(risk_store, "T1", _base_seats())
    _tier_a_panels(risk_store, "T1", n=2)
    two = registry.close_level(risk_store, "T1", persist=False)
    assert two["c1"] is False and two["level"] == "C0"
    assert two["detail"]["tier_a_done"] == 2

    _panel(risk_store, "T1", "PA3", 3)
    three = registry.close_level(risk_store, "T1", persist=False)
    assert three["c1"] is True and three["detail"]["tier_a_done"] == 3


def test_close_level_c1_needs_every_domain(risk_store, clock):
    """한 도메인이라도 종결 좌석이 없으면 C1 미달이다."""
    _target(risk_store, "T1")
    seats = [(agent, domain, "pending" if domain == "material" else "done", "PA1")
             for agent, domain, _, _ in _base_seats()]
    _seed_coverage(risk_store, "T1", seats)
    _tier_a_panels(risk_store, "T1")
    out = registry.close_level(risk_store, "T1", persist=False)
    assert out["c1"] is False and out["level"] == "C0"
    assert out["detail"]["domains_terminal"]["material"] == 0
    # 미착석 배지 = 비종결 좌석 수.
    assert out["unseated_n"] == 1


def test_close_level_c2_strong_ratio_boundary(risk_store, clock):
    """strong 비율 done/(done+done_weak) 가 0.7 이면 통과, 0.65 면 미달(plan §0.6 완결 행)."""
    _target(risk_store, "T1")
    seats = [(f"exp-{d}", d, "done", "PA1") for d in DOMAINS if d != "xd"]
    seats += [(f"exp-xd-{i}", "xd", "done_weak", "PA1") for i in range(6)]
    _seed_coverage(risk_store, "T1", seats)
    _tier_a_panels(risk_store, "T1")
    ok = registry.close_level(risk_store, "T1", persist=False)
    assert ok["detail"]["strong"] == 14 and ok["detail"]["done_weak"] == 6
    assert ok["detail"]["strong_ratio"] == pytest.approx(0.7)
    assert ok["c1"] is True and ok["c2"] is True

    # 좌석 하나를 done_weak 로 내리면 13/20 = 0.65 로 미달한다(도메인 종결은 유지되어 C1 은 그대로).
    risk_store.execute("UPDATE rr_coverage SET status = 'done_weak' WHERE target_key = 'T1' AND agent_key = 'exp-sim'")
    low = registry.close_level(risk_store, "T1", persist=False)
    assert low["detail"]["strong_ratio"] == pytest.approx(0.65)
    assert low["c1"] is True and low["c2"] is False and low["level"] == "C1"


def test_close_level_c2_excludes_mcp_evidence_only_seats(risk_store, clock):
    """MCP evidence_only 패널 좌석은 strong 비율 분모·분자에서 빠진다(plan §6.9 C2·§6.11)."""
    _target(risk_store, "T1")
    seats = [(f"exp-{d}", d, "done", "PA1") for d in DOMAINS if d != "xd"]
    seats += [(f"exp-xd-{i}", "xd", "done_weak", "PA1") for i in range(4)]
    seats += [(f"exp-mcp-{i}", "xd", "done_weak", "PM1") for i in range(3)]
    _seed_coverage(risk_store, "T1", seats)
    _tier_a_panels(risk_store, "T1")
    _panel(risk_store, "T1", "PM1", 4, tier="B", engine="mcp", tool_mode="evidence_only")
    out = registry.close_level(risk_store, "T1", persist=False)
    # 웹 좌석만 세어 14/(14+4) ≈ 0.778 — MCP 3석을 세면 14/21 ≈ 0.667 로 미달했을 값이다.
    assert out["detail"]["strong"] == 14 and out["detail"]["done_weak"] == 4
    assert out["detail"]["strong_ratio"] == pytest.approx(0.7778, abs=1e-4)
    assert out["c2"] is True


def test_close_level_c2_blocked_by_unresolved_spec_parse_failure(risk_store, clock):
    """미해결 spec_parse_failed 패널이 있으면 C2 미달, '제외' 표기 후 통과(plan §6.9)."""
    _target(risk_store, "T1")
    _seed_coverage(risk_store, "T1", _base_seats())
    _tier_a_panels(risk_store, "T1")
    _panel(risk_store, "T1", "PB1", 4, tier="B", parsed=0)
    blocked = registry.close_level(risk_store, "T1", persist=False)
    assert blocked["detail"]["spec_parse_failed"] == 1
    assert blocked["c1"] is True and blocked["c2"] is False

    risk_store.execute(
        "UPDATE rr_panels SET quality_json = ? WHERE id = 'PB1'",
        (common.canonical_json({"spec_excluded": True}),))
    freed = registry.close_level(risk_store, "T1", persist=False)
    assert freed["detail"]["spec_parse_failed"] == 0 and freed["c2"] is True

    # 아직 끝나지 않은(running) 패널의 미파싱은 실패로 세지 않는다.
    _panel(risk_store, "T1", "PB2", 5, tier="B", status="running", parsed=0)
    assert registry.close_level(risk_store, "T1", persist=False)["detail"]["spec_parse_failed"] == 0


def test_close_level_c2_requires_contested_marking(risk_store, clock):
    """반대석 기각 finding 이 등록부 contested 로 표기되기 전에는 C2 미달이다(plan §6.9 C2)."""
    _target(risk_store, "T1")
    _seed_coverage(risk_store, "T1", _base_seats())
    _tier_a_panels(risk_store, "T1")
    _finding(risk_store, "T1", "F1", "cluster000001", contested_by=(registry.ADVERSARY_KEY,), contest_note="이의")
    before = registry.close_level(risk_store, "T1", persist=False)
    assert before["detail"]["contested_marked"] is False and before["c2"] is False

    registry.merge(risk_store, "T1")
    after = registry.close_level(risk_store, "T1", persist=False)
    assert after["detail"]["contested_marked"] is True and after["c2"] is True


def test_close_level_c2_depth_rule_per_domain(risk_store, clock):
    """도메인별 종결 ≥ max(3, ceil(0.3·|d|)) — 좌석 10인 도메인은 3석이 하한이다(plan §6.9 C2)."""
    _target(risk_store, "T1")
    seats = [(f"exp-{d}", d, "done", "PA1") for d in DOMAINS if d != "xd"]
    seats += [(f"exp-xd-{i}", "xd", "done" if i < 2 else "pending", "PA1") for i in range(10)]
    _seed_coverage(risk_store, "T1", seats)
    _tier_a_panels(risk_store, "T1")
    short = registry.close_level(risk_store, "T1", persist=False)
    assert short["detail"]["depth"]["xd"] == {"need": 3, "have": 2, "roster": 10, "deferred": 0}
    assert short["c1"] is True and short["c2"] is False

    risk_store.execute("UPDATE rr_coverage SET status = 'done' WHERE target_key = 'T1' AND agent_key = 'exp-xd-2'")
    ok = registry.close_level(risk_store, "T1", persist=False)
    assert ok["detail"]["depth"]["xd"]["have"] == 3 and ok["c2"] is True
    # 비종결 좌석이 남아 있으므로 C3 는 아니다.
    assert ok["c3"] is False and ok["unseated_n"] == 7


def test_close_level_c2_closed_depends_on_close_level_setting(risk_store, clock):
    """기본 마감이 C2 면 'C2(closed)', C3 면 'C2' 로 남아 Tier C 를 잇는다(plan §6.9)."""
    _target(risk_store, "T1", close_level="C2")
    _target(risk_store, "T2", close_level="C3")
    for key in ("T1", "T2"):
        panel = f"{key}-PA1"
        seats = [(f"exp-{d}", d, "done", panel) for d in DOMAINS if d != "xd"]
        seats += [(f"exp-xd-{i}", "xd", "done" if i < 3 else "pending", panel) for i in range(10)]
        _seed_coverage(risk_store, key, seats)
        _tier_a_panels(risk_store, key, prefix=f"{key}-PA")
    closed = registry.close_level(risk_store, "T1", persist=False)
    open_for_c = registry.close_level(risk_store, "T2", persist=False)
    assert closed["c2"] is True and closed["c3"] is False and closed["level"] == "C2(closed)"
    assert open_for_c["level"] == "C2" and open_for_c["close_level"] == "C3"


def test_close_level_c3_skipped_ratio_boundary(risk_store, clock):
    """C3 = 전원 종결 AND skipped ≤5% — 20석 중 1건(0.05)은 통과, 19석 중 1건(0.0526)은 미달."""
    _target(risk_store, "T1")
    seats = [(f"exp-{d}", d, "done", "PA1") for d in DOMAINS if d != "xd"]
    seats += [(f"exp-xd-{i}", "xd", "done", "PA1") for i in range(5)]
    seats += [("exp-xd-9", "xd", "skipped", None)]
    _seed_coverage(risk_store, "T1", seats)
    _tier_a_panels(risk_store, "T1")
    ok = registry.close_level(risk_store, "T1", persist=False)
    assert ok["roster_size"] == 20 and ok["detail"]["skipped"] == 1
    assert ok["detail"]["skipped_ratio"] == pytest.approx(0.05)
    assert ok["c3"] is True and ok["level"] == "C3"

    # 좌석 하나를 빼면 1/19 ≈ 0.0526 > 0.05 로 미달한다.
    risk_store.execute("DELETE FROM rr_roster WHERE target_key = 'T1' AND agent_key = 'exp-xd-4'")
    risk_store.execute("DELETE FROM rr_coverage WHERE target_key = 'T1' AND agent_key = 'exp-xd-4'")
    over = registry.close_level(risk_store, "T1", persist=False)
    assert over["detail"]["skipped_ratio"] == pytest.approx(0.0526, abs=1e-4)
    assert over["c2"] is True and over["c3"] is False and over["level"] == "C2(closed)"


def test_close_level_c3_blocked_by_non_terminal_seat(risk_store, clock):
    """failed 좌석은 종결이 아니므로 C3 를 막는다(plan §6.8.2 비종결 · §6.9 C3)."""
    _target(risk_store, "T1")
    seats = [(f"exp-{d}", d, "done", "PA1") for d in DOMAINS if d != "xd"]
    seats += [(f"exp-xd-{i}", "xd", "done", "PA1") for i in range(5)]
    seats += [("exp-xd-9", "xd", "failed", None)]
    _seed_coverage(risk_store, "T1", seats)
    _tier_a_panels(risk_store, "T1")
    out = registry.close_level(risk_store, "T1", persist=False)
    assert out["detail"]["failed"] == 1 and out["c3"] is False
    assert out["unseated_n"] == 1 and out["level"] == "C2(closed)"
    # 회계 불변식 — 상태별 카운트 합 = roster_size(plan §6.8.3 1).
    assert sum(out["status_counts"].values()) == out["roster_size"] == 20


def test_close_level_deferred_seats_do_not_block_c3(risk_store, clock):
    """deferred 는 C3 분모에서 빠지고 도메인 깊이 계산에서도 제외된다(plan §6.9)."""
    _target(risk_store, "T1")
    seats = [(f"exp-{d}", d, "done", "PA1") for d in DOMAINS]
    seats += [(f"exp-pcb-{i}", "pcb", "deferred", None) for i in range(4)]
    _seed_coverage(risk_store, "T1", seats)
    _tier_a_panels(risk_store, "T1")
    out = registry.close_level(risk_store, "T1", persist=False)
    assert out["status_counts"]["deferred"] == 4
    assert out["detail"]["depth"]["pcb"] == {"need": 1, "have": 1, "roster": 5, "deferred": 4}
    assert out["c3"] is True and out["level"] == "C3"


def test_close_level_is_monotonic_and_persists(risk_store, clock):
    """레벨은 단조 증가만 하고 persist=True 일 때만 rr_targets 에 반영된다(plan §6.9)."""
    _target(risk_store, "T1")
    _seed_coverage(risk_store, "T1", _base_seats())
    _tier_a_panels(risk_store, "T1")

    dry = registry.close_level(risk_store, "T1", persist=False)
    assert dry["level"] == "C3" and dry["previous_level"] == "C0"
    assert risk_store.query_one("SELECT level FROM rr_targets WHERE target_key = 'T1'")["level"] == "C0"

    clock["t"] = 4000
    saved = registry.close_level(risk_store, "T1")
    assert saved["level"] == "C3"
    row = risk_store.query_one("SELECT level, updated_at FROM rr_targets WHERE target_key = 'T1'")
    assert row["level"] == "C3" and row["updated_at"] == 4000

    # 이미 C3 인 타깃에서 좌석이 비종결로 되돌아가도 레벨은 내려가지 않는다.
    risk_store.execute("UPDATE rr_coverage SET status = 'pending' WHERE target_key = 'T1' AND agent_key = 'exp-sim'")
    back = registry.close_level(risk_store, "T1", persist=False)
    assert back["c1"] is False and back["level"] == "C3" and back["previous_level"] == "C3"


def test_close_level_unknown_target_is_404(risk_store):
    with pytest.raises(AppError) as exc:
        registry.close_level(risk_store, "NOPE")
    assert exc.value.code == "E404" and exc.value.http_status == 404


# ================================================================ 재제기 강도(escalated, plan §4.7.1 · §0.9 P3-16)
def _dismissed_row(store, target_key: str, cluster_key: str, *, sev3: int, support: int, grade: str) -> None:
    """사람이 dismissed 로 닫아 둔 행 — 그때의 기준선을 status_basis_json 에 남긴다."""
    _target(store, target_key)
    _reg_row(store, target_key, cluster_key)
    store.execute(
        "UPDATE rr_registry SET status = 'dismissed', status_source = 'human', status_decided_by = ?,"
        " status_decided_at = 900, status_basis_json = ?, sev3 = ?, support = ?, evidence_grade = ?"
        " WHERE target_key = ? AND cluster_key = ?",
        (OWNER, json.dumps({"evidence_ref": "rpt:1", "finding_ids": [], "support_at_decision": support,
                            "sev3_at_decision": sev3, "grade_at_decision": grade}),
         sev3, support, grade, target_key, cluster_key))


@pytest.mark.parametrize("new_sev3,expected", [(3, True), (1, False)])
def test_a_stronger_reraise_flags_the_dismissed_row(risk_store, clock, new_sev3, expected):
    """강도가 오른 재제기는 needs_review_json 을 남기고, 같은 강도면 남기지 않는다. status 는 불변이다."""
    _dismissed_row(risk_store, "T_old", "ck:reraise00001", sev3=1, support=1, grade="경험칙")
    row = {"target_key": "T_new", "cluster_key": "ck:reraise00001", "sev3": new_sev3, "support": 1,
           "evidence_grade": "경험칙"}
    flagged = registry._flag_escalations(risk_store, [row], "T_new", 1234)

    saved = risk_store.query_one(
        "SELECT status, status_source, needs_review_json FROM rr_registry"
        " WHERE target_key = 'T_old' AND cluster_key = 'ck:reraise00001'")
    assert (saved["status"], saved["status_source"]) == ("dismissed", "human")   # status 는 그대로다
    if expected:
        assert flagged == ["ck:reraise00001"]
        note = json.loads(saved["needs_review_json"])
        assert note["escalated"] is True and note["by_target"] == "T_new" and note["since"] == 1234
        assert note["delta"]["sev3"] == new_sev3 - 1
    else:
        assert flagged == [] and saved["needs_review_json"] is None


def test_human_reconfirmation_clears_the_escalation_flag(risk_store, clock):
    """사람이 다시 확정하면 재검토 표기가 지워진다(set_status 가 needs_review_json 을 비운다)."""
    _dismissed_row(risk_store, "T_old", "ck:reraise00002", sev3=1, support=1, grade="경험칙")
    registry._flag_escalations(risk_store, [{"target_key": "T_new", "cluster_key": "ck:reraise00002",
                                             "sev3": 3, "support": 2, "evidence_grade": "도구예측"}],
                               "T_new", 1234)
    assert risk_store.query_one(
        "SELECT needs_review_json FROM rr_registry WHERE target_key = 'T_old'")["needs_review_json"]

    registry.set_status(risk_store, "ck:reraise00002", "dismissed", owner_sub=OWNER, target_key="T_old",
                        evidence_ref="rpt:2")
    assert risk_store.query_one(
        "SELECT needs_review_json FROM rr_registry WHERE target_key = 'T_old'")["needs_review_json"] is None


# ================================================================ 조직 공개 토글(plan §5.1 원칙 9 · §0.9 P6-8)
def test_visibility_toggle_is_owner_only_and_writes_stay_closed(risk_store, clock):
    """org 로 열면 읽기가 열리고 쓰기는 그대로 소유자만이다(남의 신원은 404 가 아니라 403)."""
    from app import routes

    _target(risk_store)
    _reg_row(risk_store, "T1", "c1")
    other = "someone@else.com"

    with pytest.raises(AppError) as stranger:
        registry.set_visibility(risk_store, "c1", "org", owner_sub=other)
    assert (stranger.value.code, stranger.value.http_status) == ("E403", 403)

    out = registry.set_visibility(risk_store, "c1", "org", owner_sub=OWNER)
    assert out["visibility"] == "org" and out["updated"] == 1
    assert risk_store.query_one(
        "SELECT visibility FROM rr_registry WHERE cluster_key = 'c1'")["visibility"] == "org"

    # 공개는 읽기 경계다 — 남의 신원이 쓰려 하면 403 이고, 그 사실이 404 로 숨겨지지 않는다.
    with pytest.raises(AppError) as write:
        registry.set_status(risk_store, "c1", "verified", owner_sub=other, evidence_ref="rpt:1")
    assert (write.value.code, write.value.http_status) == ("E403", 403)

    with pytest.raises(AppError) as vocab:
        registry.set_visibility(risk_store, "c1", "public", owner_sub=OWNER)
    assert vocab.value.http_status == 422

    # 라우트는 감사 1행을 남긴다.
    ident = type("I", (), {"anonymous": False, "email": OWNER, "role": None,
                           "to_dict": lambda self: {}})()
    import app.routes as routes_module
    original = routes_module.get_store
    routes_module.get_store = lambda: risk_store
    try:
        routes.put_registry_visibility("c1", routes.RegistryVisibilityBody(visibility="private"), ident=ident)
    finally:
        routes_module.get_store = original
    assert risk_store.query_one(
        "SELECT COUNT(*) AS n FROM rr_audit WHERE action = 'registry.visibility'")["n"] == 1
    assert risk_store.query_one(
        "SELECT visibility FROM rr_registry WHERE cluster_key = 'c1'")["visibility"] == "private"


# ================================================================ 키 별칭 재키(plan §4.3.2 · §0.9 P3-22)
def test_cluster_alias_write_revoke_and_hop_limit(risk_store, clock):
    """사람 확정 1행 → 병합이 대표 키로 접고, 철회하면 다시 갈린다. 6홉·순환은 409 다."""
    _target(risk_store)
    _reg_row(risk_store, "T1", "ck:a0000000001")
    _reg_row(risk_store, "T1", "ck:b0000000002")

    alias = registry.add_cluster_alias(risk_store, "ck:a0000000001", "ck:b0000000002", owner_sub=OWNER)
    assert alias["new_cluster_key"] == "ck:b0000000002"
    assert registry.resolve_cluster_key(risk_store, "ck:a0000000001") == "ck:b0000000002"

    with pytest.raises(AppError) as again:
        registry.add_cluster_alias(risk_store, "ck:a0000000001", "ck:b0000000002", owner_sub=OWNER)
    assert again.value.http_status == 409

    with pytest.raises(AppError) as cycle:
        registry.add_cluster_alias(risk_store, "ck:b0000000002", "ck:a0000000001", owner_sub=OWNER)
    assert (cycle.value.code, cycle.value.http_status) == ("alias_chain_too_long", 409)

    revoked = registry.revoke_cluster_alias(risk_store, "ck:a0000000001", owner_sub=OWNER)
    assert revoked["revoked"] is True
    # 철회는 행 삭제가 아니라 표기다 — 행은 남고 해석만 끊긴다.
    assert risk_store.query_one(
        "SELECT revoked_at FROM rr_cluster_alias WHERE old_cluster_key = 'ck:a0000000001'")["revoked_at"]
    assert registry.resolve_cluster_key(risk_store, "ck:a0000000001") == "ck:a0000000001"


def test_cluster_alias_chain_stops_at_five_hops(risk_store, clock):
    """체인은 5홉까지다 — 6홉째 별칭은 409 이고 행이 생기지 않는다."""
    keys = [f"ck:hop{i:09d}" for i in range(7)]
    # 끝에서부터 이어 붙인다(새 별칭은 자기 뒤 체인 길이를 본다).
    made = 0
    for old, new in reversed(list(zip(keys, keys[1:]))):
        try:
            registry.add_cluster_alias(risk_store, old, new, owner_sub=OWNER, reason="taxonomy_major")
        except AppError as exc:
            assert (exc.code, exc.http_status) == ("alias_chain_too_long", 409)
            break
        made += 1
    else:
        raise AssertionError("6홉째에서 막혔어야 한다")
    assert made == registry.ALIAS_MAX_HOPS
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_cluster_alias")["n"] == registry.ALIAS_MAX_HOPS


def test_merge_folds_findings_through_a_human_alias(risk_store, clock):
    """finding 행의 cluster_key 는 불변이고 병합만 대표 키로 접힌다(별칭 해석)."""
    _target(risk_store)
    _finding(risk_store, "T1", "F1", "ck:x0000000001", panel_id="P1")
    _finding(risk_store, "T1", "F2", "ck:y0000000002", panel_id="P2")
    before = registry.merge(risk_store, "T1", owner_sub=OWNER)
    assert before["clusters"] == 2

    registry.add_cluster_alias(risk_store, "ck:x0000000001", "ck:y0000000002", owner_sub=OWNER)
    after = registry.merge(risk_store, "T1", owner_sub=OWNER)
    assert after["clusters"] == 1
    row = risk_store.query_one(
        "SELECT support FROM rr_registry WHERE cluster_key = 'ck:y0000000002' AND target_key = 'T1'")
    assert row["support"] == 2                       # support 는 합이 아니라 distinct 패널 수다
    assert {r["cluster_key"] for r in risk_store.query(
        "SELECT cluster_key FROM rr_findings WHERE target_key = 'T1'")} == {
        "ck:x0000000001", "ck:y0000000002"}          # finding 행의 키는 바이트 불변이다

    registry.revoke_cluster_alias(risk_store, "ck:x0000000001", owner_sub=OWNER)
    assert registry.merge(risk_store, "T1", owner_sub=OWNER)["clusters"] == 2


# ================================================================ §4.7.3 통합 보고서 — minutes 의 [품질 플래그]


def test_report_minutes_carry_the_panel_quality_flags(risk_store, clock):
    """패널 quality.flags 가 통합 보고서 [품질 플래그] 에 실린다(§6.5.5 '기준 미달 패널은 minutes 에 표로 나온다').

    쓰는 쪽(러너·MCP 회수)은 `flags`(복수)인데 보고서는 `flag`(단수)를 읽어, 이 줄에는 파싱 실패 말고는 한 번도
    실린 적이 없었다. 빠진 근거·잘린 메모처럼 같은 이름의 상세가 있는 플래그는 그 상세까지 적는다.
    """
    _target(risk_store)
    _panel(risk_store, "T1", "PA1", 1, quality={
        "flags": ["low_tool_use", "evidence_dropped", "user_memo_cut"],
        "evidence_dropped": ["E9", "X1"], "user_memo_cut": {"chars": 1500, "kept": 266}})
    _panel(risk_store, "T1", "PA2", 2, parsed=0, quality={"flags": ["spec_parse_failed"]})
    _panel(risk_store, "T1", "PA3", 3, quality={"flags": []})

    minutes = "\n".join(registry.build_report(risk_store, "T1")["blocks"]["minutes"])
    assert minutes.split("[품질 플래그]\n")[1].split("\n") == [
        "panel_no=1 low_tool_use",
        'panel_no=1 evidence_dropped ["E9","X1"]',
        'panel_no=1 user_memo_cut {"chars":1500,"kept":266}',
        "panel_no=2 spec_parse_failed",                  # flags 와 risk_spec_parsed 가 같은 말을 두 번 하지 않는다
    ]


def test_error_codes_use_the_canonical_spelling():
    """오류 코드는 계약이다 — 클라이언트가 문자열로 분기한다(정본 §8.2.3 통과 기준 15 · §4.3.2 13).

    코드는 `evidence_ref_required`·`family_key_mismatch` 로 적혀 있었고 정본은 `evidence_required`·
    `family_key_differs` 로 일관되게 적는다(다른 표기는 정본에 0회). 표기가 갈리면 정본대로 분기한
    클라이언트가 그 422 를 못 알아본다 — 사람이 근거 없이 확정하는 것을 막는 가드가 화면에서
    '알 수 없는 오류' 로 보인다는 뜻이다.
    """
    import re
    from pathlib import Path

    src = "\n".join(p.read_text(encoding="utf-8")
                    for p in (Path(__file__).resolve().parents[1] / "app").rglob("*.py"))
    for gone in ("evidence_ref_required", "family_key_mismatch"):
        assert gone not in src, f"옛 표기가 남았다 — {gone}"
    for code in ("evidence_required", "family_key_differs", "note_required"):
        assert re.search(rf'AppError\(\s*"{code}"', src), f"정본 표기 코드가 없다 — {code}"
