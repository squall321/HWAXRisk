# 카드 대조 검토의 셀 원장 — 상태기계·격자·선점·호출 결과 쓰기·정산·복구·불변식·요약(재설계 M2 · m2-wp3b S5)
"""격자는 늘 로스터 전원 × 활성 빌드의 검토 대상 단위다(X1-27). 범위는 셀을 덜 만드는 것이 아니라 덜 집는 것이다 — 잡을
만들 때 범위 안의 `pending` 셀과 그 전문가 머리에 잡 id(`run_id`)를 찍고(`assign_scope`), 선점은 그 잡 id 가 찍힌 것만 본다.

- 셀·전문가의 상태 전이는 전부 `_move` 를 지난다. 표에 없는 전이는 `IllegalTransition` 이다. `skipped` 는 `failed` 에서만 간다.
- 쓰기는 선점(`lease_owner = '<boot_id>:<uuid>'`, 선점마다 새 값)을 대조한다. 재기동 복구나 과제 폐기가 선점을 지운 뒤 늦게
  끝난 호출의 쓰기는 아무것도 바꾸지 않는다(m-10).
- 이 모듈은 엔진을 부르지 않는다. 트랜잭션은 호출 앞(선점)과 뒤(결과)에만 짧게 연다.
- 검토가 도는 동안 `rr_coverage` 는 `pending` 그대로다(`planner.check_invariants` 가 그대로 통과한다). 원장을 닫는 것은
  `planner.close_review_seat` 하나다.
"""
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app import planner, review_ops, review_verify, runner, units
from app.common import new_uuid, now_epoch, sha256_hex
from app.errors import AppError

# ---------------------------------------------------------------- 어휘와 전이표
CELL_STATES: tuple[str, ...] = ("pending", "running", "reviewed", "na_irrelevant", "no_input", "failed", "skipped")
OPEN_CELL_STATES: tuple[str, ...] = ("pending", "running")
# M2 가 쓰는 전이만 적는다. na_irrelevant·no_input 은 어휘만 있다(거르기·입력 결손 호출은 M3·M4).
CELL_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("pending", "running"),      # 워커가 셀의 첫 호출을 시작한다(start_cell — 선점 대조)
    ("running", "reviewed"),     # 정산 성공(settle_cell)
    ("running", "pending"),      # 인프라·잡 보류·취소·재기동·한도 미만 내용 탓 — 기다림은 셀을 놓지 않는다
    ("running", "failed"),       # 내용 탓 한도·호출 수 상한
    ("pending", "failed"),       # 카드 묶음 한도 초과·agent_not_found(fail_open_cells)
    ("failed", "skipped"),       # 사람의 넘김(처분 REST 는 M3) — skipped 는 failed 에서만 간다(PLAN 4절 C-18)
})
EXPERT_STATES: tuple[str, ...] = ("planned", "running", "ready", "partial", "blocked")
EXPERT_TRANSITIONS: frozenset[tuple[str, str]] = frozenset({
    ("planned", "running"),      # 선점(claim_next_expert)
    ("running", "planned"),      # 놓음(release_expert · 재기동 복구)
    ("running", "ready"),        # 마감 — 열린 실패도 0(S9)
    ("running", "partial"),      # 마감 — 열린 실패나 범위 밖 pending 이 남았다(P-04, S9)
    ("ready", "planned"),        # 새 잡의 범위가 남은 셀을 다시 연다(assign_scope)
    ("partial", "planned"),
    ("planned", "blocked"),      # 카드 묶음을 끝내 못 받았다
    ("running", "blocked"),      # 묶음 받기는 워커 자리에서 한다(m-04) — 쥔 채로 막힌다
    ("blocked", "planned"),      # 새 잡이 다시 받게 한다(assign_scope)
})
_MACHINES: dict[str, tuple[str, frozenset[tuple[str, str]]]] = {
    "cell": ("rr_review_cells", CELL_TRANSITIONS),
    "expert": ("rr_expert_reports", EXPERT_TRANSITIONS),
}
CELL_BASES: tuple[str, ...] = ("cards", "background", "role_only")   # reviewed 셀을 무엇으로 봤나(X1-04)
CALL_FINAL_STATES: tuple[str, ...] = ("ok", "infra_fail", "content_fail", "aborted")
RESTART_CODE = "restart"

# 셀이 정산에서 내용 탓으로 끝날 때의 코드(앱이 낸다 — review_ops 표 밖이라 내용 탓이다).
SETTLE_CARDS_UNJUDGED = "cards_unjudged"
SETTLE_TRUNCATED = "output_truncated"
SETTLE_SAMPLES = "samples_incomplete"
SETTLE_OFFCARD = "offcard_incomplete"

# 호출 결과·정산이 고칠 수 있는 열 — 상태·선점·신원·잡 결속은 이 모듈의 함수만 바꾼다.
_CELL_PROTECTED = frozenset({"target_key", "unit_id", "agent_key", "owner_sub", "state", "lease_owner", "run_id",
                             "created_at", "updated_at", "started_at", "finished_at", "reopened_n", "tries", "charged",
                             "infra_streak"})
_HEAD_PROTECTED = frozenset({"target_key", "agent_key", "owner_sub", "state", "lease_owner", "run_id", "review_id",
                             "claimed_at", "created_at", "updated_at"})
# 입력이 바뀐 셀을 처음부터 돌릴 때 비우는 값(start_cell).
_CELL_RESET: dict[str, Any] = {
    "tries": 0, "charged": 0, "infra_streak": 0, "not_before": None, "error_code": None, "error_class": None,
    "error": None, "knob": None, "llm_calls": 0, "tokens_in": None, "tokens_out": None, "elapsed_ms": None,
    "truncated": None, "rows_expected": None, "rows_missing": None, "stamp": 0, "soft_over": 0, "basis": None,
    "cards_expected": None, "cards_judged": None, "n_fail": 0, "n_warning": 0, "n_ok": 0, "n_na": 0,
    "n_undetermined": 0, "n_disputed": 0, "n_flipped": 0, "n_offcard": 0, "offcard_state": "todo",
    "offcard_capped": 0, "quote_ok": 0, "quote_n": 0, "refs_ok": 0, "refs_n": 0, "bg_full_n": 0, "bg_title_only_n": 0,
    "route": None, "route_forced": None, "route_json": None, "extras_json": None, "mechs_json": None,
    "handoffs_json": None, "sample_json": None, "model": None, "credential_kind": None,
}


class IllegalTransition(ValueError):
    """전이표에 없는 상태 전이 — 코드의 결함이다(사람에게 돌려줄 오류가 아니다)."""


class Expr(str):
    """`_move` 의 SET 에 그대로 들어가는 SQL 식(예 `Expr('reopened_n + 1')`). 인자를 받지 않는다."""


class _LeaseLost(Exception):
    """트랜잭션 안에서 선점을 잃은 것을 알았다 — 이미 쓴 것을 되돌리고 '쓰지 않았다' 로 끝낸다."""


# ---------------------------------------------------------------- 전이
def _move(store: Any, kind: str, src: str | Sequence[str], dst: str, *, where: str, params: Sequence[Any] = (),
          sets: Mapping[str, Any] | None = None, now: int | None = None) -> int:
    """셀(`kind='cell'`)·전문가(`'expert'`)의 상태를 `src` → `dst` 로 옮기고 바뀐 행 수를 돌려준다.

    표에 없는 전이는 DB 를 보기 전에 `IllegalTransition` 이다. `where` 는 상태 조건 뒤에 AND 로 붙는다 — 선점 대조
    (`lease_owner = ?`)도 여기에 적는다. 바뀐 행이 0 이면 그 행은 이미 다른 상태이거나 선점을 잃었다.
    """
    table, allowed = _MACHINES[kind]
    sources = (src,) if isinstance(src, str) else tuple(src)
    illegal = [s for s in sources if (s, dst) not in allowed]
    if not sources or illegal:
        raise IllegalTransition(f"{kind} 의 {', '.join(illegal or ['(없음)'])} → {dst} 는 허용 전이가 아니다")
    values = {"state": dst, "updated_at": now_epoch() if now is None else now, **dict(sets or {})}
    assigns: list[str] = []
    args: list[Any] = []
    for column, value in values.items():
        if isinstance(value, Expr):
            assigns.append(f"{column} = {value}")
        else:
            assigns.append(f"{column} = ?")
            args.append(value)
    sql = (f"UPDATE {table} SET {', '.join(assigns)} WHERE state IN ({','.join('?' * len(sources))}) AND ({where})")
    return int(store.execute(sql, (*args, *sources, *params)) or 0)


