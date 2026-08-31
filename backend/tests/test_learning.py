# 학습 루프 learning.py 검증 — delta 선례 재합산·패턴 마이닝·승격 상태기계·규칙 백테스트(plan §7.4·§7.5)
from __future__ import annotations

import dataclasses
import json

import pytest

from app import common, config, learning, registry
from app.errors import AppError

OWNER = "tester@example.com"
CK = "ck:1111111111"
NORM_A = "cl:aaaaaaaaaaaa"
NORM_B = "cl:bbbbbbbbbbbb"


# ---------------------------------------------------------------- 삽입 도우미


def _target(store, target_key, *, project_id="P1", kind="snap", ref_id="S1", created_at=100):
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, external_sync_json, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?)",
        (target_key, OWNER, kind, ref_id, project_id, "0123456789ab", created_at, created_at),
    )


def _snapshot(store, snapshot_id, *, project_id="P1", ir=None, ir_hash=None):
    store.execute(
        "INSERT INTO rr_snapshots(id, project_id, owner_sub, ir_version, ir_hash, ir_json, source_ids_json, "
        "kinds_json, created_at) VALUES (?, ?, ?, 'ir-1.0', ?, ?, '[]', '[\"mcad\"]', 100)",
        (snapshot_id, project_id, OWNER, ir_hash or snapshot_id, json.dumps(ir or {"nodes": [], "edges": [],
                                                                                   "warnings": []})),
    )


def _panel(store, panel_id, target_key, *, panel_no=1, model="claude-x"):
    store.execute(
        "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, seats_json, model_json, created_at) "
        "VALUES (?, ?, ?, ?, '[]', ?, 100)",
        (panel_id, target_key, OWNER, panel_no, json.dumps({"model": model})),
    )


def _opinion(store, opinion_id, target_key, panel_id, agent_key):
    store.execute(
        "INSERT INTO rr_seat_opinions(opinion_id, target_key, panel_id, owner_sub, agent_key, domain, "
        "opinion_json, created_at) VALUES (?, ?, ?, ?, ?, 'mech', '{}', 100)",
        (opinion_id, target_key, panel_id, OWNER, agent_key, ),
    )


def _finding(
    store, finding_id, target_key, *, project_id="P1", cluster_key=NORM_A, agent_key="seat-a", model="claude-x",
    change_kind="placement", mechanism="interface", mechanism_detail="interference", direction="risk",
    severity="중대", status="open", recall_eligible=1, origin="llm", primed=False, feature_snapshot=None,
    created_at=100, claim="합성 클레임",
):
    """패널·좌석 의견까지 한 벌로 만들어 finding 을 넣는다(좌석 수·모델 수를 세려면 세 표가 다 필요하다)."""
    panel_id = f"PN-{target_key}-{agent_key}"
    if store.query_one("SELECT id FROM rr_panels WHERE id = ?", (panel_id,)) is None:
        panel_no = len(store.query("SELECT id FROM rr_panels WHERE target_key = ?", (target_key,))) + 1
        _panel(store, panel_id, target_key, panel_no=panel_no, model=model)
    opinion_id = f"OP-{target_key}-{agent_key}"
    if store.query_one("SELECT opinion_id FROM rr_seat_opinions WHERE opinion_id = ?", (opinion_id,)) is None:
        _opinion(store, opinion_id, target_key, panel_id, agent_key)
    fj = {"claim": claim, "primed": primed, "feature_snapshot": feature_snapshot or {}}
    store.execute(
        "INSERT INTO rr_findings(finding_id, claim_uid, origin, target_key, panel_id, opinion_id, project_id, "
        "owner_sub, direction, domain, mechanism, mechanism_detail, change_kind, subject_key, severity, sev3, "
        "judgement, evidence_grade, precedent, cluster_key, finding_json, recall_eligible, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'mech', ?, ?, ?, ?, ?, 2, 'WARNING', '문헌·규격', 'none', ?, ?, ?, ?, ?)",
        (finding_id, f"{panel_id}#{finding_id}", origin, target_key, panel_id, opinion_id, project_id, OWNER,
         direction, mechanism, mechanism_detail, change_kind, CK, severity, cluster_key, json.dumps(fj),
         recall_eligible, status, created_at),
    )
    return finding_id


