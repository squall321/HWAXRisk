# 건너뜀 예산 가드가 실제로 찾는지 — 임시 디렉터리의 시험 파일을 자식 pytest 로 돌려 종료 코드를 본다(WP5b C1)
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from tests import skip_budget
from tests.conftest import BACKEND_DIR

_HEAD = "import pytest\n\n\ndef test_passes():\n    assert True\n"
_XFAIL = ('\n\n@pytest.mark.xfail(strict=True, raises=AssertionError, reason="재현 시험")\n'
          "def test_expected_failure():\n    assert False\n")
_SKIP = '\n\ndef test_skipped():\n    pytest.skip("형제 리포가 곁에 없다")\n'
_ROOT_SKIP = '\n\ndef test_root_only():\n    pytest.skip("root 는 쓰기 권한 검사를 우회한다")\n'


def _run(case: Path, strict: str, rootdir: Path) -> tuple[int, str]:
    """자식 pytest — rootdir 를 늘 준다. 안 주면 cwd 와 인자의 공통 조상(예 /tmp)이 rootdir 가 되어 그 아래를 다 훑는다."""
    env = {**os.environ, "RR_STRICT_SKIPS": strict, "PYTHONDONTWRITEBYTECODE": "1"}
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "tests.skip_budget",
            f"--rootdir={rootdir}", str(case)]
    out = subprocess.run(args, cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120)
    return out.returncode, out.stdout + out.stderr


def test_an_expected_failure_is_not_counted_as_a_skip(tmp_path):
    case = tmp_path / "test_case.py"
    case.write_text(_HEAD + _XFAIL, encoding="utf-8")
    rc, out = _run(case, "1", tmp_path)
    assert rc == 0 and "1 xfailed" in out and "건너뜀 예산" not in out, out


def test_a_skip_outside_the_list_fails_the_session_when_strict(tmp_path):
    case = tmp_path / "test_case.py"
    case.write_text(_HEAD + _XFAIL + _SKIP, encoding="utf-8")
    rc, out = _run(case, "1", tmp_path)
    assert rc == 1, out
    assert "건너뜀 예산" in out and "test_case.py::test_skipped" in out and "test_expected_failure" not in out


def test_the_same_skip_only_warns_when_not_strict(tmp_path):
    case = tmp_path / "test_case.py"
    case.write_text(_HEAD + _SKIP, encoding="utf-8")
    rc, out = _run(case, "0", tmp_path)
    assert rc == 0 and "건너뜀 예산" in out and "경고만" in out, out


def test_an_allowed_skip_passes_when_strict(tmp_path):
    # nodeid 는 rootdir(임시 디렉터리) 기준이라 허용 목록의 접두와 같은 자리에 둔다.
    case = tmp_path / "tests" / "test_config_datadir.py"
    case.parent.mkdir()
    case.write_text(_HEAD + _ROOT_SKIP, encoding="utf-8")
    rc, out = _run(case, "1", tmp_path)
    assert rc == 0 and "1 skipped" in out and "건너뜀 예산" not in out, out


def test_strict_mode_follows_the_siblings(tmp_path):
    repo = tmp_path / "HWAXRisk"
    repo.mkdir()
    assert skip_budget.strict_mode({}, repo) is False
    for name in skip_budget.SIBLINGS:
        (tmp_path / name).mkdir()
    assert skip_budget.strict_mode({}, repo) is True
    assert skip_budget.strict_mode({"RR_STRICT_SKIPS": "0"}, repo) is False


def test_every_skip_site_is_classified():
    """새로 건너뛰는 자리를 만들면 허용(사유)인지 형제 부재 전용인지 tests/skip_budget.py 에 적어야 한다(반대 검토 P-03).
    pytest.xfail() 호출도 건너뜀으로 센다(R-FLOOR-2)."""
    marker = re.compile(r"pytest\.skip\(|pytest\.mark\.skipif|importorskip|pytest\.xfail\(")
    sites = {path.relative_to(BACKEND_DIR).as_posix() for path in (BACKEND_DIR / "tests").rglob("test_*.py")
             if path.name != Path(__file__).name and marker.search(path.read_text(encoding="utf-8"))}
    classified = {prefix for prefix, _, _ in skip_budget.ALLOWED_SKIPS} | set(skip_budget.SIBLING_ONLY)
    assert sites, "건너뛰는 자리를 하나도 못 찾았다 — 이 시험이 죽었다"
    assert sorted(sites - classified) == []


