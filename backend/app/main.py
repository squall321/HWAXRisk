# FastAPI 진입점 — /api/health → /api 라우터 → MCP Route('/mcp') 이식 → frontend/dist StaticFiles('/') 순으로 등록, lifespan 은 plan §8.2.10 ①~⑦ 순서
from __future__ import annotations

import json
import logging
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, engine_client, identity, review_quality, review_runner
from app.errors import AppError
from app.mcp_server import mcp
from app.risk_store import close_store, get_store
from app.routes import PAT_MIN_REMAINING_S, router as api_router
from app.runlock import RunnerLock
from app.runner import RiskRunner

log = logging.getLogger("hwax_risk.main")

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
            f"(HWAXRISK_PANEL_TIMEOUT_S {config.panel_timeout_s(settings)}) + 엔진 자리 대기 예산"
            f"(HWAXRISK_ENGINE_BUSY_MAX_WAIT_S {config.engine_busy_max_wait_s(settings)}) + 600초로 정해집니다."
            " 벽시계나 대기 예산을 내리거나 HWAXRISK_CREDENTIAL_MARGIN_S 로 여유를 하한보다 작게 정하세요."
            f" 손잡이를 적는 자리는 {config.KNOB_HOME}.")
    # 자동 갱신 문턱은 패널 자격 여유보다 커야 한다 — 아니면 자동 등록이 '아직 갱신할 때가 아니다' 라고 보는 PAT 로 패널이 수명
    # 부족으로 멈추고(서비스 계정으로 내려가지 않는다), 그 사람이 앱을 열어도 Claude 로 불러도 새 PAT 를 받지 않는다.
    renew = config.pat_renew_before_s(settings)
    if renew <= margin:
        raise RuntimeError(
            f"PAT 자동 갱신 문턱(HWAXRISK_PAT_RENEW_BEFORE_S {renew}초)이 패널 자격 여유 {margin}초 이하입니다 — 자동 등록이"
            " 갱신하지 않는 PAT 로 패널이 수명 부족으로 멈춥니다. 문턱을 여유보다 크게 올리세요(기본"
            f" {config.DEFAULT_PAT_RENEW_BEFORE_S}). 문턱을 적는 자리는 {config.REVIEW_KNOB_HOME} 또는 환경변수, 여유의 손잡이를"
            f" 적는 자리는 {config.KNOB_HOME}.")


def check_review_chain(settings) -> None:
    """카드 대조 검토 손잡이 사이의 관계(M2.md 4.5 — 시간 한도 사슬과 단위 크기) — 뒤집혀 있으면 기동하지 않고 고칠 손잡이를 말한다.

    - 프레임 사이 침묵 한도(HWAXRISK_REVIEW_READ_TIMEOUT_S) ≤ 호출 벽시계(HWAXRISK_REVIEW_CALL_TIMEOUT_S) — 안쪽이 먼저 걸려야
      죽은 연결이 '호출이 길다' 로 읽히지 않는다. 0 은 끈 것이라 견주지 않는다.
    - 검토 자격 여유(호출 벽시계 + 600) < PAT 등록 하한 — 아니면 방금 등록한 PAT 로도 검토 호출을 시작하지 못한다(검토는
      서비스 계정으로 내려가지 않는다, 사용자 결정 2026-10-12).
    - 시간 한도는 음수가 아니다 — 접근자(review_call_timeout_s)는 음수를 '끔'(0)으로 읽어 /api/meta/runtime 과 실제가 갈린다.
    - 단위 크기 — 목표 ≤ 상한, 작은 묶음 ≤ 상한(HWAXRISK_UNIT_TARGET_LINES · HWAXRISK_UNITS_SMALL_LINES ≤ HWAXRISK_UNIT_MAX_LINES).
      뒤집히면 모든 빌드가 불변식 U3(상한 넘는 단위)에 걸려 cells 로 열리는 대상이 하나도 없다(반대 검토 C2a RC-5·RC-6).
    """
    call_s = config.review_call_timeout_s(settings)
    read_s = config.review_read_timeout_s(settings)
    problems: list[str] = []
    for env_name, attr in (("HWAXRISK_REVIEW_CALL_TIMEOUT_S", "risk_review_call_timeout_s"),
                           ("HWAXRISK_REVIEW_READ_TIMEOUT_S", "risk_review_read_timeout_s")):
        raw = int(getattr(settings, attr, 0) or 0)
        if raw < 0:
            problems.append(f"{env_name} {raw}: 음수입니다 — 0(끔) 이상으로 적으세요.")
    max_lines = int(getattr(settings, "risk_unit_max_lines", 40))
    for env_name, attr in (("HWAXRISK_UNIT_TARGET_LINES", "risk_unit_target_lines"),
                           ("HWAXRISK_UNITS_SMALL_LINES", "risk_units_small_lines")):
        lines = int(getattr(settings, attr, 0))
        if lines > max_lines:
            problems.append(f"{env_name} {lines} > HWAXRISK_UNIT_MAX_LINES {max_lines}: 단위 상한보다 크면 상한을 넘는 단위가"
                            " 서서 모든 빌드가 불변식 U3 에 걸립니다. 상한 이하로 내리세요.")
    if call_s > 0 and read_s > call_s:
        problems.append(f"프레임 사이 침묵 한도(HWAXRISK_REVIEW_READ_TIMEOUT_S {read_s})가 호출 벽시계"
                        f"(HWAXRISK_REVIEW_CALL_TIMEOUT_S {call_s})보다 깁니다 — 침묵 한도를 벽시계 이하로 내리세요.")
    margin = config.review_credential_margin_s(settings)
    if margin >= PAT_MIN_REMAINING_S:
        problems.append(f"검토 자격 여유 {margin}초가 PAT 등록 하한 {PAT_MIN_REMAINING_S}초 이상입니다 — 여유는 호출 벽시계"
                        f"(HWAXRISK_REVIEW_CALL_TIMEOUT_S {call_s}) + 600초입니다. 벽시계를 내리세요.")
    if problems:
        raise RuntimeError(" ".join(problems) + f" 손잡이를 적는 자리는 {config.REVIEW_KNOB_HOME}.")


