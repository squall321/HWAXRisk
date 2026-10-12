# 심사 방식 고르기(D-24 · 재설계 M2 U6) — 바꾸기·얹기·문지기(Tier 잡·C3 자동 후속·브리프 토큰)·Claude 입구·길잡이를 실제 생산자로 본다
"""두 방식(panels — 영역을 섞은 패널 3라운드 · cells — 전문가별 카드 대조)이 한 원장에 같이 산다. 아직 아무것도 안 돈 대상은
양쪽으로 바꾸고, 패널을 돌린 대상에는 카드 대조를 얹으며(파일럿 길), cells 대상에서는 Tier 패널 잡과 L2 보충 회차(브리프 토큰)를
막는다. 문지기는 라우트가 아니라 runner.create_job 에 있어 사용자 잡과 C3 자동 후속이 같이 막힌다.
대상·잡·패널은 공장(make_diff_target · portal_panel_body)과 라우트·러너가 만든 것이다. 검토 잡(rr_jobs.mode='reviews')이 있어야
보이는 규칙(cells → panels 의 review_ran)은 그 잡의 생산자(C2b create_review_job)가 생기면 붉어지는 자리표시로 둔다.
"""
from __future__ import annotations

import asyncio
import dataclasses
import importlib
import json

import pytest

import app.mcp_server as srv
from app import config, entry, identity, routes, runner, units
from app.common import now_epoch
from app.errors import AppError
from tests import factories

OWNER = factories.OWNER
VIEWER = "viewer@example.com"
OTHER = "other@example.com"


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, data_dir=tmp_path,
                                                               risk_review_enabled=True))
    return risk_store


def _open(store, kind: str, ref_id: str, flow: str = "panels") -> dict:
    return routes.create_target(routes.TargetBody(kind=kind, ref_id=ref_id, consent=True, flow=flow,
                                                  agents=factories.agents()), ident=factories.ident(OWNER))


def _switch(target_key: str, to: str, *, who: str = OWNER, reason: str | None = "비교") -> dict:
    return routes.post_target_flow(target_key, routes.FlowBody(to=to, reason=reason), ident=factories.ident(who))


def _refused(fn, *args, **kwargs) -> AppError:
    with pytest.raises(AppError) as exc:
        fn(*args, **kwargs)
    return exc.value


def _flow(store, target_key: str) -> str:
    return store.query_one("SELECT flow FROM rr_targets WHERE target_key = ?", (target_key,))["flow"]


def _audits(store, target_key: str) -> list[dict]:
    rows = store.query("SELECT actor, channel, scope, action, before_json, after_json, reason FROM rr_audit"
                       " WHERE subject_id = ? AND action = 'target.flow' ORDER BY at, rowid", (target_key,))
    return [{**dict(r), "before": json.loads(r["before_json"]), "after": json.loads(r["after_json"])} for r in rows]


def _register_pat(store, email: str = OWNER) -> None:
    """웹 설정 화면이 남기는 것과 같은 자격 행(Fernet 암호문) — 러너 자격이 있어야 잡이 선다."""
    store.upsert_credential(email, identity.encrypt_pat(f"pat-{email}").decode("ascii"), "sub", email, "[]",
                            now_epoch() + 30 * 86400)


def _ledger(store, target_key: str) -> dict:
    """패널 방식이 남긴 원장 — 얹기가 건드리면 안 되는 행 전부."""
    out = {}
    for table in ("rr_panels", "rr_seat_opinions", "rr_registry", "rr_coverage", "rr_findings", "rr_claim_refs"):
        cols = [r["name"] for r in store.query(f"PRAGMA table_info({table})")]
        out[table] = [tuple(r) for r in store.query(
            f"SELECT {', '.join(cols)} FROM {table} WHERE target_key = ? ORDER BY 1, 2", (target_key,))]
    return out


