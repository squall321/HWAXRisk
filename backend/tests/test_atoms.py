# narrative.py 원자 시험 — risk_spec 정규화 10단계·원자 펼치기·subject_key/cluster_key·cites 검증·facet 8 채움(plan §4.2~§4.6)
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from app.narrative import (
    FACETS,
    FEATURE_SNAPSHOT_PER_REF,
    NORMALIZE_VERSION,
    SpecContext,
    cluster_key_of,
    evidence_grade_from_cites,
    normalize_risk_spec,
    resolve_cites,
    resolve_subject,
)
from tests.conftest import FIXTURES_DIR

PANEL_ID = "pnl00000000000000000000000000001"


def _load(rel: str) -> dict:
    return json.loads((FIXTURES_DIR / rel).read_text(encoding="utf-8"))


# 기본 스코프는 MCAD 단독 IR 이다 — mcad+dyna IR 은 파트와 PID 가 같은 name_norm 을 써서 name: 참조가 다의가 된다.
IR = _load("rr_ir/valid_mcad_only.json")
IR_WITH_DYNA = _load("rr_ir/valid_mcad_dyna.json")
DIFF = _load("rr_diff/valid_pair_kind.json")
STATE = _load("rr_state/valid_clean.json")

# 픽스처 IR 의 실제 값(추측 금지 — 아래 시험의 기대값은 전부 여기서 온다).
CK_PLATE_1 = "ck:01f70db1e74f"
CK_PLATE_2 = "ck:860cf8b0d3d0"
EDGE_TIED = "e:f1dabe4da27f"
CID_GAP = "c:ec0f586d4d8b"
QUOTE_GAP = "PLATE_1↔PLATE_2 min_gap 0.000→0.018 mm"
ASM_PREFIX = "a_stack/stack_asm"


def _flat(obj: dict) -> dict:
    """rr_ir 의 nodes/edges 를 SpecContext 가 보는 평평한 형태로 편다(_row_to_node 와 같은 규칙)."""
    out = {k: v for k, v in obj.items() if k != "attrs"}
    out.update(obj.get("attrs") or {})
    return out


def _ir_view(doc: dict) -> dict:
    return {
        "nodes": {n["nid"]: _flat(n) for n in doc["nodes"]},
        "edges": {e["eid"]: _flat(e) for e in doc["edges"]},
        "dims_named": {d["name"]: d for d in doc["dims_named"]},
        "warnings": doc.get("warnings") or [],
    }


def make_ctx(**overrides) -> SpecContext:
    """픽스처 IR·diff·state 를 스코프로 갖는 SpecContext."""
    kwargs = dict(
        panel_id=PANEL_ID,
        target_key=f"diff:{DIFF['diff_id']}",
        kind="diff",
        snapshot_ids=(IR["snapshot_id"], DIFF["target"]["snapshot_id"]),
        diff_id=DIFF["diff_id"],
        ir_hash=DIFF["target"]["ir_hash"],
        irs={IR["snapshot_id"]: _ir_view(IR)},
        states={IR["snapshot_id"]: STATE},
        diff=DIFF,
        rollup_prefixes={
            row["path_prefix"]: row["path_prefix"]
            for row in (IR.get("rollups") or {}).get("by_assembly") or []
        },
    )
    kwargs.update(overrides)
    return SpecContext(**kwargs)


def make_finding(**overrides) -> dict:
    finding = {
        "id": "F1",
        "direction": "risk",
        "domain": "mech",
        "mechanism": "interface",
        "mechanism_detail": "clearance",
        "change_kind": "dimension",
        "subject": {"ckeys": [], "names": ["PLATE_1", "PLATE_2"]},
        "trigger_condition": "load.drop",
        "trigger_text": "코너 낙하",
        "severity": "중대",
        "judgement": "WARNING",
        "detectability": {"level": "sim-detectable", "tool": "list_interfaces"},
        "evidence_grade": "도구예측",
        "precedent": "none",
        "cites": [{"ref": CID_GAP, "quote": QUOTE_GAP}],
        "tool_calls": [],
        "claim": "두 판 사이 접합이 떨어져 닿음으로 바뀌었다.",
        "warrant": "엣지 파라메트릭 항목이 그 변화를 담고 있다.",
        "resolving_check": {"kind": "sim", "ref": "재해석"},
        "owner_domain": "mech",
        "raised_by": ["mech-housing-structure"],
        "contested_by": [],
        "contest_note": "",
        "status": "open",
    }
    finding.update(overrides)
    return finding


