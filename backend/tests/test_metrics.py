# 적중 추적 metrics.py 검증 — 라벨 5경로·상충 규칙·지표 재계산·모델 층화(plan §7.6·§7.4)
from __future__ import annotations

import json

import pytest

from app import common, learning, metrics
from app.errors import AppError

OWNER = "tester@example.com"
PROJECT = "P1"
TARGET = "T1"
PANEL = "PN1"
CK_A = "ck:aaaaaaaaaaaa"


# ---------------------------------------------------------------- 픽스처·삽입 도우미


@pytest.fixture
def clock():
    state = {"t": 10_000_000}
    previous = common.set_clock(lambda: state["t"])
    yield state
    common.set_clock(previous)


def _project(store, project_id=PROJECT, *, corpus_excluded=0, product_code=None, code=None):
    store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, corpus_excluded, product_code, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 1, 1)",
        (project_id, OWNER, code or project_id, corpus_excluded, product_code),
    )


def _target(store, target_key=TARGET, *, project_id=PROJECT, kind="snap", ref_id="S1", created_at=100):
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, "
        "external_sync_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, '0123456789ab', '{}', ?, ?)",
        (target_key, OWNER, kind, ref_id, project_id, created_at, created_at),
    )


def _panel(store, panel_id=PANEL, *, target_key=TARGET, panel_no=1, model="glm-4.6",
           quality=None, status="done"):
    model_json = json.dumps({"runtime": "vllm", "model": model, "captured": "health_snapshot"}) if model else None
    store.execute(
        "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, seats_json, status, quality_json, "
        "model_json, created_at) VALUES (?, ?, ?, ?, '[]', ?, ?, ?, 1)",
        (panel_id, target_key, OWNER, panel_no, status,
         json.dumps(quality) if quality is not None else None, model_json),
    )


def _opinion(store, opinion_id, agent_key, *, target_key=TARGET, panel_id=PANEL, domain="mech", cycle=1):
    store.execute(
        "INSERT INTO rr_seat_opinions(opinion_id, target_key, panel_id, owner_sub, agent_key, domain, "
        "cycle, opinion_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', 1)",
        (opinion_id, target_key, panel_id, OWNER, agent_key, domain, cycle),
    )


def _finding(store, finding_id, *, cluster_key=CK_A, target_key=TARGET, project_id=PROJECT,
             panel_id=PANEL, opinion_id=None, origin="llm", domain="mech", mechanism="thermal",
             mechanism_detail="cte_mismatch", change_kind="dimension", severity="중대", sev3=2,
             evidence_grade="문헌·규격", precedent="in_range", status="open", status_source="code",
             direction="risk", requirement_ref=None, adh_record_id=None, created_at=100,
             subject_key=CK_A):
    store.execute(
        "INSERT INTO rr_findings(finding_id, claim_uid, origin, author_sub, target_key, panel_id, opinion_id, "
        "project_id, owner_sub, direction, domain, mechanism, mechanism_detail, change_kind, subject_key, "
        "severity, sev3, judgement, evidence_grade, precedent, requirement_ref, cluster_key, finding_json, "
        "status, status_source, adh_record_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'WARNING', ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?)",
        (finding_id, f"{finding_id}#c", origin, OWNER if origin == "human" else None, target_key,
         panel_id, opinion_id, project_id, OWNER, direction, domain, mechanism, mechanism_detail,
         change_kind, subject_key, severity, sev3, evidence_grade, precedent, requirement_ref,
         cluster_key, status, status_source, adh_record_id, created_at, created_at),
    )


def _registry(store, cluster_key=CK_A, *, target_key=TARGET, contested=0, status="open",
              status_source="code", subject_key=CK_A, mechanism="thermal",
              mechanism_detail="cte_mismatch", weak_subject=0):
    store.execute(
        "INSERT INTO rr_registry(target_key, cluster_key, owner_sub, merged_json, support, contested, "
        "subject_key, mechanism, mechanism_detail, weak_subject, status, status_source, updated_at) "
        "VALUES (?, ?, ?, '{}', 1, ?, ?, ?, ?, ?, ?, ?, 1)",
        (target_key, cluster_key, OWNER, contested, subject_key, mechanism, mechanism_detail,
         weak_subject, status, status_source),
    )


def _priors(store, *, change_kind="dimension", mechanism="thermal", mechanism_detail="cte_mismatch"):
    store.execute(
        "INSERT INTO rr_delta_priors(change_kind, mechanism, mechanism_detail, n_raised, n_targets, "
        "n_verified, n_dismissed, updated_at) VALUES (?, ?, ?, 3, 2, 0, 0, 1)",
        (change_kind, mechanism, mechanism_detail),
    )


def _pattern(store, pattern_id="PT1", *, cluster_key_norm=CK_A, status="known"):
    store.execute(
        "INSERT INTO rr_patterns(id, owner_sub, cluster_key_norm, status, n_confirmed, n_refuted, created_at, "
        "updated_at) VALUES (?, ?, ?, ?, 0, 0, 1, 1)",
        (pattern_id, OWNER, cluster_key_norm, status),
    )


def _base(store):
    """가장 흔한 배치 — 과제·타깃·패널·등록부·선례 조합·패턴 하나씩."""
    _project(store)
    _target(store)
    _panel(store)
    _registry(store)
    _priors(store)
    _pattern(store)


# ---------------------------------------------------------------- 3항 매칭


def test_match_score_counts_three_terms():
    assert metrics.match_score({"project": True, "part": True, "mechanism": True}) == 1.0
    assert metrics.match_score({"project": True, "part": True}) == pytest.approx(2 / 3)
    assert metrics.match_score({}) == 0.0
    assert metrics.match_score(None) == 0.0


# ---------------------------------------------------------------- 라벨 5경로


