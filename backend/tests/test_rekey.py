# 확정 되돌리기의 키 전파(rekey) — §5.9.5 여섯 걸음을 걸음마다 · 확정 → 되돌리기 왕복 · 6홉 409 · 한 트랜잭션(plan §5.9.5 · §4.3.2 · P3 (22))
from __future__ import annotations

import json

import pytest

from app import brief, common, narrative, registry, rekey, routes, sameas
from app.errors import AppError
from tests import factories

OWNER = factories.OWNER
X, Y, Z, W, Q = "ck:" + "1" * 12, "ck:" + "2" * 12, "ck:" + "3" * 12, "ck:" + "4" * 12, "ck:" + "9" * 12
A, B, C = "ck:" + "a" * 12, "ck:" + "b" * 12, "ck:" + "c" * 12
MECH, DETAIL, CHANGE = "mechanical", "drop_stress", "dimension"


def key_of(subject: str) -> str:
    return narrative.cluster_key_of(MECH, DETAIL, subject, CHANGE)


@pytest.fixture
def clock():
    state = {"t": 1000}
    previous = common.set_clock(lambda: state["t"])
    yield state
    common.set_clock(previous)


def _part(store, ckey: str, *, status: str = "confirmed", merged_into: str | None = None,
          decided_by: str | None = None, evidence: dict | None = None) -> None:
    store.execute(
        "INSERT INTO rr_part_keys(ckey, owner_sub, status, merged_into, name_norm_canon, geom_bucket, material_norm,"
        " merge_evidence_json, decided_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,1,1)",
        (ckey, OWNER, status, merged_into, ckey[3:], "1.0@v1", "steel",
         common.canonical_json(evidence) if evidence is not None else None, decided_by))


def _target(store, target_key: str, project_id: str) -> None:
    store.execute("INSERT OR IGNORE INTO rr_projects(id, owner_sub, code, name, created_at, updated_at)"
                  " VALUES (?,?,?,?,1,1)", (project_id, OWNER, project_id, project_id))
    store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, external_sync_json,"
        " created_at, updated_at) VALUES (?,?,'snap',?,?,'h','{}',1,1)", (target_key, OWNER, target_key[5:], project_id))


def _finding(store, target_key: str, fid: str, subject: str, *, panel: str, severity: str = "중대",
             cluster_key: str | None = None, checks: tuple[str, ...] = ()) -> None:
    fj = {"claim": f"{fid} 주장", "warrant": "근거", "raised_by": ["mech-syn-0"], "contested_by": [],
          "cites": [], "resolving_checks": list(checks), "feature_snapshot": {}, "subject": {"names": []}}
    store.execute(
        "INSERT INTO rr_findings(finding_id, claim_uid, target_key, panel_id, project_id, owner_sub, direction,"
        " domain, mechanism, mechanism_detail, change_kind, subject_key, severity, sev3, judgement, evidence_grade,"
        " precedent, cluster_key, finding_json, created_at) VALUES (?,?,?,?,?,?,'risk','mech',?,?,?,?,?,?,'WARNING',"
        " '도구예측','none',?,?,100)",
        (fid, f"{panel}#{fid}", target_key, panel,
         store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (target_key,))["project_id"],
         OWNER, MECH, DETAIL, CHANGE, subject, severity, registry.SEVERITY_ORDER[severity],
         cluster_key or key_of(subject), common.canonical_json(fj)))


def _world(store) -> None:
    """X · Y 두 파트, 대상 T1(F1 = Y 중대 · F2 = X 치명, 같은 패널) · T2(F3 = Y). 병합까지 마친다."""
    for ck in (X, Y, Z, W):
        _part(store, ck)
    _target(store, "snap:T1", "P1")
    _target(store, "snap:T2", "P2")
    _finding(store, "snap:T1", "F1", Y, panel="PN1", severity="중대", checks=("test:낙하",))
    _finding(store, "snap:T1", "F2", X, panel="PN1", severity="치명")
    _finding(store, "snap:T2", "F3", Y, panel="PN2", severity="중대")
    registry.merge(store, "snap:T1", owner_sub=OWNER)
    registry.merge(store, "snap:T2", owner_sub=OWNER)


def _registry(store) -> dict:
    return {(r["target_key"], r["cluster_key"]): (r["status"], r["superseded_by"], r["support"], r["severity"])
            for r in store.query("SELECT target_key, cluster_key, status, superseded_by, support, severity"
                                 " FROM rr_registry ORDER BY target_key, cluster_key")}


def _priors(store) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT change_kind, mechanism, mechanism_detail, n_raised, n_targets, n_improvement, sev_hist_json,"
        " top_resolving_checks_json FROM rr_delta_priors ORDER BY change_kind, mechanism, mechanism_detail")]


def _contrib(store) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT change_kind, mechanism, mechanism_detail, target_key, n_raised, n_improvement, sev_hist_json,"
        " resolving_checks_json FROM rr_delta_contrib ORDER BY target_key, change_kind")]


def _decide(store, **payload) -> dict:
    return sameas.record_decision(store, payload, owner_sub=OWNER)


def _alias(store, old_key: str):
    return store.query_one("SELECT * FROM rr_cluster_alias WHERE owner_sub = ? AND old_cluster_key = ?", (OWNER, old_key))


def _audits(store) -> list[dict]:
    return [dict(r) for r in store.query(
        "SELECT actor, channel, scope, subject_id, project_id, action, before_json, after_json, at FROM rr_audit"
        " WHERE action = 'rekey' ORDER BY at, subject_id")]


