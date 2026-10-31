# 계면 목록 절단(plan §2.5.1 · §3.3.6) — 쌍의 한쪽이라도 잘린 kind 의 엣지 · 파라메트릭 변경은 truncated 로 빠지고 의미 사건을 만들지 않는다
"""B25(포털 docs/leftovers-1017/triage-1031.md · design-risk-review 125).

합성 쌍은 diff 픽스처 base(PLATE_2↔BRACKET_L 간섭 1건)에서 한쪽만 그 간섭 행을 잃고 그쪽 mcad 의
`stats.interfaces_truncated` 가 `{interference: 1}` 인 모양이다 — 5,000행에서 잘린 캡처가 '간섭이 사라졌다' 고 말하던 바로 그 꼴이다.
항목은 diff_json 에 수치째 남고(제외 사유 `truncated`), 검토 단위에서는 제외 단위가 갖는다(단서 줄로 셀에 가지 않는다).

반대 검토(10-31)가 찾은 다른 길 셋도 본다 — 잘린 계면을 읽는 명명 치수가 '미측정' 사건이 되던 것, 검토 단위가 잘린 간섭을 '삭제' 로 ·
그 부품을 '고아됨' 으로 싣던 것, 잘린 kind 가 그 조립 단위에 없어도 롤업 사건을 지우던 것(context-notes BL-7 ~ BL-9).
"""
from __future__ import annotations

import copy
import json

import pytest

from app import diff, ir_builder, units
from tests.conftest import FIXTURES_DIR

PAIRS_DIR = FIXTURES_DIR / "diff_pairs"
INTERFERENCE_EID = "e:c650f4ca3da5"          # base 의 PLATE_2↔BRACKET_L interference
TIED_EID = "e:f1dabe4da27f"                  # base 의 PLATE_1↔PLATE_2 tied
PLATE_1, BRACKET_L = "p:87ae2f56d589", "p:d8f6805b7766"
CLEARANCE_EID = ir_builder.make_eid("iface", PLATE_1, BRACKET_L)   # 시험이 더하는 PLATE_1↔BRACKET_L clearance


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


def _with_clearance(ir: dict, gap: float = 0.4) -> dict:
    """PLATE_1↔BRACKET_L clearance 한 행을 더한다 — base 픽스처에는 clearance 가 없는데 정렬 규칙상 가장 먼저 잘리는 kind 다."""
    out = copy.deepcopy(ir)
    edge = copy.deepcopy(next(e for e in out["edges"] if e["eid"] == INTERFERENCE_EID))
    edge.update(eid=CLEARANCE_EID, kind="clearance", a=PLATE_1, b=BRACKET_L, status="auto")
    edge["attrs"].update(min_gap=gap, contact_area_est=None, penetration_depth=None, note="근접")
    out["edges"].append(edge)
    return out


def _rebuilt(ir: dict, *drop: str, dim_defs: tuple = ()) -> dict:
    """행을 빼고(drop — eid) 롤업 · 명명 치수를 생산자 함수(ir_builder)로 다시 짓는다."""
    out = copy.deepcopy(ir)
    out["edges"] = [e for e in out["edges"] if e["eid"] not in drop]
    out["rollups"] = ir_builder.build_rollups(out["nodes"], out["edges"])
    if dim_defs:
        out["dims_named"] = ir_builder.evaluate_dims(out["nodes"], out["edges"], out.get("results"), list(dim_defs))
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
    """잘린 kind 가 tied 뿐이면 간섭이 사라진 것은 사건이다 — 사유는 kind 별이다. 롤업도 kind 별이다 — 그 단위의 tied 수는 두 쪽이
    같아 행은 비교 대상으로 남고 계면 수는 tied 를 뺀 수(간섭 1→0)다. BRACKET_L 은 잘리지 않은 간섭을 잃어 고아가 됐으니 그 전이도 그대로다.
    (반대 검토 10-31 전에는 어느 kind 든 잘리면 수가 움직인 롤업 행을 다 빼 롤업 사건이 사라졌다.)"""
    target = _truncate(base_ir, {"tied": 4})
    d = diff.compute_diff(base_ir, target)
    assert _codes(d) == ["asm.rollup_changed", "asm.rollup_changed", "iface.removed"]
    assert _edge_change(d, INTERFERENCE_EID)["excluded_reason"] is None
    rows = d["parametric"]["rollup_delta"]
    assert {(r["excluded_reason"], tuple(r["truncated_kinds"]), r["edges_internal"]["before"], r["edges_internal"]["after"])
            for r in rows} == {(None, ("tied",), 1, 0)}
    orphans = d["structural"]["orphans_delta"]
    assert orphans["became_orphan"] == [BRACKET_L] and orphans["truncated"] == {"became_orphan": [], "left_orphan": []}


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


