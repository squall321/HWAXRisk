# 거르기 코드 신호(M3 C3-5) 시험 — 변경 → 메커니즘 표의 닫힘·결정론·모름·역할·승인 문·15영역, 입력은 생산자 경로다
"""단위는 생산자 그대로다 — 합성 대본(syn3·syn40·syn150·무작위 대본)과 `tests/fixtures/diff_pairs` 6쌍을 실제 `compute_diff` →
`units` 로 돌린다. 표가 풀어야 하는 코드의 독립 오라클은 diff 스키마(`rr_diff.v1.json`)의 열거와 `diff.PARAM_RULES` 다 — 표를
읽어 기대를 만들지 않는다.

택소노미 1.2(메커니즘 52 · 배정표 `mech-owners.v1.json`)는 형제 꾸러미 S3-2 가 낸 진짜를 쓴다(`tax` = `app.taxonomy`). 배정표가
draft 인 동안 '승인 문이 열렸을 때' 는 승인 칸만 바꿔 보이는 `GateOf` 로 본다.
"""
from __future__ import annotations

import copy
import json
import random
import re

import pytest

from app import devseed, diff as diff_module, relevance, taxonomy, units
from app.risk_store import RiskStore
from tests import factories
from tests.conftest import BACKEND_DIR, FIXTURES_DIR
from tests.synth import scripts

SCHEMA = json.loads((BACKEND_DIR / "app" / "schemas" / "rr_diff.v1.json").read_text(encoding="utf-8"))["definitions"]
PAIRS = ("pair_add", "pair_kind", "pair_mat", "pair_move", "pair_remove", "pair_thick")


# ---------------------------------------------------------------- 택소노미 1.2(진짜) · 승인 문만 연 사본
class GateOf:
    """`app.taxonomy` 그대로에 배정표 승인 칸만 바꿔 보인다 — 배정표가 draft 인 동안 '문이 열렸을 때' 의 코드 신호를 본다(표·영역·판은
    진짜다). 사용자가 배정표를 승인한 뒤에도 같은 시험이 돈다."""

    def __init__(self, review_status: str) -> None:
        self.review_status = review_status

    def domains_for(self, codes):
        return taxonomy.domains_for(codes)

    def mech_owners_meta(self):
        return {**taxonomy.mech_owners_meta(), "review_status": self.review_status,
                "approved": self.review_status == relevance.APPROVED}

    def load_taxonomy(self):
        return taxonomy.load_taxonomy()


@pytest.fixture(scope="module")
def tax():
    return taxonomy


@pytest.fixture(scope="module")
def approved_tax():
    return GateOf("approved")


@pytest.fixture(scope="module")
def routing():
    return relevance.load_routing()


def _active_mechanisms(tax) -> set[str]:
    return {m["code"] for m in tax.load_taxonomy()["axes"]["mechanism"] if m.get("status", "active") == "active"}


# ---------------------------------------------------------------- 생산자 입력
def _store(tmp_path_factory, name: str) -> RiskStore:
    store = RiskStore(tmp_path_factory.mktemp(name) / "risk_review.db")
    store.open()
    store.migrate()
    return store


class Case:
    """생산자가 만든 diff 하나와 그 항목·단위."""

    def __init__(self, name, diff_obj, view, store=None, target=None):
        self.name, self.diff, self.view, self.store, self.target = name, diff_obj, view, store, target
        self.items = units.collect_diff_items(diff_obj)
        self.built = units.build_diff_units(diff_obj, view)


def _synth_case(tmp_path_factory, name, size, **kwargs) -> Case:
    store = _store(tmp_path_factory, name)
    target = factories.make_diff_target(store, size, open_target=False, **kwargs)
    return Case(name, target.diff, units._ir_view(store, target.base_snapshot_id, target.target_snapshot_id),
                store=store, target=target)


