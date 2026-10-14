# 검토 단위의 실호출 근거(B 층) — 캡처에 없던 지금 상태(해석 보고서 비교 · 재질 물성 비교)를 사용자 PAT 로 불러 단위마다 한 번 얼린다
"""근거 꾸러미 B 층(재설계 M3 C3-12 · spec-wp2 3.8 · W2-03 · W2-04).

A 층(`units.evidence_lines` — 스냅샷 IR 동결본 발췌)은 네트워크를 쓰지 않는다. B 층은 캡처에 없던 도구 둘만 결정적 인자로
게이트웨이 MCP 에 묻는다 — ① 두 스냅샷 IR 의 `results.report_ids` 가 다 있으면 `compare_reports(report_ids=[전, 후])` 한 번(각
쪽의 첫 보고서 — `rr_targets.report_ids_json` 은 쓰지 않는다, W2-03 (a)) → 결과 변화 줄(`result_delta` · `result.*`)이 있는 단위에
붙인다. ② 단위 부품의 재질 (전, 후) 쌍마다 `compare_materials(materials=[전, 후])` 한 번(타깃 안에서 같은 쌍은 한 번 — `get_material`
폴백은 없다, W2-03 (b)) → 그 쌍이 든 단위에 붙인다. LLM 이 인자를 짜지 않는다.

규칙.
- 인자 키는 게이트웨이 `tools/list` 의 inputSchema 와 대조한다 — 모르는 키·빠진 필수 키면 계획에서 빼고 `live_schema_mismatch` 로
  적는다(W2-03 (c)). 도구가 사용자 PAT 시야의 목록에 아예 없으면 부르지 않고 `live_denied` 다(#55 — 반대 검토 LOW 20).
- 자격은 그 잡의 사용자 PAT 하나다(사용자 결정 3 — 서비스 계정으로 내려가지 않는다). 401 은 잡의 credential 보류(`CredentialRejected`).
- 실패를 둘로 가른다(W2-04 (c)) — 내용 탓(오류 본문 `error` 키 · 스키마 · 403 · 도구 오류)은 그 호출만 빠진 채 `partial` 로 얼린다.
  인프라 탓(연결 · 5xx · 기한)은 얼리지 않고 `attempts + 1` · `not_before`(60초부터 두 배)로 다시 하고, 여섯 번째에 그 호출을
  `live_infra_exhausted` 로 적어 `partial` 로 얼린다.
- 쓰기는 비교 후 쓰기다(`… WHERE status IS NULL` — 바뀐 행 0 이면 버린다, W2-04 (a)). 두 ensure 가 겹쳐도 단위마다 한 번만 언다.
- 셀이 하나라도 이미 시작된(`input_hash` 가 있는) 단위는 `skipped` 로 얼린다 — M2 파일럿 대상의 셀 지문이 바뀌어 처음부터 도는 것을
  막는다. 손잡이(HWAXRISK_EVIDENCE_LIVE)가 0 이면 전 단위 `none` 이고 호출은 0 이다.
- 응답 원문은 붓지 않는다 — 수치 · id 칸만 줄로 만들고 문자열은 `render.sanitize_source_text(…, limit=0)` 로 «» 안에 둔다. 모르는
  모양(글 · 목록 밖 값)은 줄마다 «…». 원문은 `rr_brief_calls` 에 남는다(`field_source.LiveSource` — 인용 `tool:b-…` 의 해석 원장).
- 단위의 셀은 그 단위의 `status` 가 서기 전에는 시작하지 않는다(`READY_SQL` — 행이 없는 단위는 B 층 이전 원장이라 막지 않는다).
"""
from __future__ import annotations

import gzip
import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app import brief, config, field_source, render, units
from app.common import canonical_json, now_epoch, sha256_hex

log = logging.getLogger("hwax_risk.unit_live")

