# 적중 추적 — 라벨 5경로(rr_labels) 유입·상충 규칙과 rr_metrics 지표 재계산(모델 층화 D6 포함) — plan §7.6·§7.4
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app import common, learning, ra_client, registry
from app.errors import AppError
from app.risk_store import RiskStore

# ---------------------------------------------------------------- 상수(plan §7.6)

# 라벨 유입 5경로. incident=필드 불량 · test_run=시험 결과 · sim=후속 과제 재제기(DynaForge 후속 리포트) ·
# voc=필드 목소리 · expert_review|manual=사람 확정. 어휘는 rr_labels CHECK 과 같다.
LABEL_SOURCES: tuple[str, ...] = ("incident", "test_run", "voc", "sim", "expert_review", "manual")
MANUAL_SOURCES = frozenset({"expert_review", "manual"})
# match_score 1.0 일 때만 자동 확정하는 경로(경로 1·2). sim·voc 는 항상 큐다(도구예측·관측이라 원인 규명이 아니다).
AUTO_SCORED_SOURCES = frozenset({"incident", "test_run"})

OUTCOMES: tuple[str, ...] = ("confirmed", "refuted", "inconclusive")
STATUS_BY_OUTCOME: dict[str, str] = {"confirmed": "verified", "refuted": "dismissed"}

# 훅 우선순위(plan §7.6) — 사람이 정한 행은 자동이 덮지 않는다. 같은 등급이면 최신이 이긴다.
STATUS_RANK: dict[str, int] = {"code": 0, "label_auto": 1, "label_manual": 2, "human": 3}

# 라벨 3항 매칭(경로 1·2) — (a) 제품 일치 (b) part 별칭↔ckey (c) defect category↔mechanism.
MATCH_TERMS: tuple[str, ...] = ("project", "part", "mechanism")

# 지표별 최소 n(plan §7.6 표). n 미달이면 value 를 비우고 n 만 남긴다('n<k' 표기의 근거).
MIN_N: dict[str, int] = {
    "precision": 5,
    "recall_proxy": 3,
    "lead_time_days": 3,
    "calibration": 5,
    "over_alarm_rate": 5,
    "adversary_false_reject": 5,
    "adversary_under_reject": 5,
    "neg_precedent_cited_rate": 3,
    "cluster_dup_ratio": 1,
    "req_consistency": 5,
    "req_coverage": 1,
    "field_evidence_rate": 3,
    "human_override_share": 5,
    "evidence_grade_dist": 1,
    "out_of_range_ratio": 1,
    "unclassified_ratio": 1,
    "coverage_pct": 1,
    "precedent_hit_rate": 1,
    "known_share": 1,
    "rule_precision_trend": 1,
    "attribution_rate": 1,
    "facets_filled": 1,
}

# dimension 어휘(rr_metrics CHECK).
DIMENSIONS: tuple[str, ...] = ("expert", "domain", "mechanism", "pattern", "project", "global")
# 사람·LLM 을 합쳐 세되 '@origin=human' 접미 행을 병렬로 내는 차원(plan §7.6 층화 규칙).
ORIGIN_SUFFIX_DIMS = frozenset({"domain", "mechanism", "pattern", "project", "global"})
# 모델 층화(D6) — '@model=<name>' 접미 행을 총합 행과 병렬로 내는 차원(plan §7.4).
MODEL_SUFFIX_DIMS = frozenset({"mechanism", "pattern"})

# '루프 작동' 배지 임계(plan §7.6 판정 규칙, 최근 5타깃 이동평균).
BADGE_WINDOW = 5
BADGE_THRESHOLDS = {"precedent_hit_rate": 0.5, "known_share": 0.3, "unclassified_ratio": 0.2}
BADGE_MIN_LABELS = 20
BADGE_QUEUE_OPEN_MAX = 29           # open ≥ 30 이면 큐 적체
BADGE_QUEUE_AGE_MAX_S = 14 * 86400  # 최고령 항목 > 14일이면 큐 적체
BADGE_COVERAGE_MIN = 0.5

# 승격 임계에서 빠지는 원자와 같은 필터(plan §7.5) — 패턴 카운트·모델 층화가 같은 집합을 센다.
EXCLUDED_FINDING_STATUS = frozenset({"rejected_in_panel"})

# 관측 severity 3등급(calibration 혼동행렬 축).
SEV_LABELS: tuple[str, ...] = ("경미", "중대", "치명")

_UNCLASSIFIED = "unclassified"


# ---------------------------------------------------------------- 작은 도우미


def _loads(text: Any, default: Any) -> Any:
    """JSON 문자열을 읽는다. None·빈 문자열·깨진 JSON 은 default 로 강등한다."""
    if text is None or text == "":
        return default
    if isinstance(text, (dict, list)):
        return text
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _s(value: Any) -> str:
    return "" if value is None else str(value)


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def match_score(matched: Mapping[str, Any] | None) -> float:
    """3항 매칭(제품·part·mechanism)의 일치 수/3(plan §7.6 경로 1·2). 인자가 없으면 0.0 이다."""
    if not matched:
        return 0.0
    hits = sum(1 for term in MATCH_TERMS if bool(matched.get(term)))
    return round(hits / len(MATCH_TERMS), 6)


# ---------------------------------------------------------------- 라벨 유입(plan §7.6 5경로)

_FINDING_COLUMNS = (
    "finding_id, claim_uid, origin, target_key, panel_id, opinion_id, project_id, owner_sub, direction, "
    "domain, mechanism, mechanism_detail, change_kind, subject_key, severity, sev3, judgement, "
    "evidence_grade, precedent, requirement_ref, cluster_key, status, status_source, recall_eligible, "
    "adh_record_id, created_at"
)


def _finding_row(store: RiskStore, finding_id: str) -> dict:
    row = store.query_one(f"SELECT {_FINDING_COLUMNS} FROM rr_findings WHERE finding_id = ?", (finding_id,))
    if row is None:
        raise AppError("E404", f"finding 을 찾을 수 없습니다 — {finding_id}.", 404)
    return dict(row)


def _next_status_seq(store: RiskStore, target_key: str, cluster_key: str) -> int:
    row = store.query_one(
        "SELECT MAX(seq) AS mx FROM rr_registry_status_log WHERE target_key = ? AND cluster_key = ?",
        (target_key, cluster_key),
    )
    return int((row["mx"] if row is not None and row["mx"] is not None else 0)) + 1


def _registry_keys(store: RiskStore, target_key: str, cluster_key: str) -> list[dict]:
    """그 finding 이 실린 등록부 행(risk 행과 improvement 접미 행 둘 다)."""
    rows = store.query(
        "SELECT cluster_key, status, status_source FROM rr_registry WHERE target_key = ? "
        "AND cluster_key IN (?, ?) ORDER BY cluster_key",
        (target_key, cluster_key, cluster_key + registry.IMPROVEMENT_SUFFIX),
    )
    return [dict(r) for r in rows]


def _queue_conflict(store: RiskStore, *, owner_sub: str, payload: Mapping[str, Any], now: int) -> str:
    queue_id = common.new_uuid()
    store.execute(
        "INSERT INTO rr_curation_queue(id, owner_sub, kind, payload_json, status, created_at) "
        "VALUES (?, ?, 'label_match', ?, 'open', ?)",
        (queue_id, owner_sub, common.canonical_json(dict(payload)), now),
    )
    return queue_id


def _bump_priors(store: RiskStore, finding: Mapping[str, Any], outcome: str, now: int) -> bool:
    """라벨 훅 — 그 finding 조합의 rr_delta_priors n_verified|n_dismissed 를 1 올린다(plan §7.4)."""
    change_kind = _s(finding.get("change_kind"))
    mechanism = _s(finding.get("mechanism"))
    detail = _s(finding.get("mechanism_detail"))
    if not change_kind or not mechanism or not detail:
        return False
    if change_kind in registry.NO_CONTRIB_CHANGE_KINDS:
        return False
    column = "n_verified" if outcome == "confirmed" else "n_dismissed"
    changed = store.execute(
        f"UPDATE rr_delta_priors SET {column} = COALESCE({column}, 0) + 1, updated_at = ? "
        "WHERE change_kind = ? AND mechanism = ? AND mechanism_detail = ?",
        (now, change_kind, mechanism, detail),
    )
    return bool(changed)


