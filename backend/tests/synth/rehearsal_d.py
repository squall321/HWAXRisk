# 단계 D 배선 리허설(시험 전용) — 빈 포트·스크래치 디렉터리에 리스크 앱·포털 중계·에이전트 서버·가짜 LLM·가짜 게이트웨이를 띄워 카드 대조 사슬을 실제 HTTP/SSE 로 끝까지 돌리고 증거를 남긴다
"""재설계 M2.md 3절 단계 D — v4 를 굳히기 전에 리스크 앱 → 포털 `/agent/card-review/*` → 에이전트 서버 card_review → 가짜 LLM 배선
전체를 실제 프로세스·소켓으로 본다. 판정의 질은 보지 않는다(가짜 LLM 이 프롬프트를 읽어 형식이 맞는 답을 낸다 — 질은 cae00 파일럿 몫).

    cd backend && ulimit -v 16000000 && <리스크 venv>/bin/python tests/synth/rehearsal_d.py run <스크래치 디렉터리>

형제 리포는 이 파일에서 유도한 리포 루트의 `../HWAXAgentServer` · `../HWAXPortal` 이다(박스마다 루트가 다르다 — 절대경로를 박지 않는다).
그 venv 는 `<리포>/.venv` · `<리포>/backend/.venv` 가 기본이고 `--agent-python` · `--portal-python` 으로 바꾼다.

무엇을 띄우나 — 프로세스 다섯(이 하네스 · 가짜 LLM · 에이전트 서버 · 포털 · 리스크 앱). 하네스 안에 스레드 셋을 둔다.
  게이트웨이 대역 — FastMCP(get_agent_session · list_records · get_record)로 에이전트 서버 시험 고정물의 카드를 준다(엔진의 팩 빌더가
                   `_tools_by_name` 으로 붙는 자리). 요청마다 Authorization 을 적는다.
  heax 대역·싱크 — 리스크 앱의 신원 되묻기(`/api/v1/auth/me`)에 웹 토큰으로 답하고, 그 밖의 길(게이트웨이·AIDataHub)은 적고 503 이다.
  포털 앞 기록기 — 리스크 앱 → 포털 사이의 투명 중계. 요청마다 Authorization 을 적는다(서비스 PAT 가 실렸는지 보는 자리).

무엇을 보나(evidence.json 의 checks — 일곱과 실 저장소):
  1 limits    — 포털 중계를 지난 GET /agent/card-review/limits 가 ctx_tokens=1048576 · ctx_source=server.
  2 cells     — 대상 하나 × 범위 전문가 다섯(카드 셋 · 배경 카드뿐 · 0장) × 단위 전부가 reviewed, 전문가 보고서(REST·MCP summary), 진행판·품질.
  3 wire      — 포털 감사 card_review_run_*, 가짜 LLM /_stats 호출 수, 어느 요청에도 서비스 PAT(secrets.env)·게이트웨이 서비스 토큰이 없다.
  4 conv      — 포털 대화 수가 그대로다.
  5 risk      — 호출이 도는 동안 리스크 앱을 SIGTERM(유예 뒤 KILL) → 같은 데이터 디렉터리로 다시 → 차감·failed 없이 이어 돈다.
  6 agent     — 에이전트 서버를 start.sh 처럼 TERM → 2초 → KILL → 다시. 끊긴 스트림은 인프라(차감 없음)이고 잡이 이어 돈다.
  7 cancel    — 도는 중 취소 → cancelling → cancelled(그 사이 새 잡의 409 를 적는다). 과제 폐기로 잡이 루프 밖에서 닫히면 새 잡은
                409 review_in_flight 다.
  live        — 이 하네스가 띄운 프로세스가 이 박스의 실 저장소를 연 적이 없고(몇 초마다 /proc/<pid>/fd 를 훑는다), 실 저장소의 크기·mtime 이 앞뒤로 같다.

안전(실사고가 있던 자리 — HWAXPortal docs/gotchas · M2.md 4.6.2):
  - 떠 있는 서비스 포트를 쓰지 않는다. 빈 포트를 고르고 띄우기 직전에 비었는지 다시 본다.
  - 이 하네스가 띄운 PID 만 내린다(pkill·fuser·포트 기반 kill 없음). 끝나면 전부 내리고 포트가 닫혔는지 본다.
  - 모든 서비스는 스크래치 아래에만 쓴다 — 에이전트 서버 ARTIFACT_DIR·DELIB_JOB_DIR, 포털 저장소 다섯·JWT 키·업로드, 리스크 앱 DATA_DIR.
    자식의 환경은 처음부터 짓는다(셸의 토큰·프록시·경로 변수를 물려주지 않는다). 포털 backend/.env 가 가리키는 값은 환경변수로 덮는다.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import copy
import gzip
import hashlib
import json
import os
import random
import resource
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
SIBLINGS = REPO.parent
AGENT_ROOT = SIBLINGS / "HWAXAgentServer"
PORTAL_ROOT = SIBLINGS / "HWAXPortal"
PORTAL_BACKEND = PORTAL_ROOT / "backend"

# 이 박스에 떠 있는(떠 있을 수 있는) 서비스 포트 — 포털·vite·에이전트 서버·게이트웨이·ui-check·nginx·heax·vLLM·AIDataHub·RA.
LIVE_PORTS = frozenset({3000, 4040, 4180, 5283, 8000, 8001, 8088, 8700, 8723, 8794, 9009, 9110})
CTX = 1_048_576
MODEL = "fake-glm"
SERVICE_PAT = "svc-pat-must-never-be-sent"             # review_rig.SERVICE_PAT — seed 가 같은지 본다
GATEWAY_SVC_TOKEN = "rehearsal-gateway-service-token"  # 에이전트 서버 MCP 설정의 서비스 자격 — 게이트웨이 대역이 받으면 위반
ADMIN_EMAIL = "rr-admin@example.com"                   # /api/meta/runtime(관리자)만 본다
REVIEWER_PASSWORD = "rehearsal-d-" + "pw-0001"
# 리스크 앱 손잡이(knobs.env) — 단위 크기는 review_rig.CAPS 와 같다(seed 가 대조한다). 합성 40건 → 단위 다섯.
KNOBS = {"HWAXRISK_REVIEW_ENABLED": "1", "HWAXRISK_UNIT_TARGET_LINES": "60", "HWAXRISK_UNIT_MAX_LINES": "120",
         "HWAXRISK_UNITS_SMALL_LINES": "40", "HWAXRISK_REVIEW_CONCURRENCY": "4"}
KNOB_ATTRS = {"HWAXRISK_UNIT_TARGET_LINES": "risk_unit_target_lines", "HWAXRISK_UNIT_MAX_LINES": "risk_unit_max_lines",
              "HWAXRISK_UNITS_SMALL_LINES": "risk_units_small_lines"}
BACKGROUND_TYPES = frozenset({"concept", "faq", "data", "open-observation"})   # 엔진 card_review._BACKGROUND_TYPES
AGENT_STOP_GRACE_S = 2                                  # HWAXAgentServer start.sh 의 STOP_GRACE_S 기본값(TERM → 이만큼 → KILL)
LIVE = ("queued", "running")                            # 잡이 아직 도는 상태(만든 직후는 queued)
RISK_STOP_GRACE_S = 20                                  # 리스크 앱 — 러너 stop(스레드 2초 · 워커 5초) + 프레임 한 칸(ping 15초)


# ════════════════════════════════════════════════════════════════════ 작은 도구
def log(msg: str) -> None:
    print(f"[rehearsal {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def sha12(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def jwt_claims(auth: str) -> dict | None:
    """Bearer JWT 의 본문 칸 몇 개(서명은 보지 않는다 — 누구의 무슨 토큰인지 적는 데만 쓴다)."""
    token = auth[7:].strip() if auth[:7].lower() == "bearer " else auth.strip()
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        body = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, TypeError):
        return None
    if not isinstance(body, dict):
        return None
    return {k: body.get(k) for k in ("email", "pat_name", "scopes", "scope", "jti") if k in body}


def ss_listening() -> set[int]:
    """지금 LISTEN 중인 TCP 포트(ss -ltnH)."""
    out = subprocess.run([SS, "-ltnH"], capture_output=True, text=True, check=True, timeout=20).stdout
    ports: set[int] = set()
    for line in out.splitlines():
        cols = line.split()
        if len(cols) >= 4 and ":" in cols[3]:
            tail = cols[3].rsplit(":", 1)[1]
            if tail.isdigit():
                ports.add(int(tail))
    return ports


def assert_free(port: int) -> None:
    """띄우기 직전 — 떠 있는 서비스 포트가 아니고, LISTEN 중이 아니고, 실제로 묶인다."""
    if port in LIVE_PORTS:
        raise RuntimeError(f"포트 {port} 는 이 박스의 서비스 포트다 — 쓰지 않는다")
    if port in ss_listening():
        raise RuntimeError(f"포트 {port} 가 이미 LISTEN 중이다")
    with socket.socket() as s:
        # uvicorn 처럼 SO_REUSEADDR 로 묶어 본다 — 방금 내린 서버 포트의 TIME_WAIT 는 그 서버가 다시 묶는 데 걸리지 않는다.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))


def pick_ports(names: list[str]) -> dict[str, int]:
    listening = ss_listening()
    out: dict[str, int] = {}
    while len(out) < len(names):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        if port in LIVE_PORTS or port in listening or port in out.values() or port < 20000:
            continue
        out[names[len(out)]] = port
    return out


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_until(pred: Callable[[], Any], timeout: float, what: str, every: float = 1.0) -> Any:
    end = time.monotonic() + timeout
    last_exc: BaseException | None = None
    while time.monotonic() < end:
        try:
            got = pred()
            if got:
                return got
        except Exception as exc:  # noqa: BLE001 — 기다리는 중의 실패는 다음 번에 다시 본다
            last_exc = exc
        time.sleep(every)
    raise TimeoutError(f"{timeout:.0f}초 안에 {what} 가 되지 않았다" + (f" (마지막 오류 {last_exc!r})" if last_exc else ""))


def app_error(body: Any) -> tuple[str | None, dict]:
    """리스크 앱 오류 본문 {error:{code, message}, …detail} → (code, detail)."""
    if not isinstance(body, dict):
        return None, {}
    err = body.get("error")
    code = err.get("code") if isinstance(err, dict) else body.get("code")
    return code, {k: v for k, v in body.items() if k != "error"}


def base_env() -> dict[str, str]:
    """자식의 환경 — 처음부터 짓는다(셸의 토큰·프록시·PYTHONPATH 를 물려주지 않는다)."""
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp"), "LANG": "C.UTF-8",
           "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "MALLOC_ARENA_MAX": "4",
           "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"}
    if os.environ.get("TZ"):
        env["TZ"] = os.environ["TZ"]
    return env


SS = shutil.which("ss") or ""


# ════════════════════════════════════════════════════════════════════ 기록기
class Recorder:
    """대역 셋(게이트웨이·heax 싱크·포털 앞 기록기)이 받은 요청 — 길·경로·자격의 지문(원문은 남기지 않는다)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.rows: list[dict] = []

    def note(self, where: str, method: str, path: str, auth: str, **extra: Any) -> None:
        row = {"t": round(time.time(), 3), "where": where, "method": method, "path": path,
               "auth_sha": sha12(auth) if auth else None, "svc_pat": SERVICE_PAT in auth,
               "gw_svc": GATEWAY_SVC_TOKEN in auth, "jwt": jwt_claims(auth) if auth else None, **extra}
        with self.lock:
            self.rows.append(row)

    def of(self, where: str) -> list[dict]:
        with self.lock:
            return [r for r in self.rows if r["where"] == where]


