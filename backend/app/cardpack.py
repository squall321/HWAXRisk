# 카드 묶음(엔진 /card-review/pack 응답)을 확인·동결·꺼내는 곳 — 호출에 싣는 카드와 인용 대조의 원문은 얼린 팩 하나다(m2-wp3b S3)
"""엔진이 정규화한 전문가의 카드 전부를 통째로 얼리고, 호출마다 거기서 꺼낸 항목을 그대로 되보낸다(D-14 · C-9~C-11).

- 앱은 카드를 정규화하지 않는다. 정규화가 두 곳에 있으면 한쪽만 고쳐졌을 때 '모델이 본 글' 과 '대조하는 글' 이 갈린다.
  대신 얼린 것을 그대로 되보내고, 인용 대조도 그 얼린 글(`card_text`)로 한다. 며칠 도는 동안 카드가 고쳐져도 흔들리지 않는다.
- `rr_card_packs` 는 (agent_key, pack_key) 내용 주소이고 소유자가 없는 박스 지역 사본이다(반출·이양·폐기 제외 — C-9).
  `pack_key` 는 앱이 센다 — 휘발 칸(`PACK_VOLATILE`)을 뺀 팩 본문 전체의 sha256 이다. 엔진의 `pack_hash` 는 카드 칸 일부만 담아
  (`sources_n`·`tier`·`chars`·`unrenderable`·`norm_rev` 가 빠진다) 출처 수가 바뀐 팩이 같은 열쇠로 와 옛 팩이 영영 남았다
  (반대 검토 C2a RC-3) — 그래서 열쇠가 아니라 기록 열로만 남긴다. 검토 머리(`rr_expert_reports.pack_hash`)는 `pack_key` 를 가리킨다.
  같은 팩을 두 번·두 타깃에서 얼려도 행은 하나다(INSERT OR IGNORE).
- 문제가 있는 팩은 얼리지 않는다 — 얼린 것이 며칠 동안 정본이 되므로 들어올 때 한 번 본다(`check_pack`).
- '0장' 과 '못 받았다' 를 섞지 않는다(P-08 · X1-25) — 0장 응답은 두 번 연달아이고 그 전문가의 앞선 묶음에도 카드가 없을 때만
  `empty` 다(`judge_pack`).

엔진 팩의 개수 칸 — `cards_total` 은 그릴 수 있는 카드(`cards`) 수, `listed_total` 은 목록에 있던 전부(`cards` + 본문 없는
`unrenderable`)다(HWAXAgentServer `card_review.build_pack`). 설계서의 '`cards_total == len(cards) + len(unrenderable)`' 은 엔진의
`listed_total` 로 읽는다 — 계약 예제 `pack_ok.json` 이 그 모양이다.
"""
from __future__ import annotations

import copy
import gzip
import hashlib
import json
import threading
from collections import Counter, OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from app import review_ops
from app.common import canonical_json, now_epoch

LRU_SIZE = 32

CARD_BASIS_CARDS = "cards"              # 점검 카드가 하나라도 있다 — 훑기 → 카드 대조 → 카드 밖
CARD_BASIS_BACKGROUND = "background"    # 카드는 있는데 전부 배경 — 카드 대조 묶음이 0개
CARD_BASIS_NONE = "none"                # 0장 — 역할만으로 카드 밖 호출(role_only)

PACK_OK = "ok"
PACK_EMPTY = "empty"
PACK_ERROR = "error"
# 앱이 내는 팩 오류 코드 — review_ops 의 팩 재시도 부류(60초부터 두 배, 6번)로 다시 받는다.
SUSPECT_EMPTY = "suspect_empty"         # 0장인데 아직 두 번 연달아가 아니거나 앞선 묶음에 카드가 있었다
PACK_INVALID = "pack_invalid"           # check_pack 이 문제를 찾았다 — 얼리지 않는다
EMPTY_CONFIRMATIONS = 2                 # 0장 응답이 이만큼 연달아야 empty 다
# 팩의 내용 주소(pack_key)에서 빼는 칸 — 같은 카드를 다시 받아도 바뀌는 값(받은 시각·쓴 자격·조회 길)이다. 나머지 칸은 전부 든다.
PACK_VOLATILE: tuple[str, ...] = ("fetched_at", "credential", "source")