def _bump_pattern(store: RiskStore, finding: Mapping[str, Any], pattern_id: str | None,
                  outcome: str, now: int) -> str | None:
    """패턴 카운터 — n_confirmed|n_refuted 와 precision 재계산(plan §7.5)."""
    if pattern_id:
        row = store.query_one(
            "SELECT id, n_confirmed, n_refuted FROM rr_patterns WHERE id = ?", (pattern_id,))
    else:
        # 패턴이 세는 키는 별칭을 거친 대표 키다(plan §7.5) — 원본 cluster_key 로 찾으면 병합 뒤 못 찾는다.
        norm = learning.resolve_cluster_key(store, _s(finding.get("cluster_key")))
        row = store.query_one(
            "SELECT id, n_confirmed, n_refuted FROM rr_patterns WHERE cluster_key_norm = ?", (norm,))
    if row is None:
        return None
    confirmed = int(row["n_confirmed"] or 0) + (1 if outcome == "confirmed" else 0)
    refuted = int(row["n_refuted"] or 0) + (1 if outcome == "refuted" else 0)
    denominator = confirmed + refuted
    precision = round(confirmed / denominator, 6) if denominator else None
    store.execute(
        "UPDATE rr_patterns SET n_confirmed = ?, n_refuted = ?, precision = ?, updated_at = ? WHERE id = ?",
        (confirmed, refuted, precision, now, row["id"]),
    )
    return str(row["id"])


def _queue_retag(store: RiskStore, finding: Mapping[str, Any], status: str) -> bool:
    """AIDataHub 의견 레코드의 status:* 태그 재부착 op(plan §5.6.3·§7.6). 본문 무변경 UPSERT 다."""
    record_id = _s(finding.get("adh_record_id"))
    target_key = _s(finding.get("target_key"))
    if not record_id or not target_key:
        return False
    ra_client.queue_sync_ops(store, target_key, "adh", [{
        "op": "retag",
        "reason": "status_retag",
        "record_id": record_id,
        "finding_id": _s(finding.get("finding_id")),
        "status": status,
    }])
    return True


def _queue_ra_status(store: RiskStore, finding: Mapping[str, Any], *, status: str, label_id: str,
                     source: str, outcome: str, score: float | None, evidence_ref: str) -> bool:
    """RA `risk_finding.status` 병합 op 와 verified_by|refuted_by 링크 op(plan §7.6 경로 1·2).

    보내는 것은 야간 ⑦ 재시도의 몫이고 여기서는 두 op 를 `external_sync.ra.pending_ops` 에 올리기만 한다.
    """
    target_key = _s(finding.get("target_key"))
    if not target_key:
        return False
    link = "verified_by" if outcome == "confirmed" else "refuted_by"
    ops = [{
        "op": "merge_object",
        "reason": "label_status",
        "type": "risk_finding",
        "finding_id": _s(finding.get("finding_id")),
        "props": {"status": status},
    }, {
        "op": "link",
        "reason": "label_link",
        "relation": link,
        "finding_id": _s(finding.get("finding_id")),
        "evidence_ref": evidence_ref,
        "props": {"label_id": label_id, "match_score": score, "source": source},
    }]
    ra_client.queue_sync_ops(store, target_key, "ra", ops)
    return True


def record_label(
    store: RiskStore,
    *,
    finding_id: str,
    source: str,
    outcome: str,
    evidence_ref: str,
    owner_sub: str | None = None,
    matched: Mapping[str, Any] | None = None,
    score: float | None = None,
    severity_observed: str | None = None,
    occurred_at: int | None = None,
    evidence_note: str | None = None,
    labeled_by: str | None = None,
    pattern_id: str | None = None,
) -> dict:
    """라벨 5경로의 단일 입구 — rr_labels 1행 + 상충 규칙에 맞는 훅(plan §7.6).

    경로별 자동 확정. `incident`·`test_run` 은 3항 match_score 가 1.0 일 때만 auto 이고 그 밖은
    `rr_curation_queue(kind='label_match')` 로 간다. `sim`·`voc` 는 점수와 무관하게 항상 큐다(도구예측·관측).
    `expert_review`·`manual` 은 사람이 직접 정한 값이라 matched_by='manual' 로 바로 반영한다.

    상충 규칙. 사람이 정한 행(`status_source='human'`)에 자동 훅이 닿으면 status 를 바꾸지 않고
    `rr_registry_status_log(applied=0)` 1행 + 큐(`conflict='conflict_with_human'`)를 남긴다. 그 라벨은
    `rr_labels` 에 저장되되 큐가 처리될 때까지 precision 분모·`rr_delta_priors` 에 들어가지 않는다.
    같은 등급끼리는 최신이 이기되 전이는 항상 로그로 남는다(나중 라벨이 앞선 것을 조용히 덮지 않는다).

    같은 `(finding_id, source, evidence_ref)` 재호출은 멱등이다 — 새 행도 새 훅도 만들지 않는다.
    """
    if source not in LABEL_SOURCES:
        raise AppError("E100", f"라벨 source 어휘 밖입니다 — {source!r}. 허용 {list(LABEL_SOURCES)}.", 422)
    if outcome not in OUTCOMES:
        raise AppError("E100", f"라벨 outcome 어휘 밖입니다 — {outcome!r}. 허용 {list(OUTCOMES)}.", 422)
    if not _s(evidence_ref).strip():
        raise AppError("E100", "라벨에는 evidence_ref 가 필요합니다(근거 없는 라벨은 만들지 않는다).", 422)

    finding = _finding_row(store, finding_id)
    if owner_sub is not None and _s(finding["owner_sub"]) != owner_sub:
        raise AppError("E404", f"finding 을 찾을 수 없습니다 — {finding_id}.", 404)
    owner = _s(finding["owner_sub"])

    manual = source in MANUAL_SOURCES
    matched_by = "manual" if manual else "auto"
    if score is None:
        score = None if manual else match_score(matched)
    auto_ok = manual or (source in AUTO_SCORED_SOURCES and score is not None and score >= 1.0)

    now = common.now_epoch()
    label_id = common.new_uuid()
    result: dict[str, Any] = {
        "label_id": label_id, "finding_id": finding_id, "source": source, "outcome": outcome,
        "matched_by": matched_by, "match_score": score, "auto": auto_ok, "inserted": True,
        "applied": False, "status": None, "queue_id": None, "conflict": None,
        "counted": False, "priors": False, "pattern_id": None, "retag": False, "ra_ops": False,
    }

    with store.tx():
        existing = store.query_one(
            "SELECT id FROM rr_labels WHERE finding_id = ? AND source = ? AND evidence_ref = ?",
            (finding_id, source, evidence_ref),
        )
        if existing is not None:
            result.update({"label_id": str(existing["id"]), "inserted": False})
            return result

        store.execute(
            "INSERT INTO rr_labels(id, finding_id, pattern_id, project_id, owner_sub, source, outcome, "
            "severity_observed, matched_by, match_score, evidence_ref, evidence_note, occurred_at, "
            "labeled_by, labeled_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (label_id, finding_id, pattern_id, _s(finding["project_id"]), owner, source, outcome,
             severity_observed, matched_by, score, evidence_ref, evidence_note, occurred_at,
             labeled_by or owner, now),
        )

        if not auto_ok:
            payload = {
                "finding_id": finding_id, "label_id": label_id, "source": source, "outcome": outcome,
                "evidence_ref": evidence_ref, "match_score": score,
                "matched": {term: bool((matched or {}).get(term)) for term in MATCH_TERMS},
            }
            result["queue_id"] = _queue_conflict(store, owner_sub=owner, payload=payload, now=now)
            return result

        if outcome == "inconclusive":
            # 확정도 반증도 아니다 — 라벨만 남기고 status·통계는 건드리지 않는다(plan §7.6 precision 정의).
            result["applied"] = True
            result["counted"] = False
            return result

        new_status = STATUS_BY_OUTCOME[outcome]
        new_source = "label_manual" if manual else "label_auto"
        seq = _next_status_seq(store, _s(finding["target_key"]), _s(finding["cluster_key"]))
        registry_before = _registry_keys(store, _s(finding["target_key"]), _s(finding["cluster_key"]))
        # 사람 결정이 사는 자리는 등록부 행(`PUT /api/registry/{cluster}/status`)이다 — 훅 우선순위 ①은
        # 그 행의 status_source 최대 등급으로 판정한다(finding 행만 보면 가드가 영영 열려 있다, plan §7.6).
        sources = [_s(r["status_source"]) or "code" for r in registry_before]
        sources.append(_s(finding["status_source"]) or "code")
        old_source = max(sources, key=lambda s: STATUS_RANK.get(s, 0))
        blocked = STATUS_RANK.get(new_source, 0) < STATUS_RANK.get(old_source, 0)
        basis = {
            "finding_ids": [finding_id], "source": source, "evidence_ref": evidence_ref,
            "match_score": score, "outcome": outcome,
            "from_source": old_source,
            # 반대석 지표(§7.6)가 '기각이 code 로 닫혔던 행' 을 뒤에 되짚을 수 있게 전이 직전 상태를 남긴다.
            "from_registry": {_s(r["cluster_key"]): {"status": _s(r["status"]),
                                                     "source": _s(r["status_source"]) or "code"}
                              for r in registry_before},
        }
        note = "label_reversal" if (not blocked and _s(finding["status"]) in ("verified", "dismissed")
                                    and _s(finding["status"]) != new_status) else None
        store.execute(
            "INSERT INTO rr_registry_status_log(id, target_key, cluster_key, owner_sub, seq, from_status, "
            "to_status, source, decided_by, decided_at, evidence_ref, note, label_id, basis_json, applied) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (common.new_uuid(), _s(finding["target_key"]), _s(finding["cluster_key"]), owner, seq,
             _s(finding["status"]), new_status, new_source, labeled_by or owner, now, evidence_ref,
             note, label_id, common.canonical_json(basis), 0 if blocked else 1),
        )

        if blocked:
            payload = {
                "finding_id": finding_id, "label_id": label_id, "source": source, "outcome": outcome,
                "evidence_ref": evidence_ref, "match_score": score,
                "conflict": "conflict_with_human", "held_status": _s(finding["status"]),
            }
            result["queue_id"] = _queue_conflict(store, owner_sub=owner, payload=payload, now=now)
            result["conflict"] = "conflict_with_human"
            return result

        store.execute(
            "UPDATE rr_findings SET status = ?, status_source = ?, status_decided_by = ?, "
            "status_decided_at = ?, status_reason = ?, updated_at = ? WHERE finding_id = ?",
            (new_status, new_source, labeled_by or owner, now, f"label:{source}", now, finding_id),
        )
        for row in registry_before:
            old_row_source = _s(row["status_source"]) or "code"
            if STATUS_RANK.get(new_source, 0) < STATUS_RANK.get(old_row_source, 0):
                continue
            store.execute(
                "UPDATE rr_registry SET status = ?, status_source = ?, status_decided_by = ?, "
                "status_decided_at = ?, status_basis_json = ?, updated_at = ? "
                "WHERE target_key = ? AND cluster_key = ?",
                (new_status, new_source, labeled_by or owner, now,
                 common.canonical_json(dict(basis, label_id=label_id,
                                            from_status=_s(row["status"]), from_source=old_row_source)),
                 now, _s(finding["target_key"]), row["cluster_key"]),
            )

        result["applied"] = True
        result["status"] = new_status
        result["counted"] = True
        result["priors"] = _bump_priors(store, finding, outcome, now)
        result["pattern_id"] = _bump_pattern(store, finding, pattern_id, outcome, now)
        result["retag"] = _queue_retag(store, finding, new_status)
        result["ra_ops"] = _queue_ra_status(
            store, finding, status=new_status, label_id=label_id, source=source, outcome=outcome,
            score=score, evidence_ref=evidence_ref)

    return result


