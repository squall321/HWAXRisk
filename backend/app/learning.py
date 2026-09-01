# 학습 루프 — delta 선례 재합산·패턴 마이닝·승격 상태기계·규칙 백테스트(plan §7.4·§7.5)
from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app import common, config, registry, state
from app.errors import AppError
from app.risk_store import RiskStore

# ---------------------------------------------------------------- 상수(plan §7.4·§7.5·§0.6)

# ∅ → candidate 임계(§7.5 1행).
CANDIDATE_MIN_TARGETS = 3
CANDIDATE_MIN_PROJECTS = 2
CANDIDATE_MIN_EXPERTS = 2

# candidate → known 임계(§7.5 2행) — 큐레이터 승인 AND (confirmed ≥1 OR finding ≥5 across project ≥3).
KNOWN_MIN_FINDINGS = 5
KNOWN_MIN_PROJECTS = 3

# known → rule 백테스트 게이트(§7.5 3행).
RULE_MIN_LABELED = 10
RULE_MIN_PRECISION = 0.6
RULE_MIN_RECALL = 0.5
HOLDOUT_RATIO = 0.3

# rule → predictor 게이트(§7.5 4행). 학습 코드는 이 리포 밖이라 게이트만 본다.
PREDICTOR_MIN_LABELED = 50
PREDICTOR_MIN_PROJECTS = 15
PREDICTOR_MIN_R2 = 0.6
PREDICTOR_MIN_AUROC = 0.75

# any → suspended 자동 제안(§7.5 5행).
SUSPEND_WINDOW = 20
SUSPEND_PRECISION = 0.3

# 선례 정밀도 표기 하한(§7.4 '분모 <5 면 카운트만').
PRECISION_MIN_N = 5

# 별칭 체인 상한(§0.6 키 계보 행).
ALIAS_MAX_HOPS = 5

# 승격 상태기계가 허용하는 목적지.
PROMOTABLE = ("known", "rule", "predictor", "suspended", "deprecated")

# 라벨이 아닌 원자(§7.5 '세는 대상에서 빠지는 원자') — SQL 로 거르는 둘과 등록부로 거르는 하나.
_ATOM_SQL = (
    "SELECT finding_id, target_key, project_id, panel_id, opinion_id, origin, owner_sub, mechanism, "
    "mechanism_detail, change_kind, subject_key, cluster_key, direction, severity, sev3, finding_json, "
    "created_at FROM rr_findings WHERE status <> 'rejected_in_panel' AND recall_eligible = 1"
)
_ATOM_ORDER = " ORDER BY created_at, finding_id"

_LABEL_SQL = (
    "SELECT l.id AS label_id, l.finding_id, l.source, l.outcome, l.matched_by, l.match_score, "
    "l.labeled_at, l.occurred_at, l.owner_sub, f.target_key, f.cluster_key, f.change_kind, f.mechanism, "
    "f.mechanism_detail FROM rr_labels AS l JOIN rr_findings AS f ON f.finding_id = l.finding_id"
)
_LABEL_ORDER = " ORDER BY l.labeled_at, l.id"

# feature_snapshot ref 접두 → 조건 DSL 스코프(§7.5 조건 DSL — 평가기가 아는 접두는 이 둘뿐이다).
_REF_SCOPE: dict[str, str] = {"e": "edge", "p": "node"}
# state.evaluate_rules 가 실제로 해석하는 조건 접두. 그 밖의 항(diff.* 등)은 조용히 버려진다.
EVALUABLE_PREFIXES: tuple[str, ...] = ("warnings.", "edge.", "node.")

_PATTERN_COLUMNS = (
    "id, owner_sub, visibility, cluster_key_norm, mechanism, mechanism_detail, change_kind, subject_class, "
    "status, n_findings, n_targets, n_projects, n_experts, n_confirmed, n_refuted, precision, merged_into, "
    "feature_ranges_json, card_record_id, design_trait_tag, curated_by, promoted_at, suspended_reason, "
    "created_at, updated_at"
)

_PATTERN_ID_RE = re.compile(r"^P-(\d+)$")


# ---------------------------------------------------------------- 작은 도우미


def _loads(text: Any, default: Any) -> Any:
    if not text:
        return default
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def resolve_cluster_key(store: RiskStore, cluster_key: str, *, _cache: dict | None = None) -> str:
    """rr_cluster_alias 를 거친 대표 cluster_key(§4.3.2). 체인 ≤5홉이고 revoked 별칭·순환은 건너뛴다.

    registry 가 같은 이름의 정본을 갖게 되면 이 함수는 그쪽으로 위임한다(중복 구현 금지).
    """
    key = _s(cluster_key)
    if not key:
        return key
    if _cache is not None and key in _cache:
        return _cache[key]
    seen = {key}
    current = key
    for _ in range(ALIAS_MAX_HOPS):
        row = store.query_one(
            "SELECT new_cluster_key FROM rr_cluster_alias WHERE old_cluster_key = ? AND revoked_at IS NULL",
            (current,),
        )
        if row is None:
            break
        nxt = _s(row["new_cluster_key"])
        if not nxt or nxt in seen:
            break
        seen.add(nxt)
        current = nxt
    if _cache is not None:
        _cache[key] = current
    return current


def precision_of(n_confirmed: int, n_refuted: int) -> dict:
    """선례 정밀도(§7.4). 분모 <5 면 값 대신 카운트만 쓰라는 표기를 함께 돌려준다."""
    n = int(n_confirmed) + int(n_refuted)
    value = round(int(n_confirmed) / n, 4) if n else None
    return {"precision": value, "n": n, "low_n": n < PRECISION_MIN_N}


def delta_prior_line(row: Mapping[str, Any]) -> str:
    """E8 한 줄(§7.4 '수치만'). 총합만 쓰고 모델 층화는 싣지 않는다."""
    combo = f"{_s(row.get('change_kind'))}/{_s(row.get('mechanism'))}/{_s(row.get('mechanism_detail'))}"
    verified = int(row.get("n_verified") or 0)
    dismissed = int(row.get("n_dismissed") or 0)
    stat = precision_of(verified, dismissed)
    line = (f"{combo}: n_raised {int(row.get('n_raised') or 0)} · n_targets {int(row.get('n_targets') or 0)} · "
            f"n_verified {verified} · n_dismissed {dismissed}")
    if stat["precision"] is not None and not stat["low_n"]:
        line += f" · precision {stat['precision']:.2f} (n={stat['n']})"
    else:
        line += f" · precision n<{PRECISION_MIN_N}"
    return line


def _settings():
    return config.settings


# ---------------------------------------------------------------- 원자 수집(§7.5 '승격이 세는 원자의 조건')


