# 서비스 자격 2키 분리 정적 검사 — 읽기 경로가 쓰기 PAT 를 잡지 않는지 소스에서 확인한다(plan §8.2.7·§5.1 원칙 10)
from __future__ import annotations

import ast
from pathlib import Path

from app import config, ra_client

BACKEND_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BACKEND_DIR / "app"

READ_KEY = "HWAXRISK_PORTAL_PAT"
WRITE_KEY = "HWAXRISK_PORTAL_PAT_RW"

# 쓰기 키가 나와도 되는 모듈 — 선언(config)과 RA 인스턴스·보고서 쓰기 채널 하나뿐이다.
WRITE_KEY_ALLOWED = {"config.py", "ra_client.py"}
# 좌석 자유조회·소스 캡처·엔진 호출이 자격을 잡는 읽기 경로(여기에 쓰기 키가 나오면 경계가 무너진다).
READ_PATH_MODULES = ("runner.py", "engine_client.py", "roster.py", "adapters/registry.py")


def _sources() -> dict[str, str]:
    return {str(p.relative_to(APP_DIR)): p.read_text(encoding="utf-8")
            for p in APP_DIR.rglob("*.py")}


def test_write_pat_key_is_declared_and_loadable():
    """SECRET_KEYS 에 없으면 secrets.env 에 넣어도 로드되지 않아 RA 쓰기가 영구 실패한다."""
    assert WRITE_KEY in config.SECRET_KEYS
    assert READ_KEY in config.SECRET_KEYS
    assert ra_client.WRITE_SECRET_KEY == WRITE_KEY


def test_read_paths_never_reach_for_the_write_pat():
    sources = _sources()
    for name in READ_PATH_MODULES:
        assert name in sources, name
        assert WRITE_KEY not in sources[name], f"{name} 이 쓰기 PAT 를 잡는다 — 읽기 경로는 {READ_KEY} 만 쓴다"


def test_only_the_ra_channel_reads_the_write_pat():
    for name, text in _sources().items():
        if WRITE_KEY in text:
            assert name in WRITE_KEY_ALLOWED, f"{name} 이 쓰기 PAT 를 잡는다(허용: {sorted(WRITE_KEY_ALLOWED)})"


def test_ra_client_from_settings_uses_the_write_key_only():
    """읽기 키만 있는 secrets.env 로는 RA 쓰기 클라이언트가 열리지 않는다(조용한 폴백 규약 그대로)."""
    read_only = ra_client.ra_client_from_settings(config.settings, {READ_KEY: "fake-read-pat-for-test"})
    assert read_only.available is False
    with_write = ra_client.ra_client_from_settings(config.settings, {WRITE_KEY: "fake-rw-pat-for-test"})
    assert with_write.available is True


def test_ra_write_tools_live_on_the_write_channel():
    """쓰기 4종(§8.2.7)은 RaClient 에만 있고 러너·로스터에는 그 이름이 없다."""
    write_tools = ("create_object", "update_object", "add_object_alias", "link_objects")
    tree = ast.parse((APP_DIR / "ra_client.py").read_text(encoding="utf-8"))
    methods = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert set(write_tools) <= methods
    for name in READ_PATH_MODULES:
        text = (APP_DIR / name).read_text(encoding="utf-8")
        for tool in write_tools:
            assert tool not in text, f"{name} 이 RA 쓰기 도구 {tool} 을 부른다"
