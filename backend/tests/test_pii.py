# 근거 묶음의 개인정보 가림 시험 — 메일 · 전화 · 사설 IP · 주민번호 꼴 · 표지 붙은 사번은 가리고, 데이터인 수(소수 · 긴 숫자열 · 코드 · 버전)는 건드리지 않는다
"""HWAXPortal docs/request-1117 RK-02 · 게이트웨이의 교훈(HWAXPortal docs/request-1030 HG-21 — 소수점 뒤 숫자열을 IMEI 로 읽어 계산 결과를 망가뜨렸다).
사설 주소는 마디를 이어 붙여 만든다(추적 파일에 사설 주소 글자를 적지 않는다 — tests/rr/test_no_internal_ips.py)."""
from __future__ import annotations

import pytest

from app import pii


def _ip(*parts: int) -> str:
    return ".".join(str(p) for p in parts)


PRIVATE = _ip(10, 1, 2, 3)
PRIVATE_B = _ip(192, 168, 0, 7)
PRIVATE_C = _ip(172, 20, 1, 1)


@pytest.mark.parametrize("text,want,n", [
    ("담당 qa.tester@example.com 으로", "담당 [가림:메일] 으로", 1),
    ("전화 010-1234-5678 · 02-123-4567 · +82 10 1234 5678", "전화 [가림:전화] · [가림:전화] · [가림:전화]", 3),
    (f"서버 {PRIVATE} 와 {PRIVATE_B}, {PRIVATE_C}:8080", "서버 [가림:IP] 와 [가림:IP], [가림:IP]:8080", 3),
    ("주민 900101-1234567 확인", "주민 [가림:주민번호] 확인", 1),
    ("사번: A123456 · employee id 7654321", "사번: [가림:사번] · employee id [가림:사번]", 2),
])
def test_personal_shapes_are_masked(text, want, n):
    assert pii.mask_text(text) == (want, n)


@pytest.mark.parametrize("text", [
    "적층 두께 4.352099001761481 mm",                     # HG-21 — 소수점 뒤 15자리
    "응력 352099001761481 · 01012345678 · 1234567890",     # 가르지 않은 긴 숫자열은 데이터 id 와 가를 수 없다
    "코드 R-010 · PART-A · MET-STRESS · v1.10.0.5",
    f"버전 1.{PRIVATE}.5 와 3.{PRIVATE_B}",                   # 숫자 · 소수점에 붙은 꼴은 주소가 아니다
    "공인 주소 8.8.8.8 · 범위 밖 300.1.2.3",
    "치수 0.65 / 1.15 / -0.3 / 2.4e-3",
    "번호 1234567 만 있고 표지가 없다",
])
def test_data_numbers_are_left_alone(text):
    assert pii.mask_text(text) == (text, 0)


def test_non_text_passes_through():
    assert pii.mask_text("") == ("", 0) and pii.mask_text(None) == (None, 0)  # type: ignore[arg-type]