def _weak_subject_rows(store: RiskStore, owner_sub: str | None = None) -> set[tuple[str, str]]:
    sql = "SELECT target_key, cluster_key FROM rr_registry WHERE weak_subject = 1"
    params: tuple = ()
    if owner_sub:
        sql += " AND owner_sub = ?"
        params = (owner_sub,)
    return {
        (r["target_key"], registry.strip_improvement_suffix(_s(r["cluster_key"])))
        for r in store.query(sql, params)
    }


def collect_atoms(store: RiskStore, *, norms: Iterable[str] | None = None,
                  owner_sub: str | None = None) -> dict[str, list[dict]]:
    """cluster_key_norm → 승격이 세는 원자 목록. rejected_in_panel·recall_eligible=0·weak_subject 는 뺀다.

    `owner_sub` 를 주면 그 소유자의 원자만 센다 — 패턴 임계(타깃 ≥3·project ≥2·expert ≥2)는 한 소유자
    코퍼스 안에서 차야 하고, 다른 소유자의 claim 이 큐 payload 에 섞이면 안 된다(rr_findings 는 private).
    """
    wanted = set(norms) if norms is not None else None
    weak = _weak_subject_rows(store, owner_sub)
    agent_of = {
        r["opinion_id"]: _s(r["agent_key"])
        for r in store.query("SELECT opinion_id, agent_key FROM rr_seat_opinions", ())
    }
    model_of = {
        r["id"]: _s(_loads(r["model_json"], {}).get("model"))
        for r in store.query("SELECT id, model_json FROM rr_panels", ())
    }
    cache: dict[str, str] = {}
    groups: dict[str, list[dict]] = {}
    sql, params = _ATOM_SQL, ()
    if owner_sub:
        sql += " AND owner_sub = ?"
        params = (owner_sub,)
    for row in store.query(sql + _ATOM_ORDER, params):
        cluster_key = _s(row["cluster_key"])
        if (row["target_key"], registry.strip_improvement_suffix(cluster_key)) in weak:
            continue
        norm = resolve_cluster_key(store, cluster_key, _cache=cache)
        if wanted is not None and norm not in wanted:
            continue
        fj = _loads(row["finding_json"], {})
        groups.setdefault(norm, []).append({
            "finding_id": row["finding_id"],
            "target_key": row["target_key"],
            "project_id": row["project_id"],
            "origin": _s(row["origin"]) or "llm",
            "agent_key": agent_of.get(_s(row["opinion_id"]), ""),
            "model": model_of.get(_s(row["panel_id"]), ""),
            "mechanism": _s(row["mechanism"]),
            "mechanism_detail": _s(row["mechanism_detail"]),
            "change_kind": _s(row["change_kind"]),
            "subject_key": _s(row["subject_key"]),
            "direction": _s(row["direction"]),
            "severity": _s(row["severity"]),
            "owner_sub": _s(row["owner_sub"]),
            "sev3": int(row["sev3"] or 0),
            # gap_21 — 브리프 선례를 되풀이한 발언은 finding_json.primed 로 표기된다(스탬프는 finding 삽입 경로의 몫).
            "primed": bool(fj.get("primed")),
            # 스탬프 자체가 없으면 '되풀이가 없다' 가 아니라 '독립성을 검증하지 못했다' 다 — 통계가 그것을 드러낸다.
            "primed_stamped": "primed" in fj,
            "feature_snapshot": fj.get("feature_snapshot") if isinstance(fj.get("feature_snapshot"), dict) else {},
            "created_at": int(row["created_at"] or 0),
        })
    return groups


def collect_labels(store: RiskStore, *, owner_sub: str | None = None) -> dict[str, list[dict]]:
    """cluster_key_norm → 라벨 목록. `excluded` 판정은 metrics 의 단일 술어를 그대로 부른다.

    '통계에 드는 라벨' 의 정의가 두 모듈에서 갈리면 같은 근거로 `rr_metrics.precision` 과
    `rr_patterns.precision` 이 다른 값을 낸다 — 정의는 `metrics.is_counted_label` 한 곳이다(§7.6).
    """
    from app import metrics  # 순환 임포트 방지 — metrics 는 learning 을 모듈 최상단에서 쓴다.

    queue_status = metrics.label_queue_status(store, owner_sub)
    cache: dict[str, str] = {}
    groups: dict[str, list[dict]] = {}
    sql, params = _LABEL_SQL, ()
    if owner_sub:
        sql += " WHERE l.owner_sub = ?"
        params = (owner_sub,)
    for raw in store.query(sql + _LABEL_ORDER, params):
        row = dict(raw)
        norm = resolve_cluster_key(store, _s(row["cluster_key"]), _cache=cache)
        groups.setdefault(norm, []).append({
            "label_id": row["label_id"],
            "finding_id": row["finding_id"],
            "source": _s(row["source"]),
            "outcome": _s(row["outcome"]),
            "matched_by": _s(row["matched_by"]),
            "labeled_at": int(row["labeled_at"] or 0),
            "target_key": row["target_key"],
            "excluded": not metrics.is_counted_label(row, queue_status),
        })
    return groups


def _feature_ranges(atoms: Sequence[Mapping[str, Any]]) -> dict:
    """feature_snapshot 의 수치 속성 범위 [min, max]. 규칙 초안(§7.5 known→rule)의 재료다.

    저장 형태는 narrative.feature_snapshot_from_cites 가 쓰는 평평한 `{ref: {attr: value}}` 이고(정본),
    계획 문장 그대로의 `{refs:[{ref, attrs}], project_fv:{}}` 도 함께 읽는다. 키는 조건 DSL 스코프를 실어
    `edge.<attr>`·`node.<attr>`(ref 접두 `e:`·`p:`)로 내고, 스코프를 모르는 ref 는 버린다 — 노드 속성을
    `edge.` 로 붙이면 그 규칙은 어떤 IR 에서도 매치되지 않는다.
    """
    ranges: dict[str, list[float]] = {}

    def note(name: str, value: Any) -> None:
        num = _num(value)
        if num is None:
            return
        current = ranges.get(name)
        if current is None:
            ranges[name] = [num, num]
        else:
            current[0] = min(current[0], num)
            current[1] = max(current[1], num)

    def note_ref(ref: Any, attrs: Any) -> None:
        scope = _REF_SCOPE.get(str(ref or "").split(":", 1)[0])
        if scope is None or not isinstance(attrs, Mapping):
            return
        for key, value in attrs.items():
            note(f"{scope}.{key}", value)

    for atom in atoms:
        snapshot = atom.get("feature_snapshot") or {}
        if not isinstance(snapshot, Mapping):
            continue
        for item in snapshot.get("refs") or []:
            if isinstance(item, Mapping):
                note_ref(item.get("ref"), item.get("attrs") or {})
        for key, value in snapshot.items():
            if key in ("refs", "project_fv", "diff"):
                continue
            note_ref(key, value)
        for key, value in (snapshot.get("project_fv") or {}).items():
            note(f"fv:{key}", value)
    return {k: [round(v[0], 6), round(v[1], 6)] for k, v in sorted(ranges.items())}


