# state 시험 — 게이트 G1~G7 판정(pass/unknown/blocked)·ack·강등 효과·character_seed·feature_vector(plan §2.12·§3.2)
from __future__ import annotations

import copy
import json
import math

import pytest

from app import diff as diff_module
from app import ir_builder as ib
from app import state as st
from tests.conftest import FIXTURES_DIR

GATE_FIXTURES = FIXTURES_DIR / "ir" / "gates"
OWNER = "user@example.com"
PROJECT = "e73c023a2e8e90349bb4d853730e1bfc"
GATE_KEYS = ("G1", "G2", "G3", "G4", "G5", "G6")


def load_case(name: str) -> dict:
    path = GATE_FIXTURES / f"{name}.json"
    assert path.exists(), f"게이트 픽스처가 없다: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def build_ir(bundle: dict, *, snapshot_id: str = "0" * 32) -> dict:
    return ib.build_ir(project_id=PROJECT, owner_sub=OWNER, label="게이트 픽스처",
                       adapter_results=bundle["adapter_results"],
                       iface_ledger=bundle.get("iface_ledger") or (),
                       snapshot_id=snapshot_id, captured_at=1756600000)


def build_state(bundle: dict, **kwargs) -> dict:
    return st.build_state(build_ir(bundle), computed_at=1756600001, **kwargs)


@pytest.fixture
def clean_ir() -> dict:
    return build_ir(load_case("gate_f1_clean"))


# ---------------------------------------------------------------- 게이트 픽스처 8케이스(plan §3.2.2)
CASES = ("gate_f1_clean", "gate_f2_anon", "gate_f3_unit", "gate_f4_iface", "gate_f5_partial")
# f6~f8 은 3값(pass=null)·사유·unknown_blocking 을 보는 케이스라 기대값 형식이 다르다(plan §2.12).
NULL_CASES = ("gate_f6_mcad_absent", "gate_f7_capture_partial", "gate_f8_unit_unknown")


@pytest.mark.parametrize("case", CASES)
def test_gate_fixture_verdicts_match_the_plan_table(case):
    bundle = load_case(case)
    expect = bundle["expect"]
    ir = build_ir(bundle)
    state = st.build_state(ir, computed_at=1756600001)

    assert {k: bool(v["pass"]) for k, v in state["gates"].items()} == expect["gates"], bundle["note"]
    assert state["blocked"] is expect["blocked"]
    assert ir["partial"] is expect["partial"]
    assert sum(1 for n in ir["nodes"] if n["domain"] == "mcad" and n["kind"] == "part") == expect["n_leaf"]
    for key in GATE_KEYS:
        record = state["gates"][key]
        assert set(record) == {"key", "count", "threshold", "pass", "reason", "blocking", "effect",
                               "ack_by", "ack_at", "ack_reason", "detail"}
        assert record["blocking"] is (key == "G6")
        if record["pass"]:
            assert record["effect"] == "none"
        if key in expect:
            for field, value in expect[key].items():
                assert record[field] == value, f"{case} {key}.{field}"


def test_gate_f2_subcase_stays_under_the_threshold():
    subcase = load_case("gate_f2_anon")["subcase"]
    state = build_state(subcase)
    assert state["gates"]["G1"]["pass"] is True
    assert state["gates"]["G1"]["count"] == 4 and state["gates"]["G1"]["threshold"] == 5.0


def test_gate_details_point_at_the_offending_refs():
    anon = build_state(load_case("gate_f2_anon"))
    assert len(anon["gates"]["G1"]["detail"]) == 9
    assert all(ref.startswith("p:") for ref in anon["gates"]["G1"]["detail"])

    iface_ir = build_ir(load_case("gate_f4_iface"))
    iface = st.build_state(iface_ir)
    auto = [e["eid"] for e in iface_ir["edges"] if e["kind"] == "interference" and e["status"] == "auto"]
    ledgered = [e["eid"] for e in iface_ir["edges"] if e["status"] == "manual_ledger"]
    assert len(auto) == 1 and len(ledgered) == 1
    assert iface["gates"]["G3"]["detail"] == auto        # manual_ledger 는 세지 않는다

    partial = build_state(load_case("gate_f5_partial"))
    assert partial["gates"]["G4"]["detail"] == ["warn:suspect_coordinate_systems#b_cover.step"]
    assert partial["gates"]["G5"]["detail"] and partial["gates"]["G5"]["detail"][0].startswith("p:")