TOOLS: tuple[str, ...] = ("compare_reports", "compare_materials")
STATUSES: tuple[str, ...] = ("ok", "partial", "none", "skipped")
RETRY_BASE_S = 60                  # 인프라 실패 뒤 다시 하기까지 — 60초부터 두 배
RETRY_MAX = 6                      # 인프라 실패 여섯 번째에 얼린다(live_infra_exhausted)
CALL_DEADLINE_S = 300              # 호출 하나의 벽시계 기한(spec-wp2 HWAXRISK_EVIDENCE_CALL_DEADLINE_S 의 기본값)
ENSURE_DEADLINE_S = 1800           # 루프의 ensure 한 번이 쓰는 기한 — 넘긴 호출은 인프라(기한)로 다시 한다
CREDENTIAL_KIND = "user"
# 못 받은 호출의 까닭(rr_unit_live.gaps_json — 셀 오류가 아니다)
INFRA_EXHAUSTED = "live_infra_exhausted"
SCHEMA_MISMATCH = "live_schema_mismatch"
ERROR_BODY = "live_error_body"
DENIED = "live_denied"
INTERNAL_ERROR = "live_internal_error"      # 근거 꾸러미 워커의 예상 밖 결함이 여섯 번 — 그 단위를 얼린다(반대 검토 HIGH 4)
GAP_CODES: tuple[str, ...] = (INFRA_EXHAUSTED, SCHEMA_MISMATCH, ERROR_BODY, DENIED, INTERNAL_ERROR)
LIVE_HEAD = "실호출 근거(tool:b-…)는 지금 상태다 — 스냅샷 뒤에 바뀌었을 수 있다"
# 폐기된 과제의 행은 쓰지 않는다(반대 검토 MEDIUM 14) — 폐기가 비운 근거 줄 · 호출 계획(재질명이 든다)을 늦게 끝난 ensure 가 다시
# 채우지 않게. 쓰기 문장 하나에 조건으로 붙어 폐기의 트랜잭션과 엇갈리지 않는다.
NOT_PURGED_SQL = (" AND NOT EXISTS (SELECT 1 FROM rr_targets t JOIN rr_projects p ON p.id = t.project_id"
                  " WHERE t.target_key = rr_unit_live.target_key AND p.status = 'purged')")
# 셀을 시작해도 되는 단위 — 행이 없거나(B 층 이전 원장) 얼었다. `c` 는 rr_review_cells 의 별칭이다.
READY_SQL = (" AND NOT EXISTS (SELECT 1 FROM rr_unit_live l WHERE l.target_key = c.target_key AND l.unit_id = c.unit_id"
             " AND l.status IS NULL)")


class CredentialRejected(Exception):
    """게이트웨이가 사용자 PAT 를 401 로 거절했다 — 잡을 credential 로 멈춘다(서비스 계정으로 내려가지 않는다)."""


def enabled(settings: Any = None) -> bool:
    cfg = config.settings if settings is None else settings
    return bool(getattr(cfg, "risk_evidence_live", True))


# ---------------------------------------------------------------- 행
def seed(store: Any, target_key: str, *, enabled: bool, now: int | None = None) -> int:
    """활성 빌드의 검토 대상 단위마다 행을 둔다(INSERT OR IGNORE — 이미 있는 행은 그대로). 손잡이가 꺼져 있으면 곧바로 `none` 으로
    언다(호출 0). 새로 둔 행 수."""
    now = now_epoch() if now is None else now
    owner = store.query_one("SELECT owner_sub FROM rr_targets WHERE target_key = ?", (target_key,))
    if owner is None:
        return 0
    status, frozen = (None, None) if enabled else ("none", now)
    made = 0
    for unit in units.load_units(store, target_key, reviewable_only=True):
        made += int(store.execute(
            "INSERT OR IGNORE INTO rr_unit_live(target_key, unit_id, owner_sub, status, plan_json, frozen_at, created_at,"
            " updated_at) VALUES (?, ?, ?, ?, '[]', ?, ?, ?)",
            (target_key, unit["unit_id"], owner["owner_sub"], status, frozen, now, now)) or 0)
    return made


def pending(store: Any, target_key: str, *, now: int | None = None, due_only: bool = False) -> list[str]:
    """아직 얼지 않은 단위(status NULL). `due_only` 면 백오프(not_before)가 지난 것만."""
    sql = "SELECT unit_id FROM rr_unit_live WHERE target_key = ? AND status IS NULL"
    args: list[Any] = [target_key]
    if due_only:
        sql += " AND (not_before IS NULL OR not_before <= ?)"
        args.append(now_epoch() if now is None else now)
    return [str(r["unit_id"]) for r in store.query(sql + " ORDER BY unit_id", tuple(args))]


