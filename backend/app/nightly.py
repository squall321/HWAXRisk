# 야간 잡과 큐레이션 큐(plan §7.7) — run_nightly 가 ①~⑧ 을 멱등하게 돌고 사람이 판단할 것을 rr_curation_queue 에 올린다
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app import common, learning, sameas, taxonomy
from app.common import canonical_json, new_uuid

log = logging.getLogger("hwax_risk.nightly")

# rr_metrics 좌표. metrics.py 의 dimension='global' 행과 같은 자리를 쓰고 metric 이름만 nightly_* 로 갈린다.
# 야간 살림 지표는 누적 1행이라 재실행이 값을 부풀리지 않는다(PK 가 같아 덮어쓴다).
METRIC_PERIOD = "all"
METRIC_KEY = "global"

NIGHTLY_HOUR = 0                     # plan §7.7 로컬 00:30 에 1회
NIGHTLY_MINUTE = 30
ALIAS_CHAIN_MAX = 5                  # §4.3.2 resolve_cluster_key 체인 상한
SIZE_STEP = 0.5                      # §2.7.3 geom_bucket 의 치수 양자화 폭
NEAR_MAX_STEPS = 1                   # 'size 버킷 ±1' — 축 하나가 한 칸 어긋난 데까지만 근접으로 본다
CLUSTER_MERGE_MAX = 200              # 한 번의 스캔이 올리는 cluster_merge 신규 행 상한

QUEUE_KINDS = ("unclassified_code", "pattern_candidate", "label_match",
               "x_tag_promote", "suspect_text", "cluster_merge")

# ⑧ rr_id_map 정합 검사 — (portal_kind, 표, id 열, ra 열, adh 열). 앱 DB 에 열이 없는 kind(character·expert·trait)는 검사 대상이 아니다.
ID_MAP_SOURCES: tuple[tuple[str, str, str, str | None, str | None], ...] = (
    ("project", "rr_projects", "id", "ra_entity_id", "adh_character_record_id"),
    ("snapshot", "rr_snapshots", "id", "ra_entity_id", "adh_digest_record_id"),
    ("diff", "rr_diffs", "id", "ra_entity_id", None),
    ("opinion", "rr_seat_opinions", "opinion_id", None, "adh_record_id"),
    ("pattern", "rr_patterns", "id", None, "card_record_id"),
)

# 아직 주인이 없는 두 단계가 붙을 자리(§7.6 경로 1~4 의 RA·DynaForge 유입, §7.3 2 의 z-score 통계).
# 그 이름의 함수가 생기면 그날 밤부터 저절로 돈다 — 없으면 실패가 아니라 skipped 다.
# 인수 기준 주의 — 이 두 함수가 없는 동안 라벨은 사람 손 경로(metrics.record_label 경로 5)로만 들어온다.
# 즉 '라벨 5경로' 중 자동 유입 4경로는 **미구현** 이고, run_nightly 결과의 `unwired` 와
# rr_metrics(label_ingest_wired) 가 그 사실을 드러낸다(skipped 한 줄이 '정상' 으로 읽히지 않게).
STEP_HOOKS: dict[str, tuple[str, str]] = {
    "labels": ("app.metrics", "sync_labels"),         # ① 라벨 동기(RA incident·test_run → 큐/auto)
    "fv_stats": ("app.metrics", "refresh_fv_stats"),  # ⑤ feature_vector z-score 통계
}


# ---------------------------------------------------------------- §7.7 버전 스탬프
STAMP_KEYS: tuple[str, ...] = (
    "taxonomy_version", "rule_version", "planner_version", "ir_version", "diff_version",
    "adapter_version", "vocab_version", "lexicon_version", "injection_lexicon_version",
    "chair_rev", "seat_contract_rev", "persona_rev", "sampling", "source_app_versions",
)


def _asset_version(name: str, fallback: str) -> str:
    try:
        return str(taxonomy.version_of(taxonomy.load_json(name)) or fallback)
    except Exception:  # noqa: BLE001 — 자산이 없어도 스탬프는 나와야 한다.
        return fallback


def _seat_contract_rev() -> str | None:
    """seat-contract.v1.json 원문의 sha256[:12]. 좌석 계약이 바뀌면 같은 IR 에서 다른 결론이 난다(§7.7)."""
    try:
        return common.sha256_hex(taxonomy.asset_path("seat-contract").read_bytes())[:12]
    except OSError:
        return None