def make_spec(**overrides) -> dict:
    spec = {
        "schema": "risk_spec",
        "version": "1.0",
        "taxonomy_version": "1.0",
        "scope": {"kind": "diff", "target_key": f"diff:{DIFF['diff_id']}"},
        "findings": [make_finding()],
        "gains": [],
        "cross_domain": [],
        "open_items": [],
        "character": {"one_liner": "", "facets": []},
        "coverage": {},
        "verdict": "conditional",
        "verdict_conditions": [],
        "evidence_profile": {},
    }
    spec.update(overrides)
    return spec


def first_finding(spec: dict, ctx: SpecContext | None = None) -> dict:
    return normalize_risk_spec(spec, ctx or make_ctx())["spec"]["findings"][0]


@pytest.fixture(scope="module")
def ctx() -> SpecContext:
    return make_ctx()


# ================================================================ cluster_key(plan §4.3.2)

def test_cluster_key_matches_the_documented_formula():
    payload = "interface|clearance|ck:aa|dimension"
    assert cluster_key_of("interface", "clearance", "ck:aa", "dimension") == (
        hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    )
    assert len(cluster_key_of("a", "b", "c", "d")) == 12


@pytest.mark.parametrize("changed", [
    {"mechanism": "process"},
    {"mechanism_detail": "tolerance"},
    {"subject_key": "ck:bb"},
    {"change_kind": "topology"},
])
def test_cluster_key_changes_with_each_key_component(changed):
    base = {"mechanism": "interface", "mechanism_detail": "clearance",
            "subject_key": "ck:aa", "change_kind": "dimension"}
    assert cluster_key_of(**base) != cluster_key_of(**{**base, **changed})


def test_cluster_key_ignores_domain_seat_and_cites(ctx):
    """도메인·좌석·ir_refs 는 키에 들어가지 않는다(crit_19)."""
    a = first_finding(make_spec(), ctx)
    b = first_finding(make_spec(findings=[make_finding(
        id="F7",
        domain="disp",
        raised_by=["disp-utg-cover"],
        cites=[{"ref": "sig:counts.leaf", "quote": "leaf=3"}],
        claim="접합이 떨어졌다.",
        warrant="",
    )]), ctx)
    assert a["cluster_key"] == b["cluster_key"]


def test_cluster_key_is_stable_across_subject_name_order(ctx):
    a = first_finding(make_spec(), ctx)
    b = first_finding(make_spec(findings=[make_finding(
        subject={"ckeys": [], "names": ["PLATE_2", "PLATE_1"]})]), ctx)
    assert a["subject_key"] == b["subject_key"] == f"{CK_PLATE_1}|{CK_PLATE_2}"
    assert a["cluster_key"] == b["cluster_key"]


# ================================================================ subject_key(plan §4.2.2 4단계 · §4.3.2)

def test_subject_names_resolve_to_ckeys(ctx):
    finding = first_finding(make_spec(), ctx)
    assert finding["subject"]["ckeys"] == [CK_PLATE_1, CK_PLATE_2]
    assert finding["subject_unresolved"] is False


def test_single_part_subject_key_is_the_ckey(ctx):
    finding = first_finding(make_spec(findings=[make_finding(subject={"names": ["PLATE_1"]})]), ctx)
    assert finding["subject_key"] == CK_PLATE_1


def test_named_dimension_subject_key(ctx):
    got = resolve_subject({"names": ["dim:plate_gap"]}, ctx)
    assert got["subject_key"] == "dim:plate_gap"
    assert got["unresolved"] is False


def test_assembly_subject_key_from_rollup_prefix(ctx):
    by_path = resolve_subject({"names": [ASM_PREFIX]}, ctx)
    by_prefix = resolve_subject({"names": [f"asm:{ASM_PREFIX}"]}, ctx)
    assert by_path["subject_key"] == by_prefix["subject_key"] == f"asm:{ASM_PREFIX}"


