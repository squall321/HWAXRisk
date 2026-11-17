# 원천의 출처 표지(RK-06) — 스냅샷 · 원천 카드가 실제로 가진 것(앱 키 · ref · 판 · 환경 · 개수)만 싣고, 모르는 칸은 '모름' 과 그 까닭, 판 · 개수 불일치 · 이른 사본 경고
"""HWAXPortal docs/request-1117 RK-06. 좌석이 파싱까지만 된 StepForge 사본을 읽고 MCAD 를 null 로 결론 냈고, 요소 id 가 겹친 DynaForge 덱은 부품을 말없이
떨어뜨렸으며(덱 요소 수 ≠ 읽은 요소 수), 옛 앱 키 · 빈 앱 키로 개발 박스를 읽을 수 있었다. 이 모듈은 그 판단에 쓸 표지를 응답에 싣는다.

원천은 셋뿐이다 — rr_sources(카드의 app_key · ref · probe), rr_snapshots(ir_json 의 sources — ref · stats · degraded · app_version · provenance,
app_versions_json), 스냅샷 노드(ecad 보드 노드의 revision · dyna pid 노드 수). 지어내지 않는다 — 그 값을 돌려주는 도구를 앱 어댑터가 부르지 않으면
null 과 `unknown[칸]` 의 까닭이고, 그 앱이 무엇을 내줘야 하는지는 `needs` 에 적는다(2026-11-17 dev 소스 대조 — StepForge · KooRemapper).

StepForge 는 D-706(main 93918cf1)부터 과제 상세에 단계(stage · stage_code) · 판(revision) · 같은 CAD 사본의 단계(copy_stage)를, system_status 에
app · build · env(dev | prod | null 과 env_why) · env_raw · instance 를 낸다. 캡처가 그것을 sources[mcad].provenance · app_version.extra 에 얼리고
이 모듈은 얼린 값만 읽는다(라이브 호출이 없다) — 그 판 전의 캡처 · 스냅샷은 unknown 과 까닭이다.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

# 옛 앱 키 → 지금 키(10-31 기록 — 옛 운영 사본 키는 사라졌고 지금 키는 env production 을 낸다). 앱 키는 게이트웨이 list_tool_apps 의 이름이다.
RETIRED_APP_KEYS: dict[str, str] = {"dynaforge-prod": "heax-kooremapper_mcp"}
# 환경 낱말은 게이트웨이(GW-05)의 이름 그대로 — dev · prod, 모르면 unknown(사용자 결정 11-17 D5). 원천 앱의 낱말(DynaForge system_status 의
# development · production)은 env_raw 에 그대로 둔다.
ENV_WORDS: dict[str, str] = {"dev": "dev", "development": "dev", "prod": "prod", "production": "prod"}
ENV_UNKNOWN = "unknown"
PRODUCTION_ENV = "prod"


def env_word(raw: Any) -> str:
    """원천 앱의 환경 낱말 → 게이트웨이 낱말(dev · prod) — 없거나 모르는 낱말이면 unknown."""
    return ENV_WORDS.get(str(raw).strip().lower(), ENV_UNKNOWN) if raw not in (None, "") else ENV_UNKNOWN

# 검출 전 단계(StepForge stage_code) — 이 단계의 사본은 계면 · 관계가 비었다(파싱까지만 된 사본의 함정).
EARLY_STAGE_CODES = frozenset({"empty", "files", "parsed"})
LATE_STAGE_CODES = frozenset({"detected", "deck"})
STEPFORGE_MARKS_FROM = "StepForge D-706(main 93918cf1)"

# 그 앱이 내줘야 채워지는 칸(앱 어댑터가 부르는 도구가 지금 내지 않는다 — 11-17 dev 소스 대조). StepForge 의 단계 · 판 · 환경(D-706)과 DynaForge 의
# 요소 id 충돌 · 빠진 파트 수 · 덱 지문(KooRemapper c37bd03 · DF-14)은 그 판이 낸다 — 그 전 판의 캡처는 각 칸의 unknown 까닭이 말한다(여기 싣지 않는다).
DYNAFORGE_MARKS_FROM = "KooRemapper DF-14(c37bd03 · 11-17 바이너리)"
NEEDS: tuple[dict, ...] = (
    {"app": "DynaForge", "for": "dyna.deck_version",
     "ask": "inspect_file 에 덱 title(*TITLE) · 개정, report_summary 에 source_kfile{id, filename, sha256} — 덱 지문(sha256)은 c37bd03 부터 내지만"
            " 덱 판(이름 · 개정)은 아직 내지 않는다."},
    {"app": "DynaForge", "for": "dyna.instance",
     "ask": "system_status 에 app_key · instance · build — env 는 이미 낸다."},
)


def _loads(raw: Any, default: Any) -> Any:
    try:
        value = json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _source_cards(store: Any, project_id: str) -> dict[str, dict]:
    """kind → 첫 원천 카드(캡처는 앞의 하나만 읽는다 — entry.next_step 노트와 같다). 과제 주인의 행만."""
    out: dict[str, dict] = {}
    for row in store.query(
            "SELECT s.kind AS kind, s.app_key AS app_key, s.ref_json AS ref_json, s.probe_json AS probe_json, s.probe_at AS probe_at"
            " FROM rr_sources s JOIN rr_projects p ON p.id = s.project_id WHERE s.project_id = ? AND s.owner_sub = p.owner_sub"
            " ORDER BY s.kind, s.id", (project_id,)):
        out.setdefault(row["kind"], {"app_key": row["app_key"], "ref": _loads(row["ref_json"], {}),
                                     "probe": _loads(row["probe_json"], {}), "probe_at": row["probe_at"]})
    return out


def _snapshot(store: Any, project_id: str, snapshot_id: str | None) -> dict | None:
    """스냅샷의 출처 칸만 — IR 원문(수 MB 일 수 있다)을 파이썬으로 다 풀지 않고 SQLite 가 sources · missing 만 꺼낸다. 노드는 rr_ir_nodes 에서 dyna pid ·
    ecad board 만 읽는다(반대 검토 L3 — 스냅샷 쪽을 받을 때마다 IR 원문 전부를 다시 풀었다). 비운 원문(폐기)은 빈 IR 이다."""
    sql = ("SELECT s.id AS id, s.created_at AS created_at, s.app_versions_json AS app_versions_json,"
           " CASE WHEN json_valid(s.ir_json) THEN json_extract(s.ir_json, '$.sources') END AS sources_json,"
           " CASE WHEN json_valid(s.ir_json) THEN json_extract(s.ir_json, '$.missing') END AS missing_json"
           " FROM rr_snapshots s JOIN rr_projects p ON p.id = s.project_id WHERE s.project_id = ? AND s.owner_sub = p.owner_sub")
    row = (store.query_one(sql + " AND s.id = ?", (project_id, snapshot_id)) if snapshot_id
           else store.query_one(sql + " ORDER BY s.created_at DESC, s.rowid DESC LIMIT 1", (project_id,)))
    if row is None:
        return None
    sources = _loads(row["sources_json"], [])
    ir = {"sources": sources, "missing": _loads(row["missing_json"], {})} if row["sources_json"] is not None else {}
    nodes: list[dict] = []
    if ir:
        nodes = [{"domain": r["source_kind"], "kind": r["kind"], "attrs": _loads(r["attrs_json"], {}) if r["kind"] == "board" else {}}
                 for r in store.query("SELECT kind, source_kind, attrs_json FROM rr_ir_nodes WHERE snapshot_id = ?"
                                      " AND ((source_kind = 'dyna' AND kind = 'pid') OR (source_kind = 'ecad' AND kind = 'board'))",
                                      (row["id"],))]
        ir["nodes"] = nodes
    return {"id": row["id"], "created_at": row["created_at"], "ir": ir, "app_versions": _loads(row["app_versions_json"], {})}


def _warn(code: str, message: str, **evidence: Any) -> dict:
    return {"code": code, "message": message, "evidence": evidence}


def _env_of(extra: Mapping) -> tuple[str, Any, str | None]:
    """(게이트웨이 환경 낱말, 원래 낱말, 앱이 댄 모르는 까닭) — 원래 낱말은 env_raw 가 있으면 그것(StepForge), 없으면 env 그대로(DynaForge)."""
    raw = extra.get("env_raw") if "env_raw" in extra else extra.get("env")
    word = env_word(extra.get("env"))
    if word == ENV_UNKNOWN and extra.get("env") in (None, "") and raw not in (None, ""):
        word = env_word(raw)
    return word, raw, extra.get("env_why") if isinstance(extra.get("env_why"), str) else None


def _mcad_marks(marks: Mapping | None, source: Mapping | None) -> tuple[dict, dict]:
    """얼린 단계 · 판 · 사본 단계와 비었을 때의 까닭 — (값, unknown)."""
    got = dict(marks or {})
    values = {"stage": got.get("stage"), "stage_code": got.get("stage_code"), "revision": got.get("revision"),
              "copy_stage": got.get("copy_stage"), "copy_stage_via": got.get("copy_stage_via")}
    unknown: dict[str, str] = {}
    if source is None:
        why = "이 과제에 동결된 스냅샷이 없다 — 원천 카드의 ref 만 있다"
    elif marks is None:
        why = f"이 스냅샷의 캡처는 단계 · 판 · 사본 단계를 얼리지 않았다({STEPFORGE_MARKS_FROM} 을 읽기 전의 캡처)"
    elif not got.get("detail_read"):
        why = "캡처가 StepForge 과제 상세(REST)를 읽지 못했다(MCP 만의 캡처이거나 상세 호출이 실패했다)"
    else:
        why = f"StepForge 과제 상세가 이 칸을 내지 않았다 — {STEPFORGE_MARKS_FROM} 전 판이다"
    for key in ("stage", "revision"):
        if values[key] is None:
            unknown[key] = why
    if values["stage"] is not None and values["stage_code"] not in EARLY_STAGE_CODES | LATE_STAGE_CODES:
        unknown["stage_code"] = f"모르는 단계 낱말 {values['stage_code']!r} — {' · '.join(sorted(EARLY_STAGE_CODES | LATE_STAGE_CODES))} 가 아니다"
    if values["copy_stage"] is None:
        # MCP 답은 더 진행된 사본이 있을 때만 사본 단계를 싣는다 — 과제 상세 없이 MCP 에 없으면 '더 진행된 사본이 없다' 일 수도 있다(모른다).
        unknown["copy_stage"] = (why if source is None or marks is None or got.get("detail_read")
                                 else "과제 상세를 못 읽었고 MCP 답에 사본 단계가 없다 — MCP 는 더 진행된 사본이 있을 때만 싣는다(없다는 뜻일 수도 있다)")
    return values, unknown


def _mcad(card: Mapping | None, source: Mapping | None, version: Mapping, ir: Mapping, warnings: list, checks: list) -> dict:
    ref = dict((source or {}).get("ref") or (card or {}).get("ref") or {})
    stats = dict((source or {}).get("stats") or {})
    degraded = list((source or {}).get("degraded") or [])
    extra = dict(version.get("extra") or {})
    env, env_raw, env_why = _env_of(extra)
    marks, unknown = _mcad_marks((source or {}).get("provenance") if source is not None else None, source)
    out: dict[str, Any] = {
        "attached": True, "app_key": (source or {}).get("app_key") or (card or {}).get("app_key"),
        "stepforge_project_id": ref.get("stepforge_project_id"), "project_name": ref.get("project_name"),
        "detect_job_id": ref.get("detect_job_id"), "app_version": version.get("version"),
        "stage": marks["stage"], "stage_code": marks["stage_code"], "revision": marks["revision"], "copy_stage": marks["copy_stage"],
        "env": env, "env_raw": env_raw, "instance": extra.get("instance"), "build": extra.get("build"),
        "signals": None if source is None else {"detect_absent": "detect_absent" in degraded, "interfaces": stats.get("interfaces"),
                                                "leaf_instances": stats.get("leaf_instances"), "degraded": degraded},
        "unknown": unknown,
    }
    if env == ENV_UNKNOWN:
        out["unknown"]["env"] = (f"StepForge 가 환경을 모른다고 답했다 — {env_why}" if env_why
                                 else f"StepForge 가 모르는 환경 낱말 {env_raw!r} 을 냈다(dev · prod 가 아니다)" if env_raw not in (None, "")
                                 else "이 스냅샷의 캡처가 StepForge 환경 표지를 남기지 않았다(system_status 를 못 읽었거나 env 를 내기 전 판)")
    if source is None:
        out["unknown"]["signals"] = "이 과제에 동결된 스냅샷이 없다 — 원천 카드의 ref 만 있다"
        checks.append({"check": "mcad_stage", "status": "unknown", "why": "스냅샷이 없다"})
        return out
    missing = dict(ir.get("missing") or {})
    if missing.get("mcad_capture_failed"):
        warnings.append(_warn("mcad_capture_failed", "MCAD 캡처의 필수 호출이 실패해 MCAD 노드 · 엣지가 없다 — 좌석이 MCAD 를 '없음' 으로 읽으면 안 된다.",
                              degraded=degraded))
    code = marks["stage_code"]
    if code in EARLY_STAGE_CODES:
        # 앱이 단계를 말했다 — 신호(검출 흔적 · 계면 수)보다 앞선다.
        warnings.append(_warn("mcad_early_stage", f"StepForge 가 이 과제를 '{marks['stage']}'({code}) 라 답했다 — 검출 전 사본이라 계면 · 관계가 비었다."
                              " MCAD 를 '문제 없음' 이나 null 로 읽기 전에 검출을 마친 사본인지 확인한다.",
                              stage=marks["stage"], stage_code=code, interfaces=stats.get("interfaces")))
        checks.append({"check": "mcad_stage", "status": "warn", "why": f"stage_code {code}"})
    elif code in LATE_STAGE_CODES:
        checks.append({"check": "mcad_stage", "status": "ok", "why": f"stage_code {code}"})
    elif "detect_absent" in degraded and not stats.get("interfaces"):
        warnings.append(_warn("mcad_early_stage", "StepForge 사본에 검출(detect) 흔적이 없고 계면이 0 이다 — 파싱까지만 된 사본일 수 있다. MCAD 를"
                              " '문제 없음' 이나 null 로 읽기 전에 그 과제의 검출 잡을 확인한다.",
                              detect_job_id=ref.get("detect_job_id"), interfaces=stats.get("interfaces")))
        checks.append({"check": "mcad_stage", "status": "warn", "why": "detect_absent · 계면 0"})
    else:
        checks.append({"check": "mcad_stage", "status": "unknown",
                       "why": out["unknown"].get("stage") or out["unknown"].get("stage_code") or "단계 낱말이 없다"})
    copy = marks["copy_stage"]
    if isinstance(copy, Mapping) and copy.get("more_advanced"):
        warnings.append(_warn("mcad_more_advanced_copy", f"같은 CAD 를 올린 StepForge 사본 {copy['more_advanced']} 이 이 과제보다 더 진행됐다 — 이 과제의 빈"
                              " 값(계면 · 관계 · 구조)은 그 단계를 안 돌린 탓일 수 있다. 그 사본으로 다시 캡처할지 사용자에게 묻는다.",
                              more_advanced=copy["more_advanced"], how_far=copy.get("how_far"), why=copy.get("why"),
                              via=marks["copy_stage_via"]))
        checks.append({"check": "mcad_copy", "status": "warn", "why": f"더 진행된 사본 {copy['more_advanced']}"})
    elif isinstance(copy, Mapping):
        checks.append({"check": "mcad_copy", "status": "ok", "why": copy.get("why") or "더 진행된 사본이 없다"})
    else:
        checks.append({"check": "mcad_copy", "status": "unknown", "why": out["unknown"]["copy_stage"]})
    return out


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _dyna(card: Mapping | None, source: Mapping | None, result_card: Mapping | None, version: Mapping, nodes: list,
          warnings: list, checks: list, result_source: Mapping | None = None) -> dict:
    ref = dict((source or {}).get("ref") or (card or {}).get("ref") or {})
    stats = dict((source or {}).get("stats") or {})
    app_key = (source or {}).get("app_key") or (card or {}).get("app_key")
    env_raw = (version.get("extra") or {}).get("env")
    env = env_word(env_raw)
    parts_read = sum(1 for n in nodes if n.get("domain") == "dyna" and n.get("kind") == "pid") if source is not None else None
    marks = (source or {}).get("provenance")
    collisions = _count((marks or {}).get("element_id_collisions"))
    parts_missing = _count((marks or {}).get("parts_missing"))
    elements_read = stats.get("elements")
    # 덱에 적힌 셸 · 솔리드 요소 수 = 읽은 고유 요소 + 같은 번호의 뒤 카드에 덮여 잃은 요소(빔은 리더가 양쪽 모두 세지 않는다 — KooRemapper DF-14).
    declared = elements_read + collisions if isinstance(elements_read, int) and not isinstance(elements_read, bool) and collisions is not None else None
    out: dict[str, Any] = {
        "attached": True, "app_key": app_key, "env": env, "env_raw": env_raw, "deck_file": ref.get("filename"), "deck_sha256": ref.get("sha256"),
        "deck_version": None, "session_id": ref.get("session_id"), "file_id": ref.get("file_id"), "app_version": version.get("version"),
        "elements_read": elements_read, "elements_declared": declared, "element_id_collisions": collisions, "parts_missing": parts_missing,
        "parts_declared": stats.get("parts"), "parts_read": parts_read,
        "report_ids": list(((result_card or {}).get("ref") or {}).get("report_ids") or []) or None,
        "unknown": {"deck_version": "DynaForge 가 덱 판(*TITLE · 개정)을 내지 않는다 — 덱 지문(deck_sha256)만 있다"},
    }
    if source is None:
        why = "이 과제에 동결된 스냅샷이 없다"
        out["unknown"]["elements_read"] = why
    elif marks is None:
        why = f"이 스냅샷의 캡처는 요소 id 충돌 수를 얼리지 않았다({DYNAFORGE_MARKS_FROM} 을 읽기 전의 캡처)"
    else:
        why = (f"DynaForge 가 이 파일의 요소 id 충돌 수를 내지 않았다 — 11-17 전에 올린 파일(옛 바이너리의 메타)이거나 {DYNAFORGE_MARKS_FROM} 전 판이다"
               "(0 이 아니라 모른다)")
    for key, value in (("element_id_collisions", collisions), ("parts_missing", parts_missing), ("elements_declared", declared)):
        if value is None:
            out["unknown"][key] = why
    if not out["deck_sha256"]:
        out["unknown"]["deck_sha256"] = ("동결된 스냅샷이 없다" if source is None
                                         else "캡처가 덱 지문을 얼리지 않았다(원천 ref 에 지문이 없었고 inspect_file 이 sha256 을 내기 전 판 — c37bd03)")
    if env == ENV_UNKNOWN:
        out["unknown"]["env"] = (("이 스냅샷의 캡처가 DynaForge 환경 표지를 남기지 않았다(system_status 를 못 읽었거나 env 를 받기 전 판의 캡처)"
                                  if env_raw in (None, "") else f"DynaForge 가 모르는 환경 낱말 {env_raw!r} 을 냈다(dev · prod 가 아니다)")
                                 if source is not None else "동결된 스냅샷이 없다")
    if not app_key:
        warnings.append(_warn("dyna_app_key_empty", "DynaForge 원천에 앱 키가 비었다 — 게이트웨이의 기본 백엔드로 갔고 개발 박스일 수 있다. 운영 앱 키를"
                              " 적은 원천으로 다시 붙인다.", app_key=app_key))
        checks.append({"check": "dyna_app_key", "status": "warn", "why": "빈 앱 키"})
    elif app_key in RETIRED_APP_KEYS:
        warnings.append(_warn("dyna_app_key_retired", f"DynaForge 앱 키 {app_key} 는 사라진 옛 키다 — 지금 키는 {RETIRED_APP_KEYS[app_key]} 다.",
                              app_key=app_key, current=RETIRED_APP_KEYS[app_key]))
        checks.append({"check": "dyna_app_key", "status": "warn", "why": "옛 키"})
    else:
        checks.append({"check": "dyna_app_key", "status": "ok", "why": app_key})
    if env == ENV_UNKNOWN:
        checks.append({"check": "dyna_env", "status": "unknown", "why": out["unknown"]["env"]})
    elif env != PRODUCTION_ENV:
        warnings.append(_warn("dyna_env_not_production", f"DynaForge 가 env={env} 라 답했다 — 운영이 아닌 박스의 덱을 읽었다.", env=env,
                              env_raw=env_raw))
        checks.append({"check": "dyna_env", "status": "warn", "why": env})
    else:
        checks.append({"check": "dyna_env", "status": "ok", "why": env})
    if collisions is None:
        checks.append({"check": "deck_elements", "status": "unknown", "why": out["unknown"]["element_id_collisions"]})
    elif collisions > 0:
        warnings.append(_warn("dyna_element_id_collisions", f"덱의 요소 정의 {collisions}개가 같은 번호의 뒤 카드에 덮여 사라졌다(읽은 요소 {elements_read} ·"
                              f" 덱에 적힌 요소 {declared}) — 그 요소 · 파트는 IR 에 없다. 덱의 요소 번호를 고친 뒤 다시 캡처한다.",
                              element_id_collisions=collisions, elements_read=elements_read, elements_declared=declared))
        checks.append({"check": "deck_elements", "status": "warn", "why": f"요소 id 충돌 {collisions}"})
    else:
        checks.append({"check": "deck_elements", "status": "ok", "why": f"요소 id 충돌 0 · 덱 요소 {declared}"})
    if parts_missing is None:
        checks.append({"check": "deck_parts_missing", "status": "unknown", "why": out["unknown"]["parts_missing"]})
    elif parts_missing > 0:
        warnings.append(_warn("dyna_parts_missing", f"덱의 파트 {parts_missing}개는 요소가 하나도 남지 않아 파트 목록에 없다(요소 id 충돌로 덮였다) — 좌석이 그"
                              " 파트를 '없음' 으로 읽으면 안 된다.", parts_missing=parts_missing, element_id_collisions=collisions))
        checks.append({"check": "deck_parts_missing", "status": "warn", "why": f"빠진 파트 {parts_missing}"})
    else:
        checks.append({"check": "deck_parts_missing", "status": "ok", "why": "빠진 파트 0"})
    declared, read = out["parts_declared"], parts_read
    if isinstance(declared, int) and isinstance(read, int) and declared > read:
        warnings.append(_warn("dyna_parts_without_elements", f"덱의 파트 {declared}개 가운데 요소가 있는 파트는 {read}개다 — 요소가 없는 파트(요소 id 충돌로"
                              " 덮였거나 빈 카드)는 IR 에 없다.", parts_declared=declared, parts_read=read))
        checks.append({"check": "dyna_parts", "status": "warn", "why": f"{declared} > {read}"})
    elif isinstance(declared, int) and isinstance(read, int):
        checks.append({"check": "dyna_parts", "status": "ok", "why": f"{declared} = {read}"})
    else:
        checks.append({"check": "dyna_parts", "status": "unknown", "why": "스냅샷이 없거나 파트 수가 없다"})
    if result_card is not None or result_source is not None:
        _report_env(out, result_source, warnings, checks)
    return out


def _report_env(out: dict, result_source: Mapping | None, warnings: list, checks: list) -> None:
    """리포트를 낸 서버의 환경(KooRemapper D5 — 리포트 답의 environment). 운영이 아닌 박스의 report_id 를 인용하면 경고다."""
    got = ((result_source or {}).get("provenance") or {}).get("report_environment")
    if result_source is None or not isinstance(got, Mapping) or not got:
        out["report_environment"] = None
        out["unknown"]["report_environment"] = ("동결된 결과층이 없다" if result_source is None
                                                else "캡처가 리포트 환경을 얼리지 않았다(리포트 답이 environment 를 내기 전 판 — c37bd03 — 이거나 옛 캡처)")
        checks.append({"check": "dyna_report_env", "status": "unknown", "why": out["unknown"]["report_environment"]})
        return
    words = {str(rid): env_word(word) for rid, word in got.items()}
    out["report_environment"] = words
    off = {rid: word for rid, word in words.items() if word != PRODUCTION_ENV}
    if off:
        warnings.append(_warn("dyna_report_env_not_production", "운영이 아닌 DynaForge 가 낸 리포트를 인용한다 — "
                              + " · ".join(f"{rid}={word}" for rid, word in off.items()), reports=off))
        checks.append({"check": "dyna_report_env", "status": "warn", "why": " · ".join(f"{rid}={word}" for rid, word in off.items())})
    else:
        checks.append({"check": "dyna_report_env", "status": "ok", "why": PRODUCTION_ENV})


def _ecad(card: Mapping | None, source: Mapping | None, nodes: list) -> dict:
    ref = dict((source or {}).get("ref") or {})
    board = next((n for n in nodes if n.get("domain") == "ecad" and n.get("kind") == "board"), None)
    attrs = dict((board or {}).get("attrs") or {})
    job_id = ref.get("board_id") or ((card or {}).get("ref") or {}).get("odb_job_id") or ((card or {}).get("ref") or {}).get("board_id")
    out = {"attached": True, "app_key": (source or {}).get("app_key") or (card or {}).get("app_key"), "job_id": job_id,
           "board_name": ref.get("name") or attrs.get("name"), "revision": attrs.get("revision"), "unknown": {}}
    if board is None:
        out["unknown"]["revision"] = "스냅샷에 보드 노드가 없다(동결 전이거나 보드를 못 읽었다)"
    elif out["revision"] is None:
        out["unknown"]["revision"] = "ODB 허브 find_job 이 이 보드의 revision 을 내지 않았다"
    return out


def project_provenance(store: Any, project_id: str, *, snapshot_id: str | None = None) -> dict:
    """과제 하나(스냅샷을 주면 그 스냅샷, 아니면 가장 새 스냅샷)의 출처 표지."""
    cards = _source_cards(store, project_id)
    snap = _snapshot(store, project_id, snapshot_id)
    ir = (snap or {}).get("ir") or {}
    sources = {s.get("kind"): s for s in ir.get("sources") or [] if isinstance(s, Mapping)}
    versions = (snap or {}).get("app_versions") or {}
    nodes = list(ir.get("nodes") or [])
    warnings: list[dict] = []
    checks: list[dict] = []
    out: dict[str, Any] = {"project_id": project_id, "snapshot_id": (snap or {}).get("id"), "snapshot_at": (snap or {}).get("created_at"),
                           "basis": "snapshot" if snap and ir else "source_cards"}
    if snap is not None and not ir:
        out["basis_note"] = "스냅샷 원문이 비었다(폐기된 과제) — 원천 카드만 본다"
    for kind in ("mcad", "dyna", "ecad"):
        if kind not in cards and kind not in sources:
            out[kind] = {"attached": False}
    if "mcad" in cards or "mcad" in sources:
        out["mcad"] = _mcad(cards.get("mcad"), sources.get("mcad"), dict(versions.get("mcad") or {}), ir, warnings, checks)
    if "dyna" in cards or "dyna" in sources:
        out["dyna"] = _dyna(cards.get("dyna"), sources.get("dyna"), cards.get("dyna_result"), dict(versions.get("dyna") or {}), nodes,
                            warnings, checks, result_source=sources.get("dyna_result"))
    if "ecad" in cards or "ecad" in sources:
        out["ecad"] = _ecad(cards.get("ecad"), sources.get("ecad"), nodes)
    # 판 대조는 두 쪽 다 값이 있을 때만 잰다 — MCAD 쪽은 정한 판의 이름(revision.decided 일 때 rev_label), 덱 쪽은 DynaForge 가 아직 덱 판을 내지 않는다.
    mcad_revision = (out.get("mcad") or {}).get("revision")
    mcad_rev = (mcad_revision.get("rev_label") or None) if isinstance(mcad_revision, Mapping) and mcad_revision.get("decided") else None
    dyna_rev = (out.get("dyna") or {}).get("deck_version")
    if out["mcad"].get("attached") and out["dyna"].get("attached"):
        if mcad_rev is None or dyna_rev is None:
            sides = [why for missing_side, why in (
                (mcad_rev is None, "MCAD 판을 모른다" + (" — StepForge 에서 판을 정하지 않았다(decided false)"
                                                     if isinstance(mcad_revision, Mapping) else " — StepForge 가 판을 내지 않았다")),
                (dyna_rev is None, "덱 판을 모른다 — DynaForge 가 덱 판을 내지 않는다")) if missing_side]
            checks.append({"check": "revision_match", "status": "unknown", "why": " · ".join(sides) + " — 두 판이 같은지 잴 수 없다"})
        elif mcad_rev != dyna_rev:
            warnings.append(_warn("revision_mismatch", f"MCAD 판 {mcad_rev} 와 덱 판 {dyna_rev} 이 다르다.", mcad=mcad_rev, dyna=dyna_rev))
            checks.append({"check": "revision_match", "status": "warn", "why": f"{mcad_rev} ≠ {dyna_rev}"})
        else:
            checks.append({"check": "revision_match", "status": "ok", "why": mcad_rev})
    out["warnings"] = warnings
    out["checks"] = checks
    attached = {k for k in ("mcad", "dyna") if out[k].get("attached")}
    out["needs"] = [dict(n) for n in NEEDS if n["for"].split(".")[0] in attached]
    return out


def target_provenance(store: Any, target_key: str) -> dict | None:
    """대상의 과제 · 스냅샷(snap 대상은 그 스냅샷, diff 대상은 비교의 뒤 스냅샷)의 출처 표지. 대상이 없으면 None."""
    row = store.query_one("SELECT kind, ref_id, project_id FROM rr_targets WHERE target_key = ?", (target_key,))
    if row is None:
        return None
    snapshot_id = row["ref_id"] if row["kind"] == "snap" else None
    if row["kind"] == "diff":
        diff = store.query_one("SELECT target_snapshot_id FROM rr_diffs WHERE id = ?", (row["ref_id"],))
        snapshot_id = diff["target_snapshot_id"] if diff is not None else None
    return project_provenance(store, row["project_id"], snapshot_id=snapshot_id)


def brief(full: Mapping[str, Any] | None) -> dict | None:
    """와이어가 모자랄 때의 짧은 꼴 — 경고 코드 · 검사 상태만 싣고 전부는 risk_get_provenance 로 받는다."""
    if full is None:
        return None
    return {"project_id": full.get("project_id"), "snapshot_id": full.get("snapshot_id"), "brief": True,
            "warnings": [w["code"] for w in full.get("warnings") or []],
            "checks": {c["check"]: c["status"] for c in full.get("checks") or []},
            "full": f"risk_get_provenance(project_id={full.get('project_id')!r}, snapshot_id={full.get('snapshot_id')!r})"}
