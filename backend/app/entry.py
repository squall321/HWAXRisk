# Claude 입구 — MCP 쓰기 도구의 본체. REST 라우트 함수를 같은 신원으로 감싸 멱등하게 하고, 과제가 어디까지 왔고 무엇이 막혔고 다음에 무엇을 부르나를 한 번에 답한다(PLAN M1 'Claude 입구' · D-23)
"""입구는 둘(웹 화면·Claude)이고 원장은 하나다.

여기 함수는 전부 첫 인자로 /mcp 에 도달한 자격의 `Identity` 를 받아 REST 와 같은 라우트 함수에 그대로 넘긴다 —
소유권·역할 검사는 라우트의 것을 지난다(남의 과제는 E404). 쓰기는 그 신원이 게이트웨이 위임으로 확인됐을 때만 한다
(`require_delegate` — 위임 헤더 없이 접힌 단언·게이트웨이 서비스 세션의 Bearer·신원 없음은 까닭을 말하며 거절한다).
도구가 따로 하는 일은 셋뿐이다.

- 멱등 — 게이트웨이는 같은 호출을 한 번 더 보낼 수 있고(사람별 길의 1회 재시도) Claude 도 되묻는다. 같은 과제 코드·같은
  소스·같은 쌍·같은 대상·같은 Tier 의 살아 있는 잡이면 기존 것을 돌려준다(`created: false`).
- 막힘 안내 — 러너 자격이 없으면 웹의 어디에서 무엇을 누르라는 `fix` 를 붙인다. 비밀(PAT)은 도구 인자로 받지 않는다.
- 길잡이 — `next_step` 이 소스→캡처→리비전→same-as→비교→대상→명단→잡→결과를 걸어 where·blocked·next·facts 를 준다.
"""
from __future__ import annotations

import threading
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, ValidationError

from app import config, identity, planner, routes, runner
from app import roster as roster_module
from app import units as units_module
from app import state as state_module
from app.adapters import registry as adapters_registry
from app.common import canonical_json, now_epoch
from app.errors import AppError

# 웹 설정 화면의 버튼 이름 — 사람이 화면에서 찾는 글자다(frontend SettingsPage). 앱 서버는 포털 require_csrf 를 넘지 못해
# 사람 대신 PAT 를 발급할 수 없다(context-notes D33) — 그래서 고칠 곳은 늘 이 버튼이다.
SETTINGS_BUTTON = "포털에서 발급해 등록"
LIVE_JOB_STATES = ("queued", "running", "paused")
RUNNING_JOB_STATES = ("queued", "running", "cancelling")
# 캡처가 이 키 없이는 그 소스를 읽지 않는다(mcad.capture 422 · dyna.capture dyna_ref_incomplete). 소스를 지우는 REST 가
# 없으므로 행을 만들기 전에 거절한다. dyna_result 는 캡처 본문의 report_ids 가 ref 를 덮으므로 여기서 요구하지 않는다.
REF_REQUIRED = {"mcad": ("stepforge_project_id",), "dyna": ("session_id", "file_id")}
# 이 프로세스에서 MCP 로 캡처 중인 과제 — 게이트웨이 600초 한도에 끊긴 뒤 같은 캡처를 또 부르면 소스 앱을 두 번 읽고
# UNIQUE(project_id, ir_hash) 경합이 난다. DB 의 running 행은 웹 캡처일 수도, 예외로 끊긴 잔재일 수도 있어 막는 근거로 쓰지 않는다.
_capturing: set[str] = set()
_capturing_lock = threading.Lock()


# ---------------------------------------------------------------- 공통
def web_paths(*, project_id: str | None = None, target_key: str | None = None) -> dict:
    """웹 화면 경로(HashRouter). 앞머리는 이 앱이 떠 있는 프록시 경로(ROOT_PATH)에서 유도한다 — 박지 않는다."""
    root = str(getattr(config.settings, "root_path", "") or "").rstrip("/")
    out = {"settings": f"{root}/#/settings"}
    if project_id:
        out["project"] = f"{root}/#/projects/{quote(str(project_id), safe='')}"
    if target_key:
        out["target"] = f"{root}/#/targets/{quote(str(target_key), safe='')}"
    return out


def fix_register_pat() -> str:
    """러너·명단·dyna 캡처 자격이 없을 때의 고칠 곳 — 웹 설정 화면의 버튼 하나."""
    return (f"웹 리스크 앱 설정 화면({web_paths()['settings']})에서 '{SETTINGS_BUTTON}' 을 누른다 — 그 브라우저의 포털 세션으로"
            " 읽기 전용 PAT 를 발급해 이 앱에 등록한다. PAT 는 도구 인자로 받지 않는다(게이트웨이·대화 기록에 남는다).")


def _delegated(ident: identity.Identity) -> bool:
    return ident.source == "sso" and ident.delegated and bool(ident.email) and not ident.anonymous


def acting_as(ident: identity.Identity) -> dict:
    """이 호출이 누구로 해석됐나 — 웹 목록은 소유자 것만 보여 주므로, 쓴 것이 누구의 웹 화면에 뜨는지가 이것이다.

    `delegated` 가 참일 때만 쓰기 도구가 쓴다(`require_delegate`).
    """
    out = {"email": ident.email, "source": ident.source, "delegated": _delegated(ident)}
    if ident.source == "sso":
        out["note"] = ("게이트웨이 위임으로 확인된 신원이다 — 쓰기 도구는 이 사람으로 쓰고 이 사람의 웹 목록에 뜬다." if out["delegated"]
                       else "위임 헤더 없이 발급된 단언이라 이 이메일이 지금 부르는 사람인지 확인할 수 없다 — 읽기는 이 이메일의 시야로"
                       " 돌고 쓰기 도구는 거절한다(blocked 의 delegation_required).")
    return out