def test_assembly_key_outside_rollups_is_unresolved(ctx):
    got = resolve_subject({"asm_key": "없는/경로"}, ctx)
    assert got["unresolved"] is True and got["subject_key"] == ""
    assert got["warnings"]


def test_unresolved_subject_still_clusters_with_empty_key(ctx):
    finding = first_finding(make_spec(findings=[make_finding(subject={"names": ["NO_SUCH_PART"]})]), ctx)
    assert finding["subject_unresolved"] is True
    assert finding["subject_key"] == ""
    assert finding["cluster_key"] == cluster_key_of("interface", "clearance", "", "dimension")


def test_ckey_outside_scope_is_flagged(risk_store):
    """스코프를 볼 수 있을 때(store 연결)만 없는 ckey 를 경고한다."""
    scoped = make_ctx(store=risk_store)
    out = normalize_risk_spec(make_spec(findings=[make_finding(
        subject={"ckeys": ["ck:deadbeef0000"], "names": []})]), scoped)
    assert any("스코프에 없는 ckey" in w for w in out["parse_warnings"])


# ================================================================ cites 검증(plan §4.4)

def test_resolved_cite_is_clean(ctx):
    finding = first_finding(make_spec(), ctx)
    assert finding["dangling"] == [] and finding["quote_mismatch"] == []


def test_missing_reference_is_dangling_but_kept(ctx):
    """없는 참조는 버리지 않고 dangling 으로 보존한다."""
    cite = {"ref": "c:000000000000", "quote": "없는 항목"}
    out = normalize_risk_spec(make_spec(findings=[make_finding(cites=[cite])]), ctx)
    finding = out["spec"]["findings"][0]
    assert finding["dangling"] == ["c:000000000000"]
    assert finding["cites"] == [cite]
    assert finding["evidence_grade"] == "경험칙"


def test_fabricated_quote_is_quote_mismatch(ctx):
    """지어낸 인용 — ref 는 실재해도 quote 가 정규 표기의 부분열이 아니면 등급 기여가 사라진다."""
    finding = first_finding(make_spec(findings=[make_finding(
        cites=[{"ref": CID_GAP, "quote": "PLATE_1↔PLATE_2 min_gap 0.000→9.999 mm"}])]), ctx)
    assert finding["quote_mismatch"] == [CID_GAP]
    assert finding["dangling"] == []
    assert finding["evidence_grade"] == "경험칙"


def test_claim_number_absent_from_quotes_is_quote_mismatch(ctx):
    """claim 의 수치 토큰이 quote 안에 축어로 없으면 위반이다(§4.4.2 (1))."""
    ok = first_finding(make_spec(findings=[make_finding(claim="간극이 0.018 mm 다.", warrant="")]), ctx)
    assert ok["unquoted_numbers"] == [] and ok["quote_mismatch"] == []
    bad = first_finding(make_spec(findings=[make_finding(claim="간극이 0.777 mm 다.", warrant="")]), ctx)
    assert bad["unquoted_numbers"] == ["0.777"]
    assert bad["quote_mismatch"] == [CID_GAP]


def test_precedent_reference_must_be_in_the_brief(ctx):
    """브리프에 실리지 않은 reg: 는 not_in_brief — 지어낸 선례를 막는다."""
    good, bad = "reg:diff:aaa#112233445566", "reg:diff:zzz#999999999999"
    scoped = make_ctx(brief_known=True, brief_refs=frozenset({good}))
    finding = first_finding(make_spec(findings=[make_finding(
        cites=[{"ref": good, "quote": ""}, {"ref": bad, "quote": ""}])]), scoped)
    assert finding["dangling"] == [bad]


def test_unverifiable_channel_is_not_a_downgrade(ctx):
    """card:·rpt: 채널이 없으면 dangling 이 아니라 미검증으로만 남는다."""
    finding = first_finding(make_spec(findings=[make_finding(
        cites=[{"ref": "card:rec1", "quote": ""}])]), ctx)
    assert finding["dangling"] == []
    assert finding["unverified_refs"] == ["card:rec1"]


