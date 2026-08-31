# 어댑터 레지스트리 v0 — mcad→heax-step_forge(planned) · dyna→heax-kooremapper_mcp(planned) · ecad→None(contract_only), /api/meta/adapters 의 원천
from __future__ import annotations

from app.adapters.base import IrAdapter

# P0 고정 목록. 게이트웨이 /tools-map 도구명 집합으로 kind 를 바인딩하는 발견 로직(plan §8.2.11)은 P1 에서 이 목록을 대체한다.
ADAPTERS: tuple[IrAdapter, ...] = (
    IrAdapter(kind="mcad", app_key="heax-step_forge", status="planned"),
    IrAdapter(kind="dyna", app_key="heax-kooremapper_mcp", status="planned"),
    IrAdapter(kind="ecad", app_key=None, status="contract_only"),
)


def list_adapters() -> list[dict]:
    """/api/meta/adapters 본문 — [{kind, app, status}]."""
    return [a.to_dict() for a in ADAPTERS]
