# 카드 묶음 확인·동결·꺼내기 시험(m2-wp3b S3) — 입력은 엔진의 실제 build_pack 이 낸 계약 예제(pack_*.json)다
from __future__ import annotations

import copy
import gzip
import json

import pytest

from app import cardpack, review_ops
from app.common import canonical_json
from tests import factories
from tests.conftest import FIXTURES_DIR

CONTRACT = FIXTURES_DIR / "card_review" / "contract"
AGENT = "mech-test-seal"


def _load(name: str):
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


@pytest.fixture
def pack_ok() -> dict:
    return _load("pack_ok.json")


@pytest.fixture
def pack_empty() -> dict:
    return _load("pack_empty.json")


@pytest.fixture(autouse=True)
def _fresh_cache():
    cardpack.clear_cache()
    yield
    cardpack.clear_cache()


def _rows(store) -> list:
    return store.query("SELECT agent_key, pack_key, pack_hash, cards_total, checkable_n, chars_total, unrenderable_n"
                       " FROM rr_card_packs ORDER BY agent_key, pack_key")


# ---------------------------------------------------------------- 카드 글
def test_card_text_and_text_sha_match_the_engine_vectors():
    """엔진 정규화 벡터(card_norm_vectors.json) 전부 — 인용 원문은 절 text 를 줄바꿈으로 이은 것, 해시는 같은 식이다."""
    vectors = _load("card_norm_vectors.json")["vectors"]
    assert len(vectors) >= 10
    for vector in vectors:
        card = vector["card"]
        assert cardpack.card_text(card) == vector["card_text"], vector["name"]
        if card["sections"]:
            assert cardpack.text_sha(card["sections"]) == vector["text_sha"] == card["text_sha"], vector["name"]


def test_card_basis_is_cards_background_or_none(pack_ok, pack_empty):
    assert cardpack.card_basis(pack_ok) == "cards"
    background = dict(pack_ok, cards=[c for c in pack_ok["cards"] if not c["checkable"]])
    assert background["cards"] and cardpack.card_basis(background) == "background"
    assert cardpack.card_basis(pack_empty) == "none"


# ---------------------------------------------------------------- 확인 다섯
def test_the_engine_packs_pass(pack_ok, pack_empty):
    assert cardpack.check_pack(pack_ok, agent_key=AGENT) == []
    assert cardpack.check_pack(pack_empty, agent_key=AGENT) == []
    # 엔진 개수 칸 — cards_total 은 그릴 수 있는 카드, listed_total 은 본문 없는 카드까지.
    assert pack_ok["cards_total"] == len(pack_ok["cards"]) and pack_ok["unrenderable"]
    assert pack_ok["listed_total"] == len(pack_ok["cards"]) + len(pack_ok["unrenderable"])


def _plant(pack: dict, defect: str) -> dict:
    bad = copy.deepcopy(pack)
    if defect == "header":
        bad["role_sha"] = ""
    elif defect == "agent":
        bad["agent_key"] = "mech-someone-else"
    elif defect == "alias_dup":
        bad["cards"][1]["alias"] = bad["cards"][0]["alias"]
    elif defect == "record_dup":
        bad["cards"][1]["record_id"] = bad["cards"][0]["record_id"]
    elif defect == "record_dup_unrenderable":
        bad["unrenderable"][0]["record_id"] = bad["cards"][0]["record_id"]
    elif defect == "text_sha":
        bad["cards"][0]["sections"][0]["text"] += "."
    elif defect == "cards_total":
        bad["cards_total"] += 1
    elif defect == "listed_total":
        bad["listed_total"] -= 1
    elif defect == "checkable_n":
        bad["checkable_n"] += 1
    elif defect == "no_sections":
        bad["cards"][0]["sections"] = []
    else:
        raise AssertionError(defect)
    return bad


