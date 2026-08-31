# 학습 루프 시나리오 — 과제를 여러 배치 쌓고 라벨을 넣으면 지표·패턴·브리프가 실제로 좋아지는지 한 번에 본다(plan §7.4~§7.7)
from __future__ import annotations

import dataclasses
import json
import time

import pytest

from app import brief, config, learning, metrics, nightly, registry
from app.errors import AppError
from app.ra_client import empty_sync

OWNER = "loop@example.com"
REVIEWER = "curator@example.com"

# 배치마다 되풀이되는 한 클러스터 — '같은 위험이 과제를 건너뛰며 다시 나온다' 가 학습 루프의 원료다.
CLUSTER = "cl:iface-interference"
SUBJECT = "iface:ck:aaaa1111bbbb|ck:bbbb2222cccc"
COMBO = ("placement", "interface", "interference")

DAY = 86400
T0 = 1_700_000_000

# 로컬 02:00(야간 잡 00:30 이후)과 다음 날 같은 시각.
NIGHT_1 = int(time.mktime((2026, 8, 31, 2, 0, 0, 0, 0, -1)))
NIGHT_2 = int(time.mktime((2026, 9, 1, 2, 0, 0, 0, 0, -1)))

# (배치 번호, 과제, 패널 모델) — 1~3 은 한 모델뿐이고 4 에서 두 번째 모델이 같은 클러스터를 낸다.
BATCHES = (
    (1, "prj_a", "claude-x"),
    (2, "prj_b", "claude-x"),
    (3, "prj_a", "claude-x"),
    (4, "prj_c", "glm-y"),
)
SEATS = ("mech-housing-structure", "xd-a0")

IR = {
    "nodes": [{"nid": "n1", "kind": "part", "name": "HOUSING"}],
    "edges": [{"eid": "e1", "a": "n1", "b": "n1", "kind": "interference",
               "attrs": {"penetration_depth": 0.4}}],
    "warnings": [],
}


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------- 원장 시딩(DDL 컬럼 그대로)


def _project(store, project_id: str, code: str) -> None:
    store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, classification, lifecycle, corpus_excluded, "
        "status, character_status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'internal', 'active', 0, 'active', 'seed', ?, ?)",
        (project_id, OWNER, code, code, T0, T0),
    )


def _snapshot(store, snapshot_id: str, project_id: str, created_at: int) -> None:
    store.execute(
        "INSERT INTO rr_snapshots(id, project_id, owner_sub, ir_version, ir_hash, ir_json, source_ids_json, "
        "kinds_json, node_count, edge_count, missing_json, warnings_n, adapter_versions_json, created_at) "
        "VALUES (?, ?, ?, 'ir-1.0', ?, ?, ?, ?, 1, 1, '[]', 0, ?, ?)",
        (snapshot_id, project_id, OWNER, "h_" + snapshot_id, _j(IR),
         _j([{"kind": "mcad", "app_key": "step_forge", "ref": {"project_id": "42"}}]),
         _j(["mcad"]), _j({"mcad": "1.0"}), created_at),
    )
    store.execute(
        "INSERT INTO rr_states(snapshot_id, owner_sub, state_json, feature_json, rule_hits_json, "
        "character_seed_json, gates_json, summary_text, summary_status, blocked, computed_at) "
        "VALUES (?, ?, '{}', ?, '[]', '{}', ?, ?, 'ok', 0, ?)",
        (snapshot_id, OWNER,
         _j({"names": ["n_parts", "n_iface"], "values": [10.0, 4.0], "known": [True, True]}),
         _j({"G1": {"pass": True}}), f"[개요] {snapshot_id} 스냅샷 요약", created_at),
    )