def _mode(values: Iterable[str]) -> str:
    counts: dict[str, int] = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return ""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def pattern_stats(atoms: Sequence[Mapping[str, Any]], labels: Sequence[Mapping[str, Any]] | None = None) -> dict:
    """한 cluster_key_norm 의 조합별 통계. 독립 제기(primed=false)와 되풀이를 나눠 센다(gap_21)."""
    labels = list(labels or [])
    counted = [lab for lab in labels if not lab["excluded"] and lab["outcome"] in ("confirmed", "refuted")]
    n_confirmed = sum(1 for lab in counted if lab["outcome"] == "confirmed")
    n_refuted = len(counted) - n_confirmed
    independent = [a for a in atoms if not a["primed"]]
    seats = {a["agent_key"] for a in atoms if a["origin"] == "llm" and a["agent_key"]}
    seats_ind = {a["agent_key"] for a in independent if a["origin"] == "llm" and a["agent_key"]}
    stat = precision_of(n_confirmed, n_refuted)
    return {
        "n_findings": len(atoms),
        "n_targets": len({a["target_key"] for a in atoms}),
        "n_projects": len({a["project_id"] for a in atoms}),
        "n_experts": len(seats),
        "n_models": len({a["model"] for a in atoms if a["model"]}),
        "n_independent": len(independent),
        "n_targets_independent": len({a["target_key"] for a in independent}),
        "n_projects_independent": len({a["project_id"] for a in independent}),
        "n_experts_independent": len(seats_ind),
        "echo_ratio": round(1 - len(independent) / len(atoms), 4) if atoms else 0.0,
        # gap_21 — 스탬프가 없으면 echo_ratio 0.0 은 '되풀이가 없다' 가 아니라 '재지 못했다' 다.
        "stamp_missing": sum(1 for a in atoms if not a.get("primed_stamped")),
        "independence_verified": bool(atoms) and all(a.get("primed_stamped") for a in atoms),
        "n_confirmed": n_confirmed,
        "n_refuted": n_refuted,
        "precision": stat["precision"],
        "precision_n": stat["n"],
        "mechanism": _mode(a["mechanism"] for a in atoms),
        "mechanism_detail": _mode(a["mechanism_detail"] for a in atoms),
        "change_kind": _mode(a["change_kind"] for a in atoms),
        "subject_class": (_mode(a["subject_key"] for a in atoms).split(":", 1)[0] or "unknown"),
        "severity": _mode(a["severity"] for a in atoms),
        "feature_ranges": _feature_ranges(atoms),
        "feature_ranges_confirmed": _feature_ranges(
            [a for a in atoms if a["finding_id"] in {lab["finding_id"] for lab in counted
                                                     if lab["outcome"] == "confirmed"}]),
    }


def candidate_gate(stats: Mapping[str, Any], *, distinct_models: int | None = None) -> dict:
    """∅ → candidate 조건(§7.5) + D6 모델 층화 가드. 세는 원자는 독립 제기만이다(gap_21)."""
    need_models = int(_settings().risk_promote_distinct_models if distinct_models is None else distinct_models)
    checks = {
        "targets": (stats["n_targets_independent"], CANDIDATE_MIN_TARGETS),
        "projects": (stats["n_projects_independent"], CANDIDATE_MIN_PROJECTS),
        "experts": (stats["n_experts_independent"], CANDIDATE_MIN_EXPERTS),
    }
    unmet = [name for name, (have, need) in checks.items() if have < need]
    if need_models >= 2 and stats["n_models"] < need_models:
        unmet.append("models")
    return {
        "ok": not unmet,
        "unmet": unmet,
        "distinct_models_required": need_models,
        "checks": {name: {"have": have, "need": need} for name, (have, need) in checks.items()},
        "independence_verified": bool(stats.get("independence_verified")),
        "stamp_missing": int(stats.get("stamp_missing") or 0),
    }


def known_gate(stats: Mapping[str, Any], *, distinct_models: int | None = None) -> dict:
    """candidate → known 조건(§7.5) — confirmed ≥1 또는 finding ≥5 across project ≥3. 승인은 사람이 따로 한다.

    D6 모델 가드는 §7.4 가 **candidate 조건** 에만 더하라고 적은 것이라 여기서는 참고 값으로만 싣는다 —
    같은 가드를 두 전이에 걸면 이미 표면화된 패턴이 사람 승인까지 422 로 막힌다.
    """
    by_label = stats["n_confirmed"] >= 1
    by_volume = stats["n_findings"] >= KNOWN_MIN_FINDINGS and stats["n_projects"] >= KNOWN_MIN_PROJECTS
    need_models = int(_settings().risk_promote_distinct_models if distinct_models is None else distinct_models)
    unmet: list[str] = []
    if not (by_label or by_volume):
        unmet.append("labels_or_volume")
    return {"ok": not unmet, "unmet": unmet, "by_label": by_label, "by_volume": by_volume,
            "distinct_models_required": need_models, "n_models": int(stats.get("n_models") or 0)}


# ---------------------------------------------------------------- §7.4 delta 선례 재합산


def _combo_of(row: Mapping[str, Any]) -> tuple[str, str, str] | None:
    change_kind = _s(row["change_kind"])
    if not change_kind or change_kind in registry.NO_CONTRIB_CHANGE_KINDS:
        return None
    return (change_kind, _s(row["mechanism"]) or "unclassified", _s(row["mechanism_detail"]))


def label_counts(store: RiskStore) -> dict[tuple[str, str, str], dict]:
    """조합별 n_verified·n_dismissed 를 rr_labels 에서 다시 센다(증분 += 없음, 멱등).

    세는 라벨의 정의는 `metrics.is_counted_label` 하나다 — 증분 훅(record_label)과 이 재합산이 서로 다른
    술어를 쓰면 야간 정합 검사가 매일 '증분이 틀렸다' 며 부풀린 쪽으로 고쳐 놓는다(§7.4·§7.6).
    """
    from app import metrics  # 순환 임포트 방지.

    queue_status = metrics.label_queue_status(store)
    counts: dict[tuple[str, str, str], dict] = {}
    for raw in store.query(_LABEL_SQL + _LABEL_ORDER, ()):
        row = dict(raw)
        outcome = _s(row["outcome"])
        if outcome not in ("confirmed", "refuted"):
            continue
        if not metrics.is_counted_label(row, queue_status):
            continue
        combo = _combo_of(row)
        if combo is None:
            continue
        acc = counts.setdefault(combo, {"n_verified": 0, "n_dismissed": 0})
        acc["n_verified" if outcome == "confirmed" else "n_dismissed"] += 1
    return counts


