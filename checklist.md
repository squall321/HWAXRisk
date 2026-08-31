<!-- HWAXRisk 앱 리포의 P0 앱 슬라이스 체크리스트 — 포털 정본 checklist.md(P0 전체)에서 앱 몫만 떼어 왔다 -->
# HWAXRisk 체크리스트

정본은 `HWAXPortal/docs/design-risk-review/{plan.md, checklist.md}`. 이 문서는 **앱 리포에 속한 P0 항목**만 다룬다.
엔진 additive(deliberation.py·hwax-deliberate.js)·포털 메뉴·HEAXHub 등록·RA/AIDataHub 부트스트랩은 포털 정본 체크리스트의 몫이다.

## 1단계 — 준비 (이번 세션)
- [x] 이름·경로 정본 확정(context-notes D2·D5) — 리포 `HWAXRisk` · id `hwax_risk` · Caddy `/apps/hwax_risk` · MCP `heax-hwax_risk` · REST `/api`(D5 에서 `/api/v1` → `/api`)
- [x] ThermalShockMCP 골격 조사(pyproject·.gitignore·manifest v2·main.py 마운트 방식·config HEAX_DATA_DIR 폴백)
- [x] HEAXHub `schemas/manifest.schema.v2.json`·`manifest_validator.py` 조사(루트 `mcp` 키는 스키마 밖 — context-notes D4 메모)
- [x] backend/pyproject.toml / .gitignore / .portal/manifest.yaml / .mcp.json
- [x] README.md / checklist.md / context-notes.md / docs/plan.md / docs/odb-adapter-contract.md
- [ ] git 첫 커밋(빌더 4 산출 합류 후 — 리포에 커밋 0건)

## 2단계 — 앱 골격 (병렬 빌더, 이번 워크플로. 경로는 D5 전환 후 `backend/app/`)
- [x] `app/config.py` — settings(DATA_DIR·DB_PATH·ROOT_PATH·HOST/PORT·APP_ID·APP_VERSION), 우선순위 `HWAX_RISK_DATA_DIR > HEAX_DATA_DIR > <리포>/data`, 쓰기 불가면 기동 중단. DB 파일 `risk_review.db`(계획 §5.2.5 — `.db` 가 원자 백업 조건)
- [x] `app/risk_store.py` — RiskStore(sqlite3+Lock), `PRAGMA user_version` 정본 + `schema_migrations` 이력 + v1 표 4종(rr_projects·rr_sources·rr_snapshots·rr_snapshot_calls, plan §5.2.2 DDL 그대로), `schema_version()`·`health()`
- [x] `app/narrative.py` — `parse_risk_spec`(펜스 → 균형 중괄호 → schema 검사 → 실패 None) · `validate_risk_spec`(jsonschema)
- [x] `app/taxonomy.py` — `load_taxonomy()`·`load_json(name)`·버전
- [x] `app/identity.py` — `resolve_identity(request)`(X-Heax-User-Email 을 `header_unverified` 로만 표기, 없으면 anonymous — 정본은 P1 `/auth/me` 되묻기)
- [x] `app/api.py` — `/api/meta` · `/meta/taxonomy` · `/meta/adapters` · `/meta/vocab`
- [x] `app/mcp_server.py` — FastMCP `hwax-risk` 도구 3종 `risk_health · risk_get_taxonomy · risk_get_meta`
- [x] `app/main.py` — `/api/health` · api 라우터 · MCP `Route('/mcp')` 이식 · `/` StaticFiles(frontend/dist, 없으면 플레이스홀더) · lifespan(store.open+migrate, mcp.session_manager.run)
- [x] `app/cli.py` — `hwax-risk --port`
- [x] `app/schemas/{rr_ir, rr_state, rr_diff, risk_spec, seat_opinion}.v1.json`
- [x] `docs/{taxonomy, character-vocab, character-seed-rules, adjacency, rules-seed, seat-contract}.v1.json`

## 3단계 — 테스트
- [x] `tests/conftest.py`(HWAX_RISK_DATA_DIR=tmp_path · TestClient)
- [x] `test_health.py` · `test_config_datadir.py`(3단계 우선순위·폴백·생성·쓰기 불가) · `test_store.py`(멱등·version=1·4표)
- [x] `test_parse_risk_spec.py`(합성 6 + 픽스처 .md 6 parametrize) · `test_schemas.py`(5 스키마 × 유효/무효 ≥2)
- [x] `test_mcp_tools.py`(도구 3종 + exact `/mcp` Route·307 아님) · `test_manifest.py`(manifest.schema 검증, 파일 없으면 skip) · `test_identity.py`
- [x] `pip install -e ".[test]"` + 전체 pytest green(dist 유무 양쪽)

## 4단계 — 통합 검증
- [x] `hwax-risk --port 8000` 기동 → `/api/health` 200 · `/api/meta` 200 · `POST /mcp` initialize 200 · `/` index.html
- [x] `HWAX_RISK_DATA_DIR` 격리 환경에서 DB 생성·재기동 멱등 확인
- 실측 — `ROOT_PATH=/apps/hwax_risk` 로 기동해 `/health` 200 · `/mcp` initialize 200 · `/` index.html 확인(2026-08-31).

## 5단계 — fastapi_react 레이아웃 전환 (context-notes D5)
- [x] `app/`·`tests/`·`pyproject.toml` → `backend/` 이동, `.venv` 는 `backend/.venv` 로 재생성
- [x] `frontend/`(HEAXHub `templates/fastapi-react/frontend` 본뜸) — `hwax-risk-frontend`, `pnpm install`(lock 커밋) + `pnpm build` → `frontend/dist`
- [x] `main.py` 등록 순서 `/api/health` → `/api` 라우터 → MCP `Route('/mcp')` 이식 → `StaticFiles('/')`(dist 있을 때만)
- [x] `config.py` env `HWAX_RISK_DATA_DIR`·`BASE_DIR`=리포 루트·`risk_review.db`
- [x] 매니페스트 `stack fastapi_react`·`launch.env PYTHONNOUSERSITE`·`health /api/health`, `backend/scripts/heaxhub-build.sh`
- [x] 테스트 추가 — `/api/health`·옛 `/health`·`/api/v1` 404·`/` dist 분기·exact `/mcp` Route(307 아님) — 70 passed(dist 있음/없음)
- 실측 — `ROOT_PATH=/apps/hwax_risk` 기동 → `/api/health` 200 · `/` dist index.html · `assets/*.js` 200 · `POST /mcp` 200(리다이렉트 없음) · `/health`·`/api/v1/meta` 404 · `risk_review.db` 생성(2026-08-31).

## 보류 (이번 P0 앱 슬라이스 밖 — context-notes D4)
- [ ] GitHub `squall321/HWAXRisk` 생성·push
- [ ] HEAXHub `integrations/hwax-risk/.portal/manifest.yaml` 복사본 커밋 → 스캔·SIF 빌드·기동·게이트웨이 흡수 확인
- [ ] 엔진 additive(`_CHAIR_ITEMS['risk-review']` 등)·`check_chair_parity.py`·포털 메뉴 창(`systems.yaml` 타일·`/risk`·`RiskLaunchPage`)
- [ ] risk_spec 정규화 10단계(P3)·어댑터 실구현(P1~)·러너(P3~)
- [ ] P1 — `owner_sub` 원천을 heax `GET /api/v1/auth/me` 되묻기로(헤더는 원천 아님) · 런타임 자산 `docs/*.v1.json` 을 `backend/app/assets/` 로 옮기고 package-data 에 추가(비-editable 설치 대비)