# ---------------------------------------------------------------- 정체·해시
def review_id_of(target_key: str, agent_key: str) -> str:
    """(타깃 × 전문가) 검토의 합성 id(hex32) — 의견 행의 panel_id 자리와 claim_uid 머리에 쓴다(seat_opinion.v1 은 hex32)."""
    return sha256_hex(f"review|{target_key}|{agent_key}")[:32]


def cell_input_hash(*, unit_hash: str | None, evidence_sha: str | None, pack_hash: str | None,
                    prompt_rev: str | None, limits_rev: str | None) -> str:
    """셀 입력의 지문 — `unit_hash | evidence_sha | pack_hash | prompt_rev | limits_rev`(M2.md 4.6.1). 하나라도 바뀌면 그 셀은
    처음부터 돈다(start_cell)."""
    parts = (unit_hash, evidence_sha, pack_hash, prompt_rev, limits_rev)
    return sha256_hex("|".join("" if p is None else str(p) for p in parts))[:16]


def _cell_where() -> str:
    return "target_key = ? AND unit_id = ? AND agent_key = ?"


def _head_where() -> str:
    return "target_key = ? AND agent_key = ?"


def _columns(store: Any, table: str) -> frozenset[str]:
    return frozenset(r["name"] for r in store.query(f"PRAGMA table_info({table})"))


def _checked(store: Any, table: str, values: Mapping[str, Any], protected: Iterable[str] = ()) -> dict:
    """표에 있는 열이고 보호 열이 아닌가 — 모르는 열 이름은 조용히 버리지 않고 ValueError 다."""
    known = _columns(store, table)
    unknown = sorted(set(values) - known)
    banned = sorted(set(values) & set(protected))
    if unknown or banned:
        raise ValueError(f"{table} 에 쓸 수 없는 열 — 모름 {unknown}, 이 함수가 다루지 않는 열 {banned}")
    return dict(values)


def active_unit_ids(store: Any, target_key: str) -> list[str]:
    """활성 빌드의 검토 대상 단위 id(seq 순). 활성 빌드가 없으면 빈 목록이다."""
    return [u["unit_id"] for u in units.load_units(store, target_key, reviewable_only=True)]


# ---------------------------------------------------------------- 격자
def plan_cells(store: Any, target_key: str, *, now: int | None = None) -> dict:
    """로스터 전원(`planner.review_order`) × 활성 빌드의 검토 대상 단위의 셀과 전문가 머리를 INSERT OR IGNORE 로 만든다(멱등).

    입력 결손 전문가·`deferred` 좌석도 격자에 든다 — 격자의 분모는 늘 로스터 × 검토 대상 단위다(X1-27). 머리의 사본(영역 ·
    순위 · tier · 순서 · 셀 수)은 다시 부를 때 지금 값으로 맞춘다. 활성 빌드에 없는 단위의 `pending` 셀은 지우고(종결 셀은 남되
    집계에서 빠진다), 반환은 {experts, units, heads_new, cells_new, cells_total, cells_dropped} 다.
    """
    now = now_epoch() if now is None else now
    target = store.query_one("SELECT owner_sub FROM rr_targets WHERE target_key = ?", (target_key,))
    if target is None:
        raise AppError("E404", f"타깃이 없습니다 — {target_key}.", 404)
    owner = target["owner_sub"]
    order = planner.review_order(store, target_key)
    unit_rows = units.load_units(store, target_key, reviewable_only=True)
    unit_ids = {u["unit_id"] for u in unit_rows}
    with store.tx():
        heads_new = 0
        for row in order:
            heads_new += int(store.execute(
                "INSERT OR IGNORE INTO rr_expert_reports(target_key, agent_key, owner_sub, domain, rank_in_domain, tier,"
                " review_order, review_id, state, cells_total, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?)",
                (target_key, row["agent_key"], owner, row["domain"], row["rank_in_domain"], row["tier"], row["order"],
                 review_id_of(target_key, row["agent_key"]), len(unit_rows), now, now)) or 0)
            store.execute(
                "UPDATE rr_expert_reports SET domain = ?, rank_in_domain = ?, tier = ?, review_order = ?, cells_total = ?"
                " WHERE target_key = ? AND agent_key = ? AND NOT (domain IS ? AND rank_in_domain IS ? AND tier IS ?"
                " AND review_order IS ? AND cells_total IS ?)",
                (row["domain"], row["rank_in_domain"], row["tier"], row["order"], len(unit_rows), target_key,
                 row["agent_key"], row["domain"], row["rank_in_domain"], row["tier"], row["order"], len(unit_rows)))
        cells_new = int(store.executemany(
            "INSERT OR IGNORE INTO rr_review_cells(target_key, unit_id, agent_key, owner_sub, domain, unit_seq, state,"
            " unit_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            [(target_key, unit["unit_id"], row["agent_key"], owner, row["domain"], unit["seq"], unit["unit_hash"], now, now)
             for row in order for unit in unit_rows]) or 0)
        stale = [r["unit_id"] for r in store.query(
            "SELECT DISTINCT unit_id FROM rr_review_cells WHERE target_key = ? AND state = 'pending'", (target_key,))
            if r["unit_id"] not in unit_ids]
        dropped = int(store.executemany(
            "DELETE FROM rr_review_cells WHERE target_key = ? AND unit_id = ? AND state = 'pending'",
            [(target_key, uid) for uid in stale]) or 0) if stale else 0
    return {"experts": len(order), "units": len(unit_rows), "heads_new": heads_new, "cells_new": cells_new,
            "cells_total": len(order) * len(unit_rows), "cells_dropped": dropped}


def assign_scope(store: Any, target_key: str, run_id: str, *, agents: Sequence[str], unit_ids: Sequence[str],
                 now: int | None = None) -> dict:
    """검토 잡의 범위를 원장에 찍는다 — 범위 안 `pending` 셀과 범위 안 전문가 머리의 `run_id` 를 그 잡 id 로 둔다.

    범위 안에 `pending` 셀이 남은 전문가가 `ready`·`partial`·`blocked` 이면 `planned` 로 다시 연다(새 잡이 그 셀을 집게 —
    `blocked` 는 묶음을 다시 받게 묶음 시도 수와 백오프를 비운다). 범위 밖 셀은 손대지 않는다(앞 잡의 `run_id` 가 남는다).
    반환 {cells, experts, reopened}.
    """
    now = now_epoch() if now is None else now
    with store.tx():
        cells = int(store.executemany(
            "UPDATE rr_review_cells SET run_id = ?, updated_at = ? WHERE target_key = ? AND unit_id = ? AND agent_key = ?"
            " AND state = 'pending'",
            [(run_id, now, target_key, uid, agent) for agent in agents for uid in unit_ids]) or 0)
        heads = int(store.executemany(
            "UPDATE rr_expert_reports SET run_id = ?, updated_at = ? WHERE target_key = ? AND agent_key = ?",
            [(run_id, now, target_key, agent) for agent in agents]) or 0)
        reopened = 0
        for agent in agents:
            has_open = store.query_one(
                "SELECT 1 FROM rr_review_cells WHERE target_key = ? AND agent_key = ? AND run_id = ? AND state = 'pending'"
                " LIMIT 1", (target_key, agent, run_id))
            if has_open is None:
                continue
            reopened += _reopen(store, target_key, agent, now=now)
    return {"cells": cells, "experts": heads, "reopened": reopened}