# ---------------------------------------------------------------- 2·3걸음의 재료 — 지금 원장의 주체
def test_current_subject_follows_the_merge_chain_and_live_aliases_only(risk_store):
    _part(risk_store, X)
    _part(risk_store, Y, status="merged", merged_into=X)
    _part(risk_store, Z, status="merged", merged_into=Y)              # Z → Y → X
    assert rekey.current_subject(risk_store, Z, OWNER) == (X, "ckey_merge")
    assert rekey.current_subject(risk_store, X, OWNER) == (X, "")
    assert rekey.current_subject(risk_store, f"{A}|{Z}", OWNER) == ("|".join(sorted((A, X))), "ckey_merge")
    for other in ("dim:plate1_t", "asm:a_stack/stack_asm", ""):
        assert rekey.current_subject(risk_store, other, OWNER) == (other, "")
    # 계면 쌍은 살아 있는 계면 별칭으로 접는다 — 철회한 별칭으로는 접지 않는다.
    risk_store.execute(
        "INSERT INTO rr_iface_alias(alias_key, canonical_a, canonical_b, owner_sub, aliases_json, source, score, status)"
        " VALUES (?,?,?,?,'[]','human',1.0,'active')", (f"{A}|{B}", A, C, OWNER))
    assert rekey.current_subject(risk_store, f"{A}|{B}", OWNER) == (f"{A}|{C}", "iface_alias")
    risk_store.execute("UPDATE rr_iface_alias SET status = 'revoked' WHERE alias_key = ?", (f"{A}|{B}",))
    assert rekey.current_subject(risk_store, f"{A}|{B}", OWNER) == (f"{A}|{B}", "")


def test_new_findings_are_not_folded_through_a_revoked_alias(risk_store):
    """저장 때 주체 정규화(`narrative._iface_alias`)도 살아 있는 별칭만 본다 — 철회한 별칭으로 새 원자를 접지 않는다."""
    risk_store.execute(
        "INSERT INTO rr_iface_alias(alias_key, canonical_a, canonical_b, owner_sub, aliases_json, source, score, status)"
        " VALUES (?,?,?,?,'[]','human',1.0,'active')", (f"{A}|{B}", A, C, OWNER))
    ctx = narrative.SpecContext(store=risk_store)
    assert narrative.resolve_subject({"ckeys": [B, A]}, ctx)["subject_key"] == f"{A}|{C}"
    risk_store.execute("UPDATE rr_iface_alias SET status = 'revoked' WHERE alias_key = ?", (f"{A}|{B}",))
    assert narrative.resolve_subject({"ckeys": [B, A]}, ctx)["subject_key"] == f"{A}|{B}"


# ---------------------------------------------------------------- 1걸음 — 원장 이력(행 삭제 없음)
def test_step1_a_reversed_same_as_keeps_the_previous_decision(risk_store, clock):
    args = {"scope": "pair", "a": "mcad:/a", "b": "mcad:/b", "pair_key": "P1|P2"}
    sameas.record_decision(risk_store, {"decision": "confirm", **args}, owner_sub=OWNER, decided_by="first@example.com")
    clock["t"] = 2000
    sameas.record_decision(risk_store, {"decision": "reject", **args}, owner_sub=OWNER, decided_by="second@example.com")
    row = risk_store.query_one("SELECT * FROM rr_sameas WHERE pair_key = 'P1|P2'")
    assert (row["status"], row["decided_by"], row["decided_at"]) == ("rejected", "second@example.com", 2000)
    assert (row["prev_status"], row["prev_decided_by"], row["prev_decided_at"]) == ("confirmed", "first@example.com", 1000)
    # 같은 결정을 다시 내면 이력은 그대로다 — 뒤집힌 결정만 남긴다.
    clock["t"] = 3000
    sameas.record_decision(risk_store, {"decision": "reject", **args}, owner_sub=OWNER, decided_by="third@example.com")
    again = risk_store.query_one("SELECT * FROM rr_sameas WHERE pair_key = 'P1|P2'")
    assert (again["prev_status"], again["prev_decided_by"], again["prev_decided_at"]) == ("confirmed", "first@example.com", 1000)
    assert [r["id"] for r in risk_store.query("SELECT id FROM rr_sameas")] == [row["id"]]      # 행 하나로 유지한다


def test_step1_unmerge_writes_the_ledger_back_and_alias_revoke_marks_the_row(risk_store, clock):
    _world(risk_store)
    _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)
    clock["t"] = 2000
    _decide(risk_store, decision="unmerge_key", ckey=Y)
    row = risk_store.query_one("SELECT status, merged_into, merge_evidence_json, decided_at FROM rr_part_keys WHERE ckey = ?", (Y,))
    assert (row["status"], row["merged_into"], row["merge_evidence_json"], row["decided_at"]) == ("confirmed", None, None, 2000)

    risk_store.execute(
        "INSERT INTO rr_iface_alias(alias_key, canonical_a, canonical_b, owner_sub, aliases_json, source, score)"
        " VALUES (?,?,?,?,'[]','auto',1.0)", (f"{X}|{Z}", X, Z, OWNER))
    clock["t"] = 3000
    out = _decide(risk_store, decision="revoke_iface_alias", alias_key=f"{X}|{Z}")
    alias = risk_store.query_one("SELECT status, revoked_by, revoked_at FROM rr_iface_alias WHERE alias_key = ?", (f"{X}|{Z}",))
    assert (alias["status"], alias["revoked_by"], alias["revoked_at"]) == ("revoked", OWNER, 3000)
    assert out["revoked"] is True and _decide(risk_store, decision="revoke_iface_alias", alias_key=f"{X}|{Z}")["already"]
    with pytest.raises(AppError) as missing:
        _decide(risk_store, decision="revoke_iface_alias", alias_key=f"{X}|{W}")
    assert missing.value.http_status == 404


