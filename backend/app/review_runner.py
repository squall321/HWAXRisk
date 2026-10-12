# 카드 대조 검토 잡 — 잡 만들기(범위·자격·호출 수 추정·동의, 네트워크 없음). 검토 루프는 m2-wp3b S8 이 여기에 더한다
"""검토 잡(`rr_jobs.mode='reviews'`) 하나는 한 대상의 셀 원장에서 범위 안 셀을 끝까지 돈다. 이 파일의 첫 함수는 잡을 세우는
일만 한다 — 격자를 만들고(`review_cells.plan_cells`) 범위를 찍고(`assign_scope`) 잡 행을 넣는다. 카드 묶음·엔진 호출은 루프가 한다.

자격은 사용자 PAT 하나다 — 요청자 → 대상 소유자 순으로 등록된 PAT 가운데 남은 수명이 검토 여유(호출 벽시계 + 600초)를 넘는
첫 것이다. 서비스 계정 PAT 로 내려가지 않는다(사용자 결정 3 — 패널 경로의 `runner.resolve_credential_with_note` 와 다르다).
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from app import config, planner, review_cells, review_verify, runner, units
from app.common import canonical_json, new_uuid, now_epoch
from app.errors import AppError

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
def _refuse_live_jobs(store: Any, target_key: str) -> None:
    """살아 있는 검토 잡(409 review_job_exists)·패널 잡(409 panel_job_running)·다시 저장을 기다리는 패널(409
    repersist_pending — 검토 마감이 그 패널이 pending 으로 돌려 둔 좌석을 닫으면 다시 저장이 seats_moved 로 영영 막힌다,
    RR-ADV-1)이 있으면 거절한다."""
    marks = ",".join("?" * len(LIVE_STATES))
    live = store.query_one(
        f"SELECT id, state FROM rr_jobs WHERE target_key = ? AND mode = 'reviews' AND state IN ({marks})"
        " ORDER BY created_at DESC LIMIT 1", (target_key, *LIVE_STATES))
    if live is not None:
        raise AppError("review_job_exists", f"이 대상에는 살아 있는 검토 잡({live['id']}, {live['state']})이 있다 — 그 잡을"
                       " 재개하거나 취소한 뒤 새로 만든다.", 409, detail={"job_id": live["id"], "state": live["state"]})
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
    거절 — 409 review_disabled(HWAXRISK_REVIEW_ENABLED=0) · 404 E404 · 409 review_job_exists · 409 panel_job_running · 409
    repersist_pending · 422 units_absent(활성 빌드가 ok·oversize 가 아니다) · 422 scope_invalid · 422 scope_empty · 422
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
