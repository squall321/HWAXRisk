# 숫자 원장 · 금지값 점검(RK-04) 시험 — 원장에 없는 수(작은 정수 포함) · 금지값 쓰임(코드별 · '*') · 단위 불일치 · 원장에 없는 id 꼴, 글과 근거 묶음 둘 다
"""HWAXPortal docs/request-1117 RK-04. 게이트웨이 verify_answer 는 소수와 100 이상만 보았다 — 여기서는 작은 정수와 id 꼴도 본다. 수 · 코드 · 지표 키는 합성 값이다.

  실행:  .venv/bin/python -m pytest tests/test_ledger_numbers.py
"""
from __future__ import annotations

import pytest

from app import ledger_numbers, ledger_routes
from app.errors import AppError
from tests import factories
from tests.ledger_support import EDITOR, OWNER, STRANGER, VIEWER, call, ledger_box, seed_ledger  # noqa: F401

NUMBERS = [
    {"name": "최대 응력", "value": 412.5, "unit": "MPa", "definition": "합성 정의", "revision": "r2", "source_file": "stress.csv", "line": 7,
     "metric_key": "MET-STRESS"},
    {"name": "보드 두께", "value": "0.65", "unit": "mm", "revision": "r2", "metric_key": "MET-THK"},
    {"name": "시험 횟수", "value": 3},
]
FORBIDDEN = [{"code": "R-005", "value": 412.5, "unit": "MPa", "reason": "이전 리비전 값 — 이번 판에 쓰면 안 된다"},
             {"code": "*", "value": 9.9, "reason": "폐기된 기준값"}]


def _put(box, who=OWNER, numbers=NUMBERS, forbidden=FORBIDDEN) -> dict:
    return ledger_routes.put_numbers(box.target_key, ledger_routes.NumbersBody(numbers=numbers, forbidden=forbidden),
                                     ident=factories.ident(who))


def _check(box, **body) -> dict:
    return ledger_routes.post_numbers_check(box.target_key, ledger_routes.NumbersCheckBody(**body), ident=factories.ident(VIEWER))


def test_put_replaces_the_ledger_and_the_same_body_changes_nothing(ledger_box):
    first = _put(ledger_box)
    assert first["changed"] is True and (first["numbers_n"], first["forbidden_n"]) == (3, 2)
    assert _put(ledger_box, who=EDITOR)["changed"] is False
    smaller = _put(ledger_box, numbers=NUMBERS[:1], forbidden=[])
    assert smaller["changed"] is True and smaller["numbers_n"] == 1
    row = ledger_box.store.query_one("SELECT owner_sub, updated_by, value_text, metric_key FROM rr_ledger_numbers")
    assert dict(row) == {"owner_sub": OWNER, "updated_by": OWNER, "value_text": "412.5", "metric_key": "MET-STRESS"}
    for bad in ([{"name": "x", "value": "열"}], [{"name": "x", "value": 1}, {"name": "x", "value": 2}],
                [{"name": "x", "value": 1, "metric_key": "나쁜 키"}]):
        with pytest.raises(AppError):
            _put(ledger_box, numbers=bad, forbidden=[])
    with pytest.raises(AppError):
        _put(ledger_box, numbers=[], forbidden=[{"code": "R-001", "value": 1}])          # 까닭이 없다