def _reopen(store: Any, target_key: str, agent_key: str, *, now: int) -> int:
    """범위 안에 pending 셀이 생긴 전문가를 다시 연다 — ready·partial 은 planned 로, blocked 는 묶음 시도 수와 백오프를 비우고
    planned 로. 옮긴 머리 수."""
    return (_move(store, "expert", ("ready", "partial"), "planned", where=_head_where(), params=(target_key, agent_key),
                  now=now)
            + _move(store, "expert", "blocked", "planned", where=_head_where(), params=(target_key, agent_key),
                    sets={"pack_attempts": 0, "not_before": None}, now=now))


def adopt_released(store: Any, job_id: str, *, now: int | None = None) -> int:
    """살아 있는 검토 잡이 제 범위 안에서 '죽은 잡의 표지' 를 단 채 놓인 pending 셀을 거둔다(반대 검토 R3A-1).

    `assign_scope` 는 잡을 만드는 순간의 pending 셀만 찍는다 — 그때 다른 잡의 워커가 쥐고 있던(running) 셀은 옛 잡 id 를 단 채
    나중에 pending 으로 놓이고, 선점·완료 셈이 그 잡 id 의 셀만 보므로 아무도 집지 않는다(새 잡이 호출 0회로 completed). 그런
    셀(run_id 가 없거나 살아 있지 않은 잡의 것)을 이 잡의 범위 — 이 잡이 찍은 전문가(머리 run_id) × 잡 범위의 unit_ids(없으면
    전부) — 안에서 이 잡 id 로 찍고, 그 전문가가 ready·partial·blocked 면 다시 연다. 범위 밖 셀은 손대지 않는다. 거둔 셀 수.
    """
    now = now_epoch() if now is None else now
    job = store.query_one("SELECT target_key, params_json, state FROM rr_jobs WHERE id = ? AND mode = 'reviews'", (job_id,))
    if job is None or job["state"] not in runner.LIVE_JOB_STATES:
        return 0
    try:
        scope = (json.loads(job["params_json"] or "{}").get("scope") or {})
    except (TypeError, ValueError, AttributeError):
        scope = {}
    units_in = set(scope.get("unit_ids") or ()) if isinstance(scope, Mapping) else set()
    target_key = job["target_key"]
    marks = ",".join("?" * len(runner.LIVE_JOB_STATES))
    with store.tx():
        rows = [dict(r) for r in store.query(
            "SELECT c.unit_id, c.agent_key FROM rr_review_cells c JOIN rr_expert_reports e"
            " ON e.target_key = c.target_key AND e.agent_key = c.agent_key"
            " WHERE c.target_key = ? AND e.run_id = ? AND c.state = 'pending' AND (c.run_id IS NULL OR c.run_id NOT IN"
            f" (SELECT id FROM rr_jobs WHERE mode = 'reviews' AND state IN ({marks})))",
            (target_key, job_id, *runner.LIVE_JOB_STATES))]
        rows = [r for r in rows if not units_in or r["unit_id"] in units_in]
        if not rows:
            return 0
        adopted = int(store.executemany(
            "UPDATE rr_review_cells SET run_id = ?, updated_at = ? WHERE target_key = ? AND unit_id = ? AND agent_key = ?"
            " AND state = 'pending'", [(job_id, now, target_key, r["unit_id"], r["agent_key"]) for r in rows]) or 0)
        for agent in sorted({r["agent_key"] for r in rows}):
            _reopen(store, target_key, agent, now=now)
    return adopted


# ---------------------------------------------------------------- 선점
def _live_review_jobs(store: Any) -> list[dict]:
    """돌 수 있는 검토 잡 — 도는 전문가가 가장 적은 잡부터, 같으면 먼저 만든 잡부터(P-09)."""
    rows = store.query(
        "SELECT j.id, j.target_key, j.state, (SELECT COUNT(*) FROM rr_expert_reports e WHERE e.run_id = j.id"
        " AND e.state = 'running') AS running_n FROM rr_jobs j WHERE j.mode = 'reviews' AND j.state = 'running'"
        " ORDER BY running_n ASC, j.created_at ASC, j.id ASC")
    return [dict(r) for r in rows]


def _head(store: Any, target_key: str, agent_key: str) -> dict | None:
    row = store.query_one("SELECT * FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?",
                          (target_key, agent_key))
    return dict(row) if row is not None else None


def claim_next_expert(store: Any, job: Mapping[str, Any] | None = None, *, boot_id: str, now: int | None = None,
                      purpose: str = "review") -> dict | None:
    """전문가 한 명을 쥔다 — 쥔 머리(dict, `lease_owner` 포함) 또는 None.

    `purpose='review'` 는 카드 묶음이 `ok`·`empty` 이고 백오프가 지난 범위 안 `pending` 셀이 있는 전문가, `'pack'` 은 묶음이
    `todo`·`error` 이고 범위 안 `pending` 셀이 있는 전문가다(묶음 받기도 워커 자리에서 한다 — m-04). `'finalize'` 는 범위 안 셀이
    다 닫혔는데 마감되지 않은 전문가다(마감 도중 결함·재기동 — 마감은 머리를 ready·partial 로 옮기므로 planned 로 남은 것이 그것이다).
    마감은 닫힌 셀이 이 잡의 것이기를 요구하지 않는다 — 앞 잡에서 셀을 다 닫고 마감 전에 멈춘(재기동·취소) 전문가를 다음 잡이
    범위에 넣으면 그 잡이 마감한다(R3A-1, 머리의 run_id 가 이 잡이면 그 잡의 범위다).
    셋 다 `planned` 이고 머리의 백오프(`not_before`)가 지났어야 한다. 순서는 `review_order`(Tier A → B → C).
    `job` 을 주지 않으면 도는(`running`) 검토 잡을 돌아가며 — 도는 전문가가 가장 적은 잡부터 — 집는다(P-09). `job` 을 주어도
    그 잡이 지금 `running` 인 검토 잡이 아니면 None 이다. 선점은 `planned` 조건이 붙은 UPDATE 의 바뀐 행이 1 일 때만 선다.
    """
    if purpose not in ("review", "pack", "finalize"):
        raise ValueError(f"모르는 선점 목적 — {purpose!r}")
    now = now_epoch() if now is None else now
    lease = f"{boot_id}:{new_uuid()}"
    pack_cond = "e.pack_status IN ('todo', 'error')" if purpose == "pack" else "e.pack_status IN ('ok', 'empty')"
    cell_cond = " AND (c.not_before IS NULL OR c.not_before <= ?)" if purpose == "review" else ""
    cells_cond = (" AND EXISTS (SELECT 1 FROM rr_review_cells c WHERE c.target_key = e.target_key AND c.agent_key = e.agent_key"
                  f" AND c.run_id = e.run_id AND c.state = 'pending'{cell_cond})")
    if purpose == "finalize":
        cells_cond = (" AND NOT EXISTS (SELECT 1 FROM rr_review_cells c WHERE c.target_key = e.target_key"
                      " AND c.agent_key = e.agent_key AND c.run_id = e.run_id AND c.state IN ('pending', 'running'))")
    with store.tx():
        if job is None:
            jobs = _live_review_jobs(store)
        else:
            row = store.query_one("SELECT id, target_key FROM rr_jobs WHERE id = ? AND mode = 'reviews'"
                                  " AND state = 'running'", (job["id"],))
            jobs = [dict(row)] if row is not None else []
        for item in jobs:
            params: list[Any] = [item["target_key"], item["id"], now]
            if purpose == "review":
                params.append(now)
            candidates = store.query(
                "SELECT e.agent_key FROM rr_expert_reports e WHERE e.target_key = ? AND e.run_id = ?"
                f" AND e.state = 'planned' AND (e.not_before IS NULL OR e.not_before <= ?) AND {pack_cond}{cells_cond}"
                " ORDER BY e.review_order ASC, e.agent_key ASC", params)
            for cand in candidates:
                moved = _move(store, "expert", "planned", "running", where=f"{_head_where()} AND run_id = ?",
                              params=(item["target_key"], cand["agent_key"], item["id"]),
                              sets={"lease_owner": lease, "claimed_at": now, "error": None}, now=now)
                if moved == 1:
                    return _head(store, item["target_key"], cand["agent_key"])
    return None


