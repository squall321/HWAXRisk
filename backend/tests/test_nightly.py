# 야간 잡·큐레이션 큐(plan §7.7) 테스트 — 버전 스탬프·근접 중복 스캔·단계 멱등·비차단 실패·이중 실행 방지
from __future__ import annotations

import json
import time

import pytest

from app import nightly
from app.common import canonical_json

OWNER = "owner@example.com"

# 로컬 02:00(야간 잡 시각 00:30 이후) 과 같은 날 00:10(아직 아님).
NOW = int(time.mktime((2026, 8, 31, 2, 0, 0, 0, 0, -1)))
TOO_EARLY = int(time.mktime((2026, 8, 31, 0, 10, 0, 0, 0, -1)))
NEXT_DAY = int(time.mktime((2026, 9, 1, 2, 0, 0, 0, 0, -1)))


# ---------------------------------------------------------------- 픽스처 헬퍼
def add_part(store, ckey, *, canon="bracket", bucket="1.0x2.0x3.0@v42", material="al"):
    store.execute(
        "INSERT INTO rr_part_keys (ckey, owner_sub, name_norm_canon, geom_bucket, material_norm)"
        " VALUES (?,?,?,?,?)", (ckey, OWNER, canon, bucket, material))


def add_registry(store, cluster_key, *, family="fam1", subject="ck:a", target="T1", status="open",
                 direction="risk"):
    store.execute(
        "INSERT INTO rr_registry (target_key, cluster_key, owner_sub, merged_json, family_key,"
        " subject_key, status, direction) VALUES (?,?,?,?,?,?,?,?)",
        (target, cluster_key, OWNER, "{}", family, subject, status, direction))


def add_finding(store, finding_id, *, mechanism="thermal", detail="unclassified", free="열피로 비슷"):
    store.execute(
        "INSERT INTO rr_findings (finding_id, claim_uid, target_key, project_id, owner_sub, direction,"
        " mechanism, mechanism_detail, mechanism_free, cluster_key, finding_json)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (finding_id, f"P1#{finding_id}", "T1", "PRJ1", OWNER, "risk",
         mechanism, detail, free, "c" * 12, "{}"))


def add_character(store, char_id, *, tags, panels=2, targets=3):
    store.execute(
        "INSERT INTO rr_character (id, project_id, owner_sub, facet, tags_json, statement,"
        " support_panels, support_targets, status) VALUES (?,?,?,?,?,?,?,?,'panel')",
        (char_id, "PRJ1", OWNER, "constraint", canonical_json(tags), "문장", panels, targets))


def add_target(store, target_key="T1", *, sync=None, project="PRJ1"):
    store.execute(
        "INSERT INTO rr_targets (target_key, owner_sub, kind, ref_id, project_id, ir_hash,"
        " external_sync_json) VALUES (?,?,?,?,?,?,?)",
        (target_key, OWNER, "snap", "SNAP1", project, "h" * 12, canonical_json(sync or {})))


def queue_rows(store, kind):
    return store.query(
        "SELECT id, payload_json, status FROM rr_curation_queue WHERE kind = ? ORDER BY created_at, id",
        (kind,))


# ---------------------------------------------------------------- 버전 스탬프(§7.7)
def test_version_stamp_has_all_keys_and_global_values(risk_store):
    stamp = nightly.version_stamp()
    assert set(stamp) == set(nightly.STAMP_KEYS)
    for key in ("taxonomy_version", "rule_version", "planner_version", "ir_version",
                "diff_version", "vocab_version", "lexicon_version", "seat_contract_rev"):
        assert stamp[key], key
    # 타깃 스코프 4키는 target_key 없이는 비어 있다. chair_rev 는 엔진 상수라 앱에 원문이 없다.
    for key in ("adapter_version", "source_app_versions", "persona_rev", "sampling", "chair_rev",
                "injection_lexicon_version"):
        assert stamp[key] is None, key