def _label(store, label_id, finding_id, outcome, *, matched_by="manual", source="expert_review",
           evidence_ref=None, labeled_at=200):
    store.execute(
        "INSERT INTO rr_labels(id, finding_id, owner_sub, source, outcome, matched_by, evidence_ref, labeled_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (label_id, finding_id, OWNER, source, outcome, matched_by, evidence_ref or f"inc:{label_id}", labeled_at),
    )


def _registry_row(store, target_key, cluster_key, *, weak_subject=0, status_source="code"):
    store.execute(
        "INSERT INTO rr_registry(target_key, cluster_key, owner_sub, merged_json, weak_subject, status_source, "
        "updated_at) VALUES (?, ?, ?, '{}', ?, ?, 100)",
        (target_key, cluster_key, OWNER, weak_subject, status_source),
    )


def _pattern(store, pattern_id, *, cluster_key_norm=NORM_A, status="candidate", mechanism="interface",
             mechanism_detail="interference", change_kind="placement", merged_into=None):
    store.execute(
        "INSERT INTO rr_patterns(id, owner_sub, cluster_key_norm, mechanism, mechanism_detail, change_kind, "
        "subject_class, status, merged_into, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'ck', ?, ?, 100, 100)",
        (pattern_id, OWNER, cluster_key_norm, mechanism, mechanism_detail, change_kind, status, merged_into),
    )


def _spread(store, n_targets, *, projects=2, agents=("seat-a", "seat-b"), model="claude-x", primed=False,
            cluster_key=NORM_A):
    """n_targets 개 타깃에 같은 cluster 를 반복 제기한다(과제는 projects 개로 나눈다)."""
    for i in range(n_targets):
        target_key = f"T{i + 1}"
        project_id = f"P{(i % projects) + 1}"
        _target(store, target_key, project_id=project_id)
        for agent_key in agents:
            _finding(store, f"F{i + 1}{agent_key[-1]}", target_key, project_id=project_id, agent_key=agent_key,
                     model=model, primed=primed, cluster_key=cluster_key)


# ---------------------------------------------------------------- 도우미 함수


def test_precision_of_marks_low_n():
    assert learning.precision_of(3, 1) == {"precision": 0.75, "n": 4, "low_n": True}
    assert learning.precision_of(4, 1)["low_n"] is False
    assert learning.precision_of(0, 0)["precision"] is None


def test_delta_prior_line_hides_precision_below_five():
    row = {"change_kind": "placement", "mechanism": "interface", "mechanism_detail": "interference",
           "n_raised": 7, "n_targets": 5, "n_verified": 3, "n_dismissed": 1}
    assert learning.delta_prior_line(row).endswith("precision n<5")
    row["n_dismissed"] = 2
    assert "precision 0.60 (n=5)" in learning.delta_prior_line(row)


def test_resolve_cluster_key_follows_chain_and_skips_revoked(risk_store):
    store = risk_store
    store.execute(
        "INSERT INTO rr_cluster_alias(old_cluster_key, new_cluster_key, owner_sub, reason, decided_by, decided_at) "
        "VALUES ('a', 'b', ?, 'cluster_merge', ?, 1)", (OWNER, OWNER))
    store.execute(
        "INSERT INTO rr_cluster_alias(old_cluster_key, new_cluster_key, owner_sub, reason, decided_by, decided_at, "
        "revoked_by, revoked_at) VALUES ('b', 'c', ?, 'cluster_merge', ?, 1, ?, 2)", (OWNER, OWNER, OWNER))
    assert learning.resolve_cluster_key(store, "a") == "b"


def test_resolve_cluster_key_breaks_cycle(risk_store):
    store = risk_store
    for old, new in (("a", "b"), ("b", "a")):
        store.execute(
            "INSERT INTO rr_cluster_alias(old_cluster_key, new_cluster_key, owner_sub, reason, decided_by, "
            "decided_at) VALUES (?, ?, ?, 'cluster_merge', ?, 1)", (old, new, OWNER, OWNER))
    assert learning.resolve_cluster_key(store, "a") == "b"


# ---------------------------------------------------------------- §7.4 라벨 훅·재합산