def _pair(name: str) -> dict:
    return json.loads((FIXTURES_DIR / "diff_pairs" / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    cases = {size: _synth_case(tmp_path_factory, f"syn{size}", size) for size in scripts.SIZES}
    yield cases
    for case in cases.values():
        case.store.close()


@pytest.fixture(scope="module")
def producer_cases(tmp_path_factory, synth):
    """표가 풀어야 할 생산자 입력 전부 — 크기별 대본 · 무작위 대본 다섯 · 짝 있는 부품의 판 두께(cross.bridge_stale — 크기별
    대본에 없는 운영 코드, devseed.PRODUCER_MISREADS) · diff_pairs 6쌍."""
    extra = [_synth_case(tmp_path_factory, f"rand{seed}", 40, seed=seed, script=devseed.random_script(80, seed))
             for seed in range(5)]
    extra.append(_synth_case(tmp_path_factory, "bridge", 3, check=False, script=[("cross.bridge_stale", {})]))
    pairs = [Case(name, diff_module.compute_diff(_pair("base"), _pair(name)), units.view_of(_pair("base"), _pair(name)))
             for name in PAIRS]
    yield [*synth.values(), *extra, *pairs]
    for case in extra:
        case.store.close()


def _signal(unit, tax, routing, *, approved=True):
    return relevance.code_signal(unit["lines"], [p["name"] for p in unit["parts"]], approved=approved, routing=routing,
                                 tax=tax)


# ---------------------------------------------------------------- 표의 모양
def test_the_routing_asset_is_a_draft_with_its_vocabulary(tax, routing):
    assert routing["version"] == "change-routing-1.0"
    if routing["review_status"] == relevance.APPROVED:           # 사용자가 훑고 승인한 판 — 누가 언제 승인했는지가 적혔다
        assert routing["reviewed_by"] and routing["reviewed_at"]
    else:
        assert routing["review_status"] == "draft"             # 사용자가 훑기 전이다(D-35) — 승인 문이 닫혀 있다
    matches = [entry["match"] for entry in routing["codes"]]
    assert len(matches) == len(set(matches))
    for match in matches:
        assert "*" not in match[:-1], match                    # 끝의 * 접두만 쓴다
    assert set(routing["change_kinds"]) == {k["code"] for k in tax.load_taxonomy()["axes"]["change_kind"]}
    assert set(routing["roles"]) == relevance.ROLE_NAMES        # 정규명 10종이 다 있다(빠진 역할은 영역을 더하지 못한다)
    domains = set(relevance.domain_codes(tax))
    assert len(domains) == 15
    assert {d for ds in routing["roles"].values() for d in ds} <= domains
    assert set(routing["always"]) <= domains


def test_every_mechanism_in_the_table_is_an_active_taxonomy_code(tax, routing):
    used = {m for entry in routing["codes"] for m in entry["mechanisms"]}
    used |= {m for ms in routing["change_kinds"].values() if ms for m in ms}
    assert used - _active_mechanisms(tax) == set()
    assert len(_active_mechanisms(tax)) == 52


def test_every_producer_code_resolves_by_code_alone(producer_cases, routing):
    """저장된 단위 줄에는 change_kind 가 없다 — 생산자가 내는 코드는 `codes` 만으로 풀려야 한다(모르는 버킷만 예외)."""
    seen: set[str] = set()
    for case in producer_cases:
        for item in case.items:
            seen.add(item["code"])
            mechs = relevance.code_mechanisms(item["code"], routing)
            if item["bucket_unknown"]:
                assert mechs is None, (case.name, item["code"])
            else:
                assert mechs is not None, (case.name, item["code"])
            assert item["change_kind"] in routing["change_kinds"], (case.name, item["change_kind"])
        for unit in case.built["units"]:
            for line in unit["lines"]:
                assert relevance.line_mechanisms(line, routing) is not None or line["bucket_unknown"], line["code"]
    assert {"cross.bridge_stale", "mesh.density_changed", "param.material.name", "edge.hier.added"} <= seen


def _schema_codes() -> set[str]:
    """diff 스키마와 생산자 상수가 정하는 코드 공간 — 표를 읽지 않고 센다."""
    events = set(SCHEMA["event"]["properties"]["code"]["enum"])
    nodes = {f"node.{op}" for op in SCHEMA["node_change"]["properties"]["op"]["enum"]}
    edges = {f"edge.{family}.{op}" for family in SCHEMA["edge_change"]["properties"]["kind_family"]["enum"]
             for op in SCHEMA["edge_change"]["properties"]["op"]["enum"]}
    params = {f"param.{attr}" for attr in diff_module.PARAM_RULES}
    params |= {f"param.{m}" for m in SCHEMA["result_item"]["properties"]["metric"]["enum"]}
    params |= {f"param.material.{f}" for f in SCHEMA["material_item"]["properties"]["field"]["enum"]}
    return events | nodes | edges | params | {"param.dim", "param.rollup", "scope.changed"}


def test_every_schema_code_resolves_and_unknown_buckets_do_not(routing):
    codes = _schema_codes()
    assert len(SCHEMA["event"]["properties"]["code"]["enum"]) == 39
    assert [c for c in sorted(codes) if relevance.code_mechanisms(c, routing) is None] == []
    # 모르는 버킷(`<layer>.<rest>`)과 모르는 코드는 접두에 삼켜지지 않는다 — 그 단위는 '모름' 이다.
    for code in ("structural.mystery", "parametric.new_bucket", "semantic.events_v2", "part.teleported", "param.qux", ""):
        assert relevance.code_mechanisms(code, routing) is None, code
    # 재질 칸은 접두로 받는다 — 생산자가 새 재질 칸을 내도 재질 교체로 본다.
    assert relevance.code_mechanisms("param.material.grade", routing) == relevance.code_mechanisms("part.material_changed",
                                                                                                     routing)


def test_the_longest_prefix_wins_and_an_exact_match_beats_any_prefix():
    table = {"codes": [{"match": "param.*", "mechanisms": ["mechanical.mass"]},
                       {"match": "param.material.*", "mechanisms": ["material.property_uncertain"]},
                       {"match": "param.material.E", "mechanisms": ["mechanical.bending"]}]}
    assert relevance.code_mechanisms("param.material.grade", table) == ("material.property_uncertain",)
    assert relevance.code_mechanisms("param.volume", table) == ("mechanical.mass",)
    assert relevance.code_mechanisms("param.material.E", table) == ("mechanical.bending",)
    assert relevance.code_mechanisms("parametric.x", table) is None


def test_the_change_kind_is_a_net_only_when_the_line_carries_it(routing):
    assert relevance.line_mechanisms({"code": "part.teleported"}, routing) is None
    assert relevance.line_mechanisms({"code": "part.teleported", "change_kind": "dimension"}, routing) == tuple(
        routing["change_kinds"]["dimension"])
    for kind in ("none", "consistency", "not_a_kind"):
        assert relevance.line_mechanisms({"code": "part.teleported", "change_kind": kind}, routing) is None, kind
    assert relevance.line_mechanisms({"code": "part.moved", "change_kind": "none"}, routing) == tuple(
        relevance.code_mechanisms("part.moved", routing))       # 코드가 먼저다


def test_all_fifteen_domains_are_reached_by_the_two_tables(tax, routing):
    """메커니즘 → 영역 배정표와 이 표를 합친 결과로 15영역이 다 닿는다 — 닿지 않는 영역은 코드 신호가 늘 '무관' 이라 훑기 하나로
    걸러진다(두 신호 규칙이 무너진다). 역할 표 없이 메커니즘만으로도 다 닿는다."""
    reached: set[str] = set()
    for entry in routing["codes"]:
        for mech in entry["mechanisms"]:
            reached |= set(tax.domains_for([mech]))
    assert reached == set(relevance.domain_codes(tax))


def test_routing_rev_names_all_three_tables(tax, routing):
    assert relevance.routing_rev(routing=routing, tax=tax) == "change-routing-1.0|mech-owners-1.0|tax-1.2"


# ---------------------------------------------------------------- 코드 신호
def _reviewable(case):
    return [u for u in case.built["units"] if u["reviewable"]]


def test_the_same_unit_gives_the_same_signal_in_any_line_order(synth, approved_tax, routing):
    for case in (synth[40], synth[150]):
        for unit in _reviewable(case):
            expected = _signal(unit, approved_tax, routing)
            for seed in range(3):
                rng = random.Random(seed)
                lines, names = list(unit["lines"]), [p["name"] for p in unit["parts"]]
                rng.shuffle(lines)
                rng.shuffle(names)
                got = relevance.code_signal(lines, names, approved=True, routing=routing, tax=approved_tax)
                assert got == expected, (case.name, unit["unit_id"], seed)


def test_a_real_unit_has_related_and_unrelated_domains(synth, approved_tax, routing):
    verdicts = {v["verdict"] for case in synth.values() for unit in _reviewable(case)
                for v in _signal(unit, approved_tax, routing).values()}
    assert verdicts == {"related", "unrelated"}                # 생산자 코드는 다 풀린다 — 모름이 없다


def test_one_unknown_code_makes_every_unrelated_domain_unknown(synth, approved_tax, routing):
    unit = _reviewable(synth[40])[0]
    before = _signal(unit, approved_tax, routing)
    lines = [*unit["lines"], {"code": "semantic.brand_new_event"}]
    after = relevance.code_signal(lines, [p["name"] for p in unit["parts"]], approved=True, routing=routing, tax=approved_tax)
    assert [d for d, v in before.items() if v["verdict"] == "unrelated"]
    for domain, signal in after.items():
        if before[domain]["verdict"] == "related":
            assert signal["verdict"] == "related", domain
        else:
            assert (signal["verdict"], signal["reason"]) == ("unknown", "unmapped"), domain
        assert signal["unmapped"] == ["semantic.brand_new_event"]


def test_a_mechanism_without_an_owner_row_is_unknown(approved_tax):
    routing = {"codes": [{"match": "part.moved", "mechanisms": ["optical.not_yet_in_the_table"]}], "change_kinds": {},
               "roles": {}, "always": []}
    out = relevance.code_signal([{"code": "part.moved"}], [], approved=True, routing=routing, tax=approved_tax)
    assert {v["verdict"] for v in out.values()} == {"unknown"}
    assert out["mech"]["unmapped"] == ["mech:optical.not_yet_in_the_table"]


def test_only_non_design_lines_are_unrelated_everywhere(approved_tax, routing):
    out = relevance.code_signal([{"code": "mesh.density_changed"}, {"code": "param.n_elems"}], ["SPACER_DAMIDA"],
                                approved=True, routing=routing, tax=approved_tax)
    assert {v["verdict"] for v in out.values()} == {"unrelated"}


def test_roles_only_add_domains_and_unknown_names_add_nothing(approved_tax, routing):
    lines = [{"code": "param.fs"}]                             # 마찰 계수 — 메커니즘으로는 sh 에 닿지 않는다
    base = relevance.code_signal(lines, ["DAMPER_ZEPEDA"], approved=True, routing=routing, tax=approved_tax)
    assert {v["verdict"] for v in base.values()} == {"related", "unrelated"}
    shielded = relevance.code_signal(lines, ["DAMPER_ZEPEDA", "SUB_EMI_CAN_02"], approved=True, routing=routing,
                                     tax=approved_tax)
    for domain in routing["roles"]["shield_can"]:
        assert shielded[domain]["verdict"] == "related" and shielded[domain]["via"]["role"] == ["shield_can"], domain
    for domain, signal in shielded.items():
        if base[domain]["verdict"] == "related":
            assert signal["verdict"] == "related"
    assert relevance.part_roles(["강화유리 WINDOW", "HOOK_LATCH", "GIMBAL_XYZ", ""]) == []


@pytest.mark.parametrize(("name", "roles"), [
    ("MAIN_BOARD_ASSY", ["pcb"]), ("PBA_SUB", ["pcb"]), ("rear_cover_1_5t", ["housing"]), ("BATT_CELL", ["battery"]),
    ("OLED_PANEL", ["display"]), ("EMI_CAN_AP", ["shield_can"]), ("SHIELD_CAN", ["shield_can"]), ("FPC_LCD", ["display", "fpcb"]),
    ("BRKT_CAM#3", ["bracket"]), ("PSA_TAPE", ["tape"]), ("SCR_M1.4", ["screw"]), ("CHASSIS", ["frame"]),
    ("frame", ["frame"]), ("SPACER_DAMIDA", [])])
def test_part_roles_read_canonical_tokens_anywhere_in_the_name(name, roles):
    assert relevance.part_roles([name]) == roles


def test_the_gate_keeps_every_domain_unknown_until_both_tables_are_approved(synth, routing):
    """승인 문(#40) — 배정표·이 표 가운데 하나라도 approved 가 아니면 코드 신호는 전 영역 '모름' 이다. 승인 칸 하나만 고친 판이
    문을 연다."""
    unit = _reviewable(synth[40])[0]
    approved_routing = dict(copy.deepcopy(routing), review_status="approved")
    draft_routing = dict(copy.deepcopy(routing), review_status="draft")
    for owners, table, opened in ((GateOf("draft"), draft_routing, False), (GateOf("approved"), draft_routing, False),
                                  (GateOf("draft"), approved_routing, False),
                                  (GateOf("approved"), approved_routing, True)):
        assert relevance.routing_approved(routing=table, tax=owners) is opened
        out = _signal(unit, owners, table, approved=relevance.routing_approved(routing=table, tax=owners))
        if opened:
            assert {v["verdict"] for v in out.values()} == {"related", "unrelated"}
        else:
            assert {(v["verdict"], v["reason"]) for v in out.values()} == {("unknown", "not_approved")}
    # 승인 칸 말고는 같은 표다 — 한 칸만 고친 커밋이 거르기를 연다.
    assert {k: v for k, v in approved_routing.items() if k != "review_status"} == {
        k: v for k, v in draft_routing.items() if k != "review_status"}


# ---------------------------------------------------------------- XU3 · XU4 · XU5(M2 #14 가 M3 로 넘긴 단위 계약 — #56)
def _dn_index(case) -> dict[str, set[str]]:
    """부품 이름 → 그 부품의 dn(대응한 짝은 base 쪽 dn — units 와 같은 규칙)."""
    nodes = units._Nodes(case.diff, case.view)
    out: dict[str, set[str]] = {}
    for side in ("base", "target"):
        for node in case.view[side]["nodes"]:
            if node.get("label"):
                out.setdefault(str(node["label"]), set()).add(nodes.dn_of[str(node["nid"])])
    return out


def _record_dns(record, names) -> set[str]:
    out: set[str] = set()
    for subject in record.subjects:
        if subject.startswith(("dim:", "contact#", "asm:")):
            out.add(subject.casefold())
        else:
            out |= {dn.casefold() for dn in names.get(subject, ())}
    return out


def _anchors(item) -> set[str]:
    return {str(a).casefold() for a in item["anchors_raw"] if a}


@pytest.mark.parametrize("size", (40, 150))
def test_xu3_script_flags_land_in_the_unit_kind_they_name(synth, size):
    """대본의 깃발과 단위 종류가 맞는다 — 경계 계면은 경계 단위, 부품 키 없는 이벤트는 전역 단위(롤업은 그 조립 단위의 묶음에
    탈 수 있다 — units W2-01), 설계 무관·제외 등급은 제외 단위, 단서 등급(null_one_side 등)은 검토 단위 안의 단서 줄, 임계 밑은
    어느 단위에도 없다."""
    case = synth[size]
    names = _dn_index(case)
    owner = {ref: unit for unit in case.built["units"] for ref in unit["cids"]}
    line_of = {(unit["unit_id"], line["ref"]): line for unit in case.built["units"] for line in unit["lines"]}
    checked: dict[str, int] = {}
    for record in case.target.manifest:
        dns = _record_dns(record, names)
        events = [i for i in case.items if i["layer"] == "semantic" and i["code"] in record.expect_codes
                  and _anchors(i) and _anchors(i) <= dns]
        reasons = [f.split(":", 1)[1] for f in record.flags if f.startswith("excluded:")]
        if "boundary" in record.flags:
            assert events and {owner[i["ref"]]["kind"] for i in events} == {"boundary"}, record
            checked["boundary"] = checked.get("boundary", 0) + 1
        if "design_irrelevant" in record.flags:
            assert events and {owner[i["ref"]]["kind"] for i in events} == {"excluded"}, record
            assert {line_of[(owner[i["ref"]]["unit_id"], i["ref"])]["klass"] for i in events} == {"non_design"}
            checked["design_irrelevant"] = checked.get("design_irrelevant", 0) + 1
        if "no_ckey" in record.flags:
            # 깃발은 부품 키 없는 이벤트의 것이다 — 명명 치수 연산은 그 부품의 두께 이벤트(부품 키 있음)도 함께 낸다.
            keyless = [i for i in events if not any(a.startswith("p:") for a in _anchors(i))]
            kinds = {owner[i["ref"]]["kind"] for i in keyless}
            events = keyless
            assert events and kinds <= ({"global", "bundle"} if "derived" in record.flags else {"global"}), (record, kinds)
            checked["no_ckey"] = checked.get("no_ckey", 0) + 1
        for reason in reasons:                                 # 이벤트가 없는 변화 — 대본이 겨냥한 원자료를 본다
            mine = [i for i in case.items if _anchors(i) & dns and (i.get("flag") == reason or i.get("excluded_reason") == reason
                                                                   or i.get("nd_reason") == reason)]
            if reason == "noise":
                noise = [d for d in (case.diff["parametric"].get("node_params") or ())
                         if str(d.get("dn") or "").casefold() in dns and d.get("flag") == "noise"]
                assert noise and not [d for d in noise if d["cid"] in owner], record
            elif reason in units.EXCLUDED_POLICY["caveat"]:
                assert mine and {owner[i["ref"]]["reviewable"] for i in mine} == {True}, record
                assert {line_of[(owner[i["ref"]]["unit_id"], i["ref"])]["klass"] for i in mine} == {"caveat"}, record
            else:
                assert mine and {owner[i["ref"]]["kind"] for i in mine} == {"excluded"}, record
            checked[f"excluded:{reason}"] = checked.get(f"excluded:{reason}", 0) + 1
    assert {"boundary", "no_ckey"} <= set(checked), checked
    if size == 150:
        assert {"design_irrelevant", "excluded:noise", "excluded:null_one_side", "excluded:status_changed"} <= set(checked)
    # 단서 등급은 어디서 왔든 검토 단위 안에 단서 줄로 남는다(사유가 붙는다).
    caveats = [i for i in case.items if i["klass"] == "caveat"]
    assert caveats
    for item in caveats:
        holder = owner[item["ref"]]
        assert holder["reviewable"] and line_of[(holder["unit_id"], item["ref"])]["caveat"], item["code"]


def _shuffled_results(results, rng: random.Random) -> list[dict]:
    out = []
    for result in results:
        result = dict(result, nodes=list(result["nodes"]), edges=list(result["edges"]))
        rng.shuffle(result["nodes"])
        rng.shuffle(result["edges"])
        out.append(result)
    return out


def _unit_prints(built) -> list[tuple]:
    return sorted((u["unit_id"], u["unit_hash"], u["summary_sha"], u["digest"], u["title"]) for u in built["units"])


def test_xu4_adapter_order_does_not_move_units_or_their_signal(tmp_path_factory, approved_tax, routing):
    """어댑터 결과의 노드·엣지 순서를 섞어도(씨앗 50) 단위 id 집합·내용 지문과 단위마다의 코드 신호가 같다."""
    case = _synth_case(tmp_path_factory, "xu4", 40)
    try:
        expected = _unit_prints(case.built)
        signals = {u["unit_id"]: _signal(u, approved_tax, routing) for u in _reviewable(case)}
        later = factories.CAPTURED_AT + 86400
        base, target = devseed.to_adapter_results(case.target.base), devseed.to_adapter_results(case.target.target,
                                                                                                 captured_at=later)
        moved = 0
        for seed in range(50):
            rng = random.Random(seed)
            mixed = _shuffled_results(base, rng)
            moved += [n["local_key"] for n in mixed[0]["nodes"]] != [n["local_key"] for n in base[0]["nodes"]]
            first = factories.make_snapshot(case.store, case.target.project_id, mixed, label=f"XU4-{seed}a")
            second = factories.make_snapshot(case.store, case.target.project_id, _shuffled_results(target, rng),
                                             label=f"XU4-{seed}b", captured_at=later)
            diff_obj = factories.make_diff(case.store, first["snapshot_id"], second["snapshot_id"])
            built = units.build_diff_units(diff_obj, units._ir_view(case.store, first["snapshot_id"],
                                                                   second["snapshot_id"]))
            assert _unit_prints(built) == expected, seed
            assert {u["unit_id"]: _signal(u, approved_tax, routing) for u in built["units"] if u["reviewable"]
                    and u["kind"] != "excluded"} == signals, seed
        assert moved == 50                                     # 섞기가 실제로 순서를 바꿨다
    finally:
        case.store.close()


_LINE_CODE = r"^C\d{{2,}} (?:\[c:[0-9a-f]{{12}}\] )?(?:\(이벤트 없음\) )?{code}(?: |$)"


def _summary_codes(case, codes) -> set[str]:
    """단위 요약 글의 [변경] 줄에 코드로 나타난 것(접은 줄 `Cnn <코드> 같은 변화 N건` 포함 — 문맥 줄은 남의 소유라 뺀다)."""
    found: set[str] = set()
    for unit in case.built["units"]:
        body = unit["summary"].split("\n[문맥]")[0]
        for code in codes:
            if re.search(_LINE_CODE.format(code=re.escape(code)), body, re.MULTILINE):
                found.add(code)
    return found


def test_xu5_every_kind_is_a_summary_line_and_has_mechanisms(synth, producer_cases, approved_tax, routing):
    """33종 코드(스키마 39종 − 아직 어떤 입력도 내지 않는 loadpath 3 · ecad 3)가 전부 어느 단위의 요약 글엔가 줄로 나타난다 —
    syn40 은 대본의 expect_codes 로 센 31종, 짝 있는 부품의 판 두께가 cross.bridge_stale, 남는 것은 지금 생산자가 못 내는
    contact.type_changed(devseed.PRODUCER_GAPS) 하나뿐이다. 그 33종은 전부 변경 → 메커니즘 표에 있고, 줄 하나만으로도 어느
    영역엔가 닿는다(메시 밀도는 설계 변경이 아니라 닿지 않는다)."""
    kinds = {c for c in SCHEMA["event"]["properties"]["code"]["enum"] if not c.startswith(("loadpath.", "ecad."))}
    assert len(kinds) == 33
    expected = set(devseed.expected_codes(synth[40].target.manifest))
    assert len(expected) == 31
    seen = _summary_codes(synth[40], expected)
    assert seen == expected
    bridge = next(case for case in producer_cases if case.name == "bridge")
    seen |= _summary_codes(bridge, {"cross.bridge_stale"})
    assert kinds - seen == set(devseed.PRODUCER_GAPS) == {"contact.type_changed"}
    for code in sorted(kinds):
        out = relevance.code_signal([{"code": code}], [], approved=True, routing=routing, tax=approved_tax)
        related = {d for d, v in out.items() if v["verdict"] == "related"}
        assert bool(related) is (code != "mesh.density_changed"), (code, related)
        assert "unknown" not in {v["verdict"] for v in out.values()}, code


# ---------------------------------------------------------------- 훑기 신호 · 결측 블록 판
@pytest.mark.parametrize(("entry", "failed", "verdict", "reason"), [
    ({"rel": "no", "k": [], "why": ["무관"]}, False, "unrelated", None),
    ({"rel": "no", "k": ["K03"], "why": []}, False, "related", None),   # k 가 달린 no 는 무관이 아니다
    ({"rel": "maybe", "k": [], "why": []}, False, "related", None),
    ({"rel": "yes", "k": ["K01"], "why": []}, False, "related", None),
    ({"rel": "stamp", "k": [], "why": []}, False, "unknown", "stamp"),  # 도장 찍힌 no 는 믿지 않는다
    ({"rel": "error", "k": [], "why": []}, False, "unknown", "error"),  # 그 쪽의 답에 없던 단위
    (None, False, "unknown", "no_answer"),
    ({"rel": "no", "k": [], "why": []}, True, "unknown", "sweep_failed"),
])
def test_sweep_signal_is_unrelated_only_for_a_clean_no(entry, failed, verdict, reason):
    out = relevance.sweep_signal(entry, failed=failed)
    assert (out["verdict"], out["reason"]) == (verdict, reason)
    assert out["stamp"] is (entry is not None and not failed and entry["rel"] == "stamp")


@pytest.mark.parametrize(("sent", "rev", "aware"), [
    (True, "cr-sweep-2", True), (True, "cr-sweep-10", True), (True, "cr-sweep-1", False), (False, "cr-sweep-2", False),
    (True, None, False), (True, "cr-sweep-x", False), (True, "cr-verdict-2", False)])
def test_a_gap_expert_sweep_counts_only_from_the_missing_block_revision(sent, rev, aware):
    assert relevance.sweep_gap_aware(sent, rev) is aware


# ---------------------------------------------------------------- 경로 결정표(m3-cells 3.2) — 줄마다 하나
_UNRELATED = {"verdict": "unrelated", "related_domains": [], "via": {}, "unmapped": [], "reason": None}
_SWEEP_NO = {"verdict": "unrelated", "rel": "no", "k": [], "why": ["무관"], "stamp": False, "reason": None}
_FORCING_KW = {"filter_off": {"filter_mode": "off"}, "rank1": {"rank1": True}, "global_unit": {"unit_kind": "global"},
               "no_cards": {"no_cards": True}, "input_gap": {"input_gap": True}, "widened": {"widened": True},
               "target_off": {"target_off": True}, "handoff": {"handoffs": [{"from": "rf-x", "why": "안테나"}]},
               "tier_a_pending": {"tier_a_pending": True}}


def _key_with(audit: bool, pct: float = 5) -> tuple[str, str, str]:
    """표본 해시가 pct 아래(audit=True) 또는 위인 셀 열쇠 — 결정표가 쓰는 함수로 고르지 않고 해시를 직접 본다."""
    for n in range(10000):
        key = ("T", f"u{n}", "a")
        score = relevance.sample_score("filter_audit", *key)
        if (score < pct / 100) is audit:
            return key
    raise AssertionError("열쇠를 못 찾았다")


def _route(**kw):
    args = {"filter_mode": "on", "rank1": False, "unit_kind": "bundle", "no_cards": False, "input_gap": False,
            "gap_aware": False, "widened": False, "target_off": False, "handoffs": [], "tier_a_pending": False,
            "code": _UNRELATED, "sweep": _SWEEP_NO, "sample_key": _key_with(False), "audit_pct": 5,
            "routing_rev": "change-routing-1.0|mech-owners-1.0|tax-1.2"}
    args.update(kw)
    return relevance.route_decision(**args)


def test_row9_both_signals_unrelated_filters_the_cell():
    out = _route()
    assert (out["decision"], out["route"], out["route_forced"]) == ("filtered", "filtered", None)
    assert (out["would_filter"], out["shadow"]) == (True, False)
    rj = out["route_json"]
    assert (rj["rule"], rj["decision"], rj["filter"], rj["forced_all"]) == ("both_unrelated", "filtered", "on", [])
    assert rj["code"] == _UNRELATED and rj["sweep"] == _SWEEP_NO
    assert rj["routing_rev"] == "change-routing-1.0|mech-owners-1.0|tax-1.2"
    assert rj["audit"]["pct"] == 5 and rj["audit"]["score"] >= 0.05
    assert out["decision"] in relevance.DECISIONS


def test_row9_below_the_audit_hash_the_cell_is_judged_to_the_end():
    key = _key_with(True)
    out = _route(sample_key=key)
    assert (out["decision"], out["route"], out["route_forced"], out["would_filter"]) == (
        "audit", "audit", "filter_audit", True)
    assert out["route_json"]["audit"]["score"] == relevance.sample_score("filter_audit", *key) < 0.05


def test_row9_audit_rate_zero_never_samples_and_hundred_samples_everything():
    keys = [("T", f"u{n}", "a") for n in range(400)]
    assert {_route(sample_key=k, audit_pct=0)["decision"] for k in keys} == {"filtered"}
    assert {_route(sample_key=k, audit_pct=100)["decision"] for k in keys} == {"audit"}
    picked = [k for k in keys if _route(sample_key=k)["decision"] == "audit"]
    assert picked == [k for k in keys if relevance.sample_score("filter_audit", *k) < 0.05]
    assert 0 < len(picked) < 60                                 # 5% 안팎 — 같은 열쇠면 늘 같은 셀이다
    assert [k for k in keys if _route(sample_key=k)["decision"] == "audit"] == picked


@pytest.mark.parametrize("code", ["related", "unrelated", "unknown"])
@pytest.mark.parametrize("sweep", ["related", "unrelated", "unknown"])
def test_row10_anything_but_two_unrelated_signals_is_reviewed(code, sweep):
    """모르면 검토다 — 두 신호가 다 무관일 때만 거른다(D-33 ②)."""
    out = _route(code=dict(_UNRELATED, verdict=code), sweep=dict(_SWEEP_NO, verdict=sweep))
    if (code, sweep) == ("unrelated", "unrelated"):
        assert out["decision"] == "filtered"
    else:
        assert (out["decision"], out["route_forced"], out["would_filter"], out["route_json"]["rule"]) == (
            "review", None, False, "signal_related")
        assert out["route_json"]["audit"] is None


@pytest.mark.parametrize(("rule", "token"), [
    ("filter_off", "filter_off"), ("rank1", "rank1"), ("global_unit", "global_unit"), ("no_cards", "no_cards"),
    ("input_gap", "input_gap"), ("widened", "widened"), ("target_off", "filter_off"), ("handoff", "handoff"),
    ("tier_a_pending", "tier_a_pending")])
def test_rows1_to_8_each_forcing_rule_keeps_a_filterable_cell(rule, token):
    """두 신호가 다 무관인 셀도 강제 줄 하나면 검토로 간다 — 표본 해시 아래 셀도 표본이 아니라 그 강제 사유다."""
    for key in (_key_with(False), _key_with(True)):
        out = _route(sample_key=key, **_FORCING_KW[rule])
        assert (out["decision"], out["route_forced"], out["would_filter"]) == ("review", token, False), key
        assert out["route_json"]["rule"] == rule and out["route_json"]["forced_all"] == [rule]
        assert out["route_json"]["audit"] is None
    assert out["route"] == ("noinput" if rule == "input_gap" else "review")


def test_rows1_to_8_the_first_matching_rule_wins():
    names = [name for name, _token in relevance.FORCING_RULES]
    assert names == ["filter_off", "rank1", "global_unit", "no_cards", "input_gap", "widened", "target_off", "handoff",
                     "tier_a_pending"]                          # m3-cells 3.2 의 줄 순서(6 번은 넓힘 · 대상 끔 둘)
    for i, first in enumerate(names):
        for later in names[i + 1:]:
            kw = {**_FORCING_KW[first], **_FORCING_KW[later]}
            out = _route(**kw)
            assert out["route_json"]["rule"] == first, (first, later)
            assert out["route_json"]["forced_all"] == [first, later], (first, later)
            assert out["route_forced"] == dict(relevance.FORCING_RULES)[first]


def test_row5_a_gap_expert_is_filtered_only_after_the_missing_block_sweep():
    """입력 결손 전문가는 결측 블록을 받은 판(cr-sweep-2)의 훑기일 때만 두 신호 규칙을 탄다(X1-17). 거르지 않으면 noinput 길이다."""
    assert _route(input_gap=True, gap_aware=False)["route_forced"] == "input_gap"
    aware = _route(input_gap=True, gap_aware=True)
    assert (aware["decision"], aware["route"]) == ("filtered", "filtered")
    reviewed = _route(input_gap=True, gap_aware=True, code=dict(_UNRELATED, verdict="related"))
    assert (reviewed["decision"], reviewed["route"]) == ("review", "noinput")
    audited = _route(input_gap=True, gap_aware=True, sample_key=_key_with(True))
    assert (audited["decision"], audited["route"]) == ("audit", "audit")
    assert _route(gap_aware=True)["decision"] == "filtered"     # 결손이 아닌 전문가에게 그 판 표지는 아무 뜻이 없다


def test_row7_handoffs_are_frozen_in_the_route_json():
    handoffs = [{"from": "rf-a", "why": "안테나 간극"}, {"from": "sh-b", "why": "음향 포트"}]
    out = _route(handoffs=handoffs)
    assert out["route_json"]["handoff"] == handoffs and out["route_forced"] == "handoff"


def test_row2_rank1_cells_are_never_filtered_but_shadow_what_filtering_would_close():
    """1순위 셀은 거르지 않고, 9 번이 참이었을 셀을 그림자로 적는다 — 그 사람이 1순위가 아니었다면 거를 셀이다(대상의 1순위 대기는
    그 사람 자신의 몫이라 그림자 판정에서 뺀다). 다른 강제 사유가 있거나 신호가 관련이면 그림자가 아니다."""
    for key in (_key_with(False), _key_with(True)):
        out = _route(rank1=True, sample_key=key)
        assert (out["decision"], out["route_forced"], out["would_filter"], out["shadow"]) == ("review", "rank1", False, True)
    assert _route(rank1=True, tier_a_pending=True)["shadow"] is True
    for other in ("global_unit", "no_cards", "input_gap", "widened", "target_off", "handoff"):
        assert _route(rank1=True, **_FORCING_KW[other])["shadow"] is False, other
    assert _route(rank1=True, sweep=dict(_SWEEP_NO, verdict="unknown"))["shadow"] is False
    assert _route(rank1=True, code=dict(_UNRELATED, verdict="related"))["shadow"] is False
    assert _route(rank1=True, filter_mode="off")["shadow"] is False     # M2 잡은 그림자도 적지 않는다(원장이 바이트로 같다)
    assert _route(rank1=True, filter_mode="shadow")["shadow"] is True


def test_shadow_mode_classifies_but_never_filters():
    for key in (_key_with(False), _key_with(True)):
        out = _route(filter_mode="shadow", sample_key=key)
        assert (out["decision"], out["route"], out["route_forced"]) == ("review", "review", None)
        assert (out["would_filter"], out["shadow"], out["route_json"]["rule"]) == (True, True, "both_unrelated")
        assert out["route_json"]["audit"] is None and out["route_json"]["filter"] == "shadow"
    assert _route(filter_mode="shadow", code=dict(_UNRELATED, verdict="unknown"))["shadow"] is False
    with pytest.raises(ValueError):
        _route(filter_mode="sometimes")


def test_a_real_unit_routes_through_both_signals(synth, approved_tax, routing):
    """생산자 단위 · 실제 코드 신호 · 훑기 회계 모양으로 결정표를 지난다 — 코드가 관련인 영역은 훑기가 no 여도 검토다."""
    unit = _reviewable(synth[40])[0]
    signal = _signal(unit, approved_tax, routing)
    sweep = relevance.sweep_signal({"rel": "no", "k": [], "why": ["무관"], "missing_in": 0})
    for domain in relevance.domain_codes(approved_tax):
        out = _route(code=relevance.code_for(signal, domain), sweep=sweep, unit_kind=unit["kind"])
        assert out["decision"] == ("filtered" if signal[domain]["verdict"] == "unrelated" else "review"), domain
        assert out["route_json"]["code"]["related_domains"] == sorted(d for d, v in signal.items() if v["verdict"] == "related")
