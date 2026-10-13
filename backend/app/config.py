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
from typing import Any

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
# secrets.env 에서 읽는 키(plan §8.2.6·§8.2.7). 값은 어디에도 로그하지 않는다.
# 필수는 자격 암호화 키 하나다 — 없으면 사용자 PAT 를 등록·복호하지 못해 사람 자격으로 도는 일이 전부 멈춘다(리스크 앱 사람
# 자격 C-6). 나머지는 없으면 그 길만 닫히고 앱은 돈다(OPTIONAL_KEY_EFFECTS). 종전에는 다섯 키를 다 필수로 세어 쓰지 않는
# 키(RA 쓰기·AIDataHub — 보내는 쪽이 아직 배선되지 않았다, M4)까지 모자라다고 해 어느 박스든 경고가 떴다.
SECRET_KEYS: tuple[str, ...] = ("HWAXRISK_CRED_KEY",)
# 있으면 읽지만 없어도 기동을 막지 않는 키. PORTAL_PAT 는 scopes ['read'] 전용이고, RA 객체·보고서 쓰기와 AIDataHub import 는
# PORTAL_PAT_RW 만 쓴다(§5.1 원칙 10).
# HEAX_GATEWAY_SECRET: MCP 게이트웨이와만 나눠 갖는 이 앱 전용 값. 있어야 /auth/sso·/auth/portal-pat 가 열린다(없으면 404).
#   HEAXHub 의 gateway_shared_secret 을 재사용하지 않는다 — 그 값은 portal_auth 라우트에서 Caddy 가
#   모든 요청에 주입하므로, 같은 값을 쓰면 로그인한 아무나 남의 이메일로 단언을 발급받을 수 있다.
OPTIONAL_SECRET_KEYS: tuple[str, ...] = (
    "HWAXRISK_PORTAL_PAT", "HWAXRISK_PORTAL_PAT_RW", "HWAXRISK_HEAX_SERVICE_PAT", "HWAXRISK_AIDH_API_KEY",
    "HWAXRISK_BACKUP_KEY", "HWAXRISK_HEAX_GATEWAY_SECRET",
)
# 선택 키가 없으면 무엇이 안 되는가 — 설정 화면(GET /api/me 의 box.reasons missing_optional)이 그대로 싣는다.
OPTIONAL_KEY_EFFECTS: dict[str, str] = {
    "HWAXRISK_PORTAL_PAT": ("사람 자격이 없을 때의 짧은 조회(전문가 명단·현장 VOC·문헌 E10·캡처의 MCP 폴백)가 닫힌다 — 패널 잡은"
                            " 이 키를 쓰지 않는다(사람 PAT 만)."),
    "HWAXRISK_PORTAL_PAT_RW": "RA 쓰기 자격 — 보내는 쪽이 아직 배선되지 않아(M4) 지금은 없어도 달라지는 것이 없다.",
    "HWAXRISK_HEAX_SERVICE_PAT": ("StepForge REST 의 마지막 자격 — 웹 로그인 토큰도 게이트웨이 경유 본인 PAT 도 없는 캡처는 mcad 를"
                                  " MCP 폴백으로 읽어 G6 이 unit_unknown 으로 막힌다."),
    "HWAXRISK_AIDH_API_KEY": "AIDataHub 반입 키 — 반입하는 쪽이 아직 배선되지 않아(M4) 지금은 없어도 달라지는 것이 없다.",
    "HWAXRISK_BACKUP_KEY": "백업 암호화(age 공개키) — 없으면 백업이 평문이고 /api/health 에 backup_unencrypted 가 뜬다.",
    "HWAXRISK_HEAX_GATEWAY_SECRET": ("게이트웨이 사람별 위임 — 없으면 /api/auth/sso·/api/auth/portal-pat 가 404 라 Claude 로 오는"
                                     " 호출이 사람으로 보이지 않고(쓰기 도구 거절) PAT 자동 등록도 없다."),
}
# secrets.env 밖 환경변수로도 읽는 선택 키(backup_key·heax_gateway_secret 이 그렇게 읽는다). 나머지는 파일에서만 읽는다.
_ENV_READ_OPTIONAL_KEYS: tuple[str, ...] = ("HWAXRISK_BACKUP_KEY", "HWAXRISK_HEAX_GATEWAY_SECRET")

# 박스마다 다른 손잡이 파일(재설계 M2.md 4.5) — 데이터 디렉터리에 있어 재배포에 남고 추적 파일이 아니다. secrets.env 와 같은 꼴
# (KEY=VALUE 줄, '#' 주석)이고 비밀이 아니다. 아래 REVIEW_KNOBS 만 읽는다.
KNOBS_FILENAME = "knobs.env"

