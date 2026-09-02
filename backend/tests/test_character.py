# character.py 검증 — 씨앗 층 재생성·패널 병합·이견 보존·x: 승격 후보·3층 승격(plan §4.6.3·§4.6.4)
from __future__ import annotations

import json

import pytest

from app import character
from app.errors import AppError

OWNER = "u-owner"
PROJECT = "p-1"
SNAP = "snap-1"
TARGET_A = "t-a"
TARGET_B = "t-b"
TARGET_C = "t-c"


def _project(store, project_id=PROJECT, code="F7-DV2"):
    store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (project_id, OWNER, code, code, 100, 100))


def _snapshot_with_seeds(store, seeds, snapshot_id=SNAP, project_id=PROJECT, created_at=100):
    store.execute(
        "INSERT INTO rr_snapshots(id, project_id, owner_sub, ir_version, ir_hash, ir_json, source_ids_json,"
        " kinds_json, created_at) VALUES (?,?,?,'1.0',?,'{}','[]','[\"mcad\"]',?)",
        (snapshot_id, project_id, OWNER, f"h-{snapshot_id}", created_at))
    store.execute(
        "INSERT INTO rr_states(snapshot_id, owner_sub, state_json, feature_json, gates_json,"
        " character_seed_json, computed_at) VALUES (?,?,'{}','{}','{}',?,?)",
        (snapshot_id, OWNER, json.dumps(seeds, ensure_ascii=False), created_at))


def _statement(store, sid, *, facet, tags, statement, polarity="observation", target=TARGET_A,
               status="panel", project_id=PROJECT, cites=(), by=("mech-housing-structure",),
               created_at=200):
    store.execute(
        "INSERT INTO rr_character(id, project_id, owner_sub, facet, tag, tags_json, statement, polarity,"
        " cites_json, by_json, first_target_key, support_panels, support_targets, status, created_at,"
        " updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,1,1,?,?,?)",
        (sid, project_id, OWNER, facet, tags[0] if tags else None,
         json.dumps(list(tags), ensure_ascii=False), statement, polarity,
         json.dumps([{"ref": r} for r in cites], ensure_ascii=False),
         json.dumps(list(by), ensure_ascii=False), target, status, created_at, created_at))


def _rows(store, project_id=PROJECT):
    return {r["id"]: dict(r) for r in store.query(
        "SELECT id, facet, tag, tags_json, statement, polarity, by_json, variants_json, dissent_json,"
        " support_panels, support_targets, status, superseded_by FROM rr_character WHERE project_id = ?",
        (project_id,))}


# ---------------------------------------------------------------- 씨앗 층(L0)

SEEDS = [
    {"tag": "char:structure:multi_file_assembly", "rule": "seed.structure.multi_file",
     "cites": ["sig:counts.files"], "text": "files=2"},
    {"tag": "char:tolerance:tight", "rule": "seed.tolerance.tight", "cites": ["sig:hist.gap_mm"],
     "text": "min_gap≤0.1 비율 0.42"},
    {"tag": "char:maturity:anon_names_high", "rule": "seed.maturity.anon_names_high",
     "cites": ["gate:G1"], "text": "n_anon=9"},
]


def test_seed_layer_maps_axis_to_facet_and_is_idempotent(risk_store):
    _project(risk_store)
    _snapshot_with_seeds(risk_store, SEEDS)

    first = character.sync_seed_layer(risk_store, PROJECT, owner_sub=OWNER)
    second = character.sync_seed_layer(risk_store, PROJECT, owner_sub=OWNER)
    assert first == second and len(first) == 3

    rows = _rows(risk_store)
    assert len(rows) == 3
    by_tag = {r["tag"]: r for r in rows.values()}
    assert by_tag["char:structure:multi_file_assembly"]["facet"] == "intent"
    assert by_tag["char:tolerance:tight"]["facet"] == "constraint"
    assert by_tag["char:maturity:anon_names_high"]["facet"] == "unknown"
    seed = by_tag["char:structure:multi_file_assembly"]
    assert seed["status"] == "seed" and seed["statement"] == "files=2"
    assert json.loads(seed["by_json"]) == ["code"]