def test_version_stamp_fills_target_scope(risk_store):
    add_target(risk_store)
    risk_store.execute(
        "INSERT INTO rr_snapshots (id, project_id, owner_sub, ir_version, ir_hash, ir_json,"
        " source_ids_json, kinds_json, missing_json, adapter_versions_json)"
        " VALUES ('SNAP1','PRJ1',?,'1.0','h','{}','[]','[]','{}',?)",
        (OWNER, canonical_json({"mcad": "0.3"})))
    risk_store.execute(
        "INSERT INTO rr_roster (target_key, agent_key, owner_sub, domain, persona_rev)"
        " VALUES ('T1','mech.1',?,'mech','p-7')", (OWNER,))
    stamp = nightly.version_stamp(risk_store, target_key="T1")
    assert stamp["adapter_version"] == {"mcad": "0.3"}
    assert stamp["source_app_versions"] == {"mcad": "0.3"}
    assert stamp["persona_rev"] == "p-7"


def test_versioned_key_suffix():
    stamp = {"taxonomy_version": "1.0"}
    assert nightly.versioned_key("precision", stamp) == "precision@1.0"
    assert nightly.versioned_key("precision", {}) == "precision"


# ---------------------------------------------------------------- ③-0 근접 중복 클러스터
def _near_pair(store):
    add_part(store, "ck:a", bucket="1.0x2.0x3.0@v42")
    add_part(store, "ck:b", bucket="1.0x2.0x3.5@v42")   # size 버킷 한 칸 차이
    add_registry(store, "cl_aaaaaaaa", subject="ck:a")
    add_registry(store, "cl_bbbbbbbb", subject="ck:b")


def test_cluster_merge_scan_queues_pair_without_auto_merge(risk_store):
    _near_pair(risk_store)
    out = nightly.scan_cluster_merge(risk_store, now=NOW)
    assert out == {"n_clusters": 2, "n_pairs": 1, "queued": 1}
    rows = queue_rows(risk_store, "cluster_merge")
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload_json"])
    assert payload["a"] == "cl_aaaaaaaa" and payload["b"] == "cl_bbbbbbbb"
    assert payload["family_key"] == "fam1" and payload["score"] == 0.9
    # 자동 병합은 없다.
    assert risk_store.query("SELECT old_cluster_key FROM rr_cluster_alias") == []
    # cluster_dup_ratio 는 metrics.recompute 가 이 큐를 세어 낸다 — 야간 스캔이 직접 쓰지 않는다.
    assert nightly.metric_value(risk_store, "cluster_dup_ratio") is None


def test_cluster_merge_scan_is_idempotent(risk_store):
    _near_pair(risk_store)
    nightly.scan_cluster_merge(risk_store, now=NOW)
    out = nightly.scan_cluster_merge(risk_store, now=NOW + 60)
    assert out["queued"] == 0
    assert len(queue_rows(risk_store, "cluster_merge")) == 1


def test_cluster_merge_reject_with_suppress_is_not_requeued(risk_store):
    _near_pair(risk_store)
    nightly.scan_cluster_merge(risk_store, now=NOW)
    risk_store.execute(
        "UPDATE rr_curation_queue SET status = 'rejected', decision_json = ? WHERE kind = 'cluster_merge'",
        (canonical_json({"suppress": True}),))
    assert nightly.scan_cluster_merge(risk_store, now=NOW + 60)["queued"] == 0
    assert len(queue_rows(risk_store, "cluster_merge")) == 1


def test_cluster_merge_reject_without_suppress_comes_back(risk_store):
    _near_pair(risk_store)
    nightly.scan_cluster_merge(risk_store, now=NOW)
    risk_store.execute(
        "UPDATE rr_curation_queue SET status = 'rejected', decision_json = ? WHERE kind = 'cluster_merge'",
        (canonical_json({"suppress": False}),))
    assert nightly.scan_cluster_merge(risk_store, now=NOW + 60)["queued"] == 1
    assert len(queue_rows(risk_store, "cluster_merge")) == 2


def test_cluster_merge_skips_far_and_other_family(risk_store):
    add_part(risk_store, "ck:a", material="al")
    add_part(risk_store, "ck:b", material="cu")          # material_norm 이 다르면 근접이 아니다
    add_part(risk_store, "ck:c", bucket="9.0x9.0x9.0@v9")
    add_registry(risk_store, "cl_aaaaaaaa", subject="ck:a")
    add_registry(risk_store, "cl_bbbbbbbb", subject="ck:b")
    add_registry(risk_store, "cl_cccccccc", subject="ck:c", family="fam2")
    out = nightly.scan_cluster_merge(risk_store, now=NOW)
    assert out["n_pairs"] == 0 and out["queued"] == 0


