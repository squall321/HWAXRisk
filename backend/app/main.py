# FastAPI 진입점 — /api/health → /api 라우터 → MCP Route('/mcp') 이식 → frontend/dist StaticFiles('/') 순으로 등록, lifespan 은 plan §8.2.10 ①~⑦ 순서
from __future__ import annotations

import json
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, engine_client, identity
from app.errors import AppError
from app.mcp_server import mcp
from app.risk_store import close_store, get_store
from app.routes import PAT_MIN_REMAINING_S, router as api_router
from app.runner import RiskRunner

_INDEX_HTML = Path(__file__).resolve().parent / "static" / "index.html"
# Vite 빌드 산출물(frontend/dist). 있을 때만 '/' 에 마운트하고, 없으면 GET / 가 플레이스홀더를 준다(테스트는 dist 없이 통과).
_FRONTEND_DIST = config.BASE_DIR / "frontend" / "dist"
ORIGIN_FILENAME = "origin.json"


def _read_origin_hostname(data_dir: Path) -> str | None:
    """이전 기동이 남긴 origin.json 의 hostname(없으면 None)."""
    path = data_dir / ORIGIN_FILENAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("hostname")
    except (OSError, ValueError):
        return None


def _write_origin(data_dir: Path, hostname: str, schema_version: int) -> None:
    """origin.json 갱신 — {hostname, app_version, schema_version, written_at}(plan §5.2.5 (2))."""
    payload = {
        "hostname": hostname,
        "app_version": config.APP_VERSION,
        "schema_version": schema_version,
        "written_at": int(time.time()),
    }
    (data_dir / ORIGIN_FILENAME).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def check_credential_chain(settings) -> None:
    """자격 사슬 — 패널 자격 여유는 PAT 등록 하한보다 작아야 한다. 아니면 기동을 막는다.

    뒤집히면 등록 화면이 받아 준 PAT(남은 수명 ≥ 하한)가 패널에서는 수명 부족으로 거절된다 — 방금 등록한
    토큰으로 잡이 서비스 계정 시야로 도는데, 설정을 고치기 전에는 어떤 PAT 를 다시 발급해도 낫지 않는다.
    """
    margin = config.credential_margin_s(settings)
    if margin >= PAT_MIN_REMAINING_S:
        raise RuntimeError(
            f"패널 자격 여유 {margin}초가 PAT 등록 하한 {PAT_MIN_REMAINING_S}초 이상입니다 — 여유는 패널 벽시계"
            f"(HWAXRISK_PANEL_TIMEOUT_S {config.panel_timeout_s(settings)}) + 대기 + 600초로 정해집니다. 벽시계를"
            " 내리거나 HWAXRISK_CREDENTIAL_MARGIN_S 로 여유를 하한보다 작게 정하세요.")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = config.settings
    # ① 데이터 루트 결정·mkdir·W_OK(실패 = 예외로 기동 중단).
    config.ensure_data_dir(settings.data_dir)
    check_credential_chain(settings)
    hostname = socket.gethostname()
    prev_hostname = _read_origin_hostname(settings.data_dir)
    # ② RiskStore 생성·MIGRATIONS 적용·살림 표(get_store 가 open()+migrate() 를 수행한다).
    store = get_store()
    # ③ origin.json 갱신.
    _write_origin(settings.data_dir, hostname, store.schema_version())
    # ④ secrets.env·_user_credentials 유효성 — 직전 origin.json.hostname 이 현재 호스트와 다르면(이관 직후) 전부 무효(plan §5.2.5 (5)).
    box_match = prev_hostname in (None, hostname)
    secrets = config.load_secrets(settings.data_dir)
    app.state.store = store
    app.state.hostname = hostname
    app.state.box_match = box_match
    app.state.secrets_valid = box_match and all(k in secrets for k in config.SECRET_KEYS)
    # ⑤ identity 캐시 초기화.
    identity.reset_cache()
    # ⑥ 이식한 MCP Route 의 세션 매니저는 자동 기동되지 않으므로 직접 구동한다(MaterialTwinWeb·ThermalShockMCP 와 동일).
    # ⑦ 러너 스레드. 엔진은 주입식이라 러너 자체는 LLM 을 부르지 않는다(plan §6.7.1 (A) 경로).
    runner = RiskRunner(store, settings, engine=engine_client.build_engine(store, settings))
    app.state.runner = runner
    try:
        async with mcp.session_manager.run():
            runner.start()
            try:
                yield
            finally:
                runner.stop()
    finally:
        close_store()


app = FastAPI(
    title=config.APP_NAME,
    version=config.APP_VERSION,
    root_path=config.settings.root_path,
    lifespan=_lifespan,
)


@app.exception_handler(AppError)
async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


@app.get("/api/health")
def health() -> dict:
    """헬스체크 — HEAX 러너 health_check(path /api/health)가 읽는다. 형식 {ok, app_version, schema_version}(plan §5.2.5 (6)).

    경고가 있을 때만 `warnings[]` 를 더한다 — 지금은 `backup_unencrypted` 하나뿐이고, 그 상태에서도
    백업 자체는 막지 않는다(백업 없음이 더 나쁘다, plan §5.2.5 (3a) ③).
    """
    out = {"ok": True, "app_version": config.APP_VERSION, "schema_version": get_store().schema_version()}
    warnings = health_warnings()
    if warnings:
        out["warnings"] = warnings
    return out


def health_warnings() -> list[str]:
    """헬스 경고 코드 목록 — 백업 평문 사본(§5.2.5 (3a))과 사전 메이저 승급 후 재계산 미실행(§2.7.1)."""
    from app import routes  # noqa: PLC0415 — routes 는 main 을 import 하지 않는다.

    warnings: list[str] = []
    if not config.backup_key():
        warnings.append("backup_unencrypted")
    try:
        if routes.vocab_recompute_pending(get_store()):
            warnings.append("vocab_recompute_pending")
    except Exception:  # noqa: BLE001 — 헬스는 저장소 문제로 500 이 되지 않는다.
        pass
    return warnings


# 모든 /api/* 는 StaticFiles 마운트보다 먼저 등록한다.
app.include_router(api_router)

# MCP streamable HTTP — streamable_http_app() 의 실체는 Route('/mcp', StreamableHTTPASGIApp) 하나뿐이라 그 Route 를
# 메인 라우터에 그대로 이식하면 리다이렉트 없이 exact '/mcp' 로 매칭된다(MaterialTwinWeb 패턴).
# app.mount('/mcp', …) 는 Mount 특성상 슬래시 없는 /mcp 를 307 으로 돌려 MCP 클라이언트·게이트웨이가 못 따라가고(실측),
# mount('/', mcp_app) 는 아래 StaticFiles('/') 와 공존할 수 없어 둘 다 쓰지 않는다.
# session_manager 는 인스턴스에 캐시되고 run() 은 1회용이라 streamable_http_app() 호출 전에 리셋한다.
mcp._session_manager = None
for _route in mcp.streamable_http_app().routes:
    app.router.routes.append(_route)

# 정적 프런트엔드는 항상 마지막에 '/' 로 마운트한다(있을 때만).
if _FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
else:

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        """frontend/dist 가 없을 때의 플레이스홀더(P0 스캐폴드 안내)."""
        return FileResponse(_INDEX_HTML, media_type="text/html")