def _holds(store: Any, target_key: str, agent_key: str, lease_owner: str) -> bool:
    """그 선점이 아직 그 전문가를 쥐고 있나(running · 같은 lease_owner)."""
    row = store.query_one("SELECT 1 FROM rr_expert_reports WHERE target_key = ? AND agent_key = ? AND state = 'running'"
                          " AND lease_owner = ?", (target_key, agent_key, lease_owner))
    return row is not None


def release_expert(store: Any, target_key: str, agent_key: str, *, lease_owner: str, not_before: int | None = None,
                   error: str | None = None, now: int | None = None) -> dict:
    """쥔 전문가를 놓는다(running → planned). 그 선점으로 도는 셀은 차감 없이 `pending` 으로 돌아간다.

    `not_before` 는 머리의 백오프(그 전에는 다시 집지 않는다), `error` 는 놓은 까닭이다. 선점을 이미 잃었으면 아무것도 바꾸지
    않는다 — {released: False, cells: 0}.
    """
    now = now_epoch() if now is None else now
    with store.tx():
        head = _move(store, "expert", "running", "planned", where=f"{_head_where()} AND lease_owner = ?",
                     params=(target_key, agent_key, lease_owner),
                     sets={"lease_owner": None, "not_before": not_before, "error": error}, now=now)
        if not head:
            return {"released": False, "cells": 0}
        cells = _move(store, "cell", "running", "pending", where="target_key = ? AND agent_key = ? AND lease_owner = ?",
                      params=(target_key, agent_key, lease_owner), sets={"lease_owner": None, "heartbeat_at": None},
                      now=now)
    return {"released": True, "cells": cells}


def write_head(store: Any, target_key: str, agent_key: str, *, lease_owner: str, sets: Mapping[str, Any],
               now: int | None = None) -> bool:
    """쥔 전문가 머리에 호출이 아닌 일의 결과(계획·창 판·묶음 확인 셈 따위)를 적는다 — 상태·선점·신원·잡 결속은 받지 않는다.
    선점을 잃었으면 쓰지 않고 False 다(m-10)."""
    values = _checked(store, "rr_expert_reports", sets, _HEAD_PROTECTED)
    if not values:
        return _holds(store, target_key, agent_key, lease_owner)
    now = now_epoch() if now is None else now
    return bool(store.execute(
        f"UPDATE rr_expert_reports SET {', '.join(f'{c} = ?' for c in values)}, updated_at = ?"
        f" WHERE {_head_where()} AND state = 'running' AND lease_owner = ?",
        (*values.values(), now, target_key, agent_key, lease_owner)))


def block_expert(store: Any, target_key: str, agent_key: str, *, lease_owner: str, error: str | None = None,
                 now: int | None = None) -> bool:
    """카드 묶음을 끝내 받지 못한 전문가를 쥔 채로 막는다(running → blocked, 선점을 지운다). 그 셀은 부른 쪽이 먼저
    `fail_open_cells` 로 닫는다. 선점을 잃었으면 False 다."""
    now = now_epoch() if now is None else now
    return bool(_move(store, "expert", "running", "blocked", where=f"{_head_where()} AND lease_owner = ?",
                      params=(target_key, agent_key, lease_owner), sets={"lease_owner": None, "error": error}, now=now))


def closing_state(tally: Mapping[str, Any]) -> str:
    """마감이 머리에 적는 상태 — 열린 실패 셀이나 범위 밖 pending 이 남았으면 partial, 아니면 ready(P-04). 보고서가 같은 값을 싣는다."""
    return "partial" if tally["failed"] or tally["open"] else "ready"


def close_expert(store: Any, target_key: str, agent_key: str, *, lease_owner: str, now: int | None = None) -> str | None:
    """쥔 전문가의 검토를 마감한다 — `closing_state` 로 partial 또는 ready. 옮긴 상태 또는 None(선점을 잃었다). 승격·의견·원장·
    보고서(S9·S10)는 `review_runner.finalize_expert` 가 같은 트랜잭션에서 이 앞에 쓴다."""
    now = now_epoch() if now is None else now
    dst = closing_state(expert_tally(store, target_key, agent_key))
    moved = _move(store, "expert", "running", dst, where=f"{_head_where()} AND lease_owner = ?",
                  params=(target_key, agent_key, lease_owner), sets={"lease_owner": None, "error": None}, now=now)
    return dst if moved else None


def record_pack(store: Any, target_key: str, agent_key: str, *, lease_owner: str, status: str,
                pack_hash: str | None = None, card_basis: str | None = None, error: str | None = None,
                not_before: int | None = None, now: int | None = None) -> bool:
    """쥔 전문가 머리에 카드 묶음 결과를 적는다 — `cardpack.judge_pack` 의 status(ok·empty·error)와 얼린 묶음(`freeze_pack`
    의 pack_hash·card_basis). error 는 시도 수를 하나 올리고 `not_before` 를 그 머리의 백오프로 둔다(값은 부른 쪽이 정한다 —
    `review_ops.pack_retry_s`). 선점을 잃었으면 쓰지 않고 False 다. 상태(planned·running)는 바꾸지 않는다."""
    if status not in ("ok", "empty", "error"):
        raise ValueError(f"모르는 묶음 상태 — {status!r}")
    now = now_epoch() if now is None else now
    if status == "error":
        sql = ("UPDATE rr_expert_reports SET pack_status = 'error', pack_error = ?, pack_attempts = pack_attempts + 1,"
               " not_before = ?, updated_at = ? WHERE target_key = ? AND agent_key = ? AND state = 'running'"
               " AND lease_owner = ?")
        params: tuple = (error or "pack_error", not_before, now, target_key, agent_key, lease_owner)
    else:
        if not pack_hash:
            raise ValueError("ok·empty 묶음에는 얼린 pack_hash 가 있어야 한다")
        sql = ("UPDATE rr_expert_reports SET pack_status = ?, pack_hash = ?, card_basis = ?, pack_error = NULL,"
               " pack_attempts = 0, pack_frozen_at = ?, not_before = NULL, updated_at = ?"
               " WHERE target_key = ? AND agent_key = ? AND state = 'running' AND lease_owner = ?")
        params = (status, pack_hash, card_basis, now, now, target_key, agent_key, lease_owner)
    return bool(store.execute(sql, params))


# ---------------------------------------------------------------- 셀 하나의 일생
def _cell(store: Any, target_key: str, unit_id: str, agent_key: str) -> dict | None:
    row = store.query_one(f"SELECT * FROM rr_review_cells WHERE {_cell_where()}", (target_key, unit_id, agent_key))
    return dict(row) if row is not None else None


def start_cell(store: Any, target_key: str, unit_id: str, agent_key: str, *, lease_owner: str, input_hash: str,
               pack_hash: str | None = None, prompt_rev: str | None = None, verify_rev: str | None = None,
               now: int | None = None) -> dict | None:
    """쥔 전문가의 `pending` 셀 하나를 시작한다(pending → running, 셀에도 같은 선점을 찍는다). 시작한 셀(dict) 또는 None.

    저장된 `input_hash` 가 있고 지금 값과 다르면 그 셀의 판정 행을 지우고 셈을 비운 뒤 처음부터 돈다(`reopened_n + 1`) —
    단위·근거·카드 묶음·프롬프트 판·창 판 가운데 하나가 바뀌었다(M2.md 4.6.1). 앞 입력의 호출 원장 행은 이력으로 남는다.
    """
    now = now_epoch() if now is None else now
    key = (target_key, unit_id, agent_key)
    with store.tx():
        if not _holds(store, target_key, agent_key, lease_owner):
            return None
        row = _cell(store, *key)
        if row is None or row["state"] != "pending":
            return None
        sets: dict[str, Any] = {"lease_owner": lease_owner, "heartbeat_at": now, "input_hash": input_hash,
                                "pack_hash": pack_hash, "prompt_rev": prompt_rev, "verify_rev": verify_rev,
                                "started_at": row["started_at"] or now, "finished_at": None}
        if row["input_hash"] is not None and row["input_hash"] != input_hash:
            store.execute(f"DELETE FROM rr_card_verdicts WHERE {_cell_where()}", key)
            sets.update(_CELL_RESET, reopened_n=Expr("reopened_n + 1"), started_at=now)
        if _move(store, "cell", "pending", "running", where=_cell_where(), params=key, sets=sets, now=now) != 1:
            return None
        return _cell(store, *key)


