# Claude Code 길(MCP 보충 경로)의 브리프 — 바깥 한도(MCP 결과 상한·옮겨 적기) 안으로 받고 잘린 것은 크게 알린다(BQ-2·GA-1·X-2·P-1)
"""hwax-risk-review.js 는 risk_get_brief 를 Claude 서브에이전트에게 부르게 하고 그 응답을 구조화 출력으로 '원문 그대로' 다시 받는다.

이 길에는 GLM 의 창이 아니라 바깥 한도가 걸린다 — Claude Code 는 MCP 결과가 MAX_MCP_OUTPUT_TOKENS(기본 25,000토큰)를 넘으면
본문 대신 'Error: result (N characters) exceeds maximum allowed tokens. Output has been saved to <파일>' 을 주고, 에이전트는 받은
근거를 다시 적어야 한다. M1 이 이 길의 브리프를 좌석 창(JS ctxTokens)에서 유도해 50,400자로 키우자 변경 100건 남짓부터 응답이
늘 그 상한을 넘었다(검토 GA-1·BQ-2·X-2). 권고값(context-notes '권고값으로 정한 것' — MCP 보충 경로의 옛 한도는 올리지 않는다)대로
JS 파이프라인의 옛 상수(11,000자·12항목·항목 2,000자)로 되돌리고, 응답은 토큰의 패널 1건과 근거 한 벌만 싣고, 항목마다 원문
길이(result_chars)를 실어 옮겨 적기를 대조하게 한다. 그 한도에 잘린 것은 브리프 줄 안의 표식과 응답 칸, 패널 품질로 남긴다.
"""
from __future__ import annotations

import asyncio
import json
import re

import app.mcp_server as srv
from app import brief, devseed, planner, routes, runner
from tests import factories

# Claude Code 의 MCP 결과 상한(MAX_MCP_OUTPUT_TOKENS 기본 25,000토큰)을 글자로 — JS 파이프라인과 같은 보수 환산(1자≈1토큰)이다.
CLAUDE_MCP_RESULT_CHARS = 25_000
_DOMAINS = ("mech", "sim", "xd", "rel", "cam")


def _target(store, monkeypatch, size: int = 40, *, script=None):
    """합성 다건 변경 타깃 + 라우트가 이 저장소를 보고 필드 근거 채널은 끈다(브리프가 바깥에 닿지 않게)."""
    monkeypatch.setattr(routes, "get_store", lambda: store)
    monkeypatch.setattr(routes.field_source, "for_target", lambda *a, **k: None)
    kwargs = {"seed": 7, "script": script, "check": False} if script is not None else {}
    return factories.make_diff_target(store, size, agents=factories.agents(_DOMAINS, 3), **kwargs)


def _issue(synth) -> dict:
    """앱 화면이 토큰을 내는 길(GET /targets/{key}/brief) 그대로 — planned 패널 1건과 그 토큰."""
    return routes.brief_payload(synth.target_key, "B", owner_sub=factories.OWNER, issue_token=True)["panels"][0]


def _wire(target_key: str, token: str) -> str:
    """게이트웨이가 Claude Code 에 넘기는 글 — FastMCP 가 실제로 낸 text 블록(이 도구는 구조화 출력이 없다)."""
    blocks = asyncio.run(srv.mcp.call_tool("risk_get_brief", {"target_key": target_key, "brief_token": token}))
    assert isinstance(blocks, list) and len(blocks) == 1, blocks
    return blocks[0].text


