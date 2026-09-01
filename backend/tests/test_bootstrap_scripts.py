# 부트스트랩 스크립트 2종(plan §5.3.4·§5.4.1) — dry-run 기본·멱등·drift 보고만·자격 부재(전부 MockTransport, 실 네트워크 0)
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _load(name: str):
    """backend/scripts/<name>.py 를 모듈로 읽어 온다(패키지가 아니라 실행자 셸 전용 파일이다)."""
    spec = importlib.util.spec_from_file_location(f"hwaxrisk_scripts_{name}", SCRIPTS_DIR / name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ra_boot = _load("bootstrap_ra_ontology.py")
adh_boot = _load("bootstrap_adh.py")

RA_TOKEN = "rat_fake-token"            # 명백한 가짜 — 실 토큰이 아니다
AIDH_KEY = "fake-aidh-key"
PORTAL_PAT = "fake-portal-pat"


def _boom_client() -> httpx.Client:
    """한 번이라도 호출되면 실패시키는 전송(자격 부재 경로 검사용)."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"자격 없이 외부 호출이 나갔다: {request.method} {request.url}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def _stdout_json(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


# ---------------------------------------------------------------- RA 관리 REST 모형
class FakeRa:
    """RA 관리 REST 의 최소 모형 — 축·관계·속성을 실제로 담아 두어 두 번째 실행의 멱등을 본다.

    수정 계열(PATCH·PUT·DELETE)이 오면 그 자리에서 실패시킨다(RA hands-off 계약).
    """

    def __init__(self) -> None:
        self.types: dict[str, dict] = {}
        self.relations: dict[str, dict] = {}
        self.props: dict[int, dict[str, dict]] = {}
        self.rel_props: dict[str, dict[str, dict]] = {}
        self.calls: list[tuple[str, str]] = []
        self._next_id = 1

    def seed_type(self, slug: str, **over) -> dict:
        row = {"id": self._next_id, "slug": slug, "label": slug, "icon": "", "multi": False,
               "sort_order": 0, "description": "", "kind_class": "reference"}
        row.update(over)
        self._next_id += 1
        self.types[slug] = row
        self.props[row["id"]] = {}
        return row

    def seed_relation(self, slug: str, **over) -> dict:
        row = {"id": self._next_id, "slug": slug, "label": slug, "inverse_label": "", "directed": True,
               "transitive": False, "acyclic": False, "src_axis_slugs": None, "dst_axis_slugs": None,
               "sort_order": 0, "description": ""}
        row.update(over)
        self._next_id += 1
        self.relations[slug] = row
        self.rel_props[slug] = {}
        return row

    def seed_prop(self, slug: str, prop: dict) -> None:
        self.props[self.types[slug]["id"]][prop["key"]] = dict(prop)

    # -- 전송 ---------------------------------------------------------------
    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append((method, path))
        assert request.headers["authorization"] == f"Bearer {RA_TOKEN}"
        if method not in ("GET", "POST"):
            raise AssertionError(f"수정 계열 호출이 나갔다: {method} {path}")
        body = json.loads(request.content.decode()) if request.content else {}
        parts = [p for p in path.split("/") if p]

        if parts == ["api", "entity-types"]:
            if method == "GET":
                return self._ok({"items": list(self.types.values())})
            return self._create_type(body)
        if len(parts) == 4 and parts[:2] == ["api", "entity-types"] and parts[3] == "properties":
            return self._properties(self.props.get(int(parts[2]), {}), method, body)
        if parts == ["api", "relation-types"]:
            if method == "GET":
                return self._ok({"items": list(self.relations.values())})
            return self._create_relation(body)
        if len(parts) == 4 and parts[:2] == ["api", "relation-types"] and parts[3] == "properties":
            return self._properties(self.rel_props.get(parts[2], {}), method, body)
        return httpx.Response(404, json={"success": False, "message": f"no route: {path}"})

    def _ok(self, data, status: int = 200) -> httpx.Response:
        return httpx.Response(status, json={"success": True, "data": data})

    def _create_type(self, body: dict) -> httpx.Response:
        if body["slug"] in self.types:
            return httpx.Response(400, json={"success": False, "message": "이미 존재하는 축"})
        return self._ok(self.seed_type(body["slug"], **{k: v for k, v in body.items() if k != "slug"}), 201)

    def _create_relation(self, body: dict) -> httpx.Response:
        if body["slug"] in self.relations:
            return httpx.Response(400, json={"success": False, "message": "이미 존재하는 관계 종류"})
        return self._ok(
            self.seed_relation(body["slug"], **{k: v for k, v in body.items() if k != "slug"}), 201)

    def _properties(self, store: dict, method: str, body: dict) -> httpx.Response:
        if method == "GET":
            return self._ok({"items": list(store.values())})
        if body["key"] in store:
            return httpx.Response(400, json={"success": False, "message": "이미 있는 속성 키"})
        # entity_ref 는 축이 있어야 만들어진다(RA _check_data_type).
        if body.get("data_type") == "entity_ref" and body.get("ref_type_slug"):
            assert body["ref_type_slug"] in self.types, "축보다 속성을 먼저 만들었다"
        store[body["key"]] = dict(body)
        return self._ok(dict(body), 201)


@pytest.fixture
def fake_ra() -> FakeRa:
    """기존 15축·17관계 중 이 계획이 참조하는 것들만 담은 RA(계획 밖 축·관계도 하나씩 둔다)."""
    ra = FakeRa()
    for slug in ("project", "part", "model", "failure_mode", "defect", "incident", "test_run"):
        ra.seed_type(slug, label=f"{slug} 축")
    ra.seed_relation("supersedes", label="대체")
    ra.seed_relation("variant_of", label="변형")
    return ra


def _totals() -> dict:
    return {"types": len(ra_boot.AXES),
            "props": sum(len(v) for v in ra_boot.PROPS.values()),
            "relations": len(ra_boot.RELATIONS),
            "rel_props": sum(len(v) for v in ra_boot.REL_PROPS.values())}


# ---------------------------------------------------------------- RA — 계획표 자체
def test_ra_plan_table_matches_section_5_3(monkeypatch):
    """축 6·관계 12 이고 관계는 전부 directed·비추이, acyclic 은 계보 둘뿐이다(plan §5.3.1~§5.3.2)."""
    assert len(ra_boot.AXES) == 6 and len(ra_boot.RELATIONS) == 12
    assert [a["slug"] for a in ra_boot.AXES] == [
        "expert", "design_snapshot", "design_diff", "assessment", "risk_finding", "design_trait"]
    assert [r["slug"] for r in ra_boot.RELATIONS] == [
        "snapshot_of", "derived_from", "diff_of", "assesses", "assessed_by", "raised_by",
        "concerns", "mitigated_by", "verified_by", "refuted_by", "exhibits", "revision_of"]
    assert all(r["directed"] and not r["transitive"] for r in ra_boot.RELATIONS)
    assert {r["slug"] for r in ra_boot.RELATIONS if r["acyclic"]} == {"derived_from", "revision_of"}
    # 네 record 축은 owner·visibility 를 공통으로 갖는다(plan §5.1 원칙 9).
    for slug in ("design_snapshot", "design_diff", "assessment", "risk_finding"):
        keys = {p["key"] for p in ra_boot.PROPS[slug]}
        assert {"owner", "visibility"} <= keys


def test_ra_property_types_are_within_ra_nine(monkeypatch):
    """RA 속성 타입 9종 밖의 값이 없고 JSON 형은 쓰지 않는다(plan §5.3.1)."""
    allowed = {"text", "longtext", "number", "date", "year", "bool", "enum", "entity_ref", "url"}
    for props in list(ra_boot.PROPS.values()) + list(ra_boot.REL_PROPS.values()):
        for prop in props:
            assert prop["data_type"] in allowed
            if prop["data_type"] == "enum":
                assert prop["enum_options"], f"enum 인데 옵션이 없다: {prop['key']}"
            if prop["data_type"] == "entity_ref":
                assert prop["ref_type_slug"]


def test_ra_enum_values_match_taxonomy_asset():
    """risk_finding 의 enum 은 앱 택소노미 자산과 코드가 같다(assets/taxonomy.v1.json)."""
    from app.taxonomy import load_taxonomy

    axes = load_taxonomy()["axes"]
    props = {p["key"]: p for p in ra_boot.PROPS["risk_finding"]}

    def values(key: str) -> list[str]:
        return [o["value"] for o in props[key]["enum_options"]]

    assert values("domain") == [d["code"] for d in axes["domain"]]
    assert values("change_kind") == [c["code"] for c in axes["change_kind"]]
    assert values("direction") == [d["code"] for d in axes["direction"]]
    assert values("status") == [s["code"] for s in axes["status"]]
    assert values("precedent") == [p["code"] for p in axes["precedent"]]
    mechanisms = []
    for row in axes["mechanism"]:
        if row["mechanism"] not in mechanisms:
            mechanisms.append(row["mechanism"])
    assert values("mechanism") == mechanisms


# ---------------------------------------------------------------- RA — 자격·dry-run·멱등·drift
def test_ra_without_credential_exits_3_and_calls_nothing(monkeypatch, capsys):
    monkeypatch.delenv(ra_boot.CRED_ENV, raising=False)
    code = ra_boot.main(["--base", "https://ra.test", "--apply"], client=_boom_client())
    assert code == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert ra_boot.CRED_ENV in captured.err and "부르지 않고" in captured.err


def test_ra_without_base_exits_1(monkeypatch, capsys):
    monkeypatch.setenv(ra_boot.CRED_ENV, RA_TOKEN)
    assert ra_boot.main([], client=_boom_client()) == 1
    assert "--base" in capsys.readouterr().err


def test_ra_dry_run_lists_every_candidate_and_writes_nothing(monkeypatch, capsys, fake_ra):
    monkeypatch.setenv(ra_boot.CRED_ENV, RA_TOKEN)
    assert ra_boot.main(["--base", "https://ra.test"], client=fake_ra.client()) == 0

    result = _stdout_json(capsys)
    assert result["mode"] == "dry-run"
    assert result["created"] == {"types": 0, "props": 0, "relations": 0, "rel_props": 0}
    assert result["skipped"] == {"types": 0, "props": 0, "relations": 0, "rel_props": 0}
    assert result["drift"] == [] and result["existing_unchanged"] is None
    assert {k: len(v) for k, v in result["candidates"].items()} == _totals()
    assert {m for m, _ in fake_ra.calls} == {"GET"}          # dry-run 은 GET 만 부른다
    assert fake_ra.types.keys() == {"project", "part", "model", "failure_mode", "defect",
                                    "incident", "test_run"}


def test_ra_apply_creates_in_fixed_order_then_is_idempotent(monkeypatch, capsys, fake_ra):
    monkeypatch.setenv(ra_boot.CRED_ENV, RA_TOKEN)
    assert ra_boot.main(["--base", "https://ra.test", "--apply"], client=fake_ra.client()) == 0

    first = _stdout_json(capsys)
    assert first["mode"] == "apply" and first["created"] == _totals()
    assert first["drift"] == [] and first["existing_unchanged"] is True

    # 축 → 축 속성 → 관계 종류 → 관계 속성 순서(관계가 축 slug 를 참조한다).
    posts = [path for method, path in fake_ra.calls if method == "POST"]
    def phase(path: str) -> int:
        if path == "/api/entity-types":
            return 0
        if path.startswith("/api/entity-types/"):
            return 1
        return 2 if path == "/api/relation-types" else 3
    assert [phase(p) for p in posts] == sorted(phase(p) for p in posts)

    # 두 번째 실행 — 생성 0건, 전부 건너뜀, drift 없음.
    fake_ra.calls.clear()
    assert ra_boot.main(["--base", "https://ra.test", "--apply"], client=fake_ra.client()) == 0
    second = _stdout_json(capsys)
    assert second["created"] == {"types": 0, "props": 0, "relations": 0, "rel_props": 0}
    assert second["skipped"] == _totals()
    assert second["drift"] == [] and second["existing_unchanged"] is True
    assert all(m == "GET" for m, _ in fake_ra.calls)


def test_ra_apply_leaves_preexisting_axes_untouched(monkeypatch, capsys, fake_ra):
    monkeypatch.setenv(ra_boot.CRED_ENV, RA_TOKEN)
    before = json.dumps([fake_ra.types[s] for s in sorted(fake_ra.types)], ensure_ascii=False)
    assert ra_boot.main(["--base", "https://ra.test", "--apply"], client=fake_ra.client()) == 0
    capsys.readouterr()
    after = json.dumps([fake_ra.types[s] for s in sorted(fake_ra.types)
                        if s not in ra_boot.PLANNED_AXES], ensure_ascii=False)
    assert after == before
    assert fake_ra.relations["supersedes"]["label"] == "대체"


def test_ra_reports_drift_without_calling_update(monkeypatch, capsys, fake_ra):
    """정의가 다른 축·관계·속성은 drift 로 보고만 하고 종료 코드 2 다(update 계열 호출 0)."""
    monkeypatch.setenv(ra_boot.CRED_ENV, RA_TOKEN)
    fake_ra.seed_type("design_trait", label="설계 성격", kind_class="record")     # 계획은 reference
    fake_ra.seed_type("assessment", label="심사 판정", kind_class="record")
    fake_ra.seed_prop("assessment", {"key": "stance", "data_type": "enum", "required": False,
                                     "multi": False, "ref_type_slug": None,
                                     "enum_options": [{"value": "agree"}, {"value": "oppose"}]})
    fake_ra.seed_relation("revision_of", label="후속 과제", acyclic=False,     # 계획은 acyclic
                          src_axis_slugs=["project"], dst_axis_slugs=["project"])

    assert ra_boot.main(["--base", "https://ra.test", "--apply"], client=fake_ra.client()) == 2

    result = _stdout_json(capsys)
    drift = {(d["kind"], d["name"], d["field"]) for d in result["drift"]}
    assert ("entity_type", "design_trait", "kind_class") in drift
    assert ("property", "assessment.stance", "enum_options") in drift
    assert ("relation_type", "revision_of", "acyclic") in drift
    assert ("entity_type", "assessment", "kind_class") not in drift     # 같은 정의는 drift 가 아니다
    # drift 가 있어도 없는 것은 그대로 만든다 — 있는 것을 고치지는 않는다.
    assert result["created"]["types"] == len(ra_boot.AXES) - 2
    assert result["skipped"]["types"] == 2 and result["skipped"]["props"] == 1
    assert all(method in ("GET", "POST") for method, _ in fake_ra.calls)


# ---------------------------------------------------------------- AIDataHub MCP 모형
class FakeAdh:
    """게이트웨이 MCP 의 최소 모형 — doc_type·에이전트를 담아 두 번째 실행의 멱등을 본다."""

    def __init__(self) -> None:
        self.doc_types: dict[str, dict] = {}
        self.agents: dict[str, dict] = {}
        self.tools: list[str] = []

    def seed_doc_type(self, code: str, **over) -> None:
        row = {"code": code, "name": code, "description": "", "expected_sections": []}
        row.update(over)
        self.doc_types[code] = row

    def seed_agent(self, agent_type: str, **over) -> None:
        row = {"agent_type": agent_type, "name": agent_type, "description": "", "common_tags": []}
        row.update(over)
        self.agents[agent_type] = row

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {PORTAL_PAT}"
        payload = json.loads(request.content.decode())
        if payload["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {}},
                                  headers={"mcp-session-id": "sess-adh"})
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        name = payload["params"]["name"]
        args = payload["params"]["arguments"]
        self.tools.append(name)
        return self._rpc(self._tool(name, args))

    def _tool(self, name: str, args: dict):
        if name == "list_doc_types":
            assert args["api_key"] == AIDH_KEY
            return {"doc_types": list(self.doc_types.values())}
        if name == "list_agents":
            return list(self.agents.values())
        if name == "create_doc_type":
            assert args["api_key"] == AIDH_KEY
            row = args["doc_type"]
            if row["code"] in self.doc_types:
                return {"status": "error", "error": "duplicate", "code": "create_failed"}
            self.seed_doc_type(row["code"], **{k: v for k, v in row.items() if k != "code"})
            return {"status": "created", "code": row["code"]}
        if name == "create_agent":
            assert args["api_key"] == AIDH_KEY
            row = args["agent"]
            if row["agent_type"] in self.agents:
                return {"status": "error", "error": "duplicate", "code": "duplicate"}
            self.seed_agent(row["agent_type"], **{k: v for k, v in row.items() if k != "agent_type"})
            return {"status": "created", "agent_type": row["agent_type"]}
        raise AssertionError(f"계약에 없는 도구를 불렀다: {name}")

    @staticmethod
    def _rpc(result) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1,
                                         "result": {"structuredContent": result}})


@pytest.fixture
def adh_env(monkeypatch):
    monkeypatch.setenv(adh_boot.API_KEY_ENV, AIDH_KEY)
    monkeypatch.setenv(adh_boot.PORTAL_PAT_ENV, PORTAL_PAT)


def _adh_totals() -> dict:
    return {"doc_types": len(adh_boot.DOC_TYPES), "agents": 1}


# ---------------------------------------------------------------- AIDataHub — 계획표·자격·dry-run·멱등·drift
def test_adh_plan_table_matches_section_5_4():
    """doc_type 3종·의사 에이전트 1이고 섹션 수는 §5.4.1 표 그대로다."""
    assert [d["code"] for d in adh_boot.DOC_TYPES] == [
        "risk_review_opinion", "risk_review_panel", "project_character"]
    sections = {d["code"]: len(d["expected_sections"]) for d in adh_boot.DOC_TYPES}
    assert sections == {"risk_review_opinion": 7, "risk_review_panel": 9, "project_character": 12}
    assert all(d["mode"] == "llm_context" for d in adh_boot.DOC_TYPES)
    assert adh_boot.AGENT["agent_type"] == "risk-review-memory"
    assert adh_boot.AGENT["common_tags"] == ["hwax-risk-review"]
    # `bind_records_to_agent`·`patch_agent` 는 계약에 없다(plan §5.4.7).
    assert set(adh_boot.WRITE_TOOLS) == {"create_doc_type", "create_agent"}


@pytest.mark.parametrize("present", [(), ("api_key",), ("pat",)])
def test_adh_without_credential_exits_3_and_calls_nothing(monkeypatch, capsys, present):
    monkeypatch.delenv(adh_boot.API_KEY_ENV, raising=False)
    monkeypatch.delenv(adh_boot.PORTAL_PAT_ENV, raising=False)
    if "api_key" in present:
        monkeypatch.setenv(adh_boot.API_KEY_ENV, AIDH_KEY)
    if "pat" in present:
        monkeypatch.setenv(adh_boot.PORTAL_PAT_ENV, PORTAL_PAT)

    code = adh_boot.main(["--base", "https://gw.test/mcp", "--apply"], client=_boom_client())
    assert code == 3
    captured = capsys.readouterr()
    assert captured.out == "" and "부르지 않고" in captured.err


def test_adh_dry_run_lists_candidates_and_writes_nothing(adh_env, capsys):
    fake = FakeAdh()
    assert adh_boot.main(["--base", "https://gw.test/mcp"], client=fake.client()) == 0

    result = _stdout_json(capsys)
    assert result["mode"] == "dry-run"
    assert result["created"] == {"doc_types": 0, "agents": 0}
    assert result["skipped"] == {"doc_types": 0, "agents": 0}
    assert result["candidates"] == {"doc_types": [d["code"] for d in adh_boot.DOC_TYPES],
                                    "agents": ["risk-review-memory"]}
    assert result["drift"] == []
    assert fake.tools == ["list_doc_types", "list_agents"]
    assert fake.doc_types == {} and fake.agents == {}


def test_adh_apply_then_second_run_is_idempotent(adh_env, capsys):
    fake = FakeAdh()
    assert adh_boot.main(["--base", "https://gw.test/mcp", "--apply"], client=fake.client()) == 0
    first = _stdout_json(capsys)
    assert first["created"] == _adh_totals()
    assert fake.tools.count("create_doc_type") == 3 and fake.tools.count("create_agent") == 1
    assert set(fake.doc_types) == {"risk_review_opinion", "risk_review_panel", "project_character"}
    assert fake.agents["risk-review-memory"]["common_tags"] == ["hwax-risk-review"]

    fake.tools.clear()
    assert adh_boot.main(["--base", "https://gw.test/mcp", "--apply"], client=fake.client()) == 0
    second = _stdout_json(capsys)
    assert second["created"] == {"doc_types": 0, "agents": 0}
    assert second["skipped"] == _adh_totals()
    assert second["drift"] == []
    assert fake.tools == ["list_doc_types", "list_agents"]        # 쓰기 도구는 다시 부르지 않는다


def test_adh_reports_drift_without_touching_existing(adh_env, capsys):
    fake = FakeAdh()
    fake.seed_doc_type("risk_review_opinion", name="리스크 심사 좌석 의견",
                       description=adh_boot.DOC_TYPES[0]["description"],
                       expected_sections=["대상과 변화 요약", "관점(도메인) 평가"])
    fake.seed_agent("risk-review-memory", name="리스크 심사 기억",
                    description=adh_boot.AGENT["description"], common_tags=["hwax-risk-review", "x"])

    assert adh_boot.main(["--base", "https://gw.test/mcp", "--apply"], client=fake.client()) == 2

    result = _stdout_json(capsys)
    drift = {(d["kind"], d["name"], d["field"]) for d in result["drift"]}
    assert ("doc_type", "risk_review_opinion", "expected_sections") in drift
    assert ("agent", "risk-review-memory", "common_tags") in drift
    assert ("doc_type", "risk_review_opinion", "name") not in drift
    # 있는 것은 건너뛰고 없는 두 doc_type 만 만든다 — 갱신 도구는 없다.
    assert result["created"] == {"doc_types": 2, "agents": 0}
    assert result["skipped"] == {"doc_types": 1, "agents": 1}
    assert fake.doc_types["risk_review_opinion"]["expected_sections"] == [
        "대상과 변화 요약", "관점(도메인) 평가"]


def test_adh_tool_error_ends_with_code_1(adh_env, capsys):
    """쓰기 도구가 `{status:'error'}` 를 주면 실패로 본다(중복은 error 로 온다)."""
    fake = FakeAdh()

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode())
        if payload["method"] != "tools/call":
            return fake.handler(request)
        if payload["params"]["name"] == "create_doc_type":
            return FakeAdh._rpc({"status": "error", "error": "duplicate", "code": "create_failed"})
        return fake.handler(request)

    code = adh_boot.main(["--base", "https://gw.test/mcp", "--apply"],
                         client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "create_doc_type" in captured.err


# ---------------------------------------------------------------- 암호화 백업 래퍼(plan §5.2.5 (3a)·§0.9 P1-16)
BACKUP_SCRIPT = SCRIPTS_DIR / "backup-to-drive.sh"


def _dry_run(data_dir: Path, env_extra: dict | None = None) -> list[str]:
    import os
    import subprocess

    env = {**os.environ, "HWAXRISK_DATA_DIR": str(data_dir), **(env_extra or {})}
    env.pop("HWAXRISK_BACKUP_KEY", None)
    env.update(env_extra or {})
    out = subprocess.run([str(BACKUP_SCRIPT), "--dry-run"], capture_output=True, text=True, env=env, check=True)
    return [line for line in out.stdout.splitlines() if line and not line.startswith("#")]


def _data_dir(tmp_path: Path) -> Path:
    (tmp_path / "risk_review.db").write_text("db", encoding="utf-8")
    (tmp_path / "risk_review.db-wal").write_text("wal", encoding="utf-8")
    (tmp_path / "exports").mkdir()
    (tmp_path / "exports" / "1.jsonl").write_text("{}", encoding="utf-8")
    (tmp_path / "origin.json").write_text("{}", encoding="utf-8")
    (tmp_path / "secrets.env").write_text("HWAXRISK_BACKUP_KEY=age1testrecipient\n", encoding="utf-8")
    return tmp_path


def test_backup_wrapper_puts_only_encrypted_copies_in_the_tar(tmp_path):
    """평문 DB·exports 는 0건이고 `.age` 사본이 각 1건이다(등급 있는 원문은 평문 tar 에 싣지 않는다)."""
    members = _dry_run(_data_dir(tmp_path))
    assert members.count("risk_review.db.age") == 1
    assert members.count("exports.tar.age") == 1
    assert "risk_review.db" not in members and "risk_review.db-wal" not in members
    assert not any(m.startswith("exports/") or m == "exports" for m in members)
    assert "secrets.env" not in members and "origin.json" in members


def test_backup_wrapper_warns_when_the_age_key_is_missing(tmp_path):
    """키가 없으면 backup_unencrypted 를 찍고 평문으로 진행한다(백업 자체는 막지 않는다)."""
    import os
    import subprocess

    data_dir = _data_dir(tmp_path)
    (data_dir / "secrets.env").write_text("# 키 없음\n", encoding="utf-8")
    env = {**os.environ, "HWAXRISK_DATA_DIR": str(data_dir)}
    env.pop("HWAXRISK_BACKUP_KEY", None)
    out = subprocess.run([str(BACKUP_SCRIPT), "--dry-run"], capture_output=True, text=True, env=env, check=True)
    assert "backup_unencrypted" in out.stdout
    members = [line for line in out.stdout.splitlines() if line and not line.startswith(("#", "⚠"))]
    assert "risk_review.db" in members and "risk_review.db.age" not in members


# ---------------------------------------------------------------- 사전 편집·재키(plan §2.7.1 · §0.9 P2-12)
def _admin():
    return type("I", (), {"anonymous": False, "email": "admin@example.com", "role": "admin",
                          "to_dict": lambda self: {}})()


def test_vocab_edits_bump_the_version_and_gate_a_second_major(risk_store, monkeypatch):
    """동의어 추가는 마이너, stop-token 추가는 메이저이고 재계산 전 두 번째 메이저는 409 다."""
    from app import main, routes
    from app.errors import AppError

    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    minor = routes.post_vocab_synonyms(
        routes.VocabSynonymBody(head="pcb", **{"from": ["mainpcb"]}), ident=_admin())
    assert minor["vocab_version"] == "1.1" and minor["bump"] == "minor"
    assert routes.vocab_recompute_pending(risk_store) is False

    major = routes.post_vocab_stop_tokens(routes.VocabStopTokenBody(tokens=["draft"]), ident=_admin())
    assert major["vocab_version"] == "2.0" and major["recompute_required"] is True
    assert routes.vocab_recompute_pending(risk_store) is True
    monkeypatch.setattr(main, "get_store", lambda: risk_store)
    assert "vocab_recompute_pending" in main.health_warnings()

    with pytest.raises(AppError) as second:
        routes.post_vocab_stop_tokens(routes.VocabStopTokenBody(tokens=["wip"]), ident=_admin())
    assert (second.value.code, second.value.http_status) == ("vocab_recompute_required", 409)

    # 비관리자는 편집할 수 없다.
    user = type("I", (), {"anonymous": False, "email": "u@x", "role": "user",
                          "to_dict": lambda self: {}})()
    with pytest.raises(AppError) as role:
        routes.post_vocab_synonyms(routes.VocabSynonymBody(head="pcb", **{"from": ["x"]}), ident=user)
    assert role.value.http_status == 403


def test_recompute_part_keys_is_dry_run_by_default_and_idempotent(risk_store, monkeypatch):
    """재계산은 별칭 행만 더한다 — ckey·ir_hash 불변이고 2회 실행에 새 행 0 이다."""
    from app import routes

    script = _load("recompute_part_keys.py")
    monkeypatch.setattr(routes, "get_store", lambda: risk_store)
    risk_store.execute(
        "INSERT INTO rr_part_keys(ckey, owner_sub, status, name_norm_canon, geom_bucket, material_norm,"
        " vocab_version, created_at, updated_at) VALUES ('ck:old000000001', 'u@x', 'candidate',"
        " 'plate_draft', 'bx:1', 'al6061', '1.0', 1, 1)")
    routes.post_vocab_stop_tokens(routes.VocabStopTokenBody(tokens=["draft"]), ident=_admin())

    planned = script.plan_rows(risk_store)
    assert len(planned) == 1 and planned[0]["merged_into"] == "ck:old000000001"
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_part_keys")["n"] == 1   # dry-run 은 쓰지 않는다

    written = script.apply_rows(risk_store, planned, vocab_version="2.0")
    assert written == 1
    rows = risk_store.query(
        "SELECT ckey, status, merged_into, decided_by FROM rr_part_keys ORDER BY ckey")
    new_row = next(r for r in rows if r["decided_by"] == script.DECIDED_BY)
    assert (new_row["status"], new_row["merged_into"]) == ("merged", "ck:old000000001")
    # 옛 행은 그대로다(ckey 불변).
    assert any(r["ckey"] == "ck:old000000001" and r["status"] == "candidate" for r in rows)
    assert routes.vocab_recompute_pending(risk_store) is False

    # 2회 실행에 새 행 0.
    assert script.apply_rows(risk_store, script.plan_rows(risk_store), vocab_version="2.0") == 0
    assert risk_store.query_one("SELECT COUNT(*) AS n FROM rr_part_keys")["n"] == 2
