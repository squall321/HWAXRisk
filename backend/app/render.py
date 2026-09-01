# 정규 표기(canonical text)·summary_text 코드 조립·판단어 린터 — plan §3.4(LLM 없음, 코드가 rr_state·rr_diff 에서 문자열을 짓는다)
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Any, Callable, Iterable, Sequence

__all__ = [
    "LEXICON_VERSION",
    "SUMMARY_MAX",
    "INJECTION_VERSION",
    "INJECTION_LEXICON",
    "SANITIZE_LIMITS",
    "sanitize_source_text",
    "injection_hit",
    "suspect_placeholder",
    "JUDGEMENT_LEXICON",
    "LINT_NEUTRAL_PATTERNS",
    "JudgementLintError",
    "quote_source",
    "strip_quoted",
    "mask_neutral",
    "lint_text",
    "assert_clean",
    "MINUS",
    "fmt_num",
    "fmt_signed",
    "fmt_pct",
    "fmt_value",
    "fmt_change",
    "fmt_label",
    "fmt_iface",
    "fmt_refs",
    "signal_text",
    "param_text",
    "event_text",
    "summarize",
    "render_summary",
]

LEXICON_VERSION = "lex-1.0"
SUMMARY_MAX = 2000

QUOTE_OPEN = "«"   # «
QUOTE_CLOSE = "»"  # »
MINUS = "−"        # − (정규 표기의 음수 부호)


# ---------------------------------------------------------------- 판단어 린터(plan §3.4.3)
# 항목은 {id, pattern, allow}. 매칭은 정규식 단위이고 allow 에 걸린 구간 안의 매치는 위반이 아니다.
JUDGEMENT_LEXICON: tuple[dict, ...] = (
    {"id": "L01", "pattern": r"위험", "allow": ()},
    {"id": "L02", "pattern": r"리스크", "allow": (r"리스크\s?심사", r"risk-review", r"hwax-risk")},
    {"id": "L03", "pattern": r"개선", "allow": ()},
    {"id": "L04", "pattern": r"악화", "allow": ()},
    {"id": "L05", "pattern": r"안전(?!율|계수|_factor)", "allow": (r"min_safety_factor", r"안전율", r"안전계수")},
    {"id": "L06", "pattern": r"문제", "allow": ()},
    {"id": "L07", "pattern": r"양호|불량|우수|열악|적절|부적절|바람직", "allow": ()},
    {"id": "L08", "pattern": r"취약|강건|튼튼|허약", "allow": ()},
    {"id": "L09", "pattern": r"심각|우려|경고(?!\s?코드)", "allow": (r"warning", r"WARNING")},
    {"id": "L10", "pattern": r"권장|권고|필요하|해야\s?한다|해야\s?함", "allow": (r"재검사 필요",)},
    {"id": "L11", "pattern": r"과다|과소|부족|충분", "allow": ()},
    {"id": "L12", "pattern": r"좋(다|은|아)|나쁘|나쁜", "allow": ()},
    {"id": "L13", "pattern": r"약화|강화|저하|향상|열화", "allow": ()},
    {"id": "L14", "pattern": r"결함|오류|실패|성공", "allow": (r"file_load_failed", r"failed", r"success")},
    {"id": "L15", "pattern": r"치명|중대|경미", "allow": (r"severity=(치명|중대|경미)",)},
    {"id": "L16", "pattern": r"OK|FAIL|PASS(?!_)", "allow": (r"pass=(true|false)", r"G\d\s(pass|fail)",
                                                              r"judgement=(OK|FAIL|PASS|WARNING|undetermined)")},
    # '결론 아님' 은 브리프 프레이밍 줄의 고정 문구다 — 결론을 금지하는 문장 자체가 걸리면 안 된다(plan §5.6.2).
    {"id": "L17", "pattern": r"추천|제안|판단|결론|평가", "allow": (r"상태 평가", r"평가어", r"평가 불가", r"결론\s?아님")},
)

# 린터가 보지 않는 구간(plan §3.4.3 — 원문 인용·참조·태그·도구/앱 id 는 검사 대상이 아니다).
LINT_NEUTRAL_PATTERNS: tuple[str, ...] = (
    QUOTE_OPEN + r"[^" + QUOTE_CLOSE + r"]*" + QUOTE_CLOSE,      # «원문 인용»
    r"\[[a-z]+:[^\]]*\]",                                        # 산문 표기의 참조 [c:…]
    r"(?<![A-Za-z0-9_])(?:p|e|c|d|sig|gate|rule|warn|narr|reg|card|rpt|inc|tool|name):[^\s\]]+",
    r"char:[a-z_]+:[A-Za-z0-9_]+",                               # 성격 통제 어휘 태그
    r"(?<![A-Za-z0-9_])x:[A-Za-z0-9_]+",                         # 자유 제안 태그
)

