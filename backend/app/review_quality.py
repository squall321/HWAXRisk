# 검토 품질 수치 — 셀·판정·호출 원장에서 격자·카드 폭포·절단·인용·뒤집힘·호출 초·실측을 세고 문면 블록을 조립한다(LLM 을 부르지 않는다, m2-wp3b S11)
"""진행 응답·전문가 보고서·M2 실측표가 같은 수를 읽는 한 곳이다(C-29). 원장은 v4 의 `rr_review_cells` · `rr_card_verdicts` ·
`rr_review_calls` · `rr_expert_reports` · `rr_card_packs` 이고 이 모듈은 아무것도 쓰지 않는다.

- `compute(store, target_key, *, agent_key=None)` — 수치 dict. 비율·통계는 `{value, num, den, upper95?, threshold?, within?}` 이고
  표본이 `min_n` 에 못 미치면 `value=None`(0 으로 적지 않는다 — n 은 `den` 에 남는다).
- `block(store, target_key)` — `{key:'quality', title, text, json}`. 문면의 수는 `json` 의 수 그대로이고 판단어 린터를 지난다
  (표기는 WP5b 3.11.3 — 걸림 · 걸림 없음 · 보류 · 미완 · 미달). 셀 원장이 없는 대상은 한 줄만 낸다.
- `progress_hook` — 검토 루프의 진행판이 60초마다 불러 `progress_json.quality` 에 넣는다(M2.md 5절 #16, main 이 꽂는다).

센 범위 — 활성 빌드의 검토 대상 단위의 셀과 그 판정·호출이다(`review_cells.review_summary` 와 같다). 단위가 없는 훑기 호출은 센다.
새 표 바이트(`pilot.bytes`)만은 활성 여부와 상관없이 그 대상의 행 전부다(DB 증가분). 챗 첫 응답 지연은 여기서 재지 않는다
(포털·에이전트 서버 로그 — 절차서 몫).
"""
from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app import audit, planner, review_cells, review_verify, taxonomy
from app.common import canonical_json, now_epoch, sha256_hex
from app.runner import ENGINE_EXTERNAL, JUDGE_CLAUDE, LLM_CLAUDE

POLICY_ASSET = "review-quality"
BLOCK_KEY = "quality"
TITLE = "검토 품질"
EXTERNAL_MODEL = ENGINE_EXTERNAL     # 외부 응답자 답의 meta.model(엔진 계약 — 그 길의 답에만 external 이 선다, Claude 길 X-2)
# 호출 초를 가르는 종류 — verdict 는 변형까지(fwd·rev·solo). 늘 다섯 줄을 낸다(재지 않은 종류는 미측정으로).
KINDS: tuple[str, ...] = ("sweep", "verdict/fwd", "verdict/rev", "verdict/solo", "offcard")
CALL_DONE_STATES: tuple[str, ...] = ("ok", "infra_fail", "content_fail", "aborted")   # 낸 호출(기다림·도는 중 제외)
SWEEP_ANSWERED: tuple[str, ...] = ("yes", "maybe", "no", "stamp")                     # 훑기가 답한 단위(error 제외)
# 카드 폭포의 줄 — 분모 = Σ(셀마다 그 전문가 묶음의 카드 전부). 줄의 합이 분모다(어긋나면 residual).
# noinput_reviewed — 입력 결손 호출로 검토한 칸(재설계 M3 C3-3)의 카드 전부. 카드를 한 장씩 판정하지 않고 근거로 읽었다 — '판정 없음'
# 으로 세면 거짓 미판정이 된다.
WATERFALL: tuple[str, ...] = ("judged", "unjudged", "background_full", "background_title_only", "background_unsent",
                              "no_body", "noinput_reviewed", "failed", "open", "out_of_scope", "filtered", "no_input")
# 새 표(v4) — 대상 범위와 전문가 범위. 전문가 범위는 머리(rr_expert_reports)를 뺀다 — 보고서를 머리에 쓰는 S10 이 이 수를
# 보고서에 실으므로, 넣으면 같은 원장에서도 다시 마감할 때마다 앞 보고서의 바이트가 수에 들어가 보고서가 바뀐다(m-07).
TARGET_TABLES: tuple[str, ...] = ("rr_unit_builds", "rr_units", "rr_expert_reports", "rr_review_cells", "rr_card_verdicts",
                                  "rr_review_calls", "rr_card_packs")
AGENT_TABLES: tuple[str, ...] = ("rr_review_cells", "rr_card_verdicts", "rr_review_calls", "rr_card_packs")

# 기준 밖 줄의 이름(문면).
LABELS: dict[str, str] = {
    "truncation.calls": "절단(호출)", "citation.quote.flagged": "인용 대조(걸림)", "citation.quote.clear": "인용 대조(걸림 없음)",
    "flips.order": "순서(fwd·rev 다름)", "flips.solo_neg_pos": "뒤집힘(걸림 없음→걸림) 95% 상한",
    "filter.audit.risk_miss": "거름 표본의 놓침 95% 상한",
}


# ---------------------------------------------------------------- 기준판
def load_policy() -> dict:
    """assets/review-quality.v1.json(기준판 rq-2 — 재설계 M3 C3-8 의 거르기 표본 기준)."""
    return taxonomy.load_json(POLICY_ASSET)


def verdict_class(judgement: Any, *, split: Any = 0) -> str:
    """판정 범주 셋 — 'pos'(걸림 FAIL·WARNING) · 'neg'(걸림 없음 OK·na) · 'hold'(보류 undetermined). 실효 행의 `split` 이 1 이면
    변형 사이에 걸림·통과가 갈려 실효를 보류로 둔 카드다(X1-14 — 행의 판정 글자가 OK 여도 보류다)."""
    if split:
        return "hold"
    j = str(judgement or "")
    if j in review_verify.FLAGGED:
        return "pos"
    if j in review_verify.CLEAR:
        return "neg"
    return "hold"


def _threshold_of(policy: Mapping[str, Any], key: str | None) -> dict | None:
    if not key:
        return None
    found = (policy.get("thresholds") or {}).get(key)
    return dict(found) if isinstance(found, Mapping) else None


def _min_n(policy: Mapping[str, Any], key: str | None) -> int:
    value = (policy.get("min_n") or {}).get(key) if key else None
    return max(1, int(value)) if isinstance(value, int) and not isinstance(value, bool) else 1


def _ratio(num: int | float, den: int | float) -> float | None:
    return round(float(num) / float(den), 6) if den else None


def rate(num: int, den: int, *, policy: Mapping[str, Any], key: str | None = None, upper: bool = False) -> dict:
    """비율 하나 — {value, num, den, upper95?, min_n?, threshold?, within?}. den 이 min_n 미만이면 value·upper95·within 이 None
    이다(n 은 den). `upper` 면 audit.binom_upper 의 단측 95% 상한을 싣는다. 기준(max·min 은 값, upper_max 는 상한과 견준다)이
    있으면 within 을 단다."""
    floor = _min_n(policy, key)
    enough = den >= floor and den > 0
    out: dict[str, Any] = {"value": _ratio(num, den) if enough else None, "num": int(num), "den": int(den)}
    if floor > 1:
        out["min_n"] = floor
    if upper:
        bound = audit.binom_upper(int(num), int(den)) if enough else None
        out["upper95"] = round(bound, 6) if bound is not None else None
    threshold = _threshold_of(policy, key)
    if threshold is not None:
        out["threshold"] = threshold
        out["within"] = _within(out, threshold)
    return out


def _within(metric: Mapping[str, Any], threshold: Mapping[str, Any]) -> bool | None:
    value = metric.get("value")
    if value is None:
        return None
    if "upper_max" in threshold:
        bound = metric.get("upper95")
        if bound is None:
            return None
        if bound > float(threshold["upper_max"]):
            return False
    if "max" in threshold and value > float(threshold["max"]):
        return False
    if "min" in threshold and value < float(threshold["min"]):
        return False
    return True


def _percentile(sorted_values: Sequence[float], p: float) -> float:
    """가까운 순위 백분위 — 작은 쪽부터 ceil(p·n) 번째 값(보간하지 않는다)."""
    rank = max(1, math.ceil(p * len(sorted_values)))
    return sorted_values[rank - 1]