def test_seed_layer_uses_latest_snapshot_and_keeps_panel_rows(risk_store):
    _project(risk_store)
    _snapshot_with_seeds(risk_store, SEEDS, snapshot_id="snap-old", created_at=100)
    _snapshot_with_seeds(risk_store, [SEEDS[0]], snapshot_id="snap-new", created_at=200)
    _statement(risk_store, "panelA#C1", facet="vulnerability",
               tags=["char:interface:utg_housing"], statement="UTG 계면이 얇다")

    character.sync_seed_layer(risk_store, PROJECT, owner_sub=OWNER)

    rows = _rows(risk_store)
    assert [r["tag"] for r in rows.values() if r["status"] == "seed"] == \
        ["char:structure:multi_file_assembly"]
    assert rows["panelA#C1"]["status"] == "panel"


def test_seed_layer_adds_source_absent_statement(risk_store):
    _project(risk_store)
    _snapshot_with_seeds(risk_store, [{"tag": "char:analysis:sim_only", "rule": "seed.analysis.primary",
                                       "cites": ["sig:sources.primary"], "text": "primary=dyna"}])

    character.sync_seed_layer(risk_store, PROJECT, owner_sub=OWNER)

    rows = _rows(risk_store)
    auto = rows[f"seed:{PROJECT}:source_absent"]
    assert auto["facet"] == "unknown" and auto["statement"] == character.SOURCE_ABSENT_TEXT
    assert json.loads(auto["by_json"]) == ["code"]


def test_seed_layer_without_state_clears_seed_rows(risk_store):
    _project(risk_store)
    _snapshot_with_seeds(risk_store, SEEDS)
    character.sync_seed_layer(risk_store, PROJECT, owner_sub=OWNER)

    risk_store.execute("DELETE FROM rr_states WHERE snapshot_id = ?", (SNAP,))
    assert character.sync_seed_layer(risk_store, PROJECT, owner_sub=OWNER) == []
    assert _rows(risk_store) == {}


# ---------------------------------------------------------------- 패널 층 병합(L2)

def test_merge_counts_panels_and_targets_and_keeps_variants(risk_store):
    _project(risk_store)
    _statement(risk_store, "panelA#C1", facet="vulnerability", tags=["char:tolerance:tight"],
               statement="UTG 여유가 0.18 mm 로 줄었다", target=TARGET_A, created_at=200)
    _statement(risk_store, "panelB#C2", facet="vulnerability", tags=["char:tolerance:tight",
                                                                    "x:hinge_gap"],
               statement="힌지 여유도 같은 방향으로 줄었다", target=TARGET_B, created_at=210)

    merged = character.merge_panel_layer(risk_store, PROJECT)
    assert merged == [{"id": "panelA#C1", "facet": "vulnerability", "tag": "char:tolerance:tight",
                       "support_panels": 2, "support_targets": 2, "variants": 1, "dissent": 0}]

    rows = _rows(risk_store)
    head = rows["panelA#C1"]
    assert head["support_panels"] == 2 and head["support_targets"] == 2
    assert json.loads(head["tags_json"]) == ["char:tolerance:tight", "x:hinge_gap"]
    variants = json.loads(head["variants_json"])
    assert [v["id"] for v in variants] == ["panelB#C2"]
    assert variants[0]["statement"] == "힌지 여유도 같은 방향으로 줄었다"
    # 흡수된 행은 지우지 않고 1/1 로 되돌린다 — 지지 수를 두 번 세지 않는다.
    assert rows["panelB#C2"]["support_panels"] == 1 and rows["panelB#C2"]["variants_json"] is None


def test_merge_leaves_untagged_statements_separate(risk_store):
    _project(risk_store)
    _statement(risk_store, "panelA#C6", facet="tradeoff", tags=[], statement="박형을 얻고 여유를 내줬다")
    _statement(risk_store, "panelB#C8", facet="tradeoff", tags=[], statement="질량을 얻고 강성을 내줬다")

    merged = character.merge_panel_layer(risk_store, PROJECT)

    assert len(merged) == 2
    rows = _rows(risk_store)
    assert all(r["support_panels"] == 1 and r["support_targets"] == 1
               for r in rows.values())