def test_label_priors_count_confirmed_and_dismissed(risk_store):
    store = risk_store
    _target(store, "T1")
    _finding(store, "F1", "T1")
    _finding(store, "F2", "T1", agent_key="seat-b")
    _label(store, "L1", "F1", "confirmed")
    _label(store, "L2", "F2", "refuted")
    assert learning.recompute_label_priors(store) == 1
    row = store.query_one(
        "SELECT n_verified, n_dismissed FROM rr_delta_priors WHERE change_kind = 'placement'", ())
    assert (row["n_verified"], row["n_dismissed"]) == (1, 1)
    # 두 번째 호출은 쓸 것이 없다(멱등).
    assert learning.recompute_label_priors(store) == 0


def test_label_priors_skip_inconclusive_and_discretization(risk_store):
    store = risk_store
    _target(store, "T1")
    _finding(store, "F1", "T1")
    _finding(store, "F2", "T1", agent_key="seat-b", change_kind="discretization")
    _label(store, "L1", "F1", "inconclusive")
    _label(store, "L2", "F2", "confirmed")
    learning.recompute_label_priors(store)
    assert store.query("SELECT change_kind FROM rr_delta_priors", ()) == []


def test_auto_label_on_human_row_excluded_until_curated(risk_store):
    store = risk_store
    _target(store, "T1")
    _finding(store, "F1", "T1")
    _registry_row(store, "T1", NORM_A, status_source="human")
    _label(store, "L1", "F1", "confirmed", matched_by="auto", source="incident")
    learning.recompute_label_priors(store)
    row = store.query_one("SELECT n_verified FROM rr_delta_priors WHERE change_kind = 'placement'", ())
    assert row is None or row["n_verified"] == 0
    # 사람이 직접 단 라벨은 같은 행에서도 센다.
    _label(store, "L2", "F1", "confirmed", matched_by="manual")
    learning.recompute_label_priors(store)
    assert store.query_one("SELECT n_verified FROM rr_delta_priors", ())["n_verified"] == 1


def test_on_label_updates_combo_and_pattern(risk_store):
    store = risk_store
    _target(store, "T1")
    _finding(store, "F1", "T1")
    _pattern(store, "P-001")
    _label(store, "L1", "F1", "confirmed")
    out = learning.on_label(store, "L1")
    assert out["combo"] == ["placement", "interface", "interference"]
    assert out["pattern_id"] == "P-001"
    assert store.query_one("SELECT n_verified FROM rr_delta_priors", ())["n_verified"] == 1
    pattern = store.query_one("SELECT n_confirmed, precision FROM rr_patterns WHERE id = 'P-001'", ())
    assert (pattern["n_confirmed"], pattern["precision"]) == (1, 1.0)


def test_on_label_missing_label_404(risk_store):
    with pytest.raises(AppError) as err:
        learning.on_label(risk_store, "nope")
    assert err.value.http_status == 404


def test_check_delta_priors_clean_after_merge(risk_store):
    store = risk_store
    _target(store, "T1")
    _finding(store, "F1", "T1")
    registry.merge(store, "T1", owner_sub=OWNER)
    assert learning.check_delta_priors(store, fix=False)["drift"] == 0


def test_check_delta_priors_detects_and_fixes_drift(risk_store):
    store = risk_store
    _target(store, "T1")
    _finding(store, "F1", "T1")
    registry.merge(store, "T1", owner_sub=OWNER)
    store.execute("UPDATE rr_delta_priors SET n_raised = 99, n_verified = 7")
    report = learning.check_delta_priors(store, fix=True)
    assert report["drift"] == 1 and report["fixed"] == 1
    row = store.query_one("SELECT n_raised, n_verified FROM rr_delta_priors", ())
    assert (row["n_raised"], row["n_verified"]) == (1, 0)
    assert learning.check_delta_priors(store, fix=False)["drift"] == 0


# ---------------------------------------------------------------- §7.5 패턴 마이너


def test_mine_creates_candidate_and_queue(risk_store):
    store = risk_store
    _spread(store, 3)
    out = learning.mine_patterns(store)
    assert [c["pattern_id"] for c in out["created"]] == ["P-001"]
    row = store.query_one("SELECT status, n_targets, n_projects, n_experts FROM rr_patterns WHERE id = 'P-001'", ())
    assert (row["status"], row["n_targets"], row["n_projects"], row["n_experts"]) == ("candidate", 3, 2, 2)
    queue = store.query_one("SELECT kind, payload_json, status FROM rr_curation_queue", ())
    payload = json.loads(queue["payload_json"])
    assert queue["kind"] == "pattern_candidate" and queue["status"] == "open"
    assert payload["pattern_id"] == "P-001" and payload["proposal"] == "known"
    assert len(payload["sample_claims"]) <= 5