def test_name_reference_resolves_to_an_edge(ctx):
    resolved = resolve_cites([{"ref": "name:PLATE_1|PLATE_2", "quote": ""}], ctx)
    assert resolved["dangling"] == []
    assert resolved["resolved_refs"] == [EDGE_TIED]
    missing = resolve_cites([{"ref": "name:PLATE_1|NO_SUCH_PART", "quote": ""}], ctx)
    assert missing["dangling"] == ["name:PLATE_1|NO_SUCH_PART"]


def test_ambiguous_name_reference_is_dangling():
    """MCAD 파트와 Dyna PID 가 같은 이름을 쓰면 name: 은 해석하지 않는다."""
    scoped = make_ctx(irs={IR_WITH_DYNA["snapshot_id"]: _ir_view(IR_WITH_DYNA)})
    resolved = resolve_cites([{"ref": "name:PLATE_1|PLATE_2", "quote": ""}], scoped)
    assert resolved["dangling"] == ["name:PLATE_1|PLATE_2"]
    assert [row["dangling_reason"] for row in resolved["cites"]] == ["name_ambiguous"]


@pytest.mark.parametrize("ref,expected", [
    ("inc:obj1", "측정"),
    ("rpt:RPT1", "측정"),
    ("rpt:OTHER", "도구예측"),
    ("card:rec1", "문헌·규격"),
    (CID_GAP, "도구예측"),
    ("sig:counts.leaf", "도구예측"),
])
def test_evidence_grade_table(ref, expected):
    external = make_ctx(external_check=lambda _ref: True, test_run_reports=frozenset({"RPT1"}))
    resolved = resolve_cites([{"ref": ref, "quote": ""}], external)
    assert evidence_grade_from_cites(resolved, external) == expected


def test_evidence_grade_without_usable_cites_is_heuristic(ctx):
    assert evidence_grade_from_cites(resolve_cites([], ctx), ctx) == "경험칙"
    dangling = resolve_cites([{"ref": "c:000000000000", "quote": "x"}], ctx)
    assert evidence_grade_from_cites(dangling, ctx) == "경험칙"


@pytest.mark.parametrize("marker", ["e:3", "[e:3]", "e:3|E3", "[e:3|E3]", "[e:2|E0c]", "[e:12|M]"])
def test_engine_evidence_marker_is_never_read_as_an_ir_edge(ctx, marker):
    """엔진은 브리프 항목 줄 머리에 `[e:N]`(키가 가면 `[e:N|E3]`)을 찍고 좌석에게 그 표지를 적으라 한다.

    이 앱에서 `e:` 는 IR 엣지(`e:<12hex>`)라 접두가 겹친다 — 갈리는 것은 모양뿐이다(항목 번호는 12자리
    16진수가 못 된다). 표지를 엣지로 읽으면 IR 인용률과 도구예측 등급이 근거 없이 오른다.
    """
    from app import narrative
    from app.common import parse_ref

    assert parse_ref(marker) is None
    # 좌석 발언 — 표지는 인용으로 세지 않고, 같은 문장의 진짜 엣지 참조는 그대로 읽는다.
    assert narrative.cited_refs_in(f"간극이 좁다 {marker} 근거는 [{EDGE_TIED}] 다") == [EDGE_TIED]
    # 표지의 번호가 claim 의 수치 토큰으로 잡히면 quote 에 없는 숫자로 몰려 quote_mismatch 가 된다.
    assert narrative._number_tokens(f"min_gap 0.018 mm 다 {marker}") == ["0.018"]

    # risk_spec cites 에 적힌 표지 — 버리지 않고 행으로 보존하되 등급에도 dangling 에도 세지 않는다.
    # 지어낸 참조가 아니라 엔진이 적으라고 시킨 번호라서다(모양이 틀린 참조 `x:1` 은 여전히 dangling 이다).
    alone = resolve_cites([{"ref": marker, "quote": ""}], ctx)
    assert [(row["ref_type"], row["ok"], row["dangling_reason"]) for row in alone["cites"]] == \
        [("unknown", False, narrative.ENGINE_MARKER)]
    assert alone["dangling"] == []
    assert evidence_grade_from_cites(alone, ctx) == "경험칙"
    beside = resolve_cites([{"ref": marker, "quote": ""}, {"ref": EDGE_TIED, "quote": ""},
                            {"ref": "x:1", "quote": ""}], ctx)
    assert beside["dangling"] == ["x:1"] and beside["resolved_refs"] == [EDGE_TIED]
    assert evidence_grade_from_cites(beside, ctx) == "도구예측"