# ---------------------------------------------------------------- 게이트 단위 판정(plan §2.12)
def test_g1_threshold_is_max_of_five_and_ten_percent(clean_ir):
    ir = copy.deepcopy(clean_ir)
    leaves = [n for n in ir["nodes"] if n["kind"] == "part"]
    assert st.compute_gates(ir)["G1"]["threshold"] == 5.0        # 리프 6 → max(5, 0.6)
    for node in leaves[:5]:
        node["status_flags"] = ["auto_named"]
    boundary = st.compute_gates(ir)["G1"]
    assert boundary["count"] == 5 and boundary["pass"] is True and boundary["effect"] == "none"
    leaves[5]["status_flags"] = ["duplicate_name"]
    failed = st.compute_gates(ir)["G1"]
    assert failed["count"] == 6 and failed["pass"] is False and failed["effect"] == "mark"


def test_g2_counts_pending_sameas_and_conflicts(clean_ir):
    ir = copy.deepcopy(clean_ir)
    assert st.compute_gates(ir)["G2"]["pass"] is True
    ir["same_as"] = [{"a": "p:aaa", "b": "p:bbb", "method": "fuzzy", "score": 0.8, "status": "pending"},
                     {"a": "p:ccc", "b": "p:ddd", "method": "ledger", "score": 1.0, "status": "confirmed"}]
    ir["warnings"] = ir["warnings"] + [{"severity": "WARNING", "code": "sameas_conflict",
                                        "message": "같은 도메인 둘", "ref": "p:eee", "source_kind": "ir_builder"}]
    gate = st.compute_gates(ir)["G2"]
    assert gate["count"] == 2 and gate["pass"] is False and gate["effect"] == "mark"
    assert gate["detail"] == ["p:aaa", "p:eee"]


def test_g3_ignores_confirmed_and_rejected_interference(clean_ir):
    ir = copy.deepcopy(clean_ir)
    edge = next(e for e in ir["edges"] if e["kind"] == "tied")
    edge["kind"] = "interference"
    for status, expected in (("auto", 1), ("confirmed", 0), ("manual_ledger", 0), ("rejected", 0)):
        edge["status"] = status
        assert st.compute_gates(ir)["G3"]["count"] == expected, status


def test_g5_only_fires_when_a_source_declares_a_scope(clean_ir):
    ir = copy.deepcopy(clean_ir)
    leaf = next(n for n in ir["nodes"] if n["kind"] == "part")
    leaf["status_flags"] = ["scope_out"]
    # scope 가 null 이면 범위 밖 리프를 세지 않는다.
    assert st.compute_gates(ir)["G5"]["pass"] is True
    ir["sources"][0]["scope"] = {"match": ["PLATE*"]}
    gate = st.compute_gates(ir)["G5"]
    assert gate["count"] == 1 and gate["pass"] is False and gate["effect"] == "mark_partial"


def test_g6_counts_every_unit_signal_and_blocks(clean_ir):
    ir = copy.deepcopy(clean_ir)
    assert st.compute_gates(ir)["G6"]["pass"] is True

    mismatch = copy.deepcopy(ir)
    mismatch["warnings"] = [{"severity": "WARNING", "code": "unit_mismatch",
                             "message": "header_unit=inch", "ref": "a_stack.step", "source_kind": "mcad"}]
    gate = st.compute_gates(mismatch)["G6"]
    assert gate["count"] == 1 and gate["pass"] is False and gate["blocking"] is True and gate["effect"] == "block"
    assert st.build_state(mismatch)["blocked"] is True

    inch = copy.deepcopy(ir)
    inch["sources"][0]["ref"]["unit_system"] = "inch"
    assert st.compute_gates(inch)["G6"]["detail"] == ["unit_system=inch"]

    ecad = copy.deepcopy(ir)
    ecad["sources"].append({"kind": "ecad", "app_key": None, "adapter_version": "1.0", "channel": "mcp",
                            "ref": {}, "source_hash": None, "degraded": ["unit_conversion_failed"],
                            "captured_at": 1756600000})
    assert st.compute_gates(ecad)["G6"]["count"] == 1


