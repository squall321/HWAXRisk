# 패널 결과 영속(narrative.persist_panel_result)과 브리프 되먹임(narrative.prior_evidence) 검증 — plan §4.3·§4.6·§5.6·§6.7.2 8단계
from __future__ import annotations

import json

import pytest

from app import narrative, registry
from app.errors import AppError

OWNER = "tester@example.com"
PROJECT = "P1"
SNAPSHOT = "S1"
TARGET = "snap:" + "a" * 32
PANEL = "PN1"

NID = "p:0123456789ab"
CKEY = "ck:0123456789ab"
QUOTE = "HOUSING 상단 리브"
NODE_TEXT = QUOTE + " 형상"

SEATS = [
    {"key": "mech-housing-structure", "domain": "mech", "origin": "primary"},
    {"key": "sim-drop-impact", "domain": "sim", "origin": "primary"},
]


# ---------------------------------------------------------------- 픽스처·삽입 도우미


def _seed(store) -> None:
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash,"
        " external_sync_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (TARGET, OWNER, "snap", SNAPSHOT, PROJECT, "0123456789ab", "{}", 1, 1),
    )
    store.execute(
        "INSERT INTO rr_ir_nodes(snapshot_id, nid, owner_sub, kind, source_kind, name, name_norm, ckey,"
        " dn, asm_key, material_norm, volume, attrs_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (SNAPSHOT, NID, OWNER, "part", "mcad", "HOUSING", "HOUSING", CKEY, "/ROOT/HOUSING",
         "ROOT", "PC_ABS", 1200.0, json.dumps({"text": NODE_TEXT, "min_gap": 0.4}, ensure_ascii=False)),
    )
    store.execute(
        "INSERT INTO rr_states(snapshot_id, owner_sub, state_json, feature_json, gates_json,"
        " summary_text, summary_status, computed_at) VALUES (?,?,?,?,?,?,?,?)",
        (SNAPSHOT, OWNER, json.dumps({"signals": {}, "gates": {}}, ensure_ascii=False), "{}", "{}",
         "스냅샷 요약", "ok", 1),
    )
    store.execute(
        "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, tier, seats_json, rounds, status,"
        " conv_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (PANEL, TARGET, OWNER, 1, "B", json.dumps(SEATS, ensure_ascii=False), 2, "running", "CONV1", 1),
    )
    for seat in SEATS:
        store.execute(
            "INSERT INTO rr_coverage(target_key, agent_key, owner_sub, domain, tier, origin, status,"
            " cycle, panel_id, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (TARGET, seat["key"], OWNER, seat["domain"], "B", "primary", "running", 1, PANEL, 1),
        )


def _spec() -> dict:
    """findings·gains·cross_domain·character·open_items 를 한 원자씩 담은 최소 risk_spec."""
    cite = [{"ref": NID, "quote": QUOTE}]
    finding = {
        "id": "F1", "direction": "risk", "domain": "mech",
        "mechanism": "mechanical", "mechanism_detail": "drop_stress",
        "change_kind": "dimension",
        "subject": {"ckeys": [CKEY], "names": ["HOUSING"]},
        "trigger_condition": "load.drop",
        "severity": "중대", "judgement": "WARNING",
        "detectability": {"level": "sim-detectable", "tool": "report_part_risk"},
        "evidence_grade": "도구예측", "precedent": "none",
        "cites": cite, "tool_calls": [],
        "claim": "낙하 시 상단 리브에 응력이 집중된다",
        "warrant": "리브가 얇아 낙하 하중 경로가 한 점으로 모인다",
        "resolving_check": {"kind": "sim", "ref": "report_part_risk"},
        "owner_domain": "mech",
        "raised_by": ["mech-housing-structure"],
        "contested_by": [registry.ADVERSARY_KEY],
        "contest_note": "기존 설계에서 문제된 적 없다",
        "status": "open",
    }
    gain = {
        **finding,
        "id": "G1", "direction": "improvement", "severity": "경미", "judgement": "OK",
        "mechanism_detail": "bending",
        "claim": "리브 추가로 강성이 올라간다",
        "warrant": "단면 이차모멘트가 커진다",
        "contested_by": [], "contest_note": "",
        "raised_by": ["sim-drop-impact"], "owner_domain": "sim",
    }
    statement = {
        "id": "C1", "facet": "vulnerability", "text": "얇은 리브에 하중을 몰아주는 성향이 있다",
        "polarity": "inference", "by": ["mech-housing-structure"], "cites": cite,
        "tags": ["char:analysis:ecad_absent"], "confidence": "medium",
    }
    return {
        "schema": "risk_spec", "version": "1.0", "taxonomy_version": "1.0",
        "scope": {"kind": "snap", "target_key": TARGET, "project_refs": [PROJECT],
                  "ir_refs": [SNAPSHOT], "diff_ref": None, "ir_hash": "0123456789ab"},
        "findings": [finding], "gains": [gain],
        "cross_domain": [{"id": "X1", "from_domain": "mech", "to_domain": "sim",
                          "path": "리브 형상 변경이 낙하 해석 경계조건을 바꾼다", "cites": cite,
                          "raised_by": ["mech-housing-structure"]}],
        "character": {"one_liner": "강성 우선 설계",
                      "facets": [{"facet": "vulnerability", "statements": [statement], "na_reason": None}]},
        "open_items": [{"id": "O1", "question": "리브 두께 하한은 얼마인가",
                        "resolving_check": {"kind": "sim", "ref": "report_part_risk"}}],
        "coverage": {"seats": SEATS, "domains_seated": ["mech", "sim"], "domains_missing": []},
        "verdict": "conditional", "verdict_conditions": ["리브 두께 재검토"],
        "evidence_profile": {"tool": 0, "card": 0, "precedent": {"verified": 0, "dismissed": 0},
                             "heuristic": 0, "measured": 0},
    }