@pytest.mark.parametrize("defect,expected", [
    ("header", "missing:role_sha"), ("agent", "agent_key:"), ("alias_dup", "alias_dup:"), ("record_dup", "record_dup:"),
    ("record_dup_unrenderable", "record_dup:"), ("text_sha", ":text_sha"), ("cards_total", "count:cards_total"),
    ("listed_total", "count:listed_total"), ("checkable_n", "count:checkable_n"), ("no_sections", ":no_sections"),
])
def test_each_planted_defect_is_named(pack_ok, defect, expected):
    problems = cardpack.check_pack(_plant(pack_ok, defect), agent_key=AGENT)
    assert problems and any(expected in p for p in problems), problems


def test_a_pack_that_is_not_an_object_is_one_problem():
    assert cardpack.check_pack(["K01"], agent_key=AGENT) == ["pack:not_object"]


# ---------------------------------------------------------------- 얼리기
def test_a_bad_pack_leaves_no_row(risk_store, pack_ok):
    with pytest.raises(cardpack.PackInvalid) as err:
        cardpack.freeze_pack(risk_store, _plant(pack_ok, "text_sha"), agent_key=AGENT)
    assert any("text_sha" in p for p in err.value.problems)
    assert _rows(risk_store) == []


def test_freezing_twice_keeps_one_row(risk_store, pack_ok):
    first = cardpack.freeze_pack(risk_store, pack_ok, agent_key=AGENT)
    again = cardpack.freeze_pack(risk_store, copy.deepcopy(pack_ok), agent_key=AGENT)
    assert first == dict(again, inserted=True) and first["inserted"] is True and again["inserted"] is False
    key = cardpack.pack_key(pack_ok)
    assert first == {"pack_key": key, "pack_hash": pack_ok["pack_hash"], "cards_total": 10, "checkable_n": 6,
                     "chars_total": 2042, "unrenderable_n": 1, "card_basis": "cards", "inserted": True}
    assert [tuple(r) for r in _rows(risk_store)] == [(AGENT, key, pack_ok["pack_hash"], 10, 6, 2042, 1)]


def test_the_frozen_bytes_are_the_whole_pack_and_the_manifest_has_no_body(risk_store, pack_ok):
    cardpack.freeze_pack(risk_store, pack_ok, agent_key=AGENT)
    row = risk_store.query_one("SELECT pack_gz, manifest_json, norm_rev, role_sha, source, fetched_at FROM rr_card_packs")
    assert json.loads(gzip.decompress(row["pack_gz"]).decode("utf-8")) == pack_ok
    manifest = json.loads(row["manifest_json"])
    assert [m["alias"] for m in manifest] == [c["alias"] for c in pack_ok["cards"]]
    assert all("sections" not in m for m in manifest)
    body = pack_ok["cards"][0]["sections"][1]["text"]
    assert body not in row["manifest_json"]
    assert (row["norm_rev"], row["role_sha"], row["source"]) == ("cr-n1", pack_ok["role_sha"], "list+get")
    assert row["fetched_at"] > 0                              # 예제의 fetched_at 0 은 '모름' 이라 얼린 시각을 적는다


def test_two_targets_pointing_at_one_pack_share_the_row(risk_store, pack_ok):
    """같은 전문가의 같은 팩은 타깃이 둘이어도 행 하나다 — 두 검토 머리가 같은 pack_key 를 가리킨다. 휘발 칸(받은 시각·자격·
    조회 길)만 다른 다시 받은 팩도 같은 열쇠다."""
    key = cardpack.freeze_pack(risk_store, pack_ok, agent_key=AGENT)["pack_key"]
    refetched = dict(copy.deepcopy(pack_ok), fetched_at=86400, credential="service", source="search+get")
    for target in ("diff:t-one", "diff:t-two"):
        _seed_head(risk_store, target, key)
        assert cardpack.freeze_pack(risk_store, refetched, agent_key=AGENT) == {
            **cardpack.freeze_pack(risk_store, pack_ok, agent_key=AGENT), "pack_key": key}
    assert len(_rows(risk_store)) == 1
    one = cardpack.load_for(risk_store, "diff:t-one", AGENT)
    two = cardpack.load_for(risk_store, "diff:t-two", AGENT)
    assert one is two and (one.pack_key, one.pack_hash) == (key, pack_ok["pack_hash"])


