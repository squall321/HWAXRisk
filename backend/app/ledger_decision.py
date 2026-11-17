# 결정 → 판정표 층(RK-03) — 결정 JSON(contracts §3) · 결정문 글(parse_risk_spec) · 심의 job_id(그 사람의 PAT 로 게이트웨이)를 칸 대응 표로 원장 칸에 옮겨 층 하나로 쌓는다
"""HWAXPortal docs/request-1117 RK-03 · contracts.md §3.

- 입력은 셋 가운데 하나 — `decision_json`(엔진 `deliberate_result(view="decision_json")` 답 전체 또는 그 안의 `decision_json`), `decision_text`
  (결정문 — `narrative.parse_risk_spec` 과 같은 규칙), `job_id`(앱이 그 사람의 포털 PAT 로 게이트웨이 `deliberate_result` 를 부른다 — 엔진이
  decision_json 꼴을 아직 내지 않으면 view="summary" 의 결정문 글을 이어 받아 읽고, 표결은 그 답의 votes.tally 를 쓴다 · 없으면 모른다고 말한다).
- 칸 대응은 데이터다 — `decision_map` 틀({fields: {결정 칸 경로: 원장 칸}, code_field, items}) 또는 부를 때 준 대응. 결정 항목(risk_spec 의
  findings 따위)마다 code_field 가 원장 코드다.
- 칸마다 상태 — filled(값이 있고 앞 값이 비었거나 같다) · conflict(앞 값과 다르다 — 그래도 층에 싣고 표시한다, 판 짓기가 덮을지는 사람이 본다) ·
  empty(결정 항목에 칸은 있는데 값이 비었다 — 싣지 않는다) · no_source(결정 항목에 그 칸이 없다 — 싣지 않는다). 앞 값은 견줄 판(version)의 행이다.
- 결정문이 '전원 합의' 꼴로 만장일치를 말하는데 표결에 조건부 · 반대가 있으면 consistency.match=false 다.
- 패널 결과 다시 저장(risk_submit_panel_result)의 길은 쓰지 않는다 — 그 길은 finding 을 새로 세워 항목 위치가 사라진다(요청서 함정). 이 함수는
  판정표 층만 쌓는다(등록부 · finding 을 건드리지 않는다).
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

from app import ledger, narrative
from app.common import canonical_json
from app.errors import AppError

SOURCES: tuple[str, ...] = ("decision_json", "decision_text", "job_id")
STATUSES: tuple[str, ...] = ("filled", "empty", "conflict", "no_source")
DELIB_RESULT_TOOL = "deliberate_result"
DECISION_JSON_VIEW = "decision_json"
SUMMARY_VIEW = "summary"
RESULT_TIMEOUT_S = 60.0
SUMMARY_PARTS_MAX = 40
CELLS_SHOWN_MAX = 2000
# 표결 낱말 — 엔진(agree · conditional · oppose · abstain)과 한국어 꼴(동의 · 찬성 · 조건부 · 반대 · 미표명 · 기권)을 같은 칸으로 모은다.
TALLY_KEYS: dict[str, str] = {
    "agree": "agree", "찬성": "agree", "동의": "agree",
    "conditional": "conditional", "조건부": "conditional", "조건부 동의": "conditional", "조건부동의": "conditional",
    "oppose": "oppose", "반대": "oppose", "abstain": "abstain", "미표명": "abstain", "기권": "abstain", "total": "total",
}
# 만장일치를 말하는 문장 꼴(결정문 글 · 엔진 consensus_claim).
_CONSENSUS_RE = re.compile(r"(전원\s*(?:합의|동의|찬성|일치)|만장\s*일치|이견\s*(?:없|이\s*없)|모든\s*좌석이\s*동의|모두\s*동의|unanimous(?:ly)?)",
                           re.I)


# ---------------------------------------------------------------- 입력
def _normalize_tally(raw: Any) -> dict | None:
    if not isinstance(raw, Mapping):
        return None
    out: dict[str, int] = {}
    unknown: dict[str, Any] = {}
    for key, value in raw.items():
        slot = TALLY_KEYS.get(str(key).strip().lower()) or TALLY_KEYS.get(str(key).strip())
        if slot is None or not isinstance(value, int) or isinstance(value, bool):
            unknown[str(key)] = value
            continue
        out[slot] = out.get(slot, 0) + value
    if not out:
        return None
    if unknown:
        out["_unknown"] = unknown        # type: ignore[assignment]
    return out


def consensus_claim(text: str | None) -> str | None:
    if not text:
        return None
    hit = _CONSENSUS_RE.search(text)
    if hit is None:
        return None
    start = max(0, text.rfind("\n", 0, hit.start()) + 1)
    end = text.find("\n", hit.end())
    return " ".join(text[start:end if end >= 0 else len(text)].split())[:300]


def consistency(claim: str | None, tally: Mapping[str, Any] | None, engine: Mapping[str, Any] | None = None) -> dict:
    """합의 문장과 표결의 대조 — 문장이 만장일치를 말하는데 조건부 · 반대가 있으면 match=false."""
    claim = claim or (str((engine or {}).get("consensus_claim") or "") or None)
    dissent = None if tally is None else int(tally.get("conditional") or 0) + int(tally.get("oppose") or 0)
    if claim is None:
        match, note = None, "결정문에 만장일치를 말하는 문장이 없다"
    elif dissent is None:
        match, note = None, "표결을 모른다 — 합의 문장을 표결과 견주지 못했다"
    elif dissent > 0:
        match, note = False, f"결정문은 만장일치를 말하는데 표결에 조건부 · 반대가 {dissent}표 있다"
    else:
        match, note = True, "합의 문장과 표결이 맞다"
    if engine and engine.get("match") is False and match is not False:
        match, note = False, str(engine.get("note") or "엔진 대조가 불일치를 말한다")
    return {"consensus_claim": claim, "tally": tally, "dissent": dissent, "match": match, "note": note}


def _from_decision_json(raw: Mapping[str, Any]) -> dict:
    """엔진 답 전체({job_id, job, template, decision_json, consistency}) 또는 decision_json({risk_spec, votes, cites}) 또는 risk_spec 그대로."""
    engine_consistency = raw.get("consistency") if isinstance(raw.get("consistency"), Mapping) else None
    body = raw.get("decision_json") if "decision_json" in raw else raw
    if body is None:
        raise AppError("decision_unparsable", "엔진이 결정 JSON 을 내지 못했다 — " + str(raw.get("parse_error") or "까닭 없음"), 422,
                       detail={"parse_error": raw.get("parse_error")})
    if not isinstance(body, Mapping):
        raise ledger._bad("decision_json 은 객체다.")
    spec = body.get("risk_spec") if isinstance(body.get("risk_spec"), Mapping) else (body if body.get("schema") == "risk_spec" else None)
    if spec is None:
        raise AppError("decision_unparsable", "decision_json 에 risk_spec 이 없다(schema 가 risk_spec 인 객체).", 422)
    votes = body.get("votes") if isinstance(body.get("votes"), Mapping) else {}
    return {"risk_spec": dict(spec), "tally": _normalize_tally(votes.get("tally")), "engine_consistency": engine_consistency,
            "text": None, "votes_source": "decision_json" if votes.get("tally") else None}


def _from_text(text: str) -> dict:
    spec = narrative.parse_risk_spec(text)
    if spec is None:
        raise AppError("decision_unparsable", "결정문에서 risk_spec 을 읽지 못했다 — 마지막 ```json 펜스나 끝의 균형 중괄호에 schema 가 risk_spec 인"
                       " 객체가 있어야 한다.", 422)
    return {"risk_spec": spec, "tally": None, "engine_consistency": None, "text": text, "votes_source": None}


def _summary_pages(channel: Any, job_id: str) -> tuple[str | None, Any]:
    """view=summary 를 쪽마다 이어 결정문 글과 첫 쪽의 표결을 얻는다."""
    text_parts: list[str] = []
    votes: Any = None
    part = 1
    for _ in range(SUMMARY_PARTS_MAX):
        args = {"job_id": job_id, "view": SUMMARY_VIEW} if part == 1 else {"job_id": job_id, "view": SUMMARY_VIEW, "part": part}
        reply = channel.call(DELIB_RESULT_TOOL, args, deadline=time.monotonic() + RESULT_TIMEOUT_S)
        if not reply.get("ok"):
            raise AppError("decision_job_unreadable", f"게이트웨이 {DELIB_RESULT_TOOL}(job {job_id})를 읽지 못했다 — "
                           f"{_failure(reply)}", 409, detail={"job_id": job_id, "refusal": reply.get("refusal")})
        body = reply.get("result") if isinstance(reply.get("result"), Mapping) else {}
        if isinstance(body.get("decision"), str):
            text_parts.append(body["decision"])
        if votes is None and isinstance(body.get("votes"), Mapping):
            votes = body["votes"]
        nxt = (body.get("page") or {}).get("next") if isinstance(body.get("page"), Mapping) else None
        if not nxt:
            break
        part += 1
    return ("".join(text_parts) or None), votes


def _failure(reply: Mapping[str, Any]) -> str:
    refusal = reply.get("refusal") if isinstance(reply.get("refusal"), Mapping) else None
    if refusal:
        return str(refusal.get("message"))
    detail = reply.get("detail")
    text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False, default=str)
    return f"{reply.get('error') or 'unknown_error'} {' '.join(str(text or '').split())[:200]}".strip()


def from_job(channel: Any, job_id: str) -> dict:
    """심의 잡의 결정 — 먼저 view=decision_json, 엔진이 그 꼴을 모르면(도구 오류) view=summary 의 결정문 글을 읽는다."""
    reply = channel.call(DELIB_RESULT_TOOL, {"job_id": job_id, "view": DECISION_JSON_VIEW},
                         deadline=time.monotonic() + RESULT_TIMEOUT_S)
    body = reply.get("result") if reply.get("ok") and isinstance(reply.get("result"), Mapping) else None
    if body is not None and "decision_json" in body:
        got = _from_decision_json(body)
        return {**got, "view_used": DECISION_JSON_VIEW}
    if not reply.get("ok") and reply.get("error") != "tool_error":
        raise AppError("decision_job_unreadable", f"게이트웨이 {DELIB_RESULT_TOOL}(job {job_id})를 읽지 못했다 — {_failure(reply)}", 409,
                       detail={"job_id": job_id, "refusal": reply.get("refusal")})
    if reply.get("refusal"):
        raise AppError("decision_job_unreadable", f"게이트웨이가 {DELIB_RESULT_TOOL} 을 막았다 — {_failure(reply)}", 409,
                       detail={"job_id": job_id, "refusal": reply.get("refusal")})
    text, votes = _summary_pages(channel, job_id)
    if not text:
        raise AppError("decision_unparsable", f"심의 잡 {job_id} 에 결정문이 없다(끝나지 않았거나 결정문 단계 전에 멈췄다).", 422,
                       detail={"job_id": job_id})
    got = _from_text(text)
    tally = _normalize_tally((votes or {}).get("tally")) if isinstance(votes, Mapping) else None
    return {**got, "tally": tally, "votes_source": SUMMARY_VIEW if tally else None, "view_used": SUMMARY_VIEW}


# ---------------------------------------------------------------- 대응
_MISSING = object()


def _dig(item: Any, path: str) -> Any:
    current = item
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def _cell(value: Any) -> Any:
    """결정 값 → 원장 칸 값 — 글 · 수 · 참거짓은 그대로, 글 · 수 목록은 '; ' 로 잇고, 그 밖은 정규 JSON 글이다."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list) and all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in value):
        return "; ".join(str(v) for v in value)
    return canonical_json(value)


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, dict)) and not value)


