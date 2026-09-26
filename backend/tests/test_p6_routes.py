# P6 REST 경로 시험 — 사람 라벨·지표 재계산·큐레이션 결정·승격 상태 조회와 등록부→라벨 연결(plan §7.5·§7.6·§8.2.3)
from __future__ import annotations

import json
import pathlib

import pytest

from app import common, learning, metrics, routes
from app.errors import AppError

OWNER = "owner@example.com"
OTHER = "other@example.com"
PROJECT = "P1"
TARGET = "T1"
PANEL = "PN1"
CK_A = "ck:aaaaaaaaaaaa"


def _ident(email: str | None = OWNER):
    return type("I", (), {"anonymous": email is None, "email": email,
                          "to_dict": lambda self: {"email": email}})()


@pytest.fixture
def clock():
    state = {"t": 10_000_000}
    previous = common.set_clock(lambda: state["t"])
    yield state
    common.set_clock(previous)


@pytest.fixture
def store(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    return risk_store


# ---------------------------------------------------------------- 씨앗(test_metrics.py 와 같은 모양)
def _project(store, project_id=PROJECT, *, owner_sub=OWNER, corpus_excluded=0):
    store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, corpus_excluded, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 1, 1)", (project_id, owner_sub, project_id, corpus_excluded))


def _target(store, target_key=TARGET, *, owner_sub=OWNER, project_id=PROJECT):
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, "
        "external_sync_json, created_at, updated_at) VALUES (?, ?, 'snap', 'S1', ?, '0123456789ab', "
        "'{}', 100, 100)", (target_key, owner_sub, project_id))


def _panel(store, panel_id=PANEL, *, target_key=TARGET, owner_sub=OWNER, model="glm-4.6"):
    store.execute(
        "INSERT INTO rr_panels(id, target_key, owner_sub, panel_no, seats_json, status, model_json, "
        "created_at) VALUES (?, ?, ?, 1, '[]', 'done', ?, 1)",
        (panel_id, target_key, owner_sub, json.dumps({"model": model, "captured": "health_snapshot"})))


def _opinion(store, opinion_id, agent_key, *, target_key=TARGET, panel_id=PANEL, owner_sub=OWNER):
    store.execute(
        "INSERT INTO rr_seat_opinions(opinion_id, target_key, panel_id, owner_sub, agent_key, domain, "
        "cycle, opinion_json, created_at) VALUES (?, ?, ?, ?, ?, 'mech', 1, '{}', 1)",
        (opinion_id, target_key, panel_id, owner_sub, agent_key))


def _finding(store, finding_id, *, cluster_key=CK_A, target_key=TARGET, project_id=PROJECT,
             owner_sub=OWNER, opinion_id=None, panel_id=PANEL, status="open", status_source="code"):
    store.execute(
        "INSERT INTO rr_findings(finding_id, claim_uid, origin, target_key, panel_id, opinion_id, "
        "project_id, owner_sub, direction, domain, mechanism, mechanism_detail, change_kind, subject_key, "
        "severity, sev3, judgement, evidence_grade, precedent, cluster_key, finding_json, status, "
        "status_source, created_at, updated_at) VALUES (?, ?, 'llm', ?, ?, ?, ?, ?, 'risk', 'mech', "
        "'thermal', 'cte_mismatch', 'dimension', ?, '중대', 2, 'WARNING', '문헌·규격', 'in_range', ?, "
        "'{}', ?, ?, 100, 100)",
        (finding_id, f"{finding_id}#c", target_key, panel_id, opinion_id, project_id, owner_sub,
         cluster_key, cluster_key, status, status_source))


def _registry(store, cluster_key=CK_A, *, target_key=TARGET, owner_sub=OWNER, status="open"):
    store.execute(
        "INSERT INTO rr_registry(target_key, cluster_key, owner_sub, merged_json, support, contested, "
        "subject_key, mechanism, mechanism_detail, weak_subject, status, status_source, updated_at) "
        "VALUES (?, ?, ?, '{}', 1, 0, ?, 'thermal', 'cte_mismatch', 0, ?, 'code', 1)",
        (target_key, cluster_key, owner_sub, cluster_key, status))


def _base(store):
    _project(store)
    _target(store)
    _panel(store)
    _opinion(store, "O1", "mech.stress")
    _finding(store, "F1", opinion_id="O1")
    _registry(store)


