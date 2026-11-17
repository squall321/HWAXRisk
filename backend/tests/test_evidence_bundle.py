# 심의 근거 묶음(RK-02) 시험 — 색인이 늘 맨 앞(실은 코드 전부 · 판 · 칸 정의 판 · 묶음 id · '없다는 뜻이 아니다'), 칸별 · 합 상한, 표기 규칙, 가림, 엔진 상한 거절, 지문(contracts §1)
"""HWAXPortal docs/request-1117 RK-02 · contracts.md §1. 요청서 틀(a=2,600 b=5,200 c=6,500 d=2,600 e=2,400 f=1,800 · 합 20,000)은 합성 시험
틀로만 쓴다. 함정 셋을 지킨다 — 일부 행만 실으면 좌석이 빠진 행을 '없음' 으로 읽었다(색인) · 근거 칸 이름에 판정을 쓰면 좌석이 인용했다(칸은 칸
정의의 중립 이름만, key 는 기계 이름) · 파일 줄을 행으로 셌다(행으로 센다).

  실행:  .venv/bin/python -m pytest tests/test_evidence_bundle.py
"""
from __future__ import annotations

import json
import types

import pytest

from app import config, evidence_bundle, labels, ledger_routes
from app.errors import AppError
from tests import factories
from tests import ledger_support
from tests.ledger_support import CODES, OWNER, STRANGER, VIEWER, call, seed_ledger

ledger_box = ledger_support.ledger_box          # 판정표 시험 상자(tests/ledger_support.py)를 이 모듈에도 건다

TEMPLATE = {"name": "합성 6칸", "caps": {"부품": 2600, "고장 모드": 5200, "1차 등급": 6500, "최종 등급": 2600, "근거 유형": 2400,
                                        "비고": 1800}, "total_cap": 20000}


def _build(box, **body) -> dict:
    return ledger_routes.post_evidence_bundle(box.target_key, ledger_routes.BundleBody(**{"template": TEMPLATE, **body}),
                                              ident=factories.ident(OWNER))


def _refused(fn, *args, **kwargs) -> AppError:
    with pytest.raises(AppError) as exc:
        fn(*args, **kwargs)
    return exc.value


def test_the_index_comes_first_and_names_every_row_and_what_was_left_out(ledger_box):
    seed_ledger(ledger_box)
    built = _build(ledger_box)
    assert built["created"] is True and built["bundle_id"].startswith("eb_") and built["items_n"] == 1 + len(TEMPLATE["caps"])
    got = ledger_routes.get_evidence_bundle(built["bundle_id"], ident=factories.ident(VIEWER))
    evidence = got["evidence"]
    index = evidence[0]
    assert set(index) == {"source", "tool", "args", "result", "key"} and index["key"].endswith(".idx")
    assert all(evidence_bundle.KEY_RE.fullmatch(item["key"]) for item in evidence)
    lines = index["result"].splitlines()
    assert lines[-1] == evidence_bundle.INDEX_TAIL
    assert f"묶음 {built['bundle_id']}" in index["result"] and "판정표 판 v2" in index["result"] and "칸 정의 판 c1" in index["result"]
    assert f"실은 행 {len(CODES) + 1}개(코드 차례): " + ", ".join([*CODES, "R-013"]) in index["result"]
    # 칸 항목 — 틀 차례, 기계 key, 칸 이름은 칸 정의의 이름 그대로(source · 머리), 한 줄에 코드 하나.
    assert [item["key"].split(".")[1] for item in evidence[1:]] == [f"f{n:02d}" for n in range(1, 7)]
    first = evidence[1]["result"].splitlines()
    assert first[0].startswith("[판정표 칸 01] 부품 — 판 v2 · 행 13개") and first[1] == "R-001 | PART-A" and len(first) == 14
    # 지문은 contracts §1 의 식이고, 받는 쪽이 다시 재면 같다.
    assert got["fingerprint"] == built["fingerprint"] == evidence_bundle.fingerprint(evidence)
    # 인용 형식(contracts §5 C1) — 플랫폼 · 종류(엔진 ref.kind 와 같은 risk_bundle) · id · 판/칸 정의 판 · 범위.
    assert got["cite"] == built["cite"] == {"source_platform": "hwax_risk", "source_kind": "risk_bundle", "source_id": built["bundle_id"],
                                            "source_version": "v2/c1",
                                            "scope": {"target_key": ledger_box.target_key, "codes": [*CODES, "R-013"]}}
    assert json.loads(json.dumps(evidence)) == evidence


def test_values_use_the_axis_labels_and_the_bundle_has_no_bare_axis_letters(ledger_box):
    seed_ledger(ledger_box)
    evidence = evidence_bundle.payload(evidence_bundle.bundle_row(ledger_box.store, _build(ledger_box)["bundle_id"]))["evidence"]
    final = next(item for item in evidence if "최종 등급" in item["source"])["result"]
    kinds = next(item for item in evidence if "근거 유형" in item["source"])["result"]
    assert "R-005 | [등급 C조]" in final and "R-001 | [등급 A조]" in final
    assert "R-003 | 유형③" in kinds
    assert labels.check_obj([item["result"] for item in evidence]) == []
    assert "R-001 | (빈 칸)" in next(item for item in evidence if "'비고'" in item["source"])["result"]


