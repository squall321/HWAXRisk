# 검토 단위 동결 발췌(M2 걸음 U2, 근거 A 층) — 그 부품의 계면 전부·명세·해석 결과·규칙 적중을 IR 동결본에서 결정적으로 뽑는지
"""입력은 생산자 경로다 — `factories.make_diff_target(40·150)` 의 IR 과 diff, 그리고 devseed 어댑터 결과를 실제 IR 빌더로 얼린
스냅샷. 오라클은 IR 표(`rr_ir_nodes`·`rr_ir_edges`)와 `rr_states.rule_hits_json` 을 SQL 로 직접 센다 — 근거 조립 코드를 쓰지 않는다.
"""
from __future__ import annotations

import json
import random
import time

import pytest

from app import brief, devseed, render, routes, units
from app.common import parse_ref
from app.risk_store import RiskStore
from tests import factories


def _store(tmp_path_factory, name: str) -> RiskStore:
    store = RiskStore(tmp_path_factory.mktemp(name) / "risk_review.db")
    store.open()
    store.migrate()
    return store


class Case:
    def __init__(self, store, target):
        self.store, self.target = store, target
        self.view = units._ir_view(store, target.base_snapshot_id, target.target_snapshot_id)
        self.built = units.build_diff_units(target.diff, self.view)
        self.evidence = {u["unit_id"]: units.evidence_lines(u, self.view) for u in self.built["units"]}

    def reviewable(self):
        return [u for u in self.built["units"] if u["reviewable"]]


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    cases = {}
    for size in (40, 150):
        store = _store(tmp_path_factory, f"ev{size}")
        cases[size] = Case(store, factories.make_diff_target(store, size, check=True, open_target=False))
    yield cases
    for case in cases.values():
        case.store.close()


# ---------------------------------------------------------------- 오라클(IR 표를 직접 센다)
def _part_nids(case: Case, dn: str) -> set[str]:
    sids = (case.target.base_snapshot_id, case.target.target_snapshot_id)
    rows = case.store.query("SELECT nid FROM rr_ir_nodes WHERE snapshot_id IN (?, ?) AND dn = ?", (*sids, dn))
    nids = {r["nid"] for r in rows}
    for m in case.target.diff["correspondence"]["matched"]:
        if m["dn"] == dn:
            nids.update((m["nid_base"], m["nid_target"]))
    return nids


def _iface_eids(case: Case, nids: set[str]) -> set[str]:
    sids = (case.target.base_snapshot_id, case.target.target_snapshot_id)
    marks = ",".join("?" for _ in nids)
    rows = case.store.query(
        f"SELECT eid FROM rr_ir_edges WHERE snapshot_id IN (?, ?) AND kind_family = 'iface' AND status != 'rejected'"
        f" AND (a IN ({marks}) OR b IN ({marks}))", (*sids, *nids, *nids))
    return {r["eid"] for r in rows}


def test_every_interface_of_a_unit_part_is_in_its_evidence(synth):
    """그 부품이 끼인 계면 전부(변경 없는 것 포함)가 근거 줄에 있다 — 오라클은 rr_ir_edges 를 직접 센다."""
    unchanged = 0
    for case in synth.values():
        for unit in case.reviewable():
            nids = set().union(*(_part_nids(case, p["dn"]) for p in unit["parts"])) if unit["parts"] else set()
            want = _iface_eids(case, nids) if nids else set()
            rows = case.evidence[unit["unit_id"]]["evidence"]
            got = {row["ref"] for row in rows if row["kind"] == "iface"}
            assert got == want, (unit["unit_id"], sorted(want - got), sorted(got - want))
            unchanged += sum(1 for row in rows if row["kind"] == "iface" and row["text"].endswith("변경 없음"))
    assert unchanged > 0


def test_clearance_is_listed_as_near(synth):
    seen = 0
    for case in synth.values():
        for evidence in case.evidence.values():
            for row in evidence["evidence"]:
                if row["kind"] == "iface" and " clearance " in f" {row['text']} ":
                    assert row["text"].startswith("근접 "), row
                    seen += 1
    assert seen > 0