# ================================================================ POST /findings/{id}/labels
def test_label_route_applies_the_human_label_and_flips_status(store, clock):
    _base(store)

    out = routes.post_finding_label(
        "F1", routes.LabelBody(outcome="confirmed", evidence_ref="inc:2026-0007"), ident=_ident())

    assert (out["applied"], out["status"], out["counted"]) == (True, "verified", True)
    assert out["matched_by"] == "manual"
    row = store.query_one("SELECT source, outcome, labeled_by FROM rr_labels WHERE finding_id = 'F1'")
    assert (row["source"], row["outcome"], row["labeled_by"]) == ("expert_review", "confirmed", OWNER)
    assert store.query_one("SELECT status, status_source FROM rr_findings WHERE finding_id = 'F1'")[
        "status_source"] == "label_manual"
    assert store.query_one(
        "SELECT status FROM rr_registry WHERE cluster_key = ?", (CK_A,))["status"] == "verified"


def test_label_route_refuses_anonymous_auto_source_and_unknown_vocabulary(store, clock):
    _base(store)
    body = routes.LabelBody(outcome="confirmed", evidence_ref="inc:1")

    with pytest.raises(AppError) as anon:
        routes.post_finding_label("F1", body, ident=_ident(None))
    assert anon.value.http_status == 401

    # 자동 4경로는 야간 잡의 입구다 — REST 로 3항 매칭 없는 auto 라벨을 세우지 못한다.
    with pytest.raises(AppError) as forged:
        routes.post_finding_label(
            "F1", routes.LabelBody(outcome="confirmed", evidence_ref="inc:1", source="incident"),
            ident=_ident())
    assert forged.value.http_status == 422

    # 어휘 422·소유권 404 는 metrics.record_label 이 낸다.
    with pytest.raises(AppError) as vocab:
        routes.post_finding_label(
            "F1", routes.LabelBody(outcome="maybe", evidence_ref="inc:1"), ident=_ident())
    assert vocab.value.http_status == 422
    with pytest.raises(AppError) as other:
        routes.post_finding_label("F1", body, ident=_ident(OTHER))
    assert other.value.http_status == 404
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_labels")["n"] == 0


# ================================================================ /meta/metrics · /meta/metrics/recompute
def test_recompute_rows_are_actually_visible_on_get(store, clock):
    """옛 필터(`key = <owner_sub>`)는 rr_metrics 의 어떤 key 와도 맞지 않아 private 행을 전부 가렸다."""
    _base(store)
    routes.post_finding_label(
        "F1", routes.LabelBody(outcome="confirmed", evidence_ref="inc:1"), ident=_ident())

    computed = routes.post_metrics_recompute(ident=_ident())
    assert computed["rows"] > 0 and computed["labels"] == 1

    rows = routes.get_metrics(ident=_ident())["metrics"]
    assert len(rows) == computed["rows"]
    assert {r["visibility"] for r in rows} == {"private"}
    assert any(r["dimension"] == "global" and r["metric"] == "precision" for r in rows)
    assert routes.get_metrics(limit=1, ident=_ident())["metrics"].__len__() == 1


def test_metrics_routes_require_a_signed_in_caller(store):
    for call in (lambda: routes.get_metrics(ident=_ident(None)),
                 lambda: routes.post_metrics_recompute(ident=_ident(None))):
        with pytest.raises(AppError) as err:
            call()
        assert err.value.http_status == 401


# ================================================================ PUT /registry/{cluster}/status → 라벨
def test_registry_status_chains_an_expert_review_label(store, clock):
    _base(store)
    _finding(store, "F2", opinion_id="O1")

    out = routes.put_registry_status(
        CK_A, routes.RegistryStatusBody(status="verified", evidence_ref="rpt:R-9"), ident=_ident())

    assert out["label_needed"] is True and len(out["labels"]) == 2
    assert {lab["source"] for lab in out["labels"]} == {"expert_review"}
    assert {lab["outcome"] for lab in out["labels"]} == {"confirmed"}
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_labels")["n"] == 2
    # 사람 전이가 먼저 status 5열을 잡았으므로 적용된 로그는 그 1행이고(§4.7.1),
    # 뒤이은 라벨 훅은 사람 판정을 덮지 못해 applied=0 시도로만 남는다(§7.6 conflict_with_human).
    assert store.query_one(
        "SELECT COUNT(*) AS n FROM rr_registry_status_log WHERE applied = 1")["n"] == 1
    assert store.query_one(
        "SELECT COUNT(*) AS n FROM rr_registry_status_log WHERE applied = 0")["n"] == 2
    row = store.query_one("SELECT status, status_source FROM rr_registry WHERE cluster_key = ?", (CK_A,))
    assert (row["status"], row["status_source"]) == ("verified", "human")