# ---------------------------------------------------------------- 3걸음 — 별칭 append · revoke
def test_step3_merge_appends_a_ledger_alias_and_unmerge_revokes_it_by_the_same_person_at_the_same_time(risk_store, clock):
    _world(risk_store)
    sameas.record_decision(risk_store, {"decision": "merge_key", "ckey_from": Y, "ckey_into": X}, owner_sub=OWNER,
                           decided_by="merger@example.com")
    alias = _alias(risk_store, key_of(Y))
    assert (alias["new_cluster_key"], alias["reason"], alias["decided_by"], alias["decided_at"], alias["revoked_at"]) == (
        key_of(X), "ckey_merge", "merger@example.com", 1000, None)
    assert registry.resolve_cluster_key(risk_store, key_of(Y), owner_sub=OWNER) == key_of(X)
    assert rr_findings_keys(risk_store) == {"F1": key_of(Y), "F2": key_of(X), "F3": key_of(Y)}   # 원자 키는 동결이다

    clock["t"] = 2000
    sameas.record_decision(risk_store, {"decision": "unmerge_key", "ckey": Y}, owner_sub=OWNER,
                           decided_by="undoer@example.com")
    alias = _alias(risk_store, key_of(Y))
    part = risk_store.query_one("SELECT decided_by, decided_at FROM rr_part_keys WHERE ckey = ?", (Y,))
    assert (alias["revoked_by"], alias["revoked_at"]) == (part["decided_by"], part["decided_at"]) == ("undoer@example.com", 2000)
    assert registry.resolve_cluster_key(risk_store, key_of(Y), owner_sub=OWNER) == key_of(Y)
    assert rr_findings_keys(risk_store) == {"F1": key_of(Y), "F2": key_of(X), "F3": key_of(Y)}


def rr_findings_keys(store) -> dict:
    return {r["finding_id"]: r["cluster_key"] for r in store.query("SELECT finding_id, cluster_key FROM rr_findings")}


def test_step3_leaves_a_human_alias_alone(risk_store):
    """사람이 세운 별칭(cluster_merge)은 원장 재키가 거두거나 덮지 않는다 — 그 사실을 결과에 남긴다."""
    _world(risk_store)
    registry.add_cluster_alias(risk_store, key_of(Y), key_of(Z), owner_sub=OWNER, reason="cluster_merge")
    out = _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)["rekey"]
    alias = _alias(risk_store, key_of(Y))
    assert (alias["new_cluster_key"], alias["reason"], alias["revoked_at"]) == (key_of(Z), "cluster_merge", None)
    assert out["aliases_added"] == [] and out["kept_human"] == [
        {"cluster_key": key_of(Y), "alias": key_of(Z), "reason": "cluster_merge", "ledger_wants": key_of(X)}]


def test_step3_skips_a_frozen_key_it_cannot_reproduce(risk_store):
    """동결 cluster_key 를 같은 식으로 다시 만들 수 없는 원자는 옮기지 않는다 — 다른 식의 키를 지어 별칭으로 잇지 않는다."""
    _world(risk_store)
    _finding(risk_store, "snap:T1", "F9", Y, panel="PN9", cluster_key="odd0odd0odd0")
    out = _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)["rekey"]
    assert {"cluster_key": "odd0odd0odd0", "reason": "key_not_reproducible"} in out["skipped"]
    assert _alias(risk_store, "odd0odd0odd0") is None


# ---------------------------------------------------------------- 4·5걸음 — 등록부 · priors · 패턴 · 큐
def test_step4_the_registry_folds_on_merge_and_splits_back_on_unmerge(risk_store):
    """병합되면 옛 키의 행은 superseded(superseded_by=대상#대표 키)로 닫히고 support 는 distinct 패널 수다. 되돌리면 그 행이 다시 열리고
    접힘으로만 섰던 행도 닫힌다 — 행은 지우지 않는다."""
    _world(risk_store)
    original = _registry(risk_store)
    assert original == {("snap:T1", key_of(X)): ("open", None, 1, "치명"), ("snap:T1", key_of(Y)): ("open", None, 1, "중대"),
                        ("snap:T2", key_of(Y)): ("open", None, 1, "중대")}

    _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)
    folded = _registry(risk_store)
    assert folded[("snap:T1", key_of(X))] == ("open", None, 1, "치명")                 # 같은 패널 둘 — 합이 아니라 1
    assert folded[("snap:T1", key_of(Y))] == ("superseded", f"snap:T1#{key_of(X)}", 1, "중대")
    assert folded[("snap:T2", key_of(X))] == ("open", None, 1, "중대")
    assert folded[("snap:T2", key_of(Y))] == ("superseded", f"snap:T2#{key_of(X)}", 1, "중대")
    assert registry.verdict_candidate(risk_store, "snap:T1")["counts"]["clusters"] == 1     # 두 번 세지 않는다

    _decide(risk_store, decision="unmerge_key", ckey=Y)
    split = _registry(risk_store)
    assert {k: v for k, v in split.items() if k in original} == original
    assert split[("snap:T2", key_of(X))] == ("superseded", f"snap:T2#{key_of(Y)}", 1, "중대")


def test_step5_priors_and_contributions_come_back_byte_for_byte(risk_store):
    _world(risk_store)
    before_priors, before_contrib = _priors(risk_store), _contrib(risk_store)
    assert json.loads(before_priors[0]["sev_hist_json"]) == {"중대": 2, "치명": 1}

    _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)
    merged = _priors(risk_store)
    assert json.loads(merged[0]["sev_hist_json"]) == {"중대": 1, "치명": 1} and merged[0]["n_raised"] == 2

    _decide(risk_store, decision="unmerge_key", ckey=Y)
    assert _priors(risk_store) == before_priors
    assert _contrib(risk_store) == before_contrib


