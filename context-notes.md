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
  `^[a-z][a-z0-9_]{2,63}$`), 게이트웨이 백엔드 키는 `heax-<id>`. **이름·경로·계약 정본은 포털 `plan.md`(§10.8 #28)** 이고,
  이 노트는 앱 리포에서 내린 결정의 이유만 남긴다(D6 에서 확정 — 이전에는 이 노트를 경로·이름 정본으로 적었다).
- **REST prefix.** 처음엔 빌더 계약대로 `/api/v1`·헬스 `/health` 였으나 D5 에서 plan §0.5.1 의 `/api`·`/api/health` 로 맞췄다
  (`fastapi_react` 스택 `health_path` 가 `/api/health`).

### D3. 데이터 경로
- **결정(D6 에서 계획 정본 값으로 확정).** 데이터 루트 우선순위 `HWAXRISK_DATA_DIR` > `HEAX_DATA_DIR` > `<리포>/data`. DB 파일은
  `<data>/risk_review.db` 하나. 루트는 첫 기동 시 생성하고 `os.access(W_OK)` 실패면 기동을 중단한다(조용한 폴백 금지, plan §5.2.5 (1)).
  `.gitignore` 에 `data/*.db*`(wal·shm 포함)·`var/` 를 넣는다. env 접두는 처음부터 `HWAXRISK_` 였고 D5 에서 잠시 다른 접두로 바꿨다가
  D6 에서 plan §0.5.3·§8.2.6 의 `HWAXRISK_` 로 되돌렸다(코드·테스트·문서·매니페스트 전부).
- **근거.** ThermalShockMCP `config.py` 의 폴백 규칙 복제 — SIF 배포는 rootfs 가 read-only 라 HEAX 가 bind 하는
  `HEAX_DATA_DIR`(`/data`, 호스트 `HEAXHub/var/app_data/hwax_risk/`) 아래에 써야 재빌드 후에도 영속된다. 앱 전용
  변수(`HWAXRISK_DATA_DIR`)를 최우선에 두는 이유는 테스트·격리 실행(`tmp_path`)과 호스트 프로세스 실행에서 HEAX
  경로를 덮기 위해서다.
- **DB 파일명·확장자.** `risk_review.db`(plan §0.3.1) — 확장자 `.db` 가 HEAXHub `appdata-to-drive.sh` 의 `**/*.db` `sqlite3 .backup`
  원자 스냅샷 조건이다. 스크립트는 `-wal/-shm` 을 제외하므로 다른 확장자를 쓰면 WAL 을 켠 DB 의 원본 파일이 그대로 tar 에 들어가
  체크포인트 전 내용이 빠진다(plan §5.2.5 (3)). 스키마 버전 정본은 plan §5.2.5 (6) 대로 `PRAGMA user_version` 이고
  `_schema_migrations(version, applied_at, app_version)` 은 이력표다(`schema_version()` 은 user_version 을 읽는다).
- **소유권.** `owner_sub` 의 원천은 heax `GET /api/v1/auth/me` 되묻기다(D6 에서 `identity.current` 로 구현).
  `X-Heax-User-Email` 은 원천이 아니다 — service 모드 앱의 Caddy 라우트(HEAXHub `proxy_manager._build_route`)는
  forward_auth 에 `copy_identity` 가 없어 헤더가 운영에서 도착하지 않고(복사는 proxy 모드 `launch.portal_auth` 전용),
  클라이언트가 보낸 같은 이름의 헤더는 제거되지 않고 통과한다. 초기 P0 `identity.py` 는 이 값을 미검증 표기로만 읽었고
  D6 에서 그 경로를 아예 없앴다(어느 경로에서도 읽지 않는다).

### D4. P0 범위와 보류
- **이번 슬라이스에 넣은 것.** 패키징(pyproject·.gitignore)·매니페스트 v2·README·checklist·context-notes·docs/plan.md
  포인터·odb-adapter-contract.md, 그리고 병렬 빌더의 `app/`(config·risk_store 4표·narrative parse/validate·taxonomy·
  identity·api meta 4종·mcp 읽기 도구 3종(→ D6 에서 §0.5.2 6종 시그니처로 교체)·main·cli·schemas 5종·static 플레이스홀더)·`docs/*.v1.json` 6종(→ D6 에서 `backend/app/assets/`)·`tests/` 9종.
- **보류(이유와 함께).**
  - GitHub `squall321/HWAXRisk` 생성·push — 매니페스트 `source.url` 은 적어 두되 리포가 없으면 HEAXHub 스캔이 fetch
    실패 메일을 반복하므로(plan §0.4.1) 등록 전에 만든다.
  - HEAXHub `integrations/hwax-risk/` 복사본 — 위와 같은 이유로 GitHub 생성 뒤. 이 세션은 다른 리포를 수정하지 않는다.
  - 엔진 additive(`_CHAIR_ITEMS['risk-review']`·반대석·좌석 계약·`_RISK_READ_TOOLS`·`_RISK_KEEP_TOOLS`)와
    `check_chair_parity.py` — agent-server·포털 리포의 몫(포털 정본 checklist P0).
  - 포털 메뉴 창(`systems.yaml` 타일·`/risk`·`RiskLaunchPage`) — 앱이 뜬 뒤에 연다.
  - risk_spec 정규화 10단계(plan §4.2.2) — P3. P0 파서는 펜스/중괄호 추출 + `schema=='risk_spec'` 검사 + jsonschema
    검증까지.
  - MCP 도구 6종(`risk_get_snapshot`… `risk_submit_panel_result`) 본문 — P1~P5. (D6 에서 6종 시그니처를 P0 에 등록하고 본문만 `not_implemented` 로 두었다.)
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
  `backend/app/static/index.html` 플레이스홀더). 함께 계획 정본으로 되돌린 값 — REST prefix `/api`(옛 `/api/v1` 제거), 헬스
  `/api/health`(옛 `/health` 제거), DB 파일 `risk_review.db`(§5.2.5), 매니페스트 `build.stack fastapi_react`·
  `launch.env PYTHONNOUSERSITE=1`·`health_check.path /api/health`. (이때 env 접두를 계획과 다른 이름으로 바꾼 것은 D6 에서 `HWAXRISK_` 로 되돌렸다.)
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
- **남은 것.** `identity.py` 는 P0 스탠드인(미검증 헤더 표기) 그대로(→ D6 에서 교체). HEAXHub 등록 사본·GitHub 생성은 여전히 D4 보류.

