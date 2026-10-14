# 택소노미 1.2(메커니즘 14종, 재설계 M3 S3-2) — 옛 38행 보존 · 대분류 일치 · 1.1 별칭 보존 · 1.1 finding 정규화 불변
"""D-34 가 광학·음향·RF·방수·ESD·자기 등 14종을 더했다. 1.1 에서 이미 코드로 풀리던 낱말·finding 은 1.2 에서도 같은 코드다 — 비교
기준은 얼린 1.1 자산(`tests/fixtures/taxonomy/taxonomy.1.1.json`, HWAXRisk 3aea93b 의 것)이다.
"""
from __future__ import annotations

import copy
import gzip
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from app import engine_client, narrative, taxonomy
from tests.conftest import BACKEND_DIR, FIXTURES_DIR
from tests.rr import legacy_build, v3_build, v4_build

TAX_1_1 = json.loads((FIXTURES_DIR / "taxonomy" / "taxonomy.1.1.json").read_text(encoding="utf-8"))
# D-34 가 더한 14종 — 차례는 m3-synthesis 3.4 표의 것이다(택소노미 축 끝에 붙는다).
NEW_1_2 = ("optical.alignment", "optical.stray_light", "optical.contamination", "acoustic.leak", "acoustic.resonance",
           "acoustic.port_block", "rf.detune", "rf.efficiency", "rf.isolation", "rf.sar", "interface.seal_compression",
           "interface.ingress_path", "electrical.esd", "electrical.magnetic_interference")
MAJORS_1_2 = ("thermal", "mechanical", "interface", "electrical", "material", "process", "optical", "acoustic", "rf")


def _active(doc: dict) -> list[str]:
    return [m["code"] for m in doc["axes"]["mechanism"] if m.get("status", "active") == "active"]


def _domains() -> list[str]:
    return [d["code"] for d in taxonomy.load_taxonomy()["axes"]["domain"]]


@pytest.fixture
def under():
    """정규화(narrative)가 보는 택소노미를 시험 안에서만 바꿔 끼운다 — 끝나면 원래 자산과 색인 캐시로 돌린다."""
    original = narrative._taxonomy

    def use(doc: dict) -> None:
        narrative._taxonomy = lambda: doc
        narrative._mechanism_index.cache_clear()

    yield use
    narrative._taxonomy = original
    narrative._mechanism_index.cache_clear()


# ---------------------------------------------------------------- 택소노미 1.2
def test_taxonomy_1_2_appends_the_fourteen_mechanisms_and_leaves_the_1_1_rows_alone():
    doc = taxonomy.load_taxonomy()
    assert doc["taxonomy_version"] == "1.2" and TAX_1_1["taxonomy_version"] == "1.1"
    axis = doc["axes"]["mechanism"]
    assert len(_active(doc)) == len(axis) == 52 and len(set(_active(doc))) == 52
    assert axis[:38] == TAX_1_1["axes"]["mechanism"]                       # 옛 38행은 한 칸도 바뀌지 않았다
    assert tuple(m["code"] for m in axis[38:]) == NEW_1_2
    for row in axis[38:]:
        assert row["code"] == f"{row['mechanism']}.{row['detail']}" and row["label"] and row["description"]
        assert (row["version_added"], row["status"], row["merged_into"]) == ("1.2", "active", None), row["code"]
        assert row["default_detectability"] in {d["code"] for d in doc["axes"]["detectability"]}
        assert row["default_tools"] == []                                  # 모르면 비운다(m3-synthesis S3-2)
    # 다른 축은 그대로다 — 1.2 는 메커니즘과 그 낱말만 더한다.
    assert {k: v for k, v in doc["axes"].items() if k != "mechanism"} == {
        k: v for k, v in TAX_1_1["axes"].items() if k != "mechanism"}
    assert {k: v for k, v in doc.items() if k not in ("taxonomy_version", "axes", "synonyms")} == {
        k: v for k, v in TAX_1_1.items() if k not in ("taxonomy_version", "axes", "synonyms")}
    assert engine_client.review_mechanisms() == [{"code": m["code"], "label": m["label"]} for m in axis]


def test_the_mechanism_majors_agree_across_asset_normalizer_schema_and_share_only_two_names_with_domains():
    """대분류 아홉 == 자산에서 읽은 정규화의 집합 == risk_spec enum(P-17-1 — enum 은 대분류다). 대분류와 영역 코드가 글자로 겹치는
    것은 material·rf 둘뿐이고(두 축을 문자열로 잇는 코드는 없다 — 영역은 좌석 키 접두), 영역 코드는 동의어 낱말이 아니다."""
    assert taxonomy.mechanism_majors() == MAJORS_1_2
    assert taxonomy.mechanism_majors(TAX_1_1) == MAJORS_1_2[:6]
    spec = json.loads((BACKEND_DIR / "app" / "schemas" / "risk_spec.v1.json").read_text(encoding="utf-8"))
    assert tuple(spec["definitions"]["finding"]["properties"]["mechanism"]["enum"]) == MAJORS_1_2
    assert set(MAJORS_1_2) & set(_domains()) == {"material", "rf"}
    assert not set(taxonomy.load_taxonomy()["synonyms"]) & set(_domains())