def test_registry_dismissed_labels_are_refuted_and_mitigated_makes_none(store, clock):
    _base(store)
    routes.put_registry_status(
        CK_A, routes.RegistryStatusBody(status="dismissed", evidence_ref="rpt:R-1"), ident=_ident())
    assert store.query_one("SELECT outcome FROM rr_labels WHERE finding_id = 'F1'")["outcome"] == "refuted"

    _registry(store, "ck:bbbbbbbbbbbb")
    _finding(store, "F3", cluster_key="ck:bbbbbbbbbbbb", opinion_id="O1")
    out = routes.put_registry_status(
        "ck:bbbbbbbbbbbb", routes.RegistryStatusBody(status="mitigated", note="완화 조치"), ident=_ident())
    assert out["label_needed"] is False and "labels" not in out
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_labels")["n"] == 1


def test_registry_status_without_evidence_rolls_the_whole_transaction_back(store, clock):
    _base(store)

    with pytest.raises(AppError) as err:
        routes.put_registry_status(CK_A, routes.RegistryStatusBody(status="verified"), ident=_ident())
    assert err.value.http_status == 422

    # 근거 없는 확정만 남고 라벨이 없는 상태를 만들지 않는다 — 등록부도 그대로다.
    assert store.query_one("SELECT status FROM rr_registry WHERE cluster_key = ?", (CK_A,))["status"] == "open"
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_labels")["n"] == 0


# ================================================================ GET /curation · PUT /curation/{id}
def _queue_row(store, kind, payload, *, owner_sub=OWNER, queue_id="Q1"):
    store.execute(
        "INSERT INTO rr_curation_queue(id, owner_sub, kind, payload_json, status, created_at) "
        "VALUES (?, ?, ?, ?, 'open', 1)", (queue_id, owner_sub, kind, json.dumps(payload)))
    return queue_id


def test_curation_list_is_scoped_to_the_caller_and_filters_by_kind(store, clock):
    _queue_row(store, "label_match", {"finding_id": "F1"}, queue_id="Q1")
    _queue_row(store, "pattern_candidate", {"pattern_id": "P-001"}, queue_id="Q2")
    _queue_row(store, "label_match", {"finding_id": "F9"}, owner_sub=OTHER, queue_id="Q3")

    rows = routes.get_curation(ident=_ident())["rows"]
    assert [r["id"] for r in rows] == ["Q1", "Q2"]
    assert rows[0]["payload"] == {"finding_id": "F1"}
    assert [r["id"] for r in routes.get_curation(kind="label_match", ident=_ident())["rows"]] == ["Q1"]
    assert routes.get_curation(status="done", ident=_ident())["rows"] == []


def test_label_match_decision_opens_the_label_for_counting(store, clock):
    """큐가 열려 있는 동안 sim 라벨은 통계 밖이고, `done` 결정이 그 계수를 연다(metrics.is_counted_label)."""
    _base(store)
    label = metrics.record_label(store, finding_id="F1", source="sim", outcome="confirmed",
                                 evidence_ref="rpt:후속")
    queue_id = label["queue_id"]
    assert queue_id and metrics.is_counted_label({"id": label["label_id"], "source": "sim"},
                                                 metrics.label_queue_status(store)) is False

    out = routes.put_curation(queue_id, routes.CurationDecisionBody(decision="confirmed", reason="시험 확인"),
                              ident=_ident())

    assert (out["status"], out["applied"]) == ("done", {})
    assert metrics.is_counted_label({"id": label["label_id"], "source": "sim"},
                                    metrics.label_queue_status(store)) is True
    assert store.query_one(
        "SELECT COUNT(*) AS n FROM rr_audit WHERE action = 'curation.decide'")["n"] == 1