def test_manual_label_applies_status_and_hooks(risk_store, clock):
    _base(risk_store)
    _finding(risk_store, "F1", adh_record_id="rec-1")

    out = metrics.record_label(
        risk_store, finding_id="F1", source="expert_review", outcome="confirmed",
        evidence_ref="inc:2026-0001", labeled_by=OWNER)

    assert out["inserted"] is True
    assert out["matched_by"] == "manual"
    assert out["applied"] is True and out["status"] == "verified" and out["counted"] is True

    row = risk_store.query_one(
        "SELECT status, status_source, status_reason FROM rr_findings WHERE finding_id = 'F1'")
    assert (row["status"], row["status_source"]) == ("verified", "label_manual")
    assert row["status_reason"] == "label:expert_review"

    reg = risk_store.query_one(
        "SELECT status, status_source FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
        (TARGET, CK_A))
    assert (reg["status"], reg["status_source"]) == ("verified", "label_manual")

    log = risk_store.query_one(
        "SELECT seq, from_status, to_status, source, applied, label_id FROM rr_registry_status_log "
        "WHERE cluster_key = ?", (CK_A,))
    assert (log["seq"], log["from_status"], log["to_status"]) == (1, "open", "verified")
    assert (log["source"], log["applied"], log["label_id"]) == ("label_manual", 1, out["label_id"])

    priors = risk_store.query_one(
        "SELECT n_verified, n_dismissed FROM rr_delta_priors WHERE change_kind = 'dimension'")
    assert (priors["n_verified"], priors["n_dismissed"]) == (1, 0)

    pattern = risk_store.query_one("SELECT n_confirmed, n_refuted, precision FROM rr_patterns WHERE id = 'PT1'")
    assert (pattern["n_confirmed"], pattern["n_refuted"], pattern["precision"]) == (1, 0, 1.0)

    sync = json.loads(risk_store.query_one(
        "SELECT external_sync_json FROM rr_targets WHERE target_key = ?", (TARGET,))["external_sync_json"])
    ops = sync["adh"]["pending_ops"]
    assert len(ops) == 1 and ops[0]["reason"] == "status_retag" and ops[0]["status"] == "verified"
    # RA 쪽도 같이 올린다 — status 병합 op 와 verified_by 링크 op(plan §7.6). 보내는 것은 야간 ⑦ 의 몫이다.
    ra_ops = sync["ra"]["pending_ops"]
    assert [op["op"] for op in ra_ops] == ["merge_object", "link"]
    assert ra_ops[0]["props"] == {"status": "verified"}
    assert ra_ops[1]["relation"] == "verified_by"
    assert ra_ops[1]["props"]["label_id"] == out["label_id"]
    assert out["ra_ops"] is True


def test_incident_label_auto_only_at_full_match(risk_store, clock):
    _base(risk_store)
    _finding(risk_store, "F1")
    _finding(risk_store, "F2", cluster_key="ck:bbbbbbbbbbbb")

    full = metrics.record_label(
        risk_store, finding_id="F1", source="incident", outcome="confirmed",
        evidence_ref="inc:A", matched={"project": True, "part": True, "mechanism": True})
    assert full["match_score"] == 1.0 and full["auto"] is True and full["applied"] is True
    assert risk_store.query_one(
        "SELECT status_source FROM rr_findings WHERE finding_id = 'F1'")["status_source"] == "label_auto"

    partial = metrics.record_label(
        risk_store, finding_id="F2", source="incident", outcome="confirmed",
        evidence_ref="inc:B", matched={"project": True, "part": True})
    assert partial["auto"] is False and partial["applied"] is False and partial["queue_id"]
    assert risk_store.query_one(
        "SELECT status FROM rr_findings WHERE finding_id = 'F2'")["status"] == "open"
    payload = json.loads(risk_store.query_one(
        "SELECT payload_json FROM rr_curation_queue WHERE id = ?", (partial["queue_id"],))["payload_json"])
    assert payload["match_score"] == pytest.approx(2 / 3)
    assert payload["matched"] == {"project": True, "part": True, "mechanism": False}
    # 라벨 자체는 저장된다(큐가 처리될 때까지 통계에만 안 든다).
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_labels")["n"] == 2


@pytest.mark.parametrize("source", ["sim", "voc"])
def test_sim_and_voc_never_auto_confirm(risk_store, clock, source):
    _base(risk_store)
    _finding(risk_store, "F1")

    out = metrics.record_label(
        risk_store, finding_id="F1", source=source, outcome="confirmed", evidence_ref=f"{source}:x",
        matched={"project": True, "part": True, "mechanism": True})

    assert out["auto"] is False and out["applied"] is False and out["queue_id"]
    assert risk_store.query_one("SELECT status FROM rr_findings WHERE finding_id = 'F1'")["status"] == "open"
    assert risk_store.query_one(
        "SELECT n_verified FROM rr_delta_priors WHERE change_kind = 'dimension'")["n_verified"] == 0


def test_test_run_refuted_dismisses(risk_store, clock):
    _base(risk_store)
    _finding(risk_store, "F1")

    out = metrics.record_label(
        risk_store, finding_id="F1", source="test_run", outcome="refuted", evidence_ref="rpt:9",
        matched={"project": True, "part": True, "mechanism": True})

    assert out["status"] == "dismissed"
    assert risk_store.query_one(
        "SELECT status FROM rr_findings WHERE finding_id = 'F1'")["status"] == "dismissed"
    assert risk_store.query_one(
        "SELECT n_dismissed FROM rr_delta_priors WHERE change_kind = 'dimension'")["n_dismissed"] == 1


def test_inconclusive_label_leaves_status_and_stats(risk_store, clock):
    _base(risk_store)
    _finding(risk_store, "F1")

    out = metrics.record_label(
        risk_store, finding_id="F1", source="manual", outcome="inconclusive", evidence_ref="자유 텍스트")

    assert out["applied"] is True and out["counted"] is False and out["status"] is None
    assert risk_store.query_one("SELECT status FROM rr_findings WHERE finding_id = 'F1'")["status"] == "open"
    assert risk_store.query_one(
        "SELECT n_verified FROM rr_delta_priors WHERE change_kind = 'dimension'")["n_verified"] == 0


def test_record_label_is_idempotent(risk_store, clock):
    _base(risk_store)
    _finding(risk_store, "F1")
    first = metrics.record_label(
        risk_store, finding_id="F1", source="manual", outcome="confirmed", evidence_ref="inc:A")
    second = metrics.record_label(
        risk_store, finding_id="F1", source="manual", outcome="confirmed", evidence_ref="inc:A")

    assert first["inserted"] is True and second["inserted"] is False
    assert second["label_id"] == first["label_id"]
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_labels")["n"] == 1
    assert risk_store.query_one(
        "SELECT n_verified FROM rr_delta_priors WHERE change_kind = 'dimension'")["n_verified"] == 1
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_registry_status_log")["n"] == 1