def test_mine_below_threshold_makes_nothing(risk_store):
    store = risk_store
    _spread(store, 2)                     # 타깃 2 < 3
    out = learning.mine_patterns(store)
    assert out["created"] == [] and "targets" in out["skipped"][0]["unmet"]
    assert store.query("SELECT id FROM rr_patterns", ()) == []


def test_mine_single_expert_below_threshold(risk_store):
    store = risk_store
    _spread(store, 3, agents=("seat-a",))
    out = learning.mine_patterns(store)
    assert out["created"] == [] and "experts" in out["skipped"][0]["unmet"]


def test_mine_is_idempotent(risk_store):
    store = risk_store
    _spread(store, 3)
    learning.mine_patterns(store)
    second = learning.mine_patterns(store)
    assert second["created"] == [] and second["updated"] == []
    assert len(store.query("SELECT id FROM rr_patterns", ())) == 1
    assert len(store.query("SELECT id FROM rr_curation_queue", ())) == 1


@pytest.mark.parametrize("nullify", ["rejected_in_panel", "recall_eligible", "weak_subject"])
def test_mine_excludes_three_atom_kinds(risk_store, nullify):
    """세 원자(rejected_in_panel · recall_eligible=0 · weak_subject)는 승격 카운트에서 빠진다(§7.5)."""
    store = risk_store
    _spread(store, 3)
    if nullify == "rejected_in_panel":
        store.execute("UPDATE rr_findings SET status = 'rejected_in_panel' WHERE target_key = 'T1'")
    elif nullify == "recall_eligible":
        store.execute("UPDATE rr_findings SET recall_eligible = 0 WHERE target_key = 'T1'")
    else:
        _registry_row(store, "T1", NORM_A, weak_subject=1)
    out = learning.mine_patterns(store)
    assert out["created"] == [] and out["skipped"][0]["unmet"] == ["targets"]


def test_mine_distinct_models_guard(risk_store, monkeypatch):
    store = risk_store
    _spread(store, 3, model="claude-x")
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_promote_distinct_models=2))
    out = learning.mine_patterns(store)
    assert out["created"] == [] and "models" in out["skipped"][0]["unmet"]
    # 다른 모델의 패널이 한 번 더 같은 클러스터를 내면 가드가 풀린다.
    _target(store, "T4", project_id="P2")
    _finding(store, "F4a", "T4", project_id="P2", agent_key="seat-c", model="glm-y")
    out = learning.mine_patterns(store)
    assert [c["pattern_id"] for c in out["created"]] == ["P-001"]


def test_mine_primed_repeats_do_not_reach_threshold(risk_store):
    """브리프가 심어준 선례를 되풀이한 원자(primed)는 승격 임계를 채우지 못한다(gap_21 독립 가드)."""
    store = risk_store
    _spread(store, 3, primed=True)
    out = learning.mine_patterns(store)
    assert out["created"] == []
    stats = learning.pattern_stats(learning.collect_atoms(store)[NORM_A], [])
    assert stats["n_targets"] == 3 and stats["n_targets_independent"] == 0
    assert stats["echo_ratio"] == 1.0


def test_mine_with_owner_scope_counts_only_that_owner(risk_store):
    """소유자가 다른 finding 이 한 패턴의 승격 임계를 함께 채우지 않는다(rr_findings 는 소유자 표다)."""
    store = risk_store
    _spread(store, 3)
    store.execute("UPDATE rr_findings SET owner_sub = 'b@x.com' WHERE target_key = 'T2'")
    store.execute("UPDATE rr_findings SET owner_sub = 'c@x.com' WHERE target_key = 'T3'")

    out = learning.mine_patterns(store, owner_sub=OWNER)
    assert out["created"] == [] and "targets" in out["skipped"][0]["unmet"]
    assert store.query("SELECT id FROM rr_patterns", ()) == []