def test_curation_refuses_foreign_rows_wrong_vocabulary_unwired_kinds_and_replays(store, clock):
    _queue_row(store, "label_match", {"finding_id": "F1"}, queue_id="Q1")
    _queue_row(store, "cluster_merge", {"a": "ck:1", "b": "ck:2"}, queue_id="Q2")
    _queue_row(store, "label_match", {"finding_id": "F9"}, owner_sub=OTHER, queue_id="Q3")

    with pytest.raises(AppError) as foreign:
        routes.put_curation("Q3", routes.CurationDecisionBody(decision="reject"), ident=_ident())
    assert foreign.value.http_status == 404

    with pytest.raises(AppError) as vocab:
        routes.put_curation("Q1", routes.CurationDecisionBody(decision="known"), ident=_ident())
    assert (vocab.value.code, vocab.value.http_status) == ("decision_not_allowed_for_kind", 422)

    # 승격은 어느 축으로 올릴지를 코드가 고를 수 없다 — payload.axis 없이는 422 고 큐는 열린 채다.
    _queue_row(store, "x_tag_promote", {"tag": "x:stack_budget"}, queue_id="Q4")
    with pytest.raises(AppError) as no_axis:
        routes.put_curation("Q4", routes.CurationDecisionBody(decision="promote"), ident=_ident())
    assert no_axis.value.http_status == 422
    assert store.query_one("SELECT status FROM rr_curation_queue WHERE id = 'Q4'")["status"] == "open"

    # cluster_merge 는 P5 에서 적용 함수가 붙었다 — reject 는 두 행을 그대로 둔다.
    routes.put_curation("Q2", routes.CurationDecisionBody(decision="reject"), ident=_ident())
    assert store.query_one("SELECT status FROM rr_curation_queue WHERE id = 'Q2'")["status"] == "rejected"
    assert store.query("SELECT old_cluster_key FROM rr_cluster_alias") == []

    routes.put_curation("Q1", routes.CurationDecisionBody(decision="reject"), ident=_ident())
    assert store.query_one("SELECT status FROM rr_curation_queue WHERE id = 'Q1'")["status"] == "rejected"
    with pytest.raises(AppError) as replay:
        routes.put_curation("Q1", routes.CurationDecisionBody(decision="confirmed"), ident=_ident())
    assert replay.value.http_status == 409


# ================================================================ 화면이 부르던 죽은 경로 2종(§8.2.4)
def _opinion_with_turns(store, opinion_id, agent_key, domain, turns, *, panel_id=PANEL):
    store.execute(
        "INSERT INTO rr_seat_opinions(opinion_id, target_key, panel_id, owner_sub, agent_key, domain,"
        " origin, cycle, opinion_json, final_stance, created_at) VALUES (?,?,?,?,?,?,'primary',1,?,?,1)",
        (opinion_id, TARGET, panel_id, OWNER, agent_key, domain,
         json.dumps({"turns": turns}, ensure_ascii=False), turns[-1]["stance"]))


def test_panel_transcript_flattens_seat_turns_by_round(store, clock):
    """`PanelTranscript` '발언' 탭 — 좌석 발언을 라운드로 묶고 결정문·risk_spec 은 원문 그대로다."""
    _project(store)
    _target(store)
    _panel(store)
    store.execute("UPDATE rr_panels SET decision_text = ?, risk_spec_json = ? WHERE id = ?",
                  ("[판정] 조건부.", json.dumps({"verdict": "conditional"}), PANEL))
    _opinion_with_turns(store, "OP-a", "mech-a", "mech",
                        [{"round": 1, "say_excerpt": "얇다.", "position": "risk", "stance": "oppose"},
                         {"round": 2, "say_excerpt": "수용.", "position": "risk", "stance": "conditional"}])
    _opinion_with_turns(store, "OP-b", "thermal-b", "thermal",
                        [{"round": 1, "say_excerpt": "무난.", "position": "ok", "stance": "agree"}])

    out = routes.get_panel_transcript(PANEL, ident=_ident())

    assert out["decision_text"] == "[판정] 조건부."
    assert out["risk_spec"] == {"verdict": "conditional"}
    # 좌석을 섞지 않고 라운드로 묶는다 — 같은 라운드 안에서는 좌석 키 순이다(결정론).
    assert [(t["round"], t["seat"], t["stance"]) for t in out["turns"]] == [
        (1, "mech-a", "oppose"), (1, "thermal-b", "agree"), (2, "mech-a", "conditional")]


def test_panel_transcript_without_a_spec_returns_null_not_an_empty_object(store, clock):
    _project(store)
    _target(store)
    _panel(store)

    out = routes.get_panel_transcript(PANEL, ident=_ident())

    assert (out["decision_text"], out["turns"], out["risk_spec"]) == ("", [], None)


def test_panel_transcript_hides_other_owners_panels(store, clock):
    _project(store, owner_sub=OTHER)
    _target(store, owner_sub=OTHER)
    _panel(store, owner_sub=OTHER)

    with pytest.raises(AppError) as err:
        routes.get_panel_transcript(PANEL, ident=_ident())
    assert err.value.http_status == 404


