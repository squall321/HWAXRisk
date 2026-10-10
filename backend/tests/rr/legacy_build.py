# 옛 타깃 얼리기(WP5b C0) — 스키마 v2 코드로 합성 원장 DB 와 불변 사영 골든을 만들고, 그 사영과 가짜 엔진을 시험과 같이 쓴다
"""옛 타깃(재설계 전 — 단위·칸이 없는 타깃)이 새 코드에서도 열리고 걸린 패널이 끝까지 도는지를 지키는 픽스처다.

만드는 것은 `tests/fixtures/legacy/` 의 넷이다.

- `risk_review.v2.db.gz` — 스키마 v2 DB. 합성 자료만 있고 타깃 셋을 담는다(역할 `done` · `planned` · `human`).
- `manifest.json` — 역할마다 target_key 와 시험이 집는 id(planned 패널 · queued 잡 · ack 한 스냅샷).
- `golden/<역할>.json` — `coverage_payload` · `registry_rows` · `close_level` · `build_report` 의 **불변 사영**.
  글(문면)과 새로 생기는 키는 담지 않는다 — WP1 이 브리프·표시 문면을 일부러 바꾸기 때문이다.
- `golden/mcp_tools.json` — 얼린 시점의 MCP 도구 이름과 순서.

**스키마 v2 를 쓰는 코드(HWAXRisk `7248651`)에서만 돈다.** 그 뒤 판에서 다시 만들어야 하면 그 판을 꺼내
그 안에서 돌린다 — 새 코드로 만들면 '옛 DB 를 새 코드로 연다' 는 시험이 빈 시험이 된다.

    git worktree add /tmp/rr-7248651 7248651
    cd /tmp/rr-7248651/backend && <리스크 venv>/bin/python -m tests.rr.legacy_build --out <이 리포>/backend/tests/fixtures/legacy

자료는 생산자 경로로만 만든다 — 과제·타깃은 라우트, 스냅샷은 `ir_builder.freeze_snapshot`, diff 는 `diff.create_diff`,
패널은 러너(`claim_next_job` → `run_panel`)와 MCP 회수(`complete_panel`)다. 원장 행을 손으로 INSERT 하지 않는다.
"""
from __future__ import annotations

import argparse
import copy
import gzip
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
LEGACY_DIR = BACKEND_DIR / "tests" / "fixtures" / "legacy"
IR_FIXTURES = BACKEND_DIR / "tests" / "fixtures" / "ir"
DB_GZ = "risk_review.v2.db.gz"
FROZEN_SCHEMA = 2
FROZEN_COMMIT = "7248651"
ROLES = ("done", "planned", "human")

OWNER = "legacy@example.com"
# 서비스 PAT 는 임시 데이터 디렉터리의 secrets.env 에만 둔다. 얼린 DB 에 이 문자열이 보이면 시험이 붉다.
SERVICE_PAT_CANARY = "legacy-fixture-canary-pat"
CAPTURED_AT = 1756600000
# 도메인 넷은 ECAD 무관, pcb 는 ECAD 도메인이라 ECAD 없는 스냅샷에서 rank 2 가 deferred 로 앉는다(옛 원장의 모양).
# 도메인이 다섯이라 Tier A(도메인별 rank 1)는 패널 한 건이다. 같은 타깃의 두 번째 패널은 7248651 에서 저장이 실패한다
# (rr_seat_opinions 의 UNIQUE — 지정 반대석의 회차가 늘 1, 계획서 D-5). 옛 원장은 그 결함이 나지 않은 모양만 담는다.
ROSTER_DOMAINS = ("mech", "sim", "xd", "rel", "pcb")
GATE_ACK = ("G3", "계면 간섭 auto 초안을 확인했고 진행한다")


# ---------------------------------------------------------------- 불변 사영(골든과 시험이 같은 함수를 쓴다)
_LEVEL_DETAIL = ("domains_terminal", "tier_a_done", "depth", "strong", "done_weak", "strong_ratio",
                 "spec_parse_failed", "skipped", "skipped_ratio", "failed")