def test_g6_scale_ratio_is_unknown_when_it_cannot_be_computed(clean_ir):
    ir = copy.deepcopy(clean_ir)
    dyna_source = {"kind": "dyna", "app_key": "heax-kooremapper_mcp", "adapter_version": "1.0",
                   "channel": "mcp", "ref": {}, "source_hash": "sha", "degraded": [],
                   "captured_at": 1756600000, "stats": {}}
    ir["sources"].append(dyna_source)
    # dyna size 가 없으면 대각비를 계산할 수 없다 — unknown 은 계수 0(pass 표기)이다.
    assert st.compute_gates(ir)["G6"]["pass"] is True

    # mcad bbox_world 가 전부 없어도 마찬가지다.
    no_world = copy.deepcopy(ir)
    no_world["sources"][1]["stats"] = {"size": [500, 400, 32]}
    for node in no_world["nodes"]:
        node["attrs"].pop("bbox_world", None)
    assert st.compute_gates(no_world)["G6"]["pass"] is True

    matching = copy.deepcopy(ir)
    matching["sources"][1]["stats"] = {"size": [50, 40, 1.5]}
    assert st.compute_gates(matching)["G6"]["pass"] is True        # 대각비 ≈ 1.0

    mismatched = copy.deepcopy(ir)
    mismatched["sources"][1]["stats"] = {"size": [500, 400, 15]}   # 10 배 = mm/cm 혼용
    gate = st.compute_gates(mismatched)["G6"]
    assert gate["count"] == 1 and gate["pass"] is False
    assert gate["detail"] and gate["detail"][0].startswith("dyna/mcad 대각비")


def test_ack_is_recorded_but_never_flips_pass():
    bundle = load_case("gate_f2_anon")
    acks = {"dup_or_anon_names": {"by": OWNER, "at": 1756600100, "reason": "초안 단계라 감수한다"}}
    state = build_state(bundle, acks=acks)
    gate = state["gates"]["G1"]
    assert gate["pass"] is False and gate["effect"] == "mark"
    assert (gate["ack_by"], gate["ack_at"], gate["ack_reason"]) == (OWNER, 1756600100, "초안 단계라 감수한다")
    assert state["signals"]["gates.summary"]["value"]["G1"] == {"pass": False, "count": 9, "ack": True}


def test_g6_ack_does_not_unblock():
    bundle = load_case("gate_f3_unit")
    state = build_state(bundle, acks={"unit_scale": {"by": OWNER, "at": 1, "reason": "그냥"}})
    assert state["gates"]["G6"]["pass"] is False and state["blocked"] is True


# ---------------------------------------------------------------- 강등 효과(plan §3.2.2 effect)
def test_g4_failure_degrades_cross_file_edges_in_the_top_tables():
    bundle = load_case("gate_f5_partial")
    ir = build_ir(bundle)
    failed = st.build_state(ir)
    assert failed["gates"]["G4"]["effect"] == "degrade_cross_file"
    # 유일한 clearance 엣지가 cross_file 이라 근접 간극 표에서 빠진다.
    assert failed["signals"]["counts.cross_file"]["value"] == 1
    assert failed["signals"]["counts.edges.clearance"]["value"] == 1
    assert failed["signals"]["top.tight_clearance"]["value"] == []

    healthy = copy.deepcopy(ir)
    healthy["warnings"] = [w for w in healthy["warnings"] if w["code"] != "suspect_coordinate_systems"]
    ok = st.build_state(healthy)
    assert ok["gates"]["G4"]["pass"] is True
    assert [row["min_gap"] for row in ok["signals"]["top.tight_clearance"]["value"]] == [0.12]


def test_state_copies_the_missing_flags_without_recomputing(clean_ir):
    ir = copy.deepcopy(clean_ir)
    ir["missing"]["volume_null"] = True                # rr_state 는 §2 의 값을 그대로 옮긴다
    state = st.build_state(ir)
    assert state["missing"] == ir["missing"]
    assert state["missing"]["dyna_absent"] is True and state["missing"]["ecad_absent"] is True


def test_unknown_signals_are_null_not_zero(clean_ir):
    state = st.build_state(clean_ir)
    for key in ("counts.dyna.pids", "counts.ecad.components", "results.part_risk_top"):
        record = state["signals"][key]
        assert record["known"] is False and record["value"] is None


