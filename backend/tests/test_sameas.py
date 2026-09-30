# same-as 사다리 7단(§2.6) 단계별 대응·클러스터/conflict·전역 정규 키 ckey(§2.7)·원장 재적용(§2.10)
from __future__ import annotations

import hashlib
import json

import pytest

from app import sameas
from app.common import canonical_json
from app.errors import AppError
from tests.conftest import FIXTURES_DIR

OWNER = "user@example.com"


# ---------------------------------------------------------------- 노드 만들기(소스 어댑터 산출 모양)
def mcad(nid: str, path: str, canon: str, size=(10.0, 5.0, 1.0), volume=50.0,
         material="al6061", geom_fp=None, flags=()) -> dict:
    return {
        "nid": nid, "canon_key": "mcad:" + path, "domain": "mcad", "kind": "part",
        "label": canon.upper(), "local_key": path, "name_norm": canon, "name_norm_canon": canon,
        "geom_fp": geom_fp, "status_flags": list(flags),
        "attrs": {"shape_kind": "solid", "size_sorted": list(size), "volume": volume,
                  "material": material},
    }


def dyna(nid: str, canon: str, size=(10.0, 5.0, 1.0), volume=50.0, elem_class="solid",
         geom_fp=None, material="AL6061", pid="1") -> dict:
    return {
        "nid": nid, "canon_key": f"dyna:e8de64cc:{pid}", "domain": "dyna", "kind": "pid",
        "label": "STACK\\" + canon.upper(), "local_key": pid,
        "name_norm": canon, "name_norm_canon": canon, "geom_fp": geom_fp, "status_flags": [],
        "attrs": {"elem_class": elem_class, "size_sorted": list(size), "volume": volume,
                  "material": {"name": material, "db": None}},
    }


def ecad(nid: str, refdes: str, canon: str | None = None, part_number="cap_x7r") -> dict:
    name = canon or refdes.lower()
    return {
        "nid": nid, "canon_key": "ecad:" + refdes, "domain": "ecad", "kind": "component",
        "label": refdes, "local_key": refdes, "name_norm": name, "name_norm_canon": name,
        "geom_fp": None, "status_flags": [],
        "attrs": {"refdes": refdes, "part_number": part_number, "footprint": "0402", "pin_count": 2},
    }


def bridge_edge(mcad_nid: str, dyna_nid: str, *, stale=False, eid="e:bridge01",
                join_key="path:/x/plate") -> dict:
    """브리지 엣지 — 조인 키는 REST 가용 시 `path:…`, MCP 폴백 시 `file+name:…` 이다(plan §2.5.1).

    attrs 자리는 정본이 못 박은 `attrs.dyna.bridge` 다. 예전 이 헬퍼는 평면(`attrs.join_key`·
    `attrs.bridge_stale`)이었고 소비처도 같은 평면을 읽어 **서로 맞춰져 있었지만 둘 다 정본과 달랐다** —
    브리지를 만드는 코드가 없어 그 어긋남이 드러나지 않았다(항진명제 쌍).
    """
    return {"eid": eid, "kind": "bridge", "kind_family": "bridge", "a": mcad_nid, "b": dyna_nid,
            "domain": "dyna", "status": "auto",
            "attrs": {"dyna": {"bridge": {"join_key": join_key, "stale": stale}}}}


def _one(records: list[dict]) -> dict:
    assert len(records) == 1, records
    return records[0]


# ---------------------------------------------------------------- stable key(§2.6.2 1단계)
def test_stable_key_per_domain():
    assert sameas.stable_key(mcad("m1", "/x/plate", "plate")) == "mcad:/x/plate"
    # dyna 는 pid·sha 가 K파일마다 바뀌므로 canon_key 를 쓰지 않는다.
    node = dyna("d1", "plate")
    assert sameas.stable_key(node) == "plate@solid" != node["canon_key"]
    assert sameas.stable_key(ecad("e1", "C12")) == "C12"
    assert sameas.stable_key({"domain": "dyna", "name_norm_canon": ""}) is None


# ---------------------------------------------------------------- 사다리 단계별 대응(§2.6.2)
def test_ladder_ledger_wins_over_everything_else():
    """1단계 원장은 이름·기하가 전혀 닮지 않아도 잇고, 그 노드는 뒤 단계 후보에서 빠진다."""
    a = [mcad("b1", "/dv1/alpha", "alpha")]
    b = [mcad("t1", "/dv2/zeta", "zeta", (99.0, 88.0, 7.0), 1000.0, material="steel")]
    ledger = {("mcad:/dv1/alpha", "mcad:/dv2/zeta"):
              {"id": "sa-row-1", "status": "confirmed", "decided_by": "u@x", "decided_at": 1756600000}}
    record = _one(sameas.resolve(a, b, [], [], "pair", ledger))
    assert record["method"] == "ledger" and record["score"] == 1.0
    assert record["status"] == "confirmed"
    assert record["ledger_id"] == "sa-row-1" and record["decided_by"] == "u@x"
    assert record["id"].startswith("sa:") and record["scope"] == "pair"
    assert record["evidence"]["ledger"]["a_stable"] == "mcad:/dv1/alpha"


def test_ladder_ledger_rejected_blocks_later_stages():
    """`rejected` 는 레코드로 남아 뒤 단계가 같은 쌍을 다시 제안하지 못하게 한다(§2.6.1)."""
    a = [mcad("b1", "/x/alpha", "alpha", geom_fp="ff00")]
    b = [mcad("t1", "/x/alpha", "alpha", geom_fp="ff00")]     # 원장이 없으면 exact_path 로 이어질 쌍
    ledger = {("mcad:/x/alpha", "mcad:/x/alpha"):
              {"id": "sa-row-2", "status": "rejected", "decided_by": "u@x", "decided_at": 1}}
    record = _one(sameas.resolve(a, b, [], [], "pair", ledger))
    assert (record["method"], record["status"]) == ("ledger", "rejected")