def test_merge_preserves_dissent_without_dropping_it(risk_store):
    _project(risk_store)
    _statement(risk_store, "panelA#C1", facet="intent", tags=["char:structure:thin_stack"],
               statement="박형 우선으로 적층했다", polarity="observation", created_at=200)
    _statement(risk_store, "panelB#C1", facet="intent", tags=["char:structure:thin_stack"],
               statement="박형이 아니라 원가 때문일 수 있다", polarity="hypothesis",
               target=TARGET_B, created_at=210)

    character.merge_panel_layer(risk_store, PROJECT)

    head = _rows(risk_store)["panelA#C1"]
    dissent = json.loads(head["dissent_json"])
    assert [d["id"] for d in dissent] == ["panelB#C1"]
    assert dissent[0]["polarity"] == "hypothesis"
    assert dissent[0]["statement"] == "박형이 아니라 원가 때문일 수 있다"


def test_merge_prefers_confirmed_row_as_head(risk_store):
    _project(risk_store)
    _statement(risk_store, "panelA#C1", facet="intent", tags=["char:structure:thin_stack"],
               statement="먼저 나온 문장", created_at=200)
    _statement(risk_store, "panelB#C1", facet="intent", tags=["char:structure:thin_stack"],
               statement="사람이 확정한 문장", status="confirmed", target=TARGET_B, created_at=210)

    merged = character.merge_panel_layer(risk_store, PROJECT)

    assert merged[0]["id"] == "panelB#C1" and merged[0]["support_panels"] == 2


def test_merge_normalizes_interface_tag_by_alias(risk_store):
    _project(risk_store)
    risk_store.execute(
        "INSERT INTO rr_iface_alias(alias_key, canonical_a, canonical_b, owner_sub, aliases_json, source,"
        " status, created_at, updated_at) VALUES (?,?,?,?,?,'human','active',?,?)",
        ("utg|housing_front", "utg", "housing_front", OWNER,
         json.dumps([{"name_a": "UTG_TOP", "name_b": "HOUSING FRONT"}], ensure_ascii=False), 100, 100))
    _statement(risk_store, "panelA#C1", facet="vulnerability",
               tags=["char:interface:housing_front_utg_top"], statement="A", created_at=200)
    _statement(risk_store, "panelB#C1", facet="vulnerability",
               tags=["char:interface:housing_front_utg"], statement="B", target=TARGET_B, created_at=210)

    merged = character.merge_panel_layer(risk_store, PROJECT)

    assert merged == [{"id": "panelA#C1", "facet": "vulnerability",
                       "tag": "char:interface:housing_front_utg", "support_panels": 2,
                       "support_targets": 2, "variants": 1, "dissent": 0}]


# ---------------------------------------------------------------- x: 자유 태그 승격 후보

def test_x_tag_queued_only_above_threshold(risk_store):
    _project(risk_store)
    _statement(risk_store, "panelA#C1", facet="anomaly", tags=["x:wound_jelly"], statement="A",
               target=TARGET_A)
    _statement(risk_store, "panelB#C1", facet="anomaly", tags=["x:wound_jelly"], statement="B",
               target=TARGET_B)

    assert character.queue_x_tag_promotions(risk_store, owner_sub=OWNER) == []

    _statement(risk_store, "panelC#C1", facet="anomaly", tags=["x:wound_jelly"], statement="C",
               target=TARGET_C)
    assert character.queue_x_tag_promotions(risk_store, owner_sub=OWNER) == ["x:wound_jelly"]
    # 같은 태그를 두 번 올리지 않는다.
    assert character.queue_x_tag_promotions(risk_store, owner_sub=OWNER) == []

    row = risk_store.query_one(
        "SELECT kind, payload_json, status FROM rr_curation_queue WHERE kind = 'x_tag_promote'", ())
    payload = json.loads(row["payload_json"])
    assert row["status"] == "open"
    assert payload["tag"] == "x:wound_jelly"
    assert payload["targets"] == [TARGET_A, TARGET_B, TARGET_C]
    assert sorted(payload["panels"]) == ["panelA", "panelB", "panelC"]


