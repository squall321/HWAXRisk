# 박스 간 이관(dev↔cae00) — GET /api/export JSONL 생성(첫 줄 헤더 + §5.2.2 A→H 표 순서 {table,row})과 POST /api/import 병합(사람 확정이 자동을 이김, 충돌은 conflicts[])
from __future__ import annotations

import base64
import hashlib
import json
import re
import socket
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator

from app import config
from app.errors import AppError
from app.risk_store import MIGRATIONS, RiskStore

EXPORTS_DIRNAME = "exports"
# 살림 표(_schema_migrations·_user_credentials·_user_prefs)는 rr_ 접두가 아니라서 표 목록에 애초에 들어오지 않는다(plan §5.2.5 (6)·§8.2.3).
_CREATE_TABLE_RE = re.compile(r"CREATE TABLE IF NOT EXISTS\s+(rr_\w+)", re.IGNORECASE)


# 박스 지역 표 — owner_sub 가 없는 내용 주소 사본이라 반출·들여오기에서 뺀다(TABLE_ORDER 에 들지 않으므로 그 표의 줄을
# 들여오면 '알 수 없는 표' 422 다). rr_card_packs 는 사내 카드 원문의 동결본이고 과제 자료가 아니다(재설계 C-9, 사용자 결정
# 2026-10-12 — 카드 원문은 앱 DB 에 복제하되 박스 밖으로는 판정당 인용 200자만 나간다). tests/test_store.py 의 표 규약이 같이 읽는다.
LOCAL_ONLY_TABLES: frozenset[str] = frozenset({"rr_card_packs"})


def _table_order() -> tuple[str, ...]:
    """plan §5.2.2 A→H 표 순서 — MIGRATIONS 의 DDL 문장에 나온 차례 그대로다(별도 하드코딩 목록을 두지 않는다).
    박스 지역 표(LOCAL_ONLY_TABLES)는 뺀다."""
    out: list[str] = []
    for _version, statements in MIGRATIONS:
        for sql in statements:
            hit = _CREATE_TABLE_RE.search(sql)
            if hit is not None and hit.group(1) not in out and hit.group(1) not in LOCAL_ONLY_TABLES:
                out.append(hit.group(1))
    return tuple(out)


TABLE_ORDER: tuple[str, ...] = _table_order()

# owner_sub 열이 없는 공용 표 — 소유자 스코프가 없으므로 들여올 때 병합하지 않는다(남의 박스 규칙·지표가
# 이 박스 전역 판정을 갈아치우는 것을 막는다. rr_rules 는 state.load_active_rules 의 입력이다).
# rr_delta_priors 는 rr_delta_contrib 합으로만 채우는 파생 표라 들여올 이유도 없다(plan §4.7.1 '증분 += 없음').
GLOBAL_TABLES: tuple[str, ...] = ("rr_dim_vocab", "rr_delta_priors", "rr_rules", "rr_metrics")

# since 비교 열(앞의 열이 NULL 이면 뒤의 열을 본다). 빈 튜플은 시각 열이 없는 자식 표 — since 와 무관하게 전부 싣는다
# (부모보다 적게 싣는 쪽이 위험하고, import 는 행 단위 멱등이라 더 싣는 비용은 바이트뿐이다).
_SINCE_COLS: dict[str, tuple[str, ...]] = {
    "rr_projects": ("updated_at", "created_at"),
    "rr_sources": ("created_at",),
    "rr_snapshots": ("created_at",),
    "rr_snapshot_calls": ("started_at",),
    "rr_brief_calls": ("fetched_at",),
    "rr_ir_nodes": (),
    "rr_ir_edges": (),
    "rr_part_keys": ("updated_at", "created_at"),
    "rr_sameas": ("decided_at",),
    "rr_iface_ledger": ("decided_at",),
    "rr_dim_vocab": ("created_at",),
    "rr_dim_defs": ("updated_at", "created_at"),
    "rr_states": ("computed_at",),
    "rr_diffs": ("created_at",),
    "rr_diff_events": (),
    "rr_targets": ("updated_at", "created_at"),
    "rr_roster": ("frozen_at",),
    "rr_coverage": ("updated_at", "started_at"),
    "rr_panels": ("created_at",),
    "rr_jobs": ("updated_at", "created_at"),
    "rr_seat_opinions": ("created_at",),
    "rr_findings": ("updated_at", "created_at"),
    "rr_registry": ("updated_at",),
    "rr_claim_refs": (),
    "rr_character": ("updated_at", "created_at"),
    "rr_iface_alias": ("updated_at", "created_at"),
    "rr_delta_priors": ("updated_at",),
    "rr_delta_contrib": ("updated_at",),
    "rr_labels": ("labeled_at", "occurred_at"),
    "rr_patterns": ("updated_at", "created_at"),
    "rr_rules": ("created_at",),
    "rr_metrics": ("computed_at",),
    "rr_curation_queue": ("created_at",),
    "rr_id_map": ("ra_synced_at", "adh_synced_at"),
    # v4(재설계 M2) — 단위 둘은 한 번 쓰고 고치지 않는다. 셀·머리·판정은 고쳐 쓰는 행이라 updated_at 이 먼저다 — 판정은 rev·solo
    # 결과가 온 뒤 fwd 행의 is_effective·agree·split 을 고쳐 쓴다(그때 updated_at 을 올린다 — tests/rr/test_v4_rows.py 의 가드).
    "rr_unit_builds": ("built_at",),
    "rr_units": ("created_at",),
    "rr_expert_reports": ("updated_at", "created_at"),
    "rr_review_cells": ("updated_at", "created_at"),
    "rr_card_verdicts": ("updated_at", "created_at"),
    "rr_review_calls": ("started_at",),
    # v5(재설계 M3) — 쟁점·요약·근거 꾸러미 실호출은 고쳐 쓰는 행이라 updated_at 이 먼저다. 보고서 판은 한 번 쓰고 고치지 않는다.
    # 완결 확인은 취소할 때 행을 지우지 않고 revoked_at 을 적으므로 그것이 먼저다(취소가 since 반출에서 빠지지 않게).
    "rr_issues": ("updated_at", "created_at"),
    "rr_summaries": ("updated_at", "created_at"),
    "rr_reports": ("created_at",),
    "rr_close_acks": ("revoked_at", "ack_at"),
    "rr_unit_live": ("updated_at", "created_at"),
}