def test_step5_patterns_are_reinterpreted(risk_store):
    """합쳐진 패턴은 대표 패턴을 merged_into 로 가리키고, 갈라지면 merged_into 가 NULL 로 돌아간다."""
    _world(risk_store)
    for pid, norm in (("pat-y", key_of(Y)), ("pat-x", key_of(X))):
        risk_store.execute(
            "INSERT INTO rr_patterns(id, owner_sub, cluster_key_norm, status, created_at, updated_at)"
            " VALUES (?,?,?,'candidate',1,1)", (pid, OWNER, norm))
    out = _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)["rekey"]
    assert out["patterns"] == [{"pattern_id": "pat-y", "merged_into": "pat-x"}]
    assert risk_store.query_one("SELECT merged_into FROM rr_patterns WHERE id = 'pat-y'")["merged_into"] == "pat-x"
    _decide(risk_store, decision="unmerge_key", ckey=Y)
    assert risk_store.query_one("SELECT merged_into FROM rr_patterns WHERE id = 'pat-y'")["merged_into"] is None


def test_step5_closes_merge_proposals_the_rekey_made_moot(risk_store, clock):
    """열린 cluster_merge 항목 가운데 두 키가 이제 한 키로 풀리는 것은 rejected · decision_json.reason='rekey' 로 닫힌다. 다른 쌍은 그대로다."""
    _world(risk_store)
    for qid, a, b in (("q-moot", key_of(Y), key_of(X)), ("q-other", key_of(Z), key_of(W))):
        risk_store.execute(
            "INSERT INTO rr_curation_queue(id, owner_sub, kind, payload_json, status, created_at)"
            " VALUES (?,?,'cluster_merge',?,'open',1)", (qid, OWNER, common.canonical_json({"a": a, "b": b})))
    _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)
    rows = {r["id"]: dict(r) for r in risk_store.query("SELECT id, status, decision_json, decided_by FROM rr_curation_queue")}
    assert (rows["q-moot"]["status"], json.loads(rows["q-moot"]["decision_json"])["reason"], rows["q-moot"]["decided_by"]) == (
        "rejected", "rekey", OWNER)
    assert rows["q-other"]["status"] == "open"


# ---------------------------------------------------------------- 6걸음 — rr_audit(rekey) 1행
def test_step6_each_operation_leaves_one_rekey_audit_row(risk_store, clock):
    _world(risk_store)
    _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)
    clock["t"] = 2000
    _decide(risk_store, decision="unmerge_key", ckey=Y)
    rows = _audits(risk_store)
    assert [(r["subject_id"], r["scope"], r["actor"], r["channel"], r["at"]) for r in rows] == [
        (f"ckey:{Y}", "registry", OWNER, "rest", 1000), (f"ckey:{Y}", "registry", OWNER, "rest", 2000)]
    before, after = json.loads(rows[1]["before_json"]), json.loads(rows[1]["after_json"])
    assert before["op"] == "unmerge_key" and before["old_cluster_keys"] == {key_of(Y): key_of(X)}
    assert after["new_cluster_keys"] == {key_of(Y): key_of(Y)}
    assert (after["findings_n"], after["targets_n"]) == (2, 2)
    # 뒤집을 확정이 없던 unmerge(이미 confirmed)는 재키를 돌지 않는다.
    _decide(risk_store, decision="unmerge_key", ckey=Y)
    assert len(_audits(risk_store)) == 2


# ---------------------------------------------------------------- 왕복 · 옛 reg: · 6홉 · 한 트랜잭션
def test_a_confirm_then_reject_round_trip_restores_the_registry_and_old_reg_refs_never_dangle(risk_store):
    """확정(merge_key) → 되돌리기(unmerge_key) 왕복에서 등록부 support · priors 가 처음 값으로 돌아오고, 옛 `reg:<target>#<old>` 인용은
    두 방향 모두에서 해석된다(dangling 0)."""
    _world(risk_store)
    registry_before, priors_before = _registry(risk_store), _priors(risk_store)
    refs = [{"kind": "reg", "target_key": t, "cluster_key": k} for t, k in registry_before]

    def dangling() -> list:
        with factories.routes_store(risk_store):
            return [r for r in refs if routes._ref_from_store(r, OWNER) is None]

    _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)
    # 확정이 등록부까지 왔다 — 옛 키의 행이 닫히고 priors 가 접힌 값이다(이것이 없으면 왕복은 아무것도 보지 않는다).
    assert _registry(risk_store)[("snap:T1", key_of(Y))][0] == "superseded" and _priors(risk_store) != priors_before
    assert dangling() == []
    _decide(risk_store, decision="unmerge_key", ckey=Y)
    assert dangling() == []
    assert {k: v for k, v in _registry(risk_store).items() if k in registry_before} == registry_before
    assert _priors(risk_store) == priors_before


def _human_chain(store, start: str, hops: int) -> None:
    keys = [start] + [f"h{i:011d}" for i in range(hops)]
    for old, new in reversed(list(zip(keys, keys[1:]))):
        registry.add_cluster_alias(store, old, new, owner_sub=OWNER, reason="cluster_merge")


