# 다음 과제 브리프 조립 — prior_evidence E0~E9 예산표(plan §5.6)·유사 검색(§5.7)·계보 없는 재사용 회수(§5.9)
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app import config, render, taxonomy
from app.common import canonical_json, new_uuid, now_epoch, parse_ref
from app.errors import AppError

# ---------------------------------------------------------------- 공유 상수(plan §0.6·§5.6.1)
# 엔진 클램프(deliberation.py `_resolve_opts` :464-467 / hwax-deliberate.js :128-130).
CLAMP_SOURCE, CLAMP_TOOL, CLAMP_ARGS, CLAMP_RESULT = 120, 80, 400, 2000
# 엔진 누적 예산(PY :2165 / JS :131). 항목마다 라인 길이를 재고 넘는 항목부터 통째로 드롭한다.
ENGINE_BUDGET = 11000
EVIDENCE_MAX_ITEMS = 12

# 항목별 라인 상한. 합 10600 ≤ 11000 이라 드롭 0 이 산술로 보장된다(plan §5.6.1).
# E5 는 세 블록(E5+ 700 · E5− 300 · E10 500)이라 1500 이고, 그 500 은 E1(−250)·E6(−150)·E9(−100)
# 재배분으로 낸다 — 합 10600 은 그대로다(plan §5.6.1 '부정 선례').
CAPS: dict[str, int] = {
    "E0": 500, "E0c": 1000, "E1": 1650, "E2": 1100, "E3": 700, "E4": 600,
    "E5": 1500, "E6": 650, "E7": 1400, "E8": 500, "E9": 600, "M": 400,
}
# E5 안쪽 블록 상한(plan §5.6.1). 정본은 E10 을 500 이라 적지만 그 합 1500 은 CAPS['E5'] 에 들어가지 않는다 —
# CAPS 는 오버헤드(line_overhead 52)까지 포함하는 **라인** 상한이라 result 실효 한도가 1448 이고, 여기에
# 프레이밍 56 + 블록 머리글 3줄 51 이 먼저 든다. 세 블록을 정본 값대로 채우면 1608 이 필요해 160 을 넘기고,
# clip_lines 가 뒤에서부터 버리므로 맨 뒤 E10 이 통째로 조용히 사라진다. 그래서 E10 만 실효 잔여로 맞춘다
# (E5+·E5− 는 정본 값 그대로 — 선례를 깎지 않는다, context-notes D18).
E5_POSITIVE_CAP, E5_NEGATIVE_CAP, E5_FIELD_CAP = 700, 300, 340
# 그 실효 잔여의 근거 — CAPS['E5'] 에서 먼저 드는 오버헤드다(line_overhead 52 + 프레이밍 ≤56 +
# 블록 머리글 3줄 51). 세 캡의 합이 `CAPS['E5'] − E5_STRUCTURAL` 를 넘으면 clip_lines 가 뒤에서부터
# 버려 맨 뒤 E10 이 통째로 사라진다. 주석으로만 두면 다시 틀어지므로 시험이 이 부등식을 지킨다.
E5_STRUCTURAL = 159
ITEM_ORDER: tuple[str, ...] = ("E0", "E0c", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "M")

# E7 고정 슬롯(plan §5.6.3) — 좌석당 줄 220자, 좌석 합 1100자. 다른 항목이 비어도 늘리지 않는다.
E7_SEAT_LINE = 220
E7_SEAT_TOTAL = 1100
# 프레이밍 줄 상한(plan §5.6.1) — 결측 문구도 80자 이하다.
FRAMING_MAX = 80

# 항목 키 → (source, 원천 표 이름). args 는 항목마다 따로 만든다.
_SOURCES: dict[str, tuple[str, str]] = {
    "E0": ("rr_scope", "rr_targets"),
    "E0c": ("seat_contract", "seat-contract.v1.json"),
    "E1": ("rr_diff", "summary_text"),
    "E2": ("rr_diff.events", "rr_diff_events"),
    "E3": ("rr_diff.dims", "dims_delta"),
    "E4": ("rr_diff.results", "result_delta"),
    "E5": ("rr_registry.prior", "rr_registry"),
    "E6": ("rr_character.similar", "rr_character"),
    "E7": ("rr_seat_opinions.self", "rr_seat_opinions"),
    "E8": ("rr_delta_priors", "rr_delta_priors"),
    "E9": ("rr_state.warnings_rules", "rr_states"),
    "M": ("user_memo", "rr_jobs"),
}

# 인용 추적 대상 스킴(plan §5.6.4).
_TRACKED_SCHEMES = ("reg", "narr", "rule", "c", "d")
_REF_TOKEN = re.compile(r"\b(?:reg|narr|rule|c|d|sig|warn|gate|p|e|rpt|inc|card):[^\s\]|]+")

# §7.3 교집합 가중.
# 별칭으로 이어진 subject 는 정확 매치보다 한 급 낮게 센다(연결이 사람 확정 별칭에 기댄다).
_PATH_WEIGHT = {"lineage": 3.0, "vector": 2.0, "text": 1.0, "subject": 2.0, "subject·별칭": 1.5}
# 벡터 경로가 열리는 최소 코퍼스(plan §7.3 2단계).
VECTOR_MIN_CORPUS = 5


# ---------------------------------------------------------------- 라인·절단 유틸(엔진과 같은 식)
def evidence_line(item: Mapping[str, Any]) -> str:
    """엔진이 예산에 누적하는 라인 문자열 `· [{source} · {tool}({args})] {result}`.

    tool 이나 args 가 비면 그 부분과 구분자가 빠진다(plan §5.6.1 오버헤드 규칙).
    """
    source = str(item.get("source") or "")
    tool = str(item.get("tool") or "")
    args = str(item.get("args") or "")
    result = str(item.get("result") or "")
    meta = ""
    if tool:
        meta = f" · {tool}" + (f"({args})" if args else "")
    return f"· [{source}{meta}] {result}"


def line_overhead(item: Mapping[str, Any]) -> int:
    """result 를 뺀 라인 길이. result 의 실효 상한은 CAP[key] − 이 값이다."""
    return len(evidence_line({**dict(item), "result": ""}))


def _ellipsis(n: int) -> str:
    return f"…({n}줄 생략)"


def clip_lines(text: str, limit: int) -> str:
    """줄 경계로 자르고 잘린 줄 수를 `…(n줄 생략)` 으로 남긴다(plan §5.6.2 절단 규칙).

    한 줄이 남은 자리를 넘으면 그 줄부터 통째로 뺀다 — 참조 id 가 잘린 채 실리지 않게 한다.
    """
    text = "" if text is None else str(text)
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    lines = text.split("\n")
    reserve = 1 + len(_ellipsis(len(lines)))  # 줄바꿈 + 최악(전부 생략) 길이
    kept: list[str] = []
    used = 0
    for line in lines:
        add = len(line) + (1 if kept else 0)
        if used + add + reserve <= limit:
            kept.append(line)
            used += add
        else:
            break
    dropped = len(lines) - len(kept)
    if dropped <= 0:
        return "\n".join(kept)
    marker = _ellipsis(dropped)
    if not kept:
        return marker if len(marker) <= limit else ""
    return "\n".join(kept) + "\n" + marker


def _framing(source: str) -> str:
    """result 첫 줄 — `[검증 대상 — 결론 아님 · 원천: <source> · 생성: <YYYY-MM-DD>]`(≤80자)."""
    day = datetime.fromtimestamp(now_epoch(), tz=timezone.utc).strftime("%Y-%m-%d")
    return f"[검증 대상 — 결론 아님 · 원천: {source} · 생성: {day}]"[:FRAMING_MAX]


def _body(source: str, lines: Sequence[str]) -> str:
    """프레이밍 줄 + 본문 줄을 하나의 result 문자열로 잇는다."""
    return "\n".join([_framing(source), *[str(x) for x in lines if str(x) != ""]])


# ---------------------------------------------------------------- 작은 도우미
def _j(raw: Any, default: Any) -> Any:
    """JSON 문자열을 파싱한다. 비었거나 깨지면 default(예외 없음 — 브리프가 막히지 않는다)."""
    if raw is None or raw == "":
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return value if value is not None else default


def _s(value: Any, fallback: str = "") -> str:
    return fallback if value is None else str(value)


# ---------------------------------------------------------------- 원천 문자열 위생(plan §3.4.1·§5.6.1)
# 좌석 계약 `_common` 의 인젝션 방어는 «…» 표시에 전적으로 기댄다 — 그러니 소스 앱·사람·이전 LLM 이 쓴
# 문자열은 이 두 함수를 거쳐서만 브리프 줄에 들어간다. 코드가 만든 라벨(`[d:`·`conf=`·`rel=`)은 밖에 둔다.
_suspect_sink = threading.local()


def begin_suspect_queue(store: Any, owner_sub: str | None) -> None:
    """이 스레드의 `suspect_text` 적재 대상을 연다(prior_evidence 진입에서 부른다)."""
    _suspect_sink.store = store
    _suspect_sink.owner_sub = owner_sub
    _suspect_sink.seen = set()


def end_suspect_queue() -> None:
    _suspect_sink.store = None
    _suspect_sink.owner_sub = None
    _suspect_sink.seen = None


def _on_suspect(payload: Mapping[str, Any]) -> None:
    """`rr_curation_queue(kind='suspect_text')` 1행. 같은 sha1 이 이미 열려 있으면 넣지 않는다."""
    store = getattr(_suspect_sink, "store", None)
    owner_sub = getattr(_suspect_sink, "owner_sub", None)
    if store is None or not owner_sub:
        return
    sha1 = str(payload.get("sha1") or "")
    seen = getattr(_suspect_sink, "seen", None)
    if seen is not None:
        if sha1 in seen:
            return
        seen.add(sha1)
    row = store.query_one(
        "SELECT id FROM rr_curation_queue WHERE kind = 'suspect_text' AND status = 'open'"
        " AND payload_json LIKE ?", (f'%"sha1":"{sha1}"%',))
    if row is not None:
        return
    store.execute(
        "INSERT INTO rr_curation_queue(id, owner_sub, kind, payload_json, status, created_at)"
        " VALUES (?,?, 'suspect_text', ?, 'open', ?)",
        (new_uuid(), owner_sub, canonical_json(dict(payload)), now_epoch()),
    )


def _q(value: Any, kind: str = "label") -> str:
    """외부 출처 문자열 한 칸 → 위생 통과본을 «…» 로 감싼 표기(적중은 `«[suspect_text …]»`)."""
    return render.sanitize_source_text(value, kind, on_suspect=_on_suspect)


def _ref_name(value: Any, kind: str = "label") -> str:
    """참조 토큰 자리(`[d:<name>]`)의 이름 — 위생만 하고 «…» 는 벗긴다(토큰이 기계 판독 가능해야 한다).

    인젝션 어휘에 걸리면 이름 대신 `suspect_text-<sha1[:12]>` 가 토큰이 되고 원문은 큐로 간다.
    """
    quoted = _q(value, kind)
    inner = quoted[1:-1] if quoted.startswith(render.QUOTE_OPEN) and quoted.endswith(render.QUOTE_CLOSE) else quoted
    if inner.startswith("[suspect_text "):
        return "suspect_text-" + inner[len("[suspect_text "):-1]
    return inner


