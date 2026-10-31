# RA 보내는 쪽(RK-01 — 사용자 결정 10-31 D-1 (가)) 검증 — 부른 것을 적는 게이트웨이 · RA 대역으로 번역 · id 사상 · 보류 · 꺼짐 · 실패 사유를 본다
from __future__ import annotations

import json
import re
import types

import httpx
import pytest

from app import character, common, metrics, nightly, ra_client

OWNER = "owner@example.com"
PROJECT = "p-rk01"
TARGET = "diff:" + "d" * 32
TARGET_B = "diff:" + "e" * 32
CK = "a1b2c3d4e5f6"
FINDING = "f-rk01"
RW = "rw-pat-for-test"
READ = "read-pat-for-test"
NOW = 1_800_000_000
CODE = f"{TARGET}#{CK}"


# ---------------------------------------------------------------- 게이트웨이 · RA 대역
class FakeGateway:
    """게이트웨이 + RA 대역 — MCP JSON-RPC(initialize · tools/call)를 받아 RA 온톨로지 쓰기를 흉내 내고 부른 것을 적는다.

    RA 의 실제 계약(ReportArchive mcp_server · ai/agent_tools)을 따른다 — get_object(type, id) · create_object(type_slug, value, code,
    properties, description) · update_object(object_id, properties — 통째 교체) · link_objects(src_id, dst_id, relation, properties).
    도구는 게이트웨이의 호출 전용 별칭(reportarchive_<이름>)으로만 받는다(맨 이름은 겹치면 접두가 붙어 바뀐다). 쓰기는 시스템 관리자
    토큰만이고 RA 의 실패는 성공 답 안의 {"error": …} 다(RA MCP 가 HTTP 상태를 글로만 넘긴다). 나가는 답은 게이트웨이 HG-20 처럼
    owner 칸과 메일 꼴 글을 `[가림:…]` 로 가린다. `fail[이름]` 에 넣은 답은 그 도구의 다음 호출이 차례로 받는다.
    """

    TYPES = {"risk_finding", "design_trait", "project", "incident", "test_run", "report"}
    RELATIONS = {"verified_by": ({"risk_finding"}, {"incident", "test_run"}),
                 "refuted_by": ({"risk_finding"}, {"incident", "test_run"}),
                 "exhibits": ({"project", "design_snapshot"}, {"design_trait"})}
    WRITES = {"create_object", "update_object", "add_object_alias", "link_objects"}
    EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

    def __init__(self, *, tokens=(RW, READ), admins=(RW,), readonly=(), mask=True):
        self.objects: dict[int, dict] = {}
        self.links: dict[tuple[int, int, str], dict] = {}
        self.calls: list[tuple[str, dict, str]] = []
        self.methods: list[str] = []
        # 게이트웨이가 받는 토큰 · 그 가운데 RA 시스템 관리자 계정의 것 · 읽기 전용(scopes 에 read 만)인 것.
        self.tokens, self.admins, self.readonly = set(tokens), set(admins), set(readonly)
        self.mask = mask
        self.fail: dict[str, list] = {}
        self._next = 100

    def seed(self, type_slug: str, value: str, code: str | None = None, properties: dict | None = None) -> int:
        self._next += 1
        self.objects[self._next] = {"type_slug": type_slug, "value": value, "code": code, "description": "",
                                    "properties": dict(properties or {})}
        return self._next

    def tools(self) -> list[str]:
        return [name for name, _args, _bearer in self.calls]

    # -- RA 쪽 -----------------------------------------------------------
    def _brief(self, oid: int) -> dict:
        obj = self.objects[oid]
        return {"id": oid, "value": obj["value"], "type_slug": obj["type_slug"], "code": obj["code"],
                "description": obj["description"] or None, "status": "active", "properties": dict(obj["properties"])}

    def _create_object(self, args: dict) -> dict:
        slug, value, code = args.get("type_slug"), str(args.get("value") or ""), args.get("code")
        if slug not in self.TYPES:
            return {"error": f"알 수 없는 타입(type_slug): {slug!r}"}
        for by in ("code", "value"):           # RA resolve_existing — code 가 먼저, 없으면 value(대소문자 무시)
            want = code if by == "code" else value
            for oid, obj in self.objects.items():
                if want and obj["type_slug"] == slug and str(obj[by] or "").casefold() == str(want).casefold():
                    return {"created": False, "object": self._brief(oid)}
        oid = self.seed(slug, value, code, args.get("properties"))
        self.objects[oid]["description"] = args.get("description") or ""
        return {"created": True, "object": self._brief(oid)}

    def _get_object(self, args: dict) -> dict:
        oid = int(args["id"]) if str(args.get("id") or "").isdigit() else None
        obj = self.objects.get(oid)
        if obj is None or obj["type_slug"] != args.get("type"):
            return {"error": f"객체를 찾을 수 없습니다: {args.get('type')}:{args.get('id')}"}
        return {"type": obj["type_slug"], "id": str(oid), "label": obj["value"], "kind": "record",
                "properties": dict(obj["properties"]), "relations": [], "reports": []}

    def _update_object(self, args: dict) -> dict:
        obj = self.objects.get(int(args["object_id"]))
        if obj is None:
            return {"error": f"객체를 찾을 수 없습니다: {args['object_id']}"}
        obj["properties"] = dict(args.get("properties") or {})
        return {"updated": True, "object": self._brief(int(args["object_id"]))}

    def _link_objects(self, args: dict) -> dict:
        src, dst = self.objects.get(int(args["src_id"])), self.objects.get(int(args["dst_id"]))
        if src is None or dst is None:
            return {"error": f"객체를 찾을 수 없습니다: src={args['src_id']}, dst={args['dst_id']}"}
        allowed = self.RELATIONS.get(args.get("relation"))
        if allowed is None or src["type_slug"] not in allowed[0] or dst["type_slug"] not in allowed[1]:
            return {"error": f"관계 축 제약 위반: {args.get('relation')}"}
        self.links[(int(args["src_id"]), int(args["dst_id"]), args["relation"])] = dict(args.get("properties") or {})
        return {"ok": True, "src_id": int(args["src_id"]), "dst_id": int(args["dst_id"]), "relation": args["relation"]}

    # -- 게이트웨이 쪽 -----------------------------------------------------
    def _masked(self, value, key=None):
        if isinstance(value, dict):
            return {k: self._masked(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self._masked(v, key) for v in value]
        if isinstance(value, str):
            return "[가림:이름]" if key == "owner" else self.EMAIL.sub("[가림:메일]", value)
        return value

    def handler(self, request: httpx.Request) -> httpx.Response:
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if bearer not in self.tokens:
            return httpx.Response(401, text="invalid token")
        payload = json.loads(request.content.decode())
        self.methods.append(payload["method"])
        if payload["method"] == "initialize":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": {}},
                                  headers={"mcp-session-id": "sess-1"})
        if payload["method"] == "notifications/initialized":
            return httpx.Response(202)
        name, args = payload["params"]["name"], dict(payload["params"].get("arguments") or {})
        self.calls.append((name, args, bearer))
        canned = self.fail.get(name) or []
        if canned:
            kind, value = canned.pop(0)
            if kind == "http":
                return httpx.Response(value, text="upstream")
            if kind == "rpc_error":                                     # JSON-RPC 오류(인자 꼴 · 메서드) — 결과 없이 error 만 온다
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"],
                                                 "error": {"code": -32602, "message": value}})
            if kind == "tool_error":
                return self._reply(payload, {"isError": True, "content": [{"type": "text", "text": value}]})
            return self._ok(payload, {"error": value})
        if not name.startswith(ra_client.GATEWAY_ALIAS_PREFIX):
            return self._reply(payload, {"isError": True, "content": [{"type": "text", "text": f"unknown tool: {name}"}]})
        tool = name[len(ra_client.GATEWAY_ALIAS_PREFIX):]
        if tool in self.WRITES and bearer in self.readonly:
            return self._reply(payload, {"isError": True, "content": [{"type": "text", "text": (
                f"read_only: '{name}' — 읽기 전용 토큰(scopes 에 read 만)은 조회 도구만 부른다.")}]})
        if tool in self.WRITES and bearer not in self.admins:
            return self._ok(payload, {"error": "시스템 관리자 권한이 필요합니다."})
        return self._ok(payload, getattr(self, f"_{tool}")(args))

    def _ok(self, payload: dict, result: dict) -> httpx.Response:
        shown = self._masked(result) if self.mask else result
        return self._reply(payload, {"structuredContent": shown,
                                     "content": [{"type": "text", "text": json.dumps(shown, ensure_ascii=False)}]})

    @staticmethod
    def _reply(payload: dict, result: dict) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})