def lines_for(store: Any, target_key: str, unit_id: str) -> dict | None:
    """그 단위의 얼린 B 층 — {status, lines[{ref, text}], gaps[{tool, code, note}], sha, chars} 또는 None(행이 없거나 아직)."""
    row = store.query_one("SELECT status, lines_gz, gaps_json, live_sha, live_chars FROM rr_unit_live"
                          " WHERE target_key = ? AND unit_id = ?", (target_key, unit_id))
    if row is None or row["status"] is None:
        return None
    lines = _ungz(row["lines_gz"])
    gaps = _loads(row["gaps_json"], [])
    return {"status": row["status"], "lines": lines if isinstance(lines, list) else [],
            "gaps": gaps if isinstance(gaps, list) else [], "sha": row["live_sha"], "chars": row["live_chars"]}


def notes_of(live: Mapping[str, Any] | None) -> str:
    """단위 payload 의 notes 에 덧붙일 글 — 실은 줄이 있으면 '지금 상태' 머리, 못 받은 호출은 `[실호출 조회 불가: 도구 — 까닭]`."""
    if not live:
        return ""
    out = [LIVE_HEAD] if live.get("lines") else []
    out += [f"[실호출 조회 불가: {g.get('tool')} — {g.get('code')}]" for g in live.get("gaps") or () if isinstance(g, Mapping)]
    return " ".join(out)


def refs_of(store: Any, target_key: str, unit_id: str) -> set[str]:
    """그 단위의 B 층 줄 참조(`tool:b-…`) — 판정이 인용할 수 있는 참조에 더한다(Q8)."""
    live = lines_for(store, target_key, unit_id)
    return {str(line["ref"]) for line in (live or {}).get("lines") or () if isinstance(line, Mapping) and line.get("ref")}


def call_ids(store: Any, target_key: str) -> set[str]:
    """그 대상의 얼린 B 층이 받은 호출 id(`b-…`) — 인용 검증 스코프(`narrative.review_scope`)가 call_ids 에 더한다(P-07)."""
    out: set[str] = set()
    for row in store.query("SELECT plan_json FROM rr_unit_live WHERE target_key = ? AND status IS NOT NULL", (target_key,)):
        for item in _loads(row["plan_json"], []):
            if isinstance(item, Mapping) and item.get("state") == "ok" and item.get("call_id"):
                out.add(str(item["call_id"]))
    return out


def counts(store: Any, target_key: str) -> dict:
    """상태별 단위 수 {ok, partial, none, skipped, pending} — 성공률과 못 받은 까닭은 재기만 한다(a-10)."""
    out = {s: 0 for s in (*STATUSES, "pending")}
    for row in store.query("SELECT status, COUNT(*) AS n FROM rr_unit_live WHERE target_key = ? GROUP BY status",
                           (target_key,)):
        out[row["status"] if row["status"] in STATUSES else "pending"] += int(row["n"])
    return out


# ---------------------------------------------------------------- 계획(결정적)
def plan_calls(store: Any, target_key: str) -> dict:
    """대상 하나의 호출 계획 — {calls{call_key: {tool, args}}, by_unit{unit_id: [call_key…]}, pids{unit_id: [pid…]}}.

    call_key 는 `tool|정규 인자` 다. 같은 쌍은 타깃 안에서 한 번이다. 계획은 원장(diff · 두 스냅샷 IR · 단위)만 읽는다."""
    row = store.query_one(
        "SELECT d.base_snapshot_id, d.target_snapshot_id, d.diff_json FROM rr_targets t JOIN rr_diffs d ON d.id = t.ref_id"
        " WHERE t.target_key = ? AND t.kind = 'diff'", (target_key,))
    out: dict[str, Any] = {"calls": {}, "by_unit": {}, "pids": {}}
    if row is None:
        return out
    diff_obj = _loads(row["diff_json"], {})
    base_ir, target_ir = _ir(store, row["base_snapshot_id"]), _ir(store, row["target_snapshot_id"])
    reports = [_first(((ir or {}).get("results") or {}).get("report_ids")) for ir in (base_ir, target_ir)]
    result_refs = _result_refs(diff_obj)
    pid_of = _pid_index(base_ir, target_ir)
    for unit in units.load_units(store, target_key, reviewable_only=True):
        keys: list[str] = []
        if None not in reports and str(reports[0]) != str(reports[1]) and result_refs & set(unit.get("cids") or ()):
            keys.append(_add(out, "compare_reports", {"report_ids": list(reports)}))
            nids = {str(n) for p in unit.get("parts") or () for side in ("nids_base", "nids_target") for n in p.get(side) or ()}
            out["pids"][unit["unit_id"]] = sorted({pid for nid, pids in pid_of.items() if nid in nids for pid in pids})
        for part in unit.get("parts") or ():
            before, after = part.get("material_before"), part.get("material_after")
            if before and after and str(before) != str(after):
                keys.append(_add(out, "compare_materials", {"materials": [str(before), str(after)]}))
        if keys:
            out["by_unit"][unit["unit_id"]] = list(dict.fromkeys(keys))
    return out


