# REST 라우터 /api(plan §8.2.3 계약표 전부) — 신원은 Depends(identity.current), 쓰기는 익명 401·owner_sub 소유권, 본문 로직은 전부 모듈 함수 호출
from __future__ import annotations

import base64
import gzip
import hmac
import json
import secrets
import sqlite3
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import brief as brief_module
from app import character, config, diff as diff_module
from app import export as export_module
from app import identity, ir_builder, learning, metrics, narrative, planner, ra_client, requirements, runner, sameas, taxonomy
from app import roster as roster_module
from app import state as state_module
from app import registry as registry_module
from app.adapters import base as adapters_base
from app.adapters import registry as adapters_registry
from app.adapters.dyna import CONTEXT_KIND as CONTEXT_CALL_KIND
from app import field_source
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
    """_user_credentials 행 → {registered, email, groups[], exp, scopes[], revoked_at}. PAT 값·암호문은 싣지 않는다.

    `revoked_at` 이 찍혀 있으면 SettingsPage 가 '이 PAT 는 폐기됨 — 재등록하세요' 를 띄운다(plan §8.2.7).
    """
    if row is None:
        return None
    try:
        groups = json.loads(row.get("pat_groups_json") or "[]")
    except ValueError:
        groups = []
    try:
        scopes = json.loads(row.get("pat_scopes_json") or "[]")
    except ValueError:
        scopes = []
    return {"registered": True, "email": row.get("pat_email"), "groups": groups, "exp": row.get("pat_exp"),
            "scopes": scopes if isinstance(scopes, list) else [], "jti": row.get("pat_jti"),
            "revoked_at": row.get("revoked_at"),
            # 키가 바뀌었거나 사라져 복호가 안 되면 '등록됨' 인데 러너는 매번 자격 (a) 로 강등된다 — 그 사실을 드러낸다.
            "decryptable": identity.credential_pat(row) is not None}


def _caller_groups(ident: identity.Identity) -> list[str]:
    """반출 자격 대조에 쓰는 이 호출자의 그룹 — heax role + 등록된 포털 PAT 의 groups 클레임.

    `Identity` 에는 groups 열이 없다(heax /auth/me 가 role 만 준다) — 그래서 사용자가 스스로 등록한
    PAT 의 groups 를 함께 본다. 둘 다 없으면 빈 목록이고 `risk_export_allowed_groups` 가 설정된 박스에서는
    닫힘(403)이 기본이다.
    """
    groups = [ident.role] if ident.role else []
    if ident.email:
        row = get_store().get_credential(ident.email)
        if row is not None:
            groups += [str(g) for g in _loads(row.get("pat_groups_json"), []) if g]
    return groups


def _require_user(ident: identity.Identity) -> str:
    if ident.anonymous or not ident.email:
        raise AppError("unauthorized", "인증된 사용자만 호출할 수 있습니다.", 401)
    return ident.email


def _audit(store: Any, owner_sub: str, *, scope: str, subject_id: str, action: str,
           project_id: str | None = None, before: Any = None, after: Any = None,
           reason: str | None = None, channel: str = "rest") -> None:
    """rr_audit 1행(append-only, 사람 행위 한정 — plan §0.6). 열람(GET)은 남기지 않는다."""
    store.execute(
        "INSERT INTO rr_audit(id, owner_sub, actor, actor_verified, channel, scope, subject_id, project_id,"
        " action, before_json, after_json, reason, at) VALUES (?,?,?,1,?,?,?,?,?,?,?,?,?)",
        (new_uuid(), owner_sub, owner_sub, channel, scope, subject_id, project_id, action,
         canonical_json(before) if before is not None else None,
         canonical_json(after) if after is not None else None, reason, now_epoch()),
    )


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
    """등록 전에 포털이 이 PAT 를 받는지 확인한다(§8.2.3).

    **포털에 닿지 못한 것과 포털이 거부한 것을 같은 코드로 접지 않는다.** 둘을 `pat_invalid` 로 뭉치면
    화면이 "값을 다시 복사하거나 새로 발급하세요" 로 번역하는데, 실제 원인이 `HWAXRISK_PORTAL_BASE`
    오지정이면 사용자는 멀쩡한 토큰을 몇 번이고 다시 발급하게 된다(2026-09-30 실측 — 기본값
    `127.0.0.1:5283` 은 포털 vite 개발 포트라 이 박스에서 죽어 있고 실제 오리진은 nginx `:8088` 이다).
    """
    base = config.settings.portal_base.rstrip("/")
    url = f"{base}/agent/conversations?limit=1"
    try:
        with httpx.Client(transport=_portal_transport, timeout=PORTAL_TIMEOUT_S) as client:
            r = client.get(url, headers={"Authorization": f"Bearer {pat}"})
    except httpx.HTTPError as exc:
        raise AppError(
            "portal_unreachable",
            f"포털에 닿지 못했습니다 — {base} ({type(exc).__name__}). PAT 문제가 아니라 설정 문제입니다"
            f" — HWAXRISK_PORTAL_BASE 가 실제 포털 오리진(nginx)을 가리키는지 확인하세요.", 502) from exc
    if r.status_code != 200:
        raise AppError("pat_invalid", f"포털이 PAT 를 거부했습니다(HTTP {r.status_code}).", 422)


@router.post("/auth/sso")
def post_auth_sso(request: Request) -> dict:
    """게이트웨이 전용 신원 위임 — 공유 시크릿을 받고 그 이메일의 단기 HMAC 단언을 내준다(§8.2.8).

    시크릿 미설정이면 404 다 — 열려 있지 않다는 사실 자체를 굳이 알리지 않는다(KooRemapper 와 같은 규약).
    """
    secret = config.heax_gateway_secret()
    if not secret:
        raise AppError("not_found", "SSO 위임이 설정돼 있지 않습니다.", 404)
    got = request.headers.get("x-heax-gateway-secret", "")
    if not hmac.compare_digest(got, secret):
        raise AppError("unauthorized", "게이트웨이 시크릿이 맞지 않습니다.", 401)
    email = (request.headers.get("x-heax-user-email") or "").strip().lower()
    if "@" not in email:
        raise AppError("bad_email", "X-Heax-User-Email 이 이메일 형식이 아닙니다.", 401)
    token = identity.mint_sso_assertion(email, ttl_s=config.settings.sso_ttl_s, secret=secret)
    # 단언은 저장하지 않으므로 회수도 없다 — 게이트웨이 캐시가 이 수명보다 길면 만료 단언으로 부르게 되니
    # expires_in 을 함께 준다(게이트웨이는 실패 시 1회 재발급하므로 어긋나도 자가 복구된다).
    return {"access_token": token, "token_type": "bearer", "expires_in": config.settings.sso_ttl_s}


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
    payload["box"] = {"hostname": state.hostname, "secrets_valid": state.secrets_valid,
                      # 부작용 없는 갈래로만 본다 — 여기서 키를 만들면 기존 암호문이 영구히 복호 불가가 된다.
                      "cred_key_present": config.load_cred_key(create=False) is not None,
                      # 앱이 포털을 부르는 주소를 화면이 볼 수 있게 낸다(비밀이 아니다). 이 값이 틀리면
                      # PAT 등록·패널 실행이 전부 실패하는데 화면에 안 보이면 사람이 토큰을 의심한다
                      # (2026-09-30 실측 — 기본값이 포털 vite 개발 포트라 죽어 있었고 아무도 못 봤다).
                      "portal_base": config.settings.portal_base}
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
    # 저장은 Fernet 암호문이다(plan §8.2.7) — scopes 검사·jti 추출·암호화를 identity 가 한 곳에서 한다.
    rec = identity.credential_record(claims, body.pat)
    store.upsert_credential(
        owner_sub, rec["portal_pat_enc"].decode("ascii"), claims.get("sub"), email,
        json.dumps(groups, ensure_ascii=False), int(exp),
        pat_scopes_json=rec["pat_scopes_json"], pat_jti=rec["pat_jti"])
    return {"registered": True, "email": email, "groups": groups, "exp": int(exp),
            "scopes": rec["scopes"], "jti": rec["pat_jti"]}


@router.get("/meta/taxonomy")
def get_taxonomy() -> dict:
    return taxonomy.load_taxonomy()


@router.get("/meta/adapters")
def get_adapters(ident: identity.Identity = Depends(identity.current)) -> dict:
    """`{apps:[{app_key, kind, tools_ok, choices[]}]}`(plan §8.2.3·§8.2.4 ProjectPage 소스 카드).

    게이트웨이 `/tools-map` 실측이다(60 s 캐시). 못 읽으면 고정 목록 + `status='planned'` 로 떨어지며,
    그 사실은 `gateway_error` 로 드러난다 — '도구가 없다' 와 '못 물어봤다' 를 섞지 않는다.
    `choices[]` 는 소스 앱 도구를 실제로 불러야 채워지고 그건 포털 PAT 가 필요해 아직 빈 배열이다(P1 잔여).
    """
    return {"apps": adapters_registry.discover_adapters(token=ident.token)}


@router.get("/meta/vocab")
def get_vocab() -> dict:
    """어휘 자산 목록 + 자유 태그를 올릴 수 있는 축(§7.7 x_tag_promote 화면의 선택지).

    축 목록을 화면이 따로 갖지 않게 서버가 준다 — 통제 어휘가 두 곳에 적히면 한쪽만 늙는다.
    """
    return {"asset_version": taxonomy.ASSET_VERSION, "assets": taxonomy.vocab_index(),
            "promotable_axes": character.promotable_axes()}


METRICS_LIMIT_MAX = 2000


@router.get("/meta/metrics")
def get_metrics(limit: int = 500, ident: identity.Identity = Depends(identity.current)) -> dict:
    """rr_metrics 행 전부(코퍼스 1벌). 계산은 §7.6 야간 잡·`POST /meta/metrics/recompute` 의 몫이다.

    소유자 축으로 좁히지 않는다 — rr_metrics 의 PK 는 `(period, dimension, key, metric)` 뿐이고
    `key` 는 좌석 키·domain·mechanism·project_id·pattern_id·'global' 이라 owner_sub 가 실릴 자리가 없다
    (§5.2.2·metrics.recompute 는 '코퍼스 전체 1회' 계산이다). 옛 `key = <owner_sub>` 필터는 어떤 행과도
    맞지 않아 `visibility='private'` 로 적힌 재계산 결과를 전부 가렸다.
    """
    _require_user(ident)                      # 다른 조회 경로와 같이 익명은 401 이다(heax 불통 익명 강등 방어).
    rows = get_store().query(
        "SELECT period, dimension, key, metric, value, n, computed_at, visibility FROM rr_metrics"
        " ORDER BY period DESC, dimension, key, metric LIMIT ?",
        (max(1, min(int(limit), METRICS_LIMIT_MAX)),),
    )
    return {"metrics": [dict(r) for r in rows]}


class MetricsRecomputeBody(BaseModel):
    period: str = "all"
    visibility: str = "private"


@router.post("/meta/metrics/recompute")
def post_metrics_recompute(body: MetricsRecomputeBody = MetricsRecomputeBody(),
                           ident: identity.Identity = Depends(identity.current)) -> dict:
    """§7.6 지표 재계산 1회(야간 잡 ④ 와 같은 함수). 계산 단위는 코퍼스 전체이므로 소유자별 사본은 없다."""
    _require_user(ident)
    return metrics.recompute(get_store(), period=body.period, visibility=body.visibility)


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


# ================================================================ MCP 읽기 범위(plan §5.1 원칙 9 · §8.2.5)
# 읽기 4종의 범위는 자칭 `actor` 가 아니라 /mcp 에 실제로 도달한 Authorization 이 정한다. 게이트웨이는 호출자
# 토큰을 downstream 으로 넘기지 않고 자기 백엔드 헤더로 갈아 끼우므로 그 경로의 caller 는 언제나 service 이고,
# 사람이 개인 heax_pat 로 앱 MCP 를 직접 등록해 부른 경우에만 그 사람의 범위가 열린다. 해석 실패는 service 다(닫힘).
SERVICE_CALLER: dict[str, Any] = {"kind": "service", "email": None}


def mcp_caller(request: Any) -> dict:
    """이번 /mcp 요청의 caller — 신원이 해석되면 `user`, 토큰 없음·401·불통은 `service`."""
    if request is None:
        return dict(SERVICE_CALLER)
    ident = identity.current(request)
    if ident.anonymous or not ident.email:
        return dict(SERVICE_CALLER)
    return {"kind": "user", "email": ident.email}


def visible_projects(caller: dict) -> list[str]:
    """caller 가 MCP 로 볼 수 있는 과제 id — user 는 자기 소유 ∪ 멤버 ∪ `mcp_visibility='org'`, service 는 org 만."""
    email = caller.get("email") if caller.get("kind") == "user" else None
    if email:
        rows = get_store().query(
            "SELECT id FROM rr_projects WHERE owner_sub = ? OR mcp_visibility = 'org'"
            " OR id IN (SELECT project_id FROM rr_project_members WHERE email = ?) ORDER BY id",
            (email, email))
    else:
        rows = get_store().query("SELECT id FROM rr_projects WHERE mcp_visibility = 'org' ORDER BY id")
    return [r["id"] for r in rows]


def _not_visible(what: str) -> AppError:
    """범위 밖 id 는 존재를 숨긴다 + `rr_metrics(dimension='global', metric='mcp_not_visible')` 1 증가."""
    get_store().execute(
        "INSERT INTO rr_metrics(period, dimension, key, metric, value, n, computed_at)"
        " VALUES ('all','global','global','mcp_not_visible',1,1,?)"
        " ON CONFLICT(period, dimension, key, metric) DO UPDATE SET value = value + 1, n = n + 1,"
        " computed_at = excluded.computed_at", (now_epoch(),))
    return AppError("not_visible", f"볼 수 없는 id 입니다 — {what}.", 404)


def mcp_scope_owner(kind: str, key: str, caller: dict) -> str:
    """읽기 4종의 문지기 — 통과하면 그 행의 owner_sub, 범위 밖·부재는 `not_visible`(존재를 숨긴다).

    diff 는 base·target 두 과제가 모두 범위 안이어야 열린다(한쪽만 공개된 비교는 닫힌 쪽을 흘린다).
    """
    store = get_store()
    if kind == "snapshot":
        row = store.query_one("SELECT owner_sub, project_id FROM rr_snapshots WHERE id = ?", (key,))
        projects = [row["project_id"]] if row is not None else []
    elif kind == "diff":
        row = store.query_one(
            "SELECT owner_sub, base_project_id, target_project_id FROM rr_diffs WHERE id = ?", (key,))
        projects = [row["base_project_id"], row["target_project_id"]] if row is not None else []
    elif kind == "project":
        row = store.query_one("SELECT owner_sub, id AS project_id FROM rr_projects WHERE id = ?", (key,))
        projects = [row["project_id"]] if row is not None else []
    elif kind == "panel":
        # 패널은 과제를 직접 안 들고 타깃을 거친다 — 타깃의 과제로 범위를 본다.
        row = store.query_one(
            "SELECT p.owner_sub AS owner_sub, t.project_id AS project_id FROM rr_panels p"
            " JOIN rr_targets t ON t.target_key = p.target_key WHERE p.id = ?", (key,))
        projects = [row["project_id"]] if row is not None else []
    else:
        row = store.query_one("SELECT owner_sub, project_id FROM rr_targets WHERE target_key = ?", (key,))
        projects = [row["project_id"]] if row is not None else []
    if row is None or not all(p in set(visible_projects(caller)) for p in projects):
        raise _not_visible(key)
    return row["owner_sub"]


# ================================================================ 과제(plan §8.2.3)
class ProjectBody(BaseModel):
    code: str = Field(max_length=40)
    name: str = Field(max_length=200)
    # 등급은 반출 경계를 정하므로 등록 시 사람이 고른다 — 빠지면 422 다(plan §5.2.5 (3)·§0.6 '데이터 등급·반출').
    classification: str | None = None
    stage: str | None = None
    predecessor_project_id: str | None = None
    # 제품 3열(정본 §8.2.3 POST 계약) — §7.6 라벨 경로 4·§5.6.1 E10 의 조회 키다. 없으면 pydantic 이
    # extra 를 조용히 버려, 정본 계약대로 보낸 클라이언트가 **오류 없이** 제품 연결 없는 과제를 얻는다.
    product_code: str | None = None
    product_refs_json: list | None = None
    predecessor_product_code: str | None = None
    adh_scope: dict | None = None


