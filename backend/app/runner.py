# 배치 러너(plan §6.7·§8.2.9) — panel_loop 이 잡을 집어 패널을 편성·실행하고 SSE 귀속·커버리지·등록부로 넘긴다. 엔진은 주입식(PanelEngine)
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from app import config, planner, taxonomy
from app.common import canonical_json, new_uuid, now_epoch
from app.errors import AppError

log = logging.getLogger("hwax_risk.runner")

# (스레드명, 폴링 주기 초). sync_loop 은 PAT 폐기 대조(§8.2.7)를 돌리고 external_sync 재시도(§5.5.3)는 P4 배선,
# nightly_loop(§7.7 야간 잡) 본문은 P6 에서 채운다.
_LOOPS: tuple[tuple[str, float], ...] = (("panel_loop", 5.0), ("sync_loop", 60.0), ("nightly_loop", 60.0))

# 좌석 귀속 정규식(plan §0.2.3·§6.7 7단계). SSE 스트림과 POST /api/panels/{id}/complete 의 events[] 에 같은 식을 쓴다.
STATUS_LOOKUP_RE = re.compile(r"^(?P<key>\S+) 조회: (?P<tool>\S+)$")
EVIDENCE_SEP = " · "

ENGINE_BUSY_WAIT_S = 30.0          # 포털 /agent/chat 429(세마포어 초과)는 error 가 아니라 대기 후 재시도
ENGINE_BUSY_MAX_RETRY = 10
CREDENTIAL_MARGIN_S = 1800         # (b) 사용자 PAT 는 timeout_s 만큼 남아 있어야 쓴다
ENGINE_FAIL_STREAK = 3             # 연속 3패널 error → 잡 failed
DIMINISHING_WINDOW = 3             # 최근 3패널이 신규 클러스터 <1 이면 수확 체감 정지
QUALITY_TOOL_USE_MIN = 0.8
QUALITY_IR_CITE_MIN = 0.5
QUALITY_ADVERSARY_OVERREJECT = 0.6
SEAT_CONTRACT_LINE_MAX = 200       # E0c 도메인당 ≤200자
SEAT_CONTRACT_TOTAL_MAX = 1000     # E0c 합 ≤1000자(plan §5.6.1 예산표)
USER_MEMO_MAX = 2000
PANEL_TIMEOUT_S = 2400             # 패널 벽시계 상한 40분(plan §6.10.2) — delib_opts.timeout_s 로 명시한다

# 러너 정본 경로가 부르는 모듈 함수(없으면 잡을 집지 않고 error 로 강등한다 — 반쪽 저장 방지).
REQUIRED_NARRATIVE = ("prior_evidence", "parse_risk_spec", "persist_panel_result")
REQUIRED_REGISTRY = ("merge_panel", "close_level", "build_consolidated_report")


class PanelEngine(Protocol):
    """심의 엔진 클라이언트(배선 담당 구현). 러너는 이 한 메서드만 부른다.

    run(delib_opts, owner_sub=None) -> {decision_text, turns, conv_id, events, credential?, call_path?}
      · turns  = [{round, persona, say, stance?, position?}]
      · events = 압축 로그 [{kind: 'status'|'evidence'|'personas'|'turn'|'warning'|'error', step?, tool?, source?, personas?}]
                 (None 이면 좌석 귀속 불가 — tool_calls_ok·used_tool 은 null 로 남는다)
    선택 메서드 health() -> {model, vllm?, engine_rev?, endpoint_host?} 가 있으면 D6 model_json 을 채운다.
    포털 429 는 EngineBusy, 그 밖의 실패는 EngineError 로 올린다.
    """

    def run(self, delib_opts: Mapping[str, Any], *, owner_sub: str | None = None) -> Mapping[str, Any]: ...


class EngineBusy(Exception):
    """엔진 슬롯이 없다(포털 agent_semaphore 429). 패널 카운트를 올리지 않고 대기 후 재시도한다."""


class EngineError(Exception):
    """엔진 호출이 실패했다(연결·타임아웃·error 이벤트). 패널은 error 로 닫힌다."""


class PatUnavailable(Exception):
    """러너 자격 문제(자격 없음·포털 401/403). 폴백하지 않고 잡을 `error='pat_unavailable'` 로 멈춘다(plan §6.7.1)."""