def recompute_label_priors(store: RiskStore, combos: Iterable[tuple] | None = None, *, now: int | None = None) -> int:
    """rr_delta_priors 의 n_verified·n_dismissed 를 rr_labels 합으로 재합산한다(§7.4 라벨 훅). 쓴 행 수를 돌려준다."""
    now = common.now_epoch() if now is None else now
    counts = label_counts(store)
    targets = set(counts)
    if combos is not None:
        targets = {tuple(c) for c in combos}
    else:
        targets |= {
            (r["change_kind"], r["mechanism"], r["mechanism_detail"])
            for r in store.query(
                "SELECT change_kind, mechanism, mechanism_detail FROM rr_delta_priors "
                "WHERE n_verified > 0 OR n_dismissed > 0", ())
        }
    written = 0
    for combo in sorted(targets):
        acc = counts.get(tuple(combo), {"n_verified": 0, "n_dismissed": 0})
        current = store.query_one(
            "SELECT n_verified, n_dismissed FROM rr_delta_priors "
            "WHERE change_kind = ? AND mechanism = ? AND mechanism_detail = ?",
            tuple(combo),
        )
        if current is not None and (
                int(current["n_verified"] or 0) == acc["n_verified"]
                and int(current["n_dismissed"] or 0) == acc["n_dismissed"]):
            continue
        if current is None:
            store.execute(
                "INSERT INTO rr_delta_priors (change_kind, mechanism, mechanism_detail, n_verified, n_dismissed, "
                "stats_version, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*combo, acc["n_verified"], acc["n_dismissed"], registry.STATS_VERSION, now),
            )
        else:
            store.execute(
                "UPDATE rr_delta_priors SET n_verified = ?, n_dismissed = ?, stats_version = ?, updated_at = ? "
                "WHERE change_kind = ? AND mechanism = ? AND mechanism_detail = ?",
                (acc["n_verified"], acc["n_dismissed"], registry.STATS_VERSION, now, *combo),
            )
        written += 1
    return written


def on_label(store: RiskStore, label_id: str, *, now: int | None = None) -> dict:
    """라벨 1건이 들어온 뒤의 훅(§7.4) — 그 조합의 선례 카운트와 그 패턴의 통계를 다시 맞춘다."""
    now = common.now_epoch() if now is None else now
    row = store.query_one(
        "SELECT l.id AS label_id, l.finding_id, f.cluster_key, f.change_kind, f.mechanism, f.mechanism_detail "
        "FROM rr_labels AS l JOIN rr_findings AS f ON f.finding_id = l.finding_id WHERE l.id = ?",
        (label_id,),
    )
    if row is None:
        raise AppError("E404", f"라벨을 찾을 수 없습니다: {label_id}", 404)
    combo = _combo_of(row)
    with store.tx():
        priors_written = recompute_label_priors(store, [combo] if combo else [], now=now)
        norm = resolve_cluster_key(store, _s(row["cluster_key"]))
        pattern = store.query_one("SELECT id FROM rr_patterns WHERE cluster_key_norm = ?", (norm,))
        pattern_id = _s(pattern["id"]) if pattern is not None else ""
        if pattern_id:
            refresh_pattern(store, pattern_id, now=now)
    return {"label_id": label_id, "combo": list(combo) if combo else None,
            "priors_written": priors_written, "pattern_id": pattern_id or None}


def check_delta_priors(store: RiskStore, *, fix: bool = True, now: int | None = None) -> dict:
    """야간 정합 검사(§7.4) — rr_delta_contrib 합·rr_labels 와 rr_delta_priors 를 대조하고 불일치만 재합산한다."""
    now = common.now_epoch() if now is None else now
    combos = {
        (r["change_kind"], r["mechanism"], r["mechanism_detail"])
        for r in store.query("SELECT change_kind, mechanism, mechanism_detail FROM rr_delta_contrib", ())
    }
    combos |= {
        (r["change_kind"], r["mechanism"], r["mechanism_detail"])
        for r in store.query("SELECT change_kind, mechanism, mechanism_detail FROM rr_delta_priors", ())
    }
    counts = label_counts(store)
    drift: list[dict] = []
    for combo in sorted(combos):
        rows = store.query(
            "SELECT target_key, n_raised, n_improvement FROM rr_delta_contrib "
            "WHERE change_kind = ? AND mechanism = ? AND mechanism_detail = ?",
            combo,
        )
        expected = {
            "n_raised": sum(int(r["n_raised"] or 0) for r in rows),
            "n_improvement": sum(int(r["n_improvement"] or 0) for r in rows),
            "n_targets": len({r["target_key"] for r in rows}),
            **counts.get(combo, {"n_verified": 0, "n_dismissed": 0}),
        }
        current = store.query_one(
            "SELECT n_raised, n_improvement, n_targets, n_verified, n_dismissed FROM rr_delta_priors "
            "WHERE change_kind = ? AND mechanism = ? AND mechanism_detail = ?",
            combo,
        )
        actual = {k: int(current[k] or 0) for k in expected} if current is not None else dict.fromkeys(expected, 0)
        if actual != expected:
            drift.append({"combo": list(combo), "expected": expected, "actual": actual})
    fixed = 0
    if fix and drift:
        with store.tx():
            keys = [tuple(d["combo"]) for d in drift]
            # 기여 합산의 정본은 registry 한 곳뿐이다 — 여기서 다시 구현하면 두 합이 갈린다.
            registry._recompute_priors(store, keys, now)
            recompute_label_priors(store, keys, now=now)
            fixed = len(keys)
    # §7.4 — drift 가 언제 몇 건 났는지 볼 자리를 남긴다(nightly_delta_priors_ok 0/1 만으로는 못 본다).
    from app import nightly
    nightly.record_metric(store, "nightly_delta_priors_drift", float(len(drift)), n=len(combos), now=now)
    return {"checked": len(combos), "drift": len(drift), "fixed": fixed, "details": drift}


# ---------------------------------------------------------------- §7.5 패턴 마이닝·승격


def _next_pattern_id(store: RiskStore) -> str:
    top = 0
    for row in store.query("SELECT id FROM rr_patterns", ()):
        m = _PATTERN_ID_RE.match(_s(row["id"]))
        if m:
            top = max(top, int(m.group(1)))
    return f"P-{top + 1:03d}"


def get_pattern(store: RiskStore, pattern_id: str) -> dict:
    row = store.query_one(f"SELECT {_PATTERN_COLUMNS} FROM rr_patterns WHERE id = ?", (pattern_id,))
    if row is None:
        raise AppError("E404", f"패턴을 찾을 수 없습니다: {pattern_id}", 404)
    return dict(row)