# 새 시도(내용 탓으로 다시 도는 셀)를 시작할 때 비우는 판정 셈 — 호출 수·차감·토큰 같은 누적 비용은 남긴다.
_ATTEMPT_RESET: dict[str, Any] = {
    "truncated": None, "rows_expected": None, "rows_missing": None, "stamp": 0, "soft_over": 0, "basis": None,
    "cards_expected": None, "cards_judged": None, "n_fail": 0, "n_warning": 0, "n_ok": 0, "n_na": 0,
    "n_undetermined": 0, "n_disputed": 0, "n_flipped": 0, "n_offcard": 0, "offcard_state": "todo", "offcard_capped": 0,
    "quote_ok": 0, "quote_n": 0, "refs_ok": 0, "refs_n": 0, "bg_full_n": 0, "bg_title_only_n": 0,
    "extras_json": None, "mechs_json": None, "handoffs_json": None,
}


def begin_attempt(store: Any, target_key: str, unit_id: str, agent_key: str, *, lease_owner: str,
                  now: int | None = None) -> dict | None:
    """도는 셀의 시도 표지(`sample_json.attempt` = 지금 `charged`)를 맞춘다 — 표지가 다르면 내용 탓 실패 뒤의 새 시도라 그 셀의
    판정 행과 판정 셈을 비우고 표지를 적는다(앞 시도의 단독 재질의 행이 새 시도의 실효를 덮지 않게). 같으면 아무것도 하지 않는다
    (재기동·인프라 실패 뒤 같은 시도를 이어 돈다 — 끝난 호출의 판정이 남는다). 반환은 그 셀(dict) 또는 None(선점을 잃었다)."""
    now = now_epoch() if now is None else now
    key = (target_key, unit_id, agent_key)
    with store.tx():
        row = _cell(store, *key)
        if row is None or row["state"] != "running" or row["lease_owner"] != lease_owner:
            return None
        try:
            marker = json.loads(row["sample_json"] or "null")
        except ValueError:
            marker = None
        marker = marker if isinstance(marker, dict) else {}
        attempt = int(row["charged"] or 0)
        if marker.get("attempt") == attempt:
            return row
        store.execute(f"DELETE FROM rr_card_verdicts WHERE {_cell_where()}", key)
        store.execute(f"UPDATE rr_review_cells SET {', '.join(_assign(_ATTEMPT_RESET))}, sample_json = ?, updated_at = ?"
                      f" WHERE {_cell_where()} AND lease_owner = ?",
                      (*_args(_ATTEMPT_RESET), json.dumps({**marker, "attempt": attempt}, sort_keys=True), now, *key,
                       lease_owner))
        return _cell(store, *key)


def begin_call(store: Any, target_key: str, agent_key: str, *, lease_owner: str, call: Mapping[str, Any],
               now: int | None = None) -> bool:
    """호출을 내기 직전에 호출 원장에 `running` 행을 둔다 — 재기동 복구가 그 호출을 `aborted('restart')` 로 닫을 수 있게.
    `call` 은 `rr_review_calls` 열 이름의 dict 이고 `call_id`·`kind` 가 있어야 한다. 선점을 잃었으면 쓰지 않고 False 다."""
    now = now_epoch() if now is None else now
    values = _checked(store, "rr_review_calls", call)
    if not values.get("call_id") or not values.get("kind"):
        raise ValueError("호출 원장 행에는 call_id·kind 가 있어야 한다")
    with store.tx():
        head = _head(store, target_key, agent_key)
        if head is None or head["state"] != "running" or head["lease_owner"] != lease_owner:
            return False
        row = {**values, "target_key": target_key, "agent_key": agent_key, "owner_sub": head["owner_sub"],
               "run_id": values.get("run_id") or head["run_id"], "state": "running",
               "started_at": values.get("started_at") or now}
        store.execute(f"INSERT OR REPLACE INTO rr_review_calls({', '.join(row)}) VALUES ({','.join('?' * len(row))})",
                      tuple(row.values()))
    return True


def _rewrite_effective(store: Any, key: tuple[str, str, str], *, now: int | None = None) -> dict:
    """그 셀의 판정 행 전부에서 실효를 다시 고르고(`review_verify.mark_effective`) 셀의 판정 셈을 맞춘다. 셈 dict 를 돌려준다.

    고쳐 쓴 행은 `updated_at` 을 같이 올린다 — since 반출이 `updated_at` → `created_at` 순으로 보므로 올리지 않으면 실효·일치·갈림의
    고침이 반출에서 빠진다(tests/rr/test_v4_rows.py 의 소스 가드)."""
    rows = [dict(r) for r in store.query(
        "SELECT record_id, variant, applies, judgement, cq, quote_ok, refs_ok FROM rr_card_verdicts"
        f" WHERE {_cell_where()}", key)]
    if not rows:
        return {}
    marked = review_verify.mark_effective(rows)
    stamp = now_epoch() if now is None else now
    store.executemany(
        f"UPDATE rr_card_verdicts SET is_effective = ?, agree = ?, split = ?, updated_at = ? WHERE {_cell_where()}"
        " AND record_id = ? AND variant = ?",
        [(r["is_effective"], r["agree"], r["split"], stamp, *key, r["record_id"], r["variant"]) for r in marked])
    effective = [r for r in marked if r["is_effective"]]
    tally = review_verify.cell_tally(review_verify.effective_rows(rows))
    tally.update({
        "quote_ok": sum(1 for r in effective if r["quote_ok"] == 1),
        "quote_n": sum(1 for r in effective if r["cq"]),                     # 인용이 있던 실효 행(열 주석 그대로)
        "refs_ok": sum(1 for r in effective if r["refs_ok"] == 1),
        "refs_n": sum(1 for r in effective if r["refs_ok"] is not None),     # 참조가 있던(또는 있어야 했던) 실효 행
    })
    return tally