### D6. P0 정합 — 계획 §9.1 A-δ 즉시 델타를 그대로 적용 (같은 날, 엔지니어 2명 병렬)
- **결정.** 포털 `plan.md` §9.1 A-δ(2026-08-31 실측 대조)의 항목을 전부 적용해 코드·테스트·문서·매니페스트를 계획 정본과 일치시켰다.
  이후 이름·경로·계약의 정본은 포털 `plan.md`(§10.8 #28) 이고 이 노트는 이유만 남긴다(D2 문구 수정).
- **적용 목록(1번 — 저장소·기동·MCP·자산·매니페스트).** env 접두 `HWAXRISK_` 복원 · Settings §8.2.6 전 필드(소문자 속성, `risk_*`) ·
  `secrets.env` 로드(0600 아니면 경고, 값 로그 금지) · `risk_store.py` v1 = §5.2.2 DDL 전문(4표 골격 대체) + 살림 표
  `_schema_migrations(version, applied_at, app_version)`·`_user_credentials` · `pre-migrate-<ts>` 사본 · 상위 `user_version` 기동 실패 ·
  `main.py` lifespan ①~⑦(`origin.json`·`secrets_valid`·identity 캐시·러너) · `mcp_server.py` 6종 시그니처(옛 3종 제거) ·
  `docs/*.v1.json` → `backend/app/assets/`(package-data) · `httpx` 런타임 의존 · `adapters/{base,registry}.py` v0 · `runner.py` 골격 ·
  매니페스트 `company`·`memory_gb 2`·`allowed_groups []`·`description` §8.2.2 문구.
- **적용 목록(2번 — 신원·REST·테스트·문서).** `identity.py` 재작성(`current(request) -> Identity`, Bearer > 쿠키 `heax_access_token`,
  heax `GET /api/v1/auth/me` httpx 2 s, `sha256(token)` TTL 60 s 캐시, `reset_cache()`) · `api.py` → `routes.py`(git mv, `Depends(identity.current)`,
  `GET /me`·`PUT /me/portal-pat` 추가) · `RiskStore` 에 `_user_credentials` get/upsert/delete 3메서드 · 테스트 `test_health`→`test_boot`,
  `test_parse_risk_spec`→`test_parser`, `test_identity`(MockTransport)·`test_me`·`test_parity` 신설 · README·checklist·docs/plan.md·이 노트 ·
  `static/index.html`·`frontend/src/{api.ts,App.tsx}` 표기(도구 6종·`/api/health` 3키·`/api/me`).
- **`/api/meta` 제거.** plan §0.5.1·§8.2.3 경로 목록에 `/meta`(app_id·data_dir·identity) 는 없고 `/meta/taxonomy|adapters|vocab` 만 있다.
  신원은 `/me` 가, 버전·스키마는 `/health` 가 이미 내므로 지웠다(데이터 경로를 응답에 싣는 것도 불필요한 노출이다). 프런트는
  `api/health`+`api/me`+`api/meta/adapters` 로 바꿨고 `test_boot` 가 `/api/meta` 404 를 고정한다.
- **identity 불통 처리.** plan §8.2.8 은 heax `/auth/me` 401 → 앱 401, 5xx·불통 → 503 을 적지만, P0 정합 지시(A-δ 적용 브리프)는
  "401/불통/없음 → anonymous" 다. P0 에는 쓰기 라우트가 `PUT /me/portal-pat` 뿐이고 그것은 익명 401 로 막히므로 anonymous 로 통일했다.
  불통 결과는 캐시하지 않아 heax 가 돌아오면 다음 요청부터 바로 해석된다. 쓰기 라우트가 늘어나는 P1 에서 §8.2.8 대로
  401/503 을 구분할지 다시 결정한다.
- **PAT 검증 순서.** JWT payload 를 서명 검증 없이 디코드(서명 검증은 포털 몫) → `pat_email_mismatch` → `pat_audience`(aud 에
  `mcp-gateway` 없음 또는 scope≠api) → `pat_expiring`(exp−now < 86400) → 포털 `GET /agent/conversations?limit=1`(httpx 3 s) 200 아니면
  `pat_invalid`. 오류 본문은 `errors.AppError` 의 `{error:{code, message}}`. 응답·`/me` 어디에도 PAT 값은 싣지 않는다.
  `box_match` 가 false(이관 직후)면 `_user_credentials` 행이 있어도 `/me.portal_pat` 은 null(plan §5.2.5 (5)).
- **매니페스트 `launch.env` 에 `HWAXRISK_DATA_DIR: /data` 를 넣지 않은 이유.** HEAX 런처가 SIF 에 `HEAX_DATA_DIR=/data` 를 주므로
  폴백만으로 충분하고, dev 런처가 이 앱을 호스트 프로세스로 띄우면 `/data` 가 호스트 `/data` 를 가리켜 오지정된다
  (plan §8.2.6 P0 확인 항목·§9.1 리스크와 완화). `launch.env` 는 `{PYTHONNOUSERSITE: "1"}` 만이며 `test_manifest` 가 이를 고정한다.
- **정본 불일치 발견(사용자 결정 대기).** plan §5.2.2 의 ```sql 블록을 바이트 그대로 옮기면 `rr_` 표는 32 가 아니라 **33** 개다
  (A2·B4·C5·D3·E5·F5·G8·H1 — §4.7.1 에서 추가된 `rr_delta_contrib` 가 '32표' 요약에 반영되지 않은 것으로 보인다). DDL 을 자르지 않고
  그대로 두었고 `test_store` 는 33 을 단언한다. plan §5.2.5 (6)·§9.1 (16)·§0.7 #12 의 '32표' 문구를 33 으로 고칠지 표 하나를 뺄지는 포털 쪽 결정이다.
- **PAT 검증 중 포털 불통(리뷰 지적, 정본 제안).** `_verify_with_portal` 은 브리프('200 아니면 422 pat_invalid') 대로 `httpx.HTTPError`
  (타임아웃·연결 거부 등 포털 불통) 도 422 `pat_invalid` 로 매핑한다. 포털 장애 중에는 유효한 PAT 가 '무효' 로 보고되어 SettingsPage 가
  재발급을 유도할 수 있다 — 메시지에 `포털 검증 호출 실패(ConnectError)` 로 구분은 된다. plan §8.2.3 오류 표에 불통 분기를
  503 `pat_verify_unavailable` 로 나누는 것을 제안하며, 코드 변경은 정본(§8.2.3) 수정 뒤에 한다(코드는 현재 브리프와 일치).
- **HTTP tools/list 실증(리뷰 지적 반영).** `tools/list == 6` 검사가 인프로세스 `srv.mcp.list_tools()` 만 쳤으므로, `test_mcp_tools.py` 에
  `Route('/mcp')` 를 통한 JSON-RPC 경로(initialize → `mcp-session-id` 재사용 → notifications/initialized → tools/list, SSE 면 `data:` 줄 파싱) 로
  도구 이름 6개를 `TOOL_NAMES` 와 같게 단언하는 테스트 1건을 추가했다(plan §9.1 통과 기준 13 의 경로 실증).
- **보류(이번 정합 밖).** `backend/scripts/{bootstrap_ra_ontology,bootstrap_adh}.py`(RA 관리자 PAT·AIDataHub 키 발급 뒤) · `export.py` 자리(P1) ·
  `adapters/registry.py` 의 `/tools-map` 발견 로직(P1) · 엔진 additive(`_CHAIR_ITEMS['risk-review']` 등, agent-server·포털 리포 몫 —
  `test_parity.py` 는 그때까지 skip) · `HWAXPortal/scripts/check_chair_parity.py` · GitHub 생성·HEAXHub 등록(D4) · git 커밋(지시대로 하지 않음).
- **검증.** `cd backend && .venv/bin/python -m pytest -o addopts='' -q` → 103 passed, 2 skipped(`test_parity`, `HWAX_PORTAL_REPO` 미설정; HTTP tools/list 1건 추가 후).
  `HWAX_PORTAL_REPO=…/HWAXPortal` 을 주면 skip 사유가 "deliberation.py 에 _CHAIR_ITEMS['risk-review'] 없음 — P0 엔진 additive 미착수" 로 바뀐다.
  `cd frontend && pnpm build` 성공(dist 갱신). 외부 HTTP 실호출은 테스트에 없다(heax·포털 모두 `httpx.MockTransport`).

## 2026-08-31 (P6 리뷰 반영 — metrics·learning·character·nightly)

- **훅 우선순위 ①의 판정 자리를 등록부 행으로 옮겼다.** `record_label` 이 `rr_findings.status_source` 를 봤는데 앱 어디에도 그
  열에 `'human'` 을 쓰는 경로가 없어 가드가 항상 열려 있었다. 이제 `_registry_keys()` 가 돌려주는 등록부 행의 `status_source`
  최대 등급(+ finding 행 등급)으로 판정하고, 막히면 `applied=0` 로그 1행 + `conflict_with_human` 큐를 남기고 `counted=False` 다.
- **'통계에 드는 라벨' 정의를 한 곳으로 모았다** — `metrics.is_counted_label(label, queue_status)`. 사람(expert_review·manual)
  또는 match_score 1.0 자동 확정(incident·test_run)이면서 그 라벨의 `label_match` 큐가 열려 있지 않은 것만 센다. `sim`·`voc` 는
  큐가 `done` 이 된 뒤에야 precision·`rr_delta_priors`·`rr_patterns` 에 들어간다. `learning.collect_labels`·`label_counts` 가
  같은 술어를 부르므로 증분 훅과 야간 재합산이 갈리지 않는다(옛 `_human_status_rows` 병존 정의는 삭제).
- **지표는 코퍼스 전체 1회 계산으로 바꿨다(선택지 (a)).** `rr_metrics` PK 에 소유자 축이 없어(§5.2.2) 소유자마다 계산하면
  마지막 소유자 값만 남았다. `metrics.recompute(store, *, period, visibility)` 에서 `owner_sub` 를 없애고 `nightly._recompute_metrics`
  의 owners() 루프도 없앴다. `@owner=` 접미(선택지 (b))를 택하지 않은 이유 — 읽는 쪽(§8 배선·화면)이 `('global','global')`
  자리를 그대로 보고, 야간 살림 지표(`nightly_*`)도 이미 소유자 없이 그 자리를 쓴다.
- **분모·적중 판정을 계획대로 좁혔다.** `recall_proxy` 는 라벨이 아니라 **사고**(incident 라벨의 서로 다른 evidence_ref)를 분모로
  세고 같은 cluster_key_norm·mechanism 의 선행 finding 존재로 분자를 센다. `precedent_hit_rate` 는 change_kind 하나가 아니라
  (change_kind, mechanism, mechanism_detail) 조합 선례 또는 같은 subject 의 다른 타깃 등록부 행일 때만 적중이다.
  `adversary_false_reject` 분자는 finding_id 가 아니라 대표 클러스터로 묶는다. `req_consistency` 분모는 요구별 finding ≥2 만.
- **지표 원자 집합을 승격 원자 집합과 맞췄다** — `rejected_in_panel`·`recall_eligible=0`·`weak_subject` 는 분모에서 뺀다
  (`_load_atoms` 가 `eligible` 을 붙인다). 예외는 반대석 지표뿐이다(기각 원자가 그 분모다).
- **낡은 지표 행 삭제.** `recompute` 가 이번 계산에 없는 같은 period 의 자리를 지운다(`nightly_*` 제외 — 지우면 하루 1회 판정이 깨진다).
- **known→rule 초안·백테스트 정합.** `_feature_ranges` 가 narrative 의 실제 저장 형태 `{ref:{attr:value}}` 를 읽고(계획 표기도 허용)
  ref 접두 `e:`·`p:` 로 `edge.*`·`node.*` 를 가른다. 초안에서 `diff.change_kind` 를 뺐고(평가기가 snap 스코프에서 조용히 버린다),
  `backtest` 는 평가기가 모르는 접두가 섞이면 422 다 — 채점한 조건과 저장·발화할 조건이 갈리지 않게.
- **소유자 경계.** `collect_atoms`·`collect_labels`·`mine_patterns` 에 `owner_sub` 를 넣었고(야간은 소유자마다 한 번),
  같은 `cluster_key_norm` 이 남의 패턴으로 서 있으면 `skipped(owned_by_other)` 로 건너뛴다(rr_patterns 는 UNIQUE(cluster_key_norm)
  이라 자리를 못 나눈다 — 키 분기는 §8 배선 담당과 맞춘다). `character.queue_x_tag_promotions` 도 진술·큐 조회에 owner 필터를 걸고
  한 번 판단한 태그(open·done·rejected)는 다시 올리지 않는다. `_next_pattern_id` 는 전역 그대로다 — id 는 PK 라 소유자별로
  나누면 `P-001` 이 충돌한다.
- **gap_21 관측 가능성.** `pattern_stats` 가 `stamp_missing`·`independence_verified` 를 내고 candidate 큐 payload·`promote()` 응답에
  '독립성 미검증(primed 스탬프 없음)' 을 싣는다. `finding_json.primed` 스탬프를 찍는 것은 narrative(다른 담당)의 몫이다.
- **routes_needed(뒤 배선 패스 몫).** ① `PUT /api/curation/{id}` 가 `kind='label_match'` 를 `done|rejected` 로 닫을 때 그 결정이
  곧 '통계에 드는지' 를 가르므로(위 술어) 닫은 뒤 `metrics.recompute`·`learning.recompute_label_priors` 를 다시 부를 것.
  ② 패턴 승격 API 응답에 `independence` 블록을 그대로 실을 것. ③ narrative 의 finding 삽입 경로가 `finding_json.primed` 를 찍을 것.
- **이번 패스에서 하지 않은 것.** (a) 야간 ①·⑤(`metrics.sync_labels`·`refresh_fv_stats`) 미구현 — 라벨 자동 유입 4경로(RA incident·
  test_run·DynaForge·VOC)는 아직 없고, 그 사실을 `run_nightly(...)['unwired']` 와 `rr_metrics(label_ingest_wired)`·배지
  `label_auto_ingest` 로 드러낸다('5경로 완료' 로 읽히면 안 된다). (b) 백테스트 표본 재설계(train 구간에서만 범위 산출·라벨 없는
  심사 타깃을 관측 음성으로 편입·홀드아웃 최소 표본) — 계획이 표본 우주를 정하지 않아 §7.5 정본 결정이 필요하다.
- **검증.** `cd backend && .venv/bin/python -m pytest -o addopts='' -q` → 944 passed, 2 skipped(회귀 없음; 리뷰 재현 8건을 시험으로 고정).

## 2026-09-02 (문서 동기화 — 실체는 P6 인데 문서가 P0 에 멈춰 있었다)

### D7. 앱 리포 문서를 실측으로 되맞추고, 잔여 백로그를 이 리포로 가져왔다

- **문제.** 커밋 8건이 P0~P6 을 통과했는데 `README.md`·`checklist.md`·`docs/plan.md`·매니페스트 description 은 전부 P0 시점 문구였다 —
  "현재는 P0 스캐폴드 단계다", "MCP 본문은 전부 not_implemented", "DDL 33표", "REST 6경로", "Vite/React 플레이스홀더 SPA".
  문서만 읽은 다음 세션(사람이든 에이전트든)이 실체를 정반대로 이해한다. 코드가 아니라 문서가 회귀해 있었다.
- **정본 관계를 한 단계 조정했다.** 계획 정본은 여전히 포털 `HWAXPortal/docs/design-risk-review/plan.md` 다. 다만 **진척과 잔여 백로그의
  정본은 이 리포 `checklist.md`** 로 옮겼다 — 포털 `checklist.md` 는 단계 착수 전에 쓴 문서라 P1~P7 항목이 전부 미체크로 남아 있고
  (체크 17 / 미체크 111), 구현이 끝난 항목과 진짜 남은 항목이 구분되지 않는다. 포털 문서를 소급 수정하는 대신 앱 몫을 여기로 가져와
  실측으로 채우는 쪽을 골랐다 — 계획(무엇을 하기로 했나)과 진척(무엇이 됐나)은 수명이 달라 한 문서에 두면 계속 어긋난다.
- **판정은 grep 이 아니라 코드 대조로 했다.** 정본 체크리스트 P0~P7 절 전문을 읽고 항목마다 심볼·파일을 확인했다. 그 과정에서
  내 첫 판정 둘이 틀렸던 것을 잡았다 — `visible_projects` 와 PAT 오류 6종(`pat_scope_too_broad`·`cred_key_absent`)은 '없음' 이 아니라
  각각 `routes.py:313`·`identity.py` 에 있었다(`routes.py` 만 본 grep 이 놓쳤다). 문서에는 확인된 것만 적었다.
- **이번에 드러난 진짜 구멍 3종**(checklist 1장).
  ① `x_tag_promote` 큐가 결정 불가 — `character.py:311` 이 그 kind 로 큐를 쌓고 DDL CHECK 도 6종을 허용하는데
  `routes.py:2878 CURATION_DECISIONS` 에는 5종만 있어 `PUT /api/curation/{id}` 가 501 이다. 성격 X태그 승격이 UI·API 양쪽에서 막혀 있다.
  ② E10 필드·VOC·문헌 근거가 스텁 — `brief.py:688` 이 늘 결측 문구 한 줄을 낸다. 블록과 지표(`field_evidence_rate`)는 있는데
  실호출·`voc:`/`paper:` 참조·`taxonomy.voc_map` 시드(현재 `[]`)가 없어 분자가 항상 0 이다.
  ③ 프런트 화면 6종 부재 — 특히 `CurationQueue`(`#/curation`)가 없어 `GET /curation`·`PUT /curation/{id}` 가 UI 없이 떠 있다.
  인젝션 의심 문구·라벨 대조·패턴 후보·근접 중복 병합이 전부 그 큐로 오는데 사람이 볼 입구가 없다.
- **'미구현' 과 '미실측' 을 갈라 적었다.** 코드가 없는 것(1장·4장)과, 코드는 있는데 소스 앱 자격·실데이터가 없어 합성 픽스처로만
  채워 둔 통과 기준(2장)은 다른 종류의 빚이다. 섞어 두면 B1(heax 서비스 PAT) 하나로 여러 항이 함께 닫힌다는 사실이 보이지 않는다.
- **HEAX 헬스 프로브 이중 접두는 앱 버그가 아니다.** `/apps/hwax_risk/apps/hwax_risk/api/health` 로 404 를 3,756회(200 은 0회) 냈는데,
  `materialtwin_web`·`web_design_agents`·`voice_recorder` 로그에도 같은 이중 접두가 있다. 플랫폼 공통이라 앱 매니페스트 `health_check.path`
  (`/api/health`, materialtwin-web 과 동일 형태)는 건드리지 않고 checklist 3장에 기록만 남겼다.
- **검증.** 문서 수정 뒤 `pytest -o addopts='' -q` → **1085 passed, 2 skipped**(회귀 0). `test_manifest.py` 는 description 을
  `strip()` 비어 있지 않음으로만 보므로 문구 갱신에 걸리지 않는다. 리포 `.portal/manifest.yaml` 과 HEAXHub 등록 사본은 전체 diff 0 으로 맞췄다.

### D8. `x_tag_promote` 승격을 잇고, 그 과정에서 어휘 자산의 정본 이탈을 잡았다 (2026-09-02)

- **막혀 있던 것.** `character.queue_x_tag_promotions` 가 `x_tag_promote` 큐를 쌓고 DDL CHECK 도 그 kind 를 허용하는데
  `routes.CURATION_DECISIONS` 에 어휘가 없어 `PUT /api/curation/{id}` 가 501 이었다. 큐는 차는데 결정할 수가 없었다.
- **축은 사람이 준다.** 승격은 `x:<value>` → `char:<axis>:<value>` 인데 어느 축인지는 코드가 고를 수 없다(자유 태그는 축 없이 온다).
  `payload.axis` 를 필수로 하고 없으면 422 로 큐를 열어 둔다 — `unclassified_code` 가 `payload.mechanism_detail` 을 받는 것과 같은 꼴이다.
- **승격은 재분류가 아니다.** 대표 태그(`rr_character.tag`)가 없던 행은 승격 태그가 대표가 되고 그 축의 facet 을 따르지만,
  이미 `char:` 대표가 있는 행은 대표·facet 을 그대로 두고 태그 목록에만 더한다. 어휘를 넓히는 결정이 진술의 facet 분류를
  조용히 갈아 끼우면 프로파일 조립(§4.6.4)이 사람 모르게 흔들린다.
- **자산 파일은 앱이 고치지 않는다.** 어휘 마이너 승급(`vocab-1.0`→`vocab-1.1`)은 `applied` 기록에만 남기고 파일 갱신은 사람 몫이다 —
  `unclassified_code` 의 택소노미 승급과 같은 관례다. 값이 이미 축 목록에 있으면(`already_in_vocab`) 승급 없이 진술만 옮긴다.
- **`char:interface` 로는 승격할 수 없다**(`axis_not_promotable`). 그 축의 값은 통제 목록이 아니라 `rr_iface_alias` 에서 파생된다(§4.6.3 (4)).
- **RA 연결.** 승격 전 `x:` 태그는 RA 에 잇지 않는 것이 규칙이라(§5.4 ⑦) 승격 시점에 `design_trait`(status=vocab)+`exhibits` op 를
  `pending_ops` 에 올린다. `queue_sync_ops` 가 같은 op 를 접으므로 객체는 태그마다 1건, 엣지는 진술마다 1건이 된다.
- **덤으로 잡은 것 — 어휘 자산이 정본과 달랐다.** `character-vocab.v1.json` 에 `char:constraint` 축이 통째로 없고 `char:analysis` 가
  5값이었다(정본 plan §4.6.3 JSON 블록은 8축이고 `char:analysis` 8값). 그 결과 씨앗이 내는 `char:analysis:sim_only`·`ecad_only`
  (`character.SOURCE_ABSENT_SEEDS`)가 `narrative.py:1046` 어휘 검사에서 어휘 밖으로 판정돼 **`x:sim_only` 로 강등되고 다시
  `x_tag_promote` 큐로 돌아오고 있었다** — 통제 값이 자유 태그 후보가 되는 고리다. 자산을 정본 블록과 바이트 동일하게 맞췄다.
  요구 규격 축(`char:constraint`)은 `AXIS_FACET` 에는 이미 있었으나 어휘에 없어 검사를 통과만 하고 통제되지 않던 상태였다.
- **회귀 가드.** '적용 함수가 없는 kind 는 501' 을 지키던 옛 시험이 이제 지킬 대상이 없다(6종 전부 배선). 대신
  **'DDL 이 허용한 kind == `CURATION_DECISIONS` == `CURATION_AUDIT_SCOPE`'** 를 시험으로 고정했다 — 다음에 kind 를 늘릴 때
  어휘와 감사 scope 를 같이 넣지 않으면 그 자리에서 깨진다.
- **검증.** `pytest -o addopts='' -q` → **1092 passed, 2 skipped**(시험 7건 추가, 회귀 0). `ruff check .` All checks passed
  (`ruff` 를 venv 에 설치했다 — `[test]` extras 에 있었는데 빠져 있어 그동안 린트가 안 돌았다).

### D9. 큐레이션 큐 화면 — 어휘와 축 목록을 화면이 새로 만들지 않게 (2026-09-02)

- **왜 먼저 했나.** `GET /curation`·`PUT /curation/{id}` 가 UI 없이 떠 있었다. 인젝션 의심 문구·라벨 대조·패턴 후보·근접 중복 병합·
  미분류 코드·자유 태그 승격 여섯 갈래가 전부 그 큐로 오는데 사람이 볼 입구가 없었다 — D8 에서 연 승격 결정도 화면 없이는 못 쓴다.
- **어휘는 한 곳에서만 온다.** kind 별 결정 어휘를 화면이 갖되(`KINDS`), **그 집합이 서버 `CURATION_DECISIONS` 와 같다는 것을 시험으로
  고정**했다(`test_curation_screen_uses_the_same_decision_vocabulary_as_the_server`). 리포에 이미 있는 파리티 관례(`test_parity.py` 가
  PY/JS 문자열을 대조하는 것)와 같은 방식이다 — 어휘가 두 곳에 적히는 것 자체는 UX 문구 때문에 피할 수 없으니, 늙는 것을 막는다.
- **승격 축 선택지는 서버가 준다.** `GET /meta/vocab` 에 `promotable_axes` 를 더했다(`character.promotable_axes()` — 통제 값 목록이
  있는 축만, `char:interface` 는 별칭 파생이라 빠진다). 화면이 축 목록을 따로 가지면 `axis_not_promotable` 가드와 갈린다.
  같은 판정을 라우트와 가드가 함께 부르게 한 것이다. 정본 §0.5.1 경로 목록은 그대로다(응답만 additive).
- **값을 더 받아야 하는 결정은 버튼을 잠근다.** `x_tag_promote` 의 `axis`, `unclassified_code` 의 `mechanism_detail` 이 빈 채로 가면
  서버가 422 를 낸다 — 보내기 전에 막되, 서버 가드는 그대로 둔다(화면이 유일한 방벽이 되지 않게).
- **실동작 확인.** 임시 데이터 디렉터리에 앱을 띄우고 큐 1건을 넣어 화면이 쓰는 경로를 그대로 호출했다 —
  `GET /` 200 text/html · `GET /api/meta/vocab` 200(`promotable_axes` 7축) · `GET /api/curation?status=open` 200(1행) ·
  `PUT /api/curation/QX {promote, axis:char:constraint}` 200(`new_tag` 반영·`vocab-1.1`) · 결정 뒤 `status=done`.
- **덤으로 찾은 것 — 프런트가 부르는데 서버에 없는 경로 2종.** 클라이언트 호출과 `@router` 데코레이터를 기계로 대조했더니
  `GET /panels/{id}/transcript`(`PanelTranscript.tsx`)와 `GET /targets/{key}/seats`(`TargetPage.tsx`)가 서버에 없다. 404 라
  '아직 준비 중' 배너로 접히지만 두 화면 기능이 죽어 있다. 정본 §0.5.1 목록에도 없어 **경로를 더할지 화면을 접을지 결정이 먼저**라
  이번에 고치지 않고 checklist 1장에 적었다(속기록은 §5.2.2 F·§6.7.2 7단계가 원문 보존을 요구하므로 경로를 더하는 쪽이 자연스럽다).
- **검증.** `pytest` **1094 passed, 2 skipped** · `ruff` All checks passed · `pnpm build`(`tsc -b && vite build`) 통과.

### D10. 프런트↔서버 계약 표류를 전수 대조로 걷어냈다 (2026-09-02)

- **어떻게 시작됐나.** 죽은 경로 2종(`/panels/{id}/transcript`·`/targets/{key}/seats`)을 살리려다, 같은 방식으로 응답 **모양**까지
  대조해 봤다. 클라이언트 호출과 `@router` 데코레이터를 기계로 맞춰 보고, 임시 DB 를 띄워 UI 가 부르는 GET 21개의 실제 응답
  최상위 키를 찍어 `types.ts` 와 나란히 놓았다. 9건이 어긋나 있었다.
- **정본이 판정했고, 대부분 서버가 맞았다.** §8.2.3 응답표(`apps[{app_key,…}]`)·§8.2.4 화면표(`L0 seed · L2 panel · confirmed
  3층 나란히`, `출처별 top-k 를 섞지 않음`)가 서버 쪽 모양이었다. 그래서 클라이언트를 서버에 맞췄다 — 반대로 했으면 정본에서
  멀어진다. 봉투 관례(`{rows}`·`{panels}`·`{projects}`)도 서버가 일관돼 있었다(정본 표기 `rr_panels[]` 는 '내용이 그 행들' 이라는
  뜻이고, 같은 표기의 `rr_registry[]` 를 클라이언트도 `{rows, verdict_candidate}` 로 받고 있었다).
- **조용히 깨져 있던 것들.** `adapters.filter(...)` 는 객체에 대고 부르니 TypeError 로 소스 연결 폼이 통째로 죽고,
  `character.data.facets`·`similar.data.by_source` 는 `undefined` 라 성격·유사 과제 카드가 늘 빈 채였다. 404 로 접히는
  두 경로와 달리 이쪽은 배너조차 없었다 — 화면이 '데이터가 없다' 처럼 보였다.
- **서버에 더한 셋.** ① `GET /panels/{id}/transcript` — `rr_seat_opinions.opinion_json.turns` 를 좌석마다 펴서 라운드로 묶는다
  (같은 라운드 안은 좌석 키 순 — 표시 순서를 결정론으로). ② `GET /targets/{key}/seats?domain=` — `coverage` 는 5 s 폴링이라
  카운트만 두고 행은 여기서만 편다. ③ `registry_payload` 의 `verdict_final` — 헤더가 후보와 확정을 한 응답에서 읽는다.
  셋 다 §0.5.1 경로 목록에는 없지만 §8.2.4 화면표가 요구하는 데이터이고 다른 어떤 경로도 주지 않았다.
- **`_loads(x, None)` 함정.** `return value if isinstance(value, type(default)) else default` 라 default 가 `None` 이면
  `type(None)` 과 비교해 **무엇을 넣든 None** 이 나온다. 속기록의 `risk_spec` 을 그렇게 부르다 스모크에서 걸렸다.
  `{}` 로 받고 `spec or None` 로 돌린다. 리포 안의 다른 `_loads` 호출은 전부 `[]`·`{}` 기본값이라 이 함정에 걸린 곳은 없다.
- **가드 둘.** ① `tests/test_client_contract.py` — 클라이언트가 부르는 모든 경로가 서버에 있는지 검사한다(서버의 `{}` 자리는
  클라이언트 리터럴도 받게 해 `POST /jobs/{id}/{action}` 을 정상 처리). 경로 하나를 일부러 지워 실제로 실패하는 것까지 확인했다.
  ② 모양은 TypeScript 가 잡는다 — 봉투 타입을 고치자 `tsc` 가 깨진 소비처 20곳을 그대로 짚었다. 이 두 축이면 다음 표류는
  조용히 지나가지 않는다.
- **앞선 조사 정정.** `CoverageHeatmap` 은 '없음' 이 아니라 `TargetPage.tsx` 안에 있었다(내 grep 이 대소문자를 가렸다).
  드릴다운이 부르던 좌석 경로가 없어 죽어 있었을 뿐이고 이번에 살아났다. checklist 를 고쳤다.
- **아직 남은 것.** `TargetPage` 가 '좌석 상태 되돌리기 · skipped 사유 입력 경로는 아직 서버에 없습니다' 라고 적어 두었는데
  `PUT /targets/{key}/coverage/{agent_key}` 는 서버에 있다 — 클라이언트에 함수가 없을 뿐이다(§8.2.4 가 요구하는 폼).
- **검증.** `pytest` **1101 passed, 2 skipped**(시험 7건 추가) · `ruff` All checks passed · `pnpm build` 통과 ·
  임시 데이터로 속기록 3발언(라운드 순)·좌석 드릴다운·`verdict_final`·어댑터 `app_key` 실응답 확인.

### D12. 어댑터 발견을 이었다 — 소스 카드가 거짓말을 멈춘다 (2026-09-02)

- **증상.** `POST /projects/{id}/sources` 가 소스 카드를 늘 `status='unreachable'` 로 적었다. `list_adapters()` 가
  `ADAPTERS` 고정 목록(mcad·dyna `status='planned'`)을 돌려주기 때문이고 `GET /meta/adapters` 도 같은 값을 냈다.
  그런데 `capture_all` 은 probe 상태를 보지 않으므로 **실제로는 캡처가 돈다** — 배지만 '연결 안 됨' 이었다.
  사용자가 시도조차 안 하게 만드는 종류의 거짓말이라 실 STEP 을 붙이기 전에 먼저 닫았다.
- **구현은 이미 있었다.** `GatewayRegistry`(도구명 suffix 매칭·다의 판정·Probe)가 완성돼 있고 배선만 없었다.
  `discover_adapters(token=, force=, client=)` 로 감싸 두 경로에 이었다.
- **캐시.** `/meta/adapters` 는 ProjectPage 를 열 때마다 불린다 — 60 s 모듈 캐시를 뒀다(identity 의 TTL 60 s 와 같은 결).
  모듈 수준 캐시는 시험 사이로 새므로 conftest 에 autouse 리셋 픽스처를 넣었다.
- **'없다' 와 '못 물어봤다' 를 나눴다.** 게이트웨이를 못 읽으면 `status='planned'` + `gateway_error` 로 남긴다. 도구가 실제로
  빠졌을 때만 `unavailable` 이다. ecad 는 도구가 다 보여도 `contract_only` 다 — 계약만 있는 스텁이고 붙는 것은 P7 이다(§2.5.3).
  폴백에서도 `app_key` 는 고정 목록 값을 유지한다(화면에 빈칸을 보이지 않게).
- **실측(2026-09-02).** 라이브 게이트웨이에 도구 329종·백엔드 15개가 떠 있고 **mcad `heax-step_forge` ready · dyna
  `heax-kooremapper_mcp` ready** 다(요구 도구 전부 present). ecad 만 4종 부재. 소스 등록이 `linked` 를 적는다.
- **시험이 잡아 준 것.** ① `test_meta_adapters_p0_fixed_list` 가 고정 목록을 못 박고 있었다 — 실측 3종으로 다시 썼다.
  ② e2e 스모크의 '외부 호출 0' 가드가 소스 등록의 새 게이트웨이 호출을 즉시 잡았다. 발견 결과를 실제 형태 그대로 캐시에
  미리 넣는 픽스처로 풀었다(호출을 우회한 게 아니라 '이미 답을 안다' 는 상태를 만든 것). 시험은 여전히 네트워크를 안 쓴다.
- **자격 서술 정정.** 이 작업 중 확인한 것 — 커밋 `37b9c3b` 이 캡처 경로의 heax 서비스 PAT 의존을 이미 없앴는데
  checklist 2장은 여전히 'B1 = 최대 단일 레버' 라고 적고 있었다. 실제 필요는 셋으로 갈린다 — 캡처는 로그인만,
  패널 심의는 사용자 포털 PAT 1개(`resolve_credential` (b)), 서비스 키는 무인 배치 전용. 문서를 고쳤다.
- **남은 P1 잔여.** `choices[]`(StepForge `list_projects` 로 프로젝트 선택지 채우기)는 소스 앱 도구 실호출이라 포털 PAT 가
  선행한다 — 지금은 빈 배열이고 사용자가 ref 를 직접 적는다.
- **검증.** `pytest` **1103 passed, 2 skipped** · `ruff` All checks passed · 실 게이트웨이로 mcad/dyna ready·소스 등록 linked 확인.

### D13. 실 STEP 을 붙이기 전에 mcad REST 계약을 실물과 대조했다 — 파트 절단 버그 (2026-09-02)

- **왜 지금.** 캡처 경로는 한 번도 실 StepForge 를 만난 적이 없다. 자격이 풀리는 순간 처음 도는 코드라,
  붙이기 전에 어댑터가 기대하는 REST 를 실물(`/home/koopark/claude/StepForge/app/rest.py`)과 맞춰 봤다.
- **맞은 것.** 5경로 전부 실재하고(`/projects/{id}` · `/tree` · `/parts` · `/interfaces` · `/artifacts/graph/`),
  base 는 `heax_base` + `rest()` 가 붙이는 `/apps/{slug}/api` 로 정확하며, `artifacts/graph/` 의 빈 `ref` 도
  StepForge 가 `_store_artifact(conn, pid, "graph", "", …)` 로 빈 문자열에 저장하는 것과 맞는다.
  `/tree` 는 FileResponse 지만 `media_type='application/json'` 이라 `response.json()` 이 그대로 판다.
- **틀린 것 — `/parts` 의 limit.** StepForge 는 `limit: int = Query(500, ge=1, le=5000)` 이고 어댑터는 아무것도 안 넘겼다.
  **501번째 파트부터 조용히 사라진다.** 같은 파일에서 `/interfaces` 는 `{"limit": REST_IFACE_LIMIT}`(5000)을 넘기고 있었으니
  상한을 몰라서가 아니라 REST 경로를 나중에 붙이면서 빠뜨린 것이다.
- **왜 조용한가.** `/interfaces` 는 `counts` 로 총수를 주어 `sum(counts) > len(rows)` 로 절단을 잡는데, `/parts` 는 총수를
  주지 않는다. 그리고 **MCP 폴백에는 이미 가드가 있었다** — `tree.summary.leaf_instances > len(parts)` 로 `parts_truncated`
  를 붙인다(recon §2.2). REST 경로에만 그 대조가 빠져 있었다.
- **고침.** `REST_PARTS_LIMIT = 5000` 을 명시해 넘기고, REST 트리의 `summary.leaf_instances` 와 대조해 짧으면
  `degraded='parts_truncated'` + 사유 경고를 남긴다(MCP 분기와 같은 규칙). 경고는 결과 최상위 `warnings` 에 실린다.
- **왜 이게 나쁜 버그인가.** 잘린 파트 목록은 예외를 내지 않는다 — 그 파트의 계면·치수·규칙 히트가 통째로 사라진 채
  스냅샷이 '정상' 으로 동결되고, 게이트도 통과하고, 패널은 있지도 않은 깨끗한 모델을 심사한다.
  **오류가 아니라 '없는 리스크' 를 만든다.** 첫 실접촉에서만 드러나는 종류다.
- **픽스처 오독 정정.** `TREE_JSON` 에 `summary` 가 없다고 보고 하나 더 넣었는데, 아래쪽에 이미 있었고(중복 키라 뒤엣것이 이김)
  `leaf_instances=2` 로 실제와 맞게 적혀 있었다. 내 중복 키를 걷어냈다 — 픽스처는 처음부터 옳았고 코드에만 가드가 없었다.
- **검증.** `pytest` **1105 passed, 2 skipped**(시험 2건 추가 — limit 명시 확인 · 짧은 목록에서 절단 표기) · `ruff` 통과.

### D14. `context.corpus_usage` 봉투 승격(§2.2) — 정본 내부 모순을 정본 자신의 문장으로 풀었다 (2026-09-04)

- **왜 미완이었나.** dyna 계약 대조에서 §2.2 가 다섯 곳에서 못 박은 규격과 코드가 어긋난 것을 찾았다. 4도구 중 3도구만 부르고,
  위치가 정본이 "아니다" 라고 명시한 `sources[dyna].context` 이고, 봉투 키가 다르고, 무엇보다 **자격 없으면 early return 으로
  3a 자체가 안 돌았다**. 포털 PAT 를 아무도 등록하지 않은 지금 상태에서는 조직 집계가 한 번도 안 모인다는 뜻이다.
- **정본 안의 모순처럼 보이던 것 — 내 해석이 과했다(적대 검증이 잡았다).** 처음엔 §2.11.3 "dyna 부재여도 3a 수행" 과
  §9.2 "정상 1회 캡처 rest 5 + mcp 3" 이 충돌한다고 보고, 전사 호출을 `source_kind='context'` 로 회계 밖에 두면
  풀린다고 판단했다. **틀렸다.** ① 예산은 `source_kind` 가 아니라 `channel` 로 세므로 태그가 빼주지 못한다.
  ② 더 근본적으로 §2.11.3 의 3a 는 "**3. dyna 캡처**" 의 하위 단계다 — "dyna 부재여도" 는 *자격* 부재를 뜻하지
  mcad 단독 스냅샷을 뜻하지 않는다. 그래서 3a 는 **dyna 를 요청했을 때만** 돌되 자격 유무와 무관하게 돈다.
  이렇게 읽으면 두 조항이 함께 지켜진다(실측 — mcad 단독은 corpus 없음, mcad+dyna 무자격은 corpus 채움).
- **`source_kind='context'` 는 그래도 남긴다** — §2.2 의 "`degraded` 에는 넣지 않는다(**소스 캡처가 아니다**)" 가
  근거이고, 예산과는 별개로 매핑이 찾아낸 위험 셋을 닫는다 —
  ① `call_ids('dyna')` 오염(kind 가 달라 자동 분리) ② 예산 위반(집계 밖) ③ `reuse_prior_calls` 가 `args={}` 를 100%
  재사용 표기해 `calls_reused` 가 4씩 부푸는 것(시변 집계라 재사용 자체가 틀렸다 — `fetched_at` 이 있는 이유다).
  실패도 잡을 `partial` 로 만들지 않는다(같은 근거).
- **3a 위치는 한 곳뿐이다.** `capture_all` 의 409 가드 뒤·kind 루프 **뒤**. 앞에 두면 mcad 의 ref 결손 422 가 이 호출을
  먼저 내보내고 죽어(소스 캡처가 실패한 잡에 조직 집계만 남는다) e2e 스모크가 깨진다. 어댑터 안에 남기면 dyna 소스 카드가
  없을 때 어댑터 자체가 안 불려(registry.py `if row is None: continue`) '자격 무관' 이 소스 카드 유무에 다시 매달린다.
- **봉투는 병합이다.** 리포 정찰 픽스처가 증거였다 — `material_usage`→`{materials}`, `section_contact_usage`→`{sections}`,
  `corpus_summary`→`{sessions}`. 각 도구가 자기 키를 담은 dict 를 돌려주므로 4응답을 **펼쳐 합치면** 정본 §2.2 예시의 평평한
  8키가 그대로 나온다. 옛 코드는 합치지 않고 중첩해서 정본에 없는 `corpus` 키가 생겼다. 이 설계 덕에 `operation_usage` 의
  키 이름을 내가 지어낼 필요가 없었다(게이트웨이 MCP 는 401 이라 도구 응답을 직접 볼 수 없었다).
- **발견 게이트에서 전사 도구를 뺐다.** 정본 §2.13.2 의 dyna 집합은 `{inspect_file, list_session_files, report_summary,
  report_part_risk, report_energy_flow}` 이고 전사 도구가 없다. 코드는 거기에 corpus 3종을 넣고 있었다 — 그 도구가 없는
  게이트웨이에서 dyna 가 통째로 unreachable 이 된다. 라이브 게이트웨이에 정본 집합이 전부 있음을 확인하고 바꿨다.
- **스키마 표류가 1건이 아니라 3건이었다.** `primary_source` 누락 · `definitions.source.app_version` 누락 ·
  `degraded_code` enum 의 `app_version_unknown` 누락. 셋 다 **실제 `build_ir()` 산출을 스키마로 검증하는 시험이 리포에
  0건**이라 잡히지 않았다(검증은 손으로 쓴 픽스처에만 걸려 있었다). `tests/test_ir_schema_contract.py` 를 세워
  실제 산출·부재 소스 봉투·어댑터가 내는 degraded 어휘를 전부 계약으로 묶었다. 두 표류를 일부러 되살려 시험이 실제로
  실패하는 것까지 확인했다.
- **`ir_hash` 는 손댈 필요가 없었다.** `compute_ir_hash` 가 `nodes·edges·same_as·dims_named` 허용목록이라 봉투에 키를
  더해도 해시가 안 바뀐다 — 정본의 "ir_hash 에서 제외" 가 구조로 이미 보장된다. 그 사실을 시험으로 고정했다.
- **실동작 확인.** dyna 소스 카드 없음 · 사용자 PAT 없음 · REST 채널 없음이라는 최악 조건에서 `capture_all` 이
  `corpus_usage` 를 채웠고(8키 전부), 호출 kind 가 `{mcad: 8, context: 4}` 로 갈렸으며 mcad 소스의 `call_ids` 에
  corpus id 가 섞이지 않았다.
- **포맷 사고 정정.** 스키마·픽스처를 `json.dumps(indent=2)` 로 라운드트립해 8,000줄이 다시 쓰였다(원본은 스키마 2칸·픽스처
  1칸 들여쓰기). CLAUDE.md §3 위반이라 되돌리고 텍스트 최소 편집으로 다시 했다 — 스키마 1537→9줄, 픽스처 1550→16줄.
- **범위 밖으로 남긴 것**(별건, checklist 에 적었다) — ① 호출 시점 도구 이름 해석 부재(`tool_matches` 는 probe 전용이라
  게이트웨이가 이름 충돌로 접두를 붙이면 전사 4호출이 경고 없이 전멸한다) ② `freeze_snapshot` 재사용 분기가 `ir_json` 을
  갱신하지 않아 같은 `ir_hash` 재캡처에서 호출은 나가는데 값이 얼어붙는 것 ③ corpus_usage 의 위생(`sanitize_source_text`
  우회)과 `part='ir'` 상한 부재 — 정본이 '원문 발췌' 의 추출 규칙을 정하지 않았다.
- **검증.** `pytest` **1116 passed, 2 skipped**(시험 11건 추가) · `ruff` All checks passed.

### D15. 적대 검증이 내 변경에서 결함 28건을 찾았다 — 절반은 시험이 자기를 속인 것 (2026-09-04)

5렌즈 × 3표 반증(에이전트 137)으로 D14 변경을 다시 봤다. 확정 28 · 반증 16. 값진 것만 적는다.

- **내가 만든 회귀(HIGH, 5렌즈 전부가 독립적으로 잡음).** 스키마의 `definitions.source.app_version` 을
  `["string","null"]` 로 적었는데 실물은 `{version, captured_via, extra}` **객체**다(`base.UNKNOWN_APP_VERSION`,
  정본 plan §2.2·:635 예시도 객체). 같은 변경에서 `additionalProperties:false` 를 세웠으므로 **실제 mcad 봉투가
  전부 거부**된다. 타입을 확인하지 않고 추측해서 넣은 것이다.
- **그걸 가린 것은 내가 새로 만든 시험이었다.** '실제 산출을 검증한다' 던 `test_ir_schema_contract.py` 의
  `_mcad_result()` 가 `app_version: None` 이라는 **손으로 지은 모양**을 써서 초록이었다. 이제 어댑터 상수
  `base.UNKNOWN_APP_VERSION` 을 그대로 쓰고, 버전을 읽은 정상 경로도 함께 고정한다. 교훈은 하나다 —
  '실물을 검증한다' 는 시험이 stub 을 쓰면 그 취지가 통째로 무너진다.
- **항진명제 시험이 진짜 버그 둘을 가리고 있었다.** `assert [name for name,_ in seen] == list(CORPUS_TOOLS)` 와
  `assert {c["source_kind"]} == {CONTEXT_KIND}` 는 코드를 코드 자신과 비교한다. 상수를 정본 리터럴로 바꾸자
  **`CORPUS_TOOLS` 순서가 뒤집혀 있고 `CONTEXT_KIND` 가 `"dyna"` 로 되어 있는 것**이 드러났다(내 스모크가 통과한
  뒤 어느 시점에 뒤집혔다 — 적대 검증 에이전트 137개가 쓰기 권한을 가진 채 돌았고 프롬프트에 '고치지 마라' 를
  넣지 않았다. **검토 에이전트는 읽기 전용으로 돌려야 한다**).
- **degraded enum 수정이 부분적이었다.** `app_version_unknown` 하나만 넣었는데 `capture_partial`(state.py:210 이 읽는다)·
  `schema_drift`(diff.py:265 가 읽는다) 등 6종이 더 빠져 있었고 픽스처도 이미 쓰고 있었다. 어휘 가드를 3축으로
  넓혔다 — 어댑터가 **내는** 코드 · 하류가 **읽는** 코드 · 픽스처가 **쓰는** 코드. 하류 축이 실제로 잡는 것을 확인했다.
- **배선이 미검증이었다.** capture_all→routes→ir_json 을 검증하는 시험이 0건이라 **3a 블록을 통째로 지워도 전 시험이
  초록**이었다. 3건을 세웠고, 블록을 지워 실제로 빨개지는 것을 확인했다.
- **작은 것들** — corpus `app_key` 를 정적 기본값으로 박아 다른 백엔드를 쓰는 조직에서 틀린 값이 동결될 수 있었다
  (등록된 소스 카드 값 우선으로 고침) · 부재 소스 시험의 `ecad` 파라미터가 실제로는 dyna 를 두 번 돌려 ecad_stub 이
  한 번도 검증되지 않았다(실제 스텁 산출로 검증하는 시험 신설).
- **남긴 것.** `primary_source`·`context` 를 스키마 `required` 에 넣는 것은 유효·무효 픽스처를 함께 손봐야 하고
  무효 픽스처 6종의 거부 사유가 '원래 잡으려던 결함' 에서 '새 필수 키 누락' 으로 바뀔 위험이 있어 별건으로 둔다.
- **검증.** `pytest` **1121 passed, 2 skipped** · `ruff` All checks passed · 두 시나리오 실측
  (mcad 단독 → corpus 없음·DynaForge 0회 / mcad+dyna 무자격 → corpus 채움·kind `{mcad:8, context:4}`).

### D16. E10 착수 전에 `req:` 참조를 1급으로 만들었다 — 좌석 계약이 지시하는 인용이 파서에 없었다 (2026-09-04)

- **E10 매핑에서 딸려 나온 것.** 정본 §0.2.1 (5) 는 `req:`·`voc:` → **측정**, `paper:` → **문헌·규격** 이라고
  세 행을 못 박는데 `common.REF_SCHEMES` 에 셋 다 없었다. 그중 `req:` 는 **이미 쓰이고 있었다** —
  좌석 계약(`seat-contract.v1.json`)의 `_common` 이 "판정은 브리프 E0·E3 에 실린 요구(req:)의 한계와 여유를
  기준으로 하라" 고 지시하고, `std` 좌석은 `req:<name>` 인용을 **필수**로 요구하며, `requirements.py` 가
  E3 줄에 `req:` 를 싣는다. 그런데 `parse_ref('req:thickness')` 가 `None` 이라 그 인용은 전부 `dangling` 이 되고
  등급이 **경험칙**으로 떨어졌다 — 정본이 `측정` 이라고 적은 자리에서.
- **왜 나쁜가.** §6.5.2 가 적어 둔 그대로다 — "그것이 좌석에게 닿지 않으면 `evidence_grade` 분포가
  `도구예측·경험칙` 으로 굳어 학습 루프가 사고 이력을 못 쓴다". 등급은 재제기 escalated 판정(§4.7.1)과
  E5 정렬에도 들어가므로 조용히 전체 계보를 낮춘다.
- **catch-all 함정.** `parse_ref` 의 마지막 줄이 `return {"kind": "inc", ...}` 다. 스킴만 `REF_SCHEMES` 에 더하고
  분기를 빠뜨리면 `req:` 가 **사고 참조로 읽혀 등급이 곧장 `측정`** 으로 튄다(해석 없이). 그래서 분기를
  catch-all 앞에 명시로 넣고 그 사실을 시험 주석에 남겼다.
- **해석 원장은 명확했다** — `rr_requirements` 의 그 과제 행이다(`SpecContext.requirement`). `project_id` 는
  `panel_context`(narrative.py:1369)가 이미 채우므로 패널 경로에서 끝까지 통한다. 등록되지 않은 요구를
  인용하면 여전히 dangling·경험칙이다(지어낸 요구가 등급을 올리지 못한다).
- **`voc:`·`paper:` 는 함께 넣지 않았다.** 등급은 해석이 성공해야 오르는데(`evidence_grade_from_cites` 가
  `ok and grade_ok` 만 센다), 그 둘의 **해석 규칙이 정본 안에서 갈린다** — §0.2.1 은 `voc:` 를 "브리프 E10
  블록에 실린 것만", §5.6.2 는 "`rr_panel_calls` 에 남아 해석된다", §5.6.4 는 추적 목록을 5종으로 못 박는다.
  E10 본체 결정과 함께 가야 한다.
- **검증.** `pytest` **1124 passed, 2 skipped**(시험 3건 추가) · `ruff` 통과.

### D17. E10 은 정본이 정하지 않은 P0 결정 4개를 안고 있다 — 구현 보류 (2026-09-04)

5축 매핑(읽기 전용)과 완결성 비판이 낸 결론이다. 정본 §5.6.1·§5.6.2 가 줄 형식·상한·호출·데드라인까지
촘촘히 적어 두었는데도, 리포에 실제로 넣으려면 정본이 답하지 않은 것이 넷 남는다.

1. **E5 세 블록 산술이 성립하지 않는다.** 정본은 "세 블록 합 1500" 이라 쓰지만 `CAPS['E5']=1500` 은
   오버헤드(≈75)·프레이밍·머리글까지 포함하는 **라인 상한**이라 세 블록이 다 차면 실효 한도를 183자 넘긴다.
   `build_brief` 의 `clip_lines` 가 뒤에서부터 버리므로 **맨 뒤 E10 이 먼저 조용히 죽는다**. 실효 잔여는 319자.
   E5_FIELD_CAP 을 잔여치로 낮출지 · E5+ 700 을 줄일지 · 블록 순서를 뒤집을지 · CAPS 를 올리고 다른 항목에서
   뺄지 — 정본은 넷 중 어느 것도 말하지 않는다.
2. **정본의 결측 문구가 정본의 린터에 걸린다.** `[조회 실패: <tool>]` 의 '실패' 가 `render.JUDGEMENT_LEXICON`
   L14 에 걸리고 `LINT_NEUTRAL_PATTERNS` 로도 마스킹되지 않아 `strict_lint=True` 인 러너 경로에서 브리프
   조립이 E500 으로 죽는다. 문구를 바꾸면 정본 문면 개정이고, 린터에 예외를 더하면 판단어 검문에 구멍이 난다.
3. **`rr_panel_calls` 에 `source_kind` 열이 없다.** 열 이름은 `source` 이고 CHECK 는 `sse|events|tool_inject` 다.
   CHECK 확장은 리포·정본의 마이그레이션 규칙(ADD COLUMN·인덱스만)을 어기므로 **열 추가(v2 마이그레이션)가
   유일한 길**이고, 그러면 `test_store.py` 의 `MIGRATIONS[-1][0] == 1` 이 깨진다. 더구나 `panel_id` 가 NOT NULL
   인데 E10 결과는 **타깃 단위 24 h 공유**이고 브리프는 패널 편성 전에도 돌며,
   `runner.record_panel_calls` 의 `DELETE ... WHERE panel_id = ?` 가 그 행을 지운다.
4. **24 h 재사용의 키·저장처가 비어 있다.** 판정 키(target_key? project_id? (product_code, tool, args)?),
   재사용 시 새 행인지 인용인지(`rr_panel_calls` 에는 `reused_from_call_id`·`args_hash` 열이 없다),
   그리고 결정론 시험('두 번 조립하면 바이트 동일')을 이 캐시가 어떻게 지키는지.

그 밖에 P1·P2 로 — `voc:` 존재 검증 원장이 §0.2.1/§5.6.2/§5.6.4 세 곳에서 서로 다르게 적혀 있고,
`paper:` 의 record_id 와 DOI 구별 규칙이 없으며, `voc_map` 시드 12행은 정본이 예시 4개만 주는데
그중 3개(`mechanical.fracture`·`interface.gap`·`interface.delamination`)가 택소노미 38코드 밖이고,
`evidence_profile.field` 는 §0.2.1 (5) 가 요구하지만 §0.1 용어표·risk_spec 스키마 어디에도 자리가 없다.

**하지 않은 이유.** 3번은 DB 마이그레이션(되돌리기 어려운 계약 변경), 2번은 정본 내부 모순, P2 는 통제
어휘 8행을 코드가 지어내야 하는 일이다. 어느 하나라도 틀리게 고르면 작업이 통째로 무의미해지므로
결정 전에는 착수하지 않는다(CLAUDE.md §1).

### D18. E10 필드·VOC·문헌 근거 — P0 결정 넷을 실측 위에서 확정하고 구현했다 (2026-09-04)

사용자가 추천안대로 진행을 승인해 셋을 확정하고, 넷째는 셋째에 딸려 풀렸다.

- **① E5 세 블록 산술 — `E5_FIELD_CAP` 500 → 340.** 실측이 답을 정했다. `CAPS['E5']`=1500 은 오버헤드
  (`line_overhead` 52)까지 포함하는 **라인** 상한이라 result 실효 한도가 1448 이고, 여기에 프레이밍 56 +
  블록 머리글 46 + 줄바꿈 4 = 106 이 먼저 든다. 세 블록을 정본 값(700+300+500)대로 채우면 1606 이 필요해
  158 을 넘기고, `clip_lines` 가 **뒤에서부터** 버리므로 맨 뒤 E10 이 통째로 사라진다. 선례 두 블록은 정본 값
  그대로 두고(E5+ 는 이 앱의 핵심 산출이다) E10 만 실효 잔여로 맞췄다. 최악 픽스처로 E10 본문 4줄이
  살아남는 것을 시험으로 잠갔다.
- **② 결측 문구 `[조회 실패: …]` → `[조회 불가: …]`.** 정본 문면의 '실패' 가 `render` 판단어 어휘 L14 에
  걸리고 `LINT_NEUTRAL_PATTERNS` 로도 마스킹되지 않아 `strict_lint=True` 인 러너 경로에서 브리프 조립이
  E500 으로 죽는다. 대안 문구를 실제로 린터에 태워 보고(`불가`·`없음` 통과) 상태 서술로 바꿨다 —
  린터에 예외를 파면 "코드는 판단어를 쓰지 않는다" 는 원칙에 구멍이 생긴다.
- **③ `rr_panel_calls` 대신 `rr_brief_calls`(DDL v2).** 정본은 `rr_panel_calls(source_kind='brief')` 라
  적지만 그 표에는 `source_kind` 열이 없고(열 이름은 `source`, CHECK 3값) CHECK 확장은 마이그레이션 허용
  연산(`CREATE TABLE IF NOT EXISTS`·`ADD COLUMN`·`CREATE INDEX`) 밖이다. 더 근본적으로 그 표는
  `panel_id` NOT NULL 인데 브리프는 **패널 편성 전에도** 돌고 E10 결과는 **타깃 단위 24 h 공유**이며
  `record_panel_calls` 의 `DELETE WHERE panel_id = ?` 가 그 행을 지운다. 열 이름만 맞추면 이 셋이 그대로
  남아 별도 우회가 필요하다. 구조가 맞는 별도 표로 두어 셋을 한 번에 없앴다.
- **④ 24 h 재사용 — 키 `(target_key, tool, args_hash)`, 원장에 한 행.** ③에서 자유로운 설계가 가능해졌다.
  `call_id` 에 시각을 섞지 않는다 — 같은 초 재호출이 UNIQUE 로 터지고, 행이 쌓이면 `voc:` 참조가 어느 행을
  가리키는지 모호해진다. 창이 지나면 그 행을 새 원문으로 **갱신**한다. 재사용 시 같은 원문을 돌려주므로
  '두 번 조립하면 바이트 동일' 결정론이 유지된다(시험으로 고정).

**정본이 두 갈래로 적은 것이 사실은 한 갈래였다.** §0.2.1 은 `voc:` 를 "브리프 E10 블록에 실린 것만",
§5.6.2 는 "원장에 남아 해석된다" 고 적어 매핑이 모순으로 봤다. `rr_brief_calls` 를 두니 **브리프가 부른
응답 원문 원장이 곧 실린 것의 목록**이라 둘이 같은 뜻이 됐다. 좌석이 지어낸 `voc:` 는 원장에 없어 dangling
이고 등급이 오르지 않는다(시험으로 실증).

**위생에서 정본 문면을 하나 벗어났다.** 정본 줄 형식은 `paper:<id> | <제목> | «<초록>»` 이라 제목·카테고리를
`«»` 밖에 두는데, 그 자리는 **외부 문자열**이고 `«…»` 밖은 판단어 린터에 그대로 노출된다. VOC 카테고리가
`치명적 실패` 하나만 와도 브리프 조립이 통째로 죽는다. 자유 문자열은 전부 `sanitize_source_text` 를 거쳐
`«…»` 안에 두고, 기간은 응답 대신 **내가 보낸 인자**로 적어 외부 문자열을 하나 줄였으며, 건수는 정수로만
싣는다. 적대적 응답(판단어·주입 문구·문자열 건수)으로 그 방어를 시험에 고정했다 — 주입 문구는
`«[suspect_text …]»` 자리표시자가 되고 린터는 통과한다.

**두 호출자 모두에 채널을 주입했다.** `build_brief` 는 러너(`narrative.prior_evidence`)와 REST·MCP
미리보기(`routes.brief_payload`) 양쪽에서 돈다 — "러너 몫" 으로 두면 미리보기 경로의 E10 이 영영 빈다.
채널이 없으면(`HWAXRISK_PORTAL_PAT` 미등록) `None` 이고 그 블록만 결측 문구가 된다.

**함께 닫은 참조.** `voc:`·`paper:` 를 `REF_SCHEMES` 에 넣고 **catch-all 앞에 명시 분기**를 뒀다
(빠뜨리면 `inc:` 로 읽혀 등급이 곧장 측정으로 튄다 — D16 과 같은 함정). 등급은 §0.2.1 (5) 대로
`voc:` → 측정, `paper:` → 문헌·규격.

**남긴 것** — `taxonomy.voc_map` 시드 12행(정본이 예시 4개만 주고 그중 3개가 택소노미 38코드 밖. E10 이
아니라 §7.6 라벨 경로 4 의 입력이라 이번 범위 밖) · `evidence_profile.field`(§0.2.1 (5)가 요구하지만
§0.1 용어표·risk_spec 스키마에 자리가 없다 — 의장 신고 키인지 코드 계산값인지 정본 결정 필요) ·
§4.4.3 등급 표에 `req:`·`voc:`·`paper:` 세 행 추가(정본 문면 개정).

**검증.** `pytest` **1134 passed, 2 skipped**(시험 12건 추가) · `ruff` 통과 · DDL v1→v2 업그레이드가
데이터를 보존하고 pre-migrate 사본을 남기는 것 실측 · 악의적 VOC 응답에 대한 위생·린터 방어 실증.

### D19. 프런트 화면 3종 — REST 가 UI 없이 떠 있던 마지막 자리 (2026-09-25)

큐레이션 큐(D-2026-09-02)와 같은 종류다 — 서버 경로는 있는데 사람이 쓸 입구가 없던 것들.

- **`HumanFindingForm`**(TargetPage 등록부 카드) — `POST /targets/{key}/findings` 의 짝.
  **인용 최소 1건을 폼이 먼저 강제한다** — 서버가 `cites:[]` 를 422 로 막으므로(§4.3.1), 사용자가 422 를
  보고 나서야 알게 두지 않는다. 서버 가드는 그대로 남긴다(화면이 유일한 방벽이 되지 않게).
  `mechanism` 선택지는 `GET /meta/taxonomy` 의 축에서 온다 — 어휘를 화면이 따로 가지면 한쪽만 늙는다.
  실측 — 인용 1건이면 200 `{finding_id:'snap:S1#H1', origin:'human'}`, 0건이면 422.
- **`BriefTokens`**(RecallPreview 안) — `GET /targets/{key}/brief` 가 패널마다 싣는 `brief_token` 을
  복사한다. L2 오케스트레이터(`hwax-risk-review`)가 MCP `risk_get_brief` 에 넘기는 **유일한 열쇠**이고
  이 값 없이는 게이트웨이 경유 호출이 안 열린다(§8.2.5). 클립보드가 막힌 환경(비보안 오리진)에서는
  `window.prompt` 로 값을 노출해 직접 고를 수 있게 한다.
  실측 — 편성된 패널에 32자 토큰이 발급되고 **DB 에는 해시만 남는다**(`brief_token_hash`) —
  화면 문구 "이 화면을 떠나면 다시 볼 수 없습니다" 가 사실이다.
- **`VocabCard`**(ProjectPage) — `POST /vocab/synonyms`·`stop-tokens`. 추가는 마이너, 삭제는 메이저이고
  메이저면 붉은 배너로 `recompute_part_keys.py` 안내를 띄운다(§2.7.1). 실측 — 추가 `1.1/minor/
  recompute_required=false`, 삭제 `2.0/major/true`.
- **타입을 두 번 추측했다가 실물로 고쳤다.** `HumanFindingCreated` 를 `{dangling, evidence_grade}` 로,
  `VocabBump` 를 `recompute_pending` 으로 적었는데 실제는 `{finding_id, claim_uid, cluster_key, origin}` 과
  `recompute_required`(+`synonyms`·`stop_tokens`)다. D14 의 `app_version` 과 같은 실수라 이번에는
  커밋 전에 라우트 반환문을 직접 읽어 맞췄다 — **응답 모양은 추측하지 말고 `return` 문을 본다**.
- **3주 공백 확인.** 이 세션 재개 시 제 마지막 커밋(`6680384`) 위에 다른 세션의 커밋 4개가 있었다
  (MCP 도구 7종·게이트웨이 사용자 위임). 프런트엔드는 건드리지 않아 충돌 0 이었고, 시험은 1134→1147 로
  늘어 있었다. 재개 전에 `git log`·`pytest`·`checklist` 를 먼저 확인한 것이 그 판단의 근거다.
- **검증.** `pytest` **1147 passed, 2 skipped** · `ruff` 통과 · `tsc -b && vite build` 통과 ·
  `test_client_contract` 가 새 경로 3종을 인정 · 세 경로 실응답 확인.

### D20. E10 자체 점검에서 내 버그 둘을 먼저 잡았다 (2026-09-25)

적대 검증(5렌즈)을 돌리면서, 렌즈가 놓칠 수 있는 곳을 직접 확인해 둘을 찾았다.

- **`product_refs_json` 의 `kind` 를 안 가렸다.** 정본 §5.6.2 는 "`product_refs_json` 의 **`product_code`
  값들**" 이고 항목 모양은 `[{kind: 'ra_model'|'product_code', value, ra_entity_id}]`(§5.2.2 DDL 주석 2310행)다.
  내 `product_keys` 는 종류를 안 가리고 모든 항목의 `value` 를 썼다 — **`ra_model` 의 값(RA 엔티티 코드)이
  제품코드로 쓰여 VOC 를 엉뚱한 키로 조회한다.** 응답이 비면 `[필드·문헌 근거 없음 — VOC 0건]` 이 되어
  오류 없이 '필드 이력 없음' 으로 보인다 — 또 '없는 리스크' 계열이다. kind 필터를 넣고 폴백 순서까지 시험에 고정했다.
- **채널을 닫지 않았다.** `McpHttpClient` 는 자기 `httpx.Client` 를 소유하고 `close()` 가 있는데
  `from_settings()` 로 만든 채널을 아무도 닫지 않았다. 리포에는 이미 같은 관례가 주석까지 달려 있다
  (`routes.py` capture_all 뒤 "닫지 않으면 스냅샷 요청마다 소켓이 샌다"). 브리프 조립은 패널마다·미리보기
  요청마다 돌아 누수가 더 빠르다. `FieldSource.close()` 를 주고 두 호출자를 `try/finally` 로 감쌌다.
- **확인해서 문제 없던 것들**(렌즈 결과와 대조할 기준) — `scholar_query` 의 두 쿼리에 타이브레이커가
  있어(`, id` · `, mechanism`) 정렬 결정론은 안전하다 · `_cached` 가 `ok = 1` 만 보므로 실패 응답을
  캐시해 재시도를 막지 않는다 · `except Exception` 은 `KeyboardInterrupt`·`SystemExit`(BaseException)을
  삼키지 않는다 · `_framing` 의 날짜는 ISO 고정폭이라 E5 산술이 날짜로 흔들리지 않고, 그 산술 시험은
  실측값에서 계산하므로 프레이밍이 길어지면 스스로 깨진다.
- **검증.** `pytest` **1148 passed, 2 skipped**(시험 2건 추가) · `ruff` 통과.

### D21. 재사용 스냅샷 — 불변은 지키고, 버려지던 값은 낸다 (2026-09-25)

체크리스트 1장 "`freeze_snapshot` 재사용 분기가 값을 얼린다" 를 닫았다. 문제를 정확히 적으면 —
`ir_hash` 는 허용목록(`nodes`·`edges`·`same_as`·`dims_named`)이라 **전사 집계는 해시 입력이 아니다**.
그래서 모델이 그대로면 조직 집계가 바뀌어도 같은 해시가 나오고, 재사용 분기가 기존 스냅샷을 돌려주며
방금 받은 집계를 버린다. 호출은 매번 나가는데(비용·지연) 값은 첫 스냅샷에 얼어 있다.

**고칠 수 없는 쪽을 먼저 정했다.** `ir_json` 을 UPDATE 하는 건 스냅샷 불변(§2.1)을 깨는 일이고
docstring 이 그걸 명시한다. 그러니 스냅샷은 그대로 두고 **응답이 사실을 다 말하게** 했다 —

- `context` — 이번에 받은 집계. 버리지 않는다. 두 분기가 같은 키를 낸다(재사용이든 아니든 "이번 값").
- `context_frozen_at` — 얼어 있는 값이 언제 조회된 것인지.
- `context_changed` — 값이 달라졌는지. `fetched_at`·`app_key` 는 비교에서 뺀다(그것까지 비교하면
  언제나 `True` 라 아무것도 못 알려 준다). **이번 4호출이 전부 실패하면 `None`** 이다 — 안 변한 게
  아니라 모르는 것이고, 그 둘을 같은 `False` 로 눕히면 또 '없는 리스크' 가 된다.

**같이 나온 것.** `routes.create_snapshot` 끝의
`UPDATE rr_snapshots SET job_id = ?, capture_partial = ? WHERE id = ?` 가 재사용일 때도 돌아
**남의 스냅샷을 이번 잡으로 덮어쓰고** 있었다. 이번 캡처가 부분이면 완주했던 스냅샷이 부분으로 바뀌고,
`job_id` 는 자기를 만든 잡을 잃는다. 재사용이면 그 UPDATE 를 건너뛴다 — 여러 잡이 한 스냅샷을 재사용하니
잡→스냅샷 방향은 `rr_snapshot_jobs.snapshot_id` 가 맡는 게 맞다. 이쪽이 스냅샷 불변의 진짜 위반이었다.

**검증.** 시험 2건 — `test_reuse_returns_this_calls_corpus_not_the_frozen_one`(네 경우: 신규 · 값 변화 ·
`fetched_at` 만 다름 · 전부 실패), `test_reusing_a_snapshot_does_not_restamp_it_with_the_new_job`
(고치기 전 실제로 깨지는 것까지 확인했다). `pytest` **1151 passed, 2 skipped** · `ruff` 통과.

### D22. E10 적대 검증 — 검증 단계가 죽었고, 그래서 내가 전수 대조했다 (2026-09-25)

**먼저 검증 자체의 실패를 적는다.** 5렌즈×3표 반증 워크플로를 돌렸는데 렌즈 5개는 끝났고(지적 63건,
중복 포함) **반증 에이전트 186개가 전부 세션 한도로 죽었다**. 워크플로가 돌려준
`{confirmed: [], refuted_count: 62}` 는 결과가 아니라 **실패의 흔적**이다 — 반증이 0회 돌았으므로
"62건 반박됨" 은 사실이 아니고 "확정 0건" 도 사실이 아니다. 그대로 믿으면 63건을 전부 버리게 된다.
그래서 정본과 코드를 직접 기계 대조했다. 이번 교훈은 **집계 수치를 결과로 읽지 말고 실패 목록을 먼저
읽으라**는 것이다(지난번 교훈이 '에이전트에 쓰기 권한을 주지 말라' 였던 것과 같은 계열).

**확정해 고친 것 — 9건.**

1. **`E5_FIELD_CAP`(340)이 죽은 상수였다.** D18 이 그 값을 계산한 이유가 바로 "적용하지 않으면
   `clip_lines` 가 뒤에서부터 버려 맨 뒤 E10 이 통째로 사라진다" 였는데, **계산만 하고 적용하지 않았다.**
   막으려던 실패가 그대로 살아 있었다. 문자 상한을 걸고, `[조회 불가]` 꼬리 길이를 먼저 떼어 두어
   조회 불가 사실이 예산 때문에 지워지지 않게 했다(지워지면 '조회했는데 0건' 과 구별되지 않는다).
   산술 자체를 `E5_STRUCTURAL=159` 로 코드에 두고 시험이 부등식을 지킨다 — 주석으로만 두면 또 틀어진다.
2. **`voc:`·`paper:`·`req:` 가 판단어 린터 중립 목록에 없었다.** `inc:`·`card:` 는 있다. 외부 issue_key·
   DOI·규격 번호는 남이 지은 문자열이고 `«…»` 로 감쌀 수도 없다(감싸면 참조로 파싱되지 않는다).
   **재현했다** — `voc:P1#치명` 이 `JudgementLintError` 로 죽고 `inc:ABC치명` 은 통과했다.
   `strict_lint` 러너 경로에서 VOC 키 한 개가 브리프 조립을 E500 으로 죽이는 길이었다.
3. **실패한 재조회가 성공 원문을 지웠다.** 행이 `(target, tool, args)` 당 하나뿐이라
   `INSERT OR REPLACE` 가 `result_gz` 를 NULL 로 만든다 → 그 원문으로 해석되던 `voc:`·`paper:` 인용이
   **전부 dangling 으로 뒤바뀌고 등급이 측정→경험칙으로 떨어진다.** 성공만 REPLACE, 실패는
   `INSERT OR IGNORE` + 실패 행에만 마지막 시도 갱신.
4. **`rr_brief_calls` 가 폐기·이양·증분 반출 계약 밖에 있었다.** `rr_panel_calls.result_gz` 와 같은
   성질의 열인데 `PURGE_BLANK_SQL`·`TRANSFER_DERIVED`·`_SINCE_COLS` 세 곳에 다 없었다. 폐기해도 외부
   VOC 원문이 남고, 이양하면 `owner_sub` 불변식이 깨져 새 소유자의 반출에서 해석 원장이 사라진다.
5. **인용 검증 범위가 '부른 것' 이었다 — 정본은 '실린 것' 이다.** 원문에 이슈가 수십 건 와도 블록은
   상위 카테고리 3 + 문헌 2 만 싣는다. 원문 전체를 근거로 삼으면 블록에 없던 이슈를 인용해도 측정
   등급이 붙는다(이슈 키는 연번이라 추측이 쉽다). 선택 규칙을 `brief.rendered_field_items` 한 곳에 두고
   조립과 검증이 같은 목록을 본다. `voc:` 는 **제품코드까지 대조**한다 — 안 하면 남의 제품 필드 이력이
   이 제품의 근거로 선다.
6. **`paper:` 해석이 최근 3행만 봤다.** `scholar_query` 는 성격 태그·mechanism 이 쌓이면 바뀌어
   `args_hash` 마다 새 행이 생긴다 → 몇 행만 보면 **예전 패널의 인용이 뒤늦게 dangling** 이 된다.
   한 타깃의 필드 호출은 소수라 행 수를 자르지 않는다.
7. **정본 "상위 카테고리 3" 을 '응답 앞 3건' 으로 읽었다.** 같은 카테고리가 세 줄을 차지하면 VOC 의
   넓이가 사라지고 한 이슈가 필드 이력 전체처럼 보인다.
8. **`req:` 가 `waived` 요구까지 풀었다.** 정본 §4.3.1 은 범위를 못 박는다 —
   "`status ∈ candidate|confirmed` 에 있는지 확인하고 없으면 dangling + 등급 강등". `waived` 는 과제가
   **포기한** 요구라 인용 근거가 아니다. 같이 — UNIQUE 가 `(project_id, kind, name)` 이라 같은 이름이
   kind 마다 있을 수 있는데 정렬이 없었다(등급이 흔들린다).
9. **`req:` 를 무조건 측정으로 올렸다.** 정본 §2.8b — "`standard` kind 만 예외이며 등급은 측정이 아니라
   문헌·규격". 규격 번호 인용은 실측이 아니다. 이 예외가 없으면 요구 행 하나만 등록돼 있어도 전 클러스터가
   측정으로 올라 `all_heuristic` 안전장치와 `[가설 단계]` 표기가 사실상 죽는다. 등급 함수가 payload 를
   받지 않으므로 `resolve_cites` 가 `req_kind` 한 칸만 행에 싣게 했다.

**시험을 쓰다가 렌즈가 못 본 걸 하나 더 찾았다 — `POST /projects` 가 제품 3열을 조용히 버렸다.**
정본 §8.2.3 계약은 `product_code`·`product_refs_json`·`predecessor_product_code` 를 받는데
`ProjectBody` 에 그 필드가 없었다. pydantic 이 extra 를 무시하므로 정본대로 보낸 클라이언트는
**오류 없이** 제품 연결 없는 과제를 얻고, E10 은 영영 `[제품 연결 미등록]` 한 줄이다. `PATCH` 는 세 열을
받으므로 도달 불가는 아니었다(처음에 그렇게 적었다가 정정했다). 대표값 규칙은 §8.2.4 를 따랐다 —
`kind='product_code'` 인 첫 행이 대표값이고(`ra_model` 값은 RA 엔티티 코드라 조회 키가 아니다)
계보 과제가 있으면 그 과제의 `product_code` 가 전작으로 채워진다.

**기각한 지적 — `[조회 불가]` 줄이 5줄 상한 밖이라 블록이 7줄까지 커진다(3렌즈 지적).** 정본이 그렇게
적는다 — "합쳐 최대 `risk_field_evidence_lines`(5)줄" 은 근거 줄이고 `[조회 실패: <tool>]` 은
"블록 끝에 한 줄이 남는다" 로 따로 적혀 있다. 코드가 정본과 같다.

**재현하지 못해 계약 고정으로만 둔 것 — 같은 이름 다른 kind 의 결정론.** 인덱스가 우연히 kind 순서를
주고 있어 고치기 전에도 시험이 통과한다. 잠재 비결정이라 `ORDER BY kind` 로 못 박고 시험은 계약
가드로 남겼다(다른 8건은 전부 고치기 전에 실제로 깨지는 것을 확인했다).

**검증.** `pytest` **1164 passed, 2 skipped**(시험 13건 추가) · `ruff` 통과 · `pnpm build` 통과.

### D23. E10 후속 4건 — 검증 없는 최고 등급과 남의 시야 (2026-09-26)

D22 가 백로그로 남긴 6건 중 정본 결정이 필요 없는 4건을 닫고 2건을 기각했다.

- **`character.evidence_grade_of` 가 존재 검증 없이 측정을 줬다.** `{ok: True, grade_ok: True}` 를
  모든 파싱 가능 참조에 부여하고 있었다. `git show` 로 확인하니 **`inc:` 는 E10 전에도 같은 구멍**이었고
  E10 이 `req:`·`voc:` 를 같은 구멍에 통과시킨 것이다 — 내가 만든 게 아니라 **넓힌** 것이다.
  구분선은 '지역에서 확인할 수 있는가' 다. `req:`·`voc:` 는 store 만 있으면 확인되므로 확인한다.
  `inc:` 는 RA 사고라 경로가 없고 정본은 채널 부재를 강등 사유로 보지 않는다(`_resolve_one` 의
  `verified=False` 와 같은 규칙). `p:`·`e:`·`c:` 는 스냅샷 스코프가 없어 그대로 센다 — 스코프 없이
  강등하면 파트를 인용한 성격 행이 전부 경험칙으로 떨어진다(과대 교정이 과소만큼 나쁘다).
  `store` 를 안 주면 예전 동작이라 다른 호출자는 안 바뀐다.
- **자격이 서비스 PAT 하나뿐이었다.** `from_settings` 는 `portal_pat` 을 받는데 **호출자 둘이 안
  넘기고 있었다.** 서비스 시야로 부르면 시야 밖 데이터는 오류가 아니라 **빈 배열**로 와서
  `[VOC 0건]` 으로만 보이고 24 h 재사용된다 — 없는 리스크가 굳는다. `for_target` 을 두고 러너·로스터와
  같은 (b)→(a) 순서를 쓴다. **(c) 요청자는 쓰지 않았다** — 브리프를 여는 MCP 경로의 `actor` 는
  게이트웨이 신고값이고 정본이 미검증이라 못 박았다(§6.11). 그걸 자격 선택에 쓰면 남의 PAT 를 고른다.
- **인젝션 적중이 사람에게 안 닿았다.** E10 만 `render.sanitize_source_text` 를 직접 불러 `on_suspect`
  가 빠졌다 — 자리표시자로 가려지긴 하니 **방어는 작동하는데 아무도 시도를 모른다**. `_q` 경유로 바꿨다.
  같이 `_cut` 을 쓴다 — 외부 문자열의 줄바꿈을 접지 않으면 남의 VOC 한 줄이 두 줄이 되어 줄 수 상한을
  우회한다(적중 시험에 그 단정을 같이 넣었다).
- **지표가 양방향으로 틀렸다.** 분자가 `dangling` 인용까지 세어 지어낸 `voc:` 로 값이 부풀 수 있었고
  (`rr_claim_refs.dangling` 열이 있는데 안 봤다), 분모는 `product_refs_json` 이 비어 있지 않기만 하면
  셌다 — `ra_model` 만 든 과제는 조회 키가 0건이라 E10 이 **구조적으로 불가능**한데 분모에 들고,
  전작 코드만 있는 과제는 E10 이 도는데 빠졌다. `brief.product_keys_of` 를 순수 함수로 떼어 조립과
  지표가 같은 판정을 쓴다.

**기각 2건.** `registry._is_stronger` 가 새 등급표로 낸 값을 옛 `grade_at_decision` 과 비교한다는
지적은 사실이지만 **방향이 반대**다 — 이번 변경은 등급을 내리므로(standard 예외·검증 추가) delta 가
음수가 되어 dismissed 클러스터가 되살아나지 않는다. 게다가 이 앱은 실데이터를 한 번도 안 돌렸으므로
기존 `req:`·`voc:` 인용이 애초에 없다. `all_heuristic` 안전장치가 죽는다는 지적은 정본 §0.2.1 (5)
("`req:` 와 `voc:` 는 측정")의 설계 그대로라 코드 결함이 아니다.

**검증.** `pytest` **1168 passed, 2 skipped**(시험 4건 추가, 전부 고치기 전 깨짐) · `ruff` 통과.

### D24. 외부 근거의 quote 대조 — 대조 기준이 그 줄이어야 한다 (2026-09-26)

`canonical_text_for` 에 `voc:`·`paper:`·`req:` 분기가 없어 §4.4.2 quote 대조가 건너뛰어지고 있었다.
다른 스킴 다수도 그러하므로 '이 셋만의 결함' 은 아니다. 그런데 이 셋은 다르다 — **VOC 원문과 논문
초록은 사람이 눈으로 확인할 방법이 없다.** 지어낸 인용문이 가장 잘 먹히는 자리다.

**설계에서 중요한 건 대조 기준을 무엇으로 두느냐였다.** 좌석이 읽은 것은 응답 원문이 아니라 **E10 줄**
이다(위생·절단을 통과한 `«…»` 표기). 기준을 원문으로 두면 좌석이 못 본 문장을 인용해도 통과하고,
줄 형식을 두 곳에서 각자 만들면 조금만 달라져도 대조가 늘 실패한다. 그래서 줄을 만드는 곳을
`brief.field_evidence_line` 한 곳으로 모으고 조립·대조가 그 함수를 같이 쓴다
(`rendered_field_items` 를 한 곳에 모은 것과 같은 이유다 — 인용 검증은 조립과 같은 규칙이어야 한다).

`req:` 는 **한계값**이 정규 표기다. 좌석이 `req:thickness` 를 인용하며 `0.3` 대신 `0.5` 라 적는 것을
잡는다 — 그 실패가 §4.4.2 가 존재하는 이유다. `standard` kind 는 대조할 한계가 없어 조항·제목이
표기다(§2.8b 가 그 kind 를 '대조하지 않는다' 로 적는 것과 같은 결).

**남은 하나는 정본 결정이다.** 제품코드가 여럿일 때 정본이 "`product_code` **값들**"(복수)과
`get_top_issues(product_code, 90d)`(단수)로 갈려 있다. 제품마다 부르면 호출 예산(§9.2)과 24 h 캐시
행 수가 제품 수에 비례해 늘고 5줄 상한을 제품들이 나눠 쓰게 된다 — 값을 지어내지 않고 6장에
선택지 3개로 올렸다.

**검증.** `pytest` **1170 passed, 2 skipped**(시험 2건, 둘 다 고치기 전 깨짐) · `ruff` 통과 · `pnpm build` 통과.

### D25. 호출 시점 도구 이름 해석 — probe 가 찾은 것을 호출이 못 찾았다 (2026-09-26)

정본 §2.13.2 는 두 문장으로 적는다 — 발견은 suffix 매칭이고, "그렇게 얻은 **게이트웨이 실이름**(접두
포함형 그대로)을 **호출 인자와** `rr_snapshot_calls.tool` 에 적는다". 통과 기준 (23)(a)가 그 둘을 함께
검사한다. 코드는 앞 문장만 지켰다 — `tool_matches` 는 probe 에서만 쓰이고 어댑터는 맨이름으로 불렀다.

