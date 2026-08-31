# GET /api/export · POST /api/import — JSONL 헤더·표 순서·소유자 스코프·since, 왕복(빈 DB import 후 행 수·해시 동일), 409 schema_mismatch·owner_mismatch, 사람 확정 우선·conflicts[]
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app import config, export, identity
from app.errors import AppError
from app.risk_store import RiskStore, get_store

ALICE = "alice@example.com"
BOB = "bob@example.com"
BLOB = b"\x1f\x8b\x08\x00fake-gzip\x00\xff"

TOKEN = "heax_pat_test_fake_export"
EXPORT_USER = {"id": 9, "email": "exporter@example.com", "display_name": "Exp", "role": "member", "organization": "cae"}
AUTH = {"Authorization": f"Bearer {TOKEN}"}


# ---------------------------------------------------------------- 씨앗 데이터(열을 전부 명시한다 — 'select *' 금지 규약과 같은 이유)
def _insert(store: RiskStore, table: str, row: dict) -> None:
    cols = list(row)
    store.execute(
        f"INSERT INTO {table}({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
        tuple(row[c] for c in cols),
    )


def _seed(store: RiskStore, owner: str = ALICE, at: int = 1_000) -> None:
    """한 사용자의 대표 표 10종에 행을 심는다(BLOB·사람 확정 원장 포함)."""
    pid, sid = f"p-{owner[:3]}", f"s-{owner[:3]}"
    _insert(store, "rr_projects", {"id": pid, "owner_sub": owner, "code": f"PRJ-{owner[:3]}", "name": "케이스",
                                   "stage": "concept", "character_status": "seed", "created_at": at, "updated_at": at})
    _insert(store, "rr_sources", {"id": f"src-{owner[:3]}", "project_id": pid, "owner_sub": owner, "kind": "mcad",
                                  "app_key": "heax-step_forge", "ref_json": '{"project_id":1}',
                                  "ref_key": "mcad:heax-step_forge:1", "created_at": at})
    _insert(store, "rr_snapshots", {"id": sid, "project_id": pid, "owner_sub": owner, "ir_version": "1.0",
                                    "ir_hash": f"hash-{owner[:3]}", "ir_json": '{"nodes":[]}',
                                    "source_ids_json": "[]", "kinds_json": '["mcad"]', "node_count": 2,
                                    "edge_count": 1, "warnings_n": 0, "created_at": at})
    _insert(store, "rr_snapshot_calls", {"call_id": f"{sid}-001", "snapshot_id": sid, "owner_sub": owner, "seq": 1,
                                         "source_kind": "mcad", "channel": "rest", "tool": "/tree", "ok": 1,
                                         "response_gz": BLOB, "response_bytes": len(BLOB), "started_at": at})
    for nid in ("n1", "n2"):
        _insert(store, "rr_ir_nodes", {"snapshot_id": sid, "nid": nid, "owner_sub": owner, "kind": "part",
                                       "source_kind": "mcad", "name": nid.upper(), "name_norm": nid})
    _insert(store, "rr_ir_edges", {"snapshot_id": sid, "eid": "e1", "owner_sub": owner, "kind": "interference",
                                   "kind_family": "contact", "a": "n1", "b": "n2", "status": "auto"})
    _insert(store, "rr_part_keys", {"ckey": f"ck-{owner[:3]}", "owner_sub": owner, "status": "candidate",
                                    "name_norm_canon": "cover", "geom_bucket": "b1", "material_norm": "pc",
                                    "created_at": at, "updated_at": at})
    _insert(store, "rr_iface_ledger", {"project_id": pid, "pair_key": "n1|n2", "owner_sub": owner,
                                       "status": "confirmed", "decided_by": owner, "decided_at": at})
    _insert(store, "rr_states", {"snapshot_id": sid, "owner_sub": owner, "state_json": "{}", "feature_json": "{}",
                                 "gates_json": "{}", "computed_at": at})
    _insert(store, "rr_targets", {"target_key": f"t-{owner[:3]}", "owner_sub": owner, "kind": "snap", "ref_id": sid,
                                  "project_id": pid, "ir_hash": f"hash-{owner[:3]}", "level": "C0",
                                  "external_sync_json": "{}", "created_at": at, "updated_at": at})