_LEX_COMPILED = tuple(
    {
        "id": item["id"],
        "pattern": re.compile(item["pattern"]),
        "allow": tuple(re.compile(a) for a in item["allow"]),
    }
    for item in JUDGEMENT_LEXICON
)
_NEUTRAL_COMPILED = tuple(re.compile(p) for p in LINT_NEUTRAL_PATTERNS)
_SECTION_TAG = re.compile(r"^\[([^\]]+)\]")


class JudgementLintError(Exception):
    """코드 생성 문장에 판단어가 섞였다 — 렌더러 결함이다(plan §3.4.3)."""

    def __init__(self, violations: list[dict], lexicon_version: str = LEXICON_VERSION) -> None:
        super().__init__(f"판단어 린터 위반 {len(violations)}건(lexicon {lexicon_version}).")
        self.violations = violations
        self.lexicon_version = lexicon_version


# ---------------------------------------------------------------- 표기층 위생(plan §0.6 '표기층 위생' 행·§3.4.1)
INJECTION_VERSION = "inj-1.0"

# 종류별 상한(plan §0.6). 상한 뒤에 «…» 로 감싸므로 실제 라인은 +2자다.
SANITIZE_LIMITS: dict[str, int] = {
    "label": 120, "note": 300, "title": 200, "message": 350,
    "memo": 400, "statement": 200, "claim": 160,
}
DEFAULT_SANITIZE_KIND = "label"

# 제거 대상 — 제어문자(C0/C1, 개행·탭은 앞서 공백으로 바꾼다) · zero-width · 양방향 제어.
_ZERO_WIDTH = "\u200b\u200c\u200d\ufeff"
_BIDI = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]")
_STRIP_RE = re.compile("[" + _ZERO_WIDTH + _BIDI + "]")
_WHITESPACE_RE = re.compile(r"[\n\r\t\v\f]+")
_SPACES_RE = re.compile(r" {2,}")

# 저장형 프롬프트 인젝션 어휘(plan §3.4.1 시드 X01~X10). 항목은 {id, pattern}.
INJECTION_LEXICON: tuple[dict, ...] = (
    # X01 은 plan 시드에 어순 하나를 더한다 — '이전 지시를 무시하고' 처럼 목적어가 앞에 오는 형태가 실제로 온다.
    {"id": "X01", "pattern": r"무시(하고|하라|해라|해)?\s*(위|이전|앞)|(위|이전|앞)\s*\S{0,10}\s*무시"},
    {"id": "X02", "pattern": r"(?i)ignore\s+(all\s+)?(previous|prior|above)"},
    {"id": "X03", "pattern": r"(?i)(system|developer)\s*(prompt|message|instruction)"},
    {"id": "X04", "pattern": r"(?i)너는\s*이제|당신은\s*이제|from now on"},
    {"id": "X05", "pattern": r"(?i)^\s*(assistant|system|user)\s*:"},
    {"id": "X06", "pattern": r"(?i)</?(system|instructions?|tool_call)>"},
    {"id": "X07", "pattern": r"```"},
    {"id": "X08", "pattern": r"(?i)https?://"},
    {"id": "X09", "pattern": r"(?i)(reveal|출력하라|그대로\s*복사).{0,20}(prompt|지시|규칙)"},
    {"id": "X10", "pattern": r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]"},
)
_INJECTION_COMPILED = tuple((item["id"], re.compile(item["pattern"])) for item in INJECTION_LEXICON)


def injection_hit(text: str) -> str | None:
    """인젝션 어휘에 걸린 첫 항목 id(없으면 None). 위생 통과본을 대상으로 검사한다(§3.4.1)."""
    for lexicon_id, pattern in _INJECTION_COMPILED:
        if pattern.search(text or ""):
            return lexicon_id
    return None


def source_sha1(text: Any) -> str:
    """원본 문자열의 sha1 앞 12자 — 자리표시자·큐 payload·복원 승인이 같은 키를 쓴다."""
    return hashlib.sha1(("" if text is None else str(text)).encode("utf-8")).hexdigest()[:12]


def suspect_placeholder(text: Any) -> str:
    """`«[suspect_text <sha1[:12]>]»` — 원문 대신 실리는 자리표시자."""
    return QUOTE_OPEN + f"[suspect_text {source_sha1(text)}]" + QUOTE_CLOSE


