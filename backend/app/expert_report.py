# 카드 대조 검토의 전문가 마감 — finding 승격·의견 행·원장 마감(m2-wp3b S9)과 전문가 보고서의 조립(S10, LLM 0회)
"""전문가 한 명의 범위 안 열린 셀이 0 이 되면 검토 루프(`review_runner.finalize_expert`)가 선점을 쥔 채 이 모듈을 부른다.

- `prepare` 는 읽기만 한다 — 원장(셀·판정 행·얼린 팩·단위)에서 finding·보고서·요약·의견 행을 지어 둔다. 무거운 정규화와 조립을
  쓰기 트랜잭션 밖에서 한다(저장소는 연결 하나를 잠금으로 나눠 쓰므로 트랜잭션 안의 읽기가 다른 워커를 붙든다).
- `commit` 은 그것을 한 트랜잭션 안에서 쓴다 — finding(코드가 정하는 열만 고친다, P-12)·인용 역색인·큐레이션 큐·의견 행·원장 마감
  (`planner.close_review_seat`). 같은 원장이면 같은 id 에 같은 값이라 다시 마감해도 같은 자리다.

finding 의 원천은 셋이다 — 실효 FAIL·WARNING(카드 근거), 실효 undetermined 이면서 split=1(변형 하나라도 걸림 — X1-14),
카드 밖 `f` 줄. 셋 다 패널 finding 과 같은 정규화(`narrative._normalize_finding`)를 지나 메커니즘·주체·인용 검증·등급·
cluster_key 가 같은 코드로 정해지고, 한 셀(단위) 안에서 (cluster_key, direction) 으로 접는다. 정책은 hold 하나다(사용자 결정 2) —
등록부로 갈 판정은 WARNING 까지, 심각도는 중대까지이고 원래 값은 judgement_claimed·severity_claimed 에 남는다. M2 에서는 등록부에
병합하지 않는다(M2.md 5절 #7 — 패널 경로는 source_kind='card_review' 를 읽지 않는다, #20). 회수 자격은 0 이다(#9).
"""
from __future__ import annotations

import dataclasses
import gzip
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app import cardpack, export, narrative, planner, render, review_cells, review_quality, review_verify, units
from app.common import canonical_json, now_epoch
from app.errors import AppError

SOURCE_KIND = "card_review"                 # rr_findings.source_kind — 패널 경로가 거르는 값(M2.md 5절 #20)
REPORT_REV = "expert-report-1"
QUOTE_SHOW = 200                            # 보고서 표시·반출의 카드 인용 — 판정당 200자(사용자 결정 1)
SUMMARY_MAX = 1500                          # summary_md — 의견 행 excerpt_for_rag 의 원천
_SEV_RANK = {"경미": 1, "중대": 2, "치명": 3}
_GRADE_RANK = {"경험칙": 1, "도구예측": 2, "문헌·규격": 3, "측정": 4}
_DETECT = {"tool": "sim-detectable", "sim": "sim-detectable", "test": "test-only", "field": "field-only"}
_DETECT_TOOL_MAX = 80                       # 설계서 §3.10.2 — detectability.tool 은 닫는 확인 글의 앞 80자(글 전체는 resolving_check)
_JUDGE_ORDER = ("FAIL", "WARNING", "undetermined", "OK", "na")