# ---------------------------------------------------------------- 바꾸기 규칙
def test_a_target_nothing_ran_on_switches_both_ways_and_each_switch_is_audited(store):
    """아직 아무것도 안 돈 대상은 panels ⇄ cells 로 바꾼다. cells 로 바꾸면 그 자리에서 단위를 세우고, 바꿀 때마다 감사 한 행
    (scope target · action target.flow · 입구 · 앞뒤 방식 · 사유)이다. 같은 방식으로의 요청은 아무것도 쓰지 않는다."""
    synth = factories.make_diff_target(store, 40)
    key = synth.target_key
    assert _flow(store, key) == "panels" and units.active_build(store, key) is None

    out = _switch(key, "cells")
    assert {k: out[k] for k in ("target_key", "flow", "changed")} == {"target_key": key, "flow": "cells", "changed": True}
    assert out["units"]["status"] == "ok" and _flow(store, key) == "cells"
    assert units.active_build(store, key)["reason"] == "비교"
    assert _switch(key, "cells") == {"target_key": key, "flow": "cells", "changed": False}
    back = _switch(key, "panels", reason=None)
    assert back == {"target_key": key, "flow": "panels", "changed": True} and _flow(store, key) == "panels"
    assert _audits(store, key) == [
        {"actor": OWNER, "channel": "rest", "scope": "target", "action": "target.flow", "before_json": '{"flow":"panels"}',
         "after_json": '{"flow":"cells"}', "reason": "비교", "before": {"flow": "panels"}, "after": {"flow": "cells"}},
        {"actor": OWNER, "channel": "rest", "scope": "target", "action": "target.flow", "before_json": '{"flow":"cells"}',
         "after_json": '{"flow":"panels"}', "reason": None, "before": {"flow": "cells"}, "after": {"flow": "panels"}}]
    # 다시 cells 로 — 활성 빌드가 있으니 다시 세우지 않는다.
    assert _switch(key, "cells")["units"]["rev"] == 1


def test_the_switch_is_refused_while_a_job_lives_off_a_switched_box_and_for_unbuildable_units(store):
    """panels → cells 는 살아 있는 잡이 있으면 409 flow_locked(job_live), 스위치가 꺼진 박스면 409 review_disabled, 단위가 안 서면
    409 units_unbuildable(빌드 상태와 까닭)이다. 막히면 방식은 그대로다."""
    _register_pat(store)
    synth = factories.make_diff_target(store, 3)
    job = routes.create_job(synth.target_key, routes.JobBody(tier="A"), ident=factories.ident(OWNER))
    refused = _refused(_switch, synth.target_key, "cells")
    assert (refused.code, refused.http_status, refused.detail["reason"]) == ("flow_locked", 409, "job_live")
    assert [j["id"] for j in refused.detail["jobs"]] == [job["job_id"]]
    runner.cancel_job(store, job["job_id"], by=OWNER)
    config.settings = dataclasses.replace(config.settings, risk_review_enabled=False)
    assert _refused(_switch, synth.target_key, "cells").code == "review_disabled"
    config.settings = dataclasses.replace(config.settings, risk_review_enabled=True)
    assert _switch(synth.target_key, "cells")["changed"] is True        # 잡이 끝난 뒤에는 얹을 수 있다

    snap = _open(store, "snap", synth.target_snapshot_id)["target_key"]
    refused = _refused(_switch, snap, "cells")
    assert (refused.code, refused.http_status) == ("units_unbuildable", 409)
    assert refused.detail["units"] == {"rev": 1, "status": "failed", "error": "snap_not_supported"}
    assert _flow(store, snap) == "panels" and _audits(store, snap) == []


def test_only_editors_switch_the_flow(store):
    """방식 바꾸기는 잡을 세울 수 있는 사람(editor 이상)이다 — 과제 밖 사람은 404(존재를 숨긴다), viewer 는 403 이다."""
    synth = factories.make_diff_target(store, 3)
    routes.put_members(synth.project_id, routes.MembersBody(members=[routes.MemberItem(email=VIEWER, role="viewer")]),
                       ident=factories.ident(OWNER))
    assert _refused(_switch, synth.target_key, "cells", who=OTHER).http_status == 404
    refused = _refused(_switch, synth.target_key, "cells", who=VIEWER)
    assert (refused.code, refused.http_status) == ("role_insufficient", 403)
    assert _flow(store, synth.target_key) == "panels"