def _add(out: dict, tool: str, args: Mapping[str, Any]) -> str:
    key = f"{tool}|{canonical_json(dict(args))}"
    out["calls"].setdefault(key, {"tool": tool, "args": dict(args)})
    return key


def _first(value: Any) -> Any:
    items = value if isinstance(value, list) else []
    return items[0] if items and items[0] not in (None, "") else None


def _ir(store: Any, snapshot_id: str | None) -> dict | None:
    if not snapshot_id:
        return None
    row = store.query_one("SELECT ir_json FROM rr_snapshots WHERE id = ?", (snapshot_id,))
    value = _loads(row["ir_json"], None) if row is not None else None
    return value if isinstance(value, dict) else None


def _result_refs(diff_obj: Mapping[str, Any]) -> set[str]:
    """결과 변화 줄의 참조 — `parametric.result_delta`(값이 같은 표지 행은 뺀다)와 의미 이벤트 `result.*`."""
    parametric = diff_obj.get("parametric") if isinstance(diff_obj.get("parametric"), Mapping) else {}
    semantic = diff_obj.get("semantic") if isinstance(diff_obj.get("semantic"), Mapping) else {}
    refs = {str(r["cid"]) for r in parametric.get("result_delta") or () if isinstance(r, Mapping) and r.get("cid")
            and not units._non_change(r)}
    refs |= {str(r["cid"]) for r in semantic.get("events") or () if isinstance(r, Mapping) and r.get("cid")
             and str(r.get("code") or "").startswith("result.")}
    return refs


def _pid_index(*irs: Mapping[str, Any] | None) -> dict[str, set[str]]:
    """nid → 해석 보고서의 pid 들(두 IR 의 results.parts_map — pid → nid)."""
    out: dict[str, set[str]] = {}
    for ir in irs:
        parts_map = ((ir or {}).get("results") or {}).get("parts_map") or {}
        if isinstance(parts_map, Mapping):
            for pid, nid in parts_map.items():
                out.setdefault(str(nid), set()).add(str(pid))
    return out


# ---------------------------------------------------------------- 스키마 대조
def schema_gap(tool: str, args: Mapping[str, Any], schemas: Mapping[str, Mapping[str, Any]],
               names: Sequence[str]) -> tuple[str, str] | None:
    """부를 수 없으면 (까닭 코드, 글), 맞으면 None — 도구가 사용자 PAT 시야에 없음(live_denied — #55) · 모르는 키 · 빠진 필수 키
    (live_schema_mismatch)."""
    real = field_source._real_name(tool, names)
    if real not in schemas:
        return DENIED, f"게이트웨이에 {tool} 이 없다(사용자 PAT 시야)"
    schema = schemas[real] if isinstance(schemas[real], Mapping) else {}
    props = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else None
    if props is not None:
        unknown = sorted(set(args) - set(props))
        if unknown:
            return SCHEMA_MISMATCH, f"모르는 인자 {unknown}"
    missing = sorted(set(schema.get("required") or ()) - set(args))
    return (SCHEMA_MISMATCH, f"빠진 필수 인자 {missing}") if missing else None


# ---------------------------------------------------------------- 응답 → 줄
def render_lines(tool: str, args: Mapping[str, Any], result: Any, *, pids: Sequence[str] | None = None,
                 on_suspect: Callable[[dict], None] | None = None) -> list[str]:
    """응답 하나 → 줄 글들. 머리 한 줄(도구와 인자) 뒤에 행마다 한 줄 — 수치 · id 칸은 그대로, 문자열은 «위생 통과본»(자르지 않는다 —
    주입 어휘는 자리표시자이고 `on_suspect` 가 걸린 원문을 받는다). `compare_reports` 는 그 단위 부품의 pid 행만 싣는다(pid 가 없는
    행은 싣는다 — 단위에 pid 가 하나도 없으면 전부)."""
    note = on_suspect
    head = f"{tool}(" + ", ".join(f"{k}={_value(v, note)}" for k, v in sorted(args.items())) + ")"
    rows = _rows(result, note)
    if rows is None:
        text = result if isinstance(result, str) else canonical_json(result)
        return [head] + [_q(line, note) for line in str(text).splitlines() if line.strip()]
    keep = set(pids or ())
    lines = [head]
    for label, row in rows:
        if tool == "compare_reports" and keep and isinstance(row, Mapping):
            pid = row.get("part_id", row.get("pid"))
            if pid is not None and str(pid) not in keep:
                continue
        body = _flat(row, note=note)
        if body:
            lines.append(f"{label}: {body}" if label else body)
    return lines


