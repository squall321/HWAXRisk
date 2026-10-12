# 카드 대조 결과 회계·얼린 팩 재대조·등급·실효 판정·훑기 회계·이중 판정 시험(m2-wp3b S4) — 입력은 엔진 계약 예제(요청·결과·벡터)다
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import pytest

from app import cardpack, units
from app import review_verify as rv
from tests.conftest import FIXTURES_DIR, REPO_ROOT

CONTRACT = FIXTURES_DIR / "card_review" / "contract"


def _load(name: str):
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def _pack_of(request: dict) -> cardpack.FrozenPack:
    return cardpack.view_of({"agent_key": request["expert"]["key"], "cards": request["cards"]})


def _unit_refs(request: dict) -> set[str]:
    """그 단위에 실은 참조 — 단위 투영(`units.refs_of`)과 같은 규칙(소유 줄 + 근거 줄, 문맥 줄 제외)."""
    unit = request["unit"]
    return units.refs_of({"lines": unit["lines"]}, {"evidence": unit["evidence"]})


def _accept(result: dict, request: dict, **kwargs) -> dict:
    return rv.accept_rows(result, kind=request["kind"], sent_aliases=[c["alias"] for c in request["cards"]],
                          pack=_pack_of(request), unit_refs=_unit_refs(request), variant=request.get("variant"),
                          **kwargs)


@pytest.fixture(scope="module")
def fwd() -> dict:
    return _load("req_verdict_fwd.json")


def _row(result: dict, alias: str) -> dict:
    return next(r for r in result["rows"] if r.get("k") == alias)


# ---------------------------------------------------------------- 인용 정규화 — 엔진과 같은 벡터
def test_quote_check_matches_the_engine_vectors():
    """엔진의 실제 quote_check 가 낸 벡터 전부(상태와 맞은 절) — 강조 기호·굽은 따옴표·«»·이스케이프 개행·절 경계·머리 줄."""
    vectors = _load("quote_vectors.json")
    assert vectors["rules"] == {"quote_min": rv.QUOTE_MIN, "quote_substantive_min": rv.QUOTE_SUBSTANTIVE_MIN}
    assert len(vectors["quote"]) >= 16
    for vector in vectors["quote"]:
        card = {"sections": vector["card"]["sections"]}
        assert cardpack.card_text(card) == vector["card"]["card_text"], vector["name"]
        got = rv.quote_check(vector["q"], card)
        assert got == (vector["expect"]["quote"], vector["expect"]["quote_sid"]), vector["name"]


@pytest.mark.parametrize("raw,expected", [
    ("**압축률 20~30%**", "압축률 20~30%"),
    ("“따옴표”와 ‘홑따옴표’", "\"따옴표\"와 '홑따옴표'"),
    ("«구간»  기호\n\t줄", "구간 기호 줄"),
    ("넓은 공백　둘", "넓은 공백 둘"),            # 엔진 _nq 의 \s+ 는 유니코드 공백도 접는다
    ("`코드` 표기", "코드 표기"),
    (None, ""),
])
def test_nq_strips_marks_and_folds_space(raw, expected):
    assert rv.nq(raw) == expected


def test_quote_rules_match_the_engine_source():
    """엔진 리포가 곁에 있으면 그쪽 소스의 하한·지우는 기호가 앱과 같다(벡터가 덮지 않는 상수를 직접 견준다)."""
    repo = Path(os.environ.get("HWAX_AGENT_SERVER_REPO") or REPO_ROOT.parent / "HWAXAgentServer")
    if not repo.is_dir():
        pytest.skip(f"엔진 리포가 곁에 없다(HWAX_AGENT_SERVER_REPO 또는 ../HWAXAgentServer) — {repo}")
    engine = repo / "card_review.py"
    if not engine.is_file():
        pytest.fail(f"엔진 리포는 곁에 있는데 card_review.py 가 없다 — {engine}. 이름이 바뀌었으면 이 시험을 같이 고친다")
    source = engine.read_text(encoding="utf-8")
    found = re.search(r"^QUOTE_MIN, QUOTE_SUBST_MIN, NEED_SUBST_MIN = (\d+), (\d+), \d+$", source, re.M)
    assert found, "엔진 card_review.py 의 인용 하한 줄을 찾지 못했다 — 이름이 바뀌었으면 이 시험을 같이 고친다"
    assert (int(found.group(1)), int(found.group(2))) == (rv.QUOTE_MIN, rv.QUOTE_SUBSTANTIVE_MIN)
    assert 're.sub(r"[*`«»]", "", s)' in source, "엔진 _nq 가 지우는 기호가 바뀌었다 — 앱 nq 와 같이 고친다"


