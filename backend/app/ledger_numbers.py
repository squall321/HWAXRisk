# 숫자 원장과 금지값 점검(RK-04) — 숫자 행(이름 · 값 · 단위 · 정의 · 리비전 · 출처 · 줄 · 지표 키)과 코드별 금지값을 두고, 글 · 근거 묶음의 수를 원장과 대조한다
"""HWAXPortal docs/request-1117 RK-04.

- 숫자 원장 · 금지값은 대상마다 통째로 갈아 쓴다(PUT) — 같은 몸이면 바뀐 것이 없다(changed false).
- 점검은 글 하나 또는 근거 묶음 하나(bundle_id — 칸 항목의 'R-001 | 값' 줄은 그 줄의 코드를 안다)를 읽어 셋을 센다 — 원장에 없는 수(not_in_ledger) ·
  금지값 쓰임(forbidden — 코드 '*' 는 모든 코드, 아니면 그 코드의 줄에서만) · 단위 불일치(unit_mismatch — 원장의 같은 값에 다른 단위). 위치는
  offset · line · col 과 앞뒤 글이다.
- 게이트웨이 verify_answer 는 소수와 100 이상만 본다 — 여기서는 작은 정수(2 · 13)도 센다. 코드 · 키 꼴 낱말(R-001 · MET-STRESS · U1001) 속 숫자는 수로
  세지 않고, 대신 id 꼴로 본다 — 원장의 코드 · 지표 키와 같은 머리(R- · MET-)인데 원장에 없는 id 는 unknown_ids 다(없는 행을 가리킨다).
- 수는 Decimal 로 견준다(0.650 = 0.65, 1,234 = 1234). 단위는 대소문자 · µ/μ/u 를 맞춰 견준다.
"""
from __future__ import annotations

import bisect
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from app import evidence_bundle, ledger
from app.common import canonical_json, now_epoch, sha256_hex
from app.errors import AppError

NUMBERS_MAX = 5000
FORBIDDEN_MAX = 5000
TEXT_MAX = 2_000_000
FINDINGS_SHOWN_MAX = 500
CONTEXT_CHARS = 20
NAME_MAX = 120
DEFINITION_MAX = 1000
METRIC_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
# 단위 — 수 바로 뒤(빈칸 하나까지)에 붙는 낱말. 길이 · 힘 · 응력 · 질량 · 가속 · 백분율 · 온도 · 시간 · 진동수 · 전기 · 에너지 · 데시벨.
_UNITS = ("mm", "cm", "um", "µm", "μm", "nm", "m", "MPa", "GPa", "kPa", "Pa", "kN", "N", "mg", "kg", "g", "G", "%", "℃", "°C", "ms",
          "us", "µs", "s", "kHz", "MHz", "GHz", "Hz", "mV", "kV", "V", "mA", "A", "mW", "kW", "W", "mJ", "kJ", "J", "dB", "K")
_UNIT_ALT = "|".join(re.escape(u) for u in sorted(_UNITS, key=len, reverse=True))
# id 꼴 — 글자로 시작해 하이픈 · 밑줄로 이은 마디(R-001 · MET-STRESS · PART-A)이거나 글자 + 숫자(U1001 · DV1).
_ID_RE = re.compile(r"(?<![A-Za-z0-9_.-])([A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+|[A-Za-z]+[0-9][A-Za-z0-9]*)(?![A-Za-z0-9_-])")
# 수 — 한 번 훑기(선형)로 자른다. 옛 정규식(천 단위 묶음을 되짚는 꼴)은 '111,111,…' 글에서 길이의 제곱으로 느려져 2백만 자 글이 서버를 붙들었다
# (반대 검토 H1). 숫자 · 쉼표 덩이를 소유 한정자로 한 번에 집고, 천 단위 묶음(1,234,567)인지는 파이썬이 가른다 — 묶음이 아니면 쉼표마다 따로 센
# 수다(1,2,3 → 1 · 2 · 3). 바로 뒤에 '.숫자' 가 이어지는 덩이(1.2.3 — 판 · 조항 번호)는 수가 아니다. 단위는 덩이 끝에서 따로 맞춘다.
_NUM_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_.])-?\d[\d,]*+(?:\.\d++)?+(?:[eE][-+]?\d++)?+")
_UNIT_AT_RE = re.compile(rf"\s?({_UNIT_ALT})(?![A-Za-z])")
_GROUPED_RE = re.compile(r"\d{1,3}(?:,\d{3})+")
_DOT_DIGIT_RE = re.compile(r"\.\d")
_TAIL_RE = re.compile(r"[.eE]")
_FAMILY_RE = re.compile(r"^([A-Za-z]+[-_]?)")