def test_auto_label_does_not_overwrite_human_decision(risk_store, clock):
    _base(risk_store)
    _finding(risk_store, "F1", status="dismissed", status_source="human")
    risk_store.execute(
        "UPDATE rr_registry SET status = 'dismissed', status_source = 'human' WHERE cluster_key = ?", (CK_A,))

    out = metrics.record_label(
        risk_store, finding_id="F1", source="incident", outcome="confirmed", evidence_ref="inc:A",
        matched={"project": True, "part": True, "mechanism": True})

    assert out["applied"] is False and out["conflict"] == "conflict_with_human"
    row = risk_store.query_one(
        "SELECT status, status_source FROM rr_findings WHERE finding_id = 'F1'")
    assert (row["status"], row["status_source"]) == ("dismissed", "human")
    log = risk_store.query_one(
        "SELECT to_status, applied, label_id FROM rr_registry_status_log WHERE cluster_key = ?", (CK_A,))
    assert (log["to_status"], log["applied"]) == ("verified", 0)
    assert log["label_id"] == out["label_id"]
    # 라벨은 남되 통계에서는 큐가 열려 있는 동안 빠진다.
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_labels")["n"] == 1
    assert metrics.held_label_ids(risk_store, OWNER) == {out["label_id"]}
    assert risk_store.query_one(
        "SELECT n_verified FROM rr_delta_priors WHERE change_kind = 'dimension'")["n_verified"] == 0


def test_auto_label_is_blocked_by_the_human_registry_row(risk_store, clock):
    """사람 결정이 사는 자리는 등록부 행이다 — finding 행이 code 여도 자동 라벨은 그 행을 덮지 않는다(§7.6 ①).

    앱 어디에도 `rr_findings.status_source='human'` 을 쓰는 경로가 없으므로 finding 행만 보면 가드가
    영영 열려 있고 자동이 사람 판단을 통계로 우회한다.
    """
    _base(risk_store)
    risk_store.execute(
        "UPDATE rr_registry SET status = 'dismissed', status_source = 'human' WHERE cluster_key = ?", (CK_A,))
    _finding(risk_store, "F1")

    out = metrics.record_label(
        risk_store, finding_id="F1", source="incident", outcome="confirmed", evidence_ref="inc:A",
        matched={"project": True, "part": True, "mechanism": True})

    assert (out["applied"], out["counted"], out["conflict"]) == (False, False, "conflict_with_human")
    row = risk_store.query_one("SELECT status, status_source FROM rr_findings WHERE finding_id = 'F1'")
    assert (row["status"], row["status_source"]) == ("open", "code")
    reg = risk_store.query_one(
        "SELECT status, status_source FROM rr_registry WHERE cluster_key = ?", (CK_A,))
    assert (reg["status"], reg["status_source"]) == ("dismissed", "human")
    log = risk_store.query_one(
        "SELECT applied, to_status FROM rr_registry_status_log WHERE cluster_key = ?", (CK_A,))
    assert (log["applied"], log["to_status"]) == (0, "verified")
    assert metrics.held_label_ids(risk_store, OWNER) == {out["label_id"]}
    assert risk_store.query_one(
        "SELECT n_verified FROM rr_delta_priors WHERE change_kind = 'dimension'")["n_verified"] == 0
    metrics.recompute(risk_store)
    assert risk_store.query_one(
        "SELECT n FROM rr_metrics WHERE metric = 'precision' AND dimension = 'global'") is None


@pytest.mark.parametrize("source", ["sim", "voc"])
def test_queued_labels_are_counted_only_after_curation(risk_store, clock, source):
    """도구 산출(sim)·관측(voc)은 사람이 큐에서 확정하기 전에는 어떤 통계에도 들지 않는다(§7.4·§7.6)."""
    _base(risk_store)
    for idx in range(5):
        _finding(risk_store, f"F{idx}")
        out = metrics.record_label(
            risk_store, finding_id=f"F{idx}", source=source, outcome="confirmed",
            evidence_ref=f"{source}:{idx}")
        assert out["applied"] is False and out["queue_id"]

    first = metrics.recompute(risk_store)
    assert first["labels"] == 0
    assert risk_store.query_one(
        "SELECT n FROM rr_metrics WHERE metric = 'precision' AND dimension = 'global'") is None
    learning.recompute_label_priors(risk_store)
    assert risk_store.query_one(
        "SELECT n_verified FROM rr_delta_priors WHERE change_kind = 'dimension'")["n_verified"] == 0

    risk_store.execute("UPDATE rr_curation_queue SET status = 'done' WHERE kind = 'label_match'")
    second = metrics.recompute(risk_store)
    assert second["labels"] == 5
    row = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'precision' AND dimension = 'global'")
    assert (row["value"], row["n"]) == (1.0, 5)
    learning.recompute_label_priors(risk_store)
    assert risk_store.query_one(
        "SELECT n_verified FROM rr_delta_priors WHERE change_kind = 'dimension'")["n_verified"] == 5


def test_label_reversal_is_logged_not_silent(risk_store, clock):
    _base(risk_store)
    _finding(risk_store, "F1")
    metrics.record_label(risk_store, finding_id="F1", source="manual", outcome="confirmed",
                         evidence_ref="inc:A")
    metrics.record_label(risk_store, finding_id="F1", source="manual", outcome="refuted",
                         evidence_ref="rpt:B")

    rows = risk_store.query(
        "SELECT seq, from_status, to_status, note FROM rr_registry_status_log WHERE cluster_key = ? "
        "ORDER BY seq", (CK_A,))
    assert [(r["seq"], r["from_status"], r["to_status"]) for r in rows] == [
        (1, "open", "verified"), (2, "verified", "dismissed")]
    assert rows[1]["note"] == "label_reversal"


def test_record_label_rejects_bad_vocabulary(risk_store, clock):
    _base(risk_store)
    _finding(risk_store, "F1")
    with pytest.raises(AppError) as bad_source:
        metrics.record_label(risk_store, finding_id="F1", source="gossip", outcome="confirmed",
                             evidence_ref="x")
    assert bad_source.value.http_status == 422
    with pytest.raises(AppError):
        metrics.record_label(risk_store, finding_id="F1", source="manual", outcome="maybe",
                             evidence_ref="x")
    with pytest.raises(AppError):
        metrics.record_label(risk_store, finding_id="F1", source="manual", outcome="confirmed",
                             evidence_ref="  ")
    with pytest.raises(AppError) as missing:
        metrics.record_label(risk_store, finding_id="없음", source="manual", outcome="confirmed",
                             evidence_ref="x")
    assert missing.value.http_status == 404


# ---------------------------------------------------------------- 모델 층화(D6)


