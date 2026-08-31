# 3층 diff(§3.3) — 합성 쌍 6종의 기대 이벤트 각 1건·self-diff 0건·comparability/G7 판정·제외 사유·changed_ckeys
from __future__ import annotations

import copy
import json

import pytest
from jsonschema import validators

from app import diff
from app.common import canonical_json
from app.errors import AppError
from tests.conftest import BACKEND_DIR, FIXTURES_DIR

PAIRS_DIR = FIXTURES_DIR / "diff_pairs"

PLATE_1 = "p:87ae2f56d589"          # mcad PLATE_1 (ck:01f70db1e74f)
PLATE_2 = "p:8051c8e0492d"          # mcad PLATE_2 (ck:860cf8b0d3d0)
BRACKET_L = "p:d8f6805b7766"        # mcad BRACKET_L (ck:323a88501a2e)
CK_PLATE_1 = "ck:01f70db1e74f"
CK_PLATE_2 = "ck:860cf8b0d3d0"
CK_BRACKET = "ck:323a88501a2e"
CK_SHIM = "ck:7b21c0de44a1"
TIED_EID = "e:f1dabe4da27f"

# plan §3.3.5 합성 픽스처 6종 표 — 각 쌍은 golden IR 에 변형 한 가지만 주고 기대 이벤트는 그 건뿐이다.
EXPECTED = {
    "pair_add": {
        "events": ["iface.added", "part.added"],
        "stats": {"nodes_added": 1, "nodes_removed": 0, "edges_added": 1, "edges_removed": 0,
                  "edges_kind_changed": 0},
    },
    "pair_remove": {
        "events": ["iface.removed", "part.removed"],
        "stats": {"nodes_added": 0, "nodes_removed": 1, "edges_added": 0, "edges_removed": 1,
                  "edges_kind_changed": 0},
    },
    "pair_kind": {
        "events": ["iface.gap_changed", "iface.rank_down"],
        "stats": {"nodes_added": 0, "nodes_removed": 0, "edges_added": 0, "edges_removed": 0,
                  "edges_kind_changed": 1, "params_changed": 1},
    },
    "pair_thick": {
        "events": ["part.thickness_changed"],
        "stats": {"nodes_added": 0, "nodes_removed": 0, "edges_added": 0, "edges_removed": 0,
                  "edges_kind_changed": 0},
    },
    "pair_mat": {
        "events": ["part.material_changed"],
        "stats": {"nodes_added": 0, "nodes_removed": 0, "edges_added": 0, "edges_removed": 0,
                  "edges_kind_changed": 0},
    },
    "pair_move": {
        "events": ["part.moved"],
        "stats": {"nodes_added": 0, "nodes_removed": 0, "edges_added": 0, "edges_removed": 0,
                  "edges_kind_changed": 0},
    },
}