def label_queue_status(store: RiskStore, owner_sub: str | None = None) -> dict[str, str]:
    """label_match 큐에 오른 라벨 id → 그 큐 행의 status(같은 라벨이 여럿이면 마지막 결정)."""
    sql = ("SELECT payload_json, status, created_at, id FROM rr_curation_queue WHERE kind = 'label_match'")
    params: tuple = ()
    if owner_sub is not None:
        sql += " AND owner_sub = ?"
        params = (owner_sub,)
    out: dict[str, str] = {}
    for row in store.query(sql + " ORDER BY created_at, id", params):
        payload = _loads(row["payload_json"], {})
        label_id = _s(payload.get("label_id"))
        if label_id:
            out[label_id] = _s(row["status"])
    return out


def held_label_ids(store: RiskStore, owner_sub: str | None = None) -> set[str]:
    """사람 판단과 충돌해 큐가 열려 있는 라벨 id — precision 분모에서 빼는 집합(plan §7.6 훅 우선순위 ①)."""
    sql = ("SELECT payload_json FROM rr_curation_queue WHERE kind = 'label_match' AND status = 'open'")
    params: tuple = ()
    if owner_sub is not None:
        sql += " AND owner_sub = ?"
        params = (owner_sub,)
    held: set[str] = set()
    for row in store.query(sql, params):
        payload = _loads(row["payload_json"], {})
        if payload.get("conflict") == "conflict_with_human" and payload.get("label_id"):
            held.add(str(payload["label_id"]))
    return held


def is_counted_label(label: Mapping[str, Any], queue_status: Mapping[str, str]) -> bool:
    """통계에 드는 라벨의 단일 정의 — metrics 지표와 learning 선례·패턴 카운트가 같은 술어를 쓴다.

    사람(expert_review·manual) 또는 match_score 1.0 로 자동 확정된 incident·test_run 만 곧바로 세고,
    큐(label_match)에 오른 라벨은 사람이 `done` 으로 닫은 뒤에야 센다 — `sim`(도구예측)·`voc`(관측)는
    그 전에는 precision·`rr_delta_priors`·`n_confirmed` 어디에도 들어가지 않는다(plan §7.4·§7.6).
    """
    label_id = _s(label.get("id") if label.get("id") is not None else label.get("label_id"))
    status = queue_status.get(label_id)
    if status is not None:
        return status == "done"
    source = _s(label.get("source"))
    if source in MANUAL_SOURCES:
        return True
    score = _f(label.get("match_score"))
    return source in AUTO_SCORED_SOURCES and score is not None and score >= 1.0


# ---------------------------------------------------------------- 모델 층화(D6, plan §7.4)


def panel_models(store: RiskStore, owner_sub: str | None = None) -> dict[str, str]:
    """panel_id → rr_panels.model_json.model. 표를 늘리지 않고 조회 시 조인으로 층화한다."""
    sql = "SELECT id, model_json FROM rr_panels"
    params: tuple = ()
    if owner_sub is not None:
        sql += " WHERE owner_sub = ?"
        params = (owner_sub,)
    out: dict[str, str] = {}
    for row in store.query(sql + " ORDER BY id", params):
        model = _s(_loads(row["model_json"], {}).get("model")).strip()
        if model:
            out[str(row["id"])] = model
    return out


def precedents_by_model(store: RiskStore, *, owner_sub: str, change_kind: str,
                        mechanism: str, mechanism_detail: str) -> list[dict]:
    """`GET /api/precedents` 의 by_model[] — 조합별 총합 옆에 모델별 카운트를 같은 조인으로 낸다.

    저장 표를 늘리지 않는다: rr_findings.panel_id → rr_panels.model_json.model 조인이 전부다.
    """
    models = panel_models(store, owner_sub)
    rows = store.query(
        "SELECT f.finding_id AS finding_id, f.panel_id AS panel_id, f.target_key AS target_key, "
        "f.direction AS direction, f.status AS status FROM rr_findings f "
        "JOIN rr_projects p ON p.id = f.project_id "
        "WHERE f.owner_sub = ? AND f.change_kind = ? AND f.mechanism = ? AND f.mechanism_detail = ? "
        "AND p.status = 'active' AND p.corpus_excluded = 0 ORDER BY f.finding_id",
        (owner_sub, change_kind, mechanism, mechanism_detail),
    )
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        if _s(row["status"]) in EXCLUDED_FINDING_STATUS:
            continue
        model = models.get(_s(row["panel_id"]), "unknown")
        slot = buckets.setdefault(model, {
            "model": model, "n_raised": 0, "n_improvement": 0, "n_verified": 0, "n_dismissed": 0,
            "_targets": set(),
        })
        if _s(row["direction"]) == "improvement":
            slot["n_improvement"] += 1
        else:
            slot["n_raised"] += 1
        slot["_targets"].add(_s(row["target_key"]))
        if _s(row["status"]) == "verified":
            slot["n_verified"] += 1
        elif _s(row["status"]) == "dismissed":
            slot["n_dismissed"] += 1
    out = []
    for model in sorted(buckets):
        slot = buckets[model]
        slot["n_targets"] = len(slot.pop("_targets"))
        out.append(slot)
    return out