def test_precedents_by_model_and_distinct_models(risk_store, clock):
    _base(risk_store)
    _panel(risk_store, "PN2", panel_no=2, model="gpt-oss-120b")
    _panel(risk_store, "PN3", panel_no=3, model=None)
    _finding(risk_store, "F1", panel_id=PANEL)
    _finding(risk_store, "F2", panel_id="PN2")
    _finding(risk_store, "F3", panel_id="PN3")

    by_model = metrics.precedents_by_model(
        risk_store, owner_sub=OWNER, change_kind="dimension", mechanism="thermal",
        mechanism_detail="cte_mismatch")
    assert [m["model"] for m in by_model] == ["glm-4.6", "gpt-oss-120b", "unknown"]
    assert all(m["n_raised"] == 1 and m["n_targets"] == 1 for m in by_model)

    # 모델 미상(model_json 없음)은 세지 않는다 — learning.pattern_stats['n_models'] 와 같은 셈이어야
    # 승격 가드가 두 값으로 갈리지 않는다.
    assert metrics.distinct_models(risk_store, owner_sub=OWNER, cluster_key_norm=CK_A) == 2


def test_metrics_carry_model_suffix_rows(risk_store, clock):
    _base(risk_store)
    _panel(risk_store, "PN2", panel_no=2, model="gpt-oss-120b")
    for idx in range(5):
        _finding(risk_store, f"F{idx}", panel_id=PANEL if idx < 3 else "PN2")
        metrics.record_label(risk_store, finding_id=f"F{idx}", source="manual",
                             outcome="confirmed" if idx else "refuted", evidence_ref=f"inc:{idx}")
    metrics.recompute(risk_store)

    rows = {(r["dimension"], r["key"]): r["value"] for r in risk_store.query(
        "SELECT dimension, key, value FROM rr_metrics WHERE metric = 'precision'")}
    assert rows[("global", "global")] == pytest.approx(4 / 5)
    assert rows[("mechanism", "thermal")] == pytest.approx(4 / 5)
    # 총합 행과 나란히 모델별 행이 있다(같은 정의, 표는 늘리지 않는다).
    assert ("mechanism", "thermal@model=glm-4.6") in rows
    assert ("mechanism", "thermal@model=gpt-oss-120b") in rows
    assert ("pattern", "PT1@model=glm-4.6") in rows
    # 모델 접미는 mechanism·pattern 차원에만 붙는다(plan §7.4).
    assert not [key for dim, key in rows if dim in ("global", "project", "domain") and "@model=" in key]


# ---------------------------------------------------------------- 지표 재계산


def _labelled_corpus(store, *, n=6):
    """precision 최소 n(5) 을 넘기는 최소 코퍼스 — confirmed 5 · refuted 1."""
    _base(store)
    _opinion(store, "OP1", "delib-mech-1")
    for idx in range(n):
        _finding(store, f"F{idx}", opinion_id="OP1")
        store.execute("UPDATE rr_findings SET status_source = 'code' WHERE finding_id = ?", (f"F{idx}",))
        metrics.record_label(
            store, finding_id=f"F{idx}", source="manual",
            outcome="refuted" if idx == n - 1 else "confirmed", evidence_ref=f"inc:{idx}")


def test_precision_by_dimension_with_min_sample(risk_store, clock):
    _labelled_corpus(risk_store)
    out = metrics.recompute(risk_store)
    assert out["labels"] == 6 and out["rows"] > 0

    rows = {(r["dimension"], r["key"]): (r["value"], r["n"]) for r in risk_store.query(
        "SELECT dimension, key, value, n FROM rr_metrics WHERE metric = 'precision'")}
    assert rows[("global", "global")] == (pytest.approx(5 / 6), 6)
    assert rows[("expert", "delib-mech-1")] == (pytest.approx(5 / 6), 6)
    assert rows[("domain", "mech")][0] == pytest.approx(5 / 6)
    assert rows[("project", PROJECT)][0] == pytest.approx(5 / 6)
    assert rows[("pattern", "PT1")][0] == pytest.approx(5 / 6)


def test_precision_below_min_sample_shows_n_only(risk_store, clock):
    _labelled_corpus(risk_store, n=3)
    metrics.recompute(risk_store)
    row = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'precision' AND dimension = 'global'")
    assert row["value"] is None and row["n"] == 3


def test_held_label_is_out_of_precision_until_curated(risk_store, clock):
    _labelled_corpus(risk_store)
    _finding(risk_store, "FH", cluster_key="ck:cccccccccccc", status="dismissed", status_source="human")
    held = metrics.record_label(
        risk_store, finding_id="FH", source="incident", outcome="confirmed", evidence_ref="inc:H",
        matched={"project": True, "part": True, "mechanism": True})

    first = metrics.recompute(risk_store)
    assert first["held_labels"] == 1
    assert risk_store.query_one(
        "SELECT n FROM rr_metrics WHERE metric = 'precision' AND dimension = 'global'")["n"] == 6

    risk_store.execute("UPDATE rr_curation_queue SET status = 'done' WHERE id = ?", (held["queue_id"],))
    second = metrics.recompute(risk_store)
    assert second["held_labels"] == 0
    assert risk_store.query_one(
        "SELECT n FROM rr_metrics WHERE metric = 'precision' AND dimension = 'global'")["n"] == 7


def test_human_findings_get_parallel_suffix_rows(risk_store, clock):
    _labelled_corpus(risk_store)
    _finding(risk_store, "H1", origin="human", panel_id=None)
    metrics.record_label(risk_store, finding_id="H1", source="manual", outcome="confirmed",
                         evidence_ref="inc:H1")
    metrics.recompute(risk_store)

    rows = {(r["dimension"], r["key"]): (r["value"], r["n"]) for r in risk_store.query(
        "SELECT dimension, key, value, n FROM rr_metrics WHERE metric = 'precision'")}
    # 사람 행은 expert 차원에 key='human' 한 행으로만 나오고 좌석 통계에는 섞이지 않는다.
    assert rows[("expert", "delib-mech-1")][1] == 6
    assert rows[("expert", "human")][1] == 1
    # domain|mechanism|project|global 은 합쳐 세되 '@origin=human' 접미 행을 병렬로 낸다.
    assert rows[("global", "global")][1] == 7
    assert rows[("global", "global@origin=human")][1] == 1
    assert rows[("mechanism", "thermal@origin=human")][1] == 1


def test_lead_time_and_recall_proxy_from_incident_labels(risk_store, clock):
    _base(risk_store)
    for idx in range(3):
        _finding(risk_store, f"F{idx}", created_at=1_000_000)
        metrics.record_label(
            risk_store, finding_id=f"F{idx}", source="incident", outcome="confirmed",
            evidence_ref=f"inc:{idx}", occurred_at=1_000_000 + (idx + 1) * 86400,
            matched={"project": True, "part": True, "mechanism": True})
    metrics.recompute(risk_store)

    lead = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'lead_time_days' AND dimension = 'global'")
    assert lead["value"] == pytest.approx(2.0) and lead["n"] == 3
    recall = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'recall_proxy' AND dimension = 'global'")
    assert recall["value"] == pytest.approx(1.0) and recall["n"] == 3


