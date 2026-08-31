<!-- HWAXRisk 앱 리포의 결정 기록 — 포털 정본 context-notes(D0~D5)의 후속으로, 앱 리포 착수 시점의 결정 D1~D5 를 근거와 함께 남긴다 -->
# HWAXRisk 컨텍스트 노트

착수 2026-08-31. 계획 정본은 `HWAXPortal/docs/design-risk-review/plan.md`(§0 spine·§2 IR·§3 state/diff·§4 서술·§5.2 DDL·§6 워크플로·§7 택소노미·§8 통합·§9 단계).
포털 정본 `context-notes.md` 의 D0~D5(계획 도출·합성 사고·검토·토폴로지 B·이름 관례)는 여기서 반복하지 않는다.
이 문서는 **앱 리포**에서 내린 결정과 그 이유만 시간순으로 적는다.

## 2026-08-31 (앱 리포 착수)

### D1. 토폴로지 B — 자산은 HEAX 앱, 포털은 창
- **결정.** 리스크 심사의 누적 자산(IR 스냅샷·diff·의견 원자·등록부·성격 프로파일·커버리지 원장·학습 산출)은 전부 이 앱이
  소유한다 — 전용 sqlite + REST + MCP + UI + 러너를 한 프로세스에 두고, 포털은 '심의'와 별개의 메뉴 창 하나
  (`systems.yaml` 타일 `hwax-risk` → `/launch/hwax-risk` → `/apps/hwax_risk/` 새 탭)만 둔다.
- **근거.** 이 자산은 과제 수십 개·수년치가 쌓이는 장기 자산이라 포털 릴리스·박스 수명에 묶이면 안 된다.
  ThermalShockMCP 선례처럼 데이터를 품은 HEAX 앱으로 두면 `HEAX_DATA_DIR` 영구 경로 + `appdata-to-drive.sh` 백업 +
  매니페스트 `mcp:{expose}` 로 게이트웨이 자동 흡수(설정·코드 변경 0)를 그대로 얻는다. 포털 SPA 는 heax bearer 를
  갖지 않아(jwt-handoff 는 localStorage bearer) 앱 REST 를 직접 fetch 할 수 없으므로 '창' 방식이 자연스럽다.