def seconds_stat(values_ms: Iterable[int], *, policy: Mapping[str, Any]) -> dict:
    """호출 시간(ms 목록) → {n, p50, p95, max} — 각 칸 {value(초, 소수 셋째 자리), n}, p95 는 기준(seconds.p95)과 견준다."""
    values = sorted(int(v) for v in values_ms)
    n = len(values)

    def secs(ms: float | None) -> dict:
        return {"value": round(ms / 1000.0, 3) if ms is not None else None, "n": n}

    p95 = secs(_percentile(values, 0.95) if n else None)
    threshold = _threshold_of(policy, "seconds.p95")
    if threshold is not None:
        p95["threshold"] = threshold
        p95["within"] = _within(p95, threshold)
    return {"n": n, "p50": secs(_percentile(values, 0.50) if n else None), "p95": p95,
            "max": secs(float(values[-1]) if n else None)}


# ---------------------------------------------------------------- 원장 읽기
def _rows(store: Any, sql: str, params: Sequence[Any]) -> list[dict]:
    return [dict(r) for r in store.query(sql, tuple(params))]


def _scope_sql(agent_key: str | None) -> tuple[str, list[Any]]:
    return (" AND agent_key = ?", [agent_key]) if agent_key else ("", [])


def _latest_review_job(store: Any, target_key: str) -> str | None:
    row = store.query_one("SELECT id FROM rr_jobs WHERE target_key = ? AND mode = 'reviews'"
                          " ORDER BY created_at DESC, id DESC LIMIT 1", (target_key,))
    return str(row["id"]) if row is not None else None


def _load(store: Any, target_key: str, agent_key: str | None) -> dict:
    """원장 행(활성 단위만 — 단위 없는 훑기 호출은 남긴다)과 로스터·단위·잡."""
    roster = [r["agent_key"] for r in planner.review_order(store, target_key)]
    agents = [a for a in roster if agent_key is None or a == agent_key]
    active = review_cells.active_unit_ids(store, target_key)
    alive = set(active)
    extra, params = _scope_sql(agent_key)
    cells = [r for r in _rows(store,
        "SELECT unit_id, agent_key, state, basis, run_id, pack_hash, cards_expected, cards_judged, truncated, soft_over,"
        " offcard_capped, bg_full_n, bg_title_only_n, n_fail, n_warning, quote_ok, decided_by, route,"
        " json_extract(route_json, '$.rule') AS rule, sample_json,"
        " json_extract(extras_json, '$.noinput.outcome') AS noinput_outcome,"
        " json_extract(extras_json, '$.noinput.capped') AS noinput_capped,"
        " json_extract(extras_json, '$.coverage') AS coverage FROM rr_review_cells"
        f" WHERE target_key = ?{extra} ORDER BY agent_key, unit_id", [target_key, *params]) if r["unit_id"] in alive]
    for cell in cells:
        # 표본 · 그림자의 실효 결과 — 앞 결과는 놓침만 센다(반대 검토 2차 LOW 6 · 3차 LOW 4 · D-47 — 완결 몫 · 넓힘과 같은 셈)
        outcomes = review_cells.sample_outcomes(cell.pop("sample_json"))
        cell.update(audit=outcomes.get("filter_audit"), shadow=outcomes.get("shadow"))
    verdicts = [r for r in _rows(store,
        "SELECT unit_id, agent_key, record_id, variant, applies, judgement, quote_ok, refs_ok, check_disagree, is_effective,"
        " agree, split, json_type(checks_json, '$.flipped_from') IS NOT NULL AS flipped_row,"
        " json_type(checks_json, '$.flipped_from.raw') IS NOT NULL AS flipped_raw"
        f" FROM rr_card_verdicts WHERE target_key = ?{extra} ORDER BY agent_key, unit_id, record_id, variant",
        [target_key, *params]) if r["unit_id"] in alive]
    calls = [r for r in _rows(store,
        "SELECT call_id, agent_key, unit_id, kind, variant, state, duration_ms, queued_ms, output_truncated, soft_over,"
        " attempts, prompt_chars, tokens_in, tokens_out, dropped_over_cap, model, prompt_rev, limits_rev,"
        " json_extract(quality_json, '$.app.check_disagree') AS check_disagree,"
        " json_extract(quality_json, '$.engine.dup_conflict') AS dup_conflict,"
        " json_extract(quality_json, '$.engine.flipped') AS flipped,"
        " json_extract(quality_json, '$.app.clipped') AS clipped FROM rr_review_calls"
        f" WHERE target_key = ?{extra} ORDER BY call_id", [target_key, *params])
        if r["unit_id"] is None or r["unit_id"] in alive]
    heads = _rows(store, "SELECT agent_key, state, pack_hash, pack_status, sweep_json, plan_json, rank_in_domain"
                         f" FROM rr_expert_reports WHERE target_key = ?{extra} ORDER BY agent_key", [target_key, *params])
    keys = sorted({(r["agent_key"], r["pack_hash"]) for r in (*cells, *heads) if r.get("pack_hash")})
    packs: dict[tuple[str, str], dict] = {}
    for agent, key in keys:
        row = store.query_one("SELECT cards_total, checkable_n, unrenderable_n FROM rr_card_packs WHERE agent_key = ?"
                              " AND pack_key = ?", (agent, key))
        if row is not None:
            packs[(agent, key)] = dict(row)
    job_id = _latest_review_job(store, target_key)
    job = store.query_one("SELECT params_json FROM rr_jobs WHERE id = ?", (job_id,)) if job_id else None
    try:
        knobs = (json.loads(job["params_json"] or "{}").get("knobs") or {}) if job is not None else {}
    except ValueError:
        knobs = {}
    # 1순위(보정 모집단 — 걸린 것만 이중 판정이어도 묶음 전체를 rev 한다, C3-9) 전문가. 전문가 범위에서는 그 사람이 1순위인지다.
    rank1 = {str(r["agent_key"]) for r in planner.review_order(store, target_key) if r["rank_in_domain"] == 1}
    return {"agent_key": agent_key, "agents": agents, "units": active, "cells": cells, "verdicts": verdicts, "calls": calls,
            "heads": heads,
            "packs": packs, "job_id": job_id, "knobs": dict(knobs), "rank1": rank1}


def _ledger_hash(data: Mapping[str, Any]) -> str:
    """수를 센 원장 행의 지문(sha256 앞 16자) — 같은 원장이면 같은 값이다(머리는 뺀다 — 상태가 마감 중에 바뀐다)."""
    body = {"agents": data["agents"], "units": data["units"], "cells": data["cells"], "verdicts": data["verdicts"],
            "calls": data["calls"], "packs": sorted([list(k), v] for k, v in data["packs"].items())}
    return sha256_hex(canonical_json(body))[:16]


# ---------------------------------------------------------------- 칸별 셈
def _deck_k(heads: Sequence[Mapping[str, Any]]) -> list[dict]:
    """K(판정 묶음당 카드 상한 — 엔진 limits 의 verdict.k) — 전문가 머리의 계획(plan_json.k)에서 값마다 전문가 수. 계획 전이거나 이
    칸을 적기 전의 계획이면 세지 않는다."""
    counts: Counter = Counter()
    for head in heads:
        try:
            k = (json.loads(head.get("plan_json") or "{}") or {}).get("k")
        except (TypeError, ValueError):
            k = None
        if isinstance(k, int) and not isinstance(k, bool):
            counts[k] += 1
    return [{"value": k, "experts": n} for k, n in sorted(counts.items())]