def _write_stats(store: RiskStore, pattern_id: str, stats: Mapping[str, Any], now: int) -> bool:
    current = store.query_one(
        "SELECT n_findings, n_targets, n_projects, n_experts, n_confirmed, n_refuted, precision, "
        "feature_ranges_json FROM rr_patterns WHERE id = ?", (pattern_id,))
    ranges = common.canonical_json(stats["feature_ranges"])
    if current is not None and (
            int(current["n_findings"] or 0) == stats["n_findings"]
            and int(current["n_targets"] or 0) == stats["n_targets"]
            and int(current["n_projects"] or 0) == stats["n_projects"]
            and int(current["n_experts"] or 0) == stats["n_experts"]
            and int(current["n_confirmed"] or 0) == stats["n_confirmed"]
            and int(current["n_refuted"] or 0) == stats["n_refuted"]
            and current["precision"] == stats["precision"]
            and _s(current["feature_ranges_json"]) == ranges):
        return False
    store.execute(
        "UPDATE rr_patterns SET n_findings = ?, n_targets = ?, n_projects = ?, n_experts = ?, "
        "n_confirmed = ?, n_refuted = ?, precision = ?, feature_ranges_json = ?, updated_at = ? WHERE id = ?",
        (stats["n_findings"], stats["n_targets"], stats["n_projects"], stats["n_experts"],
         stats["n_confirmed"], stats["n_refuted"], stats["precision"], ranges, now, pattern_id),
    )
    return True


def refresh_pattern(store: RiskStore, pattern_id: str, *, now: int | None = None) -> dict:
    """한 패턴의 통계(n_*·precision·feature_ranges)를 원자·라벨에서 다시 센다. status 는 건드리지 않는다."""
    now = common.now_epoch() if now is None else now
    pattern = get_pattern(store, pattern_id)
    norm = _s(pattern["cluster_key_norm"])
    owner = _s(pattern["owner_sub"]) or None
    atoms = collect_atoms(store, norms=[norm], owner_sub=owner).get(norm, [])
    labels = collect_labels(store, owner_sub=owner).get(norm, [])
    stats = pattern_stats(atoms, labels)
    changed = _write_stats(store, pattern_id, stats, now)
    return {"pattern_id": pattern_id, "changed": changed, "stats": stats}


def _open_queue_item(store: RiskStore, pattern_id: str, proposal: str) -> str | None:
    for row in store.query(
            "SELECT id, payload_json FROM rr_curation_queue WHERE kind = 'pattern_candidate' AND status = 'open'", ()):
        payload = _loads(row["payload_json"], {})
        if _s(payload.get("pattern_id")) == pattern_id and _s(payload.get("proposal") or "known") == proposal:
            return _s(row["id"])
    return None


def _queue(store: RiskStore, owner_sub: str, payload: Mapping[str, Any], now: int) -> str:
    queue_id = common.new_uuid()
    store.execute(
        "INSERT INTO rr_curation_queue (id, owner_sub, kind, payload_json, status, created_at) "
        "VALUES (?, ?, 'pattern_candidate', ?, 'open', ?)",
        (queue_id, owner_sub, common.canonical_json(dict(payload)), now),
    )
    return queue_id


def _sample_claims(store: RiskStore, atoms: Sequence[Mapping[str, Any]], limit: int = 5) -> list[dict]:
    out: list[dict] = []
    for atom in atoms[:limit]:
        row = store.query_one("SELECT finding_json FROM rr_findings WHERE finding_id = ?", (atom["finding_id"],))
        claim = _s(_loads(row["finding_json"], {}).get("claim")) if row is not None else ""
        out.append({"finding_id": atom["finding_id"], "target_key": atom["target_key"], "claim": claim})
    return out


def _recent_precision(labels: Sequence[Mapping[str, Any]], window: int = SUSPEND_WINDOW) -> dict:
    counted = [lab for lab in labels if not lab["excluded"] and lab["outcome"] in ("confirmed", "refuted")]
    recent = counted[-window:]
    n_confirmed = sum(1 for lab in recent if lab["outcome"] == "confirmed")
    stat = precision_of(n_confirmed, len(recent) - n_confirmed)
    return {"n": len(recent), "precision": stat["precision"]}


def mine_patterns(store: RiskStore, *, owner_sub: str | None = None, now: int | None = None) -> dict:
    """야간 패턴 마이너(§7.5) — 반복 cluster 를 candidate 로 표면화하고 통계를 갱신하며 suspended 를 제안한다.

    사람 승인 없이 known 이상으로 올리는 경로는 이 함수에 없다(자동 활성화 금지, §7.5).
    """
    now = common.now_epoch() if now is None else now
    groups = collect_atoms(store, owner_sub=owner_sub)
    labels_all = collect_labels(store, owner_sub=owner_sub)
    existing = {
        _s(r["cluster_key_norm"]): dict(r)
        for r in store.query("SELECT id, cluster_key_norm, status, owner_sub, merged_into FROM rr_patterns", ())
    }
    created: list[dict] = []
    updated: list[str] = []
    suspend_proposed: list[dict] = []
    skipped: list[dict] = []

    with store.tx():
        for norm in sorted(groups):
            atoms = groups[norm]
            stats = pattern_stats(atoms, labels_all.get(norm, []))
            row = existing.get(norm)
            if row is None:
                gate = candidate_gate(stats)
                if not gate["ok"]:
                    skipped.append({"cluster_key_norm": norm, "unmet": gate["unmet"]})
                    continue
                pattern_id = _next_pattern_id(store)
                owner = owner_sub or _s(store.query_one(
                    "SELECT owner_sub FROM rr_findings WHERE finding_id = ?", (atoms[0]["finding_id"],))["owner_sub"])
                store.execute(
                    "INSERT INTO rr_patterns (id, owner_sub, visibility, cluster_key_norm, mechanism, "
                    "mechanism_detail, change_kind, subject_class, status, n_findings, n_targets, n_projects, "
                    "n_experts, n_confirmed, n_refuted, precision, feature_ranges_json, created_at, updated_at) "
                    "VALUES (?, ?, 'private', ?, ?, ?, ?, ?, 'candidate', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (pattern_id, owner, norm, stats["mechanism"], stats["mechanism_detail"], stats["change_kind"],
                     stats["subject_class"], stats["n_findings"], stats["n_targets"], stats["n_projects"],
                     stats["n_experts"], stats["n_confirmed"], stats["n_refuted"], stats["precision"],
                     common.canonical_json(stats["feature_ranges"]), now, now),
                )
                queue_id = _queue(store, owner, {
                    "pattern_id": pattern_id, "cluster_key_norm": norm, "proposal": "known",
                    "n_findings": stats["n_findings"], "n_projects": stats["n_projects"],
                    "n_experts": stats["n_experts"], "n_models": stats["n_models"],
                    "n_independent": stats["n_independent"], "echo_ratio": stats["echo_ratio"],
                    "distinct_models_required": gate["distinct_models_required"],
                    "independence_verified": gate["independence_verified"],
                    "stamp_missing": gate["stamp_missing"],
                    "note": None if gate["independence_verified"]
                    else "독립성 미검증(primed 스탬프 없음) — echo_ratio 0.0 은 되풀이가 없다는 뜻이 아니다.",
                    "sample_claims": _sample_claims(store, atoms),
                }, now)
                created.append({"pattern_id": pattern_id, "cluster_key_norm": norm, "queue_id": queue_id})
                existing[norm] = {"id": pattern_id, "cluster_key_norm": norm, "status": "candidate",
                                  "owner_sub": owner, "merged_into": None}
                continue

            pattern_id = _s(row["id"])
            if _s(row["merged_into"]):
                continue
            if owner_sub and _s(row["owner_sub"]) != owner_sub:
                # 같은 cluster_key_norm 이 다른 소유자의 패턴으로 이미 서 있다. rr_patterns 는
                # UNIQUE(cluster_key_norm) 이라 자리를 나눌 수 없으므로 남의 행에 내 통계를 쓰지 않는다.
                skipped.append({"cluster_key_norm": norm, "unmet": ["owned_by_other"],
                                "owner_sub": _s(row["owner_sub"])})
                continue
            if _write_stats(store, pattern_id, stats, now):
                updated.append(pattern_id)
            if _s(row["status"]) in ("candidate", "known", "rule", "predictor"):
                recent = _recent_precision(labels_all.get(norm, []))
                if recent["precision"] is not None and recent["precision"] < SUSPEND_PRECISION:
                    if _open_queue_item(store, pattern_id, "suspend") is None:
                        queue_id = _queue(store, _s(row["owner_sub"]), {
                            "pattern_id": pattern_id, "cluster_key_norm": norm, "proposal": "suspend",
                            "recent_precision": recent["precision"], "recent_n": recent["n"],
                        }, now)
                        suspend_proposed.append({"pattern_id": pattern_id, "queue_id": queue_id,
                                                 "recent_precision": recent["precision"]})

    return {"scanned": len(groups), "created": created, "updated": updated,
            "suspend_proposed": suspend_proposed, "skipped": skipped}


