# 시험 입력을 생산자 함수로 만드는 공장 — 손으로 쓴 원장 행 대신 쓴다(WP5b C2 가드 A, 규칙 R1)
"""소비자 시험의 정상 경로 입력은 생산자 함수의 출력이어야 한다. 손으로 쓴 dict·INSERT 는 소비자 코드를 보고 쓴 것이라
소비자와 같이 틀린다(일치 시험은 둘이 같이 틀리면 통과한다 — 2.3절의 실례 여섯이 전부 이 모양이었다).

- 과제·치수·타깃은 라우트(`routes.create_project` · `add_dim` · `create_target`) — 라우트는 모듈 전역 `get_store` 를 부르므로
  공장이 그 자리를 이 저장소로 잠깐 바꿔 끼우고 되돌린다(반대 검토 P-23).
- 스냅샷은 `ir_builder.freeze_snapshot`, diff 는 `diff.create_diff`, 좌석은 `planner.plan_next_panel` 그대로다.
- `seed_raw` 는 생산자가 만들 수 없는 '망가진 행' 전용이고 사유가 필수다.
"""
from __future__ import annotations

import copy
import json
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from jsonschema import validators

from app import devseed, identity, ir_builder, planner, routes
from app import diff as diff_module
from app.common import canonical_json, sha256_hex

OWNER = "syn@example.com"
CAPTURED_AT = 1756600000
_BACKEND = Path(__file__).resolve().parents[1]
IR_FIXTURES = _BACKEND / "tests" / "fixtures" / "ir"
_SCHEMAS = _BACKEND / "app" / "schemas"


def ident(owner: str = OWNER) -> identity.Identity:
    return identity.Identity(email=owner, display_name="합성", role="user", organization="qa", anonymous=False,
                             source="bearer")


@contextmanager
def routes_store(store) -> Iterator[None]:
    """라우트 본문이 이 저장소를 보게 한다(라우트는 모듈 전역 `get_store` 를 부른다)."""
    previous = routes.get_store
    routes.get_store = lambda: store
    try:
        yield
    finally:
        routes.get_store = previous


# ---------------------------------------------------------------- 생산자 경유
def make_project(store, *, owner: str = OWNER, code: str | None = None, name: str = "합성 과제",
                 classification: str = "internal") -> str:
    """`routes.create_project` — 코드를 안 주면 그 저장소의 과제 수에서 유도한다(`UNIQUE(owner_sub, code)` 409 를 피한다)."""
    if code is None:
        n = store.query_one("SELECT COUNT(*) AS n FROM rr_projects WHERE owner_sub = ?", (owner,))["n"]
        code = f"SYN-{n + 1}"
    with routes_store(store):
        return routes.create_project(routes.ProjectBody(code=code, name=name, stage="DV1",
                                                        classification=classification), ident=ident(owner))["id"]


def make_dim(store, project_id: str, name: str, extractor: str, *, kind: str = "thickness", unit: str = "mm",
             owner: str = OWNER) -> dict:
    """`routes.add_dim` — 명명 치수 정의 1건(스냅샷을 얼리기 **전에** 둬야 그 스냅샷의 dims_named 에 값이 선다)."""
    with routes_store(store):
        return routes.add_dim(project_id, routes.DimBody(name=name, kind=kind, unit=unit, extractor=extractor),
                              ident=ident(owner))


def make_snapshot(store, project_id: str, adapter_results: Sequence[Mapping[str, Any]], *, label: str,
                  owner: str = OWNER, captured_at: int = CAPTURED_AT, **build_kwargs: Any) -> dict:
    """`ir_builder.freeze_snapshot` 을 그대로 부른다. 반환은 그 함수의 반환이다."""
    return ir_builder.freeze_snapshot(store, project_id=project_id, owner_sub=owner, label=label,
                                      adapter_results=adapter_results, captured_at=captured_at, **build_kwargs)


def make_diff(store, base_snapshot_id: str, target_snapshot_id: str, *, owner: str = OWNER) -> dict:
    """`diff.create_diff` 를 그대로 부른다 — `rr_diffs`·`rr_diff_events` 가 생산자 경로로 찬다."""
    return diff_module.create_diff(store, base_snapshot_id, target_snapshot_id, owner_sub=owner)