# ---------------------------------------------------------------- 좌석 귀속(plan §6.7 7단계)
def attribute_events(
    events: Sequence[Mapping[str, Any]] | None,
    seat_keys: Sequence[str],
    *,
    adversary_key: str = planner.ADVERSARY_KEY,
) -> dict:
    """status/evidence/personas/turn 이벤트를 좌석에 귀속한다.

    status.step 이 '<key> 조회: <tool>' 이면 시도(tool_calls_n), evidence.source 의 ' · ' 앞이 좌석 키면 성공(tool_calls_ok).
    events 가 None 이면 귀속 불가 — 좌석마다 tool_calls_n/ok·used_tool 을 None 으로 둔다(C2 strong 비율 분모 제외).
    """
    known = set(seat_keys) | {adversary_key}
    seats: dict[str, dict] = {
        key: {"tool_calls_n": 0, "tool_calls_ok": 0, "used_tool": False, "turns_n": 0, "tool_calls": []}
        for key in list(seat_keys) + [adversary_key]
    }
    if events is None:
        for key in seats:
            seats[key].update({"tool_calls_n": None, "tool_calls_ok": None, "used_tool": None})
        return {"seats": seats, "extra_seats": [], "personas_seen": [], "attribution_rate": None,
                "attributable": 0, "attributed": 0, "lookups": 0}

    personas_seen: list[str] = []
    attributable = attributed = lookups = 0
    activity_idx = 0
    for event in events:
        kind = str(event.get("kind") or event.get("event") or "")
        if kind == "personas":
            for item in event.get("personas") or ():
                key = item.get("key") if isinstance(item, Mapping) else item
                if key and str(key) not in personas_seen:
                    personas_seen.append(str(key))
            continue
        if kind == "turn":
            key = str(event.get("persona") or "")
            if key in seats:
                seats[key]["turns_n"] += 1
            continue
        if kind == "status":
            match = STATUS_LOOKUP_RE.match(str(event.get("step") or ""))
            if not match:
                continue
            attributable += 1
            lookups += 1
            key, tool = match.group("key"), match.group("tool")
            idx = activity_idx
            activity_idx += 1
            if key in known:
                attributed += 1
                seats.setdefault(key, {"tool_calls_n": 0, "tool_calls_ok": 0, "used_tool": False, "turns_n": 0,
                                       "tool_calls": []})
                seats[key]["tool_calls_n"] += 1
                seats[key]["tool_calls"].append({"tool": tool or event.get("tool"), "activity_idx": idx})
            continue
        if kind == "evidence":
            source = str(event.get("source") or "")
            if EVIDENCE_SEP not in source:
                continue                                  # E0~E9·지정 도구 주입은 좌석 귀속 없음(공용)
            attributable += 1
            key = source.split(EVIDENCE_SEP, 1)[0].strip()
            if key in known:
                attributed += 1
                seats.setdefault(key, {"tool_calls_n": 0, "tool_calls_ok": 0, "used_tool": False, "turns_n": 0,
                                       "tool_calls": []})
                seats[key]["tool_calls_ok"] += 1
    for state in seats.values():
        if state["tool_calls_ok"] is not None:
            state["used_tool"] = state["tool_calls_ok"] >= 1
    extra = [k for k in personas_seen if k not in known]
    return {
        "seats": seats,
        "extra_seats": extra,
        "personas_seen": personas_seen,
        "attribution_rate": (attributed / attributable) if attributable else None,
        "attributable": attributable,
        "attributed": attributed,
        "lookups": lookups,
    }


# ---------------------------------------------------------------- 러너 자격(plan §6.7 3단계)
def resolve_credential(store: Any, settings: Any | None, owner_sub: str | None) -> dict | None:
    """(b) 타깃 owner 가 등록한 포털 PAT → (a) 서비스 계정 PAT 순으로 자격을 정한다. 둘 다 없으면 None.

    시크릿 값은 돌려주지 않는다(엔진 클라이언트가 같은 규칙으로 다시 읽는다). 반환은 {kind, email?}.
    """
    cfg = config.settings if settings is None else settings
    if owner_sub:
        from app import identity  # noqa: PLC0415 — identity 는 config 만 읽으므로 지연 import 로 순환을 피한다.

        row = store.get_credential(owner_sub)
        # 복호되지 않는 자격(키 없음·폐기 표기·손상)은 엔진이 쓸 수 없으므로 (b) 로 세지 않는다(plan §8.2.7).
        if row and identity.credential_pat(row) and int(row.get("pat_exp") or 0) > now_epoch() + CREDENTIAL_MARGIN_S:
            return {"kind": "owner", "email": row.get("pat_email")}
    secrets = config.load_secrets(cfg.data_dir)
    if secrets.get("HWAXRISK_PORTAL_PAT"):
        return {"kind": "service", "email": None}
    return None


# ---------------------------------------------------------------- delib_opts 조립(plan §6.6.4)
def _delib_apps() -> list[str]:
    """자유조회 스코프 앱키(≤3) — 앱명을 하드코딩하지 않고 adapters/registry 가 발견한 값을 쓴다."""
    from app.adapters.registry import ADAPTERS

    keys: list[str] = []
    for adapter in ADAPTERS:
        if adapter.app_key and adapter.app_key not in keys:
            keys.append(adapter.app_key)
    return keys[:planner.MAX_APPS]


def seat_contract_evidence(domains: Sequence[str]) -> dict:
    """E0c — 이번 패널 착석 도메인의 좌석 계약 행(도메인당 ≤200자, 합 ≤1000자). 대화 기록·MCP 경로 이중화."""
    contract = taxonomy.load_json("seat-contract").get("contract", {})
    seen: list[str] = []
    for dom in domains:
        if dom not in seen:
            seen.append(dom)
    lines: list[str] = []
    total = 0
    for dom in seen:
        line = str(contract.get(dom) or "")[:SEAT_CONTRACT_LINE_MAX]
        if not line or total + len(line) + 1 > SEAT_CONTRACT_TOTAL_MAX:
            continue
        lines.append(line)
        total += len(line) + 1
    return {
        "source": "seat_contract",
        "tool": "seat-contract.v1",
        "args": ",".join(seen),
        "result": "\n".join(lines),
    }


def panel_question(store: Any, target_key: str) -> str:
    """질문 문자열(plan §6.6.4) — 과제코드·target_key·소스 id·요약 첫 줄. 좌석 agent_search(q=question) 의 문맥이다."""
    target = store.query_one(
        "SELECT target_key, kind, ref_id, project_id, base_project_id FROM rr_targets WHERE target_key = ?",
        (target_key,),
    )
    if target is None:
        raise AppError("E404", f"타깃이 없습니다: {target_key}", 404)

    def code_of(project_id: str | None) -> str:
        if not project_id:
            return "-"
        row = store.query_one("SELECT code FROM rr_projects WHERE id = ?", (project_id,))
        return row["code"] if row else project_id

    if target["kind"] == "diff":
        row = store.query_one("SELECT summary_text FROM rr_diffs WHERE id = ?", (target["ref_id"],))
        head = "기준 %s 대비 변경" % code_of(target["base_project_id"])
    else:
        row = store.query_one("SELECT summary_text FROM rr_states WHERE snapshot_id = ?", (target["ref_id"],))
        head = "현황"
    summary = (row["summary_text"] if row and row["summary_text"] else "")[:200]

    parts: list[str] = []
    for source in store.query(
        "SELECT kind, ref_json FROM rr_sources WHERE project_id = ? ORDER BY kind ASC, id ASC", (target["project_id"],)
    ):
        try:
            ref = json.loads(source["ref_json"] or "{}")
        except ValueError:
            ref = {}
        if not isinstance(ref, dict):
            continue
        pairs = " ".join(f"{k}={ref[k]}" for k in sorted(ref) if ref[k] not in (None, "", [], {}))
        if pairs:
            parts.append(f"{source['kind']} {pairs}")

    return (
        f"[리스크심사 {code_of(target['project_id'])} {target_key}] {head}이 각 도메인에서 어떤 리스크와 개선을 "
        f"낳는가를 도구 근거로 판정하라. 소스 {'; '.join(parts) if parts else '(등록된 소스 없음)'}. "
        f"{'diff' if target['kind'] == 'diff' else '현황'} 요약 첫 줄: {summary}"
    )