def _delegation_refusal(ident: identity.Identity) -> tuple[str, dict]:
    """쓰기를 거절하는 까닭(문구)과 기계 판독 칸 — 무엇이 없어서인지를 가르고, 고칠 곳(`fix`)도 그 원인을 따른다(RV-6).

    관리자·서비스 계정으로 떨어지지 않는다. Bearer 는 앱 MCP 를 개인 PAT 로 직접 등록한 사람과 사람별 위임 없이 부른 게이트웨이
    서비스 세션이 같은 모양이라 둘을 함께 말하되, 사람이 스스로 고칠 수 있는 직접 등록을 먼저 말한다.
    """
    root = str(getattr(config.settings, "root_path", "") or "").rstrip("/")
    web = f"그 전에는 웹 리스크 앱({root}/)에서 같은 일을 한다."
    if ident.anonymous or not ident.email:
        why = ("이 호출에는 확인된 신원이 없다 — 게이트웨이가 사람별 위임 단언(X-Heax-Sso-Assertion)을 싣지 않았거나(사람별 위임 없이"
               " 부른 서비스 세션 · 이 앱의 per_user_sso 가 설정되지 않은 박스) 단언의 서명·만료가 맞지 않는다.")
        fix = ("운영자가 게이트웨이의 사람별 위임(per_user_sso.hwax_risk, token_header=X-Heax-Sso-Assertion)과 이 앱의 게이트웨이"
               f" 시크릿이 맞는지 본다. {web}")
    elif ident.source == "sso":
        why = (f"이 호출의 단언({ident.email})은 게이트웨이가 위임 헤더(X-Hwax-Delegate-Email) 없이 받아 온 것이다 — 그 헤더를 보내지"
               " 않는 옛 게이트웨이면 HEAXHub Caddy 가 이메일을 게이트웨이 서비스 토큰의 주인(heax 첫 관리자)으로 덮어, 누가 부르든"
               " 같은 계정이 된다.")
        fix = f"운영자가 게이트웨이를 사람별 위임에 X-Hwax-Delegate-Email 을 싣는 판으로 올린다. {web}"
    else:
        why = (f"이 호출은 Bearer 토큰({ident.email})으로 왔다 — 앱 MCP 를 개인 PAT 로 직접 등록했거나(claude mcp add …"
               " /apps/hwax_risk/mcp --header 'Authorization: Bearer …') 사람별 위임 없이 부른 게이트웨이 서비스 세션(게이트웨이 heax"
               " 토큰 = heax 첫 관리자 PAT)이다. 둘 다 같은 모양이라 누가 부르는지 가를 수 없다.")
        fix = ("직접 등록이면 쓰기·결과 제출은 게이트웨이(hwax) MCP 로 부른다 — 직접 등록은 읽기 전용이다(운영자가 게이트웨이를"
               " 올려도 직접 등록한 길은 계속 거절된다). 게이트웨이를 거쳤는데 이렇다면 운영자가 게이트웨이의 사람별 위임"
               f"(per_user_sso.hwax_risk)이 이 앱에 걸렸는지 본다. {web}")
    detail = {"identity": {"email": ident.email, "source": ident.source, "delegated": bool(ident.delegated)}, "fix": fix}
    return why + " 쓰기 도구는 게이트웨이 위임으로 확인된 신원으로만 쓴다(그 계정으로 대신 쓰지 않는다).", detail


def require_delegate(ident: identity.Identity) -> str:
    """쓰기 도구의 문 — 게이트웨이 위임(X-Hwax-Delegate-Email 로 발급된 단언)으로 확인된 사람의 이메일. 아니면 `delegation_required`.

    읽기는 지금 규칙대로 도달한 신원의 시야로 돈다. 쓰기만 막는 까닭은 접힌 신원으로 쓴 것이 남의 웹 목록에 오르고, 남의 잡을
    되돌릴 수 없게 취소하며, 남의 PAT 로 잡을 돌리기 때문이다(SEC-1·SEC-2).
    """
    if _delegated(ident):
        return str(ident.email)
    why, detail = _delegation_refusal(ident)
    raise AppError("delegation_required", why, 403, detail=detail)


def _delegation_block(ident: identity.Identity) -> dict | None:
    """길잡이의 막힘 — 쓰기가 거절될 신원이면 그 까닭과 고칠 곳(위임 확인된 신원이면 None)."""
    if _delegated(ident):
        return None
    why, detail = _delegation_refusal(ident)
    return _blocked("delegation_required", why, detail["fix"], identity=detail["identity"])


def _body(model: type[BaseModel], **fields: Any) -> Any:
    """REST 본문 모델을 그대로 쓴다 — 검증 실패는 예외 추적이 아니라 REST 와 같은 422 E100 으로 답한다."""
    try:
        return model(**fields)
    except ValidationError as exc:
        reasons = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors())
        raise AppError("E100", f"인자가 계약에 맞지 않습니다 — {reasons}.", 422) from exc


def _step(tool: str, args: dict, why: str, *, write: bool = True) -> dict:
    return {"tool": tool, "args": args, "write": write, "why": why}


def _blocked(code: str, message: str, fix: str | None = None, **extra: Any) -> dict:
    out: dict[str, Any] = {"code": code, "message": message, **extra}
    if fix:
        out["fix"] = fix
    return out


# ---------------------------------------------------------------- 쓰기 — REST 라우트를 같은 신원으로 감싼다
def create_project(ident: identity.Identity, *, code: str, name: str, classification: str,
                   stage: str | None = None, predecessor_project_id: str | None = None,
                   product_code: str | None = None, adh_scope: dict | None = None) -> dict:
    """`POST /api/projects`. 같은 소유자의 같은 code 는 `UNIQUE(owner_sub, code)` 라 기존 과제를 돌려준다."""
    owner = require_delegate(ident)
    body = _body(routes.ProjectBody, code=code, name=name, classification=classification, stage=stage,
                 predecessor_project_id=predecessor_project_id, product_code=product_code, adh_scope=adh_scope)
    created = True
    try:
        row = routes.create_project(body, ident=ident)
    except AppError as exc:
        found = routes.get_store().query_one(
            "SELECT id FROM rr_projects WHERE owner_sub = ? AND code = ?", (owner, code)) if exc.code == "E409" else None
        if found is None:
            raise
        row, created = routes._project_row(found["id"], owner), False
    out = {**row, "created": created, "acting_as": acting_as(ident), "web": web_paths(project_id=row["id"])}
    if not created:
        differs = [key for key, want in (("name", name), ("stage", stage)) if want is not None and row.get(key) != want]
        if differs:
            out["differs"] = differs       # 같은 code 의 다른 과제를 만들려던 것일 수 있다 — 바꾸지 않고 알린다
    return out


