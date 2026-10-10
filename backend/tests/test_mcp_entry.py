# Claude 입구 — MCP 쓰기 도구가 REST 와 같은 라우트를 같은 신원으로 거쳐 웹 원장에 올라가는지, 멱등·막힘 안내·남의 과제 차단·이벤트 루프 비점유를 실제 캡처·명단 경로로 본다
from __future__ import annotations

import asyncio
import json
import threading
import types

import httpx
import pytest
from starlette.requests import Request

import app.mcp_server as srv
from app import config, identity, ir_builder, roster, routes, sameas
from app import state as state_module
from app.adapters import registry as adapters_registry
from app.adapters.base import RestGetClient
from app.common import now_epoch
from tests.test_e2e_smoke import FakeSourceApps, no_network, seeded_discovery  # noqa: F401 — autouse 픽스처
from tests import factories
from tests import test_adapters as recon
from tests.test_roster import _gateway_handler

OWNER = "claude-user@example.com"
OTHER = "someone-else@example.com"
SSO_SECRET = "entry-test-gateway-secret"
DOMAINS = ("mech", "sim", "xd")          # 로스터 도메인 — test_roster 의 가짜 게이트웨이 카탈로그와 같다
SOURCE_REFS = {
    "mcad": {"stepforge_project_id": recon.SF_PROJECT, "detect_job_id": "01JDET"},
    "dyna": {"session_id": "01JSES", "file_id": "01JFIL", "sha256": recon.KSHA},
    "dyna_result": {"report_ids": ["r1"]},
}


def call(tool: str, /, **kwargs) -> dict:
    """도구 함수를 끝까지 돌린다(입구 도구는 async 이고 본문은 스레드에서 돈다)."""
    out = getattr(srv, tool)(**kwargs)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def _request_as(email: str | None) -> Request:
    """게이트웨이 위임과 같은 모양의 /mcp 요청 — 사용자 자격은 서명된 단언 헤더로 온다.

    단언은 앱의 실제 발급 함수가 게이트웨이의 위임 헤더(X-Hwax-Delegate-Email)로 만든 것이다 — 쓰기 도구는 그 단언만 받는다.
    """
    headers = []
    if email:
        token = factories.delegated_assertion(email)
        headers.append((identity.SSO_HEADER.encode(), token.encode()))
    return Request({"type": "http", "method": "POST", "path": "/mcp", "headers": headers, "query_string": b""})


