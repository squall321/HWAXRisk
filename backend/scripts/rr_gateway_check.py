#!/usr/bin/env python3
# 배포된 게이트웨이에 리스크 앱 MCP 도구가 실제로 떠 있는지 이 체크아웃의 소스(app/mcp_server.py)와 대조하는 읽기 전용 점검 — 표준 라이브러리만 쓴다
"""리스크 심사 재설계 M2 걸음 U11(WP5b C15). 도구가 있는지는 소스가 아니라 게이트웨이에 묻는다(리포 규칙 — 'unknown tool: intake' 전례).

사용(어느 디렉터리에서든 — venv·앱 의존성 없이 python3 3.10 이상이면 돈다. 3.10~3.13 에서 확인했다).

    python3 backend/scripts/rr_gateway_check.py                      # PAT 없이 — 무인증 /tools-map 목록만 본다
    read -rs HWAX_GATEWAY_PAT && export HWAX_GATEWAY_PAT             # PAT 는 셸에만(화면·기록에 남지 않는다)
    python3 backend/scripts/rr_gateway_check.py                      # PAT 로 — tools/list 와 새 읽기 도구 한 번 호출

- 기대 목록 — `backend/app/mcp_server.py` 의 `@mcp.tool` 함수 이름(AST 로 읽는다. 앱을 들이지 않는다). 이 체크아웃이 기준이다.
- PAT 가 환경(`HWAX_GATEWAY_PAT`)에 있으면 게이트웨이 MCP(`HWAX_GATEWAY_URL`, 기본 http://127.0.0.1:9110/mcp)에 tools/list 를 묻고,
  새 읽기 도구(`risk_get_units`)를 없는 대상 키로 한 번 부른다 — `not_visible` 이면 배포된 앱이 그 도구를 안다(살아 있다),
  `unknown tool` 이면 게이트웨이 목록에만 있다(앱은 모른다).
- PAT 가 없으면 무인증 `GET /tools-map` 에서 `heax-hwax_risk` 백엔드의 도구만 본다. 호출 확인은 PAT 가 있어야 한다.
- 이름이 겹치는 도구에 게이트웨이가 붙이는 접두(`heaxhwax_risk_…`)는 꼬리 일치로 맞춘다.
- PAT 는 인자로 받지 않고 찍지 않는다. 쓰는 호출이 없다. 프록시 환경변수는 쓰지 않는다(게이트웨이는 이 박스에 있다).
- 종료 0 이상 없음 · 2 판정 불가(닿지 않음·PAT 거절·리스크 앱이 안 보임) · 3 배포본이 낡았다(SIF 를 다시 빌드하고 인스턴스를 바꾼다).
- update-all 에 배선하지 않는다(재설계 M2.md 5절 #15). 배포 뒤 절차서가 한 번 부른다.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

OK, CANT_JUDGE, STALE = 0, 2, 3
BACKEND = "heax-hwax_risk"                  # 게이트웨이가 허브 앱에 붙이는 백엔드 키(heax- + 앱 id)
SOURCE = Path(__file__).resolve().parents[1] / "app" / "mcp_server.py"
DEFAULT_URL = "http://127.0.0.1:9110/mcp"
PROBE_TOOL = "risk_get_units"               # M2 에 새로 든 읽기 도구 — 없는 키로 부르면 not_visible 이 정상이다
PROBE_ARGS = {"target_key": "rr-gateway-check-absent"}
PROTOCOL_VERSION = "2025-06-18"
TIMEOUT_S = 60
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class CantJudge(Exception):
    """판정 불가 — 까닭을 사람이 읽는 글로 싣는다."""


def expected_tools(source: Path = SOURCE) -> list[str]:
    """`@mcp.tool` · `@mcp.tool()` · `@mcp.tool(name=…)` 로 꾸민 함수의 도구 이름(정렬)."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            call = dec if isinstance(dec, ast.Call) else None
            func = call.func if call else dec
            if not (isinstance(func, ast.Attribute) and func.attr == "tool"
                    and isinstance(func.value, ast.Name) and func.value.id == "mcp"):
                continue
            name = node.name
            for kw in call.keywords if call else ():
                if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    name = kw.value.value
            names.append(name)
    return sorted(names)


