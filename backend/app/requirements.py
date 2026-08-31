# 요구 규격(rr_requirements) — REST 4행의 동작 함수와 판정 보조(sig:req.*·missing.req_*·finding requirement_ref)
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, MutableMapping, Sequence
from typing import Any

from app.common import canonical_json, new_uuid, now_epoch
from app.errors import AppError

__all__ = [
    "KINDS",
    "OPS",
    "STATUSES",
    "REQ_PREFIX",
    "EXPERIENCE_BASIS_TEXT",
    "list_requirements",
    "upsert_requirements",
    "decide_requirement",
    "inherit_requirements",
    "snapshots_to_recompute",
    "compute_req_signals",
    "judgement_basis",
    "requirement_ref",
    "parse_requirement_ref",
    "requirement_index",
    "margins_by_name",
    "check_finding_requirement",
]

# plan §2.8b·§5.2.2 A 의 어휘. DB CHECK 과 같은 집합이고 여기서 먼저 걸러 422 를 준다.
KINDS: tuple[str, ...] = ("dim_limit", "scenario", "standard")
OPS: tuple[str, ...] = ("lte", "gte", "between")
STATUSES: tuple[str, ...] = ("candidate", "confirmed", "waived")

# 인용 문법 `req:<name>`(plan §0.2.1). common.REF_SCHEMES 에는 아직 'req' 가 없어 여기서 따로 판다.
REQ_PREFIX = "req:"

# 요구가 0건인 과제에서 좌석이 판정 옆에 적어야 하는 문장(plan §6.5.3 `_common` 문면 그대로).
EXPERIENCE_BASIS_TEXT = "요구 미등록 — 이 판정은 내 경험 기준"

# 대조에 쓰는 상태 — waived 는 사람이 사유와 함께 면제한 요구라 대조하지 않고 표기만 한다(plan §2.8b 공통 필드).
_ACTIVE_STATUSES: tuple[str, ...] = ("candidate", "confirmed")

_COLUMNS = (
    "id, project_id, owner_sub, kind, name, op, value_json, unit, source_ref, status, waive_reason,"
    " inherited_from, decided_by, decided_at, created_at, updated_at"
)
# GET 응답 키(plan §8.2.3 requirements 행). value 는 value_json 을 푼 값이다.
_PUBLIC_KEYS = ("id", "kind", "name", "op", "value", "unit", "source_ref", "status", "waive_reason",
                "inherited_from", "decided_by", "decided_at")

_REASON_MAX = 300


# ---------------------------------------------------------------- 행 변환
def _loads(text: Any) -> Any:
    if text is None or text == "":
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        # 저장 시 canonical_json 으로 넣으므로 정상 경로에서는 오지 않는다. 깨진 행은 원문을 그대로 보인다.
        return text


def _public(row: Mapping[str, Any]) -> dict:
    """rr_requirements 행 하나를 REST 응답 형상으로 바꾼다(value_json → value)."""
    item = dict(row)
    item["value"] = _loads(item.get("value_json"))
    return {key: item.get(key) for key in _PUBLIC_KEYS}


def _rows(store, sql: str, params: Sequence[Any]) -> list[dict]:
    return [dict(r) for r in store.query(sql, params)]


# ---------------------------------------------------------------- GET /projects/{id}/requirements
def list_requirements(store, project_id: str, *, kind: str | None = None,
                      status: str | None = None) -> dict:
    """과제의 요구 목록. 필터는 kind·status 이고 정렬은 (kind, name) 고정이다."""
    if kind is not None and kind not in KINDS:
        raise AppError("kind_unknown", f"kind 는 {list(KINDS)} 중 하나여야 합니다 — {kind!r}.", 422)
    if status is not None and status not in STATUSES:
        raise AppError("status_unknown", f"status 는 {list(STATUSES)} 중 하나여야 합니다 — {status!r}.", 422)
    sql = f"SELECT {_COLUMNS} FROM rr_requirements WHERE project_id = ?"
    params: list[Any] = [project_id]
    if kind is not None:
        sql += " AND kind = ?"
        params.append(kind)
    if status is not None:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY kind, name"
    return {"requirements": [_public(r) for r in _rows(store, sql, params)]}


