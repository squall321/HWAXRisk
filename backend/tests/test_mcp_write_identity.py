# 쓰기 도구의 신원 — 게이트웨이 위임(X-Hwax-Delegate-Email 로 발급된 단언)으로 확인된 사람만 쓰고, 접힌 단언·게이트웨이 서비스 세션(Bearer)·신원 없음은 까닭을 말하며 거절한다(SEC-1·SEC-2·SEC-5)
from __future__ import annotations

import json

import pytest
from starlette.requests import Request

import app.mcp_server as srv
from app import config, identity, planner, routes, runner
from tests.test_e2e_smoke import FakeSourceApps, no_network, seeded_discovery  # noqa: F401 — autouse 픽스처
from tests import factories, test_mcp_entry
from tests.test_mcp_entry import (OTHER, OWNER, SOURCE_REFS, SSO_SECRET, call, register_pat, web_ident, wire_sources,
                                  write_secrets)
from tests.test_wiring_regressions import DECISION, _seed

box = test_mcp_entry.box          # 입구 시험의 박스 픽스처(빈 DB·데이터 디렉터리·게이트웨이 시크릿)를 이 모듈에도 건다

# 게이트웨이 서비스 토큰의 주인 — provision 의 mint_heax 가 고른 '가장 먼저 만든 heax 관리자' 다. HEAXHub Caddy 의 forward_auth 는
# 앱으로 가는 X-Heax-User-Email 을 지우고 이 이메일로 다시 싣는다(proxy_manager `_forward_auth_handler(copy_identity=True)`).
FIRST_ADMIN = "first-admin@example.com"
GATEWAY_HEAX_PAT = "gateway-service-heax-pat"
WRITE_TABLES = ("rr_projects", "rr_sources", "rr_snapshots", "rr_diffs", "rr_targets", "rr_jobs", "rr_gate_acks",
                "rr_sameas", "rr_findings")
# 쓰기 9종 — id 가 있든 없든 신원 검사가 먼저다(없는 id 의 E404 로 존재를 흘리지도 않는다).
ENTRY_WRITES = {
    "risk_create_project": {"code": "P1", "name": "A 의 과제", "classification": "internal"},
    "risk_add_source": {"project_id": "p1", "kind": "mcad", "ref": SOURCE_REFS["mcad"]},
    "risk_capture_snapshot": {"project_id": "p1"},
    "risk_ack_gate": {"snapshot_id": "s1", "gate": "G3", "reason": "확인함"},
    "risk_decide_sameas": {"base_snapshot_id": "s0", "target_snapshot_id": "s1",
                           "decisions": [{"a_stable": "a", "b_stable": "b", "decision": "confirm"}]},
    "risk_create_diff": {"base_snapshot_id": "s0", "target_snapshot_id": "s1"},
    "risk_open_target": {"kind": "diff", "ref_id": "d1", "consent": True},
    "risk_start_job": {"target_key": "diff:d1", "tier": "A"},
    "risk_job_action": {"job_id": "j1", "action": "cancel"},
}


