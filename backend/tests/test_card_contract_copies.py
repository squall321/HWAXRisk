# 카드 대조 계약 예제 사본 가드 — tests/fixtures/card_review/contract/ 의 파일이 에이전트 서버 원본과 바이트까지 같다
"""리스크 앱의 카드 묶음·검증 시험은 엔진이 실제 코드로 만든 계약 예제(팩·결과·인용 벡터)를 입력으로 쓴다(M2.md 4.6).

사본은 SIF 빌드처럼 형제 리포가 없는 곳에서도 시험이 돌게 하려고 둔다. 사본이 원본에서 멀어지면 앱 시험은 엔진이 더는
내지 않는 모양으로 초록이 된다 — 그래서 형제 리포가 곁에 있으면 사본 전부를 원본과 바이트로 견준다.

- 형제 리포가 없을 때만 건너뛴다(`tests/skip_budget.py` SIBLING_ONLY).
- 형제 리포는 곁에 있는데 계약 디렉터리·파일이 없거나 읽히지 않으면 건너뛰지 않고 실패한다(P-22) — 이름이 바뀐 것이고,
  건너뛰면 엔진만 고친 커밋이 이 리포의 시험으로는 영영 잡히지 않는다.
- 엔진이 예제를 다시 뜨면(`CARD_REVIEW_CONTRACT_UPDATE=1`) 사본도 같은 바이트로 다시 복사한다. 손으로 고치지 않는다.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.conftest import FIXTURES_DIR, REPO_ROOT

COPIES = FIXTURES_DIR / "card_review" / "contract"
ENGINE_REL = Path("tests") / "fixtures" / "card_review" / "contract"


def _engine_repo() -> Path:
    return Path(os.environ.get("HWAX_AGENT_SERVER_REPO") or REPO_ROOT.parent / "HWAXAgentServer")


def differing(copies: Path, source: Path) -> list[str]:
    """사본 디렉터리의 파일 가운데 원본과 바이트가 다른 것의 이름. 원본이 없거나 읽히지 않으면 OSError 를 그대로 올린다."""
    out: list[str] = []
    for copy in sorted(p for p in copies.iterdir() if p.is_file()):
        if (source / copy.name).read_bytes() != copy.read_bytes():
            out.append(copy.name)
    return out


def test_copies_exist():
    """사본 디렉터리가 비면 아래 대조가 0건을 훑고 통과한다 — 그 자체를 막는다."""
    names = {p.name for p in COPIES.iterdir() if p.is_file()}
    assert {"pack_ok.json", "pack_empty.json", "pack_errors.json", "quote_vectors.json", "card_norm_vectors.json",
            "result_verdict_ok.json", "req_verdict_fwd.json"} <= names, sorted(names)


def test_copies_equal_the_engine_files_byte_for_byte():
    repo = _engine_repo()
    if not repo.is_dir():
        pytest.skip(f"엔진 리포가 곁에 없다(HWAX_AGENT_SERVER_REPO 또는 ../HWAXAgentServer) — {repo}")
    source = repo / ENGINE_REL
    if not source.is_dir():
        pytest.fail(f"엔진 리포는 곁에 있는데 계약 예제 디렉터리가 없다 — {source}. 경로가 바뀌었으면 이 시험을 같이 고친다")
    try:
        differ = differing(COPIES, source)
    except OSError as exc:
        pytest.fail(f"엔진 리포는 곁에 있는데 원본을 읽지 못했다 — {exc}")
    assert differ == [], (f"사본이 엔진 원본과 다르다 — {differ}. 엔진 예제가 다시 떴으면 원본을 그대로 다시 복사한다"
                          f"(cp {source}/<파일> {COPIES}/)")


def test_the_guard_sees_one_changed_byte_and_a_missing_original(tmp_path):
    """가드가 실제로 짚는다 — 한 바이트 다른 사본은 이름이 나오고, 원본이 없으면 건너뛰지 않고 OSError 다."""
    copies, source = tmp_path / "copies", tmp_path / "source"
    copies.mkdir()
    source.mkdir()
    data = (COPIES / "pack_ok.json").read_bytes()
    (source / "pack_ok.json").write_bytes(data)
    (copies / "pack_ok.json").write_bytes(data)
    assert differing(copies, source) == []
    (copies / "pack_ok.json").write_bytes(data.replace(b"K01", b"K0l", 1))
    assert differing(copies, source) == ["pack_ok.json"]
    (copies / "pack_empty.json").write_bytes(b"{}")
    with pytest.raises(OSError):
        differing(copies, source)
