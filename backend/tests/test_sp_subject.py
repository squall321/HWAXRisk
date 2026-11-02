# 과제 주제(SP 과제 key · 차수) 시험 — 차수 정규화가 에이전트 서버와 같은 규칙인지 형제 리포의 원문에 대고 견준다(과제 인사이트 그래프 M2b)
"""HWAXPortal docs/project-insight-graph contracts §9 · PLAN §4.6.

  · 차수는 NFKC · 유니코드 White_Space 빼기 · 소문자만 하고 개발 단계 코드 열한 개에 글자 그대로 있을 때만이다 — 에이전트 서버
    `delib_subject.norm_round` 와 같은 규칙이어야 포털 과제 보기의 (과제, 차수) 칸에서 두 원천이 만난다. 형제 리포의 원문(리포 루트의
    `../HWAXAgentServer/delib_subject.py`)에서 STAGES · _SPACE_RE · norm_round 를 떼어 그 자리에서 돌려 견준다(없으면 건너뛴다).
  · SP 과제 key 는 앱이 그 사람의 포털 PAT 로 스스로 부른 풀이(heaxstep_forge_find_plm_task)의 결과 행 가운데 key 가 글자 그대로 같은 살아
    있는 행이 꼭 하나일 때만 적는다. 풀이의 가짜는 **실제 StepForge 응답**이다(tests/fixtures/subject/find_plm_task.json — 에이전트 서버
    시험의 고정본을 옮긴 것, 형제 리포에 있으면 같은지 본다). 게이트웨이 대역은 httpx 전송 한 곳(소켓 0)이고 FastMCP 가 내는 글 꼴로 답한다.

  실행:  .venv/bin/python -m pytest tests/test_sp_subject.py
"""
from __future__ import annotations

import ast
import asyncio
import copy
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

import app.mcp_server as srv
from app import config, identity, routes, sp_subject
from app.common import now_epoch
from app.errors import AppError
from tests import factories
from tests.conftest import FIXTURES_DIR, REPO_ROOT
from tests.rr.test_member_reads import _forge
from tests.rr.test_review1_stranger import OTHER as LEDGER_STRANGER
from tests.rr.test_review1_stranger import OWNER as LEDGER_OWNER
from tests.rr.test_review1_stranger import ledger, template  # noqa: F401 — 등록부가 선 원장(검토 → 쟁점 → 종합) 픽스처 둘

AGENT_SOURCE = REPO_ROOT.parent / "HWAXAgentServer" / "delib_subject.py"
AGENT_NAMES = {"STAGES", "_SPACE_RE", "norm_round"}


def _agent() -> dict:
    """형제 리포 원문의 STAGES · _SPACE_RE · norm_round 만 떼어 돌린 이름표 — 모듈을 import 하지 않는다(그 모듈이 쓰는 다른 이름이 이 venv 에
    없어도 견줄 수 있게). 원문이 없으면 건너뛴다."""
    if not AGENT_SOURCE.is_file():
        pytest.skip(f"형제 리포의 원문이 없다 — {AGENT_SOURCE}")
    tree = ast.parse(AGENT_SOURCE.read_text(encoding="utf-8"), filename=str(AGENT_SOURCE))
    body = [node for node in tree.body
            if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in AGENT_NAMES for t in node.targets))
            or (isinstance(node, ast.FunctionDef) and node.name in AGENT_NAMES)]
    found = {t.id for node in body if isinstance(node, ast.Assign) for t in node.targets if isinstance(t, ast.Name)} | {
        node.name for node in body if isinstance(node, ast.FunctionDef)}
    assert found == AGENT_NAMES, f"에이전트 원문에서 {sorted(AGENT_NAMES - found)} 를 찾지 못했다 — 이름이 바뀌었으면 이 시험을 고친다"
    names: dict = {"re": re, "unicodedata": unicodedata}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(AGENT_SOURCE), "exec"), names)  # noqa: S102 — 형제 리포의 순수 함수 하나
    return names


# 코드로 읽히는 것 · 아닌 것이 섞인 까다로운 입력 — 에이전트 시험의 묶음에 전각 숫자 · 로마 숫자 · 원 숫자(NFKC 가 숫자로 편다) · 공백이 아닌
# 보이지 않는 글자(BOM · 폭 없는 공백 · 이음 · 몽골 모음 구분 · 소프트 하이픈 · 정보 분리)를 더했다.
TRICKY = [
    "dv1", "DV1", " Dv 2 ", "ＤＶ１", "ｐｖｒ", "PRE", "mp", "M P", "pra", "dvr", "pv3", "　dv3　", "dv 1", "dv\u00851",
    "\tdv\n2\r", "pv 1", "Ｍｐ", "ＤＶＲ", "dv①", "ⅾⅴ1", "dv 1", " pre", "pv 2", "dv 1", "ＰＲＡ　",
    "2차", "C2", "c2", "양산", "선행", "DV", "dv", "pre1", "pv4", "dv-1", "dv_1", "dv0", "mp1", "", "  ", "dv1차", "PV 1차",
    "dv1﻿", "﻿pv2", "dv\u001f1", "dv\u001c1", "dv​1", "dv‍1", "dv⁠1", "dv᠎1", "dv­1",
    "D́V1", "PV-1", "pv1.", "ｄｖ－１",
]


def test_the_stages_and_the_space_class_are_the_agents_letter_for_letter():
    """열한 코드(차례까지)와 빼는 공백 글자 묶음(정규식 글 그대로)이 에이전트 서버의 것과 같다."""
    agent = _agent()
    assert sp_subject.STAGES == agent["STAGES"]
    assert sp_subject._SPACE_RE.pattern == agent["_SPACE_RE"].pattern


def test_norm_round_answers_like_the_agent_on_tricky_inputs():
    """같은 입력에 같은 답이다 — 글이 아닌 값도(None · 수 · 바이트 · 목록). 묶음에는 코드로 읽히는 것과 아닌 것이 둘 다 있다."""
    agent = _agent()["norm_round"]
    for raw in [*TRICKY, None, 1, b"dv1", ["dv1"]]:
        assert sp_subject.norm_round(raw) == agent(raw), repr(raw)
    answers = {sp_subject.norm_round(raw) for raw in TRICKY}
    assert None in answers and {"dv1", "dv2", "pvr", "mp", "pra"} <= answers


@pytest.mark.parametrize("raw,want", [
    ("dv1", "dv1"), ("DV1", "dv1"), (" Dv 2 ", "dv2"), ("ＤＶ１", "dv1"), ("ｐｖｒ", "pvr"), ("PRE", "pre"), ("M P", "mp"),
    ("　dv3　", "dv3"), ("dv 1", "dv1"), ("\tdv\n2\r", "dv2"), ("pv 1", "pv1"), ("dv①", "dv1"),
])
def test_norm_round_keeps_only_width_space_and_case_folding(raw, want):
    assert sp_subject.norm_round(raw) == want


