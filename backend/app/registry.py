# 등록부 병합·verdict 후보·완결 레벨 C1~C3·무효화(stale/superseded)·통합 보고서 조립 — plan §4.7·§4.8·§6.9
from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from app import common, config
from app.errors import AppError
from app.risk_store import RiskStore

# ---------------------------------------------------------------- 상수(plan §4.7.1·§4.4.3·§6.9)

SEVERITY_ORDER: dict[str, int] = {"경미": 1, "중대": 2, "치명": 3}
SEV3_TO_SEVERITY: dict[int, str] = {1: "경미", 2: "중대", 3: "치명"}
JUDGEMENT_ORDER: dict[str, int] = {"OK": 0, "undetermined": 1, "WARNING": 2, "FAIL": 3}
GRADE_ORDER: dict[str, int] = {"경험칙": 0, "도구예측": 1, "문헌·규격": 2, "측정": 3}
W_GRADE: dict[str, float] = {"측정": 1.0, "도구예측": 0.9, "문헌·규격": 0.8, "경험칙": 0.6}
W_DET: dict[str, float] = {"field-only": 3.0, "test-only": 2.0, "unknown": 2.0, "sim-detectable": 1.0}

# 지정 반대석 키(plan §4.3.1 contested_by · §6.6.2).
ADVERSARY_KEY = "delib-baseline-defender"

# rr_registry 의 PK 는 (target_key, cluster_key) 라 한 cluster_key 를 risk·improvement 두 행으로 나눌 수 없다.
# plan §4.7.1 의 '두 행으로 분리' 를 지키면서 PK 를 깨지 않도록 improvement 행만 접미를 붙여 저장한다.
# 접미는 URL 경로 조각(PUT /api/registry/{cluster}/status)에 안전한 문자만 쓴다. 원래 키는 merged_json.cluster_key 에 남는다.
IMPROVEMENT_SUFFIX = ".imp"

# 기여 행을 만들지 않는 change_kind(plan §4.7.1 마지막 줄).
NO_CONTRIB_CHANGE_KINDS = frozenset({"discretization", "none"})

# rr_delta_priors 재합산 스탬프.
STATS_VERSION = "1.0"

# 커버리지 종결·비종결(plan §6.8.2).
TERMINAL_STATUSES = ("done", "done_weak", "abstain", "skipped", "deferred", "carried")
NONTERMINAL_STATUSES = ("pending", "assigned", "running", "failed")

# 완결 레벨 단조 증가 순서(plan §6.9).
LEVEL_ORDER: dict[str, int] = {"C0": 0, "C1": 1, "C2": 2, "C2(closed)": 3, "C3": 4}

# character facet 8종 표시 순서(plan §4.6.2·§4.7.3 (c)).
FACET_ORDER = ("intent", "constraint", "anomaly", "lineage", "vulnerability", "strength", "tradeoff", "unknown")
CHARACTER_STATUS_ORDER: dict[str, int] = {"confirmed": 3, "panel": 2, "seed": 1, "superseded": 0}

# RA rich_text 분할 상한(plan §0.6 저장 상한).
RICH_TEXT_LIMIT = 1900

# C2 strong 비율 하한(plan §0.6 완결 행).
STRONG_RATIO_MIN = 0.7
# C3 skipped 상한 비율.
SKIPPED_RATIO_MAX = 0.05

_REGISTRY_COLUMNS = (
    "target_key, cluster_key, owner_sub, visibility, merged_json, support, contested, direction, "
    "mechanism, mechanism_detail, change_kind, subject_key, severity, sev3, judgement, evidence_grade, "
    "precedent, weak_subject, priority, status, verified_by_json, stale_json, superseded_by, ra_entity_id, updated_at"
)

# 병합이 다시 계산하는 열(사람·라벨이 정하는 status·verified_by_json·stale_json·superseded_by 는 건드리지 않는다).
_MERGE_OWNED_COLUMNS = (
    "merged_json", "support", "contested", "direction", "mechanism", "mechanism_detail", "change_kind",
    "subject_key", "severity", "sev3", "judgement", "evidence_grade", "precedent", "weak_subject", "priority",
)


# ---------------------------------------------------------------- 작은 도우미


def _loads(text: Any, default: Any) -> Any:
    """JSON 문자열을 읽는다. None·빈 문자열·깨진 JSON 은 default 로 강등한다(예외를 삼키지 않고 기본값으로 표기)."""
    if text is None or text == "":
        return default
    if isinstance(text, (dict, list)):
        return text
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _clean_str(value: Any) -> str:
    return "" if value is None else str(value)


def _sev3_of(severity: str | None, fallback: int | None) -> int:
    if severity in SEVERITY_ORDER:
        return SEVERITY_ORDER[severity]
    if isinstance(fallback, int) and fallback in SEV3_TO_SEVERITY:
        return fallback
    return 1


def split_rich_text(text: str, limit: int = RICH_TEXT_LIMIT) -> list[str]:
    """RA rich_text 상한(1900자)으로 자른다. 줄 경계를 우선 지키고 한 줄이 상한을 넘으면 그 줄만 자른다."""
    if not text:
        return [""]
    chunks: list[str] = []
    buf = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = line if not buf else buf + "\n" + line
        if len(candidate) > limit:
            chunks.append(buf)
            buf = line
        else:
            buf = candidate
    if buf or not chunks:
        chunks.append(buf)
    return chunks


def strip_improvement_suffix(cluster_key: str) -> str:
    """저장 키에서 improvement 접미를 떼어 원래 cluster_key(sha1 12자)를 돌려준다."""
    if cluster_key.endswith(IMPROVEMENT_SUFFIX):
        return cluster_key[: -len(IMPROVEMENT_SUFFIX)]
    return cluster_key


def _ckeys_of_subject(subject_key: str) -> list[str]:
    """subject_key 문자열에서 ck: 조각만 뽑는다(파트 1개·계면 2개. dim:·asm: 는 ckey 가 없다)."""
    return [p for p in _clean_str(subject_key).split("|") if p.startswith("ck:")]


# ---------------------------------------------------------------- §4.7.1 등록부 병합


def _load_findings(store: RiskStore, target_key: str) -> list[dict]:
    """이 타깃의 finding·gain 전부(status 무관, plan §4.7.1 입력 정의)."""
    rows = store.query(
        "SELECT finding_id, claim_uid, panel_id, opinion_id, owner_sub, visibility, direction, domain, "
        "mechanism, mechanism_detail, change_kind, subject_key, ckeys_json, severity, sev3, judgement, "
        "detectability, detect_tool, evidence_grade, precedent, cluster_key, finding_json, created_at "
        "FROM rr_findings WHERE target_key = ? ORDER BY finding_id",
        (target_key,),
    )
    out: list[dict] = []
    for row in rows:
        item = dict(row)
        item["_json"] = _loads(item.get("finding_json"), {})
        out.append(item)
    return out


