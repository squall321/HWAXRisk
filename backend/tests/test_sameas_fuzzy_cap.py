# same-as 6단계 상한(plan §2.6.3) — 남은 노드 곱이 800×800 을 넘으면 헝가리안을 건너뛰고 스냅샷 degraded · 경고 · sig, 쌍 caveat 로 남는다
"""B24(포털 docs/leftovers-1017/triage-1031.md · design-risk-review 108).

- 상한은 `len(rest_a) × len(rest_b) > 800 × 800` 이다 — 801 × 801 은 건너뛰고 799 × 799(와 800 × 800)는 그대로 돈다.
- 건너뛰었는지는 `score_pair` 첩자로 본다. 옛 코드는 801 × 801 에서도 점수를 매기고(641,601번) 1,602 행렬의 순수 파이썬 헝가리안을
  돌린다 — 첩자가 첫 호출에서 실패시켜 그 길이 몇 시간 매달리지 않게 한다.
- 스냅샷(intra)은 두 도메인 소스의 degraded 와 경고 한 줄, `sig:capture.fuzzy_skipped` 로, 쌍(pair)은 대응층의 `fuzzy_skipped` 와
  의미층 · 이벤트의 `caveat='fuzzy_skipped_large'` 로 남는다. 같은 입력이면 ir_hash 가 같다.
"""
from __future__ import annotations

import copy
import json

import pytest

from app import diff, ir_builder, sameas
from app import state as state_module
from app.common import canonical_json
from tests.conftest import FIXTURES_DIR

PROJECT = "e73c023a2e8e90349bb4d853730e1bfc"
OWNER = "user@example.com"
IR_FIXTURES = FIXTURES_DIR / "ir"


def _never(*_args, **_kwargs):
    raise AssertionError("6단계 점수를 매겼다 — 남은 노드 곱이 800×800 을 넘는데 행렬을 짓는다")


def _pruned(calls: list):
    """점수를 셀 뿐 모두 가지치기되는 첩자 — 행렬 · 헝가리안까지 가지 않는다(799 × 799 의 1,598 행렬은 순수 파이썬으로 수 시간이다)."""
    def spy(*_args, **_kwargs):
        calls.append(1)
        return {"score": 0.0, "name_sim": 0.0, "geom_sim": 0.0, "material_eq": 0.5, "neighbor_sim": 0.5}
    return spy


def _mcad_nodes(prefix: str, n: int, *, extra_exact: int = 0) -> list[dict]:
    """같은 도메인 노드 n 개 — 이름 · canon_key · 기하가 상대와 겹치지 않아 1~5단계가 아무것도 잇지 않는다.

    `extra_exact` 개는 상대와 canon_key 가 같아 3단계(exact_path)가 잇는다 — 남은 노드 수를 앞 단계가 줄이는지 본다."""
    out = []
    for i in range(n):
        out.append({"nid": f"p:{prefix}{i:011x}"[:14], "canon_key": f"mcad:/syn.step/ASM/{prefix}_{i:04d}",
                    "domain": "mcad", "kind": "part", "name_norm": f"{prefix.lower()}_{i:04d}",
                    "name_norm_canon": f"{prefix.lower()}x{i:04d}", "geom_fp": None, "status_flags": [],
                    "attrs": {"size_sorted": [10.0 + i, 5.0, 1.0]}})
    for j in range(extra_exact):
        out.append({"nid": f"p:{prefix}e{j:010x}"[:14], "canon_key": f"mcad:/syn.step/ASM/SHARED_{j:04d}",
                    "domain": "mcad", "kind": "part", "name_norm": f"shared_{j:04d}", "name_norm_canon": f"shared{j:04d}",
                    "geom_fp": None, "status_flags": [], "attrs": {"size_sorted": [3.0, 2.0, 1.0]}})
    return out