def write_call_result(store: Any, target_key: str, agent_key: str, *, lease_owner: str, call: Mapping[str, Any],
                      verdicts: Sequence[Mapping[str, Any]] = (), cell: Mapping[str, Any] | None = None,
                      head: Mapping[str, Any] | None = None, outcome: review_ops.Outcome | None = None,
                      max_charged: int = 2, now: int | None = None) -> dict:
    """끝난 호출 하나를 한 트랜잭션으로 적는다 — 호출 원장 행, 판정 행, 셀의 셈과 결말, 머리의 칸.

    - 선점 대조가 먼저다. 머리가 그 선점으로 `running` 이 아니면(재기동 복구·폐기가 지웠다), 단위 호출인데 셀이 그 선점으로
      `running` 이 아니면 아무것도 쓰지 않고 {written: False} 다(m-10).
    - `call` — `rr_review_calls` 열의 dict(`call_id`·`kind`·`state` 필수). 신원 열은 이 함수가 채운다.
    - `verdicts` — `review_verify.accept_rows` 의 행(그 열 이름 그대로). 별칭이 그 호출의 `cards_json` 에 없으면 ValueError 다
      (저장된 판정의 카드는 그 호출에 실은 카드다 — 나갈 기준 2). 쓴 뒤 그 셀의 실효·셈을 다시 맞춘다.
    - `cell` · `head` — 그 셀·머리에 적을 칸(상태·선점·신원·잡 결속·셈은 받지 않는다).
    - `outcome` — None 이면 성공이다(연속 인프라 실패를 0 으로). 실패는 `review_ops.classify` 의 결과로 셀을 옮긴다 —
      인프라는 차감 없이 `pending` + 백오프, 내용 탓은 `charged + 1`(한도 `max_charged` 에 닿으면 `failed(fail_code)`),
      잡 보류·취소·묶음은 차감 없이 `pending`, 기다림은 셀을 놓지 않는다(호출 수에도 세지 않는다).
    셀의 호출 수·토큰·시간은 호출 원장 행이 처음 끝날 때 한 번만 더한다(같은 call_id 를 다시 적어도 두 번 세지 않는다).
    """
    now = now_epoch() if now is None else now
    values = _checked(store, "rr_review_calls", call)
    for name in ("call_id", "kind", "state"):
        if not values.get(name):
            raise ValueError(f"호출 원장 행에는 {name} 가 있어야 한다")
    unit_id = values.get("unit_id")
    sent = set(json.loads(values["cards_json"])) if values.get("cards_json") else None
    rows = [_checked(store, "rr_card_verdicts", v, ("target_key", "agent_key", "owner_sub", "call_id")) for v in verdicts]
    if rows and unit_id is None:
        raise ValueError("판정 행은 단위 호출에만 있다")
    outside = sorted({str(r.get("alias")) for r in rows if sent is None or str(r.get("alias")) not in sent})
    if outside:
        raise ValueError(f"그 호출에 싣지 않은 카드의 판정 — {outside}")
    cell_sets = _checked(store, "rr_review_cells", cell or {}, _CELL_PROTECTED)
    head_sets = _checked(store, "rr_expert_reports", head or {}, _HEAD_PROTECTED)
    key = (target_key, str(unit_id), agent_key)
    try:
        with store.tx():
            if not _holds(store, target_key, agent_key, lease_owner):
                raise _LeaseLost
            owner = store.query_one("SELECT owner_sub, run_id FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?",
                                    (target_key, agent_key))
            row = None
            if unit_id is not None:
                row = _cell(store, *key)
                if row is None or row["state"] != "running" or row["lease_owner"] != lease_owner:
                    raise _LeaseLost
            before = store.query_one("SELECT state FROM rr_review_calls WHERE call_id = ?", (values["call_id"],))
            first_end = before is None or before["state"] == "running"
            record = {**values, "target_key": target_key, "agent_key": agent_key, "owner_sub": owner["owner_sub"],
                      "run_id": values.get("run_id") or owner["run_id"], "started_at": values.get("started_at") or now}
            store.execute(f"INSERT OR REPLACE INTO rr_review_calls({', '.join(record)})"
                          f" VALUES ({','.join('?' * len(record))})", tuple(record.values()))
            for verdict in rows:
                item = {**verdict, "target_key": target_key, "agent_key": agent_key, "owner_sub": owner["owner_sub"],
                        "unit_id": unit_id, "call_id": values["call_id"],
                        "deck_id": verdict.get("deck_id") or values.get("deck_id"),
                        "created_at": verdict.get("created_at") or now}
                item.pop("updated_at", None)
                # 행을 통째로 다시 쓰므로 updated_at 을 SQL 글에 못 박는다(since 반출 — 소스 가드가 이 글을 읽는다).
                store.execute(f"INSERT OR REPLACE INTO rr_card_verdicts({', '.join(item)}, updated_at)"
                              f" VALUES ({','.join('?' * len(item))}, ?)", (*item.values(), now))
            if head_sets:
                store.execute(f"UPDATE rr_expert_reports SET {', '.join(f'{c} = ?' for c in head_sets)}, updated_at = ?"
                              f" WHERE {_head_where()}", (*head_sets.values(), now, target_key, agent_key))
            state = None
            if row is not None:
                state = _apply_cell_outcome(store, key, row, values, cell_sets, outcome, first_end=first_end,
                                            max_charged=max_charged, lease_owner=lease_owner, now=now,
                                            rewrite=bool(rows))
    except _LeaseLost:
        return {"written": False, "call_id": values["call_id"]}
    return {"written": True, "call_id": values["call_id"], "cell_state": state}


def _apply_cell_outcome(store: Any, key: tuple[str, str, str], row: Mapping[str, Any], call: Mapping[str, Any],
                        cell_sets: Mapping[str, Any], outcome: review_ops.Outcome | None, *, first_end: bool,
                        max_charged: int, lease_owner: str, now: int, rewrite: bool) -> str:
    """`write_call_result` 의 셀 몫 — 셈을 더하고 결말대로 옮긴다. 셀의 새 상태를 돌려준다."""
    sets: dict[str, Any] = dict(cell_sets)
    if rewrite:
        sets.update(_rewrite_effective(store, key, now=now))
    waiting = outcome is not None and outcome.klass == review_ops.WAIT
    if first_end and not waiting:
        sets.update({
            "tries": Expr("tries + 1"),
            "llm_calls": Expr(f"llm_calls + {int(call.get('attempts') or 0)}"),
            "tokens_in": Expr(f"COALESCE(tokens_in, 0) + {int(call.get('tokens_in') or 0)}"),
            "tokens_out": Expr(f"COALESCE(tokens_out, 0) + {int(call.get('tokens_out') or 0)}"),
            "elapsed_ms": Expr(f"COALESCE(elapsed_ms, 0) + {int(call.get('duration_ms') or 0)}"),
        })
    sets["heartbeat_at"] = now
    where = f"{_cell_where()} AND lease_owner = ?"
    params = (*key, lease_owner)
    if outcome is None or waiting:
        if outcome is None:
            sets.update({"infra_streak": 0, "error_code": None, "error_class": None, "error": None, "knob": None})
        store.execute(f"UPDATE rr_review_cells SET {', '.join(_assign(sets))}, updated_at = ? WHERE {where}",
                      (*_args(sets), now, *params))
        return "running"
    released = {"lease_owner": None, "heartbeat_at": None, "error_code": outcome.code, "error_class": outcome.klass,
                "error": call.get("error"), "knob": outcome.knob}
    if outcome.klass == review_ops.INFRA:
        streak = int(row["infra_streak"] or 0) + 1
        salt = "|".join(key)
        _move(store, "cell", "running", "pending", where=where, params=params, now=now,
              sets={**sets, **released, "infra_streak": streak, "not_before": now + review_ops.backoff_s(streak, salt=salt)})
        return "pending"
    if outcome.klass == review_ops.CONTENT:
        charged = int(row["charged"] or 0) + 1
        if charged >= max(1, int(max_charged)):
            _move(store, "cell", "running", "failed", where=where, params=params, now=now,
                  sets={**sets, **released, "charged": charged, "error_code": outcome.fail_code or outcome.code,
                        "finished_at": now})
            return "failed"
        _move(store, "cell", "running", "pending", where=where, params=params, now=now,
              sets={**sets, **released, "charged": charged})
        return "pending"
    # 잡 보류·사람의 정지·취소·묶음 — 셀 탓이 아니다. 차감 없이 놓는다.
    _move(store, "cell", "running", "pending", where=where, params=params, now=now, sets={**sets, **released})
    return "pending"


def _assign(sets: Mapping[str, Any]) -> list[str]:
    return [f"{c} = {v}" if isinstance(v, Expr) else f"{c} = ?" for c, v in sets.items()]


def _args(sets: Mapping[str, Any]) -> list[Any]:
    return [v for v in sets.values() if not isinstance(v, Expr)]


