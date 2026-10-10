# 옛 타깃 회귀(WP5b C0) — 7248651 에서 얼린 스키마 v2 DB 를 지금 코드로 열어 옛 응답·planned 패널·queued 잡이 그대로 도는지 본다
"""얼린 DB 와 골든은 `tests/rr/legacy_build.py` 가 `7248651` 코드로 만들었다(다시 만드는 법은 그 파일 머리말).

골든은 통짜가 아니라 불변 사영이다 — 키가 더해지는 것은 통과하고 있던 키의 값이 달라지면 실패한다.
재설계가 그 값을 일부러 바꾸는 커밋은 골든의 그 칸을 고치고 `tests/fixtures/legacy/CHANGES.md` 에 까닭을 적는다.
"""
from __future__ import annotations

import asyncio
import dataclasses
import gzip
import json
import re
import shutil
import sqlite3
from pathlib import Path

import httpx
import pytest

from app import config, mcp_server, planner, registry, routes, runner
from app.risk_store import MIGRATIONS, RiskStore
from tests.rr import legacy_build as legacy

MANIFEST = json.loads((legacy.LEGACY_DIR / "manifest.json").read_text(encoding="utf-8"))
OWNER = MANIFEST["owner"]


def _thaw(directory: Path) -> Path:
    db = directory / "risk_review.db"
    with gzip.open(legacy.LEGACY_DIR / legacy.DB_GZ, "rb") as src, open(db, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return db


@pytest.fixture
def no_network(monkeypatch):
    """러너·브리프가 게이트웨이를 부르면 연결 오류로 답한다 — 시험이 dev 박스의 실 게이트웨이에 닿지 않게."""
    def _refused(*args, **_kwargs):
        raise httpx.ConnectError("시험은 외부를 부르지 않는다.", request=args[-1])

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _refused)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _refused)


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """얼린 DB 의 사본을 지금 코드로 열고 이행한 저장소. 라우트도 이 저장소를 본다."""
    store = RiskStore(_thaw(tmp_path))
    store.open()
    store.migrate()
    monkeypatch.setattr(routes, "get_store", lambda: store)
    yield store
    store.close()


# ---------------------------------------------------------------- ① 이행
def test_the_frozen_db_migrates_and_leaves_a_pre_migrate_copy(tmp_path):
    db = _thaw(tmp_path)
    raw = sqlite3.connect(db)
    frozen_version = raw.execute("PRAGMA user_version").fetchone()[0]
    raw.close()
    assert frozen_version == MANIFEST["schema_version"] == legacy.FROZEN_SCHEMA

    store = RiskStore(db)
    store.open()
    try:
        assert store.migrate() == MIGRATIONS[-1][0]
        assert store.query_one("SELECT COUNT(*) AS n FROM rr_targets")["n"] == len(legacy.ROLES)
    finally:
        store.close()
    # 적용할 버전이 있었으면 적용 직전 사본이 남는다(그 사본은 옛 버전이다). 얼린 시점의 코드에서는 적용할 것이 없다.
    copies = sorted(tmp_path.glob("risk_review.db.pre-migrate-*"))
    assert bool(copies) == (frozen_version < MIGRATIONS[-1][0])
    for copy in copies:
        raw = sqlite3.connect(copy)
        assert raw.execute("PRAGMA user_version").fetchone()[0] == frozen_version
        raw.close()


# ---------------------------------------------------------------- ② 옛 응답 넷
@pytest.mark.parametrize("role", legacy.ROLES)
def test_old_responses_still_cover_the_golden(frozen, role):
    golden = json.loads((legacy.LEGACY_DIR / "golden" / f"{role}.json").read_text(encoding="utf-8"))
    current = legacy.golden_for(frozen, routes, registry, MANIFEST["targets"][role]["target_key"])
    assert legacy.covers(golden, current) == []