def make_target(store, kind: str, ref_id: str, *, agents: Sequence[Mapping[str, Any]], owner: str = OWNER) -> str:
    """`routes.create_target` — 로스터 동결까지. 반환은 target_key."""
    with routes_store(store):
        out = routes.create_target(routes.TargetBody(kind=kind, ref_id=ref_id, consent=True,
                                                      agents=[dict(a) for a in agents]), ident=ident(owner))
    return out["target_key"]


def plan_panel(store, target_key: str, tier: str = "A", **kwargs: Any) -> dict | None:
    """`planner.plan_next_panel` — 좌석 dict 는 편성기가 쓴 그대로(`key`)다."""
    return planner.plan_next_panel(store, target_key, tier, **kwargs)


def agents(domains: Sequence[str] = ("mech", "sim", "xd", "rel", "pcb"), per_domain: int = 2) -> list[dict]:
    """로스터 원천(`list_agents` + `recommend_agents` 결과 모양). 도메인은 Settings 화이트리스트 안이어야 한다."""
    return [{"key": f"{d}-syn-{i}", "domain": d, "relevance": round(0.9 - 0.1 * i, 3)}
            for d in domains for i in range(per_domain)]


_default_agents = agents          # make_diff_target 의 인자 이름이 이 함수를 가린다.


def adapter_fixture(name: str) -> dict:
    return json.loads((IR_FIXTURES / name).read_text(encoding="utf-8"))


def fixture_adapter_results() -> list[dict]:
    """기존 어댑터 픽스처 셋(mcad·dyna·dyna_result) — 실 어댑터 계약 모양이다."""
    return [adapter_fixture("adapter_mcad_basic.json"), adapter_fixture("adapter_dyna_basic.json"),
            adapter_fixture("adapter_dyna_result.json")]


# ---------------------------------------------------------------- 합성 다건 변경 타깃(app/devseed.py 위)
class SynthMismatch(RuntimeError):
    """합성 쌍이 대본이 뜻한 diff 를 만들지 못했다 — 생성기와 생산자 중 한쪽이 틀렸다(출력에 맞춰 기대를 고치지 않는다).

    AssertionError 가 아니다 — xfail(raises=AssertionError) 시험이 공장의 실패를 삼키지 않게 한다(반대 검토 P-02).
    """


@dataclass(frozen=True)
class SynthTarget:
    project_id: str
    base_snapshot_id: str
    target_snapshot_id: str
    diff_id: str
    target_key: str
    diff: dict
    manifest: tuple[devseed.ChangeRecord, ...]
    base: devseed.Design
    target: devseed.Design


def synth_mismatch(diff: Mapping[str, Any], records: Sequence[devseed.ChangeRecord]) -> list[str]:
    """대본의 기대와 생산자 diff 의 어긋남(빈 목록 = 같다). 의미 이벤트가 막혔으면 그것부터 말한다."""
    semantic = diff.get("semantic") or {}
    if semantic.get("blocked_by"):
        return [f"의미 이벤트가 막혔다 — blocked_by={semantic['blocked_by']}"]
    got = Counter(e["code"] for e in semantic.get("events") or [])
    want = Counter(devseed.expected_codes(records))
    out = [f"{code}: 기대 {want[code]} · 생산 {got[code]}" for code in sorted(set(got) | set(want))
           if got[code] != want[code]]
    unmeasured = [d["name"] for d in (diff.get("parametric") or {}).get("dims_delta") or [] if d.get("before") is None]
    if unmeasured:
        out.append(f"base 에서 값이 서지 않은 명명 치수 — {unmeasured}")
    return out