# ════════════════════════════════════════════════════════════════════ 하네스 안의 대역 셋
def load_cards() -> list[dict]:
    root = AGENT_ROOT / "tests" / "fixtures" / "card_review" / "cards"
    cards = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.glob("*.json"))]
    if not cards:
        raise RuntimeError(f"카드 고정물이 없다 — {root}")
    return cards


_LONG_WORDS = ("간극", "압입", "볼트", "토크", "열팽창", "피로", "균열", "도금", "접합", "응력", "실링", "누설")


def long_cards() -> list[dict]:
    """20만 창 리허설(--long-cards)의 긴 카드 — 점검 카드 하나(30만 자 남짓 — 한 장 자리를 넘어 조각으로 돈다)와 배경 카드 넷
    (4.5만 자 — 훑기에 걸리면 카드 밖 호출의 반드시 전문이 창 한 번을 넘어 쪽으로 돈다). 문장은 '다.' 로 끝나 문단 · 문장 경계에서
    나뉜다. 엔진 고정물 카드(design_rule · data)를 본으로 id · 제목 · 절만 바꾼다(HWAXPortal docs/risk-200k W5)."""
    root = AGENT_ROOT / "tests" / "fixtures" / "card_review" / "cards"
    rule = json.loads((root / "design_rule.json").read_text(encoding="utf-8"))
    data = json.loads((root / "data.json").read_text(encoding="utf-8"))

    def grow(base: dict, seq: int, chars: int) -> dict:
        rng = random.Random(seq)
        paras, total = [], 0
        while total < chars:
            p = " ".join(" ".join(rng.choice(_LONG_WORDS) for _ in range(rng.randint(6, 14))) + " 이 변하면 응력이 달라진다."
                         for _ in range(rng.randint(4, 9)))
            paras.append(p)
            total += len(p) + 2
        text = "\n\n".join(paras)[:chars].rstrip()
        card = copy.deepcopy(base)
        card.update(id=f"DOC-CCT-MECH-2026-{900 + seq:010d}", seq=900 + seq, title=f"{base['title']} — 긴 카드 {seq}")
        half = len(text) // 2
        card["content"]["sections"] = [{"section_id": "1", "level": 1, "title": "본문 앞", "content_text": text[:half]},
                                       {"section_id": "2", "level": 1, "title": "본문 뒤", "content_text": text[half:]}]
        card["content"]["card"] = {**card["content"]["card"], "card_id": f"LONG-{seq}"}
        return card

    return [grow(rule, 1, 300_000)] + [grow(data, 1 + i, 45_000) for i in range(1, 5)]


def card_type(rec: dict) -> str:
    card = (rec.get("content") or {}).get("card") if isinstance(rec.get("content"), dict) else None
    if isinstance(card, dict) and card.get("type"):
        return str(card["type"])
    return next((str(t)[5:] for t in rec.get("tags") or () if str(t).startswith("type:")), "")


def gateway_app(rec: Recorder, catalog: dict[str, list[str]], records: dict[str, dict]):
    """에이전트 서버 MCP 설정이 가리키는 게이트웨이 대역 — 엔진 팩 빌더의 도구 셋(card_review.PACK_TOOLS).

    `catalog` 은 전문가 키 → 그 전문가 카드의 record id 다(빈 목록 = 카드 0장). 모르는 전문가는 'agent not found' 다.
    tests/test_card_review_pack.py 의 게이트웨이 대역과 같은 모양(FastMCP stateless · 경로 '/')이다."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("rehearsal-gateway", stateless_http=True, streamable_http_path="/")

    def summary(r: dict) -> dict:
        return {k: r.get(k) for k in ("id", "title", "data_type", "team", "group", "year", "doc_type", "tags", "agents", "summary")}

    @mcp.tool()
    async def get_agent_session(agent_type: str) -> dict:
        """역할."""
        rec.note("gateway_tool", "CALL", "get_agent_session", "", agent=agent_type)
        if agent_type not in catalog:
            raise ValueError(f"agent not found: {agent_type}")
        return {"agent_type": agent_type, "name": f"리허설 {agent_type}",
                "description": f"리허설 역할 — {agent_type} 의 관점으로 변경 단위를 카드와 맞대어 본다.",
                "system_prompt": "역할", "retrieval_config": {}, "response_config": {}, "sample_queries": [],
                "scope": {"common_tags": []}}

    @mcp.tool()
    async def list_records(agents: list[str] | None = None, doc_type: str = "", limit: int = 20, offset: int = 0) -> dict:
        """목록."""
        key = (agents or [""])[0]
        rec.note("gateway_tool", "CALL", "list_records", "", agent=key, offset=offset)
        ids = sorted(catalog.get(key, []), reverse=True)
        page = ids[offset: offset + limit]
        return {"total": len(ids), "count": len(page), "offset": offset, "items": [summary(records[i]) for i in page]}

    @mcp.tool()
    async def get_record(record_id: str) -> dict:
        """한 장."""
        rec.note("gateway_tool", "CALL", "get_record", "", record_id=record_id)
        if record_id not in records:
            raise ValueError(f"record not found: {record_id}")
        return records[record_id]

    inner = mcp.streamable_http_app()

    async def gate(scope, receive, send):
        if scope["type"] == "http":
            hdr = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            rec.note("gateway", scope.get("method", ""), scope.get("path", ""), hdr.get("authorization", ""))
        await inner(scope, receive, send)

    return gate


def sink_app(rec: Recorder, users: dict[str, dict]):
    """리스크 앱의 heax 신원 되묻기 대역 + 그 밖의 바깥 길(게이트웨이·AIDataHub) 싱크."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def any_path(request: Request):
        auth = request.headers.get("authorization", "")
        path = request.url.path
        rec.note("sink", request.method, path, auth)
        if path == "/api/v1/auth/me":
            user = users.get(auth[7:].strip()) if auth[:7].lower() == "bearer " else None
            if user is None:
                return JSONResponse({"detail": "invalid token"}, status_code=401)
            return JSONResponse(user)
        return JSONResponse({"error": "rehearsal_sink", "path": path}, status_code=503)

    return Starlette(routes=[Route("/{path:path}", any_path, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])])


_HOP = frozenset({"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
                  "transfer-encoding", "upgrade", "host", "content-length"})


def proxy_app(rec: Recorder, upstream: str):
    """리스크 앱 → 포털 사이의 투명 중계 — 본문·상태·SSE 바이트를 그대로 넘기고 요청마다 자격의 지문을 적는다.

    리스크 앱이 끊으면(재기동) 응답을 닫고 포털 쪽 연결도 닫는다(포털이 에이전트 쪽 연결을 닫아 엔진이 LLM 을 거두는 사슬 그대로)."""
    import httpx
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Route

    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(_app):
        state["client"] = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=None, write=60.0, pool=60.0),
                                            limits=httpx.Limits(max_connections=64), trust_env=False)
        try:
            yield
        finally:
            await state["client"].aclose()

    async def forward(request: Request):
        body = await request.body()
        auth = request.headers.get("authorization", "")
        rec.note("proxy", request.method, request.url.path, auth, bytes=len(body))
        headers = [(k, v) for k, v in request.headers.raw if k.decode("latin-1").lower() not in _HOP]
        url = upstream + request.url.path + (f"?{request.url.query}" if request.url.query else "")
        client = state["client"]
        try:
            r = await client.send(client.build_request(request.method, url, headers=headers, content=body), stream=True)
        except httpx.HTTPError as exc:
            return JSONResponse({"code": "portal_unreachable", "message": f"리허설 기록기가 포털에 닿지 못했다({type(exc).__name__})",
                                 "infra": True, "retryable": True}, status_code=502)
        out = {k: v for k, v in r.headers.items() if k.lower() not in _HOP}

        async def chunks():
            try:
                async for chunk in r.aiter_raw():
                    yield chunk
            finally:
                await r.aclose()

        return StreamingResponse(chunks(), status_code=r.status_code, headers=out)

    return Starlette(routes=[Route("/{path:path}", forward, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])],
                     lifespan=lifespan)


class ThreadServer:
    """하네스 안의 uvicorn(스레드) — 끝날 때 should_exit."""

    def __init__(self, name: str, app: Any, port: int) -> None:
        import uvicorn

        self.name, self.port = name, port
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, daemon=True, name=f"rehearsal-{name}")

    def start(self) -> None:
        assert_free(self.port)
        self.thread.start()
        wait_until(lambda: self.server.started, 20, f"{self.name}(:{self.port}) 기동", every=0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)