# ---------------------------------------------------------------- POST /projects/{id}/requirements
def _validate_item(item: Mapping[str, Any], *, index: int, vocab: Mapping[str, Mapping[str, Any]]) -> dict:
    """입력 1건을 plan §2.8b 불변식으로 검사하고 저장 형상으로 바꾼다."""
    where = f"요구 {index} 번째"
    kind = str(item.get("kind") or "")
    if kind not in KINDS:
        raise AppError("kind_unknown", f"{where}: kind 는 {list(KINDS)} 중 하나여야 합니다 — {kind!r}.", 422)
    name = str(item.get("name") or "").strip()
    if not name:
        raise AppError("name_required", f"{where}: name 이 비었습니다.", 422)
    op = item.get("op")
    unit = item.get("unit")
    value = item.get("value_json", item.get("value"))
    source_ref = item.get("source_ref")
    source_ref = str(source_ref).strip() if source_ref is not None and str(source_ref).strip() else None

    if kind == "dim_limit":
        if op is None or value is None or not unit:
            raise AppError("dim_limit_incomplete",
                           f"{where}: dim_limit 은 op·value_json·unit 이 모두 필요합니다 — {name!r}.", 422)
        if op not in OPS:
            raise AppError("op_unknown", f"{where}: op 는 {list(OPS)} 중 하나여야 합니다 — {op!r}.", 422)
        _check_limit_value(op, value, where=where, name=name)
        entry = vocab.get(name)
        if entry is None:
            # 치수 한계의 name 은 rr_dim_vocab 에 있어야 대조 대상(dims_named)이 정해진다.
            raise AppError("unknown_dim_name", f"{where}: rr_dim_vocab 에 없는 치수 이름입니다 — {name!r}.", 422)
        vocab_unit = entry.get("unit")
        if vocab_unit and str(unit) != str(vocab_unit):
            raise AppError("unit_mismatch",
                           f"{where}: 단위가 rr_dim_vocab 과 다릅니다 — {name!r} 은 {vocab_unit!r} 인데 {unit!r} 입니다.", 400)
    else:
        # dim_limit 전용 열은 그 밖의 kind 에서 NULL 이다(DDL 주석).
        op, unit = None, None
        if kind == "standard" and not source_ref:
            raise AppError("source_ref_required",
                           f"{where}: standard 는 source_ref(card:·paper:·URL)가 필요합니다 — {name!r}.", 422)

    return {
        "kind": kind, "name": name, "op": op, "unit": str(unit) if unit else None,
        "value_json": canonical_json(value) if value is not None else None,
        "source_ref": source_ref,
    }


def _check_limit_value(op: str, value: Any, *, where: str, name: str) -> None:
    """dim_limit 의 value 형상 — lte·gte 는 스칼라, between 은 [lo, hi] 다(plan §2.8b)."""
    def _num(x: Any) -> bool:
        return isinstance(x, (int, float)) and not isinstance(x, bool)

    if op == "between":
        ok = isinstance(value, (list, tuple)) and len(value) == 2 and all(_num(v) for v in value) and value[0] <= value[1]
        if not ok:
            raise AppError("value_invalid", f"{where}: between 은 [lo, hi] 두 수여야 합니다 — {name!r}={value!r}.", 422)
    elif not _num(value):
        raise AppError("value_invalid", f"{where}: {op} 는 스칼라 수여야 합니다 — {name!r}={value!r}.", 422)