def distinct_models(store: RiskStore, *, owner_sub: str, cluster_key_norm: str) -> int:
    """그 패턴의 finding 을 낸 서로 다른 model 수 — Settings risk_promote_distinct_models 가드용(plan §7.4).

    삽입 시 동결된 `cluster_key` 는 별칭 병합 뒤 대표 키와 달라지므로 resolve 를 거쳐 묶고, 모델 미상은
    세지 않는다 — learning.pattern_stats['n_models'] 와 같은 셈이어야 승격 가드가 두 값으로 갈리지 않는다.
    """
    models = panel_models(store, owner_sub)
    rows = store.query(
        "SELECT panel_id, status, cluster_key FROM rr_findings WHERE owner_sub = ? ORDER BY finding_id",
        (owner_sub,),
    )
    cache: dict[str, str] = {}
    seen = {models.get(_s(r["panel_id"]), "") for r in rows
            if _s(r["status"]) not in EXCLUDED_FINDING_STATUS
            and learning.resolve_cluster_key(store, _s(r["cluster_key"]), _cache=cache) == cluster_key_norm}
    return len(seen - {""})


# ---------------------------------------------------------------- 지표 재계산(plan §7.6)


def _corpus_projects(store: RiskStore) -> set[str]:
    """§0.6 코퍼스 필터 — status='active' AND corpus_excluded=0 인 과제만 통계에 든다(정본은 registry)."""
    from app import registry  # noqa: PLC0415 — registry 는 metrics 를 import 하지 않는다.

    return registry.corpus_projects(store)


def _dims_of(atom: Mapping[str, Any]) -> list[tuple[str, str]]:
    """이 원자가 실릴 (dimension, key) 목록 — '@origin=human'·'@model=' 접미 행을 총합 행과 병렬로 낸다."""
    dims: list[tuple[str, str]] = []
    human = atom.get("origin") == "human"
    # expert 차원은 LLM 좌석만 센다. 사람 행은 key='human' 한 행으로 따로 낸다(작성자별 랭킹 없음).
    if human:
        dims.append(("expert", "human"))
    elif atom.get("agent_key"):
        dims.append(("expert", _s(atom["agent_key"])))
    base = [
        ("domain", _s(atom.get("domain")) or _UNCLASSIFIED),
        ("mechanism", _s(atom.get("mechanism")) or _UNCLASSIFIED),
        ("project", _s(atom.get("project_id"))),
        ("global", "global"),
    ]
    if atom.get("pattern_id"):
        base.append(("pattern", _s(atom["pattern_id"])))
    for dim, key in base:
        if not key:
            continue
        dims.append((dim, key))
        if human and dim in ORIGIN_SUFFIX_DIMS:
            dims.append((dim, f"{key}@origin=human"))
        if atom.get("model") and dim in MODEL_SUFFIX_DIMS:
            dims.append((dim, f"{key}@model={atom['model']}"))
    return dims


def _accumulate(atoms: Iterable[Mapping[str, Any]], denom, num, dims: Iterable[str]) -> dict:
    allowed = set(dims)
    acc: dict[tuple[str, str], list[int]] = {}
    for atom in atoms:
        if not denom(atom):
            continue
        hit = 1 if num(atom) else 0
        for dim, key in atom["_dims"]:
            if dim not in allowed:
                continue
            slot = acc.setdefault((dim, key), [0, 0])
            slot[0] += 1
            slot[1] += hit
    return acc


def _emit_ratio(out: list, metric: str, acc: Mapping[tuple[str, str], Sequence[int]]) -> None:
    floor = MIN_N.get(metric, 1)
    for (dim, key) in sorted(acc):
        denominator, numerator = acc[(dim, key)]
        value = round(numerator / denominator, 6) if denominator >= floor else None
        out.append((dim, key, metric, value, denominator))


def _emit(out: list, dim: str, key: str, metric: str, value: float | None, n: int) -> None:
    out.append((dim, key, metric, value if n >= MIN_N.get(metric, 1) else None, n))


def _weak_subject_keys(store: RiskStore) -> set[tuple[str, str]]:
    """등록부가 weak_subject 로 표기한 (target_key, cluster_key) — 승격이 세지 않는 원자와 같은 집합(§7.5)."""
    return {(_s(r["target_key"]), registry.strip_improvement_suffix(_s(r["cluster_key"])))
            for r in store.query(
                "SELECT target_key, cluster_key FROM rr_registry WHERE weak_subject = 1", ())}


def _load_atoms(store: RiskStore) -> list[dict]:
    """코퍼스 안의 finding 원자 — 좌석·모델·패턴 귀속과 `eligible`(§7.5 세는 원자 조건)을 붙여 둔다.

    `eligible=False`(패널이 기각한 것·recall_eligible=0·weak_subject)는 승격이 세지 않는 원자와 같고,
    지표도 그것을 뺀 집합에서 센다 — 예외는 반대석 지표뿐이다(기각 원자가 그 분모다).
    """
    corpus = _corpus_projects(store)
    models = panel_models(store)
    weak = _weak_subject_keys(store)
    seats = {str(r["opinion_id"]): _s(r["agent_key"]) for r in store.query(
        "SELECT opinion_id, agent_key FROM rr_seat_opinions", ())}
    patterns = {_s(r["cluster_key_norm"]): str(r["id"]) for r in store.query(
        "SELECT id, cluster_key_norm, status FROM rr_patterns", ())}
    known = {_s(r["cluster_key_norm"]) for r in store.query(
        "SELECT cluster_key_norm FROM rr_patterns WHERE status IN ('known','rule','predictor')", ())}
    cited = {str(r["claim_uid"]) for r in store.query(
        "SELECT claim_uid FROM rr_claim_refs WHERE ref LIKE 'voc:%' OR ref LIKE 'paper:%'", ())}

    cache: dict[str, str] = {}
    atoms: list[dict] = []
    for row in store.query(f"SELECT {_FINDING_COLUMNS} FROM rr_findings ORDER BY finding_id", ()):
        atom = dict(row)
        if _s(atom["project_id"]) not in corpus:
            continue
        cluster = _s(atom["cluster_key"])
        norm = learning.resolve_cluster_key(store, cluster, _cache=cache)
        atom["cluster_key_norm"] = norm
        atom["agent_key"] = seats.get(_s(atom["opinion_id"]), "")
        atom["model"] = models.get(_s(atom["panel_id"]), "")
        atom["pattern_id"] = patterns.get(norm, "")
        atom["known"] = norm in known
        atom["field_cited"] = _s(atom["claim_uid"]) in cited
        atom["eligible"] = (
            _s(atom["status"]) not in EXCLUDED_FINDING_STATUS
            and int(atom["recall_eligible"] or 0) == 1
            and (_s(atom["target_key"]), registry.strip_improvement_suffix(cluster)) not in weak
        )
        atom["_dims"] = _dims_of(atom)
        atoms.append(atom)
    return atoms


def _label_rows(store: RiskStore) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT id, finding_id, source, outcome, severity_observed, matched_by, match_score, evidence_ref, "
        "occurred_at, labeled_at FROM rr_labels ORDER BY id", ())]