@pytest.mark.parametrize("raw", ["2차", "C2", "양산", "선행", "DV", "dv", "pre1", "pv4", "dv-1", "dv_1", "mp1", "", "dv1﻿",
                                 "dv\u001f1", "dv​1", "PV-1"])
def test_anything_else_is_round_unknown(raw):
    """하이픈 · 밑줄을 빼지 않고 '2차' · 'C2' · '양산' · 웹 폼의 'dv' · 'pre1' 을 코드로 읽지 않는다 — 공백이 아닌 글자(BOM · 정보 분리 ·
    폭 없는 공백)도 빼지 않는다(PLAN §4.6)."""
    assert sp_subject.norm_round(raw) is None


def test_the_write_round_is_a_code_or_nothing():
    """쓰기의 round — 비면 stage 를 그대로 두고(None), 코드면 그 코드, 아니면 422 round_invalid(허용값을 detail 에)."""
    assert sp_subject.parse_round(None) is None and sp_subject.parse_round("") is None and sp_subject.parse_round("  ") is None
    assert sp_subject.parse_round(" ＤＶ２ ") == "dv2" and sp_subject.parse_round("MP") == "mp"
    for raw in ("dv", "pre1", "2차", "C2", "unknown", "모름"):
        with pytest.raises(AppError) as err:
            sp_subject.parse_round(raw)
        assert (err.value.code, err.value.http_status, err.value.detail) == (
            "round_invalid", 422, {"allowed": list(sp_subject.STAGES)}), raw


def test_the_find_round_filter_takes_codes_and_unknown_only():
    """찾기의 round — 비면 모든 차수(None), unknown · 모름 은 차수 모름 칸, 코드는 그 코드, 아니면 422(아무것도 안 걸리는 거름을 말없이
    돌려주지 않는다)."""
    assert sp_subject.parse_round_filter(None) is None and sp_subject.parse_round_filter(" ") is None
    assert sp_subject.parse_round_filter("UNKNOWN") == sp_subject.parse_round_filter("모름") == sp_subject.ROUND_UNKNOWN
    assert sp_subject.parse_round_filter("Pv1") == "pv1"
    with pytest.raises(AppError) as err:
        sp_subject.parse_round_filter("C2")
    assert (err.value.code, err.value.http_status) == ("round_invalid", 422)
    assert err.value.detail == {"allowed": [*sp_subject.STAGES, sp_subject.ROUND_UNKNOWN]}


# ================================================================ SP 과제 key — 그 사람의 PAT 로 부른 풀이의 결과 행에서만(쓰기)
FIXTURE_PATH = FIXTURES_DIR / "subject" / "find_plm_task.json"
AGENT_FIXTURE = REPO_ROOT.parent / "HWAXAgentServer" / "tests" / "fixtures" / "subject" / "find_plm_task.json"
FIX = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
KEY = "알파 개발_C2"                  # 운영 허브 꼴 — key 가 과제명이다(과제코드 TC-1001 은 properties.task_code)
OTHER_ROW_KEY = "알파 개발_C2 보강"     # 같은 질의에 부분 일치로 걸리는 다른 행
OWNER = "sp-owner@example.com"
EDITOR = "sp-editor@example.com"
VIEWER = "sp-viewer@example.com"
STRANGER = "sp-stranger@example.com"
PATS = {OWNER: "owner-pat-not-real", EDITOR: "editor-pat-not-real", VIEWER: "viewer-pat-not-real",
        STRANGER: "stranger-pat-not-real"}
BOX_PAT = "box-read-pat-not-real"
META = "heaxstep_forge_get_project_meta"


def _who(email: str, source: str = "bearer") -> identity.Identity:
    return identity.Identity(email=email, display_name="주제", role="user", organization="qa", anonymous=False, source=source)


class Gateway:
    """게이트웨이 하나 — `/mcp`(JSON-RPC)와 `/tools-map`. 도구마다 답(본문 dict · 인자를 받아 본문을 내는 함수 · ('error', 글) · ('text', 글) ·
    예외)을 정해 두고, 받은 요청마다 (무엇, 도구, 인자, Authorization)을 `seen` 에 적는다. 도구 답은 FastMCP 가 dict 를 내는 꼴(들여쓰기 2 JSON
    글 한 덩이)이다. 도구 지도(`tool_map`)는 ECAD 보드 붙이기(find_job)만 읽는다."""

    def __init__(self) -> None:
        self.answers: dict[str, Any] = {}
        self.tool_map: dict[str, str] = {}
        self.seen: list[tuple[str, str | None, dict | None, str | None]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization")
        if request.method == "GET" and request.url.path.endswith("/tools-map") and self.tool_map:
            self.seen.append(("tools-map", None, None, auth))
            return httpx.Response(200, json={"map": dict(self.tool_map)})
        if request.method != "POST" or not request.url.path.endswith("/mcp"):
            self.seen.append((f"{request.method} {request.url.path}", None, None, auth))
            return httpx.Response(404, json={"detail": "not found"})
        payload = json.loads(request.content.decode("utf-8") or "{}")
        method, rid = payload.get("method"), payload.get("id")
        if method == "initialize":
            self.seen.append(("initialize", None, None, auth))
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {}}, headers={"mcp-session-id": "sess-sp"})
        if method == "notifications/initialized":
            return httpx.Response(202)
        name = str((payload.get("params") or {}).get("name") or "")
        args = dict((payload.get("params") or {}).get("arguments") or {})
        self.seen.append(("tools/call", name, args, auth))
        answer = self.answers.get(name, ("error", f"unknown tool: {name}"))
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            answer = answer(args)
        if isinstance(answer, tuple):
            kind, text = answer
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {
                "isError": kind == "error", "content": [{"type": "text", "text": text}]}})
        text = json.dumps(answer, ensure_ascii=False, indent=2)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": {
            "isError": False, "content": [{"type": "text", "text": text}]}})

    def calls(self, tool: str) -> list[tuple[dict | None, str | None]]:
        return [(args, auth) for what, name, args, auth in self.seen if what == "tools/call" and name == tool]


@dataclass
class Box:
    store: Any
    gw: Gateway
    project: str


@pytest.fixture
def box(risk_store, monkeypatch) -> Box:
    """주인의 과제(구성원 — 편집자 · 보기) 하나와 게이트웨이 대역. 박스 읽기 PAT 는 늘 있다 — 풀이가 그것으로 내려가지 않는지가 요지다."""
    gw = Gateway()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: gw.handle(request))

    def _no_async(*_args, **_kwargs):
        raise AssertionError("이 시험의 경로는 비동기 HTTP 를 쓰지 않는다")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _no_async)
    monkeypatch.setattr(config, "load_secrets", lambda *_a, **_k: {"HWAXRISK_PORTAL_PAT": BOX_PAT})
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    for email in (OWNER, EDITOR, VIEWER, STRANGER):
        _register(risk_store, email)
    project = routes.create_project(routes.ProjectBody(code="SP-1", name="주제 과제", stage="DV1", classification="internal"),
                                    ident=_who(OWNER))["id"]
    routes.put_members(project, routes.MembersBody(members=[routes.MemberItem(email=EDITOR, role="editor"),
                                                            routes.MemberItem(email=VIEWER, role="viewer")]), ident=_who(OWNER))
    gw.answers[sp_subject.RESOLVER_CALL] = FIX["exact_and_partial"]["body"]
    return Box(store=risk_store, gw=gw, project=project)