def upsert_requirements(store, project_id: str, owner_sub: str, items: Sequence[Mapping[str, Any]]) -> dict:
    """요구 배열을 `UNIQUE(project_id, kind, name)` 기준으로 UPSERT 한다(plan §8.2.3 POST).

    `owner_sub` 는 호출자가 아니라 과제 소유자(`rr_projects.owner_sub`)다 — 다른 하위 표와 같은 소유 앵커라
    이양·회수·export 가 한 값으로 움직인다. 사람이 정한 값(status·waive_reason·inherited_from·decided_*)은
    UPSERT 가 건드리지 않는다 — 같은 요구를 다시 올려도 confirmed·waived 결정은 그대로 남는다.
    요구는 `ir_hash` 를 바꾸지 않으므로 응답의 `recompute` 는 rr_states 만 다시 계산하면 되는 스냅샷 목록이다
    (plan §2.8b (1)). 권한(`require_role(project_id, 'editor')`)과 `rr_audit` 기록은 라우트의 몫이다.
    """
    vocab = {r["name"]: dict(r) for r in store.query("SELECT name, unit FROM rr_dim_vocab", ())}
    prepared: dict[tuple[str, str], dict] = {}
    for index, item in enumerate(items or ()):
        row = _validate_item(item, index=index, vocab=vocab)
        prepared[(row["kind"], row["name"])] = row     # 한 요청 안 중복은 마지막 값이 이긴다
    if not prepared:
        return {"upserted": 0, "rows": [], "recompute": []}

    now = now_epoch()
    with store.tx():
        for row in prepared.values():
            store.execute(
                "INSERT INTO rr_requirements(id, project_id, owner_sub, kind, name, op, value_json, unit,"
                " source_ref, status, waive_reason, inherited_from, decided_by, decided_at, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,'candidate',NULL,NULL,NULL,NULL,?,?)"
                " ON CONFLICT(project_id, kind, name) DO UPDATE SET op=excluded.op,"
                " value_json=excluded.value_json, unit=excluded.unit, source_ref=excluded.source_ref,"
                " updated_at=excluded.updated_at",
                (new_uuid(), project_id, owner_sub, row["kind"], row["name"], row["op"], row["value_json"],
                 row["unit"], row["source_ref"], now, now))

    placeholders = ",".join(["(?,?)"] * len(prepared))
    params: list[Any] = [project_id]
    for kind, name in prepared:
        params.extend([kind, name])
    rows = _rows(
        store,
        f"SELECT {_COLUMNS} FROM rr_requirements WHERE project_id = ?"
        f" AND (kind, name) IN ({placeholders}) ORDER BY kind, name",
        params)
    return {"upserted": len(prepared), "rows": [_public(r) for r in rows],
            "recompute": snapshots_to_recompute(store, project_id)}


def snapshots_to_recompute(store, project_id: str) -> list[str]:
    """요구가 바뀌었을 때 rr_states 만 다시 계산하면 되는 스냅샷 id 목록(ir_hash 는 불변, plan §2.8b (1))."""
    rows = store.query(
        "SELECT id FROM rr_snapshots WHERE project_id = ? ORDER BY created_at, id", (project_id,))
    return [r["id"] for r in rows]


# ---------------------------------------------------------------- PUT /requirements/{id}
def decide_requirement(store, requirement_id: str, *, status: str, waive_reason: str | None = None,
                       actor_sub: str) -> dict:
    """요구 1건의 status 를 사람이 정한다(plan §8.2.3 PUT). `waived` 는 사유가 없으면 422 다.

    응답의 `status_source` 는 계산값이다 — rr_requirements 에는 그 열이 없고 사람 결정만 이 함수를 통과한다.
    `rr_audit(action='requirement.decide')` 1행은 라우트가 쓴다.
    """
    if status not in STATUSES:
        raise AppError("status_unknown", f"status 는 {list(STATUSES)} 중 하나여야 합니다 — {status!r}.", 422)
    row = store.query_one(f"SELECT {_COLUMNS} FROM rr_requirements WHERE id = ?", (requirement_id,))
    if row is None:
        raise AppError("E404", f"요구를 찾을 수 없습니다 — {requirement_id}.", 404)
    reason = (waive_reason or "").strip()
    if status == "waived" and not reason:
        raise AppError("reason_required", "status='waived' 는 사유가 필요합니다.", 422)
    # waived 를 벗어나면 사유도 함께 지운다 — 면제가 풀린 요구에 남은 사유는 거짓 표기다.
    stored_reason = reason[:_REASON_MAX] if status == "waived" else None
    now = now_epoch()
    store.execute(
        "UPDATE rr_requirements SET status = ?, waive_reason = ?, decided_by = ?, decided_at = ?,"
        " updated_at = ? WHERE id = ?",
        (status, stored_reason, actor_sub, now, now, requirement_id))
    updated = store.query_one(f"SELECT {_COLUMNS} FROM rr_requirements WHERE id = ?", (requirement_id,))
    return {**_public(dict(updated)), "project_id": dict(updated)["project_id"], "status_source": "human"}


