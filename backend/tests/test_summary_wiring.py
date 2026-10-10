# 변경 요약 정본 배선 — diff 요약은 render 생성기, snap 요약은 린터를 실제로 돌리고 원천 글을 «» 로 싸며 아무것도 말없이 버리지 않는다(WP1 S10 · R-22 · R-23 · P-17)
from __future__ import annotations

import json
import re

import pytest

from app import render
from tests import factories

DIFF_SECTIONS = ["대상", "비교가능성", "구조", "의미", "치수", "재료", "결과", "씨앗"]


def _diff_row(store, diff_id: str):
    return store.query_one("SELECT diff_json, summary_text, summary_status FROM rr_diffs WHERE id = ?", (diff_id,))


def _quoted_spans(text: str) -> list[str]:
    return re.findall(render.QUOTE_OPEN + r"([^" + render.QUOTE_CLOSE + r"]*)" + render.QUOTE_CLOSE, text)


def test_diff_summary_uses_the_render_builder(risk_store):
    """저장된 diff 요약은 render 의 정본 생성기가 만든 것이다 — 종전에는 그 이름이 render 에 없어 늘 폴백이 돌았다
    (의미 이벤트를 코드 이름순 앞 5건만, 변하지 않은 치수까지 전부, 2,000자에서 표식 없이 끊었다)."""
    synth = factories.make_diff_target(risk_store, 40)
    row = _diff_row(risk_store, synth.diff_id)
    text = row["summary_text"]
    assert (text, row["summary_status"]) == render.diff_summary_text(json.loads(row["diff_json"]))
    assert [line.split("]")[0].lstrip("[") for line in text.split("\n")] == DIFF_SECTIONS
    assert row["summary_status"] == "ok" and render.lint_text(text)["ok"] is True
    # 의미 이벤트는 종류별로 묶여 싣고 넘친 수를 센다.
    semantic = next(line for line in text.split("\n") if line.startswith("[의미]"))
    assert " | " in semantic and "… 외 " in semantic
    # 원천 글(부품 이름)은 «» 안이다 — 합성 쌍의 판단어 이름(강화유리 …)이 날것으로 서지 않는다.
    names = [rec_subject for rec in synth.manifest for rec_subject in rec.subjects if "hazard" in rec.flags]
    shown = [n for n in names if n in text]
    assert shown, "요약에 판단어 이름이 실리지 않았다 — 이 시험은 감싸기를 보지 않는다"
    assert all(any(n in span for span in _quoted_spans(text)) for n in shown), shown


def test_diff_summary_lists_only_changed_dims_and_counts_the_rest(risk_store):
    synth = factories.make_diff_target(risk_store, 40)
    diff = json.loads(_diff_row(risk_store, synth.diff_id)["diff_json"])
    dims = diff["parametric"]["dims_delta"]
    unchanged = [d for d in dims if d.get("flag") != "changed" and (d.get("before") is None) == (d.get("after") is None)]
    assert unchanged, "변하지 않은 치수가 없는 쌍이면 이 시험은 접기를 보지 않는다"
    line = next(ln for ln in render.diff_summary_text(diff)[0].split("\n") if ln.startswith("[치수]"))
    assert f"변화 없음 {len(unchanged)}건" in line
    assert not any(f"[d:{d['name']}]" in line for d in unchanged)


def test_a_lexicon_word_in_a_name_keeps_the_summary_instead_of_blanking_it(risk_store):
    """감싸지 못한 원천 글이 남아도 요약을 빈 글(lint_failed)로 굳히지 않는다 — 걸린 줄만 싸서 남긴다(P-17).
    스냅샷·diff 는 불변이라 빈 요약은 영구히 빈다."""
    text, status = render.settle_summary("[상위 계면] HOOK_L↔FRAME 간섭 [e:aaaaaaaaaaaa]\n[치수] t=1.0 mm [d:t]")
    assert status == "ok" and render.lint_text(text)["ok"] is True
    assert text.split("\n")[1] == "[치수] t=1.0 mm [d:t]" and "HOOK_L" in text and render.QUOTE_OPEN in text
    assert render.settle_summary("[치수] t=1.0 mm [d:t]") == ("[치수] t=1.0 mm [d:t]", "ok")


