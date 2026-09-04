# build_ir 이 실제로 내는 봉투를 rr_ir.v1.json 으로 검증한다 — 스키마가 픽스처만 보던 사각을 막는다(plan §2)
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from app import ir_builder
from app.adapters import base as adapters_base
from app.adapters import dyna as dyna_adapter

SCHEMA = json.loads(
    (Path(ir_builder.__file__).parent / "schemas" / "rr_ir.v1.json").read_text(encoding="utf-8"))
OWNER = "owner@example.com"
PROJECT = "0123456789abcdef0123456789abcdef"
SNAPSHOT = "fedcba9876543210fedcba9876543210"


def _errors(ir):
    return sorted(f"{'.'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
                  for e in Draft7Validator(SCHEMA).iter_errors(ir))


def _mcad_result(**over):
    """mcad 어댑터가 실제로 내는 모양의 최소 결과.

    값은 손으로 짓지 않고 어댑터 코드의 상수를 그대로 쓴다 — 손으로 쓴 stub 은 '실제 산출을 검증한다' 는
    이 파일의 취지를 무너뜨린다(실제로 `app_version` 을 `None` 으로 적었다가 dict 인 실물을 놓쳤다).
    """
    source = {"kind": "mcad", "app_key": "heax-step_forge", "adapter_version": "1.0",
              "channel": "rest", "ref": {"stepforge_project_id": "SF-1"}, "source_hash": "a" * 64,
              "stats": {}, "app_version": dict(adapters_base.UNKNOWN_APP_VERSION),
              "degraded": [], "captured_at": 1756600000}
    source.update(over.pop("source", {}))
    return {"source": source, "nodes": [], "edges": [], "warnings": [], "degraded": [],
            "call_ids": [], "missing": {}, **over}


class _Recorder:
    """호출을 하나도 내보내지 않는 기록기 — ecad 스텁은 어떤 소스도 부르지 않는다(§2.5.3)."""

    calls: list = []

    def call_ids(self, _kind):
        return []


def _build(**kw):
    return ir_builder.build_ir(project_id=PROJECT, owner_sub=OWNER, label="DV1",
                               adapter_results=[_mcad_result()], snapshot_id=SNAPSHOT,
                               captured_at=1756600000, **kw)


def test_a_captured_app_version_object_validates():
    """소스 앱 버전은 `{version, captured_via, extra}` 객체다(§2.2) — 문자열이 아니다.

    강등(못 읽음)과 정상(읽음) 두 모양 다 실물이라 둘 다 계약을 지켜야 한다.
    """
    read = {"version": "1.4.2", "captured_via": "heaxstep_forge_system_status", "extra": {"build": None}}
    ir = ir_builder.build_ir(project_id=PROJECT, owner_sub=OWNER, label="DV1", snapshot_id=SNAPSHOT,
                             captured_at=1756600000,
                             adapter_results=[_mcad_result(source={"app_version": read})])

    assert _errors(ir) == []
    # 강등 경로(probe 실패)는 기본 픽스처가 이미 쓰는 모양이다.
    assert _errors(_build()) == []


def test_the_envelope_build_ir_actually_produces_validates():
    """스키마는 손으로 쓴 픽스처가 아니라 **실제 산출물**을 기술해야 한다.

    이 시험이 없어서 `primary_source`(봉투에 들어간 지 오래)가 스키마 밖에 남아 있었고,
    최상위 `additionalProperties:false` 라 실제 IR 은 자기 계약을 어기고 있었다.
    """
    assert _errors(_build()) == []


def test_the_envelope_carries_the_organisation_context():
    """§2.2 — 전사 집계는 봉투 최상위 `context.corpus_usage` 이고 소스 하위가 아니다."""
    usage = {"app_key": "heax-kooremapper_mcp", "materials": [], "sections": [], "contacts": [],
             "sessions": 12, "files": 25, "jobs": 8, "fetched_at": 1756600000}
    ir = _build(context={"corpus_usage": usage})

    assert _errors(ir) == []
    assert ir["context"]["corpus_usage"] == usage
    # 통과 기준 (23)(e) — `sources[*].context` 키는 어느 소스에도 없다.
    assert all("context" not in s for s in ir["sources"])


def test_context_absent_is_null_not_missing():
    """4호출이 전부 실패하면 corpus_usage 는 null 이다(§2.2). 키 자체를 없애지 않는다."""
    ir = _build()

    assert ir["context"] == {"corpus_usage": None}
    assert _errors(ir) == []


