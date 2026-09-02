# 프런트엔드 API 클라이언트와 서버 라우트의 계약 대조 — 화면이 부르는 경로가 서버에 없으면 그 화면은 조용히 죽는다.
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import main as main_module
from app import routes

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
API_CLIENT = FRONTEND / "api" / "risk.api.ts"

# 경로 매개변수는 이름이 서로 달라도 같은 자리다 — `{}` 로 지워 비교한다.
_PARAM = re.compile(r"\{[^}]+\}")
# `request<T>("path")` · `` request<T>(`path/${x}`) `` 와 requestText 판.
_CALL = re.compile(
    r'request(?:Text)?<[^>]*>\(\s*([`"])([^`"]+)\1(?:\s*,\s*\{\s*method:\s*"(\w+)")?',
)
# 템플릿 보간 `${...}` 은 경로 매개변수 한 칸이다.
_INTERP = re.compile(r"\$\{[^}]+\}")


def _norm(path: str) -> str:
    return _PARAM.sub("{}", path)


def _server_routes() -> set[tuple[str, str]]:
    """`/api` 라우터 + main.py 가 직접 단 경로(`/api/health`)."""
    out: set[tuple[str, str]] = set()
    # 라우터는 prefix='/api' 로 선언돼 있고 클라이언트는 base 'api/' 뒤의 조각만 부른다 — 접두를 떼고 맞춘다.
    for source in (routes.router.routes, main_module.app.routes):
        for route in source:
            path = str(getattr(route, "path", ""))
            if not path.startswith("/api/"):
                continue
            for method in getattr(route, "methods", set()) or set():
                if method in ("HEAD", "OPTIONS"):
                    continue
                out.add((method, _norm(path[len("/api"):])))
    return out


def _served(call: tuple[str, str], server: set[tuple[str, str]]) -> bool:
    """서버 경로의 `{}` 자리는 클라이언트의 리터럴도 받는다 — `POST /jobs/{id}/{action}` 이 `.../pause` 를 받는다."""
    method, path = call
    parts = path.strip("/").split("/")
    for smethod, spath in server:
        if smethod != method:
            continue
        sparts = spath.strip("/").split("/")
        if len(sparts) != len(parts):
            continue
        if all(sp == "{}" or sp == p for sp, p in zip(sparts, parts)):
            return True
    return False


def _client_calls() -> list[tuple[str, str]]:
    text = API_CLIENT.read_text(encoding="utf-8")
    calls: list[tuple[str, str]] = []
    for quote, path, method in _CALL.findall(text):
        del quote
        calls.append(((method or "GET").upper(), "/" + _INTERP.sub("{}", path)))
    return calls


pytestmark = pytest.mark.skipif(not API_CLIENT.exists(), reason="프런트엔드 클라이언트가 없다")


def test_every_path_the_client_calls_exists_on_the_server():
    """클라이언트가 부르는 경로는 전부 서버에 있어야 한다.

    없으면 404 가 `NotReadyError` 로 접혀 '아직 준비 중' 배너가 되므로 화면은 조용히 빈 채로 남는다 —
    실제로 `GET /panels/{id}/transcript`(속기록)와 `GET /targets/{key}/seats`(좌석 목록)가 그렇게 죽어 있었다.
    """
    server = _server_routes()
    calls = _client_calls()
    assert calls, "클라이언트에서 호출을 하나도 못 읽었다 — 정규식이 낡았다"

    missing = sorted({c for c in calls if not _served(c, server)})
    assert missing == [], "서버에 없는 경로를 부른다: " + ", ".join(f"{m} {p}" for m, p in missing)


def test_the_client_covers_the_ui_facing_routes():
    """화면이 쓰는 축은 클라이언트에 다 있어야 한다 — 새 라우트를 넣고 클라이언트를 잊는 반대 방향의 표류를 막는다."""
    called = {path for _, path in _client_calls()}
    for path in ("/curation", "/curation/{}", "/panels/{}/transcript", "/targets/{}/seats",
                 "/targets/{}/coverage", "/targets/{}/registry", "/targets/{}/panels"):
        assert path in called, f"클라이언트가 {path} 를 부르지 않는다"