def test_card_review_lays_over_a_target_whose_panels_already_ran(store, tmp_path):
    """패널을 돌린 대상에 카드 대조를 얹는다(D-24 '비교' — 파일럿 길) — 잡이 끝나면 cells 로 바꿀 수 있고, 이미 돈 패널·의견·
    좌석·등록부·finding 행은 한 칸도 바뀌지 않는다. 패널은 러너가 실모듈로 돌린 것이다(포털·에이전트 서버만 대역)."""
    ran = factories.portal_panel_body(store, tmp_path)
    key = ran.target.target_key
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_panels WHERE target_key = ? AND status = 'done'",
                           (key,))["n"] == 1
    job_id = store.query_one("SELECT id FROM rr_jobs WHERE target_key = ?", (key,))["id"]
    assert _refused(_switch, key, "cells").detail["reason"] == "job_live"
    runner.cancel_job(store, job_id, by=OWNER)
    runner.claim_next_job(store, dataclasses.replace(config.settings, data_dir=tmp_path))   # cancelling → cancelled
    before = _ledger(store, key)
    assert before["rr_panels"] and before["rr_seat_opinions"]
    assert _switch(key, "cells")["flow"] == "cells"
    assert _ledger(store, key) == before


# ---------------------------------------------------------------- 문지기 — Tier 잡과 C3 자동 후속
def test_tier_jobs_are_refused_on_a_cells_target_through_every_entry(store, monkeypatch):
    """cells 대상의 Tier A·B·C 패널 잡은 422 flow_mismatch — 러너 함수·REST·Claude 입구 어디로 와도 같은 문을 지나고 잡 행이
    서지 않는다."""
    _register_pat(store)
    synth = factories.make_diff_target(store, 40, open_target=False)
    key = _open(store, "diff", synth.diff_id, "cells")["target_key"]
    for tier in ("A", "B", "C"):
        refused = _refused(runner.create_job, store, key, tier, owner_sub=OWNER, consent=True, settings=config.settings)
        assert (refused.code, refused.http_status, refused.detail) == ("flow_mismatch", 422, {"flow": "cells", "tier": tier})
    assert _refused(routes.create_job, key, routes.JobBody(tier="B"), ident=factories.ident(OWNER)).code == "flow_mismatch"
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: factories.TEST_GATEWAY_SECRET)
    factories.act_as_delegate(monkeypatch, OWNER)
    assert asyncio.run(srv.risk_start_job(target_key=key, tier="A"))["error"] == "flow_mismatch"
    assert store.query("SELECT id FROM rr_jobs") == []


def test_the_c3_follow_up_is_refused_on_a_cells_target_and_says_why(store):
    """닫힘 레벨 C3 의 Tier B 뒤 자동 Tier C 도 create_job 의 문을 지난다 — cells 로 바뀐 대상에서는 세우지 않고, 끝난 잡은
    completed 그대로 두며 까닭을 그 잡에 적는다. 패널 대상에서는 종전대로 Tier C 가 선다(_finish_job 을 실제로 돌린다)."""
    _register_pat(store)
    config.settings = dataclasses.replace(config.settings, risk_default_close_level="C3")
    cells = factories.make_diff_target(store, 3)
    panels = factories.make_diff_target(store, 3)
    jobs = {}
    for synth in (cells, panels):
        made = routes.create_job(synth.target_key, routes.JobBody(tier="B"), ident=factories.ident(OWNER))
        runner.cancel_job(store, made["job_id"], by=OWNER)
        row = dict(store.query_one("SELECT id, target_key, owner_sub, tier, params_json FROM rr_jobs WHERE id = ?",
                                   (made["job_id"],)))
        jobs[synth.target_key] = {**row, "params": json.loads(row.pop("params_json"))}
    _switch(cells.target_key, "cells")

    refused = runner._finish_job(store, jobs[cells.target_key], config.settings)
    assert refused == {"job_state": "completed", "next_job": None, "next_job_refused": "flow_mismatch"}
    row = store.query_one("SELECT state, error FROM rr_jobs WHERE id = ?", (jobs[cells.target_key]["id"],))
    assert row["state"] == "completed" and row["error"].startswith("flow_mismatch: C3 자동 후속 Tier C 를 세우지 않았다")
    assert store.query("SELECT id FROM rr_jobs WHERE target_key = ? AND tier = 'C'", (cells.target_key,)) == []

    followed = runner._finish_job(store, jobs[panels.target_key], config.settings)
    assert followed["next_job"] and "next_job_refused" not in followed
    assert store.query_one("SELECT tier FROM rr_jobs WHERE id = ?", (followed["next_job"],))["tier"] == "C"