def _decision_text(spec: dict) -> str:
    return (
        "F1 낙하 시 상단 리브에 응력이 집중된다.\n"
        "G1 리브 추가로 강성이 올라간다.\n"
        "X1 리브 형상 변경이 낙하 해석 경계조건을 바꾼다.\n"
        "C1 얇은 리브에 하중을 몰아주는 성향이 있다.\n"
        "O1 리브 두께 하한은 얼마인가.\n\n"
        "```json\n" + json.dumps(spec, ensure_ascii=False) + "\n```\n"
    )


def _turns() -> list[dict]:
    return [
        {"persona": "mech-housing-structure", "round": 1, "stance": "oppose",
         "say": f"상단 리브 단면이 얇다 [{NID}]", "position": "리브 보강 필요"},
        {"persona": "sim-drop-impact", "round": 1, "stance": "conditional",
         "say": "낙하 해석으로 확인하자", "position": "해석 선행"},
    ]


@pytest.fixture
def seeded(risk_store):
    _seed(risk_store)
    return risk_store


def _persist(store, *, spec_present: bool = True, actor: str | None = None) -> dict:
    spec = _spec() if spec_present else None
    text = _decision_text(_spec()) if spec_present else "펜스 없는 결정문"
    return narrative.persist_panel_result(
        store, PANEL, decision_text=text, spec=spec, turns=_turns(),
        attribution={"seats": {"mech-housing-structure": {"tool_calls_n": 2, "tool_calls_ok": 2,
                                                          "used_tool": True, "turns_n": 1}},
                     "extra_seats": []},
        actor=actor,
    )


# ---------------------------------------------------------------- 원자 저장(§4.3·§4.6)


def test_persist_writes_findings_with_cluster_key(seeded):
    out = _persist(seeded)

    assert out["findings_total"] == 2
    rows = seeded.query(
        "SELECT claim_uid, direction, mechanism, mechanism_detail, change_kind, subject_key, ckeys_json,"
        " trigger_condition, severity, sev3, judgement, detectability, detect_tool, evidence_grade,"
        " precedent, dangling, cluster_key, panel_id, target_key, project_id, snapshot_id, owner_sub, status"
        " FROM rr_findings WHERE panel_id = ? ORDER BY claim_uid", (PANEL,))
    assert [r["claim_uid"] for r in rows] == [f"{PANEL}#F1", f"{PANEL}#G1"]

    f1 = rows[0]
    assert f1["direction"] == "risk" and rows[1]["direction"] == "improvement"
    assert f1["subject_key"] == CKEY and json.loads(f1["ckeys_json"]) == [CKEY]
    assert f1["trigger_condition"] == "load.drop" and f1["sev3"] == 2
    assert f1["detectability"] == "sim-detectable" and f1["detect_tool"] == "report_part_risk"
    assert f1["evidence_grade"] == "도구예측"          # p: 인용 1건 → §4.4.3 도구예측
    assert f1["dangling"] == 0                        # 스코프 안 노드라 dangling 이 아니다
    assert f1["project_id"] == PROJECT and f1["snapshot_id"] == SNAPSHOT
    assert f1["owner_sub"] == OWNER and f1["status"] == "open"
    # §4.3.2 cluster_key = sha1(mechanism|mechanism_detail|subject_key|change_kind)[:12]
    assert f1["cluster_key"] == narrative.cluster_key_of("mechanical", "drop_stress", CKEY, "dimension")
    assert rows[1]["cluster_key"] == narrative.cluster_key_of("mechanical", "bending", CKEY, "dimension")
    assert f1["cluster_key"] != rows[1]["cluster_key"]