def test_a_sixth_hop_is_409_and_the_ledger_change_rolls_back(risk_store):
    """대표 키 뒤로 사람 별칭이 이미 5홉이면 병합이 세울 6홉째 별칭은 409 다 — 원장 병합 · 별칭 · 등록부 · 감사가 하나도 남지 않는다."""
    _world(risk_store)
    _human_chain(risk_store, key_of(X), 5)
    registry_before = _registry(risk_store)
    with pytest.raises(AppError) as err:
        _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)
    assert (err.value.code, err.value.http_status) == ("alias_chain_too_long", 409)
    assert risk_store.query_one("SELECT status, merged_into FROM rr_part_keys WHERE ckey = ?", (Y,))["status"] == "confirmed"
    assert _alias(risk_store, key_of(Y)) is None and _audits(risk_store) == []
    assert _registry(risk_store) == registry_before


def test_a_sixth_hop_on_a_reversal_rolls_the_unmerge_back(risk_store):
    """되돌리기도 별칭을 세운다 — Z → Y → X 에서 Y 를 풀면 Z 의 원자는 Y 의 클러스터로 옮겨야 한다. 그 뒤로 사람 별칭이 5홉이면 409 이고
    unmerge 가 통째로 되돌아간다(원장 · 별칭 · 감사)."""
    _world(risk_store)
    _finding(risk_store, "snap:T1", "F4", Z, panel="PN4")
    registry.merge(risk_store, "snap:T1", owner_sub=OWNER)
    _human_chain(risk_store, key_of(Y), 5)                                   # Y 의 클러스터 뒤로 사람 별칭 5홉
    assert _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)["rekey"]["kept_human"]   # Y 는 사람 별칭이 이긴다
    _decide(risk_store, decision="merge_key", ckey_from=Z, ckey_into=Y)    # Z 의 원자는 Z → Y → X 의 끝(X)의 클러스터로
    assert _alias(risk_store, key_of(Z))["new_cluster_key"] == key_of(X)
    audits = len(_audits(risk_store))
    with pytest.raises(AppError) as err:
        _decide(risk_store, decision="unmerge_key", ckey=Y)
    assert (err.value.code, err.value.http_status) == ("alias_chain_too_long", 409)
    assert risk_store.query_one("SELECT merged_into FROM rr_part_keys WHERE ckey = ?", (Y,))["merged_into"] == X
    alias = _alias(risk_store, key_of(Z))
    assert (alias["new_cluster_key"], alias["revoked_at"]) == (key_of(X), None)
    assert len(_audits(risk_store)) == audits


def test_the_decide_route_is_one_transaction_with_its_rekeys(risk_store):
    """POST /sameas/decide 의 배열은 한 트랜잭션이다 — 뒤 항목이 404 면 앞 항목의 병합과 그 재키(별칭 · 등록부 · 감사)도 남지 않는다."""
    _world(risk_store)
    registry_before = _registry(risk_store)
    with factories.routes_store(risk_store), pytest.raises(AppError) as err:
        routes.post_sameas_decide([{"decision": "merge_key", "ckey_from": Y, "ckey_into": X},
                                   {"decision": "unmerge_key", "ckey": "ck:nowhere00000"}], ident=factories.ident(OWNER))
    assert err.value.http_status == 404
    assert risk_store.query_one("SELECT status FROM rr_part_keys WHERE ckey = ?", (Y,))["status"] == "confirmed"
    assert _alias(risk_store, key_of(Y)) is None and _audits(risk_store) == [] and _registry(risk_store) == registry_before
    # 맞대 보기 — 앞 항목만 보내면 같은 경로가 병합 · 별칭 · 감사를 남긴다(위의 '없음' 이 되돌림 때문임을 본다).
    with factories.routes_store(risk_store):
        routes.post_sameas_decide([{"decision": "merge_key", "ckey_from": Y, "ckey_into": X}], ident=factories.ident(OWNER))
    assert _alias(risk_store, key_of(Y))["new_cluster_key"] == key_of(X) and len(_audits(risk_store)) == 1


# ---------------------------------------------------------------- 네 조작 — same-as reject · 계면 원장 · 계면 별칭
def test_a_rejected_same_as_unmerges_the_rows_it_auto_inherited_and_rekeys(risk_store):
    """same-as 확정에서 자동 승계된 병합(§2.7.3 — 근거의 ledger_id 가 그 확정 행)은 reject 하면 되돌아가고 키 전파가 돈다.
    다른 확정에서 온 승계 행은 그대로다."""
    _world(risk_store)
    args = {"scope": "pair", "a": "mcad:/dv1/plate", "b": "mcad:/dv2/plate", "pair_key": "P1|P2"}
    _decide(risk_store, decision="confirm", **args)
    sameas_id = risk_store.query_one("SELECT id FROM rr_sameas")["id"]
    risk_store.execute("UPDATE rr_part_keys SET status = 'merged', merged_into = ?, decided_by = ?, merge_evidence_json = ?"
                       " WHERE ckey = ?", (X, rekey.AUTO_DECIDED_BY,
                                          common.canonical_json({"method": "ledger", "ledger_id": sameas_id}), Y))
    risk_store.execute("UPDATE rr_part_keys SET status = 'merged', merged_into = ?, decided_by = ?, merge_evidence_json = ?"
                       " WHERE ckey = ?", (X, rekey.AUTO_DECIDED_BY,
                                          common.canonical_json({"method": "exact_path", "ledger_id": "other"}), W))
    # 승계가 등록부까지 따라온 상태(별칭 ckey_merge)를 만든다.
    rekey.run(risk_store, op="merge_key", owner_sub=OWNER, ckeys={Y}, subject_id="test:inherit")
    assert _registry(risk_store)[("snap:T1", key_of(Y))][0] == "superseded"

    out = _decide(risk_store, decision="reject", **args)
    assert out["rekey"]["aliases_revoked"] == [{"old": key_of(Y), "new": key_of(X), "reason": "ckey_merge"}]
    row = risk_store.query_one("SELECT status, merged_into, merge_evidence_json FROM rr_part_keys WHERE ckey = ?", (Y,))
    assert (row["status"], row["merged_into"], row["merge_evidence_json"]) == ("confirmed", None, None)
    assert risk_store.query_one("SELECT merged_into FROM rr_part_keys WHERE ckey = ?", (W,))["merged_into"] == X
    assert _registry(risk_store)[("snap:T1", key_of(Y))] == ("open", None, 1, "중대")
    audit = [a for a in _audits(risk_store) if a["subject_id"] == f"sameas:{sameas_id}"]
    assert len(audit) == 1 and json.loads(audit[0]["before_json"])["ledger"]["unmerged"] == [Y]
    # 확정이 아니던 쌍의 reject 는 뒤집을 것이 없어 재키를 돌지 않는다.
    out = _decide(risk_store, decision="reject", scope="pair", a="mcad:/x", b="mcad:/y", pair_key="P1|P2")
    assert "rekey" not in out