def _bucket_of(direction: str | None) -> str:
    """direction 버킷 — improvement 는 따로 묶고 risk·neutral 은 한 행으로 본다(plan §4.7.1 '병합 시 분리')."""
    return "improvement" if direction == "improvement" else "risk"


def _representative(members: list[dict]) -> dict:
    """대표 finding — evidence_grade 최고 → 제기 좌석 수 최고 → 최신 → finding_id 순(결정론 타이브레이크)."""
    def key(item: dict) -> tuple:
        grade = GRADE_ORDER.get(_clean_str(item.get("evidence_grade")), -1)
        raised = len(_as_list(item["_json"].get("raised_by")))
        created = item.get("created_at") or 0
        return (-grade, -raised, -created, _clean_str(item.get("finding_id")))

    return sorted(members, key=key)[0]


def _merge_cluster(target_key: str, stored_key: str, base_key: str, bucket: str, members: list[dict]) -> dict:
    """한 클러스터의 집계 행을 만든다(plan §4.7.1 병합 규칙)."""
    members = sorted(members, key=lambda m: _clean_str(m.get("finding_id")))

    panels = sorted({_clean_str(m.get("panel_id")) for m in members if m.get("panel_id")})
    support = len(panels) if panels else len(members)

    contested = 0
    contest_notes: list[dict] = []
    raised_by: list[str] = []
    cites: list[dict] = []
    seen_refs: set[str] = set()
    feature_snapshot: dict[str, Any] = {}
    resolving_checks: set[str] = set()
    names: list[str] = []
    domains: list[str] = []
    severity_counts: dict[str, int] = {}
    precedent_counts: dict[str, int] = {}
    direction_counts: dict[str, int] = {}
    weak_subject = False
    w_det = 1.0

    for m in members:
        fj = m["_json"]
        contested_by = [str(x) for x in _as_list(fj.get("contested_by"))]
        if ADVERSARY_KEY in contested_by:
            contested += 1
        if contested_by:
            note = _clean_str(fj.get("contest_note"))
            contest_notes.append({"finding_id": m["finding_id"], "by": sorted(set(contested_by)), "note": note})
        for key in _as_list(fj.get("raised_by")):
            if str(key) not in raised_by:
                raised_by.append(str(key))
        for cite in _as_list(fj.get("cites")):
            if not isinstance(cite, dict):
                continue
            ref = _clean_str(cite.get("ref"))
            if not ref or ref in seen_refs:
                continue
            seen_refs.add(ref)
            cites.append({"ref": ref, "quote": _clean_str(cite.get("quote"))})
        snap = fj.get("feature_snapshot")
        if isinstance(snap, dict):
            for ref, value in snap.items():
                feature_snapshot.setdefault(str(ref), value)
        check = fj.get("resolving_check")
        if isinstance(check, dict) and check.get("ref"):
            resolving_checks.add(f"{_clean_str(check.get('kind')) or 'tool'}:{_clean_str(check.get('ref'))}")
        for check in _as_list(fj.get("resolving_checks")):
            if isinstance(check, dict) and check.get("ref"):
                resolving_checks.add(f"{_clean_str(check.get('kind')) or 'tool'}:{_clean_str(check.get('ref'))}")
        subject = fj.get("subject") if isinstance(fj.get("subject"), dict) else {}
        for name in _as_list(subject.get("names")):
            if str(name) not in names:
                names.append(str(name))
        if fj.get("subject_unresolved") or not _clean_str(m.get("subject_key")):
            weak_subject = True
        domain = _clean_str(m.get("domain"))
        if domain and domain not in domains:
            domains.append(domain)

        sev = _clean_str(m.get("severity")) or SEV3_TO_SEVERITY.get(_sev3_of(None, m.get("sev3")), "경미")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
        prec = _clean_str(m.get("precedent")) or "none"
        precedent_counts[prec] = precedent_counts.get(prec, 0) + 1
        d = _clean_str(m.get("direction")) or "risk"
        direction_counts[d] = direction_counts.get(d, 0) + 1
        level = _clean_str(m.get("detectability")) or _clean_str(
            (fj.get("detectability") or {}).get("level") if isinstance(fj.get("detectability"), dict) else ""
        )
        w_det = max(w_det, W_DET.get(level, 2.0))

    severity = max(severity_counts, key=lambda s: SEVERITY_ORDER.get(s, 0)) if severity_counts else "경미"
    sev3 = SEVERITY_ORDER.get(severity, 1)
    judgement = "OK"
    for m in members:
        j = _clean_str(m.get("judgement")) or "undetermined"
        if JUDGEMENT_ORDER.get(j, 1) > JUDGEMENT_ORDER.get(judgement, 0):
            judgement = j
    grade = "경험칙"
    for m in members:
        g = _clean_str(m.get("evidence_grade")) or "경험칙"
        if GRADE_ORDER.get(g, 0) > GRADE_ORDER.get(grade, 0):
            grade = g
    # precedent 는 최빈, 동률이면 out_of_range 우선(plan §4.7.1).
    best_n = max(precedent_counts.values()) if precedent_counts else 0
    tied = sorted(k for k, v in precedent_counts.items() if v == best_n)
    precedent = "out_of_range" if "out_of_range" in tied else (tied[0] if tied else "none")
    # direction 은 버킷 안 최빈(improvement 버킷은 improvement 고정, risk 버킷은 risk·neutral 중 최빈·동률 risk).
    if bucket == "improvement":
        direction = "improvement"
    else:
        best = max(direction_counts.values()) if direction_counts else 0
        cand = sorted(k for k, v in direction_counts.items() if v == best)
        direction = "risk" if "risk" in cand else (cand[0] if cand else "risk")

    rep = _representative(members)
    priority = float(sev3) * w_det * W_GRADE.get(grade, 0.6)
    if contested:
        priority *= 0.8
    priority = round(priority, 6)

    merged = {
        "cluster_key": base_key,
        "stored_cluster_key": stored_key,
        "direction": direction,
        "claim": _clean_str(rep["_json"].get("claim")),
        "claim_finding_id": rep["finding_id"],
        "warrant": _clean_str(rep["_json"].get("warrant")),
        "member_ids": [m["finding_id"] for m in members],
        "panels": panels,
        "raised_by": sorted(raised_by),
        "contest_notes": contest_notes,
        "cites": cites,
        "feature_snapshot": feature_snapshot,
        "resolving_checks": sorted(resolving_checks),
        "names": names,
        "domains": domains,
        "severity_counts": severity_counts,
        "precedent_counts": precedent_counts,
        "trigger_condition": _clean_str(rep["_json"].get("trigger_condition")),
        "owner_domain": _clean_str(rep["_json"].get("owner_domain")),
    }

    return {
        "target_key": target_key,
        "cluster_key": stored_key,
        "owner_sub": _clean_str(rep.get("owner_sub")),
        "visibility": _clean_str(rep.get("visibility")) or "private",
        "merged_json": common.canonical_json(merged),
        "support": support,
        "contested": contested,
        "direction": direction,
        "mechanism": _clean_str(rep.get("mechanism")) or "unclassified",
        "mechanism_detail": _clean_str(rep.get("mechanism_detail")),
        "change_kind": _clean_str(rep.get("change_kind")),
        "subject_key": _clean_str(rep.get("subject_key")),
        "severity": severity,
        "sev3": sev3,
        "judgement": judgement,
        "evidence_grade": grade,
        "precedent": precedent,
        "weak_subject": 1 if weak_subject else 0,
        "priority": priority,
    }


