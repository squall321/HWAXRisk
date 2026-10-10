# 의장 글의 길이 — 스키마 상한을 넘는 칸을 정규화가 말없이 자르지 않고 저장하며 그 사실을 parse_warnings 에 남긴다(절단 전수 조사 N5)
from __future__ import annotations

from app.narrative import FACETS, normalize_risk_spec
from tests.test_atoms import make_ctx, make_finding, make_spec

LONG = "가" * 700


def test_long_chair_fields_are_kept_whole_and_reported():
    spec = make_spec(findings=[make_finding(trigger_condition="코너 낙하 특수 조건", trigger_text=LONG[:300])])
    spec["character"] = {"one_liner": LONG[:200], "facets": [
        {"facet": FACETS[0], "statements": [{"text": LONG[:500], "polarity": "neutral", "confidence": "medium",
                                             "by": ["chair"]}]}]}
    spec["cross_domain"] = [{"from_domain": "mech", "to_domain": "rel", "path": LONG, "cites": [], "raised_by": []}]
    spec["open_items"] = [{"question": LONG[:300], "resolving_check": {"kind": "tool", "ref": "x"}}]
    out = normalize_risk_spec(spec, make_ctx())
    body, warnings = out["spec"], out["parse_warnings"]
    assert body["findings"][0]["trigger_text"] == LONG[:300]
    assert body["character"]["one_liner"] == LONG[:200]
    assert body["cross_domain"][0]["path"] == LONG
    assert body["open_items"][0]["question"] == LONG[:300]
    texts = [s.get("text") for f in body["character"]["facets"] for s in f.get("statements") or ()]
    assert LONG[:500] in texts
    joined = " ".join(warnings)
    for where, n, limit in (("trigger_text", 300, 120), ("character/one_liner", 200, 140), ("/text", 500, 240),
                            ("cross_domain/0/path", 700, 400), ("open_items/0/question", 300, 200)):
        assert f"{n}자 — 스키마 상한 {limit}자" in joined and where in joined, (where, warnings)