**왜 조용한가.** 게이트웨이가 이름 충돌로 접두를 붙이면 probe 는 suffix 로 찾으니 '도구 있음 ·
reachable' 로 보고한다. 실패는 어댑터 쪽에서만 나고, 오류 메시지에 '이름' 이라는 단서가 없다.
`job_status` 처럼 흔한 이름은 다른 백엔드가 같은 이름을 노출하는 순간 **양쪽 다** 접두형으로 바뀐다.

**설계에서 고민한 네 가지.**

1. **어디서 해석하나.** `McpHttpClient.call` 에 넣으면 원장에는 맨이름이 남아 정본의 뒤 문장을 못 지킨다.
   `CallRecorder.call` 은 호출과 기록을 한 자리에서 하므로 두 문장을 동시에 만족한다. 모든 어댑터가
   이 한 곳을 지나므로 전사 집계(3a)까지 자동으로 덮인다.
2. **규칙을 두 곳에 두지 않는다.** `resolve_tool_name` 을 `adapters/base`(채널 층)로 내리고 `registry` 가
   그것을 import 한다(`tool_matches` 도 함께 내렸다 — 판정이 갈리면 probe 가 찾은 도구를 호출이 못 찾는다).
   `base` 가 `registry` 를 import 하면 순환이므로 방향이 이쪽뿐이다.
3. **계약 검사는 맨이름이다.** `check_contract` 표의 키가 맨이름이라 실이름으로 찾으면 전부 '계약 없는
   도구'(`contract_ok=None`)가 되어 **검사가 조용히 꺼진다.** 시험으로 못 박았다 — 이건 고치면서
   새로 만들 수 있었던 회귀다.
4. **이름 목록을 누가 받아 오나.** 처음에 `capture_all` 안에서 받아 왔는데 **E2E 스모크가 잡았다**
   ("E2E 스모크는 외부 호출을 하지 않는다"). 캡처 경로가 스스로 발견 요청을 내보내면 그 계약이 깨진다.
   자격을 아는 곳은 `clients_from_settings` 이므로 거기서 받아 `channels['tool_names']` 로 넘긴다
   (토큰·주입 클라이언트를 이미 들고 있고 60 s 캐시를 탄다). 시험의 가드가 설계를 고친 사례다.

**두 원장의 규칙이 다르다 — 의도한 것이다.** `rr_snapshot_calls.tool` 은 **실이름**(정본 요구),
`rr_brief_calls.tool` 은 **맨이름**이다. 후자의 `tool` 은 24 h 재사용 키이자 `voc:`·`paper:` 해석
키이므로, 실이름을 적으면 게이트웨이가 접두를 붙이는 날 캐시가 통째로 무효가 되고 이미 인용된
`voc:` 가 전부 dangling 이 된다(읽는 쪽 `narrative.field_evidence` 는 맨이름으로 찾는다).
호출만 실이름으로 나간다.

**검증.** `pytest` **1174 passed, 2 skipped**(시험 4건, 전부 고치기 전 깨짐) · `ruff` 통과.

### D26. 스키마 required 2키 — 미뤄 둔 사유가 틀렸고 진짜 구멍은 다른 데 있었다 (2026-09-26)

`primary_source`·`context` 가 `properties` 에만 있어 두 키 없는 IR 도 스키마를 통과했다. 2026-09-04 에
미뤄 둔 사유는 "무효 픽스처 6종의 거부 사유가 '원래 잡으려던 결함' 에서 '새 필수 키 누락' 으로 바뀔
위험" 이었다. **그 사유가 틀렸다** — `jsonschema.iter_errors` 는 모든 오류를 내므로 새 필수 키 오류가
추가될 뿐 원래 결함 오류가 사라지지 않는다. `validate()`(첫 오류만) 를 쓰고 있었다면 맞는 걱정이었다.

**대신 대조하다 진짜 구멍을 봤다 — 시험이 '거부됐는가' 만 보고 '왜' 를 안 봤다.**
`test_invalid_fixtures_are_rejected` 는 `assert list(v.iter_errors(obj))` 다. 어휘를 좁히거나 필수 키를
더하면 무효 픽스처가 새 사유로도 거부되므로 이 시험은 계속 초록이고, 원래 결함 검사가 죽었는지 알 수
없다. 이 리포에는 항진명제 시험이 버그를 가린 전례가 이미 있다(`CORPUS_TOOLS` 순서 역전 ·
`CONTEXT_KIND='dyna'` — 시험이 코드를 코드와 비교하고 있었다).

그래서 **픽스처 이름의 토큰이 실제 오류의 경로·문구·validator 에 나타나야 한다**는 불변식을 세웠다.
이름을 명세로 쓰는 셈이고 유지비가 없다(픽스처마다 기대 사유 표를 두지 않는다). 첫 실행에서
`invalid_facet7` 하나를 잡았다 — 이름의 꼬리 숫자가 개수라(`facet7` = 8축이어야 하는데 7축) 토큰이
`facets` 와 안 맞았다. 꼬리 숫자를 떼도록 고치고 오류 경로가 `character/facets` 인 것을 확인했다.

**픽스처 편집은 텍스트로 했다** — 지난번 JSON 라운드트립으로 8,000 줄을 재포맷한 CLAUDE.md §3 위반을
반복하지 않으려고 `"partial"` 줄 앞에 최상위 키 두 줄만 끼웠다(9파일 14줄, 재포맷 0).
값은 실제 `build_ir` 산출과 같게 뒀다(`primary_source: "mcad"` · `context: {"corpus_usage": null}`) —
실산출을 검증하는 `test_ir_schema_contract.py` 가 함께 초록인 것으로 확인했다.

**검증.** `pytest` **1178 passed, 2 skipped** · `ruff` 통과.

### D27. 정본 통과 기준을 코드와 대조하다 — 죽어 있던 지표 화면 (2026-09-26)

1장의 코드 항목이 전부 정본 결정·실자격 대기로 막혔으니, 이 세션에서 수확이 가장 컸던 방법을 계속 썼다 —
**정본의 번호 붙은 통과 기준을 코드와 기계 대조.** `GET /api/refs` 404 와 도구 이름 전멸이 둘 다 그렇게
나왔다(둘 다 '정본이 명시한 통과 기준인데 코드가 안 함' 이었다).

P6 통과 기준 9항의 식별자를 코드·시험에 전수 대조하니 `표본 부족` 이 **app 0 · test 0** 이었다.
따라가 보니 더 큰 게 있었다 — **`getMetrics` 가 API 클라이언트에만 있고 아무도 부르지 않는다.**
정본 §9.7 산출물은 "지표 대시보드(앱 `TargetPage` 하단 '품질' 카드) · '루프 작동' 배지" 를 요구한다.
2026-09-25 의 '화면 5종' 점검이 이 경로를 놓쳤다 — 그때는 클라이언트가 **부르는** 경로의 서버 존재를
검사했고(`test_client_contract.py`), **부르지 않는** 선언은 검사 대상이 아니었다. 죽은 경로의 반대
방향이다.

**서버는 이미 다 하고 있었다.** 배지 판정은 `_badge_rows` 가 `rr_metrics` 행으로 낸다 —
`loop_ok` · `loop_bottleneck_{labels,queue,coverage}` · `label_ingest_wired`. 그래서 화면이 임계를 다시
계산하지 않게 하는 것이 설계의 핵심이었다(계산이 두 곳에 있으면 갈린다). 카드는 값을 읽어 배지로만 바꾼다.

**'표본 부족' 을 0 으로 두지 않는다.** 정본 P6 (2)가 `n<5 는 '표본 부족' 표기` 라 적고 §4 원칙이
"null 은 미측정이지 0 이 아니다" 라 적는다. 서버는 `value=null` + `n` 으로 내고 있었는데 그 구분을
보여 줄 화면이 없었다. 0 으로 렌더하면 '지표가 나쁘다' 로 읽힌다 — 없는 리스크의 거울상이다.

**계약 표류 1건이 같이 나왔다.** `MetricRow.value` 가 `number` 인데 서버는 `null` 을 보낸다.
타입을 `number | null` 로 고치자 `tsc` 가 새 카드의 두 자리를 바로 짚었다 — 타입을 먼저 고친 덕에
런타임에서 `null > 0` 이 조용히 false 가 되는 일을 피했다.

**검증.** `pytest` **1179 passed, 2 skipped**(시험 1건) · `ruff` 통과 · `pnpm build` 통과.

### D28. 통과 기준 식별자를 자동 전수 대조했다 (2026-09-26)

'품질' 카드가 통과 기준 대조에서 나왔으니 그 방법을 **자동화해 전수로** 돌렸다 — 정본의 번호 붙은
통과 기준 246줄에서 백틱 식별자 451종을 뽑아 이 리포의 `*.py`·`*.ts*`·`*.json` 전체와 대조했다.
흔적 없는 것 26종. 그중 20종은 엔진(`_RISK_READ_TOOLS`·`_RESCREEN`·`prompt_fn` …)·허브
(`manifest_validator`)·게이트웨이(`per_user_sso`·`list_sessions`) 소관이라 걸러 냈고 6종이 남았다.

**고친 것 — 오류 코드 표기 2건.** 코드가 `evidence_ref_required`·`family_key_mismatch` 인데 정본은
`evidence_required`(3회)·`family_key_differs`(2회)로 적고 다른 표기는 정본에 **0회**다. 사소해 보이지만
**오류 코드는 계약**이다 — 클라이언트가 문자열로 분기하므로 표기가 갈리면 '근거 없이 verified 를 찍는
것을 막는 가드' 가 화면에서 '알 수 없는 오류' 로 보인다. 가드 자체는 있었으니 기능이 아니라 계약의
표류였다. `family_key` 가드는 **두 곳**이었다(직접 병합 + 큐레이션 큐 병합) — 한 곳만 고치면 같은 버그가
남는다. `note_required` 는 원래 정본 표기였다(내 첫 grep 이 `head -10` 에 잘려 없다고 봤다).

**같이 드러난 것 — `required` 변경의 영향 범위를 내가 좁게 봤다.** D26 에서 `tests/fixtures/rr_ir/` 만
손봤는데 `tests/fixtures/diff_pairs/` 7종도 같은 스키마로 검증된다. 시험이 잡았다
(`test_pair_fixtures_validate_against_rr_ir_schema`). 이번엔 디렉터리를 고르지 않고 **IR 모양인 픽스처를
전수로** 찾아 처리했다 — 조건은 `ir_hash`·`nodes` 키 보유다. 교훈은 '한 디렉터리를 보고 다 봤다고 하지
말 것' 이고, 그걸 잡아 준 것이 스키마 대조 시험이라는 점이 중요하다.

**클라이언트 죽은 선언도 반대 방향으로 전수 점검했다.** `test_client_contract.py` 는 클라이언트가
**부르는** 경로의 서버 존재를 본다 — **부르지 않는 선언**은 대상이 아니다('품질' 카드가 그 구멍에서
나왔다). 56종 중 4종이 미사용이었고 나머지 셋은 빠진 기능이 아니었다 — `getSnapshotNodes`·
`getSnapshotEdges` 는 화면이 `part=ir` 로 이미 그려 중복이고, `completePanel` 은 엔진·러너 콜백이라
UI 가 부르면 안 되며, `exportJsonl` 은 운영자 이관 경로로 정본 §8.2.4 에 화면이 없다. 다음 세션이 다시
조사하지 않도록 체크리스트에 결론을 적었다.

**남긴 4건**은 체크리스트 2장에 사유와 함께 올렸다. 중요한 둘은 `warnings.ambiguous_bridge_key`(조인 키
다의일 때 엉뚱한 브리지가 조용히 생긴다)와 `missing.mcad_capture_failed`(요약 응답으로 노드·엣지를
지어내지 않고 mcad 를 통째로 버려야 한다) — 둘 다 '없는 리스크' 계열이라 다음에 먼저 볼 것이다.

**검증.** `pytest` **1181 passed, 2 skipped** · `ruff` 통과 · `pnpm build` 통과.

### D29. 잘린 트리로 IR 을 지어내던 것 — 그리고 내가 적어 둔 범위가 틀렸다 (2026-09-29)

D28 이 남긴 2건을 착수하면서 **먼저 범위가 틀렸음을 확인했다.**

- **①은 "경고가 없다" 가 아니라 "브리지 자체가 없다" 였다.** `part_mesh_map` 을 아무도 부르지 않는다 —
  `mcad.py:16` 주석이 "캡처가 한 번도 부르지 않으므로 게이트에서 뺀다" 고 적어 둔 그대로다.
  `kind='bridge'` 엣지를 만드는 코드가 0건이라 `join_key`·`bridge_stale`·`ambiguous_bridge_key` 가
  전부 없고, 그 엣지를 읽는 `sameas` 2단계 `pid_map` 과 `diff` 의 `cross.bridge_stale` 이 **구조적으로
  죽어 있다**. 정본 MCP 3 예산(§2.13.3)은 `job_status`·`part_mesh_map`·`inspect_report` 인데 코드는
  `job_status`·`interface_graph` 둘만 부른다 — `inspect_report` 의 `source_inconsistent` 교차 검증도 없다.
  체크리스트에 정확한 범위로 다시 적었다. 이건 P2 산출물 한 덩이라 별도 단위로 한다.
- **②는 플래그가 없는 게 아니라 데이터를 지어내고 있었다.** 코드는 `tree_truncated` 를 세우고도 계속
  진행해 `list_parts` 로 노드를 만든다. `list_parts` 는 500 으로 클램프하면서 truncated 플래그를 주지
  않으므로 **501번째부터 조용히 사라진 IR 이 '정상' 으로 동결된다.** 픽스처로 실측했다 — 요약이 리프
  620건이라 말하는데 IR 은 파트 2건으로 섰고 `missing` 은 아무 말도 하지 않았다. 사라진 파트가 낀
  간섭이 함께 사라지므로 '없는 리스크' 다.

**정본이 왜 버리라고 하는지가 구현을 정했다.** "요약만으로는 노드·엣지를 만들 수 없기 때문" 이고,
§2.2 missing 표는 `<kind>_capture_failed` 가 **`<kind>_absent` 와 함께 선다** 고 적는다. 그 '함께' 가
핵심이었다 — `mcad_absent` 가 서야 형상층 게이트가 §2.12 대로 `pass=null` 로 내려가고, 그러지 않으면
**노드 0건인데 위반 0건이라 G3 가 통과로 읽힌다.** 통과 조건을 만족시키는 가장 나쁜 방법이 '데이터를
없애는 것' 이라는 점에서 앞서 고친 결함들과 같은 계열이다. 소스 행은 남긴다 — 어느 앱을 어떤 인자로
불렀고 무엇이 왔는지가 원장에 있어야 사람이 원인을 본다.

§2.2 degraded 표가 이 경로를 **"실무 어셈블리에서는 이 경로가 상시 경로다"** 라고 적는다. 서비스 PAT
없이 도는 첫 실캡처에서 바로 걸리는 자리라, 실데이터가 들어오기 전에 막는 것이 맞았다.

**같이 드러난 표류 — `missing` 키가 셋으로 갈려 있었다.** 코드 9키 · 스키마 7키 · 정본 봉투 11키.
정본으로 통일하고 IR 모양 픽스처 16종을 실산출에 맞췄다(D26·D28 에서 배운 대로 디렉터리를 고르지 않고
전수). 그리고 `missing.update({k: v for k, v in missing_declared.items() if k in missing})` 가
**기본값 있는 키만** 통과시킨다는 사실을 주석으로 못 박았다 — 새 플래그를 기본값에 안 넣으면 어댑터가
세운 사실이 봉투에 조용히 안 실린다. 이번에 그 함정을 직접 밟았다.

**검증.** `pytest` **1184 passed, 2 skipped**(시험 3건, 전부 고치기 전 깨짐) · `ruff` 통과.

### D30. 브리지 — 만드는 쪽이 없어 어긋남이 드러나지 않았다 (2026-09-30)

D29 가 정정한 범위대로 브리지 한 덩이를 구현했다. `part_mesh_map` 을 정본 MCP 3 예산에서 부르고
`kind='bridge'` 엣지를 mcad part ↔ dyna pid 로 잇는다. 도구 집합도 정본 6종으로 되돌렸다(코드는 5종이고
주석이 "캡처가 한 번도 부르지 않으므로 게이트에서 뺀다" 고 적어 두었다 — 이제 부른다).

**설계에서 정한 것 넷.**

1. **엣지를 누가 만드나.** mcad 가 먼저 캡처되고 dyna pid 를 모른다. 그래서 mcad 는 `a_canon_key` +
   **`b_pid`** 로 내고 `ir_builder` 가 dyna pid 노드에서 끝점을 푼다 — `dyna:<sha8>:<pid>` 를 mcad 가
   스스로 만들 수 없기 때문이다(K파일 sha 를 모른다). 못 풀면 기존 `ambiguous_edge_endpoint` 경로로
   빠진다 — 없는 노드를 가리키는 엣지를 만들지 않는다.
2. **조인 키는 식별자이지 경로가 아니다.** 처음에 `step_file + '/' + source_name` 으로 canon_key 를
   지어냈다가 시험이 잡았다(MCP 폴백에서 브리지 0건). 경로로 만든 후보를 먼저 찾고, 안 맞으면
   `source_name` 을 **경로 꼬리**로 대조한다. 후보가 둘 이상이면 고르지 않는다 — 엉뚱한 파트를 dyna pid 에
   묶는 것이 브리지를 안 만드는 것보다 나쁘다.
3. **다의 키는 그 키만 건너뛴다.** 정본은 "같은 `(step_file, source_name)` 이 2행 이상이면 브리지를
   만들지 않고 `ambiguous_bridge_key`" 다. 표 하나가 전부를 죽이지 않게 키 단위로 막았다.
4. **degraded 코드를 지어냈다가 되돌렸다.** `part_mesh_absent` 를 추가했는데 스키마 enum 가드 시험이
   잡았다 — 정본 degraded 어휘에 mesh 관련 코드가 없다. 실패는 경고로만 남긴다(`interfaces_unreadable`
   과 같은 처리). 브리지 0건 자체가 pid_map 을 건너뛰게 만든다.

**곁에서 나온 것 셋 — 둘은 '서로 맞춰진 오류' 였다.**

- **MCP 폴백에서 프로젝트 접두가 안 벗겨졌다.** MCP `project_tree` 응답에 `project` 키가 없어(§2.5.1 실측)
  소스 카드에 `project_name` 이 없으면 이름이 아예 없다. 그때 접두가 남아 같은 파트의 canon_key 가
  **채널마다 달랐다**(`mcad:/sif-e2e/…` vs `mcad:/…`). same-as 3단계(`exact_path`)가 REST 스냅샷과 MCP
  폴백 스냅샷 사이에서 통째로 빗나가고 ckey 가 '과제 무관' 이라는 정의도 깨진다. 정본이 "path 는
  `/{project}/…` 로 시작하므로 반드시 제거한다" 고 불변식을 적어 두었으므로 이름을 몰라도 첫 구간을 뗀다.
- **`sameas` 의 브리지 attrs 자리가 정본과 달랐다.** 소비처는 `attrs.bridge_stale`·`attrs.join_key`
  평면을 읽고 시험 헬퍼도 같은 평면을 만들었다 — **둘이 서로 맞춰져 있었으므로 시험은 늘 초록이었다.**
  정본 자리는 `attrs.dyna.bridge` 다. 만드는 코드가 없어 이 어긋남이 드러날 방법이 없었다(항진명제 쌍의
  세 번째 사례다 — `CORPUS_TOOLS`·`CONTEXT_KIND` 에 이어). 게다가 없는 키는 falsy 라 옛 소비처는
  **stale 을 항상 '아님' 으로 읽었다** — 브리지가 생기는 날 stale 가드가 없는 채로 돌 예정이었다.
- **`bridge_stale` 판정이 정본 내부 불일치다.** §2.6.2 는 false 를 "kfile 일치 **그리고** pid 최대값 ≤
  행 수" 로 적는데 `mesh_report` 가 §2.13.3 의 MCP 3 예산에 없다. 없는 근거로 'stale 아님' 이라
  단정하지 않았다 — 그게 pid_map 을 틀린 대응으로 1.0/auto 확정하는 길이다. 지금은 항상 stale 이고
  `kfile_checked: false`·`pid_within_rows` 를 attrs 에 남겨 **왜** stale 인지 보이게 했다. 선택지 3개를
  체크리스트 6장에 올렸다(값을 지어내지 않는다).

**내가 만든 실수 하나.** stale 식을 `True if not pid_ok else stale` 로 꼬아 써서 의도와 **반대로**
동작했다(pid 가 맞으면 stale 을 내렸다). 시험이 바로 잡았고 `stale = not (kfile_checked and pid_ok)` 로
평평하게 고쳤다 — 조건을 꼬면 주석이 맞아도 코드가 틀린다.

**검증.** `pytest` **1190 passed, 2 skipped**(시험 6건, 전부 고치기 전 깨짐) · `ruff` 통과.

### D31. §4.8 무효화 — 기계는 다 있고 부르는 곳이 시험뿐이었다 (2026-09-30)

D28 이 남긴 ④(`subject_ckeys` 를 `resolve_ckey` 로 해석하는지)를 확인하러 갔다가 훨씬 큰 것을 봤다.
`registry.invalidate` 는 세 원천(subject ckeys · `cited_ckeys` · `cites[].ckey`)에 전부 `resolve()` 를
제대로 적용한다 — ④는 이름만 다른 것이고 구현돼 있었다. 문제는 **그 함수를 부르는 곳이 시험밖에
없다**는 것이었다. `planner.apply_carry_over` 도 같다. `create_target` 은 §4.8 을 한 줄도 하지 않는다.

**그래서 §4.8 전체가 죽어 있었다** — stale·superseded·unraised·carried 가 한 번도 안 쓰였다.
시험이 함수를 직접 부르니 초록이었고, 브리지와 똑같은 모양이다: **시험이 함수를 부르는 것은 그 함수가
동작한다는 증거이지 시스템이 그것을 쓴다는 증거가 아니다.** 이 세션에서 세 번째로 같은 함정을 봤다
(항진명제 쌍 → 죽은 REST 경로 → 배선 없는 모듈).

**설계에서 가장 중요했던 결정은 '모를 때 무엇을 하는가' 였다.**
`changed_ckeys` 를 빈 집합으로 넘기면 어떻게 되는지 코드로 확인했다 —
`invalidate` 의 `own & changed` 는 공집합이라 **stale 0건**, `apply_carry_over` 의 '인용 ckey ∩ 변경
ckey = ∅' 은 항상 참이라 **전 좌석 carried** 다. 즉 빈 집합은 "아무것도 안 바뀌었으니 다 승계하라" 와
같은 말이고, 그건 재검증 없이 통과시키는 쪽이다 — 이 세션에서 계속 나온 '없는 리스크' 의 또 한 모습이다.
그래서 diff 가 없으면 1단계(닫기)만 하고 3·4·5 를 **건너뛰며 사유를 남긴다**. 모르는 값을 0 으로 적지 않는다.

**정본 문면 하나를 의도적으로 좁혔다.** §4.8 2 는 "`diff(S, S′)`(있으면 재사용, **없으면 생성**)" 이라
적지만 **재사용만** 한다. 타깃 생성이 diff 를 부수효과로 만들면 게이트 차단·비교 불가로 409 가 날 수
있고, 그러면 타깃이 안 열린다 — 심사를 시작하려는 사람이 diff 실패로 막히는 건 잘못된 실패 방향이다.
생성은 사람이 `POST /diffs` 로 한다. 좁힌 사실과 이유를 체크리스트에 적었다.

**순서가 중요했다.** §4.8 은 로스터 고정 **뒤**에 돌아야 `carried` 가 T′ 좌석 행에 앉는다. 그리고 전부
같은 트랜잭션 안이다(`store.tx()` 가 재진입 안전하다) — T′ 는 생겼는데 T 가 안 닫힌 상태를 만들지 않는다.

**남은 것.** E5 의 `[변경 주체 — 재검증 대상]`·`[미변경 주체]` 접두(§4.8 3)는 아직 없다. stale 표기가
이제 실제로 쌓이기 시작하므로 그 값을 브리프가 읽는 것이 다음 자리다.

**검증.** `pytest` **1193 passed, 2 skipped**(시험 3건, 전부 고치기 전 깨짐) · `ruff` 통과 · `pnpm build` 통과.

### D32. E5 변경 주체 접두 — 모름을 '안 바뀜' 으로 쓰지 않는다 (2026-09-30)

D31 이 stale 표기를 실제로 쌓기 시작했으니 브리프가 그 값을 읽게 했다. `stale_json` 이 브리프의
등록부 조회 열(`_REGISTRY_COLS`)에 **아예 없었다** — 값이 있어도 읽는 쪽이 없었다.