# 반출에 싣지 않는 열 — 패널의 엔진 결과 원문(v3)은 그 박스에서 다시 저장할 때만 쓴다. 받은 쪽은 다시 저장할 일이 없고,
# 그 원문에는 좌석이 받은 근거 글이 그대로 들어 있다(WP1 P-19). 들여오기는 빠진 열을 INSERT 에서 뺀다.
# 검토 호출의 result 프레임(v4)도 같다 — 카드 인용 원문이 판정당 상한 없이 들어 있다.
_EXPORT_SKIP_COLUMNS: dict[str, tuple[str, ...]] = {"rr_panels": ("result_gz",), "rr_review_calls": ("result_gz",)}

# 카드 인용은 판정당 이만큼만 박스 밖으로 나간다(사용자 결정 2026-10-12 — 재설계 M2.md 2절 · 5절 #18 · #21). 판정 행의 cq 는
# cq_chars 에, 인용 역색인의 card: 인용은 quote_chars 에, JSON 열 안의 인용은 그 항목 옆 `<칸>_chars` 에 원래 길이를 적는다.
# 이미 적힌 값은 그대로 둔다 — 들여온 행을 다시 내보내도 원래 길이가 남는다.
EXPORT_CQ_MAX = 200
_CARD_REVIEW = "card_review"
_QUOTED = re.compile("«([^»]*)»")


def _clip(item: dict, key: str) -> dict:
    """JSON 항목 하나의 인용 칸 — 넘으면 200자로 줄이고 `<칸>_chars` 에 원래 길이(이미 있으면 그대로)."""
    value = item.get(key)
    if not isinstance(value, str) or len(value) <= EXPORT_CQ_MAX:
        return item
    return {**item, key: value[:EXPORT_CQ_MAX], f"{key}_chars": item.get(f"{key}_chars") or len(value)}


def _clip_json(text: Any, fix) -> Any:
    try:
        value = json.loads(text) if isinstance(text, str) and text else None
    except ValueError:
        return text
    if value is None:
        return text
    fixed = fix(value)
    return text if fixed == value else json.dumps(fixed, ensure_ascii=False, sort_keys=True)


def clip_quoted(text: str) -> tuple[str, list[int]]:
    """글 안의 «» 인용(카드 대조 finding 의 근거 문장 — 카드 글을 그대로 옮겼다)을 하나마다 200자로 — (줄인 글, 줄인 인용의 원래
    길이들). 줄인 것이 없으면 (글 그대로, [])."""
    lengths: list[int] = []

    def cut(m: re.Match) -> str:
        if len(m.group(1)) <= EXPORT_CQ_MAX:
            return m.group(0)
        lengths.append(len(m.group(1)))
        return "«" + m.group(1)[:EXPORT_CQ_MAX] + "»"

    clipped = _QUOTED.sub(cut, text)
    return (clipped, lengths) if lengths else (text, [])