def build_delib_opts(
    store: Any,
    settings: Any | None,
    panel: Mapping[str, Any],
    *,
    evidence: Sequence[Mapping[str, Any]] | None = None,
    user_memo: str | None = None,
    narrative_mod: Any | None = None,
) -> dict:
    """패널 1건의 delib_opts(plan §6.6.4). human_note·continue_summary·non_negotiables·search_sources·
    stop_after_round·build_plan 은 절대 싣지 않는다(불변식 extra_seats == ∅ 의 전제)."""
    seats = panel["seats"]
    if evidence is None:
        module = narrative_mod
        if module is None:
            from app import narrative as module  # noqa: PLC0415 — 순환 import 회피(narrative 는 러너를 import 한다)
        build = getattr(module, "prior_evidence", None)
        if not callable(build):
            raise AppError("not_implemented", "narrative.prior_evidence 가 없습니다 — 브리프를 조립할 수 없습니다.", 501)
        evidence = list(build(store, panel["target_key"], user_memo=user_memo,
                              seats=seats, panel_id=panel["id"]))
    else:
        evidence = list(evidence)
    # E0(스코프·게이트) 바로 뒤가 E0c 좌석 계약표다.
    evidence.insert(1 if evidence else 0, seat_contract_evidence([s["domain"] for s in seats]))
    if user_memo and not any(e.get("source") == "user_memo" for e in evidence):
        evidence.append({"source": "user_memo", "tool": "note", "result": str(user_memo)[:USER_MEMO_MAX]})

    return {
        "chair_template": planner.CHAIR_TEMPLATE,
        "modifiers": list(panel["modifiers"]),
        "rounds": int(panel["rounds"]),
        "free_tools": planner.FREE_TOOLS,
        "tool_budget": planner.TOOL_BUDGET,
        "personas": [{"key": s["key"], "role": "", "origin": s["origin"]} for s in seats],
        "tools": list(panel["tools"]),
        "apps": _delib_apps(),
        "evidence": evidence[:planner.MAX_EVIDENCE],
        # 벽시계 상한 40분(plan §6.10.2). 엔진 기본값(30분)에 기대지 않고 계약값을 실어 보낸다.
        "timeout_s": PANEL_TIMEOUT_S,
        "question": panel_question(store, panel["target_key"]),
    }


# ---------------------------------------------------------------- 잡(plan §6.4.3·§8.2.3)
def _params(row: Mapping[str, Any]) -> dict:
    try:
        value = json.loads(row["params_json"] or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _local_midnight(ts: float | None = None) -> int:
    """서버 로컬 시각 기준 오늘 00:00 의 epoch 초(일일 상한·자동 재개 판정용).

    '지금' 은 앱 전체가 `common.now_epoch` 한 곳에서 읽는다 — time.time() 을 직접 읽으면 시계를 고정한
    시험·재현에서 rr_panels.created_at 과 기준이 어긋나 일일 상한이 영영 걸리지 않는다.
    """
    lt = time.localtime(ts if ts is not None else now_epoch())
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1)))


def create_job(
    store: Any,
    target_key: str,
    tier: str,
    *,
    owner_sub: str,
    modifiers: Sequence[str] | None = None,
    user_memo: str | None = None,
    concurrency: int = 1,
    consent: bool = False,
    settings: Any | None = None,
) -> dict:
    """배치 잡 1건을 만든다(POST /api/targets/{key}/jobs). Tier C 는 consent 필수, 러너 자격이 없으면 422."""
    cfg = config.settings if settings is None else settings
    if tier not in planner.TIERS:
        raise AppError("E100", f"모르는 tier — {tier!r}. 허용 {list(planner.TIERS)}.", 422)
    if tier == "C" and not consent:
        raise AppError("E100", "Tier C 는 consent:true 명시 승인이 필요합니다.", 422)
    credential = resolve_credential(store, cfg, owner_sub)
    if credential is None:
        raise AppError("pat_unavailable", "러너 자격이 없습니다 — 포털 PAT 를 등록하거나 서비스 PAT 를 설정하세요.", 422)

    plan = planner.tier_plan(store, target_key, settings=cfg)
    row = next(t for t in plan["tiers"] if t["tier"] == tier)
    job_id = new_uuid()
    now = now_epoch()
    params = {
        "tier": tier,
        "modifiers": list(planner.resolve_modifiers(modifiers)),
        "user_memo": (str(user_memo)[:USER_MEMO_MAX] if user_memo else None),
        "consent": bool(consent),
        "credential": credential["kind"],
    }
    store.execute(
        "INSERT INTO rr_jobs(id, target_key, owner_sub, tier, state, concurrency, params_json, panels_done,"
        " panels_total, created_at, updated_at) VALUES (?, ?, ?, ?, 'queued', ?, ?, 0, ?, ?, ?)",
        (job_id, target_key, owner_sub, tier, max(1, min(int(concurrency), int(cfg.risk_concurrency))),
         canonical_json(params), row["panels"], now, now),
    )
    return {
        "job_id": job_id,
        "panels_planned": row["panels"],
        "llm_calls_estimate": {"low": row["llm_calls_low"], "high": row["llm_calls_high"]},
        "credential": credential["kind"],
    }


