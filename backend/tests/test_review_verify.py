# 카드 대조 결과 회계·얼린 팩 재대조·등급·실효 판정·훑기 회계·이중 판정 시험(m2-wp3b S4) — 입력은 엔진 계약 예제(요청·결과·벡터)다
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from app import cardpack, engine_client, units
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


# 엔진의 실제 _nq·quote_check 를 엔진 venv 로 돌리는 하위 프로세스 — 이 앱 venv 로는 엔진 모듈을 들이지 않는다(의존이 다르다).
# 입출력은 ASCII JSON 이다(-I 는 PYTHONIOENCODING 을 무시한다). 카드는 엔진 build_ctx 가 요청의 팩 카드로 만드는 모양 그대로다.
_ENGINE_QUOTE_PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import card_review as cr
cases = json.loads(sys.stdin.buffer.read().decode("utf-8"))
out = {"nq": [cr._nq(s) for s in cases["nq"]], "quote": []}
for item in cases["quote"]:
    card = item["card"]
    runtime = {"text": cr.card_text(card), "sections": [(cr._str(x.get("sid")), cr._str(x.get("text")))
                                                       for x in card["sections"] if isinstance(x, dict)]}
    out["quote"].append(list(cr.quote_check(item["q"], runtime)))
sys.stdout.buffer.write(json.dumps(out, ensure_ascii=True).encode("ascii"))
"""
# 정규화가 갈리기 쉬운 글자들 — zero-width·BOM, 양방향 표지, NBSP 무리와 유니코드 공백, 제어 문자, 굽은 따옴표 여덟, 강조 기호,
# 분해형(NFD) 한글·악센트. 공유 벡터(quote_vectors.json)에는 이런 글자가 한 건도 없다(반대 검토 C2a RC-4).
_TRICKY = ("a\u200bb\u200cc\u200dd\u2060e\ufefff", "\u202eabc\u202c \u2066x\u2069 \u200el\u200fr \u061c",
           "nb\u00a0sp\u202fnarrow\u3000wide\u2028ls\u2029ps\x85nel", "c\x00t\x07rl\x1b[0m\x1c\x1d\x1e\x1f\x7f",
           "\u201c\u201d\u201e\u201f\u2018\u2019\u201a\u201b", "**굵게** `코드` «구간» *기울*",
           "\u1100\u1161\u11a8 e\u0301", "  \t\n 앞뒤 공백 \r\n ", "", None, 0)
_CARD_TEXT = ("시험용 접착 실링의 유효 접착폭은 최악 공차 누적에서도 0.8 mm 이상을 남긴다.", "코너 R 은 1.2 mm 이상이다.")


def _quote_cases() -> list[dict]:
    base = _CARD_TEXT[0]
    nfd = "\u1100\u1175\u11b7\u1109\u1173\u11bc 시험의 접착폭 기준은 0.8 mm 이상이다"   # '김승' 분해형 + 본문
    cards = {
        "plain": [{"sid": "1", "title": "규칙", "text": base}, {"sid": "2", "title": "적용", "text": _CARD_TEXT[1]}],
        "zw_card": [{"sid": "1", "title": "규칙", "text": base.replace("접착폭", "접착\u200b폭")}],
        "ctrl_card": [{"sid": "1", "title": "규칙", "text": base.replace("최악", "최\x07악")}],
        "bidi_card": [{"sid": "1", "title": "규칙", "text": "\u202a" + base + "\u202c"}],
        "nbsp_card": [{"sid": "1", "title": "규칙", "text": base.replace(" ", "\u00a0")}],
        "nfd_card": [{"sid": "1", "title": "규칙", "text": nfd}],
        "emph_card": [{"sid": "1", "title": "규칙", "text": base.replace("유효 접착폭", "**유효 접착폭**")}],
    }
    quotes = (base[:30], base[:30].replace("접착폭", "접착\u200b폭"), "\u202b" + base[:30] + "\u202c",
              base[:30].replace("최악", "최\x07악"), base[:30].replace(" ", "\u00a0"), "\u201c" + base[:30] + "\u201d",
              base[:30].replace(" ", "\n "), nfd[:25], "가각간갇갈" * 4, base[-20:] + "\n" + _CARD_TEXT[1][:12],
              base[:30].replace("\n", "\\n"), "짧다", "")
    return [{"name": f"{card}:{n}", "card": {"sections": sections}, "q": q}
            for card, sections in cards.items() for n, q in enumerate(quotes)]


def test_nq_and_quote_check_equal_the_engine_on_tricky_text():
    """앱 nq·quote_check 가 엔진 card_review._nq·quote_check 와 글자 하나까지 같다(RC-4) — 형제 엔진의 실제 함수를 엔진 venv
    하위 프로세스로 돌려 견준다. 둘이 다르면 그런 글자가 든 카드·인용은 행마다 check_disagree 가 되고(잡당 5건을 넘으면 contract
    보류) 카드 내용 탓으로 사람이 멈춘 잡을 풀어야 한다. 엔진 리포가 곁에 있는데 들이지 못하면 건너뛰지 않고 실패다(P-22)."""
    repo = Path(os.environ.get("HWAX_AGENT_SERVER_REPO") or REPO_ROOT.parent / "HWAXAgentServer")
    if not repo.is_dir():
        pytest.skip(f"엔진 리포가 곁에 없다(HWAX_AGENT_SERVER_REPO 또는 ../HWAXAgentServer) — {repo}")
    python = repo / ".venv" / "bin" / "python"
    if not python.is_file():
        pytest.fail(f"엔진 리포는 곁에 있는데 그 venv 의 python 이 없다 — {python}")
    cases = {"nq": list(_TRICKY), "quote": _quote_cases()}
    done = subprocess.run([str(python), "-I", "-B", "-c", _ENGINE_QUOTE_PROBE, str(repo)], input=json.dumps(cases).encode(),
                          capture_output=True, timeout=120, check=False)
    if done.returncode != 0:
        pytest.fail(f"엔진 card_review 를 들이거나 돌리지 못했다(rc {done.returncode}) — {done.stderr.decode(errors='replace')[-2000:]}")
    engine = json.loads(done.stdout.decode("ascii"))
    assert [rv.nq(s) for s in _TRICKY] == engine["nq"]
    app = [list(rv.quote_check(c["q"], c["card"])) for c in cases["quote"]]
    assert {c["name"]: a for c, a, e in zip(cases["quote"], app, engine["quote"]) if a != e} == {}
    assert len(app) == len(engine["quote"]) and {e[0] for e in engine["quote"]} >= {"ok", "not_found", "short", "empty"}


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
        rv.accept_rows({"rows": []}, kind="noinput", sent_aliases=[], pack={"cards": []})
    with pytest.raises(ValueError):
        rv.accept_rows({"rows": []}, kind="summary", sent_aliases=[], pack={"cards": []}, unit_refs=set())


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


def test_an_engine_conflict_mark_survives_the_accounting_and_reads_back_from_the_ledger(fwd):
    """RB3-1 — 엔진이 판정 행에 단 부딪침 표지(checks.dup_conflict · 행의 flipped_from)는 앱 회계를 지나 checks_json 에 남고
    (판정 표에 flipped_from 칸이 없어 checks 사본에 둔다), engine_conflict 가 받은 행·원장 행 어느 쪽에서든 읽는다."""
    result = copy.deepcopy(_load("result_verdict_ok.json"))
    first, second = result["rows"][0], result["rows"][1]
    first["checks"] = {**first["checks"], "dup_conflict": True}
    second["flipped_from"] = {"verdict": "FAIL", "attempt": 1}
    rows = {r["alias"]: r for r in _accept(result, fwd)["rows"]}
    a, b = first["k"], second["k"]
    assert json.loads(rows[a]["checks_json"]).get("dup_conflict") is True
    assert json.loads(rows[b]["checks_json"]).get("flipped_from") == {"verdict": "FAIL", "attempt": 1}
    assert rv.engine_conflict(rows[a]) and rv.engine_conflict(rows[b]) and rv.engine_conflict(second)
    assert not any(rv.engine_conflict(r) for k, r in rows.items() if k not in (a, b))
    assert not rv.engine_conflict({"checks_json": "not json"}) and not rv.engine_conflict({})


# ---------------------------------------------------------------- 입력 결손 호출(재설계 M3 C3-3)
def test_noinput_rows_are_accepted_whole_from_the_engine_example():
    """엔진 계약 예제(req_noinput · result_noinput_ok) — q1 둘(영향 있음 · 카드 인용이 앱 재대조도 지난다) · q2 둘(카드를 댄 것과
    대지 않은 것) · more no. 버린 줄도 빠진 줄 종류도 없다."""
    request = _load("req_noinput.json")
    out = _accept(_load("result_noinput_ok.json"), request)
    assert out["missing"] == [] and out["dropped"] == []
    q1 = [r for r in out["rows"] if r["t"] == "q1"]
    q2 = [r for r in out["rows"] if r["t"] == "q2"]
    assert [(r["impact"], r["k"], r["quote_ok"], r["refs_ok"], r["check_disagree"]) for r in q1] == [
        ("yes", "K01", 1, 1, 0), ("yes", "K02", 1, 1, 0)]
    assert q1[0]["record_id"] == request["cards"][0]["record_id"] and q1[0]["mech"] == "thermal.cte_mismatch"
    assert [(r["item"], r["k"], r["record_id"]) for r in q2] == [
        ("보드 고정점 주변 부품 배치", "K01", request["cards"][0]["record_id"]), ("근접 계면의 네트 경로", None, None)]
    assert out["extras"]["more"] == "no"
    assert rv.noinput_outcome(q1, q2) == "impact"


def test_noinput_accounting_drops_what_cannot_be_trusted():
    """실리지 않은 카드를 댄 줄(alias_outside_call) · 남의 단위를 가리키는 참조(foreign_ref — Q8) · 열거 밖 impact(bad_enum) · 제목
    없는 영향 줄(no_title)은 버린다. 지어낸 인용은 앱 재대조가 0 으로 가른다. 줄 종류가 빠지면 missing 이다."""
    request = _load("req_noinput.json")
    result = copy.deepcopy(_load("result_noinput_ok.json"))
    q1, q1b, q2, q2b, more = result["rows"]
    rows = [{**q1, "cq": "카드에 없는 지어낸 인용 문장이다 열다섯 자를 넘는다"},
            {**q1b, "k": "K99"}, {**q1b, "refs": ["c:not-this-unit"]}, {**q1b, "impact": "maybe"},
            {**q1b, "title": ""}, {**q1b, "impact": "no", "title": "", "k": "", "cq": "", "refs": [], "l": []}, more]
    out = _accept({**result, "rows": rows}, request)
    assert sorted(d["reason"] for d in out["dropped"]) == ["alias_outside_call", "bad_enum", "foreign_ref", "no_title"]
    kept = out["rows"]
    assert [(r["impact"], r["quote_ok"]) for r in kept] == [("yes", 0), ("no", None)]
    assert out["missing"] == ["q2"]
    assert _accept({**result, "rows": [q2, q2b, more]}, request)["missing"] == ["q1"]


@pytest.mark.parametrize(("impacts", "items", "outcome"), [
    (["yes", "no"], [""], "impact"), (["unknown", "yes"], ["a"], "impact"), (["no", "unknown"], [""], "unknown"),
    (["no"], ["", "확인할 것"], "request"), (["no", "no"], [""], "none"), ([], ["a"], None), (["yes"], [], None),
])
def test_the_noinput_settle_table(impacts, items, outcome):
    """m3-cells 3.6 의 정산표 — 영향 있음이 하나라도 있으면 impact, 없고 모름이 있으면 unknown, 전부 없음이면 확인할 항목이 있을 때
    request · 까닭만이면 none. q1·q2 가운데 하나라도 비면 결과가 없다(내용 탓 실패)."""
    q1 = [{"impact": i} for i in impacts]
    q2 = [{"item": x} for x in items]
    assert rv.noinput_outcome(q1, q2) == outcome


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


# ---------------------------------------------------------------- 거른 셀의 놓침 판정(M3 C3-7 — X1-13 · m3-cells 3.4)
def _eff(*cards):
    """카드마다 변형 행 [(variant, applies, judgement), …] → `effective_rows` 가 낸 실효(생산자 함수 그대로)."""
    rows = [{"record_id": f"R{i}", "variant": v, "applies": a, "judgement": j}
            for i, card in enumerate(cards) for v, a, j in card]
    return rv.effective_rows(rows)


_NA = [("fwd", "no", "na")]
_OK = [("fwd", "yes", "OK")]


@pytest.mark.parametrize(("cards", "offcard", "outcome"), [
    # risk_miss — 실효 걸림 하나, 변형이 걸렸다가 풀린 카드(split), 카드 밖 중대·치명, 심각도 없는 카드 밖 리스크
    ([_NA, [("fwd", "yes", "FAIL")]], [], "risk_miss"),
    ([_NA, [("fwd", "yes", "WARNING")]], [], "risk_miss"),
    ([_NA, [("fwd", "yes", "FAIL"), ("rev", "yes", "OK"), ("solo", "yes", "OK")]], [], "risk_miss"),
    ([_NA, [("fwd", "no", "na"), ("rev", "yes", "WARNING")]], [], "risk_miss"),
    ([_NA], [{"dir": "risk", "sev": "중대"}], "risk_miss"),
    ([_NA], [{"dir": "risk", "sev": "치명"}], "risk_miss"),
    ([_NA], [{"dir": "risk", "sev": None}], "risk_miss"),
    ([_NA], [{"sev": ""}], "risk_miss"),                                 # 방향이 비면 리스크다(앱 회계의 기본값)
    ([_OK, [("fwd", "unknown", "undetermined")]], [{"dir": "risk", "sev": "경미"}, {"dir": "risk", "sev": "치명"}],
     "risk_miss"),
    # relevance_miss — 걸림 없이 적용된 카드, 카드 밖 경미·개선
    ([_NA, _OK], [], "relevance_miss"),
    ([_NA, [("fwd", "yes", "undetermined")]], [], "relevance_miss"),   # 표의 순서 — applies=yes 가 보류보다 먼저다
    ([_NA], [{"dir": "risk", "sev": "경미"}], "relevance_miss"),
    ([_NA], [{"dir": "improvement", "sev": "치명"}], "relevance_miss"),
    ([_NA, [("fwd", "unknown", "undetermined")]], [{"dir": "improvement", "sev": "경미"}], "relevance_miss"),
    # undetermined — 판단 불가는 깨끗한 쪽에 넣지 않는다
    ([_NA, [("fwd", "unknown", "undetermined")]], [], "undetermined"),
    ([[("fwd", "unknown", "undetermined")]], [], "undetermined"),
    # kept — 전부 해당 없음, 카드 밖 없음
    ([_NA, _NA], [], "kept"),
    ([], [], "kept"),
])
def test_audit_outcome_table(cards, offcard, outcome):
    assert rv.audit_outcome(_eff(*cards), offcard) == outcome
    assert outcome in rv.AUDIT_OUTCOMES


def test_audit_outcome_reads_the_engine_offcard_rows_through_the_app_accounting():
    """카드 밖 줄은 앱 회계(`accept_rows(kind='offcard')`)를 지난 모양 그대로 읽는다 — 엔진 계약 예제의 결과로."""
    request, result = _load("req_offcard.json"), _load("result_offcard_ok.json")
    rows = _accept(result, request)["rows"]
    assert rows
    expected = ("risk_miss" if any(r["dir"] == "risk" and r["sev"] != "경미" for r in rows) else "relevance_miss")
    assert rv.audit_outcome(_eff(_NA), rows) == expected
    assert rv.audit_outcome(_eff(_NA), [dict(r, dir="improvement") for r in rows]) == "relevance_miss"


# ---------------------------------------------------------------- 걸린 것만 이중 판정 · 1순위 보정 · 무작위 뒤집기(M3 C3-9 — #31 · #32)
def _pack_with_digest(request: dict) -> cardpack.FrozenPack:
    """요청의 전문 카드 + 제목만 실린 카드(digest)를 한 팩으로 — `run_body` 가 digest 를 팩에서 다시 짓게."""
    stubs = [{**d, "sections": [], "checkable": False} for d in request["digest"]]
    return cardpack.view_of({"agent_key": request["expert"]["key"], "cards": [*request["cards"], *stubs]})


def test_two_or_more_flags_ask_rev_on_those_cards_only(fwd):
    """걸린 별칭이 둘 이상이면 그 별칭만 실은 rev 한 번 — 카드는 fwd 순서(엔진이 뒤집는다), 빠진 묶음 카드는 제목 목록으로 내려
    팩 순서로 선다. 같은 본문을 `engine_client.run_body` 가 짓는 것과 견준다(검토 루프가 rev 를 지을 그 함수)."""
    before = copy.deepcopy(fwd)
    plan = rv.dual_plan_flagged(fwd, ["K05", "K02", "K99"])     # 순서가 섞여 와도, 묶음 밖 별칭이 와도
    assert (plan["reason"], plan["solo"], plan["aliases"]) == ("dual", [], ["K02", "K05"])
    rev = plan["rev"]
    assert rev["variant"] == "rev" and [c["alias"] for c in rev["cards"]] == ["K02", "K05"]
    assert rev["cards"] == [c for c in fwd["cards"] if c["alias"] in ("K02", "K05")]
    pack = _pack_with_digest(fwd)
    oracle = engine_client.run_body("verdict", variant="rev", target_key=fwd["target_key"], pack=pack, cards=["K02", "K05"],
                                    digest=[a for a in pack.order if a not in ("K02", "K05")], unit=fwd["unit"])
    assert rev["cards"] == oracle["cards"]
    keyed = ("alias", "type", "title", "record_id")
    assert [{k: d.get(k) for k in keyed} for d in rev["digest"]] == [{k: d.get(k) for k in keyed} for d in oracle["digest"]]
    assert {k: v for k, v in rev.items() if k not in ("variant", "cards", "digest")} == {
        k: v for k, v in fwd.items() if k not in ("variant", "cards", "digest")}
    assert rv.effective_body_sha(rev) != rv.effective_body_sha(fwd)
    assert fwd == before                                        # 받은 요청은 그대로다


def test_one_flag_is_judged_again_by_its_solo_and_no_flag_asks_nothing(fwd):
    assert rv.dual_plan_flagged(fwd, ["K03"]) == {"rev": None, "solo": ["K03"], "reason": "single_flag", "aliases": [],
                                                  "neg": {"on": False, "picked": False}}
    assert rv.dual_plan_flagged(fwd, []) == {"rev": None, "solo": [], "reason": "none_flagged", "aliases": [],
                                             "neg": {"on": False, "picked": False}}
    assert rv.dual_plan_flagged(fwd, ["K42"])["reason"] == "none_flagged"     # 이 묶음에 없는 별칭은 걸림이 아니다


def test_rank1_cells_calibrate_with_the_whole_deck(fwd):
    """1순위 셀(보정 모집단)은 걸림과 상관없이 묶음 전체를 rev 한다 — M2 의 rev 요청(계약 예제)과 같다."""
    for flagged in ([], ["K01"], ["K01", "K02"]):
        plan = rv.dual_plan_flagged(fwd, flagged, calibrate=True)
        assert (plan["reason"], plan["solo"]) == ("calib", [])
        assert plan["rev"] == _load("req_verdict_rev.json") == rv.dual_plan(fwd)["rev"]
        assert plan["aliases"] == [c["alias"] for c in fwd["cards"]]
    one = dict(copy.deepcopy(fwd), cards=fwd["cards"][:1])
    assert rv.dual_plan_flagged(one, [], calibrate=True) == {"rev": None, "solo": ["K01"], "reason": "same_body",
                                                             "aliases": [], "neg": {"on": False, "picked": False}}


def test_the_random_flip_takes_a_tenth_of_unflagged_decks_only_when_on(fwd):
    keys = [("T", f"u{n}", "a", "d1") for n in range(300)]
    off = [rv.dual_plan_flagged(fwd, [], neg_on=False, neg_pct=10, sample_key=k) for k in keys]
    assert {p["reason"] for p in off} == {"none_flagged"} and {p["neg"]["on"] for p in off} == {False}
    assert {rv.dual_plan_flagged(fwd, [], neg_on=True, neg_pct=0, sample_key=k)["reason"] for k in keys} == {"none_flagged"}
    on = {k: rv.dual_plan_flagged(fwd, [], neg_on=True, neg_pct=10, sample_key=k) for k in keys}
    picked = [k for k, p in on.items() if p["reason"] == "dual_neg"]
    assert picked == [k for k in keys if rv.sample_score("dual_neg", *k) < 0.10] and 10 < len(picked) < 60
    for k, plan in on.items():
        assert plan["neg"] == {"on": True, "picked": k in picked}
        if k in picked:
            assert plan["rev"] == rv.dual_plan(fwd)["rev"] and plan["aliases"] == [c["alias"] for c in fwd["cards"]]
    # 걸린 묶음은 무작위 뒤집기를 타지 않는다 — 걸린 길(rev 걸린 별칭 · 단독)이 먼저다.
    for k in picked:
        assert rv.dual_plan_flagged(fwd, ["K01"], neg_on=True, neg_pct=10, sample_key=k)["reason"] == "single_flag"
        assert rv.dual_plan_flagged(fwd, ["K01", "K04"], neg_on=True, neg_pct=10, sample_key=k)["reason"] == "dual"
    one = dict(copy.deepcopy(fwd), cards=fwd["cards"][:1])
    assert rv.dual_plan_flagged(one, [], neg_on=True, neg_pct=100, sample_key=keys[0])["reason"] == "same_body"
    with pytest.raises(ValueError):
        rv.dual_plan_flagged(dict(fwd, variant="rev"), [])


def _calib(*cards):
    """[(unit, record, fwd, rev | None), …] → 보정 모집단의 판정 행."""
    rows = []
    for unit, record, fwd_j, rev_j in cards:
        rows.append({"unit_id": unit, "agent_key": "mech-1", "record_id": record, "variant": "fwd", "judgement": fwd_j})
        if rev_j is not None:
            rows.append({"unit_id": unit, "agent_key": "mech-1", "record_id": record, "variant": "rev", "judgement": rev_j})
    return rows


def test_the_random_flip_switches_on_above_five_percent_of_calibrated_clears():
    """분모 = fwd 가 걸림 없음(OK·na)이고 rev 가 있는 셀 × 카드, 분자 = 그 가운데 rev 가 걸림. 5% 를 **넘어야** 켠다."""
    rows = _calib(("u1", "R1", "OK", "FAIL"), ("u1", "R2", "na", "na"), ("u2", "R1", "OK", "WARNING"),
                  ("u2", "R3", "FAIL", "OK"),               # fwd 가 걸린 카드는 분모가 아니다
                  ("u3", "R1", "OK", None))                 # rev 를 못 받은 카드는 잴 수 없다
    assert rv.dual_neg_state(rows, tier_a_closed=True) == {"state": "on", "n": 3, "flips": 2, "rate": 2 / 3}
    clears = [("u", f"R{i}", "OK", "OK") for i in range(19)]
    assert rv.dual_neg_state(_calib(*clears, ("u", "R19", "na", "FAIL")), tier_a_closed=True)["state"] == "off"   # 1/20 = 5%
    assert rv.dual_neg_state(_calib(*clears[:18], ("u", "R19", "na", "FAIL")), tier_a_closed=True)["state"] == "on"  # 1/19
    assert rv.dual_neg_state(_calib(*clears), tier_a_closed=True) == {"state": "off", "n": 19, "flips": 0, "rate": 0.0}


def test_the_random_flip_is_unmeasured_until_tier_a_closes_and_never_switches_off():
    rows = _calib(("u1", "R1", "OK", "FAIL"))
    assert rv.dual_neg_state(rows, tier_a_closed=False)["state"] == "unmeasured"
    assert rv.dual_neg_state([], tier_a_closed=True) == {"state": "unmeasured", "n": 0, "flips": 0, "rate": None}
    assert rv.dual_neg_state(_calib(("u1", "R1", "FAIL", "FAIL")), tier_a_closed=True)["state"] == "unmeasured"
    clean = _calib(("u1", "R1", "OK", "OK"))
    assert rv.dual_neg_state(clean, tier_a_closed=True, already_on=True)["state"] == "on"
    assert rv.dual_neg_state(clean, tier_a_closed=False, already_on=True)["state"] == "on"