# ---------------------------------------------------------------- 사다리(resolve · fuzzy_skip)
def test_801_by_801_skips_the_fuzzy_stage_and_says_how_large_the_rest_was(monkeypatch):
    monkeypatch.setattr(sameas, "score_pair", _never)
    base, target = _mcad_nodes("a", 801, extra_exact=3), _mcad_nodes("b", 801, extra_exact=3)
    links = sameas.resolve(base, target, [], [], "pair", None)
    # 1~5단계까지의 결과로 진행한다 — 3단계가 이은 셋만 있고 fuzzy 레코드는 없다(pending 이 없어 G2 에 세지 않는다).
    assert sorted(r["method"] for r in links) == ["exact_path"] * 3
    assert sameas.fuzzy_skip(base, target, links) == {"rest_a": 801, "rest_b": 801, "limit": 640_000}
    # 같은 입력이면 같은 레코드다.
    assert canonical_json(sameas.resolve(base, target, [], [], "pair", None)) == canonical_json(links)


@pytest.mark.parametrize("n", [799, 800])
def test_799_by_799_and_800_by_800_still_score_every_pair(monkeypatch, n):
    """곱이 상한과 같은 800 × 800 까지는 그대로 돈다 — `>` 이지 `≥` 가 아니다."""
    calls: list = []
    monkeypatch.setattr(sameas, "score_pair", _pruned(calls))
    base, target = _mcad_nodes("a", n, extra_exact=3), _mcad_nodes("b", n, extra_exact=3)
    links = sameas.resolve(base, target, [], [], "pair", None)
    assert len(calls) == n * n
    assert sameas.fuzzy_skip(base, target, links) is None


@pytest.mark.parametrize("na,nb,skipped", [(800, 800, False), (800, 801, True), (801, 799, False), (801, 800, True),
                                              (1, 640_000, False), (1, 640_001, True)])
def test_the_cap_is_a_strict_product_bound(na, nb, skipped):
    """`> 800 × 800` 이다 — 곱이 정확히 640,000 이면 돈다. 한쪽이 1 이어도 곱으로 잰다."""
    a = [{"nid": f"p:a{i:011x}", "domain": "mcad"} for i in range(na)]
    b = [{"nid": f"p:b{i:011x}", "domain": "mcad"} for i in range(nb)]
    assert (sameas.fuzzy_skip(a, b, []) is not None) is skipped


def test_rest_counts_follow_the_ladder_rules_ledger_ecad_and_low_scores():
    """fuzzy_skip 은 resolve 와 같은 규칙으로 남은 노드를 센다 — 원장 confirmed 와 0.90 이상 auto 는 가져가고, 원장 rejected ·
    pending · 0.90 밑 auto(크기 감점 fingerprint)는 남기며, ecad 는 6단계에 들지 않는다."""
    a = [{"nid": f"p:a{i:011x}", "domain": "mcad"} for i in range(802)] + [{"nid": "p:aecad0000000", "domain": "ecad"}]
    b = [{"nid": f"p:b{i:011x}", "domain": "mcad"} for i in range(802)]
    taken = [{"a": a[0]["nid"], "b": b[0]["nid"], "method": "ledger", "status": "confirmed", "score": 1.0},
             {"a": a[1]["nid"], "b": b[1]["nid"], "method": "name_norm", "status": "auto", "score": 0.95}]
    kept = [{"a": a[2]["nid"], "b": b[2]["nid"], "method": "ledger", "status": "rejected", "score": 1.0},
            {"a": a[3]["nid"], "b": b[3]["nid"], "method": "fingerprint", "status": "pending", "score": 0.85},
            {"a": a[4]["nid"], "b": b[4]["nid"], "method": "fingerprint", "status": "auto", "score": 0.85},
            {"a": a[5]["nid"], "b": b[5]["nid"], "method": "fuzzy", "status": "auto", "score": 0.97}]
    # 둘을 가져가 800 × 800 — 상한과 같아 건너뛰지 않는다. 하나만 가져가면 801 × 801 이라 건너뛴다.
    assert sameas.fuzzy_skip(a, b, taken + kept) is None
    assert sameas.fuzzy_skip(a, b, taken[:1] + kept) == {"rest_a": 801, "rest_b": 801, "limit": 640_000}