def add_source(ident: identity.Identity, *, project_id: str, kind: str, ref: dict, app_key: str | None = None,
               bridge_declared: bool = False) -> dict:
    """`POST /api/projects/{id}/sources`. 같은 소스는 같은 행이고, 같은 kind 의 다른 소스는 거절한다.

    캡처는 kind 마다 첫 행만 쓰고(`capture_all`, `ORDER BY kind, id` — id 는 uuid) 소스를 지우는 REST 가 없다. 둘째 행이
    생기면 어느 쪽이 캡처될지 uuid 순서가 정하고 되돌릴 길이 없다.
    """
    owner = require_delegate(ident)
    routes._project_row(project_id, owner)
    if kind not in routes.SOURCE_KINDS:
        raise AppError("E100", f"kind 는 {list(routes.SOURCE_KINDS)} 중 하나여야 합니다 — {kind!r}.", 422)
    ref = dict(ref or {})
    missing = [key for key in REF_REQUIRED.get(kind, ()) if not ref.get(key)]
    if missing:
        raise AppError("E100", f"{kind} ref 에 {'·'.join(missing)} 가 없습니다 — 캡처가 이 소스를 읽지 못합니다."
                       " 소스는 지울 수 없어 잘못 붙이면 이 과제의 그 종류 캡처가 막힙니다.", 422)
    if app_key is None:
        # 웹이 고르는 값과 같게 — 게이트웨이 실측(`/meta/adapters`)이 먼저고, 못 읽으면 어댑터 기본값이다.
        kind_root = kind.split("_")[0]
        found = next((a for a in adapters_registry.discover_adapters(token=ident.token) if a["kind"] == kind_root), None)
        app_key = (found or {}).get("app_key") or adapters_registry.default_app_key(kind)
    same_kind = [s for s in routes._project_sources(project_id) if s["kind"] == kind]
    wanted = canonical_json(ref)

    def matches(source: dict) -> bool:
        return source["app_key"] == app_key and canonical_json(source["ref"]) == wanted

    existed = next((s for s in same_kind if matches(s)), None)
    if same_kind and existed is None:
        raise AppError("source_kind_taken",
                       f"이 과제에는 이미 {kind} 소스가 있습니다 — 캡처는 종류마다 하나만 읽고 소스는 지울 수 없습니다. 새 리비전이"
                       " 소스 앱의 다른 프로젝트에 있으면 risk_create_project(predecessor_project_id=이 과제) 로 새 과제를 만들어"
                       " 거기에 붙입니다.", 409, detail={"existing": same_kind})
    out = routes.add_source(project_id, _body(routes.SourceBody, kind=kind, app_key=app_key, ref=ref,
                                              bridge_declared=bridge_declared), ident=ident)
    row = next(s for s in routes._project_sources(project_id) if s["kind"] == kind and matches(s))
    return {**out, "source": row, "created": existed is None}


def running_snapshot_jobs(project_id: str) -> list[dict]:
    rows = routes.get_store().query(
        "SELECT id, label, started_at FROM rr_snapshot_jobs WHERE project_id = ? AND state = 'running'"
        " ORDER BY created_at DESC, rowid DESC", (project_id,))
    return [dict(r) for r in rows]


def capture_snapshot(ident: identity.Identity, *, project_id: str, label: str | None = None,
                     kinds: list[str] | None = None, report_ids: list[int] | None = None,
                     detect_result_file_id: str | None = None, allow_large: bool = False) -> dict:
    """`POST /api/projects/{id}/snapshots`(동기 캡처). 같은 내용이면 앱이 기존 스냅샷을 돌려준다(reused)."""
    owner = require_delegate(ident)
    routes._project_row(project_id, owner)
    body = _body(routes.SnapshotBody, label=label, kinds=list(kinds or []), report_ids=report_ids,
                 detect_result_file_id=detect_result_file_id, allow_large=allow_large)
    with _capturing_lock:
        if project_id in _capturing:
            raise AppError("capture_running", "이 과제의 캡처가 이미 돌고 있습니다 — 같은 호출을 다시 보내지 말고 risk_next_step"
                           " 으로 끝났는지 확인하세요.", 409, detail={"running_jobs": running_snapshot_jobs(project_id)})
        _capturing.add(project_id)
    try:
        out = routes.create_snapshot(project_id, body, ident=ident)
    finally:
        with _capturing_lock:
            _capturing.discard(project_id)
    return {**out, "web": web_paths(project_id=project_id)}


def ack_gate(ident: identity.Identity, *, snapshot_id: str, gate: str, reason: str,
             gates_hash: str | None = None) -> dict:
    """`POST /api/snapshots/{id}/gates/{gate}/ack` — upsert 라 같은 ack 는 한 행이다."""
    require_delegate(ident)
    return routes.post_gate_ack(snapshot_id, gate, _body(routes.GateAckBody, reason=reason, gates_hash=gates_hash),
                                ident=ident)


def get_sameas(ident: identity.Identity, *, base_snapshot_id: str, target_snapshot_id: str) -> dict:
    """`GET /api/sameas` — 두 스냅샷 모두 호출자 소유여야 한다."""
    routes._require_user(ident)
    return routes.get_sameas(base=base_snapshot_id, target=target_snapshot_id, ident=ident)


def decide_sameas(ident: identity.Identity, *, base_snapshot_id: str, target_snapshot_id: str,
                  decisions: list[dict]) -> dict:
    """`POST /api/sameas/decide` 의 confirm|reject — scope·pair_key 는 비교가 원장을 읽는 열쇠와 같게 여기서 채운다.

    `diff.create_diff`·`get_sameas` 는 `('pair', 정렬한 두 project_id 를 '|' 로 이은 것)` 으로 원장을 읽는다. 호출자가 그
    열쇠를 손으로 짓게 두면 한 글자만 어긋나도 결정이 아무 비교에도 닿지 않는다(오류 없이).
    """
    owner = require_delegate(ident)
    base = routes._snapshot_row(base_snapshot_id, owner)
    target = routes._snapshot_row(target_snapshot_id, owner)
    pair_key = "|".join(sorted([str(base["project_id"]), str(target["project_id"])]))
    items = []
    for item in decisions or []:
        decision = (item or {}).get("decision") if isinstance(item, dict) else None
        if decision not in ("confirm", "reject"):
            raise AppError("E100", f"decision 은 confirm|reject 여야 합니다 — {decision!r}.", 422)
        items.append({"decision": decision, "scope": "pair", "pair_key": pair_key,
                      "a_stable": item.get("a_stable"), "b_stable": item.get("b_stable"),
                      "snapshot_id": target_snapshot_id, "evidence": item.get("evidence")})
    if not items:
        raise AppError("E100", "decisions 가 비었습니다 — [{a_stable, b_stable, decision}] 를 하나 이상 주세요.", 422)
    return routes.post_sameas_decide(items, ident=ident)


def create_diff(ident: identity.Identity, *, base_snapshot_id: str, target_snapshot_id: str) -> dict:
    """`POST /api/diffs` — 같은 쌍은 저장된 비교를 돌려준다(앱이 원래 멱등이다)."""
    owner = require_delegate(ident)
    existed = routes.get_store().query_one(
        "SELECT id FROM rr_diffs WHERE base_snapshot_id = ? AND target_snapshot_id = ? AND owner_sub = ?",
        (base_snapshot_id, target_snapshot_id, owner)) is not None
    out = routes.create_diff(_body(routes.DiffBody, base_snapshot_id=base_snapshot_id,
                                   target_snapshot_id=target_snapshot_id), ident=ident)
    return {**out, "created": not existed}