# ---------------------------------------------------------------- 받은 행의 회계(verdict)
def test_the_engine_ok_result_is_accepted_whole(fwd):
    out = _accept(_load("result_verdict_ok.json"), fwd)
    assert [r["alias"] for r in out["rows"]] == [f"K0{n}" for n in range(1, 9)]
    assert out["missing"] == [] and out["dropped"] == []
    for row in out["rows"]:
        assert (row["quote_ok"], row["check_disagree"], row["refs_ok"], row["section_id"]) == (1, 0, 1, "1"), row
        assert row["variant"] == "fwd" and row["record_id"] == _pack_of(fwd).cards[row["alias"]]["record_id"]
        assert json.loads(row["refs_json"]) == ["c:ab12cd34ef56"] and json.loads(row["lines_json"]) == ["L01"]
    grades = {r["alias"]: r["grade"] for r in out["rows"]}
    assert grades["K06"] == grades["K07"] == "문헌·규격" and grades["K01"] == "경험칙"   # fact+규격 · heuristic+규격


def test_missing_is_recounted_and_outside_aliases_are_dropped(fwd):
    """실은 K01..K08, 온 행 K01..K06 + K13 → missing [K07, K08] 이고 K13 은 버린다 — 엔진이 missing [] 라 해도."""
    result = copy.deepcopy(_load("result_verdict_ok.json"))
    rows = [r for r in result["rows"] if r["k"] not in ("K07", "K08")]
    rows.append(dict(rows[0], k="K13", record_id="DOC-X"))
    result["rows"], result["missing"] = rows, []
    out = _accept(result, fwd)
    assert out["missing"] == ["K07", "K08"]
    assert [(d["reason"], d["row"]["k"]) for d in out["dropped"]] == [("alias_outside_call", "K13")]
    assert out["extras"]["engine_missing"] == []


def test_the_first_row_wins_and_a_foreign_record_id_is_dropped(fwd):
    result = copy.deepcopy(_load("result_verdict_ok.json"))
    first = _row(result, "K01")
    result["rows"].append(dict(first, judgement="FAIL"))
    _row(result, "K02")["record_id"] = "DOC-CCT-MECH-2026-0000000101"          # K01 의 record_id 를 실었다
    out = _accept(result, fwd)
    assert {r["alias"]: r["judgement"] for r in out["rows"]}["K01"] == "OK"
    assert out["missing"] == ["K02"]
    assert sorted(d["reason"] for d in out["dropped"]) == ["duplicate", "record_mismatch"]


@pytest.mark.parametrize("applies,judgement,reason", [
    ("maybe", "OK", "bad_enum"), ("yes", "PASS", "bad_enum"), ("no", "FAIL", "inconsistent"),
    ("unknown", "OK", "inconsistent"), ("yes", "na", "inconsistent"),
])
def test_rows_off_the_vocabulary_become_missing_cards(fwd, applies, judgement, reason):
    result = copy.deepcopy(_load("result_verdict_ok.json"))
    _row(result, "K03").update(applies=applies, judgement=judgement)
    out = _accept(result, fwd)
    assert out["missing"] == ["K03"] and [d["reason"] for d in out["dropped"]] == [reason]