# ---------------------------------------------------------------- 명명 치수(반대 검토 10-31 — BL-7)
DIM_DEFS = (
    {"name": "bracket_clear", "extractor": "edge[name=plate_1|bracket_l].attrs.min_gap", "unit": "mm"},
    {"name": "bracket_pen", "extractor": "edge[name=plate_2|bracket_l].attrs.penetration_depth", "unit": "mm"},
    {"name": "bracket_margin", "extractor": "dim(bracket_clear) + dim(bracket_pen)", "unit": "mm"},
    {"name": "plate_tie_gap", "extractor": "edge[ck=ck:01f70db1e74f|ck:860cf8b0d3d0].attrs.min_gap", "unit": "mm"},
)
CUT_DIMS = ("bracket_clear", "bracket_margin", "bracket_pen")


def test_a_named_dim_on_a_cut_interface_is_not_reported_unmeasured(base_ir):
    """잘린 clearance · interference 계면을 읽는 명명 치수와 그것을 읽는 파생 치수는 '미측정(ref 소실)' 사건이 아니고 검토 셀 · 요약
    [치수] 에도 가지 않는다 — 잘린 쪽에서 행이 빠져 ref 가 비었을 뿐이다. 잘리지 않은 tied 계면이 정말 사라져 빈 치수는 그대로 사건이다."""
    base = _rebuilt(_with_clearance(base_ir), dim_defs=DIM_DEFS)
    target = _rebuilt(_with_clearance(base_ir), CLEARANCE_EID, INTERFERENCE_EID, TIED_EID, dim_defs=DIM_DEFS)
    target = _truncate(target, {"clearance": 1, "interference": 1}, drop_eid=None)
    # 전제 — 잘린 쪽의 치수는 ref 가 비어 ref_missing(파생은 attr_null)이고 남은 쪽은 그 계면을 ref 로 읽었다.
    assert {r["name"]: (r["value"], r["null_reason"]) for r in target["dims_named"]} == {
        "bracket_clear": (None, "ref_missing"), "bracket_margin": (None, "attr_null"),
        "bracket_pen": (None, "ref_missing"), "plate_tie_gap": (None, "ref_missing")}
    assert {r["name"]: r["ref"] for r in base["dims_named"]}["bracket_clear"] == CLEARANCE_EID

    d = diff.compute_diff(base, target)
    dims = {item["name"]: (item["flag"], item["before"], item["excluded_reason"]) for item in d["parametric"]["dims_delta"]}
    assert dims == {"bracket_clear": ("null_one_side", 0.4, "truncated"),
                    "bracket_margin": ("null_one_side", 0.45, "truncated"),
                    "bracket_pen": ("null_one_side", 0.05, "truncated"),
                    "plate_tie_gap": ("null_one_side", 0.0, "null_one_side")}
    assert _codes(d) == ["dim.named_unmeasured", "iface.removed"]
    assert [e["subject_key"] for e in d["semantic"]["events"] if e["code"] == "dim.named_unmeasured"] == ["dim:plate_tie_gap"]

    built = units.build_diff_units(d, units.view_of(base, target))
    cids = {item["name"]: item["cid"] for item in d["parametric"]["dims_delta"]}
    for name in CUT_DIMS:
        owners = [u for u in built["units"] if cids[name] in u["cids"]]
        assert [u["kind"] for u in owners] == ["excluded"], name
        assert next(line for line in owners[0]["lines"] if line["ref"] == cids[name])["caveat"] == "truncated"
    assert [u["reviewable"] for u in built["units"] if cids["plate_tie_gap"] in u["cids"]] == [True]
    assert "plate_tie_gap" in d["summary_text"] and not [n for n in CUT_DIMS if n in d["summary_text"]]

    # 잘린 쪽이 base 여도 같다 — 남은 target 쪽의 ref 로 알아본다.
    back = diff.compute_diff(target, base)
    assert {item["name"]: (item["before"], item["excluded_reason"]) for item in back["parametric"]["dims_delta"]} == {
        "bracket_clear": (None, "truncated"), "bracket_margin": (None, "truncated"),
        "bracket_pen": (None, "truncated"), "plate_tie_gap": (None, "null_one_side")}