def test_mine_does_not_write_another_owners_pattern(risk_store):
    """같은 cluster_key_norm 이 남의 패턴으로 서 있으면 건너뛴다(UNIQUE(cluster_key_norm) 라 자리를 못 나눈다)."""
    store = risk_store
    _spread(store, 3)
    _pattern(store, "P-001")
    store.execute("UPDATE rr_patterns SET owner_sub = 'b@x.com' WHERE id = 'P-001'")

    out = learning.mine_patterns(store, owner_sub=OWNER)
    assert out["updated"] == []
    assert out["skipped"][0]["unmet"] == ["owned_by_other"]
    assert store.query_one("SELECT n_findings FROM rr_patterns WHERE id = 'P-001'", ())["n_findings"] is None


def test_candidate_queue_flags_missing_primed_stamp(risk_store):
    """primed 스탬프가 없으면 echo_ratio 0.0 은 독립성 근거가 아니다 — 큐가 그 사실을 싣는다(gap_21)."""
    store = risk_store
    _spread(store, 3, projects=3)
    store.execute("UPDATE rr_findings SET finding_json = ?", (json.dumps({"claim": "스탬프 없는 원자"}),))

    out = learning.mine_patterns(store)
    assert [c["pattern_id"] for c in out["created"]] == ["P-001"]
    payload = json.loads(store.query_one(
        "SELECT payload_json FROM rr_curation_queue WHERE kind = 'pattern_candidate'", ())["payload_json"])
    assert payload["independence_verified"] is False and payload["stamp_missing"] == 6
    assert "독립성 미검증" in payload["note"] and payload["echo_ratio"] == 0.0

    promoted = learning.promote(store, "P-001", to_status="known", decided_by=OWNER)
    assert promoted["independence"]["verified"] is False
    assert promoted["independence"]["stamp_missing"] == 6


def test_mine_proposes_suspend_on_low_recent_precision(risk_store):
    store = risk_store
    _spread(store, 3)
    learning.mine_patterns(store)
    for i in range(4):
        _label(store, f"L{i}", "F1a" if i else "F1b", "refuted", evidence_ref=f"inc:{i}")
    out = learning.mine_patterns(store)
    assert out["suspend_proposed"] and out["suspend_proposed"][0]["pattern_id"] == "P-001"
    assert store.query_one("SELECT status FROM rr_patterns WHERE id = 'P-001'", ())["status"] == "candidate"
    # 제안은 한 번만 큐에 올린다.
    again = learning.mine_patterns(store)
    assert again["suspend_proposed"] == []


# ---------------------------------------------------------------- §7.5 승격 상태기계


def test_promote_requires_human_approval(risk_store):
    store = risk_store
    _pattern(store, "P-001")
    with pytest.raises(AppError) as err:
        learning.promote(store, "P-001", to_status="known", decided_by="")
    assert err.value.http_status == 422
    assert store.query_one("SELECT status FROM rr_patterns WHERE id = 'P-001'", ())["status"] == "candidate"


def test_promote_known_gate_unmet_422(risk_store):
    store = risk_store
    _spread(store, 3)
    learning.mine_patterns(store)
    with pytest.raises(AppError) as err:
        learning.promote(store, "P-001", to_status="known", decided_by=OWNER)
    assert err.value.http_status == 422
    assert store.query_one("SELECT status FROM rr_patterns WHERE id = 'P-001'", ())["status"] == "candidate"


def test_promote_known_with_confirmed_label(risk_store):
    store = risk_store
    _spread(store, 3)
    learning.mine_patterns(store)
    _label(store, "L1", "F1a", "confirmed")
    out = learning.promote(store, "P-001", to_status="known", decided_by=OWNER)
    assert out["gate"]["by_label"] is True
    row = store.query_one("SELECT status, curated_by, n_confirmed FROM rr_patterns WHERE id = 'P-001'", ())
    assert (row["status"], row["curated_by"], row["n_confirmed"]) == ("known", OWNER, 1)


def test_promote_known_by_volume(risk_store):
    store = risk_store
    _spread(store, 3, projects=3)         # finding 6 · project 3
    learning.mine_patterns(store)
    out = learning.promote(store, "P-001", to_status="known", decided_by=OWNER)
    assert out["gate"]["by_volume"] is True and out["gate"]["by_label"] is False


