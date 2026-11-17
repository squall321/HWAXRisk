# 근거 묶음의 개인정보 가림 — 메일 · 전화 · 사설 IPv4 · 주민등록번호 꼴 · 표지가 붙은 사번을 `[가림:<종류>]` 로 바꾸고, 데이터인 수 · 부품 · 그림 이름은 건드리지 않는다
"""HWAXPortal docs/request-1117 RK-02. 앱에는 가림 도우미가 없었다(게이트웨이 `_pii_mask_text` 는 다른 리포 — 나가는 응답 전체를 가린다). 사용자
결정(11-17)으로 게이트웨이는 근거 묶음 받기(`risk_get_evidence_bundle`)를 제 가림에서 빼므로(가림이 묶음 글을 고쳐 엔진의 지문 대조가 깨졌다) 묶음의
가림은 이 모듈 하나가 지킨다. 게이트웨이가 가림으로 계산 결과의 수를 망가뜨린 일(HWAXPortal docs/request-1030 HG-21 — 소수점 뒤 숫자열을 IMEI 로
읽었다)을 되풀이하지 않도록 보수적으로만 가린다.

모든 꼴의 앞뒤 거르개는 ASCII 글자 · 숫자다 — 한글이 바로 붙은 꼴('010-1234-5678로' · '담당자010-…' · '900101-1234567입니다')도 가린다(반대 검토
M3 — 종전에는 유니코드 \\w 거르개라 한글이 붙으면 가리지 않았다).

- 메일 — 로컬@도메인.최상위(2자 이상 글자). 다만 부품 · 넷 이름(로컬이 U1 · R12 꼴이고 도메인이 다 대문자 — U1@PCB.TOP)과 그림 파일 이름(도메인이
  '2x.png' 꼴이거나 최상위가 그림 · 문서 파일 확장자)은 메일이 아니다(반대 검토 L4).
- 전화 — 휴대 01x 와 지역 0x 번호를 하이픈 · 빈칸으로 가른 꼴, 휴대 머리의 점 꼴(010.1234.5678), 괄호 지역 번호((02) 123-4567), +82 로 시작하는 꼴. 가르지 않은 숫자열(01012345678)은 데이터 id 와 가를 수
  없어 가리지 않는다. 문장 끝 마침표는 막지 않는다.
- 사설 IPv4 — 10/8 · 172.16/12 · 192.168/16 만, 네 마디 모두 0~255. 소수점 · 숫자에 붙은 꼴(1.10.0.0.5 · 3.192.168.1.1.2)은 주소가 아니다. 앞에
  조항 · 절 · 표 · 그림 낱말이 오면(조항 10.1.2.3 · §10.1.2.3 · clause 10.1.2.3) 번호 매긴 조항이라 주소가 아니다(반대 검토 L4).
- 주민등록번호 꼴 — 6자리-7자리이고 앞 여섯이 날짜(월 01~12 · 일 01~31)이며 뒤 첫 자리가 1~4 일 때만(품번 123456-1234567 은 아니다 — 반대 검토 L4).
- 사번 — '사번 · 사원번호 · employee id · emp no' 표지 뒤의 영숫자 id 만(표지 없는 숫자는 데이터다).
- 사람 이름은 꼴로 가르지 않는다(원천에서 가린다 — 게이트웨이와 같은 결정). 가림 표지는 게이트웨이와 같은 `[가림:<종류>]` 다.
"""
from __future__ import annotations

import ipaddress
import re

MARK = "[가림:"
_A = re.ASCII
_EMAIL = re.compile(r"(?<![A-Za-z0-9_.%+-])([A-Za-z0-9_.%+-]+)@((?:[A-Za-z0-9-]+\.)+([A-Za-z]{2,}))(?![A-Za-z0-9_-]|\.[A-Za-z0-9])", _A)
_PHONE = re.compile(
    r"(?<![A-Za-z0-9_.+-])(?:"
    r"\+82[- ]?(?:1[016789]|[2-6][0-9]?)[- ]?\d{3,4}[- ]?\d{4}"          # +82 10-1234-5678 · +82-2-123-4567
    r"|01[016789][- ]\d{3,4}[- ]\d{4}"                                     # 010-1234-5678 · 010 1234 5678
    r"|01[016789]\.\d{3,4}\.\d{4}"                                          # 010.1234.5678(휴대 머리일 때만 — 소수와 가른다)
    r"|0(?:2|[3-6][1-5])[- ]\d{3,4}[- ]\d{4}"                              # 02-123-4567 · 031-123-4567
    r"|\(0(?:2|[3-6][1-5])\)\s?\d{3,4}-\d{4}"                               # (02) 123-4567
    r")(?![A-Za-z0-9_-]|\.\d)", _A)