# 로스터 15 도메인(plan §0.6 실측 순서).
_DEFAULT_ROSTER_DOMAINS = "xd,sim,cam,rel,soc,disp,mech,pcb,rf,passive,pwr,sh,mem,std,material"
_DEFAULT_ECAD_DOMAINS = "pcb,pwr,rf,soc,passive,mem"
# mcad_absent 일 때 대표 1석만 남기고 deferred 로 내리는 도메인(plan §3.2.4).
_DEFAULT_MCAD_DOMAINS = "mech,cam,xd,disp,sh"

# ---------------------------------------------------------------- 시간 한도의 코드 기본값(초)
# 넉넉해야 하는 쪽이 코드다 — HEAXHub SIF 는 cleanenv 라 env 가 매니페스트 launch.env 로만 닿고, 거기 적지 않은
# 박스는 전부 이 값으로 돈다. 20석 안팎 패널이 공유 LLM 에 줄을 서면 패널 하나가 몇 시간을 가므로, 진행 중인 것을
# 자르지 않을 만큼 크게 잡고 안쪽 한도가 바깥보다 작게 둔다. 한쪽만 바꾸면 순서가 뒤집히니 이웃을 같이 본다.
#   누적 시간 — LLM 논리 호출 1회(엔진 2×DELIB_TIMEOUT_S+8 = 3608, 요청 상한이면 28808) < 패널 벽시계
#               < 자격 여유(벽시계 + 429 대기 예산 + 600) < PAT 등록 하한(routes.PAT_MIN_REMAINING_S 86400)
#   줄 사이 침묵 — 엔진 ping 15 < 포털 릴레이 AGENT_STREAM_IDLE_TIMEOUT_S(46800)
#               < nginx NGINX_AGENT_READ_TIMEOUT(50400) < 이 앱의 읽기 한도(아래 54000)
# 이 손잡이들을 적는 자리 — 기동 문구가 이 말을 붙인다. 만료 문구를 보고 셸에서 export 하거나 .env 에 적으면 아무 일도
# 일어나지 않는다(런처가 넘기는 것은 매니페스트의 launch.env 뿐이다). 등록 사본(HEAXHub integrations/hwax-risk)도 같이 고친다.
KNOB_HOME = "매니페스트(.portal/manifest.yaml) launch.env — SIF 가 cleanenv 라 셸 export·.env 는 닿지 않는다"
# 패널 1건의 벽시계(HWAXRISK_PANEL_TIMEOUT_S, 0 = 끔). 앱이 SSE 스트림에서 잰다 — 엔진에는 패널 전체를 재는 손잡이가
# 없다. 죽은 스트림은 침묵 한도가 잡으므로 이 값은 끝없이 말하는 스트림만 막으면 된다. 3라운드 패널은 LLM 단계가
# 직렬로 약 15번 이어져 단계마다 제 한도(1800초) 안에서 성공해도 7.5시간이다 — 그래서 12시간이다. 러너는 호출당
# timeout_s 를 싣지 않으므로, 엔진 박스의 DELIB_TIMEOUT_S 를 21596초 넘게 올리면(2×T+8 > 43200) 이 값도 올린다.
DEFAULT_PANEL_TIMEOUT_S = 43200
# 포털 /agent/chat SSE 의 줄 사이 침묵 한도(HWAXRISK_ENGINE_READ_TIMEOUT_S, 0 = 끔). 엔진이 15초마다 ping 을 흘리므로
# 살아 있는 심의에서는 걸리지 않는 마지막 그물이다. 침묵 한도 셋 중 가장 바깥이라 포털·nginx 보다 커야 안쪽의
# 구체적인 문구가 먼저 온다. 0 으로 끄면 닫히지 않은 채 조용해진 연결을 끊는 것이 없다 — 벽시계는 프레임이 올 때만
# 보므로 벽시계가 켜져 있어도 그렇다(기동 때 main.warn_stream_limits_off 가 그렇게 적는다).
DEFAULT_ENGINE_READ_TIMEOUT_S = 54000
# 포털이 429(동시 실행 자리 없음)를 줄 때 다시 묻는 간격(HWAXRISK_ENGINE_BUSY_WAIT_S).
DEFAULT_ENGINE_BUSY_WAIT_S = 30
# 429 를 기다리는 총 예산의 기본값(HWAXRISK_ENGINE_BUSY_MAX_WAIT_S). 429 는 빠르고 분명한 답이라 그것을 기다리는 것은
# 멈춤이 아니다 — 심의가 SSE 자리를 몇 시간씩 쥐므로 종전의 30초 × 10회(5분)로는 모자랐다. 자격 여유는 이 예산을
# 그대로 429 몫으로 잡는다(credential_margin_s) — 종전에는 러너의 대기(횟수 리터럴)와 여유의 몫(이 상수)이 따로
# 적혀 있어, 한쪽만 늘리면 기다리는 사이 PAT 가 만료될 수 있었다.
ENGINE_BUSY_ALLOWANCE_S = 3600
# 자격 여유에 얹는 고정 여분(대화 생성·마지막 저장).
CREDENTIAL_SLACK_S = 600
# 패널 전 포털 대화 생성 호출(HWAXRISK_PORTAL_CALL_TIMEOUT_S). 죽은 포털은 connect 10초가 잡는다 — 이 값은 느린
# 응답을 기다리는 몫이고, 놓치면 그 패널의 발언이 포털에 남지 않는다.
DEFAULT_PORTAL_CALL_TIMEOUT_S = 30
# 스냅샷 소스 호출 1건의 응답 침묵 한도(HWAXRISK_SOURCE_CALL_TIMEOUT_S) — 게이트웨이 MCP 도구와 소스 앱 REST GET.
DEFAULT_SOURCE_CALL_TIMEOUT_S = 120
# 패널 시작 때의 E10 필드 근거 호출(get_top_issues·search_scholar) 1건의 벽시계 기한(HWAXRISK_FIELD_TIMEOUT_S).
# 침묵 한도가 아니라 기한이다 — 게이트웨이가 15초마다 ping 을 흘려 15초를 넘는 침묵 한도는 호출 길이를 자르지 못한다
# (ra_client.McpHttpClient 가 줄마다 경과를 본다, 넘겨 듣는 폭은 ping 한 칸). 5초 리터럴이던 동안 부하 걸린 박스의
# 문헌 검색이 그 줄을 놓치면 몇 시간짜리 패널이 필드 근거 없이 돌았다. 브리프 한 번의 최악은 도구 지도 10초 +
# 4×(20+15) = 150초라 MCP 길의 risk_get_brief(게이트웨이 600초) 안에 든다.
DEFAULT_FIELD_TIMEOUT_S = 20
# 타깃을 열 때의 전문가 명단 조회 전체(recommend_agents 1 + 도메인마다 list_agents)의 벽시계 기한
# (HWAXRISK_ROSTER_DEADLINE_S). 이 조회는 nginx /apps/(proxy_read_timeout 600초, 포털 시험이 고정) 안의 동기 요청이다 —
# 넘겨 듣는 폭(게이트웨이 ping 한 칸 15초)을 더해도 600 보다 작아야, 프록시가 빈 504 를 내기 전에 앱이 받은 만큼으로
# 답한다. 호출당 침묵 한도(HWAXRISK_SOURCE_CALL_TIMEOUT_S)는 ping 이 되감아 호출 길이를 자르지 못한다 — 게이트웨이
# 호출 한도가 600초가 된 뒤로는 호출 하나가 프록시 한도와 같은 길이까지 간다.
DEFAULT_ROSTER_DEADLINE_S = 540

