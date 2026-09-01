# brief — E0~E9 라인 예산(드롭 0)·항목별 상한·모델 출처 표기(D6)·유사 검색 호출 형식(plan §5.6·§5.7·§7.3)
from __future__ import annotations

import json

import pytest

from app import brief
from app.errors import AppError
from app.ra_client import empty_sync

OWNER = "me@example.com"


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------- 시드(plan §5.2.2 DDL 컬럼 그대로)
def _seed_projects(store) -> None:
    store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, predecessor_project_id, character_status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("p_prev", OWNER, "DV1", "전작", None, "confirmed", 100, 100))
    store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, predecessor_project_id, character_status,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("p_now", OWNER, "DV2", "현재", "p_prev", "seed", 200, 200))


def _add_snapshot(store, snapshot_id: str, project_id: str, ir: dict) -> None:
    store.execute(
        "INSERT INTO rr_snapshots(id, project_id, owner_sub, ir_version, ir_hash, ir_json, source_ids_json,"
        " kinds_json, node_count, edge_count, missing_json, warnings_n, degraded, adapter_versions_json,"
        " created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (snapshot_id, project_id, OWNER, "ir-1", "h_" + snapshot_id, _j(ir),
         _j([{"kind": "mcad", "app_key": "step_forge", "ref": {"project_id": "42"},
              "tol_params": {"gap": 0.05}}]),
         _j(["mcad"]), 3, 2, _j([]), 1, None, _j({"mcad": "1.0"}), 300))


def _add_state(store, snapshot_id: str, summary: str, *, feature: dict | None = None) -> None:
    store.execute(
        "INSERT INTO rr_states(snapshot_id, owner_sub, state_json, feature_json, rule_hits_json,"
        " character_seed_json, gates_json, summary_text, summary_status, blocked, computed_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (snapshot_id, OWNER, _j({}),
         _j(feature or {"names": ["n_parts", "n_iface"], "values": [10.0, 4.0], "known": [True, True]}),
         _j([{"rule_id": "R-001", "severity": "중대", "pass": True, "found": ["e:0123456789ab"],
              "why_it_matters": "간섭이 auto 로 남아 있다"}]),
         _j({}), _j({"G1": {"pass": True}, "G2": {"pass": False}}), summary, "ok", 0, 400))


SUBJECT = "iface:ck:aaaa1111bbbb|ck:bbbb2222cccc"