_COVERAGE_KEYS = ("roster_size", "by_domain", "by_status", "strong", "unseated_n", "level", "close_level")
_JOB_KEYS = ("tier", "state", "panels_done", "panels_total")
_REGISTRY_KEYS = ("cluster_key", "status", "direction", "severity", "judgement", "evidence_grade", "support",
                  "contested")


def project_close_level(level: dict) -> dict:
    """`registry.close_level` 의 레벨·회계 칸. 시각·문면은 없다."""
    detail = level.get("detail") or {}
    out = {k: level[k] for k in ("level", "close_level", "roster_size", "status_counts", "unseated_n", "c1", "c2", "c3")}
    out["detail"] = {k: detail.get(k) for k in _LEVEL_DETAIL}
    return out


def project_coverage(payload: dict) -> dict:
    """`routes.coverage_payload` 의 카운트 칸과 잡 상태. 잡 id·진행 신호(지금 시각에 묶인 값)는 뺀다."""
    out = {k: payload[k] for k in _COVERAGE_KEYS}
    job = payload.get("job")
    out["job"] = None if job is None else {k: job.get(k) for k in _JOB_KEYS}
    return out


def project_registry(rows: list[dict]) -> list[dict]:
    """등록부 행의 정체(클러스터 키)·상태·등급과 그 행에 묶인 finding id 집합."""
    out = []
    for row in rows:
        item = {k: row.get(k) for k in _REGISTRY_KEYS}
        merged = row.get("merged") or {}
        item["member_ids"] = sorted(str(f) for f in merged.get("member_ids") or [])
        item["human_refs"] = sorted(str(f) for f in merged.get("human_refs") or [])
        out.append(item)
    return out


def project_report(report: dict) -> dict:
    """통합 보고서는 블록의 키 목록과 블록마다의 행 수만 본다(문면은 WP1 이 일부러 바꾼다)."""
    blocks = report.get("blocks") or {}
    lines: dict[str, int] = {}
    for key, value in blocks.items():
        if isinstance(value, list):
            text = "\n".join(str(v) for v in value)
        else:
            text = str(value)
        lines[key] = len(text.splitlines())
    return {"block_keys": sorted(blocks), "block_lines": lines, "level": report.get("level"),
            "version": report.get("version")}


def covers(golden: Any, current: Any, path: str = "$") -> list[str]:
    """골든이 현재 값에 그대로 들어 있는지 — 어긋난 경로 목록(빈 목록 = 통과).

    dict 는 골든의 키만 본다(새 키가 더해지는 것은 통과). 있던 키의 값이 달라지면 실패다. list 는 길이와 자리가 같아야 한다.
    """
    if isinstance(golden, dict):
        if not isinstance(current, dict):
            return [f"{path}: dict 가 아니다 — {type(current).__name__}"]
        out: list[str] = []
        for key, value in golden.items():
            if key not in current:
                out.append(f"{path}.{key}: 키가 사라졌다")
            else:
                out.extend(covers(value, current[key], f"{path}.{key}"))
        return out
    if isinstance(golden, list):
        if not isinstance(current, list) or len(current) != len(golden):
            return [f"{path}: 길이가 다르다 — 골든 {len(golden)} · 지금 {len(current) if isinstance(current, list) else current!r}"]
        out = []
        for i, (g, c) in enumerate(zip(golden, current)):
            out.extend(covers(g, c, f"{path}[{i}]"))
        return out
    return [] if golden == current else [f"{path}: 골든 {golden!r} · 지금 {current!r}"]


def golden_for(store, routes_mod, registry_mod, target_key: str) -> dict:
    """한 타깃의 옛 응답 넷을 사영한다. `routes.get_store` 는 호출자가 이 저장소로 바꿔 끼워 둔다."""
    return {
        "coverage": project_coverage(routes_mod.coverage_payload(target_key, owner_sub=OWNER)),
        "registry": project_registry(registry_mod.registry_rows(store, target_key)),
        "close_level": project_close_level(registry_mod.close_level(store, target_key, persist=False)),
        "report": project_report(registry_mod.build_report(store, target_key)),
    }