def numbers_in(text: str) -> Iterator[tuple[int, int, str, str | None]]:
    """글의 수를 차례로 — (값 시작, 단위까지 끝, 값 글, 단위). 값 글은 쓴 그대로(1,234.5 — to_decimal 이 쉼표를 뗀다)."""
    for m in _NUM_TOKEN_RE.finditer(text):
        end = m.end()
        if _DOT_DIGIT_RE.match(text, end):
            continue
        raw = m.group(0).rstrip(",")
        start = m.start()
        sign = "-" if raw.startswith("-") else ""
        body = raw[len(sign):]
        cut = _TAIL_RE.search(body)
        head, tail = (body[:cut.start()], body[cut.start():]) if cut else (body, "")
        if "," not in head or _GROUPED_RE.fullmatch(head):
            pieces = [(start, raw)]
        else:
            pieces, at = [], start + len(sign)
            parts = head.split(",")
            for n, part in enumerate(parts):
                if part:
                    text_part = (sign if n == 0 else "") + part + (tail if n == len(parts) - 1 else "")
                    pieces.append((at - (len(sign) if n == 0 else 0), text_part))
                at += len(part) + 1
        last_end = start + len(raw)
        unit_m = _UNIT_AT_RE.match(text, last_end)
        for n, (at, value) in enumerate(pieces):
            if n == len(pieces) - 1 and unit_m:
                yield at, unit_m.end(), value, unit_m.group(1)
            else:
                yield at, at + len(value), value, None


class _IdSpans:
    """id 꼴 낱말의 자리 — 수가 그 안에서 시작하는지를 이분 탐색으로 본다(수 × 낱말 짝을 다 보지 않는다)."""

    def __init__(self, spans: Sequence[tuple[int, int]]) -> None:
        self.starts = [s for s, _ in spans]
        self.ends = [e for _, e in spans]

    def covers(self, at: int) -> bool:
        i = bisect.bisect_right(self.starts, at) - 1
        return i >= 0 and at < self.ends[i]


def to_decimal(raw: Any) -> Decimal | None:
    if isinstance(raw, bool) or raw is None:
        return None
    text = str(raw).strip().replace(",", "")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def unit_key(unit: Any) -> str | None:
    if unit in (None, ""):
        return None
    return str(unit).strip().replace("µ", "u").replace("μ", "u").replace("°C", "℃").lower()


def _text(value: Any, field: str, max_len: int, *, required: bool = False) -> str | None:
    return ledger._text(value, field, max_len=max_len, required=required)