def test_the_brief_fits_the_mcp_result_limit_of_claude_code(risk_store, monkeypatch):
    """변경 319건(예산을 다 채우는 타깃)에서도 risk_get_brief 의 와이어 글이 Claude Code 의 MCP 결과 상한 안이다.

    종전에는 91,000자 남짓(약 41K토큰)이라 브리프 에이전트가 본문 대신 '파일로 저장했다' 는 'Error:' 문구를 받았다.
    """
    synth = _target(risk_store, monkeypatch, script=devseed.random_script(300, 7))
    events = risk_store.query_one("SELECT COUNT(*) AS n FROM rr_diff_events WHERE diff_id = ?", (synth.diff_id,))["n"]
    assert events > 300
    text = _wire(synth.target_key, _issue(synth)["brief_token"])
    assert len(text) <= CLAUDE_MCP_RESULT_CHARS, f"risk_get_brief 와이어 {len(text):,}자"
    out = json.loads(text)
    panel = out["panels"][0]
    assert panel["delib_opts"]["evidence"] and out["meta"]["profile"] == "mcp"


def test_the_mcp_profile_is_the_old_js_pipeline_limit():
    """MCP 보충 경로의 크기는 JS 파이프라인의 옛 상수다(권고값 — 옛 한도는 올리지 않는다). 웹 러너는 엔진 예산 그대로다."""
    assert (brief.PROFILE_MCP.name, brief.PROFILE_MCP.budget, brief.PROFILE_MCP.max_items,
            brief.PROFILE_MCP.item_result_max) == ("mcp", 11_000, 12, 2_000)
    assert brief.web_profile(500_000).budget == 500_000


def test_the_mcp_brief_carries_the_tokens_panel_once(risk_store, monkeypatch):
    """응답은 토큰의 패널 1건이고 근거는 그 패널의 delib_opts 한 벌이다 — 최상위 evidence·keys·refs 사본이 와이어의 절반이었고
    (JS 는 쓰지 않는다), 토큰과 무관한 planned 패널(동결되지 않아 인용 대조도 안 된다)까지 실려 에이전트가 옮겨 적어야 했다."""
    synth = _target(risk_store, monkeypatch, 3)
    issued = _issue(synth)
    other = planner.plan_next_panel(risk_store, synth.target_key, "C")
    assert other is not None, "둘째 planned 패널을 만들지 못했다 — 시험 전제가 깨졌다"
    out = srv.risk_get_brief(synth.target_key, issued["brief_token"])
    assert [p["panel_id"] for p in out["panels"]] == [issued["panel_id"]]
    assert not {"evidence", "keys", "refs"} & set(out), sorted(out)
    assert "shielded" not in out["meta"], "meta.shielded 는 패널의 brief_shielded 와 같은 사본이다"


def test_each_evidence_item_says_its_length_for_the_echo_check(risk_store, monkeypatch):
    """근거 항목마다 result_chars = len(result.strip()) — JS 가 옮겨 적은 result 와 견준다(줄여 옮기거나 Read 의 2,000자 줄 절단으로
    앞부분만 옮긴 근거로 좌석을 앉히지 않는다). 동결 브리프는 그 칸 없는 원문이다(항목 해시·brief_drift 가 웹 패널과 같은 기준이다)."""
    synth = _target(risk_store, monkeypatch, 40)
    issued = _issue(synth)
    out = srv.risk_get_brief(synth.target_key, issued["brief_token"])
    evidence = out["panels"][0]["delib_opts"]["evidence"]
    assert evidence and all(e["result_chars"] == len(e["result"].strip()) > 0 for e in evidence)
    frozen = runner.load_brief(risk_store, issued["panel_id"])
    assert frozen["evidence"] == [{k: v for k, v in e.items() if k != "result_chars"} for e in evidence]
    assert out["panels"][0]["brief_frozen"]["brief_hash"] == frozen["brief_hash"]


