# FastAPI 진입점 — /api/health → /api 라우터 → MCP Route('/mcp') 이식 → frontend/dist StaticFiles('/') 순으로 등록, lifespan 에서 저장소·MCP 세션 기동
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.api import router as api_router
from app.errors import AppError
from app.mcp_server import mcp
from app.risk_store import close_store, get_store

_INDEX_HTML = Path(__file__).resolve().parent / "static" / "index.html"
# Vite 빌드 산출물(frontend/dist). 있을 때만 '/' 에 마운트하고, 없으면 GET / 가 플레이스홀더를 준다(테스트는 dist 없이 통과).
_FRONTEND_DIST = config.BASE_DIR / "frontend" / "dist"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # get_store() 가 open()+migrate() 를 수행한다. 이식한 MCP Route 의 세션 매니저는 자동 기동되지 않으므로
    # 직접 구동한다(MaterialTwinWeb·ThermalShockMCP 와 동일).
    get_store()
    try:
        async with mcp.session_manager.run():
            yield
    finally:
        close_store()


app = FastAPI(
    title=config.APP_NAME,
    version=config.APP_VERSION,
    root_path=config.settings.ROOT_PATH,
    lifespan=_lifespan,
)


@app.exception_handler(AppError)
async def _app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


@app.get("/api/health")
def health() -> dict:
    """헬스체크 — HEAX 러너 health_check(path /api/health)가 읽는다."""
    settings = config.settings
    return {
        "status": "ok",
        "app_id": settings.APP_ID,
        "version": settings.APP_VERSION,
        "schema_version": get_store().schema_version(),
        "data_dir": str(settings.DATA_DIR),
    }


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