def test_claimed_grade_is_lowered_but_never_raised(ctx):
    higher = first_finding(make_spec(findings=[make_finding(evidence_grade="측정")]), ctx)
    assert higher["evidence_grade"] == "도구예측"
    assert higher["evidence_grade_claimed"] == "측정"
    lower = first_finding(make_spec(findings=[make_finding(evidence_grade="경험칙")]), ctx)
    assert lower["evidence_grade"] == "경험칙"


def test_tool_conv_reference_checks_the_speaker(ctx):
    activity = [
        {"tool": "list_parts", "persona": "mech-housing-structure", "result_preview": "leaf=3"},
        {"tool": "list_interfaces", "persona": "mech-housing-structure", "result_preview": "min_gap 0.018"},
    ]
    conv = make_ctx(conv_id="conv1", activity=activity)
    finding = first_finding(make_spec(findings=[make_finding(
        cites=[{"ref": "tool:conv:conv1#1", "quote": "min_gap 0.018"}],
        claim="간극 0.018 이다.", warrant="", tool_calls=["list_interfaces(kind=clearance)", "없는도구()"])]), conv)
    assert finding["dangling"] == [] and finding["quote_mismatch"] == []
    assert finding["tool_call_refs"] == ["tool:conv:conv1#1"]
    other = first_finding(make_spec(findings=[make_finding(
        domain="disp", raised_by=["disp-utg-cover"],
        cites=[{"ref": "tool:conv:conv1#0", "quote": "leaf=3"}], claim="", warrant="")]), conv)
    assert other["dangling"] == ["tool:conv:conv1#0"]


# ================================================================ feature_snapshot · precedent(plan §4.3.3 · §4.3.4)

def test_feature_snapshot_freezes_source_values_within_caps(ctx):
    finding = first_finding(make_spec(findings=[make_finding(
        cites=[{"ref": EDGE_TIED, "quote": ""}], claim="접합이다.", warrant="")]), ctx)
    snapshot = finding["feature_snapshot"][EDGE_TIED]
    assert snapshot["min_gap"] == 0.0
    assert len(snapshot) <= FEATURE_SNAPSHOT_PER_REF


@pytest.mark.parametrize("bounds,expected", [
    ({"min_gap": {"min": 0.010, "max": 1.0}}, "out_of_range"),
    ({"min_gap": {"min": 0.0, "max": 1.0}}, "in_range"),
    ({"no_such_feature": {"min": 0.0, "max": 1.0}}, "none"),
])
def test_precedent_from_corpus_bounds(bounds, expected):
    scoped = make_ctx(corpus={"n": 7, "per_feature": bounds})
    finding = first_finding(make_spec(findings=[make_finding(
        cites=[{"ref": EDGE_TIED, "quote": ""}], claim="접합이다.", warrant="")]), scoped)
    assert finding["precedent"] == expected
    assert finding["precedent_corpus_n"] == 7


# 예측 도구 결과(predict_sed 등)는 IR 형상 속성이 아니라 _FEATURE_OF_ATTR 표에 없다 —
# 코퍼스가 그 이름의 경계를 알면 그대로 대조해 범위 밖이면 선례를 강등한다(plan §0.9 P7-3 · §7.6).
PREDICT_SED_CASES = [
    ({"sed": {"min": 0.0, "max": 0.1}}, 0.42, "out_of_range"),
    ({"sed": {"min": 0.0, "max": 1.0}}, 0.42, "in_range"),
    ({"other": {"min": 0.0, "max": 1.0}}, 0.42, "none"),
]


@pytest.mark.parametrize("bounds,value,expected", PREDICT_SED_CASES)
def test_predict_sed_result_outside_the_corpus_downgrades_the_precedent(bounds, value, expected):
    activity = [{"tool": "predict_sed", "persona": "mech-housing-structure",
                 "result_preview": f"sed={value}", "sed": value}]
    scoped = make_ctx(conv_id="conv1", activity=activity, corpus={"n": 9, "per_feature": bounds})
    finding = first_finding(make_spec(findings=[make_finding(
        cites=[{"ref": "tool:conv:conv1#0", "quote": f"sed={value}"}], claim="", warrant="")]), scoped)
    assert finding["feature_snapshot"]["tool:conv:conv1#0"]["sed"] == value
    assert finding["precedent"] == expected