def test_context_is_not_an_ir_hash_input():
    """§2.2 — context 는 ir_hash 에서 빠진다. compute_ir_hash 허용목록이 구조로 보장한다."""
    bare = _build()
    filled = _build(context={"corpus_usage": {"materials": [1, 2, 3], "fetched_at": 9}})

    assert bare["ir_hash"] == filled["ir_hash"]


def test_every_degraded_code_the_adapters_emit_is_in_the_schema_vocabulary():
    """어댑터가 내는 degraded 코드가 enum 밖이면 그 스냅샷 봉투가 통째로 거부된다.

    실제로 `app_version_unknown`(mcad)이 enum 밖이라 mcad 캡처 봉투가 스키마를 어기고 있었다.
    """
    import re

    vocabulary = set(SCHEMA["definitions"]["degraded_code"]["enum"])
    app = Path(ir_builder.__file__).parent

    # ① 어댑터가 쓰는 리터럴 — add()·update() 뿐 아니라 집합·리스트 리터럴도 훑는다.
    #    (옛 정규식은 add/update 만 봐서 `"degraded": ["ecad_absent"]` 같은 자리를 통째로 놓쳤다.)
    emitted: set[str] = set()
    for path in (app / "adapters").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for block in re.findall(
                r"degraded\.add\([^)]*\)|degraded\.update\(\{[^}]*\}\)"
                r"|degraded[\"']?\s*[:=]\s*[\[{][^\]}]*[\]}]", text):
            emitted.update(re.findall(r"[\"']([a-z][a-z0-9_]*)[\"']", block))
    assert emitted, "어댑터에서 degraded 코드를 하나도 못 읽었다 — 정규식이 낡았다"
    assert emitted <= vocabulary, f"어댑터가 내는데 enum 밖: {sorted(emitted - vocabulary)}"

    # ② 하류가 **읽는** 코드 — 어휘에 없으면 그 분기를 살리는 순간 봉투가 거부된다.
    #    state.py 의 capture_partial · diff.py 의 schema_drift 가 실제로 그런 상태였다.
    consumed: set[str] = set()
    for name in ("state.py", "diff.py"):
        text = (app / name).read_text(encoding="utf-8")
        consumed.update(re.findall(r"[\"']([a-z][a-z0-9_]*)[\"']\s+in\s+\w*degraded", text))
    assert consumed, "하류에서 degraded 코드를 하나도 못 읽었다 — 정규식이 낡았다"
    assert consumed <= vocabulary, f"코드가 읽는데 enum 밖: {sorted(consumed - vocabulary)}"

    # ③ 픽스처가 쓰는 코드 — 픽스처는 실제 봉투를 흉내 낸 것이라 어휘를 벗어나면 안 된다.
    fixture_codes: set[str] = set()
    for path in (Path(__file__).parent / "fixtures").rglob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for src in (doc.get("sources") or []) if isinstance(doc, dict) else []:
            fixture_codes.update(src.get("degraded") or [])
    assert fixture_codes <= vocabulary, f"픽스처가 쓰는데 enum 밖: {sorted(fixture_codes - vocabulary)}"


@pytest.mark.parametrize("kind", ["dyna", "dyna_result"])
def test_absent_source_envelopes_also_validate(kind):
    """부재 소스(_absent)의 소스 dict 도 스키마를 지켜야 한다 — 자격 없는 캡처가 가장 흔한 경로다."""
    absent = dyna_adapter._absent("heax-kooremapper_mcp", 1756600000, "dyna_pat_absent", "자격 없음",
                                  kind=kind)
    ir = ir_builder.build_ir(project_id=PROJECT, owner_sub=OWNER, label="DV1",
                             adapter_results=[_mcad_result(), absent], snapshot_id=SNAPSHOT,
                             captured_at=1756600000)

    assert _errors(ir) == []


def test_the_ecad_stub_envelope_validates():
    """ecad 는 계약만 있는 스텁이라 늘 부재 소스를 낸다 — 가장 자주 도는 경로가 계약을 지켜야 한다."""
    from app.adapters import ecad_stub

    result = ecad_stub.EcadStubAdapter(None).capture({}, None, _Recorder())
    ir = ir_builder.build_ir(project_id=PROJECT, owner_sub=OWNER, label="DV1",
                             adapter_results=[_mcad_result(), result], snapshot_id=SNAPSHOT,
                             captured_at=1756600000)

    assert _errors(ir) == []
    assert "ecad_absent" in ir["sources"][1]["degraded"]