class PackInvalid(ValueError):
    """check_pack 이 문제를 찾은 팩 — 얼리지 않는다."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("카드 묶음을 얼리지 않는다 — " + "; ".join(self.problems))


class PackMissing(LookupError):
    """검토 머리는 묶음을 가리키는데 rr_card_packs 에 그 행이 없다 — 조용히 '카드 없음' 으로 읽지 않는다."""


# ---------------------------------------------------------------- 카드 글(엔진 card_review 와 같은 정의)
def text_sha(sections: Sequence[Mapping[str, Any]]) -> str:
    """절 목록의 해시 — sha256("\\n".join(f"{sid}\\t{title}\\n{text}")) (엔진 `_text_sha` 와 같은 식)."""
    joined = "\n".join(f"{s.get('sid')}\t{s.get('title')}\n{s.get('text')}" for s in sections)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def card_text(card: Mapping[str, Any]) -> str:
    """인용 대조의 원문 — 절 text 를 줄바꿈으로 이은 것. 머리 줄(종류·등급·제목)은 인용 대상이 아니다(엔진 `card_text`)."""
    return "\n".join(str(s.get("text") or "") for s in card.get("sections") or () if isinstance(s, Mapping))


def pack_key(pack: Mapping[str, Any]) -> str:
    """팩의 내용 주소 — 휘발 칸(`PACK_VOLATILE`)을 뺀 팩 본문의 sha256(canonical_json). 앱이 쓰는 칸(등급의 `sources_n`·
    `standard_refs`·`confidence`, `tier`·`chars`·`unrenderable`·`norm_rev`·역할…)이 하나라도 다르면 다른 열쇠다."""
    body = {key: value for key, value in pack.items() if key not in PACK_VOLATILE}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def card_basis(pack: Mapping[str, Any]) -> str:
    """점검 카드 ≥1 이면 cards, 카드는 있는데 전부 배경이면 background, 0장이면 none."""
    cards = [c for c in pack.get("cards") or () if isinstance(c, Mapping)]
    if any(c.get("checkable") is True for c in cards):
        return CARD_BASIS_CARDS
    return CARD_BASIS_BACKGROUND if cards else CARD_BASIS_NONE


# ---------------------------------------------------------------- 확인
def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def check_pack(pack: Any, *, agent_key: str) -> list[str]:
    """받은 팩의 무결성 문제 목록(빈 목록 = 통과). 보는 것은 다섯이다.

    1. `pack_hash`·`norm_rev`·`role_sha` 가 있고 `agent_key` 가 청한 키와 같다.
    2. 별칭이 팩 안에서 유일하고 `record_id` 도 유일하다(본문 없는 카드까지).
    3. 카드마다 `text_sha == sha256("\\n".join(f"{sid}\\t{title}\\n{text}"))` 다.
    4. 개수·합 — `cards_total == len(cards)`, `listed_total == len(cards) + len(unrenderable)`, `checkable_n` 은 점검 카드 수,
       `chars_total` 은 `chars` 의 합이다.
    5. 절이 하나도 없는 카드가 `cards` 에 없다(그런 카드는 `unrenderable` 에만 있다).
    """
    if not isinstance(pack, Mapping):
        return ["pack:not_object"]
    problems: list[str] = []
    for field in ("pack_hash", "norm_rev", "role_sha"):
        if not isinstance(pack.get(field), str) or not pack[field].strip():
            problems.append(f"missing:{field}")
    if pack.get("agent_key") != agent_key:
        problems.append(f"agent_key:{pack.get('agent_key')!r}≠{agent_key!r}")

    cards = pack.get("cards")
    unrenderable = pack.get("unrenderable")
    if not isinstance(cards, list):
        problems.append("cards:not_list")
        cards = []
    if not isinstance(unrenderable, list):
        problems.append("unrenderable:not_list")
        unrenderable = []

    aliases: list[str] = []
    records: list[str] = []
    chars = 0
    for index, card in enumerate(cards):
        if not isinstance(card, Mapping):
            problems.append(f"card[{index}]:not_object")
            continue
        alias = card.get("alias")
        label = alias if isinstance(alias, str) and alias else f"card[{index}]"
        if not isinstance(alias, str) or not alias:
            problems.append(f"{label}:alias")
        else:
            aliases.append(alias)
        if not isinstance(card.get("record_id"), str) or not card["record_id"]:
            problems.append(f"{label}:record_id")
        else:
            records.append(card["record_id"])
        if not isinstance(card.get("checkable"), bool):
            problems.append(f"{label}:checkable")
        if _int(card.get("chars")) is None:
            problems.append(f"{label}:chars")
        else:
            chars += card["chars"]
        sections = card.get("sections")
        if not isinstance(sections, list) or not sections:
            problems.append(f"{label}:no_sections")
        elif not all(isinstance(s, Mapping) and isinstance(s.get("text"), str) for s in sections):
            problems.append(f"{label}:section_shape")
        elif card.get("text_sha") != text_sha(sections):
            problems.append(f"{label}:text_sha")
    for index, item in enumerate(unrenderable):
        if not isinstance(item, Mapping) or not isinstance(item.get("record_id"), str) or not item["record_id"]:
            problems.append(f"unrenderable[{index}]:record_id")
            continue
        if item.get("sections"):
            problems.append(f"unrenderable[{index}]:has_sections")
        records.append(item["record_id"])

    for alias, n in sorted(Counter(aliases).items()):
        if n > 1:
            problems.append(f"alias_dup:{alias}")
    for record_id, n in sorted(Counter(records).items()):
        if n > 1:
            problems.append(f"record_dup:{record_id}")

    checkable = sum(1 for c in cards if isinstance(c, Mapping) and c.get("checkable") is True)
    if _int(pack.get("cards_total")) != len(cards):
        problems.append(f"count:cards_total {pack.get('cards_total')!r}≠{len(cards)}")
    if _int(pack.get("listed_total")) != len(cards) + len(unrenderable):
        problems.append(f"count:listed_total {pack.get('listed_total')!r}≠{len(cards) + len(unrenderable)}")
    if _int(pack.get("checkable_n")) != checkable:
        problems.append(f"count:checkable_n {pack.get('checkable_n')!r}≠{checkable}")
    if _int(pack.get("chars_total")) != chars:
        problems.append(f"count:chars_total {pack.get('chars_total')!r}≠{chars}")
    return problems


# ---------------------------------------------------------------- 받은 결과 가르기
@dataclass(frozen=True)
class PackVerdict:
    """팩 응답 하나를 가른 것.

    - `status` — ok | empty | error.
    - `code` — error 일 때의 코드다. 엔진 오류는 그 `code`(없으면 상태로 `review_ops.classify` 가 정한 이름), 앱이 낸 것은
      `suspect_empty`·`pack_invalid` 다. 다음 할 일(팩 재시도·잡 보류·기다림)은 `review_ops.classify(code)` 가 정한다.
    - `zero_streak` — 이번 응답까지 연달은 0장 응답 수. 0장이 아니면 0 이다. 러너가 그 전문가 머리에 들고 있다가 다음
      `judge_pack` 의 `zero_streak_before` 로 넘긴다.
    """

    status: str
    code: str | None = None
    problems: tuple[str, ...] = ()
    cards_n: int = 0
    zero_streak: int = 0


def had_cards_before(store: Any, agent_key: str) -> bool:
    """이 전문가의 앞선 묶음(어느 타깃이든)에 카드가 한 장이라도 있었나."""
    row = store.query_one("SELECT 1 FROM rr_card_packs WHERE agent_key = ? AND cards_total > 0 LIMIT 1", (agent_key,))
    return row is not None


def judge_pack(store: Any, agent_key: str, *, http_status: int, body: Any, zero_streak_before: int = 0) -> PackVerdict:
    """팩 응답(상태·본문)을 ok·empty·error 로 가른다(m2-wp3b S3).

    - 200 · 카드 ≥1 · 확인 통과 → ok. 확인에 걸리면 error(`pack_invalid`)이고 얼리지 않는다.
    - 200 · 0장 → 이번까지 0장이 두 번 연달았고 그 전문가의 앞선 묶음에도 카드가 없을 때만 empty, 아니면
      error(`suspect_empty`)다 — 복원 창에 받은 '0장' 이 타깃 끝까지 '카드 결손 전문가' 로 굳지 않게(P-08).
    - 그 밖의 상태 → error. 코드는 본문의 `code`, 없으면 상태로 정한 이름이다(`review_ops.classify`).
    통신 실패(응답이 없다)는 이 함수를 지나지 않는다 — 부른 쪽이 그 오류 코드로 `review_ops.classify` 를 바로 부른다.
    """
    if http_status != 200:
        code = body.get("code") if isinstance(body, Mapping) else None
        if not isinstance(code, str) or not code.strip():
            code = review_ops.classify(None, http_status=http_status).code
        return PackVerdict(status=PACK_ERROR, code=code.strip())
    problems = check_pack(body, agent_key=agent_key)
    if problems:
        return PackVerdict(status=PACK_ERROR, code=PACK_INVALID, problems=tuple(problems))
    cards_n = len(body["cards"])
    if cards_n:
        return PackVerdict(status=PACK_OK, cards_n=cards_n)
    zero = max(int(zero_streak_before), 0) + 1
    if zero >= EMPTY_CONFIRMATIONS and not had_cards_before(store, agent_key):
        return PackVerdict(status=PACK_EMPTY, zero_streak=zero)
    return PackVerdict(status=PACK_ERROR, code=SUSPECT_EMPTY, zero_streak=zero)


# ---------------------------------------------------------------- 얼리기
def freeze_pack(store: Any, pack: Mapping[str, Any], *, agent_key: str) -> dict:
    """확인을 지난 팩을 rr_card_packs 에 (agent_key, pack_key) 로 INSERT OR IGNORE 해 얼린다(호출마다 한 번 커밋 — 전문가마다 따로).

    문제가 있으면 `PackInvalid` 이고 행을 남기지 않는다. 반환 {pack_key, pack_hash, cards_total, checkable_n, chars_total,
    unrenderable_n, card_basis, inserted} — 검토 머리(`rr_expert_reports.pack_hash`)에는 `pack_key` 를 적는다(엔진 `pack_hash`
    가 아니다). 같은 `pack_key` 면 휘발 칸 말고는 같은 팩이라 먼저 얼린 행이 남는다. `pack_gz` 는 팩 전체의 canonical_json
    gzip(mtime 0 — 같은 팩이면 같은 바이트)이고 `manifest_json` 은 본문(절)을 뺀 카드 목록이다.
    """
    problems = check_pack(pack, agent_key=agent_key)
    if problems:
        raise PackInvalid(problems)
    cards = list(pack["cards"])
    payload = canonical_json(pack)
    manifest = [{k: v for k, v in card.items() if k != "sections"} for card in cards]
    fetched = _int(pack.get("fetched_at"))
    key = pack_key(pack)
    inserted = store.execute(
        "INSERT OR IGNORE INTO rr_card_packs (agent_key, pack_key, pack_hash, norm_rev, role_sha, cards_total,"
        " checkable_n, chars_total, unrenderable_n, manifest_json, pack_gz, source, fetched_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (agent_key, key, pack["pack_hash"], pack["norm_rev"], pack["role_sha"], len(cards), pack["checkable_n"],
         pack["chars_total"], len(pack["unrenderable"]), canonical_json(manifest),
         gzip.compress(payload.encode("utf-8"), mtime=0), str(pack.get("source") or ""),
         fetched if fetched and fetched > 0 else now_epoch()))
    return {"pack_key": key, "pack_hash": pack["pack_hash"], "cards_total": len(cards), "checkable_n": pack["checkable_n"],
            "chars_total": pack["chars_total"], "unrenderable_n": len(pack["unrenderable"]),
            "card_basis": card_basis(pack), "inserted": bool(inserted)}


# ---------------------------------------------------------------- 꺼내기
@dataclass(frozen=True)
class FrozenPack:
    """얼린 팩의 읽기 전용 뷰(프로세스 LRU 가 나눠 쓴다 — 고치지 않는다. 요청에 실을 때는 `cards_for` 가 복사본을 준다).

    - `pack_key` — 앱의 내용 주소(얼린 행의 열쇠), `pack_hash` — 엔진이 낸 값(기록용).
    - `cards` — 별칭 → 카드(팩 항목 그대로), `order` — 팩의 별칭 순서.
    - `record_cards` — record_id → 카드. 인용 검증 스코프(`narrative.SpecContext.card_pack`)가 이것을 받는다.
    - `checkable`·`background` — 점검·배경 카드의 별칭(팩 순서), `unrenderable` — 본문 없는 카드(판정할 수 없다).
    """

    agent_key: str
    pack_key: str
    pack_hash: str
    norm_rev: str
    role: str
    role_sha: str
    raw: Mapping[str, Any]
    cards: Mapping[str, Mapping[str, Any]]
    order: tuple[str, ...]
    record_cards: Mapping[str, Mapping[str, Any]]
    by_record: Mapping[str, str]
    checkable: tuple[str, ...]
    background: tuple[str, ...]
    unrenderable: tuple[Mapping[str, Any], ...]

    @property
    def card_basis(self) -> str:
        return card_basis(self.raw)


def view_of(pack: Mapping[str, Any]) -> FrozenPack:
    """팩 dict → FrozenPack(확인은 하지 않는다 — 얼린 것과 계약 예제에만 쓴다)."""
    cards = [c for c in pack.get("cards") or () if isinstance(c, Mapping)]
    by_alias = {str(c["alias"]): c for c in cards}
    return FrozenPack(
        agent_key=str(pack.get("agent_key") or ""), pack_key=pack_key(pack), pack_hash=str(pack.get("pack_hash") or ""),
        norm_rev=str(pack.get("norm_rev") or ""), role=str(pack.get("role") or ""),
        role_sha=str(pack.get("role_sha") or ""), raw=MappingProxyType(dict(pack)),
        cards=MappingProxyType(by_alias), order=tuple(by_alias),
        record_cards=MappingProxyType({str(c["record_id"]): c for c in cards}),
        by_record=MappingProxyType({str(c["record_id"]): str(c["alias"]) for c in cards}),
        checkable=tuple(a for a, c in by_alias.items() if c.get("checkable") is True),
        background=tuple(a for a, c in by_alias.items() if c.get("checkable") is not True),
        unrenderable=tuple(u for u in pack.get("unrenderable") or () if isinstance(u, Mapping)),
    )


_LRU: OrderedDict[tuple[str, str, str], FrozenPack] = OrderedDict()
_LRU_LOCK = threading.Lock()


def _cache_key(store: Any, agent_key: str, key: str) -> tuple[str, str, str]:
    return (str(getattr(store, "db_path", id(store))), agent_key, key)


def load_pack(store: Any, agent_key: str, key: str) -> FrozenPack:
    """얼린 팩(프로세스 안 LRU 32 — DB 파일·전문가·pack_key 가 열쇠). `key` 는 freeze_pack 이 낸 pack_key 다. 행이 없으면 PackMissing."""
    cache = _cache_key(store, agent_key, key)
    with _LRU_LOCK:
        hit = _LRU.get(cache)
        if hit is not None:
            _LRU.move_to_end(cache)
            return hit
    row = store.query_one("SELECT pack_gz FROM rr_card_packs WHERE agent_key = ? AND pack_key = ?", (agent_key, key))
    if row is None:
        raise PackMissing(f"얼린 카드 묶음이 없다 — {agent_key} · {key}")
    view = view_of(json.loads(gzip.decompress(row["pack_gz"]).decode("utf-8")))
    with _LRU_LOCK:
        _LRU[cache] = view
        _LRU.move_to_end(cache)
        while len(_LRU) > LRU_SIZE:
            _LRU.popitem(last=False)
    return view


def load_for(store: Any, target_key: str, agent_key: str) -> FrozenPack | None:
    """그 타깃·전문가의 검토 머리가 가리키는 묶음(머리의 pack_hash 칸은 pack_key 다). 아직 얼리지 않았으면 None, 가리키는데 행이
    없으면 PackMissing."""
    row = store.query_one("SELECT pack_hash FROM rr_expert_reports WHERE target_key = ? AND agent_key = ?",
                          (target_key, agent_key))
    if row is None or not row["pack_hash"]:
        return None
    return load_pack(store, agent_key, str(row["pack_hash"]))


def cards_for(pack: FrozenPack, aliases: Sequence[str]) -> list[dict]:
    """요청에 실을 카드 항목 — 팩의 항목 그대로(키를 빼거나 고치지 않는다), 받은 별칭 순서대로, 복사본이다.

    `rev` 도 순서를 바꾸지 않는다 — 엔진이 `variant='rev'` 를 받으면 스스로 카드 순서를 뒤집는다(계약 예제
    `req_verdict_rev.json` 의 카드 순서는 `fwd` 와 같다). 앱이 또 뒤집으면 두 번 뒤집혀 `fwd` 와 같은 순서가 된다.
    모르는 별칭은 KeyError 다(계획에 없는 카드를 싣지 않는다).
    """
    out: list[dict] = []
    for alias in aliases:
        if alias not in pack.cards:
            raise KeyError(f"얼린 묶음에 없는 별칭 — {alias} ({pack.agent_key} · {pack.pack_key})")
        out.append(copy.deepcopy(dict(pack.cards[alias])))
    return out


def clear_cache() -> None:
    """시험용 — 프로세스 LRU 를 비운다."""
    with _LRU_LOCK:
        _LRU.clear()