# ---------------------------------------------------------------- 가짜 엔진(LLM·네트워크 없음)
def risk_spec(*, target_key: str, project_id: str, snapshot_ids: tuple[str, str], diff_id: str, ir_hash: str,
              events: list[dict], seats: list[str], domain_of) -> dict:
    """그 diff 가 실제로 낸 의미 이벤트만 인용하는 risk_spec(주체 ckey 와 cites 는 이벤트에서 그대로 온다)."""
    by_code = {e["code"]: e for e in events}
    thickness, material = by_code["part.thickness_changed"], by_code["part.material_changed"]
    seat = seats[0]

    def finding(fid: str, direction: str, mechanism: str, detail: str, event: dict, claim: str) -> dict:
        return {
            "id": fid, "direction": direction, "domain": domain_of(seat),
            "mechanism": mechanism, "mechanism_detail": detail, "change_kind": event["change_kind"],
            "subject": {"ckeys": list(event["subject"]["ckeys"]), "names": []},
            "trigger_condition": "none",
            "severity": "중대" if direction == "risk" else "경미",
            "judgement": "WARNING" if direction == "risk" else "OK",
            "detectability": {"level": "sim-detectable", "tool": "report_part_risk"},
            "evidence_grade": "도구예측", "precedent": "none",
            "cites": [{"ref": event["cid"], "quote": event["text"]}],
            "tool_calls": [], "claim": claim,
            "warrant": "diff 의미 이벤트가 같은 방향의 수치 변화를 낸다.",
            "resolving_check": {"kind": "sim", "ref": "낙하 해석 재실행"},
            "owner_domain": domain_of(seat), "raised_by": [seat], "contested_by": [], "contest_note": "",
            "status": "open",
        }

    facets = ("intent", "constraint", "anomaly", "lineage", "vulnerability", "strength", "tradeoff", "unknown")
    return {
        "schema": "risk_spec", "version": "1.0", "taxonomy_version": "1.0",
        "scope": {"kind": "diff", "target_key": target_key, "project_refs": [project_id],
                  "ir_refs": list(snapshot_ids), "diff_ref": diff_id, "ir_hash": ir_hash},
        "findings": [
            finding("F1", "risk", "mechanical", "drop_stress", thickness,
                    "PLATE_2 두께가 1.0→1.4 mm 로 늘어 적층 높이 여유가 줄어든다."),
            finding("F2", "risk", "interface", "interference", material,
                    "PLATE_1 재질 교체로 접합부 강성 가정이 바뀐다."),
        ],
        "gains": [
            finding("G1", "improvement", "mechanical", "drop_stress", thickness, "두께 증가로 굽힘 강성이 올라간다."),
        ],
        "cross_domain": [], "open_items": [],
        "character": {"one_liner": "두께·재질 변경 1건씩의 개정 스냅샷.",
                      "facets": [{"facet": f, "statements": [], "na_reason": "좌석 미기재"} for f in facets]},
        "coverage": {"seats": [{"key": k, "domain": domain_of(k), "origin": "primary"} for k in seats],
                     "domains_seated": sorted({domain_of(k) for k in seats}), "domains_missing": []},
        "verdict": "undetermined", "verdict_conditions": [],
        "evidence_profile": {"tool": 3, "card": 0, "precedent": {"verified": 0, "dismissed": 0},
                             "heuristic": 0, "measured": 0},
    }


class LegacyEngine:
    """러너가 부르는 심의 엔진 자리 — SSE 캡처와 같은 모양({decision_text, turns, events, conv_id})만 돌려준다."""

    def __init__(self, spec_for) -> None:
        self._spec_for = spec_for
        self.calls: list[dict] = []

    def health(self) -> dict:
        return {"model": "legacy-fake-model", "provider": "fake", "engine_rev": "legacy"}

    def run(self, delib_opts, *, owner_sub=None):
        self.calls.append(dict(delib_opts))
        keys = [p["key"] for p in delib_opts["personas"]]
        return {
            "decision_text": decision_text(self._spec_for(keys)),
            "turns": [{"round": r, "persona": k, "say": f"{k} 라운드 {r} 발언"} for r in (1, 2) for k in keys],
            "events": seat_events(keys), "conv_id": "conv-legacy", "report_id": 9001, "call_path": "portal",
        }