def exposed_as(tool: str, names: list[str]) -> str | None:
    """게이트웨이 목록에서 그 도구가 드러난 이름 — 그대로이거나 접두가 붙은 꼬리 일치."""
    if tool in names:
        return tool
    return next((n for n in sorted(names) if n.endswith(f"_{tool}")), None)


def _excerpt(raw: bytes | str, secret: str = "") -> str:
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    if secret:
        text = text.replace(secret, "***")
    text = " ".join(text.split())
    return text[:200] + (f"… (원래 {len(text)}자)" if len(text) > 200 else "")


def _http(method: str, url: str, *, body: bytes | None = None, headers: dict | None = None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read()
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise CantJudge(f"{url} 에 닿지 않는다({reason}) — 게이트웨이가 떠 있는지, 주소(HWAX_GATEWAY_URL)가 맞는지 본다") from exc


def _sse_messages(body: bytes) -> list[dict]:
    """text/event-stream 본문의 data 덩이를 JSON 으로."""
    out, data = [], []
    for line in body.decode("utf-8", "replace").splitlines() + [""]:
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line.strip() and data:
            try:
                out.append(json.loads("\n".join(data)))
            except ValueError:
                pass
            data = []
    return out


class McpClient:
    """streamable HTTP MCP 의 최소 클라이언트 — initialize → tools/list → tools/call → 세션 닫기."""

    def __init__(self, url: str, pat: str) -> None:
        self.url, self.pat = url, pat
        self.session: str | None = None
        self.version = PROTOCOL_VERSION
        self._id = 0

    def _headers(self) -> dict:
        headers = {"Authorization": f"Bearer {self.pat}", "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.session:
            headers.update({"Mcp-Session-Id": self.session, "MCP-Protocol-Version": self.version})
        return headers

    def _post(self, message: dict) -> tuple[int, dict, bytes]:
        status, headers, body = _http("POST", self.url, body=json.dumps(message).encode("utf-8"), headers=self._headers())
        if status in (401, 403):
            raise CantJudge(f"게이트웨이가 PAT 를 거절했다(HTTP {status} — {_excerpt(body, self.pat)}). 포털 '개인 토큰' 페이지에서"
                            " 다시 받거나, PAT 없이 돌려 /tools-map 으로 본다")
        if status >= 400:
            raise CantJudge(f"{message.get('method')} 이 HTTP {status} 로 끝났다 — {_excerpt(body, self.pat)}")
        return status, headers, body

    def request(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        status, headers, body = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}})
        if self.session is None and headers.get("mcp-session-id"):
            self.session = headers["mcp-session-id"]
        if headers.get("content-type", "").startswith("text/event-stream"):
            messages = _sse_messages(body)
        else:
            try:
                parsed = json.loads(body or b"null")
            except ValueError as exc:
                raise CantJudge(f"{method} 응답이 JSON 이 아니다 — {_excerpt(body, self.pat)}") from exc
            messages = parsed if isinstance(parsed, list) else [parsed]
        reply = next((m for m in messages if isinstance(m, dict) and m.get("id") == self._id), None)
        if reply is None:
            raise CantJudge(f"{method} 응답에 답이 없다(HTTP {status}) — {_excerpt(body, self.pat)}")
        if "error" in reply:
            raise CantJudge(f"{method} 오류 — {_excerpt(json.dumps(reply['error'], ensure_ascii=False), self.pat)}")
        return reply.get("result") or {}

    def notify(self, method: str) -> None:
        self._post({"jsonrpc": "2.0", "method": method})

    def close(self) -> None:
        if self.session:
            try:
                _http("DELETE", self.url, headers=self._headers())
            except CantJudge:
                pass