def _write_registry_row(store: RiskStore, row: dict, now: int) -> str:
    """등록부 행 1건 UPSERT. 집계값이 그대로면 아무것도 쓰지 않는다(재병합 멱등 — plan §9.4 (12))."""
    existing = store.query_one(
        "SELECT " + ", ".join(_MERGE_OWNED_COLUMNS) + " FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
        (row["target_key"], row["cluster_key"]),
    )
    if existing is not None:
        same = all(existing[col] == row[col] for col in _MERGE_OWNED_COLUMNS)
        if same:
            return "unchanged"
        sets = ", ".join(f"{col} = :{col}" for col in _MERGE_OWNED_COLUMNS)
        params = {col: row[col] for col in _MERGE_OWNED_COLUMNS}
        params.update({"target_key": row["target_key"], "cluster_key": row["cluster_key"], "updated_at": now})
        store.execute(
            f"UPDATE rr_registry SET {sets}, updated_at = :updated_at "
            "WHERE target_key = :target_key AND cluster_key = :cluster_key",
            params,
        )
        return "updated"
    store.execute(
        "INSERT INTO rr_registry (target_key, cluster_key, owner_sub, visibility, merged_json, support, contested, "
        "direction, mechanism, mechanism_detail, change_kind, subject_key, severity, sev3, judgement, evidence_grade, "
        "precedent, weak_subject, priority, status, verified_by_json, stale_json, updated_at) "
        "VALUES (:target_key, :cluster_key, :owner_sub, :visibility, :merged_json, :support, :contested, :direction, "
        ":mechanism, :mechanism_detail, :change_kind, :subject_key, :severity, :sev3, :judgement, :evidence_grade, "
        ":precedent, :weak_subject, :priority, 'open', NULL, NULL, :updated_at)",
        {**row, "updated_at": now},
    )
    return "inserted"


def _recompute_contrib(store: RiskStore, target_key: str, owner_sub: str, rows: list[dict], now: int) -> set[tuple]:
    """이 타깃의 rr_delta_contrib 기여를 다시 계산해 덮어쓰고 영향받은 조합 키를 돌려준다(증분 += 없음)."""
    combos: dict[tuple, dict] = {}
    for row in rows:
        change_kind = row["change_kind"] or ""
        if change_kind in NO_CONTRIB_CHANGE_KINDS or not change_kind:
            continue
        key = (change_kind, row["mechanism"] or "unclassified", row["mechanism_detail"] or "")
        acc = combos.setdefault(key, {"n_raised": 0, "n_improvement": 0, "sev_hist": {}, "checks": set()})
        support = int(row["support"])
        if row["direction"] == "risk":
            acc["n_raised"] += support
            sev = row["severity"]
            acc["sev_hist"][sev] = acc["sev_hist"].get(sev, 0) + support
        elif row["direction"] == "improvement":
            acc["n_improvement"] += support
        acc["checks"].update(_loads(row["merged_json"], {}).get("resolving_checks", []))

    affected: set[tuple] = set(combos)
    old = store.query(
        "SELECT change_kind, mechanism, mechanism_detail FROM rr_delta_contrib WHERE target_key = ?",
        (target_key,),
    )
    for row in old:
        key = (row["change_kind"], row["mechanism"], row["mechanism_detail"])
        affected.add(key)
        if key not in combos:
            store.execute(
                "DELETE FROM rr_delta_contrib WHERE change_kind = ? AND mechanism = ? AND mechanism_detail = ? "
                "AND target_key = ?",
                (*key, target_key),
            )

    for key, acc in sorted(combos.items()):
        params = {
            "change_kind": key[0], "mechanism": key[1], "mechanism_detail": key[2], "target_key": target_key,
            "owner_sub": owner_sub, "n_raised": acc["n_raised"], "n_improvement": acc["n_improvement"],
            "sev_hist_json": common.canonical_json(acc["sev_hist"]),
            "resolving_checks_json": common.canonical_json(sorted(acc["checks"])),
        }
        current = store.query_one(
            "SELECT n_raised, n_improvement, sev_hist_json, resolving_checks_json FROM rr_delta_contrib "
            "WHERE change_kind = ? AND mechanism = ? AND mechanism_detail = ? AND target_key = ?",
            (*key, target_key),
        )
        if current is not None and all(
            current[col] == params[col] for col in ("n_raised", "n_improvement", "sev_hist_json", "resolving_checks_json")
        ):
            continue
        store.execute(
            "INSERT INTO rr_delta_contrib (change_kind, mechanism, mechanism_detail, target_key, owner_sub, "
            "n_raised, n_improvement, sev_hist_json, resolving_checks_json, updated_at) "
            "VALUES (:change_kind, :mechanism, :mechanism_detail, :target_key, :owner_sub, :n_raised, "
            ":n_improvement, :sev_hist_json, :resolving_checks_json, :updated_at) "
            "ON CONFLICT(change_kind, mechanism, mechanism_detail, target_key) DO UPDATE SET "
            "owner_sub = excluded.owner_sub, n_raised = excluded.n_raised, n_improvement = excluded.n_improvement, "
            "sev_hist_json = excluded.sev_hist_json, resolving_checks_json = excluded.resolving_checks_json, "
            "updated_at = excluded.updated_at",
            {**params, "updated_at": now},
        )
    return affected