def test_finding_json_carries_registry_merge_keys(seeded):
    _persist(seeded)
    row = seeded.query_one("SELECT finding_json FROM rr_findings WHERE claim_uid = ?", (f"{PANEL}#F1",))
    fj = json.loads(row["finding_json"])
    for key in ("claim", "warrant", "raised_by", "contested_by", "cites", "resolving_check",
                "feature_snapshot", "subject", "subject_unresolved", "trigger_condition", "owner_domain"):
        assert key in fj, key
    assert fj["raised_by"] == ["mech-housing-structure"]
    assert fj["contested_by"] == [registry.ADVERSARY_KEY]
    assert fj["cites"] == [{"ref": NID, "quote": QUOTE}]
    assert fj["subject"]["names"] == ["HOUSING"] and fj["subject_unresolved"] is False
    assert fj["feature_snapshot"][NID]["min_gap"] == 0.4   # §4.3.4 인용 원천 동결


def test_registry_merge_consumes_persisted_findings(seeded):
    _persist(seeded)
    merged = registry.merge(seeded, TARGET)
    assert merged["findings"] == 2 and merged["clusters"] == 2

    rows = seeded.query(
        "SELECT cluster_key, direction, contested, merged_json FROM rr_registry WHERE target_key = ?"
        " ORDER BY direction", (TARGET,))
    risk = [r for r in rows if r["direction"] == "risk"][0]
    body = json.loads(risk["merged_json"])
    assert risk["contested"] == 1                       # 지정 반대석 contested_by 를 세었다
    assert body["claim"] == "낙하 시 상단 리브에 응력이 집중된다"
    assert body["warrant"].startswith("리브가 얇아")
    assert body["raised_by"] == ["mech-housing-structure"]
    assert body["cites"] == [{"ref": NID, "quote": QUOTE}]
    assert body["names"] == ["HOUSING"] and body["trigger_condition"] == "load.drop"
    assert body["owner_domain"] == "mech"
    assert body["resolving_checks"] == ["sim:report_part_risk"]
    assert NID in body["feature_snapshot"]


def test_persist_writes_claim_refs_and_character(seeded):
    _persist(seeded)
    refs = seeded.query(
        "SELECT claim_uid, ref_type, ref, quote, dangling, owner_sub, target_key FROM rr_claim_refs"
        " ORDER BY claim_uid, ref")
    assert {r["claim_uid"] for r in refs} == {f"{PANEL}#F1", f"{PANEL}#G1"}
    assert all(r["ref"] == NID and r["ref_type"] == "p" and r["dangling"] == 0 for r in refs)
    assert all(r["owner_sub"] == OWNER and r["target_key"] == TARGET for r in refs)

    chars = seeded.query(
        "SELECT id, project_id, facet, tag, tags_json, statement, polarity, by_json, status,"
        " first_target_key FROM rr_character WHERE project_id = ?", (PROJECT,))
    assert [c["id"] for c in chars] == [f"{PANEL}#C1"]
    assert chars[0]["facet"] == "vulnerability" and chars[0]["status"] == "panel"
    assert chars[0]["tag"] == "char:analysis:ecad_absent"
    assert json.loads(chars[0]["by_json"]) == ["mech-housing-structure"]
    assert chars[0]["first_target_key"] == TARGET