def test_rejected_x_tag_is_not_queued_again(risk_store):
    """큐레이터가 되돌린 태그를 매일 밤 다시 올리지 않는다(열린 큐가 늘면 배지 병목이 영구히 켜진다)."""
    _project(risk_store)
    for sid, target in (("panelA#C1", TARGET_A), ("panelB#C1", TARGET_B), ("panelC#C1", TARGET_C)):
        _statement(risk_store, sid, facet="anomaly", tags=["x:wound_jelly"], statement="A", target=target)
    assert character.queue_x_tag_promotions(risk_store, owner_sub=OWNER) == ["x:wound_jelly"]

    risk_store.execute("UPDATE rr_curation_queue SET status = 'rejected' WHERE kind = 'x_tag_promote'")
    assert character.queue_x_tag_promotions(risk_store, owner_sub=OWNER) == []
    assert len(risk_store.query(
        "SELECT id FROM rr_curation_queue WHERE kind = 'x_tag_promote'", ())) == 1


def test_x_tag_scan_counts_inside_one_owner(risk_store):
    """임계는 그 소유자의 진술로만 찬다 — 첫 소유자가 남의 태그를 자기 큐로 가져가지 않는다(§4.6.3 (2))."""
    _project(risk_store)
    for sid, target in (("panelA#C1", TARGET_A), ("panelB#C1", TARGET_B), ("panelC#C1", TARGET_C)):
        _statement(risk_store, sid, facet="anomaly", tags=["x:other_owner"], statement="A", target=target)
    risk_store.execute("UPDATE rr_character SET owner_sub = 'u-other' WHERE project_id = ?", (PROJECT,))

    assert character.queue_x_tag_promotions(risk_store, owner_sub=OWNER) == []
    assert character.queue_x_tag_promotions(risk_store, owner_sub="u-other") == ["x:other_owner"]
    row = risk_store.query_one(
        "SELECT owner_sub FROM rr_curation_queue WHERE kind = 'x_tag_promote'", ())
    assert row["owner_sub"] == "u-other"


# ---------------------------------------------------------------- 자유 태그 승격(plan §7.7)

def test_promote_x_tag_refuses_a_non_free_tag_and_an_unknown_or_open_axis(risk_store):
    with pytest.raises(AppError) as not_free:
        character.promote_x_tag(risk_store, tag="char:structure:thin_stack", axis="char:constraint",
                                owner_sub=OWNER)
    assert not_free.value.http_status == 422

    with pytest.raises(AppError) as unknown:
        character.promote_x_tag(risk_store, tag="x:stack_budget", axis="char:nope", owner_sub=OWNER)
    assert unknown.value.code == "axis_unknown"

    # char:interface 값은 rr_iface_alias 에서 파생돼 통제 목록이 없다 — 자유 태그를 그리로 올릴 수 없다(§4.6.3 (4)).
    with pytest.raises(AppError) as open_axis:
        character.promote_x_tag(risk_store, tag="x:stack_budget", axis="char:interface", owner_sub=OWNER)
    assert open_axis.value.code == "axis_not_promotable"


def test_promote_x_tag_touches_only_my_live_statements(risk_store):
    """남의 행·폐기된 행은 건드리지 않는다 — 진술은 소유자 표다."""
    _project(risk_store)
    _statement(risk_store, "panelA#C1", facet="anomaly", tags=["x:stack_budget"], statement="A")
    _statement(risk_store, "panelB#C1", facet="anomaly", tags=["x:stack_budget"], statement="B",
               target=TARGET_B)
    _statement(risk_store, "panelC#C1", facet="anomaly", tags=["x:stack_budget"], statement="C",
               target=TARGET_C)
    risk_store.execute("UPDATE rr_character SET owner_sub = 'u-other' WHERE id = 'panelB#C1'")
    risk_store.execute("UPDATE rr_character SET status = 'superseded' WHERE id = 'panelC#C1'")

    out = character.promote_x_tag(risk_store, tag="x:stack_budget", axis="char:tolerance",
                                  owner_sub=OWNER)

    assert out["statements"] == 1
    tags = {r["id"]: json.loads(r["tags_json"]) for r in risk_store.query(
        "SELECT id, tags_json FROM rr_character", ())}
    assert tags["panelA#C1"] == ["char:tolerance:stack_budget"]
    assert tags["panelB#C1"] == ["x:stack_budget"]           # 남의 행
    assert tags["panelC#C1"] == ["x:stack_budget"]           # 폐기된 행


