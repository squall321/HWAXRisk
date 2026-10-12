# review_ops 시험 — M2.md §4.4 오류 어휘의 부류·보류 코드, 해시 흩뿌림 백오프, 보류 재개 간격, 차단기 판정
from __future__ import annotations

import pytest

from app import review_ops as ops

# M2.md §4.4 의 표를 옮겨 적은 것이다(코드에서 뽑지 않는다 — 둘이 같이 틀리면 통과하는 일치 시험을 피한다).
WAIT_CODES = ["review_busy", "engine_busy", "draining", "ctx_unknown"]   # ctx_unknown — 엔진의 503(창 조회 실패 중)
INFRA_CODES = ["llm_unreachable", "llm_timeout", "llm_error",
               "agent_unreachable", "agent_5xx", "agent_timeout", "agent_stream_idle", "portal_unreachable", "portal_5xx",
               "engine_stream_cut", "engine_silent", "restart", "store_write_failed", "busy"]
CONTENT_CODES = ["no_rows", "truncated_empty", "llm_rejected", "cards_unjudged", "review_parse_failed",
                 "body_too_large", "internal_error"]
HOLDS = {
    "llm_misconfigured": "llm_misconfigured",
    "context_overflow": "ctx_too_small", "over_budget": "ctx_too_small", "ctx_too_small": "ctx_too_small",
    "oversize": "ctx_too_small",
    "credential_rejected": "credential", "credential_missing": "credential", "credential_expired": "credential",
    "pat_unavailable": "credential",
    "agent_outdated": "agent_outdated", "unknown_fields": "contract", "rev_mismatch": "contract",
    "denied": "contract", "bad_request": "contract", "empty_unit": "contract", "unsupported_unit_kind": "contract",
    "deck_too_large": "contract",
    # 표 밖 이름의 별칭(RA-10) — 엔진 build_ctx 의 unsupported_kind, m2-wp3b S7 의 review_unsupported·forbidden.
    "unsupported_kind": "contract", "review_unsupported": "agent_outdated", "forbidden": "contract",
}
PACKS = {"card_fetch_failed": (6, "pack_unavailable"), "card_list_failed": (6, "pack_unavailable"),
         "card_list_unstable": (6, "pack_unavailable"), "tools_unavailable": (6, "pack_unavailable"),
         "agent_not_found": (3, "agent_not_found")}


# ---------------------------------------------------------------- 분류표
@pytest.mark.parametrize("code", WAIT_CODES)
def test_wait_codes_count_nothing_and_retry_after_the_given_seconds(code):
    out = ops.classify(code, retry_after_s=45)
    assert (out.klass, out.charge, out.hold_code, out.retry_after_s) == ("wait", False, None, 45)
    assert ops.classify(code).retry_after_s == ops.WAIT_DEFAULT_S == 30          # 값이 없으면 엔진·포털의 기본 30초
    assert ops.classify(code, retry_after_s=0).retry_after_s == 30


@pytest.mark.parametrize("given,expected", [
    (45, 45), (0.4, 1), (1.2, 2), (29.0, 29), ("30", 30), (" 12 ", 12), ("2.5", 3), (1e9, 3600), ("99999", 3600),
    (3600.5, 3600), (0, 30), (-5, 30), ("", 30), ("Wed, 21 Oct 2026 07:28:00 GMT", 30), ("abc", 30), (None, 30),
    (float("nan"), 30), (float("inf"), 30), (True, 30), ([30], 30),
])
def test_retry_after_is_rounded_up_clamped_and_never_throws(given, expected):
    """0.4 는 0 이 되어 대기 없이 관문을 다시 때렸고, 글자(Retry-After 머리)는 TypeError 로 던졌고, 10억 초도 받았다(RA-11)."""
    assert ops.classify("review_busy", retry_after_s=given).retry_after_s == expected


@pytest.mark.parametrize("code", INFRA_CODES)
def test_infra_codes_are_not_charged(code):
    out = ops.classify(code)
    assert (out.code, out.klass, out.charge, out.hold_code, out.fail_code) == (code, "infra", False, None, None)


def test_llm_timeout_is_infra_even_when_the_engine_bit_is_ignored():
    # 설계서끼리 갈린 코드(WP3a 인프라 · WP5a 용량) — M2.md 는 인프라로 친다.
    assert ops.classify("llm_timeout").klass == "infra"


@pytest.mark.parametrize("code", CONTENT_CODES)
def test_content_codes_are_charged_and_fail_with_their_own_code(code):
    out = ops.classify(code)
    assert (out.klass, out.charge, out.fail_code, out.hold_code) == ("content", True, code, None)


@pytest.mark.parametrize("code,hold", sorted(HOLDS.items()))
def test_job_codes_hold_the_job_without_charging_the_cell(code, hold):
    out = ops.classify(code)
    assert (out.klass, out.hold_code, out.charge) == ("job", hold, False)
    assert hold in ops.HOLD_CODES


@pytest.mark.parametrize("code,expected", sorted(PACKS.items()))
def test_pack_codes_retry_that_experts_pack_then_fail_its_cells(code, expected):
    out = ops.classify(code)
    assert (out.klass, out.charge, out.hold_code) == ("pack", False, None)
    assert (out.max_tries, out.fail_code) == expected


def test_human_cancel_counts_nothing():
    out = ops.classify("cancelled")
    assert (out.klass, out.charge, out.hold_code) == ("cancelled", False, None)


def test_unknown_code_is_content_and_keeps_its_text():
    out = ops.classify("brand_new_engine_code")
    assert (out.code, out.klass, out.charge, out.fail_code) == ("brand_new_engine_code", "content", True,
                                                                 "brand_new_engine_code")