def test_rejecting_a_confirmed_interface_ledger_row_leaves_one_rekey_audit(risk_store):
    """계면 원장의 확정(confirmed · manual)을 rejected 로 뒤집으면 같은 트랜잭션에서 재키가 돌고 rr_audit(rekey) 1행이 남는다 — 계면
    원장은 저장 키를 바꾸지 않아 별칭 · 등록부는 그대로다. 확정으로 바꾸는 쪽은 재키가 없다."""
    project_id = factories.make_project(risk_store)
    body = [routes.LedgerItem(pair_key="/a/p1|/a/p2", status="confirmed")]
    with factories.routes_store(risk_store):
        routes.put_iface_ledger(project_id, body, ident=factories.ident(OWNER))
        assert _audits(risk_store) == []
        routes.put_iface_ledger(project_id, [routes.LedgerItem(pair_key="/a/p1|/a/p2", status="rejected")],
                                ident=factories.ident(OWNER))
    audit = _audits(risk_store)
    assert [(a["subject_id"], a["project_id"]) for a in audit] == [(f"ledger:{project_id}:/a/p1|/a/p2", project_id)]
    assert json.loads(audit[0]["before_json"])["ledger"]["before"] == "confirmed"


def test_revoking_an_interface_alias_splits_what_it_folded(risk_store):
    """사람 확정 별칭(A|B → A|C)이 접은 계면 원자는 그 별칭을 revoke 하면 원장 별칭(iface_alias)이 거둬지고 등록부가 다시 갈라진다."""
    _target(risk_store, "snap:T5", "P5")
    _finding(risk_store, "snap:T5", "G1", f"{A}|{B}", panel="PN1")
    _finding(risk_store, "snap:T5", "G2", f"{A}|{C}", panel="PN2")
    risk_store.execute(
        "INSERT INTO rr_iface_alias(alias_key, canonical_a, canonical_b, owner_sub, aliases_json, source, score)"
        " VALUES (?,?,?,?,'[]','human',1.0)", (f"{A}|{B}", A, C, OWNER))
    findings = rekey.touching_findings(risk_store, OWNER, pairs=[f"{A}|{B}"])
    added = rekey.reconcile_aliases(risk_store, OWNER, findings, op="iface_alias_confirm", actor=OWNER, at=1)["added"]
    assert added == [{"old": key_of(f"{A}|{B}"), "new": key_of(f"{A}|{C}"), "reason": "iface_alias"}]
    registry.merge(risk_store, "snap:T5", owner_sub=OWNER)
    assert _registry(risk_store)[("snap:T5", key_of(f"{A}|{C}"))][2] == 2

    out = _decide(risk_store, decision="revoke_iface_alias", alias_key=f"{A}|{B}")["rekey"]
    assert out["aliases_revoked"] == [{"old": key_of(f"{A}|{B}"), "new": key_of(f"{A}|{C}"), "reason": "iface_alias"}]
    split = _registry(risk_store)
    assert split[("snap:T5", key_of(f"{A}|{B}"))] == ("open", None, 1, "중대")
    assert split[("snap:T5", key_of(f"{A}|{C}"))][2] == 1


# ---------------------------------------------------------------- 병합이 다른 대상의 닫힘 표지를 건드리지 않는다
def test_merge_does_not_reopen_a_row_another_target_closed(risk_store):
    """§4.8 이 닫은 행(superseded_by=다른 대상#키)은 그 옛 대상을 다시 병합해도 그대로다 — 종전에는 open 으로 돌아갔다(재키가 옛 대상까지
    다시 병합해 드러났다)."""
    _world(risk_store)
    risk_store.execute("UPDATE rr_registry SET status = 'superseded', superseded_by = ? WHERE target_key = 'snap:T1'"
                       " AND cluster_key = ?", (f"snap:T9#{key_of(X)}", key_of(X)))
    registry.merge(risk_store, "snap:T1", owner_sub=OWNER)
    assert _registry(risk_store)[("snap:T1", key_of(X))][:2] == ("superseded", f"snap:T9#{key_of(X)}")


# ---------------------------------------------------------------- 검토 후속(10-31) — 접힌 행의 주체 · 별칭으로만 닿는 대상 · 닫힌 행의
# 주의 등급 · 한 트랜잭션 병합 · 키 차례 · 재매핑 · 재검토 표기
def _live(store, target: str) -> dict:
    return {r["cluster_key"]: (r["support"], r["severity"]) for r in store.query(
        "SELECT cluster_key, support, severity FROM rr_registry WHERE target_key = ? AND status IN ('open', 'rejected_in_panel')",
        (target,))}