def _coverage(store, agent_key, domain, status, **extra):
    cols = {"target_key": TARGET, "agent_key": agent_key, "owner_sub": OWNER, "domain": domain,
            "status": status, "updated_at": 1, **extra}
    store.execute(f"INSERT INTO rr_coverage({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                  tuple(cols.values()))


def test_seats_drill_down_filters_by_domain(store, clock):
    """`CoverageHeatmap` 셀 클릭의 드릴다운 — coverage 는 카운트만 주고 행은 여기서만 편다(§8.2.4)."""
    _project(store)
    _target(store)
    _coverage(store, "mech-a", "mech", "done", panel_id=PANEL, opinion_id="OP-a")
    _coverage(store, "ecad-c", "ecad", "skipped", reason="ECAD 소스 없음",
              status_source="human", decided_by=OWNER)

    one = routes.get_seats(TARGET, domain="mech", ident=_ident())
    every = routes.get_seats(TARGET, ident=_ident())

    assert [s["agent_key"] for s in one["seats"]] == ["mech-a"]
    assert one["seats"][0]["opinion_id"] == "OP-a"
    # 사람이 옮긴 상태는 주체가 남는다 — 셀 툴팁의 decided_by 가 이 값이다(§6.8.2).
    skipped = next(s for s in every["seats"] if s["agent_key"] == "ecad-c")
    assert (skipped["status_source"], skipped["decided_by"], skipped["reason"]) == (
        "human", OWNER, "ECAD 소스 없음")
    assert [s["agent_key"] for s in every["seats"]] == ["ecad-c", "mech-a"]


def test_registry_payload_carries_the_final_verdict(store, clock):
    """헤더의 verdict_final 과 등록부 카드가 같은 응답을 쓴다(§8.2.4) — 후보는 코드, 확정은 사람이다."""
    _project(store)
    _target(store)
    store.execute("UPDATE rr_targets SET verdict_final = 'conditional' WHERE target_key = ?", (TARGET,))

    out = routes.get_registry(TARGET, ident=_ident())

    assert out["verdict_final"] == "conditional"
    assert "verdict_candidate" in out and out["target_key"] == TARGET


# ================================================================ 자유 태그 승격(plan §7.7 x_tag_promote)
def test_every_queue_kind_the_ddl_allows_has_a_decision_vocabulary():
    """DDL 이 쌓게 허용한 kind 는 전부 결정할 수 있어야 한다 — 어휘가 없으면 그 큐가 501 로 막힌다."""
    import re

    from app import risk_store as risk_store_module

    ddl = pathlib.Path(risk_store_module.__file__).read_text(encoding="utf-8")
    body = re.search(r"rr_curation_queue.*?kind TEXT NOT NULL CHECK\(kind IN \(([^)]*)\)", ddl, re.S).group(1)
    kinds = {k.strip().strip("'") for k in body.split(",")}

    assert kinds == set(routes.CURATION_DECISIONS)
    assert kinds == set(routes.CURATION_AUDIT_SCOPE)


def test_curation_screen_uses_the_same_decision_vocabulary_as_the_server():
    """화면의 결정 어휘는 서버 CURATION_DECISIONS 와 같은 집합이어야 한다 — 어휘가 두 곳에 적히면 한쪽만 늙는다."""
    page = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "pages"
            / "CurationQueuePage.tsx")
    if not page.exists():
        pytest.skip("프런트엔드 화면이 없다")
    text = page.read_text(encoding="utf-8")

    import re

    blocks = re.findall(r'kind:\s*"(\w+)".*?decisions:\s*\[(.*?)\]', text, re.S)
    screen = {kind: tuple(re.findall(r'value:\s*"([\w]+)"', body)) for kind, body in blocks}

    assert screen.keys() == routes.CURATION_DECISIONS.keys()
    for kind, values in screen.items():
        assert set(values) == set(routes.CURATION_DECISIONS[kind]), kind


def _character(store, sid, *, tags, lead=None, facet="unknown", target_key=None, project_id=PROJECT):
    store.execute(
        "INSERT INTO rr_character(id, project_id, owner_sub, facet, tag, tags_json, statement, polarity,"
        " by_json, support_panels, support_targets, recall_eligible, needs_review, status,"
        " first_target_key, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,'문장','observation','[]',2,3,1,0,'panel',?,1,1)",
        (sid, project_id, OWNER, facet, lead, json.dumps(tags, ensure_ascii=False), target_key))


