# GET /api/export · POST /api/import — JSONL 헤더·표 순서·소유자 스코프·since, 왕복(빈 DB import 후 행 수·해시 동일), 409 schema_mismatch·owner_mismatch, 사람 확정 우선·conflicts[]
from __future__ import annotations

import json
import stat
from pathlib import Path

import httpx
import pytest

from app import config, export, identity
from app.errors import AppError
from app.risk_store import RiskStore, get_store

from app.risk_store import MIGRATIONS as _MIGRATIONS

LATEST_SCHEMA = _MIGRATIONS[-1][0]

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
    _insert(store, "rr_snapshot_calls", {"call_id": f"{sid}-001", "job_id": sid, "snapshot_id": sid,
                                         "owner_sub": owner, "seq": 1,
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
    assert head["schema_version"] == seeded.schema_version() == LATEST_SCHEMA
    assert head["app_version"] == config.APP_VERSION
    assert isinstance(head["origin"], dict) and "hostname" in head["origin"]


def test_default_export_scopes_target_keyed_rows_by_their_project(risk_store):
    """기본 반출은 과제 열이 없는 대상 열쇠 표(등록부 · 기여 …)도 과제 열 표와 같은 규칙으로 거른다 — 코퍼스에서 뺀(기밀) 과제의 대상에
    매인 행은 싣지 않고 include_excluded 로만 싣는다. 종전에는 그 행이 실리는데 classification_max 는 'internal' 이었다(조합 검토 M9)."""
    _seed(risk_store, ALICE, at=1_000)
    risk_store.execute("UPDATE rr_projects SET corpus_excluded = 1, excluded_reason = 'user', classification = 'confidential'"
                       " WHERE id = 'p-ali'")
    _insert(risk_store, "rr_registry", {"target_key": "t-ali", "cluster_key": "ck:excluded01", "owner_sub": ALICE,
                                        "merged_json": "{}", "status": "open", "updated_at": 1_000})
    _insert(risk_store, "rr_delta_contrib", {"change_kind": "placement", "mechanism": "interface",
                                             "mechanism_detail": "interference", "target_key": "t-ali",
                                             "owner_sub": ALICE, "resolving_checks_json": '["기밀 확인 절차"]',
                                             "updated_at": 1_000})
    default = {line["table"] for line in _lines(risk_store)[1:]}
    assert not {"rr_targets", "rr_registry", "rr_delta_contrib"} & default
    assert export.classification_max(risk_store, ALICE) == "internal"
    widened = {json.loads(ln)["table"] for ln in list(export.iter_lines(risk_store, ALICE, 0, include_excluded=True))[1:]}
    assert {"rr_targets", "rr_registry", "rr_delta_contrib"} <= widened
    assert export.classification_max(risk_store, ALICE, include_excluded=True) == "confidential"


# 스냅샷 · diff 열쇠 표 — 과제 열도 대상 열쇠도 없다(D50). 표마다 그 행이 매인 스냅샷 · diff 를 읽는 칸.
SNAPSHOT_DIFF_KEYS = {"rr_snapshot_calls": "snapshot_id", "rr_ir_nodes": "snapshot_id", "rr_ir_edges": "snapshot_id",
                      "rr_states": "snapshot_id", "rr_gate_acks": "snapshot_id", "rr_diffs": "id", "rr_diff_events": "diff_id"}


def _snapshot_rows(store: RiskStore, owner: str, pid: str, sid: str, at: int, *, with_rows: bool = True) -> None:
    _insert(store, "rr_snapshots", {"id": sid, "project_id": pid, "owner_sub": owner, "ir_version": "1.0",
                                    "ir_hash": f"hash-{sid}", "ir_json": '{"nodes":[]}', "source_ids_json": "[]",
                                    "kinds_json": '["mcad"]', "node_count": 1, "edge_count": 1, "warnings_n": 0,
                                    "created_at": at})
    if not with_rows:
        return
    _insert(store, "rr_snapshot_calls", {"call_id": f"{sid}-001", "job_id": sid, "snapshot_id": sid, "owner_sub": owner,
                                         "seq": 1, "source_kind": "mcad", "channel": "rest", "tool": "/tree", "ok": 1,
                                         "started_at": at})
    _insert(store, "rr_ir_nodes", {"snapshot_id": sid, "nid": "n1", "owner_sub": owner, "kind": "part",
                                   "source_kind": "mcad", "name": "N1", "name_norm": "n1"})
    _insert(store, "rr_ir_edges", {"snapshot_id": sid, "eid": "e1", "owner_sub": owner, "kind": "interference",
                                   "kind_family": "contact", "a": "n1", "b": "n1", "status": "auto"})
    _insert(store, "rr_states", {"snapshot_id": sid, "owner_sub": owner, "state_json": "{}", "feature_json": "{}",
                                 "gates_json": "{}", "computed_at": at})


def _diff_rows(store: RiskStore, owner: str, did: str, base: tuple[str, str], target: tuple[str, str], at: int) -> None:
    """diff 한 건(base · target 은 (과제, 스냅샷))과 그 이벤트 한 줄 · target 스냅샷의 게이트 확인 한 줄."""
    _insert(store, "rr_diffs", {"id": did, "owner_sub": owner, "base_snapshot_id": base[1], "target_snapshot_id": target[1],
                                "base_project_id": base[0], "target_project_id": target[0], "diff_version": "1.0",
                                "diff_json": "{}", "summary_text": "기밀 변경 요약", "created_at": at})
    _insert(store, "rr_diff_events", {"diff_id": did, "cid": "c:000000000001", "owner_sub": owner, "layer": "structural",
                                      "code": "part_added", "text": "기밀 부품이 더해졌다"})


def _subjects(lines) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {table: set() for table in SNAPSHOT_DIFF_KEYS}
    for line in lines:
        if line["table"] in out:
            out[line["table"]].add(line["row"][SNAPSHOT_DIFF_KEYS[line["table"]]])
    return out


def test_default_export_scopes_snapshot_and_diff_rows_by_their_project(risk_store):
    """기본 반출은 스냅샷 · diff 열쇠 표(스냅샷 호출 · IR 노드 · 엣지 · 상태 · 게이트 확인 · diff · diff 이벤트)도 그 과제를 따른다 —
    코퍼스에서 뺀 기밀 과제의 스냅샷 · diff 행은 싣지 않고 include_excluded 로만 싣는다. diff 는 base · target 두 과제가 모두 반출
    범위여야 실린다(읽기 문지기 mcp_scope_owner 와 같은 규칙 — 한쪽이 빠진 비교는 빠진 쪽의 내용을 싣는다). 스냅샷이 없는 호출
    (실패 · 부분 잡의 원문)은 그 스냅샷 잡의 과제를 따른다. 범위 안 과제의 행은 그대로 실린다(D50)."""
    at = 1_000
    for pid, code, grade in (("p-secret", "SECRET-1", "confidential"), ("p-kept", "KEPT-1", "internal")):
        _insert(risk_store, "rr_projects", {"id": pid, "owner_sub": ALICE, "code": code, "name": "케이스", "stage": "concept",
                                            "classification": grade, "character_status": "seed", "created_at": at,
                                            "updated_at": at})
    risk_store.execute("UPDATE rr_projects SET corpus_excluded = 1, excluded_reason = 'user' WHERE id = 'p-secret'")
    _snapshot_rows(risk_store, ALICE, "p-secret", "s-secret", at)
    _snapshot_rows(risk_store, ALICE, "p-secret", "s-secret2", at, with_rows=False)
    _snapshot_rows(risk_store, ALICE, "p-kept", "s-kept", at)
    _snapshot_rows(risk_store, ALICE, "p-kept", "s-kept2", at, with_rows=False)
    _diff_rows(risk_store, ALICE, "d-secret", ("p-secret", "s-secret"), ("p-secret", "s-secret2"), at)
    _diff_rows(risk_store, ALICE, "d-cross", ("p-secret", "s-secret"), ("p-kept", "s-kept"), at)
    _diff_rows(risk_store, ALICE, "d-kept", ("p-kept", "s-kept"), ("p-kept", "s-kept2"), at)
    for sid, did in (("s-secret", "d-secret"), ("s-kept", "d-kept")):
        _insert(risk_store, "rr_gate_acks", {"snapshot_id": sid, "gate": "G1", "owner_sub": ALICE, "diff_id": did,
                                             "ack_by": ALICE, "ack_at": at, "ack_reason": "넘긴다", "gates_hash": "h"})
    # 스냅샷이 없는 호출 — 실패한 스냅샷 잡의 원문(그 잡의 과제를 따른다).
    for pid, job in (("p-secret", "job-secret"), ("p-kept", "job-kept")):
        _insert(risk_store, "rr_snapshot_jobs", {"id": job, "project_id": pid, "owner_sub": ALICE, "kinds_json": '["mcad"]',
                                                 "state": "failed", "created_at": at})
        _insert(risk_store, "rr_snapshot_calls", {"call_id": f"{job}-001", "job_id": job, "snapshot_id": None,
                                                  "owner_sub": ALICE, "seq": 1, "source_kind": "mcad", "channel": "rest",
                                                  "tool": "/tree", "ok": 0, "started_at": at})
    default_lines = _lines(risk_store)[1:]
    assert _subjects(default_lines) == {"rr_snapshot_calls": {"s-kept", None}, "rr_ir_nodes": {"s-kept"},
                                        "rr_ir_edges": {"s-kept"}, "rr_states": {"s-kept"}, "rr_gate_acks": {"s-kept"},
                                        "rr_diffs": {"d-kept"}, "rr_diff_events": {"d-kept"}}
    assert {ln["row"]["call_id"] for ln in default_lines if ln["table"] == "rr_snapshot_calls"} == {"s-kept-001", "job-kept-001"}
    assert export.classification_max(risk_store, ALICE) == "internal"
    widened = [json.loads(ln) for ln in list(export.iter_lines(risk_store, ALICE, 0, include_excluded=True))[1:]]
    assert _subjects(widened) == {"rr_snapshot_calls": {"s-secret", "s-kept", None}, "rr_ir_nodes": {"s-secret", "s-kept"},
                                  "rr_ir_edges": {"s-secret", "s-kept"}, "rr_states": {"s-secret", "s-kept"},
                                  "rr_gate_acks": {"s-secret", "s-kept"}, "rr_diffs": {"d-secret", "d-cross", "d-kept"},
                                  "rr_diff_events": {"d-secret", "d-cross", "d-kept"}}
    assert {ln["row"]["call_id"] for ln in widened if ln["table"] == "rr_snapshot_calls"} == {
        "s-secret-001", "s-kept-001", "job-secret-001", "job-kept-001"}


def test_rows_follow_plan_table_order_and_skip_housekeeping(seeded):
    tables = [ln["table"] for ln in _lines(seeded)[1:]]
    assert tables, "행이 하나도 실리지 않았다"
    assert set(tables) <= set(export.TABLE_ORDER)
    assert not any(t.startswith("_") for t in tables)
    order = {t: i for i, t in enumerate(export.TABLE_ORDER)}
    assert [order[t] for t in tables] == sorted(order[t] for t in tables)
    # 순서는 plan §5.2.2 v1 DDL 의 CREATE TABLE 차례 그대로다(과제 → 요구·멤버 → 소스 → 스냅샷 …).
    assert export.TABLE_ORDER[:6] == ("rr_projects", "rr_requirements", "rr_project_members", "rr_sources",
                                      "rr_snapshots", "rr_snapshot_jobs")


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


# ---------------------------------------------------------------- v4(재설계 M2) — 검토 단위·셀 원장
V4_EXPORTED = ("rr_unit_builds", "rr_units", "rr_expert_reports", "rr_review_cells", "rr_card_verdicts",
               "rr_review_calls")
# v5(재설계 M3) — 쟁점·요약·보고서 판·완결 확인·근거 꾸러미 실호출. 박스 지역 표는 없다(M3.md 4.2).
V5_EXPORTED = ("rr_issues", "rr_summaries", "rr_reports", "rr_close_acks", "rr_unit_live")


def test_v4_tables_ride_the_export_except_the_local_card_packs(seeded, empty_store):
    """새 표 여섯은 반출 표 목록에서 v5 표 앞에 붙고 since 열이 실제 열이다. 카드 묶음은 박스 지역 사본이라 목록에 없다.
    새 표가 빈 원장도 빈 DB 로 왕복해 같은 행 수·해시다(행이 든 왕복은 C2 의 생산자가 생긴 뒤 본다)."""
    assert export.LOCAL_ONLY_TABLES == {"rr_card_packs"}
    head = export.TABLE_ORDER[:-len(V5_EXPORTED)]
    assert head[-len(V4_EXPORTED):] == V4_EXPORTED
    assert "rr_card_packs" not in export.TABLE_ORDER
    for table in V4_EXPORTED:
        cols, _ = export._table_meta(seeded, table)
        assert export._SINCE_COLS[table] and set(export._SINCE_COLS[table]) <= set(cols), table
        assert "owner_sub" in cols, table
    assert export._EXPORT_SKIP_COLUMNS["rr_review_calls"] == ("result_gz",)

    body = "".join(export.iter_lines(seeded, ALICE, 0))
    assert json.loads(body.splitlines()[0])["schema_version"] == LATEST_SCHEMA == 5
    assert not any(json.loads(ln)["table"] == "rr_card_packs" for ln in body.splitlines()[1:])
    export.import_jsonl(empty_store, ALICE, body)
    here, there = export.row_digest(empty_store, ALICE), export.row_digest(seeded, ALICE)
    assert "rr_card_packs" not in here
    assert {t: here[t] for t in V4_EXPORTED} == {t: there[t] for t in V4_EXPORTED}
    assert all(here[t][0] == 0 for t in V4_EXPORTED)


def test_v5_tables_ride_the_export_at_the_end_with_real_since_columns(seeded, empty_store):
    """v5 새 표 다섯은 반출 표 목록 끝에 붙고(박스 지역 표 없음), since 열이 실제 열이며 owner_sub 가 있다. 고쳐 쓰는 행은
    updated_at 이 먼저고, 완결 확인은 취소 시각(revoked_at)이 먼저다 — 취소가 since 반출에서 빠지지 않게. 새 표가 빈 v5 원장도
    빈 DB 로 왕복해 같은 행 수·해시다(행이 든 왕복은 각 표의 생산자 걸음이 본다 — tests/rr/test_v5_rows.py)."""
    assert export.TABLE_ORDER[-len(V5_EXPORTED):] == V5_EXPORTED
    assert not export.LOCAL_ONLY_TABLES & set(V5_EXPORTED)
    for table in V5_EXPORTED:
        cols, _ = export._table_meta(seeded, table)
        assert export._SINCE_COLS.get(table) and set(export._SINCE_COLS[table]) <= set(cols), table
        assert "owner_sub" in cols and "target_key" in cols, table
        assert table not in export._EXPORT_SKIP_COLUMNS, table
    assert {t: (export._SINCE_COLS.get(t) or ("",))[0] for t in V5_EXPORTED} == {
        "rr_issues": "updated_at", "rr_summaries": "updated_at", "rr_reports": "created_at",
        "rr_close_acks": "revoked_at", "rr_unit_live": "updated_at"}

    body = "".join(export.iter_lines(seeded, ALICE, 0))
    export.import_jsonl(empty_store, ALICE, body)
    here, there = export.row_digest(empty_store, ALICE), export.row_digest(seeded, ALICE)
    assert {t: here[t] for t in V5_EXPORTED} == {t: there[t] for t in V5_EXPORTED}
    assert all(here[t][0] == 0 for t in V5_EXPORTED)


def test_card_pack_lines_are_refused_on_import(empty_store):
    """카드 묶음 줄은 들여오지 않는다 — 반출이 싣지 않는 표라 손으로 만든 줄이면 '알 수 없는 표' 다."""
    head = json.dumps(export.header_line(empty_store))
    row = {"agent_key": "a", "pack_hash": "h", "norm_rev": "n", "role_sha": "r", "cards_total": 0, "checkable_n": 0,
           "chars_total": 0, "manifest_json": "[]", "pack_gz": {"__b64__": ""}, "source": "x", "fetched_at": 1}
    with pytest.raises(AppError) as exc:
        export.import_jsonl(empty_store, ALICE, head + "\n" + json.dumps({"table": "rr_card_packs", "row": row}) + "\n")
    assert exc.value.http_status == 422 and "rr_card_packs" in exc.value.message
    assert empty_store.query("SELECT agent_key FROM rr_card_packs") == []


def test_export_cuts_a_card_quote_to_200_chars_and_keeps_its_length():
    """판정 행의 카드 인용은 판정당 200자만 나가고 원문 길이가 cq_chars 에 실린다(사용자 결정 2026-10-12).
    한 번 줄인 행을 다시 내보내도 원래 길이가 남는다. 200자 안의 인용과 다른 표는 그대로다."""
    quote = "온도 사이클 1000회 뒤 솔더 접합부 균열 길이가 접합 폭의 25%를 넘으면 불합격으로 판정한다. " * 8
    assert len(quote) > export.EXPORT_CQ_MAX == 200
    row = {"record_id": "r1", "variant": "fwd", "cq": quote, "cq_chars": None, "why": "근거"}
    out = export._export_view("rr_card_verdicts", row)
    assert out["cq"] == quote[:200] and out["cq_chars"] == len(quote)
    assert {k: v for k, v in out.items() if k not in ("cq", "cq_chars")} == {
        k: v for k, v in row.items() if k not in ("cq", "cq_chars")}
    assert row["cq"] == quote                                   # 원장 행(입력)은 건드리지 않는다
    assert export._export_view("rr_card_verdicts", out) == out  # 다시 내보내도 같다
    for short in ({**row, "cq": quote[:200]}, {**row, "cq": None}, {**row, "cq": ""}):
        assert export._export_view("rr_card_verdicts", short) == short
    assert export._export_view("rr_findings", {"cq": quote}) == {"cq": quote}


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
    # 서버 절대 경로는 헤더로 흘리지 않는다 — 파일명만 남고 등급은 X-Risk-Classification-Max 로 온다(§0.6).
    assert "X-Export-Path" not in r.headers
    assert r.headers["X-Risk-Classification-Max"] in ("internal", "confidential")
    saved = Path(config.settings.data_dir) / export.EXPORTS_DIRNAME / r.headers["X-Export-File"]
    assert saved.is_file() and saved.parent.name == export.EXPORTS_DIRNAME
    assert saved.read_text(encoding="utf-8") == r.text
    # 사본은 평문이라 0600 으로 남는다(plan §5.2.5 (1)).
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600


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