**정본 문면 하나를 좁혀 읽었고, 그게 이 작업의 요점이다.** §4.8 3 은 "E5 는 stale 클러스터를
`[변경 주체 — 재검증 대상]` 접두로, **나머지를 `[미변경 주체]`** 로 싣는다" 고 적는다. 문면대로 모든
비-stale 선례에 `[미변경 주체]` 를 붙이면, 판정이 아예 없던 선례까지 '안 바뀜' 으로 적힌다.
stale 표기는 `stale_json[T′]` 이고 그 판정은 **같은 과제의 직전 타깃에만** 일어난다 — 다른 과제·다른
계보에서 온 선례에는 항목이 없다. 그것을 `[미변경 주체]` 로 적으면 **확인하지 않은 것을 확인했다고
적는 것**이다. 그래서 항목이 없으면 접두를 붙이지 않는다. §4.8 의 '나머지' 는 그 절이 실제로 판정한
클러스터로 읽는 것이 §4.8 의 문맥(전부 T→T′ 한 과제 안의 이야기)과도 맞는다.
이 세션에서 계속 나온 규칙의 또 한 적용이다 — null 은 미측정이지 0 이 아니다.

**접두는 겹쳐 붙인다.** §5.6.1 의 2종(`[재검토]`·`[사람 제기·검증 대상]`)과 §4.8 의 2종은 서로를
참조하지 않고 **다른 사실**이다. 변경 주체를 먼저 둔다 — 재검증이 필요한지가 좌석이 먼저 알아야 할
사실이고, 그다음이 누가 왜 올렸는지다.

**예산을 실측했다.** 접두 길이는 17자(변경)·9자(미변경)이고 E5+ 700자에서 최악(선례 전부 stale)일 때
4줄→3줄이 된다. 정본이 요구한 대가이고, 선례 전부의 주체가 바뀌었으면 실리는 줄이 줄어드는 쪽이
맞다(그 선례들은 그대로 믿을 게 아니라 재검증 대상이다). D18 의 산술 시험이 함께 초록인 것으로 확인했다.

**남긴 판단 하나.** E5− 에는 붙이지 않았다. §4.8 은 "E5 는" 이라 적고 E5− 도 E5 의 블록이지만,
§5.6.1 의 E5− 줄 형식에 접두 자리가 없고 300자·6줄 상한을 접두가 먹는다. 그런데 기각된 선례의 주체가
바뀐 사실은 **오히려 더 중요할 수 있다** — 옛 형상에서 기각한 리스크가 지금은 실재할 수 있다.
값을 지어내지 않고 선택지 3개를 체크리스트 6장에 올렸다.

**검증.** `pytest` **1195 passed, 2 skipped**(시험 2건, 둘 다 고치기 전 깨짐) · `ruff` 통과.

### D33. 포털 PAT 을 브라우저가 발급한다 — 붙여넣기를 없앤 곳 (2026-09-30)