def test_x_tag_promotion_rewrites_statements_and_records_the_vocabulary_bump(store, clock):
    """승격은 진술을 통제 태그로 옮기고, 어휘 승급 값은 결정 기록에만 남긴다(자산 파일은 앱이 안 고친다)."""
    _project(store)
    _target(store)
    _character(store, "PN1#C1", tags=["x:stack_budget"], target_key=TARGET)
    _character(store, "PN1#C2", tags=["char:structure:thin_stack", "x:stack_budget"],
               lead="char:structure:thin_stack", facet="intent", target_key=TARGET)
    _character(store, "PN1#C3", tags=["x:stack_budget_v2"])      # 부분 문자열로 걸려서는 안 되는 이웃
    queue_id = _queue_row(store, "x_tag_promote", {"tag": "x:stack_budget"}, queue_id="QX")

    out = routes.put_curation(
        queue_id, routes.CurationDecisionBody(decision="promote", reason="XD 리더 승인",
                                              payload={"axis": "char:constraint"}), ident=_ident())

    applied = out["applied"]
    assert out["status"] == "done"
    assert (applied["new_tag"], applied["statements"]) == ("char:constraint:stack_budget", 2)
    assert (applied["vocab_version_before"], applied["vocab_version_after"]) == ("vocab-1.0", "vocab-1.1")
    assert applied["already_in_vocab"] is False

    rows = {r["id"]: r for r in store.query("SELECT id, facet, tag, tags_json FROM rr_character")}
    # 대표 태그가 없던 행은 승격 태그가 대표가 되고 그 축의 facet 을 따른다.
    assert (rows["PN1#C1"]["tag"], rows["PN1#C1"]["facet"]) == ("char:constraint:stack_budget", "constraint")
    # 이미 대표가 있던 행은 대표·facet 이 그대로다 — 승격은 어휘를 넓히는 일이지 재분류가 아니다.
    assert (rows["PN1#C2"]["tag"], rows["PN1#C2"]["facet"]) == ("char:structure:thin_stack", "intent")
    assert json.loads(rows["PN1#C2"]["tags_json"]) == ["char:structure:thin_stack",
                                                       "char:constraint:stack_budget"]
    assert json.loads(rows["PN1#C3"]["tags_json"]) == ["x:stack_budget_v2"]

    # 승격 전에는 RA 에 잇지 않던 태그다(§5.4 ⑦) — 이제 design_trait·exhibits op 가 올라간다.
    sync = json.loads(store.query_one(
        "SELECT external_sync_json AS j FROM rr_targets WHERE target_key = ?", (TARGET,))["j"])
    pending = sync["ra"]["pending_ops"]
    # design_trait 객체는 태그마다 하나로 접히고(queue_sync_ops 가 같은 op 를 합친다), exhibits 는 진술마다 하나다.
    assert [op["op"] for op in pending] == ["merge_object", "link", "link"]
    assert {op["reason"] for op in pending} == {"x_tag_promote"}
    assert pending[0]["props"] == {"status": "vocab"}
    assert [op["evidence_note"] for op in pending[1:]] == ["narr:PN1#C1", "narr:PN1#C2"]

    audit = store.query_one("SELECT scope, subject_id FROM rr_audit WHERE action = 'curation.decide'")
    assert (audit["scope"], audit["subject_id"]) == ("project", "x:stack_budget")


def test_x_tag_rejection_leaves_the_statements_alone(store, clock):
    _project(store)
    _character(store, "PN1#C1", tags=["x:stack_budget"])
    queue_id = _queue_row(store, "x_tag_promote", {"tag": "x:stack_budget"}, queue_id="QX")

    out = routes.put_curation(queue_id, routes.CurationDecisionBody(decision="reject", reason="너무 좁다"),
                              ident=_ident())

    assert (out["status"], out["applied"]) == ("rejected", {})
    assert json.loads(store.query_one(
        "SELECT tags_json AS t FROM rr_character WHERE id = 'PN1#C1'")["t"]) == ["x:stack_budget"]


# ================================================================ 승격 결정 · GET /patterns
def _candidate_pattern(store, pattern_id="P-001"):
    store.execute(
        "INSERT INTO rr_patterns(id, owner_sub, visibility, cluster_key_norm, mechanism, mechanism_detail, "
        "change_kind, subject_class, status, n_findings, n_targets, n_projects, n_experts, n_confirmed, "
        "n_refuted, created_at, updated_at) VALUES (?, ?, 'private', ?, 'thermal', 'cte_mismatch', "
        "'dimension', 'ck', 'candidate', 1, 1, 1, 1, 0, 0, 1, 1)", (pattern_id, OWNER, CK_A))
    return _queue_row(store, "pattern_candidate", {"pattern_id": pattern_id, "cluster_key_norm": CK_A,
                                                   "proposal": "known"})


