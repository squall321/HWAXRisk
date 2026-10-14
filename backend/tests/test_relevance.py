# 거르기 코드 신호(M3 C3-5) 시험 — 변경 → 메커니즘 표의 닫힘·결정론·모름·역할·승인 문·15영역, 입력은 생산자 경로다
"""단위는 생산자 그대로다 — 합성 대본(syn3·syn40·syn150·무작위 대본)과 `tests/fixtures/diff_pairs` 6쌍을 실제 `compute_diff` →
`units` 로 돌린다. 표가 풀어야 하는 코드의 독립 오라클은 diff 스키마(`rr_diff.v1.json`)의 열거와 `diff.PARAM_RULES` 다 — 표를
읽어 기대를 만들지 않는다.

택소노미 1.2(메커니즘 52 · 배정표 `mech-owners.v1.json`)는 형제 꾸러미 S3-2 의 몫이고 가지 m3 에 아직 없다. 그동안은
`tax` 픽스처가 대역(`TaxonomyDouble` — m3-synthesis 3.4 초안 52행)을 준다. **가지 m3 로 rebase 하면** `tax` 픽스처가
`app.taxonomy` 를 돌려주게 바꾸고 `TaxonomyDouble`·`tests/fixtures/relevance/mech_owners_draft.json` 을 지운다.
"""
from __future__ import annotations

import copy
import json
import random

import pytest

from app import devseed, diff as diff_module, relevance, taxonomy, units
from app.risk_store import RiskStore
from tests import factories
from tests.conftest import BACKEND_DIR, FIXTURES_DIR
from tests.synth import scripts

DRAFT = FIXTURES_DIR / "relevance" / "mech_owners_draft.json"
SCHEMA = json.loads((BACKEND_DIR / "app" / "schemas" / "rr_diff.v1.json").read_text(encoding="utf-8"))["definitions"]
PAIRS = ("pair_add", "pair_kind", "pair_mat", "pair_move", "pair_remove", "pair_thick")


# ---------------------------------------------------------------- 택소노미 1.2 대역(rebase 하면 지운다)
class TaxonomyDouble:
    """`taxonomy.domains_for` · `mech_owners_meta` · `load_taxonomy` 셋의 대역 — 배정표 초안 52행 위에서 돈다. 영역·변경 종류
    축은 지금 택소노미 그대로다(1.2 는 메커니즘만 더한다)."""

    def __init__(self, review_status: str | None = None) -> None:
        self.doc = json.loads(DRAFT.read_text(encoding="utf-8"))
        if review_status is not None:
            self.doc["review_status"] = review_status
        self.rows = {r["code"]: r for r in self.doc["rows"]}
        real = taxonomy.load_taxonomy()
        mechanisms = [{"code": code, "status": "active"} for code in self.rows]
        self._tax = {**real, "taxonomy_version": self.doc["taxonomy_version"],
                     "axes": {**real["axes"], "mechanism": mechanisms}}

    def domains_for(self, codes):
        out: dict[str, str] = {}
        for code in codes:
            row = self.rows.get(code)
            if row is None:
                continue
            for domain in row["owners"]:
                out[domain] = "owner"
            for domain in row["related"]:
                out.setdefault(domain, "related")
        return out

    def mech_owners_meta(self):
        return {"version": self.doc["mech_owners_version"], "review_status": self.doc["review_status"],
                "reviewed_at": self.doc["reviewed_at"]}

    def load_taxonomy(self):
        return self._tax


@pytest.fixture(scope="module")
def tax():
    return TaxonomyDouble()


@pytest.fixture(scope="module")
def approved_tax():
    return TaxonomyDouble(review_status="approved")


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
    assert routing["review_status"] == "draft"                 # 사용자가 훑기 전이다(D-35) — 승인 문이 닫혀 있다
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
    for owners, table, opened in ((TaxonomyDouble(), routing, False), (TaxonomyDouble("approved"), routing, False),
                                  (TaxonomyDouble(), approved_routing, False),
                                  (TaxonomyDouble("approved"), approved_routing, True)):
        assert relevance.routing_approved(routing=table, tax=owners) is opened
        out = _signal(unit, owners, table, approved=relevance.routing_approved(routing=table, tax=owners))
        if opened:
            assert {v["verdict"] for v in out.values()} == {"related", "unrelated"}
        else:
            assert {(v["verdict"], v["reason"]) for v in out.values()} == {("unknown", "not_approved")}
    # 승인 칸 말고는 같은 표다 — 한 칸만 고친 커밋이 거르기를 연다.
    assert {k: v for k, v in approved_routing.items() if k != "review_status"} == {
        k: v for k, v in routing.items() if k != "review_status"}