def _cut(text: Any, n: int) -> str:
    """한 필드를 n 자로 자른다(줄바꿈은 공백으로 접어 한 줄 규약을 지킨다)."""
    s = " ".join(_s(text).split())
    return s if len(s) <= n else s[:n]


def _resolve_ckey(store, ckey: str) -> str:
    """merged_into 를 끝까지 따라가 대표 ckey 로 치환한다(plan §5.9.1).

    정본은 sameas.resolve_ckey 이고 그 모듈이 있으면 그것을 쓴다.
    """
    try:
        from app.sameas import resolve_ckey as _canonical  # type: ignore
    except ImportError:
        pass
    else:
        return _canonical(store, ckey)
    seen: set[str] = set()
    current = ckey
    while current and current not in seen:
        seen.add(current)
        row = store.query_one("SELECT merged_into FROM rr_part_keys WHERE ckey=?", (current,))
        if row is None or not row["merged_into"]:
            return current
        current = row["merged_into"]
    return ckey


def _visibility_clause(owner_sub: str | None, alias: str = "") -> tuple[str, list[Any]]:
    """소유자 또는 visibility='org' 만 보는 WHERE 조각. owner_sub 가 없으면 조건 없음."""
    prefix = f"{alias}." if alias else ""
    if not owner_sub:
        return "", []
    return f" AND ({prefix}owner_sub = ? OR {prefix}visibility = 'org')", [owner_sub]


# ---------------------------------------------------------------- 타깃 문맥
def _target_context(store, target_key: str) -> dict:
    """브리프 조립에 필요한 타깃·스냅샷·diff 행을 한 번에 읽는다."""
    target = store.query_one(
        "SELECT target_key, owner_sub, kind, ref_id, project_id, base_project_id, ir_hash, "
        "external_sync_json, level FROM rr_targets WHERE target_key = ?",
        (target_key,),
    )
    if target is None:
        raise AppError("E404", f"타깃이 없습니다: {target_key}", http_status=404)
    ctx: dict[str, Any] = {"target": target, "kind": target["kind"], "diff": None,
                           "snapshot_id": None, "base_snapshot_id": None}
    if target["kind"] == "diff":
        diff = store.query_one(
            "SELECT id, base_snapshot_id, target_snapshot_id, base_project_id, target_project_id, "
            "pair_kind, diff_json, summary_text, summary_status, comparability_json, gates_json "
            "FROM rr_diffs WHERE id = ?",
            (target["ref_id"],),
        )
        ctx["diff"] = diff
        if diff is not None:
            ctx["snapshot_id"] = diff["target_snapshot_id"]
            ctx["base_snapshot_id"] = diff["base_snapshot_id"]
    else:
        ctx["snapshot_id"] = target["ref_id"]
    ctx["snapshot"] = _snapshot_row(store, ctx["snapshot_id"])
    ctx["state"] = _state_row(store, ctx["snapshot_id"])
    return ctx


def _snapshot_row(store, snapshot_id: str | None):
    if not snapshot_id:
        return None
    return store.query_one(
        "SELECT id, project_id, ir_version, ir_hash, ir_json, source_ids_json, kinds_json, "
        "node_count, edge_count, missing_json, warnings_n, degraded, adapter_versions_json "
        "FROM rr_snapshots WHERE id = ?",
        (snapshot_id,),
    )


def _state_row(store, snapshot_id: str | None):
    if not snapshot_id:
        return None
    return store.query_one(
        "SELECT snapshot_id, gates_json, rule_hits_json, character_seed_json, feature_json, "
        "summary_text, summary_status, state_json FROM rr_states WHERE snapshot_id = ?",
        (snapshot_id,),
    )


def _project_code(store, project_id: str | None) -> str:
    if not project_id:
        return "-"
    row = store.query_one("SELECT code FROM rr_projects WHERE id = ?", (project_id,))
    return _s(row["code"], project_id) if row is not None else _s(project_id)


# ---------------------------------------------------------------- E0 스코프
def _gates_lines(gates: Any) -> str:
    """게이트 G1~G7 을 `G1 pass · G2 fail` 로 적는다(판단어 린터 예외 표기, plan §3.4.3 L16 allow)."""
    parts = []
    if isinstance(gates, dict):
        source = gates.get("gates") if isinstance(gates.get("gates"), dict) else gates
        for n in range(1, 8):
            key = f"G{n}"
            if key not in source:
                continue
            value = source[key]
            ok = value.get("pass") if isinstance(value, dict) else value
            if ok is None:
                # 입력이 없어 검문하지 못했다 — pass 로도 fail 로도 세지 않는다(plan §2.12).
                reason = value.get("reason") if isinstance(value, dict) else None
                parts.append(f"{key} n/a({reason or 'unknown'})")
            else:
                parts.append(f"{key} {'pass' if ok else 'fail'}")
    return " · ".join(parts) if parts else "게이트 기록 없음"


def _source_apps(snapshot) -> str:
    """E0 의 소스 앱 id 줄 — `stepforge project_id=… · dynaforge session_id=… · ecad absent`."""
    if snapshot is None:
        return "소스 기록 없음"
    items = _j(snapshot["source_ids_json"], [])
    parts = []
    kinds = set()
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = _s(item.get("kind"), "?")
            kinds.add(kind)
            ref = item.get("ref")
            if isinstance(ref, dict):
                detail = " ".join(f"{k}={_q(v)}" for k, v in sorted(ref.items()) if v is not None)
            else:
                detail = _q(ref)
            parts.append(f"{kind} {_q(item.get('app_key'))} {detail}".strip())
    if "ecad" not in kinds:
        parts.append("ecad absent")
    return " · ".join(parts) if parts else "소스 기록 없음"


def _tol_params(snapshot) -> str:
    if snapshot is None:
        return "tol_params 없음"
    items = _j(snapshot["source_ids_json"], [])
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("tol_params"):
                return f"tol_params={json.dumps(item['tol_params'], ensure_ascii=False, sort_keys=True)}"
    return "tol_params 없음"


def _panel_model(store, target_key: str, panel_id: str | None) -> str:
    """이 브리프가 실릴 패널의 모델명(D6). 없으면 'unknown'(plan §4.5 — E0 첫 줄 헤더 `model=<name>`)."""
    if panel_id:
        row = store.query_one("SELECT model_json FROM rr_panels WHERE id = ?", (panel_id,))
    else:
        row = store.query_one(
            "SELECT model_json FROM rr_panels WHERE target_key = ? ORDER BY panel_no DESC LIMIT 1",
            (target_key,),
        )
    if row is None:
        return "unknown"
    model = _j(row["model_json"], {})
    name = model.get("model") if isinstance(model, dict) else None
    return _s(name) or "unknown"


def _item_e0(store, ctx, external_ok: bool, model: str = "unknown") -> dict:
    target = ctx["target"]
    snapshot = ctx["snapshot"]
    diff = ctx["diff"]
    gates = _j(diff["gates_json"], {}) if diff is not None else (
        _j(ctx["state"]["gates_json"], {}) if ctx["state"] is not None else {})
    missing = _j(snapshot["missing_json"], []) if snapshot is not None else []
    adapters = _j(snapshot["adapter_versions_json"], {}) if snapshot is not None else {}
    base_code = _project_code(store, target["base_project_id"]) if target["base_project_id"] else "-"
    lines = [
        f"kind={target['kind']} target_key={target['target_key']} level={_s(target['level'], 'C0')} "
        f"model={model}",
        f"과제 base={base_code} target={_project_code(store, target['project_id'])}",
        f"snapshot_id={_s(ctx['snapshot_id'], '-')} ir_hash={_s(target['ir_hash'])}",
        f"게이트 {_gates_lines(gates)}",
        f"missing={json.dumps(missing, ensure_ascii=False, sort_keys=True) if missing else '[]'}",
        f"소스 {_source_apps(snapshot)}",
        f"{_tol_params(snapshot)} adapter_version={json.dumps(adapters, ensure_ascii=False, sort_keys=True)}",
        f"외부 검색 가용={'true' if external_ok else 'false'}",
    ]
    return {"key": "E0", "args": target["target_key"], "result": _body("rr_scope", lines)}


# ---------------------------------------------------------------- E0c 좌석 계약
def _item_e0c(seats: Sequence[Mapping[str, Any]]) -> dict:
    contract = taxonomy.load_json("seat-contract").get("contract") or {}
    domains: list[str] = []
    for seat in seats:
        domain = _s(seat.get("domain"))
        if domain and domain not in domains:
            domains.append(domain)
    lines = [_cut(contract.get("_common"), 200)] if contract.get("_common") else []
    for domain in domains:
        row = contract.get(domain)
        lines.append(_cut(row, 200) if row else f"[{domain}] 계약 행 없음")
    return {"key": "E0c", "args": ",".join(domains), "result": _body("seat_contract", lines)}


# ---------------------------------------------------------------- E1 요약
def _item_e1(ctx) -> dict:
    if ctx["kind"] == "diff":
        diff = ctx["diff"]
        args = f"diff:{_s(ctx['target']['ref_id'])}"
        if diff is None:
            return {"key": "E1", "args": args, "result": _body("rr_diff", ["[diff 행 없음]"])}
        if diff["summary_status"] == "lint_failed" or not diff["summary_text"]:
            return {"key": "E1", "args": args,
                    "result": _body("rr_diff", ["[summary_text 없음 — summary_status=lint_failed]"])}
        return {"key": "E1", "args": args, "result": _body("rr_diff", [diff["summary_text"]])}
    state = ctx["state"]
    args = f"snap:{_s(ctx['snapshot_id'])}"
    # snap 타깃의 원천은 rr_state 다(§5.6.1 표 E1 행의 `rr_diff`/`rr_state`).
    snap = {"key": "E1", "args": args, "source": "rr_state", "tool": "rr_states"}
    if state is None or state["summary_status"] == "lint_failed" or not state["summary_text"]:
        return {**snap, "result": _body("rr_state", ["[summary_text 없음 — summary_status=lint_failed]"])}
    return {**snap, "result": _body("rr_state", [state["summary_text"]])}


# ---------------------------------------------------------------- E2 이벤트 표
_LAYER_ORDER = {"semantic": 0, "structural": 1, "parametric": 2}