# ---------------------------------------------------------------- §7.5 규칙 초안·백테스트


def draft_rule_condition(store: RiskStore, pattern_id: str) -> dict:
    """known → rule 자동 초안(§7.5) — confirmed finding 의 feature_snapshot 수치 범위를 between 조건으로 만든다.

    조건은 평가기(state.evaluate_rules)가 해석하는 접두만 쓴다 — `diff.*` 는 snap 스코프에서 조용히
    버려져 '백테스트가 채점한 조건' 과 '활성화되는 조건' 이 갈리므로 초안에 넣지 않고 참고 값으로만 낸다.
    """
    pattern = get_pattern(store, pattern_id)
    norm = _s(pattern["cluster_key_norm"])
    owner = _s(pattern["owner_sub"]) or None
    atoms = collect_atoms(store, norms=[norm], owner_sub=owner).get(norm, [])
    labels = collect_labels(store, owner_sub=owner).get(norm, [])
    stats = pattern_stats(atoms, labels)
    ranges = stats["feature_ranges_confirmed"] or stats["feature_ranges"]
    source = "confirmed" if stats["feature_ranges_confirmed"] else "all"
    conditions: list[dict] = []
    for name, (low, high) in ranges.items():
        scope, _, attr = name.partition(".")
        if scope not in ("edge", "node") or not attr:
            continue
        conditions.append({"ref": f"{scope}.{attr}", "op": "between", "value": [low, high]})
    return {"pattern_id": pattern_id, "range_source": source,
            "condition_json": {"all": conditions, "any": []},
            "change_kind": _s(pattern["change_kind"]),
            "feature_ranges": ranges}


def _target_ir(store: RiskStore, target_key: str) -> dict | None:
    row = store.query_one("SELECT kind, ref_id FROM rr_targets WHERE target_key = ?", (target_key,))
    if row is None:
        return None
    snapshot_id = _s(row["ref_id"])
    if _s(row["kind"]) == "diff":
        diff = store.query_one("SELECT target_snapshot_id FROM rr_diffs WHERE id = ?", (snapshot_id,))
        if diff is None:
            return None
        snapshot_id = _s(diff["target_snapshot_id"])
    snap = store.query_one("SELECT ir_json FROM rr_snapshots WHERE id = ?", (snapshot_id,))
    if snap is None:
        return None
    ir = _loads(snap["ir_json"], {})
    return ir or None


def unevaluable_refs(condition: Mapping[str, Any]) -> list[str]:
    """평가기가 해석하지 못하는 조건 ref — 있으면 그 항은 채점에서 조용히 사라진다(§7.5 조건 DSL)."""
    out: set[str] = set()
    for key in ("all", "any"):
        for cond in condition.get(key) or ():
            ref = _s((cond or {}).get("ref"))
            if not ref.startswith(EVALUABLE_PREFIXES):
                out.add(ref or "(ref 없음)")
    return sorted(out)