def _clip_finding(finding: Any) -> Any:
    """카드 대조 finding 의 카드 인용 — cites·_resolved_cites 의 card: 행 quote 와 warrant 의 «» 인용(원래 길이는 warrant_chars)."""
    if not isinstance(finding, dict):
        return finding
    out = dict(finding)
    for key in ("cites", "_resolved_cites"):
        if isinstance(out.get(key), list):
            out[key] = [_clip(c, "quote") if isinstance(c, dict) and str(c.get("ref") or "").startswith("card:") else c
                        for c in out[key]]
    warrant = out.get("warrant")
    if isinstance(warrant, str):
        clipped, lengths = clip_quoted(warrant)
        if lengths:
            out["warrant"] = clipped
            out["warrant_chars"] = out.get("warrant_chars") or lengths
    return out


def clip_queue_payload(payload: Any) -> Any:
    """카드 대조 마감이 올린 큐 항목(payload.source_kind='card_review')의 원문 칸(raw — 의심 문구가 걸린 finding 글)의 «» 카드 인용을
    200자로 줄이고 원래 길이를 raw_chars 에 적는다(R3B-3 — 큐도 박스 밖으로 나가는 카드 인용의 운반체다). 이미 적힌 값은 그대로다."""
    if not isinstance(payload, dict) or payload.get("source_kind") != _CARD_REVIEW or not isinstance(payload.get("raw"), str):
        return payload
    clipped, lengths = clip_quoted(payload["raw"])
    if not lengths:
        return payload
    return {**payload, "raw": clipped, "raw_chars": payload.get("raw_chars") or lengths}


def _clip_card_text(value: Any) -> Any:
    """JSON 값 안의 카드 인용을 판정당 200자로 — card: 인용 행의 quote, 판정 모양 항목의 cq, 글 안의 «» 인용(원래 길이는 옆 칸
    `<칸>_chars` — 이미 적힌 값은 그대로). 등록부 merged_json·쟁점 basis_json 은 걸음마다 칸이 자라므로(주장값·분포·쟁점 전 값·
    제기자 판정 — M3.md 4.2) 칸 이름이 아니라 모양으로 찾아 깊이와 상관없이 다 줄인다."""
    if isinstance(value, list):
        return [_clip_card_text(v) for v in value]
    if not isinstance(value, dict):
        return value
    out = {k: _clip_card_text(v) for k, v in value.items()}
    cut: set[str] = set()
    if str(out.get("ref") or "").startswith("card:") and isinstance(out.get("quote"), str):
        out, cut = _clip(out, "quote"), {"quote"}
    if isinstance(out.get("cq"), str):
        out, cut = _clip(out, "cq"), cut | {"cq"}
    for key in [k for k, v in out.items() if isinstance(v, str) and k not in cut and not k.endswith("_chars")]:
        clipped, lengths = clip_quoted(out[key])
        if lengths:
            out[key] = clipped
            out[f"{key}_chars"] = out.get(f"{key}_chars") or lengths
    return out


def _clip_extras(extras: Any) -> Any:
    """셀 extras_json — 카드 밖 줄의 인용(q, 배경 카드에서 옮긴 글)과 입력 결손 q1 의 카드 인용(cq — 그 줄에 실린 다툼의 cq 까지,
    반대 검토 MEDIUM 11)."""
    if not isinstance(extras, dict):
        return extras
    out = dict(extras)
    off = extras.get("offcard")
    if isinstance(off, dict) and isinstance(off.get("findings"), list):
        out["offcard"] = {**off, "findings": [_clip(f, "q") if isinstance(f, dict) else f for f in off["findings"]]}
    if isinstance(extras.get("noinput"), dict):
        out["noinput"] = _clip_card_text(extras["noinput"])
    return out