def _target_summary(target_key: str) -> dict:
    store = routes.get_store()
    summary = planner.coverage_summary(store, target_key)
    plan = planner.tier_plan(store, target_key) if summary["roster_size"] else None
    return {"roster_size": summary["roster_size"], "deferred": plan["deferred"] if plan else 0,
            "tier_plan": plan["tiers"] if plan else None, "cost_estimate": plan["cost_estimate"] if plan else None}


def open_target(ident: identity.Identity, *, kind: str, ref_id: str, consent: bool = False, flow: str | None = None,
                reason: str | None = None) -> dict:
    """`POST /api/targets`. 이미 연 내 대상이면 그것이고, 명단이 비었으면 그 자리에서 최초 고정을 다시 시도한다.

    라우트는 kind·동의·참조 소유·G6 을 먼저 보고 '이미 열린 타깃' 409 를 마지막에 낸다 — 그래서 기존 대상을 돌려주는
    갈래도 같은 검사를 다 지난 뒤다. 명단이 비는 것은 자격이 없어 게이트웨이를 못 물었을 때다(roster_source unavailable).
    `flow` 는 심사 방식이다(D-24) — 새 대상은 그 방식으로 열고(없으면 panels), 이미 연 내 대상인데 방식이 다르면 웹과 같은
    바꾸기 함수(`POST /targets/{key}/flow`)를 지난다(감사 channel mcp). None 이면 방식을 건드리지 않는다.
    """
    owner = require_delegate(ident)
    body = _body(routes.TargetBody, kind=kind, ref_id=ref_id, consent=consent, flow=flow or "panels")
    try:
        out = {**routes.create_target(body, ident=ident), "created": True}
    except AppError as exc:
        if exc.code != "E409":
            raise
        key = f"{kind}:{ref_id}"
        row = routes._target_row(key, owner)
        out = {"target_key": key, "created": False, "superseded_by": row["superseded_by"], "flow": row["flow"]}
        if flow is not None and flow != row["flow"]:
            change = routes.post_target_flow(key, _body(routes.FlowBody, to=flow, reason=reason), ident=ident)
            out.update({"flow": change["flow"], "flow_change": change})
        if planner.coverage_summary(routes.get_store(), key)["roster_size"] == 0:
            out["roster_refresh"] = routes.refresh_roster(key, routes.RosterBody(), ident=ident)
        out.update(_target_summary(key))
    row = routes._target_row(out["target_key"], owner)
    return {**out, "web": web_paths(project_id=row["project_id"], target_key=out["target_key"])}


def start_job(ident: identity.Identity, *, target_key: str, tier: str, consent: bool = False,
              modifiers: list[str] | None = None, user_memo: str | None = None, concurrency: int = 1) -> dict:
    """`POST /api/targets/{key}/jobs`. 같은 대상·같은 Tier 의 살아 있는 잡이 있으면 그것을 돌려준다.

    라우트는 부를 때마다 잡 행을 하나 더 만든다(중복 검사 없음). 역할 검사는 라우트와 같은 함수로 먼저 한다 — 살아 있는
    잡을 돌려주는 갈래가 남의 대상의 잡을 흘리지 않게.
    """
    email = require_delegate(ident)
    store = routes.get_store()
    target = store.query_one("SELECT owner_sub, project_id FROM rr_targets WHERE target_key = ?", (target_key,))
    if target is None:
        raise AppError("E404", f"타깃({target_key}) 을 찾을 수 없습니다.", 404)
    if not routes._is_admin(ident):
        routes.require_role(target["project_id"], email, "editor")
    web = web_paths(project_id=target["project_id"], target_key=target_key)
    live = store.query_one(
        "SELECT id, tier, state, pause_reason, panels_done, panels_total, error, credential_email FROM rr_jobs"
        f" WHERE target_key = ? AND tier = ? AND {runner.PANEL_JOBS_SQL}"
        f" AND state IN ({','.join('?' for _ in LIVE_JOB_STATES)})"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1", (target_key, tier, *LIVE_JOB_STATES))
    if live is not None:
        return {"job_id": live["id"], "created": False, **{k: live[k] for k in live.keys() if k != "id"}, "web": web}
    body = _body(routes.JobBody, tier=tier, concurrency=concurrency, modifiers=modifiers, user_memo=user_memo,
                 consent=consent)
    try:
        out = routes.create_job(target_key, body, ident=ident)
    except AppError as exc:
        if exc.code == "pat_unavailable":
            raise AppError(exc.code, exc.message, exc.http_status, detail={**exc.detail, "fix": fix_register_pat()}) from exc
        raise
    return {**out, "created": True, "web": web}


# 이미 그 상태면 할 일이 없는 조작 — 러너는 이 경우 409 를 내지만 입구는 같은 호출을 두 번 받을 수 있다.
_ALREADY = {"pause": ("paused",), "resume": ("queued", "running")}


def job_action(ident: identity.Identity, *, job_id: str, action: str) -> dict:
    """`POST /api/jobs/{id}/{action}`(pause|resume|cancel). 이미 그 상태면 그대로 돌려준다(`changed: false`)."""
    require_delegate(ident)
    store = routes.get_store()
    before = store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))
    try:
        out = routes.job_action(job_id, action, ident=ident)
    except AppError as exc:
        # 라우트가 소유를 확인한 뒤에야 E100(상태 전이 불가)이 난다 — 여기서 상태를 읽어 돌려줘도 남의 잡을 흘리지 않는다.
        row = store.query_one("SELECT state, pause_reason FROM rr_jobs WHERE id = ?", (job_id,))
        if exc.code != "E100" or row is None or row["state"] not in _ALREADY.get(action, ()):
            raise
        return {"job_id": job_id, "state": row["state"], "pause_reason": row["pause_reason"], "changed": False}
    return {**out, "changed": before is None or out.get("state") != before["state"]}


def repersist_panel(ident: identity.Identity, *, panel_id: str, discard: bool = False) -> dict:
    """`POST /api/panels/{id}/repersist`(discard=1 이면 포기) — 원장에 앉히지 못해 엔진 결과가 패널에 남은 패널을 다시 앉힌다.

    다시 저장을 기다리는 패널이 남은 타깃은 새 패널을 편성하지 않는다(RR-ADV-1). 이 길이 REST 뿐이라 Claude 로 돌린 심사는
    저장이 한 번 실패하면 Claude 에서 풀 수 없었다(10-11 dev 실주행 — 7B 의장 출력의 모양 오류로 첫 패널이 persist_error).
    """
    require_delegate(ident)
    return routes.post_panel_repersist(panel_id, discard=discard, ident=ident)