@pytest.fixture
def seeded(risk_store):
    _seed(risk_store, ALICE, at=1_000)
    _seed(risk_store, BOB, at=9_000)
    # owner_sub 열이 없는 공용 표 — 소유자와 무관하게 실린다.
    _insert(risk_store, "rr_dim_vocab", {"name": "cover_thk", "kind": "thickness", "unit": "mm", "created_at": 1_000})
    return risk_store


def _lines(store: RiskStore, owner: str = ALICE, since: int = 0) -> list[dict]:
    return [json.loads(ln) for ln in export.iter_lines(store, owner, since)]


# ---------------------------------------------------------------- export
def test_header_is_first_line(seeded):
    head = _lines(seeded)[0]
    assert set(head) == {"schema_version", "app_version", "origin"}
    assert head["schema_version"] == seeded.schema_version() == 1
    assert head["app_version"] == config.APP_VERSION
    assert isinstance(head["origin"], dict) and "hostname" in head["origin"]


def test_rows_follow_plan_table_order_and_skip_housekeeping(seeded):
    tables = [ln["table"] for ln in _lines(seeded)[1:]]
    assert tables, "행이 하나도 실리지 않았다"
    assert set(tables) <= set(export.TABLE_ORDER)
    assert not any(t.startswith("_") for t in tables)
    order = {t: i for i, t in enumerate(export.TABLE_ORDER)}
    assert [order[t] for t in tables] == sorted(order[t] for t in tables)
    assert export.TABLE_ORDER[:4] == ("rr_projects", "rr_sources", "rr_snapshots", "rr_snapshot_calls")


def test_only_owner_rows_are_exported(seeded):
    rows = _lines(seeded, ALICE)[1:]
    owners = {ln["row"]["owner_sub"] for ln in rows if "owner_sub" in ln["row"]}
    assert owners == {ALICE}
    # owner_sub 열이 없는 공용 표는 그대로 실린다.
    assert any(ln["table"] == "rr_dim_vocab" for ln in rows)


def test_blob_is_base64_wrapped(seeded):
    call = next(ln["row"] for ln in _lines(seeded)[1:] if ln["table"] == "rr_snapshot_calls")
    assert set(call["response_gz"]) == {"__b64__"}
    assert export._decode(call["response_gz"]) == BLOB


def test_since_filters_by_time_column(seeded):
    recent = [ln for ln in _lines(seeded, BOB, since=5_000)[1:] if ln["table"] == "rr_projects"]
    assert len(recent) == 1                        # bob 의 행은 at=9000
    old = [ln for ln in _lines(seeded, ALICE, since=5_000)[1:] if ln["table"] == "rr_projects"]
    assert old == []                               # alice 의 행은 at=1000


def test_write_export_file_leaves_a_copy(seeded, tmp_path):
    path = export.write_export_file(seeded, ALICE, 0, data_dir=tmp_path)
    assert path.parent == tmp_path / export.EXPORTS_DIRNAME and path.suffix == ".jsonl"
    assert path.read_text(encoding="utf-8") == "".join(export.iter_lines(seeded, ALICE, 0, tmp_path))
    again = export.write_export_file(seeded, ALICE, 0, data_dir=tmp_path)
    assert again != path                           # 같은 초에 두 번 불러도 앞 파일을 덮지 않는다


# ---------------------------------------------------------------- 왕복
@pytest.fixture
def empty_store(tmp_path):
    store = RiskStore(tmp_path / "dest" / "risk_review.db")
    store.open()
    store.migrate()
    yield store
    store.close()


def test_roundtrip_into_empty_db_matches_row_counts_and_hashes(seeded, empty_store):
    body = "".join(export.iter_lines(seeded, ALICE, 0))
    data_lines = len(body.splitlines()) - 1
    result = export.import_jsonl(empty_store, ALICE, body)
    # 공용 표(owner_sub 열이 없는 rr_dim_vocab·rr_rules·rr_metrics·rr_delta_priors)는 export 에는 실리지만
    # import 는 병합하지 않고 skipped_global 로 센다 — 남의 박스 어휘·규칙을 덮지 않기 위해서다(export.import_jsonl).
    assert result["inserted"] + result["skipped_global"] == data_lines
    assert result["merged"] == 0 and result["conflicts"] == []
    # 소유자 행은 바이트 그대로 돌아온다. 공용 표는 병합 대상이 아니라 목적지에 비어 있는 것이 정상이다.
    here, there = export.row_digest(empty_store, ALICE), export.row_digest(seeded, ALICE)
    globals_ = [t for t in here if here[t] != there[t]]
    assert all(here[t][0] == 0 for t in globals_), f"공용 표 외에 차이가 있다 — {globals_}"
    assert {t: v for t, v in here.items() if t not in globals_} == {
        t: v for t, v in there.items() if t not in globals_}
    # BLOB 도 바이트 그대로 돌아온다.
    row = empty_store.query_one("SELECT response_gz FROM rr_snapshot_calls WHERE call_id = ?", ("s-ali-001",))
    assert bytes(row["response_gz"]) == BLOB