# ---------------------------------------------------------------- 봉투·씨앗·벡터(plan §3.2.1·§3.2.4·§3.2.5)
def test_state_envelope_fields(clean_ir):
    state = st.build_state(clean_ir, computed_at=1756600001)
    for key in ("state_version", "snapshot_id", "ir_hash", "project_id", "rule_version",
                "taxonomy_version", "seed_rules_version", "computed_at", "blocked", "gates",
                "missing", "signals", "character_seed", "feature_vector", "precedent",
                "rule_hits", "summary_text", "summary_status"):
        assert key in state, f"rr_state 봉투에 {key} 가 없다"
    assert state["state_version"] == "1.0"
    assert state["snapshot_id"] == clean_ir["snapshot_id"] and state["ir_hash"] == clean_ir["ir_hash"]
    assert state["computed_at"] == 1756600001
    assert "G7" not in state["gates"]        # G7 은 pair 전용이라 rr_state 에 없다
    assert state["precedent"] == {"corpus_n": 0, "per_feature": {}, "out_of_range_count": 0}
    assert len(state["summary_text"]) <= 2000 and state["summary_status"] in ("ok", "lint_failed")
    assert {h["rule"] for h in state["rule_hits"]} == {"R-001", "R-002", "R-003", "R-004", "R-005", "R-006"}


def test_build_state_is_deterministic(clean_ir):
    first = st.build_state(clean_ir, computed_at=7)
    second = st.build_state(clean_ir, computed_at=7)
    assert json.dumps(first, sort_keys=True, ensure_ascii=False) == json.dumps(second, sort_keys=True, ensure_ascii=False)


def test_character_seed_is_deterministic_and_cites_its_source():
    anon = build_state(load_case("gate_f2_anon"))
    tags = [s["tag"] for s in anon["character_seed"]]
    assert "char:maturity:anon_names_high" in tags        # G1 fail 씨앗(plan §3.2.4)
    assert "char:analysis:no_dyna" in tags
    assert not any(t.startswith("char:philosophy") for t in tags)   # 축 philosophy 는 씨앗이 내지 않는다
    seed = next(s for s in anon["character_seed"] if s["tag"] == "char:maturity:anon_names_high")
    assert seed["rule"] == "seed.maturity.anon_names_high" and seed["cites"] == ["gate:G1"]

    clean = build_state(load_case("gate_f1_clean"))
    clean_tags = [s["tag"] for s in clean["character_seed"]]
    assert "char:maturity:anon_names_high" not in clean_tags
    assert "char:tolerance:loose" in clean_tags           # clearance 1건이 min_gap 0.35 ≥ 0.3
    multi_file = build_state(load_case("gate_f5_partial"))
    assert "char:structure:multi_file_assembly" in [s["tag"] for s in multi_file["character_seed"]]


def test_feature_vector_is_fixed_length_and_masks_unknown_dimensions(clean_ir):
    features = st.build_state(clean_ir)["feature_vector"]
    assert features["version"] == "fv-1.0"
    assert features["names"] == list(st.FEATURE_NAMES) and len(features["names"]) == 22
    assert len(features["values"]) == len(features["known"]) == len(features["transform"]) == 22
    index = {name: i for i, name in enumerate(features["names"])}
    assert features["values"][index["n_leaf"]] == pytest.approx(math.log1p(6))
    # dyna·ecad 가 없으면 그 차원은 0 이 아니라 null·known=false 다.
    for name in ("n_dyna_pids", "n_dyna_contacts", "shell_ratio", "n_ecad_cmp"):
        assert features["known"][index[name]] is False
        assert features["values"][index[name]] is None


def test_save_and_load_state_round_trip(risk_store):
    mcad = json.loads((FIXTURES_DIR / "ir" / "adapter_mcad_basic.json").read_text(encoding="utf-8"))
    frozen = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="DV1",
                                adapter_results=[mcad], captured_at=1756600000)
    loaded = st.load_state(risk_store, frozen["snapshot_id"])
    assert loaded is not None and loaded["snapshot_id"] == frozen["snapshot_id"]
    assert loaded["ir_hash"] == frozen["ir_hash"]
    row = risk_store.query_one(
        "SELECT blocked, rule_version, taxonomy_version, summary_status, gates_json FROM rr_states"
        " WHERE snapshot_id = ?", (frozen["snapshot_id"],))
    assert row["blocked"] == 0 and sorted(json.loads(row["gates_json"])) == list(GATE_KEYS)
    # 재계산은 같은 값을 덮어쓴다(스냅샷 1건당 1행).
    again = st.compute_state_for_snapshot(risk_store, frozen["snapshot_id"])
    assert again["gates"] == loaded["gates"]
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_states", ())["n"] == 1
    assert st.load_state(risk_store, "0" * 32) is None