def warn_stream_limits_off(settings) -> None:
    """패널 스트림을 끊는 한도를 꺼 둔 박스에서, 기동 때 그 결과를 로그로 말한다. 막지는 않는다 — 0 은 허용된 값이다.

    패널 벽시계는 프레임이 올 때만 본다(engine_client._watched). 줄 사이 침묵 한도(HWAXRISK_ENGINE_READ_TIMEOUT_S)를
    0 으로 끄면, 닫히지 않은 채 조용해진 연결(상대가 끊었다는 말 없이 사라졌다)에서는 프레임도 읽기 타임아웃도
    오지 않는다 — 벽시계가 켜져 있어도 그 패널은 러너 자리와 타깃의 직렬 순서를 재기동 때까지 붙들고, 취소도
    닿지 않는다(취소 역시 프레임이 올 때 듣는다). 엔진은 제 한도를 끄면 기동 로그에 적는데 이 앱에는 그 말이
    없어, 끈 사람은 '벽시계가 있으니 괜찮다' 고 믿었다. 벽시계만 끈 박스는 조용히 지나간다 — 죽은 스트림은
    침묵 한도가 잡는다.
    """
    read_s = int(getattr(settings, "risk_engine_read_timeout_s", config.DEFAULT_ENGINE_READ_TIMEOUT_S) or 0)
    if read_s > 0:
        return
    wall_s = config.panel_timeout_s(settings)
    held = "러너 자리와 그 타깃의 직렬 순서를 재기동 때까지 붙든다"
    back = f"기본값은 {config.DEFAULT_ENGINE_READ_TIMEOUT_S} 이다. 손잡이를 적는 자리는 {config.KNOB_HOME}"
    if wall_s > 0:
        log.warning(
            "HWAXRISK_ENGINE_READ_TIMEOUT_S=0 — 줄 사이 침묵 한도가 꺼져 있다. 패널 벽시계(HWAXRISK_PANEL_TIMEOUT_S %s)는"
            " 프레임이 올 때만 보므로, 닫히지 않은 채 조용해진 연결의 패널은 %s. %s.", wall_s, held, back)
    else:
        log.error(
            "HWAXRISK_ENGINE_READ_TIMEOUT_S=0 · HWAXRISK_PANEL_TIMEOUT_S=0 — 패널을 끊는 한도가 하나도 없다. 조용해진"
            " 연결이든 끝없이 말하는 스트림이든 그 패널은 %s. %s.", held, back)


