# rr_diff.v1 계약 — 실제 생산자(diff.create_diff)가 쓰고 REST · MCP 가 그대로 내는 diff 본문이 계약을 지나고, 계약은 그 밖을 거절한다(OI-1)
"""생산자 본문이 계약 밖이었다(context-notes MB-17 남긴 것 · OI-1) — 합성 비교 하나에서 15건(최상위 pair_kind · 조립품 주체 asm:…). 시험
전체의 diff 1,077개를 훑은 탐침에서는 다섯 갈래가 더 나왔다 — 명명 치수 dim:<name> · dyna 접촉 범위 contact#<n> · 결과 [dn, metric] 의
사건 주체 열쇠, 제외 사유 capture_partial(정본 §3.3.6 의 source_drift 도 같은 처지), 의미층 차단 capture_partial. 정본(포털 plan §3.3 —
앱 docs/plan.md 가 가리킨다)과 생산자를 견줘 계약을 생산자 쪽으로 고쳤다 — pair_kind 는 rr_diffs 열의 사본이라 비교 화면이 본문에서
읽고, 주체 열쇠는 정본 §3.3.2 의 cid 열쇠 그대로이며, 제외 사유 13종은 정본 §3.3.6 의 어휘다. 생산자가 틀린 것은 없었다 — 결과 kind
'drop' · 빈 diff_id · 빈 rule_version 은 rr_ir 밖의 손 IR 이나 상태 없는 손 스냅샷을 생산자에 직접 먹인 시험에서만 났다.

원장은 실제 생산자 사슬이다 — 합성 다건(devseed 어댑터 결과 → 동결 → 상태 → 대응 → create_diff) 씨앗 셋, 다른 과제 쌍(대응을 정하지
못한 부품 — G2), 뒤 캡처가 부분인 쌍(mcad 어댑터가 범위를 받아 싣는 scope), 뒤 캡처의 소스 응답 꼴이 바뀐 쌍(schema_drift). 본문은
REST · MCP 가 내는 함수(routes.diff_part part='diff')로 받는다.

  실행:  .venv/bin/python -m pytest tests/test_diff_contract.py
"""
from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from jsonschema import validators

import app.mcp_server as srv
from app import diff, routes
from app.risk_store import RiskStore
from tests import factories
from tests.conftest import BACKEND_DIR

SCHEMA = json.loads((BACKEND_DIR / "app" / "schemas" / "rr_diff.v1.json").read_text(encoding="utf-8"))
VALIDATOR = validators.validator_for(SCHEMA)(SCHEMA)
SEEDS = (None, 1, 2)                      # None 은 합성기의 기본 씨앗이다(syn40 은 생산자가 내는 코드를 다 끈다)


def _errors(doc: Any) -> list[str]:
    return [f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message[:200]}" for e in VALIDATOR.iter_errors(doc)]


def _served(store, diff_id: str) -> dict:
    """REST GET /diffs/{id}?part=diff 와 MCP risk_get_diff(part='diff') 가 내는 본문 — 같은 함수(routes.diff_part)다."""
    owner = store.query_one("SELECT owner_sub FROM rr_diffs WHERE id = ?", (diff_id,))["owner_sub"]
    return routes.diff_part(diff_id, "diff", owner_sub=owner)


def _rename(node: dict, new: str) -> None:
    """mcad 부품 하나의 경로 · 이름을 바꾼다 — 대응 사다리가 정하지 못해 대응표에 pending 한 줄이 선다(G2)."""
    old = node["label"]
    node.update(label=new, canon_key=node["canon_key"].replace(old, new), local_key=node["local_key"].replace(old, new))


def _mcad(results: list[dict]) -> dict:
    return next(r for r in results if (r.get("source") or {}).get("kind") == "mcad")


def _pair(store, code: str, later: list[dict]) -> str:
    """같은 과제의 앞 · 뒤 캡처(손 어댑터 픽스처 → 실제 동결)와 그 비교."""
    project = factories.make_project(store, code=code)
    base = factories.make_snapshot(store, project, factories.fixture_adapter_results(), label="DV1")["snapshot_id"]
    target = factories.make_snapshot(store, project, later, label="DV2",
                                     captured_at=factories.CAPTURED_AT + 86400)["snapshot_id"]
    return factories.make_diff(store, base, target)["diff_id"]