# ---------------------------------------------------------------- 문지기 — 브리프 토큰(L2 보충 회차)
def test_panel_briefs_and_their_tokens_are_refused_on_cells_targets(store, monkeypatch):
    """cells 대상에는 패널 브리프를 내지 않는다(422 cells_flow_web_only) — 토큰을 발급하지 않고 planned 패널도 만들지 않는다.
    방식이 바뀌기 전에 받아 둔 토큰도 cells 가 된 뒤에는 열리지 않고 그 패널은 동결되지 않는다. panels 대상은 종전대로 연다."""
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: factories.TEST_GATEWAY_SECRET)
    synth = factories.make_diff_target(store, 3, open_target=False)
    cells = _open(store, "diff", synth.diff_id, "cells")["target_key"]
    refused = _refused(routes.get_brief, cells, "B", ident=factories.ident(OWNER))
    assert (refused.code, refused.http_status) == ("cells_flow_web_only", 422)
    assert store.query("SELECT id FROM rr_panels WHERE target_key = ?", (cells,)) == []

    panels = factories.make_diff_target(store, 3).target_key
    brief = routes.get_brief(panels, "B", ident=factories.ident(OWNER))
    token = brief["panels"][0]["brief_token"]
    _switch(panels, "cells")
    factories.act_as_delegate(monkeypatch, OWNER)
    assert srv.risk_get_brief(panels, token)["error"] == "cells_flow_web_only"
    row = store.query_one("SELECT status, brief_gz FROM rr_panels WHERE id = ?", (brief["panels"][0]["panel_id"],))
    assert row["status"] == "planned" and row["brief_gz"] is None
    _switch(panels, "panels")
    assert "error" not in srv.risk_get_brief(panels, token)


# ---------------------------------------------------------------- Claude 입구 — risk_open_target(flow=…)
def test_claude_opens_a_target_in_either_flow_and_switches_an_open_one(store, monkeypatch):
    """새 대상은 flow 로 열고(없으면 panels), 이미 연 내 대상에 다른 flow 를 주면 웹과 같은 바꾸기 함수를 지난다(감사 channel
    mcp · 사유). flow 를 안 주면 방식을 건드리지 않는다. 쓰기는 위임 신원만이다."""
    monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: factories.TEST_GATEWAY_SECRET)

    def call(**kwargs) -> dict:
        return asyncio.run(srv.risk_open_target(**kwargs))

    assert call(kind="diff", ref_id="d-none", consent=True, flow="cells")["error"] == "delegation_required"
    factories.act_as_delegate(monkeypatch, OWNER)
    fresh = factories.make_diff_target(store, 3, open_target=False)
    opened = call(kind="diff", ref_id=fresh.diff_id, consent=True, flow="cells")
    assert opened["created"] is True and opened["flow"] == "cells" and opened["units"]["status"] == "ok"
    assert call(kind="diff", ref_id=fresh.diff_id, consent=True, flow="nope")["error"] == "E100"

    synth = factories.make_diff_target(store, 3)
    same = call(kind="diff", ref_id=synth.diff_id, consent=True)
    assert same["created"] is False and same["flow"] == "panels" and "flow_change" not in same
    switched = call(kind="diff", ref_id=synth.diff_id, consent=True, flow="cells", reason="파일럿")
    assert switched["flow"] == "cells" and switched["flow_change"]["changed"] is True
    assert [(a["channel"], a["reason"], a["after"]) for a in _audits(store, synth.target_key)] == [
        ("mcp", "파일럿", {"flow": "cells"})]
    assert call(kind="diff", ref_id=synth.diff_id, consent=True)["flow"] == "cells"