def _label_atoms(atoms: Sequence[Mapping[str, Any]], labels: Sequence[Mapping[str, Any]],
                 queue_status: Mapping[str, str]) -> list[dict]:
    """라벨 원자 — 그 finding 의 차원을 승계한다. 통계에 들지 않는 라벨(큐 미결·sim·voc)은 빠진다."""
    by_id = {_s(a["finding_id"]): a for a in atoms}
    out: list[dict] = []
    for label in labels:
        if not is_counted_label(label, queue_status):
            continue
        parent = by_id.get(_s(label["finding_id"]))
        if parent is None:
            continue
        item = dict(label)
        item["_dims"] = parent["_dims"]
        item["_finding"] = parent
        out.append(item)
    return out


def _precision_rows(out: list, label_atoms: Sequence[Mapping[str, Any]]) -> None:
    acc = _accumulate(
        label_atoms,
        lambda a: a["outcome"] in ("confirmed", "refuted"),
        lambda a: a["outcome"] == "confirmed",
        DIMENSIONS,
    )
    _emit_ratio(out, "precision", acc)


# 선행시간·보정도가 나는 차원(plan §7.6 표 — 전문가·도메인도 자기 층을 갖는다).
LEAD_TIME_DIMS: tuple[str, ...] = ("global", "project", "mechanism", "expert", "domain")
CALIBRATION_DIMS: tuple[str, ...] = ("global", "expert", "domain", "mechanism")


def _lead_time_rows(out: list, label_atoms: Sequence[Mapping[str, Any]]) -> None:
    """median(incident.occurred_on − finding.created_at) 일수(plan §7.6)."""
    buckets: dict[tuple[str, str], list[float]] = {}
    for label in label_atoms:
        if label["source"] != "incident" or label["outcome"] != "confirmed":
            continue
        occurred = label.get("occurred_at")
        created = label["_finding"].get("created_at")
        if occurred is None or created is None:
            continue
        days = (float(occurred) - float(created)) / 86400.0
        for dim, key in label["_dims"]:
            if dim not in LEAD_TIME_DIMS:
                continue
            buckets.setdefault((dim, key), []).append(days)
    floor = MIN_N["lead_time_days"]
    for dim, key in sorted(buckets):
        values = buckets[(dim, key)]
        value = round(_median(values), 6) if len(values) >= floor else None
        out.append((dim, key, "lead_time_days", value, len(values)))


def _recall_proxy_rows(out: list, atoms: Sequence[Mapping[str, Any]],
                       label_atoms: Sequence[Mapping[str, Any]]) -> None:
    """심사 과제에서 관측된 incident 중 선행 finding 이 있던 비율(plan §7.6).

    분모는 라벨이 아니라 **사고**다 — 지금 코퍼스가 아는 사고 원천은 `incident` 라벨의 서로 다른
    `evidence_ref` 뿐이라 그것을 센다(경로 1 자동 유입이 붙으면 매칭 실패 사고까지 같은 자리로 들어온다).
    분자는 같은 cluster_key_norm·같은 mechanism 의 finding 이 발생 시각 이전에 있었는지다.
    """
    prior: dict[tuple[str, str], list[float]] = {}
    for atom in atoms:
        if not atom["eligible"] or atom.get("created_at") is None:
            continue
        prior.setdefault((_s(atom["cluster_key_norm"]), _s(atom["mechanism"])), []).append(
            float(atom["created_at"]))

    seen: dict[tuple[str, str], set[str]] = {}
    acc: dict[tuple[str, str], list[int]] = {}
    for label in label_atoms:
        if label["source"] != "incident" or label.get("occurred_at") is None:
            continue
        parent = label["_finding"]
        occurred = float(label["occurred_at"])
        key_pair = (_s(parent["cluster_key_norm"]), _s(parent["mechanism"]))
        lead = any(created <= occurred for created in prior.get(key_pair, ()))
        incident_ref = _s(label.get("evidence_ref")) or _s(label.get("id"))
        for dim, key in label["_dims"]:
            if dim not in ("global", "project"):
                continue
            marks = seen.setdefault((dim, key), set())
            if incident_ref in marks:
                continue
            marks.add(incident_ref)
            slot = acc.setdefault((dim, key), [0, 0])
            slot[0] += 1
            slot[1] += 1 if lead else 0
    _emit_ratio(out, "recall_proxy", acc)


def _calibration_rows(out: list, label_atoms: Sequence[Mapping[str, Any]]) -> None:
    """예측 sev3 × 관측 severity_observed 3×3 혼동행렬. rr_metrics 에 열을 늘리지 않으려 셀별 행으로 편다."""
    cells: dict[tuple[str, str, str], int] = {}
    totals: dict[tuple[str, str], int] = {}
    over: dict[tuple[str, str], list[int]] = {}
    for label in label_atoms:
        observed = _s(label.get("severity_observed"))
        if observed not in SEV_LABELS:
            continue
        sev3 = label["_finding"].get("sev3")
        predicted = SEV_LABELS[int(sev3) - 1] if isinstance(sev3, int) and 1 <= int(sev3) <= 3 else None
        if predicted is None:
            continue
        for dim, key in label["_dims"]:
            if dim not in CALIBRATION_DIMS:
                continue
            cells[(dim, key, f"calibration_{predicted}x{observed}")] = \
                cells.get((dim, key, f"calibration_{predicted}x{observed}"), 0) + 1
            totals[(dim, key)] = totals.get((dim, key), 0) + 1
            bucket = over.setdefault((dim, key), [0, 0])
            if predicted == "치명":
                bucket[1] += 1
                bucket[0] += 1 if observed == "경미" else 0
    if not totals:
        return
    for dim, key, metric in sorted(cells):
        total = totals[(dim, key)]
        enough = total >= MIN_N["calibration"]
        out.append((dim, key, metric, float(cells[(dim, key, metric)]) if enough else None, total))
    for dim, key in sorted(over):
        num, den = over[(dim, key)]
        value = round(num / den, 6) if den >= MIN_N["over_alarm_rate"] else None
        out.append((dim, key, "over_alarm_rate", value, den))


def _corpus_ratio_rows(out: list, atoms: Sequence[Mapping[str, Any]]) -> None:
    _emit_ratio(out, "out_of_range_ratio", _accumulate(
        atoms, lambda a: True, lambda a: _s(a["precedent"]) in ("none", "out_of_range"),
        ("global", "mechanism")))
    _emit_ratio(out, "unclassified_ratio", _accumulate(
        atoms, lambda a: True, lambda a: _s(a["mechanism_detail"]) == _UNCLASSIFIED,
        ("global", "domain")))
    _emit_ratio(out, "known_share", _accumulate(
        atoms, lambda a: True, lambda a: bool(a["known"]), ("global", "mechanism", "project")))
    grades: dict[str, int] = {}
    for atom in atoms:
        grade = _s(atom["evidence_grade"])
        if grade:
            grades[grade] = grades.get(grade, 0) + 1
    total = sum(grades.values())
    for grade in sorted(grades):
        out.append(("global", "global", f"evidence_grade_dist_{grade}",
                    round(grades[grade] / total, 6), total))


def _req_rows(out: list, atoms: Sequence[Mapping[str, Any]]) -> None:
    """req_consistency — 같은 요구 이름·같은 위반 방향에서 다수 severity 와 일치하는 비율(plan §7.6)."""
    votes: dict[str, dict[str, int]] = {}
    for atom in atoms:
        if not _s(atom["requirement_ref"]):
            continue
        bucket = votes.setdefault(_s(atom["requirement_ref"]), {})
        severity = _s(atom["severity"]) or _UNCLASSIFIED
        bucket[severity] = bucket.get(severity, 0) + 1
    # 요구별 finding 이 1건이면 그 1건이 곧 다수라 '갈리지 않았다' 를 판정할 수 없다 — 분모에서 뺀다.
    votes = {ref: bucket for ref, bucket in votes.items() if sum(bucket.values()) >= 2}
    graded = [a for a in atoms if _s(a["requirement_ref"]) in votes]
    majority = {ref: max(sorted(bucket), key=lambda s: bucket[s]) for ref, bucket in votes.items()}
    _emit_ratio(out, "req_consistency", _accumulate(
        graded, lambda a: True,
        lambda a: (_s(a["severity"]) or _UNCLASSIFIED) == majority.get(_s(a["requirement_ref"])),
        ("global", "mechanism")))