def test_pattern_candidate_gate_failure_leaves_the_queue_open(store, clock):
    _base(store)
    queue_id = _candidate_pattern(store)

    with pytest.raises(AppError) as gate:
        routes.put_curation(queue_id, routes.CurationDecisionBody(decision="known"), ident=_ident())
    assert gate.value.http_status == 422                # confirmed 0 · finding 1 — known_gate 미충족

    row = store.query_one("SELECT status, decided_by FROM rr_curation_queue WHERE id = ?", (queue_id,))
    assert (row["status"], row["decided_by"]) == ("open", None)
    assert store.query_one("SELECT status FROM rr_patterns WHERE id = 'P-001'")["status"] == "candidate"


def test_pattern_candidate_known_promotes_and_shows_up_on_patterns(store, clock):
    _base(store)
    queue_id = _candidate_pattern(store)
    metrics.record_label(store, finding_id="F1", source="expert_review", outcome="confirmed",
                         evidence_ref="inc:2026-0007")

    out = routes.put_curation(queue_id, routes.CurationDecisionBody(decision="known", reason="큐레이터 승인"),
                              ident=_ident())

    assert out["status"] == "done" and out["applied"]["to_status"] == "known"
    assert out["applied"]["pattern"]["curated_by"] == OWNER
    assert store.query_one("SELECT status FROM rr_curation_queue WHERE id = ?", (queue_id,))["status"] == "done"

    listed = routes.get_patterns(ident=_ident())
    assert [(p["id"], p["status"]) for p in listed["patterns"]] == [("P-001", "known")]
    assert listed["rules"] == []                        # known 은 아직 규칙이 아니다(§7.5 3행)
    assert routes.get_patterns(status="candidate", ident=_ident())["patterns"] == []


def test_patterns_route_hides_other_owners_private_rows(store, clock):
    _candidate_pattern(store)
    store.execute(
        "INSERT INTO rr_patterns(id, owner_sub, visibility, cluster_key_norm, status, created_at, updated_at) "
        "VALUES ('P-002', ?, 'private', 'ck:cccccccccccc', 'known', 1, 1)", (OTHER,))
    store.execute(
        "INSERT INTO rr_patterns(id, owner_sub, visibility, cluster_key_norm, status, created_at, updated_at) "
        "VALUES ('P-003', ?, 'org', 'ck:dddddddddddd', 'known', 1, 1)", (OTHER,))

    ids = [p["id"] for p in routes.get_patterns(ident=_ident())["patterns"]]
    assert ids == ["P-001", "P-003"]
    with pytest.raises(AppError) as anon:
        routes.get_patterns(ident=_ident(None))
    assert anon.value.http_status == 401


def test_promotable_vocabulary_matches_the_learning_state_machine():
    """큐 결정 어휘는 승격 상태기계의 목적지 + reject 다 — 두 곳이 갈리면 UI 가 막힌 전이를 제안한다."""
    assert set(routes.CURATION_DECISIONS["pattern_candidate"]) == set(learning.PROMOTABLE) | {"reject"}


# ================================================================ 근접 중복 클러스터 수동 병합(plan §0.9 P5-13)
def _dup_queue(store, key_a: str, key_b: str, family: str = "fam1") -> str:
    queue_id = "q-dup-1"
    store.execute(
        "INSERT INTO rr_curation_queue(id, owner_sub, kind, payload_json, status, created_at)"
        " VALUES (?,?, 'cluster_merge', ?, 'open', 1)",
        (queue_id, OWNER, json.dumps({"a": key_a, "b": key_b, "family_key": family,
                                      "subject_a": "sk:a", "subject_b": "sk:b", "score": 0.93})))
    return queue_id


def _registry_pair(store, key_a: str, key_b: str, *, family_a="fam1", family_b="fam1") -> None:
    for key, family in ((key_a, family_a), (key_b, family_b)):
        store.execute(
            "INSERT INTO rr_registry(target_key, cluster_key, owner_sub, visibility, merged_json, support,"
            " contested, rejected, human_n, family_key, direction, mechanism, mechanism_detail, change_kind,"
            " subject_key, severity, sev3, judgement, status, status_source, updated_at)"
            " VALUES (?,?,?, 'private', '{}', 1, 0, 0, 0, ?, 'risk', 'thermal', 'cte_mismatch',"
            " 'dimension', 'sk:a', '중대', 2, 'WARNING', 'open', 'code', 1)",
            (TARGET, key, OWNER, family))