def test_ladder_pid_map_uses_the_bridge_edge():
    m, d = mcad("m1", "/x/plate", "plate"), dyna("d1", "plate")
    record = _one(sameas.resolve([m], [d], [bridge_edge("m1", "d1")], [], "intra", None))
    assert (record["method"], record["score"], record["status"]) == ("pid_map", 1.0, "auto")
    assert record["evidence"]["bridge"] == {"join_key": "path:/x/plate", "stale": False}
    # 소스가 주는 행 id(mesh_key)는 앱 원장에 남기지 않는다 — 재파싱마다 바뀐다(plan §2.5.1).
    assert "mesh_key" not in record["evidence"]["bridge"]


def test_ladder_pid_map_follows_the_declaration_not_the_name():
    """브리지 선언 케이스는 이름·기하가 엇갈려도 선언대로만 잇는다(P2 통과 기준 (2) 정밀도 100%)."""
    parts = [mcad("m1", "/x/alpha", "alpha"), mcad("m2", "/x/beta", "beta"),
             mcad("m3", "/x/gamma", "gamma")]
    pids = [dyna("d1", "beta", pid="1"), dyna("d2", "gamma", pid="2"), dyna("d3", "alpha", pid="3")]
    edges = [bridge_edge("m1", "d1", eid="e:b1"), bridge_edge("m2", "d2", eid="e:b2"),
             bridge_edge("m3", "d3", eid="e:b3")]
    records = sameas.resolve(parts, pids, edges, [], "intra", None)
    assert {(r["a"], r["b"]) for r in records} == {("m1", "d1"), ("m2", "d2"), ("m3", "d3")}
    assert {r["method"] for r in records} == {"pid_map"}


def test_intra_ladder_on_the_golden_ir_matches_mcad_to_dyna():
    """골든 IR 의 mcad 파트 ↔ dyna pid — 이름이 겹쳐도 지문 단계가 1:1 로 가른다(§2.6.2 4단계)."""
    ir = json.loads((FIXTURES_DIR / "rr_ir" / "valid_mcad_dyna.json").read_text(encoding="utf-8"))
    parts = [n for n in ir["nodes"] if n["domain"] == "mcad" and n["kind"] == "part"]
    pids = [n for n in ir["nodes"] if n["domain"] == "dyna"]
    records = sameas.resolve(parts, pids, ir["edges"], [], "intra", None)
    labels = {(next(p["label"] for p in parts if p["nid"] == r["a"]),
               next(p["label"] for p in pids if p["nid"] == r["b"])) for r in records}
    assert labels == {("PLATE_1", "STACK\\PLATE_1"), ("PLATE_2", "STACK\\PLATE_2"),
                      ("BRACKET_L", "STACK\\BRACKET_L")}
    assert {r["method"] for r in records} == {"fingerprint"}
    clusters = sameas.build_clusters(parts + pids, records)
    assert clusters["conflicts"] == []
    assert len(set(clusters["dn"].values())) == 3


def test_ladder_pid_map_skipped_when_the_bridge_is_stale():
    """stale 이면 2단계를 건너뛰고 아래 단계로 내려간다 — 여기서는 4단계 fingerprint 가 받는다."""
    m, d = mcad("m1", "/x/plate", "plate"), dyna("d1", "zzz")
    record = _one(sameas.resolve([m], [d], [bridge_edge("m1", "d1", stale=True)], [], "intra", None))
    assert record["method"] == "fingerprint"


def test_ladder_exact_path_is_pair_scope_and_not_for_dyna():
    """3단계는 canon_key 동일인 mcad 만 탄다. dyna 는 canon_key 에 sha 가 들어 있어 5단계로 내려간다."""
    d_base, d_target = dyna("d1", "beta"), dyna("d2", "beta")
    d_target["canon_key"] = d_base["canon_key"]
    records = sameas.resolve([mcad("b1", "/x/alpha", "alpha"), d_base],
                             [mcad("t1", "/x/alpha", "alpha"), d_target], [], [], "pair", None)
    by_pair = {(r["a"], r["b"]): r for r in records}
    assert by_pair[("b1", "t1")]["method"] == "exact_path"
    assert by_pair[("b1", "t1")]["score"] == 1.0
    assert by_pair[("d1", "d2")]["method"] == "name_norm"


def test_ladder_exact_path_is_not_used_in_intra_scope():
    m1 = mcad("m1", "/x/plate", "plate")
    m2 = mcad("m2", "/x/plate", "plate")
    records = sameas.resolve([m1], [m2], [], [], "intra", None)
    assert all(r["method"] != "exact_path" for r in records)


def test_ladder_fingerprint_same_domain_scores():
    """같은 도메인은 geom_fp 동일 + name_sim ≥0.5 → 0.95 auto, name_sim <0.5 → 0.85 pending."""
    a = [mcad("b1", "/x/alpha", "alpha", geom_fp="ff00")]
    same_name = _one(sameas.resolve(a, [mcad("t1", "/y/alpha", "alpha", geom_fp="ff00")],
                                    [], [], "pair", None))
    assert (same_name["method"], same_name["score"], same_name["status"]) == ("fingerprint", 0.95, "auto")

    renamed = _one(sameas.resolve(a, [mcad("t1", "/y/omega", "omega_zzz", geom_fp="ff00")],
                                  [], [], "pair", None))
    assert (renamed["method"], renamed["score"], renamed["status"]) == ("fingerprint", 0.85, "pending")
    assert renamed["evidence"]["geom_fp"] == "ff00"


def test_ladder_fingerprint_one_to_many_falls_through_to_fuzzy():
    a = [mcad("b1", "/x/alpha", "alpha", geom_fp="ff00")]
    b = [mcad("t1", "/y/a1", "alpha_1", geom_fp="ff00"), mcad("t2", "/y/a2", "alpha_2", geom_fp="ff00")]
    records = sameas.resolve(a, b, [], [], "pair", None)
    assert all(r["method"] != "fingerprint" for r in records)
    assert _one(records)["method"] == "fuzzy"