@pytest.fixture
def box(risk_store, monkeypatch, tmp_path):
    """한 박스 — 빈 DB · 임시 데이터 디렉터리(secrets.env·cred.key) · 게이트웨이 시크릿 · 가짜 명단 게이트웨이."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(config, "settings", types.SimpleNamespace(
        **{**vars(config.settings), "data_dir": tmp_path, "risk_roster_domains": DOMAINS,
           "gateway_mcp": "https://gw.test/mcp", "root_path": "/apps/hwax_risk"}))
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: SSO_SECRET)
    previous = roster.set_transport(httpx.MockTransport(_gateway_handler()))
    yield types.SimpleNamespace(store=risk_store, data_dir=tmp_path, monkeypatch=monkeypatch)
    roster.set_transport(previous)


def act_as(box, email: str | None) -> None:
    request = _request_as(email)
    box.monkeypatch.setattr(srv, "_request", lambda: request)


def write_secrets(box, **values: str) -> None:
    path = box.data_dir / "secrets.env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    path.chmod(0o600)


def register_pat(box, email: str, seconds_left: int) -> None:
    """웹 설정 화면의 '포털에서 발급해 등록' 이 남기는 것과 같은 행(Fernet 암호문) — 도구 인자로는 받지 않는다."""
    box.store.upsert_credential(email, identity.encrypt_pat(f"pat-{email}").decode("ascii"), "sub", email, "[]",
                                now_epoch() + seconds_left)


def wire_sources(box, apps: FakeSourceApps) -> None:
    """캡처 채널 — 이 박스가 실제로 넘기는 인자를 따른다. REST 자격은 서비스 PAT(secrets.env) 또는 호출자 heax 토큰이고,
    게이트웨이 위임(SSO 단언)으로 온 호출자는 heax 토큰이 없다(identity.current)."""
    def channels(settings, secrets=None, *, portal_pat=None, heax_token=None, **_):
        out = apps.channels()
        token = (secrets or {}).get("HWAXRISK_HEAX_SERVICE_PAT") or heax_token
        if not token:
            out["rest"].close()
            out["rest"] = RestGetClient("https://heax.test", None)
            out["service_pat"] = None
        return out

    box.monkeypatch.setattr(adapters_registry, "clients_from_settings", channels)


def web_ident(email: str) -> identity.Identity:
    """웹 화면의 신원 — 로그인 쿠키를 heax 에 되물어 얻는 것과 같은 모양."""
    return identity.Identity(email=email, display_name=email, role="user", organization=None, anonymous=False,
                             source="cookie", token="heax-web-token")


def first_next(out: dict) -> dict:
    assert out["next"], out
    return out["next"][0]


# ---------------------------------------------------------------- 한 바퀴 — Claude 로 올린 과제가 웹 원장에 그대로 있다
def test_claude_entry_runs_from_project_to_job_and_lands_in_the_web_ledger(box):
    act_as(box, OWNER)
    write_secrets(box, HWAXRISK_HEAX_SERVICE_PAT="service-pat")      # REST 자격이 있는 박스
    apps = FakeSourceApps()
    wire_sources(box, apps)

    # 0. 과제가 없으면 과제 만들기부터 — 누구로 해석됐는지를 늘 말한다.
    out = call("risk_next_step")
    assert out["acting_as"]["email"] == OWNER and out["acting_as"]["source"] == "sso"
    assert out["acting_as"]["delegated"] is True and out["blocked"] == []
    assert out["projects"] == [] and first_next(out)["tool"] == "risk_create_project"

    # 1. 과제 — 같은 code 를 다시 보내면 같은 과제다(게이트웨이는 같은 호출을 한 번 더 보낼 수 있다).
    project = call("risk_create_project", code="CLAUDE-1", name="Claude 로 올린 과제", classification="internal")
    assert project["created"] is True and project["acting_as"]["email"] == OWNER
    pid = project["id"]
    again = call("risk_create_project", code="CLAUDE-1", name="Claude 로 올린 과제", classification="internal")
    assert again["created"] is False and again["id"] == pid
    assert box.store.query_one("SELECT COUNT(*) AS n FROM rr_projects")["n"] == 1
    assert project["web"]["project"] == f"/apps/hwax_risk/#/projects/{pid}"
    # 웹 목록은 소유자 것만 보여 준다 — 같은 사람의 웹 화면에 뜨고 남의 화면에는 안 뜬다.
    assert [p["id"] for p in routes.list_projects(ident=web_ident(OWNER))["projects"]] == [pid]
    assert routes.list_projects(ident=web_ident(OTHER))["projects"] == []

    out = call("risk_next_step", project_id=pid)
    assert out["where"] == "sources" and first_next(out)["tool"] == "risk_add_source"

    # 2. 소스 — 같은 소스는 같은 행이고, app_key 를 안 줘도 웹이 고르는 값으로 채운다.
    added = {}
    for kind in ("mcad", "dyna", "dyna_result"):
        added[kind] = call("risk_add_source", project_id=pid, kind=kind, ref=SOURCE_REFS[kind])
        assert added[kind]["created"] is True and added[kind]["source"]["kind"] == kind
    again = call("risk_add_source", project_id=pid, kind="mcad", ref=SOURCE_REFS["mcad"])
    assert again["created"] is False and again["source"]["id"] == added["mcad"]["source"]["id"]
    assert added["mcad"]["source"]["app_key"] == "heax-step_forge"
    assert len(routes._project_sources(pid)) == 3
    # 같은 kind 의 다른 소스는 받지 않는다 — 캡처는 kind 마다 첫 행만 쓰고 소스를 지울 길이 없다.
    taken = call("risk_add_source", project_id=pid, kind="mcad", ref={"stepforge_project_id": "another"})
    assert taken["error"] == "source_kind_taken" and taken["detail"]["existing"][0]["id"] == added["mcad"]["source"]["id"]
    # 캡처가 읽지 못할 ref 는 행을 만들기 전에 거절한다.
    assert call("risk_add_source", project_id=pid, kind="mcad", ref={})["error"] == "E100"
    assert len(routes._project_sources(pid)) == 3

    out = call("risk_next_step", project_id=pid)
    assert out["where"] == "capture" and first_next(out) == {
        "tool": "risk_capture_snapshot", "args": {"project_id": pid}, "write": True, "why": first_next(out)["why"]}

    # 3. 캡처 — 실제 어댑터가 가짜 소스 앱을 읽는다. 같은 내용을 다시 캡처하면 같은 스냅샷이다.
    first = call("risk_capture_snapshot", project_id=pid, label="DV1")
    assert first["blocked"] is False and first["reused"] is False
    out = call("risk_next_step", project_id=pid)
    assert out["where"] == "revision"
    assert {n["tool"] for n in out["next"]} >= {"risk_capture_snapshot", "risk_open_target"}

    apps.revise()
    second = call("risk_capture_snapshot", project_id=pid, label="DV2")
    repeat = call("risk_capture_snapshot", project_id=pid, label="DV2 다시")
    assert repeat["snapshot_id"] == second["snapshot_id"] and repeat["reused"] is True

    # 4. 변경 비교 — same-as 가 남은 것이 없으면 바로 비교다. 같은 쌍은 같은 비교다.
    out = call("risk_next_step", project_id=pid)
    assert out["where"] == "diff" and first_next(out)["tool"] == "risk_create_diff"
    assert first_next(out)["args"] == {"base_snapshot_id": first["snapshot_id"],
                                       "target_snapshot_id": second["snapshot_id"]}
    diff = call("risk_create_diff", **first_next(out)["args"])
    assert diff["created"] is True and diff["counts"]
    assert call("risk_create_diff", **first_next(out)["args"]) == {**diff, "created": False}

    # 5. 심사 대상 — 동의 없이는 열지 않는다. 러너 자격이 없으면 명단을 못 받고, 그 사실과 고칠 곳을 말한다.
    out = call("risk_next_step", project_id=pid)
    assert out["where"] == "target" and first_next(out)["args"] == {
        "kind": "diff", "ref_id": diff["diff_id"], "consent": True}
    assert call("risk_open_target", kind="diff", ref_id=diff["diff_id"])["error"] == "E100"
    opened = call("risk_open_target", kind="diff", ref_id=diff["diff_id"], consent=True)
    target_key = opened["target_key"]
    assert opened["created"] is True and opened["roster_size"] == 0 and opened["roster_source"] == "unavailable"
    out = call("risk_next_step", project_id=pid)
    assert out["where"] == "roster"
    blocked = {b["code"]: b for b in out["blocked"]}
    assert "#/settings" in blocked["roster_empty"]["fix"] and "포털에서 발급해 등록" in blocked["roster_empty"]["fix"]

    # 6. 웹에서 PAT 을 등록했다(명단 조회는 되지만 패널을 감쌀 수명은 못 된다) — 같은 호출이 그 자리에서 명단을 받는다.
    register_pat(box, OWNER, 2 * 3600)
    reopened = call("risk_open_target", kind="diff", ref_id=diff["diff_id"], consent=True)
    assert reopened["created"] is False and reopened["target_key"] == target_key
    assert reopened["roster_size"] == 5 and [t["tier"] for t in reopened["tier_plan"]] == ["A", "B", "C"]
    assert call("risk_open_target", kind="diff", ref_id=diff["diff_id"], consent=True)["roster_size"] == 5

    out = call("risk_next_step", project_id=pid)
    assert out["where"] == "job"
    blocked = {b["code"]: b for b in out["blocked"]}
    assert "포털에서 발급해 등록" in blocked["pat_unavailable"]["fix"]
    refused = call("risk_start_job", target_key=target_key, tier="A")
    assert refused["error"] == "pat_unavailable" and "#/settings" in refused["detail"]["fix"]
    assert box.store.query("SELECT id FROM rr_jobs") == []

    # 7. 오래가는 PAT — 잡이 선다. Tier 는 누적이라 첫 잡은 도메인 대표석(A)이고, 길잡이도 그것을 권한다.
    #    같은 대상·같은 Tier 로 다시 부르면 같은 잡이다.
    register_pat(box, OWNER, 30 * 86400)
    out = call("risk_next_step", project_id=pid)
    assert out["where"] == "job" and out["blocked"] == []
    assert first_next(out)["tool"] == "risk_start_job" and first_next(out)["args"] == {
        "target_key": target_key, "tier": "A"}
    job = call("risk_start_job", **first_next(out)["args"])
    assert job["created"] is True and job["credential"] == "owner" and job["panels_planned"] == 1
    assert call("risk_start_job", target_key=target_key, tier="A")["job_id"] == job["job_id"]
    assert box.store.query_one("SELECT COUNT(*) AS n FROM rr_jobs")["n"] == 1
    out = call("risk_next_step", project_id=pid)
    assert out["where"] == "running" and out["facts"]["job"]["id"] == job["job_id"]
    assert out["web"]["target"] == f"/apps/hwax_risk/#/targets/diff%3A{diff['diff_id']}"

    # 8. 잡 조작 — 이미 그 상태면 그대로 돌려준다.
    assert call("risk_job_action", job_id=job["job_id"], action="pause")["state"] == "paused"
    again = call("risk_job_action", job_id=job["job_id"], action="pause")
    assert again["state"] == "paused" and again["changed"] is False
    assert call("risk_next_step", project_id=pid)["where"] == "paused"
    assert call("risk_job_action", job_id=job["job_id"], action="resume")["state"] == "queued"
    assert call("risk_job_action", job_id=job["job_id"], action="cancel")["state"] == "cancelled"
    assert call("risk_job_action", job_id=job["job_id"], action="cancel")["changed"] is False

    # 9. 웹 화면이 읽는 것 — 같은 원장이라 Claude 로 연 대상·잡이 과제 화면에 그대로 있다.
    page = routes.get_project(pid, ident=web_ident(OWNER))
    assert [t["target_key"] for t in page["targets"]] == [target_key]
    assert [j["id"] for j in page["jobs"]] == [job["job_id"]]
    assert [t["target_key"] for t in routes.list_targets(ident=web_ident(OWNER))["targets"]] == [target_key]


# ---------------------------------------------------------------- 남의 과제에는 쓰지 못한다
def test_another_caller_cannot_write_to_my_project(box):
    act_as(box, OWNER)
    write_secrets(box, HWAXRISK_HEAX_SERVICE_PAT="service-pat")
    register_pat(box, OWNER, 30 * 86400)
    apps = FakeSourceApps()
    wire_sources(box, apps)
    pid = call("risk_create_project", code="MINE", name="내 과제", classification="confidential")["id"]
    call("risk_add_source", project_id=pid, kind="mcad", ref=SOURCE_REFS["mcad"])
    s1 = call("risk_capture_snapshot", project_id=pid)["snapshot_id"]
    apps.revise()
    s2 = call("risk_capture_snapshot", project_id=pid)["snapshot_id"]
    diff_id = call("risk_create_diff", base_snapshot_id=s1, target_snapshot_id=s2)["diff_id"]
    target_key = call("risk_open_target", kind="diff", ref_id=diff_id, consent=True)["target_key"]
    job_id = call("risk_start_job", target_key=target_key, tier="A")["job_id"]
    before = {t: box.store.query_one(f"SELECT COUNT(*) AS n FROM {t}")["n"]
              for t in ("rr_projects", "rr_sources", "rr_snapshots", "rr_diffs", "rr_targets", "rr_jobs",
                        "rr_gate_acks", "rr_sameas")}

    act_as(box, OTHER)
    attempts = {
        "risk_next_step": {"project_id": pid},
        "risk_add_source": {"project_id": pid, "kind": "dyna", "ref": SOURCE_REFS["dyna"]},
        "risk_capture_snapshot": {"project_id": pid},
        "risk_ack_gate": {"snapshot_id": s2, "gate": "G3", "reason": "남의 것"},
        "risk_get_sameas": {"base_snapshot_id": s1, "target_snapshot_id": s2},
        "risk_decide_sameas": {"base_snapshot_id": s1, "target_snapshot_id": s2,
                               "decisions": [{"a_stable": "a", "b_stable": "b", "decision": "confirm"}]},
        "risk_create_diff": {"base_snapshot_id": s1, "target_snapshot_id": s2},
        "risk_open_target": {"kind": "diff", "ref_id": diff_id, "consent": True},
        "risk_start_job": {"target_key": target_key, "tier": "A"},
        "risk_job_action": {"job_id": job_id, "action": "cancel"},
    }
    for name, args in attempts.items():
        assert call(name, **args).get("error") == "E404", name
    # 같은 code 로 과제를 만들면 그 사람의 새 과제다 — 내 과제를 돌려주지 않는다.
    theirs = call("risk_create_project", code="MINE", name="같은 코드", classification="internal")
    assert theirs["created"] is True and theirs["id"] != pid
    after = {t: box.store.query_one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in before}
    assert after == {**before, "rr_projects": before["rr_projects"] + 1}
    assert box.store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"] == "queued"
    assert [p["id"] for p in call("risk_next_step")["projects"]] == [theirs["id"]]


# ---------------------------------------------------------------- 게이트웨이 길에 REST 자격이 없는 박스
def test_without_a_rest_credential_the_claude_capture_is_blocked_and_says_where_to_capture(box):
    """위임 신원에는 heax 토큰이 없다 — 서비스 PAT 가 없는 박스에서 mcad 는 MCP 폴백으로 읽혀 G6 이 unit_unknown 으로 막는다.

    웹은 로그인 토큰으로 REST 를 읽어 같은 과제가 막히지 않는다. 길잡이가 캡처 전에 그 사실을 말하고, 캡처 뒤에는
    막힌 까닭과 고칠 곳(웹 과제 화면에서 캡처 · 운영자의 HWAXRISK_HEAX_SERVICE_PAT)을 말한다.
    """
    act_as(box, OWNER)
    apps = FakeSourceApps()
    wire_sources(box, apps)
    pid = call("risk_create_project", code="NOREST", name="REST 자격 없음", classification="internal")["id"]
    call("risk_add_source", project_id=pid, kind="mcad", ref=SOURCE_REFS["mcad"])

    out = call("risk_next_step", project_id=pid)
    assert out["where"] == "capture" and out["facts"]["credentials"]["capture_rest"] is None
    warned = {b["code"]: b for b in out["blocked"]}
    assert "HWAXRISK_HEAX_SERVICE_PAT" in warned["rest_channel_absent"]["fix"]
    assert f"#/projects/{pid}" in warned["rest_channel_absent"]["fix"]

    snap = call("risk_capture_snapshot", project_id=pid)
    assert snap["blocked"] is True
    gates = state_module.load_state(box.store, snap["snapshot_id"])["gates"]
    assert state_module.blocked_reason(gates) == state_module.UNKNOWN_BLOCKING_REASON
    out = call("risk_next_step", project_id=pid)
    assert out["where"] == "capture"
    blocked = {b["code"]: b for b in out["blocked"]}
    assert blocked["gate_blocked"]["reason"] == "unit_unknown"
    assert "HWAXRISK_HEAX_SERVICE_PAT" in blocked["gate_blocked"]["fix"]
    # 차단 게이트는 ack 로 넘기지 못하고, 비차단 게이트(G4 — 경고를 못 읽어 검문 불가)는 사유를 남길 수 있다.
    assert call("risk_ack_gate", snapshot_id=snap["snapshot_id"], gate="G6", reason="넘긴다")["error"] == \
        "gate_blocking"
    acked = call("risk_ack_gate", snapshot_id=snap["snapshot_id"], gate="G4", reason="좌표 경고는 웹에서 확인")
    assert acked["ack_by"] == OWNER and acked["pass"] is None
    call("risk_ack_gate", snapshot_id=snap["snapshot_id"], gate="G4", reason="좌표 경고는 웹에서 확인")
    assert box.store.query_one("SELECT COUNT(*) AS n FROM rr_gate_acks")["n"] == 1
    # 막힌 스냅샷으로는 비교도 대상도 열리지 않는다 — 앱이 원래 막는 그대로다.
    apps.revise()
    second = call("risk_capture_snapshot", project_id=pid)
    refused = call("risk_create_diff", base_snapshot_id=snap["snapshot_id"], target_snapshot_id=second["snapshot_id"])
    assert refused["error"] == "gate_blocked" and refused["detail"]["reason"] == "unit_unknown"


# ---------------------------------------------------------------- 계보 과제 — 새 리비전이 다른 과제에 있을 때
def test_a_successor_project_compares_against_its_predecessors_latest_capture(box):
    """새 리비전이 소스 앱의 다른 프로젝트에 있으면 새 과제를 계보로 잇는다 — 첫 캡처부터 앞 과제의 최신 캡처와 비교한다."""
    act_as(box, OWNER)
    write_secrets(box, HWAXRISK_HEAX_SERVICE_PAT="service-pat")
    apps = FakeSourceApps()
    wire_sources(box, apps)
    old = call("risk_create_project", code="GEN-1", name="1세대", classification="internal")["id"]
    call("risk_add_source", project_id=old, kind="mcad", ref=SOURCE_REFS["mcad"])
    base = call("risk_capture_snapshot", project_id=old)["snapshot_id"]
    new = call("risk_create_project", code="GEN-2", name="2세대", classification="internal",
               predecessor_project_id=old)["id"]
    call("risk_add_source", project_id=new, kind="mcad", ref=SOURCE_REFS["mcad"])
    apps.revise()
    target = call("risk_capture_snapshot", project_id=new)["snapshot_id"]

    out = call("risk_next_step", project_id=new)
    assert out["where"] == "diff" and first_next(out)["args"] == {"base_snapshot_id": base,
                                                                  "target_snapshot_id": target}
    diff = call("risk_create_diff", **first_next(out)["args"])
    summary = routes.diff_part(diff["diff_id"], "diff", owner_sub=OWNER)
    assert summary["pair_kind"] == "same_project_revision"          # 계보 사슬이라 같은 과제의 리비전으로 본다
    # 계보 과제가 남의 것이면 그 스냅샷을 앞에 세우지 않는다 — 비교가 두 스냅샷 모두 호출자 소유를 요구한다.
    act_as(box, OTHER)
    foreign = call("risk_create_project", code="GEN-2", name="남의 계보", classification="internal",
                   predecessor_project_id=old)["id"]
    call("risk_add_source", project_id=foreign, kind="mcad", ref=SOURCE_REFS["mcad"])
    call("risk_capture_snapshot", project_id=foreign)
    assert call("risk_next_step", project_id=foreign)["where"] == "revision"


# ---------------------------------------------------------------- same-as 확정 — 비교가 읽는 원장 칸에 들어간다
def test_sameas_decisions_land_where_the_diff_reads_them(box):
    act_as(box, OWNER)
    write_secrets(box, HWAXRISK_HEAX_SERVICE_PAT="service-pat")
    apps = FakeSourceApps()
    wire_sources(box, apps)
    pid = call("risk_create_project", code="SAMEAS", name="same-as", classification="internal")["id"]
    call("risk_add_source", project_id=pid, kind="mcad", ref=SOURCE_REFS["mcad"])
    s1 = call("risk_capture_snapshot", project_id=pid)["snapshot_id"]
    apps.revise()
    s2 = call("risk_capture_snapshot", project_id=pid)["snapshot_id"]
    review = call("risk_get_sameas", base_snapshot_id=s1, target_snapshot_id=s2)
    assert review["pending_n"] == 0 and isinstance(review["pairs"], list)

    nodes_a = ir_builder.load_ir(box.store, s1)["nodes"]
    nodes_b = ir_builder.load_ir(box.store, s2)["nodes"]
    a_stable, b_stable = sameas.stable_key(nodes_a[0]), sameas.stable_key(nodes_b[0])
    decision = {"a_stable": a_stable, "b_stable": b_stable, "decision": "confirm"}
    out = call("risk_decide_sameas", base_snapshot_id=s1, target_snapshot_id=s2, decisions=[decision])
    assert out["updated"] == 1
    call("risk_decide_sameas", base_snapshot_id=s1, target_snapshot_id=s2, decisions=[decision])
    rows = box.store.query("SELECT scope, pair_key, status FROM rr_sameas")
    assert [dict(r) for r in rows] == [{"scope": "pair", "pair_key": f"{pid}|{pid}", "status": "confirmed"}]
    # 비교가 원장을 읽는 열쇠와 같은 열쇠다 — load_ledger 가 이 결정을 찾는다.
    ledger = sameas.load_ledger(box.store, "pair", f"{pid}|{pid}", OWNER)
    assert ledger
    assert call("risk_decide_sameas", base_snapshot_id=s1, target_snapshot_id=s2,
                decisions=[{**decision, "decision": "merge_key"}])["error"] == "E100"
    assert call("risk_decide_sameas", base_snapshot_id=s1, target_snapshot_id=s2, decisions=[])["error"] == "E100"


# ---------------------------------------------------------------- 캡처는 이벤트 루프를 붙들지 않는다
def test_capture_runs_off_the_event_loop_and_a_second_call_does_not_start_another(box):
    """동기 도구는 이벤트 루프 위에서 돈다(mcp 1.29 func_metadata) — 캡처가 루프를 붙들면 그동안 /api/health 도 멎는다.

    첫 캡처가 소스 앱을 기다리는 동안 같은 과제의 두 번째 캡처는 루프에서 곧바로 `capture_running` 으로 답한다.
    """
    act_as(box, OWNER)
    pid = call("risk_create_project", code="SLOW", name="느린 캡처", classification="internal")["id"]
    started, release = threading.Event(), threading.Event()
    seen: list[str] = []

    def slow_snapshot(project_id, body, ident):
        seen.append(ident.email)
        started.set()
        assert release.wait(10)
        return {"snapshot_id": "s-slow", "blocked": False}

    box.monkeypatch.setattr(routes, "create_snapshot", slow_snapshot)

    async def scenario():
        first = asyncio.create_task(srv.risk_capture_snapshot(project_id=pid))
        assert await asyncio.to_thread(started.wait, 10)
        second = await asyncio.wait_for(srv.risk_capture_snapshot(project_id=pid), timeout=5)
        release.set()
        return await first, second

    first, second = asyncio.run(scenario())
    assert first["snapshot_id"] == "s-slow" and seen == [OWNER]
    assert second["error"] == "capture_running"
    # 끝나면 다시 캡처할 수 있다.
    release.set()
    assert call("risk_capture_snapshot", project_id=pid)["snapshot_id"] == "s-slow"


# ---------------------------------------------------------------- 신원은 /mcp 에 도달한 자격에서 온다(HTTP 경로)
def _jsonrpc(client, payload: dict, headers: dict) -> dict:
    r = client.post("/mcp", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    if r.headers.get("content-type", "").startswith("text/event-stream"):
        msgs = [json.loads(line[5:].strip()) for line in r.text.splitlines() if line.startswith("data:")]
        msg = next(m for m in msgs if "result" in m or "error" in m)
    else:
        msg = r.json()
    assert "error" not in msg, msg
    result = msg["result"]
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and structured:
        return structured.get("result", structured)
    return json.loads(result["content"][0]["text"])


def test_the_identity_that_reached_mcp_owns_what_the_tool_writes(client, box):
    """게이트웨이가 실은 서명 단언이 /mcp 요청 → FastMCP 요청 문맥 → 스레드 → 라우트 신원까지 닿는다."""
    base = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

    def session(extra: dict) -> dict:
        headers = {**base, **extra}
        r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "0"}}},
            headers=headers)
        assert r.status_code == 200
        headers["mcp-session-id"] = r.headers["mcp-session-id"]
        client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers)
        return headers

    def create(headers: dict, code: str) -> dict:
        return _jsonrpc(client, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "risk_create_project",
            "arguments": {"code": code, "name": "HTTP 경로", "classification": "internal"}}}, headers)

    # 게이트웨이가 위임 헤더를 실어 받아 온 단언 — 앱의 실제 발급 경로(/api/auth/sso)로 만든다.
    r = client.post("/api/auth/sso", headers={"X-Heax-Gateway-Secret": SSO_SECRET, "X-Hwax-Delegate-Email": OWNER})
    token = r.json()["access_token"]
    made = create(session({identity.SSO_HEADER: token}), "HTTP-1")
    assert made["created"] is True and made["acting_as"] == {"email": OWNER, "source": "sso", "delegated": True,
                                                            "note": made["acting_as"]["note"]}
    assert box.store.query_one("SELECT owner_sub FROM rr_projects WHERE id = ?", (made["id"],))["owner_sub"] == OWNER
    # 단언이 없으면(서비스 계정 호출) 쓰지 않고, 신원이 없어서라고 말한다.
    assert create(session({}), "HTTP-2")["error"] == "delegation_required"
    # 위조 단언도 마찬가지다 — 서명이 틀리면 익명이다.
    forged = identity.mint_sso_assertion(OWNER, ttl_s=900, secret="not-the-secret", delegated=True)
    assert create(session({identity.SSO_HEADER: forged}), "HTTP-3")["error"] == "delegation_required"
    assert box.store.query_one("SELECT COUNT(*) AS n FROM rr_projects")["n"] == 1