def seed_diff_target(store, *, summary: str = "[의미] 배치가 바뀌었다 [c:5b0e11aa22bb]") -> str:
    """diff 타깃 하나와 E0~E9·M 이 모두 채워지는 최소 원장을 심는다. target_key 를 돌려준다."""
    _seed_projects(store)
    ir_target = {
        "dims_named": {"utg_edge_gap": {"value": 0.42, "unit": "mm", "method": "edge"}},
        "results": {"part_risk": [{"part": "HOUSING", "value": 1.2}]},
        "warnings": [{"code": "world_transform_absent", "severity": "중대",
                      "message": "world_transform 미기록", "ref": "p:0123456789ab"}],
    }
    _add_snapshot(store, "s_prev", "p_prev", {})
    _add_snapshot(store, "s_base", "p_now", {})
    _add_snapshot(store, "s_tgt", "p_now", ir_target)
    _add_state(store, "s_prev", "[개요] 전작 스냅샷 요약")
    _add_state(store, "s_tgt", "[개요] 현재 스냅샷 요약")

    store.execute(
        "INSERT INTO rr_ir_nodes(snapshot_id, nid, owner_sub, kind, name, name_norm, ckey)"
        " VALUES (?,?,?,?,?,?,?)",
        ("s_tgt", "n1", OWNER, "part", "HOUSING", "housing", "ck:aaaa1111bbbb"))
    store.execute(
        "INSERT INTO rr_ir_edges(snapshot_id, eid, owner_sub, kind, kind_family, a, b, subject_key)"
        " VALUES (?,?,?,?,?,?,?,?)",
        ("s_tgt", "e1", OWNER, "interference", "iface", "n1", "n1", SUBJECT))

    diff_json = {
        "dims_delta": [{"name": "utg_edge_gap", "base": 0.5, "target": 0.42, "unit": "mm",
                        "rel": -16.0, "method": "edge"}],
        "result_delta": [{"name": "max_stress", "base": 100, "target": 120, "unit": "MPa", "rel": 20.0}],
    }
    store.execute(
        "INSERT INTO rr_diffs(id, owner_sub, base_snapshot_id, target_snapshot_id, base_project_id,"
        " target_project_id, pair_kind, diff_version, diff_json, summary_text, summary_status, stats_json,"
        " comparability_json, gates_json, diff_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("d1", OWNER, "s_base", "s_tgt", "p_now", "p_now", "same_project_revision", "diff-1",
         _j(diff_json), summary, "ok", _j({}), _j({"result_parity": True}),
         _j({"G1": {"pass": True}}), "dh", 500))
    for cid, layer, code, magnitude in (("c:5b0e11aa22bb", "semantic", "iface.placement_moved", 2.0),
                                        ("c:aa11bb22cc33", "structural", "node.added", 1.0)):
        store.execute(
            "INSERT INTO rr_diff_events(diff_id, cid, owner_sub, layer, code, change_kind, subject_key,"
            " magnitude, unit, rel, confidence, unconfirmed, excluded_reason, text)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("d1", cid, OWNER, layer, code, "placement", SUBJECT, magnitude, "mm", None, "high",
             0, None, f"{code} 정규 표기"))

    for target_key, ref_id, project_id in (("diff:d1", "d1", "p_now"), ("diff:d0", "d0", "p_prev")):
        store.execute(
            "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, base_project_id,"
            " ir_hash, level, external_sync_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (target_key, OWNER, "diff", ref_id, project_id, "p_prev", "h_s_tgt", "C0",
             _j(empty_sync()), 600, 600))

    store.execute(
        "INSERT INTO rr_registry(target_key, cluster_key, owner_sub, visibility, merged_json, support,"
        " contested, direction, mechanism, mechanism_detail, change_kind, subject_key, severity, sev3,"
        " judgement, status, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("diff:d0", "clu1", OWNER, "org",
         _j({"subject_names": ["HOUSING", "BRACKET"], "claim": "간극이 0.42 mm 로 좁아졌다"}), 3, 1,
         "risk", "interface", "interference", "placement", SUBJECT, "중대", 2, "WARNING", "open", 700))
    store.execute(
        "INSERT INTO rr_character(id, project_id, owner_sub, facet, tag, statement, by_json,"
        " support_panels, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("ch1", "p_prev", OWNER, "intent", "char:intent:thin", "얇은 두께를 우선한 설계다",
         _j(["mech-housing-structure"]), 3, "confirmed", 800, 800))
    store.execute(
        "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, tier, seats_json, chair_template,"
        " rounds, engine, tool_mode, status, model_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("pan1", "diff:d1", OWNER, 1, "B", _j(SEATS), "risk-review", 3, "web", "tools", "done",
         _j({"model": "glm-4.6", "captured": "health_snapshot"}), 900))
    store.execute(
        "INSERT INTO rr_seat_opinions(opinion_id, target_key, panel_id, owner_sub, agent_key, domain,"
        " origin, cycle, opinion_json, final_stance, raised_finding_ids_json, excerpt_for_rag, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("op0", "diff:d0", "pan0", OWNER, "mech-housing-structure", "mech", "primary", 1, _j({}),
         "conditional", _j(["pan0#F1"]), "전작에서 같은 계면의 간극을 지적했다", 850))
    store.execute(
        "INSERT INTO rr_findings(finding_id, claim_uid, target_key, panel_id, project_id, owner_sub,"
        " direction, subject_key, cluster_key, finding_json, status, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("pan0#F1", "pan0#F1", "diff:d0", "pan0", "p_prev", OWNER, "risk", SUBJECT, "clu1",
         _j({}), "open", 860))
    store.execute(
        "INSERT INTO rr_delta_priors(change_kind, mechanism, mechanism_detail, n_raised, n_targets,"
        " n_verified, n_dismissed, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("placement", "interface", "interference", 7, 5, 3, 1, 870))
    store.execute(
        "INSERT INTO rr_jobs(id, target_key, owner_sub, tier, state, params_json, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        ("j1", "diff:d1", OWNER, "B", "queued", _j({"user_memo": "이 계면을 먼저 보라"}), 880, 880))
    return "diff:d1"


SEATS = [
    {"agent_key": "mech-housing-structure", "domain": "mech", "origin": "primary"},
    {"agent_key": "xd-a0", "domain": "xd", "origin": "primary"},
    {"agent_key": "sim-a0", "domain": "sim", "origin": "primary"},
    {"agent_key": "rel-a0", "domain": "rel", "origin": "primary"},
    {"agent_key": "delib-baseline-defender", "domain": "std", "origin": "counter"},
]


def seed_snap_target(store) -> str:
    """snap 타깃(같은 원장 위) — E2·E8 의 `[pair 전용 — 해당 없음]` 경로를 본다."""
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, base_project_id,"
        " ir_hash, level, external_sync_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("snap:s_tgt", OWNER, "snap", "s_tgt", "p_now", None, "h_s_tgt", "C0",
         _j(empty_sync()), 610, 610))
    return "snap:s_tgt"


class FakeAdh:
    """AdhClient 흉내 — 실 호출 없이 인자만 기록한다(실 LLM·네트워크 0)."""

    def __init__(self, *, hybrid=None, agent=None, available: bool = True) -> None:
        self.available = available
        self.calls: list[tuple[str, tuple, dict]] = []
        self._hybrid = hybrid or {"ok": False, "error": "no_hit"}
        self._agent = agent or {"ok": False, "error": "no_hit"}

    def hybrid_search(self, q, **kwargs):
        self.calls.append(("hybrid_search", (q,), kwargs))
        return self._hybrid

    def agent_search(self, agent_type, q, **kwargs):
        self.calls.append(("agent_search", (agent_type, q), kwargs))
        return self._agent