# ---------------------------------------------------------------- 스냅샷(intra) — degraded · 경고 · sig · ir_hash
def _adapter_results(n: int) -> list[dict]:
    """mcad 리프 n 개와 dyna pid n 개 — 이름 · 크기가 서로 닮지 않아 도메인 간 대응이 5단계까지 하나도 서지 않는다."""
    mcad = json.loads((IR_FIXTURES / "adapter_mcad_basic.json").read_text(encoding="utf-8"))
    dyna = json.loads((IR_FIXTURES / "adapter_dyna_basic.json").read_text(encoding="utf-8"))
    part = next(node for node in mcad["nodes"] if node["kind"] == "part")
    pid = dyna["nodes"][0]
    mcad["nodes"] = [node for node in mcad["nodes"] if node["kind"] != "part"]
    mcad["edges"] = []
    for i in range(n):
        node = copy.deepcopy(part)
        node["canon_key"] = f"mcad:/a_stack.step/STACK_ASM/MCX_{i:04d}"
        node["label"] = f"MCX_{i:04d}"
        node["local_key"] = f"/sif-e2e/a_stack.step/STACK_ASM/MCX_{i:04d}"
        node["attrs"]["size_sorted"] = [50.0 + i, 40.0, 1.2]
        mcad["nodes"].append(node)
    dyna["nodes"], dyna["edges"] = [], []
    for i in range(n):
        node = copy.deepcopy(pid)
        node["canon_key"] = f"dyna:abcd1234:{i + 1}"
        node["label"] = f"Stack\\DYQ_{i:04d}"
        node["local_key"] = str(i + 1)
        node["attrs"]["title"] = node["label"]
        node["attrs"]["size_sorted"] = [7.0, 3.0, 0.3]
        dyna["nodes"].append(node)
    return [mcad, dyna]


def _build(results: list[dict]) -> dict:
    return ir_builder.build_ir(project_id=PROJECT, owner_sub=OWNER, label="SKIP", adapter_results=copy.deepcopy(results),
                               captured_at=1756600000)


def test_a_snapshot_with_an_801_by_801_rest_records_the_skip_and_keeps_its_hash(monkeypatch):
    monkeypatch.setattr(sameas, "score_pair", _never)
    results = _adapter_results(801)
    ir = _build(results)
    assert ir["same_as"] == []                                   # 1~5단계가 잇지 못했고 6단계는 돌지 않았다
    for kind in ("mcad", "dyna"):
        source = next(s for s in ir["sources"] if s["kind"] == kind)
        assert "fuzzy_skipped_large" in source["degraded"], kind
    # mcad 쪽은 리프 801 에 파일 · 조립 노드 둘이 더 있다(도메인 쌍은 그 도메인의 노드 전부를 본다) — 801 × 803 이다.
    n_dyna = sum(1 for node in ir["nodes"] if node["domain"] == "dyna")
    n_mcad = sum(1 for node in ir["nodes"] if node["domain"] == "mcad")
    assert (n_dyna, n_mcad) == (801, 803)
    warning = next(w for w in ir["warnings"] if w["code"] == "fuzzy_skipped_large")
    assert warning["source_kind"] == "ir_builder" and f"{n_dyna} × {n_mcad}" in warning["message"]
    assert warning["ref"] == "dyna~mcad"
    # 같은 입력이면 같은 해시다 — 건너뛴 사실(degraded · 경고)은 해시 입력이 아니다.
    assert _build(results)["ir_hash"] == ir["ir_hash"]

    state = state_module.build_state(ir)
    flag = state["signals"]["capture.fuzzy_skipped"]
    assert flag["kind"] == "flag" and flag["value"] is True and flag["known"] is True
    assert flag["refs"] == ["warn:fuzzy_skipped_large#dyna~mcad"]
    assert "6단계 생략" in flag["text"] and "dyna·mcad" in flag["text"]


