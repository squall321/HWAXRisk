# 가짜 카드 대조 엔진 한 벌(시험 전용, D-15) — 포털 중계 /agent/card-review/{limits,pack,plan,run} 과 /health 에 엔진과 같은 모양으로 답하는 MockTransport
"""운영 코드에는 가짜로 바꾸는 손잡이가 없다 — 시험이 `PortalReviewEngine(store, settings, transport=fake.transport)` 로 꽂는다.

모양은 에이전트 서버 `card_review.py` 가 실제로 내는 것이다(계약 예제 `result_*.json` 과 키 집합이 같다 — 시험이 본다).
- 카드 별칭은 받은 팩 항목의 것(K01…), 줄 별칭은 받은 단위의 변경 → 문맥 → 근거 순으로 L01…(엔진 build_ctx), 목록 단위는 U01….
- 인용(`cq`·`q`)은 받은 카드의 절 글에서 실제로 잘라 낸 부분 문자열이다(앞 40자 — 엔진 예제의 신탁 LLM 과 같은 자르기).
- 받은 요청은 엔진 요청 모델처럼 선언 밖 칸을 422 `unknown_fields` 로 거절한다(칸 집합은 C7 시험이 엔진 모델과 견준다).

결함 스위치(속성 — 시험이 도중에 바꿔도 된다):
  skip_cards       판정하지 않고 빼먹을 카드 별칭(엔진이 `missing` 에 싣는다)
  unknown_alias    실은 적 없는 별칭(K99)의 v 행을 하나 더 낸다(거짓 엔진 — 앱이 버려야 한다)
  invented_quote   이 별칭들의 인용을 지어낸다(엔진 `checks.quote` 는 정직하게 not_found)
  lying_quote      이 별칭들의 인용을 지어내고 `checks.quote` 를 ok 로 속인다(앱 재대조가 갈라야 한다)
  truncated        출력 상한에 걸렸다 — 마지막 판정 행이 빠지고 quality.truncated·finish_reason=length
  busy_n           앞 run N 번은 error{review_busy, retry_after_s} → done(관문 즉답)
  error_n·error    앞 run N 번은 error 프레임(기본 llm_unreachable, infra true)
  cut_n            앞 run N 번은 status 한 장 뒤 연결이 끊긴다(done 없음)
  delay_s          result 앞에서 이만큼 잔다(실제 시간)
  limits_delay_s   limits 응답 앞에서 이만큼 잔다(실제 시간 — 포털 → 에이전트 서버 왕복이 루프의 탐침 한도를 넘는 박스, R3A-3)
  limits_error     (상태, 본문) — limits 가 이 오류로 답한다(포털이 중계한 agent_unreachable 따위 — 창 조회 실패, R3A-10)
  credential_expired  포털이 PAT 를 401 로 거절한다(모든 경로)
  ctx_source       limits 의 창 출처(server·env·fallback)
  ctx_unknown      창 조회 실패 중 — limits 는 ctx_retrying, plan·run 은 503 ctx_unknown
  oversize_units   plan 이 oversize.units 에 싣는 단위
  pair_over_units  plan 이 모든 verdict 묶음과 짝지어 pair_over 에 싣는 단위
  verdicts         record_id → (applies, judgement). 없으면 ('yes', 'OK')
  rev_verdicts     rev 변형에서만 쓰는 record_id → (applies, judgement) — fwd 와 rev 가 갈리는 카드(S8)
  offcard_findings offcard 의 f 줄 수(상한 findings_max 이면 more=yes)
  busy_over        도는 run 이 이 수 이상이면 새 run 에 review_busy(관문 즉답 — S8 의 P-02(5))
  pack_errors      agent_key → (상태, 본문) 하나(늘) 또는 목록(차례로 쓰고 다 쓰면 정상 팩) — 계약 예제 pack_errors.json 의 응답
  pack_sequence    agent_key → 팩 목록(차례로 내고 마지막을 되풀이 — 0장 뒤 30장, P-08)
  long_quote       이 별칭들의 인용을 카드에 없는 긴 글(LONG_QUOTE, 260자)로 낸다(엔진 checks.quote 는 정직하게 not_found)
  cond_text        단독 재질의 c 줄의 조건 글(기본 COND — 긴 글로 바꾸면 반출의 조건 글 200자를 본다, S9)
  offcard_src·offcard_quote  카드 밖 f 줄이 근거로 댄 배경 카드 별칭과 그 인용(기본 exp · 빈 인용 — S9 의 카드 근거 카드 밖 줄)
  handoff_to       이 영역으로 넘기는 h 줄을 훑기(첫 단위)와 카드 밖 호출에 하나씩 더한다(S10 의 넘김 절)
  seen·need        카드 밖 m 줄의 따져 본 메커니즘 · need 줄의 글(S10 의 메커니즘·필요 정보 절)
  hold_runs        n(1부터 센 run 차례) → threading.Event — 그 run 은 result 앞에서 그 사건을 기다린다(호출 중 재기동 시험)
  solo_verdicts    solo 변형에서만 쓰는 record_id → (applies, judgement) — 단독 재질의가 앞 판정을 뒤집는 카드(S11)
  sweep_rel        unit_id → 훑기 rel(yes·maybe·no) — 그 단위의 u 줄 rel 을 바꾼다(훑기 '무관' 비율, S11)
  error_cells      (agent_key, unit_id) → error 프레임 — 그 셀의 run 은 늘 그 오류다(내용 탓이면 셀이 failed 로 간다, S11)
  truncate         (kind, variant, unit_id) → 'length' | 'repaired' | 'unknown' — 처음 맞는 run 한 번만: length 는 판정이면
                   truncated 처럼 마지막 판정 행을 빼고(행이 둘 이상인 호출에 건다 — 엔진은 남는 행이 0 이면 결과 대신
                   truncated_empty 를 낸다), 카드 밖이면 꼬리(more 줄)를 잃은 채 끝난 답이다(missing ['more'] · maybe_more null ·
                   finish_reason length). repaired 는 첫 시도가 잘렸지만 보충이 끝까지 낸 답이다 — 행은 다 있고 quality.truncated·
                   tail_broken 참, attempts 2·repaired 참, 마지막 finish_reason stop(엔진 _truncated 는 '어느 시도든 length' 다 —
                   계약 예제 result_verdict_truncated 의 모양, R3A-4). unknown 은 quality.truncated·finish_reason 을 null 로 낸다
                   (절단 모름 — X1-22, S11)
  queued_ms        정수면 meta.queued_ms 로 싣는다(자리 대기 — 엔진 예제에는 없는 칸이라 기본은 싣지 않는다, S11)
  no_quote         이 별칭들의 판정 행에 인용을 싣지 않는다(cq 빈 글 · checks.quote empty — 인용 통과율의 분모, X1-06, S11)
  no_refs          이 별칭들의 판정 행에 변경 줄을 싣지 않는다(l·refs 빈 목록 · checks.refs missing — 참조 통과율의 분모, S11)
기록 — requests(받은 요청 전부), runs(받은 run 수), max_active(동시에 돈 run 의 최댓값).
S8(검토 루프)과 WP5b C9 가 이 파일을 넓힌다. 시험이 쓰는 여러 전문가의 팩은 `derive_pack` 이 엔진 계약 예제(pack_ok·pack_empty)에서
전문가 이름·카드 고르기만 바꿔 짓는다(카드 글·text_sha 는 엔진이 낸 그대로다).
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from app import review_verify

CONTRACT = Path(__file__).resolve().parents[1] / "fixtures" / "card_review" / "contract"

# 엔진 요청 모델(card_review.RunRequest·PlanRequest·PackRequest 와 안쪽 항목)의 칸 — 선언 밖 칸은 422 unknown_fields.
IDENT_FIELDS = frozenset({"groups", "user_email", "user_pat", "entitlements"})
RUN_SHAPE: dict[str, frozenset[str]] = {
    "": frozenset({"kind", "variant", "target_key", "expert", "cards", "digest", "unit", "manifest", "extra", "expect"})
    | IDENT_FIELDS,
    "expert": frozenset({"key", "name", "domain", "role"}),
    "digest": frozenset({"alias", "type", "title", "record_id", "card_id"}),
    "unit": frozenset({"unit_id", "kind", "title", "summary", "notes", "lines", "context", "evidence", "missing",
                       "unit_hash", "summary_sha", "evidence_sha", "evidence_status", "input_gaps"}),
    "unit.lines": frozenset({"ref", "text", "owner_unit"}),
    "unit.context": frozenset({"ref", "text", "owner_unit"}),
    "unit.evidence": frozenset({"ref", "text", "owner_unit"}),
    "unit.missing": frozenset({"kind", "note"}),
    "manifest": frozenset({"unit_id", "kind", "title", "text"}),
    "extra": frozenset({"domains", "mechanisms", "known"}),
    "extra.domains": frozenset({"key", "label"}),
    "extra.mechanisms": frozenset({"code", "label"}),
    "extra.known": frozenset({"alias", "judgement", "why"}),
    "expect": frozenset({"prompt_rev", "limits_rev"}),
}
PLAN_SHAPE: dict[str, frozenset[str]] = {
    "": frozenset({"cards", "units", "expect"}) | IDENT_FIELDS,
    "cards": frozenset({"alias", "record_id", "checkable", "chars"}),
    "units": frozenset({"unit_id", "manifest_chars", "body_chars"}),
    "expect": frozenset({"prompt_rev", "limits_rev"}),
}
PACK_SHAPE: dict[str, frozenset[str]] = {"": frozenset({"agent_key"}) | IDENT_FIELDS}

INVENTED_QUOTE = "카드 어디에도 없는 지어낸 인용 문장으로 판정을 꾸몄다"
LONG_QUOTE = ("카드 본문을 길게 옮겨 적었다고 주장하는 인용 — " * 12)[:260]
WHY = "카드의 조건과 변경 줄을 맞대어 보니 판정이 이렇다"
COND = "카드가 요구하는 적용 조건"
NEED = "변경 줄에 그 조건의 값이 없어 판정할 수 없다"


def load(name: str) -> Any:
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def alias_width(n: int) -> int:
    """엔진 alias_width — 99 까지 두 자리, 그 위는 자릿수대로."""
    return max(2, len(str(n)))


def _sha8(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:8]


def derive_pack(base: Mapping[str, Any], agent_key: str, *, name: str | None = None, domain: str | None = None,
                keep: str = "all", copies: int | None = None) -> dict:
    """엔진 계약 예제 팩에서 다른 전문가의 팩을 짓는다 — 카드 글·절·text_sha 는 엔진이 낸 그대로다.

    `keep` — all(그대로) · background(점검 카드를 빼고 배경 카드만 — 카드는 있는데 카드 대조 묶음이 0개) · none(0장).
    `copies` — 카드를 차례로 되풀이해 이만큼 싣는다(별칭 K01… 과 record_id·card_id 꼬리를 새로 단다 — 30장 팩). 개수 칸
    (cards_total·listed_total·checkable_n·chars_total)은 실린 카드로 다시 센다(엔진 build_pack 의 정의)."""
    pack = copy.deepcopy(dict(base))
    cards = list(pack.get("cards") or ())
    if keep == "background":
        cards = [c for c in cards if not c.get("checkable")]
    elif keep == "none":
        cards = []
        pack["unrenderable"] = []
    if copies is not None and cards:
        source = list(cards)
        width = alias_width(copies)
        cards = []
        for i in range(copies):
            card = copy.deepcopy(source[i % len(source)])
            card.update({"alias": f"K{i + 1:0{width}d}", "record_id": f"{card['record_id']}-{i + 1:03d}",
                         "card_id": f"{card['card_id']}-{i + 1:03d}"})
            cards.append(card)
    elif keep == "background":
        width = alias_width(len(cards))
        cards = [dict(c, alias=f"K{i:0{width}d}") for i, c in enumerate(cards, 1)]
    pack.update({"agent_key": agent_key, "name": name or pack.get("name"), "domain": domain or pack.get("domain"),
                 "cards": cards, "cards_total": len(cards), "listed_total": len(cards) + len(pack.get("unrenderable") or ()),
                 "checkable_n": sum(1 for c in cards if c.get("checkable")),
                 "chars_total": sum(int(c.get("chars") or 0) for c in cards)})
    return pack


def shape_problems(body: Any, shape: Mapping[str, frozenset[str]]) -> list[str]:
    """선언 밖 칸의 경로(엔진 `unknown_fields` 의 fields 와 같은 표기 — extra.domains.0.code)."""
    out: list[str] = []

    def walk(obj: Any, key: str, path: str) -> None:
        if not isinstance(obj, Mapping):
            return
        allowed = shape.get(key)
        for name, value in obj.items():
            here = f"{path}.{name}" if path else name
            if allowed is not None and name not in allowed:
                out.append(here)
                continue
            child = f"{key}.{name}" if key else name
            if isinstance(value, list):
                for i, item in enumerate(value):
                    walk(item, child, f"{here}.{i}")
            elif isinstance(value, Mapping):
                walk(value, child, here)

    walk(body, "", "")
    return out


def _sse(event: str, data: Mapping[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _offcard_quote(cards: Mapping[str, Mapping[str, Any]], src: str, quote: str) -> str:
    """카드 밖 줄이 배경 카드를 댈 때 엔진의 인용 검사 — 그 카드 글에 인용이 있으면 ok, 없으면 not_found(정직한 엔진)."""
    card = cards.get(src)
    if card is None:
        return "not_found"
    text = "\n".join(str(s.get("text") or "") for s in card.get("sections") or ())
    return "ok" if review_verify.quote_status(quote, text) == "ok" else "not_found"


def quote_of(card: Mapping[str, Any]) -> tuple[str, str]:
    """카드에서 실제로 잘라 낸 인용과 그 절 번호 — 엔진 하한(15자·실질 10자)을 넘는 첫 절의 앞 40자."""
    for section in card.get("sections") or ():
        text = str(section.get("text") or "")[:40]
        if review_verify.quote_status(text, str(section.get("text") or "")) == "ok":
            return text, str(section.get("sid") or "")
    return "", ""


class FakeReviewEngine:
    """가짜 엔진 + 포털 중계. `transport` 를 PortalReviewEngine 에 꽂는다. 받은 요청은 `requests` 에 남는다."""

    def __init__(self, packs: Mapping[str, Mapping[str, Any]] | None = None, *,
                 limits: Mapping[str, Any] | None = None) -> None:
        self.packs = {key: copy.deepcopy(dict(pack)) for key, pack in (packs or {}).items()}
        self.base_limits = copy.deepcopy(dict(limits or load("limits_1m.json")))
        self.limits_rev = str(self.base_limits["limits_rev"])
        self.gate_limit = int(self.base_limits.get("gate", {}).get("limit") or 4)
        # 결함 스위치
        self.skip_cards: set[str] = set()
        self.unknown_alias = False
        self.invented_quote: set[str] = set()
        self.lying_quote: set[str] = set()
        self.truncated = False
        self.busy_n = 0
        self.retry_after_s = 30
        self.error_n = 0
        self.error: dict[str, Any] = {"code": "llm_unreachable", "message": "LLM 서버에 연결하지 못했다(가짜)",
                                      "infra": True, "retryable": True}
        self.cut_n = 0
        self.delay_s = 0.0
        self.limits_delay_s = 0.0
        self.limits_error: tuple[int, dict[str, Any]] | None = None
        self.credential_expired = False
        self.ctx_source = str(self.base_limits.get("ctx_source") or "server")
        self.ctx_unknown = False
        self.oversize_units: set[str] = set()
        self.pair_over_units: set[str] = set()
        self.verdicts: dict[str, tuple[str, str]] = {}
        self.rev_verdicts: dict[str, tuple[str, str]] = {}
        self.offcard_findings = 1
        self.busy_over: int | None = None
        self.pack_errors: dict[str, Any] = {}
        self.pack_sequence: dict[str, list[dict]] = {}
        self.long_quote: set[str] = set()
        self.cond_text = COND
        self.offcard_src = "exp"
        self.offcard_quote = ""
        self.handoff_to: str | None = None
        self.seen: list[str] = []
        self.need: str | None = None
        self.hold_runs: dict[int, threading.Event] = {}
        self.solo_verdicts: dict[str, tuple[str, str]] = {}
        self.sweep_rel: dict[str, str] = {}
        self.error_cells: dict[tuple[str, str], dict[str, Any]] = {}
        self.truncate: dict[tuple[str, str | None, str | None], str] = {}
        self.queued_ms: int | None = None
        self.no_quote: set[str] = set()
        self.no_refs: set[str] = set()
        # 기록
        self.requests: list[dict[str, Any]] = []
        self.runs = 0
        self.max_active = 0
        self.active = 0
        self._reserved = 0          # 관문을 지나 result 를 흘리기 직전인 run(busy_over 의 자리 셈 — 동시에 온 요청이 둘 다 지나지 않게)
        self._lock = threading.Lock()
        self.transport = httpx.MockTransport(self.handle)

    # -- 기록·계수 --------------------------------------------------------------------
    def _take(self, name: str) -> bool:
        """스위치 계수 하나를 쓴다 — 남았으면 하나 줄이고 참."""
        with self._lock:
            left = getattr(self, name)
            if left > 0:
                setattr(self, name, left - 1)
                return True
            return False

    def calls(self, route: str) -> list[dict[str, Any]]:
        return [r for r in self.requests if r["route"] == route]

    # -- 라우팅 -------------------------------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        route = path.rsplit("/", 1)[-1] if path.startswith("/agent/card-review/") else path
        with self._lock:
            self.requests.append({"method": request.method, "path": path, "route": route, "body": body,
                                  "authorization": request.headers.get("authorization")})
        if path == "/health":
            return httpx.Response(200, json=self.health())
        if not path.startswith("/agent/card-review/"):
            return httpx.Response(404, json={"detail": "Not Found"})
        if self.credential_expired or not str(request.headers.get("authorization") or "").startswith("Bearer "):
            return httpx.Response(401, json={"detail": "PAT 가 만료됐거나 폐기됐습니다"})
        if route == "limits" and request.method == "GET":
            if self.limits_delay_s > 0:
                time.sleep(float(self.limits_delay_s))
            if self.limits_error is not None:
                return httpx.Response(int(self.limits_error[0]), json=copy.deepcopy(self.limits_error[1]))
            return httpx.Response(200, json=self.limits())
        if request.method != "POST" or route not in ("pack", "plan", "run"):
            return httpx.Response(404, json={"detail": "Not Found"})
        if not isinstance(body, dict):
            return self._reject(422, "bad_request", "요청 본문이 JSON 객체가 아니다")
        shape = {"pack": PACK_SHAPE, "plan": PLAN_SHAPE, "run": RUN_SHAPE}[route]
        extra = shape_problems(body, shape)
        if extra:
            return self._reject(422, "unknown_fields", f"선언하지 않은 칸 {len(extra)}개({', '.join(extra[:20])})",
                                fields=extra)
        if route == "pack":
            return self._pack(body)
        if self.ctx_unknown:
            return self._reject(503, "ctx_unknown", "LLM 서버에 창 크기를 묻지 못해 다시 묻는 중이다(가짜)",
                                retry_after_s=60, infra=True, retryable=True)
        want = (body.get("expect") or {}).get("limits_rev")
        if want not in (None, self.limits_rev):
            return self._reject(409, "rev_mismatch", f"요청이 기대한 limits_rev({want})가 이 서버의 판({self.limits_rev})과"
                                " 다르다", limits_rev=self.limits_rev, expect=body.get("expect"))
        if route == "run":
            # 엔진 prepare 처럼 run 은 종류별 prompt_rev 도 견준다(limits_rev 의 원천에 PROMPT_REV 는 없다 — R3A-6).
            want_prompt = (body.get("expect") or {}).get("prompt_rev")
            have_prompt = (self.base_limits.get("prompt_rev") or {}).get(body.get("kind"))
            if want_prompt not in (None, have_prompt):
                return self._reject(409, "rev_mismatch", f"요청이 기대한 판(prompt_rev={want_prompt})이 이 서버의 판"
                                    f"(prompt_rev={have_prompt})과 다르다", prompt_rev=have_prompt,
                                    limits_rev=self.limits_rev, expect=body.get("expect"))
        if route == "plan":
            return httpx.Response(200, json=self.plan(body))
        return self._run(body)

    @staticmethod
    def _reject(status: int, code: str, message: str, **extra: Any) -> httpx.Response:
        return httpx.Response(status, json={"code": code, "message": message, **extra})

    # -- 단발 ------------------------------------------------------------------------------
    def limits(self) -> dict:
        out = copy.deepcopy(self.base_limits)
        out.update({"ctx_source": "fallback" if self.ctx_unknown else self.ctx_source, "ctx_retrying": self.ctx_unknown,
                    "limits_rev": self.limits_rev,
                    "gate": {"limit": self.gate_limit, "limit_reason": "normal", "active": self.active}})
        return out

    def health(self) -> dict:
        return {"model": self.base_limits.get("model"), "provider": "openai", "vllm": "http://llm.fake:8000/v1",
                "review_active": self.active, "capabilities": ["card_review"],
                "card_review": {"rev": self.base_limits.get("api_rev"), "kinds": list(self.base_limits.get("kinds") or ()),
                                "limit": self.gate_limit, "limit_reason": "normal", "active": self.active,
                                "retry_after_s": self.retry_after_s, "timeout_s": 1800, "tries": 2, "attempts_max": 3,
                                "request_worst_s": 10824, "prompt_rev": dict(self.base_limits.get("prompt_rev") or {}),
                                "totals": {}, "last_error": None}}

    def _pack(self, body: Mapping[str, Any]) -> httpx.Response:
        key = str(body.get("agent_key") or "")
        with self._lock:
            errors = self.pack_errors.get(key)
            if isinstance(errors, list):
                error = errors.pop(0) if errors else None
            else:
                error = errors
            sequence = self.pack_sequence.get(key)
            pack = (sequence.pop(0) if len(sequence) > 1 else sequence[0]) if sequence else self.packs.get(key)
        if error is not None:
            status, payload = error
            return httpx.Response(int(status), json=copy.deepcopy(payload))
        if pack is None:
            return self._reject(404, "agent_not_found", f"전문가 '{key}' 가 없다", agent_key=key)
        return httpx.Response(200, json=copy.deepcopy(pack))

    def plan(self, body: Mapping[str, Any]) -> dict:
        """엔진 plan 의 모양 — 점검 카드를 팩 순서로 K 장씩, 훑기 묶음은 카드 전부 한 묶음, 목록 쪽은 쪽당 상한까지."""
        k = int(self.base_limits["verdict"]["k"])
        per_page = int(self.base_limits["sweep"]["units_per_page_max"])
        cards = [c for c in body.get("cards") or () if isinstance(c, Mapping)]
        units = [u for u in body.get("units") or () if isinstance(u, Mapping)]

        def deck(kind: str, items: Sequence[Mapping[str, Any]]) -> dict:
            return {"deck_id": f"{kind[0]}-{_sha8(kind, [[c['alias'], c.get('record_id', '')] for c in items])}",
                    "aliases": [c["alias"] for c in items], "chars": sum(int(c.get("chars") or 0) for c in items),
                    "soft_over": False}

        checkable = [c for c in cards if c.get("checkable")]
        verdict_decks = [deck("verdict", checkable[i:i + k]) for i in range(0, len(checkable), k)]
        sweep_decks = [deck("sweep", cards)] if cards else []
        fits = [u["unit_id"] for u in units if u["unit_id"] not in self.oversize_units]
        pages = [fits[i:i + per_page] for i in range(0, len(fits), per_page)]
        p_hard = int(self.base_limits["p_hard"])
        pair_over = [{"deck_id": d["deck_id"], "unit_id": u["unit_id"], "need": p_hard + 1, "have": p_hard}
                     for u in units if u["unit_id"] in self.pair_over_units and u["unit_id"] not in self.oversize_units
                     for d in verdict_decks]
        return {"limits_rev": self.limits_rev, "verdict_decks": verdict_decks, "sweep_decks": sweep_decks,
                "manifest_pages": pages,
                "oversize": {"cards": [], "kinds": {}, "units": [u["unit_id"] for u in units
                                                                  if u["unit_id"] in self.oversize_units],
                             "manifest": []},
                "soft_over": {"units": [], "manifest": []}, "pair_over": pair_over}

    # -- run(SSE) -----------------------------------------------------------------------
    def _busy(self) -> httpx.Response:
        return self._stream(iter([_sse("error", {"code": "review_busy", "message": "카드 대조 자리가 없다(가짜)", "infra": True,
                                                 "retryable": True,
                                                 "knob": "CARD_REVIEW_CONCURRENCY · CARD_REVIEW_CONCURRENCY_WITH_DELIB",
                                                 "reason": "normal", "retry_after_s": self.retry_after_s,
                                                 "limit": self.gate_limit, "active": self.active}),
                                  _sse("done", {})]))

    def _run(self, body: Mapping[str, Any]) -> httpx.Response:
        with self._lock:
            self.runs += 1
            nth = self.runs
        if self._take("busy_n"):
            return self._busy()
        cell = (str((body.get("expert") or {}).get("key") or ""), str((body.get("unit") or {}).get("unit_id") or ""))
        if cell in self.error_cells:
            return self._stream(iter([_sse("status", {"step": "attempt", "n": 1}),
                                      _sse("error", {**self.error_cells[cell], "attempt": 1}), _sse("done", {})]))
        if self._take("error_n"):
            return self._stream(iter([_sse("status", {"step": "attempt", "n": 1}),
                                      _sse("error", {**self.error, "attempt": 1}), _sse("done", {})]))
        if self._take("cut_n"):
            def cut() -> Iterator[bytes]:
                yield _sse("status", {"step": "attempt", "n": 1})
                raise httpx.RemoteProtocolError("peer closed connection without sending complete message body")
            return self._stream(cut())
        with self._lock:
            # 자리 셈과 자리 잡기를 한 잠금 안에서 — 동시에 온 둘이 같이 관문을 지나지 않게(result 를 흘리기 시작하면 active 로 옮긴다).
            if self.busy_over is not None and self.active + self._reserved >= self.busy_over:
                return self._busy()
            self._reserved += 1
        result = self.result(body)
        delay = float(self.delay_s)
        gate = self.hold_runs.get(nth)

        def frames() -> Iterator[bytes]:
            # 도는 수(active)는 result 를 넘긴 뒤 done 앞에서 내린다 — 클라이언트는 done 에서 읽기를 멈춰 생성기가 끝까지
            # 돌지 않는다. 도중에 닫힌 스트림은 생성기가 거두어질 때 finally 가 내린다.
            with self._lock:
                self._reserved -= 1
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                yield _sse("status", {"step": "attempt", "n": 1})
                if delay > 0:
                    time.sleep(delay)
                if gate is not None:
                    gate.wait(30)
                yield _sse("result", result)
            finally:
                with self._lock:
                    self.active -= 1
            yield _sse("done", {})
        return self._stream(frames())

    @staticmethod
    def _stream(content: Iterator[bytes]) -> httpx.Response:
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    # -- result 프레임 -------------------------------------------------------------------
    def result(self, body: Mapping[str, Any]) -> dict:
        """요청 하나 → 엔진 result 프레임 모양(M2.md 4.3)."""
        kind, variant = body.get("kind"), body.get("variant")
        with self._lock:
            cut = self.truncate.pop((kind, variant, (body.get("unit") or {}).get("unit_id")), None)
        cards = {c["alias"]: c for c in body.get("cards") or ()}
        order = list(cards)
        digest = {d["alias"]: d for d in body.get("digest") or () if d["alias"] not in cards}
        unit = body.get("unit") or {}
        parts = [(part, x) for part, key in (("line", "lines"), ("context", "context"), ("evidence", "evidence"))
                 for x in unit.get(key) or ()]
        lines = {f"L{i:0{alias_width(len(parts))}d}": {"ref": x["ref"], "part": part} for i, (part, x) in enumerate(parts, 1)}
        manifest = list(body.get("manifest") or ())
        units = {f"U{i:0{alias_width(len(manifest))}d}": m["unit_id"] for i, m in enumerate(manifest, 1)}
        own = [a for a, x in lines.items() if x["part"] == "line"] or list(lines)[:1]
        quality = {"expected": 0, "ok": 0, "flagged": 0, "missing": 0, "bad_lines": 0, "truncated": False,
                   "tail_broken": False, "attempts": 1, "repaired": False, "stamp": False, "dropped_over_cap": 0,
                   "maybe_more": None, "dropped_alias": 0, "dup": 0}
        extras: dict[str, Any] = {"inj": []}
        if kind == "verdict":
            judge = order[::-1] if variant == "rev" else order
            main = [self._verdict_row(a, cards[a], own, lines, variant=variant) for a in judge if a not in self.skip_cards]
            if (self.truncated or cut == "length") and main:
                main = main[:-1]
                quality.update(truncated=True, tail_broken=True)
            missing = [a for a in judge if a not in {r["k"] for r in main}]
            rows = list(main)
            if variant == "solo":
                rows += [{"t": "c", "l": r["l"], "cond": self.cond_text, "met": "yes",
                          "note": "변경 줄에서 조건을 확인했다", "refs": r["refs"], "k": r["k"], "record_id": r["record_id"],
                          "from_attempt": 1, "checks": {"refs": "ok", "coerced": []}} for r in main]
            if self.unknown_alias:
                ghost = {"alias": "K99", "record_id": "DOC-FAKE-0000000099", "card_id": "FAKE-99",
                         "sections": [{"sid": "1", "title": "", "text": INVENTED_QUOTE}]}
                rows.append(self._verdict_row("K99", ghost, own, lines))
            flagged = sum(1 for r in main if r["checks"]["quote"] != "ok")
            quality.update(expected=len(judge), ok=len(main) - flagged, flagged=flagged, missing=len(missing))
        elif kind == "sweep":
            rows = [{"t": "u", "k": list(order), "u": u, "rel": self.sweep_rel.get(uid) or ("maybe" if order else "no"),
                     "why": "카드의 적용 조건이 이 단위에 걸릴 수 있다", "unit_id": uid,
                     "record_ids": [cards[a]["record_id"] for a in order], "from_attempt": 1,
                     "checks": {"why": "ok", "coerced": []}} for u, uid in units.items()]
            if self.handoff_to and units:
                first = next(iter(units))
                rows.append({"t": "h", "u": first, "to": self.handoff_to, "why": "훑기가 다른 영역의 몫으로 본 단위",
                             "unit_id": units[first], "from_attempt": 1, "checks": {"coerced": []}})
            missing = []
            extras["unmatched_cards"] = []
            quality.update(expected=len(units), ok=len(rows))
        else:
            cap = int(self.base_limits["offcard"]["findings_max"])
            n = min(int(self.offcard_findings), cap)
            rows = [{"t": "f", "l": own[:1], "dir": "risk", "title": f"카드 밖 위험 {i}", "mech": "free",
                     "mech_free": "계면 박리", "path": "변경 줄의 계면", "src": self.offcard_src, "q": self.offcard_quote,
                     "sev": "중대", "conf": "medium",
                     "check_kind": "test", "check": "고온 고습 시험으로 박리를 본다",
                     "refs": [lines[a]["ref"] for a in own[:1]], "basis": "경험칙", "from_attempt": 1,
                     "checks": {"refs": "ok" if own else "missing", "src": self.offcard_src,
                                "quote": "ok" if self.offcard_src == "exp" else _offcard_quote(cards, self.offcard_src,
                                                                                               self.offcard_quote),
                                "quote_sid": "", "coerced": []}} for i in range(1, n + 1)]
            more = "yes" if n >= cap else "no"
            rows += [{"t": "m", "seen": list(self.seen), "from_attempt": 1, "checks": {"coerced": []}},
                     {"t": "more", "more": more, "from_attempt": 1, "checks": {"coerced": []}}]
            if self.handoff_to:
                rows.append({"t": "h", "to": self.handoff_to, "why": "카드 밖 호출이 다른 영역의 몫으로 본 줄", "l": own[:1],
                             "from_attempt": 1, "checks": {"coerced": []}})
            if self.need:
                rows.append({"t": "need", "what": self.need, "from_attempt": 1, "checks": {"coerced": []}})
            missing = []
            quality.update(expected=3, ok=n, maybe_more=more == "yes")
        prompt_rev = self.base_limits["prompt_rev"][kind]
        meta = {"model": self.base_limits.get("model"), "ctx_tokens": self.base_limits["ctx_tokens"],
                "ctx_source": self.ctx_source, "prompt_rev": prompt_rev, "norm_rev": self.base_limits["norm_rev"],
                "limits_rev": self.limits_rev,
                "input_sha": hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
                "prompt_chars": len(json.dumps(body, ensure_ascii=False)),
                "usage": {"llm_calls": 1, "tokens_in": 1000, "tokens_out": 100,
                          "per_attempt": [{"n": 1, "tokens_in": 1000, "tokens_out": 100}]},
                "finish_reason": ("length" if (self.truncated or cut == "length") and kind == "verdict" else "stop"),
                "llm_ms": [0],
                "soft_over": False, "basis": "cards" if (order or digest) else "role_only", "bg_dropped": 0,
                "order_effective": not (kind == "verdict" and variant == "rev" and len(order) < 2),
                "aliases": {"cards": {a: cards[a]["record_id"] for a in order},
                            "lines": {a: x["ref"] for a, x in lines.items()}, "units": units}}
        if cut == "unknown":
            quality["truncated"] = None
            meta["finish_reason"] = None
        if cut == "repaired":
            quality.update(truncated=True, tail_broken=True, attempts=2, repaired=True)
            meta["usage"] = {"llm_calls": 2, "tokens_in": 2000, "tokens_out": 200,
                             "per_attempt": [{"n": 1, "tokens_in": 1000, "tokens_out": 100},
                                             {"n": 2, "tokens_in": 1000, "tokens_out": 100}]}
            meta["llm_ms"] = [0, 0]
        if cut == "length" and kind == "offcard":
            rows = [r for r in rows if r["t"] != "more"]
            missing = ["more"]
            quality.update(truncated=True, tail_broken=True, maybe_more=None)
            meta["finish_reason"] = "length"
        if self.queued_ms is not None:
            meta["queued_ms"] = int(self.queued_ms)
        return {"kind": kind, "variant": variant, "rows": rows, "missing": missing, "extras": extras,
                "quality": quality, "meta": meta}

    def _verdict_row(self, alias: str, card: Mapping[str, Any], own: Sequence[str],
                     lines: Mapping[str, Mapping[str, Any]], *, variant: str | None = None) -> dict:
        record_id = str(card.get("record_id"))
        applies, judgement = self.verdicts.get(record_id, ("yes", "OK"))
        if variant == "rev" and record_id in self.rev_verdicts:
            applies, judgement = self.rev_verdicts[record_id]
        if variant == "solo" and record_id in self.solo_verdicts:
            applies, judgement = self.solo_verdicts[record_id]
        quote, sid = quote_of(card)
        status = "ok" if quote else "empty"
        if alias in self.invented_quote or alias in self.lying_quote:
            quote, sid = INVENTED_QUOTE, ""
            status = "not_found"
        if alias in self.long_quote:
            quote, sid, status = LONG_QUOTE, "", "not_found"
        if alias in self.lying_quote:
            status, sid = "ok", "1"
        if alias in self.no_quote:
            quote, sid, status = "", "", "empty"
        flagged = judgement in ("WARNING", "FAIL")
        cited = list(own[:1]) if applies != "no" and alias not in self.no_refs else []
        return {"t": "v", "l": cited, "k": alias, "applies": applies, "judgement": judgement, "cq": quote, "why": WHY,
                "need": NEED if applies == "unknown" or judgement == "undetermined" else "",
                "sev": "중대" if flagged else "", "path": "변경 줄 → 카드 조건" if flagged else "",
                "check_kind": "test" if flagged else "", "check": "시험으로 확인한다" if flagged else "",
                "refs": [lines[a]["ref"] for a in cited], "record_id": str(card.get("record_id") or ""),
                "card_id": str(card.get("card_id") or ""), "from_attempt": 1,
                "checks": {"quote": status, "quote_sid": sid, "refs": "ok" if cited or applies != "yes" else "missing",
                           "nums_unsourced": [], "need": "ok", "coerced": []}}