def _loads(text: Any, default: Any) -> Any:
    try:
        value = json.loads(text) if text else default
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _target_snapshot_id(store: Any, target_key: str) -> str | None:
    """타깃이 가리키는 target 쪽 스냅샷 id(snap 은 ref_id, diff 는 rr_diffs.target_snapshot_id)."""
    row = store.query_one("SELECT kind, ref_id FROM rr_targets WHERE target_key = ?", (target_key,))
    if row is None:
        return None
    if row["kind"] == "snap":
        return str(row["ref_id"])
    diff = store.query_one("SELECT target_snapshot_id FROM rr_diffs WHERE id = ?", (row["ref_id"],))
    return str(diff["target_snapshot_id"]) if diff is not None else None


def version_stamp(store: Any = None, *, target_key: str | None = None) -> dict:
    """§7.7 버전 스탬프 14키. finding·패널·보고서에 같은 값을 적어 '무엇이 바뀌어 결과가 달라졌나' 를 가린다.

    타깃 스코프 4키(adapter_version · source_app_versions · persona_rev · sampling)는 store 와 target_key 가
    있을 때만 채워지고 그 밖에는 None 이다. chair_rev 는 엔진(deliberation.py) 상수라 앱에 원문이 없다.
    """
    stamp: dict[str, Any] = {key: None for key in STAMP_KEYS}
    stamp["taxonomy_version"] = _asset_version("taxonomy", "1.0")
    stamp["rule_version"] = _asset_version("rules-seed", "rules-1.0")
    stamp["vocab_version"] = _asset_version("character-seed-rules", "vocab-1.0")
    stamp["seat_contract_rev"] = _seat_contract_rev()

    from app import diff as diff_mod
    from app import ir_builder, planner, render

    stamp["planner_version"] = planner.PLANNER_VERSION
    stamp["ir_version"] = ir_builder.IR_VERSION
    stamp["diff_version"] = diff_mod.DIFF_VERSION
    stamp["lexicon_version"] = render.LEXICON_VERSION

    if store is None or not target_key:
        return stamp

    snapshot_id = _target_snapshot_id(store, target_key)
    if snapshot_id:
        row = store.query_one(
            "SELECT adapter_versions_json FROM rr_snapshots WHERE id = ?", (snapshot_id,))
        if row is not None:
            versions = _loads(row["adapter_versions_json"], {})
            stamp["adapter_version"] = versions or None
            stamp["source_app_versions"] = versions or None
    roster = store.query_one(
        "SELECT persona_rev FROM rr_roster WHERE target_key = ? AND persona_rev IS NOT NULL"
        " ORDER BY agent_key LIMIT 1", (target_key,))
    if roster is not None:
        stamp["persona_rev"] = roster["persona_rev"]
    panel = store.query_one(
        "SELECT model_json FROM rr_panels WHERE target_key = ? AND model_json IS NOT NULL"
        " ORDER BY created_at DESC, id LIMIT 1", (target_key,))
    if panel is not None:
        stamp["sampling"] = _loads(panel["model_json"], {}).get("sampling")
    return stamp


def versioned_key(key: str, stamp: Mapping[str, Any]) -> str:
    """§7.7 — 버전이 다른 레코드를 섞어 지표를 낼 때 rr_metrics.key 에 붙이는 `@<taxonomy_version>` 접미."""
    version = stamp.get("taxonomy_version")
    return f"{key}@{version}" if version else key


# ---------------------------------------------------------------- rr_metrics 살림
def record_metric(store: Any, metric: str, value: float | None, *, now: int,
                  n: int | None = None, dimension: str = "global", key: str = METRIC_KEY) -> None:
    """(period, dimension, key, metric) 한 자리를 덮어쓴다 — 야간 잡을 두 번 돌려도 행이 늘지 않는다."""
    store.execute(
        "INSERT INTO rr_metrics (period, dimension, key, metric, value, n, computed_at)"
        " VALUES (?,?,?,?,?,?,?)"
        " ON CONFLICT(period, dimension, key, metric) DO UPDATE SET"
        " value = excluded.value, n = excluded.n, computed_at = excluded.computed_at",
        (METRIC_PERIOD, dimension, key, metric, value, n, now),
    )