def _recompute_priors(store: RiskStore, combos: Iterable[tuple], now: int) -> int:
    """영향받은 조합의 rr_delta_priors 를 rr_delta_contrib 합으로 재합산한다(n_verified·n_dismissed 는 §7.4 몫)."""
    written = 0
    for key in sorted(combos):
        rows = store.query(
            "SELECT target_key, n_raised, n_improvement, sev_hist_json, resolving_checks_json "
            "FROM rr_delta_contrib WHERE change_kind = ? AND mechanism = ? AND mechanism_detail = ? "
            "ORDER BY target_key",
            key,
        )
        n_raised = sum(int(r["n_raised"] or 0) for r in rows)
        n_improvement = sum(int(r["n_improvement"] or 0) for r in rows)
        n_targets = len({r["target_key"] for r in rows})
        sev_hist: dict[str, int] = {}
        check_freq: dict[str, int] = {}
        for r in rows:
            for sev, n in _loads(r["sev_hist_json"], {}).items():
                sev_hist[sev] = sev_hist.get(sev, 0) + int(n)
            for check in _loads(r["resolving_checks_json"], []):
                check_freq[str(check)] = check_freq.get(str(check), 0) + 1
        top = [c for c, _ in sorted(check_freq.items(), key=lambda kv: (-kv[1], kv[0]))[:3]]
        params = {
            "change_kind": key[0], "mechanism": key[1], "mechanism_detail": key[2],
            "n_raised": n_raised, "n_targets": n_targets, "n_improvement": n_improvement,
            "sev_hist_json": common.canonical_json(sev_hist),
            "top_resolving_checks_json": common.canonical_json(top),
        }
        current = store.query_one(
            "SELECT n_raised, n_targets, n_improvement, sev_hist_json, top_resolving_checks_json "
            "FROM rr_delta_priors WHERE change_kind = ? AND mechanism = ? AND mechanism_detail = ?",
            key,
        )
        cols = ("n_raised", "n_targets", "n_improvement", "sev_hist_json", "top_resolving_checks_json")
        if current is not None and all(current[c] == params[c] for c in cols):
            continue
        store.execute(
            "INSERT INTO rr_delta_priors (change_kind, mechanism, mechanism_detail, n_raised, n_targets, "
            "n_improvement, sev_hist_json, top_resolving_checks_json, stats_version, updated_at) "
            "VALUES (:change_kind, :mechanism, :mechanism_detail, :n_raised, :n_targets, :n_improvement, "
            ":sev_hist_json, :top_resolving_checks_json, :stats_version, :updated_at) "
            "ON CONFLICT(change_kind, mechanism, mechanism_detail) DO UPDATE SET "
            "n_raised = excluded.n_raised, n_targets = excluded.n_targets, n_improvement = excluded.n_improvement, "
            "sev_hist_json = excluded.sev_hist_json, top_resolving_checks_json = excluded.top_resolving_checks_json, "
            "stats_version = excluded.stats_version, updated_at = excluded.updated_at",
            {**params, "stats_version": STATS_VERSION, "updated_at": now},
        )
        written += 1
    return written


def merge(store: RiskStore, target_key: str, *, owner_sub: str | None = None) -> dict:
    """타깃의 finding 을 cluster_key 로 병합해 rr_registry·rr_delta_contrib·rr_delta_priors 를 다시 만든다.

    plan §4.7.1 — 패널이 끝날 때마다 다시 부르며 멱등이다(같은 finding 집합이면 support 가 중복 가산되지 않는다).
    같은 cluster_key 에 risk 와 improvement 가 섞이면 두 행으로 나누고 improvement 행에 IMPROVEMENT_SUFFIX 를 붙인다.
    """
    now = common.now_epoch()
    findings = _load_findings(store, target_key)
    if owner_sub is None:
        row = store.query_one("SELECT owner_sub FROM rr_targets WHERE target_key = ?", (target_key,))
        owner_sub = _clean_str(row["owner_sub"]) if row is not None else ""

    buckets: dict[tuple[str, str], list[dict]] = {}
    for item in findings:
        base = _clean_str(item.get("cluster_key"))
        if not base:
            continue
        buckets.setdefault((base, _bucket_of(_clean_str(item.get("direction")))), []).append(item)

    rows: list[dict] = []
    for (base, bucket), members in sorted(buckets.items()):
        stored = base + IMPROVEMENT_SUFFIX if bucket == "improvement" else base
        row = _merge_cluster(target_key, stored, base, bucket, members)
        if not row["owner_sub"]:
            row["owner_sub"] = owner_sub
        rows.append(row)

    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    with store.tx():
        for row in rows:
            counts[_write_registry_row(store, row, now)] += 1
        affected = _recompute_contrib(store, target_key, owner_sub or "", rows, now)
        priors_written = _recompute_priors(store, affected, now)
        candidate = verdict_candidate(store, target_key)
        current = store.query_one("SELECT verdict_candidate FROM rr_targets WHERE target_key = ?", (target_key,))
        if current is not None and current["verdict_candidate"] != candidate["verdict"]:
            store.execute(
                "UPDATE rr_targets SET verdict_candidate = ?, updated_at = ? WHERE target_key = ?",
                (candidate["verdict"], now, target_key),
            )

    return {
        "target_key": target_key,
        "findings": len(findings),
        "clusters": len(rows),
        "inserted": counts["inserted"],
        "updated": counts["updated"],
        "unchanged": counts["unchanged"],
        "priors_written": priors_written,
        "verdict_candidate": candidate["verdict"],
    }


# ---------------------------------------------------------------- §4.7.2 verdict 후보


def _registry_rows(store: RiskStore, target_key: str, statuses: Sequence[str] | None = None) -> list[dict]:
    sql = "SELECT " + _REGISTRY_COLUMNS + " FROM rr_registry WHERE target_key = ?"
    params: list[Any] = [target_key]
    if statuses:
        sql += " AND status IN (" + ",".join("?" for _ in statuses) + ")"
        params.extend(statuses)
    sql += " ORDER BY priority DESC, cluster_key ASC"
    return [dict(r) for r in store.query(sql, params)]


def registry_rows(store: RiskStore, target_key: str) -> list[dict]:
    """GET /api/targets/{key}/registry 용 — 등록부 전 행(priority 내림차순)에 merged_json 을 풀어 붙인다."""
    out = []
    for row in _registry_rows(store, target_key):
        row["merged"] = _loads(row.get("merged_json"), {})
        out.append(row)
    return out


def verdict_candidate(store: RiskStore, target_key: str) -> dict:
    """등록부 집계로 verdict 후보를 낸다(plan §4.7.2 — 후보일 뿐 자동 승인은 없다)."""
    rows = _registry_rows(store, target_key, ("open", "verified"))
    counts = {"clusters": len(rows), "FAIL": 0, "WARNING": 0, "OK": 0, "undetermined": 0}
    fail_uncontested = 0
    all_heuristic = True
    for row in rows:
        j = _clean_str(row["judgement"]) or "undetermined"
        counts[j] = counts.get(j, 0) + 1
        if j == "FAIL" and int(row["contested"] or 0) < int(row["support"] or 0):
            fail_uncontested += 1
        if _clean_str(row["evidence_grade"]) != "경험칙":
            all_heuristic = False

    reasons: list[str] = []
    if not rows:
        return {"verdict": "undetermined", "counts": counts, "reasons": ["클러스터 0건"]}
    if all_heuristic:
        reasons.append("근거 등급이 전부 경험칙")
    if counts["undetermined"] * 2 > len(rows):
        reasons.append("undetermined 클러스터 과반")
    if reasons:
        return {"verdict": "undetermined", "counts": counts, "reasons": reasons}
    if fail_uncontested:
        return {"verdict": "no-go", "counts": counts, "reasons": [f"미기각 FAIL 클러스터 {fail_uncontested}건"]}
    if counts["WARNING"]:
        return {"verdict": "conditional", "counts": counts, "reasons": [f"WARNING 클러스터 {counts['WARNING']}건"]}
    if counts["OK"] == len(rows):
        return {"verdict": "go", "counts": counts, "reasons": ["모든 클러스터 OK"]}
    return {"verdict": "undetermined", "counts": counts, "reasons": ["FAIL 클러스터가 전부 반대석 기각 상태"]}