def test_engine_evidence_marker_in_cites_is_not_counted_as_a_dangling_reference(seeded):
    """의장이 엔진의 근거 표지(`[e:N]` · `[e:N|KEY]`)를 risk_spec cites 에 옮겨 적어도 dangling 으로 세지 않는다.

    dangling 은 '실재하지 않는 것을 가리켰다' 는 표시다(§0.2.1 (2) — 지어낸 참조). 표지는 엔진이 브리프 항목에
    붙이고 결정문에 적으라고 시킨 번호다. 그걸 dangling 으로 세면 지시를 따른 패널마다 `dangling_n` 이 오르고
    (P3 통과 기준은 dangling 0 이다) 진짜 지어낸 참조가 그 속에 묻힌다.
    """
    spec = _spec()
    spec["findings"][0]["cites"] = [{"ref": NID, "quote": QUOTE}, {"ref": "[e:3|E3]", "quote": ""}]
    spec["gains"][0]["cites"] = [{"ref": "e:2", "quote": ""}, {"ref": "p:ffffffffffff", "quote": ""}]
    narrative.persist_panel_result(seeded, PANEL, decision_text=_decision_text(spec), spec=spec, turns=_turns(),
                                   attribution={"seats": {}, "extra_seats": []})

    rows = {r["claim_uid"]: r for r in seeded.query(
        "SELECT claim_uid, dangling, evidence_grade, finding_json FROM rr_findings WHERE panel_id = ?", (PANEL,))}
    f1, g1 = rows[f"{PANEL}#F1"], rows[f"{PANEL}#G1"]
    assert f1["dangling"] == 0 and json.loads(f1["finding_json"])["dangling"] == []
    assert f1["evidence_grade"] == "도구예측"            # 등급은 종전대로 진짜 참조(p:)만 센다
    # 버리지 않는다 — 의장이 적은 그대로 남는다.
    assert {"ref": "[e:3|E3]", "quote": ""} in json.loads(f1["finding_json"])["cites"]
    # 실재하지 않는 참조는 여전히 dangling 이다. 빠지는 것은 표지뿐이다.
    assert g1["dangling"] == 1 and json.loads(g1["finding_json"])["dangling"] == ["p:ffffffffffff"]
    assert g1["evidence_grade"] == "경험칙"              # 표지만으로는 등급이 오르지 않는다

    quality = {r["agent_key"]: json.loads(r["quality_json"]) for r in seeded.query(
        "SELECT agent_key, quality_json FROM rr_seat_opinions WHERE panel_id = ?", (PANEL,))}
    assert quality["mech-housing-structure"]["dangling_n"] == 0
    assert quality["sim-drop-impact"]["dangling_n"] == 1

    # 표지는 참조가 아니라서 역색인에 앉지 않는다 — 같은 번호가 패널마다 다른 항목을 가리킨다.
    refs = seeded.query("SELECT claim_uid, ref, dangling FROM rr_claim_refs ORDER BY claim_uid, ref")
    assert [(r["claim_uid"], r["ref"], r["dangling"]) for r in refs] == [
        (f"{PANEL}#F1", NID, 0), (f"{PANEL}#G1", "p:ffffffffffff", 1)]


def test_persist_writes_seat_opinions(seeded):
    out = _persist(seeded)

    assert {s["agent_key"] for s in out["seats"]} == {s["key"] for s in SEATS}
    rows = seeded.query(
        "SELECT opinion_id, agent_key, domain, origin, cycle, final_stance, tool_calls_n, tool_calls_ok,"
        " cited_refs_json, raised_finding_ids_json, excerpt_for_rag, opinion_json FROM rr_seat_opinions"
        " WHERE panel_id = ? ORDER BY agent_key", (PANEL,))
    by_key = {r["agent_key"]: r for r in rows}
    # 발언·귀속이 있는 좌석만 의견 행이 된다 — contested_by 에만 등장한 지정 반대석은 행을 만들지 않는다.
    assert set(by_key) == {"mech-housing-structure", "sim-drop-impact"}

    mech = by_key["mech-housing-structure"]
    assert mech["origin"] == "primary" and mech["final_stance"] == "oppose"
    assert mech["tool_calls_n"] == 2 and mech["tool_calls_ok"] == 2
    assert NID in json.loads(mech["cited_refs_json"])
    assert json.loads(mech["raised_finding_ids_json"]) == [f"{PANEL}#F1"]
    assert "상단 리브 단면이 얇다" in mech["excerpt_for_rag"]
    assert json.loads(mech["opinion_json"])["quality"]["cited_ir"] is True

    # 지정 반대석의 기각은 의견 행 없이도 회계된다(§6.7.2 8단계).
    assert registry.ADVERSARY_KEY not in {s["agent_key"] for s in out["seats"]}
    assert out["adversary_rejects"] == 1
    assert out["grade_dist"] == {"도구예측": 2}


def test_persist_is_idempotent_on_resubmit(seeded):
    first = _persist(seeded)
    second = _persist(seeded)

    assert first["seats"] == second["seats"]
    counts = {
        table: seeded.query_one(f"SELECT COUNT(*) AS n FROM {table} WHERE panel_id = ?", (PANEL,))["n"]
        for table in ("rr_findings", "rr_seat_opinions")
    }
    assert counts == {"rr_findings": 2, "rr_seat_opinions": 2}
    assert seeded.query_one("SELECT COUNT(*) AS n FROM rr_claim_refs", ())["n"] == 2
    assert seeded.query_one("SELECT COUNT(*) AS n FROM rr_character", ())["n"] == 1