def _s(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _json(text: Any, default: Any) -> Any:
    if not text:
        return default
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


# ================================================================ 원장 읽기
@dataclasses.dataclass
class Ledger:
    """한 전문가의 검토 원장 — 마감·보고서가 읽는 것 전부(쓰지 않는다)."""

    target_key: str
    agent_key: str
    head: dict
    target: dict
    order: dict                              # planner.review_order 의 그 전문가 행(영역·순위·tier)
    pack: cardpack.FrozenPack | None
    units: list[dict]                        # 활성 빌드의 검토 대상 단위(seq 순)
    cells: dict[str, dict]                   # unit_id → 셀 행
    rows: dict[str, list[dict]]              # unit_id → 판정 행 전부(변형별)
    payloads: dict[str, dict] = dataclasses.field(default_factory=dict)   # unit_id → units.review_payload(검토한 셀만)
    # pack_key → 검토한 셀이 판정을 받은 얼린 묶음(머리 묶음 밖의 것, 이 박스에 없으면 None — 들여온 원장, M2.md 5절 #22). 별칭은
    # 묶음마다 다시 매기는 이름이라 판정 행의 카드는 늘 그 셀의 묶음에서 record_id 로 찾는다(R3B-2).
    packs: dict[str, cardpack.FrozenPack | None] = dataclasses.field(default_factory=dict)

    @property
    def review_id(self) -> str:
        return str(self.head["review_id"])

    def reviewed(self) -> list[dict]:
        """검토한(reviewed) 셀의 단위 — seq 순."""
        return [u for u in self.units if (self.cells.get(u["unit_id"]) or {}).get("state") == "reviewed"]

    def effective(self, unit_id: str) -> dict[str, dict]:
        """record_id → 실효 판정(실효 변형 행의 열 + effective_rows 의 표기). applies·judgement 는 실효 규칙의 값이다 — 변형이 갈린
        카드(split)는 행에 적힌 변형의 판정이 아니라 undetermined 다(X1-14). 행의 원래 값은 row_applies·row_judgement 에 둔다."""
        rows = self.rows.get(unit_id) or []
        marks = review_verify.effective_rows(rows) if rows else {}
        out: dict[str, dict] = {}
        for row in rows:
            if row["is_effective"]:
                mark = marks[str(row["record_id"])]
                out[str(row["record_id"])] = {**row, "row_applies": row["applies"], "row_judgement": row["judgement"],
                                              **{k: mark[k] for k in ("applies", "judgement", "claimed", "flipped",
                                                                      "disputed")}}
        return out

    def unit_pack(self, unit_id: str) -> cardpack.FrozenPack | None:
        """그 셀이 판정을 받은 얼린 묶음(셀의 pack_hash 칸은 pack_key 다). 묶음 없이 봤거나 이 박스에 없으면 None."""
        key = (self.cells.get(unit_id) or {}).get("pack_hash")
        if not key:
            return None
        if self.pack is not None and key == self.pack.pack_key:
            return self.pack
        return self.packs.get(str(key))

    def pack_state(self, unit_id: str) -> str | None:
        """그 셀을 본 묶음 — current(머리 묶음) · earlier(이 박스에 있는 앞 묶음) · absent(이 박스에 없다) · None(묶음 없이 봤다)."""
        key = (self.cells.get(unit_id) or {}).get("pack_hash")
        if not key:
            return None
        if self.pack is not None and key == self.pack.pack_key:
            return "current"
        return "earlier" if self.packs.get(str(key)) is not None else "absent"

    def unit_cards(self, unit_id: str) -> Mapping[str, Mapping[str, Any]]:
        """record_id → 카드 — 그 셀을 본 얼린 묶음의 카드. 그 묶음이 이 박스에 없으면(들여온 원장) 머리 묶음의 카드로 읽는다(글이
        바뀌었는지는 판정 행의 text_sha 로 견준다 — 보고서의 card_changed)."""
        pack = self.unit_pack(unit_id)
        if pack is None and self.pack_state(unit_id) == "absent":
            pack = self.pack
        return pack.record_cards if pack is not None else {}

    def alias_key(self, alias: str, unit_id: str) -> tuple[int, str]:
        """그 셀 안의 별칭 차례 — 그 셀을 본 묶음의 순서(묶음이 없으면 별칭 글 순서 — 한 묶음의 별칭은 폭이 같다)."""
        pack = self.unit_pack(unit_id)
        order = pack.order if pack is not None else ()
        return (order.index(alias) if alias in order else len(order), alias)


def load_ledger(store: Any, target_key: str, agent_key: str, *, with_pack: bool = True) -> Ledger:
    """그 전문가의 원장을 읽는다. 얼린 묶음을 가리키는데 이 박스에 없으면 cardpack.PackMissing 이다(조용히 '카드 없음' 으로 읽지
    않는다 — 마감은 묶음을 얼린 박스에서만 돈다). `with_pack=False` 는 묶음을 끝내 받지 못한 전문가의 보고서다(묶음 없이 읽는다)."""
    head = store.query_one("SELECT * FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?", (target_key, agent_key))
    target = store.query_one("SELECT target_key, owner_sub, kind, project_id, flow FROM rr_targets WHERE target_key = ?",
                             (target_key,))
    if head is None or target is None:
        raise AppError("E404", f"검토 머리가 없습니다 — {target_key}:{agent_key}.", 404)
    order = next((r for r in planner.review_order(store, target_key) if r["agent_key"] == agent_key), None) or {}
    unit_rows = units.load_units(store, target_key, reviewable_only=True)
    active = {u["unit_id"] for u in unit_rows}
    cells = {r["unit_id"]: dict(r) for r in store.query(
        "SELECT * FROM rr_review_cells WHERE target_key = ? AND agent_key = ?", (target_key, agent_key))
        if r["unit_id"] in active}
    rows: dict[str, list[dict]] = {}
    for r in store.query("SELECT * FROM rr_card_verdicts WHERE target_key = ? AND agent_key = ?"
                         " ORDER BY unit_id, record_id, variant", (target_key, agent_key)):
        if r["unit_id"] in active:
            rows.setdefault(str(r["unit_id"]), []).append(dict(r))
    ledger = Ledger(target_key=target_key, agent_key=agent_key, head=dict(head), target=dict(target), order=dict(order),
                    pack=cardpack.load_for(store, target_key, agent_key) if with_pack else None, units=unit_rows,
                    cells=cells, rows=rows)
    for unit in ledger.reviewed():
        ledger.payloads[unit["unit_id"]] = units.review_payload(store, target_key, unit["unit_id"], agent_key)
        key = _s(ledger.cells[unit["unit_id"]].get("pack_hash"))
        if key and key not in ledger.packs and (ledger.pack is None or key != ledger.pack.pack_key):
            try:
                ledger.packs[key] = cardpack.load_pack(store, agent_key, key)
            except cardpack.PackMissing:
                ledger.packs[key] = None
    return ledger


# ================================================================ finding 승격(S9)
def _mech_parts(mech: Any, mech_free: Any) -> tuple[str, str, str]:
    """(mechanism, mechanism_detail, mechanism_free) — 엔진의 `mech` 는 택소노미 code(`interface.seal_compression`) 또는 'free'.
    택소노미 밖이면 원문을 detail 자리에 두어 정규화가 unclassified 로 내리며 원문을 mechanism_free 에 남기게 한다."""
    code, free = _s(mech).strip(), _s(mech_free).strip()
    if code and code != "free":
        head, _, tail = code.partition(".")
        return head, tail, free
    return "", free, free


def _hold(direction: str, weight: int, claimed: str | None, sev: str | None) -> tuple[str, str]:
    """hold 정책(사용자 결정 2)의 (severity, judgement) — 등록부로 갈 판정은 WARNING 까지, 심각도는 중대까지다. 치명은 FAIL 과만
    짝이라 정규화가 판정을 FAIL 로 고쳐 버리기 때문이다(설계서 §3.10.3). `weight` 는 구성원 가운데 가장 무거운 걸림이다 —
    3 실효 FAIL · 2 실효 WARNING 이나 카드 밖 지적 · 1 변형이 갈려 실효가 undetermined 인 카드(그대로 undetermined, X1-14)."""
    if direction == "improvement":
        return "경미", "OK"
    capped = "중대" if sev in ("중대", "치명") else "경미"
    if weight >= 3:
        return "중대", "WARNING"
    if weight == 2:
        return capped, "WARNING"
    return ("중대" if claimed == "FAIL" else capped), "undetermined"


def _detect(check_kind: Any, check_text: Any) -> tuple[dict, dict | None]:
    kind, text = _s(check_kind).strip(), _s(check_text).strip()
    level = _DETECT.get(kind, "unknown")
    tool = text[:_DETECT_TOOL_MAX] if level == "sim-detectable" else ""
    return {"level": level, "tool": tool}, ({"kind": kind or "unknown", "ref": text} if text else None)


def _ref_rank(ref: str, layers: Mapping[str, str]) -> tuple[int, str]:
    """주체를 뽑는 참조의 차례 — 의미 이벤트 → 구조·파라메트릭 항목 → e: → p: → d: → 그 밖, 같은 급이면 참조 문자열 순."""
    layer = layers.get(ref)
    if layer == "semantic":
        return 0, ref
    if layer in ("structural", "parametric") or ref.startswith("c:"):
        return 1, ref
    return {"e": 2, "p": 3, "d": 4}.get(ref.split(":", 1)[0], 5), ref


def _subject_of(ref: str, ctx: narrative.SpecContext) -> dict | None:
    """참조 하나가 가리키는 항목의 주체 — ckeys(subject.ckeys · ckey · ckey_a/ckey_b · 노드 ckey · 엣지 ck_a/ck_b) 또는 이름
    (dim:·asm:). 쓸 것이 없으면 None."""
    kind = ref.split(":", 1)[0]
    if kind == "d":
        return {"names": [f"dim:{ref.split(':', 1)[1]}"]}
    item: Mapping[str, Any] | None = None
    if kind == "c":
        item = ctx.diff_item(ref)
    elif kind == "p":
        item = ctx.node(ref)
    elif kind == "e":
        item = ctx.edge(ref)
    if not isinstance(item, Mapping):
        return None
    subject = item.get("subject") if isinstance(item.get("subject"), Mapping) else {}
    ckeys = [str(c) for c in subject.get("ckeys") or () if c]
    if not ckeys and item.get("ckey"):
        ckeys = [str(item["ckey"])]
    for a, b in (("ckey_a", "ckey_b"), ("ck_a", "ck_b")):
        if not ckeys and item.get(a) and item.get(b):
            ckeys = [str(item[a]), str(item[b])]
    if ckeys:
        return {"ckeys": ckeys}
    key = _s(item.get("subject_key"))
    if key.startswith(("dim:", "asm:")):
        return {"names": [key]}
    if item.get("asm_key"):
        return {"names": [f"asm:{item['asm_key']}"]}
    return None


def _unit_scope_subject(unit: Mapping[str, Any]) -> dict:
    """참조로 주체를 못 정할 때의 바닥 — 묶음 단위의 범위(조립 접두)·경계 단위의 조립. 그 밖(전역)은 빈 주체다."""
    scope = _s(unit.get("scope_key"))
    if unit.get("kind") == "bundle" and scope:
        return {"names": [f"asm:{scope}"]}
    if unit.get("kind") == "boundary" and scope.startswith("boundary:"):
        return {"names": [f"asm:{scope[len('boundary:'):].split('#', 1)[0]}"]}
    return {}


@dataclasses.dataclass
class _Member:
    """접히기 전 finding 후보 하나 — 카드 판정 한 장 또는 카드 밖 줄 하나."""

    unit_id: str
    raw: dict                                  # risk_spec finding 모양(정규화 전)
    direction: str
    weight: int                                # 걸림의 무게 — 3 FAIL · 2 WARNING·카드 밖 · 1 split(_hold)
    sev_rank: int
    passed: bool                               # 카드 인용이 재대조를 지났나(대표 고르기)
    alias_rank: tuple[int, str]                # 그 셀을 본 묶음 안의 별칭 차례(Ledger.alias_key)
    grade: str                                 # 주장 등급(카드 등급 또는 경험칙)
    claimed: str | None
    sev_claimed: str | None
    nums: list[str]
    card: dict | None = None                   # finding.cards[] 한 줄
    off_index: int | None = None               # 그 셀 카드 밖 줄의 자리
    cites: list[tuple[bool, dict]] = dataclasses.field(default_factory=list)
    corpus_cards: list[str] = dataclasses.field(default_factory=list)
    split: bool = False
    weak_subject: bool = False
    conf: str | None = None
    quote_chars: int | None = None             # 카드 인용이 이미 줄인 글일 때(들여온 원장)의 원래 길이 — R3B-7


def _unit_layers(ledger: Ledger, unit_id: str) -> dict[str, str]:
    unit = next((u for u in ledger.units if u["unit_id"] == unit_id), None) or {}
    return {str(line["ref"]): str(line.get("layer") or "") for line in unit.get("lines") or ()}


def _variants(ledger: Ledger, unit_id: str) -> dict[str, dict[str, dict]]:
    """record_id → 변형 → 판정 행(그 셀의 것)."""
    out: dict[str, dict[str, dict]] = {}
    for row in ledger.rows.get(unit_id) or ():
        out.setdefault(str(row["record_id"]), {})[str(row["variant"])] = row
    return out


def _unit_refs(payload: Mapping[str, Any]) -> set[str]:
    return {str(x["ref"]) for key in ("lines", "evidence") for x in payload.get(key) or () if isinstance(x, Mapping)}


def _subject(ledger: Ledger, unit_id: str, refs: Sequence[str], ctx: narrative.SpecContext,
             items: Mapping[str, Mapping[str, Any]]) -> tuple[dict, str, bool]:
    """(subject, change_kind, weak) — 통과한 참조를 `_ref_rank` 차례로 세워 주체를 낼 수 있는 첫 항목의 주체와 그 항목의
    change_kind(없으면 none, snap 대상은 늘 none). 쓸 참조가 없으면 단위의 범위로 내리고 weak 이다."""
    layers = _unit_layers(ledger, unit_id)
    ranked = sorted(dict.fromkeys(refs), key=lambda r: _ref_rank(r, layers))

    def kind_of(ref: str | None) -> str:
        if ledger.target.get("kind") != "diff" or ref is None:
            return "none"
        return _s((items.get(ref) or {}).get("change_kind")) or "none"

    for ref in ranked:
        subject = _subject_of(ref, ctx)
        if subject is not None:
            return subject, kind_of(ref), False
    unit = next((u for u in ledger.units if u["unit_id"] == unit_id), {})
    return _unit_scope_subject(unit), kind_of(next(iter(ranked), None)), True


def _card_members(ledger: Ledger, unit_id: str, ctx: narrative.SpecContext,
                  items: Mapping[str, Mapping[str, Any]]) -> list[_Member]:
    """그 셀의 실효 FAIL·WARNING 과 split 인 undetermined → 후보. 메커니즘·심각도·닫는 확인은 단독 재질의 행에서 읽는다."""
    unit_refs = _unit_refs(ledger.payloads[unit_id])
    variants = _variants(ledger, unit_id)
    out: list[_Member] = []
    for record_id, eff in sorted(ledger.effective(unit_id).items(), key=lambda kv: ledger.alias_key(kv[1]["alias"], unit_id)):
        flagged = eff["judgement"] in review_verify.FLAGGED
        split = eff["judgement"] == "undetermined" and int(eff["split"] or 0) == 1
        if not (flagged or split):
            continue
        solo = variants[record_id].get("solo") or eff
        claimed = str(eff["claimed"])
        weight = 3 if eff["judgement"] == "FAIL" else 2 if flagged else 1
        sev_claimed = next((s for s in (_s(solo.get("sev")), _s(eff.get("sev"))) if s in _SEV_RANK), None)
        severity, judgement = _hold("risk", weight, claimed, sev_claimed)
        mechanism, detail, free = _mech_parts(solo.get("mech") or eff.get("mech"), solo.get("mech_free") or eff.get("mech_free"))
        detectability, resolving = _detect(solo.get("check_kind") or eff.get("check_kind"),
                                           solo.get("check_text") or eff.get("check_text"))
        refs = [str(r) for r in _json(eff.get("refs_json"), [])]
        for cond in _json(solo.get("conds_json"), []):
            refs.extend(str(r) for r in cond.get("refs") or () if isinstance(cond, Mapping))
        refs = list(dict.fromkeys(refs))
        passed = eff.get("quote_ok") == 1
        cites = [(passed, _card_cite(record_id, eff.get("cq"), eff.get("cq_chars")))]
        cites += [(ref in unit_refs, {"ref": ref, "quote": ""}) for ref in refs]
        subject, change_kind, weak = _subject(ledger, unit_id, [r for r in refs if r in unit_refs], ctx, items)
        checks = _json(eff.get("checks_json"), {})
        nums = sorted({_s(n) for n in checks.get("nums_unsourced") or () if _s(n)})
        grade = _s(eff.get("grade")) if passed and eff.get("grade") else "경험칙"
        if nums:
            grade = "경험칙"
        raw = {
            "direction": "risk", "domain": ledger.head["domain"], "owner_domain": ledger.head["domain"],
            "raised_by": [ledger.agent_key], "mechanism": mechanism, "mechanism_detail": detail,
            "mechanism_free": free, "subject": subject,
            "change_kind": change_kind,
            "trigger_condition": "none", "severity": severity, "judgement": judgement,
            "detectability": detectability, "resolving_check": resolving, "evidence_grade": grade,
            "claim": _s(eff.get("why")),
            "warrant": f"근거 카드 [card:{record_id}] " + render.quote_source(_s(eff.get("cq"))),
        }
        card = {"record_id": record_id, "card_id": eff.get("card_id"), "alias": eff["alias"],
                "judgement": eff["judgement"], "claimed": claimed, "variant": eff["variant"], "agree": eff["agree"],
                "flipped": bool(eff["flipped"]), "split": split}
        out.append(_Member(unit_id=unit_id, raw=raw, direction="risk", weight=weight,
                           sev_rank=_SEV_RANK.get(sev_claimed or "", 0),
                           passed=passed, alias_rank=ledger.alias_key(eff["alias"], unit_id), grade=grade, claimed=claimed,
                           sev_claimed=sev_claimed, nums=nums, card=card, cites=cites, corpus_cards=[record_id],
                           split=split, weak_subject=weak, quote_chars=_known_chars(eff.get("cq_chars"))))
    return out


def _known_chars(value: Any) -> int | None:
    """반출이 적어 둔 원래 길이 칸(cq_chars · q_chars · cond_chars) — 있으면 그 글은 이미 200자로 줄인 글이다(들여온 원장)."""
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _card_cite(record_id: str, quote: Any, chars: Any) -> dict:
    """finding 의 카드 인용 한 줄 — 인용이 이미 줄인 글이면(들여온 박스에서 다시 마감) 원래 길이를 quote_chars 로 이어받는다(R3B-7 —
    그 박스에서 다시 반출해도 원래 길이가 남는다)."""
    cite = {"ref": f"card:{record_id}", "quote": _s(quote)}
    known = _known_chars(chars)
    if known is not None:
        cite["quote_chars"] = known
    return cite


def offcard_rows(cell: Mapping[str, Any]) -> tuple[list[dict], dict]:
    """셀의 카드 밖 결과 — (f 줄들, 나머지{need, seen, handoffs, known_dropped, none, more})."""
    extras = _json(cell.get("extras_json"), {})
    off = extras.get("offcard") if isinstance(extras.get("offcard"), Mapping) else {}
    rows = [dict(f) for f in off.get("findings") or () if isinstance(f, Mapping)]
    return rows, {k: v for k, v in off.items() if k != "findings"}


def _offcard_members(ledger: Ledger, unit_id: str, ctx: narrative.SpecContext,
                     items: Mapping[str, Mapping[str, Any]]) -> list[_Member]:
    payload = ledger.payloads[unit_id]
    unit_refs = _unit_refs(payload)
    out: list[_Member] = []
    rows, _rest = offcard_rows(ledger.cells[unit_id])
    for index, row in enumerate(rows):
        direction = "improvement" if row.get("dir") == "improvement" else "risk"
        sev_claimed = _s(row.get("sev")) if _s(row.get("sev")) in _SEV_RANK else None
        severity, judgement = _hold(direction, 2, None, sev_claimed)
        mechanism, detail, free = _mech_parts(row.get("mech"), row.get("mech_free"))
        detectability, resolving = _detect(row.get("check_kind"), row.get("check_text"))
        refs = list(dict.fromkeys(str(r) for r in row.get("refs") or ()))
        record_id = _s(row.get("record_id"))
        card = ledger.unit_cards(unit_id).get(record_id) if record_id else None
        passed = row.get("quote_ok") == 1
        cites = ([(passed, _card_cite(record_id, row.get("q"), row.get("q_chars")))] if card is not None else [])
        cites += [(ref in unit_refs, {"ref": ref, "quote": ""}) for ref in refs]
        subject, change_kind, weak = _subject(ledger, unit_id, [r for r in refs if r in unit_refs], ctx, items)
        grade = _s(row.get("grade")) if card is not None and passed and row.get("grade") else "경험칙"
        raw = {
            "direction": direction, "domain": ledger.head["domain"], "owner_domain": ledger.head["domain"],
            "raised_by": [ledger.agent_key], "mechanism": mechanism, "mechanism_detail": detail,
            "mechanism_free": free, "subject": subject,
            "change_kind": change_kind,
            "trigger_condition": "none", "severity": severity, "judgement": judgement,
            "detectability": detectability, "resolving_check": resolving, "evidence_grade": grade,
            "claim": _s(row.get("title")), "warrant": _s(row.get("path")),
        }
        out.append(_Member(unit_id=unit_id, raw=raw, direction=direction, weight=2,
                           sev_rank=_SEV_RANK.get(sev_claimed or "", 0), passed=passed, alias_rank=(1 << 20, ""), grade=grade,
                           claimed=None, sev_claimed=sev_claimed, nums=[], off_index=index, cites=cites,
                           corpus_cards=[record_id] if card is not None else [], weak_subject=weak,
                           conf=_s(row.get("conf")) or None))
    return out


def _corpus(ledger: Ledger, unit_id: str, record_ids: Sequence[str]) -> str:
    """수치 대조 말뭉치 — 인용한 카드들의 글(얼린 묶음) + 그 단위 요청에 실린 줄 글 전부(소유 줄·문맥·근거)."""
    cards = ledger.unit_cards(unit_id)
    parts = [cardpack.card_text(cards[r]) for r in dict.fromkeys(record_ids) if r in cards]
    payload = ledger.payloads.get(unit_id) or {}
    parts += [_s(x.get("text")) for key in ("lines", "context", "evidence") for x in payload.get(key) or ()
              if isinstance(x, Mapping)]
    return "\n".join(parts)


def claim_uid_of(review_id: str, direction: str, cluster_key: str, unit_id: str) -> str:
    """finding id — 내용에서 나온다(m-06, 12 hex). 다시 마감해 집합이 바뀌어도 남은 finding 의 id 는 그대로다."""
    tail = int(hashlib.sha1(f"{cluster_key}|{unit_id}".encode("utf-8")).hexdigest()[:12], 16)
    return f"{review_id}#{'G' if direction == 'improvement' else 'F'}{tail}"


def _normalize(raw: Mapping[str, Any], ctx: narrative.SpecContext, path: str, *, warnings: list[str],
               curation: list[dict]) -> dict:
    return narrative._normalize_finding(dict(raw), path, ctx, is_gain=raw["direction"] == "improvement", invalid=[],
                                        warnings=warnings, curation=curation)


def _fold(ledger: Ledger, members: Sequence[_Member], ctx: narrative.SpecContext, *, warnings: list[str],
          curation: list[dict]) -> dict:
    """한 셀 안에서 (cluster_key, direction) 이 같은 후보들 → finding 하나. 대표는 걸림이 무거운 순 → 심각도 높은 순 → 인용이 통과한
    순 → 별칭 순(카드 밖 줄은 카드 뒤) → 자리 순이고, 인용은 구성원 전부의 합집합에서 통과한 것 먼저다(상한 없음 — D-21)."""
    ordered = sorted(members, key=lambda m: (-m.weight, -m.sev_rank, not m.passed, m.alias_rank,
                                             m.off_index if m.off_index is not None else -1))
    rep = ordered[0]
    unit_id = rep.unit_id
    seen: dict[str, tuple[bool, dict]] = {}
    for member in ordered:
        for passed, cite in member.cites:
            prior = seen.get(cite["ref"])
            if prior is None or (passed and not prior[0]):
                seen[cite["ref"]] = (passed, cite)
    cites = [c for p, c in seen.values() if p] + [c for p, c in seen.values() if not p]
    claimed = next((m.claimed for m in ordered if m.claimed), None)
    sevs = sorted((m.sev_claimed for m in ordered if m.sev_claimed), key=lambda x: -_SEV_RANK[x])
    sev_claimed = sevs[0] if sevs else None
    severity, judgement = _hold(rep.direction, rep.weight, claimed, sev_claimed)
    raw = {**rep.raw, "cites": cites, "severity": severity, "judgement": judgement,
           "evidence_grade": max((m.grade for m in ordered), key=lambda g: _GRADE_RANK.get(g, 0))}
    record_ids = [r for m in ordered for r in m.corpus_cards]
    local = dataclasses.replace(ctx, number_corpus=_corpus(ledger, unit_id, record_ids))
    finding = _normalize(raw, local, f"{ledger.agent_key}/{unit_id}", warnings=warnings, curation=curation)
    uid = claim_uid_of(ledger.review_id, finding["direction"], finding["cluster_key"], unit_id)
    # 카드 행의 해석 결과에서 카드 글이 새지 않게 정규 글 자리를 뗀다(P-06 — card_payload 는 본문 없이 이미 줄여 둔 값이다).
    finding["_resolved_cites"] = [{k: v for k, v in row.items() if not (row.get("ref_type") == "card" and k == "canonical")}
                                  for row in finding.get("_resolved_cites") or ()]
    finding.update({
        "claim_uid": uid, "source": SOURCE_KIND, "review_id": ledger.review_id, "unit_ids": [unit_id],
        "cards": sorted((dict(m.card) for m in ordered if m.card), key=lambda c: ledger.alias_key(c["alias"], unit_id)),
        "off_card": all(m.off_index is not None for m in ordered),
        "off_card_n": sum(1 for m in ordered if m.off_index is not None), "input_gap": False,
        "conf": next((m.conf for m in ordered if m.conf), None), "judgement_claimed": claimed,
        "severity_claimed": sev_claimed, "nums_missing": sorted({n for m in ordered for n in m.nums}), "doc_refs": [],
        "split": any(m.split for m in ordered), "weak_subject": rep.weak_subject,
        "members": [_member_key(m) for m in ordered],
    })
    if rep.card is not None and rep.quote_chars is not None:
        finding["warrant_chars"] = [rep.quote_chars]          # 근거 문장의 «» 인용이 이미 줄인 글이다(R3B-7)
    return finding


def _member_key(member: _Member) -> str:
    """보고서가 판정 행·카드 밖 줄에서 그것이 들어간 finding 을 찾는 열쇠 — `card:<record_id>` · `off:<자리>`."""
    return f"card:{member.card['record_id']}" if member.card else f"off:{member.off_index}"


def build_findings(store: Any, ledger: Ledger) -> dict:
    """검토한 셀에서 finding 을 짓는다(쓰지 않는다) — {findings[], curation[], warnings[]}. finding 은 claim_uid 순이다."""
    ctx = narrative.review_scope(store, ledger.target_key, ledger.agent_key, ledger.review_id, ledger.pack)
    items = ({str(i["ref"]): i for i in units.collect_diff_items(ctx.diff)} if ledger.target.get("kind") == "diff"
             else {})
    warnings: list[str] = []
    curation: list[dict] = []
    findings: list[dict] = []
    for unit in ledger.reviewed():
        unit_id = unit["unit_id"]
        # 카드 인용은 그 셀을 본 묶음의 글로 검증한다 — 묶음이 바뀐 대상에서 머리 묶음으로 보면 같은 record_id 의 다른 글에 댄다(R3B-2).
        local = dataclasses.replace(ctx, card_pack=ledger.unit_cards(unit_id))
        members = _card_members(ledger, unit_id, local, items) + _offcard_members(ledger, unit_id, local, items)
        groups: dict[tuple[str, str], list[_Member]] = {}
        for member in members:
            probe = _normalize({**member.raw, "cites": [c for _p, c in member.cites]}, local,
                               f"{ledger.agent_key}/{unit_id}", warnings=[], curation=[])
            groups.setdefault((probe["cluster_key"], probe["direction"]), []).append(member)
        for key in sorted(groups):
            findings.append(_fold(ledger, groups[key], local, warnings=warnings, curation=curation))
    findings.sort(key=lambda f: f["claim_uid"])
    return {"findings": findings, "curation": curation, "warnings": warnings}


# ================================================================ 보고서의 머리·범위·finding 절(요약과 의견 행의 원천)
_STATE_WORD = {"pending": "대기", "running": "도는 중", "reviewed": "검토", "na_irrelevant": "해당 없음", "no_input": "입력 결손",
               "failed": "미완", "skipped": "넘김"}


def _head_section(ledger: Ledger, state: str, why: str | None) -> dict:
    """머리 — 판번호·만든 시각은 싣지 않는다(m-07 — 같은 원장이면 같은 바이트, 둘은 행의 열에만 있다)."""
    head, pack = ledger.head, ledger.pack
    return {
        "agent_key": ledger.agent_key, "name": _s((pack.raw if pack is not None else {}).get("name")) or ledger.agent_key,
        "domain": head["domain"], "rank_in_domain": head["rank_in_domain"], "tier": head["tier"],
        "review_id": ledger.review_id, "state": state, "why": why, "model": head["model"],
        "prompt_rev": head["prompt_rev"], "norm_rev": head["norm_rev"], "verify_rev": head["verify_rev"],
        "report_rev": REPORT_REV, "input_gaps": list(ledger.order.get("input_gaps") or ()),
        "pack": None if pack is None else {
            "pack_key": pack.pack_key, "pack_hash": pack.pack_hash, "card_basis": pack.card_basis,
            "cards_total": len(pack.order), "checkable_n": len(pack.checkable), "background_n": len(pack.background),
            "unrenderable_n": len(pack.unrenderable), "frozen_at": head["pack_frozen_at"]},
        "pack_status": head["pack_status"], "pack_error": head["pack_error"],
    }


def _scope_section(ledger: Ledger, state: str) -> dict:
    """본 범위 — 단위마다 상태·무엇으로 봤나·판정별 수, 끝에 보지 못한 것(미완·범위 밖 대기·묶음을 못 받아 못 본 것)."""
    run_id = ledger.head.get("run_id")
    rows: list[dict] = []
    unseen: list[dict] = []
    for unit in ledger.units:
        cell = ledger.cells.get(unit["unit_id"]) or {"state": "pending"}
        cell_state = str(cell["state"])
        reviewed = cell_state == "reviewed"
        rows.append({
            "unit_id": unit["unit_id"], "unit_seq": unit["seq"], "kind": unit["kind"], "title": unit["title"],
            "state": cell_state, "in_scope": cell.get("run_id") == run_id, "basis": cell.get("basis") if reviewed else None,
            "counts": ({j: int(cell.get(f"n_{j.lower()}") or 0) for j in _JUDGE_ORDER} if reviewed else None),
            "offcard_n": int(cell.get("n_offcard") or 0) if reviewed else 0,
            "bg_full_n": int(cell.get("bg_full_n") or 0) if reviewed else 0,
            "bg_title_only_n": int(cell.get("bg_title_only_n") or 0) if reviewed else 0,
            "error_code": cell.get("error_code"), "tries": int(cell.get("tries") or 0),
            "charged": int(cell.get("charged") or 0), "pack_state": ledger.pack_state(unit["unit_id"]) if reviewed else None})
        if reviewed:
            continue
        if cell_state == "failed":
            why = {"code": cell.get("error_code"), "text": cell.get("error")}
        elif cell.get("run_id") != run_id:
            why = {"code": "out_of_scope", "text": None}
        elif state == "blocked":
            why = {"code": "pack_blocked", "text": None}
        else:
            why = {"code": cell_state, "text": None}
        unseen.append({"unit_id": unit["unit_id"], "unit_seq": unit["seq"], "title": unit["title"], "state": cell_state,
                       "why": why})
    by_state: dict[str, int] = {}
    for row in rows:
        by_state[row["state"]] = by_state.get(row["state"], 0) + 1
    by_basis: dict[str, int] = {}
    for row in rows:
        if row["basis"]:
            by_basis[row["basis"]] = by_basis.get(row["basis"], 0) + 1
    return {"units": rows, "totals": {"units": len(rows), "by_state": dict(sorted(by_state.items())),
                                      "by_basis": dict(sorted(by_basis.items()))}, "unseen": unseen}


def _findings_section(findings: Sequence[Mapping[str, Any]], ledger: Ledger) -> list[dict]:
    seq = {u["unit_id"]: u["seq"] for u in ledger.units}
    return [{"claim_uid": f["claim_uid"], "unit_id": f["unit_ids"][0], "unit_seq": seq.get(f["unit_ids"][0]),
             "cluster_key": f["cluster_key"], "direction": f["direction"], "severity": f["severity"],
             "judgement": f["judgement"], "judgement_claimed": f.get("judgement_claimed"),
             "severity_claimed": f.get("severity_claimed"), "evidence_grade": f["evidence_grade"],
             "mechanism": f"{f['mechanism']}.{f['mechanism_detail']}", "mechanism_free": f.get("mechanism_free") or None,
             "subject_key": f.get("subject_key"), "weak_subject": bool(f.get("weak_subject")),
             "cards": [{"record_id": c["record_id"], "card_id": c.get("card_id"), "alias": c["alias"],
                        "judgement": c["judgement"]} for c in f.get("cards") or ()],
             "off_card": bool(f.get("off_card")), "split": bool(f.get("split")), "claim": f.get("claim") or "",
             "dangling": list(f.get("dangling") or ()), "quote_mismatch": list(f.get("quote_mismatch") or ()),
             "unquoted_numbers": list(f.get("unquoted_numbers") or ())}
            for f in findings]


# ---------------------------------------------------------------- 보고서의 나머지 절(S10)
def _clip_quote(text: Any, known: Any = None) -> tuple[str, int | None]:
    """보고서 표시의 카드 인용 — 판정당 200자, 줄였으면 (앞 200자, 원래 길이)(사용자 결정 1). 행의 원래 길이 칸(`known` — 반출이 적는
    cq_chars·q_chars·cond_chars)이 있으면 글은 이미 줄인 것이라 그 길이를 쓴다(R3B-7 — 들여온 박스에서 다시 마감해도 남는다)."""
    value = _s(text)
    chars = _known_chars(known)
    if chars is not None:
        return value[:QUOTE_SHOW], chars
    return (value[:QUOTE_SHOW], len(value)) if len(value) > QUOTE_SHOW else (value, None)


def _finding_of(findings: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], str]:
    """(unit_id, 구성원 열쇠 card:<record_id>·off:<자리>) → 그것이 들어간 finding 의 claim_uid."""
    return {(f["unit_ids"][0], key): f["claim_uid"] for f in findings for key in f.get("members") or ()}