def set_status(
    store: RiskStore,
    cluster_key: str,
    status: str,
    *,
    owner_sub: str,
    target_key: str | None = None,
    evidence_ref: str | None = None,
    note: str | None = None,
    actor: str | None = None,
) -> dict:
    """PUT /api/registry/{cluster}/status — 사람·라벨이 정하는 상태 전이(plan §4.7.1).

    verified·dismissed 는 라벨(§7.6) 생성이 뒤따르고 mitigated 는 사람 표기만이다. 라벨 생성 자체는 이 모듈이 하지 않는다.
    """
    if status not in ("verified", "dismissed", "mitigated"):
        raise AppError("E100", f"등록부 상태 어휘 밖입니다: {status}", 422)
    now = common.now_epoch()
    sql = "SELECT target_key, cluster_key, verified_by_json FROM rr_registry WHERE cluster_key = ? AND owner_sub = ?"
    params: list[Any] = [cluster_key, owner_sub]
    if target_key:
        sql += " AND target_key = ?"
        params.append(target_key)
    rows = store.query(sql + " ORDER BY target_key", params)
    if not rows:
        raise AppError("E404", f"등록부 클러스터를 찾지 못했습니다: {cluster_key}", 404)
    updated = 0
    with store.tx():
        for row in rows:
            log = _loads(row["verified_by_json"], [])
            log.append({
                "status": status,
                "by": actor or owner_sub,
                "at": now,
                "evidence_ref": evidence_ref or "",
                "note": note or "",
            })
            store.execute(
                "UPDATE rr_registry SET status = ?, verified_by_json = ?, updated_at = ? "
                "WHERE target_key = ? AND cluster_key = ?",
                (status, common.canonical_json(log), now, row["target_key"], row["cluster_key"]),
            )
            updated += 1
    return {"cluster_key": cluster_key, "status": status, "updated": updated, "label_needed": status != "mitigated"}


# ---------------------------------------------------------------- §4.8 무효화(stale · superseded)


def invalidate(
    store: RiskStore,
    old_target_key: str,
    new_target_key: str,
    changed_ckeys: Iterable[str],
    *,
    resolve_ckey: Callable[[str], str] | None = None,
    mark_unraised: bool = False,
) -> dict:
    """새 타깃 T′ 기준으로 옛 타깃 T 의 등록부 행에 stale·superseded 를 표기한다(plan §4.8 3·6).

    행은 지우지 않는다 — stale 은 `stale_json[T′].stale`, 재제기된 클러스터는 status='superseded'(superseded_by=`T′#키`),
    `mark_unraised=True`(T′ 의 C1 완료 시점)면 다시 제기되지 않은 클러스터에 `stale_json[T′].unraised` 를 남긴다.
    ckey 비교는 resolve_ckey(§5.9.1, merged_into 끝까지 해석)를 거친 유효 ckey 로 한다.
    """
    resolve = resolve_ckey or (lambda ck: ck)
    changed = {resolve(str(ck)) for ck in changed_ckeys if ck}
    now = common.now_epoch()

    new_base_keys = {
        strip_improvement_suffix(_clean_str(r["cluster_key"]))
        for r in store.query("SELECT cluster_key FROM rr_registry WHERE target_key = ?", (new_target_key,))
    }
    rows = store.query(
        "SELECT target_key, cluster_key, subject_key, merged_json, stale_json, status, superseded_by "
        "FROM rr_registry WHERE target_key = ? ORDER BY cluster_key",
        (old_target_key,),
    )

    stale_n = superseded_n = unraised_n = 0
    with store.tx():
        for row in rows:
            merged = _loads(row["merged_json"], {})
            own = {resolve(ck) for ck in _ckeys_of_subject(row["subject_key"])}
            for member_ck in merged.get("cited_ckeys", []) or []:
                own.add(resolve(str(member_ck)))
            for ref in merged.get("cites", []) or []:
                ck = ref.get("ckey") if isinstance(ref, dict) else None
                if ck:
                    own.add(resolve(str(ck)))
            entry = dict(_loads(row["stale_json"], {}).get(new_target_key, {}))
            before = dict(entry)
            if own & changed:
                entry["stale"] = True
            base = strip_improvement_suffix(_clean_str(row["cluster_key"]))
            status = row["status"]
            superseded_by = row["superseded_by"]
            if base in new_base_keys:
                if status not in ("verified", "dismissed", "mitigated"):
                    status = "superseded"
                    superseded_by = f"{new_target_key}#{row['cluster_key']}"
            elif mark_unraised:
                entry["unraised"] = True

            changed_row = (entry != before) or status != row["status"] or superseded_by != row["superseded_by"]
            if not changed_row:
                continue
            stale_map = _loads(row["stale_json"], {})
            stale_map[new_target_key] = entry
            store.execute(
                "UPDATE rr_registry SET stale_json = ?, status = ?, superseded_by = ?, updated_at = ? "
                "WHERE target_key = ? AND cluster_key = ?",
                (common.canonical_json(stale_map), status, superseded_by, now,
                 row["target_key"], row["cluster_key"]),
            )
            stale_n += 1 if entry.get("stale") and not before.get("stale") else 0
            superseded_n += 1 if status == "superseded" and row["status"] != "superseded" else 0
            unraised_n += 1 if entry.get("unraised") and not before.get("unraised") else 0

    return {
        "old_target_key": old_target_key,
        "new_target_key": new_target_key,
        "changed_ckeys": len(changed),
        "stale": stale_n,
        "superseded": superseded_n,
        "unraised": unraised_n,
    }


# ---------------------------------------------------------------- §6.9 완결 판정 C0~C3


def _coverage_rows(store: RiskStore, target_key: str) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT agent_key, domain, origin, status, panel_id, opinion_id, reason FROM rr_coverage "
        "WHERE target_key = ? ORDER BY agent_key",
        (target_key,),
    )]


def _roster_rows(store: RiskStore, target_key: str) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT agent_key, domain, ecad_dependent, rank_in_domain FROM rr_roster WHERE target_key = ? "
        "ORDER BY agent_key",
        (target_key,),
    )]


def _panel_rows(store: RiskStore, target_key: str) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT id, panel_no, tier, status, engine, tool_mode, conv_id, report_id, seats_json, "
        "risk_spec_json, risk_spec_parsed, quality_json FROM rr_panels WHERE target_key = ? ORDER BY panel_no",
        (target_key,),
    )]