def _diff_target(store, batch: int, project_id: str, created_at: int) -> str:
    """배치 하나의 diff 타깃(스냅샷 2개·diff·의미 변화 1건)을 심고 target_key 를 돌려준다."""
    base, target = f"s{batch}_base", f"s{batch}_tgt"
    _snapshot(store, base, project_id, created_at)
    _snapshot(store, target, project_id, created_at)
    diff_id = f"d{batch}"
    store.execute(
        "INSERT INTO rr_diffs(id, owner_sub, base_snapshot_id, target_snapshot_id, base_project_id, "
        "target_project_id, pair_kind, diff_version, diff_json, summary_text, summary_status, stats_json, "
        "comparability_json, gates_json, diff_hash, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'same_project_revision', 'diff-1', ?, ?, 'ok', '{}', ?, ?, ?, ?)",
        (diff_id, OWNER, base, target, project_id, project_id,
         _j({"dims_delta": [], "result_delta": []}), f"[의미] 배치 {batch} 에서 배치가 바뀌었다",
         _j({"result_parity": True}), _j({"G1": {"pass": True}}), f"dh{batch}", created_at),
    )
    store.execute(
        "INSERT INTO rr_diff_events(diff_id, cid, owner_sub, layer, code, change_kind, subject_key, "
        "magnitude, unit, confidence, design_relevant, unconfirmed, text) "
        "VALUES (?, ?, ?, 'semantic', 'iface.placement_moved', 'placement', ?, 2.0, 'mm', 'high', 1, 0, ?)",
        (diff_id, f"c:{batch:012d}", OWNER, SUBJECT, "iface.placement_moved 정규 표기"),
    )
    target_key = f"diff:{diff_id}"
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, level, "
        "external_sync_json, created_at, updated_at) VALUES (?, ?, 'diff', ?, ?, ?, 'C0', ?, ?, ?)",
        (target_key, OWNER, diff_id, project_id, "h_" + target, _j(empty_sync()), created_at, created_at),
    )
    return target_key


def _panel_with_findings(store, batch: int, target_key: str, project_id: str, model: str,
                         created_at: int) -> list[str]:
    """좌석 2석이 같은 클러스터를 제기한 패널 1개. 좌석 수·모델 수를 세려면 세 표가 다 필요하다."""
    panel_id = f"pan{batch}"
    store.execute(
        "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, tier, seats_json, chair_template, "
        "rounds, engine, tool_mode, status, model_json, quality_json, created_at) "
        "VALUES (?, ?, ?, 1, 'B', ?, 'risk-review', 3, 'web', 'tools', 'done', ?, ?, ?)",
        (panel_id, target_key, OWNER,
         _j([{"agent_key": key, "domain": "mech", "origin": "primary"} for key in SEATS]),
         _j({"model": model}), _j({"attribution_rate": 0.9, "facets_filled": 6}), created_at),
    )
    finding_ids: list[str] = []
    for seat_no, agent_key in enumerate(SEATS, start=1):
        opinion_id = f"{panel_id}#op{seat_no}"
        store.execute(
            "INSERT INTO rr_seat_opinions(opinion_id, target_key, panel_id, owner_sub, agent_key, domain, "
            "origin, cycle, opinion_json, final_stance, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'mech', 'primary', 1, '{}', 'conditional', ?)",
            (opinion_id, target_key, panel_id, OWNER, agent_key, created_at),
        )
        finding_id = f"{panel_id}#F{seat_no}"
        store.execute(
            "INSERT INTO rr_findings(finding_id, claim_uid, origin, target_key, panel_id, opinion_id, "
            "project_id, owner_sub, direction, domain, mechanism, mechanism_detail, change_kind, "
            "subject_key, severity, sev3, judgement, evidence_grade, precedent, cluster_key, finding_json, "
            "recall_eligible, status, created_at) "
            "VALUES (?, ?, 'llm', ?, ?, ?, ?, ?, 'risk', 'mech', ?, ?, ?, ?, '중대', 2, 'WARNING', "
            "'문헌·규격', 'none', ?, ?, 1, 'open', ?)",
            (finding_id, finding_id, target_key, panel_id, opinion_id, project_id, OWNER,
             COMBO[1], COMBO[2], COMBO[0], SUBJECT, CLUSTER,
             _j({"claim": f"배치 {batch} 에서 계면 간섭이 남아 있다", "primed": False,
                 "feature_snapshot": {"refs": [{"ref": "e:e1", "attrs": {"penetration_depth": 0.4}}]}}),
             created_at),
        )
        finding_ids.append(finding_id)
    return finding_ids


def _seed_projects(store) -> None:
    """과제 3개와 '다음 과제'(배치 5) 타깃 — 배치 1~4 는 시험이 한 배치씩 쌓는다."""
    for project_id, code in (("prj_a", "DV-A"), ("prj_b", "DV-B"), ("prj_c", "DV-C")):
        _project(store, project_id, code)
    _diff_target(store, 5, "prj_b", T0 + 5 * DAY)


