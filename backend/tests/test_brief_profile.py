# 브리프 예산 프로파일 — 웹은 엔진이 알려 준 근거 예산, MCP 는 JS 파이프라인 상한, 1백만 토큰 창에서 상한표가 묶이지 않는다(WP1 S9)
from __future__ import annotations

import itertools
import json

from app import brief, devseed, routes, runner, taxonomy
from tests import factories


def test_web_profile_uses_the_engine_budget():
    """엔진 /health 의 evid_budget 을 그대로 쓴다 — 낮은 고정 천장(권고였던 24,000)이 없고, 바닥은 종전 11,000 이다."""
    assert brief.web_profile(None) is brief.PROFILE_LEGACY
    assert brief.web_profile("17967") is brief.PROFILE_LEGACY and brief.web_profile(True) is brief.PROFILE_LEGACY
    assert brief.PROFILE_LEGACY.budget == brief.ENGINE_BUDGET == 11000
    small = brief.web_profile(2000)                                   # 16K 창 — 엔진 예산이 바닥 2,000자
    assert (small.name, small.budget) == ("web", 11000)
    assert brief.web_profile(17967).budget == 17967                    # 128K 창
    wide = brief.web_profile(500_000)                                  # 1백만 토큰 창(엔진 천장 500,000)
    assert wide.budget == 500_000 and wide.item_result_max == brief.ENGINE_ITEM_MAX
    # 상한표는 같은 배수로 는다 — Σ 상한 ≤ 예산이 서고 어느 칸도 바닥 값에 묶이지 않는다.
    for profile in (small, brief.web_profile(17967), wide, brief.PROFILE_MCP):
        caps = {key: profile.cap(key) for key in brief.ITEM_ORDER}
        assert sum(caps.values()) <= profile.budget
        assert all(caps[k] >= brief.CAPS[k] for k in caps)
    assert wide.cap("E2") > 40 * brief.CAPS["E2"] and wide.cap("M") > 40 * brief.CAPS["M"]


def test_profile_sum_never_exceeds_its_budget_and_wide_windows_carry_every_change(risk_store):
    """다건 변경(대본 300건)에서 — 어느 프로파일이든 라인 합 ≤ Σ 상한 ≤ 예산이고, 1백만 토큰 창이면 변경 전부가 실린다."""
    synth = factories.make_diff_target(risk_store, 40, seed=7, script=devseed.random_script(300, 7), check=False)
    n_events = risk_store.query_one("SELECT COUNT(*) AS n FROM rr_diff_events WHERE diff_id = ?",
                                    (synth.diff_id,))["n"]
    assert n_events > 150
    for profile in (brief.PROFILE_LEGACY, brief.web_profile(17967), brief.PROFILE_MCP, brief.web_profile(500_000)):
        built = brief.build_brief(risk_store, synth.target_key, owner_sub=factories.OWNER, shield_lint=True,
                                  profile=profile)
        meta = built["meta"]
        assert meta["profile"] == profile.name and meta["budget"] == profile.budget
        assert meta["budget_used"] == sum(len(brief.evidence_line(i)) for i in built["evidence"])
        assert meta["budget_used"] <= meta["caps_sum"] <= profile.budget, profile
        assert len(built["evidence"]) <= profile.max_items
        assert all(len(i["result"]) <= profile.item_result_max for i in built["evidence"])
    legacy = brief.build_brief(risk_store, synth.target_key, owner_sub=factories.OWNER, shield_lint=True)
    assert legacy["meta"]["clipped"]["E2"]["omitted"] > 0                     # 바닥에서는 종전처럼 잘리고 그 수를 남긴다
    wide = brief.build_brief(risk_store, synth.target_key, owner_sub=factories.OWNER, shield_lint=True,
                             profile=brief.web_profile(500_000))
    assert "E2" not in wide["meta"]["clipped"], wide["meta"]["clipped"]
    e2 = next(i for i in wide["evidence"] if i["key"] == "E2")["result"].split("\n")
    assert e2[-1].startswith(f"[전체 {n_events}건 — 실림 {n_events} · 생략 0 |"), e2[-1]