def _checklist_row(ledger: Ledger, unit: Mapping[str, Any], eff: Mapping[str, Any], variants: Mapping[str, Mapping],
                   finding_of: Mapping[tuple[str, str], str]) -> dict:
    """점검표 한 행 — 실효 판정 하나와 그 대조 표기. 상세 칸(심각도·경로·닫는 확인·조건별 대조)은 단독 재질의 행에서 읽는다."""
    src = variants.get("solo") or eff
    record_id = str(eff["record_id"])
    cq, cq_chars = _clip_quote(eff.get("cq"), eff.get("cq_chars"))
    checks = _json(eff.get("checks_json"), {})
    conds = []
    for cond in _json(src.get("conds_json"), []):
        if not isinstance(cond, Mapping):
            continue
        text, chars = _clip_quote(cond.get("cond"), cond.get("cond_chars"))
        conds.append({"cond": text, "cond_chars": chars, "met": cond.get("met"), "note": cond.get("note"),
                      "lines": list(cond.get("l") or ()), "refs": list(cond.get("refs") or ()), "refs_ok": cond.get("refs_ok")})
    section = eff.get("section_id")
    return {
        "unit_id": unit["unit_id"], "unit_seq": unit["seq"], "applies": eff["applies"], "judgement": eff["judgement"],
        "judgement_claimed": eff["claimed"] if eff["claimed"] != eff["judgement"] else None,
        "variant": eff["variant"], "agree": eff["agree"], "split": bool(eff["split"]), "flipped": bool(eff["flipped"]),
        "disputed": bool(eff["disputed"]),
        "variants": [{"variant": v, "applies": variants[v]["applies"], "judgement": variants[v]["judgement"]}
                     for v in ("fwd", "rev", "solo") if v in variants],
        "cq": cq, "cq_chars": cq_chars, "quote_ref": f"card:{record_id}#{section}" if section else f"card:{record_id}",
        "quote_ok": eff.get("quote_ok"), "check_disagree": bool(eff.get("check_disagree")),
        "quote_state": review_verify.quote_state(eff.get("cq"), eff.get("quote_ok"), eff.get("check_disagree"),
                                                 checks.get("quote")),
        "lines": _json(eff.get("lines_json"), []), "refs": _json(eff.get("refs_json"), []), "refs_ok": eff.get("refs_ok"),
        "why": eff.get("why"), "need": eff.get("need"), "sev": src.get("sev"), "mech": src.get("mech"),
        "mech_free": src.get("mech_free"), "path": src.get("path"), "check_kind": src.get("check_kind"),
        "check": src.get("check_text"), "conds": conds,
        "nums_missing": sorted({_s(n) for n in checks.get("nums_unsourced") or () if _s(n)}), "grade": eff.get("grade"),
        "revised_from": eff.get("revised_from"), "finding_id": finding_of.get((unit["unit_id"], f"card:{record_id}")),
    }


