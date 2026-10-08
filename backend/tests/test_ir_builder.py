# ir_builder 시험 — 봉투 필드·ir_hash 재현·노드/엣지 정규화·dims_named·rollups·원장 재적용·스냅샷 동결(plan §2.2~§2.12)
from __future__ import annotations

import copy
import json

import pytest

from app import ir_builder as ib
from app.errors import AppError
from tests.conftest import FIXTURES_DIR

IR_FIXTURES = FIXTURES_DIR / "ir"
OWNER = "user@example.com"
PROJECT = "e73c023a2e8e90349bb4d853730e1bfc"

PLATE_1 = "mcad:/a_stack.step/STACK_ASM/PLATE_1"
PLATE_2 = "mcad:/a_stack.step/STACK_ASM/PLATE_2"
BRACKET = "mcad:/a_stack.step/STACK_ASM/BRACKET_L"


def load_fixture(name: str) -> dict:
    path = IR_FIXTURES / name
    assert path.exists(), f"IR 픽스처가 없다: {path}"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def mcad_result() -> dict:
    return load_fixture("adapter_mcad_basic.json")


@pytest.fixture
def dyna_result() -> dict:
    return load_fixture("adapter_dyna_basic.json")


@pytest.fixture
def dyna_result_layer() -> dict:
    return load_fixture("adapter_dyna_result.json")


def build(adapter_results, **kwargs) -> dict:
    kwargs.setdefault("project_id", PROJECT)
    kwargs.setdefault("owner_sub", OWNER)
    kwargs.setdefault("label", "M22 DV1")
    kwargs.setdefault("captured_at", 1756600000)
    return ib.build_ir(adapter_results=adapter_results, **kwargs)


def node_by_ck(ir, canon_key):
    return next(n for n in ir["nodes"] if n["canon_key"] == canon_key)


def edge_of(ir, kind):
    return next(e for e in ir["edges"] if e["kind"] == kind)


# ---------------------------------------------------------------- 전역 정규 키(plan §2.7)
def test_make_nid_and_make_eid_follow_the_formula():
    assert ib.make_nid(PLATE_1) == "p:" + ib.sha1_hex(PLATE_1)[:12]
    assert ib.make_eid("iface", "p:aaa", "p:bbb") == "e:" + ib.sha1_hex("iface|p:aaa|p:bbb")[:12]
    # 무방향 kind 는 끝점을 정렬하므로 순서를 바꿔도 같은 eid 다.
    assert ib.make_eid("iface", "p:bbb", "p:aaa") == ib.make_eid("iface", "p:aaa", "p:bbb")
    # 방향 kind 는 정렬하지 않는다.
    assert ib.make_eid("hier", "p:bbb", "p:aaa", directed=True) != ib.make_eid("hier", "p:aaa", "p:bbb", directed=True)
    # scope 하이퍼엣지는 b 가 없다.
    assert ib.make_eid("contact", "p:aaa", None) == "e:" + ib.sha1_hex("contact|" + "|".join(sorted(["p:aaa", ""])))[:12]


def test_kind_family_of_maps_known_kinds_and_rejects_unknown():
    assert ib.kind_family_of("tied") == "iface"
    assert ib.kind_family_of("geometric") == "iface"
    assert ib.kind_family_of("contact") == "contact"
    assert ib.kind_family_of("scope") == "contact"
    assert ib.kind_family_of("part_of") == "hier"
    assert ib.kind_family_of("load_path") == "load_path"
    with pytest.raises(AppError) as exc:
        ib.kind_family_of("teleport")
    assert exc.value.code == "E100"


@pytest.mark.parametrize("label,auto_named,expected", [
    ("PLATE_1", False, "plate_1"),
    ("PLATE_1#3", False, "plate_1"),
    ("SOLID_7", True, "solid"),
    ("Stack\\PLATE_1", False, "plate_1"),
    ("dir/sub/COVER TOP", False, "cover_top"),
    ("__A--B__", False, "a_b"),
])
def test_name_norm_rules(label, auto_named, expected):
    assert ib.name_norm(label, auto_named=auto_named) == expected


@pytest.mark.parametrize("normalized,expected", [
    ("main_board_rev", "pcb"),          # 동의어(머리 2토큰) + 불용어 제거
    ("board_top", "pcb_top"),
    ("bracket_l", "bracket_l"),         # 인스턴스 순번은 유지한다
    ("cover_1_5t", "housing"),          # 두께 토큰 제거 + 동의어
    ("plate_t05", "plate"),
    ("plate_0_3mm", "plate"),
    ("rev", "rev"),                     # 전부 지워지면 원문을 그대로 쓴다
])
def test_name_norm_canon_rules(normalized, expected):
    assert ib.name_norm_canon(normalized) == expected


# 표시명 접미 변형표(plan §0.9 P1-9 · §2.7.1). `#\\d+` 는 항상 지우고 `_\\d+` 는 인스턴스 플래그가 있을 때만 지운다 —
# plan §2.7.1 은 `plate_1`·`plate_2` 를 서로 다른 부품으로 남겨야 한다고 못박는다.
CKEY_SUFFIX_CASES = [
    ("PLATE_1", False, True),        # 기준
    ("PLATE_1#2", False, True),      # 인스턴스 순번 접미 — 같은 ckey
    ("PLATE_1_3", True, True),       # auto_named 인스턴스 접미 — 같은 ckey
    ("PLATE_1_3", False, False),     # 플래그 없는 `_3` 은 다른 부품 번호다
    ("PLATE_2", False, False),       # 실 부품 번호는 갈라져야 한다
]


@pytest.mark.parametrize("label,auto_named,same", CKEY_SUFFIX_CASES,
                         ids=[f"{c[0]}-{c[1]}" for c in CKEY_SUFFIX_CASES])
def test_ckey_is_stable_across_instance_suffixes(label, auto_named, same):
    """같은 파트의 표시명 접미 변형은 같은 ckey 를 낸다(재료·형상 버킷 고정)."""
    def ckey_of(text: str, flag: bool) -> str:
        canon = ib.name_norm_canon(ib.name_norm(text, auto_named=flag))
        return ib.canonical_part_key(canon, "bx:1.0|2.0|3.0", "al6061")

    base = ckey_of("PLATE_1", False)
    assert (ckey_of(label, auto_named) == base) is same


def test_ckey_changes_when_only_the_material_changes():
    canon = ib.name_norm_canon(ib.name_norm("PLATE_1"))
    bucket = "bx:1.0|2.0|3.0"
    assert ib.canonical_part_key(canon, bucket, "al6061") != ib.canonical_part_key(canon, bucket, "az91d")


def test_name_norm_canon_drops_project_codes():
    assert ib.name_norm_canon("m22_plate_1", project_codes=["M22"]) == "plate_1"


def test_asm_key_of_matches_plan_example():
    assert ib.asm_key_of("/a_stack.step/STACK_ASM/PLATE_1", project_name=None) == "a_stack/stack_asm"
    # 프로젝트명 접두는 떼고, 세그먼트의 `#\d+` 도 지운다.
    assert ib.asm_key_of("sif-e2e/a_stack.step/STACK_ASM#2/PLATE_1", project_name="sif-e2e") == "a_stack/stack_asm"
    # drop_leaf=False 면 리프까지 포함한다(dims_named 선택자용).
    assert ib.asm_key_of("/a_stack.step/STACK_ASM/PLATE_1", drop_leaf=False) == "a_stack/stack_asm/plate_1"