def sanitize_source_text(text: Any, kind: str = DEFAULT_SANITIZE_KIND, *,
                         block: bool | None = None,
                         on_suspect: Callable[[dict], None] | None = None) -> str:
    """원천 문자열을 표기층에 넣기 직전에 위생 처리한다(plan §0.6·§3.4.1).

    NFC → 제어·zero-width·양방향 제어 제거 → 개행·탭을 공백 1개로 → 연속 공백 압축 → 종류별 상한 → `«…»`.
    `INJECTION_LEXICON` 적중이고 `block` 이면 문자열 **전체** 를 `«[suspect_text <sha1[:12]>]»` 로 바꾸고
    `on_suspect({sha1, raw, lexicon_id, lexicon_version})` 을 부른다(호출자가 rr_curation_queue 에 올린다).

    표기층 전용이다 — `rr_snapshots.ir_json` 원본과 `ir_hash` 는 이 함수로 바뀌지 않는다.
    """
    raw = "" if text is None else str(text)
    s = unicodedata.normalize("NFC", raw)
    s = _WHITESPACE_RE.sub(" ", s)
    s = _CONTROL_RE.sub("", s)
    s = _STRIP_RE.sub("", s)
    s = _SPACES_RE.sub(" ", s).strip()
    limit = SANITIZE_LIMITS.get(kind, SANITIZE_LIMITS[DEFAULT_SANITIZE_KIND])
    s = s[:limit]
    if block is None:
        block = _suspect_block_setting()
    # 위생 통과본과 원문을 함께 본다 — X10(제어문자)처럼 위생이 지워 버리는 표지도 '의심' 의 근거다(§3.4.1).
    lexicon_id = injection_hit(s) or injection_hit(raw)
    if lexicon_id is not None and block:
        if on_suspect is not None:
            on_suspect({"sha1": source_sha1(raw), "raw": raw, "lexicon_id": lexicon_id,
                        "lexicon_version": INJECTION_VERSION})
        return suspect_placeholder(raw)
    return quote_source(s)


def _suspect_block_setting() -> bool:
    """Settings `risk_suspect_text_block`(기본 true). config 를 못 읽으면 막는 쪽(True)이 기본이다."""
    try:
        from app import config  # noqa: PLC0415 — 선택 의존이라 지연 임포트한다.
        return bool(config.settings.risk_suspect_text_block)
    except Exception:                                    # pragma: no cover — 설정 부재는 닫힘으로 본다.
        return True


def quote_source(text: Any) -> str:
    """원천 문자열을 «…» 로 감싼다(린터 제외 구간). 이미 감싼 문자열은 그대로 둔다."""
    s = "" if text is None else str(text)
    if s.startswith(QUOTE_OPEN) and s.endswith(QUOTE_CLOSE):
        return s
    return QUOTE_OPEN + s.replace(QUOTE_OPEN, "").replace(QUOTE_CLOSE, "") + QUOTE_CLOSE


def strip_quoted(text: str) -> str:
    """«…» 구간을 지운 텍스트(길이는 보존하지 않는다 — 사람이 읽는 용도)."""
    return re.sub(QUOTE_OPEN + r"[^" + QUOTE_CLOSE + r"]*" + QUOTE_CLOSE, "", text or "")


def mask_neutral(text: str) -> str:
    """린터 제외 구간을 같은 길이의 공백으로 덮는다(줄·열 번호가 보존된다)."""
    s = text or ""
    chars = list(s)
    for pattern in _NEUTRAL_COMPILED:
        for m in pattern.finditer(s):
            for i in range(m.start(), m.end()):
                if chars[i] != "\n":
                    chars[i] = " "
    return "".join(chars)


def lint_text(text: str, section: str = "") -> dict:
    """코드 생성 문장의 판단어를 찾는다. {ok, lexicon_version, violations:[{section, line_no, token, id}]}."""
    masked = mask_neutral(text or "")
    violations: list[dict] = []
    for line_no, line in enumerate(masked.split("\n"), start=1):
        tag = _SECTION_TAG.match(line.strip())
        line_section = tag.group(1) if tag else section
        for item in _LEX_COMPILED:
            allowed: list[tuple[int, int]] = []
            for allow in item["allow"]:
                allowed.extend((m.start(), m.end()) for m in allow.finditer(line))
            for m in item["pattern"].finditer(line):
                if any(a <= m.start() and m.end() <= b for a, b in allowed):
                    continue
                violations.append(
                    {"section": line_section, "line_no": line_no, "token": m.group(0), "id": item["id"]}
                )
    violations.sort(key=lambda v: (v["line_no"], v["id"], v["token"]))
    return {"ok": not violations, "lexicon_version": LEXICON_VERSION, "violations": violations}


def assert_clean(text: str, section: str = "") -> str:
    """린터를 통과하면 텍스트를 그대로 돌려주고, 위반이 있으면 JudgementLintError 를 던진다."""
    result = lint_text(text, section)
    if not result["ok"]:
        raise JudgementLintError(result["violations"], result["lexicon_version"])
    return text


# ---------------------------------------------------------------- 정규 표기 원자(plan §3.4.1)
# 표기 자릿수 — 길이 mm 3자리 · 면적 mm² 1자리 · 부피 mm³ 유효 3자리 · 비율 2자리 · 응력 MPa 정수.
_DISPLAY_DECIMALS = {"length": 3, "ratio": 2, "area": 1, "acceleration": 1, "fs": 2, "alignment": 3}
_DISPLAY_SIGFIGS = {"volume": 3}
_DISPLAY_INT = ("stress", "count", "rank")


def _sigfig(value: float, digits: int) -> str:
    if value == 0:
        return "0"
    exponent = math.floor(math.log10(abs(value)))
    decimals = max(0, digits - 1 - exponent)
    return f"{round(value, decimals):.{decimals}f}"


