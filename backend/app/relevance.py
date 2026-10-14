# 검토 셀 거르기의 순수 판정 — 변경 → 메커니즘 → 영역 코드 신호(M3 C3-5)·훑기 신호·셀 경로 결정표(m3-cells 3.2)
"""저장소·네트워크 없는 순수 함수만 둔다. 셀 원장에 쓰는 일(`_classify`)은 검토 루프(C3-6)의 몫이다.

- 코드 신호 — 단위 줄의 `code` 를 `assets/change-routing.v1.json` 의 `codes`(정확 일치, 없으면 끝이 `*` 인 가장 긴 접두)로
  찾고, 없으면 줄에 실린 `change_kind` 를 `change_kinds` 로 찾는다. 그 메커니즘을 배정표(택소노미 1.2 의 `domains_for`)로 영역에
  잇고, 부품 역할 → 영역(`roles`)을 더한다. 풀리지 않는 줄이 하나라도 있으면 관련이 아닌 영역 전부가 '모름' 이다.
  저장된 단위 줄에는 `change_kind` 가 없다(`units._item` 은 빌드 끝에 떼어 낸다) — 그래서 표는 생산자가 내는 코드를 `codes`
  만으로 전부 푼다(시험 `test_every_producer_code_resolves_by_code_alone`). `change_kinds` 는 줄이 그 칸을 실어 올 때의 그물이다.
- 승인 문(#40) — 배정표의 `review_status` 와 이 표의 `review_status` 가 둘 다 `approved` 가 아니면 코드 신호는 전 영역 '모름' 이다.
  잡은 만들 때의 승인 여부를 얼려 `approved` 로 넘긴다(승인 커밋은 다음 잡부터 듣는다).
- 경로 결정표 — 처음 맞는 줄이다. 모르면 검토다. 거름은 두 신호가 다 '무관' 일 때뿐이고 표본 해시 아래면 끝까지 판정한다.

택소노미와 닿는 곳은 `_taxonomy()` 하나다(형제 꾸러미 S3-2 의 택소노미 1.2 — `domains_for` · `mech_owners_meta` ·
`load_taxonomy`). 모든 함수가 `tax=` 로 그 대역을 받는다.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app import ir_builder, taxonomy
from app.review_verify import SAMPLE_SALT, sample_score

ROUTING_ASSET = "change-routing"
APPROVED = "approved"
VERDICTS: tuple[str, ...] = ("related", "unrelated", "unknown")
FILTER_MODES: tuple[str, ...] = ("off", "shadow", "on")
DECISIONS: tuple[str, ...] = ("filtered", "review", "audit")
SWEEP_GAP_REV = 2                  # 결측 블록을 아는 훑기 판(cr-sweep-2) — 그 판의 답일 때만 입력 결손 전문가의 셀을 거른다
_SWEEP_REV = re.compile(r"^cr-sweep-(\d+)$")
ROLE_NAMES: frozenset[str] = frozenset(ir_builder.SEED_SYNONYMS.values())

# 강제 줄(m3-cells 3.2 의 1~8) — (규칙 이름, 셀의 route_forced). 대상 전체 끔은 1 번과 같은 route_forced 를 쓴다.
FORCING_RULES: tuple[tuple[str, str], ...] = (
    ("filter_off", "filter_off"), ("rank1", "rank1"), ("global_unit", "global_unit"), ("no_cards", "no_cards"),
    ("input_gap", "input_gap"), ("widened", "widened"), ("target_off", "filter_off"), ("handoff", "handoff"),
    ("tier_a_pending", "tier_a_pending"))


def _taxonomy() -> Any:
    """택소노미 1.2 의 읽는 함수를 가진 것 — `app.taxonomy` 모듈이다(`domains_for` · `mech_owners_meta` · `load_taxonomy`, 형제
    꾸러미 S3-2). 시험은 `tax=` 로 승인 칸만 바꿔 보이는 사본을 준다."""
    return taxonomy


# ---------------------------------------------------------------- 표와 판
def load_routing() -> dict:
    """`assets/change-routing.v1.json`(프로세스 캐시)."""
    return taxonomy.load_json(ROUTING_ASSET)


def domain_codes(tax: Any = None) -> tuple[str, ...]:
    """택소노미 영역 코드(15) — 로스터 영역과 같은 어휘다."""
    tax = tax or _taxonomy()
    return tuple(str(d["code"]) for d in tax.load_taxonomy()["axes"]["domain"])


def routing_approved(*, routing: Mapping[str, Any] | None = None, tax: Any = None) -> bool:
    """승인 문(#40) — 배정표와 이 표가 둘 다 `approved` 인가. 잡을 만들 때 한 번 읽어 `knobs.routing_approved` 로 얼린다."""
    routing = routing if routing is not None else load_routing()
    tax = tax or _taxonomy()
    meta = tax.mech_owners_meta() or {}
    return routing.get("review_status") == APPROVED and meta.get("review_status") == APPROVED


def routing_rev(*, routing: Mapping[str, Any] | None = None, tax: Any = None) -> str:
    """판 표지 `change-routing 판 | mech-owners-<배정표 판> | tax-<택소노미 판>` — 셀 `route_json` 과 잡 `knobs` 에 얼린다."""
    routing = routing if routing is not None else load_routing()
    tax = tax or _taxonomy()
    meta = tax.mech_owners_meta() or {}
    return f"{routing['version']}|mech-owners-{meta.get('version')}|tax-{tax.load_taxonomy().get('taxonomy_version')}"


# ---------------------------------------------------------------- 줄 → 메커니즘
def _code_table(routing: Mapping[str, Any]) -> tuple[dict[str, tuple[str, ...]], list[tuple[str, tuple[str, ...]]]]:
    exact: dict[str, tuple[str, ...]] = {}
    prefixes: list[tuple[str, tuple[str, ...]]] = []
    for entry in routing.get("codes") or ():
        match, mechs = str(entry["match"]), tuple(str(m) for m in entry["mechanisms"])
        if match.endswith("*"):
            prefixes.append((match[:-1], mechs))
        else:
            exact[match] = mechs
    prefixes.sort(key=lambda p: -len(p[0]))
    return exact, prefixes


def code_mechanisms(code: str, routing: Mapping[str, Any]) -> tuple[str, ...] | None:
    """변경 코드 하나 → 후보 메커니즘. 정확 일치가 먼저, 없으면 가장 긴 `*` 접두. 표에 없으면 None."""
    exact, prefixes = _code_table(routing)
    if code in exact:
        return exact[code]
    return next((mechs for prefix, mechs in prefixes if code.startswith(prefix)), None)


def line_mechanisms(line: Mapping[str, Any], routing: Mapping[str, Any]) -> tuple[str, ...] | None:
    """단위 줄 하나 → 후보 메커니즘. `codes` 로 못 풀면 줄의 `change_kind` 를 `change_kinds` 로 본다. 둘 다 없거나 값이 null
    이면 None('풀리지 않는 줄'). 빈 튜플은 '설계 변경이 아니다'(메시 밀도 등) — 관련도 모름도 아니다."""
    mechs = code_mechanisms(str(line.get("code") or ""), routing)
    if mechs is not None:
        return mechs
    kinds = routing.get("change_kinds") or {}
    kind = line.get("change_kind")
    if kind is None or kind not in kinds or kinds[kind] is None:
        return None
    return tuple(str(m) for m in kinds[kind])


def part_roles(names: Iterable[Any]) -> list[str]:
    """부품 이름 → 역할(ir_builder.SEED_SYNONYMS 의 정규명 10종). 이름을 정규화한 토큰의 어느 자리에서든 1~3토큰 창이 정규명이나
    그 동의어면 그 역할이다. 역할은 영역을 더하기만 한다 — 모르는 이름은 아무것도 만들지 않는다('모름' 도 아니다)."""
    found: set[str] = set()
    for name in names:
        tokens = [t for t in ir_builder.name_norm_canon(ir_builder.name_norm(str(name or ""))).split("_") if t]
        for i in range(len(tokens)):
            for width in (3, 2, 1):
                chunk = tokens[i:i + width]
                if len(chunk) < width:
                    continue
                window = "_".join(chunk)
                role = window if window in ROLE_NAMES else ir_builder.SEED_SYNONYMS.get(window)
                if role:
                    found.add(role)
    return sorted(found)


# ---------------------------------------------------------------- 코드 신호
def code_signal(lines: Sequence[Mapping[str, Any]], part_names: Iterable[Any], *, approved: bool,
                routing: Mapping[str, Any] | None = None, tax: Any = None) -> dict[str, dict]:
    """한 단위의 코드 신호 — {영역: {verdict, via{mech[], role[], always}, unmapped[], reason}}.

    `related` = 그 영역이 (줄 메커니즘 → 배정표의 소유 ∪ 관련) ∪ (역할 → 영역) ∪ `always` 에 든다. `unknown` = 풀리지 않는 줄
    (`unmapped` — 표에 없는 코드, 또는 배정표에 행이 없는 메커니즘 `mech:<코드>`)이 있고 그 영역이 `related` 가 아니다. 나머지는
    `unrelated`. 승인 문이 닫혀 있으면(`approved` 거짓) 전 영역 `unknown`(사유 `not_approved`) 이다.
    """
    routing = routing if routing is not None else load_routing()
    tax = tax or _taxonomy()
    domains = domain_codes(tax)
    if not approved:
        return {d: {"verdict": "unknown", "via": {"mech": [], "role": [], "always": False}, "unmapped": [],
                    "reason": "not_approved"} for d in domains}
    owners_of: dict[str, Mapping[str, str]] = {}
    via_mech: dict[str, set[str]] = {d: set() for d in domains}
    via_role: dict[str, set[str]] = {d: set() for d in domains}
    unmapped: set[str] = set()
    for line in lines:
        mechs = line_mechanisms(line, routing)
        if mechs is None:
            unmapped.add(str(line.get("code") or ""))
            continue
        for mech in mechs:
            if mech not in owners_of:
                owners_of[mech] = dict(tax.domains_for([mech]) or {})
            if not owners_of[mech]:
                unmapped.add(f"mech:{mech}")
            for domain in owners_of[mech]:
                if domain in via_mech:
                    via_mech[domain].add(mech)
    roles = routing.get("roles") or {}
    for role in part_roles(part_names):
        for domain in roles.get(role) or ():
            if domain in via_role:
                via_role[domain].add(role)
    always = {str(d) for d in routing.get("always") or ()}
    out: dict[str, dict] = {}
    for d in domains:
        related = bool(via_mech[d] or via_role[d] or d in always)
        verdict = "related" if related else ("unknown" if unmapped else "unrelated")
        out[d] = {"verdict": verdict, "via": {"mech": sorted(via_mech[d]), "role": sorted(via_role[d]), "always": d in always},
                  "unmapped": sorted(unmapped), "reason": "unmapped" if verdict == "unknown" else None}
    return out


def code_for(signal: Mapping[str, Mapping[str, Any]], domain: str) -> dict:
    """한 셀(영역 d)의 `route_json.code` — 그 영역의 신호에 관련 영역 목록을 붙인다. 택소노미에 없는 영역(로스터 영역 손잡이로
    더한 영역)은 `unknown`(사유 `domain_unknown`) 이다 — 거르는 쪽에 서지 않는다."""
    own = signal.get(domain) or {"verdict": "unknown", "via": {"mech": [], "role": [], "always": False}, "unmapped": [],
                                 "reason": "domain_unknown"}
    return {"verdict": own["verdict"], "related_domains": sorted(d for d, s in signal.items() if s["verdict"] == "related"),
            "via": own["via"], "unmapped": own["unmapped"], "reason": own["reason"]}


# ---------------------------------------------------------------- 훑기 신호
def sweep_signal(entry: Mapping[str, Any] | None, *, failed: bool = False) -> dict:
    """훑기 회계(`review_verify.sweep_accounting` 의 units[unit_id]) → {verdict, rel, k, why, stamp, reason}.

    `unrelated` 는 `rel == 'no'` 이고 `k` 가 빌 때뿐이다(도장 찍힌 no 는 회계가 이미 `stamp` 로 적었다). yes·maybe 와 k 가 달린
    no 는 `related`, stamp·error·답에 없는 단위·훑기 실패는 `unknown` 이다 — 거르는 쪽에 서지 않는다. 엔진이 부딪침 표지를 단 no 도
    `unknown`(reason engine_conflict)이다.
    """
    if failed:
        return {"verdict": "unknown", "rel": None, "k": [], "why": [], "stamp": False, "reason": "sweep_failed"}
    if entry is None:
        return {"verdict": "unknown", "rel": None, "k": [], "why": [], "stamp": False, "reason": "no_answer"}
    rel = str(entry.get("rel") or "")
    k = [str(a) for a in entry.get("k") or ()]
    reason = None
    if rel == "no" and not k and entry.get("conflict"):
        # 엔진이 그 '무관' 줄에 부딪침 표지(다툼 · 보충 · dup_conflict)를 달았다 — 믿지 않는다(D-42 ④ · 반대 검토 HIGH 2)
        verdict, reason = "unknown", "engine_conflict"
    elif rel == "no" and not k:
        verdict = "unrelated"
    elif rel in ("yes", "maybe", "no"):
        verdict = "related"
    else:
        verdict, reason = "unknown", rel or None
    return {"verdict": verdict, "rel": rel or None, "k": k, "why": [str(w) for w in entry.get("why") or ()],
            "stamp": rel == "stamp", "reason": reason}


def sweep_gap_aware(sent_missing: bool, prompt_rev: Any) -> bool:
    """입력 결손 전문가의 훑기가 결측 블록을 받은 판의 답인가 — 요청에 `extra.missing` 을 실었고 답의 `meta.prompt_rev.sweep` 이
    `cr-sweep-2` 이상이다. 모르는 판 표기는 아니다(거르지 않는 쪽)."""
    match = _SWEEP_REV.match(str(prompt_rev or ""))
    return bool(sent_missing) and match is not None and int(match.group(1)) >= SWEEP_GAP_REV


# ---------------------------------------------------------------- 경로 결정표(m3-cells 3.2 · M3.md 4.9)
def route_decision(*, filter_mode: str, rank1: bool, unit_kind: str, no_cards: bool, input_gap: bool,
                   gap_aware: bool, widened: bool, target_off: bool, handoffs: Sequence[Mapping[str, Any]],
                   tier_a_pending: bool, code: Mapping[str, Any], sweep: Mapping[str, Any], sample_key: Sequence[Any],
                   audit_pct: float, salt: str = SAMPLE_SALT, routing_rev: str | None = None) -> dict:
    """셀 (단위 u, 전문가 a, 영역 d) 하나의 경로 — 처음 맞는 줄이다.

    | # | 조건 | 결과 · route_forced |
    | 1 | 잡의 거르기 `off` | 검토 · filter_off |
    | 2 | a 가 그 영역 1순위 | 검토 · rank1(9 번이 참이었을 셀은 그림자) |
    | 3 | u 가 전역 단위 | 검토 · global_unit |
    | 4 | a 의 카드 0장 | 검토 · no_cards |
    | 5 | a 가 입력 결손이고 훑기가 결측 블록을 못 받았다 | 검토(noinput 길) · input_gap |
    | 6 | d 가 넓혀졌다 · 대상 전체 거르기가 꺼졌다 | 검토 · widened · filter_off |
    | 7 | 다른 전문가의 훑기가 u 를 d 로 넘겼다 | 검토 · handoff |
    | 8 | 대상의 1순위 셀이 아직 다 종결되지 않았다 | 검토 · tier_a_pending |
    | 9 | 코드 = 무관 그리고 훑기 = 무관 | 거름 — 표본 해시 < audit_pct/100 이면 표본(audit · filter_audit) |
    | 10 | 그 밖(어느 한쪽이 관련·모름) | 검토 |

    `filter_mode='shadow'` 면 9 번이 참이어도 검토로 보내고 그림자로 적는다. 반환 {decision, route, route_forced,
    would_filter, shadow, route_json}. `would_filter` 는 9 번까지 내려와 두 신호가 다 무관이었던 셀(거를 수 있던 셀 — 거름 +
    표본, 대상 그림자면 그 셀), `shadow` 는 거르지 않았지만 거르기가 닫았을 셀(1순위 셀은 1·2·8 번을 빼고 다시 본다)이다.
    잡 거르기가 `off` 면 부르는 쪽은 아무것도 쓰지 않는다(M2 원장과 바이트가 같게).
    """
    if filter_mode not in FILTER_MODES:
        raise ValueError(f"filter_mode 는 {FILTER_MODES} 가운데 하나다 — {filter_mode!r}")
    hits = {"filter_off": filter_mode == "off", "rank1": bool(rank1), "global_unit": unit_kind == "global",
            "no_cards": bool(no_cards), "input_gap": bool(input_gap) and not gap_aware, "widened": bool(widened),
            "target_off": bool(target_off), "handoff": bool(handoffs), "tier_a_pending": bool(tier_a_pending)}
    forced = [name for name, _token in FORCING_RULES if hits[name]]
    both = code.get("verdict") == "unrelated" and sweep.get("verdict") == "unrelated"
    # 1순위의 그림자 — 그 사람이 1순위가 아니었다면(대상의 1순위 대기도 그 사람 몫이다) 9 번까지 내려왔을까. 잡 거르기 끔(1 번)은
    # 빼지 않는다 — 끈 잡은 그림자도 적지 않는다.
    rank1_shadow = bool(rank1) and both and not [
        name for name in forced if name not in ("rank1", "tier_a_pending")]
    audit: dict | None = None
    if forced:
        rule, decision = forced[0], "review"
        route_forced: str | None = dict(FORCING_RULES)[rule]
        would_filter, shadow = False, rank1_shadow
    elif both:
        rule, would_filter = "both_unrelated", True
        if filter_mode == "shadow":
            decision, route_forced, shadow = "review", None, True
        else:
            score = sample_score("filter_audit", *map(str, sample_key), salt=salt)
            audit = {"score": score, "pct": audit_pct}
            picked = score < float(audit_pct) / 100.0
            decision, route_forced, shadow = ("audit", "filter_audit", False) if picked else ("filtered", None, False)
    else:
        rule, decision, route_forced, would_filter, shadow = "signal_related", "review", None, False, False
    route = {"filtered": "filtered", "audit": "audit"}.get(decision) or ("noinput" if input_gap else "review")
    route_json = {"rule": rule, "decision": decision, "filter": filter_mode, "routing_rev": routing_rev,
                  "code": dict(code), "sweep": dict(sweep), "handoff": [dict(h) for h in handoffs],
                  "forced_all": forced, "audit": audit}
    return {"decision": decision, "route": route, "route_forced": route_forced, "would_filter": would_filter,
            "shadow": shadow, "route_json": route_json}