def test_second_import_is_idempotent(seeded, empty_store):
    body = "".join(export.iter_lines(seeded, ALICE, 0))
    first = export.import_jsonl(empty_store, ALICE, body)
    second = export.import_jsonl(empty_store, ALICE, body)
    assert second["inserted"] == 0 and second["merged"] == 0
    assert second["skipped"] == first["inserted"] and second["conflicts"] == []


# ---------------------------------------------------------------- 거절과 충돌
def test_schema_version_mismatch_is_409(seeded, empty_store):
    lines = list(export.iter_lines(seeded, ALICE, 0))
    head = json.loads(lines[0])
    head["schema_version"] = head["schema_version"] + 1
    body = json.dumps(head) + "\n" + "".join(lines[1:])
    with pytest.raises(AppError) as exc:
        export.import_jsonl(empty_store, ALICE, body)
    assert exc.value.http_status == 409 and exc.value.code == "schema_mismatch"
    assert empty_store.query("SELECT id FROM rr_projects") == []


def test_foreign_owner_rows_are_409(seeded, empty_store):
    body = "".join(export.iter_lines(seeded, BOB, 0))
    with pytest.raises(AppError) as exc:
        export.import_jsonl(empty_store, ALICE, body)
    assert exc.value.http_status == 409 and exc.value.code == "owner_mismatch"
    assert empty_store.query("SELECT id FROM rr_projects") == []


def test_empty_body_is_422(empty_store):
    with pytest.raises(AppError) as exc:
        export.import_jsonl(empty_store, ALICE, "   \n")
    assert exc.value.http_status == 422


def test_human_confirmation_beats_automatic(seeded, empty_store):
    _seed(empty_store, ALICE, at=1_000)
    # 들어오는 쪽만 사람 확정 — 로컬 candidate 를 이긴다.
    seeded.execute("UPDATE rr_part_keys SET status = 'confirmed', decided_by = ?, display_name = '커버' WHERE ckey = ?",
                   (ALICE, "ck-ali"))
    body = "".join(export.iter_lines(seeded, ALICE, 0))
    result = export.import_jsonl(empty_store, ALICE, body)
    assert result["merged"] == 1 and result["conflicts"] == []
    row = empty_store.query_one("SELECT status, display_name FROM rr_part_keys WHERE ckey = ?", ("ck-ali",))
    assert row["status"] == "confirmed" and row["display_name"] == "커버"


def test_local_human_confirmation_survives_automatic_incoming(seeded, empty_store):
    _seed(empty_store, ALICE, at=1_000)
    empty_store.execute("UPDATE rr_part_keys SET status = 'confirmed', decided_by = ?, display_name = '로컬' WHERE ckey = ?",
                        (ALICE, "ck-ali"))
    result = export.import_jsonl(empty_store, ALICE, "".join(export.iter_lines(seeded, ALICE, 0)))
    assert result["merged"] == 0 and result["conflicts"] == []
    row = empty_store.query_one("SELECT status, display_name FROM rr_part_keys WHERE ckey = ?", ("ck-ali",))
    assert row["status"] == "confirmed" and row["display_name"] == "로컬"