_IPV4 = re.compile(r"(?<![A-Za-z0-9_.])(\d{1,3}(?:\.\d{1,3}){3})(?![A-Za-z0-9_]|\.\d)", _A)
_RRN = re.compile(r"(?<![A-Za-z0-9_.-])\d{2}(\d{2})(\d{2})-[1-4]\d{6}(?![A-Za-z0-9_-]|\.\d)", _A)
# 표지와 id 사이 — '\s*(?:[:：=]\s*)?' 다(옛 '\s*[:：=]?\s*' 는 빈칸 덩이를 두 \s* 가 나눠 가지며 길이의 제곱으로 되짚었다 — 반대 검토 H1).
_EMPLOYEE = re.compile(r"((?:사번|사원\s?번호|employee\s?(?:id|no\.?|number)|emp\.?\s?no\.?)\s*(?:[:：=]\s*)?)([A-Za-z]{0,3}\d{4,10})(?![A-Za-z0-9_])",
                       re.I | _A)
_PRIVATE_NETS = tuple(ipaddress.IPv4Network(n) for n in ((10 << 24, 8), ((172 << 24) | (16 << 16), 12), ((192 << 24) | (168 << 16), 16)))
# 메일이 아닌 꼴 — 부품 · 넷 이름의 로컬(refdes 꼴)과 다 대문자 도메인, 그림 배율 도메인(2x · 3x), 파일 확장자 최상위.
_REFDES_LOCAL = re.compile(r"[A-Z]{1,4}\d{1,6}", _A)
_SCALE_LABEL = re.compile(r"\d+x", _A)
_FILE_TLDS = frozenset({"png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "tif", "tiff", "pdf", "csv", "json", "txt", "xml", "step", "stp",
                        "xlsx", "xls", "docx", "doc", "pptx", "ppt", "zip", "gz", "html", "htm", "md"})
# 번호 매긴 조항 — 사설 IP 꼴 바로 앞(빈칸 몇 개까지)에 이 낱말이 오면 주소가 아니다.
_CLAUSE_BEFORE = re.compile(r"(?:조항|조|항|절|장|표|그림|§|clause|section|sec\.?|para(?:graph)?|fig\.?|figure|table)\s{0,3}\Z", re.I | _A)


def _is_email(m: re.Match) -> bool:
    local, domain, tld = m.group(1), m.group(2), m.group(3)
    if tld.lower() in _FILE_TLDS or _SCALE_LABEL.fullmatch(domain.split(".", 1)[0]):
        return False
    if _REFDES_LOCAL.fullmatch(local) and domain.upper() == domain:
        return False
    return True


def _is_birth(m: re.Match) -> bool:
    month, day = int(m.group(1)), int(m.group(2))
    return 1 <= month <= 12 and 1 <= day <= 31


def mask_text(text: str) -> tuple[str, int]:
    """(가린 글, 가린 수). 글이 아니면 그대로(0)다."""
    if not isinstance(text, str) or not text:
        return text, 0
    count = 0

    def sub(kind: str, keep=None):
        def repl(m: re.Match) -> str:
            nonlocal count
            if keep is not None and not keep(m):
                return m.group(0)
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
        if _CLAUSE_BEFORE.search(m.string, max(0, m.start() - 16), m.start()):
            return m.group(0)
        count += 1
        return f"{MARK}IP]"

    def employee(m: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{m.group(1)}{MARK}사번]"

    out = _EMAIL.sub(sub("메일", _is_email), text)
    out = _RRN.sub(sub("주민번호", _is_birth), out)
    out = _PHONE.sub(sub("전화"), out)
    out = _IPV4.sub(ip, out)
    out = _EMPLOYEE.sub(employee, out)
    return out, count