def test_cluster_merge_does_not_pair_risk_with_improvement(risk_store):
    """등록부는 risk 와 improvement 를 따로 세운다 — 같은 subject 라도 병합 후보가 아니다(§4.7.1)."""
    add_part(risk_store, "ck:a")
    add_registry(risk_store, "cl_aaaaaaaa", subject="ck:a", direction="risk")
    add_registry(risk_store, "cl_aaaaaaaa+imp", subject="ck:a", direction="improvement")
    out = nightly.scan_cluster_merge(risk_store, now=NOW)
    assert out["n_pairs"] == 0 and out["queued"] == 0


def test_cluster_merge_skips_alias_merged_pair(risk_store):
    _near_pair(risk_store)
    risk_store.execute(
        "INSERT INTO rr_cluster_alias (old_cluster_key, new_cluster_key, owner_sub, reason,"
        " decided_by, decided_at) VALUES ('cl_bbbbbbbb','cl_aaaaaaaa',?,'cluster_merge',?,?)",
        (OWNER, OWNER, NOW))
    out = nightly.scan_cluster_merge(risk_store, now=NOW)
    assert out["n_clusters"] == 1 and out["n_pairs"] == 0


def test_cluster_merge_scan_disabled_by_setting(risk_store):
    _near_pair(risk_store)
    out = nightly.scan_cluster_merge(risk_store, now=NOW, enabled=False)
    assert out["skipped"]
    assert queue_rows(risk_store, "cluster_merge") == []


def test_alias_cycle_is_counted_not_fixed(risk_store):
    for old, new in (("k1", "k2"), ("k2", "k1")):
        risk_store.execute(
            "INSERT INTO rr_cluster_alias (old_cluster_key, new_cluster_key, owner_sub, reason,"
            " decided_by, decided_at) VALUES (?,?,?,'ckey_merge',?,?)", (old, new, OWNER, OWNER, NOW))
    out = nightly.check_cluster_alias(risk_store, now=NOW)
    assert out["broken"] == ["k1", "k2"]
    assert nightly.metric_value(risk_store, "nightly_cluster_alias_cycle") == 2.0
    assert len(risk_store.query("SELECT old_cluster_key FROM rr_cluster_alias")) == 2


def test_alias_chain_within_limit_is_clean(risk_store):
    for i in range(4):
        risk_store.execute(
            "INSERT INTO rr_cluster_alias (old_cluster_key, new_cluster_key, owner_sub, reason,"
            " decided_by, decided_at) VALUES (?,?,?,'ckey_merge',?,?)",
            (f"k{i}", f"k{i + 1}", OWNER, OWNER, NOW))
    assert nightly.check_cluster_alias(risk_store, now=NOW)["broken"] == []


# ---------------------------------------------------------------- unclassified_code 큐
def test_unclassified_scan_queues_once_with_candidates(risk_store):
    add_finding(risk_store, "F1")
    out = nightly.scan_unclassified(risk_store, now=NOW)
    assert out == {"n_unclassified": 1, "queued": 1}
    payload = json.loads(queue_rows(risk_store, "unclassified_code")[0]["payload_json"])
    assert payload["finding_id"] == "F1" and payload["mechanism_free"] == "열피로 비슷"
    assert "thermal.cte_mismatch" in payload["candidates"]
    assert nightly.scan_unclassified(risk_store, now=NOW + 60)["queued"] == 0


def test_classified_finding_is_not_queued(risk_store):
    add_finding(risk_store, "F1", detail="cte_mismatch")
    assert nightly.scan_unclassified(risk_store, now=NOW)["n_unclassified"] == 0


# ---------------------------------------------------------------- ⑥ x: 태그 승격(character 위임)
def test_x_tag_step_delegates_to_character(risk_store):
    risk_store.execute(
        "INSERT INTO rr_projects (id, owner_sub, code) VALUES ('PRJ1',?,'C1')", (OWNER,))
    add_character(risk_store, "C1", tags=["x:thin_wall"])
    out = nightly.run_nightly(risk_store, now=NOW)
    step = next(s for s in out["steps"] if s["step"] == "x_tags")
    assert step["status"] == "ok" and OWNER in step["result"]


