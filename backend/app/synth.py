# 영역 요약과 종합 보고서(재설계 M3 S3-9) — 요약 서술만 LLM(엔진 summary 종류)이고 표·수는 코드가 내며, LLM 이 죽어도 보고서 판은 선다
"""두 부분이다(m3-synthesis 3.9 · 3.10 · M3.md #49 · #50).

- **요약** — 로스터 영역마다 하나(`rr_summaries.scope_kind='domain'`)와 과제 종합 하나(`'target'`). 입력은 그 영역이 제기에 참여한
  등록부 행 **전부**(`merged.domains` 에 그 영역 — 행을 버리지 않는다, D-21), 꼭 다룰 행(주의 A 를 우선순위 순으로
  `limits.summary.cover_max` 까지), 코드가 센 블록(수 · 쟁점 · 정보 요청 · 종합이면 영역 요약)이다. 행 0 인 영역은 LLM 없이
  `code_only(no_rows)`. 입력 해시가 같은 `done` 행이 있으면 다시 부르지 않는다. 엔진 결과는 앱이 한 번 더 대조한다(빠진 must_cover ·
  출처 없는 수 · 입력 밖 참조) — 걸리면 지적을 실어 한 번 다시 묻고 그래도면 `code_only(checks_failed)`.
- **보고서 판** — `assemble_report` 가 등록부·쟁점·셀·완결 수·요약에서 쪽을 조립한다. 보고서의 모든 수는 같은 호출 안의
  `closure.cell_counts` 한 벌에서 나온다(`rr_reports.counts_json` == 머리의 표, 나갈 기준 4). 내용이 직전 판과 같으면 새 판을 만들지
  않는다. 요약이 없거나 실패한 쪽은 '서술 없음 — 까닭' 을 크게 적는다.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from app import closure, common, config, issues, registry, render, review_ops
from app.errors import AppError
from app.risk_store import RiskStore

log = logging.getLogger("hwax_risk.synth")

KIND = "summary"
SYNTH_MODE = "synth"
SYNTH_AGENT = "synth"                     # rr_review_calls.agent_key — 요약 호출은 전문가가 없다
TARGET_SCOPE = ("target", "-")
LINE_MAX_DEFAULT = 400                    # 엔진 limits.summary.line_max 의 기본(ROW_CHARS['summary'])
COVER_MAX_DEFAULT = 30                    # limits 를 못 받았을 때의 꼭 다룰 행 수
B_TOP = 30                                # 종합의 주의 B 상위 행 수
ASKS_TOP = 20
REPORT_TRIGGERS: tuple[str, ...] = ("reviews_partial", "reviews_closed", "issues_closed", "synth_done", "ack", "manual",
                                    "level_up")
ROW_TYPES: tuple[str, ...] = ("head", "risk", "conflict", "gain", "watch", "ask", "para")
# 엔진 줄 종류 → 앱 객체 칸(3.9).
_OUTPUT_KEYS = {"head": "headline", "risk": "key_risks", "conflict": "conflicts", "gain": "gains", "watch": "watch",
                "ask": "info_requests", "para": "narrative"}
DONE_STATES: tuple[str, ...] = ("done", "code_only")
REASON_LABELS = {"no_rows": "이 영역이 제기에 참여한 클러스터가 없다", "content_fail": "엔진이 내용 탓으로 거듭 실패했다",
                 "infra_exhausted": "엔진·포털이 거듭 응답하지 않았다", "ctx_too_small": "이 박스의 창이 요약 입력을 담지 못한다",
                 "checks_failed": "서술이 꼭 다룰 행을 빠뜨렸거나 출처 없는 수를 냈다(다시 물어도 같았다)"}


def _loads(text: Any, default: Any) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def _str(value: Any) -> str:
    return str(value or "").strip()


def _q(value: Any) -> str:
    """앞 단계의 글(전문가 주장·LLM 서술·부품 이름)은 «» 안에 둔다 — 판단어 린터 밖이고 2차 주입을 막는다(WP5b 3.10.4)."""
    return render.quote_source(" ".join(_str(value).split()))


def _domain_labels() -> dict[str, str]:
    from app import taxonomy  # noqa: PLC0415

    return {str(d.get("code")): str(d.get("label") or d.get("code")) for d in taxonomy.load_taxonomy()["axes"]["domain"]}


# ---------------------------------------------------------------- 행 한 줄 · 범위
def row_line(store: RiskStore, row: Mapping[str, Any], *, line_max: int = LINE_MAX_DEFAULT) -> str:
    """등록부 행 한 줄 — `severity=중대 · judgement=WARNING(주장 FAIL) · mechanical.drop_stress · dimension · «이름» · 제기 7명/3영역/
    2단위(검증 4) · 쟁점 upheld · «주장»`(판단어 린터가 허용하는 꼴 — P-17-12). `line_max` 를 넘으면 주장 글만 줄이고 원래 길이를 밝힌다."""
    merged = row.get("merged") or {}
    claimed = merged.get("claimed") or {}
    judgement = _str(row.get("judgement")) or "undetermined"
    if claimed.get("judgement") and claimed["judgement"] != judgement:
        judgement += f"(주장 {claimed['judgement']})"
    names = issues.part_names(store, row) or [_str(row.get("subject_key"))]
    head = (f"severity={_str(row.get('severity')) or '-'} · judgement={judgement} · {_str(row.get('mechanism'))}."
            f"{_str(row.get('mechanism_detail'))} · {_str(row.get('change_kind')) or '-'} · {_q(', '.join(names))} · 제기 "
            f"{int(row.get('support_experts') or row.get('support') or 0)}명/{int(row.get('support_domains') or 0)}영역/"
            f"{int(row.get('support_units') or 0)}단위(검증 {int(row.get('support_verified') or 0)})")
    if row.get("issue_state"):
        head += f" · 쟁점 {row['issue_state']}"
    claim = _str(merged.get("claim"))
    if not claim:
        return head[:line_max]
    room = line_max - len(head) - len(" · ") - 2
    if len(claim) <= room:
        return f"{head} · {_q(claim)}"
    mark = f"…({len(claim)}자 중 {{kept}}자)"
    kept = max(0, room - len(mark.format(kept=len(claim))))
    return (f"{head} · {_q(claim[:kept])}{mark.format(kept=kept)}")[:line_max]


def _risk_rows(store: RiskStore, target_key: str) -> list[dict]:
    return [r for r in registry.registry_rows(store, target_key) if r["direction"] == "risk"]


def domain_rows(store: RiskStore, target_key: str, domain: str) -> list[dict]:
    """그 영역이 제기에 참여한 등록부 행 전부(`merged.domains` 에 그 영역 — 개선 행 포함), 주의 등급 → 우선순위 → 키 순."""
    rows = [r for r in registry.registry_rows(store, target_key) if domain in (r["merged"].get("domains") or ())]
    return sorted(rows, key=_row_order)


def _row_order(row: Mapping[str, Any]) -> tuple:
    return (registry.ATTENTION_ORDER.get(_str(row.get("attention")) or "C", 2), -float(row.get("priority") or 0),
            str(row["cluster_key"]))


def target_rows(store: RiskStore, target_key: str) -> list[dict]:
    """종합 입력 — 주의 A 전부와 B 상위 B_TOP 건(리스크 행)."""
    rows = sorted(_risk_rows(store, target_key), key=_row_order)
    a = [r for r in rows if r.get("attention") == "A"]
    b = [r for r in rows if r.get("attention") == "B"][:B_TOP]
    return a + b


def _cover(rows: Sequence[Mapping[str, Any]], cover_max: int) -> tuple[list[str], int]:
    """꼭 다룰 행 — 주의 A 를 우선순위 순으로 cover_max 까지. (참조 목록, 넘친 A 행 수)."""
    a = [r for r in sorted(rows, key=_row_order) if r.get("attention") == "A"]
    return [f"reg:{r['cluster_key']}" for r in a[:cover_max]], max(0, len(a) - cover_max)


# ---------------------------------------------------------------- 블록(코드가 센 원천 — 요약의 수는 여기서만 온다)
def _numbers_block(counts: Mapping[str, Any], domain: str | None) -> dict:
    experts = counts["experts"]
    if domain is None:
        cells = counts["cells"]
        text = (f"전문가 {counts['roster']} · 검토 대상 단위 {counts['units']['reviewable']} · 셀 {cells['actual']}/"
                f"{cells['expected']} · " + " · ".join(f"{k} {v}" for k, v in sorted(cells["by_state"].items()))
                + f" · 등록부 클러스터 {counts['registry']['clusters']}")
        return {"name": "numbers", "title": "과제 수치", "text": text}
    by_state: dict[str, int] = {}
    for row in counts["_rows"]:
        if row.get("domain") == domain:
            by_state[row["state"]] = by_state.get(row["state"], 0) + 1
    text = (f"검토한 전문가 {experts['active_by_domain'].get(domain, 0)} · 카드로 본 전문가 "
            f"{experts['have_by_domain'].get(domain, 0)} · " + (" · ".join(f"셀 {k} {v}" for k, v in sorted(by_state.items()))
                                                             or "셀 없음"))
    return {"name": "numbers", "title": "영역 수치", "text": text}


def _issues_block(store: RiskStore, target_key: str, domain: str | None) -> dict | None:
    lines = []
    for issue in issues.issue_rows(store, target_key):
        raisers = issue["basis"].get("raisers") or ()
        if domain is not None and not any(r.get("domain") == domain for r in raisers):
            continue
        lines.append(f"reg:{issue['anchor_cluster_key']} · {issue['state']}" + (f"/{issue['outcome']}" if issue["outcome"]
                                                                                else ""))
    return {"name": "issues", "title": "쟁점 결과", "text": "\n".join(lines)} if lines else None


def _asks_block(store: RiskStore, target_key: str, domain: str | None) -> dict | None:
    """정보 요청 — 보류 판정의 `need` 를 접어 건수 순(X1-15 (3))."""
    rows = store.query("SELECT v.need AS need, c.domain AS domain FROM rr_card_verdicts v JOIN rr_review_cells c ON"
                       " c.target_key = v.target_key AND c.unit_id = v.unit_id AND c.agent_key = v.agent_key WHERE"
                       " v.target_key = ? AND v.is_effective = 1 AND v.need IS NOT NULL AND v.need <> ''", (target_key,))
    folded: dict[str, int] = {}
    for row in rows:
        if domain is None or row["domain"] == domain:
            key = " ".join(_str(row["need"]).split())
            folded[key] = folded.get(key, 0) + 1
    top = sorted(folded.items(), key=lambda kv: (-kv[1], kv[0]))[:ASKS_TOP]
    return {"name": "asks", "title": "정보 요청", "text": "\n".join(f"{n}건 · {_q(t)}" for t, n in top)} if top else None


def _domains_block(store: RiskStore, target_key: str) -> dict | None:
    """종합 호출의 영역 요약 — 앞 단계 LLM 글이라 엔진이 «» 안에 그린다(앱도 «» 로 싣는다)."""
    lines = []
    for row in latest_summaries(store, target_key):
        if row["scope_kind"] != "domain" or row["state"] != "done":
            continue
        out = _loads(row["output_json"], {})
        lines.append(f"[{row['scope_key']}] 머리 {_q(out.get('headline'))}")
        lines += [f"[{row['scope_key']}] 걸림 {_q(r.get('text'))}" for r in out.get("key_risks") or ()]
    return {"name": "domains", "title": "영역 요약", "text": "\n".join(lines)} if lines else None


# ---------------------------------------------------------------- 요약 계획
def summary_id_of(target_key: str, scope_kind: str, scope_key: str, input_hash: str) -> str:
    return "sm-" + hashlib.sha1(f"{target_key}|{scope_kind}|{scope_key}|{input_hash}".encode()).hexdigest()[:16]


def summary_input(store: RiskStore, target_key: str, scope_kind: str, scope_key: str, *, limits: Mapping[str, Any] | None,
                  counts: Mapping[str, Any]) -> dict:
    """요약 요청의 `summary` 칸 — {scope, rows, must_cover, blocks} 와 그 해시·꼭 다룰 행 넘침 수. 결정론이다(같은 원장이면 같은 값)."""
    lim = ((limits or {}).get("summary") or {}) if isinstance(limits, Mapping) else {}
    line_max = int(lim.get("line_max") or LINE_MAX_DEFAULT)
    cover_max = int(lim.get("cover_max") or COVER_MAX_DEFAULT)
    domain = None if scope_kind == "target" else scope_key
    rows = target_rows(store, target_key) if domain is None else domain_rows(store, target_key, domain)
    cover, over = _cover(rows, cover_max)
    blocks = [_numbers_block(counts, domain), _issues_block(store, target_key, domain), _asks_block(store, target_key, domain)]
    if domain is None:
        blocks.append(_domains_block(store, target_key))
    label = "과제 종합" if domain is None else _domain_labels().get(domain, domain)
    summary = {"scope": {"kind": scope_kind, "key": scope_key, "label": label},
               "rows": [{"ref": f"reg:{r['cluster_key']}", "text": row_line(store, r, line_max=line_max)} for r in rows],
               "must_cover": cover, "blocks": [b for b in blocks if b]}
    prompt_rev = _str(((limits or {}).get("prompt_rev") or {}).get(KIND)) if isinstance(limits, Mapping) else ""
    digest = common.sha256_hex(common.canonical_json({"summary": summary, "prompt_rev": prompt_rev}))[:16]
    return {"summary": summary, "input_hash": digest, "cover_over": over, "n_rows": len(summary["rows"]),
            "input_chars": len(common.canonical_json(summary))}


def summary_request(target_key: str, summary: Mapping[str, Any], *, limits: Mapping[str, Any] | None,
                    notes: Sequence[str] = ()) -> dict:
    """엔진 run 본문(kind 'summary' — 엔진 RunRequest · SummaryInput). 중립 서기라 expert 는 null 이고 카드·단위·extra 를 싣지 않는다.
    `notes` 는 앞 답의 지적 — 다시 물을 때 블록 하나로 싣는다. 기대 판은 받은 limits 에 있는 것만 싣는다."""
    body: dict[str, Any] = {"kind": KIND, "variant": None, "target_key": target_key, "expert": None,
                            "summary": json.loads(json.dumps(dict(summary)))}
    if notes:
        body["summary"]["blocks"].append({"name": "checks", "title": "앞 답의 지적", "text": "\n".join(notes)})
    expect = {}
    if isinstance(limits, Mapping):
        if ((limits.get("prompt_rev") or {}).get(KIND)):
            expect["prompt_rev"] = limits["prompt_rev"][KIND]
        if ((limits.get("limits_rev_by_kind") or {}).get(KIND)):
            expect["limits_rev_kind"] = limits["limits_rev_by_kind"][KIND]
    if expect:
        body["expect"] = expect
    return body


def latest_summaries(store: RiskStore, target_key: str) -> list[dict]:
    """범위마다 가장 늦은 요약 행."""
    out: dict[tuple[str, str], dict] = {}
    for row in store.query("SELECT summary_id, scope_kind, scope_key, input_hash, n_rows, input_chars, state, state_reason,"
                           " output_json, checks_json, attempts, charged, infra_streak, not_before, run_id, model, prompt_rev,"
                           " error_code, error, created_at, finished_at FROM rr_summaries WHERE target_key = ?"
                           " ORDER BY created_at, summary_id", (target_key,)):
        out[(row["scope_kind"], row["scope_key"])] = dict(row)
    return list(out.values())


def _code_output(summary: Mapping[str, Any], reason: str) -> dict:
    """서술 없는 코드 조립본 — 행 수와 까닭만(LLM 0회)."""
    return {"headline": None, "key_risks": [], "conflicts": [], "gains": [], "watch": [], "info_requests": [],
            "narrative": None, "code_only": reason, "n_rows": len(summary.get("rows") or ())}


def plan_summary(store: RiskStore, target_key: str, scope_kind: str, scope_key: str, *, run_id: str,
                 limits: Mapping[str, Any] | None, counts: Mapping[str, Any], owner_sub: str) -> dict:
    """요약 행 하나를 세운다 — 입력이 같은 done(또는 no_rows) 행이 있으면 그 행 그대로, 행 0 이면 code_only(no_rows), 아니면 pending.
    같은 입력의 실패 행은 이번 잡으로 다시 연다(차감·백오프를 비운다)."""
    built = summary_input(store, target_key, scope_kind, scope_key, limits=limits, counts=counts)
    sid = summary_id_of(target_key, scope_kind, scope_key, built["input_hash"])
    row = store.query_one("SELECT state, state_reason FROM rr_summaries WHERE summary_id = ?", (sid,))
    now = common.now_epoch()
    if row is not None and (row["state"] == "done" or (row["state"] == "code_only" and row["state_reason"] == "no_rows")):
        return {"summary_id": sid, "state": row["state"], "reused": True}
    if built["n_rows"] == 0:
        state, reason, output = "code_only", "no_rows", common.canonical_json(_code_output(built["summary"], "no_rows"))
    else:
        state, reason, output = "pending", None, None
    if row is None:
        store.execute(
            "INSERT INTO rr_summaries(summary_id, target_key, owner_sub, scope_kind, scope_key, input_hash, input_chars,"
            " n_rows, state, state_reason, output_json, run_id, created_at, finished_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, target_key, owner_sub, scope_kind, scope_key, built["input_hash"], built["input_chars"], built["n_rows"],
             state, reason, output, run_id, now, now if state == "code_only" else None))
    else:
        store.execute("UPDATE rr_summaries SET state = ?, state_reason = ?, output_json = ?, checks_json = NULL, attempts = 0,"
                      " charged = 0, infra_streak = 0, not_before = NULL, run_id = ?, error_code = NULL, error = NULL,"
                      " finished_at = ? WHERE summary_id = ?",
                      (state, reason, output, run_id, now if state == "code_only" else None, sid))
    return {"summary_id": sid, "state": state, "reused": False}


def plan_domains(store: RiskStore, target_key: str, *, run_id: str, limits: Mapping[str, Any] | None,
                 owner_sub: str) -> list[dict]:
    """로스터 영역 전부(HWAXRISK_ROSTER_DOMAINS — 15)에 요약 행 하나씩(나갈 기준 4 의 '15건')."""
    counts = closure.cell_counts(store, target_key)
    return [plan_summary(store, target_key, "domain", d, run_id=run_id, limits=limits, counts=counts, owner_sub=owner_sub)
            for d in config.settings.risk_roster_domains]


# ---------------------------------------------------------------- 결과 → 객체 · 대조
def to_output(result: Mapping[str, Any]) -> dict:
    """엔진 결과 줄(JSON Lines 를 옮긴 rows) → 앱 객체 {headline, key_risks[], conflicts[], gains[], watch[], info_requests[],
    narrative}. 줄의 `refs`(엔진이 별칭을 되돌린 reg: 참조)를 그대로 싣는다."""
    out: dict[str, Any] = {"headline": None, "key_risks": [], "conflicts": [], "gains": [], "watch": [], "info_requests": [],
                           "narrative": None}
    paras: list[str] = []
    for row in result.get("rows") or ():
        t = _str(row.get("t"))
        if t not in ROW_TYPES:
            continue
        item = {"text": _str(row.get("text")), "refs": [str(r) for r in row.get("refs") or ()]}
        if t == "head":
            out["headline"] = out["headline"] or item["text"]
        elif t == "para":
            paras.append(item["text"])
        else:
            out[_OUTPUT_KEYS[t]].append(item)
    out["narrative"] = "\n".join(p for p in paras if p) or None
    return out


def check_summary(result: Mapping[str, Any], summary: Mapping[str, Any]) -> dict:
    """앱의 대조 — 엔진 `missing`(보충을 다 써도 빠진 must_cover), `checks.nums_unsourced` 가 선 줄, 입력 밖 참조(두 리포의 정규화가
    갈리면 크게 보이게), 엔진이 몫에서 끊은 입력(`meta.clipped` — 보고서에 크게 싣는다)."""
    known = {str(r["ref"]) for r in summary.get("rows") or ()}
    aliases = ((result.get("meta") or {}).get("aliases") or {}).get("rows") or {}
    missing = [str(aliases.get(m, m)) for m in result.get("missing") or ()]
    unsourced = [{"t": _str(r.get("t")), "nums": list((r.get("checks") or {}).get("nums_unsourced") or ())}
                 for r in result.get("rows") or () if (r.get("checks") or {}).get("nums_unsourced")]
    outside = sorted({str(ref) for r in result.get("rows") or () for ref in r.get("refs") or () if str(ref) not in known})
    clipped = (result.get("meta") or {}).get("clipped") or None
    return {"missing": missing, "nums_unsourced": unsourced, "refs_outside": outside, "clipped": clipped,
            "ok": not missing and not unsourced and not outside}


def check_notes(check: Mapping[str, Any]) -> list[str]:
    """다시 물을 때 싣는 지적(코드 산문 — 판단어 없이)."""
    notes = []
    if check.get("missing"):
        notes.append("꼭 다룰 행 가운데 risk·conflict 줄에 없는 것: " + ", ".join(check["missing"]))
    if check.get("nums_unsourced"):
        notes.append("행·블록에 없는 수를 쓴 줄: " + ", ".join(f"{u['t']}({', '.join(map(str, u['nums']))})"
                                                       for u in check["nums_unsourced"]))
    if check.get("refs_outside"):
        notes.append("입력에 없는 참조: " + ", ".join(check["refs_outside"]))
    return notes


# ---------------------------------------------------------------- 잡 · 워커
def create_synth_job(store: RiskStore, target_key: str, *, owner_sub: str, requester_sub: str | None = None,
                     consent_source: str | None = "web", settings: Any = None,
                     chain: Mapping[str, Any] | None = None) -> dict:
    """종합 잡(`rr_jobs.mode='synth'`) — 영역 요약 → 과제 종합 → 보고서 판(synth_done). 자격이 없어도 행을 만들고 까닭을 적는다."""
    from app import runner  # noqa: PLC0415 — runner 는 이 모듈을 쓴다.

    cfg = settings or config.settings
    credential, note = runner.resolve_credential_with_note(store, cfg, owner_sub, requester_sub)
    job_id = common.new_uuid()
    now = common.now_epoch()
    params = {"mode": SYNTH_MODE, "requester": requester_sub, "consent": True, "consent_source": consent_source,
              "credential": credential["kind"] if credential else None}
    error = None if credential else "pat_unavailable" + (f": {note}" if note else "")
    store.execute(
        "INSERT INTO rr_jobs(id, target_key, owner_sub, tier, state, concurrency, params_json, credential_email, panels_done,"
        " panels_total, error, mode, chain_json, created_at, updated_at)"
        " VALUES (?, ?, ?, NULL, 'queued', 1, ?, ?, 0, ?, ?, ?, ?, ?, ?)",
        (job_id, target_key, owner_sub, common.canonical_json(params), (credential or {}).get("email"),
         len(config.settings.risk_roster_domains) + 1, error, SYNTH_MODE,
         common.canonical_json(dict(chain)) if chain else None, now, now))
    return {"job_id": job_id, "credential": params["credential"], **({"error": error} if error else {})}


class SynthWorker:
    """종합 잡 하나씩, 요약 호출은 차례로(#51 — 관문을 카드 대조와 같이 쓰므로 따로 동시 수를 두지 않는다). `tick()` 한 번이 요약
    호출 하나(또는 계획·조립 한 걸음)다. 비우기 범위 `all` 동안은 새 요약 호출을 내지 않는다(#50 — `panels` 범위에서는 이어 돈다)."""

    def __init__(self, store: RiskStore, settings: Any, engine: Any, *, stop: threading.Event | None = None,
                 clock: Callable[[], int] | None = None) -> None:
        self.store = store
        self.settings = settings
        self.engine = engine
        self.stop = stop or threading.Event()
        self.clock = clock or common.now_epoch

    # ------------------------------------------------------------ 잡
    def _job(self) -> dict | None:
        row = self.store.query_one(
            "SELECT id, target_key, owner_sub, state, params_json, credential_email, hold_code, hold_until, error"
            " FROM rr_jobs WHERE mode = ? AND (state IN ('queued', 'running') OR (state = 'paused' AND hold_code IS NOT"
            " NULL AND hold_code <> 'user' AND hold_until IS NOT NULL AND hold_until <= ?)) ORDER BY created_at, id LIMIT 1",
            (SYNTH_MODE, self.clock()))
        return dict(row) if row is not None else None

    def _set(self, job_id: str, state: str, *, hold: str | None = None, until: int | None = None,
             error: str | None = None) -> None:
        self.store.execute("UPDATE rr_jobs SET state = ?, hold_code = ?, hold_until = ?, error = ?, updated_at = ?"
                           " WHERE id = ?", (state, hold, until, error, self.clock(), job_id))

    def _drain_all(self) -> bool:
        probe = getattr(self.engine, "drain_state", None)
        if not callable(probe):
            return False
        try:
            state = probe() or {}
        except Exception:  # noqa: BLE001 — 비우기를 못 읽으면 비우지 않는 것으로 본다(러너와 같다).
            return False
        return bool(state.get("on")) and _str(state.get("scope")) in ("all", "")

    def tick(self) -> dict:
        """한 걸음 — {job_id, step, …}. 할 일이 없으면 {'step': 'idle'}."""
        if self.engine is None or self.stop.is_set():
            return {"step": "idle"}
        job = self._job()
        if job is None:
            return {"step": "idle"}
        if self._drain_all():
            note = "draining: 에이전트 서버가 전부 비우는 중이다(update-all) — 새 요약 호출을 내지 않는다. 비우기가 끝나면 이어 돈다"
            if job["error"] != note:
                self.store.execute("UPDATE rr_jobs SET error = ?, updated_at = ? WHERE id = ?", (note, self.clock(), job["id"]))
            return {"job_id": job["id"], "step": "draining"}
        if job["state"] != "running":
            self._set(job["id"], "running")
        email = job["credential_email"] or _loads(job["params_json"], {}).get("requester") or job["owner_sub"]
        try:
            limits = self.engine.limits(email=email)
        except Exception as exc:  # noqa: BLE001 — 아래 run 과 같은 갈래로 가른다.
            return self._job_error(job, exc)
        key = job["target_key"]
        rows = {(r["scope_kind"], r["scope_key"]): r for r in self.store.query(
            "SELECT summary_id, scope_kind, scope_key, state, not_before FROM rr_summaries WHERE target_key = ? AND run_id = ?",
            (key, job["id"]))}
        if not any(k[0] == "domain" for k in rows):
            plan_domains(self.store, key, run_id=job["id"], limits=limits, owner_sub=job["owner_sub"])
            return {"job_id": job["id"], "step": "planned"}
        due = [r for k, r in sorted(rows.items()) if r["state"] == "pending" and int(r["not_before"] or 0) <= self.clock()]
        if due:
            return self._run_one(job, due[0]["summary_id"], limits, email)
        if any(r["state"] in ("pending", "running") for r in rows.values()):
            return {"job_id": job["id"], "step": "waiting"}
        if TARGET_SCOPE not in rows:
            counts = closure.cell_counts(self.store, key)
            plan_summary(self.store, key, *TARGET_SCOPE, run_id=job["id"], limits=limits, counts=counts,
                         owner_sub=job["owner_sub"])
            return {"job_id": job["id"], "step": "planned_target"}
        report = assemble_report(self.store, key, trigger="synth_done")
        self._set(job["id"], "completed")
        from app import chain  # noqa: PLC0415 — chain 은 이 모듈을 쓴다.

        chain.safe(chain.on_synth_closed, self.store, job)
        return {"job_id": job["id"], "step": "completed", "report": report}

    def _job_error(self, job: Mapping[str, Any], exc: BaseException) -> dict:
        from app import engine_client  # noqa: PLC0415

        try:
            outcome = engine_client.review_outcome(exc)
        except TypeError:
            raise exc from None
        if outcome.klass == review_ops.JOB:
            self._set(job["id"], "paused", hold=outcome.hold_code, error=f"{outcome.code}: {exc}")
        else:
            self.store.execute("UPDATE rr_jobs SET error = ?, updated_at = ? WHERE id = ?",
                               (f"{outcome.code}: {exc}", self.clock(), job["id"]))
        return {"job_id": job["id"], "step": "job_error", "code": outcome.code}

    # ------------------------------------------------------------ 요약 하나
    def _run_one(self, job: Mapping[str, Any], summary_id: str, limits: Mapping[str, Any], email: str) -> dict:
        row = dict(self.store.query_one("SELECT * FROM rr_summaries WHERE summary_id = ?", (summary_id,)))
        key = job["target_key"]
        counts = closure.cell_counts(self.store, key)
        built = summary_input(self.store, key, row["scope_kind"], row["scope_key"], limits=limits, counts=counts)
        if built["input_hash"] != row["input_hash"]:
            # 계획한 뒤 원장이 바뀌었다(병합·쟁점 해결) — 이번 입력으로 다시 세운다(같은 run).
            self.store.execute("UPDATE rr_summaries SET state = 'code_only', state_reason = 'superseded', finished_at = ?"
                               " WHERE summary_id = ?", (self.clock(), summary_id))
            plan_summary(self.store, key, row["scope_kind"], row["scope_key"], run_id=job["id"], limits=limits,
                         counts=counts, owner_sub=job["owner_sub"])
            return {"job_id": job["id"], "step": "replanned", "summary_id": summary_id}
        if (limits.get("runnable") or {}).get(KIND) is False:
            return self._close(summary_id, "code_only", "ctx_too_small", built["summary"], step="not_runnable",
                               error="runnable.summary=false — 이 박스에서 요약만 못 돈다")
        checks = _loads(row["checks_json"], {}) or {}
        body = summary_request(key, built["summary"], limits=limits, notes=checks.get("notes") or ())
        call_id = common.new_uuid()
        started = self.clock()
        self.store.execute("UPDATE rr_summaries SET state = 'running', attempts = attempts + 1, call_id = ? WHERE summary_id = ?",
                           (call_id, summary_id))
        try:
            result = self.engine.run(body, email=email, should_stop=lambda: "stopped" if self.stop.is_set() else None)
        except Exception as exc:  # noqa: BLE001 — 부류로 가른다.
            return self._failed(job, row, built["summary"], exc, call_id=call_id, started=started, body=body)
        self._ledger(job, call_id, started, body, result=result, state="ok")
        check = check_summary(result, built["summary"])
        meta = result.get("meta") or {}
        # 꼭 다룰 행이 cover_max 에 걸렸으면 서술 대상은 A 상위만이다 — 보고서가 그 사실을 적는다(조용히 빼지 않는다).
        cover = {"cover_n": len(built["summary"]["must_cover"]), "cover_over": built["cover_over"]}
        if check["ok"]:
            return self._close(summary_id, "done", None, built["summary"], step="done",
                               output={**to_output(result), **cover}, checks=check, model=meta.get("model"),
                               prompt_rev=meta.get("prompt_rev"))
        if not checks.get("retried"):
            self.store.execute("UPDATE rr_summaries SET state = 'pending', checks_json = ? WHERE summary_id = ?",
                               (common.canonical_json({**check, "retried": True, "notes": check_notes(check)}), summary_id))
            return {"job_id": job["id"], "step": "reask", "summary_id": summary_id}
        return self._close(summary_id, "code_only", "checks_failed", built["summary"], step="checks_failed",
                           output={**to_output(result), "code_only": "checks_failed"}, checks={**check, "retried": True},
                           model=meta.get("model"), prompt_rev=meta.get("prompt_rev"))

    def _failed(self, job: Mapping[str, Any], row: Mapping[str, Any], summary: Mapping[str, Any], exc: BaseException, *,
                call_id: str, started: int, body: Mapping[str, Any]) -> dict:
        from app import engine_client  # noqa: PLC0415

        code = _str(getattr(exc, "code", None))
        sid = row["summary_id"]
        try:
            outcome = engine_client.review_outcome(exc)
        except TypeError:
            outcome = review_ops.classify("internal_error")
        self._ledger(job, call_id, started, body, error=exc,
                     state="infra_fail" if outcome.klass in (review_ops.INFRA, review_ops.WAIT) else "content_fail")
        if code == "over_budget":
            return self._close(sid, "code_only", "ctx_too_small", summary, step="over_budget", error=str(exc))
        if code == "cover_too_large":
            # 앱이 cover_max 를 어겼다 — 앱 결함이라 종합 잡을 contract 로 보류한다(#49). 요약 행은 대기로 돌아간다.
            self.store.execute("UPDATE rr_summaries SET state = 'pending', error_code = ?, error = ? WHERE summary_id = ?",
                               (code, str(exc), sid))
            self._set(job["id"], "paused", hold="contract", error=f"{code}: {exc}")
            return {"job_id": job["id"], "step": "hold", "hold": "contract"}
        cfg = self.settings or config.settings
        if outcome.klass == review_ops.JOB:
            self.store.execute("UPDATE rr_summaries SET state = 'pending', error_code = ?, error = ? WHERE summary_id = ?",
                               (outcome.code, str(exc), sid))
            self._set(job["id"], "paused", hold=outcome.hold_code, error=f"{outcome.code}: {exc}")
            return {"job_id": job["id"], "step": "hold", "hold": outcome.hold_code}
        if outcome.klass in (review_ops.WAIT, review_ops.CANCELLED):
            until = self.clock() + int(outcome.retry_after_s or review_ops.WAIT_DEFAULT_S)
            self.store.execute("UPDATE rr_summaries SET state = 'pending', not_before = ?, error_code = ? WHERE summary_id = ?",
                               (until, outcome.code, sid))
            return {"job_id": job["id"], "step": "wait", "code": outcome.code}
        if outcome.klass == review_ops.INFRA:
            streak = int(row["infra_streak"] or 0) + 1
            if streak >= int(cfg.risk_summary_infra_max):
                return self._close(sid, "code_only", "infra_exhausted", summary, step="infra_exhausted", error=str(exc),
                                   infra_streak=streak)
            until = self.clock() + review_ops.backoff_s(streak, salt=sid)
            self.store.execute("UPDATE rr_summaries SET state = 'pending', infra_streak = ?, not_before = ?, error_code = ?,"
                               " error = ? WHERE summary_id = ?", (streak, until, outcome.code, str(exc), sid))
            return {"job_id": job["id"], "step": "infra", "code": outcome.code}
        charged = int(row["charged"] or 0) + 1
        if charged >= int(cfg.risk_summary_max_charged):
            return self._close(sid, "code_only", "content_fail", summary, step="content_fail", error=str(exc),
                               charged=charged)
        self.store.execute("UPDATE rr_summaries SET state = 'pending', charged = ?, error_code = ?, error = ?"
                           " WHERE summary_id = ?", (charged, outcome.code, str(exc), sid))
        return {"job_id": job["id"], "step": "content", "code": outcome.code}

    def _close(self, summary_id: str, state: str, reason: str | None, summary: Mapping[str, Any], *, step: str,
               output: Mapping[str, Any] | None = None, checks: Mapping[str, Any] | None = None, model: Any = None,
               prompt_rev: Any = None, error: str | None = None, infra_streak: int | None = None,
               charged: int | None = None) -> dict:
        out = output if output is not None else _code_output(summary, reason or "")
        self.store.execute(
            "UPDATE rr_summaries SET state = ?, state_reason = ?, output_json = ?, checks_json = COALESCE(?, checks_json),"
            " model = COALESCE(?, model), prompt_rev = COALESCE(?, prompt_rev), error = COALESCE(?, error),"
            " infra_streak = COALESCE(?, infra_streak), charged = COALESCE(?, charged), finished_at = ? WHERE summary_id = ?",
            (state, reason, common.canonical_json(dict(out)), common.canonical_json(dict(checks)) if checks else None,
             model, prompt_rev, error, infra_streak, charged, self.clock(), summary_id))
        return {"step": step, "summary_id": summary_id, "state": state, "reason": reason}

    def _ledger(self, job: Mapping[str, Any], call_id: str, started: int, body: Mapping[str, Any], *,
                result: Mapping[str, Any] | None = None, error: BaseException | None = None, state: str) -> None:
        """호출 원장(rr_review_calls, kind 'summary', agent_key 'synth') 한 행."""
        meta = (result or {}).get("meta") or {}
        usage = meta.get("usage") or {}
        quality = (result or {}).get("quality") or {}
        text = common.canonical_json(dict(result)) if result is not None else None
        self.store.execute(
            "INSERT OR REPLACE INTO rr_review_calls(call_id, target_key, agent_key, unit_id, owner_sub, run_id, kind, state,"
            " request_hash, input_sha, prompt_chars, tokens_in, tokens_out, finish_reason, soft_over, attempts, model,"
            " prompt_rev, norm_rev, limits_rev, result_gz, result_sha256, quality_json, error_code, error, started_at,"
            " duration_ms) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (call_id, job["target_key"], SYNTH_AGENT, job["owner_sub"], job["id"], KIND, "ok" if result is not None else state,
             common.sha256_hex(common.canonical_json(dict(body)))[:16], meta.get("input_sha"), meta.get("prompt_chars"),
             usage.get("tokens_in"), usage.get("tokens_out"), meta.get("finish_reason"), int(bool(meta.get("soft_over"))),
             quality.get("attempts"), meta.get("model"), meta.get("prompt_rev"), meta.get("norm_rev"), meta.get("limits_rev"),
             gzip.compress(text.encode("utf-8")) if text else None, common.sha256_hex(text) if text else None,
             common.canonical_json(dict(quality)) if quality else None, getattr(error, "code", None) if error else None,
             str(error) if error else None, started, max(0, self.clock() - started) * 1000))


# ---------------------------------------------------------------- 보고서 판
def _summary_state(store: RiskStore, target_key: str) -> tuple[dict[tuple[str, str], dict], str]:
    """범위별 마지막 요약과 서술 상태(none · partial · full). 행 0 영역(no_rows)은 서술이 필요 없어 full 에 든다."""
    latest = {(r["scope_kind"], r["scope_key"]): r for r in latest_summaries(store, target_key)}
    domains = [("domain", d) for d in config.settings.risk_roster_domains]
    needed = domains + [TARGET_SCOPE]
    done = [k for k in needed if (latest.get(k) or {}).get("state") == "done"]
    satisfied = [k for k in needed if (latest.get(k) or {}).get("state") == "done"
                 or ((latest.get(k) or {}).get("state") == "code_only" and latest[k]["state_reason"] == "no_rows")]
    state = "full" if len(satisfied) == len(needed) else ("partial" if done else "none")
    return latest, state


def _narrative_lines(summary: Mapping[str, Any] | None, *, scope: str) -> list[str]:
    """요약 서술 — '서술은 LLM, 근거는 아래 표' 머리와 «» 안의 서술. 없으면 '서술 없음 — 까닭' 을 크게."""
    if summary is None:
        return [f"**서술 없음 — {scope} 요약이 아직 없다(종합 잡 전).**"]
    if summary["state"] != "done":
        reason = summary.get("state_reason") or summary["state"]
        return [f"**서술 없음 — {REASON_LABELS.get(reason, reason)}({reason}).**"]
    out = _loads(summary["output_json"], {})
    lines = ["서술은 LLM(요약 서기), 근거는 아래 표다 — 서술의 참조는 등록부 키다."]
    if out.get("headline"):
        lines.append(f"- 머리: {_q(out['headline'])}")
    for label, field in (("걸림", "key_risks"), ("갈림", "conflicts"), ("개선", "gains"), ("지켜볼 것", "watch"),
                         ("정보 요청", "info_requests")):
        for item in out.get(field) or ():
            refs = " ".join(f"[{r}]" for r in item.get("refs") or ())
            lines.append(f"- {label}: {_q(item.get('text'))} {refs}".rstrip())
    if out.get("narrative"):
        lines.append(f"- 서술: {_q(out['narrative'])}")
    if out.get("cover_over"):
        lines.append(f"**서술은 주의 A 상위 {out.get('cover_n')}건 — 나머지 {out['cover_over']}건은 표에만 있다.**")
    clipped = (_loads(summary.get("checks_json"), {}) or {}).get("clipped")
    if clipped:
        lines.append(f"**엔진이 입력 일부를 몫에서 끊었다 — {_q(common.canonical_json(clipped))}. 서술은 끊긴 입력으로 썼다.**")
    return lines


def _issue_line(issue: Mapping[str, Any]) -> str:
    """쟁점 결과 한 줄 — 원래 분포와 패널 결과를 한 줄에('제기 12명(FAIL 9 · WARNING 3) · 반대 2명 → 쟁점 패널 하향 중대/WARNING')."""
    basis = issue.get("basis") or {}
    dist = (basis.get("distribution") or {}).get("by_judgement_claimed") or {}
    head = (f"reg:{issue['anchor_cluster_key']} · 제기 {len(basis.get('raisers') or ())}명("
            + " · ".join(f"judgement={k} {v}" for k, v in sorted(dist.items())) + f") · 반대 {len(basis.get('opposers') or ())}명")
    outcome = _loads(issue.get("outcome_json"), {}) or {}
    words = {"upheld": "유지", "downgraded": "하향", "escalated": "상향", "rejected": "기각", "undetermined": "판정 못 함"}
    if issue.get("outcome"):
        tail = f" → 쟁점 패널 {words.get(issue['outcome'], issue['outcome'])}"
        if outcome.get("severity_after"):
            tail += f" severity={outcome['severity_after']} · judgement={outcome.get('judgement_after') or '-'}"
        return head + tail
    return head + f" → {issue['state']}" + (f"({issue['state_reason']})" if issue.get("state_reason") else "")


def _quality_block(store: RiskStore, target_key: str) -> str:
    """품질 블록 — 이 판의 고정본(WP5b 3.11.1 · C10). 진행판에 있으면 그 값, 없으면 그 자리에서 센 값."""
    from app import review_quality  # noqa: PLC0415

    row = store.query_one("SELECT progress_json FROM rr_jobs WHERE target_key = ? AND mode = 'reviews'"
                          " ORDER BY created_at DESC, id DESC LIMIT 1", (target_key,))
    board = ((_loads(row["progress_json"], {}) if row is not None else {}) or {}).get("quality") or {}
    if isinstance(board, Mapping) and board.get("text"):
        return str(board["text"])
    return str(review_quality.block(store, target_key)["text"])


def build_report(store: RiskStore, target_key: str, *, closure_result: Mapping[str, Any], counts: Mapping[str, Any],
                 version_no: int) -> dict:
    """보고서 판 하나의 쪽(저장 모양) — 1 본문 · 영역 쪽(로스터 영역 전부) · 메커니즘 · 부록. 쪽 모양은 전문가 보고서와 같다."""
    latest, narrative_state = _summary_state(store, target_key)
    rows = registry.registry_rows(store, target_key)
    risk = sorted([r for r in rows if r["direction"] == "risk"], key=_row_order)
    gains = sorted([r for r in rows if r["direction"] == "improvement"], key=lambda r: -float(r.get("priority") or 0))
    all_issues = issues.issue_rows(store, target_key)
    labels = _domain_labels()
    level_label = closure_result["level_label"]

    background = [f"# 리스크 심사 보고서 v{version_no} [{level_label}] — {target_key}",
                  f"- 완결: {level_label}"]
    background += [f"- 잔여 {q['label']} · {'막음' if q['blocking'] else '표기'}"
                   + (" · 확인됨" if q.get("acked") else "") for q in closure_result.get("qualifiers") or ()]
    cells = counts["cells"]
    background.append(f"- 수: 전문가 {counts['roster']} · 검토 대상 단위 {counts['units']['reviewable']} · 셀 {cells['actual']}/"
                      f"{cells['expected']}(" + " · ".join(f"{k} {v}" for k, v in sorted(cells["by_state"].items())) + ")")
    reports = counts["experts"]["reports"]
    background.append(f"- 전문가 보고서: 기대 {reports['expected']} · ready {reports['ready']} · partial {reports['partial']}"
                      f" · blocked {reports['blocked']} · 누락 {reports['missing']}")
    open_cells = sum(1 for r in counts["_rows"] if r["state"] in closure.OPEN_CELL_STATES)
    if open_cells:
        background.append(f"**마감 범위 미완 — 열린 셀 {open_cells}**")
    for (kind, key), summary in sorted(latest.items()):
        reason = summary["state_reason"]
        if summary["state"] == "code_only" and reason not in ("no_rows", "superseded"):
            background.append(f"**{key} 요약은 서술 없이 코드 조립본이다 — {REASON_LABELS.get(reason, reason)}({reason}).**")
        clipped = (_loads(summary.get("checks_json"), {}) or {}).get("clipped")
        if clipped:
            background.append(f"**{key} 요약 입력 일부가 엔진 몫에서 끊겼다 — {_q(common.canonical_json(clipped))}.**")

    results = _narrative_lines(latest.get(TARGET_SCOPE), scope="과제 종합")
    a_rows = [r for r in risk if r.get("attention") == "A"]
    b_rows = [r for r in risk if r.get("attention") == "B"]
    results.append(f"## 주의 A {len(a_rows)}건")
    results += [f"- {row_line(store, r, line_max=10_000)}" for r in a_rows]
    results.append(f"## 주의 B 상위 {min(len(b_rows), B_TOP)}건(전체 {len(b_rows)}건)")
    results += [f"- {row_line(store, r, line_max=10_000)}" for r in b_rows[:B_TOP]]
    results.append(f"## 개선 상위 {min(len(gains), 10)}건")
    results += [f"- {row_line(store, r, line_max=10_000)}" for r in gains[:10]]
    results.append(f"## 넘김(2차 영향 미실행의 대신) — {counts['handoffs']['lines']}건 · 영역 쌍 {counts['handoffs']['pairs']}")
    results.append(f"## 쟁점 결과 {len(all_issues)}건")
    results += [f"- {_issue_line(i)}" for i in all_issues if i["state"] in ("resolved", "inconclusive")]

    candidate = registry.verdict_candidate(store, target_key)
    recommendation = [f"## 판정 후보: {candidate.get('verdict')}"] + [f"- 까닭: {_q(r)}" for r in candidate.get("reasons") or ()]
    untried = [i for i in all_issues if i["state"] in closure.ISSUE_UNTRIED_STATES]
    recommendation.append(f"## 미토의 쟁점 {len(untried)}건")
    for issue in untried:
        line = f"- {_issue_line(issue)}"
        if "held_fail" in issue["types"]:
            line += (f" — 전문가 {int(((issue['basis'].get('claimed') or {}).get('fail_experts')) or 0)}명이 FAIL 로 봤으나"
                     " 미토의")
        recommendation.append(line)
    fails = store.query_one("SELECT COUNT(*) AS n, SUM(CASE WHEN sev = '치명' THEN 1 ELSE 0 END) AS k FROM rr_card_verdicts"
                            " WHERE target_key = ? AND is_effective = 1 AND judgement = 'FAIL'", (target_key,))
    recommendation.append(f"- 카드 대조가 FAIL 로 본 판정 {int(fails['n'] or 0)}건 · 그 가운데 severity=치명 {int(fails['k'] or 0)}건"
                          "(등록부에는 hold 로 주의)")
    asks = _asks_block(store, target_key, None)
    if asks:
        recommendation.append("## 정보 요청")
        recommendation += [f"- {line}" for line in asks["text"].split("\n")]

    minutes = ["## 쟁점 패널"]
    minutes += [f"- {r['id']} · 쟁점 {r['issue_id']} · {r['status']}" for r in store.query(
        "SELECT id, issue_id, status FROM rr_panels WHERE target_key = ? AND kind = 'issue' ORDER BY panel_no", (target_key,))]
    minutes.append("## 영역 × 셀 상태")
    by_domain: dict[str, dict[str, int]] = {}
    for row in counts["_rows"]:
        label = row["state"] if row["state"] != "reviewed" else f"reviewed/{row.get('basis') or 'cards'}"
        by_domain.setdefault(row.get("domain") or "-", {}).setdefault(label, 0)
        by_domain[row.get("domain") or "-"][label] += 1
    minutes += [f"- {d}: " + " · ".join(f"{k} {v}" for k, v in sorted(states.items())) for d, states in sorted(by_domain.items())]
    flt = counts["filter"]
    audit = flt.get("audit") or {}
    minutes.append(f"## 거름 {int(flt.get('n') or 0)}셀 · 표본 {int(audit.get('sampled') or 0)} · 놓친 걸림"
                   f" {int(audit.get('risk_miss') or 0)}")
    minutes.append("## 검토 품질(이 판의 고정본)")
    minutes += _quality_block(store, target_key).split("\n")
    acks = store.query("SELECT item, ack_by, ack_reason, revoked_at FROM rr_close_acks WHERE target_key = ? ORDER BY ack_at",
                       (target_key,))
    minutes.append(f"## 사람 확인 {len(acks)}건")
    minutes += [f"- {a['item']} · {a['ack_by']} · {_q(a['ack_reason'])}" + (" · 취소" if a["revoked_at"] else "") for a in acks]

    pages = [{"page_no": 1, "kind": "summary", "title": f"본문 — {level_label}",
              "blocks": {"background": background, "results": results, "recommendation": recommendation, "minutes": minutes}}]
    for domain in config.settings.risk_roster_domains:
        mine = [r for r in rows if domain in (r["merged"].get("domains") or ())]
        a_b = [r for r in sorted(mine, key=_row_order) if r.get("attention") in ("A", "B")]
        c_d = {g: sum(1 for r in mine if r.get("attention") == g) for g in ("C", "D")}
        block = [f"## {labels.get(domain, domain)}({domain})", f"- {_numbers_block(counts, domain)['text']}"]
        if not mine:
            block.append(f"- 이 영역이 제기한 클러스터 없음 — {_numbers_block(counts, domain)['text']}")
        block += _narrative_lines(latest.get(("domain", domain)), scope=f"{domain} 영역")
        block += [f"- {row_line(store, r, line_max=10_000)}" for r in a_b]
        block.append(f"- 주의 C {c_d['C']}건 · D {c_d['D']}건(본문 표 없음)")
        block += [f"- {_issue_line(i)}" for i in all_issues
                  if any(x.get("domain") == domain for x in (i["basis"].get("raisers") or ()))]
        pages.append({"page_no": len(pages) + 1, "kind": "domain", "title": f"영역 {domain}",
                      "blocks": {"background": [], "results": block, "recommendation": [], "minutes": []}})
    mech_table: dict[tuple[str, str], int] = {}
    for row in risk:
        for unit in row["merged"].get("unit_ids") or ("-",):
            mech_table[(unit, _str(row.get("mechanism")))] = mech_table.get((unit, _str(row.get("mechanism"))), 0) + 1
    free = store.query("SELECT mech_free, COUNT(*) AS n FROM rr_card_verdicts WHERE target_key = ? AND is_effective = 1 AND"
                       " mech_free IS NOT NULL AND mech_free <> '' GROUP BY mech_free ORDER BY n DESC, mech_free", (target_key,))
    pages.append({"page_no": len(pages) + 1, "kind": "mechanisms", "title": "메커니즘",
                  "blocks": {"background": [], "minutes": [],
                             "results": ["## 단위 × 메커니즘 대분류(결손 사냥 미실행)"]
                             + [f"- {u} · {m} · {n}" for (u, m), n in sorted(mech_table.items())]
                             + ["## 택소노미 밖 메커니즘"] + [f"- {_q(r['mech_free'])} · {r['n']}" for r in free],
                             "recommendation": []}})
    appendix = ["## 전문가 색인"]
    reports_by = {str(r["agent_key"]): dict(r) for r in store.query(
        "SELECT agent_key, state FROM rr_expert_reports WHERE target_key = ?", (target_key,))}
    for expert in counts["_order"]:
        mine = [r for r in counts["_rows"] if r["agent_key"] == expert["agent_key"]]
        states = {s: sum(1 for r in mine if r["state"] == s) for s in ("reviewed", "na_irrelevant", "no_input", "failed",
                                                                       "skipped")}
        cell_sum = store.query_one(
            "SELECT SUM(cards_judged) AS j, SUM(cards_expected) AS e, SUM(n_fail + n_warning) AS hit, SUM(n_offcard) AS off,"
            " SUM(quote_ok) AS qok, SUM(quote_n) AS qn FROM rr_review_cells WHERE target_key = ? AND agent_key = ?",
            (target_key, expert["agent_key"]))
        appendix.append(
            f"- {expert['agent_key']} · {expert['domain']} · 검토 {states['reviewed']} · 거름 {states['na_irrelevant']} ·"
            f" 입력 결손 {states['no_input']} · 실패 {states['failed']} · 넘김 {states['skipped']} · 판정"
            f" {int(cell_sum['j'] or 0)}/{int(cell_sum['e'] or 0)} · 걸림 {int(cell_sum['hit'] or 0)} · 카드 밖"
            f" {int(cell_sum['off'] or 0)} · 인용 통과 {int(cell_sum['qok'] or 0)}/{int(cell_sum['qn'] or 0)} · 보고서"
            f" {(reports_by.get(expert['agent_key']) or {}).get('state') or '없음'}")
    pages.append({"page_no": len(pages) + 1, "kind": "appendix", "title": "부록 — 전문가 색인",
                  "blocks": {"background": [], "results": [], "recommendation": [], "minutes": appendix}})
    return {"pages": pages, "narrative_state": narrative_state, "summary_ids": sorted(r["summary_id"] for r in latest.values())}


def registry_hash(store: RiskStore, target_key: str) -> str:
    rows = [(r["cluster_key"], r["severity"], r["judgement"], r["status"], r.get("issue_state"), r.get("attention"))
            for r in registry.registry_rows(store, target_key)]
    return common.sha256_hex(common.canonical_json(sorted(rows)))[:16]


def assemble_report(store: RiskStore, target_key: str, *, trigger: str) -> dict:
    """보고서 판 하나 — 수는 같은 호출 안의 `closure.cell_counts` 한 벌(판정과 머리가 같은 값). 내용이 직전 판과 같으면 새 판을
    만들지 않는다(`created: False`). 반환 {report_uid, version_no, pages_n, level_label, counts, narrative_state, created}."""
    if trigger not in REPORT_TRIGGERS:
        raise AppError("E100", f"모르는 보고서 판 계기 — {trigger!r}. 허용 {list(REPORT_TRIGGERS)}.", 422)
    target = store.query_one("SELECT owner_sub, flow FROM rr_targets WHERE target_key = ?", (target_key,))
    if target is None:
        raise AppError("E404", f"타깃이 없습니다 — {target_key}.", 404)
    counts = closure.cell_counts(store, target_key)
    result = closure.close_level_cells(store, target_key, persist=True, counts=counts)
    public = {k: v for k, v in counts.items() if not k.startswith("_")}
    last = store.query_one("SELECT report_uid, version_no, content_hash, pages_n, level_label, narrative_state, counts_json"
                           " FROM rr_reports WHERE target_key = ? ORDER BY version_no DESC LIMIT 1", (target_key,))
    version_no = int(last["version_no"]) + 1 if last is not None else 1
    built = build_report(store, target_key, closure_result=result, counts=counts, version_no=version_no)
    # 판 번호를 뺀 내용으로 해시한다 — 같은 내용이면 판 번호만 다른 새 판을 만들지 않는다.
    body_pages = json.loads(common.canonical_json(built["pages"]).replace(f"v{version_no} [", "v# ["))
    content_hash = common.sha256_hex(common.canonical_json({"pages": body_pages, "counts": public,
                                                            "label": result["level_label"]}))[:16]
    if last is not None and last["content_hash"] == content_hash:
        return {"report_uid": last["report_uid"], "version_no": last["version_no"], "pages_n": last["pages_n"],
                "level_label": last["level_label"], "counts": _loads(last["counts_json"], {}),
                "narrative_state": last["narrative_state"], "created": False}
    heuristic = all(_str(r.get("evidence_grade")) == "경험칙" for r in registry.registry_rows(store, target_key)) and \
        bool(registry.registry_rows(store, target_key))
    title = ("[가설 단계] " if heuristic else "") + f"리스크 심사 보고서 v{version_no} [{result['level_label']}] — {target_key}"
    uid = "rp-" + hashlib.sha1(f"{target_key}|{version_no}".encode()).hexdigest()[:16]
    now = common.now_epoch()
    store.execute(
        "INSERT INTO rr_reports(report_uid, target_key, owner_sub, version_no, trigger, flow, level, level_label,"
        " narrative_state, title, counts_json, closure_hash, cells_hash, registry_hash, summary_ids_json, pages_gz, pages_n,"
        " content_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (uid, target_key, target["owner_sub"], version_no, trigger, target["flow"], result["level"], result["level_label"],
         built["narrative_state"], title, common.canonical_json(public),
         common.sha256_hex(common.canonical_json({"level": result["level"], "label": result["level_label"]}))[:16],
         result["detail"]["cells_hash"], registry_hash(store, target_key), common.canonical_json(built["summary_ids"]),
         gzip.compress(common.canonical_json(built["pages"]).encode("utf-8"), mtime=0), len(built["pages"]), content_hash,
         now))
    # 판이 섰다 — 신선도(종합까지 지금 지문으로 돌았나)가 바뀔 수 있으니 완결 캐시를 다시 쓴다.
    closure.refresh(store, target_key)
    return {"report_uid": uid, "version_no": version_no, "pages_n": len(built["pages"]), "level_label": result["level_label"],
            "counts": public, "narrative_state": built["narrative_state"], "created": True}