def fmt_num(value: Any, kind: str = "length") -> str:
    """수치 하나의 표기. 값이 없으면 '미측정' 이고 숫자가 아니면 원문 문자열이다."""
    if value is None:
        return "미측정"
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if not math.isfinite(float(value)):
        return "미측정"
    if kind in _DISPLAY_INT:
        return str(int(round(float(value))))
    if kind in _DISPLAY_SIGFIGS:
        return _sigfig(float(value), _DISPLAY_SIGFIGS[kind])
    decimals = _DISPLAY_DECIMALS.get(kind, 3)
    return f"{float(value):.{decimals}f}"


def _sign(value: float) -> str:
    if value > 0:
        return "+"
    if value < 0:
        return MINUS
    return ""


def fmt_signed(value: Any, kind: str = "length") -> str:
    """부호를 앞에 붙인 수치 표기(음수는 U+2212). 값이 없으면 '미측정'."""
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return fmt_num(value, kind)
    return _sign(float(value)) + fmt_num(abs(float(value)), kind)


def fmt_pct(rel: Any) -> str:
    """상대 변화(0.136 → '(+13.6%)'). 값이 없으면 빈 문자열."""
    if rel is None or isinstance(rel, bool) or not isinstance(rel, (int, float)):
        return ""
    if not math.isfinite(float(rel)):
        return ""
    return f"({_sign(float(rel))}{abs(float(rel)) * 100:.1f}%)"


def fmt_value(value: Any, unit: str | None = None, kind: str = "length", *, lower_bound: bool = False) -> str:
    """값+단위 표기. lower_bound 면 '≥0.05 mm(lower_bound)' 형식이다."""
    body = fmt_num(value, kind)
    if body == "미측정":
        return body
    prefix = "≥" if lower_bound else ""
    text = f"{prefix}{body}" + (f" {unit}" if unit else "")
    return text + "(lower_bound)" if lower_bound else text


def fmt_change(before: Any, after: Any, unit: str | None = None, rel: Any = None, kind: str = "length") -> str:
    """변화 표기 'before→after unit (±rel%)'. 숫자가 아니면 원문 그대로 잇는다(tied→touching)."""
    numeric = all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (before, after))
    if numeric:
        head = f"{fmt_num(before, kind)}→{fmt_num(after, kind)}"
        if rel is None and float(before) != 0:
            rel = (float(after) - float(before)) / abs(float(before))
    else:
        head = f"{'미측정' if before is None else before}→{'미측정' if after is None else after}"
        rel = rel if numeric else rel
    parts = [head]
    if unit:
        parts.append(unit)
    pct = fmt_pct(rel) if numeric else ""
    if pct:
        parts.append(pct)
    return " ".join(parts)


def fmt_label(label: Any, auto_named: bool = False) -> str:
    """노드 이름 표기 — label 원문에 auto_named 면 '(auto_named)' 접미."""
    text = "" if label is None else str(label)
    return f"{text}(auto_named)" if auto_named else text


def fmt_iface(name_a: Any, name_b: Any) -> str:
    """계면 표기 'A↔B'. 정렬 무관이고 표시는 이름 오름차순이다."""
    a, b = str(name_a or ""), str(name_b or "")
    first, second = sorted([a, b], key=lambda s: s.casefold())
    return f"{first}↔{second}"


def fmt_refs(*refs: Any) -> str:
    """줄 끝 참조 표기 '[c:…] [d:…]'. 빈 값·중복은 버린다(순서 보존)."""
    out: list[str] = []
    for ref in _flatten(refs):
        if not ref:
            continue
        text = str(ref).strip()
        if not text:
            continue
        token = text if text.startswith("[") else f"[{text}]"
        if token not in out:
            out.append(token)
    return " ".join(out)


def _flatten(values: Iterable[Any]) -> list[Any]:
    out: list[Any] = []
    for value in values:
        if isinstance(value, (list, tuple, set, frozenset)):
            out.extend(_flatten(value))
        else:
            out.append(value)
    return out


def signal_text(key: str, signal: dict | None) -> str:
    """rr_state signals 항목의 정규 표기. signal.text 가 정본이고 없으면 값으로 조립한다."""
    if not isinstance(signal, dict):
        return f"{key}=미측정"
    text = signal.get("text")
    if isinstance(text, str) and text:
        return text
    if signal.get("known") is False or signal.get("value") is None:
        return f"{key}=미측정"
    value = signal.get("value")
    unit = signal.get("unit")
    kind = "ratio" if signal.get("kind") == "ratio" else ("count" if signal.get("kind") == "count" else "length")
    return f"{key}={fmt_value(value, unit, kind)}"


def param_text(item: dict | None) -> str:
    """rr_diff 파라메트릭 항목의 정규 표기. item.text 가 정본이고 없으면 필드로 조립한다."""
    if not isinstance(item, dict):
        return ""
    text = item.get("text")
    if isinstance(text, str) and text:
        return text
    subject = item.get("name") or item.get("dn") or item.get("eid") or item.get("asm_key") or ""
    attr = item.get("attr") or ""
    body = fmt_change(item.get("before"), item.get("after"), item.get("unit"), item.get("rel_delta"))
    return " ".join(part for part in [str(subject), str(attr), body, fmt_refs(item.get("cid"))] if part)