@pytest.mark.parametrize("scenario,missing", [
    ("result_verdict_missing.json", ["K04"]), ("result_verdict_repair_error.json", ["K03", "K04", "K05"]),
    ("result_verdict_truncated.json", []), ("result_verdict_repaired.json", []),
])
def test_engine_scenarios_recount_to_the_engine_missing(fwd, scenario, missing):
    result = _load(scenario)
    out = _accept(result, fwd)
    assert out["missing"] == missing == result["missing"]


# ---------------------------------------------------------------- 인용 재대조
def _with_quote(fwd: dict, alias: str, cq: str, engine: str) -> dict:
    result = copy.deepcopy(_load("result_verdict_ok.json"))
    row = _row(result, alias)
    row["cq"] = cq
    row["checks"]["quote"] = engine
    return _accept(result, fwd)["rows"][int(alias[1:]) - 1]


def test_quote_without_markdown_marks_and_with_shaken_newlines_passes(fwd):
    assert _with_quote(fwd, "K01", "정적 접착 실링 부위의 유효 접착폭은 최악 공차 누적에서도 0.8", "ok")["quote_ok"] == 1
    shaken = _with_quote(fwd, "K01", "  후면\n   커버와\n   미들프레임\n   사이의 PSA 테이프 접착 계면 \t", "ok")
    assert (shaken["quote_ok"], shaken["section_id"]) == (1, "2")


def test_short_and_invented_quotes_are_zero(fwd):
    assert _with_quote(fwd, "K01", "후면 커버와 미들프레임 사", "short")["quote_ok"] == 0          # 14자
    invented = _with_quote(fwd, "K01", "이 문장은 카드 본문 어디에도 없는 지어낸 인용 문장이다", "not_found")
    assert (invented["quote_ok"], invented["check_disagree"], invented["grade"]) == (0, 0, None)


def test_another_cards_sentence_is_not_this_cards_quote(fwd):
    """그 카드의 글에만 댄다 — 같은 호출의 다른 카드(K08) 문장을 K01 인용으로 쓰면 엔진이 ok 라 해도 0 이고 어긋남이다."""
    row = _with_quote(fwd, "K01", "코너 R 을 2.0 에서 1.5 mm 로 줄인 시험 기종에서 고온 고습", "ok")
    assert (row["quote_ok"], row["check_disagree"], row["section_id"]) == (0, 1, None)


def test_quote_ok_needs_both_the_engine_and_the_app(fwd):
    """엔진이 not_found 라 했는데 앱이 통과시켜도 1 이 아니다(X1-21) — 어긋남만 남긴다."""
    row = _with_quote(fwd, "K01", "정적 접착 실링 부위의 유효 접착폭은 최악 공차 누적에서도 0.8", "not_found")
    assert (row["quote_ok"], row["check_disagree"], row["section_id"]) == (0, 1, "1")


def test_the_engine_flagged_scenario_agrees_with_the_app(fwd):
    out = _accept(_load("result_verdict_flagged.json"), fwd)
    assert {(r["quote_ok"], r["check_disagree"]) for r in out["rows"]} == {(0, 0)}


def test_an_empty_quote_is_null(fwd):
    row = _with_quote(fwd, "K02", "", "empty")
    assert (row["quote_ok"], row["check_disagree"], row["cq"], row["grade"]) == (None, 0, None, None)


# ---------------------------------------------------------------- 참조
def test_refs_outside_the_unit_fail_and_evidence_refs_pass(fwd):
    result = copy.deepcopy(_load("result_verdict_ok.json"))
    _row(result, "K01")["refs"] = ["c:ab12cd34ef56", "c:ctx0"]                  # 문맥 줄(다른 단위 소유)
    _row(result, "K02")["refs"] = ["tool:call-0"]                                # 근거 줄
    _row(result, "K03").update(refs=[], l=[])                                    # yes 인데 참조 없음
    _row(result, "K04").update(applies="no", judgement="na", refs=[], l=[])      # na 는 참조가 없을 수 있다
    rows = {r["alias"]: r for r in _accept(result, fwd)["rows"]}
    assert [rows[a]["refs_ok"] for a in ("K01", "K02", "K03", "K04")] == [0, 1, 0, None]