def test_promote_x_tag_into_an_existing_value_moves_statements_without_bumping(risk_store):
    """값이 이미 어휘에 있으면 승급할 것이 없다 — 진술만 통제 태그로 옮긴다."""
    _project(risk_store)
    _statement(risk_store, "panelA#C1", facet="anomaly", tags=["x:tight"], statement="A")

    out = character.promote_x_tag(risk_store, tag="x:tight", axis="char:tolerance", owner_sub=OWNER)

    assert out["already_in_vocab"] is True
    assert out["vocab_version_before"] == out["vocab_version_after"] == "vocab-1.0"
    assert json.loads(risk_store.query_one(
        "SELECT tags_json AS t FROM rr_character WHERE id = 'panelA#C1'")["t"]) == ["char:tolerance:tight"]


def test_promoted_statements_stop_coming_back_as_candidates(risk_store):
    """승격하면 그 태그를 단 진술이 사라지므로 다음 스캔이 같은 후보를 다시 올리지 않는다."""
    _project(risk_store)
    for sid, target in (("panelA#C1", TARGET_A), ("panelB#C1", TARGET_B), ("panelC#C1", TARGET_C)):
        _statement(risk_store, sid, facet="anomaly", tags=["x:stack_budget"], statement="A", target=target)
    assert character.queue_x_tag_promotions(risk_store, owner_sub=OWNER) == ["x:stack_budget"]

    character.promote_x_tag(risk_store, tag="x:stack_budget", axis="char:constraint", owner_sub=OWNER)

    assert character.queue_x_tag_promotions(risk_store, owner_sub=OWNER) == []


# ---------------------------------------------------------------- 프로파일 조립

def test_profile_orders_by_status_then_support_then_grade(risk_store):
    _project(risk_store)
    _snapshot_with_seeds(risk_store, [SEEDS[0]])
    _statement(risk_store, "panelA#C1", facet="intent", tags=["char:structure:thin_stack"],
               statement="지지 2 패널", cites=["sig:counts.files"], created_at=200)
    _statement(risk_store, "panelB#C1", facet="intent", tags=["char:structure:thin_stack"],
               statement="같은 태그 다른 패널", target=TARGET_B, created_at=210)
    _statement(risk_store, "panelC#C1", facet="intent", tags=["char:structure:sandwich"],
               statement="지지 1 패널", target=TARGET_C, created_at=220)
    _statement(risk_store, "panelD#C1", facet="intent", tags=["char:structure:wound"],
               statement="사람이 확정", status="confirmed", created_at=230)

    profile = character.synthesize(risk_store, PROJECT, owner_sub=OWNER)

    assert [f["facet"] for f in profile["facets"]] == list(character.FACET_ORDER)
    intent = next(f for f in profile["facets"] if f["facet"] == "intent")
    assert [s["id"] for s in intent["statements"][:4]] == [
        "panelD#C1", "panelA#C1", "panelB#C1", "panelC#C1"]
    assert intent["statements"][-1]["id"].startswith(f"seed:{PROJECT}:")
    assert intent["statements"][0]["status"] == "confirmed"
    assert intent["statements"][1]["support_panels"] == 2
    assert intent["statements"][-1]["status"] == "seed"
    assert intent["na_reason"] is None
    empty = next(f for f in profile["facets"] if f["facet"] == "strength")
    assert empty["statements"] == [] and empty["na_reason"] == "좌석 미기재"
    assert profile["facets_filled"] == 1
    assert profile["character_status"] == "confirmed"


def test_profile_exposes_dissent_and_tag_counts(risk_store):
    _project(risk_store)
    _statement(risk_store, "panelA#C1", facet="intent", tags=["char:structure:thin_stack"],
               statement="관찰", polarity="observation", created_at=200)
    _statement(risk_store, "panelB#C1", facet="intent", tags=["char:structure:thin_stack"],
               statement="가설", polarity="hypothesis", target=TARGET_B, created_at=210)

    profile = character.synthesize(risk_store, PROJECT, owner_sub=OWNER)

    assert [d["id"] for d in profile["dissent"]] == ["panelB#C1"]
    assert profile["dissent"][0]["head"] == "panelA#C1"
    assert profile["tags"][0] == {"tag": "char:structure:thin_stack", "n": 2}


