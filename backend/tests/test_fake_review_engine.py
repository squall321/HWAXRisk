# 가짜 카드 대조 엔진(tests/synth/fake_review_engine.py) 검사 — 모양이 엔진 계약 예제와 같고, 인용·줄 별칭이 받은 것에서 오며, 결함 스위치가 실제 클라이언트에서 그 결말을 낸다
"""가짜가 엔진과 다른 모양을 내면 그 위의 검토 루프 시험(S8)은 엔진이 내지 않는 모양으로 초록이 된다. 그래서 가짜의 result
프레임을 엔진이 같은 요청 예제로 실제로 낸 `result_*.json` 과 키 집합까지 견준다. 스위치는 실제 `PortalReviewEngine` 을 거쳐
본다 — 앱이 받는 예외와 `review_verify.accept_rows` 의 회계가 그 결함을 가르는지까지.
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from app import cardpack, common, engine_client, identity, review_ops, units
from app import review_verify as rv
from app.runner import EngineBusy, EngineRejected, EngineStreamLost, PatUnavailable
from tests.synth import fake_review_engine as fre
from tests.synth.fake_review_engine import FakeReviewEngine

USER = "reviewer@example.com"
USER_PAT = "pat-reviewer"
# (요청 예제, 엔진 결과 예제) — 같은 요청을 엔진이 실제 run 으로 낸 결과와 견준다.
SCENES = {"verdict_fwd": ("req_verdict_fwd.json", "result_verdict_ok.json"),
          "verdict_rev": ("req_verdict_rev.json", "result_verdict_rev.json"),
          "verdict_solo": ("req_verdict_solo.json", "result_verdict_solo.json"),
          "sweep": ("req_sweep.json", "result_sweep_ok.json"),
          "offcard": ("req_offcard.json", "result_offcard_ok.json")}


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def get_credential(self, owner_sub):
        return self.rows.get(owner_sub)


def _client(tmp_path, fake: FakeReviewEngine) -> engine_client.PortalReviewEngine:
    (tmp_path / "secrets.env").write_text("HWAXRISK_PORTAL_PAT=svc-pat\n", encoding="utf-8")
    (tmp_path / "secrets.env").chmod(0o600)
    row = {"portal_pat": identity.encrypt_pat(USER_PAT).decode("ascii"), "pat_email": USER,
           "pat_exp": common.now_epoch() + 30 * 86400, "revoked_at": None}
    settings = SimpleNamespace(data_dir=tmp_path, portal_base="http://portal.test", agent_url="http://agent.test")
    return engine_client.PortalReviewEngine(_Store({USER: row}), settings, transport=fake.transport)


def _raised(fn, *args, **kwargs) -> BaseException:
    with pytest.raises((EngineBusy, PatUnavailable, EngineRejected, EngineStreamLost)) as exc:
        fn(*args, **kwargs)
    return exc.value


def _keysets(rows) -> dict[str, set]:
    out: dict[str, set] = {}
    for row in rows:
        out.setdefault(row["t"], set()).add(frozenset(row))
        out.setdefault(f"{row['t']}.checks", set()).add(frozenset(row["checks"]))
    return out


def _accept(result: dict, request: dict) -> dict:
    return rv.accept_rows(result, kind=request["kind"], sent_aliases=[c["alias"] for c in request["cards"]],
                          pack=cardpack.view_of({"agent_key": request["expert"]["key"], "cards": request["cards"]}),
                          unit_refs=units.refs_of({"lines": request["unit"]["lines"]},
                                                  {"evidence": request["unit"]["evidence"]}),
                          variant=request.get("variant"))


# ---------------------------------------------------------------- 모양 = 엔진 계약 예제
@pytest.mark.parametrize("scene", sorted(SCENES))
def test_the_fake_result_has_the_engine_key_sets(tmp_path, scene):
    req_name, result_name = SCENES[scene]
    request, engine = fre.load(req_name), fre.load(result_name)
    got = _client(tmp_path, FakeReviewEngine()).run(request, email=USER)

    assert set(got) == set(engine)
    for key in ("quality", "meta", "extras"):
        assert set(got[key]) == set(engine[key]), key
    assert set(got["meta"]["aliases"]) == set(engine["meta"]["aliases"])
    assert set(got["meta"]["usage"]) == set(engine["meta"]["usage"])
    assert set(got["meta"]["usage"]["per_attempt"][0]) == set(engine["meta"]["usage"]["per_attempt"][0])
    # 줄 종류마다 칸 집합(checks 포함)이 엔진의 것과 같고, 엔진이 낸 줄 종류를 가짜도 낸다.
    assert _keysets(got["rows"]) == _keysets(engine["rows"])
    # 같은 요청이면 별칭 표가 엔진의 것과 같다 — 가짜는 받은 카드·줄·단위로 별칭을 세운다.
    assert got["meta"]["aliases"] == engine["meta"]["aliases"]
    assert (got["kind"], got["variant"], got["missing"]) == (engine["kind"], engine["variant"], [])
    assert got["meta"]["prompt_rev"] == engine["meta"]["prompt_rev"] and got["meta"]["basis"] == engine["meta"]["basis"]


@pytest.mark.parametrize("scene", ["verdict_fwd", "verdict_rev", "verdict_solo"])
def test_quotes_are_cut_from_the_cards_sent_and_lines_are_the_aliases_sent(tmp_path, scene):
    request = fre.load(SCENES[scene][0])
    got = _client(tmp_path, FakeReviewEngine()).run(request, email=USER)
    cards = {c["alias"]: c for c in request["cards"]}
    aliases = got["meta"]["aliases"]["lines"]
    verdicts = [r for r in got["rows"] if r["t"] == "v"]
    assert [r["k"] for r in verdicts] == (list(cards)[::-1] if scene == "verdict_rev" else list(cards))
    for row in verdicts:
        card = cards[row["k"]]
        assert any(row["cq"] in s["text"] for s in card["sections"]), row["k"]      # 받은 카드 글의 실제 부분 문자열
        assert rv.quote_check(row["cq"], card) == (row["checks"]["quote"], row["checks"]["quote_sid"]) == ("ok", "1")
        assert row["record_id"] == card["record_id"] and row["card_id"] == card["card_id"]
        assert row["l"] and set(row["l"]) <= set(aliases) and row["refs"] == [aliases[a] for a in row["l"]]
    accepted = _accept(got, request)
    assert accepted["dropped"] == [] and accepted["missing"] == []
    assert {(r["quote_ok"], r["check_disagree"], r["refs_ok"]) for r in accepted["rows"]} == {(1, 0, 1)}
    if scene == "verdict_solo":
        assert json.loads(accepted["rows"][0]["conds_json"])[0]["met"] == "yes"


# ---------------------------------------------------------------- 결함 스위치 — 실제 클라이언트를 거쳐 본다
def test_card_switches_reach_the_apps_accounting(tmp_path):
    request = fre.load("req_verdict_fwd.json")
    fake = FakeReviewEngine()
    client = _client(tmp_path, fake)

    fake.skip_cards = {"K02"}
    got = client.run(request, email=USER)
    assert got["missing"] == ["K02"] and got["quality"]["missing"] == 1 and "K02" not in {r["k"] for r in got["rows"]}
    assert _accept(got, request)["missing"] == ["K02"]

    fake.skip_cards, fake.unknown_alias = set(), True
    got = client.run(request, email=USER)
    assert got["rows"][-1]["k"] == "K99"
    assert [d["reason"] for d in _accept(got, request)["dropped"]] == ["alias_outside_call"]

    fake.unknown_alias, fake.invented_quote = False, {"K01"}
    got = client.run(request, email=USER)
    row = next(r for r in got["rows"] if r["k"] == "K01")
    assert row["cq"] == fre.INVENTED_QUOTE and row["checks"]["quote"] == "not_found"
    assert got["quality"]["flagged"] == 1
    k01 = next(r for r in _accept(got, request)["rows"] if r["alias"] == "K01")
    assert (k01["quote_ok"], k01["check_disagree"]) == (0, 0)

    fake.invented_quote, fake.lying_quote = set(), {"K03"}
    got = client.run(request, email=USER)
    assert next(r for r in got["rows"] if r["k"] == "K03")["checks"]["quote"] == "ok"   # 엔진이 속인다
    k03 = next(r for r in _accept(got, request)["rows"] if r["alias"] == "K03")
    assert (k03["quote_ok"], k03["check_disagree"]) == (0, 1)                         # 앱 재대조가 가른다

    fake.lying_quote, fake.truncated = set(), True
    got = client.run(request, email=USER)
    assert got["quality"]["truncated"] is True and got["meta"]["finish_reason"] == "length"
    assert got["missing"] == ["K08"]

    fake.truncated = False
    fake.verdicts = {request["cards"][0]["record_id"]: ("yes", "FAIL"), request["cards"][1]["record_id"]: ("no", "na")}
    got = client.run(request, email=USER)
    fail, na = got["rows"][0], got["rows"][1]
    assert (fail["judgement"], fail["sev"], fail["check_kind"]) == ("FAIL", "중대", "test")
    assert (na["applies"], na["judgement"], na["l"]) == ("no", "na", [])
    assert _accept(got, request)["dropped"] == []


def test_stream_switches_give_the_clients_outcomes(tmp_path):
    request = fre.load("req_verdict_solo.json")
    fake = FakeReviewEngine()
    client = _client(tmp_path, fake)

    fake.busy_n = 2
    for _ in range(2):
        exc = _raised(client.run, request, email=USER)
        assert isinstance(exc, EngineBusy) and (exc.code, exc.retry_after_s) == ("review_busy", 30)
    assert client.run(request, email=USER)["variant"] == "solo"

    fake.error_n = 1
    exc = _raised(client.run, request, email=USER)
    assert isinstance(exc, EngineRejected) and exc.code == "llm_unreachable" and exc.infra is True
    assert engine_client.review_outcome(exc).klass == review_ops.INFRA
    fake.error_n, fake.error = 1, {"code": "llm_misconfigured", "message": "키가 틀렸다", "infra": True, "retryable": False}
    assert engine_client.review_outcome(_raised(client.run, request, email=USER)).hold_code == "llm_misconfigured"

    fake.cut_n = 1
    exc = _raised(client.run, request, email=USER)
    assert isinstance(exc, EngineStreamLost) and exc.code == "engine_stream_cut"
    assert client.run(request, email=USER)["rows"]

    fake.delay_s = 0.2
    seen: list = []
    started = time.monotonic()
    client.run(request, email=USER, on_progress=seen.append)
    assert time.monotonic() - started >= 0.2 and seen[0]["last_step"] == "attempt 1"
    assert fake.active == 0

    fake.delay_s, fake.credential_expired = 0.0, True
    for call in (lambda: client.limits(email=USER), lambda: client.pack("x", email=USER),
                 lambda: client.plan({}, email=USER), lambda: client.run(request, email=USER)):
        exc = _raised(call)
        assert isinstance(exc, PatUnavailable) and exc.code == "credential_rejected"


def test_window_and_plan_switches(tmp_path):
    fake = FakeReviewEngine()
    client = _client(tmp_path, fake)
    assert client.limits(email=USER)["ctx_source"] == "server"
    fake.ctx_source = "fallback"
    assert client.limits(email=USER)["ctx_source"] == "fallback"
    assert client.run(fre.load("req_verdict_solo.json"), email=USER)["meta"]["ctx_source"] == "fallback"

    fake.ctx_unknown = True
    lim = client.limits(email=USER)
    assert lim["ctx_retrying"] is True
    for call in (lambda: client.plan(fre.load("plan_req.json"), email=USER),
                 lambda: client.run(fre.load("req_verdict_solo.json"), email=USER)):
        exc = _raised(call)
        assert isinstance(exc, EngineBusy) and (exc.code, exc.retry_after_s) == ("ctx_unknown", 60)
    fake.ctx_unknown = False

    req = fre.load("plan_pair_over_req.json")
    plain = client.plan(req, email=USER)
    assert plain["pair_over"] == [] and plain["oversize"]["units"] == [] and plain["manifest_pages"] == [["u-big", "u-small"]]
    fake.pair_over_units = {"u-big"}
    out = client.plan(req, email=USER)
    assert [(p["deck_id"], p["unit_id"]) for p in out["pair_over"]] == [(d["deck_id"], "u-big") for d in out["verdict_decks"]]
    fake.pair_over_units, fake.oversize_units = set(), {"u-big"}
    out = client.plan(req, email=USER)
    assert out["oversize"]["units"] == ["u-big"] and out["manifest_pages"] == [["u-small"]]
    assert set(out) == set(fre.load("plan_pair_over.json"))
    # 묶음은 점검 카드를 팩 순서로 K 장씩 — 엔진 예제(plan_req → plan_ok)와 같은 묶음 id 다.
    ok = client.plan(fre.load("plan_req.json"), email=USER)
    assert [d["deck_id"] for d in ok["verdict_decks"]] == [d["deck_id"] for d in fre.load("plan_ok.json")["verdict_decks"]]


def test_the_fake_refuses_like_the_engine(tmp_path):
    """선언 밖 칸(안쪽 항목까지)·판 어긋남·모르는 전문가는 엔진과 같은 코드다 — 가짜가 무엇이든 받아 주면 S8 의 요청 버그가
    가짜 위에서 초록이 된다."""
    fake = FakeReviewEngine({"mech-test-seal": fre.load("pack_ok.json")})
    client = _client(tmp_path, fake)
    assert client.pack("mech-test-seal", email=USER)["pack_hash"] == fre.load("pack_ok.json")["pack_hash"]
    exc = _raised(client.pack, "nobody", email=USER)
    assert isinstance(exc, EngineRejected) and exc.code == "agent_not_found"
    assert engine_client.review_outcome(exc).klass == review_ops.PACK

    request = fre.load("req_verdict_fwd.json")
    bad = {**request, "extra": {"domains": [{"code": "mech", "label": "기구"}]}}
    exc = _raised(client.run, bad, email=USER)
    assert isinstance(exc, EngineRejected) and exc.code == "unknown_fields"
    assert exc.detail["fields"] == ["extra.domains.0.code"]
    exc = _raised(client.plan, {"agent_key": "mech-test-seal", "cards": [], "units": []}, email=USER)
    assert exc.code == "unknown_fields" and exc.detail["fields"] == ["agent_key"]
    exc = _raised(client.run, {**request, "expect": {"limits_rev": "00000000"}}, email=USER)
    assert isinstance(exc, EngineRejected) and exc.code == "rev_mismatch"
    assert engine_client.review_outcome(exc).hold_code == "contract"


def test_health_and_the_request_log(tmp_path):
    fake = FakeReviewEngine()
    client = _client(tmp_path, fake)
    health = client.health()
    assert health["card_review"] == {"capable": True, "active": 0, "limit": 4, "limit_reason": "normal",
                                     "request_worst_s": 10824, "error": None}
    fake.gate_limit = 2
    assert client.health()["card_review"]["limit"] == 2 and client.limits(email=USER)["gate"]["limit"] == 2
    client.run(fre.load("req_sweep.json"), email=USER)
    review = [r for r in fake.requests if r["path"].startswith("/agent/")]
    assert review and all(r["path"].startswith("/agent/card-review/") for r in review)
    assert all(r["authorization"] == f"Bearer {USER_PAT}" for r in review)
    assert [r["route"] for r in fake.calls("run")] == ["run"]