# ---------------------------------------------------------------- 길잡이 — 어디까지 왔고 무엇이 막혔고 다음에 무엇을 부르나
def _credentials(store: Any, ident: identity.Identity, owner: str) -> dict:
    """자격 현황 — 값은 싣지 않고 있음·쓸 수 있음·남은 수명만. 규칙은 각 소비처의 것을 그대로 부른다."""
    secrets = config.load_secrets(config.settings.data_dir)
    row = store.get_credential(owner)
    usable = row is not None and identity.credential_pat(row) is not None
    left = int(row.get("pat_exp") or 0) - now_epoch() if row is not None else None
    runner_credential, runner_note = runner.resolve_credential_with_note(store, None, owner, ident.email)
    return {
        "portal_pat": {"registered": row is not None, "usable": usable, "seconds_left": left,
                       "revoked_at": row.get("revoked_at") if row is not None else None},
        "runner": runner_credential,
        "runner_note": runner_note,
        "roster": bool(roster_module.credential(store, owner)),
        # 캡처의 REST 채널(clients_from_settings) — 서비스 PAT 또는 호출자 본인의 heax 토큰. 게이트웨이 위임 신원은 토큰이 없다.
        "capture_rest": ("service_pat" if secrets.get("HWAXRISK_HEAX_SERVICE_PAT")
                         else "caller_token" if ident.token else None),
        # 캡처의 MCP 채널 — create_snapshot 과 같은 규칙(남은 수명 > CREDENTIAL_MARGIN_S 인 본인 PAT → 서비스 PAT).
        "capture_mcp": ("user_pat" if usable and left is not None and left > runner.CREDENTIAL_MARGIN_S
                        else "service_pat" if secrets.get("HWAXRISK_PORTAL_PAT") else None),
    }


def _gate_view(gates: dict) -> dict:
    return {key: {"pass": g.get("pass"), "reason": g.get("reason"), "count": g.get("count"), "effect": g.get("effect"),
                  "ack_by": g.get("ack_by")} for key, g in sorted(gates.items()) if isinstance(g, dict)}


def _snapshots(store: Any, project_id: str) -> list[dict]:
    """최신이 앞이다. 같은 초에 찍힌 둘은 rowid(넣은 순서)로 가른다 — uuid 순서는 무작위다."""
    rows = store.query(
        "SELECT s.id AS id, s.created_at AS created_at, s.node_count AS node_count, s.edge_count AS edge_count,"
        " s.capture_partial AS capture_partial, s.degraded_json AS degraded_json, j.label AS label,"
        " st.gates_json AS gates_json, st.blocked AS blocked FROM rr_snapshots s"
        " LEFT JOIN rr_snapshot_jobs j ON j.id = s.job_id LEFT JOIN rr_states st ON st.snapshot_id = s.id"
        " WHERE s.project_id = ? ORDER BY s.created_at DESC, s.rowid DESC", (project_id,))
    out = []
    for row in rows:
        gates = routes._loads(row["gates_json"], {})
        # 차단 판정은 create_target 과 같다 — 게이트 판정이 우선이고, 판정이 없는데 blocked 열이 서 있으면 단위 불일치다.
        reason = state_module.blocked_reason(gates) or ("unit_mismatch" if row["blocked"] else None)
        out.append({"id": row["id"], "label": row["label"], "created_at": row["created_at"],
                    "node_count": row["node_count"], "edge_count": row["edge_count"],
                    "partial": bool(row["capture_partial"]), "degraded": routes._loads(row["degraded_json"], []),
                    "blocked_reason": reason, "gates": _gate_view(gates)})
    return out


def _snapshot_jobs(store: Any, project_id: str) -> list[dict]:
    rows = store.query(
        "SELECT id, label, state, snapshot_id, error_json, started_at, finished_at FROM rr_snapshot_jobs"
        " WHERE project_id = ? ORDER BY created_at DESC, rowid DESC", (project_id,))
    return [{**{k: row[k] for k in row.keys() if k != "error_json"}, "error": routes._loads(row["error_json"], {}) or None}
            for row in rows]


_CAPTURE_FIX = {
    "model_too_large": "모델이 상한을 넘는다 — 그래도 동결하려면 사용자 확인 뒤 risk_capture_snapshot(allow_large=true).",
    "detect_not_done": "StepForge 의 계면 검출 잡이 끝나지 않았다 — 소스 앱에서 검출을 마친 뒤 다시 캡처한다.",
    "source_unreachable": "연결된 소스가 없다 — risk_add_source 로 먼저 붙인다.",
}


def _fix_gate_blocked(reason: str | None, project_id: str) -> str:
    if reason == state_module.UNKNOWN_BLOCKING_REASON:
        return (f"mcad 를 REST(/tree)로 읽지 못해 단위를 검문할 수 없었다 — 웹 과제 화면({web_paths(project_id=project_id)['project']})"
                "에서 다시 캡처하거나(로그인 토큰으로 REST 를 읽는다), 운영자가 앱 secrets.env 에 HWAXRISK_HEAX_SERVICE_PAT 를"
                " 넣은 뒤 risk_capture_snapshot 을 다시 부른다.")
    return "소스 앱에서 단위를 mm 로 맞추거나 모델 크기 불일치를 고친 뒤 risk_capture_snapshot 을 다시 부른다. G6 은 ack 로 넘길 수 없다."


def _rest_channel_absent(project_id: str) -> dict:
    return _blocked(
        "rest_channel_absent",
        "이 박스에는 소스 앱 REST 를 읽을 서비스 자격이 없고, 게이트웨이를 거친 호출에는 로그인 토큰이 없다 — Claude 에서 캡처하면"
        " mcad 가 MCP 폴백으로 읽혀 G6 이 unit_unknown 으로 막힌다.",
        _fix_gate_blocked(state_module.UNKNOWN_BLOCKING_REASON, project_id))


# 카드 대조(flow='cells')가 꺼진 박스의 길잡이 메모 — 대상을 열기 전 두 방식을 나란히 보이는 자리에서 cells 걸음 대신 쓴다.
REVIEW_OFF_NOTE = ("카드 대조(flow='cells' — 전문가별로 자기 지식카드를 단위마다 대조)는 이 박스에서 꺼져 있다 — 데이터 디렉터리의"
                   " knobs.env 에 HWAXRISK_REVIEW_ENABLED=1 을 적고 앱을 다시 띄우면 켜진다.")


# 동의는 사람이 하는 것이다 — 길잡이가 consent 를 채워 주면 next 를 그대로 따르는 에이전트가 묻지 않고 동의한 것이 되고, 원장에는
# 웹과 똑같이 '동의함' 이 남는다(SEC-4). 그래서 args 에 넣지 않고 why 로 받으라고만 말한다.
_CONSENT_WHY = " 동의는 사용자에게 받은 뒤에만 consent=true 를 더해 부른다(길잡이는 채워 주지 않는다)."