def _add_batch(store, batch: int) -> list[str]:
    """배치 하나를 원장에 쌓는다 — 타깃·패널·finding 을 넣고 등록부까지 병합한다.

    등록부 병합에서 rr_delta_contrib·rr_delta_priors(n_raised·n_targets)가 선다.
    """
    _batch, project_id, model = next(b for b in BATCHES if b[0] == batch)
    created_at = T0 + batch * DAY
    target_key = _diff_target(store, batch, project_id, created_at)
    finding_ids = _panel_with_findings(store, batch, target_key, project_id, model, created_at)
    registry.merge(store, target_key, owner_sub=OWNER)
    return finding_ids


def _add_batches(store, upto: int) -> dict[int, list[str]]:
    return {batch: _add_batch(store, batch) for batch, _p, _m in BATCHES if batch <= upto}


# ---------------------------------------------------------------- 읽기 도우미


def _metric(store, metric: str, *, dimension: str = "global", key: str = "global"):
    row = store.query_one(
        "SELECT value, n FROM rr_metrics WHERE period = 'all' AND dimension = ? AND key = ? AND metric = ?",
        (dimension, key, metric),
    )
    return None if row is None else (row["value"], row["n"])


def _priors(store) -> dict:
    row = store.query_one(
        "SELECT n_raised, n_targets, n_verified, n_dismissed FROM rr_delta_priors "
        "WHERE change_kind = ? AND mechanism = ? AND mechanism_detail = ?", COMBO)
    return dict(row) if row is not None else {}


def _e8_line(store, target_key: str) -> str:
    out = brief.build_brief(store, target_key, owner_sub=OWNER)
    item = next(i for i, key in zip(out["evidence"], out["keys"]) if key == "E8")
    return item["result"]


@pytest.fixture
def loop_store(risk_store, monkeypatch):
    """모델 층화 가드를 켠(risk_promote_distinct_models=2) 빈 코퍼스 — 배치는 시험이 직접 쌓는다."""
    monkeypatch.setattr(config, "settings",
                        dataclasses.replace(config.settings, risk_promote_distinct_models=2))
    _seed_projects(risk_store)
    return risk_store


# ---------------------------------------------------------------- 시나리오 본체