def _card_head(card: Mapping[str, Any]) -> dict:
    return {"alias": card["alias"], "record_id": str(card["record_id"]), "card_id": card.get("card_id"),
            "type": card.get("type"), "confidence": card.get("confidence"), "title": card.get("title"),
            "grade": review_verify.card_grade(card), "ref": f"card:{card['record_id']}"}


def _row_head(eff: Mapping[str, Any]) -> dict:
    """카드를 실은 묶음이 이 박스에 하나도 없을 때의 카드 머리 — 판정 행에 있는 id 만(제목·종류·등급은 모른다)."""
    record_id = str(eff["record_id"])
    return {"alias": eff["alias"], "record_id": record_id, "card_id": eff.get("card_id"), "type": None, "confidence": None,
            "title": None, "grade": None, "ref": f"card:{record_id}"}


def _card_units(ledger: Ledger) -> list[dict]:
    """카드로 본(basis='cards') 검토한 단위 — 점검표의 열."""
    return [u for u in ledger.reviewed() if (ledger.cells[u["unit_id"]].get("basis")) == "cards"]


def _checklist_section(ledger: Ledger, finding_of: Mapping[tuple[str, str], str]) -> list[dict]:
    """점검 카드 × 카드로 본 단위마다 실효 판정 한 행 — 생략하는 행이 없다(점검표 행 수 == 실효 판정 행 수).

    카드의 열쇠는 record_id 다(R3B-2 — 별칭은 묶음마다 다시 매기는 이름이다). 카드 목록은 지금 묶음(머리)의 점검 카드(팩 순서) 뒤에
    판정 행이 가리키는데 거기 없는 카드를 단위 순서로 잇는다 — 카드 머리는 그 판정을 낸 묶음에서(`source='unit_pack'`), 그 묶음이 이
    박스에 없으면 지금 묶음에서(`head_pack`), 어디에도 없으면 판정 행의 id 만으로(`verdict`) 적는다. 실효가 없는 칸은 missing 이고
    `missing_why` 가 그 까닭이다 — no_verdict(판정이 비었다) · not_in_unit_pack(그 단위를 본 묶음에 없던 카드) · unit_pack_absent(그 묶음이 이
    박스에 없어 판정 대상이었는지 모른다)."""
    columns = [(u, ledger.effective(u["unit_id"]), _variants(ledger, u["unit_id"])) for u in _card_units(ledger)]
    heads: dict[str, dict] = {}
    if ledger.pack is not None:
        for alias in ledger.pack.checkable:
            card = ledger.pack.cards[alias]
            heads[str(card["record_id"])] = {**_card_head(card), "source": "pack"}
    for unit, effective, _variants_of in columns:
        for eff in sorted(effective.values(), key=lambda e: ledger.alias_key(e["alias"], unit["unit_id"])):
            record_id = str(eff["record_id"])
            if record_id in heads:
                continue
            judged = ledger.unit_pack(unit["unit_id"])
            if judged is not None and record_id in judged.record_cards:
                heads[record_id] = {**_card_head(judged.record_cards[record_id]), "source": "unit_pack"}
            elif ledger.pack is not None and record_id in ledger.pack.record_cards:
                heads[record_id] = {**_card_head(ledger.pack.record_cards[record_id]), "source": "head_pack"}
            else:
                heads[record_id] = {**_row_head(eff), "source": "verdict"}
    out = []
    for record_id, head in heads.items():
        rows = []
        for unit, effective, variants in columns:
            eff = effective.get(record_id)
            if eff is not None:
                card = ledger.unit_cards(unit["unit_id"]).get(record_id)
                row = _checklist_row(ledger, unit, eff, variants.get(record_id) or {}, finding_of)
                rows.append({**row, "alias": eff["alias"],
                             "card_changed": card is not None and _s(card.get("text_sha")) != _s(eff.get("text_sha"))})
                continue
            judged, state = ledger.unit_pack(unit["unit_id"]), ledger.pack_state(unit["unit_id"])
            why = ("unit_pack_absent" if state == "absent" else
                   "not_in_unit_pack" if judged is not None and record_id not in {
                       str(judged.cards[a]["record_id"]) for a in judged.checkable} else "no_verdict")
            rows.append({"unit_id": unit["unit_id"], "unit_seq": unit["seq"], "missing": True, "missing_why": why})
        out.append({**head, "rows": rows})
    return out


def _unjudged_section(ledger: Ledger) -> list[dict]:
    """판정하지 못한 카드 — 본문이 없는 카드(묶음의 unrenderable)와 계획이 창을 넘는다고 한 카드(oversize.cards)."""
    if ledger.pack is None:
        return []
    out = [{"record_id": _s(u.get("record_id")), "card_id": u.get("card_id"), "title": u.get("title"), "why": "unrenderable"}
           for u in ledger.pack.unrenderable]
    plan = (_json(ledger.head.get("plan_json"), {}).get("plan") or {})
    for alias in ((plan.get("oversize") or {}).get("cards") or ()):
        card = ledger.pack.cards.get(str(alias)) or {}
        out.append({"record_id": _s(card.get("record_id")), "card_id": card.get("card_id"), "title": card.get("title"),
                    "alias": str(alias), "why": "oversize"})
    return out


def _off_card_section(ledger: Ledger, finding_of: Mapping[tuple[str, str], str]) -> list[dict]:
    out = []
    for unit in ledger.reviewed():
        unit_refs = _unit_refs(ledger.payloads[unit["unit_id"]])
        rows, _rest = offcard_rows(ledger.cells[unit["unit_id"]])
        for index, row in enumerate(rows):
            q, q_chars = _clip_quote(row.get("q"), row.get("q_chars"))
            record_id, section = _s(row.get("record_id")), _s(row.get("section_id"))
            refs = [str(r) for r in row.get("refs") or ()]
            out.append({
                "unit_id": unit["unit_id"], "unit_seq": unit["seq"], "index": index, "dir": row.get("dir") or "risk",
                "title": row.get("title"), "path": row.get("path"), "lines": list(row.get("l") or ()), "refs": refs,
                "refs_ok": row.get("refs_ok"), "refs_outside": [r for r in refs if r not in unit_refs],
                "src": row.get("src"), "record_id": record_id or None,
                "q": q or None, "q_chars": q_chars,
                "quote_ref": (f"card:{record_id}#{section}" if section else f"card:{record_id}") if record_id else None,
                "quote_ok": row.get("quote_ok"),
                "quote_state": review_verify.quote_state(row.get("q"), row.get("quote_ok"), row.get("check_disagree"),
                                                         (row.get("checks") or {}).get("quote")),
                "mech": row.get("mech"), "mech_free": row.get("mech_free"),
                "sev": row.get("sev"), "conf": row.get("conf"), "check_kind": row.get("check_kind"),
                "check": row.get("check_text"), "basis": row.get("basis"), "grade": row.get("grade"),
                "finding_id": finding_of.get((unit["unit_id"], f"off:{index}"))})
    return out


def _by_unit_section(ledger: Ledger, off_card: Sequence[Mapping[str, Any]]) -> list[dict]:
    """단위마다 판정별 카드 record_id(그 단위를 본 묶음의 별칭 순서)와 그 단위의 카드 밖 지적 자리(off_card 절의 순번) — 마크다운이
    FAIL → WARNING(조건별 대조 · 영향 경로 · 닫는 확인) → 보류(필요 자료) → 걸림 없음 순으로 편다. 점검표 행은 (unit_id, record_id)
    로 찾는다(R3B-2 — 별칭은 묶음마다 다시 매기는 이름이다)."""
    out = []
    for unit in ledger.reviewed():
        effective = sorted(ledger.effective(unit["unit_id"]).values(),
                           key=lambda e: ledger.alias_key(e["alias"], unit["unit_id"]))
        entry = {"unit_id": unit["unit_id"], "unit_seq": unit["seq"], "title": unit["title"],
                 "basis": ledger.cells[unit["unit_id"]].get("basis")}
        for judgement in _JUDGE_ORDER:
            entry[judgement] = [str(e["record_id"]) for e in effective if e["judgement"] == judgement]
        entry["off_card"] = [n for n, f in enumerate(off_card) if f["unit_id"] == unit["unit_id"] and f["dir"] != "improvement"]
        entry["improvements"] = [n for n, f in enumerate(off_card)
                                 if f["unit_id"] == unit["unit_id"] and f["dir"] == "improvement"]
        out.append(entry)
    return out


def _handoff_section(ledger: Ledger) -> list[dict]:
    """다른 영역으로 넘긴 것 — 훑기의 h 와 카드 밖 호출의 h 를 합친다."""
    seq = {u["unit_id"]: u["seq"] for u in ledger.units}
    sweep = _json(ledger.head.get("sweep_json"), {})
    out = [{"source": "sweep", "unit_id": h.get("unit_id") or None, "unit_seq": seq.get(_s(h.get("unit_id"))),
            "to": h.get("to"), "why": h.get("why"), "lines": [], "refs": []}
           for h in sweep.get("handoffs") or () if isinstance(h, Mapping)]
    for unit in ledger.reviewed():
        _rows, rest = offcard_rows(ledger.cells[unit["unit_id"]])
        out += [{"source": "off_card", "unit_id": unit["unit_id"], "unit_seq": unit["seq"], "to": h.get("to"),
                 "why": h.get("why"), "lines": list(h.get("l") or ()), "refs": list(h.get("refs") or ())}
                for h in rest.get("handoffs") or () if isinstance(h, Mapping)]
    return out


def _needs_section(ledger: Ledger) -> list[dict]:
    """필요한 추가 정보 — 보류 행의 need 와 카드 밖 호출의 need 줄. 공백을 접어 같은 글은 한 항목으로(어디서 나왔나는 모은다)."""
    out = []
    for unit in ledger.reviewed():
        items: dict[str, dict] = {}

        def add(text: Any, source: str) -> None:
            norm = " ".join(_s(text).split())
            if norm:
                items.setdefault(norm, {"text": norm, "from": []})["from"].append(source)

        for eff in sorted(ledger.effective(unit["unit_id"]).values(),
                          key=lambda e: ledger.alias_key(e["alias"], unit["unit_id"])):
            if eff["judgement"] == "undetermined" or eff["applies"] == "unknown":
                add(eff.get("need"), eff["alias"])
        _rows, rest = offcard_rows(ledger.cells[unit["unit_id"]])
        for need in rest.get("need") or ():
            add(need.get("what") if isinstance(need, Mapping) else need, "off_card")
        if items:
            out.append({"unit_id": unit["unit_id"], "unit_seq": unit["seq"], "title": unit["title"],
                        "items": list(items.values())})
    return out


def _mechanisms_section(ledger: Ledger) -> list[dict]:
    """카드 밖 호출이 따져 본 메커니즘(문제없다고 본 것 포함)을 단위별로."""
    out = []
    for unit in ledger.reviewed():
        _rows, rest = offcard_rows(ledger.cells[unit["unit_id"]])
        out.append({"unit_id": unit["unit_id"], "unit_seq": unit["seq"],
                    "seen": sorted({_s(m) for m in rest.get("seen") or () if _s(m)})})
    return out


def _quality_section(store: Any, target_key: str, agent_key: str) -> dict:
    """검토 품질(S11 의 전문가 몫) — 품질 수치 모듈의 계산(`compute(…, agent_key=…)`)과 문면(`block`)이다. 표본이 모자란 값은 그
    모듈이 0 이 아니라 '표본 수 미달(n=…)' 로 적는다."""
    return {"status": "measured", "json": review_quality.compute(store, target_key, agent_key=agent_key),
            "text": review_quality.block(store, target_key, agent_key=agent_key)["text"]}


def _state_of(store: Any, ledger: Ledger, *, blocked: str | None) -> tuple[str, str | None]:
    """보고서에 싣는 마감 상태와 그 까닭 — blocked(묶음을 끝내 못 받았다) · partial(미완 셀·범위 밖 대기) · ready."""
    if blocked:
        return "blocked", blocked
    tally = review_cells.expert_tally(store, ledger.target_key, ledger.agent_key)
    state = review_cells.closing_state(tally)
    if state == "partial":
        return state, f"미완 셀 {tally['failed']}개 · 아직 열린 셀 {tally['open']}개"
    return state, None


def build_report(store: Any, target_key: str, agent_key: str, *, ledger: Ledger | None = None,
                 findings: Sequence[Mapping[str, Any]] | None = None, blocked: str | None = None) -> dict:
    """판정 행·셀·호출 원장·얼린 팩에서 전문가 보고서 JSON 을 조립한다(LLM 0회, 쓰지 않는다). 같은 원장이면 같은 바이트다 —
    판번호·만든 시각은 싣지 않는다(m-07, 행의 revision·finalized_at 에만 있다).

    절은 head · scope(끝에 보지 못한 것) · checklist(점검 카드 × 카드로 본 단위마다 실효 판정 한 행, 생략 없음) · background ·
    unjudged_cards · by_unit · off_card · handoff · needs_info · mechanisms · findings · quality(S11 의 전문가 몫 — 모듈이 없으면
    미측정)다. 카드 인용은 판정당 200자로 싣고 원래 길이를 옆 칸에 적는다(사용자 결정 1). 그 밖의 글은 줄이지 않는다(D-21).
    `findings` 를 주지 않으면 여기서 짓는다. `blocked` 는 카드 묶음을 끝내 받지 못한 전문가의 까닭이다 — 그 보고서는 아무 단위도
    보지 않았다는 것을 '보지 못한 것' 이 말한다."""
    ledger = ledger if ledger is not None else load_ledger(store, target_key, agent_key)
    if findings is None:
        findings = build_findings(store, ledger)["findings"] if ledger.pack is not None or not blocked else []
    state, why = _state_of(store, ledger, blocked=blocked)
    finding_of = _finding_of(findings)
    off_card = _off_card_section(ledger, finding_of)
    return {
        "report_rev": REPORT_REV, "target_key": target_key, "agent_key": agent_key,
        "head": _head_section(ledger, state, why), "scope": _scope_section(ledger, state),
        "checklist": _checklist_section(ledger, finding_of),
        "background": [_card_head(ledger.pack.cards[a]) for a in ledger.pack.background] if ledger.pack is not None else [],
        "unjudged_cards": _unjudged_section(ledger), "by_unit": _by_unit_section(ledger, off_card), "off_card": off_card,
        "handoff": _handoff_section(ledger), "needs_info": _needs_section(ledger), "mechanisms": _mechanisms_section(ledger),
        "findings": _findings_section(findings, ledger), "quality": _quality_section(store, target_key, agent_key),
    }