def _rows(result: Any, note: Callable[[dict], None] | None = None) -> list[tuple[str, Any]] | None:
    """행 목록 — 목록이면 항목마다, 객체면 목록 칸의 항목마다(칸 이름이 머리) + 나머지 칸 한 줄. 그 밖(글 · 수)은 None."""
    if isinstance(result, list):
        return [("", item) for item in result]
    if not isinstance(result, Mapping):
        return None
    rows: list[tuple[str, Any]] = []
    scalars = {}
    for key in sorted(result):
        value = result[key]
        if isinstance(value, list) and any(isinstance(v, Mapping) for v in value):
            rows += [(_safe_key(key, note), item) for item in value]
        elif isinstance(value, Mapping) and value and all(isinstance(v, Mapping) for v in value.values()):
            rows += [(f"{_safe_key(key, note)}.{_safe_key(k, note)}", value[k]) for k in sorted(value)]
        else:
            scalars[key] = value
    if scalars:
        rows.insert(0, ("", scalars))
    return rows


def _flat(value: Any, prefix: str = "", *, note: Callable[[dict], None] | None = None) -> str:
    """객체 하나 → `칸=값` 을 ' · ' 로. 수 · 참거짓은 그대로, id 칸과 문자열은 «» 안, 빈 값은 뺀다."""
    if not isinstance(value, Mapping):
        return _value(value, note)
    parts: list[str] = []
    for key in sorted(value):
        item = value[key]
        name = f"{prefix}{_safe_key(key, note)}"
        if isinstance(item, Mapping):
            inner = _flat(item, f"{name}.", note=note)
            if inner:
                parts.append(inner)
        elif item is None or item == "" or item == []:
            continue
        else:
            parts.append(f"{name}={_value(item, note)}")
    return " · ".join(parts)


def _value(value: Any, note: Callable[[dict], None] | None = None) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(v, note) for v in value) + "]"
    if isinstance(value, Mapping):
        return "{" + _flat(value, note=note) + "}"
    return _q(value, note)


def _safe_key(key: Any, note: Callable[[dict], None] | None = None) -> str:
    text = str(key)
    return (text if text.replace("_", "").replace("-", "").isalnum() and text.isascii() and len(text) <= 40
            else _q(text, note))


def _q(text: Any, note: Callable[[dict], None] | None = None) -> str:
    return render.sanitize_source_text(text, "label", limit=0, on_suspect=note)