def test_batches_accumulate_into_a_better_next_brief(loop_store):
    """배치가 쌓일수록 좋아진다 — 지표 이동·candidate→known 승격·모델 가드·다음 브리프 선례를 한 줄기로 본다.

    (a) 라벨이 들어오면 precision·known_share·lead_time 이 값을 갖는다.
    (b) 패턴은 candidate 까지만 자동으로 오르고 known 은 사람이, rule 은 사람+백테스트가 있어야 한다.
    (c) 서로 다른 모델 2개에서 재현되기 전에는 candidate 조차 서지 않는다.
    (d) 그 선례가 다음 과제의 브리프 E8 에 실제로 실린다.
    """
    store = loop_store

    # ── 0단계. 아무것도 쌓이지 않았을 때 '다음 과제' 브리프에는 실을 선례가 없다.
    assert "[선례 없음" in _e8_line(store, "diff:d5")

    # ── 1단계. 배치 1~3(한 모델뿐) — 타깃·과제·좌석 임계는 찼지만 모델 가드가 승격을 막는다(c).
    findings = _add_batches(store, 3)
    early = learning.mine_patterns(store)
    assert early["created"] == []
    skipped = next(s for s in early["skipped"] if s["cluster_key_norm"] == CLUSTER)
    assert skipped["unmet"] == ["models"], "타깃·과제·좌석은 찼고 모델 수만 모자라야 한다."
    stats_3 = learning.pattern_stats(learning.collect_atoms(store)[CLUSTER],
                                     learning.collect_labels(store).get(CLUSTER, []))
    assert (stats_3["n_targets_independent"], stats_3["n_projects_independent"],
            stats_3["n_experts_independent"], stats_3["n_models"]) == (3, 2, 2, 1)

    # 라벨이 하나도 없을 때의 지표 — 여기가 '움직였다' 의 기준선이다.
    base = metrics.recompute(store)
    assert base["labels"] == 0
    assert _metric(store, "precision") is None, "라벨 0 이면 precision 행 자체가 없다."
    assert _metric(store, "known_share") == (0.0, 6)
    assert _metric(store, "lead_time_days") is None
    assert _priors(store) == {"n_raised": 3, "n_targets": 3, "n_verified": 0, "n_dismissed": 0}

    # ── 2단계. 배치 4 — 두 번째 모델(glm-y)이 같은 클러스터를 내자 가드가 풀리고 candidate 가 선다(c).
    findings[4] = _add_batch(store, 4)
    mined = learning.mine_patterns(store)
    assert [c["cluster_key_norm"] for c in mined["created"]] == [CLUSTER]
    pattern_id = mined["created"][0]["pattern_id"]
    pattern = learning.get_pattern(store, pattern_id)
    assert (pattern["status"], pattern["n_targets"], pattern["n_projects"]) == ("candidate", 4, 3)
    queue = store.query_one(
        "SELECT payload_json FROM rr_curation_queue WHERE kind = 'pattern_candidate' AND status = 'open'", ())
    assert json.loads(queue["payload_json"])["proposal"] == "known", "자동 승격이 아니라 사람에게 올리는 제안이다."

    # ── 3단계. 라벨 6건(현장 3 · 사람 3) — 5경로 단일 입구로만 들어간다.
    incidents = [(1, 10), (2, 20), (3, 30)]
    for batch, lag_days in incidents:
        out = metrics.record_label(
            store, finding_id=findings[batch][0], source="incident", outcome="confirmed",
            evidence_ref=f"inc:2026-{batch:03d}", owner_sub=OWNER,
            matched={"project": True, "part": True, "mechanism": True},
            occurred_at=T0 + batch * DAY + lag_days * DAY, severity_observed="중대")
        assert (out["auto"], out["applied"], out["counted"]) == (True, True, True)
        assert out["match_score"] == 1.0 and out["queue_id"] is None
    manual = metrics.record_label(
        store, finding_id=findings[4][0], source="expert_review", outcome="confirmed",
        evidence_ref="rev:2026-004", owner_sub=OWNER, labeled_by=REVIEWER, severity_observed="중대")
    assert manual["matched_by"] == "manual" and manual["counted"] is True
    for batch in (1, 2):
        metrics.record_label(
            store, finding_id=findings[batch][1], source="expert_review", outcome="refuted",
            evidence_ref=f"rev:2026-1{batch:02d}", owner_sub=OWNER, labeled_by=REVIEWER)

    # 같은 (finding, source, evidence_ref) 재호출은 행도 훅도 늘리지 않는다.
    again = metrics.record_label(
        store, finding_id=findings[1][0], source="incident", outcome="confirmed",
        evidence_ref="inc:2026-001", owner_sub=OWNER,
        matched={"project": True, "part": True, "mechanism": True})
    assert again["inserted"] is False
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_labels", ())["n"] == 6

    # ── 4단계. 지표가 움직인다(a) — 없던 값이 생기고 known_share 는 승격 뒤에 바뀐다.
    after_labels = metrics.recompute(store)
    assert after_labels["labels"] == 6 and after_labels["held_labels"] == 0
    assert _metric(store, "precision") == (pytest.approx(4 / 6), 6), "확정 4 · 반증 2."
    assert _metric(store, "lead_time_days") == (20.0, 3), "median(10·20·30일) 이 값으로 선다."
    assert _priors(store) == {"n_raised": 4, "n_targets": 4, "n_verified": 4, "n_dismissed": 2}
    assert after_labels["badge"]["n_labels"] == 6 > base["badge"]["n_labels"]

    # ── 5단계. 승격은 사람 몫이다(b). 자동 경로는 candidate 에서 멈춘다.
    assert learning.mine_patterns(store)["created"] == []
    assert learning.get_pattern(store, pattern_id)["status"] == "candidate"
    with pytest.raises(AppError) as err:
        learning.promote(store, pattern_id, to_status="known", decided_by="")
    assert err.value.http_status == 422
    assert learning.get_pattern(store, pattern_id)["status"] == "candidate"

    promoted = learning.promote(store, pattern_id, to_status="known", decided_by=REVIEWER)
    assert promoted["gate"]["ok"] is True and promoted["gate"]["by_label"] is True
    assert learning.get_pattern(store, pattern_id)["curated_by"] == REVIEWER

    # known 이 됐다고 rule 이 저절로 서지는 않는다 — 사람 승인도 백테스트도 각각 필요하다.
    assert store.query("SELECT id FROM rr_rules", ()) == []
    with pytest.raises(AppError) as err:
        learning.promote(store, pattern_id, to_status="rule", decided_by="",
                         rule={"why_it_matters": "사람이 쓴 문장"})
    assert err.value.http_status == 422
    with pytest.raises(AppError) as err:
        learning.promote(store, pattern_id, to_status="rule", decided_by=REVIEWER,
                         rule={"why_it_matters": "사람이 쓴 문장"})
    assert err.value.http_status == 422 and "n_labeled" in err.value.message
    assert learning.get_pattern(store, pattern_id)["status"] == "known"
    assert store.query("SELECT id FROM rr_rules", ()) == []

    # 승격이 지표를 다시 움직인다 — known_share 0.0 → 1.0(a).
    after_known = metrics.recompute(store)
    assert _metric(store, "known_share") == (1.0, 8)
    assert after_known["findings"] == 8

    # ── 6단계. 같은 과제·같은 브리프 자리에 이제 선례가 실린다(d) — 0단계의 '[선례 없음]' 이 바뀌었다.
    e8 = _e8_line(store, "diff:d5")
    assert ("placement interface.interference n_raised=4 n_targets=4 "
            "n_verified=4 n_dismissed=2 precision=0.67 (n=6)") in e8
    assert "[선례 없음" not in e8
    seen = brief.precedents(store, "d5", owner_sub=OWNER)
    assert seen["delta_priors"] == [{"change_kind": "placement", "mechanism": "interface",
                                     "mechanism_detail": "interference", "n_raised": 4, "n_targets": 4,
                                     "n_verified": 4, "n_dismissed": 2}]
    assert {"pattern_id": pattern_id, "status": "known"}.items() <= seen["pattern_candidates"][0].items()