def _contested_marking_done(store: RiskStore, target_key: str) -> bool:
    """반대석이 기각을 요구한 finding 이 전부 등록부 contested 로 표기됐는지(plan §6.9 C2 조건)."""
    contested_clusters = {
        strip_improvement_suffix(_clean_str(r["cluster_key"]))
        for r in store.query(
            "SELECT cluster_key FROM rr_registry WHERE target_key = ? AND contested > 0", (target_key,)
        )
    }
    for row in store.query(
        "SELECT cluster_key, finding_json FROM rr_findings WHERE target_key = ? ORDER BY finding_id", (target_key,)
    ):
        fj = _loads(row["finding_json"], {})
        if ADVERSARY_KEY in [str(x) for x in _as_list(fj.get("contested_by"))]:
            if strip_improvement_suffix(_clean_str(row["cluster_key"])) not in contested_clusters:
                return False
    return True


def _unresolved_parse_failures(panels: list[dict]) -> int:
    """미해결 spec_parse_failed 패널 수 — 재제출로 파싱됐거나 사람이 '제외' 표기한 패널은 빼고 센다."""
    n = 0
    for p in panels:
        if p["status"] not in ("done", "error"):
            continue
        if p["risk_spec_parsed"]:
            continue
        quality = _loads(p["quality_json"], {})
        if quality.get("spec_excluded"):
            continue
        n += 1
    return n


def close_level(store: RiskStore, target_key: str, *, persist: bool = True) -> dict:
    """완결 레벨 C0~C3 를 계산한다(plan §6.9). 레벨은 단조 증가만 하고 persist 면 rr_targets.level 에 반영한다."""
    target = store.query_one(
        "SELECT target_key, project_id, level, close_level, verdict_final, verdict_candidate "
        "FROM rr_targets WHERE target_key = ?",
        (target_key,),
    )
    if target is None:
        raise AppError("E404", f"타깃을 찾지 못했습니다: {target_key}", 404)

    roster = _roster_rows(store, target_key)
    coverage = _coverage_rows(store, target_key)
    panels = _panel_rows(store, target_key)
    cov_by_agent = {c["agent_key"]: c for c in coverage}
    roster_size = len(roster) or len(coverage)

    status_counts: dict[str, int] = {}
    for c in coverage:
        status_counts[c["status"]] = status_counts.get(c["status"], 0) + 1
    # 로스터에 있지만 원장 행이 아직 없는 좌석은 pending 으로 센다(회계 불변식 1 — 합 = roster_size).
    missing = [r for r in roster if r["agent_key"] not in cov_by_agent]
    if missing:
        status_counts["pending"] = status_counts.get("pending", 0) + len(missing)

    terminal_by_domain: dict[str, int] = {}
    roster_by_domain: dict[str, int] = {}
    deferred_by_domain: dict[str, int] = {}
    for r in roster:
        roster_by_domain[r["domain"]] = roster_by_domain.get(r["domain"], 0) + 1
    for c in coverage:
        if c["status"] in TERMINAL_STATUSES:
            terminal_by_domain[c["domain"]] = terminal_by_domain.get(c["domain"], 0) + 1
        if c["status"] == "deferred":
            deferred_by_domain[c["domain"]] = deferred_by_domain.get(c["domain"], 0) + 1

    required_domains = list(config.settings.risk_roster_domains) or sorted(roster_by_domain)
    c1_domains_ok = all(terminal_by_domain.get(d, 0) >= 1 for d in required_domains)
    tier_a_done = sum(1 for p in panels if p["tier"] == "A" and p["status"] == "done")
    c1 = bool(c1_domains_ok and tier_a_done >= 3)

    # C2 — 도메인별 종결 ≥ max(3, ceil(0.3·|d|)), |d|<3 이면 전원.
    depth_ok = True
    depth_detail: dict[str, dict] = {}
    for domain, size in sorted(roster_by_domain.items()):
        active = size - deferred_by_domain.get(domain, 0)
        if active <= 0:
            continue
        need = active if active < 3 else max(3, math.ceil(0.3 * active))
        have = terminal_by_domain.get(domain, 0) - deferred_by_domain.get(domain, 0)
        depth_detail[domain] = {"need": need, "have": have, "roster": size, "deferred": deferred_by_domain.get(domain, 0)}
        if have < need:
            depth_ok = False

    # strong 비율 — 웹 엔진 좌석만(MCP evidence_only 패널 좌석 제외).
    panel_by_id = {p["id"]: p for p in panels}
    strong = weak = 0
    for c in coverage:
        if c["status"] not in ("done", "done_weak"):
            continue
        panel = panel_by_id.get(c["panel_id"])
        if panel is not None and (panel["engine"] == "mcp" or panel["tool_mode"] == "evidence_only"):
            continue
        if c["status"] == "done":
            strong += 1
        else:
            weak += 1
    strong_ratio = (strong / (strong + weak)) if (strong + weak) else 0.0
    contested_ok = _contested_marking_done(store, target_key)
    parse_failed = _unresolved_parse_failures(panels)
    c2 = bool(c1 and depth_ok and strong_ratio >= STRONG_RATIO_MIN and contested_ok and parse_failed == 0)

    # C3 — deferred 아닌 로스터 전원 종결, skipped ≤5%, failed 0.
    non_deferred = [r for r in roster if cov_by_agent.get(r["agent_key"], {}).get("status") != "deferred"]
    non_deferred_n = len(non_deferred) or max(0, roster_size - status_counts.get("deferred", 0))
    all_terminal = all(
        cov_by_agent.get(r["agent_key"], {}).get("status") in TERMINAL_STATUSES for r in non_deferred
    ) and bool(non_deferred)
    skipped = status_counts.get("skipped", 0)
    failed = status_counts.get("failed", 0)
    skipped_ratio = (skipped / non_deferred_n) if non_deferred_n else 0.0
    c3 = bool(c2 and all_terminal and skipped_ratio <= SKIPPED_RATIO_MAX and failed == 0)

    target_close = _clean_str(target["close_level"]) or config.settings.risk_default_close_level
    if c3:
        level = "C3"
    elif c2:
        # 기본 마감 레벨이 C2 면 여기서 닫고, C3 면 Tier C 를 잇는다(plan §6.9).
        level = "C2(closed)" if target_close == "C2" else "C2"
    elif c1:
        level = "C1"
    else:
        level = "C0"

    stored = _clean_str(target["level"]) or "C0"
    if LEVEL_ORDER.get(stored, 0) > LEVEL_ORDER.get(level, 0):
        level = stored

    unseated = sum(status_counts.get(s, 0) for s in NONTERMINAL_STATUSES)

    if persist and level != stored:
        store.execute(
            "UPDATE rr_targets SET level = ?, updated_at = ? WHERE target_key = ?",
            (level, common.now_epoch(), target_key),
        )

    return {
        "target_key": target_key,
        "level": level,
        "previous_level": stored,
        "close_level": target_close,
        "roster_size": roster_size,
        "status_counts": status_counts,
        "unseated_n": unseated,
        "c1": c1,
        "c2": c2,
        "c3": c3,
        "detail": {
            "domains_terminal": {d: terminal_by_domain.get(d, 0) for d in required_domains},
            "tier_a_done": tier_a_done,
            "depth": depth_detail,
            "strong": strong,
            "done_weak": weak,
            "strong_ratio": round(strong_ratio, 4),
            "contested_marked": contested_ok,
            "spec_parse_failed": parse_failed,
            "skipped": skipped,
            "skipped_ratio": round(skipped_ratio, 4),
            "failed": failed,
        },
    }