@pytest.fixture(scope="module")
def produced(tmp_path_factory) -> dict[str, dict]:
    """실제 생산자가 쓴 본문 — 이름 → 본문."""
    store = RiskStore(tmp_path_factory.mktemp("diff-contract") / "risk_review.db")
    store.open()
    store.migrate()
    out: dict[str, dict] = {}
    try:
        with factories.routes_store(store):        # 본문은 라우트 함수(routes.diff_part)로 받는다
            for seed in SEEDS:
                synth = factories.make_diff_target(store, 40, seed=seed, project={"code": f"SYN-{seed}"}, open_target=False)
                out[f"syn40-{seed}"] = _served(store, synth.diff_id)

            # 다른 과제 쌍 — 뒤 과제의 부품 하나는 경로 · 이름이 바뀌어 대응이 정해지지 않는다(G2 가 의미층을 막는다).
            base_project = factories.make_project(store, code="CROSS-1")
            target_project = factories.make_project(store, code="CROSS-2")
            renamed = factories.fixture_adapter_results()
            _rename(next(n for n in _mcad(renamed)["nodes"] if n.get("label") == "PLATE_1"), "NEWPART_0")
            base = factories.make_snapshot(store, base_project, factories.fixture_adapter_results(), label="X1")["snapshot_id"]
            target = factories.make_snapshot(store, target_project, renamed, label="X2")["snapshot_id"]
            out["cross"] = _served(store, factories.make_diff(store, base, target)["diff_id"])

            # 뒤 캡처가 부분이다 — 실제 mcad 어댑터는 잡 인자의 범위(scope)를 소스에 싣는다(adapters/mcad.py). 두께도 바뀐다.
            partial = factories.fixture_adapter_results()
            _mcad(partial)["source"]["scope"] = {"match": ["PLATE*"]}
            factories.set_thickness(partial, "PLATE_1", 1.0)
            out["partial"] = _served(store, _pair(store, "PART-1", partial))

            # 뒤 캡처의 소스 응답 꼴이 바뀌었다(degraded schema_drift — rr_ir 어휘, ECAD 어댑터가 실제로 낸다). 두께도 바뀐다.
            drift = factories.fixture_adapter_results()
            _mcad(drift)["source"]["degraded"] = ["schema_drift"]
            factories.set_thickness(drift, "PLATE_1", 1.0)
            out["drift"] = _served(store, _pair(store, "DRIFT-1", drift))
    finally:
        store.close()
    return out


@pytest.mark.parametrize("name", [*(f"syn40-{s}" for s in SEEDS), "cross", "partial", "drift"])
def test_a_produced_diff_meets_the_contract(produced, name):
    """생산자가 쓴 본문은 계약 오류가 0 이다 — 종전에는 합성 비교 하나에서 15건(최상위 pair_kind · asm: 주체)이었다."""
    assert _errors(produced[name]) == [], name


def _subject_forms(doc: dict) -> set[str]:
    forms = set()
    for event in doc["semantic"]["events"]:
        dns = event["subject"]["dns"]
        if event["code"] == "result.part_metric_shift":
            forms.add("result")
        elif dns and all(str(d).startswith("p:") for d in dns):
            forms.add("node")
        else:
            forms.update(str(d).split(":")[0].split("#")[0] for d in dns)
    return forms


def _excluded(doc: dict) -> set[str]:
    reasons = set()
    for layer in ("structural", "parametric"):
        for items in doc[layer].values():
            for item in items if isinstance(items, list) else ():
                if isinstance(item, dict) and item.get("excluded_reason"):
                    reasons.add(item["excluded_reason"])
    return reasons


def test_the_produced_set_reaches_every_widened_part_of_the_contract(produced):
    """시험이 넓힌 자리를 다 지난다(빈 통과가 아니다) — 사건 주체 열쇠 다섯 꼴 · pair_kind 두 값 · 의미층 차단 둘 · 새 제외 사유 둘."""
    docs = list(produced.values())
    assert set().union(*map(_subject_forms, docs)) >= {"node", "asm", "dim", "contact", "result"}
    assert {d["pair_kind"] for d in docs} == {"same_project_revision", "cross_project"}
    assert produced["cross"]["pair_kind"] == "cross_project" and produced["cross"]["semantic"]["blocked_by"] == "G2"
    assert produced["partial"]["semantic"]["blocked_by"] == "capture_partial"
    assert produced["partial"]["semantic"]["events"] == []
    assert "capture_partial" in _excluded(produced["partial"])
    assert "source_drift" in _excluded(produced["drift"])