def test_geom_fp_is_deterministic_and_none_without_geometry():
    kwargs = {"kind": "solid", "size": [50, 40, 1.2], "volume": 3000.0, "area": None,
              "centroid_offset": [0.0, 0.0, 0.0]}
    fp = ib.geom_fp(**kwargs)
    assert fp == ib.geom_fp(**kwargs) and len(fp) == 16
    # size 는 정렬 후 소수 2자리라 순서·미세 잡음에 둔감하다.
    assert ib.geom_fp(**dict(kwargs, size=[1.2, 50.001, 40])) == fp
    assert ib.geom_fp(**dict(kwargs, size=[50, 40, 1.5])) != fp
    assert ib.geom_fp(**dict(kwargs, size=None)) is None


def test_geom_bucket_and_canonical_part_key():
    assert ib.geom_bucket([50.0, 40.0, 1.2], 3000.0).startswith("50.0x40.0x1.0@v")
    assert ib.geom_bucket([50.0, 40.0, 1.2], None).endswith("@v?")
    assert ib.geom_bucket(None, None) == "?@v?"
    ck = ib.canonical_part_key("plate_1", "50.0x40.0x1.0@v164", "al6061")
    assert ck == "ck:" + ib.sha1_hex("plate_1|50.0x40.0x1.0@v164|al6061")[:12]


def test_material_norm_takes_first_token_after_synonyms():
    assert ib.material_norm("AL 6061-T6") == "al"
    assert ib.material_norm(None) == "na"
    assert ib.material_norm("  ") == "na"


# ---------------------------------------------------------------- ir_hash(plan §2.11.1)
def test_ir_hash_is_identical_across_two_extractions(mcad_result, dyna_result):
    """P1 통과 기준 (1) — 같은 소스·같은 원장이면 재추출해도 ir_hash 가 같다."""
    first = build([mcad_result, dyna_result], snapshot_id="a" * 32, captured_at=1756600000)
    second_input = copy.deepcopy([mcad_result, dyna_result])
    # 재추출에서 달라지는 것들 — 캡처 시각·스냅샷 id·provenance·소스 stats 는 해시 입력이 아니다.
    second_input[0]["source"]["stats"] = {"files": 99}
    second_input[0]["source"]["captured_at"] = 1799999999
    for node in second_input[0]["nodes"]:
        node["provenance"] = {"adapter": "mcad", "call_id": "zzzz9999-777", "node_id_at_capture": "n999"}
    second = build(second_input, snapshot_id="b" * 32, captured_at=1799999999, label="다른 라벨")
    assert first["ir_hash"] == second["ir_hash"]
    assert len(first["ir_hash"]) == 64
    assert first["snapshot_id"] != second["snapshot_id"]


def test_ir_hash_ignores_sub_rounding_noise_but_catches_real_change(mcad_result):
    base = build([mcad_result])
    noisy = copy.deepcopy(mcad_result)
    # 길이 반올림은 0.001 mm — 그보다 작은 잡음은 해시를 흔들지 않는다.
    noisy["edges"][0]["attrs"]["min_gap"] = 0.00004
    assert build([noisy])["ir_hash"] == base["ir_hash"]
    real = copy.deepcopy(mcad_result)
    real["edges"][0]["attrs"]["min_gap"] = 0.02
    assert build([real])["ir_hash"] != base["ir_hash"]


def test_ir_hash_changes_when_dims_or_ledger_change(mcad_result):
    base = build([mcad_result])
    with_dim = build([mcad_result], dim_defs=[{"name": "n_leaf", "extractor": "overall.n_leaf", "unit": "count"}])
    assert with_dim["ir_hash"] != base["ir_hash"]
    ledger = [{"project_id": PROJECT, "pair_key": "/a_stack.step/STACK_ASM/PLATE_1|/a_stack.step/STACK_ASM/PLATE_2",
               "kind_override": "touching", "status": "confirmed"}]
    assert build([mcad_result], iface_ledger=ledger)["ir_hash"] != base["ir_hash"]


def test_compute_ir_hash_only_reads_the_declared_inputs():
    ir = {
        "nodes": [{"nid": "p:1", "canon_key": "c", "domain": "mcad", "kind": "part",
                   "name_norm": "a", "name_norm_canon": "a", "ckey": None, "dn": "p:1",
                   "asm_key": None, "status_flags": [], "attrs": {"min_gap": 0.12345678}}],
        "edges": [], "same_as": [], "dims_named": [],
    }
    digest = ib.compute_ir_hash(ir)
    louder = copy.deepcopy(ir)
    louder["nodes"][0]["label"] = "무시되는 표시명"
    louder["nodes"][0]["provenance"] = {"call_id": "x"}
    louder["warnings"] = [{"code": "whatever"}]
    louder["rollups"] = {"by_assembly": [{"path_prefix": "x"}]}
    louder["gates"] = {"G1": {"pass": False}}
    assert ib.compute_ir_hash(louder) == digest
    # 확정되지 않은 same_as 는 해시에 들어가지 않는다.
    pending = copy.deepcopy(ir)
    pending["same_as"] = [{"a": "p:1", "b": "p:2", "method": "name_norm", "status": "auto"}]
    assert ib.compute_ir_hash(pending) == digest
    confirmed = copy.deepcopy(pending)
    confirmed["same_as"][0]["status"] = "confirmed"
    assert ib.compute_ir_hash(confirmed) != digest


def test_round_attrs_applies_kind_rules_down_the_subtree():
    rounded = ib.round_attrs({"min_gap": 0.12345, "volume": 1234.5678, "fs": 1.234,
                              "note": "원문", "nothing": 0.98765,
                              "bbox_def": [0.00049, 1.23456]})
    assert rounded["min_gap"] == 0.123
    assert rounded["volume"] == 1235.0
    assert rounded["fs"] == 1.23
    assert rounded["note"] == "원문"
    assert rounded["nothing"] == 0.98765      # 규칙표에 없는 키는 원값이다
    assert rounded["bbox_def"] == [0.0, 1.235]  # 하위 트리에 같은 kind 를 적용한다


# ---------------------------------------------------------------- 봉투(plan §2.2)
def test_envelope_has_every_declared_field(mcad_result):
    ir = build([mcad_result], snapshot_id="c" * 32, derived_from="b" * 32)
    for key in ("ir_version", "snapshot_id", "project_id", "owner_sub", "label", "captured_at",
                "derived_from", "partial", "sources", "units", "nodes", "edges", "same_as",
                "dims_named", "rollups", "results", "missing", "warnings", "gates",
                "character_seed", "feature_vector", "ir_hash", "versions"):
        assert key in ir, f"봉투에 {key} 가 없다"
    assert ir["ir_version"] == "1.0"
    assert ir["snapshot_id"] == "c" * 32 and ir["derived_from"] == "b" * 32
    assert ir["units"] == {"length": "mm", "area": "mm2", "volume": "mm3",
                           "stress": "MPa", "accel": "G", "density": "as_in_file"}
    assert ir["partial"] is False and ir["results"] is None
    # 게이트·씨앗·벡터는 state.py 가 채우므로 조립 시점에는 비어 있다.
    assert ir["gates"] == {} and ir["character_seed"] == [] and ir["feature_vector"] == {}
    assert ir["versions"]["adapter_versions"] == {"mcad": "1.0"}
    for stamp in ("taxonomy_version", "seed_rules_version", "vocab_version"):
        assert ir["versions"][stamp]


def test_sources_are_ordered_and_defaulted(mcad_result, dyna_result, dyna_result_layer):
    shuffled = [dyna_result_layer, dyna_result, mcad_result]
    ir = build(shuffled)
    assert [s["kind"] for s in ir["sources"]] == ["mcad", "dyna", "dyna_result"]
    dyna = next(s for s in ir["sources"] if s["kind"] == "dyna")
    assert dyna["degraded"] == ["no_secid"]            # 정렬된 문자열 목록
    assert dyna["captured_at"] == 1756600000           # 없으면 봉투 captured_at 을 물려받는다


