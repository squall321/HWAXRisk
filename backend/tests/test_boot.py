# 기동 3점(plan §8.2.10) — /api/health 정확한 3키 · POST /mcp initialize 200 + mcp-session-id · GET / text/html — 와 /api/meta 계열·옛 경로 404
from __future__ import annotations

import importlib
from pathlib import Path

from app import config
from app.config import settings
from app.mcp_server import mcp


def test_health_exact_three_keys(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "app_version": settings.app_version, "schema_version": 1}


def test_mcp_initialize_with_session_header(client):
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                         "clientInfo": {"name": "pytest", "version": "0"}}},
        headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.headers.get("mcp-session-id")


def test_index_is_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


def test_old_paths_are_gone(client):
    for path in ("/health", "/api/v1/meta", "/api/v1/health", "/api/meta"):
        assert client.get(path).status_code == 404, path


def _reload_main_with_base_dir(monkeypatch, base_dir: Path):
    """config.BASE_DIR 을 바꾼 채 app.main 을 다시 import 해 '/' 마운트 분기를 다시 결정한 FastAPI 앱을 돌려준다.

    import 시점에 `_FRONTEND_DIST.is_dir()` 로 마운트가 결정되므로 reload 가 필요하다. reload 는 공유 `mcp` 의
    session_manager 를 새로 만들므로 세션 client 픽스처(run() 1회 제약)와 충돌하지 않게 호출자가 원상복구한다.
    """
    import app.main as main_mod

    monkeypatch.setattr(config, "BASE_DIR", base_dir)
    return importlib.reload(main_mod).app


def test_index_serves_dist_or_placeholder(monkeypatch, tmp_path):
    """단일 실행에서 두 분기를 모두 고정한다 — dist 있음 → dist/index.html, dist 없음 → app/static 플레이스홀더."""
    from fastapi.testclient import TestClient

    import app.main as main_mod

    orig_app = main_mod.app
    orig_session_manager = mcp._session_manager
    try:
        fake_root = tmp_path / "with_dist"
        fake_index = fake_root / "frontend" / "dist" / "index.html"
        fake_index.parent.mkdir(parents=True)
        fake_index.write_text("<!doctype html><title>fake dist</title>", encoding="utf-8")
        with_dist = _reload_main_with_base_dir(monkeypatch, fake_root)
        # lifespan 없이(GET / 만) 친다 — MCP session_manager.run() 을 두 번 열지 않기 위해서다.
        r = TestClient(with_dist).get("/")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert r.text == fake_index.read_text(encoding="utf-8")

        no_dist = _reload_main_with_base_dir(monkeypatch, tmp_path / "without_dist")
        r = TestClient(no_dist).get("/")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "P0" in r.text
        # 서브패스(/apps/hwax_risk) 아래에서도 동작하도록 상대 링크(api/health)를 쓴다.
        assert "api/health" in r.text and "api/v1" not in r.text and "api/meta\"" not in r.text
        for name in ("risk_get_snapshot", "risk_submit_panel_result"):
            assert name in r.text
    finally:
        monkeypatch.undo()
        importlib.reload(main_mod)
        main_mod.app = orig_app
        mcp._session_manager = orig_session_manager


def test_meta_taxonomy(client):
    r = client.get("/api/meta/taxonomy")
    assert r.status_code == 200
    body = r.json()
    assert body["taxonomy_version"] == "1.0"
    axes = body["axes"]
    assert {"mechanism", "change_kind", "trigger_condition", "severity_judgement",
            "detectability", "evidence_grade", "precedent", "direction", "status"} <= set(axes)
    assert axes["severity_judgement"] == {"경미": ["OK", "WARNING"], "중대": ["WARNING", "FAIL"], "치명": ["FAIL"]}


def test_meta_adapters_p0_fixed_list(client):
    r = client.get("/api/meta/adapters")
    assert r.status_code == 200
    assert r.json() == [
        {"kind": "mcad", "app": "heax-step_forge", "status": "planned"},
        {"kind": "dyna", "app": "heax-kooremapper_mcp", "status": "planned"},
        {"kind": "ecad", "app": None, "status": "contract_only"},
    ]


def test_meta_vocab_lists_runtime_assets(client):
    r = client.get("/api/meta/vocab")
    assert r.status_code == 200
    text = str(r.json())
    for name in ("character-vocab", "seat-contract", "rules-seed", "adjacency", "character-seed-rules"):
        assert name in text, f"{name} 가 /meta/vocab 응답에 없다"
    assert "1.0" in text or "version" in text.lower()