def test_a_text_check_counts_unknown_numbers_small_integers_forbidden_values_unit_mismatches_and_unknown_ids(ledger_box):
    seed_ledger(ledger_box)
    _put(ledger_box)
    text = ("R-005 의 최대 응력은 412.5 MPa 이고 두께는 0.650 mm 다.\n"         # 금지값(그 코드의 줄) · 같은 값(0.650 = 0.65)
            "R-001 은 412.5 mm 로 적혔다.\n"                                      # 같은 값, 다른 단위
            "시험은 3 회 · 표본 2 개 · 기준 9.9 를 썼다.\n"                       # 작은 정수 2 는 원장에 없다 · 9.9 는 어디서나 금지
            "MET-STRESS 와 MET-STRAIN · R-099 · VRD-COND 를 본다.")               # 원장에 없는 지표 키 · 코드(같은 머리) — VRD- 는 머리가 다르다
    out = _check(ledger_box, text=text)
    counts = out["counts"]
    assert counts["forbidden"] == 2 and {(f["forbidden_code"], f["value"], f["where"]) for f in out["forbidden"]} == {
        ("R-005", "412.5", "line:1"), ("*", "9.9", "line:3")}
    assert [(u["value"], u["unit"], u["where"]) for u in out["unit_mismatch"]] == [("412.5", "mm", "line:2")]
    assert {(n["value"], n["kind"]) for n in out["not_in_ledger"]} == {("2", "integer"), ("9.9", "decimal")}
    assert sorted(u["token"] for u in out["unknown_ids"]) == ["MET-STRAIN", "R-099"]
    assert all("005" not in n["value"] for n in out["not_in_ledger"])                    # 코드 속 숫자는 수로 세지 않는다
    assert counts["numbers"] == counts["matched"] + counts["not_in_ledger"] and out["numbers_in_ledger"] == 3
    hit = out["forbidden"][0]
    assert hit["col"] >= 1 and "412.5" in hit["context"] and hit["reason"]


def test_a_bundle_check_knows_the_code_of_each_line(ledger_box):
    seed_ledger(ledger_box)
    owner = factories.ident(OWNER)
    ledger_routes.post_version(ledger_box.target_key, ledger_routes.BuildBody(base_version=2, layers=[
        {"name": "수치 비고", "order": 80, "rows": {"R-005": {"비고": "응력 412.5 MPa"}, "R-006": {"비고": "응력 412.5 MPa"}}}]),
        ident=owner)
    _put(ledger_box)
    bundle = ledger_routes.post_evidence_bundle(ledger_box.target_key, ledger_routes.BundleBody(
        version=3, template={"name": "비고만", "caps": {"비고": 3000}, "total_cap": 3000}), ident=owner)["bundle_id"]
    out = _check(ledger_box, bundle_id=bundle)
    assert out["source"] == {"kind": "bundle", "bundle_id": bundle, "version": 3}
    assert [(f["code"], f["forbidden_code"]) for f in out["forbidden"]] == [("R-005", "R-005")]   # R-006 의 같은 값은 금지가 아니다
    assert out["counts"]["matched"] == 2
    with pytest.raises(AppError) as exc:
        _check(ledger_box, bundle_id="eb_none")
    assert exc.value.http_status == 404
    with pytest.raises(AppError):
        _check(ledger_box, text="글", bundle_id=bundle)


def test_the_gates_hold_on_rest_and_mcp(ledger_box):
    with pytest.raises(AppError) as exc:
        _put(ledger_box, who=VIEWER)
    assert exc.value.code == "role_insufficient"
    with pytest.raises(AppError) as exc:
        ledger_routes.post_numbers_check(ledger_box.target_key, ledger_routes.NumbersCheckBody(text="1"), ident=factories.ident(STRANGER))
    assert exc.value.http_status == 404
    ledger_box.act_as(None)
    assert call("risk_numbers_put", target_key=ledger_box.target_key, numbers=NUMBERS)["error"] == "delegation_required"
    ledger_box.act_as(EDITOR)
    assert call("risk_numbers_put", target_key=ledger_box.target_key, numbers=NUMBERS, forbidden=FORBIDDEN)["changed"] is True
    ledger_box.act_as(VIEWER)
    many = "\n".join(f"값 {i}.5 와 {i} 를 적었다 — 길게 늘인 설명 글이 따라온다 " * 2 for i in range(1, 400))
    out = call("risk_numbers_check", target_key=ledger_box.target_key, text=many)
    assert out["counts"]["not_in_ledger"] > len(out["not_in_ledger"]) and out["shown_per_list"] >= 1


def test_decimals_and_units_compare_by_value():
    assert ledger_numbers.to_decimal("1,234.50") == ledger_numbers.to_decimal(1234.5)
    assert ledger_numbers.to_decimal("열") is None and ledger_numbers.to_decimal(True) is None
    assert ledger_numbers.unit_key("µm") == ledger_numbers.unit_key("um") and ledger_numbers.unit_key("MPa") == "mpa"