def test_dyna_only_snapshot_stands_with_dyna_as_the_primary_source(dyna_result):
    """mcad 없이도 IR 은 선다 — primary_source='dyna'·missing.mcad_absent=true 다(plan §2.2·§0.9 P2-13)."""
    ir = build([dyna_result])
    assert ir["primary_source"] == "dyna"
    assert ir["missing"]["mcad_absent"] is True
    assert [s["kind"] for s in ir["sources"]] == ["dyna_result"] or "mcad" not in \
        {s["kind"] for s in ir["sources"]}

    with pytest.raises(AppError) as empty:
        build([])
    assert empty.value.code == "E100" and empty.value.http_status == 409


def test_unknown_and_duplicated_source_kinds_are_rejected(mcad_result):
    bogus = copy.deepcopy(mcad_result)
    bogus["source"]["kind"] = "sketchup"
    with pytest.raises(AppError) as exc:
        build([bogus])
    assert exc.value.code == "E100"
    with pytest.raises(AppError) as exc:
        build([mcad_result, copy.deepcopy(mcad_result)])
    assert "최대 1건" in exc.value.message


def test_ecad_nodes_bump_ir_version_to_1_1(mcad_result):
    ecad = {
        "source": {"kind": "ecad", "app_key": "heax-odb", "adapter_version": "1.0", "channel": "mcp",
                   "ref": {"board_id": "B1"}, "source_hash": "sha-ecad", "degraded": []},
        "nodes": [{"canon_key": "ecad:U1", "domain": "ecad", "kind": "component", "label": "U1",
                   "local_key": "U1", "attrs": {"refdes": "U1", "part_number": "AP1234",
                                                "footprint": "BGA-100", "pin_count": 100,
                                                "side": "top"}}],
        "edges": [], "warnings": [], "degraded": [], "call_ids": [],
    }
    ir = build([mcad_result, ecad])
    assert ir["ir_version"] == "1.1" and ir["versions"]["ir_version"] == "1.1"
    assert ir["missing"]["ecad_absent"] is False
    component = node_by_ck(ir, "ecad:U1")
    assert component["geom_fp"] is not None      # footprint + pin_count 지문


# ---------------------------------------------------------------- 노드 정규화(plan §2.3·§2.7)
def test_nodes_are_normalized(mcad_result):
    ir = build([mcad_result])
    plate = node_by_ck(ir, PLATE_1)
    assert plate["nid"] == ib.make_nid(PLATE_1)
    assert plate["name_norm"] == "plate_1" and plate["name_norm_canon"] == "plate_1"
    assert plate["asm_key"] == "a_stack/stack_asm"
    assert plate["geom_fp"] and len(plate["geom_fp"]) == 16
    assert plate["ckey"].startswith("ck:") and plate["dn"] == plate["nid"]
    assert plate["parent_nid"] == ib.make_nid("mcad:/a_stack.step/STACK_ASM")
    assert plate["group"] == "stack_asm"          # 부모 assembly 의 name_norm
    assert plate["status_flags"] == []
    # 노드는 nid 오름차순으로 정렬돼 있다.
    assert [n["nid"] for n in ir["nodes"]] == sorted(n["nid"] for n in ir["nodes"])


def test_node_without_canon_key_or_with_duplicate_canon_key_is_rejected(mcad_result):
    broken = copy.deepcopy(mcad_result)
    broken["nodes"][2].pop("canon_key")
    with pytest.raises(AppError) as exc:
        build([broken])
    assert exc.value.code == "E100"
    duplicated = copy.deepcopy(mcad_result)
    duplicated["nodes"].append(copy.deepcopy(duplicated["nodes"][2]))
    with pytest.raises(AppError) as exc:
        build([duplicated])
    assert "중복" in exc.value.message


def test_duplicate_leaf_names_get_the_duplicate_name_flag(mcad_result):
    twins = copy.deepcopy(mcad_result)
    clone = copy.deepcopy(twins["nodes"][2])
    clone["canon_key"] = "mcad:/a_stack.step/OTHER_ASM/PLATE_1"
    clone["local_key"] = "/sif-e2e/a_stack.step/OTHER_ASM/PLATE_1"
    clone.pop("parent_canon_key", None)
    twins["nodes"].append(clone)
    ir = build([twins])
    flagged = [n["label"] for n in ir["nodes"] if "duplicate_name" in n["status_flags"]]
    assert flagged == ["PLATE_1", "PLATE_1"]
    # 이름이 유일한 리프에는 붙지 않는다.
    assert "duplicate_name" not in node_by_ck(ir, PLATE_2)["status_flags"]


def test_auto_named_flag_drops_the_instance_suffix(mcad_result):
    auto = copy.deepcopy(mcad_result)
    auto["nodes"][2]["label"] = "SOLID_7"
    auto["nodes"][2]["status_flags"] = ["auto_named"]
    ir = build([auto])
    node = node_by_ck(ir, PLATE_1)
    assert node["name_norm"] == "solid"
    assert node["status_flags"] == ["auto_named"]


def test_dyna_nodes_join_the_mcad_cluster_and_share_the_ckey(mcad_result, dyna_result):
    ir = build([mcad_result, dyna_result])
    dyna_node = node_by_ck(ir, "dyna:abcd1234:1")
    mcad_node = node_by_ck(ir, PLATE_1)
    assert dyna_node["dn"] == mcad_node["nid"]        # 대표는 mcad part(plan §2.7.5)
    assert dyna_node["ckey"] == mcad_node["ckey"]
    assert ir["same_as"], "다중 도메인이면 same-as 사다리가 돈다"
    assert ir["same_as"] == sorted(ir["same_as"], key=lambda s: (s["a"], s["b"]))


def test_sameas_ledger_is_not_the_iface_ledger(mcad_result, dyna_result):
    """사다리 1단계 원장은 rr_sameas(stable 키 쌍 색인)다 — rr_iface_ledger 를 넘기면 안 된다."""
    ledger = [{"project_id": PROJECT, "pair_key": "/a_stack.step/STACK_ASM/PLATE_1|/a_stack.step/STACK_ASM/PLATE_2",
               "kind_override": None, "status": "confirmed"}]
    ir = build([mcad_result, dyna_result], iface_ledger=ledger)
    assert edge_of(ir, "tied")["status"] == "manual_ledger"
    captured = {}

    def spy(nodes_a, nodes_b, edges_a, edges_b, scope, ledger_arg):
        captured["ledger"] = ledger_arg
        captured["scope"] = scope
        return []

    stable_ledger = {("mcad:x", "mcad:y"): {"id": "sa1", "status": "confirmed"}}
    build([mcad_result, dyna_result], iface_ledger=ledger, sameas_ledger=stable_ledger, sameas_resolve=spy)
    assert captured["scope"] == "intra"
    assert captured["ledger"] == stable_ledger


# ---------------------------------------------------------------- 엣지 정규화(plan §2.4)
def test_edges_are_normalized(mcad_result):
    ir = build([mcad_result])
    tied = edge_of(ir, "tied")
    a, b = ib.make_nid(PLATE_1), ib.make_nid(PLATE_2)
    assert tied["eid"] == ib.make_eid("iface", a, b)
    assert tied["kind_family"] == "iface" and tied["status"] == "confirmed"
    assert edge_of(ir, "interference")["kind_family"] == "iface"
    part_of = edge_of(ir, "part_of")
    assert part_of["kind_family"] == "hier"
    assert part_of["eid"] == ib.make_eid("hier", part_of["a"], part_of["b"], directed=True)
    assert [e["eid"] for e in ir["edges"]] == sorted(e["eid"] for e in ir["edges"])


def test_edge_endpoints_may_be_swapped_without_changing_the_eid(mcad_result):
    swapped = copy.deepcopy(mcad_result)
    swapped["edges"][0]["a"], swapped["edges"][0]["b"] = swapped["edges"][0]["b"], swapped["edges"][0]["a"]
    assert edge_of(build([swapped]), "tied")["eid"] == edge_of(build([mcad_result]), "tied")["eid"]


