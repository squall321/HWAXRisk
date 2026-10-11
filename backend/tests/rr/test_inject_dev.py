# dev 주입 스크립트(tests/synth/inject_dev.py)가 diff 까지만 넣고, 없는 DB·다른 스키마·같은 코드에서는 아무것도 쓰지 않는지 본다
from __future__ import annotations

import json

from tests.synth import inject_dev

OWNER = "dev@example.com"


def _rows(store, table: str) -> int:
    return store.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"]


def test_diff_까지만_넣고_심사_대상은_열지_않는다(risk_store, capsys):
    data_dir = risk_store.db_path.parent
    assert inject_dev.main(["--data-dir", str(data_dir), "--owner", OWNER, "--size", "3"]) == 0
    out = json.loads(capsys.readouterr().out)
    project = risk_store.query_one("SELECT owner_sub, code FROM rr_projects WHERE id = ?", (out["project_id"],))
    assert (project["owner_sub"], project["code"]) == (OWNER, out["code"])
    assert risk_store.query_one("SELECT 1 AS x FROM rr_diffs WHERE id = ?", (out["diff_id"],))
    assert _rows(risk_store, "rr_targets") == 0
    assert out["changes"] == 3


def test_같은_코드가_있으면_멈춘다(risk_store, capsys):
    args = ["--data-dir", str(risk_store.db_path.parent), "--owner", OWNER, "--size", "3"]
    assert inject_dev.main(args) == 0
    before = _rows(risk_store, "rr_snapshots")
    assert inject_dev.main(args) == 2
    assert "이미 있다" in capsys.readouterr().err
    assert _rows(risk_store, "rr_snapshots") == before


def test_DB_가_없으면_만들지_않는다(tmp_path, capsys):
    assert inject_dev.main(["--data-dir", str(tmp_path), "--owner", OWNER, "--size", "3"]) == 2
    assert not (tmp_path / "risk_review.db").exists()


def test_스키마가_다르면_쓰지_않는다(risk_store, monkeypatch, capsys):
    monkeypatch.setattr(inject_dev, "MIGRATIONS", [*inject_dev.MIGRATIONS, (99, [])])
    assert inject_dev.main(["--data-dir", str(risk_store.db_path.parent), "--owner", OWNER, "--size", "3"]) == 2
    assert "코드 99" in capsys.readouterr().err
    assert _rows(risk_store, "rr_projects") == 0
