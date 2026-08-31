<!-- HWAXRisk 앱 리포의 P0 앱 슬라이스 체크리스트 — 포털 정본 checklist.md(P0 전체)에서 앱 몫만 떼어 왔다 -->
# HWAXRisk 체크리스트

정본은 `HWAXPortal/docs/design-risk-review/{plan.md, checklist.md}`. 이 문서는 **앱 리포에 속한 P0 항목**만 다룬다.
엔진 additive(deliberation.py·hwax-deliberate.js)·포털 메뉴·HEAXHub 등록·RA/AIDataHub 부트스트랩은 포털 정본 체크리스트의 몫이다.

## 1단계 — 준비 (이번 세션)
- [x] 이름·경로 정본 확정(context-notes D2·D6) — 리포 `HWAXRisk` · id `hwax_risk` · Caddy `/apps/hwax_risk` · MCP `heax-hwax_risk` · REST `/api`
- [x] ThermalShockMCP 골격 조사(pyproject·.gitignore·manifest v2·main.py 마운트 방식·config HEAX_DATA_DIR 폴백)
- [x] HEAXHub `schemas/manifest.schema.v2.json`·`manifest_validator.py` 조사(루트 `mcp` 키는 스키마 밖 — context-notes D4 메모)
- [x] backend/pyproject.toml / .gitignore / .portal/manifest.yaml / .mcp.json
- [x] README.md / checklist.md / context-notes.md / docs/plan.md / docs/odb-adapter-contract.md
- [ ] git 첫 커밋(리포에 커밋 0건 — P0 정합까지 합쳐 사용자가 결정)

## 2단계 — 앱 골격 (병렬 빌더, 경로는 D5 전환 후 `backend/app/`)
- [x] `app/config.py` — Settings(plan §8.2.6 전 필드, env `HWAXRISK_<대문자>`), 우선순위 `HWAXRISK_DATA_DIR > HEAX_DATA_DIR > <리포>/data`, 쓰기 불가면 기동 중단, DB 파일 `risk_review.db`, `secrets.env` 로드
- [x] `app/risk_store.py` — RiskStore(sqlite3+Lock, WAL), `PRAGMA user_version` 정본 + `_schema_migrations` 이력 + v1 = plan §5.2.2 DDL 전문(rr_* 33표+인덱스) + 살림 표 `_user_credentials`, pre-migrate 사본, 상위 버전 기동 실패
- [x] `app/narrative.py` — `parse_risk_spec`(펜스 → 균형 중괄호 → schema 검사 → 실패 None) · `validate_risk_spec`(jsonschema)
- [x] `app/taxonomy.py` — `load_taxonomy()`·`load_json(name)`·버전, 자산은 `backend/app/assets/`
- [x] `app/identity.py` — `current(request) -> Identity`(Bearer > 쿠키 `heax_access_token` → heax `/api/v1/auth/me`, sha256 TTL 60 s 캐시, `X-Heax-User-*` 미사용)
- [x] `app/routes.py` — `/api/me` · `PUT /api/me/portal-pat` · `/api/meta/taxonomy` · `/meta/adapters` · `/meta/vocab`, `Depends(identity.current)`
- [x] `app/mcp_server.py` — FastMCP `hwax-risk` 도구 6종 시그니처(§0.5.2), 본문 `not_implemented` + `ready_in`
- [x] `app/main.py` — `/api/health {ok, app_version, schema_version}` · api 라우터 · MCP `Route('/mcp')` 이식 · `/` StaticFiles(frontend/dist, 없으면 플레이스홀더) · lifespan ①~⑦(§8.2.10)
- [x] `app/runner.py` — 스레드 3개 골격(start/stop/status) · `app/adapters/{base,registry}.py` v0
- [x] `app/cli.py` — `hwax-risk --port`
- [x] `app/schemas/{rr_ir, rr_state, rr_diff, risk_spec, seat_opinion}.v1.json`
- [x] `app/assets/{taxonomy, character-vocab, character-seed-rules, adjacency, rules-seed, seat-contract}.v1.json`(package-data)

## 3단계 — 테스트
- [x] `tests/conftest.py`(HWAXRISK_DATA_DIR=임시 디렉터리 · lifespan TestClient)
- [x] `test_boot.py`(기동 3점 + dist 분기 + 옛 경로 404) · `test_config_datadir.py`(우선순위·폴백·생성·쓰기 불가·Settings 기본값·secrets) · `test_store.py`(user_version 1·33+2표·멱등·pre-migrate 사본·상위 버전 예외)
- [x] `test_parser.py`(합성 6 + 픽스처 .md 6 parametrize) · `test_schemas.py`(5 스키마 × 유효/무효 ≥2)
- [x] `test_mcp_tools.py`(6종 이름 고정·not_implemented·exact `/mcp` Route·307 아님·HTTP JSON-RPC tools/list 6종) · `test_manifest.py`(v2 스키마 허용 오류 2건·§8.2.2 값) · `test_runner.py`
- [x] `test_identity.py`(Bearer/쿠키/위조 헤더/익명/10회 1호출, MockTransport) · `test_me.py`(익명·인증·401·422 4종·등록 1행·null 삭제 0행) · `test_parity.py`(조건부 skip)
- [x] `pip install -e ".[test]"` + 전체 pytest green(dist 유무 양쪽)

## 4단계 — 통합 검증
- [x] `hwax-risk --port 8000` 기동 → `/api/health` 200 · `POST /mcp` initialize 200 · `/` index.html
- [x] `HWAXRISK_DATA_DIR` 격리 환경에서 DB 생성·재기동 멱등 확인
- 실측 — `ROOT_PATH=/apps/hwax_risk` 로 기동해 `/api/health` 200 · `/mcp` initialize 200 · `/` index.html 확인(2026-08-31).