def map_cells(spec: Mapping[str, Any], mapping: Mapping[str, Any], base: Mapping[str, Mapping[str, Any]]) -> dict:
    """risk_spec 의 항목을 칸 대응으로 펴 칸마다 상태를 매기고 층에 실을 행을 모은다."""
    cells: list[dict] = []
    rows: dict[str, dict[str, Any]] = {}
    items_n = 0
    without_code: list[str] = []
    bad_codes: list[str] = []
    for list_name in mapping["items"]:
        items = spec.get(list_name)
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            items_n += 1
            label = f"{list_name}[{index}]" + (f" {item.get('id')}" if isinstance(item, Mapping) and item.get("id") else "")
            code = _dig(item, mapping["code_field"])
            if code is _MISSING or _empty(code):
                without_code.append(label)
                continue
            code = str(code).strip()
            if not ledger.CODE_RE.fullmatch(code):
                bad_codes.append(code[:80])
                continue
            for path, column in mapping["fields"].items():
                raw = _dig(item, path)
                previous = (base.get(code) or {}).get(column)
                entry = {"code": code, "column": column, "field": path, "item": label, "previous": previous}
                if raw is _MISSING:
                    cells.append({**entry, "status": "no_source", "value": None})
                    continue
                if _empty(raw):
                    cells.append({**entry, "status": "empty", "value": None})
                    continue
                value = _cell(raw)
                status = "filled" if ledger.is_empty(previous) or ledger.same_value(previous, value) else "conflict"
                earlier = rows.get(code, {}).get(column, _MISSING)
                if earlier is not _MISSING and not ledger.same_value(earlier, value):
                    status, entry["note"] = "conflict", "결정 안의 두 항목이 이 칸에 다른 값을 준다 — 뒤 항목의 값을 싣는다"
                cells.append({**entry, "status": status, "value": value})
                rows.setdefault(code, {})[column] = value
    counts = {s: sum(1 for c in cells if c["status"] == s) for s in STATUSES}
    return {"cells": cells, "rows": rows, "counts": counts, "items_n": items_n, "items_without_code": without_code,
            "items_bad_code": bad_codes}