def _normalize(numbers: Any, forbidden: Any) -> tuple[list[dict], list[dict]]:
    if not isinstance(numbers, list) or len(numbers) > NUMBERS_MAX:
        raise ledger._bad(f"numbers 는 숫자 행 목록이다({NUMBERS_MAX:,}개까지).")
    if not isinstance(forbidden, list) or len(forbidden) > FORBIDDEN_MAX:
        raise ledger._bad(f"forbidden 은 금지값 목록이다({FORBIDDEN_MAX:,}개까지).")
    rows, seen = [], set()
    for i, item in enumerate(numbers):
        if not isinstance(item, Mapping) or set(item) - {"name", "value", "unit", "definition", "revision", "source_file", "line",
                                                           "metric_key"}:
            raise ledger._bad(f"numbers[{i}] 는 {{name, value, unit?, definition?, revision?, source_file?, line?, metric_key?}} 다.")
        name = _text(item.get("name"), f"numbers[{i}].name", NAME_MAX, required=True)
        value = item.get("value")
        if to_decimal(value) is None:
            raise ledger._bad(f"numbers[{i}].value 는 수다 — {value!r}.")
        revision = _text(item.get("revision"), f"numbers[{i}].revision", 64) or ""
        if (name, revision) in seen:
            raise ledger._bad(f"숫자 행 (이름, 리비전)이 겹친다 — {name!r} · {revision!r}.")
        line = item.get("line")
        if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
            raise ledger._bad(f"numbers[{i}].line 은 1 이상 정수다.")
        metric = item.get("metric_key")
        if metric is not None and (not isinstance(metric, str) or not METRIC_KEY_RE.fullmatch(metric)):
            raise ledger._bad(f"numbers[{i}].metric_key 는 지표 키 꼴이다(예 MET-STRESS) — {metric!r}.")
        seen.add((name, revision))
        rows.append({"name": name, "revision": revision, "value_text": str(value).strip(),
                     "unit": _text(item.get("unit"), f"numbers[{i}].unit", 16),
                     "definition": _text(item.get("definition"), f"numbers[{i}].definition", DEFINITION_MAX),
                     "source_file": _text(item.get("source_file"), f"numbers[{i}].source_file", ledger.SOURCE_FILE_MAX),
                     "line": line, "metric_key": metric})
    bans, seen_bans = [], set()
    for i, item in enumerate(forbidden):
        if not isinstance(item, Mapping) or set(item) - {"code", "value", "unit", "reason"}:
            raise ledger._bad(f"forbidden[{i}] 는 {{code, value, unit?, reason}} 다.")
        code = item.get("code")
        if code != "*":
            ledger.check_code(code, f"forbidden[{i}].code")
        value = item.get("value")
        if to_decimal(value) is None:
            raise ledger._bad(f"forbidden[{i}].value 는 수다 — {value!r}.")
        reason = _text(item.get("reason"), f"forbidden[{i}].reason", DEFINITION_MAX, required=True)
        key = (code, str(value).strip())
        if key in seen_bans:
            raise ledger._bad(f"금지값 (코드, 값)이 겹친다 — {key}.")
        seen_bans.add(key)
        bans.append({"code": code, "value_text": key[1], "unit": _text(item.get("unit"), f"forbidden[{i}].unit", 16), "reason": reason})
    return rows, bans


def put(store: Any, target_key: str, owner_sub: str, *, numbers: Any, forbidden: Any, actor: str) -> dict:
    """숫자 원장 · 금지값을 통째로 갈아 쓴다. 같은 몸이면 쓰지 않는다(changed false)."""
    rows, bans = _normalize(numbers, forbidden)
    want = sha256_hex(canonical_json({"numbers": sorted(rows, key=lambda r: (r["name"], r["revision"])),
                                      "forbidden": sorted(bans, key=lambda r: (r["code"], r["value_text"]))}))
    have = current(store, target_key)
    if have["hash"] == want:
        return {"target_key": target_key, "numbers_n": len(rows), "forbidden_n": len(bans), "hash": want, "changed": False}
    now = now_epoch()
    with store.tx():
        store.execute("DELETE FROM rr_ledger_numbers WHERE target_key = ?", (target_key,))
        store.execute("DELETE FROM rr_ledger_forbidden WHERE target_key = ?", (target_key,))
        store.executemany("INSERT INTO rr_ledger_numbers(target_key, name, revision, owner_sub, value_text, unit, definition, source_file,"
                          " line, metric_key, updated_by, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          [(target_key, r["name"], r["revision"], owner_sub, r["value_text"], r["unit"], r["definition"], r["source_file"],
                            r["line"], r["metric_key"], actor, now) for r in rows])
        store.executemany("INSERT INTO rr_ledger_forbidden(target_key, code, value_text, owner_sub, unit, reason, updated_by, updated_at)"
                          " VALUES (?,?,?,?,?,?,?,?)",
                          [(target_key, b["code"], b["value_text"], owner_sub, b["unit"], b["reason"], actor, now) for b in bans])
    return {"target_key": target_key, "numbers_n": len(rows), "forbidden_n": len(bans), "hash": want, "changed": True}