# ---------------------------------------------------------------- 얼리기
def ensure(store: Any, settings: Any, target_key: str, credential: Mapping[str, Any] | None, *,
           deadline_s: float = ENSURE_DEADLINE_S, http_client: Any = None, now: int | None = None,
           stop: Callable[[], str | None] | None = None, clock: Callable[[], int] | None = None) -> dict:
    """백오프가 지난 미동결 단위를 얼린다 — {frozen{status: n}, retry, calls, cached} · 멈췄으면 aborted(까닭).

    `credential` 은 {kind:'user', email, pat} — 그 잡의 사용자 PAT 다(없으면 호출 없이 credential 로 올린다). 손잡이가 꺼져 있으면
    남은 단위를 `none` 으로, 셀이 이미 시작된 단위는 `skipped` 로, 부를 것이 없는 단위는 `ok`(줄 없음)로 언다. 시작 · 호출마다 앞 ·
    얼리기 앞에서 `stop`(잡의 취소 · 사람의 정지 · 앱 종료 — 까닭 글)과 과제 폐기를 보고, 걸리면 더 부르지 않고 아무것도 얼리지 않는다
    (반대 검토 MEDIUM 14 — 다음 잡이 다시 하고, 이미 받은 답은 원장에서 다시 쓴다). `now` 는 시작 시각(백오프가 지났나 · 다음 시도
    시각)이고, 얼린 행의 frozen_at · updated_at 은 적는 순간의 `clock()` 이다 — 호출이 길어도 since 반출이 그 행을 놓치지 않게
    (반대 검토 LOW 19). `clock` 이 없으면 준 `now`(없으면 지금)다."""
    if clock is None:
        clock = now_epoch if now is None else (lambda: now)
    now = now_epoch() if now is None else now
    out: dict[str, Any] = {"frozen": {}, "retry": 0, "calls": 0, "cached": 0}
    due = pending(store, target_key, now=now, due_only=True)
    if not due:
        return out
    if halted := _halted(store, target_key, stop):
        out["aborted"] = halted
        return out
    if not enabled(settings):
        for unit_id in due:
            _freeze(store, target_key, unit_id, "none", out, now=clock())
        return out
    started = {str(r["unit_id"]) for r in store.query(
        "SELECT DISTINCT unit_id FROM rr_review_cells WHERE target_key = ? AND input_hash IS NOT NULL", (target_key,))}
    plan = plan_calls(store, target_key)
    work: list[str] = []
    for unit_id in due:
        if unit_id in started:
            _freeze(store, target_key, unit_id, "skipped", out, now=clock())
        elif not plan["by_unit"].get(unit_id):
            _freeze(store, target_key, unit_id, "ok", out, now=clock())
        else:
            work.append(unit_id)
    if not work:
        return out
    pat = str((credential or {}).get("pat") or "")
    if not pat:
        raise CredentialRejected("근거 꾸러미 실호출의 사용자 PAT 가 없다")
    cfg = config.settings if settings is None else settings
    until = time.monotonic() + max(1.0, float(deadline_s))
    from app.ra_client import McpHttpClient  # noqa: PLC0415 — 순환 import 회피(field_source 와 같은 규칙).

    mcp = McpHttpClient(getattr(cfg, "gateway_mcp", ""), headers={"Authorization": f"Bearer {pat}"}, client=http_client,
                        timeout=float(getattr(cfg, "risk_field_timeout_s", config.DEFAULT_FIELD_TIMEOUT_S)),
                        deadline_s=CALL_DEADLINE_S)
    try:
        if halted := _halted(store, target_key, stop):
            out["aborted"] = halted
            return out
        listed = mcp.list_tools(deadline=min(until, time.monotonic() + CALL_DEADLINE_S))
        outcomes: dict[str, dict] = {}
        if not listed["ok"]:
            kind = _classify(listed)
            if kind == "credential":
                raise CredentialRejected(f"게이트웨이가 사용자 PAT 를 거절했다({listed.get('error')})")
            outcomes = {key: {"state": kind, "code": _gap_code(listed, kind), "note": str(listed.get("error") or "")}
                        for uid in work for key in plan["by_unit"][uid]}
        else:
            tools = [t for t in listed["result"] if isinstance(t, Mapping) and t.get("name")]
            schemas = {str(t["name"]): t.get("inputSchema") or {} for t in tools}
            names = tuple(schemas)
            source = field_source.LiveSource(mcp, credential_kind=CREDENTIAL_KIND, tool_names=names)
            owner = store.query_one("SELECT owner_sub FROM rr_targets WHERE target_key = ?", (target_key,))["owner_sub"]
            for key in dict.fromkeys(k for uid in work for k in plan["by_unit"][uid]):
                call = plan["calls"][key]
                gap = schema_gap(call["tool"], call["args"], schemas, names)
                if gap is not None:
                    outcomes[key] = {"state": "content", "code": gap[0], "note": gap[1]}
                    continue
                if halted := _halted(store, target_key, stop):
                    out["aborted"] = halted
                    return out
                if time.monotonic() >= until:
                    outcomes[key] = {"state": "infra", "code": INFRA_EXHAUSTED, "note": "deadline_exceeded"}
                    continue
                reply = source.fetch_live(store, target_key, owner, call["tool"], call["args"],
                                          deadline=min(until, time.monotonic() + CALL_DEADLINE_S))
                out["calls"] += int(not reply["cached"])
                out["cached"] += int(reply["cached"])
                if reply["ok"]:
                    outcomes[key] = {"state": "ok", "call_id": reply["call_id"], "result": reply["result"]}
                    continue
                kind = _classify(reply)
                if kind == "credential":
                    raise CredentialRejected(f"게이트웨이가 사용자 PAT 를 거절했다({reply.get('error')})")
                outcomes[key] = {"state": kind, "code": _gap_code(reply, kind), "note": str(reply.get("error") or ""),
                                 "call_id": reply["call_id"]}
    finally:
        mcp.close()
    if halted := _halted(store, target_key, stop):                 # 마지막 호출 도중에 멈췄다
        out["aborted"] = halted
        return out
    email = (credential or {}).get("email")
    at = clock()
    for unit_id in work:
        _settle(store, target_key, unit_id, plan, outcomes, out, email=email, now=now, at=at)
    return out