def decision_text(spec: dict) -> str:
    return ("[검증 대상 — 결론 아님] 두께·재질 변경이 낙하 응력과 접합부에 미치는 영향을 좌석별로 검토했다.\n\n"
            "```json\n" + json.dumps(spec, ensure_ascii=False) + "\n```")


def seat_events(keys: list[str]) -> list[dict]:
    events: list[dict] = [{"kind": "personas", "personas": [{"key": k} for k in keys]}]
    for key in keys:
        events.append({"kind": "status", "step": f"{key} 조회: list_interfaces", "tool": "list_interfaces"})
        events.append({"kind": "evidence", "source": f"{key} · list_interfaces", "text": "계면 2건"})
    return events


def spec_builder(store, target_key: str, domain_of):
    """그 타깃의 diff·스냅샷을 원장에서 읽어 좌석 목록 → risk_spec 함수를 돌려준다."""
    target = store.query_one("SELECT ref_id, project_id, ir_hash FROM rr_targets WHERE target_key = ?", (target_key,))
    diff_row = store.query_one("SELECT base_snapshot_id, target_snapshot_id, diff_json FROM rr_diffs WHERE id = ?",
                               (target["ref_id"],))
    events = json.loads(diff_row["diff_json"])["semantic"]["events"]
    return lambda seats: risk_spec(
        target_key=target_key, project_id=target["project_id"],
        snapshot_ids=(diff_row["base_snapshot_id"], diff_row["target_snapshot_id"]), diff_id=target["ref_id"],
        ir_hash=target["ir_hash"], events=events, seats=seats, domain_of=domain_of)


# ---------------------------------------------------------------- 만들기
def _fixture(name: str) -> dict:
    return json.loads((IR_FIXTURES / name).read_text(encoding="utf-8"))


def adapter_pair() -> tuple[list[dict], list[dict]]:
    """기존 어댑터 픽스처 셋(mcad·dyna·dyna_result) 과 그 개정본 — PLATE_2 두께 1.0→1.4 · PLATE_1 재질 교체 · 결과 응력 상승."""
    base = [_fixture("adapter_mcad_basic.json"), _fixture("adapter_dyna_basic.json"),
            _fixture("adapter_dyna_result.json")]
    target = copy.deepcopy(base)
    mcad, _dyna, result = target
    by_label = {n["label"]: n for n in mcad["nodes"]}
    by_label["PLATE_2"]["attrs"]["min_dim"] = 1.4
    by_label["PLATE_1"]["attrs"]["material"] = "AZ91D"
    result["results"]["part_risk"][0]["worst_stress"]["value"] = 262.0
    return base, target


def _agents() -> list[dict]:
    return [{"key": f"{d}-legacy-{i}", "domain": d, "relevance": 0.9 - 0.1 * i}
            for d in ROSTER_DOMAINS for i in range(2)]


def _open_target(app, store, ident, code: str) -> dict:
    """과제 → 스냅샷 둘 → diff → 타깃(로스터 동결)까지 생산자 경로로 연다."""
    routes, ir_builder = app["routes"], app["ir_builder"]
    project = routes.create_project(routes.ProjectBody(code=code, name=f"옛 타깃 {code}", stage="DV1",
                                                       classification="internal"), ident=ident)
    base_results, target_results = adapter_pair()
    base = ir_builder.freeze_snapshot(store, project_id=project["id"], owner_sub=OWNER, label="DV1",
                                      adapter_results=base_results, captured_at=CAPTURED_AT)
    target = ir_builder.freeze_snapshot(store, project_id=project["id"], owner_sub=OWNER, label="DV2",
                                        adapter_results=target_results, captured_at=CAPTURED_AT + 86400)
    diff = routes.create_diff(routes.DiffBody(base_snapshot_id=base["snapshot_id"],
                                              target_snapshot_id=target["snapshot_id"]), ident=ident)
    opened = routes.create_target(routes.TargetBody(kind="diff", ref_id=diff["diff_id"], consent=True,
                                                    agents=_agents()), ident=ident)
    return {"project_id": project["id"], "base_snapshot_id": base["snapshot_id"],
            "target_snapshot_id": target["snapshot_id"], "diff_id": diff["diff_id"],
            "target_key": opened["target_key"]}