def _set_job(store: Any, job_id: str, state: str, *, reason: str | None = None, error: str | None = None) -> dict:
    store.execute(
        "UPDATE rr_jobs SET state = ?, pause_reason = ?, error = ?, updated_at = ? WHERE id = ?",
        (state, reason, error, now_epoch(), job_id),
    )
    return {"job_id": job_id, "state": state, "pause_reason": reason}


def pause_job(store: Any, job_id: str, *, reason: str = "user") -> dict:
    """패널 경계에서 반영되는 일시정지(reason ∈ diminishing|daily_cap|user)."""
    row = store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))
    if row is None:
        raise AppError("E404", f"잡이 없습니다: {job_id}", 404)
    if row["state"] not in ("queued", "running"):
        raise AppError("E100", f"일시정지할 수 없는 상태입니다 — {row['state']}.", 409)
    return _set_job(store, job_id, "paused", reason=reason)


def resume_job(store: Any, job_id: str) -> dict:
    row = store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))
    if row is None:
        raise AppError("E404", f"잡이 없습니다: {job_id}", 404)
    if row["state"] != "paused":
        raise AppError("E100", f"재개할 수 없는 상태입니다 — {row['state']}.", 409)
    return _set_job(store, job_id, "queued")


def cancel_job(store: Any, job_id: str) -> dict:
    """진행 중 패널은 끝까지 가고 그 다음 패널 경계에서 cancelled 가 된다."""
    row = store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))
    if row is None:
        raise AppError("E404", f"잡이 없습니다: {job_id}", 404)
    if row["state"] in ("cancelled", "completed", "failed"):
        return {"job_id": job_id, "state": row["state"], "pause_reason": None}
    if row["state"] == "running":
        return _set_job(store, job_id, "cancelling")
    return _set_job(store, job_id, "cancelled")


def _panels_today(store: Any, target_key: str) -> int:
    row = store.query_one(
        "SELECT COUNT(*) AS n FROM rr_panels WHERE target_key = ? AND created_at >= ?",
        (target_key, _local_midnight()),
    )
    return int(row["n"] or 0) if row else 0


def claim_next_job(store: Any, settings: Any | None = None) -> dict | None:
    """다음에 패널을 돌릴 잡 1건을 집는다. 타깃당 직렬·일일 상한·자격·취소를 여기서 판정한다."""
    cfg = config.settings if settings is None else settings
    midnight = _local_midnight()
    for row in store.query(
        "SELECT id, target_key, owner_sub, tier, state, pause_reason, params_json, panels_done, updated_at"
        " FROM rr_jobs WHERE state = 'paused' AND pause_reason = 'daily_cap' ORDER BY created_at ASC, id ASC"
    ):
        if int(row["updated_at"] or 0) < midnight:
            _set_job(store, row["id"], "queued")

    for row in store.query(
        "SELECT id, target_key, owner_sub, tier, state, params_json, panels_done, panels_total"
        " FROM rr_jobs WHERE state IN ('queued', 'running', 'cancelling') ORDER BY created_at ASC, id ASC"
    ):
        job = dict(row)
        if job["state"] == "cancelling":
            _set_job(store, job["id"], "cancelled")
            continue
        busy = store.query_one(
            "SELECT id FROM rr_panels WHERE target_key = ? AND status = 'running' LIMIT 1", (job["target_key"],)
        )
        if busy is not None:
            continue
        if _panels_today(store, job["target_key"]) >= int(cfg.risk_daily_panel_cap):
            _set_job(store, job["id"], "paused", reason="daily_cap")
            continue
        credential = resolve_credential(store, cfg, job["owner_sub"])
        if credential is None:
            store.execute(
                "UPDATE rr_jobs SET error = 'pat_unavailable', updated_at = ? WHERE id = ?", (now_epoch(), job["id"])
            )
            continue
        if job["state"] != "running":
            _set_job(store, job["id"], "running")
            job["state"] = "running"
        job["params"] = _params(row)
        job["credential"] = credential["kind"]
        return job
    return None


# ---------------------------------------------------------------- 재기동 복구(plan §6.7.2 끝 문단)
def recover_running_panels(store: Any) -> dict:
    """이전 기동이 남긴 running 패널을 error(retry+1) 로 닫고 좌석을 pending 으로 되돌린다."""
    rows = store.query("SELECT id, target_key, retry FROM rr_panels WHERE status = 'running' ORDER BY created_at ASC")
    now = now_epoch()
    for row in rows:
        planner.fail_panel_seats(store, row["id"], reason="engine_fail")
        store.execute(
            "UPDATE rr_panels SET status = 'error', error = 'restart', retry = ?, ended_at = ? WHERE id = ?",
            (int(row["retry"] or 0) + 1, now, row["id"]),
        )
    store.execute("UPDATE rr_jobs SET state = 'queued', updated_at = ? WHERE state = 'running'", (now,))
    return {"recovered": len(rows)}


# ---------------------------------------------------------------- 패널 1건(plan §6.7.2 1~12단계)
def seat_contract_rev() -> str:
    """seat-contract.v1.json 의 sha256[:12](D6 model_json.seat_contract_rev, plan §6.7.2 1단계)."""
    from app.common import sha256_hex  # noqa: PLC0415

    return sha256_hex(taxonomy.asset_path("seat-contract").read_bytes())[:12]