def _register(store, email: str, *, life_s: int = 30 * 86400) -> None:
    store.upsert_credential(email, identity.encrypt_pat(PATS[email]).decode("ascii"), "sub", email, "[]", now_epoch() + life_s)


def _subject(store, project_id: str) -> tuple[str | None, str | None]:
    row = store.query_one("SELECT sp_task, stage FROM rr_projects WHERE id = ?", (project_id,))
    return row["sp_task"], row["stage"]


def _audits(store, project_id: str) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT owner_sub, actor, actor_verified, channel, before_json, after_json FROM rr_audit WHERE action = 'project.sp_subject'"
        " AND project_id = ? ORDER BY at, rowid", (project_id,))]


def _put(project_id: str, who: str, sp_task: str | None, round_: str | None = None, *, source: str = "bearer") -> dict:
    return routes.put_sp_subject(project_id, routes.SpSubjectBody(sp_task=sp_task, round=round_), ident=_who(who, source))


def _refused(call) -> AppError:
    with pytest.raises(AppError) as err:
        call()
    return err.value


def _call(tool: str, /, **kwargs) -> dict:
    out = getattr(srv, tool)(**kwargs)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def test_the_resolver_fixture_is_the_agents_fixture():
    """풀이 가짜는 에이전트 서버 시험과 같은 실제 StepForge 응답이다 — 형제 리포에 있으면 글자까지 같은지 본다(한쪽만 고치지 않게)."""
    if not AGENT_FIXTURE.is_file():
        pytest.skip(f"형제 리포의 고정본이 없다 — {AGENT_FIXTURE}")
    assert FIXTURE_PATH.read_bytes() == AGENT_FIXTURE.read_bytes()
    rows = FIX["exact_and_partial"]["body"]["tasks"]
    assert [r["key"] for r in rows] == [KEY, OTHER_ROW_KEY] and FIX["exact_and_partial"]["body"]["query"] == KEY


def test_one_live_exact_row_writes_the_key_and_the_round_and_audits_once(box):
    """결과 행 가운데 key 가 글자 그대로 같은 살아 있는 행이 꼭 하나면 적는다 — 풀이는 그 사람의 PAT 로 한 번(인자 query · limit 50 · full),
    round 는 코드로 stage 에. 감사 한 줄(앞 · 뒤 · 풀이 지문). 같은 값을 다시 보내면 풀이는 다시 부르되 바뀐 것이 없어 감사가 없다."""
    out = _put(box.project, OWNER, KEY, " ＤＶ２ ")
    assert (out["ok"], out["changed"], out["sp_task"], out["stage"], out["round"]) == (True, True, KEY, "dv2", "dv2")
    assert out["previous"] == {"sp_task": None, "stage": "DV1"}
    assert _subject(box.store, box.project) == (KEY, "dv2")
    assert box.gw.calls(sp_subject.RESOLVER_CALL) == [({"query": KEY, "limit": 50, "full": True}, f"Bearer {PATS[OWNER]}")]
    assert {auth for *_rest, auth in box.gw.seen} == {f"Bearer {PATS[OWNER]}"}       # 박스 PAT 는 한 번도 나가지 않는다
    fingerprint = {"tool": "heaxstep_forge_find_plm_task", "at": out["resolved_by"]["at"],
                   "sha256": sp_subject.fingerprint(FIX["exact_and_partial"]["body"])}
    assert out["resolved_by"] == fingerprint and isinstance(fingerprint["at"], int)
    rows = _audits(box.store, box.project)
    assert [(r["owner_sub"], r["actor"], r["actor_verified"], r["channel"]) for r in rows] == [(OWNER, OWNER, 1, "rest")]
    assert json.loads(rows[0]["before_json"]) == {"sp_task": None, "stage": "DV1"}
    assert json.loads(rows[0]["after_json"]) == {"sp_task": KEY, "stage": "dv2", "resolved_by": fingerprint}

    again = _put(box.project, OWNER, KEY, "dv2")
    assert again["changed"] is False and len(box.gw.calls(sp_subject.RESOLVER_CALL)) == 2
    assert len(_audits(box.store, box.project)) == 1


def _not_confirmed(box: Box, key: str) -> AppError:
    err = _refused(lambda: _put(box.project, OWNER, key, "dv1"))
    assert (err.code, err.http_status) == ("sp_task_not_confirmed", 422), (err.code, err.message)
    assert _subject(box.store, box.project) == (None, "DV1") and _audits(box.store, box.project) == []
    return err


def test_a_key_that_is_not_a_row_key_is_not_written(box):
    """결과 0행(no_match) — 적지 않고 차수도 그대로다(한 요청은 통째로 거절된다). 까닭에 풀이의 까닭(no_match)을 싣는다."""
    box.gw.answers[sp_subject.RESOLVER_CALL] = FIX["no_match"]["body"]
    err = _not_confirmed(box, "없는 과제")
    assert "0행" in err.message and "no_match" in err.message and err.detail["tool"] == sp_subject.RESOLVER_CALL


def test_the_echoed_query_is_never_evidence(box):
    """답의 query 칸이 key 와 같아도(풀이는 질의를 되싣는다) 결과 행에 그 key 가 없으면 확인이 아니다."""
    box.gw.answers[sp_subject.RESOLVER_CALL] = {**FIX["no_match"]["body"], "query": KEY}
    _not_confirmed(box, KEY)


@pytest.mark.parametrize("given,fixture", [("알파 개발", "exact_and_partial"), ("TC-1001", "task_code"), ("알파", "exact_and_partial")])
def test_a_partial_or_task_code_match_is_not_written_and_the_reason_names_no_row_key(box, given, fixture):
    """부분 일치 · 과제코드(properties.task_code) · 별칭으로 걸린 행은 key 가 다르다 — 적지 않는다. 까닭에는 결과 행의 key 가 없다(StepForge
    허가가 없는 사람이 그 까닭을 볼 수 있다)."""
    box.gw.answers[sp_subject.RESOLVER_CALL] = FIX[fixture]["body"]
    err = _not_confirmed(box, given)
    assert KEY not in err.message and OTHER_ROW_KEY not in err.message and KEY not in json.dumps(err.detail, ensure_ascii=False)


