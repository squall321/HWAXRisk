# 카드 대조 검토 MCP(재설계 M2 S12) — risk_get_cells·risk_get_expert_report 가 REST 와 같은 함수를 와이어 25,000자 안에서 나눠 주고, risk_start_job(mode='reviews') 는 위임 신원만 받으며, risk_next_step 의 카드 대조 갈래가 검토 순서·검토 잡 걸음·보류의 고칠 곳을 준다
"""원장은 생산자가 쓴다 — 대상·단위는 합성 쌍 → 실제 캡처·diff → 단위 빌드, 검토 잡은 REST·MCP 입구, 셀·판정·보고서는 가짜 엔진을 꽂은
검토 루프(S8)와 마감(S9·S10)이다(tests/synth/review_rig.py). 보류는 루프의 `hold`(러너가 거는 것과 같은 함수)로 건다.
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import threading

import pytest
from starlette.requests import Request

import app.mcp_server as srv
from app import config, entry, expert_report, identity, review_quality, review_runner, routes, runner
from tests import factories
from tests.synth import fake_review_engine as fre
from tests.synth import review_rig as rig
from tests.synth.fake_review_engine import FakeReviewEngine
from tests.test_review_routes import _reviewed

OWNER = rig.OWNER
SEAL = rig.SEAL
OTHER = "other@example.com"
PERSONAL_PAT = "personal-heax-pat"
START_ARGS = {"mode": "reviews", "scope": {"agents": ["<agent_key>", "…"]}}


@pytest.fixture
def store(risk_store, monkeypatch, tmp_path):
    rig.configure(monkeypatch, risk_store, tmp_path)
    monkeypatch.setattr(review_runner, "QUALITY_HOOK", review_quality.progress_hook)
    yield risk_store
    identity.reset_cache()


def _call(name: str, /, **kwargs) -> dict:
    out = getattr(srv, name)(**kwargs)
    return asyncio.run(out) if asyncio.iscoroutine(out) else out


def _as_bearer(monkeypatch, email: str) -> None:
    """앱 MCP 를 개인 heax PAT 로 직접 등록한 호출 — Bearer 가 그 사람으로 풀리지만 위임으로 확인된 신원은 아니다."""
    monkeypatch.setattr(identity, "_fetch_me", lambda token: (
        {"email": email, "role": "user", "display_name": email} if token == PERSONAL_PAT else None))
    identity.reset_cache()
    request = Request({"type": "http", "method": "POST", "path": "/mcp",
                       "headers": [(b"authorization", f"Bearer {PERSONAL_PAT}".encode())], "query_string": b""})
    monkeypatch.setattr(srv, "_request", lambda: request)


def _delegate(email: str = OWNER) -> identity.Identity:
    """게이트웨이 위임으로 확인된 신원(길잡이를 entry 로 직접 부를 때)."""
    return identity.Identity(email=email, display_name=email, role=None, organization=None, anonymous=False, source="sso",
                             delegated=True)


def _project_with_source(store, key: str) -> str:
    """길잡이가 대상 단계까지 걸어가게 소스를 붙인다(합성 대상은 소스 행 없이 스냅샷을 만든다)."""
    project_id = store.query_one("SELECT project_id FROM rr_targets WHERE target_key = ?", (key,))["project_id"]
    routes.add_source(project_id, routes.SourceBody(kind="mcad", ref={"stepforge_project_id": "sf-1"}),
                      ident=factories.ident(OWNER))
    return project_id


def _digest(store) -> str:
    """DB 전체의 지문(표마다 행 전부) — 읽기 도구가 아무것도 쓰지 않았는지 본다."""
    h = hashlib.sha256()
    for table in [r["name"] for r in store.query("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]:
        for row in store.query(f"SELECT * FROM {table} ORDER BY rowid"):
            h.update(repr(tuple(row)).encode())
    return h.hexdigest()


# ---------------------------------------------------------------- 읽기 도구 둘
def test_risk_get_cells_pages_the_grid_inside_the_wire_limit_and_matches_rest(store, monkeypatch):
    """risk_get_cells — REST 와 같은 함수(cells_payload)의 짧은 행(CELL_BRIEF_COLUMNS)을 와이어 한도 안에서 나눠 준다. next_offset 으로
    이어 받은 행을 이으면 REST 의 행을 그 칸으로 줄인 것과 같다(자르지 않는다). 남의 대상·서비스 세션에는 not_visible 이다."""
    key, job_id, _fake = _reviewed(store)
    factories.act_as_delegate(monkeypatch, OWNER)
    rest = routes.get_cells(key, ident=factories.ident(OWNER))["rows"]
    want = [{c: r[c] for c in routes.CELL_BRIEF_COLUMNS} for r in rest]
    one = _call("risk_get_cells", target_key=key)
    assert srv._wire_chars(one) <= srv.MCP_RESULT_CHARS
    monkeypatch.setattr(srv, "MCP_RESULT_CHARS", 5000)                  # 한도를 줄여 여러 번에 나눠 받게 한다
    rows, offset, calls = [], 0, 0
    while True:
        page = _call("risk_get_cells", target_key=key, offset=offset)
        calls += 1
        assert srv._wire_chars(page) <= 5000 and all(list(r) == list(routes.CELL_BRIEF_COLUMNS) for r in page["rows"])
        rows += page["rows"]
        if "next_offset" not in page:
            break
        offset = page["next_offset"]
    assert rows == want and calls > 2
    assert _call("risk_get_cells", target_key=key, agent_key=SEAL)["total"] == 5
    assert _call("risk_get_cells", target_key=key, state="reviewed")["total"] == 10
    assert _call("risk_get_cells", target_key=key, state="done")["error"] == "E100"
    factories.act_as_delegate(monkeypatch, OTHER)
    assert _call("risk_get_cells", target_key=key)["error"] == "not_visible"
    monkeypatch.setattr(srv, "_request", lambda: None)
    assert _call("risk_get_cells", target_key=key)["error"] == "not_visible"


def test_risk_get_expert_report_pages_fit_the_wire_and_join_to_the_whole_part(store, monkeypatch):
    """risk_get_expert_report — 쪽 크기를 그 보고서의 쪽 전부가 와이어 한도 안에 들게 정하고(부르는 쪽마다 같은 크기), next_page 로
    이어 받은 쪽을 이으면 그 part 의 마크다운 전체다. 한도를 줄여도 본문은 잘리지 않고 쪽만 는다."""
    key, _job_id, _fake = _reviewed(store)
    factories.act_as_delegate(monkeypatch, OWNER)
    report = expert_report.load_report(store, key, SEAL)
    for limit in (srv.MCP_RESULT_CHARS, 3000):
        monkeypatch.setattr(srv, "MCP_RESULT_CHARS", limit)
        for part in expert_report.PARTS:
            texts, page, totals = [], 1, set()
            while page:
                out = _call("risk_get_expert_report", target_key=key, agent_key=SEAL, part=part, page=page)
                assert "error" not in out, out
                fragments = sum(len(v) for v in out["page"]["blocks"].values())
                assert srv._wire_chars(out) <= limit or fragments == 1, (part, page)
                texts += [t for block in expert_report.BLOCKS for t in out["page"]["blocks"][block]]
                totals.add(out["pages_total"])
                page = out.get("next_page")
            assert len(totals) == 1                                         # 쪽 수가 부르는 쪽마다 같다
            assert "\n".join(texts) == expert_report.render_report_md(report, part=part), (limit, part)
    assert totals != {1}
    unit = report["scope"]["units"][1]["unit_id"]
    narrowed = _call("risk_get_expert_report", target_key=key, agent_key=SEAL, part="units", unit_id=unit)
    assert narrowed["unit_id"] == unit and "error" not in narrowed
    assert _call("risk_get_expert_report", target_key=key, agent_key=rig.ZERO_CARDS)["error"] == "E404"
    assert _call("risk_get_expert_report", target_key=key, agent_key=SEAL, page=999)["error"] == "E100"
    # 판 확인(R3B-13) — 첫 쪽의 version 을 주면 같은 판의 쪽이고, 그사이 판이 바뀌었으면 REST 와 같은 409 오류다.
    first = _call("risk_get_expert_report", target_key=key, agent_key=SEAL, part="full")
    again = _call("risk_get_expert_report", target_key=key, agent_key=SEAL, part="full", page=2, version=first["version"])
    assert "error" not in again and again["version"] == first["version"]
    moved = _call("risk_get_expert_report", target_key=key, agent_key=SEAL, part="full", page=2, version=first["version"] + 1)
    assert (moved["error"], moved["detail"]) == ("report_version_moved", {"version": first["version"],
                                                                          "asked": first["version"] + 1})
    factories.act_as_delegate(monkeypatch, OTHER)
    assert _call("risk_get_expert_report", target_key=key, agent_key=SEAL)["error"] == "not_visible"


def test_risk_get_coverage_picks_up_the_review_block_and_the_readers_write_nothing(store, monkeypatch):
    """risk_get_coverage 는 같은 coverage_payload 라 review 칸이 저절로 붙는다. 읽기 도구 셋은 DB 를 한 바이트도 바꾸지 않는다."""
    key, _job_id, _fake = _reviewed(store)
    factories.act_as_delegate(monkeypatch, OWNER)
    before = _digest(store)
    coverage = _call("risk_get_coverage", target_key=key, with_seats=False)
    rest = routes.coverage_payload(key, owner_sub=OWNER)["review"]
    assert coverage["review"] == {**rest, **routes.review_order_brief(rest["order"])} and coverage["review"]["job"]
    _call("risk_get_cells", target_key=key)
    _call("risk_get_expert_report", target_key=key, agent_key=SEAL, part="full")
    assert _digest(store) == before


def _full_roster(n: int = 359) -> list[dict]:
    """설정의 영역 열다섯에 고루 나눈 전원 로스터(파일럿 대상의 크기) — 로스터 원천 모양 그대로 입구(create_target)가 얼린다."""
    domains = config.settings.risk_roster_domains
    return [{"key": f"{domains[i % len(domains)]}-expert-{i:03d}", "domain": domains[i % len(domains)],
             "relevance": round(0.99 - i / 1000, 4)} for i in range(n)]


def test_a_359_expert_roster_keeps_the_coverage_and_the_guide_inside_the_wire_limit(store, monkeypatch):
    """R3B-1 — 359명 로스터의 카드 대조 대상에서 진행판(좌석 행 있이·없이)과 길잡이가 와이어 25,000자 안이다. MCP 의 검토 순서는
    영역마다 영역 안 순위 1~3 과 전체 셈(order_page)이고, order_offset 으로 이어 받은 쪽을 이으면 REST 진행판의 검토 순서 전부다.
    좌석 행도 seat_offset 으로 이어 받으면 REST 좌석 행 전부다(자르지 않는다). REST 진행판은 전부를 싣는다."""
    key = rig.target(store, roster=_full_roster())
    project_id = _project_with_source(store, key)
    rig.pat(store)
    factories.act_as_delegate(monkeypatch, OWNER)
    rest = routes.coverage_payload(key, owner_sub=OWNER)
    full = rest["review"]["order"]
    assert len(full) == 359 and srv._wire_chars(rest) > 4 * srv.MCP_RESULT_CHARS
    domains = sorted({r["domain"] for r in full})

    light = _call("risk_get_coverage", target_key=key, with_seats=False)
    assert srv._wire_chars(light) <= srv.MCP_RESULT_CHARS and "seats" not in light
    assert light["review"]["order"] == [r for r in full if r["rank_in_domain"] <= 3]
    assert [r["domain"] for r in light["review"]["order"] if r["rank_in_domain"] == 1] == sorted(
        domains, key=lambda d: next(r["order"] for r in full if r["domain"] == d))
    page = light["review"]["order_page"]
    assert (page["total"], page["shown"], page["top_per_domain"], page["next_order_offset"]) == (359, 3 * len(domains), 3, 0)
    assert page["by_domain"] == {d: {"total": sum(1 for r in full if r["domain"] == d),
                                     "input_gap_n": sum(1 for r in full if r["domain"] == d and r["input_gaps"])}
                                 for d in domains}
    assert page["input_gap_n"] == sum(1 for r in full if r["input_gaps"]) > 0

    rows, offset, calls = [], 0, 0
    while offset is not None:
        out = _call("risk_get_coverage", target_key=key, order_offset=offset)
        assert srv._wire_chars(out) <= srv.MCP_RESULT_CHARS and "seats" not in out
        assert out["review"]["order_page"]["offset"] == offset
        rows += out["review"]["order"]
        calls += 1
        offset = out["review"]["order_page"].get("next_order_offset")
    assert rows == full and calls > 3

    seats, offset, calls = [], 0, 0
    while offset is not None:
        out = _call("risk_get_coverage", target_key=key, seat_offset=offset)
        assert srv._wire_chars(out) <= srv.MCP_RESULT_CHARS and out["seats_page"]["total"] == 359
        seats += out["seats"]
        calls += 1
        offset = out.get("next_seat_offset")
    assert seats == routes.seats_payload(key, owner_sub=OWNER)["seats"] and calls > 3

    guide = _call("risk_next_step", project_id=project_id)
    assert srv._wire_chars(guide) <= srv.MCP_RESULT_CHARS and guide["where"] == "review"
    shown = guide["facts"]["review_order_page"]
    assert guide["facts"]["review_order"] == [r for r in full if r["rank_in_domain"] <= shown["top_per_domain"]]
    assert (shown["total"], shown["next_order_offset"]) == (359, 0)
    assert "order_offset=0" in guide["next"][0]["why"]
    small = rig.target(store)                                            # 작은 로스터의 좌석 행은 종전처럼 한 번에 전부다
    assert "next_seat_offset" not in _call("risk_get_coverage", target_key=small) and "seats_page" not in _call(
        "risk_get_coverage", target_key=small)
    assert _call("risk_get_coverage", target_key=factories.make_diff_target(store, 3).target_key,
                 order_offset=0)["error"] == "E100"


# ---------------------------------------------------------------- 검토 잡 — risk_start_job(mode='reviews')
def test_risk_start_job_makes_a_review_job_only_for_a_delegated_identity(store, monkeypatch):
    """검토 잡은 새 쓰기 도구가 아니라 risk_start_job 의 mode·scope 다. 위임 신원이면 세우고(동의 입구 mcp · 감사 channel mcp) 같은
    호출을 다시 하면 그 잡을 돌려주며(범위가 다르면 differs), 개인 PAT Bearer(직접 등록)는 delegation_required 다. 패널 칸(tier)을
    주면 살아 있는 잡이 있어도 422 로 까닭을 말한다(조용히 버리지 않는다)."""
    key = rig.target(store)
    rig.pat(store)
    _as_bearer(monkeypatch, OWNER)
    refused = _call("risk_start_job", target_key=key, mode="reviews", scope={"agents": [SEAL]}, consent=True)
    assert refused["error"] == "delegation_required" and "Bearer" in refused["message"]
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_jobs")["n"] == 0

    factories.act_as_delegate(monkeypatch, OWNER)
    tier = _call("risk_start_job", target_key=key, mode="reviews", tier="A", scope={"agents": [SEAL]})
    assert tier["error"] == "E100" and "tier" in tier["message"]
    made = _call("risk_start_job", target_key=key, mode="reviews", scope={"agents": [SEAL]}, consent=True)
    assert made["created"] is True and made["mode"] == "reviews" and made["experts_in_scope"] == 1
    assert made["web"]["target"].endswith(key.replace(":", "%3A"))
    params = rig.job_row(store, made["job_id"])
    assert params["mode"] == "reviews" and '"consent_source":"mcp"' in params["params_json"]
    assert store.query_one("SELECT channel FROM rr_audit WHERE action = 'job.create'")["channel"] == "mcp"
    again = _call("risk_start_job", target_key=key, mode="reviews", scope={"agents": [SEAL]}, consent=True)
    assert (again["created"], again["job_id"], again["scope"], "differs" in again) == (False, made["job_id"],
                                                                                    {"agents": [SEAL]}, False)
    wider = _call("risk_start_job", target_key=key, mode="reviews", scope={"agents": [SEAL, "mech-syn-0"]})
    assert (wider["created"], wider["differs"]) == (False, ["scope"])
    assert _call("risk_start_job", target_key=key, mode="reviews", tier="B")["error"] == "E100"
    assert _call("risk_start_job", target_key=key)["error"] == "E100"           # 패널 잡은 tier 가 필요하다
    assert store.query_one("SELECT COUNT(*) AS n FROM rr_jobs")["n"] == 1


# ---------------------------------------------------------------- 길잡이 — 카드 대조 갈래
def test_the_guide_on_a_cells_target_shows_the_review_order_and_a_review_job_step_before_a_job(store, monkeypatch):
    """검토 잡 전 — facts.review_order 가 진행판의 검토 순서이고, 첫 걸음이 risk_start_job(mode='reviews', scope 자리표) 다(사람이
    고른다 — 길잡이는 전문가도 동의도 채우지 않는다). 자격이 없으면 pat_unavailable, 스위치가 꺼졌으면 review_disabled 가 막힘이고
    검토 잡 걸음을 주지 않는다."""
    key = rig.target(store)
    project_id = _project_with_source(store, key)
    out = entry.next_step(_delegate(), project_id=project_id)
    assert out["where"] == "review" and out["facts"]["review_job"] is None
    brief = routes.review_order_brief(routes.coverage_payload(key, owner_sub=OWNER)["review"]["order"])
    assert (out["facts"]["review_order"], out["facts"]["review_order_page"]) == (brief["order"], brief["order_page"])
    assert [s["tool"] for s in out["next"]] == ["risk_start_job", "risk_get_units", "risk_get_coverage", "risk_get_cells",
                                                "risk_next_step"]
    start = out["next"][0]
    assert start["args"] == {"target_key": key, **START_ARGS} and start["write"] is True
    assert "consent=true" in start["why"] and "facts.review_order" in start["why"]
    assert [b["code"] for b in out["blocked"]] == ["pat_unavailable"] and "포털에서 발급해 등록" in out["blocked"][0]["fix"]

    rig.pat(store)
    assert entry.next_step(_delegate(), project_id=project_id)["blocked"] == []
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_enabled=False))
    off = entry.next_step(_delegate(), project_id=project_id)
    assert [b["code"] for b in off["blocked"]] == ["review_disabled"] and "knobs.env" in off["blocked"][0]["fix"]
    assert "risk_start_job" not in [s["tool"] for s in off["next"]]


def test_the_guide_watches_a_running_review_job_and_reads_reports_once_it_is_done(store, monkeypatch):
    """도는 검토 잡 — 지켜볼 도구(진행판 review 칸 · 셀 격자)와 다시 보기. 끝난 잡 — where='done', 마감한 전문가의 보고서 걸음, 범위
    밖으로 남은 셀이 있으면 범위를 넓히는 검토 잡 걸음과 그 수."""
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, risk_review_concurrency=1))
    key = rig.target(store)
    project_id = _project_with_source(store, key)
    rig.pat(store)
    job_id = routes.create_job(key, routes.JobBody(mode="reviews", scope={"agents": [SEAL]}, consent=True),
                               ident=factories.ident(OWNER))["job_id"]
    fake = FakeReviewEngine({SEAL: fre.load("pack_ok.json")})
    gate = threading.Event()
    fake.hold_runs = {2: gate}
    r = rig.Rig(store, fake)
    r.tick()
    r.tick(wait=False)
    rig.wait_for(lambda: fake.runs == 2)
    try:
        running = entry.next_step(_delegate(), project_id=project_id)
        assert running["where"] == "running" and running["facts"]["review_job"]["id"] == job_id
        assert [s["tool"] for s in running["next"]] == ["risk_get_coverage", "risk_get_cells", "risk_next_step"]
        assert running["blocked"] == []
    finally:
        gate.set()
        r.loop.join(30)
    r.finish(job_id)
    done = entry.next_step(_delegate(), project_id=project_id)
    assert done["where"] == "done"
    assert [s["tool"] for s in done["next"]] == ["risk_start_job", "risk_get_coverage", "risk_get_cells",
                                                 "risk_get_expert_report", "risk_next_step"]
    report = next(s for s in done["next"] if s["tool"] == "risk_get_expert_report")
    assert report["args"] == {"target_key": key, "agent_key": SEAL} and report["write"] is False
    assert any("범위 밖으로 남은 셀이 25개" in n for n in done["notes"])          # 로스터 6 × 단위 5 − SEAL 의 5


@pytest.mark.parametrize("code,auto", [("credential", False), ("ctx_too_small", False), ("contract", False),
                                       ("agent_outdated", True), ("ctx_unknown", True)])
def test_the_guide_turns_a_code_hold_into_a_blocked_entry_with_its_fix(store, code, auto):
    """코드 보류 — 막힘에 그 보류 코드·까닭(잡 error)·고칠 곳·hold_until 을 싣는다. 자동 재개가 없는 보류는 고친 뒤 재개하는 걸음을,
    자동 재개 보류는 저절로 재개한다는 메모를 준다. 사람의 정지는 막힘이 아니라 재개 걸음이다."""
    key = rig.target(store)
    project_id = _project_with_source(store, key)
    job_id = rig.job(store, key, scope={"agents": [SEAL]})
    r = rig.Rig(store, FakeReviewEngine({SEAL: fre.load("pack_ok.json")}))
    assert r.loop.hold(job_id, code, f"시험이 거는 보류 {code}")
    out = entry.next_step(_delegate(), project_id=project_id)
    assert out["where"] == "paused"
    (held,) = [b for b in out["blocked"] if b["code"] == code]
    assert held["message"] == f"시험이 거는 보류 {code}" and held["job_id"] == job_id and held["fix"]
    assert held["fix"] == entry._review_hold_fix(code) and held["fix"] != entry._review_hold_fix("unknown-code")
    resume = [s for s in out["next"] if s["tool"] == "risk_job_action"]
    assert (resume == []) is auto
    if not auto:
        assert resume[0]["args"] == {"job_id": job_id, "action": "resume"}
    else:
        assert any(f"보류 {code} 는 저절로 재개한다" in n for n in out["notes"])
    if code == "credential":
        assert "포털에서 발급해 등록" in held["fix"] and "서비스 계정으로 내려가지 않는다" in held["fix"]

    runner.resume_job(store, job_id, by=OWNER)
    runner.pause_job(store, job_id, by=OWNER)
    paused = entry.next_step(_delegate(), project_id=project_id)
    assert [b["code"] for b in paused["blocked"]] == []
    assert paused["next"][0]["tool"] == "risk_job_action" and paused["next"][0]["args"]["action"] == "resume"


def test_the_guide_on_a_panels_target_carries_no_review_facts(store):
    """D-24 — 패널 방식 대상의 길잡이는 종전 그대로다(검토 순서·검토 잡 칸이 없고, facts.coverage 의 칸도 같다)."""
    synth = factories.make_diff_target(store, 3)
    project_id = _project_with_source(store, synth.target_key)
    out = entry.next_step(_delegate(), project_id=project_id)
    assert "review_order" not in out["facts"] and "review_job" not in out["facts"]
    assert set(out["facts"]["coverage"]) == {"roster_size", "by_status", "by_domain", "unseated_n", "strong", "level",
                                             "close_level"}
    assert not any(s["args"].get("mode") == "reviews" for s in out["next"])