def event_text(event: dict | None) -> str:
    """rr_diff 의미 이벤트의 정규 표기. event.text 가 정본이고 없으면 code·subject 로 조립한다."""
    if not isinstance(event, dict):
        return ""
    text = event.get("text")
    if isinstance(text, str) and text:
        return text
    subject = event.get("subject") or {}
    names = subject.get("names") or []
    head = fmt_iface(names[0], names[1]) if len(names) >= 2 else (str(names[0]) if names else "")
    magnitude = event.get("magnitude") or {}
    body = fmt_change(event.get("before"), event.get("after"), magnitude.get("unit"), magnitude.get("rel"))
    return " ".join(part for part in [head, str(event.get("code") or ""), body, fmt_refs(event.get("cid"))] if part)


# ---------------------------------------------------------------- 섹션 조립
def _render_section(tag: str, items: Sequence[str], limit: int, sep: str = " · ", ref: str = "") -> str:
    head = f"[{tag}] "
    kept: list[str] = []
    used = len(head)
    line = ""
    for index, item in enumerate(items):
        text = (item or "").strip()
        if not text:
            continue
        add = (len(sep) if kept else 0) + len(text)
        if kept and used + add > limit:
            line = head + sep.join(kept) + f"{sep}… 외 {len(items) - index}건"
            break
        kept.append(text)
        used += add
    else:
        line = head + sep.join(kept) if kept else head + "없음"
    return _with_ref(line, ref)


# 줄 끝 참조 토큰 `[sig:…]`·`[gate:…]`·`[p:…]` … 이 한 개라도 있는지 본다(plan §0.9 6항).
_REF_TOKEN = re.compile(r"\[[a-z]+:[^\]]*\]")


def _with_ref(line: str, ref: str) -> str:
    """줄에 참조가 하나도 없으면 섹션 기본 참조를 붙인다 — 요약의 모든 줄은 참조 ≥1 이다(plan §0.9 6항)."""
    if not ref or _REF_TOKEN.search(line):
        return line
    return f"{line} {fmt_refs(ref)}"


def _fit_total(sections: list[tuple], budget: int) -> str:
    """섹션을 조립하고 총량이 budget 을 넘으면 뒤 섹션의 항목부터 접는다(결정론).

    섹션 튜플은 `(tag, items, limit, sep)` 또는 `(tag, items, limit, sep, ref)` 다. `ref` 는 그 줄에
    항목발 참조가 하나도 없을 때만 붙는 기본 참조이고, 항목이 접혀도 사라지지 않는다.
    """
    work = [(s[0], list(s[1]), s[2], s[3], s[4] if len(s) > 4 else "") for s in sections]
    for _ in range(4000):
        lines = [_render_section(*section) for section in work]
        text = "\n".join(lines)
        if len(text) <= budget:
            return text
        for index in range(len(work) - 1, -1, -1):
            if len(work[index][1]) > 1:
                work[index][1].pop()
                break
        else:
            return text[:budget]
    return "\n".join(_render_section(*section) for section in work)[:budget]


def _first(values: Iterable[Any], default: Any = None) -> Any:
    for value in values:
        return value
    return default


def _cid_ref(items: Sequence[dict], predicate) -> str:
    for item in items or ():
        if predicate(item):
            return fmt_refs(item.get("cid"))
    return ""


# ---------------------------------------------------------------- snap summary_text(plan §3.2.7)
def _sig(state: dict, key: str) -> dict | None:
    signals = state.get("signals") or {}
    value = signals.get(key)
    return value if isinstance(value, dict) else None


def _sig_value(state: dict, key: str, default: Any = None) -> Any:
    signal = _sig(state, key)
    if signal is None or signal.get("known") is False:
        return default
    value = signal.get("value")
    return default if value is None else value


def _indexed_signals(state: dict, prefix: str, limit: int) -> list[tuple[str, dict]]:
    """'top.interference[1]' 형태의 키를 인덱스 순으로 모은다(리스트 값 형태도 받는다)."""
    signals = state.get("signals") or {}
    out: list[tuple[str, dict]] = []
    direct = signals.get(prefix)
    if isinstance(direct, dict) and isinstance(direct.get("value"), list):
        for index, entry in enumerate(direct["value"][:limit], start=1):
            text = entry.get("text") if isinstance(entry, dict) else None
            out.append((f"{prefix}[{index}]", {"text": text or str(entry), "refs": []}))
        return out
    pattern = re.compile(r"^" + re.escape(prefix) + r"\[(\d+)\]$")
    matched = []
    for key, signal in signals.items():
        m = pattern.match(key)
        if m and isinstance(signal, dict):
            matched.append((int(m.group(1)), key, signal))
    for _, key, signal in sorted(matched)[:limit]:
        out.append((key, signal))
    return out