def _engine_health(engine: Any) -> dict:
    """엔진이 health() 를 노출하면 D6 model_json 시작 스냅샷을 만든다(없으면 captured='unavailable')."""
    probe = getattr(engine, "health", None)
    if not callable(probe):
        return {"runtime": "agent-server", "captured": "unavailable", "model": "unknown",
                "seat_contract_rev": seat_contract_rev()}
    try:
        info = dict(probe() or {})
    except Exception as exc:  # noqa: BLE001 — /health 불통은 비치명이고 패널은 그대로 진행한다.
        log.warning("엔진 health 조회 실패(비치명): %s", exc)
        return {"runtime": "agent-server", "captured": "unavailable", "model": "unknown",
                "seat_contract_rev": seat_contract_rev()}
    return {
        "runtime": "agent-server",
        "provider": info.get("provider") or "vllm",
        "model": info.get("model") or "unknown",
        "endpoint_host": info.get("endpoint_host"),
        "captured": "health_snapshot",
        "engine_rev": info.get("engine_rev") or info.get("version"),
        "vllm": info.get("vllm"),
        "sampling": info.get("sampling"),
        # chair_rev 는 엔진(deliberation.py) 상수의 해시라 앱에 원문이 없다 — 비워 둔다(§6.7.2 1단계 미충족 표기).
        "chair_rev": None,
        "seat_contract_rev": seat_contract_rev(),
    }


def _quality(
    panel: Mapping[str, Any],
    attribution: Mapping[str, Any],
    extracted: Mapping[str, Any],
    *,
    credential: str,
    call_path: str,
    new_clusters: int,
    llm_calls: int,
    cap: int,
    parsed: bool,
    pat_degraded: bool,
) -> dict:
    """rr_panels.quality_json(plan §6.5.5) — 비율·분포·flags."""
    seat_keys = [s["key"] for s in panel["seats"]]
    seats = extracted.get("seats") or []
    by_key = {s.get("agent_key"): s for s in seats}
    attributable = [k for k in seat_keys if (attribution["seats"].get(k) or {}).get("used_tool") is not None]
    used = [k for k in attributable if attribution["seats"][k]["used_tool"]]
    cited_ir = [k for k in seat_keys if (by_key.get(k) or {}).get("cited_ir")]
    findings_total = int(extracted.get("findings_total") or 0)
    rejects = int(extracted.get("adversary_rejects") or 0)

    tool_use_rate = (len(used) / len(attributable)) if attributable else None
    ir_cite_rate = (len(cited_ir) / len(seat_keys)) if seat_keys else None
    reject_rate = (rejects / findings_total) if findings_total else 0.0

    flags: list[str] = []
    if tool_use_rate is not None and tool_use_rate < QUALITY_TOOL_USE_MIN:
        flags.append("low_tool_use")
    if ir_cite_rate is not None and ir_cite_rate < QUALITY_IR_CITE_MIN:
        flags.append("low_ir_cite")
    if rejects == 0:
        flags.append("adversary_silent")
    if reject_rate > QUALITY_ADVERSARY_OVERREJECT:
        flags.append("adversary_overreject")
    if extracted.get("header_mismatch"):
        flags.append("header_mismatch")
    if not parsed:
        flags.append("spec_parse_failed")
    if llm_calls > cap:
        flags.append("over_budget")
    if attribution["extra_seats"]:
        flags.append("rescreen_seats")
    if extracted.get("coverage_mismatch"):
        flags.append("coverage_mismatch")

    return {
        "tool_use_rate": tool_use_rate,
        "ir_cite_rate": ir_cite_rate,
        "grade_dist": extracted.get("grade_dist") or {},
        "adversary_reject_rate": reject_rate,
        "attribution_rate": attribution["attribution_rate"],
        "new_clusters": new_clusters,
        "llm_calls_observed": llm_calls,
        "pat_degraded": pat_degraded,
        "credential": credential,
        "call_path": call_path,
        "extra_seats": list(attribution["extra_seats"]),
        "flags": flags,
    }


def _finish_job(store: Any, job: Mapping[str, Any], settings: Any) -> dict:
    """Tier 범위 소진 — 잡을 completed 로 닫고, close_level 이 C3 이면 Tier B 뒤에 Tier C 를 자동 큐잉한다."""
    _set_job(store, job["id"], "completed")
    target = store.query_one("SELECT owner_sub, close_level FROM rr_targets WHERE target_key = ?", (job["target_key"],))
    close_level = (target["close_level"] if target and target["close_level"] else settings.risk_default_close_level)
    if job["tier"] == "B" and close_level == "C3":
        follow = create_job(
            store, job["target_key"], "C", owner_sub=job["owner_sub"],
            modifiers=(job.get("params") or {}).get("modifiers"),
            user_memo=(job.get("params") or {}).get("user_memo"),
            consent=True, settings=settings,
        )
        return {"job_state": "completed", "next_job": follow["job_id"]}
    return {"job_state": "completed", "next_job": None}


def _diminishing(store: Any, target_key: str) -> bool:
    """최근 3패널이 각각 신규 클러스터 <1 이면 수확 체감(호출자는 C1 충족까지 확인한다)."""
    rows = store.query(
        "SELECT quality_json FROM rr_panels WHERE target_key = ? AND status = 'done'"
        " ORDER BY panel_no DESC LIMIT ?",
        (target_key, DIMINISHING_WINDOW),
    )
    if len(rows) < DIMINISHING_WINDOW:
        return False
    for row in rows:
        try:
            quality = json.loads(row["quality_json"] or "{}")
        except ValueError:
            return False
        if int(quality.get("new_clusters") or 0) >= 1:
            return False
    return True


def _error_streak(store: Any, target_key: str) -> int:
    streak = 0
    for row in store.query(
        "SELECT status FROM rr_panels WHERE target_key = ? ORDER BY panel_no DESC LIMIT ?",
        (target_key, ENGINE_FAIL_STREAK),
    ):
        if row["status"] != "error":
            break
        streak += 1
    return streak


