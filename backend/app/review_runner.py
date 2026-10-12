# 카드 대조 검토 잡 — 잡 만들기(범위·자격·호출 수 추정·동의, 네트워크 없음)와 검토 루프(전문가 세션·기다림·차단기·재기동 이어 돌기, m2-wp3b S8)
"""검토 잡(`rr_jobs.mode='reviews'`) 하나는 한 대상의 셀 원장에서 범위 안 셀을 끝까지 돈다. 이 파일의 첫 함수는 잡을 세우는
일만 한다 — 격자를 만들고(`review_cells.plan_cells`) 범위를 찍고(`assign_scope`) 잡 행을 넣는다. 카드 묶음·엔진 호출은 아래의
검토 루프(`ReviewLoop` — 러너의 review_loop 스레드가 2초마다 `tick`)가 한다.

자격은 사용자 PAT 하나다 — 요청자 → 대상 소유자 순으로 등록된 PAT 가운데 남은 수명이 검토 여유(호출 벽시계 + 600초)를 넘는
첫 것이다. 서비스 계정 PAT 로 내려가지 않는다(사용자 결정 3 — 패널 경로의 `runner.resolve_credential_with_note` 와 다르다).
"""
from __future__ import annotations

import gzip
import json
import logging
import math
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app import (cardpack, config, engine_client, expert_report, planner, review_cells, review_ops, review_verify, runner,
                 units)
from app.common import canonical_json, new_uuid, now_epoch, sha256_hex
from app.errors import AppError
from app.runner import EngineBusy, EngineRejected, EngineStreamLost, PatUnavailable

log = logging.getLogger("hwax_risk.review")

MODE = "reviews"
SCOPE_KEYS: tuple[str, ...] = ("tiers", "domains", "agents", "unit_ids")   # 범위 칸 넷(PLAN 4절 REST)

# 호출 수 추정 — 잡을 만들 때는 카드 묶음을 받기 전이라 묶음 수를 모른다. 셀 하나의 낮은 끝은 묶음 하나의 fwd·rev 와 카드 밖
# 한 번(3), 높은 끝은 묶음 둘의 fwd·rev(4) + 빠진 카드 재질의 2 + 단독 재질의 4 + 카드 밖 1 + '이것 말고 더' 3 = 14 다
# (m2-wp3b S8 의 호출 표, 점검 카드는 전문가당 평균 12.9장 — spec-wp3b §3.14.1). 전문가마다 훑기 1~2 를 더한다.
# M2 파일럿의 셀당 호출 수(품질 '실측')로 다시 정한다.
CALLS_PER_CELL: tuple[int, int] = (3, 14)
SWEEP_CALLS_PER_EXPERT: tuple[int, int] = (1, 2)
EST_CALL_S = 300               # 호출 하나의 가정(PLAN 6절 — 5분). 자격 수명과 견주는 데만 쓴다
LIVE_STATES: tuple[str, ...] = runner.LIVE_JOB_STATES


# ---------------------------------------------------------------- 자격(사용자 결정 3)
def review_credential(store: Any, settings: Any | None, owner_sub: str | None,
                      requester_sub: str | None = None) -> tuple[dict | None, str | None]:
    """검토 잡의 자격 — ({kind: requester·owner, email, exp}, 건너뛴 사유) 또는 (None, 사유).

    등록된 사용자 PAT 만 본다. 남은 수명이 `config.review_credential_margin_s`(호출 벽시계 + 600초)를 넘어야 쓴다. 서비스 PAT 가
    설정돼 있어도 쓰지 않는다 — 긴 작업 도중 사용자 자격이 끝나면 잡이 멈추고 알린다(사용자 결정 3).
    """
    cfg = config.settings if settings is None else settings
    margin = config.review_credential_margin_s(cfg)
    short: tuple[str, int] | None = None
    order = [("requester", requester_sub)] if requester_sub and requester_sub != owner_sub else []
    for kind, email in (*order, ("owner", owner_sub)):
        row, left = runner._registered_pat(store, email)
        if row is None:
            continue
        if left > margin:
            note = None
            if short is not None:
                note = (f"{short[0]} 의 PAT 남은 수명 {max(short[1], 0) / 3600:.1f}시간이 검토 여유 {margin / 3600:.1f}시간"
                        f"(HWAXRISK_REVIEW_CALL_TIMEOUT_S + 600초)에 못 미쳐 {email} 의 PAT 로 돈다")
            return {"kind": kind, "email": row.get("pat_email") or email, "exp": int(row.get("pat_exp") or 0)}, note
        short = short or (str(email), left)
    who = " · ".join(e for _, e in (*order, ("owner", owner_sub)) if e)
    why = (f"{short[0]} 의 PAT 남은 수명 {max(short[1], 0) / 3600:.1f}시간이 검토 여유 {margin / 3600:.1f}시간"
           "(HWAXRISK_REVIEW_CALL_TIMEOUT_S + 600초)에 못 미친다" if short else f"{who} 의 등록된 포털 PAT 가 없다")
    return None, why


# ---------------------------------------------------------------- 범위
def _scope_error(message: str, **detail: Any) -> AppError:
    return AppError("scope_invalid", message, 422, detail=detail)


def resolve_scope(scope: Mapping[str, Any] | None, order: Sequence[Mapping[str, Any]],
                  unit_rows: Sequence[Mapping[str, Any]]) -> dict:
    """범위 칸 넷(tiers·domains·agents·unit_ids — 칸끼리는 AND, 빠진 칸은 전부)을 로스터·활성 단위에 댄다.

    반환 {scope(정규 표기), experts(review_order 행, 순서 그대로), unit_ids(seq 순)}. 모르는 칸·목록이 아닌 값·빈 목록·이 대상에
    없는 값(로스터 밖 전문가·영역, 검토 대상이 아닌 단위)은 422 `scope_invalid` 다 — 이름 하나를 잘못 적은 범위가 말없이 좁아지지
    않게. 맞는 전문가나 단위가 0 이면 422 `scope_empty` 다.
    """
    raw = dict(scope or {})
    unknown = sorted(set(raw) - set(SCOPE_KEYS))
    if unknown:
        raise _scope_error(f"범위에 모르는 칸이 있다 — {unknown}. 칸은 {list(SCOPE_KEYS)} 넷이다.", unknown_keys=unknown)
    known = {"tiers": set(planner.TIERS), "domains": {r["domain"] for r in order},
             "agents": {r["agent_key"] for r in order}, "unit_ids": {u["unit_id"] for u in unit_rows}}
    norm: dict[str, list[str]] = {}
    for key in SCOPE_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
            raise _scope_error(f"범위의 {key} 는 목록이어야 한다 — {type(value).__name__}.", key=key)
        items = list(dict.fromkeys(str(v).strip() for v in value if str(v).strip()))
        if not items:
            raise _scope_error(f"범위의 {key} 가 빈 목록이다 — 전부를 뜻하면 그 칸을 뺀다.", key=key)
        outside = [v for v in items if v not in known[key]]
        if outside:
            raise _scope_error(f"범위의 {key} 에 이 대상에 없는 값이 있다 — {outside}.", key=key, values=outside)
        norm[key] = items
    experts = [r for r in order
               if ("tiers" not in norm or r["tier"] in norm["tiers"])
               and ("domains" not in norm or r["domain"] in norm["domains"])
               and ("agents" not in norm or r["agent_key"] in norm["agents"])]
    unit_ids = [u["unit_id"] for u in unit_rows if "unit_ids" not in norm or u["unit_id"] in norm["unit_ids"]]
    if not experts or not unit_ids:
        raise AppError("scope_empty", f"범위에 드는 셀이 없다 — 전문가 {len(experts)}명 × 단위 {len(unit_ids)}개.", 422,
                       detail={"scope": norm, "experts": len(experts), "units": len(unit_ids)})
    return {"scope": norm, "experts": experts, "unit_ids": unit_ids}


def calls_estimate(cells: int, experts: int) -> dict:
    """돌 셀 수·전문가 수로 호출 수의 낮은·높은 끝(CALLS_PER_CELL · SWEEP_CALLS_PER_EXPERT)."""
    return {"low": cells * CALLS_PER_CELL[0] + experts * SWEEP_CALLS_PER_EXPERT[0],
            "high": cells * CALLS_PER_CELL[1] + experts * SWEEP_CALLS_PER_EXPERT[1]}


# ---------------------------------------------------------------- 잡 만들기
def in_flight(store: Any, *, job_id: str | None = None, target_key: str | None = None) -> dict:
    """아직 도는(running) 전문가 머리·셀 수 — {heads, cells}. `job_id` 를 주면 그 잡의 것(run_id), `target_key` 를 주면 그 대상의
    것 전부다. 코드 보류는 도는 호출을 닫지 않으므로(M2.md 5절 #13) 잡이 paused 여도 0 이 아닐 수 있다(R3A-1)."""
    col, value = ("run_id", job_id) if job_id is not None else ("target_key", target_key)
    row = store.query_one(
        f"SELECT (SELECT COUNT(*) FROM rr_expert_reports WHERE {col} = ? AND state = 'running') AS heads,"
        f" (SELECT COUNT(*) FROM rr_review_cells WHERE {col} = ? AND state = 'running') AS cells", (value, value))
    return {"heads": int(row["heads"] or 0), "cells": int(row["cells"] or 0)}


def close_progress(store: Any, job_id: str, state: str) -> None:
    """루프를 거치지 않고 끝난 잡(도는 것이 없는 paused·queued 의 취소)의 진행판을 끝난 모양으로 적는다 — phase=state, 워커 없음,
    기다림 없음, 원장을 다시 센 값(R3A-1 · R3A-11)."""
    body = JobProgress(store, job_id, clock=now_epoch).finish(state)
    store.execute("UPDATE rr_jobs SET progress_json = ? WHERE id = ?", (body, job_id))


def _refuse_live_jobs(store: Any, target_key: str) -> None:
    """살아 있는 검토 잡(409 review_job_exists)·아직 도는 카드 대조 호출(409 review_in_flight)·패널 잡(409 panel_job_running)·
    다시 저장을 기다리는 패널(409 repersist_pending — 검토 마감이 그 패널이 pending 으로 돌려 둔 좌석을 닫으면 다시 저장이
    seats_moved 로 영영 막힌다, RR-ADV-1)이 있으면 거절한다."""
    marks = ",".join("?" * len(LIVE_STATES))
    live = store.query_one(
        f"SELECT id, state FROM rr_jobs WHERE target_key = ? AND mode = 'reviews' AND state IN ({marks})"
        " ORDER BY created_at DESC LIMIT 1", (target_key, *LIVE_STATES))
    if live is not None:
        raise AppError("review_job_exists", f"이 대상에는 살아 있는 검토 잡({live['id']}, {live['state']})이 있다 — 그 잡을"
                       " 재개하거나 취소한 뒤 새로 만든다.", 409, detail={"job_id": live["id"], "state": live["state"]})
    # 잡은 끝났는데 워커가 아직 쥔 전문가·셀이 있다 — 지금 범위를 찍으면 그 셀은 옛 잡 id 를 단 채 나중에 놓인다(R3A-1).
    busy = in_flight(store, target_key=target_key)
    if busy["heads"] or busy["cells"]:
        raise AppError("review_in_flight", f"이 대상에는 아직 도는 카드 대조 호출이 있다(전문가 {busy['heads']}명 · 셀"
                       f" {busy['cells']}개) — 앞 잡의 워커가 그 호출을 닫고 놓을 때까지 기다렸다가 다시 만든다.", 409,
                       detail=busy)
    panel = store.query_one(
        f"SELECT id, state FROM rr_jobs WHERE target_key = ? AND {runner.PANEL_JOBS_SQL} AND state IN ({marks})"
        " ORDER BY created_at DESC LIMIT 1", (target_key, *LIVE_STATES))
    if panel is not None:
        raise AppError("panel_job_running", f"이 대상에는 살아 있는 패널 잡({panel['id']}, {panel['state']})이 있다 — 그 잡이"
                       " 끝나거나 취소된 뒤 검토 잡을 만든다.", 409, detail={"job_id": panel["id"], "state": panel["state"]})
    waiting = runner.awaiting_repersist(store, target_key)
    if waiting:
        raise AppError(runner.REPERSIST_PENDING_CODE, runner.repersist_pending_note(waiting), 409,
                       detail={"panels": [p["id"] for p in waiting]})