# ════════════════════════════════════════════════════════════════════ 자식 프로세스
class Proc:
    """이 하네스가 띄운 프로세스 하나 — 내릴 때는 이 PID 만 내린다(자식이라 거두기 전에는 PID 가 다시 쓰이지 않는다)."""

    def __init__(self, name: str, argv: list[str], *, cwd: Path, env: dict[str, str], logs: Path, port: int) -> None:
        self.name, self.argv, self.cwd, self.env, self.logs, self.port = name, argv, cwd, env, logs, port
        self.popen: subprocess.Popen | None = None
        self.n = 0
        self.history: list[dict] = []

    @property
    def pid(self) -> int | None:
        return self.popen.pid if self.popen is not None else None

    def alive(self) -> bool:
        return self.popen is not None and self.popen.poll() is None

    def start(self) -> None:
        assert_free(self.port)
        self.n += 1
        logf = open(self.logs / f"{self.name}-{self.n}.log", "ab")
        self.popen = subprocess.Popen(self.argv, cwd=str(self.cwd), env=self.env, stdout=logf, stderr=subprocess.STDOUT,
                                      stdin=subprocess.DEVNULL, start_new_session=True)
        logf.close()
        self.history.append({"event": "start", "pid": self.popen.pid, "t": round(time.time(), 3)})
        log(f"{self.name} 띄움 pid={self.popen.pid} :{self.port}")

    def stop(self, grace_s: float) -> dict:
        """SIGTERM → grace_s 기다림 → 아직 살아 있으면 SIGKILL(이 PID 만)."""
        if self.popen is None:
            return {"event": "stop", "pid": None}
        pid, t0 = self.popen.pid, time.monotonic()
        out = {"event": "stop", "pid": pid, "t": round(time.time(), 3), "killed": False}
        if self.popen.poll() is None:
            os.kill(pid, signal.SIGTERM)
            try:
                self.popen.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                os.kill(pid, signal.SIGKILL)
                out["killed"] = True
                self.popen.wait(timeout=30)
        out.update(rc=self.popen.returncode, took_s=round(time.monotonic() - t0, 2))
        self.history.append(out)
        log(f"{self.name} 내림 pid={pid} rc={out['rc']} killed={out['killed']} {out['took_s']}초")
        return out

    def crash(self) -> dict:
        """SIGKILL 하나(정리 없이 죽는 박스 — OOM·전원)."""
        pid = self.popen.pid
        os.kill(pid, signal.SIGKILL)
        self.popen.wait(timeout=30)
        out = {"event": "crash", "pid": pid, "t": round(time.time(), 3), "rc": self.popen.returncode}
        self.history.append(out)
        log(f"{self.name} SIGKILL pid={pid} rc={out['rc']}")
        return out


# ════════════════════════════════════════════════════════════════════ 실 저장소
def live_roots() -> list[Path]:
    """이 박스의 실 저장소가 있을 수 있는 자리(리포 루트에서 유도 — 심링크를 따라간다)."""
    cands = [PORTAL_BACKEND / "data", PORTAL_BACKEND / "secrets", AGENT_ROOT / "artifacts", REPO / "data",
             SIBLINGS / "HWAXRisk" / "data", SIBLINGS / "HEAXHub" / "var" / "app_data" / "hwax_risk"]
    art = AGENT_ROOT / "artifacts"
    if art.exists():
        cands.append(Path(os.path.realpath(art)).parent / "delib-jobs")
    out: list[Path] = []
    for c in cands:
        if c.exists():
            real = Path(os.path.realpath(c))
            if real not in out:
                out.append(real)
    return out


def snapshot_live(roots: list[Path]) -> dict[str, list[int]]:
    """실 저장소 파일의 (크기, mtime_ns) — 한 단 아래 디렉터리(심링크 포함)까지."""
    out: dict[str, list[int]] = {}

    def add(path: Path, depth: int) -> None:
        try:
            st = path.stat()
        except OSError:
            return
        if path.is_dir():
            out[str(Path(os.path.realpath(path))) + "/"] = [0, st.st_mtime_ns]
            if depth < 2:
                try:
                    kids = sorted(path.iterdir())
                except OSError:
                    return
                for kid in kids[:5000]:
                    add(kid, depth + 1)
        else:
            out[os.path.realpath(path)] = [st.st_size, st.st_mtime_ns]

    for root in roots:
        add(root, 0)
    return out


class FdWatch:
    """띄운 프로세스의 열린 파일을 몇 초마다 훑어 실 저장소(또는 /data)를 가리키는 것을 적는다 — 쓰기 모드면 위반이다."""

    def __init__(self, procs: Callable[[], list[Proc]], roots: list[Path], scratch: Path) -> None:
        self.procs, self.scratch = procs, str(scratch)
        self.prefixes = sorted({str(r) for r in roots} | {"/data/"})
        self.seen: dict[tuple, dict] = {}
        self.scans = 0
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="rehearsal-fdwatch")

    def _run(self) -> None:
        while not self.stop.wait(2.0):
            self.scan()

    def scan(self) -> None:
        self.scans += 1
        for p in self.procs():
            pid = p.pid
            if pid is None or not p.alive():
                continue
            fd_dir = Path(f"/proc/{pid}/fd")
            try:
                fds = list(fd_dir.iterdir())
            except OSError:
                continue
            for fd in fds:
                try:
                    target = os.readlink(fd)
                except OSError:
                    continue
                if not target.startswith("/") or target.startswith(self.scratch):
                    continue
                if not any(target.startswith(pre) for pre in self.prefixes):
                    continue
                mode = "?"
                try:
                    flags = next(int(line.split()[1], 8) for line in Path(f"/proc/{pid}/fdinfo/{fd.name}").read_text().splitlines()
                                 if line.startswith("flags:"))
                    mode = {0: "r", 1: "w", 2: "rw"}.get(flags & 3, "?")
                except (OSError, StopIteration, ValueError):
                    pass
                self.seen.setdefault((p.name, target, mode), {"proc": p.name, "pid": pid, "path": target, "mode": mode})


# ════════════════════════════════════════════════════════════════════ 원장(스크래치의 임시 DB 만 읽는다)
class RiskDb:
    def __init__(self, path: Path) -> None:
        self.path = path

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        con = sqlite3.connect(str(self.path), timeout=30)
        try:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA query_only = ON")
            return [dict(r) for r in con.execute(sql, args)]
        finally:
            con.close()

    def cells(self, key: str) -> list[dict]:
        return self.q("SELECT unit_id, agent_key, state, basis, charged, infra_streak, tries, error_code, error_class, run_id"
                      " FROM rr_review_cells WHERE target_key = ? ORDER BY agent_key, unit_seq", (key,))

    def by_state(self, key: str, agents: list[str] | None = None) -> dict[str, int]:
        rows = self.cells(key)
        return dict(Counter(r["state"] for r in rows if agents is None or r["agent_key"] in agents))

    def reviewed(self, key: str) -> int:
        return int(self.q("SELECT COUNT(*) AS n FROM rr_review_cells WHERE target_key = ? AND state = 'reviewed'", (key,))[0]["n"])

    def calls(self, job_id: str) -> list[dict]:
        return self.q("SELECT call_id, kind, variant, agent_key, unit_id, state, outcome_class, error_code, error_infra, seq,"
                      " started_at, duration_ms FROM rr_review_calls WHERE run_id = ? ORDER BY started_at, rowid", (job_id,))

    def job(self, job_id: str) -> dict:
        return self.q("SELECT id, state, hold_code, hold_until, hold_n, error, progress_json FROM rr_jobs WHERE id = ?", (job_id,))[0]

    def in_flight(self, key: str) -> dict:
        row = self.q("SELECT (SELECT COUNT(*) FROM rr_expert_reports WHERE target_key = ? AND state = 'running') AS heads,"
                     " (SELECT COUNT(*) FROM rr_review_cells WHERE target_key = ? AND state = 'running') AS cells", (key, key))[0]
        return {"heads": int(row["heads"]), "cells": int(row["cells"])}

    def heads(self, key: str) -> list[dict]:
        return self.q("SELECT agent_key, state, card_basis, pack_status, sweep_state, error, revision FROM rr_expert_reports"
                      " WHERE target_key = ? ORDER BY review_order, agent_key", (key,))


# ════════════════════════════════════════════════════════════════════ seed — 리스크 앱 venv 의 자식으로 돈다(app 을 여기서만 들인다)
def cmd_seed(args: argparse.Namespace) -> int:
    """review_rig 의 생산자로 임시 원장을 씨앗한다 — 합성 40건 쌍 → 실제 캡처·diff → create_target(flow='cells'). 대상 셋(본 잡 ·
    취소 · 폐기)이 각자 과제를 갖는다. 데이터 디렉터리의 knobs.env·secrets.env 는 run 이 먼저 적는다."""
    data_dir = Path(args.data_dir).resolve()
    os.environ["HWAXRISK_DATA_DIR"] = str(data_dir)      # app.config 는 import 때 읽는다 — 그 전에 정한다
    sys.path.insert(0, str(BACKEND))
    import app

    app_file = Path(app.__file__).resolve()
    if BACKEND not in app_file.parents:
        raise SystemExit(f"app 이 이 리포 밖에서 왔다 — {app_file}")
    from app import config, units
    from app.risk_store import close_store, get_store
    from tests.synth import review_rig as rig
    from tests.synth import scripts

    cfg = config.settings
    problems = []
    if cfg.data_dir.resolve() != data_dir:
        problems.append(f"data_dir {cfg.data_dir} ≠ {data_dir}")
    if not cfg.risk_review_enabled:
        problems.append("HWAXRISK_REVIEW_ENABLED 가 켜지지 않았다")
    for env_name, attr in KNOB_ATTRS.items():
        if getattr(cfg, attr) != rig.CAPS[attr]:
            problems.append(f"{env_name} {getattr(cfg, attr)} ≠ review_rig.CAPS {rig.CAPS[attr]}")
    if rig.SERVICE_PAT != SERVICE_PAT:
        problems.append("review_rig.SERVICE_PAT 이 바뀌었다")
    if problems:
        raise SystemExit("seed 전제가 다르다 — " + " · ".join(problems))
    store = get_store()
    targets = []
    for role, seed in (("main", None), ("cancel", scripts.SEED + 1), ("purge", scripts.SEED + 2)):
        key = rig.target(store, seed=seed)
        proj = store.query_one("SELECT p.id, p.code FROM rr_targets t JOIN rr_projects p ON p.id = t.project_id"
                               " WHERE t.target_key = ?", (key,))
        targets.append({"role": role, "target_key": key, "project_id": proj["id"], "code": proj["code"],
                        "units": len(units.load_units(store, key, reviewable_only=True))})
    out = {"owner": rig.OWNER, "roster": [dict(r) for r in rig.ROSTER], "seal": rig.SEAL,
           "background_only": rig.BACKGROUND_ONLY, "zero_cards": rig.ZERO_CARDS, "card_experts": list(rig.CARD_EXPERTS),
           "targets": targets, "app_file": str(app_file), "schema_version": store.schema_version(),
           "caps": {k: getattr(cfg, v) for k, v in KNOB_ATTRS.items()}}
    close_store()
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