def missing_interfaces(narrative_mod: Any | None = None, registry_mod: Any | None = None) -> list[str]:
    """러너 정본 경로가 부르는 모듈 함수 중 실재하지 않는 것의 이름(정상이면 빈 목록).

    대역을 주입하지 않은 운영 배선에서도 이 검사가 먼저 돌아 '패널만 running 에 고착' 을 막는다.
    """
    if narrative_mod is None:
        from app import narrative as narrative_mod  # noqa: PLC0415
    if registry_mod is None:
        from app import registry as registry_mod  # noqa: PLC0415
    out = [f"narrative.{n}" for n in REQUIRED_NARRATIVE if not callable(getattr(narrative_mod, n, None))]
    out += [f"registry.{n}" for n in REQUIRED_REGISTRY if not callable(getattr(registry_mod, n, None))]
    return out


def run_panel(
    store: Any,
    settings: Any,
    engine: PanelEngine,
    job: Mapping[str, Any],
    *,
    narrative_mod: Any | None = None,
    registry_mod: Any | None = None,
    stop: threading.Event | None = None,
) -> dict:
    """패널 1건을 편성·실행·회수한다(plan §6.7.2). 반환 {panel_id|None, status, ...}."""
    params = job.get("params") or {}
    missing = missing_interfaces(narrative_mod, registry_mod)
    if missing:
        # 배선이 덜 된 채 좌석을 앉히면 패널이 running 에 고착돼 그 타깃이 영영 편성되지 않는다.
        log.error("러너 인터페이스 결손 %s — 잡 %s 를 집지 않는다", missing, job.get("id"))
        _set_job(store, job["id"], "failed", error="missing_interface: " + ",".join(missing))
        return {"panel_id": None, "status": "missing_interface", "missing": missing}

    panel = planner.plan_next_panel(
        store, job["target_key"], job["tier"], modifiers=params.get("modifiers"), settings=settings
    )
    if panel is None:
        return {"panel_id": None, "status": "no_panel", **_finish_job(store, job, settings)}

    planner.start_panel_seats(store, panel["id"])
    try:
        model_json = _engine_health(engine)
        store.execute("UPDATE rr_panels SET model_json = ? WHERE id = ?", (canonical_json(model_json), panel["id"]))
        delib_opts = build_delib_opts(
            store, settings, panel, user_memo=params.get("user_memo"), narrative_mod=narrative_mod
        )
    except Exception as exc:  # noqa: BLE001 — 브리프 조립 실패도 좌석을 pending 으로 되돌리고 닫는다.
        log.exception("패널 %s 브리프 조립 실패", panel["id"])
        return _close_panel_error(store, panel, job, f"brief_error: {type(exc).__name__}: {exc}", settings)

    result: Mapping[str, Any] | None = None
    error: str | None = None
    for attempt in range(ENGINE_BUSY_MAX_RETRY):
        try:
            # 러너 자격 (b) 사용자 PAT 를 쓰려면 잡의 owner_sub 가 엔진까지 가야 한다(plan §6.7 3단계).
            result = engine.run(delib_opts, owner_sub=job.get("owner_sub"))
            break
        except EngineBusy:
            if stop is not None and stop.wait(ENGINE_BUSY_WAIT_S):
                error = "stopped"
                break
            if stop is None:
                time.sleep(ENGINE_BUSY_WAIT_S)
            if attempt == ENGINE_BUSY_MAX_RETRY - 1:
                error = "engine_busy"
        except PatUnavailable as exc:
            # 자격 문제는 폴백·재시도 대상이 아니다 — 잡을 멈추고 좌석을 되돌린다(plan §6.7.1).
            out = _close_panel_error(store, panel, job, f"pat_unavailable: {exc}", settings)
            _set_job(store, job["id"], "failed", error="pat_unavailable")
            return {**out, "error": "pat_unavailable"}
        except EngineError as exc:
            error = f"engine_error: {exc}"
            break
        except Exception as exc:  # noqa: BLE001 — 어떤 예외든 패널만 error 로 닫고 러너는 계속 돈다.
            log.exception("패널 %s 엔진 호출 실패", panel["id"])
            error = f"{type(exc).__name__}: {exc}"
            break

    if result is None:
        return _close_panel_error(store, panel, job, error or "engine_error", settings)
    return _complete_panel(
        store, settings, panel, job, result, model_json,
        narrative_mod=narrative_mod, registry_mod=registry_mod, engine=engine,
    )


def _close_panel_error(store: Any, panel: Mapping[str, Any], job: Mapping[str, Any], error: str, settings: Any) -> dict:
    planner.fail_panel_seats(store, panel["id"], reason="engine_fail")
    now = now_epoch()
    store.execute(
        "UPDATE rr_panels SET status = 'error', error = ?, retry = retry + 1, ended_at = ? WHERE id = ?",
        (error[:500], now, panel["id"]),
    )
    if _error_streak(store, panel["target_key"]) >= ENGINE_FAIL_STREAK:
        _set_job(store, job["id"], "failed", error="engine_fail_streak")
    return {"panel_id": panel["id"], "status": "error", "error": error}


