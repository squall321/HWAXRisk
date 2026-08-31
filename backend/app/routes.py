# REST 라우터 /api(plan §8.2.3 계약표 전부) — 신원은 Depends(identity.current), 쓰기는 익명 401·owner_sub 소유권, 본문 로직은 전부 모듈 함수 호출
from __future__ import annotations

import base64
import json
import sqlite3
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import brief as brief_module
from app import config, diff as diff_module
from app import export as export_module
from app import identity, ir_builder, narrative, planner, ra_client, runner, sameas, taxonomy
from app import roster as roster_module
from app import state as state_module
from app import registry as registry_module
from app.adapters import base as adapters_base
from app.adapters import registry as adapters_registry
from app.adapters.registry import list_adapters
from app.common import canonical_json, new_uuid, now_epoch, parse_ref, sha256_hex
from app.errors import AppError
from app.risk_store import get_store

router = APIRouter(prefix="/api")

PORTAL_TIMEOUT_S = 3.0
PAT_MIN_REMAINING_S = 86400
# 테스트가 httpx.MockTransport 를 꽂는 자리. None 이면 실제 네트워크.
_portal_transport: httpx.BaseTransport | None = None


class PortalPatBody(BaseModel):
    pat: str | None


def _pat_summary(row: dict | None) -> dict | None:
    """_user_credentials 행 → {registered, email, groups[], exp}. PAT 값은 싣지 않는다."""
    if row is None:
        return None
    try:
        groups = json.loads(row.get("pat_groups_json") or "[]")
    except ValueError:
        groups = []
    return {"registered": True, "email": row.get("pat_email"), "groups": groups, "exp": row.get("pat_exp")}


def _require_user(ident: identity.Identity) -> str:
    if ident.anonymous or not ident.email:
        raise AppError("unauthorized", "인증된 사용자만 호출할 수 있습니다.", 401)
    return ident.email


def _decode_jwt_payload(pat: str) -> dict:
    """서명 검증 없이 payload 만 디코드한다(서명 검증은 포털 몫 — 아래 /agent/conversations 호출이 대신한다)."""
    parts = pat.split(".")
    if len(parts) != 3:
        raise AppError("pat_invalid", "포털 PAT 형식이 아닙니다(JWT 3분절).", 422)
    try:
        segment = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(segment.encode("ascii")))
    except (ValueError, UnicodeDecodeError) as exc:
        raise AppError("pat_invalid", "포털 PAT payload 를 읽을 수 없습니다.", 422) from exc
    if not isinstance(payload, dict):
        raise AppError("pat_invalid", "포털 PAT payload 가 객체가 아닙니다.", 422)
    return payload


def _verify_with_portal(pat: str) -> None:
    url = f"{config.settings.portal_base.rstrip('/')}/agent/conversations?limit=1"
    try:
        with httpx.Client(transport=_portal_transport, timeout=PORTAL_TIMEOUT_S) as client:
            r = client.get(url, headers={"Authorization": f"Bearer {pat}"})
    except httpx.HTTPError as exc:
        raise AppError("pat_invalid", f"포털 검증 호출 실패({type(exc).__name__}).", 422) from exc
    if r.status_code != 200:
        raise AppError("pat_invalid", f"포털이 PAT 를 거부했습니다(HTTP {r.status_code}).", 422)


@router.get("/me")
def get_me(request: Request, ident: identity.Identity = Depends(identity.current)) -> dict:
    """{email, display_name, role, organization, anonymous, portal_pat|null, box{hostname, secrets_valid}}."""
    state = request.app.state
    payload = ident.to_dict()
    portal_pat = None
    # 박스 불일치(이관 직후)면 _user_credentials 전부 무효(plan §5.2.5 (5)).
    if not ident.anonymous and state.box_match:
        portal_pat = _pat_summary(get_store().get_credential(ident.email))
    payload["portal_pat"] = portal_pat
    payload["box"] = {"hostname": state.hostname, "secrets_valid": state.secrets_valid}
    return payload


@router.put("/me/portal-pat")
def put_portal_pat(body: PortalPatBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """사용자 포털 PAT 등록(러너 자격 (b)). null 은 삭제. 검증 순서 — email → aud/scope → exp → 포털 실호출."""
    owner_sub = _require_user(ident)
    store = get_store()
    if body.pat is None:
        store.delete_credential(owner_sub)
        return {"registered": False, "email": None, "groups": [], "exp": None}

    claims = _decode_jwt_payload(body.pat)
    email = str(claims.get("email") or "").strip().lower()
    if email != owner_sub:
        raise AppError("pat_email_mismatch", "PAT 의 email 이 현재 사용자와 다릅니다.", 422)
    aud = claims.get("aud")
    aud_list = aud if isinstance(aud, list) else [aud]
    if "mcp-gateway" not in aud_list or claims.get("scope") != "api":
        raise AppError("pat_audience", "PAT 의 aud 에 mcp-gateway 가 없거나 scope 가 api 가 아닙니다.", 422)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or exp - time.time() < PAT_MIN_REMAINING_S:
        raise AppError("pat_expiring", "PAT 만료까지 24 시간 미만입니다.", 422)
    _verify_with_portal(body.pat)

    groups = claims.get("groups") if isinstance(claims.get("groups"), list) else []
    store.upsert_credential(owner_sub, body.pat, claims.get("sub"), email, json.dumps(groups, ensure_ascii=False), int(exp))
    return {"registered": True, "email": email, "groups": groups, "exp": int(exp)}


@router.get("/meta/taxonomy")
def get_taxonomy() -> dict:
    return taxonomy.load_taxonomy()


@router.get("/meta/adapters")
def get_adapters() -> dict:
    """`{apps:[{app_key, kind, tools_ok, choices[]}]}`(plan §8.2.3·§8.2.4 ProjectPage 소스 카드).

    발견 로직(도구 확인·선택지 열거)은 P1 이라 지금은 `tools_ok=false`·`choices=[]` 로 채운다 — 키는 확정이다.
    """
    return {"apps": [
        {"app_key": a.get("app"), "kind": a.get("kind"), "status": a.get("status"),
         "tools_ok": a.get("status") == "ready", "choices": []}
        for a in list_adapters()
    ]}


@router.get("/meta/vocab")
def get_vocab() -> dict:
    return {"asset_version": taxonomy.ASSET_VERSION, "assets": taxonomy.vocab_index()}


@router.get("/meta/metrics")
def get_metrics(ident: identity.Identity = Depends(identity.current)) -> dict:
    """rr_metrics 행(소유자 + org 공개). 지표 계산은 §7.6 야간 잡의 몫이고 여기서는 읽기만 한다."""
    owner_sub = _require_user(ident)          # 다른 조회 경로와 같이 익명은 401 이다(heax 불통 익명 강등 방어).
    store = get_store()
    rows = store.query(
        "SELECT period, dimension, key, metric, value, n, computed_at, visibility FROM rr_metrics"
        " WHERE visibility = 'org' OR key = ? ORDER BY period DESC, dimension, key, metric LIMIT 500",
        (owner_sub,),
    )
    return {"metrics": [dict(r) for r in rows]}


# ================================================================ 공통 헬퍼
def _loads(raw: Any, default: Any) -> Any:
    try:
        value = json.loads(raw) if raw else default
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, type(default)) else default


def _not_implemented(what: str, reason: str) -> AppError:
    """모듈이 아직 없는 기능 — 501. 라우트가 대신 로직을 지어내지 않는다."""
    return AppError("not_implemented", f"{what} — {reason}", 501)


def _owned_row(sql: str, params: tuple, owner_sub: str, what: str) -> dict:
    """소유자 행 1건(없거나 남의 것이면 404 — 존재 여부를 흘리지 않는다)."""
    row = get_store().query_one(sql, params)
    if row is None or row["owner_sub"] != owner_sub:
        raise AppError("E404", f"{what} 를 찾을 수 없습니다.", 404)
    return dict(row)


def _project_row(project_id: str, owner_sub: str) -> dict:
    return _owned_row(
        "SELECT id, owner_sub, code, name, stage, predecessor_project_id, adh_team, adh_group,"
        " character_status, created_at, updated_at FROM rr_projects WHERE id = ?",
        (project_id,), owner_sub, f"과제({project_id})",
    )