# ================================================================ 요약(의견 행 excerpt_for_rag · turns[0])
def _clip(text: str, limit: int, word: str) -> str:
    """글을 limit 자 안으로 — 줄였으면 원래 길이를 적는다(줄이지 않았으면 그대로)."""
    if len(text) <= limit:
        return text
    mark = f" …({word} {len(text)}자 중 {{kept}}자)"
    kept = limit - len(mark.format(kept=limit))
    return text[:kept] + mark.format(kept=kept)


def summary_md(report: Mapping[str, Any]) -> str:
    """≤1500자 요약 — 의견 행 excerpt_for_rag 와 turns[0] 의 글. 코드가 쓰는 문장은 수와 참조뿐이고 전문가·카드의 글은 «» 로
    감싼다. 넘치면 원래 길이를 적고 줄인다(보고서 본문은 줄이지 않는다 — D-21)."""
    head, scope = report["head"], report["scope"]
    name = f"{_q(head['name'])}({_q(head['agent_key'])})"
    totals = scope["totals"]["by_state"]
    if head["state"] == "blocked":
        seen = totals.get("reviewed", 0)
        lines = [f"{name} — 카드 묶음을 받지 못해({_q(head.get('pack_error') or '')}) "
                 + ("아무 단위도 보지 않았다" if not seen else f"이번 범위를 보지 않았다(앞서 검토한 단위 {seen}개)")
                 + f". 단위 {scope['totals']['units']}개 가운데 {len(scope['unseen'])}개가 보지 못한 것으로 남았다."]
        return _clip("\n".join(lines), SUMMARY_MAX, "요약")
    counts = {j: sum((u["counts"] or {}).get(j, 0) for u in scope["units"]) for j in _JUDGE_ORDER}
    offcard = sum(u["offcard_n"] for u in scope["units"])
    # 검토 수는 '형식만 채운 칸' 과 같은 줄에 단다(WP5b 3.11.3 규칙 3 — 이 요약이 의견 행 excerpt_for_rag 가 된다, R3B-10).
    form_only = (((report.get("quality") or {}).get("json") or {}).get("grid") or {}).get("form_only")
    form = f"(형식만 채운 칸 {review_quality.fmt_rate(form_only)})" if isinstance(form_only, Mapping) else ""
    lines = [f"{name} 카드 대조 요약 — 단위 {scope['totals']['units']}개 가운데 검토 {totals.get('reviewed', 0)}{form}"
             f" · 미완 {totals.get('failed', 0)} · 대기 {totals.get('pending', 0)}.",
             f"실효 판정 judgement=FAIL {counts['FAIL']} · judgement=WARNING {counts['WARNING']} · 보류 {counts['undetermined']}"
             f" · 걸림 없음 {counts['OK']} · 해당 없음 {counts['na']}, 카드 밖 지적 {offcard}건, finding {len(report['findings'])}건."]
    weight = {"FAIL": 0, "WARNING": 1}
    for f in sorted(report["findings"], key=lambda x: (weight.get(x.get("judgement_claimed") or "", 2), x["unit_seq"] or 0,
                                                      x["claim_uid"])):
        cards = " · ".join(_q(c.get("card_id") or c["record_id"]) for c in f["cards"]) or "카드 밖"
        verdict = f"judgement={f['judgement_claimed']}" if f.get("judgement_claimed") else f"direction={f['direction']}"
        lines.append(f"- 단위 {f['unit_seq']} {verdict} {cards} — {_q(f['claim'])}")
    return _clip("\n".join(lines), SUMMARY_MAX, "요약")


# ================================================================ 의견 행(seat_opinion.v1)
def _final_stance(ledger: Ledger, findings: Sequence[Mapping[str, Any]]) -> str:
    """실효 FAIL → oppose, WARNING·카드 밖 지적·변형이 갈린 카드 → conditional, 적용 판정이 보류뿐이거나 검토한 셀이 없으면 abstain
    (X1-15), 그 밖 → agree."""
    reviewed = ledger.reviewed()
    if not reviewed:
        return "abstain"
    effective = [row for unit in reviewed for row in ledger.effective(unit["unit_id"]).values()]
    if any(row["judgement"] == "FAIL" for row in effective):
        return "oppose"
    if (any(row["judgement"] == "WARNING" for row in effective)
            or any(f["direction"] == "risk" and (f.get("off_card_n") or f.get("split")) for f in findings)):
        return "conditional"
    applicable = [row["judgement"] for row in effective if row["applies"] != "no"]
    if applicable and all(j == "undetermined" for j in applicable):
        return "abstain"
    return "agree"


def _cited(ledger: Ledger) -> tuple[list[str], list[str], bool]:
    """(cited_refs, cited_refs_resolved, cited_ir) — 검토한 셀의 실효 판정·카드 밖 줄이 짚은 카드·단위 참조와 그 가운데 대조를
    지난 것(카드 인용은 재대조 통과, 단위 참조는 그 단위 소속)."""
    cited: set[str] = set()
    resolved: set[str] = set()
    for unit in ledger.reviewed():
        unit_id = unit["unit_id"]
        unit_refs = _unit_refs(ledger.payloads[unit_id])
        sources = [(f"card:{row['record_id']}" if row.get("cq") else None, row.get("quote_ok") == 1,
                    _json(row.get("refs_json"), [])) for row in ledger.effective(unit_id).values()]
        rows, _rest = offcard_rows(ledger.cells[unit_id])
        sources += [(f"card:{row['record_id']}" if row.get("record_id") else None, row.get("quote_ok") == 1,
                     list(row.get("refs") or ())) for row in rows]
        for card_ref, card_ok, refs in sources:
            if card_ref:
                cited.add(card_ref)
                if card_ok:
                    resolved.add(card_ref)
            for ref in refs:
                cited.add(str(ref))
                if str(ref) in unit_refs:
                    resolved.add(str(ref))
    cited_ir = any(ref.split(":", 1)[0] in narrative.IR_REF_KINDS for ref in resolved)
    return sorted(cited), sorted(resolved), cited_ir


def opinion_cycle(store: Any, target_key: str, agent_key: str) -> int:
    """검토 의견의 회차 — 500 + 원장 회차(narrative.REVIEW_CYCLE_BASE, 원장 밖 좌석 100000 대역과 겹치지 않는다)."""
    row = store.query_one("SELECT cycle FROM rr_coverage WHERE target_key = ? AND agent_key = ?", (target_key, agent_key))
    return narrative.REVIEW_CYCLE_BASE + int((row["cycle"] if row is not None else None) or 1)


def build_opinion(ledger: Ledger, findings: Sequence[Mapping[str, Any]], summary: str, *, cycle: int) -> dict:
    """seat_opinion.v1 필수 칸 전부(contested_finding_ids·character_sentences 는 빈 목록 — m-11). 패널 자리는 review_id 다."""
    stance = _final_stance(ledger, findings)
    refs, resolved, cited_ir = _cited(ledger)
    grades = sorted((str(f["evidence_grade"]) for f in findings if f.get("evidence_grade")),
                    key=lambda g: _GRADE_RANK.get(g, 0))
    knowledge = {row["record_id"] for unit in ledger.reviewed() for row in ledger.effective(unit["unit_id"]).values()}
    return {
        "opinion_id": narrative._opinion_id(ledger.review_id, ledger.agent_key, cycle),
        "target_key": ledger.target_key, "panel_id": ledger.review_id, "agent_key": ledger.agent_key,
        "domain": ledger.head["domain"], "origin": "primary", "cycle": cycle,
        "turns": [{"round": 1, "say_excerpt": summary, "say": summary, "position": "", "stance": stance,
                   "non_negotiable": ""}],
        "final_stance": stance, "tool_calls": [], "tool_calls_n": None, "tool_calls_ok": None,
        "knowledge_hits_n": len(knowledge), "model": ledger.head.get("model"),
        "cited_refs": refs, "cited_refs_resolved": resolved,
        "cited_ckeys": sorted({str(ck) for f in findings for ck in (f.get("subject") or {}).get("ckeys") or ()
                               if str(ck).startswith("ck:") and len(str(ck)) == 15}),
        "quality": {"used_tool": None, "cited_ir": cited_ir, "grade_min": grades[0] if grades else None,
                    "dangling_n": sum(len(f.get("dangling") or ()) for f in findings)},
        "raised_finding_ids": sorted(f["claim_uid"] for f in findings),
        "contested_finding_ids": [], "character_sentences": [], "excerpt_for_rag": summary,
    }


# ================================================================ 마감(준비는 읽기만, 쓰기는 한 트랜잭션)
@dataclasses.dataclass
class Prepared:
    """마감 한 번이 쓸 것 — `prepare` 가 읽기만으로 짓고 `commit` 이 한 트랜잭션에서 쓴다."""

    ledger: Ledger
    findings: list[dict]
    curation: list[dict]
    report: dict
    summary: str
    opinion: dict


def prepare(store: Any, target_key: str, agent_key: str) -> Prepared:
    ledger = load_ledger(store, target_key, agent_key)
    built = build_findings(store, ledger)
    report = build_report(store, target_key, agent_key, ledger=ledger, findings=built["findings"])
    summary = summary_md(report)
    opinion = build_opinion(ledger, built["findings"], summary, cycle=opinion_cycle(store, target_key, agent_key))
    return Prepared(ledger=ledger, findings=built["findings"], curation=built["curation"], report=report, summary=summary,
                    opinion=opinion)


# finding 행에서 마감이 다시 정하는 열 — 사람·라벨·외부 반영이 쓰는 열(status*·recall_eligible·ra_entity_id·adh_record_id·
# visibility·owner_sub·created_at)은 처음 넣을 때만 정하고 다시 마감해도 건드리지 않는다(P-12).
_FINDING_CODE_COLUMNS: tuple[str, ...] = (
    "claim_uid", "origin", "target_key", "panel_id", "opinion_id", "project_id", "snapshot_id", "diff_id", "direction",
    "domain", "mechanism", "mechanism_detail", "mechanism_free", "change_kind", "subject_key", "ckeys_json",
    "trigger_condition", "severity", "sev3", "judgement", "detectability", "detect_tool", "evidence_grade", "precedent",
    "dangling", "cluster_key", "finding_json", "taxonomy_version", "rule_version", "ir_version", "diff_version",
    "unit_id", "source_kind", "source_id", "agent_key",
)


def _finding_row(prepared: Prepared, finding: Mapping[str, Any], *, opinion_id: str, scope: Mapping[str, Any]) -> dict:
    ledger = prepared.ledger
    detect = finding.get("detectability") or {}
    return {
        "claim_uid": finding["claim_uid"], "origin": "llm", "target_key": ledger.target_key, "panel_id": None,
        "opinion_id": opinion_id, "project_id": _s(ledger.target.get("project_id")),
        "snapshot_id": scope["snapshot_id"], "diff_id": scope["diff_id"], "direction": finding["direction"],
        "domain": _s(finding.get("domain")), "mechanism": finding.get("mechanism"),
        "mechanism_detail": finding.get("mechanism_detail"), "mechanism_free": finding.get("mechanism_free"),
        "change_kind": finding.get("change_kind"), "subject_key": finding.get("subject_key"),
        "ckeys_json": json.dumps((finding.get("subject") or {}).get("ckeys") or [], ensure_ascii=False),
        "trigger_condition": finding.get("trigger_condition"), "severity": finding.get("severity"),
        "sev3": finding.get("sev3"), "judgement": finding.get("judgement"), "detectability": detect.get("level"),
        "detect_tool": detect.get("tool"), "evidence_grade": finding.get("evidence_grade"),
        "precedent": finding.get("precedent"), "dangling": 1 if finding.get("dangling") else 0,
        "cluster_key": finding["cluster_key"], "finding_json": json.dumps(finding, ensure_ascii=False, sort_keys=True),
        "taxonomy_version": finding.get("taxonomy_version"), "rule_version": finding.get("rule_version"),
        "ir_version": finding.get("ir_version"), "diff_version": finding.get("diff_version"),
        "unit_id": finding["unit_ids"][0], "source_kind": SOURCE_KIND, "source_id": ledger.review_id,
        "agent_key": ledger.agent_key,
    }