def create_review_job(store: Any, target_key: str, *, owner_sub: str, requester_sub: str | None = None,
                      scope: Mapping[str, Any] | None = None, user_memo: str | None = None, consent: bool = False,
                      consent_source: str | None = None, settings: Any | None = None) -> dict:
    """검토 잡 1건을 세운다 — 네트워크를 부르지 않는다(격자와 범위는 여기서, 카드 묶음·호출은 루프가).

    범위는 `{tiers?, domains?, agents?, unit_ids?}`(칸끼리 AND, 빠진 칸은 전부)다. 격자는 범위와 상관없이 로스터 전원 × 검토
    대상 단위이고, 범위는 그 가운데 이 잡이 집을 셀이다(X1-27 — 범위 밖 셀은 pending 으로 남는다).
    거절 — 409 review_disabled(HWAXRISK_REVIEW_ENABLED=0) · 404 E404 · 409 review_job_exists · 409 review_in_flight(그 대상의
    전문가·셀이 아직 running — 끝난 잡의 워커가 놓기를 기다린다) · 409 panel_job_running · 409 repersist_pending · 422 units_absent(활성 빌드가 ok·oversize 가 아니다) · 422 scope_invalid · 422 scope_empty · 422
    input_gap_m3(범위에 ECAD 에 기대는데 ECAD 가 없는 전문가 — 입력 결손 호출은 M3) · 409 review_too_large(높은 끝 추정이
    HWAXRISK_REVIEW_MAX_CALLS 초과) · 422 consent_required(HWAXRISK_REVIEW_CONSENT_CALLS 초과인데 consent 가 없다) · 422
    pat_unavailable(쓸 사용자 PAT 가 없다 — 포털에서 PAT 를 등록한다, 서비스 계정으로 내려가지 않는다).
    반환 {job_id, mode, cells_total, cells_in_scope, experts_in_scope, units, calls_estimate{low, high},
    credential{kind, email, exp}, credential_note?}. 높은 끝 추정 소요(호출 × 300초 ÷ 동시 수)가 PAT 남은 수명보다 길거나
    요청자 PAT 를 수명 때문에 건너뛰었으면 `credential_note` 로 미리 알린다.
    """
    from app import routes  # noqa: PLC0415 — routes 는 runner·planner 를 거쳐 무겁다(같은 문을 쓴다).

    cfg = config.settings if settings is None else settings
    routes.require_review_enabled(cfg)
    target = store.query_one("SELECT target_key FROM rr_targets WHERE target_key = ?", (target_key,))
    if target is None:
        raise AppError("E404", f"타깃({target_key}) 을 찾을 수 없습니다.", 404)
    _refuse_live_jobs(store, target_key)
    build = units.active_build(store, target_key)
    if build is None or build["status"] not in units.OPEN_STATUSES:
        state = units.summary_of(store, target_key)
        raise AppError("units_absent", f"검토 단위가 서지 않았다(빌드 {state.get('status')}) — 단위를 세운 뒤"
                       f"(POST /api/targets/{target_key}/units) 검토 잡을 만든다.", 422, detail={"units": state})
    unit_rows = units.load_units(store, target_key, reviewable_only=True)
    order = planner.review_order(store, target_key)
    picked = resolve_scope(scope, order, unit_rows)
    gaps = [r for r in picked["experts"] if r["input_gaps"]]
    if gaps:
        raise AppError("input_gap_m3", f"범위에 입력 결손 전문가 {len(gaps)}명이 있다(ECAD 에 기대는데 이 대상에 ECAD 가 없다)"
                       " — 입력 결손 호출은 M3 다. 범위(domains·agents)에서 빼고 만든다.", 422,
                       detail={"agents": [r["agent_key"] for r in gaps],
                               "input_gaps": sorted({g for r in gaps for g in r["input_gaps"]})})
    agents = [r["agent_key"] for r in picked["experts"]]
    states = {(r["unit_id"], r["agent_key"]): r["state"] for r in store.query(
        "SELECT unit_id, agent_key, state FROM rr_review_cells WHERE target_key = ?", (target_key,))}
    to_run = [(a, u) for a in agents for u in picked["unit_ids"] if states.get((u, a), "pending") == "pending"]
    estimate = calls_estimate(len(to_run), len({a for a, _ in to_run}))
    if estimate["high"] > int(cfg.risk_review_max_calls):
        raise AppError("review_too_large", f"호출 추정의 높은 끝 {estimate['high']:,}회가 상한 {int(cfg.risk_review_max_calls):,}회"
                       "(HWAXRISK_REVIEW_MAX_CALLS)를 넘는다 — 범위(tiers·domains·agents·unit_ids)를 줄여 나눠 돈다.", 409,
                       detail={"calls_estimate": estimate, "knob": "HWAXRISK_REVIEW_MAX_CALLS"})
    if estimate["high"] > int(cfg.risk_review_consent_calls) and not consent:
        raise AppError("consent_required", f"호출 추정의 높은 끝 {estimate['high']:,}회가 {int(cfg.risk_review_consent_calls):,}회"
                       "(HWAXRISK_REVIEW_CONSENT_CALLS)를 넘는다 — consent:true 로 명시 승인한다.", 422,
                       detail={"calls_estimate": estimate, "knob": "HWAXRISK_REVIEW_CONSENT_CALLS"})
    credential, credential_note = review_credential(store, cfg, owner_sub, requester_sub)
    if credential is None:
        raise AppError("pat_unavailable", f"카드 대조 검토는 사용자 PAT 로만 돈다 — {credential_note}. 포털에서 PAT 를 발급해"
                       " 등록한 뒤 다시 만든다(서비스 계정으로 내려가지 않는다).", 422,
                       detail={"fix": "portal_pat", "knob": "HWAXRISK_REVIEW_CALL_TIMEOUT_S"})
    now = now_epoch()
    notes = [credential_note] if credential_note else []
    workers = max(1, int(cfg.risk_review_concurrency))
    need_s = math.ceil(estimate["high"] / workers) * EST_CALL_S
    left = credential["exp"] - now
    if need_s > left:
        notes.append(f"{credential['email']} 의 PAT 남은 수명 {max(left, 0) / 3600:.1f}시간이 이 잡의 높은 끝 추정 소요"
                     f" {need_s / 3600:.1f}시간(호출 {estimate['high']:,}회 × {EST_CALL_S}초 ÷ 동시 {workers})보다 짧다 — 도중에"
                     " 만료되면 잡이 credential 로 멈춘다(서비스 계정으로 내려가지 않는다). 포털에서 PAT 를 다시 발급해"
                     " 등록하고 재개하면 이어 돈다")
    job_id = new_uuid()
    params = {
        "scope": picked["scope"], "user_memo": str(user_memo) if user_memo else None, "requester": requester_sub,
        "consent": bool(consent), "consent_source": consent_source if consent else None,
        "credential": credential, "calls_estimate": estimate,
        # 잡에 복사해 두는 실행 설정 — 도는 중에 설정이 바뀌어도 이 잡의 표본·배치는 바뀌지 않는다(결정론의 전제).
        "knobs": {"dual_rate": 1.0, "sweep": "on", "filter": "off", "max_charged": int(cfg.risk_review_max_charged),
                  "sample_salt": review_verify.SAMPLE_SALT},
    }
    with store.tx():
        # 확인과 쓰기 사이에 다른 잡이 서지 않게 트랜잭션 안에서 문을 다시 본다(패널 잡 만들기도 같은 트랜잭션에서 본다).
        _refuse_live_jobs(store, target_key)
        plan = review_cells.plan_cells(store, target_key, now=now)
        review_cells.assign_scope(store, target_key, job_id, agents=agents, unit_ids=picked["unit_ids"], now=now)
        store.execute(
            "INSERT INTO rr_jobs(id, target_key, owner_sub, tier, state, concurrency, params_json, progress_json,"
            " credential_email, panels_done, panels_total, created_at, updated_at, mode)"
            " VALUES (?, ?, ?, NULL, 'queued', ?, ?, ?, ?, 0, NULL, ?, ?, ?)",
            (job_id, target_key, owner_sub, workers, canonical_json(params),
             canonical_json({"mode": MODE, "phase": "pack"}), credential["email"], now, now, MODE))
    out = {"job_id": job_id, "mode": MODE, "cells_total": plan["cells_total"],
           "cells_in_scope": len(agents) * len(picked["unit_ids"]), "experts_in_scope": len(agents),
           "units": plan["units"], "calls_estimate": estimate, "credential": credential}
    if notes:
        out["credential_note"] = " · ".join(notes)
    return out


# ================================================================ 검토 루프(m2-wp3b S8)
# 선점 단위는 전문가 세션이다 — 워커 하나가 전문가 한 명을 쥐고 그 사람의 범위 안 셀을 정해진 차례(훑기 → 묶음 먼저 fwd → 빠진 카드
# 재질의 → rev → 단독 → 카드 밖 → 정산)로 돈다. 루프 스레드는 2초마다 틱을 돌며 보류를 풀고·잡을 닫고·창을 보고·워커를 띄운다.
# 엔진 호출은 늘 워커에서 한다(루프 스레드가 HTTP 를 붙들지 않는다 — m-04, 창·관문 조회는 짧게 기다리는 탐침 스레드다).
HEALTH_CACHE_S = 30                 # 서버 관문 limit(/health) 캐시
LIMITS_CACHE_S = 60                 # 창·판(/card-review/limits) 캐시
PROBE_JOIN_S = 1.0                  # 틱이 탐침을 기다리는 한도 — 넘으면 이번 틱은 새 호출을 내지 않고 기다린다(지난 답을 쓰지 않는다)
PROGRESS_INTERVAL_S = 60            # progress_json 을 다시 세는 간격(단계·차단기·워커 변화는 즉시 적는다)
STOP_POLL_S = 5                     # 도는 호출이 잡 행(취소·사람의 정지)을 읽는 간격
WAIT_SLICE_S = 5                    # 기다림을 이만큼씩 쪼개 그 사이 잡 상태를 본다(코드 보류·취소가 기다림을 끊는다)
MISSING_REASKS = 2                  # 빠진 카드 재질의(fwd) — 셀마다 최대
SOLO_REASKS = 2                     # 단독 재질의가 그 카드를 빼먹었을 때 다시 묻는 수
MORE_REASKS = 3                     # 카드 밖 줄이 findings_max 에 닿으면 '이것 말고 더' 를 다시 묻는 수(X1-16)
INTERNAL_BACKOFF_S = 60             # 워커가 예기치 않은 예외로 끝난 전문가를 다시 집기 전의 대기
INTERNAL_STRIKES = 3                # 같은 셀(또는 머리 몫)의 예기치 않은 예외가 잇달아 이만큼이면 셀을 차감하거나 잡을 멈춘다(R3A-2)
CALL_CAP_FACTOR = 3                 # 셀당 호출 수 상한 = 3 × (2·묶음 수 + 점검 카드 수 + 4)(m-02)
CALL_CAP_BASE = 4
# 팩 502 가 범위 전원에게 이어지면 잡 보류 aidh_unreachable 다(카드 저장소·게이트웨이 쪽 문제 — 전문가를 하나씩 실패시키지 않는다).
AIDH_CODES = frozenset({"card_fetch_failed", "card_list_failed", "card_list_unstable", "tools_unavailable"})
KNOWN_CTX_SOURCES = ("server", "env")          # 창 출처가 이것이면 서버가 창을 안다(fallback 은 가정한 값)
CREDENTIAL_FIX = "포털에서 PAT 를 다시 발급해 등록하고 재개한다 — 서비스 계정으로 내려가지 않는다"
CTX_KNOB = "LLM_CONTEXT_TOKENS"
DISABLED = "review_disabled"          # 이 박스의 검토 스위치(HWAXRISK_REVIEW_ENABLED)가 꺼져 있다 — 새 선점·새 호출을 내지 않는다
_ENGINE_ERRORS = (EngineBusy, PatUnavailable, EngineRejected, EngineStreamLost)
_CALL_STATE = {review_ops.INFRA: "infra_fail", review_ops.CONTENT: "content_fail", review_ops.WAIT: "wait"}
_BASIS_OF_PACK = {cardpack.CARD_BASIS_CARDS: "cards", cardpack.CARD_BASIS_BACKGROUND: "background",
                  cardpack.CARD_BASIS_NONE: "role_only"}
_JUDGEMENT_FIRST = {"FAIL": 0, "WARNING": 1}

# S11(품질 수치)이 꽂는 자리 — (store, target_key, job_id) -> dict | None. 진행판이 60초마다 불러 progress_json.quality 에 넣는다
# (5초 폴링이 원장을 다시 세지 않게 — M2.md 5절 #16). None 이면 칸을 비워 둔다.
QUALITY_HOOK: Callable[[Any, str, str], Mapping[str, Any] | None] | None = None


def call_cap(decks: int, checkable: int) -> int:
    """셀당 호출 수 상한(m-02) — 넘으면 그 셀은 failed('call_cap') 다. 기다림은 세지 않는다(tries)."""
    return CALL_CAP_FACTOR * (2 * int(decks) + int(checkable) + CALL_CAP_BASE)


