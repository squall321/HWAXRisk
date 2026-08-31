# 앱 설정 단일 소스 — Settings(plan §8.2.6, env 접두 HWAXRISK_)·데이터 경로 우선순위(HWAXRISK_DATA_DIR > HEAX_DATA_DIR > <리포>/data)·secrets.env·cred.key 로드
from __future__ import annotations

import base64
import logging
import os
import secrets as secrets_module
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
# 사용자 포털 PAT 암복호(Fernet) 키의 로컬 개발 폴백 파일. 운영은 secrets.env 의 HWAXRISK_CRED_KEY 를 쓴다 —
# 암호문(risk_review.db)과 같은 디렉터리에 키를 두면 Drive tar 한 벌로 모든 사용자 PAT 가 함께 나간다(plan §8.2.7).
CRED_KEY_FILENAME = "cred.key"
# secrets.env 에서 읽는 키 5종(plan §8.2.6·§8.2.7). 값은 어디에도 로그하지 않는다.
# PORTAL_PAT 는 scopes ['read'] 전용이고, RA 객체·보고서 쓰기와 AIDataHub import 는 PORTAL_PAT_RW 만 쓴다(§5.1 원칙 10).
SECRET_KEYS: tuple[str, ...] = (
    "HWAXRISK_PORTAL_PAT", "HWAXRISK_PORTAL_PAT_RW", "HWAXRISK_HEAX_SERVICE_PAT",
    "HWAXRISK_AIDH_API_KEY", "HWAXRISK_CRED_KEY",
)

# 로스터 15 도메인(plan §0.6 실측 순서).
_DEFAULT_ROSTER_DOMAINS = "xd,sim,cam,rel,soc,disp,mech,pcb,rf,passive,pwr,sh,mem,std,material"
_DEFAULT_ECAD_DOMAINS = "pcb,pwr,rf,soc,passive,mem"
# mcad_absent 일 때 대표 1석만 남기고 deferred 로 내리는 도메인(plan §3.2.4).
_DEFAULT_MCAD_DOMAINS = "mech,cam,xd,disp,sh"


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
    risk_admin_roles: tuple[str, ...]
    risk_export_allowed_groups: tuple[str, ...]
    risk_export_retain_days: int
    risk_prior_include_human: bool
    risk_suspect_text_block: bool
    risk_recall_require_verified_actor: bool
    risk_neg_precedent_lines: int
    risk_cluster_dup_scan: bool
    risk_max_leaf: int
    risk_max_interfaces: int
    risk_snapshot_budget_s: int
    risk_mcad_domains: tuple[str, ...]
    risk_source_drift_block: bool
    risk_field_evidence_lines: int
    risk_brief_token_ttl_s: int
    risk_pat_require_read_only: bool
    risk_pat_revocation_poll_s: int
    adh_team: str | None
    adh_group: str | None
    app_id: str = APP_ID
    app_version: str = APP_VERSION


def _csv(raw: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in raw.split(",") if s.strip())


def _bool(raw: str, default: bool) -> bool:
    """env 불리언 — '1/true/yes/on' 참, '0/false/no/off' 거짓, 그 밖(빈 값 포함)은 기본값."""
    token = raw.strip().lower()
    if token in ("1", "true", "yes", "on"):
        return True
    if token in ("0", "false", "no", "off"):
        return False
    return default


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
        risk_admin_roles=_csv(env.get("HWAXRISK_ADMIN_ROLES", "admin")),
        risk_export_allowed_groups=_csv(env.get("HWAXRISK_EXPORT_ALLOWED_GROUPS", "")),
        risk_export_retain_days=int(env.get("HWAXRISK_EXPORT_RETAIN_DAYS", "30")),
        risk_prior_include_human=_bool(env.get("HWAXRISK_PRIOR_INCLUDE_HUMAN", ""), True),
        risk_suspect_text_block=_bool(env.get("HWAXRISK_SUSPECT_TEXT_BLOCK", ""), True),
        risk_recall_require_verified_actor=_bool(env.get("HWAXRISK_RECALL_REQUIRE_VERIFIED_ACTOR", ""), True),
        risk_neg_precedent_lines=int(env.get("HWAXRISK_NEG_PRECEDENT_LINES", "6")),
        risk_cluster_dup_scan=_bool(env.get("HWAXRISK_CLUSTER_DUP_SCAN", ""), True),
        risk_max_leaf=int(env.get("HWAXRISK_MAX_LEAF", "1500")),
        risk_max_interfaces=int(env.get("HWAXRISK_MAX_INTERFACES", "6000")),
        risk_snapshot_budget_s=int(env.get("HWAXRISK_SNAPSHOT_BUDGET_S", "180")),
        risk_mcad_domains=_csv(env.get("HWAXRISK_MCAD_DOMAINS", _DEFAULT_MCAD_DOMAINS)),
        risk_source_drift_block=_bool(env.get("HWAXRISK_SOURCE_DRIFT_BLOCK", ""), False),
        risk_field_evidence_lines=int(env.get("HWAXRISK_FIELD_EVIDENCE_LINES", "5")),
        risk_brief_token_ttl_s=int(env.get("HWAXRISK_BRIEF_TOKEN_TTL_S", "900")),
        risk_pat_require_read_only=_bool(env.get("HWAXRISK_PAT_REQUIRE_READ_ONLY", ""), True),
        risk_pat_revocation_poll_s=int(env.get("HWAXRISK_PAT_REVOCATION_POLL_S", "60")),
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