# ---------------------------------------------------------------- 카드 대조 검토의 손잡이(재설계 M2.md 4.5 — 전부 선택)
# 순서는 환경변수 > $DATA_DIR/knobs.env > 코드 기본값이다. 매니페스트 launch.env 에는 적지 않는다 — 거기 적으면 dev·cae00 이 같이
# 바뀐다(켜기 스위치는 박스마다 켠다, P-07). 기동 때 한 번 읽는다 — 파일을 고친 뒤에는 앱을 다시 띄운다. GET /api/meta/runtime 이
# 값과 출처를 보인다.
REVIEW_KNOB_HOME = "$DATA_DIR/knobs.env(박스마다 — 데이터 디렉터리라 재배포에 남는다, 고친 뒤 앱을 다시 띄운다)"
# 호출 하나의 벽시계(HWAXRISK_REVIEW_CALL_TIMEOUT_S, 0 = 끔). 엔진의 요청 최악(약 10,824초)보다 길어야 한다.
DEFAULT_REVIEW_CALL_TIMEOUT_S = 18000


@dataclass(frozen=True)
class Knob:
    """검토 손잡이 하나 — 환경변수 이름 · Settings 속성 · 코드 기본값 · 형(int|bool) · 정수의 하한(그 밑은 기동을 막는다)."""

    env: str
    attr: str
    default: int | bool
    kind: str = "int"
    minimum: int = 0