def test_caps_hold_per_field_and_in_total_and_cut_fields_name_the_codes_they_left_out(ledger_box):
    """요청서 틀 꼴 — 칸 합이 21,100 이라 합 상한 20,000 에서 뒤 칸이 줄어든다. 잘린 칸은 실리지 않은 코드를 안내 줄에 적는다."""
    seed_ledger(ledger_box)
    owner = factories.ident(OWNER)
    rows = {f"R-{i:03d}": {"부품": f"PART-{i % 7}", "고장 모드": "합성 고장 모드 설명 " * 4, "1차 등급": "AB"[i % 2],
                           "최종 등급": "BC"[i % 2], "근거 유형": "DE"[i % 2], "비고": "비고 " * 6}
            for i in range(1, 121)}
    ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=2, layers=[
        {"name": "큰 층", "order": 90, "rows": rows}]), ident=owner)
    built = _build(ledger_box, version=3)
    per = built["per_field"]
    assert all(per[col]["chars"] <= cap for col, cap in TEMPLATE["caps"].items())
    assert sum(v["chars"] for v in per.values()) <= TEMPLATE["total_cap"]
    assert per["고장 모드"]["truncated"] is True and per["고장 모드"]["codes_cut"] > 0
    evidence = evidence_bundle.payload(evidence_bundle.bundle_row(ledger_box.store, built["bundle_id"]))["evidence"]
    cut = next(item for item in evidence if "'고장 모드'" in item["source"])["result"]
    assert "값이 없다는 뜻이 아니다" in cut.splitlines()[-1] and f"실리지 않은 코드 {per['고장 모드']['codes_cut']}개" in cut
    assert "(상한에서 잘림" in evidence[0]["result"]
    # 행 수 = 코드 줄 수(머리 · 안내 줄 밖) — 줄바꿈이 든 값도 한 줄이다.
    ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=2, layers=[
        {"name": "여러 줄", "order": 91, "rows": {"R-002": {"비고": "첫 줄\n둘째 줄"}}}]), ident=owner)
    small = _build(ledger_box, version=4, codes=["R-001", "R-002", "R-003"])
    note = next(item for item in evidence_bundle.payload(evidence_bundle.bundle_row(ledger_box.store, small["bundle_id"]))["evidence"]
                if "'비고'" in item["source"])["result"].splitlines()
    assert note[0].endswith("행 3개(코드 차례, 한 줄에 코드 하나)") and len(note) == 4 and note[2] == "R-002 | 첫 줄 ⏎ 둘째 줄"


def test_a_subset_bundle_lists_only_its_codes_and_unknown_codes_or_fields_are_refused(ledger_box):
    seed_ledger(ledger_box)
    built = _build(ledger_box, codes=["R-005", "R-001"])
    index = evidence_bundle.payload(evidence_bundle.bundle_row(ledger_box.store, built["bundle_id"]))["evidence"][0]["result"]
    assert "실은 행 2개(코드 차례): R-001, R-005" in index and index.endswith(evidence_bundle.INDEX_TAIL)
    assert _refused(_build, ledger_box, codes=["R-999"]).code == "bundle_unknown_codes"
    wrong = {"name": "판정 이름 칸", "caps": {"FAIL 근거": 100}, "total_cap": 100}
    assert _refused(_build, ledger_box, template=wrong).code == "bundle_unknown_fields"


def test_over_the_engine_limits_is_refused_at_build_time_with_the_numbers(ledger_box, monkeypatch):
    seed_ledger(ledger_box)
    monkeypatch.setattr(config, "settings", types.SimpleNamespace(**{**vars(config.settings), "risk_bundle_max_items": 3}))
    too_many = _refused(_build, ledger_box)
    assert (too_many.code, too_many.http_status, too_many.detail["items"], too_many.detail["limit"]) == (
        "bundle_too_many_items", 422, 7, 3)
    monkeypatch.setattr(config, "settings", types.SimpleNamespace(**{**vars(config.settings), "risk_bundle_max_items": 120,
                                                                      "risk_bundle_max_chars": 500}))
    too_big = _refused(_build, ledger_box)
    assert too_big.code == "bundle_too_large" and too_big.detail["chars"] > 500 == too_big.detail["limit"]
    assert ledger_box.store.query_one("SELECT COUNT(*) AS n FROM rr_evidence_bundles")["n"] == 0