def _field_evidence_rows(out: list, store: RiskStore, atoms: Sequence[Mapping[str, Any]]) -> None:
    """E10 이 실릴 수 있는(제품 연결이 있는) 과제의 패널 중 voc:·paper: 를 인용한 finding 이 있는 비율."""
    linked = set()
    for row in store.query(
        "SELECT id, product_code, product_refs_json FROM rr_projects "
        "WHERE status = 'active' AND corpus_excluded = 0", ()
    ):
        if _s(row["product_code"]).strip() or _loads(row["product_refs_json"], []):
            linked.add(str(row["id"]))
    panels: dict[str, bool] = {}
    for atom in atoms:
        if _s(atom["project_id"]) not in linked:
            continue
        panel_id = _s(atom["panel_id"])
        if not panel_id:
            continue
        panels[panel_id] = panels.get(panel_id, False) or bool(atom["field_cited"])
    total = len(panels)
    hits = sum(1 for cited in panels.values() if cited)
    value = round(hits / total, 6) if total >= MIN_N["field_evidence_rate"] else None
    out.append(("global", "global", "field_evidence_rate", value, total))


def _adversary_rows(out: list, store: RiskStore, atoms: Sequence[Mapping[str, Any]],
                    labels_by_cluster: Mapping[str, list]) -> None:
    """반대석 지표 짝(plan §7.6) — 분모에서 사람이 닫은 행을 뺀다(훅 우선순위 ③).

    분모는 '반대석 기각이 실제로 반영됐던' 원자이므로 뒤에 라벨이 status 를 되돌린 행도 남는다 —
    되돌리기 전 상태는 `rr_registry_status_log.basis_json`(from_status·from_registry)이 갖고 있다.
    """
    registry_rows = {}
    for row in store.query(
        "SELECT target_key, cluster_key, contested, status, status_source, merged_json FROM rr_registry "
        "ORDER BY target_key, cluster_key", ()
    ):
        registry_rows[(_s(row["target_key"]), _s(row["cluster_key"]))] = dict(row)

    def _reg_of(atom):
        key = (_s(atom["target_key"]), _s(atom["cluster_key"]))
        return registry_rows.get(key) or registry_rows.get(
            (key[0], key[1] + registry.IMPROVEMENT_SUFFIX))

    def _later(atom: Mapping[str, Any], outcome: str) -> bool:
        """분자는 finding_id 가 아니라 대표 클러스터로 묶는다 — 기각된 뒤 다음 타깃에서 새 finding_id 로
        재제기돼 거기서 확정되는 것이 정상 경로다(plan §7.6 '별칭 resolve 후 같은 클러스터 포함')."""
        created = float(atom.get("created_at") or 0)
        return any(_s(row["outcome"]) == outcome and float(row.get("labeled_at") or 0) >= created
                   for row in labels_by_cluster.get(_s(atom["cluster_key_norm"]), []))

    label_finding = {str(r["id"]): _s(r["finding_id"]) for r in store.query(
        "SELECT id, finding_id FROM rr_labels", ())}
    was_rejected: set[str] = set()
    was_code_dismissed: set[tuple[str, str]] = set()
    for row in store.query(
        "SELECT target_key, cluster_key, from_status, label_id, basis_json FROM rr_registry_status_log "
        "WHERE applied = 1", ()
    ):
        if _s(row["from_status"]) in EXCLUDED_FINDING_STATUS and row["label_id"]:
            finding_id = label_finding.get(str(row["label_id"]), "")
            if finding_id:
                was_rejected.add(finding_id)
        before = _loads(row["basis_json"], {}).get("from_registry") or {}
        if isinstance(before, dict):
            for cluster_key, state in before.items():
                if isinstance(state, dict) and state.get("status") == "dismissed" \
                        and state.get("source") == "code":
                    was_code_dismissed.add((_s(row["target_key"]), _s(cluster_key)))

    false_den = false_num = 0
    under_den = under_num = 0
    for atom in atoms:
        reg = _reg_of(atom)
        contested = int((reg or {}).get("contested") or 0)
        rejected_here = _s(atom["status"]) in EXCLUDED_FINDING_STATUS \
            or _s(atom["finding_id"]) in was_rejected
        reg_key = (_s(atom["target_key"]), _s((reg or {}).get("cluster_key")))
        code_dismissed = contested >= 1 and (
            (bool(reg) and _s(reg["status"]) == "dismissed" and _s(reg["status_source"]) == "code")
            or reg_key in was_code_dismissed)
        if rejected_here or code_dismissed:
            false_den += 1
            false_num += 1 if _later(atom, "confirmed") else 0
        elif contested == 0:
            under_den += 1
            under_num += 1 if _later(atom, "refuted") else 0
    _emit(out, "global", "global", "adversary_false_reject",
          round(false_num / false_den, 6) if false_den else None, false_den)
    _emit(out, "global", "global", "adversary_under_reject",
          round(under_num / under_den, 6) if under_den else None, under_den)


def _cluster_dup_rows(out: list, store: RiskStore) -> None:
    """야간 ③-0 스캔이 올린 미병합 근접 쌍(open cluster_merge 큐) / 전체 클러스터 수(plan §4.3.2)."""
    total = store.query_one("SELECT COUNT(DISTINCT cluster_key) AS n FROM rr_registry", ())
    clusters = int((total["n"] if total is not None else 0) or 0)
    pairs = store.query_one(
        "SELECT COUNT(*) AS n FROM rr_curation_queue WHERE kind = 'cluster_merge' AND status = 'open'", ())
    n_pairs = int((pairs["n"] if pairs is not None else 0) or 0)
    value = round(n_pairs / clusters, 6) if clusters else None
    out.append(("global", "global", "cluster_dup_ratio", value, clusters))


def _human_override_rows(out: list, store: RiskStore) -> None:
    rows = store.query(
        "SELECT l.source AS source, t.project_id AS project_id FROM rr_registry_status_log l "
        "LEFT JOIN rr_targets t ON t.target_key = l.target_key WHERE l.applied = 1", ())
    acc: dict[tuple[str, str], list[int]] = {}
    for row in rows:
        hit = 1 if _s(row["source"]) == "human" else 0
        for dim, key in (("global", "global"), ("project", _s(row["project_id"]))):
            if not key:
                continue
            slot = acc.setdefault((dim, key), [0, 0])
            slot[0] += 1
            slot[1] += hit
    _emit_ratio(out, "human_override_share", acc)