# ---------------------------------------------------------------- 라인 산식(엔진과 같은 식)
def test_evidence_line_matches_engine_format():
    item = {"source": "rr_diff", "tool": "summary_text", "args": "diff:d1", "result": "본문"}
    assert brief.evidence_line(item) == "· [rr_diff · summary_text(diff:d1)] 본문"
    # plan §5.6.1 오버헤드 규칙 — len(source)+len(tool)+len(args)+10.
    assert brief.line_overhead(item) == len("rr_diff") + len("summary_text") + len("diff:d1") + 10
    assert brief.line_overhead(item) == len(brief.evidence_line({**item, "result": ""}))


def test_evidence_line_drops_empty_meta_parts():
    assert brief.evidence_line({"source": "s", "tool": "t", "args": "", "result": "r"}) == "· [s · t] r"
    assert brief.evidence_line({"source": "s", "tool": "", "args": "x", "result": "r"}) == "· [s] r"


def test_caps_table_matches_plan_budget():
    assert set(brief.CAPS) == set(brief.ITEM_ORDER)
    assert sum(brief.CAPS.values()) == 10600
    assert sum(brief.CAPS.values()) <= brief.ENGINE_BUDGET == 11000
    assert len(brief.ITEM_ORDER) == brief.EVIDENCE_MAX_ITEMS == 12
    assert (brief.CLAMP_SOURCE, brief.CLAMP_TOOL, brief.CLAMP_ARGS, brief.CLAMP_RESULT) == \
        (120, 80, 400, 2000)


# ---------------------------------------------------------------- 절단 규칙(§5.6.2)
def test_clip_lines_keeps_whole_lines_and_marks_dropped():
    text = "\n".join(f"줄{i}" * 10 for i in range(6))
    out = brief.clip_lines(text, 120)
    assert len(out) <= 120
    lines = out.split("\n")
    assert lines[-1].endswith("줄 생략)")
    dropped = int(lines[-1].split("(")[1].split("줄")[0])
    assert dropped == 6 - (len(lines) - 1)
    # 잘린 줄은 통째로 빠진다 — 남은 줄은 원문 줄과 바이트 동일하다.
    assert all(line in text.split("\n") for line in lines[:-1])


def test_clip_lines_drops_a_single_overlong_line_entirely():
    out = brief.clip_lines("[c:5b0e11aa22bb] " + "가" * 200, 40)
    assert out == brief._ellipsis(1)
    assert "c:5b0e11aa22bb" not in out


def test_clip_lines_passes_short_text_through():
    assert brief.clip_lines("짧다", 100) == "짧다"
    assert brief.clip_lines("무엇이든", 0) == ""


# ---------------------------------------------------------------- 조립 정본(§5.6.2)
def test_build_brief_orders_items_and_stays_in_budget(risk_store):
    target_key = seed_diff_target(risk_store)
    out = brief.build_brief(risk_store, target_key)

    assert out["keys"] == list(brief.ITEM_ORDER)
    assert len(out["evidence"]) == len(out["keys"]) <= brief.EVIDENCE_MAX_ITEMS
    for key, item in zip(out["keys"], out["evidence"]):
        assert set(item) == {"source", "tool", "args", "result"}
        assert len(brief.evidence_line(item)) <= brief.CAPS[key], key
        assert len(item["result"]) <= brief.CLAMP_RESULT
        assert len(item["source"]) <= brief.CLAMP_SOURCE
        assert len(item["tool"]) <= brief.CLAMP_TOOL
        assert len(item["args"]) <= brief.CLAMP_ARGS
    total = sum(len(brief.evidence_line(i)) for i in out["evidence"])
    assert total == out["meta"]["budget_used"] <= brief.ENGINE_BUDGET
    assert out["meta"]["dropped"] == 0
    assert out["meta"]["caps_sum"] == 10600


def test_every_item_declares_its_source_table(risk_store):
    """§5.6.1 표의 source·원천 표(tool)가 항목마다 그대로 실린다."""
    target_key = seed_diff_target(risk_store)
    out = brief.build_brief(risk_store, target_key)
    for key, item in zip(out["keys"], out["evidence"]):
        assert (item["source"], item["tool"]) == brief._SOURCES[key], key
        first = item["result"].split("\n")[0]
        assert first.startswith(f"[검증 대상 — 결론 아님 · 원천: {item['source']} · 생성: ")
        assert len(first) <= brief.FRAMING_MAX


def test_e0_carries_model_provenance(risk_store):
    """D6 — E0 첫 줄 헤더에 그 패널의 model_json.model 을 `model=<name>` 으로 적는다."""
    target_key = seed_diff_target(risk_store)
    out = brief.build_brief(risk_store, target_key)
    header = out["evidence"][0]["result"].split("\n")[1]
    assert header.startswith("kind=diff target_key=diff:d1 level=C0 ")
    assert "model=glm-4.6" in header


def test_e0_model_is_unknown_without_panel_record(risk_store):
    target_key = seed_diff_target(risk_store)
    risk_store.execute("DELETE FROM rr_panels WHERE id = ?", ("pan1",))
    out = brief.build_brief(risk_store, target_key, seats=SEATS)
    assert "model=unknown" in out["evidence"][0]["result"].split("\n")[1]