# ---------------------------------------------------------------- ② rr_delta_priors 정합(learning 위임)
def test_delta_priors_step_fixes_drift_then_reports_zero(risk_store):
    risk_store.execute(
        "INSERT INTO rr_delta_contrib (change_kind, mechanism, mechanism_detail, target_key, owner_sub,"
        " n_raised, n_improvement, sev_hist_json, resolving_checks_json, updated_at)"
        " VALUES ('placement','interface','interference','T1',?,3,0,'{}','[]',?)", (OWNER, NOW))
    first = nightly.run_nightly(risk_store, now=NOW)
    step = next(s for s in first["steps"] if s["step"] == "delta_priors")
    assert step["status"] == "ok" and step["result"]["drift"] == 1 and step["result"]["fixed"] == 1
    row = risk_store.query_one(
        "SELECT n_raised, n_targets, stats_version FROM rr_delta_priors"
        " WHERE change_kind='placement' AND mechanism='interface' AND mechanism_detail='interference'")
    assert row["n_raised"] == 3 and row["n_targets"] == 1 and row["stats_version"]
    second = nightly.run_nightly(risk_store, now=NEXT_DAY)
    assert next(s for s in second["steps"] if s["step"] == "delta_priors")["result"]["drift"] == 0


# ---------------------------------------------------------------- ⑦ external_sync 재시도
def _pending(ops, next_at=0):
    return {"ra": {"state": "pending", "attempts": 0, "next_at": next_at, "last_error": None,
                   "done_at": None, "pending_ops": ops},
            "adh": {"state": "done", "attempts": 0, "next_at": 0, "last_error": None,
                    "done_at": None, "pending_ops": []}}


def test_external_sync_counts_due_without_sender(risk_store):
    add_target(risk_store, sync=_pending([{"op": "create_object"}]))
    out = nightly.retry_external_sync(risk_store, now=NOW)
    assert out["due"] == 1 and out["sent"] == 0 and out["skipped"]


def test_external_sync_not_due_yet(risk_store):
    add_target(risk_store, sync=_pending([{"op": "create_object"}], next_at=NOW + 3600))
    assert nightly.retry_external_sync(risk_store, now=NOW)["due"] == 0


def test_external_sync_sends_and_clears(risk_store):
    add_target(risk_store, sync=_pending([{"op": "create_object"}]))
    calls = []

    def send(store, target_key, channel, ops):
        calls.append((target_key, channel, list(ops)))
        return True

    out = nightly.retry_external_sync(risk_store, now=NOW, send=send)
    assert out == {"due": 1, "sent": 1, "failed": 0}
    assert calls[0][:2] == ("T1", "ra")
    from app import ra_client
    assert ra_client.load_external_sync(risk_store, "T1")["ra"]["state"] == "done"


def test_external_sync_failure_backs_off(risk_store):
    add_target(risk_store, sync=_pending([{"op": "create_object"}]))

    def send(store, target_key, channel, ops):
        raise RuntimeError("게이트웨이 불통")

    out = nightly.retry_external_sync(risk_store, now=NOW, send=send)
    assert out == {"due": 1, "sent": 0, "failed": 1}
    from app import ra_client
    entry = ra_client.load_external_sync(risk_store, "T1")["ra"]
    assert entry["attempts"] == 1 and entry["next_at"] > NOW and "게이트웨이 불통" in entry["last_error"]


# ---------------------------------------------------------------- ⑧ rr_id_map 정합
def test_id_map_drift_detects_missing_and_mismatch(risk_store):
    risk_store.execute(
        "INSERT INTO rr_projects (id, owner_sub, code, ra_entity_id) VALUES ('PRJ1',?,'C1',11)", (OWNER,))
    risk_store.executemany(
        "INSERT INTO rr_id_map (portal_kind, portal_id, owner_sub, ra_entity_id) VALUES (?,?,?,?)",
        [("project", "PRJ1", OWNER, 11), ("project", "PRJ2", OWNER, 22)])
    out = nightly.check_id_map(risk_store, now=NOW)
    assert out["n_rows"] == 2
    assert out["drift"] == [{"kind": "project", "portal_id": "PRJ2", "reason": "source_missing"}]

    risk_store.execute("UPDATE rr_projects SET ra_entity_id = 99 WHERE id = 'PRJ1'")
    reasons = {d["reason"] for d in nightly.check_id_map(risk_store, now=NOW)["drift"]}
    assert reasons == {"source_missing", "ra_mismatch"}
    assert nightly.metric_value(risk_store, "nightly_id_map_drift") == 2.0