def test_a_major_of_1_2_survives_normalization_and_an_unknown_major_still_folds_to_process(under):
    """정규화의 대분류 집합은 자산에서 온다 — 1.2 에서 'acoustic' 대분류는 그대로 남고(세부는 unclassified), 1.1 에서는 process 로
    접혔다. 아무 축에도 없는 대분류는 어느 판이든 process 다."""
    for doc, expected in ((TAX_1_1, "process"), (taxonomy.load_taxonomy(), "acoustic")):
        under(doc)
        finding = {"mechanism": "acoustic", "mechanism_detail": "squeal"}
        narrative._normalize_mechanism(finding, "F1", [], [])
        assert (finding["mechanism"], finding["mechanism_detail"]) == (expected, "unclassified")
        other = {"mechanism": "hydraulic", "mechanism_detail": "squeal"}
        narrative._normalize_mechanism(other, "F2", [], [])
        assert other["mechanism"] == "process"


def test_every_1_1_alias_resolves_to_the_same_code_under_1_2(under):
    """1.1 의 별칭 색인(코드·세부·라벨·동의어) 전부가 1.2 에서도 같은 코드로 풀린다 — 새 낱말이 옛 낱말을 빼앗지 않는다. 새
    메커니즘의 코드·세부·라벨·낱말은 그 메커니즘으로 풀린다."""
    under(TAX_1_1)
    _by_code, old = narrative._mechanism_index()
    under(taxonomy.load_taxonomy())
    by_code, new = narrative._mechanism_index()
    assert {k: new.get(k) for k in old} == old
    for code in NEW_1_2:
        row = by_code[code]
        assert new[code] == new[row["detail"]] == new[row["label"]] == code
    assert {k: v for k, v in taxonomy.load_taxonomy()["synonyms"].items() if k not in TAX_1_1["synonyms"]} == {
        k: v for k, v in new.items() if k in taxonomy.load_taxonomy()["synonyms"] and k not in TAX_1_1["synonyms"]}
    assert all(v in NEW_1_2 for k, v in taxonomy.load_taxonomy()["synonyms"].items() if k not in TAX_1_1["synonyms"])


def _fixture_findings(tmp_path: Path) -> list[tuple[str, dict]]:
    """지금 리포의 risk_spec 픽스처 전부와 얼린 옛 원장 셋(v2 옛 타깃 · v3 · v4 — 패널·카드 대조 finding)의 finding."""
    out: list[tuple[str, dict]] = []
    for path in sorted((FIXTURES_DIR / "risk_spec").iterdir()):
        spec = narrative.parse_risk_spec(path.read_text(encoding="utf-8"))
        if isinstance(spec, dict):
            for key in ("findings", "gains"):
                out += [(f"{path.name}/{key}/{n}", f) for n, f in enumerate(spec.get(key) or ()) if isinstance(f, dict)]
    frozen = {"v2": legacy_build.LEGACY_DIR / legacy_build.DB_GZ, "v3": v3_build.V3_DIR / v3_build.DB_GZ,
              "v4": v4_build.V4_DIR / v4_build.DB_GZ}
    for name, gz_path in frozen.items():
        db = tmp_path / f"{name}.db"
        with gzip.open(gz_path, "rb") as src, open(db, "wb") as dst:
            shutil.copyfileobj(src, dst)
        con = sqlite3.connect(db)
        try:
            out += [(f"{name}/{fid}", json.loads(text)) for fid, text in con.execute(
                "SELECT finding_id, finding_json FROM rr_findings WHERE finding_json <> '' ORDER BY finding_id")]
        finally:
            con.close()
    return out


def test_findings_that_1_1_resolved_resolve_the_same_under_1_2(under, tmp_path):
    """동의어 충돌 없음 — risk_spec 픽스처와 얼린 옛 원장 셋의 finding 을 1.1·1.2 로 각각 정규화하면 1.1 에서 코드로 풀린 것은 1.2 에서도
    같은 코드다. 달라지는 것은 1.1 에서 unclassified 이던 것뿐이고 그 목록이 여기 적힌 것이다(지금 픽스처에는 없다)."""
    findings = _fixture_findings(tmp_path)
    assert len(findings) >= 20 and any(path.startswith("v4/") for path, _ in findings)

    def normalized(doc: dict) -> dict[str, tuple[str, str]]:
        under(doc)
        out = {}
        for path, finding in findings:
            item = copy.deepcopy(finding)
            narrative._normalize_mechanism(item, path, [], [])
            out[path] = (item["mechanism"], item["mechanism_detail"])
        return out

    old, new = normalized(TAX_1_1), normalized(taxonomy.load_taxonomy())
    resolved = {p: v for p, v in old.items() if v[1] != "unclassified"}
    assert resolved and {p: new[p] for p in resolved} == resolved
    assert {p: (old[p], new[p]) for p in old if old[p] != new[p]} == {}