def test_evidence_grade_of_uses_narrative_table(risk_store):
    assert character.evidence_grade_of([{"ref": "inc:12"}]) == "측정"
    assert character.evidence_grade_of([{"ref": "card:abc"}]) == "문헌·규격"
    assert character.evidence_grade_of([{"ref": "sig:counts.files"}]) == "도구예측"
    assert character.evidence_grade_of([]) == "경험칙"
    assert character.evidence_grade_of([{"ref": "정체불명"}]) == "경험칙"


# ---------------------------------------------------------------- 승격

def test_confirm_raises_layer_and_project_status(risk_store):
    _project(risk_store)
    _statement(risk_store, "panelA#C1", facet="intent", tags=["char:structure:thin_stack"],
               statement="확정 대상")

    out = character.confirm(risk_store, "panelA#C1", actor="human@example.com", owner_sub=OWNER)

    assert out["status"] == "confirmed" and out["decided_by"] == "human@example.com"
    assert out["decided_at"] is not None
    project = risk_store.query_one("SELECT character_status FROM rr_projects WHERE id = ?", (PROJECT,))
    assert project["character_status"] == "confirmed"
    # 다시 확정해도 같다.
    assert character.confirm(risk_store, "panelA#C1", actor="x", owner_sub=OWNER)["status"] == "confirmed"


def test_confirm_rejects_unknown_or_superseded(risk_store):
    _project(risk_store)
    _statement(risk_store, "panelA#C1", facet="intent", tags=[], statement="A")
    _statement(risk_store, "panelB#C1", facet="intent", tags=[], statement="B")
    character.supersede(risk_store, "panelA#C1", superseded_by="panelB#C1", actor="h", owner_sub=OWNER)

    with pytest.raises(AppError) as missing:
        character.confirm(risk_store, "없는id", actor="h", owner_sub=OWNER)
    assert missing.value.http_status == 404

    with pytest.raises(AppError) as bad:
        character.confirm(risk_store, "panelA#C1", actor="h", owner_sub=OWNER)
    assert bad.value.http_status == 400


def test_supersede_records_winner_and_guards(risk_store):
    _project(risk_store)
    _project(risk_store, project_id="p-2", code="OTHER")
    _statement(risk_store, "panelA#C1", facet="intent", tags=[], statement="밀려나는 문장")
    _statement(risk_store, "panelB#C1", facet="intent", tags=[], statement="우선 문장")
    _statement(risk_store, "panelZ#C1", facet="intent", tags=[], statement="남의 과제", project_id="p-2")

    out = character.supersede(risk_store, "panelA#C1", superseded_by="panelB#C1", actor="h",
                              owner_sub=OWNER)
    assert out["status"] == "superseded" and out["superseded_by"] == "panelB#C1"

    with pytest.raises(AppError):
        character.supersede(risk_store, "panelB#C1", superseded_by="panelB#C1", actor="h",
                            owner_sub=OWNER)
    with pytest.raises(AppError):
        character.supersede(risk_store, "panelB#C1", superseded_by="panelZ#C1", actor="h",
                            owner_sub=OWNER)

    profile = character.build_profile(risk_store, PROJECT)
    assert [s["id"] for s in profile["superseded"]] == ["panelA#C1"]
    intent = next(f for f in profile["facets"] if f["facet"] == "intent")
    assert [s["id"] for s in intent["statements"]] == ["panelB#C1"]


def test_synthesize_is_idempotent(risk_store):
    _project(risk_store)
    _snapshot_with_seeds(risk_store, SEEDS)
    _statement(risk_store, "panelA#C1", facet="vulnerability", tags=["char:tolerance:tight"],
               statement="A", created_at=200)
    _statement(risk_store, "panelB#C1", facet="vulnerability", tags=["char:tolerance:tight"],
               statement="B", target=TARGET_B, created_at=210)

    first = character.synthesize(risk_store, PROJECT, owner_sub=OWNER)
    second = character.synthesize(risk_store, PROJECT, owner_sub=OWNER)

    def shape(profile):
        return [(s["id"], s["status"], s["support_panels"], s["support_targets"], tuple(s["tags"]))
                for f in profile["facets"] for s in f["statements"]]

    assert shape(first) == shape(second)
    assert first["synthesis"]["merged_groups"] == second["synthesis"]["merged_groups"] == 1
    assert second["character_status"] == "panel"
