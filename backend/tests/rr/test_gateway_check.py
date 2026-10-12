# 게이트웨이 대조 스크립트(scripts/rr_gateway_check.py)가 기대 목록을 실제 mcp_server.py 에서 읽고, 가짜 게이트웨이(/tools-map·MCP)에 종료 0·2·3 을 가르는지 본다
"""가짜 게이트웨이는 실제 MCP SDK 의 streamable HTTP 서버다 — FastMCP 의 저수준 서버에 tools/list·tools/call 을 다는 꼴이 실제 게이트웨이와
같고, 빈 루프백 포트에 uvicorn 으로 띄운다. 스크립트의 MCP 클라이언트는 손으로 짠 것이라 그 짝까지 손으로 짜면 둘이 같이 틀려도 통과한다.
호출의 답(`not_visible`)은 실제 앱 도구(`app.mcp_server`)가 낸 글을 그대로 싣는다(게이트웨이는 앱의 답을 그대로 넘긴다).
실 게이트웨이(9110)는 부르지 않는다 — 세션 가드가 그 포트를 거절하고, 새 프로세스에는 주소를 늘 이 가짜로 명시한다.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route

import app.mcp_server as srv
from app.risk_store import get_store
from tests.conftest import BACKEND_DIR

SCRIPT = BACKEND_DIR / "scripts" / "rr_gateway_check.py"
PAT = "hwax_pat_test_fake_gateway_check"          # 명백한 가짜 — 실 토큰이 아니다
OTHER_APP_TOOLS = ("search_tools", "echo")


def _load():
    """backend/scripts/rr_gateway_check.py 를 모듈로 읽는다(패키지가 아니라 실행자 셸 전용 파일이다)."""
    spec = importlib.util.spec_from_file_location("hwaxrisk_scripts_rr_gateway_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = _load()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakeGateway:
    """`/tools-map`(무인증)과 `/mcp`(Bearer PAT) 둘. 무엇을 내놓을지는 `reset` 뒤 시험이 칸을 고친다."""

    def __init__(self, answer: list) -> None:
        self._default_answer = answer
        self.reset()
        fm = FastMCP("fake-gateway")
        fm.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        low = fm._mcp_server

        @low.list_tools()
        async def _list_tools() -> list[types.Tool]:
            return [types.Tool(name=n, description="가짜", inputSchema={"type": "object"}) for n in self.listed]

        @low.call_tool(validate_input=False)
        async def _call_tool(name: str, arguments: dict):
            self.calls.append((name, dict(arguments or {})))
            if name not in self.listed:          # 실제 게이트웨이의 route 에 없는 이름
                return types.CallToolResult(content=[types.TextContent(type="text", text=f"unknown tool: {name}")], isError=True)
            if name in self.app_lacks:           # 게이트웨이는 지난 목록으로 알지만 지금 앱(FastMCP)은 모른다
                original = name.split("heaxhwax_risk_", 1)[-1]
                return types.CallToolResult(content=[types.TextContent(type="text", text=f"Unknown tool: {original}")],
                                            isError=True)
            return self.answer

        star = fm.streamable_http_app()
        star.router.routes.insert(0, Route("/tools-map", self._tools_map))
        self.app = self._guard(star)

    def reset(self) -> None:
        self.listed = [*check.expected_tools(), *OTHER_APP_TOOLS]
        self.app_lacks: set[str] = set()
        self.map_status, self.map_body, self.reachable, self.backend = 200, None, True, check.BACKEND
        self.calls: list[tuple[str, dict]] = []
        self.auth_seen: list[str] = []
        self.answer = self._default_answer

    async def _tools_map(self, request):
        if self.map_body is not None:
            return JSONResponse(self.map_body, status_code=self.map_status)
        ours = [n for n in self.listed if n not in OTHER_APP_TOOLS]
        body = {"map": {**{n: self.backend for n in ours}, "search_tools": "_gateway", "echo": "heax-other"},
                "apps": [{"app": self.backend, "reachable": self.reachable, "tool_count": len(ours)},
                         {"app": "_gateway", "reachable": True, "tool_count": 1}]}
        return JSONResponse(body, status_code=self.map_status)

    def _guard(self, inner):
        async def app(scope, receive, send):
            if scope["type"] == "http" and scope["path"].startswith("/mcp"):
                auth = dict(scope["headers"]).get(b"authorization", b"").decode()
                self.auth_seen.append(auth)
                if auth != f"Bearer {PAT}":
                    await send({"type": "http.response.start", "status": 401,
                                "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body", "body": b'{"detail":"invalid token"}'})
                    return
            await inner(scope, receive, send)
        return app

    def start(self) -> None:
        port = _free_port()
        self.url = f"http://127.0.0.1:{port}/mcp"
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=port, log_level="warning",
                                                    lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            assert time.monotonic() < deadline, "가짜 게이트웨이가 뜨지 않았다"
            time.sleep(0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)


@pytest.fixture(scope="module")
def real_answer() -> list:
    """실제 앱 도구가 없는 대상 키에 내는 답(FastMCP 가 와이어에 싣는 내용 그대로)."""
    get_store()
    answer = asyncio.run(srv.mcp.call_tool(check.PROBE_TOOL, check.PROBE_ARGS))
    assert '"not_visible"' in answer[0].text
    return answer


@pytest.fixture(scope="module")
def gateway(real_answer):
    gw = FakeGateway(real_answer)
    gw.start()
    yield gw
    gw.stop()


@pytest.fixture
def gw(gateway, monkeypatch):
    gateway.reset()
    monkeypatch.setenv("HWAX_GATEWAY_URL", gateway.url)
    monkeypatch.delenv("HWAX_GATEWAY_PAT", raising=False)
    return gateway


def _run(capsys) -> tuple[int, str]:
    rc = check.main([])
    out = capsys.readouterr()
    return rc, out.out + out.err


# ---------------------------------------------------------------- 기대 목록
def test_기대_목록은_앱이_실제로_등록한_도구다():
    registered = sorted(t.name for t in asyncio.run(srv.mcp.list_tools()))
    assert check.expected_tools() == registered
    assert check.PROBE_TOOL in registered
    assert check.SOURCE == BACKEND_DIR / "app" / "mcp_server.py"


def test_AST_는_세_꼴의_꾸밈을_읽고_다른_꾸밈은_뺀다(tmp_path):
    source = tmp_path / "mcp_server.py"
    source.write_text(
        "@mcp.tool()\ndef a(): ...\n"
        "@mcp.tool\nasync def b(): ...\n"
        "@mcp.tool(name='renamed')\ndef c(): ...\n"
        "@other.tool()\ndef d(): ...\n"
        "@mcp.resource('x')\ndef e(): ...\n"
        "def f(): ...\n", encoding="utf-8")
    assert check.expected_tools(source) == ["a", "b", "renamed"]


# ---------------------------------------------------------------- PAT 없이 — /tools-map
def test_PAT_없이_목록이_다_있으면_0_이고_호출은_하지_않는다(gw, capsys):
    rc, out = _run(capsys)
    assert rc == 0, out
    assert f"{check.BACKEND} 도구 {len(check.expected_tools())}종 · 앱 연결 됨" in out
    assert "[호출] 하지 않았다" in out and "판정 0 — 이상 없음" in out
    assert gw.calls == [] and gw.auth_seen == []


def test_PAT_없이_빠진_도구가_있으면_3(gw, capsys):
    gw.listed.remove(check.PROBE_TOOL)
    rc, out = _run(capsys)
    assert rc == 3, out
    assert f"[빠짐] 1종 — {check.PROBE_TOOL}" in out and "판정 3 — 배포본이 낡았다" in out and "SIF" in out


def test_PAT_없이_소스에_없는_도구는_알리기만_한다(gw, capsys):
    gw.listed.append("risk_from_the_future")
    rc, out = _run(capsys)
    assert rc == 0, out
    assert "[소스에 없음] 1종 — risk_from_the_future" in out


@pytest.mark.parametrize("change, phrase", [
    ({"backend": "heax-someone_else"}, "목록에 heax-hwax_risk 가 없다"),
    ({"reachable": False}, "닿지 못한다"),
    ({"map_status": 500}, "HTTP 500"),
    ({"map_body": ["목록이", "아니다"]}, "읽지 못했다"),
])
def test_PAT_없이_앱이_없거나_끊겼거나_답이_이상하면_2(gw, capsys, change, phrase):
    for key, value in change.items():
        setattr(gw, key, value)
    rc, out = _run(capsys)
    assert rc == 2, out
    assert phrase in out and "판정 2 — 판정 불가" in out


# ---------------------------------------------------------------- PAT 로 — MCP tools/list 와 호출
def test_PAT_로_목록과_호출이_맞으면_0(gw, monkeypatch, capsys):
    monkeypatch.setenv("HWAX_GATEWAY_PAT", PAT)
    rc, out = _run(capsys)
    assert rc == 0, out
    n = len(check.expected_tools())
    assert f"이 소스의 리스크 앱 도구 {n}/{n}종" in out
    assert f"[호출] {check.PROBE_TOOL}(없는 대상 키) → not_visible" in out and "판정 0 — 이상 없음" in out
    assert gw.calls == [(check.PROBE_TOOL, check.PROBE_ARGS)]
    assert gw.auth_seen and set(gw.auth_seen) == {f"Bearer {PAT}"}
    assert PAT not in out


def test_접두가_붙은_이름도_꼬리로_맞추고_그_이름으로_부른다(gw, monkeypatch, capsys):
    monkeypatch.setenv("HWAX_GATEWAY_PAT", PAT)
    gw.listed = [f"heaxhwax_risk_{n}" for n in check.expected_tools()] + list(OTHER_APP_TOOLS)
    rc, out = _run(capsys)
    assert rc == 0, out
    assert gw.calls == [(f"heaxhwax_risk_{check.PROBE_TOOL}", check.PROBE_ARGS)]


def test_목록에만_있고_앱이_모르면_3(gw, monkeypatch, capsys):
    monkeypatch.setenv("HWAX_GATEWAY_PAT", PAT)
    gw.app_lacks = {check.PROBE_TOOL}
    rc, out = _run(capsys)
    assert rc == 3, out
    assert "→ unknown tool" in out and "판정 3 — 배포본이 낡았다" in out


def test_PAT_로_빠진_도구가_있으면_3_이고_빠진_도구는_부르지_않는다(gw, monkeypatch, capsys):
    monkeypatch.setenv("HWAX_GATEWAY_PAT", PAT)
    gw.listed.remove(check.PROBE_TOOL)
    rc, out = _run(capsys)
    assert rc == 3, out
    assert f"[빠짐] 1종 — {check.PROBE_TOOL}" in out and gw.calls == []


def test_PAT_로_다른_도구만_빠져도_호출은_하고_3(gw, monkeypatch, capsys):
    monkeypatch.setenv("HWAX_GATEWAY_PAT", PAT)
    other = next(n for n in check.expected_tools() if n != check.PROBE_TOOL)
    gw.listed.remove(other)
    rc, out = _run(capsys)
    assert rc == 3, out
    assert f"[빠짐] 1종 — {other}" in out and gw.calls == [(check.PROBE_TOOL, check.PROBE_ARGS)]


def test_PAT_가_거절되면_2_이고_PAT_를_찍지_않는다(gw, monkeypatch, capsys):
    wrong = "hwax_pat_test_wrong_token"
    monkeypatch.setenv("HWAX_GATEWAY_PAT", wrong)
    rc, out = _run(capsys)
    assert rc == 2, out
    assert "PAT 를 거절했다(HTTP 401" in out and wrong not in out


def test_리스크_앱_도구가_하나도_안_보이면_2(gw, monkeypatch, capsys):
    monkeypatch.setenv("HWAX_GATEWAY_PAT", PAT)
    gw.listed = list(OTHER_APP_TOOLS)
    rc, out = _run(capsys)
    assert rc == 2, out
    assert "리스크 앱 도구가 하나도 안 보인다" in out and gw.calls == []


def test_호출_답이_not_visible_도_unknown_tool_도_아니면_2(gw, monkeypatch, capsys):
    monkeypatch.setenv("HWAX_GATEWAY_PAT", PAT)
    gw.answer = types.CallToolResult(content=[types.TextContent(type="text", text="forbidden: risk_get_units — 권한 없음")],
                                     isError=True)
    rc, out = _run(capsys)
    assert rc == 2, out
    assert "not_visible 도 unknown tool 도 아니다" in out and "forbidden" in out


def test_게이트웨이에_닿지_않으면_2(monkeypatch, capsys):
    monkeypatch.setenv("HWAX_GATEWAY_URL", f"http://127.0.0.1:{_free_port()}/mcp")
    for pat in (None, PAT):
        if pat:
            monkeypatch.setenv("HWAX_GATEWAY_PAT", pat)
        else:
            monkeypatch.delenv("HWAX_GATEWAY_PAT", raising=False)
        rc, out = _run(capsys)
        assert rc == 2, out
        assert "에 닿지 않는다" in out


def test_PAT_는_인자로_받지_않는다():
    with pytest.raises(SystemExit) as exc:
        check.main(["--pat", PAT])
    assert exc.value.code == 2


def test_표준_라이브러리만으로_새_프로세스에서_돈다(gw):
    """`-I -S` — site-packages(앱 venv 포함)와 PYTHON* 환경변수 없이 돈다. 주소는 늘 이 가짜로 명시한다(실 게이트웨이를 부르지 않는다).
    사내 박스의 셸에는 프록시 변수가 있다 — 죽은 프록시를 주어도 이 박스의 게이트웨이에 곧바로 닿아야 한다(urllib 은 프록시를 들일 때 읽으므로
    새 프로세스로만 볼 수 있다)."""
    dead = f"http://127.0.0.1:{_free_port()}"
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
           "HWAX_GATEWAY_URL": gw.url, "HWAX_GATEWAY_PAT": PAT,
           "http_proxy": dead, "HTTP_PROXY": dead, "all_proxy": dead, "ALL_PROXY": dead}
    out = subprocess.run([sys.executable, "-I", "-S", str(SCRIPT)], cwd=Path("/"), env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "판정 0 — 이상 없음" in out.stdout and PAT not in out.stdout + out.stderr
    assert gw.calls == [(check.PROBE_TOOL, check.PROBE_ARGS)]