def metric_value(store: Any, metric: str, *, dimension: str = "global",
                 key: str = METRIC_KEY) -> float | None:
    row = store.query_one(
        "SELECT value FROM rr_metrics WHERE period = ? AND dimension = ? AND key = ? AND metric = ?",
        (METRIC_PERIOD, dimension, key, metric),
    )
    return None if row is None or row["value"] is None else float(row["value"])


def last_run_at(store: Any) -> int | None:
    """마지막 야간 실행 시각(nightly_run_at). 없으면 None."""
    value = metric_value(store, "nightly_run_at")
    return None if value is None else int(value)


def is_due(store: Any, now: int) -> bool:
    """로컬 00:30 이후이고 마지막 실행이 다른 날짜일 때만 참(하루 1회, 이중 실행 방지)."""
    local = time.localtime(now)
    if (local.tm_hour, local.tm_min) < (NIGHTLY_HOUR, NIGHTLY_MINUTE):
        return False
    last = last_run_at(store)
    if last is None:
        return True
    prev = time.localtime(last)
    return (prev.tm_year, prev.tm_yday) != (local.tm_year, local.tm_yday)


# ---------------------------------------------------------------- 큐레이션 큐
def _queue_payloads(store: Any, kind: str) -> list[tuple[dict, str, dict]]:
    rows = store.query(
        "SELECT payload_json, status, decision_json FROM rr_curation_queue WHERE kind = ?", (kind,))
    return [(_loads(r["payload_json"], {}), str(r["status"]), _loads(r["decision_json"], {})) for r in rows]


def enqueue(store: Any, kind: str, payload: Mapping[str, Any], *, owner_sub: str, now: int,
            dedupe: Callable[[Mapping[str, Any]], Any] | None = None) -> str | None:
    """큐 1행을 올린다. dedupe 가 같은 값을 내는 행이 이미 있으면 올리지 않고 None 을 돌려준다(멱등).

    §3.4.1 의심 문구(`suspect_text`)처럼 야간이 아닌 경로가 채우는 kind 도 이 함수를 부른다.
    """
    if kind not in QUEUE_KINDS:
        raise ValueError(f"모르는 큐 kind: {kind!r}")
    if dedupe is not None:
        mark = dedupe(payload)
        for existing, _status, _decision in _queue_payloads(store, kind):
            if dedupe(existing) == mark:
                return None
    queue_id = new_uuid()
    store.execute(
        "INSERT INTO rr_curation_queue (id, owner_sub, kind, payload_json, status, created_at)"
        " VALUES (?,?,?,?,'open',?)",
        (queue_id, owner_sub, kind, canonical_json(dict(payload)), now),
    )
    return queue_id


# ---------------------------------------------------------------- ③-0 근접 중복 클러스터 · 별칭 검사
def check_cluster_alias(store: Any, *, now: int) -> dict:
    """rr_cluster_alias 의 순환·5홉 초과를 센다(§4.3.2 불변식). 자동 수정은 없다 — 사전은 사람이 고친다.

    learning.resolve_cluster_key 는 순환을 만나면 조용히 멈추므로(정상 조회 경로) 그 조용함이 가리는
    깨진 사전을 여기서 따로 센다.
    """
    rows = store.query(
        "SELECT old_cluster_key, new_cluster_key FROM rr_cluster_alias WHERE revoked_at IS NULL")
    alias = {str(r["old_cluster_key"]): str(r["new_cluster_key"]) for r in rows}
    broken: list[str] = []
    for key in sorted(alias):
        seen, current = [key], key
        for _ in range(ALIAS_CHAIN_MAX + 1):         # 5홉까지는 정상, 6홉째가 있으면 초과다
            nxt = alias.get(current)
            if nxt is None:
                break
            if nxt in seen:
                broken.append(key)                   # 순환
                break
            seen.append(nxt)
            current = nxt
        else:
            broken.append(key)                       # 5홉 초과
    record_metric(store, "nightly_cluster_alias_cycle", float(len(broken)), n=len(alias), now=now)
    return {"n_alias": len(alias), "broken": broken}


