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
import dataclasses
import json
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import httpx
from jsonschema import validators

from app import config, devseed, engine_client, identity, ir_builder, planner, routes, runner
from app import diff as diff_module
from app.common import canonical_json, now_epoch, sha256_hex

OWNER = "syn@example.com"
CAPTURED_AT = 1756600000
_BACKEND = Path(__file__).resolve().parents[1]
IR_FIXTURES = _BACKEND / "tests" / "fixtures" / "ir"
_SCHEMAS = _BACKEND / "app" / "schemas"


def ident(owner: str = OWNER) -> identity.Identity:
    return identity.Identity(email=owner, display_name="합성", role="user", organization="qa", anonymous=False,
                             source="bearer")


TEST_GATEWAY_SECRET = "factories-gateway-secret"


def delegated_assertion(email: str) -> str:
    """게이트웨이가 사람별 위임으로 받아 오는 단언 — 앱의 실제 발급 함수(`routes.post_auth_sso`)에 위임 헤더를 실어 만든다.

    시크릿은 호출자가 이미 정한 것(`config.heax_gateway_secret`)을 쓴다 — 정하지 않았으면 `act_as_delegate` 가 정한다.
    """
    from starlette.requests import Request  # noqa: PLC0415 — 시험 공장만 쓴다.

    headers = [(b"x-heax-gateway-secret", config.heax_gateway_secret().encode()),
               (b"x-hwax-delegate-email", email.encode())]
    request = Request({"type": "http", "method": "POST", "path": "/api/auth/sso", "headers": headers,
                       "query_string": b""})
    return routes.post_auth_sso(request)["access_token"]


def act_as_delegate(monkeypatch, email: str) -> None:
    """이번 시험의 /mcp 요청을 게이트웨이 위임으로 확인된 그 사람으로 만든다 — MCP 쓰기 도구는 이 신원으로만 쓴다."""
    import app.mcp_server as srv  # noqa: PLC0415 — 순환을 피한다.
    from starlette.requests import Request  # noqa: PLC0415

    if not config.heax_gateway_secret():
        monkeypatch.setattr(config, "heax_gateway_secret", lambda *a, **k: TEST_GATEWAY_SECRET)
    headers = [(identity.SSO_HEADER.encode(), delegated_assertion(email).encode())]
    request = Request({"type": "http", "method": "POST", "path": "/mcp", "headers": headers, "query_string": b""})
    monkeypatch.setattr(srv, "_request", lambda: request)


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


class AdapterShapeError(RuntimeError):
    """공장 입력이 실제 어댑터가 낼 수 없는 모양이다(R-FLOOR-1).

    AssertionError 가 아니다 — xfail(raises=AssertionError) 시험이 공장의 실패를 삼키지 않게 한다(반대 검토 P-02).
    """


def check_adapter_shape(adapter_results: Sequence[Mapping[str, Any]]) -> None:
    """실제 mcad 어댑터만 낼 수 있는 모양인지 본다 — 둘은 어댑터가 한 곳에서만 만든다(adapters/mcad.py).

    - 부품의 min_dim 은 min(size_def) 다(`_shape_attrs`). min_dim 만 바꾼 손 픽스처는 이 모양이 아니라, 짝 있는 부품의 실제 두께
      변경이 내는 거짓 part.moved·part.rotated 를 바닥의 시험이 보지 못했다. 두께는 `set_thickness` 로 바꾼다.
    - 계면의 관통 깊이는 부울 경로가 부피를 냈을 때만 하한이 아니다(`penetration_depth_is_lower_bound = penetration_volume is None`).

    min_dim 이 없는(한쪽 미측정) 부품은 보지 않는다.
    """
    bad = []
    for result in adapter_results:
        if (result.get("source") or {}).get("kind") != "mcad":
            continue
        for node in result.get("nodes") or ():
            attrs = node.get("attrs") or {}
            if node.get("kind") != "part" or attrs.get("min_dim") is None or not attrs.get("size_def"):
                continue
            if abs(float(attrs["min_dim"]) - min(float(x) for x in attrs["size_def"])) > 1e-9:
                bad.append(f"{node.get('label')} min_dim {attrs['min_dim']} ≠ min(size_def) {min(attrs['size_def'])}")
        for edge in result.get("edges") or ():
            attrs = edge.get("attrs") or {}
            if "penetration_depth_is_lower_bound" not in attrs:
                continue
            if bool(attrs["penetration_depth_is_lower_bound"]) != (attrs.get("penetration_volume") is None):
                bad.append(f"{edge.get('kind')} {edge.get('a')}↔{edge.get('b')} is_lower_bound "
                           f"{attrs['penetration_depth_is_lower_bound']} · penetration_volume {attrs.get('penetration_volume')}")
    if bad:
        raise AdapterShapeError("어댑터가 낼 수 없는 mcad 모양이다 — 실제 어댑터는 min_dim 을 min(size_def) 로, 관통 깊이의 하한 여부를"
                                " penetration_volume 의 유무로 낸다. 두께는 factories.set_thickness 로 바꾼다: " + "; ".join(bad))