def test_duplicate_edges_are_dropped_and_unknown_kinds_raise(mcad_result):
    doubled = copy.deepcopy(mcad_result)
    doubled["edges"].append(copy.deepcopy(doubled["edges"][0]))
    assert len(build([doubled])["edges"]) == len(build([mcad_result])["edges"])
    bogus = copy.deepcopy(mcad_result)
    bogus["edges"][0]["kind"] = "welded"
    with pytest.raises(AppError) as exc:
        build([bogus])
    assert exc.value.code == "E100"


def test_unresolvable_edge_endpoint_is_dropped_with_a_warning(mcad_result):
    dangling = copy.deepcopy(mcad_result)
    dangling["edges"][1]["b"] = "mcad:/a_stack.step/STACK_ASM/GHOST"
    ir = build([dangling])
    assert not [e for e in ir["edges"] if e["kind"] == "interference"]
    warning = next(w for w in ir["warnings"] if w["code"] == "ambiguous_edge_endpoint")
    assert warning["severity"] == "WARNING"


def _with_bridges(mcad_result: dict, pids) -> dict:
    """mcad 결과에 어댑터가 내는 모양의 브리지 원시 엣지(`a_canon_key`·`b_pid`)를 얹는다."""
    out = copy.deepcopy(mcad_result)
    for canon, pid in zip((PLATE_1, PLATE_2, BRACKET), pids):
        out["edges"].append({"kind": "bridge", "domain": "mcad", "status": "auto", "a_canon_key": canon,
                             "b_pid": str(pid), "attrs": {"dyna": {"bridge": {"join_key": f"file+name:{canon}"}}}})
    return out


def test_bridges_without_any_dyna_pid_leave_one_note_not_one_warning_per_row(mcad_result):
    """dyna pid 가 하나도 없는 스냅샷에서는 브리지를 잇지 않고 **한 줄**만 남긴다.

    part_mesh 표는 StepForge 가 주므로 K파일을 싣지 않은 스냅샷(mcad 만)에도 메시 행 수만큼 브리지 후보가
    온다. 그 행마다 `ambiguous_edge_endpoint` 를 남기면 파트 수만큼 같은 경고가 쌓여, 코드 순으로 맨 앞에
    서는 그 경고가 좌표·단위 경고를 화면과 브리프에서 밀어낸다. 이을 상대가 없다는 사실은 하나다.
    """
    ir = build([_with_bridges(mcad_result, (1, 2, 3))])

    assert [e for e in ir["edges"] if e["kind"] == "bridge"] == []
    assert not [w for w in ir["warnings"] if w["code"] == "ambiguous_edge_endpoint"], ir["warnings"]
    notes = [w for w in ir["warnings"] if w["code"] == "bridge_without_dyna"]
    assert len(notes) == 1 and notes[0]["severity"] == "INFO" and notes[0]["source_kind"] == "ir_builder"
    assert "3건" in notes[0]["message"]


def test_a_bridge_to_a_pid_the_kfile_lacks_still_warns_per_row(mcad_result, dyna_result):
    """dyna 는 있는데 그 pid 만 없으면 행마다 남긴다 — 그건 메시 표와 K파일이 어긋났다는 신호다."""
    ir = build([_with_bridges(mcad_result, (1, 2, 99)), dyna_result])

    assert len([e for e in ir["edges"] if e["kind"] == "bridge"]) == 2
    unresolved = [w for w in ir["warnings"] if w["code"] == "ambiguous_edge_endpoint"]
    assert len(unresolved) == 1 and "pid:99" in unresolved[0]["message"]
    assert not [w for w in ir["warnings"] if w["code"] == "bridge_without_dyna"]


def test_scope_hyperedge_keeps_members(mcad_result, dyna_result):
    hyper = copy.deepcopy(dyna_result)
    hyper["nodes"].append({
        "canon_key": "dyna:abcd1234:contact:2", "domain": "dyna", "kind": "contact_set",
        "label": "single_surface", "local_key": "2",
        "attrs": {"contact_index": 2, "contact_type": "*CONTACT_AUTOMATIC_SINGLE_SURFACE",
                  "title": "ss", "n_members": 2},
    })
    hyper["edges"].append({
        "kind": "scope", "domain": "dyna", "status": "auto",
        "a": "dyna:abcd1234:contact:2", "b": None,
        "members": ["dyna:abcd1234:1", "dyna:abcd1234:2"],
        "attrs": {"contact_index": 2, "contact_type": "*CONTACT_AUTOMATIC_SINGLE_SURFACE", "title": "ss"},
    })
    ir = build([mcad_result, hyper])
    scope = edge_of(ir, "scope")
    assert scope["b"] is None and scope["kind_family"] == "contact"
    assert scope["members"] == sorted([ib.make_nid("dyna:abcd1234:1"), ib.make_nid("dyna:abcd1234:2")])


# ---------------------------------------------------------------- 원장 재적용(plan §2.10)
def _ledger_row(path_a: str, path_b: str, **row) -> dict:
    base = {"project_id": PROJECT, "pair_key": "|".join(sorted([path_a, path_b])),
            "kind_override": None, "status": "confirmed", "note": None,
            "geom_fp_a": None, "geom_fp_b": None,
            "decided_by": OWNER, "decided_at": 1756590000}
    base.update(row)
    return base


def test_ledger_confirm_overrides_source_status(mcad_result):
    ledger = [_ledger_row("/a_stack.step/STACK_ASM/PLATE_2", "/a_stack.step/STACK_ASM/BRACKET_L")]
    ir = build([mcad_result], iface_ledger=ledger)
    assert edge_of(ir, "interference")["status"] == "manual_ledger"
    assert edge_of(ir, "tied")["status"] == "confirmed"        # 원장이 없는 엣지는 소스 값 그대로


def test_ledger_kind_override_keeps_the_source_kind(mcad_result):
    ledger = [_ledger_row("/a_stack.step/STACK_ASM/PLATE_2", "/a_stack.step/STACK_ASM/BRACKET_L",
                          kind_override="touching")]
    ir = build([mcad_result], iface_ledger=ledger)
    touching = edge_of(ir, "touching")
    assert touching["attrs"]["kind_source"] == "interference"
    assert touching["status"] == "manual_ledger"
    # eid 는 kind_family 로 만들어지므로 kind 를 덮어도 그대로다(diff 가 kind_changed 로 잡는다).
    assert touching["eid"] == edge_of(build([mcad_result]), "interference")["eid"]


def test_ledger_rejected_status_survives_into_the_ir(mcad_result):
    ledger = [_ledger_row("/a_stack.step/STACK_ASM/PLATE_1", "/a_stack.step/STACK_ASM/PLATE_2",
                          status="rejected")]
    ir = build([mcad_result], iface_ledger=ledger)
    assert edge_of(ir, "tied")["status"] == "rejected"
    # rejected 는 롤업에서 빠진다.
    depth1 = next(r for r in ir["rollups"]["by_assembly"] if r["depth"] == 1)
    assert "tied" not in depth1["edges_internal"]


def test_ledger_geom_change_and_absent_pair_are_reported(mcad_result):
    ledger = [
        _ledger_row("/a_stack.step/STACK_ASM/PLATE_1", "/a_stack.step/STACK_ASM/PLATE_2",
                    geom_fp_a="0123456789abcdef", geom_fp_b="fedcba9876543210"),
        _ledger_row("/a_stack.step/STACK_ASM/GHOST_A", "/a_stack.step/STACK_ASM/GHOST_B"),
    ]
    ir = build([mcad_result], iface_ledger=ledger)
    review = next(w for w in ir["warnings"] if w["code"] == "ledger_needs_review")
    assert review["severity"] == "INFO" and review["ref"] == edge_of(ir, "tied")["eid"]
    absent = next(w for w in ir["warnings"] if w["code"] == "ledger_pair_absent")
    assert "GHOST_A" in absent["message"]
    # 적용은 그대로 한다(경고는 표기일 뿐이다).
    assert edge_of(ir, "tied")["status"] == "manual_ledger"