def test_a_dim_on_an_uncut_kind_is_still_compared_when_another_kind_is_cut(base_ir):
    """tied 계면을 읽는 치수는 clearance 만 잘린 쌍에서 그대로 비교된다 — 사유는 그 치수가 읽은 계면의 kind 로 정한다."""
    base = _rebuilt(_with_clearance(base_ir), dim_defs=DIM_DEFS)
    target = _rebuilt(_with_clearance(base_ir), TIED_EID, dim_defs=DIM_DEFS)
    d = diff.compute_diff(base, _truncate(target, {"clearance": 5}, drop_eid=None))
    dims = {item["name"]: item["excluded_reason"] for item in d["parametric"]["dims_delta"]}
    assert dims == {"bracket_clear": "truncated", "bracket_margin": "truncated", "bracket_pen": None,
                    "plate_tie_gap": "null_one_side"}
    assert [e["subject_key"] for e in d["semantic"]["events"] if e["code"] == "dim.named_unmeasured"] == ["dim:plate_tie_gap"]


# ---------------------------------------------------------------- 고아 표지 · 근거 줄(반대 검토 10-31 — BL-8)
@pytest.mark.parametrize("cut_side", ["target", "base"])
def test_a_cut_interface_beside_a_real_change_is_neither_deleted_nor_a_new_orphan(base_ir, cut_side):
    """BRACKET_L 은 실제로 움직였고(part.moved) 그 간섭 행은 한쪽 목록에서 잘렸다 — 검토 셀은 움직임을 싣되 BRACKET_L 을 '고아됨'(또는
    '고아 벗어남')으로, 간섭을 '삭제'(또는 '추가')로 싣지 않는다. 근거 줄은 있는 쪽 값만 적고 '목록 절단 — 비교 불가' 다."""
    moved = json.loads((PAIRS_DIR / "pair_move.json").read_text(encoding="utf-8"))
    if cut_side == "target":
        base, target, key, only = base_ir, _truncate(moved, {"interference": 1}), "became_orphan", "base 에만 있다"
    else:
        base, target, key, only = _truncate(base_ir, {"interference": 1}), moved, "left_orphan", "target 에만 있다"
    d = diff.compute_diff(base, target)
    assert _codes(d) == ["part.moved"]
    orphans = d["structural"]["orphans_delta"]
    assert orphans[key] == [] and orphans["truncated"][key] == [BRACKET_L]

    view = units.view_of(base, target)
    unit = next(u for u in units.build_diff_units(d, view)["units"]
                if u["reviewable"] and any(line["code"] == "part.moved" for line in u["lines"]))
    assert [(part["name"], part["status"]) for part in unit["parts"]] == [("BRACKET_L", "유지")]
    assert all(line["part_marks"] == [] for line in unit["lines"])
    row = next(r for r in units.evidence_lines(unit, view, d)["evidence"] if r["ref"] == INTERFERENCE_EID)
    assert row["text"].endswith(f"목록 절단 — 비교 불가({only})"), row["text"]
    assert "관통 깊이 0.050 mm" in row["text"] and "미측정" not in row["text"]
    assert "삭제" not in row["text"] and "추가" not in row["text"]


def test_an_honest_removal_beside_the_same_move_is_deleted_and_orphaned(base_ir):
    """같은 모양을 잘리지 않은 캡처로 비교하면 간섭이 정말 사라진 것이다 — '삭제' 와 '고아됨' 이 선다(앞 시험이 빈 것을 단언한 게 아니다)."""
    moved = json.loads((PAIRS_DIR / "pair_move.json").read_text(encoding="utf-8"))
    target = _truncate(moved, {"interference": 1})
    _mcad(target)["degraded"] = []
    _mcad(target)["stats"].pop("interfaces_truncated")
    d = diff.compute_diff(base_ir, target)
    assert d["structural"]["orphans_delta"]["became_orphan"] == [BRACKET_L]
    assert "truncated" not in d["structural"]["orphans_delta"]
    view = units.view_of(base_ir, target)
    unit = next(u for u in units.build_diff_units(d, view)["units"]
                if u["reviewable"] and any(part["dn"] == BRACKET_L for part in u["parts"]))
    assert "고아됨" in next(part["status"] for part in unit["parts"] if part["dn"] == BRACKET_L)
    row = next(r for r in units.evidence_lines(unit, view, d)["evidence"] if r["ref"] == INTERFERENCE_EID)
    assert row["text"].endswith("삭제") and "0.050→미측정" in row["text"]


