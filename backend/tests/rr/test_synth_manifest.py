# 합성 다건 변경 생성기(WP5b C3)의 기초 단언 — 대본의 코드 집계가 생산자 diff 와 같고, 같은 씨앗이면 같은 diff 본문이다
"""입력은 `app/devseed.py` 가 만든 어댑터 결과뿐이고 IR·대응·diff 는 실제 생산자가 만든다(`tests/factories.make_diff_target`).

기대는 대본에서 나온다 — 연산마다 적은 `expect_codes` 와, 설계 모형에서 센 조립 단위 롤업. 어긋나면 생성기와 생산자 가운데
한쪽이 틀린 것이고 출력에 맞춰 기대를 고치지 않는다. 지금 생산자가 못 내는 것 둘은 따로 재현 시험으로 둔다(xfail strict).
"""
from __future__ import annotations

import ast
import json
from collections import Counter

import pytest

from app import devseed
from app.risk_store import RiskStore
from tests import factories
from tests.conftest import BACKEND_DIR
from tests.synth import scripts

SCHEMA = json.loads((BACKEND_DIR / "app" / "schemas" / "rr_diff.v1.json").read_text(encoding="utf-8"))
# 스키마의 이벤트 코드 39종 가운데 diff._semantic 이 내는 것 — loadpath 3 · ecad 3 은 지금 어떤 입력도 내지 않는다.
SCHEMA_CODES = set(SCHEMA["definitions"]["event"]["properties"]["code"]["enum"])
EMITTED_CODES = {c for c in SCHEMA_CODES if not c.startswith(("loadpath.", "ecad."))}


def _store(tmp_path_factory, name: str) -> RiskStore:
    store = RiskStore(tmp_path_factory.mktemp(name) / "risk_review.db")
    store.open()
    store.migrate()
    return store


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    stores, out = [], {}
    try:
        for size in scripts.SIZES:
            store = _store(tmp_path_factory, f"syn{size}")
            stores.append(store)
            out[size] = factories.make_diff_target(store, size, check=False)
        yield out
    finally:
        for store in stores:
            store.close()


def _ops(target: factories.SynthTarget) -> list[devseed.ChangeRecord]:
    return [r for r in target.manifest if "derived" not in r.flags]


@pytest.mark.parametrize("size", scripts.SIZES)
def test_size_is_the_number_of_script_operations(built, size):
    assert len(_ops(built[size])) == size == len(scripts.script_for(size))


@pytest.mark.parametrize("size", scripts.SIZES)
def test_event_codes_match_the_script(built, size):
    target = built[size]
    assert factories.synth_mismatch(target.diff, target.manifest) == []
    assert len(target.diff["semantic"]["events"]) == sum(len(r.expect_codes) for r in target.manifest)


def test_the_same_seed_gives_the_same_diff_body(tmp_path_factory):
    first, second = (factories.make_diff_target(_store(tmp_path_factory, f"again{i}"), 40) for i in range(2))
    assert factories.diff_fingerprint(first.diff) == factories.diff_fingerprint(second.diff)
    assert [r for r in first.manifest] == [r for r in second.manifest]


def test_a_different_seed_gives_a_different_diff(tmp_path_factory):
    one = factories.make_diff_target(_store(tmp_path_factory, "seed-a"), 40, seed=1)
    other = factories.make_diff_target(_store(tmp_path_factory, "seed-b"), 40, seed=2)
    assert factories.diff_fingerprint(one.diff) != factories.diff_fingerprint(other.diff)


def test_syn40_runs_every_code_the_producer_emits(built):
    codes = {e["code"] for e in built[40].diff["semantic"]["events"]}
    assert codes == EMITTED_CODES - set(_gap_codes())
    assert len(codes) == 32


def test_syn40_carries_the_shapes_downstream_must_handle(built):
    """감소 변화 · 단위 섞임 · 부품 키 없는 이벤트 · 경계 계면 · 설계 무관 · 이름에 판단어가 든 부품."""
    target = built[40]
    events = target.diff["semantic"]["events"]
    decreases = {e["code"] for e in events if (e["magnitude"]["value"] or 0) < 0}
    assert {"part.thickness_changed", "iface.gap_changed", "result.part_metric_shift", "iface.band_area_changed",
            "iface.rank_down", "iface.penetration_changed", "dim.named_changed"} <= decreases
    assert {e["magnitude"]["unit"] for e in events} >= {"mm", "rank", "mm2", "MPa", "G", None}
    assert {e["code"] for e in events if not e["subject"]["ckeys"]} == {
        "dim.named_changed", "dim.named_unmeasured", "asm.rollup_changed", "contact.scope_changed"}
    assert [e["code"] for e in events if e["design_relevant"] is False] == ["mesh.density_changed"]
    boundary = [r for r in target.manifest if "boundary" in r.flags]
    assert len(boundary) >= 2 and {target.base.parts.get(n, target.target.parts.get(n)).asm
                                   for r in boundary for n in r.subjects[:2]} != set()
    # 부품 이벤트의 글에는 이름이 실린다(계면 이벤트는 지금 nid 로 적는다 — WP1 R-8). 판단어가 든 이름이 셋 다 실린다.
    text = "\n".join(e["text"] for e in events if e["code"].startswith("part."))
    assert [name for name in devseed.HAZARD_NAMES if name not in text] == []