def _halted(store: Any, target_key: str, stop: Callable[[], str | None] | None) -> str | None:
    """멈출 까닭 — `stop` 의 답(잡의 취소 · 사람의 정지 · 앱 종료)이나 과제 폐기. 없으면 None."""
    why = stop() if stop is not None else None
    if why:
        return why
    row = store.query_one("SELECT p.status FROM rr_targets t JOIN rr_projects p ON p.id = t.project_id WHERE t.target_key = ?",
                          (target_key,))
    return "과제가 폐기됐다" if row is not None and row["status"] == "purged" else None


def note_failure(store: Any, target_key: str, *, note: str, now: int | None = None) -> dict:
    """ensure 가 예상 밖 결함으로 빠져나갔다 — 백오프가 지난 미동결 단위마다 attempts + 1 · not_before(60초부터 두 배)로 미루고, 여섯
    번째에 live_internal_error 로 partial 로 언다(틱마다 다시 부르며 단위를 영영 미동결로 두지 않는다). {retry, frozen}."""
    now = now_epoch() if now is None else now
    out: dict[str, Any] = {"frozen": {}, "retry": 0}
    for unit_id in pending(store, target_key, now=now, due_only=True):
        row = store.query_one("SELECT attempts FROM rr_unit_live WHERE target_key = ? AND unit_id = ? AND status IS NULL",
                              (target_key, unit_id))
        if row is None:
            continue
        attempts = int(row["attempts"] or 0)
        if attempts + 1 < RETRY_MAX:
            out["retry"] += int(bool(store.execute(
                "UPDATE rr_unit_live SET attempts = attempts + 1, not_before = ?, updated_at = ?"
                " WHERE target_key = ? AND unit_id = ? AND status IS NULL AND attempts = ?",
                (now + RETRY_BASE_S * 2 ** attempts, now, target_key, unit_id, attempts))))
        else:
            _freeze(store, target_key, unit_id, "partial", out, now=now,
                    gaps=[{"tool": "*", "code": INTERNAL_ERROR, "note": note}], attempts=attempts + 1)
    return out


def _classify(reply: Mapping[str, Any]) -> str:
    """실패한 답 → infra · credential · content. 연결 · 기한 · 5xx 는 인프라, 401 은 자격, 그 밖(403 · 4xx · 오류 본문 · 도구 오류 ·
    읽을 수 없는 답)은 내용 탓이다."""
    error = str(reply.get("error") or "")
    status = reply.get("status")
    if error in ("transport_error", "deadline_exceeded"):
        return "infra"
    if isinstance(status, int) and status >= 500:
        return "infra"
    if status == 401:
        return "credential"
    return "content"


def _gap_code(reply: Mapping[str, Any], kind: str) -> str:
    if kind == "infra":
        return INFRA_EXHAUSTED
    return DENIED if reply.get("status") == 403 else ERROR_BODY