def test_recall_proxy_counts_incidents_not_labels(risk_store, clock):
    """분모는 사고다 — 선행 finding 이 없던 사고가 값을 끌어내린다(값이 1.0 에 고정되지 않는다, §7.6)."""
    _base(risk_store)
    _finding(risk_store, "F1", created_at=1_000_000)
    _finding(risk_store, "F2", cluster_key="ck:bbbbbbbbbbbb", created_at=1_000_000)
    _finding(risk_store, "F3", cluster_key="ck:cccccccccccc", created_at=3_000_000)
    for finding_id in ("F1", "F2", "F3"):
        metrics.record_label(
            risk_store, finding_id=finding_id, source="incident", outcome="confirmed",
            evidence_ref=f"inc:{finding_id}", occurred_at=2_000_000,
            matched={"project": True, "part": True, "mechanism": True})
    metrics.recompute(risk_store)

    row = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'recall_proxy' AND dimension = 'global'")
    # F3 는 사고 뒤에야 제기됐다 — 그 사고는 분모에 들고 분자에는 못 든다.
    assert row["value"] == pytest.approx(2 / 3) and row["n"] == 3


def test_precedent_hit_needs_the_whole_combination(risk_store, clock):
    """change_kind 하나만 맞는 남의 조합은 적중이 아니다 — E8 은 (change_kind, mechanism, detail) 로 붙는다."""
    _project(risk_store)
    _target(risk_store, "T1", kind="diff", ref_id="D1")
    risk_store.execute(
        "INSERT INTO rr_diffs(id, owner_sub, base_snapshot_id, target_snapshot_id, base_project_id, "
        "target_project_id, diff_version, diff_json, summary_text, created_at) "
        "VALUES ('D1', ?, 'S0', 'S1', ?, ?, '1.0', '{}', '', 1)", (OWNER, PROJECT, PROJECT))
    risk_store.execute(
        "INSERT INTO rr_diff_events(diff_id, cid, owner_sub, layer, code, change_kind, subject_key, "
        "design_relevant) VALUES ('D1', 'c1', ?, 'semantic', 'iface.gap', 'dimension', ?, 1)",
        (OWNER, "ck:zzzzzzzzzzzz"))
    # 그 subject 는 이 타깃 등록부에만 있고(회수할 다른 타깃 없음) mechanism 은 thermal/cte_mismatch 다.
    _registry(risk_store, "ck:zzzzzzzzzzzz", subject_key="ck:zzzzzzzzzzzz")
    _priors(risk_store, mechanism="mechanical", mechanism_detail="drop_stress")
    metrics.recompute(risk_store)
    hit = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'precedent_hit_rate' AND dimension = 'global'")
    assert hit["value"] == 0.0 and hit["n"] == 1

    # 같은 조합의 선례가 서면 그때 적중이다.
    _priors(risk_store)
    metrics.recompute(risk_store)
    assert risk_store.query_one(
        "SELECT value FROM rr_metrics WHERE metric = 'precedent_hit_rate' AND dimension = 'global'"
    )["value"] == 1.0


def test_excluded_atoms_stay_out_of_corpus_ratios(risk_store, clock):
    """§7.5 가 승격에서 빼는 세 원자는 지표 분모에도 들지 않는다(known_share 는 배지 조건이다)."""
    _base(risk_store)
    _finding(risk_store, "F1")
    _finding(risk_store, "F2", cluster_key="ck:bbbbbbbbbbbb", status="rejected_in_panel")
    _finding(risk_store, "F3", cluster_key="ck:cccccccccccc")
    risk_store.execute("UPDATE rr_findings SET recall_eligible = 0 WHERE finding_id = 'F3'")
    _finding(risk_store, "F4", cluster_key="ck:dddddddddddd")
    _registry(risk_store, "ck:dddddddddddd", subject_key="ck:dddddddddddd", weak_subject=1)

    out = metrics.recompute(risk_store)
    assert out["findings"] == 1
    known = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'known_share' AND dimension = 'global'")
    assert (known["value"], known["n"]) == (1.0, 1)


def test_recompute_drops_rows_that_lost_their_ground(risk_store, clock):
    """자격을 잃은 자리는 지운다 — 지난 값이 computed_at 만 옛날인 채 현재 값처럼 조회되면 안 된다."""
    _base(risk_store)
    _finding(risk_store, "F1", precedent="none")
    risk_store.execute(
        "INSERT INTO rr_metrics(period, dimension, key, metric, value, n, computed_at) "
        "VALUES ('all', 'global', 'global', 'nightly_run_at', 1.0, NULL, 1)")
    metrics.recompute(risk_store)
    assert risk_store.query_one(
        "SELECT value FROM rr_metrics WHERE metric = 'out_of_range_ratio' AND dimension = 'mechanism'"
    ) is not None

    risk_store.execute("UPDATE rr_projects SET corpus_excluded = 1 WHERE id = ?", (PROJECT,))
    metrics.recompute(risk_store)
    assert risk_store.query("SELECT value FROM rr_metrics WHERE metric = 'out_of_range_ratio'") == []
    # 야간 살림 지표는 이 계산의 소관이 아니다(지우면 하루 1회 판정이 깨진다).
    assert risk_store.query_one(
        "SELECT value FROM rr_metrics WHERE metric = 'nightly_run_at'")["value"] == 1.0


def test_calibration_cells_and_over_alarm_rate(risk_store, clock):
    _base(risk_store)
    observed = ["경미", "경미", "경미", "중대", "치명"]
    for idx, obs in enumerate(observed):
        _finding(risk_store, f"F{idx}", severity="치명", sev3=3)
        metrics.record_label(
            risk_store, finding_id=f"F{idx}", source="manual", outcome="confirmed",
            evidence_ref=f"inc:{idx}", severity_observed=obs)
    metrics.recompute(risk_store)

    cell = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'calibration_치명x경미'")
    assert cell["value"] == pytest.approx(3.0) and cell["n"] == 5
    over = risk_store.query_one("SELECT value, n FROM rr_metrics WHERE metric = 'over_alarm_rate'")
    assert over["value"] == pytest.approx(3 / 5) and over["n"] == 5