def backtest(
    store: RiskStore,
    condition: Mapping[str, Any],
    *,
    cluster_key_norm: str | None = None,
    aggregate: Mapping[str, Any] | None = None,
    holdout: float = HOLDOUT_RATIO,
    rule_id: str = "backtest",
    rule_version: str = "backtest",
) -> dict:
    """조건 DSL 을 과거 스냅샷에 돌려 적중·오탐을 잰다(§7.5 known → rule 게이트).

    표본은 라벨이 붙은 타깃뿐이다 — 예측 양성 = 그 타깃 스냅샷 IR 에서 규칙이 걸린 것,
    관측 양성 = 그 타깃에 confirmed 라벨이 있는 것(refuted 만이면 음성). 시간순 정렬 뒤 30% 가 홀드아웃이다.

    평가기가 해석하지 못하는 접두의 조건이 섞이면 422 다 — 그 항은 채점에서 사라지므로 '측정한 조건' 과
    '저장돼 발화할 조건' 이 갈린다(diff.* 는 snap 스코프 평가기가 버린다, §7.5).
    """
    unevaluable = unevaluable_refs(condition)
    if unevaluable:
        raise AppError(
            "E100",
            f"백테스트가 채점할 수 없는 조건 ref 입니다 — {unevaluable}. "
            f"평가기가 아는 접두는 {list(EVALUABLE_PREFIXES)} 뿐이라 그 항은 채점에서 사라진다.", 422)
    labels_all = collect_labels(store)
    if cluster_key_norm:
        pools = [labels_all.get(cluster_key_norm, [])]
    else:
        pools = list(labels_all.values())
    truth: dict[str, bool] = {}
    for pool in pools:
        for lab in pool:
            if lab["excluded"] or lab["outcome"] not in ("confirmed", "refuted"):
                continue
            target_key = lab["target_key"]
            truth[target_key] = truth.get(target_key, False) or lab["outcome"] == "confirmed"

    order = {
        r["target_key"]: (int(r["created_at"] or 0), _s(r["target_key"]))
        for r in store.query("SELECT target_key, created_at FROM rr_targets", ())
    }
    rule = {
        "id": rule_id, "name": rule_id, "rule_version": rule_version, "severity": "중대",
        "condition_json": dict(condition), "aggregate": dict(aggregate or {"count_gte": 1}),
        "why_it_matters": "", "fix_hint": "",
    }

    samples: list[dict] = []
    for target_key in sorted(truth, key=lambda k: order.get(k, (0, k))):
        ir = _target_ir(store, target_key)
        if ir is None:
            continue
        hit = state.evaluate_rules(ir, [rule])
        fired = bool(hit) and hit[0]["pass"] is False      # pass=null(평가 불가)은 발화로 세지 않는다
        samples.append({"target_key": target_key, "fired": fired, "actual": truth[target_key]})

    n = len(samples)
    split = int(n * (1.0 - holdout))
    parts = {"train": samples[:split], "holdout": samples[split:]}
    scored: dict[str, dict] = {}
    for name, rows in parts.items():
        tp = sum(1 for r in rows if r["fired"] and r["actual"])
        fp = sum(1 for r in rows if r["fired"] and not r["actual"])
        fn = sum(1 for r in rows if not r["fired"] and r["actual"])
        tn = len(rows) - tp - fp - fn
        scored[name] = {
            "n": len(rows), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
            "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        }

    result = {
        "n_labeled": n,
        "holdout_ratio": holdout,
        "precision": scored["holdout"]["precision"],
        "recall": scored["holdout"]["recall"],
        "train": scored["train"],
        "holdout": scored["holdout"],
        "samples": samples[:200],
    }
    unmet: list[str] = []
    if n < RULE_MIN_LABELED:
        unmet.append("n_labeled")
    if result["precision"] < RULE_MIN_PRECISION:
        unmet.append("precision")
    if result["recall"] < RULE_MIN_RECALL:
        unmet.append("recall")
    result["unmet"] = unmet
    result["passes"] = not unmet
    result["gates"] = {"n_labeled": RULE_MIN_LABELED, "precision": RULE_MIN_PRECISION, "recall": RULE_MIN_RECALL}
    return result


# ---------------------------------------------------------------- §7.5 승격 상태기계


_ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "candidate": ("known", "suspended", "deprecated"),
    "known": ("rule", "suspended", "deprecated"),
    "rule": ("predictor", "suspended", "deprecated"),
    "predictor": ("suspended", "deprecated"),
    # 복귀는 known 뿐 아니라 직전 층(rule)로도 열어 둔다 — 게이트는 그대로 다시 통과해야 한다(§7.5 '사람이 복귀').
    "suspended": ("known", "rule", "deprecated"),
    "deprecated": (),
}


def _fail(unmet: Sequence[str], detail: str) -> AppError:
    return AppError("E100", f"승격 조건 미충족({', '.join(unmet)}) — {detail}", 422)


def _create_rule(store: RiskStore, pattern: Mapping[str, Any], rule: Mapping[str, Any],
                 backtest_result: Mapping[str, Any], decided_by: str, now: int) -> str:
    why = _s(rule.get("why_it_matters"))
    if not why:
        raise AppError("E100", "규칙 승격에는 사람이 쓴 why_it_matters 원문이 필요합니다.", 422)
    severity = _s(rule.get("severity")) or _s(pattern.get("severity")) or "중대"
    if severity not in ("경미", "중대", "치명"):
        raise AppError("E100", f"severity 어휘가 아닙니다: {severity}", 422)
    rule_id = _s(rule.get("id")) or f"R-{_s(pattern['id']).replace('-', '')}"
    backtest_json = common.canonical_json({
        k: backtest_result[k] for k in ("n_labeled", "precision", "recall", "train", "holdout", "gates")})
    existing = store.query_one(
        "SELECT id, pattern_id, status FROM rr_rules WHERE id = ?", (rule_id,))
    if existing is not None:
        # suspend 가 내려놓은 그 패턴의 규칙이면 되살린다 — 그러지 않으면 복귀 경로가 파생 id 충돌로 막힌다(§7.5).
        if _s(existing["pattern_id"]) != _s(pattern["id"]) or _s(existing["status"]) != "retired":
            raise AppError("E100", f"이미 있는 규칙 id 입니다: {rule_id}", 422)
        store.execute(
            "UPDATE rr_rules SET condition_json = ?, severity = ?, why_it_matters = ?, fix_hint = ?, "
            "backtest_json = ?, status = 'active', activated_by = ?, activated_at = ? WHERE id = ?",
            (common.canonical_json(dict(rule.get("condition_json") or {})), severity, why,
             _s(rule.get("fix_hint")), backtest_json, decided_by, now, rule_id),
        )
        return rule_id
    store.execute(
        "INSERT INTO rr_rules (id, pattern_id, rule_version, mechanism, mechanism_detail, change_kind, "
        "condition_json, severity, why_it_matters, fix_hint, backtest_json, source, status, activated_by, "
        "activated_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pattern', 'active', ?, ?, ?)",
        (rule_id, _s(pattern["id"]), _s(rule.get("rule_version")) or "rules-1.0", _s(pattern["mechanism"]),
         _s(pattern["mechanism_detail"]), _s(pattern["change_kind"]),
         common.canonical_json(dict(rule.get("condition_json") or {})), severity, why,
         _s(rule.get("fix_hint")), backtest_json, decided_by, now, now),
    )
    return rule_id