def test_result_rows_cover_every_part_risk_row_of_the_unit(synth):
    case = synth[40]
    sids = (case.target.base_snapshot_id, case.target.target_snapshot_id)
    risk = set()
    for sid in sids:
        ir = json.loads(case.store.query_one("SELECT ir_json FROM rr_snapshots WHERE id = ?", (sid,))["ir_json"])
        risk.update(r["nid"] for r in (ir.get("results") or {}).get("part_risk") or ())
    seen = 0
    for unit in case.reviewable():
        nids = set().union(*(_part_nids(case, p["dn"]) for p in unit["parts"])) if unit["parts"] else set()
        got = {row["ref"] for row in case.evidence[unit["unit_id"]]["evidence"] if row["kind"] == "result"}
        assert got == nids & risk, unit["unit_id"]
        seen += len(got)
    assert seen > 0


def test_rule_hits_that_touch_the_unit_are_cited(synth):
    case = synth[40]
    hits = []
    for sid in (case.target.base_snapshot_id, case.target.target_snapshot_id):
        row = case.store.query_one("SELECT rule_hits_json FROM rr_states WHERE snapshot_id = ?", (sid,))
        hits.extend(h for h in json.loads(row["rule_hits_json"]) if h.get("pass") is False)
    assert hits
    cited = 0
    for unit in case.reviewable():
        rows = case.evidence[unit["unit_id"]]["evidence"]
        related = {row["ref"] for row in rows if row["kind"] in ("part", "iface", "contact")}
        want = {f"rule:{h['rule']}" for h in hits if set(h.get("refs") or ()) & related}
        assert {row["ref"] for row in rows if row["kind"] == "rule"} == want, unit["unit_id"]
        cited += len(want)
    assert cited > 0


def test_parts_carry_both_snapshots_and_neighbors_are_one_hop(synth):
    case = synth[40]
    for unit in case.reviewable():
        rows = case.evidence[unit["unit_id"]]["evidence"]
        parts = [row for row in rows if row["kind"] == "part"]
        assert len(parts) >= len(unit["parts"])
        mine = set().union(*(_part_nids(case, p["dn"]) for p in unit["parts"])) if unit["parts"] else set()
        for row in rows:
            if row["kind"] == "neighbor":
                assert row["ref"] not in mine
    changed = [row for unit in case.reviewable() for row in case.evidence[unit["unit_id"]]["evidence"]
               if row["kind"] == "part" and "→" in row["text"]]
    assert changed and any(" · 추가" in row["text"] for unit in case.reviewable()
                           for row in case.evidence[unit["unit_id"]]["evidence"] if row["kind"] == "part")


def test_order_follows_the_priority(synth):
    """단위 부품 명세 → 바뀐 계면 → 바뀌지 않은 계면(간섭 → 접합·접촉 → 근접) → 이웃 → 해석 결과 → 규칙 적중."""
    rank = {"part": 0, "iface": 1, "contact": 1, "neighbor": 2, "result": 3, "rule": 4}
    for case in synth.values():
        for evidence in case.evidence.values():
            kinds = [rank[row["kind"]] for row in evidence["evidence"]]
            assert kinds == sorted(kinds), evidence["unit_id"]
            edges = [row["text"] for row in evidence["evidence"] if row["kind"] in ("iface", "contact")]
            states = [0 if text.endswith(("바뀜", "추가", "삭제")) else 1 for text in edges]
            assert states == sorted(states), evidence["unit_id"]
            near = [text.startswith("근접 ") for text, state in zip(edges, states) if state == 1]
            assert near == sorted(near), evidence["unit_id"]