def _bucket_parts(bucket: str) -> list[float] | None:
    """geom_bucket('s1xs2…@vN') 의 치수 부분만 뽑는다. 형식이 아니면 None."""
    head = str(bucket).split("@v", 1)[0]
    if not head:
        return []
    try:
        return [float(part) for part in head.split("x")]
    except ValueError:
        return None


def _size_steps(bucket_a: str, bucket_b: str) -> int | None:
    """두 geom_bucket 사이의 치수 칸 수. 차원 수가 다르거나 형식이 아니면 None(비교 불가)."""
    a, b = _bucket_parts(bucket_a), _bucket_parts(bucket_b)
    if a is None or b is None or len(a) != len(b):
        return None
    return sum(int(round(abs(x - y) / SIZE_STEP)) for x, y in zip(a, b))


def _part_row(store: Any, ckey: str, cache: dict[str, dict | None]) -> dict | None:
    if ckey in cache:
        return cache[ckey]
    resolved = sameas.resolve_ckey(store, ckey)
    row = store.query_one(
        "SELECT ckey, name_norm_canon, geom_bucket, material_norm FROM rr_part_keys WHERE ckey = ?",
        (resolved,),
    )
    cache[ckey] = dict(row) if row is not None else None
    return cache[ckey]


def _subject_parts(store: Any, subject_key: str, cache: dict[str, dict | None]) -> list[dict] | None:
    """subject_key 의 ck: 조각을 rr_part_keys 행으로 바꾼다. 하나라도 없거나 ck: 가 없으면 None."""
    ckeys = [p for p in str(subject_key or "").split("|") if p.startswith("ck:")]
    if not ckeys:
        return None
    rows = [_part_row(store, ck, cache) for ck in ckeys]
    if any(row is None for row in rows):
        return None
    return sorted((row for row in rows if row is not None), key=lambda r: str(r["ckey"]))


def near_subject_score(store: Any, subject_a: str, subject_b: str,
                       cache: dict[str, dict | None] | None = None) -> float | None:
    """§2.7.3 근접 매치 — name_norm_canon 동일·material_norm 동일·size 버킷 ±1 이면 점수, 아니면 None."""
    cache = {} if cache is None else cache
    parts_a = _subject_parts(store, subject_a, cache)
    parts_b = _subject_parts(store, subject_b, cache)
    if parts_a is None or parts_b is None or len(parts_a) != len(parts_b):
        return None
    steps = 0
    for a, b in zip(parts_a, parts_b):
        if a["name_norm_canon"] != b["name_norm_canon"] or a["material_norm"] != b["material_norm"]:
            return None
        step = _size_steps(str(a["geom_bucket"]), str(b["geom_bucket"]))
        if step is None or step > NEAR_MAX_STEPS:
            return None
        steps += step
    if steps > NEAR_MAX_STEPS:
        return None
    return round(1.0 - 0.1 * steps, 3)