def _write_findings(store: Any, prepared: Prepared, *, opinion_id: str, now: int) -> dict:
    """finding 을 finding_id 로 넣거나(회수 자격 0 — M2.md 5절 #9) 코드가 정하는 열만 고치고, 새 집합에 없는 이 검토의 finding
    과 그 인용 역색인을 지운다. 인용 역색인은 이 검토의 finding 전부를 다시 쓴다."""
    ledger = prepared.ledger
    target = store.query_one("SELECT kind, ref_id FROM rr_targets WHERE target_key = ?", (ledger.target_key,))
    scope = {"snapshot_id": None, "diff_id": None}
    if target is not None and target["kind"] == "diff":
        diff = store.query_one("SELECT id, target_snapshot_id FROM rr_diffs WHERE id = ?", (target["ref_id"],))
        if diff is not None:
            scope = {"snapshot_id": diff["target_snapshot_id"], "diff_id": diff["id"]}
    elif target is not None:
        scope = {"snapshot_id": target["ref_id"], "diff_id": None}
    owner = _s(ledger.head["owner_sub"])
    old = [r["finding_id"] for r in store.query(
        "SELECT finding_id FROM rr_findings WHERE target_key = ? AND source_kind = ? AND source_id = ?",
        (ledger.target_key, SOURCE_KIND, ledger.review_id))]
    new_ids = [f["claim_uid"] for f in prepared.findings]
    stale = sorted(set(old) - set(new_ids))
    touched = sorted(set(old) | set(new_ids))
    if touched:
        store.executemany("DELETE FROM rr_claim_refs WHERE claim_uid = ?", [(uid,) for uid in touched])
    if stale:
        store.executemany("DELETE FROM rr_findings WHERE finding_id = ?", [(uid,) for uid in stale])
    inserted = updated = 0
    for finding in prepared.findings:
        row = _finding_row(prepared, finding, opinion_id=opinion_id, scope=scope)
        have = store.query_one(f"SELECT {', '.join(_FINDING_CODE_COLUMNS)} FROM rr_findings WHERE finding_id = ?",
                               (finding["claim_uid"],))
        if have is None:
            cols = ["finding_id", "owner_sub", "visibility", "recall_eligible", "status", "created_at", "updated_at", *row]
            store.execute(f"INSERT INTO rr_findings({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                          (finding["claim_uid"], owner, "private", 0, "open", now, now, *row.values()))
            inserted += 1
        elif any(have[c] != row[c] for c in _FINDING_CODE_COLUMNS):
            store.execute(f"UPDATE rr_findings SET {', '.join(f'{c} = ?' for c in row)}, updated_at = ?"
                          " WHERE finding_id = ?", (*row.values(), now, finding["claim_uid"]))
            updated += 1
        # 원래 길이 — 들여온 박스에서 다시 마감하면 인용은 이미 200자로 줄인 글이다(R3B-7). 그때만 칸을 채운다(NULL 은 원문이다).
        known = {_s(c.get("ref")): c["quote_chars"] for c in finding.get("cites") or ()
                 if isinstance(c, Mapping) and c.get("quote_chars")}
        for cite in finding.get("_resolved_cites") or ():
            ref = _s(cite.get("ref"))
            if not ref or cite.get("dangling_reason") == narrative.ENGINE_MARKER:
                continue
            store.execute("INSERT OR REPLACE INTO rr_claim_refs(claim_uid, ref_type, ref, quote, owner_sub, target_key,"
                          " dangling, quote_chars) VALUES (?,?,?,?,?,?,?,?)",
                          (finding["claim_uid"], _s(cite.get("ref_type")) or "unknown", ref, _s(cite.get("quote")), owner,
                           ledger.target_key, 0 if cite.get("ok") else 1, known.get(ref)))
    return {"inserted": inserted, "updated": updated, "deleted": len(stale)}


def _enqueue(store: Any, prepared: Prepared, *, now: int) -> dict:
    """큐레이션 큐 — 택소노미 밖 메커니즘은 대상 안에서 같은 원문을 한 번만(전문가 수백 명이 같은 말을 수백 번 올리지 않게),
    인젝션 어휘에 걸린 finding 글은 패널 저장과 같은 규칙으로(같은 sha1 이 열려 있으면 다시 넣지 않는다)."""
    from app import nightly  # noqa: PLC0415 — 야간 잡 모듈은 학습·별칭 모듈을 끌고 온다(마감에서만 쓴다).

    ledger = prepared.ledger
    owner = _s(ledger.head["owner_sub"])
    unclassified = suspects = 0
    texts: dict[str, dict] = {}
    for finding in prepared.findings:
        free = _s(finding.get("mechanism_free")).strip()
        if finding.get("mechanism_detail") == "unclassified" and free and free not in texts:
            texts[free] = finding
    for free, finding in sorted(texts.items()):
        payload = {"finding_id": finding["claim_uid"], "mechanism_free": free, "target_key": ledger.target_key,
                   "source_kind": SOURCE_KIND, "candidates": nightly._detail_candidates(_s(finding.get("mechanism")))}
        if nightly.enqueue(store, "unclassified_code", payload, owner_sub=owner, now=now,
                           dedupe=lambda p: (p.get("source_kind"), p.get("target_key"), p.get("mechanism_free"))):
            unclassified += 1
    for finding in prepared.findings:
        suspect = narrative.suspect_hit(finding)
        if suspect is None:
            continue
        # 같은 finding 의 같은 글은 한 번만 — 사람이 승인(done)한 뒤 다시 마감해도 다시 올리지 않는다(승인이 되돌린 회수 자격을
        # 다시 마감이 건드리지 않는 것과 같은 까닭 — P-12). 원문 칸(raw)의 «» 카드 인용은 처음부터 200자로 싣고 원래 길이를 raw_chars
        # 에 적는다(R3B-3 — 큐는 박스 밖으로 나간다, 사용자 결정 1). sha1 은 줄이기 전 글의 것이라 같은 글은 같은 항목이다.
        payload = export.clip_queue_payload({**suspect, "claim_uid": finding["claim_uid"], "finding_id": finding["claim_uid"],
                                             "target_key": ledger.target_key, "source_kind": SOURCE_KIND})
        if nightly.enqueue(store, "suspect_text", payload, owner_sub=owner, now=now,
                           dedupe=lambda p: (p.get("sha1"), p.get("claim_uid"))):
            suspects += 1
    return {"unclassified": unclassified, "suspect_text": suspects}


def _write_opinion(store: Any, prepared: Prepared, *, now: int) -> None:
    """의견 행 — 이 검토의 자리(panel_id = review_id)를 지우고 다시 넣는다. 외부 반영 열(adh_record_id·ra_assessment_id)과 처음
    넣은 시각은 옛 행에서 이어받는다(다시 마감해도 같은 자리다)."""
    ledger, opinion = prepared.ledger, prepared.opinion
    prev = store.query_one("SELECT adh_record_id, ra_assessment_id, created_at FROM rr_seat_opinions WHERE opinion_id = ?",
                           (opinion["opinion_id"],))
    persona = store.query_one("SELECT persona_rev FROM rr_roster WHERE target_key = ? AND agent_key = ?",
                              (ledger.target_key, ledger.agent_key))
    store.execute("DELETE FROM rr_seat_opinions WHERE panel_id = ?", (ledger.review_id,))
    store.execute(
        "INSERT INTO rr_seat_opinions(opinion_id, target_key, panel_id, owner_sub, agent_key, domain, persona_rev, origin,"
        " cycle, opinion_json, final_stance, tool_calls_n, tool_calls_ok, knowledge_hits_n, cited_refs_json, quality_json,"
        " raised_finding_ids_json, excerpt_for_rag, adh_record_id, ra_assessment_id, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (opinion["opinion_id"], ledger.target_key, ledger.review_id, _s(ledger.head["owner_sub"]), ledger.agent_key,
         opinion["domain"], persona["persona_rev"] if persona is not None else None, "primary", opinion["cycle"],
         canonical_json(opinion), opinion["final_stance"], None, None, opinion["knowledge_hits_n"],
         json.dumps(opinion["cited_refs"], ensure_ascii=False), json.dumps(opinion["quality"], ensure_ascii=False),
         json.dumps(opinion["raised_finding_ids"], ensure_ascii=False), opinion["excerpt_for_rag"],
         prev["adh_record_id"] if prev is not None else None, prev["ra_assessment_id"] if prev is not None else None,
         prev["created_at"] if prev is not None else now))


def commit(store: Any, prepared: Prepared, *, lease_owner: str, now: int | None = None) -> dict | None:
    """마감 쓰기 — finding·인용 역색인·큐레이션 큐·의견 행·원장 마감(`planner.close_review_seat`, flow='cells' 대상만)·머리 칸.
    부른 쪽이 연 트랜잭션 안에서 돌고 선점을 먼저 본다 — 선점을 잃었으면 아무것도 쓰지 않고 None 이다(m-10)."""
    ledger = prepared.ledger
    now = now_epoch() if now is None else now
    with store.tx():
        if not review_cells._holds(store, ledger.target_key, ledger.agent_key, lease_owner):
            return None
        opinion_id = prepared.opinion["opinion_id"]
        written = _write_findings(store, prepared, opinion_id=opinion_id, now=now)
        queued = _enqueue(store, prepared, now=now)
        _write_opinion(store, prepared, now=now)
        seat = planner.close_review_seat(store, ledger.target_key, ledger.agent_key, review_id=ledger.review_id,
                                         opinion_id=opinion_id, model=ledger.head.get("model"),
                                         tier=ledger.head.get("tier"))
        report = _report_columns(store, ledger, prepared.report, prepared.summary, now=now)
        review_cells.write_head(store, ledger.target_key, ledger.agent_key, lease_owner=lease_owner, now=now,
                                sets={**report, "opinion_id": opinion_id, "findings_n": len(prepared.findings),
                                      "coverage_status": seat["status"]})
    return {"findings": written, "curation": queued, "opinion_id": opinion_id, "seat": seat,
            "revision": report["revision"], "report_hash": report["report_hash"]}


def _report_columns(store: Any, ledger: Ledger, report: Mapping[str, Any], summary: str, *, now: int) -> dict:
    """머리에 얼릴 보고서 칸 — canonical_json → gzip(mtime 0), 해시 sha256[:12], 바이트. 판번호는 해시가 직전과 다를 때만 오른다
    (m-07 — 같은 원장을 다시 마감하면 같은 바이트·같은 판이다). 마감 시각은 늘 이번 마감이다."""
    body = canonical_json(report).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()[:12]
    prev = store.query_one("SELECT report_hash, revision FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?",
                           (ledger.target_key, ledger.agent_key))
    revision = int(prev["revision"] or 0) if prev is not None else 0
    return {"report_gz": gzip.compress(body, mtime=0), "report_hash": digest, "report_bytes": len(body),
            "revision": revision if prev is not None and prev["report_hash"] == digest else revision + 1,
            "summary_md": summary, "finalized_at": now}


def write_blocked(store: Any, target_key: str, agent_key: str, *, lease_owner: str, why: str,
                  now: int | None = None) -> dict | None:
    """카드 묶음을 끝내 받지 못한 전문가의 보고서 — 상태 blocked, 까닭, 아무 단위도 보지 않았다는 '보지 못한 것'(파일럿이 범위의
    전문가마다 보고서 한 편을 갖게). finding·의견 행·원장은 쓰지 않는다. 부른 쪽이 연 트랜잭션 안에서, 선점을 쥔 채로(묶음
    실패로 셀을 닫은 뒤 · 머리를 막기 전) 부른다. 선점을 잃었으면 None 이다. 앞서 얼린 실제 보고서(ready·partial)가 있으면 그것을
    그대로 두고 `kept=True` 다(R3B-2 — 막힘은 머리의 상태·error 로 곁에 남는다)."""
    now = now_epoch() if now is None else now
    with store.tx():
        if not review_cells._holds(store, target_key, agent_key, lease_owner):
            return None
        prev = store.query_one("SELECT report_gz, report_hash, revision FROM rr_expert_reports WHERE target_key = ? AND"
                               " agent_key = ?", (target_key, agent_key))
        if prev is not None and prev["report_gz"] is not None and _frozen_state(prev["report_gz"]) != "blocked":
            # 앞 잡이 얼린 실제 보고서(ready·partial)는 덮지 않는다(R3B-2) — 이번 막힘은 그 곁의 머리 상태(blocked)와 까닭(error,
            # block_expert 가 적는다)으로 남는다. 덮으면 점검표 0행·finding 0건 보고서가 DB 에 남은 그 전문가의 finding 을 가린다.
            return {"revision": int(prev["revision"] or 0), "report_hash": prev["report_hash"], "kept": True}
        try:
            ledger = load_ledger(store, target_key, agent_key)        # 앞 잡이 얼린 묶음 — 그때 본 단위의 점검표가 남는다
        except cardpack.PackMissing:
            ledger = load_ledger(store, target_key, agent_key, with_pack=False)
        report = build_report(store, target_key, agent_key, ledger=ledger, blocked=why)
        columns = _report_columns(store, ledger, report, summary_md(report), now=now)
        review_cells.write_head(store, target_key, agent_key, lease_owner=lease_owner, now=now, sets=columns)
    return {"revision": columns["revision"], "report_hash": columns["report_hash"]}


def _frozen_state(report_gz: bytes) -> str | None:
    """얼린 보고서의 마감 상태(head.state). 읽지 못하면 None."""
    try:
        return (json.loads(gzip.decompress(report_gz).decode("utf-8")).get("head") or {}).get("state")
    except (OSError, ValueError, AttributeError):
        return None


def load_report(store: Any, target_key: str, agent_key: str) -> dict:
    """마감 때 얼린 보고서 JSON(머리의 report_gz). 없으면 E404 — 아직 마감하지 않았거나 폐기가 원문을 비웠다."""
    row = store.query_one("SELECT report_gz FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?",
                          (target_key, agent_key))
    if row is None or row["report_gz"] is None:
        raise AppError("E404", f"전문가 보고서가 없습니다 — {target_key}:{agent_key}.", 404)
    return json.loads(gzip.decompress(row["report_gz"]).decode("utf-8"))


# ================================================================ 마크다운 · 쪽
PAGE_CHARS = 25_000            # 쪽 하나의 글자 — Claude Code 의 MCP 결과 상한을 바깥 한도로 보고 쪽으로 나눈다(truncation.md 원칙)
PARTS: tuple[str, ...] = ("summary", "units", "cards", "full")
BLOCKS: tuple[str, ...] = ("background", "results", "recommendation", "minutes")   # WP4 통합 보고서 쪽의 블록 넷
# 절 → 쪽 블록. 쪽은 블록이 바뀌는 자리에서도 끊어(한 쪽에 블록 하나) 쪽을 차례로 이으면 full 마크다운과 같다.
_SECTION_BLOCK = {"head": "background", "scope": "background", "checklist": "results", "background": "results",
                  "unjudged_cards": "results", "by_unit": "results", "off_card": "results", "handoff": "recommendation",
                  "needs_info": "recommendation", "mechanisms": "minutes", "findings": "results", "quality": "minutes"}