def test_covers_flags_a_changed_value_but_not_an_added_key():
    """사영 비교가 실제로 찾는다 — 0건을 훑고 통과하는 비교는 아무것도 지키지 않는다."""
    golden = {"level": "C0", "rows": [{"k": 1}], "nested": {"a": 1}}
    assert legacy.covers(golden, {"level": "C0", "rows": [{"k": 1, "new": 2}], "nested": {"a": 1, "b": 2},
                                  "added": True}) == []
    assert legacy.covers(golden, {"level": "C1", "rows": [{"k": 1}], "nested": {"a": 1}}) == [
        "$.level: 골든 'C0' · 지금 'C1'"]
    assert legacy.covers(golden, {"level": "C0", "rows": [], "nested": {}}) == [
        "$.rows: 길이가 다르다 — 골든 1 · 지금 0", "$.nested.a: 키가 사라졌다"]


# ---------------------------------------------------------------- ③ 옛 타깃에 걸린 패널과 잡이 끝까지 돈다
def test_the_planned_panel_closes_done(frozen, no_network):
    """MCP 미리보기가 편성해 둔 planned 패널을 회수 경로(complete_panel)로 닫는다."""
    target = MANIFEST["targets"]["planned"]
    panel = frozen.query_one("SELECT status, seats_json FROM rr_panels WHERE id = ?", (target["panel_id"],))
    assert panel["status"] == "planned"
    seats = [s["key"] for s in json.loads(panel["seats_json"])]
    spec_for = legacy.spec_builder(frozen, target["target_key"], planner.domain_of)

    out = routes.complete_panel(
        target["panel_id"], engine="mcp", decision_text=legacy.decision_text(spec_for(seats)),
        turns=[{"round": r, "persona": k, "say": f"{k} 라운드 {r} 발언"} for r in (1, 2) for k in seats],
        actor=OWNER, owner_sub=OWNER)

    assert out["parsed"] is True
    assert frozen.query_one("SELECT status FROM rr_panels WHERE id = ?", (target["panel_id"],))["status"] == "done"
    assert planner.check_invariants(frozen, target["target_key"]) == []


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "7248651 의 결함(WP1 P-03 · S5-a) — 같은 원장의 human 타깃(비슷한 과제)에 사람 finding 이 있어 이 타깃 브리프의 E5 에"
    " '[사람 제기·검증 대상]' 접두 줄이 실리고, 그 줄의 '중대' 가 판단어 린터 L15 에 걸려 brief_error 로 닫힌다."
    " 수리 뒤 xpass 가 strict 로 깨지면 이 표식을 지운다"))
def test_the_queued_job_runs_through_the_runner(frozen, no_network, tmp_path):
    """얼린 queued 잡을 러너가 집어(claim_next_job) 패널을 끝내고 잡을 닫는다 — 옛 잡도 러너를 지난다."""
    target = MANIFEST["targets"]["planned"]
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    secrets = data_dir / config.SECRETS_FILENAME
    secrets.write_text("HWAXRISK_PORTAL_PAT=test-service-pat\n", encoding="utf-8")
    secrets.chmod(0o600)
    cfg = dataclasses.replace(config.settings, data_dir=data_dir)
    engine = legacy.LegacyEngine(legacy.spec_builder(frozen, target["target_key"], planner.domain_of))

    job = runner.claim_next_job(frozen, cfg)
    assert job is not None and job["id"] == target["job_id"]
    out = runner.run_panel(frozen, cfg, engine, job)
    assert out["status"] == "done", out
    assert planner.check_invariants(frozen, target["target_key"]) == []

    # 남은 좌석이 없으면 다음 집기에서 잡이 completed 로 닫힌다.
    again = runner.claim_next_job(frozen, cfg)
    assert again is not None and runner.run_panel(frozen, cfg, engine, again)["status"] == "no_panel"
    assert frozen.query_one("SELECT state FROM rr_jobs WHERE id = ?", (target["job_id"],))["state"] == "completed"