# ---------------------------------------------------------------- POST /projects/{id}/requirements/inherit
def inherit_requirements(store, project_id: str, owner_sub: str, from_project_id: str) -> dict:
    """계보 과제의 요구를 복사한다 — `status='candidate'`·`inherited_from=<원본 id>`, 멱등(plan §2.8b (2)).

    같은 `(kind, name)` 이 이미 있으면 건너뛴다(덮어쓰지 않는다). `owner_sub` 는 받는 과제의 소유자다.
    원본 과제의 조회 범위 판정(403 `not_a_member`)은 라우트가 §5.2.1 조회 규약으로 먼저 본다 —
    여기서는 존재 여부만 404 로 가른다.
    """
    if from_project_id == project_id:
        raise AppError("same_project", "자기 자신에게서 요구를 승계할 수 없습니다.", 422)
    if store.query_one("SELECT id FROM rr_projects WHERE id = ?", (from_project_id,)) is None:
        raise AppError("source_project_not_found", f"승계 원본 과제가 없습니다 — {from_project_id}.", 404)

    source = _rows(
        store,
        f"SELECT {_COLUMNS} FROM rr_requirements WHERE project_id = ? ORDER BY kind, name",
        (from_project_id,))
    existing = {(r["kind"], r["name"]) for r in _rows(
        store, "SELECT kind, name FROM rr_requirements WHERE project_id = ?", (project_id,))}

    now = now_epoch()
    copied = 0
    with store.tx():
        for row in source:
            if (row["kind"], row["name"]) in existing:
                continue
            store.execute(
                "INSERT INTO rr_requirements(id, project_id, owner_sub, kind, name, op, value_json, unit,"
                " source_ref, status, waive_reason, inherited_from, decided_by, decided_at, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,'candidate',NULL,?,NULL,NULL,?,?)",
                (new_uuid(), project_id, owner_sub, row["kind"], row["name"], row["op"], row["value_json"],
                 row["unit"], row["source_ref"], row["id"], now, now))
            existing.add((row["kind"], row["name"]))
            copied += 1
    return {"copied": copied, "skipped": len(source) - copied}


# ---------------------------------------------------------------- 판정 보조 — sig:req.* · missing.req_*
def _rec(kind: str, value: Any, unit: str | None, refs: Sequence[str], text: str, known: bool = True) -> dict:
    """state.compute_signals 의 레코드 형상과 같다(state.put 이 render.signal_text 로 text 를 덮을 수 있다)."""
    return {"kind": kind, "value": value, "unit": unit, "refs": list(refs),
            "text": text, "derived_from": [], "known": bool(known)}


def _num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _round(x: float | None, digits: int = 6) -> float | None:
    return None if x is None else round(float(x), digits)


def _margin(op: str, limit: Any, actual: float) -> tuple[float | None, float | None]:
    """여유와 상대여유 — lte 는 limit−actual, gte 는 actual−limit, between 은 두 여유의 최솟값(plan §2.8b)."""
    if op == "lte" and _num(limit):
        margin = float(limit) - actual
        rel = margin / abs(float(limit)) if float(limit) else None
    elif op == "gte" and _num(limit):
        margin = actual - float(limit)
        rel = margin / abs(float(limit)) if float(limit) else None
    elif op == "between" and isinstance(limit, (list, tuple)) and len(limit) == 2:
        lo, hi = float(limit[0]), float(limit[1])
        margin = min(actual - lo, hi - actual)
        band = hi - lo
        rel = margin / band if band else None
    else:
        return None, None
    return _round(margin), (None if rel is None else round(rel, 3))


def _margin_line(row: Mapping[str, Any]) -> str:
    """`sig:req.margin` 한 행의 정규 표기. 미측정은 0 이 아니라 '미측정' 이다."""
    limit = canonical_json(row["limit"])
    unit = f" {row['unit']}" if row.get("unit") else ""
    actual = row["actual"] if row["known"] else "미측정"
    margin = row["margin"] if row["margin"] is not None else "미측정"
    return f"req:{row['name']} {row['op']} {limit}{unit} actual={actual} margin={margin}"


def _margin_sort_key(row: Mapping[str, Any]) -> tuple:
    """margin 오름차순. 미측정(known=false)은 0 이 아니라 맨 뒤다."""
    margin = row.get("margin")
    return (margin is None, margin if margin is not None else 0.0, str(row.get("name")))