@pytest.mark.parametrize("change", ["sources_n", "standard_refs", "confidence", "tier", "chars", "unrenderable",
                                    "norm_rev", "role"])
def test_a_pack_that_differs_in_any_field_the_app_uses_is_its_own_row(risk_store, pack_ok, change):
    """앱의 열쇠(pack_key)는 엔진 pack_hash 에 기대지 않는다 — 엔진 식은 카드 칸 일부만 담아 출처 수(sources_n)·tier·chars·
    unrenderable·norm_rev 가 바뀐 팩도 같은 pack_hash 로 온다(계약 예제로 엔진 식을 재현해 확인, 반대 검토 C2a RC-3). 같은
    pack_hash 로 와도 앱이 쓰는 칸 어느 하나가 다르면 새 행이고, 그 팩을 가리키는 머리는 새 팩으로 등급을 매긴다 — 옛 팩이 다른
    타깃의 등급·조회를 대신하지 않는다."""
    later = copy.deepcopy(pack_ok)
    card = later["cards"][0]
    if change == "sources_n":
        card["sources_n"] = 3
    elif change == "standard_refs":
        card["standard_refs"] = []
    elif change == "confidence":
        card["confidence"] = "fact"
    elif change == "tier":
        card["tier"] = "edge"
    elif change == "chars":
        card["chars"] += 1
        later["chars_total"] += 1
    elif change == "unrenderable":
        later["unrenderable"][0]["title"] = "다른 제목"
    elif change == "norm_rev":
        later["norm_rev"] = "cr-n2"
    else:
        later["role"] = "바뀐 역할"
    assert later["pack_hash"] == pack_ok["pack_hash"] and cardpack.check_pack(later, agent_key=AGENT) == []
    first = cardpack.freeze_pack(risk_store, pack_ok, agent_key=AGENT)
    second = cardpack.freeze_pack(risk_store, later, agent_key=AGENT)
    assert second["inserted"] is True and second["pack_key"] != first["pack_key"] and len(_rows(risk_store)) == 2
    _seed_head(risk_store, "diff:t-old", first["pack_key"])
    _seed_head(risk_store, "diff:t-new", second["pack_key"])
    assert cardpack.load_for(risk_store, "diff:t-new", AGENT).raw == later
    assert cardpack.load_for(risk_store, "diff:t-old", AGENT).raw == pack_ok


def _seed_head(store, target_key: str, key: str | None) -> None:
    factories.seed_raw(store, "rr_expert_reports", {
        "target_key": target_key, "agent_key": AGENT, "owner_sub": factories.OWNER, "domain": "mech",
        "review_id": "0" * 32, "pack_hash": key},
        reason="검토 머리의 생산자(S5 review_cells.plan_cells)가 이 걸음 뒤에 선다 — 머리가 묶음을 가리키는 열 하나만 본다")


# ---------------------------------------------------------------- 꺼내기
def test_load_pack_reads_the_frozen_view(risk_store, pack_ok):
    key = cardpack.freeze_pack(risk_store, pack_ok, agent_key=AGENT)["pack_key"]
    view = cardpack.load_pack(risk_store, AGENT, key)
    assert view.order == tuple(c["alias"] for c in pack_ok["cards"])
    assert view.checkable == tuple(c["alias"] for c in pack_ok["cards"] if c["checkable"])
    assert view.background == tuple(c["alias"] for c in pack_ok["cards"] if not c["checkable"])
    assert set(view.record_cards) == {c["record_id"] for c in pack_ok["cards"]}
    assert view.by_record["DOC-CCT-MECH-2026-0000000101"] == "K01"
    assert [u["record_id"] for u in view.unrenderable] == [u["record_id"] for u in pack_ok["unrenderable"]]
    assert (view.role, view.norm_rev, view.card_basis) == (pack_ok["role"], "cr-n1", "cards")
    assert view.pack_key == key and cardpack.load_pack(risk_store, AGENT, key) is view    # 프로세스 LRU
    with pytest.raises(cardpack.PackMissing):                                              # 엔진 pack_hash 는 열쇠가 아니다
        cardpack.load_pack(risk_store, AGENT, pack_ok["pack_hash"])