@router.post("/projects")
def create_project(body: ProjectBody, ident: identity.Identity = Depends(identity.current)) -> dict:
    """rr_projects 1행. `UNIQUE(owner_sub, code)` 충돌은 409, 등급 미지정·어휘 밖은 422."""
    owner_sub = _require_user(ident)
    if body.classification is None:
        raise AppError("classification_required",
                       f"등급(classification)을 골라야 합니다 — {list(CLASSIFICATIONS)}.", 422)
    if body.classification not in CLASSIFICATIONS:
        raise AppError("E100", f"classification 은 {list(CLASSIFICATIONS)} 중 하나여야 합니다.", 422)
    scope = body.adh_scope or {}
    now = now_epoch()
    project_id = new_uuid()
    store = get_store()
    # 정본 §8.2.4 — "첫 행이 product_code 대표값으로 들어가고 계보 과제가 있으면 그 과제의
    # product_code 가 predecessor_product_code 로 채워진다". 대표값은 `kind='product_code'` 인 행에서
    # 고른다(`ra_model` 값은 RA 엔티티 코드라 VOC 조회 키가 아니다 — brief.product_keys 와 같은 규칙).
    refs = [r for r in (body.product_refs_json or []) if isinstance(r, dict)]
    product_code = body.product_code or next(
        (str(r.get("value")) for r in refs
         if str(r.get("kind") or "") == "product_code" and r.get("value")), None)
    predecessor_product_code = body.predecessor_product_code
    if predecessor_product_code is None and body.predecessor_project_id:
        prior = store.query_one("SELECT product_code FROM rr_projects WHERE id = ? AND owner_sub = ?",
                                (body.predecessor_project_id, owner_sub))
        predecessor_product_code = (prior["product_code"] if prior else None) or None
    try:
        # 과제 행과 owner 멤버 행은 한 트랜잭션이다(risk_store rr_project_members 불변식 — owner 행 정확히 1건).
        with store.tx():
            store.execute(
                "INSERT INTO rr_projects(id, owner_sub, code, name, stage, classification,"
                " predecessor_project_id, product_code, product_refs_json, predecessor_product_code,"
                " adh_team, adh_group, character_status, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'seed',?,?)",
                (project_id, owner_sub, body.code, body.name, body.stage, body.classification,
                 body.predecessor_project_id, product_code,
                 canonical_json(refs) if refs else None, predecessor_product_code,
                 scope.get("team"), scope.get("group"), now, now),
            )
            store.execute(
                "INSERT INTO rr_project_members(project_id, owner_sub, email, role, added_by, added_at,"
                " updated_at) VALUES (?,?,?,'owner',?,?,?)",
                (project_id, owner_sub, owner_sub, owner_sub, now, now),
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
    return projects_payload(owner_sub=_require_user(ident))


def projects_payload(*, owner_sub: str | None = None, project_ids: list[str] | None = None) -> dict:
    """`GET /projects` 본체 — MCP `risk_list_projects` 와 같은 함수.

    웹은 `owner_sub` 로 자기 과제만 본다. MCP 는 단일 소유자가 아니라 **볼 수 있는 과제 집합**
    (`visible_projects`)이 범위라 `project_ids` 로 받는다 — 그래서 두 인자가 따로 있다.
    id 를 알아낼 길이 이것뿐이라(나머지 도구가 전부 id 를 인자로 받는다) 목록이 곧 진입점이다."""
    store = get_store()
    if project_ids is not None:
        if not project_ids:
            return {"projects": []}
        marks = ",".join("?" for _ in project_ids)
        rows = store.query(
            f"SELECT id, code, name, stage, owner_sub, created_at FROM rr_projects WHERE id IN ({marks})"
            " ORDER BY created_at DESC, id", tuple(project_ids))
    else:
        rows = store.query(
            "SELECT id, code, name, stage, owner_sub, created_at FROM rr_projects WHERE owner_sub = ?"
            " ORDER BY created_at DESC, id", (owner_sub,))
    projects = []
    for row in rows:
        _own = row["owner_sub"]
        last = store.query_one(
            "SELECT MAX(created_at) AS ts FROM rr_snapshots WHERE project_id = ?", (row["id"],))
        targets = [dict(t) for t in store.query(
            "SELECT target_key, level, created_at FROM rr_targets WHERE project_id = ? AND owner_sub = ?"
            " ORDER BY created_at DESC", (row["id"], _own))]
        coverage_pct = None
        if targets:
            summary = planner.coverage_summary(store, targets[0]["target_key"])
            if summary["roster_size"]:
                coverage_pct = round(100.0 * summary["terminal_n"] / summary["roster_size"], 1)
        _snap = store.query_one(
            "SELECT id FROM rr_snapshots WHERE project_id = ? ORDER BY created_at DESC, id LIMIT 1",
            (row["id"],))
        projects.append({
            "id": row["id"], "code": row["code"], "name": row["name"], "stage": row["stage"],
            "targets": [t["target_key"] for t in targets],
            "last_snapshot_id": _snap["id"] if _snap else None,
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


ROLE_RANK: dict[str, int] = {"viewer": 1, "editor": 2, "owner": 3}
PROJECT_PATCH_COLS: tuple[str, ...] = (
    "lifecycle", "closed_at", "corpus_excluded", "excluded_reason", "classification",
    "mcp_visibility", "product_code", "product_refs_json", "predecessor_product_code",
)
LIFECYCLES = ("active", "shipped", "cancelled", "archived")
CLASSIFICATIONS = ("internal", "confidential")
MCP_VISIBILITIES = ("private", "org")
EXCLUDED_REASONS = ("fixture", "misregistered", "duplicate", "user")


def project_role(project_id: str, email: str) -> str | None:
    """그 과제에서 이 사람의 role — 소유자는 언제나 owner, 아니면 rr_project_members 행(없으면 None)."""
    store = get_store()
    row = store.query_one("SELECT owner_sub FROM rr_projects WHERE id = ?", (project_id,))
    if row is None:
        return None
    if row["owner_sub"] == email:
        return "owner"
    member = store.query_one(
        "SELECT role FROM rr_project_members WHERE project_id = ? AND email = ?", (project_id, email))
    return member["role"] if member is not None else None


def require_role(project_id: str, email: str, need: str) -> str:
    """`need` 이상의 권한을 요구한다 — 멤버가 아니면 404(존재를 숨긴다), 등급 미달은 403 role_insufficient."""
    role = project_role(project_id, email)
    if role is None:
        raise AppError("E404", f"과제({project_id}) 를 찾을 수 없습니다.", 404)
    if ROLE_RANK.get(role, 0) < ROLE_RANK.get(need, 9):
        raise AppError("role_insufficient", f"이 작업에는 {need} 이상 권한이 필요합니다(현재 {role}).", 403)
    return role


class ProjectPatchBody(BaseModel):
    lifecycle: str | None = None
    closed_at: int | None = None
    corpus_excluded: bool | None = None
    excluded_reason: str | None = None
    classification: str | None = None
    mcp_visibility: str | None = None
    product_code: str | None = None
    product_refs_json: list | None = None
    predecessor_product_code: str | None = None


@router.patch("/projects/{project_id}")
def patch_project(project_id: str, body: ProjectPatchBody,
                  ident: identity.Identity = Depends(identity.current)) -> dict:
    """과제 메타 갱신(editor, `mcp_visibility` 는 owner 만) — plan §8.2.3.

    `corpus_excluded` 토글은 같은 트랜잭션에서 delta 선례·패턴을 재합산하고,
    `mcp_visibility` 변경은 `external_sync.ra` 의 `withheld → pending` 을 풀고 감사 1행을 남긴다(§5.5.3).
    """
    owner_sub = _require_user(ident)
    role = require_role(project_id, owner_sub, "editor")
    store = get_store()
    before = store.query_one(
        "SELECT id, owner_sub, status, lifecycle, corpus_excluded, excluded_reason, classification,"
        " mcp_visibility, product_code, product_refs_json, predecessor_product_code, closed_at"
        " FROM rr_projects WHERE id = ?", (project_id,))
    if before is None:
        raise AppError("E404", f"과제({project_id}) 를 찾을 수 없습니다.", 404)
    if before["status"] == "purged":
        raise AppError("project_purged", "회수된 과제는 고칠 수 없습니다.", 409)

    patch = body.model_dump(exclude_unset=True)
    if body.mcp_visibility is not None and role != "owner":
        raise AppError("role_insufficient", "mcp_visibility 는 과제 소유자만 바꿀 수 있습니다.", 403)
    if body.lifecycle is not None and body.lifecycle not in LIFECYCLES:
        raise AppError("E100", f"lifecycle 은 {list(LIFECYCLES)} 중 하나여야 합니다.", 422)
    if body.classification is not None and body.classification not in CLASSIFICATIONS:
        raise AppError("E100", f"classification 은 {list(CLASSIFICATIONS)} 중 하나여야 합니다.", 422)
    if body.mcp_visibility is not None and body.mcp_visibility not in MCP_VISIBILITIES:
        raise AppError("E100", f"mcp_visibility 는 {list(MCP_VISIBILITIES)} 중 하나여야 합니다.", 422)
    if (body.classification == "internal" and before["classification"] == "confidential"
            and role != "owner"):
        raise AppError("classification_downgrade", "confidential → internal 은 과제 소유자만 할 수 있습니다.", 422)
    excluded_now = bool(patch["corpus_excluded"]) if "corpus_excluded" in patch else bool(before["corpus_excluded"])
    reason_now = patch.get("excluded_reason", before["excluded_reason"])
    if excluded_now and not (reason_now or "").strip():
        raise AppError("excluded_reason_required", "corpus_excluded=1 에는 excluded_reason 이 필요합니다.", 422)
    if reason_now and reason_now not in EXCLUDED_REASONS:
        raise AppError("E100", f"excluded_reason 은 {list(EXCLUDED_REASONS)} 중 하나여야 합니다.", 422)

    values: dict[str, Any] = {}
    for col in PROJECT_PATCH_COLS:
        if col not in patch:
            continue
        value = patch[col]
        if col == "corpus_excluded":
            value = 1 if value else 0
        elif col == "product_refs_json":
            value = canonical_json(value) if value is not None else None
        values[col] = value
    if not values:
        raise AppError("E100", "바꿀 필드가 없습니다.", 422)
    # lifecycle 이 active 를 떠나면 closed_at 을 기본으로 찍는다(호출자가 명시하면 그 값이 이긴다).
    if values.get("lifecycle") not in (None, "active") and "closed_at" not in values:
        values["closed_at"] = now_epoch()

    corpus_changed = "corpus_excluded" in values and values["corpus_excluded"] != int(before["corpus_excluded"] or 0)
    visibility_changed = "mcp_visibility" in values and values["mcp_visibility"] != before["mcp_visibility"]
    now = now_epoch()
    recomputed = {"delta_priors_rows": 0, "patterns_rows": 0}
    resynced = {"targets": 0, "ra_ops_released": 0}

    with store.tx():
        assignments = ", ".join(f"{col} = ?" for col in values)
        params = [*values.values()]
        if visibility_changed:
            assignments += ", mcp_visibility_by = ?, mcp_visibility_at = ?"
            params += [owner_sub, now]
        store.execute(f"UPDATE rr_projects SET {assignments}, updated_at = ? WHERE id = ?",
                      (*params, now, project_id))
        if corpus_changed:
            # 코퍼스 필터가 바뀌면 delta 선례·패턴의 분모가 바뀐다(§0.6 코퍼스 필터).
            recomputed["delta_priors_rows"] = int(learning.recompute_label_priors(store, now=now) or 0)
            mined = learning.mine_patterns(store, owner_sub=owner_sub, now=now) or {}
            recomputed["patterns_rows"] = len(mined.get("created") or ()) + len(mined.get("updated") or ())
        if visibility_changed:
            resynced = _release_withheld(store, project_id, now)
            resynced["adh_retag_ops"] = _queue_visibility_retag(store, project_id, values["mcp_visibility"])
            _audit(store, owner_sub, scope="project", subject_id=project_id, project_id=project_id,
                   action="project.mcp_visibility", before={"mcp_visibility": before["mcp_visibility"]},
                   after={"mcp_visibility": values["mcp_visibility"]})
        else:
            _audit(store, owner_sub, scope="project", subject_id=project_id, project_id=project_id,
                   action="project.update", before={k: before[k] for k in values},
                   after=dict(values))

    row = store.query_one(
        "SELECT id, owner_sub, code, name, stage, lifecycle, closed_at, corpus_excluded, excluded_reason,"
        " classification, mcp_visibility, product_code, product_refs_json, predecessor_product_code,"
        " status, created_at, updated_at FROM rr_projects WHERE id = ?", (project_id,))
    out = {"project": dict(row), "recomputed": recomputed}
    if visibility_changed:
        out["resynced"] = resynced
    return out


def _release_withheld(store: Any, project_id: str, now: int) -> dict:
    """`mcp_visibility='org'` 로 열린 과제의 타깃에서 `external_sync.ra` 의 withheld 를 pending 으로 되돌린다."""
    released_targets = 0
    released_ops = 0
    for row in store.query(
        "SELECT target_key, external_sync_json FROM rr_targets WHERE project_id = ?", (project_id,)):
        sync = ra_client.load_external_sync(store, row["target_key"])
        channel = sync.get("ra") or {}
        if channel.get("state") != "withheld":
            continue
        channel["state"] = "pending"
        channel["next_at"] = now
        sync["ra"] = channel
        ra_client.save_external_sync(store, row["target_key"], sync)
        released_targets += 1
        released_ops += len(channel.get("pending_ops") or [])
    return {"targets": released_targets, "ra_ops_released": released_ops}


def _queue_visibility_retag(store: Any, project_id: str, visibility: str) -> int:
    """가시성이 바뀐 과제의 AIDataHub 레코드에 태그 재부착 op 를 올린다(본문 무변경 UPSERT, plan §8.2.5 ②)."""
    ops = 0
    for row in store.query(
        "SELECT target_key FROM rr_targets WHERE project_id = ? ORDER BY target_key", (project_id,)
    ):
        records = store.query(
            "SELECT adh_record_id FROM rr_seat_opinions WHERE target_key = ? AND adh_record_id IS NOT NULL",
            (row["target_key"],))
        payload = [{"op": "retag", "reason": "visibility_retag", "record_id": str(r["adh_record_id"]),
                    "visibility": visibility} for r in records]
        if not payload:
            continue
        ra_client.queue_sync_ops(store, row["target_key"], "adh", payload)
        ops += len(payload)
    return ops


# ---------------------------------------------------------------- 멤버십·이양·이력·폐기(plan §5.2.1·§5.2.6·§8.2.3)
# 이양이 owner_sub 를 함께 옮기는 하위 11표(전부 project_id 를 직접 갖는다). 신원 앵커는 rr_projects.owner_sub
# 하나이고 하위 표의 owner_sub 는 그 복제라 불일치는 불변식 위반이다(plan §5.2.1).
TRANSFER_PROJECT_TABLES: tuple[str, ...] = (
    "rr_project_members", "rr_sources", "rr_requirements", "rr_snapshots", "rr_snapshot_jobs",
    "rr_dim_defs", "rr_iface_ledger", "rr_targets", "rr_findings", "rr_character", "rr_labels",
)
# 과제를 직접 가리키지 않고 스냅샷·타깃을 거쳐 달린 표. 같은 트랜잭션에서 함께 옮긴다.
TRANSFER_DERIVED: tuple[tuple[str, str], ...] = (
    ("rr_ir_nodes", "snapshot_id IN (SELECT id FROM rr_snapshots WHERE project_id = ?)"),
    ("rr_ir_edges", "snapshot_id IN (SELECT id FROM rr_snapshots WHERE project_id = ?)"),
    ("rr_states", "snapshot_id IN (SELECT id FROM rr_snapshots WHERE project_id = ?)"),
    ("rr_snapshot_calls", "snapshot_id IN (SELECT id FROM rr_snapshots WHERE project_id = ?)"),
    ("rr_gate_acks", "snapshot_id IN (SELECT id FROM rr_snapshots WHERE project_id = ?)"),
    ("rr_coverage", "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    ("rr_roster", "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    ("rr_panels", "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    ("rr_panel_calls", "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    # 빠뜨리면 새 소유자의 반출(owner_sub 스코프)에서 해석 원장이 사라져 voc:·paper: 인용이 dangling 된다.
    ("rr_brief_calls", "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    ("rr_seat_opinions", "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    ("rr_jobs", "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    ("rr_registry", "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    ("rr_registry_status_log", "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    ("rr_claim_refs", "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    ("rr_delta_contrib", "target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
)
MEMBER_ROLES = ("viewer", "editor")
RUNNING_JOB_STATES = ("queued", "running", "paused", "cancelling")


def _is_admin(ident: identity.Identity) -> bool:
    """`risk_admin_roles` 에 든 heax role 은 전 과제에서 editor 이고 이양·폐기는 owner 와 동등하다(plan §0.6)."""
    return bool(ident.role) and ident.role in tuple(config.settings.risk_admin_roles)


def _require_owner(project_id: str, ident: identity.Identity) -> str:
    """owner 전용 경로 — admin role 은 owner 와 동등하게 통과한다."""
    email = _require_user(ident)
    if _is_admin(ident):
        if get_store().query_one("SELECT id FROM rr_projects WHERE id = ?", (project_id,)) is None:
            raise AppError("E404", f"과제({project_id}) 를 찾을 수 없습니다.", 404)
        return email
    require_role(project_id, email, "owner")
    return email


def _members_of(project_id: str) -> list[dict]:
    rows = get_store().query(
        "SELECT project_id, email, role, added_by, added_at, updated_at FROM rr_project_members"
        " WHERE project_id = ? ORDER BY role, email", (project_id,))
    return [dict(r) for r in rows]


class MemberItem(BaseModel):
    email: str = Field(max_length=200)
    role: str


class MembersBody(BaseModel):
    members: list[MemberItem] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


@router.get("/projects/{project_id}/members")
def get_members(project_id: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """멤버 표(viewer 이상). 멤버가 아니면 404 로 존재를 숨긴다."""
    email = _require_user(ident)
    if not _is_admin(ident):
        require_role(project_id, email, "viewer")
    return {"project_id": project_id, "members": _members_of(project_id)}


@router.put("/projects/{project_id}/members")
def put_members(project_id: str, body: MembersBody,
                ident: identity.Identity = Depends(identity.current)) -> dict:
    """멤버 배열 UPSERT·삭제(owner 전용). owner 행은 여기서 바뀌지 않는다 — 이양(`/transfer`)만이 바꾼다."""
    owner_sub = _require_owner(project_id, ident)
    store = get_store()
    project = store.query_one("SELECT owner_sub, status FROM rr_projects WHERE id = ?", (project_id,))
    if project is None:
        raise AppError("E404", f"과제({project_id}) 를 찾을 수 없습니다.", 404)
    if project["status"] == "purged":
        raise AppError("project_purged", "회수된 과제는 고칠 수 없습니다.", 409)
    for item in body.members:
        if item.role not in MEMBER_ROLES:
            raise AppError("E100", f"role 은 {list(MEMBER_ROLES)} 중 하나여야 합니다 — {item.role!r}.", 422)
        if item.email == project["owner_sub"]:
            raise AppError("owner_row_immutable", "소유자 행은 이양으로만 바뀝니다.", 422)
    if project["owner_sub"] in set(body.remove):
        raise AppError("owner_row_immutable", "소유자 행은 지울 수 없습니다.", 422)

    before = _members_of(project_id)
    now = now_epoch()
    with store.tx():
        for item in body.members:
            store.execute(
                "INSERT INTO rr_project_members(project_id, owner_sub, email, role, added_by, added_at,"
                " updated_at) VALUES (?,?,?,?,?,?,?)"
                " ON CONFLICT(project_id, email) DO UPDATE SET role = excluded.role, updated_at = excluded.updated_at",
                (project_id, project["owner_sub"], item.email, item.role, owner_sub, now, now),
            )
        for email in body.remove:
            store.execute("DELETE FROM rr_project_members WHERE project_id = ? AND email = ?",
                          (project_id, email))
        after = _members_of(project_id)
        _audit(store, owner_sub, scope="project", subject_id=project_id, project_id=project_id,
               action="member.put", before={"members": before}, after={"members": after})
    return {"project_id": project_id, "members": after}


class TransferBody(BaseModel):
    to_email: str = Field(max_length=200)
    reason: str = Field(max_length=300)


@router.post("/projects/{project_id}/transfer")
def transfer_project(project_id: str, body: TransferBody,
                     ident: identity.Identity = Depends(identity.current)) -> dict:
    """소유권 이양 — 과제 행·멤버 두 행·하위 표 owner_sub 를 한 트랜잭션에서 옮긴다(plan §5.2.1)."""
    actor = _require_owner(project_id, ident)
    store = get_store()
    project = store.query_one("SELECT owner_sub, status FROM rr_projects WHERE id = ?", (project_id,))
    if project is None:
        raise AppError("E404", f"과제({project_id}) 를 찾을 수 없습니다.", 404)
    if project["status"] == "purged":
        raise AppError("project_purged", "회수된 과제는 이양할 수 없습니다.", 409)
    to_email = (body.to_email or "").strip().lower()
    if "@" not in to_email or to_email.startswith("@") or to_email.endswith("@"):
        raise AppError("unknown_user", f"heax 사용자 이메일이 아닙니다 — {body.to_email!r}.", 422)
    old_owner = project["owner_sub"]
    if to_email == old_owner:
        raise AppError("same_owner", "이미 이 사람이 소유자입니다.", 422)
    if not (body.reason or "").strip():
        raise AppError("E100", "이양에는 사유가 필요합니다.", 422)
    running = store.query_one(
        "SELECT COUNT(*) AS n FROM rr_jobs WHERE state IN ('queued','running','paused','cancelling')"
        " AND target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)", (project_id,))
    if int(running["n"] or 0) > 0:
        raise AppError("job_running", "진행 중 배치 잡이 있습니다 — 먼저 pause 하세요.", 409)

    now = now_epoch()
    rows_updated: dict[str, int] = {}
    with store.tx():
        store.execute("UPDATE rr_projects SET owner_sub = ?, updated_at = ? WHERE id = ?",
                      (to_email, now, project_id))
        # 새 소유자 행을 owner 로 올리고 이전 소유자는 editor 로 남긴다(멤버 행은 지우지 않는다).
        store.execute(
            "INSERT INTO rr_project_members(project_id, owner_sub, email, role, added_by, added_at, updated_at)"
            " VALUES (?,?,?,'owner',?,?,?)"
            " ON CONFLICT(project_id, email) DO UPDATE SET role = 'owner', updated_at = excluded.updated_at",
            (project_id, to_email, to_email, actor, now, now))
        store.execute(
            "UPDATE rr_project_members SET role = 'editor', updated_at = ? WHERE project_id = ? AND email = ?",
            (now, project_id, old_owner))
        for table in TRANSFER_PROJECT_TABLES:
            rows_updated[table] = int(store.execute(
                f"UPDATE {table} SET owner_sub = ? WHERE project_id = ?", (to_email, project_id)) or 0)
        for table, where in TRANSFER_DERIVED:
            rows_updated[table] = int(store.execute(
                f"UPDATE {table} SET owner_sub = ? WHERE {where}", (to_email, project_id)) or 0)
        _audit(store, actor, scope="project", subject_id=project_id, project_id=project_id,
               action="project.transfer", before={"owner_sub": old_owner}, after={"owner_sub": to_email},
               reason=body.reason)
    return {"from": old_owner, "to": to_email, "rows_updated": {"tables": rows_updated}}


@router.get("/projects/{project_id}/audit")
def get_project_audit(project_id: str, action: str | None = None, since: int = 0,
                      until: int | None = None, limit: int = 100, offset: int = 0,
                      ident: identity.Identity = Depends(identity.current)) -> dict:
    """사람 행위 감사 로그 조회(viewer 이상). 자동 전이는 애초에 rr_audit 에 들어가지 않는다(plan §0.6)."""
    email = _require_user(ident)
    if not _is_admin(ident):
        require_role(project_id, email, "viewer")
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    sql = ("SELECT id, actor, actor_verified, channel, scope, subject_id, project_id, action, before_json,"
           " after_json, reason, at FROM rr_audit WHERE project_id = ? AND at >= ?")
    params: list[Any] = [project_id, int(since)]
    if action:
        sql += " AND action = ?"
        params.append(action)
    if until is not None:
        sql += " AND at <= ?"
        params.append(int(until))
    total = get_store().query_one(sql.replace(
        "SELECT id, actor, actor_verified, channel, scope, subject_id, project_id, action, before_json,"
        " after_json, reason, at FROM", "SELECT COUNT(*) AS n FROM", 1), tuple(params))
    rows = get_store().query(sql + " ORDER BY at DESC, id DESC LIMIT ? OFFSET ?", (*params, limit, offset))
    entries = []
    for row in rows:
        item = dict(row)
        item["before"] = _loads(item.pop("before_json"), {})
        item["after"] = _loads(item.pop("after_json"), {})
        item["actor_verified"] = bool(item["actor_verified"])
        entries.append(item)
    return {"project_id": project_id, "total": int(total["n"] or 0), "limit": limit, "offset": offset,
            "entries": entries}


class PurgeBody(BaseModel):
    code: str = Field(max_length=40)
    reason: str = Field(max_length=300)


# 폐기가 비우는 원문 열(plan §5.2.6). NOT NULL 열은 DDL 이 41표로 동결돼 있어 NULL 대신 빈 문자열로 비운다.
PURGE_BLANK_SQL: tuple[tuple[str, str], ...] = (
    ("rr_snapshots", "UPDATE rr_snapshots SET ir_json = '' WHERE project_id = ?"),
    ("rr_snapshot_calls", "UPDATE rr_snapshot_calls SET response_gz = NULL"
                          " WHERE snapshot_id IN (SELECT id FROM rr_snapshots WHERE project_id = ?)"),
    ("rr_states", "UPDATE rr_states SET state_json = '', summary_text = NULL"
                  " WHERE snapshot_id IN (SELECT id FROM rr_snapshots WHERE project_id = ?)"),
    ("rr_panels", "UPDATE rr_panels SET decision_text = NULL, risk_spec_json = NULL, brief_gz = NULL"
                  " WHERE target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    ("rr_panel_calls", "UPDATE rr_panel_calls SET result_gz = NULL"
                       " WHERE target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    ("rr_seat_opinions", "UPDATE rr_seat_opinions SET opinion_json = '', excerpt_for_rag = NULL"
                         " WHERE target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
    ("rr_findings", "UPDATE rr_findings SET finding_json = '' WHERE project_id = ?"),
    ("rr_character", "UPDATE rr_character SET statement = '' WHERE project_id = ?"),
    # 브리프가 부른 외부 VOC·문헌 **원문**이다(§5.6.2). 비우지 않으면 폐기·코퍼스 제외 뒤에도 DB 와
    # 반출 JSONL 에 남는다 — rr_panel_calls.result_gz 와 같은 성질의 열이다.
    ("rr_brief_calls", "UPDATE rr_brief_calls SET result_gz = NULL"
                       " WHERE target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)"),
)


def _purge_exports(project_id: str) -> int:
    """`$DATA_DIR/exports/` 에서 그 과제가 실린 사본을 지운다(plan §5.2.6 6층)."""
    out_dir = config.settings.data_dir / export_module.EXPORTS_DIRNAME
    removed = 0
    if not out_dir.is_dir():
        return 0
    for path in out_dir.glob("*.jsonl"):
        try:
            if project_id in path.read_text(encoding="utf-8", errors="ignore"):
                path.unlink()
                removed += 1
        except OSError:                          # 파일 정리 실패는 비치명적이다 — remaining 에 남지 않는다.
            continue
    return removed


@router.post("/projects/{project_id}/purge")
def purge_project(project_id: str, body: PurgeBody,
                  ident: identity.Identity = Depends(identity.current)) -> dict:
    """과제 폐기(owner 또는 admin) — 행 삭제가 아니라 원문 열을 비우는 tombstone 이다(plan §5.2.6).

    해시·카운트·`rr_audit`·`rr_registry_status_log` 는 남는다. 다른 과제가 인용한 `reg:`·`narr:` 는
    dangling 이 아니라 '폐기된 과제 — 원문 없음' 으로 해석된다.
    """
    actor = _require_owner(project_id, ident)
    store = get_store()
    project = store.query_one("SELECT code, status FROM rr_projects WHERE id = ?", (project_id,))
    if project is None:
        raise AppError("E404", f"과제({project_id}) 를 찾을 수 없습니다.", 404)
    if project["status"] == "purged":
        raise AppError("already_purged", "이미 폐기된 과제입니다.", 409)
    if (body.code or "").strip() != project["code"]:
        raise AppError("code_mismatch", "과제 코드가 일치하지 않습니다.", 422)

    now = now_epoch()
    layers: dict[str, dict] = {}
    with store.tx():
        blanked: dict[str, int] = {}
        for table, sql in PURGE_BLANK_SQL:
            blanked[table] = int(store.execute(sql, (project_id,)) or 0)
        cancelled_n = store.execute(
            "UPDATE rr_jobs SET state = 'cancelled', state_by = ?, state_at = ?"
            " WHERE state IN ('queued','running','paused','cancelling')"
            " AND target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)",
            (actor, now, project_id))
        skipped_n = store.execute(
            "UPDATE rr_coverage SET status = 'skipped', reason = 'project_purged', status_source = 'code',"
            " updated_at = ? WHERE status IN ('pending','assigned','running','deferred','carried')"
            " AND target_key IN (SELECT target_key FROM rr_targets WHERE project_id = ?)",
            (now, project_id))
        layers["db"] = {"blanked": blanked, "jobs_cancelled": int(cancelled_n or 0),
                        "coverage_skipped": int(skipped_n or 0)}

        # 2층 학습 — 기여를 지우고 delta 선례·패턴을 재합산한다(코퍼스 분모에서 빠진다).
        contrib_n = store.execute(
            "DELETE FROM rr_delta_contrib WHERE target_key IN"
            " (SELECT target_key FROM rr_targets WHERE project_id = ?)", (project_id,))
        store.execute(
            "UPDATE rr_projects SET status = 'purged', purged_at = ?, corpus_excluded = 1,"
            " excluded_reason = 'user', updated_at = ? WHERE id = ?", (now, now, project_id))
        priors = int(learning.recompute_label_priors(store, now=now) or 0)
        mined = learning.mine_patterns(store, owner_sub=actor, now=now) or {}
        metrics_n = store.execute(
            "UPDATE rr_metrics SET value = NULL WHERE dimension = 'project' AND key = ?", (project_id,))
        layers["learning"] = {
            "delta_contrib_deleted": int(contrib_n or 0),
            "delta_priors_rows": priors,
            "patterns_rows": len(mined.get("created") or ()) + len(mined.get("updated") or ()),
            "metrics_invalidated": int(metrics_n or 0),
        }
        layers["files"] = {"exports_removed": _purge_exports(project_id)}

        remaining = [
            {"layer": "adh", "reason": "delete_api_absent",
             "detail": "AIDataHub 레코드는 같은 _external_id 로 빈 UPSERT 만 가능하고 임베딩 잔여 벡터는 재색인 전까지 남는다."},
            {"layer": "ra", "reason": "no_delete_permission",
             "detail": "RA 코드 무수정 원칙상 삭제 권한이 없는 객체는 status='retracted' 표기만 남는다."},
            {"layer": "portal_conversations", "reason": "not_owned",
             "detail": "다른 사용자 소유 대화는 지울 수 없다."},
            {"layer": "drive", "reason": "retention_window",
             "detail": "Drive app-data tar 5세대는 보존 주기가 지나야 사라진다."},
        ]
        report = {"project_id": project_id, "purged_at": now, "by": actor, "reason": body.reason,
                  "layers": layers, "remaining": remaining}
        store.execute("UPDATE rr_projects SET purge_report_json = ? WHERE id = ?",
                      (canonical_json(report), project_id))
        _audit(store, actor, scope="project", subject_id=project_id, project_id=project_id,
               action="project.purge", before={"status": project["status"]}, after={"status": "purged"},
               reason=body.reason)
    return {"job_id": project_id, "status": "purged", "purge_report": report}


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
    # 게이트웨이 실측으로 카드 상태를 정한다 — 고정 목록으로 적으면 캡처가 도는데도 '연결 안 됨' 이라고 적힌다.
    kind_root = body.kind.split("_")[0]
    adapter = next((a for a in adapters_registry.discover_adapters(token=ident.token)
                    if a["kind"] == kind_root), None)
    reachable = bool(adapter and adapter["tools_ok"])
    if adapter is None:
        detail = "adapter_unknown"
    elif reachable:
        detail = f"tools_ok app_key={adapter['app_key']}"
    else:
        missing = ",".join(adapter["tools_missing"]) or "-"
        detail = f"adapter={adapter['status']} missing={missing}"
        if adapter["gateway_error"]:
            detail += f" gateway_error={adapter['gateway_error']}"
    probe = {
        "reachable": reachable,
        "detail": detail,
        # mcad·dyna 는 REST 가 정본이고 게이트웨이 MCP 는 폴백이다(§2.5.1) — 실제 등급은 캡처가 정한다.
        "capture_mode": "rest_primary" if reachable else None,
        "status": "linked" if reachable else "unreachable",
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
    # 상한 초과 모델을 그래도 동결하겠다는 명시 요청(그때 예산은 600 s 다, plan §2.11.3).
    allow_large: bool = False


LARGE_BUDGET_S = 600


def _check_model_size(captured: dict, allow_large: bool) -> None:
    """리프·계면 수가 `risk_max_leaf`·`risk_max_interfaces` 를 넘으면 409 `model_too_large`(plan §2.11.3)."""
    leaves = 0
    interfaces = 0
    for result in captured.get("results") or ():
        stats = (result.get("source") or {}).get("stats") or {}
        leaves += int(stats.get("leaf_instances") or 0)
        interfaces += int(stats.get("interfaces") or 0)
    max_leaf = int(config.settings.risk_max_leaf)
    max_iface = int(config.settings.risk_max_interfaces)
    if leaves <= max_leaf and interfaces <= max_iface:
        return
    if allow_large:
        return
    raise AppError(
        "model_too_large",
        f"모델이 상한을 넘습니다 — 리프 {leaves}/{max_leaf} · 계면 {interfaces}/{max_iface}."
        " 그래도 동결하려면 allow_large=true 로 다시 보내세요(예산 600 s).",
        409,
        detail={"leaf": leaves, "interfaces": interfaces, "max_leaf": max_leaf,
                "max_interfaces": max_iface, "budget_s": LARGE_BUDGET_S},
    )


# ---------------------------------------------------------------- 스냅샷 잡 상태기계(plan §2.11.3 · §0.9 P1-22)
SNAPSHOT_JOB_STATES = ("queued", "running", "done", "partial", "failed")


def _snapshot_job_start(store: Any, *, job_id: str, project_id: str, owner_sub: str, label: str | None,
                        kinds: list[str], params: dict, budget_s: int) -> None:
    """잡 행 1건(queued→running). 실패해도 이 행이 남아 무엇이 왜 실패했는지가 보인다."""
    now = now_epoch()
    store.execute(
        "INSERT INTO rr_snapshot_jobs(id, project_id, owner_sub, label, kinds_json, params_json, state,"
        " budget_s, started_at, created_at) VALUES (?,?,?,?,?,?, 'running', ?,?,?)",
        (job_id, project_id, owner_sub, label, canonical_json(kinds), canonical_json(params),
         budget_s, now, now),
    )


def _snapshot_job_finish(store: Any, job_id: str, *, state: str, snapshot_id: str | None = None,
                         error: dict | None = None, calls: int = 0, calls_failed: int = 0,
                         started: int | None = None) -> None:
    now = now_epoch()
    store.execute(
        "UPDATE rr_snapshot_jobs SET state = ?, snapshot_id = ?, error_json = ?, calls_n = ?,"
        " calls_failed_n = ?, elapsed_ms = ?, finished_at = ? WHERE id = ?",
        (state, snapshot_id, canonical_json(error) if error else None, calls, calls_failed,
         max(0, (now - int(started or now)) * 1000), now, job_id),
    )


def close_stale_snapshot_jobs(store: Any) -> int:
    """기동 시 `state='running'` 이던 행을 failed(error_json.stage='restart')로 마감한다(plan §2.11.3)."""
    rows = store.query("SELECT id FROM rr_snapshot_jobs WHERE state = 'running'", ())
    for row in rows:
        _snapshot_job_finish(store, str(row["id"]), state="failed",
                             error={"stage": "restart", "message": "앱이 재기동해 잡을 마감했다."})
    return len(rows)


def reuse_prior_calls(store: Any, project_id: str, calls: list[dict]) -> int:
    """직전 잡의 `ok=1`·같은 `args_hash` 호출을 재사용 표기한다 — 소스를 다시 부르지 않았다는 사실을 남긴다.

    실제 재호출 회피는 캡처 계층의 몫이고, 여기서는 그 사실을 `reused_from_call_id` 로 기록한다(§2.11.3).
    """
    reused = 0
    for call in calls:
        # 전사 집계는 args 가 늘 {} 라 두 번째 스냅샷부터 전부 걸린다 — 게다가 시변 집계라 재사용이 틀렸다
        # (`fetched_at` 이 있는 이유다). 소스 호출만 센다(§2.11.3).
        if str(call.get("source_kind") or "") == CONTEXT_CALL_KIND:
            continue
        args_hash = sha256_hex(canonical_json(call.get("args") or {}))
        row = store.query_one(
            "SELECT call_id FROM rr_snapshot_calls WHERE args_hash = ? AND ok = 1 AND tool = ?"
            " AND snapshot_id IN (SELECT id FROM rr_snapshots WHERE project_id = ?)"
            " ORDER BY started_at DESC LIMIT 1",
            (args_hash, str(call.get("tool") or ""), project_id))
        if row is not None:
            call["reused_from_call_id"] = str(row["call_id"])
            reused += 1
    return reused


def refresh_source_probes(store: Any, project_id: str, calls: list[dict]) -> int:
    """캡처가 실제로 본 것으로 소스 카드의 probe 를 갱신한다 — 측정값에 **나이**가 생기지 않게.

    probe 는 `POST /projects/{id}/sources` 가 연결하는 순간 한 번만 적혔다. 그래서 그때 게이트웨이를
    못 읽었으면 카드는 그 뒤로 영구히 `unreachable` 이라 적혀 있었다 — 방금 캡처가 그 소스를 200 으로
    읽었는데도 그렇다. 어댑터 발견 배선(checklist 1장, 2026-09-02)이 **연결 시점**의 같은 거짓말을
    고쳤고, 이것은 시간이 지나면 되살아나던 쪽이다. 캡처 성공은 그 자체로 도달 측정이므로 되쓴다.

    `system_status`(선택 호출)와 전사 집계(`CONTEXT_CALL_KIND`)는 세지 않는다 — 캡처의 `failed_calls`
    판정과 같은 제외다. 호출이 하나도 없던 kind 는 건드리지 않는다(미측정은 실패가 아니다).
    """
    seen: dict[str, dict] = {}
    for call in calls:
        kind = str(call.get("source_kind") or "")
        if not kind or kind == CONTEXT_CALL_KIND or str(call.get("tool") or "").endswith("system_status"):
            continue
        slot = seen.setdefault(kind, {"ok": 0, "failed": [], "app_key": call.get("app_key")})
        if call.get("ok", True):
            slot["ok"] += 1
        else:
            slot["failed"].append(f"{call.get('tool')}={call.get('error') or 'error'}")
    updated = 0
    now = now_epoch()
    for row in store.query(
            "SELECT id, kind, probe_json FROM rr_sources WHERE project_id = ?", (project_id,)):
        slot = seen.get(str(row["kind"]))
        if slot is None:
            continue
        reachable = not slot["failed"]
        detail = (f"capture_ok calls={slot['ok']} app_key={slot['app_key']}" if reachable
                  else "capture_failed " + " ".join(slot["failed"][:3]))
        probe = {**_loads(row["probe_json"], {}), "reachable": reachable, "detail": detail,
                 "capture_mode": "rest_primary" if reachable else None,
                 "status": "linked" if reachable else "unreachable"}
        store.execute("UPDATE rr_sources SET probe_json = ?, probe_at = ? WHERE id = ?",
                      (canonical_json(probe), now, row["id"]))
        updated += 1
    return updated


@router.post("/projects/{project_id}/snapshots")
def create_snapshot(project_id: str, body: SnapshotBody,
                    ident: identity.Identity = Depends(identity.current)) -> dict:
    """스냅샷 동결 — 등록된 소스 카드를 어댑터가 읽고 ir_builder 가 IR 을 동결한다(plan §2.11.3).

    rr_jobs 는 타깃 패널 전용 표라 여기서는 백그라운드 워커를 띄우지 않고 동기로 캡처하되,
    `rr_snapshot_jobs` 상태기계(queued→running→done|partial|failed)는 그대로 남긴다 — 실패해도 행이 남아
    무엇이 왜 실패했는지가 보이고, 그 잡의 호출 행은 `snapshot_id IS NULL` 로 원문을 지킨다(§2.11.3).
    반환은 `{snapshot_id, ir_hash, reused, partial, blocked, gates_summary, degraded, job_id, job_state}` 다.
    """
    owner_sub = _require_user(ident)
    _project_row(project_id, owner_sub)
    store = get_store()
    job_id = new_uuid()
    started = now_epoch()
    budget_s = LARGE_BUDGET_S if body.allow_large else int(config.settings.risk_snapshot_budget_s)
    _snapshot_job_start(store, job_id=job_id, project_id=project_id, owner_sub=owner_sub,
                        label=body.label, kinds=list(body.kinds),
                        params={"report_ids": body.report_ids,
                                "detect_result_file_id": body.detect_result_file_id,
                                "allow_large": bool(body.allow_large)}, budget_s=budget_s)
    # 만료 PAT 는 쓰지 않는다 — 값이 있기만 하면 쓰면 서비스 PAT 폴백이 죽어 게이트웨이 401 로 강등된다
    # (runner.resolve_credential·roster.credential 과 같은 규칙).
    credential = store.get_credential(owner_sub) or {}
    portal_pat = identity.credential_pat(credential)
    if int(credential.get("pat_exp") or 0) <= now_epoch() + runner.CREDENTIAL_MARGIN_S:
        portal_pat = None
    # 사람이 시작한 캡처다 — 서비스 PAT 가 없으면 호출자 본인의 heax 토큰으로 REST 를 읽는다.
    channels = adapters_registry.clients_from_settings(
        config.settings, config.load_secrets(config.settings.data_dir), portal_pat=portal_pat,
        heax_token=ident.token)
    principal = adapters_base.Principal(owner_sub=owner_sub, portal_pat=channels["portal_pat"],
                                        service_pat=channels["service_pat"])
    try:
        captured = adapters_registry.capture_all(
            sources=_project_sources(project_id), principal=principal, mcp_client=channels["mcp"],
            rest_client=channels["rest"], kinds=list(body.kinds) or None, report_ids=body.report_ids,
            detect_result_file_id=body.detect_result_file_id,
            tool_names=channels.get("tool_names") or ())
    except AppError as exc:
        # 캡처가 통째로 실패해도 잡 행은 남는다 — 그 잡의 호출 원문은 snapshot_id NULL 로 보존된다.
        _snapshot_job_finish(store, job_id, state="failed", started=started,
                             error={"stage": "capture", "message": exc.message, "code": exc.code})
        raise
    finally:
        # 채널은 자기 httpx.Client 를 소유한다 — 닫지 않으면 스냅샷 요청마다 소켓이 샌다(roster.fetch_for_target 과 같은 처리).
        for channel in (channels["mcp"], channels["rest"]):
            if channel is not None:
                channel.close()
    calls = list(captured["calls"])
    # 버전 조회(system_status)는 선택 호출이라 실패해도 부분 캡처가 아니다 — 그 사실은 degraded 로 남는다(§2.2).
    # 전사 집계(source_kind='context')도 소스 캡처가 아니라 봉투 문맥이라 실패가 잡을 partial 로 만들지 않는다(§2.2).
    failed_calls = [c for c in calls
                    if not c.get("ok", True) and not str(c.get("tool") or "").endswith("system_status")
                    and str(c.get("source_kind") or "") != CONTEXT_CALL_KIND]
    try:
        _check_model_size(captured, body.allow_large)
    except AppError as exc:
        _snapshot_job_finish(store, job_id, state="failed", started=started, calls=len(calls),
                             calls_failed=len(failed_calls),
                             error={"stage": "model_size", "message": exc.message, "code": exc.code})
        # 실패 잡의 호출 원문은 스냅샷 없이 남긴다(30일 보존, §2.11.4).
        ir_builder.record_calls(store, None, owner_sub, calls, job_id=job_id, start_seq=1)
        raise
    reused = reuse_prior_calls(store, project_id, calls)
    # 카드가 '연결 안 됨' 이라 적힌 채 캡처는 돌고 있는 상태를 없앤다 — 측정은 방금 한 이 캡처다.
    refresh_source_probes(store, project_id, calls)
    prior = store.query_one(
        "SELECT id FROM rr_snapshots WHERE project_id = ? ORDER BY created_at DESC, id LIMIT 1", (project_id,))
    out = ir_builder.freeze_snapshot(
        store, project_id=project_id, owner_sub=owner_sub, label=body.label or f"snap-{now_epoch()}",
        adapter_results=captured["results"], calls=calls, job_id=job_id,
        context=captured.get("context"),
        snapshot_id=captured["snapshot_id"], derived_from=prior["id"] if prior else None)
    state = "partial" if (out.get("partial") or failed_calls) else "done"
    _snapshot_job_finish(store, job_id, state=state, snapshot_id=out["snapshot_id"], started=started,
                         calls=len(calls), calls_failed=len(failed_calls),
                         error={"stage": "capture_partial",
                                "failed_calls": [c.get("tool") for c in failed_calls]} if failed_calls else None)
    # 재사용이면 남의 스냅샷이다 — 이번 잡의 부분 여부를 거기에 덮어쓰면 완주했던 스냅샷이 부분으로 바뀐다.
    # 잡→스냅샷 연결은 rr_snapshot_jobs 에 이미 있고(여러 잡이 한 스냅샷을 재사용한다), 스냅샷의 job_id 는
    # 자기를 만든 잡을 가리켜야 한다.
    if not out.get("reused"):
        store.execute("UPDATE rr_snapshots SET job_id = ?, capture_partial = ? WHERE id = ?",
                      (job_id, 1 if state == "partial" else 0, out["snapshot_id"]))
    return {**out, "job_id": job_id, "job_state": state, "calls_reused": reused}


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


# ================================================================ 요구 규격(plan §2.8b · §8.2.3 4행)
class RequirementItem(BaseModel):
    kind: str
    name: str
    op: str | None = None
    value_json: Any = None
    unit: str | None = None
    source_ref: str | None = None


class RequirementDecision(BaseModel):
    status: str
    waive_reason: str | None = Field(default=None, max_length=300)


class InheritBody(BaseModel):
    from_project_id: str


@router.get("/projects/{project_id}/requirements")
def get_requirements(project_id: str, kind: str | None = None, status: str | None = None,
                     ident: identity.Identity = Depends(identity.current)) -> dict:
    """과제의 요구 목록(kind·status 필터). 판정·여유 계산은 state 가 하고 여기서는 원장만 읽는다."""
    owner_sub = _require_user(ident)
    _project_row(project_id, owner_sub)
    return requirements.list_requirements(get_store(), project_id, kind=kind, status=status)


@router.post("/projects/{project_id}/requirements")
def post_requirements(project_id: str, body: list[RequirementItem],
                      ident: identity.Identity = Depends(identity.current)) -> dict:
    """요구 배열 UPSERT — `UNIQUE(project_id, kind, name)` 기준. 전건 선검사라 한 건이라도 틀리면 아무 행도 쓰지 않는다."""
    owner_sub = _require_user(ident)
    project = _project_row(project_id, owner_sub)
    # owner_sub 는 호출자가 아니라 과제 소유 앵커다(plan §5.2.1 — 하위 표의 owner_sub 는 rr_projects 값의 복제다).
    return requirements.upsert_requirements(
        get_store(), project_id, project["owner_sub"], [item.model_dump() for item in body])


@router.put("/requirements/{requirement_id}")
def put_requirement(requirement_id: str, body: RequirementDecision,
                    ident: identity.Identity = Depends(identity.current)) -> dict:
    """요구 1건의 status 결정(candidate|confirmed|waived). waived 는 사유 필수이고 rr_audit 1행이 남는다."""
    owner_sub = _require_user(ident)
    store = get_store()
    before = store.query_one(
        "SELECT id, project_id, status, waive_reason FROM rr_requirements WHERE id = ?", (requirement_id,))
    if before is None:
        raise AppError("E404", f"요구를 찾을 수 없습니다 — {requirement_id}.", 404)
    _project_row(before["project_id"], owner_sub)
    updated = requirements.decide_requirement(
        store, requirement_id, status=body.status, waive_reason=body.waive_reason, actor_sub=owner_sub)
    _audit(store, owner_sub, scope="project", subject_id=requirement_id, project_id=before["project_id"],
           action="requirement.decide",
           before={"status": before["status"], "waive_reason": before["waive_reason"]},
           after={"status": updated["status"], "waive_reason": updated["waive_reason"]},
           reason=body.waive_reason)
    return updated


@router.post("/projects/{project_id}/requirements/inherit")
def post_requirements_inherit(project_id: str, body: InheritBody,
                              ident: identity.Identity = Depends(identity.current)) -> dict:
    """계보 과제의 요구를 복사한다(status='candidate'·inherited_from, 멱등). 원본에도 조회 규약을 먼저 적용한다."""
    owner_sub = _require_user(ident)
    store = get_store()
    project = _project_row(project_id, owner_sub)
    source = store.query_one("SELECT owner_sub FROM rr_projects WHERE id = ?", (body.from_project_id,))
    # 존재 여부는 모듈이 404 source_project_not_found 로 가른다 — 여기서는 있는 과제의 조회 규약만 본다.
    if source is not None and source["owner_sub"] != owner_sub:
        raise AppError("not_a_member", f"승계 원본 과제를 볼 수 없습니다 — {body.from_project_id}.", 403)
    return requirements.inherit_requirements(store, project_id, project["owner_sub"], body.from_project_id)


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
SNAPSHOT_PARTS = ("ir", "state", "nodes", "edges", "calls", "rule_hits")


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
    if part == "rule_hits":
        # 코드가 기계적으로 잡아낸 상태 위반 — 리스크 후보의 1차 목록이다. 별 라우트로만 있어
        # MCP 에서 안 보였다(도구를 늘리지 않고 part 한 칸으로 연다).
        row = store.query_one(
            "SELECT rule_hits_json, rule_version FROM rr_states WHERE snapshot_id = ?", (snapshot_id,))
        if row is None:
            raise AppError("E404", f"rr_state 가 없습니다 — {snapshot_id}.", 404)
        return {"snapshot_id": snapshot_id, "rule_version": row["rule_version"],
                "rule_hits": _loads(row["rule_hits_json"], [])}
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


# ---------------------------------------------------------------- 게이트 ack(plan §8.2.3 · §3.2.2)
GATE_KEYS: tuple[str, ...] = ("G1", "G2", "G3", "G4", "G5", "G6", "G7")
GATE_ACK_REASON_MAX = 300


class GateAckBody(BaseModel):
    reason: str = Field(default="", max_length=GATE_ACK_REASON_MAX)
    gates_hash: str | None = None


def _gate_state(snapshot_id: str, gate: str, owner_sub: str) -> tuple[dict, dict]:
    """(gates_json 전체, 그 게이트 레코드). 어휘 밖·pass=true·G6 은 422, 상태 부재는 404."""
    if gate not in GATE_KEYS:
        raise AppError("E100", f"게이트는 {list(GATE_KEYS)} 중 하나여야 합니다 — {gate!r}.", 422)
    _snapshot_row(snapshot_id, owner_sub)
    row = get_store().query_one("SELECT gates_json FROM rr_states WHERE snapshot_id = ?", (snapshot_id,))
    if row is None:
        raise AppError("E404", f"rr_state 가 없습니다 — {snapshot_id}.", 404)
    gates = _loads(row["gates_json"], {})
    record = gates.get(gate)
    if not isinstance(record, dict):
        raise AppError("E404", f"이 스냅샷에 {gate} 레코드가 없습니다.", 404)
    # G6 은 blocking 이라 ack 로 넘길 수 없다 — pass=false 든 unknown_blocking 이든 같다(§2.12).
    if record.get("blocking") or gate == "G6":
        raise AppError("gate_blocking", f"{gate} 는 차단 게이트라 ack 로 넘길 수 없습니다 — 소스를 고쳐 재캡처하세요.", 422)
    if record.get("pass") is True:
        raise AppError("gate_passing", f"{gate} 는 pass 라 ack 할 것이 없습니다.", 422)
    return gates, record


def _save_gate_ack_state(store: Any, snapshot_id: str, gates: dict, gate: str, ack: dict | None) -> dict:
    """gates_json 의 그 게이트 한 칸에 ack 3필드를 반영해 되쓴다(판정 pass 는 바뀌지 않는다, §3.2.2)."""
    record = dict(gates[gate])
    record["ack_by"] = (ack or {}).get("by")
    record["ack_at"] = (ack or {}).get("at")
    record["ack_reason"] = (ack or {}).get("reason")
    gates[gate] = record
    store.execute("UPDATE rr_states SET gates_json = ? WHERE snapshot_id = ?",
                  (canonical_json(gates), snapshot_id))
    return record


@router.post("/snapshots/{snapshot_id}/gates/{gate}/ack")
def post_gate_ack(snapshot_id: str, gate: str, body: GateAckBody,
                  ident: identity.Identity = Depends(identity.current)) -> dict:
    """fail 게이트에 사유를 적고 진행한다. ack 가 붙어도 `pass` 는 false 로 남는다(plan §3.2.2)."""
    owner_sub = _require_user(ident)
    reason = (body.reason or "").strip()
    if not reason:
        raise AppError("reason_required", "ack 에는 사유가 필요합니다(≤300자).", 422)
    gates, record = _gate_state(snapshot_id, gate, owner_sub)
    current_hash = state_module.gates_hash(gates)
    if body.gates_hash and body.gates_hash != current_hash:
        raise AppError("gates_hash_stale", "그 사이 게이트가 재계산됐습니다 — 다시 읽고 ack 하세요.", 409,
                       detail={"gates_hash": current_hash})
    store = get_store()
    now = now_epoch()
    with store.tx():
        store.execute(
            "INSERT INTO rr_gate_acks(snapshot_id, gate, owner_sub, diff_id, ack_by, ack_at, ack_reason,"
            " gates_hash) VALUES (?,?,?,NULL,?,?,?,?)"
            " ON CONFLICT(snapshot_id, gate) DO UPDATE SET ack_by=excluded.ack_by, ack_at=excluded.ack_at,"
            " ack_reason=excluded.ack_reason, gates_hash=excluded.gates_hash,"
            " revoked_by=NULL, revoked_at=NULL",
            (snapshot_id, gate, owner_sub, owner_sub, now, reason, current_hash),
        )
        record = _save_gate_ack_state(store, snapshot_id, gates, gate,
                                      {"by": owner_sub, "at": now, "reason": reason})
        _audit(store, owner_sub, scope="snapshot", subject_id=snapshot_id, action="gate.ack",
               after={"gate": gate, "gates_hash": current_hash}, reason=reason)
    return {"gate": gate, "ack_by": owner_sub, "ack_at": now, "ack_reason": reason,
            "gates_hash": current_hash, "pass": record.get("pass")}


@router.delete("/snapshots/{snapshot_id}/gates/{gate}/ack")
def delete_gate_ack(snapshot_id: str, gate: str,
                    ident: identity.Identity = Depends(identity.current)) -> dict:
    """ack 취소 — 행을 지우지 않고 `revoked_by`·`revoked_at` 을 찍는다(plan §5.2.1 삭제 없음)."""
    owner_sub = _require_user(ident)
    gates, _ = _gate_state(snapshot_id, gate, owner_sub)
    store = get_store()
    row = store.query_one(
        "SELECT ack_by, ack_at, revoked_at FROM rr_gate_acks WHERE snapshot_id = ? AND gate = ?",
        (snapshot_id, gate))
    if row is None or row["revoked_at"] is not None:
        raise AppError("E404", f"취소할 ack 가 없습니다 — {snapshot_id}/{gate}.", 404)
    now = now_epoch()
    with store.tx():
        store.execute(
            "UPDATE rr_gate_acks SET revoked_by = ?, revoked_at = ? WHERE snapshot_id = ? AND gate = ?",
            (owner_sub, now, snapshot_id, gate))
        record = _save_gate_ack_state(store, snapshot_id, gates, gate, None)
        _audit(store, owner_sub, scope="snapshot", subject_id=snapshot_id, action="gate.ack",
               before={"gate": gate, "ack_by": row["ack_by"]}, after={"gate": gate, "revoked": True})
    return {"gate": gate, "ack_by": None, "ack_at": None, "ack_reason": None,
            "gates_hash": state_module.gates_hash(gates), "pass": record.get("pass"),
            "revoked_by": owner_sub, "revoked_at": now}


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


# 목록 경로 3종(정본 §8.2.4 RiskHomePage '상단 탭 과제/비교(diff 목록)/타깃/보고서').
# 이 셋이 없어서 첫 화면 탭 3개가 '목록 경로가 아직 없습니다' 였다 — 앱이 "여기 무엇이 있는지" 를
# 보여 줄 방법이 없었다. 항목 경로(`/diffs/{id}` 등)만 있고 컬렉션 경로가 없던 자리다.
# 무거운 본문(diff_json·summary_text)은 싣지 않는다 — 목록은 고르기 위한 것이고 전문은 항목 경로가 준다.
LIST_LIMIT_DEFAULT, LIST_LIMIT_MAX = 50, 200


def _list_window(limit: int, offset: int) -> tuple[int, int]:
    """목록 창 — 상한을 넘기면 자르고, 음수는 0 으로 접는다(요청이 DB 를 통째로 끌지 않게)."""
    return max(1, min(int(limit), LIST_LIMIT_MAX)), max(0, int(offset))


@router.get("/diffs")
def list_diffs(project_id: str | None = None, limit: int = LIST_LIMIT_DEFAULT, offset: int = 0,
               ident: identity.Identity = Depends(identity.current)) -> dict:
    """비교 목록 — 최신순. `project_id` 는 base·target 어느 쪽이든 그 과제가 걸린 diff 를 고른다."""
    owner_sub = _require_user(ident)
    take, skip = _list_window(limit, offset)
    store = get_store()
    where = ["owner_sub = ?"]
    params: list[Any] = [owner_sub]
    if project_id:
        where.append("(base_project_id = ? OR target_project_id = ?)")
        params += [project_id, project_id]
    clause = " AND ".join(where)
    total = store.query_one(f"SELECT COUNT(*) AS n FROM rr_diffs WHERE {clause}", tuple(params))["n"]
    rows = store.query(
        "SELECT id, base_snapshot_id, target_snapshot_id, base_project_id, target_project_id, pair_kind,"
        " diff_version, summary_status, stats_json, comparability_json, gates_json, diff_hash, created_at"
        f" FROM rr_diffs WHERE {clause} ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
        (*params, take, skip))
    diffs = []
    for row in rows:
        item = dict(row)
        item["stats"] = _loads(item.pop("stats_json"), {})
        # 비교 가능성·게이트는 '이 diff 를 믿어도 되나' 의 판정이라 목록에서 바로 보여야 한다(§3.3.6·§2.12).
        item["comparability"] = _loads(item.pop("comparability_json"), {})
        gates = _loads(item.pop("gates_json"), {}) or {}
        item["blocked"] = state_module.is_blocked(gates)
        item["gates_failed"] = sorted(k for k, v in gates.items() if v.get("pass") is False)
        diffs.append(item)
    return {"diffs": diffs, "total": int(total or 0), "limit": take, "offset": skip}


@router.get("/targets")
def list_targets(project_id: str | None = None, include_superseded: bool = False,
                 limit: int = LIST_LIMIT_DEFAULT, offset: int = 0,
                 ident: identity.Identity = Depends(identity.current)) -> dict:
    """타깃 목록 — 최신순. 기본은 살아 있는 타깃만이다(§4.8 로 닫힌 것은 `include_superseded` 로 본다)."""
    owner_sub = _require_user(ident)
    take, skip = _list_window(limit, offset)
    store = get_store()
    where = ["owner_sub = ?"]
    params: list[Any] = [owner_sub]
    if project_id:
        where.append("project_id = ?")
        params.append(project_id)
    if not include_superseded:
        where.append("superseded_by IS NULL")
    clause = " AND ".join(where)
    total = store.query_one(f"SELECT COUNT(*) AS n FROM rr_targets WHERE {clause}", tuple(params))["n"]
    rows = store.query(
        "SELECT target_key, kind, ref_id, project_id, base_project_id, ir_hash, level, close_level,"
        " verdict_candidate, verdict_final, superseded_by, report_ids_json, roster_frozen_at,"
        " created_at, updated_at"
        f" FROM rr_targets WHERE {clause} ORDER BY created_at DESC, target_key LIMIT ? OFFSET ?",
        (*params, take, skip))
    targets = []
    for row in rows:
        item = dict(row)
        item["report_ids"] = _loads(item.pop("report_ids_json"), [])
        # 진행판 요약 — 목록에서 '얼마나 됐나' 가 보이지 않으면 사람이 타깃마다 들어가 봐야 한다.
        summary = planner.coverage_summary(store, item["target_key"])
        item["roster_size"] = summary["roster_size"]
        item["coverage_pct"] = (round(100.0 * summary["terminal_n"] / summary["roster_size"], 1)
                                if summary["roster_size"] else None)
        targets.append(item)
    return {"targets": targets, "total": int(total or 0), "limit": take, "offset": skip}


@router.get("/reports")
def list_reports(project_id: str | None = None, limit: int = LIST_LIMIT_DEFAULT, offset: int = 0,
                 ident: identity.Identity = Depends(identity.current)) -> dict:
    """보고서 목록 — 앱은 보고서를 소유하지 않는다(§5.3 외부 투영). RA `rpt:` 포인터를 타깃에서 모은다.

    그래서 이 목록은 '어느 타깃이 어떤 보고서를 냈나' 이고, 전문은 RA 가 갖는다 — 앱이 사본을 두지 않는다.
    보고서를 낸 적 없는 타깃은 빠진다(빈 줄로 목록을 채우지 않는다).
    """
    owner_sub = _require_user(ident)
    take, skip = _list_window(limit, offset)
    store = get_store()
    where = ["owner_sub = ?", "report_ids_json IS NOT NULL", "report_ids_json <> '[]'"]
    params: list[Any] = [owner_sub]
    if project_id:
        where.append("project_id = ?")
        params.append(project_id)
    clause = " AND ".join(where)
    rows = store.query(
        "SELECT target_key, kind, project_id, level, verdict_final, report_ids_json, external_sync_json,"
        " updated_at FROM rr_targets"
        f" WHERE {clause} ORDER BY updated_at DESC, target_key", tuple(params))
    reports: list[dict] = []
    for row in rows:
        sync = _loads(row["external_sync_json"], {}) or {}
        for report_id in _loads(row["report_ids_json"], []) or []:
            reports.append({
                "report_id": str(report_id),
                "ref": f"rpt:{report_id}",
                "target_key": row["target_key"], "kind": row["kind"], "project_id": row["project_id"],
                "level": row["level"], "verdict_final": row["verdict_final"],
                # RA 반영 상태 — '앱에는 있는데 RA 에 아직 안 올라간' 보고서를 구분한다(§5.5.3).
                "ra_state": (sync.get("ra") or {}).get("state"),
                "updated_at": row["updated_at"],
            })
    return {"reports": reports[skip:skip + take], "total": len(reports), "limit": take, "offset": skip}


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


def _supersede_previous_target(store: Any, *, project_id: str, new_target_key: str,
                              new_snapshot_id: str, owner_sub: str, now: int) -> dict:
    """새 타깃 T′ 가 생기면 옛 타깃 T 를 닫고 무엇을 승계할지 정한다(plan §4.8 1·3·4·5).

    **`changed_ckeys` 를 모를 때 빈 집합으로 진행하지 않는다.** 빈 집합은 '아무것도 안 바뀌었다' 와 같아서
    등록부는 stale 0건, 좌석은 전원 carried 가 된다 — 재검증 없이 통과시키는 쪽이므로 '없는 리스크' 다.
    두 스냅샷 사이 diff 가 없으면 1단계(닫기)만 하고 3·4·5 는 건너뛰며 그 사실을 응답에 남긴다.
    정본은 "있으면 재사용, 없으면 생성" 이라 하지만 타깃 생성이 diff 를 부수효과로 만들면 게이트 차단·
    비교 불가로 409 가 날 수 있어 **재사용만** 한다(생성은 사람이 `POST /diffs` 로 한다).

    ckey 비교는 전부 `resolve_ckey`(§5.9.1 merged_into 끝까지)를 거친 유효 ckey 다 — 안 거치면 자동 승계로
    병합된 키가 한쪽에서만 맞아 stale·carried 판정이 '어느 스냅샷 키로 계산했는지' 에 따라 갈린다.
    """
    prev = store.query_one(
        "SELECT target_key, kind, ref_id FROM rr_targets WHERE project_id = ? AND target_key <> ?"
        " AND superseded_by IS NULL AND owner_sub = ? ORDER BY created_at DESC, target_key LIMIT 1",
        (project_id, new_target_key, owner_sub))
    if prev is None:
        return {"previous_target_key": None}
    prev_key = str(prev["target_key"])
    store.execute("UPDATE rr_targets SET superseded_by = ?, updated_at = ? WHERE target_key = ?",
                  (new_target_key, now, prev_key))
    out: dict = {"previous_target_key": prev_key, "changed_ckeys": None}

    prev_snapshot = str(prev["ref_id"]) if prev["kind"] == "snap" else _diff_target_snapshot(store, prev["ref_id"])
    diff_row = store.query_one(
        "SELECT id FROM rr_diffs WHERE base_snapshot_id = ? AND target_snapshot_id = ? AND owner_sub = ?"
        " ORDER BY created_at DESC LIMIT 1", (prev_snapshot, new_snapshot_id, owner_sub)) if prev_snapshot else None
    if diff_row is None:
        out["skipped"] = "diff_absent"
        return out

    def resolve(ckey: str) -> str:
        return sameas.resolve_ckey(store, ckey, owner_sub)

    diff_obj = diff_module.get_diff(store, str(diff_row["id"]), owner_sub=owner_sub, part="diff")
    changed = diff_module.changed_ckeys(diff_obj, resolve)
    out["changed_ckeys"] = len(changed)
    out["registry"] = registry_module.invalidate(store, prev_key, new_target_key, changed,
                                                resolve_ckey=resolve)
    # 좌석 carried — 인용 ckey 는 좌석 의견 본문(`cited_ckeys`)에 이미 있다(§6.8.2 네 조건의 입력).
    cited: dict[str, list[str]] = {}
    for row in store.query(
            "SELECT agent_key, opinion_json FROM rr_seat_opinions WHERE target_key = ?", (prev_key,)):
        keys = _loads(row["opinion_json"], {}).get("cited_ckeys") or []
        cited.setdefault(str(row["agent_key"]), []).extend(str(k) for k in keys)
    out["carried"] = planner.apply_carry_over(store, new_target_key, prev_key, cited_ckeys=cited,
                                              changed_ckeys=changed)
    # §4.8 5 — 성격 행은 과제 단위라 옮기지 않고, 인용 ckey 가 변경에 들면 재확인 표기만 남긴다.
    out["character_needs_review"] = _flag_character_needs_review(store, project_id, set(changed), now)
    return out


def _diff_target_snapshot(store: Any, diff_id: Any) -> str | None:
    row = store.query_one("SELECT target_snapshot_id FROM rr_diffs WHERE id = ?", (diff_id,))
    return str(row["target_snapshot_id"]) if row else None


def _flag_character_needs_review(store: Any, project_id: str, changed: set[str], now: int) -> int:
    """성격 서술의 인용 ckey 가 바뀐 주체에 들면 `needs_review=1`(plan §4.8 5).

    status 는 건드리지 않는다 — confirmed 를 코드가 내리지 않는다(사람만 바꾼다).
    """
    flagged = 0
    for row in store.query(
            "SELECT id, cites_json FROM rr_character WHERE project_id = ? AND needs_review = 0", (project_id,)):
        keys = {str((c or {}).get("ckey")) for c in _loads(row["cites_json"], []) if isinstance(c, dict)}
        if keys & changed:
            store.execute("UPDATE rr_character SET needs_review = 1, updated_at = ? WHERE id = ?",
                          (now, row["id"]))
            flagged += 1
    return flagged


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
    reasons: list[str] = []
    for role, sid in zip(("base", "target") if body.kind == "diff" else ("target",), blocked_snapshots):
        state = store.query_one(
            "SELECT blocked, gates_json FROM rr_states WHERE snapshot_id = ?", (sid,))
        if state is None:
            continue
        gate_map = _loads(state["gates_json"], {}) or {}
        reason = state_module.blocked_reason(gate_map)
        if reason is None and not state["blocked"]:
            continue
        gates[role] = gate_map.get("G6")
        reasons.append(reason or "unit_mismatch")
    if gates:
        reason = "unit_mismatch" if "unit_mismatch" in reasons else reasons[0]
        raise AppError("gate_blocked", f"게이트 G6 로 차단된 스냅샷입니다(reason={reason}).", 409,
                       detail={"gates": gates, "reason": reason})

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
        # §4.8 — 옛 타깃을 닫고 승계를 정한다. 로스터 고정 **뒤**여야 carried 가 T′ 좌석 행에 앉는다.
        superseded = _supersede_previous_target(
            store, project_id=project_id, new_target_key=target_key,
            new_snapshot_id=str(snapshot["id"]), owner_sub=owner_sub, now=now)
    plan = planner.tier_plan(store, target_key) if roster["roster_size"] else None
    return {
        "target_key": target_key,
        "superseded": superseded,
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
    """배치 잡 1건(Tier C 는 consent 필수, 러너 자격이 없으면 422 pat_unavailable).

    소유자만이 아니라 그 과제의 editor 도 잡을 만든다 — 잡 행의 `owner_sub` 는 신원 앵커(타깃 소유자)를
    승계하고 실제로 쓰인 자격의 email 은 `credential_email` 에 남는다(plan §0.1.6·§5.2.1).
    """
    email = _require_user(ident)
    row = get_store().query_one(
        "SELECT owner_sub, project_id FROM rr_targets WHERE target_key = ?", (target_key,))
    if row is None:
        raise AppError("E404", f"타깃({target_key}) 을 찾을 수 없습니다.", 404)
    if not _is_admin(ident):
        require_role(row["project_id"], email, "editor")
    return runner.create_job(get_store(), target_key, body.tier, owner_sub=row["owner_sub"],
                             modifiers=body.modifiers, user_memo=body.user_memo,
                             concurrency=body.concurrency, consent=body.consent, requester_sub=email)


JOB_ACTIONS = {"pause": runner.pause_job, "resume": runner.resume_job, "cancel": runner.cancel_job}


@router.post("/jobs/{job_id}/{action}")
def job_action(job_id: str, action: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """일시정지·재개·취소(패널 경계에서 반영). 주체는 rr_jobs.state_by 에 남는다(plan §0.6)."""
    owner_sub = _require_user(ident)
    if action not in JOB_ACTIONS:
        raise AppError("E404", f"모르는 잡 조작입니다 — {action}.", 404)
    _owned_row("SELECT id, owner_sub FROM rr_jobs WHERE id = ?", (job_id,), owner_sub, f"잡({job_id})")
    return JOB_ACTIONS[action](get_store(), job_id, by=owner_sub)


class CoverageBody(BaseModel):
    status: str
    reason: str | None = None


@router.put("/targets/{target_key}/coverage/{agent_key}")
def put_coverage(target_key: str, agent_key: str, body: CoverageBody,
                 ident: identity.Identity = Depends(identity.current)) -> dict:
    """좌석 상태를 사람이 옮긴다 — skipped(사유 필수)와 carried→pending 되돌리기 두 갈래다(plan §6.8.1).

    행에는 `status_source='human'`·`decided_by`·`decided_at` 이 남고 `rr_audit` 에 1행이 붙는다.
    """
    email = _require_user(ident)
    store = get_store()
    row = store.query_one(
        "SELECT owner_sub, project_id FROM rr_targets WHERE target_key = ?", (target_key,))
    if row is None:
        raise AppError("E404", f"타깃({target_key}) 을 찾을 수 없습니다.", 404)
    if not _is_admin(ident):
        require_role(row["project_id"], email, "editor")
    before = store.query_one(
        "SELECT status FROM rr_coverage WHERE target_key = ? AND agent_key = ?", (target_key, agent_key))
    if before is None:
        raise AppError("E404", f"원장 행이 없습니다: {target_key}:{agent_key}", 404)
    if body.status not in ("skipped", "pending"):
        raise AppError("E100", "status 는 'skipped' 또는 'pending'(carried 되돌리기) 여야 합니다.", 422)

    with store.tx():
        if body.status == "skipped":
            out = planner.skip_seat(store, target_key, agent_key, body.reason or "", decided_by=email)
            action = "coverage.skip"
        else:
            out = planner.revert_carried(store, target_key, agent_key, decided_by=email)
            action = "coverage.uncarry"
        _audit(store, email, scope="coverage", subject_id=f"{target_key}#{agent_key}",
               project_id=row["project_id"], action=action, before={"status": before["status"]},
               after={"status": out["status"]}, reason=body.reason)
    return out


# ================================================================ 커버리지·등록부·패널
@router.get("/targets/{target_key}/coverage")
def get_coverage(target_key: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """진행판 — 도메인별 상태·미착석 수·완결 레벨(레벨 계산은 registry.close_level)."""
    return coverage_payload(target_key, owner_sub=_require_user(ident))


def coverage_payload(target_key: str, *, owner_sub: str | None = None) -> dict:
    """`GET /targets/{key}/coverage` 본체 — MCP `risk_get_coverage` 와 같은 함수.

    좌석 행까지 함께 준다(웹은 카운트만 5초 폴링하고 드릴다운을 따로 부르지만, MCP 는 왕복이
    비싸고 '더 돌려야 하나' 판단에 미착석 좌석이 바로 필요하다)."""
    _target_row(target_key, owner_sub)
    store = get_store()
    summary = planner.coverage_summary(store, target_key)
    level = registry_module.close_level(store, target_key, persist=False)
    job = store.query_one(
        "SELECT id, tier, state, pause_reason, panels_done, panels_total, error FROM rr_jobs"
        " WHERE target_key = ? ORDER BY created_at DESC LIMIT 1", (target_key,))
    return {
        "target_key": target_key,
        "job": dict(job) if job is not None else None,
        "roster_size": summary["roster_size"],
        "by_domain": summary["by_domain"],
        "by_status": summary["by_status"],
        "strong": summary["strong"],
        "unseated_n": summary["unseated_n"],
        "level": level["level"],
        "close_level": level["close_level"],
    }


def seats_payload(target_key: str, domain: str | None = None, *, owner_sub: str | None = None) -> dict:
    """`GET /targets/{key}/seats` 본체 — MCP `risk_get_coverage(with_seats=True)` 가 같이 쓴다."""
    _target_row(target_key, owner_sub)
    sql = ("SELECT agent_key, domain, tier, origin, status, reason, panel_id, opinion_id, model,"
           " status_source, decided_by, decided_at, started_at, finished_at"
           " FROM rr_coverage WHERE target_key = ?")
    params: list[Any] = [target_key]
    if domain:
        sql += " AND domain = ?"
        params.append(domain)
    rows = [dict(r) for r in get_store().query(sql + " ORDER BY domain, agent_key", params)]
    return {"target_key": target_key, "domain": domain, "seats": rows}


def panels_payload(target_key: str, *, owner_sub: str | None = None) -> dict:
    """`GET /targets/{key}/panels` 본체 — MCP `risk_list_panels` 와 같은 함수."""
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


def panel_transcript_payload(panel_id: str, *, owner_sub: str | None = None) -> dict:
    """`GET /panels/{id}/transcript` 본체 — MCP `risk_get_panel_transcript` 와 같은 함수."""
    panel = _owned_row(
        "SELECT id, owner_sub, decision_text, risk_spec_json FROM rr_panels WHERE id = ?",
        (panel_id,), owner_sub, f"패널 {panel_id}")
    turns: list[dict] = []
    for row in get_store().query(
            "SELECT agent_key, opinion_json FROM rr_seat_opinions WHERE panel_id = ? ORDER BY agent_key",
            (panel_id,)):
        for turn in _loads(row["opinion_json"], {}).get("turns") or ():
            if not isinstance(turn, dict):
                continue
            turns.append({"seat": row["agent_key"], "round": int(turn.get("round") or 0),
                          "say_excerpt": str(turn.get("say_excerpt") or ""),
                          "position": turn.get("position") or None,
                          "stance": turn.get("stance") or None})
    turns.sort(key=lambda t: (t["round"], t["seat"]))
    spec = _loads(panel["risk_spec_json"], {})
    return {"panel_id": panel_id, "decision_text": panel["decision_text"] or "",
            "turns": turns, "risk_spec": spec or None}


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
    target = store.query_one("SELECT verdict_final FROM rr_targets WHERE target_key = ?", (target_key,))
    return {"target_key": target_key, "rows": rows, "truncated": truncated,
            "verdict_candidate": registry_module.verdict_candidate(store, target_key),
            # 후보는 코드가 내고 확정은 사람이 낸다(§8.2.4) — 화면 헤더가 둘을 한 응답에서 읽는다.
            "verdict_final": target["verdict_final"] if target is not None else None}


@router.get("/targets/{target_key}/registry")
def get_registry(target_key: str, status: str | None = None, severity: str | None = None,
                 domain: str | None = None, ident: identity.Identity = Depends(identity.current)) -> dict:
    owner_sub = _require_user(ident)
    return registry_payload(target_key, owner_sub=owner_sub, status=status, severity=severity, domain=domain)


@router.get("/targets/{target_key}/seats")
def get_seats(target_key: str, domain: str | None = None,
              ident: identity.Identity = Depends(identity.current)) -> dict:
    """도메인 한 칸의 좌석 목록 — `CoverageHeatmap` 셀 클릭의 드릴다운이다(§8.2.4).

    `GET coverage` 는 도메인×상태 카운트만 준다(5 s 폴링이라 가볍게 둔다). 여기서만 행을 편다.
    """
    return seats_payload(target_key, domain, owner_sub=_require_user(ident))


@router.get("/targets/{target_key}/panels")
def get_panels(target_key: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """패널 목록(conv_id · report_id · quality_json · model_json)."""
    return panels_payload(target_key, owner_sub=_require_user(ident))


@router.get("/panels/{panel_id}/transcript")
def get_panel_transcript(panel_id: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """`PanelTranscript` '발언' 탭 — 앱 DB 의 좌석 발언·결정문·risk_spec(§8.2.4).

    포털 conv_store 를 읽지 않는다. 발언은 `rr_seat_opinions.opinion_json.turns` 를 좌석마다 펴서
    라운드 순으로 합친 것이고, 결정문·risk_spec 은 `rr_panels` 원문 그대로다.
    """
    return panel_transcript_payload(panel_id, owner_sub=_require_user(ident))


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


# 등록부 상태 → 라벨 outcome(§7.6 경로 5). mitigated 는 사람 표기만이라 라벨이 없다(label_needed=false).
REGISTRY_LABEL_OUTCOME = {"verified": "confirmed", "dismissed": "refuted"}


def _cluster_finding_ids(store: Any, cluster_key: str, owner_sub: str,
                         target_key: str | None) -> list[str]:
    """그 등록부 클러스터에 실린 finding id — 사람 확정 라벨의 대상."""
    sql = "SELECT finding_id FROM rr_findings WHERE cluster_key = ? AND owner_sub = ?"
    params: list[Any] = [cluster_key, owner_sub]
    if target_key:
        sql += " AND target_key = ?"
        params.append(target_key)
    return [str(r["finding_id"]) for r in store.query(sql + " ORDER BY finding_id", params)]


@router.put("/registry/{cluster_key:path}/status")
def put_registry_status(cluster_key: str, body: RegistryStatusBody,
                        ident: identity.Identity = Depends(identity.current)) -> dict:
    """verified·dismissed 는 라벨 대상(§7.6), mitigated 는 사람 표기만(§4.7.1).

    `label_needed` 면 같은 트랜잭션에서 `metrics.record_label(source='expert_review')` 를 클러스터의
    finding 마다 잇는다 — 그 함수가 `rr_labels`·`rr_registry_status_log`·`rr_delta_priors`·패턴 카운트·
    AIDataHub 재부착 op 를 한 번에 처리한다. 근거 없는 확정은 record_label 이 422 로 막고 그때는
    등록부 갱신도 함께 되돌아간다(사람 확정만 남고 라벨이 없는 상태를 만들지 않는다).
    """
    owner_sub = _require_user(ident)
    store = get_store()
    with store.tx():
        out = registry_module.set_status(store, cluster_key, body.status, owner_sub=owner_sub,
                                         target_key=body.target_key, evidence_ref=body.evidence_ref,
                                         note=body.note, actor=owner_sub)
        if out.get("label_needed"):
            outcome = REGISTRY_LABEL_OUTCOME[out["status"]]
            out["labels"] = [
                metrics.record_label(
                    store, finding_id=finding_id, source="expert_review", outcome=outcome,
                    evidence_ref=body.evidence_ref or "", owner_sub=owner_sub,
                    labeled_by=owner_sub, evidence_note=body.note)
                for finding_id in _cluster_finding_ids(store, cluster_key, owner_sub, body.target_key)]
    return out


class RegistryMergeBody(BaseModel):
    into: str                      # 살아남을 대표 cluster_key
    reason: str = "cluster_merge"
    target_key: str | None = None


@router.put("/registry/{cluster_key:path}/merge")
def put_registry_merge(cluster_key: str, body: RegistryMergeBody,
                       ident: identity.Identity = Depends(identity.current)) -> dict:
    """두 클러스터를 사람 확정으로 잇는다 — 별칭 1행 + 그 타깃 재병합(plan §4.3.2·§0.9 P3-22).

    finding 행의 `cluster_key` 는 바이트 불변이고 병합은 조회 시 별칭 해석으로 이뤄진다. family_key 가
    다르면 422 — 메커니즘이 다른 두 클러스터를 한 행으로 접지 않는다.
    """
    owner_sub = _require_user(ident)
    store = get_store()
    left = store.query_one(
        "SELECT target_key, family_key FROM rr_registry WHERE cluster_key = ? AND owner_sub = ? LIMIT 1",
        (cluster_key, owner_sub))
    right = store.query_one(
        "SELECT target_key, family_key FROM rr_registry WHERE cluster_key = ? AND owner_sub = ? LIMIT 1",
        (body.into, owner_sub))
    if left is None or right is None:
        raise AppError("E404", "두 등록부 클러스터가 모두 있어야 합니다.", 404)
    if left["family_key"] and right["family_key"] and left["family_key"] != right["family_key"]:
        raise AppError("family_key_differs", "family_key 가 다른 클러스터는 병합할 수 없습니다.", 422)

    with store.tx():
        alias = registry_module.add_cluster_alias(
            store, cluster_key, body.into, owner_sub=owner_sub, reason=body.reason,
            evidence={"from": cluster_key, "to": body.into, "by": owner_sub})
        _audit(store, owner_sub, scope="registry", subject_id=f"{left['target_key']}#{cluster_key}",
               action="registry.merge", before={"cluster_key": cluster_key},
               after={"cluster_key": body.into})
    merged = registry_module.merge(store, body.target_key or left["target_key"], owner_sub=owner_sub)
    return {"alias": alias, "merged": {k: merged[k] for k in ("clusters", "inserted", "updated", "unchanged")}}


@router.delete("/registry/{cluster_key:path}/merge")
def delete_registry_merge(cluster_key: str, target_key: str | None = None,
                          ident: identity.Identity = Depends(identity.current)) -> dict:
    """별칭 철회 — 행은 남고 revoked_at 만 찍히며 재병합에서 다시 갈린다."""
    owner_sub = _require_user(ident)
    store = get_store()
    row = store.query_one(
        "SELECT target_key FROM rr_registry WHERE cluster_key = ? AND owner_sub = ? LIMIT 1",
        (cluster_key, owner_sub))
    with store.tx():
        out = registry_module.revoke_cluster_alias(store, cluster_key, owner_sub=owner_sub)
        _audit(store, owner_sub, scope="registry", subject_id=cluster_key,
               action="registry.merge.revoke", before={"cluster_key": cluster_key}, after=out)
    if row is not None:
        registry_module.merge(store, target_key or row["target_key"], owner_sub=owner_sub)
    return out


class RegistryVisibilityBody(BaseModel):
    visibility: str
    target_key: str | None = None


@router.put("/registry/{cluster_key:path}/visibility")
def put_registry_visibility(cluster_key: str, body: RegistryVisibilityBody,
                            ident: identity.Identity = Depends(identity.current)) -> dict:
    """등록부 행의 조직 공개 토글(소유자 전용) — rr_audit 1행을 남긴다(plan §0.9 P6-8)."""
    owner_sub = _require_user(ident)
    store = get_store()
    with store.tx():
        out = registry_module.set_visibility(store, cluster_key, body.visibility,
                                             owner_sub=owner_sub, target_key=body.target_key)
        _audit(store, owner_sub, scope="registry", subject_id=cluster_key,
               action="registry.visibility", before={"visibility": out["before"]},
               after={"visibility": out["visibility"]})
    return out


@router.get("/panels/{panel_id}/brief")
def get_panel_brief(panel_id: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """그 패널이 실제로 받은 브리프 — 재조립이 아니라 동결본을 돌려준다(plan §5.6.1·§0.9 P3-19)."""
    owner_sub = _require_user(ident)
    _panel_row(panel_id, owner_sub)
    return runner.load_brief(get_store(), panel_id)


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


BRIEF_TOKEN_BYTES = 24


def brief_token_hash(token: str) -> str:
    """brief_token 저장형 — sha256[:32]. 원문은 어디에도 저장하지 않는다(plan §8.2.5)."""
    return sha256_hex(token.strip())[:32]


def issue_brief_token(store: Any, panel_id: str) -> str:
    """패널 1건에 붙는 brief_token 을 발급한다 — rr_panels 에는 해시와 만료(now + risk_brief_token_ttl_s)만 남는다."""
    token = secrets.token_urlsafe(BRIEF_TOKEN_BYTES)
    store.execute(
        "UPDATE rr_panels SET brief_token_hash = ?, brief_token_exp = ? WHERE id = ?",
        (brief_token_hash(token), now_epoch() + int(config.settings.risk_brief_token_ttl_s), panel_id))
    return token


def resolve_brief_token(target_key: str, brief_token: str | None) -> dict:
    """brief_token 을 그 타깃의 패널 행과 대조한다 — 없음·불일치·만료는 `brief_token_invalid`(401 등가, §8.2.5)."""
    token = (brief_token or "").strip()
    row = None
    if token:
        row = get_store().query_one(
            "SELECT id, target_key, owner_sub, brief_token_exp FROM rr_panels"
            " WHERE target_key = ? AND brief_token_hash = ?", (target_key, brief_token_hash(token)))
    if row is None or int(row["brief_token_exp"] or 0) < now_epoch():
        raise AppError("brief_token_invalid", "브리프 토큰이 없거나 만료됐습니다 — 앱 화면에서 다시 받으세요.", 401)
    return dict(row)


def brief_by_token(target_key: str, brief_token: str | None, tier: str = "B") -> dict:
    """MCP `risk_get_brief` 본체 — caller 판정 대신 brief_token 대조로 연다(plan §8.2.5).

    토큰은 UI·REST `GET /targets/{key}/brief` 가 그 패널 1건·`risk_brief_token_ttl_s` 동안만 위임한 열쇠다.
    """
    panel = resolve_brief_token(target_key, brief_token)
    return brief_payload(target_key, tier, owner_sub=panel["owner_sub"])


def brief_payload(target_key: str, tier: str = "B", *, owner_sub: str | None = None,
                  actor: str | None = None, exclude: tuple[str, ...] = (),
                  issue_token: bool = False) -> dict:
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
    # REST·MCP 미리보기도 같은 브리프를 만든다 — E10 을 러너에만 두면 이 경로의 그 블록이 영영 빈다.
    # 24 h 캐시가 있어 미리보기가 게이트웨이를 매번 왕복하지는 않는다(§5.6.2).
    # 자격은 (b) 타깃 owner → (a) 서비스 순이다 — 서비스 시야로만 부르면 빈 응답이 'VOC 0건' 으로 굳는다.
    field = field_source.for_target(store, target_key)
    try:
        brief = brief_module.build_brief(store, target_key, seats=seats, panel_id=panel_id,
                                        exclude=exclude, owner_sub=target["owner_sub"], field=field)
    finally:
        # 채널은 자기 httpx.Client 를 소유한다 — 미리보기 요청마다 소켓이 새지 않게 닫는다.
        if field is not None:
            field.close()
    # E0c(좌석 계약)는 build_delib_opts 가 다시 끼우므로 엔진 몫 evidence 에서는 뺀다.
    engine_evidence = [item for item, key in zip(brief["evidence"], brief["keys"]) if key != "E0c"]

    out_panels = []
    for panel in panels:
        loss: dict = {}
        item = {
            "panel_id": panel["id"],
            "panel_no": panel["panel_no"],
            "seats_json": panel["seats_json"],
            "delib_opts": runner.build_delib_opts(store, config.settings, panel, evidence=engine_evidence,
                                                  loss=loss),
        }
        # 칸을 넘겨 빠진 항목·다 못 실은 메모는 그 패널 옆에 적는다 — 호출자가 받은 근거를 전부라고 읽지 않게.
        item.update(loss)
        if issue_token:
            # L2 오케스트레이터가 게이트웨이 MCP 로 같은 브리프를 다시 받을 유일한 열쇠다(§8.2.5).
            item["brief_token"] = issue_brief_token(store, panel["id"])
        out_panels.append(item)
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
    """패널 브리프 + 패널마다 1건의 `brief_token`(MCP `risk_get_brief` 의 열쇠, §8.2.5)."""
    owner_sub = _require_user(ident)
    return brief_payload(target_key, tier, owner_sub=owner_sub, issue_token=True)


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
    # 엔진이 좌석에 주지 않았다고 알린 근거 — 러너 경로와 같은 표기로 남긴다. events[] 없는 재제출은 지우지 않는다.
    withheld = runner.withheld_by_engine(checked)
    if withheld:
        quality["engine_withheld"] = withheld
        if "engine_withheld" not in flags:
            flags.append("engine_withheld")
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

        # 미검증 actor(MCP 경로)가 낸 원자는 회수에서 격리한다 — 이 타깃 등록부·보고서에는 그대로 남고
        # 다른 과제 브리프의 E5·E6·E7 후보에서만 빠진다(plan §3.4.1 회수 격리·§6.11).
        if not actor_verified and config.settings.risk_recall_require_verified_actor:
            store.execute("UPDATE rr_findings SET recall_eligible = 0 WHERE panel_id = ?", (panel_id,))
            store.execute("UPDATE rr_character SET recall_eligible = 0 WHERE id LIKE ?", (f"{panel_id}#%",))

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
    """스냅샷 스코프 없이 전역으로 주소가 잡히는 참조(reg·narr·tool·rpt·inc·card·req·voc·paper)를 원장에서 찾는다."""
    store = get_store()
    kind = info["kind"]
    if kind == "req":
        # 과제 스코프는 참조 문자열에 없다 — 호출자 소유 요구에서 찾는다. 범위·정렬은 인용 해석과 같다
        # (waived 제외·kind 순서, §2.8b) — 갈리면 인용은 해석되는데 REST 가 404 가 된다.
        row = store.query_one(
            "SELECT id, project_id, name, kind, op, value_json, unit, status, source_ref FROM rr_requirements"
            " WHERE name = ? AND owner_sub = ? AND status IN ('candidate','confirmed')"
            " ORDER BY kind LIMIT 1", (info["name"], owner_sub))
        return dict(row) if row is not None else None
    if kind in ("voc", "paper"):
        return narrative.find_field_item(
            store, kind, info["issue_key"] if kind == "voc" else info["paper_id"],
            product_code=info.get("product_code"), owner_sub=owner_sub)
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
    if kind == "tool" and "conv_id" in info:
        # 레거시 참조 — 포털 대화가 지워져도 rr_panel_calls(conv_id, activity_idx)로 해석한다(§6.7.2 7단계).
        row = store.query_one(
            "SELECT call_id, panel_id, target_key, seq, agent_key, tool, result_gz, result_bytes, sha256,"
            " conv_id, activity_idx FROM rr_panel_calls WHERE conv_id = ? AND activity_idx = ?"
            " AND owner_sub = ?", (info["conv_id"], int(info["idx"]), owner_sub))
        return _panel_call_payload(row) if row is not None else None
    if kind == "tool" and str(info.get("call_id") or "").startswith("panel:"):
        row = store.query_one(
            "SELECT call_id, panel_id, target_key, seq, agent_key, tool, result_gz, result_bytes, sha256,"
            " conv_id, activity_idx FROM rr_panel_calls WHERE call_id = ? AND owner_sub = ?",
            (str(info["call_id"])[len("panel:"):], owner_sub))
        return _panel_call_payload(row) if row is not None else None
    if kind == "tool" and "call_id" in info:
        row = store.query_one(
            "SELECT call_id, snapshot_id, seq, source_kind, app_key, channel, tool, args_json, ok, http_status,"
            " response_sha256, response_gz, response_bytes, started_at, duration_ms, error FROM rr_snapshot_calls"
            " WHERE call_id = ? AND owner_sub = ?", (info["call_id"], owner_sub))
        return _tool_call_payload(row) if row is not None else None
    return None


# `GET /api/refs/tool:<call_id>` 가 돌려주는 원문 발췌 상한(자). 넘으면 앞부분만 싣고 잘림을 표기한다.
REF_RESPONSE_MAX = 200_000


def _panel_call_payload(row: Any) -> dict:
    """rr_panel_calls 한 행 — 좌석 도구 호출 원문(§6.7.2 7단계). 원문이 없으면 quote_unverifiable 이다."""
    item = {key: row[key] for key in row.keys() if key != "result_gz"}
    blob = row["result_gz"]
    item["result_available"] = blob is not None
    if blob is None:
        item["quote_unverifiable"] = True
        return item
    text = gzip.decompress(blob).decode("utf-8")
    item["result_text"] = text[:REF_RESPONSE_MAX]
    item["result_truncated"] = len(text) > REF_RESPONSE_MAX
    return item


def _tool_call_payload(row: Any) -> dict:
    """rr_snapshot_calls 한 행을 참조 payload 로 편다 — 보관한 gzip 원문을 풀어 함께 싣는다(plan §2.11.2).

    원문이 없으면(보존기간이 지나 `response_gz=NULL`) 해시·메타만 남고 `response_available=false` 다.
    """
    item = {key: row[key] for key in row.keys() if key != "response_gz"}
    blob = row["response_gz"]
    item["response_available"] = blob is not None
    item["response_truncated"] = False
    if blob is None:
        return item
    text = gzip.decompress(blob).decode("utf-8")
    if len(text) > REF_RESPONSE_MAX:
        item["response_text"] = text[:REF_RESPONSE_MAX]
        item["response_truncated"] = True
        return item
    item["response_text"] = text
    try:
        item["response"] = json.loads(text)
    except json.JSONDecodeError:
        pass
    return item


def claims_for_ref(ref: str, *, owner_sub: str | None = None, limit: int = 100,
                   projects: list[str] | None = None) -> dict:
    """참조 1건에 앵커된 주장 목록 — MCP `risk_claims_for_ref` 와 같은 함수(rr_claim_refs 역색인, §4.4.4).

    `projects` 를 주면 그 과제에 속한 타깃의 주장만 돌려준다 — MCP 읽기의 범위 판정이 쓰는 갈래로,
    빈 목록은 '보이는 과제 0건' 이라 결과도 0건이다(§8.2.5 ②).
    """
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
    if projects is not None:
        holes = ", ".join("?" for _ in projects) or "NULL"
        sql += f" AND r.target_key IN (SELECT target_key FROM rr_targets WHERE project_id IN ({holes}))"
        params.extend(projects)
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


# ---------------------------------------------------------------- 사전 편집과 재계산(plan §2.7.1·§0.9 P2-12)
# 사전은 성장 사전이라 편집이 곧 키 변경이다 — 추가는 마이너, 변경·삭제·stop_token 추가는 메이저다.
VOCAB_ROW_NAME = "_vocab"          # 사전 전역 행(치수 이름이 아니라 사전 자체의 자리)
VOCAB_OPS = ("add", "remove")


def _vocab_row(store: Any) -> dict:
    row = store.query_one(
        "SELECT name, synonyms_json, stop_tokens_json, vocab_version FROM rr_dim_vocab WHERE name = ?",
        (VOCAB_ROW_NAME,))
    if row is None:
        return {"synonyms": {}, "stop_tokens": [], "vocab_version": "1.0"}
    return {"synonyms": _loads(row["synonyms_json"], {}),
            "stop_tokens": _loads(row["stop_tokens_json"], []),
            "vocab_version": row["vocab_version"] or "1.0"}


def bump_vocab_version(current: str, level: str) -> str:
    """마이너 `1.<m>` · 메이저 `<M>.0`(plan §0.6 키 계보)."""
    try:
        major, minor = (int(x) for x in str(current or "1.0").split(".", 1))
    except ValueError:
        major, minor = 1, 0
    return f"{major + 1}.0" if level == "major" else f"{major}.{minor + 1}"


def vocab_recompute_pending(store: Any) -> bool:
    """메이저 승급 뒤 `recompute_part_keys.py` 가 아직 안 돈 상태(plan §2.7.1)."""
    row = store.query_one(
        "SELECT description, vocab_version FROM rr_dim_vocab WHERE name = ?", (VOCAB_ROW_NAME,))
    if row is None:
        return False
    return _loads(row["description"], {}).get("recomputed_at") is None and \
        str(row["vocab_version"] or "1.0").endswith(".0") and str(row["vocab_version"]) != "1.0"


def _save_vocab(store: Any, *, synonyms: dict, stop_tokens: list, version: str,
                owner_sub: str, recomputed_at: int | None) -> None:
    now = now_epoch()
    store.execute(
        "INSERT INTO rr_dim_vocab(name, kind, unit, description, synonyms_json, stop_tokens_json,"
        " vocab_version, created_by, created_at) VALUES (?, 'other', NULL, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(name) DO UPDATE SET description = excluded.description,"
        " synonyms_json = excluded.synonyms_json, stop_tokens_json = excluded.stop_tokens_json,"
        " vocab_version = excluded.vocab_version",
        (VOCAB_ROW_NAME, canonical_json({"recomputed_at": recomputed_at}),
         canonical_json(synonyms), canonical_json(sorted(stop_tokens)), version, owner_sub, now),
    )


class VocabSynonymBody(BaseModel):
    head: str
    from_: list[str] = Field(default_factory=list, alias="from")
    op: str = "add"

    model_config = {"populate_by_name": True}


class VocabStopTokenBody(BaseModel):
    tokens: list[str] = Field(default_factory=list)
    op: str = "add"


def _require_vocab_admin(ident: identity.Identity) -> str:
    email = _require_user(ident)
    if not _is_admin(ident):
        raise AppError("role_insufficient", "사전 편집은 risk_admin_roles 만 할 수 있습니다.", 403)
    return email


def _apply_vocab_edit(store: Any, *, level: str, mutate, owner_sub: str) -> dict:
    """사전 편집 1건 — 같은 트랜잭션에서 값과 vocab_version 을 함께 올린다.

    메이저는 재계산(`recompute_part_keys.py`)이 필수라, 재계산 전에 두 번째 메이저가 오면 409 다.
    """
    current = _vocab_row(store)
    if level == "major" and vocab_recompute_pending(store):
        raise AppError("vocab_recompute_required",
                       "직전 메이저 승급의 재계산(recompute_part_keys.py)이 아직 안 돌았습니다.", 409)
    synonyms = dict(current["synonyms"])
    stop_tokens = list(current["stop_tokens"])
    mutate(synonyms, stop_tokens)
    version = bump_vocab_version(current["vocab_version"], level)
    with store.tx():
        _save_vocab(store, synonyms=synonyms, stop_tokens=stop_tokens, version=version,
                    owner_sub=owner_sub, recomputed_at=None if level == "major" else 1)
        _audit(store, owner_sub, scope="project", subject_id=VOCAB_ROW_NAME,
               action="vocab.edit", before={"vocab_version": current["vocab_version"]},
               after={"vocab_version": version, "bump": level})
    return {"vocab_version": version, "bump": level, "synonyms": synonyms,
            "stop_tokens": sorted(stop_tokens),
            "recompute_required": level == "major"}


@router.post("/vocab/synonyms")
def post_vocab_synonyms(body: VocabSynonymBody,
                        ident: identity.Identity = Depends(identity.current)) -> dict:
    """동의어 추가는 마이너, 삭제는 메이저다(plan §2.7.1 '사전 편집과 재계산')."""
    owner_sub = _require_vocab_admin(ident)
    if body.op not in VOCAB_OPS:
        raise AppError("E100", f"op 는 {list(VOCAB_OPS)} 중 하나여야 합니다.", 422)
    head = (body.head or "").strip().lower()
    aliases = [str(x).strip().lower() for x in body.from_ if str(x).strip()]
    if not head or not aliases:
        raise AppError("E100", "head 와 from[] 이 필요합니다.", 422)

    def mutate(synonyms: dict, _stop_tokens: list) -> None:
        for alias in aliases:
            if body.op == "add":
                synonyms[alias] = head
            else:
                synonyms.pop(alias, None)

    return _apply_vocab_edit(get_store(), level="minor" if body.op == "add" else "major",
                             mutate=mutate, owner_sub=owner_sub)


@router.post("/vocab/stop-tokens")
def post_vocab_stop_tokens(body: VocabStopTokenBody,
                           ident: identity.Identity = Depends(identity.current)) -> dict:
    """stop_token 추가·삭제는 둘 다 키를 바꾼다 — 메이저 승급이다(plan §2.7.1)."""
    owner_sub = _require_vocab_admin(ident)
    if body.op not in VOCAB_OPS:
        raise AppError("E100", f"op 는 {list(VOCAB_OPS)} 중 하나여야 합니다.", 422)
    tokens = [str(x).strip().lower() for x in body.tokens if str(x).strip()]
    if not tokens:
        raise AppError("E100", "tokens[] 가 필요합니다.", 422)

    def mutate(_synonyms: dict, stop_tokens: list) -> None:
        for token in tokens:
            if body.op == "add" and token not in stop_tokens:
                stop_tokens.append(token)
            elif body.op == "remove" and token in stop_tokens:
                stop_tokens.remove(token)

    return _apply_vocab_edit(get_store(), level="major", mutate=mutate, owner_sub=owner_sub)


# ================================================================ 이동(export·import)
@router.get("/export")
def get_export(since: int = 0, include_excluded: int = 0,
               ident: identity.Identity = Depends(identity.current)) -> StreamingResponse:
    """JSONL 내보내기(소유자 행만) — 첫 줄 헤더 `{schema_version, app_version, origin}`, 이어서 §5.2.2 A→H 표 순서로 `{table, row}`.

    반출 자격은 `risk_export_allowed_groups` 로 막고(403 `export_not_allowed`), 실린 과제의 최고 등급을
    `X-Risk-Classification-Max` 헤더로 알린다. `status='purged'`·`corpus_excluded=1` 과제는 기본 제외이고
    `?include_excluded=1` 로만 싣는다(plan §0.6 '데이터 등급·반출'·§5.2.6 (ii)).
    """
    owner_sub = _require_user(ident)
    allowed = [g for g in (config.settings.risk_export_allowed_groups or []) if g]
    if allowed and not (set(allowed) & set(_caller_groups(ident))):
        raise AppError("export_not_allowed", "이 계정 그룹은 반출 자격이 없습니다.", 403)
    with_excluded = bool(int(include_excluded or 0))
    store = get_store()
    path = export_module.write_export_file(store, owner_sub, int(since), include_excluded=with_excluded)

    def _stream():
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                yield line

    return StreamingResponse(_stream(), media_type="application/x-ndjson", headers={
        "Content-Disposition": f'attachment; filename="{path.name}"',
        # 서버 절대 경로는 흘리지 않는다 — 파일명만 남긴다.
        "X-Export-File": path.name,
        "X-Risk-Classification-Max": export_module.classification_max(store, owner_sub, with_excluded)})


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


# ================================================================ P6 — 라벨·큐레이션 결정·승격 상태(plan §7.5·§7.6·§7.7)
class LabelBody(BaseModel):
    outcome: str
    evidence_ref: str
    source: str = "expert_review"
    severity_observed: str | None = None
    occurred_at: int | None = None
    evidence_note: str | None = None
    pattern_id: str | None = None


# ---------------------------------------------------------------- 사람 finding 1급 레코드(plan §4.3.1·§0.9 P3-17)
class HumanFindingBody(BaseModel):
    direction: str = "risk"
    domain: str | None = None
    mechanism: str = "unclassified"
    mechanism_detail: str | None = None
    change_kind: str | None = None
    subject_key: str | None = None
    subject_names: list[str] = Field(default_factory=list)
    severity: str | None = None
    judgement: str | None = None
    trigger_condition: str | None = None
    claim: str = Field(max_length=2000)
    warrant: str | None = None
    cites: list[dict] = Field(default_factory=list)
    requirement_ref: str | None = None


HUMAN_DIRECTIONS = ("risk", "improvement", "neutral")
HUMAN_SEVERITIES = ("경미", "중대", "치명")
HUMAN_JUDGEMENTS = ("OK", "WARNING", "FAIL", "undetermined")
_SEV3_OF = {"경미": 1, "중대": 2, "치명": 3}


def _next_human_claim_uid(store: Any, target_key: str) -> str:
    """`<target_key>#H<n>` — 그 타깃의 사람 finding 순번(plan §0.2.2)."""
    rows = store.query(
        "SELECT claim_uid FROM rr_findings WHERE target_key = ? AND origin = 'human'", (target_key,))
    used = []
    for row in rows:
        tail = str(row["claim_uid"]).rsplit("#H", 1)
        if len(tail) == 2 and tail[1].isdigit():
            used.append(int(tail[1]))
    return f"{target_key}#H{(max(used) + 1) if used else 1}"


def _human_finding_row(store: Any, finding_id: str, owner_sub: str) -> dict:
    row = store.query_one(
        "SELECT finding_id, claim_uid, target_key, project_id, owner_sub, origin, author_sub, direction,"
        " cluster_key, finding_json, status FROM rr_findings WHERE finding_id = ?", (finding_id,))
    if row is None or row["owner_sub"] != owner_sub:
        raise AppError("E404", f"finding 을 찾을 수 없습니다 — {finding_id}.", 404)
    if row["origin"] != "human":
        raise AppError("llm_finding_immutable", "패널이 낸 원자는 REST 로 고치지 않습니다(재제출만).", 422)
    return dict(row)


@router.post("/targets/{target_key}/findings")
def create_human_finding(target_key: str, body: HumanFindingBody,
                         ident: identity.Identity = Depends(identity.current)) -> dict:
    """사람이 직접 제기하는 finding 1건 — 패널 산출과 같은 표에 `origin='human'` 으로 앉는다(plan §4.3.1).

    인용이 0건이면 422 다. 등급·판정은 사람이 고르고 `panel_id` 는 NULL 이며 병합에서 전문가 지지로 세지
    않는다(`human_n` 으로 따로 센다, §4.7.1).
    """
    email = _require_user(ident)
    store = get_store()
    row = store.query_one(
        "SELECT owner_sub, project_id, kind, ref_id FROM rr_targets WHERE target_key = ?", (target_key,))
    if row is None:
        raise AppError("E404", f"타깃({target_key}) 을 찾을 수 없습니다.", 404)
    if not _is_admin(ident):
        require_role(row["project_id"], email, "editor")
    if body.direction not in HUMAN_DIRECTIONS:
        raise AppError("E100", f"direction 은 {list(HUMAN_DIRECTIONS)} 중 하나여야 합니다.", 422)
    if body.severity is not None and body.severity not in HUMAN_SEVERITIES:
        raise AppError("E100", f"severity 는 {list(HUMAN_SEVERITIES)} 중 하나여야 합니다.", 422)
    if body.judgement is not None and body.judgement not in HUMAN_JUDGEMENTS:
        raise AppError("E100", f"judgement 는 {list(HUMAN_JUDGEMENTS)} 중 하나여야 합니다.", 422)
    cites = [c for c in body.cites if isinstance(c, dict) and str(c.get("ref") or "").strip()]
    if not cites:
        raise AppError("cites_required", "사람 finding 도 인용이 최소 1건 필요합니다(§4.3.1).", 422)
    if not (body.claim or "").strip():
        raise AppError("E100", "claim 이 비었습니다.", 422)

    now = now_epoch()
    claim_uid = _next_human_claim_uid(store, target_key)
    finding_id = claim_uid
    severity = body.severity or "경미"
    subject_key = (body.subject_key or "").strip()
    cluster_key = narrative.cluster_key_of(body.mechanism, body.mechanism_detail or "", subject_key,
                                           body.change_kind or "")
    finding_json = {
        "id": claim_uid, "origin": "human", "author_sub": email,
        "direction": body.direction, "domain": body.domain, "mechanism": body.mechanism,
        "mechanism_detail": body.mechanism_detail, "change_kind": body.change_kind,
        "subject": {"ckeys": [], "names": list(body.subject_names)},
        "subject_key": subject_key, "severity": severity, "judgement": body.judgement or "undetermined",
        "trigger_condition": body.trigger_condition, "claim": body.claim, "warrant": body.warrant or "",
        "cites": cites, "requirement_ref": body.requirement_ref, "status": "open",
    }
    with store.tx():
        store.execute(
            "INSERT INTO rr_findings(finding_id, claim_uid, origin, author_sub, target_key, panel_id,"
            " opinion_id, project_id, owner_sub, visibility, direction, domain, mechanism, mechanism_detail,"
            " change_kind, subject_key, ckeys_json, trigger_condition, severity, sev3, judgement,"
            " evidence_grade, precedent, requirement_ref, dangling, cluster_key, finding_json,"
            " recall_eligible, status, status_source, created_at, updated_at)"
            " VALUES (?,?, 'human', ?, ?, NULL, NULL, ?, ?, 'private', ?,?,?,?,?,?, '[]', ?,?,?,?, '경험칙',"
            " 'none', ?, 0, ?, ?, 1, 'open', 'code', ?, ?)",
            (finding_id, claim_uid, email, target_key, row["project_id"], row["owner_sub"],
             body.direction, body.domain, body.mechanism, body.mechanism_detail, body.change_kind,
             subject_key, body.trigger_condition, severity, _SEV3_OF.get(severity, 1),
             body.judgement or "undetermined", body.requirement_ref, cluster_key,
             canonical_json(finding_json), now, now),
        )
        for cite in cites:
            ref = str(cite.get("ref"))
            info = parse_ref(ref)
            store.execute(
                "INSERT OR REPLACE INTO rr_claim_refs(claim_uid, ref_type, ref, quote, owner_sub, target_key,"
                " dangling) VALUES (?,?,?,?,?,?,?)",
                (claim_uid, (info or {}).get("kind") or "unknown", ref, str(cite.get("quote") or ""),
                 row["owner_sub"], target_key, 0 if info else 1),
            )
        _audit(store, email, scope="finding", subject_id=finding_id, project_id=row["project_id"],
               action="finding.create", after={"origin": "human", "claim_uid": claim_uid})
    registry_module.merge(get_store(), target_key)
    return {"finding_id": finding_id, "claim_uid": claim_uid, "cluster_key": cluster_key, "origin": "human"}


@router.put("/findings/{finding_id}")
def update_human_finding(finding_id: str, body: HumanFindingBody,
                         ident: identity.Identity = Depends(identity.current)) -> dict:
    """작성자만 고칠 수 있다 — 패널이 낸 llm 행은 422 다."""
    email = _require_user(ident)
    store = get_store()
    row = _human_finding_row(store, finding_id, _require_user(ident))
    if row["author_sub"] != email and not _is_admin(ident):
        raise AppError("role_insufficient", "작성자만 고칠 수 있습니다.", 403)
    cites = [c for c in body.cites if isinstance(c, dict) and str(c.get("ref") or "").strip()]
    if not cites:
        raise AppError("cites_required", "사람 finding 도 인용이 최소 1건 필요합니다(§4.3.1).", 422)
    finding_json = _loads(row["finding_json"], {})
    finding_json.update({"claim": body.claim, "warrant": body.warrant or "", "cites": cites,
                         "severity": body.severity or finding_json.get("severity") or "경미",
                         "judgement": body.judgement or finding_json.get("judgement") or "undetermined"})
    now = now_epoch()
    with store.tx():
        store.execute(
            "UPDATE rr_findings SET severity = ?, sev3 = ?, judgement = ?, finding_json = ?, updated_at = ?"
            " WHERE finding_id = ?",
            (finding_json["severity"], _SEV3_OF.get(finding_json["severity"], 1), finding_json["judgement"],
             canonical_json(finding_json), now, finding_id))
        _audit(store, email, scope="finding", subject_id=finding_id, project_id=row["project_id"],
               action="finding.update", before={"claim": _loads(row["finding_json"], {}).get("claim")},
               after={"claim": body.claim})
    registry_module.merge(store, row["target_key"])
    return {"finding_id": finding_id, "updated": True}


@router.delete("/findings/{finding_id}")
def delete_human_finding(finding_id: str, ident: identity.Identity = Depends(identity.current)) -> dict:
    """작성자 삭제 — 인용 역색인도 함께 지운다. 패널이 낸 행은 422 다."""
    email = _require_user(ident)
    store = get_store()
    row = _human_finding_row(store, finding_id, email)
    if row["author_sub"] != email and not _is_admin(ident):
        raise AppError("role_insufficient", "작성자만 지울 수 있습니다.", 403)
    with store.tx():
        store.execute("DELETE FROM rr_claim_refs WHERE claim_uid = ?", (row["claim_uid"],))
        store.execute("DELETE FROM rr_findings WHERE finding_id = ?", (finding_id,))
        _audit(store, email, scope="finding", subject_id=finding_id, project_id=row["project_id"],
               action="finding.delete", before={"claim_uid": row["claim_uid"]})
    registry_module.merge(store, row["target_key"])
    return {"finding_id": finding_id, "deleted": True}


@router.post("/findings/{finding_id}/labels")
def post_finding_label(finding_id: str, body: LabelBody,
                       ident: identity.Identity = Depends(identity.current)) -> dict:
    """§7.6 라벨 경로 5(사람) — finding·등록부 화면이 직접 붙이는 `confirmed|refuted|inconclusive`.

    자동 4경로(incident·test_run·sim·voc)는 야간 잡의 입구라 REST 로는 받지 않는다 — 사람 손으로
    `matched_by='auto'` 라벨을 세우면 3항 매칭 없이 자동 확정 통계가 부풀기 때문이다.
    어휘 422·남의 finding 404 와 훅(상태 전이·선례·패턴 카운트)은 `metrics.record_label` 이 낸다.
    """
    owner_sub = _require_user(ident)
    if body.source not in metrics.MANUAL_SOURCES:
        raise AppError("E100", f"사람 라벨의 source 는 {sorted(metrics.MANUAL_SOURCES)} 뿐입니다 — {body.source!r}.", 422)
    return metrics.record_label(
        get_store(), finding_id=finding_id, source=body.source, outcome=body.outcome,
        evidence_ref=body.evidence_ref, owner_sub=owner_sub, severity_observed=body.severity_observed,
        occurred_at=body.occurred_at, evidence_note=body.evidence_note, labeled_by=owner_sub,
        pattern_id=body.pattern_id)


# 큐 kind 별 결정 어휘(§7.7 표). 여기 없는 kind 는 적용 함수가 아직 없어 501 이다(라우트가 로직을 지어내지 않는다).
CURATION_DECISIONS: dict[str, tuple[str, ...]] = {
    "label_match": ("confirmed", "refuted", "inconclusive", "reject"),
    "pattern_candidate": ("known", "rule", "predictor", "suspended", "deprecated", "reject"),
    # 의심 문구는 사람이 원문을 보고 승인(원문 복원 + 회수 복귀)하거나 기각(격리 유지)한다(§3.4.1).
    "suspect_text": ("approve", "reject"),
    # 근접 중복 클러스터 — merge 는 별칭 1행 + 재병합, reject 는 그대로 두 행이다
    # (payload {"suppress": true} 로 기각하면 다음 스캔이 그 쌍을 다시 올리지 않는다, §7.7 표).
    "cluster_merge": ("merge", "reject"),
    # 미분류 코드 — map 은 기존 detail 로, new 는 사람이 준 새 detail 로 옮긴다(둘 다 별칭 경로).
    "unclassified_code": ("map", "new", "reject"),
    # 자유 태그 승격 — promote 는 payload.axis 로 `char:<axis>:<value>` 를 만들고, reject 는 그 태그를 다시 올리지 않는다.
    "x_tag_promote": ("promote", "reject"),
}
# 감사 로그의 scope 는 rr_audit CHECK 어휘 안에서 고른다(§5.2.2 — 'curation' 은 그 어휘에 없다).
CURATION_AUDIT_SCOPE: dict[str, str] = {"label_match": "finding", "pattern_candidate": "registry",
                                        "suspect_text": "finding", "cluster_merge": "registry",
                                        "unclassified_code": "finding",
                                        # 승격은 한 과제가 아니라 소유자 코퍼스의 진술을 건드린다 — 가장 가까운 어휘가 'project' 다.
                                        "x_tag_promote": "project"}
CURATION_LIMIT_MAX = 200


def _bump_minor(version: str) -> str:
    """`1.0` → `1.1` — 택소노미 마이너 승급(이전 값은 결정 기록에 남는다, plan §7.7)."""
    try:
        major, minor = (int(x) for x in str(version or "1.0").split(".", 1))
    except ValueError:
        return "1.1"
    return f"{major}.{minor + 1}"


class CurationDecisionBody(BaseModel):
    decision: str
    reason: str | None = None
    payload: dict | None = None


@router.get("/curation")
def get_curation(kind: str | None = None, status: str | None = "open", limit: int = 200,
                 ident: identity.Identity = Depends(identity.current)) -> dict:
    """큐레이션 큐 조회(내 소유 행만) — `?kind=&status=open&limit≤200`."""
    owner_sub = _require_user(ident)
    sql = ("SELECT id, kind, payload_json, status, decision_json, decided_by, decided_at, created_at"
           " FROM rr_curation_queue WHERE owner_sub = ?")
    params: list[Any] = [owner_sub]
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    if status:
        sql += " AND status = ?"
        params.append(status)
    params.append(max(1, min(int(limit), CURATION_LIMIT_MAX)))
    rows = []
    for row in get_store().query(sql + " ORDER BY created_at, id LIMIT ?", params):
        item = dict(row)
        item["payload"] = _loads(item.pop("payload_json"), {})
        item["decision"] = _loads(item.pop("decision_json"), {})
        rows.append(item)
    return {"rows": rows}


@router.put("/curation/{queue_id}")
def put_curation(queue_id: str, body: CurationDecisionBody,
                 ident: identity.Identity = Depends(identity.current)) -> dict:
    """큐레이션 결정(§8.2.3) — `{status, decision_json, applied}` + `rr_audit(action='curation.decide')`.

    `pattern_candidate` 승인은 `learning.promote` 가 게이트를 다시 보고 미달이면 422 를 낸다 —
    같은 트랜잭션이라 그때 큐 상태도 열린 채로 남는다(승인 기록만 남고 승격이 없는 상태를 만들지 않는다).
    `label_match` 는 적용 함수가 따로 없다 — `metrics.is_counted_label` 이 이 큐의 status 로 계수 여부를
    정하므로 결정 자체가 적용이다(`done` 이면 그 라벨이 precision·선례 분모에 든다).
    """
    owner_sub = _require_user(ident)
    store = get_store()
    row = _owned_row("SELECT id, owner_sub, kind, payload_json, status FROM rr_curation_queue WHERE id = ?",
                     (queue_id,), owner_sub, "큐레이션 항목")
    kind = str(row["kind"])
    allowed = CURATION_DECISIONS.get(kind)
    if allowed is None:
        raise _not_implemented(f"큐레이션 kind '{kind}' 의 결정",
                               "적용 함수가 아직 없습니다(unclassified_code·x_tag_promote·suspect_text·cluster_merge 는 P1·P5 몫).")
    if body.decision not in allowed:
        raise AppError("decision_not_allowed_for_kind",
                       f"'{kind}' 큐의 결정 어휘가 아닙니다 — {body.decision!r}. 허용 {list(allowed)}.", 422)
    if row["status"] != "open":
        raise AppError("E409", f"이미 결정된 항목입니다 — status={row['status']}.", 409)

    payload = _loads(row["payload_json"], {})
    decision_json = {"decision": body.decision, "reason": body.reason, "payload": body.payload or {}}
    status = "rejected" if body.decision == "reject" else "done"
    applied: dict = {}
    with store.tx():
        if kind == "suspect_text" and body.decision == "approve":
            # 승인은 원문 복원이다 — 자리표시자가 가리키던 sha1 의 원문을 돌려주고 그 finding 을 회수로 되돌린다.
            claim_uid = str(payload.get("claim_uid") or "")
            restored = 0
            if claim_uid:
                restored = int(store.execute(
                    "UPDATE rr_findings SET recall_eligible = 1, updated_at = ?"
                    " WHERE claim_uid = ? AND owner_sub = ?", (now_epoch(), claim_uid, owner_sub)) or 0)
            applied = {"restored_text": payload.get("raw"), "sha1": payload.get("sha1"),
                       "findings_recalled": restored}
        if kind == "unclassified_code" and body.decision in ("map", "new"):
            # 미분류 코드를 택소노미 값으로 옮긴다 — finding 의 cluster_key 는 불변이고 별칭만 더한다(§4.3.2).
            detail = str((body.payload or {}).get("mechanism_detail") or "").strip()
            if not detail:
                raise AppError("E100", "payload.mechanism_detail 이 필요합니다.", 422)
            finding_id = str(payload.get("finding_id") or "")
            row = store.query_one(
                "SELECT mechanism, mechanism_detail FROM rr_findings WHERE finding_id = ? AND owner_sub = ?",
                (finding_id, owner_sub))
            if row is None:
                raise AppError("E404", f"finding 을 찾을 수 없습니다 — {finding_id}.", 404)
            before_version = taxonomy.version_of(taxonomy.load_json("taxonomy")) or "1.0"
            plan = learning.plan_remap(store, mechanism=str(row["mechanism"] or ""),
                                       from_detail=str(row["mechanism_detail"] or ""),
                                       to_detail=detail)
            out_remap = learning.apply_remap(store, plan, owner_sub=owner_sub)
            applied = {"mechanism_detail": detail, "decision": body.decision,
                       "taxonomy_version_before": before_version,
                       # 자산 파일은 앱이 고치지 않는다 — 승급 값은 결정 기록에 남고 자산 갱신은 사람 몫이다.
                       "taxonomy_version_after": _bump_minor(before_version), **out_remap}
        if kind == "cluster_merge" and body.decision == "merge":
            # 두 클러스터를 한 행으로 접는다 — family_key 가 다르면 422 이고 support 는 distinct 패널 수로 다시 센다.
            key_a, key_b = str(payload.get("a") or ""), str(payload.get("b") or "")
            rows = {key: store.query_one(
                "SELECT target_key, family_key FROM rr_registry WHERE cluster_key = ? AND owner_sub = ? LIMIT 1",
                (key, owner_sub)) for key in (key_a, key_b)}
            if not all(rows.values()):
                raise AppError("E404", "두 등록부 클러스터가 모두 있어야 합니다.", 404)
            if rows[key_a]["family_key"] and rows[key_b]["family_key"] \
                    and rows[key_a]["family_key"] != rows[key_b]["family_key"]:
                raise AppError("family_key_differs", "family_key 가 다른 클러스터는 병합할 수 없습니다.", 422)
            alias = registry_module.add_cluster_alias(store, key_a, key_b, owner_sub=owner_sub,
                                                      reason="cluster_merge",
                                                      evidence={"from": key_a, "to": key_b,
                                                                "score": payload.get("score")})
            merged = registry_module.merge(store, rows[key_a]["target_key"], owner_sub=owner_sub)
            applied = {"alias": alias, "clusters": merged["clusters"]}
        if kind == "x_tag_promote" and body.decision == "promote":
            # 어휘를 넓히는 결정이다 — 어느 축으로 올릴지는 코드가 고를 수 없어 사람이 payload.axis 로 준다.
            axis = str((body.payload or {}).get("axis") or "").strip()
            if not axis:
                raise AppError("E100", "payload.axis 가 필요합니다(예: 'char:structure').", 422)
            applied = character.promote_x_tag(store, tag=str(payload.get("tag") or ""),
                                              axis=axis, owner_sub=owner_sub)
        if kind == "pattern_candidate" and body.decision != "reject":
            pattern_id = str(payload.get("pattern_id") or "")
            if not pattern_id:
                raise AppError("E100", "pattern_candidate payload 에 pattern_id 가 없습니다.", 422)
            extra = body.payload or {}
            applied = learning.promote(store, pattern_id, to_status=body.decision, decided_by=owner_sub,
                                       reason=body.reason, rule=extra.get("rule"), cv=extra.get("cv"))
        store.execute(
            "UPDATE rr_curation_queue SET status = ?, decision_json = ?, decided_by = ?, decided_at = ?"
            " WHERE id = ?", (status, canonical_json(decision_json), owner_sub, now_epoch(), queue_id))
        _audit(store, owner_sub, scope=CURATION_AUDIT_SCOPE[kind],
               subject_id=str(payload.get("finding_id") or payload.get("cluster_key_norm")
                              or payload.get("a") or payload.get("tag") or queue_id),
               action="curation.decide", before={"kind": kind, "status": "open"},
               after={"status": status, "decision": body.decision}, reason=body.reason)
    return {"status": status, "decision_json": decision_json, "applied": applied}


# 'select *' 금지 — rr_patterns 에서 화면이 쓰는 열만 적는다(feature_ranges_json 은 상세 조회의 몫).
PATTERN_COLUMNS = (
    "id, owner_sub, visibility, cluster_key_norm, mechanism, mechanism_detail, change_kind, subject_class, "
    "status, n_findings, n_targets, n_projects, n_experts, n_confirmed, n_refuted, precision, merged_into, "
    "card_record_id, design_trait_tag, curated_by, promoted_at, suspended_reason, created_at, updated_at"
)


@router.get("/patterns")
def get_patterns(status: str | None = None,
                 ident: identity.Identity = Depends(identity.current)) -> dict:
    """§7.5 승격 상태 조회 — 내 패턴 + org 공개 패턴과, 그중 지금 도는 규칙(`active_pattern_rules`)."""
    owner_sub = _require_user(ident)
    store = get_store()
    sql = f"SELECT {PATTERN_COLUMNS} FROM rr_patterns WHERE (owner_sub = ? OR visibility = 'org')"
    params: list[Any] = [owner_sub]
    if status:
        sql += " AND status = ?"
        params.append(status)
    patterns = [dict(r) for r in store.query(sql + " ORDER BY id", params)]
    ids = {p["id"] for p in patterns}
    rules = [r for r in learning.active_pattern_rules(store) if r.get("pattern_id") in ids]
    return {"patterns": patterns, "rules": rules}