def _complete_panel(
    store: Any,
    settings: Any,
    panel: Mapping[str, Any],
    job: Mapping[str, Any],
    result: Mapping[str, Any],
    model_json: Mapping[str, Any],
    *,
    narrative_mod: Any | None,
    registry_mod: Any | None,
    engine: Any,
) -> dict:
    if narrative_mod is None:
        from app import narrative as narrative_mod  # noqa: PLC0415
    if registry_mod is None:
        from app import registry as registry_mod  # noqa: PLC0415

    seat_keys = [s["key"] for s in panel["seats"]]
    decision_text = str(result.get("decision_text") or "")
    turns = list(result.get("turns") or [])
    events = result.get("events")
    attribution = attribute_events(events, seat_keys)

    spec = narrative_mod.parse_risk_spec(decision_text)
    parsed = spec is not None
    now = now_epoch()

    # 종료 직후 model 스냅샷 재확인(D6 — 시작값이 정본, 재실행 없음).
    model_final = dict(model_json)
    model_changed = False
    if model_json.get("captured") == "health_snapshot":
        after = _engine_health(engine)
        if after.get("captured") == "health_snapshot" and (
            after.get("model") != model_json.get("model") or after.get("vllm") != model_json.get("vllm")
        ):
            model_final["model_end"] = after.get("model")
            model_changed = True

    # 8~12단계를 한 트랜잭션으로 묶는다 — 중간 실패 시 'done 인데 finding 0·좌석 running' 반쪽 저장이 남지 않는다.
    with store.tx():
        store.execute(
            "UPDATE rr_panels SET status = 'done', decision_text = ?, risk_spec_json = ?, risk_spec_parsed = ?,"
            " conv_id = ?, report_id = ?, model_json = ?, ended_at = ? WHERE id = ?",
            (decision_text, canonical_json(spec) if parsed else None, 1 if parsed else 0,
             result.get("conv_id"), result.get("report_id"), canonical_json(model_final), now, panel["id"]),
        )

        extracted = narrative_mod.persist_panel_result(
            store, panel["id"], decision_text=decision_text, spec=spec, turns=turns,
            attribution=attribution, actor=None,
        )
        # 발언 수는 turns[] 가 정본이다(events 에 turn 이 없는 캡처도 있다 — §6.7 7단계 표).
        turns_by_seat: dict[str, int] = {}
        for turn in turns:
            key = str(turn.get("persona") or "")
            if key:
                turns_by_seat[key] = turns_by_seat.get(key, 0) + 1

        seat_results = []
        for seat in extracted.get("seats") or []:
            key = seat.get("agent_key")
            if key not in seat_keys:
                continue
            state = attribution["seats"].get(key) or {}
            seat_results.append({
                "agent_key": key,
                "opinion_id": seat.get("opinion_id"),
                "turns_n": max(
                    int(seat.get("turns_n") or 0),
                    turns_by_seat.get(key, 0),
                    int(state.get("turns_n") or 0),
                ),
                "used_tool": state.get("used_tool"),
                "cited_refs_n": int(seat.get("cited_refs_n") or 0),
                "abstained": bool(seat.get("abstained")),
            })
        coverage = planner.apply_seat_results(
            store, panel["id"], seat_results, decision_ok=bool(decision_text), model=model_final.get("model")
        )

        merged = registry_mod.merge_panel(store, panel["id"])
        new_clusters = int((merged or {}).get("new_clusters") or 0)

        llm_calls = len(turns) + attribution["lookups"] * 3 + len(panel["tools"]) + 3
        quality = _quality(
            panel, attribution, extracted,
            # 실제로 어느 자격으로 돌았는지는 엔진이 안다 — 잡의 사전 판정은 폴백값이다.
            credential=str(result.get("credential") or job.get("credential") or "service"),
            call_path=str(result.get("call_path") or "portal"),
            new_clusters=new_clusters,
            llm_calls=llm_calls,
            cap=int(settings.risk_panel_llm_cap),
            parsed=parsed,
            pat_degraded=bool(result.get("pat_degraded")),
        )
        if model_changed and "model_changed_midrun" not in quality["flags"]:
            quality["flags"].append("model_changed_midrun")
        if result.get("call_groups"):
            quality["call_groups"] = list(result["call_groups"])
        store.execute(
            "UPDATE rr_panels SET quality_json = ?, llm_calls = ? WHERE id = ?",
            (canonical_json(quality), llm_calls, panel["id"]),
        )
        store.execute(
            "UPDATE rr_jobs SET panels_done = panels_done + 1, updated_at = ? WHERE id = ?", (now, job["id"])
        )

        level = registry_mod.close_level(store, panel["target_key"])
        if level.get("raised"):
            registry_mod.build_consolidated_report(store, panel["target_key"], level["level"])

    # 연속 2패널 over_budget 이면 이후 패널을 rounds 2 로(적응은 앞으로만) — budget_json 에 남긴다.
    if "over_budget" in quality["flags"]:
        log.info("패널 %s over_budget(llm_calls=%s)", panel["id"], llm_calls)
    if level.get("level") not in (None, "C0") and _diminishing(store, panel["target_key"]):
        _set_job(store, job["id"], "paused", reason="diminishing")

    return {
        "panel_id": panel["id"],
        "status": "done",
        "parsed": parsed,
        "coverage": coverage["by_status"],
        "new_clusters": new_clusters,
        "llm_calls": llm_calls,
        "level": level.get("level"),
        "quality_flags": quality["flags"],
    }


# ---------------------------------------------------------------- 스레드
# ---------------------------------------------------------------- PAT 폐기 대조(plan §8.2.7·§0.6 '자격 최소 권한')
REVOKED_PATH = "/auth/pat/revoked.json"
REVOKED_TIMEOUT_S = 3.0
# 테스트가 httpx.MockTransport 를 꽂는 자리. None 이면 실제 네트워크.
_revoked_transport: Any | None = None


def fetch_revoked_jtis(settings) -> list[str] | None:
    """포털 `GET /auth/pat/revoked.json` → `{"revoked":[jti…]}`. 형식이 아니거나 실패면 None(직전 목록 유지)."""
    import httpx  # noqa: PLC0415 — 러너 정본 경로가 아니라 이 함수에서만 쓴다.

    base = str(getattr(settings, "portal_base", "") or "").rstrip("/")
    if not base:
        return None
    try:
        with httpx.Client(transport=_revoked_transport, timeout=REVOKED_TIMEOUT_S) as client:
            r = client.get(base + REVOKED_PATH)
        if r.status_code != 200:
            log.warning("PAT 폐기 목록 조회 실패(HTTP %s) — 직전 목록을 유지한다.", r.status_code)
            return None
        body = r.json()
    except Exception as exc:  # noqa: BLE001 — 네트워크·파싱 실패는 비치명적이다(값은 로그하지 않는다).
        log.warning("PAT 폐기 목록 조회 실패(%s) — 직전 목록을 유지한다.", type(exc).__name__)
        return None
    revoked = body.get("revoked") if isinstance(body, dict) else None
    if not isinstance(revoked, list):
        log.warning("PAT 폐기 목록 형식이 {'revoked':[jti…]} 가 아니다 — 직전 목록을 유지한다.")
        return None
    return [str(j) for j in revoked if str(j).strip()]