def test_small_corpus_gives_no_precedent():
    scoped = make_ctx(corpus={"n": 3, "per_feature": {"min_gap": {"min": 0.010, "max": 1.0}}})
    finding = first_finding(make_spec(findings=[make_finding(
        cites=[{"ref": EDGE_TIED, "quote": ""}], claim="접합이다.", warrant="")]), scoped)
    assert finding["precedent"] == "none" and finding["precedent_corpus_n"] == 3


# ================================================================ 정규화 10단계(plan §4.2.2)

def test_enum_outside_the_list_is_preserved_and_defaulted(ctx):
    out = normalize_risk_spec(make_spec(findings=[make_finding(severity="critical")]), ctx)
    finding = out["spec"]["findings"][0]
    assert finding["severity"] == "경미" and finding["sev3"] == 1
    assert {"path": "findings/0", "field": "severity", "value": "critical"} in out["invalid_enum"]


def test_severity_judgement_mapping_is_corrected(ctx):
    out = normalize_risk_spec(make_spec(findings=[make_finding(severity="치명", judgement="OK")]), ctx)
    finding = out["spec"]["findings"][0]
    assert finding["judgement"] == "FAIL" and finding["sev3"] == 3
    assert any("조합을 보정" in w for w in out["parse_warnings"])


def test_undetermined_judgement_survives_the_mapping(ctx):
    finding = first_finding(make_spec(findings=[make_finding(severity="중대", judgement="undetermined")]), ctx)
    assert finding["judgement"] == "undetermined"


def test_gains_direction_is_forced_to_improvement(ctx):
    out = normalize_risk_spec(make_spec(findings=[], gains=[make_finding(id="G1", direction="risk")]), ctx)
    assert out["spec"]["gains"][0]["direction"] == "improvement"


def test_mechanism_synonym_is_normalized(ctx):
    finding = first_finding(make_spec(findings=[make_finding(mechanism="", mechanism_detail="간섭")]), ctx)
    assert (finding["mechanism"], finding["mechanism_detail"]) == ("interface", "interference")


def test_unknown_mechanism_goes_to_the_curation_queue(ctx):
    out = normalize_risk_spec(make_spec(findings=[make_finding(
        mechanism="mechanical", mechanism_detail="정체불명")]), ctx)
    finding = out["spec"]["findings"][0]
    assert finding["mechanism_detail"] == "unclassified"
    assert finding["mechanism_free"] == "mechanical.정체불명"
    assert any(item["kind"] == "unclassified_code" for item in out["curation"])


def test_trigger_and_detectability_corrections(ctx):
    out = normalize_risk_spec(make_spec(findings=[make_finding(
        trigger_condition="떨어뜨림", trigger_text="",
        detectability={"level": "sim-detectable", "tool": ""})]), ctx)
    finding = out["spec"]["findings"][0]
    assert finding["trigger_condition"] == "none" and finding["trigger_text"] == "떨어뜨림"
    assert finding["detectability"]["level"] == "unknown"


def test_change_kind_outside_the_axis_becomes_none(ctx):
    finding = first_finding(make_spec(findings=[make_finding(change_kind="색상")]), ctx)
    assert finding["change_kind"] == "none"


def test_status_is_open_on_storage_except_a_panel_rejection(ctx):
    """저장 status 는 open 이 정본이지만 패널 기각(rejected_in_panel)만은 보존된다(plan §0.9 P3-20)."""
    assert first_finding(make_spec(findings=[make_finding(status="verified")]), ctx)["status"] == "open"
    assert first_finding(make_spec(findings=[make_finding(status="dismissed")]), ctx)["status"] == "open"
    rejected = first_finding(make_spec(findings=[make_finding(status="rejected_in_panel")]), ctx)
    assert rejected["status"] == "rejected_in_panel"


