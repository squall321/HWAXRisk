# 판정표 원장(RK-01) — 칸 정의 · facts 틀 · 결정 칸 대응의 판 등록, 덮어쓰기 층, 판 짓기(층 차례대로 덮고 덮은 앞 값을 칸마다 남긴다) · 판 비교 · 내보내기
"""HWAXPortal docs/request-1117 RK-01 · contracts.md.

- 칸 정의는 데이터다(context-notes R-2) — 대상마다 `columns` 틀을 판으로 등록한다(칸 이름 · 차례 · 등급 칸 · SP 사전 키 칸 · 표기 축 · 그림 칸).
  과제 고유 칸을 코드에 박지 않는다. facts 틀(RK-05) · 결정 칸 대응(RK-03)도 같은 표의 다른 종류다.
- 판 = 기준 판 + 층들. 층은 `layer_order` 차례로 덮는다 — 같은 칸이면 뒤 층이 이긴다. 덮은 칸마다 그 앞 값을 `rr_ledger_cells` 에 남긴다(층 차례가
  병합 스크립트 안에만 있던 것을 데이터로). 행 열쇠는 코드다(참조번호는 리비전마다 바뀐다).
- 빈 칸 — 값 null · 빈 글은 같은 '빈 칸' 이다(비교 · 등급 변경 셈). 층의 null 은 그 칸을 비운다.
- 셈은 행으로 한다 — 파일 줄 수가 아니다(값 안의 줄바꿈이 행 수를 바꾸지 않는다).
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app import labels
from app.common import canonical_json, new_uuid, now_epoch, sha256_hex
from app.errors import AppError

TEMPLATE_KINDS: tuple[str, ...] = ("columns", "facts", "decision_map")
LAYER_ORIGINS: tuple[str, ...] = ("manual", "decision")
EXPORT_FORMATS: tuple[str, ...] = ("csv", "json")
# 내보내기 첫 줄의 보안 문구 — 칸 정의 틀의 notice 가 없을 때 쓴다(과제 자료가 담긴다 — 요청서 '넘기기 전 보안 승인').
NOTICE_DEFAULT = "[보안] 사내 한정 — 미출시 과제 정보가 담길 수 있다. 반출 · 공유 전에 보안 승인을 받는다."
NOTICE_MAX = 300
NAME_MAX = 64
CODE_MAX = 64
COLUMNS_MAX = 200
FACT_KEYS_MAX = 200
LAYER_ROWS_MAX = 20_000
LAYER_CELLS_MAX = 400_000
VALUE_MAX = 20_000
SOURCE_FILE_MAX = 300
BUILD_LAYERS_MAX = 50
# 코드 — 글자 · 숫자로 시작하고 영문 · 한글 · 숫자 · _ . : / # - 만(빈칸 없음). 참조번호가 아니라 리비전을 넘어 같은 행을 잇는 열쇠다.
CODE_RE = re.compile(r"^[A-Za-z0-9가-힣][A-Za-z0-9가-힣_.:/#-]{0,63}$")
# 칸 이름에 판정 낱말을 쓰면 좌석이 그 이름을 판정으로 인용한다(요청서 RK-02 함정 — 근거 칸 이름은 중립이어야 한다). 판정 · 심각도 · 판정 결과
# 낱말이 낱말로 들면 받지 않는다.
_JUDGEMENT_WORDS = ("OK", "WARNING", "FAIL", "PASS", "NG", "GO", "NO-GO", "경미", "중대", "치명", "합격", "불합격", "위험확정")
_JUDGEMENT_RE = re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(w) for w in _JUDGEMENT_WORDS) + r")(?![A-Za-z0-9])", re.I)
# facts 틀의 원천 — 원장 칸 이름이거나 아래 낱말이다.
FACT_SOURCES: tuple[str, ...] = ("@code", "@version", "@sources", "@figures", "@numbers")
_FACT_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}(\.[A-Za-z_][A-Za-z0-9_]{0,40}){0,3}$")


# ---------------------------------------------------------------- 공통
def _bad(message: str, **detail: Any) -> AppError:
    return AppError("E100", message, 422, detail=detail or None)


def _text(value: Any, field: str, *, max_len: int, required: bool = True) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise _bad(f"{field} 가 비었다.")
        return None
    if not isinstance(value, str):
        raise _bad(f"{field} 는 글이어야 한다.")
    text = value.strip()
    if len(text) > max_len or any(ord(ch) < 32 for ch in text):
        raise _bad(f"{field} 는 {max_len}자 이하 한 줄 글이다.")
    return text


def _cell_value(value: Any, where: str) -> Any:
    """칸 값 — 글 · 수 · 참거짓 · null 만 받는다(글은 그대로 — 내보내기가 원본과 칸 단위로 같아야 한다)."""
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise _bad(f"{where} 의 값이 수가 아니다(NaN · 무한).")
        return value
    if isinstance(value, str):
        if len(value) > VALUE_MAX:
            raise _bad(f"{where} 의 값이 {VALUE_MAX:,}자를 넘는다.")
        return value
    raise _bad(f"{where} 의 값은 글 · 수 · 참거짓 · null 가운데 하나다.")


def is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def same_value(a: Any, b: Any) -> bool:
    """빈 칸(null · 빈 글)은 서로 같고, 그 밖은 정규 JSON 이 같을 때 같다."""
    if is_empty(a) and is_empty(b):
        return True
    return canonical_json(a) == canonical_json(b)


def check_code(code: Any, where: str = "코드") -> str:
    if not isinstance(code, str) or not CODE_RE.fullmatch(code):
        raise _bad(f"{where} {code!r} 는 꼴이 아니다 — 글자 · 숫자로 시작하는 {CODE_MAX}자 이하(영문 · 한글 · 숫자 · _ . : / # -, 빈칸 없음).")
    return code


def code_sort_key(code: str) -> tuple:
    """코드 차례 — 숫자 마디는 수로 본다(R-2 가 R-10 앞)."""
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"(\d+)", code) if p != "")


# ---------------------------------------------------------------- 틀(칸 정의 · facts · 결정 칸 대응)
def _normalize_columns(body: Mapping[str, Any]) -> dict:
    raw = body.get("columns")
    if not isinstance(raw, list) or not raw:
        raise _bad("columns 는 칸 정의 목록이다(하나 이상).")
    if len(raw) > COLUMNS_MAX:
        raise _bad(f"칸은 {COLUMNS_MAX}개까지다.")
    out, names, orders = [], set(), set()
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise _bad(f"columns[{i}] 는 객체다.")
        unknown = set(item) - {"name", "order", "grade", "sp_key", "axis", "figure"}
        if unknown:
            raise _bad(f"columns[{i}] 에 모르는 칸이 있다 — {sorted(unknown)}.")
        name = _text(item.get("name"), f"columns[{i}].name", max_len=NAME_MAX)
        hit = _JUDGEMENT_RE.search(name)
        if hit:
            raise _bad(f"칸 이름 {name!r} 에 판정 낱말 {hit.group(1)!r} 이 들었다 — 좌석이 칸 이름을 판정으로 인용한다(근거 칸 이름은 중립 낱말로,"
                       " 예 '판정' · '등급').", column=name)
        if name in names:
            raise _bad(f"칸 이름이 겹친다 — {name!r}.")
        order = item.get("order", i + 1)
        if not isinstance(order, int) or isinstance(order, bool):
            raise _bad(f"columns[{i}].order 는 정수다.")
        if order in orders:
            raise _bad(f"칸 차례가 겹친다 — {order}.")
        grade = item.get("grade", False)
        sp_key = item.get("sp_key", False)
        figure = item.get("figure", False)
        if not all(isinstance(v, bool) for v in (grade, sp_key, figure)):
            raise _bad(f"columns[{i}] 의 grade · sp_key · figure 는 참거짓이다.")
        axis = item.get("axis")
        if axis is None and grade:
            axis = "grade"
        if axis is not None and axis not in labels.AXES:
            raise _bad(f"columns[{i}].axis 는 {list(labels.AXES)} 가운데 하나거나 null 이다 — {axis!r}.")
        names.add(name)
        orders.add(order)
        out.append({"name": name, "order": order, "grade": grade, "sp_key": sp_key, "axis": axis, "figure": figure})
    out.sort(key=lambda c: c["order"])
    notice = _text(body.get("notice"), "notice", max_len=NOTICE_MAX, required=False)
    code_label = _text(body.get("code_label"), "code_label", max_len=NAME_MAX, required=False) or "code"
    return {"columns": out, "notice": notice, "code_label": code_label}


def _normalize_facts(body: Mapping[str, Any], columns: Sequence[str]) -> dict:
    raw = body.get("keys")
    if not isinstance(raw, list) or not raw:
        raise _bad("keys 는 facts 키 목록이다(하나 이상).")
    if len(raw) > FACT_KEYS_MAX:
        raise _bad(f"facts 키는 {FACT_KEYS_MAX}개까지다.")
    out, seen = [], set()
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping) or set(item) - {"key", "from"}:
            raise _bad(f"keys[{i}] 는 {{key, from}} 객체다.")
        key = item.get("key")
        if not isinstance(key, str) or not _FACT_KEY_RE.fullmatch(key):
            raise _bad(f"keys[{i}].key {key!r} 는 영문 키(점으로 넷까지 내려간다 — 예 cad.use)다.")
        if key in seen or any(k.startswith(key + ".") or key.startswith(k + ".") for k in seen):
            raise _bad(f"facts 키가 겹치거나 한 키가 다른 키의 부모다 — {key!r}.")
        source = item.get("from")
        if source is not None and source not in FACT_SOURCES and source not in columns:
            raise _bad(f"keys[{i}].from {source!r} 는 칸 정의에 없는 칸이다 — 원장 칸 이름 · {list(FACT_SOURCES)} · null(대응 없음)"
                       " 가운데 하나다.", key=key)
        seen.add(key)
        out.append({"key": key, "from": source})
    return {"keys": out}


def _normalize_decision_map(body: Mapping[str, Any], columns: Sequence[str]) -> dict:
    fields = body.get("fields")
    if not isinstance(fields, Mapping) or not fields:
        raise _bad("fields 는 {결정 칸 경로: 원장 칸} 대응이다(하나 이상).")
    out = {}
    for path, column in fields.items():
        if not isinstance(path, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+){0,4}", path):
            raise _bad(f"결정 칸 경로 {path!r} 는 점으로 가른 영문 경로다(예 severity · subject.code).")
        if column not in columns:
            raise _bad(f"{path!r} 가 가리키는 원장 칸 {column!r} 이 칸 정의에 없다.")
        out[path] = column
    if len(set(out.values())) != len(out):
        raise _bad("두 결정 칸이 한 원장 칸을 가리킨다 — 어느 쪽이 이기는지 대응이 말하지 않는다.")
    code_field = body.get("code_field", "code")
    if not isinstance(code_field, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_]+){0,4}", code_field):
        raise _bad(f"code_field {code_field!r} 는 결정 항목 안에서 원장 코드를 쥔 경로다(기본 code).")
    items = body.get("items", ["findings"])
    if (not isinstance(items, list) or not items
            or not all(isinstance(x, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", x) for x in items)):
        raise _bad("items 는 risk_spec 의 항목 목록 이름이다(기본 ['findings']).")
    return {"fields": out, "code_field": code_field, "items": list(dict.fromkeys(items))}


def template(store: Any, target_key: str, kind: str, version: int | None = None) -> dict | None:
    """그 종류의 틀 한 판(판을 안 주면 가장 새 판). 없으면 None."""
    if version is None:
        row = store.query_one("SELECT * FROM rr_ledger_templates WHERE target_key = ? AND kind = ? ORDER BY version DESC LIMIT 1",
                              (target_key, kind))
    else:
        row = store.query_one("SELECT * FROM rr_ledger_templates WHERE target_key = ? AND kind = ? AND version = ?",
                              (target_key, kind, int(version)))
    if row is None:
        return None
    return {"kind": row["kind"], "version": row["version"], "body": json.loads(row["body_json"] or "{}"),
            "body_hash": row["body_hash"], "created_by": row["created_by"], "created_at": row["created_at"]}


def require_columns(store: Any, target_key: str, version: int | None = None) -> dict:
    found = template(store, target_key, "columns", version)
    if found is None:
        what = f"칸 정의 판 c{version}" if version is not None else "칸 정의"
        raise AppError("ledger_columns_missing", f"이 대상에 {what} 가 없다 — 먼저 칸 정의(columns 틀)를 등록한다.", 409,
                       detail={"fix": "risk_ledger_put_template(kind='columns') · PUT /api/targets/{key}/ledger/templates/columns"})
    return found


def column_names(colset: Mapping[str, Any]) -> list[str]:
    return [c["name"] for c in colset["body"]["columns"]]


def put_template(store: Any, target_key: str, owner_sub: str, kind: str, body: Any, *, actor: str) -> dict:
    """틀 한 판을 적는다 — 같은 몸이면 지금 판을 돌려준다(created false). facts · decision_map 은 지금 칸 정의의 칸 이름과 대조한다."""
    if kind not in TEMPLATE_KINDS:
        raise _bad(f"틀 종류는 {list(TEMPLATE_KINDS)} 가운데 하나다 — {kind!r}.")
    if not isinstance(body, Mapping):
        raise _bad("틀 몸은 객체다.")
    if kind == "columns":
        normal = _normalize_columns(body)
    else:
        colset = require_columns(store, target_key)
        normal = (_normalize_facts if kind == "facts" else _normalize_decision_map)(body, column_names(colset))
        normal["colset_version"] = colset["version"]
    body_json = canonical_json(normal)
    body_hash = sha256_hex(body_json)
    with store.tx():
        last = template(store, target_key, kind)
        if last is not None and last["body_hash"] == body_hash:
            return {**last, "created": False}
        version = 1 if last is None else int(last["version"]) + 1
        now = now_epoch()
        store.execute("INSERT INTO rr_ledger_templates(target_key, kind, version, owner_sub, body_json, body_hash, created_by, created_at)"
                      " VALUES (?,?,?,?,?,?,?,?)", (target_key, kind, version, owner_sub, body_json, body_hash, actor, now))
    return {"kind": kind, "version": version, "body": normal, "body_hash": body_hash, "created_by": actor, "created_at": now,
            "created": True}


# ---------------------------------------------------------------- 층
def _normalize_rows(rows: Any, columns: Sequence[str]) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, Mapping) or not rows:
        raise _bad("rows 는 {코드: {칸: 값}} 이다(한 행 이상).")
    if len(rows) > LAYER_ROWS_MAX:
        raise _bad(f"층 하나의 행은 {LAYER_ROWS_MAX:,}개까지다.")
    known = set(columns)
    out: dict[str, dict[str, Any]] = {}
    unknown: set[str] = set()
    cells = 0
    for code, cols in rows.items():
        check_code(code)
        if not isinstance(cols, Mapping) or not cols:
            raise _bad(f"행 {code!r} 는 {{칸: 값}} 이다(한 칸 이상).")
        unknown |= {c for c in cols if c not in known}
        out[code] = {c: _cell_value(v, f"{code}.{c}") for c, v in cols.items()}
        cells += len(cols)
    if unknown:
        raise AppError("ledger_unknown_columns", f"칸 정의에 없는 칸 — {sorted(unknown)[:20]}. 칸 정의를 먼저 고친다(새 판).", 422,
                       detail={"unknown_columns": sorted(unknown)})
    if cells > LAYER_CELLS_MAX:
        raise _bad(f"층 하나의 칸은 {LAYER_CELLS_MAX:,}개까지다.")
    return out


def _layer_view(row: Mapping[str, Any], *, with_rows: bool = False) -> dict:
    rows = json.loads(row["rows_json"] or "{}")
    out = {"layer_id": row["layer_id"], "target_key": row["target_key"], "name": row["name"], "order": row["layer_order"],
           "source_file": row["source_file"], "origin": row["origin"], "colset_version": row["colset_version"],
           "rows_n": len(rows), "cells_n": sum(len(v) for v in rows.values()), "rows_hash": row["rows_hash"],
           "created_by": row["created_by"], "created_at": row["created_at"]}
    if row["meta_json"]:
        out["meta"] = json.loads(row["meta_json"])
    if with_rows:
        out["rows"] = rows
    return out


def put_layer(store: Any, target_key: str, owner_sub: str, *, name: Any, order: Any, rows: Any, source_file: Any = None,
              origin: str = "manual", meta: Mapping[str, Any] | None = None, actor: str) -> dict:
    """덮어쓰기 층 하나를 쌓는다(판은 아직 바뀌지 않는다 — risk_ledger_build 가 차례대로 덮는다). 같은 (이름 · 차례 · 원천 · 행)이면 그 층을
    돌려준다(created false)."""
    name = _text(name, "layer.name", max_len=NAME_MAX)
    if not isinstance(order, int) or isinstance(order, bool):
        raise _bad("layer.order 는 정수다(작은 차례가 먼저 덮고 큰 차례가 이긴다).")
    source_file = _text(source_file, "layer.source_file", max_len=SOURCE_FILE_MAX, required=False)
    if origin not in LAYER_ORIGINS:
        raise _bad(f"층 출처는 {list(LAYER_ORIGINS)} 가운데 하나다.")
    colset = require_columns(store, target_key)
    normal = _normalize_rows(rows, column_names(colset))
    rows_json = canonical_json(normal)
    rows_hash = sha256_hex(rows_json)
    meta_json = canonical_json(dict(meta)) if meta else None
    with store.tx():
        same = store.query_one(
            "SELECT * FROM rr_ledger_layers WHERE target_key = ? AND name = ? AND layer_order = ? AND rows_hash = ?"
            " AND COALESCE(source_file, '') = ? AND origin = ? AND COALESCE(meta_json, '') = ?",
            (target_key, name, order, rows_hash, source_file or "", origin, meta_json or ""))
        if same is not None:
            return {**_layer_view(same), "created": False}
        layer_id = "ly-" + new_uuid()[:24]
        store.execute("INSERT INTO rr_ledger_layers(layer_id, target_key, owner_sub, name, layer_order, source_file, origin,"
                      " colset_version, rows_json, rows_hash, meta_json, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (layer_id, target_key, owner_sub, name, order, source_file, origin, colset["version"], rows_json, rows_hash,
                       meta_json, actor, now_epoch()))
        row = store.query_one("SELECT * FROM rr_ledger_layers WHERE layer_id = ?", (layer_id,))
    return {**_layer_view(row), "created": True}


def layer_row(store: Any, target_key: str, layer_id: str) -> dict:
    row = store.query_one("SELECT * FROM rr_ledger_layers WHERE layer_id = ? AND target_key = ?", (layer_id, target_key))
    if row is None:
        raise AppError("ledger_layer_missing", f"이 대상에 그 층이 없다 — {layer_id}.", 404)
    return dict(row)


# ---------------------------------------------------------------- 판
def latest_version(store: Any, target_key: str) -> int | None:
    row = store.query_one("SELECT MAX(version) AS v FROM rr_ledger_versions WHERE target_key = ?", (target_key,))
    return None if row is None or row["v"] is None else int(row["v"])


def version_head(store: Any, target_key: str, version: int | None) -> dict:
    """판 머리 — 판을 안 주면 가장 새 판. 없으면 404 ledger_version_missing."""
    if version is None:
        version = latest_version(store, target_key)
    row = None if version is None else store.query_one(
        "SELECT * FROM rr_ledger_versions WHERE target_key = ? AND version = ?", (target_key, int(version)))
    if row is None:
        raise AppError("ledger_version_missing", "이 대상에 그 판정표 판이 없다" + (f" — v{version}." if version is not None else
                       " — 먼저 판을 짓는다(risk_ledger_build)."), 404)
    out = dict(row)
    out["layers"] = json.loads(out.pop("layers_json") or "[]")
    return out


def version_rows(store: Any, target_key: str, version: int) -> dict[str, dict[str, Any]]:
    rows = store.query("SELECT code, cells_json FROM rr_ledger_rows WHERE target_key = ? AND version = ?", (target_key, int(version)))
    return {r["code"]: json.loads(r["cells_json"] or "{}") for r in sorted(rows, key=lambda r: code_sort_key(r["code"]))}


def grade_columns(colset: Mapping[str, Any]) -> list[str]:
    return [c["name"] for c in colset["body"]["columns"] if c.get("grade")]


def _grade_changed(base: Mapping[str, Mapping[str, Any]], new: Mapping[str, Mapping[str, Any]], grades: Sequence[str]) -> list[str]:
    """두 판에 다 있는 코드 가운데 등급 칸 값이 하나라도 바뀐 코드(새로 든 · 빠진 코드는 등급 변경이 아니라 추가 · 삭제다)."""
    return [code for code in new if code in base
            and any(not same_value(base[code].get(g), new[code].get(g)) for g in grades)]


def build_version(store: Any, target_key: str, owner_sub: str, *, base_version: int | None, layers: Sequence[Any],
                  colset_version: int | None = None, actor: str) -> dict:
    """기준 판 위에 층들을 차례대로 덮어 새 판을 짓는다. 층은 layer_id 이거나 {name, order, rows, source_file} 객체(그 자리에서 쌓는다)다.
    같은 (기준 판 · 층 차례 · 칸 정의 판)이면 지은 판을 돌려준다(created false)."""
    if not isinstance(layers, (list, tuple)) or not layers:
        raise _bad("layers 는 층 하나 이상이다(layer_id 또는 {name, order, rows, source_file}).")
    if len(layers) > BUILD_LAYERS_MAX:
        raise _bad(f"한 번에 덮는 층은 {BUILD_LAYERS_MAX}개까지다.")
    colset = require_columns(store, target_key, colset_version)
    columns = column_names(colset)
    resolved: list[dict] = []
    for i, item in enumerate(layers):
        if isinstance(item, str):
            resolved.append(layer_row(store, target_key, item))
        elif isinstance(item, Mapping):
            unknown = set(item) - {"name", "order", "rows", "source_file"}
            if unknown:
                raise _bad(f"layers[{i}] 에 모르는 칸이 있다 — {sorted(unknown)}.")
            made = put_layer(store, target_key, owner_sub, name=item.get("name"), order=item.get("order"), rows=item.get("rows"),
                             source_file=item.get("source_file"), actor=actor)
            resolved.append(layer_row(store, target_key, made["layer_id"]))
        else:
            raise _bad(f"layers[{i}] 는 layer_id 이거나 층 객체다.")
    ids = [r["layer_id"] for r in resolved]
    if len(set(ids)) != len(ids):
        raise _bad("같은 층을 두 번 덮는다.")
    orders = [r["layer_order"] for r in resolved]
    if len(set(orders)) != len(orders):
        raise _bad("층 차례가 겹친다 — 같은 칸을 두 층이 덮으면 어느 쪽이 이기는지 데이터가 말하지 않는다.",
                   orders=sorted(o for o in orders if orders.count(o) > 1))
    resolved.sort(key=lambda r: r["layer_order"])
    stray = sorted({c for r in resolved for cols in json.loads(r["rows_json"]).values() for c in cols} - set(columns))
    if stray:
        raise AppError("ledger_unknown_columns", f"층의 칸이 칸 정의 판 c{colset['version']} 에 없다 — {stray[:20]}.", 422,
                       detail={"unknown_columns": stray})

    base_rows: dict[str, dict[str, Any]] = {}
    if base_version is not None:
        version_head(store, target_key, base_version)
        base_rows = version_rows(store, target_key, int(base_version))
    inputs_hash = sha256_hex(canonical_json({"base": base_version, "layers": [r["layer_id"] for r in resolved],
                                             "colset_version": colset["version"]}))
    with store.tx():
        same = store.query_one("SELECT version FROM rr_ledger_versions WHERE target_key = ? AND inputs_hash = ?",
                               (target_key, inputs_hash))
        if same is not None:
            return {**build_summary(store, target_key, int(same["version"])), "created": False}

        current = {code: {c: v for c, v in cells.items() if c in columns} for code, cells in base_rows.items()}
        dropped = sorted({c for cells in base_rows.values() for c in cells} - set(columns))
        version = (latest_version(store, target_key) or 0) + 1
        seq = 0
        cell_rows: list[tuple] = []
        summary: list[dict] = []
        for layer in resolved:
            rows = json.loads(layer["rows_json"])
            applied = changed = new_codes = 0
            for code in sorted(rows, key=code_sort_key):
                if code not in current:
                    current[code] = {}
                    new_codes += 1
                for col, value in rows[code].items():
                    prev = current[code].get(col)
                    seq += 1
                    applied += 1
                    if not same_value(prev, value):
                        changed += 1
                    cell_rows.append((target_key, version, seq, owner_sub, layer["layer_id"], layer["name"], layer["layer_order"],
                                      layer["source_file"], code, col, canonical_json(value) if value is not None else None,
                                      canonical_json(prev) if col in current[code] else None))
                    if value is None:
                        current[code].pop(col, None)
                    else:
                        current[code][col] = value
            summary.append({"layer_id": layer["layer_id"], "name": layer["name"], "order": layer["layer_order"],
                            "source_file": layer["source_file"], "origin": layer["origin"], "rows": len(rows), "cells": applied,
                            "changed": changed, "new_codes": new_codes})
        ordered = sorted(current, key=code_sort_key)
        rows_hash = sha256_hex(canonical_json({code: current[code] for code in ordered}))
        grade_changed = _grade_changed(base_rows, current, grade_columns(colset)) if base_version is not None else []
        notice = colset["body"].get("notice") or NOTICE_DEFAULT
        store.execute("INSERT INTO rr_ledger_versions(target_key, version, owner_sub, based_on, colset_version, notice, layers_json,"
                      " inputs_hash, rows_n, rows_hash, grade_changed_n, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (target_key, version, owner_sub, base_version, colset["version"], notice, canonical_json(summary), inputs_hash,
                       len(ordered), rows_hash, len(grade_changed) if base_version is not None else None, actor, now_epoch()))
        store.executemany("INSERT INTO rr_ledger_rows(target_key, version, code, owner_sub, cells_json) VALUES (?,?,?,?,?)",
                          [(target_key, version, code, owner_sub, canonical_json(current[code])) for code in ordered])
        store.executemany("INSERT INTO rr_ledger_cells(target_key, version, seq, owner_sub, layer_id, layer_name, layer_order,"
                          " source_file, code, col, value_json, prev_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", cell_rows)
    out = build_summary(store, target_key, version)
    out["columns_dropped"] = dropped
    return {**out, "created": True}


def build_summary(store: Any, target_key: str, version: int) -> dict:
    head = version_head(store, target_key, version)
    out = {k: head[k] for k in ("target_key", "version", "based_on", "colset_version", "rows_n", "rows_hash", "grade_changed_n",
                                "created_by", "created_at")}
    out["layers"] = head["layers"]
    out["applied"] = {"cells": sum(x["cells"] for x in head["layers"]), "changed": sum(x["changed"] for x in head["layers"])}
    if head["based_on"] is not None:
        colset = require_columns(store, target_key, head["colset_version"])
        out["grade_changed_codes"] = _grade_changed(version_rows(store, target_key, head["based_on"]),
                                                    version_rows(store, target_key, version), grade_columns(colset))
    return out


def diff_versions(store: Any, target_key: str, version: int, base: int | None = None) -> dict:
    """두 판의 차이 — 바뀐 코드 · 칸 · 앞뒤 값, 든 · 빠진 코드, 등급이 바뀐 코드 수(두 판에 다 있는 코드). base 를 안 주면 그 판의 기준 판이다.
    칸은 새 판의 칸 정의 차례, 코드는 코드 차례다. 셈은 행이다(파일 줄이 아니다)."""
    head = version_head(store, target_key, version)
    base = head["based_on"] if base is None else int(base)
    if base is None:
        raise _bad(f"v{version} 은 기준 판 없이 지었다 — 견줄 판(base)을 준다.")
    base_head = version_head(store, target_key, base)
    colset = require_columns(store, target_key, head["colset_version"])
    order = {c: i for i, c in enumerate(column_names(colset))}
    old, new = version_rows(store, target_key, base), version_rows(store, target_key, version)
    changes: list[dict] = []
    for code in sorted(set(old) & set(new), key=code_sort_key):
        cols = sorted(set(old[code]) | set(new[code]), key=lambda c: (order.get(c, len(order)), c))
        for col in cols:
            if not same_value(old[code].get(col), new[code].get(col)):
                changes.append({"code": code, "column": col, "before": old[code].get(col), "after": new[code].get(col)})
    grades = grade_columns(colset)
    graded = _grade_changed(old, new, grades)
    return {"target_key": target_key, "version": version, "base": base, "colset_version": head["colset_version"],
            "base_colset_version": base_head["colset_version"], "rows_n": {"base": len(old), "version": len(new)},
            "codes_added": sorted(set(new) - set(old), key=code_sort_key), "codes_removed": sorted(set(old) - set(new), key=code_sort_key),
            "changed_codes_n": len({c["code"] for c in changes}), "changed_cells_n": len(changes),
            "grade_columns": grades, "grade_changed_n": len(graded), "grade_changed_codes": graded, "changes": changes}


def export_table(store: Any, target_key: str, version: int | None = None) -> dict:
    """내보낼 표 — 머리(보안 문구 · 판 · 칸 정의 판)와 칸 차례 · 코드 차례의 행. 값은 원장 그대로다(표기 규칙을 입히지 않는다 — 원본 표와 칸
    단위로 같아야 한다)."""
    head = version_head(store, target_key, version)
    colset = require_columns(store, target_key, head["colset_version"])
    columns = column_names(colset)
    rows = version_rows(store, target_key, head["version"])
    return {"notice": head["notice"], "target_key": target_key, "version": head["version"], "colset_version": head["colset_version"],
            "code_label": colset["body"].get("code_label") or "code", "columns": columns, "rows": rows}


# 스프레드시트가 수식으로 읽는 글 칸의 머리(CSV 수식 주입 — 반대 검토 L1). 이 글자로 시작해도 칸 전체가 수 글(-12.5 · -1,234 · +3e2)이면 값이다 —
# '-' 뒤가 숫자라는 것만으로는 수가 아니다(-1+1 · -0.5+cmd|… · -.5+HYPERLINK(…) 는 수식이다, 반대 검토 2차 3).
_FORMULA_HEAD = re.compile(r"^[=+\-@\t\r]")
# 수 글 — 부호 · 숫자(천 단위 쉼표 묶음 가능) · 소수 · 지수만. float() 는 inf · nan · 밑줄 · 앞뒤 빈칸도 받아 쓰지 않는다.
_PLAIN_NUMBER = re.compile(r"[+-]?(?:\d+(?:,\d{3})*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", re.ASCII)


def formula_guard(value: Any) -> tuple[Any, bool]:
    """수식으로 읽힐 글 칸이면 앞에 ' 를 붙인다 — (칸, 붙였나). 수 · 참거짓 · 수 글('-12.5')은 그대로다."""
    if isinstance(value, str) and _FORMULA_HEAD.match(value) and _number_text(value) is None:
        return "'" + value, True
    return value, False