def compute_req_signals(store, project_id: str, ir: Mapping[str, Any]) -> dict:
    """요구를 IR 과 대조해 `sig:req.margin`·`req.scenario_coverage`·`req.standards` 와 결측 2종을 만든다.

    plan §3.2.3 표. 결과는 rr_state 에만 살고 rr_ir 에는 들어가지 않는다 — 요구를 고쳐도 `ir_hash` 는 그대로다.
    반환은 `{'signals': {...}, 'missing': {'req_absent': bool, 'scenario_uncovered': bool}}` 이고,
    state.py 는 signals 를 자기 signals 에 합치고 missing 2종을 rr_state 의 missing 에 더한다.
    """
    rows = _rows(
        store,
        f"SELECT {_COLUMNS} FROM rr_requirements WHERE project_id = ? ORDER BY kind, name", (project_id,))
    active = [r for r in rows if r["status"] in _ACTIVE_STATUSES]
    dims = {str(d.get("name")): d for d in (ir.get("dims_named") or [])}

    margin_rows = []
    for row in (r for r in active if r["kind"] == "dim_limit"):
        name = row["name"]
        limit = _loads(row["value_json"])
        dim = dims.get(name)
        actual = dim.get("value") if dim else None
        unit_ok = dim is None or not dim.get("unit") or not row["unit"] or str(dim["unit"]) == str(row["unit"])
        known = _num(actual) and unit_ok
        margin, rel = _margin(row["op"], limit, float(actual)) if known else (None, None)
        margin_rows.append({
            "name": name, "op": row["op"], "limit": limit, "unit": row["unit"],
            "actual": actual if known else None, "margin": margin, "rel": rel,
            "known": bool(known), "status": row["status"],
        })
    margin_rows.sort(key=_margin_sort_key)
    margin_text = " · ".join(_margin_line(r) for r in margin_rows) or EXPERIENCE_BASIS_TEXT
    margin_refs = [f"req:{r['name']}" for r in margin_rows] + [f"d:{r['name']}" for r in margin_rows if r["name"] in dims]

    coverage = _scenario_coverage([r for r in active if r["kind"] == "scenario"], ir)
    standards = []
    for row in (r for r in active if r["kind"] == "standard"):
        value = _loads(row["value_json"])
        value = value if isinstance(value, Mapping) else {}
        standards.append({"name": row["name"], "clause": value.get("clause"), "title": value.get("title"),
                          "source_ref": row["source_ref"]})

    signals = {
        "req.margin": _rec("table", margin_rows, None, margin_refs, margin_text, known=bool(margin_rows)),
        "req.scenario_coverage": _rec(
            "table", coverage["value"], None, coverage["refs"], coverage["text"]),
        "req.standards": _rec(
            "table", standards, None, [f"req:{s['name']}" for s in standards],
            " · ".join(f"req:{s['name']} «{s['title'] or ''}» {s['source_ref'] or ''}".strip() for s in standards)
            or "규격 요구 없음", known=bool(standards)),
    }
    return {
        "signals": signals,
        "missing": {"req_absent": not rows, "scenario_uncovered": bool(coverage["value"]["uncovered"])},
    }


def _scenario_map() -> Mapping[str, Any]:
    """taxonomy 자산의 scenario_map(있으면). 없으면 taxonomy_key 를 결과 kind 로 그대로 읽는다."""
    try:
        from app import taxonomy

        mapping = taxonomy.load_taxonomy().get("scenario_map")
    except Exception:       # 자산이 없거나 깨져도 대조는 계속한다(항등 사상으로 내려간다).
        return {}
    return mapping if isinstance(mapping, Mapping) else {}


def _scenario_coverage(rows: Sequence[Mapping[str, Any]], ir: Mapping[str, Any]) -> dict:
    """필수 시나리오와 rr_ir.results 의 대조(plan §2.8b·§3.2.3). results 가 없으면 covered_n=0 이고 known 은 true 다."""
    results = ir.get("results") or {}
    result_kinds = {str(results.get("kind"))} if results.get("kind") else set()
    report_ids = list(results.get("report_ids") or [])
    mapping = _scenario_map()

    required, covered, uncovered = 0, 0, []
    for row in rows:
        value = _loads(row["value_json"]) or {}
        value = value if isinstance(value, Mapping) else {}
        # required 미기재는 요구로 본다 — 시나리오 요구를 등록한 사실 자체가 '필요하다' 는 선언이다.
        if value.get("required", True) is not True:
            continue
        required += 1
        key = str(value.get("taxonomy_key") or "")
        mapped = mapping.get(key, key)
        mapped_kinds = {str(m) for m in mapped} if isinstance(mapped, (list, tuple)) else {str(mapped)}
        if mapped_kinds & result_kinds:
            covered += 1
        else:
            uncovered.append({"name": row["name"], "taxonomy_key": key or None})
    value = {"required_n": required, "covered_n": covered, "uncovered": uncovered}
    refs = [f"req:{u['name']}" for u in uncovered] + [f"dyna:rpt:{rid}" for rid in report_ids]
    text = (f"필수 시나리오 {required}건 중 {covered}건 대응"
            + (f" · 미커버 {', '.join(u['name'] for u in uncovered)}" if uncovered else ""))
    return {"value": value, "refs": refs, "text": text if required else "필수 시나리오 없음"}