def _snapshot_row(snapshot_id: str, owner_sub: str | None) -> dict:
    row = get_store().query_one(
        "SELECT id, owner_sub, project_id, ir_version, ir_hash, kinds_json, node_count, edge_count,"
        " missing_json, warnings_n, degraded, created_at FROM rr_snapshots WHERE id = ?",
        (snapshot_id,),
    )
    if row is None or (owner_sub is not None and row["owner_sub"] != owner_sub):
        raise AppError("E404", f"스냅샷을 찾을 수 없습니다 — {snapshot_id}.", 404)
    return dict(row)


def _target_row(target_key: str, owner_sub: str | None) -> dict:
    row = get_store().query_one(
        "SELECT target_key, owner_sub, kind, ref_id, project_id, base_project_id, ir_hash, level,"
        " close_level, verdict_candidate, verdict_final, verdict_note, external_sync_json,"
        " superseded_by, report_ids_json, roster_frozen_at, created_at FROM rr_targets WHERE target_key = ?",
        (target_key,),
    )
    if row is None or (owner_sub is not None and row["owner_sub"] != owner_sub):
        raise AppError("E404", f"타깃을 찾을 수 없습니다 — {target_key}.", 404)
    return dict(row)


def _panel_row(panel_id: str, owner_sub: str | None) -> dict:
    row = get_store().query_one(
        "SELECT id, target_key, owner_sub, panel_no, tier, seats_json, chair_template, modifiers_json,"
        " rounds, engine, tool_mode, conv_id, report_id, status, quality_json, model_json, budget_json,"
        " retry, created_at FROM rr_panels WHERE id = ?",
        (panel_id,),
    )
    if row is None or (owner_sub is not None and row["owner_sub"] != owner_sub):
        raise AppError("E404", f"패널을 찾을 수 없습니다 — {panel_id}.", 404)
    return dict(row)


# ================================================================ 과제(plan §8.2.3)
class ProjectBody(BaseModel):
    code: str = Field(max_length=40)
    name: str = Field(max_length=200)
    stage: str | None = None
    predecessor_project_id: str | None = None
    adh_scope: dict | None = None