# ---------------------------------------------------------------- rollups(plan §2.9)
def test_rollups_count_leaves_and_edges_per_prefix(mcad_result):
    ir = build([mcad_result])
    rows = {r["path_prefix"]: r for r in ir["rollups"]["by_assembly"]}
    assert sorted(rows) == ["a_stack", "a_stack/stack_asm"]
    assert rows["a_stack"]["depth"] == 1 and rows["a_stack/stack_asm"]["depth"] == 2
    assert rows["a_stack"]["n_leaf"] == 3
    assert rows["a_stack"]["edges_internal"] == {"interference": 1, "tied": 1}
    assert rows["a_stack"]["edges_external"] == {}
    assert rows["a_stack"]["orphan_leaf"] == 0


def test_rollup_orphan_ignores_clearance_and_external_edges(mcad_result):
    lonely = copy.deepcopy(mcad_result)
    # BRACKET_L 을 clearance 로만 잇는다 — clearance 는 '닿음' 이 아니므로 고아다.
    lonely["edges"][1]["kind"] = "clearance"
    lonely["edges"][1]["attrs"]["min_gap"] = 0.2
    lonely["edges"][1]["attrs"]["penetration_depth"] = None
    ir = build([lonely])
    depth1 = next(r for r in ir["rollups"]["by_assembly"] if r["depth"] == 1)
    assert depth1["orphan_leaf"] == 1
    assert depth1["edges_internal"] == {"clearance": 1, "tied": 1}


def test_rollup_marks_cross_prefix_edges_as_external():
    two_files = load_fixture("gates/gate_f5_partial.json")["adapter_results"]
    ir = build(two_files)
    rows = {r["path_prefix"]: r for r in ir["rollups"]["by_assembly"]}
    assert rows["a_stack"]["edges_external"] == {"clearance": 1}
    assert rows["b_cover"]["edges_external"] == {"clearance": 1}
    assert rows["a_stack"]["edges_internal"] == {"tied": 1}


# ---------------------------------------------------------------- dims_named(plan §2.8)
def _dims(ir) -> dict:
    return {d["name"]: d for d in ir["dims_named"]}


def test_dims_named_evaluates_each_extractor_form(mcad_result):
    plate_ck = node_by_ck(build([mcad_result]), PLATE_1)["ckey"]
    defs = [
        {"name": "declared_gap", "extractor": "const:0.35", "unit": "mm"},
        {"name": "plate_thickness", "extractor": f"node[ck={plate_ck}].attrs.min_dim", "unit": "mm"},
        {"name": "plate_volume", "extractor": "node[asm=a_stack/stack_asm/plate_2].attrs.volume", "unit": "mm3"},
        {"name": "stack_gap", "extractor": "edge[name=plate_1|plate_2].attrs.min_gap", "unit": "mm"},
        {"name": "n_leaf", "extractor": "overall.n_leaf", "unit": "count"},
        {"name": "overall_z", "extractor": "overall.bbox_world.z", "unit": "mm"},
        {"name": "total_volume", "extractor": "overall.volume", "unit": "mm3"},
        {"name": "stack_volume", "extractor": "sum(node[asm=a_stack/*].attrs.volume)", "unit": "mm3"},
        {"name": "delta", "extractor": "dim(plate_thickness) - dim(declared_gap)", "unit": "mm"},
    ]
    dims = _dims(build([mcad_result], dim_defs=defs))
    assert [d["name"] for d in build([mcad_result], dim_defs=defs)["dims_named"]] == sorted(dims)
    assert (dims["declared_gap"]["value"], dims["declared_gap"]["method"]) == (0.35, "declared")
    assert (dims["plate_thickness"]["value"], dims["plate_thickness"]["method"]) == (1.2, "measured")
    assert dims["plate_thickness"]["ref"] == ib.make_nid(PLATE_1)
    assert dims["plate_volume"]["value"] == 2500.0
    assert dims["stack_gap"]["value"] == 0.0 and dims["stack_gap"]["ref"].startswith("e:")
    assert dims["n_leaf"]["value"] == 3 and dims["n_leaf"]["unit"] == "count"
    assert dims["overall_z"]["value"] == pytest.approx(1.2)
    assert dims["total_volume"]["value"] == pytest.approx(5700.0)
    assert (dims["stack_volume"]["value"], dims["stack_volume"]["method"]) == (5700.0, "derived")
    assert dims["delta"]["value"] == pytest.approx(0.85) and dims["delta"]["method"] == "derived"
    assert dims["delta"]["ref"] == ["plate_thickness", "declared_gap"]
    assert all(d["owner_sub"] == OWNER and d["null_reason"] is None for d in dims.values())
    assert all(d["formula"] for d in dims.values())


def test_dims_named_uses_null_with_a_reason_instead_of_zero(mcad_result):
    twins = copy.deepcopy(mcad_result)
    clone = copy.deepcopy(twins["nodes"][2])
    clone["canon_key"] = "mcad:/a_stack.step/STACK_ASM_2/PLATE_1"
    clone["local_key"] = "/sif-e2e/a_stack.step/STACK_ASM_2/PLATE_1"
    clone.pop("parent_canon_key", None)
    twins["nodes"].append(clone)
    defs = [
        {"name": "gone", "extractor": "node[asm=a_stack/stack_asm/no_such_part].attrs.min_dim"},
        {"name": "empty_attr", "extractor": "node[asm=a_stack/stack_asm/plate_2].attrs.color"},
        {"name": "ambiguous_leaf", "extractor": "node[ck=" + node_by_ck(build([twins]), PLATE_1)["ckey"] + "].attrs.min_dim"},
        {"name": "bad_syntax", "extractor": "node.min_dim"},
        {"name": "orphan_derived", "extractor": "dim(gone) * dim(empty_attr)"},
    ]
    dims = _dims(build([twins], dim_defs=defs))
    assert dims["gone"]["value"] is None and dims["gone"]["null_reason"] == "ref_missing"
    assert dims["empty_attr"]["value"] is None and dims["empty_attr"]["null_reason"] == "attr_null"
    assert dims["ambiguous_leaf"]["null_reason"] == "ambiguous"
    assert dims["bad_syntax"]["null_reason"] == "ref_missing"
    assert dims["orphan_derived"]["value"] is None and dims["orphan_derived"]["null_reason"] == "attr_null"


def test_dims_named_reports_scope_out_separately(mcad_result):
    scoped = copy.deepcopy(mcad_result)
    scoped["source"]["scope"] = {"match": ["PLATE*"]}
    scoped["nodes"][4]["status_flags"] = ["scope_out"]
    defs = [{"name": "bracket_thickness", "extractor": "node[asm=a_stack/stack_asm/bracket_l].attrs.min_dim"}]
    ir = build([scoped], dim_defs=defs)
    row = _dims(ir)["bracket_thickness"]
    assert row["value"] is None and row["null_reason"] == "scope_out"
    assert row["ref"] == ib.make_nid(BRACKET)
    assert ir["partial"] is True


def test_dims_named_unit_comes_from_the_vocab(mcad_result):
    defs = [{"name": "total_volume", "extractor": "overall.volume", "unit": "mm"}]
    vocab = {"total_volume": {"unit": "mm3", "kind": "overall"}}
    dims = _dims(build([mcad_result], dim_defs=defs, dim_vocab=vocab))
    assert dims["total_volume"]["unit"] == "mm3"