def _stamps(calls: Sequence[Mapping[str, Any]], heads: Sequence[Mapping[str, Any]] = ()) -> dict:
    """판 — 모델·창 판은 받은(ok) 호출의 값, 프롬프트 판은 종류별 값, K 는 전문가 머리의 계획 값. 한 값이면 그 글, 여럿이면 None 이고
    `revs` 에 호출 수(K 는 전문가 수)와 함께 전부 싣는다.

    판이 섞인 대상(도중에 모델·프롬프트·창이 바뀌었다)은 '판 섞임' 으로 적고 판마다 호출 수를 단다 — 수치를 판마다 따로 다시 세지
    않는다(M2 의 선택, R3B-10). 파일럿 한 잡은 한 판으로 돌고, 판마다 다시 세는 일은 판을 바꿔 가며 견주는 M3 의 몫이다."""
    ok = [c for c in calls if c["state"] == "ok"]

    def tally(values: Iterable[Any]) -> list[dict]:
        counts = Counter(v for v in values if v)
        return [{"value": v, "calls": n} for v, n in sorted(counts.items())]

    models = tally(c["model"] for c in ok)
    limits = tally(c["limits_rev"] for c in ok)
    prompts = {kind: tally(c["prompt_rev"] for c in ok if c["kind"] == kind)
               for kind in sorted({c["kind"] for c in ok})}
    prompts = {k: v for k, v in prompts.items() if v}
    ks = _deck_k(heads)
    mixed = len(models) > 1 or len(limits) > 1 or any(len(v) > 1 for v in prompts.values()) or len(ks) > 1
    single_prompt = (",".join(f"{k}={v[0]['value']}" for k, v in prompts.items())
                     if prompts and all(len(v) == 1 for v in prompts.values()) else None)
    return {"model": models[0]["value"] if len(models) == 1 else None,
            "prompt_rev": single_prompt,
            "limits_rev": limits[0]["value"] if len(limits) == 1 else None,
            "k": ks[0]["value"] if len(ks) == 1 else None,
            "revs": {"model": models, "prompt_rev": prompts, "limits_rev": limits, "k": ks, "mixed": mixed}}


def _grid(data: Mapping[str, Any], policy: Mapping[str, Any]) -> dict:
    cells, job_id = data["cells"], data["job_id"]
    by_state = Counter(c["state"] for c in cells)
    reviewed = [c for c in cells if c["state"] == "reviewed"]
    basis = Counter(c["basis"] if c["basis"] in review_cells.CELL_BASES else "unset" for c in reviewed)
    expected = {(u, a) for u in data["units"] for a in data["agents"]}
    present = {(c["unit_id"], c["agent_key"]) for c in cells}
    in_scope = None
    pending_out = sum(1 for c in cells if c["state"] == "pending")
    if job_id is not None:
        mine = [c for c in cells if c["run_id"] == job_id]
        scoped = Counter(c["state"] for c in mine)
        in_scope = {"job_id": job_id, "total": len(mine),
                    "by_state": {s: scoped.get(s, 0) for s in review_cells.CELL_STATES}}
        pending_out = sum(1 for c in cells if c["state"] == "pending" and c["run_id"] != job_id)
    heads = Counter(h["state"] for h in data["heads"])
    carded = [c for c in reviewed if c["basis"] == "cards"]
    form_only = sum(1 for c in carded if int(c["n_fail"] or 0) + int(c["n_warning"] or 0) == 0 and not int(c["quote_ok"] or 0))
    return {
        "experts": len(data["agents"]), "units": len(data["units"]), "expected": len(expected), "cells": len(cells),
        "missing": len(expected - present), "extra": len(present - expected),
        "by_state": {s: by_state.get(s, 0) for s in review_cells.CELL_STATES},
        "reviewed_by_basis": {**{b: basis.get(b, 0) for b in review_cells.CELL_BASES},
                              **({"unset": basis["unset"]} if basis.get("unset") else {})},
        "in_scope": in_scope, "out_of_scope_pending": pending_out,
        "failed_open": sum(1 for c in cells if c["state"] == "failed" and not c["decided_by"]),
        # 전문가 한 명 범위(보고서의 품질 절)에서는 머리 상태를 싣지 않는다 — 마감 순간에 running → ready·partial 로 바뀌어,
        # 같은 원장으로 다시 조립한 보고서의 바이트가 달라진다(m-07). 대상 범위에서만 센다.
        "expert_states": (None if data.get("agent_key") else
                          {"total": sum(heads.values()),
                           "by_state": {s: heads.get(s, 0) for s in review_cells.EXPERT_STATES}}),
        # 카드를 대조한 검토 칸 가운데 걸림 0 이고 대조를 지난 카드 인용도 0 인 칸(WP5b rv.form_only — 검토 수와 같은 줄에 단다).
        "form_only": rate(form_only, len(carded), policy=policy, key="grid.form_only"),
    }


def _cards(data: Mapping[str, Any], policy: Mapping[str, Any]) -> dict:
    """카드 폭포(X1-03) — 분모는 셀마다 그 전문가 묶음의 카드 전부(점검 · 배경 · 본문 없음)의 합이다. 'judged/expected'(정의상
    늘 100%)는 불변식 칸에만 둔다. 묶음을 아직 얼리지 못한 전문가의 셀은 카드 수를 몰라 분모 밖이고 그 수를 따로 싣는다."""
    head_pack = {h["agent_key"]: h["pack_hash"] for h in data["heads"]}
    judged_of = Counter((v["unit_id"], v["agent_key"]) for v in data["verdicts"] if v["is_effective"])
    lines = dict.fromkeys(WATERFALL, 0)
    denominator = 0
    no_pack_cells = 0
    no_pack_agents: set[str] = set()
    inv_judged = inv_expected = 0
    job_id = data["job_id"]
    for c in data["cells"]:
        pack = data["packs"].get((c["agent_key"], c["pack_hash"] or head_pack.get(c["agent_key"]) or ""))
        if pack is None:
            no_pack_cells += 1
            no_pack_agents.add(c["agent_key"])
            continue
        checkable = int(pack["checkable_n"])
        background = int(pack["cards_total"]) - checkable
        no_body = int(pack["unrenderable_n"])
        total = checkable + background + no_body
        denominator += total
        state = c["state"]
        if state == "reviewed" and c["basis"] == review_cells.NOINPUT:
            lines["noinput_reviewed"] += total
        elif state == "reviewed":
            judged = judged_of.get((c["unit_id"], c["agent_key"]), 0)
            full, title = int(c["bg_full_n"] or 0), int(c["bg_title_only_n"] or 0)
            lines["judged"] += judged
            lines["unjudged"] += max(checkable - judged, 0)
            lines["background_full"] += full
            lines["background_title_only"] += title
            lines["background_unsent"] += max(background - full - title, 0)
            lines["no_body"] += no_body
            inv_judged += int(c["cards_judged"] or 0)
            inv_expected += int(c["cards_expected"] or 0)
        elif state in ("failed", "skipped"):
            lines["failed"] += total
        elif state in ("pending", "running"):
            lines["open" if job_id is not None and c["run_id"] == job_id else "out_of_scope"] += total
        elif state == "na_irrelevant":
            lines["filtered"] += total
        elif state == "no_input":
            lines["no_input"] += total
    return {
        "denominator": denominator,
        "lines": {name: rate(n, denominator, policy=policy) for name, n in lines.items()},
        "coverage": _coverage(data["cells"]),
        "residual": denominator - sum(lines.values()),
        "experts_without_pack": len(no_pack_agents), "cells_without_pack": no_pack_cells,
        # X1-03 — 검토 칸의 판정 카드 = 계획 카드는 정산 조건이라 늘 참이다. 지표가 아니라 불변식으로만 둔다.
        "invariant": {"judged": inv_judged, "expected": inv_expected, "holds": inv_judged == inv_expected},
    }


def _coverage(cells: Sequence[Mapping[str, Any]]) -> dict:
    """닫힌(reviewed · no_input) 칸의 카드 커버리지 합(HWAXPortal docs/risk-200k W-D3 · W-D17 — 러너가 칸마다 extras_json.coverage 에
    적는다). 카드 × 칸마다 전문으로 본 길 — 판정 · 카드 밖/입력 결손 호출의 전문 · 훑기 대조만. 놓침(missed)은 셋 다 없는 것(불변식
    G10), hit_title 은 훑기에 걸렸는데 판정도 호출 전문도 없는 것(자리가 없어 제목으로). 커버리지를 적기 전에 닫힌 칸은 unknown 이다."""
    out = {"cells": 0, "unknown_cells": 0, "pairs": 0, "judged": 0, "full": 0, "swept_only": 0, "missed": 0, "hit_title": 0}
    for c in cells:
        if c["state"] not in ("reviewed", "no_input"):
            continue
        try:
            cov = json.loads(c.get("coverage") or "null")
        except ValueError:
            cov = None
        if not isinstance(cov, Mapping):
            out["unknown_cells"] += 1
            continue
        out["cells"] += 1
        for key in ("judged", "full", "swept_only"):
            out[key] += int(cov.get(key) or 0)
        out["pairs"] += int(cov.get("cards") or 0)
        out["missed"] += len(cov.get("missed") or ())
        out["hit_title"] += len(cov.get("hit_title") or ())
    return out


