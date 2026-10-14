# 카드 대조 결과의 회계·얼린 팩 재대조·카드 등급·실효 판정·훑기 회계·이중 판정 계획 — 저장소·네트워크 없는 순수 함수(m2-wp3b S4)
"""'저장된 판정의 카드는 그 호출에 실은 카드이고, 대조 통과 인용은 얼린 원문에 있다'(M2 나갈 기준 2)를 코드로 지킨다.

대조의 구현은 엔진에 한 벌 있다 — 행마다 `checks{quote, quote_sid, refs, nums_unsourced, need, coerced}` 가 실려 온다. 앱이
하는 일은 넷이다.

1. 집합 회계 — 실은 카드 집합과 판정이 온 카드 집합을 앱이 다시 센다(엔진의 `missing` 을 그대로 믿지 않는다).
2. 얼린 글로 재대조 — 카드 인용을 앱이 얼린 팩(`cardpack.card_text`)에 한 번 더 댄다. `quote_ok = 1` 은 엔진이 ok 라 했고
   앱의 재대조도 통과할 때뿐이다. 둘이 갈리면 `check_disagree = 1` 이고 0 이다(X1-21 — 앱이 느슨한 쪽으로 틀려도 통과가 아니다).
3. 등급 — 카드 confidence 로 정한다(엔진은 등급을 모른다). 재대조를 지난 행에만 뜻이 있다.
4. 실효 판정 — 변형(fwd·rev·solo)이 여럿인 카드에서 하나를 고른다. 어느 변형이든 걸림이 있었는데 실효가 통과로 끝나면
   실효를 undetermined 로 두고 split 을 단다(X1-14).

목록 칸(`l`·`refs`·`k`)에 문자열 하나가 오면 한 항목 목록으로 읽는다 — 글자로 쪼개지 않는다(D-25 의 교훈).
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from app import cardpack
from app.common import canonical_json

VERIFY_REV = "verify-1"
QUOTE_MIN = 15                      # 엔진 card_review.QUOTE_MIN — 인용 하한(글자)
QUOTE_SUBSTANTIVE_MIN = 10          # 엔진 QUOTE_SUBST_MIN — 실질 문자(숫자·영문·한글) 하한
SAMPLE_SALT = "rr-sample-1"         # 바꾸면 표본이 바뀐다 — 잡 params.knobs.sample_salt 에 같이 적는다

APPLIES = ("yes", "no", "unknown")
JUDGEMENTS = ("OK", "WARNING", "FAIL", "undetermined", "na")
FLAGGED = ("FAIL", "WARNING")       # 걸림
CLEAR = ("OK", "na")                # 걸림 없음
_WEIGHT = {"FAIL": 4, "WARNING": 3, "undetermined": 2, "OK": 1, "na": 0}
_APPLIES_JUDGEMENTS = {"yes": ("OK", "WARNING", "FAIL", "undetermined"), "no": ("na",), "unknown": ("undetermined",)}
GRADE_LITERATURE = "문헌·규격"
GRADE_HEURISTIC = "경험칙"
RELS = ("yes", "maybe", "no")
_REL_RANK = {"yes": 4, "maybe": 3, "error": 2, "stamp": 1, "no": 0}

_CURLY = str.maketrans({"“": '"', "”": '"', "„": '"', "‟": '"', "‘": "'", "’": "'", "‚": "'", "‛": "'"})
_MARKS_RE = re.compile(r"[*`«»]")
_ANY_SPACE_RE = re.compile(r"\s+")
_SUBSTANTIVE_RE = re.compile(r"[0-9A-Za-z가-힣]")


# ---------------------------------------------------------------- 인용 정규화·대조(엔진 _nq·quote_check 와 같은 규칙)
def nq(text: Any) -> str:
    """인용 대조의 정규화 — 엔진 `card_review._nq` 와 글자 하나까지 같다. 굽은 따옴표를 곧은 따옴표로, 강조 기호(* · `)와 인용
    구간 기호(«»)를 지우고, 유니코드 공백(`\\s` — 개행·NBSP·U+3000 따위)을 한 칸으로 접는다. 양쪽(인용과 카드 글)에 같은 함수를 건다.

    NFC·zero-width·제어·양방향 문자는 건드리지 않는다 — 엔진이 건드리지 않기 때문이다. 종전에는 `render.norm_quote` 로 그것들을
    지워 엔진보다 느슨했고, 그런 글자가 든 카드나 인용은 행마다 앱 ok · 엔진 not_found 로 갈려 `check_disagree` 가 쌓였다(잡당
    5건을 넘으면 contract 보류 — 반대 검토 C2a RC-4). 엔진의 실제 함수와의 동치는 시험이 엔진 venv 하위 프로세스로 본다."""
    s = str(text or "").translate(_CURLY)
    return _ANY_SPACE_RE.sub(" ", _MARKS_RE.sub("", s)).strip()


def _unescape(text: str) -> str:
    """모델이 이스케이프를 한 겹 더 적은 인용(\\n · \\" · \\t)을 풀어 본다(엔진 `_unescape`)."""
    return (text.replace("\\\\", "\x00").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')
            .replace("\x00", "\\"))


def substantive(text: str) -> int:
    return len(_SUBSTANTIVE_RE.findall(text or ""))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value if v is not None)
    return str(value)


def _quote_match(quote: Any, text: str) -> tuple[str, str]:
    """(상태, 맞은 정규화 인용) — 상태는 ok · short · not_found · empty."""
    q = _text(quote)
    if not q.strip():
        return "empty", ""
    full = nq(text)
    status = "short"
    for candidate in dict.fromkeys((q, _unescape(q))):
        n = nq(candidate).strip("\"' ")
        if len(n) < QUOTE_MIN or substantive(n) < QUOTE_SUBSTANTIVE_MIN:
            continue
        if n in full:
            return "ok", n
        status = "not_found"
    return status, ""


def quote_too_short(quote: Any) -> bool:
    """인용이 대조 하한(15자 · 실질 문자 10자, 이스케이프를 푼 것도 본다) 밑이라 대조하지 않는 글인가 — `_quote_match` 의 short 와
    같은 규칙이다(카드 글 없이 인용만으로 정한다). 빈 인용은 짧은 것이 아니라 없는 것이라 False 다."""
    q = _text(quote)
    if not q.strip():
        return False
    for candidate in dict.fromkeys((q, _unescape(q))):
        n = nq(candidate).strip("\"' ")
        if len(n) >= QUOTE_MIN and substantive(n) >= QUOTE_SUBSTANTIVE_MIN:
            return False
    return True


def quote_state(quote: Any, quote_ok: Any, check_disagree: Any, engine_status: Any) -> str | None:
    """저장된 대조 열에서 읽은 카드 인용의 갈래(보고서 표기 — R3B-4) — ok(엔진·앱 둘 다 찾았다) · short(하한 밑이라 대조하지
    않았다) · app_only(앱 재대조는 찾았고 엔진은 못 찾았다) · engine_only(엔진은 찾았다 하고 앱 재대조는 못 찾았다) · not_found(둘 다
    못 찾았다) · unchecked(인용은 있는데 댈 카드가 없었다) · None(인용 없음). `quote_ok = 0` 하나로 셋을 뭉개지 않는다."""
    if not _text(quote).strip():
        return None
    if quote_ok is None:
        return "unchecked"
    if int(quote_ok) == 1:
        return "ok"
    if int(check_disagree or 0):
        return "engine_only" if engine_status == "ok" else "app_only"
    return "short" if quote_too_short(quote) else "not_found"


def quote_status(quote: Any, text: str) -> str:
    """인용이 글(카드 전체 글 또는 절 하나)에 있나 — ok · short · not_found · empty(`quote_check` 와 같은 규칙)."""
    return _quote_match(quote, text)[0]


def quote_check(quote: Any, card: Mapping[str, Any]) -> tuple[str, str]:
    """인용이 **그 카드**의 얼린 글에 있나 — (ok · short · not_found · empty, 맞은 첫 절의 sid). 두 절에 걸치면 sid 는 "".

    15자 이상 · 실질 문자 10자 이상이어야 대조한다. 이스케이프를 푼 것도 보고, 인용을 감싼 따옴표는 떼고 본다. 머리 줄(제목)은
    인용 원문이 아니다(엔진 `quote_check` 와 같은 규칙 — 공유 벡터가 지킨다)."""
    status, matched = _quote_match(quote, cardpack.card_text(card))
    if status != "ok":
        return status, ""
    sid = next((str(s.get("sid")) for s in card.get("sections") or ()
                if isinstance(s, Mapping) and matched in nq(s.get("text"))), "")
    return "ok", sid


def card_grade(card: Mapping[str, Any]) -> str:
    """카드 confidence 로 정한 등급 — `fact` 이고 규격(`standard_refs`)이나 출처(`sources_n ≥ 1`)가 있으면 문헌·규격, 나머지는
    경험칙이다(설계서 §3.8.5). 재대조를 지난 인용(`quote_ok = 1`)에만 뜻이 있다."""
    refs = card.get("standard_refs")
    has_refs = isinstance(refs, (list, tuple)) and any(str(r).strip() for r in refs)
    sources = card.get("sources_n")
    has_sources = isinstance(sources, int) and not isinstance(sources, bool) and sources >= 1
    if str(card.get("confidence") or "") == "fact" and (has_refs or has_sources):
        return GRADE_LITERATURE
    return GRADE_HEURISTIC


def as_list(value: Any) -> list[str]:
    """목록 칸을 문자열 목록으로 — 문자열 하나는 한 항목 목록이다(글자로 쪼개지 않는다). 빈 값은 뺀다."""
    if value is None or isinstance(value, Mapping):
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v is not None and not isinstance(v, Mapping) and str(v).strip()]
    return [str(value)]


def refs_verdict(refs: Sequence[str], unit_refs: Collection[str], *, required: bool) -> int | None:
    """되돌아온 참조가 전부 그 단위에 실어 보낸 참조(변경 줄 + 근거 줄)면 1, 아니면 0. 참조가 하나도 없으면 NULL(X1-05)이고,
    참조가 있어야 하는 행(`applies='yes'` 판정 · 카드 밖 리스크)이 비었으면 0 이다."""
    if not refs:
        return 0 if required else None
    return 1 if all(ref in unit_refs for ref in refs) else 0


def _cards_of(pack: Any) -> Mapping[str, Mapping[str, Any]]:
    if isinstance(pack, cardpack.FrozenPack):
        return pack.cards
    if isinstance(pack, Mapping) and isinstance(pack.get("cards"), list):
        return cardpack.view_of(pack).cards
    raise TypeError("pack 은 cardpack.FrozenPack 이거나 팩 dict 여야 한다")


def _quote_columns(quote: Any, card: Mapping[str, Any] | None, engine_status: Any) -> dict:
    """(quote_ok, check_disagree, section_id) — 엔진이 ok 이고 앱 재대조도 ok 일 때만 1, 인용이 없으면 NULL."""
    if not _text(quote).strip() or card is None:
        return {"quote_ok": None, "check_disagree": 0, "section_id": None}
    status, sid = quote_check(quote, card)
    app_ok = status == "ok"
    engine_ok = engine_status == "ok"
    return {"quote_ok": int(app_ok and engine_ok), "check_disagree": int(app_ok != engine_ok),
            "section_id": (sid or None) if app_ok else None}


def _drop(dropped: list, reason: str, row: Any) -> None:
    dropped.append({"reason": reason, "row": copy.deepcopy(row)})


# ---------------------------------------------------------------- 받은 행의 회계
def accept_rows(result: Mapping[str, Any], *, kind: str, sent_aliases: Sequence[str], pack: Any,
                unit_refs: Collection[str] | None = None, page_units: Sequence[str] | None = None,
                variant: str | None = None) -> dict:
    """엔진 result 프레임 → {rows, missing, dropped, extras}.

    - `sent_aliases` — 이 호출에 실은 카드 별칭(팩 별칭). `pack` — 얼린 팩(`cardpack.FrozenPack` 또는 팩 dict).
    - `unit_refs` — 그 단위에 실어 보낸 참조(변경 줄 + 근거 줄, 문맥 줄 제외 — `units.refs_of`). verdict·offcard 에 필요하다.
    - `page_units` — sweep 에서 그 쪽에 실은 단위 id.

    verdict — `v` 행을 판정 행으로(`rr_card_verdicts` 열 이름 그대로, 신원 열·`is_effective`·`agree`·`split`·`call_id` 는 부른
    쪽이 채운다). 별칭이 실은 집합 밖이면 버리고(`alias_outside_call`), 같은 별칭은 첫 행만 쓰며(`duplicate`), `record_id` 는
    행의 값이 아니라 별칭 → 팩으로 되돌린 값이다(다르면 `record_mismatch`). 열거 밖·정합이 안 맞는 행은 버린다 — 그 카드는
    빠진 카드가 된다. `missing` 은 앱이 다시 센 것이다(엔진의 `missing` 은 `extras.engine_missing` 에 둔다). solo 의 `c` 줄은
    같은 별칭의 `conds_json` 으로 간다.
    offcard — `f` 행을 카드 밖 후보로, `m`·`h`·`need`·`none`·`more` 는 `extras` 로. sweep — `u` 행을 단위 선별로(빠진 단위가
    `missing`, 어느 줄에도 없는 카드가 `extras.cards_unseen`). noinput — `q1`(지금 변경으로 말할 수 있는 영향)·`q2`(결측 입력이
    오면 확인할 것) 행을 그대로 `t` 를 달아(재설계 M3 C3-3 · m3-cells 3.6), `more` 는 `extras` 로. 빠진 줄 종류(q1·q2)가
    `missing` 이다.
    """
    if kind not in ("verdict", "offcard", "sweep", "noinput"):
        raise ValueError(f"모르는 호출 종류 — {kind!r}")
    if kind in ("verdict", "offcard", "noinput") and unit_refs is None:
        raise ValueError(f"{kind} 의 참조 대조에는 unit_refs(그 단위에 실은 참조)가 필요하다")
    if kind == "sweep" and page_units is None:
        raise ValueError("sweep 의 회계에는 page_units(그 쪽에 실은 단위)가 필요하다")
    cards = _cards_of(pack)
    sent = list(dict.fromkeys(str(a) for a in sent_aliases))
    raw_rows = [r for r in result.get("rows") or ()] if isinstance(result, Mapping) else []
    extras_in = result.get("extras") if isinstance(result, Mapping) and isinstance(result.get("extras"), Mapping) else {}
    common = {"inj": list(extras_in.get("inj") or ()),
              "engine_missing": as_list(result.get("missing")) if isinstance(result, Mapping) else []}
    if kind == "verdict":
        return _accept_verdict(raw_rows, sent, cards, frozenset(unit_refs or ()), variant, common)
    if kind == "offcard":
        return _accept_offcard(raw_rows, sent, cards, frozenset(unit_refs or ()), common)
    if kind == "noinput":
        return _accept_noinput(raw_rows, sent, cards, frozenset(unit_refs or ()), common)
    quality = result.get("quality") if isinstance(result, Mapping) and isinstance(result.get("quality"), Mapping) else {}
    return _accept_sweep(raw_rows, sent, list(dict.fromkeys(str(u) for u in page_units or ())), common,
                         stamp=bool(quality.get("stamp")))


def _consistent(applies: str, judgement: str) -> bool:
    return judgement in _APPLIES_JUDGEMENTS.get(applies, ())


def _revised_from(checks: Mapping[str, Any]) -> str | None:
    """엔진이 (applies, judgement) 를 고쳐 실었으면 그 표지(`consistency:no+FAIL` 등)."""
    marks = [str(c) for c in checks.get("coerced") or () if str(c).startswith(("consistency:", "applies:", "judgement:"))]
    return ";".join(marks) or None


def _accept_verdict(raw_rows: list, sent: list[str], cards: Mapping[str, Mapping[str, Any]],
                    unit_refs: frozenset, variant: str | None, extras: dict) -> dict:
    sent_set = set(sent)
    dropped: list[dict] = []
    claimed: set[str] = set()
    accepted: dict[str, dict] = {}
    conds: dict[str, list[dict]] = {}
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            _drop(dropped, "not_object", raw)
            continue
        t = raw.get("t")
        alias = str(raw.get("k") or "")
        if t == "c":
            if alias not in sent_set:
                _drop(dropped, "alias_outside_call", raw)
                continue
            refs = as_list(raw.get("refs"))
            conds.setdefault(alias, []).append({
                "cond": _text(raw.get("cond")), "met": _text(raw.get("met")), "note": _text(raw.get("note")),
                "l": as_list(raw.get("l")), "refs": refs,
                "refs_ok": refs_verdict(refs, unit_refs, required=False)})
            continue
        if t != "v":
            _drop(dropped, "foreign_row", raw)
            continue
        if alias not in sent_set:
            _drop(dropped, "alias_outside_call", raw)
            continue
        if alias in claimed:
            _drop(dropped, "duplicate", raw)
            continue
        claimed.add(alias)
        card = cards.get(alias)
        if card is None:
            _drop(dropped, "alias_not_in_pack", raw)
            continue
        record_id = str(card["record_id"])
        if raw.get("record_id") not in (None, "") and str(raw.get("record_id")) != record_id:
            _drop(dropped, "record_mismatch", raw)
            continue
        applies, judgement = _text(raw.get("applies")), _text(raw.get("judgement"))
        if applies not in APPLIES or judgement not in JUDGEMENTS:
            _drop(dropped, "bad_enum", raw)
            continue
        if not _consistent(applies, judgement):
            _drop(dropped, "inconsistent", raw)
            continue
        checks = raw.get("checks") if isinstance(raw.get("checks"), Mapping) else {}
        for mark in ("flipped_from", "contested_by"):
            # 엔진 보충이 앞 시도의 판정을 갈아 끼웠다(flipped_from) · 검증된 철회가 그 걸림을 다퉜다(contested_by — 걸림은 선다,
            # RB3-1). 판정 표에 그 칸이 없어 checks 사본에 남긴다.
            if raw.get(mark):
                checks = {**checks, mark: raw.get(mark)}
        lines = as_list(raw.get("l"))
        refs = as_list(raw.get("refs"))
        quote = _quote_columns(raw.get("cq"), card, checks.get("quote"))
        accepted[alias] = {
            "variant": variant, "alias": alias, "record_id": record_id,
            "card_id": str(card.get("card_id") or raw.get("card_id") or "") or None,
            "section_id": quote["section_id"], "text_sha": str(card.get("text_sha") or ""),
            "applies": applies, "judgement": judgement, "cq": _text(raw.get("cq")) or None,
            "lines_json": canonical_json(lines), "refs_json": canonical_json(refs),
            "why": _text(raw.get("why")) or None, "need": _text(raw.get("need")) or None,
            "sev": _text(raw.get("sev")) or None, "mech": _text(raw.get("mech")) or None,
            "mech_free": _text(raw.get("mech_free")) or None, "path": _text(raw.get("path")) or None,
            "check_kind": _text(raw.get("check_kind")) or None, "check_text": _text(raw.get("check")) or None,
            "conds_json": None, "checks_json": canonical_json(dict(checks)),
            "quote_ok": quote["quote_ok"], "check_disagree": quote["check_disagree"],
            "refs_ok": refs_verdict(refs, unit_refs, required=applies == "yes"),
            "grade": card_grade(card) if quote["quote_ok"] == 1 else None,
            "revised_from": _revised_from(checks),
        }
    for alias, items in conds.items():
        if alias in accepted:
            accepted[alias]["conds_json"] = canonical_json(items)
        else:
            _drop(dropped, "cond_without_verdict", {"k": alias, "conds": items})
    rows = [accepted[a] for a in sent if a in accepted]
    return {"rows": rows, "missing": [a for a in sent if a not in accepted], "dropped": dropped, "extras": extras}


def _accept_offcard(raw_rows: list, sent: list[str], cards: Mapping[str, Mapping[str, Any]],
                    unit_refs: frozenset, extras: dict) -> dict:
    sent_set = set(sent)
    dropped: list[dict] = []
    findings: list[dict] = []
    out = dict(extras, seen=[], handoffs=[], need=[], none=False, more=None)
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            _drop(dropped, "not_object", raw)
            continue
        t = raw.get("t")
        if t == "f":
            title = _text(raw.get("title")).strip()
            if not title:
                _drop(dropped, "no_title", raw)
                continue
            checks = raw.get("checks") if isinstance(raw.get("checks"), Mapping) else {}
            src = _text(raw.get("src")) or "exp"
            card = cards.get(src) if src in sent_set else None
            quote = (_quote_columns(raw.get("q"), card, checks.get("quote")) if card is not None
                     else {"quote_ok": None, "check_disagree": 0, "section_id": None})
            refs = as_list(raw.get("refs"))
            findings.append({
                "dir": _text(raw.get("dir")) or "risk", "title": title, "mech": _text(raw.get("mech")) or None,
                "mech_free": _text(raw.get("mech_free")) or None, "path": _text(raw.get("path")) or None,
                "l": as_list(raw.get("l")), "refs": refs, "src": src,
                "record_id": str(card["record_id"]) if card is not None else (_text(raw.get("record_id")) or None),
                "q": _text(raw.get("q")) or None, "sev": _text(raw.get("sev")) or None,
                "conf": _text(raw.get("conf")) or None, "check_kind": _text(raw.get("check_kind")) or None,
                "check_text": _text(raw.get("check")) or None, "basis": _text(raw.get("basis")) or None,
                "quote_ok": quote["quote_ok"], "check_disagree": quote["check_disagree"],
                "section_id": quote["section_id"],
                "grade": card_grade(card) if card is not None and quote["quote_ok"] == 1 else None,
                "refs_ok": refs_verdict(refs, unit_refs, required=True),
                "checks": dict(checks)})
        elif t == "m":
            out["seen"] = sorted(set(out["seen"]) | set(as_list(raw.get("seen"))))
        elif t == "h":
            out["handoffs"].append({"to": _text(raw.get("to")), "why": _text(raw.get("why")),
                                    "l": as_list(raw.get("l")), "refs": as_list(raw.get("refs"))})
        elif t == "need":
            out["need"].append({k: _text(v) if not isinstance(v, list) else as_list(v)
                                for k, v in raw.items() if k not in ("t", "checks", "from_attempt")})
        elif t == "none":
            out["none"] = True
        elif t == "more":
            out["more"] = _text(raw.get("more")) or None
        else:
            _drop(dropped, "foreign_row", raw)
    return {"rows": findings, "missing": [], "dropped": dropped, "extras": out}


IMPACTS = APPLIES                   # q1 의 impact — 영향 있음 · 없음 · 모름


def _accept_noinput(raw_rows: list, sent: list[str], cards: Mapping[str, Mapping[str, Any]], unit_refs: frozenset,
                    extras: dict) -> dict:
    """입력 결손 호출의 회계 — 카드(`k`)는 실은 별칭이어야 하고(밖이면 버린다 — `alias_outside_call`), 참조가 남의 단위를 가리키면
    버린다(`foreign_ref` — Q8). impact 가 열거 밖이면 버리고(`bad_enum`), 영향 있음(yes)인데 제목이 없으면 finding 이 될 수 없어
    버린다(`no_title`). 카드 인용(`cq`)은 그 카드의 얼린 원문으로 다시 대조한다(`quote_ok` — verdict 와 같은 규칙). 목록 칸은 문자열
    하나도 한 항목으로 읽는다(D-25)."""
    sent_set = set(sent)
    dropped: list[dict] = []
    rows: list[dict] = []
    out = dict(extras, more=None)
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            _drop(dropped, "not_object", raw)
            continue
        t = raw.get("t")
        if t == "more":
            out["more"] = _text(raw.get("more")) or None
            continue
        if t not in ("q1", "q2"):
            _drop(dropped, "foreign_row", raw)
            continue
        alias = _text(raw.get("k")).strip()
        if alias and alias not in sent_set:
            _drop(dropped, "alias_outside_call", raw)
            continue
        refs = as_list(raw.get("refs"))
        if any(ref not in unit_refs for ref in refs):
            _drop(dropped, "foreign_ref", raw)
            continue
        checks = raw.get("checks") if isinstance(raw.get("checks"), Mapping) else {}
        card = cards.get(alias) if alias else None
        base = {"t": t, "k": alias or None, "record_id": str(card["record_id"]) if card is not None else None,
                "l": as_list(raw.get("l")), "refs": refs, "why": _text(raw.get("why")) or None, "checks": dict(checks)}
        if t == "q2":
            rows.append({**base, "item": _text(raw.get("item")).strip(), "needs": _text(raw.get("needs")) or None,
                         "refs_ok": refs_verdict(refs, unit_refs, required=False)})
            continue
        impact = _text(raw.get("impact"))
        if impact not in IMPACTS:
            _drop(dropped, "bad_enum", raw)
            continue
        title = _text(raw.get("title")).strip()
        if impact == "yes" and not title:
            _drop(dropped, "no_title", raw)
            continue
        quote = (_quote_columns(raw.get("cq"), card, checks.get("quote")) if card is not None
                 else {"quote_ok": None, "check_disagree": 0, "section_id": None})
        rows.append({**base, "impact": impact, "title": title, "mech": _text(raw.get("mech")) or None,
                     "mech_free": _text(raw.get("mech_free")) or None, "path": _text(raw.get("path")) or None,
                     "cq": _text(raw.get("cq")) or None, "sev": _text(raw.get("sev")) or None,
                     "quote_ok": quote["quote_ok"], "check_disagree": quote["check_disagree"],
                     "section_id": quote["section_id"],
                     "grade": card_grade(card) if card is not None and quote["quote_ok"] == 1 else None,
                     "refs_ok": refs_verdict(refs, unit_refs, required=impact == "yes")})
    have = {r["t"] for r in rows}
    return {"rows": rows, "missing": [t for t in ("q1", "q2") if t not in have], "dropped": dropped, "extras": out}


def noinput_outcome(q1: Sequence[Mapping[str, Any]], q2: Sequence[Mapping[str, Any]]) -> str | None:
    """입력 결손 셀을 닫는 결과(m3-cells 3.6 의 정산표) — 처음 맞는 줄이다.

    | q1 | q2 | 결과 | 셀 |
    | 영향 있음(yes)이 하나라도 | 무엇이든 | impact | reviewed(basis noinput) |
    | yes 없고 모름(unknown) 있음 | 무엇이든 | unknown | no_input |
    | 전부 없음(no) | 확인할 항목 ≥1 | request | no_input |
    | 전부 없음(no) | 항목 0(까닭만) | none | reviewed(basis noinput) |
    q1 이나 q2 가 한 줄도 없으면 None 이다(답이 모자라다 — 정산이 내용 탓 실패로 센다)."""
    if not q1 or not q2:
        return None
    impacts = {str(r.get("impact")) for r in q1}
    if "yes" in impacts:
        return "impact"
    if "unknown" in impacts:
        return "unknown"
    return "request" if any(_text(r.get("item")).strip() for r in q2) else "none"


def _accept_sweep(raw_rows: list, sent: list[str], page_units: list[str], extras: dict, *, stamp: bool) -> dict:
    sent_set = set(sent)
    units = set(page_units)
    dropped: list[dict] = []
    picked: dict[str, dict] = {}
    handoffs: list[dict] = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            _drop(dropped, "not_object", raw)
            continue
        t = raw.get("t")
        if t == "h":
            handoffs.append({"unit_id": _text(raw.get("unit_id")), "to": _text(raw.get("to")),
                             "why": _text(raw.get("why"))})
            continue
        if t != "u":
            _drop(dropped, "foreign_row", raw)
            continue
        unit_id = _text(raw.get("unit_id"))
        if unit_id not in units:
            _drop(dropped, "unit_outside_call", raw)
            continue
        if unit_id in picked:
            _drop(dropped, "duplicate", raw)
            continue
        rel = _text(raw.get("rel"))
        if rel not in RELS:
            _drop(dropped, "bad_enum", raw)
            continue
        aliases = as_list(raw.get("k"))
        outside = [a for a in aliases if a not in sent_set]
        if outside:
            _drop(dropped, "alias_outside_call", {"unit_id": unit_id, "k": outside})
        picked[unit_id] = {"unit_id": unit_id, "rel": rel, "k": [a for a in dict.fromkeys(aliases) if a in sent_set],
                           "why": _text(raw.get("why"))}
    seen = {a for row in picked.values() for a in row["k"]}
    rows = [picked[u] for u in page_units if u in picked]
    return {"rows": rows, "missing": [u for u in page_units if u not in picked], "dropped": dropped,
            "extras": dict(extras, cards_unseen=[a for a in sent if a not in seen], handoffs=handoffs, stamp=stamp)}


def sweep_accounting(calls: Sequence[Mapping[str, Any]]) -> dict:
    """훑기 호출 여럿(묶음 × 쪽)을 단위·카드로 모은다. calls = [{sent_aliases, page_units, result}].

    단위마다 rel 은 묶음들의 답 가운데 가장 넓은 것이다(yes > maybe > error > stamp > no) — 한 묶음이 no, 다른 묶음이 maybe 면
    maybe 다. 품질 `stamp` 가 선 호출의 no 는 믿지 않고 stamp 로 적는다. 그 쪽의 답에 없는 단위는 error 다(셀 분류에는 쓰지
    않는다 — M2 는 늘 대조로 간다). 실은 호출 어디에서도 어느 `u` 줄의 `k` 에 나오지 않은 카드가 `cards_unseen` 이다 — 훑기에서
    그 카드가 읽혔다는 증거가 없다. 훑기가 다른 영역으로 넘긴 `h` 줄은 handoffs 에 모은다(전문가 보고서의 넘김 절).
    반환 {units{unit_id: {rel, k[], why[], missing_in}}, units_error[], cards_unseen[], handoffs[], dropped}.
    """
    units: dict[str, dict] = {}
    sent_all: list[str] = []
    seen: set[str] = set()
    dropped: list[dict] = []
    handoffs: list[dict] = []
    for call in calls:
        accepted = accept_rows(call["result"], kind="sweep", sent_aliases=call["sent_aliases"], pack={"cards": []},
                               page_units=call["page_units"])
        stamp = accepted["extras"]["stamp"]
        sent_all.extend(str(a) for a in call["sent_aliases"])
        dropped.extend(accepted["dropped"])
        handoffs.extend(accepted["extras"]["handoffs"])
        for row in accepted["rows"]:
            rel = "stamp" if stamp and row["rel"] == "no" else row["rel"]
            entry = units.setdefault(row["unit_id"], {"rel": rel, "k": [], "why": [], "missing_in": 0})
            if _REL_RANK[rel] > _REL_RANK[entry["rel"]]:
                entry["rel"] = rel
            entry["k"] = sorted(set(entry["k"]) | set(row["k"]))
            if row["why"]:
                entry["why"].append(row["why"])
            seen.update(row["k"])
        for unit_id in accepted["missing"]:
            entry = units.setdefault(unit_id, {"rel": "error", "k": [], "why": [], "missing_in": 0})
            entry["missing_in"] += 1
            if _REL_RANK["error"] > _REL_RANK[entry["rel"]]:
                entry["rel"] = "error"
    return {"units": units, "units_error": sorted(u for u, e in units.items() if e["rel"] == "error"),
            "cards_unseen": [a for a in dict.fromkeys(sent_all) if a not in seen], "handoffs": handoffs, "dropped": dropped}


# ---------------------------------------------------------------- 실효 판정(설계서 §3.8.7 + X1-14)
def _pair(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("applies") or ""), str(row.get("judgement") or "")


def _weight(row: Mapping[str, Any]) -> int:
    return _WEIGHT.get(str(row.get("judgement") or ""), -1)


def effective_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict]:
    """한 셀의 판정 행(카드 × 변형) → record_id 마다 실효 하나.

    | 가진 행 | 실효 | 표기 |
    | fwd 뿐 | fwd | — |
    | fwd · rev 가 같다 | fwd | agree 1 |
    | fwd · rev 가 다르고 solo 가 있다 | solo | agree 0, solo 가 fwd 와 다르면 flipped |
    | fwd · rev 가 다르고 solo 가 없다 | 더 무거운 쪽(FAIL > WARNING > undetermined > OK > na) | agree 0, disputed |
    | fwd 와 solo | solo | 다르면 flipped |
    견주는 것은 (applies, judgement) 쌍이다. 어느 변형이든 FAIL·WARNING 이 있었는데 실효가 OK·na 면 실효를 undetermined 로 두고
    split · disputed 를 단다(X1-14 — 세 번 중 두 번 걸린 카드가 '문제없음' 으로 세지지 않게). `claimed` 는 변형 가운데 가장
    무거운 판정이다(승격 때 judgement_claimed).
    반환 {record_id: {variant, applies, judgement, claimed, agree, split, flipped, disputed}}.
    """
    grouped: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["record_id"]), {}).setdefault(str(row.get("variant") or "fwd"), row)
    out: dict[str, dict] = {}
    for record_id, by_variant in grouped.items():
        fwd, rev, solo = by_variant.get("fwd"), by_variant.get("rev"), by_variant.get("solo")
        base = fwd if fwd is not None else rev
        agree = int(_pair(fwd) == _pair(rev)) if fwd is not None and rev is not None else None
        flipped = disputed = False
        if solo is not None:
            chosen = solo
            flipped = base is not None and _pair(solo) != _pair(base)
        elif agree == 0:
            chosen = rev if _weight(rev) > _weight(fwd) else fwd
            disputed = True
        else:
            chosen = base
        applies, judgement = _pair(chosen)
        variants = list(by_variant.values())
        split = 0
        if any(str(r.get("judgement")) in FLAGGED for r in variants) and judgement in CLEAR:
            judgement, split, disputed = "undetermined", 1, True
            if applies == "no":
                applies = "unknown"
        out[record_id] = {
            "variant": next(v for v, r in by_variant.items() if r is chosen), "applies": applies,
            "judgement": judgement, "claimed": str(max(variants, key=_weight).get("judgement")),
            "agree": agree, "split": split, "flipped": flipped, "disputed": disputed}
    return out


def mark_effective(rows: Sequence[Mapping[str, Any]]) -> list[dict]:
    """판정 행 복사본에 `is_effective`(실효 변형 행만 1)·`agree`·`split`(그 카드의 행 전부)을 채운다 — 쓰기 직전에 부른다."""
    effective = effective_rows(rows)
    out: list[dict] = []
    for row in rows:
        eff = effective[str(row["record_id"])]
        out.append(dict(row, is_effective=int(str(row.get("variant") or "fwd") == eff["variant"]),
                        agree=eff["agree"], split=eff["split"]))
    return out


def cell_tally(effective: Mapping[str, Mapping[str, Any]]) -> dict:
    """실효 판정의 셈 — 판정별 수는 실효 판정(split 이면 undetermined)으로 세어 합이 `cards_judged` 와 같고, `n_disputed`·
    `n_flipped` 는 그 위에 겹쳐 세는 표지다."""
    counts = {f"n_{j.lower()}": 0 for j in JUDGEMENTS}
    for eff in effective.values():
        counts[f"n_{str(eff['judgement']).lower()}"] += 1
    return {"cards_judged": len(effective), "n_fail": counts["n_fail"], "n_warning": counts["n_warning"],
            "n_ok": counts["n_ok"], "n_na": counts["n_na"], "n_undetermined": counts["n_undetermined"],
            "n_disputed": sum(1 for e in effective.values() if e["disputed"]),
            "n_flipped": sum(1 for e in effective.values() if e["flipped"])}


# ---------------------------------------------------------------- 표본·이중 판정(결정론 — 난수를 쓰지 않는다)
def sample_score(purpose: str, *parts: str, salt: str = SAMPLE_SALT) -> float:
    """sha256('|'.join((purpose, salt, *parts))) 의 앞 12 hex 를 [0, 1) 로 옮긴다. 같은 인자면 같은 값이다."""
    digest = hashlib.sha256("|".join((purpose, salt, *map(str, parts))).encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(16 ** 12)


def effective_body_sha(request: Mapping[str, Any]) -> str:
    """엔진이 실제로 보는 본문의 해시 — 변형 표지를 빼고 카드를 엔진이 놓을 순서(rev 면 뒤집은 순서)로 둔다."""
    body = {k: v for k, v in request.items() if k != "variant"}
    cards = list(request.get("cards") or ())
    if request.get("variant") == "rev":
        cards.reverse()
    body["cards"] = cards
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def dual_plan(fwd_request: Mapping[str, Any], *, dual_rate: float = 1.0, sample_key: Sequence[str] = (),
              salt: str = SAMPLE_SALT) -> dict:
    """fwd 판정 요청 하나의 이중 판정 계획 — {rev: 요청 | None, solo: [별칭…], reason}.

    `dual_rate` 가 1 이상이면 전량(M2 의 잡 knobs), 아니면 `sample_score('dual', *sample_key) < dual_rate` 인 셀만이다. rev 요청은
    fwd 요청에서 `variant` 만 'rev' 로 바꾼 것이다(카드 순서는 엔진이 뒤집는다). 엔진이 보는 본문이 fwd 와 같으면(카드 1장 묶음)
    rev 를 부르지 않고 그 카드를 solo 로 보낸다 — 같은 요청을 두 번 받아 일치율이 공짜로 오르지 않게(X1-20, agree 는 NULL).
    """
    if fwd_request.get("kind") != "verdict" or fwd_request.get("variant") != "fwd":
        raise ValueError("dual_plan 은 verdict·fwd 요청만 받는다")
    if dual_rate < 1.0 and not sample_score("dual", *sample_key, salt=salt) < dual_rate:
        return {"rev": None, "solo": [], "reason": "not_sampled"}
    rev = dict(copy.deepcopy(dict(fwd_request)), variant="rev")
    if effective_body_sha(rev) == effective_body_sha(fwd_request):
        return {"rev": None, "solo": [str(c.get("alias")) for c in fwd_request.get("cards") or ()],
                "reason": "same_body"}
    return {"rev": rev, "solo": [], "reason": "dual"}


# ---------------------------------------------------------------- 거른 셀의 놓침(M3 C3-7 — X1-13 · m3-cells 3.4)
AUDIT_OUTCOMES: tuple[str, ...] = ("risk_miss", "relevance_miss", "undetermined", "kept")
SEV_MINOR = "경미"


def _offcard_risk(row: Mapping[str, Any]) -> bool:
    """카드 밖 줄이 리스크 놓침인가 — 방향이 리스크이고 심각도가 경미가 아니다. 중대·치명이 그렇고, 심각도가 비었거나 모르는 값인
    리스크도 그쪽에 둔다(모르는 것을 깨끗한 쪽에 넣지 않는다 — 놓침을 넓히는 쪽이 안전하다)."""
    return str(row.get("dir") or "risk") == "risk" and str(row.get("sev") or "") != SEV_MINOR


def audit_outcome(effective: Mapping[str, Mapping[str, Any]], offcard_rows: Sequence[Mapping[str, Any]]) -> str:
    """표본·그림자 셀 하나의 놓침 판정 — 처음 맞는 줄이다(X1-13 · m3-cells 3.4).

    | risk_miss | 실효 FAIL·WARNING 이 하나라도(실효 undetermined 이면서 split=1 — 변형이 걸렸던 카드 — 포함), 또는 카드 밖
    |           | 리스크의 심각도가 경미가 아니다(`_offcard_risk`) |
    | relevance_miss | 걸림은 없지만 applies='yes' 실효 행이나 카드 밖 줄(경미 리스크 · 개선)이 있다 |
    | undetermined | 위 둘이 아니고 applies='unknown' 이거나 판정이 undetermined 인 실효 행이 있다 |
    | kept | 실효가 전부 해당 없음이고 카드 밖이 없다 |

    `effective` 는 `effective_rows` 의 반환, `offcard_rows` 는 카드 밖 회계(`accept_rows(kind='offcard')`)의 rows 다.
    넓힘(그 영역의 거른 셀을 다시 연다)을 일으키는 것은 risk_miss 뿐이다.
    """
    rows = list(effective.values())
    if any(str(e.get("judgement")) in FLAGGED or (str(e.get("judgement")) == "undetermined" and int(e.get("split") or 0))
           for e in rows) or any(_offcard_risk(f) for f in offcard_rows):
        return "risk_miss"
    if any(str(e.get("applies")) == "yes" for e in rows) or offcard_rows:
        return "relevance_miss"
    if any(str(e.get("applies")) == "unknown" or str(e.get("judgement")) == "undetermined" for e in rows):
        return "undetermined"
    return "kept"


# ---------------------------------------------------------------- 걸린 것만 이중 판정 · 1순위 보정 · 무작위 뒤집기(M3 C3-9 — #31 · #32)
DUAL_NEG_TRIGGER = 0.05             # 보정 모집단의 '걸림 없음 → 걸림' 비율이 이것을 넘으면 그 대상에서 무작위 뒤집기를 켠다(#32)
DUAL_REASONS: tuple[str, ...] = ("dual", "single_flag", "none_flagged", "same_body", "calib", "dual_neg")


def dual_neg_state(calib_rows: Sequence[Mapping[str, Any]], *, tier_a_closed: bool, already_on: bool = False) -> dict:
    """무작위 뒤집기를 켜나(#32) — 원장에서 유도한다(저장하지 않는다). 반환 {state: on · off · unmeasured, n, flips, rate}.

    `calib_rows` 는 보정 모집단(1순위 셀 — 묶음 전체를 rev 했다)의 판정 행 [{unit_id, agent_key, record_id, variant, judgement}].
    셀 × 카드마다 fwd 가 걸림 없음(OK·na)이고 rev 행이 있는 것이 분모, 그 가운데 rev 가 걸림(FAIL·WARNING)인 것이 분자다.
    한 번 켜지면 꺼지지 않는다(`already_on` — 그 대상의 셀 가운데 `sample_json.dual_neg.on` 이 선 것이 있다). 1순위 셀이 다
    종결되기 전이거나(분류 8 번 줄이 풀리는 때와 같다) 잴 카드가 없으면 '미측정' 이고 켜지 않는다.
    """
    pairs: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in calib_rows:
        key = (str(row.get("unit_id")), str(row.get("agent_key")), str(row.get("record_id")))
        pairs.setdefault(key, {})[str(row.get("variant") or "fwd")] = str(row.get("judgement") or "")
    measured = [p for p in pairs.values() if p.get("fwd") in CLEAR and "rev" in p]
    flips = sum(1 for p in measured if p.get("rev") in FLAGGED)
    rate = flips / len(measured) if measured else None
    if already_on:
        state = "on"
    elif not tier_a_closed or rate is None:
        state = "unmeasured"
    else:
        state = "on" if rate > DUAL_NEG_TRIGGER else "off"
    return {"state": state, "n": len(measured), "flips": flips, "rate": rate}


def engine_conflict(row: Mapping[str, Any]) -> bool:
    """엔진이 그 판정 행에 부딪침을 알렸나(RB3-1) — 같은 카드의 다른 판정과 부딪쳤거나(`checks.dup_conflict`) 보충이 판정을 갈아
    끼웠다(`flipped_from`). 그런 행은 '문제없음' 으로 믿지 않고 걸린 것처럼 두 번째 판정을 받는다(rev 또는 단독). `checks_json`(원장
    행) 또는 `checks`(받은 행) 어느 쪽이든 읽는다."""
    checks = row.get("checks")
    if not isinstance(checks, Mapping):
        try:
            checks = json.loads(row.get("checks_json") or "{}")
        except (TypeError, ValueError):
            checks = {}
    return isinstance(checks, Mapping) and (checks.get("dup_conflict") is True or bool(checks.get("flipped_from"))
                                            or bool(row.get("flipped_from")))


def _alias_order(alias: Any) -> tuple[int, str]:
    """팩 별칭(K01…)은 팩 순서로 매겨진다(엔진 `assign_aliases`) — 숫자 순서가 팩 순서다."""
    text = str(alias or "")
    return (int(text[1:]), text) if text[1:].isdigit() else (1 << 30, text)


def _flagged_rev(fwd_request: Mapping[str, Any], flagged: Sequence[str]) -> dict:
    """걸린 별칭만 실은 rev 요청 — 카드는 fwd 순서 그대로(엔진이 뒤집는다), 빠진 묶음 카드는 제목 목록(digest)으로 내려 팩 순서로
    둔다. `engine_client.run_body('verdict', variant='rev', cards=걸린 별칭, digest=팩의 나머지)` 와 같은 본문이다."""
    keep = set(flagged)
    rev = dict(copy.deepcopy(dict(fwd_request)), variant="rev")
    cards = list(rev.get("cards") or ())
    rev["cards"] = [c for c in cards if str(c.get("alias")) in keep]
    moved = [{k: (None if c.get(k) is None else str(c.get(k))) for k in ("alias", "type", "title", "record_id", "card_id")}
             for c in cards if str(c.get("alias")) not in keep]
    rev["digest"] = sorted([*(rev.get("digest") or ()), *moved], key=lambda d: _alias_order(d.get("alias")))
    return rev


def dual_plan_flagged(fwd_request: Mapping[str, Any], flagged_aliases: Collection[str], *, calibrate: bool = False,
                      neg_on: bool = False, neg_pct: float = 0.0, sample_key: Sequence[str] = (),
                      salt: str = SAMPLE_SALT) -> dict:
    """fwd 판정 요청(묶음 하나)의 이중 판정 계획 — `knobs.dual='flagged'` 의 길. 반환 {rev, solo, reason, aliases, neg{on, picked}}.

    `flagged_aliases` 는 그 셀 · 묶음에서 fwd 실효(빠진 카드 재질의 뒤)가 FAIL·WARNING 인 별칭이다. 처음 맞는 줄이다.

    | 1순위 셀(`calibrate` — 보정 모집단) | 묶음 전체 rev — `calib` |
    | 걸린 별칭 둘 이상 | 그 별칭만 실은 rev 한 번 — `dual` |
    | 걸린 별칭 하나 | rev 없이 그 카드의 단독 재질의가 두 번째 판정 — `single_flag` |
    | 걸림 없음 · 무작위 뒤집기가 켜졌고 `sample_score('dual_neg', T, u, a, 묶음) < neg_pct/100` | 묶음 전체 rev — `dual_neg` |
    | 걸림 없음 | rev 없음 — `none_flagged` |

    묶음 전체 rev 가 fwd 와 같은 본문이면(카드 1장 묶음) 부르지 않고 그 카드를 단독으로 보낸다(`same_body` — `dual_plan` 과 같다).
    `aliases` 는 rev 에 실은 별칭(셀의 `dual_aliases` — 단독 재질의의 'rev 를 물었는데 rev 행이 없다' 갈래가 이것으로 판단한다).
    """
    if fwd_request.get("kind") != "verdict" or fwd_request.get("variant") != "fwd":
        raise ValueError("dual_plan_flagged 는 verdict·fwd 요청만 받는다")
    order = [str(c.get("alias")) for c in fwd_request.get("cards") or ()]
    wanted = {str(a) for a in flagged_aliases}
    flagged = [a for a in order if a in wanted]
    neg = {"on": bool(neg_on) and neg_pct > 0, "picked": False}

    def whole(reason: str) -> dict:
        rev = dict(copy.deepcopy(dict(fwd_request)), variant="rev")
        if effective_body_sha(rev) == effective_body_sha(fwd_request):
            return {"rev": None, "solo": order, "reason": "same_body", "aliases": [], "neg": neg}
        return {"rev": rev, "solo": [], "reason": reason, "aliases": order, "neg": neg}

    if calibrate:
        return whole("calib")
    if len(flagged) >= 2:
        return {"rev": _flagged_rev(fwd_request, flagged), "solo": [], "reason": "dual", "aliases": flagged, "neg": neg}
    if len(flagged) == 1:
        return {"rev": None, "solo": flagged, "reason": "single_flag", "aliases": [], "neg": neg}
    if neg["on"] and sample_score("dual_neg", *sample_key, salt=salt) < neg_pct / 100.0:
        neg["picked"] = True
        return whole("dual_neg")
    return {"rev": None, "solo": [], "reason": "none_flagged", "aliases": [], "neg": neg}
