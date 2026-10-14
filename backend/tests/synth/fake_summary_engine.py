# 가짜 요약 엔진(재설계 M3 S3-9 시험) — 엔진 summary 종류의 limits·run 을 계약 예제(result_summary_*.json)와 같은 모양으로 낸다
"""엔진(HWAXAgentServer card_review.py `_summary_ctx`)이 하는 요청 검사를 그대로 한다 — expert 가 있거나 카드·단위·extra 를
실었거나 rows 가 비었거나 ref 가 겹치거나 must_cover 가 rows 밖이면 422 bad_request, must_cover 가 cover_hard_max 를 넘으면
cover_too_large. 행에 R001… 별칭을 매기고 결과 줄의 refs 를 되돌린다.

대본(`script`) — 범위 key(영역 코드 · '-') 또는 '*' → 하나:
  'ok' · 'missing'(첫 must_cover 를 risk 줄에서 빼고 missing 에 싣는다 — 다시 물어도 같다) · 'missing_once'(첫 호출만) ·
  'nums'(para 줄에 출처 없는 수) · 'outside'(입력 밖 참조를 싣는다) · 'clipped'(meta.clipped 를 싣는다) · 'over_budget' ·
  예외 인스턴스(그대로 올린다 — 인프라·내용 탓 시험)
`runnable` 이 거짓이면 limits 의 runnable.summary=false. `drain` 은 None 이거나 {'on', 'scope'}.
기록 — requests(받은 본문 전부).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.runner import EngineRejected

PROMPT_REV = "cr-summary-2"
LIMITS_REV = "fake-sum-1"


class FakeSummaryEngine:
    def __init__(self, script: Mapping[str, Any] | None = None, *, cover_max: int = 30, cover_hard_max: int = 60) -> None:
        self.script: dict[str, Any] = dict(script or {})
        self.requests: list[dict] = []
        self.runnable = True
        self.drain: dict | None = None
        self.cover_max = cover_max
        self.cover_hard_max = cover_hard_max
        self._seen: dict[str, int] = {}

    def health(self) -> dict:
        return {"model": "fake-sum", "provider": "fake"}

    def drain_state(self) -> dict:
        return dict(self.drain or {"on": False, "scope": None})

    def limits(self, *, email: str) -> dict:
        return {"kinds": ["sweep", "verdict", "offcard", "noinput", "summary"],
                "summary": {"p": 400_000, "line_max": 400, "narrative_max": 4000, "blocks_max": 40_000,
                            "cover_max": self.cover_max, "cover_hard_max": self.cover_hard_max},
                "runnable": {"sweep": True, "verdict": True, "offcard": True, "noinput": True, "summary": self.runnable},
                "prompt_rev": {"summary": PROMPT_REV}, "limits_rev_by_kind": {"summary": LIMITS_REV},
                "limits_rev": "fake-cells-1"}

    # ------------------------------------------------------------ run
    def run(self, body: Mapping[str, Any], *, email: str, on_progress: Any = None, should_stop: Any = None) -> dict:
        self.requests.append(dict(body))
        sm = self._check(body)
        key = str(sm["scope"]["key"])
        plan = self.script.get(key, self.script.get("*", "ok"))
        if isinstance(plan, BaseException):
            raise plan
        self._seen[key] = self._seen.get(key, 0) + 1
        if plan == "over_budget":
            raise EngineRejected("over_budget", "프롬프트가 이 박스의 창 한도를 넘는다(가짜) — 다시 쪼개지 않는다")
        rows = sm["rows"]
        alias = {f"R{i:03d}": r["ref"] for i, r in enumerate(rows, 1)}
        by_ref = {v: k for k, v in alias.items()}
        cover = [by_ref[c] for c in sm.get("must_cover") or ()]
        missing = plan == "missing" or (plan == "missing_once" and self._seen[key] == 1)
        dropped = cover[:1] if missing else []
        out_rows = [self._row("head", list(alias)[:2], "이 범위의 걸림은 계면과 낙하 응력에 몰린다", alias)]
        out_rows += [self._row("risk", [a], f"{a} 행의 걸림이 같은 계면에 겹친다", alias) for a in cover if a not in dropped]
        para = self._row("para", list(alias)[:1], "제기 수가 많은 행부터 닫는 확인을 잡는다", alias)
        if plan == "nums":
            para["checks"]["nums_unsourced"] = ["999"]
            para["text"] += " — 999건이 겹친다"
        if plan == "outside":
            para["refs"].append("reg:ffffffffffff")
        out_rows.append(para)
        meta = {"model": "fake-sum", "ctx_tokens": 1_048_576, "ctx_source": "server", "prompt_rev": PROMPT_REV,
                "norm_rev": "cr-n1", "limits_rev": LIMITS_REV, "input_sha": "f" * 64, "prompt_chars": 4000,
                "usage": {"llm_calls": 1, "tokens_in": 2000, "tokens_out": 300}, "finish_reason": "stop", "llm_ms": [0],
                "soft_over": False, "basis": "rows", "aliases": {"rows": alias}}
        if plan == "clipped":
            meta["clipped"] = {"blocks": {"had": 52_000, "kept": 40_000}}
        return {"kind": "summary", "variant": None, "rows": out_rows, "missing": dropped, "extras": {"inj": []},
                "quality": {"expected": len(cover) + 2, "ok": len(out_rows), "missing": len(dropped), "attempts": 1,
                            "repaired": False, "narrative_chars": len(para["text"])},
                "meta": meta}

    @staticmethod
    def _row(t: str, aliases: list[str], text: str, alias: Mapping[str, str]) -> dict:
        return {"t": t, "r": list(aliases), "text": text, "refs": [alias[a] for a in aliases], "from_attempt": 1,
                "checks": {"refs": "ok", "nums_unsourced": [], "coerced": []}}

    def _check(self, body: Mapping[str, Any]) -> dict:
        """엔진 `_summary_ctx` 와 같은 요청 검사."""
        if body.get("kind") != "summary" or body.get("expert") is not None:
            raise EngineRejected("bad_request", "summary 는 expert 가 없다(null)")
        for k in ("cards", "digest", "manifest"):
            if body.get(k):
                raise EngineRejected("bad_request", f"summary 에는 {k} 가 없다")
        if body.get("unit") not in (None, {}) or (body.get("extra") or {}):
            raise EngineRejected("bad_request", "summary 에는 unit·extra 가 없다")
        sm = body.get("summary")
        if not isinstance(sm, Mapping) or (sm.get("scope") or {}).get("kind") not in ("domain", "target"):
            raise EngineRejected("bad_request", "summary.scope 는 {kind: domain|target, key, label} 이다")
        rows = [r for r in sm.get("rows") or () if isinstance(r, Mapping)]
        if not rows:
            raise EngineRejected("bad_request", "summary.rows 가 비었다")
        refs = [str(r.get("ref") or "") for r in rows]
        if len(set(refs)) != len(refs) or not all(refs):
            raise EngineRejected("bad_request", "summary.rows 의 ref 가 비었거나 겹친다")
        if any(len(str(r.get("text") or "")) > 400 for r in rows):
            raise EngineRejected("bad_request", "행 한 줄이 line_max(400)를 넘는다")
        cover = [str(c) for c in sm.get("must_cover") or ()]
        if any(c not in refs for c in cover):
            raise EngineRejected("bad_request", "summary.must_cover 가 rows 밖이다")
        if len(set(cover)) > self.cover_hard_max:
            raise EngineRejected("cover_too_large", f"꼭 다룰 행 {len(set(cover))}건이 상한 {self.cover_hard_max}건을 넘는다")
        unknown = set(body) - {"kind", "variant", "target_key", "expert", "summary", "cards", "digest", "unit", "manifest",
                               "extra", "expect"}
        if unknown:
            raise EngineRejected("unknown_fields", f"선언 밖 칸 — {sorted(unknown)}")
        return dict(sm)