def test_known_gate_does_not_repeat_the_model_guard(risk_store, monkeypatch):
    """D6 모델 가드는 candidate 조건에만 붙는다(§7.4) — 이미 표면화된 패턴을 사람 승인에서 또 막지 않는다."""
    store = risk_store
    _spread(store, 3)                     # 한 모델뿐
    learning.mine_patterns(store)
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_promote_distinct_models=2))
    _label(store, "L1", "F1a", "confirmed")

    out = learning.promote(store, "P-001", to_status="known", decided_by=OWNER)
    assert out["gate"]["ok"] is True and out["gate"]["n_models"] == 1
    assert out["gate"]["distinct_models_required"] == 2
    assert store.query_one("SELECT status FROM rr_patterns WHERE id = 'P-001'", ())["status"] == "known"


def test_suspended_pattern_can_come_back_to_rule(risk_store):
    """복귀 경로가 파생 규칙 id 충돌로 막히지 않는다 — suspend 가 내려놓은 그 패턴의 규칙을 되살린다(§7.5)."""
    store = risk_store
    _backtest_corpus(store)
    _pattern(store, "P-001", status="known")
    rule = {"condition_json": CONDITION_HIT, "why_it_matters": "간섭 깊이가 확정 범위를 넘었다"}
    first = learning.promote(store, "P-001", to_status="rule", decided_by=OWNER, rule=rule)
    learning.promote(store, "P-001", to_status="suspended", decided_by=OWNER, reason="최근 정밀도 하락")
    assert store.query_one("SELECT status FROM rr_rules WHERE id = ?", (first["rule_id"],))["status"] == "retired"

    back = learning.promote(store, "P-001", to_status="rule", decided_by=OWNER, rule=rule)
    assert back["rule_id"] == first["rule_id"]
    assert store.query_one("SELECT status FROM rr_rules WHERE id = ?", (first["rule_id"],))["status"] == "active"
    assert len(store.query("SELECT id FROM rr_rules", ())) == 1
    assert store.query_one("SELECT status FROM rr_patterns WHERE id = 'P-001'", ())["status"] == "rule"


def test_promote_rejects_illegal_transition(risk_store):
    store = risk_store
    _pattern(store, "P-001", status="candidate")
    with pytest.raises(AppError) as err:
        learning.promote(store, "P-001", to_status="rule", decided_by=OWNER)
    assert err.value.http_status == 422


def test_promote_rejects_merged_pattern(risk_store):
    store = risk_store
    _pattern(store, "P-001", status="candidate", merged_into="P-002")
    with pytest.raises(AppError) as err:
        learning.promote(store, "P-001", to_status="known", decided_by=OWNER)
    assert "P-002" in err.value.message


def test_promote_suspend_and_deprecate_retire_rules(risk_store):
    store = risk_store
    _pattern(store, "P-001", status="known")
    store.execute(
        "INSERT INTO rr_rules(id, pattern_id, rule_version, condition_json, severity, why_it_matters, source, "
        "status, created_at) VALUES ('R-P001', 'P-001', 'rules-1.0', '{}', '중대', '사람이 쓴 문장', 'pattern', "
        "'active', 100)")
    learning.promote(store, "P-001", to_status="suspended", decided_by=OWNER, reason="최근 라벨 정밀도 하락")
    row = store.query_one("SELECT status, suspended_reason FROM rr_patterns WHERE id = 'P-001'", ())
    assert row["status"] == "suspended" and row["suspended_reason"] == "최근 라벨 정밀도 하락"
    assert store.query_one("SELECT status FROM rr_rules WHERE id = 'R-P001'", ())["status"] == "retired"
    learning.promote(store, "P-001", to_status="deprecated", decided_by=OWNER)
    assert store.query_one("SELECT status FROM rr_patterns WHERE id = 'P-001'", ())["status"] == "deprecated"


def test_promote_predictor_gate_unmet_writes_nothing(risk_store):
    store = risk_store
    _pattern(store, "P-001", status="rule")
    with pytest.raises(AppError) as err:
        learning.promote(store, "P-001", to_status="predictor", decided_by=OWNER, cv={"metric": "r2", "value": 0.9})
    assert err.value.http_status == 422 and "n_labeled" in err.value.message
    assert store.query_one("SELECT status FROM rr_patterns WHERE id = 'P-001'", ())["status"] == "rule"


# ---------------------------------------------------------------- §7.5 백테스트·규칙 초안


