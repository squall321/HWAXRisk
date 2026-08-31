# ODB hub(ecad) 어댑터 스텁 — 계약 4도구가 게이트웨이에 보이기 전까지 discover 만 하고 capture 는 빈 결과 + ecad_absent 다(plan §2.5.3·§2.13.5)
from __future__ import annotations

from typing import Any, Mapping

from app.adapters.base import AdapterResult, CallRecorder, Principal, Probe, SourceAdapter
from app.common import now_epoch

ADAPTER_VERSION = "0.0-stub"
KIND = "ecad"

# 계약(docs/odb-adapter-contract.md)이 이행되면 이 4종이 게이트웨이에 뜨고 ecad.py 가 스텁을 대체한다.
REQUIRED_TOOLS: tuple[str, ...] = ("odb_get_board", "odb_list_components", "odb_list_nets", "odb_get_stackup")


class EcadStubAdapter(SourceAdapter):
    """계약만 있는 스텁. 어떤 소스도 호출하지 않고 노드·엣지를 만들지 않는다."""

    kind = KIND
    version = ADAPTER_VERSION
    required_tools = REQUIRED_TOOLS

    def __init__(self, app_key: str | None = None) -> None:
        self.app_key = app_key

    def discover(self, registry: Any) -> Probe:
        """4도구가 다 보이면 reachable=True 다 — 그때 ecad.py 로 교체한다(스텁은 그래도 capture 하지 않는다)."""
        return registry.probe(KIND, self.app_key)

    def capture(self, ref: Mapping[str, Any], principal: Principal | None,
                recorder: CallRecorder) -> AdapterResult:  # noqa: ARG002 — 스텁은 인자를 쓰지 않는다.
        captured_at = now_epoch()
        return {
            "source": {"kind": KIND, "app_key": None, "adapter_version": ADAPTER_VERSION, "channel": None,
                       "ref": {}, "source_hash": None, "degraded": ["ecad_absent"], "captured_at": captured_at},
            "nodes": [], "edges": [],
            "warnings": [{"severity": "INFO", "code": "ecad_absent",
                          "message": "ODB hub 어댑터 계약 4도구가 게이트웨이에 없어 ecad 소스를 싣지 않았다.",
                          "ref": None, "source_kind": KIND}],
            "degraded": ["ecad_absent"], "call_ids": [], "missing": {"ecad_absent": True},
        }