def safe_assemble(store: RiskStore, target_key: str, *, trigger: str) -> dict | None:
    """조립은 어떤 단계의 트랜잭션 밖에서 try/except 로 감싼다 — 조립이 터져도 사슬·패널 완료를 무르지 않는다(P-16)."""
    try:
        return assemble_report(store, target_key, trigger=trigger)
    except Exception:  # noqa: BLE001 — 위 설명대로다.
        log.exception("대상 %s 보고서 판(%s) 조립 실패", target_key, trigger)
        return None


# ---------------------------------------------------------------- 읽기 · 렌더
PARTS: tuple[str, ...] = ("summary", "domains", "mechanisms", "appendix", "full")
_PART_KINDS = {"summary": ("summary",), "domains": ("domain",), "mechanisms": ("mechanisms",), "appendix": ("appendix",),
               "full": ("summary", "domain", "mechanisms", "appendix")}
BLOCKS: tuple[str, ...] = ("background", "results", "recommendation", "minutes")


def report_source(store: RiskStore, target_key: str, *, version: int | None = None) -> dict | None:
    """저장된 판(없으면 None) — {report_uid, version_no, title, level_label, narrative_state, counts, pages, trigger, created_at}."""
    sql = ("SELECT report_uid, version_no, trigger, level, level_label, narrative_state, title, counts_json, pages_gz,"
           " pages_n, created_at FROM rr_reports WHERE target_key = ?")
    params: list[Any] = [target_key]
    if version is not None:
        sql += " AND version_no = ?"
        params.append(int(version))
    row = store.query_one(sql + " ORDER BY version_no DESC LIMIT 1", params)
    if row is None:
        return None
    return {"report_uid": row["report_uid"], "version_no": row["version_no"], "trigger": row["trigger"],
            "level": row["level"], "level_label": row["level_label"], "narrative_state": row["narrative_state"],
            "title": row["title"], "counts": _loads(row["counts_json"], {}), "created_at": row["created_at"],
            "pages": json.loads(gzip.decompress(row["pages_gz"]).decode("utf-8"))}


