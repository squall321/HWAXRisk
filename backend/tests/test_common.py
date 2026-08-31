# common.py 결정론 유틸(canonical_json·sha256_hex·R·now_epoch·new_uuid·make_ref/parse_ref)과 RiskStore 원시 도구(tx·query·execute) 검증
from __future__ import annotations

import json
import math
import sqlite3

import pytest

from app.common import (
    R,
    ROUNDING,
    canonical_json,
    make_ref,
    new_uuid,
    now_epoch,
    parse_ref,
    set_clock,
    sha256_hex,
)


# ---------------------------------------------------------------- canonical_json · sha256_hex
def test_canonical_json_is_order_independent_and_compact():
    a = canonical_json({"b": 1, "a": {"z": [1, 2], "y": None}})
    b = canonical_json({"a": {"y": None, "z": [1, 2]}, "b": 1})
    assert a == b == '{"a":{"y":null,"z":[1,2]},"b":1}'
    assert " " not in a


def test_canonical_json_keeps_unicode_raw():
    assert canonical_json({"과제": "리스크"}) == '{"과제":"리스크"}'


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_nan_and_inf(bad):
    with pytest.raises(ValueError):
        canonical_json({"v": bad})


def test_sha256_hex_matches_utf8_hash():
    assert sha256_hex("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256_hex("리스크") == sha256_hex("리스크".encode("utf-8"))
    assert len(sha256_hex(canonical_json({"a": 1}))) == 64


# ---------------------------------------------------------------- R(반올림 규칙 §2.11.1)
def test_rounding_table_matches_plan():
    assert ROUNDING == {
        "length": ("decimals", 3),
        "ratio": ("decimals", 3),
        "alignment": ("decimals", 3),
        "fs": ("decimals", 2),
        "stress": ("decimals", 1),
        "acceleration": ("decimals", 1),
        "area": ("sigfigs", 4),
        "volume": ("sigfigs", 4),
    }


@pytest.mark.parametrize(
    "value,kind,expected",
    [
        (0.0123456, "length", 0.012),      # 길이 0.001 mm
        (1.23456789, "length", 1.235),
        (0.0005, "length", 0.001),         # ROUND_HALF_UP
        (812.43219, "area", 812.4),        # 면적 4 유효자리
        (0.00123456, "area", 0.001235),
        (1234567.0, "volume", 1235000.0),  # 부피 4 유효자리
        (0.166666, "ratio", 0.167),
        (0.99949, "alignment", 0.999),
        (1.2349, "fs", 1.23),
        (123.456, "stress", 123.5),
        (9.849, "acceleration", 9.8),
        (0, "area", 0.0),
        (-0.0001, "length", 0.0),          # -0.0 은 0.0 으로 접는다
    ],
)
def test_R_rounds_per_kind(value, kind, expected):
    assert R(value, kind) == expected


def test_R_passes_through_non_numbers():
    assert R(None, "length") is None
    assert R("12.3 mm", "length") == "12.3 mm"
    assert R(True, "ratio") is True


def test_R_rejects_unknown_kind_and_non_finite():
    with pytest.raises(ValueError):
        R(1.0, "torque")
    with pytest.raises(ValueError):
        R(math.nan, "length")


def test_R_is_deterministic_and_json_safe():
    values = [0.1 + 0.2, 1 / 3, 2.675]
    once = [R(v, "length") for v in values]
    assert once == [R(v, "length") for v in values]
    assert json.loads(canonical_json(once)) == once


# ---------------------------------------------------------------- 시계·id
def test_now_epoch_is_injectable():
    previous = set_clock(lambda: 1_700_000_000)
    try:
        assert now_epoch() == 1_700_000_000
    finally:
        set_clock(None)
    assert now_epoch() != 1_700_000_000
    assert callable(previous)


def test_new_uuid_is_hex32():
    a, b = new_uuid(), new_uuid()
    assert len(a) == 32 and int(a, 16) >= 0
    assert a != b


# ---------------------------------------------------------------- 참조 문법(§0.2.1)
@pytest.mark.parametrize(
    "text,expected",
    [
        ("p:0123456789ab", {"kind": "p", "id": "0123456789ab"}),
        ("[e:00ff00ff00ff]", {"kind": "e", "id": "00ff00ff00ff"}),
        ("c:abcdef012345", {"kind": "c", "id": "abcdef012345"}),
        ("d:bbox_dz", {"kind": "d", "name": "bbox_dz"}),
        ("name:BRACKET|COVER", {"kind": "name", "a": "BRACKET", "b": "COVER"}),
        ("tool:1a2b3c4d-007", {"kind": "tool", "call_id": "1a2b3c4d-007"}),
        ("tool:conv:cv1#3", {"kind": "tool", "conv_id": "cv1", "idx": 3}),
        ("card:rec_88", {"kind": "card", "record_id": "rec_88"}),
        ("narr:op1#F2", {"kind": "narr", "opinion_id": "op1", "finding_id": "F2"}),
        ("narr:ch7", {"kind": "narr", "character_id": "ch7"}),
        ("reg:snap:s1#0123456789ab", {"kind": "reg", "target_key": "snap:s1", "cluster_key": "0123456789ab"}),
        ("warn:unit_mismatch#p:0123456789ab", {"kind": "warn", "code": "unit_mismatch", "ref_to": "p:0123456789ab"}),
        ("warn:files_all_overlap", {"kind": "warn", "code": "files_all_overlap", "ref_to": None}),
        ("gate:G6", {"kind": "gate", "gate": "G6", "n": 6}),
        ("sig:partial_scope", {"kind": "sig", "key": "partial_scope"}),
        ("rule:R-012", {"kind": "rule", "rule_id": "R-012"}),
        ("rpt:dyna:rpt:99", {"kind": "rpt", "report_id": "dyna:rpt:99"}),
        ("inc:obj_5", {"kind": "inc", "object_id": "obj_5"}),
    ],
)
def test_parse_ref_reads_every_scheme(text, expected):
    parsed = parse_ref(text)
    assert parsed is not None
    assert {k: parsed[k] for k in expected} == expected
    assert parsed["ref"] == text.strip("[]")


@pytest.mark.parametrize(
    "text",
    ["", "그냥 문장", "x:1", "p:", "p:ZZZZZZZZZZZZ", "p:0123", "name:BRACKET", "reg:snap:s1", "gate:six",
     "tool:conv:cv1", "tool:conv:cv1#x"],
)
def test_parse_ref_returns_none_for_non_refs(text):
    assert parse_ref(text) is None


def test_parse_ref_accepts_brackets_and_whitespace():
    assert parse_ref(" [d:min_gap] ") == parse_ref("d:min_gap")


@pytest.mark.parametrize(
    "kind,parts,expected",
    [
        ("p", {"id": "0123456789ab"}, "p:0123456789ab"),
        ("name", {"a": "COVER", "b": "BRACKET"}, "name:BRACKET|COVER"),
        ("tool", {"conv_id": "cv1", "idx": 3}, "tool:conv:cv1#3"),
        ("narr", {"opinion_id": "op1", "finding_id": "F2"}, "narr:op1#F2"),
        ("narr", {"character_id": "ch7"}, "narr:ch7"),
        ("reg", {"target_key": "diff:d1", "cluster_key": "0123456789ab"}, "reg:diff:d1#0123456789ab"),
        ("warn", {"code": "unit_mismatch"}, "warn:unit_mismatch"),
        ("gate", {"n": 7}, "gate:G7"),
    ],
)
def test_make_ref_builds_and_round_trips(kind, parts, expected):
    ref = make_ref(kind, **parts)
    assert ref == expected
    assert parse_ref(ref)["kind"] == kind


def test_make_ref_name_is_order_insensitive():
    assert make_ref("name", a="A", b="B") == make_ref("name", a="B", b="A")


def test_make_ref_rejects_bad_input():
    with pytest.raises(ValueError):
        make_ref("p", id="nothex")
    with pytest.raises(ValueError):
        make_ref("d")
    with pytest.raises(ValueError):
        make_ref("zzz", id="0123456789ab")


# ---------------------------------------------------------------- RiskStore 원시 도구
def _vocab(store, name):
    return store.query_one("SELECT name, kind, unit FROM rr_dim_vocab WHERE name = ?", (name,))


def test_query_returns_sqlite_rows(risk_store):
    risk_store.execute("INSERT INTO rr_dim_vocab(name, kind, unit) VALUES (?, ?, ?)", ("bbox_dz", "overall", "mm"))
    rows = risk_store.query("SELECT name, kind, unit FROM rr_dim_vocab ORDER BY name")
    assert len(rows) == 1
    assert isinstance(rows[0], sqlite3.Row)
    assert rows[0]["kind"] == "overall"
    assert dict(rows[0]) == {"name": "bbox_dz", "kind": "overall", "unit": "mm"}


def test_execute_returns_rowcount_and_commits(risk_store, tmp_path):
    assert risk_store.execute(
        "INSERT INTO rr_dim_vocab(name, kind) VALUES (?, ?)", ("gap_a", "gap")) == 1
    assert risk_store.execute("UPDATE rr_dim_vocab SET unit = ? WHERE name = ?", ("mm", "gap_a")) == 1
    assert risk_store.execute("DELETE FROM rr_dim_vocab WHERE name = ?", ("nope",)) == 0
    # 별도 연결에서 보인다 = commit 됐다.
    con = sqlite3.connect(tmp_path / "risk_review.db")
    try:
        assert con.execute("SELECT unit FROM rr_dim_vocab WHERE name='gap_a'").fetchone()[0] == "mm"
    finally:
        con.close()


def test_query_one_returns_none_when_absent(risk_store):
    assert _vocab(risk_store, "없는이름") is None


def test_executemany_inserts_all(risk_store):
    n = risk_store.executemany(
        "INSERT INTO rr_dim_vocab(name, kind) VALUES (?, ?)",
        [("d1", "gap"), ("d2", "gap"), ("d3", "offset")],
    )
    assert n == 3
    assert len(risk_store.query("SELECT name FROM rr_dim_vocab")) == 3


def test_tx_commits_on_success(risk_store):
    with risk_store.tx():
        risk_store.execute("INSERT INTO rr_dim_vocab(name, kind) VALUES (?, ?)", ("t1", "gap"))
        risk_store.execute("INSERT INTO rr_dim_vocab(name, kind) VALUES (?, ?)", ("t2", "gap"))
    assert len(risk_store.query("SELECT name FROM rr_dim_vocab")) == 2


def test_tx_rolls_back_on_exception(risk_store):
    with pytest.raises(RuntimeError):
        with risk_store.tx():
            risk_store.execute("INSERT INTO rr_dim_vocab(name, kind) VALUES (?, ?)", ("t1", "gap"))
            raise RuntimeError("중단")
    assert risk_store.query("SELECT name FROM rr_dim_vocab") == []
    # 롤백 뒤에도 저장소는 계속 쓸 수 있다.
    risk_store.execute("INSERT INTO rr_dim_vocab(name, kind) VALUES (?, ?)", ("t2", "gap"))
    assert _vocab(risk_store, "t2") is not None


def test_tx_is_reentrant_and_commits_once(risk_store):
    with risk_store.tx():
        risk_store.execute("INSERT INTO rr_dim_vocab(name, kind) VALUES (?, ?)", ("outer", "gap"))
        with risk_store.tx():
            risk_store.execute("INSERT INTO rr_dim_vocab(name, kind) VALUES (?, ?)", ("inner", "gap"))
        # 안쪽 블록이 끝나도 아직 열린 트랜잭션이다.
        assert risk_store.conn.in_transaction
    assert not risk_store.conn.in_transaction
    assert {r["name"] for r in risk_store.query("SELECT name FROM rr_dim_vocab")} == {"outer", "inner"}


def test_nested_tx_failure_rolls_back_everything(risk_store):
    with pytest.raises(ValueError):
        with risk_store.tx():
            risk_store.execute("INSERT INTO rr_dim_vocab(name, kind) VALUES (?, ?)", ("outer", "gap"))
            with risk_store.tx():
                risk_store.execute("INSERT INTO rr_dim_vocab(name, kind) VALUES (?, ?)", ("inner", "gap"))
                raise ValueError("안쪽 실패")
    assert risk_store.query("SELECT name FROM rr_dim_vocab") == []


def test_tx_yields_the_connection(risk_store):
    with risk_store.tx() as conn:
        assert conn is risk_store.conn
        conn.execute("INSERT INTO rr_dim_vocab(name, kind) VALUES (?, ?)", ("direct", "gap"))
    assert _vocab(risk_store, "direct") is not None