def _settle(store: Any, target_key: str, unit_id: str, plan: Mapping[str, Any], outcomes: Mapping[str, dict],
            out: dict, *, email: str | None, now: int, at: int) -> None:
    """호출 결과로 그 단위를 얼리거나(내용 탓 · 성공 · 여섯 번째 인프라) 다시 하기로 미룬다. `now` 는 ensure 의 시작 시각(다음
    시도 not_before 의 기준), `at` 은 적는 시각(frozen_at · updated_at)이다."""
    keys = plan["by_unit"][unit_id]
    row = store.query_one("SELECT attempts FROM rr_unit_live WHERE target_key = ? AND unit_id = ? AND status IS NULL",
                          (target_key, unit_id))
    if row is None:
        return                                           # 다른 ensure 가 먼저 얼렸다
    attempts = int(row["attempts"] or 0)
    entries = [{"tool": plan["calls"][k]["tool"], "args": plan["calls"][k]["args"],
                "call_id": outcomes.get(k, {}).get("call_id"), "state": outcomes.get(k, {}).get("state", "infra"),
                "code": outcomes.get(k, {}).get("code")} for k in keys]
    infra = [e for e in entries if e["state"] == "infra"]
    if infra and attempts + 1 < RETRY_MAX:
        changed = store.execute(
            "UPDATE rr_unit_live SET attempts = attempts + 1, not_before = ?, plan_json = ?, updated_at = ?"
            " WHERE target_key = ? AND unit_id = ? AND status IS NULL AND attempts = ?" + NOT_PURGED_SQL,
            (now + RETRY_BASE_S * 2 ** attempts, canonical_json(entries), at, target_key, unit_id, attempts))
        out["retry"] += int(bool(changed))
        return
    lines: list[dict] = []
    gaps: list[dict] = []
    suspects: dict[str, dict] = {}

    def note(payload: Mapping[str, Any]) -> None:
        suspects.setdefault(str(payload.get("sha1")), dict(payload))

    for key, entry in zip(keys, entries):
        got = outcomes.get(key) or {}
        if entry["state"] == "ok":
            pids = plan["pids"].get(unit_id) if entry["tool"] == "compare_reports" else None
            text = " / ".join(render_lines(entry["tool"], entry["args"], got.get("result"), pids=pids, on_suspect=note))
            lines.append({"ref": f"tool:{entry['call_id']}", "text": text})
        else:
            gaps.append({"tool": entry["tool"], "code": entry["code"] or INFRA_EXHAUSTED, "note": got.get("note") or ""})
    status = "partial" if gaps else "ok"
    if _freeze(store, target_key, unit_id, status, out, now=at, entries=entries, lines=lines, gaps=gaps, email=email,
               attempts=attempts + int(bool(infra))) and suspects:
        # 응답에 든 주입 어휘(자리표시자로 실린 원문)는 큐레이션 큐로 — 단위 빌드의 suspects 와 같은 큐 · 같은 규칙(열린 같은 sha1 은 한 번)
        owner = store.query_one("SELECT owner_sub FROM rr_targets WHERE target_key = ?", (target_key,))
        brief.begin_suspect_queue(store, owner["owner_sub"] if owner is not None else None)
        try:
            for payload in suspects.values():
                brief._on_suspect(payload)
        finally:
            brief.end_suspect_queue()


def _freeze(store: Any, target_key: str, unit_id: str, status: str, out: dict, *, now: int,
            entries: Sequence[Mapping[str, Any]] = (), lines: Sequence[Mapping[str, Any]] = (),
            gaps: Sequence[Mapping[str, Any]] = (), email: str | None = None, attempts: int | None = None) -> bool:
    """비교 후 쓰기 — status 가 NULL 인 행만 언다(폐기된 과제의 행은 쓰지 않는다). 바뀐 행이 0 이면(다른 ensure 가 먼저) 버린다."""
    body = {"lines": list(lines), "gaps": list(gaps)}
    sha = sha256_hex(canonical_json(body)) if (lines or gaps) else None
    chars = sum(len(str(line.get("text") or "")) for line in lines)
    called = status in ("ok", "partial") and bool(entries)
    changed = store.execute(
        "UPDATE rr_unit_live SET status = ?, plan_json = ?, lines_gz = ?, live_sha = ?, live_chars = ?, credential_kind = ?,"
        " credential_email = ?, gaps_json = ?, attempts = COALESCE(?, attempts), frozen_at = ?, updated_at = ?"
        " WHERE target_key = ? AND unit_id = ? AND status IS NULL" + NOT_PURGED_SQL,
        (status, canonical_json(list(entries)), gzip.compress(canonical_json(list(lines)).encode("utf-8"), mtime=0),
         sha, chars, CREDENTIAL_KIND if called else None, email if called else None,
         canonical_json(list(gaps)) if gaps else None, attempts, now, now, target_key, unit_id))
    if changed:
        out["frozen"][status] = out["frozen"].get(status, 0) + 1
    return bool(changed)


# ---------------------------------------------------------------- 작은 도구
def _loads(text: Any, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _ungz(blob: Any) -> Any:
    if not blob:
        return []
    try:
        return json.loads(gzip.decompress(blob).decode("utf-8"))
    except (OSError, ValueError):
        return []
