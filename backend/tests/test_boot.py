# 기동 3점(plan §8.2.10) — /api/health 정확한 3키 · POST /mcp initialize 200 + mcp-session-id · GET / text/html — 와 /api/meta 계열·옛 경로 404
from __future__ import annotations

import importlib
from pathlib import Path

import httpx

from app import config
from app.adapters import registry as adapters_registry
from app.config import settings
from app.mcp_server import mcp


def test_health_exact_three_keys(client, monkeypatch):
    """정상 상태의 health 는 3키 고정이다(plan §5.2.5 (6))."""
    from app import main

    monkeypatch.setattr(main, "health_warnings", lambda: [])
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "app_version": settings.app_version, "schema_version": 1}


def test_health_reports_backup_unencrypted_without_an_age_key(client, monkeypatch):
    """age 공개키가 없으면 백업 사본이 평문으로 나간다 — health warnings 로 드러낸다(plan §5.2.5 (3a) ③)."""
    from app import main

    monkeypatch.setattr(config, "backup_key", lambda *a, **k: "")
    assert main.health_warnings() == ["backup_unencrypted"]
    assert client.get("/api/health").json()["warnings"] == ["backup_unencrypted"]

    monkeypatch.setattr(config, "backup_key", lambda *a, **k: "age1examplerecipient")
    assert main.health_warnings() == []
    assert "warnings" not in client.get("/api/health").json()


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


def _tools_map_client(payload, status_code=200):
    """게이트웨이 `/tools-map` 을 흉내 낸다 — 시험은 실제 게이트웨이를 때리지 않는다."""
    def handler(request):
        assert request.url.path.endswith("/tools-map")
        return httpx.Response(status_code, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _full_map():
    """mcad·dyna 가 요구하는 도구를 다 갖춘 지도(ecad 4종은 일부러 뺀다)."""
    from app.adapters import dyna as dyna_adapter
    from app.adapters import mcad

    out = {name: "heax-step_forge" for name in mcad.REQUIRED_TOOLS}
    out.update({name: "heax-kooremapper_mcp" for name in dyna_adapter.REQUIRED_TOOLS})
    return {"map": out}


def test_meta_adapters_reports_what_the_gateway_actually_has(client):
    """plan §8.2.3 응답 모양 + 게이트웨이 실측 — 도구가 다 보이면 `ready`·`tools_ok` 다."""
    adapters_registry.reset_discovery_cache()
    http = _tools_map_client(_full_map())
    try:
        rows = {r["kind"]: r for r in adapters_registry.discover_adapters(client=http, force=True)}
    finally:
        http.close()

    assert rows["mcad"]["status"] == "ready" and rows["mcad"]["tools_ok"] is True
    assert rows["mcad"]["app_key"] == "heax-step_forge"
    assert rows["dyna"]["status"] == "ready" and rows["dyna"]["tools_ok"] is True
    # ecad 는 도구가 다 보여도 계약만 있는 스텁이다(§2.5.3) — 붙는 것은 P7.
    assert rows["ecad"]["status"] == "contract_only" and rows["ecad"]["tools_ok"] is False
    assert set(rows["mcad"]) == {"kind", "app_key", "status", "tools_ok", "tools_missing",
                                 "gateway_error", "warnings", "choices"}


def test_meta_adapters_falls_back_when_the_gateway_cannot_be_read(client):
    """'도구가 없다' 와 '못 물어봤다' 를 섞지 않는다 — 못 읽으면 planned 로 남고 사유가 실린다."""
    adapters_registry.reset_discovery_cache()
    http = _tools_map_client({}, status_code=503)
    try:
        rows = {r["kind"]: r for r in adapters_registry.discover_adapters(client=http, force=True)}
    finally:
        http.close()
        adapters_registry.reset_discovery_cache()

    assert rows["mcad"]["status"] == "planned" and rows["mcad"]["tools_ok"] is False
    assert rows["mcad"]["gateway_error"] == "http_503"
    # 폴백에서도 app_key 는 고정 목록 값을 유지한다 — 화면이 빈칸을 보이지 않게.
    assert rows["mcad"]["app_key"] == "heax-step_forge"


def test_meta_adapters_route_shape(client):
    """라우트 자체의 봉투 — `{apps:[…]}`(클라이언트 `AdapterList` 와 같은 모양)."""
    # 캐시를 먼저 채워 라우트가 게이트웨이를 때리지 않게 한다(시험에 외부 HTTP 실호출은 없다).
    http = _tools_map_client(_full_map())
    try:
        adapters_registry.discover_adapters(client=http, force=True)
    finally:
        http.close()

    body = client.get("/api/meta/adapters").json()

    assert list(body) == ["apps"]
    assert [a["kind"] for a in body["apps"]] == ["mcad", "dyna", "ecad"]
    assert body["apps"][0]["tools_ok"] is True


def test_meta_vocab_lists_runtime_assets(client):
    r = client.get("/api/meta/vocab")
    assert r.status_code == 200
    text = str(r.json())
    for name in ("character-vocab", "seat-contract", "rules-seed", "adjacency", "character-seed-rules"):
        assert name in text, f"{name} 가 /meta/vocab 응답에 없다"
    assert "1.0" in text or "version" in text.lower()


def test_meta_vocab_carries_the_promotable_axes(client):
    """자유 태그 승격 화면의 축 선택지는 서버가 준다 — 통제 어휘를 화면이 따로 갖지 않게(§7.7)."""
    axes = client.get("/api/meta/vocab").json()["promotable_axes"]

    assert axes == sorted(axes) and "char:structure" in axes and "char:constraint" in axes
    # 값 목록이 없는 축은 선택지에 없다 — 서버 가드(axis_not_promotable)와 같은 판정이다.
    assert "char:interface" not in axes