def test_an_inactive_exact_row_is_not_written_and_the_merged_key_is_not_named(box):
    """허브에서 비활성인 과제(지워졌거나 합쳐졌다)는 확인이 아니다 — 까닭은 그 행의 gone_reason 이고 합쳐진 곳의 key 는 싣지 않는다."""
    body = copy.deepcopy(FIX["exact_and_partial"]["body"])
    body["tasks"][0].update(active=False, gone_reason="merged", merged_into="알파 개발_C3")
    box.gw.answers[sp_subject.RESOLVER_CALL] = body
    err = _not_confirmed(box, KEY)
    assert "비활성" in err.message and "merged" in err.message and "알파 개발_C3" not in err.message


def test_two_exact_rows_are_not_written(box):
    """같은 key 의 행이 둘이면 고르지 않는다(하나가 비활성이어도 — 에이전트와 같은 규칙)."""
    body = copy.deepcopy(FIX["exact_and_partial"]["body"])
    body["tasks"].append({**copy.deepcopy(body["tasks"][0]), "active": False})
    box.gw.answers[sp_subject.RESOLVER_CALL] = body
    assert "2개" in _not_confirmed(box, KEY).message


@pytest.mark.parametrize("answer,word", [
    (("error", "forbidden: plat:stepforge 허가가 없다"), "오류로 답했다 — forbidden"),
    (("text", "JSON 이 아닌 글"), "객체로 읽지 못했다"),
    (httpx.ConnectError("게이트웨이가 꺼져 있다"), "부르지 못했다(transport_error)"),
])
def test_a_tool_error_an_unreadable_answer_or_an_unreachable_gateway_is_not_written(box, answer, word):
    box.gw.answers[sp_subject.RESOLVER_CALL] = answer
    assert word in _not_confirmed(box, KEY).message


def test_a_resolver_past_its_deadline_is_not_written(box, monkeypatch):
    """기한(RESOLVE_TIMEOUT_S)을 넘기면 확인하지 못한 것이다 — 기한이 이미 지났으면 게이트웨이에 보내지도 않는다."""
    monkeypatch.setattr(sp_subject, "RESOLVE_TIMEOUT_S", 0.0)
    assert "안에 답하지 않았다" in _not_confirmed(box, KEY).message
    assert box.gw.seen == []


@pytest.mark.parametrize("state", ["none", "expiring", "revoked"])
def test_without_the_persons_pat_nothing_is_sent_and_nothing_is_written(box, state):
    """그 사람의 PAT 가 없거나 곧 끝나거나 폐기됐으면 409 sp_pat_absent 이고 게이트웨이에 아무것도 보내지 않는다(박스 PAT 로 내려가지 않는다)."""
    if state == "none":
        box.store.delete_credential(OWNER)
    elif state == "expiring":
        from app import runner  # noqa: PLC0415

        _register(box.store, OWNER, life_s=runner.CREDENTIAL_MARGIN_S)
    else:
        box.store.execute("UPDATE _user_credentials SET revoked_at = ? WHERE owner_sub = ?", (now_epoch(), OWNER))
    err = _refused(lambda: _put(box.project, OWNER, KEY, "dv1"))
    assert (err.code, err.http_status, err.detail["fix"]) == ("sp_pat_absent", 409, "portal_pat")
    assert box.gw.seen == [] and _subject(box.store, box.project) == (None, "DV1")


def test_null_detaches_without_the_resolver_and_a_round_code_writes_the_stage(box):
    """sp_task=null 은 풀이 없이 뗀다(PAT 가 없어도) — 감사 한 줄(resolved_by null). round 만 주면 stage 에 코드로, 빈 round 는 stage 그대로."""
    _put(box.project, OWNER, KEY)
    box.gw.seen.clear()
    box.store.delete_credential(OWNER)
    out = _put(box.project, OWNER, None, "")
    assert (out["changed"], out["sp_task"], out["stage"], out["resolved_by"]) == (True, None, "DV1", None)
    assert box.gw.seen == [] and _subject(box.store, box.project) == (None, "DV1")
    staged = _put(box.project, OWNER, None, "PVR")
    assert (staged["stage"], staged["round"], staged["changed"]) == ("pvr", "pvr", True)
    after = [json.loads(r["after_json"]) for r in _audits(box.store, box.project)]
    assert after[1:] == [{"sp_task": None, "stage": "DV1", "resolved_by": None}, {"sp_task": None, "stage": "pvr", "resolved_by": None}]


@pytest.mark.parametrize("round_", ["dv", "pre1", "2차", "C2", "양산", "unknown"])
def test_a_round_that_is_not_a_code_is_422_before_the_resolver(box, round_):
    err = _refused(lambda: _put(box.project, OWNER, KEY, round_))
    assert (err.code, err.http_status) == ("round_invalid", 422)
    assert box.gw.seen == [] and _subject(box.store, box.project) == (None, "DV1")


def test_an_empty_key_is_not_a_detach(box):
    """빈 글 key 는 떼기가 아니다 — 422(떼려면 null). 원장 그대로."""
    _put(box.project, OWNER, KEY)
    for given in ("", "   "):
        err = _refused(lambda given=given: _put(box.project, OWNER, given))
        assert (err.code, err.http_status) == ("E100", 422)
    assert _subject(box.store, box.project) == (KEY, "DV1")


def test_only_owners_and_editors_write_and_strangers_see_a_missing_project(box):
    """편집자는 제 PAT 로 풀어 적는다(감사 행위자는 편집자). 보기는 403 role_insufficient, 남은 없는 과제와 같은 404 — 원장 그대로이고
    게이트웨이에 아무것도 보내지 않는다."""
    viewer = _refused(lambda: _put(box.project, VIEWER, KEY))
    assert (viewer.code, viewer.http_status) == ("role_insufficient", 403)
    stranger = _refused(lambda: _put(box.project, STRANGER, KEY))
    missing = _refused(lambda: _put("no-such-project", STRANGER, KEY))
    assert (stranger.code, stranger.http_status) == (missing.code, missing.http_status) == ("E404", 404)
    assert stranger.message.replace(box.project, "<p>") == missing.message.replace("no-such-project", "<p>")
    assert box.gw.seen == [] and _subject(box.store, box.project) == (None, "DV1")
    out = _put(box.project, EDITOR, KEY, "dv3", source="cookie")
    assert out["changed"] is True and _subject(box.store, box.project) == (KEY, "dv3")
    assert box.gw.calls(sp_subject.RESOLVER_CALL)[0][1] == f"Bearer {PATS[EDITOR]}"
    assert [(r["owner_sub"], r["actor"], r["channel"]) for r in _audits(box.store, box.project)] == [(EDITOR, EDITOR, "web")]


def test_a_purged_project_is_not_written(box):
    box.store.execute("UPDATE rr_projects SET status = 'purged' WHERE id = ?", (box.project,))
    err = _refused(lambda: _put(box.project, OWNER, None, "dv1"))
    assert (err.code, err.http_status) == ("project_purged", 409)