_SHAPE_KEYS = ("bbox_def", "size_def", "size_sorted", "bbox_world", "centroid_def", "centroid_world", "volume", "min_dim")


def set_thickness(adapter_results: Sequence[dict], label: str, thickness: float, *, twin: str | None = None) -> None:
    """mcad 부품 하나의 판 두께(가장 얇은 축)를 실제 어댑터가 내는 모양으로 바꾼다(R-FLOOR-1) — 제자리에서 고친다.

    모양 칸(bbox·size·centroid·min_dim)은 어댑터 함수(`adapters.mcad._shape_attrs` · `adapters.dyna._bbox_size`)가 다시 낸다.
    부피는 두께에 비례한다. 짝 dyna pid(`twin` 라벨, 없으면 '<묶음>\\<label>' 꼴의 같은 이름)도 같은 두께로 다시 만든다 —
    K 파일도 고친 정상 개정이다.
    짝 있는 부품을 K 파일 그대로 두께만 바꾸는 것(cross.bridge_stale)은 지금 생산자가 거짓 이동·회전을 덧붙이는 길이라
    (devseed.PRODUCER_MISREADS) 합성기의 시험 두 곳(렌더링 통과·덧붙음 재현)에만 둔다. 회전한 부품(bbox_world 크기 ≠
    bbox_def 크기)은 받지 않는다.
    """
    from app.adapters import dyna as dyna_adapter  # noqa: PLC0415 — 이 공장만 쓴다.
    from app.adapters import mcad as mcad_adapter  # noqa: PLC0415

    mcad = next(r for r in adapter_results if (r.get("source") or {}).get("kind") == "mcad")
    attrs = next(n for n in mcad["nodes"] if n.get("kind") == "part" and n.get("label") == label)["attrs"]
    bbox = [float(x) for x in attrs["bbox_def"]]
    world = [float(x) for x in attrs["bbox_world"]]
    size = [bbox[i + 3] - bbox[i] for i in range(3)]
    if any(abs((world[i + 3] - world[i]) - size[i]) > 1e-9 for i in range(3)):
        raise AdapterShapeError(f"{label} 은 조립 좌표에서 회전해 있다 — 이 공장은 회전하지 않은 부품의 두께만 바꾼다")
    axis = size.index(min(size))
    old = size[axis]
    move = [world[i] - bbox[i] for i in range(3)]
    transform = [[1.0, 0.0, 0.0, move[0]], [0.0, 1.0, 0.0, move[1]], [0.0, 0.0, 1.0, move[2]], [0.0, 0.0, 0.0, 1.0]]
    bbox[axis + 3] = bbox[axis] + thickness
    centroid = None
    if attrs.get("centroid_def") is not None:
        centroid = [float(x) for x in attrs["centroid_def"]]
        centroid[axis] = bbox[axis] + thickness / 2.0
    volume = None if attrs.get("volume") is None else float(attrs["volume"]) * thickness / old
    shape = mcad_adapter._shape_attrs({"kind": attrs.get("shape_kind"), "bbox": bbox, "centroid": centroid,
                                       "volume": volume}, depth=attrs.get("depth"), transform=transform,
                                      color=None, step_file=None, shape_def_id=None)
    attrs.update({key: shape[key] for key in _SHAPE_KEYS})
    for result in adapter_results:
        if (result.get("source") or {}).get("kind") != "dyna":
            continue
        for node in result.get("nodes") or ():
            name = str(node.get("label", ""))
            if node.get("kind") != "pid" or (name != twin if twin else name.rsplit("\\", 1)[-1] != label):
                continue
            pid = node["attrs"]
            lo, hi = [float(x) for x in pid["bbox_min"]], [float(x) for x in pid["bbox_max"]]
            before = dyna_adapter._bbox_size(lo, hi)
            hi[axis] = lo[axis] + thickness
            pid["bbox_max"] = hi
            pid["size"] = dyna_adapter._bbox_size(lo, hi)
            pid["size_sorted"] = sorted(pid["size"], reverse=True)
            # 외곽 면적·부피는 K 파일 도구가 낸다 — 판 두께만 바뀐 상자의 변화량으로 옮긴다.
            if pid.get("area_ext") is not None:
                rim = sum(x for i, x in enumerate(before) if i != axis)
                pid["area_ext"] = float(pid["area_ext"]) + 2.0 * rim * (thickness - before[axis])
            if pid.get("volume") is not None:
                pid["volume"] = float(pid["volume"]) * thickness / before[axis]


