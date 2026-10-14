# 검토 루프 시험대(시험 전용) — 실제 단위의 카드 대조 대상·사용자 PAT·검토 잡과, 가짜 엔진을 꽂은 ReviewLoop 를 주입한 시계로 돌린다
"""검토 루프(m2-wp3b S8)를 끝까지 돌려 셀·판정·호출 원장을 만드는 생산자다 — 손으로 쓴 원장 행이 없다(PLAN 9절).

- 대상은 합성 40건 변경 쌍 → 실제 캡처·diff → 라우트(`create_target(flow='cells')`)가 세운 단위다. 단위 크기 손잡이(`CAPS`)를
  키워 단위를 다섯으로 줄인다(시험 시간).
- 팩은 엔진 계약 예제(`pack_ok`·`pack_empty`)에서 `fake_review_engine.derive_pack` 으로 전문가만 바꿔 짓는다.
- 엔진은 실제 `engine_client.PortalReviewEngine` 에 가짜 엔진의 MockTransport 를 꽂은 것이다(가짜는 tests/synth 한 벌 — D-15).
  데이터 디렉터리의 secrets.env 에 서비스 PAT 를 두어 그것이 어떤 요청에도 실리지 않는지 시험이 본다(사용자 결정 3).
- 시계는 정수 초를 손으로 민다. 루프의 기다림은 1ms 로 줄인다(기다림의 '초' 는 셈으로만 지나간다).
"""
from __future__ import annotations

import dataclasses
import json
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app import cardpack, config, engine_client, identity, review_runner, routes
from app.common import now_epoch
from tests import factories
from tests.synth import fake_review_engine as fre

OWNER = factories.OWNER
SEAL = "mech-test-seal"                 # 엔진 계약 예제 팩의 전문가 — 그 팩 그대로
BACKGROUND_ONLY = "sim-syn-0"           # 배경 카드뿐(카드 대조 묶음 0개)
ZERO_CARDS = "sim-syn-1"                # 0장(역할만으로 카드 밖 호출)
SERVICE_PAT = "svc-pat-must-never-be-sent"
# 입력 결손이 없는 로스터(합성 쌍에는 회로 소스가 없다 — M2 는 ECAD 에 기대는 영역을 범위에 받지 않는다).
ROSTER: tuple[dict, ...] = (
    {"key": SEAL, "domain": "mech", "relevance": 0.99}, {"key": "mech-syn-0", "domain": "mech", "relevance": 0.9},
    {"key": BACKGROUND_ONLY, "domain": "sim", "relevance": 0.9}, {"key": ZERO_CARDS, "domain": "sim", "relevance": 0.8},
    {"key": "xd-syn-0", "domain": "xd", "relevance": 0.9}, {"key": "xd-syn-1", "domain": "xd", "relevance": 0.8},
)
CARD_EXPERTS: tuple[str, ...] = (SEAL, "mech-syn-0", "xd-syn-0", "xd-syn-1")
CAPS = {"risk_unit_target_lines": 60, "risk_unit_max_lines": 120, "risk_units_small_lines": 40}   # 합성 40건 → 단위 5개


def configure(monkeypatch, store, tmp_path, **overrides: Any) -> None:
    """설정(데이터 디렉터리·새 흐름 스위치·단위 크기·검토 손잡이)과 라우트 저장소. secrets.env 에는 서비스 PAT 를 둔다.

    이중 판정은 M2 동작(`all` — 묶음 전체 rev)이 기본이다 — 호출 차례·수를 세는 M2 시험이 그 위에 서 있다. 걸린 것만 이중
    판정(운영 기본 `flagged`, 재설계 M3 C3-9)은 그것을 보는 시험이 `risk_review_dual='flagged'` 로 켠다."""
    monkeypatch.setattr(routes, "get_store", lambda: store)
    values = {"data_dir": tmp_path, "risk_review_enabled": True, "risk_review_concurrency": 4, "risk_review_dual": "all",
              **CAPS, **overrides}
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, **values))
    secrets = tmp_path / "secrets.env"
    secrets.write_text(f"HWAXRISK_PORTAL_PAT={SERVICE_PAT}\n", encoding="utf-8")
    secrets.chmod(0o600)
    cardpack.clear_cache()


def packs(roster: Sequence[Mapping[str, Any]] = ROSTER) -> dict[str, dict]:
    """전문가마다 팩 — SEAL 은 계약 예제 그대로, 배경뿐·0장 전문가는 그 모양으로, 나머지는 같은 카드에 전문가만 바꾼 것."""
    ok, empty = fre.load("pack_ok.json"), fre.load("pack_empty.json")
    out: dict[str, dict] = {}
    for row in roster:
        key = str(row["key"])
        if key == SEAL:
            out[key] = ok
        elif key == BACKGROUND_ONLY:
            out[key] = fre.derive_pack(ok, key, name="배경 카드뿐", domain=row["domain"], keep="background")
        elif key == ZERO_CARDS:
            out[key] = fre.derive_pack(empty, key, name="카드 0장", domain=row["domain"], keep="none")
        else:
            out[key] = fre.derive_pack(ok, key, name=key, domain=row["domain"])
    return out