def test_the_general_patch_does_not_take_the_key(box):
    """일반 PATCH 칸에는 sp_task 가 없다 — 넣으면 사람 글이 key 로 들어간다(받지 않는 칸은 버려지고 바꿀 것이 없어 422)."""
    assert "sp_task" not in routes.PROJECT_PATCH_COLS and "sp_task" not in routes.ProjectPatchBody.model_fields
    err = _refused(lambda: routes.patch_project(box.project, routes.ProjectPatchBody.model_validate({"sp_task": KEY}),
                                                ident=_who(OWNER)))
    assert (err.code, err.http_status) == ("E100", 422) and _subject(box.store, box.project) == (None, "DV1")


@pytest.mark.parametrize("stage,want", [("dv", None), ("pre1", None), ("DV1", "dv1"), ("2차", None), (None, None), ("Ｍｐ", "mp")])
def test_project_creation_keeps_free_text_stage_and_reads_a_round_only_for_codes(box, stage, want):
    """과제 만들기는 stage 를 종전대로 글로 받는다(웹 폼의 'dv' · 'pre1' 이 422 가 되지 않는다 — PG-33). 꼴에 안 맞는 stage 는 차수 모름이다."""
    made = routes.create_project(routes.ProjectBody(code=f"FREE-{stage}", name="자유 단계", stage=stage, classification="internal"),
                                 ident=_who(OWNER))
    assert made["stage"] == stage
    got = routes.get_sp_subject(made["id"], ident=_who(OWNER))
    assert (got["sp_task"], got["stage"], got["round"]) == (None, stage, want)


def test_the_read_gives_the_current_values_and_a_hint_from_the_attached_mcad_source(box):
    """읽기 — 지금 값과 후보 힌트(붙은 기구 CAD 원천의 get_project_meta.plm_task — 부른 사람의 PAT 로, 확인이 아니다). 원천이 없으면 힌트 없이
    까닭이고, 그 사람의 PAT 가 없으면 아무것도 보내지 않고 까닭이다(읽기는 막지 않는다). 구성원(보기)도 읽고 남은 없는 과제와 같은 404 다."""
    first = routes.get_sp_subject(box.project, ident=_who(VIEWER))
    assert (first["sp_task"], first["stage"], first["round"], first["hint"]) == (None, "DV1", "dv1", None)
    assert "원천이 붙지 않아" in first["hint_note"] and box.gw.seen == []
    routes.add_source(box.project, routes.SourceBody(kind="mcad", app_key="heax-step_forge",
                                                     ref={"stepforge_project_id": "019a2b3c4d5e6f7a8b9c0d1"}), ident=_who(OWNER))
    box.gw.seen.clear()
    meta_row = FIX["exact_and_partial"]["body"]["tasks"][0]
    box.gw.answers[META] = {"id": "019a2b3c4d5e6f7a8b9c0d1", "code": "TC-1001", "plm_task": {**meta_row, "resolved_via": "task_code"},
                            "plm_task_why": None}
    got = routes.get_sp_subject(box.project, ident=_who(VIEWER))
    assert got["hint"] == {"sp_task": KEY, "label": KEY, "active": True, "why": None,
                           "stepforge_project_id": "019a2b3c4d5e6f7a8b9c0d1", "tool": META} and got["hint_note"] is None
    assert box.gw.calls(META) == [({"project_id": "019a2b3c4d5e6f7a8b9c0d1"}, f"Bearer {PATS[VIEWER]}")]
    assert got["sp_task"] is None                                  # 힌트는 적지 않는다
    box.gw.answers[META] = {"plm_task": None, "plm_task_why": {"cause": "ambiguous", "message": "둘 이상"}}
    assert routes.get_sp_subject(box.project, ident=_who(OWNER))["hint"]["why"] == "ambiguous"
    box.store.delete_credential(VIEWER)
    box.gw.seen.clear()
    no_pat = routes.get_sp_subject(box.project, ident=_who(VIEWER))
    assert no_pat["hint"] is None and "포털 PAT" in no_pat["hint_note"] and box.gw.seen == []
    stranger = _refused(lambda: routes.get_sp_subject(box.project, ident=_who(STRANGER)))
    assert (stranger.code, stranger.http_status) == ("E404", 404)


def test_claude_sets_the_subject_through_the_same_route_as_a_delegate_only(box, monkeypatch):
    """MCP risk_set_project_subject — 웹과 같은 함수를 게이트웨이 위임으로 확인된 신원으로 지난다(감사 입구 mcp · 행위자 미검증). 위임이 없으면
    delegation_required 이고 게이트웨이에 아무것도 보내지 않는다."""
    assert _call("risk_set_project_subject", project_id=box.project, sp_task=KEY)["error"] == "delegation_required"
    assert box.gw.seen == []
    factories.act_as_delegate(monkeypatch, OWNER)
    out = _call("risk_set_project_subject", project_id=box.project, sp_task=KEY, round="dv1")
    assert (out["ok"], out["sp_task"], out["round"]) == (True, KEY, "dv1") and out["web"]["project"].endswith(box.project)
    assert [(r["actor"], r["actor_verified"], r["channel"]) for r in _audits(box.store, box.project)] == [(OWNER, 0, "mcp")]
    refused = _call("risk_set_project_subject", project_id=box.project, sp_task="알파 개발")
    assert refused["error"] == "sp_task_not_confirmed" and KEY not in refused["message"]
    cleared = _call("risk_set_project_subject", project_id=box.project, sp_task=None)
    assert (cleared["sp_task"], cleared["changed"]) == (None, True)


# ================================================================ 주제로 과제 찾기(MCP risk_find_projects_by_subject — 읽기)
OTHER_KEY = "베타 개발_C1"
MCAD_ID = "019A2B3C4D5E6F7A8B9C0D1"          # StepForge project_id(원천에는 사람이 준 꼴 그대로 — 대문자)
REPORT_ID = "01HZX3K5Q9V8N7M6P5R4S3T2W1"      # DynaForge 리포트 ULID
BOARD = "0123456789abcdef"                    # ODB 허브 job_id


def _any_key(args: dict) -> dict:
    """풀이 답 — 실제 응답 꼴(고정본의 첫 행)에 key · label 만 질의로 바꾼 한 행. 여러 과제에 서로 다른 key 를 다는 시험이 쓴다."""
    body = copy.deepcopy(FIX["exact_and_partial"]["body"])
    row = {**body["tasks"][0], "key": args["query"], "label": args["query"]}
    return {**body, "query": args["query"], "count": 1, "tasks": [row]}


def _made(owner: str, code: str, stage: str | None, key: str | None = None) -> str:
    project_id = routes.create_project(routes.ProjectBody(code=code, name=f"과제 {code}", stage=stage, classification="internal"),
                                       ident=_who(owner))["id"]
    if key is not None:
        _put(project_id, owner, key)
    return project_id