def test_a_single_string_is_a_one_item_list_never_characters(fwd):
    result = copy.deepcopy(_load("result_verdict_ok.json"))
    _row(result, "K01").update(l="L01", refs="c:ab12cd34ef56")
    row = _accept(result, fwd)["rows"][0]
    assert (json.loads(row["lines_json"]), json.loads(row["refs_json"]), row["refs_ok"]) == (["L01"],
                                                                                            ["c:ab12cd34ef56"], 1)
    assert rv.as_list("K01") == ["K01"] and rv.as_list(["K01", "", None]) == ["K01"] and rv.as_list({"a": 1}) == []


def test_unit_refs_and_page_units_are_required():
    with pytest.raises(ValueError):
        rv.accept_rows({"rows": []}, kind="verdict", sent_aliases=[], pack={"cards": []})
    with pytest.raises(ValueError):
        rv.accept_rows({"rows": []}, kind="sweep", sent_aliases=[], pack={"cards": []})
    with pytest.raises(ValueError):
        rv.accept_rows({"rows": []}, kind="noinput", sent_aliases=[], pack={"cards": []}, unit_refs=set())


# ---------------------------------------------------------------- 등급
def test_card_grade_follows_confidence_and_sources():
    pack = {c["alias"]: c for c in _load("pack_ok.json")["cards"]}
    assert rv.card_grade(pack["K04"]) == "문헌·규격"          # fact · 규격 · 출처 1
    assert rv.card_grade(pack["K07"]) == "문헌·규격"          # fact · 출처 1(규격 없음)
    assert rv.card_grade(dict(pack["K04"], standard_refs=[], sources_n=0)) == "경험칙"   # fact 인데 출처가 없다
    assert rv.card_grade(pack["K01"]) == "경험칙"             # heuristic 은 규격이 있어도 경험칙
    assert rv.card_grade(pack["K05"]) == "경험칙"             # expert-judgement
    assert rv.card_grade({"confidence": ""}) == "경험칙"


# ---------------------------------------------------------------- solo · offcard · sweep
def test_solo_condition_lines_go_with_their_card():
    request = _load("req_verdict_solo.json")
    out = _accept(_load("result_verdict_solo.json"), request)
    assert [r["alias"] for r in out["rows"]] == ["K01"] and out["rows"][0]["variant"] == "solo"
    conds = json.loads(out["rows"][0]["conds_json"])
    assert [(c["cond"], c["met"], c["refs"], c["refs_ok"]) for c in conds] == [
        ("카드가 요구하는 적용 조건", "yes", ["c:ab12cd34ef56"], 1)]


def test_offcard_rows_and_side_lines():
    request = _load("req_offcard.json")
    out = _accept(_load("result_offcard_ok.json"), request)
    assert out["missing"] == [] and out["dropped"] == []
    [finding] = out["rows"]
    assert (finding["dir"], finding["src"], finding["quote_ok"], finding["refs_ok"], finding["grade"]) == (
        "risk", "exp", None, 1, None)
    assert (out["extras"]["seen"], out["extras"]["more"], out["extras"]["none"]) == ([], "no", False)


def test_an_offcard_quote_from_a_sent_card_is_rechecked():
    request = _load("req_offcard.json")
    result = copy.deepcopy(_load("result_offcard_ok.json"))
    card = request["cards"][0]
    quote = cardpack.card_text(card)[:40]
    result["rows"][0].update(src=card["alias"], q=quote, checks=dict(result["rows"][0]["checks"], quote="ok"))
    finding = _accept(result, request)["rows"][0]
    assert (finding["quote_ok"], finding["record_id"], finding["check_disagree"]) == (
        1 if rv.quote_check(quote, card)[0] == "ok" else 0, card["record_id"], 0)


