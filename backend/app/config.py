# 앱 설정 단일 소스 — Settings(plan §8.2.6, env 접두 HWAXRISK_)·데이터 경로 우선순위(HWAXRISK_DATA_DIR > HEAX_DATA_DIR > <리포>/data)·secrets.env 로드
from __future__ import annotations

import logging
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("hwax_risk.config")

# 리포 루트(backend/app/ 의 부모의 부모). 로컬 폴백 데이터 루트 <리포>/data 의 기준이다.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

APP_ID = "hwax_risk"
APP_NAME = "HWAX Risk Review"
APP_VERSION = "0.1.0"
# 확장자 .db 고정 — HEAXHub appdata-to-drive.sh 가 '**/*.db' 만 sqlite3 .backup 원자 스냅샷으로 교체한다(plan §5.2.5 (3)).
DB_FILENAME = "risk_review.db"
SECRETS_FILENAME = "secrets.env"
# secrets.env 에서 읽는 키 3종(plan §8.2.7). 값은 어디에도 로그하지 않는다.
SECRET_KEYS: tuple[str, ...] = ("HWAXRISK_PORTAL_PAT", "HWAXRISK_HEAX_SERVICE_PAT", "HWAXRISK_AIDH_API_KEY")

# 로스터 15 도메인(plan §0.6 실측 순서).
_DEFAULT_ROSTER_DOMAINS = "xd,sim,cam,rel,soc,disp,mech,pcb,rf,passive,pwr,sh,mem,std,material"
_DEFAULT_ECAD_DOMAINS = "pcb,pwr,rf,soc,passive,mem"


def resolve_data_dir(env: Mapping[str, str] | None = None) -> Path:
    """데이터 루트를 정한다 — HWAXRISK_DATA_DIR > HEAX_DATA_DIR(HEAX 러너가 bind 하는 영구 경로) > <리포>/data.

    SIF 배포에서는 rootfs 가 read-only 라 리포 안에 쓸 수 없으므로 HEAX_DATA_DIR 폴백이 필수다.
    """
    env = os.environ if env is None else env
    raw = env.get("HWAXRISK_DATA_DIR") or env.get("HEAX_DATA_DIR")
    return Path(raw) if raw else BASE_DIR / "data"


def ensure_data_dir(data_dir: Path) -> None:
    """mkdir -p 후 W_OK 검사. 쓸 수 없으면 기동을 막는다(조용한 폴백 금지, plan §5.2.5 (1))."""
    data_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(data_dir, os.W_OK):
        raise RuntimeError(f"데이터 루트에 쓸 수 없습니다: {data_dir} — HWAXRISK_DATA_DIR/HEAX_DATA_DIR 권한을 확인하세요.")


@dataclass(frozen=True)
class Settings:
    """plan §8.2.6 표의 필드. 속성명은 risk_*·소문자, env 는 HWAXRISK_<대문자>."""

    data_dir: Path
    db_path: Path
    root_path: str
    host: str
    port: int
    portal_base: str
    heax_api: str
    heax_base: str
    gateway_mcp: str
    aidh_base: str
    agent_url: str
    risk_roster_domains: tuple[str, ...]
    risk_ecad_domains: tuple[str, ...]
    risk_adjacency: str
    risk_concurrency: int
    risk_daily_panel_cap: int
    risk_default_close_level: str
    risk_carried_days: int
    risk_panel_llm_cap: int
    risk_promote_distinct_models: int
    adh_team: str | None
    adh_group: str | None
    app_id: str = APP_ID
    app_version: str = APP_VERSION


def _csv(raw: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """env 를 읽어 Settings 를 만든다. data_dir 은 없으면 생성하고, 쓸 수 없으면 기동을 막는다.

    HEAX 러너는 PORT·ROOT_PATH 를 env 로 준다. 요청 경로에서는 이 함수를 다시 부르지 말고 모듈 `settings` 를 쓴다.
    """
    env = os.environ if env is None else env
    data_dir = resolve_data_dir(env)
    ensure_data_dir(data_dir)
    return Settings(
        data_dir=data_dir,
        db_path=data_dir / DB_FILENAME,
        root_path=env.get("ROOT_PATH", ""),
        host=env.get("HOST", "127.0.0.1"),
        port=int(env.get("PORT", "8000")),
        portal_base=env.get("HWAXRISK_PORTAL_BASE", "http://127.0.0.1:5283"),
        heax_api=env.get("HWAXRISK_HEAX_API", "http://127.0.0.1:4040"),
        heax_base=env.get("HWAXRISK_HEAX_BASE", "http://127.0.0.1:4180"),
        gateway_mcp=env.get("HWAXRISK_GATEWAY_MCP", "http://127.0.0.1:9110/mcp"),
        aidh_base=env.get("HWAXRISK_AIDH_BASE", "http://127.0.0.1:8001"),
        agent_url=env.get("HWAXRISK_AGENT_URL", ""),
        risk_roster_domains=_csv(env.get("HWAXRISK_ROSTER_DOMAINS", _DEFAULT_ROSTER_DOMAINS)),
        risk_ecad_domains=_csv(env.get("HWAXRISK_ECAD_DOMAINS", _DEFAULT_ECAD_DOMAINS)),
        risk_adjacency=env.get("HWAXRISK_ADJACENCY", ""),
        risk_concurrency=int(env.get("HWAXRISK_CONCURRENCY", "2")),
        risk_daily_panel_cap=int(env.get("HWAXRISK_DAILY_PANEL_CAP", "24")),
        risk_default_close_level=env.get("HWAXRISK_DEFAULT_CLOSE_LEVEL", "C2"),
        risk_carried_days=int(env.get("HWAXRISK_CARRIED_DAYS", "90")),
        risk_panel_llm_cap=int(env.get("HWAXRISK_PANEL_LLM_CAP", "120")),
        risk_promote_distinct_models=int(env.get("HWAXRISK_PROMOTE_DISTINCT_MODELS", "1")),
        adh_team=env.get("HWAXRISK_ADH_TEAM") or None,
        adh_group=env.get("HWAXRISK_ADH_GROUP") or None,
    )


def load_secrets(data_dir: Path) -> dict[str, str]:
    """$DATA_DIR/secrets.env 의 SECRET_KEYS 3종을 읽는다(KEY=VALUE 줄, '#' 주석, 따옴표 없음 — plan §8.2.7).

    파일이 없으면 빈 dict. 모드가 0600 이 아니면 경고만 낸다. 값은 절대 로그하지 않는다.
    """
    path = data_dir / SECRETS_FILENAME
    if not path.is_file():
        return {}
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        log.warning("secrets.env 권한이 0600 이 아닙니다(%s): %o", path, mode)
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in SECRET_KEYS and value:
            out[key] = value
    return out


settings = load_settings()