def test_ladder_fingerprint_mcad_dyna_uses_size_and_volume_tolerance():
    """intra mcad↔dyna 는 size 3축 상대오차 ≤2% AND volume ≤3% 면 0.90, volume 한쪽 null 이면 0.05 감점."""
    m = mcad("m1", "/x/plate", "plate", (10.0, 5.0, 1.0), 50.0)
    close = _one(sameas.resolve([m], [dyna("d1", "zzz", (10.1, 5.05, 1.01), 50.5)], [], [], "intra", None))
    assert (close["method"], close["score"]) == ("fingerprint", 0.90)
    assert close["evidence"]["size_rel_max"] < 0.02 and close["evidence"]["volume_penalty"] == 0.0

    penalized = _one(sameas.resolve([m], [dyna("d1", "zzz", (10.1, 5.05, 1.01), None)], [], [], "intra", None))
    assert (penalized["method"], penalized["score"]) == ("fingerprint", 0.85)
    assert penalized["evidence"]["volume_penalty"] == 0.05

    far = sameas.resolve([m], [dyna("d1", "zzz", (12.0, 5.0, 1.0), 60.0)], [], [], "intra", None)
    assert all(r["method"] != "fingerprint" for r in far)


def test_ladder_name_norm_requires_a_one_to_one_candidate():
    a = [mcad("b1", "/x/p1", "plate")]
    one_to_one = _one(sameas.resolve(a, [mcad("t1", "/y/p1", "plate")], [], [], "pair", None))
    assert (one_to_one["method"], one_to_one["score"], one_to_one["status"]) == ("name_norm", 0.95, "auto")

    ambiguous = sameas.resolve(a, [mcad("t1", "/y/p1", "plate"),
                                   mcad("t2", "/y/p2", "plate", (90.0, 80.0, 7.0), 5000.0)],
                               [], [], "pair", None)
    assert all(r["method"] != "name_norm" for r in ambiguous)


def test_ladder_order_is_fixed_and_a_pair_is_taken_once():
    """세 단계가 모두 맞는 쌍이라도 가장 앞선 단계 하나만 레코드를 만든다(§2.6 순서 고정)."""
    a = [mcad("b1", "/x/alpha", "alpha", geom_fp="ff00")]
    b = [mcad("t1", "/x/alpha", "alpha", geom_fp="ff00")]
    record = _one(sameas.resolve(a, b, [], [], "pair", None))
    assert record["method"] == "exact_path"


def test_ladder_rejects_unknown_scope():
    with pytest.raises(AppError) as excinfo:
        sameas.resolve([], [], [], [], "global", None)
    assert excinfo.value.http_status == 400


def test_ecad_only_uses_ledger_name_norm_and_manual():
    """ecad 는 1차에서 1·5·7 단계만 허용한다(§2.6.4) — 지문·헝가리안을 타지 않는다."""
    component = ecad("e1", "C12", canon="c12_cap")
    part = mcad("m1", "/x/c12_cap", "c12_cap")
    matched = _one(sameas.resolve([component], [part], [], [], "intra", None))
    assert (matched["method"], matched["score"]) == ("name_norm", 0.95)

    # 이름은 같아도 refdes·part_number 토큰이 상대 이름과 겹치지 않으면 5단계를 타지 않는다.
    odd = ecad("e2", "R99", canon="widget", part_number="res")
    assert sameas.resolve([odd], [mcad("m2", "/x/widget", "widget")], [], [], "intra", None) == []

    # 지문이 같아도 ecad 가 끼면 4단계·6단계를 돌리지 않는다.
    fp_component = ecad("e3", "C13", canon="alpha")
    fp_component["geom_fp"] = "ff00"
    assert sameas.resolve([fp_component], [mcad("m3", "/x/beta", "beta_zz", geom_fp="ff00")],
                          [], [], "pair", None) == []


# ---------------------------------------------------------------- fuzzy 점수·배정(§2.6.3)
def test_fuzzy_score_follows_the_weighted_formula():
    a = mcad("b1", "/x/alpha_plate", "alpha_plate", (10.0, 5.0, 1.0), 50.0)
    b = mcad("t1", "/y/alpha_bracket", "alpha_bracket", (10.0, 5.0, 1.0), 50.0)
    parts = sameas.score_pair(a, b)
    expected = (sameas.FUZZY_WEIGHTS["name"] * parts["name_sim"]
                + sameas.FUZZY_WEIGHTS["geom"] * parts["geom_sim"]
                + sameas.FUZZY_WEIGHTS["material"] * parts["material_eq"]
                + sameas.FUZZY_WEIGHTS["neighbor"] * parts["neighbor_sim"])
    assert parts["score"] == pytest.approx(expected, abs=1e-6)
    assert parts["neighbor_sim"] == 0.5           # 양쪽 이웃이 0 이면 0.5(§2.6.3)
    assert parts["geom_sim"] == 1.0 and parts["material_eq"] == 1.0