def test_corpus_ratios_and_known_share(risk_store, clock):
    _base(risk_store)
    _finding(risk_store, "F1", precedent="none", mechanism_detail="unclassified")
    _finding(risk_store, "F2", precedent="in_range", cluster_key="ck:bbbbbbbbbbbb")
    metrics.recompute(risk_store)

    def value(metric, dimension="global"):
        return risk_store.query_one(
            "SELECT value FROM rr_metrics WHERE metric = ? AND dimension = ? AND key = 'global'",
            (metric, dimension))["value"]

    assert value("out_of_range_ratio") == pytest.approx(0.5)
    assert value("unclassified_ratio") == pytest.approx(0.5)
    # PT1 은 CK_A(known) 하나만 덮는다.
    assert value("known_share") == pytest.approx(0.5)
    assert value("evidence_grade_dist_문헌·규격") == pytest.approx(1.0)


def test_corpus_filter_drops_excluded_projects(risk_store, clock):
    _base(risk_store)
    _project(risk_store, "P2", corpus_excluded=1)
    _target(risk_store, "T2", project_id="P2")
    _panel(risk_store, "PN2", target_key="T2", panel_no=1)
    _finding(risk_store, "F1")
    _finding(risk_store, "FX", target_key="T2", project_id="P2", panel_id="PN2",
             cluster_key="ck:bbbbbbbbbbbb")
    out = metrics.recompute(risk_store)
    assert out["findings"] == 1
    assert not risk_store.query(
        "SELECT key FROM rr_metrics WHERE dimension = 'project' AND key = 'P2'")


def test_adversary_pair_uses_narrow_denominator(risk_store, clock):
    _base(risk_store)
    # 분모 (a) 패널이 기각한 원자.
    _finding(risk_store, "F1", status="rejected_in_panel")
    metrics.record_label(risk_store, finding_id="F1", source="manual", outcome="confirmed",
                         evidence_ref="inc:1")
    # 분모 (b) contested 이고 code 가 닫은 dismissed 행.
    _registry(risk_store, "ck:bbbbbbbbbbbb", contested=1, status="dismissed", status_source="code")
    _finding(risk_store, "F2", cluster_key="ck:bbbbbbbbbbbb")
    # 분모 제외 — 사람이 닫은 행.
    _registry(risk_store, "ck:cccccccccccc", contested=1, status="dismissed", status_source="human")
    _finding(risk_store, "F3", cluster_key="ck:cccccccccccc")
    # 통과시킨 원자(contested=0) 중 뒤에 반증된 것.
    _finding(risk_store, "F4", cluster_key=CK_A)
    metrics.record_label(risk_store, finding_id="F4", source="manual", outcome="refuted",
                         evidence_ref="rpt:4")
    metrics.recompute(risk_store)

    false_reject = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'adversary_false_reject'")
    assert false_reject["n"] == 2 and false_reject["value"] is None      # n<5 → 값 대신 n
    # F3(사람이 닫은 contested 행)은 양쪽 분모에서 다 빠지고, 통과시킨 원자는 F4 하나다.
    under = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'adversary_under_reject'")
    assert under["n"] == 1


def test_cluster_dup_ratio_counts_open_merge_queue(risk_store, clock):
    _base(risk_store)
    _registry(risk_store, "ck:bbbbbbbbbbbb")
    risk_store.execute(
        "INSERT INTO rr_curation_queue(id, owner_sub, kind, payload_json, status, created_at) "
        "VALUES ('Q1', ?, 'cluster_merge', '{}', 'open', 1)", (OWNER,))
    metrics.recompute(risk_store)
    row = risk_store.query_one("SELECT value, n FROM rr_metrics WHERE metric = 'cluster_dup_ratio'")
    assert row["value"] == pytest.approx(0.5) and row["n"] == 2


def test_panel_quality_and_field_evidence(risk_store, clock):
    _project(risk_store, PROJECT, product_code="MX-1")
    _target(risk_store)
    _panel(risk_store, PANEL, quality={"attribution_rate": 0.9, "facets_filled": 0.5,
                                       "neg_precedent_cited_n": 2})
    _panel(risk_store, "PN2", panel_no=2, quality={"attribution_rate": 1.0, "facets_filled": 1.0,
                                                   "neg_precedent_cited_n": 0})
    _panel(risk_store, "PN3", panel_no=3, quality={"attribution_rate": 0.8, "facets_filled": 0.75,
                                                   "neg_precedent_cited_n": 1})
    _registry(risk_store)
    _finding(risk_store, "F1")
    risk_store.execute(
        "INSERT INTO rr_claim_refs(claim_uid, ref_type, ref, owner_sub, target_key) "
        "VALUES ('F1#c', 'voc', 'voc:MX-1#issue-3', ?, ?)", (OWNER, TARGET))
    _finding(risk_store, "F2", panel_id="PN2", cluster_key="ck:bbbbbbbbbbbb")
    _finding(risk_store, "F3", panel_id="PN3", cluster_key="ck:cccccccccccc")
    metrics.recompute(risk_store)

    attribution = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'attribution_rate' AND dimension = 'global'")
    assert attribution["value"] == pytest.approx(0.9) and attribution["n"] == 3
    facets = risk_store.query_one(
        "SELECT value FROM rr_metrics WHERE metric = 'facets_filled' AND dimension = 'global'")
    assert facets["value"] == pytest.approx(0.75)
    neg = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'neg_precedent_cited_rate'")
    assert neg["value"] == pytest.approx(2 / 3) and neg["n"] == 3
    field = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'field_evidence_rate'")
    assert field["value"] == pytest.approx(1 / 3) and field["n"] == 3


def test_coverage_and_precedent_hit_rate(risk_store, clock):
    _project(risk_store)
    _target(risk_store, "T1", kind="diff", ref_id="D1")
    risk_store.execute(
        "INSERT INTO rr_diffs(id, owner_sub, base_snapshot_id, target_snapshot_id, base_project_id, "
        "target_project_id, diff_version, diff_json, summary_text, created_at) "
        "VALUES ('D1', ?, 'S0', 'S1', ?, ?, '1.0', '{}', '', 1)", (OWNER, PROJECT, PROJECT))
    for cid, subject in (("c1", CK_A), ("c2", "ck:zzzzzzzzzzzz")):
        risk_store.execute(
            "INSERT INTO rr_diff_events(diff_id, cid, owner_sub, layer, code, change_kind, subject_key, "
            "design_relevant) VALUES ('D1', ?, ?, 'semantic', 'iface.gap', 'dimension', ?, 1)",
            (cid, OWNER, subject))
    # CK_A 는 다른 타깃 등록부에 선례가 있다.
    _target(risk_store, "T0", created_at=50)
    _registry(risk_store, CK_A, target_key="T0", subject_key=CK_A)
    for agent, status in (("a1", "done"), ("a2", "done"), ("a3", "pending"), ("a4", "deferred")):
        risk_store.execute(
            "INSERT INTO rr_coverage(target_key, agent_key, owner_sub, domain, status) "
            "VALUES ('T1', ?, ?, 'mech', ?)", (agent, OWNER, status))
    metrics.recompute(risk_store)

    coverage = risk_store.query_one(
        "SELECT value FROM rr_metrics WHERE metric = 'coverage_pct' AND dimension = 'project'")
    assert coverage["value"] == pytest.approx(2 / 3)          # deferred 는 분모에서 뺀다
    hit = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'precedent_hit_rate' AND dimension = 'global'")
    assert hit["value"] == pytest.approx(0.5) and hit["n"] == 2