def test_dims_named_reads_the_result_layer(mcad_result, dyna_result, dyna_result_layer):
    ir = build([mcad_result, dyna_result, dyna_result_layer])
    dyna_ck = node_by_ck(ir, "dyna:abcd1234:1")["ckey"]
    defs = [{"name": "plate_worst_stress", "extractor": f"result[ck={dyna_ck}].worst_stress", "unit": "MPa"},
            {"name": "no_results", "extractor": "result[ck=ck:000000000000].worst_stress", "unit": "MPa"}]
    dims = _dims(build([mcad_result, dyna_result, dyna_result_layer], dim_defs=defs))
    assert dims["plate_worst_stress"]["value"] == pytest.approx(231.4)
    assert dims["no_results"]["value"] is None and dims["no_results"]["null_reason"] == "ref_missing"


# ---------------------------------------------------------------- results·missing(plan §2.2·§2.9)
def test_results_overlay_lands_on_the_dyna_node_and_moves_the_hash(mcad_result, dyna_result, dyna_result_layer):
    without = build([mcad_result, dyna_result])
    with_results = build([mcad_result, dyna_result, dyna_result_layer])
    node = node_by_ck(with_results, "dyna:abcd1234:1")
    assert node["attrs"]["results"]["worst_stress"] == {"value": 231.4, "case_key": "c1"}
    assert node["attrs"]["results"]["report_id"] == "01JRPT"
    assert with_results["results"]["kind"] == "sphere"
    assert with_results["ir_hash"] != without["ir_hash"]        # 결과가 붙으면 새 스냅샷이다


@pytest.mark.parametrize("flag,expected_without_dyna", [
    ("ecad_absent", True), ("dyna_absent", True), ("dyna_result_absent", False),
    ("result_kind_mismatch", False), ("world_transform_absent", False),
    ("volume_null", False), ("material_density_unsourced", False),
])
def test_missing_flags_for_an_mcad_only_snapshot(mcad_result, flag, expected_without_dyna):
    assert build([mcad_result])["missing"][flag] is expected_without_dyna


def test_missing_flags_follow_the_sources(mcad_result, dyna_result, dyna_result_layer):
    with_dyna = build([mcad_result, dyna_result])
    assert with_dyna["missing"]["dyna_absent"] is False
    assert with_dyna["missing"]["dyna_result_absent"] is True     # 결속된 리포트가 없다
    full = build([mcad_result, dyna_result, dyna_result_layer])
    assert full["missing"]["dyna_result_absent"] is False

    stripped = copy.deepcopy(mcad_result)
    for node in stripped["nodes"]:
        if node["kind"] == "part":
            node["attrs"]["bbox_world"] = None
            node["attrs"]["centroid_world"] = None
            node["attrs"]["volume"] = None
    degraded = build([stripped])
    assert degraded["missing"]["world_transform_absent"] is True
    assert degraded["missing"]["volume_null"] is True


def test_adapter_declared_missing_flags_win(mcad_result):
    declared = copy.deepcopy(mcad_result)
    declared["missing"] = {"material_density_unsourced": True, "not_a_flag": True}
    ir = build([declared])
    assert ir["missing"]["material_density_unsourced"] is True
    assert "not_a_flag" not in ir["missing"]


def test_density_without_a_unit_marks_material_density_unsourced(mcad_result):
    unsourced = copy.deepcopy(mcad_result)
    unsourced["nodes"][2]["attrs"]["density"] = 2.7
    assert build([unsourced])["missing"]["material_density_unsourced"] is True


def test_warnings_are_sorted_and_carry_the_source_kind(mcad_result):
    noisy = copy.deepcopy(mcad_result)
    noisy["warnings"] = [
        {"severity": "WARNING", "code": "source_inconsistent", "message": "b"},
        {"code": "auto_named", "message": "a", "ref": "a_stack.step#P3"},
    ]
    ir = build([noisy])
    codes = [w["code"] for w in ir["warnings"]]
    assert codes == sorted(codes)
    auto = next(w for w in ir["warnings"] if w["code"] == "auto_named")
    assert auto["severity"] == "WARNING" and auto["source_kind"] == "mcad"


# ---------------------------------------------------------------- 동결·호출 원문(plan §2.11.3·§2.11.4)
def test_freeze_snapshot_writes_every_table(risk_store, mcad_result):
    calls = [{"source_kind": "mcad", "channel": "rest", "tool": "GET /tree", "args": {"id": 1},
              "response": {"ok": True}, "started_at": 10, "duration_ms": 5, "http_status": 200}]
    result = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="DV1",
                                adapter_results=[mcad_result], calls=calls, captured_at=1756600000)
    assert result["reused"] is False and result["partial"] is False and result["blocked"] is False
    assert set(result["gates_summary"]) == {"G1", "G2", "G3", "G4", "G5", "G6"}
    snapshot = risk_store.query_one(
        "SELECT id, project_id, owner_sub, ir_version, ir_hash, node_count, edge_count, warnings_n, degraded"
        " FROM rr_snapshots WHERE id = ?", (result["snapshot_id"],))
    assert snapshot["ir_hash"] == result["ir_hash"] and snapshot["owner_sub"] == OWNER
    assert snapshot["node_count"] == 5 and snapshot["edge_count"] == 3 and snapshot["degraded"] is None
    nodes = risk_store.query("SELECT nid, ckey, dn, asm_key, material_norm FROM rr_ir_nodes WHERE snapshot_id = ?",
                             (result["snapshot_id"],))
    assert len(nodes) == 5
    edges = risk_store.query("SELECT eid, kind, b, subject_key FROM rr_ir_edges WHERE snapshot_id = ?",
                             (result["snapshot_id"],))
    assert len(edges) == 3
    assert all(row["b"] is not None for row in edges)        # b 는 NOT NULL 이라 빈 문자열로 눕힌다
    keys = risk_store.query("SELECT ckey, status, n_projects, n_snapshots FROM rr_part_keys", ())
    assert keys and all(row["status"] == "candidate" for row in keys)
    state = risk_store.query_one("SELECT snapshot_id, blocked, state_version FROM rr_states WHERE snapshot_id = ?",
                                 (result["snapshot_id"],))
    assert state["blocked"] == 0 and state["state_version"] == "1.0"


def test_freeze_snapshot_reuses_the_same_ir_hash(risk_store, mcad_result):
    call = [{"source_kind": "mcad", "channel": "rest", "tool": "GET /tree", "args": {}, "response": {"n": 1}}]
    first = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="DV1",
                               adapter_results=[mcad_result], calls=call, captured_at=1756600000)
    second = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="다시",
                                adapter_results=[mcad_result], calls=call, captured_at=1756699999)
    assert second["reused"] is True
    assert second["snapshot_id"] == first["snapshot_id"] and second["ir_hash"] == first["ir_hash"]
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_snapshots", ())["n"] == 1
    # 재사용 경로도 이번 호출 로그는 덧붙인다.
    assert len(ib.load_calls(risk_store, first["snapshot_id"])) == 2
    # 스냅샷 본문은 UPDATE 하지 않는다(불변).
    assert ib.load_ir(risk_store, first["snapshot_id"])["label"] == "DV1"


