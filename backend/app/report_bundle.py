# 판정표 → 보고 묶음(RK-05) — 코드마다 facts(등록된 틀의 키 전부 — 빈 키는 null 과 까닭) · 그림 참조 · 출처 층 · 숫자 원장 참조를 묶는다(그리기는 ReportArchive 몫)
"""HWAXPortal docs/request-1117 RK-05 · contracts.md §4 · §5 C1.

- facts 틀은 데이터다(context-notes R-2) — 대상마다 `facts` 틀({keys: [{key, from}]})을 판으로 등록하고, 키는 점으로 내려간다(cad.use → {cad: {use}}).
  from 은 원장 칸 이름이거나 @code · @version · @sources · @figures · @numbers, null 은 '대응 없음' 이다.
- 키는 전부 채운다 — 값이 없으면 null 이고 null_reasons[키] 에 까닭(대응 없음 · 그 코드의 칸이 비었다 · 그림 · 출처 · 수가 없다)이다.
- 표기 규칙(RK-07) — 표기 축이 있는 칸의 값은 표시 글로 적고, 글 전체를 단독 대문자 A ~ J 검사(label_check)에 건다.
- 출처는 판 사슬(이 판 → 기준 판 → …)의 덮은 칸 기록(rr_ledger_cells)에서 그 코드를 덮은 층(이름 · 차례 · 원천 파일 · 판)이다. 숫자 원장 참조는 그
  코드의 칸 글에 나온 수와 값이 같은 숫자 행이다.
- 묶음 id 는 rb_ 머리의 내용 지문이고(같은 판 · 같은 틀이면 같은 id) 인용 형식 cite(source_kind risk_report_bundle)가 붙는다. 내보낼 때마다 기록
  (rr_ledger_exports kind report_bundle)이 남는다.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app import labels, ledger, ledger_numbers
from app.common import canonical_json, sha256_hex
from app.errors import AppError

SOURCE_KIND = "risk_report_bundle"
ID_PREFIX = "rb_"
_FIGURE_SPLIT = re.compile(r"[;,\n]+")


def _set(tree: dict, key: str, value: Any) -> None:
    parts = key.split(".")
    node = tree
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _chain(store: Any, target_key: str, version: int) -> list[int]:
    out, seen, current = [], set(), version
    while current is not None and current not in seen:
        seen.add(current)
        out.append(current)
        row = store.query_one("SELECT based_on FROM rr_ledger_versions WHERE target_key = ? AND version = ?", (target_key, current))
        current = None if row is None or row["based_on"] is None else int(row["based_on"])
    return out


def _sources(store: Any, target_key: str, versions: Sequence[int]) -> dict[str, list[dict]]:
    """코드 → 그 코드를 덮은 층(판 사슬 전부, 판 · 차례 순, 같은 층은 한 번)."""
    out: dict[str, list[dict]] = {}
    seen: set[tuple[str, int, str]] = set()
    marks = ",".join("?" for _ in versions)
    for row in store.query(f"SELECT version, layer_id, layer_name, layer_order, source_file, code FROM rr_ledger_cells"
                           f" WHERE target_key = ? AND version IN ({marks}) ORDER BY version, layer_order, seq", (target_key, *versions)):
        key = (row["code"], row["version"], row["layer_id"])
        if key in seen:
            continue
        seen.add(key)
        out.setdefault(row["code"], []).append({"version": row["version"], "layer": row["layer_name"], "order": row["layer_order"],
                                                "source_file": row["source_file"], "layer_id": row["layer_id"]})
    return out


def _number_refs(cells: Mapping[str, Any], numbers: Sequence[Mapping[str, Any]]) -> list[dict]:
    """칸 글에 나온 수와 값이 같은 숫자 행 — 코드 · 키 꼴 낱말 속 숫자는 수로 보지 않는다(점검과 같은 규칙)."""
    found: set = set()
    for value in cells.values():
        if isinstance(value, bool) or value is None:
            continue
        text = str(value)
        spans = [m.span(1) for m in ledger_numbers._ID_RE.finditer(text)]
        for m in ledger_numbers._NUM_RE.finditer(text):
            if not any(s <= m.start(1) < e for s, e in spans):
                number = ledger_numbers.to_decimal(m.group(1))
                if number is not None:
                    found.add(number)
    return [{k: n[k] for k in ("name", "revision", "value_text", "unit", "metric_key", "source_file", "line")}
            for n in numbers if ledger_numbers.to_decimal(n["value_text"]) in found]


def build(store: Any, target_key: str, *, version: int | None, template_version: int | None = None) -> dict:
    head = ledger.version_head(store, target_key, version)
    version = int(head["version"])
    colset = ledger.require_columns(store, target_key, head["colset_version"])
    defs = {c["name"]: c for c in colset["body"]["columns"]}
    tpl = ledger.template(store, target_key, "facts", template_version)
    if tpl is None:
        raise AppError("ledger_facts_template_missing", "이 대상에 facts 틀이 없다 — 먼저 facts 틀(키 목록 · 원장 칸 대응)을 등록한다.", 409,
                       detail={"fix": "risk_ledger_put_template(kind='facts') · PUT /api/targets/{key}/ledger/templates/facts"})
    keys = tpl["body"]["keys"]
    rows = ledger.version_rows(store, target_key, version)
    sources = _sources(store, target_key, _chain(store, target_key, version))
    numbers = ledger_numbers.current(store, target_key)["numbers"]
    figure_cols = [c["name"] for c in colset["body"]["columns"] if c.get("figure")]
    facts_out: list[dict] = []
    all_figures: list[dict] = []
    all_numbers: dict[tuple, dict] = {}
    nulls = 0
    for code, cells in rows.items():
        facts: dict[str, Any] = {}
        reasons: dict[str, str] = {}
        figures = [{"code": code, "column": col, "ref": ref.strip()} for col in figure_cols
                   for ref in _FIGURE_SPLIT.split(str(cells.get(col) or "")) if ref.strip()]
        refs = _number_refs(cells, numbers)
        all_figures.extend(figures)
        for ref in refs:
            all_numbers[(ref["name"], ref["revision"])] = ref
        for item in keys:
            source, value, why = item["from"], None, None
            if source is None:
                why = "facts 틀에 원장 칸 대응이 없다"
            elif source == "@code":
                value = code
            elif source == "@version":
                value = f"v{version}"
            elif source == "@sources":
                value = sources.get(code) or None
                why = None if value else "이 코드를 덮은 층 기록이 없다"
            elif source == "@figures":
                value = [f["ref"] for f in figures] or None
                why = None if value else ("칸 정의에 그림 칸이 없다" if not figure_cols else "그림 칸이 이 코드에서 비었다")
            elif source == "@numbers":
                value = refs or None
                why = None if value else ("숫자 원장이 비었다" if not numbers else "이 코드의 칸 글에 숫자 원장의 값이 나오지 않는다")
            elif source not in defs:
                why = f"facts 틀이 가리키는 원장 칸 {source!r} 이 이 판의 칸 정의(c{colset['version']})에 없다"
            elif ledger.is_empty(cells.get(source)):
                why = f"원장 칸 '{source}' 이 이 코드에서 비었다"
            else:
                value, _ = labels.label_value(defs[source].get("axis"), cells[source])
            if value is None:
                nulls += 1
                reasons[item["key"]] = why or "값이 없다"
            _set(facts, item["key"], value)
        facts_out.append({"code": code, "facts": facts, "null_reasons": reasons})
    check = labels.check_summary(labels.check_obj([f["facts"] for f in facts_out]))
    all_sources = sorted({(s["version"], s["order"], s["layer"], s["source_file"] or "") for v in sources.values() for s in v})
    body = {"notice": head["notice"], "target_key": target_key, "version": version, "colset_version": colset["version"],
            "template_version": tpl["version"], "labels_version": labels.load_labels().get("labels_version"), "facts": facts_out,
            "figures": all_figures, "sources": [{"version": v, "order": o, "layer": layer, "source_file": f or None}
                                                for v, o, layer, f in all_sources],
            "numbers": sorted(all_numbers.values(), key=lambda n: (n["name"], n["revision"]))}
    digest = sha256_hex(canonical_json(body))
    bundle_id = ID_PREFIX + digest[:24]
    out = {"notice": body["notice"], "report_bundle_id": bundle_id,
           "cite": {"source_platform": "hwax_risk", "source_kind": SOURCE_KIND, "source_id": bundle_id,
                    "source_version": f"v{version}/c{colset['version']}",
                    "scope": {"target_key": target_key, "codes": list(rows)}},
           **{k: v for k, v in body.items() if k != "notice"},
           "counts": {"codes": len(rows), "keys": len(keys), "nulls": nulls, "figures": len(all_figures), "numbers": len(all_numbers)},
           "label_check": check, "sha256": digest}
    return out