def test_personal_shapes_in_cells_are_masked_and_counted_but_numbers_stay(ledger_box):
    seed_ledger(ledger_box)
    ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=2, layers=[
        {"name": "담당 메모", "order": 92, "rows": {"R-001": {"비고": "담당 qa.tester@example.com · 010-1234-5678"},
                                                "R-002": {"비고": "두께 4.352099001761481 · 간극 0.05"}}}]), ident=factories.ident(OWNER))
    built = _build(ledger_box, version=3)
    assert built["masked_n"] == 2
    note = next(item for item in evidence_bundle.payload(evidence_bundle.bundle_row(ledger_box.store, built["bundle_id"]))["evidence"]
                if "'비고'" in item["source"])["result"]
    assert "R-001 | 담당 [가림:메일] · [가림:전화]" in note and "R-002 | 두께 4.352099001761481 · 간극 0.05" in note
    # 묶음은 늘 가린다(사용자 결정 11-17) — mask=false 는 받지 않는다.
    refused = _refused(_build, ledger_box, version=3, mask=False)
    assert (refused.code, refused.http_status) == ("bundle_mask_required", 422)
    assert "끌 수 없다" in evidence_bundle.payload(evidence_bundle.bundle_row(ledger_box.store, built["bundle_id"]))["evidence"][0]["result"]


def test_the_order_of_the_template_caps_is_part_of_the_bundle(ledger_box):
    """반대 검토 M4 — 칸 차례가 항목 key(f01 …)와 합 상한 나누기를 정하는데 지문이 정렬한 칸으로 재어 차례만 다른 틀이 같은 묶음이 됐다."""
    seed_ledger(ledger_box)
    one = _build(ledger_box, template={"name": "차례", "caps": {"부품": 900, "비고": 900}, "total_cap": 1000})
    two = _build(ledger_box, template={"name": "차례", "caps": {"비고": 900, "부품": 900}, "total_cap": 1000})
    assert one["bundle_id"] != two["bundle_id"] and one["per_field"]["부품"]["key"].endswith("f01") and two["per_field"]["비고"]["key"].endswith("f01")
    stored = ledger_box.store.query_one("SELECT template_json FROM rr_evidence_bundles WHERE bundle_id = ?", (two["bundle_id"],))
    assert json.loads(stored["template_json"])["caps"] == [["비고", 900], ["부품", 900]]


def test_the_same_inputs_are_the_same_bundle_and_the_gates_hold(ledger_box):
    seed_ledger(ledger_box)
    first = _build(ledger_box)
    again = _build(ledger_box)
    assert again["created"] is False and again["bundle_id"] == first["bundle_id"] and again["fingerprint"] == first["fingerprint"]
    body = ledger_routes.BundleBody(template=TEMPLATE)
    assert _refused(ledger_routes.post_evidence_bundle, ledger_box.target_key, body, ident=factories.ident(VIEWER)).code == (
        "role_insufficient")
    assert _refused(ledger_routes.get_evidence_bundle, first["bundle_id"], ident=factories.ident(STRANGER)).code == "E404"
    assert _refused(ledger_routes.get_evidence_bundle, "eb_none", ident=factories.ident(VIEWER)).code == "E404"


def test_mcp_returns_the_whole_evidence_by_default_and_pages_on_request(ledger_box):
    seed_ledger(ledger_box)
    ledger_box.act_as(None)
    assert call("risk_build_evidence_bundle", target_key=ledger_box.target_key, template=TEMPLATE)["error"] == "delegation_required"
    ledger_box.act_as(OWNER)
    built = call("risk_build_evidence_bundle", target_key=ledger_box.target_key, template=TEMPLATE)
    assert built["created"] is True
    ledger_box.act_as(VIEWER)
    whole = call("risk_get_evidence_bundle", bundle_id=built["bundle_id"])
    assert whole["fingerprint"] == evidence_bundle.fingerprint(whole["evidence"]) and len(whole["evidence"]) == built["items_n"]
    first = call("risk_get_evidence_bundle", bundle_id=built["bundle_id"], offset=0)
    assert first["paged"] is True and first["evidence"][0] == whole["evidence"][0]
    ledger_box.act_as(STRANGER)
    assert call("risk_get_evidence_bundle", bundle_id=built["bundle_id"])["error"] == "not_visible"
    assert call("risk_get_evidence_bundle", bundle_id="eb_none")["error"] == "not_visible"


def test_every_line_breaking_character_in_a_cell_is_folded(ledger_box):
    """반대 검토 L4 — \\v · \\u2028 · \\u2029 따위도 줄을 가른다(str.splitlines). 한 줄에 코드 하나를 지키려 다 접는다."""
    seed_ledger(ledger_box)
    owner = factories.ident(OWNER)
    ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=2, layers=[
        {"name": "갈린 비고", "order": 93, "rows": {"R-002": {"비고": "가\x0b나 다 라\x85마"}}}]), ident=owner)
    built = _build(ledger_box, version=3, codes=["R-001", "R-002"])
    note = next(item for item in evidence_bundle.payload(evidence_bundle.bundle_row(ledger_box.store, built["bundle_id"]))["evidence"]
                if "'비고'" in item["source"])["result"]
    assert note.splitlines()[2] == "R-002 | 가 ⏎ 나 ⏎ 다 ⏎ 라 ⏎ 마" and len(note.splitlines()) == 3