# ════════════════════════════════════════════════════════════════════ run
class Rehearsal:
    def __init__(self, root: Path, args: argparse.Namespace) -> None:
        self.root, self.args = root, args
        self.logs = root / "logs"
        self.risk_data = root / "risk-data"
        self.agent_dir = root / "agent"
        self.portal_dir = root / "portal"
        for d in (self.logs, self.risk_data, self.agent_dir / "artifacts", self.agent_dir / "delib-jobs", self.agent_dir / "cwd",
                  self.portal_dir / "jwt", self.portal_dir / "upload"):
            d.mkdir(parents=True, exist_ok=True)
        self.agent_py = Path(args.agent_python or AGENT_ROOT / ".venv" / "bin" / "python")
        self.portal_py = Path(args.portal_python or PORTAL_BACKEND / ".venv" / "bin" / "python")
        self.risk_py = Path(sys.executable)
        self.rec = Recorder()
        self.procs: dict[str, Proc] = {}
        self.threads: list[ThreadServer] = []
        self.ev: dict[str, Any] = {"started_at": time.strftime("%Y-%m-%d %H:%M:%S"), "scratch": str(root), "checks": {},
                                   "notes": [], "repos": {}}
        self.web_token = "web-" + secrets.token_hex(16)
        self.admin_token = "adm-" + secrets.token_hex(16)
        self.gw_secret = secrets.token_hex(24)
        self.pat = ""
        self.llm_calls_before_reset = 0
        self.db = RiskDb(self.risk_data / "risk_review.db")
        self.http = None

    # ---------------------------------------------------------------- 공통
    def check(self, name: str, ok: bool, **evidence: Any) -> None:
        self.ev["checks"][name] = {"pass": bool(ok), **evidence}
        log(f"{'PASS' if ok else 'FAIL'} {name}")

    def note(self, text: str) -> None:
        self.ev["notes"].append(text)
        log(f"note — {text}")

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.ports[name]}"

    def risk(self, method: str, path: str, *, token: str | None = None, **kw: Any):
        headers = {"Authorization": f"Bearer {token or self.web_token}"}
        return self.http.request(method, self.url("risk") + path, headers=headers, **kw)

    def coverage(self, key: str) -> dict:
        r = self.risk("GET", f"/api/targets/{key}/coverage")
        r.raise_for_status()
        return r.json()

    def llm_stats(self) -> dict:
        return self.http.get(self.url("llm") + "/_stats").json()

    def llm_script(self, script: list) -> None:
        self.llm_calls_before_reset += int(self.llm_stats()["calls"])
        r = self.http.post(self.url("llm") + "/_script", json={"script": script})
        r.raise_for_status()

    # ---------------------------------------------------------------- 앞 점검
    def preflight(self) -> None:
        if not SS.startswith(("/usr/", "/bin/", "/sbin/")):
            raise RuntimeError(f"ss 가 시스템 경로가 아니다 — {SS!r}")
        for name, path in (("agent", AGENT_ROOT / "app.py"), ("portal", PORTAL_BACKEND / "app" / "main.py"),
                           ("llm_server", AGENT_ROOT / "tests" / "fakes" / "llm_server.py")):
            if not path.is_file():
                raise RuntimeError(f"형제 리포 파일이 없다({name}) — {path}")
        for name, py in (("agent", self.agent_py), ("portal", self.portal_py), ("risk", self.risk_py)):
            if not os.access(py, os.X_OK):
                raise RuntimeError(f"{name} 파이썬이 없다 — {py}")
        # 모듈이 실제로 어디서 오는지 — 실행하지 않고 find_spec 으로 본다(에이전트 app.py 는 import 만으로 ARTIFACT_DIR 를 만든다).
        probe = "import importlib.util as u, sys; sys.path.insert(0, sys.argv[1]); print(u.find_spec('app').origin)"
        want = {"agent": (self.agent_py, AGENT_ROOT, AGENT_ROOT / "app.py"),
                "portal": (self.portal_py, PORTAL_BACKEND, PORTAL_BACKEND / "app" / "__init__.py"),
                "risk": (self.risk_py, BACKEND, BACKEND / "app" / "__init__.py")}
        for name, (py, where, expect) in want.items():
            got = subprocess.run([str(py), "-c", probe, str(where)], cwd=str(where), env=base_env(), capture_output=True,
                                 text=True, timeout=60).stdout.strip()
            if Path(got).resolve() != expect.resolve():
                raise RuntimeError(f"{name} 의 app 모듈이 다른 곳에서 온다 — {got} (기대 {expect})")
        limit = resource.getrlimit(resource.RLIMIT_AS)[0]
        self.ev["rlimit_as"] = None if limit == resource.RLIM_INFINITY else limit
        if limit == resource.RLIM_INFINITY:
            self.note("가상 메모리 한도가 없다 — `ulimit -v 16000000` 아래에서 돌리길 권한다")
        for name, root in (("risk", REPO), ("agent", AGENT_ROOT), ("portal", PORTAL_ROOT)):
            head = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%h %s"], capture_output=True, text=True,
                                  timeout=20).stdout.strip()
            branch = subprocess.run(["git", "-C", str(root), "branch", "--show-current"], capture_output=True, text=True,
                                    timeout=20).stdout.strip()
            self.ev["repos"][name] = {"root": str(root), "branch": branch, "head": head[:120]}
        self.roots = live_roots()
        self.ev["live_roots"] = [str(r) for r in self.roots]

    # ---------------------------------------------------------------- 씨앗
    def seed(self) -> None:
        knobs = dict(KNOBS)
        if self.args.long_cards:
            # 긴 카드 모드는 카드 대조의 조각 · 쪽을 본다 — 근거 꾸러미 실호출(M3 C3-1)은 이 하네스의 게이트웨이 싱크가 물성 도구를
            # 503 으로 받아 그 단위가 여섯 번 다시 한 뒤(약 31분)에야 얼어 본 잡이 기한(1800초)을 넘긴다. 끄고 그 사실을 적는다.
            knobs["HWAXRISK_EVIDENCE_LIVE"] = "0"
            self.note("긴 카드 모드 — 근거 꾸러미 실호출을 껐다(HWAXRISK_EVIDENCE_LIVE=0 · 게이트웨이 싱크가 물성 도구를 503 으로 받는다)")
        (self.risk_data / "knobs.env").write_text("".join(f"{k}={v}\n" for k, v in knobs.items()), encoding="utf-8")
        sec = self.risk_data / "secrets.env"
        sec.write_text(f"HWAXRISK_PORTAL_PAT={SERVICE_PAT}\nHWAXRISK_HEAX_GATEWAY_SECRET={self.gw_secret}\n", encoding="utf-8")
        sec.chmod(0o600)
        out = self.root / "seed.json"
        env = {**base_env(), "HWAXRISK_DATA_DIR": str(self.risk_data)}
        r = subprocess.run([str(self.risk_py), str(Path(__file__).resolve()), "seed", "--data-dir", str(self.risk_data),
                            "--out", str(out)], cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=600)
        (self.logs / "seed.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        if r.returncode != 0:
            raise RuntimeError(f"seed 실패 rc={r.returncode} — {(r.stdout + r.stderr)[-1500:]}")
        self.seedinfo = json.loads(out.read_text(encoding="utf-8"))
        self.owner = self.seedinfo["owner"]
        self.targets = {t["role"]: t for t in self.seedinfo["targets"]}
        self.ev["seed"] = {k: self.seedinfo[k] for k in ("owner", "targets", "app_file", "schema_version", "caps")}
        log(f"seed — {[(t['role'], t['target_key'], t['units']) for t in self.seedinfo['targets']]}")

    # ---------------------------------------------------------------- 띄우기
    def start_all(self) -> None:
        self.ports = pick_ports(["llm", "gateway", "sink", "proxy", "agent", "portal", "risk", "closed"])
        self.ev["ports"] = dict(self.ports)
        log(f"포트 {self.ports}")
        closed = self.url("closed")
        cards = load_cards() + (long_cards() if self.args.long_cards else [])
        records = {c["id"]: c for c in cards}
        everything = sorted(records)
        background = sorted(c["id"] for c in cards if card_type(c) in BACKGROUND_TYPES)
        catalog: dict[str, list[str]] = {}
        for row in self.seedinfo["roster"]:
            key = row["key"]
            catalog[key] = ([] if key == self.seedinfo["zero_cards"] else background if key == self.seedinfo["background_only"]
                            else everything)
        self.ev["gateway_catalog"] = {k: len(v) for k, v in catalog.items()}

        users = {self.web_token: {"email": self.owner, "display_name": "리허설 검토자", "role": "user", "organization": "qa"},
                 self.admin_token: {"email": ADMIN_EMAIL, "display_name": "리허설 관리자", "role": "admin", "organization": "qa"}}
        for name, app in (("gateway", gateway_app(self.rec, catalog, records)), ("sink", sink_app(self.rec, users)),
                          ("proxy", proxy_app(self.rec, self.url("portal")))):
            server = ThreadServer(name, app, self.ports[name])
            server.start()
            self.threads.append(server)

        # 가짜 LLM — 에이전트 서버 시험 디렉터리의 llm_server.py(1M 창을 /v1/models 로 알린다).
        self.procs["llm"] = Proc("llm", [str(self.agent_py), str(AGENT_ROOT / "tests" / "fakes" / "llm_server.py"),
                                         "--port", str(self.ports["llm"]), "--ctx", str(self.args.ctx), "--model", MODEL,
                                         "--script", "oracle"],
                                 cwd=self.agent_dir / "cwd", env=base_env(), logs=self.logs, port=self.ports["llm"])
        # 에이전트 서버 — artifacts 는 /data 로 가는 심링크라 둘 다 스크래치로 돌린다(M2.md 4.6.2). 게이트웨이·AIDataHub 기본 주소(떠 있는
        # 9110·8001)는 닫힌 포트로 돌리고, MCP 설정은 게이트웨이 대역 하나만 서비스 토큰으로 가리킨다.
        mcp_json = self.agent_dir / "mcp_servers.json"
        mcp_json.write_text(json.dumps({"gateway": {"url": self.url("gateway") + "/", "transport": "streamable_http",
                                                    "headers": {"Authorization": f"Bearer {GATEWAY_SVC_TOKEN}"}}}), encoding="utf-8")
        agent_env = {**base_env(), "VLLM_BASE_URL": self.url("llm") + "/v1", "VLLM_MODEL": MODEL, "VLLM_API_KEY": "EMPTY",
                     "MCP_CONFIG": str(mcp_json), "ARTIFACT_DIR": str(self.agent_dir / "artifacts"),
                     "DELIB_JOB_DIR": str(self.agent_dir / "delib-jobs"), "GATEWAY_HTTP_BASE": closed, "AIDH_HTTP_BASE": closed}
        self.procs["agent"] = Proc("agent", [str(self.agent_py), "-m", "uvicorn", "app:app", "--app-dir", str(AGENT_ROOT),
                                             "--host", "127.0.0.1", "--port", str(self.ports["agent"])],
                                   cwd=self.agent_dir / "cwd", env=agent_env, logs=self.logs, port=self.ports["agent"])
        # 포털 — 저장소 다섯·JWT 키·업로드를 스크래치로, backend/.env 가 가리키는 바깥 길은 닫힌 포트·빈 값으로 덮는다. 프런트는 내지 않는다.
        pd = self.portal_dir
        portal_env = {**base_env(), "APP_ENV": "dev", "AUTH_PROVIDER": "mock", "PUBLIC_BASE_URL": self.url("portal"),
                      "FRONTEND_URL": self.url("portal"), "SERVE_FRONTEND": "false", "COOKIE_SECURE": "false",
                      "SESSION_SECRET": secrets.token_urlsafe(48),
                      "USER_STORE_PATH": str(pd / "users.sqlite"), "TOKEN_STORE_PATH": str(pd / "token_store.sqlite"),
                      "CONV_STORE_PATH": str(pd / "conversations.sqlite"), "PROCEDURES_STORE_PATH": str(pd / "procedures.sqlite"),
                      "AGENT_AUDIT_LOG_PATH": str(pd / "agent_audit.sqlite"), "JWT_KEYS_DIR": str(pd / "jwt"),
                      "JWT_AUTOGEN_KEYS": "true", "UPLOAD_STAGING_DIR": str(pd / "upload"),
                      "NGINX_ACCESS_LOG_PATH": str(pd / "nginx-access.log"),
                      "AGENT_SERVER_URL": self.url("agent"), "MCP_GATEWAY_URL": closed, "RA_BASE_URL": closed,
                      "STE_BASE_URL": closed, "EMBED_BASE_URL": closed, "STE_SSO_SECRET": "", "RA_SSO_SECRET": "",
                      "TESTSCOPE_SSO_SECRET": "", "TESTSCOPE_BASE_URL": "", "GATEWAY_SHARED_TOKEN": "",
                      "MAIL_BACKEND": "console", "LOCAL_AUTH_ENABLED": "true", "LOCAL_BOOTSTRAP_ADMINS": self.owner,
                      "PORTAL_ADMIN_EMAILS": ""}
        self.procs["portal"] = Proc("portal", [str(self.portal_py), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                               "--port", str(self.ports["portal"])],
                                    cwd=PORTAL_BACKEND, env=portal_env, logs=self.logs, port=self.ports["portal"])
        # 리스크 앱 — 포털은 기록기를 지나서, 그 밖의 바깥 길(heax·게이트웨이·AIDataHub)은 대역·싱크로.
        sink = self.url("sink")
        risk_env = {**base_env(), "HWAXRISK_DATA_DIR": str(self.risk_data), "HWAXRISK_PORTAL_BASE": self.url("proxy"),
                    "HWAXRISK_AGENT_URL": self.url("agent"), "HWAXRISK_HEAX_API": sink, "HWAXRISK_HEAX_BASE": sink,
                    "HWAXRISK_GATEWAY_MCP": sink + "/mcp", "HWAXRISK_AIDH_BASE": sink, "HOST": "127.0.0.1",
                    "PORT": str(self.ports["risk"]), "ROOT_PATH": ""}
        self.procs["risk"] = Proc("risk", [str(self.risk_py), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                                           "--port", str(self.ports["risk"])],
                                  cwd=BACKEND, env=risk_env, logs=self.logs, port=self.ports["risk"])

        self.fdwatch = FdWatch(lambda: list(self.procs.values()), self.roots, self.root)
        self.fdwatch.thread.start()
        for name in ("llm", "agent", "portal"):
            self.procs[name].start()
        self.wait_llm()
        self.wait_agent()
        self.wait_portal()
        self.start_risk()

    def wait_llm(self) -> None:
        wait_until(lambda: self.http.get(self.url("llm") + "/health").status_code == 200, 60, "가짜 LLM 기동")

    def wait_agent(self) -> dict:
        def ok():
            r = self.http.get(self.url("agent") + "/health", timeout=5)
            return r.json() if r.status_code == 200 else None
        return wait_until(ok, 120, "에이전트 서버 기동")

    def wait_portal(self) -> None:
        wait_until(lambda: self.http.get(self.url("portal") + "/health", timeout=5).status_code < 500, 120, "포털 기동")

    def start_risk(self) -> None:
        self.procs["risk"].start()
        wait_until(lambda: self.http.get(self.url("risk") + "/api/health", timeout=5).status_code == 200, 120, "리스크 앱 기동")
        cwd = os.readlink(f"/proc/{self.procs['risk'].pid}/cwd")
        if Path(cwd).resolve() != BACKEND.resolve():
            raise RuntimeError(f"리스크 앱 cwd 가 다르다 — {cwd}")

    # ---------------------------------------------------------------- 검토자(포털 계정·PAT → 리스크 앱 등록)
    def reviewer(self) -> None:
        import httpx

        portal = httpx.Client(base_url=self.url("portal"), timeout=30, trust_env=False)
        try:
            r = portal.post("/auth/local/signup", json={"email": self.owner, "name": "리허설 검토자", "password": REVIEWER_PASSWORD})
            r.raise_for_status()
            if r.json().get("status") != "active":
                raise RuntimeError(f"검토자 가입이 active 가 아니다 — {r.text[:200]}")
            portal.post("/auth/local/login", json={"email": self.owner, "password": REVIEWER_PASSWORD}).raise_for_status()
            csrf = portal.cookies.get("hwax_csrf")
            r = portal.post("/auth/pat", json={"name": "rehearsal-d", "scopes": ["read"], "ttl_days": 7},
                            headers={"X-CSRF-Token": csrf or ""})
            r.raise_for_status()
            self.pat = r.json()["token"]
        finally:
            portal.close()
        # 웹 설정 화면이 부르는 그 길 — PUT /api/me/portal-pat(앱이 포털 /agent/conversations 로 PAT 를 확인하고 Fernet 으로 얼린다).
        r = self.risk("PUT", "/api/me/portal-pat", json={"pat": self.pat})
        if r.status_code != 200 or not r.json().get("registered"):
            raise RuntimeError(f"PAT 등록 실패 {r.status_code} — {r.text[:300]}")
        self.ev["reviewer"] = {"email": self.owner, "pat_registered": r.json() | {"jti": "…"}}
        runtime = self.risk("GET", "/api/meta/runtime", token=self.admin_token).json()
        self.ev["runtime"] = {"knobs": runtime.get("knobs"), "schema_version": runtime.get("schema_version"),
                              "runner_lock": runtime.get("runner_lock")}

    # ---------------------------------------------------------------- MCP(게이트웨이처럼 위임 단언을 받아 /mcp 를 부른다)
    def mcp(self, tool: str, arguments: dict) -> dict:
        r = self.http.post(self.url("risk") + "/api/auth/sso",
                           headers={"x-heax-gateway-secret": self.gw_secret, "x-hwax-delegate-email": self.owner})
        r.raise_for_status()
        assertion = r.json()["access_token"]

        async def go() -> dict:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(self.url("risk") + "/mcp", headers={"x-heax-sso-assertion": assertion},
                                             timeout=60, sse_read_timeout=300) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    res = await session.call_tool(tool, arguments)
            if res.structuredContent is not None and not ("result" in res.structuredContent and len(res.structuredContent) == 1):
                return dict(res.structuredContent)
            text = "".join(getattr(c, "text", "") for c in res.content)
            try:
                value = json.loads(text)
            except ValueError:
                return {"raw": text[:500], "is_error": res.isError}
            return value if isinstance(value, dict) else {"value": value}

        return asyncio.run(go())

    # ---------------------------------------------------------------- 셈
    def conv_count(self) -> dict:
        r = self.http.get(self.url("portal") + "/agent/conversations", headers={"Authorization": f"Bearer {self.pat}"})
        listed = r.json() if r.status_code == 200 else {}
        n_list = listed.get("total")
        con = sqlite3.connect(str(self.portal_dir / "conversations.sqlite"), timeout=10)
        try:
            n_db = con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        finally:
            con.close()
        return {"rest_status": r.status_code, "rest_listed": n_list, "db_rows": n_db}

    def audit(self) -> dict:
        con = sqlite3.connect(str(self.portal_dir / "agent_audit.sqlite"), timeout=10)
        try:
            rows = con.execute("SELECT event, COALESCE(status, ''), COUNT(*) FROM agent_audit WHERE event LIKE 'card_review_%'"
                               " GROUP BY 1, 2 ORDER BY 1, 2").fetchall()
            codes = con.execute("SELECT event, meta FROM agent_audit WHERE event LIKE 'card_review_%' AND status <> 'ok'").fetchall()
            principals = con.execute("SELECT DISTINCT principal FROM agent_audit WHERE event LIKE 'card_review_%'").fetchall()
        finally:
            con.close()
        err_codes = Counter(f"{e}:{(json.loads(m or '{}') or {}).get('code')}" for e, m in codes)
        return {"by_event_status": {f"{e}|{s}": n for e, s, n in rows}, "non_ok_codes": dict(err_codes),
                "principals": [p for (p,) in principals]}

    def cell_map(self, key: str) -> dict[tuple, dict]:
        return {(c["agent_key"], c["unit_id"]): c for c in self.db.cells(key)}

    def charged_increases(self, before: dict[tuple, dict], after: dict[tuple, dict]) -> list[dict]:
        out = []
        for k, b in before.items():
            a = after.get(k)
            if a is not None and int(a["charged"]) > int(b["charged"]):
                out.append({"agent": k[0], "unit": k[1], "before": b["charged"], "after": a["charged"], "error_code": a["error_code"]})
        return out

    # ---------------------------------------------------------------- 점검 1
    def check_limits(self) -> None:
        r = self.http.get(self.url("portal") + "/agent/card-review/limits", headers={"Authorization": f"Bearer {self.pat}"})
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        health = self.http.get(self.url("agent") + "/health").json()
        cr = health.get("card_review") or {}
        self.check("1_limits_via_portal_relay",
                   r.status_code == 200 and body.get("ctx_tokens") == self.args.ctx and body.get("ctx_source") == "server",
                   http_status=r.status_code, api_rev=body.get("api_rev"), model=body.get("model"),
                   ctx_tokens=body.get("ctx_tokens"), ctx_source=body.get("ctx_source"), ctx_retrying=body.get("ctx_retrying"),
                   runnable=body.get("runnable"), k=(body.get("verdict") or {}).get("k"), limits_rev=body.get("limits_rev"),
                   gate=body.get("gate"), agent_health={"capabilities": health.get("capabilities"),
                                                        "review_active": health.get("review_active"),
                                                        "request_worst_s": cr.get("request_worst_s"), "limit": cr.get("limit")})

    def restart_risk(self, key: str, job_id: str, scope: list[str], *, crash: bool, need_reviewed: int) -> dict:
        """호출이 도는 동안 리스크 앱을 내렸다(SIGTERM 유예 뒤 KILL, 또는 곧장 SIGKILL) 같은 데이터 디렉터리로 다시 띄우고, reviewed 가
        다시 느는지·차감이 늘지 않는지·failed 가 없는지 본다."""
        wait_until(lambda: self.db.reviewed(key) >= need_reviewed and self.llm_stats()["active"] >= 2
                   or self.db.job(job_id)["state"] not in LIVE, 900,
                   f"reviewed {need_reviewed} 이상 · 호출 2건 이상 도는 중", every=0.3)
        if self.db.job(job_id)["state"] not in LIVE:
            return {"skipped": "잡이 먼저 끝났다"}
        before_map = self.cell_map(key)
        known = {c["call_id"] for c in self.db.calls(job_id)}
        before = {"by_state": self.db.by_state(key, scope), "coverage_by_state": self.coverage(key)["review"]["cells"]["by_state"],
                  "llm_active": self.llm_stats()["active"], "calls_running": sum(1 for c in self.db.calls(job_id) if c["state"] == "running")}
        stop = self.procs["risk"].crash() if crash else self.procs["risk"].stop(RISK_STOP_GRACE_S)
        after_down = {"by_state": self.db.by_state(key, scope), "in_flight": self.db.in_flight(key),
                      "calls_running": sum(1 for c in self.db.calls(job_id) if c["state"] == "running")}
        self.start_risk()
        restarted = time.time()
        base = before["by_state"].get("reviewed", 0)
        wait_until(lambda: self.db.reviewed(key) >= base + 2 or self.db.job(job_id)["state"] in ("completed", "failed", "cancelled"),
                   900, "재기동 뒤 reviewed 가 다시 늘기", every=1)
        after_map = self.cell_map(key)
        closed = [c for c in self.db.calls(job_id) if c["call_id"] not in known or c["state"] in ("aborted",)]
        aborted = [c for c in self.db.calls(job_id) if c["state"] == "aborted"]
        return {"mode": "sigkill" if crash else "sigterm", "before": before, "stop": stop, "after_down": after_down,
                "resumed_within_s": round(time.time() - restarted, 1),
                "after": {"by_state": self.db.by_state(key, scope),
                          "coverage_by_state": self.coverage(key)["review"]["cells"]["by_state"],
                          "job": {k: v for k, v in self.db.job(job_id).items() if k != "progress_json"}},
                "aborted_calls_so_far": dict(Counter(f"{c['outcome_class']}:{c['error_code']}" for c in aborted)),
                "new_or_aborted_calls": len(closed),
                "charged_increases": self.charged_increases(before_map, after_map),
                "failed_cells": [list(k) for k, c in after_map.items() if c["state"] == "failed"]}

    # ---------------------------------------------------------------- 본 잡(점검 2·5·6)
    def main_job(self) -> None:
        main = self.targets["main"]
        key = main["target_key"]
        si = self.seedinfo
        scope = [si["seal"], "mech-syn-0", "xd-syn-0", si["background_only"], si["zero_cards"]]
        self.scope_main = scope
        self.llm_script([{"behavior": "oracle", "delay": float(self.args.llm_delay)}])
        r = self.risk("POST", f"/api/targets/{key}/jobs", json={"mode": "reviews", "scope": {"agents": scope}, "consent": True})
        if r.status_code != 200:
            raise RuntimeError(f"본 잡을 만들지 못했다 {r.status_code} — {r.text[:400]}")
        job = r.json()
        job_id = job["job_id"]
        self.ev["main_job"] = {"create": {k: job.get(k) for k in ("job_id", "mode", "cells_total", "cells_in_scope", "experts_in_scope",
                                                                   "units", "calls_estimate", "credential", "credential_note")},
                               "scope": scope, "target_key": key}
        log(f"본 잡 {job_id} — 셀 {job.get('cells_in_scope')}/{job.get('cells_total')} 호출 추정 {job.get('calls_estimate')}")

        # ── 5a 리스크 앱 SIGTERM 재기동(허브 재배포처럼 — 정리하며 내린다) ───────────────
        self.risk_restart = {"sigterm": self.restart_risk(key, job_id, scope, crash=False, need_reviewed=3)}

        # ── 6 에이전트 서버 재기동 ─────────────────────────────────────────
        base2 = self.db.reviewed(key)
        if self.db.job(job_id)["state"] in LIVE:
            wait_until(lambda: self.llm_stats()["active"] >= 2 or self.db.job(job_id)["state"] not in LIVE, 600,
                       "호출 2건 이상 도는 중(에이전트 서버 재기동 앞)", every=0.3)
        before_map2 = self.cell_map(key)
        calls_before = self.db.calls(job_id)
        before2 = {"by_state": self.db.by_state(key, scope), "llm_active": self.llm_stats()["active"],
                   "job_state": self.db.job(job_id)["state"], "calls_running": sum(1 for c in calls_before if c["state"] == "running")}
        astop = self.procs["agent"].stop(AGENT_STOP_GRACE_S)
        killed_at = int(time.time())
        self.procs["agent"].start()
        self.wait_agent()
        restarted2 = time.time()
        wait_until(lambda: self.db.reviewed(key) >= base2 + 3 or self.db.job(job_id)["state"] in ("completed", "failed", "cancelled"),
                   1500, "에이전트 서버 재기동 뒤 reviewed 가 다시 늘기", every=1)
        self.agent_restart = {"before": before2, "stop": astop, "resumed_within_s": round(time.time() - restarted2, 1),
                              "_running_ids": [c["call_id"] for c in calls_before if c["state"] == "running"],
                              "_known_ids": [c["call_id"] for c in calls_before], "_killed_at": killed_at,
                              "charged_increases": self.charged_increases(before_map2, self.cell_map(key)),
                              "job_after": {k: v for k, v in self.db.job(job_id).items() if k != "progress_json"}}

        # ── 5b 리스크 앱 SIGKILL(정리 없이 죽음 — 재기동 복구가 running 호출을 aborted('restart') 로 닫는다) ──
        if self.db.job(job_id)["state"] in LIVE:
            self.risk_restart["sigkill"] = self.restart_risk(key, job_id, scope, crash=True, need_reviewed=self.db.reviewed(key) + 2)
        else:
            self.note("본 잡이 SIGKILL 재기동 전에 끝났다 — 5b 를 하지 못했다(--llm-delay 를 올린다)")

        # ── 끝까지 ───────────────────────────────────────────────────────
        wait_until(lambda: self.db.job(job_id)["state"] in ("completed", "failed", "cancelled"), 1800, "본 잡 끝", every=2)
        self.main_job_id = job_id

    # ---------------------------------------------------------------- 점검 8 — 긴 카드(--long-cards)
    def judge_long_cards(self) -> None:
        """긴 카드가 멈추지 않고 다 읽혔나(HWAXPortal docs/risk-200k W5) — 본 잡의 호출 결과에 조각(meta.chunked) 판정 · 훑기가 있고, 창이
        작으면(30만 토큰 밖) 쪽(meta.paged) 카드 밖 호출이 있다. 닫힌 칸의 커버리지에 놓침이 없고 불변식(G10 포함)이 빈다. 긴 점검 카드는
        카드 전문가의 검토 칸마다 실효 판정이 있다."""
        key, job_id = self.targets["main"]["target_key"], self.main_job_id
        rows = self.db.q("SELECT kind, variant, state, result_gz FROM rr_review_calls WHERE run_id = ? AND state = 'ok'"
                         " AND result_gz IS NOT NULL", (job_id,))
        metas = []
        for row in rows:
            try:
                metas.append((row["kind"], (json.loads(gzip.decompress(row["result_gz"])) or {}).get("meta") or {}))
            except (OSError, ValueError):
                continue
        chunked = Counter(kind for kind, m in metas if m.get("chunked"))
        paged = Counter(kind for kind, m in metas if m.get("paged"))
        cells = self.coverage(key).get("review", {}).get("cells", {})
        invariants = list(cells.get("invariants") or ())
        quality = (self.coverage(key).get("review", {}).get("quality") or {}).get("text") or ""
        proof = next((line for line in quality.split("\n") if line.startswith("[누락 0 증명]")), "")
        long_rid = long_cards()[0]["id"]
        judged = self.db.q("SELECT COUNT(DISTINCT unit_id || '|' || agent_key) AS n FROM rr_card_verdicts WHERE target_key = ?"
                           " AND record_id = ? AND is_effective = 1", (key, long_rid))[0]["n"]
        want_paged = self.args.ctx < 300_000
        ok = (chunked.get("verdict", 0) > 0 and chunked.get("sweep", 0) > 0 and (paged.get("offcard", 0) > 0 or not want_paged)
              and not invariants and " + 놓침 0 " in proof and judged > 0)
        self.check("8_long_cards_all_read", ok, ctx=self.args.ctx, results=len(metas), chunked=dict(chunked),
                   paged=dict(paged), invariants=invariants[:10], proof=proof, long_card_judged_cells=judged)

    # ---------------------------------------------------------------- 점검 2·5·6 판정
    def judge_main(self) -> None:
        si, key, job_id, scope = self.seedinfo, self.targets["main"]["target_key"], self.main_job_id, self.scope_main
        job = self.db.job(job_id)
        cells = self.db.cells(key)
        in_scope = [c for c in cells if c["agent_key"] in scope]
        out_scope = [c for c in cells if c["agent_key"] not in scope]
        basis = {a: sorted({c["basis"] or "-" for c in in_scope if c["agent_key"] == a}) for a in scope}
        want_basis = {a: ["role_only"] if a == si["zero_cards"] else ["background"] if a == si["background_only"] else ["cards"]
                      for a in scope}
        heads = {h["agent_key"]: h for h in self.db.heads(key)}
        cov = self.coverage(key)
        review = cov.get("review") or {}
        reports = {}
        for agent in scope:
            rr = self.risk("GET", f"/api/targets/{key}/experts/{agent}/report", params={"part": "summary"})
            body = rr.json() if rr.status_code == 200 else {"error": rr.text[:300]}
            mm = self.mcp("risk_get_expert_report", {"target_key": key, "agent_key": agent, "part": "summary"})
            page = body.get("page") or {}
            reports[agent] = {"rest_status": rr.status_code, "rest_pages_total": body.get("pages_total"),
                              "rest_page_chars": len(json.dumps(page, ensure_ascii=False)),
                              "rest_version": body.get("version", body.get("revision")),
                              "mcp_error": mm.get("error"), "mcp_pages_total": mm.get("pages_total"),
                              "mcp_page_chars": len(json.dumps(mm.get("page") or {}, ensure_ascii=False)),
                              "head_state": (heads.get(agent) or {}).get("state")}
        mcov = self.mcp("risk_get_coverage", {"target_key": key, "with_seats": False})
        calls = self.db.calls(job_id)
        reports_ok = all(r["rest_status"] == 200 and (r["rest_pages_total"] or 0) >= 1 and not r["mcp_error"]
                         and (r["mcp_pages_total"] or 0) >= 1 for r in reports.values())
        units_n = self.targets["main"]["units"]
        ok2 = (job["state"] == "completed" and not job["error"] and len(in_scope) == len(scope) * units_n
               and all(c["state"] == "reviewed" for c in in_scope) and all(c["state"] == "pending" for c in out_scope)
               and basis == want_basis and reports_ok and all((heads.get(a) or {}).get("state") == "ready" for a in scope))
        quality = review.get("quality") or {}
        self.check("2_every_cell_finishes", ok2,
                   job={k: v for k, v in job.items() if k != "progress_json"},
                   cells={"in_scope": len(in_scope), "in_scope_by_state": dict(Counter(c["state"] for c in in_scope)),
                          "out_of_scope_by_state": dict(Counter(c["state"] for c in out_scope)), "units": units_n,
                          "experts_in_scope": len(scope), "basis": basis,
                          "charged_total": sum(int(c["charged"]) for c in cells), "tries_total": sum(int(c["tries"]) for c in in_scope)},
                   calls={"total": len(calls), "by_kind_state": dict(Counter(f"{c['kind']}:{c['state']}" for c in calls)),
                          "non_ok": dict(Counter(f"{c['state']}:{c['outcome_class']}:{c['error_code']}" for c in calls if c["state"] != "ok"))},
                   heads={a: {k: (heads.get(a) or {}).get(k) for k in ("state", "card_basis", "pack_status", "sweep_state", "revision")}
                          for a in scope},
                   reports=reports,
                   review_block={"cells": review.get("cells"), "experts": review.get("experts"), "cards": review.get("cards"),
                                 "job": {k: (review.get("job") or {}).get(k) for k in ("state", "phase", "hold_code", "error", "progress")},
                                 "quality_title": quality.get("title"), "quality_text": (quality.get("text") or "")[:1500],
                                 "quality_out_of_bounds": quality.get("out_of_bounds"), "quality_unchecked": quality.get("unchecked")},
                   mcp_coverage_review_cells=(mcov.get("review") or {}).get("cells"), mcp_coverage_error=mcov.get("error"))

        rr = self.risk_restart
        legs = [leg for leg in rr.values() if "skipped" not in leg]
        ok5 = (bool(legs) and all(not leg["charged_increases"] and not leg["failed_cells"]
                                  and leg["after"]["by_state"].get("reviewed", 0) > leg["before"]["by_state"].get("reviewed", 0)
                                  for leg in legs)
               and job["state"] == "completed" and sum(int(c["charged"]) for c in in_scope) == 0)
        self.check("5_risk_app_restart_mid_run", ok5, legs_exercised=[leg.get("mode") for leg in legs], **rr)
        ar = dict(self.agent_restart)
        running_ids, known = set(ar.pop("_running_ids")), set(ar.pop("_known_ids"))
        ar.pop("_killed_at")
        # 끊긴 호출 = 내릴 때 돌던 호출(그 끝 상태) + 내린 뒤 새로 낸 호출 가운데 ok 가 아닌 것(에이전트 서버가 없는 사이 포털이 낸 것).
        interrupted = [c for c in calls if c["call_id"] in running_ids]
        # 리스크 앱 SIGKILL(5b)이 닫은 호출(aborted·restart)은 그 다리의 몫이라 여기서 뺀다.
        later_bad = [c for c in calls if c["call_id"] not in known and c["state"] not in ("ok", "running")
                     and c["error_code"] != "restart"]
        brief = ("kind", "state", "outcome_class", "error_code", "error_infra")
        ar["interrupted_calls"] = [{k: c[k] for k in brief} for c in interrupted]
        ar["failed_calls_after_kill"] = [{k: c[k] for k in brief} for c in later_bad]
        classes = {c["outcome_class"] for c in interrupted + later_bad}
        infra_only = classes <= {"infra", "wait"}
        ok6 = (bool(interrupted) and infra_only and not ar["charged_increases"] and job["state"] == "completed"
               and sum(int(c["charged"]) for c in in_scope) == 0)
        self.check("6_agent_server_restart_mid_run", ok6, interrupted_streams_seen=len(interrupted),
                   all_interrupted_classed_infra=infra_only, **ar)

    # ---------------------------------------------------------------- 점검 7 — 취소 · 루프 밖에서 닫힌 잡
    def cancel_path(self) -> None:
        si = self.seedinfo
        wait_until(lambda: self.llm_stats()["active"] == 0, 120, "가짜 LLM 이 한가해지기", every=0.5)
        self.llm_script([{"behavior": "oracle", "delay": float(self.args.cancel_delay)}])
        key = self.targets["cancel"]["target_key"]
        started = self.mcp("risk_start_job", {"target_key": key, "mode": "reviews", "scope": {"agents": [si["seal"], si["zero_cards"]]},
                                              "consent": True})
        job_id = started.get("job_id")
        if not job_id:
            raise RuntimeError(f"MCP risk_start_job 이 잡을 만들지 못했다 — {started}")
        wait_until(lambda: self.llm_stats()["active"] >= 1 and any(c["state"] == "running" for c in self.db.calls(job_id)), 300,
                   "취소 잡의 호출이 도는 중", every=0.3)
        inflight = self.db.in_flight(key)
        r = self.risk("POST", f"/api/jobs/{job_id}/cancel")
        cancel_resp = r.json()
        state_now = self.db.job(job_id)["state"]
        again = self.risk("POST", f"/api/targets/{key}/jobs", json={"mode": "reviews", "scope": {"agents": [si["seal"]]}, "consent": True})
        again_body = again.json()
        t0 = time.time()
        wait_until(lambda: self.db.job(job_id)["state"] == "cancelled", 300, "취소 잡이 cancelled", every=0.5)
        took = round(time.time() - t0, 1)
        calls = self.db.calls(job_id)
        cov_job = (self.coverage(key).get("review") or {}).get("job") or {}
        # 취소 중(cancelling)인 잡이 있는 동안의 새 잡은 409 다 — 지금 코드는 review_job_exists{state: cancelling} 로 답한다(잡이 아직 살아
        # 있다 — runner.LIVE_JOB_STATES). review_in_flight 는 잡이 루프 밖에서 닫혔는데 워커가 아직 쥔 경우다(아래 7b).
        ok_cancel = (cancel_resp.get("state") == "cancelling" and state_now == "cancelling" and again.status_code == 409
                     and app_error(again_body)[0] in ("review_job_exists", "review_in_flight"))
        cancel_ev = {"mcp_start": {k: started.get(k) for k in ("job_id", "mode", "cells_in_scope", "calls_estimate")},
                     "in_flight_at_cancel": inflight, "cancel_response": cancel_resp, "state_right_after": state_now,
                     "new_job_while_cancelling": {"status": again.status_code, "code": app_error(again_body)[0],
                                                  "detail": app_error(again_body)[1]},
                     "cancelled_after_s": took, "calls": dict(Counter(f"{c['state']}:{c['outcome_class']}:{c['error_code']}" for c in calls)),
                     "coverage_job": {k: cov_job.get(k) for k in ("state", "phase", "progress")}}

        # 7b — 과제 폐기(루프 밖에서 잡 행을 곧바로 cancelled 로 쓰는 길) 뒤 아직 도는 호출이 있으면 새 잡은 409 review_in_flight.
        wait_until(lambda: self.llm_stats()["active"] == 0, 120, "가짜 LLM 이 한가해지기", every=0.5)
        purge = self.targets["purge"]
        pkey = purge["target_key"]
        r = self.risk("POST", f"/api/targets/{pkey}/jobs", json={"mode": "reviews", "scope": {"agents": [si["seal"]]}, "consent": True})
        if r.status_code != 200:
            raise RuntimeError(f"폐기 대상 잡을 만들지 못했다 {r.status_code} — {r.text[:300]}")
        pjob = r.json()["job_id"]
        wait_until(lambda: self.llm_stats()["active"] >= 1 and any(c["state"] == "running" for c in self.db.calls(pjob)), 300,
                   "폐기 대상 잡의 호출이 도는 중", every=0.3)
        pr = self.risk("POST", f"/api/projects/{purge['project_id']}/purge", json={"code": purge["code"], "reason": "단계 D 리허설 — 루프 밖 닫힘"})
        p_state = self.db.job(pjob)["state"]
        inflight2 = self.db.in_flight(pkey)
        nj = self.risk("POST", f"/api/targets/{pkey}/jobs", json={"mode": "reviews", "scope": {"agents": [si["seal"]]}, "consent": True})
        nj_body = nj.json()
        wait_until(lambda: self.db.in_flight(pkey) == {"heads": 0, "cells": 0}, 300, "폐기 대상의 도는 호출이 0", every=0.5)
        purge_ev = {"purge_status": pr.status_code, "purge_db_layer": ((pr.json() or {}).get("purge_report") or {}).get("layers", {}).get("db") if pr.status_code == 200 else pr.text[:300],
                    "job_state_after_purge": p_state, "in_flight_after_purge": inflight2,
                    "new_job": {"status": nj.status_code, "code": app_error(nj_body)[0], "detail": app_error(nj_body)[1]},
                    "in_flight_later": self.db.in_flight(pkey)}
        ok_inflight = (nj.status_code == 409 and app_error(nj_body)[0] == "review_in_flight"
                       and purge_ev["in_flight_later"] == {"heads": 0, "cells": 0})
        self.check("7_cancel_and_review_in_flight", ok_cancel and ok_inflight, cancel=cancel_ev, purge_closed_outside_loop=purge_ev,
                   cancel_ok=ok_cancel, in_flight_ok=ok_inflight)

    # ---------------------------------------------------------------- 점검 3·4
    def judge_wire(self, conv_before: dict) -> None:
        proxy = self.rec.of("proxy")
        sink = self.rec.of("sink")
        gw = self.rec.of("gateway")
        user_sha = sha12(f"Bearer {self.pat}")
        cr_rows = [r for r in proxy if r["path"].startswith("/agent/card-review/")]
        stats = self.llm_stats()
        audit = self.audit()
        all_calls = self.db.q("SELECT state, COUNT(*) AS n FROM rr_review_calls GROUP BY state")
        ledger = {r["state"]: r["n"] for r in all_calls}
        run_start = sum(n for k, n in audit["by_event_status"].items() if k.startswith("card_review_run_start|"))
        gw_auth = Counter(("svc" if r["gw_svc"] else (r["jwt"] or {}).get("pat_name") or "other") + ":" +
                          str((r["jwt"] or {}).get("email")) for r in gw)
        proxy_auth = Counter("user_pat" if r["auth_sha"] == user_sha else ("service_pat" if r["svc_pat"] else
                             ("none" if r["auth_sha"] is None else "other")) for r in proxy)
        svc_hits = [r for r in self.rec.rows if r["svc_pat"] or r["gw_svc"]]
        llm_total = self.llm_calls_before_reset + int(stats["calls"])
        ok3 = (bool(cr_rows) and all(r["auth_sha"] == user_sha for r in cr_rows) and not svc_hits and run_start >= 1
               and llm_total >= ledger.get("ok", 0) and bool(gw) and all(not r["gw_svc"] for r in gw)
               and set(audit["principals"]) == {self.owner})
        self.check("3_real_wire_no_service_pat", ok3,
                   portal_audit=audit, portal_relay_requests=dict(Counter(f"{r['method']} {r['path']}" for r in cr_rows)),
                   proxy_auth=dict(proxy_auth), proxy_paths=dict(Counter(r["path"] for r in proxy)),
                   sink_requests=dict(Counter(f"{r['method']} {r['path']}" for r in sink)),
                   gateway_http_auth=dict(gw_auth), gateway_tool_calls=dict(Counter(r["path"] for r in self.rec.of("gateway_tool"))),
                   service_credential_hits=len(svc_hits), llm_calls_total=llm_total, llm_peak_last_script=stats.get("peak"),
                   risk_ledger_calls_by_state=ledger)
        conv_after = self.conv_count()
        self.check("4_zero_portal_conversations", conv_after["db_rows"] == conv_before["db_rows"]
                   and conv_after["rest_listed"] == conv_before["rest_listed"] and conv_before["rest_status"] == 200,
                   before=conv_before, after=conv_after)

    # ---------------------------------------------------------------- 내리기
    def stop_all(self) -> None:
        for name, grace in (("risk", RISK_STOP_GRACE_S), ("portal", 15), ("agent", 15), ("llm", 10)):
            p = self.procs.get(name)
            if p is not None and p.alive():
                try:
                    p.stop(grace)
                except Exception as exc:  # noqa: BLE001 — 하나가 실패해도 나머지를 내린다
                    self.note(f"{name} 내리기 실패 {exc!r}")
        for t in self.threads:
            try:
                t.stop()
            except Exception as exc:  # noqa: BLE001
                self.note(f"{t.name} 내리기 실패 {exc!r}")
        if getattr(self, "fdwatch", None) is not None:
            self.fdwatch.stop.set()
            self.fdwatch.thread.join(timeout=10)
        ports = getattr(self, "ports", {})
        still = {n: p for n, p in ports.items() if port_open(p) or p in ss_listening()}
        self.ev["shutdown"] = {"procs": {n: p.history for n, p in self.procs.items()},
                               "ports_still_open": still, "all_closed": not still}

    def judge_live(self, before: dict) -> None:
        after = snapshot_live(self.roots)
        changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        fds = list(self.fdwatch.seen.values()) if getattr(self, "fdwatch", None) else []
        writes = [f for f in fds if f["mode"] in ("w", "rw")]
        self.check("live_stores_untouched", not changed and not fds,
                   roots=[str(r) for r in self.roots], files_watched=len(before), changed=changed[:50],
                   changed_detail={p: {"before": before.get(p), "after": after.get(p)} for p in changed[:20]},
                   fd_scans=getattr(self.fdwatch, "scans", 0), fds_on_live_paths=fds, write_fds_on_live_paths=writes)

    def run(self) -> int:
        import logging

        import httpx

        for name in ("httpx", "mcp", "uvicorn"):
            logging.getLogger(name).setLevel(logging.WARNING)

        self.http = httpx.Client(timeout=60, trust_env=False)
        live_before: dict = {}
        try:
            self.preflight()
            live_before = snapshot_live(self.roots)
            self.seed()
            self.start_all()
            self.reviewer()
            self.check_limits()
            conv_before = self.conv_count()
            self.main_job()
            self.judge_main()
            if self.args.long_cards:
                self.judge_long_cards()
            self.cancel_path()
            self.judge_wire(conv_before)
        except BaseException as exc:  # noqa: BLE001 — 무엇이 터져도 띄운 것을 내리고 증거를 남긴다
            self.ev["error"] = {"type": type(exc).__name__, "message": str(exc)[:2000], "trace": traceback.format_exc()[-4000:]}
            log(f"중단 — {type(exc).__name__}: {exc}")
        finally:
            # 판정까지 못 간 단계의 날 증거도 남긴다.
            for name in ("risk_restart", "agent_restart"):
                if hasattr(self, name) and not any(k.startswith(("5_", "6_")) for k in self.ev["checks"]):
                    self.ev.setdefault("partial", {})[name] = getattr(self, name)
            self.stop_all()
            if hasattr(self, "roots"):
                self.judge_live(live_before)
            self.http.close()
            self.ev["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            (self.root / "evidence.json").write_text(json.dumps(self.ev, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        failed = [k for k, v in self.ev["checks"].items() if not v["pass"]]
        log(f"끝 — 통과 {len(self.ev['checks']) - len(failed)}/{len(self.ev['checks'])}, 실패 {failed}, 오류 {self.ev.get('error', {}).get('type')}")
        log(f"증거 — {self.root / 'evidence.json'}")
        return 0 if not failed and "error" not in self.ev and self.ev["shutdown"]["all_closed"] else 1


def cmd_run(args: argparse.Namespace) -> int:
    scratch = Path(args.scratch).resolve()
    forbidden = [REPO, AGENT_ROOT, PORTAL_ROOT, Path("/data")]
    if any(scratch == f or f in scratch.parents for f in forbidden):
        raise SystemExit(f"스크래치는 리포·/data 밖이어야 한다 — {scratch}")
    root = scratch / time.strftime("run-%Y%m%d-%H%M%S")
    root.mkdir(parents=True, exist_ok=False)
    log(f"스크래치 {root}")
    return Rehearsal(root, args).run()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M2 단계 D 배선 리허설 — 카드 대조 사슬을 임시 포트·임시 디렉터리에서 실제 HTTP/SSE 로 끝까지 돌린다")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="리허설 전체")
    run.add_argument("scratch", help="스크래치 디렉터리(그 아래 run-<시각>/ 을 만든다 — 리포·/data 밖)")
    run.add_argument("--agent-python", help="에이전트 서버 venv 파이썬(기본 ../HWAXAgentServer/.venv/bin/python)")
    run.add_argument("--portal-python", help="포털 venv 파이썬(기본 ../HWAXPortal/backend/.venv/bin/python)")
    run.add_argument("--llm-delay", type=float, default=4.0, help="본 잡의 가짜 LLM 호출 하나의 초(재기동 때 호출이 돌고 있게)")
    run.add_argument("--cancel-delay", type=float, default=12.0, help="취소·폐기 단계의 가짜 LLM 호출 하나의 초")
    run.add_argument("--ctx", type=int, default=CTX, help="가짜 LLM 의 창(토큰) — 20만이면 200000(HWAXPortal docs/risk-200k W5)")
    run.add_argument("--long-cards", action="store_true",
                     help="긴 카드(점검 30만 자 하나 · 배경 4.5만 자 넷)를 더하고 점검 8(조각 · 쪽 · 놓침 0)을 본다")
    seed = sub.add_parser("seed", help="(run 이 부른다) 임시 원장 씨앗")
    seed.add_argument("--data-dir", required=True)
    seed.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    return cmd_run(args) if args.cmd == "run" else cmd_seed(args)


if __name__ == "__main__":
    sys.exit(main())