def _job_step(target_key: str, tier: str, plan_tiers: list[dict]) -> dict:
    row = next((t for t in plan_tiers if t["tier"] == tier), {})
    args: dict[str, Any] = {"target_key": target_key, "tier": tier}
    why = (f"Tier {tier} — 패널 {row.get('panels')}건 · LLM 호출 {row.get('llm_calls_low')}~{row.get('llm_calls_high')}회 추정."
           " Tier 는 누적이다(A 도메인 대표 → B → C 전원). 비용을 사용자에게 보이고 확인받은 뒤 부른다.")
    if tier == "C":
        why += _CONSENT_WHY
    return _step("risk_start_job", args, why)


def next_step(ident: identity.Identity, *, project_id: str | None = None) -> dict:
    """과제 하나의 단계를 걸어 where·blocked·next·facts 를 준다. project_id 가 없으면 내 과제 목록이다. 읽기 전용이다."""
    owner = routes._require_user(ident)
    store = routes.get_store()
    head = {"acting_as": acting_as(ident)}
    # 쓰기가 거절될 신원이면 그것이 첫 막힘이다 — next 의 쓰기 단계를 따라가도 delegation_required 로 막힌다.
    refusal = _delegation_block(ident)
    if not project_id:
        projects = [dict(r) for r in store.query(
            "SELECT id, code, name, stage, created_at FROM rr_projects WHERE owner_sub = ?"
            " ORDER BY created_at DESC, rowid DESC", (owner,))]
        steps = [_step("risk_next_step", {"project_id": p["id"]}, f"{p['code']} 가 어디까지 왔는지", write=False)
                 for p in projects]
        steps.append(_step("risk_create_project", {"code": "<과제 코드>", "name": "<과제 이름>",
                                                   "classification": "<internal|confidential>"},
                           "새 과제 — 코드·이름·등급(반출 경계)을 사용자에게 받아 만든다."))
        return {**head, "projects": projects, "web": web_paths(), "blocked": [refusal] if refusal else [], "next": steps}

    project = routes._project_row(project_id, owner)
    sources = routes._project_sources(project_id)
    snapshots = _snapshots(store, project_id)
    creds = _credentials(store, ident, owner)
    facts: dict[str, Any] = {"sources": sources, "snapshots": snapshots,
                             "snapshot_jobs": _snapshot_jobs(store, project_id), "credentials": creds}
    blocked: list[dict] = [refusal] if refusal else []
    notes: list[str] = []
    web = web_paths(project_id=project_id)

    def answer(where: str, steps: list[dict]) -> dict:
        return {**head, "project": {k: project[k] for k in ("id", "code", "name", "stage", "predecessor_project_id")},
                "web": web, "where": where, "blocked": blocked, "next": steps, "notes": notes, "facts": facts}

    # 1. 소스
    if not sources:
        return answer("sources", [
            _step("risk_add_source", {"project_id": project_id, "kind": "mcad",
                                      "ref": {"stepforge_project_id": "<StepForge 프로젝트 id>"}},
                  "설계(STEP)는 StepForge 에 올라가 있어야 한다. 계면 검출 잡 id 를 ref.detect_job_id 로 주면 간섭·간극까지 온다."),
            _step("risk_add_source", {"project_id": project_id, "kind": "dyna",
                                      "ref": {"session_id": "<DynaForge 세션 id>", "file_id": "<K 파일 id>"}},
                  "해석 모델(K 파일)은 그 사람의 DynaForge 세션에 있어야 한다 — 세션은 본인 PAT 로만 읽힌다."),
        ])
    kinds = [s["kind"] for s in sources]
    for kind in sorted({k for k in kinds if kinds.count(k) > 1}):
        notes.append(f"{kind} 소스가 {kinds.count(kind)}개다 — 캡처는 앞의 하나만 읽는다(어느 것인지는 facts.sources 의 순서).")
    for source in sources:
        missing = [key for key in REF_REQUIRED.get(source["kind"], ()) if not (source["ref"] or {}).get(key)]
        if missing:
            blocked.append(_blocked("source_ref_incomplete", f"{source['kind']} 소스 ref 에 {'·'.join(missing)} 가 없어 캡처가"
                                    " 그 소스를 읽지 못한다.", "소스는 지울 수 없다 — 새 과제를 만들어 바른 ref 로 붙인다.",
                                    source_id=source["id"]))
    if {"dyna", "dyna_result"} & set(kinds) and creds["capture_mcp"] != "user_pat":
        notes.append("dyna 는 사람별 세션이라 본인 PAT 가 있어야 읽힌다 — 없으면 dyna 가 빈 채 캡처된다. " + fix_register_pat())
    capture_blockers = [_rest_channel_absent(project_id)] if "mcad" in kinds and creds["capture_rest"] is None else []

    # 2. 캡처
    with _capturing_lock:
        capturing = project_id in _capturing
    if capturing:
        return answer("capture", [_step("risk_next_step", {"project_id": project_id},
                                        "이 과제의 캡처가 지금 돌고 있다 — 끝난 뒤 다시 본다.", write=False)])
    if any(j["state"] == "running" for j in facts["snapshot_jobs"]):
        notes.append("running 으로 남은 캡처 잡이 있다 — 웹에서 도는 중이거나 끊긴 잡이다(앱이 재기동하면 failed 로 닫힌다).")
    if not snapshots:
        last = facts["snapshot_jobs"][0] if facts["snapshot_jobs"] else None
        if last and last["state"] == "failed" and last["error"]:
            code = last["error"].get("code") or last["error"].get("stage")
            blocked.append(_blocked("capture_failed", str(last["error"].get("message") or code), _CAPTURE_FIX.get(code),
                                    job_id=last["id"], error=last["error"]))
        blocked.extend(capture_blockers)
        steps = [] if capture_blockers else [_step("risk_capture_snapshot", {"project_id": project_id},
                                                   "소스를 읽어 스냅샷을 동결한다(수십 초~수 분).")]
        return answer("capture", steps or [_step("risk_next_step", {"project_id": project_id},
                                                 "웹에서 캡처한 뒤 다시 본다.", write=False)])
    latest = snapshots[0]
    if latest["blocked_reason"]:
        blocked.append(_blocked("gate_blocked", "최신 스냅샷이 G6(단위·크기)으로 막혔다 — 변경 비교도 심사 대상도 열리지 않는다.",
                                _fix_gate_blocked(latest["blocked_reason"], project_id), reason=latest["blocked_reason"],
                                snapshot_id=latest["id"]))
        blocked.extend(capture_blockers)
        return answer("capture", [] if capture_blockers else [
            _step("risk_capture_snapshot", {"project_id": project_id}, "원인을 고친 뒤 다시 캡처한다.")])
    for key, gate in latest["gates"].items():
        if gate["pass"] is False and not gate["ack_by"]:
            notes.append(f"{key} 실패({gate['effect']}) — 진행을 막지 않는다. 사유를 남기려면 risk_ack_gate.")

    # 3. 리비전 — 변경 비교의 앞 스냅샷. 같은 과제의 앞 캡처가 먼저고, 없으면 계보 과제의 최신 캡처다.
    base = snapshots[1] if len(snapshots) > 1 else None
    if base is None and project.get("predecessor_project_id"):
        # 계보 과제도 호출자 것이어야 한다 — diff 가 두 스냅샷 모두 호출자 소유를 요구한다(diff._load_ir).
        if store.query_one("SELECT id FROM rr_projects WHERE id = ? AND owner_sub = ?",
                           (project["predecessor_project_id"], owner)) is not None:
            base = next(iter(_snapshots(store, project["predecessor_project_id"])), None)
    targets = [dict(r) for r in store.query(
        "SELECT target_key, kind, ref_id, superseded_by, roster_frozen_at, level, flow, created_at FROM rr_targets"
        " WHERE project_id = ? AND owner_sub = ? ORDER BY created_at DESC, rowid DESC", (project_id, owner))]
    facts["targets"] = targets
    if base is None:
        target_key = f"snap:{latest['id']}"
        if not any(t["target_key"] == target_key for t in targets):
            blocked.extend(capture_blockers)
            return answer("revision", [
                *([] if capture_blockers else [_step(
                    "risk_capture_snapshot", {"project_id": project_id},
                    "변경 심사에는 두 리비전이 필요하다 — 소스 앱에 새 리비전을 올린 뒤 같은 과제를 다시 캡처한다. 소스 앱의"
                    " 프로젝트가 바뀌었으면 risk_create_project(predecessor_project_id=이 과제) 로 새 과제를 만든다.")]),
                _step("risk_open_target", {"kind": "snap", "ref_id": latest["id"]},
                      "변경 없이 지금 설계를 심사한다(현황 심사)." + _CONSENT_WHY),
            ])
    else:
        facts["pair"] = {"base_snapshot_id": base["id"], "target_snapshot_id": latest["id"]}
        if base["blocked_reason"]:
            blocked.append(_blocked("gate_blocked", "비교의 앞 스냅샷이 G6 으로 막혀 변경 비교를 만들 수 없다.",
                                    _fix_gate_blocked(base["blocked_reason"], project_id),
                                    reason=base["blocked_reason"], snapshot_id=base["id"]))
            return answer("diff", [])
        diff = store.query_one(
            "SELECT id, stats_json FROM rr_diffs WHERE base_snapshot_id = ? AND target_snapshot_id = ? AND owner_sub = ?",
            (base["id"], latest["id"], owner))
        pair_args = {"base_snapshot_id": base["id"], "target_snapshot_id": latest["id"]}
        if diff is None:
            # 4. same-as — 비교는 만들 때의 원장으로 굳는다(같은 쌍은 저장본을 돌려준다). 확정은 비교 전에 해야 반영된다.
            pending = routes.get_sameas(base=base["id"], target=latest["id"], ident=ident)["pending_n"]
            facts["sameas_pending"] = pending
            if pending:
                return answer("sameas", [
                    _step("risk_get_sameas", pair_args, f"대응을 정하지 못한 부품 {pending}건 — 표를 읽는다.", write=False),
                    _step("risk_decide_sameas", {**pair_args, "decisions": [
                        {"a_stable": "<a_stable>", "b_stable": "<b_stable>", "decision": "confirm|reject"}]},
                          "사용자가 고른 대응을 확정한다 — 비교를 만든 뒤에는 반영되지 않는다."),
                    _step("risk_create_diff", pair_args, "확정 없이 진행한다 — 남은 대응은 G2 로 표기된다."),
                ])
            # 5. 변경 비교
            return answer("diff", [_step("risk_create_diff", pair_args, "앞·뒤 리비전의 변경을 비교한다.")])
        facts["diff"] = {"id": diff["id"], "counts": routes._loads(diff["stats_json"], {})}
        target_key = f"diff:{diff['id']}"

    # 6. 심사 대상
    kind, ref_id = target_key.split(":", 1)
    target = next((t for t in targets if t["target_key"] == target_key), None)
    if target is None:
        live = [t["target_key"] for t in targets if t["superseded_by"] is None]
        if live:
            notes.append(f"살아 있는 대상 {', '.join(live)} 은 새 대상을 열면 닫힌다(superseded) — 등록부는 변경에 따라 승계된다.")
        # 두 방식을 나란히 보인다(D-24) — 고르는 것은 사람이다. 패널 방식이 기본이라 첫 걸음의 인자는 종전 그대로다.
        steps = [_step("risk_open_target", {"kind": kind, "ref_id": ref_id},
                       "심사 대상을 열고 전문가 명단을 고정한다 — 방식은 panels(영역을 섞은 전문가 패널 3라운드, 기본)다."
                       + _CONSENT_WHY)]
        if kind == "diff":
            if config.review_enabled():
                steps.append(_step("risk_open_target", {"kind": kind, "ref_id": ref_id, "flow": "cells"},
                                   "같은 대상을 cells(전문가별 카드 대조 — 변경을 단위로 나눠 전문가마다 자기 지식카드로 판정)로"
                                   " 연다. 두 방식 가운데 사용자가 고른다." + _CONSENT_WHY))
            else:
                notes.append(REVIEW_OFF_NOTE)
        return answer("target", steps)
    web.update(web_paths(project_id=project_id, target_key=target_key))
    facts["target"] = target

    # 7. 명단
    coverage = routes.coverage_payload(target_key, owner_sub=owner)
    facts["coverage"] = {k: coverage[k] for k in ("roster_size", "by_status", "by_domain", "unseated_n", "strong",
                                                  "level", "close_level")}
    if coverage["roster_size"] == 0:
        fix = (fix_register_pat() + " 그 뒤 risk_open_target 을 같은 인자로 다시 부르면 명단을 받는다." if not creds["roster"]
               else "게이트웨이 전문가 조회가 비어 돌아왔다 — risk_open_target 을 같은 인자로 다시 부르면 명단을 다시 받는다.")
        blocked.append(_blocked("roster_empty", "전문가 명단이 비어 잡을 만들 수 없다.", fix))
        return answer("roster", [_step("risk_open_target", {"kind": kind, "ref_id": ref_id},
                                       "명단을 다시 받는다(이미 연 대상이면 그것을 돌려주고 명단만 고정한다)." + _CONSENT_WHY)])
    plan_tiers = planner.tier_plan(store, target_key)["tiers"]
    facts["tier_plan"] = plan_tiers

    # 8. 잡
    job = coverage["job"]
    facts["job"] = job
    # 엔진 결과가 다시 저장을 기다리는 패널 — 그 전에는 재개해도·새 잡을 세워도 이 타깃은 편성되지 않는다(RR-ADV-1).
    # 다시 저장은 risk_repersist_panel(MCP) 이고 웹 REST 경로도 함께 적는다(화면 버튼은 아직 없다).
    waiting = runner.awaiting_repersist(store, target_key)
    repersist_steps = [
        _step("risk_repersist_panel", {"panel_id": p["id"]},
              f"패널 #{p['panel_no']} 의 엔진 결과를 다시 앉힌다 — 원인을 고친 뒤에(같은 결과로 되풀이해 실패하면 discard=true 로 포기).")
        for p in waiting]
    if waiting:
        paths = " · ".join(f"POST /api/panels/{p['id']}/repersist" for p in waiting)
        blocked.append(_blocked(
            runner.REPERSIST_PENDING_CODE,
            f"엔진 결과가 다시 저장을 기다리는 패널이 {len(waiting)}건 있다 — {runner.REPERSIST_FIRST}(새 잡도 기다린다).",
            f"원인을 고친 뒤 risk_repersist_panel(panel_id) 로 다시 앉힌다(웹 REST 는 {paths}). 같은 결과로 다시 저장이"
            " 되풀이해 실패하면 discard=true(REST 는 ?discard=1)로 포기한다 — 엔진 결과는 패널에 남고 좌석은 다음 패널에서 다시 돈다.",
            panels=[p["id"] for p in waiting]))
    if target.get("flow") == "cells":
        return _cells_answer(answer, target_key, project_id, coverage["units"], repersist_steps, facts, blocked, notes)
    jobs = [dict(r) for r in store.query(
        f"SELECT tier, state FROM rr_jobs WHERE target_key = ? AND {runner.PANEL_JOBS_SQL}"
        " ORDER BY created_at DESC, rowid DESC", (target_key,))]
    done_tiers = {j["tier"] for j in jobs if j["state"] == "completed"}
    next_tier = next((t["tier"] for t in plan_tiers if t["panels"] and t["tier"] not in done_tiers), None)
    watch = [_step("risk_get_coverage", {"target_key": target_key, "with_seats": False}, "진행판(좌석 상태·완결 레벨).",
                   write=False),
             _step("risk_next_step", {"project_id": project_id}, "단계·막힘을 다시 본다.", write=False)]
    if job is not None and job["state"] in RUNNING_JOB_STATES:
        if str(job.get("error") or "").startswith("pat_unavailable"):
            blocked.append(_blocked("pat_unavailable", "러너가 이 잡을 돌릴 자격이 없어 줄에서 집지 않는다.", fix_register_pat(),
                                    job_id=job["id"]))
        return answer("running", [*repersist_steps, *watch])
    if job is not None and job["state"] == "paused":
        reason = job.get("pause_reason")
        if reason == "daily_cap":
            notes.append("하루 패널 상한에 걸려 멈췄다 — 자정 뒤 저절로 다시 줄을 선다.")
            return answer("paused", watch)
        why = {"restart": "앱이 재기동해 도는 패널을 닫고 잡을 멈췄다 — 재개하면 이어 돈다.",
               "diminishing": "최근 패널이 새 리스크를 거의 내지 않아 멈췄다 — 더 돌릴지 사용자에게 묻는다."}.get(
            reason, "멈춘 잡이다 — 재개하면 이어 돈다.")
        if waiting:
            # 종전에는 '재개하면 이어 돈다' 만 말해 그대로 따르면 다른 패널이 그 좌석을 가져가 결과를 잃었다.
            why = f"멈춘 잡이다 — {runner.REPERSIST_FIRST}(blocked 의 {runner.REPERSIST_PENDING_CODE})."
        return answer("paused", [*repersist_steps, _step("risk_job_action", {"job_id": job["id"], "action": "resume"}, why),
                                 *watch])
    if job is not None and job["state"] == "completed" and next_tier is None:
        return answer("done", [
            _step("risk_get_registry", {"target_key": target_key}, "판정 등록부 — 웹 대상 화면과 같은 원장이다.", write=False),
            _step("risk_list_panels", {"target_key": target_key}, "돈 패널 목록(발언·결정문은 risk_get_panel_transcript).",
                  write=False)])
    if job is not None and job["state"] in ("failed", "cancelled"):
        notes.append(f"마지막 잡 {job['id']} 는 {job['state']} 다" + (f" — {job['error']}" if job.get("error") else "") + ".")
    if next_tier is None:
        # 패널이 있는 Tier 를 전부 마쳤다 — 명단이 비지 않으면 도메인 rank 1 은 미뤄지지 않아 Tier A 패널이 늘 1건 이상이다.
        return answer("done", [_step("risk_get_registry", {"target_key": target_key}, "판정 등록부.", write=False)])
    if creds["runner"] is None:
        blocked.append(_blocked("pat_unavailable", creds["runner_note"] or "러너 자격이 없다 — 잡을 만들 수 없다.",
                                fix_register_pat()))
    steps = [_job_step(target_key, next_tier, plan_tiers)]
    if job is not None and job["state"] == "completed":
        steps.insert(0, _step("risk_get_registry", {"target_key": target_key}, "지금까지의 판정 등록부.", write=False))
        return answer("done", steps)
    return answer("job", steps)