def test_persist_without_spec_keeps_seat_opinions(seeded):
    out = _persist(seeded, spec_present=False)

    assert out["spec_parse_failed"] is True and out["findings_total"] == 0
    assert seeded.query_one("SELECT COUNT(*) AS n FROM rr_findings", ())["n"] == 0
    assert seeded.query_one("SELECT COUNT(*) AS n FROM rr_character", ())["n"] == 0
    assert {s["agent_key"] for s in out["seats"]} == {s["key"] for s in SEATS}
    assert seeded.query_one("SELECT COUNT(*) AS n FROM rr_seat_opinions WHERE panel_id = ?", (PANEL,))["n"] == 2


def test_persist_records_actor_unverified(seeded):
    _persist(seeded, actor="caller@example.com")
    row = seeded.query_one(
        "SELECT quality_json FROM rr_seat_opinions WHERE panel_id = ? AND agent_key = ?",
        (PANEL, "sim-drop-impact"))
    quality = json.loads(row["quality_json"])
    assert quality["actor"] == "caller@example.com" and quality["actor_verified"] is False


def test_persist_rejects_unknown_panel(seeded):
    with pytest.raises(AppError) as err:
        narrative.persist_panel_result(seeded, "NOPE", decision_text="", spec=None, turns=())
    assert err.value.http_status == 404 and err.value.code == "E404"


def test_complete_panel_route_uses_real_persist(seeded, monkeypatch):
    """routes.complete_panel 의 getattr 배선이 실제로 켜졌는지 — 501 없이 원자가 앉는다(§6.7.2 8단계)."""
    from app import routes

    monkeypatch.setattr(routes, "get_store", lambda: seeded)
    out = routes.complete_panel(
        PANEL, engine="web", decision_text=_decision_text(_spec()), turns=_turns(),
        events=None, model="fake-model-1", actor=OWNER, actor_verified=True, owner_sub=OWNER)

    assert out["parsed"] is True and out["coverage_updated"] is True
    assert out["findings_n"] == 2 and out["clusters"] == 2
    assert seeded.query_one("SELECT status FROM rr_panels WHERE id = ?", (PANEL,))["status"] == "done"
    assert seeded.query_one("SELECT COUNT(*) AS n FROM rr_findings WHERE panel_id = ?", (PANEL,))["n"] == 2


# ---------------------------------------------------------------- 브리프 되먹임(§5.6)


def test_prior_evidence_wraps_build_brief(seeded, monkeypatch):
    """E0c 는 러너가 다시 끼우므로 빠지고, 나머지는 build_brief 결과를 그대로 돌려준다(중복 구현 없음)."""
    from app import brief as brief_module

    calls: dict = {}

    def fake_build_brief(store, target_key, *, seats=None, panel_id=None, exclude=(), **kw):
        calls["args"] = {"target_key": target_key, "seats": seats, "panel_id": panel_id,
                         "exclude": tuple(exclude)}
        return {
            "keys": ["E0", "E0c", "E1"],
            "evidence": [{"source": "scope", "tool": "state", "result": "E0"},
                         {"source": "contract", "tool": "seat", "result": "E0c"},
                         {"source": "summary", "tool": "state", "result": "E1"}],
        }

    monkeypatch.setattr(brief_module, "build_brief", fake_build_brief)
    items = narrative.prior_evidence(seeded, TARGET, seats=SEATS, panel_id=PANEL, exclude=("E6",))

    assert calls["args"] == {"target_key": TARGET, "seats": SEATS, "panel_id": PANEL, "exclude": ("E6",)}
    assert [i["result"] for i in items] == ["E0", "E1"]


def test_prior_evidence_appends_user_memo(seeded, monkeypatch):
    from app import brief as brief_module

    monkeypatch.setattr(brief_module, "build_brief",
                        lambda *a, **kw: {"keys": ["E0"], "evidence": [{"source": "scope", "result": "E0"}]})
    items = narrative.prior_evidence(seeded, TARGET, user_memo="사용자 메모")

    assert items[-1] == {"source": "user_memo", "tool": "note", "args": TARGET, "result": "사용자 메모",
                         "key": "M"}


def test_prior_evidence_runs_on_real_store(seeded):
    """러너 기본 경로 시그니처(store, target_key, panel_id=…) 로 실제 브리프를 조립한다."""
    items = narrative.prior_evidence(seeded, TARGET, panel_id=PANEL)

    assert items and all({"source", "tool", "result"} <= set(i) for i in items)
    assert not any(str(i.get("source")).startswith("좌석 계약") for i in items)
    assert all(len(str(i.get("result") or "")) <= 2000 for i in items)
