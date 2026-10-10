# 통합 보고서의 표·성격 줄 — 주장과 인용을 자르지 않고, 성격 진술을 줄일 때는 남은 수를 밝힌다(절단 전수 조사 G1·G2)
from __future__ import annotations

import json

from app import narrative, registry
from tests.test_persist_panel import PANEL, PROJECT, _seed, _spec


def test_registry_table_carries_the_whole_claim_and_every_cite():
    claim = "낙하 시 상단 리브에 응력이 집중된다 " * 20
    cites = [{"ref": f"c:{i:012x}", "quote": "q"} for i in range(5)]
    row = {"merged_json": json.dumps({"claim": claim, "cites": cites, "names": ["HOUSING"], "domains": ["mech"]}),
           "cluster_key": "k1", "direction": "risk", "mechanism": "mechanical", "mechanism_detail": "drop_stress",
           "change_kind": "dimension", "subject_key": "ck:1", "severity": "중대", "judgement": "WARNING",
           "evidence_grade": "도구예측", "precedent": "none", "support": 1, "contested": 0, "status": "open"}
    line = registry._registry_table([row])[2]
    assert f"«{claim}»" in line and all(f"[c:{i:012x}]" in line for i in range(5))


def test_character_lines_count_what_they_leave_out(risk_store):
    """facet 마다 상위 둘을 싣되 남은 진술 수를 줄로 밝힌다 — 종전에는 셋째부터 흔적이 없었다."""
    _seed(risk_store)
    spec = _spec()
    statements = [dict(spec["character"]["facets"][0]["statements"][0], id=f"C{i}", text=f"성향 {i} 이 있다")
                  for i in range(1, 5)]
    spec["character"]["facets"][0]["statements"] = statements
    narrative.persist_panel_result(risk_store, PANEL, decision_text="", spec=spec, turns=[], attribution=None)
    lines = [ln for ln in registry._character_lines(risk_store, PROJECT) if ln.startswith("[vulnerability]")]
    assert len(lines) == 3 and lines[-1] == "[vulnerability] … 외 2건(과제 성격 프로파일에서 전부 본다)"