# ---------------------------------------------------------------- 야간 잡 멱등


def _fingerprint(store) -> dict:
    """시각 열을 뺀 원장 상태 — 야간 잡을 다시 돌려도 이 값이 그대로여야 한다."""
    return {
        "patterns": [tuple(r) for r in store.query(
            "SELECT id, status, n_findings, n_targets, n_projects, n_experts, n_confirmed, n_refuted, "
            "precision FROM rr_patterns ORDER BY id", ())],
        "queue": [tuple(r) for r in store.query(
            "SELECT kind, payload_json, status FROM rr_curation_queue ORDER BY kind, payload_json", ())],
        "priors": [tuple(r) for r in store.query(
            "SELECT change_kind, mechanism, mechanism_detail, n_raised, n_targets, n_verified, n_dismissed "
            "FROM rr_delta_priors ORDER BY change_kind, mechanism, mechanism_detail", ())],
        "rules": [tuple(r) for r in store.query("SELECT id, status FROM rr_rules ORDER BY id", ())],
        "metrics": [tuple(r) for r in store.query(
            "SELECT dimension, key, metric, value, n FROM rr_metrics WHERE metric NOT LIKE 'nightly_%' "
            "ORDER BY dimension, key, metric", ())],
        "labels": store.query_one("SELECT COUNT(*) AS n FROM rr_labels", ())["n"],
        "findings": [tuple(r) for r in store.query(
            "SELECT finding_id, status, status_source FROM rr_findings ORDER BY finding_id", ())],
    }


def test_nightly_run_twice_lands_on_the_same_ledger(loop_store):
    """야간 잡 ①~⑧ 은 두 번 돌아도 같은 결과다 — 패턴·큐·선례·지표가 한 번 더 쌓이지 않는다."""
    store = loop_store
    findings = _add_batches(store, 4)
    metrics.record_label(
        store, finding_id=findings[1][0], source="expert_review", outcome="confirmed",
        evidence_ref="rev:2026-001", owner_sub=OWNER, labeled_by=REVIEWER)

    first = nightly.run_nightly(store, now=NIGHT_1, settings=config.settings)
    assert first["ran"] is True
    assert [s["status"] for s in first["steps"] if s["step"] in ("delta_priors", "patterns", "metrics")] \
        == ["ok", "ok", "ok"]
    snapshot = _fingerprint(store)
    rows_before = store.query_one("SELECT COUNT(*) AS n FROM rr_metrics", ())["n"]

    # 같은 날 다시 부르면 아예 돌지 않는다(하루 1회 판정).
    assert nightly.run_nightly(store, now=NIGHT_1 + 3600, settings=config.settings)["ran"] is False

    second = nightly.run_nightly(store, now=NIGHT_2, settings=config.settings)
    assert second["ran"] is True
    assert next(s for s in second["steps"] if s["step"] == "delta_priors")["result"]["drift"] == 0
    assert next(s for s in second["steps"] if s["step"] == "patterns")["result"]["created"] == []
    assert _fingerprint(store) == snapshot
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_metrics", ())["n"] == rows_before

    # force 로 한 번 더 돌려도 마찬가지다.
    nightly.run_nightly(store, now=NIGHT_2 + 60, settings=config.settings, force=True)
    assert _fingerprint(store) == snapshot
