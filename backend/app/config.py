# 앱 설정 단일 소스 — 데이터 경로 우선순위(HWAX_RISK_DATA_DIR > HEAX_DATA_DIR > <리포>/data)·DB 파일·포트·root_path
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# 리포 루트(backend/app/ 의 부모의 부모). 로컬 폴백 데이터 루트 <리포>/data 와 런타임 자산 <리포>/docs 의 기준이다.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

APP_ID = "hwax_risk"
APP_NAME = "HWAX Risk Review"
APP_VERSION = "0.1.0"
# 확장자 .db 고정 — HEAXHub appdata-to-drive.sh 가 '**/*.db' 만 sqlite3 .backup 원자 스냅샷으로 교체한다(plan §5.2.5 (3)).
DB_FILENAME = "risk_review.db"


def resolve_data_dir(env: Mapping[str, str] | None = None) -> Path:
    """데이터 루트를 정한다 — HWAX_RISK_DATA_DIR > HEAX_DATA_DIR(HEAX 러너가 bind 하는 영구 경로) > <리포>/data.

    SIF 배포에서는 rootfs 가 read-only 라 리포 안에 쓸 수 없으므로 HEAX_DATA_DIR 폴백이 필수다.
    """
    env = os.environ if env is None else env
    raw = env.get("HWAX_RISK_DATA_DIR") or env.get("HEAX_DATA_DIR")
    return Path(raw) if raw else BASE_DIR / "data"


@dataclass(frozen=True)
class Settings:
    DATA_DIR: Path
    DB_PATH: Path
    ROOT_PATH: str
    HOST: str
    PORT: int
    APP_ID: str = APP_ID
    APP_VERSION: str = APP_VERSION


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """env 를 읽어 Settings 를 만든다. DATA_DIR 은 없으면 생성하고, 쓸 수 없으면 기동을 막는다(조용한 폴백 금지, plan §5.2.5 (1)).

    HEAX 러너는 PORT·ROOT_PATH 를 env 로 준다. 요청 경로에서는 이 함수를 다시 부르지 말고 모듈 `settings` 를 쓴다.
    """
    env = os.environ if env is None else env
    data_dir = resolve_data_dir(env)
    data_dir.mkdir(parents=True, exist_ok=True)
    if not os.access(data_dir, os.W_OK):
        raise RuntimeError(f"데이터 루트에 쓸 수 없습니다: {data_dir} — HWAX_RISK_DATA_DIR/HEAX_DATA_DIR 권한을 확인하세요.")
    return Settings(
        DATA_DIR=data_dir,
        DB_PATH=data_dir / DB_FILENAME,
        ROOT_PATH=env.get("ROOT_PATH", ""),
        HOST=env.get("HOST", "127.0.0.1"),
        PORT=int(env.get("PORT", "8000")),
    )


settings = load_settings()