def warn_box_reasons(box: dict, data_dir) -> None:
    """박스 자격의 까닭을 기동 로그에 남긴다 — 필수 키 없음·cred.key 폴백은 WARNING, 선택 키 없음은 INFO(앱은 돈다).

    cred.key 폴백은 동작하므로 화면만 보면 아무 일도 없다. 그 파일을 모르고 옮기면 등록된 PAT 가 전부 풀리지 않는다 — 운영자가
    로그에서 '옮기라' 는 말과 그 명령을 보게 한다(값은 싣지 않는다). 화면 글은 경로를 싣지 않으므로(명령은 데이터 디렉터리에서
    돈다) 로그 줄이 그 디렉터리를 함께 적는다.
    """
    for reason in box.get("reasons") or ():
        level = logging.INFO if reason["code"] == "missing_optional" else logging.WARNING
        log.log(level, "박스 자격 %s — %s 고칠 곳(데이터 디렉터리 %s): %s", reason["code"], reason["message"], data_dir,
                reason["fix"])


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = config.settings
    # ① 데이터 루트 결정·mkdir·W_OK(실패 = 예외로 기동 중단).
    config.ensure_data_dir(settings.data_dir)
    check_credential_chain(settings)
    check_review_chain(settings)
    warn_stream_limits_off(settings)
    hostname = socket.gethostname()
    prev_hostname = _read_origin_hostname(settings.data_dir)
    # ①-b 러너 잠금 — 저장소를 열기 전에 잡아 본다(WP5a R2 · 반대 검토 P-12). 허브가 같은 데이터 디렉터리에 띄운 둘째는
    # 못 쥔다 — 기동은 하지만(REST·MCP) 러너 루프와 재기동 복구는 돌지 않는다. 이행은 migrate.lock 이 따로 줄 세운다.
    runner_lock = RunnerLock(settings.data_dir)
    runner_lock.acquire()
    app.state.runner_lock = runner_lock
    # ② RiskStore 생성·MIGRATIONS 적용·살림 표(get_store 가 open()+migrate() 를 수행한다).
    store = get_store()
    # ③ origin.json 갱신.
    _write_origin(settings.data_dir, hostname, store.schema_version())
    # ④ secrets.env·_user_credentials 유효성 — 직전 origin.json.hostname 이 현재 호스트와 다르면(이관 직후) 전부 무효(plan §5.2.5 (5)).
    box_match = prev_hostname in (None, hostname)
    app.state.store = store
    app.state.hostname = hostname
    app.state.box_match = box_match
    # 필수는 자격 암호화 키 하나다(env·path 로 준 키도 있는 것으로 센다) — 까닭은 GET /api/me 의 box.reasons 가 같은 판정으로 싣는다.
    box = config.box_assessment(box_match=box_match, data_dir=settings.data_dir)
    app.state.secrets_valid = box["secrets_valid"]
    warn_box_reasons(box, settings.data_dir)
    # ⑤ identity 캐시 초기화.
    identity.reset_cache()
    # ⑥ 이식한 MCP Route 의 세션 매니저는 자동 기동되지 않으므로 직접 구동한다(MaterialTwinWeb·ThermalShockMCP 와 동일).
    # ⑦ 러너 스레드. 엔진은 주입식이라 러너 자체는 LLM 을 부르지 않는다(plan §6.7.1 (A) 경로).
    # 검토 잡 진행판의 품질 칸 — 진행판이 60초마다 불러 progress_json.quality 에 넣는다(M2.md 5절 #16, S11).
    review_runner.QUALITY_HOOK = review_quality.progress_hook
    runner = RiskRunner(store, settings, engine=engine_client.build_engine(store, settings), lock=runner_lock,
                        review_engine=engine_client.build_review_engine(store, settings))
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
        runner_lock.release()


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

    저장소 락을 잡지 않는다(WP5a R1) — 허브는 45초마다 2초 탐침을 하고 넷 다 실패하면 같은 데이터 디렉터리에 서버를
    하나 더 띄운다. 반출·병합이 락을 몇 초 쥐는 동안 헬스가 그 뒤에 서면 그 일이 일어난다. 버전은 이행 때 담아 둔 값이다.
    """
    store = get_store()
    version = store.known_version if store.known_version is not None else store.schema_version()
    out = {"ok": True, "app_version": config.APP_VERSION, "schema_version": version}
    warnings = health_warnings()
    if warnings:
        out["warnings"] = warnings
    return out


# 저장소를 읽어야 하는 경고의 직전 값 — 락을 못 잡은 순간에는 이 값을 낸다('못 읽었다' 를 '경고 없음' 으로 바꾸지 않는다).
_LAST_STORE_WARNINGS: dict[str, bool] = {"vocab_recompute_pending": False}


def health_warnings() -> list[str]:
    """헬스 경고 코드 목록 — 백업 평문 사본(§5.2.5 (3a)) · 러너 잠금을 다른 프로세스가 쥠(runner_lock_held, WP5a R2) ·
    사전 메이저 승급 후 재계산 미실행(§2.7.1).

    사전 경고는 저장소를 읽는다 — 락을 기다리지 않고 잡아 보고(try_lock), 못 잡으면 직전 값을 낸다(반대 검토 P-11).
    """
    from app import routes  # noqa: PLC0415 — routes 는 main 을 import 하지 않는다.

    warnings: list[str] = []
    if not config.backup_key():
        warnings.append("backup_unencrypted")
    # 같은 데이터 디렉터리의 다른 프로세스가 러너 잠금을 쥐고 있다 — 이 프로세스는 REST·MCP 만 연다(WP5a R2).
    lock = getattr(app.state, "runner_lock", None)
    if lock is not None and not lock.held():
        warnings.append("runner_lock_held")
    try:
        store = get_store()
        with store.try_lock() as got:
            if got:
                _LAST_STORE_WARNINGS["vocab_recompute_pending"] = bool(routes.vocab_recompute_pending(store))
    except Exception:  # noqa: BLE001 — 헬스는 저장소 문제로 500 이 되지 않는다.
        pass
    if _LAST_STORE_WARNINGS["vocab_recompute_pending"]:
        warnings.append("vocab_recompute_pending")
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