def _find(monkeypatch, who: str | None, **kwargs) -> dict:
    """그 사람(None 이면 위임 신원 없음 — service)으로 MCP 찾기를 부른다."""
    if who is None:
        monkeypatch.setattr(srv, "_request", lambda: None)
    else:
        factories.act_as_delegate(monkeypatch, who)
    return _call("risk_find_projects_by_subject", **kwargs)


def _ids(out: dict) -> list[str]:
    return [p["project_id"] for p in out["projects"]]


@pytest.fixture
def many(box) -> dict:
    """주인의 과제 넷(같은 key 둘 — 차수 코드 · 꼴 아닌 stage, key 없는 과제, 다른 key)과 남의 비공개 과제(같은 key) 하나."""
    box.gw.answers[sp_subject.RESOLVER_CALL] = _any_key
    ids = {"coded": _made(OWNER, "F-1", "DV1", KEY), "free": _made(OWNER, "F-2", "dv", KEY), "bare": _made(OWNER, "F-3", "pv1"),
           "other": _made(OWNER, "F-4", "mp", OTHER_KEY), "theirs": _made(STRANGER, "S-1", "DV1", KEY)}
    return {"box": box, **ids}


def test_find_by_key_returns_only_that_key_in_the_callers_sight(many, monkeypatch):
    """sp_task 는 글자 그대로 — 그 key 의 보이는 과제만이고 key 가 없는 과제 · 다른 key · 남의 비공개 과제는 없다. 앞부분만 같은 key 는 걸리지
    않는다. 답의 머리는 caller · total · truncated 이고 과제마다 계약의 칸이 다 있다."""
    out = _find(monkeypatch, OWNER, sp_task=KEY)
    assert (out["caller"], set(_ids(out)), out["total"], out["truncated"]) == ("user", {many["free"], many["coded"]}, 2, False)
    first = next(p for p in out["projects"] if p["project_id"] == many["coded"])
    assert set(first) == {"project_id", "code", "name", "stage", "round", "sp_task", "my_role", "mcp_visibility", "classification",
                          "targets", "registry_top", "registry_total"}
    assert (first["code"], first["stage"], first["round"], first["sp_task"], first["my_role"], first["mcp_visibility"],
            first["classification"], first["targets"], first["registry_top"], first["registry_total"]) == (
        "F-1", "DV1", "dv1", KEY, "owner", "private", "internal", [], [], 0)
    assert _find(monkeypatch, OWNER, sp_task="알파 개발")["projects"] == []
    assert set(_ids(_find(monkeypatch, OWNER, sp_task=f" {KEY} "))) == {many["free"], many["coded"]}      # 앞뒤 공백만 뗀다


def test_find_without_filters_lists_only_projects_that_have_a_key(many, monkeypatch):
    """거름을 다 비우면 SP 과제가 달린 보이는 과제 전부다 — key 없는 과제는 없다. 차수만 주어도 그렇다."""
    assert set(_ids(_find(monkeypatch, OWNER))) == {many["coded"], many["free"], many["other"]}
    assert _ids(_find(monkeypatch, OWNER, round="pv1")) == []                      # pv1 은 key 없는 과제뿐이다


def test_find_by_round_takes_codes_and_unknown_only(many, monkeypatch):
    """round 는 차수 코드(정규화 뒤 글자 그대로) · unknown(차수 모름 — stage 가 꼴이 아닌 과제만)이다. 꼴이 아니면 round_invalid."""
    assert _ids(_find(monkeypatch, OWNER, sp_task=KEY, round="ＤＶ１")) == [many["coded"]]
    assert _ids(_find(monkeypatch, OWNER, sp_task=KEY, round="unknown")) == [many["free"]]
    assert _ids(_find(monkeypatch, OWNER, round="모름")) == [many["free"]]
    assert _find(monkeypatch, OWNER, sp_task=KEY, round="dv")["error"] == "round_invalid"


def test_find_follows_the_mcp_sight_of_the_caller(many, monkeypatch):
    """시야는 MCP 의 것이다(visible_projects) — 구성원은 제 역할로 보고, 남은 제 과제만 본다. 조직 공개로 열면 남(역할 없음 — my_role null)과
    위임 신원 없는 호출(service — 조직 공개만)도 본다. 폐기된 과제는 누구에게도 없다."""
    box = many["box"]
    routes.put_members(many["coded"], routes.MembersBody(members=[routes.MemberItem(email=VIEWER, role="viewer")]),
                       ident=_who(OWNER))
    seen = _find(monkeypatch, VIEWER, sp_task=KEY)
    assert [(p["project_id"], p["my_role"]) for p in seen["projects"]] == [(many["coded"], "viewer")]
    assert _ids(_find(monkeypatch, STRANGER, sp_task=KEY)) == [many["theirs"]]
    assert _find(monkeypatch, None, sp_task=KEY) == {"caller": "service", "projects": [], "total": 0, "truncated": False}
    routes.patch_project(many["coded"], routes.ProjectPatchBody(mcp_visibility="org"), ident=_who(OWNER))
    theirs = _find(monkeypatch, STRANGER, sp_task=KEY)
    assert {p["project_id"]: p["my_role"] for p in theirs["projects"]} == {many["theirs"]: "owner", many["coded"]: None}
    service = _find(monkeypatch, None, sp_task=KEY)
    assert (service["caller"], _ids(service), service["projects"][0]["my_role"]) == ("service", [many["coded"]], None)
    box.store.execute("UPDATE rr_projects SET status = 'purged' WHERE id = ?", (many["coded"],))
    assert _ids(_find(monkeypatch, OWNER, sp_task=KEY)) == [many["free"]]
    assert _find(monkeypatch, None, sp_task=KEY)["projects"] == []