def test_fuzzy_status_thresholds_and_no_record_below_070():
    # 이미 확정된 이웃을 공유하면 neighbor_sim 이 1.0 이 되어 0.90 을 넘는다(§2.6.3).
    anchor_base, anchor_target = mcad("b0", "/x/anchor", "anchor"), mcad("t0", "/x/anchor", "anchor")
    edges_a = [{"eid": "e:a", "kind": "tied", "kind_family": "iface", "a": "b0", "b": "b1",
                "status": "confirmed", "attrs": {}}]
    edges_b = [{"eid": "e:b", "kind": "tied", "kind_family": "iface", "a": "t0", "b": "t1",
                "status": "confirmed", "attrs": {}}]
    records = sameas.resolve([anchor_base, mcad("b1", "/x/plate_left", "plate_left")],
                             [anchor_target, mcad("t1", "/y/plate_left_2", "plate_left_2")],
                             edges_a, edges_b, "pair", None)
    auto = next(r for r in records if r["method"] == "fuzzy")
    assert auto["score"] >= sameas.AUTO_SCORE and auto["status"] == "auto"
    assert auto["evidence"]["neighbor_sim"] == 1.0
    assert auto["evidence"]["rank_in_row"] == 1 and auto["evidence"]["n_candidates"] == 1

    pending = _one(sameas.resolve([mcad("b1", "/x/housing", "housing")],
                                  [mcad("t1", "/y/housing_rev", "housing_rev")], [], [], "pair", None))
    assert sameas.PENDING_SCORE <= pending["score"] < sameas.AUTO_SCORE
    assert pending["status"] == "pending"

    far = sameas.resolve([mcad("b1", "/x/housing", "housing", (10.0, 5.0, 1.0), 50.0)],
                         [mcad("t1", "/y/screw", "screw", (0.9, 0.9, 8.0), 6.0, material="sus304")],
                         [], [], "pair", None)
    assert far == []


def test_fuzzy_assignment_is_deterministic_under_input_order():
    base = [mcad(f"b{i}", f"/x/p{i}", f"part_{i}", (10.0 + i, 5.0, 1.0), 50.0 + i) for i in range(5)]
    target = [mcad(f"t{i}", f"/y/q{i}", f"part_{i}_rev", (10.0 + i, 5.0, 1.0), 50.0 + i) for i in range(5)]
    first = sameas.resolve(base, target, [], [], "pair", None)
    second = sameas.resolve(list(reversed(base)), list(reversed(target)), [], [], "pair", None)
    assert canonical_json(first) == canonical_json(second)
    assert {(r["a"], r["b"]) for r in first} == {(f"b{i}", f"t{i}") for i in range(5)}


def test_perturbed_names_keep_precision_and_recall():
    """이름 교란 20%(6/30)인 합성 30쌍 — 정밀도 ≥0.95 · 재현율 ≥0.9(P2 통과 기준 (3))."""
    families = ["bracket", "housing", "plate", "shield", "frame"]
    base, target, truth = [], [], {}
    for i in range(30):
        canon = f"{families[i % 5]}_{i:02d}"
        size = (40.0 + i, 20.0 + i * 0.5, 1.0 + i * 0.1)
        volume = size[0] * size[1] * size[2]
        perturbed = f"{canon}_rev" if i % 5 == 0 else canon        # 6/30 = 20%
        b = mcad(f"b:{i:04d}", f"/dv1/{canon}", canon, size, volume)
        t = mcad(f"t:{i:04d}", f"/dv2/{perturbed}", perturbed,
                 tuple(round(x * 1.001, 4) for x in size), volume * 1.001)
        base.append(b)
        target.append(t)
        truth[b["nid"]] = t["nid"]

    records = sameas.resolve(base, target, [], [], "pair", None)
    correct = sum(1 for r in records if truth.get(r["a"]) == r["b"])
    assert records, "대응이 하나도 안 나오면 정밀도·재현율을 잴 수 없다"
    assert correct / len(records) >= 0.95
    assert correct / len(truth) >= 0.9
    methods = {r["method"] for r in records}
    assert methods == {"name_norm", "fuzzy"}      # 교란되지 않은 24쌍은 5단계, 교란된 6쌍은 6단계다


# ---------------------------------------------------------------- 클러스터·conflict·dn(§2.6.4·§2.7.5)
def test_build_clusters_picks_mcad_as_the_representative():
    nodes = [mcad("m1", "/x/plate", "plate"), dyna("d1", "plate"), ecad("e1", "C12", canon="plate")]
    links = [{"a": "m1", "b": "d1", "status": "auto", "score": 0.95},
             {"a": "d1", "b": "e1", "status": "confirmed", "score": 1.0}]
    out = sameas.build_clusters(nodes, links)
    assert out["dn"] == {"m1": "m1", "d1": "m1", "e1": "m1"}
    assert out["conflicts"] == [] and out["warnings"] == []
    assert len(out["clusters"]) == 1 and out["clusters"][0]["members"] == ["d1", "e1", "m1"]


def test_build_clusters_excludes_pending_and_low_score_auto():
    nodes = [mcad("m1", "/x/plate", "plate"), dyna("d1", "plate")]
    for status, score in (("pending", 0.80), ("auto", 0.85), ("rejected", 1.0)):
        out = sameas.build_clusters(nodes, [{"a": "m1", "b": "d1", "status": status, "score": score}])
        assert out["dn"] == {"m1": "m1", "d1": "d1"}, (status, score)


def test_build_clusters_marks_same_domain_conflict():
    nodes = [mcad("m1", "/x/p1", "plate"), mcad("m2", "/x/p2", "plate"), dyna("d1", "plate")]
    links = [{"a": "m1", "b": "d1", "status": "auto", "score": 0.95},
             {"a": "m2", "b": "d1", "status": "auto", "score": 0.95}]
    out = sameas.build_clusters(nodes, links)
    assert out["conflicts"] and sorted(out["conflicts"][0]["members"]) == ["d1", "m1", "m2"]
    assert out["dn"] == {"m1": "m1", "m2": "m2", "d1": "d1"}      # conflict 면 dn 은 자기 nid 다
    warning = _one(out["warnings"])
    assert warning["code"] == "sameas_conflict" and warning["severity"] == "WARNING"
    assert out["clusters"][0]["conflict"] is True and out["clusters"][0]["dn"] is None