## 5단계 — fastapi_react 레이아웃 전환 (context-notes D5)
- [x] `app/`·`tests/`·`pyproject.toml` → `backend/` 이동, `.venv` 는 `backend/.venv` 로 재생성
- [x] `frontend/`(HEAXHub `templates/fastapi-react/frontend` 본뜸) — `hwax-risk-frontend`, `pnpm install`(lock 커밋) + `pnpm build` → `frontend/dist`
- [x] `main.py` 등록 순서 `/api/health` → `/api` 라우터 → MCP `Route('/mcp')` 이식 → `StaticFiles('/')`(dist 있을 때만)
- [x] `config.py` `BASE_DIR`=리포 루트·`risk_review.db`
- [x] 매니페스트 `stack fastapi_react`·`launch.env PYTHONNOUSERSITE`·`health /api/health`, `backend/scripts/heaxhub-build.sh`
- [x] 테스트 추가 — `/api/health`·옛 `/health`·옛 prefix 404·`/` dist 분기·exact `/mcp` Route(307 아님) — 70 passed(dist 있음/없음)
- 실측 — `ROOT_PATH=/apps/hwax_risk` 기동 → `/api/health` 200 · `/` dist index.html · `assets/*.js` 200 · `POST /mcp` 200(리다이렉트 없음) · `risk_review.db` 생성(2026-08-31).

## 6단계 — P0 정합 (plan §9.1 A-δ, context-notes D6)
- [x] env 접두 `HWAXRISK_` 복원(코드·테스트·문서·매니페스트) · Settings §8.2.6 전 필드 · `secrets.env` 로드
- [x] `risk_store.py` v1 = §5.2.2 DDL 전문 + `_schema_migrations`·`_user_credentials` · pre-migrate 사본 · 상위 버전 기동 실패
- [x] `main.py` lifespan ①~⑦ — `origin.json` · `secrets_valid`(box_match AND 3키) · identity 캐시 · MCP session_manager · 러너
- [x] `mcp_server.py` 6종 시그니처(옛 `risk_health·risk_get_taxonomy·risk_get_meta` 제거) · DNS-rebinding 보호 off
- [x] 자산 `docs/*.v1.json` → `backend/app/assets/`(git mv, package-data) · `httpx` 런타임 의존 · `adapters/` v0 · `runner.py` 골격
- [x] 매니페스트 — `company` · `memory_gb 2` · `launch.env {PYTHONNOUSERSITE}` 만(`HWAXRISK_DATA_DIR` 미기재, 이유 D6) · `allowed_groups []` · description §8.2.2 문구
- [x] `identity.py` 재작성(`current`, 되묻기+캐시+`reset_cache`) · `api.py`→`routes.py`(git mv) · `GET /me` · `PUT /me/portal-pat`(422 4종·UPSERT·null 삭제·익명 401) · `/api/meta` 제거
- [x] 테스트 — `test_health`→`test_boot` · `test_parse_risk_spec`→`test_parser` · `test_identity` 재작성 · `test_me`·`test_parity` 신설 · `test_store` 33+2 · `test_manifest` A-δ 값
- [x] 문서 — README·checklist·context-notes·docs/plan.md·`static/index.html`·`frontend/src/{api.ts,App.tsx}` 표기(6종·`/api/health` 3키·`/api/me`·`_schema_migrations`·`HWAXRISK_`)
- 실측(2026-08-31) — pytest **103 passed, 2 skipped**(`test_parity` — `HWAX_PORTAL_REPO` 미설정) · `pnpm build` 성공 · TestClient `GET /api/health {ok:true, app_version:'0.1.0', schema_version:1}` · `POST /mcp` initialize 200 + `mcp-session-id` · HTTP JSON-RPC `tools/list` 6종(세션 헤더 재사용, `test_mcp_tools`) · `GET /` text/html · 데이터 루트에 `origin.json`+`risk_review.db` 생성 · 러너 3스레드 alive.
- [x] 리뷰 반영 — HTTP `tools/list` 경로 실증 테스트 추가(통과 기준 13) · PAT 검증 포털 불통 422→503 `pat_verify_unavailable` 제안을 context-notes D6 에 기록(코드는 §8.2.3 수정 뒤)
- [ ] 정본 불일치 결정 대기 — §5.2.2 DDL 전문은 rr_ 표 33개(`rr_delta_contrib` 포함), plan 요약 문구는 32표(D6)
- [ ] 정본 §8.2.8 결정 대기 — heax 불통 시 앱 503 vs anonymous(코드·브리프는 anonymous, D6 'identity 불통 처리'); 포털 plan 문구 수정 또는 코드 503 승격 중 택일

## 보류 (이번 P0 앱 슬라이스 밖 — context-notes D4·D6)
- [ ] GitHub `squall321/HWAXRisk` 생성·push
- [ ] HEAXHub `integrations/hwax-risk/.portal/manifest.yaml` 복사본 커밋 → 스캔·SIF 빌드·기동·게이트웨이 흡수 확인(plan §9.1 통과 기준 13~16)
- [ ] 엔진 additive(`_CHAIR_ITEMS['risk-review']` 등)·`HWAXPortal/scripts/check_chair_parity.py`·포털 메뉴 창(`systems.yaml` 타일·`/risk`·`RiskLaunchPage`) — 되면 `test_parity.py` 가 skip 에서 실검사로 바뀐다
- [ ] `backend/scripts/{bootstrap_ra_ontology,bootstrap_adh}.py` · `export.py` 자리 · `adapters/registry.py` `/tools-map` 발견 로직(P1)
- [ ] risk_spec 정규화 10단계(P3)·어댑터 실구현(P1~)·러너 본문(P3~)·MCP 도구 본문(P1~P5)