def promote(
    store: RiskStore,
    pattern_id: str,
    *,
    to_status: str,
    decided_by: str,
    reason: str | None = None,
    rule: Mapping[str, Any] | None = None,
    cv: Mapping[str, Any] | None = None,
    now: int | None = None,
) -> dict:
    """승격·강등·폐기(§7.5). 사람 승인(decided_by) 없이는 어떤 전이도 없고 rule 자동 활성화도 없다."""
    now = common.now_epoch() if now is None else now
    decided_by = _s(decided_by)
    if not decided_by:
        raise AppError("E100", "승격은 사람 승인이 필요합니다 — decided_by 가 비었습니다.", 422)
    if to_status not in PROMOTABLE:
        raise AppError("E100", f"전이 대상 status 가 아닙니다: {to_status}", 422)

    pattern = get_pattern(store, pattern_id)
    if _s(pattern["merged_into"]):
        raise AppError("E100",
                       f"별칭으로 흡수된 패턴입니다 — 대표 패턴 {_s(pattern['merged_into'])} 을 승격하세요.", 422)
    current = _s(pattern["status"])
    if to_status not in _ALLOWED_TRANSITIONS.get(current, ()):
        raise AppError("E100", f"허용되지 않는 전이입니다: {current} → {to_status}", 422)

    norm = _s(pattern["cluster_key_norm"])
    owner = _s(pattern["owner_sub"]) or None
    atoms = collect_atoms(store, norms=[norm], owner_sub=owner).get(norm, [])
    labels = collect_labels(store, owner_sub=owner).get(norm, [])
    stats = pattern_stats(atoms, labels)
    out: dict[str, Any] = {"pattern_id": pattern_id, "from_status": current, "to_status": to_status,
                           "stats": stats,
                           "independence": {
                               "verified": bool(stats["independence_verified"]),
                               "stamp_missing": stats["stamp_missing"],
                               "echo_ratio": stats["echo_ratio"],
                               "note": None if stats["independence_verified"]
                               else "독립성 미검증(primed 스탬프 없음) — echo_ratio 를 독립성 근거로 읽지 마라."}}

    if to_status == "known":
        gate = known_gate(stats)
        if not gate["ok"]:
            raise _fail(gate["unmet"],
                        f"confirmed {stats['n_confirmed']} · finding {stats['n_findings']} · "
                        f"project {stats['n_projects']} · model {stats['n_models']}")
        out["gate"] = gate
    elif to_status == "rule":
        draft = rule or {}
        condition = draft.get("condition_json") or draft_rule_condition(store, pattern_id)["condition_json"]
        result = backtest(store, condition, cluster_key_norm=norm,
                          aggregate=draft.get("aggregate"))
        out["backtest"] = result
        if not result["passes"]:
            raise _fail(result["unmet"],
                        f"n_labeled {result['n_labeled']} · precision {result['precision']} · "
                        f"recall {result['recall']}")
        out["condition_json"] = condition
    elif to_status == "predictor":
        unmet = []
        n_labeled = stats["n_confirmed"] + stats["n_refuted"]
        if n_labeled < PREDICTOR_MIN_LABELED:
            unmet.append("n_labeled")
        if stats["n_projects"] < PREDICTOR_MIN_PROJECTS:
            unmet.append("n_projects")
        metric = _s((cv or {}).get("metric"))
        value = _num((cv or {}).get("value"))
        if metric == "r2":
            if value is None or value < PREDICTOR_MIN_R2:
                unmet.append("r2")
        elif metric == "auroc":
            if value is None or value < PREDICTOR_MIN_AUROC:
                unmet.append("auroc")
        else:
            unmet.append("cv")
        if unmet:
            # 게이트 미충족이면 학습 코드는 0줄이다(§7.5 P6 (7)) — 상태를 바꾸지 않고 돌려보낸다.
            raise _fail(unmet, f"n_labeled {n_labeled} · n_projects {stats['n_projects']} · cv {cv}")
        out["cv"] = dict(cv or {})

    with store.tx():
        if to_status == "rule":
            out["rule_id"] = _create_rule(store, {**pattern, "severity": stats["severity"]},
                                          {**(rule or {}), "condition_json": out["condition_json"]},
                                          out["backtest"], decided_by, now)
        store.execute(
            "UPDATE rr_patterns SET status = ?, curated_by = ?, promoted_at = ?, suspended_reason = ?, "
            "updated_at = ? WHERE id = ?",
            (to_status, decided_by, now, _s(reason) or None if to_status in ("suspended", "deprecated") else None,
             now, pattern_id),
        )
        if to_status in ("suspended", "deprecated"):
            # 제외는 상태로만 하고 선례 링크는 유지한다(§7.5) — rr_rules 도 함께 물린다.
            store.execute(
                "UPDATE rr_rules SET status = 'retired' WHERE pattern_id = ? AND status = 'active'", (pattern_id,))
        _write_stats(store, pattern_id, stats, now)

    out["pattern"] = get_pattern(store, pattern_id)
    return out


def active_pattern_rules(store: RiskStore) -> list[dict]:
    """패턴에서 승격돼 지금 도는 규칙 목록(§7.4 rule_hits 의 pattern 몫)."""
    return [dict(r) for r in store.query(
        "SELECT id, pattern_id, rule_version, severity, condition_json, why_it_matters, fix_hint, backtest_json "
        "FROM rr_rules WHERE source = 'pattern' AND status = 'active' ORDER BY id", ())]


# ---------------------------------------------------------------- 택소노미 재매핑(plan §7.7·§4.3.2 — 스크립트가 부르는 정본)
REMAP_DECIDED_BY = "code:taxonomy_remap"


def plan_remap(store: RiskStore, *, mechanism: str, from_detail: str, to_detail: str) -> list[dict]:
    """옮길 finding 과 그 새 cluster_key 목록(쓰지 않는다). 저장된 cluster_key 는 바이트 불변이다."""
    from app import narrative  # noqa: PLC0415 — narrative 는 learning 을 import 하지 않는다.

    rows = store.query(
        "SELECT finding_id, cluster_key, mechanism, mechanism_detail, change_kind, subject_key, owner_sub"
        " FROM rr_findings WHERE mechanism = ? AND mechanism_detail = ? ORDER BY finding_id",
        (mechanism, from_detail))
    out: list[dict] = []
    for row in rows:
        new_key = narrative.cluster_key_of(_s(row["mechanism"]), to_detail,
                                           _s(row["subject_key"]), _s(row["change_kind"]))
        if new_key == _s(row["cluster_key"]):
            continue
        out.append({"finding_id": _s(row["finding_id"]), "old_cluster_key": _s(row["cluster_key"]),
                    "new_cluster_key": new_key, "owner_sub": _s(row["owner_sub"]),
                    "from_detail": from_detail, "to_detail": to_detail})
    return out


def apply_remap(store: RiskStore, rows: Sequence[Mapping[str, Any]], *,
                owner_sub: str | None = None) -> dict:
    """별칭 행만 더한다 — rr_findings.cluster_key 는 건드리지 않는다(인용은 별칭 해석으로 이어진다).

    멱등이다 — 이미 이어진 쌍은 건너뛰므로 2회 실행에 새 행이 0 이다.
    """
    written = 0
    seen: set[tuple[str, str]] = set()
    for row in rows:
        pair = (row["old_cluster_key"], row["new_cluster_key"])
        if pair in seen:
            continue
        seen.add(pair)
        if resolve_cluster_key(store, row["old_cluster_key"]) == row["new_cluster_key"]:
            continue
        try:
            registry.add_cluster_alias(store, row["old_cluster_key"], row["new_cluster_key"],
                                       owner_sub=owner_sub or row["owner_sub"], reason="taxonomy_major",
                                       evidence={"from_detail": row["from_detail"],
                                                 "to_detail": row["to_detail"], "by": REMAP_DECIDED_BY})
        except AppError:
            continue                      # 이미 있는 별칭·홉 초과는 건너뛴다(멱등)
        written += 1
    mined = mine_patterns(store, owner_sub=owner_sub) or {}
    return {"aliases_written": written,
            "patterns_touched": len(mined.get("created") or ()) + len(mined.get("updated") or ())}