def _load(name: str) -> dict:
    return json.loads((PAIRS_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def base_ir() -> dict:
    return _load("base")


@pytest.fixture(scope="module")
def result_ir() -> dict:
    return json.loads((FIXTURES_DIR / "rr_ir" / "valid_mcad_dyna_result.json").read_text(encoding="utf-8"))


def _mcad_source(ir: dict) -> dict:
    return next(s for s in ir["sources"] if s["kind"] == "mcad")


def _codes(d: dict) -> list[str]:
    return sorted(e["code"] for e in d["semantic"]["events"])


# ---------------------------------------------------------------- 픽스처 자체
def test_pair_fixtures_validate_against_rr_ir_schema():
    schema = json.loads((BACKEND_DIR / "app" / "schemas" / "rr_ir.v1.json").read_text(encoding="utf-8"))
    validator = validators.validator_for(schema)(schema)
    paths = sorted(PAIRS_DIR.glob("*.json"))
    assert {p.stem for p in paths} == {"base"} | set(EXPECTED)
    for path in paths:
        obj = json.loads(path.read_text(encoding="utf-8"))
        assert [e.message for e in validator.iter_errors(obj)] == [], path.name


def test_each_pair_differs_from_base_in_one_place(base_ir):
    """변형은 한 곳뿐이어야 기대 이벤트가 1건으로 떨어진다 — 노드·엣지 차이 수를 센다."""
    diffs = {
        "pair_add": (1, 1), "pair_remove": (1, 1), "pair_kind": (0, 1),
        "pair_thick": (1, 0), "pair_mat": (1, 0), "pair_move": (1, 0),
    }
    for name, (n_nodes, n_edges) in diffs.items():
        target = _load(name)
        b_nodes = {n["nid"]: canonical_json(n) for n in base_ir["nodes"]}
        t_nodes = {n["nid"]: canonical_json(n) for n in target["nodes"]}
        b_edges = {e["eid"]: canonical_json(e) for e in base_ir["edges"]}
        t_edges = {e["eid"]: canonical_json(e) for e in target["edges"]}
        node_delta = {k for k in set(b_nodes) | set(t_nodes) if b_nodes.get(k) != t_nodes.get(k)}
        edge_delta = {k for k in set(b_edges) | set(t_edges) if b_edges.get(k) != t_edges.get(k)}
        assert (len(node_delta), len(edge_delta)) == (n_nodes, n_edges), name


# ---------------------------------------------------------------- 합성 쌍 6종 · self-diff
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_synthetic_pair_emits_exactly_the_expected_events(base_ir, name):
    d = diff.compute_diff(base_ir, _load(name))
    assert d["semantic"]["blocked_by"] is None
    assert _codes(d) == EXPECTED[name]["events"], d["semantic"]["events"]
    for code in EXPECTED[name]["events"]:
        assert sum(1 for e in d["semantic"]["events"] if e["code"] == code) == 1
    for key, value in EXPECTED[name]["stats"].items():
        assert d["stats"][key] == value, (name, key)
    assert d["stats"]["events"] == len(EXPECTED[name]["events"])
    assert d["correspondence"]["pending_n"] == 0


def test_self_diff_has_no_events_and_no_changed_items(base_ir):
    d = diff.compute_diff(base_ir, base_ir)
    assert d["semantic"]["events"] == []
    assert d["structural"]["node_changes"] == [] and d["structural"]["edge_changes"] == []
    assert d["stats"]["params_changed"] == 0
    assert d["stats"]["nodes_added"] == d["stats"]["nodes_removed"] == 0
    assert d["stats"]["nodes_matched"] == len(base_ir["nodes"])
    assert d["character_seed"] == []
    assert all(p["flag"] != "changed" for p in d["parametric"]["node_params"])


def test_pair_correspondence_uses_the_sameas_ladder(base_ir):
    """mcad 는 canon_key 동일이라 exact_path, dyna 는 geom_fp 동일이라 fingerprint 로 이어진다(§2.6.2)."""
    d = diff.compute_diff(base_ir, _load("pair_thick"))
    counts = d["correspondence"]["method_counts"]
    assert counts["exact_path"] == 4 and counts["fingerprint"] == 3
    assert counts["fuzzy"] == 0 and counts["ledger"] == 0
    assert d["correspondence"]["unmatched_base"] == [] and d["correspondence"]["unmatched_target"] == []


def test_pair_kind_event_details(base_ir):
    d = diff.compute_diff(base_ir, _load("pair_kind"))
    events = {e["code"]: e for e in d["semantic"]["events"]}
    rank = events["iface.rank_down"]
    assert (rank["before"], rank["after"]) == ("tied", "touching")
    assert rank["magnitude"] == {"value": -1, "unit": "rank", "rel": None}
    assert rank["subject_key"] == "|".join(sorted([CK_PLATE_1, CK_PLATE_2]))
    assert rank["change_kind"] == "topology"
    gap = events["iface.gap_changed"]
    assert (gap["before"], gap["after"]) == (0.0, 0.018)
    assert gap["magnitude"]["unit"] == "mm" and gap["magnitude"]["value"] == 0.018
    assert gap["subject"]["eids"] == {"base": TIED_EID, "target": TIED_EID}
    edge_change = next(c for c in d["structural"]["edge_changes"] if c["op"] == "kind_changed")
    assert (edge_change["rank_from"], edge_change["rank_to"], edge_change["rank_delta"]) == (2, 1, -1)


def test_pair_thick_prefers_thickness_over_resized(base_ir):
    """min_dim 이 두께 근사라 part.resized 보다 우선한다(§3.3.5 표 pair_thick 행)."""
    d = diff.compute_diff(base_ir, _load("pair_thick"))
    event = d["semantic"]["events"][0]
    assert event["code"] == "part.thickness_changed"
    assert (event["before"], event["after"]) == (1.2, 1.0)
    assert event["magnitude"]["rel"] == pytest.approx(-1 / 6, rel=1e-3)
    assert "(min_dim 근사)" in event["text"]
    assert event["confidence"] == "high"          # 대응이 exact_path 다
    assert event["subject_key"] == CK_PLATE_1
    changed = {p["attr"] for p in d["parametric"]["node_params"]
               if p["dn"] == PLATE_1 and p["flag"] == "changed"}
    assert {"min_dim", "volume", "bbox_def_dims[2]"} <= changed


def test_pair_move_is_placement_not_dimension(base_ir):
    d = diff.compute_diff(base_ir, _load("pair_move"))
    event = d["semantic"]["events"][0]
    assert event["code"] == "part.moved" and event["change_kind"] == "placement"
    assert event["magnitude"] == {"value": 2.0, "unit": "mm", "rel": None}
    assert event["subject_key"] == CK_BRACKET
    bracket = [p for p in d["parametric"]["node_params"] if p["dn"] == BRACKET_L]
    assert all(p["flag"] != "changed" for p in bracket if p["attr"].startswith("bbox_def_dims"))
    assert [p["attr"] for p in bracket if p["flag"] == "changed"] == ["centroid_world[0]"]


def test_pair_mat_records_material_rows(base_ir):
    d = diff.compute_diff(base_ir, _load("pair_mat"))
    rows = d["parametric"]["materials"]
    # 표시명(name)과 정규화 재료(material_norm)는 같은 변경의 두 필드다(§3.3.4 materials[] 필드 어휘).
    assert {r["field"] for r in rows} == {"name", "material_norm"}
    assert all(r["dn"] == PLATE_1 and r["ckey"] == CK_PLATE_1 for r in rows)
    assert {(r["before"], r["after"]) for r in rows} == {("AL6061", "AL7075"), ("al6061", "al7075")}
    assert _codes(d) == ["part.material_changed"]


def test_pair_add_and_remove_touch_the_expected_subjects(base_ir):
    added = diff.compute_diff(base_ir, _load("pair_add"))
    part_added = next(e for e in added["semantic"]["events"] if e["code"] == "part.added")
    assert part_added["subject_key"] == CK_SHIM
    assert part_added["subject"]["names"] == ["SHIM_1"]
    iface_added = next(e for e in added["semantic"]["events"] if e["code"] == "iface.added")
    assert iface_added["after"] == "tied"

    removed = diff.compute_diff(base_ir, _load("pair_remove"))
    part_removed = next(e for e in removed["semantic"]["events"] if e["code"] == "part.removed")
    assert part_removed["subject_key"] == CK_BRACKET
    iface_removed = next(e for e in removed["semantic"]["events"] if e["code"] == "iface.removed")
    assert iface_removed["before"] == "interference"


# ---------------------------------------------------------------- 결정론(§3.1 원칙 1 · P2 통과 기준)
@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_diff_is_byte_identical_on_recompute(base_ir, name):
    target = _load(name)
    first = diff.compute_diff(base_ir, target, created_at=0)
    second = diff.compute_diff(base_ir, target, created_at=0)
    assert canonical_json(first) == canonical_json(second)


def test_cids_are_prefixed_and_unique(base_ir):
    d = diff.compute_diff(base_ir, _load("pair_kind"))
    items = (d["structural"]["node_changes"] + d["structural"]["edge_changes"]
             + d["parametric"]["node_params"] + d["parametric"]["edge_params"]
             + d["parametric"]["materials"] + d["parametric"]["dims_delta"]
             + d["parametric"]["rollup_delta"] + d["semantic"]["events"])
    cids = [i["cid"] for i in items]
    assert cids and all(c.startswith("c:") and len(c) == 14 for c in cids)
    assert len(cids) == len(set(cids))
    assert diff.cid_for("semantic", "iface.rank_down", "a", "b") == \
        diff.cid_for("semantic", "iface.rank_down", "a", "b")
    assert diff.cid_for("semantic", "iface.rank_down", "a", "b") != \
        diff.cid_for("semantic", "iface.rank_down", "b", "a")


# ---------------------------------------------------------------- comparability · G7(§3.3.6 · §3.2.2)
def test_comparability_is_all_parity_for_the_same_yardstick(base_ir):
    comp = diff.comparability(base_ir, base_ir)
    assert comp["tol_parity"] is True and comp["tol_keys_known"] is True
    assert comp["unit_parity"] is True and comp["scope_parity"] is True
    assert comp["result_parity"] is True and comp["result_present"] is False
    assert comp["coordinate_ok"] is True and comp["partial_any"] is False
    assert comp["ir_version_parity"] is True
    assert comp["G7"]["pass"] is True and comp["G7"]["count"] == 0
    assert comp["G7"]["blocking"] is False and comp["G7"]["effect"] == "none"
    # tol 키가 잡 params 4키뿐이면 fail 이 아니라 표기다(§3.2.2 G7 세부).
    assert comp["G7"]["detail"] == ["reason=tol_keys_partial(4)"]


def test_tol_differs_excludes_the_gap_family(base_ir):
    """P2 통과 기준 (5) — tol 다른 쌍에서 gap 계열 delta 는 전부 excluded_reason='tol_differs' 다."""
    target = _load("pair_kind")
    _mcad_source(target)["tol_config_hash"] = "f" * 64
    d = diff.compute_diff(base_ir, target)
    comp = d["comparability"]
    assert comp["tol_parity"] is False and comp["tol_keys_known"] is True
    assert comp["G7"] == {"key": "yardstick_parity", "count": 1, "threshold": 0, "pass": False,
                          "blocking": False, "effect": "exclude_by_reason",
                          "detail": ["reason=tol_keys_partial(4)"]}
    gap_family = [p for p in d["parametric"]["edge_params"] if p["attr"] in diff.TOL_DEPENDENT]
    assert gap_family and all(p["excluded_reason"] == "tol_differs" for p in gap_family)
    assert d["stats"]["excluded_by_reason"]["tol_differs"] == len(gap_family)
    assert "iface.gap_changed" not in _codes(d)          # 제외 항목은 의미 이벤트를 만들지 않는다
    assert "iface.rank_down" in _codes(d)                 # kind 변경 자체는 tol 에 종속하지 않는다


def test_tol_unknown_when_one_side_has_no_tol_hash(base_ir):
    target = _load("pair_kind")
    _mcad_source(target)["tol_config_hash"] = None
    d = diff.compute_diff(base_ir, target)
    comp = d["comparability"]
    assert comp["tol_parity"] is None and comp["tol_keys_known"] is False
    assert "reason=tol_unknown" in comp["G7"]["detail"]
    assert comp["G7"]["pass"] is False
    gap_family = [p for p in d["parametric"]["edge_params"] if p["attr"] in diff.TOL_DEPENDENT]
    assert gap_family and all(p["excluded_reason"] == "tol_unknown" for p in gap_family)


def test_unit_and_scope_and_ir_version_parity(base_ir):
    other = copy.deepcopy(base_ir)
    other["units"] = dict(other["units"], length="m")
    other["ir_version"] = "1.1"
    _mcad_source(other)["scope"] = ["a_stack.step"]
    comp = diff.comparability(base_ir, other)
    assert comp["unit_parity"] is False
    assert comp["scope_parity"] is False
    assert comp["ir_version_parity"] is False


def test_result_parity_and_result_delta(result_ir):
    base = copy.deepcopy(result_ir)
    target = copy.deepcopy(result_ir)
    target["snapshot_id"] = "b" * 32
    target["results"]["part_risk"][0]["worst_stress"] = {"value": 468.0, "case_key": "corner_45"}
    d = diff.compute_diff(base, target)
    assert d["comparability"]["result_parity"] is True
    assert d["comparability"]["result_reason"] is None
    changed = [i for i in d["parametric"]["result_delta"] if i["flag"] == "changed"]
    assert [i["metric"] for i in changed] == ["worst_stress"]
    assert changed[0]["rel_delta"] == pytest.approx(0.135922, rel=1e-4)
    assert changed[0]["excluded_reason"] is None
    shift = [e for e in d["semantic"]["events"] if e["code"] == "result.part_metric_shift"]
    assert len(shift) == 1 and shift[0]["change_kind"] == "result"


def test_result_kind_differs_makes_no_result_event(result_ir):
    base = copy.deepcopy(result_ir)
    target = copy.deepcopy(result_ir)
    target["snapshot_id"] = "b" * 32
    target["results"]["part_risk"][0]["worst_stress"] = {"value": 468.0, "case_key": "corner_45"}
    target["results"]["kind"] = "drop"
    d = diff.compute_diff(base, target)
    assert d["comparability"]["result_parity"] is False
    assert d["comparability"]["result_reason"] == "result_kind_differs"
    # 제외된 항목은 수치와 함께 diff_json 에 남고 의미 이벤트만 만들지 않는다(§3.3.6).
    assert d["parametric"]["result_delta"]
    assert all(i["excluded_reason"] == "result_kind_differs" for i in d["parametric"]["result_delta"])
    assert [e for e in d["semantic"]["events"] if e["code"].startswith("result.")] == []


def test_sim_params_differ_keeps_numbers_but_drops_events(result_ir):
    base = copy.deepcopy(result_ir)
    target = copy.deepcopy(result_ir)
    target["snapshot_id"] = "b" * 32
    target["results"]["part_risk"][0]["worst_stress"] = {"value": 468.0, "case_key": "corner_45"}
    target["results"]["sim_params_hash"] = "0" * 64
    d = diff.compute_diff(base, target)
    assert d["comparability"]["result_reason"] == "sim_params_differ"
    changed = [i for i in d["parametric"]["result_delta"] if i["before"] != i["after"]]
    assert changed and all(i["excluded_reason"] == "sim_params_differ" for i in changed)
    assert [e for e in d["semantic"]["events"] if e["code"].startswith("result.")] == []


def test_result_on_one_side_only_is_kind_differs(result_ir):
    target = copy.deepcopy(result_ir)
    target["snapshot_id"] = "b" * 32
    target["results"] = None
    comp = diff.comparability(result_ir, target)
    assert comp["result_present"] is True and comp["result_parity"] is False
    assert comp["result_reason"] == "result_kind_differs"
    assert diff.compute_diff(result_ir, target)["parametric"]["result_delta"] == []


def test_check_pair_blocked_only_on_g6():
    g6 = {"blocked": True, "gates": {"G6": {"key": "unit_scale", "pass": False}}}
    assert diff.check_pair_blocked(g6, None) == {
        "gates": {"base": {"key": "unit_scale", "pass": False}}, "reason": "unit_mismatch"}
    # unknown_blocking — pass=null 이어도 차단이고 reason 은 unit_unknown 이다(§2.12).
    unknown = {"blocked": True, "gates": {"G6": {"key": "unit_scale", "pass": None, "reason": "unit_unknown"}}}
    assert diff.check_pair_blocked(None, unknown)["reason"] == "unit_unknown"
    assert diff.check_pair_blocked({"blocked": False}, {"blocked": False}) is None
    assert diff.check_pair_blocked(None, None) is None


# ---------------------------------------------------------------- 제외 사유(§3.3.6)
def test_excluded_reasons_stay_in_the_vocabulary(base_ir):
    seen = set()
    for name in EXPECTED:
        d = diff.compute_diff(base_ir, _load(name))
        for reason, _n in d["stats"]["excluded_by_reason"].items():
            seen.add(reason)
    assert seen <= set(diff.EXCLUDED_REASONS)


def test_partial_scope_excludes_out_of_scope_subjects(base_ir):
    base = copy.deepcopy(base_ir)
    target = _load("pair_kind")
    target["partial"] = True
    for ir in (base, target):
        for node in ir["nodes"]:
            if node["nid"] == PLATE_1:
                node["status_flags"] = ["scope_out"]
    d = diff.compute_diff(base, target)
    assert d["comparability"]["partial_any"] is True
    assert d["stats"]["excluded_by_reason"]["partial_scope"] > 0
    plate = [p for p in d["parametric"]["node_params"] if p["dn"] == PLATE_1]
    assert plate and all(p["excluded_reason"] == "partial_scope" for p in plate)
    tied = [p for p in d["parametric"]["edge_params"] if PLATE_1 in (p["dn_a"], p["dn_b"])]
    assert tied and all(p["excluded_reason"] == "partial_scope" for p in tied)
    assert d["semantic"]["events"] == []


def test_null_one_side_on_named_dimension(base_ir):
    """값이 있던 명명 치수의 ref 가 사라지면 null_one_side 제외 + dim.named_unmeasured 다(§3.3.4·§3.3.5)."""
    base = copy.deepcopy(base_ir)
    base["dims_named"] = [{"name": "plate_gap", "value": 0.35, "unit": "mm", "method": "measured",
                           "ref": TIED_EID, "formula": "edge.min_gap", "owner_sub": "user@example.com",
                           "null_reason": None}]
    target = copy.deepcopy(base_ir)
    target["dims_named"] = [dict(base["dims_named"][0], value=None, ref=None, null_reason="ref_missing")]
    d = diff.compute_diff(base, target)
    item = d["parametric"]["dims_delta"][0]
    assert item["flag"] == "null_one_side" and item["excluded_reason"] == "null_one_side"
    assert _codes(d) == ["dim.named_unmeasured"]

    # 값이 바뀌면 dim.named_changed 이고 [d:<name>] 을 병기한다.
    moved = copy.deepcopy(base)
    moved["dims_named"] = [dict(base["dims_named"][0], value=0.18)]
    d2 = diff.compute_diff(base, moved)
    assert _codes(d2) == ["dim.named_changed"]
    changed = d2["parametric"]["dims_delta"][0]
    assert changed["flag"] == "changed" and "[d:plate_gap]" in changed["text"]

    # 양쪽 다 미측정이면 소실이 아니므로 이벤트를 만들지 않는다(self-diff 0건의 전제).
    both_null = copy.deepcopy(target)
    assert diff.compute_diff(target, both_null)["semantic"]["events"] == []


def test_g2_blocks_semantic_but_keeps_the_other_layers(base_ir):
    state = {"blocked": False, "gates": {"G2": {"key": "sameas_pending", "count": 2, "pass": False}}}
    d = diff.compute_diff(base_ir, _load("pair_kind"), base_state=state)
    assert d["semantic"] == {"blocked_by": "G2", "events": []}
    assert d["stats"]["edges_kind_changed"] == 1 and d["stats"]["params_changed"] == 1


def test_g4_downgrades_interface_confidence(base_ir):
    state = {"blocked": False, "gates": {"G4": {"key": "coordinate", "pass": False}}}
    d = diff.compute_diff(base_ir, _load("pair_kind"), base_state=state)
    assert d["comparability"]["coordinate_ok"] is False
    assert {e["confidence"] for e in d["semantic"]["events"]} == {"low"}


# ---------------------------------------------------------------- changed_ckeys(§6.5 2)
@pytest.mark.parametrize("name,expected", [
    ("pair_add", [CK_PLATE_1, CK_SHIM]),            # 새 파트 + 새 계면의 상대 끝점
    ("pair_remove", [CK_BRACKET, CK_PLATE_2]),      # 사라진 파트 + 사라진 계면의 상대 끝점
    ("pair_kind", [CK_PLATE_1, CK_PLATE_2]),
    ("pair_thick", [CK_PLATE_1]),
    ("pair_mat", [CK_PLATE_1]),
    ("pair_move", [CK_BRACKET]),
])
def test_changed_ckeys_per_pair(base_ir, name, expected):
    d = diff.compute_diff(base_ir, _load(name))
    assert diff.changed_ckeys(d) == sorted(expected)


def test_changed_ckeys_is_empty_on_self_diff(base_ir):
    assert diff.changed_ckeys(diff.compute_diff(base_ir, base_ir)) == []


def test_changed_ckeys_skips_excluded_items(base_ir):
    """제외된 항목(잣대 불일치)은 변경 주체로 세지 않는다 — gap 만 바뀐 쌍에서 확인한다."""
    target = _load("pair_kind")
    next(e for e in target["edges"] if e["eid"] == TIED_EID)["kind"] = "tied"   # kind 는 되돌리고 min_gap 만 남긴다
    _mcad_source(target)["tol_config_hash"] = "f" * 64
    d = diff.compute_diff(base_ir, target)
    assert [p for p in d["parametric"]["edge_params"] if p["attr"] == "min_gap"
            and p["flag"] == "changed"]
    assert diff.changed_ckeys(d) == []


def test_changed_ckeys_folds_merged_keys(base_ir):
    d = diff.compute_diff(base_ir, _load("pair_kind"))
    folded = diff.changed_ckeys(d, lambda ck: "ck:merged" if ck == CK_PLATE_2 else ck)
    assert folded == sorted({CK_PLATE_1, "ck:merged"})


# ---------------------------------------------------------------- 저장 경로(§3.3.1 · §5.2.2)
def _seed_snapshot(store, ir: dict, owner_sub: str = "user@example.com") -> str:
    store.execute(
        "INSERT OR IGNORE INTO rr_projects (id, owner_sub, code, name, created_at, updated_at)"
        " VALUES (?,?,?,?,0,0)",
        (ir["project_id"], owner_sub, "M22", "M22"),
    )
    store.execute(
        "INSERT INTO rr_snapshots (id, project_id, owner_sub, ir_version, ir_hash, ir_json,"
        " source_ids_json, kinds_json, node_count, edge_count, created_at)"
        " VALUES (?,?,?,?,?,?,'[]','[\"mcad\"]',?,?,0)",
        (ir["snapshot_id"], ir["project_id"], owner_sub, ir["ir_version"], ir["ir_hash"],
         json.dumps(ir, ensure_ascii=False), len(ir["nodes"]), len(ir["edges"])),
    )
    return str(ir["snapshot_id"])


def test_create_diff_stores_events_and_is_idempotent(risk_store, base_ir):
    owner = "user@example.com"
    base_id = _seed_snapshot(risk_store, base_ir, owner)
    target_id = _seed_snapshot(risk_store, _load("pair_kind"), owner)

    created = diff.create_diff(risk_store, base_id, target_id, owner_sub=owner)
    assert created["pair_kind"] == "same_project_revision"
    assert _codes(created) == EXPECTED["pair_kind"]["events"]

    rows = risk_store.query("SELECT diff_id, cid, layer, code, subject_key, confidence FROM rr_diff_events"
                            " WHERE owner_sub=? ORDER BY code", (owner,))
    assert [r["code"] for r in rows] == EXPECTED["pair_kind"]["events"]
    assert {r["layer"] for r in rows} == {"semantic"}

    again = diff.create_diff(risk_store, base_id, target_id, owner_sub=owner)
    assert again["diff_id"] == created["diff_id"]
    assert len(risk_store.query("SELECT id FROM rr_diffs WHERE owner_sub=?", (owner,))) == 1

    summary = diff.get_diff(risk_store, created["diff_id"], owner_sub=owner, part="summary")
    assert summary["summary_status"] == "ok"
    assert summary["comparability"]["G7"]["pass"] is True
    assert summary["diff_hash"] and len(summary["diff_hash"]) == 64
    events = diff.get_diff(risk_store, created["diff_id"], owner_sub=owner, part="events")
    assert [e["code"] for e in events["events"]] == EXPECTED["pair_kind"]["events"]
    with pytest.raises(AppError):
        diff.get_diff(risk_store, created["diff_id"], owner_sub=owner, part="nope")
    with pytest.raises(AppError):
        diff.get_diff(risk_store, "no-such-diff", owner_sub=owner)


def test_create_diff_refuses_a_g6_blocked_snapshot(risk_store, base_ir):
    owner = "user@example.com"
    base_id = _seed_snapshot(risk_store, base_ir, owner)
    target = _load("pair_thick")
    target_id = _seed_snapshot(risk_store, target, owner)
    risk_store.execute(
        "INSERT INTO rr_states (snapshot_id, owner_sub, state_json, feature_json, gates_json, blocked)"
        " VALUES (?,?,?,'{}',?,1)",
        (target_id, owner,
         json.dumps({"blocked": True, "gates": {"G6": {"key": "unit_scale", "pass": False}}}),
         json.dumps({"G6": {"pass": False}})),
    )
    with pytest.raises(AppError) as excinfo:
        diff.create_diff(risk_store, base_id, target_id, owner_sub=owner)
    assert excinfo.value.http_status == 409
    assert risk_store.query("SELECT id FROM rr_diffs WHERE owner_sub=?", (owner,)) == []
