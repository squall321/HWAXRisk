# 축별 표기 규칙(RK-07) 시험 — 등급 · 증거 유형 · 주의 등급 · 판정의 표시 글, risk_taxonomy(part="labels") · GET /api/taxonomy/labels, 단독 대문자 A ~ J 검사
"""HWAXPortal docs/request-1117 RK-07 · contracts.md §4. 같은 글자(A · B · C …)가 축마다 다른 뜻이라 좌석이 엉뚱한 반박을 냈다 — 표시 글은 축 낱말이
붙거나 다른 기호 체계를 쓰고, 검사는 축 낱말 없는 단독 대문자를 센다.

  실행:  .venv/bin/python -m pytest tests/test_labels.py
"""
from __future__ import annotations

import pytest

import app.mcp_server as srv
from app import labels, routes


def test_each_axis_has_its_own_wording_and_the_verdicts_are_sp_keys():
    assert labels.label_value("grade", "A") == ("[등급 A조]", True)
    assert labels.label_value("grade", "b조") == ("[등급 B조]", True)
    assert labels.label_value("type", "C") == ("유형③", True) and labels.label_value("type", "J") == ("유형⑩", True)
    assert labels.label_value("attention", "D") == ("주의 D", True)
    assert labels.label_value("verdict", "conditional") == ("VRD-COND", True)
    assert labels.label_value("verdict", "VRD-COND") == ("VRD-COND", True)
    # 모르는 값 · 빈 값 · 축 없음은 그대로다(지어내지 않는다).
    assert labels.label_value("grade", "Z") == ("Z", False)
    assert labels.label_value("grade", "") == ("", False) and labels.label_value(None, "A") == ("A", False)
    # 이미 표시 글이면 같은 글이다(두 번 입혀도 그대로).
    assert labels.label_value("grade", "[등급 A조]") == ("[등급 A조]", True)
    shown = {axis: set(labels.load_labels()["axes"][axis]["values"].values()) for axis in labels.AXES}
    assert not shown["grade"] & shown["type"] and not shown["grade"] & shown["attention"]


@pytest.mark.parametrize("text,letters", [
    ("최종은 [등급 A조] 이고 근거는 유형③, 주의 A 다.", []),
    ("판정 VRD-COND · 코드 R-001 · CAD 단면 · A등급 · B 등급", []),
    ("이 행은 B 로 올렸다", ["B"]),
    ("A, C 둘 다 아니다.\n(D) 도 아니다", ["A", "C", "D"]),
    ("K 와 Z 는 축 글자가 아니다", []),
])
def test_the_checker_counts_standalone_capitals_without_an_axis_word(text, letters):
    found = labels.check_text(text)
    assert [v["letter"] for v in found] == letters
    if found:
        assert found[-1]["line"] >= 1 and found[-1]["col"] >= 1 and found[-1]["context"]


def test_the_checker_walks_nested_values_but_not_keys():
    hits = labels.check_obj({"A": "[등급 A조]", "rows": [{"note": "B 로 봤다"}]})
    assert [(h["path"], h["letter"]) for h in hits] == [("rows[0].note", "B")]


def test_labels_part_rides_the_taxonomy_tool_and_the_rest_route():
    assert "labels" in routes.TAXONOMY_PARTS
    out = srv.risk_taxonomy(part="labels")
    assert set(out["labels"]["axes"]) == set(labels.AXES)
    assert out["labels"]["axes"]["verdict"]["sp_keys"]["conditional"] == "VRD-COND"
    assert out["labels"]["axes"]["verdict"]["sp_keys_status"] == "unconfirmed"
    assert routes.get_taxonomy_labels() == out["labels"]


def test_the_rest_route_answers_without_identity(client):
    r = client.get("/api/taxonomy/labels")
    assert r.status_code == 200 and r.json()["axes"]["grade"]["values"]["A"] == "[등급 A조]"