def _fresh(store, target: str) -> dict:
    """지금 별칭으로 새로 센 병합(아무것도 쓰지 않는다)."""
    return {r["cluster_key"]: (r["support"], r["severity"])
            for r in registry.merge(store, target, owner_sub=OWNER, persist=False)["rows"]}


def _assert_settled(store) -> None:
    """모든 대상을 지금 별칭으로 다시 병합해도 등록부 · 기여 · priors 가 그대로다 — 재키가 영향 대상을 빠짐없이 다시 병합했다."""
    before = (_registry(store), _contrib(store), _priors(store))
    for row in store.query("SELECT target_key FROM rr_targets ORDER BY target_key"):
        registry.merge(store, row["target_key"], owner_sub=OWNER)
    assert (_registry(store), _contrib(store), _priors(store)) == before


def test_a_folded_row_carries_the_subject_its_key_names_so_subject_recall_still_finds_it(risk_store, clock):
    """접힌 등록부 행의 주체는 그 행의 키가 가리키는 주체다 — 대표 원자(F1)가 병합으로 사라진 주체 Y 라도 접힌 key(X) 행의 주체는 X 라,
    X 로 찾는 §5.9.4 회수(`_subject_path` · precedents)가 병합 뒤에도 그 행을 찾는다. 원자가 전부 별칭으로 들어온 행(T2)은 대표 주체를
    지금 원장으로 다시 센 값이다. 종전에는 대표 원자의 동결 주체(Y)를 써 merge_key 가 X 의 회수에서 T1 을 지웠다."""
    _world(risk_store)
    # 회수하는 쪽 — 생산자 경로로 뜬 다른 과제의 diff. 그 뒤 스냅샷의 한 파트가 X 와 같은 파트라고 원장에서 확정해 둔다(노드가 X 로 풀린다).
    project_id = factories.make_project(risk_store, code="P-RECALL")
    adapter_results = factories.fixture_adapter_results()
    first = factories.make_snapshot(risk_store, project_id, adapter_results, label="DV1")
    second = factories.make_snapshot(risk_store, project_id, adapter_results, label="DV2",
                                     captured_at=factories.CAPTURED_AT + 86400)
    diff_id = factories.make_diff(risk_store, first["snapshot_id"], second["snapshot_id"])["diff_id"]
    part = risk_store.query_one("SELECT ckey FROM rr_ir_nodes WHERE snapshot_id = ? AND ckey LIKE 'ck:%' ORDER BY nid",
                                (second["snapshot_id"],))["ckey"]
    _decide(risk_store, decision="merge_key", ckey_from=part, ckey_into=X)
    visible = brief._member_project_ids(risk_store, OWNER)

    def recalled() -> list[str]:
        return sorted(p for hit in brief._subject_path(risk_store, second["snapshot_id"], OWNER, visible)
                      for p in hit["project_ids"])

    def precedents() -> list[str]:
        return sorted(c["reg_ref"] for c in brief.precedents(risk_store, diff_id, owner_sub=OWNER)["clusters"])

    assert recalled() == ["P1"] and precedents() == [f"reg:snap:T1#{key_of(X)}"]
    _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)
    open_subjects = {(r["target_key"], r["cluster_key"]): r["subject_key"] for r in risk_store.query(
        "SELECT target_key, cluster_key, subject_key FROM rr_registry WHERE status = 'open'")}
    assert open_subjects == {("snap:T1", key_of(X)): X, ("snap:T2", key_of(X)): X}
    assert recalled() == ["P1", "P2"]
    assert precedents() == [f"reg:snap:T1#{key_of(X)}", f"reg:snap:T2#{key_of(X)}"]
    clock["t"] = 2000
    _decide(risk_store, decision="unmerge_key", ckey=Y)                 # 되돌리면 각자 제 주체로 돌아간다
    assert recalled() == ["P1"] and precedents() == [f"reg:snap:T1#{key_of(X)}"]


