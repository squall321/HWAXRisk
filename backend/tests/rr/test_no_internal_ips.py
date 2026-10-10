# 추적 파일에 사내 IP 가 박히지 않게 막는다(WP5b C1 위생 가드) — 이 리포는 GitHub 에 있고 기준선은 0 건이다
"""포털 리포의 같은 가드는 이미 박힌 것이 있어 '늘지 않게' 만 막는다. 이 리포는 0 건이라 0 건을 지킨다.

주소는 사설 대역(10/8 · 172.16/12 · 192.168/16)의 네 자리 모두를 요구한다. 세 자리만 보면 `"autoprefixer": "^10.6.1"`
같은 버전 숫자가 걸린다(포털 가드의 오탐). 루프백·0.0.0.0 은 내부 배치가 아니라 뺀다. 예시 값은 `127.0.0.1` 만 쓴다.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT

_IP = re.compile(r"(?<![\d.])(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}(?![\d.])")
_SKIP_SUFFIXES = (".gz", ".db", ".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2", ".sif")
_SELF = "backend/tests/rr/test_no_internal_ips.py"          # 이 파일은 가드 시험용 예시 주소를 적는다


def _tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip(f"git 체크아웃이 아니다 — 추적 목록을 못 읽는다({out.stderr.strip()[:200]})")
    return [REPO_ROOT / p for p in out.stdout.split("\0") if p]


def scan(paths: list[Path], root: Path = REPO_ROOT) -> dict[str, list[str]]:
    """경로 → 그 파일에서 찾은 사설 대역 주소(정렬). 이진·읽을 수 없는 파일은 건너뛴다."""
    hits: dict[str, list[str]] = {}
    for path in paths:
        rel = path.relative_to(root).as_posix()
        if rel == _SELF or path.suffix.lower() in _SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found = sorted(set(_IP.findall(text)))
        if found:
            hits[rel] = found
    return hits


def test_no_tracked_file_carries_a_private_ip():
    hits = scan(_tracked())
    assert hits == {}, f"추적 파일에 사설 대역 주소가 있다 — 이 리포는 GitHub 에 있다(리포 CLAUDE.md 금지 항목): {hits}"


def test_the_guard_actually_finds(tmp_path):
    """0건을 훑고 통과하는 가드는 아무것도 지키지 않는다 — 실제로 찾는지와 오탐하지 않는지를 같이 본다."""
    for text in ("NO_PROXY=10.0.0.12,localhost", "http://192.168.0.5:8000", "172.20.1.2"):
        assert _IP.search(text), text
    for text in ("127.0.0.1:8723", "0.0.0.0:8723", '"autoprefixer": "^10.6.1"', "172.15.0.1", "v10.1.2.3.4"):
        assert not _IP.search(text), text
    planted = tmp_path / "planted.yaml"
    planted.write_text("upstream: http://10.0.0.12:9009\n", encoding="utf-8")
    assert scan([planted], root=tmp_path) == {"planted.yaml": ["10.0.0.12"]}
    assert len(_tracked()) > 100, "추적 파일을 거의 못 읽었다 — 가드가 죽었다"