def test_a_finding_the_panel_rejected_reaches_the_registry_as_rejected(frozen, no_network):
    """패널이 기각한 원자는 rr_findings.status 열에 기각으로 앉아 등록부가 센다(WP4 0a) — 종전에는 열이 'open' 고정이었다."""
    target = MANIFEST["targets"]["planned"]
    panel = frozen.query_one("SELECT seats_json FROM rr_panels WHERE id = ?", (target["panel_id"],))
    seats = [s["key"] for s in json.loads(panel["seats_json"])]
    spec = legacy.spec_builder(frozen, target["target_key"], planner.domain_of)(seats)
    rejected = spec["findings"][0]
    rejected.update({"status": "rejected_in_panel", "contested_by": [planner.ADVERSARY_KEY],
                     "contest_note": "기준선 대비 변화가 측정 오차 안이다."})

    routes.complete_panel(
        target["panel_id"], engine="mcp", decision_text=legacy.decision_text(spec),
        turns=[{"round": r, "persona": k, "say": f"{k} 라운드 {r} 발언"} for r in (1, 2) for k in seats],
        actor=OWNER, owner_sub=OWNER)

    stored = {r["claim_uid"].rsplit("#", 1)[-1]: r["status"] for r in frozen.query(
        "SELECT claim_uid, status FROM rr_findings WHERE panel_id = ?", (target["panel_id"],))}
    assert stored == {"F1": "rejected_in_panel", "F2": "open", "G1": "open"}
    rows = {json.loads(r["merged_json"])["claim"]: r for r in frozen.query(
        "SELECT merged_json, rejected, status FROM rr_registry WHERE target_key = ?", (target["target_key"],))}
    assert rows[rejected["claim"]]["rejected"] == 1 and rows[rejected["claim"]]["status"] == "rejected_in_panel"
    assert all(r["rejected"] == 0 and r["status"] == "open" for c, r in rows.items() if c != rejected["claim"])


def test_the_report_and_the_domain_filter_read_the_keys_the_schema_writes(frozen, no_network):
    """보고서 조립은 risk_spec 스키마의 키(cross_domain 의 from_domain·to_domain·path, open_items 의 question)를 읽고,
    등록부의 영역 필터는 병합이 쓰는 키(domains·owner_domain)를 읽는다(WP4 0d). 종전에는 각각 빈칸·0행이었다."""
    target = MANIFEST["targets"]["planned"]
    panel = frozen.query_one("SELECT seats_json FROM rr_panels WHERE id = ?", (target["panel_id"],))
    seats = [s["key"] for s in json.loads(panel["seats_json"])]
    spec = legacy.spec_builder(frozen, target["target_key"], planner.domain_of)(seats)
    domain = spec["findings"][0]["domain"]
    spec["cross_domain"] = [{"id": "X1", "from_domain": domain, "to_domain": "rel", "path": "두께 감소가 접합부 피로 수명을 줄인다",
                             "cites": [], "raised_by": [seats[0]]}]
    spec["open_items"] = [{"id": "O1", "question": "접합부 피로 시험을 다시 할 것인가",
                           "resolving_check": {"kind": "test", "ref": "접합부 피로 시험"}, "owner_domain": "rel"}]

    routes.complete_panel(
        target["panel_id"], engine="mcp", decision_text=legacy.decision_text(spec),
        turns=[{"round": r, "persona": k, "say": f"{k} 라운드 {r} 발언"} for r in (1, 2) for k in seats],
        actor=OWNER, owner_sub=OWNER)

    report = registry.build_report(frozen, target["target_key"])
    results = "\n".join(report["blocks"]["results"])
    assert f"{domain}→rel" in results and "«두께 감소가 접합부 피로 수명을 줄인다»" in results
    assert "open_item: 접합부 피로 시험을 다시 할 것인가" in report["blocks"]["recommendation"]
    filtered = routes.registry_payload(target["target_key"], owner_sub=OWNER, domain=domain)["rows"]
    assert filtered and all(domain in r["merged"]["domains"] for r in filtered)
    assert routes.registry_payload(target["target_key"], owner_sub=OWNER, domain="rf")["rows"] == []