def test_the_cache_is_bounded_and_keyed_by_the_db(risk_store, pack_ok, tmp_path):
    key = cardpack.freeze_pack(risk_store, pack_ok, agent_key=AGENT)["pack_key"]
    view = cardpack.load_pack(risk_store, AGENT, key)
    for n in range(cardpack.LRU_SIZE):
        cardpack._LRU[("other.db", AGENT, f"h{n}")] = view
    assert len(cardpack._LRU) == cardpack.LRU_SIZE + 1
    cardpack.load_pack(risk_store, AGENT, key)                                            # 맞힌 것은 끝으로 간다
    from app.risk_store import RiskStore

    other = RiskStore(tmp_path / "other" / "risk_review.db")
    other.open()
    other.migrate()
    try:
        with pytest.raises(cardpack.PackMissing):                                         # 다른 DB 의 행을 빌려 오지 않는다
            cardpack.load_pack(other, AGENT, key)
        cardpack.freeze_pack(other, pack_ok, agent_key=AGENT)
        cardpack.load_pack(other, AGENT, key)
    finally:
        other.close()
    assert len(cardpack._LRU) == cardpack.LRU_SIZE
    assert (str(risk_store.db_path), AGENT, key) in cardpack._LRU


def test_load_for_is_none_before_freezing_and_loud_when_the_row_is_gone(risk_store, pack_ok):
    assert cardpack.load_for(risk_store, "diff:t-none", AGENT) is None
    _seed_head(risk_store, "diff:t-none", None)
    assert cardpack.load_for(risk_store, "diff:t-none", AGENT) is None
    _seed_head(risk_store, "diff:t-gone", "f" * 64)
    with pytest.raises(cardpack.PackMissing):
        cardpack.load_for(risk_store, "diff:t-gone", AGENT)


def test_cards_for_returns_the_pack_items_byte_for_byte(risk_store, pack_ok):
    key = cardpack.freeze_pack(risk_store, pack_ok, agent_key=AGENT)["pack_key"]
    view = cardpack.load_pack(risk_store, AGENT, key)
    picked = cardpack.cards_for(view, ["K04", "K01"])
    by_alias = {c["alias"]: c for c in pack_ok["cards"]}
    assert [canonical_json(c) for c in picked] == [canonical_json(by_alias["K04"]), canonical_json(by_alias["K01"])]
    assert [set(c) for c in picked] == [set(by_alias["K04"]), set(by_alias["K01"])]     # 키를 빼거나 더하지 않는다
    picked[0]["sections"][0]["text"] = "고친 글"                                        # 복사본이다 — 얼린 뷰는 그대로
    assert cardpack.cards_for(view, ["K04"])[0] == by_alias["K04"]
    with pytest.raises(KeyError):
        cardpack.cards_for(view, ["K99"])


def test_cards_for_does_not_reverse_for_rev():
    """엔진이 rev 에서 스스로 카드 순서를 뒤집는다 — 계약 예제의 rev 요청은 fwd 와 같은 순서로 카드를 싣는다."""
    fwd, rev = _load("req_verdict_fwd.json"), _load("req_verdict_rev.json")
    assert [c["alias"] for c in fwd["cards"]] == [c["alias"] for c in rev["cards"]]
    assert {k for k in fwd if fwd[k] != rev[k]} == {"variant"}


# ---------------------------------------------------------------- 받은 결과 가르기
def test_a_pack_with_cards_is_ok(risk_store, pack_ok):
    verdict = cardpack.judge_pack(risk_store, AGENT, http_status=200, body=pack_ok)
    assert (verdict.status, verdict.code, verdict.cards_n, verdict.zero_streak) == ("ok", None, 10, 0)