# ---------------------------------------------------------------- 전역 정규 키(§2.7.2·§2.7.3)
def test_ckey_inputs_are_project_independent():
    a = mcad("x1", "/proj_a/sub/plate", "plate", (10.0, 5.0, 1.0), 50.0, "al6061")
    b = mcad("x2", "/proj_b/other/plate", "plate", (10.0, 5.0, 1.0), 50.0, "al6061")
    assert sameas.ckey_of_node(a) == sameas.ckey_of_node(b)
    assert sameas.ckey_of_node(a).startswith("ck:") and len(sameas.ckey_of_node(a)) == 15
    # 이름·버킷·재료 중 하나만 달라도 다른 키다.
    assert sameas.ckey_of_node(a) != sameas.ckey_of_node(
        mcad("x3", "/proj_a/sub/plate", "plate", (10.0, 5.0, 1.0), 50.0, "sus304"))


def test_geom_bucket_rounds_size_and_logs_volume():
    assert sameas.geom_bucket([10.0, 5.0, 1.0], 50.0) == "10.0x5.0x1.0@v80"
    assert sameas.geom_bucket([10.24, 5.0, 1.0], None) == "10.0x5.0x1.0@v?"
    assert sameas.geom_bucket([10.26, 5.0, 1.0], 50.0) != sameas.geom_bucket([10.24, 5.0, 1.0], 50.0)
    payload = "plate|10.0x5.0x1.0@v80|al6061"
    assert sameas.compute_ckey("plate", [10.0, 5.0, 1.0], 50.0, "al6061") == \
        "ck:" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def test_material_norm_first_token_per_domain():
    assert sameas.material_norm_of(mcad("m1", "/x/p", "p", material="AL 6061-T6")) == "al"
    assert sameas.material_norm_of(dyna("d1", "p", material="AL6061")) == "al6061"
    assert sameas.material_norm_of(ecad("e1", "C12")) == "cap"
    assert sameas.material_norm_of({"domain": "mcad", "attrs": {}}) == "na"


# ---------------------------------------------------------------- 원장(§2.7.3 · §2.10) — 저장소가 붙는다
def test_assign_ckeys_writes_the_part_key_ledger(risk_store):
    nodes = [mcad("m1", "/x/plate", "plate"), dyna("d1", "plate")]
    links = [{"a": "m1", "b": "d1", "method": "fingerprint", "score": 0.95, "status": "auto"}]
    out = sameas.assign_ckeys(risk_store, nodes, links, owner_sub=OWNER,
                              project_id="p1", snapshot_id="s1")
    ckey = out["ckeys"]["m1"]
    assert out["ckeys"] == {"m1": ckey, "d1": ckey}          # 클러스터 전원이 같은 키를 받는다
    assert out["dn"] == {"m1": "m1", "d1": "m1"}
    row = risk_store.query_one(
        "SELECT ckey, status, merged_into, name_norm_canon, geom_bucket, material_norm,"
        " aliases_json, n_projects, n_snapshots FROM rr_part_keys WHERE ckey=? AND owner_sub=?",
        (ckey, OWNER))
    assert row["status"] == "candidate" and row["merged_into"] is None
    assert (row["name_norm_canon"], row["material_norm"]) == ("plate", "al6061")
    assert {a["domain"] for a in json.loads(row["aliases_json"])} == {"mcad", "dyna"}
    assert (row["n_projects"], row["n_snapshots"]) == (1, 1)

    sameas.assign_ckeys(risk_store, nodes, links, owner_sub=OWNER, project_id="p1", snapshot_id="s2")
    again = risk_store.query_one("SELECT n_projects, n_snapshots FROM rr_part_keys WHERE ckey=?", (ckey,))
    assert (again["n_projects"], again["n_snapshots"]) == (1, 2)

    sameas.assign_ckeys(risk_store, nodes, links, owner_sub=OWNER, project_id="p2", snapshot_id="s3")
    cross = risk_store.query_one("SELECT n_projects, n_snapshots FROM rr_part_keys WHERE ckey=?", (ckey,))
    assert (cross["n_projects"], cross["n_snapshots"]) == (2, 3)


def test_assign_ckeys_gives_conflict_clusters_a_null_key(risk_store):
    nodes = [mcad("m1", "/x/p1", "plate"), mcad("m2", "/x/p2", "plate"), dyna("d1", "plate")]
    links = [{"a": "m1", "b": "d1", "status": "auto", "score": 0.95},
             {"a": "m2", "b": "d1", "status": "auto", "score": 0.95}]
    out = sameas.assign_ckeys(risk_store, nodes, links, owner_sub=OWNER,
                              project_id="p1", snapshot_id="s1")
    assert out["ckeys"] == {"m1": None, "m2": None, "d1": None}
    assert [w["code"] for w in out["warnings"]] == ["sameas_conflict"]
    assert risk_store.query("SELECT ckey FROM rr_part_keys", ()) == []


def test_resolve_ckey_follows_the_merge_chain(risk_store):
    def insert(ckey, status, merged_into=None):
        risk_store.execute(
            "INSERT INTO rr_part_keys (ckey, owner_sub, status, merged_into, name_norm_canon,"
            " geom_bucket, material_norm) VALUES (?,?,?,?,'x','x','x')",
            (ckey, OWNER, status, merged_into))

    insert("ck:a", "merged", "ck:b")
    insert("ck:b", "merged", "ck:c")
    insert("ck:c", "confirmed")
    assert sameas.resolve_ckey(risk_store, "ck:a", OWNER) == "ck:c"
    assert sameas.resolve_ckey(risk_store, "ck:zz", OWNER) == "ck:zz"      # 없는 키는 그대로다

    # 체인은 최대 5단까지만 따라간다(§2.7.3).
    for i in range(8):
        insert(f"ck:chain{i}", "merged", f"ck:chain{i + 1}")
    assert sameas.resolve_ckey(risk_store, "ck:chain0", OWNER) == f"ck:chain{sameas.MERGE_CHAIN_MAX}"