# ---------------------------------------------------------------- 길잡이 — 두 방식을 나란히
def _project_with_a_diff(store) -> factories.SynthTarget:
    synth = factories.make_diff_target(store, 3, open_target=False)
    routes.add_source(synth.project_id, routes.SourceBody(kind="mcad", ref={"stepforge_project_id": "sf-1"}),
                      ident=factories.ident(OWNER))
    return synth


def test_the_guide_shows_both_flows_before_a_target_opens_and_the_cells_branch_after(store):
    """대상을 열기 전 단계는 risk_open_target 두 걸음(패널 — 인자는 종전 그대로 · 카드 대조 — flow='cells')을 나란히 준다.
    꺼진 박스는 카드 대조 걸음 대신 켜는 자리를 notes 에 적는다. cells 대상이 열리면 Tier 잡 걸음을 주지 않고 단위를 읽게 한다."""
    synth = _project_with_a_diff(store)
    ident = factories.ident(OWNER)
    out = entry.next_step(ident, project_id=synth.project_id)
    assert out["where"] == "target"
    assert [(s["tool"], s["args"]) for s in out["next"]] == [
        ("risk_open_target", {"kind": "diff", "ref_id": synth.diff_id}),
        ("risk_open_target", {"kind": "diff", "ref_id": synth.diff_id, "flow": "cells"})]
    assert all("consent=true" in s["why"] and "consent" not in s["args"] for s in out["next"])
    assert entry.REVIEW_OFF_NOTE not in out["notes"]

    config.settings = dataclasses.replace(config.settings, risk_review_enabled=False)
    off = entry.next_step(ident, project_id=synth.project_id)
    assert [s["args"] for s in off["next"]] == [{"kind": "diff", "ref_id": synth.diff_id}]
    assert entry.REVIEW_OFF_NOTE in off["notes"] and "knobs.env" in entry.REVIEW_OFF_NOTE
    config.settings = dataclasses.replace(config.settings, risk_review_enabled=True)

    key = _open(store, "diff", synth.diff_id, "cells")["target_key"]
    opened = entry.next_step(ident, project_id=synth.project_id)
    assert opened["where"] == "review" and opened["facts"]["target"]["flow"] == "cells"
    assert opened["facts"]["units"]["status"] == "ok"
    assert [s["tool"] for s in opened["next"]] == ["risk_get_units", "risk_get_coverage", "risk_next_step"]
    assert not any(s["tool"] == "risk_start_job" for s in opened["next"])
    assert not [b for b in opened["blocked"] if b["code"] == "units_unbuildable"]
    assert opened["next"][0]["args"] == {"target_key": key} and opened["next"][0]["write"] is False


# ---------------------------------------------------------------- 패널 경로는 패널 잡만 본다(재설계 M2 S6)
def test_panel_job_transitions_leave_the_hold_columns_alone(store):
    """패널 잡의 정지·재개·취소는 종전 그대로다 — 검토 잡의 보류 열(hold_code·hold_until·hold_n)을 건드리지 않고, mode 는 NULL
    (v4 전 행과 같은 '패널') 그대로다. 진행판의 job 칸·과제 화면의 잡 목록은 그 잡을 패널 잡으로 보인다."""
    _register_pat(store)
    synth = factories.make_diff_target(store, 3)
    job_id = routes.create_job(synth.target_key, routes.JobBody(tier="A"), ident=factories.ident(OWNER))["job_id"]

    def row() -> dict:
        return dict(store.query_one("SELECT state, pause_reason, mode, hold_code, hold_until, hold_n FROM rr_jobs"
                                    " WHERE id = ?", (job_id,)))

    assert row() == {"state": "queued", "pause_reason": None, "mode": None, "hold_code": None, "hold_until": None,
                     "hold_n": 0}
    paused = runner.pause_job(store, job_id, by=OWNER)
    assert "hold_code" not in paused and row()["state"] == "paused" and row()["pause_reason"] == "user"
    assert _refused(runner.pause_job, store, job_id, by=OWNER).http_status == 409
    runner.resume_job(store, job_id, by=OWNER)
    runner.cancel_job(store, job_id, by=OWNER)
    assert row() == {"state": "cancelled", "pause_reason": None, "mode": None, "hold_code": None, "hold_until": None,
                     "hold_n": 0}
    assert routes.coverage_payload(synth.target_key, owner_sub=OWNER)["job"]["id"] == job_id
    page = routes.get_project(synth.project_id, ident=factories.ident(OWNER))
    assert [(j["id"], j["mode"], j["kind"]) for j in page["jobs"]] == [(job_id, "panels", "panel_batch")]