def _sweep_call(result: dict, request: dict) -> dict:
    return {"sent_aliases": [c["alias"] for c in request["cards"]],
            "page_units": [u["unit_id"] for u in request["manifest"]], "result": result}


def test_sweep_accounting_matches_the_engine_unmatched_cards():
    request, result = _load("req_sweep.json"), _load("result_sweep_ok.json")
    out = rv.sweep_accounting([_sweep_call(result, request)])
    assert len(out["units"]) == 30 and out["units_error"] == []
    assert out["cards_unseen"] == result["extras"]["unmatched_cards"]
    assert {u["rel"] for u in out["units"].values()} == {"maybe"}
    repaired = rv.sweep_accounting([_sweep_call(_load("result_sweep_broken_line.json"), request)])
    assert repaired["units_error"] == []                         # 깨진 줄을 엔진이 보충했다


def test_sweep_missing_unit_is_error_and_unseen_card_is_counted():
    request = _load("req_sweep.json")
    result = copy.deepcopy(_load("result_sweep_ok.json"))
    result["rows"] = [r for r in result["rows"] if r["unit_id"] != "u-05"]
    out = rv.sweep_accounting([_sweep_call(result, request)])
    assert out["units_error"] == ["u-05"] and out["units"]["u-05"]["missing_in"] == 1
    assert "K02" in out["cards_unseen"] and "K01" not in out["cards_unseen"]


def test_two_decks_take_the_wider_answer_and_a_stamped_no_is_not_trusted():
    request = _load("req_sweep.json")
    base = _load("result_sweep_ok.json")
    deck_no = copy.deepcopy(base)
    for row in deck_no["rows"]:
        row.update(rel="no", k=[])
    deck_maybe = copy.deepcopy(base)
    out = rv.sweep_accounting([_sweep_call(deck_no, request), _sweep_call(deck_maybe, request)])
    assert out["units"]["u-00"]["rel"] == "maybe"
    stamped = copy.deepcopy(deck_no)
    stamped["quality"]["stamp"] = True
    assert rv.sweep_accounting([_sweep_call(stamped, request)])["units"]["u-00"]["rel"] == "stamp"
    assert rv.sweep_accounting([_sweep_call(deck_no, request)])["units"]["u-00"]["rel"] == "no"


# ---------------------------------------------------------------- 실효 판정
def _v(variant: str, judgement: str, applies: str | None = None, record_id: str = "R1") -> dict:
    applies = applies or {"na": "no", "undetermined": "unknown"}.get(judgement, "yes")
    return {"record_id": record_id, "variant": variant, "applies": applies, "judgement": judgement}


@pytest.mark.parametrize("rows,expected", [
    ([_v("fwd", "WARNING")], ("fwd", "WARNING", None, 0, False, False)),
    ([_v("fwd", "OK"), _v("rev", "OK")], ("fwd", "OK", 1, 0, False, False)),
    ([_v("fwd", "FAIL"), _v("rev", "WARNING"), _v("solo", "WARNING")], ("solo", "WARNING", 0, 0, True, False)),
    ([_v("fwd", "WARNING"), _v("rev", "FAIL")], ("rev", "FAIL", 0, 0, False, True)),
    ([_v("fwd", "WARNING"), _v("solo", "FAIL")], ("solo", "FAIL", None, 0, True, False)),
    # X1-14 — 걸림이 있었는데 실효가 통과로 끝나면 undetermined · split.
    ([_v("fwd", "FAIL"), _v("rev", "FAIL"), _v("solo", "OK")], ("solo", "undetermined", 1, 1, True, True)),
    ([_v("fwd", "OK"), _v("rev", "FAIL"), _v("solo", "OK")], ("solo", "undetermined", 0, 1, False, True)),
    ([_v("fwd", "WARNING"), _v("solo", "na")], ("solo", "undetermined", None, 1, True, True)),
])
def test_effective_table(rows, expected):
    eff = rv.effective_rows(rows)["R1"]
    assert (eff["variant"], eff["judgement"], eff["agree"], eff["split"], eff["flipped"], eff["disputed"]) == expected
    assert eff["claimed"] == max((r["judgement"] for r in rows), key=lambda j: rv._WEIGHT[j])