# ---------------------------------------------------------------- G7(pair 전용, plan §2.12·§3.3.6)
def _pair_ir(tol_hash, results=None, *, tol_known_keys=None):
    ir = {"ir_version": "1.0", "units": {"length": "mm"}, "partial": False, "results": results,
          "sources": [{"kind": "mcad", "tol_config_hash": tol_hash, "scope": None}]}
    if tol_known_keys is not None:
        ir["sources"][0]["tol_known_keys"] = tol_known_keys
    return ir


def test_g7_passes_when_the_yardsticks_match():
    comp = diff_module.comparability(_pair_ir("tol-a"), _pair_ir("tol-a"))
    assert comp["G7"] == {"key": "yardstick_parity", "count": 0, "threshold": 0, "pass": True,
                          "blocking": False, "effect": "none", "detail": []}
    assert comp["tol_parity"] is True and comp["result_parity"] is True
    assert comp["unit_parity"] is True and comp["ir_version_parity"] is True


def test_g7_counts_tol_and_result_mismatches():
    tol_differs = diff_module.comparability(_pair_ir("tol-a"), _pair_ir("tol-b"))
    assert tol_differs["tol_parity"] is False
    assert tol_differs["G7"]["count"] == 1 and tol_differs["G7"]["pass"] is False
    assert tol_differs["G7"]["effect"] == "exclude_by_reason"

    unknown = diff_module.comparability(_pair_ir(None), _pair_ir("tol-a"))
    assert unknown["tol_parity"] is None and unknown["tol_keys_known"] is False
    assert unknown["G7"]["count"] == 1 and "reason=tol_unknown" in unknown["G7"]["detail"]

    base = _pair_ir("tol-a", {"kind": "sphere", "sim_params_hash": "p1"})
    other_kind = _pair_ir("tol-a", {"kind": "deep", "sim_params_hash": "p1"})
    other_params = _pair_ir("tol-a", {"kind": "sphere", "sim_params_hash": "p2"})
    kind_diff = diff_module.comparability(base, other_kind)
    assert kind_diff["result_parity"] is False and kind_diff["result_reason"] == "result_kind_differs"
    params_diff = diff_module.comparability(base, other_params)
    assert params_diff["result_reason"] == "sim_params_differ"
    assert params_diff["G7"]["count"] == 1
    both = diff_module.comparability(_pair_ir("tol-a", {"kind": "sphere", "sim_params_hash": "p1"}),
                                     _pair_ir("tol-b", {"kind": "deep", "sim_params_hash": "p2"}))
    assert both["G7"]["count"] == 2 and both["G7"]["pass"] is False


def test_g7_notes_partial_tol_keys_without_failing():
    comp = diff_module.comparability(
        _pair_ir("tol-a", tol_known_keys=["tied_gap", "clearance_gap", "tied_area", "tied_width"]),
        _pair_ir("tol-a"))
    assert comp["G7"]["pass"] is True
    assert comp["G7"]["detail"] == ["reason=tol_keys_partial(4)"]


def test_g7_records_the_blocked_state_of_both_sides():
    blocked_state = build_state(load_case("gate_f3_unit"))
    clean_state = build_state(load_case("gate_f1_clean"))
    comp = diff_module.comparability(_pair_ir("tol-a"), _pair_ir("tol-a"), blocked_state, clean_state)
    assert comp["base_blocked"] is True and comp["target_blocked"] is False
    assert diff_module.check_pair_blocked(blocked_state, clean_state) is not None
    assert diff_module.check_pair_blocked(clean_state, clean_state) is None