# ---------------------------------------------------------------- 검토 잡이 있어야 보이는 규칙(C2b 의 생산자 자리표시)
class C2bProducerMissing(Exception):
    """검토 잡의 생산자(review_runner.create_review_job, m2-wp3b S5)가 아직 없다 — 자리표시의 기대한 실패는 이것 하나다."""


def _create_review_job(store, target_key: str, *, user_memo: str | None = None) -> str:
    try:
        review_runner = importlib.import_module("app.review_runner")
    except ModuleNotFoundError as exc:
        raise C2bProducerMissing("app.review_runner") from exc
    if not hasattr(review_runner, "create_review_job"):
        raise C2bProducerMissing("app.review_runner.create_review_job")
    _register_pat(store)
    # 범위는 ECAD 에 기대지 않는 영역 하나다 — M2 는 입력 결손(ECAD 부재) 전문가를 범위에 받지 않는다(422 input_gap_m3).
    out = review_runner.create_review_job(store, target_key, owner_sub=OWNER, requester_sub=OWNER,
                                          scope={"domains": ["mech"]}, user_memo=user_memo, consent=True,
                                          consent_source="web", settings=config.settings)
    return out["job_id"]


# 검토 잡 자리표시의 로스터 — ECAD 에 기대는 영역이 없다(합성 쌍에는 회로 소스가 없다).
NO_ECAD = factories.agents(("mech", "sim", "xd"), 2)
C2B_REVIEW_JOBS = pytest.mark.xfail(strict=True, raises=C2bProducerMissing,
                                    reason="C2b producer — review_runner.create_review_job(m2-wp3b S5)이 생기면 표식을 지운다")


@C2B_REVIEW_JOBS
def test_a_target_a_review_job_ever_stood_on_does_not_go_back_to_panels_or_rebuild(store):
    """cells → panels 는 검토 잡이 한 번도 없을 때만이다(409 flow_locked·review_ran, 잡을 취소해도 그대로). 검토 잡이 선 대상의
    다른 입력 재빌드는 409 units_in_use 다(M2.md 5절 #6) — 같은 입력은 그대로 no-op 이다."""
    synth = factories.make_diff_target(store, 40, open_target=False)
    key = routes.create_target(routes.TargetBody(kind="diff", ref_id=synth.diff_id, consent=True, flow="cells",
                                                 agents=NO_ECAD), ident=factories.ident(OWNER))["target_key"]
    job_id = _create_review_job(store, key)
    refused = _refused(_switch, key, "panels")
    assert (refused.code, refused.detail["reason"]) == ("flow_locked", "review_ran")
    runner.cancel_job(store, job_id, by=OWNER)
    assert _refused(_switch, key, "panels").detail["reason"] == "review_ran"
    assert _flow(store, key) == "cells"
    assert units.build_units(store, key, built_by=OWNER)["changed"] is False
    config.settings = dataclasses.replace(config.settings, risk_unit_max_lines=12, risk_unit_target_lines=8,
                                          risk_units_small_lines=4)
    assert _refused(units.build_units, store, key, built_by=OWNER).code == "units_in_use"
    assert _refused(routes.post_units, key, routes.UnitsBody(), ident=factories.ident(OWNER)).http_status == 409



