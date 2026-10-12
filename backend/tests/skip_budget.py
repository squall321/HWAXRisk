# 건너뜀 예산(WP5b C1 가드 D) — 형제 리포가 곁에 있는 박스에서 허용 목록 밖의 건너뜀이 나오면 세션을 붉게 끝낸다
"""건너뛴 시험은 통과가 아니다. CI 가 없어 시험은 사람과 에이전트가 손으로 돌리고, 끝줄의 'N skipped' 는 아무도 읽지 않는다.

`tests/conftest.py` 가 이 모듈의 훅을 이름으로 들인다. 따로 시험할 때는 `-p tests.skip_budget` 으로 싣는다.

- 형제 리포(`../HWAXPortal` · `../HWAXAgentServer`)가 곁에 있으면 엄격하다 — 허용 목록 밖의 건너뜀이 하나라도 있으면
  종료 코드가 1 이다. 없으면(SIF 빌드 등) 경고만 찍는다. `RR_STRICT_SKIPS=0|1` 이 이 판정을 덮는다.
- strict 인 xfail 은 세지 않는다. pytest 는 기대한 실패(xfail)도 `report.skipped` 로 넘기는데(`wasxfail` 이 붙는다), 그것을
  세면 재현 시험(xfail strict)을 넣는 순간 전체가 붉어진다(반대 검토 P-01). 다만 strict 아닌 표식과 `pytest.xfail()` 호출은
  건너뜀으로 센다 — 건너뛰던 자리를 그것으로 바꾸면 이 가드를 같은 모양으로 비켜 간다(R-FLOOR-2).
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SIBLINGS = ("HWAXPortal", "HWAXAgentServer")

# (nodeid 접두, 사유에 든 조각, 왜 허용하나). 건너뜀 사유에 그 조각이 있어야 허용된다.
ALLOWED_SKIPS: tuple[tuple[str, str, str], ...] = (
    ("tests/test_config_datadir.py", "root", "root 로 돌 때만 — root 는 쓰기 권한 검사를 우회한다"),
    ("tests/test_manifest.py", "HEAXHub", "HEAXHub 매니페스트 스키마가 곁에 없을 때 — HEAXHub 는 형제 셋에 들지 않는다"),
    ("tests/test_client_contract.py", "프런트엔드", "frontend/ 는 다른 세션이 개발한다 — 파일이 옮겨지는 날 백엔드가 붉어지지 않게"),
    ("tests/test_p6_routes.py", "프런트엔드", "같은 까닭(화면 파일)"),
    ("tests/test_wiring_regressions.py", "이 venv 로 불러오지 못했다",
     "포털이 새 서드파티 의존을 들이면 리스크 venv 로 포털 모델을 못 연다 — 계약 위반이 아니라 환경이다(사유가 끝줄에 찍힌다)."
     " 하위 프로세스가 포털 밖 모듈의 ModuleNotFoundError 일 때만 이 사유로 건너뛴다 — 이름이 없다·포털 안 모듈이 없다·"
     "검증 중 예외는 건너뛰지 않고 붉다(R-FLOOR-2)"),
    ("tests/rr/test_no_internal_ips.py", "git 체크아웃이 아니다", "git archive·SIF 사본에는 추적 목록이 없다"),
)
# 형제 리포가 없을 때만 건너뛰는 자리 — 형제가 곁에 있는데 건너뛰면 허용 목록 밖이라 붉다.
SIBLING_ONLY: tuple[str, ...] = ("tests/test_parity.py", "tests/test_atoms.py", "tests/test_wiring_regressions.py",
                                 "tests/test_stream_attribution.py", "tests/test_card_contract_copies.py")

_skipped: list[tuple[str, str]] = []
_strict_xfail: set[str] = set()      # strict 인 xfail 표식이 붙은 시험(nodeid) — 이것만 건너뜀으로 세지 않는다


def _reason(report) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        return str(longrepr[2])
    return str(longrepr or "")


def strict_mode(environ=None, root: Path = REPO_ROOT) -> bool:
    env = os.environ if environ is None else environ
    siblings = all((root.parent / name).is_dir() for name in SIBLINGS)
    return env.get("RR_STRICT_SKIPS", "1" if siblings else "0") == "1"


def unallowed(skipped: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(nodeid, reason) for nodeid, reason in skipped
            if not any(nodeid.startswith(prefix) and fragment in reason for prefix, fragment, _ in ALLOWED_SKIPS)]


def pytest_collection_modifyitems(session, config, items):
    for item in items:
        mark = item.get_closest_marker("xfail")
        if mark is not None and mark.kwargs.get("strict", config.getini("xfail_strict")):
            _strict_xfail.add(item.nodeid)


def pytest_runtest_logreport(report):
    if not report.skipped or report.when not in ("setup", "call"):
        return
    if not hasattr(report, "wasxfail"):
        _skipped.append((report.nodeid, _reason(report)))
    elif report.nodeid not in _strict_xfail:
        _skipped.append((report.nodeid, f"strict 아닌 xfail — {report.wasxfail}"))


def pytest_sessionfinish(session, exitstatus):
    if unallowed(_skipped) and strict_mode() and int(exitstatus) == 0:
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    extra = unallowed(_skipped)
    if not extra:
        return
    terminalreporter.section("건너뜀 예산")
    for nodeid, reason in extra:
        terminalreporter.write_line(f"{nodeid} — {reason}")
    verdict = ("형제 리포가 곁에 있어 종료 코드 1 로 끝낸다" if strict_mode()
               else "엄격 판정이 꺼져 있어 경고만 찍는다(RR_STRICT_SKIPS=1 이면 붉다)")
    terminalreporter.write_line(f"허용 목록(tests/skip_budget.py ALLOWED_SKIPS) 밖의 건너뜀 {len(extra)}건 — {verdict}.")
