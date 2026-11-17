# 근거 묶음의 개인정보 가림 — 메일 · 전화 · 사설 IPv4 · 주민등록번호 꼴 · 표지가 붙은 사번을 `[가림:<종류>]` 로 바꾸고, 데이터인 수는 건드리지 않는다
"""HWAXPortal docs/request-1117 RK-02. 앱에는 가림 도우미가 없었다(게이트웨이 `_pii_mask_text` 는 다른 리포 — 나가는 응답 전체를 가린다).
게이트웨이가 가림으로 계산 결과의 수를 망가뜨린 일(HWAXPortal docs/request-1030 HG-21 — 소수점 뒤 숫자열을 IMEI 로 읽었다)을 되풀이하지 않도록
보수적으로만 가린다.

- 메일 — 로컬@도메인.최상위(2자 이상 글자).
- 전화 — 휴대 01x 와 지역 0x 번호를 하이픈 · 빈칸으로 가른 꼴, 또는 +82 로 시작하는 꼴. 가르지 않은 숫자열(01012345678)은 데이터 id 와 가를 수
  없어 가리지 않는다.
- 사설 IPv4 — 10/8 · 172.16/12 · 192.168/16 만, 네 마디 모두 0~255. 소수점 · 숫자에 붙은 꼴(1.10.0.0.5 · 3.192.168.1.1.2)은 주소가 아니다.
- 주민등록번호 꼴 — 6자리-7자리(뒤 첫 자리 1~4).
- 사번 — '사번 · 사원번호 · employee id · emp no' 표지 뒤의 영숫자 id 만(표지 없는 숫자는 데이터다).
- 사람 이름은 꼴로 가르지 않는다(원천에서 가린다 — 게이트웨이와 같은 결정). 가림 표지는 게이트웨이와 같은 `[가림:<종류>]` 다.
"""
from __future__ import annotations

import ipaddress
import re

MARK = "[가림:"
_EMAIL = re.compile(r"(?<![A-Za-z0-9_.%+-])[A-Za-z0-9_.%+-]+@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?![A-Za-z0-9_-]|\.[A-Za-z0-9])")
_PHONE = re.compile(
    r"(?<![\w.+-])(?:"
    r"\+82[- ]?(?:1[016789]|[2-6][0-9]?)[- ]?\d{3,4}[- ]?\d{4}"          # +82 10-1234-5678 · +82-2-123-4567
    r"|01[016789][- ]\d{3,4}[- ]\d{4}"                                     # 010-1234-5678 · 010 1234 5678
    r"|0(?:2|[3-6][1-5])[- ]\d{3,4}[- ]\d{4}"                              # 02-123-4567 · 031-123-4567
    r")(?![\w.-]|\.\d)")
_IPV4 = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?![\w]|\.\d)")
_RRN = re.compile(r"(?<![\w.-])\d{6}-[1-4]\d{6}(?![\w.-])")
_EMPLOYEE = re.compile(r"((?:사번|사원\s?번호|employee\s?(?:id|no\.?|number)|emp\.?\s?no\.?)\s*[:：=]?\s*)([A-Za-z]{0,3}\d{4,10})(?![\w])",
                       re.I)
_PRIVATE_NETS = tuple(ipaddress.IPv4Network(n) for n in ((10 << 24, 8), ((172 << 24) | (16 << 16), 12), ((192 << 24) | (168 << 16), 16)))


def mask_text(text: str) -> tuple[str, int]:
    """(가린 글, 가린 수). 글이 아니면 그대로(0)다."""
    if not isinstance(text, str) or not text:
        return text, 0
    count = 0

    def sub(kind: str):
        def repl(m: re.Match) -> str:
            nonlocal count
            count += 1
            return f"{MARK}{kind}]"
        return repl

    def ip(m: re.Match) -> str:
        nonlocal count
        try:
            addr = ipaddress.IPv4Address(m.group(1))
        except ValueError:            # 255 를 넘는 마디 · 앞자리 0 — 주소가 아니다
            return m.group(0)
        if not any(addr in net for net in _PRIVATE_NETS):
            return m.group(0)
        count += 1
        return f"{MARK}IP]"

    def employee(m: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{m.group(1)}{MARK}사번]"

    out = _EMAIL.sub(sub("메일"), text)
    out = _RRN.sub(sub("주민번호"), out)
    out = _PHONE.sub(sub("전화"), out)
    out = _IPV4.sub(ip, out)
    out = _EMPLOYEE.sub(employee, out)
    return out, count