def test_reuse_returns_this_calls_corpus_not_the_frozen_one(risk_store, mcad_result):
    """전사 집계는 시변인데 스냅샷은 불변이다 — 재사용이 이번 값을 버리지 않는다(§2.1·§2.2).

    같은 `ir_hash` 면 `ir_json` 은 첫 캡처 값 그대로다. 그래서 응답이 ① 이번에 받은 값 ② 얼어 있는 값의
    조회 시각 ③ 달라졌는지를 모두 낸다. 이게 없으면 조직 집계가 첫 스냅샷에 조용히 얼어붙는다.
    """
    first = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="DV1",
                               adapter_results=[mcad_result], captured_at=1756600000,
                               context={"corpus_usage": {"sessions": 12, "fetched_at": 1756600000}})
    assert first["reused"] is False
    assert first["context_frozen_at"] == 1756600000 and first["context_changed"] is False

    second = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="다시",
                                adapter_results=[mcad_result], captured_at=1756699999,
                                context={"corpus_usage": {"sessions": 31, "fetched_at": 1756699999}})
    assert second["reused"] is True
    # 얼어 있는 값은 첫 시각이고, 이번 값은 그대로 돌려받는다.
    assert second["context_frozen_at"] == 1756600000
    assert second["context"]["corpus_usage"]["sessions"] == 31
    assert second["context_changed"] is True
    # 불변 — 얼어 있는 본문은 여전히 첫 값이다.
    assert ib.load_ir(risk_store, first["snapshot_id"])["context"]["corpus_usage"]["sessions"] == 12

    # 값이 같으면 변한 게 아니다 — fetched_at 만 달라도 changed 가 되면 아무것도 못 알려 준다.
    same = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="또",
                              adapter_results=[mcad_result], captured_at=1756777777,
                              context={"corpus_usage": {"sessions": 12, "fetched_at": 1756777777}})
    assert same["context_changed"] is False

    # 이번 4호출이 전부 실패하면 corpus_usage 는 None 이다 — 변했는지 '모른다'(False 가 아니다).
    dead = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="죽음",
                              adapter_results=[mcad_result], captured_at=1756888888,
                              context={"corpus_usage": None})
    assert dead["context_changed"] is None


def test_freeze_snapshot_stores_gates_and_seeds_inside_the_frozen_ir(risk_store, mcad_result):
    result = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="DV1",
                                adapter_results=[mcad_result], captured_at=1756600000)
    ir = ib.load_ir(risk_store, result["snapshot_id"])
    assert sorted(ir["gates"]) == ["G1", "G2", "G3", "G4", "G5", "G6"]
    assert ir["feature_vector"]["version"] == "fv-1.0"
    assert ir["ir_hash"] == result["ir_hash"]        # 게이트는 해시 입력이 아니므로 값이 그대로다


def test_freeze_snapshot_reports_degraded_sources(risk_store, mcad_result, dyna_result):
    degraded = copy.deepcopy(mcad_result)
    degraded["degraded"] = ["mcp_degraded", "no_world_transform"]
    result = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="DV1",
                                adapter_results=[degraded, dyna_result], captured_at=1756600000)
    assert result["degraded"] == ["mcp_degraded", "no_secid", "no_world_transform"]
    row = risk_store.query_one(
        "SELECT degraded, degraded_json, app_versions_json, primary_source FROM rr_snapshots WHERE id = ?",
        (result["snapshot_id"],))
    # degraded 는 배열의 첫 값만 담는 호환 컬럼이고 배열은 degraded_json 이다(plan §2.2).
    assert row["degraded"] == "mcp_degraded"
    assert json.loads(row["degraded_json"]) == ["mcp_degraded", "no_secid", "no_world_transform"]
    # 소스 앱 버전은 kind 별로 열에 남는다(ir_hash 입력이 아니다, §2.2·§0.9 P1-21).
    assert set(json.loads(row["app_versions_json"])) == {"mcad", "dyna"}


def test_record_calls_and_load_calls_round_trip(risk_store):
    calls = [
        {"source_kind": "mcad", "channel": "rest", "tool": "GET /tree", "args": {"b": 2, "a": 1},
         "response": {"nodes": [1, 2, 3]}, "started_at": 100, "duration_ms": 12, "http_status": 200},
        {"source_kind": "dyna", "channel": "mcp", "tool": "inspect_file", "args": {},
         "response": None, "ok": False, "error": "timeout"},
    ]
    ids = ib.record_calls(risk_store, "c3ff832377ee3e0bcdd66aa561bdfa33", OWNER, calls, start_seq=1)
    assert ids == ["c3ff8323-001", "c3ff8323-002"]
    loaded = ib.load_calls(risk_store, "c3ff832377ee3e0bcdd66aa561bdfa33")
    assert [c["call_id"] for c in loaded] == ids
    assert loaded[0]["response"] == {"nodes": [1, 2, 3]} and loaded[0]["ok"] is True
    assert loaded[0]["args"] == {"a": 1, "b": 2}
    assert loaded[1]["ok"] is False and loaded[1]["error"] == "timeout" and "response" not in loaded[1]
    # 원문 없이도 읽을 수 있다(목록 화면용).
    assert "response" not in ib.load_calls(risk_store, "c3ff832377ee3e0bcdd66aa561bdfa33",
                                           include_response=False)[0]
    # 이어붙이면 seq 가 이어진다.
    assert ib.record_calls(risk_store, "c3ff832377ee3e0bcdd66aa561bdfa33", OWNER, calls[:1]) == ["c3ff8323-003"]


def test_load_ir_raises_e404_for_an_unknown_snapshot(risk_store):
    with pytest.raises(AppError) as exc:
        ib.load_ir(risk_store, "0" * 32)
    assert exc.value.code == "E404" and exc.value.http_status == 404


def test_resolve_ckey_follows_the_merge_chain(risk_store):
    rows = [("ck:aaaaaaaaaaaa", "merged", "ck:bbbbbbbbbbbb"),
            ("ck:bbbbbbbbbbbb", "merged", "ck:cccccccccccc"),
            ("ck:cccccccccccc", "confirmed", None)]
    for ckey, status, into in rows:
        risk_store.execute(
            "INSERT INTO rr_part_keys (ckey, owner_sub, status, merged_into, name_norm_canon, geom_bucket,"
            " material_norm) VALUES (?,?,?,?,'plate','?@v?','na')", (ckey, OWNER, status, into))
    assert ib.resolve_ckey(risk_store, "ck:aaaaaaaaaaaa") == "ck:cccccccccccc"
    assert ib.resolve_ckey(risk_store, "ck:cccccccccccc") == "ck:cccccccccccc"
    assert ib.resolve_ckey(risk_store, "ck:no_such_key") == "ck:no_such_key"
    # 체인 상한(기본 5)을 넘으면 거기서 멈춘다.
    assert ib.resolve_ckey(risk_store, "ck:aaaaaaaaaaaa", max_hops=1) == "ck:bbbbbbbbbbbb"


def test_build_ir_applies_the_effective_ckey_from_the_ledger(risk_store, mcad_result):
    computed = node_by_ck(build([mcad_result]), PLATE_1)["ckey"]
    risk_store.execute(
        "INSERT INTO rr_part_keys (ckey, owner_sub, status, merged_into, name_norm_canon, geom_bucket,"
        " material_norm) VALUES (?,?, 'merged', 'ck:999999999999', 'plate', '?@v?', 'na')", (computed, OWNER))
    risk_store.execute(
        "INSERT INTO rr_part_keys (ckey, owner_sub, status, merged_into, name_norm_canon, geom_bucket,"
        " material_norm) VALUES ('ck:999999999999', ?, 'confirmed', NULL, 'plate', '?@v?', 'na')", (OWNER,))
    result = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="DV1",
                                adapter_results=[mcad_result], captured_at=1756600000)
    ir = ib.load_ir(risk_store, result["snapshot_id"])
    assert node_by_ck(ir, PLATE_1)["ckey"] == "ck:999999999999"


def test_part_keys_ledger_accumulates_aliases_across_projects(risk_store, mcad_result):
    variant = copy.deepcopy(mcad_result)
    variant["edges"] = []
    ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="DV1",
                       adapter_results=[mcad_result], captured_at=1756600000)
    ib.freeze_snapshot(risk_store, project_id="other-project", owner_sub=OWNER, label="DV1",
                       adapter_results=[variant], captured_at=1756600000)
    plate_ck = node_by_ck(build([mcad_result]), PLATE_1)["ckey"]
    row = risk_store.query_one(
        "SELECT n_projects, n_snapshots, aliases_json, first_project_id FROM rr_part_keys WHERE ckey = ?",
        (plate_ck,))
    assert row["n_projects"] == 2 and row["n_snapshots"] == 2
    assert row["first_project_id"] == PROJECT
    aliases = json.loads(row["aliases_json"])
    assert {a["project_id"] for a in aliases} == {PROJECT, "other-project"}