def _number_text(value: str) -> float | None:
    if not _PLAIN_NUMBER.fullmatch(value):
        return None
    return float(value.replace(",", ""))


def table_csv(table: Mapping[str, Any], codes: Sequence[str] | None = None, *, raw: bool = False) -> tuple[str, int]:
    """CSV 글과 막은 칸 수 — 첫 줄은 보안 문구(한 칸), 둘째 줄이 칸 머리(코드 칸 + 칸 정의 차례), 이어 코드 차례의 행. 빈 칸은 빈 글이다. `raw` 가
    아니면 수식으로 읽힐 글 칸(=, +, -, @, 탭 · CR 로 시작하는데 칸 전체가 수 글이 아닌 것) 앞에 ' 를 붙인다 — 원본 표와 바이트까지 견줄 때만 raw 다."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    guarded = 0

    def cell(value: Any) -> Any:
        nonlocal guarded
        if raw:
            return value
        value, hit = formula_guard(value)
        guarded += hit
        return value

    writer.writerow([table["notice"]])
    writer.writerow([cell(table["code_label"]), *(cell(c) for c in table["columns"])])
    for code in (codes if codes is not None else table["rows"]):
        cells = table["rows"][code]
        writer.writerow([code, *("" if cells.get(c) is None else cell(cells[c]) for c in table["columns"])])
    return buf.getvalue(), guarded


def table_json(table: Mapping[str, Any], codes: Sequence[str] | None = None) -> dict:
    """JSON — 첫 칸이 보안 문구(notice)다. 행은 {code, 칸: 값 …}(빈 칸은 null)."""
    picked = list(codes if codes is not None else table["rows"])
    return {"notice": table["notice"], "target_key": table["target_key"], "version": table["version"],
            "colset_version": table["colset_version"], "columns": table["columns"], "rows_n": len(table["rows"]),
            "rows": [{"code": code, **{c: table["rows"][code].get(c) for c in table["columns"]}} for code in picked]}


def note_export(store: Any, target_key: str, owner_sub: str, *, version: int, kind: str, rows_n: int, body: str,
                actor: str, template_version: int | None = None) -> str:
    """내보내기 기록 한 행(누가 어느 판을 어떤 꼴로 냈나 · 낸 글의 지문)."""
    export_id = "ex-" + new_uuid()[:24]
    store.execute("INSERT INTO rr_ledger_exports(export_id, target_key, owner_sub, version, kind, template_version, rows_n, sha256,"
                  " actor, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (export_id, target_key, owner_sub, version, kind, template_version, rows_n, sha256_hex(body), actor, now_epoch()))
    return export_id


def overview(store: Any, target_key: str) -> dict:
    """대상의 원장 한눈 — 틀 종류별 판 · 판정표 판 목록 · 판에 쓰지 않은 층 · 근거 묶음 · 숫자 원장 수 · 최근 내보내기."""
    templates = {}
    for kind in TEMPLATE_KINDS:
        rows = store.query("SELECT version, created_at FROM rr_ledger_templates WHERE target_key = ? AND kind = ? ORDER BY version",
                           (target_key, kind))
        templates[kind] = {"versions": [r["version"] for r in rows], "latest": rows[-1]["version"] if rows else None}
    versions = [{k: r[k] for k in ("version", "based_on", "colset_version", "rows_n", "grade_changed_n", "created_by", "created_at")}
                for r in store.query("SELECT * FROM rr_ledger_versions WHERE target_key = ? ORDER BY version", (target_key,))]
    used = {x["layer_id"] for r in store.query("SELECT layers_json FROM rr_ledger_versions WHERE target_key = ?", (target_key,))
            for x in json.loads(r["layers_json"] or "[]")}
    # 층의 행 · 칸 수는 SQLite 가 센다 — 층마다 행 글 전부를 파이썬으로 풀지 않는다(반대 검토 L3).
    layers = [{"layer_id": r["layer_id"], "target_key": r["target_key"], "name": r["name"], "order": r["layer_order"],
               "source_file": r["source_file"], "origin": r["origin"], "colset_version": r["colset_version"], "rows_n": r["rows_n"],
               "cells_n": r["cells_n"], "rows_hash": r["rows_hash"], "created_by": r["created_by"], "created_at": r["created_at"],
               "used": r["layer_id"] in used}
              for r in store.query(
                  "SELECT l.layer_id, l.target_key, l.name, l.layer_order, l.source_file, l.origin, l.colset_version, l.rows_hash,"
                  " l.created_by, l.created_at, (SELECT COUNT(*) FROM json_each(l.rows_json)) AS rows_n,"
                  " (SELECT COUNT(*) FROM json_each(l.rows_json) AS r, json_each(r.value)) AS cells_n"
                  " FROM rr_ledger_layers l WHERE l.target_key = ? ORDER BY l.created_at, l.layer_order", (target_key,))]
    bundles = [dict(r) for r in store.query(
        "SELECT bundle_id, version, fingerprint, items_n, total_chars, masked_n, created_at FROM rr_evidence_bundles"
        " WHERE target_key = ? ORDER BY created_at, bundle_id", (target_key,))]
    numbers_n = store.query_one("SELECT COUNT(*) AS n FROM rr_ledger_numbers WHERE target_key = ?", (target_key,))["n"]
    forbidden_n = store.query_one("SELECT COUNT(*) AS n FROM rr_ledger_forbidden WHERE target_key = ?", (target_key,))["n"]
    exports = [dict(r) for r in store.query(
        "SELECT export_id, version, kind, template_version, rows_n, actor, created_at FROM rr_ledger_exports WHERE target_key = ?"
        " ORDER BY created_at DESC, export_id LIMIT 20", (target_key,))]
    return {"target_key": target_key, "templates": templates, "versions": versions, "latest_version": versions[-1]["version"]
            if versions else None, "layers": layers, "bundles": bundles, "numbers_n": numbers_n, "forbidden_n": forbidden_n,
            "recent_exports": exports}