def _item_e2(store, ctx) -> dict:
    source, tool = _SOURCES["E2"]
    if ctx["kind"] != "diff" or ctx["diff"] is None:
        return {"key": "E2", "args": _s(ctx["target"]["target_key"]),
                "result": _body(source, ["[pair 전용 — 해당 없음]"])}
    diff_id = ctx["diff"]["id"]
    rows = store.query(
        "SELECT cid, layer, code, change_kind, subject_key, magnitude, unit, rel, confidence, "
        "unconfirmed, excluded_reason, text FROM rr_diff_events "
        "WHERE diff_id = ? AND layer IN ('semantic','structural')",
        (diff_id,),
    )
    ordered = sorted(
        rows,
        key=lambda r: (_LAYER_ORDER.get(_s(r["layer"]), 9),
                       -(r["magnitude"] if isinstance(r["magnitude"], (int, float)) else 0.0),
                       _s(r["cid"])),
    )
    lines = []
    for row in ordered:
        tail = ""
        if row["unconfirmed"]:
            tail = " unconfirmed"
        elif row["excluded_reason"]:
            tail = f" excluded_reason={row['excluded_reason']}"
        # 이벤트 정규 표기는 소스 앱 부품명을 그대로 담는다(render.fmt_label 은 감싸지 않는다) — 여기서 «…» 로 넣는다.
        text = _q(_s(row["text"]) or f"{_s(row['subject_key'])} {_s(row['change_kind'])}", "note")
        # §3.3.2 의 cid 는 'c:' 접두를 포함한 값이고 §5.6.1 의 표기는 `[c:<cid>]` 다 — 접두를 두 번 붙이지 않는다.
        cid = _s(row["cid"])
        ref = cid if cid.startswith("c:") else f"c:{cid}"
        lines.append(f"[{ref}] {_s(row['code'])} {text} conf={_s(row['confidence'], '-')}{tail}")
    if not lines:
        lines = ["[의미·구조 이벤트 0건]"]
    return {"key": "E2", "args": f"diff:{diff_id}", "result": _body(source, lines)}


# ---------------------------------------------------------------- E3 명명 치수
def _item_e3(ctx) -> dict:
    source = _SOURCES["E3"][0]
    lines: list[str] = []
    if ctx["kind"] == "diff" and ctx["diff"] is not None:
        args = f"diff:{ctx['diff']['id']}"
        for item in _j(ctx["diff"]["diff_json"], {}).get("dims_delta") or []:
            if not isinstance(item, dict):
                continue
            rel = item.get("rel")
            rel_text = f" ({rel}%)" if rel is not None else ""
            lines.append(
                f"[d:{_ref_name(item.get('name'))}] {_s(item.get('base'), '미측정')}"
                f"→{_s(item.get('target'), '미측정')} "
                f"{_q(item.get('unit'))}{rel_text} method={_q(item.get('method') or '-')}"
            )
    else:
        args = f"snap:{_s(ctx['snapshot_id'])}"
        ir = _j(ctx["snapshot"]["ir_json"], {}) if ctx["snapshot"] is not None else {}
        named = ir.get("dims_named") or {}
        entries = named.items() if isinstance(named, dict) else [
            (i.get("name"), i) for i in named if isinstance(i, dict)]
        for name, item in sorted(entries, key=lambda kv: _s(kv[0])):
            value = item.get("value") if isinstance(item, dict) else item
            unit = item.get("unit") if isinstance(item, dict) else ""
            method = item.get("method") if isinstance(item, dict) else None
            lines.append(f"[d:{_ref_name(name)}] {_s(value, '미측정')} {_q(unit)} "
                         f"method={_q(method or '-')}")
    if not lines:
        lines = ["[명명 치수 없음 — rr_dim_defs 0건]"]
    return {"key": "E3", "args": args, "result": _body(source, lines)}


# ---------------------------------------------------------------- E4 결과 delta
def _item_e4(ctx) -> dict:
    source = _SOURCES["E4"][0]
    lines: list[str] = []
    if ctx["kind"] == "diff" and ctx["diff"] is not None:
        args = f"diff:{ctx['diff']['id']}"
        comparability = _j(ctx["diff"]["comparability_json"], {})
        if comparability.get("result_parity") is False:
            lines = ["[result_parity=false — 정성만]"]
        else:
            for item in _j(ctx["diff"]["diff_json"], {}).get("result_delta") or []:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"{_q(item.get('name'))} {_s(item.get('base'), '미측정')}"
                    f"→{_s(item.get('target'), '미측정')} "
                    f"{_q(item.get('unit'))} rel={_s(item.get('rel'), '-')}"
                )
    else:
        args = f"snap:{_s(ctx['snapshot_id'])}"
        ir = _j(ctx["snapshot"]["ir_json"], {}) if ctx["snapshot"] is not None else {}
        rows = (ir.get("results") or {}).get("part_risk") if isinstance(ir.get("results"), dict) else None
        for item in (rows or [])[:5]:
            if isinstance(item, dict):
                # part_risk 행의 값에는 dyna 소스가 쓴 파트명·이벤트 문자열이 섞인다 — 전부 «…» 안에 넣는다.
                fields = " ".join(f"{k}={_q(item[k])}" for k in sorted(item)
                                  if not isinstance(item[k], (dict, list)))
                lines.append(fields)
    if not lines:
        lines = ["[dyna_result 부재]"]
    return {"key": "E4", "args": args, "result": _body(source, lines)}


# ---------------------------------------------------------------- E5 선행 등록부
def _registry_line(row, path: str) -> str:
    merged = _j(row["merged_json"], {})
    subject_names = merged.get("subject_names") or merged.get("subject_name") or row["subject_key"]
    if isinstance(subject_names, list):
        subject_names = "↔".join(str(x) for x in subject_names)
    claim = merged.get("claim")
    if not claim and isinstance(merged.get("representative"), dict):
        claim = merged["representative"].get("claim")
    return (
        f"reg:{row['target_key']}#{row['cluster_key']} | "
        f"{_s(row['mechanism'], '-')}.{_s(row['mechanism_detail'], '-')} | {_q(subject_names)} | "
        f"{_s(row['severity'], '-')}/{_s(row['judgement'], '-')} | status {_s(row['status'], '-')} | "
        f"support {row['support'] or 0} · contested {row['contested'] or 0} | {_q(claim, 'claim')} | "
        f"[경로: {path}]"
    )


def _negative_line(row) -> str:
    """E5− 한 줄 — 기각·반증 선례. 살아 있는 선례와 형식을 달리해 섞이지 않게 한다(plan §5.6.1)."""
    merged = _j(row["merged_json"], {})
    subject_names = merged.get("subject_names") or merged.get("subject_name") or row["subject_key"]
    if isinstance(subject_names, list):
        subject_names = "↔".join(str(x) for x in subject_names)
    notes = merged.get("contest_notes") or []
    excerpt = ""
    if isinstance(notes, list) and notes:
        excerpt = _s((notes[0] or {}).get("note") if isinstance(notes[0], dict) else notes[0])
    source = _s(row["status_source"], "code") if "status_source" in row.keys() else "code"
    return (
        f"reg:{row['target_key']}#{row['cluster_key']} | "
        f"{_s(row['mechanism'], '-')}.{_s(row['mechanism_detail'], '-')} | {_q(subject_names)} | "
        f"status {_s(row['status'], '-')}({source}) | rejected {row['rejected'] or 0} · "
        f"support {row['support'] or 0} | {_q(excerpt or '-', 'claim')}"
    )


_REGISTRY_COLS = (
    "target_key, cluster_key, merged_json, support, contested, rejected, human_n, direction, mechanism, "
    "mechanism_detail, change_kind, subject_key, severity, sev3, judgement, status, status_source, "
    "needs_review_json, stale_json, updated_at"
)
# E5+ 는 살아 있는 선례, E5− 는 기각·반증 선례다. 한 줄도 두 블록에 겹쳐 실리지 않는다(plan §5.6.1).
E5_POSITIVE_STATUSES = ("open", "verified")
# 회수 검색에서 항상 빼는 상태 태그 3종(plan §5.6.3 '상태 필터') — 기각·철회·대체된 발언은 돌아오지 않는다.
RECALL_EXCLUDE_TAGS: tuple[str, ...] = ("status:dismissed", "status:rejected_in_panel", "status:superseded")
E5_NEGATIVE_STATUSES = ("rejected_in_panel", "dismissed")


def _corpus_ids(store) -> set[str]:
    """회수가 보는 과제 집합 — §0.6 코퍼스 필터(registry.corpus_projects) 하나만 본다(plan §0.9 P5-11)."""
    from app import registry  # noqa: PLC0415 — registry 는 brief 를 import 하지 않는다.

    return registry.corpus_projects(store)


