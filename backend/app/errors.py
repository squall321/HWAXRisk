# 표준 예외 AppError(code·message·http_status) — REST 는 {error:{code,message}} 로, MCP 도구는 dict 로 변환한다
from __future__ import annotations

# 코드 — E100 입력 스키마 위반 · E300 저장소·자산 IO 오류 · E404 대상 없음 · E500 내부 예외(메시지는 발생 지점에서 한국어로).


class AppError(Exception):
    """코드·메시지·HTTP 상태를 함께 갖는 표준 예외."""

    def __init__(self, code: str, message: str, http_status: int = 500,
                 detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        # 기계 판독용 부가 필드(예: 409 gate_blocked 의 {gates, reason}) — 본문 최상위에 함께 실린다.
        self.detail = dict(detail or {})

    def to_dict(self) -> dict:
        """REST 응답 본문 {error:{code,message}, …detail} 형식으로 변환."""
        return {"error": {"code": self.code, "message": self.message}, **self.detail}