def test_a_second_panel_on_the_done_target_saves_beside_the_old_adversary_row(frozen, no_network):
    """옛 코드가 회차 1 로 남긴 반대석 의견 행이 있는 DB 에서 같은 타깃의 두 번째 패널이 저장된다(WP1 R-1 의 옛 DB 쪽).

    러너 길은 이 DB 에서 브리프가 WP1 P-03 에 먼저 걸려(③b 의 xfail) 저장까지 오지 못한다 — 편성기가 연 패널을
    회수 경로(complete_panel)로 닫는다. 그 길도 반대석을 귀속 좌석으로 더해 의견 행을 쓴다.
    """
    target = MANIFEST["targets"]["done"]
    old = frozen.query("SELECT cycle FROM rr_seat_opinions WHERE target_key = ? AND agent_key = ?",
                       (target["target_key"], planner.ADVERSARY_KEY))
    assert [r["cycle"] for r in old] == [1]
    panel = planner.plan_next_panel(frozen, target["target_key"], "C")
    assert panel is not None and panel["panel_no"] == 2
    seats = [s["key"] for s in panel["seats"]]
    spec_for = legacy.spec_builder(frozen, target["target_key"], planner.domain_of)

    out = routes.complete_panel(
        panel["id"], engine="mcp", decision_text=legacy.decision_text(spec_for(seats)),
        turns=[{"round": r, "persona": k, "say": f"{k} 라운드 {r} 발언"} for r in (1, 2) for k in seats],
        actor=OWNER, owner_sub=OWNER)

    assert out["parsed"] is True
    assert frozen.query_one("SELECT status FROM rr_panels WHERE id = ?", (panel["id"],))["status"] == "done"
    rows = frozen.query("SELECT o.cycle, p.panel_no FROM rr_seat_opinions o JOIN rr_panels p ON p.id = o.panel_id"
                        " WHERE o.target_key = ? AND o.agent_key = ? ORDER BY p.panel_no",
                        (target["target_key"], planner.ADVERSARY_KEY))
    assert [(r["cycle"], r["panel_no"]) for r in rows] == [(1, 1), (100002, 2)]
    assert planner.check_invariants(frozen, target["target_key"]) == []


# ---------------------------------------------------------------- ⑤ MCP 도구 이름과 순서
def test_mcp_tools_keep_their_names_and_order():
    golden = json.loads((legacy.LEGACY_DIR / "golden" / "mcp_tools.json").read_text(encoding="utf-8"))
    names = [t.name for t in asyncio.run(mcp_server.mcp.list_tools())]
    assert names[:len(golden)] == golden, "옛 도구의 이름·순서는 그대로이고 새 도구는 뒤에 붙는다"


# ---------------------------------------------------------------- 위생 — 얼린 DB 에 내부 주소·비밀 꼴이 없다
_IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_SECRET_SHAPES = (re.compile(r"Bearer\s+\S"), re.compile(r"\brat_[A-Za-z0-9]"), re.compile(r"-----BEGIN"),
                  re.compile(r"\bgAAAAA[A-Za-z0-9_-]{20}"))       # 마지막은 Fernet 암호문의 머리다


def _all_text(db: Path) -> str:
    """모든 표의 모든 칸을 글로 — gzip BLOB 은 풀어서 본다."""
    raw = sqlite3.connect(db)
    parts: list[str] = []
    try:
        tables = [r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            for row in raw.execute(f'SELECT * FROM "{table}"'):
                for value in row:
                    if isinstance(value, bytes):
                        try:
                            value = gzip.decompress(value).decode("utf-8", "replace")
                        except OSError:
                            value = value.decode("utf-8", "replace")
                    parts.append(str(value))
    finally:
        raw.close()
    return "\n".join(parts)


def test_the_frozen_db_holds_no_internal_address_or_secret(tmp_path):
    text = _all_text(_thaw(tmp_path))
    assert len(text) > 10_000                                   # 빈 DB 를 훑고 통과하지 않는다
    assert set(_IPV4.findall(text)) <= {"127.0.0.1"}
    assert legacy.SERVICE_PAT_CANARY not in text
    assert [p.pattern for p in _SECRET_SHAPES if p.search(text)] == []