def test_e0_reports_external_search_availability(risk_store):
    target_key = seed_diff_target(risk_store)
    off = brief.build_brief(risk_store, target_key)
    assert off["meta"]["external_search"] == "unavailable"
    assert "외부 검색 가용=false" in off["evidence"][0]["result"]

    on = brief.build_brief(risk_store, target_key, adh=FakeAdh())
    assert on["meta"]["external_search"] == "available"
    assert "외부 검색 가용=true" in on["evidence"][0]["result"]


def test_build_brief_is_deterministic(risk_store):
    target_key = seed_diff_target(risk_store)
    first = brief.build_brief(risk_store, target_key)
    second = brief.build_brief(risk_store, target_key)
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == \
        json.dumps(second, ensure_ascii=False, sort_keys=True)


def test_oversized_summary_is_clipped_inside_e1_cap(risk_store):
    long_summary = "\n".join(f"[의미] {i} 번째 줄 [c:5b0e11aa22bb] " + "가" * 60 for i in range(80))
    target_key = seed_diff_target(risk_store, summary=long_summary)
    out = brief.build_brief(risk_store, target_key)
    e1 = out["evidence"][out["keys"].index("E1")]
    assert len(brief.evidence_line(e1)) <= brief.CAPS["E1"]
    assert e1["result"].endswith("줄 생략)")
    assert out["meta"]["dropped"] == 0


def test_exclude_removes_items_only(risk_store):
    target_key = seed_diff_target(risk_store)
    full = brief.build_brief(risk_store, target_key)
    trimmed = brief.build_brief(risk_store, target_key, exclude=["E6", "E8"])
    assert trimmed["keys"] == [k for k in full["keys"] if k not in ("E6", "E8")]
    assert trimmed["meta"]["excluded"] == ["E6", "E8"]
    assert trimmed["meta"]["budget_used"] < full["meta"]["budget_used"]
    kept = dict(zip(trimmed["keys"], trimmed["evidence"]))
    assert kept["E5"] == dict(zip(full["keys"], full["evidence"]))["E5"]


def test_missing_target_raises_e404(risk_store):
    with pytest.raises(AppError) as exc:
        brief.build_brief(risk_store, "diff:nope")
    assert exc.value.code == "E404"


# ---------------------------------------------------------------- 결측 문구(§5.6.1 표 마지막 열)
def test_snap_target_uses_pair_only_placeholders(risk_store):
    seed_diff_target(risk_store)
    target_key = seed_snap_target(risk_store)
    out = brief.build_brief(risk_store, target_key, seats=SEATS)
    items = dict(zip(out["keys"], out["evidence"]))
    assert "[pair 전용 — 해당 없음]" in items["E2"]["result"]
    assert "[pair 전용 — 해당 없음]" in items["E8"]["result"]
    # §5.6.1 표 E1 행의 `rr_diff`/`rr_state` — snap 타깃은 rr_state 를 원천으로 적는다.
    assert (items["E1"]["source"], items["E1"]["tool"]) == ("rr_state", "rr_states")
    assert "원천: rr_state ·" in items["E1"]["result"]
    for key, item in zip(out["keys"], out["evidence"]):
        assert len(brief.evidence_line(item)) <= brief.CAPS[key], key


def test_empty_ledger_falls_back_to_missing_sentences(risk_store):
    _seed_projects(risk_store)
    _add_snapshot(risk_store, "s_bare", "p_now", {})
    risk_store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, level,"
        " external_sync_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("snap:s_bare", OWNER, "snap", "s_bare", "p_now", "h_s_bare", "C0", _j(empty_sync()), 1, 1))
    out = brief.build_brief(risk_store, "snap:s_bare", seats=SEATS)
    items = dict(zip(out["keys"], out["evidence"]))
    assert "[summary_text 없음 — summary_status=lint_failed]" in items["E1"]["result"]
    assert "[명명 치수 없음 — rr_dim_defs 0건]" in items["E3"]["result"]
    assert "[dyna_result 부재]" in items["E4"]["result"]
    assert "[선행 등록부 없음 — 이 과제 계보·유사 과제 0건]" in items["E5"]["result"]
    assert "[유사 과제 성격 진술 없음 — 코퍼스 n_projects=2]" in items["E6"]["result"]
    assert "[warnings 0 · rule_hits 0]" in items["E9"]["result"]
    assert "M" not in items                            # user_memo 없으면 항목 생략
    for line in items["E9"]["result"].split("\n")[1:] + items["E5"]["result"].split("\n")[1:]:
        assert len(line) <= brief.FRAMING_MAX          # 결측 문구는 80자 이하다


# ---------------------------------------------------------------- E7 고정 슬롯(§5.6.3)
def test_e7_fixed_slots_stay_inside_seat_budget(risk_store):
    target_key = seed_diff_target(risk_store)
    out = brief.build_brief(risk_store, target_key)
    e7 = out["evidence"][out["keys"].index("E7")]
    seat_lines = e7["result"].split("\n")[1:]

    assert len(seat_lines) == len(SEATS)
    assert all(len(line) <= brief.E7_SEAT_LINE for line in seat_lines)
    assert sum(len(line) for line in seat_lines) + len(seat_lines) - 1 <= brief.E7_SEAT_TOTAL
    assert seat_lines[0].startswith("narr:op0#pan0#F1 | mech-housing-structure | DV1/diff:d0 | ")
    assert seat_lines[1:] == [f"[{s['agent_key']}: 이전 발언 없음]" for s in SEATS[1:]]
    assert e7["args"] == ",".join(s["agent_key"] for s in SEATS)