def settle_cell(store: Any, target_key: str, unit_id: str, agent_key: str, *, lease_owner: str,
                samples_done: bool = True, more_calls: bool = False, fail_code: str | None = None,
                max_charged: int = 2, now: int | None = None) -> dict:
    """도는 셀을 정산한다 — {written, state, code?, missing?}.

    `reviewed` 조건(전부 참) — `cards_expected` 가 있고 `cards_judged == cards_expected`, 정산에 쓴 호출에 절단이 남지 않았다
    (`truncated = 1` 이 아니다 — NULL 은 '모름' 이라 막지 않는다, X1-22), 계획한 이중·단독 판정이 다 돌았다(`samples_done`),
    카드 밖 호출이 `done`·`none` 이다. 하나라도 거짓이고 `more_calls` 면 그대로 둔다(`state: 'running'`). 더 부를 호출이
    없으면 내용 탓 실패다 — `charged + 1`, 한도에 닿으면 `failed(<코드>)`. `fail_code` 를 주면 조건을 보지 않고 곧바로
    `failed(fail_code)` 다(셀당 호출 수 상한 — `call_cap`). 선점을 잃었으면 {written: False}.
    """
    now = now_epoch() if now is None else now
    key = (target_key, unit_id, agent_key)
    where = f"{_cell_where()} AND lease_owner = ?"
    params = (*key, lease_owner)
    release = {"lease_owner": None, "heartbeat_at": None, "finished_at": now}
    with store.tx():
        row = _cell(store, *key)
        if not _holds(store, target_key, agent_key, lease_owner) or row is None or row["state"] != "running" \
                or row["lease_owner"] != lease_owner:
            return {"written": False, "state": row["state"] if row else None}
        if fail_code:
            _move(store, "cell", "running", "failed", where=where, params=params, now=now,
                  sets={**release, "error_code": fail_code, "error_class": review_ops.CONTENT})
            return {"written": True, "state": "failed", "code": fail_code}
        missing = []
        if row["cards_expected"] is None or row["cards_judged"] != row["cards_expected"]:
            missing.append(SETTLE_CARDS_UNJUDGED)
        if row["truncated"] == 1:
            missing.append(SETTLE_TRUNCATED)
        if not samples_done:
            missing.append(SETTLE_SAMPLES)
        if row["offcard_state"] not in ("done", "none"):
            missing.append(SETTLE_OFFCARD)
        if not missing:
            _move(store, "cell", "running", "reviewed", where=where, params=params, now=now,
                  sets={**release, "not_before": None, "error_code": None, "error_class": None, "error": None,
                        "knob": None})
            return {"written": True, "state": "reviewed"}
        if more_calls:
            return {"written": True, "state": "running", "missing": missing}
        charged = int(row["charged"] or 0) + 1
        failure = {**release, "charged": charged, "error_code": missing[0], "error_class": review_ops.CONTENT,
                   "error": "정산 조건 미달 — " + ", ".join(missing)}
        if charged >= max(1, int(max_charged)):
            _move(store, "cell", "running", "failed", where=where, params=params, now=now, sets=failure)
            return {"written": True, "state": "failed", "code": missing[0], "missing": missing}
        _move(store, "cell", "running", "pending", where=where, params=params, now=now,
              sets={**failure, "finished_at": None})
        return {"written": True, "state": "pending", "code": missing[0], "missing": missing}


def fail_open_cells(store: Any, target_key: str, agent_key: str, *, code: str, error: str | None = None,
                    run_id: str | None = None, lease_owner: str | None = None, now: int | None = None) -> int:
    """그 전문가의 `pending` 셀을 `failed(code)` 로 닫는다 — 카드 묶음 한도 초과(`pack_unavailable`)·없는 전문가
    (`agent_not_found`) 처럼 셀을 돌릴 수 없는데 잡은 닫혀야 할 때(X1-25). `run_id` 를 주면 그 잡의 범위 안 셀만이고,
    `lease_owner` 를 주면 그 선점이 전문가를 쥐고 있을 때만 쓴다. 바꾼 셀 수를 돌려준다."""
    now = now_epoch() if now is None else now
    with store.tx():
        if lease_owner is not None and not _holds(store, target_key, agent_key, lease_owner):
            return 0
        where = "target_key = ? AND agent_key = ?" + (" AND run_id = ?" if run_id is not None else "")
        params = (target_key, agent_key) + ((run_id,) if run_id is not None else ())
        return _move(store, "cell", "pending", "failed", where=where, params=params, now=now,
                     sets={"error_code": code, "error_class": review_ops.PACK, "error": error, "finished_at": now})


def recover_running(store: Any, *, now: int | None = None) -> dict:
    """재기동 복구 — 셀 running → pending, 전문가 running → planned(선점을 지운다), 호출 running → aborted('restart').

    차감도 백오프도 없다(재기동은 누구 탓도 아니다). 검토 잡은 `running` 그대로다 — 검토 호출은 분리 태스크가 아니어서 겹칠
    심의가 없다(m2-wp3b S8). 끊긴 호출은 사람의 취소와 같은 부류로 적어 차단기 창에 들지 않게 한다. 반환 {cells, experts, calls}.
    """
    now = now_epoch() if now is None else now
    with store.tx():
        cells = _move(store, "cell", "running", "pending", where="1 = 1", sets={"lease_owner": None, "heartbeat_at": None},
                      now=now)
        experts = _move(store, "expert", "running", "planned", where="1 = 1", sets={"lease_owner": None}, now=now)
        calls = int(store.execute(
            "UPDATE rr_review_calls SET state = 'aborted', outcome_class = ?, error_code = ?, error_infra = 0,"
            " error = ? WHERE state = 'running'",
            (review_ops.CANCELLED, RESTART_CODE, "앱이 다시 떴다 — 이 호출만 다시 낸다(차감 없음)")) or 0)
    return {"cells": cells, "experts": experts, "calls": calls}


# ---------------------------------------------------------------- 셈
def _target_cells(store: Any, target_key: str, active: set[str]) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT unit_id, agent_key, state, basis, run_id, decided_by FROM rr_review_cells WHERE target_key = ?",
        (target_key,)) if r["unit_id"] in active]


def expert_tally(store: Any, target_key: str, agent_key: str) -> dict:
    """한 전문가의 셀 셈(활성 단위만) — 원장 롤업(`planner.close_review_seat`)의 입력.

    {by_state, open, reviewed, failed, skipped, verified, role_only_only}. `verified` 는 reviewed 셀의 실효 판정 가운데
    `applies='yes'` 이고 `quote_ok = 1`·`refs_ok = 1` 인 행이 하나라도 있나다(X1-05 — 해당 없음 행의 공허한 참은 세지 않는다).
    """
    active = set(active_unit_ids(store, target_key))
    rows = [r for r in _target_cells(store, target_key, active) if r["agent_key"] == agent_key]
    by_state = Counter(r["state"] for r in rows)
    reviewed = [r for r in rows if r["state"] == "reviewed"]
    reviewed_units = sorted({r["unit_id"] for r in reviewed})
    verified = False
    if reviewed_units:
        marks = ",".join("?" * len(reviewed_units))
        verified = store.query_one(
            f"SELECT 1 FROM rr_card_verdicts WHERE target_key = ? AND agent_key = ? AND unit_id IN ({marks})"
            " AND is_effective = 1 AND applies = 'yes' AND quote_ok = 1 AND refs_ok = 1 LIMIT 1",
            (target_key, agent_key, *reviewed_units)) is not None
    return {"by_state": {s: by_state.get(s, 0) for s in CELL_STATES},
            "open": sum(by_state.get(s, 0) for s in OPEN_CELL_STATES), "reviewed": len(reviewed),
            "failed": by_state.get("failed", 0), "skipped": by_state.get("skipped", 0), "verified": verified,
            "role_only_only": bool(reviewed) and all(r["basis"] == "role_only" for r in reviewed)}


def _latest_review_job(store: Any, target_key: str) -> dict | None:
    row = store.query_one("SELECT id, state FROM rr_jobs WHERE target_key = ? AND mode = 'reviews'"
                          " ORDER BY created_at DESC, id DESC LIMIT 1", (target_key,))
    return dict(row) if row is not None else None