def test_both_sides_human_confirmed_and_different_goes_to_conflicts(seeded, empty_store):
    _seed(empty_store, ALICE, at=1_000)
    seeded.execute("UPDATE rr_iface_ledger SET kind_override = 'contact', note = '원격' WHERE pair_key = ?", ("n1|n2",))
    empty_store.execute("UPDATE rr_iface_ledger SET kind_override = 'clearance', note = '로컬' WHERE pair_key = ?", ("n1|n2",))
    result = export.import_jsonl(empty_store, ALICE, "".join(export.iter_lines(seeded, ALICE, 0)))
    hit = [c for c in result["conflicts"] if c["table"] == "rr_iface_ledger"]
    assert len(hit) == 1
    assert hit[0]["key"] == "p-ali|n1|n2"
    assert hit[0]["local"]["kind_override"] == "clearance" and hit[0]["incoming"]["kind_override"] == "contact"
    row = empty_store.query_one("SELECT kind_override FROM rr_iface_ledger WHERE pair_key = ?", ("n1|n2",))
    assert row["kind_override"] == "clearance"     # 마지막 쓰기 승리 없음


def test_unknown_table_is_422(seeded, empty_store):
    head = json.dumps(export.header_line(empty_store))
    body = head + "\n" + json.dumps({"table": "rr_nope", "row": {"id": "x"}}) + "\n"
    with pytest.raises(AppError) as exc:
        export.import_jsonl(empty_store, ALICE, body)
    assert exc.value.http_status == 422


# ---------------------------------------------------------------- REST 경로
@pytest.fixture
def wired(monkeypatch):
    """heax 는 TOKEN 만 200. 세션 DB 에 남긴 시험 행은 뒤에서 지운다."""
    def heax(req: httpx.Request) -> httpx.Response:
        if req.headers.get("authorization") == f"Bearer {TOKEN}":
            return httpx.Response(200, json=EXPORT_USER)
        return httpx.Response(401)

    monkeypatch.setattr(identity, "_transport", httpx.MockTransport(heax))
    identity.reset_cache()
    yield
    get_store().execute("DELETE FROM rr_projects WHERE owner_sub = ?", (EXPORT_USER["email"],))
    identity.reset_cache()


def test_export_route_is_401_for_anonymous(client, wired):
    assert client.get("/api/export").status_code == 401


def test_export_route_streams_jsonl_and_leaves_a_file(client, wired):
    r = client.get("/api/export", headers=AUTH)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/x-ndjson")
    lines = r.text.splitlines()
    head = json.loads(lines[0])
    assert set(head) == {"schema_version", "app_version", "origin"}
    saved = Path(r.headers["X-Export-Path"])
    assert saved.is_file() and saved.parent.name == export.EXPORTS_DIRNAME
    assert saved.read_text(encoding="utf-8") == r.text


def test_import_route_inserts_then_reports_mismatch(client, wired):
    store = get_store()
    row = {"id": "rt-export-1", "owner_sub": EXPORT_USER["email"], "code": "PRJ-RT", "name": "왕복",
           "stage": "concept", "character_status": "seed", "created_at": 1, "updated_at": 1}
    body = (json.dumps(export.header_line(store)) + "\n"
            + json.dumps({"table": "rr_projects", "row": row}, ensure_ascii=False) + "\n")

    first = client.post("/api/import", headers=AUTH, content=body.encode("utf-8"))
    assert first.status_code == 200, first.text
    # 응답은 회계 키를 더 갖는다(skipped_global·recomputed_targets) — 병합 결과 4키만 고정한다.
    assert {k: first.json()[k] for k in ("inserted", "merged", "skipped", "conflicts")} == {
        "inserted": 1, "merged": 0, "skipped": 0, "conflicts": []}

    again = client.post("/api/import", headers=AUTH, content=body.encode("utf-8"))
    assert again.json()["inserted"] == 0 and again.json()["skipped"] == 1

    bad_head = export.header_line(store)
    bad_head["schema_version"] = bad_head["schema_version"] + 99
    bad = client.post("/api/import", headers=AUTH,
                      content=(json.dumps(bad_head) + "\n").encode("utf-8"))
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "schema_mismatch"

    foreign = dict(row, id="rt-export-2", owner_sub="someone-else@example.com")
    other = client.post("/api/import", headers=AUTH, content=(
        json.dumps(export.header_line(store)) + "\n"
        + json.dumps({"table": "rr_projects", "row": foreign}, ensure_ascii=False) + "\n").encode("utf-8"))
    assert other.status_code == 409 and other.json()["error"]["code"] == "owner_mismatch"
    assert store.query_one("SELECT id FROM rr_projects WHERE id = ?", ("rt-export-2",)) is None


def test_import_route_is_401_for_anonymous(client, wired):
    assert client.post("/api/import", content=b"{}\n").status_code == 401