def _summarize_state(state: dict, context: dict) -> str:
    missing = state.get("missing") or {}
    gates = state.get("gates") or {}
    sources = context.get("sources") or {}

    def source_of(kind: str, absent_flag: str) -> str:
        value = sources.get(kind)
        if value:
            return f"{kind}={value}"
        return f"{kind}=absent" if missing.get(absent_flag) else f"{kind}=미측정"

    target = [
        f"과제 {context.get('project_code') or state.get('project_id', '')[:8]}",
        f"스냅샷 {str(state.get('snapshot_id') or '')[:8]}",
        f"ir_hash={str(state.get('ir_hash') or '')[:12]}",
        f"소스 {sources.get('mcad') and 'mcad=' + str(sources['mcad']) or 'mcad=미측정'}",
        source_of("dyna", "dyna_absent"),
        source_of("dyna_result", "dyna_result_absent"),
        source_of("ecad", "ecad_absent"),
    ]
    g5 = gates.get("G5") or {}
    if g5.get("pass") is False:
        target.append(f"부분 검출(범위 밖 리프 {g5.get('count', 0)})")

    gate_items: list[str] = []
    gate_refs: list[str] = []
    for name in ("G1", "G2", "G3", "G4", "G5", "G6"):
        gate = gates.get(name)
        if not isinstance(gate, dict):
            continue
        if gate.get("pass") is True:
            gate_items.append(f"{name} pass")
            continue
        if gate.get("pass") is None:
            # 입력이 없어 검문하지 못했다 — pass 로 세지 않는다(plan §2.12).
            gate_items.append(f"{name} n/a({gate.get('reason') or 'unknown'})")
            gate_refs.append(f"gate:{name}")
            continue
        ack = gate.get("ack_reason")
        ack_text = f", ack {quote_source(ack)}" if ack else ", ack 없음"
        gate_items.append(f"{name} fail({gate.get('count', 0)}{ack_text})")
        gate_refs.append(f"gate:{name}")
    if gate_refs:
        gate_items.append(fmt_refs(gate_refs))

    edges = " ".join(
        f"{kind} {_sig_value(state, f'counts.edges.{kind}', 0)}"
        for kind in ("tied", "touching", "clearance", "interference")
    )
    structure = [
        f"파일 {_sig_value(state, 'counts.files', 0)}",
        f"리프 {_sig_value(state, 'counts.leaf', 0)}",
        f"어셈블리 {_sig_value(state, 'counts.assemblies', 0)}",
        f"엣지 {edges}",
        f"고아 {_sig_value(state, 'counts.orphans', 0)}",
        f"cross_file {_sig_value(state, 'counts.cross_file', 0)}",
        "[sig:counts.*]",
    ]

    iface: list[str] = []
    for key, signal in _indexed_signals(state, "top.interference", 3):
        iface.append(f"간섭 {signal_text(key, signal)} {fmt_refs(signal.get('refs'))}".strip())
    for key, signal in _indexed_signals(state, "top.tight_clearance", 3):
        iface.append(f"근접 간극 {signal_text(key, signal)} {fmt_refs(signal.get('refs'))}".strip())

    dims_signal = _sig(state, "dims_named")
    dims: list[str] = []
    if dims_signal is not None:
        value = dims_signal.get("value")
        if isinstance(value, dict):
            for name in sorted(value):
                entry = value[name]
                body = entry.get("text") if isinstance(entry, dict) else None
                if not body:
                    raw = entry.get("value") if isinstance(entry, dict) else entry
                    unit = entry.get("unit") if isinstance(entry, dict) else "mm"
                    body = f"{name}={fmt_value(raw, unit)}"
                dims.append(f"{body} {fmt_refs(f'd:{name}')}".strip())
        else:
            dims.append(signal_text("dims_named", dims_signal))

    materials = [
        f"재질 종류 {_sig_value(state, 'counts.materials_distinct', 0)}",
        f"미기재 {_sig_value(state, 'counts.material_null', 0)}",
        "[sig:counts.material_null]",
    ]

    if missing.get("dyna_absent"):
        dyna = ["absent"]
    else:
        dyna = [f"pid {_sig_value(state, 'counts.dyna.pids', 0)}"]
        contacts = _sig_value(state, "counts.dyna.contacts_by_type", {}) or {}
        if isinstance(contacts, dict):
            dyna.extend(f"{name} {count}" for name, count in sorted(contacts.items()))
        for key, signal in _indexed_signals(state, "results.part_risk_top", 3):
            dyna.append(f"{signal_text(key, signal)} {fmt_refs(signal.get('refs'))}".strip())
        if missing.get("dyna_result_absent"):
            dyna.append("결과 absent")

    rules: list[str] = []
    for hit in state.get("rule_hits") or ():
        if not isinstance(hit, dict):
            continue
        rule_id = hit.get("rule") or ""
        if hit.get("evaluable") is False or hit.get("pass") is None:
            # 결측을 '이상 없음' 으로 읽히게 두지 않는다(plan §3.2.6).
            rules.append(f"{rule_id} 평가 불가({hit.get('not_evaluable_reason') or 'unknown'})")
        elif hit.get("pass"):
            rules.append(f"{rule_id} pass")
        else:
            count = (hit.get("found") or {}).get("count", 0)
            rules.append(f"{rule_id} fail({count}건) {fmt_refs(f'rule:{rule_id}')}".strip())

    seeds = [str(seed.get("tag") or "") for seed in state.get("character_seed") or () if isinstance(seed, dict)]
    absent = [name for name in sorted(missing) if missing.get(name)]

    first_rule = _first((str(h.get("rule") or "") for h in state.get("rule_hits") or () if isinstance(h, dict)), "")

    return _fit_total(
        [
            ("대상", target, 320, " ", "sig:counts.files"),
            ("게이트", gate_items, 240, " · ", "gate:G1"),
            ("구조", structure, 300, " · ", "sig:counts.*"),
            ("상위 계면", iface, 420, " · ", "sig:top.interference"),
            ("치수", dims, 300, " · ", "sig:dims_named"),
            ("재료", materials, 120, " · ", "sig:counts.material_null"),
            ("Dyna", dyna, 320, " · ", "sig:counts.dyna.pids"),
            ("규칙", rules, 200, " · ", f"rule:{first_rule}" if first_rule else "sig:rule_hits"),
            ("씨앗", seeds, 120, " · ", "sig:character_seed"),
            ("결측", absent, 160, " · ", "sig:missing"),
        ],
        SUMMARY_MAX,
    )