def _backtest_corpus(store, n=12, *, depth_hit=0.1, depth_miss=0.0):
    """confirmed 타깃만 penetration_depth 가 임계를 넘는 코퍼스. 시간순으로 T01…Tn."""
    for i in range(1, n + 1):
        confirmed = i % 2 == 1
        snapshot_id = f"S{i:02d}"
        depth = depth_hit if confirmed else depth_miss
        _snapshot(store, snapshot_id, ir={
            "nodes": [{"nid": "n1"}, {"nid": "n2"}],
            "edges": [{"eid": "e1", "a": "n1", "b": "n2", "kind": "interference",
                       "attrs": {"penetration_depth": depth}}],
            "warnings": [],
        })
        target_key = f"T{i:02d}"
        _target(store, target_key, ref_id=snapshot_id, created_at=100 + i)
        _finding(store, f"F{i:02d}", target_key)
        _label(store, f"L{i:02d}", f"F{i:02d}", "confirmed" if confirmed else "refuted", labeled_at=200 + i)


CONDITION_HIT = {"all": [{"ref": "edge.penetration_depth", "op": "between", "value": [0.05, 1.0]}], "any": []}
CONDITION_MISS = {"all": [{"ref": "edge.penetration_depth", "op": "gte", "value": 9.0}], "any": []}


def test_backtest_splits_holdout_and_scores(risk_store):
    store = risk_store
    _backtest_corpus(store)
    out = learning.backtest(store, CONDITION_HIT, cluster_key_norm=NORM_A)
    assert out["n_labeled"] == 12
    assert out["train"]["n"] == 8 and out["holdout"]["n"] == 4
    assert out["precision"] == 1.0 and out["recall"] == 1.0
    assert out["passes"] is True


def test_backtest_reports_unmet_gates(risk_store):
    store = risk_store
    _backtest_corpus(store, n=4)
    out = learning.backtest(store, CONDITION_MISS, cluster_key_norm=NORM_A)
    assert out["passes"] is False
    assert set(out["unmet"]) == {"n_labeled", "precision", "recall"}


def test_backtest_counts_false_alarms(risk_store):
    """모든 타깃에서 걸리는 조건은 재현율은 1 이어도 정밀도 게이트에서 걸린다."""
    store = risk_store
    _backtest_corpus(store)
    always = {"all": [{"ref": "edge.penetration_depth", "op": "gte", "value": -1.0}], "any": []}
    out = learning.backtest(store, always, cluster_key_norm=NORM_A)
    assert out["holdout"] == {"n": 4, "tp": 2, "fp": 2, "fn": 0, "tn": 0, "precision": 0.5, "recall": 1.0}
    assert out["unmet"] == ["precision"]


def test_promote_rule_requires_passing_backtest(risk_store):
    store = risk_store
    _backtest_corpus(store, n=4)
    _pattern(store, "P-001", status="known")
    with pytest.raises(AppError) as err:
        learning.promote(store, "P-001", to_status="rule", decided_by=OWNER,
                         rule={"condition_json": CONDITION_MISS, "why_it_matters": "사람이 쓴 문장"})
    assert err.value.http_status == 422
    assert store.query_one("SELECT status FROM rr_patterns WHERE id = 'P-001'", ())["status"] == "known"
    assert store.query("SELECT id FROM rr_rules", ()) == []


def test_promote_rule_creates_active_rule(risk_store):
    store = risk_store
    _backtest_corpus(store)
    _pattern(store, "P-001", status="known")
    out = learning.promote(store, "P-001", to_status="rule", decided_by=OWNER,
                           rule={"condition_json": CONDITION_HIT, "why_it_matters": "간섭 깊이가 확정 범위를 넘었다"})
    assert out["backtest"]["passes"] is True
    row = store.query_one(
        "SELECT id, status, source, activated_by, why_it_matters, backtest_json FROM rr_rules", ())
    assert (row["status"], row["source"], row["activated_by"]) == ("active", "pattern", OWNER)
    assert json.loads(row["backtest_json"])["precision"] == 1.0
    assert store.query_one("SELECT status FROM rr_patterns WHERE id = 'P-001'", ())["status"] == "rule"
    assert [r["id"] for r in learning.active_pattern_rules(store)] == [row["id"]]


