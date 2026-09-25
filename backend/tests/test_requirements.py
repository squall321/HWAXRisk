# 요구 규격 모듈 테스트 — UPSERT·결정·승계 4행의 동작 함수와 sig:req.* · finding requirement_ref 보정(plan §2.8b)
from __future__ import annotations

import pytest

from app import requirements as req
from app.common import now_epoch
from app.errors import AppError

# plan §5.2.2 A 의 rr_requirements DDL. v1 전문 교체가 아직 안 들어온 저장소에서도 이 테스트가 서게 하는 안전판이고,
# 교체가 들어오면 IF NOT EXISTS 라 아무 일도 하지 않는다.
_DDL = """
CREATE TABLE IF NOT EXISTS rr_requirements (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_sub TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('dim_limit','scenario','standard')),
  name TEXT NOT NULL,
  op TEXT CHECK(op IN ('lte','gte','between')),
  value_json TEXT,
  unit TEXT,
  source_ref TEXT,
  status TEXT NOT NULL CHECK(status IN ('candidate','confirmed','waived')) DEFAULT 'candidate',
  waive_reason TEXT,
  inherited_from TEXT,
  decided_by TEXT, decided_at INTEGER, created_at INTEGER, updated_at INTEGER,
  UNIQUE(project_id, kind, name));
CREATE INDEX IF NOT EXISTS ix_rr_req_project ON rr_requirements(project_id, kind, status);
"""

OWNER = "owner@example.com"