# ---------------------------------------------------------------- 한 박스
@pytest.fixture
def clock():
    previous = common.set_clock(lambda: NOW)
    yield NOW
    common.set_clock(previous)


def write_secrets(data_dir, **values: str) -> None:
    path = data_dir / "secrets.env"
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    path.chmod(0o600)


@pytest.fixture
def box(risk_store, tmp_path, clock):
    """과제(조직 공개) · 대상 · finding · 등록부 행 하나와 박스 쓰기 PAT · 읽기 PAT 가 있는 박스, 그리고 게이트웨이 대역."""
    risk_store.execute(
        "INSERT INTO rr_projects(id, owner_sub, code, name, mcp_visibility, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (PROJECT, OWNER, "P-RK01", "합성 과제", "org", 100, 100))
    for key in (TARGET, TARGET_B):
        risk_store.execute(
            "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, level, external_sync_json,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (key, OWNER, "diff", key[5:], PROJECT, "h" * 12, "C0", json.dumps(ra_client.empty_sync()), 200, 200))
    risk_store.execute(
        "INSERT INTO rr_findings(finding_id, claim_uid, origin, target_key, panel_id, project_id, owner_sub, direction,"
        " domain, mechanism, mechanism_detail, change_kind, subject_key, severity, sev3, judgement, evidence_grade,"
        " precedent, cluster_key, finding_json, status, status_source, created_at, updated_at)"
        " VALUES (?,?,'llm',?,'pn-1',?,?,'risk','mech','thermal','cte_mismatch','dimension',?,'중대',2,'WARNING',"
        " '문헌·규격','in_range',?,'{}','open','code',100,100)",
        (FINDING, f"{FINDING}#c", TARGET, PROJECT, OWNER, f"ck:{CK}", CK))
    risk_store.execute(
        "INSERT INTO rr_registry(target_key, cluster_key, owner_sub, merged_json, support, contested, subject_key,"
        " mechanism, mechanism_detail, status, status_source, updated_at) VALUES (?,?,?,'{}',1,0,?,?,?,'open','code',1)",
        (TARGET, CK, OWNER, f"ck:{CK}", "thermal", "cte_mismatch"))
    write_secrets(tmp_path, HWAXRISK_PORTAL_PAT=READ, HWAXRISK_PORTAL_PAT_RW=RW)
    fake = FakeGateway()
    settings = types.SimpleNamespace(data_dir=tmp_path, gateway_mcp="https://gw.test/mcp")
    client = httpx.Client(transport=httpx.MockTransport(fake.handler))
    sender = ra_client.RaSender(settings, client=client)
    yield types.SimpleNamespace(store=risk_store, data_dir=tmp_path, fake=fake, settings=settings, sender=sender)
    client.close()


def tick(box) -> dict:
    return nightly.retry_external_sync(box.store, now=common.now_epoch(), send=box.sender)


def ra_entry(box, target_key=TARGET) -> dict:
    return ra_client.load_external_sync(box.store, target_key)["ra"]


def summary(box, target_key=TARGET) -> dict:
    return ra_client.sync_summary(ra_client.load_external_sync(box.store, target_key),
                                  status=ra_client.sender_status(box.settings))["ra"]


def label(box, evidence_ref: str, outcome: str = "confirmed") -> dict:
    return metrics.record_label(box.store, finding_id=FINDING, source="expert_review", outcome=outcome,
                                evidence_ref=evidence_ref, owner_sub=OWNER, labeled_by=OWNER)


def id_map(box) -> dict:
    return {(r["portal_kind"], r["portal_id"]): (r["ra_entity_id"], r["ra_type_slug"], r["owner_sub"])
            for r in box.store.query("SELECT * FROM rr_id_map")}


# ---------------------------------------------------------------- 번역 — 라벨(상태 병합 · verified_by)
def test_label_ops_create_the_finding_and_link_the_incident_under_the_box_pat(box):
    """라벨 op 둘이 RA 도구 호출로 옮겨진다 — 없는 risk_finding 은 code 로 만들고, 근거 inc:<id> 가 사고면 verified_by 로 잇는다."""
    incident = box.fake.seed("incident", "사고 2026-0042")
    out = label(box, f"inc:{incident}")
    assert [op["op"] for op in ra_entry(box)["pending_ops"]] == ["merge_object", "link"]

    assert tick(box) == {"due": 1, "sent": 1, "failed": 0}

    alias = ra_client.GATEWAY_ALIAS_PREFIX
    assert box.fake.tools() == [alias + "create_object", alias + "get_object", alias + "get_object", alias + "link_objects"]
    create = box.fake.calls[0][1]
    assert (create["type_slug"], create["code"]) == ("risk_finding", CODE)
    assert create["value"] == f"P-RK01@thermal.cte_mismatch@{CODE}"
    assert create["properties"] == {"cluster_key": CK, "portal_registry_key": CODE, "owner": OWNER,
                                    "visibility": "org", "status": "verified"}
    ra_id = next(oid for oid, obj in box.fake.objects.items() if obj["code"] == CODE)
    assert box.fake.calls[1][1] == {"type": "incident", "id": str(incident)}           # 근거가 사고 객체인지 본다
    assert box.fake.calls[2][1] == {"type": "risk_finding", "id": str(ra_id)}           # 사상된 id 가 살아 있는지 본다
    assert box.fake.links == {(ra_id, incident, "verified_by"): {"label_id": out["label_id"], "source": "expert_review"}}
    # 배경 잡의 자격은 박스 쓰기 PAT 하나다(D-1 (가)) — 같은 박스의 읽기 PAT 는 한 번도 나가지 않는다.
    assert {bearer for _name, _args, bearer in box.fake.calls} == {RW}

    entry = ra_entry(box)
    assert entry["state"] == "done" and entry["pending_ops"] == []
    assert id_map(box) == {("registry", CODE): (ra_id, "risk_finding", OWNER)}
    assert box.store.query_one("SELECT ra_entity_id FROM rr_registry WHERE target_key = ? AND cluster_key = ?",
                               (TARGET, CK))["ra_entity_id"] == ra_id
    assert summary(box)["reason"] == "sent"

    # 다음 라벨은 사상된 id 로 같은 객체를 고친다(새 객체 없음) — 시험 객체를 근거로 한 반증은 refuted_by 다.
    test_run = box.fake.seed("test_run", "낙하 시험 7")
    label(box, f"inc:{test_run}", outcome="refuted")
    assert tick(box)["sent"] == 1
    assert len([o for o in box.fake.objects.values() if o["type_slug"] == "risk_finding"]) == 1
    assert box.fake.objects[ra_id]["properties"]["status"] == "dismissed"
    assert box.fake.objects[ra_id]["properties"]["owner"] == OWNER                     # 가려 읽은 owner 를 되쓰지 않았다
    assert (ra_id, test_run, "refuted_by") in box.fake.links


def test_merge_on_an_existing_object_restores_the_masked_owner_and_keeps_other_properties(box):
    """update_object 는 통째 교체라 get_object 로 읽어 병합한다 — 게이트웨이가 가린 owner 는 앱 DB 값으로 되돌리고 남이 단 칸은 둔다."""
    ra_id = box.fake.seed("risk_finding", "옛 값", CODE, {"owner": OWNER, "note": "운영자가 단 메모", "status": "open"})
    box.store.execute("INSERT INTO rr_id_map(portal_kind, portal_id, owner_sub, ra_entity_id, ra_type_slug)"
                      " VALUES ('registry', ?, ?, ?, 'risk_finding')", (CODE, OWNER, ra_id))
    # 라벨이 등록부를 dismissed 로 옮긴 뒤의 op 다 — 보내는 쪽은 op 에 적힌 값이 아니라 보낼 때의 등록부 status 를 싣는다.
    box.store.execute("UPDATE rr_registry SET status = 'dismissed' WHERE target_key = ? AND cluster_key = ?", (TARGET, CK))
    ra_client.queue_sync_ops(box.store, TARGET, "ra", [{"op": "merge_object", "reason": "label_status",
                                                         "type": "risk_finding", "finding_id": FINDING,
                                                         "props": {"status": "dismissed"}}])
    assert tick(box)["sent"] == 1
    assert [name.removeprefix(ra_client.GATEWAY_ALIAS_PREFIX) for name in box.fake.tools()] == ["get_object", "update_object"]
    sent = box.fake.calls[1][1]
    assert sent["object_id"] == ra_id and ra_client.MASK_MARK not in json.dumps(sent, ensure_ascii=False)
    assert box.fake.objects[ra_id]["properties"] == {"owner": OWNER, "note": "운영자가 단 메모", "status": "dismissed",
                                                     "cluster_key": CK, "portal_registry_key": CODE, "visibility": "org"}


def test_a_masked_property_the_app_does_not_own_stops_the_write(box):
    """앱이 값을 모르는 칸이 가려져 오면 되쓰지 않는다 — 그 op 는 보내지 않고 까닭과 함께 따로 둔다(그 객체에만 걸린 거절이라 대상의 나머지
    op 는 나간다, 재시도하지 않는다 — 고친 뒤 재동기)."""
    ra_id = box.fake.seed("risk_finding", "옛 값", CODE, {"memo": "연락 someone@example.com"})
    box.store.execute("INSERT INTO rr_id_map(portal_kind, portal_id, owner_sub, ra_entity_id, ra_type_slug)"
                      " VALUES ('registry', ?, ?, ?, 'risk_finding')", (CODE, OWNER, ra_id))
    label(box, "검토 회의에서 확인")
    assert tick(box) == {"due": 1, "sent": 1, "failed": 0}
    assert "reportarchive_update_object" not in box.fake.tools()
    assert box.fake.objects[ra_id]["properties"] == {"memo": "연락 someone@example.com"}
    entry = ra_entry(box)
    assert entry["state"] == "done" and entry["pending_ops"] == [] and entry["skipped_n"] == 1
    assert [(d["op"]["op"], d["error"].split(":")[0]) for d in entry["dead_ops"]] == [("merge_object", "masked_readback")]
    assert summary(box)["dead_ops"] == 1 and "masked_readback" in summary(box)["message"]


def test_a_label_whose_evidence_is_not_an_ra_incident_is_not_linked_but_counted(box):
    """verified_by 의 dst 는 RA 사고 · 시험 객체다 — 근거가 글이거나 다른 축의 객체면 잇지 않고(만들지도 않는다) 건수와 까닭을 남긴다."""
    label(box, "검토 회의에서 확인")
    assert tick(box)["sent"] == 1
    assert "reportarchive_link_objects" not in box.fake.tools() and box.fake.links == {}
    entry = ra_entry(box)
    assert entry["state"] == "done" and entry["skipped_n"] == 1 and entry["last_skip"] == "evidence_not_ra_object"
    assert "RA 에 잇지 않은 것 1건" in summary(box)["message"]

    report = box.fake.seed("report", "보고서 9")
    label(box, f"inc:{report}", outcome="refuted")
    assert tick(box)["sent"] == 1
    assert ra_entry(box)["skipped_n"] == 2 and ra_entry(box)["last_skip"] == "evidence_not_incident_or_test_run"
    assert box.fake.links == {}
    assert [o["type_slug"] for o in box.fake.objects.values()].count("incident") == 0


def test_the_finding_maps_to_its_registry_row_through_the_alias_and_the_improvement_suffix(box):
    """RA risk_finding 은 등록부 행이다 — 행을 고르는 규칙은 registry.merge 와 같다(사람이 확정한 별칭을 거친 대표 키, improvement 는 .imp 행)."""
    box.store.execute("UPDATE rr_findings SET direction = 'improvement', cluster_key = 'old000000000' WHERE finding_id = ?",
                      (FINDING,))
    box.store.execute("INSERT INTO rr_cluster_alias(old_cluster_key, new_cluster_key, owner_sub, reason, decided_by, decided_at)"
                      " VALUES ('old000000000', ?, ?, 'cluster_merge', ?, 1)", (CK, OWNER, OWNER))
    box.store.execute("UPDATE rr_registry SET cluster_key = ? WHERE target_key = ?", (CK + ".imp", TARGET))
    ra_client.queue_sync_ops(box.store, TARGET, "ra", [{"op": "merge_object", "reason": "label_status", "type": "risk_finding",
                                                         "finding_id": FINDING, "props": {"status": "verified"}}])
    assert tick(box)["sent"] == 1
    assert box.fake.calls[0][1]["code"] == f"{TARGET}#{CK}.imp"
    assert id_map(box)[("registry", f"{TARGET}#{CK}.imp")][1] == "risk_finding"


# ---------------------------------------------------------------- 번역 — X태그 승격(design_trait · exhibits)
def test_x_tag_promotion_creates_the_trait_and_the_project_and_links_exhibits(box):
    box.store.execute(
        "INSERT INTO rr_character(id, project_id, owner_sub, facet, tag, tags_json, statement, polarity, cites_json, by_json,"
        " first_target_key, support_panels, support_targets, status, created_at, updated_at)"
        " VALUES ('pn#C1', ?, ?, 'anomaly', 'x:stack_budget', '[\"x:stack_budget\"]', 'A', 'observation', '[]', '[]', ?,"
        " 2, 1, 'panel', 1, 1)", (PROJECT, OWNER, TARGET))
    character.promote_x_tag(box.store, tag="x:stack_budget", axis="char:tolerance", owner_sub=OWNER)
    tag = "char:tolerance:stack_budget"
    assert [op["op"] for op in ra_entry(box)["pending_ops"]] == ["merge_object", "link"]

    assert tick(box)["sent"] == 1
    trait = next(oid for oid, obj in box.fake.objects.items() if obj["type_slug"] == "design_trait")
    project = next(oid for oid, obj in box.fake.objects.items() if obj["type_slug"] == "project")
    assert box.fake.objects[trait] | {"properties": None} == {"type_slug": "design_trait", "value": tag, "code": tag,
                                                              "description": "", "properties": None}
    assert box.fake.objects[trait]["properties"] == {"axis": "tolerance", "token": "stack_budget", "status": "vocab"}
    assert box.fake.objects[project]["code"] == PROJECT and box.fake.objects[project]["value"] == f"P-RK01@{PROJECT}"
    assert box.fake.links == {(project, trait, "exhibits"): {"support": 2}}
    assert id_map(box) == {("trait", tag): (trait, "design_trait", OWNER), ("project", PROJECT): (project, "project", OWNER)}
    # 원본 표의 ra_entity_id 도 함께 적어 야간 ⑧ 정합 검사가 어긋남을 세지 않는다.
    assert box.store.query_one("SELECT ra_entity_id FROM rr_projects WHERE id = ?", (PROJECT,))["ra_entity_id"] == project
    assert nightly.check_id_map(box.store, now=NOW)["drift"] == []


# ---------------------------------------------------------------- 보류 · 꺼짐
def test_a_private_project_is_withheld_without_a_call_and_released_when_opened(box):
    """비공개 과제의 op 는 보내지 않는다 — 큐에 그대로 두고 withheld 로 둔다(plan §5.5.3). 조직 공개로 풀면 쌓인 op 가 나간다."""
    from app import routes

    box.store.execute("UPDATE rr_projects SET mcp_visibility = 'private' WHERE id = ?", (PROJECT,))
    label(box, "검토 회의에서 확인")
    assert tick(box) == {"due": 1, "sent": 0, "failed": 0, "held": 1}
    assert box.fake.methods == []                                       # 세션조차 열지 않는다
    entry = ra_entry(box)
    assert entry["state"] == "withheld" and len(entry["pending_ops"]) == 2
    label(box, "다시 확인", outcome="refuted")                          # 새 op 가 쌓여도 보류는 그대로다
    assert ra_entry(box)["state"] == "withheld" and len(ra_entry(box)["pending_ops"]) == 4
    assert summary(box)["reason"] == "withheld" and "대기 4건" in summary(box)["message"]
    assert tick(box) == {"due": 0, "sent": 0, "failed": 0}

    box.store.execute("UPDATE rr_projects SET mcp_visibility = 'org' WHERE id = ?", (PROJECT,))
    routes._release_withheld(box.store, PROJECT, NOW)
    assert tick(box)["sent"] == 1 and ra_entry(box)["state"] == "done"
    assert box.fake.objects and all(bearer == RW for _n, _a, bearer in box.fake.calls)


def test_without_the_box_write_pat_nothing_is_called_and_the_summary_says_so(box):
    """쓰기 PAT 가 없으면 보내는 쪽이 꺼져 있다 — 읽기 PAT 가 있어도 쓰지 않는다. 대기는 그대로이고 요약이 그 까닭을 말한다(조용한
    pending 이 아니다). 키를 넣으면 재기동 없이 다음 틱부터 나간다."""
    write_secrets(box.data_dir, HWAXRISK_PORTAL_PAT=READ, HWAXRISK_HEAX_SERVICE_PAT="svc")
    label(box, "검토 회의에서 확인")
    reason = f"credential_missing:{ra_client.WRITE_SECRET_KEY}"
    assert box.sender.off_reason() == reason
    assert tick(box) == {"due": 1, "sent": 0, "skipped": reason}
    assert box.fake.methods == []
    entry = ra_entry(box)
    assert (entry["state"], entry["attempts"], entry["last_error"], len(entry["pending_ops"])) == ("pending", 0, None, 2)
    got = summary(box)
    assert got["reason"] == reason and got["pending_ops"] == 2
    assert ra_client.WRITE_SECRET_KEY in got["message"] and "보낸 것 없음" in got["message"]

    write_secrets(box.data_dir, HWAXRISK_PORTAL_PAT=READ, HWAXRISK_PORTAL_PAT_RW=RW)
    assert box.sender.off_reason() is None
    assert tick(box)["sent"] == 1 and ra_entry(box)["state"] == "done"


# ---------------------------------------------------------------- 실패 — 큐에 남기고 까닭을 적는다
def test_an_ra_admin_refusal_keeps_the_ops_queued_and_does_not_retry_until_resync(box):
    """RA 온톨로지 쓰기는 시스템 관리자 전용이다 — PAT 주인이 관리자가 아니면 곧바로 멈추고(forbidden) 재동기 전에는 다시 부르지 않는다."""
    box.fake.admins = set()                                             # PAT 는 유효하지만 그 계정이 RA 관리자가 아니다
    label(box, "검토 회의에서 확인")
    assert tick(box) == {"due": 1, "sent": 0, "failed": 1}
    entry = ra_entry(box)
    assert entry["state"] == "unavailable" and entry["last_error"].startswith("forbidden: create_object — 시스템 관리자")
    assert len(entry["pending_ops"]) == 2 and entry["attempts"] == 0
    got = summary(box)
    assert got["reason"] == "forbidden" and "재동기" in got["message"] and "시스템 관리자" in got["message"]
    calls = len(box.fake.calls)
    assert tick(box) == {"due": 0, "sent": 0, "failed": 0} and len(box.fake.calls) == calls

    box.fake.admins = {RW}                                              # 운영자가 그 계정을 RA 관리자로 올렸다
    ra_client.resync(box.store, TARGET)
    assert tick(box)["sent"] == 1 and ra_entry(box)["state"] == "done"


def test_transient_failures_back_off_and_defer_the_rest_of_the_tick(box):
    """게이트웨이 5xx · 연결 실패만 백오프로 다시 보낸다 — 그 틱의 남은 대상은 미뤄 죽은 상대를 대상마다 두드리지 않는다."""
    label(box, "검토 회의에서 확인")
    ra_client.queue_sync_ops(box.store, TARGET_B, "ra", [{"op": "merge_object", "type": "design_trait",
                                                           "tag": "char:tolerance:tight", "props": {"status": "vocab"}}])
    box.fake.fail["reportarchive_create_object"] = [("http", 503)]
    assert tick(box) == {"due": 2, "sent": 0, "failed": 1, "deferred": 1}
    first = ra_entry(box)
    assert first["state"] == "pending" and first["attempts"] == 1 and first["next_at"] > NOW
    assert first["last_error"].startswith("transient: create_object — 게이트웨이 HTTP 503")
    assert len(first["pending_ops"]) == 2
    assert ra_entry(box, TARGET_B)["attempts"] == 0 and box.fake.tools() == ["reportarchive_create_object"]
    assert summary(box)["reason"] == "transient"

    assert tick(box) == {"due": 1, "sent": 1, "failed": 0}               # 미룬 대상은 다음 틱에 나간다
    assert ra_entry(box, TARGET_B)["state"] == "done"


def test_partial_progress_sets_aside_only_the_op_ra_refused(box):
    """앞의 op 가 나간 뒤 RA 가 그 연결만 거절하면(rejected — 관계 축 제약) 나간 것은 큐에서 빼고 거절된 op 는 까닭과 함께 따로 둔다
    (다시 보내지 않는다 — 고친 뒤 재동기)."""
    incident = box.fake.seed("incident", "사고 2026-0042")
    label(box, f"inc:{incident}")
    box.fake.fail["reportarchive_link_objects"] = [("ra_error", "관계 축 제약 위반: verified_by")]
    assert tick(box) == {"due": 1, "sent": 1, "failed": 0}
    entry = ra_entry(box)
    assert entry["state"] == "done" and entry["pending_ops"] == []
    assert [(d["op"]["op"], d["error"]) for d in entry["dead_ops"]] == [
        ("link", "rejected: link_objects — 관계 축 제약 위반: verified_by")]
    assert summary(box)["reason"] == "sent" and summary(box)["dead_ops"] == 1


@pytest.mark.parametrize(("fail", "head"), [
    (("http", 404), "rejected: link_objects — 게이트웨이 HTTP 404"),
    (("rpc_error", "Invalid params: object_id"), "rejected: link_objects — rpc_error"),
], ids=["http_404", "rpc_error"])
def test_partial_progress_keeps_the_failed_op_and_what_follows_when_the_channel_stops(box, fail, head):
    """채널 전체가 막히는 실패(게이트웨이가 그 밖의 4xx 로 답한다 — 끝점, JSON-RPC 오류 — 인자 꼴 · 판이 다른 RA)는 op 를 따로 두지 않고
    멈춘다 — 나간 것만 빼고 실패한 op 와 그 뒤는 큐에 남는다(rejected — 다시 보내지 않는다)."""
    incident = box.fake.seed("incident", "사고 2026-0042")
    label(box, f"inc:{incident}")
    box.fake.fail["reportarchive_link_objects"] = [fail]
    assert tick(box) == {"due": 1, "sent": 0, "failed": 1}
    entry = ra_entry(box)
    assert [op["op"] for op in entry["pending_ops"]] == ["link"] and not entry.get("dead_ops")
    assert entry["state"] == "unavailable" and entry["last_error"].startswith(head)
    assert summary(box)["reason"] == "rejected"


def test_gateway_refusals_name_what_to_fix(box):
    """읽기 전용 PAT · RA 백엔드 없음 · RA 온톨로지 없음은 사람이 고칠 것이라 곧바로 멈추고 그 낱말을 남긴다."""
    cases = (
        ("tool_error", "read_only: 'reportarchive_create_object' — 읽기 전용 토큰(scopes 에 read 만)은 조회 도구만 부른다.",
         "read_only"),
        ("tool_error", "unknown tool: reportarchive_create_object", "tool_missing"),
        ("ra_error", "알 수 없는 타입(type_slug): 'risk_finding'", "ontology_missing"),
        ("tool_error", "backend reportarchive unavailable: ConnectError", "transient"),
    )
    label(box, "검토 회의에서 확인")
    for kind, text, code in cases:
        ra_client.resync(box.store, TARGET)
        box.fake.fail["reportarchive_create_object"] = [(kind, text)]
        tick(box)
        entry = ra_entry(box)
        assert entry["last_error"].startswith(f"{code}: "), (code, entry["last_error"])
        assert entry["state"] == ("pending" if code == "transient" else "unavailable"), code
        assert summary(box)["reason"] == code
    assert box.fake.objects == {}


def test_a_value_collision_never_writes_someone_elses_object(box):
    """code 가 맞는 객체가 없으면 RA 는 값이 겹친 객체를 돌려준다(resolve_existing) — code 가 다르면 그 객체를 고치지 않고 그 op 를 따로 둔다."""
    other = box.fake.seed("risk_finding", f"P-RK01@thermal.cte_mismatch@{CODE}", "남의 code", {"status": "open"})
    label(box, "검토 회의에서 확인")
    assert tick(box) == {"due": 1, "sent": 1, "failed": 0}
    assert box.fake.tools() == ["reportarchive_create_object"]
    assert box.fake.objects[other]["properties"] == {"status": "open"}
    entry = ra_entry(box)
    assert entry["last_error"] is None and entry["dead_ops"][0]["error"].startswith("value_collision: ") and id_map(box) == {}


def test_a_stale_id_map_entry_is_resolved_again_by_code(box):
    """rr_id_map 의 id 가 RA 에서 사라졌으면(not found) code 로 다시 찾거나 만든다 — 사상을 새 id 로 고친다."""
    box.store.execute("INSERT INTO rr_id_map(portal_kind, portal_id, owner_sub, ra_entity_id, ra_type_slug)"
                      " VALUES ('registry', ?, ?, 999, 'risk_finding')", (CODE, OWNER))
    label(box, "검토 회의에서 확인")
    assert tick(box)["sent"] == 1
    assert [name.removeprefix("reportarchive_") for name in box.fake.tools()] == ["get_object", "create_object"]
    ra_id = next(oid for oid, obj in box.fake.objects.items() if obj["code"] == CODE)
    assert id_map(box)[("registry", CODE)][0] == ra_id != 999


def test_the_adh_channel_is_left_to_its_own_sender(box):
    """이 전송기는 RA 채널만 보낸다 — AIDataHub 대기는 세기만 하고(unwired) 상태를 바꾸지 않으며 요약은 sender_unwired 그대로다."""
    ra_client.queue_sync_ops(box.store, TARGET, "adh", [{"op": "retag", "record_id": "rec-1", "status": "verified"}])
    assert tick(box) == {"due": 1, "sent": 0, "failed": 0, "unwired": 1}
    adh = ra_client.load_external_sync(box.store, TARGET)["adh"]
    assert (adh["state"], adh["attempts"], len(adh["pending_ops"])) == ("pending", 0, 1)
    assert ra_client.sync_summary(ra_client.load_external_sync(box.store, TARGET),
                                  status=ra_client.sender_status(box.settings))["adh"]["reason"] == "sender_unwired"
    assert box.fake.methods == []


# ---------------------------------------------------------------- 반대 검토 고침(RK-01 — 상태 되돌림 · 따로 둠 · 호출마다 가시성 · 로그 · 틱 크기 · 폐기 글)
def _registry_status(box) -> str:
    return box.store.query_one("SELECT status FROM rr_registry WHERE target_key = ? AND cluster_key = ?", (TARGET, CK))["status"]


def _ra_finding(box) -> dict | None:
    return next(({"id": oid, **obj} for oid, obj in box.fake.objects.items()
                 if obj["type_slug"] == "risk_finding" and obj["code"] == CODE), None)


def _promote_stack_budget(box) -> None:
    """X태그 승격 — 큐에 [design_trait 병합, exhibits 연결] 이 쌓인다."""
    box.store.execute(
        "INSERT INTO rr_character(id, project_id, owner_sub, facet, tag, tags_json, statement, polarity, cites_json, by_json,"
        " first_target_key, support_panels, support_targets, status, created_at, updated_at)"
        " VALUES ('pn#C1', ?, ?, 'anomaly', 'x:stack_budget', '[\"x:stack_budget\"]', 'A', 'observation', '[]', '[]', ?,"
        " 2, 1, 'panel', 1, 1)", (PROJECT, OWNER, TARGET))
    character.promote_x_tag(box.store, tag="x:stack_budget", axis="char:tolerance", owner_sub=OWNER)


def _trait_target(box, i: int) -> str:
    """design_trait 병합 op 하나가 쌓인 대상 — 틱 크기 시험용."""
    key = f"diff:{i:032x}"
    box.store.execute(
        "INSERT INTO rr_targets(target_key, owner_sub, kind, ref_id, project_id, ir_hash, level, external_sync_json,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (key, OWNER, "diff", key[5:], PROJECT, "h" * 12, "C0", json.dumps(ra_client.empty_sync()), 300, 300))
    ra_client.queue_sync_ops(box.store, key, "ra", [{"op": "merge_object", "type": "design_trait",
                                                     "tag": f"char:tolerance:t{i}", "props": {"status": "vocab"}}])
    return key


def test_a_status_that_turns_back_while_held_reaches_ra_as_the_app_has_it(box):
    """보류 중 확정 → 반증 → 다시 확정이면 RA 의 status 도 확정이다. 큐는 같은 꼴의 셋째 병합을 버리지만(내용이 같은 op 는 한 번만 쌓인다)
    보내는 쪽은 보낼 때의 등록부 status 를 싣는다(원칙 3 — 투영은 정본을 따라간다). 종전에는 RA 가 dismissed 로 끝나고 요약은 sent 였다."""
    from app import routes

    box.store.execute("UPDATE rr_projects SET mcp_visibility = 'private' WHERE id = ?", (PROJECT,))
    label(box, "근거 1", outcome="confirmed")
    label(box, "근거 2", outcome="refuted")
    label(box, "근거 3", outcome="confirmed")
    assert tick(box)["held"] == 1
    box.store.execute("UPDATE rr_projects SET mcp_visibility = 'org' WHERE id = ?", (PROJECT,))
    routes._release_withheld(box.store, PROJECT, NOW)
    assert tick(box)["sent"] == 1
    assert _registry_status(box) == "verified" == _ra_finding(box)["properties"]["status"]
    assert summary(box)["reason"] == "sent"


def test_a_status_flip_during_the_send_is_not_lost(box):
    """보내는 틱 도중에 상태가 뒤집혀도(반증 뒤 다시 확정) 다음 틱이 그때의 등록부 status 로 맞춘다 — 보낸 op 를 내용으로 지우는
    complete 가 같은 꼴의 새 op 를 함께 지워도, 남는 op 가 보낼 때의 정본을 싣는다."""
    label(box, "근거 1", outcome="confirmed")
    real = box.fake._create_object
    flipped: list[bool] = []

    def create_then_flip(args):
        out = real(args)
        if not flipped:
            flipped.append(True)
            label(box, "근거 2", outcome="refuted")
            label(box, "근거 3", outcome="confirmed")
        return out

    box.fake._create_object = create_then_flip
    assert tick(box)["sent"] == 1
    assert ra_entry(box)["pending_ops"]                                     # 도중에 쌓인 op 가 남았다
    assert tick(box)["sent"] == 1 and ra_entry(box)["state"] == "done"
    assert _registry_status(box) == "verified" == _ra_finding(box)["properties"]["status"]


def test_an_op_ra_refuses_is_set_aside_and_the_rest_of_the_target_still_goes_out(box):
    """RA 가 op 하나만 받지 않으면(값이 겹친 남의 객체 · 관계 축 제약 · enum · 길이) 그 op 만 dead_ops 에 까닭과 함께 두고 대상의 나머지
    op 는 계속 보낸다. 종전에는 맨 앞 op 에서 멈춰 뒤의 상관없는 라벨 병합까지 영영 나가지 않았고 재동기해도 같은 op 에서 다시 멈췄다.
    재동기는 따로 둔 op 를 큐 앞으로 되돌린다."""
    other = box.fake.seed("design_trait", "char:tolerance:stack_budget", None, {"axis": "tolerance"})   # 값은 같고 code 가 없는 객체
    _promote_stack_budget(box)
    label(box, "검토 회의에서 확인")                                     # 뒤에 쌓인, 상관없는 라벨 op 둘
    assert tick(box) == {"due": 1, "sent": 1, "failed": 0}
    assert _ra_finding(box)["properties"]["status"] == "verified"      # 라벨 병합은 나갔다
    assert box.fake.objects[other]["properties"] == {"axis": "tolerance"}  # 남의 객체는 고치지 않았다
    entry = ra_entry(box)
    assert entry["state"] == "done" and entry["pending_ops"] == [] and entry["last_error"] is None
    assert [(d["op"]["op"], d["op"].get("type") or d["op"].get("relation"), d["error"].split(":")[0])
            for d in entry["dead_ops"]] == [("merge_object", "design_trait", "value_collision"),
                                            ("link", "exhibits", "value_collision")]
    got = summary(box)
    assert got["reason"] == "sent" and got["dead_ops"] == 2
    assert "따로 둔 op 2건" in got["message"] and "value_collision" in got["message"] and "재동기" in got["message"]
    calls = len(box.fake.calls)
    assert tick(box)["due"] == 0 and len(box.fake.calls) == calls      # 따로 둔 op 는 저절로 다시 부르지 않는다

    del box.fake.objects[other]                                          # 운영자가 RA 에서 겹친 값을 정리했다
    ra_client.resync(box.store, TARGET)
    entry = ra_entry(box)
    assert [op["op"] for op in entry["pending_ops"]] == ["merge_object", "link"] and not entry.get("dead_ops")
    assert tick(box)["sent"] == 1 and ra_entry(box)["state"] == "done"
    trait = next(oid for oid, obj in box.fake.objects.items() if obj["code"] == "char:tolerance:stack_budget")
    project = next(oid for oid, obj in box.fake.objects.items() if obj["type_slug"] == "project")
    assert (project, trait, "exhibits") in box.fake.links and summary(box)["dead_ops"] == 0


def test_a_target_whose_only_op_is_refused_settles_with_it_set_aside(box):
    """대상의 op 가 모두 따로 두어지면 큐가 비어 done 이다(대기 0건 · 따로 둔 1건) — pending 인 채 빈 큐로 남지 않는다."""
    box.fake.seed("design_trait", "char:tolerance:tight", None, {})
    ra_client.queue_sync_ops(box.store, TARGET_B, "ra", [{"op": "merge_object", "type": "design_trait",
                                                           "tag": "char:tolerance:tight", "props": {"status": "vocab"}}])
    assert tick(box) == {"due": 1, "sent": 1, "failed": 0}
    entry = ra_entry(box, TARGET_B)
    assert (entry["state"], entry["pending_ops"], len(entry["dead_ops"])) == ("done", [], 1)
    assert summary(box, TARGET_B)["dead_ops"] == 1


def test_a_project_made_private_mid_send_stops_the_next_call_and_holds_the_rest(box):
    """보내는 도중 소유자가 과제를 비공개로 돌리면 다음 호출부터 하지 않는다 — 가시성을 호출마다 다시 본다. 종전에는 틱 머리에서 한 번만
    봐 그 대상의 남은 조회 · 연결이 계속 나갔다. 남은 op 는 보류(withheld)로 큐에 그대로이고 다시 조직 공개로 풀면 나간다."""
    from app import routes

    incident = box.fake.seed("incident", "사고 1")
    label(box, f"inc:{incident}")
    real = box.fake._create_object

    def create_then_hide(args):
        out = real(args)
        box.store.execute("UPDATE rr_projects SET mcp_visibility = 'private' WHERE id = ?", (PROJECT,))
        return out

    box.fake._create_object = create_then_hide
    assert tick(box) == {"due": 1, "sent": 0, "failed": 0, "held": 1}
    assert box.fake.tools() == ["reportarchive_create_object"]
    entry = ra_entry(box)
    assert entry["state"] == "withheld" and [op["op"] for op in entry["pending_ops"]] == ["link"]

    box.fake._create_object = real
    box.store.execute("UPDATE rr_projects SET mcp_visibility = 'org' WHERE id = ?", (PROJECT,))
    routes._release_withheld(box.store, PROJECT, NOW)
    assert tick(box)["sent"] == 1
    assert (_ra_finding(box)["id"], incident, "verified_by") in box.fake.links


def test_a_project_made_private_inside_an_op_stops_before_its_next_write(box):
    """op 하나 안에서도 호출마다 본다 — exhibits 연결이 과제 객체를 만든 직후 비공개가 되면 성격 태그 조회 · 연결을 하지 않는다."""
    _promote_stack_budget(box)
    real = box.fake._create_object

    def create_then_hide(args):
        out = real(args)
        if args.get("type_slug") == "project":
            box.store.execute("UPDATE rr_projects SET mcp_visibility = 'private' WHERE id = ?", (PROJECT,))
        return out

    box.fake._create_object = create_then_hide
    assert tick(box)["held"] == 1
    assert [name.removeprefix("reportarchive_") for name in box.fake.tools()] == ["create_object", "create_object"]
    assert box.fake.links == {} and [op["op"] for op in ra_entry(box)["pending_ops"]] == ["link"]


def test_a_project_reopened_right_after_the_gate_closed_is_not_left_withheld(box, monkeypatch):
    """문이 닫힌 직후 다시 조직 공개로 돌아왔으면 보류로 두지 않는다 — 보류는 공개 토글만 풀어 그대로 두면 영영 멈춘다. 남은 op 는 큐에
    그대로(pending)이고 다음 틱에 나간다."""
    incident = box.fake.seed("incident", "사고 1")
    label(box, f"inc:{incident}")
    real = ra_client._projects
    reads: list[int] = []

    def projects_closing_once(store, ids):
        rows = real(store, ids)
        reads.append(1)
        if len(reads) == 3:                                             # 틱 머리 · 첫 호출 다음, 둘째 op 의 첫 호출 앞에서 한 번만 닫힌다
            return {pid: {**dict(row), "mcp_visibility": "private"} for pid, row in rows.items()}
        return rows

    monkeypatch.setattr(ra_client, "_projects", projects_closing_once)
    assert tick(box) == {"due": 1, "sent": 1, "failed": 0}
    entry = ra_entry(box)
    assert entry["state"] == "pending" and [op["op"] for op in entry["pending_ops"]] == ["link"]
    monkeypatch.setattr(ra_client, "_projects", real)
    assert tick(box)["sent"] == 1 and ra_entry(box)["state"] == "done"
    assert (_ra_finding(box)["id"], incident, "verified_by") in box.fake.links


def test_a_purge_mid_send_stops_the_next_call(box):
    """보내는 도중 과제가 폐기되면 다음 호출부터 하지 않고 대상은 멈춘다(폐기된 과제는 RA 에 올리지 않는다)."""
    incident = box.fake.seed("incident", "사고 1")
    label(box, f"inc:{incident}")
    real = box.fake._create_object

    def create_then_purge(args):
        out = real(args)
        box.store.execute("UPDATE rr_projects SET status = 'purged' WHERE id = ?", (PROJECT,))
        return out

    box.fake._create_object = create_then_purge
    assert tick(box) == {"due": 1, "sent": 0, "failed": 1}
    assert box.fake.tools() == ["reportarchive_create_object"]
    entry = ra_entry(box)
    assert entry["state"] == "unavailable" and "폐기" in entry["last_error"]


def test_a_stop_says_so_in_the_log_once_per_tick(box, caplog):
    """채널 전체가 막히는 실패(관리자 아님 · 읽기 전용 · 토큰 거절 · 도구 없음 · 온톨로지 없음)는 대상 화면을 하나씩 열지 않아도 알 수 있게
    경고 한 줄을 남긴다 — 틱마다 한 번, 사유 낱말과 대상 수. 종전에는 기동 로그의 '켜짐' 한 줄뿐이었다. 따로 둔 op 도 한 줄이다."""
    import logging

    box.fake.admins = set()                                             # PAT 는 유효하지만 그 계정이 RA 관리자가 아니다
    label(box, "검토 회의에서 확인")
    ra_client.queue_sync_ops(box.store, TARGET_B, "ra", [{"op": "merge_object", "type": "design_trait",
                                                           "tag": "char:tolerance:tight", "props": {"status": "vocab"}}])
    caplog.set_level(logging.INFO, logger="hwax_risk")
    assert tick(box) == {"due": 2, "sent": 0, "failed": 2}
    warned = [r.getMessage() for r in caplog.records if r.name.startswith("hwax_risk") and r.levelno >= logging.WARNING]
    assert len(warned) == 1, warned
    assert "forbidden" in warned[0] and "대상 2개" in warned[0] and "재동기" in warned[0] and "시스템 관리자" in warned[0]
    caplog.clear()
    assert tick(box)["due"] == 0
    assert not [r for r in caplog.records if r.name.startswith("hwax_risk") and r.levelno >= logging.WARNING]

    box.fake.admins = {RW}
    box.fake.seed("design_trait", "char:tolerance:tight", None, {})
    for key in (TARGET, TARGET_B):
        ra_client.resync(box.store, key)
    caplog.clear()
    tick(box)
    warned = [r.getMessage() for r in caplog.records if r.name.startswith("hwax_risk") and r.levelno >= logging.WARNING]
    assert len(warned) == 1 and "따로 뒀다" in warned[0] and "value_collision" in warned[0], warned


def test_one_tick_sends_at_most_the_cap_and_leaves_the_rest_for_the_next(box):
    """한 틱이 보내는 대상 수에 상한이 있다 — 처음 키를 넣은 박스 · 오래 보류됐다 풀린 과제의 대상 수백 개를 한 틱에 비우는 동안 같은
    sync_loop 의 PAT 폐기 대조가 멈추지 않게. 남은 대상은 상태 그대로 다음 틱에 나간다."""
    assert (box.sender.tick_max_targets, box.sender.tick_budget_s) == (ra_client.SEND_TICK_MAX_TARGETS,
                                                                        ra_client.SEND_TICK_BUDGET_S)
    for i in range(12):
        _trait_target(box, i)
    box.sender.tick_max_targets = 5
    assert tick(box) == {"due": 12, "sent": 5, "failed": 0, "deferred": 7}
    assert tick(box) == {"due": 7, "sent": 5, "failed": 0, "deferred": 2}
    assert tick(box) == {"due": 2, "sent": 2, "failed": 0}


def test_the_tick_budget_and_the_stop_signal_end_the_tick_between_targets(box):
    """벽시계 예산이 다하거나 러너가 멈추면 대상 사이에서 틱을 끝낸다 — 첫 대상은 늘 보낸다(예산이 0 이어도 나아간다). 러너는 자기 정지
    신호를 넘긴다(종전에는 stop() 이 러너 잠금을 놓은 뒤에도 큐 비우기가 계속됐다)."""
    from app import config, runner

    for i in range(3):
        _trait_target(box, i)
    box.sender.tick_budget_s = 0.0
    assert tick(box) == {"due": 3, "sent": 1, "failed": 0, "deferred": 2}
    box.sender.tick_budget_s = ra_client.SEND_TICK_BUDGET_S
    calls = len(box.fake.calls)
    assert nightly.retry_external_sync(box.store, now=NOW, send=box.sender, should_stop=lambda: True) == {
        "due": 2, "sent": 0, "failed": 0, "deferred": 2}
    assert len(box.fake.calls) == calls

    risk_runner = runner.RiskRunner(box.store, config.settings, engine=None, external_sync_send=box.sender)
    risk_runner._stop.set()
    assert risk_runner._external_sync_tick() == {"due": 2, "sent": 0, "failed": 0, "deferred": 2}
    assert len(box.fake.calls) == calls
    risk_runner._stop.clear()
    assert risk_runner._external_sync_tick() == {"due": 2, "sent": 2, "failed": 0}
