#!/usr/bin/env python3
# 리스크 명단 전문가의 카드를 AIDataHub 에서 읽어 엔진 식으로 1M · 20만 창의 한 장 자리 초과 · 입력 결손 몫 초과 · 셀당 판정 호출을 재는 읽기 전용 측정
"""포털 docs/risk-200k W-D2 의 측정을 명단 전원으로 넓힌다(B32 — 포털 docs/leftovers-1017/triage-1031.md · risk-200k 체크리스트 7줄).

방법은 W-D2 와 같다 — AIDataHub `GET /api/agents`(게이트웨이 list_agents 가 그대로 내는 풀)로 명단을 받고, 전문가마다
`GET /api/agents/{agent}/records` 를 읽어 엔진(형제 리포 HWAXAgentServer)의 `card_review.normalize_card` · `assign_aliases`
(= `render_card` 길이)로 펴고, `limits()` · `plan()` · `card_room()` 의 식 그대로 창마다 센다.

- 한 장 자리 초과 카드 — `chars > card_room(lim)`(판정 · 훑기 자리 가운데 작은 것). 20만에서는 계획이 그 카드를 조각 묶음(chunked)으로
  낸다 — 조각 수 어림(`chunks` 합)을 함께 싣는다. `plan().oversize.cards` 는 조각이 생긴 뒤로 0 이어야 한다.
- 입력 결손 몫 초과 — 전문가의 렌더 글자 합이 `noinput.card_budget` 을 넘는가(넘는 카드는 제목으로만 실리거나 쪽으로 나뉜다).
- 셀당 판정 호출 — `plan().verdict_decks` 의 묶음 수(조각 묶음은 `chunks` 번). 훑기 호출은 목록 한 쪽 기준 `sweep_decks` 수다.
- 창 — 1M 은 1,048,576 토큰 · 출력 상한 없음(GLM 길, DELIB_MAX_TOKENS 미설정), 20만은 엔진 `external_llm` 기본(Claude 길 — 200,000 ·
  32,000)이다. W-D2 의 한 장 자리(1M 84.5만 · 81.7만, 20만 13.2만 · 12.6만)와 입력 결손 몫(1M 138,117 · 20만 24,648)이 이 값이다.
  손잡이(CARD_REVIEW_K · 몫)는 엔진 기본이다 — 박스의 env 를 읽지 않는다(같은 카드면 어느 박스에서 돌려도 같은 수).
- 보기 둘 — `records` 는 그 경로가 내는 기록 전부(W-D2 의 방법 그대로), `knowledge_cards` 는 그 가운데 `doc_type ==
  expert_knowledge_card` 만이다. 엔진의 팩(`card_review.build_pack`)은 list_records(doc_type=expert_knowledge_card)로 지식카드만
  싣는다 — 실제 심사가 보는 것은 뒤쪽이다. 두 보기가 갈리면 논문 · 특허 · 물성 카드가 앞쪽 수를 만든 것이다.

읽기만 한다 — GET 두 경로뿐이고 쓰는 호출 · 프록시가 없다. AIDataHub 가 키를 요구하면(AUTH_REQUIRED=true) 환경변수
`AIDH_API_KEY`(없으면 `HWAXRISK_AIDH_API_KEY`)를 X-API-Key 로 싣는다 — 인자로 받지 않고 찍지 않는다.

사용(리포 루트에서 — 엔진 모듈을 들이므로 엔진 venv 의 python 이 가장 확실하다. 리스크 앱 venv 도 된다).

    ../HWAXAgentServer/.venv/bin/python backend/scripts/card_window_census.py --out /tmp/census.json        # 명단 전원
    ../HWAXAgentServer/.venv/bin/python backend/scripts/card_window_census.py --wd2                         # W-D2 표본(시드 20261020)

- `--base` AIDataHub 주소(기본 env HWAXRISK_AIDH_BASE, 없으면 http://127.0.0.1:8001) · `--engine` 엔진 리포(기본 형제 ../HWAXAgentServer)
- `--agents a,b` 명단 대신 고른 전문가 · `--sample N --seed S --include a,b` 무작위 표본(정렬한 키에서 random.Random(S).sample)
- `--windows 1M=1048576:0,200k=200000:32000` 창 이름=창 토큰:출력 상한 · `--per-expert` 전문가마다의 행을 싣는다
- 종료 0 잼(못 읽은 전문가는 `failed` 에 적는다) · 2 잴 수 없음(AIDataHub 에 닿지 않음 · 키 거절 · 엔진을 못 들임)
- 무겁다 — 전문가마다 기록 전문을 받는다(dev 표본 32명이 6,775건 · 전문가 한 명 중앙값 480만 자). 한 명씩 차례로 돌고 끝난 전문가의
  글은 버린다. 서비스를 띄우거나 내리지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

OK, CANT_MEASURE = 0, 2
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENGINE = REPO_ROOT.parent / "HWAXAgentServer"
DEFAULT_BASE = "http://127.0.0.1:8001"
TIMEOUT_S = 300                       # 전문가 한 명의 기록 전문 — 수천 건이면 응답이 수십 MB 다
ONE_M = 1_048_576                     # GLM 1M 창(토큰) — W-D2 의 1M 한 장 자리가 이 값 · 출력 상한 없음에서 나온다
WD2 = {"sample": 30, "seed": 20261020, "include": ("xd-yield-ramp", "material-twin-analyst")}
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class CantMeasure(Exception):
    """잴 수 없다 — 까닭을 사람이 읽는 글로 싣는다."""


# ---------------------------------------------------------------- 읽기(GET 만)
def http_fetcher(base: str, api_key: str = "") -> Callable[[str], Any]:
    """AIDataHub 의 GET 하나 — JSON 을 돌려준다. 404 는 None(그 전문가가 사라졌다), 401 · 403 · 닿지 않음은 CantMeasure 다."""
    root = base.rstrip("/")

    def fetch(path: str) -> Any:
        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        req = urllib.request.Request(root + path, method="GET", headers=headers)
        try:
            with _OPENER.open(req, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (401, 403):
                raise CantMeasure(f"AIDataHub 가 HTTP {exc.code} 로 거절했다 — 키를 요구하는 박스면(AUTH_REQUIRED=true) "
                                  "AIDH_API_KEY 를 셸에 내보내고 다시 돌린다") from exc
            raise RuntimeError(f"HTTP {exc.code} — {path}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise CantMeasure(f"{root} 에 닿지 않는다({getattr(exc, 'reason', exc)}) — AIDataHub 가 떠 있는지, "
                              "--base(또는 HWAXRISK_AIDH_BASE)가 맞는지 본다") from exc

    return fetch


def load_engine(engine_dir: Path) -> tuple[Any, Any, dict]:
    """엔진의 card_review · external_llm 을 들이고 판 정보(커밋 · api_rev · norm_rev · 식 판)를 돌려준다."""
    if not (engine_dir / "card_review.py").is_file():
        raise CantMeasure(f"엔진 리포를 못 찾았다 — {engine_dir}/card_review.py 가 없다(--engine 으로 준다)")
    sys.path.insert(0, str(engine_dir))
    try:
        import card_review  # noqa: PLC0415 — 형제 리포의 모듈이라 경로를 넣은 뒤에 들인다.
        import external_llm  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001 — 엔진 의존성이 없는 python 이면 까닭과 함께 멈춘다
        raise CantMeasure(f"엔진 모듈을 들이지 못했다({type(exc).__name__}: {exc}) — 엔진 venv 의 python 으로 돌린다") from exc
    # 한 장 자리(card_room)와 조각 계획은 risk-200k W1(엔진 5aa33fc, 10-20) 뒤에 생겼다 — 그 전 판이면 셈의 뜻이 다르다.
    lacking = [n for n in ("card_room", "normalize_card", "assign_aliases", "limits", "plan", "CELL_KINDS", "CARD_DOC_TYPE")
               if not hasattr(card_review, n)] + [n for n in ("CTX_DEFAULT", "MAX_TOKENS_DEFAULT") if not hasattr(external_llm, n)]
    if lacking:
        raise CantMeasure(f"엔진이 이 측정보다 낡았다 — {', '.join(lacking)} 이 없다(risk-200k W1 · 5aa33fc 이상이 필요하다)")
    try:
        commit = subprocess.run(["git", "-C", str(engine_dir), "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, timeout=10, check=False).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        commit = None
    info = {"dir": str(engine_dir), "commit": commit, "api_rev": card_review.API_REV, "norm_rev": card_review.NORM_REV,
            "limits_formula_rev": card_review.LIMITS_FORMULA_REV, "features": list(card_review.FEATURES)}
    return card_review, external_llm, info


# ---------------------------------------------------------------- 창 · 명단
def default_windows(external_llm: Any) -> str:
    return f"1M={ONE_M}:0,200k={external_llm.CTX_DEFAULT}:{external_llm.MAX_TOKENS_DEFAULT}"


def parse_windows(text: str) -> list[tuple[str, int, int]]:
    """`이름=창:출력상한,…` → [(이름, 창, 출력 상한)]. 첫 창이 배수의 기준이다."""
    out = []
    for part in [p.strip() for p in text.split(",") if p.strip()]:
        name, _, spec = part.partition("=")
        ctx, _, mt = spec.partition(":")
        if not name or not ctx.strip().isdigit() or (mt.strip() and not mt.strip().isdigit()):
            raise ValueError(f"창 표기가 다르다 — {part!r}(이름=창토큰:출력상한)")
        out.append((name.strip(), int(ctx), int(mt or 0)))
    if not out or len({n for n, _, _ in out}) != len(out):
        raise ValueError(f"창이 없거나 이름이 겹친다 — {text!r}")
    return out


def window_limits(cr: Any, ctx: int, max_tokens: int) -> dict:
    """그 창의 limits() 응답과 이 측정이 쓰는 자리 — 손잡이는 엔진 기본(env={})이다."""
    lim = cr.limits(ctx, "census", max_tokens, env={})
    return {"lim": lim, "card_room": cr.card_room(lim),
            "verdict_slot": lim["p_hard"] - lim["verdict"]["fixed"] - lim["unit_body_max"],
            "sweep_slot": lim["p_hard"] - lim["sweep"]["fixed"] - lim["sweep"]["manifest_page_max"],
            "noinput_card_budget": lim["noinput"]["card_budget"], "offcard_card_budget": lim["offcard"]["card_budget"],
            "runnable": all(lim["runnable"][k] for k in cr.CELL_KINDS)}


def select_roster(keys: list[str], *, agents: list[str] | None, sample: int | None, seed: int | None,
                  include: list[str]) -> list[str]:
    """명단 — 고른 전문가, 무작위 표본(정렬한 키에서 Random(seed).sample — W-D2 와 같은 뽑기)과 덧붙인 전문가, 아니면 전원."""
    ordered = sorted(set(keys))
    if agents:
        return list(dict.fromkeys(agents))
    if sample:
        picked = random.Random(seed).sample(ordered, min(sample, len(ordered)))
        return list(dict.fromkeys(picked + [k for k in include if k not in picked]))
    return ordered


# ---------------------------------------------------------------- 셈
def _calls(decks: list[dict]) -> int:
    """묶음 하나 = 호출 하나, 조각 묶음(chunked)은 조각 수 어림(chunks)만큼."""
    return sum(int(d.get("chunks") or 1) if d.get("chunked") else 1 for d in decks)


def measure_view(cr: Any, cards: list[dict], windows: dict[str, dict]) -> dict:
    """정규 카드 목록 하나(한 전문가의 한 보기) → 렌더 길이와 창마다의 셈."""
    rendered = cr.assign_aliases([c for c in cards if c["sections"]])
    chars = [int(c["chars"]) for c in rendered]
    out: dict = {"cards": len(cards), "rendered": len(rendered), "unrenderable": len(cards) - len(rendered),
                 "checkable": sum(1 for c in rendered if c["checkable"]), "chars_total": sum(chars),
                 "card_chars_max": max(chars, default=0), "card_chars_median": statistics.median(chars) if chars else 0,
                 "windows": {}}
    for name, w in windows.items():
        plan = cr.plan(rendered, [], w["lim"])
        over = [c for c in rendered if c["chars"] > w["card_room"]]
        chunked = [d for d in plan["sweep_decks"] if d.get("chunked")]
        out["windows"][name] = {
            "over_slot": len(over), "over_slot_doc_types": {}, "over_slot_records": [c["record_id"] for c in over],
            "chunks": sum(int(d.get("chunks") or 1) for d in chunked), "oversize": len(plan["oversize"]["cards"]),
            "noinput_over": sum(chars) > w["noinput_card_budget"],
            "verdict_calls": _calls(plan["verdict_decks"]), "sweep_calls": _calls(plan["sweep_decks"]),
        }
    return out


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "median": None, "max": None, "total": 0}
    return {"n": len(values), "median": statistics.median(values), "max": max(values), "total": sum(values)}


def summarize(rows: list[dict], view: str, windows: dict[str, dict]) -> dict:
    """전문가 행 → 한 보기의 합계. 중앙값 · 비율은 렌더 카드가 한 장 이상인 전문가만 센다(0장은 카드 대조 셀이 없다)."""
    mine = [r for r in rows if r["views"].get(view) is not None]
    with_cards = [r for r in mine if r["views"][view]["rendered"] > 0]
    doc_types: dict[str, int] = {}
    for r in mine:
        for dt, n in r["views"][view]["doc_types"].items():
            doc_types[dt] = doc_types.get(dt, 0) + n
    chars_all = [r["views"][view]["chars_total"] for r in with_cards]
    out: dict = {
        "experts": len(mine), "experts_with_cards": len(with_cards),
        "cards_listed": sum(r["views"][view]["cards"] for r in mine),
        "cards_rendered": sum(r["views"][view]["rendered"] for r in mine),
        "unrenderable": sum(r["views"][view]["unrenderable"] for r in mine),
        "doc_types": dict(sorted(doc_types.items(), key=lambda t: (-t[1], str(t[0])))),
        "expert_chars_total": _stats(chars_all),
        "expert_card_chars_max": _stats([r["views"][view]["card_chars_max"] for r in with_cards]),
        "windows": {},
    }
    first = next(iter(windows))
    for name, w in windows.items():
        per = [(r, r["views"][view]["windows"][name]) for r in with_cards]
        over_experts = sorted(((r["agent"], m["over_slot"], r["views"][view]["card_chars_max"]) for r, m in per
                               if m["over_slot"]), key=lambda t: (-t[1], t[0]))
        over_types: dict[str, int] = {}
        for r, m in per:
            for dt, n in m["over_slot_doc_types"].items():
                over_types[dt] = over_types.get(dt, 0) + n
        block = {
            "ctx_tokens": w["lim"]["ctx_tokens"], "max_tokens": w["lim"]["llm_max_tokens"] or 0,
            "card_room": w["card_room"], "verdict_slot": w["verdict_slot"], "sweep_slot": w["sweep_slot"],
            "noinput_card_budget": w["noinput_card_budget"], "runnable": w["runnable"],
            "over_slot_cards": sum(m["over_slot"] for _, m in per),
            "over_slot_doc_types": dict(sorted(over_types.items(), key=lambda t: (-t[1], str(t[0])))),
            "experts_with_over_slot": len(over_experts),
            "chunks": sum(m["chunks"] for _, m in per), "oversize_cards": sum(m["oversize"] for _, m in per),
            "experts_noinput_over": sum(1 for _, m in per if m["noinput_over"]),
            "verdict_calls_per_cell": _stats([m["verdict_calls"] for _, m in per]),
            "sweep_calls": _stats([m["sweep_calls"] for _, m in per]),
            "over_slot_experts": [{"agent": a, "over_slot_cards": n, "max_card_chars": c} for a, n, c in over_experts],
        }
        if name != first:
            ratios = [m["verdict_calls"] / r["views"][view]["windows"][first]["verdict_calls"] for r, m in per
                      if r["views"][view]["windows"][first]["verdict_calls"] > 0]
            base_sweep = sum(r["views"][view]["windows"][first]["sweep_calls"] for r, _ in per)
            block["vs_" + first] = {
                "verdict_calls_ratio_per_expert": {"median": round(statistics.median(ratios), 3) if ratios else None,
                                                   "max": round(max(ratios), 3) if ratios else None},
                "sweep_calls_ratio_total": round(block["sweep_calls"]["total"] / base_sweep, 3) if base_sweep else None,
            }
        out["windows"][name] = block
    return out


def measure_expert(cr: Any, agent: str, records: list[dict], windows: dict[str, dict]) -> dict:
    """한 전문가 — 기록을 한 번 정규화해 두 보기(records · knowledge_cards)로 잰다."""
    doc_type_of = {str(r.get("id")): str(r.get("doc_type") or "") for r in records if isinstance(r, dict)}
    normalized = [c for c in (cr.normalize_card(r) for r in records) if c is not None]
    views = {"records": normalized,
             "knowledge_cards": [c for c in normalized if doc_type_of.get(c["record_id"]) == cr.CARD_DOC_TYPE]}
    out: dict = {"agent": agent, "listed": len(records), "invalid": len(records) - len(normalized), "views": {}}
    for view, cards in views.items():
        got = measure_view(cr, cards, windows)
        got["doc_types"] = {}
        for c in cards:
            dt = doc_type_of.get(c["record_id"], "")
            got["doc_types"][dt] = got["doc_types"].get(dt, 0) + 1
        for m in got["windows"].values():
            for rid in m.pop("over_slot_records"):
                dt = doc_type_of.get(rid, "")
                m["over_slot_doc_types"][dt] = m["over_slot_doc_types"].get(dt, 0) + 1
        out["views"][view] = got
    return out


def run(fetch: Callable[[str], Any], cr: Any, windows_spec: list[tuple[str, int, int]], *,
        agents: list[str] | None = None, sample: int | None = None, seed: int | None = None,
        include: list[str] = (), per_expert: bool = False, progress: Callable[[str], None] | None = None) -> dict:
    """명단을 받고 전문가마다 읽어 잰 결과(JSON 으로 낼 사전). fetch 는 GET 경로 → JSON 이다(시험이 가짜를 꽂는다)."""
    listed = fetch("/api/agents")
    if not isinstance(listed, list):
        raise CantMeasure(f"/api/agents 응답이 목록이 아니다 — {type(listed).__name__}")
    keys = [str(a.get("agent_type")) for a in listed if isinstance(a, dict) and a.get("agent_type")]
    roster = select_roster(keys, agents=agents, sample=sample, seed=seed, include=list(include))
    windows = {name: window_limits(cr, ctx, mt) for name, ctx, mt in windows_spec}
    rows: list[dict] = []
    failed: list[dict] = []
    started = time.monotonic()
    for i, agent in enumerate(roster, 1):
        try:
            records = fetch(f"/api/agents/{urllib.parse.quote(agent, safe='')}/records")
        except CantMeasure:
            raise
        except Exception as exc:  # noqa: BLE001 — 한 전문가의 실패는 적고 다음으로 간다(빼고 세지 않는다 — failed 에 남는다)
            failed.append({"agent": agent, "why": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        if records is None:
            failed.append({"agent": agent, "why": "404 — 명단에는 있는데 기록 경로가 그 전문가를 모른다"})
            continue
        if not isinstance(records, list):
            failed.append({"agent": agent, "why": f"기록 응답이 목록이 아니다({type(records).__name__})"})
            continue
        rows.append(measure_expert(cr, agent, [r for r in records if isinstance(r, dict)], windows))
        if progress and (i % 25 == 0 or i == len(roster)):
            progress(f"[{i}/{len(roster)}] {time.monotonic() - started:.0f}s")
    out = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "roster": {"source": "/api/agents", "listed": len(keys), "selected": len(roster), "measured": len(rows),
                   "mode": "agents" if agents else ("sample" if sample else "all"), "sample": sample, "seed": seed,
                   "include": list(include)},
        "windows": {name: {"ctx_tokens": ctx, "max_tokens": mt} for name, ctx, mt in windows_spec},
        "views": {view: summarize(rows, view, windows) for view in ("records", "knowledge_cards")},
        "failed": failed,
        "elapsed_s": round(time.monotonic() - started, 1),
    }
    if per_expert:
        out["experts"] = rows
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="card_window_census", description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=(os.environ.get("HWAXRISK_AIDH_BASE") or "").strip() or DEFAULT_BASE)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--agents", default="", help="쉼표로 고른 전문가(명단 대신)")
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--include", default="", help="표본에 덧붙일 전문가(쉼표)")
    parser.add_argument("--wd2", action="store_true", help="W-D2 표본 — --sample 30 --seed 20261020 --include xd-yield-ramp,material-twin-analyst")
    parser.add_argument("--windows", default="", help="이름=창:출력상한,…(기본 1M=1048576:0,200k=엔진 Claude 길 기본)")
    parser.add_argument("--per-expert", action="store_true")
    parser.add_argument("--out", type=Path, default=None, help="JSON 을 이 파일로(없으면 표준 출력)")
    args = parser.parse_args(argv)
    if args.wd2:
        args.sample, args.seed, args.include = WD2["sample"], WD2["seed"], ",".join(WD2["include"])
    api_key = (os.environ.get("AIDH_API_KEY") or os.environ.get("HWAXRISK_AIDH_API_KEY") or "").strip()
    try:
        cr, external_llm, engine = load_engine(args.engine.resolve())
        windows = parse_windows(args.windows or default_windows(external_llm))
        result = run(http_fetcher(args.base, api_key), cr, windows,
                     agents=[a.strip() for a in args.agents.split(",") if a.strip()] or None,
                     sample=args.sample, seed=args.seed,
                     include=[a.strip() for a in args.include.split(",") if a.strip()],
                     per_expert=args.per_expert, progress=lambda line: print(line, file=sys.stderr, flush=True))
    except (CantMeasure, ValueError) as exc:
        print(f"[잴 수 없음] {exc}", file=sys.stderr)
        return CANT_MEASURE
    result = {"aidh_base": args.base, "engine": engine, **result}
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(f"[잼] {result['roster']['measured']}/{result['roster']['selected']}명 · 실패 {len(result['failed'])} → {args.out}",
              file=sys.stderr)
    else:
        print(text)
    return OK


if __name__ == "__main__":
    sys.exit(main())