def resolve_mapping(store: Any, target_key: str, mapping: Any, mapping_version: int | None) -> tuple[dict, int | None]:
    """부를 때 준 대응(칸 정의와 대조) 또는 등록된 decision_map 틀(판을 안 주면 가장 새 판)."""
    if mapping is not None:
        colset = ledger.require_columns(store, target_key)
        return ledger._normalize_decision_map(mapping if isinstance(mapping, Mapping) else {}, ledger.column_names(colset)), None
    found = ledger.template(store, target_key, "decision_map", mapping_version)
    if found is None:
        raise AppError("ledger_decision_map_missing", "결정 칸 → 원장 칸 대응이 없다 — mapping 을 주거나 decision_map 틀을 등록한다.", 409,
                       detail={"fix": "risk_ledger_put_template(kind='decision_map') · PUT /api/targets/{key}/ledger/templates/decision_map"})
    return found["body"], found["version"]


def apply(store: Any, target_key: str, owner_sub: str, *, decision: dict, source: dict, mapping: Any = None,
          mapping_version: int | None = None, version: int | None = None, layer_name: str | None = None,
          layer_order: int | None = None, actor: str) -> dict:
    """읽은 결정(`decision` — risk_spec · tally · engine_consistency · text)을 대응으로 펴 판정표 층 하나로 쌓는다."""
    body, map_version = resolve_mapping(store, target_key, mapping, mapping_version)
    compared = None
    base: dict[str, dict[str, Any]] = {}
    latest = ledger.latest_version(store, target_key)
    if version is not None or latest is not None:
        head = ledger.version_head(store, target_key, version)
        compared = int(head["version"])
        base = ledger.version_rows(store, target_key, compared)
    mapped = map_cells(decision["risk_spec"], body, base)
    tally = decision.get("tally")
    check = consistency(consensus_claim(decision.get("text")), tally, decision.get("engine_consistency"))
    meta = {"source": source, "mapping_version": map_version, "version_compared": compared, "counts": mapped["counts"],
            "tally": tally, "consistency": check, "items_n": mapped["items_n"]}
    layer = None
    notes: list[str] = []
    if tally is None:
        notes.append("표결을 모른다 — " + ("엔진이 아직 decision_json 꼴을 내지 않아 결정문 글로 읽었다" if source.get("kind") == "job_id" else
                                         "결정 글에는 표결이 없다(job_id 나 decision_json 의 votes 로 준다)"))
    if mapped["rows"]:
        if layer_order is None:
            row = store.query_one("SELECT MAX(layer_order) AS o FROM rr_ledger_layers WHERE target_key = ?", (target_key,))
            layer_order = (int(row["o"]) if row and row["o"] is not None else 0) + 10
        name = layer_name or ("결정 반영 " + (source.get("job_id") or source["kind"]))[:ledger.NAME_MAX]
        source_file = (f"deliberation:{source['job_id']}" if source.get("job_id") else source["kind"])[:ledger.SOURCE_FILE_MAX]
        layer = ledger.put_layer(store, target_key, owner_sub, name=name, order=layer_order, rows=mapped["rows"], source_file=source_file,
                                 origin="decision", meta=meta, actor=actor)
    else:
        notes.append("채울 칸이 없다 — 층을 쌓지 않았다(칸 상태를 본다)")
    codes = set(mapped["rows"])
    cells = mapped["cells"]
    return {"target_key": target_key, "layer_id": (layer or {}).get("layer_id"), "layer": layer, "source": source,
            "mapping_version": map_version, "version_compared": compared, "counts": mapped["counts"],
            "cells": cells[:CELLS_SHOWN_MAX], "cells_truncated": max(0, len(cells) - CELLS_SHOWN_MAX), "items_n": mapped["items_n"],
            "items_without_code": mapped["items_without_code"], "items_bad_code": mapped["items_bad_code"],
            "codes_new": sorted(codes - set(base), key=ledger.code_sort_key),
            "codes_without_decision_n": len(set(base) - {c["code"] for c in cells}), "tally": tally, "consistency": check,
            "notes": notes}