def test_promote_rule_requires_human_written_text(risk_store):
    store = risk_store
    _backtest_corpus(store)
    _pattern(store, "P-001", status="known")
    with pytest.raises(AppError) as err:
        learning.promote(store, "P-001", to_status="rule", decided_by=OWNER,
                         rule={"condition_json": CONDITION_HIT})
    assert err.value.http_status == 422
    assert store.query("SELECT id FROM rr_rules", ()) == []
    assert store.query_one("SELECT status FROM rr_patterns WHERE id = 'P-001'", ())["status"] == "known"


def test_draft_rule_condition_uses_confirmed_ranges(risk_store):
    """초안은 narrative 가 실제로 저장하는 평평한 {ref: {attr: value}} 를 읽고 ref 접두로 스코프를 가른다."""
    store = risk_store
    _target(store, "T1")
    _target(store, "T2", project_id="P2")
    _finding(store, "F1", "T1", feature_snapshot={"e:1": {"min_gap": 0.2},
                                                  "p:0123456789ab": {"volume": 12.0}})
    _finding(store, "F2", "T2", project_id="P2", agent_key="seat-b",
             feature_snapshot={"e:2": {"min_gap": 5.0}})
    _label(store, "L1", "F1", "confirmed")
    _pattern(store, "P-001", status="known")
    draft = learning.draft_rule_condition(store, "P-001")
    assert draft["range_source"] == "confirmed"
    assert draft["condition_json"]["all"] == [
        {"ref": "edge.min_gap", "op": "between", "value": [0.2, 0.2]},
        {"ref": "node.volume", "op": "between", "value": [12.0, 12.0]},
    ]
    # diff.* 는 snap 스코프 평가기가 조용히 버린다 — 채점한 조건과 저장할 조건이 갈리므로 초안에 넣지 않는다.
    assert not [c for c in draft["condition_json"]["all"] if c["ref"].startswith("diff.")]
    assert draft["change_kind"] == "placement"
    assert learning.unevaluable_refs(draft["condition_json"]) == []


def test_draft_reads_plan_shaped_snapshot_too(risk_store):
    """계획 문장 그대로의 {refs:[{ref, attrs}]} 표기도 같은 범위를 낸다."""
    store = risk_store
    _target(store, "T1")
    _finding(store, "F1", "T1", feature_snapshot={"refs": [{"ref": "e:1", "attrs": {"min_gap": 0.4}}],
                                                  "project_fv": {"n_tied": 4}})
    _label(store, "L1", "F1", "confirmed")
    _pattern(store, "P-001", status="known")
    draft = learning.draft_rule_condition(store, "P-001")
    assert draft["condition_json"]["all"] == [
        {"ref": "edge.min_gap", "op": "between", "value": [0.4, 0.4]}]
    # project_fv 는 평가기가 모르는 축이라 조건이 되지 않는다(범위에는 남는다).
    assert draft["feature_ranges"]["fv:n_tied"] == [4.0, 4.0]


def test_backtest_rejects_conditions_the_evaluator_drops(risk_store):
    """diff.* 처럼 평가기가 버리는 항이 섞이면 422 다 — 측정한 조건과 저장할 조건이 갈리면 안 된다."""
    store = risk_store
    _backtest_corpus(store, n=4)
    mixed = {"all": [{"ref": "edge.penetration_depth", "op": "between", "value": [0.05, 1.0]},
                     {"ref": "diff.change_kind", "op": "in", "value": ["material"]}], "any": []}
    with pytest.raises(AppError) as err:
        learning.backtest(store, mixed, cluster_key_norm=NORM_A)
    assert err.value.http_status == 422 and "diff.change_kind" in err.value.message


def test_refresh_pattern_recounts_from_atoms(risk_store):
    store = risk_store
    _spread(store, 3)
    _pattern(store, "P-001")
    out = learning.refresh_pattern(store, "P-001")
    assert out["changed"] is True and out["stats"]["n_findings"] == 6
    assert learning.refresh_pattern(store, "P-001")["changed"] is False


def test_get_pattern_missing_404(risk_store):
    with pytest.raises(AppError) as err:
        learning.get_pattern(risk_store, "P-999")
    assert err.value.http_status == 404


def test_clock_is_not_required(risk_store):
    """now 를 주지 않아도 공용 시계로 돈다(야간 잡 경로)."""
    assert isinstance(common.now_epoch(), int)
    assert learning.mine_patterns(risk_store)["scanned"] == 0