def test_boundary_records_really_cross_assemblies(built):
    for size in (40, 150):
        target = built[size]
        for record in (r for r in target.manifest if "boundary" in r.flags):
            parts = {**target.base.parts, **target.target.parts}
            assert parts[record.subjects[0]].asm != parts[record.subjects[1]].asm, record


def test_syn150_is_skewed_like_a_real_revision(built):
    """한 조립 단위에 60건, 변경 1건짜리 조립 단위 12개, 경계 계면 20, 이벤트 없는 변화 10."""
    script = scripts.script_for(150)
    by_asm = Counter(params["asm"] for _, params in script if "asm" in params)
    assert by_asm[scripts.HEAVY_ASM] == 60
    assert sorted(asm for asm, n in by_asm.items() if n == 1) == sorted(scripts.SINGLE_ASMS)
    target = built[150]
    # 대본이 정한 조립 단위에 실제 부품이 앉았다(빈 부품을 찾지 못해 다른 단위에 만들지 않았다). 옮긴 부품은 base 쪽을 본다.
    for (op, params), record in zip(script, _ops(target)):
        homes = {design.parts[s].asm for s in record.subjects for design in (target.base, target.target)
                 if s in design.parts}
        assert not homes or params["asm"] in homes, (op, params, record)
    assert sum("boundary" in r.flags for r in target.manifest) == 20
    assert sum(any(f.startswith("excluded:") for f in r.flags) for r in target.manifest) == 10
    assert all(not r.expect_codes for r in target.manifest if any(f.startswith("excluded:") for f in r.flags))


@pytest.mark.parametrize("seed", range(5))
def test_random_scripts_match_the_producer(tmp_path_factory, seed):
    target = factories.make_diff_target(_store(tmp_path_factory, f"random{seed}"), 40, seed=seed,
                                        script=devseed.random_script(80, seed), check=False)
    assert factories.synth_mismatch(target.diff, target.manifest) == []


def test_a_300_change_random_script_still_matches(tmp_path_factory):
    """WP1 의 순서 속성 시험이 쓰는 크기(의미 이벤트 300건 이상)."""
    target = factories.make_diff_target(_store(tmp_path_factory, "random300"), 40, seed=7,
                                        script=devseed.random_script(300, 7), check=False)
    assert factories.synth_mismatch(target.diff, target.manifest) == []
    assert len(target.diff["semantic"]["events"]) >= 300


def test_the_factory_refuses_a_pair_that_misses_the_script(tmp_path_factory):
    """공장은 대본과 다른 diff 를 조용히 넘기지 않는다 — AssertionError 가 아니라 SynthMismatch 다(xfail 이 삼키지 않게)."""
    with pytest.raises(factories.SynthMismatch, match="contact.type_changed"):
        factories.make_diff_target(_store(tmp_path_factory, "refuse"), 3, script=[("contact.type_changed", {})])


def _gap_codes() -> list[str]:
    return [key for key in devseed.PRODUCER_GAPS if "(" not in key]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "생산자 결함(WP1 목록) — diff._edge_change 가 엣지 kind 만 견줘 contact_type 이 바뀐 접촉(*CONTACT_TIED → "
    "*CONTACT_AUTOMATIC)이 이벤트를 내지 않는다. contact.type_changed 는 contact↔scope 로 kind 가 뒤집힐 때만 난다"))
def test_a_contact_type_change_is_an_event(tmp_path_factory):
    target = factories.make_diff_target(_store(tmp_path_factory, "contact-type"), 3,
                                        script=[("contact.type_changed", {})], check=False)
    assert factories.synth_mismatch(target.diff, target.manifest) == []


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "생산자 결함(WP1 목록) — diff._parametric 이 같은 dn 의 mcad·dyna 노드 값을 같은 cid 로 by_dn 에 덮어, 짝 있는 부품의 "
    "판 두께 변화(bbox 까지)가 part.moved·part.rotated 를 덧붙인다. 짝 없는 부품의 같은 변화는 두께 하나만 낸다"))
def test_a_twinned_plate_thickness_change_is_not_read_as_a_move(tmp_path_factory):
    target = factories.make_diff_target(_store(tmp_path_factory, "twin-plate"), 3,
                                        script=[("cross.bridge_stale", {"local": False})], check=False)
    assert factories.synth_mismatch(target.diff, target.manifest) == []


def test_production_modules_do_not_import_devseed():
    """합성기는 시험과 dev 주입 전용이다 — 운영 경로가 import 하면 합성 자료가 운영 원장으로 새는 길이 생긴다."""
    offenders = []
    for path in sorted((BACKEND_DIR / "app").rglob("*.py")):
        if path.name == "devseed.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [f"{node.module or ''}.{a.name}" for a in node.names] + [node.module or ""]
            if any(n.split(".")[-1] == "devseed" or ".devseed" in n for n in names):
                offenders.append(path.relative_to(BACKEND_DIR).as_posix())
    assert offenders == []
