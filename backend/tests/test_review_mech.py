# 카드 대조 finding 의 메커니즘 — 앱 쪽(M2 #25 · 재설계 M3 S3-3): 실효 행의 mech · cells 대상의 미분류 쪼개기 · 영역 밖 표지 · 패널 대상 불변
"""엔진이 걸린 줄에 `mech`·`mech_free` 를 싣는다(cr-verdict-2, M3.md 4.4.3 — 엔진 몫은 E3-4). 앱은 finding 의 메커니즘을 실효 행(단독
재질의가 있으면 그것)의 코드로 읽고, 비거나 택소노미 밖(free)이면 cells 대상에서만 클러스터 키의 세부 자리를 자유 기술로 쪼갠다 —
서로 다른 지적이 process.unclassified 한 덩이로 뭉치지 않게. 배정표의 그 영역 밖 메커니즘이면 표지만 단다(판정은 그대로).

입력은 생산자다 — 대상·단위는 합성 쌍 → 실제 캡처·diff → 단위 빌드, 판정·finding 은 가짜 엔진(걸린 줄 mech 대본)을 꽂은 검토 루프가
쓴다(tests/synth/review_rig.py). 대본의 칸 모양은 M3.md 4.4.3 의 것이고, 엔진 계약 예제 result_verdict_mech.json 이 서면(E3-10) 그
모양에 맞춘다.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from app import expert_report, narrative, registry, routes, taxonomy, units
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.test_atoms import first_finding, make_ctx, make_finding, make_spec

OWNER = rig.OWNER
SEAL = rig.SEAL                      # 영역 mech
CARDS = {c["alias"]: c for c in fre.load("pack_ok.json")["cards"]}


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    return risk_store


def _rid(alias: str) -> str:
    return str(CARDS[alias]["record_id"])


def _run(store, key: str, *, verdicts: dict, mechs: dict | None = None, solo_mechs: dict | None = None) -> None:
    """SEAL 한 사람의 검토 잡을 가짜 엔진으로 끝까지 — 대본은 별칭으로 적고 (SEAL, record_id) 로 싣는다."""
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    fake = FakeReviewEngine(rig.packs())
    fake.verdicts = {_rid(a): v for a, v in verdicts.items()}
    fake.mechs = {(SEAL, _rid(a)): m for a, m in (mechs or {}).items()}
    fake.solo_mechs = {(SEAL, _rid(a)): m for a, m in (solo_mechs or {}).items()}
    rig.Rig(store, fake).finish(job_id)
    assert rig.state(store, job_id) == "completed", rig.job_row(store, job_id)


def _findings(store, key: str) -> list[dict]:
    rows = store.query("SELECT * FROM rr_findings WHERE target_key = ? AND source_kind = 'card_review' ORDER BY finding_id",
                       (key,))
    return [{**dict(r), "_json": json.loads(r["finding_json"])} for r in rows]


def _by_card(findings: list[dict]) -> dict[str, dict]:
    """별칭 → 그 카드가 든 finding."""
    alias_of = {str(c["record_id"]): a for a, c in CARDS.items()}
    return {alias_of[c["record_id"]]: f for f in findings for c in f["_json"].get("cards") or ()}


def _panel_flow_target(store) -> str:
    """패널 대상(flow='panels')에 카드 대조를 얹는 길 — 단위는 사람이 짓는다(M2 #3 의 얹기)."""
    synth = factories.make_diff_target(store, 40, open_target=False)
    key = routes.create_target(routes.TargetBody(kind="diff", ref_id=synth.diff_id, consent=True, flow="panels",
                                                 agents=[dict(r) for r in rig.ROSTER]),
                               ident=factories.ident(OWNER))["target_key"]
    units.build_units(store, key, built_by=OWNER)
    return key


# ---------------------------------------------------------------- 실효 행의 mech 가 finding 의 메커니즘이다
def test_a_flagged_line_mech_becomes_the_finding_mechanism_and_the_solo_line_wins(store):
    """걸린 카드의 finding 메커니즘은 실효 행의 코드다 — 단독 재질의 줄에 mech 가 있으면 그것(묶음 판정과 달라도), 없으면 묶음 판정
    줄의 것. 코드로 풀렸으니 클러스터 키는 지금 식(세부 그대로)이고 쪼갠 세부(key_detail)가 없다. 판정 행에 받은 mech 가 남는다."""
    key = rig.target(store)
    _run(store, key, verdicts={"K01": ("yes", "FAIL"), "K02": ("yes", "WARNING")},
         mechs={"K01": ("interface.seal_compression", ""), "K02": ("mechanical.bending", "")},
         solo_mechs={"K02": ("interface.ingress_path", "")})
    by_card = _by_card(_findings(store, key))
    for alias, (mech, detail) in {"K01": ("interface", "seal_compression"), "K02": ("interface", "ingress_path")}.items():
        finding = by_card[alias]
        assert (finding["mechanism"], finding["mechanism_detail"]) == (mech, detail), alias
        assert finding["cluster_key"] == narrative.cluster_key_of(mech, detail, finding["subject_key"],
                                                                  finding["change_kind"])
        assert "key_detail" not in finding["_json"]
    stored = {(r["variant"], r["record_id"]): r["mech"] for r in store.query(
        "SELECT variant, record_id, mech FROM rr_card_verdicts WHERE target_key = ? AND record_id = ?", (key, _rid("K02")))}
    assert stored[("fwd", _rid("K02"))] == "mechanical.bending" and stored[("solo", _rid("K02"))] == "interface.ingress_path"


# ---------------------------------------------------------------- 미분류 쪼개기 — cells 대상만
UNCLASSIFIED_SCRIPT = {
    "verdicts": {a: ("yes", "FAIL") for a in ("K01", "K02", "K03", "K04", "K05")},
    "mechs": {"K01": ("free", "계면 박리"), "K02": ("free", " 계면박리!! "), "K03": ("free", "접착 들뜸"), "K05": ("", "")},
}


def test_unclassified_card_findings_split_by_free_text_or_card_on_a_cells_target(store):
    """cells 대상 — 자유 기술이 같으면(NFKC·소문자·공백·구두점 제거 뒤) 한 클러스터, 다르면 둘이다. 메커니즘도 자유 기술도 없으면 그
    카드로 갈린다('card~' + card_id, card_id 가 비면 record_id). mechanism_detail 칸은 그대로 'unclassified' 이고 쪼갠 세부는 finding 의
    key_detail 에만 있다."""
    key = rig.target(store)
    _run(store, key, **UNCLASSIFIED_SCRIPT)
    findings = _findings(store, key)
    by_card = _by_card(findings)
    assert by_card["K01"]["finding_id"] == by_card["K02"]["finding_id"]          # 같은 자유 기술 → 한 finding
    expected = {"K01": "unclassified~계면박리", "K03": "unclassified~접착들뜸",
                "K04": f"unclassified~card~{CARDS['K04']['card_id']}", "K05": f"unclassified~card~{_rid('K05')}"}
    assert CARDS["K05"]["card_id"] == "" and CARDS["K04"]["card_id"]
    for alias, detail in expected.items():
        finding = by_card[alias]
        assert (finding["mechanism"], finding["mechanism_detail"]) == ("process", "unclassified"), alias
        assert finding["_json"].get("key_detail") == detail, alias
        assert finding["cluster_key"] == narrative.cluster_key_of("process", detail, finding["subject_key"],
                                                                  finding["change_kind"]), alias
    assert len({by_card[a]["cluster_key"] for a in expected}) == 4


def test_the_same_script_on_a_panel_flow_target_keeps_one_unclassified_cluster_and_todays_key(store):
    """패널 대상(flow='panels')에 얹은 카드 대조는 쪼개지 않는다 — 같은 대본의 미분류 넷이 지금처럼 한 finding 으로 접히고, 클러스터
    키가 지금 식(process|unclassified|주체|변경 종류)이며 key_detail 칸이 없다(D-24 — 패널 대상 바이트 불변)."""
    key = _panel_flow_target(store)
    _run(store, key, **UNCLASSIFIED_SCRIPT)
    findings = _findings(store, key)
    by_card = _by_card(findings)
    assert {by_card[a]["finding_id"] for a in ("K01", "K02", "K03", "K04", "K05")} == {by_card["K01"]["finding_id"]}
    finding = by_card["K01"]
    assert finding["cluster_key"] == narrative.cluster_key_of("process", "unclassified", finding["subject_key"],
                                                              finding["change_kind"])
    assert all("key_detail" not in f["_json"] for f in findings)


def test_the_normalizer_splits_only_when_the_scope_is_a_cells_target():
    """정규화 하나로 본다 — 같은 미분류 finding 이 패널 스코프(기본)에서는 지금 키, cells 스코프에서는 자유 기술로 쪼갠 키다. 카드
    대체 열쇠(_free_key_fallback)는 쓰고 지운다(저장되지 않는다). 코드로 풀린 finding 은 어느 스코프든 같은 키다."""
    ctx = make_ctx()
    raw = make_finding(mechanism="optical", mechanism_detail="lens glare", mechanism_free="Lens Glare — 렌즈 반사")
    panel = first_finding(make_spec(findings=[raw]), ctx)
    cells = first_finding(make_spec(findings=[raw]), dataclasses.replace(ctx, flow="cells"))
    assert (panel["mechanism"], panel["mechanism_detail"]) == (cells["mechanism"], cells["mechanism_detail"]) == (
        "optical", "unclassified")
    assert panel["cluster_key"] == narrative.cluster_key_of("optical", "unclassified", panel["subject_key"],
                                                            panel["change_kind"]) and "key_detail" not in panel
    assert cells.get("key_detail") == "unclassified~" + narrative.free_key_of(cells["mechanism_free"])
    assert cells["cluster_key"] != panel["cluster_key"]
    seeded = {**raw, "mechanism_free": "", narrative.FREE_KEY_FALLBACK: "card~X-1"}
    split = first_finding(make_spec(findings=[seeded]), dataclasses.replace(ctx, flow="cells"))
    plain = first_finding(make_spec(findings=[seeded]), ctx)
    assert narrative.FREE_KEY_FALLBACK not in split and narrative.FREE_KEY_FALLBACK not in plain
    assert split["mechanism_free"] == "optical.lens glare"          # 정규화가 원문을 적는다 — 그 원문으로 쪼갠다
    known = make_finding(mechanism="mechanical", mechanism_detail="bending")
    assert first_finding(make_spec(findings=[known]), ctx)["cluster_key"] == first_finding(
        make_spec(findings=[known]), dataclasses.replace(ctx, flow="cells"))["cluster_key"]


def test_the_free_key_is_nfkc_lowercase_without_spaces_or_punctuation_and_24_chars():
    assert narrative.free_key_of("  Ｃｏｍｐｒｅｓｓｉｏｎ  SET!! (gasket)") == "compressionsetgasket"
    assert narrative.free_key_of("계면 박리.") == narrative.free_key_of("계면박리") == "계면박리"
    assert narrative.free_key_of("a" * 30) == "a" * 24 and narrative.free_key_of(None) == ""
    assert narrative.free_key_of("±5% 공차~") == "±5공차~"          # 기호(S 범주 — ±·~)는 남고 구두점(P 범주 — %)은 빠진다


def test_the_family_key_of_a_split_cluster_uses_the_split_detail(store):
    """family_key 도 같은 규칙이다(P-17-6) — 쪼갠 클러스터의 대표가 key_detail 을 가지면 family_key 의 세부 자리가 그것이라, 근접 중복
    스캔이 갈라 놓은 미분류를 다시 묶지 않는다. 병합(S3-4)이 서기 전이라 검토 루프가 만든 finding 행을 등록부의 클러스터 병합에 바로
    넣는다. 쪼개지 않은 finding(코드로 풀림)은 지금 식이다."""
    key = rig.target(store)
    _run(store, key, verdicts={"K01": ("yes", "FAIL"), "K03": ("yes", "FAIL")},
         mechs={"K01": ("free", "계면 박리"), "K03": ("mechanical.bending", "")})
    by_card = _by_card(_findings(store, key))
    split, known = by_card["K01"], by_card["K03"]
    row = registry._merge_cluster(key, split["cluster_key"], split["cluster_key"], "risk", [split])
    assert row["family_key"] == registry.family_key_of("process", "unclassified~계면박리", split["change_kind"])
    assert row["family_key"] != registry.family_key_of("process", "unclassified", split["change_kind"])
    plain = registry._merge_cluster(key, known["cluster_key"], known["cluster_key"], "risk", [known])
    assert plain["family_key"] == registry.family_key_of("mechanical", "bending", known["change_kind"])


# ---------------------------------------------------------------- 영역 밖 메커니즘 — 표지만
def test_an_out_of_domain_mechanism_is_flagged_and_counted_without_changing_the_verdict(store):
    """SEAL(영역 mech)이 광학 이물(소유 cam · 관련 sh·rel·xd)을 달면 finding 에 mech_out_of_domain 표지가 서고, 기구 소유 메커니즘
    (실링 압축량) · 기구가 관련인 메커니즘(SAR — 소유 rf · 관련 mech·sh) · 미분류는 서지 않는다. 판정·심각도는 hold 정책 그대로다
    (표지가 바꾸지 않는다). 전문가 보고서의 품질 칸이 걸린 카드 수 · mech 를 달지 않은 수 · 영역 밖 finding 수를 센다(대본은 단위마다
    같다 — 수는 단위 수의 배수다)."""
    key = rig.target(store)
    _run(store, key, verdicts={"K01": ("yes", "FAIL"), "K02": ("yes", "FAIL"), "K03": ("yes", "FAIL"),
                               "K04": ("yes", "WARNING")},
         mechs={"K01": ("optical.contamination", ""), "K02": ("rf.sar", ""), "K03": ("interface.seal_compression", "")})
    by_card = _by_card(_findings(store, key))
    owners = taxonomy.mech_owners()
    assert "mech" not in owners["optical.contamination"]["owners"] + owners["optical.contamination"]["related"]
    assert "mech" in owners["rf.sar"]["related"] and "mech" not in owners["rf.sar"]["owners"]
    assert by_card["K01"]["_json"].get("flags") == [expert_report.MECH_OUT_OF_DOMAIN]
    assert [a for a in ("K02", "K03", "K04") if "flags" in by_card[a]["_json"]] == []
    for alias in ("K01", "K02", "K03"):
        assert (by_card[alias]["severity"], by_card[alias]["judgement"]) == ("중대", "WARNING"), alias  # hold 정책
    report = expert_report.build_report(store, key, SEAL)
    n = store.query_one("SELECT COUNT(*) AS n FROM rr_review_cells WHERE target_key = ? AND agent_key = ? AND state = 'reviewed'",
                        (key, SEAL))["n"]
    assert n >= 2 and report["quality"]["mech"] == {"flagged": 4 * n, "missing": n, "out_of_domain": n}
    flags = {f["claim_uid"]: f.get("flags") for f in report["findings"]}
    assert flags[by_card["K01"]["claim_uid"]] == [expert_report.MECH_OUT_OF_DOMAIN]
    assert flags[by_card["K03"]["claim_uid"]] == []
