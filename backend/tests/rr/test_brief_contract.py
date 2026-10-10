# 브리프 모양 계약(WP5b C2 가드 C) — 생산자가 낸 diff·좌석을 브리프가 실제로 읽는지 본다(재현 시험 — WP1 S6·S7·S8 이 고쳤다)
"""입력은 전부 공장(`tests/factories.py`)을 거친 생산자 산출이다 — 기존 어댑터 픽스처 셋에 변경을 준 작은 다건 쌍,
명명 치수 정의 1건, 편성기가 낸 Tier A 좌석. 손으로 쓴 diff_json·좌석 dict 는 없다(규칙 R1).

시험 다섯은 7248651 에서 실패했다(2.3절 실례 #1·#2). `xfail(strict=True, raises=AssertionError)` 로 넣고 WP1 의 수리 커밋이
표식을 지웠다 — 고쳐지면 xpass 가 strict 로 깨져 표식을 지우게 만든다. 공장·조립은 모듈 픽스처라 그쪽 예외는 xfail 이
아니라 error 로 뜬다(반대 검토 P-02). 픽스처의 전제 확인은 AssertionError 가 아니라 RuntimeError 로 낸다 — xfail 은
setup 단계의 AssertionError 도 삼킨다.
"""
from __future__ import annotations

import copy
import re

import pytest

from app import brief, render
from app.risk_store import RiskStore
from tests import factories

# 값을 못 읽었을 때의 자리표시 줄 — 시험 쪽 정규식으로 뽑는다(브리프에 자리표시 등록 상수가 생기면 그것으로 바꾼다).
PLACEHOLDER = re.compile(r"\[[^\]\n]*(?:없음|부재)[^\]\n]*\]")
# 이 타깃(첫 심사 · 과제 하나 · 제품 연결 없음)에서 나와도 되는 자리표시의 머리(' — ' 앞)와 그 까닭.
EXPECTED_PLACEHOLDERS = {
    "[선행 등록부 없음": "첫 심사다 — 이 과제의 계보·유사 과제 등록부가 없다",
    "[기각된 선례 없음": "첫 심사다 — 기각된 선례가 없다",
    "[선례 없음": "코퍼스에 이 조합이 처음이다",
    "[유사 과제 성격 진술 없음": "코퍼스에 과제가 하나뿐이다",
    "[필드·문헌 근거 없음": "과제에 제품 연결(product_code)을 등록하지 않았다",
    "[<좌석>: 이전 발언 없음": "첫 심사다 — 좌석마다 이전 발언이 없다(E7 은 좌석 키를 줄 머리에 적는다)",
}
SEAT_PLACEHOLDER = re.compile(r"^\[[a-z0-9-]+: 이전 발언 없음$")
DIM_NAME = "plate1_t"


def _revise(results: list[dict]) -> list[dict]:
    """개정본 — 두께 감소·증가, 설계 무관 요소 수, 계면 간극·관통, 결과 지표 증감(어댑터 결과 수준에서만 바꾼다)."""
    out = copy.deepcopy(results)
    mcad, dyna, result = out
    by_label = {n["label"]: n for n in mcad["nodes"]}
    by_label["PLATE_1"]["attrs"]["min_dim"] = 0.84               # −30%
    by_label["PLATE_2"]["attrs"]["min_dim"] = 1.2                # +20%
    dyna["nodes"][0]["attrs"]["n_elems"] = 11250                 # +125%, 설계 무관
    tied, interference = mcad["edges"][0], mcad["edges"][1]
    tied["attrs"]["min_gap"] = 0.018                             # 0 에서 생긴 간극
    interference["attrs"]["penetration_depth"] = 0.02            # −60%(한쪽이 하한이 아니라 비교된다)
    interference["attrs"]["penetration_depth_is_lower_bound"] = False
    risk = result["results"]["part_risk"]
    risk[0]["worst_stress"]["value"] = 185.1                     # −20%
    risk[0]["worst_g"] = 100.0
    risk[1]["worst_stress"]["value"] = 150.0
    risk[1]["worst_disp"] = 0.3
    return out


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(f"픽스처 전제가 깨졌다 — {message}")