def test_the_mcp_read_serves_the_stored_body(produced, risk_store, monkeypatch):
    """MCP risk_get_diff(part='diff') 의 본문도 계약 안이다 — REST 와 같은 함수(routes.diff_part)가 저장된 본문을 그대로 낸다."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    synth = factories.make_diff_target(risk_store, 3)
    factories.act_as_delegate(monkeypatch, factories.OWNER)
    served = srv.risk_get_diff(diff_id=synth.diff_id, part="diff")
    assert served == _served(risk_store, synth.diff_id) and _errors(served) == []


def test_the_excluded_reason_vocabulary_is_the_producers(produced):
    """제외 사유 어휘는 하나다 — 계약 enum == 생산자 diff.EXCLUDED_REASONS(+ null) == 정본 §3.3.6 의 13종."""
    enum = SCHEMA["definitions"]["excluded_reason"]["enum"]
    assert enum == [*diff.EXCLUDED_REASONS, None]
    assert len(diff.EXCLUDED_REASONS) == 13 and {"source_drift", "capture_partial"} <= set(diff.EXCLUDED_REASONS)
    # 결과 사건의 주체 열쇠 [dn, metric] 의 지표는 result_delta 의 지표 어휘와 같다(생산자 diff.RESULT_METRICS 를 품는다).
    metrics = SCHEMA["definitions"]["result_metric"]["enum"]
    assert metrics == SCHEMA["definitions"]["result_item"]["properties"]["metric"]["enum"]
    assert set(diff.RESULT_METRICS) <= set(metrics)


def _event(doc: dict, code: str) -> tuple[int, dict]:
    return next((i, e) for i, e in enumerate(doc["semantic"]["events"]) if e["code"] == code)


@pytest.mark.parametrize("case", ["part_with_asm_key", "rollup_with_node", "dim_with_node", "scope_with_dim", "result_three_keys",
                                  "result_metric_first", "top_level_unknown", "pair_kind_other", "pair_kind_missing",
                                  "blocked_by_other", "excluded_reason_other"])
def test_the_contract_still_refuses_what_the_producer_does_not_emit(produced, case):
    """넓힌 계약이 생산자 밖을 열지 않았다 — 사건 code 마다 주체 열쇠의 꼴이 묶이고(부품 사건에 asm: · 롤업에 노드 · 결과에 셋), 최상위는
    여전히 닫혀 있고, 어휘 밖 값은 거절된다."""
    doc = copy.deepcopy(produced["syn40-None"])
    events = doc["semantic"]["events"]
    if case == "part_with_asm_key":
        i, e = _event(doc, "part.added")
        events[i]["subject"]["dns"] = ["asm:syn_phone/rear_asm"]
    elif case == "rollup_with_node":
        i, e = _event(doc, "asm.rollup_changed")
        events[i]["subject"]["dns"] = [_event(doc, "part.added")[1]["subject"]["dns"][0]]
    elif case == "dim_with_node":
        i, e = _event(doc, "dim.named_changed")
        events[i]["subject"]["dns"] = [_event(doc, "part.added")[1]["subject"]["dns"][0]]
    elif case == "scope_with_dim":
        i, e = _event(doc, "contact.scope_changed")
        events[i]["subject"]["dns"] = ["dim:plate1_t"]
    elif case == "result_three_keys":
        i, e = _event(doc, "result.part_metric_shift")
        events[i]["subject"]["dns"] = [*e["subject"]["dns"], "worst_g"]
    elif case == "result_metric_first":
        i, e = _event(doc, "result.part_metric_shift")
        events[i]["subject"]["dns"] = list(reversed(e["subject"]["dns"]))
    elif case == "top_level_unknown":
        doc["owner_sub"] = "someone@example.com"
    elif case == "pair_kind_other":
        doc["pair_kind"] = "same_project"
    elif case == "pair_kind_missing":
        del doc["pair_kind"]                      # 생산자가 늘 싣는다 — 비교 화면이 기대는 칸이라 계약이 요구한다
    elif case == "blocked_by_other":
        doc["semantic"]["blocked_by"] = "G7"
    else:
        item = doc["parametric"]["node_params"][0]
        item["excluded_reason"] = "parser_differs"
    assert _errors(doc), case
