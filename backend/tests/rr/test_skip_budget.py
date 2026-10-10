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
    """새로 건너뛰는 자리를 만들면 허용(사유)인지 형제 부재 전용인지 tests/skip_budget.py 에 적어야 한다(반대 검토 P-03)."""
    marker = re.compile(r"pytest\.skip\(|pytest\.mark\.skipif|importorskip")
    sites = {path.relative_to(BACKEND_DIR).as_posix() for path in (BACKEND_DIR / "tests").rglob("test_*.py")
             if path.name != Path(__file__).name and marker.search(path.read_text(encoding="utf-8"))}
    classified = {prefix for prefix, _, _ in skip_budget.ALLOWED_SKIPS} | set(skip_budget.SIBLING_ONLY)
    assert sites, "건너뛰는 자리를 하나도 못 찾았다 — 이 시험이 죽었다"
    assert sorted(sites - classified) == []
