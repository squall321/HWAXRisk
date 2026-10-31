# 계면 목록 절단(plan §2.5.1 · §3.3.6) — 쌍의 한쪽이라도 잘린 kind 의 엣지 · 파라메트릭 변경은 truncated 로 빠지고 의미 사건을 만들지 않는다
"""B25(포털 docs/leftovers-1017/triage-1031.md · design-risk-review 125).

합성 쌍은 diff 픽스처 base(PLATE_2↔BRACKET_L 간섭 1건)에서 한쪽만 그 간섭 행을 잃고 그쪽 mcad 의
`stats.interfaces_truncated` 가 `{interference: 1}` 인 모양이다 — 5,000행에서 잘린 캡처가 '간섭이 사라졌다' 고 말하던 바로 그 꼴이다.
항목은 diff_json 에 수치째 남고(제외 사유 `truncated`), 검토 단위에서는 제외 단위가 갖는다(단서 줄로 셀에 가지 않는다).
"""
from __future__ import annotations

import copy
import json

import pytest

from app import diff, units
from tests.conftest import FIXTURES_DIR

PAIRS_DIR = FIXTURES_DIR / "diff_pairs"
INTERFERENCE_EID = "e:c650f4ca3da5"          # base 의 PLATE_2↔BRACKET_L interference


@pytest.fixture
def base_ir() -> dict:
    return json.loads((PAIRS_DIR / "base.json").read_text(encoding="utf-8"))


def _mcad(ir: dict) -> dict:
    return next(s for s in ir["sources"] if s["kind"] == "mcad")


def _truncate(ir: dict, by_kind: dict | None, *, drop_eid: str | None = INTERFERENCE_EID) -> dict:
    """그 스냅샷을 '잘린 캡처' 로 만든다 — 행 하나를 빼고(롤업의 엣지 수도 같이), degraded 와 kind 별 못 받은 수를 단다.

    `by_kind=None` 은 종류별 수가 없던 옛 캡처(degraded 만 있다)다."""
    out = copy.deepcopy(ir)
    if drop_eid:
        dropped = next(e for e in out["edges"] if e["eid"] == drop_eid)
        out["edges"] = [e for e in out["edges"] if e["eid"] != drop_eid]
        for row in out["rollups"]["by_assembly"]:
            internal = dict(row["edges_internal"])
            internal[dropped["kind"]] -= 1
            row["edges_internal"] = {k: v for k, v in internal.items() if v}
    mcad = _mcad(out)
    mcad["degraded"] = sorted(set(mcad["degraded"]) | {"interfaces_truncated"})
    if by_kind is not None:
        mcad["stats"] = dict(mcad["stats"], interfaces_truncated=dict(by_kind))
    return out


def _codes(d: dict) -> list[str]:
    return sorted(e["code"] for e in d["semantic"]["events"])


def _edge_change(d: dict, eid: str) -> dict:
    return next(c for c in d["structural"]["edge_changes"] if eid in (c["eid_base"], c["eid_target"]))


def test_a_truncated_target_does_not_report_that_the_interference_disappeared(base_ir):
    target = _truncate(base_ir, {"interference": 1})
    d = diff.compute_diff(base_ir, target)
    # 잘린 쪽의 빠진 간섭은 사건이 아니다 — iface.removed · 롤업 변화 둘 다 없다.
    assert _codes(d) == []
    change = _edge_change(d, INTERFERENCE_EID)
    assert (change["op"], change["kind_from"], change["excluded_reason"]) == ("removed", "interference", "truncated")
    assert change["text"]                                         # 항목은 diff_json 에 남는다
    # 제외 건수에 truncated 한 건이 더해진다(픽스처 자체의 null_one_side 는 자기 비교에도 있다).
    assert d["stats"]["edges_removed"] == 1 and d["stats"]["excluded_by_reason"] == \
        dict(diff.compute_diff(base_ir, base_ir)["stats"]["excluded_by_reason"], truncated=1)
    moved = [r for r in d["parametric"]["rollup_delta"]
             if r["edges_internal"]["before"] != r["edges_internal"]["after"]]
    assert moved and {r["excluded_reason"] for r in moved} == {"truncated"}
    # 잘리지 않은 비교에서는 같은 변화가 사건이다(시험이 빈 것을 단언한 게 아니다).
    honest = copy.deepcopy(target)
    _mcad(honest)["degraded"] = []
    _mcad(honest)["stats"].pop("interfaces_truncated")
    assert _codes(diff.compute_diff(base_ir, honest)) == ["asm.rollup_changed", "asm.rollup_changed", "iface.removed"]


