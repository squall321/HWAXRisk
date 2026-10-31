# ECAD 는 그 사람의 PAT 로만(사용자 결정 10-31, context-notes EC-27) — 찾기 · 붙이기 확인 · 캡처가 박스 읽기 PAT 로 내려가지 않는지, 앱이 내보내는 모든 HTTP 의 자격을 게이트웨이 대역에서 적어 REST · MCP 두 입구로 본다
"""odb-hub 는 사람별 격리가 없고 게이트웨이의 `plat:odbhub` 로만 막힌다 — 박스 읽기 PAT(`HWAXRISK_PORTAL_PAT`)로 내려가면 그 문을
서비스 계정으로 지난다. 그래서 ECAD 는 그 사람의 등록된 포털 PAT 로만 부르고, 없으면(없음 · 폐기 · 풀리지 않음 · 곧 끝남)
찾기 · 붙이기는 409 `ecad_pat_absent`, 캡처는 결측 + 경고 `ecad_pat_absent` 다. mcad · dyna 의 MCP 폴백은 종전대로 박스 PAT 다.

게이트웨이 대역은 httpx 전송 한 곳(소켓 0)이다 — `/tools-map` 과 `/mcp`(JSON-RPC)를 받고 요청마다 (무엇 · 도구 · Authorization)을
적는다. odb-hub 도구는 tests/test_ecad_adapter.py 의 부록 A 꼴 가짜가, StepForge 도구는 tests/test_adapters.py 의 MCP 답이 답한다.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import httpx
import pytest

import app.mcp_server as srv
from app import config, identity, ir_builder, routes, runner
from app.adapters import registry as adapters_registry
from app.adapters.base import Principal
from app.common import now_epoch
from app.errors import AppError
from tests import factories
from tests import test_adapters as recon
from tests.test_ecad_adapter import JOB_STD, ODB, FakeOdbHub

OWNER = "ecad-pat@example.com"
PERSON_PAT = "person-pat-not-real"          # 그 사람이 등록한 포털 PAT 자리(가짜 값)
BOX_PAT = "box-read-pat-not-real"           # 박스 secrets.env 의 HWAXRISK_PORTAL_PAT 자리(가짜 값)
PERSON, BOX = f"Bearer {PERSON_PAT}", f"Bearer {BOX_PAT}"
WEB = identity.Identity(email=OWNER, display_name="ECAD PAT", role="user", organization="qa", anonymous=False,
                        source="bearer")
MCAD_REF = {"stepforge_project_id": recon.SF_PROJECT, "detect_job_id": "01JDET"}


class Gateway:
    """게이트웨이 하나 — `/tools-map` 과 `/mcp`. 받은 요청마다 (무엇, 도구, Authorization)을 `seen` 에 적는다."""

    def __init__(self) -> None:
        self.hub = FakeOdbHub()
        self.mcad = {**recon.MCP_TOOLS_FULL, "heaxstep_forge_list_parts": recon.MCP_TOOLS_FULL["list_parts"]}
        self.seen: list[tuple[str, str | None, str | None]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization")
        if request.method == "GET" and request.url.path.endswith("/tools-map"):
            self.seen.append(("tools-map", None, auth))
            return httpx.Response(200, json={"map": dict(self.hub.tools)})
        if request.method == "POST" and request.url.path.endswith("/mcp"):
            payload = json.loads(request.content.decode("utf-8") or "{}")
            method, rid = payload.get("method"), payload.get("id")
            if method == "initialize":
                self.seen.append(("initialize", None, auth))
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {}},
                                      headers={"mcp-session-id": "sess-ecad-pat"})
            if method == "notifications/initialized":
                return httpx.Response(202)
            name = str((payload.get("params") or {}).get("name") or "")
            args = dict((payload.get("params") or {}).get("arguments") or {})
            self.seen.append(("tools/call", name, auth))
            original = name[len("odbhub_"):] if name.startswith("odbhub_") else name
            if self.hub.tools.get(name) == ODB:
                body = self.hub.answer(original, args)
            elif name in self.mcad:
                body = self.mcad[name]
            else:
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {
                    "isError": True, "content": [{"type": "text", "text": f"unknown tool: {name}"}]}})
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {"structuredContent": body}})
        self.seen.append((f"{request.method} {request.url.path}", None, auth))
        return httpx.Response(404, json={"detail": "not found"})

    def calls_to(self, backend: str) -> list[tuple[str, str | None]]:
        """그 백엔드 도구의 tools/call — (게이트웨이 이름, Authorization)."""
        return [(tool, auth) for what, tool, auth in self.seen if what == "tools/call" and self.hub.tools.get(tool) == backend]


@dataclass
class Box:
    store: object
    gw: Gateway


@pytest.fixture
def box(risk_store, monkeypatch) -> Box:
    gw = Gateway()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: gw.handle(request))

    def _no_async(*_args, **_kwargs):
        raise AssertionError("이 시험의 경로는 비동기 HTTP 를 쓰지 않는다")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _no_async)
    # 박스 읽기 PAT 는 늘 있다 — ECAD 가 그것으로 내려가지 않는지가 요지다.
    monkeypatch.setattr(config, "load_secrets", lambda *_a, **_k: {"HWAXRISK_PORTAL_PAT": BOX_PAT})
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    return Box(store=risk_store, gw=gw)


def _register(store, state: str = "valid") -> None:
    """그 사람의 포털 PAT 행 — valid · expiring(남은 수명이 캡처 여유 CREDENTIAL_MARGIN_S) · revoked · undecryptable · none."""
    if state == "none":
        store.delete_credential(OWNER)
        return
    blob = "garbage" if state == "undecryptable" else identity.encrypt_pat(PERSON_PAT).decode("ascii")
    life = runner.CREDENTIAL_MARGIN_S if state == "expiring" else 30 * 86400
    store.upsert_credential(OWNER, blob, "sub-ecad-pat", OWNER, "[]", now_epoch() + life)
    if state == "revoked":
        store.execute("UPDATE _user_credentials SET revoked_at = ? WHERE owner_sub = ?", (now_epoch(), OWNER))


def _project(code: str) -> str:
    return routes.create_project(routes.ProjectBody(code=code, name="ECAD 자격", stage="DV1", classification="internal"),
                                 ident=WEB)["id"]


def _attached(box: Box, code: str, *, mcad: bool = False) -> str:
    """보드를 붙인 과제 — 붙일 때는 그 사람의 PAT 가 있다(붙이기 확인도 그 PAT 로만 한다). mcad 카드는 원하면 함께 붙인다."""
    _register(box.store)
    project_id = _project(code)
    routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id=JOB_STD), ident=WEB)
    if mcad:
        routes.add_source(project_id, routes.SourceBody(kind="mcad", app_key=recon.APP_KEY, ref=MCAD_REF), ident=WEB)
    return project_id


def _call(tool: str, /, **kwargs) -> dict:
    out = getattr(srv, tool)(**kwargs)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def _ecad_card(project_id: str) -> dict | None:
    return next((s for s in routes._project_sources(project_id) if s["kind"] == "ecad"), None)


# ---------------------------------------------------------------- 찾기 · 붙이기 — 그 사람의 PAT 가 없으면 아무것도 보내지 않는다
@pytest.mark.parametrize("state", ["none", "expiring", "revoked", "undecryptable"])
@pytest.mark.parametrize("entrance", ["rest_search", "rest_attach", "mcp_search", "mcp_attach"])
def test_search_and_attach_refuse_with_ecad_pat_absent_before_any_request(box, monkeypatch, state, entrance):
    """박스 읽기 PAT 가 있어도 그 사람의 PAT 가 쓸 수 없으면 찾기 · 붙이기는 409 ecad_pat_absent 이고 게이트웨이에 아무것도
    보내지 않는다(도구 지도도) — 카드도 적히지 않는다."""
    project_id = _project(f"PAT-{entrance}-{state}")
    _register(box.store, state)
    if entrance.startswith("mcp"):
        factories.act_as_delegate(monkeypatch, OWNER)
    box.gw.seen.clear()
    if entrance == "rest_search":
        with pytest.raises(AppError) as err:
            routes.get_ecad_boards(q="SM-X100", ident=WEB)
        got = (err.value.code, err.value.http_status, err.value.detail)
    elif entrance == "rest_attach":
        with pytest.raises(AppError) as err:
            routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id=JOB_STD), ident=WEB)
        got = (err.value.code, err.value.http_status, err.value.detail)
    elif entrance == "mcp_search":
        out = _call("risk_find_ecad_boards", query="SM-X100")
        got = (out["error"], 409, out["detail"])
    else:
        out = _call("risk_set_ecad_board", project_id=project_id, odb_job_id=JOB_STD)
        got = (out["error"], 409, out["detail"])
    assert got == ("ecad_pat_absent", 409, {"app_key": ODB, "fix": "portal_pat"})
    assert box.gw.seen == []
    assert _ecad_card(project_id) is None


@pytest.mark.parametrize("entrance", ["rest", "mcp"])
def test_with_the_persons_pat_every_ecad_request_carries_it_and_never_the_box_pat(box, monkeypatch, entrance):
    """그 사람의 PAT 가 있으면 찾기 · 붙이기 · 캡처의 모든 요청(도구 지도 · 세션 · odb-hub 도구)이 그 PAT 를 싣는다 — 박스 PAT 는
    한 번도 나가지 않는다. 캡처는 보드를 싣고 답의 MCP 자격은 user 다."""
    _register(box.store)
    project_id = _project(f"PAT-OK-{entrance}")
    box.gw.seen.clear()
    if entrance == "rest":
        found = routes.get_ecad_boards(q="SM-X100", ident=WEB)
        routes.put_ecad_board(project_id, routes.EcadBoardBody(odb_job_id=JOB_STD), ident=WEB)
        out = routes.create_snapshot(project_id, routes.SnapshotBody(label="DV1"), ident=WEB)
    else:
        factories.act_as_delegate(monkeypatch, OWNER)
        found = _call("risk_find_ecad_boards", query="SM-X100")
        assert _call("risk_set_ecad_board", project_id=project_id, odb_job_id=JOB_STD)["ok"] is True
        out = _call("risk_capture_snapshot", project_id=project_id, label="DV1")
    assert JOB_STD in [c["job_id"] for c in found["candidates"]]
    assert out["credentials"]["mcp"] == "user", out.get("credentials")
    ir = ir_builder.load_ir(box.store, out["snapshot_id"])
    assert ir["missing"]["ecad_absent"] is False
    assert len([n for n in ir["nodes"] if n["domain"] == "ecad" and n["kind"] == "component"]) == 748
    odb = box.gw.calls_to(ODB)
    assert odb and {auth for _tool, auth in odb} == {PERSON}
    assert {tool for tool, _auth in odb} >= {"find_job", "get_board_layers", "odbhub_list_parts"}
    assert [s for s in box.gw.seen if s[2] == BOX] == []
    assert {auth for what, _tool, auth in box.gw.seen if what in ("tools-map", "initialize")} == {PERSON}


# ---------------------------------------------------------------- 캡처 — 그 사람의 PAT 가 없으면 보드를 읽지 않는다
@pytest.mark.parametrize("entrance", ["rest", "mcp"])
def test_a_board_only_capture_without_the_persons_pat_sends_nothing_and_freezes_nothing(box, monkeypatch, entrance):
    """보드만 붙은 과제를 그 사람의 PAT 없이 캡처하면 게이트웨이에 아무것도 보내지 않는다 — 박스 PAT 로 도구 지도를 받으러 가지도
    않는다. 읽은 카드가 ECAD 하나뿐이라 스냅샷을 만들지 않고 409 source_unreachable(reason ecad_pat_absent)이며, 잡 · 카드에 까닭이
    남는다(EC-16 · EC-22 의 꼴)."""
    project_id = _attached(box, f"PAT-ONLY-{entrance}")
    _register(box.store, "none")
    box.gw.seen.clear()
    if entrance == "rest":
        with pytest.raises(AppError) as err:
            routes.create_snapshot(project_id, routes.SnapshotBody(label="DV1"), ident=WEB)
        got = (err.value.code, err.value.http_status, err.value.detail)
    else:
        factories.act_as_delegate(monkeypatch, OWNER)
        out = _call("risk_capture_snapshot", project_id=project_id, label="DV1")
        got = (out["error"], 409, out["detail"])
    assert got == ("source_unreachable", 409, {"kind": "ecad", "reason": "ecad_pat_absent"})
    assert box.gw.seen == []
    job = box.store.query_one("SELECT state, snapshot_id, error_json FROM rr_snapshot_jobs WHERE project_id = ?"
                              " ORDER BY created_at DESC, rowid DESC LIMIT 1", (project_id,))
    assert (job["state"], job["snapshot_id"], json.loads(job["error_json"])["reason"]) == ("failed", None, "ecad_pat_absent")
    card = _ecad_card(project_id)
    assert card["status"] == "unreachable" and card["probe"]["detail"].startswith("capture_failed ecad_pat_absent — ")


def test_a_capture_with_mcad_keeps_the_box_pat_for_mcad_and_leaves_the_board_unread(box):
    """mcad 와 함께면 mcad 의 MCP 폴백은 종전대로 박스 PAT 다 — 보드는 읽지 않고(odb-hub 호출 0) 결측 + 경고 ecad_pat_absent
    (WARNING)이며 capture_failed 가 아니다(EC-16). 박스 PAT 로 나간 도구 호출은 전부 StepForge 의 것이다."""
    project_id = _attached(box, "PAT-MIXED", mcad=True)
    _register(box.store, "none")
    box.gw.seen.clear()
    out = routes.create_snapshot(project_id, routes.SnapshotBody(label="DV1"), ident=WEB)
    assert out["credentials"]["mcp"] == "service"
    ir = ir_builder.load_ir(box.store, out["snapshot_id"])
    assert (ir["missing"]["ecad_absent"], ir["missing"]["ecad_capture_failed"]) == (True, False)
    assert [n for n in ir["nodes"] if n["domain"] == "ecad"] == [] and {n["domain"] for n in ir["nodes"]} == {"mcad"}
    warning = next(w for w in ir["warnings"] if w.get("source_kind") == "ecad")
    assert (warning["code"], warning["severity"]) == ("ecad_pat_absent", "WARNING")
    assert box.gw.calls_to(ODB) == []
    mcad_calls = box.gw.calls_to(recon.APP_KEY)
    assert mcad_calls and {auth for _tool, auth in mcad_calls} == {BOX}
    # 박스 PAT 로 나간 도구 호출은 StepForge 의 것뿐이다(캡처 도구 + 버전 조회 system_status).
    boxed = {tool for what, tool, auth in box.gw.seen if what == "tools/call" and auth == BOX}
    assert boxed <= set(box.gw.mcad) | {"heaxstep_forge_system_status"}, boxed


def test_the_adapter_reads_the_board_only_on_the_persons_channel():
    """어댑터 문 — 채널이 살아 있어도 그 채널의 자격이 그 사람의 PAT(user)가 아니면 부르지 않는다(service · 모름)."""
    for credential in ("service", None, "user"):
        hub = FakeOdbHub()
        captured = adapters_registry.capture_all(
            sources=[{"kind": "ecad", "app_key": ODB, "ref": {"odb_job_id": JOB_STD}}],
            principal=Principal(owner_sub=OWNER, portal_pat="some-pat", mcp_credential=credential),
            mcp_client=hub.mcp(), tool_names=tuple(sorted(hub.tools)), tool_map=hub.tools)
        result = next(r for r in captured["results"] if r["source"]["kind"] == "ecad")
        if credential == "user":
            assert result["missing"] == {"ecad_absent": False} and hub.calls
            continue
        assert hub.calls == [] and captured["calls"] == []
        assert result["missing"] == {"ecad_absent": True} and result["nodes"] == []
        assert (result["warnings"][0]["code"], result["warnings"][0]["severity"]) == ("ecad_pat_absent", "WARNING")


def test_without_the_box_fallback_no_channel_is_built_and_nothing_is_sent(box):
    """`box_pat_fallback=False` 면 그 사람의 PAT 가 없을 때 MCP 채널도 도구 지도도 없다(요청 0). 기본값은 종전대로 박스 PAT 다."""
    secrets = {"HWAXRISK_PORTAL_PAT": BOX_PAT}
    closed = adapters_registry.clients_from_settings(config.settings, secrets, portal_pat=None, box_pat_fallback=False)
    assert (closed["mcp"], closed["portal_pat"], closed["tool_map"]) == (None, None, {})
    assert box.gw.seen == []
    default = adapters_registry.clients_from_settings(config.settings, secrets, portal_pat=None)
    assert default["portal_pat"] == BOX_PAT and default["mcp"] is not None
    assert box.gw.seen == [("tools-map", None, BOX)]
    for channel in (closed["rest"], default["mcp"], default["rest"]):
        channel.close()


def test_the_guide_says_the_board_needs_the_persons_pat(box, monkeypatch):
    """길잡이(risk_next_step)는 보드가 붙은 과제에 그 사람의 PAT 가 없으면 보드가 빈 채 캡처된다고 말한다(dyna 와 같은 자리)."""
    project_id = _attached(box, "PAT-GUIDE")
    _register(box.store, "none")
    factories.act_as_delegate(monkeypatch, OWNER)
    notes = _call("risk_next_step", project_id=project_id)["notes"]
    assert [n for n in notes if n.startswith("ECAD 보드는 본인 PAT 로만 읽는다") and "ecad_pat_absent" in n]
    _register(box.store)
    notes = _call("risk_next_step", project_id=project_id)["notes"]
    assert not [n for n in notes if n.startswith("ECAD 보드는")]
