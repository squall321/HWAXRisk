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


def test_write_pat_key_is_declared_and_loadable(tmp_path):
    """선언된 키(필수 SECRET_KEYS · 선택 OPTIONAL_SECRET_KEYS)가 아니면 secrets.env 에 넣어도 로드되지 않아 RA 쓰기가 영구 실패한다.
    두 키는 선택 키다(없으면 그 길만 닫힌다 — 리스크 앱 사람 자격 R5)."""
    assert WRITE_KEY in config.OPTIONAL_SECRET_KEYS and READ_KEY in config.OPTIONAL_SECRET_KEYS
    assert ra_client.WRITE_SECRET_KEY == WRITE_KEY
    path = tmp_path / "secrets.env"
    path.write_text(f"{READ_KEY}=fake-read\n{WRITE_KEY}=fake-rw\n", encoding="utf-8")
    path.chmod(0o600)
    assert config.load_secrets(tmp_path) == {READ_KEY: "fake-read", WRITE_KEY: "fake-rw"}


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


# ---------------------------------------------------------------- MCP 쓰기 도구 목록(재설계 M2 S12 — 바뀌지 않는다)
# 게이트웨이 위임 신원(entry.require_delegate)으로만 쓰는 도구. S12 의 검토 잡은 새 도구가 아니라 risk_start_job(mode='reviews')
# 이고(M2.md 4.7), 새로 든 risk_get_cells·risk_get_expert_report 는 읽기다. risk_get_brief 는 읽기지만 결과를 낼 신원에게만 열어
# 같은 문을 지난다(RV-1).
MCP_WRITE_TOOLS = frozenset({
    "risk_submit_panel_result", "risk_add_finding", "risk_create_project", "risk_add_source", "risk_capture_snapshot",
    "risk_ack_gate", "risk_decide_sameas", "risk_create_diff", "risk_open_target", "risk_start_job", "risk_job_action",
    "risk_repersist_panel"})
DELEGATE_GATED_READS = frozenset({"risk_get_brief"})
REVIEW_READERS = ("risk_get_units", "risk_get_cells", "risk_get_expert_report")


def _calls_require_delegate(fn: ast.AST) -> bool:
    return any(isinstance(n, ast.Call) and ((isinstance(n.func, ast.Name) and n.func.id == "require_delegate")
                                            or (isinstance(n.func, ast.Attribute) and n.func.attr == "require_delegate"))
               for n in ast.walk(fn))


def _delegate_gated_tools() -> set[str]:
    """MCP 도구 가운데 위임 문을 지나는 것 — 본문이 require_delegate 를 부르거나, 그 문을 지나는 entry 함수를 부른다."""
    entry_tree = ast.parse((APP_DIR / "entry.py").read_text(encoding="utf-8"))
    gated_entry = {f.name for f in ast.walk(entry_tree)
                   if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and _calls_require_delegate(f)}
    out: set[str] = set()
    for fn in ast.parse((APP_DIR / "mcp_server.py").read_text(encoding="utf-8")).body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "tool"
                   for d in fn.decorator_list):
            continue
        used = {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id == "entry"}
        if _calls_require_delegate(fn) or used & gated_entry:
            out.add(fn.name)
    return out


def test_the_mcp_write_tools_are_the_same_and_the_review_readers_do_not_pass_the_write_door():
    gated = _delegate_gated_tools()
    assert gated == MCP_WRITE_TOOLS | DELEGATE_GATED_READS
    assert not gated & set(REVIEW_READERS)
