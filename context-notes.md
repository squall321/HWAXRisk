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