def _run_one_job(app, store, cfg, target_key: str, tier: str) -> str:
    """잡 1건을 러너 경로로 끝까지 돌린다 — 패널을 다 돈 뒤 다음 집기에서 completed 로 닫힌다."""
    runner, planner = app["runner"], app["planner"]
    job_id = runner.create_job(store, target_key, tier, owner_sub=OWNER, consent=(tier == "C"), settings=cfg)["job_id"]
    engine = LegacyEngine(spec_builder(store, target_key, planner.domain_of))
    for _ in range(10):
        job = runner.claim_next_job(store, cfg)
        if job is None:
            break
        out = runner.run_panel(store, cfg, engine, job)
        if out["status"] not in ("done", "no_panel"):
            raise RuntimeError(f"러너 패널이 끝나지 않았다 — {out}")
    state = store.query_one("SELECT state FROM rr_jobs WHERE id = ?", (job_id,))["state"]
    if state != "completed":
        raise RuntimeError(f"잡 {job_id} 가 completed 가 아니다 — {state}")
    return job_id


def _import_app() -> dict:
    from app import config, diff, ir_builder, planner, registry, routes, runner  # noqa: PLC0415
    from app import mcp_server  # noqa: PLC0415
    from app.risk_store import MIGRATIONS, RiskStore  # noqa: PLC0415

    return {"config": config, "diff": diff, "ir_builder": ir_builder, "planner": planner, "registry": registry,
            "routes": routes, "runner": runner, "mcp_server": mcp_server, "MIGRATIONS": MIGRATIONS,
            "RiskStore": RiskStore}


def _block_network() -> None:
    """이 스크립트의 어느 단계도 소켓으로 나가지 않는다 — 게이트웨이가 꺼진 박스와 같은 연결 오류로 답한다.

    브리프의 필드 근거 조회(E10)가 서비스 PAT 로 게이트웨이를 부르는데, 운영 코드는 연결 오류를 '조회 실패' 로 적고
    넘어간다. 옛 박스의 흔한 모양이라 그대로 얼린다.
    """
    import httpx  # noqa: PLC0415

    def _blocked(*args, **_kwargs):
        raise httpx.ConnectError("legacy_build 는 외부를 부르지 않는다.", request=args[-1])

    httpx.HTTPTransport.handle_request = _blocked                   # type: ignore[method-assign]
    httpx.AsyncHTTPTransport.handle_async_request = _blocked        # type: ignore[method-assign]


def build(out_dir: Path) -> dict:
    data_dir = Path(tempfile.mkdtemp(prefix="rr-legacy-build-"))
    try:
        return _build(data_dir, out_dir)
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