def test_g4_failure_marks_the_pair_coordinates_as_not_ok():
    coordinate_fail = build_state(load_case("gate_f5_partial"))
    clean_state = build_state(load_case("gate_f1_clean"))
    comp = diff_module.comparability(_pair_ir("tol-a"), _pair_ir("tol-a"), coordinate_fail, clean_state)
    assert comp["coordinate_ok"] is False
    assert comp["partial_any"] is False        # 두 IR 자체는 partial 이 아니다


# ---------------------------------------------------------------- 3값·사유·unknown_blocking(plan §2.12)
def _gates_of(bundle: dict) -> tuple[dict, bool, list]:
    """f6 은 ir 을 직접 싣는다 — ir_builder 가 mcad 없는 스냅샷을 거부하기 때문이다(§2.11.3 1단계)."""
    if "ir" in bundle:
        ir = bundle["ir"]
        return st.compute_gates(ir), st.is_blocked(st.compute_gates(ir)), st.evaluate_rules(ir)
    state = build_state(bundle)
    return state["gates"], state["blocked"], state["rule_hits"]


@pytest.mark.parametrize("case", NULL_CASES)
def test_gate_three_valued_pass_and_reason(case):
    bundle = load_case(case)
    gates, blocked, _hits = _gates_of(bundle)
    expect = bundle["expect"]
    assert blocked is expect["blocked"], bundle["note"]
    for key in GATE_KEYS:
        record = gates[key]
        assert "reason" in record
        # 사유는 다섯뿐이고 pass ∈ true|false 면 null 이다(§2.12·§8.2.3).
        assert record["reason"] in (None, *st.GATE_NULL_REASONS)
        if record["pass"] is not None:
            assert record["reason"] is None
        for field, value in (expect.get(key) or {}).items():
            assert record[field] == value, f"{case} {key}.{field}"


def test_g6_unknown_blocking_blocks_without_being_a_fail():
    """pass=null 인데도 차단이다 — '계산 불가면 pass' 가 유일한 차단 게이트를 무력화하던 자리(§2.12)."""
    gates, blocked, hits = _gates_of(load_case("gate_f8_unit_unknown"))
    g6 = gates["G6"]
    assert g6["pass"] is None and g6["reason"] == "unit_unknown" and g6["blocking"] is True
    assert blocked is True
    assert st.blocked_reason(gates) == "unit_unknown"
    # G4 는 같은 mcp_degraded 에서 warnings 입력이 0 이라 '경고 없음' 이 아니라 '검문 불가' 다.
    assert gates["G4"]["pass"] is None and gates["G4"]["reason"] == "warnings_unavailable"
    # 같은 픽스처에서 R-004·R-005 는 evaluable=false·degraded 다(§3.2.6).
    by_rule = {h["rule"]: h for h in hits}
    for rule in ("R-004", "R-005"):
        assert by_rule[rule]["evaluable"] is False
        assert by_rule[rule]["not_evaluable_reason"] == "degraded"
        assert by_rule[rule]["pass"] is None


def test_mcad_absent_and_capture_partial_reasons():
    absent, _b, hits = _gates_of(load_case("gate_f6_mcad_absent"))
    assert absent["G3"]["reason"] == absent["G4"]["reason"] == "mcad_absent"
    assert absent["G6"]["pass"] is True                      # dyna 단위만 보고 판정한다
    assert all(h["not_evaluable_reason"] == "source_absent" for h in hits if not h["evaluable"])

    partial, _b2, hits2 = _gates_of(load_case("gate_f7_capture_partial"))
    assert partial["G3"]["pass"] is None and partial["G3"]["reason"] == "capture_partial"
    assert {h["rule"] for h in hits2 if h["not_evaluable_reason"] == "degraded"} == {"R-001"}


def test_ack_never_flips_pass_and_blocked_uses_the_plan_formula():
    acks = {"iface_unconfirmed": {"by": OWNER, "at": 1756600002, "reason": "확인 후 진행"}}
    state = st.build_state(build_ir(load_case("gate_f4_iface")), acks=acks, computed_at=1756600001)
    g3 = state["gates"]["G3"]
    assert g3["pass"] is False and g3["ack_by"] == OWNER and g3["ack_reason"] == "확인 후 진행"
    # ack 는 gates_hash 를 바꾸지 않는다(그 지문은 판정만 본다).
    assert st.gates_hash(state["gates"]) == st.gates_hash(st.compute_gates(build_ir(load_case("gate_f4_iface"))))