def test_a_token_whose_panel_already_ran_does_not_hand_out_another_panel(risk_store, monkeypatch):
    """토큰의 패널이 이미 planned 가 아니면(웹·다른 실행이 집었다) 다른 패널을 동결 없이 내주지 않고 까닭을 말한다 — 종전에는
    그 자리에서 새 패널을 편성해 내줘, 토큰과 무관한 패널이 동결 브리프 없이 돌았다."""
    synth = _target(risk_store, monkeypatch, 3)
    issued = _issue(synth)
    planner.start_panel_seats(risk_store, issued["panel_id"])
    out = srv.risk_get_brief(synth.target_key, issued["brief_token"])
    assert out["error"] == "brief_panel_not_planned", out
    assert out["detail"] == {"panel_id": issued["panel_id"], "status": "running"}
    assert [r["id"] for r in risk_store.query("SELECT id FROM rr_panels")] == [issued["panel_id"]], "새 패널을 편성했다"


def test_what_the_old_limit_cut_is_marked_in_the_brief_and_kept_on_the_panel(risk_store, monkeypatch):
    """옛 한도에 잘린 것은 조용히 빠지지 않는다 — 브리프 줄 안의 표식(E2 꼬리 '실림 k · 생략 m', '…(n줄 생략)'), 응답 칸
    (brief_clipped)과 사람이 읽는 한 줄(brief_notice), 그리고 패널 품질(웹에서 보인다)에 남는다. 패널 품질은 JS 가 그 칸을 옮겨
    적지 않아도 남아야 한다 — 결과 제출(engine='mcp') 뒤에도 그대로다. 지식카드 검색어 절단은 넣지 않는다 — JS 길은 그 검색어를
    엔진에 보내지 않는다."""
    synth = _target(risk_store, monkeypatch, script=devseed.random_script(300, 7))
    issued = _issue(synth)
    out = srv.risk_get_brief(synth.target_key, issued["brief_token"])
    panel = out["panels"][0]
    clipped = panel["brief_clipped"]
    assert clipped["E2"]["omitted"] > 0
    items = {e["key"]: e["result"] for e in panel["delib_opts"]["evidence"]}
    for key, info in clipped.items():
        if key == "E2":
            assert f"실림 {info['kept']} · 생략 {info['omitted']} |" in items[key].split("\n")[-1]
        elif info.get("omitted"):
            assert items[key].endswith(f"…({info['omitted']}줄 생략)"), (key, items[key][-80:])
    notice = out["brief_notice"]
    assert "11,000자" in notice and f"E2 {clipped['E2']['lines']}줄 중 {clipped['E2']['kept']}줄" in notice
    assert "risk_start_job" in notice
    quality = json.loads(risk_store.query_one("SELECT quality_json FROM rr_panels WHERE id = ?",
                                              (issued["panel_id"],))["quality_json"])
    assert quality["brief_clipped"] == clipped and "brief_clipped" in quality["flags"]
    assert "knowledge_query_cut" not in quality and "지식카드" not in notice
    # 같은 토큰으로 다시 받아도 깃발이 겹쳐 쌓이지 않는다.
    srv.risk_get_brief(synth.target_key, issued["brief_token"])
    again = json.loads(risk_store.query_one("SELECT quality_json FROM rr_panels WHERE id = ?",
                                            (issued["panel_id"],))["quality_json"])
    assert again["flags"].count("brief_clipped") == 1

    routes.complete_panel(issued["panel_id"], engine="mcp", decision_text="판정 본문.", turns=[], actor="syn",
                          owner_sub=factories.OWNER)
    after = json.loads(risk_store.query_one("SELECT quality_json, status FROM rr_panels WHERE id = ?",
                                            (issued["panel_id"],))["quality_json"])
    assert after["brief_clipped"] == clipped and "brief_clipped" in after["flags"]


def test_risk_get_diff_tells_how_to_page_the_lines():
    """part='lines' 는 상한 없이 거른 것 전부라 큰 diff 면 Claude Code 의 MCP 결과 상한을 넘는다 — 도구 설명이 limit·offset 으로
    나눠 받으라고 말한다(넘으면 본문 대신 파일 저장 안내가 간다)."""
    tools = {t.name: t for t in asyncio.run(srv.mcp.list_tools())}
    description = tools["risk_get_diff"].description
    assert re.search(r"lines.*limit.*offset.*나눠", description), description