def test_find_by_design_artifact_keys_reads_the_project_sources(many, monkeypatch):
    """설계 자료 열쇠로 찾는다 — mcad 는 StepForge project_id, cae 는 dyna_result 원천의 report_ids 가운데 하나, ecad 는 붙은 보드의 job_id
    (대소문자 무시). 설계 자료로 찾을 때는 SP 과제가 없는 과제도 든다. sp_task 와 함께 주면 둘 다 맞는 과제다. 종류 · 열쇠는 함께 준다."""
    box = many["box"]
    owner = _who(OWNER)
    routes.add_source(many["bare"], routes.SourceBody(kind="mcad", app_key="heax-step_forge", ref={"stepforge_project_id": MCAD_ID}),
                      ident=owner)
    routes.add_source(many["coded"], routes.SourceBody(kind="dyna_result", app_key="heax-kooremapper_mcp",
                                                       ref={"report_ids": [7, REPORT_ID]}), ident=owner)
    box.gw.tool_map = {"find_job": "odb-hub"}
    box.gw.answers["find_job"] = {"jobs": [{"job_id": BOARD, "project": "알파", "model": "SM-A100", "board_type": "main",
                                            "revision": "C2", "original_filename": "a.tgz", "uploaded_at": 1}]}
    routes.put_ecad_board(many["other"], routes.EcadBoardBody(odb_job_id=BOARD), ident=owner)
    routes.add_source(many["theirs"], routes.SourceBody(kind="mcad", app_key="heax-step_forge",
                                                        ref={"stepforge_project_id": MCAD_ID}), ident=_who(STRANGER))
    assert _ids(_find(monkeypatch, OWNER, artifact_kind="mcad", artifact_id=MCAD_ID.lower())) == [many["bare"]]
    assert _ids(_find(monkeypatch, OWNER, artifact_kind="CAE", artifact_id=REPORT_ID.lower())) == [many["coded"]]
    assert _ids(_find(monkeypatch, OWNER, artifact_kind="ecad", artifact_id=BOARD.upper())) == [many["other"]]
    assert _ids(_find(monkeypatch, OWNER, artifact_kind="cae", artifact_id="7")) == [many["coded"]]
    assert _ids(_find(monkeypatch, OWNER, sp_task=OTHER_KEY, artifact_kind="cae", artifact_id=REPORT_ID)) == []
    assert _ids(_find(monkeypatch, STRANGER, artifact_kind="mcad", artifact_id=MCAD_ID)) == [many["theirs"]]
    assert _find(monkeypatch, OWNER, artifact_kind="mcad")["error"] == "E100"
    assert _find(monkeypatch, OWNER, artifact_id=MCAD_ID)["error"] == "E100"
    assert _find(monkeypatch, OWNER, artifact_kind="pcb", artifact_id=BOARD)["error"] == "E100"


def test_find_pages_by_offset_and_shrinks_a_page_to_the_wire(many, monkeypatch):
    """한 번에 limit(1 ~ 50 으로 죈다) 과제이고 남으면 truncated · next_offset 이다 — 다음 쪽은 offset 이다. MCP 결과 상한을 넘으면 과제 수를
    줄여 나눈다(자르지 않는다)."""
    first = _find(monkeypatch, OWNER, limit=2)
    assert (len(first["projects"]), first["total"], first["truncated"], first["next_offset"]) == (2, 3, True, 2)
    rest = _find(monkeypatch, OWNER, limit=2, offset=first["next_offset"])
    assert (len(rest["projects"]), rest["truncated"], "next_offset" in rest) == (1, False, False)
    assert set(_ids(first) + _ids(rest)) == {many["coded"], many["free"], many["other"]}
    assert len(_find(monkeypatch, OWNER, limit=0)["projects"]) == 1 and _find(monkeypatch, OWNER, limit=999)["total"] == 3
    one = srv._wire_chars({"x": _find(monkeypatch, OWNER, limit=1)["projects"]})
    monkeypatch.setattr(srv, "MCP_RESULT_CHARS", one + 400)
    fitted = _find(monkeypatch, OWNER)
    assert (len(fitted["projects"]), fitted["truncated"], fitted["next_offset"]) == (1, True, 1)


def test_both_subject_tools_are_risk_tools_closed_to_risk_review_seats():
    """D-18 — 두 도구 이름이 risk_ 로 시작한다. 에이전트 엔진은 리스크 심사 좌석에 리스크 앱 도구를 이름으로 닫고(변경 · 스냅샷 둘만 연다 —
    delib 엔진 _risk_designated_refusal 갈래 app), 자유 조회 접두에도 걸리지 않는다(포털 contracts §8)."""
    names = {t.name for t in asyncio.run(srv.mcp.list_tools())}
    for name in ("risk_set_project_subject", "risk_find_projects_by_subject"):
        assert name in names and name.startswith("risk_") and name not in ("risk_get_diff", "risk_get_snapshot")


def _registry_all(target_key: str) -> list[dict]:
    """MCP risk_get_registry 가 이 신원에게 주는 그 대상의 등록부 행 전부(쪽을 다 잇는다)."""
    page = srv.risk_get_registry(target_key=target_key)
    rows = list(page["rows"])
    while page.get("next_offset"):
        page = srv.risk_get_registry(target_key=target_key, offset=page["next_offset"])
        rows += page["rows"]
    return [{"target_key": target_key, **r} for r in rows]


def test_registry_rows_pass_the_same_door_as_risk_get_registry(ledger, monkeypatch):
    """등록부 앞 행은 같은 사람이 risk_get_registry 로 받는 행과 같은 문을 지난 행이다 — 과제의 지금 대상(과제 주인의 대상만 — 남이 매단 대상은
    빠진다)마다 그 도구의 행 전부를 주의 등급 → 우선순위 → 지지 영역 · 전문가 수 → 키 차례로 세운 앞 다섯(칸 값 · 대표 주장 그대로 — 상태 낱말 ·
    stale_json 은 원장 그대로)과 그 수다. 그 대상을 risk_get_registry 로 못 보는 남에게는 과제째 없고, 조직 공개로 열면 남 · service 도 같은
    행을 본다. 원장은 남 시험 표와 같은 생산자 사슬(검토 → 쟁점 → 종합)이다."""
    store, ids = ledger
    gw = Gateway()
    gw.answers[sp_subject.RESOLVER_CALL] = _any_key
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: gw.handle(request))
    owner = factories.ident(LEDGER_OWNER)
    routes.put_sp_subject(ids["project"], routes.SpSubjectBody(sp_task=KEY, round="dv1"), ident=owner)
    assert gw.calls(sp_subject.RESOLVER_CALL)                          # 원장 주인의 등록 PAT 로 풀었다
    _forged_snapshot, forged_target = _forge(store, ids)               # 남이 주인의 과제에 매단 대상(RD-10) — 싣지 않는다

    factories.act_as_delegate(monkeypatch, LEDGER_OWNER)
    found = _call("risk_find_projects_by_subject", sp_task=KEY, round="dv1")
    assert _ids(found) == [ids["project"]]
    project = found["projects"][0]
    assert [t["target_key"] for t in project["targets"]] == [ids["target"]] and forged_target != ids["target"]
    assert set(project["targets"][0]) == {"target_key", "kind", "level", "verdict_candidate", "verdict_final", "created_at"}
    full = [row for t in project["targets"] for row in _registry_all(t["target_key"])]
    assert project["registry_total"] == len(full) > routes.SUBJECT_REGISTRY_TOP, len(full)
    want = sorted(full, key=routes._subject_registry_order)[:routes.SUBJECT_REGISTRY_TOP]
    assert [(r["target_key"], r["cluster_key"]) for r in project["registry_top"]] == [(r["target_key"], r["cluster_key"]) for r in want]
    for got, row in zip(project["registry_top"], want):
        assert {c: got[c] for c in routes.SUBJECT_REGISTRY_COLS} == {c: row.get(c) for c in routes.SUBJECT_REGISTRY_COLS}
        assert got["claim"] == row["merged"]["claim"] and got["status"] in ("open", "rejected_in_panel", "verified", "dismissed",
                                                                           "mitigated", "superseded")

    factories.act_as_delegate(monkeypatch, LEDGER_STRANGER)
    assert srv.risk_get_registry(target_key=ids["target"])["error"] == "not_visible"
    assert _find(monkeypatch, LEDGER_STRANGER, sp_task=KEY)["projects"] == []
    routes.patch_project(ids["project"], routes.ProjectPatchBody(mcp_visibility="org"), ident=owner)
    theirs = _find(monkeypatch, LEDGER_STRANGER, sp_task=KEY)["projects"]
    assert [(p["project_id"], p["my_role"]) for p in theirs] == [(ids["project"], None)]
    assert theirs[0]["registry_top"] == project["registry_top"] and theirs[0]["registry_total"] == project["registry_total"]
    assert [(r["target_key"], r["cluster_key"]) for r in _registry_all(ids["target"])] == [
        (r["target_key"], r["cluster_key"]) for r in full]                 # 그 남이 risk_get_registry 로 받는 행과 같다
    service = _find(monkeypatch, None, sp_task=KEY)
    assert (service["caller"], _ids(service)) == ("service", [ids["project"]])