def read_decision(*, decision_json: Any = None, decision_text: Any = None, job_id: Any = None, channel_factory: Any = None) -> tuple[dict, dict]:
    """세 입력 가운데 하나만 — (읽은 결정, 출처 표지). job_id 는 channel_factory() 가 준 그 사람의 게이트웨이 채널로 읽는다."""
    given = [name for name, value in (("decision_json", decision_json), ("decision_text", decision_text), ("job_id", job_id))
             if value not in (None, "")]
    if len(given) != 1:
        raise ledger._bad("decision_json · decision_text · job_id 가운데 하나만 준다.", given=given)
    if decision_json is not None:
        if not isinstance(decision_json, Mapping):
            raise ledger._bad("decision_json 은 객체다.")
        got = _from_decision_json(decision_json)
        return got, {"kind": "decision_json", "job_id": decision_json.get("job_id"), "votes_known": got["tally"] is not None}
    if decision_text is not None:
        if not isinstance(decision_text, str):
            raise ledger._bad("decision_text 는 글이다.")
        got = _from_text(decision_text)
        return got, {"kind": "decision_text", "votes_known": False}
    job = str(job_id).strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", job):
        raise ledger._bad("job_id 는 심의 잡 id 다(영문 · 숫자 · _ . : -).")
    channel = channel_factory()
    try:
        got = from_job(channel, job)
    finally:
        close = getattr(channel, "close", None)
        if callable(close):
            close()
    return got, {"kind": "job_id", "job_id": job, "view_used": got.get("view_used"), "votes_known": got["tally"] is not None,
                 "votes_source": got.get("votes_source")}


__all__: Sequence[str] = ("apply", "read_decision", "consistency", "consensus_claim", "map_cells", "STATUSES")