def test_a_split_na_is_not_left_as_applies_no():
    eff = rv.effective_rows([_v("fwd", "WARNING"), _v("solo", "na")])["R1"]
    assert (eff["applies"], eff["judgement"]) == ("unknown", "undetermined")


def test_mark_effective_and_tally():
    rows = [_v("fwd", "FAIL", record_id="A"), _v("rev", "FAIL", record_id="A"),
            _v("fwd", "OK", record_id="B"), _v("rev", "WARNING", record_id="B"),
            _v("fwd", "OK", record_id="C"), _v("fwd", "na", record_id="D")]
    marked = rv.mark_effective(rows)
    assert [(r["record_id"], r["variant"], r["is_effective"], r["agree"], r["split"]) for r in marked] == [
        ("A", "fwd", 1, 1, 0), ("A", "rev", 0, 1, 0), ("B", "fwd", 0, 0, 0), ("B", "rev", 1, 0, 0),
        ("C", "fwd", 1, None, 0), ("D", "fwd", 1, None, 0)]
    tally = rv.cell_tally(rv.effective_rows(rows))
    assert tally == {"cards_judged": 4, "n_fail": 1, "n_warning": 1, "n_ok": 1, "n_na": 1, "n_undetermined": 0,
                     "n_disputed": 1, "n_flipped": 0}
    assert sum(tally[k] for k in ("n_fail", "n_warning", "n_ok", "n_na", "n_undetermined")) == tally["cards_judged"]


# ---------------------------------------------------------------- 표본 · 이중 판정
def test_sample_score_is_deterministic_and_uniform():
    assert rv.sample_score("dual", "T", "U", "A") == rv.sample_score("dual", "T", "U", "A")
    assert rv.sample_score("dual", "T", "U", "A") != rv.sample_score("dual", "A", "U", "T")
    assert rv.sample_score("dual", "T", salt="other") != rv.sample_score("dual", "T")
    scores = [rv.sample_score("dual", "t", str(n)) for n in range(10000)]
    assert all(0.0 <= s < 1.0 for s in scores)
    assert abs(sum(scores) / len(scores) - 0.5) < 0.02


def test_dual_plan_builds_the_engine_rev_request(fwd):
    """rev 요청은 엔진 계약 예제 req_verdict_rev.json 과 같다 — variant 만 바뀌고 카드 순서는 엔진이 뒤집는다."""
    plan = rv.dual_plan(fwd)
    assert plan["reason"] == "dual" and plan["solo"] == []
    assert plan["rev"] == _load("req_verdict_rev.json")
    assert fwd["variant"] == "fwd"                              # 받은 요청은 그대로다


def test_a_one_card_deck_is_not_asked_twice(fwd):
    """카드 1장 묶음의 rev 는 엔진이 보는 본문이 fwd 와 같다 — 부르지 않고 그 카드를 solo 로(X1-20)."""
    one = dict(copy.deepcopy(fwd), cards=fwd["cards"][:1])
    assert rv.effective_body_sha(one) == rv.effective_body_sha(dict(one, variant="rev"))
    assert rv.dual_plan(one) == {"rev": None, "solo": ["K01"], "reason": "same_body"}


def test_dual_plan_samples_below_full_rate(fwd):
    keys = [("t", f"u{n}", "a") for n in range(200)]
    picked = [k for k in keys if rv.dual_plan(fwd, dual_rate=0.15, sample_key=k)["rev"] is not None]
    assert picked == [k for k in keys if rv.sample_score("dual", *k) < 0.15] and 0 < len(picked) < 200
    with pytest.raises(ValueError):
        rv.dual_plan(dict(fwd, variant="rev"))