def _export_view(table: str, row: dict) -> dict:
    """반출 줄 하나 — 표마다 박스 밖으로 내보낼 모양으로 바꾼다(카드 인용 200자 — 판정 행 cq·조건별 대조, 셀의 카드 밖 인용,
    카드 대조 finding 의 인용·근거 문장, 인용 역색인의 card: 인용, 카드 대조 마감이 올린 큐 항목의 원문, 등록부·쟁점의 카드 인용.
    쟁점 패널의 브리프는 싣지 않는다)."""
    if table == "rr_card_verdicts":
        cq = row.get("cq")
        if isinstance(cq, str) and len(cq) > EXPORT_CQ_MAX:
            chars = row.get("cq_chars")
            row = {**row, "cq": cq[:EXPORT_CQ_MAX], "cq_chars": len(cq) if chars is None else chars}
        conds = _clip_json(row.get("conds_json"),
                           lambda v: [_clip(c, "cond") if isinstance(c, dict) else c for c in v] if isinstance(v, list)
                           else v)
        # 엔진이 단 다툼(contested_by)의 cq 도 같은 200자 규칙이다(반대 검토 MEDIUM 11 — checks 사본에 실린다)
        checks = _clip_json(row.get("checks_json"), _clip_card_text)
        if conds is not row.get("conds_json"):
            row = {**row, "conds_json": conds}
        return row if checks is row.get("checks_json") else {**row, "checks_json": checks}
    if table == "rr_review_cells":
        extras = _clip_json(row.get("extras_json"), _clip_extras)
        return row if extras is row.get("extras_json") else {**row, "extras_json": extras}
    if table == "rr_findings" and row.get("source_kind") in _CARD_TEXT_SOURCES:
        finding = _clip_json(row.get("finding_json"), _clip_finding)
        return row if finding is row.get("finding_json") else {**row, "finding_json": finding}
    if table == "rr_claim_refs" and row.get("ref_type") == "card":
        quote = row.get("quote")
        if isinstance(quote, str) and len(quote) > EXPORT_CQ_MAX:
            return {**row, "quote": quote[:EXPORT_CQ_MAX], "quote_chars": row.get("quote_chars") or len(quote)}
    if table == "rr_curation_queue":
        payload = _clip_json(row.get("payload_json"), clip_queue_payload)
        return row if payload is row.get("payload_json") else {**row, "payload_json": payload}
    # v5(재설계 M3) — 쟁점 패널이 받은 근거(I6)에는 카드 절 원문이 든다. 그 브리프는 박스 밖으로 내보내지 않는다(그 박스에서만
    # 쓴다 — 브리프 해시·항목 해시는 남는다). 등록부·쟁점의 카드 인용은 판정 행과 같은 200자 규칙이다(M2 #18·#21 을 넓힌다).
    if table == "rr_panels" and row.get("kind") == "issue":
        # 쟁점 패널의 결정문 · risk_spec 에는 좌석이 옮겨 적은 카드 절이 들 수 있다(review1 M6) — 같은 200자 규칙이다.
        out = {**row, "brief_gz": None}
        if isinstance(row.get("decision_text"), str):
            out["decision_text"] = clip_card_text_blob(row["decision_text"])
        out["risk_spec_json"] = _clip_json(row.get("risk_spec_json"), _clip_card_text)
        return out
    if table == "rr_reports" and isinstance(row.get("pages_gz"), dict):
        # 보고서 판의 쪽 — 요약 서기(LLM)의 서술은 «» 안에 실리고 행 글을 옮겨 적을 수 있다(review1 M6). «» 인용을 200자로.
        pages = _clip_pages_gz(_decode(row["pages_gz"]))
        return row if pages is None else {**row, "pages_gz": _encode(pages)}
    if table in ("rr_registry", "rr_issues"):
        column = "merged_json" if table == "rr_registry" else "basis_json"
        clipped = _clip_json(row.get(column), _clip_card_text)
        return row if clipped is row.get(column) else {**row, column: clipped}
    return row


# 카드 글을 옮겨 적을 수 있는 finding 출처 — 카드 대조(M2)와 쟁점 패널(M3 — 좌석이 쟁점 근거의 카드 절을 옮겨 적는다, review1 M6).
_CARD_TEXT_SOURCES: tuple[str, ...] = (_CARD_REVIEW, "issue_panel")
_JSON_QUOTE = re.compile(r'("quote"\s*:\s*")((?:[^"\\]|\\.)*)(")')


def clip_card_text_blob(text: str) -> str:
    """JSON 이 섞인 자유 글(쟁점 패널 결정문)의 카드 글 — «» 인용과 JSON 의 "quote" 글을 하나마다 200자로 줄이고 원래 길이를 그 자리에
    적는다('…(원래 N자)'). 줄일 것이 없으면 그대로."""
    clipped = _mark_lengths(text)

    def cut(m: re.Match) -> str:
        try:
            value = json.loads(f'"{m.group(2)}"')
        except ValueError:
            return m.group(0)
        if len(value) <= EXPORT_CQ_MAX:
            return m.group(0)
        short = json.dumps(value[:EXPORT_CQ_MAX] + f"…(원래 {len(value)}자)", ensure_ascii=False)[1:-1]
        return m.group(1) + short + m.group(3)

    return _JSON_QUOTE.sub(cut, clipped)


def _clip_strings(value: Any) -> Any:
    """JSON 값 안의 글마다 «» 인용을 200자로(원래 길이는 그 자리에 '…(원래 N자)')."""
    if isinstance(value, list):
        return [_clip_strings(v) for v in value]
    if isinstance(value, dict):
        return {k: _clip_strings(v) for k, v in value.items()}
    if isinstance(value, str):
        return _mark_lengths(value)
    return value