REVIEW_KNOBS: tuple[Knob, ...] = (
    Knob("HWAXRISK_REVIEW_ENABLED", "risk_review_enabled", False, "bool"),   # 새 흐름(flow='cells')의 스위치
    Knob("HWAXRISK_UNIT_TARGET_LINES", "risk_unit_target_lines", 20, minimum=1),   # 검토 단위 크기(줄 수) — 글자 상한은 없다
    Knob("HWAXRISK_UNIT_MAX_LINES", "risk_unit_max_lines", 40, minimum=1),
    Knob("HWAXRISK_UNITS_SMALL_LINES", "risk_units_small_lines", 15, minimum=1),
    Knob("HWAXRISK_UNITS_MAX", "risk_units_max", 60, minimum=1),
    Knob("HWAXRISK_REVIEW_CONCURRENCY", "risk_review_concurrency", 4, minimum=1),   # 앱의 검토 워커 수
    Knob("HWAXRISK_REVIEW_CALL_TIMEOUT_S", "risk_review_call_timeout_s", DEFAULT_REVIEW_CALL_TIMEOUT_S),  # 0 = 끔
    Knob("HWAXRISK_REVIEW_READ_TIMEOUT_S", "risk_review_read_timeout_s", 300),  # 프레임 사이 침묵 한도(엔진 ping 15초), 0 = 끔
    Knob("HWAXRISK_REVIEW_MAX_CHARGED", "risk_review_max_charged", 2, minimum=1),   # 셀의 내용 탓 실패 한도
    Knob("HWAXRISK_REVIEW_CONSENT_CALLS", "risk_review_consent_calls", 1500),  # 동의가 필요한 호출 추정
    Knob("HWAXRISK_REVIEW_MAX_CALLS", "risk_review_max_calls", 30000, minimum=1),   # 넘으면 거절하는 상한
)
# 손잡이 불리언의 낱말 — 그 밖의 값은 기동을 막는다(다른 스위치의 _bool 처럼 기본값으로 돌지 않는다).
_KNOB_TRUE = ("1", "true", "yes", "on")
_KNOB_FALSE = ("0", "false", "no", "off")


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
    # SSO 로 발급하는 신원 단언의 수명(초). 짧게 둔다 — 저장하지 않는 무상태 토큰이라 회수가 없다.
    sso_ttl_s: int
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
    risk_panel_timeout_s: int
    risk_engine_read_timeout_s: int
    # 0 이면 벽시계에서 유도한다(credential_margin_s).
    risk_credential_margin_s: int
    risk_portal_call_timeout_s: int
    risk_source_call_timeout_s: int
    risk_engine_busy_wait_s: int
    risk_engine_busy_max_wait_s: int
    risk_field_timeout_s: int
    risk_roster_deadline_s: int
    adh_team: str | None
    adh_group: str | None
    app_id: str = APP_ID
    app_version: str = APP_VERSION
    # 카드 대조 검토 손잡이(REVIEW_KNOBS) — 기본값은 표의 코드 기본값과 같다. knob_sources 는 (환경변수 이름, 출처) 쌍이다.
    risk_review_enabled: bool = False
    risk_unit_target_lines: int = 20
    risk_unit_max_lines: int = 40
    risk_units_small_lines: int = 15
    risk_units_max: int = 60
    risk_review_concurrency: int = 4
    risk_review_call_timeout_s: int = DEFAULT_REVIEW_CALL_TIMEOUT_S
    risk_review_read_timeout_s: int = 300
    risk_review_max_charged: int = 2
    risk_review_consent_calls: int = 1500
    risk_review_max_calls: int = 30000
    knob_sources: tuple[tuple[str, str], ...] = ()


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
    knob_values, knob_sources = load_review_knobs(data_dir, env)
    return Settings(
        **knob_values,
        knob_sources=knob_sources,
        data_dir=data_dir,
        db_path=data_dir / DB_FILENAME,
        root_path=env.get("ROOT_PATH", ""),
        host=env.get("HOST", "127.0.0.1"),
        port=int(env.get("PORT", "8000")),
        portal_base=env.get("HWAXRISK_PORTAL_BASE", "http://127.0.0.1:5283"),
        heax_api=env.get("HWAXRISK_HEAX_API", "http://127.0.0.1:4040"),
        heax_base=env.get("HWAXRISK_HEAX_BASE", "http://127.0.0.1:4180"),
        sso_ttl_s=int(env.get("HWAXRISK_SSO_TTL_S", "900")),
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
        risk_panel_timeout_s=int(env.get("HWAXRISK_PANEL_TIMEOUT_S", str(DEFAULT_PANEL_TIMEOUT_S))),
        risk_engine_read_timeout_s=int(env.get("HWAXRISK_ENGINE_READ_TIMEOUT_S", str(DEFAULT_ENGINE_READ_TIMEOUT_S))),
        risk_credential_margin_s=int(env.get("HWAXRISK_CREDENTIAL_MARGIN_S", "0")),
        risk_portal_call_timeout_s=int(env.get("HWAXRISK_PORTAL_CALL_TIMEOUT_S", str(DEFAULT_PORTAL_CALL_TIMEOUT_S))),
        risk_source_call_timeout_s=int(env.get("HWAXRISK_SOURCE_CALL_TIMEOUT_S", str(DEFAULT_SOURCE_CALL_TIMEOUT_S))),
        risk_engine_busy_wait_s=int(env.get("HWAXRISK_ENGINE_BUSY_WAIT_S", str(DEFAULT_ENGINE_BUSY_WAIT_S))),
        risk_engine_busy_max_wait_s=int(env.get("HWAXRISK_ENGINE_BUSY_MAX_WAIT_S", str(ENGINE_BUSY_ALLOWANCE_S))),
        risk_field_timeout_s=int(env.get("HWAXRISK_FIELD_TIMEOUT_S", str(DEFAULT_FIELD_TIMEOUT_S))),
        risk_roster_deadline_s=int(env.get("HWAXRISK_ROSTER_DEADLINE_S", str(DEFAULT_ROSTER_DEADLINE_S))),
        adh_team=env.get("HWAXRISK_ADH_TEAM") or None,
        adh_group=env.get("HWAXRISK_ADH_GROUP") or None,
    )


