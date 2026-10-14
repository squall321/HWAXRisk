# 택소노미 1.2(메커니즘 14종)와 메커니즘 → 영역 배정표(재설계 M3 S3-2) — 불변식 · 승인 문 · 읽는 함수 · 1.1 별칭 보존
"""배정표(`assets/mech-owners.v1.json`)는 사람이 훑고 승인하는 정책이고(D-35 — 초안은 review_status draft), 거르기의 코드 신호·쟁점 패널의
인접 석·카드 대조 finding 의 영역 밖 표지가 같은 표를 읽는다. 승인 전에는 코드 신호가 전 영역 '모름' 이라 거르기가 일어나지 않는다.
1.1 에서 이미 코드로 풀리던 낱말·finding 은 1.2 에서도 같은 코드다 — 비교 기준은 얼린 1.1 자산(`tests/fixtures/taxonomy/taxonomy.1.1.json`,
HWAXRisk 3aea93b 의 것)이다.
"""
from __future__ import annotations

import copy
import gzip
import json
import shutil
import sqlite3
from collections import Counter
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


# ---------------------------------------------------------------- 메커니즘 → 영역 배정표
def _owners_doc() -> dict:
    return taxonomy.load_json(taxonomy.MECH_OWNERS_ASSET)


def test_the_owner_table_covers_every_active_code_once_with_known_domains_and_no_overlap():
    """불변식 넷(M3.md 4.9) — 택소노미 active 코드마다 정확히 한 행 · 소유 1개 이상, 영역 이름은 택소노미 영역 15개 안, 15개 영역이 전부
    어느 행엔가 나온다(닿지 않는 영역은 코드 신호가 늘 '무관' 이라 훑기 하나로 걸러진다 — 두 신호 규칙이 무너진다), 한 행에서 소유와
    관련이 겹치지 않는다. 행 차례는 택소노미 축 차례다."""
    doc = _owners_doc()
    rows = doc["rows"]
    domains = set(_domains())
    assert len(domains) == 15
    assert [r["code"] for r in rows] == _active(taxonomy.load_taxonomy())
    for row in rows:
        assert set(row) == {"code", "owners", "related"}, row["code"]
        assert row["owners"] and len(set(row["owners"])) == len(row["owners"]), row["code"]
        assert len(set(row["related"])) == len(row["related"]), row["code"]
        assert not set(row["owners"]) & set(row["related"]), row["code"]
        assert set(row["owners"]) | set(row["related"]) <= domains, row["code"]
    assert {d for r in rows for d in r["owners"] + r["related"]} == domains
    assert doc["mech_owners_version"] == "1.0"
    assert doc["taxonomy_version"] == taxonomy.load_taxonomy()["taxonomy_version"]


def test_the_review_status_is_a_gate_value_with_a_reviewer_once_approved():
    """review_status 는 draft · approved 둘 중 하나다. 승인 커밋은 review_status·reviewed_by·reviewed_at 을 함께 고친다(D-35 — 그 전에는
    둘 다 비어 있다)."""
    doc = _owners_doc()
    assert doc["review_status"] in ("draft", taxonomy.APPROVED)
    if doc["review_status"] == taxonomy.APPROVED:
        assert doc["reviewed_by"] and doc["reviewed_at"]
    else:
        assert doc["reviewed_by"] is None and doc["reviewed_at"] is None


def test_the_draft_is_the_table_handed_to_the_user():
    """초안(review_status draft)은 m3-synthesis 3.4 의 52행이다 — 그 문서가 '훑을 때 봐 주면 좋은 셋' 으로 적은 수가 이 자산의 수와
    같다(xd 24개 — 소유 11 · 관련 13, mech 41개, rel 27개, mem·std 는 관련으로만, 재질 계열 넷의 첫 소유가 rel — P-15). 사용자가 표를
    고쳐 승인하면 승인본이 정본이라 초안의 수는 더 보지 않고 승인한 사람·때가 적혔는지만 본다(건너뛰지 않는다 — 건너뜀 예산)."""
    doc = _owners_doc()
    if doc["review_status"] != "draft":
        assert doc["review_status"] == taxonomy.APPROVED and doc["reviewed_by"] and doc["reviewed_at"]
        return
    rows = doc["rows"]
    owners = Counter(d for r in rows for d in r["owners"])
    related = Counter(d for r in rows for d in r["related"])
    assert len(rows) == 52
    assert (owners["xd"], related["xd"]) == (11, 13)
    assert owners["mech"] + related["mech"] == 41 and owners["rel"] + related["rel"] == 27
    assert owners["mem"] == owners["std"] == 0 and related["mem"] == related["std"] == 5
    first = {r["code"]: r["owners"][0] for r in rows}
    assert {c: first[c] for c in ("material.creep", "material.moisture", "material.corrosion",
                                  "material.adhesive_aging")} == dict.fromkeys(
        ("material.creep", "material.moisture", "material.corrosion", "material.adhesive_aging"), "rel")
    assert {c: first[c] for c in NEW_1_2} == {
        "optical.alignment": "cam", "optical.stray_light": "cam", "optical.contamination": "cam",
        "acoustic.leak": "sh", "acoustic.resonance": "sh", "acoustic.port_block": "sh", "rf.detune": "rf",
        "rf.efficiency": "rf", "rf.isolation": "rf", "rf.sar": "rf", "interface.seal_compression": "mech",
        "interface.ingress_path": "mech", "electrical.esd": "rel", "electrical.magnetic_interference": "sh"}