def _mark_lengths(text: str) -> str:
    def cut(m: re.Match) -> str:
        if len(m.group(1)) <= EXPORT_CQ_MAX:
            return m.group(0)
        return "«" + m.group(1)[:EXPORT_CQ_MAX] + f"…(원래 {len(m.group(1))}자)»"

    return _QUOTED.sub(cut, text)


def _clip_pages_gz(blob: bytes) -> bytes | None:
    """보고서 판 쪽(gzip JSON)의 «» 인용을 200자로 — 바뀐 것이 없으면 None."""
    import gzip  # noqa: PLC0415

    try:
        pages = json.loads(gzip.decompress(blob).decode("utf-8"))
    except (OSError, ValueError):
        return None
    clipped = _clip_strings(pages)
    if clipped == pages:
        return None
    return gzip.compress(json.dumps(clipped, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                         mtime=0)


def _human_rank(table: str, row: dict) -> int:
    """사람이 확정한 행이면 1, 자동·후보면 0.

    plan §5.2.5 (7)① 이 사람 확정으로 못박은 자리만 본다 — 원장 4표(rr_sameas · rr_iface_ledger · rr_part_keys ·
    rr_iface_alias) · rr_targets.verdict_final · rr_registry.status · 큐레이션 결정(rr_curation_queue).
    """
    decided_by = str(row.get("decided_by") or "")
    human_decision = bool(decided_by) and not decided_by.startswith("code:")
    if table == "rr_sameas" or table == "rr_iface_ledger":
        return 1 if human_decision else 0
    if table == "rr_part_keys":
        return 1 if human_decision and row.get("status") in ("confirmed", "merged") else 0
    if table == "rr_iface_alias":
        return 1 if row.get("source") == "human" else 0
    if table == "rr_targets":
        return 1 if row.get("verdict_final") else 0
    if table == "rr_registry":
        return 1 if row.get("status") in ("verified", "dismissed", "mitigated") else 0
    if table == "rr_curation_queue":
        return 1 if row.get("status") in ("done", "rejected") else 0
    return 0


# ---------------------------------------------------------------- 표 메타(PRAGMA 로 실제 스키마를 읽는다 — 'select *' 금지)
def _table_meta(store: RiskStore, table: str) -> tuple[list[str], list[str]]:
    """(컬럼 이름 cid 순, PK 컬럼 이름 pk 순). 표가 없으면 AppError E404."""
    rows = store.query(f"PRAGMA table_info({table})")
    if not rows:
        raise AppError("E404", f"표를 찾을 수 없습니다 — {table}.", 404)
    cols = [str(r["name"]) for r in rows]
    pks = [str(r["name"]) for r in sorted((r for r in rows if int(r["pk"]) > 0), key=lambda r: int(r["pk"]))]
    return cols, pks


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _encode(value: Any) -> Any:
    """sqlite 값 → JSON 값. BLOB(response_gz)만 {'__b64__': …} 로 감싼다."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__b64__": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__b64__"}:
        try:
            return base64.b64decode(str(value["__b64__"]).encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise AppError("E100", "BLOB(__b64__) 값을 디코드할 수 없습니다.", 422) from exc
    return value


def _json_line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


# ---------------------------------------------------------------- export
def read_origin(data_dir: Path | None = None) -> dict:
    """origin.json({hostname, app_version, schema_version, written_at}) — 없으면 현재 호스트로 채운다(main.py 가 기동마다 쓴다)."""
    root = config.settings.data_dir if data_dir is None else data_dir
    path = root / "origin.json"
    if path.is_file():
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(body, dict):
                return body
        except (OSError, ValueError):
            pass
    return {"hostname": socket.gethostname(), "app_version": config.APP_VERSION,
            "schema_version": None, "written_at": None}


def header_line(store: RiskStore, data_dir: Path | None = None) -> dict:
    """첫 줄 헤더 {schema_version, app_version, origin}(plan §8.2.3)."""
    return {"schema_version": store.schema_version(), "app_version": config.APP_VERSION,
            "origin": read_origin(data_dir)}


# 반출 기본 제외 — 회수된 과제와 코퍼스 제외 과제(plan §5.2.6 (ii)). `include_excluded=1` 로만 싣는다.
_PROJECT_SCOPE_SQL = ("project_id IN (SELECT id FROM rr_projects WHERE owner_sub = ?"
                      " AND status <> 'purged' AND (corpus_excluded = 0 OR ? = 1))")


def _select(store: RiskStore, table: str, owner_sub: str, since: int,
            include_excluded: bool = False) -> Iterator[dict]:
    """한 표의 소유자 행을 PK 순으로 흘린다.

    owner_sub 열이 없는 공용 표(rr_dim_vocab·rr_rules·rr_metrics·rr_delta_priors)는 소유자로 거를 수 없다 —
    그 중 visibility 열이 있는 표는 'org' 행만 싣는다(남의 사설 집계가 내 JSONL 에 따라 나가지 않게 한다).
    `project_id` 를 가진 표는 회수·코퍼스 제외 과제를 기본으로 뺀다(plan §5.2.6 (ii)).
    """
    cols, pks = _table_meta(store, table)
    cols = [c for c in cols if c not in _EXPORT_SKIP_COLUMNS.get(table, ())]
    sql = f"SELECT {', '.join(_quote(c) for c in cols)} FROM {table}"
    where: list[str] = []
    params: list[Any] = []
    if "owner_sub" in cols:
        where.append("owner_sub = ?")
        params.append(owner_sub)
    elif "visibility" in cols:
        where.append("visibility = 'org'")
    if table == "rr_projects":
        where.append("status <> 'purged'")
        if not include_excluded:
            where.append("corpus_excluded = 0")
    elif "project_id" in cols:
        where.append(_PROJECT_SCOPE_SQL)
        params += [owner_sub, 1 if include_excluded else 0]
    since_cols = [c for c in _SINCE_COLS.get(table, ()) if c in cols]
    if since > 0 and since_cols:
        expr = since_cols[0] if len(since_cols) == 1 else f"COALESCE({', '.join(since_cols)})"
        where.append(f"COALESCE({expr}, 0) >= ?")
        params.append(int(since))
    if where:
        sql += " WHERE " + " AND ".join(where)
    order = pks or cols
    sql += " ORDER BY " + ", ".join(_quote(c) for c in order)
    for row in store.query(sql, tuple(params)):
        yield _export_view(table, {c: _encode(row[c]) for c in cols})


def iter_lines(store: RiskStore, owner_sub: str, since: int = 0, data_dir: Path | None = None,
               include_excluded: bool = False) -> Iterator[str]:
    """JSONL 한 줄씩 — 첫 줄 헤더, 이어서 §5.2.2 A→H 표 순서로 {"table", "row"} 줄."""
    yield _json_line(header_line(store, data_dir))
    for table in TABLE_ORDER:
        for row in _select(store, table, owner_sub, since, include_excluded):
            yield _json_line({"table": table, "row": row})


def classification_max(store: RiskStore, owner_sub: str, include_excluded: bool = False) -> str:
    """이 반출에 든 과제의 최고 등급 — `X-Risk-Classification-Max` 헤더 값(plan §0.6 '데이터 등급·반출')."""
    sql = ("SELECT COUNT(*) AS n FROM rr_projects WHERE owner_sub = ? AND status <> 'purged'"
           " AND classification = 'confidential'")
    if not include_excluded:
        sql += " AND corpus_excluded = 0"
    row = store.query_one(sql, (owner_sub,))
    return "confidential" if row is not None and int(row["n"] or 0) > 0 else "internal"


def purge_old_exports(data_dir: Path | None = None, retain_days: int | None = None, now: int | None = None) -> int:
    """`risk_export_retain_days` 보다 오래된 exports/*.jsonl 을 지운다(지운 개수). 0 이하면 정리하지 않는다."""
    root = config.settings.data_dir if data_dir is None else data_dir
    days = config.settings.risk_export_retain_days if retain_days is None else retain_days
    if days <= 0:
        return 0
    out_dir = root / EXPORTS_DIRNAME
    if not out_dir.is_dir():
        return 0
    cutoff = (int(time.time()) if now is None else now) - days * 86400
    removed = 0
    for path in out_dir.glob("*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:                            # 정리 실패는 비치명적이다(반출 자체를 막지 않는다).
            continue
    return removed


def write_export_file(store: RiskStore, owner_sub: str, since: int = 0, data_dir: Path | None = None,
                      include_excluded: bool = False) -> Path:
    """같은 내용을 $HEAX_DATA_DIR/exports/<ts>.jsonl 에 0600 으로 남기고 그 경로를 돌려준다(plan §5.2.5 (1)).

    사본은 평문이라 모드를 0600 으로 고정하고, 같은 함수 끝에서 보존기간이 지난 사본을 지운다.
    """
    import os                                      # noqa: PLC0415 — 0600 생성에만 쓴다.

    root = config.settings.data_dir if data_dir is None else data_dir
    out_dir = root / EXPORTS_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    path = out_dir / f"{ts}.jsonl"
    seq = 1
    while path.exists():                          # 같은 초에 두 번 부르면 뒤 호출이 앞 파일을 지우지 않게 한다.
        path = out_dir / f"{ts}-{seq}.jsonl"
        seq += 1
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for line in iter_lines(store, owner_sub, since, data_dir, include_excluded):
            fh.write(line)
    purge_old_exports(data_dir)
    return path


# ---------------------------------------------------------------- import
def _parse(text: str) -> tuple[dict, list[tuple[str, dict]]]:
    """JSONL 본문 → (헤더, [(table, row)…]). 빈 줄은 건너뛴다."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise AppError("E100", "본문이 비어 있습니다 — 첫 줄 헤더가 필요합니다(plan §8.2.3).", 422)
    try:
        head = json.loads(lines[0])
    except ValueError as exc:
        raise AppError("E100", "첫 줄이 JSON 헤더가 아닙니다.", 422) from exc
    if not isinstance(head, dict) or "schema_version" not in head:
        raise AppError("E100", "헤더에 schema_version 이 없습니다.", 422)
    rows: list[tuple[str, dict]] = []
    for no, raw in enumerate(lines[1:], start=2):
        try:
            item = json.loads(raw)
        except ValueError as exc:
            raise AppError("E100", f"{no} 번째 줄이 JSON 이 아닙니다.", 422) from exc
        if not isinstance(item, dict) or not isinstance(item.get("row"), dict) or not isinstance(item.get("table"), str):
            raise AppError("E100", f"{no} 번째 줄이 {{table, row}} 형식이 아닙니다.", 422)
        rows.append((item["table"], item["row"]))
    return head, rows


def _key_of(row: dict, pks: list[str]) -> str:
    return "|".join("" if row.get(c) is None else str(row.get(c)) for c in pks)


def _diff_cols(local: dict, incoming: dict, cols: list[str]) -> list[str]:
    return [c for c in cols if _encode(local.get(c)) != incoming.get(c, None)]


def import_jsonl(store: RiskStore, owner_sub: str, text: str) -> dict:
    """JSONL 을 병합한다 — {inserted, merged, skipped, skipped_global, recomputed_targets, conflicts[]}.

    거절(둘 다 409) — 헤더 schema_version 이 PRAGMA user_version 과 다르면 `schema_mismatch`,
    남의 owner_sub 행이 섞여 있으면 `owner_mismatch`(박스 간 이동은 자기 행만 옮긴다, plan §8.2.3 '(소유자 행만)').
    병합(plan §5.2.5 (7)④·§4.7.1) — 없으면 insert, 같으면 skip, 사람 확정이 자동을 이기고,
    양쪽이 똑같이 사람 확정인데 값이 다르면 건너뛰고 conflicts[] 에 적는다(마지막 쓰기 승리 없음).
    조회·UPDATE 는 PK 가 아니라 (PK + 호출자 owner_sub) 로 건다 — PK 만으로 걸면 본문 owner_sub 만 자기 것으로
    적어 남의 행을 통째로 덮거나(권한 상승) 충돌 응답으로 읽어낼 수 있다. 소유자가 다른 같은 PK 는
    `owner_conflict`, UNIQUE 만 겹치는 새 행은 `unique_conflict` 로 그 줄만 눕히고 나머지는 계속 병합한다.
    """
    head, items = _parse(text)
    local_version = store.schema_version()
    if head.get("schema_version") != local_version:
        raise AppError("schema_mismatch",
                       f"스키마 버전이 다릅니다 — 본문 {head.get('schema_version')!r}, 이 박스 {local_version}."
                       " 양쪽 앱을 같은 SIF 로 올린 뒤 다시 시도하세요.", 409)

    meta: dict[str, tuple[list[str], list[str]]] = {}
    for table, row in items:
        if table not in TABLE_ORDER:
            raise AppError("E100", f"알 수 없는 표입니다 — {table}.", 422)
        if table not in meta:
            meta[table] = _table_meta(store, table)
        cols = meta[table][0]
        if "owner_sub" in cols and str(row.get("owner_sub") or "") != owner_sub:
            raise AppError("owner_mismatch",
                           f"다른 소유자의 행이 들어 있습니다 — {table}.owner_sub={row.get('owner_sub')!r}.", 409)

    inserted = merged = skipped = skipped_global = 0
    conflicts: list[dict] = []
    touched_targets: set[str] = set()
    with store.tx():
        for table, row in items:
            cols, pks = meta[table]
            if "owner_sub" not in cols:            # 공용 표는 병합하지 않는다(GLOBAL_TABLES 주석 참조).
                skipped_global += 1
                continue
            if not pks:                            # v1 DDL 의 rr_* 는 전부 PK 가 있다 — 없으면 병합 키를 정할 수 없다.
                raise AppError("E300", f"{table} 에 기본키가 없어 병합할 수 없습니다.", 500)
            unknown = [c for c in row if c not in cols]
            if unknown:
                raise AppError("E100", f"{table} 에 없는 열입니다 — {', '.join(sorted(unknown))}.", 422)
            values = {c: _decode(row.get(c)) for c in cols}
            pk_where = " AND ".join(f"{_quote(c)} = ?" for c in pks)
            where = pk_where + " AND owner_sub = ?"
            key_params = tuple(values[c] for c in pks) + (owner_sub,)
            found = store.query_one(
                f"SELECT {', '.join(_quote(c) for c in cols)} FROM {table} WHERE {where}", key_params,
            )
            if found is None:
                other = store.query_one(f"SELECT owner_sub FROM {table} WHERE {pk_where}",
                                        tuple(values[c] for c in pks))
                if other is not None:              # PK 는 같은데 주인이 다르다 — 값은 한 글자도 흘리지 않는다.
                    skipped += 1
                    conflicts.append({"table": table, "key": _key_of(row, pks), "reason": "owner_conflict"})
                    continue
                # 본문에 없는 열은 INSERT 에서 뺀다 — 명시적 NULL 을 넣으면 NOT NULL DEFAULT 열(classification·
                # lifecycle·status·mcp_visibility …)이 DEFAULT 를 못 받고 IntegrityError 로 눕는다. 내보내기는
                # 언제나 전 열을 싣지만 손으로 만든 줄은 부분 열이라 이 갈래가 필요하다.
                given = [c for c in cols if c in row]
                try:
                    store.execute(
                        f"INSERT INTO {table}({', '.join(_quote(c) for c in given)})"
                        f" VALUES ({', '.join('?' for _ in given)})",
                        tuple(values[c] for c in given),
                    )
                except sqlite3.IntegrityError:
                    # PK 는 다른데 UNIQUE 만 겹치는 행(두 박스가 같은 과제를 각자 만든 경우) — 그 줄만 눕힌다.
                    skipped += 1
                    conflicts.append({"table": table, "key": _key_of(row, pks), "reason": "unique_conflict"})
                    continue
                inserted += 1
                if table == "rr_findings":
                    touched_targets.add(str(values.get("target_key") or ""))
                continue
            local = dict(found)
            changed = _diff_cols(local, row, cols)
            if not changed:
                skipped += 1
                continue
            local_rank, incoming_rank = _human_rank(table, local), _human_rank(table, row)
            if incoming_rank > local_rank:
                # owner_sub 는 병합으로 바뀌지 않는다(소유자 이전은 이관의 일이 아니다).
                assign = [c for c in cols if c not in pks and c != "owner_sub"]
                store.execute(
                    f"UPDATE {table} SET {', '.join(f'{_quote(c)} = ?' for c in assign)} WHERE {where}",
                    tuple([values[c] for c in assign] + list(key_params)),
                )
                merged += 1
                if table == "rr_findings":
                    touched_targets.add(str(values.get("target_key") or ""))
                continue
            skipped += 1
            if incoming_rank == local_rank and local_rank > 0:
                conflicts.append({
                    "table": table, "key": _key_of(row, pks),
                    "local": {c: _encode(local.get(c)) for c in changed},
                    "incoming": {c: row.get(c) for c in changed},
                })

    # §5.2.5 (5) — import 는 별도 병합 규칙을 두지 않고 §4.7.1 등록부 병합을 그대로 재사용한다.
    # merge 는 멱등이라 커밋 뒤 타깃마다 한 번만 부르면 rr_registry·rr_delta_contrib·rr_delta_priors 가 다시 맞는다.
    recomputed = 0
    for target_key in sorted(t for t in touched_targets if t):
        from app import registry as registry_module  # noqa: PLC0415 — 순환 임포트를 피하려 지연 임포트한다.

        registry_module.merge(store, target_key, owner_sub=owner_sub)
        recomputed += 1
    return {"inserted": inserted, "merged": merged, "skipped": skipped, "skipped_global": skipped_global,
            "recomputed_targets": recomputed, "conflicts": conflicts}


def row_digest(store: RiskStore, owner_sub: str) -> dict[str, tuple[int, str]]:
    """표별 (행 수, 행 내용 sha256) — 왕복 검증용. 시각 열까지 그대로 비교한다."""
    out: dict[str, tuple[int, str]] = {}
    for table in TABLE_ORDER:
        digest = hashlib.sha256()
        count = 0
        for row in _select(store, table, owner_sub, 0):
            digest.update(_json_line({"table": table, "row": row}).encode("utf-8"))
            count += 1
        out[table] = (count, digest.hexdigest())
    return out


__all__ = ["TABLE_ORDER", "GLOBAL_TABLES", "LOCAL_ONLY_TABLES", "EXPORT_CQ_MAX", "header_line", "iter_lines",
           "write_export_file", "import_jsonl", "row_digest", "read_origin", "EXPORTS_DIRNAME"]