def _verdict(code: int, why: str) -> int:
    label = {OK: "이상 없음", CANT_JUDGE: "판정 불가", STALE: "배포본이 낡았다"}[code]
    print(f"판정 {code} — {label}: {why}")
    if code == STALE:
        print("  할 일 — 리스크 앱 SIF 를 이 소스로 다시 빌드하고 떠 있는 인스턴스를 바꾼 뒤 이 점검을 다시 돌린다")
    return code


def _compare(expected: list[str], names: list[str], extra_pool: list[str]) -> tuple[dict[str, str], list[str]]:
    """({기대 이름: 드러난 이름}, 빠진 기대 이름). 소스에 없는 리스크 앱 도구는 알리기만 한다(이 체크아웃이 배포본보다 낡았을 수 있다)."""
    found = {tool: n for tool in expected if (n := exposed_as(tool, names))}
    missing = [tool for tool in expected if tool not in found]
    extra = sorted(set(extra_pool) - set(found.values()))
    if missing:
        print(f"[빠짐] {len(missing)}종 — {', '.join(missing)}")
    if extra:
        print(f"[소스에 없음] {len(extra)}종 — {', '.join(extra)} (이 체크아웃이 배포본보다 낡았을 수 있다 — git pull 뒤 다시 돌린다)")
    return found, missing


def tools_map_url(mcp_url: str) -> str:
    base = mcp_url.rstrip("/")
    return (base[: -len("/mcp")] if base.endswith("/mcp") else base) + "/tools-map"


def check_tools_map(url: str, expected: list[str]) -> int:
    map_url = tools_map_url(url)
    status, _headers, body = _http("GET", map_url, headers={"Accept": "application/json"})
    if status != 200:
        raise CantJudge(f"{map_url} 이 HTTP {status} 로 끝났다 — {_excerpt(body)}")
    try:
        data = json.loads(body)
        names = sorted(n for n, bk in (data.get("map") or {}).items() if bk == BACKEND)
        app = next((a for a in data.get("apps") or () if isinstance(a, dict) and a.get("app") == BACKEND), None)
    except (ValueError, AttributeError) as exc:
        raise CantJudge(f"{map_url} 의 응답을 읽지 못했다 — {_excerpt(body)}") from exc
    reachable = bool(app and app.get("reachable"))
    print(f"[목록] {map_url}(PAT 없음) — {BACKEND} 도구 {len(names)}종 · 앱 연결 {'됨' if reachable else '안 됨'}")
    if app is None or not names:
        raise CantJudge(f"게이트웨이 목록에 {BACKEND} 가 없다 — 허브에 리스크 앱이 떠 있는지, 게이트웨이가 허브 앱을 찾았는지 본다")
    if not reachable:
        raise CantJudge(f"게이트웨이가 {BACKEND} 에 닿지 못한다 — 목록이 지난 것일 수 있다. 앱 인스턴스가 떠 있는지 본다")
    _found, missing = _compare(expected, names, names)
    if missing:
        return _verdict(STALE, f"배포된 리스크 앱에 이 소스의 도구 {len(missing)}종이 없다")
    print(f"[호출] 하지 않았다 — HWAX_GATEWAY_PAT 가 없다(PAT 를 주면 {PROBE_TOOL} 을 한 번 불러 앱이 그 도구를 아는지 본다)")
    return _verdict(OK, f"도구 {len(expected)}종이 게이트웨이 목록에 있다(목록만 봤다)")