def test_a_truncated_base_does_not_report_a_new_interference(base_ir):
    base = _truncate(base_ir, {"interference": 1})
    d = diff.compute_diff(base, base_ir)
    assert _codes(d) == []
    change = _edge_change(d, INTERFERENCE_EID)
    assert (change["op"], change["kind_to"], change["excluded_reason"]) == ("added", "interference", "truncated")


def test_parametric_change_of_a_truncated_kind_is_kept_but_excluded(base_ir):
    """두 쪽 다 있는 간섭이라도 그 kind 가 한쪽에서 잘렸으면 관통 깊이 변화는 사건이 아니다(정렬 규칙상 남은 행의 값만 보인다)."""
    base = copy.deepcopy(base_ir)
    for ir in (base,):
        edge = next(e for e in ir["edges"] if e["eid"] == INTERFERENCE_EID)
        edge["attrs"].update(penetration_depth_is_lower_bound=False, penetration_volume=0.01)
    target = copy.deepcopy(base)
    next(e for e in target["edges"] if e["eid"] == INTERFERENCE_EID)["attrs"]["penetration_depth"] = 0.30
    assert _codes(diff.compute_diff(base, target)) == ["iface.penetration_changed"]

    target = _truncate(target, {"interference": 7}, drop_eid=None)
    d = diff.compute_diff(base, target)
    assert _codes(d) == []
    item = next(p for p in d["parametric"]["edge_params"] if p["attr"] == "penetration_depth")
    assert (item["flag"], item["before"], item["after"], item["excluded_reason"]) == ("changed", 0.05, 0.30, "truncated")


def test_only_the_truncated_kind_is_excluded(base_ir):
    """잘린 kind 가 tied 뿐이면 간섭이 사라진 것은 사건이다 — 사유는 kind 별이다(롤업 엣지 수는 어느 단위의 행이 빠졌는지 몰라 뺀다)."""
    target = _truncate(base_ir, {"tied": 4})
    d = diff.compute_diff(base_ir, target)
    assert _codes(d) == ["iface.removed"]
    assert _edge_change(d, INTERFERENCE_EID)["excluded_reason"] is None


def test_a_capture_without_per_kind_counts_excludes_every_interface_kind(base_ir):
    """종류별 수가 없는 옛 캡처(degraded 에 interfaces_truncated 만)는 어느 kind 가 잘렸는지 몰라 네 kind 전부를 뺀다."""
    target = _truncate(base_ir, None)
    d = diff.compute_diff(base_ir, target)
    assert _codes(d) == []
    assert _edge_change(d, INTERFERENCE_EID)["excluded_reason"] == "truncated"


def test_truncated_items_go_to_the_excluded_unit_not_to_a_review_cell(base_ir):
    """검토 단위에서 truncated 는 capture_partial 처럼 제외 단위가 갖는다 — 단서 줄로 실으면 '사라졌다' 가 셀에 간다."""
    target = _truncate(base_ir, {"interference": 1})
    d = diff.compute_diff(base_ir, target)
    built = units.build_diff_units(d, units.view_of(base_ir, target))
    cid = _edge_change(d, INTERFERENCE_EID)["cid"]
    owners = [u for u in built["units"] if cid in u["cids"]]
    assert [u["kind"] for u in owners] == ["excluded"]
    line = next(line for line in owners[0]["lines"] if line["ref"] == cid)
    assert line["klass"] == "excluded" and line["caveat"] == "truncated"
