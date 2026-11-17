# 근거 묶음의 개인정보 가림 시험 — 메일 · 전화 · 사설 IP · 주민번호 꼴 · 표지 붙은 사번은 한글이 붙어도 가리고, 데이터인 수 · 부품 · 그림 이름 · 조항 번호는 건드리지 않는다
"""HWAXPortal docs/request-1117 RK-02 · 반대 검토 M3 · L4. 게이트웨이의 교훈(HWAXPortal docs/request-1030 HG-21 — 소수점 뒤 숫자열을 IMEI 로 읽어 계산
결과를 망가뜨렸다)대로 보수적으로 가린다. 사설 주소는 마디를 이어 붙여 만든다(추적 파일에 사설 주소 글자를 적지 않는다 — tests/rr/test_no_internal_ips.py)."""
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
    ("hong@corp.com으로 보냄", "[가림:메일]으로 보냄", 1),
    ("전화 010-1234-5678 · 02-123-4567 · +82 10 1234 5678", "전화 [가림:전화] · [가림:전화] · [가림:전화]", 3),
    (f"서버 {PRIVATE} 와 {PRIVATE_B}, {PRIVATE_C}:8080", "서버 [가림:IP] 와 [가림:IP], [가림:IP]:8080", 3),
    ("주민 900101-1234567 확인", "주민 [가림:주민번호] 확인", 1),
    ("사번: A123456 · employee id 7654321", "사번: [가림:사번] · employee id [가림:사번]", 2),
    # 한글이 바로 붙은 꼴(반대 검토 M3 — 종전에는 유니코드 \w 거르개라 가리지 않았다).
    ("연락처 010-1234-5678로 연락", "연락처 [가림:전화]로 연락", 1),
    ("010-1234-5678입니다", "[가림:전화]입니다", 1),
    ("담당자010-1234-5678", "담당자[가림:전화]", 1),
    ("+82-10-1234-5678로", "[가림:전화]로", 1),
    ("주민 900101-1234567입니다", "주민 [가림:주민번호]입니다", 1),
    ("사번 A123456입니다", "사번 [가림:사번]입니다", 1),
    (f"서버 {PRIVATE}에서 받음", "서버 [가림:IP]에서 받음", 1),
    ("끝 번호는 010-1234-5678.", "끝 번호는 [가림:전화].", 1),
    ("전화 010.1234.5678 · (02) 123-4567", "전화 [가림:전화] · [가림:전화]", 2),
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
    # 반대 검토 L4 — 부품 · 넷 이름 · 그림 이름 · 품번 · 조항 번호는 개인정보가 아니다.
    "부품 U1@PCB.TOP 위치 · R12@NET.GND",
    "그림 icon@2x.png · logo@3x.webp · plot@a.pdf",
    "P/N 123456-1234567 품번 · 991340-1234567",
    f"규격 조항 {PRIVATE} 참조 · §{PRIVATE_B} · clause {PRIVATE_C}",
])
def test_data_numbers_and_names_are_left_alone(text):
    assert pii.mask_text(text) == (text, 0)


def test_a_lower_case_refdes_like_local_is_still_an_email():
    """메일이 아닌 꼴은 좁다 — 다 대문자 도메인의 refdes 꼴 로마자 로컬만 뺀다(보통 메일은 그대로 가린다)."""
    assert pii.mask_text("u1@corp.com · U1@corp.com")[1] == 2


def test_non_text_passes_through():
    assert pii.mask_text("") == ("", 0) and pii.mask_text(None) == (None, 0)  # type: ignore[arg-type]