def _cells_answer(answer, target_key: str, project_id: str, units_state: dict, repersist_steps: list[dict],
                  facts: dict, blocked: list[dict], notes: list[str]) -> dict:
    """카드 대조(flow='cells') 대상의 길잡이 — Tier 패널 잡은 받지 않는다(runner.panel_job_gate). 단위가 서 있지 않으면
    `units_unbuildable` 이 막힘이다. 검토 잡 걸음은 카드 대조 러너(재설계 M2 단계 C2b)가 이 자리에 붙인다."""
    facts["units"] = units_state
    if units_state.get("status") not in units_module.OPEN_STATUSES:
        blocked.append(_blocked(
            "units_unbuildable", f"이 카드 대조 대상의 검토 단위가 서 있지 않다(빌드 {units_state.get('status')}).",
            f"웹 REST POST /api/targets/{target_key}/units 로 다시 세우거나, 검토 잡이 서기 전이면 risk_open_target 에"
            " flow='panels' 를 주어 패널 방식으로 되돌린다.", units=units_state))
    notes.append("이 대상은 카드 대조(cells) 방식이다 — Tier 패널 잡(risk_start_job)은 받지 않는다. 카드 대조 검토 잡을 세우는"
                 " 도구는 이 앱 판에 아직 없다.")
    return answer("review", [
        *repersist_steps,
        _step("risk_get_units", {"target_key": target_key}, "검토 단위 목록(전문가가 카드로 대조할 변경 묶음).", write=False),
        _step("risk_get_coverage", {"target_key": target_key, "with_seats": False}, "진행판(방식·단위·좌석).", write=False),
        _step("risk_next_step", {"project_id": project_id}, "단계·막힘을 다시 본다.", write=False)])