def test_zero_cards_once_is_not_empty_and_twice_is(risk_store, pack_empty):
    first = cardpack.judge_pack(risk_store, AGENT, http_status=200, body=pack_empty)
    assert (first.status, first.code, first.zero_streak, first.was_nonempty) == ("error", "suspect_empty", 1, False)
    second = cardpack.judge_pack(risk_store, AGENT, http_status=200, body=pack_empty,
                                 zero_streak_before=first.zero_streak)
    assert (second.status, second.code, second.zero_streak, second.was_nonempty) == ("empty", None, 2, False)
    out = review_ops.classify(first.code)
    assert (out.klass, out.charge, out.fail_code) == ("pack", False, "pack_unavailable")


def test_zero_cards_after_a_pack_that_had_cards_needs_three_and_says_so(risk_store, pack_ok, pack_empty):
    """앞선 묶음(어느 타깃이든)에 카드가 있던 전문가의 0장은 두 번으로는 empty 가 아니고(P-08 — 복원 창), 세 번 연달으면 empty 에
    was_nonempty 를 단다 — 카드를 정말 다 잃은 전문가가 팩 재시도 끝에 failed(pack_unavailable)로 굳지 않는다(앞으로의 위험 5)."""
    cardpack.freeze_pack(risk_store, pack_ok, agent_key=AGENT)
    for streak in (0, 1):
        verdict = cardpack.judge_pack(risk_store, AGENT, http_status=200, body=pack_empty, zero_streak_before=streak)
        assert (verdict.status, verdict.code, verdict.was_nonempty) == ("error", "suspect_empty", True)
    for streak in (2, 5):
        verdict = cardpack.judge_pack(risk_store, AGENT, http_status=200, body=pack_empty, zero_streak_before=streak)
        assert (verdict.status, verdict.code, verdict.zero_streak, verdict.was_nonempty) == ("empty", None, streak + 1, True)


def test_zero_then_thirty_is_ok(risk_store, pack_ok, pack_empty):
    first = cardpack.judge_pack(risk_store, AGENT, http_status=200, body=pack_empty)
    second = cardpack.judge_pack(risk_store, AGENT, http_status=200, body=pack_ok, zero_streak_before=first.zero_streak)
    assert (first.status, second.status, second.zero_streak) == ("error", "ok", 0)


def test_an_invalid_pack_is_an_error_with_its_problems(risk_store, pack_ok):
    verdict = cardpack.judge_pack(risk_store, AGENT, http_status=200, body=_plant(pack_ok, "agent"))
    assert (verdict.status, verdict.code) == ("error", "pack_invalid") and verdict.problems
    assert review_ops.classify(verdict.code).klass == "pack"


@pytest.mark.parametrize("name,klass", [
    ("agent_not_found", "pack"), ("tools_unavailable", "pack"), ("card_fetch_failed", "pack"),
    ("card_list_unstable", "pack"), ("credential_missing", "job"), ("credential_rejected", "job"),
    ("review_busy", "wait"),
])
def test_engine_pack_errors_keep_their_code(risk_store, name, klass):
    """엔진 계약 예제 pack_errors.json 의 상태·본문 그대로 — 코드를 지키고, 다음 할 일은 review_ops 가 정한다."""
    case = _load("pack_errors.json")[name]
    verdict = cardpack.judge_pack(risk_store, AGENT, http_status=case["status"], body=case["body"])
    assert (verdict.status, verdict.code) == ("error", name)
    assert review_ops.classify(verdict.code).klass == klass


def test_a_codeless_error_status_takes_the_status_name(risk_store):
    assert cardpack.judge_pack(risk_store, AGENT, http_status=503, body="<html>").code == "portal_5xx"
    assert cardpack.judge_pack(risk_store, AGENT, http_status=404, body={}).code == "agent_outdated"