_PART_SECTIONS = {
    "summary": ("head", "scope", "findings", "quality"),
    "units": ("by_unit", "off_card", "handoff", "needs_info", "mechanisms"),
    "cards": ("checklist", "background", "unjudged_cards"),
    "full": ("head", "scope", "checklist", "background", "unjudged_cards", "by_unit", "off_card", "handoff", "needs_info",
             "mechanisms", "findings", "quality"),
}
_STATE_LINE = {"ready": "다 봤다", "partial": "일부만 봤다", "blocked": "카드 묶음을 받지 못했다"}
# 그 단위를 본 카드 묶음(R3B-2) — 지금 묶음이 아니면 단위 줄에 적는다.
_PACK_STATE_LINE = {"earlier": " · 앞 카드 묶음으로 봤다", "absent": " · 이 단위를 본 카드 묶음이 이 박스에 없다"}
# 점검표 카드 머리의 출처(R3B-2) — 지금 묶음의 점검 카드가 아니면 머리 줄 끝에 적는다.
_CARD_SOURCE_LINE = {"unit_pack": " · 지금 카드 묶음의 점검 카드가 아니다(그 단위를 본 앞 묶음의 카드)",
                     "head_pack": " · 그 판정을 낸 카드 묶음이 이 박스에 없어 지금 묶음의 카드로 적었다",
                     "verdict": " · 이 카드를 실은 묶음이 이 박스에 없다(판정 행의 id 만 있다)"}
_MISSING_LINE = {"no_verdict": "실효 판정 없음(점검표 칸이 비었다)",
                 "not_in_unit_pack": "이 단위를 본 카드 묶음에서는 점검 카드가 아니었다(판정 대상 밖)",
                 "unit_pack_absent": "이 단위를 본 카드 묶음이 이 박스에 없어 판정 대상이었는지 모른다"}


# 마크다운에 펴는 글 안의 줄바꿈 — 카드 인용·모델 글은 여러 줄일 수 있다(엔진은 카드 글을 그대로 옮기라고 시킨다). 그대로 실으면
# 둘째 줄의 '#'·'- '·'1. ' 이 보고서의 새 제목·목록이 된다(R3B-6). 펼 때만 줄바꿈 자리를 ⏎ 로 적어 한 줄로 접는다 — JSON 의 글은 그대로다.
_LINE_BREAKS = re.compile(r"[ \t]*(?:\r\n|\r|\n|\u2028|\u2029|\x0b|\x0c|\x85)[ \t]*")
LINE_BREAK_MARK = " ⏎ "


def _one_line(text: str) -> str:
    return _LINE_BREAKS.sub(LINE_BREAK_MARK, text)


def _q(value: Any) -> str:
    """전문가·카드·대상의 글은 «» 안에 둔다(판단어 린터 밖). 줄바꿈은 ⏎ 로 접는다(R3B-6)."""
    return render.quote_source(_one_line(_s(value)))


def _qv(value: Any) -> str:
    """머리 칸 — 값이 없으면 '없음' 이라고 적는다(빈 «» 를 싣지 않는다)."""
    return _q(value) if _s(value) else "없음"


def _jw(judgement: Any) -> str:
    """판정 표기 — 코드는 린터가 받는 꼴(judgement=…)로, na 는 해당 없음, undetermined 는 보류다(WP5b 3.11.3)."""
    value = _s(judgement)
    if value == "na":
        return "해당 없음"
    if value == "undetermined":
        return "보류(judgement=undetermined)"
    return f"judgement={value}" if value in ("OK", "WARNING", "FAIL") else _q(value)


def _sev(value: Any) -> str:
    return f"severity={value}" if value in _SEV_RANK else ""


def _refs(lines: Sequence[Any], refs: Sequence[Any]) -> str:
    parts = [" · ".join(_q(x) for x in lines), " · ".join(_s(r) for r in refs)]
    return " → ".join(p for p in parts if p)


# 카드 인용 대조의 갈래(review_verify.quote_state) → 보고서 표기(R3B-4). 사람이 인용을 카드 원문과 견줄 때 이 줄을 읽는다 — 맞는
# 인용을 '불일치' 로 적지 않는다(짧아서 대조하지 않은 것 · 앱만 찾은 것 · 둘이 갈린 것 · 둘 다 못 찾은 것을 가른다).
_QUOTE_STATE_LINE = {
    "ok": "앱 재대조·엔진 검사 둘 다 카드 글에서 찾았다",
    "short": "인용이 대조 하한(15자 · 실질 글자 10자) 밑이라 대조하지 않았다",
    "app_only": "앱 재대조는 카드 글에서 찾았고{section} 엔진 검사는 찾지 못했다",
    "engine_only": "엔진 검사는 찾았다고 했고 앱 재대조는 카드 글에서 찾지 못했다 — 둘이 갈렸다",
    "not_found": "카드 글에 없다 — 앱 재대조·엔진 검사 둘 다 찾지 못했다",
    "unchecked": "댈 카드가 없어 대조하지 않았다",
}


def _quote_mark(state: Any, ok: Any, ref: str) -> str:
    """대조 표기 — 갈래가 없는 보고서(이 판 앞)는 quote_ok 로만 적는다(1 이면 찾았다, 아니면 갈래를 모른다)."""
    if state is None:
        state = "ok" if ok == 1 else None
    if state is None:
        return "대조 갈래가 이 보고서에 없다(앞 판의 보고서)"
    section = ref.split("#", 1)[1] if "#" in ref else ""
    return _QUOTE_STATE_LINE.get(str(state), _q(state)).format(section=f"(절 {section})" if section else "")


def _refs_mark(refs: Sequence[Any], refs_ok: Any) -> str:
    """변경 줄 참조의 대조 표기(R3B-5) — 참조가 있어야 하는 행(applies=yes 판정 · 카드 밖 리스크)이 비어 0 인 것을 '그 단위 밖 참조'
    와 가른다(review_verify.refs_verdict 는 둘 다 0 이다)."""
    if refs_ok == 1:
        return "그 단위 소속"
    if not refs:
        return "참조가 필요한 행인데 판정에 쓴 변경 줄을 대지 않았다" if refs_ok == 0 else "참조 없음"
    return "그 단위 밖 참조가 섞였다"


def _quote_line(prefix: str, ref: str, quote: str | None, chars: int | None, ok: Any, *, word: str,
                state: Any = None) -> str:
    if not quote:
        return f"{prefix} 인용 없음"
    mark = f" …({word} {chars}자 중 {QUOTE_SHOW}자)" if chars else ""
    return f"{prefix} {ref} {_q(quote)}{mark} — {_quote_mark(state, ok, ref)}"


def _md_head(report: Mapping[str, Any]) -> list[str]:
    h = report["head"]
    lines = [f"# 전문가 보고서 — {_q(h['name'])} ({_q(h['agent_key'])})",
             f"- 영역 {_q(h['domain'])} · 영역 안 순위 {h['rank_in_domain']} · tier {_q(h['tier'])} · 검토 id {_q(h['review_id'])}",
             f"- 마감 상태 {_q(h['state'])} — {_STATE_LINE.get(h['state'], '')}" + (f" · {_q(h['why'])}" if h.get("why") else ""),
             f"- 모델 {_qv(h['model'])} · 프롬프트 판 {_qv(h['prompt_rev'])} · 정규화 판 {_qv(h['norm_rev'])} · 대조 판"
             f" {_qv(h['verify_rev'])} · 보고서 판 {_qv(h['report_rev'])}"]
    pack = h.get("pack")
    if pack is None:
        lines.append(f"- 카드 묶음 없음 — 묶음 상태 {_q(h.get('pack_status'))}"
                     + (f" · {_q(h.get('pack_error'))}" if h.get("pack_error") else ""))
    else:
        lines.append(f"- 카드 묶음 {_q(pack['pack_key'][:16])} — 점검 카드 {pack['checkable_n']}장 · 배경 카드"
                     f" {pack['background_n']}장 · 본문 없는 카드 {pack['unrenderable_n']}장 · 묶음 근거 {_q(pack['card_basis'])}")
    if h.get("input_gaps"):
        lines.append(f"- 입력 결손 {' · '.join(_q(g) for g in h['input_gaps'])}")
    return ["\n".join(lines)]


def _md_scope(report: Mapping[str, Any], unit_id: str | None) -> list[str]:
    scope = report["scope"]
    totals = scope["totals"]["by_state"]
    items = [f"## 본 범위 — 단위 {scope['totals']['units']}개 · " + " · ".join(
        f"{_STATE_WORD.get(s, _q(s))} {n}" for s, n in totals.items())]
    for u in scope["units"]:
        if unit_id and u["unit_id"] != unit_id:
            continue
        line = f"- 단위 {u['unit_seq']} {_q(u['title'])} — {_STATE_WORD.get(u['state'], _q(u['state']))}"
        if u["counts"] is not None:
            c = u["counts"]
            line += (f"({_q(u['basis'])}) · judgement=FAIL {c['FAIL']} · judgement=WARNING {c['WARNING']} · 보류"
                     f" {c['undetermined']} · 걸림 없음 {c['OK']} · 해당 없음 {c['na']} · 카드 밖 지적 {u['offcard_n']}"
                     f" · 카드 밖 호출에 배경 카드 본문 {u['bg_full_n']}장 · 제목만 {u['bg_title_only_n']}장")
        elif u["state"] == "failed":
            line += f" {_q(u['error_code'])} · 호출 {u['tries']}번 · 내용 탓 {u['charged']}번"
        if not u["in_scope"] and u["state"] != "reviewed":
            line += " · 이 검토 잡의 범위 밖"
        line += _PACK_STATE_LINE.get(u.get("pack_state") or "", "")
        items.append(line)
    unseen = [x for x in scope["unseen"] if not unit_id or x["unit_id"] == unit_id]
    items.append(f"### 보지 못한 것 {len(unseen)}개")
    why_word = {"out_of_scope": "이 검토 잡의 범위 밖이라 대기", "pack_blocked": "카드 묶음을 받지 못해 보지 않았다"}
    for x in unseen:
        why = x["why"]
        text = why_word.get(why["code"]) or f"{_STATE_WORD.get(x['state'], _q(x['state']))} {_q(why['code'])}"
        items.append(f"- 단위 {x['unit_seq']} {_q(x['title'])} — {text}" + (f" {_q(why['text'])}" if why.get("text") else ""))
    if not unseen:
        items.append("- 없음 — 이 전문가의 단위 전부를 검토했다.")
    return items


def _md_check_row(row: Mapping[str, Any], card: Mapping[str, Any] | None = None) -> str:
    if row.get("missing"):
        return f"- 단위 {row['unit_seq']} — {_MISSING_LINE.get(row.get('missing_why') or 'no_verdict', _MISSING_LINE['no_verdict'])}"
    variants = " · ".join(f"{v['variant']} {_jw(v['judgement'])}" for v in row["variants"])
    marks = [m for m, on in (("변형 갈림", row["split"]), ("뒤집힘", row["flipped"]), ("다툼", row["disputed"]),
                             ("서버와 앱의 인용 대조 갈림", row["check_disagree"]),
                             ("카드 글이 바뀌었다 — 이 판정은 앞 글로 했다", row.get("card_changed"))) if on]
    if card is not None and row.get("alias") and row["alias"] != card.get("alias"):
        marks.append(f"그 단위를 본 묶음의 별칭 {row['alias']}")
    agree = {1: "fwd·rev 일치", 0: "fwd·rev 다름"}.get(row["agree"], "한 변형뿐")
    out = [f"- 단위 {row['unit_seq']} — {_jw(row['judgement'])} · applies={_q(row['applies'])} · 실효 변형 {row['variant']}"
           f"({agree}; {variants})" + (f" · 원래 {_jw(row['judgement_claimed'])}" if row.get("judgement_claimed") else "")
           + (f" · {_sev(row['sev'])}" if _sev(row.get("sev")) else ""),
           "  - " + _quote_line("카드 인용", row["quote_ref"], row["cq"], row["cq_chars"], row["quote_ok"], word="cq",
                                state=row.get("quote_state")),
           f"  - 변경 줄 {_refs(row['lines'], row['refs']) or '없음'} — {_refs_mark(row['refs'], row['refs_ok'])}"]
    if row.get("why"):
        out.append(f"  - 이유 {_q(row['why'])}")
    if row.get("need"):
        out.append(f"  - 필요 정보 {_q(row['need'])}")
    if row.get("nums_missing"):
        marks.append("근거 없는 수 " + " · ".join(_q(n) for n in row["nums_missing"]))
    if row.get("revised_from"):
        marks.append(f"엔진 보충 {_q(row['revised_from'])}")
    if marks:
        out.append("  - 표기 — " + " · ".join(marks))
    out.append(f"  - 등급 {_q(row.get('grade') or '경험칙')}" + (f" · finding {_q(row['finding_id'])}" if row.get("finding_id")
                                                             else ""))
    return "\n".join(out)


def _md_checklist(report: Mapping[str, Any], unit_id: str | None) -> list[str]:
    cards = report["checklist"]
    n_units = len({r["unit_id"] for c in cards for r in c["rows"]})
    items = [f"## 카드 점검표 — 점검 카드 {len(cards)}장 × 카드로 본 단위 {n_units}개"]
    if not cards:
        items.append("- 점검 카드가 없다 — " + ("카드 묶음이 없다." if report["head"].get("pack") is None
                                              else "카드 묶음의 점검 카드가 0장이다."))
    for card in cards:
        items.append(f"### {card['alias']} {_qv(card['card_id'])} {_qv(card['title'])} — {_qv(card['type'])} ·"
                     f" {_qv(card['confidence'])} · 등급 {_qv(card['grade'])} · {card['ref']}"
                     + _CARD_SOURCE_LINE.get(card.get("source") or "", ""))
        items += [_md_check_row(row, card) for row in card["rows"] if not unit_id or row["unit_id"] == unit_id]
    return items