def poll_revoked_pats(store, settings, *, now: int | None = None) -> dict:
    """적중한 `pat_jti` 행에 `revoked_at` 을 찍는다 — 강등은 패널 경계에서 credential_pat 이 None 을 돌려 일어난다.

    응답이 계약 형식이 아니거나 조회가 실패하면 아무 행도 건드리지 않는다(조용한 전체 강등 금지).
    """
    jtis = fetch_revoked_jtis(settings)
    if not jtis:
        return {"checked": 0, "revoked": 0}
    stamp = now_epoch() if now is None else now
    marks = ",".join("?" for _ in jtis)
    rows = store.query(
        f"SELECT owner_sub FROM _user_credentials WHERE pat_jti IN ({marks}) AND revoked_at IS NULL", jtis)
    for row in rows:
        store.execute(
            "UPDATE _user_credentials SET revoked_at = ?, revoked_seen_at = ? WHERE owner_sub = ?",
            (stamp, stamp, row["owner_sub"]))
    return {"checked": len(jtis), "revoked": len(rows)}


class RiskRunner:
    """main.py lifespan 이 start()/stop() 하는 객체. 엔진 클라이언트는 주입식이고 러너는 직접 LLM 을 부르지 않는다."""

    def __init__(
        self,
        store,
        settings,
        engine: PanelEngine | None = None,
        *,
        narrative_mod: Any | None = None,
        registry_mod: Any | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.engine = engine
        self.narrative_mod = narrative_mod
        self.registry_mod = registry_mod
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._workers: list[threading.Thread] = []
        self._last_tick: dict[str, float | None] = {name: None for name, _ in _LOOPS}
        self._last_revocation_poll = 0.0
        concurrency = int(getattr(settings, "risk_concurrency", 1) or 1) if settings is not None else 1
        self._sem = threading.Semaphore(max(1, concurrency))

    # ------------------------------------------------------------ 루프
    def _loop(self, name: str, interval: float) -> None:
        while not self._stop.is_set():
            self._last_tick[name] = time.time()
            if name == "panel_loop":
                try:
                    self._panel_tick()
                except Exception:  # noqa: BLE001 — 한 번의 실패가 스레드를 죽이지 않게 한다.
                    log.exception("panel_loop tick 실패")
            elif name == "sync_loop":
                try:
                    self._revocation_tick()
                except Exception:  # noqa: BLE001 — 폐기 대조 실패는 비치명적이다.
                    log.exception("sync_loop 폐기 대조 실패")
            self._stop.wait(interval)

    def _revocation_tick(self) -> None:
        """포털 폐기 목록을 `risk_pat_revocation_poll_s` 주기로 대조한다(plan §8.2.7 '폐기 대조')."""
        if self.store is None or self.settings is None:
            return
        period = float(getattr(self.settings, "risk_pat_revocation_poll_s", 0) or 0)
        if period <= 0:
            return
        now = time.time()
        if now - self._last_revocation_poll < period:
            return
        self._last_revocation_poll = now
        poll_revoked_pats(self.store, self.settings)

    def _panel_tick(self) -> None:
        """잡 1건을 집어 패널 1건을 돌릴 워커를 띄운다(세마포어 risk_concurrency, 타깃당 직렬)."""
        if self.store is None or self.settings is None or self.engine is None or self._stop.is_set():
            return
        self._workers = [t for t in self._workers if t.is_alive()]
        if not self._sem.acquire(blocking=False):
            return
        started = False
        try:
            job = claim_next_job(self.store, self.settings)
            if job is None:
                return
            worker = threading.Thread(
                target=self._run_worker, args=(job,), name=f"panel-{str(job['id'])[:8]}", daemon=True
            )
            started = True
            worker.start()
            self._workers.append(worker)
        finally:
            if not started:
                self._sem.release()

    def _run_worker(self, job: Mapping[str, Any]) -> None:
        try:
            run_panel(
                self.store, self.settings, self.engine, job,
                narrative_mod=self.narrative_mod, registry_mod=self.registry_mod, stop=self._stop,
            )
        except Exception:  # noqa: BLE001 — 잡 하나의 실패로 러너가 멈추지 않는다.
            log.exception("패널 실행 실패(job=%s)", job.get("id"))
        finally:
            self._sem.release()

    # ------------------------------------------------------------ 수명
    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        if self.store is not None:
            try:
                recover_running_panels(self.store)
            except Exception:  # noqa: BLE001 — 복구 실패가 기동을 막지 않는다.
                log.exception("재기동 복구 실패")
        for name, interval in _LOOPS:
            t = threading.Thread(target=self._loop, args=(name, interval), name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        """Event 를 세우고 스레드당 최대 2 s(패널 워커는 5 s)만 join 한다."""
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2.0)
        for t in self._workers:
            t.join(timeout=5.0)
        self._threads = []
        self._workers = [t for t in self._workers if t.is_alive()]

    def status(self) -> dict:
        """{threads: [{name, alive, last_tick}]} — /api/health 에는 싣지 않는다(형식 고정)."""
        alive = {t.name: t.is_alive() for t in self._threads}
        return {
            "threads": [
                {"name": name, "alive": alive.get(name, False), "last_tick": self._last_tick[name]}
                for name, _ in _LOOPS
            ]
        }
