# 카드 대조 대상의 잡 사슬(재설계 M3 S3-5) — 검토가 마감 범위를 닫으면 쟁점 → 종합을 사람 손 없이 잇고, 끊긴 사슬은 러너 틱이 메운다
"""m3-synthesis 3.7 의 그림 그대로다.

    reviews ──completed──▶ on_reviews_closed ─┬─ 마감 범위에 열린 셀이 남았다 ─▶ 병합 → 코드 조립 판(reviews_partial). 끝
                                              └─ 다 닫혔다 ─▶ 병합 → 판(reviews_closed) → 쟁점 선정 → issues 잡(없으면 synth 잡)
    issues  ──completed·failed──▶ on_issues_closed ─▶ 병합 → 판(issues_closed) → synth 잡
    synth   ──completed──▶ (사슬 끝 — 판 synth_done 은 종합 워커가 세우고 그 조립이 완결 캐시를 쓴다)

- 다음 잡 생성은 앞 잡의 상태 전이와 다른 트랜잭션이다. 그 사이에 프로세스가 죽으면 `sweep`(러너 30초 틱)이 메운다 — 마지막으로
  끝난 단계에 다음 잡이 없으면 하나만 만든다(`chain_json.prev_job_id` 로 멱등).
- 사람이 취소한 잡 뒤에는 잇지 않는다. 쟁점 잡이 실패(연속 3패널 오류)로 닫혀도 종합은 잇는다(P-08 ②).
- 같은 대상에 쟁점·종합 잡이 이미 살아 있으면 새로 만들지 않는다 — 살아 있는 쟁점 잡은 새 대기 쟁점을 집고, 살아 있는 종합 잡은
  입력이 바뀐 요약을 다시 세운다(superseded).
- 사슬 잡은 앞 잡의 요청자·메모를 잇고 동의 출처는 `chain` 이다. 자격이 없어도 행을 만들고 `error='pat_unavailable: …'` 를 적는다
  (자격 검사로 사슬이 끊기지 않는다 — 집는 쪽이 건너뛰며 사유를 남긴다).
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from app import closure, common, issues, registry, synth
from app.risk_store import RiskStore

log = logging.getLogger("hwax_risk.chain")

STAGES: tuple[str, ...] = ("issues", "synth")
CHAIN_MODES: tuple[str, ...] = ("reviews", *STAGES)
LIVE_STATES: tuple[str, ...] = ("queued", "running", "paused", "cancelling")
FINISHED_STATES: tuple[str, ...] = ("completed", "failed", "cancelled")


def _loads(text: Any) -> dict:
    try:
        value = json.loads(text) if text else {}
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _cells_target(store: RiskStore, target_key: str) -> bool:
    row = store.query_one("SELECT flow FROM rr_targets WHERE target_key = ?", (target_key,))
    return row is not None and row["flow"] == "cells"


def scope_open(store: RiskStore, target_key: str) -> int:
    """마감 범위(`closure.closing_agents` — C3 면 격자 전부, C2 면 Tier B 범위)의 열린 셀(pending·running) 수. failed·skipped·
    na_irrelevant·no_input 은 닫힌 것이다(C-18 — 잡은 끝나고 완결이 막힌다)."""
    agents = closure.closing_agents(store, target_key)
    open_states = closure.OPEN_CELL_STATES
    rows = store.query(f"SELECT agent_key FROM rr_review_cells WHERE target_key = ? AND state IN"
                       f" ({','.join('?' * len(open_states))})", (target_key, *open_states))
    return sum(1 for r in rows if agents is None or r["agent_key"] in agents)


def _live(store: RiskStore, target_key: str, modes: tuple[str, ...]) -> dict | None:
    row = store.query_one(
        f"SELECT id, mode, state FROM rr_jobs WHERE target_key = ? AND mode IN ({','.join('?' * len(modes))})"
        f" AND state IN ({','.join('?' * len(LIVE_STATES))}) ORDER BY created_at DESC LIMIT 1",
        (target_key, *modes, *LIVE_STATES))
    return dict(row) if row is not None else None


def _busy(store: RiskStore, target_key: str, stage: str) -> dict | None:
    """그 단계를 새로 세울 필요가 없게 하는 살아 있는 잡 — 쟁점은 살아 있는 쟁점 잡(새 대기 쟁점을 그 잡이 집는다), 종합은 살아 있는
    쟁점 잡(그 잡이 끝나면 종합을 잇는다)이나 아직 집히지 않은 종합 잡(시작할 때 지금 원장을 읽는다). 도는 종합 잡은 막지 않는다 —
    그 잡이 이미 끝낸 요약은 옛 입력이라 새 종합 잡이 뒤에 줄을 선다."""
    if stage == "issues":
        return _live(store, target_key, ("issues",))
    live = _live(store, target_key, ("issues",))
    if live is not None:
        return live
    row = store.query_one("SELECT id, mode, state FROM rr_jobs WHERE target_key = ? AND mode = 'synth' AND state = 'queued'"
                          " ORDER BY created_at DESC LIMIT 1", (target_key,))
    return dict(row) if row is not None else None


def _rearm(store: RiskStore, target_key: str, job_id: str, *, by: str, round_no: int) -> dict:
    """살아 있는 단계 잡이 지금 원장으로 돈다는 표지 — 그 잡의 chain_json 의 지문(cells_hash · registry_hash · reopened_n · round)을
    지금 값으로 고치고 다시 세운 앞 잡(`rearmed_by`)을 적는다. 앞 잡·뿌리는 그대로다(멱등의 열쇠). 사슬 밖에서 선 잡(사람이 올린 쟁점의
    잡)이면 지금 잡을 뿌리로 새로 적는다. 이것이 없으면 쟁점을 다 그대로 둔 다시 고르기는 지문을 어디에도 남기지 않아 '후속 낡음' 이
    풀리지 않는다."""
    row = store.query_one("SELECT mode, chain_json FROM rr_jobs WHERE id = ?", (job_id,))
    chain = _loads(row["chain_json"]) or {"root_job_id": by, "prev_job_id": None, "stage": row["mode"], "scope_open": 0,
                                          "reason": "rearmed"}
    chain.update({"round": int(round_no), "cells_hash": closure.closing_hash(store, target_key),
                  "registry_hash": synth.registry_hash(store, target_key),
                  "reopened_n": closure.reopened_sum(store, target_key), "rearmed_by": by})
    store.execute("UPDATE rr_jobs SET chain_json = ? WHERE id = ?", (common.canonical_json(chain), job_id))
    return chain


def _followed(store: RiskStore, job_id: str) -> str | None:
    row = store.query_one("SELECT id FROM rr_jobs WHERE json_extract(chain_json, '$.prev_job_id') = ? LIMIT 1", (job_id,))
    return row["id"] if row is not None else None


def _next_round(store: RiskStore, target_key: str) -> int:
    row = store.query_one("SELECT MAX(selected_round) AS r FROM rr_issues WHERE target_key = ?", (target_key,))
    return int(row["r"] or 0) + 1


def create_stage_job(store: RiskStore, target_key: str, stage: str, *, prev: Mapping[str, Any], reason: str,
                     round_no: int) -> dict:
    """사슬의 다음 잡 하나 — 앞 잡(`prev`)에 이미 다음 잡이 있으면 그것을 돌려준다(`created: False`). 반환 {job_id, stage, created,
    chain, error?}."""
    if stage not in STAGES:
        raise ValueError(f"모르는 사슬 단계 — {stage!r}")
    params = _loads(prev.get("params_json")) if "params_json" in prev else dict(prev.get("params") or {})
    root = _loads(prev.get("chain_json")).get("root_job_id") or prev["id"]
    chain = {"root_job_id": root, "prev_job_id": prev["id"], "stage": stage, "round": int(round_no),
             "cells_hash": closure.closing_hash(store, target_key), "registry_hash": synth.registry_hash(store, target_key),
             "scope_open": 0, "reason": reason, "reopened_n": closure.reopened_sum(store, target_key)}
    with store.tx():
        # 확인과 쓰기를 한 트랜잭션으로 — 사슬 훅과 sweep 이 겹쳐도 앞 잡 하나에 다음 잡은 하나다.
        existing = _followed(store, str(prev["id"]))
        if existing is not None:
            return {"job_id": existing, "stage": stage, "created": False, "chain": chain}
        kwargs = {"owner_sub": prev["owner_sub"], "requester_sub": params.get("requester"), "consent_source": "chain",
                  "chain": chain}
        made = (issues.create_issues_job(store, target_key, user_memo=params.get("user_memo"), **kwargs) if stage == "issues"
                else synth.create_synth_job(store, target_key, **kwargs))
    log.info("사슬: 대상 %s 의 %s 잡 %s 를 세웠다(앞 잡 %s · %s)%s", target_key, stage, made["job_id"], prev["id"], reason,
             f" — {made['error']}" if made.get("error") else "")
    return {**made, "stage": stage, "created": True, "chain": chain}


def _job(store: RiskStore, job_id: str) -> dict:
    return dict(store.query_one("SELECT id, target_key, owner_sub, mode, state, params_json, chain_json FROM rr_jobs"
                                " WHERE id = ?", (job_id,)))


def on_reviews_closed(store: RiskStore, job: Mapping[str, Any]) -> dict:
    """검토 잡이 completed 로 닫힌 뒤(`ReviewLoop._finish`). 반환 {stage, created?, job_id?, reason, open?, report?}."""
    key = str(job["target_key"])
    if not _cells_target(store, key):
        return {"stage": None, "reason": "panels"}
    registry.merge(store, key)
    open_n = scope_open(store, key)
    if open_n:
        # 좁은 범위의 검토(파일럿·Tier A 만·한 영역) — 적은 인원의 결과로 쟁점·종합을 닫지 않는다(P-01). 판만 세운다.
        report = synth.safe_assemble(store, key, trigger="reviews_partial")
        if report is None:
            closure.refresh(store, key)
        return {"stage": None, "reason": "scope_open", "open": open_n, "report": report}
    report = synth.safe_assemble(store, key, trigger="reviews_closed")
    round_no = _next_round(store, key)
    issues.select_issues(store, key, selected_round=round_no, cells_hash=closure.closing_hash(store, key))
    queued = int(store.query_one("SELECT COUNT(*) AS n FROM rr_issues WHERE target_key = ? AND state = 'queued'",
                                 (key,))["n"] or 0)
    stage = "issues" if queued else "synth"
    live = _busy(store, key, stage)
    if live is not None:
        _rearm(store, key, live["id"], by=str(job["id"]), round_no=round_no)
        out = {"stage": None, "reason": f"{live['mode']}_live", "job_id": live["id"], "report": report}
    else:
        out = {**create_stage_job(store, key, stage, prev=_job(store, str(job["id"])),
                                  reason="reviews_closed" if queued else "no_issues", round_no=round_no), "report": report}
    closure.refresh(store, key)
    return out


def on_issues_closed(store: RiskStore, job: Mapping[str, Any]) -> dict:
    """쟁점 잡이 completed·failed 로 닫힌 뒤(러너 `_finish_job` · 연속 오류). 취소된 잡 뒤에는 잇지 않는다."""
    key = str(job["target_key"])
    row = _job(store, str(job["id"]))
    if row["state"] not in ("completed", "failed"):
        return {"stage": None, "reason": f"issues_{row['state']}"}
    if not _cells_target(store, key):
        return {"stage": None, "reason": "panels"}
    registry.merge(store, key)
    report = synth.safe_assemble(store, key, trigger="issues_closed")
    live = _busy(store, key, "synth")
    round_no = int(_loads(row["chain_json"]).get("round") or max(_next_round(store, key) - 1, 1))
    if live is not None:
        _rearm(store, key, live["id"], by=str(row["id"]), round_no=round_no)
        out = {"stage": None, "reason": f"{live['mode']}_live", "job_id": live["id"], "report": report}
    else:
        out = {**create_stage_job(store, key, "synth", prev=row, reason=f"issues_{row['state']}", round_no=round_no),
               "report": report}
    closure.refresh(store, key)
    return out


def safe(hook: Any, store: RiskStore, job: Mapping[str, Any]) -> dict | None:
    """사슬 훅을 앞 잡의 전이 밖에서 부른다 — 터져도 앞 잡의 완료를 무르지 않고 로그를 남긴다(다음 sweep 이 다시 본다)."""
    try:
        return hook(store, job)
    except Exception:  # noqa: BLE001 — 위 설명대로다.
        log.exception("사슬 훅 %s 실패(잡 %s, 대상 %s) — 다음 sweep 이 다시 본다", getattr(hook, "__name__", hook),
                      job.get("id"), job.get("target_key"))
        return None


def sweep(store: RiskStore) -> dict:
    """끊긴 사슬 메우기 — cells 대상마다 살아 있는 검토·쟁점·종합 잡이 없고 마지막으로 끝난 잡(끝난 시각 · 넣은 차례)에 다음 잡이
    없으면 그 단계의 훅을 한 번 부른다. 마지막이 종합·취소면 할 일이 없고, 검토면 마감 범위가 다 닫혔을 때만 잇는다(좁은 범위 뒤에는
    잇지 않는다). 반환 {checked, made[{target_key, after, job_id, stage}]}."""
    made: list[dict] = []
    targets = [r["target_key"] for r in store.query("SELECT target_key FROM rr_targets WHERE flow = 'cells'")]
    for key in targets:
        if _live(store, key, CHAIN_MODES) is not None:
            continue
        last = store.query_one(
            f"SELECT id, target_key, owner_sub, mode, state, params_json, chain_json FROM rr_jobs WHERE target_key = ?"
            f" AND mode IN ({','.join('?' * len(CHAIN_MODES))}) AND state IN ({','.join('?' * len(FINISHED_STATES))})"
            " ORDER BY updated_at DESC, rowid DESC LIMIT 1", (key, *CHAIN_MODES, *FINISHED_STATES))
        if last is None or last["state"] == "cancelled" or last["mode"] == "synth":
            continue
        if _followed(store, last["id"]) is not None:
            continue
        if last["mode"] == "reviews":
            if last["state"] != "completed" or scope_open(store, key):
                continue
            out = safe(on_reviews_closed, store, dict(last))
        else:
            out = safe(on_issues_closed, store, dict(last))
        if out and out.get("created"):
            made.append({"target_key": key, "after": last["id"], "job_id": out["job_id"], "stage": out["stage"]})
            log.warning("사슬 sweep: 대상 %s 의 끝난 잡 %s 뒤에 %s 잡 %s 를 세웠다(끊긴 사슬)", key, last["id"], out["stage"],
                        out["job_id"])
    return {"checked": len(targets), "made": made}
