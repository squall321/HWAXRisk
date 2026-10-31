# 노드 500 · 엣지 2,000 합성 쌍의 diff 시간과 메모리(plan §9.3 P2 (7) · §10 #27) — compute_diff 5 s 안 · tracemalloc 피크 1.5 GB 밑
"""B26(포털 docs/leftovers-1017/triage-1031.md · design-risk-review 126).

쌍은 합성기(`app/devseed.py`)가 어댑터 결과로 만들고 IR · 대응 · diff 는 실제 생산자가 만든다 — 리프 362(dyna 짝 35%) · 조립 단위 8 ·
계면 밀도 9.0 에 무작위 변경 50건이면 한쪽마다 노드 ≥500 · 엣지 ≥2,000 이다. 시간은 대응(same-as 사다리)까지 든 `compute_diff`
한 번이고, 메모리는 같은 호출을 tracemalloc 아래에서 한 번 더 돌려 파이썬 할당 피크로 잰다(재는 동안은 느려지므로 시간과 따로 잰다).
피크가 1.5 GB 를 넘으면 매니페스트 `memory_gb` 를 3 으로 올린다(§10 #27). 잰 값은 context-notes 에 적는다.
"""
from __future__ import annotations

import time
import tracemalloc

from app import devseed, diff, ir_builder

SEED = 20261031
SPEC = devseed.SynthSpec(seed=SEED, n_parts=362, iface_per_part=9.0, twin_ratio=0.35, named_dims=0, hazards=False)
MUTATIONS = 50
NODES_MIN, EDGES_MIN = 500, 2_000
DIFF_BUDGET_S = 5.0
PEAK_LIMIT_BYTES = int(1.5 * 1024 ** 3)       # 이를 넘으면 매니페스트 memory_gb 2 → 3(§10 #27)


def synthetic_pair() -> tuple[dict, dict]:
    """노드 500 · 엣지 2,000 규모의 합성 쌍(IR 둘) — 결정적이다(같은 씨앗이면 같은 쌍)."""
    base, target, _records = devseed.apply_script(devseed.build_design(SPEC), devseed.random_script(MUTATIONS, SEED), SEED)
    out = []
    for design, captured_at in ((base, devseed.CAPTURED_AT), (target, devseed.CAPTURED_AT + 86400)):
        out.append(ir_builder.build_ir(project_id="5ca1e000000000000000000000000500", owner_sub="scale@example.com",
                                       label="SCALE", captured_at=captured_at,
                                       adapter_results=devseed.to_adapter_results(design, captured_at=captured_at)))
    return out[0], out[1]


def measure(base_ir: dict, target_ir: dict) -> dict:
    """compute_diff 한 번의 벽시계(초)와 tracemalloc 피크(바이트) — 둘은 따로 돈다."""
    started = time.perf_counter()
    result = diff.compute_diff(base_ir, target_ir)
    seconds = time.perf_counter() - started
    tracemalloc.start()
    try:
        diff.compute_diff(base_ir, target_ir)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return {"seconds": seconds, "peak_bytes": peak, "events": len(result["semantic"]["events"]),
            "blocked_by": result["semantic"]["blocked_by"]}


def test_a_500_node_2000_edge_pair_diffs_within_five_seconds_and_under_the_memory_line():
    base_ir, target_ir = synthetic_pair()
    for ir in (base_ir, target_ir):
        assert len(ir["nodes"]) >= NODES_MIN and len(ir["edges"]) >= EDGES_MIN, (len(ir["nodes"]), len(ir["edges"]))
    got = measure(base_ir, target_ir)
    # 막힌 diff 는 의미층을 건너뛰어 빨라 보인다 — 실제로 사건을 만든 쌍인지 먼저 본다.
    assert got["blocked_by"] is None and got["events"] > 0
    assert got["seconds"] < DIFF_BUDGET_S, got
    assert got["peak_bytes"] < PEAK_LIMIT_BYTES, got