def test_e7_second_path_uses_adh_agent_search(risk_store):
    """앱 DB 에 이전 발언이 없는 좌석은 AIDataHub 의사 에이전트 회수로 채운다(§5.6.3 2)."""
    target_key = seed_diff_target(risk_store)
    risk_store.execute("DELETE FROM rr_seat_opinions")
    adh = FakeAdh(agent={"ok": True, "result": [{
        "record_id": "rec-abcdef123456",
        "summary": "이전 과제에서 같은 계면의 간극을 재검사 대상으로 남겼다",
        "content": {"meta": {"portal": {"opinion_id": "op9", "finding_id": "pan9#F2"}}}}]})
    out = brief.build_brief(risk_store, target_key, adh=adh)
    seat_lines = out["evidence"][out["keys"].index("E7")]["result"].split("\n")[1:]

    assert seat_lines[0].startswith("narr:op9#pan9#F2 | mech-housing-structure | adh/rec-abcdef12 | ")
    assert all(len(line) <= brief.E7_SEAT_LINE for line in seat_lines)
    agent_calls = [c for c in adh.calls if c[0] == "agent_search"]
    assert len(agent_calls) == len(SEATS)
    name, args, kwargs = agent_calls[0]
    assert args[0] == "risk-review-memory"
    assert kwargs["mode"] == "hybrid"
    assert kwargs["top_k"] == 3
    assert kwargs["required_tags"] == ["hwax:expert:mech-housing-structure"]


def test_e7_says_no_prior_when_seats_are_empty(risk_store):
    target_key = seed_diff_target(risk_store)
    out = brief.build_brief(risk_store, target_key, seats=[])
    e7 = out["evidence"][out["keys"].index("E7")]
    assert e7["result"].split("\n")[1] == "[착석 좌석 없음]"
    assert e7["args"] == ""


# ---------------------------------------------------------------- 인용 추적(§5.6.4)
def test_collect_refs_tracks_five_schemes_in_order(risk_store):
    target_key = seed_diff_target(risk_store)
    out = brief.build_brief(risk_store, target_key)
    assert out["refs"] == ["c:5b0e11aa22bb", "c:aa11bb22cc33", "d:utg_edge_gap",
                           "reg:diff:d0#clu1", "narr:ch1", "narr:op0#pan0#F1", "rule:R-001"]
    assert len(out["refs"]) == len(set(out["refs"]))
    assert all(ref.split(":")[0] in brief._TRACKED_SCHEMES for ref in out["refs"])


def test_collect_refs_ignores_untracked_schemes():
    items = [{"result": "warn:code#p:0123456789ab sig:counts.parts rpt:12 c:5b0e11aa22bb"}]
    assert brief.collect_refs(items) == ["c:5b0e11aa22bb"]


def test_lint_meta_is_reported(risk_store):
    target_key = seed_diff_target(risk_store)
    lint = brief.build_brief(risk_store, target_key)["meta"]["lint"]
    assert set(lint) == {"ok", "reason", "violations"}
    assert lint["violations"] == []


# ---------------------------------------------------------------- §5.7 유사 검색 호출 계약
def test_similar_projects_returns_contract_shape(risk_store):
    seed_diff_target(risk_store)
    out = brief.similar_projects(risk_store, "p_now")
    assert set(out) == {"lineage", "vector", "text", "subject", "merged", "corpus_n", "reason"}
    assert out["lineage"] == [{"project_id": "p_prev", "code": "DV1", "hops": 1,
                               "relation": "predecessor"}]
    assert out["subject"][0]["subject_key"] == SUBJECT
    assert out["subject"][0]["path"] == "subject"
    merged = {e["project_id"]: e for e in out["merged"]}
    assert merged["p_prev"]["paths"] == ["lineage", "subject"]
    assert merged["p_prev"]["score"] == pytest.approx(5.0)     # §7.3 계보 3 + subject 2


def test_similar_projects_closes_vector_path_below_min_corpus(risk_store):
    seed_diff_target(risk_store)
    out = brief.similar_projects(risk_store, "p_now")
    assert out["corpus_n"] == 2 < brief.VECTOR_MIN_CORPUS
    assert out["vector"] == []
    assert out["reason"]["vector"] == "corpus_n=2 < 5"
    assert out["reason"]["text"] == "external_sync=unavailable"