def test_a_small_snapshot_runs_the_fuzzy_stage_and_its_flag_is_false():
    ir = _build(_adapter_results(3))
    assert all("fuzzy_skipped_large" not in s["degraded"] for s in ir["sources"])
    assert not [w for w in ir["warnings"] if w["code"] == "fuzzy_skipped_large"]
    flag = state_module.build_state(ir)["signals"]["capture.fuzzy_skipped"]
    assert flag["value"] is False and flag["text"] == "fuzzy_skipped=false"


# ---------------------------------------------------------------- 쌍(pair) — 대응층 · 의미층 caveat
def _mcad_ir(prefix: str, n: int, thickness: float) -> dict:
    mcad = json.loads((IR_FIXTURES / "adapter_mcad_basic.json").read_text(encoding="utf-8"))
    part = next(node for node in mcad["nodes"] if node["kind"] == "part")
    mcad["nodes"] = [node for node in mcad["nodes"] if node["kind"] != "part"]
    mcad["edges"] = []
    for i in range(n):
        node = copy.deepcopy(part)
        node["canon_key"] = f"mcad:/a_stack.step/STACK_ASM/{prefix}_{i:04d}"
        node["label"] = f"{prefix}_{i:04d}"
        node["local_key"] = f"/sif-e2e/a_stack.step/STACK_ASM/{prefix}_{i:04d}"
        # 두께를 달리해 기하 지문이 겹치지 않게 한다(겹치면 4단계가 이름 다른 쌍을 0.85 pending 으로 묶는다).
        node["attrs"]["size_sorted"] = [50.0 + i, 40.0, thickness]
        node["attrs"]["size_def"] = [50.0 + i, 40.0, thickness]
        node["attrs"]["min_dim"] = thickness
        mcad["nodes"].append(node)
    return _build([mcad])


@pytest.mark.parametrize("n,skipped", [(801, True), (799, False)])
def test_a_pair_beyond_the_cap_carries_the_caveat_on_its_semantic_layer(monkeypatch, n, skipped):
    calls: list = []
    monkeypatch.setattr(sameas, "score_pair", _never if skipped else _pruned(calls))
    base, target = _mcad_ir("BASEQ", n, 1.2), _mcad_ir("TGTZ", n, 1.7)
    first = diff.compute_diff(base, target)
    corr, semantic = first["correspondence"], first["semantic"]
    assert corr["pending_n"] == 0 and semantic["blocked_by"] is None     # 짝 없는 노드는 G2 를 막지 않는다
    events = semantic["events"]
    assert {e["code"] for e in events} == {"part.added", "part.removed"} and len(events) == 2 * n
    if skipped:
        assert corr["fuzzy_skipped"] == {"rest_base": n, "rest_target": n, "limit": 640_000}
        assert semantic["caveat"] == "fuzzy_skipped_large"
        assert {e.get("caveat") for e in events} == {"fuzzy_skipped_large"}
        assert calls == []
    else:
        assert corr["fuzzy_skipped"] is None and "caveat" not in semantic
        assert all(not e.get("caveat") for e in events)
        assert len(calls) == n * n
    again = diff.compute_diff(base, target)
    assert canonical_json({k: v for k, v in again.items() if k != "created_at"}) == \
        canonical_json({k: v for k, v in first.items() if k != "created_at"})


def test_a_parser_caveat_already_on_an_event_is_kept(monkeypatch):
    """세대가 섞인 쌍(parser_differs)의 이벤트는 그 표지를 지키고, 층 표지는 건너뛴 사실을 따로 단다."""
    monkeypatch.setattr(sameas, "score_pair", _never)
    base, target = _mcad_ir("BASEQ", 801, 1.2), _mcad_ir("TGTZ", 801, 1.7)
    next(s for s in target["sources"] if s["kind"] == "mcad")["app_version"] = {"version": "9.9"}
    next(s for s in base["sources"] if s["kind"] == "mcad")["app_version"] = {"version": "1.0"}
    out = diff.compute_diff(base, target)
    assert out["semantic"]["caveat"] == "fuzzy_skipped_large"
    assert {e["caveat"] for e in out["semantic"]["events"]} == {"parser_differs"}