def diff_fingerprint(diff: Mapping[str, Any]) -> str:
    """식별자(diff·과제·스냅샷 id)와 시각을 뺀 diff 본문의 해시 — 같은 씨앗이면 저장소가 달라도 같아야 한다.

    `rr_diffs.diff_hash` 는 결정론 단언에 못 쓴다 — 본문에 스냅샷 id(uuid)와 그 앞 8자가 든 요약문이 있어 저장소마다
    다르다(반대 검토 P-04).
    """
    body = copy.deepcopy(dict(diff))
    marks = {str(body["base"]["snapshot_id"]): "<base>", str(body["target"]["snapshot_id"]): "<target>"}
    for key in ("diff_id", "created_at", "project_id"):
        body.pop(key, None)
    text = canonical_json(body)
    for snapshot_id, mark in marks.items():
        text = text.replace(snapshot_id, mark).replace(snapshot_id[:8], mark)
    return sha256_hex(text)


def make_diff_target(store, size: int = 40, *, seed: int | None = None, owner: str = OWNER,
                     agents: Sequence[Mapping[str, Any]] | None = None,
                     script: Sequence[tuple[str, Mapping[str, Any]]] | None = None,
                     spec: devseed.SynthSpec | None = None, check: bool = True) -> SynthTarget:
    """합성 다건 변경 타깃 — 대본 → 어댑터 결과 쌍 → 실제 생산자(명명 치수·스냅샷 둘·diff·타깃)."""
    from tests.synth import scripts  # noqa: PLC0415 — 대본은 시험 쪽 모듈이다.

    seed = scripts.SEED if seed is None else seed
    spec = spec or scripts.spec_for(size, seed)
    script = list(script if script is not None else scripts.script_for(size, seed))
    base, target, records = devseed.apply_script(devseed.build_design(spec), script, seed)
    project_id = make_project(store, owner=owner)
    for dim in devseed.dim_defs(base):
        make_dim(store, project_id, dim["name"], dim["extractor"], kind=dim["kind"], unit=dim["unit"], owner=owner)
    first = make_snapshot(store, project_id, devseed.to_adapter_results(base), label="DV1", owner=owner)
    later = CAPTURED_AT + 86400
    second = make_snapshot(store, project_id, devseed.to_adapter_results(target, captured_at=later), label="DV2",
                           owner=owner, captured_at=later)
    diff = make_diff(store, first["snapshot_id"], second["snapshot_id"], owner=owner)
    if check:
        problems = synth_mismatch(diff, records)
        if problems:
            raise SynthMismatch("합성 쌍이 대본과 다르다 — " + " | ".join(problems))
    target_key = make_target(store, "diff", diff["diff_id"], agents=agents or _default_agents(), owner=owner)
    return SynthTarget(project_id=project_id, base_snapshot_id=first["snapshot_id"],
                       target_snapshot_id=second["snapshot_id"], diff_id=diff["diff_id"], target_key=target_key,
                       diff=diff, manifest=tuple(records), base=base, target=target)


# ---------------------------------------------------------------- 생산자가 못 만드는 행
# 손으로 심는 JSON 열은 그 열의 스키마로 먼저 검증한다(규칙 R4) — 스키마를 일부러 어기는 시험만 validate=False 를 준다.
_JSON_SCHEMA_COLUMNS = {("rr_diffs", "diff_json"): "rr_diff", ("rr_snapshots", "ir_json"): "rr_ir",
                        ("rr_states", "state_json"): "rr_state"}
SEEDED_RAW: list[tuple[str, str]] = []


def seed_raw(store, table: str, row: Mapping[str, Any], *, reason: str, validate: bool = True) -> None:
    """생산자가 만들 수 없는 '망가진 행' 전용 INSERT. `reason` 은 필수이고 `SEEDED_RAW` 에 남는다."""
    if not (reason or "").strip():
        raise ValueError("seed_raw 는 사유가 필수다 — 생산자 경로로 이 행을 왜 못 만드는지 적는다")
    if validate:
        for (name, column), schema_name in _JSON_SCHEMA_COLUMNS.items():
            if name == table and column in row:
                value = row[column]
                doc = json.loads(value) if isinstance(value, str) else copy.deepcopy(value)
                schema = json.loads((_SCHEMAS / f"{schema_name}.v1.json").read_text(encoding="utf-8"))
                validators.validator_for(schema)(schema).validate(doc)
    columns = list(row)
    store.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                  [row[c] for c in columns])
    SEEDED_RAW.append((table, reason))
