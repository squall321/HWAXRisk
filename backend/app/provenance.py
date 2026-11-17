# 원천의 출처 표지(RK-06) — 스냅샷 · 원천 카드가 실제로 가진 것(앱 키 · ref · 판 · 환경 · 개수)만 싣고, 모르는 칸은 '모름' 과 그 까닭, 판 · 개수 불일치 · 이른 사본 경고
"""HWAXPortal docs/request-1117 RK-06. 좌석이 파싱까지만 된 StepForge 사본을 읽고 MCAD 를 null 로 결론 냈고, 요소 id 가 겹친 DynaForge 덱은 부품을 말없이
떨어뜨렸으며(덱 요소 수 ≠ 읽은 요소 수), 옛 앱 키 · 빈 앱 키로 개발 박스를 읽을 수 있었다. 이 모듈은 그 판단에 쓸 표지를 응답에 싣는다.

원천은 셋뿐이다 — rr_sources(카드의 app_key · ref · probe), rr_snapshots(ir_json 의 sources — ref · stats · degraded · app_version, app_versions_json),
스냅샷 노드(ecad 보드 노드의 revision · dyna pid 노드 수). 지어내지 않는다 — 그 값을 돌려주는 도구를 앱 어댑터가 부르지 않으면 null 과
`unknown[칸]` 의 까닭이고, 그 앱이 무엇을 내줘야 하는지는 `needs` 에 적는다(2026-11-17 dev 소스 대조 — StepForge · KooRemapper).
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

# 그 앱이 내줘야 채워지는 칸(앱 어댑터가 부르는 도구가 지금 내지 않는다 — 11-17 dev 소스 대조).
NEEDS: tuple[dict, ...] = (
    {"app": "StepForge", "for": "mcad.stage",
     "ask": "GET /api/projects/{id} 에 stage(빈 과제 · 파일만 · 파싱까지 · 검출까지 · 덱까지)와 기계 낱말 stage_code(empty · files · parsed · "
            "detected · deck) — 지금은 list_projects · what_next · revision_history 만 낸다."},
    {"app": "StepForge", "for": "mcad.revision",
     "ask": "GET /api/projects/{id} 에 revision{rev_label, rev_seq, model_key, task_code, status} — 지금은 get_project_meta.revision 만 낸다."},
    {"app": "StepForge", "for": "mcad.env",
     "ask": "system_status 에 env(development · production) · instance · app · build — 지금은 status · version · data_root 뿐이다."},
    {"app": "DynaForge", "for": "dyna.elements_declared",
     "ask": "inspect_file meta 에 elements_declared(읽은 요소 줄 수)와 duplicate_element_ids{count, top} — 지금 elements 는 덮어쓴 뒤의 고유 id 수라 "
            "요소 id 충돌로 빠진 요소를 알 수 없다."},
    {"app": "DynaForge", "for": "dyna.deck_version",
     "ask": "inspect_file 에 덱 title(*TITLE) · sha256, report_summary 에 source_kfile{id, filename, sha256} — 지금 덱 판은 내지 않는다."},
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
    sql = ("SELECT s.id AS id, s.created_at AS created_at, s.ir_json AS ir_json, s.app_versions_json AS app_versions_json"
           " FROM rr_snapshots s JOIN rr_projects p ON p.id = s.project_id WHERE s.project_id = ? AND s.owner_sub = p.owner_sub")
    row = (store.query_one(sql + " AND s.id = ?", (project_id, snapshot_id)) if snapshot_id
           else store.query_one(sql + " ORDER BY s.created_at DESC, s.rowid DESC LIMIT 1", (project_id,)))
    if row is None:
        return None
    return {"id": row["id"], "created_at": row["created_at"], "ir": _loads(row["ir_json"], {}),
            "app_versions": _loads(row["app_versions_json"], {})}


def _warn(code: str, message: str, **evidence: Any) -> dict:
    return {"code": code, "message": message, "evidence": evidence}


def _mcad(card: Mapping | None, source: Mapping | None, version: Mapping, ir: Mapping, warnings: list, checks: list) -> dict:
    ref = dict((source or {}).get("ref") or (card or {}).get("ref") or {})
    stats = dict((source or {}).get("stats") or {})
    degraded = list((source or {}).get("degraded") or [])
    out: dict[str, Any] = {
        "attached": True, "app_key": (source or {}).get("app_key") or (card or {}).get("app_key"),
        "stepforge_project_id": ref.get("stepforge_project_id"), "project_name": ref.get("project_name"),
        "detect_job_id": ref.get("detect_job_id"), "app_version": version.get("version"),
        "stage": None, "revision": None, "env": env_word((version.get("extra") or {}).get("env")),
        "env_raw": (version.get("extra") or {}).get("env"),
        "signals": None if source is None else {"detect_absent": "detect_absent" in degraded, "interfaces": stats.get("interfaces"),
                                                "leaf_instances": stats.get("leaf_instances"), "degraded": degraded},
        "unknown": {"stage": "StepForge 가 앱이 부르는 도구(프로젝트 상세 · 트리 · 계면 · 시스템 상태)로 과제 단계를 내지 않는다 — 신호(signals)만 있다",
                    "revision": "StepForge 가 앱이 부르는 도구로 설계 판 이름을 내지 않는다(project_name 은 과제 이름이다)"},
    }
    if out["env"] == ENV_UNKNOWN:
        out["unknown"]["env"] = "StepForge system_status 가 환경 표지를 내지 않는다"
    if source is None:
        out["unknown"]["signals"] = "이 과제에 동결된 스냅샷이 없다 — 원천 카드의 ref 만 있다"
        checks.append({"check": "mcad_stage", "status": "unknown", "why": "스냅샷이 없다"})
        return out
    missing = dict(ir.get("missing") or {})
    if missing.get("mcad_capture_failed"):
        warnings.append(_warn("mcad_capture_failed", "MCAD 캡처의 필수 호출이 실패해 MCAD 노드 · 엣지가 없다 — 좌석이 MCAD 를 '없음' 으로 읽으면 안 된다.",
                              degraded=degraded))
    if "detect_absent" in degraded and not stats.get("interfaces"):
        warnings.append(_warn("mcad_early_stage", "StepForge 사본에 검출(detect) 흔적이 없고 계면이 0 이다 — 파싱까지만 된 사본일 수 있다. MCAD 를"
                              " '문제 없음' 이나 null 로 읽기 전에 그 과제의 검출 잡을 확인한다.",
                              detect_job_id=ref.get("detect_job_id"), interfaces=stats.get("interfaces")))
        checks.append({"check": "mcad_stage", "status": "warn", "why": "detect_absent · 계면 0"})
    else:
        checks.append({"check": "mcad_stage", "status": "unknown",
                       "why": "단계는 StepForge 가 내지 않는다 — 검출 흔적은 있다" if "detect_absent" not in degraded else "계면이 있다"})
    return out


def _dyna(card: Mapping | None, source: Mapping | None, result_card: Mapping | None, version: Mapping, nodes: list,
          warnings: list, checks: list) -> dict:
    ref = dict((source or {}).get("ref") or (card or {}).get("ref") or {})
    stats = dict((source or {}).get("stats") or {})
    app_key = (source or {}).get("app_key") or (card or {}).get("app_key")
    env_raw = (version.get("extra") or {}).get("env")
    env = env_word(env_raw)
    parts_read = sum(1 for n in nodes if n.get("domain") == "dyna" and n.get("kind") == "pid") if source is not None else None
    out: dict[str, Any] = {
        "attached": True, "app_key": app_key, "env": env, "env_raw": env_raw, "deck_file": ref.get("filename"), "deck_sha256": ref.get("sha256"),
        "deck_version": None, "session_id": ref.get("session_id"), "file_id": ref.get("file_id"), "app_version": version.get("version"),
        "elements_read": stats.get("elements"), "elements_declared": None, "parts_declared": stats.get("parts"), "parts_read": parts_read,
        "report_ids": list(((result_card or {}).get("ref") or {}).get("report_ids") or []) or None,
        "unknown": {"elements_declared": "DynaForge 가 덱에 적힌 요소 수를 따로 내지 않는다 — elements 는 같은 id 를 덮어쓴 뒤의 고유 수다",
                    "deck_version": "DynaForge 가 덱 판(title · 개정)을 내지 않는다"},
    }
    if source is None:
        out["unknown"]["elements_read"] = "이 과제에 동결된 스냅샷이 없다"
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
    checks.append({"check": "deck_elements", "status": "unknown", "why": out["unknown"]["elements_declared"]})
    declared, read = out["parts_declared"], parts_read
    if isinstance(declared, int) and isinstance(read, int) and declared > read:
        warnings.append(_warn("dyna_parts_without_elements", f"덱의 파트 {declared}개 가운데 요소가 있는 파트는 {read}개다 — 요소가 없는 파트(요소 id 충돌로"
                              " 덮였거나 빈 카드)는 IR 에 없다.", parts_declared=declared, parts_read=read))
        checks.append({"check": "dyna_parts", "status": "warn", "why": f"{declared} > {read}"})
    elif isinstance(declared, int) and isinstance(read, int):
        checks.append({"check": "dyna_parts", "status": "ok", "why": f"{declared} = {read}"})
    else:
        checks.append({"check": "dyna_parts", "status": "unknown", "why": "스냅샷이 없거나 파트 수가 없다"})
    return out


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
                            warnings, checks)
    if "ecad" in cards or "ecad" in sources:
        out["ecad"] = _ecad(cards.get("ecad"), sources.get("ecad"), nodes)
    mcad_rev = (out.get("mcad") or {}).get("revision")
    dyna_rev = (out.get("dyna") or {}).get("deck_version")
    if out["mcad"].get("attached") and out["dyna"].get("attached"):
        if mcad_rev is None or dyna_rev is None:
            checks.append({"check": "revision_match", "status": "unknown",
                           "why": "MCAD 판 · 덱 판을 원천 앱이 내지 않는다 — 두 판이 같은지 잴 수 없다"})
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
