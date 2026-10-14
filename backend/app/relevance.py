# 검토 셀 거르기의 순수 판정 — 변경 → 메커니즘 → 영역 코드 신호(M3 C3-5)
"""저장소·네트워크 없는 순수 함수만 둔다. 셀 원장에 쓰는 일(`_classify`)은 검토 루프(C3-6)의 몫이다.

- 코드 신호 — 단위 줄의 `code` 를 `assets/change-routing.v1.json` 의 `codes`(정확 일치, 없으면 끝이 `*` 인 가장 긴 접두)로
  찾고, 없으면 줄에 실린 `change_kind` 를 `change_kinds` 로 찾는다. 그 메커니즘을 배정표(택소노미 1.2 의 `domains_for`)로 영역에
  잇고, 부품 역할 → 영역(`roles`)을 더한다. 풀리지 않는 줄이 하나라도 있으면 관련이 아닌 영역 전부가 '모름' 이다.
  저장된 단위 줄에는 `change_kind` 가 없다(`units._item` 은 빌드 끝에 떼어 낸다) — 그래서 표는 생산자가 내는 코드를 `codes`
  만으로 전부 푼다(시험 `test_every_producer_code_resolves_by_code_alone`). `change_kinds` 는 줄이 그 칸을 실어 올 때의 그물이다.
- 승인 문(#40) — 배정표의 `review_status` 와 이 표의 `review_status` 가 둘 다 `approved` 가 아니면 코드 신호는 전 영역 '모름' 이다.
  잡은 만들 때의 승인 여부를 얼려 `approved` 로 넘긴다(승인 커밋은 다음 잡부터 듣는다).

택소노미와 닿는 곳은 `_taxonomy()` 하나다(형제 꾸러미 S3-2 의 택소노미 1.2 — `domains_for` · `mech_owners_meta` ·
`load_taxonomy`). 모든 함수가 `tax=` 로 그 대역을 받는다.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app import ir_builder, taxonomy

ROUTING_ASSET = "change-routing"
APPROVED = "approved"
VERDICTS: tuple[str, ...] = ("related", "unrelated", "unknown")
ROLE_NAMES: frozenset[str] = frozenset(ir_builder.SEED_SYNONYMS.values())


def _taxonomy() -> Any:
    """택소노미 1.2 의 읽는 함수를 가진 것 — 정본은 `app.taxonomy` 모듈이다(형제 꾸러미 S3-2 가 `domains_for` ·
    `mech_owners_meta` 를 더한다). 가지 m3 에 합치기 전에는 그 두 함수가 없으므로 시험은 `tax=` 로 대역을 준다."""
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
    """한 셀(영역 d)의 `route_json.code` — 그 영역의 신호에 관련 영역 목록을 붙인다."""
    own = signal[domain]
    return {"verdict": own["verdict"], "related_domains": sorted(d for d, s in signal.items() if s["verdict"] == "related"),
            "via": own["via"], "unmapped": own["unmapped"], "reason": own["reason"]}