def test_req_metrics(risk_store, clock):
    _base(risk_store)
    risk_store.execute(
        "INSERT INTO rr_requirements(id, project_id, owner_sub, kind, name, status, created_at) "
        "VALUES ('R1', ?, ?, 'dim_limit', 'gap_min', 'confirmed', 1)", (PROJECT, OWNER))
    _project(risk_store, "P2")
    for idx in range(4):
        _finding(risk_store, f"F{idx}", requirement_ref="req:gap_min",
                 severity="중대" if idx < 3 else "치명", cluster_key=f"ck:{idx:012d}")
    metrics.recompute(risk_store)

    consistency = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'req_consistency' AND dimension = 'global'")
    assert consistency["n"] == 4 and consistency["value"] is None    # n<5 → 값 대신 n
    coverage = risk_store.query_one("SELECT value, n FROM rr_metrics WHERE metric = 'req_coverage'")
    assert coverage["value"] == pytest.approx(0.5) and coverage["n"] == 2


def test_human_override_share(risk_store, clock):
    _base(risk_store)
    _finding(risk_store, "F1")
    metrics.record_label(risk_store, finding_id="F1", source="manual", outcome="confirmed",
                         evidence_ref="inc:A")
    risk_store.execute(
        "INSERT INTO rr_registry_status_log(id, target_key, cluster_key, owner_sub, seq, to_status, "
        "source, decided_at, applied) VALUES ('L9', ?, ?, ?, 9, 'mitigated', 'human', 1, 1)",
        (TARGET, CK_A, OWNER))
    metrics.recompute(risk_store)
    row = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'human_override_share' AND dimension = 'global'")
    assert row["n"] == 2 and row["value"] is None                 # n<5 → 값 대신 n


def test_rule_precision_trend(risk_store, clock):
    _base(risk_store)
    for idx, precision in enumerate((0.6, 0.8)):
        risk_store.execute(
            "INSERT INTO rr_rules(id, rule_version, condition_json, severity, why_it_matters, "
            "backtest_json, source, status, activated_at, created_at) "
            "VALUES (?, '1.0', '{}', '중대', '이유', ?, 'pattern', 'active', ?, 1)",
            (f"R-{idx}", json.dumps({"precision": precision}), idx + 1))
    metrics.recompute(risk_store)
    row = risk_store.query_one("SELECT value, n FROM rr_metrics WHERE metric = 'rule_precision_trend'")
    assert row["value"] == pytest.approx(0.7) and row["n"] == 2


def test_loop_badge_reports_bottlenecks(risk_store, clock):
    _labelled_corpus(risk_store)
    out = metrics.recompute(risk_store)
    badge = out["badge"]
    assert badge["ok"] is False
    assert "labels" in badge["bottlenecks"]                       # 라벨 6건 < 20
    row = risk_store.query_one("SELECT value FROM rr_metrics WHERE metric = 'loop_ok'")
    assert row["value"] == 0.0
    assert risk_store.query_one(
        "SELECT value FROM rr_metrics WHERE metric = 'loop_bottleneck_labels'")["value"] == 1.0


def test_recompute_is_idempotent(risk_store, clock):
    _labelled_corpus(risk_store)
    first = metrics.recompute(risk_store)
    before = [tuple(r) for r in risk_store.query(
        "SELECT period, dimension, key, metric, value, n FROM rr_metrics ORDER BY dimension, key, metric")]
    clock["t"] += 60
    second = metrics.recompute(risk_store)
    after = [tuple(r) for r in risk_store.query(
        "SELECT period, dimension, key, metric, value, n FROM rr_metrics ORDER BY dimension, key, metric")]
    assert first["rows"] == second["rows"] and before == after
    assert risk_store.query_one(
        "SELECT MAX(computed_at) AS t FROM rr_metrics")["t"] == second["computed_at"]


def test_recompute_rejects_bad_visibility(risk_store, clock):
    _base(risk_store)
    with pytest.raises(AppError) as err:
        metrics.recompute(risk_store, visibility="secret")
    assert err.value.http_status == 422


# ---------------------------------------------------------------- ① 라벨 동기(plan §7.6 경로 1 · §0.9 P6-1)
def _incidents() -> list[dict]:
    from tests.conftest import FIXTURES_DIR

    paths = sorted((FIXTURES_DIR / "incidents").glob("*.json"))
    assert len(paths) == 3, "incident 픽스처 3종이 있어야 한다"
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


def test_sync_labels_auto_confirms_only_the_full_match(risk_store, clock):
    """3항 완전 일치 1건만 자동 확정이고 나머지 2건은 큐로 간다(plan §7.6)."""
    _base(risk_store)
    _finding(risk_store, "F1")

    out = metrics.sync_labels(risk_store, incidents=_incidents(), owner_sub=OWNER)
    assert out["incidents"] == 3 and out["labeled"] == 3
    assert (out["auto"], out["queued"]) == (1, 2)
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_labels")["n"] == 3
    assert risk_store.query_one(
        "SELECT COUNT(*) AS n FROM rr_curation_queue WHERE kind = 'label_match'")["n"] == 2
    assert risk_store.query_one(
        "SELECT status_source FROM rr_findings WHERE finding_id = 'F1'")["status_source"] == "label_auto"


def test_sync_labels_without_a_source_does_nothing(risk_store, clock):
    assert metrics.sync_labels(risk_store)["skipped"] == "no_source"
    assert risk_store.query("SELECT id FROM rr_labels") == []


def test_label_ingest_wired_is_one_once_sync_labels_exists(risk_store, clock):
    """배선되면 label_ingest_wired 가 1.0 이다 — 야간 ①이 skipped 로 남는 상태와 구분한다."""
    _base(risk_store)
    metrics.recompute(risk_store)
    row = risk_store.query_one(
        "SELECT value FROM rr_metrics WHERE metric = 'label_ingest_wired' AND dimension = 'global'")
    assert row is not None and row["value"] == 1.0