def test_scope_kind_mismatch_fails_the_parse(ctx):
    out = normalize_risk_spec(make_spec(
        scope={"kind": "snap", "target_key": f"diff:{DIFF['diff_id']}"}), ctx)
    assert "spec_parse_failed" in out["quality"]["flag"]
    assert out["ok"] is False


def test_seat_and_coverage_mismatch_are_reported():
    scoped = make_ctx(seats=("mech-housing-structure",))
    out = normalize_risk_spec(make_spec(
        findings=[make_finding(raised_by=["mech-housing-structure", "ghost-seat"])],
        coverage={"seats": [{"key": "ghost-seat"}]}), scoped)
    assert "coverage_mismatch" in out["quality"]["flag"]
    assert any("착석 집합 밖 좌석" in w for w in out["parse_warnings"])


def test_evidence_profile_header_mismatch(ctx):
    out = normalize_risk_spec(
        make_spec(evidence_profile={"tool": 99, "card": 0, "heuristic": 0, "measured": 0}), ctx,
        opinions=[{"tool_calls_ok": 2, "knowledge_hits_n": 1}])
    assert "header_mismatch" in out["quality"]["flag"]
    assert out["quality"]["evidence_profile_computed"]["tool"] == 2
    assert out["quality"]["evidence_profile_computed"]["card"] == 1


def test_prose_and_spec_ids_are_cross_checked(ctx):
    out = normalize_risk_spec(make_spec(), ctx, prose="F1 첫 항목\nF9 산문에만 있는 항목\n")
    assert "prose_only_id F9" in out["parse_warnings"]


def test_normalization_is_deterministic(ctx):
    once = normalize_risk_spec(make_spec(), ctx)
    twice = normalize_risk_spec(make_spec(), ctx)
    assert json.dumps(once, sort_keys=True, ensure_ascii=False) == json.dumps(twice, sort_keys=True, ensure_ascii=False)
    assert once["quality"]["normalize_version"] == NORMALIZE_VERSION


def test_normalize_does_not_mutate_the_input(ctx):
    spec = make_spec(findings=[make_finding(severity="critical")])
    before = copy.deepcopy(spec)
    normalize_risk_spec(spec, ctx)
    assert spec == before


# ================================================================ facet 8 채움(plan §4.6.2)

def test_missing_facets_are_filled_in_fixed_order(ctx):
    out = normalize_risk_spec(make_spec(), ctx)
    facets = out["spec"]["character"]["facets"]
    assert [f["facet"] for f in facets] == list(FACETS)
    assert len(FACETS) == 8
    for facet in facets:
        if not facet["statements"]:
            assert facet["na_reason"], f"{facet['facet']} 에 na_reason 이 없다"


def test_facets_filled_counter(ctx):
    statement = {
        "id": "C1", "text": "접합 지배형이다.", "polarity": "inference",
        "by": ["mech-housing-structure"],
        "cites": [{"ref": CID_GAP, "quote": QUOTE_GAP}],
        "tags": ["char:interface:tied_dominant"], "confidence": "high",
    }
    character = {"one_liner": "짧은 한 줄.", "facets": [
        {"facet": "vulnerability", "na_reason": None, "statements": [statement]},
    ]}
    out = normalize_risk_spec(make_spec(character=character), ctx)
    facets = {f["facet"]: f for f in out["spec"]["character"]["facets"]}
    assert facets["vulnerability"]["na_reason"] is None
    # vulnerability 1 + ecad_absent 자동 unknown 1.
    assert out["quality"]["facets_filled"] == "2/8"


def test_auto_na_reasons_follow_the_table(ctx):
    out = normalize_risk_spec(make_spec(), ctx)
    facets = {f["facet"]: f for f in out["spec"]["character"]["facets"]}
    assert facets["anomaly"]["na_reason"] == "비교 불가(코퍼스 n<5)"
    assert facets["strength"]["na_reason"] == "개선 항목 없음"
    assert facets["intent"]["na_reason"] == "좌석 미기재"


def test_unknown_facet_gets_the_ecad_absent_statement(ctx):
    """ecad_absent 스냅샷에서는 코드가 unknown facet 에 미평가 문장을 넣는다."""
    out = normalize_risk_spec(make_spec(), ctx)
    facets = {f["facet"]: f for f in out["spec"]["character"]["facets"]}
    auto = facets["unknown"]["statements"]
    assert len(auto) == 1 and auto[0]["by"] == ["code"]
    assert auto[0]["tags"] == ["char:analysis:ecad_absent"]