def test_cluster_merge_decision_writes_an_alias_and_remerges(store, clock):
    _base(store)
    key_a, key_b = "ck:dup000000001", "ck:dup000000002"
    _registry_pair(store, key_a, key_b)
    queue_id = _dup_queue(store, key_a, key_b)

    out = routes.put_curation(queue_id, routes.CurationDecisionBody(decision="merge", reason="같은 계면"),
                              ident=_ident())
    assert out["status"] == "done"
    assert out["applied"]["alias"]["new_cluster_key"] == key_b
    alias = store.query_one(
        "SELECT new_cluster_key, reason, revoked_at FROM rr_cluster_alias WHERE old_cluster_key = ?", (key_a,))
    assert (alias["new_cluster_key"], alias["reason"], alias["revoked_at"]) == (key_b, "cluster_merge", None)
    assert store.query_one(
        "SELECT COUNT(*) AS n FROM rr_audit WHERE action = 'curation.decide'")["n"] == 1
    # 별칭이 서면 재병합이 대표 키 하나로 접는다.
    from app import registry as registry_module
    assert registry_module.resolve_cluster_key(store, key_a) == key_b


def test_cluster_merge_rejects_a_family_mismatch(store, clock):
    _base(store)
    key_a, key_b = "ck:dup000000003", "ck:dup000000004"
    _registry_pair(store, key_a, key_b, family_b="fam2")
    queue_id = _dup_queue(store, key_a, key_b)
    with pytest.raises(AppError) as exc:
        routes.put_curation(queue_id, routes.CurationDecisionBody(decision="merge"), ident=_ident())
    assert (exc.value.code, exc.value.http_status) == ("family_key_differs", 422)
    assert store.query("SELECT old_cluster_key FROM rr_cluster_alias") == []
    assert store.query_one(
        "SELECT status FROM rr_curation_queue WHERE id = ?", (queue_id,))["status"] == "open"


# ================================================================ 미분류 코드 재매핑(plan §7.7 · §0.9 P6-6·P6-9)
def test_unclassified_code_decision_remaps_through_an_alias(store, clock):
    """map 결정은 별칭만 더한다 — finding 의 cluster_key 는 바이트 불변이고 옛 인용이 이어진다."""
    from app import learning

    _base(store)
    _finding(store, "F9")
    store.execute("UPDATE rr_findings SET mechanism_detail = 'unclassified' WHERE finding_id = 'F9'")
    before = store.query_one("SELECT cluster_key FROM rr_findings WHERE finding_id = 'F9'")["cluster_key"]
    queue_id = _queue_row(store, "unclassified_code", {"finding_id": "F9", "mechanism_free": "열팽창"},
                          queue_id="Q-UC")

    with pytest.raises(AppError) as no_detail:
        routes.put_curation(queue_id, routes.CurationDecisionBody(decision="map"), ident=_ident())
    assert no_detail.value.http_status == 422

    out = routes.put_curation(
        queue_id, routes.CurationDecisionBody(decision="map", payload={"mechanism_detail": "cte_mismatch"}),
        ident=_ident())
    assert out["status"] == "done"
    assert out["applied"]["aliases_written"] == 1
    assert out["applied"]["taxonomy_version_after"] != out["applied"]["taxonomy_version_before"]
    after = store.query_one("SELECT cluster_key FROM rr_findings WHERE finding_id = 'F9'")["cluster_key"]
    assert after == before                                    # 저장된 키는 바이트 불변이다
    assert learning.resolve_cluster_key(store, before) != before   # 별칭으로 새 키에 이어진다
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_cluster_alias")["n"] == 1


def test_remap_is_dry_run_by_default_and_idempotent(store, clock):
    """dry-run 은 별칭 행을 만들지 않고, apply 2회째는 새 행 0 이다(plan §0.9 P6-9)."""
    from app import learning

    _base(store)
    _finding(store, "F8")
    store.execute("UPDATE rr_findings SET mechanism_detail = 'unclassified' WHERE finding_id = 'F8'")
    plan = learning.plan_remap(store, mechanism="thermal", from_detail="unclassified",
                               to_detail="cte_mismatch")
    assert len(plan) == 1
    assert store.query("SELECT old_cluster_key FROM rr_cluster_alias") == []      # 계획만으로는 쓰지 않는다

    first = learning.apply_remap(store, plan, owner_sub=OWNER)
    assert first["aliases_written"] == 1
    second = learning.apply_remap(store, plan, owner_sub=OWNER)
    assert second["aliases_written"] == 0
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_cluster_alias")["n"] == 1