def test_long_memo_is_carried_whole_in_a_wide_window(risk_store):
    """넓은 창에서 사용자 메모(1,500자)는 통째로 실린다 — 위생의 memo 400자 상한에도 묶이지 않는다."""
    synth = factories.make_diff_target(risk_store, 3)
    memo = "배터리 모서리 간극부터 보라. " + "나" * 1483
    wide = brief.build_brief(risk_store, synth.target_key, owner_sub=factories.OWNER, user_memo=memo,
                             profile=brief.web_profile(500_000))
    item = next(i for i in wide["evidence"] if i["key"] == "M")
    assert brief.memo_cut(item) is None and memo in item["result"]
    legacy = brief.build_brief(risk_store, synth.target_key, owner_sub=factories.OWNER, user_memo=memo)
    assert legacy["meta"]["user_memo_cut"]["chars"] == 1500


def test_seat_contract_evidence_keeps_every_seated_domain():
    """E0c 는 착석 도메인의 계약 행을 하나도 빼지 않는다(R-18) — 바닥 상한이면 긴 행을 같은 몫으로 줄이고 원문 길이를
    밝히며, 넓은 창이면 행 전부가 원문 그대로다. 종전에는 행마다 200자에서 끊고 합 1,000자를 넘는 다섯째 행을 뺐다."""
    contract = taxonomy.load_json("seat-contract")["contract"]
    domains = [d for d in contract if d != "_common"]
    for combo in itertools.combinations(domains, 5):
        item = runner.seat_contract_evidence(list(combo))
        lines = item["result"].split("\n")
        assert len(brief.evidence_line(item)) <= brief.CAPS["E0c"], combo
        assert len(lines) == len(combo), combo
        for dom, line in zip(combo, lines):
            row = contract[dom]
            if line != row:
                kept = len(line) - len(f" …({len(row)}자 중 ")
                assert line.endswith("자)") and f" …({len(row)}자 중 " in line, line
                assert row.startswith(line.split(" …(")[0]), (dom, line)
                assert kept > 0
    # Tier A 고정 패널(mem·passive·pcb·pwr + soc)과 가장 긴 std — 다섯째 행이 빠지던 바로 그 조합이다.
    tier_a = runner.seat_contract_evidence(["mem", "passive", "pcb", "pwr", "soc", "std"])
    assert [ln.split(" ")[0] for ln in tier_a["result"].split("\n")] == \
        [contract[d].split(" ")[0] for d in ("mem", "passive", "pcb", "pwr", "soc", "std")]
    wide = runner.seat_contract_evidence(["mem", "passive", "pcb", "pwr", "soc", "std"],
                                         brief.web_profile(500_000).cap("E0c"))
    assert wide["result"].split("\n") == [contract[d] for d in ("mem", "passive", "pcb", "pwr", "soc", "std")]


def test_mcp_brief_is_shielded_sized_for_js_and_frozen_for_the_token_panel(risk_store, monkeypatch):
    """MCP 브리프(`risk_get_brief`) — 이름에 판단어가 든 부품으로도 E500 이 아니라 방패를 싸서 싣고(웹과 같은 모드),
    크기는 JS 상한이며, 토큰의 패널에 그 조립을 동결한다(P-09). REST 미리보기는 동결하지 않는다."""
    synth = factories.make_diff_target(risk_store, 40, agents=factories.agents(("mech", "sim", "xd", "rel", "cam"), 3))
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(routes.field_source, "for_target", lambda *a, **k: None)
    preview = routes.brief_payload(synth.target_key, "B", owner_sub=factories.OWNER, issue_token=True)
    assert preview["meta"]["profile"] == "mcp" and preview["meta"]["budget"] == brief.PROFILE_MCP.budget
    assert preview["meta"]["shielded"], "합성 타깃의 이름에 판단어가 없다면 이 시험은 방패를 보지 않는다"
    panel = preview["panels"][0]
    assert panel["brief_shielded"] == preview["meta"]["shielded"]
    assert risk_store.query_one("SELECT brief_gz FROM rr_panels WHERE id = ?", (panel["panel_id"],))["brief_gz"] is None

    out = routes.brief_by_token(synth.target_key, panel["brief_token"], "B")
    frozen = runner.load_brief(risk_store, panel["panel_id"])
    item = next(p for p in out["panels"] if p["panel_id"] == panel["panel_id"])
    assert frozen["evidence"] == item["delib_opts"]["evidence"]
    assert item["brief_frozen"]["brief_hash"] == frozen["brief_hash"]
    e0c = next(e for e in item["delib_opts"]["evidence"] if e["key"] == "E0c")
    assert len(brief.evidence_line(e0c)) <= brief.PROFILE_MCP.cap("E0c")
    assert json.dumps(out, ensure_ascii=False)