def test_the_read_functions_follow_the_table():
    table = taxonomy.mech_owners()
    assert table["thermal.cte_mismatch"] == {"owners": ("rel", "material"), "related": ("pcb", "mech", "sim", "disp")}
    assert list(table) == [r["code"] for r in _owners_doc()["rows"]]
    roles = taxonomy.domains_for(["thermal.cte_mismatch", "mechanical.bending", "no.such_code", "no.such_code"])
    assert roles["mech"] == "owner"                                      # 한 코드의 관련 · 다른 코드의 소유 → 소유
    assert roles["rel"] == "owner" and roles["disp"] == "related" and "xd" not in roles
    assert roles.unknown == ("no.such_code",)
    assert taxonomy.domains_for([]) == {} and taxonomy.domains_for([]).unknown == ()
    mem = taxonomy.mechanisms_of("mem")
    assert mem["owner"] == [] and mem["related"] == ["thermal.solder_fatigue", "electrical.net", "electrical.si_pi",
                                                     "electrical.pad_lift", "process.solder"]
    sh = taxonomy.mechanisms_of("sh")
    assert sh["owner"] == ["acoustic.leak", "acoustic.resonance", "acoustic.port_block",
                           "electrical.magnetic_interference"]
    for domain in _domains():
        split = taxonomy.mechanisms_of(domain)
        assert split["owner"] or split["related"], domain
        assert not set(split["owner"]) & set(split["related"]), domain
    meta = taxonomy.mech_owners_meta()
    assert set(meta) == {"version", "taxonomy_version", "review_status", "reviewed_by", "reviewed_at", "approved"}
    assert meta["approved"] is (meta["review_status"] == taxonomy.APPROVED)


def _approved(monkeypatch, **changes) -> None:
    """배정표를 승인본으로 바꿔 끼운다(시험 안에서만 — 표의 행은 그대로)."""
    real = taxonomy.load_json
    doc = {**copy.deepcopy(real(taxonomy.MECH_OWNERS_ASSET)), "review_status": taxonomy.APPROVED,
           "reviewed_by": "reviewer@example.com", "reviewed_at": "2026-10-14", **changes}
    monkeypatch.setattr(taxonomy, "load_json", lambda name: doc if name == taxonomy.MECH_OWNERS_ASSET else real(name))


def test_before_approval_the_code_signal_is_unknown_for_every_domain(monkeypatch):
    """승인 문(#40) — 배정표가 승인 전이면 domains_for 의 결과에 approved: false 가 실리고, 코드 신호는 소유 영역까지 전 영역 '모름' 이다
    (거르기가 일어나지 않는다). 표 자체(소유·관련)는 승인과 상관없이 그대로 준다 — 인접 석·영역 밖 표지는 표를 쓴다."""
    _approved(monkeypatch, review_status="draft", reviewed_by=None, reviewed_at=None)
    roles = taxonomy.domains_for(["mechanical.bending"])
    assert roles.approved is False and taxonomy.mech_owners_meta()["approved"] is False
    assert roles["mech"] == "owner"
    assert {d: roles.signal(d) for d in _domains()} == dict.fromkeys(_domains(), "unknown")
    assert {d: taxonomy.domains_for([]).signal(d) for d in _domains()} == dict.fromkeys(_domains(), "unknown")


def test_after_approval_the_code_signal_reads_the_table(monkeypatch):
    """승인 뒤 — 소유 ∪ 관련은 related, 그 밖은 unrelated, 표에 없는 코드가 하나라도 섞이면 나머지는 unknown, 메커니즘이 없으면
    (설계 변경이 아니다) 전부 unrelated 다."""
    _approved(monkeypatch)
    roles = taxonomy.domains_for(["mechanical.bending"])
    assert roles.approved is True and taxonomy.mech_owners_meta()["approved"] is True
    near = {"mech", "sim", "disp", "pcb", "rel", "passive"}
    assert {d: roles.signal(d) for d in _domains()} == {d: "related" if d in near else "unrelated" for d in _domains()}
    mixed = taxonomy.domains_for(["mechanical.bending", "no.such_code"])
    assert {d: mixed.signal(d) for d in _domains()} == {d: "related" if d in near else "unknown" for d in _domains()}
    assert {d: taxonomy.domains_for([]).signal(d) for d in _domains()} == dict.fromkeys(_domains(), "unrelated")


def test_the_owner_table_is_a_listed_vocab_asset():
    """`/meta/vocab` 이 배정표의 판을 보인다. 목록의 자산은 전부 파일이 있다 — 셀 꾸러미가 change-routing 을 더할 때 파일을 빠뜨리면
    여기서 붉다."""
    assert "mech-owners" in taxonomy.VOCAB_ASSETS
    index = {item["name"]: item for item in taxonomy.vocab_index()}
    assert index["mech-owners"]["version"] == "1.0"
    assert [name for name, item in index.items() if not item["present"] or item.get("error")] == []