def test_similar_projects_opens_vector_path_with_enough_corpus(risk_store):
    seed_diff_target(risk_store)
    for n in range(4):
        project_id = f"p_x{n}"
        risk_store.execute(
            "INSERT INTO rr_projects(id, owner_sub, code, created_at, updated_at) VALUES (?,?,?,?,?)",
            (project_id, OWNER, f"X{n}", 100, 100))
        _add_snapshot(risk_store, f"s_x{n}", project_id, {})
        _add_state(risk_store, f"s_x{n}", f"[개요] X{n}",
                   feature={"names": ["n_parts", "n_iface"], "values": [10.0 + n, 4.0 - n],
                            "known": [True, True]})
    out = brief.similar_projects(risk_store, "p_now")
    assert out["corpus_n"] == 6 >= brief.VECTOR_MIN_CORPUS
    assert out["reason"]["vector"] is None
    assert [e["rank"] for e in out["vector"]] == list(range(1, len(out["vector"]) + 1))
    assert len(out["vector"]) <= 5
    for entry in out["vector"]:
        assert set(entry) == {"project_id", "snapshot_id", "cosine", "top_features", "rank"}
        assert len(entry["top_features"]) <= 3
    # 절대 코사인 임계는 없다 — 순위만 쓰므로 낮은 값도 목록에 남는다(§7.3 2단계).
    assert min(e["cosine"] for e in out["vector"]) < 1.0
    assert [e["cosine"] for e in out["vector"]] == sorted((e["cosine"] for e in out["vector"]),
                                                          reverse=True)


def test_text_path_calls_hybrid_search_with_summary_head(risk_store):
    """§7.3 3단계 — q 는 최신 스냅샷 summary_text 앞 300자, tags 에 hwax-risk-review."""
    seed_diff_target(risk_store)
    risk_store.execute("UPDATE rr_states SET summary_text = ? WHERE snapshot_id = 's_tgt'",
                       ("[개요] " + "가" * 500,))
    adh = FakeAdh(hybrid={"ok": True, "result": [
        {"record_id": "rec1", "tags": ["hwax-risk-review", "hwax:project:p_prev"], "section_id": "2"},
        {"record_id": "rec2", "tags": ["hwax:project:p_now"]},          # 자기 자신은 뺀다
        {"record_id": "rec3", "tags": ["hwax-risk-review"]},            # 과제 환원 불가
    ]})
    out = brief.similar_projects(risk_store, "p_now", adh=adh)

    name, args, kwargs = adh.calls[0]
    assert name == "hybrid_search"
    assert len(args[0]) == 300 and args[0].startswith("[개요] 가")
    assert kwargs["top_k"] == 5
    assert "hwax-risk-review" in kwargs["tags"]
    assert out["text"] == [{"record_id": "rec1", "project_id": "p_prev", "rank": 1, "section_id": "2"}]
    assert out["reason"]["text"] is None


def test_text_path_reports_reason_when_search_fails(risk_store):
    seed_diff_target(risk_store)
    adh = FakeAdh(hybrid={"ok": False, "error": "http_401"})
    out = brief.similar_projects(risk_store, "p_now", adh=adh)
    assert out["text"] == []
    assert out["reason"]["text"] == "http_401"


def test_visibility_filter_hides_other_owners_registry(risk_store):
    seed_diff_target(risk_store)
    risk_store.execute("UPDATE rr_registry SET owner_sub = ?, visibility = 'private' WHERE cluster_key = ?",
                       ("other@example.com", "clu1"))
    out = brief.similar_projects(risk_store, "p_now", owner_sub=OWNER)
    assert out["subject"] == []
    brief_out = brief.build_brief(risk_store, "diff:d1", owner_sub=OWNER)
    e5 = brief_out["evidence"][brief_out["keys"].index("E5")]
    assert "[선행 등록부 없음 — 이 과제 계보·유사 과제 0건]" in e5["result"]


# ---------------------------------------------------------------- §5.7 선례 패널
def test_precedents_returns_panel_payload(risk_store):
    seed_diff_target(risk_store)
    risk_store.execute(
        "INSERT INTO rr_patterns(id, owner_sub, cluster_key_norm, mechanism, mechanism_detail,"
        " change_kind, status, n_projects, precision, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("P-017", OWNER, "interface.interference|placement", "interface", "interference",
         "placement", "known", 5, 0.71, 900, 900))
    out = brief.precedents(risk_store, "d1", owner_sub=OWNER)
    assert set(out) == {"delta_priors", "clusters", "rule_hits", "pattern_candidates"}
    assert out["delta_priors"] == [{"change_kind": "placement", "mechanism": "interface",
                                    "mechanism_detail": "interference", "n_raised": 7,
                                    "n_targets": 5, "n_verified": 3, "n_dismissed": 1}]
    assert out["clusters"][0]["reg_ref"] == "reg:diff:d0#clu1"
    assert out["clusters"][0]["project_code"] == "DV1"
    assert out["clusters"][0]["path"] == "subject"
    assert out["rule_hits"][0]["rule_id"] == "R-001"
    assert out["pattern_candidates"] == [{"pattern_id": "P-017", "status": "known",
                                          "n_projects": 5, "precision": 0.71}]


def test_precedents_missing_diff_raises_e404(risk_store):
    with pytest.raises(AppError) as exc:
        brief.precedents(risk_store, "nope")
    assert exc.value.code == "E404"