def scan_cluster_merge(store: Any, *, now: int, enabled: bool = True) -> dict:
    """③-0 — 같은 family_key 안의 근접 중복 클러스터 쌍을 큐에 올린다. 자동 병합은 없다.

    지표 `cluster_dup_ratio` 는 이 큐의 open 행을 세는 metrics.recompute 가 낸다(§7.6) — 여기서 쓰지 않는다.
    """
    if not enabled:
        return {"skipped": "risk_cluster_dup_scan=false"}

    alias_cache: dict = {}
    rows = store.query(
        "SELECT target_key, cluster_key, owner_sub, family_key, subject_key, direction FROM rr_registry"
        " WHERE family_key IS NOT NULL AND status != 'superseded' ORDER BY family_key, cluster_key")
    # direction 을 묶음 키에 넣는다 — 등록부는 risk 와 improvement 를 따로 세우므로(§4.7.1) 그 둘은 중복이 아니다.
    families: dict[tuple[str, str], dict[str, dict]] = {}
    for row in rows:
        resolved = learning.resolve_cluster_key(store, str(row["cluster_key"]), _cache=alias_cache)
        bucket = families.setdefault((str(row["family_key"]), str(row["direction"] or "")), {})
        bucket.setdefault(resolved, {
            "cluster_key": resolved, "owner_sub": str(row["owner_sub"]),
            "subject_key": str(row["subject_key"] or ""),
        })

    suppressed: set[tuple[str, str]] = set()
    for payload, status, decision in _queue_payloads(store, "cluster_merge"):
        pair = (str(payload.get("a") or ""), str(payload.get("b") or ""))
        if status == "open" or status == "done" or (status == "rejected" and decision.get("suppress")):
            suppressed.add(pair)

    cache: dict[str, dict | None] = {}
    n_pairs = 0
    queued: list[str] = []
    for (family_key, _direction), members in sorted(families.items()):
        keys = sorted(members)
        for i, key_a in enumerate(keys):
            for key_b in keys[i + 1:]:
                a, b = members[key_a], members[key_b]
                score = near_subject_score(store, a["subject_key"], b["subject_key"], cache)
                if score is None:
                    continue
                n_pairs += 1
                if (key_a, key_b) in suppressed or len(queued) >= CLUSTER_MERGE_MAX:
                    continue
                payload = {"a": key_a, "b": key_b, "family_key": family_key,
                           "subject_a": a["subject_key"], "subject_b": b["subject_key"], "score": score}
                # dedupe 를 걸지 않는다 — suppressed 가 open·done·suppress 를 이미 걸렀고, suppress 없이 reject 된
                # 쌍은 다음 스캔에 다시 올라와야 한다(§7.7 cluster_merge 결정 표).
                queue_id = enqueue(store, "cluster_merge", payload, owner_sub=a["owner_sub"], now=now)
                if queue_id:
                    queued.append(queue_id)

    n_clusters = sum(len(members) for members in families.values())
    return {"n_clusters": n_clusters, "n_pairs": n_pairs, "queued": len(queued)}


# ---------------------------------------------------------------- unclassified_code 스캔
def _detail_candidates(mechanism: str) -> list[str]:
    """같은 mechanism 의 active 택소노미 코드(큐 화면의 `map:<code>` 후보)."""
    try:
        axis = taxonomy.load_taxonomy().get("axes", {}).get("mechanism") or []
    except Exception:  # noqa: BLE001 — 자산 문제로 스캔이 멈추지 않게 한다.
        return []
    return sorted(str(item.get("code")) for item in axis
                  if item.get("mechanism") == mechanism and item.get("status", "active") == "active"
                  and item.get("code"))


def scan_unclassified(store: Any, *, now: int) -> dict:
    """mechanism_detail='unclassified' 로 저장된 finding 을 큐에 올린다(§7.1 — detail 이 목록 밖일 때)."""
    rows = store.query(
        "SELECT finding_id, owner_sub, mechanism, mechanism_free FROM rr_findings"
        " WHERE mechanism_detail = 'unclassified' ORDER BY finding_id")
    queued = 0
    for row in rows:
        payload = {"finding_id": str(row["finding_id"]),
                   "mechanism_free": row["mechanism_free"],
                   "candidates": _detail_candidates(str(row["mechanism"] or ""))}
        if enqueue(store, "unclassified_code", payload, owner_sub=str(row["owner_sub"]), now=now,
                   dedupe=lambda p: p.get("finding_id")):
            queued += 1
    return {"n_unclassified": len(rows), "queued": queued}


# ---------------------------------------------------------------- ⑦ external_sync 재시도
def retry_external_sync(store: Any, *, now: int,
                        send: Callable[[Any, str, str, Sequence[Mapping[str, Any]]], bool] | None = None) -> dict:
    """next_at ≤ now 인 pending 채널의 op 를 다시 보낸다(§5.5.3).

    send 가 없으면(러너가 아직 클라이언트를 물리지 않았으면) 보내지 않고 대기 건수만 센다 — 이 모듈은
    스스로 외부 연결을 열지 않는다.
    """
    from app import ra_client

    rows = store.query("SELECT target_key, external_sync_json FROM rr_targets ORDER BY target_key")
    due: list[tuple[str, str, list]] = []
    for row in rows:
        sync = ra_client.load_external_sync(store, str(row["target_key"]))
        for channel in ra_client.SYNC_CHANNELS:
            entry = sync.get(channel) or {}
            ops = list(entry.get("pending_ops") or [])
            if entry.get("state") == "pending" and ops and int(entry.get("next_at") or 0) <= now:
                due.append((str(row["target_key"]), channel, ops))

    if send is None:
        return {"due": len(due), "sent": 0, "skipped": "sender 미배선"}

    sent = failed = 0
    for target_key, channel, ops in due:
        try:
            ok = send(store, target_key, channel, ops)
        except Exception as exc:  # noqa: BLE001 — 한 채널의 실패가 다른 타깃을 막지 않는다.
            ra_client.note_sync_failure(store, target_key, channel, f"{type(exc).__name__}: {exc}")
            failed += 1
            continue
        if ok:
            ra_client.complete_sync_ops(store, target_key, channel, ops)
            sent += 1
        else:
            ra_client.note_sync_failure(store, target_key, channel, "send 실패")
            failed += 1
    return {"due": len(due), "sent": sent, "failed": failed}


