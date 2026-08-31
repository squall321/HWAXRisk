# IR 어댑터 베이스 v0 — kind(mcad|dyna|ecad)·app_key(게이트웨이 백엔드 키)·status(planned|contract_only) 만 갖는 기술자
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class IrAdapter:
    """소스 kind 하나를 rr_ir 로 읽는 어댑터의 기술자. 캡처 로직은 P1 부터 서브클래스가 채운다."""

    kind: str
    app_key: str | None
    status: str

    def to_dict(self) -> dict:
        """/api/meta/adapters 한 항목 {kind, app, status}."""
        d = asdict(self)
        return {"kind": d["kind"], "app": d["app_key"], "status": d["status"]}