def check_mcp(url: str, pat: str, expected: list[str]) -> int:
    client = McpClient(url, pat)
    try:
        init = client.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                             "clientInfo": {"name": "rr_gateway_check", "version": "1"}})
        client.version = str(init.get("protocolVersion") or PROTOCOL_VERSION)
        client.notify("notifications/initialized")
        names: list[str] = []
        cursor = None
        for _page in range(50):
            result = client.request("tools/list", {"cursor": cursor} if cursor else {})
            names += [str(t.get("name")) for t in result.get("tools") or () if isinstance(t, dict)]
            cursor = result.get("nextCursor")
            if not cursor:
                break
        names = sorted(set(names))
        pool = [n for n in names if n.startswith("risk_") or n.startswith(BACKEND.replace("-", "") + "_")]
        found = {tool: n for tool in expected if (n := exposed_as(tool, names))}
        print(f"[목록] {url} tools/list(PAT) — 전체 {len(names)}종 가운데 이 소스의 리스크 앱 도구 {len(found)}/{len(expected)}종")
        if not found:
            raise CantJudge("리스크 앱 도구가 하나도 안 보인다 — 이 PAT 계정에 리스크 앱 권한이 없거나(포털 '내 권한'), 토큰 페이지에서 앱을"
                            " 꺼 두었거나, 게이트웨이가 앱을 못 찾았다. PAT 없이 다시 돌리면 /tools-map 으로 등록 여부를 본다")
        found, missing = _compare(expected, names, pool)
        probe = found.get(PROBE_TOOL)
        if probe is None:
            return _verdict(STALE, f"배포된 리스크 앱에 이 소스의 도구 {len(missing)}종이 없다({PROBE_TOOL} 포함 — 호출하지 않았다)")
        result = client.request("tools/call", {"name": probe, "arguments": PROBE_ARGS})
        text = "\n".join(str(c.get("text") or "") for c in result.get("content") or () if isinstance(c, dict))
        payloads = []
        for raw in (text, result.get("structuredContent")):
            try:
                value = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                continue
            payloads += [value, value.get("result")] if isinstance(value, dict) else []
        if result.get("isError") and "unknown tool" in text.lower():
            print(f"[호출] {probe}(없는 대상 키) → unknown tool — 게이트웨이 목록에만 있고 앱은 그 도구를 모른다")
            return _verdict(STALE, f"{probe} 가 목록에는 있는데 배포된 앱이 모른다")
        if not any(isinstance(p, dict) and p.get("error") == "not_visible" for p in payloads):
            raise CantJudge(f"{probe}(없는 대상 키) 의 답이 not_visible 도 unknown tool 도 아니다 — {_excerpt(text, pat)}")
        print(f"[호출] {probe}(없는 대상 키) → not_visible — 배포된 앱이 그 도구를 안다")
    finally:
        client.close()
    if missing:
        return _verdict(STALE, f"배포된 리스크 앱에 이 소스의 도구 {len(missing)}종이 없다")
    return _verdict(OK, f"도구 {len(expected)}종이 게이트웨이에 있고 {PROBE_TOOL} 이 실제로 답한다")


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="rr_gateway_check", description=__doc__.splitlines()[0],
                            epilog="PAT 는 인자가 아니라 환경변수 HWAX_GATEWAY_PAT 로만 준다.").parse_args(argv)
    try:
        expected = expected_tools()
    except (OSError, SyntaxError) as exc:
        return _verdict(CANT_JUDGE, f"기대 목록({SOURCE})을 읽지 못했다 — {exc}")
    if not expected:
        return _verdict(CANT_JUDGE, f"{SOURCE} 에서 @mcp.tool 을 하나도 찾지 못했다")
    print(f"[기대] {SOURCE.parent.name}/{SOURCE.name} 의 도구 {len(expected)}종")
    url = (os.environ.get("HWAX_GATEWAY_URL") or "").strip() or DEFAULT_URL
    pat = (os.environ.get("HWAX_GATEWAY_PAT") or "").strip()
    try:
        return check_mcp(url, pat, expected) if pat else check_tools_map(url, expected)
    except CantJudge as exc:
        return _verdict(CANT_JUDGE, str(exc))


if __name__ == "__main__":
    sys.exit(main())