# ---------------------------------------------------------------- ⑧ rr_id_map 정합 검사
def check_id_map(store: Any, *, now: int) -> dict:
    """rr_id_map 기준으로 각 원본 표의 ra_entity_id·adh_record_id 중복 컬럼을 대조한다(§5.5.2).

    고치지 않고 세기만 한다 — 어느 쪽이 옳은지는 외부 반영 경로가 안다.
    """
    drift: list[dict] = []
    for kind, table, id_col, ra_col, adh_col in ID_MAP_SOURCES:
        rows = store.query(
            "SELECT portal_id, ra_entity_id, adh_record_id FROM rr_id_map WHERE portal_kind = ?"
            " ORDER BY portal_id", (kind,))
        for row in rows:
            cols = ", ".join(c for c in (ra_col, adh_col) if c)
            source = store.query_one(
                f"SELECT {cols} FROM {table} WHERE {id_col} = ?", (row["portal_id"],)) if cols else None
            if source is None:
                drift.append({"kind": kind, "portal_id": row["portal_id"], "reason": "source_missing"})
                continue
            if ra_col and row["ra_entity_id"] is not None and source[ra_col] != row["ra_entity_id"]:
                drift.append({"kind": kind, "portal_id": row["portal_id"], "reason": "ra_mismatch"})
            if adh_col and row["adh_record_id"] is not None and source[adh_col] != row["adh_record_id"]:
                drift.append({"kind": kind, "portal_id": row["portal_id"], "reason": "adh_mismatch"})
    total = store.query_one("SELECT COUNT(*) AS n FROM rr_id_map")
    n = int(total["n"]) if total is not None else 0
    record_metric(store, "nightly_id_map_drift", float(len(drift)), n=n, now=now)
    return {"n_rows": n, "drift": drift}


# ---------------------------------------------------------------- 야간 잡 본체
def _hook(name: str) -> Callable[..., Any] | None:
    """담당 함수가 아직 없으면 None — 그 단계는 실패가 아니라 skipped 다."""
    module_name, func_name = STEP_HOOKS[name]
    try:
        module = __import__(module_name, fromlist=[func_name])
    except ImportError:
        return None
    func = getattr(module, func_name, None)
    return func if callable(func) else None


def _run_optional(name: str, store: Any, now: int) -> Any:
    """아직 주인이 없는 단계 — 함수가 있으면 부르고 없으면 skipped 를 돌려준다."""
    func = _hook(name)
    if func is None:
        module_name, func_name = STEP_HOOKS[name]
        return {"skipped": f"{module_name}.{func_name} 미배선"}
    return func(store, now=now)


def owners(store: Any) -> list[str]:
    """과제 소유자 목록 — owner_sub 를 인자로 받는 단계(지표·x: 태그)를 소유자마다 한 번씩 돌린다."""
    rows = store.query("SELECT DISTINCT owner_sub FROM rr_projects ORDER BY owner_sub")
    return [str(r["owner_sub"]) for r in rows]


def _recompute_metrics(store: Any) -> dict:
    """④ 지표 재계산·배지(§7.6) — rr_metrics 에는 소유자 축이 없어 코퍼스 전체를 한 번만 계산한다.

    소유자마다 부르면 같은 (period, dimension, key, metric) 자리를 소유자 수만큼 덮어써 마지막 소유자의
    부분집합만 남는다(배지·병목 포함).
    """
    from app import metrics

    out = metrics.recompute(store)
    return {"rows": out["rows"], "findings": out["findings"], "labels": out["labels"],
            "loop_ok": out["badge"]["ok"], "bottlenecks": out["badge"]["bottlenecks"],
            "label_auto_ingest": out["badge"]["label_auto_ingest"]}