def _target_rows(out: list, store: RiskStore) -> dict[str, dict]:
    """타깃별 coverage_pct·precedent_hit_rate 를 내고 배지 계산용 최근 타깃 값을 돌려준다."""
    targets = [dict(r) for r in store.query(
        "SELECT target_key, project_id, kind, ref_id, created_at FROM rr_targets "
        "ORDER BY created_at, target_key", ())]
    corpus = _corpus_projects(store)
    targets = [t for t in targets if _s(t["project_id"]) in corpus]

    coverage: dict[str, list[int]] = {}
    for row in store.query("SELECT target_key, status FROM rr_coverage", ()):
        slot = coverage.setdefault(_s(row["target_key"]), [0, 0])
        if _s(row["status"]) == "deferred":
            continue
        slot[0] += 1
        slot[1] += 1 if _s(row["status"]) in registry.TERMINAL_STATUSES else 0

    # 적중은 E5·E8 이 실제로 붙는 단위로만 센다 — (a) 그 subject 를 가리키는 다른 타깃의 등록부 행(E5 회수)
    # 또는 (b) 그 subject 의 (mechanism, mechanism_detail) 과 이번 change_kind 의 조합 선례(E8, §7.4).
    subject_targets: dict[str, set[str]] = {}
    subject_combos: dict[str, set[tuple[str, str]]] = {}
    for row in store.query(
        "SELECT target_key, subject_key, mechanism, mechanism_detail FROM rr_registry", ()
    ):
        subject = _s(row["subject_key"])
        subject_targets.setdefault(subject, set()).add(_s(row["target_key"]))
        if _s(row["mechanism"]):
            subject_combos.setdefault(subject, set()).add(
                (_s(row["mechanism"]), _s(row["mechanism_detail"])))
    prior_combos = {(_s(r["change_kind"]), _s(r["mechanism"]), _s(r["mechanism_detail"]))
                    for r in store.query(
                        "SELECT change_kind, mechanism, mechanism_detail FROM rr_delta_priors "
                        "WHERE n_targets >= 1", ())}

    per_target: dict[str, dict] = {}
    project_cov: dict[str, list[float]] = {}
    hit_acc: dict[tuple[str, str], list[int]] = {}
    for target in targets:
        key = _s(target["target_key"])
        rostered, closed = coverage.get(key, [0, 0])
        cov = round(closed / rostered, 6) if rostered else None
        if cov is not None:
            project_cov.setdefault(_s(target["project_id"]), []).append(cov)
        events = store.query(
            "SELECT cid, change_kind, subject_key FROM rr_diff_events WHERE diff_id = ? "
            "AND layer = 'semantic' AND design_relevant = 1 AND excluded_reason IS NULL",
            (_s(target["ref_id"]),)) if _s(target["kind"]) == "diff" else []
        hits = 0
        for event in events:
            subject = _s(event["subject_key"])
            others = subject_targets.get(subject, set()) - {key}
            combos = {(_s(event["change_kind"]), mech, detail)
                      for mech, detail in subject_combos.get(subject, set())}
            if others or (combos & prior_combos):
                hits += 1
        for dim, dim_key in (("global", "global"), ("project", _s(target["project_id"]))):
            slot = hit_acc.setdefault((dim, dim_key), [0, 0])
            slot[0] += len(events)
            slot[1] += hits
        per_target[key] = {
            "coverage_pct": cov,
            "precedent_events": len(events),
            "precedent_hits": hits,
            "created_at": target["created_at"],
        }

    for project_id in sorted(project_cov):
        values = project_cov[project_id]
        out.append(("project", project_id, "coverage_pct",
                    round(sum(values) / len(values), 6), len(values)))
    all_values = [v for values in project_cov.values() for v in values]
    if all_values:
        out.append(("global", "global", "coverage_pct",
                    round(sum(all_values) / len(all_values), 6), len(all_values)))
    _emit_ratio(out, "precedent_hit_rate", hit_acc)
    return per_target


def _panel_quality_rows(out: list, store: RiskStore) -> None:
    """패널 quality_json 평균 — attribution_rate·facets_filled·neg_precedent_cited_rate(plan §4.6·§6.7·§7.6)."""
    sums: dict[tuple[str, str, str], list[float]] = {}
    neg_den = neg_num = 0
    for row in store.query(
        "SELECT p.id AS id, p.quality_json AS quality_json, t.project_id AS project_id "
        "FROM rr_panels p LEFT JOIN rr_targets t ON t.target_key = p.target_key "
        "WHERE p.status = 'done' ORDER BY p.id", ()
    ):
        quality = _loads(row["quality_json"], {})
        if not isinstance(quality, dict):
            continue
        if "neg_precedent_cited_n" in quality:
            neg_den += 1
            neg_num += 1 if int(_f(quality.get("neg_precedent_cited_n")) or 0) >= 1 else 0
        for metric in ("attribution_rate", "facets_filled"):
            value = _f(quality.get(metric))
            if value is None:
                continue
            for dim, key in (("global", "global"), ("project", _s(row["project_id"]))):
                if not key:
                    continue
                slot = sums.setdefault((dim, key, metric), [0.0, 0.0])
                slot[0] += value
                slot[1] += 1
    for dim, key, metric in sorted(sums):
        total, count = sums[(dim, key, metric)]
        _emit(out, dim, key, metric, round(total / count, 6) if count else None, int(count))
    value = round(neg_num / neg_den, 6) if neg_den >= MIN_N["neg_precedent_cited_rate"] else None
    out.append(("global", "global", "neg_precedent_cited_rate", value, neg_den))


def _req_coverage_rows(out: list, store: RiskStore) -> None:
    """missing.req_absent=false 인 과제 비율 — 요구가 등록된 과제의 몫(plan §7.6)."""
    projects = sorted(_corpus_projects(store))
    if not projects:
        return
    with_req = {str(r["project_id"]) for r in store.query(
        "SELECT DISTINCT project_id FROM rr_requirements WHERE status != 'waived'", ())}
    hits = sum(1 for pid in projects if pid in with_req)
    out.append(("global", "global", "req_coverage", round(hits / len(projects), 6), len(projects)))


def _rule_trend_rows(out: list, store: RiskStore) -> None:
    """active 규칙 백테스트 precision 의 최근 5회 이동평균(plan §7.6)."""
    values: list[float] = []
    for row in store.query(
        "SELECT backtest_json FROM rr_rules WHERE status = 'active' ORDER BY activated_at DESC, id DESC LIMIT ?",
        (BADGE_WINDOW,)
    ):
        precision = _f(_loads(row["backtest_json"], {}).get("precision"))
        if precision is not None:
            values.append(precision)
    if not values:
        return
    out.append(("global", "global", "rule_precision_trend",
                round(sum(values) / len(values), 6), len(values)))


def _badge_rows(out: list, store: RiskStore, per_target: Mapping[str, dict],
                atoms: Sequence[Mapping[str, Any]], n_labels: int, now: int) -> dict:
    """'루프 작동' 배지 — 최근 5타깃 이동평균 3조건과 병목 3종(plan §7.6 판정 규칙)."""
    recent = sorted(per_target.items(), key=lambda kv: (kv[1]["created_at"] or 0, kv[0]))[-BADGE_WINDOW:]
    events = sum(t["precedent_events"] for _, t in recent)
    hits = sum(t["precedent_hits"] for _, t in recent)
    recent_keys = {key for key, _ in recent}
    window_atoms = [a for a in atoms if _s(a["target_key"]) in recent_keys]
    moving = {
        "precedent_hit_rate": (hits / events) if events else None,
        "known_share": (sum(1 for a in window_atoms if a["known"]) / len(window_atoms))
        if window_atoms else None,
        "unclassified_ratio": (sum(1 for a in window_atoms
                                   if _s(a["mechanism_detail"]) == _UNCLASSIFIED) / len(window_atoms))
        if window_atoms else None,
    }
    ok = (
        moving["precedent_hit_rate"] is not None
        and moving["precedent_hit_rate"] >= BADGE_THRESHOLDS["precedent_hit_rate"]
        and moving["known_share"] is not None
        and moving["known_share"] >= BADGE_THRESHOLDS["known_share"]
        and moving["unclassified_ratio"] is not None
        and moving["unclassified_ratio"] <= BADGE_THRESHOLDS["unclassified_ratio"]
    )
    queue = store.query_one(
        "SELECT COUNT(*) AS n, MIN(created_at) AS oldest FROM rr_curation_queue WHERE status = 'open'", ())
    open_n = int((queue["n"] if queue is not None else 0) or 0)
    oldest = queue["oldest"] if queue is not None else None
    coverages = [t["coverage_pct"] for _, t in recent if t["coverage_pct"] is not None]
    bottlenecks: list[str] = []
    if n_labels < BADGE_MIN_LABELS:
        bottlenecks.append("labels")
    if open_n > BADGE_QUEUE_OPEN_MAX or (oldest is not None and (now - int(oldest)) > BADGE_QUEUE_AGE_MAX_S):
        bottlenecks.append("queue")
    if coverages and (sum(coverages) / len(coverages)) < BADGE_COVERAGE_MIN:
        bottlenecks.append("coverage")
    ok = ok and not bottlenecks
    out.append(("global", "global", "loop_ok", 1.0 if ok else 0.0, len(recent)))
    for name in ("labels", "queue", "coverage"):
        out.append(("global", "global", f"loop_bottleneck_{name}", 1.0 if name in bottlenecks else 0.0,
                    len(recent)))
    # 라벨 자동 유입(경로 1~4)이 배선되기 전에는 라벨이 사람 손 경로로만 들어온다 — 'labels' 병목이
    # 정상 운영의 부족처럼 읽히지 않게 배선 여부를 따로 낸다(야간 ①·⑤ 는 그동안 skipped 다).
    wired = callable(globals().get("sync_labels"))
    out.append(("global", "global", "label_ingest_wired", 1.0 if wired else 0.0, 0))
    return {"ok": ok, "bottlenecks": bottlenecks, "moving": moving, "n_labels": n_labels,
            "queue_open": open_n, "targets": [key for key, _ in recent],
            "label_auto_ingest": wired}