def _clipped(call: Mapping[str, Any]) -> dict:
    try:
        value = json.loads(call.get("clipped") or "null")
    except (TypeError, ValueError):
        value = None
    return value if isinstance(value, dict) else {}


def _truncation(data: Mapping[str, Any], policy: Mapping[str, Any]) -> dict:
    ok = [c for c in data["calls"] if c["state"] == "ok"]
    clipped = [_clipped(c) for c in ok if _clipped(c)]
    reviewed = [c for c in data["cells"] if c["state"] == "reviewed"]
    offcard = [c for c in ok if c["kind"] == "offcard"]
    return {
        # 받은 호출의 output_truncated — 1 · 0 · NULL(모름, X1-22 — 0 으로 치지 않는다)을 따로 센다.
        "calls": rate(sum(1 for c in ok if c["output_truncated"] == 1), len(ok), policy=policy, key="truncation.calls"),
        "calls_unknown": rate(sum(1 for c in ok if c["output_truncated"] is None), len(ok), policy=policy),
        # 검토 칸의 절단 — 1 은 정산이 막으므로 0 이어야 한다(나갈 기준 1), NULL 은 모름.
        "cells": rate(sum(1 for c in reviewed if c["truncated"] == 1), len(reviewed), policy=policy),
        "cells_unknown": rate(sum(1 for c in reviewed if c["truncated"] is None), len(reviewed), policy=policy),
        "soft_over": rate(sum(1 for c in ok if c["soft_over"]), len(ok), policy=policy),
        # 카드 밖 줄이 findings_max 에 닿은 칸과 닿은 횟수(X1-16), 엔진이 상한 밖이라 버린 줄.
        "offcard_capped": {"cells": sum(1 for c in data["cells"] if int(c["offcard_capped"] or 0) > 0),
                           "hits": sum(int(c["offcard_capped"] or 0) for c in data["cells"])},
        # 입력 결손 호출이 마지막 다시 묻기 뒤에도 '더 있다' 고 한 칸(반대 검토 2차 LOW 7 — 카드 밖 상한과 같은 몫)
        "noinput_capped": {"cells": sum(1 for c in data["cells"] if c.get("noinput_capped"))},
        "dropped_over_cap": {"rows": sum(int(c["dropped_over_cap"]) for c in ok if c["dropped_over_cap"] is not None),
                             "offcard_calls": len(offcard),
                             "offcard_calls_unknown": sum(1 for c in offcard if c["dropped_over_cap"] is None)},
        # 엔진이 몫에서 끊은 입력(RB3-11 — meta.clipped)을 실은 호출 수와 끊긴 입력 이름
        "clipped": {"calls": len(clipped), "inputs": sorted({name for c in clipped for name in c})},
    }


def _effective(data: Mapping[str, Any]) -> list[dict]:
    out = []
    for v in data["verdicts"]:
        if not v["is_effective"]:
            continue
        applies = "unknown" if v["split"] and v["applies"] == "no" else v["applies"]
        out.append({**v, "klass": verdict_class(v["judgement"], split=v["split"]), "applies_eff": applies})
    return out