def test_one_liner_is_capped_at_140(ctx):
    out = normalize_risk_spec(make_spec(character={"one_liner": "가" * 200, "facets": []}), ctx)
    assert len(out["spec"]["character"]["one_liner"]) == 140


def test_vocabulary_violation_moves_the_tag_to_free_space(ctx):
    statement = {
        "id": "C1", "text": "적층 강성 예산이 지배한다.", "polarity": "hypothesis",
        "by": ["mech-housing-structure"], "cites": [{"ref": CID_GAP, "quote": QUOTE_GAP}],
        "tags": ["char:philosophy:stack_first"], "confidence": "low",
    }
    out = normalize_risk_spec(make_spec(character={"one_liner": "", "facets": [
        {"facet": "intent", "na_reason": None, "statements": [statement]}]}), ctx)
    tags = out["spec"]["character"]["facets"][0]["statements"][0]["tags"]
    assert tags == ["x:stack_first"]
    assert any("어휘 밖 태그" in w for w in out["parse_warnings"])
    assert any(item["kind"] == "x_tag_promote" for item in out["curation"])


def test_vulnerability_statement_must_share_cites_with_findings(ctx):
    statement = {
        "id": "C1", "text": "다른 근거만 든다.", "polarity": "inference",
        "by": ["mech-housing-structure"],
        "cites": [{"ref": "sig:counts.leaf", "quote": "leaf=3"}],
        "tags": [], "confidence": "medium",
    }
    out = normalize_risk_spec(make_spec(character={"one_liner": "", "facets": [
        {"facet": "vulnerability", "na_reason": None, "statements": [statement]}]}), ctx)
    assert any("character/vulnerability" in w for w in out["parse_warnings"])


# ================================================================ 원자 펼치기(plan §4.9 실례)

@pytest.fixture(scope="module")
def plan_example() -> dict:
    return _load("risk_spec/valid_plan_example.json")


def test_plan_example_expands_into_atoms(plan_example, ctx):
    out = normalize_risk_spec(copy.deepcopy(plan_example), ctx, opinions=[])
    spec = out["spec"]
    assert len(spec["findings"]) >= 3 and len(spec["gains"]) >= 1
    assert len(spec["character"]["facets"]) == 8
    for atom in spec["findings"] + spec["gains"]:
        assert atom["claim_uid"] == f"{PANEL_ID}#{atom['id']}"
        assert len(atom["cluster_key"]) == 12
        assert atom["evidence_grade"] in ("측정", "문헌·규격", "도구예측", "경험칙")
        assert isinstance(atom["feature_snapshot"], dict)
        assert atom["status"] == "open"
    for atom in spec["cross_domain"] + spec["open_items"]:
        assert atom["claim_uid"] == f"{PANEL_ID}#{atom['id']}"
    for facet in spec["character"]["facets"]:
        for statement in facet["statements"]:
            assert statement["claim_uid"] == f"{PANEL_ID}#{statement['id']}"
            assert statement["facet"] == facet["facet"]


def test_plan_example_cross_domain_and_open_items_are_normalized(plan_example, ctx):
    spec = normalize_risk_spec(copy.deepcopy(plan_example), ctx)["spec"]
    for item in spec["cross_domain"]:
        assert item["from_domain"] != item["to_domain"]
        assert len(item["path"]) <= 400
    for item in spec["open_items"]:
        assert item["resolving_check"]["kind"] in ("tool", "sim", "test", "field")
        assert len(item["question"]) <= 200


def test_plan_example_findings_are_grouped_by_cluster(plan_example, ctx):
    """F1 과 F3 은 같은 계면이지만 메커니즘이 달라 다른 클러스터다."""
    spec = normalize_risk_spec(copy.deepcopy(plan_example), ctx)["spec"]
    by_id = {f["id"]: f for f in spec["findings"]}
    assert by_id["F1"]["cluster_key"] != by_id["F3"]["cluster_key"]
    assert by_id["F1"]["mechanism_detail"] == "drop_stress"
    assert by_id["F3"]["mechanism_detail"] == "tolerance"