@C2B_REVIEW_JOBS
def test_the_panel_path_never_picks_recovers_or_shows_a_review_job(store):
    """한 rr_jobs 표에 두 종류가 산다 — 패널 러너는 검토 잡을 집지 않고(claim_next_job) 재기동 복구도 건드리지 않으며, 진행판의
    job·패널 브리프의 최근 메모는 패널 잡의 것이다. 살아 있는 검토 잡이 있는 대상에는 패널 잡을 세우지 않는다(409
    review_job_running). 과제 화면의 잡 목록은 거르지 않고 방식을 싣는다."""
    from app import brief

    _register_pat(store)
    synth = factories.make_diff_target(store, 40, agents=NO_ECAD)
    key = synth.target_key
    panel_id = routes.create_job(key, routes.JobBody(tier="A", user_memo="패널 메모"), ident=factories.ident(OWNER))["job_id"]
    runner.cancel_job(store, panel_id, by=OWNER)
    routes.post_units(key, routes.UnitsBody(), ident=factories.ident(OWNER))
    review_id = _create_review_job(store, key, user_memo="검토 메모")

    def state(job_id: str) -> str:
        return store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"]

    assert runner.claim_next_job(store, config.settings) is None and state(review_id) == "queued"
    runner._set_job(store, review_id, "running")
    assert runner.recover_running_panels(store) == {"recovered": 0, "paused": 0} and state(review_id) == "running"
    assert routes.coverage_payload(key, owner_sub=OWNER)["job"]["id"] == panel_id
    memo = brief._item_memo(store, key)["result"]
    assert "패널 메모" in memo and "검토 메모" not in memo
    refused = _refused(routes.create_job, key, routes.JobBody(tier="B"), ident=factories.ident(OWNER))
    assert (refused.code, refused.http_status, refused.detail["job_id"]) == ("review_job_running", 409, review_id)
    page = routes.get_project(synth.project_id, ident=factories.ident(OWNER))
    assert {(j["id"], j["mode"]) for j in page["jobs"]} == {(panel_id, "panels"), (review_id, "reviews")}


@C2B_REVIEW_JOBS
def test_a_person_pausing_a_review_job_holds_it_and_resume_or_cancel_clears_the_hold(store):
    """사람의 정지는 검토 잡의 보류를 hold_code='user'·hold_until=NULL 로 덮는다(자동 재개가 다시 줄에 세우지 않는다). 재개·취소는
    보류 열 셋을 비운다(P-10 · X4-25)."""
    synth = factories.make_diff_target(store, 40, agents=NO_ECAD)
    routes.post_units(synth.target_key, routes.UnitsBody(), ident=factories.ident(OWNER))
    review_id = _create_review_job(store, synth.target_key)

    def hold() -> tuple:
        row = store.query_one("SELECT state, pause_reason, hold_code, hold_until, hold_n FROM rr_jobs WHERE id = ?",
                              (review_id,))
        return tuple(row)

    paused = runner.pause_job(store, review_id, by=OWNER)
    assert (paused["state"], paused["hold_code"], paused["hold_until"]) == ("paused", "user", None)
    assert hold() == ("paused", "user", "user", None, 0)
    assert _refused(runner.pause_job, store, review_id, by=OWNER).http_status == 409
    runner.resume_job(store, review_id, by=OWNER)
    assert hold() == ("queued", None, None, None, 0)
    runner.pause_job(store, review_id, by=OWNER)
    runner.cancel_job(store, review_id, by=OWNER)
    assert hold() == ("cancelled", None, None, None, 0)


@C2B_REVIEW_JOBS
def test_purging_a_project_cancels_its_review_jobs_and_clears_the_hold(store):
    """과제 폐기의 일괄 취소도 사람의 취소처럼 검토 잡의 보류 열 셋을 비운다(RC-8) — 취소된 잡에 보류 코드·재개 시각이 남으면
    자동 재개나 진행판이 '보류 중' 으로 읽는다."""
    synth = factories.make_diff_target(store, 40, agents=NO_ECAD)
    routes.post_units(synth.target_key, routes.UnitsBody(), ident=factories.ident(OWNER))
    review_id = _create_review_job(store, synth.target_key)
    runner.pause_job(store, review_id, by=OWNER)
    code = store.query_one("SELECT code FROM rr_projects WHERE id = ?", (synth.project_id,))["code"]
    routes.purge_project(synth.project_id, routes.PurgeBody(code=code, reason="정리"), ident=factories.ident(OWNER))
    row = store.query_one("SELECT state, hold_code, hold_until, hold_n FROM rr_jobs WHERE id = ?", (review_id,))
    assert tuple(row) == ("cancelled", None, None, 0)