def test_a_clearance_only_cut_does_not_touch_orphan_transitions(base_ir):
    """고아 차수는 clearance 를 세지 않는다 — clearance 만 잘린 쌍에서 간섭을 정말 잃어 고아가 된 BRACKET_L 은 base 에서 clearance 에도
    끼어 있었지만 그대로 전이다(잘린 clearance 행이 있었든 없었든 고아 여부는 같다)."""
    base = _rebuilt(_with_clearance(base_ir))
    target = _truncate(_rebuilt(_with_clearance(base_ir), INTERFERENCE_EID), {"clearance": 9}, drop_eid=None)
    d = diff.compute_diff(base, target)
    orphans = d["structural"]["orphans_delta"]
    assert orphans["became_orphan"] == [BRACKET_L] and orphans["truncated"] == {"became_orphan": [], "left_orphan": []}
    assert "iface.removed" in _codes(d)


# ---------------------------------------------------------------- 롤업(반대 검토 10-31 — BL-9)
def test_a_cut_kind_absent_from_a_rollup_row_keeps_its_rollup_event(base_ir):
    """clearance 만 잘렸고 그 조립 단위에는 clearance 가 하나도 없다 — 실제로 늘어난 tied 의 롤업 변화는 사건이다(종전에는 어느 kind 든
    잘리면 수가 움직인 롤업 행을 다 뺐다)."""
    target = copy.deepcopy(base_ir)
    tied = copy.deepcopy(next(e for e in target["edges"] if e["eid"] == TIED_EID))
    tied.update(eid=ir_builder.make_eid("iface", PLATE_1, BRACKET_L), a=PLATE_1, b=BRACKET_L)
    target["edges"].append(tied)
    target = _truncate(_rebuilt(target), {"clearance": 3}, drop_eid=None)
    d = diff.compute_diff(base_ir, target)
    assert _codes(d) == ["asm.rollup_changed", "asm.rollup_changed", "iface.added"]
    for row in d["parametric"]["rollup_delta"]:
        assert row["excluded_reason"] is None and "truncated_kinds" not in row
        assert row["edges_internal"] == {"before": 2, "after": 3}


def test_a_cut_kind_with_equal_counts_is_left_out_of_the_rollup_totals(base_ir):
    """clearance 가 잘렸지만 그 단위의 clearance 수는 두 쪽이 같다 — 행은 비교 대상으로 남고 계면 수는 잘리지 않은 kind 로만 센다(잘린
    쪽의 clearance 수는 일부라 합에 넣으면 숫자가 틀린다 — 원래 합은 3→2). 뺀 kind 는 항목 · 사건 글 · 검토 줄에 적힌다."""
    base = _rebuilt(_with_clearance(base_ir))
    target = _truncate(_rebuilt(_with_clearance(base_ir), TIED_EID), {"clearance": 2}, drop_eid=None)
    d = diff.compute_diff(base, target)
    assert _codes(d) == ["asm.rollup_changed", "asm.rollup_changed", "iface.removed"]
    rows = d["parametric"]["rollup_delta"]
    assert {(r["excluded_reason"], tuple(r["truncated_kinds"]), r["edges_internal"]["before"], r["edges_internal"]["after"])
            for r in rows} == {(None, ("clearance",), 2, 1)}
    note = "목록이 잘린 kind clearance 는 세지 않았다"
    assert all(note in e["text"] for e in d["semantic"]["events"] if e["code"] == "asm.rollup_changed")
    lines = [line for u in units.build_diff_units(d, units.view_of(base, target))["units"] for line in u["lines"]
             if line["code"] == "param.rollup"]
    assert len(lines) == 2 and all("내부 계면 2→1" in line["text"] and note in line["text"] for line in lines)

    # clearance 수가 두 쪽에서 다르면(잘렸을 수 있다) 그 행은 뺀다.
    target = _truncate(_rebuilt(base_ir, TIED_EID), {"clearance": 2}, drop_eid=None)
    d = diff.compute_diff(base, target)
    assert {r["excluded_reason"] for r in d["parametric"]["rollup_delta"]} == {"truncated"}
    assert _codes(d) == ["iface.removed"]