def make_snapshot(store, project_id: str, adapter_results: Sequence[Mapping[str, Any]], *, label: str,
                  owner: str = OWNER, captured_at: int = CAPTURED_AT, **build_kwargs: Any) -> dict:
    """`ir_builder.freeze_snapshot` 을 그대로 부른다. 반환은 그 함수의 반환이다.

    실제 어댑터가 낼 수 없는 mcad 부품 모양은 받지 않는다(`check_adapter_shape`) — 손 픽스처·합성기 둘 다 이 길을 지난다.
    """
    check_adapter_shape(adapter_results)
    return ir_builder.freeze_snapshot(store, project_id=project_id, owner_sub=owner, label=label,
                                      adapter_results=adapter_results, captured_at=captured_at, **build_kwargs)


def make_diff(store, base_snapshot_id: str, target_snapshot_id: str, *, owner: str = OWNER) -> dict:
    """`diff.create_diff` 를 그대로 부른다 — `rr_diffs`·`rr_diff_events` 가 생산자 경로로 찬다."""
    return diff_module.create_diff(store, base_snapshot_id, target_snapshot_id, owner_sub=owner)


def make_target(store, kind: str, ref_id: str, *, agents: Sequence[Mapping[str, Any]], owner: str = OWNER,
                flow: str = "panels") -> str:
    """`routes.create_target` — 로스터 동결까지(flow='cells' 면 검토 단위까지). 반환은 target_key."""
    with routes_store(store):
        out = routes.create_target(routes.TargetBody(kind=kind, ref_id=ref_id, consent=True, flow=flow,
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
    target_key: str | None          # open_target=False 면 None — 심사 대상은 부른 쪽이 연다(dev 주입)
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
                     spec: devseed.SynthSpec | None = None, check: bool = True,
                     project: Mapping[str, Any] | None = None, open_target: bool = True) -> SynthTarget:
    """합성 다건 변경 타깃 — 대본 → 어댑터 결과 쌍 → 실제 생산자(명명 치수·스냅샷 둘·diff·타깃).

    `project` 는 make_project 의 code·name 이고, `open_target=False` 면 diff 까지만 만든다(dev 주입 — 명단은 실제 입구가 받는다).
    """
    from tests.synth import scripts  # noqa: PLC0415 — 대본은 시험 쪽 모듈이다.

    seed = scripts.SEED if seed is None else seed
    spec = spec or scripts.spec_for(size, seed)
    script = list(script if script is not None else scripts.script_for(size, seed))
    base, target, records = devseed.apply_script(devseed.build_design(spec), script, seed)
    project_id = make_project(store, owner=owner, **dict(project or {}))
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
    target_key = (make_target(store, "diff", diff["diff_id"], agents=agents or _default_agents(), owner=owner)
                  if open_target else None)
    return SynthTarget(project_id=project_id, base_snapshot_id=first["snapshot_id"],
                       target_snapshot_id=second["snapshot_id"], diff_id=diff["diff_id"], target_key=target_key,
                       diff=diff, manifest=tuple(records), base=base, target=target)



# ---------------------------------------------------------------- 러너가 포털에 보내는 패널 본문(세 리포 사슬 시험 EX1)
_PANEL_DECISION = "판정 본문.\n```json\n{\"schema\": \"risk_spec\"}\n```"


@dataclass(frozen=True)
class PanelBody:
    body: dict            # 러너가 포털 `POST /agent/chat` 에 실제로 보낸 요청 본문
    target: SynthTarget
    run: dict             # `runner.run_panel` 의 반환


@contextmanager
def no_network() -> Iterator[None]:
    """주입한 대역(`httpx.MockTransport`) 밖의 HTTP 를 연결 오류로 막는다 — 브리프의 필드 근거·도구 이름 조회가 그 박스의
    실 게이트웨이에 닿지 않게. 시험 파일들의 `no_network` 픽스처와 같은 것이고, 픽스처를 못 쓰는 별도 프로세스가 쓴다."""
    real = httpx.HTTPTransport.handle_request

    def refused(_self, request):
        raise httpx.ConnectError("공장은 외부를 부르지 않는다.", request=request)

    httpx.HTTPTransport.handle_request = refused
    try:
        yield
    finally:
        httpx.HTTPTransport.handle_request = real


def portal_panel_body(store, data_dir: Path | str, size: int = 40, *, seed: int | None = None,
                      engine_budget: int | None = None, owner: str = OWNER,
                      roster: Sequence[Mapping[str, Any]] | None = None) -> PanelBody:
    """합성 다건 변경 타깃에서 러너 한 바퀴를 실모듈로 돌려, 포털이 받는 `/agent/chat` 본문을 돌려준다.

    러너·편성기·브리프·엔진 클라이언트(`PortalPanelEngine`)는 진짜이고 포털과 에이전트 서버만 대역이다 — 에이전트 서버
    `/health` 는 `engine_budget` 을 `evid_budget` 으로 알려 주고(None 이면 옛 엔진처럼 싣지 않는다), 포털은 결정문
    하나로 답한다. 자격은 타깃 owner 가 등록한 포털 PAT 이고 이 박스의 게이트웨이는 위임 헤더를 싣는 판이라(사람별 단언 발급을
    받아 봤다) 좌석이 owner 로 보여 그 diff 를 열 수 있다 — 질문에 `diff_id=` 가 실린다(runner.diff_ref_withheld · SEC-3).
    에이전트 서버 리포의 사슬 시험(tests/test_risk_panel_body_chain.py)이 이 본문을 포털 중계와 엔진에 넣는다.
    """
    synth = make_diff_target(store, size, seed=seed, owner=owner,
                             agents=roster or _default_agents(("mech", "sim", "xd", "rel", "cam"), 3))
    store.upsert_credential(owner, identity.encrypt_pat("pat-synth").decode("ascii"), "sub-synth", owner, "[]",
                            now_epoch() + 30 * 86400)
    runner.note_gateway_mint(store, delegated=True)
    cfg = dataclasses.replace(config.settings, data_dir=Path(data_dir))
    runner.create_job(store, synth.target_key, "C", owner_sub=owner, consent=True, settings=cfg)
    seen: dict = {}

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == engine_client.CONVERSATIONS_PATH:
            return httpx.Response(200, json={"id": "conv-synth"})
        if request.url.path == engine_client.CHAT_PATH:
            seen["body"] = json.loads(request.content.decode())
            frames = [("delib", {"kind": "decision", "text": _PANEL_DECISION}), ("done", {})]
            sse = "".join(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n" for name, data in frames)
            return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})
        info: dict = {"model": "glm-synth"}                                    # 에이전트 서버 /health
        if engine_budget is not None:
            info["evid_budget"] = engine_budget
        return httpx.Response(200, json=info)

    engine = engine_client.PortalPanelEngine(store, cfg, transport=httpx.MockTransport(answer))
    # 발급을 받아 본 박스라면 앱에 게이트웨이 시크릿이 있다 — 비면 러너가 diff_id 를 막는다(gateway_sso_off · 3차 검토 발견 3).
    # 이 공장은 monkeypatch 없는 하위 프로세스(에이전트 서버 사슬 시험)에서도 불리므로 한 바퀴 동안만 바꾸고 되돌린다.
    real_secret = config.heax_gateway_secret
    if not real_secret():
        config.heax_gateway_secret = lambda *a, **k: TEST_GATEWAY_SECRET
    try:
        with no_network():
            out = runner.run_panel(store, cfg, engine, runner.claim_next_job(store, cfg))
    finally:
        config.heax_gateway_secret = real_secret
    if out.get("status") != "done" or "body" not in seen:
        raise RuntimeError(f"러너 한 바퀴가 포털에 본문을 보내고 끝나지 못했다 — {out}")
    return PanelBody(body=seen["body"], target=synth, run=out)

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