def review_summary(store: Any, target_key: str, *, job_id: str | None = None) -> dict:
    """진행판·보고서의 셀 셈(활성 단위만). 셀이 없는 타깃은 `cells.total` 0 이다.

    {units, cells{total, by_state, by_basis, in_scope{job_id, total, by_state} | None, out_of_scope_pending, failed_open},
    experts{total, by_state}}. `by_basis` 는 reviewed 셀을 무엇으로 봤는지로 가른다(X1-04 — 카드 대조 · 배경 카드뿐 · 역할만).
    범위는 `job_id`(없으면 그 타깃의 가장 최근 검토 잡)가 찍은 셀이다. `failed_open` 은 사람이 처분하지 않은 failed 셀이다.
    """
    active = set(active_unit_ids(store, target_key))
    rows = _target_cells(store, target_key, active)
    by_state = Counter(r["state"] for r in rows)
    by_basis = Counter(r["basis"] if r["basis"] in CELL_BASES else "unset" for r in rows if r["state"] == "reviewed")
    job = ({"id": job_id} if job_id else _latest_review_job(store, target_key))
    in_scope = None
    out_pending = sum(1 for r in rows if r["state"] == "pending")
    if job is not None:
        mine = [r for r in rows if r["run_id"] == job["id"]]
        scoped = Counter(r["state"] for r in mine)
        in_scope = {"job_id": job["id"], "total": len(mine), "by_state": {s: scoped.get(s, 0) for s in CELL_STATES}}
        out_pending = sum(1 for r in rows if r["state"] == "pending" and r["run_id"] != job["id"])
    heads = Counter(r["state"] for r in store.query("SELECT state FROM rr_expert_reports WHERE target_key = ?",
                                                     (target_key,)))
    return {
        "units": len(active),
        "cells": {"total": len(rows), "by_state": {s: by_state.get(s, 0) for s in CELL_STATES},
                  "by_basis": {**{b: by_basis.get(b, 0) for b in CELL_BASES},
                               **({"unset": by_basis["unset"]} if by_basis.get("unset") else {})},
                  "in_scope": in_scope, "out_of_scope_pending": out_pending,
                  "failed_open": sum(1 for r in rows if r["state"] == "failed" and not r["decided_by"])},
        "experts": {"total": sum(heads.values()), "by_state": {s: heads.get(s, 0) for s in EXPERT_STATES}},
    }


def review_invariants(store: Any, target_key: str) -> list[str]:
    """셀 원장의 불변식 위반 목록(빈 목록 = 통과). 셀이 하나도 없는 타깃은 검사할 것이 없다.

    (G1) 격자 — 활성 단위의 셀 수 == 로스터 × 검토 대상 단위, 쌍마다 한 칸(X1-27).
    (G2) 어휘 — 셀·머리의 상태가 전이표의 어휘 안이다.
    (G3) 선점 — running 셀은 그 전문가가 같은 선점으로 running 이고, running 머리는 선점이 있으며, 아닌 것은 선점이 없다.
    (G4) reviewed 셀 — `cards_judged == cards_expected`(카드 누락 0), `truncated` 가 1 이 아니고(절단 0, NULL 은 모름),
         카드 밖 호출이 끝났고, 무엇으로 봤는지(basis)가 있다. 실효 판정이 있는 카드 수가 `cards_judged` 와 같다(X1-03).
    (G5) 판정 행 — 그 행의 호출이 원장에 있고 그 호출에 실은 카드에 그 별칭이 있다(나갈 기준 2). 참조가 없는데 `applies` 가
         yes 가 아니면 `refs_ok` 는 NULL 이다(X1-05). 카드마다 실효 행이 하나다.
    (G6) failed 셀에는 까닭(error_code)이 있다.
    """
    problems: list[str] = []
    cells = [dict(r) for r in store.query(
        "SELECT unit_id, agent_key, state, lease_owner, basis, cards_expected, cards_judged, truncated, offcard_state,"
        " error_code FROM rr_review_cells WHERE target_key = ?", (target_key,))]
    heads = {r["agent_key"]: dict(r) for r in store.query(
        "SELECT agent_key, state, lease_owner FROM rr_expert_reports WHERE target_key = ?", (target_key,))}
    if not cells and not heads:
        return problems
    active = set(active_unit_ids(store, target_key))
    roster = {r["agent_key"] for r in planner.review_order(store, target_key)}
    grid = {(c["unit_id"], c["agent_key"]) for c in cells if c["unit_id"] in active}
    expected = {(u, a) for u in active for a in roster}
    if grid != expected:
        problems.append(f"(G1) 격자가 로스터 {len(roster)} × 단위 {len(active)} = {len(expected)} 칸과 다르다 — "
                        f"빠짐 {len(expected - grid)} · 남음 {len(grid - expected)}.")
    for c in cells:
        if c["state"] not in CELL_STATES:
            problems.append(f"(G2) 셀 {c['unit_id']}×{c['agent_key']} 의 상태 {c['state']!r} 가 어휘 밖이다.")
    for agent, h in heads.items():
        if h["state"] not in EXPERT_STATES:
            problems.append(f"(G2) 머리 {agent} 의 상태 {h['state']!r} 가 어휘 밖이다.")
        if (h["state"] == "running") != bool(h["lease_owner"]):
            problems.append(f"(G3) 머리 {agent} 가 {h['state']} 인데 선점이 {'없다' if h['state'] == 'running' else '남았다'}.")
    for c in cells:
        name = f"{c['unit_id']}×{c['agent_key']}"
        head = heads.get(c["agent_key"]) or {}
        if c["state"] == "running" and not (head.get("state") == "running" and c["lease_owner"]
                                            and c["lease_owner"] == head.get("lease_owner")):
            problems.append(f"(G3) running 셀 {name} 의 선점이 그 전문가의 선점과 다르다.")
        if c["state"] != "running" and c["lease_owner"]:
            problems.append(f"(G3) {c['state']} 셀 {name} 에 선점이 남았다.")
        if c["state"] == "reviewed":
            if c["cards_expected"] is None or c["cards_judged"] != c["cards_expected"]:
                problems.append(f"(G4) reviewed 셀 {name} 의 판정 카드 {c['cards_judged']} ≠ 계획 {c['cards_expected']}.")
            if c["truncated"] == 1:
                problems.append(f"(G4) reviewed 셀 {name} 에 절단이 남았다.")
            if c["offcard_state"] not in ("done", "none"):
                problems.append(f"(G4) reviewed 셀 {name} 의 카드 밖 호출이 {c['offcard_state']} 다.")
            if c["basis"] not in CELL_BASES:
                problems.append(f"(G4) reviewed 셀 {name} 의 basis {c['basis']!r} 가 없다.")
        if c["state"] == "failed" and not c["error_code"]:
            problems.append(f"(G6) failed 셀 {name} 에 까닭이 없다.")
    judged = Counter((r["unit_id"], r["agent_key"]) for r in store.query(
        "SELECT unit_id, agent_key FROM rr_card_verdicts WHERE target_key = ? AND is_effective = 1", (target_key,)))
    for c in cells:
        if c["state"] == "reviewed" and judged.get((c["unit_id"], c["agent_key"]), 0) != (c["cards_judged"] or 0):
            problems.append(f"(G4) reviewed 셀 {c['unit_id']}×{c['agent_key']} 의 실효 판정 카드"
                            f" {judged.get((c['unit_id'], c['agent_key']), 0)} ≠ cards_judged {c['cards_judged']}.")
    effective = Counter()
    for v in store.query(
            "SELECT v.unit_id, v.agent_key, v.record_id, v.variant, v.alias, v.applies, v.refs_json, v.refs_ok,"
            " v.is_effective, v.call_id, k.cards_json FROM rr_card_verdicts v"
            " LEFT JOIN rr_review_calls k ON k.call_id = v.call_id WHERE v.target_key = ?", (target_key,)):
        name = f"{v['unit_id']}×{v['agent_key']}·{v['record_id']}·{v['variant']}"
        if v["cards_json"] is None:
            problems.append(f"(G5) 판정 {name} 의 호출 {v['call_id']} 이 원장에 없다.")
        elif v["alias"] not in json.loads(v["cards_json"]):
            problems.append(f"(G5) 판정 {name} 의 카드 {v['alias']} 가 그 호출에 실리지 않았다.")
        if not json.loads(v["refs_json"] or "[]") and v["applies"] != "yes" and v["refs_ok"] is not None:
            problems.append(f"(G5) 판정 {name} 은 참조가 없는데 refs_ok 가 {v['refs_ok']} 다(NULL 이어야 한다).")
        effective[(v["unit_id"], v["agent_key"], v["record_id"])] += int(v["is_effective"] or 0)
    for (unit_id, agent, record_id), n in effective.items():
        if n != 1:
            problems.append(f"(G5) 판정 {unit_id}×{agent}·{record_id} 의 실효 행이 {n} 개다.")
    return problems