# ---------------------------------------------------------------- 상태·결정론·형식
def test_excluded_units_have_none_and_global_units_have_no_parts_to_cite(synth):
    for case in synth.values():
        for unit in case.built["units"]:
            evidence = case.evidence[unit["unit_id"]]
            if unit["kind"] == "excluded":
                assert evidence["status"] == "none" and evidence["evidence"] == []
            else:
                assert evidence["status"] == "ok" and evidence["error"] is None
            if unit["kind"] == "global":
                assert evidence["evidence"] == []


def test_refs_are_only_existing_schemes(synth):
    for case in synth.values():
        for evidence in case.evidence.values():
            for row in evidence["evidence"]:
                parsed = parse_ref(row["ref"])
                assert parsed is not None and parsed["kind"] in ("p", "e", "rule"), row["ref"]
                assert "«" not in row["text"] and "»" not in row["text"]


def _shuffled(value, rng):
    if isinstance(value, dict):
        return {k: _shuffled(v, rng) for k, v in value.items()}
    if isinstance(value, list):
        out = [_shuffled(v, rng) for v in value]
        if out and all(isinstance(v, dict) for v in out):
            rng.shuffle(out)
        return out
    return value


def test_the_same_input_gives_the_same_evidence_sha(synth):
    case = synth[150]
    sids = (case.target.base_snapshot_id, case.target.target_snapshot_id)
    irs = [json.loads(case.store.query_one("SELECT ir_json FROM rr_snapshots WHERE id = ?", (sid,))["ir_json"])
           for sid in sids]
    hits = [json.loads(case.store.query_one("SELECT rule_hits_json FROM rr_states WHERE snapshot_id = ?",
                                            (sid,))["rule_hits_json"]) for sid in sids]
    rng = random.Random(3)
    view = units.view_of(_shuffled(irs[0], rng), _shuffled(irs[1], rng), names=brief.name_index(case.store, sids),
                         base_rule_hits=_shuffled(hits[0], rng), target_rule_hits=_shuffled(hits[1], rng))
    for unit in case.built["units"]:
        again = units.evidence_lines(unit, view)
        first = case.evidence[unit["unit_id"]]
        assert (again["sha"], again["text"], again["chars"]) == (first["sha"], first["text"], first["chars"])


def test_nothing_is_cut_and_chars_are_counted(synth):
    for case in synth.values():
        for unit in case.built["units"]:
            evidence = case.evidence[unit["unit_id"]]
            assert evidence["chars"] == len(evidence["text"])
            for row in evidence["evidence"]:
                assert f"[{row['ref']}]" in evidence["text"]
            assert render.lint_text(evidence["text"])["ok"], evidence["text"]


def test_payload_and_refs_carry_the_evidence(synth):
    case = synth[40]
    for unit in case.reviewable():
        evidence = case.evidence[unit["unit_id"]]
        payload = units.payload_of(unit, evidence)
        assert payload["evidence"] == [{"ref": row["ref"], "text": row["text"]} for row in evidence["evidence"]]
        assert payload["evidence_sha"] == evidence["sha"] and payload["evidence_status"] == "ok"
        refs = units.unit_refs(unit, evidence)
        assert {row["ref"] for row in evidence["evidence"]} <= refs
        assert not refs & {x["ref"] for x in unit["context"]["lines"]} - {row["ref"] for row in evidence["evidence"]}


def test_syn150_evidence_is_fast(synth):
    case = synth[150]
    started = time.perf_counter()
    for unit in case.built["units"]:
        units.evidence_lines(unit, case.view)
    assert time.perf_counter() - started < 2.0


# ---------------------------------------------------------------- 폐기된 IR · 강등 표지 · 원천 문자열
def test_a_purged_ir_is_failed_ir_absent(tmp_path_factory):
    store = _store(tmp_path_factory, "purged")
    target = factories.make_diff_target(store, 3, check=True, open_target=False)
    built = units.build_diff_units(target.diff, units._ir_view(store, target.base_snapshot_id,
                                                               target.target_snapshot_id))
    code = store.query_one("SELECT code FROM rr_projects WHERE id = ?", (target.project_id,))["code"]
    with factories.routes_store(store):
        routes.purge_project(target.project_id, routes.PurgeBody(code=code, reason="시험"), ident=factories.ident())
    view = units._ir_view(store, target.base_snapshot_id, target.target_snapshot_id)
    assert view["base"]["present"] is False and view["target"]["present"] is False
    for unit in built["units"]:
        evidence = units.evidence_lines(unit, view)
        assert (evidence["status"], evidence["error"], evidence["evidence"]) == ("failed", "ir_absent", [])
    store.close()