- **불변.** rr_* 스키마·원자·해시 규약·prior_evidence E0~E9·커버리지 상태기계·학습 루프·엔진 additive 항목은 A 계획 그대로.
  바뀌는 것은 위치(포털 sqlite → 앱 DB)·호출 경로·인증·P0 산출물이다(plan §0.7 #12).
- **골격 차이(plan 과 이 리포).** plan §8.2.1 은 `fastapi_react` 스택(`backend/`+`frontend/`) 을 적지만, 이 P0 슬라이스는
  ThermalShockMCP 와 같은 **루트 `app/` 패키지 + `fastapi` 스택**으로 시작한다(빌더 계약이 그렇게 고정됐고 P0 에는
  React SPA 가 없다 — `/` 는 `app/static/index.html` 플레이스홀더). `frontend/` 분리와 스택 전환은 SPA 가 생기는 P1
  이후의 결정이며, 그때 `backend/` 이동 여부를 다시 적는다. → **같은 날 D5 에서 `fastapi_react` 로 전환했다.**

### D2. 이름·경로 관례
- **결정.** 리포 `/home/koopark/claude/HWAXRisk`(GitHub `squall321/HWAXRisk`) · 매니페스트 `id: hwax_risk` · 표시명
  `HWAX Risk Review` · HEAXHub 등록 디렉터리 `integrations/hwax-risk/`(매니페스트 복사본만) · Caddy base
  `/apps/hwax_risk` · MCP `/apps/hwax_risk/mcp` → 게이트웨이 백엔드 `heax-hwax_risk` · REST base `/apps/hwax_risk/api`
  (앱 내부 `/api`, D5 에서 `/api/v1` → `/api`) · Python 패키지명 `hwax-risk` · 모듈 `app` · 콘솔 스크립트 `hwax-risk = app.cli:main` · MCP 서버명
  `hwax-risk` · 도구 접두 `risk_`.
- **근거.** 다른 앱 리포와 동일한 관례다 — 리포는 `~/claude/<PascalCase>`(HWAX 계열은 HWAX 접두: HWAXPortal·
  HWAXAgentServer·HWAXMcpGateway), HEAXHub 등록은 `integrations/<kebab>/`, 매니페스트 id 는 snake_case(스키마 패턴
  `^[a-z][a-z0-9_]{2,63}$`), 게이트웨이 백엔드 키는 `heax-<id>`. plan.md 본문은 개정 중이라 `HwaxRisk`·`risk_review.db`·
  `/api` 표기가 섞여 있는데, **경로·이름은 이 노트가 정본이고 스키마·필드·상수는 plan.md 가 정본**이다.
- **REST prefix.** 처음엔 빌더 계약대로 `/api/v1`·헬스 `/health` 였으나 D5 에서 plan §0.5.1 의 `/api`·`/api/health` 로 맞췄다
  (`fastapi_react` 스택 `health_path` 가 `/api/health`).

### D3. 데이터 경로
- **D5 로 대체됨 — 현재 정본은 env `HWAX_RISK_DATA_DIR` · 파일 `risk_review.db`.** 아래 `HWAXRISK_DATA_DIR`·`hwax_risk.db`
  문장은 P0 초기 결정의 이력이며 코드·매니페스트·테스트에는 남아 있지 않다.
- **결정(D5 에서 폐기).** 데이터 루트 우선순위 `HWAXRISK_DATA_DIR` > `HEAX_DATA_DIR` > `<리포>/data`. DB 파일은 `<data>/hwax_risk.db`
  하나(→ D5 에서 env `HWAX_RISK_DATA_DIR`·파일 `risk_review.db` 로 계획 정본에 맞췄다). 루트는 첫 기동 시 생성하고 `os.access(W_OK)` 실패면 기동을 중단한다(조용한 폴백 금지, plan §5.2.5 (1)).
  `.gitignore` 에 `data/*.db*`(wal·shm 포함)·`var/` 를 넣는다.
- **근거.** ThermalShockMCP `config.py` 의 폴백 규칙 복제 — SIF 배포는 rootfs 가 read-only 라 HEAX 가 bind 하는
  `HEAX_DATA_DIR`(`/data`, 호스트 `HEAXHub/var/app_data/hwax_risk/`) 아래에 써야 재빌드 후에도 영속된다. 앱 전용
  변수(`HWAXRISK_DATA_DIR`)를 최우선에 두는 이유는 테스트·격리 실행(`tmp_path`)과 호스트 프로세스 실행에서 HEAX
  경로를 덮기 위해서다. env 이름은 빌더 계약의 `HWAXRISK_` 접두를 따른다(plan §0.5.3 의 `HWAX_RISK_` 와 다름 —
  다른 설정 키가 생기는 P1 에서 접두를 하나로 맞춘다).
- **DB 파일명.** plan 은 `risk_review.db` 이지만 이 리포는 `hwax_risk.db` 로 확정(앱 id 와 동일). 처음엔 `hwax_risk.sqlite`
  였으나 리뷰에서 바꿨다 — HEAXHub `appdata-to-drive.sh` 는 `**/*.db` 만 `sqlite3 .backup` 원자 스냅샷으로 교체하고
  `-wal/-shm` 을 제외하므로, WAL 을 켠 `.sqlite` 는 원본 파일이 그대로 tar 에 들어가 체크포인트 전 내용이 빠진다
  (plan §5.2.5 (3) 이 `.db` 를 고정한 이유). 스키마 버전 정본은 plan §5.2.5 (6) 대로 `PRAGMA user_version` 이고
  `schema_migrations(version, applied_at)` 은 이력표다(`schema_version()` 은 user_version 을 읽는다).
- **소유권.** `owner_sub` 의 원천은 heax `GET /api/v1/auth/me` 되묻기이며 쓰기 API 가 생기는 P1 에서 넣는다.
  `X-Heax-User-Email` 은 원천이 아니다 — service 모드 앱의 Caddy 라우트(HEAXHub `proxy_manager._build_route`)는
  forward_auth 에 `copy_identity` 가 없어 헤더가 운영에서 도착하지 않고(복사는 proxy 모드 `launch.portal_auth` 전용),
  클라이언트가 보낸 같은 이름의 헤더는 제거되지 않고 통과한다. P0 `identity.py` 는 이 값을 `source='header_unverified'`
  로만 표기하고 신뢰하지 않는다.

### D4. P0 범위와 보류
- **이번 슬라이스에 넣은 것.** 패키징(pyproject·.gitignore)·매니페스트 v2·README·checklist·context-notes·docs/plan.md
  포인터·odb-adapter-contract.md, 그리고 병렬 빌더의 `app/`(config·risk_store 4표·narrative parse/validate·taxonomy·
  identity·api meta 4종·mcp 도구 3종·main·cli·schemas 5종·static 플레이스홀더)·`docs/*.v1.json` 6종·`tests/` 9종.
- **보류(이유와 함께).**
  - GitHub `squall321/HWAXRisk` 생성·push — 매니페스트 `source.url` 은 적어 두되 리포가 없으면 HEAXHub 스캔이 fetch
    실패 메일을 반복하므로(plan §0.4.1) 등록 전에 만든다.
  - HEAXHub `integrations/hwax-risk/` 복사본 — 위와 같은 이유로 GitHub 생성 뒤. 이 세션은 다른 리포를 수정하지 않는다.
  - 엔진 additive(`_CHAIR_ITEMS['risk-review']`·반대석·좌석 계약·`_RISK_READ_TOOLS`·`_RISK_KEEP_TOOLS`)와
    `check_chair_parity.py` — agent-server·포털 리포의 몫(포털 정본 checklist P0).
  - 포털 메뉴 창(`systems.yaml` 타일·`/risk`·`RiskLaunchPage`) — 앱이 뜬 뒤에 연다.
  - risk_spec 정규화 10단계(plan §4.2.2) — P3. P0 파서는 펜스/중괄호 추출 + `schema=='risk_spec'` 검사 + jsonschema
    검증까지.
  - MCP 도구 6종(`risk_get_snapshot`… `risk_submit_panel_result`) — P1~P5. P0 는 읽기 전용 3종만.
- **매니페스트 검증 메모(실측).** `manifest.schema.v2.json` 은 루트와 `source` 가 `additionalProperties: false` 이고 루트 `mcp`
  키와 `source.ref` 키가 없다. 이 리포 매니페스트를 v2 스키마로 엄격 검증하면 정확히 2건이 난다 — `<root>: 'mcp' was
  unexpected` · `source: 'ref' was unexpected`. 등록 사본 `thermal-shock-mcp` 매니페스트도 같은 2건이 난다. 그래도 두 키를
  두는 이유는 게이트웨이 자동탐지가 `mcp:{}` 를 읽고, 스캐너가 `source.ref` 를 읽어(`integrations_scanner.py:109`, 기본 `main`)
  체크아웃하며, HEAXHub 스캐너가 `validate_manifest` 를 호출하지 않기 때문이다(plan §8.2.2). 따라서 `tests/test_manifest.py`
  는 검증 전에 `mcp` 와 `source.ref` 를 빼고 돌리거나 그 2건만 허용해야 한다. `build.stack` 은 `build` 가
  `additionalProperties: true` 라 통과한다. v1 스키마(`manifest.schema.json`)는 `schema_version const 1` 이라 v2 매니페스트에 쓸 수 없다.
- **매니페스트 값이 plan §8.2.2 와 다른 곳.** `health_check.path /health`(plan `/api/health`) · `build.stack fastapi`
  (plan `fastapi_react`) · `visibility team`(plan `company`) · `memory_gb 1`(plan 2) · `launch.env` 없음. 전부 P0 골격
  (React 없음·환경 단순)에 맞춘 빌더 계약값이고, plan 이 `company` 를 고른 이유(포털 SSO 사용자의 `organization=''` 가
  `team` 가시성에서 걸릴 수 있음)는 HEAXHub 등록 시점에 다시 판단한다.

### D5. 레이아웃을 `fastapi_react` 로 전환 (같은 날, P0 슬라이스 마무리)
- **결정.** 루트 `app/`+`fastapi` 스택(D1 골격) 대신 계획 §0.4.1·§8.2.1 의 **`fastapi_react` 스택**으로 전환한다 —
  `backend/{pyproject.toml, app/, tests/, scripts/heaxhub-build.sh, .venv/}` + `frontend/`(Vite+React TS, HEAXHub
  `templates/fastapi-react/frontend` 본뜸, `hwax-risk-frontend`). `main.py` 등록 순서는 `/api/health` → `/api` 라우터 →
  MCP `Route('/mcp')` 이식 → `StaticFiles('/', frontend/dist, html=True)`(dist 가 있을 때만, 없으면 `GET /` 가
  `backend/app/static/index.html` 플레이스홀더). 함께 계획 정본으로 되돌린 값 — REST prefix `/api`(`/api/v1` 제거), 헬스
  `/api/health`(`/health` 제거), env `HWAX_RISK_DATA_DIR`(`HWAXRISK_DATA_DIR` 제거), DB 파일 `risk_review.db`(§5.2.5),
  매니페스트 `build.stack fastapi_react`·`launch.env PYTHONNOUSERSITE=1`·`health_check.path /api/health`.
- **근거.**
  - 계획 §0.4.1·§8.2.1 이 `fastapi_react` 를 적고 있고, 이 앱은 UI 를 **동봉**해야 한다(B 토폴로지 — 포털 SPA 는 heax bearer 가
    없어 앱 REST 를 직접 못 부르므로 심사 화면은 앱 자신이 서빙한다). SPA 가 생길 P1 에 뒤집을 바에야 파일이 적은 지금
    전환하는 편이 싸다.
  - MaterialTwinWeb 선례가 같은 스택으로 HEAX 에 등록·기동돼 있다 — `backend/app/main.py` 의 MCP 이식 패턴·`launch.env
    PYTHONNOUSERSITE`·`backend/scripts/heaxhub-build.sh`(빌드 중 호스트 `~/.local` 이 보여 httpx 등이 SIF 에서 빠지는 문제를
    PYTHONNOUSERSITE=1 재설치 + 명시 설치 + import 검증으로 막는다)를 그대로 가져왔다. HEAX 스택 계약(`config/stacks.yaml`)은
    `install: pnpm install --frozen-lockfile && pnpm build && pip install -e ../backend` · `entrypoint: uvicorn app.main:app …
    --root-path $ROOT_PATH`(runscript 가 `/app/backend` 로 cd) · `health_path /api/health` 이므로 `pnpm-lock.yaml` 은 커밋하고
    `frontend/dist` 는 빌드 산출물로 `.gitignore` 한다.
  - `BASE_DIR` 은 `backend/app/` 의 부모의 부모(리포 루트)로 올려야 `<리포>/data` 폴백과 `docs/*.v1.json` 자산 경로가 그대로다.
- **MCP 라우트 이식 근거(실측).** FastMCP `streamable_http_app()` 의 실체는 `Route('/mcp', StreamableHTTPASGIApp)` 하나뿐이라
  그 Route 를 `app.router.routes.append` 로 메인 라우터에 옮기면 exact `/mcp` 로 매칭된다. 대안 둘은 배제 — `app.mount('/mcp', …)`
  는 Starlette Mount 특성상 슬래시 없는 `/mcp` 를 **307** 로 `/mcp/` 에 돌려 MCP 클라이언트·게이트웨이가 못 따라가고(D1 골격에서
  실측), `app.mount('/', mcp_app)`(D1 방식)은 `StaticFiles('/')` 와 공존할 수 없다. `session_manager` 는 인스턴스에 캐시되고
  `run()` 이 1회용이라 `streamable_http_app()` 호출 전에 `mcp._session_manager = None` 으로 리셋한다(MaterialTwinWeb 동일).
  테스트 `test_mcp_route_is_exact_not_mount` 가 `app.routes` 에 `Route(path=='/mcp')` 1개·`Mount('/mcp')` 0개, initialize 200
  (307 아님)을 고정한다.
- **검증.** `backend/.venv` 재생성 후 pytest 70 passed — `frontend/dist` 가 있을 때(StaticFiles index.html)와 없을 때(플레이스홀더)
  모두. `ROOT_PATH=/apps/hwax_risk` 로 uvicorn 기동해 `/api/health` 200 · `/` dist index.html · `assets/*.js` 200 · `POST /mcp`
  initialize 200(리다이렉트 없음) · 옛 `/health`·`/api/v1/meta` 404 · `risk_review.db` 생성 확인(2026-08-31).
- **남은 것.** `identity.py` 는 P0 스탠드인(`header_unverified`) 그대로. HEAXHub 등록 사본·GitHub 생성은 여전히 D4 보류.