def _drop_stale(store: RiskStore, period: str, computed: set[tuple[str, str, str]]) -> int:
    """이번 계산이 내지 않은 같은 period 의 옛 자리를 지운다 — 자격을 잃은 행이 현재 값처럼 조회되면
    지표가 '내려가는' 사건을 화면이 못 본다. 야간 살림 지표(`nightly_*`)는 이 계산의 소관이 아니다."""
    stale = [(period, _s(r["dimension"]), _s(r["key"]), _s(r["metric"])) for r in store.query(
        "SELECT dimension, key, metric FROM rr_metrics WHERE period = ? AND metric NOT LIKE 'nightly_%'",
        (period,)) if (_s(r["dimension"]), _s(r["key"]), _s(r["metric"])) not in computed]
    if stale:
        store.executemany(
            "DELETE FROM rr_metrics WHERE period = ? AND dimension = ? AND key = ? AND metric = ?", stale)
    return len(stale)


def recompute(store: RiskStore, *, period: str = "all", visibility: str = "private") -> dict:
    """§7.6 지표 전부를 rr_metrics 에 dimension 별로 적재하고 '루프 작동' 배지를 낸다.

    계산 단위는 **코퍼스 전체 1회**다 — rr_metrics 의 PK 는 `(period, dimension, key, metric)` 뿐이라
    소유자 축을 담을 자리가 없고(§5.2.2), 소유자마다 계산해 같은 자리에 쓰면 마지막 소유자의 값만
    남아 전사 지표가 사전순 마지막 소유자의 부분집합이 된다.
    n 이 최소 표본에 못 미치면 value 를 NULL 로 두고 n 만 남긴다(화면이 'n<k' 로 정직하게 표기한다).
    총합 행 옆에 `@origin=human`(§7.6 층화)과 `@model=<name>`(§7.4 D6) 접미 행을 병렬로 낸다.
    같은 인자로 다시 부르면 같은 행을 덮어쓰고, 이번 계산에 없는 옛 자리는 지운다(멱등).
    """
    if visibility not in ("private", "org"):
        raise AppError("E100", f"visibility 어휘 밖입니다 — {visibility!r}.", 422)
    now = common.now_epoch()
    atoms = _load_atoms(store)
    eligible = [a for a in atoms if a["eligible"]]
    labels = _label_rows(store)
    queue_status = label_queue_status(store)
    held = held_label_ids(store)
    label_atoms = _label_atoms(atoms, labels, queue_status)
    # 반대석 지표는 기각 원자를 분모로 쓰므로 라벨을 대표 클러스터로 묶어 따로 준다(§7.6).
    labels_by_cluster: dict[str, list] = {}
    for label in label_atoms:
        labels_by_cluster.setdefault(_s(label["_finding"]["cluster_key_norm"]), []).append(label)
    stat_labels = [label for label in label_atoms if label["_finding"]["eligible"]]

    rows: list[tuple] = []
    _precision_rows(rows, stat_labels)
    _lead_time_rows(rows, stat_labels)
    _recall_proxy_rows(rows, eligible, stat_labels)
    _calibration_rows(rows, stat_labels)
    _corpus_ratio_rows(rows, eligible)
    _req_rows(rows, eligible)
    _field_evidence_rows(rows, store, eligible)
    _adversary_rows(rows, store, atoms, labels_by_cluster)
    _cluster_dup_rows(rows, store)
    _human_override_rows(rows, store)
    per_target = _target_rows(rows, store)
    _panel_quality_rows(rows, store)
    _req_coverage_rows(rows, store)
    _rule_trend_rows(rows, store)
    badge = _badge_rows(rows, store, per_target, eligible, len(stat_labels), now)

    with store.tx():
        store.executemany(
            "INSERT INTO rr_metrics(period, dimension, key, metric, value, n, computed_at, visibility) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(period, dimension, key, metric) DO UPDATE SET "
            "value = excluded.value, n = excluded.n, computed_at = excluded.computed_at, "
            "visibility = excluded.visibility",
            [(period, dim, key, metric, value, n, now, visibility)
             for dim, key, metric, value, n in rows],
        )
        _drop_stale(store, period, {(dim, key, metric) for dim, key, metric, _v, _n in rows})
    return {"period": period, "computed_at": now, "rows": len(rows), "labels": len(stat_labels),
            "held_labels": len(held), "findings": len(eligible), "badge": badge}


# ---------------------------------------------------------------- ① 라벨 동기(야간 STEP_HOOKS['labels'], plan §7.6 경로 1)
# incident 레코드에서 읽는 키. RA 가 주는 이름이 다르면 어댑터가 이 모양으로 맞춘다(앱은 한 모양만 안다).
INCIDENT_KEYS: tuple[str, ...] = ("id", "project_id", "ckeys", "mechanism", "outcome", "occurred_at",
                                  "severity_observed")


def _incident_match(finding: Mapping[str, Any], incident: Mapping[str, Any]) -> dict:
    """3항 매칭(project·part·mechanism)의 적중 표 — 점수는 match_score 가 센다(plan §7.6)."""
    ckeys = set(str(c) for c in (incident.get("ckeys") or ()))
    finding_ckeys = set()
    try:
        finding_ckeys = {str(c) for c in json.loads(finding["ckeys_json"] or "[]")}
    except (TypeError, ValueError):
        finding_ckeys = set()
    if finding["subject_key"]:
        finding_ckeys.add(str(finding["subject_key"]))
    return {
        "project": _s(finding["project_id"]) == _s(incident.get("project_id")),
        "part": bool(ckeys & finding_ckeys),
        "mechanism": _s(finding["mechanism"]) == _s(incident.get("mechanism")),
    }


def sync_labels(store: RiskStore, *, incidents: Sequence[Mapping[str, Any]] | None = None,
                ra: Any = None, owner_sub: str | None = None, now: int | None = None) -> dict:
    """RA incident 레코드를 라벨 경로 1로 흘린다(plan §7.6). 완전 일치(3/3)만 자동 확정이다.

    레코드는 주입식이다 — `incidents` 가 없고 `ra` 도 없으면 아무것도 하지 않고 skipped 를 돌려준다
    (야간 잡이 자격 없는 박스에서 조용히 도는 자리다). 앱이 스스로 외부를 열지 않는다.
    """
    if incidents is None:
        fetch = getattr(ra, "list_incidents", None) if ra is not None else None
        if not callable(fetch):
            return {"incidents": 0, "labeled": 0, "auto": 0, "queued": 0, "skipped": "no_source"}
        incidents = list(fetch() or ())
    rows = store.query(
        "SELECT finding_id, project_id, mechanism, subject_key, ckeys_json, owner_sub, status"
        " FROM rr_findings WHERE status IN ('open','verified','dismissed') ORDER BY finding_id", ())
    labeled = auto = queued = 0
    for incident in incidents:
        best: tuple[float, dict, dict] | None = None
        for row in rows:
            matched = _incident_match(row, incident)
            score = match_score(matched)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, dict(row), matched)
        if best is None:
            continue
        _score, finding, matched = best
        out = record_label(
            store, finding_id=_s(finding["finding_id"]), source="incident",
            outcome=_s(incident.get("outcome")) or "confirmed",
            evidence_ref=f"inc:{_s(incident.get('id'))}",
            owner_sub=owner_sub or _s(finding["owner_sub"]), matched=matched,
            severity_observed=incident.get("severity_observed"),
            occurred_at=incident.get("occurred_at"),
        )
        labeled += 1
        auto += 1 if out.get("auto") else 0
        queued += 1 if out.get("queue_id") else 0
    return {"incidents": len(incidents), "labeled": labeled, "auto": auto, "queued": queued,
            "skipped": None, "now": now}