def test_lint_items_uses_the_render_linter_and_strict_mode_raises(risk_store):
    """린터 이름이 어긋나면 브리프가 검사되지 않고 조용히 통과한다 — 그 자리를 잠근다(plan §0.9 P5-8)."""
    from app import render

    assert brief.lint_items.__module__ == "app.brief"
    planted = [{"key": "E5", "source": "rr_registry.prior", "tool": "prior", "args": "t",
                "result": "[검증 대상] 이 계면은 치명적 위험이며 반드시 개선해야 한다"}]
    lint = brief.lint_items(planted)
    assert lint["ok"] is False and lint["reason"] is None
    assert {v["token"] for v in lint["violations"]} >= {"위험", "개선"}
    # 같은 줄을 render 린터에 직접 넣은 결과와 같은 판정이어야 한다(두 경로가 한 사전을 본다).
    assert render.lint_text(planted[0]["result"])["ok"] is False

    # 자산 원문(좌석 계약)은 인용이라 검사 대상이 아니다.
    assert brief.lint_items([{"key": "E0c", "source": "seat_contract",
                              "result": "리스크만 나열하지 말고 개선점도 같은 규격으로"}])["ok"] is True

    target_key = seed_diff_target(risk_store)
    clean = brief.build_brief(risk_store, target_key, strict_lint=True)
    assert clean["meta"]["lint"]["ok"] is True


def test_strict_lint_raises_when_an_item_carries_a_judgement_word(risk_store, monkeypatch):
    """strict_lint 조립 경로는 판단어가 섞이면 E500 으로 멈춘다."""
    target_key = seed_diff_target(risk_store)
    original = brief._item_e9

    def poisoned(*args, **kwargs):
        item = original(*args, **kwargs)
        item["result"] = "[경고] 이 계면은 위험하다"
        return item

    monkeypatch.setattr(brief, "_item_e9", poisoned)
    with pytest.raises(AppError) as exc:
        brief.build_brief(risk_store, target_key, strict_lint=True)
    assert exc.value.code == "E500"


# ---------------------------------------------------------------- 코퍼스 필터가 회수에 걸린다(plan §0.6·§0.9 P5-11)
def test_corpus_excluded_project_drops_out_of_recall(risk_store):
    """corpus_excluded=1 로 바꾸면 E5·E6 에서 그 과제가 빠지고 코퍼스 수도 준다."""
    target_key = seed_diff_target(risk_store)
    before = brief.build_brief(risk_store, target_key, owner_sub=OWNER)
    before_e5 = next(i["result"] for i, k in zip(before["evidence"], before["keys"]) if k == "E5")
    before_similar = brief.similar_projects(risk_store, "p_now", owner_sub=OWNER)
    assert "p_prev" in {e["project_id"] for e in before_similar["merged"]}
    assert "[선행 등록부 없음" not in before_e5

    risk_store.execute(
        "UPDATE rr_projects SET corpus_excluded = 1, excluded_reason = 'fixture' WHERE id = 'p_prev'")
    after = brief.build_brief(risk_store, target_key, owner_sub=OWNER)
    after_e5 = next(i["result"] for i, k in zip(after["evidence"], after["keys"]) if k == "E5")
    after_e6 = next(i["result"] for i, k in zip(after["evidence"], after["keys"]) if k == "E6")
    assert after_e5 != before_e5 and "[선행 등록부 없음" in after_e5
    assert "n_projects=1" in after_e6                       # p_now 하나만 남는다
    after_similar = brief.similar_projects(risk_store, "p_now", owner_sub=OWNER)
    assert "p_prev" not in {e["project_id"] for e in after_similar["merged"]}


# ---------------------------------------------------------------- E5 세 블록(plan §5.6.1·§0.9 P5-12)
def _e5(built: dict) -> str:
    return next(i["result"] for i, k in zip(built["evidence"], built["keys"]) if k == "E5")


def test_e5_splits_living_and_rejected_precedents(risk_store):
    """기각·반증 선례는 E5− 블록에만 실리고 E5+ 에는 0건이다."""
    target_key = seed_diff_target(risk_store)
    risk_store.execute(
        "INSERT INTO rr_registry(target_key, cluster_key, owner_sub, visibility, merged_json, support,"
        " contested, rejected, direction, mechanism, mechanism_detail, change_kind, subject_key, severity,"
        " sev3, judgement, status, status_source, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("diff:d0", "clu_rejected", OWNER, "org",
         _j({"subject_names": ["HOUSING"], "claim": "기각된 주장",
             "contest_notes": [{"finding_id": "F9", "by": ["adv"], "note": "재현되지 않았다"}]}),
         0, 1, 2, "risk", "interface", "interference", "placement", SUBJECT, "중대", 2, "WARNING",
         "rejected_in_panel", "code", 700))

    body = _e5(brief.build_brief(risk_store, target_key, owner_sub=OWNER))
    positive, negative = body.split("[E5− 기각·반증 선례]")
    assert "[E5+ 살아 있는 선례]" in positive
    assert "clu_rejected" not in positive                       # 기각은 살아 있는 선례가 아니다
    assert "clu_rejected" in negative and "rejected 2" in negative
    assert "[E10 필드·VOC·문헌 근거]" in negative
    assert "[필드·문헌 근거 없음 — 제품 연결 미등록]" in negative