# ---------------------------------------------------------------- run_nightly(①~⑧)
def test_run_nightly_runs_steps_and_stamps_metrics(risk_store):
    _near_pair(risk_store)
    out = nightly.run_nightly(risk_store, now=NOW)
    assert out["ran"] is True and out["run_at"] == NOW
    names = [s["step"] for s in out["steps"]]
    assert names == ["labels", "delta_priors", "cluster_scan", "patterns", "metrics",
                     "fv_stats", "x_tags", "external_sync", "id_map"]
    assert nightly.metric_value(risk_store, "nightly_run_at") == float(NOW)
    for step in ("delta_priors", "cluster_scan", "patterns", "metrics", "x_tags", "id_map"):
        assert nightly.metric_value(risk_store, f"nightly_{step}_ok") == 1.0
    # ⑦ 은 러너가 sender 를 물려 줄 때만 실제로 보낸다 — 그 전에는 skipped 다.
    assert next(s for s in out["steps"] if s["step"] == "external_sync")["status"] == "skipped"
    assert out["versions"]["taxonomy_version"]
    assert len(queue_rows(risk_store, "cluster_merge")) == 1


def test_run_nightly_skips_unwired_steps_without_metric(risk_store):
    """① 라벨 유입과 ⑤ z-score 통계는 아직 주인이 없다 — 실패(0.0)가 아니라 skipped 로 남는다."""
    out = nightly.run_nightly(risk_store, now=NOW)
    by_name = {s["step"]: s for s in out["steps"]}
    for step in ("labels", "fv_stats"):
        assert by_name[step]["status"] == "skipped"
        assert "미배선" in by_name[step]["result"]["skipped"]
        # 미배선은 행 자체를 만들지 않아 '돌았는데 실패' 와 구분된다.
        assert nightly.metric_value(risk_store, f"nightly_{step}_ok") is None
    # 미배선 사실을 결과 최상단에도 드러낸다 — 라벨 자동 유입 4경로가 아직 없다는 뜻이다.
    assert {"labels", "fv_stats"} <= set(out["unwired"])
    assert nightly.metric_value(risk_store, "label_ingest_wired") == 0.0


def test_metrics_step_is_one_corpus_wide_computation(risk_store):
    """소유자가 둘이어도 지표는 한 번만 계산된다 — 같은 자리를 덮어써 마지막 소유자 값만 남지 않는다."""
    for project_id, owner in (("PRJ1", OWNER), ("PRJ2", "other@example.com")):
        risk_store.execute(
            "INSERT INTO rr_projects (id, owner_sub, code) VALUES (?,?,?)", (project_id, owner, project_id))
    add_finding(risk_store, "F1")
    risk_store.execute(
        "INSERT INTO rr_findings (finding_id, claim_uid, target_key, project_id, owner_sub, direction,"
        " mechanism, mechanism_detail, cluster_key, finding_json)"
        " VALUES ('F2','P1#F2','T2','PRJ2','other@example.com','risk','thermal','cte_mismatch','dddddddddddd','{}')")

    out = nightly.run_nightly(risk_store, now=NOW)
    step = next(s for s in out["steps"] if s["step"] == "metrics")
    assert step["status"] == "ok" and step["result"]["findings"] == 2
    row = risk_store.query_one(
        "SELECT value, n FROM rr_metrics WHERE metric = 'unclassified_ratio' AND dimension = 'global'")
    assert row["n"] == 2      # 두 소유자의 원자가 한 번에 세어진다(앞 소유자 값이 지워지지 않는다)


def test_run_nightly_hook_failure_is_non_blocking(risk_store):
    def boom(store, *, now):
        raise RuntimeError("라벨 원천 불통")

    out = nightly.run_nightly(risk_store, now=NOW, hooks={"labels": boom})
    by_name = {s["step"]: s for s in out["steps"]}
    assert by_name["labels"]["status"] == "failed"
    assert "라벨 원천 불통" in by_name["labels"]["error"]
    assert nightly.metric_value(risk_store, "nightly_labels_ok") == 0.0
    # 뒤 단계는 그대로 돈다.
    assert by_name["id_map"]["status"] == "ok"
    assert nightly.metric_value(risk_store, "nightly_id_map_ok") == 1.0