def test_inherit_ckeys_merges_on_same_project_revision(risk_store):
    """두께가 바뀌어 volume 버킷이 옮겨가도 결정론 대응이면 target 이 base 유효 키를 승계한다(§2.7.3)."""
    base = [mcad("b1", "/x/film", "film", (10.0, 5.0, 0.08), 4.0)]
    target = [mcad("t1", "/x/film", "film", (10.0, 5.0, 0.06), 3.0)]
    base_ckey, target_ckey = sameas.ckey_of_node(base[0]), sameas.ckey_of_node(target[0])
    assert base_ckey != target_ckey
    sameas.assign_ckeys(risk_store, base, [], owner_sub=OWNER, project_id="p1", snapshot_id="s1")

    links = [{"a": "b1", "b": "t1", "method": "exact_path", "score": 1.0, "status": "auto"}]
    applied = sameas.inherit_ckeys(risk_store, links, base, target, owner_sub=OWNER,
                                   pair_kind="same_project_revision",
                                   base_snapshot_id="s1", target_snapshot_id="s2")
    assert applied == [{"ckey": target_ckey, "merged_into": base_ckey, "action": "merged",
                        "method": "exact_path", "score": 1.0, "base_snapshot_id": "s1",
                        "target_snapshot_id": "s2", "base_nid": "b1", "target_nid": "t1"}]
    row = risk_store.query_one(
        "SELECT status, merged_into, decided_by, merge_evidence_json FROM rr_part_keys WHERE ckey=?",
        (target_ckey,))
    assert (row["status"], row["merged_into"]) == ("merged", base_ckey)
    assert row["decided_by"] == "code:pair_correspondence"
    assert json.loads(row["merge_evidence_json"])["method"] == "exact_path"
    assert sameas.resolve_ckey(risk_store, target_ckey, OWNER) == base_ckey


def test_inherit_ckeys_ignores_non_deterministic_and_human_rows(risk_store):
    base = [mcad("b1", "/x/film", "film", (10.0, 5.0, 0.08), 4.0)]
    target = [mcad("t1", "/x/film", "film", (10.0, 5.0, 0.06), 3.0)]
    target_ckey = sameas.ckey_of_node(target[0])
    sameas.assign_ckeys(risk_store, base, [], owner_sub=OWNER, project_id="p1", snapshot_id="s1")

    # fuzzy 는 결정론 단계가 아니고 fingerprint 도 0.95 미만이면 승계하지 않는다.
    for method, score in (("fuzzy", 0.99), ("fingerprint", 0.90), ("name_norm", 0.90)):
        assert sameas.inherit_ckeys(
            risk_store, [{"a": "b1", "b": "t1", "method": method, "score": score, "status": "auto"}],
            base, target, owner_sub=OWNER, pair_kind="same_project_revision",
            base_snapshot_id="s1", target_snapshot_id="s2") == []
    assert risk_store.query_one("SELECT ckey FROM rr_part_keys WHERE ckey=?", (target_ckey,)) is None

    # 사람이 confirmed 로 둔 행은 건드리지 않는다.
    risk_store.execute(
        "INSERT INTO rr_part_keys (ckey, owner_sub, status, name_norm_canon, geom_bucket, material_norm)"
        " VALUES (?,?,'confirmed','film','x','al6061')", (target_ckey, OWNER))
    applied = sameas.inherit_ckeys(
        risk_store, [{"a": "b1", "b": "t1", "method": "exact_path", "score": 1.0, "status": "auto"}],
        base, target, owner_sub=OWNER, pair_kind="same_project_revision",
        base_snapshot_id="s1", target_snapshot_id="s2")
    assert applied == [{"ckey": target_ckey, "action": "skipped_human_row"}]
    assert risk_store.query_one("SELECT status FROM rr_part_keys WHERE ckey=?", (target_ckey,))["status"] \
        == "confirmed"


def test_inherit_ckeys_only_proposes_on_cross_project(risk_store):
    base = [mcad("b1", "/x/film", "film", (10.0, 5.0, 0.08), 4.0)]
    target = [mcad("t1", "/y/film", "film", (10.0, 5.0, 0.06), 3.0)]
    base_ckey, target_ckey = sameas.ckey_of_node(base[0]), sameas.ckey_of_node(target[0])
    sameas.assign_ckeys(risk_store, base, [], owner_sub=OWNER, project_id="p1", snapshot_id="s1")
    sameas.assign_ckeys(risk_store, target, [], owner_sub=OWNER, project_id="p9", snapshot_id="s9")

    applied = sameas.inherit_ckeys(
        risk_store, [{"a": "b1", "b": "t1", "method": "name_norm", "score": 0.95, "status": "auto"}],
        base, target, owner_sub=OWNER, pair_kind="cross_project",
        base_snapshot_id="s1", target_snapshot_id="s9")
    assert applied == [{"ckey": target_ckey, "action": "proposed", "ckey_into": base_ckey}]
    row = risk_store.query_one("SELECT status, merged_into, aliases_json FROM rr_part_keys WHERE ckey=?",
                               (target_ckey,))
    assert (row["status"], row["merged_into"]) == ("candidate", None)     # 자동 병합은 없다
    assert json.loads(row["aliases_json"])["merged_candidates"] == \
        [{"ckey_into": base_ckey, "method": "name_norm", "score": 0.95}]
    assert sameas.resolve_ckey(risk_store, target_ckey, OWNER) == target_ckey