def assertion_from_gateway(client, delegate: str | None) -> str:
    """게이트웨이 → HEAXHub Caddy → 앱 `POST /api/auth/sso` 를 지금 배선 그대로 흉내 낸다.

    Caddy 는 X-Heax-User-Email 을 authz 가 준 이메일(게이트웨이 서비스 토큰의 주인)로 덮고, X-Hwax-Delegate-Email 은 건드리지
    않는다. `delegate=None` 은 그 헤더를 보내지 않는 옛 게이트웨이다.
    """
    headers = {"X-Heax-Gateway-Secret": SSO_SECRET, "X-Heax-User-Email": FIRST_ADMIN}
    if delegate is not None:
        headers["X-Hwax-Delegate-Email"] = delegate
    r = client.post("/api/auth/sso", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def act_with(box, headers: dict[str, str]) -> Request:
    """이번 /mcp 요청의 헤더를 정한다 — 도구는 이 요청에서 신원을 푼다."""
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    request = Request({"type": "http", "method": "POST", "path": "/mcp", "headers": raw, "query_string": b""})
    box.monkeypatch.setattr(srv, "_request", lambda: request)
    return request


def counts(box) -> dict[str, int]:
    return {t: box.store.query_one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in WRITE_TABLES}


@pytest.fixture
def heax_admin(box):
    """heax `/auth/me` 가 게이트웨이 heax 토큰을 그 주인(첫 관리자, role=admin)으로 푼다 — HEAXHub deps.get_current_user 와 같다."""
    box.monkeypatch.setattr(identity, "_fetch_me", lambda token: (
        {"email": FIRST_ADMIN, "role": "admin", "display_name": "관리자"} if token == GATEWAY_HEAX_PAT else None))
    identity.reset_cache()
    yield
    identity.reset_cache()


# ---------------------------------------------------------------- SEC-1 — 위임 헤더 없이 발급된 단언은 쓰지 못한다
def test_an_assertion_minted_without_the_delegate_header_cannot_write(client, box):
    """옛 게이트웨이(위임 헤더 없음)를 거친 단언의 이메일은 Caddy 가 덮은 서비스 토큰 주인이다 — 누가 부르든 그 한 계정이 된다.

    쓰기 9종은 그 단언으로 쓰지 않는다. 관리자 계정으로 떨어지지 않고, 무엇이 없어서 거절하는지(옛 게이트웨이일 수 있다)와
    고칠 곳을 말한다. 같은 게이트웨이가 위임 헤더를 실으면 그 사람으로 쓴다.
    """
    write_secrets(box, HWAXRISK_HEAX_SERVICE_PAT="service-pat")
    wire_sources(box, FakeSourceApps())
    # 관리자가 웹에서 직접 만든 과제 — 접힌 신원의 쓰기가 닿으면 안 되는 자리다.
    admin_pid = routes.create_project(routes.ProjectBody(code="ADM-1", name="관리자 웹 과제", classification="internal"),
                                      ident=web_ident(FIRST_ADMIN))["id"]
    before = counts(box)

    act_with(box, {identity.SSO_HEADER: assertion_from_gateway(client, None)})
    made = call("risk_create_project", code="P1", name="A 의 과제", classification="internal")
    assert made.get("error") == "delegation_required", made
    assert "X-Hwax-Delegate-Email" in made["message"] and FIRST_ADMIN in made["message"]
    assert made["detail"]["identity"] == {"email": FIRST_ADMIN, "source": "sso", "delegated": False}
    assert "/apps/hwax_risk/" in made["detail"]["fix"]
    attached = call("risk_add_source", project_id=admin_pid, kind="mcad", ref=SOURCE_REFS["mcad"])
    assert attached.get("error") == "delegation_required", attached
    for name, args in ENTRY_WRITES.items():
        assert call(name, **args).get("error") == "delegation_required", name
    assert counts(box) == before

    # 길잡이(읽기)는 지금 규칙대로 답하되, 쓰기가 막혔다는 것과 그 까닭을 막힘으로 먼저 말한다.
    guide = call("risk_next_step")
    assert guide["acting_as"]["delegated"] is False
    assert [b["code"] for b in guide["blocked"]] == ["delegation_required"]
    guide = call("risk_next_step", project_id=admin_pid)
    assert guide["blocked"][0]["code"] == "delegation_required"

    # 같은 게이트웨이가 위임 헤더를 실으면 그 사람이 쓰고, 그 사람의 웹 목록에 뜬다.
    act_with(box, {identity.SSO_HEADER: assertion_from_gateway(client, OWNER)})
    made = call("risk_create_project", code="P1", name="A 의 과제", classification="internal")
    assert made["created"] is True and made["acting_as"] == {**made["acting_as"], "email": OWNER, "delegated": True}
    assert box.store.query_one("SELECT owner_sub FROM rr_projects WHERE id = ?", (made["id"],))["owner_sub"] == OWNER
    assert [p["id"] for p in routes.list_projects(ident=web_ident(OWNER))["projects"]] == [made["id"]]
    assert [p["id"] for p in routes.list_projects(ident=web_ident(FIRST_ADMIN))["projects"]] == [admin_pid]
    assert call("risk_next_step")["blocked"] == []


def test_no_identity_is_refused_with_what_is_missing(box):
    """단언이 없다(게이트웨이가 사람별 위임 없이 부른 서비스 세션 · 요청 밖) — 쓰지 않고 '신원이 없다' 를 말한다."""
    act_with(box, {})
    out = call("risk_create_project", code="P1", name="과제", classification="internal")
    assert out["error"] == "delegation_required" and "신원" in out["message"]
    assert out["detail"]["identity"] == {"email": None, "source": "none", "delegated": False}
    # 위조 단언도 신원 없음이다.
    forged = identity.mint_sso_assertion(OWNER, ttl_s=900, secret="not-the-secret", delegated=True)
    act_with(box, {identity.SSO_HEADER: forged})
    assert call("risk_create_project", code="P1", name="과제", classification="internal")["error"] == "delegation_required"
    assert counts(box)["rr_projects"] == 0


# ---------------------------------------------------------------- SEC-2 — 게이트웨이 서비스 세션은 관리자 쓰기가 아니다
def test_the_gateway_service_session_is_not_an_admin_writer(client, box, heax_admin):
    """신원 없는 게이트웨이 호출(서비스 세션)은 Authorization: Bearer <게이트웨이 heax 토큰 = 첫 관리자 PAT> 만 싣는다.

    앱은 그 Bearer 를 heax 에 되물어 role=admin 으로 풀었고, 관리자 우회(_is_admin)로 남의 타깃에 Tier C 잡을 세웠다 — 그 잡은
    타깃 소유자의 PAT 로 돈다. MCP 길의 신원에는 역할이 없고, Bearer 로 온 호출은 쓰지 못한다.
    """
    write_secrets(box, HWAXRISK_HEAX_SERVICE_PAT="service-pat")
    register_pat(box, OWNER, 30 * 86400)
    apps = FakeSourceApps()
    wire_sources(box, apps)
    act_with(box, {identity.SSO_HEADER: assertion_from_gateway(client, OWNER)})
    pid = call("risk_create_project", code="MINE", name="내 과제", classification="confidential")["id"]
    call("risk_add_source", project_id=pid, kind="mcad", ref=SOURCE_REFS["mcad"])
    s1 = call("risk_capture_snapshot", project_id=pid)["snapshot_id"]
    apps.revise()
    s2 = call("risk_capture_snapshot", project_id=pid)["snapshot_id"]
    diff_id = call("risk_create_diff", base_snapshot_id=s1, target_snapshot_id=s2)["diff_id"]
    target_key = call("risk_open_target", kind="diff", ref_id=diff_id, consent=True)["target_key"]

    request = act_with(box, {"Authorization": f"Bearer {GATEWAY_HEAX_PAT}"})
    ident = routes.mcp_identity(request)
    assert ident.email == FIRST_ADMIN and ident.source == "bearer"
    assert ident.role is None and not routes._is_admin(ident)        # MCP 길에는 관리자 우회가 없다
    refused = call("risk_start_job", target_key=target_key, tier="C", consent=True)
    assert refused.get("error") == "delegation_required", refused
    assert "Bearer" in refused["message"]
    assert box.store.query("SELECT id FROM rr_jobs") == []
    assert call("risk_job_action", job_id="j1", action="cancel")["error"] == "delegation_required"
    # 읽기는 지금 규칙대로다 — 그 신원은 남의 과제 단계를 보지 못한다.
    assert call("risk_next_step", project_id=pid)["error"] == "E404"


# ---------------------------------------------------------------- SEC-5 — 옛 쓰기 도구 둘의 actor 는 소유권 열쇠가 아니다
def _finding_args(target_key: str, actor: str) -> dict:
    return {"target_key": target_key, "claim": "조립 시 간극이 부족해 보인다",
            "cites": [{"ref": "p:0123456789ab", "quote": "«PLATE_1»"}], "actor": actor, "domain": "mech",
            "mechanism": "interface", "subject_names": ["PLATE_1"], "severity": "중대", "judgement": "WARNING"}


def test_the_old_write_tools_take_ownership_from_the_reached_identity_not_actor(client, box):
    """risk_submit_panel_result·risk_add_finding 은 자칭 actor 를 소유권 열쇠로 썼다 — 남이 actor=<소유자> 를 넣으면 남의 패널을
    종결하고 남의 타깃에 finding 을 썼다. 소유권은 도달한 위임 신원이 정하고 actor 는 표기로만 남는다."""
    target_key = _seed(box.store, owner=OWNER)
    panel = planner.plan_next_panel(box.store, target_key, "B")
    turns = [{"round": 1, "persona": s["key"], "say": "발언"} for s in panel["seats"]]

    act_with(box, {identity.SSO_HEADER: assertion_from_gateway(client, OTHER)})
    stolen = srv.risk_submit_panel_result(panel_id=panel["id"], engine="mcp", decision_text=DECISION, turns=turns,
                                          report_id=None, actor=OWNER)
    assert stolen.get("error") == "E404", stolen
    assert box.store.query_one("SELECT status FROM rr_panels WHERE id = ?", (panel["id"],))["status"] == "planned"
    assert srv.risk_add_finding(**_finding_args(target_key, OWNER)).get("error") == "E404"
    assert counts(box)["rr_findings"] == 0

    # 옛 게이트웨이(위임 헤더 없음)로 접힌 단언이면 둘 다 거절하고 까닭을 말한다.
    act_with(box, {identity.SSO_HEADER: assertion_from_gateway(client, None)})
    folded = srv.risk_submit_panel_result(panel_id=panel["id"], engine="mcp", decision_text=DECISION, turns=turns,
                                          report_id=None, actor=OWNER)
    assert folded["error"] == "delegation_required" and "X-Hwax-Delegate-Email" in folded["message"]
    assert srv.risk_add_finding(**_finding_args(target_key, OWNER))["error"] == "delegation_required"

    # 소유자 본인(위임 확인)이면 actor 가 무엇이든 받는다 — actor 는 미검증 표기로만 남는다.
    act_with(box, {identity.SSO_HEADER: assertion_from_gateway(client, OWNER)})
    done = srv.risk_submit_panel_result(panel_id=panel["id"], engine="mcp", decision_text=DECISION, turns=turns,
                                        report_id=None, actor="whoever@example.com")
    assert "error" not in done, done
    quality = json.loads(box.store.query_one("SELECT quality_json FROM rr_panels WHERE id = ?",
                                             (panel["id"],))["quality_json"])
    assert quality["actor"] == "whoever@example.com" and quality["actor_verified"] is False
    added = srv.risk_add_finding(**_finding_args(target_key, "whoever@example.com"))
    assert "error" not in added, added
    assert box.store.query_one("SELECT author_sub FROM rr_findings WHERE finding_id = ?",
                               (added["finding_id"],))["author_sub"] == OWNER


# ---------------------------------------------------------------- RV-1 — 낼 수 없는 신원에게는 브리프를 동결해 주지 않는다
def _panel_state(box, panel_id: str) -> dict:
    """브리프 수신이 패널에 남기는 것 전부 — 상태·품질(brief_clipped 등)·동결본(brief_gz·해시)."""
    row = box.store.query_one(
        "SELECT status, quality_json, brief_gz, brief_hash, brief_item_hashes_json FROM rr_panels WHERE id = ?",
        (panel_id,))
    return dict(row)


def test_the_brief_refuses_an_identity_that_could_not_submit_before_freezing(client, box, heax_admin):
    """risk_get_brief 는 brief_token 만 대조해 브리프를 동결하고 패널 품질까지 쓴 뒤 정상 응답을 줬다 — 그 신원이 결과 제출에서
    delegation_required(접힌 단언·Bearer·신원 없음)나 E404(패널 소유자가 아님)로 거절될 사람이어도 몇 시간 심의를 돌린 뒤에야
    알았다. 브리프 토큰의 쓰임은 그 신원의 제출뿐이라, 제출이 거절될 신원은 동결·품질 쓰기 전에 제출과 같은 코드로 거절한다."""
    box.monkeypatch.setattr(routes.field_source, "for_target", lambda *a, **k: None)
    synth = factories.make_diff_target(box.store, 40, owner=OWNER)
    issued = routes.brief_payload(synth.target_key, "B", owner_sub=OWNER, issue_token=True)["panels"][0]
    panel_id, token = issued["panel_id"], issued["brief_token"]
    before = _panel_state(box, panel_id)
    assert before["status"] == "planned" and before["brief_gz"] is None

    refusals = (
        ({identity.SSO_HEADER: assertion_from_gateway(client, None)}, "delegation_required"),   # 옛 게이트웨이 — 접힘
        ({"Authorization": f"Bearer {GATEWAY_HEAX_PAT}"}, "delegation_required"),              # 서비스 세션·직접 등록
        ({}, "delegation_required"),                                                            # 신원 없음
        ({identity.SSO_HEADER: assertion_from_gateway(client, OTHER)}, "E404"),                 # 위임됐지만 소유자가 아니다
    )
    for headers, code in refusals:
        act_with(box, headers)
        out = srv.risk_get_brief(synth.target_key, token)
        assert out.get("error") == code, (headers.keys(), out)
        # 제출도 같은 코드로 거절된다 — 브리프만 열리면 심의를 다 돌린 뒤에야 안다.
        submitted = srv.risk_submit_panel_result(panel_id=panel_id, engine="mcp", decision_text=DECISION, turns=[],
                                                 report_id=None, actor=OWNER)
        assert submitted.get("error") == code, submitted
        assert _panel_state(box, panel_id) == before, "거절한 호출이 패널을 동결했거나 품질을 썼다"
    act_with(box, {identity.SSO_HEADER: assertion_from_gateway(client, None)})
    folded = srv.risk_get_brief(synth.target_key, token)
    assert "X-Hwax-Delegate-Email" in folded["message"] and folded["detail"]["fix"]

    # 위임으로 확인된 패널 소유자면 지금처럼 그 패널을 동결해 준다 — 틀린 토큰은 여전히 brief_token_invalid 다.
    act_with(box, {identity.SSO_HEADER: assertion_from_gateway(client, OWNER)})
    assert srv.risk_get_brief(synth.target_key, token + "x")["error"] == "brief_token_invalid"
    out = srv.risk_get_brief(synth.target_key, token)
    assert [p["panel_id"] for p in out["panels"]] == [panel_id], out
    assert _panel_state(box, panel_id)["brief_gz"] is not None


# ---------------------------------------------------------------- RV-6 — 거절의 고칠 곳은 원인을 따른다
PERSONAL_PAT = "heax_pat_owner_personal"     # 사람이 앱 MCP 를 직접 등록할 때 싣는 개인 heax PAT(README '포털 경유' 예시)
FOLDED_FIX = "X-Hwax-Delegate-Email 을 싣는 판으로 올"


def test_the_refusal_names_the_fix_for_its_cause(client, box):
    """직접 등록(개인 PAT Bearer) 길은 쓰기가 막혔는데(SEC-1) 거절 문구는 원인과 무관하게 '운영자가 게이트웨이를 X-Hwax-Delegate-Email
    을 싣는 판으로 올린다' 를 줬다 — 게이트웨이를 거치지 않는 사용자에게 틀린 처방이고, 운영자가 게이트웨이를 올려도 이 사용자는 계속
    거절된다(RV-6). Bearer 는 '직접 등록이면 게이트웨이(hwax) MCP 로 부른다(직접 등록은 읽기 전용)' 를 먼저 말하고, 접힌 단언(옛
    게이트웨이)은 운영자의 게이트웨이 판 올리기를 말한다. 길잡이의 막힘도 같은 고칠 곳이다."""
    box.monkeypatch.setattr(identity, "_fetch_me", lambda token: (
        {"email": OWNER, "role": "user", "display_name": "소유자"} if token == PERSONAL_PAT else None))
    identity.reset_cache()
    try:
        act_with(box, {"Authorization": f"Bearer {PERSONAL_PAT}"})
        direct = call("risk_create_project", code="P1", name="과제", classification="internal")
        assert direct.get("error") == "delegation_required", direct
        assert direct["detail"]["identity"] == {"email": OWNER, "source": "bearer", "delegated": False}
        assert "직접 등록" in direct["message"]
        fix = direct["detail"]["fix"]
        assert "게이트웨이(hwax) MCP" in fix and "읽기 전용" in fix and FOLDED_FIX not in fix, fix
        assert call("risk_next_step")["blocked"][0]["fix"] == fix
        # 읽기는 그 사람의 시야로 그대로 돈다 — 직접 등록이 읽기 전용이라는 안내와 맞는다.
        assert call("risk_list_projects").get("error") is None
    finally:
        identity.reset_cache()

    act_with(box, {identity.SSO_HEADER: assertion_from_gateway(client, None)})
    folded = call("risk_create_project", code="P1", name="과제", classification="internal")
    assert folded["error"] == "delegation_required"
    assert FOLDED_FIX in folded["detail"]["fix"] and "직접 등록" not in folded["detail"]["fix"], folded["detail"]["fix"]
    assert counts(box)["rr_projects"] == 0


# ---------------------------------------------------------------- RV-7 — 잡의 동의가 어느 입구에서 왔는지 원장에 남는다
def _job_params(box, job_id: str) -> dict:
    return json.loads(box.store.query_one("SELECT params_json FROM rr_jobs WHERE id = ?", (job_id,))["params_json"])


def test_a_job_records_where_its_consent_came_from(client, box):
    """SEC-4 고침은 길잡이가 consent 를 미리 채우지 않게만 했다 — 에이전트가 묻지 않고 consent=true 를 넣어 Tier C 잡을 세워도 잡
    params 에는 웹 화면 동의와 구별되지 않는 consent:true 만 남았다(RV-7). 동의의 출처(consent_source)를 남긴다 — Claude 길(게이트웨이
    위임 단언)은 'mcp', 웹은 'web', 동의 없는 잡은 None 이다. 타깃 행은 이미 principal_json.source 로 갈린다. 개인 heax PAT(Bearer)로
    REST 에서 세운 잡은 웹 화면 동의가 아니다 — 'api' 로 가른다(3차 검토 발견 4)."""
    target_key = _seed(box.store, owner=OWNER)

    act_with(box, {identity.SSO_HEADER: assertion_from_gateway(client, OWNER)})
    claude = call("risk_start_job", target_key=target_key, tier="C", consent=True)
    assert claude.get("created") is True, claude
    assert _job_params(box, claude["job_id"])["consent"] is True
    assert _job_params(box, claude["job_id"])["consent_source"] == "mcp"

    web = routes.create_job(target_key, routes.JobBody(tier="B", consent=True), ident=web_ident(OWNER))
    assert _job_params(box, web["job_id"])["consent_source"] == "web"
    unasked = routes.create_job(target_key, routes.JobBody(tier="A"), ident=web_ident(OWNER))
    assert _job_params(box, unasked["job_id"])["consent_source"] is None

    # 개인 heax PAT 를 Bearer 로 실어 REST 를 직접 부른 잡 — 신원은 실제 identity.current 가 heax /auth/me 로 푼다.
    box.monkeypatch.setattr(identity, "_fetch_me", lambda token: (
        {"email": OWNER, "role": "user", "display_name": "소유자"} if token == PERSONAL_PAT else None))
    identity.reset_cache()
    try:
        bearer = identity.current(act_with(box, {"Authorization": f"Bearer {PERSONAL_PAT}"}))
        assert bearer.source == "bearer" and bearer.email == OWNER
        api = routes.create_job(target_key, routes.JobBody(tier="B", consent=True), ident=bearer)
        assert _job_params(box, api["job_id"])["consent_source"] == "api"
    finally:
        identity.reset_cache()

    # 닫힘 레벨 C3 이 Tier B 뒤에 세우는 Tier C 는 사람이 아니라 그 정책이 동의한 것이다.
    box.store.execute("UPDATE rr_targets SET close_level = 'C3' WHERE target_key = ?", (target_key,))
    job = dict(box.store.query_one("SELECT id, target_key, tier, owner_sub FROM rr_jobs WHERE id = ?", (web["job_id"],)))
    follow = runner._finish_job(box.store, {**job, "params": _job_params(box, web["job_id"])}, config.settings)["next_job"]
    assert _job_params(box, follow)["consent_source"] == "close_level"