def current(store: Any, target_key: str) -> dict:
    numbers = [dict(r) for r in store.query(
        "SELECT name, revision, value_text, unit, definition, source_file, line, metric_key FROM rr_ledger_numbers WHERE target_key = ?"
        " ORDER BY name, revision", (target_key,))]
    forbidden = [dict(r) for r in store.query(
        "SELECT code, value_text, unit, reason FROM rr_ledger_forbidden WHERE target_key = ? ORDER BY code, value_text", (target_key,))]
    # put 의 지문과 같은 셈이다(같은 몸이면 갈아 쓰지 않는다).
    digest = sha256_hex(canonical_json({"numbers": numbers, "forbidden": forbidden}))
    return {"numbers": numbers, "forbidden": forbidden, "hash": digest}


# ---------------------------------------------------------------- 점검
def _segments_of_bundle(evidence: Sequence[Mapping[str, Any]]) -> Iterator[tuple[str, str | None, str]]:
    """근거 묶음 → (위치 이름, 줄의 코드, 줄 글) — 색인 · 칸 머리 · 잘림 안내 줄은 원장 값이 아니라 뺀다."""
    for item in evidence[1:]:
        lines = str(item.get("result") or "").split("\n")
        for n, line in enumerate(lines[1:], start=2):
            if line.startswith("… "):
                continue
            code, sep, value = line.partition(" | ")
            yield f"{item.get('key')}:{n}", code if sep else None, value if sep else line


def _segments_of_text(text: str, codes: set[str]) -> Iterator[tuple[str, str | None, str]]:
    """글 → 줄마다 (위치 이름, 그 줄에 나온 원장 코드 하나(여럿이면 첫 것), 줄 글) — 차례로 내 줄 목록을 통째로 들지 않는다."""
    start = 0
    n = 1
    while True:
        end = text.find("\n", start)
        line = text[start:] if end == -1 else text[start:end]
        found = next((m.group(1) for m in _ID_RE.finditer(line) if m.group(1) in codes), None)
        yield f"line:{n}", found, line
        if end == -1:
            return
        start, n = end + 1, n + 1


class _Findings:
    """점검이 찾은 것 — 수는 다 세고 행은 목록마다 앞 FINDINGS_SHOWN_MAX 개만 짓는다(반대 검토 M1 — 2백만 자 글이 백만 개 행 · 수백 MB 를
    지었다). `make` 는 실을 때만 부른다."""

    KEYS = ("not_in_ledger", "forbidden", "unit_mismatch", "unknown_ids")

    def __init__(self) -> None:
        self.rows: dict[str, list[dict]] = {k: [] for k in self.KEYS}
        self.n: dict[str, int] = {k: 0 for k in self.KEYS}

    def add(self, key: str, make: Callable[[], dict]) -> None:
        self.n[key] += 1
        if len(self.rows[key]) < FINDINGS_SHOWN_MAX:
            self.rows[key].append(make())