# ---------------------------------------------------------------- 사람 확정(§2.6.2 7단계) — 1단계로 흡수
def test_record_decision_confirm_is_absorbed_by_the_ladder(risk_store):
    base, target = mcad("b1", "/dv1/alpha", "alpha"), mcad("t1", "/dv2/zeta", "zeta",
                                                           (99.0, 88.0, 7.0), 1000.0, "steel")
    out = sameas.record_decision(
        risk_store,
        {"decision": "confirm", "scope": "pair", "a": sameas.stable_key(base),
         "b": sameas.stable_key(target), "pair_key": "p1|p2"},
        owner_sub=OWNER, decided_by="reviewer@example.com")
    assert out["table"] == "rr_sameas" and out["status"] == "confirmed"

    ledger = sameas.load_ledger(risk_store, "pair", "p1|p2", OWNER)
    assert set(ledger) == {("mcad:/dv1/alpha", "mcad:/dv2/zeta")}
    record = _one(sameas.resolve([base], [target], [], [], "pair", ledger))
    assert (record["method"], record["status"]) == ("ledger", "confirmed")
    assert record["decided_by"] == "reviewer@example.com"

    # 같은 쌍을 reject 로 바꾸면 행이 덮인다(UNIQUE(scope, pair_key, a_stable, b_stable)).
    sameas.record_decision(
        risk_store,
        {"decision": "reject", "scope": "pair", "a": sameas.stable_key(target),
         "b": sameas.stable_key(base), "pair_key": "p1|p2"}, owner_sub=OWNER)
    rows = risk_store.query("SELECT status FROM rr_sameas WHERE pair_key=?", ("p1|p2",))
    assert [r["status"] for r in rows] == ["rejected"]


def test_record_decision_ckey_operations(risk_store):
    node = mcad("m1", "/x/plate", "plate")
    out = sameas.assign_ckeys(risk_store, [node], [], owner_sub=OWNER,
                              project_id="p1", snapshot_id="s1")
    ckey = out["ckeys"]["m1"]
    other = mcad("m2", "/x/plate2", "plate_2")
    other_ckey = sameas.assign_ckeys(risk_store, [other], [], owner_sub=OWNER,
                                     project_id="p1", snapshot_id="s1")["ckeys"]["m2"]

    sameas.record_decision(risk_store, {"decision": "rename_key", "ckey": ckey,
                                        "display_name": "보호 필름"}, owner_sub=OWNER)
    sameas.record_decision(risk_store, {"decision": "confirm_key", "ckey": ckey}, owner_sub=OWNER)
    row = risk_store.query_one("SELECT display_name, status FROM rr_part_keys WHERE ckey=?", (ckey,))
    assert (row["display_name"], row["status"]) == ("보호 필름", "confirmed")

    sameas.record_decision(risk_store, {"decision": "merge_key", "ckey_from": other_ckey,
                                        "ckey_into": ckey}, owner_sub=OWNER)
    assert sameas.resolve_ckey(risk_store, other_ckey, OWNER) == ckey

    sameas.record_decision(risk_store, {"decision": "unmerge_key", "ckey": other_ckey}, owner_sub=OWNER)
    back = risk_store.query_one("SELECT status, merged_into FROM rr_part_keys WHERE ckey=?", (other_ckey,))
    assert (back["status"], back["merged_into"]) == ("confirmed", None)
    assert sameas.resolve_ckey(risk_store, other_ckey, OWNER) == other_ckey


def test_record_decision_validates_the_vocabulary(risk_store):
    with pytest.raises(AppError) as bad_decision:
        sameas.record_decision(risk_store, {"decision": "maybe"}, owner_sub=OWNER)
    assert bad_decision.value.http_status == 400
    with pytest.raises(AppError):
        sameas.record_decision(risk_store, {"decision": "confirm", "scope": "everything",
                                            "a": "x", "b": "y"}, owner_sub=OWNER)
    with pytest.raises(AppError):
        sameas.record_decision(risk_store, {"decision": "confirm", "scope": "pair", "a": "x", "b": "y"},
                               owner_sub=OWNER)          # pair_key 없음
    with pytest.raises(AppError) as missing:
        sameas.record_decision(risk_store, {"decision": "merge_key", "ckey_from": "ck:none",
                                            "ckey_into": "ck:x"}, owner_sub=OWNER)
    assert missing.value.http_status == 404


def test_review_rows_surface_pending_conflict_and_fuzzy():
    nodes_a = [mcad("m1", "/x/p1", "plate"), mcad("m2", "/x/p2", "plate")]
    nodes_b = [dyna("d1", "plate"), dyna("d2", "housing", pid="2")]
    links = [
        {"id": "sa:1", "scope": "intra", "a": "m1", "b": "d1", "method": "exact_path",
         "score": 1.0, "status": "auto", "evidence": {}},
        {"id": "sa:2", "scope": "intra", "a": "m2", "b": "d2", "method": "fuzzy",
         "score": 0.93, "status": "auto", "evidence": {"rank_in_row": 1}},
        {"id": "sa:3", "scope": "intra", "a": "m1", "b": "d2", "method": "fuzzy",
         "score": 0.80, "status": "pending", "evidence": {}},
    ]
    rows = sameas.review_rows(links, nodes_a, nodes_b, conflicts=[{"members": ["m1", "d1"]}])
    assert [r["id"] for r in rows] == ["sa:1", "sa:3", "sa:2"]      # (a, b) 정렬
    assert {r["id"] for r in rows if r["conflict"]} == {"sa:1", "sa:3"}
    pending = next(r for r in rows if r["id"] == "sa:3")
    assert pending["a_stable"] == "mcad:/x/p1" and pending["b_stable"] == "housing@solid"
    assert pending["a_domain"] == "mcad" and pending["b_domain"] == "dyna"