def cred_key_path(data_dir: Path | None = None) -> Path:
    """로컬 개발 폴백 키 파일 경로 — `$DATA_DIR/cred.key`(운영은 secrets.env 의 HWAXRISK_CRED_KEY, plan §8.2.7)."""
    return (settings.data_dir if data_dir is None else data_dir) / CRED_KEY_FILENAME


def cred_key_source(data_dir: Path | None = None, env: Mapping[str, str] | None = None) -> str | None:
    """자격 암호화 키가 어디서 오는지 — 'env' · 'path' · 'data_dir' · None(없음).

    'data_dir' 은 암호키가 암호문과 같은 디렉터리에 앉은 로컬 개발 폴백이고, 그때 `secrets_valid` 는 내려간다
    (HWAXRISK_CRED_KEY 가 SECRET_KEYS 에 있으므로 main.lifespan 의 all(...) 이 자동으로 False 가 된다).
    """
    env = os.environ if env is None else env
    root = settings.data_dir if data_dir is None else data_dir
    if (load_secrets(root).get("HWAXRISK_CRED_KEY") or env.get("HWAXRISK_CRED_KEY") or "").strip():
        return "env"
    raw_path = (env.get("HWAXRISK_CRED_KEY_PATH") or "").strip()
    if raw_path and Path(raw_path).is_file():
        return "path"
    return "data_dir" if cred_key_path(root).is_file() else None


def load_cred_key(data_dir: Path | None = None, *, create: bool = True) -> bytes | None:
    """Fernet 키를 읽는다 — ① secrets.env·env `HWAXRISK_CRED_KEY` ② `HWAXRISK_CRED_KEY_PATH` ③ `$DATA_DIR/cred.key`.

    ③ 은 로컬 개발 폴백이다(운영에서는 ① 을 쓴다 — 키가 암호문·백업과 같은 tar 에 실리지 않게 한다, plan §8.2.7).
    읽지도 만들지도 못하면 None 이고, 호출자(identity.encrypt_pat)는 422 `cred_key_absent` 로 등록을 거부한다 —
    평문 폴백은 없다. 키 값은 어디에도 로그하지 않는다.
    """
    root = settings.data_dir if data_dir is None else data_dir
    inline = (load_secrets(root).get("HWAXRISK_CRED_KEY") or os.environ.get("HWAXRISK_CRED_KEY") or "").strip()
    if inline:
        return inline.encode("ascii")
    raw_path = (os.environ.get("HWAXRISK_CRED_KEY_PATH") or "").strip()
    if raw_path:
        external = Path(raw_path)
        if external.is_file():
            return _read_cred_key(external)
        log.warning("HWAXRISK_CRED_KEY_PATH 가 가리키는 파일이 없습니다: %s", external)
    path = cred_key_path(data_dir)
    try:
        if path.is_file():
            return _read_cred_key(path)
        if not create:
            return None
        # Fernet 키 형식은 32 바이트의 urlsafe base64 다(cryptography Fernet.generate_key() 와 같은 산출).
        key = base64.urlsafe_b64encode(secrets_module.token_bytes(32))
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # 다른 스레드·프로세스가 방금 만들었다 — 그쪽 키가 정본이다.
            return _read_cred_key(path)
        with os.fdopen(fd, "wb") as fh:
            fh.write(key)
        log.info("자격 암호화 키를 새로 만들었습니다: %s (0600, 백업 등급은 secrets.env 와 같다)", path)
        return key
    except OSError as exc:
        log.warning("cred.key 를 읽거나 만들 수 없습니다(%s): %s", path, exc)
        return None


def _read_cred_key(path: Path) -> bytes | None:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        log.warning("cred.key 권한이 0600 이 아닙니다(%s): %o", path, mode)
    return path.read_bytes().strip() or None


settings = load_settings()