def _s(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def unit_size(unit: Mapping[str, Any], lim: Mapping[str, Any]) -> int:
    """단위가 프롬프트에서 차지하는 글자 수의 상계 — 엔진 `card_review.unit_size` 의 식을 limits 의 수(`unit_size{per_line, base}`)로
    잰다(P-15 — 두 리포가 수를 베끼지 않는다). plan 요청의 `body_chars` 다."""
    size = lim.get("unit_size") if isinstance(lim.get("unit_size"), Mapping) else {}
    per, base = int(size.get("per_line", 11)), int(size.get("base", 160))
    rows = [x for k in ("lines", "context", "evidence") for x in unit.get(k) or () if isinstance(x, Mapping)]
    n = sum(len(_s(x.get("text"))) + len(_s(x.get("ref"))) + per for x in rows)
    n += sum(len(_s(m.get("kind"))) + len(_s(m.get("note"))) + per for m in unit.get("missing") or ()
             if isinstance(m, Mapping))
    n += len(_s(unit.get("title"))) + len(_s(unit.get("summary"))) + len(_s(unit.get("notes"))) + base
    return n + len(rows) * max(0, 1 + max(2, len(str(len(rows)))) - 4)


def manifest_size(item: Mapping[str, Any], lim: Mapping[str, Any]) -> int:
    """훑기 목록 한 줄의 글자 수 — 종류·제목·목록 글 + limits 의 `manifest_item.overhead`(별칭·괄호·구분자). plan 의 `manifest_chars`."""
    head = lim.get("manifest_item") if isinstance(lim.get("manifest_item"), Mapping) else {}
    return len(_s(item.get("kind"))) + len(_s(item.get("title"))) + len(_s(item.get("text"))) + int(head.get("overhead", 14))


def prompt_key(lim: Mapping[str, Any]) -> str:
    """셀 입력 지문의 prompt_rev 자리 — 종류별 판 셋을 한 글로(셋 가운데 하나가 바뀌어도 셀이 처음부터 돈다)."""
    revs = lim.get("prompt_rev") if isinstance(lim.get("prompt_rev"), Mapping) else {}
    return ",".join(f"{k}={revs[k]}" for k in sorted(revs))


def _json(text: Any, default: Any) -> Any:
    if not text:
        return default
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _job_of(row: Mapping[str, Any]) -> dict:
    job = dict(row)
    job["params"] = _json(job.get("params_json"), {})
    return job


def credential_message(what: str, exc: BaseException) -> str:
    """credential 보류의 글 — 무엇이(코드) 왜 멈췄고 어디를 고치나. 엔진 클라이언트의 글에 고칠 곳이 이미 있으면 되풀이하지 않는다."""
    code = getattr(exc, "code", None) or "pat_unavailable"
    text = str(exc)
    return f"{what}: {code} — {text}" + ("" if "서비스 계정" in text else f" — {CREDENTIAL_FIX}")


def _credential_email(job: Mapping[str, Any]) -> str | None:
    cred = (job.get("params") or {}).get("credential") or {}
    return cred.get("email") if isinstance(cred, Mapping) else None


# ---------------------------------------------------------------- 멈춤 물음(M2.md 5절 #13)
def should_stop_review(store: Any, job_id: str, stop: threading.Event | None = None, *,
                       poll_s: float = STOP_POLL_S) -> Callable[[], str | None]:
    """도는 카드 대조 호출이 '스트림을 닫을까' 를 묻는 함수 — 닫을 까닭(글) 또는 None.

    닫는 것은 사람의 손과 앱 종료뿐이다 — 취소(cancelling·cancelled), 사람의 정지(paused + hold_code='user'), 러너 종료(`stop`).
    코드가 건 보류(llm_outage 따위)는 도는 호출을 닫지 않는다 — 그 호출은 끝까지 가고 다음 호출만 시작하지 않는다(P-02(4)). 패널의
    `runner._stop_reader` 는 paused 면 무조건 닫으므로 검토 잡에는 쓰지 않는다. 잡 행은 `poll_s` 간격으로만 읽고, 읽지 못하면 앞의
    답을 둔다(조회 한 번의 실패로 호출을 닫지 않는다)."""
    last: dict[str, Any] = {"at": None, "why": None}

    def ask() -> str | None:
        if stop is not None and stop.is_set():
            return "앱이 멈춘다 — 이 호출만 닫고 다음 기동이 차감 없이 이어 돈다"
        tick = time.monotonic()
        if last["at"] is not None and tick - last["at"] < poll_s:
            return last["why"]
        last["at"] = tick
        try:
            row = store.query_one("SELECT state, hold_code FROM rr_jobs WHERE id = ?", (job_id,))
        except Exception:  # noqa: BLE001 — 위 설명대로다.
            log.exception("검토 잡 %s 상태 조회 실패(비치명) — 호출은 계속 돈다", job_id)
            return last["why"]
        why = None
        if row is None:
            why = "검토 잡이 없어졌다"
        elif row["state"] in ("cancelling", "cancelled"):
            why = "사용자가 검토 잡을 취소했다"
        elif row["state"] == "paused" and row["hold_code"] == "user":
            why = "사용자가 검토 잡을 일시정지했다"
        last["why"] = why
        return why

    return ask


# ---------------------------------------------------------------- 진행 신호(progress_json)
class JobProgress:
    """검토 잡 하나의 진행판(`rr_jobs.progress_json`) — S12 의 coverage.review.job 과 Claude 길잡이가 읽는다.

    모양 {mode, phase, packs{total, todo, ok, empty, error, blocked}, experts{total, by_state}, cells{total, by_state, by_basis,
    in_scope, out_of_scope_pending, failed}, calls{ok, infra_fail, content_fail, wait, aborted, last_ok_at, avg_ok_s},
    workers[{agent_key, purpose, unit_id, call_kind, variant, deck_id, started_at, last_frame_at, last_event_at, last_step}],
    breaker{state, trips, hold_until, since}, waiting{reason, since, retry_at, note?} | None, server{active, limit},
    quality(S11 의 QUALITY_HOOK) | None}.
    원장을 다시 세는 것은 PROGRESS_INTERVAL_S 마다와 강제(단계·차단기·끝) 때뿐이다. 워커의 시작·끝·호출 바뀜은 센 값을 둔 채 곧바로
    적고, 프레임마다의 신호는 PROGRESS_INTERVAL_S 간격으로 적는다. 끝난 잡의 행은 고치지 않는다(늦은 워커가 끝난 진행판을 덮지 않게).
    """

    def __init__(self, store: Any, job_id: str, *, clock: Callable[[], int],
                 server: Callable[[], Mapping[str, Any]] | None = None) -> None:
        self.store = store
        self.job_id = job_id
        self.clock = clock
        self._server = server
        self._lock = threading.RLock()
        row = store.query_one("SELECT target_key, progress_json FROM rr_jobs WHERE id = ?", (job_id,))
        self.target_key = row["target_key"] if row is not None else None
        prev = _json(row["progress_json"] if row is not None else None, {})
        breaker = prev.get("breaker") if isinstance(prev.get("breaker"), dict) else {}
        self.body: dict[str, Any] = {
            "mode": MODE, "phase": prev.get("phase") or "pack", "packs": {}, "experts": {}, "cells": {}, "calls": {},
            "workers": [],
            "breaker": {"state": breaker.get("state") or "closed", "trips": int(breaker.get("trips") or 0),
                        "hold_until": breaker.get("hold_until"), "since": breaker.get("since")},
            "waiting": prev.get("waiting") if isinstance(prev.get("waiting"), dict) else None,
            "server": {"active": None, "limit": None}, "quality": prev.get("quality"),
        }
        self._workers: dict[str, dict] = {}
        self._counted_at: int | None = None
        self._frames_at: int | None = None

    # -- 셈 -------------------------------------------------------------------------
    def _count(self) -> None:
        store, job_id = self.store, self.job_id
        heads = [dict(r) for r in store.query(
            "SELECT state, pack_status FROM rr_expert_reports WHERE target_key = ? AND run_id = ?", (self.target_key, job_id))]
        packs = {"total": len(heads), "todo": 0, "ok": 0, "empty": 0, "error": 0, "blocked": 0}
        for h in heads:
            key = "blocked" if h["state"] == "blocked" else (h["pack_status"] if h["pack_status"] in packs else "todo")
            packs[key] += 1
        by_state = {s: sum(1 for h in heads if h["state"] == s) for s in review_cells.EXPERT_STATES}
        summary = review_cells.review_summary(store, self.target_key, job_id=job_id) if self.target_key else {}
        cells = dict(summary.get("cells") or {})
        scope = cells.get("in_scope") or {}
        cells["failed"] = int((scope.get("by_state") or {}).get("failed", 0))
        calls = {s: 0 for s in ("ok", "infra_fail", "content_fail", "wait", "aborted")}
        for r in store.query("SELECT state, COUNT(*) AS n FROM rr_review_calls WHERE run_id = ? GROUP BY state", (job_id,)):
            if r["state"] in calls:
                calls[r["state"]] = int(r["n"])
        ok = store.query_one("SELECT MAX(started_at) AS last_at, AVG(duration_ms) AS avg_ms FROM rr_review_calls"
                             " WHERE run_id = ? AND state = 'ok'", (job_id,))
        calls["last_ok_at"] = ok["last_at"] if ok is not None else None
        calls["avg_ok_s"] = (round(float(ok["avg_ms"]) / 1000.0, 1) if ok is not None and ok["avg_ms"] is not None
                             else None)
        self.body.update({"packs": packs, "experts": {"total": len(heads), "by_state": by_state}, "cells": cells,
                          "calls": calls})
        if self._server is not None:
            self.body["server"] = dict(self._server())
        if QUALITY_HOOK is not None and self.target_key:
            try:
                self.body["quality"] = QUALITY_HOOK(store, self.target_key, job_id)
            except Exception:  # noqa: BLE001 — 품질 수치가 진행판을 막지 않는다.
                log.exception("검토 잡 %s 품질 수치 실패(비치명)", job_id)

    def payload(self) -> dict:
        with self._lock:
            return json.loads(canonical_json({**self.body, "workers": list(self._workers.values())}))

    def _write(self, *, final_state: str | None = None) -> None:
        body = canonical_json({**self.body, "workers": list(self._workers.values())})
        try:
            if final_state is None:
                self.store.execute("UPDATE rr_jobs SET progress_json = ? WHERE id = ? AND state IN"
                                   " ('queued', 'running', 'paused', 'cancelling')", (body, self.job_id))
            else:
                self.store.execute("UPDATE rr_jobs SET progress_json = ? WHERE id = ?", (body, self.job_id))
        except Exception:  # noqa: BLE001 — 진행 표시를 못 적었다고 검토를 멈추지 않는다.
            log.exception("검토 잡 %s 진행 기록 실패(비치명)", self.job_id)

    def refresh(self, *, force: bool = False) -> None:
        with self._lock:
            now = self.clock()
            if not force and self._counted_at is not None and now - self._counted_at < PROGRESS_INTERVAL_S:
                return
            self._counted_at = now
            try:
                self._count()
            except Exception:  # noqa: BLE001
                log.exception("검토 잡 %s 진행 셈 실패(비치명)", self.job_id)
            self._write()

    def set(self, *, count: bool = False, **fields: Any) -> None:
        """칸 몇을 바꾸고 곧바로 적는다(단계·차단기·기다림). `count` 면 원장도 다시 센다."""
        with self._lock:
            changed = any(self.body.get(k) != v for k, v in fields.items())
            self.body.update(fields)
            if count:
                self._counted_at = self.clock()
                try:
                    self._count()
                except Exception:  # noqa: BLE001
                    log.exception("검토 잡 %s 진행 셈 실패(비치명)", self.job_id)
            if changed or count:
                self._write()

    def finish(self, state: str) -> str:
        """끝난 잡의 진행판(phase=state, 다시 센 값) — 잡을 닫는 UPDATE 에 같이 싣는 글을 돌려준다."""
        with self._lock:
            self.body["phase"] = state
            self.body["waiting"] = None
            self._workers.clear()
            try:
                self._count()
            except Exception:  # noqa: BLE001
                log.exception("검토 잡 %s 진행 셈 실패(비치명)", self.job_id)
            return canonical_json({**self.body, "workers": []})

    def breaker(self) -> dict:
        with self._lock:
            return dict(self.body["breaker"])

    # -- 워커 ------------------------------------------------------------------------
    def worker(self, key: str, **fields: Any) -> None:
        with self._lock:
            entry = self._workers.setdefault(key, {"agent_key": None, "purpose": None, "unit_id": None, "call_kind": None,
                                                   "variant": None, "deck_id": None, "started_at": None,
                                                   "last_frame_at": None, "last_event_at": None, "last_step": ""})
            entry.update(fields)
            self._write()

    def frame(self, key: str, frame: Mapping[str, Any]) -> None:
        with self._lock:
            entry = self._workers.get(key)
            if entry is None:
                return
            entry.update({k: frame.get(k) for k in ("last_frame_at", "last_event_at", "last_step") if k in frame})
            now = self.clock()
            if self._frames_at is not None and now - self._frames_at < PROGRESS_INTERVAL_S:
                return
            self._frames_at = now
            self._write()

    def worker_end(self, key: str) -> None:
        with self._lock:
            if self._workers.pop(key, None) is not None:
                self._write()


# ---------------------------------------------------------------- 탐침(창·관문 조회 — 루프 스레드를 붙들지 않는다)
@dataclass
class _Probe:
    """탐침 하나의 마지막 답. `at` 은 그 답이 끝난 시각이고, None 이면 쓸 답이 없다(새 탐침이 도는 중이거나 버렸다)."""

    value: Any = None
    error: BaseException | None = None
    at: int | None = None
    thread: threading.Thread | None = None


class _Stop(Exception):
    """세션이 여기서 멈춘다 — `release` 면 쥔 전문가를 놓는다(도는 셀은 차감 없이 pending), `not_before` 는 그 머리의 백오프."""

    def __init__(self, why: str, *, not_before: int | None = None, release: bool = True) -> None:
        super().__init__(why)
        self.why = why
        self.not_before = not_before
        self.release = release


@dataclass
class _Answer:
    """호출 한 건의 답 — 새로 받은 것(`call` 이 원장에 쓸 행의 바탕)이거나 같은 시도에서 이미 받은 것(`cached`)."""

    result: dict
    call: dict | None
    cached: bool


@dataclass
class _Cell:
    """세션이 돌리는 셀 하나의 이번 시도."""

    row: dict
    payload: dict
    refs: frozenset
    fwd_bodies: dict = field(default_factory=dict)      # deck_id → 그 묶음 전부를 실은 fwd 본문(rev 계획의 바탕)
    dual_decks: set = field(default_factory=set)        # rev 를 물은 묶음
    forced_solo: list = field(default_factory=list)     # pair_over·같은 본문(1장 묶음)이라 단독으로 돌릴 카드
    log: list = field(default_factory=list)             # 이번 시도의 호출 요약(새로 받은 것과 원장에서 다시 읽은 것)
    inj: list = field(default_factory=list)
    samples_done: bool = True
    alive: bool = True

    @property
    def unit_id(self) -> str:
        return str(self.row["unit_id"])

    @property
    def attempt(self) -> int:
        return int(self.row.get("charged") or 0)


def finalize_expert(store: Any, job: Mapping[str, Any], head: Mapping[str, Any], *, lease_owner: str,
                    now: int | None = None) -> str | None:
    """전문가 마감 — 범위 안 열린 셀이 0 이 된 세션의 끝에 부른다(선점을 쥔 채로). 옮긴 머리 상태(ready·partial) 또는 None(선점을
    잃었다).

    finding 승격·의견 행·원장 마감(S9)과 보고서(S10)는 `expert_report.prepare` 가 읽기만으로 짓고, 쓰기는 머리를 닫는
    `review_cells.close_expert` 와 같은 트랜잭션이다 — 중간에 앱이 내려가면 아무것도 남지 않고, 그 머리는 재기동 복구 뒤
    `finalize` 선점으로 다시 마감된다(같은 원장이면 같은 id 에 같은 값이다).
    """
    target_key, agent = str(job["target_key"]), str(head["agent_key"])
    prepared = expert_report.prepare(store, target_key, agent)
    with store.tx():
        if expert_report.commit(store, prepared, lease_owner=lease_owner, now=now) is None:
            return None
        return review_cells.close_expert(store, target_key, agent, lease_owner=lease_owner, now=now)


# ---------------------------------------------------------------- 전문가 세션
class _Session:
    """워커 하나가 쥔 전문가 한 명 — 카드 묶음 받기(`fetch_pack`) 또는 검토(`run`). 끝나면 머리를 놓거나 마감한다.

    같은 시도 안에서 이미 답을 받은 호출은 다시 내지 않는다 — 호출 원장의 `request_hash`(셀 입력 지문 · 시도 · 요청 본문의 해시)가
    같고 `ok` 인 행의 result 를 다시 읽는다. 재기동·인프라 실패 뒤의 세션이 같은 차례를 그대로 되밟으며 끊긴 호출부터 이어 내고(나갈
    기준 3), 셀 입력이 바뀌거나(`start_cell` 이 판정을 지운다) 내용 탓으로 새 시도가 서면(`begin_attempt`) 해시가 달라 처음부터다."""

    def __init__(self, loop: "ReviewLoop", job: Mapping[str, Any], head: Mapping[str, Any], purpose: str) -> None:
        self.loop = loop
        self.store = loop.store
        self.settings = loop.settings
        self.engine = loop.engine
        self.job = dict(job)
        self.job_id = str(job["id"])
        self.target_key = str(job["target_key"])
        self.head = dict(head)
        self.agent = str(head["agent_key"])
        self.lease = str(head["lease_owner"])
        self.purpose = purpose
        params = self.job.get("params") or {}
        cred = params.get("credential") if isinstance(params.get("credential"), Mapping) else {}
        self.email = str(cred.get("email") or "")
        self.cred_kind = cred.get("kind")
        knobs = params.get("knobs") if isinstance(params.get("knobs"), Mapping) else {}
        self.max_charged = int(knobs.get("max_charged") or getattr(self.settings, "risk_review_max_charged", 2) or 2)
        self.dual_rate = float(knobs.get("dual_rate", 1.0))
        self.salt = str(knobs.get("sample_salt") or review_verify.SAMPLE_SALT)
        self.progress = loop.progress(self.job_id)
        self.wkey = f"{self.agent}:{self.lease[-8:]}"
        self.should_stop = should_stop_review(self.store, self.job_id, loop.stop, poll_s=loop.poll_s)
        self.pack: cardpack.FrozenPack | None = None
        self.lim: dict = {}
        self.plan: dict = {}
        self.sweep: dict = {}
        self.payloads: dict[str, dict] = {}
        self.focus: _Cell | None = None          # 지금 다루는 셀(없으면 머리 몫) — 예기치 않은 예외를 그 셀에 센다(R3A-2)
        self.call: dict | None = None            # 원장에 running 으로 둔 채 아직 닫지 않은 호출 행(begin_call 의 바탕)

    # -- 바탕 ---------------------------------------------------------------------------
    def now(self) -> int:
        return int(self.loop.clock())

    def _head_row(self) -> dict:
        row = self.store.query_one("SELECT * FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?",
                                   (self.target_key, self.agent))
        return dict(row) if row is not None else {}

    def _job_row(self) -> dict:
        row = self.store.query_one("SELECT state, hold_code FROM rr_jobs WHERE id = ?", (self.job_id,))
        return dict(row) if row is not None else {"state": None, "hold_code": None}

    def _gate(self) -> None:
        """새 호출을 내도 되나 — 러너가 멈추거나 이 박스의 검토 스위치가 꺼졌거나 잡이 running 이 아니면(사람·코드의 보류·취소)
        세션을 멈춘다. 도는 호출은 이 물음 밖이라 끝까지 간다."""
        if self.loop.stop.is_set():
            raise _Stop("stopped")
        if not config.review_enabled(self.loop.settings):
            raise _Stop(DISABLED)
        state = self._job_row()["state"]
        if state != "running":
            raise _Stop(f"job_{state}")

    def _sleep(self, seconds: int | None, *, reason: str) -> None:
        """기다림 — WAIT_SLICE_S 씩 쪼개 그 사이 잡 상태를 본다. 기다리는 동안 진행판에 waiting 을 적는다(아무것도 세지 않는다)."""
        left = max(int(seconds or review_ops.WAIT_DEFAULT_S), 1)
        now = self.now()
        self.progress.set(waiting={"reason": reason, "since": now, "retry_at": now + left})
        try:
            while left > 0:
                step = min(left, WAIT_SLICE_S)
                if self.loop.pause(step):
                    raise _Stop("stopped")
                left -= step
                self._gate()
        finally:
            self.progress.set(waiting=None)

    def _hold(self, code: str, message: str) -> None:
        self.loop.hold(self.job_id, code, message)

    def _unary(self, fn: Callable[[], Any], what: str) -> Any:
        """단발(limits·plan·pack 밖) 하나 — 기다림은 그 자리에서 다시, 자격은 credential 보류, 잡 부류는 그 보류, 인프라는 머리
        백오프로 놓기, 그 밖(내용 탓)은 앱과 엔진의 계약이 어긋난 것이라 contract 보류다."""
        while True:
            self._gate()
            try:
                return fn()
            except EngineBusy as exc:
                self._sleep(exc.retry_after_s, reason=exc.code or "engine_busy")
            except PatUnavailable as exc:
                self._hold("credential", credential_message(what, exc))
                raise _Stop("credential") from exc
            except (EngineRejected, EngineStreamLost) as exc:
                outcome = engine_client.review_outcome(exc)
                if outcome.klass == review_ops.JOB:
                    self._hold(outcome.hold_code or "contract", f"{what}: {exc}")
                    raise _Stop(outcome.hold_code or "contract") from exc
                if outcome.klass == review_ops.CANCELLED:
                    raise _Stop("cancelled") from exc
                if outcome.klass == review_ops.INFRA:
                    raise _Stop(f"infra:{outcome.code}", not_before=self.now() + review_ops.backoff_s(
                        1, salt=f"{self.target_key}|{self.agent}|{what}")) from exc
                self._hold("contract", f"{what} 를 엔진이 받지 않았다 — {exc}. 에이전트 서버와 리스크 앱의 판을 맞춘 뒤 재개한다")
                raise _Stop("contract") from exc

    # -- 카드 묶음 --------------------------------------------------------------------------
    def fetch_pack(self) -> cardpack.FrozenPack:
        """그 전문가의 카드 묶음을 받아 확인·동결하고 머리에 적는다(m2-wp3b S3 의 받은 결과 가르기). 실패는 그 전문가의 묶음
        재시도(60초부터 두 배)·한도(404 3번 · 502 6번 → 범위 안 셀 failed)·범위 전원 502 면 잡 보류 aidh_unreachable 다."""
        head = self._head_row()
        stats = _json(head.get("stats_json"), {})
        packinfo = stats.get("pack") if isinstance(stats.get("pack"), dict) else {}
        while True:
            self._gate()
            try:
                body = self.engine.pack(self.agent, email=self.email)
                break
            except EngineBusy as exc:
                self._sleep(exc.retry_after_s, reason=exc.code or "review_busy")
            except PatUnavailable as exc:
                self._hold("credential", credential_message(f"카드 묶음({self.agent})", exc))
                raise _Stop("credential") from exc
            except (EngineRejected, EngineStreamLost) as exc:
                outcome = engine_client.review_outcome(exc)
                if outcome.klass == review_ops.JOB:
                    self._hold(outcome.hold_code or "contract", f"카드 묶음({self.agent}): {exc}")
                    raise _Stop(outcome.hold_code or "contract") from exc
                if outcome.klass == review_ops.CANCELLED:
                    raise _Stop("cancelled") from exc
                tries, fail = ((outcome.max_tries, outcome.fail_code) if outcome.klass == review_ops.PACK
                               else (review_ops.PACK_RETRY_MAX, "pack_unavailable"))
                self._pack_failed(outcome.code, int(tries or review_ops.PACK_RETRY_MAX), str(fail), str(exc))
        verdict = cardpack.judge_pack(self.store, self.agent, http_status=200, body=body,
                                      zero_streak_before=int(packinfo.get("zero_streak") or 0))
        stats["pack"] = {"zero_streak": verdict.zero_streak, "was_nonempty": verdict.was_nonempty,
                         "cards_n": verdict.cards_n}
        if not review_cells.write_head(self.store, self.target_key, self.agent, lease_owner=self.lease,
                                       sets={"stats_json": canonical_json(stats)}, now=self.now()):
            raise _Stop("lease", release=False)
        if verdict.status in (cardpack.PACK_OK, cardpack.PACK_EMPTY):
            frozen = cardpack.freeze_pack(self.store, body, agent_key=self.agent)
            if not review_cells.record_pack(self.store, self.target_key, self.agent, lease_owner=self.lease,
                                            status=verdict.status, pack_hash=frozen["pack_key"],
                                            card_basis=frozen["card_basis"], now=self.now()):
                raise _Stop("lease", release=False)
            self.loop.after_success(self.job_id)
            return cardpack.load_pack(self.store, self.agent, frozen["pack_key"])
        outcome = review_ops.classify(verdict.code)
        self._pack_failed(str(verdict.code), int(outcome.max_tries or review_ops.PACK_RETRY_MAX),
                          str(outcome.fail_code or "pack_unavailable"), "; ".join(verdict.problems) or str(verdict.code))
        raise AssertionError("unreachable")  # pragma: no cover — _pack_failed 는 늘 _Stop 을 올린다

    def _pack_failed(self, code: str, tries: int, fail_code: str, message: str) -> None:
        now = self.now()
        attempts = int(self._head_row().get("pack_attempts") or 0) + 1
        if attempts >= tries:
            # 셀 닫기 · 보고서(blocked — 파일럿이 범위의 전문가마다 보고서 한 편을 갖게) · 머리 막기를 한 트랜잭션으로.
            with self.store.tx():
                review_cells.record_pack(self.store, self.target_key, self.agent, lease_owner=self.lease, status="error",
                                         error=code, not_before=None, now=now)
                failed = review_cells.fail_open_cells(self.store, self.target_key, self.agent, code=fail_code,
                                                      error=f"카드 묶음을 {attempts}번 받지 못했다({code}) — {message}",
                                                      run_id=self.job_id, lease_owner=self.lease, now=now)
                why = f"{fail_code}: {code} {attempts}번 — 범위 안 셀 {failed}개를 failed 로 닫았다"
                expert_report.write_blocked(self.store, self.target_key, self.agent, lease_owner=self.lease, why=why,
                                            now=now)
                review_cells.block_expert(self.store, self.target_key, self.agent, lease_owner=self.lease, error=why,
                                          now=now)
            log.warning("검토 잡 %s: %s 의 카드 묶음을 %s번 받지 못해(%s) 범위 안 셀 %s개를 failed(%s)로 닫았다",
                        self.job_id, self.agent, attempts, code, failed, fail_code)
            raise _Stop("pack_blocked", release=False)
        wait_s = review_ops.pack_retry_s(attempts)
        review_cells.record_pack(self.store, self.target_key, self.agent, lease_owner=self.lease, status="error",
                                 error=code, not_before=now + wait_s, now=now)
        if code in AIDH_CODES:
            self.loop.check_aidh(self.job_id, self.target_key)
        raise _Stop(f"pack_error:{code}", not_before=now + wait_s)

    def _load_pack(self) -> cardpack.FrozenPack:
        """얼린 묶음 — 머리가 가리키는 행이 이 박스에 없으면(다른 박스에서 들여온 원장 — 묶음은 반출하지 않는다) 다시 받아 얼린다
        (M2.md 5절 #22)."""
        try:
            pack = cardpack.load_for(self.store, self.target_key, self.agent)
        except cardpack.PackMissing:
            log.info("검토 잡 %s: %s 의 얼린 카드 묶음이 이 박스에 없다 — 다시 받아 얼린다", self.job_id, self.agent)
            pack = None
        return pack if pack is not None else self.fetch_pack()

    # -- 계획 -----------------------------------------------------------------------------
    def _payload(self, unit_id: str) -> dict:
        if unit_id not in self.payloads:
            self.payloads[unit_id] = units.review_payload(self.store, self.target_key, unit_id, self.agent)
        return self.payloads[unit_id]

    def _expect(self, kind: str) -> dict:
        revs = self.lim.get("prompt_rev") if isinstance(self.lim.get("prompt_rev"), Mapping) else {}
        return {"prompt_rev": revs.get(kind), "limits_rev": self.lim.get("limits_rev")}

    def _plan(self) -> dict:
        """그 전문가의 묶음·목록 쪽 계획 — 머리에 얼린 계획이 같은 묶음·같은 창 판이면 그것을 쓰고, 아니면 엔진에 다시 받는다
        (`limits_rev` 가 바뀌면 다시 짜고 입력 지문이 바뀐 셀만 처음부터 돈다). `oversize` 가 비지 않으면 다시 쪼개지 않고 잡을
        ctx_too_small 로 멈춘다(D-22) — 그 단위·카드·목록 쪽과 이 박스의 창을 적는다."""
        assert self.pack is not None
        head = self._head_row()
        frozen = _json(head.get("plan_json"), {})
        if (head.get("limits_rev") == self.lim.get("limits_rev") and frozen.get("pack_key") == self.pack.pack_key
                and isinstance(frozen.get("plan"), dict)):
            plan = frozen["plan"]
        else:
            manifest = units.manifest_items(self.store, self.target_key)
            body = {"cards": [{"alias": a, "record_id": str(self.pack.cards[a]["record_id"]),
                               "checkable": self.pack.cards[a].get("checkable") is True,
                               "chars": int(self.pack.cards[a].get("chars") or 0)} for a in self.pack.order],
                    "units": [{"unit_id": m["unit_id"], "manifest_chars": manifest_size(m, self.lim),
                               "body_chars": unit_size(self._payload(m["unit_id"]), self.lim)} for m in manifest],
                    "expect": {"limits_rev": self.lim.get("limits_rev")}}
            plan = dict(self._unary(lambda: self.engine.plan(body, email=self.email), f"계획({self.agent})"))
            if not review_cells.write_head(self.store, self.target_key, self.agent, lease_owner=self.lease, now=self.now(),
                                           sets={"plan_json": canonical_json({"pack_key": self.pack.pack_key,
                                                                              "limits_rev": self.lim.get("limits_rev"),
                                                                              "plan": plan}),
                                                 "limits_rev": self.lim.get("limits_rev"),
                                                 "prompt_rev": prompt_key(self.lim),
                                                 "norm_rev": self.pack.norm_rev,
                                                 "verify_rev": review_verify.VERIFY_REV,
                                                 "model": self.lim.get("model")}):
                raise _Stop("lease", release=False)
        over = plan.get("oversize") if isinstance(plan.get("oversize"), Mapping) else {}
        parts = [(name, list(over.get(name) or ())) for name in ("units", "cards", "manifest")]
        parts = [(name, items) for name, items in parts if items]
        if parts:
            what = " · ".join(f"{name} {', '.join(map(str, items[:10]))}{' 외' if len(items) > 10 else ''}"
                              for name, items in parts)
            self._hold("ctx_too_small", f"창이 모자라 한 호출에 실을 수 없는 것이 있다({self.agent} 계획의 oversize — {what}). 이 박스의"
                       f" 창은 {int(self.lim.get('ctx_tokens') or 0):,} 토큰({self.lim.get('ctx_source')})이다. 다시 쪼개지 않는다(D-22)"
                       f" — 더 큰 창의 LLM 을 붙이거나({CTX_KNOB}·VLLM_MODEL) 단위 크기 손잡이(HWAXRISK_UNIT_MAX_LINES)를 줄여 단위를"
                       " 다시 세운 뒤 재개한다")
            raise _Stop("ctx_too_small")
        return plan

    # -- 셀 시작 ----------------------------------------------------------------------------
    def _start_cells(self) -> list[_Cell]:
        assert self.pack is not None
        self.focus = None
        now = self.now()
        rows = self.store.query(
            "SELECT unit_id FROM rr_review_cells WHERE target_key = ? AND agent_key = ? AND run_id = ? AND state = 'pending'"
            " AND (not_before IS NULL OR not_before <= ?) ORDER BY unit_seq ASC, unit_id ASC",
            (self.target_key, self.agent, self.job_id, now))
        active = {u["unit_id"] for u in units.load_units(self.store, self.target_key)}
        cells: list[_Cell] = []
        pkey = prompt_key(self.lim)
        for r in rows:
            unit_id = r["unit_id"]
            if unit_id not in active:
                continue
            payload = self._payload(unit_id)
            digest = review_cells.cell_input_hash(unit_hash=payload.get("unit_hash"), evidence_sha=payload.get("evidence_sha"),
                                                  pack_hash=self.pack.pack_key, prompt_rev=pkey,
                                                  limits_rev=self.lim.get("limits_rev"))
            started = review_cells.start_cell(self.store, self.target_key, unit_id, self.agent, lease_owner=self.lease,
                                              input_hash=digest, pack_hash=self.pack.pack_key, prompt_rev=pkey,
                                              verify_rev=review_verify.VERIFY_REV, now=now)
            if started is None:
                if not review_cells._holds(self.store, self.target_key, self.agent, self.lease):
                    raise _Stop("lease", release=False)
                continue
            row = review_cells.begin_attempt(self.store, self.target_key, unit_id, self.agent, lease_owner=self.lease,
                                             now=now)
            if row is None:
                raise _Stop("lease", release=False)
            cells.append(_Cell(row=dict(row), payload=payload,
                               refs=frozenset(units.unit_refs(self.store, self.target_key, unit_id))))
        return cells

    # -- 호출 하나 ----------------------------------------------------------------------------
    def _request_hash(self, cell: _Cell | None, body: Mapping[str, Any], seq: int = 0) -> str:
        """같은 시도의 같은 차례(`seq` — 재질의 순번)에서 낸 같은 본문의 열쇠. 차례가 들어가야 앞 답과 바이트로 같은 재질의(1장
        묶음의 빠진 카드 · 단독 재질의)가 캐시에서 그 앞 답(카드가 빠진 답)을 받지 않고 엔진으로 간다. 차례는 세션 차례가 정하므로
        재기동 뒤의 세션도 같은 열쇠를 짓는다."""
        assert self.pack is not None
        scope = (f"cell|{cell.row.get('input_hash')}|{cell.attempt}|{seq}" if cell is not None
                 else f"head|{self.pack.pack_key}|{self.lim.get('limits_rev')}|{prompt_key(self.lim)}")
        return sha256_hex(scope + "|" + canonical_json(body))

    def _cached(self, cell: _Cell | None, request_hash: str) -> dict | None:
        row = self.store.query_one(
            "SELECT result_gz FROM rr_review_calls WHERE target_key = ? AND agent_key = ? AND unit_id IS ? AND request_hash = ?"
            " AND state = 'ok' AND result_gz IS NOT NULL ORDER BY started_at DESC LIMIT 1",
            (self.target_key, self.agent, cell.unit_id if cell is not None else None, request_hash))
        if row is None:
            return None
        try:
            value = json.loads(gzip.decompress(row["result_gz"]).decode("utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _within_cap(self, cell: _Cell) -> bool:
        assert self.pack is not None
        decks = len(self.plan.get("verdict_decks") or ())
        cap = call_cap(decks, len(self.pack.checkable))
        row = self.store.query_one("SELECT tries FROM rr_review_cells WHERE target_key = ? AND unit_id = ? AND agent_key = ?",
                                   (self.target_key, cell.unit_id, self.agent))
        if row is not None and int(row["tries"] or 0) < cap:
            return True
        out = review_cells.settle_cell(self.store, self.target_key, cell.unit_id, self.agent, lease_owner=self.lease,
                                       fail_code="call_cap", now=self.now())
        if not out["written"]:
            raise _Stop("lease", release=False)
        cell.alive = False
        log.warning("검토 잡 %s: %s×%s 셀이 호출 수 상한 %s 에 닿아 failed(call_cap)다", self.job_id, cell.unit_id, self.agent, cap)
        return False

    def _ask(self, cell: _Cell | None, kind: str, variant: str | None, aliases: Sequence[str], body: Mapping[str, Any], *,
             deck_id: str | None = None, page_no: int | None = None, seq: int = 0) -> _Answer | None:
        """호출 하나 — 답(새로 받은 것 또는 같은 시도에서 이미 받은 것), 또는 None(그 셀이 내용 탓 실패·호출 수 상한으로 끝났다 —
        훑기는 그 쪽이 실패했다). 기다림은 같은 자리에서 다시 내고(아무것도 세지 않는다), 인프라·잡 보류·취소·묶음은 `_Stop` 이다."""
        assert self.pack is not None
        self.focus = cell
        request_hash = self._request_hash(cell, body, seq)
        cached = self._cached(cell, request_hash)
        if cached is not None:
            return _Answer(result=cached, call=None, cached=True)
        if cell is not None and not self._within_cap(cell):
            return None
        timeouts = int(self.store.query_one("SELECT COUNT(*) AS n FROM rr_review_calls WHERE request_hash = ?"
                                            " AND error_code = 'review_timeout'", (request_hash,))["n"] or 0)
        unit_id = cell.unit_id if cell is not None else None
        while True:
            self._gate()
            started = self.now()
            base = {"call_id": new_uuid(), "kind": kind, "variant": variant, "deck_id": deck_id, "page_no": page_no,
                    "seq": seq, "unit_id": unit_id, "run_id": self.job_id, "cards_json": json.dumps(list(aliases)),
                    "request_hash": request_hash, "credential_kind": self.cred_kind, "norm_rev": self.pack.norm_rev,
                    "limits_rev": self.lim.get("limits_rev"), "prompt_rev": self._expect(kind)["prompt_rev"],
                    "started_at": started}
            if not review_cells.begin_call(self.store, self.target_key, self.agent, lease_owner=self.lease,
                                           call=base, now=started):
                raise _Stop("lease", release=False)
            self.call = base
            self.progress.worker(self.wkey, unit_id=unit_id, call_kind=kind, variant=variant, deck_id=deck_id,
                                 started_at=started, last_frame_at=None, last_event_at=None, last_step="")
            tick = time.monotonic()
            try:
                result = self.engine.run(body, email=self.email, should_stop=self.should_stop,
                                         on_progress=lambda frame: self.progress.frame(self.wkey, frame))
            except _ENGINE_ERRORS as exc:
                outcome = engine_client.review_outcome(exc, timeouts_before=timeouts)
                self._failed(cell, base, exc, outcome, int((time.monotonic() - tick) * 1000))
                self.call = None
                if outcome.klass == review_ops.WAIT:
                    self._sleep(outcome.retry_after_s, reason=outcome.code)
                    continue
                return self._after_failure(cell, exc, outcome)
            return _Answer(result=dict(result), call={**base, "duration_ms": int((time.monotonic() - tick) * 1000)},
                           cached=False)

    def _failed(self, cell: _Cell | None, base: Mapping[str, Any], exc: BaseException, outcome: review_ops.Outcome,
                duration_ms: int) -> None:
        call = {**base, "state": _CALL_STATE.get(outcome.klass, "aborted"), "outcome_class": outcome.klass,
                "error_code": outcome.code, "error": str(exc), "duration_ms": duration_ms,
                "error_infra": (None if getattr(exc, "infra", None) is None else int(bool(exc.infra))),
                "error_retryable": (None if getattr(exc, "retryable", None) is None else int(bool(exc.retryable)))}
        written = review_cells.write_call_result(self.store, self.target_key, self.agent, lease_owner=self.lease, call=call,
                                                 outcome=outcome, max_charged=self.max_charged, now=self.now())
        if not written["written"]:
            raise _Stop("lease", release=False)
        if outcome.klass != review_ops.WAIT:
            self.loop.after_call(self.job_id, outcome.klass)

    def _after_failure(self, cell: _Cell | None, exc: BaseException, outcome: review_ops.Outcome) -> None:
        if outcome.klass == review_ops.CONTENT:
            if cell is not None:
                cell.alive = False          # 셀은 write_call_result 가 pending(차감) 또는 failed 로 옮겼다
            return None
        if outcome.klass == review_ops.INFRA:
            # 셀 호출이면 그 셀이 백오프를 쥐었다. 머리 몫(훑기) 호출이면 머리가 백오프한다.
            raise _Stop(f"infra:{outcome.code}", not_before=None if cell is not None else self.now() + review_ops.backoff_s(
                1, salt=f"{self.target_key}|{self.agent}|sweep"))
        if outcome.klass == review_ops.JOB:
            if outcome.code == "rev_mismatch" and self._limits_moved():
                raise _Stop("limits_rev_changed")       # 판이 바뀌었다 — 놓고 다음 세션이 계획을 다시 받는다(보류하지 않는다)
            what = f"카드 대조 호출({self.agent})"
            self._hold(outcome.hold_code or "contract", credential_message(what, exc) if outcome.hold_code == "credential"
                       else f"{what}: {exc}")
            raise _Stop(outcome.hold_code or "contract")
        if outcome.klass == review_ops.PACK:
            review_cells.record_pack(self.store, self.target_key, self.agent, lease_owner=self.lease, status="error",
                                     error=outcome.code, not_before=self.now() + review_ops.pack_retry_s(1), now=self.now())
            raise _Stop(f"pack:{outcome.code}")
        raise _Stop("cancelled")

    def _limits_moved(self) -> bool:
        try:
            fresh = self.loop.limits_for(self.email, fresh=True)
        except _ENGINE_ERRORS:
            return False
        return fresh.get("limits_rev") != self.lim.get("limits_rev")

    def _note(self, cell: _Cell | None, kind: str, variant: str | None, aliases: Sequence[str], result: Mapping[str, Any],
              accepted: Mapping[str, Any]) -> None:
        if cell is None:
            return
        quality = result.get("quality") if isinstance(result.get("quality"), Mapping) else {}
        meta = result.get("meta") if isinstance(result.get("meta"), Mapping) else {}
        cell.log.append({"kind": kind, "variant": variant, "aliases": list(aliases), "truncated": quality.get("truncated"),
                         "soft_over": bool(meta.get("soft_over")), "stamp": bool(quality.get("stamp")),
                         "expected": quality.get("expected"), "missing": len(accepted.get("missing") or ())})
        cell.inj.extend((accepted.get("extras") or {}).get("inj") or ())

    def _commit(self, cell: _Cell | None, answer: _Answer, accepted: Mapping[str, Any], *,
                verdicts: Sequence[Mapping[str, Any]] = (), cell_sets: Mapping[str, Any] | None = None,
                head_sets: Mapping[str, Any] | None = None, app: Mapping[str, Any] | None = None) -> None:
        """새로 받은 답을 한 트랜잭션으로 적는다(이미 받은 답은 그 세션이 적었다). 호출 원장 행에는 result 프레임 전체(gzip)와 엔진
        품질·앱 회계(`quality_json.app` — 버린 행의 까닭·앱이 센 빠진 카드·인용 대조 불일치)를 싣는다."""
        if answer.cached:
            return
        assert answer.call is not None
        result = answer.result
        quality = result.get("quality") if isinstance(result.get("quality"), Mapping) else {}
        meta = result.get("meta") if isinstance(result.get("meta"), Mapping) else {}
        usage = meta.get("usage") if isinstance(meta.get("usage"), Mapping) else {}
        truncated = quality.get("truncated")
        llm_ms = meta.get("llm_ms")
        disagree = sum(int(r.get("check_disagree") or 0) for r in accepted.get("rows") or () if isinstance(r, Mapping))
        payload = canonical_json(result)
        call = {**answer.call, "state": "ok", "outcome_class": review_ops.OK,
                "input_sha": meta.get("input_sha"), "prompt_chars": meta.get("prompt_chars"),
                "tokens_in": usage.get("tokens_in"), "tokens_out": usage.get("tokens_out"),
                "output_truncated": 1 if truncated is True else 0 if truncated is False else None,
                "finish_reason": meta.get("finish_reason"), "soft_over": int(bool(meta.get("soft_over"))),
                "attempts": quality.get("attempts") if quality.get("attempts") is not None else usage.get("llm_calls"),
                "queued_ms": meta.get("queued_ms"),
                "llm_ms": sum(int(x) for x in llm_ms if isinstance(x, (int, float))) if isinstance(llm_ms, list) else None,
                "rows_expected": quality.get("expected"), "rows_missing": len(accepted.get("missing") or ()),
                "bad_lines": quality.get("bad_lines"), "stamp": int(bool(quality.get("stamp"))),
                "dropped_over_cap": quality.get("dropped_over_cap"), "bg_dropped": meta.get("bg_dropped"),
                "model": meta.get("model"), "prompt_rev": meta.get("prompt_rev") or answer.call.get("prompt_rev"),
                "norm_rev": meta.get("norm_rev") or answer.call.get("norm_rev"),
                "limits_rev": meta.get("limits_rev") or answer.call.get("limits_rev"),
                "result_gz": gzip.compress(payload.encode("utf-8"), mtime=0),
                "result_sha256": sha256_hex(payload),
                "quality_json": canonical_json({"engine": dict(quality), "app": {
                    "dropped": sorted({str(d.get("reason")) for d in accepted.get("dropped") or ()}),
                    "dropped_n": len(accepted.get("dropped") or ()), "missing": list(accepted.get("missing") or ()),
                    "check_disagree": disagree, **dict(app or {})}})}
        written = review_cells.write_call_result(self.store, self.target_key, self.agent, lease_owner=self.lease, call=call,
                                                 verdicts=verdicts, cell=cell_sets, head=head_sets, outcome=None,
                                                 max_charged=self.max_charged, now=self.now())
        if not written["written"]:
            raise _Stop("lease", release=False)
        self.call = None
        self.loop.after_call(self.job_id, review_ops.OK, check_disagree=disagree)

    # -- 훑기 --------------------------------------------------------------------------------
    def _sweep(self) -> None:
        """훑기 — 묶음 × 목록 쪽. 답은 셀 분류에 쓰지 않는다(route='review' — M2 는 늘 대조로 간다). 내용 탓으로 실패한 쪽이 있으면
        sweep_state='failed' 로 두고 나아간다. 카드 밖 호출이 훑기 k 에 걸린 배경 카드를 먼저 싣는다."""
        assert self.pack is not None
        self.focus = None
        head = self._head_row()
        key = {"pack_key": self.pack.pack_key, "limits_rev": self.lim.get("limits_rev")}
        done = _json(head.get("sweep_json"), {})
        if head.get("sweep_state") in ("done", "failed") and done.get("key") == key:
            self.sweep = done
            return
        manifest = {m["unit_id"]: m for m in units.manifest_items(self.store, self.target_key)}
        calls: list[dict] = []
        failed = 0
        for deck in self.plan.get("sweep_decks") or ():
            aliases = list(deck.get("aliases") or ())
            for page_no, page in enumerate(self.plan.get("manifest_pages") or ()):
                items = [manifest[u] for u in page if u in manifest]
                body = engine_client.run_body("sweep", target_key=self.target_key, pack=self.pack, cards=aliases,
                                              manifest=items, expect=self._expect("sweep"), cfg=self.settings)
                answer = self._ask(None, "sweep", None, aliases, body, deck_id=deck.get("deck_id"), page_no=page_no)
                if answer is None:
                    failed += 1
                    continue
                accepted = review_verify.accept_rows(answer.result, kind="sweep", sent_aliases=aliases, pack=self.pack,
                                                     page_units=[i["unit_id"] for i in items])
                self._commit(None, answer, accepted)
                calls.append({"sent_aliases": aliases, "page_units": [i["unit_id"] for i in items],
                              "result": answer.result})
        accounting = review_verify.sweep_accounting(calls) if calls else {"units": {}, "units_error": [],
                                                                          "cards_unseen": [], "handoffs": [], "dropped": []}
        self.sweep = {"key": key, "failed_pages": failed, **accounting}
        if not review_cells.write_head(self.store, self.target_key, self.agent, lease_owner=self.lease, now=self.now(),
                                       sets={"sweep_state": "failed" if failed else "done",
                                             "sweep_json": canonical_json(self.sweep)}):
            raise _Stop("lease", release=False)

    # -- 카드 대조 -----------------------------------------------------------------------------
    def _others(self, aliases: Sequence[str]) -> list[str]:
        assert self.pack is not None
        sent = set(aliases)
        return [a for a in self.pack.order if a not in sent]

    def _verdict_body(self, cell: _Cell, aliases: Sequence[str], variant: str) -> dict:
        self.focus = cell
        return engine_client.run_body("verdict", variant=variant, target_key=self.target_key, pack=self.pack, cards=aliases,
                                      digest=self._others(aliases), unit=cell.payload, expect=self._expect("verdict"),
                                      cfg=self.settings)

    def _rows(self, cell: _Cell) -> list[dict]:
        return [dict(r) for r in self.store.query(
            "SELECT record_id, variant, alias, applies, judgement, why, is_effective FROM rr_card_verdicts"
            " WHERE target_key = ? AND unit_id = ? AND agent_key = ?", (self.target_key, cell.unit_id, self.agent))]

    def _judged(self, cell: _Cell, variant: str) -> set[str]:
        return {r["alias"] for r in self._rows(cell) if r["variant"] == variant}

    def _cell_basis(self) -> str:
        assert self.pack is not None
        return _BASIS_OF_PACK[self.pack.card_basis]

    def _verdict(self, cell: _Cell, aliases: Sequence[str], variant: str, body: Mapping[str, Any], *, deck_id: str | None,
                 seq: int = 0) -> bool:
        """판정 호출 하나를 내고 받은 행을 앱의 회계(`accept_rows` — 실은 카드 밖 별칭·지어낸 인용·남의 단위 참조를 가른다)를 지나
        적는다. 답을 받았으면 True."""
        assert self.pack is not None
        answer = self._ask(cell, "verdict", variant, aliases, body, deck_id=deck_id, seq=seq)
        if answer is None:
            return False
        accepted = review_verify.accept_rows(answer.result, kind="verdict", sent_aliases=aliases, pack=self.pack,
                                             unit_refs=cell.refs, variant=variant)
        self._note(cell, "verdict", variant, aliases, answer.result, accepted)
        meta = answer.result.get("meta") if isinstance(answer.result.get("meta"), Mapping) else {}
        self._commit(cell, answer, accepted, verdicts=[{**r, "deck_id": deck_id} for r in accepted["rows"]],
                     cell_sets={"basis": self._cell_basis(), "cards_expected": len(self.pack.checkable),
                                "credential_kind": self.cred_kind, "model": meta.get("model")})
        return True

    def _deck_of(self) -> dict[str, str]:
        return {a: str(d.get("deck_id")) for d in self.plan.get("verdict_decks") or () for a in d.get("aliases") or ()}

    def _solo_set(self, cell: _Cell) -> list[str]:
        """단독 재질의할 카드(팩 순서) — 묶음째로는 창을 넘는 짝(pair_over)·같은 본문이라 rev 를 건너뛴 1장 묶음(X1-20)·fwd 와
        rev 가 갈린 카드·fwd 나 rev 를 끝내 못 받은 카드·실효가 걸림(FAIL·WARNING)인 카드. fwd·rev 행만으로 정한다(단독 행이 섞이면
        재기동 뒤의 세션이 다른 집합을 고른다)."""
        assert self.pack is not None
        rows = [r for r in self._rows(cell) if r["variant"] in ("fwd", "rev")]
        effective = review_verify.effective_rows(rows) if rows else {}
        decks = self._deck_of()
        out: list[str] = []
        for alias in self.pack.checkable:
            record_id = str(self.pack.cards[alias]["record_id"])
            have = {r["variant"] for r in rows if r["record_id"] == record_id}
            eff = effective.get(record_id) or {}
            if (alias in cell.forced_solo or "fwd" not in have
                    or (decks.get(alias) in cell.dual_decks and "rev" not in have)
                    or eff.get("agree") == 0 or eff.get("judgement") in review_verify.FLAGGED):
                out.append(alias)
        return out

    def _solos(self, cell: _Cell) -> None:
        self.focus = cell
        decks = self._deck_of()
        for alias in self._solo_set(cell):
            for seq in range(SOLO_REASKS + 1):
                if not cell.alive:
                    return
                if not self._verdict(cell, [alias], "solo", self._verdict_body(cell, [alias], "solo"),
                                     deck_id=decks.get(alias), seq=seq):
                    return
                if alias in self._judged(cell, "solo"):
                    break
            else:
                cell.samples_done = False

    # -- 카드 밖 -------------------------------------------------------------------------------
    def _known(self, cell: _Cell) -> list[dict]:
        rows = [r for r in self._rows(cell) if r["is_effective"]]
        order = {a: i for i, a in enumerate(self.pack.order if self.pack else ())}
        rows.sort(key=lambda r: (_JUDGEMENT_FIRST.get(str(r["judgement"]), 2), order.get(r["alias"], 1 << 20)))
        return [{"alias": r["alias"], "judgement": r["judgement"], "why": r["why"]} for r in rows]

    def _known_dropped(self, known: Sequence[Mapping[str, Any]]) -> int:
        """엔진이 known 칸을 그 몫(`offcard.known_max` 자)으로 자를 때 빠질 줄 수 — 엔진 `_cap_lines` 와 같은 셈(넘친 수를 원장에 적는다)."""
        cap = int(((self.lim.get("offcard") or {}).get("known_max")) or 0)
        if cap <= 0:
            return 0
        used = 0
        for i, item in enumerate(known):
            line = f"{_s(item.get('alias'))} {_s(item.get('judgement'))} — «{_s(item.get('why'))}»\n"
            if used + len(line) > cap - 40:
                return len(known) - i
            used += len(line)
        return 0

    def _truncation(self, cell: _Cell) -> int | None:
        """셀의 절단 — 절단된 호출이 실은 카드가 끝내 실효 판정을 못 받았거나 마지막 카드 밖 답이 잘렸으면 1, 절단을 모르는(NULL)
        호출이 있으면 NULL(모름 — 0 으로 치지 않는다, X1-22), 아니면 0. 잘린 호출의 빠진 카드를 재질의로 다 받았으면 잃은 것이 없다
        (호출 원장의 output_truncated 는 그대로 남아 품질 수치가 센다)."""
        judged = {r["alias"] for r in self._rows(cell) if r["is_effective"]}
        lost = any(e["truncated"] is True and e["kind"] == "verdict" and any(a not in judged for a in e["aliases"])
                   for e in cell.log)
        last_off = next((e for e in reversed(cell.log) if e["kind"] == "offcard"), None)
        if lost or (last_off is not None and last_off["truncated"] is True):
            return 1
        if any(e["truncated"] is None for e in cell.log):
            return None
        return 0

    def _offcard(self, cell: _Cell) -> None:
        """카드 밖 호출 — 셀마다 1번. 배경 카드는 전부 본문으로 싣는다(훑기 k 에 걸린 것 먼저, 나머지 팩 순서 — P-03 · X1-11),
        digest 는 나머지 카드의 제목, known 은 그 셀의 실효 판정(걸림 먼저). 카드 밖 줄 수가 findings_max 에 닿으면 받은 제목을 known
        에 더해 '이것 말고 더' 를 최대 MORE_REASKS 번 다시 묻는다(X1-16). 카드 0장 전문가는 역할만으로 부른다(role_only)."""
        assert self.pack is not None
        self.focus = cell
        hits = set(((self.sweep.get("units") or {}).get(cell.unit_id) or {}).get("k") or ())
        background = list(self.pack.background)
        cards = [a for a in background if a in hits] + [a for a in background if a not in hits]
        digest = self._others(cards)
        known = self._known(cell)
        cap = int(((self.lim.get("offcard") or {}).get("findings_max")) or 0)
        findings: list[dict] = []
        extras: dict[str, Any] = {"need": [], "seen": [], "handoffs": [], "none": False, "more": None}
        capped = 0
        seq = 0
        asked = list(known)
        while True:
            body = engine_client.run_body("offcard", target_key=self.target_key, pack=self.pack, cards=cards, digest=digest,
                                          unit=cell.payload, known=asked, expect=self._expect("offcard"), cfg=self.settings)
            answer = self._ask(cell, "offcard", None, cards, body, seq=seq)
            if answer is None:
                return
            accepted = review_verify.accept_rows(answer.result, kind="offcard", sent_aliases=cards, pack=self.pack,
                                                 unit_refs=cell.refs)
            self._note(cell, "offcard", None, cards, answer.result, accepted)
            found = list(accepted["rows"])
            findings.extend(found)
            got = accepted["extras"]
            extras["need"].extend(got.get("need") or ())
            extras["seen"] = sorted(set(extras["seen"]) | set(got.get("seen") or ()))
            extras["handoffs"].extend(got.get("handoffs") or ())
            extras["none"] = bool(extras["none"] or got.get("none"))
            extras["more"] = got.get("more")
            hit = bool(cap) and len(found) >= cap
            capped += int(hit)
            last = not hit or seq >= MORE_REASKS
            meta = answer.result.get("meta") if isinstance(answer.result.get("meta"), Mapping) else {}
            bg_dropped = int(meta.get("bg_dropped") or 0)
            sets: dict[str, Any] = {
                "basis": self._cell_basis(), "credential_kind": self.cred_kind, "model": meta.get("model"),
                "n_offcard": len(findings), "offcard_capped": capped, "offcard_state": "done" if last else "todo",
                "bg_full_n": max(len(cards) - bg_dropped, 0), "bg_title_only_n": bg_dropped,
                "extras_json": canonical_json({"inj": cell.inj, "offcard": {**extras, "findings": findings,
                                                                            "known_dropped": self._known_dropped(asked)}}),
                "mechs_json": canonical_json(sorted(set(extras["seen"]) | {str(f["mech"]) for f in findings
                                                                           if f.get("mech") and f.get("mech") != "free"})),
                "handoffs_json": canonical_json(extras["handoffs"]),
            }
            if self.pack.card_basis != cardpack.CARD_BASIS_CARDS:
                sets.update({"cards_expected": 0, "cards_judged": 0})
            if last:
                sets.update({"truncated": self._truncation(cell),
                             "soft_over": int(any(e["soft_over"] for e in cell.log)),
                             "stamp": int(any(e["stamp"] for e in cell.log)),
                             "rows_expected": sum(int(e["expected"] or 0) for e in cell.log),
                             "rows_missing": sum(int(e["missing"] or 0) for e in cell.log)})
            self._commit(cell, answer, accepted, cell_sets=sets,
                         app={"known_n": len(asked), "known_dropped": self._known_dropped(asked), "more_seq": seq})
            if last:
                return
            seq += 1
            asked = known + [{"alias": f"F{i:02d}", "judgement": None, "why": str(f.get("title") or "")}
                             for i, f in enumerate(findings, 1)]

    # -- 정산 · 마감 ------------------------------------------------------------------------------
    def _settle(self, cell: _Cell) -> None:
        self.focus = cell
        out = review_cells.settle_cell(self.store, self.target_key, cell.unit_id, self.agent, lease_owner=self.lease,
                                       samples_done=cell.samples_done, more_calls=False, max_charged=self.max_charged,
                                       now=self.now())
        if not out["written"]:
            raise _Stop("lease", release=False)
        cell.alive = False
        if out["state"] != "reviewed":
            log.info("검토 잡 %s: %s×%s 셀 정산 미달(%s) → %s", self.job_id, cell.unit_id, self.agent,
                     ", ".join(out.get("missing") or [out.get("code") or ""]), out["state"])

    def _close(self) -> None:
        """세션 끝 — 그 전문가의 범위 안 열린 셀이 0 이면 마감(`finalize_expert`), 아니면 놓는다(백오프 중인 셀·다음 시도의 셀은
        다음 틱이 다시 집는다)."""
        self.focus = None
        open_n = self.store.query_one(
            "SELECT COUNT(*) AS n FROM rr_review_cells WHERE target_key = ? AND agent_key = ? AND run_id = ?"
            " AND state IN ('pending', 'running')", (self.target_key, self.agent, self.job_id))["n"]
        if int(open_n or 0) == 0:
            if finalize_expert(self.store, self.job, self.head, lease_owner=self.lease, now=self.now()) is None:
                raise _Stop("lease", release=False)
            return
        raise _Stop("cells_left")

    def internal_failure(self, exc: BaseException) -> None:
        """세션 안의 예기치 않은 예외(앱 결함·엔진 칸 모양 어긋남 따위 — 엔진 오류 부류가 아닌 것) 뒤(반대 검토 R3A-2).

        원장에 running 으로 남은 호출 행을 aborted('internal_error')로 닫고, 그 셀(다루던 셀이 없으면 머리 몫)의 연달은 결함 수를
        센다(`review_cells.note_internal`). 셀은 INTERNAL_STRIKES 번째마다 내용 탓(internal_error)으로 차감돼 한도에서
        failed('internal_error') 이고, 머리 몫(계획·훑기·마감 따위)은 INTERNAL_STRIKES 번째에 잡을 contract 로 멈추고 예외 글을
        싣는다 — 같은 결함을 60초마다 한도 없이 되풀이하며 엔진을 다시 부르지 않게. 닫은 호출은 내용 탓으로 차단기 창에 든다."""
        text = f"{type(exc).__name__}: {exc}"[:500]
        cell = self.focus
        out = review_cells.note_internal(self.store, self.target_key, self.agent, lease_owner=self.lease,
                                         unit_id=cell.unit_id if cell is not None else None,
                                         call_id=(self.call or {}).get("call_id"), error=text,
                                         strikes_max=INTERNAL_STRIKES, max_charged=self.max_charged, now=self.now())
        self.call = None
        if not out["written"]:
            return
        log.warning("검토 잡 %s: %s 의 예기치 않은 결함 %s번째(%s) — %s", self.job_id, self.agent, out["strikes"], out["key"],
                    text)
        if out["closed_call"]:
            self.loop.after_call(self.job_id, review_ops.CONTENT)
        if out["key"] == "head" and out["struck"]:
            self._hold("contract", f"검토 세션({self.agent})의 예기치 않은 결함이 {INTERNAL_STRIKES}번 잇달았다 — {text}. 앱"
                       " 로그(hwax_risk.review)를 보고 고친 뒤 재개한다")

    def finalize(self) -> None:
        """마감만 — 범위 안 셀이 다 닫혔는데 마감이 끝나지 않은 머리(마감 도중 결함·재기동)를 다시 마감한다. 얼린 묶음이 이 박스에
        없으면 다시 받는다(M2.md 5절 #22)."""
        self.pack = self._load_pack()
        self._close()

    def run(self) -> None:
        """전문가 세션 — 묶음 → 창 → 계획 → 셀 시작 → 훑기 → fwd(묶음 먼저 · 단위 나중) → 빠진 카드 재질의 → rev → 단독 → 카드 밖 →
        정산 → 마감 또는 놓기. 호출과 호출 사이마다 멈춤을 묻는다(`_gate`)."""
        self.pack = self._load_pack()
        self.lim = dict(self._unary(lambda: self.loop.limits_for(self.email), "창 조회"))
        self.plan = self._plan()
        cells = self._start_cells()
        if not cells:
            raise _Stop("no_cells")
        if self.pack.card_basis in (cardpack.CARD_BASIS_CARDS, cardpack.CARD_BASIS_BACKGROUND):
            self._sweep()
        decks = list(self.plan.get("verdict_decks") or ()) if self.pack.card_basis == cardpack.CARD_BASIS_CARDS else []
        pair_over = {(str(p.get("deck_id")), str(p.get("unit_id"))) for p in self.plan.get("pair_over") or ()}

        def live() -> list[_Cell]:
            return [c for c in cells if c.alive]

        for deck in decks:
            deck_id, aliases = str(deck.get("deck_id")), list(deck.get("aliases") or ())
            for cell in live():
                if (deck_id, cell.unit_id) in pair_over:
                    cell.forced_solo.extend(a for a in aliases if a not in cell.forced_solo)
                    continue
                body = self._verdict_body(cell, aliases, "fwd")
                cell.fwd_bodies[deck_id] = body
                self._verdict(cell, aliases, "fwd", body, deck_id=deck_id)
        for cell in live():
            for deck in decks:
                deck_id, aliases = str(deck.get("deck_id")), list(deck.get("aliases") or ())
                if (deck_id, cell.unit_id) in pair_over:
                    continue
                for seq in range(1, MISSING_REASKS + 1):
                    if not cell.alive:
                        break
                    have = self._judged(cell, "fwd")
                    missing = [a for a in aliases if a not in have]
                    if not missing:
                        break
                    self._verdict(cell, missing, "fwd", self._verdict_body(cell, missing, "fwd"), deck_id=deck_id, seq=seq)
        for deck in decks:
            deck_id, aliases = str(deck.get("deck_id")), list(deck.get("aliases") or ())
            for cell in live():
                if (deck_id, cell.unit_id) in pair_over or deck_id not in cell.fwd_bodies:
                    continue
                self.focus = cell
                dual = review_verify.dual_plan(cell.fwd_bodies[deck_id], dual_rate=self.dual_rate,
                                               sample_key=(self.target_key, cell.unit_id, self.agent, deck_id), salt=self.salt)
                if dual["rev"] is None:
                    if dual["reason"] == "same_body":
                        cell.forced_solo.extend(a for a in dual["solo"] if a not in cell.forced_solo)
                    continue
                cell.dual_decks.add(deck_id)
                self._verdict(cell, aliases, "rev", dual["rev"], deck_id=deck_id)
        if self.pack.card_basis == cardpack.CARD_BASIS_CARDS:
            for cell in live():
                self._solos(cell)
        for cell in live():
            self._offcard(cell)
        for cell in live():
            self._settle(cell)
        self._close()


# ---------------------------------------------------------------- 루프
@dataclass
class _Worker:
    thread: threading.Thread
    job_id: str
    agent_key: str
    purpose: str


class ReviewLoop:
    """검토 잡의 루프 — 러너(`runner.RiskRunner`)의 review_loop 스레드가 2초마다 `tick()` 을 부른다.

    틱은 ① 시계로 재개하는 코드 보류(사람의 것이 아닌)를 풀어 줄에 세우고(반쯤 연 재개 — 성공 하나까지 워커 하나), 창 출처를
    기다리던 ctx_unknown 은 창이 server·env 로 돌아오면 푼다. ② cancelling 이고 도는 전문가가 없는 잡을 cancelled 로, queued 를 running
    으로 옮긴다. ③ 창(limits, 60초 캐시)을 본다 — fallback 이면 새 호출을 내지 않고 기다리다 600초면 ctx_unknown, 창이 모자라면
    ctx_too_small. ④ 잡마다 단계(pack → review)를 정하고 범위 안 열린 셀이 0 이면 completed(실패 셀 수를 error 에). ⑤ 빈 자리 =
    min(HWAXRISK_REVIEW_CONCURRENCY, 서버 관문 limit(/health, 30초 캐시)) − 도는 워커만큼 워커를 띄운다(잡을 돌아가며 — P-09).
    이 박스의 검토 스위치(HWAXRISK_REVIEW_ENABLED)가 꺼져 있으면 ②까지만 하고 새 전문가·셀을 집지 않는다 — 잡은 running 그대로,
    진행판은 waiting{reason:'review_disabled'}, 도는 호출은 끝까지 가고 그 세션은 다음 호출 앞에서 놓는다.

    시험은 `clock`(정수 초)·`pause`(초 → 멈췄으면 참)·`poll_s` 를 주입한다. 운영은 now_epoch · stop.wait · 5초다.
    """

    def __init__(self, store: Any, settings: Any, engine: Any, *, stop: threading.Event | None = None,
                 clock: Callable[[], int] | None = None, pause: Callable[[float], bool] | None = None,
                 boot_id: str | None = None, poll_s: float = STOP_POLL_S, probe_join_s: float = PROBE_JOIN_S) -> None:
        self.store = store
        self.settings = settings
        self.engine = engine
        self.stop = stop if stop is not None else threading.Event()
        self.clock: Callable[[], int] = clock or now_epoch
        self._pause = pause
        self.boot_id = boot_id or new_uuid()
        self.poll_s = poll_s
        self.probe_join_s = probe_join_s
        self._lock = threading.RLock()
        self._hold_lock = threading.Lock()
        self._workers: list[_Worker] = []
        self._progress: dict[str, JobProgress] = {}
        self._served: dict[str, int] = {}
        self._served_n = 0
        self._limits: dict[str, _Probe] = {}            # 자격(이메일)마다 — 다른 사람의 자격으로 물은 답을 쓰지 않는다(R3A-3)
        self._health = _Probe()
        self._fallback_since: dict[str, int] = {}

    # -- 바탕 ------------------------------------------------------------------------------
    def ready(self) -> bool:
        return self.store is not None and self.settings is not None and self.engine is not None

    def pause(self, seconds: float) -> bool:
        """기다림 한 조각 — 러너가 멈추면 참이다."""
        if self._pause is not None:
            return bool(self._pause(seconds))
        return self.stop.wait(seconds)

    def progress(self, job_id: str) -> JobProgress:
        with self._lock:
            entry = self._progress.get(job_id)
            if entry is None:
                entry = JobProgress(self.store, job_id, clock=self.clock, server=self.server)
                self._progress[job_id] = entry
            return entry

    def server(self) -> dict:
        value = self._health.value if isinstance(self._health.value, Mapping) else {}
        block = value.get("card_review") if isinstance(value.get("card_review"), Mapping) else {}
        return {"active": block.get("active"), "limit": block.get("limit")}

    def workers(self, job_id: str | None = None) -> list[_Worker]:
        with self._lock:
            self._workers = [w for w in self._workers if w.thread.is_alive()]
            return [w for w in self._workers if job_id is None or w.job_id == job_id]

    def join(self, timeout: float | None = None) -> None:
        """도는 워커를 기다린다(러너 stop·시험)."""
        for worker in self.workers():
            worker.thread.join(timeout)

    # -- 탐침 ---------------------------------------------------------------------------------
    def _probe(self, probe: _Probe, fn: Callable[[], Any], max_age: int) -> tuple[Any, BaseException | None] | None:
        """`max_age` 초 안에 끝난 답이 있으면 그것을, 없으면 탐침 스레드로 새로 묻고 PROBE_JOIN_S 까지만 기다린다.

        돌려주는 것은 (값, 오류) 또는 None 이다. None 은 새 탐침이 아직 끝나지 않았다는 뜻이고, 부른 쪽은 그것을 '모름 — 기다린다'
        로 읽는다(보류하지 않는다). 새 탐침을 띄우는 순간 지난 답은 버린다 — 늦은 탐침이 지난 오류를 내놓아 사람이 고친 뒤 재개한 잡을
        다시 멈추지 않게(반대 검토 R3A-3). `value` 칸은 남겨 둔다(관문 limit 표시 — `server()`)."""
        now = self.clock()
        with self._lock:
            busy = probe.thread is not None and probe.thread.is_alive()
            if not busy and probe.at is not None and now - probe.at < max_age:
                return probe.value, probe.error
            if busy:
                thread = probe.thread
            else:
                probe.at = None

                def go() -> None:
                    try:
                        value, error = fn(), None
                    except Exception as exc:  # noqa: BLE001 — 탐침의 실패는 값으로 남긴다(틱이 가른다).
                        value, error = None, exc
                    with self._lock:
                        probe.value, probe.error, probe.at = value, error, self.clock()

                thread = threading.Thread(target=go, name="review_probe", daemon=True)
                probe.thread = thread
                thread.start()
        assert thread is not None
        thread.join(self.probe_join_s)
        with self._lock:
            if not thread.is_alive() and probe.at is not None:
                return probe.value, probe.error
        return None

    def _limits_entry(self, email: str) -> _Probe:
        with self._lock:
            return self._limits.setdefault(email, _Probe())

    def _forget_limits(self, email: str) -> None:
        """그 자격의 창 답을 버린다 — 보류를 건 뒤(사람이 고치고 재개하면 새로 묻는다)."""
        with self._lock:
            probe = self._limits.get(email)
            if probe is not None:
                probe.at = None

    def limits_for(self, email: str, *, fresh: bool = False) -> dict:
        """창·판(그 자격으로 물은 성공한 답, 60초 캐시). 워커가 부른다 — 낡았으면 그 자리에서 다시 묻는다(워커는 HTTP 를 붙들어도 된다)."""
        probe = self._limits_entry(email)
        now = self.clock()
        with self._lock:
            if (not fresh and probe.error is None and isinstance(probe.value, Mapping) and probe.at is not None
                    and now - probe.at < LIMITS_CACHE_S):
                return dict(probe.value)
        value = dict(self.engine.limits(email=email))
        with self._lock:
            probe.value, probe.error, probe.at = value, None, self.clock()
        return value

    # -- 보류 · 차단기 ---------------------------------------------------------------------------
    def hold(self, job_id: str, code: str, message: str, *, breaker: bool = False) -> bool:
        """도는(queued·running) 검토 잡을 코드 보류로 멈춘다 — paused + hold_code, 자동 재개 코드면 hold_until = 지금 + 그 n 번째
        간격(review_ops.hold_delay_s). 사람이 멈춘 잡(hold_code='user')·끝난 잡은 건드리지 않는다(사람의 정지가 이긴다 — P-10)."""
        now = self.clock()
        with self._hold_lock:
            row = self.store.query_one("SELECT state, hold_n FROM rr_jobs WHERE id = ?", (job_id,))
            if row is None or row["state"] not in ("queued", "running"):
                return False
            n = int(row["hold_n"] or 0) + 1
            delay = review_ops.hold_delay_s(code, n)
            until = now + delay if delay is not None else None
            changed = self.store.execute(
                "UPDATE rr_jobs SET state = 'paused', pause_reason = NULL, error = ?, hold_code = ?, hold_until = ?,"
                " hold_n = ?, state_by = ?, state_at = ?, updated_at = ? WHERE id = ? AND mode = 'reviews'"
                " AND state IN ('queued', 'running')",
                (message, code, until, n, f"code:{code}", now, now, job_id))
        if not changed:
            return False
        log.warning("검토 잡 %s 보류 %s(%s번째, 재개 %s) — %s", job_id, code, n, until or "사람", message)
        progress = self.progress(job_id)
        if breaker:
            state = progress.breaker()
            progress.set(breaker={"state": "open", "trips": int(state.get("trips") or 0) + 1, "hold_until": until,
                                  "since": now}, count=True)
        else:
            progress.set(count=True)
        return True

    def after_success(self, job_id: str) -> None:
        """반쯤 연 재개(코드 보류에서 시계로 돌아온 잡)의 첫 성공 — 보류 열을 비운다(다음 보류의 간격이 처음부터)."""
        with self._hold_lock:
            changed = self.store.execute(
                "UPDATE rr_jobs SET hold_code = NULL, hold_until = NULL, hold_n = 0, error = NULL, updated_at = ?"
                " WHERE id = ? AND state = 'running' AND hold_code IS NOT NULL AND hold_code <> 'user'",
                (self.clock(), job_id))
        if changed:
            progress = self.progress(job_id)
            progress.set(breaker={**progress.breaker(), "state": "closed", "hold_until": None})

    def after_call(self, job_id: str, klass: str, *, check_disagree: int = 0) -> None:
        """끝난 호출 하나(기다림 제외) 뒤 — 반쯤 연 재개의 성공·실패, 차단기(review_ops.breaker_verdict — 이 잡의 끝난 호출 최근 20건,
        마지막 차단 뒤의 것만), 잡의 인용 대조 불일치 상한(X1-21)."""
        if klass == review_ops.OK:
            self.after_success(job_id)
        row = self.store.query_one("SELECT state, hold_code FROM rr_jobs WHERE id = ?", (job_id,))
        if row is None or row["state"] != "running":
            return
        if klass == review_ops.INFRA and row["hold_code"] == "llm_outage":
            self.hold(job_id, "llm_outage", "반쯤 연 재개의 첫 호출이 다시 인프라 실패다 — LLM·에이전트 서버·포털이 아직 불안정하다."
                      " 더 긴 간격 뒤 다시 재 본다", breaker=True)
            return
        since = self.progress(job_id).breaker().get("since")
        classes = [r["outcome_class"] for r in self.store.query(
            "SELECT outcome_class FROM rr_review_calls WHERE run_id = ? AND state <> 'running' AND started_at > ?"
            " ORDER BY started_at DESC, rowid DESC LIMIT 100", (job_id, int(since) if since is not None else -1))]
        verdict = review_ops.breaker_verdict(classes)
        if verdict is not None:
            counted = [k for k in classes if k and k not in (review_ops.WAIT, review_ops.CANCELLED)][:review_ops.BREAKER_WINDOW]
            infra = sum(1 for k in counted if k == review_ops.INFRA)
            content = sum(1 for k in counted if k == review_ops.CONTENT)
            if verdict == "llm_outage":
                message = (f"최근 끝난 호출 {len(counted)}건 가운데 인프라 실패가 {infra}건이다(LLM·에이전트 서버·포털이 불안정) —"
                           " 정해진 간격 뒤 호출 하나로 다시 재 보고(반쯤 연 재개) 성공하면 이어 돈다")
            else:
                message = (f"최근 끝난 호출 {len(counted)}건 가운데 내용 탓 실패가 {content}건(절반 이상)이다 — 스스로 재개하지 않는다."
                           " 호출 원장(rr_review_calls)의 오류 코드를 보고 고친 뒤 재개한다")
            self.hold(job_id, verdict, message, breaker=True)
            return
        if check_disagree:
            total = self.store.query_one(
                "SELECT COALESCE(SUM(json_extract(quality_json, '$.app.check_disagree')), 0) AS n FROM rr_review_calls"
                " WHERE run_id = ? AND state = 'ok'", (job_id,))["n"]
            if int(total or 0) > review_ops.CHECK_DISAGREE_MAX:
                self.hold(job_id, "contract", f"서버와 앱의 카드 인용 대조가 {int(total)}건 갈렸다(상한 {review_ops.CHECK_DISAGREE_MAX})"
                          " — 인용 정규화(norm_rev)·대조 규칙이 어긋났다. 에이전트 서버와 리스크 앱의 판을 맞춘 뒤 재개한다")

    def check_aidh(self, job_id: str, target_key: str) -> None:
        """범위 안 전문가 전원(열린 셀이 남은 사람)의 카드 묶음이 카드 저장소 쪽 실패(502·503)면 잡 보류 aidh_unreachable."""
        rows = [dict(r) for r in self.store.query(
            "SELECT e.agent_key, e.pack_status, e.pack_error FROM rr_expert_reports e WHERE e.target_key = ? AND e.run_id = ?"
            " AND e.state <> 'blocked' AND EXISTS (SELECT 1 FROM rr_review_cells c WHERE c.target_key = e.target_key"
            " AND c.agent_key = e.agent_key AND c.run_id = e.run_id AND c.state = 'pending')", (target_key, job_id))]
        if rows and all(r["pack_status"] == "error" and r["pack_error"] in AIDH_CODES for r in rows):
            codes = ", ".join(sorted({str(r["pack_error"]) for r in rows}))
            self.hold(job_id, "aidh_unreachable", f"범위 안 전문가 {len(rows)}명 모두 카드 묶음을 받지 못했다({codes}) — AIDataHub·"
                      "게이트웨이의 카드 조회를 본다. 정해진 간격 뒤 스스로 다시 받는다")

    # -- 틱 ----------------------------------------------------------------------------------
    def _jobs(self, states: Sequence[str]) -> list[dict]:
        marks = ",".join("?" * len(states))
        return [_job_of(r) for r in self.store.query(
            "SELECT id, target_key, owner_sub, state, pause_reason, hold_code, hold_until, hold_n, params_json, created_at"
            f" FROM rr_jobs WHERE mode = 'reviews' AND state IN ({marks}) ORDER BY created_at ASC, id ASC", tuple(states))]

    def _limits_probe(self, job: Mapping[str, Any]) -> tuple[Any, BaseException | None] | None:
        """그 잡의 자격(이메일)으로 물은 창 답 — `_probe` 의 (값, 오류) 또는 None(아직 모름)."""
        email = _credential_email(job) or ""
        return self._probe(self._limits_entry(email), lambda: dict(self.engine.limits(email=email)), LIMITS_CACHE_S)

    def _resume(self, job: Mapping[str, Any], *, clear: bool) -> None:
        now = self.clock()
        extra = ", hold_code = NULL, hold_n = 0, error = NULL" if clear else ""
        changed = self.store.execute(
            f"UPDATE rr_jobs SET state = 'queued', state_by = 'code:resume', state_at = ?, updated_at = ?, hold_until = NULL{extra}"
            " WHERE id = ? AND state = 'paused' AND hold_code = ? AND COALESCE(pause_reason, '') <> 'user'",
            (now, now, job["id"], job["hold_code"]))
        if changed:
            log.info("검토 잡 %s: 보류 %s 를 %s", job["id"], job["hold_code"], "풀었다" if clear else "반쯤 열었다(성공 하나까지 워커 하나)")
            progress = self.progress(job["id"])
            progress.set(breaker={**progress.breaker(), "state": "closed" if clear else "half_open", "hold_until": None})

    def _maybe_resume(self, job: Mapping[str, Any], now: int) -> None:
        code = job.get("hold_code")
        rule = review_ops.HOLD_CODES.get(code) if code else None
        if rule is None or not rule.auto or code == "user" or job.get("pause_reason") == "user":
            return
        if rule.resume_on == "ctx_source":
            seen = self._limits_probe(job)
            lim = seen[0] if seen is not None and seen[1] is None and isinstance(seen[0], Mapping) else None
            if lim is not None and lim.get("ctx_source") in KNOWN_CTX_SOURCES and not lim.get("ctx_retrying"):
                self._fallback_since.pop(_credential_email(job) or "", None)
                self._resume(job, clear=True)
            return
        if job.get("hold_until") is not None and int(job["hold_until"]) <= now:
            self._resume(job, clear=False)

    def _waiting(self, jobs: Sequence[Mapping[str, Any]], waiting: Mapping[str, Any] | None) -> None:
        for job in jobs:
            self.progress(job["id"]).set(waiting=dict(waiting) if waiting else None)

    def _window_ok(self, jobs: list[dict], now: int) -> list[dict]:
        """창 확인 — 새 호출을 내도 되는 잡 목록. 잡마다 그 잡의 자격(이메일)으로 물은 답만 본다 — 다른 잡의 오류나 다른 사람의
        이메일로 멈추지 않는다(반대 검토 R3A-3). 새 탐침이 아직 끝나지 않은 자격의 잡은 이번 틱에 새 호출을 내지 않는다(모름 —
        기다린다, 보류 없음). 자격이 없는 잡은 credential 로 멈춘다."""
        groups: dict[str, list[dict]] = {}
        for job in jobs:
            groups.setdefault(_credential_email(job) or "", []).append(job)
        allowed: list[dict] = []
        for email, live in groups.items():
            allowed.extend(self._window_group(email, live, now))
        return allowed

    def _window_group(self, email: str, live: list[dict], now: int) -> list[dict]:
        """같은 자격의 잡들 — 그 자격으로 물은 창 답 하나로 가른다. 보류를 걸면 그 답을 버린다(재개 뒤에는 새로 묻는다)."""
        seen = self._limits_probe(live[0])
        if seen is None:
            return []                                  # 새 답이 아직 없다 — 지난 답을 다시 쓰지 않고 다음 틱에 본다
        value, error = seen
        lim = value if error is None and isinstance(value, Mapping) else None
        if lim is None:
            if error is None:
                return []
            if isinstance(error, PatUnavailable):
                for job in live:
                    self.hold(job["id"], "credential", credential_message("창 조회", error))
                self._forget_limits(email)
                return []
            outcome = (engine_client.review_outcome(error) if isinstance(error, _ENGINE_ERRORS)
                       else review_ops.classify("portal_unreachable"))
            if outcome.klass == review_ops.JOB:
                for job in live:
                    self.hold(job["id"], outcome.hold_code or "contract", f"창 조회: {error}")
                self._forget_limits(email)
            else:
                self._waiting(live, {"reason": outcome.code, "since": now, "retry_at": now + LIMITS_CACHE_S,
                                     "note": str(error)})
            return []
        runnable = lim.get("runnable") if isinstance(lim.get("runnable"), Mapping) else {}
        if lim.get("ctx_too_small") or (runnable and not all(runnable.values())):
            small = lim.get("ctx_too_small") if isinstance(lim.get("ctx_too_small"), Mapping) else {}
            need = small.get("need_ctx_tokens")
            for job in live:
                self.hold(job["id"], "ctx_too_small", f"이 박스의 창 {int(lim.get('ctx_tokens') or 0):,} 토큰"
                          f"({lim.get('ctx_source')})으로는 카드 대조 호출을 짤 수 없다(runnable {dict(runnable)})"
                          + (f" — 창이 {int(need):,} 토큰 이상인 LLM 이 필요하다" if need else "")
                          + f". 다시 쪼개지 않는다(D-22) — {CTX_KNOB}·VLLM_MODEL 을 고친 뒤 재개한다. {small.get('message') or ''}".rstrip())
            self._forget_limits(email)
            return []
        if lim.get("ctx_retrying"):
            self._waiting(live, {"reason": "ctx_retrying", "since": now, "retry_at": now + LIMITS_CACHE_S})
            return []
        if lim.get("ctx_source") not in KNOWN_CTX_SOURCES:
            if email not in self._fallback_since:
                seen_w = [(self.progress(j["id"]).body.get("waiting") or {}) for j in live]
                old = [int(w["since"]) for w in seen_w if w.get("reason") == "ctx_fallback" and w.get("since") is not None]
                self._fallback_since[email] = min(old) if old else now
            since = self._fallback_since[email]
            if now - since >= review_ops.CTX_FALLBACK_HOLD_S:
                for job in live:
                    self.hold(job["id"], "ctx_unknown", f"에이전트 서버가 LLM 창 크기를 모른다(ctx_source={lim.get('ctx_source')},"
                              f" {now - since}초 이어짐) — 에이전트 서버의 창 설정({CTX_KNOB})을 적거나 LLM 서버가 창 크기를 알리게"
                              " 하고 에이전트 서버를 다시 띄운다. 창 출처가 server·env 로 돌아오면 스스로 재개한다")
                self._fallback_since.pop(email, None)
            else:
                self._waiting(live, {"reason": "ctx_fallback", "since": since,
                                     "retry_at": since + review_ops.CTX_FALLBACK_HOLD_S})
            return []
        self._fallback_since.pop(email, None)
        for job in live:
            waiting = self.progress(job["id"]).body.get("waiting") or {}
            if str(waiting.get("reason") or "").startswith("ctx_") or waiting.get("reason") in ("portal_unreachable",
                                                                                                 DISABLED):
                self.progress(job["id"]).set(waiting=None)
        return live

    def _open_cells(self, job: Mapping[str, Any]) -> int:
        return int(self.store.query_one(
            "SELECT COUNT(*) AS n FROM rr_review_cells WHERE target_key = ? AND run_id = ? AND state IN ('pending', 'running')",
            (job["target_key"], job["id"]))["n"] or 0)

    def _running_heads(self, job: Mapping[str, Any]) -> int:
        """그 잡의 도는 전문가 머리·셀 수(R3A-1 — 취소는 이것이 0 이 될 때 cancelled 다)."""
        busy = in_flight(self.store, job_id=str(job["id"]))
        return busy["heads"] + busy["cells"]

    def _finish(self, job: Mapping[str, Any], state: str, error: str | None) -> None:
        """잡을 닫는다 — completed 는 error 를 실패 셀 셈으로 바꿔 적고(없으면 비운다), cancelled 는 취소 전의 error 를 둔다."""
        body = self.progress(job["id"]).finish(state)
        now = self.clock()
        src = "running" if state == "completed" else "cancelling"
        error_sql = "error = ?" if state == "completed" else "error = COALESCE(?, error)"
        changed = self.store.execute(
            f"UPDATE rr_jobs SET state = ?, {error_sql}, progress_json = ?, hold_code = NULL, hold_until = NULL,"
            " state_at = ?, updated_at = ? WHERE id = ? AND state = ?", (state, error, body, now, now, job["id"], src))
        if changed:
            log.info("검토 잡 %s → %s%s", job["id"], state, f" — {error}" if error else "")
            with self._lock:
                self._progress.pop(job["id"], None)
                self._served.pop(job["id"], None)

    def _unfinalized(self, job: Mapping[str, Any]) -> int:
        """범위 안 셀이 다 닫혔는데 마감되지 않은(planned 로 남은) 머리 수 — 마감 도중 결함·재기동 뒤의 것이다. 닫힌 셀이 앞 잡의
        것이어도 센다(R3A-1 — 마감 전에 멈춘 앞 잡의 전문가를 이 잡이 마감한다, `claim_next_expert(purpose='finalize')` 와 같은 조건)."""
        return int(self.store.query_one(
            "SELECT COUNT(*) AS n FROM rr_expert_reports e WHERE e.target_key = ? AND e.run_id = ? AND e.state = 'planned'"
            " AND e.pack_status IN ('ok', 'empty') AND NOT EXISTS (SELECT 1 FROM rr_review_cells c WHERE c.target_key ="
            " e.target_key AND c.agent_key = e.agent_key AND c.run_id = e.run_id AND c.state IN ('pending', 'running'))",
            (job["target_key"], job["id"]))["n"] or 0)

    def _complete_or_phase(self, job: Mapping[str, Any]) -> str | None:
        # 다른 잡이 쥐고 있다가 그 잡이 끝난 뒤 놓은 범위 안 셀을 먼저 거둔다 — 그러지 않으면 아래 셈이 그 셀을 못 보고 잡을 닫는다(R3A-1).
        review_cells.adopt_released(self.store, str(job["id"]), now=self.clock())
        if (self._open_cells(job) == 0 and self._running_heads(job) == 0 and not self.workers(job["id"])
                and self._unfinalized(job) == 0):
            failed = self.store.query(
                "SELECT error_code, COUNT(*) AS n FROM rr_review_cells WHERE target_key = ? AND run_id = ? AND state = 'failed'"
                " GROUP BY error_code ORDER BY error_code", (job["target_key"], job["id"]))
            total = sum(int(r["n"]) for r in failed)
            error = (f"범위 안 셀 {total}개가 실패로 끝났다({', '.join(f'{r['error_code']} {r['n']}' for r in failed)}) — 실패 셀의"
                     " 처분(다시·넘김)은 M3 다" if total else None)
            self._finish(job, "completed", error)
            return None
        needs_pack = self.store.query_one(
            "SELECT 1 FROM rr_expert_reports e WHERE e.target_key = ? AND e.run_id = ? AND e.state IN ('planned', 'running')"
            " AND e.pack_status IN ('todo', 'error') AND EXISTS (SELECT 1 FROM rr_review_cells c WHERE c.target_key ="
            " e.target_key AND c.agent_key = e.agent_key AND c.run_id = e.run_id AND c.state = 'pending') LIMIT 1",
            (job["target_key"], job["id"]))
        phase = "pack" if needs_pack is not None else "review"
        progress = self.progress(job["id"])
        if progress.body.get("phase") != phase:
            progress.set(phase=phase, count=True)
        else:
            progress.refresh()
        return phase

    def _spawn(self, active: list[tuple[dict, str]], now: int) -> int:
        conc = max(1, int(getattr(self.settings, "risk_review_concurrency", 4) or 4))
        if active:
            self._probe(self._health, self.engine.health, HEALTH_CACHE_S)
        limit = self.server().get("limit")
        cap = min(conc, int(limit)) if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 0 else conc
        free = cap - len(self.workers())
        started = 0
        while free > 0 and not self.stop.is_set():
            order = sorted(active, key=lambda item: (len(self.workers(item[0]["id"])), self._served.get(item[0]["id"], -1)))
            picked = None
            for job, phase in order:
                if job.get("hold_code") and self.workers(job["id"]):
                    continue                            # 반쯤 연 재개 — 성공 하나까지 워커 하나
                for purpose in (phase, "finalize") if phase == "review" else (phase,):
                    head = review_cells.claim_next_expert(self.store, {"id": job["id"]}, boot_id=self.boot_id, now=now,
                                                          purpose=purpose)
                    if head is not None:
                        picked = (job, purpose, head)
                        break
                if picked is not None:
                    break
            if picked is None:
                break
            job, phase, head = picked
            self._served_n += 1
            self._served[job["id"]] = self._served_n
            self._start_worker(job, head, phase)
            free -= 1
            started += 1
        return started

    def _start_worker(self, job: Mapping[str, Any], head: Mapping[str, Any], purpose: str) -> None:
        thread = threading.Thread(target=self._work, args=(dict(job), dict(head), purpose),
                                  name=f"review-{str(head['agent_key'])[:16]}", daemon=True)
        with self._lock:
            self._workers.append(_Worker(thread=thread, job_id=str(job["id"]), agent_key=str(head["agent_key"]),
                                         purpose=purpose))
        thread.start()

    def _work(self, job: dict, head: dict, purpose: str) -> None:
        target_key, agent, lease = str(job["target_key"]), str(head["agent_key"]), str(head["lease_owner"])
        session: _Session | None = None
        try:
            session = _Session(self, job, head, purpose)
            session.progress.worker(session.wkey, agent_key=agent, purpose=purpose, started_at=self.clock())
            if purpose == "pack":
                session.fetch_pack()
                raise _Stop("pack_frozen")
            if purpose == "finalize":
                session.finalize()
                return
            session.run()
        except _Stop as stop:
            if stop.release:
                review_cells.release_expert(self.store, target_key, agent, lease_owner=lease, not_before=stop.not_before,
                                            error=None if stop.why in ("pack_frozen", "cells_left", "no_cells") else stop.why,
                                            now=self.clock())
        except Exception as exc:  # noqa: BLE001 — 전문가 하나의 결함이 루프를 죽이지 않는다. 그 전문가는 잠시 쉬고 다시 집힌다.
            log.exception("검토 워커 실패(job=%s, agent=%s)", job.get("id"), agent)
            if session is not None:
                try:
                    session.internal_failure(exc)            # 남은 호출 행을 닫고 연달은 결함을 센다(R3A-2)
                except Exception:  # noqa: BLE001 — 기록 실패가 놓기를 막지 않는다.
                    log.exception("검토 워커 결함 기록 실패(job=%s, agent=%s)", job.get("id"), agent)
            review_cells.release_expert(self.store, target_key, agent, lease_owner=lease,
                                        not_before=self.clock() + INTERNAL_BACKOFF_S, error="internal_error", now=self.clock())
        finally:
            if session is not None:
                session.progress.worker_end(session.wkey)

    def tick(self) -> dict:
        """루프 한 번(위 ①~⑤). 반환 {jobs, running, started}(시험·로그용)."""
        if not self.ready() or self.stop.is_set():
            return {"jobs": 0, "running": 0, "started": 0}
        now = self.clock()
        jobs = self._jobs(("queued", "running", "paused", "cancelling"))
        for job in jobs:
            if job["state"] == "paused":
                self._maybe_resume(job, now)
            elif job["state"] == "cancelling" and not self.workers(job["id"]) and self._running_heads(job) == 0:
                self._finish(job, "cancelled", None)
        if not config.review_enabled(self.settings):
            # 스위치가 꺼진 채 다시 뜬 박스 — 잡은 그대로 두고(취소·끝내기 아님) 새 전문가·셀을 집지 않는다. 도는 호출은 끝까지 가고
            # 그 세션은 다음 호출 앞에서 놓는다(_gate). 다시 켜고 앱을 띄우면 차감 없이 이어 돈다.
            for job in self._jobs(("queued", "running")):
                progress = self.progress(job["id"])
                if (progress.body.get("waiting") or {}).get("reason") != DISABLED:
                    progress.set(waiting={"reason": DISABLED, "since": now, "retry_at": None,
                                          "note": "이 박스의 검토 스위치가 꺼져 있다 — $DATA_DIR/knobs.env 에"
                                                  " HWAXRISK_REVIEW_ENABLED=1 을 적고 앱을 다시 띄우면 이어 돈다"})
            return {"jobs": len(jobs), "running": 0, "started": 0}
        for job in self._jobs(("queued",)):
            self.store.execute("UPDATE rr_jobs SET state = 'running', updated_at = ? WHERE id = ? AND state = 'queued'",
                               (now, job["id"]))
        running = self._jobs(("running",))
        if not running:
            return {"jobs": len(jobs), "running": 0, "started": 0}
        active: list[tuple[dict, str]] = []
        for job in running:
            phase = self._complete_or_phase(job)
            if phase is not None:
                active.append((job, phase))
        if not active:
            return {"jobs": len(jobs), "running": 0, "started": 0}
        allowed = {j["id"] for j in self._window_ok([j for j, _ in active], now)}
        active = [(j, p) for j, p in active if j["id"] in allowed]
        return {"jobs": len(jobs), "running": len(active), "started": self._spawn(active, now)}