def judgement_basis(store, project_id: str) -> dict:
    """판정 기준이 요구인지 좌석 경험인지 — 요구 0건이면 브리프 E0·좌석 발언에 실릴 문장을 준다(plan §6.5.3)."""
    rows = store.query(
        "SELECT kind, COUNT(*) AS n FROM rr_requirements WHERE project_id = ? GROUP BY kind", (project_id,))
    by_kind = {r["kind"]: int(r["n"]) for r in rows}
    total = sum(by_kind.values())
    if not total:
        return {"req_absent": True, "basis": "experience", "by_kind": {}, "text": EXPERIENCE_BASIS_TEXT}
    detail = " · ".join(f"{k} {by_kind[k]}" for k in KINDS if by_kind.get(k))
    return {"req_absent": False, "basis": "requirement", "by_kind": by_kind,
            "text": f"요구 {total}건 등록({detail}) — 판정은 요구 한계 기준"}


# ---------------------------------------------------------------- finding 의 requirement_ref
def requirement_ref(name: str) -> str:
    """`req:<name>` 정규 표기."""
    return f"{REQ_PREFIX}{name}"


def parse_requirement_ref(text: Any) -> str | None:
    """`req:<name>`(대괄호 있어도 된다)에서 이름만 뽑는다. 요구 참조가 아니면 None 이다."""
    if not isinstance(text, str):
        return None
    s = text.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()
    if not s.startswith(REQ_PREFIX):
        return None
    name = s[len(REQ_PREFIX):].strip()
    return name or None


def requirement_index(store, project_id: str) -> dict[str, dict]:
    """이름 → 요구 행. 같은 이름이 여러 kind 에 있으면 dim_limit·scenario·standard 순으로 앞이 이긴다."""
    rows = _rows(
        store, f"SELECT {_COLUMNS} FROM rr_requirements WHERE project_id = ? ORDER BY kind, name", (project_id,))
    index: dict[str, dict] = {}
    for kind in KINDS:
        for row in rows:
            if row["kind"] == kind and row["name"] not in index:
                index[row["name"]] = {**row, "value": _loads(row["value_json"])}
    return index


def margins_by_name(margin_rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """`sig:req.margin` 의 표를 이름 → margin(미측정은 None) 사전으로 접는다."""
    return {str(r.get("name")): r.get("margin") for r in margin_rows or ()}


def check_finding_requirement(finding: MutableMapping[str, Any], *, by_name: Mapping[str, Mapping[str, Any]],
                              margins: Mapping[str, Any] | None = None) -> list[str]:
    """finding 의 `req:` 인용을 검증해 `requirement_ref` 를 세우고 판정을 보정한다(plan §2.8b (5)·P1 통과 기준 20).

    (1) `requirement_ref` 가 없으면 cites 에서 첫 `req:` 를 끌어온다. (2) 그 이름이 이 과제에 없으면
    `finding['dangling']` 에 그 참조를 더한다 — 등급은 dangling 을 빼고 세는 기존 계산이 알아서 내린다.
    (3) 여유가 0 이하인 요구를 가리키면서 `judgement='OK'` 인 finding 은 `undetermined` 로 보정한다.
    반환은 parse_warnings 에 붙일 문장 목록이다(빈 목록이면 보정 없음).
    """
    margins = margins or {}
    warnings: list[str] = []
    ref = finding.get("requirement_ref")
    name = parse_requirement_ref(ref)
    if name is None:
        for cite in finding.get("cites") or ():
            text = cite.get("ref") if isinstance(cite, Mapping) else cite
            name = parse_requirement_ref(text)
            if name:
                break
    if name is None:
        finding["requirement_ref"] = None
        return warnings

    finding["requirement_ref"] = requirement_ref(name)
    if name not in by_name:
        dangling = list(finding.get("dangling") or ())
        if finding["requirement_ref"] not in dangling:
            dangling.append(finding["requirement_ref"])
        finding["dangling"] = dangling
        warnings.append(f"{finding['requirement_ref']} 는 이 과제에 등록된 요구가 아니다(dangling).")
        return warnings

    margin = margins.get(name)
    if _num(margin) and float(margin) <= 0 and finding.get("judgement") == "OK":
        finding["judgement"] = "undetermined"
        warnings.append(
            f"{finding['requirement_ref']} 의 여유가 {margin} 인데 judgement=OK 라 undetermined 로 보정했다.")
    return warnings