def test_freeze_snapshot_reads_the_project_ledgers_from_the_db(risk_store, mcad_result):
    risk_store.execute(
        "INSERT INTO rr_iface_ledger (project_id, pair_key, owner_sub, kind_override, status, decided_by, decided_at)"
        " VALUES (?,?,?,?,'confirmed',?,?)",
        (PROJECT, "|".join(sorted(["/a_stack.step/STACK_ASM/PLATE_1", "/a_stack.step/STACK_ASM/PLATE_2"])),
         OWNER, "touching", OWNER, 1756590000))
    risk_store.execute(
        "INSERT INTO rr_dim_defs (project_id, name, owner_sub, extractor, created_at)"
        " VALUES (?,?,?,?,?)", (PROJECT, "n_leaf", OWNER, "overall.n_leaf", 1756590000))
    risk_store.execute(
        "INSERT INTO rr_dim_vocab (name, kind, unit, vocab_version) VALUES ('n_leaf', 'count', 'count', 'vocab-1.0')",
        ())
    result = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="DV1",
                                adapter_results=[mcad_result], captured_at=1756600000)
    ir = ib.load_ir(risk_store, result["snapshot_id"])
    touching = edge_of(ir, "touching")
    assert touching["status"] == "manual_ledger" and touching["attrs"]["kind_source"] == "tied"
    assert _dims(ir)["n_leaf"] == {"name": "n_leaf", "value": 3, "unit": "count", "method": "measured",
                                   "ref": None, "formula": "overall.n_leaf", "owner_sub": OWNER,
                                   "null_reason": None}


def test_freeze_snapshot_can_skip_state(risk_store, mcad_result):
    result = ib.freeze_snapshot(risk_store, project_id=PROJECT, owner_sub=OWNER, label="DV1",
                                adapter_results=[mcad_result], captured_at=1756600000, with_state=False)
    assert result["gates_summary"] == {}
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_states", ())["n"] == 0
    assert ib.load_ir(risk_store, result["snapshot_id"])["gates"] == {}


@pytest.mark.parametrize("case", ("gate_f7_capture_partial", "gate_f8_unit_unknown"))
def test_freeze_snapshot_summary_keeps_an_unjudged_gate_null(risk_store, case):
    """동결 응답의 `gates_summary` 는 검문하지 못한 게이트(pass=null)를 false 로 접지 않는다(plan §2.12).

    `sig:gates.summary` 는 7e21f68 에서 3값이 됐는데 이 응답은 `bool()` 로 접고 있었다 — 입력이 없어 G3 를 못 본
    스냅샷이 `G3: false` 로 나가, 응답만 읽는 호출자는 검문하지도 않은 게이트를 위반으로 적는다. 같은 스냅샷의
    state 와 응답이 서로 다른 말을 한 것이다. 새로 얼린 분기와 재사용 분기를 둘 다 본다.
    """
    from app import state as st

    bundle = json.loads((IR_FIXTURES / "gates" / f"{case}.json").read_text(encoding="utf-8"))
    frozen = dict(project_id=PROJECT, owner_sub=OWNER, adapter_results=bundle["adapter_results"],
                  iface_ledger=bundle.get("iface_ledger") or (), captured_at=1756600000)
    first = ib.freeze_snapshot(risk_store, label="DV1", **frozen)
    gates = st.load_state(risk_store, first["snapshot_id"])["gates"]
    # 픽스처가 바뀌어 null 게이트가 없어지면 이 시험은 아무것도 묻지 않는다 — 그때는 여기서 걸린다.
    assert [k for k, g in gates.items() if g["pass"] is None]
    assert first["reused"] is False
    assert first["gates_summary"] == {k: g["pass"] for k, g in gates.items()}
    again = ib.freeze_snapshot(risk_store, label="다시", **frozen)
    assert again["reused"] is True and again["gates_summary"] == first["gates_summary"]


def test_fixture_directory_is_shipped():
    assert (IR_FIXTURES / "adapter_mcad_basic.json").exists()
    assert sorted(p.name for p in (IR_FIXTURES / "gates").glob("*.json")) == [
        "gate_f1_clean.json", "gate_f2_anon.json", "gate_f3_unit.json",
        "gate_f4_iface.json", "gate_f5_partial.json", "gate_f6_mcad_absent.json",
        "gate_f7_capture_partial.json", "gate_f8_unit_unknown.json",
    ]


# ---------------------------------------------------------------- 배선 회귀(intra 사다리·중첩 dict 반올림)
def test_ir_hash_is_stable_under_node_edge_and_attr_shuffle(mcad_result, dyna_result):
    """plan 1094행 결정론 두 번째 갈래 — 노드·엣지 배열 순서와 attrs 키 순서를 섞어도 ir_hash 가 같다."""
    import random

    first = build([mcad_result, dyna_result], snapshot_id="a" * 32)
    for seed in range(6):
        shuffled = copy.deepcopy([mcad_result, dyna_result])
        rng = random.Random(seed)
        for result in shuffled:
            rng.shuffle(result["nodes"])
            rng.shuffle(result.get("edges") or [])
            for node in result["nodes"]:
                node.update({k: node[k] for k in reversed(list(node))})
                if isinstance(node.get("attrs"), dict):
                    node["attrs"] = {k: node["attrs"][k] for k in reversed(list(node["attrs"]))}
        rng.shuffle(shuffled)                              # 소스 순서도 함께 섞는다
        assert build(shuffled, snapshot_id="b" * 32)["ir_hash"] == first["ir_hash"], f"seed={seed}"


def test_intra_sameas_never_matches_a_node_with_itself(mcad_result, dyna_result):
    """intra 사다리는 도메인 쌍마다 돈다 — 자기 자신과 맺힌 same_as 가 있으면 뒤 단계가 죽는다."""
    ir = build([mcad_result, dyna_result])
    assert ir["same_as"], "크로스도메인 대응이 하나도 없으면 이 회귀 시험이 무의미하다"
    assert [r for r in ir["same_as"] if r["a"] == r["b"]] == []
    for record in ir["same_as"]:
        doms = {n["domain"] for n in ir["nodes"] if n["nid"] in (record["a"], record["b"])}
        assert len(doms) == 2, f"intra 대응은 서로 다른 도메인 사이여야 한다 — {record}"


def test_round_attrs_inherits_kind_into_nested_dicts():
    """반올림 키 아래에 dict 가 오면 하위 값도 같은 규칙을 받는다(worst_stress{value, case_key})."""
    folded = ib.round_attrs({"worst_stress": {"value": 12.34, "case_key": "c1"}})
    assert folded["worst_stress"]["value"] == ib.R(12.34, "stress")
    assert folded["worst_stress"]["case_key"] == "c1"


def test_ir_hash_folds_nested_result_overlay_noise(mcad_result, dyna_result, dyna_result_layer):
    """dyna_result 오버레이(part_risk.worst_stress 중첩 dict)도 반올림 규칙을 받는다."""
    base = build([mcad_result, dyna_result, dyna_result_layer])
    noisy = copy.deepcopy(dyna_result_layer)
    changed = False
    for row in noisy["results"]["part_risk"]:
        worst = row.get("worst_stress")
        if isinstance(worst, dict) and isinstance(worst.get("value"), (int, float)):
            worst["value"] = worst["value"] + 0.0001        # 0.1 MPa 규칙 아래의 잡음
            changed = True
    assert changed, "픽스처에 worst_stress{value} 가 없으면 이 시험이 무의미하다"
    assert build([mcad_result, dyna_result, noisy])["ir_hash"] == base["ir_hash"]
