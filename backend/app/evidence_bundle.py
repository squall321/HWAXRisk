# 심의 근거 묶음(RK-02) — 판정표 판의 행을 엔진 근거 항목 꼴로(색인이 늘 맨 앞) · 칸별 상한 · 개인정보 가림 · 엔진 상한 거절 · 지문
"""HWAXPortal docs/request-1117 RK-02 · contracts.md §1.

- 항목 꼴은 엔진 근거 항목 그대로 `{source, tool, args, result, key}` — 본문은 `result` 하나에, `key` 는 `[A-Za-z0-9_.-]{1,24}`.
- 맨 앞 항목은 늘 색인 — 실은 행 코드 전부 · 판 · 칸 정의 판 · 묶음 id · 본문 지문과 '이 목록 밖의 행은 이 근거에 싣지 않았다(없다는 뜻이
  아니다)' 한 줄(일부 행만 뽑으면 좌석이 없는 행을 '없음' 으로 읽었다 — 요청서 함정).
- 칸 하나 = 근거 항목 하나다. 틀(`{name, caps{칸: 자}, total_cap}`)의 칸은 칸 정의에 등록된 이름만 받는다 — 근거 칸 이름은 중립이어야 하고(칸 이름에
  판정을 쓰면 좌석이 인용했다) 칸 정의가 판정 낱말을 받지 않는다(ledger._JUDGEMENT_RE). 항목 key 는 기계 이름(`b<id6>.f01`)이다.
- 칸 글은 코드 한 줄에 값 하나(`R-001 | 값`)이고 값 안의 줄바꿈은 ' ⏎ ' 로 접는다 — 행 수 = 줄 수. 빈 값은 '(빈 칸)' 으로 적는다(잘림과 가른다).
  등급 · 유형 · 주의 · 판정 축 칸은 표기 규칙(labels)의 표시 글로 적는다(RK-07).
- 칸 상한은 그 항목 글 전체(머리 · 잘림 안내 포함)의 자수다. 틀 차례로 채우고 합 상한(total_cap)이 남은 만큼만 다음 칸에 준다. 잘린 칸은 실리지
  않은 코드를 안내 줄에 적는다(값이 없다는 뜻이 아니다).
- 엔진 상한(항목 수 · 합 자수 — config.bundle_limits)을 넘으면 만들지 않고 422(넘은 값 · 상한). 합 자수는 항목 `result` 글자 수의 합(색인 포함)이다.
- 지문 = sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) 의 hex(contracts §1). 색인은 자기 지문을 담을 수
  없어 '본문 지문'(색인 뒤 항목들의 같은 셈)을 싣는다.
- 묶음 id 는 eb_ 머리이고 만들기 · 받기 답에 인용 형식 cite(contracts §5 C1 — source_kind risk_bundle)가 붙는다.
"""
from __future__ import annotations

import gzip
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app import config, labels, ledger, pii
from app.common import canonical_json, now_epoch, sha256_hex
from app.errors import AppError

TOOL = "risk_get_evidence_bundle"
# 인용 형식(contracts §5 C1 — 플랫폼 공용) — 묶음마다 cite 를 싣는다. source_kind 는 엔진 DL-01 ref.kind 와 같은 낱말이고, id 머리는 보고 묶음(rb_)과
# 헷갈리지 않게 eb_ 다.
SOURCE_PLATFORM = "hwax_risk"
SOURCE_KIND = "risk_bundle"
ID_PREFIX = "eb_"
KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,24}$")
TEMPLATE_NAME_MAX = 64
CAP_MAX = 150_000
INDEX_TAIL = "이 목록 밖의 행은 이 근거에 싣지 않았다(없다는 뜻이 아니다)."
EMPTY_CELL = "(빈 칸)"
NEWLINE_MARK = " ⏎ "
OMITTED_SHOWN = 10


