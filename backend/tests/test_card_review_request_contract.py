# 카드 대조 요청 방향 계약(WP5b C7) — 실제 단위·실제 팩으로 지은 run 본문을 에이전트 서버의 검증기(validate_run_request)가 서브프로세스에서 받는다
"""앱이 짓는 run 본문이 엔진 요청 모델(안쪽 항목까지 선언 밖 칸은 422 unknown_fields)을 지나는지 엔진 자신의 코드로 본다.

- 단위는 생산자 그대로다 — 합성 다건 변경 타깃(`make_diff_target`)을 flow='cells' 로 열어 세운 검토 단위의 `units.review_payload`
  (대상 수준 결측 `missing[{kind, note}]`·전문가 입력 결손 `input_gaps` 포함), 훑기 목록은 `units.manifest_items` 다.
- 카드는 엔진이 지은 계약 예제 팩(`pack_ok.json` · `pack_empty.json`)을 `cardpack.view_of` 로 얼린 것이고, 본문은
  `engine_client.run_body` 가 짓는다(검토 루프가 쓸 그 함수).
- 검증은 형제 리포의 `card_review.validate_run_request(body, limits)` 를 형제 venv 로 서브프로세스에서 부른다(두 리포 모두 최상위
  모듈 이름이 겹칠 수 있고 엔진 의존은 이 venv 에 없다). 형제가 없으면 건너뛰고, 형제는 있는데 venv·모듈·이름을 못 찾으면
  건너뛰지 않고 실패한다(P-22).
- 같은 호출에서 엔진 요청 모델의 칸 집합을 받아 가짜 엔진(`tests/synth/fake_review_engine.py`)의 모양 표와 견준다 — 가짜가 엔진보다
  너그러우면 검토 루프의 요청 버그가 가짜 위에서 초록이 된다.
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from pathlib import Path

import pytest

from app import cardpack, config, engine_client, review_verify, routes, taxonomy, unit_live, units
from tests import factories
from tests.conftest import FIXTURES_DIR, REPO_ROOT
from tests.synth import fake_review_engine as fre

CONTRACT = FIXTURES_DIR / "card_review" / "contract"
ENGINE_CONTRACT = Path("tests") / "fixtures" / "card_review" / "contract"

# 형제 리포에서 돈다 — 본문 묶음과 limits 경로를 stdin 으로 받아 장면마다 문제 목록을, 요청 모델의 칸 집합을 함께 돌려준다.
_ENGINE_VALIDATE = """
import json, sys
import card_review as cr
job = json.load(sys.stdin)
lim = json.load(open(job["limits"], encoding="utf-8"))
out = {"problems": {name: cr.validate_run_request(body, lim) for name, body in job["bodies"].items()}}
models = {
    "run": {"": cr.RunRequest, "expert": cr.RunExpert, "digest": cr.DigestItem, "unit": cr.RunUnit,
            "unit.lines": cr.RunLine, "unit.context": cr.RunLine, "unit.evidence": cr.RunLine,
            "unit.missing": cr.MissingItem, "manifest": cr.RunManifestItem, "extra": cr.RunExtra,
            "extra.domains": cr.DomainItem, "extra.mechanisms": cr.MechItem, "extra.known": cr.KnownItem,
            "extra.missing": cr.MissingItem, "extra.search": cr.SearchSpec, "summary": cr.SummaryInput,
            "summary.scope": cr.SummaryScope, "summary.rows": cr.SummaryRow, "summary.blocks": cr.SummaryBlock,
            "expect": cr.RunExpect},
    "plan": {"": cr.PlanRequest, "cards": cr.PlanCard, "units": cr.PlanUnit, "expect": cr.Expect},
    "pack": {"": cr.PackRequest},
}
out["shapes"] = {route: {k: sorted(m.model_fields) for k, m in table.items()} for route, table in models.items()}
print(json.dumps(out, ensure_ascii=False))
"""


def _engine_repo() -> Path:
    return Path(os.environ.get("HWAX_AGENT_SERVER_REPO") or REPO_ROOT.parent / "HWAXAgentServer")


def _engine_validate(bodies: dict[str, dict]) -> dict:
    repo = _engine_repo()
    if not repo.is_dir():
        pytest.skip(f"엔진 리포가 곁에 없다(HWAX_AGENT_SERVER_REPO 또는 ../HWAXAgentServer) — {repo}")
    python = repo / ".venv" / "bin" / "python"
    if not python.exists():
        pytest.fail(f"엔진 리포는 곁에 있는데 그 venv 가 없다 — {python}. 엔진 리포에서 venv 를 만든다(건너뛰지 않는다 — P-22)")
    job = {"limits": str(repo / ENGINE_CONTRACT / "limits_1m.json"), "bodies": bodies}
    r = subprocess.run([str(python), "-c", _ENGINE_VALIDATE], input=json.dumps(job, ensure_ascii=False), cwd=repo,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, (f"엔진 검증기를 부르지 못했다(rc={r.returncode}) — 형제 리포의 card_review 모델·함수 이름이 바뀌었으면 이"
                               f" 시험을 같이 고친다: {r.stderr.strip()[-2000:]}")
    return json.loads(r.stdout)


@pytest.fixture
def cells(risk_store, monkeypatch, tmp_path):
    """합성 40건 변경 타깃을 flow='cells' 로 연다 — 로스터 동결과 검토 단위 빌드는 실제 입구(routes.create_target)가 한다."""
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, data_dir=tmp_path, risk_review_enabled=True))
    synth = factories.make_diff_target(risk_store, 40, open_target=False)
    key = factories.make_target(risk_store, "diff", synth.diff_id, agents=factories.agents(("mech", "pcb", "sim"), 1),
                                flow="cells")
    return risk_store, key


def _bodies(store, target_key: str) -> dict[str, dict]:
    limits = fre.load("limits_1m.json")
    pack = fre.load("pack_ok.json")
    reviewable = units.load_units(store, target_key)
    assert reviewable, "검토 단위가 서지 않았다"
    bodies: dict[str, dict] = {}
    for agent in ("mech-syn-0", "pcb-syn-0"):
        frozen = cardpack.view_of({**pack, "agent_key": agent})
        checkable, background = list(frozen.checkable), list(frozen.background)

        def body(kind: str, unit_id: str | None, **kw) -> dict:
            # 검토 루프가 run 에 싣는 기대 판 — 그 종류의 prompt_rev 와 그 종류의 창 판(RB3-6, review_runner._Session._expect)
            expect = {"prompt_rev": limits["prompt_rev"][kind], "limits_rev_kind": limits["limits_rev_by_kind"][kind]}
            unit = units.review_payload(store, target_key, unit_id, agent) if unit_id else None
            return engine_client.run_body(kind, target_key=target_key, pack=frozen, unit=unit, expect=expect, **kw)

        for unit in reviewable:
            uid = unit["unit_id"]
            bodies[f"{agent}/verdict.fwd/{uid}"] = body("verdict", uid, variant="fwd", cards=checkable[:8],
                                                        digest=background)
            bodies[f"{agent}/verdict.rev/{uid}"] = body("verdict", uid, variant="rev", cards=checkable[:8],
                                                        digest=background)
            bodies[f"{agent}/verdict.solo/{uid}"] = body("verdict", uid, variant="solo", cards=checkable[:1])
            # 걸린 별칭만 실은 rev(재설계 M3 C3-9) — 나머지 묶음 카드는 제목 목록으로 내린다
            bodies[f"{agent}/verdict.rev.flagged/{uid}"] = review_verify.dual_plan_flagged(
                bodies[f"{agent}/verdict.fwd/{uid}"], checkable[1:3])["rev"]
            bodies[f"{agent}/offcard/{uid}"] = body(
                "offcard", uid, cards=background, digest=list(frozen.order),
                known=[{"alias": "K01", "judgement": "FAIL", "why": "접착폭 하한 밑", "record_id": "x", "applies": "yes"}])
        bodies[f"{agent}/sweep"] = body("sweep", None, cards=list(frozen.order),
                                        manifest=units.manifest_items(store, target_key))
        if agent == "pcb-syn-0":
            # 입력 결손 전문가(재설계 M3 C3-3) — 단위마다 입력 결손 호출(카드 전부 · 전 카드 제목 · 다시 묻기의 known)과 결측 블록을 실은
            # 훑기(cr-sweep-2 의 extra.missing). 검토 루프가 짓는 그 모양이다.
            for unit in reviewable:
                bodies[f"{agent}/noinput/{unit['unit_id']}"] = body(
                    "noinput", unit["unit_id"], cards=list(frozen.order), digest=list(frozen.order),
                    known=[{"alias": "Q01", "judgement": "yes", "why": "보드 근접 계면 간극 축소"}])
            missing = units.review_payload(store, target_key, reviewable[0]["unit_id"], agent)["missing"]
            bodies[f"{agent}/sweep.missing"] = body("sweep", None, cards=list(frozen.order),
                                                    manifest=units.manifest_items(store, target_key), missing=missing)
    empty = cardpack.view_of({**fre.load("pack_empty.json"), "agent_key": "sim-syn-0"})
    bodies["sim-syn-0/offcard.role_only"] = engine_client.run_body(
        "offcard", target_key=target_key, pack=empty,
        unit=units.review_payload(store, target_key, reviewable[0]["unit_id"], "sim-syn-0"))
    # 근거 꾸러미 실호출(B 층 — C3-12)이 붙은 단위 — 가짜 게이트웨이 앞에서 실제 ensure 가 얼린 줄(tool:b-…)이 unit.evidence 끝에 선다
    from tests.test_unit_live import Gateway

    unit_live.seed(store, target_key, enabled=True)
    client = Gateway().client()
    try:
        unit_live.ensure(store, None, target_key, {"kind": "user", "email": factories.OWNER, "pat": "pat-contract"},
                         http_client=client)
    finally:
        client.close()
    live = next(u["unit_id"] for u in reviewable if (unit_live.lines_for(store, target_key, u["unit_id"]) or {}).get("lines"))
    frozen = cardpack.view_of({**pack, "agent_key": "mech-syn-0"})
    bodies["mech-syn-0/verdict.fwd.live"] = engine_client.run_body(
        "verdict", target_key=target_key, pack=frozen, variant="fwd", cards=list(frozen.checkable)[:8],
        unit=units.review_payload(store, target_key, live, "mech-syn-0"),
        expect={"prompt_rev": limits["prompt_rev"]["verdict"], "limits_rev_kind": limits["limits_rev_by_kind"]["verdict"]})
    return bodies


def test_run_bodies_built_from_real_units_and_packs_pass_the_engines_validator(cells):
    store, key = cells
    bodies = _bodies(store, key)
    # 생산자가 실제로 결측·입력 결손을 싣는 판이어야 시험이 그 칸을 덮는다(합성 쌍에는 회로 소스가 없다).
    pcb = next(b for name, b in bodies.items() if name.startswith("pcb-syn-0/verdict.fwd/"))
    assert pcb["unit"]["input_gaps"] == ["ecad_absent"] and pcb["unit"]["missing"][0]["kind"] == "ecad"
    assert pcb["unit"]["missing"][0]["note"].endswith("이 영역이 볼 것 — 보드 고정점·지지 스팬·보드 근접 계면.")
    assert bodies["pcb-syn-0/sweep.missing"]["extra"]["missing"] == [
        {"kind": m["kind"], "note": m["note"]} for m in pcb["unit"]["missing"]]
    assert "missing" not in bodies["mech-syn-0/sweep"]["extra"]          # 결손이 아닌 전문가의 훑기에는 싣지 않는다
    assert pcb["extra"]["domains"][0] == {"key": "xd", "label": "XD(외관·조립 설계)"}
    assert len(pcb["extra"]["domains"]) == len(config.settings.risk_roster_domains) == 15
    assert pcb["extra"]["known"] == [] and len(pcb["extra"]["mechanisms"]) == 52        # 택소노미 1.2(재설계 M3 D-34)
    assert bodies["mech-syn-0/verdict.fwd.live"]["unit"]["evidence"][-1]["ref"].startswith("tool:b-")
    # 대조군 — 엔진 자신의 요청 예제는 지나고, 안쪽 칸 이름이 틀린 것은 걸린다(검증기가 헛돌지 않는다).
    control = fre.load("req_verdict_fwd.json")
    bodies["_control_ok"] = control
    bodies["_control_bad"] = {**control, "extra": {"domains": [{"code": "mech", "label": "기구"}]}}
    # 택소노미 행을 그대로 실으면 걸린다 — run_body 가 {key, label}·{code, label} 로 짓는 까닭이다.
    axes = taxonomy.load_taxonomy()["axes"]
    bodies["_control_taxonomy"] = {**control, "extra": {"domains": axes["domain"][:1], "mechanisms": axes["mechanism"][:1]}}

    out = _engine_validate(bodies)
    problems = out["problems"]
    assert problems.pop("_control_ok") == []
    assert [(p["status"], p["code"], p["fields"]) for p in problems.pop("_control_bad")] == \
        [(422, "unknown_fields", ["extra.domains.0.code"])]
    (raw,) = problems.pop("_control_taxonomy")
    assert raw["code"] == "unknown_fields" and {"extra.domains.0.code", "extra.domains.0.ecad_dependent",
                                                 "extra.mechanisms.0.description"} <= set(raw["fields"])
    rejected = {name: found for name, found in problems.items() if found}
    assert rejected == {}, f"엔진이 앱의 run 본문을 거절한다(계약 버그 — 앱 쪽을 고친다): {json.dumps(rejected, ensure_ascii=False)[:3000]}"
    assert len(problems) == len(bodies) - 3

    # 가짜 엔진의 모양 표가 엔진 요청 모델의 칸과 같다(선언 밖 칸을 같은 경로에서 거절한다).
    fake = {"run": fre.RUN_SHAPE, "plan": fre.PLAN_SHAPE, "pack": fre.PACK_SHAPE}
    assert {route: {k: sorted(v) for k, v in table.items()} for route, table in fake.items()} == out["shapes"]


def test_the_same_bodies_pass_the_fake_engine(cells, tmp_path):
    """가짜 엔진도 같은 본문을 받아 결과를 낸다 — 검토 루프 시험(S8)이 이 본문으로 돈다."""
    from types import SimpleNamespace

    from app import common, identity

    store, key = cells
    fake = fre.FakeReviewEngine()
    row = {"portal_pat": identity.encrypt_pat("pat-u").decode("ascii"), "pat_email": "u@example.com",
           "pat_exp": common.now_epoch() + 30 * 86400, "revoked_at": None}
    client = engine_client.PortalReviewEngine(
        SimpleNamespace(get_credential=lambda sub: row if sub == "u@example.com" else None),
        SimpleNamespace(data_dir=tmp_path, portal_base="http://portal.test"), transport=fake.transport)
    for name, body in _bodies(store, key).items():
        result = client.run(body, email="u@example.com")
        assert result["kind"] == body["kind"] and result["missing"] == [], name
        if body["kind"] == "verdict":
            assert [r["k"] for r in result["rows"] if r["t"] == "v"] == \
                [c["alias"] for c in body["cards"]][::-1 if body["variant"] == "rev" else 1], name