사용자가 "자동 연결까지 손보기" 를 골랐다(정본 §10 #17 ② 결정 사항이었다). 먼저 실측으로 상태를 잡았다 —
**토큰 연결은 이미 한 번 성공한 적이 있다.** 배포된 `risk_review.db` 에 과제 4건·스냅샷 4건(노드 5·엣지 6)·
캡처 호출 77건(MCP 52/52 · REST 10/25 성공)이 2026-09-01 자로 남아 있고 `_user_credentials` 에
`scopes:["read"]` PAT 이 등록돼 있었다. 타깃·패널·finding 은 0 이다 — **캡처는 실제로 됐고 심의는 안 됐다.**
내가 여러 번 말한 "실제 STEP 을 한 번도 읽지 않았다" 는 **틀렸다**(체크리스트 2장 표기도 그 점에서 낙관적이
아니라 비관적으로 틀렸다). 그 PAT 은 2026-10-01 01:39 만료다.

**왜 앱 서버가 대신 발급할 수 없나.** 포털 `POST /auth/pat` 은 `require_csrf`(deps.py, double-submit)를
지나야 한다 — **브라우저의 `hwax_csrf` 쿠키와 `X-CSRF-Token` 헤더가 일치**해야 하고 Bearer 는 면제되지
않는다. 그래서 앱이 사용자 heax 토큰을 들고 있어도 발급이 안 된다. 포털에 토큰 교환 엔드포인트도 없다
(`/auth/ste/credential` 이 "로그인 사용자용 하위 자격 발급" 선례이지만 hwax-risk 판은 없다 — 포털 작업이다).

**그래서 발급을 브라우저가 하게 했다.** 앱 SPA 는 포털과 **같은 오리진**에서 돈다(앱 `/apps/hwax_risk/`,
포털 API `/auth/…`, 앱 API base 는 상대 경로 `api/`). 쿠키·CSRF 를 그대로 실을 수 있으므로 설정 화면의
버튼 하나가 ① 포털에서 `scopes:['read']`·`aud:['mcp-gateway']`·ttl 90일 PAT 을 발급받고 ② 그 값을 곧바로
앱 `PUT /me/portal-pat` 에 넘긴다. 값은 화면 상태에 담지 않고 입력란에도 넣지 않는다.

**scopes 관문은 건드리지 않았다.** `risk_pat_require_read_only` 를 풀면 포털 자동 PAT(`scopes:['chat']`)을
받을 수 있지만, 그건 **검사를 약화시켜 자동화하는 길**이다. 발급 쪽에서 `['read']` 로 만들면 그 검사를
그대로 통과한다 — 같은 결과를 얻는데 관문을 안 깎는다. 포털 코드도 한 줄 안 바꿨다(정본 §8.4 무손상).
(앱 주석이 이미 적어 둔 대로 이 검사는 발급 메타데이터 확인이고 런타임 강제가 아니다. 그래도 지금 깎을
이유가 없다 — 강제가 생기는 날 이 값이 쓸모를 얻는다.)

**실패를 사유별로 가른다.** 이 버튼이 안 되는 이유는 대개 셋이고 각각 다음 할 일이 다르다 —
`hwax_csrf` 쿠키 없음(포털 창에서 열어야 함) · 403(`feat:api-token` 권한을 관리자가 부여) · 401(재로그인).
"발급 실패" 한 문구로 접으면 사람이 무엇을 해야 하는지 모른다.

**병렬 조사(5갈래)가 같은 결론을 독립적으로 냈다** — 브라우저 방향은 `SsoPrimer`+per_user_sso 위임으로
사람 개입이 없고, 끊긴 것은 러너의 포털 PAT 하나다. 포털 `/tokens` 화면의 기본 scopes 가 `['read','write']`
라 그대로 발급하면 앱이 422 로 막는다는 것도 나왔다 — 버튼이 `['read']` 를 명시하므로 그 마찰도 없어진다.

**검증.** `pnpm build` 통과 · `pytest` 1195 passed(백엔드 무변경) · `ruff` 통과.
브라우저 세션이 필요한 발급 자체는 이 환경에서 실행 검증할 수 없다 — 사용자가 버튼을 눌러 확인해야 한다.

### D34. 진짜 끊긴 곳은 죽은 포트였다 — 그리고 그 실패가 토큰 탓으로 읽혔다 (2026-09-30)

D33 의 버튼을 만든 뒤 5갈래 병렬 조사(62 findings)를 대조하다 **버튼만으로는 안 된다**는 것을 알았다.

**`HWAXRISK_PORTAL_BASE` 기본값이 죽은 포트다.** `http://127.0.0.1:5283` 은 포털 `restart.sh` 의
**vite 개발 서버** 포트고, 실제 오리진은 nginx `:8088` 이다(`infra/nginx/hwax.conf` `listen 8088`).
실측 — `5283/agent/conversations` → **000(연결 실패)** · `8088/agent/conversations` → **401(살아 있음)**.
정본도 이 값을 "포털 nginx 오리진" 이라 적어 두었는데 포트가 vite 쪽이다(정본 문면의 오류).

앱이 `portal_base` 를 쓰는 곳은 셋이다 — PAT 등록 검증(`/agent/conversations`), 엔진 호출
(`/agent/chat`), 러너. 그래서 **PAT 등록부터 실패한다.** 더 나쁜 건 그 실패가 `pat_invalid` 로 접혀
화면이 "포털이 이 PAT 를 받지 않았습니다 … 값을 다시 복사하거나 포털에서 새로 발급하세요" 로 번역한
것이다. 사용자는 멀쩡한 토큰을 몇 번이고 다시 발급하게 된다 — **설정 문제를 입력 문제로 번역하는** 전형이다.

**셋을 고쳤다.**
1. 닿지 못한 것과 거부당한 것을 가른다 — `portal_unreachable`(502, 주소와 고칠 env 이름을 문구에 담는다)
   대 `pat_invalid`(422). 그 경로를 태우는 시험이 **하나도 없어서** 안 드러났다(시험 2건 추가, 하나는
   고치기 전 깨진다).
2. `portal_base` 를 `GET /api/me` 의 box 정보로 낸다(비밀이 아니다). **이 값이 화면에 안 보이는 것이
   문제의 절반**이었다 — 보이면 시도 전에 안다. `cred_key` 도 같이 띄운다(백엔드가 이미 주고 있었는데
   화면이 안 그렸다).
3. 화면 오류 사전에 빠져 있던 셋을 채웠다 — `pat_scope_too_broad`(포털 발급 화면 기본 scopes 가
   `['read','write']` 라 링크를 그대로 따라간 사람이 만나는 코드) · `cred_key_absent` · `portal_unreachable`.

**병렬 조사가 독립적으로 확인해 준 것.** 브라우저 방향(포털 로그인 → heax 쿠키 → 앱 화면)과 게이트웨이
per_user_sso 위임(양쪽 시크릿 sha256 일치 실측)은 **사람 개입 없이 이어져 있다**. 끊긴 것은 러너의 포털
PAT 하나였고 그 위에 죽은 주소가 겹쳐 있었다.

**아직 남은 것(이 리포 밖이거나 별건).** Caddy forward_auth 가 게이트웨이가 실은 진짜 호출자
`X-Heax-User-Email` 을 authz 응답 이메일로 덮는다 · 게이트웨이가 단언의 `expires_in` 을 안 읽고 12시간
캐시한다(앱 단언은 15분) · 단언에 jti·nonce 가 없어 재생 방지가 없다 · 감사 원장에 `as-user-pat` 0건 ·
`resolve_credential` 의 (c) 요청자 갈래가 엔진 실호출에는 없다. 체크리스트에 옮긴다.

### D35. UX 가 나쁜 1차 원인은 디자인이 아니었다 (2026-09-30)

사용자가 "웹이 하나도 스마트해 보이지 않고 Report Archive 처럼 깔끔했으면 좋겠다" 고 했다. 뜯기 전에
양쪽 실물을 봤고 진단이 두 겹으로 갈렸다.

**1층 — 첫 화면이 빈 탭이다.** 홈 탭 4개 중 3개가 `"목록 경로가 아직 없습니다"` 였고 서버에 **정말
없었다.** `GET /diffs/{id}`·`/targets/{key}/…` 같은 **항목** 경로만 있고 **컬렉션** 경로가 없었다.
정본 §8.2.3 경로표에도 셋이 빠져 있다(§8.2.4 는 그 탭을 요구하는데 경로표가 그것을 안 적었다 —
정본 안의 공백이다). 그래서 앱은 "여기 무엇이 있는지" 를 보여 줄 방법이 없었다. **스타일을 아무리
바꿔도 안 고쳐지는 종류다** — 빈 화면을 예쁘게 만드는 건 헛일이므로 내용을 먼저 열었다.

**2층 — 표현이 문서이고 서비스가 아니다.** 놀랍게도 토큰(색·간격·radius 8px·다크모드)은 Report Archive
와 근접하다. 빠진 것은 그 위층이다 — Radix 상호작용(Dialog·Tabs·Dropdown·Popover) 0, lucide 아이콘 0,
`cmdk` 커맨드 팔레트 0, 요약 먼저 → 상세 배치 0, 그리고 `KeyValueTable` 이 `ir_hash`·`degraded_json`·
`portal_base` 를 **그대로 label 로** 쓴다(엔지니어 덤프이지 제품 화면이 아니다).
Report Archive 는 **shadcn/ui 기본 토큰 그대로**다(`--primary: 221.2 83.2% 53.3%`·`--radius: 0.5rem`·
`.dark`) + Radix + cva + lucide + cmdk. 사용자가 "그 느낌" 이라 한 것은 이 스택의 언어다.

**사용자가 순서를 정했다** — 내용 → 표현, 스택은 Report Archive 와 동일하게.

**1단계에서 정한 것.** 목록은 **고르기 위한 것**이라 본문을 싣지 않는다(`diff_json`·`summary_text` 제외).
대신 **판정을 목록에 올린다** — diff 는 `blocked`·`gates_failed`(그 diff 를 믿어도 되는지가 고르기보다
먼저다, §2.12), 타깃은 `coverage_pct`·verdict(안 보이면 타깃마다 들어가 봐야 한다), 보고서는 RA 반영
상태. 기본 목록은 §4.8 로 닫힌 타깃을 가린다(D31 이 그 표기를 만들기 시작했으니 이제 의미가 있다).
보고서는 앱이 소유하지 않으므로(§5.3) `rr_targets.report_ids_json` 의 `rpt:` 포인터를 모으고 전문은
RA 가 갖는다고 화면에 적었다 — 사본을 두지 않는 설계를 화면이 말해 준다.

**작은 규율 하나.** 체크박스 래퍼로 `rr-check` 를 지어냈다가 CSS 에 없는 것을 확인하고 기존 `rr-row` 로
바꿨다. 새 클래스를 만들기 전에 기존 패턴을 찾는다(CLAUDE.md §3).

**검증.** `pytest` **1201 passed, 2 skipped**(시험 4건, 전부 고치기 전 깨짐) · `ruff` 통과 ·
`pnpm build` 통과 · 클라이언트 미사용 선언은 기존 4종 그대로(새로 늘지 않았다).

### D36. PAT 재발급을 실제로 눌러 보니 두 겹이 나왔다 (2026-10-01)

사용자가 "재발급도 니가 해" 라고 했다. 버튼은 내가 만든 것이고, **만든 사람이 눌러 보지 않으면
안 눌린다는 사실을 모른다** — 그래서 Playwright 로 포털에 로그인해 라이브 배포본에서 직접 눌렀다.

**1겹 — 발급은 됐고 등록이 502 였다.** 내가 전날 만든 구분(`portal_unreachable` — "PAT 문제가 아니라
설정 문제입니다")이 그대로 떴다. 원인은 컨테이너의 `HWAXRISK_PORTAL_BASE` 가 죽은 vite 포트
`127.0.0.1:5283` 로 돌아가 있던 것이다. HEAXHub `.env` 의 `APPTAINERENV_*` 는 런처가 `os.environ` 에서만
읽으므로 `.env` 를 소싱하지 않은 재배포에서는 실리지 않는다. 재배포로 `8088` 이 들어갔고(`.env 로딩 —
APPTAINERENV_* 2개`), 그 뒤 버튼은 한 번에 통했다 — 새 PAT `oDRGWDrElFg7…`, 만료 2026-12-30,
`scopes: ['read']`, `aud: ['mcp-gateway']`. 실패했던 1차 시도가 포털에 남긴 고아 PAT
`1OgmWBaZ…` 는 값을 복구할 수 없어 `DELETE /auth/pat/{jti}` 로 폐기했다(폐기 목록 475건에 들어간 것 확인).

진단 문구가 제 몫을 했다는 점을 적어 둔다 — 토큰을 다시 발급해도 안 됐을 상황에서 화면이 "토큰 탓이
아니다" 라고 말해 주었다. 이 구분이 없으면 사람은 발급을 반복한다.

**2겹 — 과제 카드가 읽히는 소스를 `unreachable` 이라 말하고 있었다.** 등록 뒤 실제 캡처를 돌렸더니
전 구간이 200 이었다(`:9110/tools-map` · StepForge REST 5경로 · `:9110/mcp` 5회). 그런데 `GET /projects`
는 네 과제 모두 소스를 `unreachable` 로 적고 있었다. `probe_json` 은 `POST /projects/{id}/sources` 가
**연결하는 순간 한 번만** 쓰이고 다시 갱신되지 않는다 — 측정값에 나이가 생기고, 그 나이가 화면에서는
현재 사실처럼 보인다.

어댑터 발견 배선(checklist 1장, 2026-09-02)이 **같은 거짓말의 연결 시점 판**을 고쳤다. 그때 쓴 주석이
"고정 목록으로 적으면 캡처가 도는데도 '연결 안 됨' 이라고 적힌다" 였는데, 한 번 재면 영구히 유효하다고
본 것이 남은 구멍이었다. 캡처 성공은 그 자체로 도달 측정이므로 `refresh_source_probes(store, project_id,
calls)` 로 되쓴다 — 호출 0건인 kind 는 건드리지 않고(**미측정은 실패가 아니다**),
`system_status`(선택 호출)와 전사 집계는 세지 않는다(캡처의 `failed_calls` 와 같은 제외).

회귀는 E2E 스모크에 걸었다. 배선을 떼고 돌려 깨지는 것을 확인했고, 그때 **E2E 의 연결 시점 probe 가
이미 `linked` 였다**는 것도 드러났다 — 모의 어댑터 발견이 성공하기 때문이다. 그래서 `all(... == "linked")`
단언은 그 파일에서 공허하고 실효 단언은 `detail.startswith("capture_ok calls=")` 쪽이다. 두 단언을 다
남긴 이유는 전자가 운영 환경(발견 실패 → `unreachable` 로 연결됨)에서는 실효이기 때문이다.
음성 경로(실패 호출 → 사유가 `detail` 에 남는다, 호출 없던 kind → `probe_at` 불변)는
`test_project_patch.py` 에 따로 고정했다.

**부수로 고친 것 하나** — `capture_all` 독스트링이 `{snapshot_id, results, calls, probes}` 를 돌려준다고
적고 있었는데 `probes` 는 반환에 없고(실제는 `context`) 읽는 곳도 없다. 그 키를 믿고 구현했으면
도달 상태를 영원히 빈 값에서 읽었을 것이다.

### D37. 화면 다섯을 뜯었더니, 띄워 보기 전에는 안 보이는 결함이 줄줄이 나왔다 (2026-10-07)

남은 상세 화면 다섯(Project·Snapshot·Target·Compare·CurationQueue, 3,464줄)을 Report Archive
스택으로 옮겼다. 방법은 **공유 층을 먼저 혼자 확정하고 화면을 병렬로 뜯는 것**이었다 — fan-in 이
큰 조각(SectionCard 9곳·Badge 12곳·DataTable 11곳·StateBlocks 11곳)을 먼저 바꾸지 않으면 같은
앱 안에 방언이 다섯 개 생긴다. 그다음 화면마다 한 에이전트가 전환하고, **전환한 사람과 다른 눈**이
git diff 를 직접 보고 역검토했다(자기 보고를 믿지 말라고 명시했다).

**역검토가 자기 보고에 없던 것을 찾았다.** 33건 중 실질 11건을 고쳤고 가장 중한 넷은 한 뿌리였다 —
내가 내린 "카드가 많으니 탭으로 묶어라" 는 지시가 `{tab === "x" ? <Card/> : null}` 로 구현되면서
**자리를 옮기는 작업이 입력의 수명까지 바꿨다.** `iface-ledger` 의 저장 전 행은 서버에서 다시 읽을
경로가 없는데 탭 한 번에 사라졌고, 등록부의 상태 변경 폼과 `credential === "service"` 경고도 같이
날아갔다. 결정적인 것은 넷째다 — **브리프 탭 재진입마다 `GET /brief` 가 돌고 그 경로는 읽기가 아니다.**
서버가 `issue_brief_token` 으로 `brief_token_hash` 를 덮어쓰므로 사용자가 복사해 둔 토큰이 조용히
무효가 된다. 역검토가 백엔드까지 따라가 확인했다.

공용 `TabPanel` 로 마운트를 유지해 고쳤는데 **그것만으로는 모자랐다.** 띄워 보니 브리프 탭을 한 번도
안 열었는데 호출이 나가 있었다 — 마운트를 유지하니 안 보이는 탭의 `useAsync` 가 그냥 돈다. 고치는
방향이 반대로 작용한 것이다. `enabled` 로 그 탭을 **보고 있을 때만** 부르게 해서 닫았다. 그 김에
`@router.get` 본문을 전수로 훑어 부작용 있는 GET 이 더 있는지 봤다(`get_brief` 하나뿐이다).

**띄워 보기 전에는 아무것도 안 보였다.** 이번에 브라우저로만 잡힌 것이 다섯이다.

- `border-*` 유틸이 **앱 전체에서 무효**였다. preflight 를 꺼 둬서 `border-style` 이 `none` 으로
  남아 width 가 있어도 선이 안 그려졌다. 클래스도 붙어 있고 색도 풀리는데 computed 가 0px 이다.
- 그 수정을 **그 아래 입력·버튼 리셋의 `border: 0` 축약이 되돌리고 있었다**(축약은 style 까지
  none 으로 돌린다). `border-width: 0` 으로 바꿔 닫았다.
- `Select` 화살표가 안 그려졌다. 긴 data URL 을 `+` 로 쪼개 Tailwind 스캐너가 리터럴을 못 보고
  규칙을 **아예 생성하지 않았다**(빌드 CSS 에 `svg+xml` 0건).
- `<h2>`·`<p>` 의 UA margin(13.28px·14px)이 살아 있어 카드 머리말이 헐거웠다.
- **앱 전체가 가로로 밀리고 있었다.** `<main>` 이 flex 자식인데 `w-full`(셸 전체 폭)을 써서
  사이드바 폭 224px 만큼 밀려났다. 이번 전환 이전부터 있던 것이고 모든 화면에 영향을 줬다.

**가장 중요한 교훈은 타입이었다.** 배포해 띄우니 과제 화면이 **백지**였다. `{stepforge_project_id}`
객체를 React 자식으로 렌더했고(error #31), `s.kinds.join()` 이 undefined 를 불렀다. `tsc` 도
통과했고 역검토 다섯도 못 잡았다 — **타입 선언이 서버와 달랐기 때문이다.** `SnapshotHeader` 에
`label`·`captured_at`·`kinds`·`counts` 가 적혀 있었는데 서버에는 그런 이름이 없다(`ir_version`·
`kinds_json`·`node_count`·`created_at` 이다). `ProjectSource.ref` 는 `string` 이라 적혀 있었지만
서버는 `_loads(row["ref_json"], {})` 로 **파싱한 객체**를 준다.

> **타입이 거짓이면 타입검사는 그 거짓을 지켜 준다.** 선언을 서버 열 이름에 맞추자 호출처 9곳이
> 한꺼번에 드러났다 — ProjectPage 8, ComparePage 1. ComparePage 의 스냅샷 고르개도 같은 버그였고
> 아직 아무도 안 눌러 봤을 뿐이었다. 브라우저로 주요 응답 키를 전부 받아 나머지 타입도 대조했다.

**끝으로 공존을 끝냈다.** `App.tsx` 의 버튼 한 곳을 바꾸자 `.rr-*` 69종의 마지막 사용자가 사라졌다.
340줄을 지우고(index.css 666 → 227줄) **preflight 를 켰다** — 도입 때 끈 이유(레거시 608줄이
무너진다)가 사라졌으므로, 점진 도입의 예정된 종점이다. `--rr-*` **변수**는 남긴다(html·body·code·a
가 아직 쓴다). 클래스와 변수는 다른 것이다.

**검증** — `pnpm build` 통과 · `pytest` 1204 passed, 2 skipped · 배포본에서 화면 여섯을 눌러
콘솔 오류 0·가로 스크롤 0 확인 · 브리프 토큰이 탭을 열 때만 발급되는 것을 fetch 계수로 확인.

### D38. 스키마 v5 는 재설계 M3 몫으로 예약한다 (2026-10-14)

- **결정.** `MIGRATIONS` 의 다음 판(v5)은 리스크 심사 재설계 M3 몫이다. 통합 가지 `m3` 에서 짓고, 꾸러미 둘(셀 확장
  `m3-cells` · 쟁점·종합 `m3-synth`)은 하위 가지를 따로 워크트리로 두고 `m3` 위로 rebase 한다. v5 블록의 주인은 쟁점·종합
  꾸러미의 걸음 S3-1 하나다 — 셀 꾸러미가 쓰는 표(`rr_unit_live`, 걸음 C3-1)도 그 블록에 함께 들고, 블록을 고치는 것은
  주인뿐이다. 단계 D(dev 배선 리허설) 전에는 push 하지 않고, 그때 `tests/test_store.py` 의 `PUSHED_DDL_SHA256[5]` 가 굳는다.
- **근거.** v5 는 몇 주 가지에 머문다. 그동안 다른 세션이 main 의 `MIGRATIONS` 를 먼저 건드리면 판 번호가 부딪치고, 나간
  판은 고칠 수 없다(v4 때와 같은 까닭 — 그때는 에이전트 안내에만 적었다). 계획과 결정은 형제 리포
  `../HWAXPortal/docs/risk-review-redesign/M3.md`(3절 짓는 순서 · 3.2 파일 주인 · 4.2 v5 DDL)와 그 context-notes D-32~D-35 다.
- **넣지 않는 것.** v4 주석이 v5 로 미뤘던 `rr_roster.input_gaps_json` 은 v5 에도 없다(M3.md 5절 #43 — 입력 결손은
  `rr_roster.ecad_dependent` 와 스냅샷 `missing.ecad_absent` 로 늘 같은 값이 계산된다).

### D39. 단계 C 첫 묶음(S3-4 · S3-6 · S3-7 · S3-8) — 계획을 코드로 옮기며 정한 것 (2026-10-14)

- **카드 대조 거름은 함수가 아니라 조각 하나다.** 설계서는 `finding_scope(store, target_key) -> (sql, params)` 였지만 대상 범위로
  읽는 세 자리가 모두 `target_key = ?` 를 이미 걸고 있어, 흐름을 하위 질의로 가르는 상수 `registry.FINDING_SCOPE_SQL` 하나로
  했다(패널 대상은 지금처럼 거르고 cells 대상은 전부). 나머지 열일곱 자리는 까닭 한 줄씩과 래칫 시험(`CARD_REVIEW_SITES`).
- **패널 대상 바이트 동일은 얼린 원장 셋으로 본다**(`tests/rr/test_panel_registry_bytes.py`, 기준선은 S3-4 앞 커밋 344e772 의
  코드가 만든 값). 그 원장에는 카드 대조가 얹힌 패널 대상이 없어 거름을 통째로 빼도 지나갔다 — 얹은 대상을 따로 시험한다.
- **`PANEL_JOBS_SQL` 은 넓히지 않았다.** 진행판·길잡이·검토 잡 문지기가 그것을 '패널 Tier 잡' 으로 읽는다. 러너만 쓰는
  `RUNNER_JOBS_SQL`(panels · issues)과 `PANEL_RUNNER_MODES` 를 따로 두었다.
- **쟁점 상한의 '돌린 수'** = 끝난 쟁점 패널(`rr_panels.kind='issue'`, done) + 지금 편성·도는 쟁점, 등급별. 다시 고른 회차도
  같은 누적이다. 엔진·스트림·재기동으로 닫힌 패널은 세지 않는다(쟁점 탓이 아니다 — 차감도 없다). 내용 탓(`charged`)은 결정문
  파싱 실패뿐이다.
- **비우기는 집는 자리에서 본다.** `claim_next_job(…, engine=)` 이 엔진의 `drain_state()`(`/health` 의 `drain.on` · `draining`)를
  한 번 묻고, 비우는 중이면 범위와 상관없이 패널을 집지 않고 잡 행에 `draining: …` 을 적는다. 읽지 못하면 비우지 않는 것으로
  본다(종전 동작).
- **완결의 깊이는 카드로 본 전문가만 센다**(X1-04). 그래서 배경 카드뿐·0장 전문가만 있는 영역은 C2 깊이를 못 채웠다 — 조정자에게
  올렸고 사용자 결정 D-35('카드 0장 전문가는 역할만으로 답하고 보고서에 잔여로 표시')로 정했다. 실제로 검토한 전문가가 전부 카드
  없이 본 영역(묶음 바탕 `card_basis` 가 cards 가 아니다)은 깊이를 막지 않고, 막지 않는 잔여 `depth_no_cards`('카드 없는 영역 —
  역할 판단만 · <영역>')가 잔여 표·표기·종합 보고서 머리에 선다. 카드를 가진 전문가가 있는 영역이 깊이에 못 미치면 지금처럼 막는다.
- **완결의 품질 칸은 진행판의 값을 읽는다**(M2 #16 — 진행판을 읽는 동안 다시 세지 않는다). 진행판에 없을 때만 그 자리에서 센다.
- **신선도** — 쟁점 단계는 선정한 쟁점의 `cells_hash` 또는 사슬 잡의 `chain_json.cells_hash` 가 지금 마감 범위 지문
  (`closure.closing_hash`)과 같을 때, 보고서 판은 `trigger='synth_done'` 판의 `cells_hash` 가 같을 때다. 사슬(S3-5)과 종합(S3-9)이
  서기 전에는 C2·C3 가 오르지 않는다.
- **못 한 것.** 최근 쟁점 패널 다섯이 전부 기각·보류면 `advice='issue_yield_low'`(m3-synthesis 3.12) · MCP 재제출의
  `issue_panel_web_only`(S3-10) · 2,000셀 원장의 refresh 실측(M2 루프로는 로스터 6 × 단위 5 가 최대 — 단계 D 리허설이 잰다).

### D40. 단계 C 둘째 묶음(S3-9 · S3-10 · S3-11 · S3-12) — 정한 것과 남긴 것 (2026-10-14)

- **요약은 카드 대조와 같은 엔진 클라이언트(포털 card-review 중계)를 탄다.** `synth.SynthWorker` 는 러너의 `synth_loop`(5초)가
  틱마다 요약 호출 하나씩 낸다(#51 — 동시 수를 따로 두지 않는다). 기대 판은 엔진이 열어 준 종류별 판(`expect.limits_rev_kind`)과
  `prompt_rev` 만 싣는다. 호출 원장은 `rr_review_calls`(kind summary · agent_key `synth`)다 — 그래서 품질 수치의 '호출 초' 에 summary
  칸이 생길 수 있다(셀 칸 셈은 unit_id 가 없는 호출을 세지 않는다).
- **대조에 걸리면 한 번만 다시 묻는다** — 앞 답의 지적은 요약 본문의 블록 하나(`name: checks`)로 싣는다(엔진 요청 모델에 따로 칸이
  없다). 두 번째도 걸리면 `code_only(checks_failed)` 이고 엔진의 출력은 감사용으로 남긴다(보고서는 '서술 없음 — 까닭').
- **계획한 뒤 원장이 바뀌면**(병합·쟁점 해결) 그 요약 행을 `code_only(superseded)` 로 닫고 같은 잡에서 새 입력으로 다시 세운다.
- **보고서 판의 내용 해시는 판 번호를 뺀 쪽·수·표기로 센다** — 같은 내용이면 판 번호만 다른 새 판을 만들지 않는다. 판을 세운 뒤
  완결 캐시를 다시 쓴다(종합까지 지금 지문으로 돌았나가 바뀐다).
- **cells 대상의 마감 레벨 기본 C3 는 S3-5 몫으로 남겼다.** 지금은 대상을 열 때 `HWAXRISK_DEFAULT_CLOSE_LEVEL`(C2)이 그대로 적혀
  cells 대상도 C2 마감이다 — 결정표 시험은 손잡이로 C3 대상을 연다.
- **MCP** — 도구 추가(29 → 31)만 따로 커밋했다(셀 꾸러미의 `risk_job_action` 인자 커밋 위로 rebase 하기 쉽게). `risk_taxonomy` 는
  한 번에 3만 자를 넘어(택소노미 1.2) `part`·`offset` 으로 나눴다. `risk_next_step` 의 쟁점·종합 단계는 `entry.py` 가 셀 꾸러미
  먼저라 남겼다.
- **포털 쪽(S3-11)은 이 리포 밖이라 조정자에게 문안을 넘겼다** — `infra/pipeline/hwax-risk-review.js` 의 `meta.whenToUse` 한 문장,
  업데이트 이력, 절차서의 이 꾸러미 몫. README 의 'MCP 도구 7종' 줄은 M1 전부터 낡아 있다(손대지 않았다).
- **남긴 것** — C11 의 입력 결손·셀 다시 열기 행(셀 꾸러미 전이 함수가 합쳐진 뒤), C12 ⑤ 2차 주입(셀 꾸러미 대본 칸), C14 정확한
  모양 단언(엔진의 마지막 계약 예제를 받은 뒤), 최근 쟁점 패널 다섯의 `issue_yield_low` 안내.

## 2026-10-14 — 재설계 M3 셀 확장(가지 `m3-cells`) 단계 A

계획 정본은 포털 `docs/risk-review-redesign/M3.md`(3절 단계 A · 4절 계약 · 5절 #26~#62)와 `reference/m3-cells.md` 다.
둘이 다르면 M3.md 가 이긴다. 이 절은 셀 꾸러미가 앱 리포에서 내린 결정만 적는다(번호 `M3C-n` — 형제 꾸러미의 `D` 번호와
rebase 때 부딪치지 않게).

### M3C-1. 시작 걸음(C3-0) — 닻은 그대로였고, 닻에 없던 사실이 둘 나왔다
- **대조.** HEAD `3aea93b` 에서 m3-cells 2절의 닻을 문자열로 다시 찾았다. 앱 쪽은 전부 그대로다 — `create_review_job` 의
  `input_gap_m3` 거절, 잡 `knobs = {dual_rate 1.0, sweep on, filter off}`, `CALLS_PER_CELL = (3, 14)`, `_Cell.dual_decks` 와
  `_solo_set` 의 묶음 갈래, `prompt_key` 가 종류 판 전부를 잇는 것, `ALLOWED_TRANSITIONS["deferred"] = frozenset()`,
  `review_rollup` 의 `nothing_reviewed`, `ir_builder.SEED_SYNONYMS`, `audit.binom_upper`, `review_verify.sample_score`.
  엔진 HEAD `412edde` 도 그대로다(`UNSUPPORTED_KINDS = ("noinput", "cross")` · `_WITH_DELIB` 기본 `min(2, conc)` ·
  `k = max(1, min(k_knob, k_out))`). 엔진 작업 트리에는 엔진 걸음을 짓는 다른 세션의 커밋 전 변경이 있다 — 셀 꾸러미는 엔진을
  건드리지 않는다.
- **닻에 없던 사실 ①.** 저장된 단위 줄에는 `change_kind` 가 없다 — `units` 빌드가 줄의 `_item` 을 끝에 떼어 낸다. 계약(M3.md
  4.9)의 '`codes` 에 없으면 `change_kinds`' 는 줄이 그 칸을 실어 올 때만 듣는다. 그래서 변경 → 메커니즘 표가 생산자 코드를
  `codes` 만으로 전부 풀게 짓고 시험이 그것을 지킨다(M3C-2).
- **닻에 없던 사실 ②.** `rr_review_cells.sample_json` 에는 이미 M2 의 시도 표지(`attempt`)가 산다. C3-6·C3-7 이 표본·그림자·
  `dual_neg` 칸을 더할 때 그 키를 덮지 않는다.
- **하지 않은 것.** 'v5 는 재설계 M3 몫, 가지 `m3`, 블록 주인은 S3-1' 메모는 가지 `m3`(S3-0)가 쓴다 — 이 가지에도 두면 rebase 때
  같은 자리에서 부딪친다.

### M3C-2. 코드 신호(C3-5) — 변경 → 메커니즘 표는 코드만으로 닫히고, 택소노미와는 한 이음매로 닿는다
- **표.** `app/assets/change-routing.v1.json`(`change-routing-1.0`) — `codes` 97줄(의미 이벤트 39 · 노드 6 · 엣지 6가족 × 4 ·
  접촉 범위 · 파라메트릭 27), `change_kinds` 14(택소노미 축 전부, `consistency`·`none` 은 null), `roles` 10(정규명 전부), `always` 빔.
  사람이 훑을 표라 줄마다 `note` 로 까닭을 단다.
- **승인 칸 이름은 `review_status`(값 `draft`)다.** M3.md 4.1·4.9 는 이 표의 칸을 `status` 로 적었다. 배정표(`mech-owners.v1.json`)와
  같은 이름 · 같은 값(`draft`·`approved`)·같은 `reviewed_by`·`reviewed_at` 으로 두어, 사용자가 셋을 한 번에 훑고 승인 커밋이 두
  파일의 같은 칸을 고치게 했다. 승인 문은 둘 다 `approved` 일 때만 연다(#40) — `relevance.routing_approved`.
- **생산자 코드는 `codes` 만으로 푼다**(M3C-1 ①). 시험이 둘을 본다 — 생산자 입력 전부(syn3·40·150 · 무작위 대본 다섯 ·
  `cross.bridge_stale` · diff_pairs 6쌍)의 항목 코드, 그리고 표를 읽지 않고 센 코드 공간(diff 스키마의 열거 + `diff.PARAM_RULES`).
  모르는 버킷(`<layer>.<rest>`)과 표에 없는 코드는 접두에 삼켜지지 않고 '모름' 이다. 접두는 `param.material.*` 하나다 — 생산자가 새
  재질 칸을 내도 재질 교체로 읽는다(정확 일치가 먼저라 E·rho·sigy·nu·mid·keyword·match_basis 는 따로다).
- **롤업도 메커니즘이 있다.** `asm.rollup_changed`·`param.rollup` 은 전역 단위만이 아니라 그 조립 단위의 묶음에 탄다(units W2-01).
  `[]`('설계 변경 아님')로 두면 롤업 줄만 남은 묶음이 코드 신호로 전 영역 무관이 된다 — 위상 요약(접합·접촉·공차·질량)으로 둔다.
- **이음매.** 택소노미 1.2 의 읽는 함수(`domains_for` · `mech_owners_meta` · `load_taxonomy`)는 `relevance._taxonomy()` 한 곳에서
  `app.taxonomy` 모듈로 닿고, 모든 함수가 `tax=` 로 대역을 받는다. 가지 `m3` 전에는 시험이 `TaxonomyDouble`(m3-synthesis 3.4 초안
  52행)을 준다. rebase 하면 시험의 `tax` 픽스처만 `taxonomy` 로 바꾸고 대역과 그 픽스처 파일을 지운다 — 운영 코드는 그대로다.
  `domains_for([코드])` 가 빈 dict 면 그 메커니즘은 배정표에 행이 없는 것으로 읽어 '모름'(`mech:<코드>`)이다.
- **역할.** 이름을 정규화한 토큰의 **어느 자리에서든** 1~3토큰 창이 정규명이나 그 동의어면 그 역할이다(`ir_builder.name_norm_canon`
  은 머리 토큰만 바꾼다 — `rear_cover` 의 `cover` 를 놓친다). 역할은 영역을 더하기만 한다. 씨앗 표에서 하나만 바꿨다 — `shield_can`
  에 `rel` 을 더했다(EMI 의 소유가 rf·rel·pcb 다).
- **초안이 넓다.** 배정표 초안과 곱하면 `mechanical.drop_stress`(소유 sim·mech, 관련 rel·disp·cam·xd·pcb)가 거의 모든 변경 줄에
  있어 그 일곱 영역은 늘 '관련' 이다. syn40·syn150 의 묶음·경계 단위에서 코드 신호가 '무관' 인 영역은 mem·soc·std·sh·passive
  쪽뿐이었다. 거르기의 절감은 이 표와 배정표를 사람이 훑는 데 달렸다(M3.md 8절 첫 줄) — 단계 A 끝에 이 수를 표와 함께 건넨다.

### M3C-3. 경로 결정표(`relevance.route_decision`) — 처음 맞는 줄, 그리고 '거를 수 있던 셀' 과 '그림자' 를 가른다
- **모양.** 입력은 셀 하나의 사실(잡의 거르기 · 1순위 · 단위 종류 · 카드 0장 · 입력 결손과 결측 블록 판 · 넓힘 · 대상 끔 · 넘김 ·
  1순위 대기)과 두 신호(`code_for` · `sweep_signal`), 표본 열쇠(T, u, a)다. 반환은 `{decision, route, route_forced, would_filter,
  shadow, route_json}` — C3-6 의 `_classify` 가 그대로 원장에 쓴다. `route_json` 은 m3-cells 3.2 의 모양에 `reason` 칸만 더했다.
- **규칙 이름과 원장 토큰.** 강제 줄 아홉(1·2·3·4·5·6a 넓힘·6b 대상 끔·7·8)의 이름이 `route_json.rule`·`forced_all` 이고
  `route_forced` 는 3.1 의 어휘다. 6b(대상 전체 끔)는 규칙 이름 `target_off` · 토큰 `filter_off` 다 — 1 번(잡의 거르기 끔)과 토큰이
  같아 원장에서 둘을 가르는 것은 `rule` 이다. 강제 줄이 여럿이면 `forced_all` 에 순서대로 다 적는다.
- **`would_filter` 와 `shadow`.** `would_filter` 는 9 번까지 내려와 두 신호가 다 무관이었던 셀(거름 + 표본 — 완결 몫 `filtered.
  would_filter` 가 이 수다), `shadow` 는 거르지 않았지만 거르기가 닫았을 셀이다 — 1순위 셀(1·2·8 번을 빼고 다시 본다: 1순위
  대기는 그 사람 자신의 몫이다)과 대상 그림자 모드(`shadow`)의 셀. 1순위 셀은 다른 강제 사유(전역 단위 등)가 있으면 그림자가
  아니다 — 1순위가 아니었어도 거르지 않았을 셀이다.
- **잡 거르기 `off` 면 아무것도 적지 않는다.** 결정은 검토로 내지만 `_classify` 는 원장에 `route*`·그림자를 쓰지 않는다 — M2 잡의
  원장이 바이트로 같아야 한다(m3-cells C3-6 수용 기준).
- **입력 결손 전문가.** 검토로 가면 `route='noinput'`(그 셀은 `verdict`·`offcard` 대신 `noinput` 한 번이다), 표본이면 `audit`,
  거르면 `filtered` 다. 결측 블록 판은 `sweep_gap_aware(요청에 extra.missing 을 실었나, 답의 meta.prompt_rev.sweep)` — 둘 다여야
  하고 모르는 판 표기는 아니다.
- **훑기 신호.** `k` 가 달린 `no` 는 '관련' 이다(엔진 `_check_u` 가 이미 maybe 로 올리지만 회계가 묶음을 합친 뒤에도 그대로 본다).
  `stamp`·`error`·답 없음·훑기 실패는 '모름' — 사유를 `reason` 에 남긴다.

### M3C-4. 놓침 판정(`review_verify.audit_outcome`) — 표의 순서를 그대로 쓰고, 표가 비운 칸 하나는 안전한 쪽으로 메웠다
- 결과 넷과 순서는 m3-cells 3.4 그대로다 — `risk_miss` → `relevance_miss` → `undetermined` → `kept`, 처음 맞는 줄. 실효 판정은
  `effective_rows` 의 것을 받는다(변형이 걸렸다가 풀린 카드는 거기서 이미 `undetermined` · `split=1` 이고 여기서 `risk_miss` 다).
- **표가 비운 칸 — 심각도가 없는 카드 밖 리스크.** 표는 '리스크 · 중대·치명 → risk_miss', '경미·개선 → relevance_miss' 만 적었다.
  엔진은 모르는 심각도를 빈 문자열로 내린다(`_enum(row, "sev", SEVS, "")`). 그 줄을 `risk_miss` 로 둔다 — 경미가 아닌 리스크는
  전부다. 놓침을 넓히는 쪽이 안전하고(넓힘은 비용만 든다), X1-13 의 '모르는 것을 깨끗한 쪽에 넣지 않는다' 와 같은 방향이다.
  방향이 빈 줄은 앱 회계의 기본값대로 리스크다.
- **표의 순서가 정하는 칸 — `applies='yes'` 이면서 판정 보류인 행.** 표의 순서상 `relevance_miss` 다(보류보다 앞 줄). 보수 상한
  `(risk_miss + undetermined) / 표본` 에는 들지 않는다. 표를 그대로 따랐고 시험이 그 순서를 고정한다 — 바꾸려면 표부터 고친다.

### M3C-5. 걸린 것만 이중 판정(`review_verify.dual_plan_flagged` · `dual_neg_state`) — 보정과 무작위 뒤집기를 한 계획 함수에
- **한 함수가 묶음 하나의 rev 를 정한다.** m3-cells C3-9 는 `dual_plan_flagged(fwd_request, flagged_aliases)` 와 이유 넷(`dual` ·
  `single_flag` · `none_flagged` · `same_body`)을 적었다. M3.md #31·#32 가 1순위 보정(묶음 전체)과 무작위 뒤집기를 더해, 인자
  `calibrate`·`neg_on`·`neg_pct`·`sample_key` 와 이유 둘(`calib` · `dual_neg`)을 더했다. 처음 맞는 줄 — 보정 → 걸림 둘 이상 →
  걸림 하나 → (걸림 없음이고 켜졌으면) 무작위 → 걸림 없음. 걸린 묶음은 무작위 길을 타지 않는다. 묶음 전체 rev 가 fwd 와 같은
  본문(카드 1장)이면 `same_body` 로 단독에 보낸다(`dual_plan` 과 같다). `dual='all'`(M2)은 지금 `dual_plan` 그대로다.
- **걸림 하나면 `solo` 에 그 별칭을 싣는다.** 단독 재질의가 그 카드의 두 번째 판정이라는 것을 계획에 드러낸다(`_solo_set` 의 '실효가
  걸림' 갈래도 같은 카드를 고른다 — 겹쳐도 한 번이다). 반환 `aliases` 는 rev 에 실은 별칭이고 셀의 `dual_aliases` 가 된다.
- **걸린 별칭만 실은 rev 본문.** 카드는 fwd 순서(엔진이 뒤집는다), 묶음에서 빠진 카드는 제목 목록(digest)으로 내려 팩 순서로
  세운다. 팩 순서는 별칭 숫자 순서다(엔진 `assign_aliases` 가 팩 순서로 K01… 를 매긴다). 시험이 그 본문을
  `engine_client.run_body(cards=걸린 별칭, digest=팩의 나머지)` 와 견준다. 엔진 검증기(형제 리포 서브프로세스)로 422 없이 받는지는
  C3-9(루프 배선)에서 본다 — 지금 엔진 작업 트리는 다른 세션이 고치는 중이다.
- **무작위 뒤집기의 켜짐(#32).** `dual_neg_state(1순위 셀 판정 행, tier_a_closed, already_on)` — 셀 × 카드마다 fwd 가 OK·na 이고
  rev 행이 있는 것이 분모, 그 가운데 rev 가 FAIL·WARNING 인 것이 분자, 비율이 5% 를 **넘으면**(`>`) 켠다. 1순위 셀이 다 종결되기
  전이거나 잴 카드가 0 이면 '미측정' 이다. 한 번 켜지면(그 대상의 셀에 `sample_json.dual_neg.on` 이 섰으면) 꺼지지 않는다 — 1순위
  셀이 사람의 다시로 다시 돌아 비율이 내려가도 그대로다. 같은 카드라도 단위가 다르면 따로 센다.

### M3C-6. 변이 검사와 rebase 할 일 — 단계 A 끝
- **변이.** `git archive` 사본 한 곳에서 66개(결정표 24 · 훑기 신호 5 · 코드 신호 10 · 놓침 판정 9 · 이중 판정 계획 12 · 켜짐 6)를
  하나씩 넣고 그 파일의 시험을 돌렸다. 단언 실패로 붉어진 것만 죽음으로 셌다(junit 의 실패 메시지가 `AssertionError`·`assert` 로
  시작하는 것). 첫 판은 62 죽음 · 살아남음 2 · 단언 아닌 실패 1 · 분류 실수 1 이었다 — 살아남은 둘은 죽은 조건(1순위 그림자의
  '잡 거르기 끔' — 강제 줄 목록이 이미 막는다, 지웠다)과 시험 없는 규칙(가장 긴 접두 — 실제 표에 접두가 하나뿐이다, 시험을
  더했다), 단언 아닌 실패는 보정 비율의 `KeyError`(분모 조건을 빼면 틀린 분모가 단언에 걸리게 `.get` 으로 읽는다)였다. 고친 뒤
  둘째 판 66/66 이 단언으로 죽었고 사본은 HEAD 와 바이트로 같다.
- **가지 `m3` 로 rebase 하면.** ① `tests/test_relevance.py` 의 `tax` · `approved_tax` 픽스처가 `TaxonomyDouble` 대신 `app.taxonomy`
  를 쓰게 한다(`approved_tax` 는 `mech-owners.v1.json` 이 draft 인 동안 `review_status` 만 바꾼 사본이 필요하다 — `mech_owners_meta`
  를 덮는 얇은 감싸개). ② `TaxonomyDouble` 과 `tests/fixtures/relevance/mech_owners_draft.json` 을 지운다. ③ `taxonomy.VOCAB_ASSETS`
  에 `change-routing` 한 줄(M3.md 3.2 — S3-2 가 먼저). ④ 시험의 `52`(활성 메커니즘 수) · `tax-1.2` 가 진짜 표에서도 맞는지 본다 —
  배정표가 초안과 달라졌으면 XU5 의 '33종 전부 어느 영역엔가 닿는다' 와 '15영역이 다 닿는다' 가 그 차이를 잡는다.
  운영 코드(`relevance.py`)는 고치지 않는다 — 이음매가 `_taxonomy()` 하나다.
- **전체 시험(공유 잠금 아래 한 번).** 2,540개(main 의 2,440 + 이 가지 100) 가운데 붉은 것은 하나다 —
  `test_card_review_request_contract.py::test_run_bodies_built_from_real_units_and_packs_pass_the_engines_validator`. 형제 엔진의
  HEAD 가 `8e1e3d4`(엔진 꾸러미 E3 진행 중)로 올라 검증기가 `limits["noinput"]["items_max"]` 를 읽는데, 그 시험이 넘기는 엔진
  계약 예제 `limits_1m.json` 에는 아직 `noinput` 칸이 없다(E3-10 이 계약 예제를 다시 뜬다). main `3aea93b` 를 같은 엔진에 대도
  똑같이 붉고, 이 가지를 기준 엔진 `412edde`(git archive 사본)에 대면 초록이다 — 이 가지 탓이 아니다. ruff 는 깨끗하다.

### M3C-7. 가지 `m3` 위로 rebase — 이음매 한 곳은 그대로 맞았다
- `m3`(`a9dfbde` — v5 블록 `f6731c2` · 택소노미 1.2 `5320f33` · 배정표 `793b685` · #25 앱 쪽 `48b1fe5`) 위로 옮겼다. 부딪친 곳은
  이 파일 하나(가지 `m3` 의 D38 과 이 절이 같은 끝에 붙었다 — 둘 다 남겼다)다.
- `taxonomy.domains_for` 는 dict 를 넓힌 `DomainRoles`(승인 여부 · 표에 없는 코드 · `signal(domain)`)를 돌려준다. 코드 신호는
  메커니즘마다 `domains_for([코드])` 의 영역만 읽고 승인 문은 두 표를 함께 스스로 본다 — 표에 없는 코드는 빈 결과라 '모름' 이다.
  `relevance.py` 는 고치지 않았다.
- 시험은 진짜 택소노미 1.2 · 배정표 초안 52행 위에서 돈다. 배정표가 draft 인 동안 '문이 열렸을 때' 는 승인 칸만 바꿔 보이는
  `GateOf` 로 본다. 대역과 그 픽스처 파일은 지웠다. `VOCAB_ASSETS` 의 표시 줄에 `change-routing` 을 넣었다(표시 줄의 '승인 문 status'
  를 이 표의 칸 이름 `review_status` 로 바로잡았다 — M3C-2). 승인된 뒤에도 표 모양 시험이 건너뛰지 않게 '누가 언제 승인했나' 를 본다.

## 2026-10-14 — 재설계 M3 셀 확장(가지 `m3-cells`) 단계 C 첫 묶음(C3-2 · C3-4 · C3-6 · C3-3 · C3-9)

### M3C-8. 전원 포함 · 보류 해제(C3-2)
- 422 `input_gap_m3` 를 없앴다. 카드 대조 대상(`flow='cells'`)이면 `create_review_job` 이 잡을 세우는 같은 트랜잭션에서 범위 안
  `deferred`(`ecad_absent`) 좌석을 `pending` 으로 풀고(`planner.undefer`) 감사 한 행(`coverage.undefer`)을 남긴다 — 풀지 않으면 원장
  마감이 그 행을 건드리지 않아 종결 어휘로 남는다(거짓 완결). 패널 대상은 풀지 않고 사람이 `POST /targets/{key}/undefer` 로 푼다.
- 보류를 여는 문은 그 하나다 — 이월 되돌리기(`revert_carried`)는 보류 좌석에 409 다. `routes._audit` 는 감사 id 를 돌려주고
  `actor_verified` 를 받는다(MCP 길은 0).
- `review_ops` 에 `input_gap_m3` 별칭은 남기지 않았다(m3-cells 3.12 의 권고와 다르다) — 그 코드를 내는 곳이 없어 별칭은 죽은 줄이다.

### M3C-9. 실패 셀 처분(C3-4)
- 다시 연 셀은 시도 수가 0 으로 돌아가므로 앞의 같은 시도에서 받은 답을 다시 쓰면 같은 실패를 엔진을 부르지 않고 되풀이한다 —
  요청 열쇠에 `reopened_n`(0 보다 클 때만)을 넣었다. 한 번도 다시 열리지 않은 셀(M2 원장)의 열쇠는 그대로다.
- 처분과 잡 세우기를 바깥 트랜잭션 하나로 묶었다 — 잡이 동의·자격으로 거절되면 처분도 되돌아간다(`store.tx()` 는 겹쳐 들어간다).
- 묶음을 끝내 못 받은 전문가(pack error)도 사람이 셀을 넘기면 마감된다(`FINALIZE_PACK_SQL` 에 error, 마감은 묶음 없이 보고서를 짓는다).
- 롤업은 m3-cells 3.9 의 아홉 줄. `failed_open` 은 failed 셀 전부다(넘긴 셀은 skipped 라 따로 셀 필요가 없다).

### M3C-10. 엔진 계약 예제 사본 두 번(734bc38 · f2281e3)
- 두 번 다 제 커밋으로 다시 떴다(`ce810ab` · `b41742b`). 가짜 엔진은 요청 모양(`extra.missing` · `extra.search` · `summary` ·
  run 의 `expect.limits_rev_kind`)과 결과 모양(`checks.mech` · `meta.limits_rev_kind` · `meta.clipped` · `quality.dup_conflict` ·
  `flipped` · noinput q1 의 `checks.why` · q1·q2 를 함께 세는 `quality.ok`)을 예제에 맞췄다.
- 창 부족 판정은 `cell_kinds` 만 본다 — 요약만 못 도는 박스는 셀 일을 멈추지 않는다.
- 엔진 HEAD 가 계약 예제보다 앞서 있던 동안(예제 재생성 전) 요청 계약 시험은 엔진 기준판의 `git archive` 사본(`HWAX_AGENT_SERVER_REPO`)
  으로 확인했다.

### M3C-11. 거르기 분류(C3-6)
- 잡 거르기 `off`(M2 잡 포함)면 아무것도 쓰지 않는다 — 결정표의 1번 줄을 원장에 적지 않는 대신 M2 원장과 바이트가 같다.
- 분류는 셀마다 한 번이다 — `route` 가 선 셀(재기동·인프라 실패 뒤)과 사람이 다시 연 셀(`human_retry`)은 다시 분류하지 않는다.
  입력이 바뀌면(`start_cell` 이 `route` 를 비운다) 다시 분류한다. 시험이 '1순위가 그 사이 닫혀도 다시 거르지 않는다' 를 본다.
- 1순위 대기(8번 줄)는 대상의 1순위 셀 전부(잡 범위와 상관없이)다 — 1순위를 범위에서 뺀 잡은 그래서 거르지 않는다.
- 넘김(7번)은 다른 머리의 `sweep_json.handoffs` 를 SQLite `json_each` 로 읽는다(359명 × 세션마다 파이썬 파싱을 피한다).
- 승인 문은 잡을 만들 때 얼린다(`routing_approved`). 표가 아직 초안이라 운영에서는 분류만 적고 아무것도 걸러지지 않는다. 손잡이
  기본은 `on` 이다(M3.md 4.5).
- 택소노미에 없는 로스터 영역의 코드 신호는 `unknown`(`domain_unknown`) — 거르는 쪽에 서지 않는다.

### M3C-12. 셀 지문 · 계획 · 훑기 열쇠 · 기대 판은 그 셀이 부르는 종류만(#37 · RB3-6)
- `prompt_key(lim, kinds)` · `limits_key(lim, kinds)` — 카드 전문가 sweep·verdict·offcard, 입력 결손 전문가 sweep·noinput.
  종류별 판이 없는 엔진(M2)은 전역 `limits_rev` 그대로라 M2 원장의 지문이 바뀌지 않는다.
- run 의 `expect` 는 `{prompt_rev, limits_rev_kind}`, plan 은 전역 `limits_rev` 그대로(엔진이 plan 의 `limits_rev_kind` 를 422).
  `_limits_moved` 는 그 종류의 판만 본다 — 다른 종류에만 닿은 변경은 rev_mismatch 가 되지 않는다.

### M3C-13. 입력 결손 호출(C3-3)
- 엔진의 `limits.kinds` 에 noinput 이 없으면 계획 전에 잡을 `agent_outdated` 로 멈춘다(차감 없음) — `unsupported_kind` 를 받아
  `contract`(자동 재개 없음)로 서는 길을 피한다.
- 요청의 digest 는 전 카드 제목(엔진 예제 `req_noinput` 과 같다). 정산표 네 줄은 `review_verify.noinput_outcome` 이 정하고, q1·q2
  가운데 한 줄도 없으면 결과가 없어 내용 탓 실패(`noinput_incomplete`)다. 마지막 답이 잘렸으면 `output_truncated`.
- basis `noinput` 을 `CELL_BASES` 에 넣고 불변식(G4)이 그 셀을 따로 본다(계획 카드 수 NULL · 결과 있음). 판정 표에는 쓰지 않는다.
- finding — q1 yes 줄. `judgement_claimed` 는 WARNING 으로 남긴다(q1 은 판정이 아니라 '영향 있음' 주장이라 hold 정책의 상한으로
  적었다 — 수용 기준 'judgement_claimed 가 남는다' 의 해석).
- 보고서에 `input_gap` 절(결손 · 실마리 · 단위마다 결과 · 영향 · 확인할 것)과 필요한 정보의 q2. `REPORT_REV` 는 올리지 않았다 —
  C3-8 이 한 번만 올린다(M3.md 3.2).
- 영역 실마리(`input-gap.v1.json`)는 입력 결손 전문가의 ecad 줄에만 붙는다 — 다른 전문가의 요청 본문은 바뀌지 않는다.
- 품질 문면의 '훑기 무관 — 분류에 쓰지 않음' 은 거르기가 켜진 대상에서는 맞지 않는 말이다 — 거르기 칸을 다는 C3-8 이 고친다.

### M3C-14. 걸린 것만 이중 판정(C3-9)
- 시험대(review_rig)의 기본은 `all`(M2 동작)이다 — 호출 차례·수를 세는 M2 시험이 그 위에 서 있다. 운영 기본은 `flagged`.
- 단독 갈래는 rev 를 실은 별칭(`dual_aliases`)으로 정한다 — 묶음 단위면 안 걸린 카드가 단독으로 샌다.
- 무작위 뒤집기는 원장에서 유도한다(보정 모집단 = 대상의 1순위 셀 판정 행, 1순위가 다 닫혔나, 이미 켜진 셀이 있나). 셀마다
  `sample_json.dual_neg{on, picked}`(1순위 밖 · 묶음이 있는 셀만).
- RB3-1 — 판정 행의 `checks.dup_conflict` · `flipped_from` 은 그 카드를 걸린 것처럼 다룬다(rev 또는 단독). 셀 단위가 아니라 표지가
  선 행의 카드 단위다(엔진의 `quality.dup_conflict`·`flipped` 는 그 행 수의 합이다). `flipped_from` 은 판정 표에 칸이 없어
  `checks_json` 사본에 둔다.
- `flips.order` 의 모집단을 보정용으로 바꾸고 `flips.flagged_pos_neg` 를 더하는 일은 품질 기준판 rq-2 와 함께 C3-8 로 넘겼다.

### M3C-15. RB3 의 보이기
- ctx_too_small 보류 글이 까닭(window · output_cap · output_too_large)과 고칠 손잡이를 싣는다.
- 품질 수치에 엔진이 알린 부딪침(`flips.engine_conflict`)과 몫에서 끊은 입력(`truncation.clipped` — 호출 원장 앱 회계에 남긴다)을
  더했다. 전문가 보고서의 품질 절이 같은 문면이다.

### M3C-16. 변이 검사 — 단계 C 첫 묶음
- `git archive` 사본 한 곳(`scratchpad/celm3-<pid>-b`)에서 63개(C3-2 3 · C3-4 4 · C3-6 13 · #37·RB3-6 5 · RB3-14 2 · 품질 2 · C3-3
  20 · C3-9 14)를 하나씩 넣고 그 규칙의 시험 파일을 돌렸다. 단언 실패로 붉어진 것만 죽음으로 셌다.
- 첫 판 48 죽음 · 살아남음 9 · 단언 아닌 실패 6. 살아남은 것은 시험이 그 갈래를 밟지 않던 곳이었다 — 다시 연 셀이 앞 실행의 ok
  답을 다시 쓰는지(그때 시험은 오류 프레임이라 캐시가 없었다), 훑기 묶음 하나만 실패한 전문가, 결손이 아닌 전문가의 실마리, 까닭만인
  q2 의 자료 칸, 보충이 다 받은 입력 결손 답, 1순위가 일부만 닫힌 대상의 무작위 뒤집기, 걸린 별칭만 실은 rev 의 호출 원장, 그리고
  보류 해제가 전이표를 보지 않던 것(`undefer` 에 `_guard` 를 더했다). 단언 아닌 실패는 거절·기동 실패를 못 낸 경우(`pytest.raises`)와
  표지가 빠진 경우(`KeyError`)라 시험이 단언으로 떨어지게 고쳤다.
- 고친 뒤 둘째 판 61/63, 남은 둘 가운데 하나(요약 판만 오른 뒤 재기동 없이 도는 세션의 기대 판)는 시험을 넓혀 죽였다 — 62/63.
  마지막 하나(훑기 열쇠를 전역 판으로)는 같은 값의 변이다 — 다시 훑어도 머리 호출의 요청 열쇠가 종류별 판이라 원장의 답을 그대로
  다시 읽어 엔진 호출도 결과도 달라지지 않는다.
- **전체 시험(공유 잠금 아래 한 번).** 2,666 통과 · xfail 6 · 실패 0(엔진 HEAD `3f23572` · 계약 예제 `f2281e3` 사본). ruff 깨끗하다.
- **가지 `m3` 와 합칠 때.** 이 가지를 세운 뒤 `m3` 가 21커밋 나아갔다(쟁점·종합 꾸러미). 3방향 비교로 글자가 부딪치는 곳은 이
  파일(`context-notes.md` — 형제의 D39 와 이 절이 같은 끝)뿐이다 — 둘 다 남긴다. 두 가지가 함께 고친 파일은 config · engine_client ·
  mcp_server · planner · routes · test_mcp_tools 다.

## 재설계 M3 — 셀 꾸러미 단계 C 둘째 묶음(C3-7 · C3-8 · C3-10 · C3-11 · C3-12 · C3-13, 2026-10-14)

### M3C-17. 엔진 계약 예제 셋째 사본(1958202 · 예제 d18e89d)
- 엔진 작업 트리가 아니라 커밋에서 뜬다(`git show 1958202:…`) — 한 커밋(684e067)이라 다시 뜨기 쉽다. 계획(plan)에 `limits_rev_by_kind`
  가 실려 가짜 엔진도 싣는다.
- ctx_too_small 보류 글은 `reason_by_kind`(없으면 `reason`)를 읽어 같은 까닭의 종류를 한 문장으로 묶고 저마다 고칠 손잡이를 단다(RB3-14).
- C3-14(대역 일치 · 마지막 예제 사본)는 엔진의 마지막 예제 커밋을 받은 뒤다 — 이 묶음에서는 하지 않았다.

### M3C-18. 표본 · 그림자 · 넓힘 · 보충 표본(C3-7)
- 넓힘과 '대상 전체 끔'은 저장하지 않고 원장(표본 · 그림자 셀의 결과가 risk_miss 인 영역)에서 유도한다(`widened_domains` ·
  `filter_off`, 셋이면 끔). 저장하면 원장과 두 벌이 되어 다시 연 셀 · 처분 뒤에 어긋난다.
- 입력 결손 셀의 표본 결과는 그 셀의 정산 결과로 — 영향 있음 risk_miss · 모름 · 확인할 항목 undetermined · 없음 kept.
- 잡 끝 보충 표본은 `knobs.filter == 'on'` 일 때만, completed 앞에서 — 다시 연 셀이 있으면 잡은 review 로 이어 돈다(사슬보다 먼저 —
  M3.md 3.1 의 합치는 차례). 표본 바닥 `n_audit = max(ceil(pct% × N), min(N, 59))` + 영역마다 1건, 못 채우면 short.
- 작은 시험 대상에서는 바닥이 거를 수 있던 셀 전부라 보충 표본이 거른 셀을 다 다시 연다 — '거름' 의 단언은 최종 상태가 아니라
  `route_json.decision == 'filtered'` 로 본다.

### M3C-19. 보이기(C3-8)
- `REPORT_REV` 는 이 묶음에서 한 번(expert-report-2)만 올렸다 — 뒤 걸음(검색 표지 · B 층)은 같은 판 안에서 더했다(아직 push 전).
- 거름 까닭(`filter_reason`)은 훑기 why 앞 80자를 위생해 «» 안에 둔다 — 셀 격자 · 셀 하나 · 보고서 '거름' 목록이 같은 글이다.
- 품질 rq-2 의 `filter.audit.risk_miss`(95% 상한 5% · 표본 59)는 거를 수 있던 칸이 있는 범위에서만 견준다(조건부 기준). `flips.order`
  는 걸린 것만 이중 판정이면 보정 모집단(1순위 셀)만 센다. '훑기 무관 — 분류에 쓰지 않음' 은 거르기가 켜진 대상에서 틀린 말이라
  '거르기 분류의 훑기 신호'(끔이면 '분류에 쓰지 않음')로 고쳤다.
- 점검표의 부딪침 표지(contested_by · dup_conflict · flipped_from)는 실효 행만이 아니라 변형 전부에서 모은다 — 실효 행이 단독이면
  fwd 의 다툼이 사라졌다.

### M3C-20. 호출 추정 · 동의 · 상한(C3-10)
- 동의 · 거절 · PAT 수명 안내는 `expected`(거르기 없음 가정)와 견준다 — `low` 는 거르기를 믿은 값이라 동의 문턱을 내릴 수 있다.
- k 는 이 박스의 마지막 계획(머리 `plan_json.k`)에서, 없으면 8. 앱 워커 기본 8(D-34) — 서버 limit 을 넘겨 띄우지 않는다.
- 동시 워커 시험이 박스 부하에 흔들렸다(limit 8 에서 겹침 2~4). 까닭은 시간이 아니라 거르기의 1순위 대기 — 영역마다 1순위만 먼저
  돈다. 시험은 거르기를 끄고 전문가마다 첫 run 을 붙들어 다섯이 함께 돌 때 놓는다(b188bf0).

### M3C-21. 359명 규모(C3-11)
- 전문가 단위 단계 — `_spawn` 은 잡 단계와 무관하게 pack → review → finalize 차례로 집는다. `check_aidh` 는 그 잡 범위에 묶음을 받은
  전문가가 하나라도 있으면 카드 저장소가 닿는 것으로 본다 — 아니면 남들이 다 끝나 열린 셀이 502 전문가에게만 남는 순간 잡 전체가
  aidh_unreachable 로 멈췄다(pack 502 시험이 찾았다).
- `expert_tally` 는 SQL 에서 전문가로 거른다. 진행판 품질 칸은 `max(60, 30 × 지난 계산 초)` 마다(끝난 잡은 늘).
- 규모 시험의 기본 단위는 다섯이다 — 합성 40줄은 단위 크기 손잡이로 셋을 만들 수 없다(다섯 → 둘로 뛴다). `RR_FULL=1` 은 20단위
  (7,180셀 — 전원 격자, 손잡이 8/15/6).
- **찾은 결함 — 359명 진행판의 MCP 기본 답이 26,579자.** 좌석을 한 줄로 줄여도 검토 순서 요약(영역 15 × 앞 3명)과 품질 칸만으로
  넘었다. 시험이 운영처럼 `QUALITY_HOOK` 을 꽂았을 때만 드러났다(꽂지 않으면 품질 칸이 없다 — 다른 시험이 main 을 띄운 순서에서만
  붉었다). 검토 순서 요약을 영역마다 3 → 2 → 1 명으로 줄인다(`_fit_guide` 와 같은 규칙, 617a4ee). 규모 시험은 이제 늘 꽂는다.

### M3C-22. 보충이 갈아 낀 행(D-42 E)
- 두 번째 판정의 방아쇠는 `flipped_from` 이 있는 행 전부(raw 가 있든 없든)와 `checks.dup_conflict` 다 — C3-9 의 `engine_conflict`
  가 이미 그렇다. raw 는 품질 셈만 가른다(`flips.engine_conflict.coerced` · `explicit`).

### M3C-23. 근거 꾸러미 실호출(B 층, C3-12)
- **계획.** 보고서 비교는 두 스냅샷 IR 의 각 쪽 첫 보고서(같으면 부르지 않는다) — '앞 두 건' 을 '전 · 후 한 건씩' 으로 읽었다(같은
  쪽의 두 건은 리비전 비교가 아니다). 결과 변화 줄은 diff 의 `parametric.result_delta`(값이 같은 표지 행 제외)와 `result.*` 이벤트의
  cid 로 단위 `cids` 와 맞춘다(단위 줄에는 버킷이 없다). 그 단위의 줄에는 그 단위 부품의 pid 행만 싣는다(`results.parts_map`).
  재질 쌍은 단위 부품의 `material_before/after`.
- **스키마.** `McpHttpClient.list_tools`(tools/list · nextCursor) — 사용자 PAT 로 묻는다. `/tools-map`(gateway_tool_names)은 쓰지 않는다.
- **실패 가르기.** 연결 · 기한 · 5xx 만 인프라(얼리지 않음 · 60초부터 두 배 · 여섯 번째에 live_infra_exhausted 로 partial). 401 은 잡
  credential 보류(서비스 계정으로 내려가지 않는다). 403(live_denied) · 4xx · 도구 오류 · rpc 오류 · 읽을 수 없는 답 · 오류 본문
  (live_error_body)은 내용 탓.
- **skipped 의 기준은 셀 상태가 아니라 `input_hash IS NOT NULL`.** 거르기 분류는 셀을 시작하지 않고 pending → na_irrelevant 로 옮기므로
  '상태가 pending 이 아닌 셀' 로 보면 막 분류된 단위가 skipped 로 얼어 B 층을 잃는다. 지문이 서 있는 셀만 '이미 돈' 것이다.
- **잡 단계로 묶지 않는다.** live 는 `_spawn` 에서 대상마다 워커 하나로 가장 먼저 뜨지만, 잡 전체를 live 단계로 막지 않고 단위 문
  (`unit_live.READY_SQL` — 셀 시작 · 전문가 집기)으로 막는다 — C3-11 과 같은 까닭(게이트웨이가 한 시간 막히면 다른 단위까지 선다).
  진행판 phase 는 'live' 다. 행이 없는 단위는 막지 않는다(B 층 이전 원장).
- **엔진 단위 모양.** RunUnit 은 모르는 칸을 422 로 거절한다 — payload 에 live_sha 칸을 더하지 않고 근거 줄 · notes 만 바꾼다. 셀 지문의
  live_sha 는 러너가 `lines_for` 에서 읽는다(값이 있을 때만 지문에 — 없으면 M2 식).
- **자격 여유** = ensure 기한(1,800초) + 600(W2-04 (d)). 원문은 `rr_brief_calls`(LiveSource — 열쇠에 자격 종류, 오류 본문 ok=0).
- 시험대(rig) · 셀 원장 시험은 M2 처럼 끈다(손잡이 0 — 전 단위 none). 운영 기본은 켬.
- 응답 문자열의 주입 어휘는 자리표시자로 서고 큐레이션 큐(suspect_text)에 원문이 올라간다(C3-13 ②).

### M3C-24. 카드 0장 전문가의 긴 문서 검색(engine-ops 4 — 첫 묶음에서 미뤘던 것)
- 검색어는 코드가 짓는다 — 단위 제목과 변경 줄 몸통(600자까지). 카드가 있는 전문가 · 배경뿐 전문가는 싣지 않는다(A5).
- `meta.search.state='failed'` 는 같은 호출을 인프라(search_failed · 차감 없음 · 셀 백오프)로 세 번까지 다시 낸다. **차단기에는 싣지
  않는다** — 답은 왔고 못 물은 것은 문서 검색이라 LLM 장애가 아니다(카드 0장 셀이 몰려 실패해도 잡 전체가 llm_outage 로 서지 않게).
  그 뒤에는 role_only 로 받고 셀에 search_failed. empty_scope · no_hits 는 물어본 것이라 다시 내지 않는다.
- 롤업의 카드 0장(no_cards)은 search_only 셀도 카드 없이 본 것으로 센다. 완결 몫에 `no_cards{experts, cells, by_basis{role_only,
  search_only, search_failed}}` — 잔여 no_cards 의 basis 표기(M3.md 4.10)를 쟁점 · 종합 꾸러미가 다시 세지 않게.

### M3C-25. 보안 시험의 셀 몫(C3-13)
- **찾은 결함 — 남의 검토 잡 처분이 대상 열쇠가 실린 404 를 냈다.** MCP `risk_job_action(retry_failed · skip_failed)` 가 잡을 찾은 뒤
  라우트의 '타깃(diff:…) 을 찾을 수 없습니다' 를 그대로 올렸다 — 없는 잡과 다른 답이고 남의 대상 열쇠가 샌다. 둘 다 `not_visible`.
- 경로 목록은 라우터에서 뽑는다(`/api/targets/{key}/` 아래 cells · experts · undefer · units) — 표에 없는 새 경로가 들어오면 붉다.
- 카나리아는 합성 카드에 인용되지 않는 절(sid 9)을 더해 심는다 — text_sha · chars 를 엔진 식으로 다시 세 묶음 무결성 검사를 지난다.
  로그는 fixture 단계(setup)의 기록까지 본다(caplog.text 는 그 단계만 준다).
- 2차 주입의 대본 칸은 가짜 엔진의 `inject`(+ `inject_kinds`)다 — 쟁점 · 종합 꾸러미의 C12 ⑤도 이 칸으로 심는다. 다음 프롬프트
  (extra.known)는 엔진 자신의 `build_prompt`(형제 리포 venv · 서브프로세스 — 요청 계약 시험과 같은 길)로 지어 «» 안인지 본다.

### M3C-26. 대역 일치 · 마지막 계약 예제(C3-14 — 엔진 c4e4823)
- 예제 사본은 엔진의 마지막 커밋에서 한 커밋으로 다시 떴다(8f9b8d4) — 4d569e8 판은 따로 뜨지 않고 건너뛰었다(덧붙기만 했다).
  요약 판 cr-summary-2 는 앱이 limits 에서 읽어 기대 판으로 싣는다(앱 코드에 판 글이 없다). 쟁점 · 종합 꾸러미의 가짜 요약 엔진
  (`tests/synth/fake_summary_engine.py` PROMPT_REV)과 `test_synth.py` 의 기대 판은 아직 cr-summary-1 이다 — 그 꾸러미의 파일이라 손대지 않았다.
- 대역 일치는 예제 행의 표지를 가짜 스위치로 그대로 옮겨 견준다 — 값을 지어 넣으면 모양이 우연히 같아도 시험이 아무것도 보지 않는다.
  표지 칸 안쪽(contested_by · flipped_from)의 칸 집합, meta.search · used, 별칭 표의 docs 까지 본다.
- 걸리지 않은 행의 contested_by(고친 값과 부딪친 다툼)를 '검증된 철회가 이 걸림을 다퉜다' 로 적으면 틀린 말이다 — 걸린 행만 그
  문구, 아닌 행은 '같은 카드의 다른 판정이 이 행과 부딪쳤다(이 행이 선다)' 와 모델이 쓴 낱말. 두 번째 판정의 방아쇠(D-42 E)는 그대로다.
- 긴 문서 발췌를 댄 카드 밖 줄(src D01 · record_id DOC-…)은 카드가 아니라 앱이 인용을 다시 대조하지 못한다(엔진 checks.quote 만
  있다) — finding 에 카드 인용을 달지 않는다(카드가 아닌 record_id 로 card: 참조를 지으면 dangling 이다).

### M3C-27. 시험대의 흔들림 셋 — 전문가 단위 단계(C3-11)가 드러낸 것
- **같은 틱의 묶음과 검토.** 전문가 단위 단계라 빨리 끝난 묶음의 전문가가 같은 `_spawn` 안에서 검토로 집힌다(운영에서는 맞는 동작).
  시험대는 틱마다 워커를 기다리므로 '첫 틱은 묶음 · 다음 wait=False 틱은 세션' 에 기대던 시험이 경합에 걸렸다(첫 틱이 붙들린 run 을
  기다린다). `Rig.tick(packs_only=True)` 로 그 틱을 묶음만 집게 했다(아홉 자리).
- **동시 워커 시험.** 시간(호출 간격 · 5초 기한)으로 겹침을 재면 바쁜 박스에서 둘 · 넷만 겹쳤다 — 까닭은 거르기의 1순위 대기와 위의
  같은 틱 경합이었다. 거르기를 끄고, 가짜 엔진 `pack_gate` 로 여섯 묶음이 다 집힌 뒤 놓고, run 은 다섯이 함께 돌거나 살아 있는 검토
  워커가 모두 붙들렸을 때 놓는다(틱이 워커를 다 띄운 뒤에만 센다).
- **가짜 엔진의 교착.** 읽다 만 run 스트림 생성기를 GC 가 아무 스레드에서나 거두며 finally 에서 가짜의 잠금을 잡는다 — 그 스레드가
  handle 의 잠금 안이면 `threading.Lock` 이 제 스레드와 교착했다(긴 묶음에서만, faulthandler 스택으로 찾았다). RLock 으로 바꿨다.
  쟁점 · 종합 꾸러미의 가짜 엔진(issue_panel_engine · fake_summary_engine)에도 같은 꼴이 있는지는 그 꾸러미가 본다.

### M3C-28. 변이 검사 · 전체 시험 — 단계 C 둘째 묶음
- `git archive` 사본(`scratchpad/celm3-<pid>-c2*`)에서 60개(C3-7 8 · C3-8 6 · C3-10 4 · C3-11 6 · D-42 1 · B 층 21 · 긴 문서 검색 7 ·
  C3-13 3 · C3-14 5 — 대역 일치의 'noinput q2 를 빼면 붉다' 포함)를 하나씩 넣고 그 규칙의 시험만 돌렸다. 단언 실패만 죽음으로 셌다.
- 첫 판 49 죽음 · 살아남음 9 · 단언 아닌 실패 2. 살아남은 것 — 영역 바닥 상수(보충 표본이 1 을 글로 박아 상수가 floor_met 에만
  쓰였다 → 보충 표본도 상수를 쓴다), 입력 결손 표본의 영향 있음 → risk_miss, 넓힘의 즉시 다시 열기(작은 시험 대상에서는 잡 끝 보충
  표본이 같은 끝 상태를 만든다 — 앞 잡이 거른 셀로 갈랐다), floor_met 의 셈, 불변식 G8, flagged 의 순서 뒤집힘 모집단, 계획 없는
  박스의 k, 고친 값/판정 바꿈 셈(시험이 1 · 1 로 대칭이었다), 카나리아 변이(반출 제외 표를 비우는 것은 그 표가 원래 반출 밖이라 같은
  값이다 → 보고서 카드 머리에 절을 싣는 변이로 바꿨다). 단언 아닌 실패 둘은 TypeError 를 단언으로 고쳤다.
- 고친 뒤 60/60 이 단언으로 죽는다.
- **전체 시험(공유 잠금 아래).** 2,835 통과 · xfail 4 · 실패 0(엔진 c4e4823 예제 사본). 첫 전체 판은 실패 둘이었다 — 건너뜀 예산에
  새 시험(2차 주입의 형제 부재 건너뜀)을 적지 않은 것, 그리고 예제 사본이 엔진과 달랐던 것(마지막 사본 전). ruff 깨끗하다.

### D41. 단계 C 셋째 묶음(S3-5 · 남은 S3-12 · 길잡이) — 정한 것과 남긴 것 (2026-10-14)

- **사슬의 자리와 원자성.** 훅은 셋이다 — `ReviewLoop._finish`(completed 로 바뀐 직후 · 보충 표본이 셀을 다시 열면 오지 않는다) ·
  `runner._finish_job` 의 쟁점 갈래 · 연속 3패널 오류로 실패한 쟁점 잡. 설계서의 `on_synth_closed` 는 두지 않았다 — 종합 워커의 판
  조립(`assemble_report`)이 이미 완결 캐시를 다시 쓴다(두 번 셀 까닭이 없다 — 변이 검사가 같은 값이라 알려 줬다). 모두 앞 잡의 UPDATE 밖에서
  `chain.safe` 로 부른다(터져도 앞 잡을 무르지 않고 로그 — 다음 sweep 이 다시 본다). `sweep` 은 러너 스레드 `chain_loop`(30초)이고,
  살아 있는 검토·쟁점·종합 잡이 없을 때 '마지막으로 끝난 잡'(updated_at · rowid 차례)에 다음 잡이 없으면 그 훅을 한 번 부른다
  (`chain_json.prev_job_id` 로 멱등 — 확인과 쓰기가 한 트랜잭션). 검토 잡은 마감 범위가 다 닫혔을 때만 잇는다.
- **이미 살아 있는 단계.** 쟁점은 살아 있는 쟁점 잡이 있으면 새로 세우지 않는다(그 잡이 새 대기 쟁점을 집는다). 종합은 살아 있는
  쟁점 잡(끝나면 종합을 잇는다)이나 아직 집히지 않은 종합 잡이 있으면 세우지 않는다. **도는 종합 잡은 막지 않는다** — 그 잡이 이미
  끝낸 요약은 옛 입력이라(입력 해시가 같은 done 행은 다시 부르지 않는다) 새 종합 잡이 뒤에 줄을 선다. 세우지 않을 때는 그 살아 있는
  잡의 chain_json 지문(cells_hash · registry_hash · reopened_n · round)을 지금 고르기로 다시 적고 `rearmed_by` 를 단다 — 쟁점을 다
  그대로 둔 다시 고르기는 rr_issues 에도 지문을 남기지 않아 신선도와 '재검토 N셀' 이 앞 고르기에 머물렀다(결정표 ⑬ 이 찾았다).
- **`chain.cells_hash` 를 따로 두지 않았다** — 설계서의 그 함수는 `closure.closing_hash`(마감 범위 셀 지문, S3-8)와 같다. 마감 범위의
  전문가는 `closure.closing_agents` 하나에서 나온다(`chain.scope_open` 도 그것을 쓴다).
- **chain_json 에 `reopened_n` 하나를 더했다**(설계서 칸 + 1) — 사슬 잡을 세울 때 마감 범위 셀의 다시 연 횟수 합이다. 쟁점 선정 뒤
  셀이 다시 열리면 표기가 '후속 낡음(재검토 N셀)' 이고 N 은 지금 합과의 차다(다시 연 횟수라 한 셀을 두 번 열면 2). 고른 적이 없으면
  '쟁점 선정 전', 다시 열지 않고 지문만 바뀌었으면(실패 셀 넘김 따위) '셀 바뀜'. 종합 판이 하나도 없으면 '후속 낡음(종합 전)' — 이제
  사슬이 검토 끝마다 코드 조립 판을 세우므로 '판이 있나' 가 아니라 '종합 판(synth_done)이 있나' 로 가른다.
- **cells 대상의 마감 레벨은 늘 C3** — `routes.close_level_for(flow)`. 대상을 cells 로 열 때 C3, panels 는 박스 손잡이
  (`HWAXRISK_DEFAULT_CLOSE_LEVEL`, 기본 C2) 그대로, 방식을 바꾸면 따라 바뀌고 감사 행 앞뒤에 마감 레벨이 남는다. 설계서는 '비어 있으면
  C3' 였지만 이 열은 늘 패널 손잡이의 스냅샷으로 차 있고 사람이 고르는 길이 없어 방식으로 정했다. **M2 때 연 cells 대상(파일럿)은
  C2 로 남는다**(옮기지 않았다 — 그 대상은 C2 마감으로 돈다). 결정표 ⑥ 은 그 모양을 `UPDATE` 한 줄로 만든다.
- **확인 이력 키의 같은 초 충돌(500)** — `rr_close_acks` 의 키가 (대상, 항목, ack_at)라 취소 뒤 같은 초에 다시 확인하면 IntegrityError
  였다. 그 항목의 마지막 ack_at 다음 초로 적는다(결정표 ⑪ 이 찾았다).
- **regressed 표기** — 셀이 닫힌 채 내려간 것(확인 낡음)에는 '재개방 0셀' 을 붙이지 않는다. 머리 'C2 · C3 대기' 와 잔여 표기가 말한다.
- **issue_yield_low** — 최근 다섯 쟁점 패널(끝난 차례)이 전부 기각(rejected)·불명(undetermined · 결정문 파싱 실패)이면 쟁점 잡
  진행판의 advice. 패널마다 그 패널이 정한 쟁점 결과로 센다(그 쟁점의 outcome_json.panel_id 가 그 패널). 패널이 끝날 때마다 맞추고,
  다음 패널의 진행 줄이 진행판을 새로 쓸 때 머리에도 실어 도는 동안 남긴다. 잡은 멈추지 않는다.
- **길잡이(3.11)** — 진행판(cells 만)에 `stage`(살아 있는, 없으면 마지막 쟁점·종합 잡)·`report`(마지막 판 머리). risk_next_step 은
  쟁점 잡이 살아 있으면 where='issues'(risk_get_issues), 종합이면 'synth'(진행판), 멈췄으면 막힘 chain_paused 와 재개가 맨 앞,
  자격이 없으면 pat_unavailable, 사슬이 끝나면 risk_get_report 걸음과 막음 잔여 residual_unacked(웹에서 소유자·관리자 확인 — Claude
  경로의 확인은 없다), 서술 없이 표만 선 요약의 까닭. 검토 잡 단계 `live`(B 층)는 메모로 그 뜻을 말한다. where 어휘가 둘 늘었다.
- **보안** — PUT /issues/{id} 를 남의 과제 사람이 부르면 404 문구에 그 과제 id 가 실렸다 → 없는 쟁점과 같은 404(셀 꾸러미의
  risk_job_action not_visible 과 같은 규칙). 문서 인용 카드 밖 줄(src D01 · record_id DOC-…)은 보고서에서 카드 근거로 세지 않는다 —
  보고서의 카드 FAIL 수는 rr_card_verdicts(카드 판정 행)만, 주장값의 검증은 카드 인용만(card_only) 본다(바꾼 것 없음 — 확인만).
- **시험이 바뀐 까닭** — 검토 잡 끝에 사슬이 병합·판·쟁점 선정을 하므로 '검토 뒤 등록부 0 · 판 없음 · 캐시 없음 · 판 v1' 을 전제한
  시험을 고쳤다(test_review_findings · test_review_dispose · test_issue_report_routes · test_synth · test_closure 둘 · 결정표 ②~⑦ ·
  test_review_mcp 의 끝난 잡 걸음 · test_target_flow 의 감사 행 · test_runner 의 스레드 여섯).
- **C12 ⑤ · C14** — 2차 주입 문구(판단어 · 따옴표 깨기)는 쟁점 브리프·쟁점 엔진 질문·요약 행에 실제로 갔고 «» 안에만 섰다(고칠 것
  없음). C14 ② — 가짜 요약 엔진의 답 칸을 예제(c4e4823)에 맞췄고 앱의 대조·옮기기가 예제 셋을 그대로 읽는다. C14 ①(쟁점 패널 SSE)은
  단계 D 리허설이 실제 프레임을 긁은 뒤다.
- **2,000셀 실측** — 400명 × 단위 5, dev 전원 검토(RR_FULL=1, 약 110~150초)에서 refresh 0.12~0.46초 · 판 조립 0.16~0.34초(세 번 중
  가장 빠른 값은 0.12 · 0.16). 시험 상한은 1초 · 2초다(tests/rr/test_closure_scale.py — 기본은 영역 대표만 돌아 약 4초).
- **가짜 엔진의 잠금** — issue_panel_engine · fake_summary_engine 에는 잠금도 스트림 생성기도 없다(셀 꾸러미가 찾은 Lock + 생성기 교착
  모양이 없다).
- **남긴 것** — 사람이 종합 잡을 취소해도 도는 요약 호출 하나는 끝까지 간다(SynthWorker 의 멈춤은 프로세스 정지만 듣는다 — 다음 틱부터
  집지 않는다). C14 ①. 단계 D 리허설의 사슬·비우기·쟁점 패널·종합 몫(조정자 보고에 적었다).

## 재설계 M3 — 셀 꾸러미 반대 검토 1차 수리(1ccc007 기준 HIGH 4 · MEDIUM 10 · LOW 6, 2026-10-14)

검토 결과와 조정자의 결정은 스크래치(cells-review1-findings.md)에 있다. 결정 항목(#8 · #12 · #13 · 셀 밖 인용 · #18 · #20)은 그대로
구현했고, 나머지는 검토의 고칠 방향을 따랐다 — 따르지 않은 곳은 아래에 까닭을 적는다.

### M3C-29. HIGH 1 — 입력 결손 q1 의 '영향 있음' 이 사라지던 것
- 겹침의 정체는 (카드 k · 경로 · 줄 l · 제목)이다. 검토는 impact 까지 정체에 넣자고 했지만 따르지 않았다 — 다시 물어 같은 줄이
  모름 → 있음으로 오르면(재현 2) 두 줄이 다 남아 한 영향이 둘로 센다. 같은 정체면 더 센 영향(있음 > 모름 > 없음)이 남는다 —
  '걸림 아닌 줄이 걸림을 갈아 끼우지 않는다' 는 검토의 뜻은 그대로다.
- 엔진은 걸린 줄에 카드와 변경 줄을 달고 없음 줄에는 달지 않는다 — 그래서 '있음 A' 다음 '없음 A' 는 정체가 달라 둘 다 남는다(변이
  시험이 찾았다, 시험 ④ 는 있음 → 모름으로 든다).
- 제목 없는 영향은 버리지 않고 경로 → 이유 → '제목 없는 영향' 으로 제목을 대신하고 `title_fallback` 표지를 단다.

### M3C-30. HIGH 2 — 훑기 u 줄의 부딪침 표지
- 회계의 단위 칸에 `conflict`(engine_conflict — dup_conflict · flipped_from · contested_by)를 싣고, `sweep_signal` 은 표지가 선 '무관'
  (rel no · k 없음)을 unknown(reason engine_conflict)으로 낸다 — 그 셀은 거르지 않고 분류 기록에 까닭이 남는다(D-42 ④).
- `engine_conflict` 가 contested_by 도 본다 — 두 번째 판정의 방아쇠에도 함께 든다.

### M3C-31. HIGH 3 — 사람의 다시가 표본 표지를 지우던 것
- 다시는 표본 · 그림자 표지와 분류 기록(route · route_json)을 남기고 결과만 비운다. 앞 결과는 `was` 에 쌓는다.
- `widened_domains` 가 `was` 도 읽는다 — 넓힘은 쌓이기만 한다(넓힘의 원인 셀을 다시 열어도 되돌아가지 않는다). 사람이 다시 연 셀은
  분류하지 않으므로(human_retry) route 'audit' 이 그대로 남아 정산이 새 결과를 적는다.

### M3C-32. HIGH 4 — 게이트웨이 답 하나가 B 층 단위를 영영 세우던 것
- 정규 JSON 으로 적을 수 없는 답(NaN · 무한 · 홀로 선 서로게이트)은 `unreadable_reply` — 내용 탓(live_error_body)으로 그 호출만 빠진 채 언다.
- 워커의 예상 밖 결함은 `unit_live.note_failure` — 백오프가 지난 미동결 단위의 attempts + 1 · not_before(60초부터 두 배, 비교 후
  쓰기), 여섯 번째에 `live_internal_error` 로 partial.

### M3C-33. MEDIUM 5 · 6 · 7
- 5 — q1 의 flipped_from 도 셀 기록(checks)에 싣는다. 보고서는 '엔진 보충이 앞 답 … 을 갈아 끼웠다(앞 답은 어휘 밖 낱말 … 을 고친
  값)'. '검증된 철회가 이 영향을 다퉜다' 는 걸린 줄(있음 · 모름)만이고, 없음 줄의 다툼은 '같은 카드의 다른 답이 이 줄과 부딪쳤다(이
  줄이 선다)' 와 모델이 쓴 낱말이다.
- 6 — floor_met 은 결과를 낸 표본만 센다(전체와 영역마다). 결과 없는 표본은 도는 중(pending)과 닫힌 실패(failed)로 가른다.
  closure.py 는 고치지 않았다 — floor_met 을 그대로 읽으므로 이제 막는다.
- 7 — 잡 끝 보충 표본은 끝난 잡(취소 · 실패 · 끝남)이 거른 셀도 고르고 셀과 그 전문가 머리를 이 잡으로 찍는다
  (`reopen_filtered(run_id=…)`). 살아 있는 다른 잡의 셀과 다른 잡이 쥔(running) 전문가의 셀은 그 잡에 둔다.
- 7 의 뒤탈은 M3C-45.

### M3C-34. MEDIUM 8(사용자 결정) — 넘긴 셀의 걸림
- `review_cells.cell_hits` = 실효 FAIL · WARNING 과 부딪침 표지 행(카드마다 하나)의 합집합 + q1 있음 · 모름.
- 보고서 원장의 `partial()`(걸림이 있는 넘긴 셀) · `judged()`(검토 + partial)로 점검표 · finding 을 읽는다. 점검표 첫 표지
  '넘긴 셀 — 일부만 판정', finding 은 카드 행만이다(카드 밖 호출은 끝내 못 받았으니 뺀다). 넘김 응답의 `hits` 와 '보지 못한 것' 줄에
  그 수가 든다. 거절은 없다(결정 그대로).

### M3C-35. MEDIUM 9 — 단독으로만 본 카드
- fwd · rev 행이 없고(pair_over) 단독 행에 엔진 표지가 있으면 그 카드 하나의 rev 로 두 번째 판정을 받는다. 원장의 judgement 칸은
  그대로이고 실효 규칙(effective_rows)이 갈림을 보류(split)로 둔다 — finding 후보다.

### M3C-36. MEDIUM 10 · LOW 16 — 두 커밋 사이
- 표본 · 그림자 결과를 `settle_cell` · `settle_noinput` 의 `sample_results` 로 정산과 같은 트랜잭션에 적는다(`note_sample_result` 는
  없앴다). 넓힘(widen)은 그 뒤다 — 사이에서 죽으면 잡 끝(보충 표본 앞)의 `reopen_widened` 가 원장에서 유도해 다시 한다. 분류와
  넓힘이 엇갈린 셀(LOW 16)도 같은 자리가 거둔다.
- 불변식 G9 — 닫힌 표본 · 그림자 셀에는 결과가 있다. 결과를 지우면 G9 가 서는 시험을 따로 두었다(종전 시험은 빈 불변식만 보았다).
- 훑기를 원장에서 다시 읽는 길도 그 넘김의 다시 열기를 이어 한다(멱등). LOW 15 의 잡 끝 거두기가 같은 틈을 덮어 이 줄을 지우는 변이는
  살아남는다(같은 끝 상태 — 다시 열기가 잡 끝으로 늦을 뿐이다). 곧바로 여는 길을 남겼다.

### M3C-37. MEDIUM 11 · 셀 밖 인용(사용자 결정)
- 반출의 `_clip_extras` 가 입력 결손 q1 의 cq 와 그 다툼의 cq 를, 판정 행 반출이 checks_json 의 다툼 cq 를 200자로 줄인다(원래 길이는
  `<칸>_chars`). 셀 하나 REST 가 같은 함수를 지난다.
- `registry_payload`(merged_json 원문 칸까지 — `_export_view` 를 먼저)와 `claims_for_ref` 도 같은 규칙이다(REST · MCP 같은 함수).

### M3C-38. MEDIUM 12 · 13(사용자 결정)
- `routes.mcp_job_brief` — 범위의 목록 칸은 앞 5 이름과 `<칸>_n`, 워커 신호는 앞 3(칸 여섯)과 `workers_n`. REST 진행판은 전부를 싣는다.
- 규모 시험의 길잡이는 그동안 소스 단계에서 멈춰 길잡이 몫을 재지 못했다(합성 과제는 소스 행 없이 스냅샷을 만든다). 소스를 잠시 붙여
  대상 단계까지 걸어 잰다 — 줄이지 않으면 359명 · 워커 8 에서 27,921자였다. 진행판(risk_get_coverage)은 검토 순서를 줄여 맞추므로
  잡 칸을 줄이면 그만큼 순서 · 좌석이 더 실린다.
- risk_job_action 의 consent — retry_failed 만(다른 action 에 주면 E100). 도구 설명과 길잡이의 다시 단계 why 가 '사용자에게 동의를
  받은 뒤에만 true' 라고 말하고, 길잡이는 args 에 채우지 않는다(SEC-4 와 같은 까닭). 잡 params 에 consent_source mcp 가 남는다.

### M3C-39. MEDIUM 14 — B 층의 취소 · 폐기
- ensure 가 시작 · 호출마다 앞 · 얼리기 앞에서 멈춘다 — stop 은 `should_stop_review(poll_s=0)`(취소 · 사람의 정지 · 앱 종료, 매번
  새로 읽는다)이고, 과제 폐기는 ensure 가 따로 본다. 멈추면 아무것도 얼리지 않는다 — 받은 답은 rr_brief_calls 에 남아 다음 잡이 다시
  부르지 않고 쓴다(폐기면 그것도 적지 않는다).
- 확인과 쓰기 사이에 끼는 폐기는 쓰기가 막는다 — 얼리기 · 다시 하기의 UPDATE 에 `NOT_PURGED_SQL`, `LiveSource._record` 는 확인과
  쓰기를 한 트랜잭션에 둔다(store.tx 는 RLock + BEGIN IMMEDIATE 라 폐기의 트랜잭션과 엇갈리지 않는다).
- 알려진 틈 — 마지막 확인 뒤 · 얼리기 앞에 취소가 끼면 그 단위들은 언다. 그 잡 안에서 받은 정상 답이라 해가 없다고 보았다.

### M3C-40. LOW 15 — 카드 밖 넘김
- `review_cells.handoffs` 가 훑기(머리 sweep_json)와 카드 밖 호출(셀 handoffs_json — 그 셀의 단위) 둘을 읽고 분류 7번 줄이 둘 다 센다.
- 거른 뒤에 온 카드 밖 넘김은 잡 끝(보충 표본 앞)이 거둔다(`reopen_handed_off`). 곧바로 열지 않은 것은 카드 밖 커밋과 다시 열기 사이의
  죽음까지 한 자리에서 거두려는 것이다. 셀의 잡 결속은 그대로다(reopen_widened 와 같다 — 끝난 잡의 셀이면 다음 잡이 돌린다).
- 자기 넘김은 세지 않는다. 7번 줄이 세지 않으니 거두기가 세면 다시 걸러지고 잡 끝이 그것을 되풀이해 잡이 끝나지 않는다(시험이
  60틱으로 잡는다).
- 가짜 엔진의 handoff_to 는 handoff_unit · handoff_from 이 있으면 카드 밖 h 줄을 내지 않는다. 모든 전문가의 카드 밖 넘김이 분류보다
  먼저 오느냐가 실행마다 달라 거르기 시험의 흐름을 갈랐기 때문이다. 카드 밖 넘김은 `offcard_handoffs` 로 낸다.

### M3C-41. LOW 17 — 남의 대상의 404
- `routes._target_editor` — 구성원이 아니면 없는 대상과 같은 글('타깃(<부른 사람이 준 열쇠>)')이고, 등급 미달 403 은 그대로다. 셀
  쓰기(다시 · 넘김 · 보류 풀기)와 `_editable_target`(단위 세우기 · 방식 바꾸기 · 보고서 다시 내기 · 쟁점 결정)에 건다.
- 쟁점 결정(PUT /issues)은 부른 사람이 대상 열쇠를 주지 않으므로 없는 쟁점과 같은 글로 바꾼다. 쓰기 문만 바꾸면 그 길에서 대상 열쇠가
  샌다. 쟁점 · 종합 꾸러미의 경로라 보고에 그 hunk 를 적는다.
- 손대지 않은 같은 꼴(셀 꾸러미 밖)이 있다. POST /targets/{key}/jobs, 좌석 상태 바꾸기, 패널 다시 앉히기, 사람 finding, MCP
  risk_start_job(entry.start_job)은 아직 '과제(<id>)' 다.

### M3C-42. LOW 18(사용자 결정) — 다시 연 횟수와 요청 캐시
- 요청 열쇠의 `|r…` 는 route_forced 가 human_retry 일 때만 붙는다. 입력 바뀜은 입력 지문이 이미 열쇠에 든다.
- 짝으로 셀의 요청 캐시를 그 셀의 started_at 이후 받은 답으로 묶었다. 캐시는 같은 시도의 이어 돌기 몫이라 답의 판정 행이 원장에
  남아 있어야 한다(`_commit` 은 다시 쓴 답을 적지 않는다). 입력이 A → B → A 로 돌아온 셀은 그 행이 지워졌는데, 결정대로 `|r` 을
  빼자 A 의 앞 답을 다시 써 빠진 카드 재질의 · 단독 여섯 · 차감으로 번졌다(시험에서 엔진 호출 14 대 4).
- started_at 은 입력 바뀜에서만 새로 찍히고 이어 돌기 · 사람의 다시에서는 남는다(사람의 다시는 `|r` 이 맡는다). M2 원장의 이어
  돌기는 그대로 맞는다.

### M3C-43. LOW 19 · 20
- 19 — ensure 의 `clock` 으로 얼린 행의 frozen_at · updated_at 을 적는 순간의 시각으로 단다. not_before 의 기준은 시작 시각 그대로다.
  clock 이 없으면 준 now(직접 부르는 시험의 옛 동작)다. 루프는 제 시계를 넘긴다.
- 20 — 사용자 PAT 시야의 tools/list 에 없는 도구는 live_denied(#55)이고, 모르는 키 · 빠진 필수 키만 live_schema_mismatch 다
  (`schema_gap` 이 (코드, 글)을 돌려준다).

### M3C-44. 공유 파일에서 바꾼 곳(합류 때 볼 것)
- entry.py — `job_action` 의 consent(시그니처 · 다른 action 거절 두 줄 · CellsRetryBody 전달), `_cells_answer` 의 facts.review_job
  (mcp_job_brief)과 다시 단계 why.
- mcp_server.py — risk_get_coverage 의 review.job(mcp_job_brief), risk_job_action 의 consent(시그니처 · 설명 · 전달).
- review_runner.py — dispose_cells(hits), `_IMPACT_RANK` · `_q1_identity`, `_request_hash` · `_cached`, `_sweep`(원장 길의
  `_replay_handoffs`) · `_replay_handoffs`, `_handoffs_to`, `_solos`, `_noinput` 겹침, `_settle` · `_sample_results`, `_audit_topup`,
  `_work_live`. `_finish` 는 손대지 않았다.
- routes.py — `_target_editor` · `_editable_target` · post_undefer · `_dispose` · put_issue(쟁점 · 종합 꾸러미의 경로) ·
  registry_payload · claims_for_ref · `mcp_job_brief`.
- closure.py · runner.py · synth.py · chain.py 는 손대지 않았다.

### M3C-45. MEDIUM 7 의 뒤탈 — 셋 중 하나꼴로만 붙던 시험
- 낮은 바닥 · 뒤 잡의 놓침 시험이 보충 표본이 끝난 잡의 거른 셀까지 점수 순으로 고르게 되자 셋째 잡이 b2 를 고를지가 대상 열쇠마다
  바뀌었다. git archive 두 사본으로 갈랐다(59ab45d 에서 6/6, 61ed736 에서 2/6). 수리 때는 한 번 붙어 지나쳤다.
- 잡 소금을 골라 b2 가 첫째가 되게 얼렸다(시나리오는 그대로). 표본 점수로 고르는 셈을 바꾼 뒤에는 그 시험을 여러 번 돌린다.

### M3C-46. 변이 검사 · 전체 시험 — 반대 검토 수리
- 변이를 짜며 비어 있던 시험 셋을 먼저 더했다 — G9 가 실제로 서는지, 자기 넘김으로 잡 끝이 되풀이되지 않는지, 마지막 호출 도중의
  취소 · 폐기(얼리기 앞의 확인).
- `git archive` 사본(`scratchpad/celm3-<pid>-r1` · `r1b`)에서 49개(HIGH 11 · MEDIUM 26 · LOW 12)를 하나씩 넣고 그 수리의 시험만
  돌렸다. 단언 실패만 죽음으로 셌다.
- 첫 판은 39 죽음 · 살아남음 3 · 단언 아닌 실패 7 이었다. 살아남은 것 가운데 둘은 q1 의 정체를 제목만으로 보는 변이와 걸림 아닌
  줄이 걸림을 갈아 끼우는 변이다 — 시험이 남는 줄 전부를 보지 않았다(①은 둘 다 남는지, ④는 약해진 같은 줄로 고쳤다). 단언 아닌
  실패(ValueError · KeyError)는 단언으로 고쳤다. 잡 칸 줄이기를 지운 변이는 KeyError 로만 넘어졌다 — 진행판은 순서를 줄여 맞추고
  길잡이는 소스 단계에서 멈췄기 때문이다(M3C-38).
- 고친 뒤 48/49 가 단언으로 죽는다. 남은 하나(원장 길의 넘김 다시 열기를 지우는 변이)는 잡 끝 거두기가 같은 끝 상태를 만드는 같은
  값 변이다(M3C-36).
- **전체 시험(공유 잠금 아래).** 2,882 통과 · xfail 4 · 실패 0(종전 2,835). ruff 깨끗하다.

### D42. 반대 검토 1차(review1) 첫 단계(phase A) — 셀 꾸러미가 손대지 않는 파일의 고침 (2026-10-14)

- **H1 · H2 · L5 — 종합 워커.** 같은 입력의 요약을 다시 쓸 때 그 행을 새 잡의 것(run_id)으로 표지한다(아니면 잡이 제 요약을 못 찾고
  '계획' 만 되풀이했다). 워커는 대상마다 가장 오래된 잡 하나를 두고 가장 오래 집지 않은 대상을 집는다(한 대상이 묶여도 다른 대상의
  종합이 줄에 묶이지 않는다). 재기동 복구가 running 요약을 대기로 돌린다(차감 없음 — 러너 `_begin`). updated_at 을 쓰기마다 적는다.
- **M4(종합 몫).** 종합 판은 같은 트랜잭션에서 지금 셀 지문의 판 행을 먼저 세우고 그 위에서 센 뒤 채운다 — 자기 판 표기가 '후속
  낡음(종합 전)' 이던 것. 내용이 같으면 그 행을 지운다. 확인(ack)이 판을 세우는 갈래는 둘째 단계(routes).
- **M8(결정).** 검토 잡을 만들 때 params_json.chain 표지 — 표지 없는 잡(M2 코드가 세운 잡)은 사슬 훅이 병합·판도 하지 않는다
  (reason pre_m3_job). 사람이 쟁점·종합을 시작하는 길잡이 걸음은 둘째 단계(entry · routes).
- **L6(결정).** registry.target_purged 를 같은 트랜잭션에서 본다 — 패널 결과 원문 저장 · 도구 호출 기록 · 원장 앉히기(두 자리 —
  답을 받은 뒤 · 종료 모델 재확인 뒤) · 요약 닫기 · 요약 호출 원장(원문만 뺀다) · 보고서 판(409 project_purged). 종합 워커는 취소·끝난
  잡을 되살리지 않는다. **새로 본 것** — 폐기(PURGE_BLANK_SQL)가 rr_panels.result_gz(엔진 결과 원문 — 결정문·발언이 든다)를 비우지
  않는다. 폐기 전에 적힌 원문이 폐기 뒤에도 남는다 → 둘째 단계(routes.py)에서 고친다. PUSHED_DDL_SHA256[5] 는 잠정 그대로.
- **M2.** 결과 칸(outcome_json)의 원자를 결과·등록부와 같은 (sev3, 판정, finding id) 로 고른다. 가짜 쟁점 패널 엔진에 같은 닻 원자를
  더 내는 대본(also).
- **H3(결정) · L1(결정).** 결과가 있는 쟁점(outcome 이 있다)은 다시 고르기가 상한으로 밀어내지도 결과·패널을 지우지도 않는다.
  근거가 바뀌면 reraised_json(at · round · 바뀐 근거 해시 · 패널 때 근거 해시 · 제기·반대 들고 남 · 주장값 앞뒤 — 같은 바뀐 근거면
  처음 것을 둔다)을 적고, 상한에 자리가 있으면 새 근거로 다시 줄을 선다(state_reason reraised — 새 패널의 결과가 바꾸며 그때 표기를
  내린다), 없으면 결과 쟁점 그대로다. 다시 섰다가 잡이 취소돼 돌아온 것도 reraised_json 이 있어 다음 자리에 다시 선다. 이미 줄을 선
  결과 쟁점의 근거가 또 바뀌면 새 근거만 적는다. 등록부는 그 결과를 낸 패널(outcome_json.panel_id)의 덮어쓰기와 before_issue 를
  새 패널이 바꿀 때까지 두고(새 패널이 편성·도는 동안에도) merged.issue_reraised 에 '패널 판정 — 근거 바뀜, 다시 토의 필요'
  (registry.REARGUE_LABEL)를 단다. 보고서 쟁점 줄도 그 표기와 바뀐 사람을 싣는다. 결정문을 못 읽어 다시 설 때도 앞 결과를 둔다.
  사람의 올리기·건너뛰기(status_source human)는 다시 고르기가 건드리지 않고(상한 밖으로 올린 것도), 패널이 판정하면 그 결정은
  끝나 코드 상태로 돌아간다. 잔여 표(closure)·길잡이(entry)의 표기는 둘째 단계다.
- **H4 · M1(결정).** 놓이는 쟁점의 대상에 살아 있는 쟁점 잡이 없으면 대기로 두지 않는다 — untried_cap(chain_cancelled · 마지막 잡이
  실패면 job_failed). 쟁점 잡의 자격 실패는 보류 credential 로 멈춘다(패널은 시작 못 한 것처럼 — credential_hold 는 연속 오류에
  세지 않는다, 재개가 보류 열을 비운다). 정말로 실패로 끝난 쟁점 잡은 남은 대기를 untried_cap(job_failed)로 놓고 종합을 잇는다
  (연속 오류는 종전대로 engine_fail — 더 구체적인 까닭이라 두었다). 놓을 때 결과 쟁점은 미토의가 아니라 결과 쟁점으로 돌아간다.
- **H5 의 등록부 몫은 두지 않았다.** registry_rows 는 웹 REST 의 행 모양(merged_json · merged 둘 다)이고 패널 바이트 동일 시험의
  열이라 바꾸지 않는다 — MCP 응답에서 줄이는 것은 둘째 단계(mcp_server · routes)의 와이어 맞춤이다.
- **L5 의 나머지.** closure_hash · summary_ids_json · chain_json 의 대부분은 감사·재현용으로 남긴다(읽는 곳 없음 — 지우지 않는다).
  registry_hash 는 M3 고침(둘째 단계)이 읽는다.

### D43. 반대 검토 1차(review1) 둘째 단계(phase B) — 셀 꾸러미 1차 수리를 합친 뒤의 고침과 남 숨김 훑기 (2026-10-15)

- **M6 · M7 · 새로 본 것(result_gz) · L4.** 반출은 쟁점 패널이 옮겨 적은 카드 글도 판정당 200자다 — 쟁점 패널 finding(인용 · 근거 문장) ·
  패널 결정문 · risk_spec · 보고서 판 쪽의 «» 서술. 전제 확인 — 판의 쪽에 카드 글이 실리는 길은 쟁점 패널이 아니라 요약 서기가 행 글을
  서술에 옮겨 적을 때뿐이라 시험은 가짜 요약 엔진의 para 대본으로 그 길을 세운다. 폐기는 rr_registry.merged_json 과 rr_panels.result_gz 를
  비운다(행 · 해시 · 수는 남는다). 들여오기는 확인 취소(revoked_at)와 사람의 쟁점 결정(status_source human)을 사람의 확정으로 읽는다.
- **M5(결정) — 깊이는 카드로 본 전문가만.** active · need · have 모두 카드로 본 전문가로 세고, 카드로 본 사람과 섞인 영역의 카드 없는
  사람 수는 막지 않는 잔여 depth_no_cards 에 '<영역>(그중 N명)' 으로 선다. 지적의 다른 반쪽('표기가 까닭을 말하지 않는다')도 고쳤다 —
  셀이 다 닫혔는데 깊이 때문에 C2 가 아니면 표기에 '깊이 미달 <영역> have/need'(다섯 영역까지, 나머지는 '외 N영역')가 붙는다.
  D-38 시험의 셋째 칸(카드 가진 영역에 0장 한 명 — 막힘)은 결정대로 '막히지 않고 잔여에 이름' 으로 고치고, 카드로 본 사람의 셀이 다
  실패해 정말로 미달인 칸을 더했다.
- **M3.** 종합 판의 신선도는 셀 지문과 등록부 지문(rr_reports.registry_hash)을 함께 본다 — 종합 뒤 사람이 상한 밖 쟁점을 올려 패널이
  판정하면 셀은 그대로여도 '후속 낡음(보고서 판)' 이다. 종합 판 행을 먼저 세울 때도 등록부 지문을 단다(빈 값이면 조립 중 판정이 그 판을
  늘 낡음으로 읽어 첫 단계 M4 가 되살아난다).
- **M4(확인 몫).** 확인과 확인 취소가 트랜잭션 밖에서 판(trigger ack)을 세우고 응답에 report_version 을 싣는다. 설계(m3-synthesis 3.8)는 확인만
  말하지만 취소도 표기를 내리므로 판을 세운다 — 마지막 판의 표기가 늘 지금 완결 표기다.
- **H3(결정)의 잔여 · 길잡이 몫.** 결과 쟁점인데 reraised_json 이 있는 것(상한에 자리가 없어 다시 돌지 못했다)은 잔여 issues_reraised —
  늘 막음, 확인으로 넘긴다, 집합 해시는 (쟁점 id, 바뀐 근거 지문), 행에 쟁점 id 20개까지. 길잡이 notes 에 표기 · 쟁점 id(10개까지) ·
  다시 올리는 길(웹 · REST PUT /api/issues/<id> queue — 사람의 결정은 상한 밖이어도 된다) · 넘기는 길(잔여 확인)이 한 줄 선다. 다시 줄을
  선 것(queued)은 쟁점 진행에 든다.
- **M8(결정)의 길잡이 몫.** 마지막 검토 잡이 끝났는데 사슬 표지가 없고(M2 시절 잡) 사슬 잡이 없으며 대기 셀도 없으면 길잡이가
  risk_start_job(mode='reviews') 걸음과 까닭을 준다. 그 잡은 셀이 다 닫혀 있어 검토 호출 없이(묶음 · 한도 조회뿐) 곧바로 끝나고 그 끝에서
  사슬이 선다 — 새 라우트 없이 표지 있는 잡 하나로 사람이 시작한다. 종합만이면 REST POST /report {refresh_summaries:true}. 얼린 v4
  원장으로 걸음을 실제로 따라가 본다.
- **L3(결정).** 쟁점 쪽은 쟁점 id 순이다(REST · MCP 같은 함수 — REST GET /issues 도 쪽이 있어 같이 바뀐다, 순위는 행의 rank). 등록부는 쪽으로
  나눌 때(MCP — limit 이 있을 때)만 (family_key, cluster_key) 순이고 한 번에 다 주는 REST(웹)는 주의 등급 순 그대로다. family_key 는 행
  모양(REST · 패널 바이트 시험)에 없는 열이라 따로 읽는다. ledger_rev = 거른 목록 전부(등록부는 merged 를 뺀 행 — merged_json 과 같은
  내용)의 sha256 앞 16자. 도구 설명이 '앞 쪽과 다르면 offset 0 부터' 를 말한다.
- **H5.** MCP risk_get_registry 의 행은 merged_json 을 빼고(행의 4할), 한 행 쪽이 아직 넘으면 merged 의 목록을 20 → 5 → 1 → 0 개로 줄이며
  원래 길이를 merged.lists_total 에 적는다 — next_offset 은 그대로 온다. REST 행은 그대로다(첫 단계 판단 그대로).
- **M9 · 셀 꾸러미 MEDIUM 12.** mcp_job_brief 안의 줄이기(목록 칸마다 앞 다섯과 <칸>_n)를 _mcp_heads 로 떼어 그대로 쓰고(동작 같음),
  MCP 진행판의 qualifiers 에도 같은 규칙을 건다(mcp_qualifiers — 수 · 표기 · 확인 상태는 그대로, 전부는 REST GET /closure). M9 의
  60단위 범위 몫은 mcp_job_brief 가 이미 막는다(중복 구현 없음). 길잡이에는 잔여 목록이 실리지 않는다(표기만).
- **L2 · 남 숨김 훑기(조정자 추가 1).** 규칙 한 곳 — routes._member_or_missing: 구성원이 아닌 남은 그 경로의 '없다' 답과 같은 404,
  구성원의 등급 미달은 403 그대로(셀 꾸러미의 _target_editor 도 이것을 쓴다). 고친 자리 — 확인 · 확인 취소(L2), 잡 만들기, 좌석 상태,
  패널 다시 저장, 사람 finding, 요구 결정, MCP risk_start_job. 훑기 시험이 더 찾은 것 — 재동기(남에게 403 → 404, 구성원은 403), 비공개
  등록부 행의 공개 토글(403 → 404 — 조직 공개 행은 남도 보므로 403, set_status 가 이미 쓰던 규칙에 맞췄다), 요구 승계의 남의 원본(403
  not_a_member → 없는 원본과 같은 source_project_not_found, 구성원은 403), MCP 패널 결과 제출(소유 확인 전에 issue_panel_web_only 로 종류까지
  말했다). 옛 시험 둘(test_external_sync 재동기 · test_registry 공개 토글)을 새 규칙으로 고쳤다.
  - 시험(tests/rr/test_review1_stranger.py)은 라우터의 쓰기 경로 51 · MCP 도구 31 의 표가 라우터 · 서버와 같은지 보고, 칸마다 남의 답이
    404(MCP 는 not_visible · E404)이고 준 id 를 지운 뒤 없는 id 의 답과 같으며 과제 id 가 없고(대상 열쇠는 준 때만 — 사람 finding id 처럼
    준 id 가 대상 열쇠를 품는 것도 준 것이다) 주인으로는 404 가 아닌지 본다. 남의 것을 가리키는 인자가 없는 경로는 까닭과 함께 면제(로그인 ·
    자기 설정 · 관리자 어휘 · 자기 지표 · 들여오기 — 들여오기는 따로 준 열쇠 말고 주인의 값이 없는지 본다). 남의 행을 읽지 않고 제 행만
    쓰는 경로(새 과제 · same-as 결정)는 성공이 남의 답이다. MCP 역색인은 보이는 과제로 좁힌 빈 목록, 브리프는 토큰 대조가 먼저다.
    원장은 모듈마다 한 번 세워 시험마다 디렉터리를 복사한다(75칸 4초).
  - **고치지 않고 남긴 것(보고 — 훑기 범위 밖의 읽기 설계)** — 새 과제의 predecessor_project_id 는 소유를 보지 않고 적힌다. 남이 주인의
    과제 id 를 앞 과제로 적으면 그 남의 risk_similar_projects 계보 경로가 그 과제의 code 를 싣는다(계보 · 벡터 경로는 본래 코퍼스 전체의
    과제 id 를 싣는 설계라 소유 거름이 없다). 들여오기는 이미 아는 PK 가 남의 것이면 owner_conflict 로 그 존재만 드러난다(있는 PK 에 새
    행을 넣을 수 없으니 본래 그렇다).
- **바깥에 닿는 것(포털 문서 · 화면 몫 — 조정자에게 넘긴다).** 새 잔여 issues_reraised · 확인 응답의 report_version · REST GET /issues 의
  순서(쟁점 id) · 쪽의 ledger_rev · MCP 등록부 행에 merged_json 없음과 merged.lists_total · MCP 진행판 잔여의 <칸>_n · 재동기 · 공개
  토글 · 요구 승계의 남 답(404).

### D44. 남 숨김 훑기 둘째 — 받은 과제 · diff id 를 거쳐 읽는 자리 (2026-10-15)

- **앞 과제(조정자 결정).** 새 과제(REST · MCP risk_create_project)의 predecessor_project_id 는 부른 사람이 구성원인 과제여야 한다 — 남의
  과제는 없는 과제와 같은 404('앞 과제(<id>) 를 찾을 수 없습니다.')이고 아무것도 만들지 않는다(MCP 입구의 '같은 code 면 기존 과제' 갈래보다
  먼저다). 관리자는 있는 과제면 된다. 종전에는 그대로 만들어 그 남의 유사 과제 계보 경로가 주인 과제의 code 를 실었다.
- **계보.** brief._lineage 하나가 유사 과제의 계보 경로와 좌석 기억(E7)의 순위 계보를 같이 낸다 — 그 과제의 소유자가 구성원인 과제만
  싣고 건너 따라간다. 보는 사람은 인자가 아니라 그 과제의 소유자다(부르는 쪽이 넘기다 빠뜨릴 자리가 없다 — REST 는 소유자만, MCP 는 그
  행의 소유자로 부른다). 앞 과제 링크를 만들 때 막아도 그 전에 선 링크와 들여오기로 선 링크(들여오기는 앞 과제를 보지 않는다)가 남의
  과제를 가리킬 수 있어 읽을 때도 거른다.
- **선례.** REST GET /precedents 는 받은 diff 의 소유를 보지 않아 남의 diff 스냅샷의 subject · 규칙 적중을 실었다 — 이제 소유자의 diff 만
  (없는 diff 와 같은 404). MCP 는 범위를 본 뒤 그 행의 소유자로 부르므로 그대로다. 유사 과제(REST 소유자만 · MCP 범위) · 요구 승계(둘째
  단계 D43) · 참조 풀이(GET /refs — 종류마다 소유자 거름) · 길잡이의 앞 과제 스냅샷(소유자만)은 이미 같은 규칙이었다.
- **들여오기 owner_conflict(조정자 결정).** 그대로 둔다 — 부른 사람이 이미 쥔 PK 의 존재만 드러나고 PK 유일성이 설계다(자리에 한 줄 주석).
- **남긴 것(보고).** 좌석 기억(E7)은 계보와 상관없이 같은 좌석의 의견을 소유자 거름 없이 읽는다(rr_seat_opinions.owner_sub 를 보지
  않는다) — 계보 거름은 남이 링크로 주인 과제의 의견을 골라 올리는 것만 막는다. 유사 과제의 벡터 · 서술 경로는 코퍼스(§0.6) 전체의 과제
  id 를 싣는 설계다. 둘 다 받은 id 를 거쳐 읽는 자리가 아니라 이번 규칙 밖이고 다음 검토에 넘긴다.

### D45. 남 숨김 훑기 셋째 — 좌석 기억(E7)과 유사 과제의 벡터 · 서술 경로 (2026-10-15)

- **좌석 기억(E7).** SQL 이 타깃 소유자가 구성원인 과제(소유자 · rr_project_members)의 의견만 읽는다. 대상 행이 없어 과제를 모르는
  의견도 읽지 않는다. 종전에는 같은 좌석의 의견을 소유자 누구든 읽어 남의 과제 발언이 패널 프롬프트와 보고서에 실렸다(D44 가 남긴 것).
- **유사 과제.** 보는 사람은 그 과제의 소유자다(계보와 같은 사람, D44). 벡터 · 서술 경로는 그가 구성원인 과제만 후보로 삼고 corpus_n
  (벡터 문턱 5)도 그 안에서 센다 — 남의 과제는 목록에도, 수와 문턱으로도 드러나지 않는다. 서술 rank 는 실은 것끼리 1 부터 센다(걸러
  낸 적중이 빈칸으로 드러나지 않게 — 자기 · 과제 모름 적중의 빈칸도 함께 없어졌다). subject 경로는 owner_sub 없는 호출도 그 소유자로
  거른다. REST · MCP · 브리프(E5 · E6 의 원천)가 같은 함수라 함께 막힌다.
- **'구성원' 은 하나.** brief._MEMBER_OF 는 `_member` · routes.project_role 의 '남' 판정을 rr_projects 위 조건 하나로 쓴 것이다. 조직
  공개(mcp_visibility='org')는 넣지 않았다 — 남의 과제를 건너 찾는 것은 기본 기능이 아니고, 원하면 명시적 조직 공개 선택지로 따로
  만든다(조정자 결정).
- **그대로 둔 것(보고).** subject 경로는 남이 조직 공개로 연 등록부 행(registry.set_visibility — 다른 신원의 E5 · 유사 과제가 본다)을
  종전대로 싣고, 그 과제가 merged 에 들면 E6 이 그 과제의 성격 진술을 싣는다. E6 의 '코퍼스 n_projects' 는 전체 과제 수다. MCP 는 그
  행의 소유자로 부르므로(D44) 구성원 · 조직 공개로 들어온 호출자는 소유자의 시야를 본다. E7 2차 경로와 서술 경로의 AIDataHub 회수는
  전체 색인에서 고른다 — 서술은 거른 뒤 k 보다 적게 올 수 있다(지금은 호출자가 adh 를 넘기지 않아 운영에서 닿지 않는다, P-12).
- **시험 · 변이.** tests/rr/test_review1_stranger_recall.py 셋 — 남(과제 · 대상 · 더 새 의견 · 대상 없는 의견 · 비공개 등록부 행 ·
  끼어든 서술 적중)을 더하기 전과 뒤의 주인 답이 같고(E7 · 함수 · REST · MCP) 주인과 구성원 과제의 것은 그대로 선다. `git archive`
  사본에서 변이 15(원래 코드 · E7 다섯 · 구성원 절 · 유사 과제 여덟)가 전부 단언으로 죽었다. 전체 시험(공유 잠금 아래) 3,064 통과 · xfail 4 · 실패 0(종전 3,061).

### D46. 남 숨김 훑기 넷째 — D45 가 남긴 넷을 닫는다(조정자 결정, 2026-10-15)

- **조직 공개 행(1) · E6 수(2).** subject 경로는 남이 연 등록부 행을 그대로 싣는다(그 주인이 연 것). E6 은 타깃 소유자가 구성원인 과제의
  성격 진술만 싣고 n_projects 도 그 안에서 센다 — 그 행으로 merged 에 든 남의 과제는 그 행만 E5 에 선다.
- **MCP 교집합(3).** risk_similar_projects · risk_get_precedents 는 다른 과제를 소유자의 구성원 과제와 부른 사람이 볼 수 있는 과제
  (routes.visible_projects)의 교집합으로만 싣고 센다(벡터 · corpus_n · 계보 · subject · clusters). 계보는 그 밖의 과제를 건너 따라가지도
  않는다 — 걸음 수가 숨긴 과제를 드러낸다. 비공개 등록부 행은 보는 과제의 것만, 조직 공개 행은 그대로다. 범위 판정 · 쓰기는 소유자로
  돈다(D44). 브리프(REST · MCP) · 길잡이 · same-as 는 부른 사람이 곧 소유자여야 열려 해당이 없다.
- **AIDataHub(4).** 클라이언트가 supports_project_filter(찾기 인자 project_ids)를 밝혀야 찾고, 찾을 때 보는 과제 목록을 넘긴다. 아니면
  건너뛰고 까닭을 남긴다(서술 reason 'adh_unscoped …' · meta.external_search 'adh_unscoped' · E0 외부 검색 가용=false). 지금의 AdhClient 는
  밝히지 않아 배선해도 닫힌 채다. 서술 경로의 받은 뒤 거름(D45)은 그대로 둔다.
- **남긴 것(보고).** 선례의 pattern_candidates 는 rr_patterns 를 소유자 · 공개 거름 없이 전부 싣는다(라우트의 패턴 목록은 owner_sub ·
  조직 공개로 거른다) — 이번 넷 밖이다. 이미 적힌 인용(등록부 · 보고서의 reg: 참조)은 그 대상의 원장 내용이라 거르지 않았다.
- **시험 · 변이.** 시험 셋을 더했고(E6 · MCP 구성원 · AIDataHub) 고치기 전에 셋 다 단언으로 졌다. `git archive` 사본에서 변이 29(D46
  스물둘 · D45 일곱 다시)가 단언으로 죽었다 — 첫 판에서 살아남은 셋(찾기의 과제 목록이 코퍼스 전체인 둘 · owner_sub 없는 subject
  호출)은 시험 원장을 늘려 잡았다(0ca99af). 전체 시험(공유 잠금 아래) 3,067 통과 · xfail 4 · 실패 0(종전 3,064).

### D47. 남 숨김 훑기 다섯째 — 선례 패턴 후보와 다섯 표 훑기(조정자 결정, 2026-10-15)

- **패턴 후보.** 선례의 pattern_candidates 는 그 소유자의 패턴이나 조직 공개로 연 패턴(라우트의 패턴 목록과 같은 거름)이고, 조직
  공개가 아니면 그 패턴을 이룬 과제(그 소유자 원자의 과제 — learning.collect_atoms, refresh_pattern 과 같은 원자)가 모두 보는 과제
  (D46 — 주인의 구성원 과제, MCP 면 부른 사람과의 교집합) 안이어야 한다. 종전에는 모든 소유자의 candidate · known 패턴을 실었다.
- **훑기.** rr_patterns · rr_seat_opinions · rr_registry · rr_findings · rr_targets 의 SELECT 가운데 대상 · 과제 열쇠가 없는 후보 39곳을
  봤다. 고친 것 둘 — E8 의 '코퍼스 n_targets' 는 보이는 과제의 타깃만 센다(E6 과 같은 규칙), 야간 근접 중복 쌍은 한 소유자의
  클러스터끼리만 큐에 올린다(남의 클러스터 · subject 가 앞 클러스터 주인의 큐에 실렸고 그 쌍은 병합할 수도 없다). 이미 막힌 것 —
  subject 경로 · 선례 clusters(D46), 라우트의 목록 · 병합 · 별칭(owner_sub), 공개 토글의 403/404(D43). 안에서만 쓰는 것 — 사슬 · 외부
  동기 잡, learning · metrics 의 지도(의견 · 패턴 · 약한 subject), 패턴 id 셈, 택소노미 재매핑 스크립트.
- **고치지 않고 보고(판단이 필요하다).** ① 등록부 재제기 표기(registry._flag_escalations)는 같은 cluster_key 인 남의 사람 dismissed
  행에 이 대상의 키(by_target)를 쓴다 — 남의 원장에 쓰고 대상 키를 흘린다. 쓰기라 '둘 다 보는 과제' 규칙이 그대로 맞지 않는다 — 같은
  소유자의 행만으로 좁히는 안을 낸다. ② 야간 패턴 마이너(learning.mine_patterns(store), 소유자 없음)는 모든 소유자의 원자를 한 패턴으로
  세고 새 패턴 큐 항목의 sample_claims 에 남의 주장 · 대상 키를 싣는다 — 소유자마다 돌리는 안이 맞아 보이나 UNIQUE(cluster_key_norm) 와
  전역 마이닝 시험이 걸린 설계 판단이다. ③ 코퍼스 통계 — rr_delta_priors(E8 행 · 선례 delta_priors, plan §5.2.2 F 는 소유자 열 없음),
  rr_metrics global 지표, 규칙 백테스트(모든 라벨의 대상)는 소유자를 가로지르는 집계가 설계다.
- **시험 · 변이.** 시험 셋(선례 패턴 · E8 수 · 야간 쌍)이 고치기 전 단언으로 졌다. `git archive` 사본에서 변이 38(D47 아홉 · D46 · D45
  다시 스물아홉)이 단언으로 죽었다 — 첫 판에서 살아남은 둘(조직 공개 예외가 늘 참 · 원자를 모든 소유자에서)은 원자를 모든 후보에서 모으고
  시험 원장을 늘려 잡았다(7218637). 전체 시험(공유 잠금 아래) 3,070 통과 · xfail 4 · 실패 0(종전 3,067).

### D48. 재제기 표기 · 전역 패턴의 보기 · 패널 대화 연결(조정자 결정 둘과 단계 D 리허설 결함, 2026-10-15)

- **재제기 표기(D47 보고 ①).** registry._flag_escalations 는 그 대상 소유자의 행에만 쓴다(같은 소유자만) — 남의 원장을 고치지 않고 이
  대상의 키를 거기 싣지 않는다. 소유자는 merge 가 넘기고 없으면 rr_targets 에서 읽으며, 모르면 아무 행에도 쓰지 않는다.
- **전역 패턴 마이닝(D47 보고 ②).** 마이닝은 전역 그대로다(소유자를 가로지르는 통계 — 델타 선례 · 지표 · 백테스트와 같다, 스키마 변경
  없음). 보기만 거른다 — 새 패턴 큐 항목의 sample_claims 는 큐 주인이 볼 수 있는 과제의 원자에서만 고르고 나머지는 other_projects_n
  (다른 과제 수)으로만, 규칙 승격 응답의 백테스트 표본은 패턴 주인과 결정한 사람 둘 다 볼 수 있는 과제의 대상만 키로 싣고 나머지는
  other_projects_n 으로 센다. n_* · 채점은 전역 그대로다. 다른 보기 — 패턴 목록(라우트)은 셈뿐이고, 선례 패턴 후보는 D47 이 거른다.
  큐 항목의 거름은 마이닝 때 큐 주인의 구성원 과제로 한다(그 뒤 구성원에서 빠져도 이미 실린 표본은 그대로다 — 큐는 주인만 본다).
- **패널 대화 연결(리허설 checks.S4.unlinked_conversations).** engine_client.run 은 대화를 만들면(다시 쓰는 대화도) 스트림을 열기 전에
  on_conversation 으로 러너에 넘기고, 러너가 곧바로 rr_panels.conv_id 를 적는다. 종전에는 패널 끝 · 잡힌 오류에서만 적어 SIGKILL 된 쟁점
  패널이 conv_id 없이 error('restart') 로 남고 그 대화는 고아가 됐다. 재기동 복구는 conv_id 를 그대로 두고 error 에 '포털 대화 <id>' 를
  적는다(코드는 restart 그대로 — 좌석 차감 없음).
- **시험 · 변이.** 시험 다섯(대화 → 통지 → 스트림 순서 · 도중에 죽은 패널의 복구 · 남의 행에 표기 없음 · 전역 큐 항목 · 승격 표본 둘)이
  고치기 전 단언으로 졌다(옛 시험 둘은 병합 대상 행을 세운다). `git archive` 사본에서 변이 14 가 단언으로 죽었다 — 첫 판의 하나(승격 거름이
  합집합이어도 같은 답 — 주인과 결정한 사람이 같았다)는 남이 결정하는 시험으로 잡았다(ae0c24c). 전체 시험(공유 잠금 아래) 3,076 통과 · xfail 4 · 실패 0(종전 3,070).

## 재설계 M3 — 셀 꾸러미 반대 검토 2차 수리(1b1de6d 기준 HIGH 1 · MEDIUM 3 · LOW 3, D-46, 2026-10-14)

검토 결과와 조정자 결정(D-46)은 스크래치의 cells-review2-findings.md 에 있다. HIGH 1(b)는 D-37 이 옛 계약 글(m3-cells.md 210/372)보다
앞선다 — 계약 글은 조정자가 고친다.

### M3C-47. HIGH 1 — 엔진이 받는 걸림을 앱이 버리던 두 곳
- 제목 없는 카드 밖 f 줄은 버리지 않는다. 경로 → 메커니즘 원문 → '제목 없는 카드 밖 위험' 으로 제목을 대신하고 `title_fallback` 을
  단다(q1 과 같은 규칙 — 표지는 기록에만 둔다).
- 입력 결손 q1 · q2 가 단위 소속 줄 밖의 참조를 대면(엔진은 문맥 줄에도 L 별칭을 준다) 버리지 않고 refs_ok 0 · `ref_context` 로 표시한다.
  그래서 q1 이 전부 문맥 줄을 대도 셀은 실패가 아니라 정산된다. 보고서는 영향 줄의 변경 줄 대조와 확인할 것 줄에 '문맥 줄을 댔다(그
  단위 소속 줄이 아니다)' 를 적는다. finding 의 인용은 그 참조를 통과하지 못한 인용으로 싣는다(종전 _noinput_members 의 규칙 그대로).

### M3C-48. MEDIUM 2 — 넘긴 셀의 걸림 셈 = 보고서가 실제로 싣는 것
- 셈과 보고서가 같은 규칙을 읽는다. `review_verify.effective_view`(보고서 원장의 effective 를 옮겼다)와 `candidate_kind` 다. 후보 까닭은
  셋이다 — flagged(실효 FAIL · WARNING), split(실효 undetermined 이면서 변형이 갈림), unjudged_conflict(엔진 부딪침 표지가 선 행인데
  변형이 하나뿐 — 두 번째 판정을 못 받았다).
- unjudged_conflict 는 갈림처럼 무게 1 의 후보(undetermined 로 hold)이고, 점검표 표지 '다툼 표지 — 두 번째 판정 못 함' 과 finding 카드의
  conflict_unjudged 가 선다. 검토한 셀에서는 생기지 않는다 — 부딪침 표지는 두 번째 판정의 방아쇠라 정산까지 간 셀이면 변형이 둘이다.
- `review_cells.cell_hits` 는 갈래를 돌려준다(card · conflict_mark · noinput_yes · noinput_unknown · n). 넘김 응답 `hits_by` 와 보고서
  '보지 못한 것' 줄이 그 갈래와 실린 자리를 말한다(카드 판정 — 점검표 · finding, 부딪침 표지 — 점검표, 영향 있음 — 입력 결손 절 · finding,
  영향 모름 — 입력 결손 절). 필요한 정보 절도 넘긴 셀의 정산된 몫을 검토한 셀과 같은 자리에 싣는다.
- 시험의 함정 하나 — 가짜 엔진에 applies no · OK 를 주면 엔진 계약 밖 짝이라 행이 버려져 빠진 카드 재질의로 번진다. 갈림 시나리오는
  yes · OK 로 짓는다.

### M3C-49. MEDIUM 3 — 잡 끝이 거둔 셀을 지금 잡으로
- 잡 끝의 거두기(reopen_widened · reopen_handed_off)는 셀과 그 전문가 머리를 지금 잡으로 찍는다. 그래서 범위 밖 전문가의 셀도 지금
  잡이 돌린다(MEDIUM 7 의 보충 표본과 같은 규칙, 살아 있는 검토 잡은 대상마다 하나라 다른 잡의 셀을 빼앗지 않는다).
- 훑기의 늦은 넘김 다시 열기(_replay_handoffs)는 제 셀을 뺀다(exclude_agent). 곧바로 연 셀의 잡 결속은 그대로 둔다 — 결정이 찍기를
  잡 끝의 거두기에만 걸었고, C3-7 의 곧바로 넓힘(widen)도 결속을 두어 그 셀을 범위로 잡은 다음 잡이 분류한다. 한때 찍었다가 결정의
  범위로 되돌렸다(037ab3a).

### M3C-50. MEDIUM 4 — 보충 표본의 바닥 셈
- 바닥은 결과를 낸 표본과 아직 결과를 낼 수 있는 표본만 센다. 아직 낼 수 있는 표본은 도는 것과 사람의 처분을 기다리는 실패다(다시
  하면 표지가 남아 결과를 낸다). 넘긴 표본만 그 자리를 다른 거른 셀로 채운다.
- '결과 없이 닫힌 표본' 에 실패를 넣지 않은 것은 해석이다 — 넣으면 같은 까닭의 실패가 그 잡 안에서 영역의 거른 셀을 차례로 실패로
  바꾼다(MEDIUM 6 시험이 거른 셋을 다 실패로 바꾸는 것으로 드러났다). 사람이 넘기면 넘김이 세우는 마감 잡의 끝이 채운다.

### M3C-51. LOW 5 — q1 겹침은 다시 묻기 사이에서만
- 한 답 안의 줄끼리는 합치지 않는다(엔진이 내용 전부로 가려 낸 줄이다). 앞 답들이 남긴 줄의 정체를 그 답 앞에서 떠 두고, 앞 줄 하나는
  이 답의 줄 하나와만 견준다(seen.pop). 영향이 비기면 더 무거운 심각도가 남는다(_q1_strength — 심각도 차례는 보고서의 것).

### M3C-52. LOW 6 — 놓침 증거는 쌓이기만 한다
- 앞 결과를 표지 안(HIGH 3 의 marker.was)에서 표지와 따로(`sample_json.was` — 종류마다 목록)로 옮겼다. 입력이 바뀌어 처음부터 도는
  셀(start_cell 의 _CELL_RESET)은 표지를 지우고 다시 분류하는데, 표지 안에 두면 앞 결과도 함께 지워지고 표지 꼴만 남기면 표지가 선
  것으로 읽혀(G9 · 보충 표본) 틀린다. 아직 머지 전이라 옮길 옛 원장이 없다.
- `review_cells.sample_outcomes` 하나를 넓힘 · 완결 몫 · 품질 · 보고서 머리 · 잡 끝 보충 표본이 함께 읽는다. 실효 결과는 지금 결과나
  앞 결과 가운데 놓침이 하나라도 있으면 놓침, 아니면 지금 결과, 없으면 마지막 앞 결과다. 표지가 지워지고 앞 결과만 남은 셀도 표본으로
  센다(보충 표본과 완결 몫이 같은 수 — 거른 셀이기도 하면 한 번만 센다).
- 사람의 다시는 표지가 없어도 앞 결과를 남긴다. 분류 기록(route · route_json)은 표지가 있을 때만 남긴다.

### M3C-53. LOW 7 — 입력 결손 다시 묻기 상한
- 마지막 다시 묻기 뒤에도 '더 있다'(maybe_more)면 셀 기록 extras.noinput.capped 에 적는다(닿지 않은 셀의 기록 바이트는 그대로).
  품질 truncation.noinput_capped{cells} 와 [절단] 줄이 센다 — 보고서 품질 절이 그 줄을 싣는다. 열을 더하지 않은 것은 v5 블록을 건드리지
  않기 위해서다.

### M3C-54. 공유 파일 · 손대지 않은 것
- review_runner.py — dispose_cells(hits_by), 머리의 _SEV_RANK · _q1_strength, _replay_handoffs(제 셀 빼기), _noinput(겹침 · capped),
  _audit_topup(거두기의 run_id). create_review_job · _finish 는 손대지 않았다. entry.py · mcp_server.py · routes.py · closure.py ·
  runner.py · synth.py · chain.py 도 이번 회차에는 손대지 않았다.

### M3C-55. 변이 검사 · 전체 시험 — 반대 검토 2차 수리
- 변이를 짜며 비어 있던 시험을 먼저 더했다 — 앞 잡이 거른 셀을 잡 끝의 넓힘 거두기가 지금 잡으로 찍는지, 표지가 지워진 표본을 보충
  표본과 완결 몫이 똑같이 세는지, 문맥 줄 표기가 영향 줄과 확인할 것 줄 둘 다에 서는지(한 글귀가 두 자리에 같아 한쪽을 지워도 붙었다).
- `git archive` 사본(`scratchpad/celm3-<pid>-r2`)에서 28개(HIGH 1 다섯 · MEDIUM 2 여섯 · MEDIUM 3 셋 · MEDIUM 4 둘 · LOW 5 둘 · LOW 6
  일곱 · LOW 7 셋)를 하나씩 넣고 그 수리의 시험만 돌렸다. 첫 판에 28/28 이 단언으로 죽었다.
- **전체 시험(공유 잠금 아래).** 2,894 통과 · xfail 4 · 실패 0(종전 2,882). ruff 깨끗하다.

## 재설계 M3 — 셀 꾸러미 반대 검토 3차 수리(489f905 기준 HIGH 1 · MEDIUM 2 · LOW 4, D-47, 2026-10-15)

검토 결과와 조정자 결정(D-47)은 스크래치의 cells-review3-findings.md 에 있다. 되풀이되던 어긋남을 끊는 구조 변경이 둘이다 — 넘긴 셀은
검토한 셀과 한 길로 지나고, 살아 있는 잡이 다시 연 셀은 셀만 그 잡에 묶는다(머리는 범위로 찍지 않는다). 이 절의 결정이 2차 기록의
M3C-48(갈래 목록 · '검토한 셀에서는 생기지 않는다') · M3C-49(곧바로 연 셀의 결속 · 잡 끝 거두기의 머리 찍기) · M3C-52(앞 결과만 남은
셀도 표본) 를 대신한다. 그 기록은 그때의 사실이라 고쳐 쓰지 않는다.

### M3C-56. HIGH 1 — 넘긴 셀은 한 길(abeb556)
- 넘긴(skipped) 셀은 검토한 셀과 같은 구성원 함수(MEMBER_SOURCES — 카드 · 카드 밖 · 입력 결손)를 가진 자료 그대로 지난다. finding 에는
  `partial_cell`(보고서 표지 '넘긴 셀 — 일부만 판정')만 더한다. 종전에는 넘긴 셀만 카드 밖 구성원을 뺐고, 셈은 따로 지은 갈래
  (`cell_hits` · `HIT_KINDS`)라 카드 밖 갈래가 없었다.
- 셈은 그 함수들이 실제로 낸 구성원 수다. 보고서는 build_findings 가 넘긴 셀마다 `Ledger.member_counts` 에 적고, 넘김 응답 hits_by 는
  `count_members` 가 같은 함수로 센다. 갈래(card · offcard · noinput)는 MEMBER_SOURCES 에서 저절로 선다 — 새 상수가 아니다.
  `cell_hits` · `HIT_KINDS` 는 없앴다.
- 영향 모름 입력 결손과 두 번째 판정까지 받은 부딪침 표지는 finding 이 아니라 셈도 0 이다. 보고서 '보지 못한 것' 줄은 걸림이 있을
  때만 '넘긴 셀 — 일부만 판정(…)' 을 단다.
- 카드 밖 · 단위 · 넘김 · 메커니즘 절과 의견 행(맺음 · 인용 · 지식)도 `Ledger.judged()`(검토 + 넘김)를 읽는다.
- 시험은 갈래 여덟(카드 FAIL · WARNING · 갈림 · 부딪침 두 갈래 · 카드 밖 · 입력 결손 있음 · 모름)에서 같은 원장의 셀 상태만 바꿔 넘긴
  셀과 검토한 셀의 finding 이 표지 빼고 같은지 본다(test_review_partial_cells.py). 가짜 엔진의 카드 밖 기본 한 줄은 카드 갈래에서 끈다.

### M3C-57. MEDIUM 2 · 3 — 다시 연 셀은 셀만 묶는다(fedb411)
- 살아 있는 잡이 다시 열면(정산의 곧바로 넓힘 · 훑기의 늦은 넘김 · 잡 끝 거두기 · 보충 표본) 다시 연 셀만 그 잡에 묶는다(run_id).
  머리는 찍지 않는다.
- 잡의 몫은 묶인 셀로 가린다 — `review_cells.job_expert_sql`(범위로 찍힌 머리이거나 그 잡에 묶인 셀이 있는 전문가). 검토 · 묶음 선점은
  그 잡에 묶인 pending 셀이 있는 전문가이고, 마감은 그 잡의 몫인 머리 가운데 그 잡에 묶인 열린 셀이 없는 것이다. 도는 수(in_flight —
  취소 판정) · 진행판 · 묶음 단계 · 마감 안 된 머리 셈 · 고아 놓기 · 잡 고르기 순서 · 보충 표본의 '남이 쥔 전문가' 도 같은 규칙이다.
- 그 잡은 묶인 셀만 돈다 — 세션이 고르는 셀이 그 잡에 묶인 셀이라서다. 재현 C 는 종전 15 호출(다섯 단위)이 3 호출(그 셀)이 됐다.
- adopt_released 는 머리 run_id 가 아니라 잡이 받은 범위(params.scope — resolve_scope 와 같은 `scope_experts`)에서 죽은 잡에 묶인
  pending 셀만 거둔다. run_id 없는 셀은 거두지 않는다 — 잡을 만들 때 범위 안 pending 셀은 assign_scope 가 찍으므로 run_id 없는 셀은
  한 번도 잡히지 않은 셀이다.
- 사람의 처분도 셀만 묶는다. 다시는 범위가 덮는 셀을, 넘김은 넘긴 셀을 살아 있는 잡에 묶는다. 넘긴 셀이 묶여야 그 잡이 그 전문가를
  다시 마감한다 — 그래서 그 잡의 진행판 셈에 넘긴 셀이 든다(응답이 adopted 라 말하는 셀이다).
- 해석 하나 — 곧바로 다시 연 셀은 그 잡의 단위 범위 밖이어도 그 잡이 돈다(결정이 '다시 연 셀만 그 잡에' 라 했다). 그 전문가의 다른
  셀은 손대지 않는다.
- 머리 run_id 는 이제 범위로 찍은 잡만 뜻한다. 보고서 단위 행의 in_scope(셀 run_id == 머리 run_id)는 그 뜻 그대로 둔다 — 다시 연 셀을
  돌린 잡은 머리를 찍지 않으므로 그 셀의 in_scope 는 거짓일 수 있다. 검토 · 넘김 줄에는 범위 밖 꼬리를 달지 않는다.

### M3C-58. LOW 4 — 앞 결과는 놓침만, 표본은 지금 표지의 결과(4392cc9)
- `sample_outcomes` 는 {marked, settled, result, picked_by} 다. 앞 결과(was)는 놓침만 세고, settled 는 지금 표지에 결과가 있다는 것이다.
  마지막 앞 결과로 메우던 것은 없앴다. 앞 결과의 기록(was)은 그대로 쌓는다 — 읽는 쪽만 바뀌었다.
- 셈은 `review_cells.sample_tally` 하나를 완결 몫과 품질이 같이 쓴다. 표본 수(sampled)는 결과를 낸 표본이다. 놓침은 결과를 아직 못
  낸 표본의 앞 놓침까지 센다. 비율 분모(n)는 둘을 더해 놓침이 분모를 넘지 않는다(binom_upper 의 k ≤ n).
- 완결 몫의 대기 · 실패는 표지가 선 채 결과가 없는 표본만 센다. 표지가 지워져 앞 놓침만 남은 셀은 표본이 아니고 놓침 수와 분모에만
  든다. 잡 끝 보충 표본도 같은 settled 로 바닥을 센다 — 재현 D 는 이제 그 잡 끝이 다시 걸러진 셀을 새 표본으로 끝까지 본다.
- 2차 시험 ④(표지가 지워진 놓침)는 표본 수 0 · 놓침 1 · 분모 1 이 됐다. 품질을 완결 몫보다 먼저 본다 — 분모를 줄이는 변이가
  binom_upper 의 ValueError 가 아니라 단언으로 걸리게.

### M3C-59. LOW 5 — 1차 모양을 읽지 않는다
- 1차 수리의 표지 안 앞 결과(marker.was)와 1차 보고서의 걸림 수를 읽는 길은 두지 않는다. 그 모양은 배포된 적이 없다 — m3 ·
  m3-rehearsal 은 밀지 않은 가지이고 그 모양을 가진 운영 원장이 없다(D-47).

### M3C-60. LOW 6 — 단독 표지의 rev 를 다시 묻는다(49e83ef)
- 단독으로만 본 카드(pair_over)의 단독 행에 부딪침 표지가 서면 그 카드 하나의 rev 를 받는다. 그 답이 그 카드를 빼먹으면 SOLO_REASKS
  번까지 다시 묻는다.
- 끝내 못 받으면 셀은 검토로 닫히고 보류 finding('두 번째 판정 못 한 부딪침')이 남는다(D-37). samples_done 을 내리지 않았다 — 내리면
  셀이 samples_incomplete 로 실패해 결정이 남기라고 한 finding 이 검토한 셀에서 사라진다.
- 표본 결과는 놓침이다. `audit_outcome` 이 finding 후보 규칙(`candidate_kind`)을 판정 행의 변형과 함께 읽어 unjudged_conflict 도
  risk_miss 로 친다.
- 단위 시험(test_audit_outcome_counts_an_unjudged_conflict_as_a_miss)은 새 인자(rows)의 계약이라 옛 코드에서는 TypeError 로 넘어진다.
  재현은 생산자 길의 시험(test_review_dual)이 단언으로 본다.

### M3C-61. LOW 7 — '넘김 — 사유'(610056e)
- 넘긴 셀의 보고서 줄 둘(본 범위의 단위 줄 · 보지 못한 것)이 같은 글 '넘김 — «사유»' 다(_skip_words). 넘김에는 범위 밖 꼬리를 달지
  않는다 — 넘김은 범위가 아니라 사람의 처분이다. 새로 선 마감 잡과 살아 있던 잡 두 길을 시험이 본다.

### M3C-62. 공유 파일 · 손대지 않은 것
- review_runner.py — resolve_scope(scope_experts), in_flight, dispose_cells(셀만 묶기 · hits_by), JobProgress._count, AIDataHub 판정,
  묶음 단계(needs_pack), _unfinalized, _settle(넓힘 run_id), _replay_handoffs(run_id), _audit_topup(주석), _solos(rev 다시 묻기),
  _sample_results(rows). create_review_job 은 손대지 않았다.
- expert_report.py — Ledger(partial · judged · member_counts), MEMBER_SOURCES · _unit_members · build_findings · count_members,
  _scope_section, _md_scope(_skip_words), _hits_line, judged() 를 읽는 절들.
- review_cells.py — job_expert_sql · scope_experts, adopt_released, _live_review_jobs, claim_next_expert, release_orphaned,
  reopen_filtered · reopen_widened · reopen_handed_off · widen, sample_outcomes · sample_tally, audit_topup, closure_cells.
  review_quality.py(_load · _filter) · review_verify.py(audit_outcome).
- frontend · 포털 문서 · runner.py · v5 블록은 손대지 않았다.

### M3C-63. 변이 검사 · 전체 시험 — 반대 검토 3차 수리
- 재현은 수리 전 사본(`scratchpad/celm3-<pid>-r3m-old` · `r3l4-old` · `r3l6-old`)에서 단언으로 넘어지는 것을 먼저 봤다(B1 · B2 둘 ·
  C 둘 · D · 표지가 지워진 앞 결과 셋 · F · LOW 7 두 길 · adopt_released 범위). LOW 6 의 단위 시험만 새 인자의 계약이라 TypeError 다.
- `git archive` 사본(`scratchpad/celm3-<pid>-r3`)에서 44개(HIGH 1 열 · MEDIUM 2 · 3 스물하나 · LOW 4 일곱 · LOW 6 셋 · LOW 7 셋)를
  하나씩 넣고 그 수리의 시험만 돌렸다. 단언 실패만 죽음으로 셌다.
- 첫 판(38개)은 33 죽음 · 살아남음 4 · 단언 아닌 실패 1 이었다. 살아남은 넷은 잡의 몫을 읽는 자리 가운데 시험이 없던 곳이다 — 마감
  선점(`_unfinalized` 가 막아 가려졌다 — 남의 planned 머리가 차례가 앞설 때만 드러난다) · 도는 수(취소 판정) · 진행판 · 고아 놓기.
  단언 아닌 하나는 분모를 줄인 변이가 binom_upper 의 ValueError 로 넘어진 것이라, 품질(분모를 단언한다)을 완결 몫보다 먼저 보게
  고쳤다. 같은 규칙을 읽는 나머지 자리(잡 고르기 차례 · 묶음 단계 · AIDataHub 판정 둘)에도 변이를 넣고 시험을 더했다.
- 고친 뒤 43/44 가 단언으로 죽는다. 남은 하나는 잡 끝 보충 표본의 '남이 쥔 전문가' 를 머리 run_id 로 되돌린 변이다 — 보충 표본은
  그 잡의 도는 머리가 0 일 때만 불리므로(`_complete_or_phase`) 그 자리에서는 같은 값이다(규칙을 맞춰 둔 것뿐이다).
- **전체 시험(공유 잠금 아래).** 2,923 통과 · xfail 4 · 실패 0(종전 2,894). ruff 깨끗하다.

## 재설계 M3 — 셀 꾸러미 반대 검토 4차 수리(90b5e25 기준 MEDIUM 2 · LOW 2, D-49, 2026-10-15)

검토 결과와 조정자 결정은 스크래치의 cells-review4-findings.md 에 있다(그 문서의 D-48c 가 포털 기록의 D-49 다 — D-48 은 Claude 길
결정이다). 3차의 구조 변경(넘긴 셀 한 길 · 셀만 묶기)은 걸림을 잃지 않았고, 남은 것은 그 구조의 뒤탈 둘(MEDIUM 1 · 2)과 옛 틈 둘
(LOW 3 · 4)이다. 재현은 검토자 탐침(r4cells-probes-90b5e25.py.txt)의 P1A · P1B · P2 · P3 · P5 · P6 · P7 을 시험으로 옮겼다.

### M3C-64. MEDIUM 1 — 입장은 검토한 셀로(faef6c7 · 한 길 2fc146d)
- `_final_stance` 가 judged()(검토 ∪ 넘김)를 읽어 X1-15('검토한 셀이 없으면 abstain')를 깼다 — 데이터 없는 넘김이 agree 가 됐다(P1A 묶음
  실패 뒤 다섯 넘김 · P1B no_rows 하나 넘김). 이제 바탕 입장은 `reviewed()` 와 넘긴 셀 finding 을 뺀 finding 으로 X1-15 그대로 정하고,
  넘긴 셀의 걸림 후보는 검토한 셀과 같은 걸림 줄(`_raised` — 실효 FAIL → oppose, WARNING · 카드 밖 · 갈림(두 번째 판정 못 한 부딪침
  포함) → conditional)로 그 입장을 올리기만 한다(max). 동의로는 결코 가지 않는다.
- 첫 구현(faef6c7)은 넘긴 셀의 리스크 후보면 무엇이든 conditional 로 올려 같은 자료의 검토한 셀보다 더 올렸다(입력 결손 영향 있음 —
  X1-15 의 줄은 그것을 세지 않는다). 변이 검사를 짜며 드러나 한 줄로 맞췄다(D-47 — 넘긴 셀은 검토한 셀과 한 길). 시험은 깨끗하게 검토한
  단위 하나가 있는 원장에서 같은 자료의 셀을 검토 · 넘김으로 둘 때 입장이 같은지를 갈래 여덟로 본다.
- **해석 — 기권은 검토한 셀로만.** 결정의 '기권은 reviewed() 로만 정한다' 를 글자 그대로 읽어, 바탕이 기권(검토 0 · 적용 판정이 보류뿐)이면
  넘긴 셀의 후보가 있어도 기권이다. 그래야 X1-15 가 서고 원장(검토 0 · 넘김 ≥1 → skipped · cells_skipped, 롤업 표 7번 줄)과 입장이 같은
  말을 한다. 그 걸림은 사라지지 않는다(D-37) — finding(partial_cell) · 보고서 '보지 못한 것' 줄 · 단위별 분석 · 요약 줄에 남는다. 다른
  읽기(검토 0 이어도 후보가 oppose 로 올린다)를 고르면 롤업 표에 '넘긴 셀에 후보가 있으면 done_weak' 줄을 더해야 원장이 입장과 맞는다 —
  결정에 없는 표 변경이라 하지 않았다.
- 단위별 분석 · 메커니즘 절의 넘긴 단위는 빼지 않고 `partial_cell` 을 단다. 마크다운은 머리를 '넘김 — 일부만 판정' 으로 쓰고, 걸림
  후보(FAIL · WARNING · 보류)만 펴며 '걸림 없음 · 해당 없음' 블록 대신 '넘긴 셀이라 걸림 없음으로 읽지 않는다' 한 줄을 적는다(판정이 선
  카드는 점검표에 '넘긴 셀' 표기로 있다). JSON 의 OK · na 목록은 자료라 그대로 둔다.
- 요약은 넘긴 셀을 검토로 세지 않고 '넘김 n(일부만 판정)' 을 따로 적으며, 넘긴 셀의 finding 줄 끝에 '넘긴 셀 — 일부만 판정' 을 단다
  (넘김이 없으면 종전 바이트 그대로다).
- 3차 LOW 7 시험(넘긴 셀 줄은 '넘김 — «사유»')은 본 범위 절만 보게 좁혔다 — 메커니즘 절의 새 표지 줄도 '- 단위 … 넘김' 으로 시작한다.
- 손대지 않은 것(관찰 · 조정자 결정 몫) — 입력 결손 전문가가 검토한 셀에서 '영향 있음'(q1 yes — finding 이 선다)을 내도 입장은
  agree 다(X1-15 의 걸림 줄이 카드 밖 · 갈림만 보고 입력 결손 finding 을 보지 않는다 — C3-3 부터, 탐침으로 확인). 이번 결정 밖이라 고치지
  않았다. 줄에 `input_gap` 을 더하면 검토 · 넘김 두 길이 함께 바뀐다(한 줄이다).

### M3C-65. MEDIUM 2 — 다시 연 셀의 몫(f4117ba · 시험 보강 5e850ac)
- **몫의 원장.** 잡 `params.reopen` = {consented{cells, calls_est}, unconsented{"<unit_id>|<agent_key>": 기대 호출}, consent_source}. 열을
  더하지 않았다(v5 블록은 S3-1 몫). 셀마다 값을 두는 것은 넘김이 그 셀을 뺄 때 같은 값을 빼기 위해서다(그 사이 박스의 k 가 바뀌어도).
- **무엇을 세나.** 살아 있는 잡 J 에 묶는 다시 연 셀 가운데 J 의 동의받은 추정 밖인 것 — `reopen_filtered(run_id=J)`(넓힘 · 늦은 넘김 ·
  잡 끝 거두기 · 보충 표본 다섯 길이 다 이 함수를 지난다)가 앞 결속이 J 가 아닌 셀을 센다. J 가 제 범위에서 제가 거른 셀은 추정 안이다
  (expected 는 거르기 없음 가정이다). 사람의 다시가 살아 있는 잡에 얹힌 셀(dispose_cells 의 adopted)은 늘 센다 — 그 잡을 만들 때 failed 라
  추정에 없었고, J 의 것이었어도 다시 도는 몫은 추정 밖이다. adopt_released 는 그 잡이 받은 범위 안이라 세지 않는다.
- **셀 하나의 값** `cell_calls` 는 calls_estimate 의 expected 가 그 셀에 세는 몫 그대로다(입력 결손 1.05 · 카드 셀 card_cell_calls · 걸린
  것만 이중 판정이면 1순위에 보정 rev D). k 는 셀 때의 box_k, dual 은 잡에 얼린 값이다.
- **여유와 보류**(`reopen_budget`). 여유 = max(ceil(0.2 × (만들 때 expected + 동의한 몫)), 30). 동의 안 받은 몫 > 여유면 consent_extra,
  추정 합(expected + 동의한 몫 + 동의 안 받은 몫) > HWAXRISK_REVIEW_MAX_CALLS 면 max_calls(먼저 본다 · 동의로 풀리지 않는다).
- **멈춤은 묶기와 한 트랜잭션.** `charge_reopened` 가 묶는 트랜잭션 안에서 몫을 적고 넘으면 잡을 paused 로 둔다 — 선점(claim_next_expert)은
  제 트랜잭션에서 잡이 running 이어야 하므로 그 셀은 한 번도 돌지 않는다(차감 없음 · 이 잡에 묶인 채 pending). 루프 틱에서 따로 보지
  않는다 — 묶기의 멈춤과 사람의 재개 관문이 모든 길을 덮는다. 시계로 저절로 재개할 보류(llm_outage 따위)로 멈춘 잡은 그 보류를
  consent_extra 로 덮고(그대로면 간격 뒤 저절로 재개해 동의 없이 돈다), 이미 이 몫으로 멈춘 잡은 새 셈의 코드 · 글로 고친다. 사람의 정지 ·
  자격 · 사람이 고칠 보류는 그대로 두고 그 재개가 몫을 다시 본다.
- **동의.** 사람의 재개(REST POST /jobs/{id}/resume?consent=true · MCP risk_job_action(action='resume', consent=true))가
  `review_runner.resume_gate` 를 지난다 — 몫 안이면 아무것도 하지 않고, consent_extra 몫이면 동의 없이는 422 consent_required(아무것도
  바꾸지 않는다), 동의면 동의 안 받은 몫을 동의받은 몫으로 옮긴다. max_calls 는 409 다. 보류 코드와 상관없이 몫으로 판다 — 사람이 멈춘
  잡에 그 사이 묶인 셀도 동의를 받는다. 길잡이는 두 보류의 고칠 곳을 말하고 재개 걸음에 동의를 채우지 않는다(SEC-4).
- **넘김.** 동의하지 않으면 넘김(filter state=pending)이 '동의를 기다리는 셀'(멈춘 잡의 동의 안 받은 몫에 든, 그 잡에 묶인 pending 셀)만
  넘긴다 — 넘김은 failed 에서만 가므로(PLAN C-18) pending → failed(consent_declined · 차감 없음) → skipped. 몫에서 빼고, 여유 안으로
  돌아오면 넘긴 사람의 이름으로 그 잡을 재개한다(job.resumed). 아직 밖이면 보류 글을 남은 수로 고친다.
- **보이기.** 진행판 `review.job.progress.reopened_extra`(셀 수 · 추정 · 동의함 · 기다림 · 여유 · 상한 · 보류)는 잡 params 에서 읽는다 —
  멈춘 잡은 루프가 진행판을 다시 세지 않아 JobProgress 에 두면 낡는다. MCP 답(길잡이 facts.review_job)도 같은 칸을 싣는다(작은 칸이다).
- 해석 셋 — ① 결정의 'retry spill' 은 사람의 다시가 살아 있는 잡에 얹힌 것(adopted)으로 읽었다(넓힘은 따로 적혀 있다). ② '동의받은/
  기대 호출' 은 만들 때의 expected 에 재개로 더 동의한 몫을 더한 것이다. ③ '잡의 합은 상한을 넘지 않는다' 는 추정 합으로 본다(만들 때의
  review_too_large 가 expected 와 견주는 것과 같은 자) — 실제 호출 수의 상한은 두지 않았다.
- 시험의 함정 — 시험대의 잡들은 같은 초에 서서 진행판의 '가장 최근 잡'(created_at 초 · id 무작위)이 그 잡이라고 기댈 수 없다. 몫의
  시험은 그 잡의 줄(routes._review_job_payload)을 읽는다.

### M3C-66. LOW 3 — 모름은 0 이 아니다(4a34feb)
- 얼린 묶음이 이 박스에 없는 전문가(들여온 원장 — rr_card_packs 는 반출하지 않는다)의 셀을 넘기면 `count_members` 는 None 이고 넘김 응답은
  hits · hits_by null · hits_basis 'pack_missing' · hits_note(그 전문가 · 모름이지 0 이 아니다 · 마감이 다시 받아 센다)다. 셀 수 있으면
  hits_basis 'members'. 여러 전문가 가운데 하나라도 못 세면 합도 모름이다.

### M3C-67. LOW 4 — 마감과 다시 열기가 엇갈려도(3c22d9b)
- 마감은 세션이 그 잡의 열린 셀 0 을 센 뒤 트랜잭션 밖에서 보고서를 짓는다. 그 사이 다른 세션의 다시 열기가 그 전문가의 셀을 그 잡에
  묶으면(_reopen 은 도는 머리를 건너뛴다) 종전에는 머리가 partial 로 닫혀 아무도 그 셀을 집지 못했다(P3 — 60시간). `close_expert` 는
  마감하는 잡(finalize_expert 가 잡 id 를 준다)에 묶인 셀이 열려 있으면 머리를 planned 로 돌린다 — 보고서 · 의견은 그대로 쓰이고(원장은
  열린 셀이 있어 닫히지 않는다) 그 잡이 그 셀을 돌린 뒤 다시 마감한다.
- 안전망 `review_cells.replan_bound` — `_complete_or_phase` 가 잡 끝 셈 앞에서 그 잡에 묶인 pending 셀이 남은 ready · partial 머리를
  planned 로 다시 연다. 시험은 둘을 따로 본다 — 마감 중 넓힘은 그 틱 뒤 곧바로 머리가 planned 인지(안전망은 다음 틱이다), 안전망은
  머리를 다시 열지 않은 묶기(_reopen 을 건너뛴다)의 원장에서 잡이 끝나는지.

### M3C-68. 공유 파일에서 바꾼 곳(m3 합류 때 볼 것)
- routes.py — `job_action`(쿼리 consent · 재개는 한 트랜잭션에서 review_runner.resume_gate 뒤 runner.resume_job), `post_cells_skip`
  설명글, `_review_job_payload` 의 progress.reopened_extra.
- entry.py — `job_action`(resume 에 consent 허용 · routes 로 넘김 · 설명글), `REVIEW_HOLD_FIX` 의 consent_extra · max_calls.
- mcp_server.py — `risk_job_action` 설명글(재개의 동의 · 넘김 filter state=pending · max_calls).
- 그 밖 — review_ops.HOLD_CODES 에 두 코드(자동 재개 없음), 계약 시험 둘(보류 표 · 잡 진행판 칸)을 고쳤다. runner.py · planner.py ·
  v5 블록 · frontend 는 손대지 않았다.

### M3C-69. 변이 검사 · 전체 시험 — 반대 검토 4차 수리
- 재현 시험은 90b5e25 의 app 위에서 단언으로 넘어지는 것을 먼저 봤다(사본 `scratchpad/celm3-<pid>-r4-old` — P1A · P1B · 후보 셋 · P2 ·
  여유 밖 둘 · 넘김 둘 · 제가 거른 셀 · P5 · P7 · 다시 얹기 둘 · P3 · 안전망 · P6 · 계약 시험 둘). 새 함수의 단위 시험(reopen_budget ·
  cell_calls)만 옛 코드에서 AttributeError 다 — 생산자 길의 시험이 단언으로 본다(M3C-60 과 같은 꼴). 입장의 짝 시험(검토 · 넘김이 같은
  입장)은 옛 코드에서도 지난다 — 한 길 고침(2fc146d)을 지키는 시험이다(첫 구현에서는 단언으로 넘어졌다).
- 첫 판(5e850ac, 사본 `celm3-<pid>-r4`)은 52개 가운데 44 가 단언으로 죽고 둘이 살았으며 다섯은 단언 아닌 실패(pytest.raises 의 DID NOT
  RAISE 셋 · MCP 거절을 AppError 로 다시 던진 하나 · 같은 초에 선 잡 셋 가운데 길잡이가 다른 잡을 집은 흔들림 하나), 하나는 자리가
  둘이었다. 산 둘은 제가 거른 셀의 시험이 정말 다시 열지 않던 것(분류 6번 줄로 검토였다)과 넘긴 단위의 걸림 없음 줄을 묶음 없는
  넘김으로만 본 것이다. 시험을 고치고(0df3b51 — 거절은 단언으로, 그 잡의 만든 시각만 뒤로 민다) 입장의 한 길을 고쳤다(2fc146d).
- 둘째 판(0df3b51)은 55개(LOW 3 다섯 · LOW 4 여섯 · MEDIUM 1 열여섯 · MEDIUM 2 스물여덟)가 모두 단언으로 죽는다.
- **전체 시험(공유 잠금 아래, 0df3b51).** 2,961 통과 · xfail 4 · 실패 0(종전 2,923 — 새 시험 38). ruff 깨끗하다. 검토자 탐침 일곱을
  마지막 판에 다시 돌리면 P1A · P1B · P1D 가 abstain, P3 잡 끝남, P6 hits null 이고, P2 · P5 · P7 은 바닥 안이라 그대로 돌되
  reopened_extra 로 셈해진다(결정대로).

## 재설계 M3 — 셀 꾸러미 4차 뒤 두 건(91e48a6 위, 2026-10-15)

조정자가 4차 수리와 해석 1~3 을 받아들였고 두 건을 더 맡겼다 — 해석 4(입력 결손 '영향 있음' 의 입장)의 결정과 단계 D 리허설(bc70523)이
찾은 결함 E1b(비우기 깃발 뒤의 호출). 증거는 스크래치 m3-rehearsal/m3-run-20261015-032955/evidence.json 의 checks.E1b 다 — 깃발 초에
여섯 · 1초 뒤 둘, 여덟 모두 엔진이 review_busy(draining)로 거절했고 차감은 0 이었다. 나갈 기준은 '깃발 뒤 엔진이 받아들인 호출 0' 으로
고쳐졌다(M3.md 3.3 #3 · D-51).

### M3C-70. 입력 결손 '영향 있음' 은 조건부(7986699)
- 결정 — q1 impact=yes 는 검토한 셀이든 넘긴 셀이든 입장을 conditional 로 올린다. 확인되지 않은 영향이라 입력이 와야 확인하므로 oppose 는
  아니다. impact=unknown 은 입장을 바꾸지 않고 입력 결손 절 · 필요한 정보에 남는다.
- 걸림 줄(`_raised`)에 finding 의 `input_gap` 을 더했다 — 한 줄이라 검토 · 넘김 두 길이 함께 바뀐다(M3C-64 의 관찰이 풀렸다). unknown 은
  `_noinput_members` 가 finding 을 짓지 않으므로 줄에 닿지 않는다(시험이 입장 agree · finding 0 · 입력 결손 절의 영향 줄 · 필요한 정보의
  noinput 출처를 본다).

### M3C-71. 리허설 E1b — 비우기 깃발 뒤에 호출을 내지 않는다(1261392 · 시험 보강 cb29685)
- 까닭 — 루프가 `_spawn` 에서 30초 캐시한 /health 의 관문 limit 으로 띄웠고, 캐시에 없으면 동시 수(8)로 띄웠다. 도는 세션은 다음 호출
  앞에서 비우기를 보지 않았다.
- ① `HEALTH_CACHE_S` 15(M3.md 4.7). ② 그 틱에 /health 를 읽지 못하면(탐침 한도 안에 답이 없다 · 실패 · limit 칸 없음) 아무것도 띄우지
  않는다(`_gate_limit` — 모르면 8 이던 자리를 없앴다). 카드 대조가 붙지 않은 엔진(limit 칸 없음)은 창 탐침이 agent_outdated 로 먼저
  막으므로 조용히 멈추지 않는다.
- ③ 도는 세션의 다음 run · pack 은 보내기 전에 `_drain_gate` 를 지난다 — 루프가 마지막으로 읽은 /health 의 card_review.limit_reason 이
  draining 이면 보내지 않고 세션을 멈춘다(셀은 차감 없이 pending, 잡은 보류 없이 running, 머리는 오류 없이 planned). 기다리며 붙들지 않고
  멈추는 것을 고른 까닭 — 비우기는 update-all 동안(최대 1800초)이고 그 사이 앱도 재기동한다. 자리를 쥔 채 기다리면 시험대의 틱도 그
  워커를 기다린다. 비우기가 걷히면 루프가 새로 읽고 다시 띄운다(같은 시도의 받은 답은 요청 열쇠로 다시 쓴다).
- 뒤 그물 — 엔진의 review_busy{reason: draining} 은 엔진 클라이언트가 `ReviewDraining`(EngineBusy 의 갈래, 기다림 부류)으로 읽는다.
  세션은 그 호출을 기다림으로 적고(차감 · tries · 묶음 시도 수 0) 그 자리에서 다시 내지 않고 멈추며, 루프의 /health 를 비우기(관문 0)로
  고쳐 두고 캐시를 버린다(`note_draining`) — 다른 세션의 다음 호출도 보내기 전에 멈추고, 깃발이 걷히면 다음 틱이 곧바로 새로 읽는다.
  엔진 계약 장면 review_busy_draining(엔진이 실제로 낸 프레임)이 그 갈래로 읽힌다.
- 가짜 엔진에 비우기 스위치(draining — /health · run · pack 거절, drain_refused 기록)와 /health 실패 · 지연 스위치를 더했다(시험 전용).
- 해석 — 결정 3 의 '보내기 전에 멈춘다' 를 세션을 멈추는 것(놓기)으로 읽었다. 결정 2 의 '캐시에 없으면' 은 15초 안의 답이 없을 때이고,
  탐침이 그 틱의 한도(1초) 안에 끝나지 않아도 '읽지 못함' 이다(그 사이 지난 값으로 띄우지 않는다).

### M3C-72. 변이 검사 · 전체 시험 — 해석 4 · E1b
- 재현은 91e48a6 의 app 위에서 단언으로 넘어졌다(사본 `celm3-<pid>-r5-old` — 영향 있음 둘 · /health 못 읽은 틱 둘 · 16초 · 도는 세션 ·
  run 거절 · 묶음 거절). 고치기 전 코드의 세션은 비우기 거절을 60초 기다린 뒤 다시 내기를 끝없이 되풀이해 시험이 기다림 한도로 넘어진다 —
  시험은 끝에서 러너를 멈추고 워커를 기다린다(그러지 않으면 저장소를 닫는 동안 그 스레드가 sqlite 를 건드려 세그폴트가 났다).
  엔진 계약 장면 시험은 새 갈래 이름을 대므로 옛 코드에서는 모아 들이기에서 AttributeError 다.
- 변이 첫 판(cb29685)은 16개 가운데 14 가 단언으로 죽고 둘이 살았다 — 영향 모름을 finding 으로 올린 변이(시험이 자연 상태 no_input 만
  봤다)와 묶음 앞 비우기 문을 뺀 변이(뒤 그물의 거절 하나가 결과를 같게 만들었다). 시험을 더하고(094ebd4) 둘째 판에서 16/16 이 단언으로
  죽는다.
- **전체 시험(공유 잠금 아래, 094ebd4).** 2,972 통과 · xfail 4 · 실패 0(4차 수리 뒤 2,961 — 새 시험 11). ruff 깨끗하다. 공유 파일
  (routes.py · entry.py · mcp_server.py)은 이번에 손대지 않았다.

## 재설계 M3 — 셀 꾸러미 묶음 반대 검토의 몫(4f71fce 위, 2026-10-15)

조정자가 4f71fce 의 묶음 반대 검토(높음 1 · 중간 9 · 낮음 10, 모두 재현)에 결정 D-52 를 내렸다. 이 꾸러미의 몫은 M3 · M4 · M5 · L4 ·
L5 · L6 · L7 · L8 이고, 나머지(H1 · M1 · M2 · M6~M9 · L1~L3 · L9 · L10 · 가드)는 종합 꾸러미가 같은 시각에 m3 에서 고친다.

### M3C-73. M5 — 넘김의 마감 잡은 넘긴 셀만 묶고 동의를 적지 않는다(cd92102)
- 종전 — 살아 있는 잡이 없을 때 넘김이 세운 잡이 넘긴 셀들의 전문가 × 단위 범위로 서서 아무도 청하지 않은 pending 셀을 돌렸고(실패 셀
  둘을 넘기면 다른 셀 둘이 엔진을 여섯 번 불렀다) 사람 대신 consent true · source api 를 적었다. 낮은 상한에서는 그 범위의 추정 때문에
  넘김이 409 라 실패 셀을 처분할 수 없었다.
- `create_review_job(cells=…)` 는 그 셀만 묶는다(`review_cells.bind_cells` — 상태와 상관없이, 머리는 범위로 찍지 않고 pending 이 생긴
  전문가만 다시 연다). 추정은 그 가운데 pending 셀로만 센다(넘김은 0). params.cells 가 묶은 집합이고 `adopt_released` 는 그 밖의 셀을
  거두지 않는다(취소된 잡의 표지를 단 교차 셀도 그대로다).
- 해석 — 결정은 넘김만 말한다. 살아 있는 잡이 없을 때의 다시(retry)는 그대로 범위로 선다(사람이 동의를 주는 길이고 추정이 문턱을 본다).
  관찰로 남긴다 — 그 범위 잡도 범위 안의 다른 pending 셀을 돌릴 수 있다(M5 와 같은 모양).

### M3C-74. M4 — 동의 막힘 · 넘겨서 거절은 보류 코드가 아니라 몫으로(cac80b6)
- 종전 — 동의를 기다리던 잡을 사람이 멈췄거나 자격 보류가 consent_extra 를 덮으면 넘김이 기다리는 셀을 고르지 못했고(skipped 0 ·
  not_failed 3) 재개는 422 로 그 넘김을 권했으며 길잡이는 맨 재개만 내밀었다.
- `awaiting_consent` 는 살아 있는 잡을 `reopen_budget(params).hold` 로 고른다. 기다리는 셀은 동의 안 받은 횟수가 남은(n > c) 그 잡에 묶인
  pending 셀이다 — 사람이 이미 동의한 다시 연 셀은 넘겨서 거절에 들지 않는다. 길잡이(entry.py `_cells_answer`)는 몫의 hold 가 보류 코드와
  다르면 그 막힘(consent_extra · max_calls)을 따로 보인다.
- 넘김 뒤 몫이 여유로 돌아오면 그 몫이 멈춘 까닭(보류 코드 consent_extra · max_calls)일 때만 잡을 잇는다 — 사람의 정지 · 자격 보류는
  넘김이 풀지 않는다. 아직 넘으면 `_reopen_hold` 가 새 셈으로 다시 적는다(사람의 정지 · 자격은 그대로 둔다).

### M3C-75. L5 · L6 — 몫은 셀마다 돈 횟수로 세고 제 추정 안의 셀은 세지 않는다(c294c33)
- 원장을 `params.reopen.runs` = {"<unit>|<agent>": [추정 밖으로 돈 횟수 n, 그 가운데 동의받은 횟수 c, 한 번의 기대 호출 est]} 로 바꿨다.
  동의 안 받은 몫은 Σ(n−c)·est, 동의받은 몫은 Σc·est 이고 진행판 reopened_extra 에 runs(Σn)가 는다.
- `charge_reopened` 는 다시 묶은 셀을 앞 결속과 함께 받는다 — 앞 결속이 그 잡이 아니거나(추정 밖에서 들어온 셀) 이미 원장에 있으면(추정
  밖 셀이 그 잡에서 다시 돈다) 한 번 더 센다. 앞 결속이 그 잡이고 원장에 없는 셀은 그 잡이 만들 때 추정에 넣은 제 셀이라 세지 않는다.
- 동의(재개 consent=true)는 모든 셀의 c 를 n 으로 올리고, 넘겨서 거절은 기다리던 한 번만 뺀다(n − 1, 0 이면 지운다 — 이미 돈 한 번은
  몫에 남는다).
- 4차 코드의 옛 모양(params.reopen 의 consented · unconsented)은 읽지 않는다 — 그 모양은 배포되지 않은 m3 의 4f71fce 에서만 생겼고 dev
  리스크 앱의 코드는 main 이다(4f71fce 를 담지 않았다).

### M3C-76. L8 — 동의를 기다리던 잡의 취소는 다시 연 전문가의 보고서를 다시 짓는다(d2e4c75)
- `refresh_after_cancel` — 몫의 hold 가 선 잡이 취소로 닫힐 때(곧바로 닫힌 취소는 `close_progress`, cancelling 으로 섰다가 루프가 닫은
  취소는 `_finish` — 둘 다 진행판을 끝내기 전에) 그 잡이 다시 연 셀(params.reopen.runs)의 전문가 가운데 planned 머리를 잠깐 쥐고
  (`review_cells.claim_for_refresh`) 마감과 같은 쓰기(prepare · commit · close_expert)를 한다. 엔진은 부르지 않는다. 열린 셀이 있으니
  마감 규칙대로 partial 이고, 입장은 검토한 셀로 정하며 돌지 않은 단위는 '보지 못한 것' 에 대기로 실린다(더는 '거름' 이 아니다).
- 준비(읽기)가 실패하면(얼린 묶음이 이 박스에 없다 따위) 취소는 서고 머리는 planned 로 놓는다. 쓰기의 실패는 감추지 않는다 — 곧바로
  닫히는 취소는 한 트랜잭션이라 통째로 되돌아가고, 루프 쪽은 그 틱이 실패로 적힌다.
- 해석 — '동의를 기다리던 잡' 은 몫의 hold 로 읽었다(M4 와 같은 기준이고, 취소는 보류 코드를 비운다). 관찰로 남긴다 — 여유 안에서 다시
  연 셀이 돌기 전에 잡을 취소해도 그 전문가 보고서는 다시 열기 전 그대로다(같은 모양이지만 결정 밖이라 넓히지 않았다).

### M3C-77. M3 · L7 — 관문이 닫힌 까닭을 말하고, 관문은 LLM 일만 막는다(8d8d14b)
- 종전 — `_spawn` 은 /health 를 못 읽거나(503 · limit 칸 없음) 비우기(limit 0)면 0 을 돌려주고 아무것도 적지 않았다. 잡은 running ·
  기다림 없음 · 길잡이 막힘 없음이었고 LLM 을 부르지 않는 마감 · 근거 꾸러미까지 멈췄다.
- 루프 기다림 — `_gate_wait` 가 까닭을 고른다(엔진의 비우기 거절 창 안이면 draining, 읽었는데 limit 을 모르면 health_unknown, /health 가
  draining 이면 draining). `_gate_waiting` 이 source loop 로 적고 같은 까닭이 이어지는 동안 since 를 두며(진행판은 바뀐 칸이 있을 때만
  쓴다) 관문이 열리면 지운다. 창 통과는 관문 기다림을 지우지 않는다(지우면 틱마다 since 가 새로 섰다). 탐침이 아직 답이 없는 틱은 지난
  기다림을 그대로 둔다. 길잡이는 이미 '검토 잡이 기다린다 — <까닭>: <글>' 을 싣는다 — entry.py 를 고치지 않았다.
- 관문은 묶음 · 검토(`GATED_PURPOSES`)만 막는다. 관문 몫은 min(동시 수, limit) − 도는 묶음 · 검토 워커이고, 마감 · 근거 꾸러미는 동시 수
  안에서 돈다(종전에는 모든 워커가 min(동시 수, limit) 안이었다).
- L7 — `note_draining(retry_after_s)` 는 거절이 알린 시각까지를 비우기 창(`_drain_until`)으로 둔다. 세션의 비우기 문과 루프의 띄우기가
  함께 본다. /health 를 고쳐 쓰고 캐시를 버리던 것은 뺐다 — /health 는 정상인데 호출이 가는 길의 서버만 비우면 틱마다 다시 띄워 분에 백
  번 거절됐다. 이제 창마다 거절은 하나다(시험 — 120초에 둘).
- 해석 — 비우기가 끝난 뒤에도 거절 창(엔진이 알린 60초)까지는 기다린다. 리허설 E1b 의 '깃발이 걷히면 곧바로 이어 돈다' 를 이것으로
  바꿨다(E1b 시험 둘의 끝을 고쳤다 — 60초 안에는 띄우지 않고 그 뒤 이어 돈다). /health 와 호출 길이 같은지 다른지는 거절 한 번으로만
  알 수 있어, 엔진이 알린 기다림을 따르는 쪽이 창마다 하나로 묶는 가장 단순한 길이다.
- 가짜 엔진에 calls_draining 스위치를 더했다 — /health 는 정상인 채 run · pack 만 비우기로 거절한다(시험 전용).

### M3C-78. L4 — 묶음을 못 받은 카드 전문가는 카드 없는 영역을 만들지 않는다(4036625)
- 완결 판정의 셈(`closure.cell_counts`)이 묶음을 끝내 못 받은(pack_status error · card_basis 없음) 전문가를 카드 전문가로 센다. 깊이의
  분모에 들어 그 영역은 깊이 미달로 막히고(실패 셀은 failed 잔여로 막는다) depth_no_cards 잔여 · 깊이 면제(no_cards)가 서지 않는다.
- 해석 — 묶음을 못 받은 전문가가 실제로 카드를 가졌는지는 모른다(묶음이 그것을 알려 준다). 모르는 것을 '카드 없음' 으로 읽어 깊이를
  면제하면 조용한 면제라, 모르면 카드 전문가로 본다(결정의 '카드가 있는데 묶음을 못 받은 전문가').

### M3C-79. 공유 파일 · 변이 검사 · 전체 시험 — 묶음 검토의 몫
- 공유 파일 — entry.py `_cells_answer` 의 동의 막힘 다섯 줄(M4)뿐이다. routes.py · mcp_server.py · runner.py 는 손대지 않았다(L8 의 취소
  쪽 다시 짓기는 review_runner 의 `close_progress` 안에서 부른다).
- 재현은 4f71fce 의 app 위에서 단언으로 넘어졌다(사본 `celm3-<pid>-p3-old` — 새 시험 20 · 고친 시험 넷). 예외 셋 — 몫 단위 시험은 새
  원장 모양을 먹이므로 여덟 가운데 셋이 KeyError 다(생산자 길의 L5 · L6 시험이 단언으로 본다, M3C-60 과 같은 꼴). 묶음 거절 E1b 시험의 고친
  줄(`draining()`)은 옛 코드도 참으로 만든다. 동의받은 셀을 넘기지 않는 M4 시험은 옛 코드에도 있던 성질을 지킨다(아래 m4d 가 새 코드에서
  그것을 깰 수 있음을 보였다).
- 변이(사본 `celm3-<pid>-p3`, 34개) — 첫 판 28 이 단언으로 죽고 다섯이 살았으며 하나는 변이가 TypeError 였다. 산 셋에 시험을 더했다
  (7dfaf3e — 넘김의 마감 잡이 취소된 잡의 교차 셀을 거두지 않는다 · 동의받은 다시 연 셀은 넘겨서 거절에 들지 않는다 · 두 번째로 돈 셀을
  넘겨도 이미 돈 한 번은 몫에 남는다). TypeError 변이는 '모르는 관문을 동시 수로 본다' 로 다시 써서 단언으로 죽는다. 둘째 판은 32/34 가
  단언으로 죽는다.
- 남긴 둘(l8a · l8e)은 결정의 범위를 지키는 문이다 — 다시 짓기를 동의를 기다리던 잡 · 다시 연 전문가로만 한다. 문을 빼면 해가 없는
  다시 짓기(같은 원장이면 같은 보고서)가 늘 뿐이라 '넓히지 않는다' 를 시험으로 박지 않았다(넓힐지는 M3C-76 의 관찰과 함께 조정자 몫).
- **전체 시험(공유 잠금 아래, 7dfaf3e).** 3,145 통과 · xfail 4 · 실패 0(rc 0). ruff 깨끗하다. 한 번 따로 돌린 검토 묶음에서
  `test_a_defect_in_a_session_releases_the_expert_with_a_pause_instead_of_stranding_it` 가 부하(load 22) 아래 한 번 넘어지고 다시 돌리면
  지났다 — 첫 틱에 묶음이 빨리 끝나 같은 틱이 검토를 집는 C3-11 의 경합(packs_only 를 쓰지 않는 시험)으로 보이며 이번 변경과 상관없다.