def _pair_from_adapters(store, base_results, target_results) -> tuple[dict, dict, dict]:
    project_id = factories.make_project(store)
    first = factories.make_snapshot(store, project_id, base_results, label="DV1")
    later = factories.CAPTURED_AT + 86400
    second = factories.make_snapshot(store, project_id, target_results, label="DV2", captured_at=later)
    diff = factories.make_diff(store, first["snapshot_id"], second["snapshot_id"])
    return first, second, diff


def test_degraded_codes_of_both_snapshots_go_to_the_notes(tmp_path_factory):
    """강등 표지는 어댑터 결과의 degraded 칸만 바꿔 실제 IR 빌더로 얼린다 — rr_snapshots.degraded_json 에서 읽혀 notes 로 간다."""
    store = _store(tmp_path_factory, "degraded")
    base, target, _records = devseed.apply_script(devseed.build_design(devseed.SynthSpec(seed=5, n_parts=12)),
                                                  [("part.thickness_changed", {"sign": -1})], 5)
    target_results = devseed.to_adapter_results(target, captured_at=factories.CAPTURED_AT + 86400)
    target_results[0]["degraded"] = ["interfaces_truncated"]
    first, second, diff = _pair_from_adapters(store, devseed.to_adapter_results(base), target_results)
    view = units._ir_view(store, first["snapshot_id"], second["snapshot_id"])
    assert view["target"]["degraded"] == ["interfaces_truncated"] and view["base"]["degraded"] == []
    built = units.build_diff_units(diff, view)
    assert any(unit["reviewable"] for unit in built["units"])
    for unit in built["units"]:
        if unit["reviewable"]:
            evidence = units.evidence_lines(unit, view)
            assert "target 스냅샷 강등 표지 interfaces_truncated — 계면 목록이 잘린 캡처다." in evidence["notes"]
            assert "[주의] target 스냅샷 강등 표지" in evidence["text"]
            assert units.payload_of(unit, evidence)["notes"].endswith(evidence["notes"])
    store.close()


def test_source_strings_stay_inside_quotes_in_the_render(tmp_path_factory, monkeypatch):
    """`SUS304 OK`·`POKETONE`·`강화유리` 같은 재질 이름이 L16·L13 에 걸리지 않는다(W2-10) — 렌더는 «» 안, 엔진 몫 글은 «» 없이."""
    monkeypatch.setattr(devseed, "MATERIALS", ("SUS304 OK", "POKETONE", "강화유리"))
    store = _store(tmp_path_factory, "words")
    target = factories.make_diff_target(store, 3, check=True, open_target=False,
                                        spec=devseed.SynthSpec(seed=9, n_parts=12, asms=devseed.DEFAULT_ASMS[:3],
                                                               named_dims=1))
    view = units._ir_view(store, target.base_snapshot_id, target.target_snapshot_id)
    built = units.build_diff_units(target.diff, view)
    texts = []
    for unit in built["units"]:
        evidence = units.evidence_lines(unit, view)
        assert render.lint_text(evidence["text"])["ok"], evidence["text"]
        texts.append(evidence["text"])
        for row in evidence["evidence"]:
            for word in ("SUS304 OK", "POKETONE", "강화유리"):
                if word in row["text"]:
                    assert f"«{word}»" in evidence["text"]
    joined = "\n".join(texts)
    assert "«SUS304 OK»" in joined or "«POKETONE»" in joined or "«강화유리»" in joined
    store.close()