def _citation(data: Mapping[str, Any], effective: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict:
    """카드 인용 통과율 — 분모는 실효 판정 행 전부(인용이 없거나 짧은 행도 분모에 든다, X1-06)이고 걸림·걸림 없음·보류를
    따로 낸다. 변경 줄 참조 통과율 — 분모는 applies='yes' 실효 행 전부(참조를 안 낸 yes 행이 깎는다). 서버·앱 대조 갈림은
    받은 호출의 앱 회계(quality_json.app.check_disagree — 잡 보류가 세는 것과 같은 수)의 합이다."""

    def quote(rows: Sequence[Mapping[str, Any]], key: str | None = None) -> dict:
        return rate(sum(1 for r in rows if r["quote_ok"] == 1), len(rows), policy=policy, key=key)

    by = {k: [r for r in effective if r["klass"] == k] for k in ("pos", "neg", "hold")}
    yes = [r for r in effective if r["applies_eff"] == "yes"]
    return {
        "quote": {"flagged": quote(by["pos"], "citation.quote.flagged"), "clear": quote(by["neg"], "citation.quote.clear"),
                  "hold": quote(by["hold"]), "all": quote(effective)},
        "refs": rate(sum(1 for r in yes if r["refs_ok"] == 1), len(yes), policy=policy),
        "check_disagree": sum(int(c["check_disagree"] or 0) for c in data["calls"] if c["state"] == "ok"),
    }


def _flips(data: Mapping[str, Any], effective: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict:
    """뒤집힘 — 순서: fwd 와 rev 가 다른 카드 / agree 가 NULL 이 아닌 카드(같은 본문이라 rev 를 건너뛴 카드는 agree 가 NULL 이라
    빠진다 — X1-20). 단독: 바탕(fwd, 없으면 rev)이 걸림이던 카드와 걸림 없음이던 카드를 갈라 단독이 반대로 간 수를 센다(X1-14).
    fwd·rev 가 갈려 단독이 가른 카드는 바탕이 없으므로 두 비율에 넣지 않고 따로 센다. 변형 갈림(split)은 실효 행 가운데 그 수다."""
    cards: dict[tuple[str, str, str], dict[str, Mapping[str, Any]]] = {}
    for v in data["verdicts"]:
        cards.setdefault((v["unit_id"], v["agent_key"], v["record_id"]), {})[str(v["variant"])] = v
    pos_den = pos_flip = neg_den = neg_flip = base_hold = solo_only = 0
    disputed = Counter()
    for rows in cards.values():
        solo = rows.get("solo")
        if solo is None:
            continue
        agree = next((r["agree"] for r in rows.values() if r["agree"] is not None), None)
        if agree == 0:
            disputed[verdict_class(solo["judgement"])] += 1
            continue
        base = rows.get("fwd") or rows.get("rev")
        if base is None:
            solo_only += 1
            continue
        was, now = verdict_class(base["judgement"]), verdict_class(solo["judgement"])
        if was == "pos":
            pos_den += 1
            pos_flip += int(now == "neg")
        elif was == "neg":
            neg_den += 1
            neg_flip += int(now == "pos")
        else:
            base_hold += 1
    # 순서 뒤집힘의 모집단 — 걸린 것만 이중 판정(dual flagged — C3-9)이면 묶음 전체를 rev 한 1순위 셀(보정)만이다. rev 가 걸린
    # 카드에만 간 셀을 넣으면 걸린 카드만 센 쏠린 비율이 된다. M2(all)는 셀 전부가 보정과 같다.
    calibration = data.get("knobs", {}).get("dual") == "flagged"
    ordered = [r for r in effective if r["agree"] is not None and (not calibration or r["agent_key"] in data["rank1"])]
    # 걸린 fwd 가 rev·단독에서 풀린 비율(C3-9) — fwd 가 걸림인 카드 가운데 실효가 걸림 없음(OK·na)인 것.
    fwd_hits = [rows for rows in cards.values() if (rows.get("fwd") or {}).get("judgement") in review_verify.FLAGGED]
    cleared = sum(1 for rows in fwd_hits if any(v["is_effective"] and v["judgement"] in review_verify.CLEAR
                                                for v in rows.values()))
    return {
        "order": rate(sum(1 for r in ordered if r["agree"] == 0), len(ordered), policy=policy, key="flips.order", upper=True),
        "order_population": "calibration" if calibration else "all",
        "flagged_pos_neg": rate(cleared, len(fwd_hits), policy=policy, key="flips.flagged_pos_neg", upper=True),
        "solo_pos_neg": rate(pos_flip, pos_den, policy=policy, key="flips.solo_pos_neg", upper=True),
        "solo_neg_pos": rate(neg_flip, neg_den, policy=policy, key="flips.solo_neg_pos", upper=True),
        "solo_disputed": {"cards": sum(disputed.values()), "pos": disputed.get("pos", 0), "neg": disputed.get("neg", 0),
                          "hold": disputed.get("hold", 0)},
        "solo_base_hold": base_hold, "solo_only": solo_only,
        "split": rate(sum(1 for r in effective if r["split"]), len(effective), policy=policy),
        # 엔진이 알린 부딪침(RB3-1) — 같은 카드의 다른 판정과 부딪친 줄(dup_conflict)과 보충이 갈아 낀 판정(flipped). 그 카드는
        # 걸린 것처럼 두 번째 판정을 받았다(review_runner._flagged · _solo_set).
        "engine_conflict": {"dup_conflict": sum(int(c["dup_conflict"] or 0) for c in data["calls"] if c["state"] == "ok"),
                            "flipped": sum(int(c["flipped"] or 0) for c in data["calls"] if c["state"] == "ok"),
                            "calls": sum(1 for c in data["calls"] if c["state"] == "ok"
                                         and (int(c["dup_conflict"] or 0) or int(c["flipped"] or 0))),
                            # 판정 행의 flipped_from 을 둘로 가른다 — 모델이 어휘 밖 값을 써 엔진이 고친 것(raw 가 있다)과
                            # 판정을 바꾼 것(raw 가 없다). 둘 다 두 번째 판정을 받는다(D-42) — 이 셈은 보이기만 한다.
                            "coerced": sum(1 for v in data["verdicts"] if v["flipped_row"] and v["flipped_raw"]),
                            "explicit": sum(1 for v in data["verdicts"] if v["flipped_row"] and not v["flipped_raw"])},
    }


def _filter(data: Mapping[str, Any], policy: Mapping[str, Any]) -> dict:
    """거르기(재설계 M3 C3-8) — 잡 손잡이 · 거를 수 있던 칸(두 신호 무관) · 거른 칸 · 표본(끝까지 본 칸의 놓침 넷과 놓침 비율의 95%
    상한 · 보수 상한 — 기준 rq-2 의 filter.audit.risk_miss) · 대표 그림자(따로 센다 — 무작위 표본이 아니다)."""
    cells = data["cells"]
    # 완결 몫과 같은 셈 — 표본 수는 결과를 낸 표본, 놓침은 앞 놓침까지, 비율의 분모는 둘을 더한다(반대 검토 3차 LOW 4 · D-47)
    tally = review_cells.sample_tally(c["audit"] for c in cells)
    shadows = review_cells.sample_tally(c["shadow"] for c in cells)
    risk = tally["counts"]["risk_miss"]
    return {
        "mode": data.get("knobs", {}).get("filter") or "off", "approved": data.get("knobs", {}).get("routing_approved"),
        "would_filter": sum(1 for c in cells if c["rule"] == "both_unrelated"),
        "filtered": sum(1 for c in cells if c["state"] == "na_irrelevant"),
        "audit": {"sampled": tally["sampled"], "counts": tally["counts"],
                  # 기준(rq-2)은 거를 수 있던 칸이 있는 범위에서만 견준다 — 거르기가 없던 범위를 '표본 미달' 로 적지 않는다
                  "risk_miss": rate(risk, tally["n"], policy=policy, upper=True,
                                    key="filter.audit.risk_miss" if any(c["rule"] == "both_unrelated" for c in cells)
                                    else None),
                  "conservative": rate(risk + tally["counts"]["undetermined"], tally["n"], policy=policy, upper=True)},
        "shadow": {"sampled": shadows["sampled"],
                   "risk_miss": rate(shadows["counts"]["risk_miss"], shadows["n"], policy=policy, upper=True)},
    }


def _noinput(data: Mapping[str, Any]) -> dict:
    """입력 결손(재설계 M3 C3-8) — 입력 결손 호출로 닫힌 칸(검토 · 입력 결손)의 전문가 수 · 칸 수 · 결과별."""
    cells = [c for c in data["cells"] if c["basis"] == review_cells.NOINPUT and c["state"] in ("reviewed", "no_input")]
    return {"experts": len({c["agent_key"] for c in cells}), "cells": len(cells),
            "by_outcome": {o: sum(1 for c in cells if c["noinput_outcome"] == o) for o in review_cells.NOINPUT_OUTCOMES}}


def _label(call: Mapping[str, Any]) -> str:
    return f"verdict/{call['variant']}" if call["kind"] == "verdict" else str(call["kind"])


def _seconds(data: Mapping[str, Any], policy: Mapping[str, Any]) -> dict:
    """호출 초 — 받은(ok) 호출의 duration_ms(앱이 잰 벽시계)를 종류별로. 자리 대기(엔진 meta.queued_ms)와 기다림(관문 즉답 —
    아무것도 세지 않은 호출) 수는 따로 낸다."""
    ok = [c for c in data["calls"] if c["state"] == "ok" and c["duration_ms"] is not None]
    labels = list(KINDS) + sorted({_label(c) for c in ok} - set(KINDS))
    waits = Counter(_label(c) for c in data["calls"] if c["state"] == "wait")
    return {
        "kinds": {label: seconds_stat((c["duration_ms"] for c in ok if _label(c) == label), policy=policy)
                  for label in labels},
        "all": seconds_stat((c["duration_ms"] for c in ok), policy=policy),
        "queued": seconds_stat((c["queued_ms"] for c in ok if c["queued_ms"] is not None), policy={}),
        "waits": {**{label: waits.get(label, 0) for label in labels}, "total": sum(waits.values())},
    }


def _table_bytes(store: Any, table: str, where: str, params: Sequence[Any]) -> int:
    """표의 행 바이트 합 — 열마다 length(CAST(열 AS BLOB))(글은 UTF-8 바이트, 수는 그 글자 수, BLOB 은 바이트)의 합. 쪽·색인
    머릿값은 들지 않는다(DB 파일 증가분의 하한)."""
    columns = [r["name"] for r in store.query(f"PRAGMA table_info({table})")]
    expr = " + ".join(f"COALESCE(length(CAST({c} AS BLOB)), 0)" for c in columns)
    row = store.query_one(f"SELECT COALESCE(SUM({expr}), 0) AS n FROM {table} WHERE {where}", tuple(params))
    return int(row["n"] or 0)


def _bytes(store: Any, target_key: str, agent_key: str | None, data: Mapping[str, Any]) -> dict:
    out: dict[str, int] = {}
    tables = AGENT_TABLES if agent_key else TARGET_TABLES
    pairs = sorted(data["packs"])
    for table in tables:
        if table == "rr_card_packs":
            out[table] = sum(_table_bytes(store, table, "agent_key = ? AND pack_key = ?", pair) for pair in pairs)
        elif agent_key and table != "rr_unit_builds" and table != "rr_units":
            out[table] = _table_bytes(store, table, "target_key = ? AND agent_key = ?", (target_key, agent_key))
        else:
            out[table] = _table_bytes(store, table, "target_key = ?", (target_key,))
    return {"tables": out, "total": sum(out.values())}


def _pilot(store: Any, target_key: str, agent_key: str | None, data: Mapping[str, Any],
           effective: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict:
    """M2 실측표 — 칸당 호출 수(낸 호출 / 호출이 간 칸), 양성 비율(실효 걸림 / 실효 행), 훑기 '무관' 비율(rel=no 단위 / 훑기가
    답한 단위 — 분류에 쓰지 않는다), 토큰(받은 호출의 합)과 자/토큰(보충 없이 한 번에 받은 호출의 prompt_chars 합 / tokens_in
    합 — 보충이 든 호출의 tokens_in 은 시도마다 프롬프트를 다시 세어 비가 흐려진다), 새 표 바이트."""
    cell_calls = [c for c in data["calls"] if c["unit_id"] is not None and c["state"] in CALL_DONE_STATES]
    touched = {(c["unit_id"], c["agent_key"]) for c in cell_calls}
    rel = Counter()
    for head in data["heads"]:
        try:
            sweep = json.loads(head["sweep_json"] or "{}")
        except ValueError:
            sweep = {}
        units = sweep.get("units") if isinstance(sweep, dict) and isinstance(sweep.get("units"), dict) else {}
        for unit_id, entry in units.items():
            if unit_id in set(data["units"]) and isinstance(entry, Mapping):
                rel[str(entry.get("rel"))] += 1
    answered = sum(rel.get(r, 0) for r in SWEEP_ANSWERED)
    ok = [c for c in data["calls"] if c["state"] == "ok"]
    plain = [c for c in ok if c["attempts"] == 1 and c["prompt_chars"] is not None and c["tokens_in"]]
    chars, tokens = sum(int(c["prompt_chars"]) for c in plain), sum(int(c["tokens_in"]) for c in plain)
    return {
        "calls_per_cell": {"value": _ratio(len(cell_calls), len(touched)), "num": len(cell_calls), "den": len(touched)},
        "positive": rate(sum(1 for r in effective if r["klass"] == "pos"), len(effective), policy=policy),
        "sweep_irrelevant": {**rate(rel.get("no", 0), answered, policy=policy), "stamp": rel.get("stamp", 0),
                             "error": rel.get("error", 0),
                             # 거르기 분류의 훑기 신호다(C3-6) — 잡 거르기가 off 면 쓰지 않는다
                             "used_for_routing": (data.get("knobs", {}).get("filter") or "off") != "off"},
        "tokens": {"in": sum(int(c["tokens_in"] or 0) for c in ok), "out": sum(int(c["tokens_out"] or 0) for c in ok),
                   "calls": len(ok), "calls_unknown": sum(1 for c in ok if c["tokens_in"] is None)},
        "chars_per_token": {"value": _ratio(chars, tokens), "num": chars, "den": tokens, "calls": len(plain),
                            "basis": "attempts=1"},
        "bytes": _bytes(store, target_key, agent_key, data),
    }


def _bounds(node: Any, path: str = "") -> tuple[list[str], list[str]]:
    """기준을 단 수치를 훑어 (밖, 표본 미달로 견주지 못함) 경로 목록."""
    out: list[str] = []
    unchecked: list[str] = []
    if isinstance(node, Mapping):
        if "threshold" in node and "within" in node:
            if node["within"] is False:
                out.append(path)
            elif node["within"] is None:
                unchecked.append(path)
        for key, value in node.items():
            if key in ("threshold", "revs"):
                continue
            sub_out, sub_unchecked = _bounds(value, f"{path}.{key}" if path else str(key))
            out += sub_out
            unchecked += sub_unchecked
    return out, unchecked


def compute(store: Any, target_key: str, *, agent_key: str | None = None) -> dict:
    """대상(또는 그 대상의 전문가 한 명)의 검토 품질 수치. 같은 원장이면 같은 dict 다(시각을 싣지 않는다 — S10 보고서의 바이트가
    같게). 반환 {policy_version, target_key, agent_key, model, prompt_rev, limits_rev, k, revs, ledger_hash, grid, cards,
    truncation, citation, flips, seconds, pilot, out_of_bounds[], unchecked[]}."""
    policy = load_policy()
    data = _load(store, target_key, agent_key)
    effective = _effective(data)
    stamps = _stamps(data["calls"], data["heads"])
    result: dict[str, Any] = {
        "policy_version": policy.get("policy_version"), "target_key": target_key, "agent_key": agent_key,
        "model": stamps["model"], "prompt_rev": stamps["prompt_rev"], "limits_rev": stamps["limits_rev"], "k": stamps["k"],
        "revs": stamps["revs"], "ledger_hash": _ledger_hash(data),
        "grid": _grid(data, policy), "cards": _cards(data, policy), "truncation": _truncation(data, policy),
        "citation": _citation(data, effective, policy), "flips": _flips(data, effective, policy),
        "filter": _filter(data, policy), "noinput": _noinput(data),
        "seconds": _seconds(data, policy), "pilot": _pilot(store, target_key, agent_key, data, effective, policy),
    }
    judge = judge_llm(store, target_key, agent_key)
    if judge is not None:
        # 판단 LLM(Claude 길 X-2) — 외부 응답자 호출이나 llm_mismatch 가 있을 때만 싣는다(GLM 대상의 결과는 종전 그대로)
        result["judge_llm"] = judge
    out, unchecked = _bounds(result)
    result["out_of_bounds"] = out
    result["unchecked"] = unchecked
    return result


def judge_llm(store: Any, target_key: str, agent_key: str | None = None) -> dict | None:
    """판단 LLM(Claude 길 X-2) — 받은(ok) 호출(활성 단위 · 단위 없는 훑기 · 요약) 가운데 외부 응답자가 답한 것(model 'external' — 엔진이
    그 길의 답에만 단다)과 이 박스의 LLM 이 답한 것, 그리고 claude 잡인데 외부 응답자 답이 아니었던 호출(llm_mismatch — 그 행의
    quality_json.app). 외부 · 어긋남이 둘 다 0 이면 None(GLM 대상 — 글을 바꾸지 않는다). 원장 지문(`_ledger_hash`)의 행과 따로
    센다(GLM 원장의 지문이 바뀌지 않게). claude 잡이 한 번도 없던 대상은 호출 원장을 훑지 않는다(잡 표 한 번 — 359명 원장의 품질
    계산에 훑기를 하나 더 얹지 않게)."""
    if store.query_one("SELECT 1 FROM rr_jobs WHERE target_key = ? AND CASE WHEN json_valid(params_json) THEN"
                       " json_extract(params_json, '$.llm') END = ? LIMIT 1", (target_key, LLM_CLAUDE)) is None:
        return None
    extra, params = _scope_sql(agent_key)
    alive = set(review_cells.active_unit_ids(store, target_key))
    rows = [r for r in _rows(store,
        "SELECT unit_id, model, json_extract(quality_json, '$.app.llm_mismatch') IS NOT NULL AS mismatch FROM rr_review_calls"
        f" WHERE target_key = ? AND state = 'ok'{extra}", [target_key, *params])
        if r["unit_id"] is None or r["unit_id"] in alive]
    external = sum(1 for r in rows if r["model"] == EXTERNAL_MODEL)
    mismatch = sum(1 for r in rows if r["mismatch"])
    if not external and not mismatch:
        return None
    return {"external": external, "other": len(rows) - external, "mismatch": mismatch}


def judge_text(judge: Mapping[str, Any] | None) -> str:
    """판단 LLM 글 — 외부 응답자 호출만이면 '판단 LLM: Claude(외부, 사용자 신고 모델)', 섞였으면 판마다 호출 수, 어긋남이 있으면 그
    수와 뜻. None 이면 빈 글(GLM — 종전 글 그대로)."""
    if not judge:
        return ""
    parts = []
    if judge["external"]:
        parts.append(f"판단 LLM: {JUDGE_CLAUDE}" + (f" {_n(judge['external'])}회 · 이 박스의 LLM {_n(judge['other'])}회"
                                                    if judge["other"] else ""))
    else:
        parts.append(f"판단 LLM: 이 박스의 LLM {_n(judge['other'])}회(Claude 로 고른 잡이지만 외부 응답자 답이 없다)")
    if judge["mismatch"]:
        parts.append(f"판단 LLM 어긋남(llm_mismatch) {_n(judge['mismatch'])}회 — Claude 로 고른 잡의 호출이 외부 응답자로 가지 않고 이 박스의"
                     " LLM 으로 돌았다(포털 중계가 llm 을 넘기지 않았다) · 그 답은 Claude 답으로 적지 않았다")
    return " · ".join(parts)


# ---------------------------------------------------------------- 문면
def _n(value: Any) -> str:
    if value is None:
        return "모름"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.3f}"
    return f"{int(value):,}"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def fmt_rate(metric: Mapping[str, Any], note: str = "") -> str:
    """비율 — 'P% (num/den)' · 상한이 있으면 'P% (num/den, 95% 상한 U%)' · 표본 0 이면 '미측정(표본 0)' · 미달이면
    '표본 수 미달(n=den)'. 0% 로 적지 않는다(WP5b 3.11.3 규칙 2). `note` 는 괄호 안 끝에 붙는다."""
    if metric.get("value") is None:
        head = "미측정(표본 0" if not metric.get("den") else f"표본 수 미달(n={_n(metric['den'])}"
        return f"{head}{', ' + note if note else ''})"
    tail = f", 95% 상한 {_pct(metric['upper95'])}" if metric.get("upper95") is not None else ""
    return f"{_pct(metric['value'])} ({_n(metric['num'])}/{_n(metric['den'])}{tail}{', ' + note if note else ''})"


def _fmt_mean(metric: Mapping[str, Any], note: str = "") -> str:
    if metric.get("value") is None:
        return f"미측정(표본 0{', ' + note if note else ''})"
    return f"{metric['value']:.3f} ({_n(metric['num'])}/{_n(metric['den'])}{', ' + note if note else ''})"


def _fmt_secs(stat: Mapping[str, Any]) -> str:
    if not stat["n"]:
        return "미측정(표본 0)"
    return (f"p50 {stat['p50']['value']:.3f} · p95 {stat['p95']['value']:.3f} · 최대 {stat['max']['value']:.3f}"
            f" (n={_n(stat['n'])})")


def _q(text: Any) -> str:
    """원천 글(모델 이름·판·전문가 키)은 «» 로 감싼다 — 린터 밖이다."""
    return "«" + str(text).replace("«", "").replace("»", "") + "»"


def _stamp_text(result: Mapping[str, Any]) -> str:
    revs = result["revs"]

    def one(name: str, single: Any, values: Sequence[Mapping[str, Any]]) -> str:
        if single:
            return f"{name} {_q(single)}"
        if not values:
            return f"{name} 미측정"
        return f"{name} " + " · ".join(f"{_q(v['value'])}({_n(v['calls'])}회)" for v in values)

    prompts = [{"value": f"{k}={v['value']}", "calls": v["calls"]} for k, items in revs["prompt_rev"].items() for v in items]
    ks = revs.get("k") or []
    k_text = (f"K {_n(result['k'])}" if result.get("k") is not None else
              "K " + " · ".join(f"{_n(v['value'])}({_n(v['experts'])}명)" for v in ks) if ks else "K 미측정")
    parts = [one("모델", result["model"], revs["model"]), one("프롬프트 판", result["prompt_rev"], prompts), k_text,
             one("창 판", result["limits_rev"], revs["limits_rev"])]
    if revs["mixed"]:
        # 판마다 따로 다시 세지 않는다 — 판마다 호출 수만 단다(M2 의 선택, _stamps 참조).
        parts.append("판 섞임 — 수는 판을 가르지 않고 합했다")
    return " · ".join(parts)


def _bound_label(path: str) -> str:
    if path.startswith("seconds.kinds."):
        return f"호출 초 p95({path.split('.')[-2]})"
    if path.startswith("seconds.all."):
        return "호출 초 p95(전체)"
    return LABELS.get(path, path)


def _bound_text(result: Mapping[str, Any], path: str) -> str:
    node: Any = result
    for key in path.split("."):
        node = node[key]
    threshold = node["threshold"]
    label = _bound_label(path)
    if path.startswith("seconds."):
        return f"{label} {node['value']:.3f} > {_n(threshold.get('max'))}"
    if "upper_max" in threshold and node.get("upper95") is not None and node["upper95"] > threshold["upper_max"]:
        return f"{label} {_pct(node['upper95'])} > {_pct(threshold['upper_max'])}"
    if "max" in threshold and node["value"] > threshold["max"]:
        return f"{label} {_pct(node['value'])} > {_pct(threshold['max'])}"
    return f"{label} {_pct(node['value'])} < {_pct(threshold['min'])}"


def render_text(result: Mapping[str, Any]) -> str:
    """compute 결과 → 문면(줄마다 [칸] 머리). 수는 전부 result 의 수이고 판단어 린터를 지난다."""
    grid, cards, trunc = result["grid"], result["cards"], result["truncation"]
    cite, flips, secs, pilot = result["citation"], result["flips"], result["seconds"], result["pilot"]
    who = f" · 전문가 {_q(result['agent_key'])}" if result.get("agent_key") else ""
    judge = judge_text(result.get("judge_llm"))
    lines = [f"[{TITLE} — 코드 계측{who} · 기준판 {result['policy_version']} · {judge + ' · ' if judge else ''}{_stamp_text(result)}"
             f" · 원장 {_q(result['ledger_hash'])}]"]
    st, basis = grid["by_state"], grid["reviewed_by_basis"]
    scope = grid["in_scope"]
    waiting = (scope["by_state"]["pending"] + scope["by_state"]["running"]) if scope else st["pending"] + st["running"]
    unset = f" · 바탕 모름 {_n(basis['unset'])}" if basis.get("unset") else ""
    gap = (f" · 격자 빠짐 {_n(grid['missing'])}칸 · 남는 칸 {_n(grid['extra'])}"
           if grid["missing"] or grid["extra"] else "")
    lines.append(
        f"[격자] 칸 {_n(grid['cells'])} = 전문가 {_n(grid['experts'])} × 단위 {_n(grid['units'])}{gap}"
        f" · 검토 {_n(st['reviewed'])}(카드 대조 {_n(basis['cards'])} · 배경 카드뿐 {_n(basis['background'])}"
        f" · 역할만 {_n(basis['role_only'])} · 긴 문서 발췌만 {_n(basis['search_only'])}"
        f" · 입력 결손 호출 {_n(basis['noinput'])}{unset}) · 무관 {_n(st['na_irrelevant'])}"
        f" · 입력 결손 {_n(st['no_input'])}"
        f" · 미완 {_n(st['failed'])}(처분 전 {_n(grid['failed_open'])}) · 넘김 {_n(st['skipped'])}"
        f" · 대기 {_n(waiting)} · 범위 밖 대기 {_n(grid['out_of_scope_pending'])}"
        f" · 형식만 채운 칸 {fmt_rate(grid['form_only'])}"
        f" · 뒤집힘(걸림 없음→걸림) {fmt_rate(flips['solo_neg_pos'])}")
    cl = cards["lines"]
    residual = f" · 셈 어긋남 {_n(cards['residual'])}" if cards["residual"] else ""
    lines.append(
        f"[카드] 분모 {_n(cards['denominator'])} = Σ 칸마다 그 전문가 묶음의 카드 전부 · 판정 받음 {fmt_rate(cl['judged'])}"
        f" · 검토 칸인데 판정 없음 {fmt_rate(cl['unjudged'])} · 배경 본문으로 읽힘 {fmt_rate(cl['background_full'])}"
        f" · 배경 제목만 {fmt_rate(cl['background_title_only'])} · 배경 안 실림 {fmt_rate(cl['background_unsent'])}"
        f" · 본문 없음 {fmt_rate(cl['no_body'])} · 입력 결손 호출로 본 칸 {fmt_rate(cl['noinput_reviewed'])}"
        f" · 미완·넘김 칸 {fmt_rate(cl['failed'])} · 대기 칸 {fmt_rate(cl['open'])}"
        f" · 범위 밖 칸 {fmt_rate(cl['out_of_scope'])} · 무관 칸 {fmt_rate(cl['filtered'])}"
        f" · 입력 결손 칸 {fmt_rate(cl['no_input'])}{residual}"
        f" · 묶음 미확보 전문가 {_n(cards['experts_without_pack'])}명({_n(cards['cells_without_pack'])}칸 — 분모 밖)")
    cov = cards["coverage"]
    unknown = (f" · 커버리지를 적기 전에 닫힌 칸 {_n(cov['unknown_cells'])}(모름)" if cov["unknown_cells"] else "")
    lines.append(
        f"[누락 0 증명] 닫힌 칸 {_n(cov['cells'])} · 카드 × 칸 {_n(cov['pairs'])} = 판정 {_n(cov['judged'])}"
        f" + 카드 밖·입력 결손 전문 {_n(cov['full'])} + 훑기 전문 대조만 {_n(cov['swept_only'])} + 놓침 {_n(cov['missed'])}"
        f" · 훑기에 걸렸는데 제목만 {_n(cov['hit_title'])}{unknown}")
    flt, gap = result["filter"], result["noinput"]
    audit_ = flt["audit"]
    counts = audit_["counts"]
    lines.append(
        f"[거름] 거르기 {_q(flt['mode'])}{'' if flt['approved'] else '(변경 → 영역 표 승인 전 — 거르지 않는다)'}"
        f" · 거를 수 있던 칸 {_n(flt['would_filter'])} · 거른 칸 {_n(flt['filtered'])}"
        f" · 표본으로 끝까지 본 칸 {_n(audit_['sampled'])}(놓침 {_n(counts['risk_miss'])} · 관련 {_n(counts['relevance_miss'])}"
        f" · 가릴 수 없음 {_n(counts['undetermined'])} · 지킴 {_n(counts['kept'])})"
        f" · 놓침 비율 {fmt_rate(audit_['risk_miss'])} · 보수(놓침 + 가릴 수 없음) {fmt_rate(audit_['conservative'])}"
        f" · 대표 그림자 {_n(flt['shadow']['sampled'])}칸 놓침 {fmt_rate(flt['shadow']['risk_miss'])}(무작위 표본이 아니다)")
    lines.append(
        f"[입력 결손] 입력 결손 호출로 닫은 칸 {_n(gap['cells'])}(전문가 {_n(gap['experts'])}명) · 영향 있음"
        f" {_n(gap['by_outcome']['impact'])} · 모름 {_n(gap['by_outcome']['unknown'])} · 입력이 와야 봄"
        f" {_n(gap['by_outcome']['request'])} · 영향 없음 {_n(gap['by_outcome']['none'])}")
    cap, drop, clip = trunc["offcard_capped"], trunc["dropped_over_cap"], trunc["clipped"]
    lines.append(
        f"[절단] 호출 {fmt_rate(trunc['calls'])} · 호출 모름 {fmt_rate(trunc['calls_unknown'])}"
        f" · 검토 칸 {fmt_rate(trunc['cells'])} · 검토 칸 모름 {fmt_rate(trunc['cells_unknown'])}"
        f" · 품질 한도 넘김 호출 {fmt_rate(trunc['soft_over'])}"
        f" · 카드 밖 상한 닿음 {_n(cap['cells'])}칸({_n(cap['hits'])}번)"
        f" · 입력 결손 다시 묻기 상한 닿음 {_n(trunc['noinput_capped']['cells'])}칸"
        f" · 상한 밖 버림 {_n(drop['rows'])}줄(카드 밖 호출 {_n(drop['offcard_calls'])} 가운데 모름 {_n(drop['offcard_calls_unknown'])})"
        f" · 몫에서 끊은 입력 {_n(clip['calls'])}호출" + (f"({', '.join(_q(x) for x in clip['inputs'])})" if clip["inputs"] else ""))
    quote = cite["quote"]
    lines.append(
        f"[인용] 카드 인용 대조 통과 — 걸림 {fmt_rate(quote['flagged'])} · 걸림 없음 {fmt_rate(quote['clear'])}"
        f" · 보류 {fmt_rate(quote['hold'])} · 전체 {fmt_rate(quote['all'])}"
        f" · 변경 줄 참조 통과 {fmt_rate(cite['refs'])} · 서버·앱 대조 갈림 {_n(cite['check_disagree'])}건")
    dis = flips["solo_disputed"]
    lines.append(
        f"[뒤집힘] 순서(fwd·rev 다름{' — 보정 모집단(1순위 셀)' if flips['order_population'] == 'calibration' else ''})"
        f" {fmt_rate(flips['order'])}"
        f" · 걸린 fwd 가 두 번째 판정에서 풀림 {fmt_rate(flips['flagged_pos_neg'])}"
        f" · 단독 걸림→걸림 없음 {fmt_rate(flips['solo_pos_neg'])}"
        f" · 단독 걸림 없음→걸림 {fmt_rate(flips['solo_neg_pos'])}"
        f" · fwd·rev 가 갈려 단독이 가른 카드 {_n(dis['cards'])}(걸림 {_n(dis['pos'])} · 걸림 없음 {_n(dis['neg'])}"
        f" · 보류 {_n(dis['hold'])}) · 바탕이 보류 {_n(flips['solo_base_hold'])} · 단독뿐 {_n(flips['solo_only'])}"
        f" · 변형 갈림(보류로 둠) {fmt_rate(flips['split'])}"
        f" · 엔진이 알린 부딪침 {_n(flips['engine_conflict']['dup_conflict'])}줄"
        f" · 보충이 갈아 낀 줄 {_n(flips['engine_conflict']['flipped'])}(판정 행 가운데 어휘 밖 값을 고친 것"
        f" {_n(flips['engine_conflict']['coerced'])} · 판정을 바꾼 것 {_n(flips['engine_conflict']['explicit'])} — 판정 변화의 수가"
        " 아니다, 그 카드는 두 번째 판정을 받았다)")
    kinds = " · ".join(f"{label} {_fmt_secs(stat)}" for label, stat in secs["kinds"].items())
    waits = " · ".join(f"{label} {_n(n)}" for label, n in secs["waits"].items() if label != "total")
    lines.append(
        f"[호출 초] {kinds} · 전체 {_fmt_secs(secs['all'])} · 자리 대기 {_fmt_secs(secs['queued'])}"
        f" · 기다림 {_n(secs['waits']['total'])}건({waits})")
    sweep, tokens, chars = pilot["sweep_irrelevant"], pilot["tokens"], pilot["chars_per_token"]
    table_bytes = " · ".join(f"{name} {_n(n)}" for name, n in pilot["bytes"]["tables"].items())
    lines.append(
        f"[실측] 칸당 호출 {_fmt_mean(pilot['calls_per_cell'])} · 걸림 비율 {fmt_rate(pilot['positive'])}"
        f" · 훑기 무관 {fmt_rate(sweep, ('거르기 분류의 훑기 신호' if sweep['used_for_routing'] else '분류에 쓰지 않음(거르기 끔)') + f' — stamp {_n(sweep["stamp"])} · 답 없음 {_n(sweep["error"])}')}"
        f" · 토큰 입력 {_n(tokens['in'])} · 출력 {_n(tokens['out'])}(받은 호출 {_n(tokens['calls'])} 가운데 모름"
        f" {_n(tokens['calls_unknown'])}) · 자/토큰 {_fmt_mean(chars, f'보충 없는 호출 {_n(chars["calls"])}')}"
        f" · 새 표 바이트 {_n(pilot['bytes']['total'])}({table_bytes})")
    out = result["out_of_bounds"]
    bound = f"[기준] 밖 {len(out)}항" + (" — " + " · ".join(_bound_text(result, p) for p in out) if out else "")
    if result["unchecked"]:
        bound += (f" · 표본 미달로 견주지 못한 기준 {len(result['unchecked'])}항"
                  f"({', '.join(_bound_label(p) for p in result['unchecked'])})")
    lines.append(bound)
    return "\n".join(lines)


def _no_cells_line(store: Any, target_key: str) -> str:
    row = store.query_one("SELECT flow FROM rr_targets WHERE target_key = ?", (target_key,))
    if row is not None and row["flow"] == "cells":
        return f"[{TITLE} — 이 대상은 카드 대조 방식인데 칸 원장이 아직 없다(검토 잡 전)]"
    return f"[{TITLE} — 이 대상은 옛 방식이라 칸 원장이 없다]"


def block(store: Any, target_key: str, *, agent_key: str | None = None) -> dict:
    """통합 보고서·진행판이 싣는 품질 블록 — {key:'quality', title, text, json(compute 결과)}. 셀 원장이 없는 대상(옛 방식 · 검토
    잡 전)은 문면 한 줄만 낸다(0 으로 채운 블록을 내지 않는다)."""
    result = compute(store, target_key, agent_key=agent_key)
    extra, params = _scope_sql(agent_key)
    has_cells = store.query_one(f"SELECT 1 FROM rr_review_cells WHERE target_key = ?{extra} LIMIT 1",
                                (target_key, *params)) is not None
    text = render_text(result) if has_cells else _no_cells_line(store, target_key)
    return {"key": BLOCK_KEY, "title": TITLE, "text": text, "json": result}


def progress_hook(store: Any, target_key: str, job_id: str) -> dict:
    """검토 루프 진행판의 품질 칸(`review_runner.QUALITY_HOOK`) — 블록에 잡 id 와 센 시각을 붙인다."""
    return {**block(store, target_key), "job_id": job_id, "computed_at": now_epoch()}