def _e5_candidates(store, ctx, similar: Mapping[str, Any], owner_sub: str | None,
                   statuses: Sequence[str]) -> list[tuple[str, Any]]:
    """E5 후보 행 — 계보·유사 과제(경로 태그 포함)와 subject 정확 매치. 코퍼스 필터를 통과한 과제만 본다."""
    project_paths: dict[str, str] = {}
    for entry in similar.get("merged") or []:
        paths = entry.get("paths") or []
        project_paths[str(entry.get("project_id"))] = "|".join(str(p) for p in paths) or "벡터"
    corpus = _corpus_ids(store)
    project_paths = {pid: path for pid, path in project_paths.items() if pid in corpus}
    marks_status = ",".join("?" for _ in statuses)
    rows: list[tuple[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    if project_paths:
        marks = ",".join("?" for _ in project_paths)
        vis, vis_params = _visibility_clause(owner_sub, "r")
        found = store.query(
            f"SELECT {_REGISTRY_COLS} FROM rr_registry AS r "
            f"WHERE r.status IN ({marks_status}) AND r.target_key IN "
            f"(SELECT target_key FROM rr_targets WHERE project_id IN ({marks})){vis}",
            [*statuses, *project_paths.keys(), *vis_params],
        )
        for row in found:
            key = (row["target_key"], row["cluster_key"])
            seen.add(key)
            owner_project = store.query_one(
                "SELECT project_id FROM rr_targets WHERE target_key = ?", (row["target_key"],))
            path = project_paths.get(_s(owner_project["project_id"]) if owner_project else "", "계보")
            rows.append((path, row))
    for hit in similar.get("subject") or []:
        vis, vis_params = _visibility_clause(owner_sub, "r")
        found = store.query(
            f"SELECT {_REGISTRY_COLS} FROM rr_registry AS r "
            f"WHERE r.subject_key = ? AND r.status IN ({marks_status})"
            f" AND r.target_key IN (SELECT target_key FROM rr_targets WHERE project_id IN"
            f" (SELECT id FROM rr_projects WHERE status = 'active' AND corpus_excluded = 0)){vis}",
            [hit["subject_key"], *statuses, *vis_params],
        )
        for row in found:
            key = (row["target_key"], row["cluster_key"])
            if key in seen or row["target_key"] == ctx["target"]["target_key"]:
                continue
            seen.add(key)
            rows.append((_s(hit.get("path"), "subject"), row))
    if not getattr(config.settings, "risk_prior_include_human", True):
        # 사람 제기 선례를 회수에서 뺀다(Settings risk_prior_include_human=false, plan §5.6.1).
        rows = [(path, row) for path, row in rows if not _is_human_row(row)]
    rows.sort(key=lambda pr: (-(pr[1]["sev3"] or 0), -(pr[1]["support"] or 0),
                              -(pr[1]["updated_at"] or 0), _s(pr[1]["cluster_key"])))
    return rows


def _is_human_row(row) -> bool:
    """전문가 지지 없이 사람만 제기한 등록부 행(support=0·human_n≥1)."""
    return int(row["human_n"] or 0) >= 1 and int(row["support"] or 0) == 0


def _stale_prefix(row, target_key: str) -> str:
    """§4.8 3 접두 — 이 타깃 기준으로 그 선례의 주체가 바뀌었는지.

    §4.8 은 "E5 는 stale 클러스터를 `[변경 주체 — 재검증 대상]` 접두로, 나머지를 `[미변경 주체]` 로
    싣는다" 고 적는다. 그 '나머지' 는 **§4.8 이 실제로 판정한 클러스터** 로 읽는다 — stale 표기는
    `stale_json[T′]` 이고 그 판정은 같은 과제의 직전 타깃에만 일어난다. 다른 과제의 선례에는 항목이
    아예 없는데 그것을 `[미변경 주체]` 로 적으면 **확인하지 않은 것을 확인했다고 적는 것**이다.
    그래서 항목이 없으면 접두를 붙이지 않는다(모름과 '안 바뀜' 을 같은 글자로 쓰지 않는다).
    """
    entry = (_j(row["stale_json"], {}) or {}).get(target_key) if "stale_json" in row.keys() else None
    if not isinstance(entry, Mapping):
        return ""
    return "[변경 주체 — 재검증 대상] " if entry.get("stale") else "[미변경 주체] "


def _e5_prefix(row, target_key: str = "") -> str:
    """E5+ 줄 접두 — 재검토(escalated)·사람 제기(origin='human')와 §4.8 변경 주체를 드러낸다.

    §5.6.1 의 2종과 §4.8 의 2종은 서로를 참조하지 않는다 — 다른 사실이라 **겹쳐 붙인다**.
    변경 주체가 먼저다(재검증이 필요한지가 좌석이 먼저 알아야 할 사실이다).
    """
    escalated = bool((_j(row["needs_review_json"], {}) or {}).get("escalated"))
    human = _is_human_row(row)
    head = _stale_prefix(row, target_key) if target_key else ""
    if escalated and human:
        return head + "[재검토·사람 제기] "
    if escalated:
        return head + "[재검토] "
    if human:
        return head + "[사람 제기·검증 대상] "
    return head


def _item_e5(store, ctx, similar: Mapping[str, Any], owner_sub: str | None, field=None) -> dict:
    """E5 세 블록 — E5+(살아 있는 선례) · E5−(기각·반증 선례) · E10(필드·문헌 근거)(plan §5.6.1).

    기각 선례는 두 번째 블록에만 실린다 — 살아 있는 선례로 되돌아오지 않게 하고, 동시에 '과거에
    기각됐다' 는 사실이 발화될 자리를 만든다.
    """
    source = _SOURCES["E5"][0]
    target_key = _s(ctx["target"]["target_key"])
    positive = [_e5_prefix(row, target_key) + _registry_line(row, path)
                for path, row in _e5_candidates(store, ctx, similar, owner_sub, E5_POSITIVE_STATUSES)]
    negative = [_negative_line(row)
                for _path, row in _e5_candidates(store, ctx, similar, owner_sub, E5_NEGATIVE_STATUSES)]
    neg_max = int(getattr(config.settings, "risk_neg_precedent_lines", 6) or 6)

    lines = ["[E5+ 살아 있는 선례]"]
    lines += (clip_lines("\n".join(positive), E5_POSITIVE_CAP).split("\n") if positive
              else ["[선행 등록부 없음 — 이 과제 계보·유사 과제 0건]"])
    lines.append("[E5− 기각·반증 선례]")
    lines += (clip_lines("\n".join(negative[:neg_max]), E5_NEGATIVE_CAP).split("\n") if negative
              else ["[기각된 선례 없음 — 이 조합에서 기각 0건]"])
    lines.append("[E10 필드·VOC·문헌 근거]")
    lines += _field_evidence_lines(store, ctx, field)
    return {"key": "E5", "args": _s(ctx["target"]["target_key"]), "result": _body(source, lines)}


# E10 실호출 데드라인(plan §5.6.2 — 호출마다 개별, 초과·오류는 그 줄만 빠진다).
FIELD_CALL_TIMEOUT_S = 5.0
# 저장 원문 재사용 창(§5.6.2 — VOC 는 하루 단위로 바뀐다).
FIELD_REUSE_S = 24 * 3600
FIELD_TOOLS: tuple[str, ...] = ("get_top_issues", "search_scholar")
_VOC_CATEGORY, _VOC_EXCERPT, _PAPER_TITLE, _PAPER_EXCERPT = 40, 80, 60, 80
# get_top_issues 조회 창(plan §5.6.2 — 90d)과 카테고리 수(§5.6.2 "상위 카테고리 3")·문헌 수(상위 2).
VOC_WINDOW_DAYS = 90
VOC_CATEGORIES, PAPER_TOP = 3, 2


def product_keys(store, project_id: str) -> tuple[list[str], bool]:
    """§5.6.2 제품 해석 — `product_refs_json` → `product_code` → `predecessor_product_code` 순.

    돌려주는 두 번째 값은 '전작인가' 다(전작이면 줄 앞에 `[전작]` 을 붙인다).
    """
    row = store.query_one(
        "SELECT product_code, product_refs_json, predecessor_product_code FROM rr_projects WHERE id = ?",
        (project_id,)) if project_id else None
    return product_keys_of(row) if row is not None else ([], False)


def product_keys_of(row: Mapping[str, Any]) -> tuple[list[str], bool]:
    """제품 3열 → 조회 키. 행을 이미 손에 든 호출자(지표)가 같은 규칙을 쓰도록 따로 둔다.

    지표 `field_evidence_rate` 의 분모('제품 연결이 있는 과제')가 이 판정과 갈리면 양방향으로 틀린다 —
    `ra_model` 만 든 과제를 분모에 넣으면 E10 이 구조적으로 불가능한데 지표가 낮게 나오고,
    전작 코드만 있는 과제를 빼면 E10 이 도는데 분모에서 사라진다.
    """
    # 정본 §5.6.2 는 "`product_refs_json` 의 **`product_code` 값들**" 이라고 적는다 — 항목 모양은
    # `[{kind: 'ra_model'|'product_code', value, ra_entity_id}]`(§5.2.2 DDL 주석)이므로 kind 를 가려야 한다.
    # 안 가리면 `ra_model` 의 값이 제품코드로 쓰여 VOC 를 엉뚱한 키로 조회한다.
    refs = [_s(r.get("value")) for r in (_j(row["product_refs_json"], []) or [])
            if isinstance(r, Mapping) and _s(r.get("kind")) == "product_code" and _s(r.get("value"))]
    if refs:
        return refs, False
    if _s(row["product_code"]):
        return [_s(row["product_code"])], False
    if _s(row["predecessor_product_code"]):
        return [_s(row["predecessor_product_code"])], True
    return [], False


def scholar_query(store, ctx) -> str:
    """§5.6.2 — 성격 태그 상위 2 + mechanism 상위 1. 결정론이어야 24 h 캐시 키가 선다."""
    project_id = _s(ctx["target"]["project_id"])
    tags = [_s(r["tag"]) for r in store.query(
        "SELECT tag FROM rr_character WHERE project_id = ? AND tag IS NOT NULL AND status != 'superseded'"
        " ORDER BY support_panels DESC, id LIMIT 2", (project_id,))] if project_id else []
    mechs = [_s(r["mechanism"]) for r in store.query(
        "SELECT mechanism, COUNT(*) AS n FROM rr_findings WHERE target_key = ? AND mechanism IS NOT NULL"
        " GROUP BY mechanism ORDER BY n DESC, mechanism LIMIT 1", (_s(ctx["target"]["target_key"]),))]
    parts = [t.split(":")[-1] for t in tags if t] + [m for m in mechs if m]
    return " ".join(parts)


def rendered_field_items(payload: Any, kind: str) -> list[Mapping[str, Any]]:
    """E10 이 **실제로 줄로 만든** 항목들. 조립과 `voc:`·`paper:` 존재 검증이 같은 규칙을 봐야 한다.

    정본 §0.2.1 은 `voc:` 를 "브리프 E10 블록에 실린 것만" 이라 적는다. 응답 원문 전체를 근거로 삼으면
    블록에 안 실린 4번째 이슈를 인용해도 측정 등급을 받는다 — 이슈 키는 연번이라 추측이 쉽다.
    `voc` 는 정본 "상위 카테고리 3" 이라 카테고리로 중복을 걷고(먼저 나온 이슈가 그 카테고리 대표),
    `paper` 는 상위 2 다. 줄 수·문자 상한은 여기서 재현하지 않으므로 이 목록은 **상한**이다.
    """
    rows = _rows_of(payload, "issues" if kind == "voc" else "papers") or []
    out: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        if kind == "voc":
            if not _s(item.get("issue_key")):
                continue
            cat = _s(item.get("category"))
            if cat in seen:
                continue
            seen.add(cat)
        elif not (_s(item.get("record_id")) or _s(item.get("doi"))):
            continue
        out.append(item)
        if len(out) >= (VOC_CATEGORIES if kind == "voc" else PAPER_TOP):
            break
    return out


def field_evidence_line(item: Mapping[str, Any], kind: str, *, product_code: str = "") -> str:
    """E10 한 줄의 정규 표기(§5.6.1 줄 형식). `[전작]` 접두는 코드 라벨이라 여기 넣지 않는다.

    조립과 **quote 대조**(§4.4.2)가 같은 문자열을 봐야 한다 — 좌석은 이 줄을 읽고 인용하므로,
    대조 기준이 이 줄이 아니면 지어낸 인용문이 그대로 통과한다. 그래서 줄을 만드는 곳을 한 곳에 둔다.

    응답의 자유 문자열은 전부 위생을 거쳐 «…» 안에 둔다 — 밖에 두면 판단어 린터에 그대로 노출돼 남의
    VOC 문구 하나가 브리프 조립을 통째로 죽인다(§3.4.1). `render.sanitize_source_text` 를 직접 부르지
    않고 `_q` 를 쓴다 — 직접 부르면 `on_suspect` 가 빠져 인젝션 적중이 자리표시자로만 가려지고
    `rr_curation_queue` 에 안 올라간다(사람이 주입 시도를 영영 모른다). `_cut` 은 줄바꿈을 접는다 —
    접지 않으면 남의 VOC 한 줄이 두 줄이 되어 줄 수 상한을 우회한다.
    기간은 응답이 아니라 내가 보낸 인자로 적는다(외부 문자열을 하나 줄인다).
    """
    if kind == "voc":
        cat = _q(_cut(item.get("category"), _VOC_CATEGORY), "voc")
        excerpt = _q(_cut(item.get("text"), _VOC_EXCERPT), "voc")
        return (f"voc:{product_code}#{_s(item.get('issue_key'))} | {cat} | n={_int(item.get('n'))} |"
                f" {VOC_WINDOW_DAYS}d | {excerpt}")
    pid = _s(item.get("record_id")) or _s(item.get("doi"))
    title = _q(_cut(item.get("title"), _PAPER_TITLE), "paper")
    excerpt = _q(_cut(item.get("abstract"), _PAPER_EXCERPT), "paper")
    return f"paper:{pid} | {title} | {excerpt}"


def _field_evidence_lines(store, ctx, field=None) -> list[str]:
    """E10 블록(plan §5.6.1·§5.6.2).

    `field` 는 게이트웨이 MCP 채널이다(없으면 조회 없이 결측 문구 한 줄). 호출 원문은 `rr_brief_calls` 에
    남아 `voc:`·`paper:` 참조의 해석 원장이 되고 같은 타깃은 24 h 안이면 그 원문을 재사용한다.
    실패한 호출은 그 줄만 빠지고 블록 끝에 `[조회 불가: <tool>]` 한 줄이 남는다 — '실패' 는 판단어
    린터(L14)에 걸려 브리프 조립이 통째로 죽으므로 상태 서술로 적는다(context-notes D18).
    """
    project_id = _s(ctx["target"]["project_id"])
    codes, inherited = product_keys(store, project_id)
    if not codes:
        return ["[필드·문헌 근거 없음 — 제품 연결 미등록]"]
    if field is None:
        return ["[필드·문헌 근거 없음 — 조회 채널 없음]"]

    target_key = _s(ctx["target"]["target_key"])
    owner_sub = _s(ctx["target"]["owner_sub"])
    prefix = "[전작] " if inherited else ""
    lines: list[str] = []
    unreachable: list[str] = []

    issues = field.fetch(store, target_key, owner_sub, "get_top_issues",
                         {"product_code": codes[0], "window_days": VOC_WINDOW_DAYS})
    if issues is None:
        unreachable.append("get_top_issues")
    else:
        for item in rendered_field_items(issues, "voc"):
            lines.append(prefix + field_evidence_line(item, "voc", product_code=codes[0]))

    query = scholar_query(store, ctx)
    papers = field.fetch(store, target_key, owner_sub, "search_scholar", {"q": query}) if query else None
    if query and papers is None:
        unreachable.append("search_scholar")
    else:
        for item in rendered_field_items(papers, "paper"):
            lines.append(field_evidence_line(item, "paper"))

    lines = lines[: max(1, int(getattr(config.settings, "risk_field_evidence_lines", 5)))]
    # 줄 수 상한(정본 "합쳐 최대 5줄")은 근거 줄에만 걸고 `[조회 불가]` 는 그 밖이다(정본은 그 줄을 따로 적는다).
    tail = [f"[조회 불가: {tool}]" for tool in unreachable]
    # 문자 상한(E5_FIELD_CAP)은 여기서 걸어야 한다 — 걸지 않으면 E5 항목 전체가 실효 한도를 넘고
    # clip_lines 가 **뒤에서부터** 버려 E10 이 통째로 사라진다(D18 이 340 을 계산한 이유이자, 그 값을
    # 적용하지 않아 D18 이 막으려던 실패가 그대로 살아 있던 자리다). 꼬리 길이를 먼저 떼어 두어
    # 조회 불가 사실이 예산 때문에 지워지지 않게 한다 — 그게 지워지면 '조회했는데 0건' 과 구별되지 않는다.
    tail_len = sum(len(t) + 1 for t in tail)
    if lines:
        clipped = clip_lines("\n".join(lines), max(0, E5_FIELD_CAP - tail_len))
        lines = clipped.split("\n") if clipped else []
    return (lines + tail) or ["[필드·문헌 근거 없음 — VOC 0건]"]


def _int(value: Any) -> int | str:
    """건수는 정수로만 싣는다 — 소스가 문자열을 주면 그 값이 린터 앞에 그대로 서지 않게 한다."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return "?"


def _rows_of(payload, key: str) -> list:
    """`{key: [...]}` 도 `[...]` 도 받는다(소스 응답 봉투가 갈린다)."""
    if isinstance(payload, Mapping):
        rows = payload.get(key)
        return [r for r in rows if isinstance(r, Mapping)] if isinstance(rows, list) else []
    return [r for r in payload if isinstance(r, Mapping)] if isinstance(payload, list) else []


# ---------------------------------------------------------------- E6 유사 과제 성격
def _item_e6(store, similar: Mapping[str, Any], ctx) -> dict:
    source = _SOURCES["E6"][0]
    corpus = _corpus_ids(store)
    project_ids = [str(e.get("project_id")) for e in (similar.get("merged") or [])
                   if str(e.get("project_id")) in corpus]
    lines: list[str] = []
    if project_ids:
        marks = ",".join("?" for _ in project_ids)
        rows = store.query(
            "SELECT id, project_id, facet, tag, statement, by_json, support_panels, status "
            f"FROM rr_character WHERE project_id IN ({marks}) AND recall_eligible = 1 "
            "AND (status = 'confirmed' OR (status = 'panel' AND support_panels >= 2))",
            project_ids,
        )
        ordered = sorted(
            rows,
            key=lambda r: (0 if r["status"] == "confirmed" else 1,
                           -(r["support_panels"] or 0), _s(r["id"])),
        )[:3]
        for row in ordered:
            by = _j(row["by_json"], [])
            by_text = ",".join(str(x) for x in by) if isinstance(by, list) else _s(by)
            status = "confirmed" if row["status"] == "confirmed" else f"panel:{row['support_panels'] or 0}"
            paths = len([e for e in (similar.get("merged") or [])
                         if str(e.get("project_id")) == row["project_id"]] or [])
            lines.append(
                f"narr:{row['id']} | {_project_code(store, row['project_id'])} | {_s(row['facet'])} | "
                f"{_s(row['tag'], '-')} | {_q(row['statement'], 'statement')} | by {_cut(by_text, 40)} | "
                f"[{status}·경로 {paths}]"
            )
    if not lines:
        lines = [f"[유사 과제 성격 진술 없음 — 코퍼스 n_projects={len(corpus)}]"]
    return {"key": "E6", "args": _s(ctx["target"]["target_key"]), "result": _body(source, lines)}


# ---------------------------------------------------------------- E7 좌석 개인 기억(고정 슬롯)
def _lineage_project_ids(store, project_id: str | None, hops: int = 3) -> list[str]:
    """rr_projects.predecessor_project_id 를 앞뒤로 hops 만큼 따라간 과제 id 목록(자기 자신 제외)."""
    out: list[str] = []
    seen = {project_id}
    current = project_id
    for _ in range(hops):
        if not current:
            break
        row = store.query_one("SELECT predecessor_project_id FROM rr_projects WHERE id = ?", (current,))
        current = row["predecessor_project_id"] if row is not None else None
        if current and current not in seen:
            seen.add(current)
            out.append(current)
    frontier = [project_id]
    for _ in range(hops):
        if not frontier:
            break
        marks = ",".join("?" for _ in frontier)
        rows = store.query(
            f"SELECT id FROM rr_projects WHERE predecessor_project_id IN ({marks})", frontier)
        frontier = []
        for row in rows:
            if row["id"] not in seen:
                seen.add(row["id"])
                out.append(row["id"])
                frontier.append(row["id"])
    return out


def _subject_keys(store, snapshot_id: str | None) -> set[str]:
    """이번 타깃 IR 의 subject_key 집합(계면 subject + 파트 ckey + dim: + asm:)."""
    if not snapshot_id:
        return set()
    out: set[str] = set()
    for row in store.query(
            "SELECT DISTINCT subject_key FROM rr_ir_edges WHERE snapshot_id = ? AND subject_key IS NOT NULL",
            (snapshot_id,)):
        out.add(_s(row["subject_key"]))
    for row in store.query(
            "SELECT DISTINCT ckey FROM rr_ir_nodes WHERE snapshot_id = ? AND ckey IS NOT NULL",
            (snapshot_id,)):
        out.add(_resolve_ckey(store, _s(row["ckey"])))
    return {k for k in out if k}


def _seat_line(store, row, excerpt: str) -> str:
    """좌석 줄 — `narr:<opinion_id>#<finding_id> | <agent_key> | <과제코드>/<target 앞12> | <발췌>` ≤220자."""
    findings = _j(row["raised_finding_ids_json"], [])
    finding_id = str(findings[0]) if isinstance(findings, list) and findings else ""
    project_code = _project_code(store, row["project_id"] if "project_id" in row.keys() else None)
    prefix = (f"narr:{row['opinion_id']}#{finding_id} | {row['agent_key']} | "
              f"{project_code}/{_s(row['target_key'])[:12]} | ")
    return prefix + _cut(excerpt, max(0, E7_SEAT_LINE - len(prefix)))


def _item_e7(store, ctx, seats: Sequence[Mapping[str, Any]], adh) -> dict:
    source = _SOURCES["E7"][0]
    target_key = _s(ctx["target"]["target_key"])
    lineage = set(_lineage_project_ids(store, ctx["target"]["project_id"]))
    subjects = _subject_keys(store, ctx["snapshot_id"])
    agent_keys = [_s(s.get("agent_key")) for s in seats
                  if _s(s.get("origin")) in ("primary", "counter") and s.get("agent_key")]
    lines: list[str] = []
    used = 0
    for agent_key in agent_keys:
        line = _seat_memory_line(store, agent_key, target_key, lineage, subjects, adh, ctx)
        if used + len(line) + (1 if lines else 0) > E7_SEAT_TOTAL:
            break
        used += len(line) + (1 if lines else 0)
        lines.append(line)
    if not lines:
        lines = ["[착석 좌석 없음]"]
    return {"key": "E7", "args": ",".join(agent_keys), "result": _body(source, lines)}


def _seat_memory_line(store, agent_key: str, target_key: str, lineage: set[str],
                      subjects: set[str], adh, ctx) -> str:
    rows = store.query(
        "SELECT o.opinion_id, o.agent_key, o.target_key, o.raised_finding_ids_json, o.excerpt_for_rag, "
        "o.created_at, t.project_id FROM rr_seat_opinions AS o "
        "LEFT JOIN rr_targets AS t ON t.target_key = o.target_key "
        "WHERE o.agent_key = ? AND o.target_key <> ? "
        "AND o.raised_finding_ids_json IS NOT NULL AND o.raised_finding_ids_json <> '[]'",
        (agent_key, target_key),
    )
    if rows:
        def rank(row):
            in_lineage = 0 if row["project_id"] in lineage else 1
            overlap = 1
            if subjects:
                finding_subjects = _finding_subjects(store, _j(row["raised_finding_ids_json"], []))
                overlap = 0 if finding_subjects & subjects else 1
            return (in_lineage, overlap, -(row["created_at"] or 0), _s(row["opinion_id"]))
        best = sorted(rows, key=rank)[0]
        return _seat_line(store, best, _s(best["excerpt_for_rag"]))
    hit = _adh_seat_memory(adh, agent_key, ctx)
    if hit is not None:
        return hit
    return f"[{agent_key}: 이전 발언 없음]"


def _finding_subjects(store, finding_ids: Any) -> set[str]:
    if not isinstance(finding_ids, list) or not finding_ids:
        return set()
    ids = [str(x) for x in finding_ids][:20]
    marks = ",".join("?" for _ in ids)
    rows = store.query(
        f"SELECT subject_key FROM rr_findings WHERE finding_id IN ({marks})", ids)
    return {_s(r["subject_key"]) for r in rows if r["subject_key"]}


def _adh_seat_memory(adh, agent_key: str, ctx) -> str | None:
    """2차 경로 — AIDataHub 의사 에이전트 `risk-review-memory` 회수(plan §5.6.3 2). 미가용이면 None."""
    if adh is None or not getattr(adh, "available", False):
        return None
    summary = ""
    if ctx["kind"] == "diff" and ctx["diff"] is not None:
        summary = _s(ctx["diff"]["summary_text"])[:200]
    elif ctx["state"] is not None:
        summary = _s(ctx["state"]["summary_text"])[:200]
    code = _s(ctx["target"]["project_id"])
    reply = adh.agent_search("risk-review-memory", f"{code} {summary}", mode="hybrid",
                             required_tags=[f"hwax:expert:{agent_key}"], top_k=3,
                             exclude_tags=list(RECALL_EXCLUDE_TAGS))
    if not reply.get("ok"):
        return None
    hits = reply.get("result") or []
    if isinstance(hits, dict):
        hits = hits.get("hits") or hits.get("items") or []
    if not hits:
        return None
    hit = hits[0] if isinstance(hits[0], dict) else {}
    meta = ((hit.get("content") or {}).get("meta") or {}) if isinstance(hit.get("content"), dict) else {}
    portal = meta.get("portal") or {}
    opinion_id = _s(portal.get("opinion_id"))
    finding_id = _s(portal.get("finding_id"))
    if not opinion_id:
        return None
    prefix = f"narr:{opinion_id}#{finding_id} | {agent_key} | adh/{_s(hit.get('record_id'))[:12]} | "
    body = _s(hit.get("summary") or hit.get("text") or hit.get("title"))
    return prefix + _cut(body, max(0, E7_SEAT_LINE - len(prefix)))


# ---------------------------------------------------------------- E8 변경-델타 선례
def _item_e8(store, ctx) -> dict:
    source = _SOURCES["E8"][0]
    if ctx["kind"] != "diff" or ctx["diff"] is None:
        return {"key": "E8", "args": _s(ctx["target"]["target_key"]),
                "result": _body(source, ["[pair 전용 — 해당 없음]"])}
    diff_id = ctx["diff"]["id"]
    kinds = [r["change_kind"] for r in store.query(
        "SELECT DISTINCT change_kind FROM rr_diff_events WHERE diff_id = ? AND change_kind IS NOT NULL",
        (diff_id,))]
    kinds = [k for k in kinds if k not in ("discretization", "none")]
    lines: list[str] = []
    if kinds:
        # rr_delta_priors 는 코퍼스 통계 표라 owner_sub 열이 없다 — 소유자 필터를 걸지 않는다(plan §5.2.2 F).
        marks = ",".join("?" for _ in kinds)
        rows = store.query(
            "SELECT change_kind, mechanism, mechanism_detail, n_raised, n_targets, n_verified, n_dismissed "
            f"FROM rr_delta_priors WHERE change_kind IN ({marks})",
            kinds,
        )
        for row in sorted(rows, key=lambda r: (_s(r["change_kind"]), _s(r["mechanism"]),
                                               _s(r["mechanism_detail"]))):
            verified, dismissed = row["n_verified"] or 0, row["n_dismissed"] or 0
            total = verified + dismissed
            precision = f"{verified / total:.2f}" if total else "-"
            lines.append(
                f"{_s(row['change_kind'])} {_s(row['mechanism'])}.{_s(row['mechanism_detail'])} "
                f"n_raised={row['n_raised'] or 0} n_targets={row['n_targets'] or 0} "
                f"n_verified={verified} n_dismissed={dismissed} precision={precision} (n={total})"
            )
    if not lines:
        corpus = store.query_one("SELECT COUNT(*) AS n FROM rr_targets")
        lines = [f"[선례 없음 — 코퍼스 n_targets={corpus['n'] if corpus else 0}, 이 조합 첫 사례]"]
    return {"key": "E8", "args": f"diff:{diff_id}", "result": _body(source, lines)}


# ---------------------------------------------------------------- E9 warnings·rule_hits
_SEVERITY_RANK = {"치명": 0, "중대": 1, "경미": 2}


def _item_e9(ctx) -> dict:
    source = _SOURCES["E9"][0]
    lines: list[str] = []
    ir = _j(ctx["snapshot"]["ir_json"], {}) if ctx["snapshot"] is not None else {}
    warnings = ir.get("warnings") or []
    if isinstance(warnings, list):
        for warning in sorted(
                [w for w in warnings if isinstance(w, dict)],
                key=lambda w: (_SEVERITY_RANK.get(_s(w.get("severity")), 9), _s(w.get("code")))):
            ref_to = _s(warning.get("ref"))
            ref = f"warn:{_s(warning.get('code'))}" + (f"#{ref_to}" if ref_to else "")
            lines.append(f"{ref} {_q(warning.get('message'), 'message')}")
    hits = _j(ctx["state"]["rule_hits_json"], []) if ctx["state"] is not None else []
    if isinstance(hits, dict):
        hits = hits.get("hits") or []
    for hit in hits if isinstance(hits, list) else []:
        if not isinstance(hit, dict):
            continue
        # 행은 `state.evaluate_rules` 가 쓴 모양 그대로 읽는다 — id 는 `rule`, `pass` 는 **발화하지 않았다**,
        # `found` 는 `{count, refs, text}` 다. 종전에는 `rule_id`·`found` 목록·`pass=True` 를 '걸렸다' 로 읽어
        # 통과한 규칙을 id 없이 싣고 발화한 규칙을 건너뛰었다(시험이 손으로 쓴 행만 넣어 가려져 있었다).
        rule_id = _s(hit.get("rule"))
        if hit.get("evaluable") is False or hit.get("pass") is None:
            # 결측을 '이상 없음' 으로 읽히게 두지 않는다(plan §3.2.6·§5.6.1 E9).
            lines.append(f"rule:{rule_id} 평가 불가({_s(hit.get('not_evaluable_reason'), 'unknown')})")
            continue
        if hit.get("pass"):
            continue
        found = hit.get("found") if isinstance(hit.get("found"), dict) else {}
        # 참조는 공백으로 띄운다 — 쉼표로 붙이면 `d:a,req:b` 가 참조 하나로 읽힌다(collect_refs). R-007 의 참조에는
        # 사람이 지은 요구 이름이 들어 있어 E3 의 `[d:<name>]` 과 같은 위생을 거친다.
        refs = [_ref_name(x) for x in (found.get("refs") or [])[:3]]
        parts = [f"rule:{rule_id}", _s(hit.get("severity"), "-"), f"found={_s(found.get('count'), '?')}건", *refs,
                 _cut(hit.get("why_it_matters"), 350)]
        lines.append(" ".join(p for p in parts if p))
    if not lines:
        lines = ["[warnings 0 · rule_hits 0]"]
    return {"key": "E9", "args": _s(ctx["snapshot_id"]), "result": _body(source, lines)}


# ---------------------------------------------------------------- M 사용자 메모
# 메모를 다 싣지 못했을 때 줄 끝에 붙는 표지. 쓰는 쪽(`memo_result`)과 읽는 쪽(`memo_cut`)이 같은 꼴을 본다 —
# «…» 밖에 서므로 메모 원문이 흉내 낼 수 없다(위생이 원문 안의 « » 를 지운다).
_MEMO_CUT_FMT = " …(메모 {chars}자 중 {kept}자)"
_MEMO_CUT_RE = re.compile(re.escape(render.QUOTE_CLOSE) + r" …\(메모 (\d+)자 중 (\d+)자\)$")


def memo_result(target_key: str, memo: Any) -> str:
    """M 항목의 result — 프레이밍 줄 + 메모 한 줄. CAPS['M'] 에 안 들어가면 들어가는 만큼만 싣고 그 사실을 적는다.

    메모는 한 줄이라 넘치면 `clip_lines` 가 그 줄을 통째로 빼고 `…(1줄 생략)` 만 남겼다. 잡 API 는 2,000자까지
    받는데 약 290자부터 좌석은 메모를 한 글자도 못 봤고, 그 사실은 어디에도 남지 않았다(S26U 실사용 피드백 3-3 을
    재현하다 찾았다). 인젝션 어휘에 걸려 자리표시자로 바뀐 메모(§3.4.1)도 '좌석에 안 갔다' 이므로 0자로 적는다.
    """
    source, tool = _SOURCES["M"]
    room = CAPS["M"] - line_overhead({"source": source, "tool": tool, "args": _s(target_key)[:CLAMP_ARGS]}) \
        - len(_framing(source)) - 1
    chars = len(_s(memo))
    quoted = _q(memo, "memo")
    inner = quoted[1:-1]
    if inner.startswith("[suspect_text "):
        return _body(source, [quoted + _MEMO_CUT_FMT.format(chars=chars, kept=0)])
    if len(quoted) <= room:
        return _body(source, [quoted])
    kept = max(0, room - 2 - len(_MEMO_CUT_FMT.format(chars=chars, kept=chars)))
    return _body(source, [render.quote_source(inner[:kept]) + _MEMO_CUT_FMT.format(chars=chars, kept=kept)])


def memo_cut(item: Mapping[str, Any] | None) -> dict | None:
    """M 항목이 메모를 다 싣지 못했으면 `{chars, kept}`, 다 실었으면 None(`memo_result` 가 적은 표지를 읽는다)."""
    found = _MEMO_CUT_RE.search(_s((item or {}).get("result")))
    return {"chars": int(found.group(1)), "kept": int(found.group(2))} if found else None


def _item_memo(store, target_key: str, user_memo: str | None = None) -> dict | None:
    """M — `user_memo` 는 지금 도는 잡의 메모다(러너가 넘긴다). None 이면 그 타깃의 가장 최근 잡 메모를 읽는다.

    조회는 잡이 없는 미리보기·MCP 경로를 위한 것이다. 러너 경로까지 조회에 맡기면 한 타깃에 잡이 둘일 때
    앞 잡의 패널이 뒤 잡의 메모를 받고 제 메모는 말없이 사라진다. 빈 문자열은 '이 잡에는 메모가 없다' 다 —
    None 과 같이 다루면 메모 없이 만든 잡이 같은 타깃의 다른 잡 메모를 빌려 온다.
    """
    memo = user_memo
    if memo is None:
        row = store.query_one(
            "SELECT params_json FROM rr_jobs WHERE target_key = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (target_key,),
        )
        memo = _j(row["params_json"], {}).get("user_memo") if row is not None else None
    if not memo:
        return None
    return {"key": "M", "args": target_key, "result": memo_result(target_key, memo)}


# ---------------------------------------------------------------- 참조 수집·린터
def collect_refs(items: Sequence[Mapping[str, Any]]) -> list[str]:
    """브리프에 실린 reg:·narr:·rule:·c:·d: 참조 목록(중복 제거, 등장 순서, plan §5.6.4)."""
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        for token in _REF_TOKEN.findall(str(item.get("result") or "")):
            parsed = parse_ref(token)
            if parsed is None or parsed["kind"] not in _TRACKED_SCHEMES:
                continue
            ref = parsed["ref"]
            if ref not in seen:
                seen.add(ref)
                out.append(ref)
    return out


_QUOTE_PREFIX = ("reg:", "narr:", "rule:", "warn:")
# 자산 원문을 그대로 싣는 항목 — 좌석 계약은 사람이 쓴 계약문이라 인용이지 코드 산문이 아니다(plan §3.4.3).
_QUOTED_SOURCES = ("seat_contract",)


def lint_items(items: Sequence[Mapping[str, Any]]) -> dict:
    """코드가 쓴 문장에만 판단어 린터를 돌린다(원문 인용 줄은 제외, plan §5.6.2 린터 적용 범위).

    린터 정본은 `render.lint_text` 다 — 이름이 어긋나면 어떤 브리프도 검사되지 않고 조용히 통과하므로
    아래 테스트(test_brief.py)가 그 자리를 잠근다. render 를 못 읽는 경우에만 ok=None 이다.
    """
    try:
        from app import render  # type: ignore
    except ImportError:
        return {"ok": None, "reason": "render_unavailable", "violations": []}
    lint = getattr(render, "lint_text", None)
    if lint is None:
        return {"ok": None, "reason": "render_unavailable", "violations": []}
    violations: list[dict] = []
    for item in items:
        if str(item.get("source") or "") in _QUOTED_SOURCES:
            continue
        for line_no, line in enumerate(str(item.get("result") or "").split("\n"), start=1):
            if line.strip().startswith(_QUOTE_PREFIX):
                continue
            report = lint(line)
            for violation in (report or {}).get("violations") or []:
                violations.append({"item": item.get("key"), "line_no": line_no, **violation})
    return {"ok": not violations, "reason": None, "violations": violations}


# ---------------------------------------------------------------- 브리프 조립(정본)
def _seats_of_panel(store, target_key: str, panel_id: str | None) -> list[dict]:
    """패널 seats_json 을 읽는다. panel_id 가 없으면 그 타깃의 최근 패널을 쓴다."""
    if panel_id:
        row = store.query_one("SELECT seats_json FROM rr_panels WHERE id = ?", (panel_id,))
    else:
        row = store.query_one(
            "SELECT seats_json FROM rr_panels WHERE target_key = ? ORDER BY panel_no DESC LIMIT 1",
            (target_key,),
        )
    if row is None:
        return []
    seats = _j(row["seats_json"], [])
    return [s for s in seats if isinstance(s, dict)] if isinstance(seats, list) else []


def build_brief(store, target_key: str, *, seats: Sequence[Mapping[str, Any]] | None = None,
                panel_id: str | None = None, exclude: Sequence[str] = (), owner_sub: str | None = None,
                adh=None, ra=None, field=None, strict_lint: bool = False,
                user_memo: str | None = None) -> dict:
    """타깃·패널을 받아 E0~E9 를 delib_opts.evidence 형식으로 조립한다(plan §5.6.2, 결정론).

    항목마다 라인 길이를 CAP 안으로 먼저 강제하므로 엔진 예산 11000 에서 드롭이 0 이다.
    `exclude` 는 항목 키(E6·E8 …)의 제외만 받는다 — 추가·편집은 없다(§5.7 RecallPreview).
    `user_memo` 는 지금 도는 잡의 메모다 — 안 주면 M 은 그 타깃의 최근 잡 메모를 읽는다(`_item_memo`).
    """
    ctx = _target_context(store, target_key)
    if owner_sub is None:
        owner_sub = _s(ctx["target"]["owner_sub"]) or None
    if seats is None:
        seats = _seats_of_panel(store, target_key, panel_id)
    external_ok = bool(adh is not None and getattr(adh, "available", False)) or \
        bool(ra is not None and getattr(ra, "available", False))
    similar = similar_projects(store, _s(ctx["target"]["project_id"]), adh=adh, ra=ra, owner_sub=owner_sub)

    # 조립하는 동안 원천 문자열 위생(§3.4.1)의 suspect_text 적재 대상을 이 스레드에 걸어 둔다.
    begin_suspect_queue(store, owner_sub)
    try:
        raw: list[dict] = [
            _item_e0(store, ctx, external_ok, _panel_model(store, target_key, panel_id)),
            _item_e0c(seats),
            _item_e1(ctx),
            _item_e2(store, ctx),
            _item_e3(ctx),
            _item_e4(ctx),
            _item_e5(store, ctx, similar, owner_sub, field),
            _item_e6(store, similar, ctx),
            _item_e7(store, ctx, seats, adh),
            _item_e8(store, ctx),
            _item_e9(ctx),
        ]
        memo = _item_memo(store, target_key, user_memo)
        if memo is not None:
            raw.append(memo)
    finally:
        end_suspect_queue()

    excluded = {str(x) for x in exclude}
    order = {key: i for i, key in enumerate(ITEM_ORDER)}
    raw = sorted([i for i in raw if i["key"] not in excluded], key=lambda i: order[i["key"]])

    items: list[dict] = []
    for entry in raw:
        source, tool = _SOURCES[entry["key"]]
        source, tool = entry.get("source") or source, entry.get("tool") or tool
        item = {
            "source": source[:CLAMP_SOURCE],
            "tool": tool[:CLAMP_TOOL],
            "args": _s(entry["args"])[:CLAMP_ARGS],
            "result": entry["result"],
        }
        cap = CAPS[entry["key"]]
        item["result"] = clip_lines(item["result"], min(CLAMP_RESULT, cap - line_overhead(item)))
        assert len(evidence_line(item)) <= cap, f"{entry['key']} 라인이 CAP {cap} 을 넘었습니다."
        item["key"] = entry["key"]
        items.append(item)

    total = sum(len(evidence_line(i)) for i in items)
    assert total <= ENGINE_BUDGET and len(items) <= EVIDENCE_MAX_ITEMS

    lint = lint_items(items)
    if strict_lint and lint["ok"] is False:
        raise AppError("E500", f"브리프 판단어 린터 위반 {len(lint['violations'])}건", http_status=500)
    return {
        "target_key": target_key,
        # 항목 키(E0~E9·E0c·M)를 다섯 번째 필드로 남긴다 — 엔진이 줄 머리를 `[e:N|E3]` 으로 찍어 좌석이 번호뿐
        # 아니라 항목 이름으로 근거를 가리킨다(종전에는 여기서 떼어 `[e:N]` 뿐이었다). `evidence_line` 은 키를
        # 세지 않는다 — 접두가 늘어도 예산 안이라는 것은 시험(test_brief)이 실제 자산으로 지킨다.
        "evidence": [{k: i[k] for k in ("source", "tool", "args", "result", "key")} for i in items],
        "keys": [i["key"] for i in items],
        "refs": collect_refs(items),
        "meta": {
            "budget_used": total,
            "budget": ENGINE_BUDGET,
            "caps_sum": sum(CAPS[i["key"]] for i in items),
            "dropped": 0,
            # 메모를 다 못 실었으면 {chars, kept} — 미리보기·MCP 호출자가 여기서 본다(패널에는 러너가 남긴다).
            "user_memo_cut": memo_cut(next((i for i in items if i["key"] == "M"), None)),
            "excluded": sorted(excluded),
            "external_search": "available" if external_ok else "unavailable",
            "lint": lint,
            "similar_corpus_n": similar.get("corpus_n", 0),
        },
    }


# ---------------------------------------------------------------- §5.7 유사 검색
def _latest_snapshot_by_project(store) -> dict[str, str]:
    """과제별 최신 스냅샷 — 코퍼스에서 빠진 과제(§0.6)는 애초에 들어오지 않는다."""
    corpus = _corpus_ids(store)
    rows = store.query(
        "SELECT project_id, id, created_at FROM rr_snapshots ORDER BY project_id, created_at, id")
    out: dict[str, str] = {}
    for row in rows:
        if _s(row["project_id"]) not in corpus:
            continue
        out[_s(row["project_id"])] = _s(row["id"])
    return out


def _feature_stats(store) -> dict[str, tuple[float, float]]:
    """rr_metrics(dimension='global') 의 fv_mean_<k>·fv_std_<k> 를 읽는다(없으면 빈 dict)."""
    rows = store.query(
        "SELECT metric, value FROM rr_metrics WHERE dimension = 'global' AND "
        "(metric LIKE 'fv_mean_%' OR metric LIKE 'fv_std_%')")
    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    for row in rows:
        metric = _s(row["metric"])
        value = row["value"]
        if value is None:
            continue
        if metric.startswith("fv_mean_"):
            means[metric[len("fv_mean_"):]] = float(value)
        else:
            stds[metric[len("fv_std_"):]] = float(value)
    return {k: (means[k], stds.get(k) or 1.0) for k in means}


def _feature_vec(raw: Any) -> tuple[list[str], list[float], list[bool]]:
    doc = _j(raw, {})
    names = doc.get("names") or []
    values = doc.get("values") or []
    known = doc.get("known") or [True] * len(values)
    return ([str(n) for n in names], [float(v) if isinstance(v, (int, float)) else 0.0 for v in values],
            [bool(k) for k in known])


def _cosine(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    dot = sum(a[k] * b[k] for k in shared)
    na = sum(a[k] * a[k] for k in shared) ** 0.5
    nb = sum(b[k] * b[k] for k in shared) ** 0.5
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


def _standardized(store, snapshot_id: str, stats: Mapping[str, tuple[float, float]]) -> dict[str, float]:
    row = store.query_one("SELECT feature_json FROM rr_states WHERE snapshot_id = ?", (snapshot_id,))
    if row is None:
        return {}
    names, values, known = _feature_vec(row["feature_json"])
    out: dict[str, float] = {}
    for i, name in enumerate(names):
        if i >= len(values) or (i < len(known) and not known[i]):
            continue
        mean, std = stats.get(name, (0.0, 1.0))
        out[name] = (values[i] - mean) / (std if std else 1.0)
    return out


def similar_projects(store, project_id: str, k: int = 5, *, owner_sub: str | None = None,
                     adh=None, ra=None) -> dict:
    """§5.7 호출 계약의 응답 — 경로별(lineage·vector·text·subject) 목록과 가중 merged.

    절대 코사인 임계는 두지 않는다(상대 순위만 쓴다). 외부 미가용 경로는 reason 과 함께 비운다.
    """
    lineage: list[dict] = []
    seen = {project_id}
    current = project_id
    for hop in range(1, 4):
        row = store.query_one("SELECT predecessor_project_id FROM rr_projects WHERE id = ?", (current,))
        current = row["predecessor_project_id"] if row is not None else None
        if not current or current in seen:
            break
        seen.add(current)
        lineage.append({"project_id": current, "code": _project_code(store, current),
                        "hops": hop, "relation": "predecessor"})
    frontier = [project_id]
    for hop in range(1, 4):
        if not frontier:
            break
        marks = ",".join("?" for _ in frontier)
        rows = store.query(f"SELECT id FROM rr_projects WHERE predecessor_project_id IN ({marks})", frontier)
        frontier = []
        for row in rows:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            lineage.append({"project_id": row["id"], "code": _project_code(store, row["id"]),
                            "hops": hop, "relation": "successor"})
            frontier.append(row["id"])

    # 코퍼스에서 빠진 과제는 어느 경로로도 회수되지 않는다(§0.6 코퍼스 필터).
    corpus = _corpus_ids(store)
    lineage = [entry for entry in lineage if entry["project_id"] in corpus]
    latest = _latest_snapshot_by_project(store)
    corpus_n = len([p for p in latest if store.query_one(
        "SELECT snapshot_id FROM rr_states WHERE snapshot_id = ?", (latest[p],)) is not None])
    vector: list[dict] = []
    vector_reason = None
    if corpus_n < VECTOR_MIN_CORPUS:
        vector_reason = f"corpus_n={corpus_n} < {VECTOR_MIN_CORPUS}"
    elif project_id in latest:
        stats = _feature_stats(store)
        mine = _standardized(store, latest[project_id], stats)
        scored = []
        for other, snapshot_id in sorted(latest.items()):
            if other == project_id:
                continue
            theirs = _standardized(store, snapshot_id, stats)
            if not theirs:
                continue
            # 이름을 최종 타이브레이크로 둔다 — std=0 인 피처는 곱이 전부 0.0 이라 동점이 상시이고,
            # 집합 순회 순서는 PYTHONHASHSEED 로 프로세스마다 달라진다.
            top = sorted(set(mine) & set(theirs), key=lambda n: (-abs(mine[n] * theirs[n]), n))[:3]
            scored.append({"project_id": other, "snapshot_id": snapshot_id,
                           "cosine": round(_cosine(mine, theirs), 6), "top_features": top})
        scored.sort(key=lambda e: (-e["cosine"], e["project_id"]))
        for rank, entry in enumerate(scored[:k], start=1):
            vector.append({**entry, "rank": rank})
    else:
        vector_reason = "스냅샷 없음"

    text, text_reason = _text_path(store, project_id, latest, adh, k)
    subject = _subject_path(store, latest.get(project_id), owner_sub)

    merged_scores: dict[str, dict] = {}

    def _add(pid: str, path: str) -> None:
        if not pid or pid == project_id:
            return
        entry = merged_scores.setdefault(pid, {"project_id": pid, "score": 0.0, "paths": []})
        if path not in entry["paths"]:
            entry["paths"].append(path)
            entry["score"] += _PATH_WEIGHT.get(path, _PATH_WEIGHT["subject"])

    for entry in lineage:
        _add(entry["project_id"], "lineage")
    for entry in vector:
        _add(entry["project_id"], "vector")
    for entry in text:
        _add(_s(entry.get("project_id")), "text")
    for entry in subject:
        for pid in entry.get("project_ids") or []:
            _add(pid, _s(entry.get("path"), "subject"))
    merged = sorted(merged_scores.values(), key=lambda e: (-e["score"], e["project_id"]))[:k]

    return {"lineage": lineage, "vector": vector, "text": text, "subject": subject,
            "merged": merged, "corpus_n": corpus_n,
            "reason": {"vector": vector_reason, "text": text_reason}}


def _text_path(store, project_id: str, latest: Mapping[str, str], adh, k: int) -> tuple[list[dict], str | None]:
    """AIDataHub hybrid_search 로 유사 서술을 찾는다(plan §7.3 3단계). 미가용이면 빈 목록."""
    if adh is None or not getattr(adh, "available", False):
        return [], "external_sync=unavailable"
    snapshot_id = latest.get(project_id)
    if not snapshot_id:
        return [], "스냅샷 없음"
    state = store.query_one("SELECT summary_text FROM rr_states WHERE snapshot_id = ?", (snapshot_id,))
    query = _s(state["summary_text"])[:300] if state is not None else ""
    if not query:
        return [], "summary_text 없음"
    reply = adh.hybrid_search(query, top_k=k, tags=["hwax-risk-review"],
                              exclude_tags=list(RECALL_EXCLUDE_TAGS))
    if not reply.get("ok"):
        return [], _s(reply.get("error"), "hybrid_search 실패")
    hits = reply.get("result") or []
    if isinstance(hits, dict):
        hits = hits.get("items") or hits.get("hits") or []
    out: list[dict] = []
    for rank, hit in enumerate(hits if isinstance(hits, list) else [], start=1):
        if not isinstance(hit, dict):
            continue
        tags = hit.get("tags") or []
        pid = next((str(t)[len("hwax:project:"):] for t in tags
                    if str(t).startswith("hwax:project:")), None)
        if not pid or pid == project_id:
            continue
        out.append({"record_id": _s(hit.get("record_id") or hit.get("id")), "project_id": pid,
                    "rank": rank, "section_id": _s(hit.get("section_id"))})
    return out, None


def alias_expand(store, keys: set[str]) -> dict[str, str]:
    """subject_key 집합을 `rr_iface_alias`(status='active') 로 양방향 확장한다(plan §5.9.4·§0.9 P5-5).

    반환은 `{조회 키: 경로 태그}` 다 — 원래 키는 'subject', 별칭으로 이어붙인 키는 'subject·별칭' 이라
    그 줄이 무엇으로 이어졌는지 브리프에 남는다. 계보가 없고 이름 규칙이 다른 과제를 잇는 유일한 다리다.
    """
    out: dict[str, str] = {key: "subject" for key in keys if key}
    if not keys:
        return out

    def bare(key: str) -> str:
        """계면 subject_key 는 `iface:` 접두를 달고 오기도 한다 — 비교는 접두를 뗀 쌍으로 한다."""
        return key[len("iface:"):] if key.startswith("iface:") else key

    bare_keys = {bare(key): key for key in keys if key}
    rows = store.query(
        "SELECT alias_key, canonical_a, canonical_b FROM rr_iface_alias WHERE status = 'active'", ())
    for row in rows:
        alias_key = _s(row["alias_key"])
        canonical = "|".join(sorted([_s(row["canonical_a"]), _s(row["canonical_b"])]))
        if not alias_key or not canonical:
            continue
        if bare(alias_key) in bare_keys:
            out.setdefault(canonical, "subject·별칭")
            out.setdefault(f"iface:{canonical}", "subject·별칭")
        if bare(canonical) in bare_keys:
            out.setdefault(alias_key, "subject·별칭")
    return out


def _subject_path(store, snapshot_id: str | None, owner_sub: str | None) -> list[dict]:
    """§5.9.4 1) 정확 매치 — 이번 IR 의 subject_key(별칭 확장 포함)로 등록부를 회수한다."""
    paths = alias_expand(store, _subject_keys(store, snapshot_id))
    if not paths:
        return []
    out: list[dict] = []
    for subject_key in sorted(paths):
        vis, vis_params = _visibility_clause(owner_sub)
        rows = store.query(
            "SELECT target_key, status FROM rr_registry WHERE subject_key = ? "
            f"AND status IN ('open','verified'){vis}",
            [subject_key, *vis_params],
        )
        if not rows:
            continue
        project_ids: list[str] = []
        for row in rows:
            target = store.query_one(
                "SELECT project_id FROM rr_targets WHERE target_key = ?", (row["target_key"],))
            pid = _s(target["project_id"]) if target is not None else ""
            if pid and pid not in project_ids:
                project_ids.append(pid)
        project_ids = [pid for pid in project_ids if pid in _corpus_ids(store)]
        if not project_ids:
            continue
        out.append({"subject_key": subject_key, "n_registry": len(rows),
                    "n_verified": len([r for r in rows if r["status"] == "verified"]),
                    "project_ids": project_ids, "path": paths[subject_key]})
    return out


# ---------------------------------------------------------------- §5.7 선례 패널
def precedents(store, diff_id: str, *, owner_sub: str | None = None) -> dict:
    """ComparePage '선례' 패널과 E5·E8 의 원천(plan §5.7 두 번째 행)."""
    diff = store.query_one("SELECT id, target_snapshot_id FROM rr_diffs WHERE id = ?", (diff_id,))
    if diff is None:
        raise AppError("E404", f"diff 가 없습니다: {diff_id}", http_status=404)
    kinds = [r["change_kind"] for r in store.query(
        "SELECT DISTINCT change_kind FROM rr_diff_events WHERE diff_id = ? AND change_kind IS NOT NULL",
        (diff_id,)) if r["change_kind"] not in ("discretization", "none")]
    delta_priors: list[dict] = []
    if kinds:
        marks = ",".join("?" for _ in kinds)
        for row in store.query(
                "SELECT change_kind, mechanism, mechanism_detail, n_raised, n_targets, n_verified, "
                f"n_dismissed FROM rr_delta_priors WHERE change_kind IN ({marks})", kinds):
            delta_priors.append({k: row[k] for k in (
                "change_kind", "mechanism", "mechanism_detail", "n_raised", "n_targets",
                "n_verified", "n_dismissed")})
    subject = _subject_path(store, _s(diff["target_snapshot_id"]), owner_sub)
    clusters: list[dict] = []
    for hit in subject:
        vis, vis_params = _visibility_clause(owner_sub, "r")
        for row in store.query(
                f"SELECT {_REGISTRY_COLS} FROM rr_registry AS r WHERE r.subject_key = ? "
                f"AND r.status IN ('open','verified'){vis}", [hit["subject_key"], *vis_params]):
            merged = _j(row["merged_json"], {})
            clusters.append({
                "reg_ref": f"reg:{row['target_key']}#{row['cluster_key']}",
                "target_key": row["target_key"],
                "project_code": _project_code(store, _target_project(store, row["target_key"])),
                "cluster_key": row["cluster_key"],
                "subject_names": merged.get("subject_names") or row["subject_key"],
                "severity": row["severity"], "status": row["status"], "support": row["support"],
                "claim": merged.get("claim"), "path": hit["path"],
            })
    state = store.query_one(
        "SELECT rule_hits_json FROM rr_states WHERE snapshot_id = ?", (diff["target_snapshot_id"],))
    hits = _j(state["rule_hits_json"], []) if state is not None else []
    if isinstance(hits, dict):
        hits = hits.get("hits") or []
    patterns = [{k: row[k] for k in ("id", "status", "n_projects", "precision")}
                for row in store.query(
                    "SELECT id, status, n_projects, precision FROM rr_patterns "
                    "WHERE status IN ('candidate','known') ORDER BY id")]
    return {"delta_priors": delta_priors, "clusters": clusters,
            "rule_hits": hits if isinstance(hits, list) else [],
            "pattern_candidates": [{"pattern_id": p["id"], "status": p["status"],
                                    "n_projects": p["n_projects"], "precision": p["precision"]}
                                   for p in patterns]}


def _target_project(store, target_key: str) -> str | None:
    row = store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (target_key,))
    return _s(row["project_id"]) if row is not None else None