def test_record_iface_aliases_keys_by_sorted_ckey_pair(risk_store):
    nodes = [mcad("m1", "/x/plate", "plate"), mcad("m2", "/x/bracket", "bracket")]
    edges = [{"eid": "e:1", "kind": "tied", "kind_family": "iface", "a": "m1", "b": "m2",
              "status": "confirmed", "attrs": {}},
             {"eid": "e:2", "kind": "part_of", "kind_family": "hier", "a": "m1", "b": "m2",
              "status": "auto", "attrs": {}}]
    ckeys = {"m1": sameas.ckey_of_node(nodes[0]), "m2": sameas.ckey_of_node(nodes[1])}
    touched = sameas.record_iface_aliases(risk_store, nodes, edges, ckeys, owner_sub=OWNER,
                                          project_id="p1", snapshot_id="s1")
    assert touched == 1                                  # 계면 엣지만 사전에 오른다(hier 는 제외)
    row = risk_store.query_one("SELECT alias_key, canonical_a, canonical_b, aliases_json,"
                               " source FROM rr_iface_alias", ())
    first, second = sorted(ckeys.values())
    assert row["alias_key"] == f"{first}|{second}"
    assert (row["canonical_a"], row["canonical_b"], row["source"]) == (first, second, "auto")
    assert json.loads(row["aliases_json"])[0]["project_id"] == "p1"

    # 같은 스냅샷을 다시 넣어도 별칭은 늘지 않는다.
    assert sameas.record_iface_aliases(risk_store, nodes, edges, ckeys, owner_sub=OWNER,
                                       project_id="p1", snapshot_id="s1") == 0


# ---------------------------------------------------------------- 키 일치율(plan §4.9 · §0.9 P2-11)
MATCH_RATE_MIN = 0.95

# 이름 규칙만 다른 두 과제의 같은 부품 목록. (A 이름, B 이름, auto_named 여부).
NAME_VARIANTS: list[tuple[str, str, bool]] = [
    ("plate_1", "plate_1", False),          # 그대로
    ("plate_2", "plate_2#3", False),        # 인스턴스 순번 접미
    ("bracket_l", "m22_bracket_l", False),  # 과제 코드 접두
    ("cover", "cover_rev", False),          # 불용어
    ("housing", "housing", False),
    ("pcb_top", "board_top", False),        # 동의어
    ("solid", "solid_7", True),             # 자동명(auto_named 접미)
    ("frame", "frame", False),
    ("gasket", "gasket", False),
    ("shield", "shield", False),
]


def _variant_nodes(which: int) -> list[dict]:
    """같은 부품 10개를 두 이름 규칙으로 만든 노드 목록(형상·재료는 같다)."""
    from app import ir_builder as ib

    nodes = []
    for index, (left, right, auto) in enumerate(NAME_VARIANTS):
        raw = left if which == 0 else right
        canon = ib.name_norm_canon(ib.name_norm(raw, auto_named=auto), project_codes=["M22"])
        nodes.append(mcad(f"n{index}", f"/x/{raw}", canon, (10.0, 5.0, 1.0), 50.0))
    return nodes


def test_ckey_and_subject_key_match_rate_across_two_naming_conventions():
    """이름·인스턴스 접미·자동명만 다른 두 과제에서 ckey 일치율이 0.95 이상이다(plan §4.9)."""
    left, right = _variant_nodes(0), _variant_nodes(1)
    ckeys_left = [sameas.ckey_of_node(n) for n in left]
    ckeys_right = [sameas.ckey_of_node(n) for n in right]
    hits = sum(1 for a, b in zip(ckeys_left, ckeys_right) if a == b)
    rate = hits / len(NAME_VARIANTS)
    assert rate >= MATCH_RATE_MIN, [
        (v[0], v[1]) for v, a, b in zip(NAME_VARIANTS, ckeys_left, ckeys_right) if a != b]

    # subject_key(계면 쌍)는 ckey 쌍의 정렬 결합이라 같은 비율로 따라온다.
    pairs_left = ["|".join(sorted(p)) for p in zip(ckeys_left, ckeys_left[1:])]
    pairs_right = ["|".join(sorted(p)) for p in zip(ckeys_right, ckeys_right[1:])]
    subject_rate = sum(1 for a, b in zip(pairs_left, pairs_right) if a == b) / len(pairs_left)
    assert subject_rate >= MATCH_RATE_MIN


def test_revision_inheritance_keeps_subject_and_cluster_keys(risk_store):
    """같은 과제 DV1→DV2 에서 자동 승계 원장을 거친 뒤 subject_key 일치율 ≥0.95 이고 cluster_key 가 같다."""
    from app import narrative

    # 두께만 바뀐 두 리비전 — 형상 버킷이 옮겨가 ckey 는 달라진다.
    base = [mcad("b1", "/x/film", "film", (10.0, 5.0, 0.08), 4.0),
            mcad("b2", "/x/plate", "plate", (10.0, 5.0, 1.0), 50.0)]
    target = [mcad("t1", "/x/film", "film", (10.0, 5.0, 0.06), 3.0),
              mcad("t2", "/x/plate", "plate", (10.0, 5.0, 1.0), 50.0)]
    sameas.assign_ckeys(risk_store, base, [], owner_sub=OWNER, project_id="p1", snapshot_id="s1")
    links = [{"a": "b1", "b": "t1", "method": "exact_path", "score": 1.0, "status": "auto"},
             {"a": "b2", "b": "t2", "method": "exact_path", "score": 1.0, "status": "auto"}]
    applied = sameas.inherit_ckeys(risk_store, links, base, target, owner_sub=OWNER,
                                   pair_kind="same_project_revision",
                                   base_snapshot_id="s1", target_snapshot_id="s2")
    assert len([a for a in applied if a.get("action") == "merged"]) >= 1

    resolved_base = [sameas.resolve_ckey(risk_store, sameas.ckey_of_node(n), OWNER) for n in base]
    resolved_target = [sameas.resolve_ckey(risk_store, sameas.ckey_of_node(n), OWNER) for n in target]
    rate = sum(1 for a, b in zip(resolved_base, resolved_target) if a == b) / len(base)
    assert rate >= MATCH_RATE_MIN

    subject_base = "|".join(sorted(resolved_base))
    subject_target = "|".join(sorted(resolved_target))
    assert subject_base == subject_target
    # 같은 subject_key·메커니즘이면 cluster_key 도 리비전을 넘어 같다(§4.3.2).
    assert narrative.cluster_key_of("interface", "clearance", subject_base, "dimension") == \
        narrative.cluster_key_of("interface", "clearance", subject_target, "dimension")