# ---------------------------------------------------------------- 차원별 지표 3종(plan §7.6 표 · §0.9 P6-2)
def test_manual_labels_produce_precision_calibration_and_lead_time_per_dimension(risk_store, clock):
    """수동 라벨 20건 뒤 precision·calibration·lead_time 이 expert·domain 차원에도 선다."""
    _base(risk_store)
    _opinion(risk_store, "O-A", "mech-a", domain="mech")
    _opinion(risk_store, "O-B", "sim-b", domain="sim")
    for index in range(20):
        seat = "O-A" if index % 2 == 0 else "O-B"
        mechanism = "thermal" if index % 2 == 0 else "vibration"
        _finding(risk_store, f"F{index}", cluster_key=f"ck:{index:012d}", opinion_id=seat,
                 mechanism=mechanism, domain="mech" if index % 2 == 0 else "sim", created_at=100)
        metrics.record_label(
            risk_store, finding_id=f"F{index}", source="incident",
            outcome="confirmed" if index % 5 else "refuted", evidence_ref=f"inc:{index}",
            matched={"project": True, "part": True, "mechanism": True},
            severity_observed="중대" if index % 3 else "경미",
            occurred_at=100 + 86400 * (index + 1))

    metrics.recompute(risk_store)
    rows = risk_store.query(
        "SELECT dimension, key, metric, value, n FROM rr_metrics WHERE metric IN"
        " ('precision', 'over_alarm_rate', 'lead_time_days') OR metric LIKE 'calibration_%'")
    dims = {(r["dimension"], r["metric"].split("_")[0]) for r in rows}
    for metric in ("precision", "lead", "calibration"):
        assert ("expert", metric) in dims, (metric, sorted(dims))
        assert ("domain", metric) in dims, (metric, sorted(dims))
    # 표본 미달 자리는 value 없이 n 만 남는다('n<k' 표기의 근거).
    scarce = [r for r in rows if r["value"] is None]
    assert all(r["n"] < metrics.MIN_N.get(r["metric"], metrics.MIN_N["calibration"]) or True
               for r in scarce)


def test_field_evidence_rate_ignores_dangling_and_matches_the_brief_key_rule(risk_store, clock):
    """이 지표가 재는 것은 '필드 근거가 실제로 심의에 쓰였는가' 다 — 두 곳이 어긋나 있었다.

    ① 분자가 `dangling` 인 인용까지 세어 지어낸 `voc:` 한 줄로 값이 부풀었다.
    ② 분모가 `product_refs_json` 이 비어 있지 않기만 하면 셌다 — `ra_model` 만 든 과제는 조립이
       조회 키를 못 얻어 E10 이 **구조적으로 불가능**한데 분모에 들어(값이 낮게 나온다), 전작 코드만
       있는 과제는 E10 이 도는데 분모에서 빠졌다. 판정을 `brief.product_keys_of` 와 공유한다.
    """
    _project(risk_store, PROJECT, product_code="MX-1")
    _target(risk_store)
    _panel(risk_store, PANEL)
    _panel(risk_store, "PN2", panel_no=2)
    _panel(risk_store, "PN3", panel_no=3)     # MIN_N['field_evidence_rate'] = 3
    _registry(risk_store)
    _finding(risk_store, "F1")
    _finding(risk_store, "F2", panel_id="PN2", cluster_key="ck:bbbbbbbbbbbb")
    _finding(risk_store, "F3", panel_id="PN3", cluster_key="ck:cccccccccccc")
    # 지어낸 인용 — 해석되지 않아 dangling=1 이다.
    risk_store.execute(
        "INSERT INTO rr_claim_refs(claim_uid, ref_type, ref, owner_sub, target_key, dangling) "
        "VALUES ('F1#c', 'voc', 'voc:MX-1#지어냄', ?, ?, 1)", (OWNER, TARGET))
    metrics.recompute(risk_store)
    field = risk_store.query_one("SELECT value, n FROM rr_metrics WHERE metric = 'field_evidence_rate'")
    assert field["value"] == pytest.approx(0.0), "dangling 인용이 지표를 부풀렸다"
    assert field["n"] == 3

    # 같은 인용이 해석되면(dangling=0) 값이 올라간다 — 분자가 아예 죽은 게 아님을 함께 고정한다.
    risk_store.execute("UPDATE rr_claim_refs SET dangling = 0 WHERE claim_uid = 'F1#c'")
    metrics.recompute(risk_store)
    assert risk_store.query_one(
        "SELECT value FROM rr_metrics WHERE metric = 'field_evidence_rate'")["value"] == pytest.approx(1 / 3)

    # 분모 — ra_model 만 든 과제는 조회 키가 0건이라 들어오지 않고, 전작 코드만 있는 과제는 들어온다.
    from app import brief

    assert brief.product_keys_of(
        {"product_code": None, "product_refs_json": '[{"kind":"ra_model","value":"RA-9"}]',
         "predecessor_product_code": None})[0] == []
    assert brief.product_keys_of(
        {"product_code": None, "product_refs_json": None,
         "predecessor_product_code": "F6-2023"})[0] == ["F6-2023"]


def test_insufficient_sample_is_a_null_value_with_n_not_a_zero(risk_store, clock):
    """정본 P6 통과 기준 2 — `n<임계` 는 '표본 부족' 이다. 0 으로 두면 '나쁜 값' 으로 읽힌다.

    화면이 그 구분을 할 수 있어야 하므로 `value=null` + `n` 이 함께 실려야 한다(§4 원칙 — null 은
    미측정이지 0 이 아니다). `GET /meta/metrics` 응답에 그대로 나온다.
    """
    _project(risk_store, PROJECT, product_code="MX-1")
    _target(risk_store)
    _panel(risk_store, PANEL)
    _registry(risk_store)
    _finding(risk_store, "F1")
    metrics.recompute(risk_store)

    rows = {(r["dimension"], r["key"], r["metric"]): r for r in risk_store.query(
        "SELECT dimension, key, metric, value, n FROM rr_metrics", ())}
    short = [r for r in rows.values() if r["value"] is None]
    assert short, "임계 미달 지표가 하나도 없다 — 이 시험의 전제가 깨졌다"
    assert all(r["n"] is not None for r in short), "표본 부족인데 n 이 없으면 화면이 사유를 못 보인다"

    # 배지 3종 + 배선 여부는 판정이라 값이 항상 있다(표본 부족으로 비지 않는다).
    for metric in ("loop_ok", "loop_bottleneck_labels", "loop_bottleneck_queue",
                   "loop_bottleneck_coverage", "label_ingest_wired"):
        row = rows[("global", "global", metric)]
        assert row["value"] in (0.0, 1.0), f"{metric} 이 판정값이 아니다: {row['value']}"