def _queue_x_tags(store: Any) -> dict:
    """⑥ `x:` 태그 승격 스캔(§7.7) — character.queue_x_tag_promotions 가 정본이다."""
    from app import character

    return {owner: character.queue_x_tag_promotions(store, owner_sub=owner) for owner in owners(store)}


def run_nightly(store: Any, *, now: int | None = None, settings: Any = None,
                hooks: Mapping[str, Callable[..., Any]] | None = None,
                send: Callable[[Any, str, str, Sequence[Mapping[str, Any]]], bool] | None = None,
                force: bool = False) -> dict:
    """plan §7.7 야간 잡 ①~⑧ 을 순서 고정·단계 멱등으로 돈다. 러너의 nightly_loop 가 이것만 부른다.

    runner.py 는 `nightly.run_nightly(self.store, now=common.now_epoch(), settings=self.settings)` 한 줄이면 된다 —
    하루 1회 판정(is_due)과 이중 실행 방지(rr_metrics.nightly_run_at)는 이 함수 안에 있다.
    한 단계의 실패는 다음 단계를 막지 않고 rr_metrics(dimension=global, metric='nightly_<step>_ok') 에 0 으로 남는다.
    아직 담당 모듈이 없는 단계는 metric 을 쓰지 않고 status='skipped' 로만 보고한다(0 = 실패와 구분).
    """
    now = common.now_epoch() if now is None else int(now)
    if not force and not is_due(store, now):
        return {"ran": False, "reason": "not_due", "last_run_at": last_run_at(store), "steps": []}

    # 먼저 찍는다 — 중간에 죽어도 같은 날 두 번 돌지 않는다.
    record_metric(store, "nightly_run_at", float(now), now=now)
    stamp = version_stamp(store)
    dup_scan = bool(getattr(settings, "risk_cluster_dup_scan", True)) if settings is not None else True
    hooks = dict(hooks or {})

    # ①~⑧ 순서 고정. 각 단계는 자기 담당 모듈의 정본 함수를 부르고 여기서 다시 계산하지 않는다.
    steps: list[tuple[str, Callable[[], Any]]] = [
        ("labels", lambda: _run_optional("labels", store, now)),
        ("delta_priors", lambda: learning.check_delta_priors(store, fix=True, now=now)),
        ("cluster_scan", lambda: {
            "cluster_merge": scan_cluster_merge(store, now=now, enabled=dup_scan),
            "alias": check_cluster_alias(store, now=now),
            "unclassified": scan_unclassified(store, now=now),
        }),
        ("patterns", lambda: learning.mine_patterns(store, now=now)),
        ("metrics", lambda: _recompute_metrics(store)),
        ("fv_stats", lambda: _run_optional("fv_stats", store, now)),
        ("x_tags", lambda: _queue_x_tags(store)),
        ("external_sync", lambda: retry_external_sync(store, now=now, send=send)),
        ("id_map", lambda: check_id_map(store, now=now)),
    ]

    report: list[dict] = []
    for name, fn in steps:
        try:
            override = hooks.get(name)
            result = override(store, now=now) if override is not None else fn()
        except Exception as exc:  # noqa: BLE001 — 실패는 비차단이다(plan §7.7).
            log.exception("야간 단계 실패: %s", name)
            record_metric(store, f"nightly_{name}_ok", 0.0, now=now)
            report.append({"step": name, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            continue
        if isinstance(result, Mapping) and result.get("skipped"):
            report.append({"step": name, "status": "skipped", "result": dict(result)})
            continue
        record_metric(store, f"nightly_{name}_ok", 1.0, now=now)
        report.append({"step": name, "status": "ok",
                       "result": dict(result) if isinstance(result, Mapping) else result})

    log.info("야간 잡 완료 — %s", " ".join(f"{r['step']}={r['status']}" for r in report))
    # 미배선 단계를 결과 최상단에 모아 둔다 — skipped 한 줄이 '정상' 으로 읽히지 않게(라벨 자동 유입 4경로).
    unwired = [r["step"] for r in report if r["status"] == "skipped"
               and "미배선" in str((r.get("result") or {}).get("skipped") or "")]
    return {"ran": True, "run_at": now, "versions": stamp, "steps": report, "unwired": unwired}