def test_a_target_reached_only_through_a_human_alias_is_remerged_both_ways(risk_store, clock):
    """사람 별칭(key(Q) → key(Y))으로만 Y 의 클러스터에 닿는 대상(TQ)도 다시 병합된다 — Y 가 X 에 접히면 TQ 의 Q · X 원자가 한 행이 되고
    (지금 별칭으로 새로 센 병합과 같다) priors 가 그 접힘을 곧바로 센다. 되돌리면 TQ 도 다시 갈라진다. 종전에는 주체로 닿는 대상(T1 ·
    T2)만 다시 병합해 TQ 의 등록부 · priors 가 다음 병합까지 옛 별칭대로 남았다."""
    _world(risk_store)
    _part(risk_store, Q)
    _target(risk_store, "snap:TQ", "PQ")
    _finding(risk_store, "snap:TQ", "G1", Q, panel="PQ1", severity="중대")
    _finding(risk_store, "snap:TQ", "G2", X, panel="PQ1", severity="치명")
    registry.add_cluster_alias(risk_store, key_of(Q), key_of(Y), owner_sub=OWNER, reason="cluster_merge")
    registry.merge(risk_store, "snap:TQ", owner_sub=OWNER)
    assert _live(risk_store, "snap:TQ") == {key_of(X): (1, "치명"), key_of(Y): (1, "중대")}
    # 패턴 · 큐도 같은 키 집합으로 본다 — key(Q) 의 패턴과 key(Q) 를 낀 병합 제안.
    for pid, norm in (("pat-q", key_of(Q)), ("pat-x", key_of(X))):
        risk_store.execute("INSERT INTO rr_patterns(id, owner_sub, cluster_key_norm, status, created_at, updated_at)"
                           " VALUES (?,?,?,'candidate',1,1)", (pid, OWNER, norm))
    risk_store.execute("INSERT INTO rr_curation_queue(id, owner_sub, kind, payload_json, status, created_at)"
                       " VALUES ('q-q',?,'cluster_merge',?,'open',1)",
                       (OWNER, common.canonical_json({"a": key_of(Q), "b": key_of(W)})))

    def pattern_q():
        return risk_store.query_one("SELECT merged_into FROM rr_patterns WHERE id = 'pat-q'")["merged_into"]

    out = _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)["rekey"]
    assert out["targets"] == ["snap:T1", "snap:T2", "snap:TQ"]
    assert _live(risk_store, "snap:TQ") == _fresh(risk_store, "snap:TQ") == {key_of(X): (1, "치명")}
    assert risk_store.query_one("SELECT subject_key FROM rr_registry WHERE target_key = 'snap:TQ' AND cluster_key = ?",
                                (key_of(X),))["subject_key"] == X       # 동결 키가 key(X) 인 원자(G2)의 주체
    assert registry.verdict_candidate(risk_store, "snap:TQ")["counts"]["clusters"] == 1
    _assert_settled(risk_store)
    audit = json.loads(_audits(risk_store)[-1]["after_json"])
    assert (audit["new_cluster_keys"][key_of(Q)], audit["targets_n"]) == (key_of(X), 3)
    assert pattern_q() == "pat-x" and out["queue_closed"] == ["q-q"]

    clock["t"] = 2000
    out = _decide(risk_store, decision="unmerge_key", ckey=Y)["rekey"]
    assert out["targets"] == ["snap:T1", "snap:T2", "snap:TQ"]
    assert _live(risk_store, "snap:TQ") == _fresh(risk_store, "snap:TQ") == {key_of(X): (1, "치명"), key_of(Y): (1, "중대")}
    _assert_settled(risk_store)
    assert pattern_q() is None


def test_a_merge_that_pushes_an_upstream_human_chain_past_five_hops_is_409(risk_store):
    """세울 때의 홉 점검은 새 별칭 뒤만 센다 — 사람 별칭 key(Q) → key(Y) 위에 Y → X(뒤로 사람 별칭 4홉)를 세우면 Q 의 사슬이
    Q → Y → X → 4홉 = 6홉이다. 맞춘 뒤 바뀐 키의 앞 키까지 보아 409 이고 원장 병합 · 별칭 · 등록부 · 감사가 하나도 남지 않는다."""
    _world(risk_store)
    registry.add_cluster_alias(risk_store, key_of(Q), key_of(Y), owner_sub=OWNER, reason="cluster_merge")
    _human_chain(risk_store, key_of(X), 4)
    registry_before = _registry(risk_store)
    with pytest.raises(AppError) as err:
        _decide(risk_store, decision="merge_key", ckey_from=Y, ckey_into=X)
    assert (err.value.code, err.value.http_status) == ("alias_chain_too_long", 409)
    assert risk_store.query_one("SELECT status FROM rr_part_keys WHERE ckey = ?", (Y,))["status"] == "confirmed"
    assert _alias(risk_store, key_of(Y)) is None and _audits(risk_store) == [] and _registry(risk_store) == registry_before


@pytest.mark.parametrize("middle,leaf", [(Y, Z), (Z, Y)], ids=["leaf-key-sorts-first", "middle-key-sorts-first"])
def test_an_unmerge_does_not_depend_on_which_key_sorts_first(risk_store, clock, middle, leaf):
    """되돌리기는 거둘 원장 별칭을 먼저 다 거두고 새 별칭을 세운다 — 세울 때의 홉 점검이 곧 거둘 별칭(key(middle) → key(X))을 세지
    않는다. 종전에는 키마다 거두고 세워, 같은 모양(뒤로 사람 별칭 4홉인 X 에 middle · leaf 를 차례로 병합한 뒤 middle 을 풀기)이 키 해시
    차례에 따라 409 가 됐다(key(leaf) 가 먼저면)."""
    assert key_of(Z) < key_of(Y)                                         # 두 매개가 서로 다른 처리 차례를 덮는다
    for ck in (X, Y, Z):
        _part(risk_store, ck)
    _target(risk_store, "snap:T1", "P1")
    _finding(risk_store, "snap:T1", "FM", middle, panel="PN1")
    _finding(risk_store, "snap:T1", "FL", leaf, panel="PN2")
    _finding(risk_store, "snap:T1", "FX", X, panel="PN3")
    registry.merge(risk_store, "snap:T1", owner_sub=OWNER)
    _human_chain(risk_store, key_of(X), 4)
    _decide(risk_store, decision="merge_key", ckey_from=middle, ckey_into=X)
    _decide(risk_store, decision="merge_key", ckey_from=leaf, ckey_into=middle)

    clock["t"] = 2000
    out = _decide(risk_store, decision="unmerge_key", ckey=middle)["rekey"]
    assert out["aliases_added"] == [{"old": key_of(leaf), "new": key_of(middle), "reason": "ckey_merge"}]
    assert sorted(a["old"] for a in out["aliases_revoked"]) == sorted([key_of(leaf), key_of(middle)])
    assert (registry._alias_hops(risk_store, key_of(leaf), OWNER), registry._alias_hops(risk_store, key_of(middle), OWNER)) == (1, 0)
    assert _live(risk_store, "snap:T1") == _fresh(risk_store, "snap:T1")