def check(store: Any, target_key: str, *, text: str | None = None, bundle_id: str | None = None, code: str | None = None) -> dict:
    if (text is None) == (bundle_id is None):
        raise ledger._bad("text · bundle_id 가운데 하나만 준다.")
    version = ledger.latest_version(store, target_key)
    if bundle_id is not None:
        row = evidence_bundle.bundle_row(store, bundle_id)
        if row is None or row["target_key"] != target_key:
            raise AppError("E404", f"근거 묶음을 찾을 수 없습니다 — {bundle_id}.", 404)
        version = int(row["version"])
        segments = _segments_of_bundle(evidence_bundle.evidence_of(row))
        source = {"kind": "bundle", "bundle_id": bundle_id, "version": version}
    else:
        if not isinstance(text, str) or len(text) > TEXT_MAX:
            raise ledger._bad(f"text 는 {TEXT_MAX:,}자 이하 글이다.")
        source = {"kind": "text", "chars": len(text)}
    codes = set(ledger.version_rows(store, target_key, version)) if version is not None else set()
    if text is not None:
        segments = _segments_of_text(text, codes)
    if code is not None:
        ledger.check_code(code, "code")
    ledger_now = current(store, target_key)
    values: dict[Decimal, list[dict]] = {}
    for n in ledger_now["numbers"]:
        values.setdefault(to_decimal(n["value_text"]), []).append(n)
    metric_keys = {n["metric_key"] for n in ledger_now["numbers"] if n["metric_key"]}
    known_ids = codes | metric_keys | {b["code"] for b in ledger_now["forbidden"] if b["code"] != "*"}
    families = {m.group(1) for k in known_ids for m in [_FAMILY_RE.match(k)] if m and m.group(1).endswith(("-", "_"))}
    bans: dict[Decimal, list[dict]] = {}
    for ban in ledger_now["forbidden"]:
        bans.setdefault(to_decimal(ban["value_text"]), []).append(ban)
    found = {"numbers": 0, "matched": 0}
    found_rows = _Findings()
    for where, line_code, line in segments:
        context_code = code or line_code
        id_spans = []
        for m in _ID_RE.finditer(line):
            id_spans.append(m.span(1))
            token = m.group(1)
            family = _FAMILY_RE.match(token)
            if family and family.group(1) in families and token not in known_ids:
                found_rows.add("unknown_ids", lambda m=m, token=token, family=family: _hit(
                    where, line, m.start(1), m.end(1), token=token, code=context_code, family=family.group(1)))
        inside = _IdSpans(id_spans)
        for start, end, raw, unit in numbers_in(line):
            if inside.covers(start):
                continue
            value = to_decimal(raw)
            if value is None:
                continue
            found["numbers"] += 1
            base = {"token": line[start:end].strip(), "value": raw, "unit": unit, "code": context_code,
                    "kind": "decimal" if ("." in raw or "e" in raw.lower()) else "integer"}
            same = values.get(value)
            if not same:
                found_rows.add("not_in_ledger", lambda start=start, end=end, base=base: _hit(where, line, start, end, **base))
            else:
                found["matched"] += 1
                units = {unit_key(n["unit"]) for n in same if n["unit"]}
                if unit and units and unit_key(unit) not in units:
                    found_rows.add("unit_mismatch", lambda start=start, end=end, base=base, same=same: _hit(where, line, start, end, **base, ledger=[
                        {"name": n["name"], "revision": n["revision"], "unit": n["unit"], "metric_key": n["metric_key"]} for n in same]))
            for ban in bans.get(value, ()):
                if ban["code"] != "*" and ban["code"] != context_code:
                    continue
                if ban["unit"] and unit and unit_key(ban["unit"]) != unit_key(unit):
                    continue
                found_rows.add("forbidden", lambda start=start, end=end, base=base, ban=ban: _hit(
                    where, line, start, end, **base, forbidden_code=ban["code"], reason=ban["reason"]))
    counts = {"numbers": found["numbers"], "matched": found["matched"], **found_rows.n}
    out = {"target_key": target_key, "source": source, "version": version, "ledger_hash": ledger_now["hash"],
           "numbers_in_ledger": len(ledger_now["numbers"]), "forbidden_in_ledger": len(ledger_now["forbidden"]), "counts": counts}
    for key, rows in found_rows.rows.items():
        out[key] = rows
        if found_rows.n[key] > len(rows):
            out[f"{key}_truncated"] = found_rows.n[key] - len(rows)
    return out


def _hit(where: str, line: str, start: int, end: int, **fields: Any) -> dict:
    col = start + 1
    return {**fields, "where": where, "col": col, "context": line[max(0, start - CONTEXT_CHARS):end + CONTEXT_CHARS]}