def _md_items(report: Mapping[str, Any], part: str) -> list[tuple[str, str]]:
    kinds = _PART_KINDS[part]
    out: list[tuple[str, str]] = []
    for page in report["pages"]:
        if page["kind"] not in kinds:
            continue
        for block in BLOCKS:
            out += [(block, str(text)) for text in page["blocks"].get(block) or ()]
    return out


def render_report_md(report: Mapping[str, Any], *, part: str = "full") -> str:
    """마크다운 — 저장된 쪽을 차례로 잇는다(블록 순서 background → results → recommendation → minutes)."""
    if part not in PARTS:
        raise AppError("E100", f"모르는 part — {part!r}. 허용 {list(PARTS)}.", 422)
    return "\n".join(text for _block, text in _md_items(report, part))


def render_pages(report: Mapping[str, Any], page_chars: int, *, part: str = "full") -> list[dict]:
    """와이어 쪽 — 쪽 하나가 page_chars 를 넘지 않게 조각을 차례로 담는다(조각 하나가 더 길면 그 조각만으로 한 쪽 — 자르지 않는다).
    블록이 바뀌는 자리에서도 끊는다. 쪽을 차례로 이으면 render_report_md(part) 와 같다."""
    if part not in PARTS:
        raise AppError("E100", f"모르는 part — {part!r}. 허용 {list(PARTS)}.", 422)
    pages: list[tuple[str, list[str]]] = []
    size = 0
    for block, text in _md_items(report, part):
        if pages and pages[-1][0] == block and size + 1 + len(text) <= page_chars:
            pages[-1][1].append(text)
            size += 1 + len(text)
            continue
        pages.append((block, [text]))
        size = len(text)
    return [{"page_no": n, "kind": "synthesis_report", "title": f"{report['title']} — 쪽 {n}/{len(pages)}",
             "blocks": {b: (texts if b == block else []) for b in BLOCKS}}
            for n, (block, texts) in enumerate(pages, start=1)]


def iter_summaries(rows: Iterable[Mapping[str, Any]]) -> list[dict]:
    """요약 행의 바깥 모양(REST·MCP) — 출력·대조를 푼다."""
    return [{**{k: v for k, v in dict(r).items() if k not in ("output_json", "checks_json")},
             "output": _loads(r.get("output_json"), None), "checks": _loads(r.get("checks_json"), None)} for r in rows]