def test_run_nightly_hook_result_is_reported(risk_store):
    def labels(store, *, now):
        return {"queued": 2, "auto": 1}

    out = nightly.run_nightly(risk_store, now=NOW, hooks={"labels": labels})
    by_name = {s["step"]: s for s in out["steps"]}
    assert by_name["labels"] == {"step": "labels", "status": "ok", "result": {"queued": 2, "auto": 1}}


def test_run_nightly_uses_injected_sender(risk_store):
    add_target(risk_store, sync=_pending([{"op": "create_object"}]))
    out = nightly.run_nightly(risk_store, now=NOW, send=lambda *a: True)
    step = next(s for s in out["steps"] if s["step"] == "external_sync")
    assert step["status"] == "ok" and step["result"] == {"due": 1, "sent": 1, "failed": 0}
    assert nightly.metric_value(risk_store, "nightly_external_sync_ok") == 1.0


def test_run_nightly_does_not_run_twice_a_day(risk_store):
    assert nightly.run_nightly(risk_store, now=NOW)["ran"] is True
    again = nightly.run_nightly(risk_store, now=NOW + 3600)
    assert again == {"ran": False, "reason": "not_due", "last_run_at": NOW, "steps": []}
    assert nightly.run_nightly(risk_store, now=NEXT_DAY)["ran"] is True
    assert nightly.metric_value(risk_store, "nightly_run_at") == float(NEXT_DAY)


def test_run_nightly_force_ignores_the_guard(risk_store):
    nightly.run_nightly(risk_store, now=NOW)
    assert nightly.run_nightly(risk_store, now=NOW + 60, force=True)["ran"] is True


def test_run_nightly_waits_for_00_30(risk_store):
    assert nightly.is_due(risk_store, TOO_EARLY) is False
    assert nightly.run_nightly(risk_store, now=TOO_EARLY)["ran"] is False


def test_run_nightly_metric_rows_do_not_pile_up(risk_store):
    nightly.run_nightly(risk_store, now=NOW)
    before = risk_store.query_one("SELECT COUNT(*) AS n FROM rr_metrics")["n"]
    nightly.run_nightly(risk_store, now=NOW + 60, force=True)
    after = risk_store.query_one("SELECT COUNT(*) AS n FROM rr_metrics")["n"]
    assert before == after


def test_run_nightly_honours_cluster_dup_scan_setting(risk_store):
    _near_pair(risk_store)

    class _S:
        risk_cluster_dup_scan = False

    out = nightly.run_nightly(risk_store, now=NOW, settings=_S())
    step = next(s for s in out["steps"] if s["step"] == "cluster_scan")
    assert step["result"]["cluster_merge"]["skipped"]
    assert queue_rows(risk_store, "cluster_merge") == []


def test_runner_can_call_with_store_and_now(risk_store):
    """runner.py 의 nightly_loop 가 부를 시그니처 — 위치 인자는 store 하나, 나머지는 키워드다."""
    import inspect

    sig = inspect.signature(nightly.run_nightly)
    params = list(sig.parameters.values())
    assert params[0].name == "store"
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params[1:])
    assert nightly.run_nightly(risk_store, now=NOW)["ran"] is True


# ---------------------------------------------------------------- enqueue 계약
def test_enqueue_rejects_unknown_kind(risk_store):
    with pytest.raises(ValueError):
        nightly.enqueue(risk_store, "nope", {}, owner_sub=OWNER, now=NOW)


def test_enqueue_suspect_text_is_deduped_by_sha1(risk_store):
    payload = {"sha1": "a" * 12, "ref": "node:n1", "raw": "…", "lexicon_id": "L1",
               "lexicon_version": "lex-1.0", "first_seen_at": NOW}
    assert nightly.enqueue(risk_store, "suspect_text", payload, owner_sub=OWNER, now=NOW,
                           dedupe=lambda p: p.get("sha1"))
    assert nightly.enqueue(risk_store, "suspect_text", payload, owner_sub=OWNER, now=NOW,
                           dedupe=lambda p: p.get("sha1")) is None
    assert len(queue_rows(risk_store, "suspect_text")) == 1