def panel_timeout_s(cfg: object | None = None) -> int:
    """패널 벽시계(초). 0 이면 끈 것이다 — 그때 패널을 끊는 것은 줄 사이 침묵 한도뿐이다."""
    cfg = settings if cfg is None else cfg
    return max(0, int(getattr(cfg, "risk_panel_timeout_s", DEFAULT_PANEL_TIMEOUT_S)))


def engine_busy_wait_s(cfg: object | None = None) -> int:
    """포털 429 뒤에 다시 묻기까지 쉬는 간격(초). 1초 밑으로는 내려가지 않는다 — 0 이면 예산 내내 포털을 두드린다."""
    cfg = settings if cfg is None else cfg
    return max(1, int(getattr(cfg, "risk_engine_busy_wait_s", DEFAULT_ENGINE_BUSY_WAIT_S)))


def engine_busy_max_wait_s(cfg: object | None = None) -> int:
    """포털 429 를 기다리는 총 예산(초). 다 쓰면 러너가 좌석을 차감하지 않고 잡을 멈춘다. 0 이면 기다리지 않는다."""
    cfg = settings if cfg is None else cfg
    return max(0, int(getattr(cfg, "risk_engine_busy_max_wait_s", ENGINE_BUSY_ALLOWANCE_S)))


def credential_margin_s(cfg: object | None = None) -> int:
    """사용자 포털 PAT 로 패널을 시작하려면 남아 있어야 하는 수명(초).

    규칙 — 남은 수명이 (패널 벽시계 + 429 대기 예산 + 600초)를 넘을 때만 그 PAT 로 패널을 시작한다. 자격은 누적
    시간 한도라 감싸는 실행보다 길어야 하는데, 종전 값은 1800초 고정이라 벽시계 2400초보다 작았다(뒤집혀
    있었다). 벽시계를 끈 박스(0)에서는 기본 벽시계로 셈한다 — 끝없는 실행을 감쌀 여유는 없다. 429 몫은 러너가
    실제로 기다리는 예산(`HWAXRISK_ENGINE_BUSY_MAX_WAIT_S`)을 그대로 쓴다 — 그 손잡이를 올리면 여유가 따라간다.
    `HWAXRISK_CREDENTIAL_MARGIN_S` 로 덮어쓸 수 있고, PAT 등록 하한보다 작은지는 기동 때 본다(main._lifespan).
    """
    cfg = settings if cfg is None else cfg
    override = int(getattr(cfg, "risk_credential_margin_s", 0) or 0)
    if override > 0:
        return override
    return (panel_timeout_s(cfg) or DEFAULT_PANEL_TIMEOUT_S) + engine_busy_max_wait_s(cfg) + CREDENTIAL_SLACK_S


def load_secrets(data_dir: Path) -> dict[str, str]:
    """$DATA_DIR/secrets.env 의 SECRET_KEYS·OPTIONAL_SECRET_KEYS 를 읽는다(KEY=VALUE 줄, '#' 주석, 따옴표 없음 — plan §8.2.7).

    파일이 없으면 빈 dict. 모드가 0600 이 아니면 경고만 낸다. 값은 절대 로그하지 않는다.
    """
    path = data_dir / SECRETS_FILENAME
    if not path.is_file():
        return {}
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        log.warning("secrets.env 권한이 0600 이 아닙니다(%s): %o", path, mode)
    return _read_env_file(path, (*SECRET_KEYS, *OPTIONAL_SECRET_KEYS))