def test_snap_summary_is_linted_and_keeps_every_line(risk_store):
    """snap 요약 — 판단어 린터를 실제로 돌려 원천 이름이 걸린 줄은 «» 로 싸고(종전엔 린터가 한 번도 안 돌았다),
    글 전체를 2,000자에서 끊지 않아 맨 뒤의 [규칙]·[결측] 줄이 남는다(종전엔 그 둘이 먼저 사라졌다)."""
    synth = factories.make_diff_target(risk_store, 40)
    row = risk_store.query_one("SELECT summary_text, summary_status FROM rr_states WHERE snapshot_id = ?",
                               (synth.target_snapshot_id,))
    text = row["summary_text"]
    assert row["summary_status"] == "ok" and render.lint_text(text)["ok"] is True
    tags = [line.split("]")[0].lstrip("[") for line in text.split("\n")]
    assert tags[-3:] == ["규칙", "씨앗", "결측"], tags
    assert not any(line.startswith("…(") for line in text.split("\n"))
    # 소스 해시는 앞 12자만 — 64자리 넷이 [대상] 줄을 채우지 않는다.
    head = text.split("\n")[0]
    assert not re.search(r"=[0-9a-f]{13,}", head), head


def test_folded_items_are_counted_in_the_section(monkeypatch):
    """총량 맞춤이 뒤 섹션의 항목을 빼면 그 수도 '… 외 N건' 에 든다 — 종전에는 뺀 항목이 줄에 흔적 없이 사라졌다."""
    sections = [("가", [f"a{i}" for i in range(30)], 1000, " · ", "sig:x"),
                ("나", [f"b{i:02d}" for i in range(30)], 1000, " · ", "sig:y")]
    text = render._fit_total(sections, 200)
    assert len(text) <= 200
    for line, total in zip(text.split("\n"), (30, 30)):
        shown = len([t for t in line.split(" · ") if re.fullmatch(r"(\[\S+\] )?[ab]\d+", t)])
        folded = re.search(r"… 외 (\d+)건", line)
        assert shown + (int(folded.group(1)) if folded else 0) == total, line


def test_result_rows_beyond_five_are_counted():
    """결과 줄은 앞 5건에서 말없이 끊지 않는다 — 섹션 상한이 넘친 수를 센다."""
    rows = [{"cid": f"c:{i:012x}", "dn": f"p{i}", "metric": "worst_stress", "before": 100, "after": 100 + i,
             "rel_delta": i / 100, "flag": "changed", "text": f"P{i} worst_stress 100→{100 + i} MPa [c:{i:012x}]"}
            for i in range(1, 9)]
    diff = {"comparability": {"result_parity": True}, "parametric": {"result_delta": rows}}
    line = next(ln for ln in render._summarize_diff(diff, {}).split("\n") if ln.startswith("[결과]"))
    shown = line.count("worst_stress")
    folded = re.search(r"… 외 (\d+)건", line)
    assert shown + (int(folded.group(1)) if folded else 0) == len(rows), line


@pytest.mark.xfail(strict=True, reason="render._summarize_state 는 실제 build_state 의 신호 모양에서 dict 원문을 찍는다 — "
                                       "배선하지 않는다(WP1 S10 · R-23). 누가 고치면 이 표시가 깨져 배선을 다시 검토한다.")
def test_summarize_state_on_real_build_state_output(risk_store):
    synth = factories.make_diff_target(risk_store, 40)
    state = json.loads(risk_store.query_one("SELECT state_json FROM rr_states WHERE snapshot_id = ?",
                                            (synth.target_snapshot_id,))["state_json"])
    assert "{'" not in render._summarize_state(state, {})