# ---------------------------------------------------------------- §4.7.3 통합 보고서 블록(텍스트 조립)


def _target_context(store: RiskStore, target: dict) -> dict:
    """타깃이 가리키는 스냅샷·diff 의 summary_text·게이트·comparability·소스 id 를 모은다."""
    ctx: dict[str, Any] = {"summary_text": "", "gates": {}, "comparability": {}, "snapshot_ids": [], "sources": []}
    if target["kind"] == "diff":
        row = store.query_one(
            "SELECT id, base_snapshot_id, target_snapshot_id, summary_text, gates_json, comparability_json "
            "FROM rr_diffs WHERE id = ?",
            (target["ref_id"],),
        )
        if row is not None:
            ctx["summary_text"] = _clean_str(row["summary_text"])
            ctx["gates"] = _loads(row["gates_json"], {})
            ctx["comparability"] = _loads(row["comparability_json"], {})
            ctx["snapshot_ids"] = [row["base_snapshot_id"], row["target_snapshot_id"]]
    else:
        row = store.query_one(
            "SELECT snapshot_id, summary_text, gates_json FROM rr_states WHERE snapshot_id = ?",
            (target["ref_id"],),
        )
        if row is not None:
            ctx["summary_text"] = _clean_str(row["summary_text"])
            ctx["gates"] = _loads(row["gates_json"], {})
            ctx["snapshot_ids"] = [row["snapshot_id"]]
    for sid in ctx["snapshot_ids"]:
        snap = store.query_one(
            "SELECT id, ir_hash, source_ids_json, kinds_json FROM rr_snapshots WHERE id = ?", (sid,)
        )
        if snap is not None:
            ctx["sources"].append({
                "snapshot_id": snap["id"],
                "ir_hash": snap["ir_hash"],
                "kinds": _loads(snap["kinds_json"], []),
                "source_ids": _loads(snap["source_ids_json"], []),
            })
    return ctx


def _gate_lines(gates: dict) -> list[str]:
    lines = []
    for name in sorted(gates):
        value = gates[name]
        if isinstance(value, dict):
            state = value.get("pass")
            detail = value.get("effect") or value.get("reason") or ""
            lines.append(f"{name} pass={state} {detail}".rstrip())
        else:
            lines.append(f"{name} {value}")
    return lines


def _registry_table(rows: list[dict]) -> list[str]:
    """등록부 표 한 벌 — priority 순, 열 구성은 plan §4.7.3 results (a)."""
    header = ("cluster_key · direction · domain · mechanism.detail · change_kind · subject · severity/judgement · "
              "evidence_grade · precedent · support/contested · status · claim · cites")
    out = [header, "-" * len(header)]
    for row in rows:
        merged = _loads(row.get("merged_json"), {})
        claim = _clean_str(merged.get("claim"))[:160]
        cites = " ".join(f"[{c.get('ref')}]" for c in merged.get("cites", [])[:3] if isinstance(c, dict))
        subject = ", ".join(merged.get("names", [])) or _clean_str(row["subject_key"])
        domains = ",".join(merged.get("domains", []))
        out.append(
            f"{row['cluster_key']} · {row['direction']} · {domains} · "
            f"{row['mechanism']}.{row['mechanism_detail']} · {row['change_kind']} · {subject} · "
            f"{row['severity']}/{row['judgement']} · {row['evidence_grade']} · {row['precedent']} · "
            f"{row['support']}/{row['contested']} · {row['status']} · «{claim}» · {cites}"
        )
    if len(out) == 2:
        out.append("(행 없음)")
    return out


def _character_lines(store: RiskStore, project_id: str) -> list[str]:
    """과제 성격 — facet 8 순서로 status(confirmed>panel>seed) 상위 문장 각 ≤2(plan §4.7.3 results (c))."""
    rows = store.query(
        "SELECT facet, tag, tags_json, statement, polarity, cites_json, by_json, support_panels, status "
        "FROM rr_character WHERE project_id = ? AND status != 'superseded' ORDER BY id",
        (project_id,),
    )
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["facet"], []).append(dict(row))
    out: list[str] = []
    for facet in FACET_ORDER:
        items = grouped.get(facet, [])
        items.sort(key=lambda it: (
            -CHARACTER_STATUS_ORDER.get(_clean_str(it["status"]), 0),
            -int(it["support_panels"] or 0),
            _clean_str(it["statement"]),
        ))
        if not items:
            out.append(f"[{facet}] (없음)")
            continue
        for it in items[:2]:
            by = ",".join(str(x) for x in _loads(it["by_json"], []))
            cites = " ".join(
                f"[{c.get('ref')}]" for c in _loads(it["cites_json"], []) if isinstance(c, dict) and c.get("ref")
            )
            tags = ",".join(str(t) for t in _loads(it["tags_json"], [])) or _clean_str(it["tag"])
            out.append(
                f"[{facet}] {it['status']}({it['support_panels']}) «{_clean_str(it['statement'])}» "
                f"by={by} tags={tags} {cites}".rstrip()
            )
    return out


def _cross_domain_lines(panels: list[dict]) -> list[str]:
    """패널 risk_spec 의 cross_domain 항목을 패널 순서대로 모은다(plan §4.7.3 results (d))."""
    out: list[str] = []
    for p in panels:
        spec = _loads(p["risk_spec_json"], {})
        for item in _as_list(spec.get("cross_domain")):
            if isinstance(item, dict):
                text = _clean_str(item.get("claim")) or _clean_str(item.get("text"))
                pair = "↔".join(str(d) for d in _as_list(item.get("domains")))
                out.append(f"패널 {p['panel_no']} · {pair} · «{text[:160]}»")
            else:
                out.append(f"패널 {p['panel_no']} · «{_clean_str(item)[:160]}»")
    return out or ["(항목 없음)"]