# ---------------------------------------------------------------- pair summary_text(plan §3.4.2)
def _summarize_diff(diff: dict, context: dict) -> str:
    base = diff.get("base") or {}
    target_side = diff.get("target") or {}
    comparability = diff.get("comparability") or {}
    structural = diff.get("structural") or {}
    parametric = diff.get("parametric") or {}
    semantic = diff.get("semantic") or {}
    stats = diff.get("stats") or {}
    sources = context.get("sources") or {}

    target = [
        f"base {base.get('label') or ''} {str(base.get('snapshot_id') or '')[:8]} ir={str(base.get('ir_hash') or '')[:12]}",
        f"→ target {target_side.get('label') or ''} {str(target_side.get('snapshot_id') or '')[:8]}"
        f" ir={str(target_side.get('ir_hash') or '')[:12]}",
    ]
    for kind in ("mcad", "dyna", "dyna_result", "ecad"):
        if sources.get(kind):
            target.append(f"{kind}={sources[kind]}")
    if comparability.get("partial_any"):
        target.append("partial=true")

    excluded: dict[str, int] = {}
    for bucket in ("node_params", "edge_params", "materials", "dims_delta", "result_delta", "rollup_delta"):
        for item in parametric.get(bucket) or ():
            reason = isinstance(item, dict) and item.get("excluded_reason")
            if reason:
                excluded[reason] = excluded.get(reason, 0) + 1
    for item in structural.get("edge_changes") or ():
        reason = isinstance(item, dict) and item.get("excluded_reason")
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1

    correspondence = diff.get("correspondence") or {}
    comparability_items = [
        f"tol_parity={_json_word(comparability.get('tol_parity'))}",
        f"result_parity={_json_word(comparability.get('result_parity'))}",
        f"unit_parity={_json_word(comparability.get('unit_parity'))}",
        f"scope_parity={_json_word(comparability.get('scope_parity'))}",
        f"coordinate_ok={_json_word(comparability.get('coordinate_ok'))}",
        f"same-as pending {correspondence.get('pending_n', 0)}",
    ]
    comparability_items.extend(f"제외 {reason} {count}건" for reason, count in sorted(excluded.items()))

    node_changes = list(structural.get("node_changes") or ())
    edge_changes = list(structural.get("edge_changes") or ())
    events = [e for e in (semantic.get("events") or ()) if isinstance(e, dict)]
    orphans = structural.get("orphans_delta") or {}

    def count_events(code: str) -> int:
        return sum(1 for e in events if e.get("code") == code)

    structure_items = [
        f"+{stats.get('nodes_added', 0)}파트 {MINUS}{stats.get('nodes_removed', 0)}파트"
        f" 교체 {sum(1 for n in node_changes if isinstance(n, dict) and n.get('op') == 'replaced')}"
        f" {_cid_ref(node_changes, lambda n: n.get('op') in ('added', 'removed', 'replaced'))}".strip(),
        f"계면 +{stats.get('edges_added', 0)} {MINUS}{stats.get('edges_removed', 0)}"
        f" {_cid_ref(edge_changes, lambda e: e.get('op') in ('added', 'removed'))}".strip(),
        f"rank 상승 {count_events('iface.rank_up')} 하락 {count_events('iface.rank_down')}"
        f" {_cid_ref(edge_changes, lambda e: e.get('op') == 'kind_changed')}".strip(),
        f"간섭 신규 {count_events('iface.interference_new')} 해소 {count_events('iface.interference_cleared')}",
        f"고아 +{len(orphans.get('became_orphan') or ())} {MINUS}{len(orphans.get('left_orphan') or ())}",
        f"롤업 변화 {len(parametric.get('rollup_delta') or ())}"
        f" {_cid_ref(parametric.get('rollup_delta') or (), lambda r: True)}".strip(),
    ]

    by_kind: dict[str, list[str]] = {}
    for event in events:
        if event.get("excluded_reason"):
            continue
        kind = str(event.get("change_kind") or "none")
        line = event_text(event)
        if event.get("confidence") == "low":
            line += " (confidence=low)"
        by_kind.setdefault(kind, []).append(line)
    semantic_items = []
    for kind in sorted(by_kind):
        texts = by_kind[kind][:5]
        extra = len(by_kind[kind]) - len(texts)
        body = " · ".join(texts) + (f" · … 외 {extra}건" if extra > 0 else "")
        semantic_items.append(f"{kind}: {body}")

    dims_items = [param_text(item) for item in parametric.get("dims_delta") or () if isinstance(item, dict)]
    node_params = [i for i in parametric.get("node_params") or () if isinstance(i, dict) and i.get("flag") == "changed"]
    edge_params = [i for i in parametric.get("edge_params") or () if isinstance(i, dict) and i.get("flag") == "changed"]
    changed = node_params + edge_params
    top_abs = sorted(changed, key=lambda i: (-abs(_num(i.get("delta"))), str(i.get("cid"))))[:5]
    top_rel = sorted(changed, key=lambda i: (-abs(_num(i.get("rel_delta"))), str(i.get("cid"))))[:5]
    merged: list[dict] = []
    for item in top_abs + top_rel:
        if item not in merged:
            merged.append(item)
    if merged:
        dims_items.append("절대·상대 상위: " + " · ".join(
            f"{param_text(item)}{_size_pct(item)}" for item in merged
        ))

    material_items = [param_text(item) for item in parametric.get("materials") or () if isinstance(item, dict)]
    if not material_items:
        material_items = ["변경 0"]

    if comparability.get("result_parity") is True:
        result_rows = [i for i in parametric.get("result_delta") or () if isinstance(i, dict) and not i.get("excluded_reason")]
        result_rows = sorted(result_rows, key=lambda i: (-abs(_num(i.get("rel_delta"))), str(i.get("cid"))))[:5]
        result_items = [param_text(item) for item in result_rows] or ["변경 0"]
    else:
        reason = _first(
            (i.get("excluded_reason") for i in parametric.get("result_delta") or () if isinstance(i, dict) and i.get("excluded_reason")),
            "result_kind_differs",
        )
        result_items = [f"결과 비교 제외({reason})"]

    seeds = [str(seed.get("tag") or "") for seed in diff.get("character_seed") or () if isinstance(seed, dict)]

    return _fit_total(
        [
            ("대상", target, 220, " ", "sig:ir_hash"),
            ("비교가능성", comparability_items, 200, " · ", "gate:G7"),
            ("구조", structure_items, 260, " · ", "sig:counts.edges.total"),
            ("의미", semantic_items, 700, " | ", "gate:G2"),
            ("치수", dims_items, 420, " · ", "sig:dims_named"),
            ("재료", material_items, 100, " · ", "sig:counts.materials_distinct"),
            ("결과", result_items, 160, " · ", "sig:results.part_risk_top"),
            ("씨앗", seeds, 60, " · ", "sig:character_seed"),
        ],
        SUMMARY_MAX,
    )