def test_app_wall_clock_is_infra_the_first_time_and_content_the_second():
    first = ops.classify("review_timeout")
    second = ops.classify("review_timeout", timeouts_before=1)
    assert (first.klass, first.charge) == ("infra", False)
    assert (second.klass, second.charge, second.fail_code) == ("content", True, "review_timeout")
    assert first.knob == second.knob == "HWAXRISK_REVIEW_CALL_TIMEOUT_S"


def test_knob_from_the_error_frame_wins_and_app_codes_name_their_own():
    assert ops.classify("llm_timeout", knob="DELIB_TIMEOUT_S").knob == "DELIB_TIMEOUT_S"
    assert ops.classify("engine_silent").knob == "HWAXRISK_REVIEW_READ_TIMEOUT_S"
    assert ops.classify("no_rows").knob is None


@pytest.mark.parametrize("status,code,klass", [
    (401, "credential_rejected", "job"), (403, "denied", "job"), (404, "agent_outdated", "job"),
    (409, "rev_mismatch", "job"), (422, "bad_request", "job"), (429, "engine_busy", "wait"),
    (502, "portal_5xx", "infra"), (504, "portal_5xx", "infra"), (418, "http_418", "content"),
])
def test_status_without_a_code_maps_to_the_vocabulary(status, code, klass):
    out = ops.classify(None, http_status=status)
    assert (out.code, out.klass) == (code, klass)


def test_code_beats_status():
    # 포털이 상태와 본문을 그대로 넘기는 502 — 본문의 코드가 이긴다.
    assert ops.classify("card_fetch_failed", http_status=502).klass == "pack"
    assert ops.classify("", http_status=None).code == "unknown"


def test_every_hold_a_code_can_raise_is_in_the_hold_table():
    raised = {ops.classify(code).hold_code for code in HOLDS}
    assert raised <= set(ops.HOLD_CODES)


# ---------------------------------------------------------------- 백오프
def test_backoff_is_deterministic_and_bounded():
    for n in range(1, 40):
        a = ops.backoff_s(n, salt="t1|u-1|mech-a")
        assert a == ops.backoff_s(n, salt="t1|u-1|mech-a")                       # 같은 인자면 같은 값(난수 없음)
        base = min(30 * 2 ** (n - 1), 900)
        assert round(base * 0.8) <= a <= min(round(base * 1.2), 900)
    assert ops.backoff_s(0, salt="x") == 0 and ops.backoff_s(-3, salt="x") == 0


def test_backoff_spreads_across_cells():
    values = {ops.backoff_s(1, salt=f"cell-{i}") for i in range(50)}
    assert len(values) > 5 and min(values) >= 24 and max(values) <= 36


def test_pack_retry_doubles_from_sixty_to_the_cap():
    assert [ops.pack_retry_s(n) for n in range(1, 8)] == [60, 120, 240, 480, 960, 1800, 1800]


# ---------------------------------------------------------------- 보류 코드
def test_hold_table_auto_resume_sets():
    auto = {code for code, rule in ops.HOLD_CODES.items() if rule.auto}
    assert auto == {"llm_outage", "aidh_unreachable", "agent_outdated", "ctx_unknown"}
    assert set(ops.HOLD_CODES) - auto == {"user", "credential", "content_fail_rate", "contract", "ctx_too_small",
                                          "llm_misconfigured"}


def test_hold_delays_step_up_and_repeat_the_last():
    assert [ops.hold_delay_s("llm_outage", n) for n in range(1, 8)] == [300, 600, 1200, 2400, 3600, 3600, 3600]
    assert [ops.hold_delay_s("aidh_unreachable", n) for n in range(1, 4)] == [300, 1800, 1800]
    assert ops.hold_delay_s("agent_outdated", 5) == 300
    assert ops.hold_delay_s("ctx_unknown", 1) is None                            # 시계가 아니라 창 출처로 재개
    assert ops.HOLD_CODES["ctx_unknown"].resume_on == "ctx_source"
    for code in ("user", "credential", "contract", "ctx_too_small", "content_fail_rate", "llm_misconfigured", "없는"):
        assert ops.hold_delay_s(code, 1) is None


# ---------------------------------------------------------------- 차단기
def test_breaker_needs_ten_finished_calls():
    assert ops.breaker_verdict(["infra"] * 9) is None
    assert ops.breaker_verdict(["infra"] * 10) == "llm_outage"


def test_breaker_ignores_waits_cancels_and_unfinished_calls():
    assert ops.breaker_verdict(["wait"] * 20) is None
    assert ops.breaker_verdict(["wait", "cancelled", None] * 20 + ["infra"] * 9) is None
    assert ops.breaker_verdict(["wait"] * 30 + ["infra"] * 10) == "llm_outage"


def test_breaker_reads_only_the_last_twenty():
    assert ops.breaker_verdict(["ok"] * 20 + ["infra"] * 20) is None             # 새것 먼저 — 오래된 실패는 창 밖
    assert ops.breaker_verdict(["infra"] * 10 + ["ok"] * 10 + ["content"] * 20) == "llm_outage"
    assert ops.breaker_verdict(["infra"] * 9 + ["ok"] * 11) is None


def test_breaker_trips_on_content_at_half():
    assert ops.breaker_verdict(["content"] * 10 + ["ok"] * 10) == "content_fail_rate"
    assert ops.breaker_verdict(["content"] * 9 + ["ok"] * 11) is None
    assert ops.breaker_verdict(["content"] * 6 + ["ok"] * 6) == "content_fail_rate"     # 12건 중 절반
    assert ops.breaker_verdict(["infra"] * 10 + ["content"] * 10) == "llm_outage"      # 인프라가 먼저다