# ================================================================ 반출 · 들여오기 — sp_task 는 이 박스의 풀이로만 선다
def test_import_never_carries_an_sp_task_and_export_does_not_ship_one(box, monkeypatch):
    """들여오기(박스 사이 이동 · 손으로 만든 줄)는 풀이를 지나지 않는다 — rr_projects 줄의 sp_task 는 버리고(새 행은 NULL) 뺀 줄 수를 답의
    sp_task_dropped 로 말한다. 그렇지 않으면 아무 key 나 단 조직 공개 과제를 감사 없이 남의 과제 보기에 세울 수 있다(반대 검토 R1). 반출도
    sp_task 를 싣지 않는다 — 받는 박스에서 주인이 다시 확인한다(그 박스의 풀이 · 감사). 들여온 과제는 주제 쓰기로만 key 를 얻는다."""
    from app import export  # noqa: PLC0415

    _put(box.project, OWNER, KEY)
    assert _subject(box.store, box.project)[0] == KEY
    lines = [json.loads(ln) for ln in "".join(export.iter_lines(box.store, OWNER, 0)).splitlines()[1:]]
    shipped = [ln["row"] for ln in lines if ln["table"] == "rr_projects"]
    assert shipped and all("sp_task" not in row for row in shipped), "반출은 sp_task 를 싣지 않는다"

    head = {"schema_version": box.store.schema_version(), "app_version": "x", "origin": {}}
    row = {"id": "p-imp", "owner_sub": OWNER, "code": "IMP-1", "name": "들여온 과제", "stage": "dv1", "sp_task": OTHER_KEY,
           "mcp_visibility": "org", "created_at": 1, "updated_at": 1}
    body = json.dumps(head) + "\n" + json.dumps({"table": "rr_projects", "row": row}, ensure_ascii=False) + "\n"
    out = export.import_jsonl(box.store, OWNER, body)
    assert (out["inserted"], out["sp_task_dropped"]) == (1, 1)
    assert _subject(box.store, "p-imp") == (None, "dv1") and _audits(box.store, "p-imp") == []
    assert _find(monkeypatch, STRANGER, sp_task=OTHER_KEY)["projects"] == [], "남의 시야에 그 key 로 서지 않는다"
    plain = export.import_jsonl(box.store, OWNER, json.dumps(head) + "\n" + json.dumps(
        {"table": "rr_projects", "row": {**row, "id": "p-imp2", "code": "IMP-2", "sp_task": None}}, ensure_ascii=False) + "\n")
    assert plain["inserted"] == 1 and "sp_task_dropped" not in plain, "뺀 것이 없으면 답은 종전 꼴이다"


# ================================================================ D-18 — 과제 주제는 좌석에 가지 않는다
SENTINEL = "알파 개발_C2-좌석에-가면-안-되는-key"


def test_a_projects_sp_task_never_reaches_the_seats(risk_store, monkeypatch):
    """sp_task 는 리스크 앱 안의 칸이다 — 브리프(근거 E0 ~ E9 · 메타 — 넓은 창이라 줄이지 않는다) · 패널 질문 · 스냅샷 · 비교의 모든 쪽(REST · MCP
    risk_get_snapshot · risk_get_diff 와 같은 함수)에 그 key 가 없다. 유사 · 계보 경로가 다른 과제를 읽으므로 두 과제 다 key 를 단다(D-18 —
    포털 contracts §9 '좌석에는 싣지 않는다')."""
    from app import brief, runner  # noqa: PLC0415

    gw = Gateway()
    gw.answers[sp_subject.RESOLVER_CALL] = _any_key
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda _self, request: gw.handle(request))
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    risk_store.upsert_credential(factories.OWNER, identity.encrypt_pat("syn-pat-not-real").decode("ascii"), "sub", factories.OWNER,
                                 "[]", now_epoch() + 30 * 86400)
    synth = factories.make_diff_target(risk_store, 40)
    sibling = factories.make_diff_target(risk_store, 3, seed=11)
    owner = factories.ident(factories.OWNER)
    for project_id in (synth.project_id, sibling.project_id):
        out = routes.put_sp_subject(project_id, routes.SpSubjectBody(sp_task=SENTINEL, round="dv1"), ident=owner)
        assert out["sp_task"] == SENTINEL
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_projects WHERE sp_task = ?", (SENTINEL,))["n"] == 2

    def dumped(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    seat_texts = {
        "brief": dumped(brief.build_brief(risk_store, synth.target_key, owner_sub=factories.OWNER, shield_lint=True,
                                          profile=brief.web_profile(500_000))),
        "panel_question": runner.panel_question(risk_store, synth.target_key),
        "panel_question(diff_ref)": runner.panel_question(risk_store, synth.target_key, diff_ref=True),
        **{f"snapshot:{part}": dumped(routes.snapshot_part(synth.target_snapshot_id, part, owner_sub=factories.OWNER))
           for part in routes.SNAPSHOT_PARTS},
        **{f"diff:{part}": dumped(routes.diff_part(synth.diff_id, part, owner_sub=factories.OWNER)) for part in routes.DIFF_PARTS},
    }
    # 빈손으로 지나가지 않게 — 브리프 · 스냅샷 IR · 변경 줄 · 패널 질문은 내용이 찬 답이다(합성 스냅샷에는 소스 호출이 없어 calls 는 빈 목록이다).
    sizes = {name: len(seat_texts[name]) for name in ("brief", "snapshot:ir", "diff:lines", "panel_question")}
    assert sizes["brief"] > 10_000 and sizes["snapshot:ir"] > 10_000 and sizes["diff:lines"] > 1_000 and sizes["panel_question"] > 300, sizes
    leaked = sorted(name for name, text in seat_texts.items() if SENTINEL in text or "sp_task" in text)
    assert not leaked, leaked