def _json_word(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _num(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value) if math.isfinite(float(value)) else 0.0


def _size_pct(item: dict) -> str:
    value = item.get("size_pct")
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    return f" (size_pct {int(round(float(value)))})"


# ---------------------------------------------------------------- 공개 진입
def summarize(payload: dict, kind: str, context: dict | None = None) -> str:
    """rr_state('snap') 또는 rr_diff('diff') 에서 summary_text 를 조립한다. 판단어가 섞이면 JudgementLintError."""
    if kind not in ("snap", "diff"):
        raise ValueError(f"summarize(): kind 는 'snap'|'diff' 여야 합니다 — {kind!r}.")
    ctx = dict(context or {})
    text = _summarize_state(payload or {}, ctx) if kind == "snap" else _summarize_diff(payload or {}, ctx)
    return assert_clean(text, section=kind)


def render_summary(payload: dict, kind: str, context: dict | None = None) -> dict:
    """summarize 의 비치명 판. {summary_text, summary_status, lexicon_version, violations}.

    운영 중 린터 위반은 코드 결함이므로 summary_text='' · summary_status='lint_failed' 로 남기고
    호출자가 violations 를 로그에 적는다(plan §3.4.3). 브리프는 표 항목만으로 조립된다.
    """
    try:
        text = summarize(payload, kind, context)
    except JudgementLintError as exc:
        return {
            "summary_text": "",
            "summary_status": "lint_failed",
            "lexicon_version": exc.lexicon_version,
            "violations": exc.violations,
        }
    return {
        "summary_text": text,
        "summary_status": "ok",
        "lexicon_version": LEXICON_VERSION,
        "violations": [],
    }