# ---------------------------------------------------------------- xfail 은 strict 여야 한다(R-FLOOR-2)
_LOOSE_XFAIL = '\n\n@pytest.mark.xfail(reason="느슨한 표식")\ndef test_loose():\n    assert False\n'
_CALLED_XFAIL = '\n\ndef test_called():\n    pytest.xfail("형제 리포가 곁에 없다")\n'


def test_a_loose_xfail_is_counted_like_a_skip(tmp_path):
    """가드는 기대한 실패(xfail)를 세지 않는다 — strict 아닌 표식이나 pytest.xfail() 호출로 바꾸면 건너뜀과 같은 우회가 된다."""
    for body, name in ((_LOOSE_XFAIL, "test_loose"), (_CALLED_XFAIL, "test_called")):
        case = tmp_path / name / "test_case.py"
        case.parent.mkdir()
        case.write_text(_HEAD + body, encoding="utf-8")
        rc, out = _run(case, "1", case.parent)
        assert rc == 1 and "건너뜀 예산" in out and f"test_case.py::{name}" in out and "strict" in out, out


# ---------------------------------------------------------------- 포털 요청 모델 계약은 의존이 없을 때만 건너뛴다(R-FLOOR-2)
_CONTRACT = "tests/test_wiring_regressions.py::test_the_whole_request_body_is_accepted_by_the_portal_model"
_FAKE_ROUTES = {
    "dependency_missing": "import hwax_dependency_not_installed_here\n",
    "renamed": "class AgentChatRequest:\n    pass\n",
    "moved": "from app.agent.chat_models import ChatRequest  # noqa: F401\n",
    "validator_raises": ("from pydantic import BaseModel\n\n\nclass ChatRequest(BaseModel):\n    @classmethod\n"
                         "    def model_validate(cls, *args, **kwargs):\n        raise TypeError('검증기 내부 오류')\n"),
}


def _fake_portal(root: Path, routes_py: str) -> Path:
    agent = root / "backend" / "app" / "agent"
    agent.mkdir(parents=True)
    (root / "backend" / "app" / "__init__.py").write_text("", encoding="utf-8")
    (agent / "__init__.py").write_text("", encoding="utf-8")
    (agent / "routes.py").write_text(routes_py, encoding="utf-8")
    return root


def _run_contract(portal: Path) -> tuple[int, str]:
    env = {**os.environ, "RR_STRICT_SKIPS": "1", "HWAX_PORTAL_REPO": str(portal), "PYTHONDONTWRITEBYTECODE": "1"}
    # -q 는 주지 않는다 — 리포의 addopts 가 이미 -q 라 겹치면 끝줄의 수가 숨는다.
    out = subprocess.run([sys.executable, "-m", "pytest", "-rs", "-p", "no:cacheprovider", _CONTRACT],
                         cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=300)
    return out.returncode, out.stdout + out.stderr


def test_the_portal_contract_skips_only_when_a_third_party_dependency_is_missing(tmp_path):
    """러너 본문을 포털 ChatRequest 로 검증하는 유일한 시험이 하위 프로세스가 어떻게 실패하든 건너뛰어, 포털이 모델을 옮기거나
    러너의 실제 본문에서 검증기가 터져도(운영에서는 패널마다 500) 형제가 곁에 있는 엄격 모드가 초록이었다. 건너뜀은 포털의
    서드파티 의존이 이 venv 에 없을 때만이다."""
    rc, out = _run_contract(_fake_portal(tmp_path / "dependency_missing", _FAKE_ROUTES["dependency_missing"]))
    assert rc == 0 and "1 skipped" in out and "hwax_dependency_not_installed_here" in out, out
    for case in ("renamed", "moved", "validator_raises"):
        rc, out = _run_contract(_fake_portal(tmp_path / case, _FAKE_ROUTES[case]))
        assert rc == 1 and "1 failed" in out and "skipped" not in out, (case, out)