def _build(data_dir: Path, out_dir: Path) -> dict:
    os.environ["HWAXRISK_DATA_DIR"] = str(data_dir)
    for key in ("HEAX_DATA_DIR", "ROOT_PATH"):
        os.environ.pop(key, None)
    secrets = data_dir / "secrets.env"
    secrets.write_text(f"HWAXRISK_PORTAL_PAT={SERVICE_PAT_CANARY}\n", encoding="utf-8")
    secrets.chmod(0o600)
    _block_network()
    app = _import_app()
    latest = app["MIGRATIONS"][-1][0]
    if latest != FROZEN_SCHEMA:
        raise SystemExit(f"이 코드의 스키마는 v{latest} 다 — 옛 타깃은 v{FROZEN_SCHEMA} 코드({FROZEN_COMMIT})로만 만든다."
                         f" `git worktree add /tmp/rr-{FROZEN_COMMIT} {FROZEN_COMMIT}` 로 꺼내 그 안에서 돌려라.")
    from app import identity  # noqa: PLC0415

    routes, registry, runner = app["routes"], app["registry"], app["runner"]
    cfg = app["config"].settings
    work = data_dir / "work"
    store = app["RiskStore"](work / "risk_review.db")
    store.open()
    store.migrate()
    routes.get_store = lambda: store                                # 라우트는 모듈 전역 저장소를 부른다
    ident = identity.Identity(email=OWNER, display_name="옛 타깃", role="user", organization="qa",
                              anonymous=False, source="bearer")
    try:
        # done — 러너가 Tier A 패널 1건을 끝내고 잡이 completed 로 닫힌 타깃.
        done = _open_target(app, store, ident, "LEG-DONE")
        done["job_id"] = _run_one_job(app, store, cfg, done["target_key"], "A")

        # planned — MCP 미리보기가 편성한 planned 패널과, 아직 집히지 않은 queued 잡(Tier C)이 걸린 타깃.
        planned = _open_target(app, store, ident, "LEG-PLAN")
        brief = routes.brief_payload(planned["target_key"], "B", owner_sub=OWNER)
        planned["panel_id"] = brief["panels"][0]["panel_id"]
        planned["job_id"] = runner.create_job(store, planned["target_key"], "C", owner_sub=OWNER, consent=True,
                                              settings=cfg)["job_id"]

        # human — 사람 finding 1건과 게이트 ack 1건이 있는 타깃(패널은 없다).
        human = _open_target(app, store, ident, "LEG-HUMAN")
        events = app["diff"].get_diff(store, human["diff_id"], owner_sub=OWNER, part="diff")["semantic"]["events"]
        cited = next(e for e in events if e["code"] == "part.thickness_changed")
        made = routes.create_human_finding(human["target_key"], routes.HumanFindingBody(
            direction="risk", domain="mech", mechanism="mechanical", mechanism_detail="drop_stress",
            change_kind=cited["change_kind"], subject_key=cited["subject_key"], severity="중대",
            judgement="WARNING", claim="두께가 늘어 적층 높이 여유가 줄었다.",
            cites=[{"ref": cited["cid"], "quote": cited["text"]}]), ident=ident)
        human["finding_id"] = made["finding_id"]
        routes.post_gate_ack(human["base_snapshot_id"], GATE_ACK[0], routes.GateAckBody(reason=GATE_ACK[1]),
                             ident=ident)
        human["acked"] = {"snapshot_id": human["base_snapshot_id"], "gate": GATE_ACK[0]}
    finally:
        store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        store.close()

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "golden").mkdir(exist_ok=True)
    with open(work / "risk_review.db", "rb") as src, open(out_dir / DB_GZ, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
            shutil.copyfileobj(src, gz)

    manifest = {"frozen_commit": FROZEN_COMMIT, "schema_version": FROZEN_SCHEMA, "owner": OWNER,
                "targets": {"done": done, "planned": planned, "human": human}}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                                           encoding="utf-8")

    # 골든은 얼린 파일을 다시 연 사본에서 받는다 — 시험이 여는 것과 같은 바이트다.
    replay = data_dir / "replay"
    replay.mkdir()
    with gzip.open(out_dir / DB_GZ, "rb") as gz, open(replay / "risk_review.db", "wb") as dst:
        shutil.copyfileobj(gz, dst)
    frozen = app["RiskStore"](replay / "risk_review.db")
    frozen.open()
    frozen.migrate()
    routes.get_store = lambda: frozen
    try:
        for role in ROLES:
            golden = golden_for(frozen, routes, registry, manifest["targets"][role]["target_key"])
            (out_dir / "golden" / f"{role}.json").write_text(
                json.dumps(golden, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    finally:
        frozen.close()

    import asyncio  # noqa: PLC0415

    tools = [t.name for t in asyncio.run(app["mcp_server"].mcp.list_tools())]
    (out_dir / "golden" / "mcp_tools.json").write_text(json.dumps(tools, indent=1) + "\n", encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="스키마 v2 옛 타깃 픽스처를 만든다(7248651 코드에서만).")
    parser.add_argument("--out", type=Path, default=LEGACY_DIR, help="쓸 디렉터리(기본 tests/fixtures/legacy)")
    args = parser.parse_args(argv)
    manifest = build(args.out)
    print(json.dumps({role: t["target_key"] for role, t in manifest["targets"].items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