def target(store, roster: Sequence[Mapping[str, Any]] = ROSTER, *, seed: int | None = None) -> str:
    """카드 대조 대상(flow='cells' — 단위까지)."""
    synth = factories.make_diff_target(store, 40, seed=seed, open_target=False)
    return routes.create_target(routes.TargetBody(kind="diff", ref_id=synth.diff_id, consent=True, flow="cells",
                                                  agents=[dict(r) for r in roster]),
                                ident=factories.ident(OWNER))["target_key"]


def pat(store, email: str = OWNER, *, life_s: int = 30 * 86400) -> None:
    """웹 설정 화면이 남기는 것과 같은 자격 행(Fernet 암호문)."""
    store.upsert_credential(email, identity.encrypt_pat(f"pat-{email}").decode("ascii"), "sub", email, "[]",
                            now_epoch() + life_s)


def job(store, key: str, scope: Mapping[str, Any] | None = None) -> str:
    """검토 잡(사용자 PAT·동의) — 잡 id."""
    pat(store)
    return review_runner.create_review_job(store, key, owner_sub=OWNER, requester_sub=OWNER, scope=scope, consent=True,
                                           consent_source="web", settings=config.settings)["job_id"]


def state(store, job_id: str) -> str:
    return str(store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"])


def job_row(store, job_id: str) -> dict:
    return dict(store.query_one("SELECT * FROM rr_jobs WHERE id = ?", (job_id,)))


def progress(store, job_id: str) -> dict:
    return json.loads(job_row(store, job_id)["progress_json"] or "{}")


class Clock:
    """손으로 미는 시계(정수 초)."""

    def __init__(self, start: int | None = None) -> None:
        self.t = int(now_epoch() if start is None else start)

    def __call__(self) -> int:
        return self.t

    def advance(self, seconds: int) -> None:
        self.t += int(seconds)


class Rig:
    """가짜 엔진을 꽂은 ReviewLoop 하나 — `tick()` 은 틱 한 번 뒤 워커가 끝날 때까지 기다린다."""

    def __init__(self, store, fake: fre.FakeReviewEngine, *, clock: Clock | None = None, boot_id: str = "boot-a") -> None:
        self.store = store
        self.fake = fake
        self.clock = clock or Clock()
        self.stop = threading.Event()
        self.engine = engine_client.PortalReviewEngine(store, config.settings, transport=fake.transport)
        self.loop = review_runner.ReviewLoop(store, config.settings, self.engine, stop=self.stop, clock=self.clock,
                                             pause=lambda seconds: self.stop.wait(0.001), boot_id=boot_id, poll_s=0)

    def tick(self, *, wait: bool = True) -> dict:
        out = self.loop.tick()
        if wait:
            self.loop.join(60)
        return out

    def run(self, until: Callable[[], bool], *, step: int = 61, ticks: int = 400) -> int:
        """`until()` 이 참이 될 때까지 틱 → 시계 밀기. 쓴 틱 수."""
        for n in range(1, ticks + 1):
            self.tick()
            if until():
                return n
            self.clock.advance(step)
        raise AssertionError(f"{ticks}틱 안에 끝나지 않았다")

    def finish(self, job_id: str, **kwargs: Any) -> int:
        return self.run(lambda: state(self.store, job_id) in ("completed", "paused", "cancelled", "failed"), **kwargs)


def wait_for(predicate: Callable[[], bool], timeout_s: float = 20.0) -> None:
    """워커 스레드가 어느 지점(가짜 엔진의 run 차례 따위)에 닿기를 실제 시간으로 기다린다."""
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("기다린 지점에 닿지 않았다")


def planned_calls(store, key: str, job_id: str) -> int:
    """머리에 얼린 계획으로 센 호출 수(걸림·재질의가 없을 때) — 전문가마다 훑기(묶음 × 목록 쪽) + 셀마다 (fwd·rev × 점검 묶음 + 카드 밖)."""
    total = 0
    for head in store.query("SELECT agent_key, card_basis, plan_json FROM rr_expert_reports WHERE target_key = ? AND run_id = ?",
                            (key, job_id)):
        plan = json.loads(head["plan_json"])["plan"]
        cells = store.query_one("SELECT COUNT(*) AS n FROM rr_review_cells WHERE target_key = ? AND agent_key = ? AND run_id = ?",
                                (key, head["agent_key"], job_id))["n"]
        sweep = (len(plan["sweep_decks"]) * len(plan["manifest_pages"])
                 if head["card_basis"] in (cardpack.CARD_BASIS_CARDS, cardpack.CARD_BASIS_BACKGROUND) else 0)
        verdict = 2 * len(plan["verdict_decks"]) if head["card_basis"] == cardpack.CARD_BASIS_CARDS else 0
        total += sweep + cells * (verdict + 1)
    return total