@router.post("/projects")
def create_project(body: ProjectBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """rr_projects 1행. `UNIQUE(owner_sub, code)` 충돌은 409."""
    owner_sub = _require_user(ident)
    scope = body.adh_scope or {}
    now = now_epoch()
    project_id = new_uuid()
    try:
        get_store().execute(
            "INSERT INTO rr_projects(id, owner_sub, code, name, stage, predecessor_project_id, adh_team,"
            " adh_group, character_status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,'seed',?,?)",
            (project_id, owner_sub, body.code, body.name, body.stage, body.predecessor_project_id,
             scope.get("team"), scope.get("group"), now, now),
        )
    except sqlite3.IntegrityError as exc:
        raise AppError("E409", f"이미 있는 과제 코드입니다 — {body.code}.", 409) from exc
    return _project_row(project_id, owner_sub)


def _project_sources(project_id: str) -> list[dict]:
    rows = get_store().query(
        "SELECT id, kind, app_key, ref_json, ref_key, bridge_declared, probe_json, probe_at, adapter_version"
        " FROM rr_sources WHERE project_id = ? ORDER BY kind, id", (project_id,),
    )
    out = []
    for row in rows:
        probe = _loads(row["probe_json"], {})
        out.append({"id": row["id"], "kind": row["kind"], "app_key": row["app_key"],
                    "ref": _loads(row["ref_json"], {}), "bridge_declared": bool(row["bridge_declared"]),
                    "probe": probe, "probe_at": row["probe_at"],
                    "status": probe.get("status") or ("linked" if probe.get("reachable") else "unlinked")})
    return out


@router.get("/projects")
def list_projects(ident: identity.Identity = Depends(identity.current)) -> dict:
    """과제 카드 그리드의 원천 — 소스 상태·최근 스냅샷·열린 타깃·커버리지·level."""
    owner_sub = _require_user(ident)
    store = get_store()
    projects = []
    for row in store.query(
        "SELECT id, code, name, stage, created_at FROM rr_projects WHERE owner_sub = ? ORDER BY created_at DESC, id",
        (owner_sub,),
    ):
        last = store.query_one(
            "SELECT MAX(created_at) AS ts FROM rr_snapshots WHERE project_id = ?", (row["id"],))
        targets = [dict(t) for t in store.query(
            "SELECT target_key, level, created_at FROM rr_targets WHERE project_id = ? AND owner_sub = ?"
            " ORDER BY created_at DESC", (row["id"], owner_sub))]
        coverage_pct = None
        if targets:
            summary = planner.coverage_summary(store, targets[0]["target_key"])
            if summary["roster_size"]:
                coverage_pct = round(100.0 * summary["terminal_n"] / summary["roster_size"], 1)
        projects.append({
            "id": row["id"], "code": row["code"], "name": row["name"], "stage": row["stage"],
            "sources": [{"kind": s["kind"], "app_key": s["app_key"], "status": s["status"]}
                        for s in _project_sources(row["id"])],
            "last_snapshot_at": last["ts"] if last else None,
            "open_targets": sum(1 for t in targets if t["level"] != "C2(closed)"),
            "coverage_pct": coverage_pct,
            "level": targets[0]["level"] if targets else None,
        })
    return {"projects": projects}


@router.get("/projects/{project_id}")
def get_project(project_id: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """ProjectPage 한 화면 — 과제·소스·스냅샷 헤더·타깃 헤더·잡·성격 태그."""
    owner_sub = _require_user(ident)
    project = _project_row(project_id, owner_sub)
    store = get_store()
    snapshots = [dict(r) for r in store.query(
        "SELECT id, ir_version, ir_hash, kinds_json, node_count, edge_count, warnings_n, degraded, created_at"
        " FROM rr_snapshots WHERE project_id = ? ORDER BY created_at DESC, id", (project_id,))]
    targets = [dict(r) for r in store.query(
        "SELECT target_key, kind, ref_id, level, close_level, verdict_candidate, verdict_final, created_at"
        " FROM rr_targets WHERE project_id = ? AND owner_sub = ? ORDER BY created_at DESC",
        (project_id, owner_sub))]
    jobs = [dict(r) for r in store.query(
        "SELECT j.id AS id, j.target_key AS target_key, j.tier AS tier, j.state AS state,"
        " j.pause_reason AS pause_reason, j.panels_done AS panels_done, j.panels_total AS panels_total,"
        " j.error AS error, j.progress_json AS progress_json FROM rr_jobs j JOIN rr_targets t"
        " ON t.target_key = j.target_key WHERE t.project_id = ? AND j.owner_sub = ?"
        " ORDER BY j.created_at DESC LIMIT 50", (project_id, owner_sub))]
    tags = [dict(r) for r in store.query(
        "SELECT tag, COUNT(*) AS n FROM rr_character WHERE project_id = ? AND tag IS NOT NULL"
        " GROUP BY tag ORDER BY n DESC, tag LIMIT 10", (project_id,))]
    return {
        "project": project,
        "sources": _project_sources(project_id),
        "snapshots": snapshots,
        "targets": targets,
        "jobs": [{"id": j["id"], "target_key": j["target_key"], "tier": j["tier"], "state": j["state"],
                  "kind": "panel_batch", "error": j["error"],
                  "progress": {"done": j["panels_done"], "total": j["panels_total"],
                               **_loads(j["progress_json"], {})}} for j in jobs],
        "character_top_tags": tags,
    }


class SourceBody(BaseModel):
    kind: str
    app_key: str | None = None
    ref: dict = Field(default_factory=dict)
    bridge_declared: bool = False


SOURCE_KINDS = ("mcad", "dyna", "dyna_result", "ecad")


@router.post("/projects/{project_id}/sources")
def add_source(project_id: str, body: SourceBody,
               ident: identity.Identity = Depends(identity.current)) -> dict:
    """소스 카드 연결. probe 는 adapters/registry 가 아는 상태만 적는다(앱은 소스 앱에 쓰기를 하지 않는다)."""
    owner_sub = _require_user(ident)
    _project_row(project_id, owner_sub)
    if body.kind not in SOURCE_KINDS:
        raise AppError("E100", f"kind 는 {list(SOURCE_KINDS)} 중 하나여야 합니다 — {body.kind!r}.", 422)
    adapter = next((a for a in list_adapters() if a["kind"] == body.kind.split("_")[0]), None)
    probe = {
        "reachable": False,
        "detail": f"adapter={adapter['status']}" if adapter else "adapter_unknown",
        "capture_mode": None,
        "status": "linked" if adapter and adapter["status"] == "ready" else "unreachable",
    }
    ref_key = f"{body.kind}:{body.app_key or '-'}:{canonical_json(body.ref)}"
    now = now_epoch()
    get_store().execute(
        "INSERT INTO rr_sources(id, project_id, owner_sub, kind, app_key, ref_json, ref_key, bridge_declared,"
        " probe_json, probe_at, adapter_version, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(project_id, ref_key) DO UPDATE SET app_key=excluded.app_key,"
        " bridge_declared=excluded.bridge_declared, probe_json=excluded.probe_json, probe_at=excluded.probe_at",
        (new_uuid(), project_id, owner_sub, body.kind, body.app_key, canonical_json(body.ref), ref_key,
         1 if body.bridge_declared else 0, canonical_json(probe), now, adapter["status"] if adapter else None, now),
    )
    return {"ok": True, "probe": probe}


class SnapshotBody(BaseModel):
    label: str | None = None
    kinds: list[str] = Field(default_factory=list)
    report_ids: list[int] | None = None
    detect_result_file_id: str | None = None


@router.post("/projects/{project_id}/snapshots")
def create_snapshot(project_id: str, body: SnapshotBody,
                    ident: identity.Identity = Depends(identity.current)) -> dict:
    """스냅샷 동결 — 등록된 소스 카드를 어댑터가 읽고 ir_builder 가 IR 을 동결한다(plan §2.11.3).

    rr_jobs 는 타깃 패널 전용 표라 여기서는 백그라운드 잡을 만들지 않고 동기로 캡처한 뒤
    `{snapshot_id, ir_hash, reused, partial, blocked, gates_summary, degraded}` 를 그대로 돌려준다.
    """
    owner_sub = _require_user(ident)
    _project_row(project_id, owner_sub)
    store = get_store()
    # 만료 PAT 는 쓰지 않는다 — 값이 있기만 하면 쓰면 서비스 PAT 폴백이 죽어 게이트웨이 401 로 강등된다
    # (runner.resolve_credential·roster.credential 과 같은 규칙).
    credential = store.get_credential(owner_sub) or {}
    portal_pat = str(credential.get("portal_pat") or "") or None
    if int(credential.get("pat_exp") or 0) <= now_epoch() + runner.CREDENTIAL_MARGIN_S:
        portal_pat = None
    channels = adapters_registry.clients_from_settings(
        config.settings, config.load_secrets(config.settings.data_dir), portal_pat=portal_pat)
    principal = adapters_base.Principal(owner_sub=owner_sub, portal_pat=channels["portal_pat"],
                                        service_pat=channels["service_pat"])
    try:
        captured = adapters_registry.capture_all(
            sources=_project_sources(project_id), principal=principal, mcp_client=channels["mcp"],
            rest_client=channels["rest"], kinds=list(body.kinds) or None, report_ids=body.report_ids,
            detect_result_file_id=body.detect_result_file_id)
    finally:
        # 채널은 자기 httpx.Client 를 소유한다 — 닫지 않으면 스냅샷 요청마다 소켓이 샌다(roster.fetch_for_target 과 같은 처리).
        for channel in (channels["mcp"], channels["rest"]):
            if channel is not None:
                channel.close()
    prior = store.query_one(
        "SELECT id FROM rr_snapshots WHERE project_id = ? ORDER BY created_at DESC, id LIMIT 1", (project_id,))
    return ir_builder.freeze_snapshot(
        store, project_id=project_id, owner_sub=owner_sub, label=body.label or f"snap-{now_epoch()}",
        adapter_results=captured["results"], calls=captured["calls"],
        snapshot_id=captured["snapshot_id"], derived_from=prior["id"] if prior else None)


class DimBody(BaseModel):
    name: str
    kind: str = "other"
    unit: str | None = None
    extractor: str


# dims extractor 문법의 정본은 ir_builder 다 — 여기서는 그 정규식으로 형식만 검사한다(plan §2.8).
_DIM_EXTRACTOR_RES = (
    ir_builder._RE_CONST, ir_builder._RE_NODE_CK, ir_builder._RE_NODE_ASM, ir_builder._RE_EDGE_CK,
    ir_builder._RE_EDGE_NAME, ir_builder._RE_RESULT_CK, ir_builder._RE_OVERALL,
    ir_builder._RE_DERIVED, ir_builder._RE_AGG,
)
DIM_KINDS = ("overall", "thickness", "gap", "offset", "count", "param", "result", "other")


@router.post("/projects/{project_id}/dims")
def add_dim(project_id: str, body: DimBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """명명 치수 정의 1건. name 이 rr_dim_vocab 에 없으면 candidate 로 함께 등록한다."""
    owner_sub = _require_user(ident)
    _project_row(project_id, owner_sub)
    extractor = body.extractor.strip()
    if not any(rx.match(extractor) for rx in _DIM_EXTRACTOR_RES):
        raise AppError("E100", f"extractor 문법(plan §2.8)에 맞지 않습니다 — {extractor!r}.", 422)
    if body.kind not in DIM_KINDS:
        raise AppError("E100", f"kind 는 {list(DIM_KINDS)} 중 하나여야 합니다 — {body.kind!r}.", 422)
    now = now_epoch()
    store = get_store()
    with store.tx():
        store.execute(
            "INSERT OR IGNORE INTO rr_dim_vocab(name, kind, unit, description, vocab_version, created_by, created_at)"
            " VALUES (?,?,?,NULL,'candidate',?,?)", (body.name, body.kind, body.unit, owner_sub, now))
        store.execute(
            "INSERT INTO rr_dim_defs(project_id, name, owner_sub, extractor, created_by, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?) ON CONFLICT(project_id, name) DO UPDATE SET extractor=excluded.extractor,"
            " updated_at=excluded.updated_at", (project_id, body.name, owner_sub, extractor, owner_sub, now, now))
    row = store.query_one(
        "SELECT project_id, name, owner_sub, extractor, created_at, updated_at FROM rr_dim_defs"
        " WHERE project_id = ? AND name = ?", (project_id, body.name))
    vocab = store.query_one("SELECT name, kind, unit, vocab_version FROM rr_dim_vocab WHERE name = ?", (body.name,))
    return {**dict(row), "vocab": dict(vocab) if vocab else None}


class LedgerItem(BaseModel):
    pair_key: str
    kind_override: str | None = None
    status: str
    note: str | None = None


@router.put("/projects/{project_id}/iface-ledger")
def put_iface_ledger(project_id: str, body: list[LedgerItem],
                     ident: identity.Identity = Depends(identity.current)) -> dict:
    """계면 확정 원장(§2.10). 스냅샷은 바뀌지 않고 다음 동결이 이 원장을 흡수한다."""
    owner_sub = _require_user(ident)
    _project_row(project_id, owner_sub)
    now = now_epoch()
    store = get_store()
    with store.tx():
        for item in body:
            if item.status not in ("confirmed", "rejected", "manual"):
                raise AppError("E100", f"status 는 confirmed|rejected|manual 여야 합니다 — {item.status!r}.", 422)
            store.execute(
                "INSERT INTO rr_iface_ledger(project_id, pair_key, owner_sub, kind_override, status, note,"
                " decided_by, decided_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(project_id, pair_key) DO UPDATE SET"
                " kind_override=excluded.kind_override, status=excluded.status, note=excluded.note,"
                " decided_by=excluded.decided_by, decided_at=excluded.decided_at",
                (project_id, item.pair_key, owner_sub, item.kind_override, item.status, item.note, owner_sub, now))
    rows = store.query(
        "SELECT project_id, pair_key, kind_override, status, note, decided_by, decided_at"
        " FROM rr_iface_ledger WHERE project_id = ? ORDER BY pair_key", (project_id,))
    return {"ledger": [dict(r) for r in rows]}


# ================================================================ 스냅샷 조회
SNAPSHOT_PARTS = ("ir", "state", "nodes", "edges", "calls")


def snapshot_part(snapshot_id: str, part: str, *, owner_sub: str | None = None,
                  limit: int | None = None) -> dict:
    """`GET /api/snapshots/{id}?part=` 본체 — MCP `risk_get_snapshot` 과 같은 함수."""
    if part not in SNAPSHOT_PARTS:
        raise AppError("E100", f"part 는 {list(SNAPSHOT_PARTS)} 중 하나여야 합니다 — {part!r}.", 422)
    header = _snapshot_row(snapshot_id, owner_sub)
    store = get_store()
    if part == "ir":
        return ir_builder.load_ir(store, snapshot_id)
    if part == "state":
        saved = state_module.load_state(store, snapshot_id)
        if saved is None:
            raise AppError("E404", f"rr_state 가 없습니다 — {snapshot_id}.", 404)
        return saved
    if part == "calls":
        return {"snapshot_id": snapshot_id,
                "calls": ir_builder.load_calls(store, snapshot_id, include_response=False)}
    if part == "nodes":
        sql = ("SELECT nid, kind, source_kind, name, name_norm, ckey, dn, geom_fp, asm_key, material_norm,"
               " size_sorted_json, volume FROM rr_ir_nodes WHERE snapshot_id = ? ORDER BY nid")
        key = "nodes"
    else:
        sql = ("SELECT eid, kind, kind_family, a, b, ck_a, ck_b, subject_key, status, attrs_json"
               " FROM rr_ir_edges WHERE snapshot_id = ? ORDER BY eid")
        key = "edges"
    if limit is not None:
        rows = store.query(sql + " LIMIT ?", (snapshot_id, int(limit) + 1))
        truncated = len(rows) > int(limit)
        rows = rows[: int(limit)]
    else:
        rows = store.query(sql, (snapshot_id,))
        truncated = False
    items = []
    for row in rows:
        item = dict(row)
        if "size_sorted_json" in item:
            item["size_sorted"] = _loads(item.pop("size_sorted_json"), [])
        if "attrs_json" in item:
            item["attrs"] = _loads(item.pop("attrs_json"), {})
        items.append(item)
    return {"snapshot_id": snapshot_id, "ir_hash": header["ir_hash"], key: items, "truncated": truncated}


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: str, part: str = "ir",
                 ident: identity.Identity = Depends(identity.current)) -> dict:
    owner_sub = _require_user(ident)
    return snapshot_part(snapshot_id, part, owner_sub=owner_sub)


@router.get("/snapshots/{snapshot_id}/rule_hits")
def get_rule_hits(snapshot_id: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """규칙 적중 표(§3.2.6). rr_states 가 없으면 404."""
    owner_sub = _require_user(ident)
    _snapshot_row(snapshot_id, owner_sub)
    row = get_store().query_one(
        "SELECT rule_hits_json, rule_version FROM rr_states WHERE snapshot_id = ?", (snapshot_id,))
    if row is None:
        raise AppError("E404", f"rr_state 가 없습니다 — {snapshot_id}.", 404)
    return {"snapshot_id": snapshot_id, "rule_version": row["rule_version"],
            "rule_hits": _loads(row["rule_hits_json"], [])}


# ================================================================ same-as·원장
@router.get("/sameas")
def get_sameas(base: str = Query(...), target: str = Query(...),
               ident: identity.Identity = Depends(identity.current)) -> dict:
    """SameAsResolver 표(§2.6.4) — 자동 매칭·pending·conflict 를 사람이 볼 행으로 준다."""
    owner_sub = _require_user(ident)
    _snapshot_row(base, owner_sub)
    _snapshot_row(target, owner_sub)
    store = get_store()
    base_ir = ir_builder.load_ir(store, base)
    target_ir = ir_builder.load_ir(store, target)
    pair_key = "|".join(sorted([str(base_ir.get("project_id") or ""), str(target_ir.get("project_id") or "")]))
    links = sameas.resolve(
        list(base_ir.get("nodes") or []), list(target_ir.get("nodes") or []),
        list(base_ir.get("edges") or []), list(target_ir.get("edges") or []),
        "pair", sameas.load_ledger(store, "pair", pair_key, owner_sub),
    )
    rows = sameas.review_rows(links, list(base_ir.get("nodes") or []), list(target_ir.get("nodes") or []))
    target_state = state_module.load_state(store, target) or {}
    return {
        "pairs": rows,
        "pending_n": sum(1 for r in rows if r["status"] == "pending"),
        "G2": (target_state.get("gates") or {}).get("G2"),
    }


@router.post("/sameas/decide")
def post_sameas_decide(body: list[dict], ident: identity.Identity = Depends(identity.current)) -> dict:
    """same-as 확정과 ckey 원장 조작을 한 배열로 받는다(§2.6.2 7단계·§2.7.3)."""
    owner_sub = _require_user(ident)
    store = get_store()
    # 배열은 한 트랜잭션이다 — 3번째 항목이 404 인데 앞 두 결정만 커밋되는 반쪽 적용을 막는다(내부 tx 는 합류한다).
    with store.tx():
        results = [sameas.record_decision(store, item, owner_sub=owner_sub) for item in body]
    return {"updated": len(results), "results": results, "G2": None}


# ================================================================ diff
class DiffBody(BaseModel):
    base_snapshot_id: str
    target_snapshot_id: str


@router.post("/diffs")
def create_diff(body: DiffBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """3층 diff 생성. G6 차단은 409, 같은 쌍이 이미 있으면 저장된 것을 그대로 돌려준다."""
    owner_sub = _require_user(ident)
    result = diff_module.create_diff(get_store(), body.base_snapshot_id, body.target_snapshot_id,
                                     owner_sub=owner_sub)
    return {"diff_id": result["diff_id"], "counts": result.get("stats") or {},
            "comparability": result.get("comparability") or {}}


DIFF_PARTS = ("diff", "summary", "events")


def diff_part(diff_id: str, part: str, *, owner_sub: str | None = None, limit: int | None = None) -> dict:
    """`GET /api/diffs/{id}?part=` 본체 — MCP `risk_get_diff` 와 같은 함수."""
    if part not in DIFF_PARTS:
        raise AppError("E100", f"part 는 {list(DIFF_PARTS)} 중 하나여야 합니다 — {part!r}.", 422)
    # owner_sub 를 행에서 되읽어 되먹이지 않는다 — 그 우회는 소유권 검사를 통째로 무력화한다.
    payload = diff_module.get_diff(get_store(), diff_id, owner_sub=owner_sub or "", part=part)
    if part == "events" and limit is not None:
        events = payload.get("events") or []
        payload = {**payload, "events": events[: int(limit)], "truncated": len(events) > int(limit)}
    return payload


@router.get("/diffs/{diff_id}")
def get_diff(diff_id: str, part: str = "diff",
             ident: identity.Identity = Depends(identity.current)) -> dict:
    owner_sub = _require_user(ident)
    return diff_part(diff_id, part, owner_sub=owner_sub)


@router.get("/precedents")
def get_precedents(diff_id: str = Query(...), ident: identity.Identity = Depends(identity.current)) -> dict:
    """선례 패널(§5.7) — rr_delta_priors 수치와 같은 subject 의 등록부 행."""
    owner_sub = _require_user(ident)
    return brief_module.precedents(get_store(), diff_id, owner_sub=owner_sub)


# ================================================================ 타깃·로스터
def _ecad_absent(snapshot: dict) -> bool:
    """ECAD 부재 판정은 IR 이 계산한 missing.ecad_absent 다.

    kinds_json 으로 볼 수 없다 — capture_all 이 요청 kinds 와 무관하게 ecad 스텁 소스를 언제나 실어
    kinds_json 에는 'ecad' 가 늘 들어 있다(그때 missing.ecad_absent 는 True 다).
    """
    return bool(_loads(snapshot.get("missing_json"), {}).get("ecad_absent", True))


def _ecad_absent_for_target(store: Any, target: dict) -> bool:
    """타깃이 가리키는 스냅샷(diff 면 target_snapshot)의 missing.ecad_absent. 못 찾으면 부재로 본다."""
    snapshot_id = target["ref_id"]
    if target["kind"] == "diff":
        row = store.query_one("SELECT target_snapshot_id FROM rr_diffs WHERE id = ?", (target["ref_id"],))
        if row is None:
            return True
        snapshot_id = row["target_snapshot_id"]
    row = store.query_one("SELECT missing_json FROM rr_snapshots WHERE id = ?", (snapshot_id,))
    return True if row is None else _ecad_absent(dict(row))


class TargetBody(BaseModel):
    kind: str
    ref_id: str
    consent: bool = False
    # 로스터 원천 — `list_agents`+`recommend_agents` 결과를 호출자가 실어 준다(planner.freeze_roster 계약).
    agents: list[dict] | None = None


@router.post("/targets")
def create_target(body: TargetBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """심사 타깃 1건. principal_json 은 신원 스냅샷일 뿐 러너가 이것으로 PAT 를 발급하지 않는다(§6.7 3단계)."""
    owner_sub = _require_user(ident)
    if body.kind not in ("snap", "diff"):
        raise AppError("E100", f"kind 는 snap|diff 여야 합니다 — {body.kind!r}.", 422)
    if body.consent is not True:
        raise AppError("E100", "consent:true 가 필요합니다.", 422)
    store = get_store()
    blocked_snapshots: list[str] = []
    if body.kind == "snap":
        snapshot = _snapshot_row(body.ref_id, owner_sub)
        project_id, base_project_id, ir_hash = snapshot["project_id"], None, snapshot["ir_hash"]
        ecad_absent = _ecad_absent(snapshot)
        blocked_snapshots = [body.ref_id]
    else:
        row = store.query_one(
            "SELECT id, owner_sub, base_snapshot_id, target_snapshot_id, base_project_id, target_project_id"
            " FROM rr_diffs WHERE id = ?", (body.ref_id,))
        if row is None or row["owner_sub"] != owner_sub:
            raise AppError("E404", f"diff 를 찾을 수 없습니다 — {body.ref_id}.", 404)
        snapshot = _snapshot_row(row["target_snapshot_id"], owner_sub)
        project_id, base_project_id, ir_hash = row["target_project_id"], row["base_project_id"], snapshot["ir_hash"]
        ecad_absent = _ecad_absent(snapshot)
        blocked_snapshots = [row["base_snapshot_id"], row["target_snapshot_id"]]

    # G6(unit_scale) 차단 스냅샷 위에는 타깃을 열지 않는다(plan §3.2.2 G6 effect — diff 409 와 같은 형식).
    gates: dict = {}
    for role, sid in zip(("base", "target") if body.kind == "diff" else ("target",), blocked_snapshots):
        state = store.query_one(
            "SELECT blocked, gates_json FROM rr_states WHERE snapshot_id = ?", (sid,))
        if state is not None and state["blocked"]:
            gates[role] = (_loads(state["gates_json"], {}) or {}).get("G6")
    if gates:
        raise AppError("E409", f"게이트 G6 로 차단된 스냅샷입니다 — {canonical_json({'gates': gates})}.", 409)

    target_key = f"{body.kind}:{body.ref_id}"
    if store.query_one("SELECT target_key FROM rr_targets WHERE target_key = ?", (target_key,)) is not None:
        raise AppError("E409", f"이미 열린 타깃입니다 — {target_key}.", 409)
    now = now_epoch()
    roster = {"roster_size": 0, "deferred": 0, "frozen_at": None}
    # 로스터 원천 — 본문 agents 가 있으면 그것이 우선이고, 없으면 게이트웨이를 조회한다(자격이 없으면 unavailable).
    # 게이트웨이 호출은 트랜잭션 밖에서 끝낸다(DB 락을 네트워크 대기 동안 잡지 않는다).
    agents: list[dict] = [dict(a) for a in (body.agents or [])]
    roster_source = roster_module.SOURCE_BODY if agents else roster_module.SOURCE_UNAVAILABLE
    if not agents:
        fetched = roster_module.fetch_for_target(store, kind=body.kind, ref_id=body.ref_id,
                                                 owner_sub=owner_sub)
        agents, roster_source = fetched["agents"], fetched["source"]
    # 타깃 행과 로스터 고정은 한 트랜잭션이다 — 고정이 실패하면 roster_size 0 인 타깃만 남아 재생성이 409 로 막힌다.
    with store.tx():
        store.execute(
            "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, base_project_id, ir_hash,"
            " principal_json, consent_at, level, close_level, external_sync_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,'C0',?,?,?,?)",
            (target_key, owner_sub, body.kind, body.ref_id, project_id, base_project_id, ir_hash,
             canonical_json(ident.to_dict()), now, config.settings.risk_default_close_level,
             canonical_json(ra_client.empty_sync()), now, now),
        )
        if agents:
            roster = planner.freeze_roster(store, target_key, owner_sub, agents, ecad_absent=ecad_absent)
    plan = planner.tier_plan(store, target_key) if roster["roster_size"] else None
    return {
        "target_key": target_key,
        "roster_size": roster["roster_size"],
        "deferred": roster["deferred"],
        "tier_plan": plan["tiers"] if plan else None,
        "cost_estimate": plan["cost_estimate"] if plan else None,
        # 로스터 원천 — body.agents(호출자 제공) · gateway(list_agents+recommend_agents) · unavailable(자격·게이트웨이 부재).
        "roster_source": roster_source,
    }


class RosterBody(BaseModel):
    agents: list[dict] = Field(default_factory=list)


@router.post("/targets/{target_key}/refresh_roster")
def refresh_roster(target_key: str, body: RosterBody = RosterBody(),
                   ident: identity.Identity = Depends(identity.current)) -> dict:
    """`list_agents` 에 새로 생긴 키만 pending 으로 덧붙인다(기존 종결 행 불변).

    본문 없는 호출도 받는다(plan §0.5.1·§8.2.3 — 인자 없이 `{added_pending}`). 본문 agents 가 있으면 그것이 우선이고,
    없으면 게이트웨이 `list_agents`·`recommend_agents` 를 조회한다(자격이 없으면 갱신 0건 + roster_source='unavailable').
    """
    owner_sub = _require_user(ident)
    target = _target_row(target_key, owner_sub)
    store = get_store()
    agents: list[dict] = [dict(a) for a in ((body or RosterBody()).agents or [])]
    roster_source = roster_module.SOURCE_BODY if agents else roster_module.SOURCE_UNAVAILABLE
    if not agents:
        fetched = roster_module.fetch_for_target(store, kind=target["kind"], ref_id=target["ref_id"],
                                                 owner_sub=owner_sub)
        agents, roster_source = fetched["agents"], fetched["source"]
    if agents and target["roster_frozen_at"] is None:
        # 고정된 적이 없는 타깃(생성 때 게이트웨이가 불통이었다)은 덧붙이기가 아니라 최초 고정이다 —
        # ECAD 부재 반영과 roster_frozen_at 갱신이 여기서 같이 일어나야 로스터 0 짜리 타깃이 남지 않는다.
        frozen = planner.freeze_roster(store, target_key, owner_sub, agents,
                                       ecad_absent=_ecad_absent_for_target(store, target))
        return {"added_pending": frozen["roster_size"], "roster_source": roster_source}
    return {**planner.refresh_roster(store, target_key, agents), "roster_source": roster_source}


# ================================================================ 잡
class JobBody(BaseModel):
    tier: str
    concurrency: int = 1
    modifiers: list[str] | None = None
    user_memo: str | None = None
    consent: bool = False


@router.post("/targets/{target_key}/jobs")
def create_job(target_key: str, body: JobBody,
               ident: identity.Identity = Depends(identity.current)) -> dict:
    """배치 잡 1건(Tier C 는 consent 필수, 러너 자격이 없으면 422 pat_unavailable)."""
    owner_sub = _require_user(ident)
    _target_row(target_key, owner_sub)
    return runner.create_job(get_store(), target_key, body.tier, owner_sub=owner_sub,
                             modifiers=body.modifiers, user_memo=body.user_memo,
                             concurrency=body.concurrency, consent=body.consent)


JOB_ACTIONS = {"pause": runner.pause_job, "resume": runner.resume_job, "cancel": runner.cancel_job}


@router.post("/jobs/{job_id}/{action}")
def job_action(job_id: str, action: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """일시정지·재개·취소(패널 경계에서 반영)."""
    owner_sub = _require_user(ident)
    if action not in JOB_ACTIONS:
        raise AppError("E404", f"모르는 잡 조작입니다 — {action}.", 404)
    _owned_row("SELECT id, owner_sub FROM rr_jobs WHERE id = ?", (job_id,), owner_sub, f"잡({job_id})")
    return JOB_ACTIONS[action](get_store(), job_id)


# ================================================================ 커버리지·등록부·패널
@router.get("/targets/{target_key}/coverage")
def get_coverage(target_key: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """진행판 — 도메인별 상태·미착석 수·완결 레벨(레벨 계산은 registry.close_level)."""
    owner_sub = _require_user(ident)
    _target_row(target_key, owner_sub)
    store = get_store()
    summary = planner.coverage_summary(store, target_key)
    level = registry_module.close_level(store, target_key, persist=False)
    job = store.query_one(
        "SELECT id, tier, state, pause_reason, panels_done, panels_total, error FROM rr_jobs"
        " WHERE target_key = ? ORDER BY created_at DESC LIMIT 1", (target_key,))
    return {
        "job": dict(job) if job is not None else None,
        "roster_size": summary["roster_size"],
        "by_domain": summary["by_domain"],
        "by_status": summary["by_status"],
        "strong": summary["strong"],
        "unseated_n": summary["unseated_n"],
        "level": level["level"],
        "close_level": level["close_level"],
    }


def registry_payload(target_key: str, *, owner_sub: str | None = None, status: str | None = None,
                     severity: str | None = None, domain: str | None = None,
                     limit: int | None = None) -> dict:
    """`GET /api/targets/{key}/registry` 본체 — MCP `risk_get_registry` 와 같은 함수."""
    _target_row(target_key, owner_sub)
    store = get_store()
    rows = registry_module.registry_rows(store, target_key)
    if status:
        rows = [r for r in rows if r["status"] == status]
    if severity:
        rows = [r for r in rows if r["severity"] == severity]
    if domain:
        rows = [r for r in rows if str((r.get("merged") or {}).get("domain") or "") == domain]
    truncated = limit is not None and len(rows) > int(limit)
    if limit is not None:
        rows = rows[: int(limit)]
    return {"target_key": target_key, "rows": rows, "truncated": truncated,
            "verdict_candidate": registry_module.verdict_candidate(store, target_key)}


@router.get("/targets/{target_key}/registry")
def get_registry(target_key: str, status: str | None = None, severity: str | None = None,
                 domain: str | None = None, ident: identity.Identity = Depends(identity.current)) -> dict:
    owner_sub = _require_user(ident)
    return registry_payload(target_key, owner_sub=owner_sub, status=status, severity=severity, domain=domain)


@router.get("/targets/{target_key}/panels")
def get_panels(target_key: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """패널 목록(conv_id · report_id · quality_json · model_json)."""
    owner_sub = _require_user(ident)
    _target_row(target_key, owner_sub)
    rows = get_store().query(
        "SELECT id, panel_no, tier, seats_json, modifiers_json, rounds, engine, tool_mode, conv_id, report_id,"
        " status, risk_spec_parsed, quality_json, model_json, llm_calls, retry, error, started_at, ended_at"
        " FROM rr_panels WHERE target_key = ? ORDER BY panel_no", (target_key,))
    panels = []
    for row in rows:
        item = dict(row)
        item["seats"] = _loads(item.pop("seats_json"), [])
        item["modifiers"] = _loads(item.pop("modifiers_json"), [])
        item["quality"] = _loads(item.pop("quality_json"), {})
        item["model"] = _loads(item.pop("model_json"), {})
        panels.append(item)
    return {"target_key": target_key, "panels": panels}


class VerdictBody(BaseModel):
    verdict: str
    note: str | None = None


@router.put("/targets/{target_key}/verdict")
def put_verdict(target_key: str, body: VerdictBody,
                ident: identity.Identity = Depends(identity.current)) -> dict:
    """사람 확정(자동 승인 없음 — 코드가 내는 것은 후보뿐이다)."""
    owner_sub = _require_user(ident)
    _target_row(target_key, owner_sub)
    if body.verdict not in ("go", "conditional", "no-go", "undetermined"):
        raise AppError("E100", f"verdict 어휘 밖입니다 — {body.verdict!r}.", 422)
    now = now_epoch()
    get_store().execute(
        "UPDATE rr_targets SET verdict_final = ?, verdict_note = ?, verdict_by = ?, verdict_at = ?,"
        " updated_at = ? WHERE target_key = ?",
        (body.verdict, body.note, owner_sub, now, now, target_key))
    return _target_row(target_key, owner_sub)


class RegistryStatusBody(BaseModel):
    status: str
    evidence_ref: str | None = None
    note: str | None = None
    target_key: str | None = None


@router.put("/registry/{cluster_key:path}/status")
def put_registry_status(cluster_key: str, body: RegistryStatusBody,
                        ident: identity.Identity = Depends(identity.current)) -> dict:
    """verified·dismissed 는 라벨 대상(§7.6), mitigated 는 사람 표기만(§4.7.1)."""
    owner_sub = _require_user(ident)
    return registry_module.set_status(get_store(), cluster_key, body.status, owner_sub=owner_sub,
                                      target_key=body.target_key, evidence_ref=body.evidence_ref,
                                      note=body.note, actor=owner_sub)


@router.post("/targets/{target_key}/resync")
def post_resync(target_key: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """external_sync 두 채널을 pending 으로 되돌린다(§5.5.3). 소유자 전용."""
    owner_sub = _require_user(ident)
    row = get_store().query_one("SELECT owner_sub FROM rr_targets WHERE target_key = ?", (target_key,))
    if row is None:
        raise AppError("E404", f"타깃을 찾을 수 없습니다 — {target_key}.", 404)
    if row["owner_sub"] != owner_sub:
        raise AppError("E403", "타깃 소유자만 재동기할 수 있습니다.", 403)
    return ra_client.resync(get_store(), target_key)


# ================================================================ 브리프(REST·MCP 공용)
def _planned_panel(row: Any) -> dict:
    """rr_panels 의 planned 행을 planner.plan_next_panel 반환과 같은 모양으로 편다."""
    budget = _loads(row["budget_json"], {})
    return {
        "id": row["id"], "target_key": row["target_key"], "owner_sub": row["owner_sub"],
        "panel_no": row["panel_no"], "tier": row["tier"],
        "seats": _loads(row["seats_json"], []), "seats_json": row["seats_json"],
        "modifiers": _loads(row["modifiers_json"], []),
        "rounds": int(row["rounds"] or planner.ROUNDS),
        "tools": list(budget.get("tools_planned") or []), "budget": budget, "status": row["status"],
    }


def brief_payload(target_key: str, tier: str = "B", *, owner_sub: str | None = None,
                  actor: str | None = None, exclude: tuple[str, ...] = ()) -> dict:
    """`GET /api/targets/{key}/brief?tier=` 본체 — MCP `risk_get_brief` 와 같은 함수.

    Tier A 대표 패널은 웹 러너 전용이라 여기서 막는다(§6.11). 패널이 없으면 결정론 편성으로 `planned` 1건을 만든다.
    """
    if tier not in planner.TIERS:
        raise AppError("E100", f"tier 는 {list(planner.TIERS)} 중 하나여야 합니다 — {tier!r}.", 422)
    if tier == "A":
        raise AppError("tier_a_web_only", "Tier A 대표 패널은 웹 러너 전용입니다.", 422)
    target = _target_row(target_key, owner_sub)
    store = get_store()

    rows = store.query(
        "SELECT id, target_key, owner_sub, panel_no, tier, seats_json, modifiers_json, rounds, budget_json,"
        " status FROM rr_panels WHERE target_key = ? AND status = 'planned' ORDER BY panel_no", (target_key,))
    panels = [_planned_panel(r) for r in rows]
    if not panels:
        # 편성은 결정론이라 멱등이다(§8.2.5 risk_get_brief 주석).
        fresh = planner.plan_next_panel(store, target_key, tier)
        if fresh is not None:
            panels = [fresh]

    seats = panels[0]["seats"] if panels else None
    panel_id = panels[0]["id"] if panels else None
    brief = brief_module.build_brief(store, target_key, seats=seats, panel_id=panel_id,
                                     exclude=exclude, owner_sub=target["owner_sub"])
    # E0c(좌석 계약)는 build_delib_opts 가 다시 끼우므로 엔진 몫 evidence 에서는 뺀다.
    engine_evidence = [item for item, key in zip(brief["evidence"], brief["keys"]) if key != "E0c"]

    out_panels = []
    for panel in panels:
        out_panels.append({
            "panel_id": panel["id"],
            "panel_no": panel["panel_no"],
            "seats_json": panel["seats_json"],
            "delib_opts": runner.build_delib_opts(store, config.settings, panel, evidence=engine_evidence),
        })
    payload = {
        "target_key": target_key,
        "tier": tier,
        "panels": out_panels,
        "evidence": brief["evidence"],
        "keys": brief["keys"],
        "refs": brief["refs"],
        "budget": {"bytes": brief["meta"]["budget_used"], "dropped": brief["meta"]["dropped"]},
        "meta": brief["meta"],
    }
    # §6.11 — actor 가 타깃 owner 로 해석되지 않으면 이유를 남긴다(게이트웨이 신고값은 미검증).
    if actor is not None and actor != target["owner_sub"]:
        payload["reason"] = "caller_unresolved"
    return payload


@router.get("/targets/{target_key}/brief")
def get_brief(target_key: str, tier: str = "B",
              ident: identity.Identity = Depends(identity.current)) -> dict:
    owner_sub = _require_user(ident)
    return brief_payload(target_key, tier, owner_sub=owner_sub)


# ================================================================ 패널 결과 회수(REST·MCP 공용)
EVENT_KINDS = ("status", "evidence", "personas", "turn", "warning", "error")
EVENTS_MAX = 400
EVENT_FIELD_MAX = 200


def _check_events(events: list[dict] | None) -> tuple[list[dict] | None, bool]:
    """events[] 형식 검사(plan §8.2.3) — kind 어휘·문자열 길이 위반은 422, 400건 초과는 앞 400건만 받는다."""
    if events is None:
        return None, False
    checked: list[dict] = []
    for item in events:
        if not isinstance(item, dict) or str(item.get("kind") or "") not in EVENT_KINDS:
            raise AppError("E100", f"events[] 항목 형식 위반 — kind 는 {list(EVENT_KINDS)} 중 하나여야 합니다.", 422)
        for key, value in item.items():
            if isinstance(value, str) and len(value) > EVENT_FIELD_MAX:
                raise AppError("E100", f"events[].{key} 가 {EVENT_FIELD_MAX}자를 넘습니다.", 422)
        checked.append(item)
    return checked[:EVENTS_MAX], len(checked) > EVENTS_MAX


def _seat_contract_rev() -> str:
    """seat-contract.v1.json 의 sha256[:12](D6 model_json.seat_contract_rev)."""
    return sha256_hex(taxonomy.asset_path("seat-contract").read_bytes())[:12]


def complete_panel(panel_id: str, *, engine: str, decision_text: str, turns: list[dict],
                   report_id: Any = None, conv_id: str | None = None,
                   events: list[dict] | None = None, model: str | None = None,
                   actor: str | None = None, actor_verified: bool = False,
                   owner_sub: str | None = None) -> dict:
    """`POST /api/panels/{id}/complete` 본체 — MCP `risk_submit_panel_result` 와 같은 함수.

    파서는 앱 단일 구현(`narrative.parse_risk_spec`)이고 병합은 `registry.merge` 다. `owner_sub` 는 패널 행을
    승계한다 — `actor`(게이트웨이 신고 이메일)로 소유자를 바꾸지 않는다(§6.11).
    """
    if engine not in ("mcp", "web"):
        raise AppError("E100", f"engine 은 mcp|web 여야 합니다 — {engine!r}.", 422)
    panel = _panel_row(panel_id, owner_sub)
    # planned 는 MCP L1·L2 의 진입 상태다(§6.11 — '패널이 planned 로 미리 편성돼 있어야 하며 없으면 409').
    if panel["status"] not in ("planned", "running", "done", "error"):
        raise AppError("E409", f"패널이 planned·running(또는 재제출 대상 done·error)이 아닙니다 — {panel['status']}.", 409)
    resubmit = panel["status"] in ("done", "error")

    # 서술 저장이 없으면 패널을 done 으로 옮기지 않는다 — 좌석이 running 에 고착돼 그 타깃 편성이 막힌다.
    persist = getattr(narrative, "persist_panel_result", None)
    if not callable(persist):
        raise _not_implemented("패널 결과 회수", "narrative.persist_panel_result 가 아직 없다(§6.7.2 8단계)")

    checked, truncated = _check_events(events)
    seats = _loads(panel["seats_json"], [])
    attribution = runner.attribute_events(checked, [s.get("key") for s in seats])
    spec = narrative.parse_risk_spec(decision_text)
    parsed = spec is not None
    store = get_store()
    now = now_epoch()

    # planned 패널은 좌석이 assigned 다 — 종결 전에 running 으로 이어 원장 상태를 맞춘다(§6.8.2 전이표).
    if panel["status"] == "planned":
        planner.start_panel_seats(store, panel_id)

    # engine·tool_mode — MCP 경로는 좌석 도구 호출 경로가 없어 evidence_only 등급이다(§6.11).
    # 재제출은 기존 engine·tool_mode 를 유지한다(§6.11 재제출 행).
    engine_stored = str(panel["engine"] or engine) if resubmit else engine
    if resubmit:
        tool_mode = panel["tool_mode"] or ("evidence_only" if engine_stored == "mcp" else "tools")
    else:
        tool_mode = "evidence_only" if engine == "mcp" else (panel["tool_mode"] or "tools")
    model_json = _loads(panel["model_json"], {})
    if engine == "mcp":
        model_json = {
            "runtime": "claude-code", "provider": None, "model": model or "unknown",
            "captured": "caller_reported", "engine_rev": None,
            # chair_rev 는 엔진(deliberation.py) 상수의 해시라 앱에 원문이 없다 — MCP 경로에서는 비운다.
            "chair_rev": None, "seat_contract_rev": _seat_contract_rev(),
        }
    elif model:
        model_json = {**model_json, "model": model, "captured": "caller_reported"}

    quality = _loads(panel["quality_json"], {})
    quality.update({"actor": actor, "actor_verified": bool(actor_verified)})
    # events[] 가 없으면 귀속 값은 건드리지 않는다 — 재제출이 기존 attribution_rate·extra_seats 를 지우면 안 된다(§8.2.3).
    if checked is not None:
        quality["attribution_rate"] = attribution["attribution_rate"]
        quality["extra_seats"] = list(attribution["extra_seats"])
    flags = list(quality.get("flags") or [])
    if attribution["extra_seats"] and "rescreen_seats" not in flags:
        flags.append("rescreen_seats")
    if not parsed and "spec_parse_failed" not in flags:
        flags.append("spec_parse_failed")           # §6.5.5 — 파싱 실패는 플래그로 남는다(§6.9 C2 차단 조건).
    if parsed and "spec_parse_failed" in flags:
        flags.remove("spec_parse_failed")           # 보정 재제출로 해결됐다.
    quality["flags"] = flags

    # 상태 전이·서술 저장·좌석 회계·등록부 병합은 한 트랜잭션이다 — 중간 실패의 반쪽 저장을 막는다.
    with store.tx():
        store.execute(
            "UPDATE rr_panels SET status = 'done', engine = ?, tool_mode = ?, decision_text = ?, risk_spec_json = ?,"
            " risk_spec_parsed = ?, conv_id = COALESCE(?, conv_id), report_id = COALESCE(?, report_id),"
            " model_json = ?, quality_json = ?, ended_at = ? WHERE id = ?",
            (engine_stored, tool_mode, decision_text, canonical_json(spec) if parsed else None, 1 if parsed else 0,
             conv_id, report_id, canonical_json(model_json), canonical_json(quality), now, panel_id),
        )

        persisted = persist(store, panel_id, decision_text=decision_text, spec=spec, turns=turns,
                            attribution=attribution, actor=actor)
        seat_results = []
        turns_by_seat: dict[str, int] = {}
        for turn in turns:
            key = str(turn.get("persona") or "")
            if key:
                turns_by_seat[key] = turns_by_seat.get(key, 0) + 1
        for seat in persisted.get("seats") or []:
            key = seat.get("agent_key")
            attr = attribution["seats"].get(key) or {}
            seat_results.append({
                "agent_key": key, "opinion_id": seat.get("opinion_id"),
                "turns_n": max(int(seat.get("turns_n") or 0), turns_by_seat.get(key, 0)),
                "used_tool": attr.get("used_tool"), "cited_refs_n": int(seat.get("cited_refs_n") or 0),
                "abstained": bool(seat.get("abstained")),
            })
        planner.apply_seat_results(store, panel_id, seat_results, decision_ok=bool(decision_text),
                                   model=model_json.get("model"))
        coverage_updated = True

        merged = registry_module.merge(store, panel["target_key"])
        level = registry_module.close_level(store, panel["target_key"])

    out = {
        "panel_id": panel_id,
        "parsed": parsed,
        "findings_n": int(merged.get("findings") or 0),
        "clusters": int(merged.get("clusters") or 0),
        "coverage_updated": coverage_updated,
        "attribution_rate": quality.get("attribution_rate"),
        "level": level.get("level"),
        "engine": engine_stored,
        "tool_mode": tool_mode,
    }
    if truncated:
        out["events_truncated"] = True
    return out


class PanelCompleteBody(BaseModel):
    engine: str
    conv_id: str | None = None
    decision_text: str
    turns: list[dict] = Field(default_factory=list)
    report_id: int | None = None
    events: list[dict] | None = None
    model: str | None = None


@router.post("/panels/{panel_id}/complete")
def post_panel_complete(panel_id: str, body: PanelCompleteBody,
                        ident: identity.Identity = Depends(identity.current)) -> dict:
    owner_sub = _require_user(ident)
    return complete_panel(panel_id, engine=body.engine, decision_text=body.decision_text, turns=body.turns,
                          report_id=body.report_id, conv_id=body.conv_id, events=body.events,
                          model=body.model, actor=owner_sub, actor_verified=True, owner_sub=owner_sub)


# ================================================================ 성격·유사·참조
@router.get("/projects/{project_id}/character")
def get_character(project_id: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """성격 프로파일 3층(seed · panel · confirmed)을 섞지 않고 그대로 준다(§4.6.4)."""
    owner_sub = _require_user(ident)
    project = _project_row(project_id, owner_sub)
    rows = get_store().query(
        "SELECT id, facet, tag, tags_json, statement, polarity, cites_json, by_json, support_panels,"
        " support_targets, confidence, needs_review, status, first_target_key, updated_at"
        " FROM rr_character WHERE project_id = ? ORDER BY facet, status, id", (project_id,))
    layers: dict[str, list[dict]] = {"seed": [], "panel": [], "confirmed": [], "superseded": []}
    for row in rows:
        item = dict(row)
        item["tags"] = _loads(item.pop("tags_json"), [])
        item["cites"] = _loads(item.pop("cites_json"), [])
        item["by"] = _loads(item.pop("by_json"), [])
        layers.setdefault(item["status"], []).append(item)
    return {"project_id": project_id, "character_status": project["character_status"], "layers": layers}


@router.get("/projects/{project_id}/similar")
def get_similar(project_id: str, k: int = 5, ident: identity.Identity = Depends(identity.current)) -> dict:
    """출처별 top-k(계보·벡터·서술·subject). 경로를 섞지 않는다(§5.7)."""
    owner_sub = _require_user(ident)
    _project_row(project_id, owner_sub)
    return brief_module.similar_projects(get_store(), project_id, k, owner_sub=owner_sub)


def _ref_from_store(info: dict, owner_sub: str) -> dict | None:
    """스냅샷 스코프 없이 전역으로 주소가 잡히는 참조(reg·narr·tool·rpt·inc·card)를 원장에서 찾는다."""
    store = get_store()
    kind = info["kind"]
    if kind == "reg":
        row = store.query_one(
            "SELECT target_key, cluster_key, merged_json, severity, judgement, status, support, contested"
            " FROM rr_registry WHERE target_key = ? AND cluster_key = ? AND owner_sub = ?",
            (info["target_key"], info["cluster_key"], owner_sub))
        return dict(row) if row is not None else None
    if kind == "narr" and "finding_id" in info:
        row = store.query_one(
            "SELECT finding_id, claim_uid, opinion_id, cluster_key, severity, judgement, status, finding_json"
            " FROM rr_findings WHERE finding_id = ? AND owner_sub = ?", (info["finding_id"], owner_sub))
        return dict(row) if row is not None else None
    if kind == "narr":
        row = store.query_one(
            "SELECT id, project_id, facet, tag, statement, status FROM rr_character WHERE id = ? AND owner_sub = ?",
            (info["character_id"], owner_sub))
        return dict(row) if row is not None else None
    if kind == "tool" and "call_id" in info:
        row = store.query_one(
            "SELECT call_id, snapshot_id, seq, source_kind, app_key, channel, tool, args_json, ok, http_status,"
            " response_sha256, response_bytes, started_at, duration_ms, error FROM rr_snapshot_calls"
            " WHERE call_id = ? AND owner_sub = ?", (info["call_id"], owner_sub))
        return dict(row) if row is not None else None
    return None


def claims_for_ref(ref: str, *, owner_sub: str | None = None, limit: int = 100) -> dict:
    """참조 1건에 앵커된 주장 목록 — MCP `risk_claims_for_ref` 와 같은 함수(rr_claim_refs 역색인, §4.4.4)."""
    info = parse_ref(ref)
    if info is None:
        raise AppError("E100", f"참조 문법(plan §0.2.1)에 맞지 않습니다 — {ref!r}.", 422)
    sql = (
        "SELECT r.claim_uid AS claim_uid, r.ref_type AS ref_type, r.ref AS ref, r.quote AS quote,"
        " r.target_key AS target_key, r.dangling AS dangling, f.finding_id AS finding_id,"
        " f.direction AS direction, f.mechanism AS mechanism, f.mechanism_detail AS mechanism_detail,"
        " f.severity AS severity, f.judgement AS judgement, f.cluster_key AS cluster_key, f.status AS status"
        " FROM rr_claim_refs r LEFT JOIN rr_findings f ON f.claim_uid = r.claim_uid WHERE r.ref = ?"
    )
    params: list[Any] = [info["ref"]]
    if owner_sub is not None:
        sql += " AND r.owner_sub = ?"
        params.append(owner_sub)
    rows = get_store().query(sql + " ORDER BY r.claim_uid LIMIT ?", (*params, int(limit) + 1))
    truncated = len(rows) > int(limit)
    return {"ref": info["ref"], "ref_type": info["kind"],
            "claims": [dict(r) for r in rows[: int(limit)]], "truncated": truncated}


@router.get("/refs/{ref:path}")
def get_ref(ref: str, snapshot_id: str | None = None, diff_id: str | None = None,
            ident: identity.Identity = Depends(identity.current)) -> dict:
    """참조 1건 해석(§0.2.1 문법). 스냅샷·diff 스코프가 필요한 스킴은 쿼리로 스코프를 받는다."""
    owner_sub = _require_user(ident)
    info = parse_ref(ref)
    if info is None:
        raise AppError("E100", f"참조 문법(plan §0.2.1)에 맞지 않습니다 — {ref!r}.", 422)
    store = get_store()
    payload: Any = _ref_from_store(info, owner_sub)
    if payload is None and (snapshot_id or diff_id):
        ctx = narrative.SpecContext(owner_sub=owner_sub, store=store)
        if snapshot_id:
            _snapshot_row(snapshot_id, owner_sub)
            ctx.snapshot_ids = (snapshot_id,)
            ctx.irs = {snapshot_id: ir_builder.load_ir(store, snapshot_id)}
            ctx.states = {snapshot_id: state_module.load_state(store, snapshot_id) or {}}
        if diff_id:
            ctx.diff_id = diff_id
            ctx.diff = diff_module.get_diff(store, diff_id, owner_sub=owner_sub, part="diff")
        text = narrative.canonical_text_for(info["ref"], ctx)
        payload = {"text": text} if text is not None else None
    if payload is None:
        raise AppError("E404", f"해석되지 않는 참조입니다(dangling) — {info['ref']}.", 404)
    return {"ref_type": info["kind"], "resolved": True, "payload": payload}


# ================================================================ 이동(export·import)
@router.get("/export")
def get_export(since: int = 0, ident: identity.Identity = Depends(identity.current)) -> StreamingResponse:
    """JSONL 내보내기(소유자 행만) — 첫 줄 헤더 `{schema_version, app_version, origin}`, 이어서 §5.2.2 A→H 표 순서로 `{table, row}`.

    같은 내용을 `$HEAX_DATA_DIR/exports/<ts>.jsonl` 에 남기고(plan §5.2.5 (1)) 그 파일을 그대로 흘려보낸다.
    """
    owner_sub = _require_user(ident)
    path = export_module.write_export_file(get_store(), owner_sub, int(since))

    def _stream():
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                yield line

    return StreamingResponse(_stream(), media_type="application/x-ndjson", headers={
        "Content-Disposition": f'attachment; filename="{path.name}"', "X-Export-Path": str(path)})


@router.post("/import")
async def post_import(request: Request, ident: identity.Identity = Depends(identity.current)) -> dict:
    """JSONL 들여오기 — `{inserted, merged, skipped, conflicts[]}`. 병합 규칙은 export.py(사람 확정이 자동을 이긴다)."""
    owner_sub = _require_user(ident)
    raw = await request.body()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AppError("E100", "본문이 UTF-8 JSONL 이 아닙니다.", 422) from exc
    return export_module.import_jsonl(get_store(), owner_sub, text)
