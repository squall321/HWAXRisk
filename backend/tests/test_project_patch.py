# PATCH /projects/{id}·멤버십 갈래·PAT 폐기 대조·회수 격리 시험 — plan §8.2.3·§5.2.1·§8.2.7·§3.4.1
from __future__ import annotations

import dataclasses
import json

import httpx
import pytest

from app import common, config, ra_client, routes, runner
from app.errors import AppError

OWNER = "owner@example.com"
EDITOR = "editor@example.com"


def _ident(email: str | None = OWNER, role: str | None = None):
    return type("I", (), {"anonymous": email is None, "email": email, "role": role,
                          "to_dict": lambda self: {"email": email}})()


def _project(store, project_id: str = "p1") -> str:
    now = common.now_epoch()
    store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
        " VALUES (?, ?, ?, '과제', ?, ?)", (project_id, OWNER, f"PRJ-{project_id}", now, now))
    store.execute(
        "INSERT INTO rr_project_members(project_id, owner_sub, email, role, added_by, added_at, updated_at)"
        " VALUES (?, ?, ?, 'owner', ?, ?, ?)", (project_id, OWNER, OWNER, OWNER, now, now))
    return project_id


# ---------------------------------------------------------------- PATCH(plan §8.2.3)
def test_create_project_writes_the_owner_member_row(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    out = routes.create_project(routes.ProjectBody(code="PRJ-A", name="새 과제"), ident=_ident())
    row = risk_store.query_one(
        "SELECT email, role FROM rr_project_members WHERE project_id = ?", (out["id"],))
    assert (row["email"], row["role"]) == (OWNER, "owner")


def test_patch_toggles_mcp_visibility_and_releases_withheld(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    project_id = _project(risk_store)
    now = common.now_epoch()
    sync = ra_client.empty_sync()
    sync["ra"] = {**sync["ra"], "state": "withheld", "pending_ops": [{"op": "create_object"}]}
    risk_store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, level,"
        " external_sync_json, created_at, updated_at)"
        " VALUES ('snap:s1', ?, 'snap', 's1', ?, 'h1', 'C0', ?, ?, ?)",
        (OWNER, project_id, json.dumps(sync), now, now))

    out = routes.patch_project(project_id, routes.ProjectPatchBody(mcp_visibility="org"), ident=_ident())
    assert out["project"]["mcp_visibility"] == "org"
    assert out["resynced"] == {"targets": 1, "ra_ops_released": 1}
    assert ra_client.load_external_sync(risk_store, "snap:s1")["ra"]["state"] == "pending"
    assert risk_store.query_one(
        "SELECT COUNT(*) AS n FROM rr_audit WHERE action = 'project.mcp_visibility'")["n"] == 1
    # 이제 org 갈래가 실제로 열린다 — service caller 의 visible_projects 가 이 과제를 본다(§8.2.5 ②).
    assert routes.visible_projects(dict(routes.SERVICE_CALLER)) == [project_id]


def test_patch_requires_owner_for_visibility_and_a_reason_for_exclusion(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    project_id = _project(risk_store)
    now = common.now_epoch()
    risk_store.execute(
        "INSERT INTO rr_project_members(project_id, owner_sub, email, role, added_by, added_at, updated_at)"
        " VALUES (?, ?, ?, 'editor', ?, ?, ?)", (project_id, OWNER, EDITOR, OWNER, now, now))

    with pytest.raises(AppError) as role:
        routes.patch_project(project_id, routes.ProjectPatchBody(mcp_visibility="org"),
                             ident=_ident(EDITOR))
    assert (role.value.code, role.value.http_status) == ("role_insufficient", 403)

    with pytest.raises(AppError) as reason:
        routes.patch_project(project_id, routes.ProjectPatchBody(corpus_excluded=True), ident=_ident())
    assert (reason.value.code, reason.value.http_status) == ("excluded_reason_required", 422)

    out = routes.patch_project(project_id, routes.ProjectPatchBody(
        corpus_excluded=True, excluded_reason="fixture"), ident=_ident())
    assert out["project"]["corpus_excluded"] == 1
    assert set(out["recomputed"]) == {"delta_priors_rows", "patterns_rows"}


def test_patch_refuses_purged_projects_and_unknown_vocabulary(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    project_id = _project(risk_store)
    with pytest.raises(AppError) as bad:
        routes.patch_project(project_id, routes.ProjectPatchBody(lifecycle="zombie"), ident=_ident())
    assert bad.value.http_status == 422

    risk_store.execute("UPDATE rr_projects SET status = 'purged' WHERE id = ?", (project_id,))
    with pytest.raises(AppError) as purged:
        routes.patch_project(project_id, routes.ProjectPatchBody(lifecycle="archived"), ident=_ident())
    assert (purged.value.code, purged.value.http_status) == ("project_purged", 409)


def test_membership_opens_the_project_to_an_invited_editor(risk_store, monkeypatch):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    project_id = _project(risk_store)
    now = common.now_epoch()
    assert routes.visible_projects({"kind": "user", "email": EDITOR}) == []
    risk_store.execute(
        "INSERT INTO rr_project_members(project_id, owner_sub, email, role, added_by, added_at, updated_at)"
        " VALUES (?, ?, ?, 'editor', ?, ?, ?)", (project_id, OWNER, EDITOR, OWNER, now, now))
    assert routes.visible_projects({"kind": "user", "email": EDITOR}) == [project_id]
    assert routes.require_role(project_id, EDITOR, "editor") == "editor"
    with pytest.raises(AppError) as exc:
        routes.require_role(project_id, "stranger@example.com", "viewer")
    assert exc.value.http_status == 404


# ---------------------------------------------------------------- PAT 폐기 대조(plan §8.2.7)
def _revoked_client(payload, status: int = 200):
    def handler(_request):
        return httpx.Response(status, json=payload)
    return httpx.MockTransport(handler)


def test_revocation_poll_marks_only_the_listed_jti(risk_store, monkeypatch):
    risk_store.upsert_credential("a@x.com", "enc-a", "sub-a", "a@x.com", "[]", 0, "[]", "jti-a")
    risk_store.upsert_credential("b@x.com", "enc-b", "sub-b", "b@x.com", "[]", 0, "[]", "jti-b")
    monkeypatch.setattr(runner, "_revoked_transport", _revoked_client({"revoked": ["jti-a"]}))

    out = runner.poll_revoked_pats(risk_store, config.settings, now=1234)
    assert out == {"checked": 1, "revoked": 1}
    assert risk_store.get_credential("a@x.com")["revoked_at"] == 1234
    assert risk_store.get_credential("b@x.com")["revoked_at"] is None


def test_malformed_revocation_list_changes_nothing(risk_store, monkeypatch):
    risk_store.upsert_credential("a@x.com", "enc-a", "sub-a", "a@x.com", "[]", 0, "[]", "jti-a")
    for payload, status in (({"oops": []}, 200), ({"revoked": ["jti-a"]}, 503)):
        monkeypatch.setattr(runner, "_revoked_transport", _revoked_client(payload, status))
        assert runner.poll_revoked_pats(risk_store, config.settings) == {"checked": 0, "revoked": 0}
        assert risk_store.get_credential("a@x.com")["revoked_at"] is None


def test_re_registering_clears_the_revocation_mark(risk_store):
    """폐기 표기가 남아 있으면 재등록해도 credential_pat 이 영구히 None 이다 — 그 자리를 닫는다."""
    risk_store.upsert_credential("a@x.com", "enc-a", "sub-a", "a@x.com", "[]", 0, "[]", "jti-a")
    risk_store.execute("UPDATE _user_credentials SET revoked_at = 1, revoked_seen_at = 1"
                       " WHERE owner_sub = 'a@x.com'")
    assert risk_store.get_credential("a@x.com")["revoked_at"] == 1
    risk_store.upsert_credential("a@x.com", "enc-a2", "sub-a", "a@x.com", "[]", 0, "[]", "jti-a2")
    row = risk_store.get_credential("a@x.com")
    assert row["revoked_at"] is None and row["revoked_seen_at"] is None


def test_credential_writes_join_an_open_transaction(risk_store):
    """tx() 안의 upsert 가 바깥 트랜잭션을 중간에 커밋하지 않는다(자격 회전을 감사 로그와 묶는 자리)."""
    try:
        with risk_store.tx():
            risk_store.upsert_credential("c@x.com", "enc-c", "sub-c", "c@x.com", "[]", 0, "[]", "jti-c")
            raise RuntimeError("중간 실패")
    except RuntimeError:
        pass
    assert risk_store.get_credential("c@x.com") is None


# ---------------------------------------------------------------- 반출 경계(plan §0.6·§5.2.6 (ii))
def test_export_skips_purged_and_excluded_projects(risk_store):
    from app import export as export_module

    _project(risk_store, "p_keep")
    _project(risk_store, "p_drop")
    _project(risk_store, "p_purged")
    risk_store.execute("UPDATE rr_projects SET corpus_excluded = 1, excluded_reason = 'fixture'"
                       " WHERE id = 'p_drop'")
    risk_store.execute("UPDATE rr_projects SET status = 'purged' WHERE id = 'p_purged'")

    ids = {json.loads(line)["row"]["id"]
           for line in list(export_module.iter_lines(risk_store, OWNER))[1:]
           if json.loads(line)["table"] == "rr_projects"}
    assert ids == {"p_keep"}
    with_excluded = {json.loads(line)["row"]["id"]
                     for line in list(export_module.iter_lines(risk_store, OWNER, include_excluded=True))[1:]
                     if json.loads(line)["table"] == "rr_projects"}
    assert with_excluded == {"p_keep", "p_drop"}


def test_export_group_gate_and_classification_header(risk_store, monkeypatch):
    from app import export as export_module

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    _project(risk_store, "p_keep")
    assert export_module.classification_max(risk_store, OWNER) == "confidential"
    risk_store.execute("UPDATE rr_projects SET classification = 'internal' WHERE id = 'p_keep'")
    assert export_module.classification_max(risk_store, OWNER) == "internal"

    monkeypatch.setattr(config, "settings",
                        dataclasses.replace(config.settings, risk_export_allowed_groups=["export"]))
    with pytest.raises(AppError) as exc:
        routes.get_export(ident=_ident(OWNER, role="member"))
    assert (exc.value.code, exc.value.http_status) == ("export_not_allowed", 403)
    assert routes.get_export(ident=_ident(OWNER, role="export")) is not None


def test_export_copies_are_purged_after_the_retention_window(tmp_path, monkeypatch):
    from app import export as export_module

    out_dir = tmp_path / export_module.EXPORTS_DIRNAME
    out_dir.mkdir()
    old = out_dir / "1.jsonl"
    old.write_text("{}\n", encoding="utf-8")
    import os
    os.utime(old, (0, 0))
    fresh = out_dir / "2.jsonl"
    fresh.write_text("{}\n", encoding="utf-8")

    assert export_module.purge_old_exports(tmp_path, retain_days=30) == 1
    assert not old.exists() and fresh.exists()


# ---------------------------------------------------------------- 회수 격리(plan §3.4.1·§6.11)
def _finding_spec(target_key: str, seat_key: str) -> dict:
    cite = [{"ref": "p:0123456789ab", "quote": "«PLATE_1»"}]
    finding = {
        "id": "F1", "direction": "risk", "domain": "mech",
        "mechanism": "mechanical", "mechanism_detail": "drop_stress", "change_kind": "dimension",
        "subject": {"ckeys": ["ck:aaaa1111bbbb"], "names": ["PLATE_1"]},
        "severity": "중대", "judgement": "WARNING",
        "detectability": {"level": "sim-detectable", "tool": "report_part_risk"},
        "evidence_grade": "도구예측", "precedent": "none", "cites": cite, "tool_calls": [],
        "claim": "낙하 시 상단 리브에 응력이 집중된다",
        "warrant": "리브가 얇아 낙하 하중 경로가 한 점으로 모인다",
        "resolving_check": {"kind": "sim", "ref": "report_part_risk"},
        "owner_domain": "mech", "raised_by": [seat_key], "contested_by": [], "contest_note": "",
        "status": "open",
    }
    return {
        "schema": "risk_spec", "version": "1.0", "taxonomy_version": "1.0",
        "scope": {"kind": "diff", "target_key": target_key, "project_refs": ["p1"],
                  "ir_refs": [], "diff_ref": "d1", "ir_hash": "h1"},
        "findings": [finding], "gains": [], "cross_domain": [],
        "character": {"one_liner": "강성 우선 설계", "facets": []},
        "open_items": [], "coverage": {"seats": [], "domains_seated": ["mech"], "domains_missing": []},
        "verdict": "conditional", "verdict_conditions": [],
        "evidence_profile": {"tool": 0, "card": 0, "precedent": {"verified": 0, "dismissed": 0},
                             "heuristic": 0, "measured": 0},
    }


def test_unverified_actor_findings_are_excluded_from_recall(risk_store, monkeypatch):
    """MCP 경로(actor_verified=false)가 낸 원자는 recall_eligible=0 으로 앉아 다른 과제 브리프로 번지지 않는다."""
    import app.mcp_server as srv
    from app import planner
    from tests.test_wiring_regressions import _seed

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    seat_key = panel["seats"][0]["key"]
    spec = _finding_spec(target_key, seat_key)
    decision = ("F1 낙하 시 상단 리브에 응력이 집중된다.\n\n```json\n"
                + json.dumps(spec, ensure_ascii=False) + "\n```\n")

    out = srv.risk_submit_panel_result(
        panel_id=panel["id"], engine="mcp", decision_text=decision,
        turns=[{"round": 1, "persona": s["key"], "say": "발언"} for s in panel["seats"]],
        report_id=None, actor=OWNER)   # MCP 경로는 owner 가 내도 actor_verified=false 다(§6.11)
    assert "error" not in out and out["parsed"] is True, out

    rows = risk_store.query("SELECT recall_eligible FROM rr_findings WHERE panel_id = ?", (panel["id"],))
    assert rows and all(r["recall_eligible"] == 0 for r in rows)
    # 승격이 세는 원자에서도 빠진다(learning.collect_atoms 는 recall_eligible=1 만 본다).
    from app import learning
    assert not any(a for group in learning.collect_atoms(risk_store).values() for a in group
                   if a.get("panel_id") == panel["id"])


def test_verified_actor_keeps_findings_recallable(risk_store, monkeypatch):
    from app import planner
    from tests.test_wiring_regressions import _seed

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    target_key = _seed(risk_store)
    panel = planner.plan_next_panel(risk_store, target_key, "B")
    spec = _finding_spec(target_key, panel["seats"][0]["key"])
    decision = ("F1 낙하 시 상단 리브에 응력이 집중된다.\n\n```json\n"
                + json.dumps(spec, ensure_ascii=False) + "\n```\n")
    routes.complete_panel(panel["id"], engine="web", decision_text=decision,
                          turns=[{"round": 1, "persona": s["key"], "say": "발언"} for s in panel["seats"]],
                          actor=OWNER, actor_verified=True, owner_sub=OWNER)
    rows = risk_store.query("SELECT recall_eligible FROM rr_findings WHERE panel_id = ?", (panel["id"],))
    assert rows and all(r["recall_eligible"] == 1 for r in rows)