def _md_background(report: Mapping[str, Any]) -> list[str]:
    cards = report["background"]
    items = [f"## 배경 카드 — 판정 대상 아님 {len(cards)}장(카드 밖 호출에 실린 수는 본 범위의 단위 줄에 있다)"]
    items += [f"- {c['alias']} {_q(c['card_id'])} {_q(c['title'])} — {_q(c['type'])} · {_q(c['confidence'])} · {c['ref']}"
              for c in cards] or ["- 없음"]
    return items


def _md_unjudged(report: Mapping[str, Any]) -> list[str]:
    cards = report["unjudged_cards"]
    why = {"unrenderable": "본문이 없는 카드(묶음에 글이 실리지 않았다)", "oversize": "창을 넘는 카드(계획의 oversize)"}
    items = [f"## 판정하지 못한 카드 {len(cards)}장"]
    items += [f"- card:{c['record_id']} {_q(c['card_id'])} {_q(c['title'])} — {why.get(c['why'], _q(c['why']))}"
              for c in cards] or ["- 없음"]
    return items


def _by_unit_rows(report: Mapping[str, Any]) -> dict[tuple[str, str], tuple[dict, dict]]:
    """(unit_id, record_id) → (점검표 카드 머리, 행) — 단위별 분석이 판정 행을 그 카드 아래에서 찾는 열쇠(R3B-2)."""
    return {(r["unit_id"], str(c["record_id"])): (c, r) for c in report["checklist"] for r in c["rows"] if not r.get("missing")}


def _unit_card(rows: Mapping[tuple[str, str], tuple[dict, dict]], unit_id: str, key: str) -> tuple[dict, dict] | None:
    """by_unit 의 카드 열쇠(record_id) → (카드, 행). 이 판 앞의 보고서(별칭을 실었다)는 그 단위 행의 별칭으로도 찾는다."""
    hit = rows.get((unit_id, key))
    if hit is None:
        hit = next(((c, r) for (u, _rid), (c, r) in rows.items() if u == unit_id and r.get("alias", c["alias"]) == key), None)
    return hit


def _md_by_unit(report: Mapping[str, Any], unit_id: str | None) -> list[str]:
    rows = _by_unit_rows(report)
    items = ["## 단위별 분석"]
    for u in report["by_unit"]:
        if unit_id and u["unit_id"] != unit_id:
            continue
        items.append(f"### 단위 {u['unit_seq']} {_q(u['title'])} — {_q(u['basis'])}")
        for judgement in ("FAIL", "WARNING"):
            items.append(f"#### {_jw(judgement)} {len(u[judgement])}장")
            for key in u[judgement]:
                hit = _unit_card(rows, u["unit_id"], key)
                if hit is None:
                    items.append(f"- card:{key} — 점검표에 이 판정 행이 없다")
                    continue
                card, row = hit
                lines = [f"- {row.get('alias', card['alias'])} {_qv(card['card_id'])} {_qv(card['title'])} — {row['quote_ref']}"]
                lines.append(f"  - 영향 경로 {_q(row.get('path') or '')}" + (f" · {_sev(row['sev'])}" if _sev(row.get("sev"))
                                                                          else "")
                             + f" · 메커니즘 {_q(row.get('mech') or row.get('mech_free') or 'unclassified')}")
                for cond in row["conds"]:
                    mark = f" …(조건 {cond['cond_chars']}자 중 {QUOTE_SHOW}자)" if cond.get("cond_chars") else ""
                    lines.append(f"  - 조건별 대조 {_q(cond['cond'])}{mark} — met={_q(cond.get('met'))} {_q(cond.get('note'))}"
                                 f" ({_refs(cond['lines'], cond['refs']) or '참조 없음'})")
                lines.append(f"  - 닫는 확인 {_q(row.get('check_kind') or '')} {_q(row.get('check') or '')}")
                lines.append(f"  - 이유 {_q(row.get('why') or '')}")
                items.append("\n".join(lines))
        items.append(f"#### 보류 {len(u['undetermined'])}장 — 필요 자료")
        for key in u["undetermined"]:
            hit = _unit_card(rows, u["unit_id"], key)
            if hit is None:
                items.append(f"- card:{key} — 점검표에 이 판정 행이 없다")
                continue
            card, row = hit
            items.append(f"- {row.get('alias', card['alias'])} {_qv(card['title'])} — 필요 정보 {_q(row.get('need') or '')}"
                         + (" · 변형 갈림" if row["split"] else ""))
        items.append(f"#### 걸림 없음 · 해당 없음 {len(u['OK']) + len(u['na'])}장")
        for judgement in ("OK", "na"):
            for key in u[judgement]:
                hit = _unit_card(rows, u["unit_id"], key)
                items.append(f"- card:{key} — {_jw(judgement)} · 점검표에 이 판정 행이 없다" if hit is None else
                             f"- {hit[1].get('alias', hit[0]['alias'])} {_qv(hit[0]['title'])} — {_jw(judgement)}")
        items.append(f"#### 카드 밖 지적 {len(u['off_card'])}건 · direction=improvement {len(u['improvements'])}건")
        for n in u["off_card"] + u["improvements"]:
            f = report["off_card"][n]
            items.append(f"- {_q(f['dir'])} {_q(f['title'])} — 경로 {_q(f.get('path') or '')}(카드 밖 지적 절의 {n + 1}번)")
    if len(items) == 1:
        items.append("- 검토한 단위가 없다.")
    return items


def _md_off_card(report: Mapping[str, Any], unit_id: str | None) -> list[str]:
    rows = [f for f in report["off_card"] if not unit_id or f["unit_id"] == unit_id]
    items = [f"## 카드 밖 지적 — {len(rows)}건"]
    for n, f in enumerate(report["off_card"]):
        if unit_id and f["unit_id"] != unit_id:
            continue
        lines = [f"- {n + 1}. 단위 {f['unit_seq']} · direction={_q(f['dir'])} {_q(f['title'])}",
                 f"  - 경로 {_q(f.get('path') or '')}" + (f" · {_sev(f['sev'])}" if _sev(f.get("sev")) else "")
                 + f" · conf {_q(f.get('conf') or '')} · 메커니즘 {_q(f.get('mech') or '')} {_q(f.get('mech_free') or '')}"]
        if f.get("record_id"):
            lines.append("  - 근거 배경 카드 " + _quote_line(_q(f.get("src")), f["quote_ref"], f["q"], f["q_chars"],
                                                         f["quote_ok"], word="q", state=f.get("quote_state")))
        else:
            lines.append("  - 근거 경험칙 — 카드 근거 없음(코드가 원문과 대조할 수 없다)")
        lines.append(f"  - 변경 줄 {_refs(f['lines'], f['refs']) or '없음'} — {_refs_mark(f['refs'], f.get('refs_ok'))}")
        lines.append(f"  - 닫는 확인 {_q(f.get('check_kind') or '')} {_q(f.get('check') or '')}"
                     + (f" · finding {_q(f['finding_id'])}" if f.get("finding_id") else ""))
        items.append("\n".join(lines))
    if not rows:
        items.append("- 없음")
    return items


def _md_handoff(report: Mapping[str, Any], unit_id: str | None) -> list[str]:
    rows = [h for h in report["handoff"] if not unit_id or h["unit_id"] in (unit_id, None)]
    items = [f"## 다른 영역으로 넘김 {len(rows)}건"]
    word = {"sweep": "훑기", "off_card": "카드 밖 호출"}
    items += [f"- → {_q(h['to'])} · " + (f"단위 {h['unit_seq']} · " if h.get("unit_seq") else "")
              + f"{word.get(h['source'], _q(h['source']))} — {_q(h.get('why') or '')}"
              + (f" ({_refs(h['lines'], h['refs'])})" if h["lines"] or h["refs"] else "") for h in rows] or ["- 없음"]
    return items


def _md_needs(report: Mapping[str, Any], unit_id: str | None) -> list[str]:
    units_ = [u for u in report["needs_info"] if not unit_id or u["unit_id"] == unit_id]
    items = [f"## 필요한 추가 정보 {sum(len(u['items']) for u in units_)}건"]
    for u in units_:
        items.append(f"### 단위 {u['unit_seq']} {_q(u['title'])}")
        items += [f"- {_q(x['text'])} — " + " · ".join("카드 밖 호출" if s == "off_card" else f"{s} 보류" for s in x["from"])
                  for x in u["items"]]
    if not units_:
        items.append("- 없음")
    return items


def _md_mechanisms(report: Mapping[str, Any], unit_id: str | None) -> list[str]:
    items = ["## 따져 본 메커니즘(카드 밖 호출)"]
    items += [f"- 단위 {m['unit_seq']} — " + (" · ".join(_q(s) for s in m["seen"]) or "적힌 것 없음")
              for m in report["mechanisms"] if not unit_id or m["unit_id"] == unit_id] or ["- 없음"]
    return items


def _md_findings(report: Mapping[str, Any], unit_id: str | None) -> list[str]:
    rows = [f for f in report["findings"] if not unit_id or f["unit_id"] == unit_id]
    items = [f"## 올린 finding {len(rows)}건 — 등록부에 병합하지 않는다(M2)"]
    for f in rows:
        cards = " · ".join(_q(c.get("card_id") or c["record_id"]) for c in f["cards"])
        line = (f"- {_q(f['claim_uid'])} — 단위 {f['unit_seq']} · direction={_q(f['direction'])} · {_sev(f['severity'])} ·"
                f" {_jw(f['judgement'])}" + (f"(원래 {_jw(f['judgement_claimed'])})" if f.get("judgement_claimed") else "")
                + f" · 등급 {_q(f['evidence_grade'])} · 메커니즘 {_q(f['mechanism'])} {_q(f.get('mechanism_free') or '')}"
                + f" · 주체 {_q(f.get('subject_key') or '')}" + (" 약한 주체" if f["weak_subject"] else "")
                + (f" · 카드 {cards}" if cards else "") + (" · 카드 밖" if f["off_card"] else ""))
        detail = [f"  - 주장 {_q(f['claim'])}"]
        flags = [(len(f["dangling"]), "지어낸 참조"), (len(f["quote_mismatch"]), "인용 불일치")]
        marks = [f"{word} {n}" for n, word in flags if n]
        if f["unquoted_numbers"]:
            marks.append("근거 없는 수 " + " · ".join(_q(n) for n in f["unquoted_numbers"]))
        if marks:
            detail.append("  - 인용 대조 — " + " · ".join(marks))
        items.append("\n".join([line, *detail]))
    if not rows:
        items.append("- 없음")
    return items


def _md_quality(report: Mapping[str, Any]) -> list[str]:
    quality = report.get("quality") or {}
    items = ["## 검토 품질"]
    if quality.get("text"):
        items.append(str(quality["text"]))
    else:
        items.append(f"- 수치 {_q(canonical_json(quality.get('json')))}")
    return items


def _md_items(report: Mapping[str, Any], *, part: str = "full", unit_id: str | None = None) -> list[tuple[str, str]]:
    """(쪽 블록, 글 조각) 목록 — 조각을 줄바꿈으로 이으면 그 부분의 마크다운이다."""
    if part not in PARTS:
        raise AppError("E100", f"part 는 {list(PARTS)} 가운데 하나다 — {part!r}.", 422)
    render_of = {
        "head": lambda: _md_head(report), "scope": lambda: _md_scope(report, unit_id),
        "checklist": lambda: _md_checklist(report, unit_id), "background": lambda: _md_background(report),
        "unjudged_cards": lambda: _md_unjudged(report), "by_unit": lambda: _md_by_unit(report, unit_id),
        "off_card": lambda: _md_off_card(report, unit_id), "handoff": lambda: _md_handoff(report, unit_id),
        "needs_info": lambda: _md_needs(report, unit_id), "mechanisms": lambda: _md_mechanisms(report, unit_id),
        "findings": lambda: _md_findings(report, unit_id), "quality": lambda: _md_quality(report),
    }
    return [(_SECTION_BLOCK[name], text) for name in _PART_SECTIONS[part] for text in render_of[name]()]


def render_report_md(report: Mapping[str, Any], *, unit_id: str | None = None, part: str = "full") -> str:
    """보고서 JSON → 마크다운(줄이지 않는다 — D-21). part ∈ summary(머리·범위·finding·품질) · units(단위별 분석·카드 밖·넘김·
    필요 정보·메커니즘) · cards(점검표·배경·판정하지 못한 카드) · full. unit_id 를 주면 그 단위의 줄만 싣는다."""
    return "\n".join(text for _block, text in _md_items(report, part=part, unit_id=unit_id))


def render_pages(report: Mapping[str, Any], page_chars: int = PAGE_CHARS, *, part: str = "full",
                 unit_id: str | None = None) -> list[dict]:
    """마크다운을 쪽으로 — 쪽 하나가 page_chars 를 넘지 않게 조각을 차례로 담고(조각 하나가 그보다 길면 그 조각만으로 한 쪽 —
    자르지 않는다), 블록이 바뀌는 자리에서도 끊는다. 모양은 WP4 통합 보고서 쪽 {page_no, kind, title, blocks{background[],
    results[], recommendation[], minutes[]}} 이고, 쪽마다 차례로 블록 조각을 이으면 render_report_md(part) 와 같다."""
    pages: list[tuple[str, list[str]]] = []
    size = 0
    for block, text in _md_items(report, part=part, unit_id=unit_id):
        if pages and pages[-1][0] == block and size + 1 + len(text) <= page_chars:
            pages[-1][1].append(text)
            size += 1 + len(text)
            continue
        pages.append((block, [text]))
        size = len(text)
    name = report["head"]["name"]
    return [{"page_no": n, "kind": "expert_report", "title": f"전문가 보고서 {_q(name)} — 쪽 {n}/{len(pages)}",
             "blocks": {b: (texts if b == block else []) for b in BLOCKS}}
            for n, (block, texts) in enumerate(pages, start=1)]