def _minutes_lines(store: RiskStore, target_key: str, panels: list[dict], coverage: list[dict]) -> list[str]:
    out = ["[패널]"]
    for p in panels:
        spec = _loads(p["risk_spec_json"], {})
        quality = _loads(p["quality_json"], {})
        seats = _loads(p["seats_json"], [])
        seat_keys = ",".join(
            str(s.get("agent_key") if isinstance(s, dict) else s) for s in seats
        )
        rejected = sum(
            1 for f in store.query(
                "SELECT finding_json FROM rr_findings WHERE panel_id = ? ORDER BY finding_id", (p["id"],)
            )
            if ADVERSARY_KEY in [str(x) for x in _as_list(_loads(f["finding_json"], {}).get("contested_by"))]
        )
        out.append(
            f"panel_no={p['panel_no']} tier={p['tier']} status={p['status']} engine={p['engine']}/{p['tool_mode']} "
            f"conv_id={p['conv_id']} report_id={p['report_id']} seats=[{seat_keys}] "
            f"tool_calls_ok={quality.get('tool_calls_ok')} 반대석기각={rejected} verdict={spec.get('verdict')}"
        )
    if len(out) == 1:
        out.append("(패널 없음)")

    out.append("[커버리지 도메인×상태]")
    grid: dict[str, dict[str, int]] = {}
    for c in coverage:
        grid.setdefault(c["domain"], {})
        grid[c["domain"]][c["status"]] = grid[c["domain"]].get(c["status"], 0) + 1
    for domain in sorted(grid):
        counts = " ".join(f"{s}={n}" for s, n in sorted(grid[domain].items()))
        out.append(f"{domain} · {counts}")
    if not grid:
        out.append("(원장 행 없음)")

    out.append("[품질 플래그]")
    flags: list[str] = []
    for p in panels:
        quality = _loads(p["quality_json"], {})
        flag = quality.get("flag")
        for value in _as_list(flag):
            flags.append(f"panel_no={p['panel_no']} {value}")
        if not p["risk_spec_parsed"] and p["status"] in ("done", "error"):
            flags.append(f"panel_no={p['panel_no']} spec_parse_failed")
    out.extend(flags or ["(없음)"])
    return out


def build_report(store: RiskStore, target_key: str) -> dict:
    """통합 보고서 4블록을 조립한다(plan §4.7.3, RA deliberation 템플릿에 그대로 실린다).

    코드가 만드는 문장에는 판단어를 쓰지 않고 좌석의 claim 은 «» 인용으로만 싣는다(§4.10 린터 항목).
    """
    target = store.query_one(
        "SELECT target_key, owner_sub, kind, ref_id, project_id, base_project_id, ir_hash, level, close_level, "
        "verdict_candidate, verdict_final, verdict_note, external_sync_json, report_ids_json "
        "FROM rr_targets WHERE target_key = ?",
        (target_key,),
    )
    if target is None:
        raise AppError("E404", f"타깃을 찾지 못했습니다: {target_key}", 404)
    target = dict(target)

    ctx = _target_context(store, target)
    level_info = close_level(store, target_key, persist=False)
    rows = _registry_rows(store, target_key)
    risk_rows = [r for r in rows if r["direction"] != "improvement"]
    gain_rows = [r for r in rows if r["direction"] == "improvement"]
    panels = _panel_rows(store, target_key)
    coverage = _coverage_rows(store, target_key)
    candidate = verdict_candidate(store, target_key)

    project = store.query_one("SELECT id, code, name, stage FROM rr_projects WHERE id = ?", (target["project_id"],))

    # background
    bg: list[str] = []
    bg.append(f"[타깃] {target_key} · kind={target['kind']} · ref={target['ref_id']} · ir_hash={target['ir_hash']}")
    if project is not None:
        bg.append(f"[과제] {project['code']} {_clean_str(project['name'])} · stage={_clean_str(project['stage'])}")
    for src in ctx["sources"]:
        refs = ", ".join(
            f"{s.get('kind')}:{s.get('app_key')}:{s.get('ref')}" for s in src["source_ids"] if isinstance(s, dict)
        )
        bg.append(f"[소스] snapshot={src['snapshot_id']} ir={src['ir_hash']} kinds={','.join(map(str, src['kinds']))} {refs}")
    bg.append("[게이트] " + (" | ".join(_gate_lines(ctx["gates"])) or "(없음)"))
    if ctx["comparability"]:
        bg.append("[비교가능성] " + common.canonical_json(ctx["comparability"]))
    bg.append("[요약]")
    bg.append(ctx["summary_text"] or "(summary_text 없음)")
    bg.append(
        f"[완결] level={level_info['level']} · close_level={level_info['close_level']} · "
        f"roster={level_info['roster_size']}"
    )
    if level_info["level"] != "C3":
        bg.append(f"[배지] 미착석 {level_info['unseated_n']}명(C3 미달)")

    # results
    results: list[str] = ["(a) 등록부"]
    results.extend(_registry_table(risk_rows))
    results.append("")
    results.append("(b) 개선 등록부")
    results.extend(_registry_table(gain_rows))
    results.append("")
    results.append("(c) 과제 성격")
    results.extend(_character_lines(store, target["project_id"]))
    results.append("")
    results.append("(d) 교차 도메인")
    results.extend(_cross_domain_lines(panels))

    # recommendation(bulleted_list)
    checks: dict[str, list[str]] = {}
    conditions: list[str] = []
    open_items: list[str] = []
    for row in rows:
        merged = _loads(row["merged_json"], {})
        for check in merged.get("resolving_checks", []):
            kind, _, ref = str(check).partition(":")
            checks.setdefault(kind, [])
            if ref not in checks[kind]:
                checks[kind].append(ref)
    for p in panels:
        spec = _loads(p["risk_spec_json"], {})
        for cond in _as_list(spec.get("verdict_conditions")):
            text = _clean_str(cond if not isinstance(cond, dict) else cond.get("text"))
            if text and text not in conditions:
                conditions.append(text)
        for item in _as_list(spec.get("open_items")):
            text = _clean_str(item if not isinstance(item, dict) else item.get("text"))
            if text and text not in open_items:
                open_items.append(text)

    recommendation: list[str] = [
        f"verdict 후보 = {candidate['verdict']} ({'; '.join(candidate['reasons'])})",
        f"verdict_final = {_clean_str(target['verdict_final']) or '(미확정)'}",
    ]
    recommendation.extend(f"조건: {c}" for c in conditions)
    for kind in sorted(checks):
        recommendation.append(f"resolving_check[{kind}]: " + " | ".join(checks[kind]))
    recommendation.extend(f"open_item: {o}" for o in open_items)

    minutes = _minutes_lines(store, target_key, panels, coverage)

    all_heuristic = bool(rows) and all(_clean_str(r["evidence_grade"]) == "경험칙" for r in rows)
    version = {"C0": "v1", "C1": "v1", "C2": "v2", "C2(closed)": "v2", "C3": "v3"}.get(level_info["level"], "v1")
    title = f"리스크 심사 보고서 {version} — {target_key}"
    if all_heuristic:
        title = "[가설 단계] " + title
    verdict_tag = _clean_str(target["verdict_final"]) or candidate["verdict"]

    return {
        "target_key": target_key,
        "title": title,
        "version": version,
        "level": level_info["level"],
        "verdict_candidate": candidate["verdict"],
        "verdict_final": _clean_str(target["verdict_final"]),
        "tags": ["리스크심사", "consolidated", f"hwax:target:{target_key}",
                 f"hwax:project:{target['project_id']}", f"verdict:{verdict_tag}"],
        "entity_ids": ctx["snapshot_ids"],
        "blocks": {
            "background": split_rich_text("\n".join(bg)),
            "results": split_rich_text("\n".join(results)),
            "recommendation": recommendation,
            "minutes": split_rich_text("\n".join(minutes)),
        },
    }