@pytest.fixture(scope="module")
def contract(tmp_path_factory):
    store = RiskStore(tmp_path_factory.mktemp("brief-contract") / "risk_review.db")
    store.open()
    store.migrate()
    try:
        project_id = factories.make_project(store)
        factories.make_dim(store, project_id, DIM_NAME, "node[asm=a_stack/stack_asm/plate_1].attrs.min_dim")
        base_results = factories.fixture_adapter_results()
        base = factories.make_snapshot(store, project_id, base_results, label="DV1")
        target = factories.make_snapshot(store, project_id, _revise(base_results), label="DV2",
                                         captured_at=factories.CAPTURED_AT + 86400)
        diff = factories.make_diff(store, base["snapshot_id"], target["snapshot_id"])
        target_key = factories.make_target(store, "diff", diff["diff_id"], agents=factories.agents())
        panel = factories.plan_panel(store, target_key, "A")
        _require(panel is not None and len(panel["seats"]) >= 2, "편성기가 좌석을 내지 않았다")
        built = brief.build_brief(store, target_key, seats=panel["seats"], panel_id=panel["id"],
                                  owner_sub=factories.OWNER)
        yield {"diff": diff, "seat_keys": [s["key"] for s in panel["seats"]],
               "items": dict(zip(built["keys"], (e["result"] for e in built["evidence"]))),
               "text": "\n".join(e["result"] for e in built["evidence"])}
    finally:
        store.close()


def _number_in(text: str, value: float) -> bool:
    return any(form in text for form in {f"{value:g}", f"{value}", f"{value:.1f}", f"{value:.3f}"})


def test_e7_reads_the_seats_the_planner_wrote(contract):
    """WP1 S8(R-14) 이 고친 것 — brief._item_e7 이 좌석 dict 의 agent_key 를 읽는데 편성기는 key 로 쓴다."""
    e7 = contract["items"]["E7"]
    assert "[착석 좌석 없음]" not in e7
    assert [k for k in contract["seat_keys"] if k not in e7] == []


def test_e3_carries_every_changed_named_dimension(contract):
    """WP1 S7(R-10) 이 고친 것 — E3 이 diff_json 최상위 dims_delta 를 base·target 키로 읽는데 생산자는 parametric 아래
    before·after 로 쓴다."""
    changed = [d for d in contract["diff"]["parametric"]["dims_delta"] if d["flag"] == "changed"]
    _require(bool(changed), "명명 치수 변화가 없다")
    e3 = contract["items"]["E3"]
    assert [d["name"] for d in changed if d["name"] not in e3] == []
    for d in changed:
        assert _number_in(e3, d["before"]) and _number_in(e3, d["after"]), (d, e3)


def test_e4_carries_every_changed_result_metric(contract):
    """WP1 S7(R-12) 이 고친 것 — E4 가 diff_json 최상위 result_delta 를 name 키로 읽는데 생산자는 parametric 아래
    dn·metric·before·after 로 쓴다.

    값은 생산자가 쓴 정규 표기의 자릿수로 견준다 — 응력은 정수로 표기한다(§2.11). 줄 몸통이 정규 표기라야 좌석의 인용이
    대조를 통과한다(R-40). 주어(dn)는 브리프가 부품 이름으로 바꾸므로 지표 이후만 본다.
    """
    changed = [r for r in contract["diff"]["parametric"]["result_delta"] if r["flag"] == "changed"]
    _require(len(changed) >= 2, "결과 지표 변화가 둘 미만이다")
    e4 = contract["items"]["E4"]
    for r in changed:
        shown = render.split_trailing_refs(r["text"])[0].split(" ", 1)[1]
        assert r["metric"] in e4 and shown in e4, (r, e4)


def test_e2_keeps_the_largest_decrease(contract):
    """WP1 S6(R-6) 이 고친 것 — E2 가 부호 있는 크기순이라 감소가 뒤로 밀려 상한에서 잘렸다."""
    events = contract["diff"]["semantic"]["events"]
    decreases = [e for e in events if e["design_relevant"] and e["magnitude"]["rel"] is not None
                 and (e["magnitude"]["value"] or 0) < 0]
    _require(len(decreases) >= 2 and len(events) >= 10, "감소 변화·이벤트 수가 시험에 모자란다")
    top = max(decreases, key=lambda e: abs(e["magnitude"]["rel"]))
    assert top["cid"] in contract["items"]["E2"], top


def test_only_registered_placeholders_appear(contract):
    """WP1 S7·S8 이 고친 것 — 값이 있는데도 '[명명 치수 없음 …]'·'[dyna_result 부재]'·'[착석 좌석 없음]' 이 나왔다."""
    heads = {p[:-1].split(" — ")[0] for p in PLACEHOLDER.findall(contract["text"])}
    heads = {"[<좌석>: 이전 발언 없음" if SEAT_PLACEHOLDER.match(h) else h for h in heads}
    assert sorted(heads - set(EXPECTED_PLACEHOLDERS)) == []
    assert sorted(set(EXPECTED_PLACEHOLDERS) - heads) == []