def test_e5_missing_blocks_use_their_own_wording(risk_store):
    """기각 선례가 0건이면 그 블록만 결측 문구다(빈 블록을 만들지 않는다)."""
    target_key = seed_diff_target(risk_store)
    body = _e5(brief.build_brief(risk_store, target_key, owner_sub=OWNER))
    assert "[기각된 선례 없음 — 이 조합에서 기각 0건]" in body
    assert "[선행 등록부 없음" not in body                       # 살아 있는 선례는 있다


def test_recall_searches_always_exclude_three_status_tags():
    """회수 검색은 기각·철회·대체 태그를 항상 뺀다(plan §5.6.3 상태 필터)."""
    assert brief.RECALL_EXCLUDE_TAGS == ("status:dismissed", "status:rejected_in_panel", "status:superseded")


# ---------------------------------------------------------------- 계면 별칭 회수(plan §5.9.4·§0.9 P5-5)
def test_interface_alias_recovers_a_precedent_without_lineage(risk_store):
    """계보가 없고 이름 규칙이 다른 과제라도 rr_iface_alias 가 이어 주면 E5 에 그 줄이 실린다."""
    target_key = seed_diff_target(risk_store)
    # 계보를 끊고(전작 링크 제거) 이전 과제 등록부의 subject_key 를 이름 기반 키로 바꾼다.
    risk_store.execute("UPDATE rr_projects SET predecessor_project_id = NULL WHERE id = 'p_now'")
    alias_key = "iface:housing|bracket"
    risk_store.execute("UPDATE rr_registry SET subject_key = ? WHERE cluster_key = 'clu1'", (alias_key,))
    assert "clu1" not in _e5(brief.build_brief(risk_store, target_key, owner_sub=OWNER))

    canonical = SUBJECT.split(":", 1)[1] if SUBJECT.startswith("iface:") else SUBJECT
    a, b = canonical.split("|")
    risk_store.execute(
        "INSERT INTO rr_iface_alias(alias_key, canonical_a, canonical_b, owner_sub, visibility,"
        " aliases_json, source, score, status, created_at, updated_at)"
        " VALUES (?,?,?,?, 'org', '[]', 'human', 1.0, 'active', 1, 1)",
        (alias_key, a, b, OWNER))
    body = _e5(brief.build_brief(risk_store, target_key, owner_sub=OWNER))
    assert "clu1" in body and "subject·별칭" in body


def test_alias_expand_is_bidirectional_and_ignores_revoked_rows(risk_store):
    risk_store.execute(
        "INSERT INTO rr_iface_alias(alias_key, canonical_a, canonical_b, owner_sub, visibility,"
        " aliases_json, source, score, status, created_at, updated_at)"
        " VALUES ('a|b', 'ck:1', 'ck:2', ?, 'org', '[]', 'human', 1.0, 'active', 1, 1)", (OWNER,))
    risk_store.execute(
        "INSERT INTO rr_iface_alias(alias_key, canonical_a, canonical_b, owner_sub, visibility,"
        " aliases_json, source, score, status, created_at, updated_at)"
        " VALUES ('x|y', 'ck:8', 'ck:9', ?, 'org', '[]', 'human', 1.0, 'revoked', 1, 1)", (OWNER,))
    assert brief.alias_expand(risk_store, {"a|b"}) == {
        "a|b": "subject", "ck:1|ck:2": "subject·별칭", "iface:ck:1|ck:2": "subject·별칭"}
    assert brief.alias_expand(risk_store, {"ck:1|ck:2"}) == {"ck:1|ck:2": "subject", "a|b": "subject·별칭"}
    assert brief.alias_expand(risk_store, {"x|y"}) == {"x|y": "subject"}


def test_human_raised_precedent_is_marked_and_can_be_turned_off(risk_store, monkeypatch):
    """사람 제기 선례는 접두로 드러나고 risk_prior_include_human=false 면 그 줄이 빠진다(plan §0.9 P5-10)."""
    import dataclasses

    from app import config

    target_key = seed_diff_target(risk_store)
    risk_store.execute(
        "INSERT INTO rr_registry(target_key, cluster_key, owner_sub, visibility, merged_json, support,"
        " contested, rejected, human_n, direction, mechanism, mechanism_detail, change_kind, subject_key,"
        " severity, sev3, judgement, status, status_source, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("diff:d0", "clu_human", OWNER, "org",
         _j({"subject_names": ["HOUSING"], "claim": "사람이 제기한 주장", "human_refs": ["diff:d0#H1"]}),
         0, 0, 0, 1, "risk", "interface", "interference", "placement", SUBJECT, "중대", 2, "WARNING",
         "open", "code", 700))

    body = _e5(brief.build_brief(risk_store, target_key, owner_sub=OWNER))
    assert "[사람 제기·검증 대상] reg:diff:d0#clu_human" in body

    monkeypatch.setattr(config, "settings",
                        dataclasses.replace(config.settings, risk_prior_include_human=False))
    without = _e5(brief.build_brief(risk_store, target_key, owner_sub=OWNER))
    assert "clu_human" not in without and "clu1" in without