def _read_env_file(path: Path, keys: tuple[str, ...]) -> dict[str, str]:
    """KEY=VALUE 줄 파일에서 `keys` 의 값만 읽는다('#' 주석·빈 줄·값이 빈 줄은 건너뛴다). secrets.env·knobs.env 가 같이 쓴다."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key in keys and value:
            out[key] = value
    return out


def load_review_knobs(data_dir: Path, env: Mapping[str, str] | None = None) -> tuple[dict[str, Any], tuple]:
    """검토 손잡이(REVIEW_KNOBS)를 환경변수 > `$DATA_DIR/knobs.env` > 코드 기본값 순으로 읽는다.

    반환은 (Settings 속성 → 값, ((환경변수 이름, 출처 env|knobs.env|default), …)). 빈 값은 적지 않은 것으로 본다. knobs.env 의 줄
    끝 주석(`KEY=1  # 파일럿`)은 떼고 읽는다(손잡이 값에는 '#' 이 들 일이 없다). 정수가 아니거나 하한(`Knob.minimum`) 밑인 값,
    켜기·끄기 낱말(1·true·yes·on · 0·false·no·off)이 아닌 불리언은 기동을 막는다 — 어느 자리(파일 경로 또는 환경변수)의 어느
    손잡이인지 말한다. 조용히 기본값으로 돌면 박스에 적은 값이 듣지 않는 것을 아무도 모른다(켜기 스위치가 오타·꼬리 주석에서
    조용히 꺼지던 것 — 반대 검토 C2a RC-5). 손잡이 사이의 관계(단위 크기의 순서·시간 한도의 사슬)는 main.check_review_chain 이 본다.
    """
    env = os.environ if env is None else env
    path = Path(data_dir) / KNOBS_FILENAME
    from_file = _read_env_file(path, tuple(k.env for k in REVIEW_KNOBS)) if path.is_file() else {}
    from_file = {key: value.split("#", 1)[0].strip() for key, value in from_file.items()}
    values: dict[str, Any] = {}
    sources: list[tuple[str, str]] = []
    for knob in REVIEW_KNOBS:
        raw, source = (env.get(knob.env) or "").strip(), "env"
        if not raw:
            raw, source = from_file.get(knob.env, ""), KNOBS_FILENAME
        if not raw:
            values[knob.attr] = knob.default
            sources.append((knob.env, "default"))
            continue
        where = f"{path}" if source == KNOBS_FILENAME else "환경변수"
        if knob.kind == "bool":
            token = raw.lower()
            if token not in _KNOB_TRUE + _KNOB_FALSE:
                raise RuntimeError(f"{knob.env}={raw!r} 은 켜기·끄기 값이 아닙니다({where}) — 1·true·yes·on 이나"
                                   f" 0·false·no·off 로 적거나 지우면 기본값 {int(bool(knob.default))} 로 돈다.")
            values[knob.attr] = token in _KNOB_TRUE
        else:
            try:
                value = int(raw)
            except ValueError as exc:
                raise RuntimeError(f"{knob.env}={raw!r} 은 정수가 아닙니다({where}) — 고치거나 지우면 기본값"
                                   f" {knob.default} 로 돈다.") from exc
            if value < knob.minimum:
                raise RuntimeError(f"{knob.env}={raw!r} 은 {knob.minimum} 이상이어야 합니다({where}) — 고치거나 지우면 기본값"
                                   f" {knob.default} 로 돈다.")
            values[knob.attr] = value
        sources.append((knob.env, source))
    return values, tuple(sources)


def review_enabled(cfg: object | None = None) -> bool:
    """새 흐름(flow='cells')의 스위치 — HWAXRISK_REVIEW_ENABLED. 꺼져 있으면 cells 로 열거나 바꾸는 요청이 409 review_disabled 다."""
    cfg = settings if cfg is None else cfg
    return bool(getattr(cfg, "risk_review_enabled", False))


def review_call_timeout_s(cfg: object | None = None) -> int:
    """카드 대조 호출 하나의 벽시계(초). 0 이면 끈 것이다."""
    cfg = settings if cfg is None else cfg
    return max(0, int(getattr(cfg, "risk_review_call_timeout_s", DEFAULT_REVIEW_CALL_TIMEOUT_S)))


def review_read_timeout_s(cfg: object | None = None) -> int:
    """카드 대조 스트림의 프레임 사이 침묵 한도(초). 0 이면 끈 것이다."""
    cfg = settings if cfg is None else cfg
    return max(0, int(getattr(cfg, "risk_review_read_timeout_s", 300)))


def review_credential_margin_s(cfg: object | None = None) -> int:
    """검토 잡이 사용자 PAT 로 호출을 내려면 남아 있어야 하는 수명(초) — 호출 벽시계 + 600(M2.md 4.5).

    기다림(자리 없음)은 호출마다 자격을 다시 고르므로 넣지 않는다. 벽시계를 끈 박스(0)에서는 기본 벽시계로 셈한다.
    """
    return (review_call_timeout_s(cfg) or DEFAULT_REVIEW_CALL_TIMEOUT_S) + CREDENTIAL_SLACK_S


def review_knobs(cfg: object | None = None) -> dict[str, dict]:
    """GET /api/meta/runtime 의 `knobs` — {환경변수 이름: {value, source}}. 출처는 기동 때 읽은 것이다(비밀은 없다)."""
    cfg = settings if cfg is None else cfg
    sources = dict(getattr(cfg, "knob_sources", ()) or ())
    return {knob.env: {"value": getattr(cfg, knob.attr, knob.default), "source": sources.get(knob.env, "default")}
            for knob in REVIEW_KNOBS}


def backup_key(data_dir: Path | None = None, env: Mapping[str, str] | None = None) -> str:
    """age 공개키(`HWAXRISK_BACKUP_KEY`) — secrets.env 우선, 없으면 환경변수. 없으면 빈 문자열(plan §5.2.5 (3a))."""
    root = settings.data_dir if data_dir is None else data_dir
    environ = os.environ if env is None else env
    return (load_secrets(root).get("HWAXRISK_BACKUP_KEY") or environ.get("HWAXRISK_BACKUP_KEY") or "").strip()


def heax_gateway_secret(data_dir: Path | None = None, env: Mapping[str, str] | None = None) -> str:
    """게이트웨이 SSO 공유 시크릿 — secrets.env 우선, 없으면 환경변수. 없으면 빈 문자열(= /auth/sso 404)."""
    root = settings.data_dir if data_dir is None else data_dir
    environ = os.environ if env is None else env
    return (load_secrets(root).get("HWAXRISK_HEAX_GATEWAY_SECRET")
            or environ.get("HWAXRISK_HEAX_GATEWAY_SECRET") or "").strip()


def cred_key_path(data_dir: Path | None = None) -> Path:
    """로컬 개발 폴백 키 파일 경로 — `$DATA_DIR/cred.key`(운영은 secrets.env 의 HWAXRISK_CRED_KEY, plan §8.2.7)."""
    return (settings.data_dir if data_dir is None else data_dir) / CRED_KEY_FILENAME


def cred_key_source(data_dir: Path | None = None, env: Mapping[str, str] | None = None) -> str:
    """자격 암호화 키가 어디서 오는지 — `load_cred_key` 와 같은 순서로 'secrets' · 'env' · 'path' · 'dev_fallback' · 'absent'.

    'dev_fallback' 은 앱이 데이터 디렉터리에 만든 `cred.key`(로컬 개발 폴백)다 — 키가 암호문과 같은 디렉터리에 앉는다.
    env·path 는 있는 것으로 센다(종전 판정은 secrets.env 파일만 봐서 env 로 준 키도 '없음' 이었다).
    """
    env = os.environ if env is None else env
    root = settings.data_dir if data_dir is None else data_dir
    if (load_secrets(root).get("HWAXRISK_CRED_KEY") or "").strip():
        return "secrets"
    if (env.get("HWAXRISK_CRED_KEY") or "").strip():
        return "env"
    raw_path = (env.get("HWAXRISK_CRED_KEY_PATH") or "").strip()
    if raw_path and Path(raw_path).is_file():
        return "path"
    return "dev_fallback" if cred_key_path(root).is_file() else "absent"


def cred_key_move_fix(data_dir: Path | None = None) -> str:
    """`cred.key` 폴백을 secrets.env 로 옮기는 절차 — **같은 값**을 옮긴다(값이 화면에 찍히지 않는 명령)."""
    root = settings.data_dir if data_dir is None else data_dir
    key_file, secrets_file = root / CRED_KEY_FILENAME, root / SECRETS_FILENAME
    return (f"같은 값을 secrets.env 로 옮기고 앱을 다시 띄운다 — printf 'HWAXRISK_CRED_KEY=%s\\n' \"$(cat {key_file})\""
            f" >> {secrets_file} && chmod 600 {secrets_file} (값이 화면에 찍히지 않는다). 새 키를 만들어 넣으면 이미 등록된"
            " 사용자 PAT 가 전부 풀리지 않는다(모두 다시 등록해야 한다) — 반드시 cred.key 의 값을 그대로 옮긴다. 다시 띄운 뒤 설정"
            " 화면의 키 출처가 secrets 이면 cred.key 는 지워도 된다(백업 한 벌에 키와 암호문이 함께 실리지 않게).")


def box_assessment(*, box_match: bool, data_dir: Path | None = None, env: Mapping[str, str] | None = None) -> dict:
    """박스 자격 판정 — `{secrets_valid, cred_key_source, reasons[{code, keys?, message, fix}]}`(GET /api/me 의 box).

    코드는 넷이다 — host_mismatch(이관 직후) · missing_required(필수 키 없음) · cred_key_dev_fallback(키가 cred.key 폴백)
    · missing_optional(그 길만 닫힌다, 앱은 돈다). `secrets_valid` 는 앞의 셋이 없을 때 참이다. 값은 싣지 않는다.
    """
    env = os.environ if env is None else env
    root = settings.data_dir if data_dir is None else data_dir
    secrets = load_secrets(root)
    source = cred_key_source(root, env)
    reasons: list[dict] = []
    if not box_match:
        reasons.append({
            "code": "host_mismatch",
            "message": "직전 기동의 호스트(origin.json)가 지금과 다르다 — 데이터 디렉터리를 다른 박스에서 옮겨 온 뒤 첫 기동이라 등록된"
                       " PAT 를 이 기동 동안 보이지 않는다.",
            "fix": "secrets.env 의 HWAXRISK_CRED_KEY 가 같은 값으로 옮겨 왔는지 확인하고 앱을 다시 띄운다(다음 기동부터 이 호스트가"
                   " 기준이다). 키가 다르면 등록된 PAT 가 풀리지 않아 각자 다시 등록해야 한다.",
        })
    if source == "absent":
        reasons.append({
            "code": "missing_required", "keys": list(SECRET_KEYS),
            "message": "자격 암호화 키(HWAXRISK_CRED_KEY)가 없다 — 사용자 PAT 를 저장할 때 앱이 데이터 디렉터리에 개발용 cred.key 를"
                       " 만들어 쓰게 된다(암호문과 같은 디렉터리라 백업 한 벌에 키와 암호문이 함께 실린다).",
            "fix": (f"운영 키를 secrets.env 에 넣고 앱을 다시 띄운다 — printf 'HWAXRISK_CRED_KEY=%s\\n' \"$(python3 -c 'from"
                    f" cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')\" >> {root / SECRETS_FILENAME}"
                    f" && chmod 600 {root / SECRETS_FILENAME} (값이 화면에 찍히지 않는다). 키를 잃으면 등록된 PAT 가 전부 풀리지 않으니"
                    " secrets.env 와 같은 등급으로 따로 보관한다."),
        })
    elif source == "dev_fallback":
        reasons.append({
            "code": "cred_key_dev_fallback", "keys": list(SECRET_KEYS),
            "message": (f"자격 암호화 키를 데이터 디렉터리의 {CRED_KEY_FILENAME}(앱이 만든 개발용 폴백)에서 읽는다 — 암호문"
                        f"({DB_FILENAME})과 같은 디렉터리라 백업 한 벌에 키와 암호문이 함께 실리고, 이 파일을 모르고 옮기면 등록된"
                        " PAT 가 전부 풀리지 않는다. 동작은 한다."),
            "fix": cred_key_move_fix(root),
        })
    missing = [key for key in OPTIONAL_SECRET_KEYS
               if not (secrets.get(key) or (key in _ENV_READ_OPTIONAL_KEYS and (env.get(key) or "").strip()))]
    if missing:
        reasons.append({
            "code": "missing_optional", "keys": missing,
            "message": "없는 선택 키 — 앱은 돌고 그 길만 닫힌다. " + " · ".join(f"{key}: {OPTIONAL_KEY_EFFECTS[key]}"
                                                                       for key in missing),
            "fix": f"필요한 길만 켠다 — {root / SECRETS_FILENAME} 에 KEY=값 줄을 넣고(0600) 앱을 다시 띄운다.",
        })
    blocking = {"host_mismatch", "missing_required", "cred_key_dev_fallback"}
    return {"secrets_valid": not any(r["code"] in blocking for r in reasons), "cred_key_source": source,
            "reasons": reasons}


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
        # 경고다 — 이 순간부터 등록된 PAT 가 이 파일에 묶인다. 운영 박스라면 같은 값을 secrets.env 로 옮겨야 한다.
        log.warning("자격 암호화 키를 새로 만들었습니다: %s (0600, 개발용 폴백) — %s", path, cred_key_move_fix(path.parent))
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