def fingerprint(evidence: Sequence[Mapping[str, Any]]) -> str:
    """contracts §1 의 지문 — 엔진이 펼친 뒤 같은 식으로 다시 재어 '차이 0' 을 본다."""
    return sha256_hex(json.dumps(list(evidence), ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _template(raw: Any, columns: Sequence[str]) -> dict:
    if not isinstance(raw, Mapping) or set(raw) - {"name", "caps", "total_cap"}:
        raise ledger._bad("template 은 {name, caps{칸: 자}, total_cap} 이다.")
    name = ledger._text(raw.get("name"), "template.name", max_len=TEMPLATE_NAME_MAX)
    caps = raw.get("caps")
    if not isinstance(caps, Mapping) or not caps:
        raise ledger._bad("template.caps 는 {칸: 자} 이다(한 칸 이상).")
    unknown = [c for c in caps if c not in columns]
    if unknown:
        raise AppError("bundle_unknown_fields", f"틀의 칸이 칸 정의에 없다 — {unknown[:20]}. 근거 칸은 칸 정의에 등록된 이름만 쓴다"
                       "(칸 이름은 중립 낱말이어야 한다).", 422, detail={"unknown_fields": unknown})
    for col, cap in caps.items():
        if not isinstance(cap, int) or isinstance(cap, bool) or not 1 <= cap <= CAP_MAX:
            raise ledger._bad(f"template.caps[{col!r}] 는 1 ~ {CAP_MAX:,} 자 정수다.")
    total = raw.get("total_cap")
    if not isinstance(total, int) or isinstance(total, bool) or total < 1:
        raise ledger._bad("template.total_cap 은 1 이상 정수다.")
    return {"name": name, "caps": dict(caps), "total_cap": total}


def _ordered(tpl: Mapping[str, Any]) -> dict:
    """틀의 칸 차례를 지키는 꼴 — caps 를 [[칸, 자] …] 로(정규 JSON 은 객체 열쇠를 정렬해 차례를 잃는다 — 차례가 항목 key f01 … 과 합 상한 나누기를
    정한다, 반대 검토 M4)."""
    return {"name": tpl["name"], "caps": [[col, cap] for col, cap in tpl["caps"].items()], "total_cap": tpl["total_cap"]}


def _cell_text(value: Any, axis: str | None) -> str:
    if ledger.is_empty(value):
        return EMPTY_CELL
    shown, _ = labels.label_value(axis, value)
    text = shown if isinstance(shown, str) else canonical_json(shown)
    # 한 줄에 코드 하나 — 줄을 가르는 글자 전부(\n · \r · \v · \f · \x1c ~ \x1e · \x85 · \u2028 · \u2029 — str.splitlines)를 접는다(반대 검토 L4).
    # 끝의 줄바꿈도 표지로 남긴다 — splitlines 는 끝의 빈 줄을 버려 'a\n' 과 'a' 가 같은 글이 되었다(반대 검토 2차 8).
    if not text:
        return text
    lines = text.splitlines()
    folded = NEWLINE_MARK.join(lines)
    return folded + NEWLINE_MARK if text.splitlines(keepends=True)[-1] != lines[-1] else folded


def _pack(header: str, lines: list[tuple[str, str]], cap: int) -> tuple[str, list[str]]:
    """머리 + 코드 줄들을 cap 자 안에 넣는다 — (글, 실리지 않은 코드). 길이는 줄 길이의 누적 합으로 재고(행이 많아도 한 번 훑는다), 안내 줄까지
    들어가는 가장 많은 앞 줄을 싣는다. 머리 + 안내만으로도 넘으면 cap 에서 자른다."""
    def note(keep: int) -> str:
        left = len(lines) - keep
        shown = ", ".join(code for code, _ in lines[keep:keep + OMITTED_SHOWN]) + (
            f" 외 {left - OMITTED_SHOWN}개" if left > OMITTED_SHOWN else "")
        return f"… 이 칸은 상한 {cap:,}자에서 잘렸다 — 실리지 않은 코드 {left}개: {shown}. 값이 없다는 뜻이 아니다."

    prefix = [len(header)]
    for _, text in lines:
        prefix.append(prefix[-1] + 1 + len(text))
    if prefix[-1] <= cap:
        return "\n".join([header, *(text for _, text in lines)]), []
    for keep in range(len(lines) - 1, -1, -1):
        tail = note(keep)
        if prefix[keep] + 1 + len(tail) <= cap:
            return "\n".join([header, *(text for _, text in lines[:keep]), tail]), [code for code, _ in lines[keep:]]
    text = "\n".join([header, note(0)])
    return text[:cap], [code for code, _ in lines]


def build(store: Any, target_key: str, owner_sub: str, *, version: int | None, codes: Sequence[str] | None, template: Any,
          mask: bool = True, actor: str, cfg: Any = None) -> dict:
    if mask is not True:
        # 사용자 결정(11-17) — 게이트웨이가 묶음 받기를 제 가림에서 빼므로(가림이 묶음 글을 고쳐 엔진의 지문 대조가 깨졌다) 묶음은 이 앱이 늘 가린다.
        raise AppError("bundle_mask_required", "근거 묶음은 늘 개인정보를 가린다 — 가림을 끌 수 없다(mask=false 는 받지 않는다, 사용자 결정 11-17).",
                       422, detail={"mask": mask})
    head = ledger.version_head(store, target_key, version)
    version = int(head["version"])
    colset = ledger.require_columns(store, target_key, head["colset_version"])
    defs = {c["name"]: c for c in colset["body"]["columns"]}
    tpl = _template(template, list(defs))
    rows = ledger.version_rows(store, target_key, version)
    if codes is None:
        picked = list(rows)
    else:
        if not isinstance(codes, (list, tuple)) or not codes:
            raise ledger._bad("codes 는 코드 목록이다(비우면 그 판의 행 전부).")
        unknown = [c for c in codes if c not in rows]
        if unknown:
            raise AppError("bundle_unknown_codes", f"그 판에 없는 코드 — {unknown[:20]}.", 422, detail={"unknown_codes": unknown})
        picked = sorted(dict.fromkeys(codes), key=ledger.code_sort_key)
    inputs = {"target_key": target_key, "version": version, "colset_version": colset["version"], "rows_hash": head["rows_hash"],
              "codes": picked, "template": _ordered(tpl), "mask": True}
    inputs_hash = sha256_hex(canonical_json(inputs))
    bundle_id = ID_PREFIX + inputs_hash[:24]
    same = store.query_one("SELECT * FROM rr_evidence_bundles WHERE bundle_id = ?", (bundle_id,))
    if same is not None:
        return {**_build_view(same), "created": False}

    short = bundle_id[len(ID_PREFIX):len(ID_PREFIX) + 6]
    total_budget = tpl["total_cap"]
    masked_n = 0
    fields: list[dict] = []
    per_field: dict[str, dict] = {}
    omitted_fields: list[str] = []
    for n, (col, cap) in enumerate(tpl["caps"].items(), start=1):
        key = f"b{short}.f{n:02d}"
        axis = defs[col].get("axis")
        lines = []
        for code in picked:
            text = _cell_text(rows[code].get(col), axis)
            text, hit = pii.mask_text(text)
            masked_n += hit
            lines.append((code, f"{code} | {text}"))
        header = f"[판정표 칸 {n:02d}] {col} — 판 v{version} · 행 {len(picked)}개(코드 차례, 한 줄에 코드 하나)"
        room = min(cap, total_budget)
        if room < len(header) + 1:
            omitted_fields.append(col)
            per_field[col] = {"key": None, "chars": 0, "truncated": True, "cap": cap, "omitted": True, "codes_cut": len(picked)}
            continue
        text, left = _pack(header, lines, room)
        total_budget -= len(text)
        fields.append({"source": f"리스크 앱 근거 묶음 {bundle_id} · 판정표 v{version} · 칸 {n:02d} '{col}' · 행 {len(picked)}개",
                       "tool": TOOL, "args": {"bundle_id": bundle_id, "part": f"f{n:02d}"}, "result": text, "key": key})
        per_field[col] = {"key": key, "chars": len(text), "truncated": bool(left), "cap": cap, "codes_cut": len(left)}
    body_fp = fingerprint(fields)
    index_lines = [
        "[근거 묶음 색인 — 이 묶음에 실은 것 전부]",
        f"묶음 {bundle_id} · 대상 {target_key} · 판정표 판 v{version} · 칸 정의 판 c{colset['version']} · 틀 '{tpl['name']}'",
        f"본문 지문(색인 뒤 항목 {len(fields)}개) sha256 {body_fp}",
        f"실은 행 {len(picked)}개(코드 차례): " + ", ".join(picked),
        "실은 칸 " + str(len(fields)) + "개: " + " · ".join(
            f"{v['key']} '{c}' {v['chars']:,}자" + (f"(상한에서 잘림 — 실리지 않은 코드 {v['codes_cut']}개)" if v["truncated"] else "")
            for c, v in per_field.items() if not v.get("omitted")),
    ]
    if omitted_fields:
        index_lines.append("합 상한이 모자라 싣지 못한 칸: " + " · ".join(f"'{c}'" for c in omitted_fields) + "(값이 없다는 뜻이 아니다).")
    index_lines.append("[표기] 등급은 [등급 A조] 꼴 · 증거 유형은 유형① 꼴 · 주의 등급은 주의 A 꼴 · 판정은 SP 판정 키(VRD-COND 꼴)로 적었다."
                       + " 개인정보 꼴(메일 · 전화 · 사설 IP · 주민번호 · 사번)은 [가림:…] 으로 가렸다(묶음은 늘 가린다 — 끌 수 없다).")
    index_lines.append(INDEX_TAIL)
    index = {"source": f"리스크 앱 근거 묶음 {bundle_id} · 판정표 v{version} · 색인", "tool": TOOL,
             "args": {"bundle_id": bundle_id, "part": "index"}, "result": "\n".join(index_lines), "key": f"b{short}.idx"}
    evidence = [index, *fields]
    assert all(KEY_RE.fullmatch(item["key"]) for item in evidence)
    items_n = len(evidence)
    total_chars = sum(len(item["result"]) for item in evidence)
    limits = config.bundle_limits(cfg)
    if items_n > limits["items"]:
        raise AppError("bundle_too_many_items", f"근거 항목 {items_n}개가 엔진 상한 {limits['items']}개를 넘는다 — 칸을 줄인다.", 422,
                       detail={"items": items_n, "limit": limits["items"], "limits": limits})
    if total_chars > limits["chars"]:
        raise AppError("bundle_too_large", f"근거 합 {total_chars:,}자가 엔진 상한 {limits['chars']:,}자를 넘는다 — 틀의 상한이나 행을 줄인다.",
                       422, detail={"chars": total_chars, "limit": limits["chars"], "limits": limits})
    fp = fingerprint(evidence)
    check = labels.scan_summary([item["result"] for item in evidence])
    meta = {"per_field": per_field, "omitted_fields": omitted_fields, "label_check": check, "limits": limits}
    # 같은 입력을 둘이 함께 만들면 같은 id 다 — 늦은 쪽은 먼저 선 행을 돌려받는다(INSERT OR IGNORE).
    store.execute("INSERT OR IGNORE INTO rr_evidence_bundles(bundle_id, target_key, owner_sub, version, colset_version, inputs_hash, template_json,"
                  " codes_json, evidence_gz, fingerprint, items_n, total_chars, per_field_json, masked_n, created_by, created_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (bundle_id, target_key, owner_sub, version, colset["version"], inputs_hash, canonical_json({**_ordered(tpl), "mask": True}),
                   canonical_json(picked), gzip.compress(canonical_json(evidence).encode("utf-8"), mtime=0), fp, items_n, total_chars,
                   canonical_json(meta), masked_n, actor, now_epoch()))
    return {**_build_view(store.query_one("SELECT * FROM rr_evidence_bundles WHERE bundle_id = ?", (bundle_id,))), "created": True}


def cite(row: Mapping[str, Any]) -> dict:
    """인용 형식(C1) — {source_platform, source_kind, source_id, source_version(판정표 판/칸 정의 판), scope(대상 · 실은 코드)}."""
    return {"source_platform": SOURCE_PLATFORM, "source_kind": SOURCE_KIND, "source_id": row["bundle_id"],
            "source_version": f"v{row['version']}/c{row['colset_version']}",
            "scope": {"target_key": row["target_key"], "codes": json.loads(row["codes_json"] or "[]")}}


def _build_view(row: Mapping[str, Any]) -> dict:
    """만들기 답(contracts §1) — {bundle_id, fingerprint, items_n, total_chars, per_field{칸: {chars, truncated}}, masked_n, limits} 와 덤."""
    meta = json.loads(row["per_field_json"] or "{}")
    return {"bundle_id": row["bundle_id"], "target_key": row["target_key"], "version": row["version"],
            "colset_version": row["colset_version"], "fingerprint": row["fingerprint"], "items_n": row["items_n"],
            "total_chars": row["total_chars"], "per_field": meta.get("per_field") or {}, "masked_n": row["masked_n"],
            "limits": meta.get("limits") or config.bundle_limits(), "omitted_fields": meta.get("omitted_fields") or [],
            "codes_n": len(json.loads(row["codes_json"] or "[]")), "label_check": meta.get("label_check"), "cite": cite(row),
            "created_by": row["created_by"], "created_at": row["created_at"]}


def bundle_row(store: Any, bundle_id: str) -> dict | None:
    row = store.query_one("SELECT * FROM rr_evidence_bundles WHERE bundle_id = ?", (bundle_id,))
    return None if row is None else dict(row)


def evidence_of(row: Mapping[str, Any]) -> list[dict]:
    return json.loads(gzip.decompress(row["evidence_gz"]).decode("utf-8"))


def payload(row: Mapping[str, Any]) -> dict:
    """받기 답(contracts §1) — `evidence` 를 고치지 않고 deliberate_start(evidence=…) 에 넣는다."""
    return {"bundle_id": row["bundle_id"], "target_key": row["target_key"], "version": row["version"],
            "fingerprint": row["fingerprint"], "cite": cite(row), "evidence": evidence_of(row)}