@pytest.fixture
def store(risk_store):
    """요구 표와 치수 어휘·과제 2건이 있는 빈 DB."""
    with risk_store.tx() as conn:
        conn.executescript(_DDL)
    now = now_epoch()
    for name, unit in (("gap_main", "mm"), ("wall_t", "mm"), ("stack_h", "mm")):
        risk_store.execute(
            "INSERT INTO rr_dim_vocab(name, kind, unit, description, synonyms_json, stop_tokens_json,"
            " tol_abs, tol_rel, vocab_version, created_by, created_at)"
            " VALUES (?,?,?,NULL,NULL,NULL,NULL,NULL,'candidate',?,?)", (name, "gap", unit, OWNER, now))
    for pid, code in (("P1", "proj-1"), ("P0", "proj-0")):
        risk_store.execute(
            "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (pid, OWNER, code, code, now, now))
    return risk_store


def _post(store, items, project_id="P1"):
    return req.upsert_requirements(store, project_id, OWNER, items)


DIM = {"kind": "dim_limit", "name": "gap_main", "op": "lte", "value_json": 0.2, "unit": "mm"}


# ---------------------------------------------------------------- POST(배열 UPSERT)
def test_upsert_inserts_and_lists(store):
    out = _post(store, [DIM, {"kind": "scenario", "name": "drop_1_2m_corner",
                              "value_json": {"taxonomy_key": "deep", "required": True}}])
    assert out["upserted"] == 2
    assert [r["name"] for r in out["rows"]] == ["gap_main", "drop_1_2m_corner"]
    listed = req.list_requirements(store, "P1")["requirements"]
    assert [r["kind"] for r in listed] == ["dim_limit", "scenario"]
    assert listed[0]["value"] == 0.2 and listed[0]["status"] == "candidate"
    assert set(listed[0]) == set(req._PUBLIC_KEYS)
    assert req.list_requirements(store, "P1", kind="scenario")["requirements"][0]["value"]["taxonomy_key"] == "deep"


def test_upsert_is_idempotent_and_keeps_human_status(store):
    _post(store, [DIM])
    rid = req.list_requirements(store, "P1")["requirements"][0]["id"]
    req.decide_requirement(store, rid, status="confirmed", actor_sub=OWNER)
    out = _post(store, [{**DIM, "value_json": 0.15}])
    assert out["upserted"] == 1
    rows = req.list_requirements(store, "P1")["requirements"]
    assert len(rows) == 1 and rows[0]["id"] == rid          # UNIQUE(project_id, kind, name) 기준 UPSERT
    assert rows[0]["value"] == 0.15                          # 값은 갱신되고
    assert rows[0]["status"] == "confirmed"                  # 사람 결정은 살아남는다


def test_upsert_rejects_bad_dim_limit(store):
    with pytest.raises(AppError) as e1:
        _post(store, [{"kind": "dim_limit", "name": "gap_main", "op": "lte", "unit": "mm"}])
    assert (e1.value.code, e1.value.http_status) == ("dim_limit_incomplete", 422)

    with pytest.raises(AppError) as e2:
        _post(store, [{**DIM, "unit": "m"}])
    assert (e2.value.code, e2.value.http_status) == ("unit_mismatch", 400)

    with pytest.raises(AppError) as e3:
        _post(store, [{**DIM, "name": "없는치수"}])
    assert (e3.value.code, e3.value.http_status) == ("unknown_dim_name", 422)

    with pytest.raises(AppError) as e4:
        _post(store, [{**DIM, "op": "between", "value_json": [0.5, 0.1]}])
    assert e4.value.code == "value_invalid"

    with pytest.raises(AppError) as e5:
        _post(store, [{"kind": "standard", "name": "IEC 62368-1 §5.4",
                       "value_json": {"clause": "5.4", "title": "전기 안전"}}])
    assert e5.value.code == "source_ref_required"
    assert req.list_requirements(store, "P1")["requirements"] == []   # 실패한 배열은 한 행도 남기지 않는다


def test_upsert_reports_snapshots_to_recompute(store):
    store.execute(
        "INSERT INTO rr_snapshots(id, project_id, owner_sub, ir_version, ir_hash, ir_json, source_ids_json,"
        " kinds_json, created_at) VALUES ('S1','P1',?, '1.0','h','{}','[]','[]',1)", (OWNER,))
    assert _post(store, [DIM])["recompute"] == ["S1"]


# ---------------------------------------------------------------- PUT /requirements/{id}
def test_decide_waive_requires_reason(store):
    _post(store, [DIM])
    rid = req.list_requirements(store, "P1")["requirements"][0]["id"]
    with pytest.raises(AppError) as exc:
        req.decide_requirement(store, rid, status="waived", waive_reason="  ", actor_sub=OWNER)
    assert (exc.value.code, exc.value.http_status) == ("reason_required", 422)

    row = req.decide_requirement(store, rid, status="waived", waive_reason="양산 치구로 대체", actor_sub=OWNER)
    assert row["status"] == "waived" and row["waive_reason"] == "양산 치구로 대체"
    assert row["status_source"] == "human" and row["decided_by"] == OWNER and row["decided_at"]

    back = req.decide_requirement(store, rid, status="confirmed", actor_sub=OWNER)
    assert back["waive_reason"] is None      # 면제가 풀리면 사유도 지운다

    with pytest.raises(AppError) as unknown:
        req.decide_requirement(store, rid, status="approved", actor_sub=OWNER)
    assert unknown.value.code == "status_unknown"
    with pytest.raises(AppError) as missing:
        req.decide_requirement(store, "없는id", status="confirmed", actor_sub=OWNER)
    assert missing.value.http_status == 404


# ---------------------------------------------------------------- POST …/requirements/inherit
def test_inherit_is_idempotent(store):
    _post(store, [DIM, {"kind": "standard", "name": "IEC 62368-1 §5.4", "source_ref": "card:abc",
                        "value_json": {"clause": "5.4", "title": "전기 안전"}}], project_id="P0")
    src = {r["name"]: r for r in req.list_requirements(store, "P0")["requirements"]}
    req.decide_requirement(store, src["gap_main"]["id"], status="confirmed", actor_sub=OWNER)

    first = req.inherit_requirements(store, "P1", OWNER, "P0")
    assert first == {"copied": 2, "skipped": 0}
    rows = {r["name"]: r for r in req.list_requirements(store, "P1")["requirements"]}
    assert rows["gap_main"]["status"] == "candidate"                      # 승계는 자동, 확정은 사람
    assert rows["gap_main"]["inherited_from"] == src["gap_main"]["id"]
    assert rows["gap_main"]["value"] == 0.2 and rows["gap_main"]["unit"] == "mm"

    assert req.inherit_requirements(store, "P1", OWNER, "P0") == {"copied": 0, "skipped": 2}
    assert len(req.list_requirements(store, "P1")["requirements"]) == 2

    with pytest.raises(AppError) as exc:
        req.inherit_requirements(store, "P1", OWNER, "없는과제")
    assert (exc.value.code, exc.value.http_status) == ("source_project_not_found", 404)
    with pytest.raises(AppError) as same:
        req.inherit_requirements(store, "P1", OWNER, "P1")
    assert same.value.code == "same_project"


# ---------------------------------------------------------------- sig:req.* · missing
def _ir(dims, results=None):
    return {"dims_named": dims, "results": results}


def test_req_margin_math_and_order(store):
    _post(store, [
        {"kind": "dim_limit", "name": "gap_main", "op": "lte", "value_json": 0.2, "unit": "mm"},
        {"kind": "dim_limit", "name": "wall_t", "op": "gte", "value_json": 1.0, "unit": "mm"},
        {"kind": "dim_limit", "name": "stack_h", "op": "between", "value_json": [10.0, 12.0], "unit": "mm"},
    ])
    ir = _ir([
        {"name": "gap_main", "value": 0.25, "unit": "mm"},     # lte → 0.2 - 0.25 = -0.05(위반)
        {"name": "wall_t", "value": 1.4, "unit": "mm"},        # gte → 1.4 - 1.0 = 0.4
        {"name": "stack_h", "value": None, "unit": "mm"},      # 미측정 → known=false
    ])
    out = req.compute_req_signals(store, "P1", ir)
    rows = out["signals"]["req.margin"]["value"]
    assert [r["name"] for r in rows] == ["gap_main", "wall_t", "stack_h"]   # margin 오름차순, 미측정은 뒤
    assert rows[0]["margin"] == -0.05 and rows[0]["rel"] == -0.25 and rows[0]["known"] is True
    assert rows[1]["margin"] == 0.4
    assert rows[2]["known"] is False and rows[2]["margin"] is None and rows[2]["actual"] is None
    assert out["missing"]["req_absent"] is False
    assert "req:gap_main" in out["signals"]["req.margin"]["refs"]
    assert "d:gap_main" in out["signals"]["req.margin"]["refs"]


def test_req_margin_unit_mismatch_is_unknown(store):
    _post(store, [DIM])
    out = req.compute_req_signals(store, "P1", _ir([{"name": "gap_main", "value": 0.0002, "unit": "m"}]))
    row = out["signals"]["req.margin"]["value"][0]
    assert row["known"] is False and row["margin"] is None      # 단위가 다르면 0 이 아니라 미측정이다


def test_req_absent_and_experience_basis(store):
    out = req.compute_req_signals(store, "P1", _ir([{"name": "gap_main", "value": 0.1, "unit": "mm"}]))
    assert out["missing"]["req_absent"] is True
    assert out["signals"]["req.margin"]["known"] is False
    assert out["signals"]["req.margin"]["text"] == req.EXPERIENCE_BASIS_TEXT
    basis = req.judgement_basis(store, "P1")
    assert basis == {"req_absent": True, "basis": "experience", "by_kind": {},
                     "text": "요구 미등록 — 이 판정은 내 경험 기준"}

    _post(store, [DIM])
    after = req.judgement_basis(store, "P1")
    assert after["req_absent"] is False and after["basis"] == "requirement" and "dim_limit 1" in after["text"]


def test_waived_requirement_is_not_compared(store):
    _post(store, [DIM])
    rid = req.list_requirements(store, "P1")["requirements"][0]["id"]
    req.decide_requirement(store, rid, status="waived", waive_reason="설계 변경으로 무효", actor_sub=OWNER)
    out = req.compute_req_signals(store, "P1", _ir([{"name": "gap_main", "value": 0.9, "unit": "mm"}]))
    assert out["signals"]["req.margin"]["value"] == []          # 표기만 하고 대조하지 않는다
    assert out["missing"]["req_absent"] is False                # 행은 있다


def test_scenario_coverage_and_standards(store):
    _post(store, [
        {"kind": "scenario", "name": "drop_1_2m_corner", "value_json": {"taxonomy_key": "deep", "required": True}},
        {"kind": "scenario", "name": "sphere_impact", "value_json": {"taxonomy_key": "sphere", "required": True}},
        {"kind": "scenario", "name": "옵션", "value_json": {"taxonomy_key": "impact", "required": False}},
        {"kind": "standard", "name": "IEC 62368-1 §5.4", "source_ref": "card:abc",
         "value_json": {"clause": "5.4", "title": "전기 안전"}},
    ])
    out = req.compute_req_signals(store, "P1", _ir([], results={"kind": "deep", "report_ids": ["r1"]}))
    coverage = out["signals"]["req.scenario_coverage"]["value"]
    assert coverage["required_n"] == 2 and coverage["covered_n"] == 1
    assert [u["name"] for u in coverage["uncovered"]] == ["sphere_impact"]
    assert out["missing"]["scenario_uncovered"] is True
    assert "dyna:rpt:r1" in out["signals"]["req.scenario_coverage"]["refs"]

    standards = out["signals"]["req.standards"]["value"]
    assert standards == [{"name": "IEC 62368-1 §5.4", "clause": "5.4", "title": "전기 안전",
                          "source_ref": "card:abc"}]

    none_covered = req.compute_req_signals(store, "P1", _ir([]))       # results 가 없어도 known 이다
    assert none_covered["signals"]["req.scenario_coverage"]["value"]["covered_n"] == 0
    assert none_covered["signals"]["req.scenario_coverage"]["known"] is True


# ---------------------------------------------------------------- finding 의 requirement_ref
def test_parse_requirement_ref():
    assert req.parse_requirement_ref("req:gap_main") == "gap_main"
    assert req.parse_requirement_ref("[req:gap_main]") == "gap_main"
    assert req.requirement_ref("gap_main") == "req:gap_main"
    assert req.parse_requirement_ref("d:gap_main") is None
    assert req.parse_requirement_ref("req:") is None
    assert req.parse_requirement_ref(None) is None


def test_check_finding_requirement(store):
    _post(store, [DIM])
    by_name = req.requirement_index(store, "P1")
    ir = _ir([{"name": "gap_main", "value": 0.25, "unit": "mm"}])
    margins = req.margins_by_name(req.compute_req_signals(store, "P1", ir)["signals"]["req.margin"]["value"])
    assert margins == {"gap_main": -0.05}

    # cites 에서 끌어오고, 여유가 음수인 요구를 OK 로 판정한 finding 은 undetermined 로 보정한다.
    finding = {"judgement": "OK", "cites": ["d:gap_main", "req:gap_main"], "dangling": []}
    warnings = req.check_finding_requirement(finding, by_name=by_name, margins=margins)
    assert finding["requirement_ref"] == "req:gap_main"
    assert finding["judgement"] == "undetermined" and len(warnings) == 1 and finding["dangling"] == []

    # 여유가 양수면 판정을 건드리지 않는다.
    ok = {"judgement": "OK", "requirement_ref": "req:gap_main", "dangling": []}
    assert req.check_finding_requirement(ok, by_name=by_name, margins={"gap_main": 0.05}) == []
    assert ok["judgement"] == "OK"

    # 실재하지 않는 요구 인용은 dangling 이다(등급 강등은 dangling 을 빼고 세는 기존 계산이 한다).
    ghost = {"judgement": "FAIL", "requirement_ref": "req:없는요구", "dangling": ["e:deadbeef0000"]}
    ghost_warnings = req.check_finding_requirement(ghost, by_name=by_name, margins=margins)
    assert ghost["dangling"] == ["e:deadbeef0000", "req:없는요구"] and len(ghost_warnings) == 1
    assert ghost["judgement"] == "FAIL"

    # 요구 인용이 없으면 아무것도 하지 않는다.
    plain = {"judgement": "OK", "cites": ["d:gap_main"]}
    assert req.check_finding_requirement(plain, by_name=by_name, margins=margins) == []
    assert plain["requirement_ref"] is None and plain["judgement"] == "OK"


# ---------------------------------------------------------------- REST 4행 배선(plan §8.2.3)
REST_TOKEN = "heax_pat_test_fake_requirements"
REST_USER = {"id": 11, "email": "req-owner@example.com", "display_name": "Req", "role": "member",
             "organization": "cae"}
REST_AUTH = {"Authorization": f"Bearer {REST_TOKEN}"}


@pytest.fixture
def rest(monkeypatch):
    """heax 는 REST_TOKEN 만 200. 세션 DB 에 남긴 시험 과제·요구는 뒤에서 지운다."""
    import httpx

    from app import identity
    from app.common import now_epoch as _now
    from app.risk_store import get_store

    def heax(request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") == f"Bearer {REST_TOKEN}":
            return httpx.Response(200, json=REST_USER)
        return httpx.Response(401)

    monkeypatch.setattr(identity, "_transport", httpx.MockTransport(heax))
    identity.reset_cache()
    store = get_store()
    now = _now()
    for name in ("gap_main", "wall_t"):
        store.execute(
            "INSERT OR IGNORE INTO rr_dim_vocab(name, kind, unit, description, synonyms_json, stop_tokens_json,"
            " tol_abs, tol_rel, vocab_version, created_by, created_at)"
            " VALUES (?,?,?,NULL,NULL,NULL,NULL,NULL,'candidate',?,?)", (name, "gap", "mm", REST_USER["email"], now))
    for pid, code in (("RQ1", "RQ-1"), ("RQ0", "RQ-0")):
        store.execute(
            "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (pid, REST_USER["email"], code, code, now, now))
    yield store
    store.execute("DELETE FROM rr_requirements WHERE owner_sub = ?", (REST_USER["email"],))
    store.execute("DELETE FROM rr_audit WHERE owner_sub = ?", (REST_USER["email"],))
    store.execute("DELETE FROM rr_projects WHERE owner_sub = ?", (REST_USER["email"],))
    identity.reset_cache()


def test_rest_requires_a_user(client, rest):
    assert client.get("/api/projects/RQ1/requirements").status_code == 401
    assert client.post("/api/projects/RQ1/requirements", json=[]).status_code == 401


def test_rest_upsert_list_decide_and_inherit(client, rest):
    body = [DIM, {"kind": "standard", "name": "IEC-62368", "source_ref": "사내 규격집 3판"}]
    r = client.post("/api/projects/RQ1/requirements", headers=REST_AUTH, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["upserted"] == 2

    listed = client.get("/api/projects/RQ1/requirements", headers=REST_AUTH).json()["requirements"]
    assert [row["name"] for row in listed] == ["gap_main", "IEC-62368"]
    assert client.get("/api/projects/RQ1/requirements?kind=standard",
                      headers=REST_AUTH).json()["requirements"][0]["name"] == "IEC-62368"

    rid = listed[0]["id"]
    bad = client.put(f"/api/requirements/{rid}", headers=REST_AUTH, json={"status": "waived"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "reason_required"
    ok = client.put(f"/api/requirements/{rid}", headers=REST_AUTH,
                    json={"status": "waived", "waive_reason": "시작품 한정"})
    assert ok.status_code == 200 and ok.json()["status_source"] == "human"
    assert ok.json()["decided_by"] == REST_USER["email"]
    audit = rest.query_one(
        "SELECT action, subject_id, project_id FROM rr_audit WHERE action = 'requirement.decide'")
    assert audit is not None and audit["subject_id"] == rid and audit["project_id"] == "RQ1"

    inherited = client.post("/api/projects/RQ0/requirements/inherit", headers=REST_AUTH,
                            json={"from_project_id": "RQ1"})
    assert inherited.status_code == 200 and inherited.json() == {"copied": 2, "skipped": 0}
    # 멱등 — 두 번째는 전부 건너뛴다.
    assert client.post("/api/projects/RQ0/requirements/inherit", headers=REST_AUTH,
                       json={"from_project_id": "RQ1"}).json() == {"copied": 0, "skipped": 2}
    copies = client.get("/api/projects/RQ0/requirements", headers=REST_AUTH).json()["requirements"]
    assert {row["status"] for row in copies} == {"candidate"} and all(row["inherited_from"] for row in copies)


def test_rest_error_codes_follow_the_plan(client, rest):
    unit = client.post("/api/projects/RQ1/requirements", headers=REST_AUTH,
                       json=[{**DIM, "unit": "cm"}])
    assert unit.status_code == 400 and unit.json()["error"]["code"] == "unit_mismatch"
    incomplete = client.post("/api/projects/RQ1/requirements", headers=REST_AUTH,
                             json=[{"kind": "dim_limit", "name": "gap_main"}])
    assert incomplete.status_code == 422 and incomplete.json()["error"]["code"] == "dim_limit_incomplete"
    unknown = client.post("/api/projects/RQ1/requirements", headers=REST_AUTH,
                          json=[{**DIM, "name": "없는치수"}])
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "unknown_dim_name"
    # 한 건이라도 틀리면 아무 행도 쓰이지 않는다.
    assert client.get("/api/projects/RQ1/requirements", headers=REST_AUTH).json()["requirements"] == []

    missing = client.post("/api/projects/RQ1/requirements/inherit", headers=REST_AUTH,
                          json={"from_project_id": "없는과제"})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "source_project_not_found"
    # 남의 과제는 404 로 존재를 숨긴다(조회 규약).
    assert client.get("/api/projects/없는과제/requirements", headers=REST_AUTH).status_code == 404


# ---------------------------------------------------------------- 요구 변경과 ir_hash 불변(plan §2.8b (1)·§0.9 P1-20)
def test_editing_requirements_keeps_ir_hash_and_only_moves_computed_at(store, monkeypatch):
    """요구는 스냅샷에 복사되지 않는다 — 고쳐도 ir_json·ir_hash 는 바이트 불변이고 rr_states.computed_at 만 오른다."""
    import json

    from app import state as st
    from tests.test_state_gates import build_ir, load_case

    ir = build_ir(load_case("gate_f1_clean"), snapshot_id="S1")
    ir["project_id"] = "P1"
    store.execute(
        "INSERT INTO rr_snapshots(id, project_id, owner_sub, ir_version, ir_hash, ir_json, source_ids_json,"
        " kinds_json, created_at) VALUES ('S1','P1',?, ?, ?, ?, '[]','[\"mcad\"]', 1)",
        (OWNER, ir["ir_version"], ir["ir_hash"], json.dumps(ir, ensure_ascii=False, sort_keys=True)))

    before_row = store.query_one("SELECT ir_json, ir_hash FROM rr_snapshots WHERE id = 'S1'")
    first = st.compute_state_for_snapshot(store, "S1")
    assert {h["rule"]: h["pass"] for h in first["rule_hits"]}["R-007"] is None      # 요구 0건 → 평가 불가

    _post(store, [{"kind": "dim_limit", "name": "gap_main", "op": "lte", "value_json": 0.2, "unit": "mm"}])
    monkeypatch.setattr(st, "now_epoch", lambda: first["computed_at"] + 10)
    second = st.compute_state_for_snapshot(store, "S1")

    after_row = store.query_one("SELECT ir_json, ir_hash FROM rr_snapshots WHERE id = 'S1'")
    assert after_row["ir_json"] == before_row["ir_json"]           # 원본 바이트 불변
    assert after_row["ir_hash"] == before_row["ir_hash"]
    assert second["computed_at"] > first["computed_at"]
    assert second["missing"]["req_absent"] is False
    assert "req.margin" in second["signals"]


# ---------------------------------------------------------------- req: 참조(plan §0.2.1 (5))
def test_a_requirement_reference_parses_without_falling_through_to_incident():
    """`parse_ref` 의 마지막 줄이 catch-all `inc:` 다 — 분기를 빠뜨리면 req: 가 사고 참조로 읽혀 등급이 튄다."""
    from app.common import REF_SCHEMES, parse_ref

    assert "req" in REF_SCHEMES
    assert parse_ref("req:thickness") == {"kind": "req", "name": "thickness", "ref": "req:thickness"}
    assert parse_ref("req:") is None


def test_a_registered_requirement_resolves_and_grades_as_measured(risk_store):
    """좌석 계약(std·_common)이 `req:` 인용을 지시한다 — 등록된 요구는 §0.2.1 (5) 대로 `측정` 이다."""
    from app import narrative

    risk_store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
        " VALUES ('P1','u@x','F7','F7',1,1)")
    risk_store.execute(
        "INSERT INTO rr_requirements(id, project_id, owner_sub, kind, name, op, value_json, unit, status,"
        " created_at, updated_at) VALUES ('R1','P1','u@x','dim_limit','thickness','gte','0.3','mm',"
        "'confirmed',1,1)")
    ctx = narrative.SpecContext(project_id="P1", owner_sub="u@x", store=risk_store)

    resolved = narrative.resolve_cites([{"ref": "req:thickness"}], ctx, claim="두께 여유", raised_by=["std"])

    assert resolved["dangling"] == []
    assert narrative.evidence_grade_from_cites(resolved, ctx) == "측정"


def test_an_unregistered_requirement_stays_dangling_and_heuristic(risk_store):
    """등록되지 않은 요구를 인용하면 dangling 이고 등급은 경험칙이다 — 지어낸 요구가 등급을 올리지 못한다."""
    from app import narrative

    risk_store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
        " VALUES ('P1','u@x','F7','F7',1,1)")
    ctx = narrative.SpecContext(project_id="P1", owner_sub="u@x", store=risk_store)

    resolved = narrative.resolve_cites([{"ref": "req:nope"}], ctx, claim="근거 없음", raised_by=["std"])

    assert resolved["dangling"] == ["req:nope"]
    assert narrative.evidence_grade_from_cites(resolved, ctx) == "경험칙"


# ------------------------------------------------- 적대 검증에서 확정된 등급 결함(2026-09-25)
def test_a_waived_requirement_does_not_raise_the_grade(risk_store):
    """정본 §4.3.1 — 범위는 `status ∈ candidate|confirmed` 다. `waived` 는 과제가 **포기한** 요구다.

    걸러내지 않으면 포기한 한계를 인용해 등급이 측정으로 오른다.
    """
    from app import narrative

    risk_store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
        " VALUES ('P1','u@x','F7','F7',1,1)")
    risk_store.execute(
        "INSERT INTO rr_requirements(id, project_id, owner_sub, kind, name, op, value_json, unit, status,"
        " waive_reason, created_at, updated_at) VALUES ('R1','P1','u@x','dim_limit','thickness','gte','0.3',"
        "'mm','waived','원가',1,1)")
    ctx = narrative.SpecContext(project_id="P1", owner_sub="u@x", store=risk_store)

    resolved = narrative.resolve_cites([{"ref": "req:thickness"}], ctx, raised_by=["std"])

    assert resolved["dangling"] == ["req:thickness"]
    assert narrative.evidence_grade_from_cites(resolved, ctx) == "경험칙"


def test_a_standard_requirement_grades_as_literature_not_measured(risk_store):
    """정본 §2.8b — "`standard` kind 만 예외이며 등급은 측정이 아니라 문헌·규격 이다".

    규격 번호를 인용한 것은 실측이 아니다. 이 예외가 없으면 요구 행 하나만 등록돼 있어도
    전 클러스터가 측정으로 올라 `all_heuristic` 안전장치와 `[가설 단계]` 표기가 사실상 죽는다.
    """
    from app import narrative

    risk_store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
        " VALUES ('P1','u@x','F7','F7',1,1)")
    risk_store.execute(
        "INSERT INTO rr_requirements(id, project_id, owner_sub, kind, name, value_json, status, source_ref,"
        " created_at, updated_at) VALUES ('R1','P1','u@x','standard','IEC 62368-1 §5.4',"
        "'{\"clause\":\"5.4\",\"title\":\"t\"}','confirmed','card:abc',1,1)")
    ctx = narrative.SpecContext(project_id="P1", owner_sub="u@x", store=risk_store)

    resolved = narrative.resolve_cites([{"ref": "req:IEC 62368-1 §5.4"}], ctx, raised_by=["std"])

    assert resolved["dangling"] == []
    assert narrative.evidence_grade_from_cites(resolved, ctx) == "문헌·규격"


def test_the_same_name_in_two_kinds_resolves_deterministically(risk_store):
    """UNIQUE 는 `(project_id, kind, name)` 이다 — 정렬 없이 한 행만 집으면 등급이 흔들린다."""
    from app import narrative

    risk_store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
        " VALUES ('P1','u@x','F7','F7',1,1)")
    for rid, kind in (("R1", "standard"), ("R2", "scenario")):
        risk_store.execute(
            "INSERT INTO rr_requirements(id, project_id, owner_sub, kind, name, value_json, status,"
            " source_ref, created_at, updated_at) VALUES (?,?,'u@x',?,'drop','{}','confirmed','card:a',1,1)",
            (rid, "P1", kind))
    ctx = narrative.SpecContext(project_id="P1", owner_sub="u@x", store=risk_store)

    picks = {ctx.requirement("drop")["kind"] for _ in range(5)}
    assert picks == {"scenario"}, "kind 순서가 결정론이 아니다"
