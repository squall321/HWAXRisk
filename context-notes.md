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

### D49. M3 수리 조합 반대 검토(4f71fce 기준)의 등록부 · 종합 몫 — 병합 대상 · 다시 토의 · 소유자별 별칭 · 좌석 기억 · 반출 · 읽기 가드(조정자 결정 D-52, 2026-10-15)

검토(HIGH 1 · MEDIUM 9 · LOW 10)와 결정은 스크래치의 m3-combined-review-findings.md 에 있다. 이 몫은 H1 · M1 · M2 · M6 · M7 · M8 · M9 ·
L1 · L2 · L3 · L9 · L10 과 읽기 경로 가드다(M3 · M4 · M5 · L4~L8 은 셀 꾸러미 `m3-cells` 몫).

- **H1(병합 대상).** PUT · DELETE /registry/{ck}/merge 는 target_key 를 부른 사람의 대상으로 찾는다(`_target_row(…, owner)`). 남의
  대상은 없는 대상과 같은 404 이고 아무것도 쓰지 않는다. 병합은 그 대상의 주인으로 돈다. 배포된 M2 앱에도 같은 경로가 있어 main 에
  같은 수리를 핫픽스로 먼저 올렸다(12130f9 — push 는 조정자가 확인 뒤에 한다).
- **M1.** 다시 줄 세우는 모든 길이 살아 있는 쟁점 잡을 본다. 읽을 수 없는 결정문으로 대기에 돌아가는 갈래(resolve_issue)에도
  release_issue 와 같은 고아 점검(`_orphan_reason` → `_untry`)을 넣었다.
- **M2 · L1 · L2 · L3(다시 토의).** 패널이 판정한 쟁점은 새 패널이 결정할 때까지 옛 판정(outcome · outcome_json · 등록부 덮어쓰기 ·
  보고서 줄)을 둔다. 새 패널이 결정하지 못하면(읽을 수 없는 결정문 한도 · 판정 못 함 · 닻 원자 없음 · 차감 놓기 한도 — `_keep_verdict`)
  결과 쟁점으로 돌아가고 reraised_json 에 new_panel_failed 를 달아 '패널 판정 — 근거 바뀜, 다시 토의 필요(새 패널 결정 못 함)' 로
  보인다(`registry.reargue_label` — 등록부 · 보고서 · 쟁점 행 · 요약 입력이 같은 글). 다시 줄 세우기(선정의 `_reraise` · 사람의 PUT
  queue)는 charged 를 0 으로 돌린다. 표기는 새 패널이 결정하거나 근거가 패널 때 근거(panel_basis_hash)로 돌아올 때만 내려간다 — 돌아오면
  다시 줄 서지 않고 결과 쟁점으로 돌아간다(L2). 그 판정을 낸 옛 패널을 다시 내면 낡음(stale)이다(L1). 쟁점 행(REST · MCP 같은 함수)에
  `reargue` 칸(없으면 null)이 선다(L3) — 행 칸을 못박은 시험(ISSUE_KEYS)을 함께 고쳤고, 계약 문서(포털 리포 m3-synthesis 3.11)의 행 칸
  목록에도 더해야 한다. release_issue(charge=True)는 지금 부르는 곳이 없다(러너는 차감 없이 놓는다) — 함수의 약속을 같게 두고 직접 부르는
  시험으로 지킨다.
- **M6.** 패턴 행에 저장하는 특징 범위는 그 행 주인이 볼 수 있는 과제의 원자에서만 고른다(`learning._owner_ranges` — 새 패턴 · 갱신 둘
  다). n_* 셈과 채점은 전역 그대로다(D48).
- **M7(스키마 v5).** rr_cluster_alias 의 열쇠를 (owner_sub, old_cluster_key) 로 바꿨다. v5 블록 끝에서 같은 이름으로 다시 짓는다 — 새 표
  rr_cluster_alias__v5 를 만들고, 옛 행을 owner_sub 그대로(그 행의 주인에게) rowid 순으로 옮기고, 옛 표를 지우고, 이름을 바꾼 뒤 색인
  ix_rr_cluster_alias_owner_new(owner_sub, new_cluster_key)를 세운다. v2+ 허용 문(CREATE · ADD COLUMN · INDEX) 밖의 네 문이라 test_store
  가 그 넷만 한 번씩 면제한다(REBUILD_STATEMENTS — CHECK 금지 · 문 머리 검사는 그대로). 설명은 SQL 주석이 아니라 파이썬 주석에 둔다(문
  머리가 '--' 로 시작하면 가드가 갈린다). 동결 원장 v2 · v3 · v4 시험은 그대로 통과한다(별칭 행 0). PUSHED_DDL_SHA256[5] 는 같은 임시
  방식으로 갈았다(25350889…). 해석 · 사슬 · 추가 · 철회(`learning.resolve_cluster_key` · `registry._alias_hops` · `add_cluster_alias` ·
  `revoke_cluster_alias`)는 owner_sub 가 필수이고, 부르는 곳(학습 원자 · 라벨 · 재매핑 · 지표 · 야간 별칭 점검 · 근접 쌍 · 쟁점 후보 ·
  쟁점 판정 · 병합)은 그 행의 주인을 넘긴다.
- **M8 · L10(좌석 기억 E7).** SQL 은 코퍼스에서 뺀 과제(status · corpus_excluded)의 의견과 발췌가 빈 의견을 싣지 않는다. AIDataHub 적중은
  hwax:project 표지의 과제가 보이는 과제일 때만 싣는다(`_hit_project` — 서술 경로와 같은 읽기).
- **M9.** 기본 반출은 과제 열이 없는 대상 열쇠 표(등록부 · 기여 · 패널 …)도 그 대상의 과제로 과제 열 표와 같은 거름(`_PROJECT_SCOPE_SQL`)
  을 건다.
- **L9.** 야간 근접 중복 쌍의 막음은 (소유자, a, b) 로 센다 — 남의 큐 항목이 주인의 쌍을 막지 않는다.
- **가드.** 라우터의 읽기 경로 41 == 시험 칸 31 + 면제 10(쓰기 경로 표와 같은 모양). 남이 주인의 것을 가리켜 읽으면 없는 것과 같은 답(글
  전체)이고 주인으로는 404 가 아니다. 과제로 거르는 목록 셋(/diffs · /targets · /reports)은 남의 과제를 주면 없는 과제와 같은 빈 목록이다.
  참조는 원장 참조(소유자 거름)와 스냅샷 스코프를 함께 준다. 면제 경로는 남에게 주인의 과제 id · 대상 열쇠를 싣지 않는지 따로 본다.
  지금 코드에서 새는 곳은 없었다 — 이 표는 가드다.
- **고치지 않고 보고.** ① 기본 반출은 스냅샷 · diff 열쇠 표(rr_ir_nodes · rr_ir_edges · rr_states · rr_snapshot_calls · rr_gate_acks ·
  rr_diffs · rr_diff_events)를 아직 과제 거름 없이 싣는다 — 이번 결정(대상 열쇠 표)의 밖이다. ② 원장 참조 해석(routes._ref_from_store)은
  owner_sub 로만 거른다 — 구성원은 남이 아니지만 그 과제의 reg · narr · tool 참조를 못 연다(새지는 않는다).
- **시험 · 변이.** 수리 시험(H1 가드 · M1 · M2 · L1 · L2 · L3 · M6 · M7 둘 · M8 · L9 · L10 · M9)은 고치기 전에 단언으로 졌다. `git archive`
  사본에서 변이 26 이 전부 단언으로 죽었다. 그 가운데 넷(새 패널의 판정 못 함 · 차감 놓기 한도 · 사람의 다시 줄 세우기 charged 0 · 남의
  별칭 사슬이 홉 한도에 드는 것)은 지키는 시험이 없어 시험을 더해 잡았다(0fea7d7 · 6c10112). 앞의 셋은 더하기 전 시험으로 돌리면
  살아남는다 — 계약 칸 시험(ISSUE_KEYS)이 L3 커밋으로 깨져 있는 동안에는 그 실패에 가려 죽은 것처럼 보였고, 그 시험을 고친 뒤(5ab3c10)
  다시 돌려 확인했다. 전체 시험(공유 잠금 아래, 6c10112) 3,175 통과 · xfail 4 · 실패 0(D48 때 3,076 — 그 뒤 셀 꾸러미 병합
  4f71fce 와 이번 시험이 더해졌다). main 핫픽스(12130f9)는 main 에서 2,435 통과 · xfail 4 · 실패 2 — 둘은 형제 리포 HWAXAgentServer
  가 M3 계약(cr-verdict-2)이라 생기는 기존 실패(test_card_contract_copies · test_card_review_request_contract)이고 수리 전 main 사본에서도
  같다.

### D50. D49 가 남긴 둘 — 반출의 스냅샷 · diff 열쇠 표 거름, 원장 참조는 구성원이 연다(조정자 결정, 2026-10-15)

D-52 는 받아들여졌고 main 핫픽스(12130f9)는 조정자가 push 했다. D49 '고치지 않고 보고' 의 둘을 결정대로 닫는다.

- **반출(①).** 과제 열도 대상 열쇠도 없는 일곱 표(rr_snapshot_calls · rr_ir_nodes · rr_ir_edges · rr_states · rr_gate_acks · rr_diffs ·
  rr_diff_events)에 M9 와 같은 거름(`_PROJECT_SCOPE_SQL` — 소유자 · 회수 아님 · 코퍼스 제외는 include_excluded 로만)을 그 행의 과제로
  건다. 스냅샷 열쇠 표는 그 스냅샷의 과제를 따른다. 스냅샷이 없는 호출(실패 · 부분 잡의 원문 — snapshot_id NULL)은 그 스냅샷 잡
  (rr_snapshot_jobs)의 과제를 따른다 — 스냅샷 거름만 걸면 범위 안 과제의 실패 원문까지 빠진다. diff 는 base · target 두 과제가 모두
  범위여야 실린다 — 읽기 문지기 mcp_scope_owner 의 규칙이다(한쪽이 빠진 비교는 빠진 쪽의 내용을 싣는다). diff 이벤트는 그 diff 를
  따른다. 규칙은 열 이름으로 건다(`snapshot_id` · `diff_id`) — 과제 · 대상 열쇠 없이 이 열을 가진 새 표도 기본으로 거른다.
- **반출 — 그대로 둔 것.** 대상 열쇠 표(M9)는 대상의 과제(rr_targets.project_id)만 본다 — 과제가 다른 diff 의 대상이면 그 diff 는
  빠지고 대상에 매인 행은 실린다. 읽기 문지기도 대상은 그 과제로, diff 는 두 과제로 판정한다(같은 규칙이다). 과제 · 대상 · 스냅샷 ·
  diff 열쇠가 없는 표(rr_part_keys · rr_sameas · rr_iface_alias · rr_id_map · rr_patterns · rr_curation_queue · rr_cluster_alias)는 소유자
  거름뿐이다 — 이번 결정 밖이다(rr_part_keys 는 first_project_id 로 처음 본 과제를 적는 공용 부품 열쇠다).
- **원장 참조(②).** `_ref_from_store` 의 reg · narr(판정 · 성격) · tool(패널 호출 id · 대화 좌표 · 스냅샷 호출)은 행의 과제를
  project_role(소유자 · rr_project_members — 보기 권한도)로 본다(`_first_member_row`). 과제는 행의 과제 · 대상의 과제 · 스냅샷의
  과제(없으면 스냅샷 잡의 과제)이고 SQL 의 `_ref_project` 칸으로 받아 응답에서 뗀다(응답 모양은 그대로다). 과제를 모르는 행은 그
  행의 주인만 연다. 대화 좌표는 색인만 있고 유일하지 않아 볼 수 있는 첫 행을 고른다. 남에게는 같은 갈래의 없는 참조와 같은 404 다.
- **참조 — 그대로 둔 것.** req(호출자 소유 요구) · voc · paper 참조와 get_ref 의 스냅샷 · diff 스코프(`_snapshot_row` · get_diff)는
  소유자로 그대로 본다 — 구성원은 그 갈래를 못 열지만 새지는 않는다(이번 결정 밖).
- **시험 · 변이.** 반출 시험 하나(코퍼스에서 뺀 기밀 과제 · 범위 안 과제 · 과제가 다른 diff · 스냅샷 없는 잡 호출 — 기본은 범위 안
  과제의 행만, include_excluded 는 전부, 헤더는 internal)와 남 시험 표의 참조 갈래 일곱(주인 · 보기 구성원은 200, 남은 없는 참조와
  같은 404, 과제 id · 대상 열쇠 없음)을 더했고 고치기 전에 단언으로 졌다(일곱째 — 스냅샷 없는 잡 호출 — 는 고친 뒤 더해 변이로
  확인했다). `git archive` 사본에서 변이 15(반출 여섯 · 참조 아홉)가 전부 단언으로 죽었다. 전체 시험(공유 잠금 아래, 24b2ec9) 3,183 통과 · xfail 4 · 실패 0(D49 3,175 + 여덟).

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

## 재설계 M3 — 묶음 검토 몫의 뒤따른 셋(5df0e67 위, 2026-10-15)

조정자가 묶음 검토 몫을 받아들이고 셋을 더 맡겼다 — 둘은 조정자 결정(다시의 잡 · 모든 취소의 다시 짓기), 하나는 한 번 흔들린 시험이다.

### M3C-80. 다시의 잡도 다시 연 셀만 묶는다(e51ab6d · 조정자 결정)
- 종전 — 살아 있는 잡이 없을 때 다시가 세운 잡은 다시 연 셀들의 전문가 × 단위 범위였다. 아무도 청하지 않은 pending 셀까지 추정해
  동의 문턱을 물었고(시험 — 두 셀 13회가 범위로 23회) 그 셀들에 엔진을 불렀다(M3C-73 의 관찰).
- 결정대로 넘김(M5)과 같은 길이다 — `create_review_job(cells=…)` 를 다시에도 준다. 다시 연 셀만 묶고 그 셀만 추정한다. 사람의 다시는
  그 셀들에 대한 동의다 — 그 셀들의 추정이 문턱을 넘으면 종전처럼 consent 가 있어야 한다(시험이 문턱을 그 추정 −1 · 그 추정으로 둔다).

### M3C-81. 모든 취소가 그 잡이 건드린 전문가 보고서를 다시 짓는다(1cb7631 · 조정자 결정)
- L8(M3C-76)을 동의를 기다리던 잡에서 모든 취소로 넓혔다. 대상은 그 잡의 몫(`job_expert_sql` — 범위로 찍힌 머리 · 그 잡에 묶인 셀이
  있는 전문가) 가운데 남은 planned 머리이고, 앞서 얼린 보고서가 있거나 닫힌 셀이 있어야 한다. 입장은 검토한 셀로, 돌지 않은 단위는
  '보지 못한 것 — 대기' 로 싣는다.
- 해석 — 건드린 머리 가운데 아무것도 보지 않았고 보고서도 없는 머리는 낡을 보고서가 없어 짓지 않는다(지으면 '전부 대기 · abstain'
  보고서만 늘고 큰 잡의 취소가 그만큼 무거워진다). 보고서가 없는데 닫힌 셀이 있는 머리(근거 꾸러미를 기다리는 단위만 남기고 세션이 놓은
  전문가)는 짓는다 — 검토한 셀의 결과가 어디에도 보이지 않던 자리다. 보고서가 있는데 닫힌 셀이 없는 머리(셀을 전부 force 로 다시 연
  전문가)도 짓는다(전부 대기 · abstain).
- 곧바로 닫히는 취소는 그 트랜잭션 밖에서 짓는다(`refresh_cancelled` — 다시 지었으면 끝난 진행판을 다시 센다). 저장소는 트랜잭션
  동안 연결 잠금을 쥐어 앱 전체가 기다리므로 전문가가 많은 대상의 다시 짓기를 취소 트랜잭션에 넣지 않는다. 그래서 runner.cancel_job 의
  반환을 트랜잭션 밖으로 옮기고 그 호출 한 줄을 더했다. 루프가 닫는 취소(`_finish`)는 원래 트랜잭션 밖이다.
- 실패 — 한 전문가를 못 지으면(얼린 묶음이 없다 따위) 그 쓰기는 제 트랜잭션째 되돌아가고 머리는 planned 로 놓이며, 취소는 이미 섰고
  나머지 전문가는 이어 짓는다(M3C-76 의 '취소 트랜잭션째 되돌린다' 는 더는 아니다).
- 남은 관찰 — 원장 좌석(rr_coverage)은 열린 셀이 있으면 `close_review_seat` 가 다시 열지 않는다. 앞 마감이 닫은 좌석은 그대로이고
  보고서만 새로다.

### M3C-82. 흔들린 시험은 시험의 틱 차례였다(1308c70)
- `test_a_defect_in_a_session_releases_the_expert_with_a_pause_instead_of_stranding_it` 는 '첫 틱은 묶음 · 다음 틱은 세션' 에 기댔다.
  동시 수가 기본(4)이라 첫 틱의 띄우기 고리는 묶음 워커를 띄운 뒤 남은 자리로 선점을 다시 묻는다. 부하 아래 루프 스레드가 밀려 그 사이
  묶음 워커가 끝나면(머리 planned · 묶음 ok) 같은 틱이 그 전문가를 검토로 집는다(C3-11 — 앱의 뜻한 동작). 그 세션은 고치기 전의 run 으로
  끝까지 돌아 머리가 ready 였다.
- 재현 — 사본에서 검토 선점 앞에 0.3초를 재우면 그 시험과 같은 꼴의 둘(묶음이 이 박스에 없다 · 포털의 PAT 거절)까지 셋이 넘어지고
  (그 시험은 ('ready', None, None)), 첫 틱을 packs_only 로 묶음만 집게 하면 셋 다 지난다. 앱이 아니라 시험의 틱 차례다.
- 고침 — 그 셋의 첫 틱을 `r.tick(packs_only=True)` 로 바꿨다. 동시 수 1(_one)인 '# 묶음' 시험 넷은 묶음 워커가 자리를 다 써 같은 틱
  선점이 없어(같은 지연에서도 지난다) 그대로 둔다.

### M3C-83. 재현 · 변이 · 전체 시험 — 뒤따른 셋
- 재현 — 새 시험 다섯(다시의 셀만 · 모든 취소 now · loop · 셀을 전부 다시 연 전문가 · 근거 꾸러미를 기다린 전문가)이 5df0e67 의 app
  위에서 모두 단언으로 넘어졌다(사본 `celm3-<pid>-f-old`).
- 변이(사본 `celm3-<pid>-f`, 9개)는 9/9 가 단언으로 죽는다 — 다시의 셀 묶기, 고르는 조건 셋(조건 없음 · 보고서만 · 닫힌 셀만), 루프와
  곧바로 닫힘의 부름 둘, 진행판 다시 세기, 잡 결속 마감, cancelling 상태. M3C-79 에서 남긴 둘(l8a · l8e — 범위의 문)은 이번 결정으로
  문이 없어졌다.
- 공유 파일(routes.py · entry.py · mcp_server.py)은 손대지 않았다. runner.py 는 `cancel_job` 의 반환을 트랜잭션 밖으로 옮기고 다시 짓기
  한 줄을 더했다.
- **전체 시험(공유 잠금 아래, 1cb7631).** 3,150 통과 · xfail 4 · 실패 0(rc 0). ruff 깨끗하다.

## 리스크 심사 Claude 길 X-2(가지 `x2-claude`, main d18e9d6 위, 2026-10-15)

포털 `docs/risk-claude-engine/` 의 걸음 X-2 다. 엔진 계약은 HWAXAgentServer README '외부 응답자' 절(main 839fa68)과 그 계약 예제
`tests/fixtures/external_llm/contract/` 다. 사용자 결정(X-D1) — 지어 두되 기본 꺼짐, 실제 Claude 로 돌리는 시험은 하지 않는다.

### XR-1. 앱의 이름은 `claude`, 엔진의 이름은 `external` 이다
- 잡 선택은 `llm: "glm" | "claude"`(없으면 glm)이고 엔진에는 `external` 로 보낸다(엔진은 `claude` 를 422 bad_request 로 거절한다 —
  rejects.json). 옮기는 자리는 engine_client 한 곳이다.
- GLM 잡의 params · 요청 본문 · 응답 · 보고서 바이트는 바뀌지 않는다 — 새 칸은 claude 잡에만 싣는다(없으면 glm).

### XR-2. 동의는 JSON true 하나 · 누가 · 언제 · 어느 입구
- `review_runner.check_llm_choice` — claude 는 `consent_external is True` 일 때만 선다(글자 'true' · 1 · 'yes' 는 422
  `consent_external_required` — 잡 행이 생기지 않는다). REST 본문은 그 칸을 `Any` 로 받는다(pydantic bool 은 'true' 를 참으로 바꾼다).
- 기록은 call-estimate 동의와 같은 자리다 — params `consent_external{by, at, source}`(by = 요청자 · source = web·mcp·api · chain 은 앞
  잡의 기록을 그대로), 반환과 감사 행(job.create after)에도 같은 칸. GLM 잡에는 칸이 없다(params · 반환 · 감사 바이트 그대로).
- ~~MCP 입구는 FastMCP 가 형을 단 인자를 미리 풀어(글자 'true' → true) 엄격함이 REST 만 못하다 — 도구 설명이 '동의를 받은 뒤에만
  true' 를 말하는 것이 그 자리의 그물이다(엔진 X-D6 도 FastMCP 의 풀기를 같은 식으로 받아들였다).~~ **틀렸다(X-D7 ②, 10-16 고침).**
  `bool` 주석이라 FastMCP(pydantic lax)가 'yes' · 'true' · 'on' · '1' · 1 을 True 로 바꿔 claude 잡이 서고 동의 기록이 남았다(반대 검토
  재현). 엔진 X-D6 의 동의는 dict(advanced) 안의 값이라 FastMCP 가 풀지 않는 자리였다(탐침 mcp_dict — 'yes' 가 글자 그대로 닿는다) —
  같은 경우가 아니었다. 이제 `consent_external: StrictBool | None` 이다 — FastMCP 가 도구에 닿기 전에 그 값들(과 0 · 'false' · dict)을
  검증 오류로 거절하고 잡 행 · 감사 행이 생기지 않으며, 도구 목록의 형은 boolean 그대로다(test_external_llm_lanes).

### XR-3. 길이 열렸는지는 잡을 만들 때 /health 로
- claude 잡만 `/health` 를 한 번 묻는다(트랜잭션 밖) — capabilities 에 external_llm 이 없으면 409 `external_llm_unavailable{reason:
  capability_absent, knob: EXTERNAL_LLM_ENABLED}`, 읽지 못하면 같은 코드의 `reason: health_unreachable`(확인 못 한 길에 세우지 않는다).
- 사슬이 세우는 쟁점 · 종합 잡은 다시 묻지 않는다 — 그 사이 스위치가 꺼지면 엔진의 `external_llm_disabled` 가 설정 보류로 멈춘다.

### XR-4. '잡 주인의 PAT' 는 동의한 사람의 PAT 로 읽었다
- 엔진의 과제는 호출 신원(포털이 PAT 로 덮어쓴 user_email)의 줄에 서고 그 사람의 워크플로만 집는다. 반출에 동의하고 워크플로를 돌릴
  사람은 잡을 만든 요청자다 — 그래서 claude 잡의 자격은 그 사람의 PAT 하나뿐이다(검토 잡 `pinned_review_credential` · 쟁점 · 종합
  `runner.resolve_job_credential` · 패널의 엔진 자격 `external_consenter`). GLM 처럼 대상 소유자의 PAT 로 내려가면 남의 줄에 과제가
  서서 아무도 집지 못하거나, 동의하지 않은 사람의 Claude 로 나간다. 서비스 PAT 는 종전처럼 어디서도 쓰지 않는다.
- 없을 때는 기존 길 그대로 — 검토 잡은 422 pat_unavailable(까닭에 '동의한 사람의 PAT 로만'), 쟁점 잡은 집지 않고 error
  `pat_unavailable: …` 를 단 채 기다리며(엔진 401 이면 보류 credential), 종합은 엔진 자격 실패의 credential 보류다.

### XR-5. 창 답은 길마다 따로 · 외부 창 출처는 '아는 창'
- 루프의 창 캐시 열쇠는 이메일(GLM — 종전 열쇠) · `이메일|external`(외부)이다 — 같은 사람의 GLM 잡과 판이 갈린다.
- 외부 limits 의 `ctx_source: external` 은 fallback 가정이 아니다(`known_ctx_sources`) — 아니면 600초 뒤 ctx_unknown 으로 멈췄다.
- 외부 창을 물었는데 답에 `llm: external` 이 없으면(포털 중계가 ?llm 을 버렸다 — X-3a) GLM 판으로 계획하지 않고 `external_config` 로
  멈춘다(루프 · 세션 · 종합 셋 다). 계획 · 호출 본문은 중계가 통째로 넘기므로 판 대조(rev_mismatch)가 뒤 그물이다.

### XR-6. external_worker 는 '기존 다시 내기 뒤' 사람이 재개하는 보류
- 검토 루프 — 일꾼 없음 · 답 시간 초과는 인프라(차감 없이 셀 백오프 — 기존 다시 내기)다. 차단기가 인프라로 열리면 창의 인프라
  실패 절반 이상이 그 둘일 때 `llm_outage`(시계로 반쯤 연다) 대신 `external_worker`(auto 없음)다 — 워크플로가 없으면 시계로 다시 열어도
  같다(`review_ops.outage_hold`). 엔진이 이미 EXTERNAL_LLM_WAIT_S 를 기다렸고, 부재 판정 뒤에는 그 사람의 과제를 곧바로 실패시키므로
  창이 금방 찬다.
- 쟁점 패널 — 엔진이 좌석 기다림과 의장 재호출을 다 쓴 뒤 `chair_failed{cause: external_worker_*}` 로 끝낸다. 패널은 종전 결정문 없음
  길(차감 없음)로 닫고 잡만 `external_worker` 로 멈춘다.
- 종합 — 요약의 인프라 한도(HWAXRISK_SUMMARY_INFRA_MAX)까지는 종전대로 다시 내고, 그 뒤 서술 없이 닫는 대신(infra_exhausted) 요약을
  대기로 두고 잡을 `external_worker` 로 멈춘다.
- 길잡이와 보류 글이 '잡 주인의 Claude Code 에서 워크플로 hwax-risk-claude 를 그 사람의 PAT 로 (다시) 돌린 뒤 재개' 를 말한다.

### XR-7. 설정 문제는 보류 external_config 하나
- `external_llm_disabled` · `external_consent_required` · `external_owner_missing`(카드 대조 스트림 전 거절 · 심의 error 프레임)과 중계의
  질의 누락은 셀 탓이 아니고 다시 내도 같다 — 차감 없이 `external_config`(auto 없음)로 멈춘다. 패널 error 는 UNCHARGED 코드로 적어
  연속 오류(ENGINE_FAIL_STREAK)에 세지 않는다. 엔진이 모르는 llm 값(bad_request)은 앱이 보내지 않는 값이라 종전 계약 어긋남 그대로다.

### XR-8. 무엇이 돌았나는 엔진의 표지로 — llm_mismatch
- 카드 대조 · 요약은 답의 `meta.llm`, 패널은 result 프레임의 `llm` 이 정본이다. claude 잡인데 external 이 아니면 답은 받되(이 박스의
  LLM 답이라 반출은 없었다) Claude 로 적지 않는다 — 호출 행 `quality_json.app.llm_mismatch{want, got}` · 패널 quality flags
  `llm_mismatch` · 잡 params `llm_mismatch`(json_set 한 문장으로 올린다 — 동시 워커가 잃지 않게).
- 카드 대조에서는 판 대조(expect 의 외부 판)가 먼저 걸려 실제로는 rev_mismatch(contract)가 되기 쉽다 — 이 표지는 뒤 그물이다.
  패널은 X-3a 전의 중계가 `delib_opts.llm` 을 버렸으므로 그때 바로 이 표지가 섰을 길이다.

### XR-9. 표기 — 판단 LLM 은 돈 것에서 센다
- 품질 글 첫 줄 · 전문가 보고서 머리 · 종합 보고서 머리 줄은 받은 호출 가운데 외부 응답자 답(엔진 계약상 `model: external`)과 어긋남을
  센다(`review_quality.judge_llm`) — 외부만이면 '판단 LLM: Claude(외부, 사용자 신고 모델)', 섞이면 판마다 호출 수, 어긋남이 있으면 그
  수. 요약 서술 머리 · 쟁점 패널 줄도 같은 말을 단다.
- 원장 지문(`_ledger_hash`)의 행에는 칸을 더하지 않고 따로 센다 — GLM 대상의 품질 글 · 보고서 바이트가 그대로다(시험이 본다).

### XR-10. 하지 않은 것 · 남긴 것
- 사람이 처분(다시 · 넘김)으로 세우는 검토 잡, 사람이 올린 쟁점의 잡, 보고서 다시 내기의 종합 잡은 GLM 이다 — 동의는 잡마다이고
  사슬 밖으로 넘기지 않는다(살아 있는 claude 잡이 그 셀을 집으면 claude 로 돈다). Claude 로 다시 돌리려면 새 잡을 claude 로 만든다.
- 외부 잡의 워커도 앱의 동시 수와 /health 관문 수(GLM)에 함께 센다 — 엔진의 주인마다 상한은 `review_busy{external_per_owner}` 기다림이
  지킨다(보수적이다 — 사람이 띄운 심의로 GLM 관문이 줄면 외부 잡도 같이 준다).
- main d18e9d6 의 전체 시험에는 X-1 탓 실패가 하나 있었다 — 엔진 요청 모델에 llm · consent_external 이 들어 가짜 엔진의 모양 표와
  갈렸다(test_card_review_request_contract). 가짜 엔진이 엔진을 따르게 고쳐 이 가지에서 닫았다.

### XR-11. 시험 · 변이 · 전체 시험
- 새 시험 두 파일(가짜만 — 실제 Claude 는 부르지 않는다) — `test_external_llm_contract.py`(엔진 외부 계약 예제 22개의 바이트 사본을
  엔진 클라이언트 · 분류표 · 심의 수집에 그대로 흘린다 — 25건) · `test_external_llm_jobs.py`(잡 만들기 · 루프 · 사슬 · 쟁점 패널 ·
  요약 · 표기 · 길잡이와 GLM 이 그대로인지 — 35건). 포털 요청 모델 시험(`test_wiring_regressions`)에 claude 패널 본문 한 건 —
  포털 main(X-3a 뒤)이 llm · consent_external 을 받고 버리지 않는다.
- 고친 기존 시험은 둘이고 둘 다 늘어난 계약 표면의 고정이다 — MCP `risk_start_job` 의 인자 집합(llm · consent_external), 보류 코드표의
  사람이 재개하는 집합(external_worker · external_config). 가짜 엔진의 요청 모양 표는 엔진(X-1)을 따르게 고쳤다(XR-10 끝 줄).
- 변이(스크래치 사본, 22개) — 동의(참 같은 값 · 검사 없음) · 능력 거절(탐침 없음 · 능력 무시) · 동의한 사람의 PAT 만(쟁점 잡 · 검토
  잡 · 패널의 엔진 자격) · 사슬 상속 · external_worker(차단기 · 차감 · 패널 · 요약) · llm_mismatch(카드 대조 · 패널 · 요약) · 중계 질의
  누락 · GLM 칸 없음 · 판단 LLM 표기 · 설정 보류(카드 대조 · 패널) · 패널 본문 · 외부 근거 예산. 첫 판 21/22 — 살아남은 m3b(패널의
  엔진 자격을 동의 기록에 박지 않음)는 사슬이 요청자와 동의 기록을 함께 물려주어 같은 값이라 살았다. 둘이 갈린 잡의 시험을 더해
  22/22(마지막 머리 b711f3a 에서도 22/22).
- 전체 시험(공유 잠금 아래, b711f3a) — 3,277 통과 · xfail 4 · 실패 0(rc 0). ruff 깨끗하다.

### XR-12. 동의는 번지지 않는다 — 길(lane)로 나눈다(반대 검토 X-D7 ①, 10-16)
- 결함 — 쟁점 · 종합 잡이 대상마다 하나라는 규칙(사슬 `_busy` · `_rearm`, 사람의 쟁점 올리기, 보고서 다시 내기의 대기 종합 잡 재사용)이
  길을 가리지 않았다. 남의 GLM 사슬이 살아 있는 claude 쟁점 잡을 다시 세우고 그 잡이 그 쟁점을 동의한 사람의 PAT · Claude 로 냈으며(탐침
  2a), 사람이 다시 올린 쟁점이 claude 잡에 붙었고(2b), 사람의 보고서 다시 내기가 대기 claude 종합 잡을 돌려받았다(2c). XR-10 이 'GLM 이다'
  라고 적은 세 갈래가 실제로는 claude 로 돌았다.
- 길 — 잡의 길은 (판단 LLM, 동의한 사람)이다(`chain.job_lane` — GLM 은 ('glm', None), claude 는 ('claude', consent_external.by)).
  '살아 있으면 새로 세우지 않는다 · 다시 세운다 · 대기 잡을 다시 쓴다' 는 같은 길의 잡끼리만이다 — `chain._busy` · `chain._live(lane)` ·
  `synth.create_synth_job`(대기 종합 잡 재사용) · `routes.put_issue`(살아 있는 GLM 쟁점 잡만 — `issues.NOT_CLAUDE_SQL`). GLM 사슬 · 사람의
  올리기 · 보고서 다시 내기는 claude 잡을 건드리지 않고 GLM 잡에 붙거나 GLM 잡을 세운다. 다른 사람의 claude 사슬은 제 claude 잡을 세운다.
  같은 사람의 claude 사슬만 그 사람의 살아 있는 claude 잡을 다시 세우고 거기에 일을 더한다.
- 묶음(데이터) — claude 쟁점 잡의 params `issue_rounds`{쟁점 id: 고른 회차}(JSON 칸 — DDL 은 v5 그대로). 사슬이 잡을 세울 때 그 걸음(회차
  R)이 대기로 세운 쟁점(사람이 정한 것 빼고 — `issues.step_selection`)을 적고, 같은 길의 다음 걸음은 `issues.bind_issues` 로 더한다.
  그 잡이 도는 쟁점(`issues.claude_claims`)은 적은 쟁점 가운데 대기이고 사람이 정하지 않았고(status_source 'human' 아님) 지금 회차가
  적은 회차와 같은 것이다 — 뒤의 걸음(어느 길이든)이 다시 고르면 그 걸음의 길로 넘어간다(마지막으로 고른 걸음이 이긴다 — GLM 걸음이 다시
  고른 쟁점이 claude 잡에 남아 Claude 로 나가지 않게). 두 claude 잡이 같은 쟁점 · 회차를 적었으면 먼저 선 잡의 것이다. GLM 쟁점 잡은
  끝나지 않은(queued · running · paused · cancelling) claude 잡의 몫이 아닌 대기 쟁점을 돈다.
- 종합 — 종합 잡의 일은 제 run 의 요약 행(run_id = 잡 id)이고 시작할 때의 원장으로 짓는다. 길이 다른 요청은 그 잡을 다시 쓰지도 다시
  세우지도 않으므로 claude 종합 잡에 남의 요청이 섞이지 않는다. 입력은 본래 대상 전체다(영역 요약은 그 영역이 제기에 참여한 등록부 행
  전부 — 다른 사람의 검토 결과가 든다). 그래서 반출 경고가 그것을 말한다(아래).
- 길에 따라 바꾼 곳 — 편성(`plan_issue_panel` → `_lane_rows`), 남은 대기 쟁점 놓기(`untry_queued(job_id=)` — 취소 · 실패한 그 잡의 길
  것만), 패널이 결과 없이 닫힌 쟁점의 고아 판정(`_orphan_reason(issue_id)` — claude 잡의 몫이면 그 잡이, 아니면 살아 있는 GLM 잡만 다시
  집는다), 사슬의 대기 수(`glm_queued_n`). claude 잡이 없는 대상에서는 모두 종전과 같은 행 · 같은 결과다(GLM 시험 · main 시험 그대로).
- 두 길이 한 대상에 함께 산다 — 쟁점 잡은 패널 러너가 대상마다 도는 패널 하나로 줄 세우고(`claim_next_job` 의 대상당 직렬 — 먼저 선
  잡부터, 멈춘 잡은 건너뛴다), 종합 잡은 종합 워커가 대상마다 한 잡씩 돈다(먼저 선 잡부터 — 보류된 잡은 다음 잡에 자리를 비킨다). 따로
  막는 규칙을 더하지 않았다(직렬은 이미 있다). 남은 관찰 — 길잡이의 사슬 단계(`chain_stage`)는 살아 있는 것 가운데 가장 늦게 선 잡 하나만
  보인다(멈춘 claude 잡이 앞이면 GLM 잡이 보일 수 있다 — 잡 목록에는 둘 다 있다).
- 반출 경고 — '이 잡의 지식카드·설계 변경 원문' 만 말하던 것을 '…과, 사슬이 이어 도는 쟁점 패널·종합 요약의 입력(이 대상 전체의
  등록부 행·쟁점·요약 — 다른 사람의 검토 결과도 든다)' 으로 고쳤다(review_runner.EGRESS_WARNING — 422 글 · MCP 도구 설명 · REST 본문
  설명). 포털 PLAN.md 3절이 인용한 옛 문구는 포털 몫이다.
- `create_synth_job` 의 답은 늘 `llm`(glm · claude)을 말한다 — GLM 잡의 params 에는 여전히 칸이 없다(보고서 다시 내기 응답에만 `llm: glm`
  이 더해진다 — 의도한 GLM 응답 변화 하나).

### XR-13. 재개한 종합 잡은 인프라 다시 내기 몫을 다시 갖는다(X-D7 ③)
- 결함 — 보류 external_worker 는 요약의 인프라 셈이 한도에 닿아 걸리는데 셈을 그대로 두어, 사람이 재개한 뒤 일시 실패(agent_timeout) 한
  번에 그 요약이 서술 없이 닫혔다(infra_exhausted, 탐침 1).
- 고른 것 — 보류를 걸 때 0 으로 돌린다(재개할 때가 아니라). 그 잡의 대기 요약 전부(run_id)의 infra_streak 를 0 으로 하고, 몇 번 뒤
  멈췄는지는 잡 행 글('인프라 다시 내기 N회 뒤 멈췄다')과 요약 행의 error_code · error 가 말한다. 이 갈래는 외부 응답자 코드
  (EXTERNAL_WORKER_CODES)에서만 열리므로 GLM 요약의 셈은 그대로다. 재개 쪽(runner.resume_job)에 두지 않은 까닭 — 패널 · 검토 · 종합
  잡이 함께 쓰는 문이라 종합의 한 보류만을 위한 갈래를 거기에 넣지 않았다.
- 시험 — 재개 뒤 일시 실패 한 번은 다시 내기(infra)이고 서술이 선다 · 재개 직후 곧바로 일꾼 부재면 곧장 보류하지 않고 백오프(셈 1)를
  거쳐 한도에서 다시 보류한다.

### XR-14. 무엇이 돌았나를 모델 칸에도 — 패널 모델 · 패널 모드의 llm(X-D7 LOW)
- claude 쟁점 패널의 model_json.model 은 외부 길 이름(external)이다 — 지표 · 학습의 모델 층화(metrics.panel_models · learning)가 그
  패널을 /health 의 GLM 모델로 세지 않는다. /health 의 모델은 box_model 에 남는다. 엔진이 외부 길로 돌지 않았으면(llm_mismatch) 완료가
  model 을 실제로 돈 그 box_model 로 고치고 llm 칸을 뺀다. 끝의 모델 재확인도 같은 길로 떠 model_changed_midrun 이 거짓으로 서지 않는다.
- `risk_start_job(mode='panels', llm='claude')` 는 살아 있는 패널 잡이 있으면 그 잡을 돌려주며 선택을 말없이 버렸다. 이제 llm ·
  consent_external 을 준 패널 요청은 살아 있는 잡을 돌려주기 전에 본문을 본다(검토 잡과 같은 차례) — claude · 동의 칸은 422(E100)다.
  패널 본문의 consent_external 도 422 다(패널 잡은 반출이 없다). 칸이 없거나 llm=glm 이면 종전 그대로 살아 있는 잡을 돌려준다.

### XR-15. 동의 기록에 사람이 없으면 닫힌 채 실패한다(X-D7 LOW)
- 숨은 길 — 쟁점 패널의 엔진 자격과 종합 워커의 이메일이 `동의한 사람 or 요청자 or 대상 소유자` 였다. 동의 기록에 by 가 없는 claude 잡이면
  남의 PAT 로 과제가 섰다. 지금 길(사슬 · 검토 잡 만들기)은 by 를 늘 적으므로 숨어 있던 것이다.
- 고침 — `runner.resolve_job_credential` 은 by 가 없으면 자격 없음(NO_CONSENTER_NOTE — 러너가 집지 않고 까닭을 적는다), `run_panel` 은
  편성 전에 설정 보류(external_config), 종합 워커는 창도 묻지 않고 설정 보류다. 요청자 · 대상 소유자 · 서비스 계정으로 내려가지 않는다.

### XR-16. 엔진의 자체 에이전트 거절을 리스크 잡까지 넓힌다(X-D7 ④ — HWAXAgentServer 가지 `x2-gate`)
- 이 박스의 GLM 챗 · 심의 에이전트가 사용자 이름으로 `risk_start_job(llm=claude, consent_external=true)` 를 부르거나(바로 · invoke_tool ·
  게이트웨이 별칭) REST 다리(rest_call)로 리스크 앱 잡 경로에 그 칸을 실어 보내면 지식카드에 숨은 지시 한 줄로 동의가 지어진다. 엔진 X-D6
  의 거절(_AGENT_NO_EXTERNAL)을 그 도구와 다리로 넓혔다 — risk_start_job 은 llm 이 claude · external 이거나 동의 칸이 있으면, rest_call 은
  본문에 동의 칸이 있으면(어느 경로든) · 리스크 잡 경로(…/targets/<key>/jobs · …/jobs/<id>/<action>)의 본문 llm 이 claude · external
  이면 게이트웨이에 닿기 전에 도구 오류로 끝난다. 그 칸이 없는 호출은 그대로다. 자세한 것은 그 가지의 커밋과 포털 X-D7.

### XR-17. 외부 쟁점 패널에 대상 열쇠를 싣는다(X-D8 ⑦ 안 a — 코디네이터 결정, 10-16)
- 까닭 — 엔진은 외부 과제 머리의 target_key 를 질문 머리 '[리스크심사 <코드> <키>]' 에서만 읽는데 쟁점 패널 질문은 '[쟁점 …]' 로 시작해
  과제 머리에 대상 열쇠가 없었다. 워크플로(X-3)는 제가 맡은 대상의 과제만 답하므로 claude 쟁점 패널의 과제를 영영 답하지 않는다.
- 앱 — claude 잡의 쟁점 패널 delib_opts 에 `target_key`(그 잡의 대상 열쇠)를 싣는다(runner.run_panel — 앱이 띄우는 외부 심의는 이것
  하나다). GLM 패널 본문은 그대로다(시험이 본다).
- 엔진(가지 x2-gate) — 외부 심의(llm=external)일 때만 `delib_opts.target_key`(MCP advanced 도)를 읽어 그 심의의 과제 머리 · 과제 기록에
  싣는다(질문 머리보다 앞선다). 꼴은 'diff:<id>' · 'snap:<id>' 이고 아니면 심의를 열기 전에 bad_request 다. GLM 심의는 보내도 읽지 않는다
  (사건 · LLM 이 받은 글이 같다 — 시험이 본다). 그 밖(앞 패널 보고서 거름 따위)에는 쓰지 않는다. 계약 예제 delib_frames.json 에 그 칸과
  '쟁점 패널 꼴 질문의 과제 머리' 를 더했고, 이 리포의 바이트 사본도 같이 바꿨다 — 그래서 이 가지의 사본 가드는 엔진 x2-gate 를 짝으로 본다
  (`HWAX_AGENT_SERVER_REPO=<x2-gate 작업 트리>` — 엔진 main 에 합치기 전까지).
- 포털 — 중계(DelibOpts)가 target_key 를 선언 · 전달하는 것은 포털 몫이다(코디네이터). 그 전에는 포털이 그 칸을 말없이 버린다 — 시험
  `test_a_claude_issue_panels_target_key_reaches_the_engine_through_the_portal_model` 이 strict xfail 이다(포털 DelibOpts 가 그 칸을 선언하면
  표식이 스스로 꺼지고 엄격히 돈다). 기존 시험은 llm · consent_external 이 버려지지 않는지를 그대로 본다.

### XR-18. 시험 · 변이 · 전체 시험(반대 검토 고침, 10-16)
- 새 시험 — `test_external_llm_lanes.py`(함수 21 · 모은 시험 22): 탐침 다섯(2a · 2b · 2c · 1 · mcp_bool/mcp_strict)을 그 장면 그대로 옮기고
  단언을 고친 동작으로 바꿨다. 더해 두 길이 한 대상에 사는 장면(제 몫만 돈다 · 취소 두 차례 · 고아 판정 · 같은 길만 다시 쓰기 · 다시 고른
  걸음이 이긴다 · GLM 걸음의 대기 셈 · 사슬 걸음의 몫 · 같은 사람의 다음 걸음 · 종합 단계의 길 · 생산자 경로의 claude 사슬), 재개 뒤 인프라
  몫 셋(잡의 대기 요약 전부), 패널 모델 둘, 패널 모드, 동의자 없는 잡. 고친 기존 시험 — `test_external_llm_jobs.py`(반출 경고 글 · 보류 때
  셈을 0 으로 · claude 패널의 target_key · GLM 패널에는 없음), `test_wiring_regressions.py`(포털 경유 claude 패널 — target_key 는 따로
  strict xfail).
- 변이(스크래치 사본) — 앱 30개: 첫 판 26/29. 살아남은 셋 — 'claude 잡 취소가 대상 전부를 놓는다'(시험이 GLM 먼저 취소해 가려졌다 —
  취소 두 차례로 고쳤다), 'GLM 걸음이 claude 몫도 센다'(고르기 뒤에만 드러난다 — 고르기를 비운 GLM 걸음 시험을 더했다), 셈 되돌림의 한
  문장만 지운 변이(남은 문장이 덮는다 — 둘 다 지우는 변이로 바꾸고, '그 요약만 되돌린다' 변이를 나눠 잡 전체의 몫 시험을 더했다). 고친 뒤
  30/30. 엔진(x2-gate) 13/13(리스크 잡 시작 · REST 다리 · 별칭 · 경로 · 대상 열쇠 꼴 · GLM 은 읽지 않음 · 칸이 머리보다 앞섬 · X-D6 회귀 그물).
- 전체 시험(공유 잠금 아래, `HWAX_AGENT_SERVER_REPO=x2-gate 작업 트리`, a111e95) — 3,299 통과 · xfail 5(기존 4 + 포털 target_key 중계
  strict xfail 1) · 실패 0(rc 0). 그 작업 트리에는 엔진 venv 를 가리키는 `.venv/`(심링크 — 무시되는 이름)를 두었다 — 형제 엔진 시험이
  `<엔진 리포>/.venv/bin/python` 을 부른다.
- main(d18e9d6)의 시험을 새 앱 코드에 대어(스크래치, 형제 없이) — 3,197 통과 · 실패 2 · 건너뜀 15 · xfail 4. 실패 둘은 반대 검토 때와 같은
  X-2 표면 고정(risk_start_job 인자 집합 · 사람이 재개하는 보류 코드표)이다 — 새 차이가 없다.
- GLM 출력 견주기(반대 검토의 하네스 — 같은 장면을 두 번 떠 흔들리는 칸을 걸렀다) — 검토한 머리(4ac2b92)와 견주어 다른 것은 종합 잡
  만들기 답의 `llm: glm`(뜻한 것) · risk_start_job 설명 글 · 벽시계로 잰 초 값뿐이다. 잡 만들기 · 검토 루프 · 차단기 · 내용 실패 · 쟁점
  패널 · 사슬은 같은 바이트다. ruff 깨끗하다.

## ECAD 1단계(가지 `wt1031/ecad`, main ecad8c8 위, 2026-10-31)

> 요청서 정본은 포털 `docs/design-risk-review/ecad-1031/request.md`(ER-01 ~ ER-06 · OH-01 ~ OH-05 · 부록 A cae00 10-31 실측)이고
> 사용자 결정 D-1 = (가)다 — 계약 4도구를 새로 내지 않고 ODB 허브가 지금 도구에 묶음 읽기를 더한다. 이 가지는 1단계(ER-01 ~ ER-05)만
> 짓는다. 화면은 화면 세션 몫이라 요청만 넘기고, 포털 plan §2.5.3 · §2.13.5 는 포털 세션이 고친다(바꿀 글은 결과 보고에). dev 게이트웨이에는
> odb-hub 가 없다 — 시험은 부록 A 꼴의 가짜이고 실물 확인은 cae00 다시 볼 시험(요청서 6절)이다.

### EC-1. 보드의 자리는 소스 카드 한 장이다 — 스키마를 바꾸지 않는다
- `rr_sources.kind` 의 CHECK 가 이미 `ecad` 를 받는다. 보드는 kind `ecad` 카드이고 ref 는 `{odb_job_id}` 다. 자리는 과제다 — 심사 대상
  (`rr_targets`)은 스냅샷 뒤에 서서 캡처 전에 보드를 담을 수 없다.
- 일반 소스 연결로는 붙이지 않는다 — (a) find_job 확인 없이 아무 글자나 붙고 (b) 같은 kind 의 둘째 행이 생기면 캡처가 uuid 순서로 고르며
  (c) 소스를 지우는 길이 없다. 그래서 `PUT · DELETE /api/projects/{id}/ecad-board` 가 따로 있고, 일반 연결의 kind ecad 는 422
  `ecad_board_route`(고칠 곳 fix)다. MCP `risk_add_source` 는 같은 kind 검사(source_kind_taken)보다 먼저 거절한다.
- 바꾸기는 같은 행 UPDATE 다(DELETE + INSERT 가 아니다) — 반출 · 들여오기는 같은 PK 행을 병합하지 않고 새 PK 만 넣어, 지우고 새로 넣으면
  받는 박스에 카드가 둘이 된다. 떼기의 삭제는 들여오기가 옮기지 못한다(지운 행 일반의 한계 그대로).
- 감사 `project.ecad_board`(before · after 의 job_id) — 바뀔 때만 남긴다. 인자 이름은 `odb_job_id` 다 — 이 앱의 `job_id`(rr_jobs ·
  캡처 잡)와 섞이지 않게.

### EC-2. 고르는 것은 사람이다 — 찾기는 후보만, 붙이기는 find_job 확인
- 찾기(`GET /api/ecad/boards?q=` · `risk_find_ecad_boards`)는 find_job 한 번의 후보를 최대 10개와 `truncated` 로 그대로 준다. 같은 모델의
  다른 판이 함께 나오므로 고르지 않는다 — 올린 시각 · 파일 이름까지 싣는 까닭이다. 허브의 봉투형 오류(찾는 것이 없다)는 빈 후보와
  `hub_message` 다.
- 붙이기는 그 job_id 가 find_job 후보에 있을 때만 적는다 — 지어낸 job_id 는 422 `ecad_board_not_found`. 꼴(16자리 16진)이 틀리면 허브를
  부르기 전에 422 다. 대소문자는 허브가 준 꼴로 적는다.
- 찾기 MCP 도 위임 문(`require_delegate`)을 지난다 — 그 사람의 등록된 PAT 로 게이트웨이를 부르는 일이고 찾는 까닭이 쓰기다
  (`risk_get_brief` 선례 — `DELEGATE_GATED_READS`). 자격은 캡처와 같은 해석(그 사람의 포털 PAT, 없거나 곧 끝나면 박스의 읽기 PAT)이라
  찾아진 보드는 캡처도 읽는다.

### EC-3. 발견은 백엔드 키와 원래 이름이다 — 캡처의 모든 MCP 호출도
- 게이트웨이 재집계(HWAXMcpGateway)는 이름이 겹치면 `backend.replace('-','') + '_'` 를 붙인다(선언 백엔드면 선언 쪽만). 그래서 두 꼴
  (원래 이름 · 접두형) 가운데 그 백엔드의 것만 본다(`base.backend_tool_name`). 다른 백엔드의 같은 이름은 보지 않는다.
- 종전 해석(suffix 를 모든 백엔드에 맞춤)은 `list_parts` 가 `heaxstep_forge_list_parts` · `odbhub_list_parts` 둘이라 다의가 되어 맨이름으로
  불렀고, 맨이름은 게이트웨이에 없다. `CallRecorder` 가 도구 지도와 그 호출의 app_key 로 먼저 푼다(지도에 없으면 종전 해석). 부수 효과로
  cae00 에서 mcad 의 MCP 폴백 `list_parts` 가 같은 까닭으로 죽어 있었을 것이 살아난다 — cae00 에서 확인하지 못한 코드 대조다.
- 지도는 `clients_from_settings` 가 받는다(`gateway_tool_map` — 발견과 같은 60 s 캐시, `tool_names` 는 그 열쇠). 캡처 경로는 스스로 발견
  요청을 내지 않는다(E2E '외부 호출 안 함'). ecad 는 지도가 없으면 부르지 않는다 — 맨이름 `list_parts` 는 다른 앱의 도구일 수 있다.
- `/meta/adapters` 의 ecad 는 실측이다 — ready · unavailable(tools_missing) · planned(게이트웨이를 못 읽음). `contract_only` 는 없어졌다.
- 게이트웨이는 접두를 '지금 붙어 있는 백엔드끼리 겹칠 때만' 붙여, 다른 앱이 재배포로 잠깐 빠지면 그 창에서 이름이 맨이름으로 돌아간다. 지도는
  60 s 캐시라 그 창에서 지도와 실제가 어긋날 수 있다. 게이트웨이의 호출 전용 별칭(`odbhub_<원래 이름>` — 목록에는 없고 늘 불린다)이 그때의
  대안이지만 쓰지 않았다 — 정본(§2.13.2)은 지도의 실이름을 호출 인자와 원장에 적게 하고, 같은 창은 mcad · dyna 에도 있다.

### EC-4. 응답 계약은 어댑터마다 제 표로 잰다
- 계약표(`RESPONSE_CONTRACT`)는 맨이름 키라 ODB 허브 `list_parts` 를 StepForge `list_parts` 의 `/parts` 로 재면 늘 위반이다.
  `CallRecorder.call(response_contract=)` 로 어댑터가 제 표를 넘긴다(넘기지 않으면 종전 표).
- find_job 은 봉투 열쇠가 부록 A 에 없어 계약을 두지 않는다. `job_rows` 가 알려진 꼴(jobs · matches · results · items · 맨 목록 · 잡 하나)만
  읽고 못 읽으면 드리프트로 닫는다. 가짜는 list_jobs(허브 레퍼런스 4.2)와 같은 `jobs` 다 — cae00 에서 봉투를 한 번 본다.

### EC-5. 1단계 사상에서 고른 것
- **board 노드는 만들지 않았다.** 계약(§2.5.3)은 `odb_get_board` 를 `sources[ecad].ref.{board_id, name}` · `source_hash` · G6 입력으로 옮기고
  ('보드 1장 = 소스 1건') 노드 kind 어휘에 board 가 없다. 요청서 4절의 'board 1건' 을 소스 1건으로 읽었다 — 보드 값은 `sources[ecad].stats`.
- 층 두께는 mm 다 — rr_ir 의 길이 단위가 mm 이고 계약은 두께 단위를 보드 units 로 선언한다. 허브는 µm(`thickness_um`)로 준다.
- idx 는 5종으로 거른 뒤 위에서 아래로 1부터(부록 A). 재료는 판정이 standard 이고 표준 적층 층(실크가 없다)과 보드 5종 행(실크 제외)의 수 ·
  구분 차례가 하나하나 같을 때만 자리대로 옮긴다 — ambiguous 도 비운다(후보가 여럿이다).
- `n_components` = `list_parts.total`(분류된 부품) — component 노드의 원천과 같은 값이라 요청서 6절 시험('component 수 = total')이 성립한다.
  배치 수는 `n_components_placed`, 근거는 `n_components_basis: 'classified'`.
- 이름은 project · model · board_type · revision 을 `' / '` 로 엮는다(job_name · step_name 은 쓰지 않는다). source_hash 는 64자리 16진만이고
  job_id 가 그 앞 16자리가 아니면 INFO 경고다.
- 부품 분류(category) · 패키지 치수(pkg_width · pkg_length)는 계약 밖이라 싣지 않았다 — 실으려면 계약에 먼저 적는다. 예약 치수
  `ecad_stackup_total` 은 시드가 없어(mcad 예약 치수도 없다) 값을 `stats.stackup_total_mm` 에 둔다.

### EC-6. 실패를 넷으로 가른다
- 보드 없음 → 스텁 봉투(INFO `ecad_absent`).
- 붙었는데 못 읽음(MCP 자격 없음 · 그 백엔드에 1단계 도구가 다 없음 · find_job 실패 · 그 job_id 없음 · find_job 드리프트) → `ecad_absent` +
  `ecad_capture_failed` 와 까닭 경고(`ecad_pat_absent` · `ecad_tools_missing` · `capture_call_failed` · `ecad_board_not_found` ·
  `source_schema_drift`). dyna 의 자격 없음(`dyna_absent` 만)과 다르게 capture_failed 를 세운 까닭 — 붙은 보드를 못 읽은 스냅샷을 ECAD 가
  실린 앞 리비전과 비교하면 부품 수백 개가 '사라짐' 이 된다. capture_failed 면 비교의 capture_parity 가 거짓이라 의미 이벤트를 만들지 않는다.
- 선택 호출 실패 → `capture_partial` + `capture_call_failed`(정본 §2.11.3 표). 부작용 — G3 · R-001 이 n/a(capture_partial)가 된다(그 판정은
  모든 소스의 degraded 합집합을 본다). 드문 일이라 정본대로 두었다.
- 허브의 봉투형 오류(200 + error — 분석을 돌리지 않은 보드) → 경고 `odb_error_body` 만. 호출 행은 ok 로 남는다(전송은 됐고 본문이 그 값이
  없다고 말한다) — 그래서 잡이 partial 이 되지 않고 카드도 linked 다.
- 쪽 넘김 — has_more(없으면 total)를 따르고, 새 행이 없으면 멈추며(`odb_paging_stalled` + capture_partial), 2000 을 넘으면 앞의 것만
  (`components_truncated`), 받은 행이 total 보다 적으면 `components_incomplete` + capture_partial 이다. 인자는 기본값이라도 다 싣는다(허브가
  빠진 선택 인자를 거부한 적이 있다 — 허브 레퍼런스 1절).

### EC-7. 결측 행의 세대는 0.0-stub 그대로다
- `diff.comparability` 의 adapter_parity 는 공통 kind 전부의 adapter_versions 를 본다. capture_all 은 ecad 결측 행을 늘 남겨 ecad 는 모든
  스냅샷의 공통 kind 다. 결측 행 세대를 1.0 으로 올리면 배포 앞뒤 스냅샷의 모든 비교에 `parser_differs`(신뢰도 한 단계 낮춤)가 붙는다.
  노드를 만들지 않은 소스에는 매핑표가 없으니 세대가 바뀔 까닭도 없다. 보드를 실은 소스만 `1.0` 이다.

### EC-8. 캡처는 kinds 를 따른다
- 종전 capture_all 은 kinds 와 무관하게 ecad 를 늘 돌렸다(스텁이라 무해했다). 실물이 된 지금 ECAD 없는 앞 스냅샷과 견줄 캡처를 사람이 고를
  길로 kinds 를 따른다 — 결측 행은 남긴다(EC-7). 보드 카드만 있고 kinds 에 ecad 가 없으면 읽을 소스가 없어 409 `source_unreachable` 다.

### EC-9. same-as 4단계는 ecad 노드만 뺀다(444c8c5)
- 4단계는 `ecad_here` 면 단계를 통째로 껐다 — 쌍 비교는 양쪽 노드 전부로 부르므로 ECAD 가 실린 순간 mcad · dyna 의 지문 대응까지 꺼진다.
  정본 '1차 ecad 는 1·5·7 단계만' 은 ecad 노드를 빼라는 뜻이다. 3단계(mcad 끼리)도 짝 목록에서 ecad 를 뺀다 — 짝 목록이 단계마다
  N×M 이라 보드 부품 1,500 개가 양쪽에 실린 쌍(dev 실측)이 2.0초 · 372 MB 에서 0.9초 · 227 MB 로 준다. 5단계는 ecad 끼리 · ecad↔mcad
  이름 대응이 있어 그대로다.

### EC-10. 신호는 실리지 않은 칸을 0 으로 세지 않는다
- `sig:counts.ecad.nets` 는 `ecad_nets_deferred` 면 미측정이다(종전 계산은 ECAD 가 실리기만 하면 0 을 '안다' 고 적었다). 부품 목록을 못 읽었으면
  (`stats.n_components` null) 부품 수도 미측정이고, 분류 안 된 부품이 빠졌으면 글에 '(분류된 부품만)' 을 단다.

### EC-11. ECAD 의존 도메인 6 은 여섯 다 deferred 에서 풀린다(ER-05)
- 편성 규칙(planner)이 `missing.ecad_absent` 하나로 가르므로 1단계 캡처 뒤에는 pcb · pwr · rf · soc · passive · mem 이 전원 편성되고 카드 대조의
  입력 결손도 사라진다. 도메인마다 무엇을 보고 무엇을 못 보는지는 계약 문서 'ECAD 의존 도메인 6' 표다. 넷 의존 도메인(pwr · rf)을 2단계까지
  deferred 로 남기는 규칙은 두지 않았다 — 요청은 '어디까지 풀지 적는다' 였고, 편성 규칙을 바꾸면 설정 · 카드 대조 입력 결손 · 시험이 함께
  바뀐다. 결정 필요로 남긴다.

### EC-12. 하지 않은 것 · 남긴 것
- **한쪽에만 ECAD 가 있는 비교** — 첫 보드를 붙인 캡처를 ECAD 없는 앞 스냅샷과 비교하면 부품 · 층 노드가 전부 `part.added` 다(의미층이
  도메인을 가르지 않는다). 지금 우회는 앞 리비전에도 보드를 붙여 다시 캡처하거나 kinds 에서 ecad 를 빼고 캡처하는 것이다. 한쪽에만 있는
  kind 의 노드를 비교에서 빼는 규칙은 결정 필요다.
- **모델 크기 상한** — 정본 §2.11.3 은 ECAD 부품 수도 리프로 세라고 적었지만 코드(`_check_model_size`)는 mcad 리프만 센다. 세면 부품
  1,500 개 넘는 보드는 늘 allow_large 가 든다 — 결정 필요.
- 2단계(ER-06) · 화면 · 포털 plan · `units._DEGRADED_NOTE` 의 새 표지 글(코드 이름 그대로 나간다) · 길잡이(`risk_next_step`)의 ECAD 안내 ·
  same-as 5단계의 쌍 목록 비용은 하지 않았다. 서비스 재기동 · 배포는 없다(가지는 push 하지 않았다).

### EC-13. 시험 · 변이 · 전체 시험
- 새 시험 `tests/test_ecad_adapter.py` — 부록 A 꼴의 가짜 odb-hub(보드 둘 — 표준 10층 · 5종 23행 · 35행 · 분류 748 · 배치 924, 비표준 8층 ·
  19행 · 528 · 702, find_job 10개 상한과 truncated, list_parts 100행 상한, 겹친 이름 접두, 봉투형 오류)로 발견 · 캡처 · 표지 · 실패 · 보드
  찾기 · 붙이기 · 떼기(REST 함수 · HTTP · MCP) · 붙인 뒤 캡처(13번 호출 · 노드 748 + 23)를 본다. `test_sameas.py` 에 4단계 시험 하나.
  고친 시험 — `test_adapters`(스텁 시험 → 보드 없는 결측 봉투) · `test_boot`(ecad 실측 상태) · `test_brief` · `test_state_gates` ·
  `test_ir_schema_contract`(스텁 → 새 어댑터) · `test_mcp_tools`(31 → 33) · `test_no_write_tools`(쓰기 도구 · 위임 읽기에 둘) ·
  `fixtures/mcp_arg_contract.json`(새 도구 둘).
- 변이(분리한 사본 작업 트리, 바이트코드 끔) 20/20 이 잡혔다 — 4단계 통째 끄기 · 백엔드 해석 끔 · 5종 거름 끔 · 못 찾음의 capture_failed ·
  미룬 넷 0 · 붙이기 확인 건너뜀 · contract_only · 쪽 크기 · kinds 무시 · 분류 표지 · 판정 무시 재료 · µm · 소스 연결 거절 둘 · 봉투형 오류를
  값으로 · 결측 행 세대 · 후보 상한 · 찾기 위임 문 · 떼기 감사 · 어댑터 계약표. '판정 무시 재료' 는 첫 판에 살아남을 자리였다(비표준 보드는
  표준 층이 아예 비었다) — ambiguous · 한 층 모자람 · 구분 뒤바뀜 시험을 더했다(2d48c27).
- 전체 시험 첫 판(2d48c27) — 3,421 통과 · xfail 4 · 실패 3. 셋 다 남 숨김 표(`tests/rr/test_review1_stranger.py`)가 라우터 · MCP 와 같아야
  한다는 시험이었다 — 새 경로 셋 · 도구 둘이 남 시험 없이 들어왔다. 붙이기 · 떼기 · risk_set_ecad_board 를 남 시험 칸에(과제 소유 검사가
  허브 호출보다 먼저라 남은 없는 과제와 같은 404 · E404), 찾기 둘은 과제 · 대상 인자가 없어 면제에 넣고 면제 경로의 새는 값 시험에 더했다
  (1115ac8). 매니페스트 설명(MCP 도구 31 → 33 · ECAD 보드 2종 · 위임 문)도 함께 고쳤다 — HEAXHub 의 등록 사본(이미 29종으로 뒤처져 있다)은
  배포하는 쪽이 맞춘다.
- 전체 시험 둘째 판(고친 뒤) — 3,427 통과 · xfail 4 · 실패 0(rc 0, 11분 41초). ruff — 남은 하나는 main 에도 있는 `tests/test_backup_wrapper_run.py`
  의 안 쓰는 import 다(이 가지 몫이 아니다).

## ECAD 1단계 — 블랙박스 · 반대 검토 뒤 고침(가지 `wt1031/ecad`, 2026-10-31)

> 블랙박스 시험(7da7e5a, 요청서만 보고 지은 23건)을 들여오고(c4d9148) 반대 검토 지적 16건을 재현한 뒤 고쳤다. 재현은 반대 검토의 실험 17건을
> 분리한 작업 트리에서 이 가지 위에 그대로 돌려 같은 값이 나오는 것을 본 뒤다. 판단 기준은 요청서다 — 요청서가 정한 것과 다르면 구현을
> 고치고, 요청서가 열어 둔 인터페이스를 시험이 다르게 가정했으면 그 가정 도우미만 고쳤다.

### EC-14. 보드는 소스 1건이면서 board 노드 1건이다(EC-5 뒤집음 · 반대 검토 1 높음)
- 요청서 ER-03 · 4절은 'board · layer · component 노드' · 'board 1건' 이다. EC-5 는 그것을 소스 1건으로 읽었는데, ir_hash 는 노드 · 엣지만
  보므로 보드의 정체(job_id · 판 · 원본 해시)가 해시 밖이었다 — 배치 · 배선만 바꾼 판(1단계 칸이 같다)으로 바꿔 붙여 캡처하면 앞 판의 스냅샷이
  `reused` 로 돌아오고 그 스냅샷의 `sources[ecad].ref` 는 옛 보드를 가리켰다(반대 검토 E1 재현).
- kind `board`(스키마 노드 kind 어휘에 더함 — `rr_ir_nodes.kind` 는 CHECK 없는 TEXT 라 스키마 판은 그대로다), canon_key `ecad:board`, label
  `board`(판이 바뀌어도 같다 — 쌍 비교가 두 판의 보드를 5단계 이름으로 맞춘다), local_key = job_id(ecad↔mcad 이름 대응은 refdes · local_key
  토큰이 상대 이름과 겹쳐야 해 'PCB' 라는 mcad 부품과 저절로 묶이지 않는다). attrs 는 계약 odb_get_board 의 칸 + 판정 · 적층 합 · 외곽 폭 ·
  높이 · 배치 수다. `stats` 의 같은 값은 그대로 둔다(해시 밖 사본).
- 부품 refdes 가 `board` · `layer:…` · `net:…` 이면 노드 열쇠가 겹쳐 IR 이 서지 않는다(canon_key 중복은 E100) — 싣지 않고 `refdes_reserved` 경고다.

### EC-15. 찾기 · 캡처 자격은 사용자 결정으로 남긴다(반대 검토 7)
- 등록된 PAT 가 없거나 곧 끝나면 찾기 · 붙이기 확인 · 캡처가 박스 PAT(`HWAXRISK_PORTAL_PAT`)로 내려간다. odb-hub 는 사람별 격리가 없고
  게이트웨이의 `plat:odbhub` 로만 막히므로 그 문을 서비스 계정으로 지난다. 안 (a) 그 사람의 PAT 만(없으면 `ecad_pat_absent` · 409),
  (b) 내려가되 답 · 스냅샷에 자격(`service`)을 적는다 — 고르지 않았다. 블랙박스 시험은 (b) 의 박스 PAT 로 돈다(가정 — 'odb-hub 는 서비스
  토큰 하나로 붙은 백엔드'). 바꾼 것은 찾기의 설명 글(‘그 사람의 PAT 로 부른다’ 는 내려가는 경우에 틀렸다)뿐이다.

### EC-16. 호출 없이 끝난 실패는 결측 + 경고다(EC-6 일부 뒤집음 · 반대 검토 2 · 8)
- 자격 없음 · 도구 지도를 못 읽음 · 그 백엔드에 도구 없음은 find_job 을 부르지도 못했다 — dyna 의 자격 없음(`dyna_pat_absent`)과 같은 꼴로
  `ecad_absent` + WARNING 경고다. `ecad_capture_failed` 는 find_job 이 실패했거나 그 job_id 가 없거나 응답을 못 읽었을 때만이다(§2.11.3 표).
- 빈 도구 지도는 게이트웨이를 못 읽은 것이다(`ecad_gateway_unreadable` — 찾기는 409 같은 코드). 종전에는 '그 백엔드에 도구 여섯이 다 없다'
  (`ecad_tools_missing`)로 적혀 고칠 곳이 ODB 허브 등록으로 보였다. 못 읽은 지도(전송 · HTTP 오류 · 빈 지도)는 캐시하지 않는다 — 한 번의
  503 이 60 s 동안 모든 ECAD 캡처 · 찾기를 닫았다(E14 재현). 읽은 지도만 캐시한다.
- 경고 severity 는 실패면 WARNING 이다(종전에는 기본값 INFO 가 실패에도 실렸다). 보드 없음 · kinds 에 ecad 없음은 INFO 그대로다.

### EC-17. 쌍 비교의 ECAD 는 kind 별로 따진다(반대 검토 2 · 3)
- 종전 — ecad_capture_failed 하나가 `capture_parity` 를 거짓으로 만들어 쌍 전체의 의미층(mcad `iface.*` 포함)을 지우고 파라메트릭 항목을 전부
  capture_partial 로 만들었다(E4). ECAD 노드 771 개는 사유 없이 '삭제' 였다(E5b). 한쪽에만 보드가 있으면 결측 행 `0.0-stub` 대 `1.0` 이라
  `adapter_parity` 가 거짓이 되어 mcad 이벤트까지 parser_differs · 등급 낮춤이었다(E5) — 웹 기본 캡처(kinds `['mcad']`)와 MCP 캡처를 견주면 흔하다.
- 지금 — `comparability.ecad = {base, target, excluded_reason, adapter_parity}`. 쪽마다 present · absent · failed(못 읽음 또는 capture_partial ·
  components_unavailable · layers_unavailable — 노드 집합을 믿을 수 없다). 한쪽이라도 failed 면 ECAD 항목에 `capture_partial`, 한쪽에만 실렸으면
  `partial_scope` 를 의미층 **앞에서** 붙인다 — 항목은 남고 `part.added` · `part.removed` 가 생기지 않으며 검토 단위에서는 제외 단위로 간다.
  세대 차이는 두 쪽 다 실렸을 때만 견주고 ECAD 항목 · 이벤트에만 caveat 다. 전역 `capture_parity` 는 ecad_capture_failed 를, 전역
  `adapter_parity` 는 ecad 를 세지 않는다 — mcad · dyna 의 종전 동작(전역 효과)은 그대로다.
- 한쪽에만 ECAD 가 있는 쌍을 partial_scope 로 남기는 것은 EC-12 가 결정 필요로 남긴 자리를 정한 것이다. 까닭 — §3.3.6 의 잣대가 다르면 사유를
  붙여 남긴다는 규칙의 kind 별 적용이고, 남기지 않으면 첫 보드를 붙인 비교 하나가 부품 772 개짜리 '추가' 를 검토 단위로 만들어(units_max 60)
  대상을 oversize 로 몬다. 되돌리려면 `_ecad_side` 의 absent ↔ present 를 사유 없음으로 두면 된다.
- ECAD 항목의 판별은 구조층은 그 변경의 domain, 파라메트릭은 그 dn 의 노드가 모두 ecad 인가다(ecad↔mcad 로 묶인 클러스터는 mcad 쪽으로 둔다).

### EC-18. diff 대상의 ECAD 의존 영역은 1단계 동안 deferred 다(EC-11 좁힘 · 반대 검토 4)
- 1단계 쌍 비교는 ECAD 칸(층 두께 · 재료 · 품번 · 패키지 · 핀 수 · 높이)을 견주지 않는다 — 노드를 refdes · 층 이름으로 맞춰 추가 · 삭제만 본다(E11
  재현 — 네 칸을 바꾼 두 판의 쌍 비교에 ECAD 항목 0). 그 비교를 받은 ECAD 좌석은 '회로 변경 없음' 으로 읽는다.
- 고른 길 — 반대 검토의 두 안 가운데 '계획에 적고 diff 대상의 ECAD 의존 영역을 deferred 로 둔다' 다. 다른 안(1단계 칸의 파라메트릭 규칙과
  이벤트)은 승인된 거르기 표(change-routing · D-56)에 없는 코드(`param.thickness` 따위)를 더해야 하고, 예약된 `ecad.*` 이벤트로는 품번 · 패키지
  변경을 담을 코드가 없다(`ecad.component_moved` 는 배치다). 표를 사람 승인 없이 바꾸지 않는다.
- `routes._ecad_absent_for_target` · `create_target` 은 diff 대상이면 참이다 — rank 1 외 deferred, 입력 결손 `ecad_absent`. 입력 결손의 어휘는
  그대로 쓴다(엔진 · 마감 표가 `ecad_absent` 를 읽는다) — 대신 대상의 결측 블록 첫 줄(kind `ecad`)이 '칸 변화는 이 비교에 없다' 를 말하고,
  입력 결손 전문가에게는 영역 실마리가 붙는다(`units._target_missing` · `gap_missing`). 스냅샷 대상은 종전대로 풀린다.

### EC-19. 노드 가족이 통째로 빠지면 표지가 선다(반대 검토 5)
- 허브의 봉투형 오류(200 + error — 분석을 돌리지 않은 보드)는 그 칸만 비는 경고(EC-6)지만, list_parts · get_board_layers 가 그러면 component ·
  layer 가족이 통째로 없다(E18 — 표지 없이 '온전한 1단계' 로 보였다). `components_unavailable`(첫 쪽을 못 읽음) · `layers_unavailable`(층을 못
  읽음 · 5종 행 없음)를 스키마 어휘에 더했다. 그 수(`stats.n_components` · `layer_rows` · `layer_rows_all`)는 미측정(null)이다. 호출 실패도
  같은 표지가 선다(capture_partial 과 함께).

### EC-20. 쪽 넘김 — 서로 다른 행 수로 견주고 쪽 수에 상한을 둔다(반대 검토 6 · 12)
- 받은 행 수(겹친 행 포함)로 total 과 견주면 쪽 순서가 흔들리는 허브(sort 기본값)가 어떤 행은 두 번, 어떤 행은 한 번도 주지 않아도 다 받은
  것으로 보였다(E9 — 748 가운데 569~575 개, 부분 표지 없음). 서로 다른 행(겹친 refdes 는 한 번, 빈 refdes 는 행마다)으로 견주고 모자라면
  capture_partial + `components_incomplete`(받은 행 · 겹친 행 수를 함께)다. `duplicate_refdes` 글은 자료 탓만 하지 않는다.
- 쪽 수 상한 ceil(min(total, 2000)/100)+1(total 을 모르면 2000 기준) — 쪽마다 새 행 하나만 주는 허브가 1,999 번 불렸다(E10). 닿으면
  capture_partial + `odb_paging_capped`. 허브가 100 보다 작은 쪽을 주면 상한에 닿아 부분으로 적힌다 — 부록 B 는 100 이다.

### EC-21. 배치 수는 count, 없으면 counted — 분류된 수보다 작으면 경고(반대 검토 11)
- 부록 A 는 count, OH-02 는 counted 라 적었다. count 를 먼저 읽고 없을 때만 counted 다. 배치 수가 분류된 부품 수보다 작을 수는 없다 — 그 칸이
  배치 수가 아니다(E7 — 큰 부품 10개 수). 경고 `placed_below_classified` 를 남기고 `components_unclassified_omitted` 는 같다고 확인될 때만 뺀다.

### EC-22. 보드만 붙은 과제에서 보드를 못 읽으면 스냅샷을 만들지 않는다(반대 검토 9 · 10)
- §2.11.3 표 — 필수 호출이 실패하고 남은 kind 가 없으면 잡 failed 다. `capture_all` 이 이번에 읽은 kind(`read_kinds`)를 돌려주고, 그것이 ecad
  하나뿐인데 보드를 못 읽었으면(`missing.ecad_absent` — 호출 없이 끝난 것 포함) `create_snapshot` 이 409 `source_unreachable`(detail
  `{kind:'ecad', reason:<경고 code>}`)로 닫는다. 잡 행은 failed(error.reason), 호출 원문은 스냅샷 없이 남긴다(find_job 의 답을 볼 수 있다).
  capture_all 안에서 던지지 않은 까닭 — 던지면 그 호출 원문이 사라진다.
- 붙은 카드는 있는데 kinds 가 그 종류를 뺐으면 409 글이 '연결하라' 가 아니라 kinds 를 고치라고 말한다(detail `{kinds, attached}`). 웹 화면의
  기본 kinds 가 mcad 라 보드만 붙은 과제가 늘 여기 걸린다 — 화면 요청(checklist 4장).
- ECAD 카드는 호출 전송이 아니라 어댑터 결과로 잰다(`refresh_source_probes(..., results)`) — find_job 이 200 이어도 그 job_id 가 없으면
  unreachable · `capture_failed ecad_board_not_found — …` 이고, 호출 없이 끝난 실패도 카드에 남는다(종전에는 붙일 때의 find_job_ok 가 남았다).
  실었지만 부분이면(선택 호출 실패 · 쪽 넘김) linked 이되 `capture_partial calls=N …` 이다.
  capture_mode 는 그 kind 가 REST 로 읽었으면 rest_primary, 아니면 mcp 다(ECAD · dyna 에 rest_primary 가 박혀 있었다).

### EC-23. same-as 5단계는 이름으로 나눠 짝을 찾는다(반대 검토 15)
- 5단계는 name_norm_canon 이 같은 쌍만 보는데 모든 자유 쌍(free_pairs)을 펼쳤다 — 부품 2,000 개 보드 두 판의 쌍 비교가 5 초 · 최고 330 MB 였다
  (E15). b 쪽을 이름으로 나눠 두고 a 마다 같은 이름 칸만 본다 — 짝 집합이 같고 받아들이는 순서는 sorted 가 정해 결과가 같다(0.2 초 · 수 MB,
  시험은 50 MB 상한). 3 · 4단계의 free_pairs(ecad 제외)는 그대로다.

### EC-24. 남긴 것
- **provenance.call_id 가 원장 call_id 와 다르다(반대 검토 14, 기존 결함)** — CallRecorder 는 snapshot_id[:8], record_calls 는 job_id[:8] 접두라
  노드 provenance 의 `tool:<call_id>` 가 풀리지 않는다. mcad · dyna 에도 main 부터 있던 것이고 모든 어댑터의 provenance · 참조 해석이 걸려 이
  가지에서 고치지 않았다(checklist 4장).
- 1단계 칸의 쌍 비교(층 두께 · 재료 · 품번 · 패키지 · 핀 수 · 높이)와 `ecad.*` 이벤트 · 거르기 표 행 — 표 승인과 함께 정한다. 그때 EC-18 의
  diff 대상 deferred 를 걷는다.
- 넷 의존 영역(pwr · rf)을 스냅샷 대상에서 2단계까지 deferred 로 둘지 · 모델 크기 상한에 ECAD 부품 수를 셀지 — 결정 필요 그대로(EC-11 · EC-12).

### EC-25. 블랙박스 가정 도우미를 구현에 맞췄다
- A1(보드를 붙이는 칸) — 요청서는 '칸을 둔다' 만 정했다. 구현은 같은 소스 카드를 PUT …/ecad-board {odb_job_id} 로만 적는다(EC-1). `_ecad_ref` ·
  `_attach` 만 바꿨다 — job_id 없는 이름뿐인 카드는 일반 연결로 시도해 422 를 받고(그 시험의 뜻 '이름으로 고르지 않는다' 그대로) 붙인 답의
  카드 probe 를 `probe` 로 옮긴다.
- A5 · A6(단위) — 요청서 부록 A 는 원천의 단위(thickness_um, µm · total_thickness_mm × 1000)를 적었다. rr_ir 의 길이 단위는 mm(units.length)라
  층 두께 · ecad_stackup_total 을 mm 로 싣는다(µm 를 mm 봉투에 실으면 단위가 거짓이 된다). 도우미가 µm 로 되돌려 견준다 — 층 두께 단언 한 줄은
  도우미를 거치게만 바꿨다.
- A3 · A4(board 노드 · 칸 이름)는 구현을 고쳤다(EC-14) — 요청서가 정한 것이다.

### EC-26. 시험 · 변이 · 전체 시험(이 고침)
- 블랙박스 23/23. `tests/test_ecad_adapter.py` 에 반대 검토 고침 시험 함수 19개(보드 노드 · 판 바꿔 붙이기 · 쌍 비교 셋 · diff 대상 deferred ·
  노드 가족 표지 · 흔들리는 쪽 · 쪽 상한 · 배치 수 둘 · 지도 캐시 · 찾기의 지도 · 보드만 과제 409 · 정확한 job_id · 빈 job_id · 큰 보드 쌍 비교 ·
  열쇠와 겹치는 refdes · 부분으로 읽은 카드), `tests/test_project_patch.py` 에 카드 capture_mode 하나. 바꾼 시험 — 못 읽은 보드 시험을 호출 없는 셋(결측 + 경고)과
  호출한 둘(capture_failed)로 나눴고, 붙인 뒤 캡처의 노드 수에 board 1 · capture_mode mcp 를 더했다.
- 재현 — 반대 검토 실험 17건을 분리한 작업 트리에서 이 가지(c4d9148) 위에 돌려 같은 값을 본 뒤 고쳤고, 고친 뒤 다시 돌려 결함 단언이 깨지는 것을
  봤다(E1 reused 거짓 · E2 409 · E4 · E5 mcad 이벤트 그대로 · E7 표지와 경고 · E9 capture_partial · E10 21쪽 · E13 kinds 글 · E14 다음 캡처가
  곧바로 산다 · E15 0.22 초 · 3.3 MB · E18 표지). E6(자격) · E11(칸 비교) · E12(call_id)는 남긴 것 그대로다.
- 변이(분리한 작업 트리, 바이트코드 끔) 30개 — 첫 판 29개가 잡혔다. 산 하나는 ECAD 밖 카드의 capture_mode 를 rest_primary 로 되돌린 것이라
  `test_the_card_capture_mode_follows_the_channel_that_read_it` 을 더해 잡았다. 작업 트리는 지웠다.
- 전체 시험(고친 뒤 마지막 판) — 3,474 통과 · xfail 4 · 실패 0(rc 0, 11분 52초). ruff — 바꾼 파일은 깨끗하다.

## ECAD 1단계 — 사용자 결정 10-31 셋(가지 `wt1031/ecad`, 76fe9a8 위, 2026-10-31)

> 포털 세션에서 사용자가 답한 셋이다 — EC-15(자격) · EC-11 · EC-24(넷 의존 영역) · EC-12 · EC-24(모델 크기 상한)가 남긴 결정 필요를
> 닫는다. 앞 항목은 그때의 기록이라 고치지 않고 여기서 닫는다.

### EC-27. ECAD 는 그 사람의 PAT 로만 — 박스 읽기 PAT 로 내려가지 않는다(사용자 결정 10-31, EC-15 닫음)
- 결정은 안 (a)다. 찾기 · 붙이기 확인 · 캡처는 그 사람의 등록된 포털 PAT 하나로 부른다. 쓸 PAT 가 없으면(없음 · 폐기 · 풀리지 않음 ·
  남은 수명이 CREDENTIAL_MARGIN_S 이하) 찾기 · 붙이기는 409 `ecad_pat_absent`(detail `{app_key, fix: 'portal_pat'}`)이고, 캡처는 결측 +
  WARNING 경고 `ecad_pat_absent` 다(EC-16 의 호출 없는 실패와 같은 꼴). 종전 409 `ecad_credential_absent`(PAT 가 둘 다 없을 때만)는 없앴다.
- 찾기 · 붙이기(`routes._ecad_mcp_channel`)는 PAT 를 먼저 보고 게이트웨이에 아무것도 보내기 전에 거절한다(도구 지도도 받지 않는다).
  캡처는 채널 하나를 kind 들이 나눠 쓰므로 `Principal.mcp_credential`(user · service · None — create_snapshot 이 그 사람의 PAT 로 정한다,
  답의 `credentials.mcp` 와 같은 값)을 어댑터가 보고 user 가 아니면 부르지 않는다. mcad · dyna 의 MCP 폴백은 그대로 박스 PAT 다.
- 보드만 읽는 캡처(ECAD 말고 읽을 카드가 없다)는 `clients_from_settings(box_pat_fallback=False)` 로 채널을 아예 만들지 않는다 — 그때
  박스 PAT 로 `/tools-map` 을 받으러 가는 요청은 ECAD 때문에만 나가는 것이라 함께 막았다. 결과는 EC-22 의 409 `source_unreachable`
  (reason `ecad_pat_absent`)이고 잡 · 카드에 까닭이 남는다.
- 길잡이(risk_next_step)는 보드가 붙은 과제에 본인 PAT 가 없으면 notes 에 그 사실과 고칠 곳(`fix_register_pat`)을 싣는다 — dyna 의 같은
  줄 옆이다. 설정 화면의 선택 키 설명(`HWAXRISK_PORTAL_PAT`)도 ECAD 를 뺐다. MCP 도구 설명 둘(찾기 · 붙이기)은 그 사람의 PAT 로만 부른다고 말한다.
- 시험 — 새 `tests/test_ecad_person_pat.py`(게이트웨이 대역이 요청마다 Authorization 을 적는다). 찾기 · 붙이기 × REST · MCP × PAT 없음 · 곧
  끝남 · 폐기 · 풀리지 않음 16건이 요청 0 · 카드 없음이고, PAT 가 있으면 도구 지도 · 세션 · odb-hub 호출이 전부 그 PAT 다(박스 PAT 0).
  보드만 붙은 과제의 캡처는 요청 0 · 409 · 잡 · 카드 까닭, mcad 와 함께면 박스 PAT 는 StepForge 도구에만 나가고 보드는 경고 하나, 어댑터
  문(user · service · 모름), 폴백 끔의 채널 없음, 길잡이 notes 를 본다. 블랙박스의 가정 A7(박스 PAT 만 두던 것)은 그 사람의 PAT 를
  등록하는 쪽으로 고쳤고 단언은 그대로다 — 박스 PAT 자리도 채워 두어 쓰이지 않는지는 새 시험이 본다. `test_ecad_adapter.py` 는 어댑터를
  곧바로 부르는 두 곳에 mcp_credential='user' 를, web_box 에 그 사람의 PAT 행을 더했다.

### EC-28. 넷 · 배치 의존 영역(pwr · rf)은 2단계까지 deferred — 단계 스위치는 한 곳(사용자 결정 10-31, EC-11 · EC-24 닫음)
- 결정 — 1단계 보드 캡처 뒤 스냅샷 대상에서 pcb · soc · passive · mem 은 편성되고 pwr · rf 는 2단계(넷 · 좌표 — ODB 허브 OH-01 ~ OH-04 뒤)까지
  deferred 다. 꼴은 ECAD 가 없을 때와 같다 — 대표 1석(rank 1)만 앉고 나머지는 deferred 이며, reason 과 검토 순서의 input_gaps 는
  `ecad_nets_deferred` 다(ER-04 표지와 같은 낱말 — '넷 · component→net 엣지가 없다(2단계)'). 보드가 없는 대상은 종전대로 여섯 다 `ecad_absent` 다.
  `ecad_absent` 로 적지 않은 까닭 — 보드가 실렸는데 진행판 reason 칸에 'ECAD 없음' 이 서면 거짓이다(화면은 그 칸을 그대로 보인다).
- 스위치 — `adapters/ecad.py` 의 `STAGE = 1` · `NET_DOMAINS = ("pwr", "rf")` · `stage_gap(domain)` 이 한 곳이고, `planner.ecad_input_gaps`
  (영역 → 사유)가 그것을 읽는다. 편성(`freeze_roster(ecad_gaps=…)` — 라우트 `create_target` · 늦은 첫 고정 `refresh_roster` 가 `_ecad_gaps` 로
  준다)과 `review_order` 의 input_gaps 가 같은 함수다. 2단계가 넷 · 좌표를 실으면 STAGE 를 2 로 올린다. 어댑터 모듈에 둔 까닭 — 단계는 어댑터가
  무엇을 싣는가이고 ADAPTER_VERSION 과 함께 올라간다.
- `freeze_roster` 의 `ecad_absent` 인자는 그대로 두었다 — 주지 않으면(시험의 일반 로스터) 종전처럼 결손이 없다. 기본값을 '보드가 실렸다' 로
  읽게 바꾸면 ECAD 와 무관한 편성 시험(plan §6.4.1 의 15 · 114 · 359)의 pwr · rf 가 보류로 바뀐다. 실제 대상은 라우트가 늘 `ecad_gaps` 를 준다.
- 닿지 않는 길 — 카드 대조(cells)는 diff 대상에서만 열린다(현황 대상은 `units.compute` 가 snap_not_supported). diff 대상은 1단계 동안 ECAD
  의존 영역 전부가 `ecad_absent` 라(EC-18) 새 사유가 입력 결손 호출의 결측 글(`units.gap_missing` 은 ecad_absent 에만 실마리) · 검토 잡의
  보류 풀기(`undefer(reasons=('ecad_absent',))`) · 마감 사유(`review_rollup` 의 input_gap:ecad_absent)에 닿지 않는다. 그래서 그 셋은 고치지
  않았다 — EC-18 을 걷거나 현황 대상에 카드 대조를 열 때 함께 본다(noinput 은 unit.missing 이 비면 엔진이 거절한다 — 넷 결손 영역에는 결측 글이 있어야 한다).
- 2단계에서 볼 것 — STAGE 를 올리면 이미 1단계로 동결된 스냅샷 위에 새로 여는 대상에서도 pwr · rf 가 풀린다(그 스냅샷에는 넷이 없다). 막으려면
  판정을 그 스냅샷의 표지(`ecad_nets_deferred`)로 좁힌다. 지금은 1단계뿐이라 둘이 같다.
- 손대지 않은 것 — `planner.refresh_roster` 의 덧붙이기(새로 생긴 전문가는 결손과 상관없이 pending)는 ECAD 가 없는 대상에서도 종전부터 그랬다.
- 시험 — `test_ecad_adapter.py` 셋(1단계 보드 대상의 보류 둘 · 응답 deferred 2 · tier_plan · input_gaps 넷 · 보드 없는 대상의 ecad_absent 여섯,
  늦은 첫 고정, 스위치 2 에서 풀림). `test_planner.py` 의 '보드가 실리면 입력 결손이 없다' 시험은 결정대로 'pwr · rf 만 남는다 · 스위치 2 면
  없다' 로 고쳤다.

### EC-29. 모델 크기 상한은 ECAD 부품도 센다(사용자 결정 10-31, EC-12 · EC-24 닫음)
- 결정 — `risk_max_leaf`(1,500)의 리프는 MCAD 리프 + ECAD 부품 노드다(plan §2.11.3 이 적은 그대로). 층 · board 노드는 세지 않는다. 넘으면 종전
  길 그대로 409 `model_too_large` 이고 `allow_large=true` 로만 동결한다.
- 센 것 — `routes._check_model_size` 가 MCAD 는 종전처럼 소스 stats 의 `leaf_instances`(mcad 만 싣는다)를, ECAD 는 그 결과의 kind `component`
  노드 수를 더한다. 정본이 적은 `odb_get_board.n_components`(= stats.n_components, list_parts total)가 아니라 노드 수인 까닭 — 결정이 'ECAD
  component nodes' 이고, 상한이 지키려는 것은 실제로 실려 쌍 비교 · 검토 단위가 다루는 수다(2,000 상한 · 겹친 refdes · 열쇠와 겹치는 refdes 를
  뺀 뒤). 못 읽은 보드(결측 행)는 노드가 없어 0 이다. dyna 는 종전대로 세지 않는다(그 stats 에 leaf_instances 가 없다 — 바꾸지 않았다).
- 알림 — 409 의 글이 `리프 N/상한(MCAD 리프 m · ECAD 부품 e)` 로, detail 이 `leaf`(합) · `leaf_mcad` · `leaf_ecad` 로 나눠 말한다. 잡 오류
  (error_json.message)도 같은 글이라 길잡이(risk_next_step)의 capture_failed 막힘에 그대로 실린다. MCP 인자 설명(allow_large)도 고쳤다.
- 뒤탈 — 분류된 부품이 1,500 개를 넘는 보드는 보드만 붙여도 allow_large 가 든다(부록 A 의 두 표본 보드는 748 · 528 이라 들지 않는다).
- 시험 — `test_ecad_adapter.py` 셋: 보드만(부품 748 · 층 23 · board 1)으로 상한 748 통과 · 747 은 409(0 · 748) · allow_large 통과, mcad 리프 2 +
  부품 748 로 750 통과 · 749 는 409(2 · 748) · 못 읽은 보드는 0, REST 캡처의 409 · 잡 failed(stage model_size, 글에 몫) · allow_large 로 748 이 실린다.

### EC-30. 시험 · 변이 · 전체 시험(사용자 결정 셋)
- 새 시험 — `tests/test_ecad_person_pat.py` 24건(EC-27) · `tests/test_ecad_adapter.py` 6건(EC-28 셋 · EC-29 셋). 바꾼 시험 — `test_planner.py`
  하나(EC-28 결정대로), `test_ecad_adapter.py` 의 어댑터 직접 호출 둘 · web_box(EC-27), 블랙박스 가정 A7(EC-27 — 단언은 그대로).
- 변이(스크래치 사본, 바이트코드 끔) 23개 — 첫 판 22개가 잡혔다. 산 하나는 '보드만 읽는 캡처도 박스 PAT 채널을 만든다'(box_fallback 늘
  참)였다 — 붙일 때 받은 도구 지도가 60 s 캐시에 남아 박스 PAT 로 지도를 받으러 가는 요청이 보이지 않았다. 캡처 앞에서 캐시를 비우게(붙인 뒤
  한참 뒤의 캡처) 시험을 고쳐 잡았다(5c8d4be). 고친 뒤 23/23. 찾기 채널의 `box_pat_fallback=False` 는 PAT 를 먼저 보고 409 를 내는 줄
  뒤라 하는 일이 없어 걷었다(05b64f3) — 변이 목록에서 살아남을 줄을 남기지 않는다.
- 전체 시험(공유 잠금 아래, HEAD) — 3,504 통과 · xfail 4 · 실패 0(rc 0, 11분 16초 — 앞 판 3,474 에 새 시험 30). ruff — 바꾼 파일은 깨끗하다.
- 하지 않은 것 — 배선 리허설(`tests/synth/rehearsal_d.py`)은 프로세스를 띄우는 일이라 돌리지 않았다. 카드 대조 사슬의 바뀐 곳은 없다(EC-28 —
  새 사유가 그 길에 닿지 않는다). 서비스 재기동 · push · 병합은 없다.

## 10-31 백로그 — B22 · B28 · B30 · B31 · A18(가지 `wt1031/bl-risk-api`, main 9bd5f48 위, 2026-10-31)

> 포털 `docs/leftovers-1017/triage-1031.md` 의 다섯 줄(사용자 결정 10-31 — 표 A 의 추천을 받아들이고 표 B 의 dev 작업을 한다)이다.
> 원천 줄은 포털 `docs/design-risk-review/checklist.md` 104 ② · 134 · 136 · 143 ① ② 와 `docs/procedures/checklist.md` 622 다.

### BL-1. 같은 원천의 다른 과제는 알리되 구성원 과제만 싣는다(B22)
- `POST /projects/{id}/sources` 가 같은 `ref_key` 의 다른 과제를 `duplicate_of[{project_id, code, owner_sub, created_at}]` 로 알린다 — 등록은
  막지 않는다(plan §8.2.3 — 같은 CAD 를 두 관점으로 심사하는 것이 정당할 수 있다). `created_at` 은 그 과제에 그 원천이 붙은 시각이다.
  알림이 없으면 칸을 싣지 않는다(종전 응답 그대로).
- 정본과 다른 곳 — 싣는 것은 부른 사람이 구성원(소유 · 멤버)인 과제뿐이다. 정본은 다른 과제를 가리지 않고 싣는데 그대로 하면 남의 과제
  id · 코드 · 소유자 메일을 흘린다 — D45 '구성원은 하나'(남의 과제는 목록에도 수로도 드러내지 않는다)를 따랐다. 남끼리 같은 CAD 를 붙인
  것은 알리지 못한다 — 알리려면 조직 공개 선택지를 따로 만든다(D45 와 같은 답). 포털 plan §8.2.3 의 그 칸 글은 포털 세션 몫이다.
- `ref_key` 는 `kind:app_key:ref` 라 app_key 를 비워 붙인 소스(`-`)와 채워 붙인 소스는 같은 원천이어도 다른 열쇠다. 웹 · MCP 둘 다 app_key 를
  채우므로(웹은 폼 필수, MCP 는 발견값 · 기본값) 실제로는 갈리지 않는다 — 열쇠 규칙은 정본대로 두었다.
- MCP `risk_add_source` 는 같은 라우트를 감싸 같은 칸을 싣는다(도구 설명에 한 구절). 시험 `tests/test_source_duplicates.py` 넷.

### BL-2. 대상 감사는 행위의 자리로 가린다 — 과제 감사와 같은 칸, 남에게는 404(B30)
- `GET /targets/{key}/audit` — 감사 표에는 대상 열이 없다(DDL 을 바꾸지 않는다). `registry.target_audit_clause` 하나가 그 대상의 행을
  고른다 — 대상 그 자체(scope target) · '<대상>#' 자리(좌석 `<대상>#<전문가>` · 등록부 `<대상>#<클러스터>` · 사람 finding `<대상>#H<n>` —
  지운 사람 finding 도) · 대상 열쇠 그대로인 좌석 처분(보류 풀기 · 셀 처분) · 그 대상의 잡 · 패널 · finding · 등록부 클러스터(맨 cluster_key 를
  쓰는 별칭 철회 · 공개 토글 · 큐 결정) · 그 대상이 가리키는 스냅샷(게이트 ack — diff 대상은 앞 · 뒤 스냅샷)이다. 과제 단위 행(멤버 · 수명주기 ·
  요구 · 어휘)은 과제 감사의 몫이라 뺐다. 접두는 '#' 까지 본다(`diff:d1` 이 `diff:d10#…` 를 집지 않게, LIKE 대신 substr).
- 통합 보고서의 '사람 개입 요약'(BL-4)도 같은 조각을 센다(`target_audit_counts`) — 조회와 보고서의 수가 갈리지 않는다.
- 칸 · 거름은 과제 감사(`GET /projects/{id}/audit`)와 같다 — `{target_key, total, limit, offset, entries[{id, actor, actor_verified, channel,
  scope, subject_id, project_id, action, before, after, reason, at}]}`, `action · since · until · offset`, 최근 것 먼저. limit 은 1~200 으로 죈다
  (트리아지 줄 '≤200' — 과제 감사는 500). 정본 §8.2.3 의 `rows · next_since` 꼴은 앱의 과제 감사가 이미 쓰지 않는 꼴이라 따르지 않았다 —
  화면(B34 '이력 탭')이 두 감사를 한 그림으로 그리게 같은 칸을 냈다.
- 권한은 viewer 이상(과제 감사와 같다) · 관리자 우회. 트리아지 받아들임은 '비멤버 403' 인데 남에게는 없는 대상과 같은 404 다 — 앱의 남 숨김
  규칙(D43 `_member_or_missing`, 시험 `tests/rr/test_review1_stranger.py` 가 모든 읽기 경로에서 404 · 없는 id 와 같은 답을 요구한다)을 따랐다.
  viewer 가 바닥이라 구성원의 403 은 생기지 않는다. 남 시험 표에 칸을 더했다.
- finding 하위 조회는 카드 대조 finding 을 거르지 않는다 — 카드 대조 finding 의 큐 결정도 그 대상의 사람 행위다. 거름 래칫
  (`tests/test_review_findings.py` REVIEW_READERS)에 까닭과 함께 한 자리를 더했다.

### BL-3. 잡 브리프 제외는 항목 단위만 · 필수 셋과 메모는 못 뺀다(B31 ①)
- `JobBody.exclude_evidence` — 종전에는 본문 모델에 칸이 없어 pydantic 이 조용히 버렸다. `brief.check_exclude` 가 뺄 수 있는 항목
  `brief.EXCLUDABLE_ITEMS`(E2~E9)만 받고 겹침 없이 항목 차례로 남긴다. 밖이면 422 `exclude_evidence_invalid{invalid, allowed}` 다.
- 필수 셋(E0 스코프 · E0c 좌석 계약 · E1 요약 — plan §5.6.2 '필수')과 잡 메모(M — 그 잡을 만드는 사람이 쓴다, 빼도 폴백이 다시 붙인다)는
  뺄 수 없다. 참조(ref) 단위 빼기는 받지 않는다 — 정본 §8.2.3 은 'E키 또는 ref' 라 적지만 §5.7 RecallPreview 는 '항목 제외만 · 추가 · 편집
  불가' 라 적는다. 항목 안의 줄을 고치면 항목 편집이고, E2 는 꼬리 줄이 전체 · 실림 · 생략 수를 말해 줄을 빼면 그 수가 거짓이 된다. ref 를
  주면 422 로 까닭을 말한다(조용히 버리지 않는다). 정본 두 절의 어긋남은 포털 세션에 넘긴다.
- 흐름 — `runner.create_job(exclude_evidence=)` 가 비지 않은 값을 params_json 과 응답에 남긴다(빼지 않은 잡의 params · 응답은 종전 그대로).
  러너가 패널마다 `build_delib_opts(exclude=)` → `prior_evidence(exclude=)` 로 그 항목을 싣지 않고 `rr_panels.evidence_excluded_json` 에 적는다
  (동결 브리프 brief_gz 도 뺀 꼴이다). 라우트가 `rr_audit(scope job, action brief.exclude, after{target_key, tier, exclude_evidence})` 한 행을
  쓴다 — 잡마다 한 행(정본 §8.2.3 '1행'). 검토 잡(mode reviews)에 주면 422(본문 검증 — 패널 칸)이고, 쟁점 잡 · C3 자동 후속 잡은 사람이 만든
  잡이 아니라 칸이 없다(후속 잡은 앞 잡의 제외를 물려받지 않는다 — '그 잡의 패널 브리프').
- MCP `risk_start_job` 에 같은 인자를 뒤에 더했다(도구 수 33 그대로 · 인자 계약 고정본과 도구 칸 시험을 고쳤다). 살아 있는 같은 Tier 잡을
  돌려주기 전에 값을 보고(틀린 값이 살아 있는 잡을 받아 '받아들여졌다' 고 읽히지 않게), 그 잡의 제외와 다르면 `differs` 에
  exclude_evidence 를 싣는다(바꾸지 않는다 — 판단 LLM 과 같은 규칙).

### BL-4. 통합 보고서 minutes 의 '사람 개입 요약'(B31 ② · P4 (13))
- `registry._minutes_lines` 끝에 `[사람 개입 요약]` — 그 대상 rr_audit 를 action 별로 센 `<action>=<n>` 줄(action 순), 없으면 `(없음)`.
  BL-2 의 조각을 그대로 쓴다. 커버리지 칸에는 사람이 넘긴 skipped 에 `(decided_by: …)` 를 병기한다(코드가 넘긴 것은 아니다, plan §4.7.3).
- 옛 타깃 골든의 minutes 행 수가 늘었다(12→14 · 10→12 · 10→13) — `tests/fixtures/legacy/CHANGES.md` 에 칸과 까닭을 적었다. 품질 플래그
  절을 읽는 시험은 새 절 앞에서 끊는다.
- 남긴 것(보고) — 요약은 rr_audit 를 센 수라 감사 행을 남기지 않는 사람 조작은 여기에도 없다. 정본 §8.2.3 은 셋을 감사하라 하는데 지금
  코드는 쓰지 않는다 — 잡 제어(`POST /jobs/{id}/pause|resume|cancel` → `job.pause|resume|cancel`, 주체는 rr_jobs.state_by 에만), 등록부 상태
  (`PUT /registry/{cluster}/status` → `registry.status`, rr_registry_status_log 에만), verdict 확정(`PUT /targets/{key}/verdict` → `verdict.final`).
  그래서 정본 요약의 '잡 제어 n · status 변경 n' 줄은 지금 늘 없다. 이번 다섯 줄 밖이라 고치지 않았다.

### BL-5. MCP 길 원자의 회수 복귀는 suspect_text 큐의 approve_recall(B28)
- MCP 길(`actor_verified=false`) 패널이 원자(finding · 성격 진술)를 recall_eligible=0 으로 앉힐 때(`risk_recall_require_verified_actor` 켬) 그
  패널마다 큐 한 항목을 세운다. kind 는 DDL 어휘 안의 `suspect_text` 다 — 새 kind(recall_review)는 CHECK 를 바꾸는 이행이라 하지 않았고, 정본도
  격리된 원자의 큐를 suspect_text 로 적는다(plan §5.2.3). `payload.reason='actor_unverified'` 가 의심 문구 항목과 가르고 target_key · panel_id ·
  actor(신고값) · findings_n · characters_n 을 싣는다. 같은 결과를 다시 내도 열린 항목은 하나다(수만 고친다).
- 결정 어휘 — suspect_text 에 `approve_recall`(회수만, 원문 복원 없음 — 정본 §3.4.1 의 그 이름)을 더했다. 미검증 신원 항목은 되살릴 원문이
  없어 approve_recall · reject 뿐이고 approve 는 422 `decision_not_allowed_for_kind` 다. approve_recall 은 미검증 신원 항목이면 그 패널의
  finding · 성격 진술을, 의심 문구 항목이면 그 claim 의 finding 을 되돌린다. 카드 대조 finding 은 어느 결정으로도 올리지 않는다(M2.md 5절 #9).
- 감사 — 회수 복귀는 `rr_audit(action='recall.approve')` 한 행(정본 §6.11 · P3 (21) — curation.decide 와 겹쳐 쓰지 않는다), 미검증 신원
  항목의 자리는 scope panel · 그 패널 id 다. 그 밖의 결정은 종전대로 curation.decide.
- 화면 — 결정 어휘 사본(`frontend/src/pages/CurationQueuePage.tsx` KINDS, 서버와 같은 집합을 `test_p6_routes` 가 본다)에 한 줄을 더했다.
  미검증 신원 항목의 요약 칸(지금 raw · sha1 을 보여 빈칸이 된다)과 설명 글은 화면 세션 몫이다.

### BL-6. 사람 finding 의 mechanism · domain 은 택소노미 어휘다(A18)
- `POST /targets/{key}/findings`(MCP risk_add_finding 도 같은 함수)가 쓰기 전에 대조한다 — 밖이면 422 `taxonomy_invalid`, detail 에 field ·
  value · allowed(mechanism 은 codes 도)다. 아무것도 쓰지 않는다. 오타가 등록부 묶음 열쇠(cluster_key)를 쪼개는 것을 막는다(트리아지 A18 (A)).
- mechanism 은 대분류(택소노미 mechanism 축의 mechanism 칸 — 아홉) · `unclassified`(기본) · 코드(`<대분류>.<세부>`)다. 코드는 패널 원자와
  같은 꼴(대분류 + 세부)로 나눠 적는다 — 웹 폼(HumanFindingForm)이 코드를 mechanism 에 실어 보내 종전에는 같은 메커니즘이 MCP · 패널 원자와
  다른 묶음 열쇠로 갈렸다. 코드의 세부와 다른 mechanism_detail 을 같이 주면 422 다. 대분류 꼴의 세부는 종전대로 받는다(A18 의 범위는 mechanism ·
  domain 이고, 세부가 자유인 시험 원장도 있다 — 세부 대조는 다음 결정이다).
- domain 은 택소노미 domain 코드(열다섯)이거나 비운다. `PUT /findings/{id}` 는 mechanism · domain 을 바꾸지 않아 검사하지 않는다.
- MCP 인자 설명(mechanism · mechanism_detail · domain)이 허용값을 코드에서 읽고 '검사하지 않는다' 를 걷었다 — 설명 시험(VOCAB)에 두 칸.

### BL-7. 시험 · 변이 · 전체 시험
- 새 시험 다섯 파일 28건 — `test_source_duplicates`(4) · `test_target_audit`(3) · `test_human_taxonomy`(5) · `test_recall_approve`(4) ·
  `test_brief_exclude`(12). 옛 코드(9bd5f48)의 스크래치 사본에 새 시험만 얹어 돌리면 24건이 지고 4건이 지난다 — 지나는 넷은 일부러 둔 회귀
  가드다(남의 과제가 안 실림 · 격리를 끄면 항목 없음 · 종전 값이 그대로 지남 · 빼지 않은 잡의 칸이 빔).
- 고친 옛 시험 — 남 시험 표(대상 감사 칸) · 거름 래칫(한 자리) · MCP 인자 설명(VOCAB 셋) · 인자 계약 고정본 · 도구 칸(risk_start_job) ·
  품질 플래그 절(새 절 앞에서 끊음) · 옛 타깃 골든 셋(minutes 행 수).
- 변이(새 코드의 스크래치 사본, 바꾼 뒤 __pycache__ 를 지운다) 32개가 전부 잡혔다 — B22 셋 · B30 아홉 · A18 넷 · B28 여섯 · B31 열.
  사본은 HEAD 와 바이트 같게 되돌렸다(diff 0).
- 전체 시험(공유 잠금 아래, 0cf4787 — 이 줄을 더한 커밋과 코드가 같다) — 3,536 통과 · xfail 4 · 실패 0(rc 0, 12분 33초). 앞 판 3,504 에
  새 시험 28 과 늘어난 매개 칸 넷(인자 설명 VOCAB 셋 · 남 시험 표 하나)이다. ruff — 바꾼 파일은 깨끗하다(종전부터 있던
  `tests/test_backup_wrapper_run.py` 의 F401 하나는 그대로 두었다).
- 하지 않은 것 — 배선 리허설(`tests/synth/rehearsal_d.py`)은 프로세스를 띄우는 일이라 돌리지 않았다(카드 대조 사슬은 바꾸지 않았다).
  화면 빌드(tsc)는 이 작업 트리에 node_modules 가 없어 돌리지 않았다 — 바꾼 것은 결정 어휘 사본 한 줄이고 옆 줄과 같은 꼴이다. 서비스
  재기동 · push · 병합은 없다. 가지 wt1031/rk01 과 겹치는 것은 context-notes 끝의 덧붙임 하나뿐이다(merge-tree — 코드 파일은 깨끗이 합쳐진다).

## 10-31 백로그 — 반대 검토 뒤 고침(가지 `wt1031/bl-risk-api`, 66fc6da 위, 2026-10-31)

> 반대 검토 지적 여섯(높음 1 · 중간 2 · 낮음 3)을 옛 코드(66fc6da)의 스크래치 사본에서 시험으로 먼저 재현했다 — 여섯 다 재현됐다. 고친 뒤
> 같은 시험이 지난다. 지적마다 아래 한 절이고 BL-2 · BL-3 의 일부를 뒤집는다.

### BL-8. 대상 감사의 맨 클러스터 열쇠 행은 그 대상 소유자의 행위만이다(BL-2 일부 뒤집음 · 반대 검토 높음)
- 재현 — 남의 과제 대상과 내 대상에 웹 폼 꼴(코드 · 대상 없음)의 사람 finding 을 하나씩 내면 묶음 열쇠가 같다(cluster_key 에 대상이
  없다). 남이 자기 행의 공개 토글과 cluster_merge 큐 기각(사유 글)을 하면 내 대상 감사(그 과제의 viewer 누구나)와 통합 보고서 minutes 의
  '사람 개입 요약' 에 남의 행(행위자 메일 · 사유)이 실렸다. 거꾸로도 같다. 같은 CAD 를 두 과제에 붙인 패널 finding(같은 부품 ckey)도 같다.
- 까닭 — rr_registry 의 열쇠는 (target_key, cluster_key)라 한 열쇠가 여러 대상 · 소유자에 산다. 공개 토글 · 별칭 철회 · 큐 결정
  (cluster_merge · pattern_candidate)은 감사 자리에 맨 클러스터 열쇠만 적고(project_id NULL), BL-2 의 조각에는 소유자 조건이 없었다.
  시험의 '남' 행은 겹치지 않는 열쇠(`c0ffeec0ffee`)라 이것을 보지 못했다.
- 고침 — 맨 열쇠 갈래에 `rr_audit.owner_sub = 그 대상의 owner_sub` 를 더했다. 그 길들은 부른 사람 자신의 등록부 행 · 별칭만 바꾸므로(남의
  행은 404) 소유자 단위 행위(대상을 고르지 않은 토글 · 별칭 철회 · 큐 결정)는 그 소유자의 같은 열쇠 대상마다 실린다. 대상을 골라 한 공개
  토글(`PUT /registry/{ck}/visibility {target_key}`)은 그 대상의 행만 바꾸므로 감사 자리를 '<대상>#<클러스터>'(병합과 같은 꼴)로 적는다 —
  맨 열쇠로 적으면 같은 열쇠를 가진 내 다른 대상(다른 과제일 수 있다 — 그 과제의 viewer 가 본다)에도 실렸다.
- 남긴 것 — (1) 이양 뒤에는 대상 소유자가 바뀌어 옛 소유자의 맨 열쇠 행(소유자 단위 행위)이 그 대상 감사에서 빠진다. 별칭도 소유자마다라
  옛 소유자의 별칭은 이양 뒤 그 대상의 병합에 듣지 않는다 — 지금 그 대상에 듣는 행위만 남는 셈이다. 대상을 고른 행은 자리가 대상이라
  남는다. (2) 이 고침 전에 대상을 골라 한 공개 토글의 감사 행은 맨 열쇠라 그 소유자의 같은 열쇠 대상마다 실린다(화면 · MCP 는 이 경로를
  부르지 않아 운영 행은 드물다). (3) `PUT /registry/{ck}/merge` 의 감사 자리는 그 소유자의 아무 대상 하나(LIMIT 1)다 — 별칭은 소유자
  단위인데 한 대상에만 실린다(종전부터, 이번 지적 밖이라 두었다).

### BL-9. 회수 격리의 두 까닭 — 한 항목의 승인은 제 격리만 푼다(BL-5 보탬 · 반대 검토 중간)
- 재현 — MCP 길 패널이 깨끗한 F1 과 인젝션 문구의 F2 를 내면 둘 다 recall_eligible=0 이고 큐 항목이 둘(F2 의 의심 문구 · 그 패널의 미검증
  신원)이다. 의심 문구를 기각(격리 유지)한 뒤 신원 항목을 approve_recall 하면 패널 단위 UPDATE 가 F2 도 1 로 되돌렸다(finding_json.claim 에
  인젝션 원문). 거꾸로 신원 항목이 열린 채 의심 문구를 approve_recall 하면 F2 가 1 이 되고 뒤의 신원 기각은 0 으로 되돌리지 않았다.
- 고침 — 승인은 후보 finding 마다 남은 격리를 큐에서 다시 읽는다(`routes._suspect_hold` · `_actor_hold`, 지금 승인하는 항목은 승인된 것으로
  본다). 의심 문구 격리는 그 claim 의 가장 최근 항목(지금 본문의 글 sha1 을 가리키는 것)이 열렸거나 기각됐으면, 또는 본문이 지금 인젝션
  어휘에 걸리는데 그 글을 승인한 항목이 없으면 남는다. 미검증 신원 격리는 그 패널의 가장 최근 신원 항목이 열렸거나 기각됐으면 남는다.
  남은 finding 은 되돌리지 않고 `applied.held[{claim_uid, reason}]` 로 말한다 — 그 격리의 항목을 승인할 때 돌아간다. 기각은 종전대로
  아무것도 쓰지 않는다(승인이 미리 풀지 않으므로 되돌릴 것이 없다). 성격 진술에는 의심 문구 격리가 없어 신원 승인이 종전대로 되돌린다.
- 큐 항목만 보지 않고 본문을 다시 대는 까닭 — 같은 sha1 의 항목이 이미 열려 있으면 의심 문구 항목이 다시 서지 않아(narrative persist 의
  중복 막기) 제 항목이 없는 인젝션 원자가 있다. 항목만 보면 신원 승인이 그것을 되돌린다(시험). '가장 최근' — 기각 뒤 재제출로 다시 선
  항목이 그 자리의 결정이고, 재제출로 글이 바뀐 옛 항목은 지금 finding 을 묶지 않는다.
- 남긴 것 — 같은 글을 승인받은 다른 원자(같은 sha1 · 제 항목 없음)는 격리로 남는다(B28 전에도 그 원자는 0 에 머물렀다). 인젝션 어휘판
  (INJECTION_VERSION)이 바뀌어 새로 걸리는 원자도 항목이 없어 격리로 남는다(안전한 쪽). 의심 문구 항목의 중복 막기는 소유자를 가리지 않고
  sha1 만 본다(종전부터) — 남의 열린 항목 때문에 내 원자의 항목이 서지 않을 수 있다(이번 지적 밖). 패널을 MCP 길로 낸 뒤 웹 길로 다시
  내도 앞의 신원 항목(열림 · 기각)은 그대로라 그 패널의 의심 문구 원자는 그 항목을 승인할 때까지 격리로 남는다(안전한 쪽 — 깨끗한 원자는 웹
  재제출이 곧바로 1 로 앉힌다).

### BL-10. C3 자동 후속 Tier C 는 앞 잡의 브리프 제외를 물려받는다(BL-3 일부 뒤집음 · 반대 검토 중간)
- 재현 — 닫힘 레벨 C3 대상에서 E6 · E8 을 뺀 Tier B 잡이 끝나면 `_finish_job` 이 세우는 Tier C 가 메모 · 층(modifiers) · 요청자는 물려받고
  제외는 버렸다 — 후속 패널 브리프에 E6 · E8 이 실리고 evidence_excluded_json 이 NULL 인데 minutes 의 요약은 brief.exclude=1 이라 그 항목
  없이 돈 것처럼 읽혔다. BL-3 의 '후속 잡은 사람이 만든 잡이 아니라 물려받지 않는다' 는 같은 후속이 사람의 메모 · 층을 물려받는 것과 어긋난다.
- 고침 — 후속에 params.exclude_evidence 를 넘기고 `exclude_evidence_from=<앞 잡 id>` 를 params 에 남긴다(물려받은 것의 표지, 뺄 항목이 있을
  때만). 감사 행은 더 쓰지 않는다 — 감사는 사람 행위 한정이고 사람의 결정은 앞 잡의 brief.exclude 한 행이다(요약의 수도 1 그대로).

### BL-11. 같은 원천 알림에서 폐기 과제는 뺀다(BL-1 보탬 · 반대 검토 낮음)
- purge 는 status='purged' 묘비만 남기고 rr_sources · 멤버 행은 그대로라 `duplicate_of` 에 실렸다(코드 · 소유자 · 시각). 조회에
  `p.status = 'active'` 를 더했다 — 수명주기(lifecycle)가 닫힌 과제(shipped · cancelled · archived)는 원문이 있어 그대로 싣는다.

### BL-12. MCP risk_start_job 이 돌려주는 살아 있는 잡의 제외를 싣는다(BL-3 보탬 · 반대 검토 낮음)
- 살아 있는 잡을 돌려주는 갈래는 판단 LLM 은 `job_llm_view` 로 실었지만 제외는 싣지 않았다 — 빼지 않은 호출은 그 잡이 E7 을 뺀다는 것을
  몰랐고(보통 브리프로 읽는다), 다른 값을 준 호출은 differs 만 받고 무엇이 살아 있는지 몰랐다. params 의 exclude_evidence 가 비지 않았으면
  `exclude_evidence` 칸으로 싣는다(빼지 않는 잡은 칸 없음 — 종전 응답 그대로). 도구 설명에 한 구절을 더했다.

### BL-13. A18 전 코드 꼴 사람 finding 의 재열쇠(BL-6 보탬 · 반대 검토 낮음)
- 재현 — A18 전 웹 폼 꼴('thermal.cte_mismatch' · 세부 빈칸)로 적힌 행과 A18 뒤 같은 입력('thermal' · 'cte_mismatch')의 새 행이 한 대상에서
  다른 등록부 행(human_n 1 · 1)으로 갈린다. 옛 행은 처음부터 패널 원자와도 갈려 있었다(A18 이 고치려던 것). 옛 행을 옮기는 것이 없었다.
- 고침 — `backend/scripts/rekey_human_codes.py`(dry-run 기본 · `--apply`). finding 행의 cluster_key 는 고치지 않고(plan §4.3.2 1 삽입 시
  동결) 그 소유자의 별칭 한 행(옛 열쇠 → 대분류 + 세부 열쇠, reason taxonomy_major · evidence {from, to, by: code:human_code_rekey})을
  세운 뒤 그 열쇠의 사람 finding 이 있는 대상을 모두 다시 병합한다 — 같은 위험의 finding 이 한 행에 든다. 코드와 다른 세부를 같이 적은 행은
  skipped(detail_differs)로 알린다(코드가 고르지 않는다). 그 소유자의 별칭 행이 이미 있는 옛 열쇠(이 스크립트가 이은 것 · 사람이 다른 곳으로
  이었거나 철회한 것)는 건드리지 않는다. 패턴 통계는 야간 ③ 이 다시 센다(remap_findings.py 와 달리 바로 캐지 않는다).
- cae00 배치 한 번(사람 몫 — 체크리스트 열린 줄) — 앱 환경(HWAXRISK_DATA_DIR)에서 dry-run 으로 planned · skipped 를 본 뒤 `--apply`.
- 남긴 것(결정 필요) — 등록부 병합은 별칭으로 접힌 옛 (대상, 옛 열쇠) 행을 닫지 않는다. 정본 plan §4.3.2 3 은 `status='superseded'` ·
  `superseded_by='<대상>#<새 열쇠>'` 로 닫으라 하는데 지금 `registry.merge` 는 그 일을 하지 않아, 재열쇠 뒤에도 옛 행(정지된 집계 · open)이
  남아 등록부 목록과 판정 후보에 든다. 사람의 cluster_merge · `PUT /registry/{ck}/merge` · 택소노미 재매핑이 다 같다(종전부터 — 스크래치
  탐침: 별칭 뒤 재병합의 clusters=1 인데 rr_registry 에는 두 행). 사람이 정한 status 를 덮을지 · 별칭 철회 때 되살릴지가 걸려 이번 줄 밖으로 둔다.

### BL-14. 시험 · 변이 · 전체 시험(반대 검토 고침)
- 새 시험 12 · 고친 시험 1 — `test_target_audit`(1) · `test_recall_approve`(8 — 두 차례 넷 · 같은 글 재제출 · 옛 글 항목 · 가장 최근 신원
  항목 · 제 항목 없는 인젝션) · `test_brief_exclude`(후속 1 + MCP 시험에 살아 있는 잡의 제외 단언) · `test_source_duplicates`(1) ·
  `test_human_taxonomy`(재열쇠 1). 옛 코드(66fc6da)의 스크래치 사본에 얹으면 11 이 지고 2 가 지난다 — 지나는 둘(옛 글 항목 · 가장 최근
  신원 항목)은 새 격리 읽기의 회귀 가드다(옛 코드는 패널을 통째로 되돌려 지난다).
- 변이(새 코드의 스크래치 사본, 바꾼 뒤 __pycache__ 를 지운다) 18 개가 전부 잡혔다 — 감사 조각 둘 · 회수 격리 여덟 · 후속 제외 둘 · 폐기
  과제 · 살아 있는 잡 칸 · 재열쇠 넷. 사본은 작업 트리와 바이트 같게 되돌렸다(diff 0).
- 커밋을 다섯으로 나눴다(대상 감사 → 회수 격리 → 브리프 제외 → 소스 중복 → 재열쇠) — 스크래치 사본에서 판마다 다섯 시험 파일과 MCP 도구 ·
  인자 시험이 지난다(143 → 154).
- 전체 시험(공유 잠금 아래, 그 다섯 커밋과 코드가 같은 작업 트리) — 3,548 통과 · xfail 4 · 실패 0(rc 0, 12분 39초). 앞 판 3,536 에 새
  시험 12 다. ruff — 바꾼 파일은 깨끗하다. 재열쇠 스크립트의 dry-run 을 빈 데이터 디렉터리에서 돌렸다(planned 0 · rc 0).
- 하지 않은 것 — 배선 리허설 · 화면 빌드 · 서비스 재기동 · push · 병합은 없다. 가지 wt1031/rk01 의 파일(ra_client · nightly · main ·
  config)은 건드리지 않았다. 포털 문서(트리아지 원천 줄)는 고치지 않았다 — 포털 세션 몫이다.

## 캡처 · diff 백로그 넷(가지 `wt1031/bl-risk-capture`, main 9bd5f48 위, 2026-10-31)

> 포털 `docs/leftovers-1017/triage-1031.md` 의 B24 · B25 · B26 · B32 다(사용자 결정 10-31 — 표 2 의 추천을 다 받고 표 3 의 dev 일을 한다).
> 원줄은 포털 design-risk-review 체크리스트 108 · 125 · 126 과 risk-200k 체크리스트 7 이다. 포털 문서는 이 리포가 고치지 않는다(문서
> 워크플로가 이 절을 근거로 단다).

### BL-1. same-as 6단계 상한 — 남은 노드 곱이 800×800 을 넘으면 헝가리안을 건너뛴다(B24, 224c8fe)
- 정본 §2.6.3 문장 그대로다 — `len(rest_a) × len(rest_b) > 800 × 800` 이면 6단계의 점수 · 행렬을 만들지 않고 5단계까지의 대응으로 간다.
  곱이 정확히 640,000 이면 돈다. 남은 노드는 미대응이고 pending 을 만들지 않았으므로 G2 에 세지 않는다.
- 건너뛴 사실을 담는 길 — resolve 의 반환(레코드 목록)에 칸을 지어내지 않고 `fuzzy_skip(nodes_a, nodes_b, links)` 이 같은 규칙으로 레코드에서
  다시 읽는다. 규칙은 한 곳이다 — `_takes`(confirmed · auto 이고 score ≥ 0.90)와 `_fuzzy_rest`(가져가지 않은 비 ecad 노드)를 resolve 와 함께
  쓰고, 원장 행은 사다리 1단계처럼 confirmed 만 가져간다. 그래서 links 를 따로 받는 `create_diff`(원장으로 푼 대응)에서도 같은 답이다.
  resolve 에 출력 인자를 더하지 않은 까닭 — ir_builder 의 `sameas_resolve` 주입(시험 첩자)이 인자 여섯으로 고정돼 있다.
- 스냅샷(intra) — 건너뛴 도메인 쌍의 두 소스 degraded 에 `fuzzy_skipped_large`, 경고 한 줄(ref `dyna~mcad` · 남은 노드 수 · 상한),
  `sig:capture.fuzzy_skipped`(flag — 그 경고를 인용). 셋 다 ir_hash 입력이 아니다 — 같은 입력이면 같은 해시다(시험). 도메인 쌍은 그 도메인의
  노드 전부를 본다(mcad 쪽에 파일 · 조립 노드가 든다 — 리프 801 이면 801 × 803).
- 쌍(pair) — `correspondence.fuzzy_skipped{rest_base, rest_target, limit}` 와 의미층 `caveat='fuzzy_skipped_large'`, 그 이벤트마다 같은 caveat.
  짝 없는 부품의 사건에만이 아니라 층 전체에 단 까닭은 정본 문장('pair 의미층은 caveat 를 단다')이고, 검토 단위가 줄마다 `caveat=` 로 보인다.
  세대가 섞인 쌍의 `parser_differs`(등급을 낮춘다)가 먼저 붙은 이벤트는 그대로 두고 층 표지로만 남긴다.
- 실측(dev, 순수 파이썬 — 앱 venv 에 scipy 가 없다) — score_pair 한 번 약 40 µs, 동봉 헝가리안은 남은 노드 200 × 200(행렬 400) 0.52 s ·
  300 × 300(행렬 600) 1.81 s 로 세제곱이다. 800 × 800 이면 점수 64만 번(약 26 s)과 1,600 행렬(약 35 s)로 1분 남짓, 1,500 × 1,500 이면 5분을
  넘는다. 상한은 정본의 값이고 그 아래는 종전 그대로 돈다(799 × 799 · 800 × 800 시험).
- 시험 — `tests/test_sameas_fuzzy_cap.py` 15건. 점수 첩자가 801 × 801 에서 첫 호출에 실패시킨다(옛 코드는 64만 번 점수와 1,602 행렬로 매달린다).
- **반대 검토 뒤(BL-6)** — 곱 규칙만으로는 기운 모양(30 × 3,000 — 곱 9만인데 3,030 변 행렬)이 빠져 배정 행렬 변 1,600 상한을 더했다.
  위의 '상한은 정본의 값' 은 곱에 대한 말이다.

### BL-2. 계면 목록 절단 — 잘린 kind 의 변화는 truncated 로 뺀다(B25, 5a59ca9)
- 캡처 — counts 합이 받은 행보다 크면(종전 판정 그대로) kind 마다 counts − 받은 행 수를 `stats.interfaces_truncated{kind: n}` 에 남긴다(n > 0 인
  kind 만, 안 잘렸으면 `{}`). counts 는 REST counts → graph.json counts → interface_graph counts 의 종전 차례다. MCP 폴백은 kind 마다 부른 행을
  그 kind 로 센다. 합이 받은 행보다 크면 적어도 한 kind 의 수가 양수다.
- 쌍 비교 — 두 스냅샷의 잘린 kind 합집합 K 로 (1) 엣지 변경(kind_from · kind_to 가 K 에 — added · removed · kind_changed · status_changed 모두),
  (2) 엣지 파라메트릭(그 엣지의 kind 를 base · target 의 eid 로 찾는다 — 항목 꼴을 바꾸지 않는다), (3) 엣지 수가 움직인 롤업 행(롤업은 kind 를
  가리지 않고 잘린 행이 빠진 채 세며 어느 조립 단위의 행이 빠졌는지 모른다)에 `excluded_reason='truncated'`. 의미층보다 먼저 단다 — capture_partial
  처럼 뒤에서 이벤트를 비우면 잘리지 않은 kind 의 사건까지 지운다. 다른 사유가 먼저 붙은 항목은 그대로 둔다(다른 제외 단계와 같다).
  의미층의 롤업 고리가 이제 제외 사유를 본다 — 종전에는 보지 않았고, 롤업에 사유를 붙이는 단계가 의미층 뒤뿐이라 드러나지 않았다.
- 옛 캡처 — 종류별 수가 없고 degraded 에 `interfaces_truncated` 만 있으면 어느 kind 인지 몰라 네 kind 전부다. 모르는 것을 '안 잘렸다' 로
  읽으면 빠진 간섭이 '해소' 가 된다. 잘리지 않은 kind 는 그대로 사건이다(tied 만 잘린 쌍에서 사라진 간섭은 iface.removed 다 — 시험).
- 검토 단위 — `units.EXCLUDED_POLICY["none"]` 에 truncated. 설계서 3.4.1 의 none 은 '한쪽 스냅샷에 없거나 캡처가 깨져 생긴 겉보기 차이' 이고
  truncated 가 바로 그것이다. 목록에 없으면 모르는 사유라 단서(caveat) 줄로 셀에 가서 '사라졌다' 가 검토에 실린다(옛 코드는 bundle 단위가
  가졌다 — 시험이 본다).
- 어휘 — `diff.EXCLUDED_REASONS` 와 rr_diff 스키마 열거에 truncated 를 더했다. source_drift · capture_partial 은 생산자가 실제로 붙이는데 두 목록에
  없다(units 의 주석이 이미 그렇게 적는다) — 이 일의 몫이 아니라 그대로 두었다.
- 남긴 것 — 규칙 R-001 · R-002 의 `not_evaluable_reason='truncated'` 는 아직 `interfaces_truncated` 하나로 둘 다 평가 불가다. 정본 §3.2.6 은 그 kind
  (interference · clearance)가 잘렸을 때만이고 이제 kind 별 수가 있어 좁힐 수 있다(작업 대장 '다음 수' — 지금이 안전한 쪽이다).
- 시험 — `tests/test_diff_truncation.py` 6건(한쪽만 잘린 합성 쌍 — target · base · 파라메트릭 · 잘리지 않은 kind · 옛 캡처 · 검토 단위)과
  `tests/test_adapters.py` 새 3건(REST · MCP 폴백의 kind 별 수 · 안 잘림) · 기존 절단 시험의 kind 별 수 단언.
- **반대 검토 뒤(BL-7 ~ BL-9)** — (3)의 롤업은 kind 별로 고쳤다(잘린 kind 의 수가 움직인 행만 뺀다). 명명 치수 · 고아 전이 · 검토 근거
  줄에도 truncated 가 닿는다. '잘리지 않은 kind' 시험이 tied 만 잘린 쌍의 롤업 사건 억제까지 단언하던 것도 고쳤다.

### BL-3. 노드 500 · 엣지 2,000 diff 의 시간 · 메모리(B26, cbd3bf6)
- 쌍 — 합성기(`devseed` — 리프 362 · 조립 단위 8 · dyna 짝 35% · 계면 밀도 9.0 · 무작위 변경 50, 씨앗 20261031)가 어댑터 결과를 만들고 IR · 대응 ·
  diff 는 실제 생산자가 만든다. 한쪽마다 노드 505 · 504, 엣지 2,084 · 2,081(tied 638 · clearance 492 · part_of 373 · touching 341 · interference 173 ·
  contact 65 · scope 2), 의미 사건 124 · 막힘 없음.
- 실측(dev, 2026-10-31 — 부하 평균 7.8 / 32코어, 파이썬 3.12) — `compute_diff`(대응 사다리 포함) 다섯 번 0.200 ~ 0.218 s(중앙 0.204 s), tracemalloc
  피크 20.0 MB(다섯 번 같다), 새 프로세스의 RSS 피크 97 MB(시작 36 MB · 쌍을 짓고 54 MB). 쌍을 짓는 데 1.1 s 다.
- 결론 — 피크가 1.5 GB 에 한참 못 미쳐 매니페스트 `memory_gb 2` 그대로다(§10 #27). 시험은 5 s · 1.5 GiB 를 단언한다.
- 시험 — `tests/test_diff_scale.py` 1건. 막힌 diff(의미층을 건너뛰어 빨라 보인다)가 아닌지 먼저 본다. 측정이라 '고치기 전 깨지는' 시험이 아니다 —
  옛 코드에서도 통과한다.

### BL-4. 카드 창 측정 스크립트(B32, 111b34e)
- `backend/scripts/card_window_census.py` — 읽기 전용(GET 두 경로 — `/api/agents` 와 전문가마다 `/api/agents/{agent}/records`). 엔진은 형제 리포를
  들인다(`../HWAXAgentServer`, 스크립트 위치에서 리포 루트를 유도한다 — 박스 경로를 박지 않는다). 앱은 카드를 정규화하지 않는다는 원칙(cardpack)과
  어긋나지 않는다 — 운영 경로가 아닌 측정 도구라 엔진 함수를 그대로 쓴다(W-D2 와 같다).
- 창 — 1M 은 1,048,576 토큰 · 출력 상한 없음이다. W-D2 의 1M 한 장 자리 84.5만 · 81.7만 자와 입력 결손 몫 138,117자가 이 값에서만 나온다
  (1,000,000 · 32,000 이면 78.9만 · 76.3만 · 131,622 — 거꾸로 맞춰 확인했다). 20만은 엔진 external_llm 기본(200,000 · 32,000)을 읽는다. 손잡이는
  env={} 로 엔진 기본이다 — 박스 env 를 읽으면 같은 카드도 박스마다 수가 달라진다.
- 보기 둘 — W-D2 는 `/records` 가 내는 기록 전부를 셌는데 엔진 팩(`build_pack`)은 list_records(doc_type=expert_knowledge_card)로 지식카드만 싣는다
  (get_record 도 doc_type 이 다르면 받지 않는다). 두 보기를 함께 내야 W-D2 를 재현하면서 실제 심사가 보는 수를 본다(↓ W-D).
- 무겁다 — 전문가마다 기록 전문을 받는다. dev 명단 전원 796명이 5분 · RSS 피크 747 MB(한 명이 3,564만 자)였다. 한 명씩 차례로 돌고 그 글을 버린다.
- 시험 — `tests/test_card_window_census.py` 6건. 하위 프로세스로 돌린다 — 엔진 모듈(card_review · deliberation …)이 이 시험 세션의 sys.path ·
  sys.modules 에 섞이지 않게(포털 계약 시험이 엔진을 들여 생긴 일이 있다). AIDataHub 는 시험이 띄운 루프백 서버라 dev 의 실 서비스를 부르지 않는다.
  엔진이 곁에 없을 때만 건너뛴다(`skip_budget.SIBLING_ONLY`).

### BL-5. 시험 · 변이 · 전체 시험
- 새 시험 31 — `test_sameas_fuzzy_cap.py` 15 · `test_diff_truncation.py` 6 · `test_diff_scale.py` 1 · `test_card_window_census.py` 6 ·
  `test_adapters.py` 3(기존 절단 시험에 kind 별 수 단언도 더했다).
- 고치기 전 — 옛 코드(9bd5f48 사본)에 새 시험을 얹으면 31건이 붉다(B24 15 · B25 10 · B32 6 — 까닭은 '6단계 점수를 매겼다' · 가짜
  iface.removed · iface.added · iface.penetration_changed · asm.rollup_changed · 검토 단위 bundle · kind 별 수 없음 · 스크립트 없음). B26 은 측정이라
  옛 코드에서도 통과한다.
- 변이(스크래치 사본, 끝나면 지웠다) 25개 전부 잡혔다 — B24 11(상한 없음 · 경계 < 둘 · 원장 rejected 를 가져감 · fuzzy 레코드를 셈 · ecad 를
  남은 노드로 · degraded · 경고 · sig · 쌍 caveat · parser_differs 덮어씀) · B25 9(엣지 변경 · 엣지 파라메트릭 · 롤업 · 의미층 롤업 고리 · 옛 캡처
  폴백 · target 만 봄 · 검토 단위 정책 · kind 별 수 대신 counts · 0 인 kind 도 적음) · B32 5(조각을 한 번으로 · 지식카드 거르기 없음 · 입력 결손
  몫을 1M 값으로 · 키를 안 실음 · 낡은 엔진 확인 없음).
- 전체 시험(공유 잠금 아래, 38c5b3f) — 3,535 통과 · xfail 4 · 실패 0 · 건너뜀 0(rc 0, 12분 51초 — 앞 판 3,504 에 새 시험 31). ruff — 바꾼 파일은
  깨끗하다.
- 하지 않은 것 — 배선 리허설(`tests/synth/rehearsal_d.py`)은 프로세스를 띄우는 일이라 돌리지 않았다. 카드 대조 사슬에서 바뀐 것은 검토 단위의
  제외 정책에 새 사유 하나(truncated)뿐이다. 서비스 재기동 · push · 병합은 없다.

## W-D — 리스크 20만 창 카드 분포(W-D2 재현 · 명단 전원, 2026-10-31)

> 포털 `docs/risk-200k/context-notes.md` W-D2 의 측정을 BL-4 스크립트로 다시 했다. 엔진 8dd579a(api cr-1 · norm cr-n1 · 식 cr-l2) · dev AIDataHub
> (전문가 796명) · 창은 1M = 1,048,576 · 출력 상한 없음, 20만 = 200,000 · 32,000(한 장 자리 126,012자 · 입력 결손 몫 24,648자 — W-D2 와 같다).

### W-D2 재현 — dev 표본(`--wd2` — 정렬한 키에서 시드 20261020 으로 30명 + xd-yield-ramp · material-twin-analyst)

| | W-D2(10-20) | 같은 방법 오늘(records) | 지식카드만(knowledge_cards) |
|---|---|---|---|
| 기록(렌더) | 5,716(5,711) | 6,779(6,775) | 969(969) |
| 20만 한 장 자리 초과 | 143장 | 200장(특허 129 · 논문 71) · 조각 어림 418 | 0 |
| 그런 카드가 있는 전문가 | 19/32 | **19/32** | 0/32 |
| 20만 입력 결손 몫 초과 | 31/32 | **31/32** | 31/32 |
| 셀당 판정 호출 1M → 20만 | 중앙 26 → 65 · 최대 519 → 1,469 | 53 → 87 · 520 → 1,466(전문가별 배수 중앙 1.79 · 최대 2.82) | 2 → 2 |
| 훑기 호출 합 1M → 20만 | 470 → 2,120 | 630 → 3,293 | 31 → 31 |

- 19/32 · 31/32 는 그대로 나온다. 143 이 200 인 까닭은 경로가 바뀐 것이다 — AIDataHub `539d06b`(10-30, AD-20)가 `GET /api/agents/{agent}/records` 를
  agent_records 표에서 정본 records.agents 로 바꿨다(자동 바인딩 · PATCH 로 묶인 기록이 들고 지운 기록은 빠진다). 표본의 기록이 1,063건 늘었는데
  10-20 이전 적재분만 걸러도 렌더 6,775장 그대로다 — 새 적재가 아니라 묶음이 는 것이다. 옛 목록(agent_records)을 읽는 API 가 이제 없어 143 자체는
  API 로 다시 낼 수 없다.
- **넘는 것은 지식카드가 아니다.** 20만에서 넘는 200장은 전부 논문 · 특허다. 엔진 팩은 지식카드만 싣으므로(BL-4) 실제 심사가 보는 카드는 표본에서
  한 장도 넘지 않는다 — 가장 긴 지식카드 2,372자, 전문가 합 최대 52,065자.

### 명단 전원 — dev 796명(5분)

| | records(기록 전부) | knowledge_cards(엔진 팩) |
|---|---|---|
| 카드가 있는 전문가 | 775/796 | 774/796(HE 팀 운영자 등 22명은 지식카드 0) |
| 기록(렌더 · 절 없음) | 72,252(71,812 · 440) | 23,418(23,418 · 0) |
| 종류 | 논문 37,770 · 지식카드 23,418 · 특허 6,535 · 물성 2,688 · 규격 1,399 · 백서 431 · 그 밖 11 | 지식카드 |
| 전문가 글자 합 | 중앙 102만 · 최대 3,564만 | 중앙 28,900 · 최대 58,699 |
| 가장 긴 한 장 | 578,728자 | 3,198자 |
| 20만 한 장 자리 초과 | 3,128장(특허 1,848 · 논문 1,096 · 규격 184) · 398명 · 조각 어림 6,748 | 0 |
| 1M 한 장 자리 초과 | 0 | 0 |
| 입력 결손 몫 초과 1M · 20만 | 578명 · 755명 | 0 · 715명 |
| 셀당 판정 호출 1M → 20만 | 중앙 12 → 21 · 최대 520 → 1,466(전문가별 배수 중앙 1.63 · 최대 3.83) | 2 → 2(1.0배) |
| 훑기 호출 합 1M → 20만 | 8,021 → 38,653(4.8배) | 774 → 774 |
| 계획의 oversize.cards | 0 | 0 |

- 읽는 법 — 엔진 팩 기준으로 20만에서 달라지는 것은 입력 결손 몫 하나다(카드 있는 774명 가운데 715명이 24,648자를 넘는다 — W2 의 must_full 쪽
  나누기가 받는 자리다). 한 장 자리 초과(조각 · W1)와 판정 · 훑기 호출 배수는 지식카드에서 생기지 않는다(지식카드 한 장은 3,198자가 최대다).
  W-D2 의 L1('19/32명이 멈춘다')과 호출 배수(2.6배 · 4.5배)는 팩이 싣지 않는 논문 · 특허 · 규격 · 물성 카드에서 나온 수다. W1 조각은 틀린 장치가
  아니다 — 카드가 길어지면 그대로 받는다. 다만 지금 dev 의 팩에서는 돌지 않는다.
- 운영(cae00)은 명단 · 카드가 다르다 — 아래 걸음으로 한 번 잰다. 전문가 키 목록(`over_slot_experts`)은 이 공개 리포에 옮기지 않는다.

### cae00 에서 한 번(사람)
1. 이 가지가 main 에 합쳐진 뒤 `git -C ~/Projects/HWAXRisk pull --ff-only`(스크립트가 든 판). 엔진은 risk-200k W1(5aa33fc) 이상이어야 한다 —
   낡았으면 스크립트가 종료 2 와 그 말로 멈춘다.
2. 리스크 심사 잡이 도는 때는 피한다 — 전문가마다 AIDataHub 의 기록 전문을 읽는다(dev 796명에 5분 · RSS 0.75 GB).
3. `cd ~/Projects/HWAXRisk && ../HWAXAgentServer/.venv/bin/python backend/scripts/card_window_census.py --out ~/census-cae00.json`
   - 종료 2 · 'HTTP 401' 이면 그 박스의 AIDataHub 가 키를 요구한다 — `read -rs AIDH_API_KEY && export AIDH_API_KEY` 뒤 다시 돌린다(키는 셸에만).
   - AIDataHub 가 127.0.0.1:8001 이 아니면 `--base` 로(또는 `HWAXRISK_AIDH_BASE`).
4. 가져올 것 — 출력의 `roster` · `engine` · `failed` 와 `views.records.windows` · `views.knowledge_cards.windows` 두 블록의 수. dev 로 가져오면 이 절에
   cae00 열로 적는다.

## 캡처 · diff 백로그 — 반대 검토 고침 넷(가지 `wt1031/bl-risk-capture`, b1e1ee7 위, 2026-10-31)

> 반대 검토가 B24 · B25 에서 찾아 확인한 넷이다. 넷 다 b1e1ee7 사본에서 먼저 재현했고(검토의 탐침 그대로), 고친 뒤 같은 탐침이 바뀐 답을 낸다.
> 포털 문서는 이 리포가 고치지 않는다 — 정본(plan §2.6.3 · §3.2.3 · §3.3.3 · §3.3.6)과 달라진 곳은 아래에 적었고 문서 워크플로가 단다.

### BL-6. same-as 6단계 — 배정 행렬의 변도 상한이다(B24 고침)
- 결함 — 곱 규칙(`len(rest_a) × len(rest_b) > 800 × 800`)이 기운 모양을 막지 못했다. 동봉 헝가리안은 미배정 더미를 붙인 (남은 a + 남은 b)
  변의 정사각 행렬에서 돌아 시간이 곱이 아니라 변의 세제곱이다. 실측(dev, 점수를 고정한 첩자) — 1 × 200 0.21 s · 1 × 400 1.74 s(변 두 배에
  8배), 30 × 300 0.84 s · 30 × 600(곱 18,000 · 변 630) 6.5 s, 반대 검토 실측 30 × 1,200 54 s. 30 × 3,000 은 곱 9만(상한의 14%)인데
  세제곱으로 늘려 어림하면 12 ~ 13분이고, 시험이 허용하던 1 × 640,000 은 640,001 변 행렬을 짓는다. dyna pid 는 모델 크기 상한(routes)이
  세지 않고 캡처 예산도 이 단계를 끊지 않아 intra dyna↔mcad 에서 그대로 닿는 모양이다.
- 고침 — `sameas.FUZZY_MAX_SIDE = 1,600`(800 × 800 이 짓는 변)을 더해 곱 또는 변이 넘으면 건너뛴다(`_fuzzy_too_large` — resolve 와 fuzzy_skip
  이 한 곳을 쓴다). 지금 두 값에서는 변 ≤ 1,600 이면 곱 ≤ 640,000 이 따라 나와 변 규칙이 곱 규칙을 품는다 — 그래도 곱 줄을 지우지 않은 까닭은
  정본이 적은 규칙이고 두 값이 따로 바뀔 수 있어서다. 건너뛴 뒤의 길(degraded · 경고 · sig · 쌍 caveat)은 같고, skip 에 `side_limit` 을
  더했다(`correspondence.fuzzy_skipped.side_limit`). 경고 글은 곱과 변을 함께 적는다.
- 버린 안 — 작은 쪽을 행으로 한 직사각 배정(더미가 큰 쪽과 함께 자라지 않는다)은 기운 모양도 돌게 하지만 풀이기가 바뀌어 동점 근처에서
  배정이 달라질 수 있다. 같은 입력의 ir_hash 가 판마다 바뀌면 스냅샷 멱등((project_id, ir_hash))이 깨진다 — 상한 안의 결과를 그대로 두는
  쪽을 골랐다. 대신 30 × 1,571 처럼 싸게 풀 수 있는 모양도 건너뛰고 그 사실은 표지로 남는다.
- 정본과 달라진 곳 — plan §2.6.3(포털 plan.md:925)은 곱 규칙만 적고 §3.2.3 sig 표(plan.md:1368)는 '`800×800` 초과' 다. 변 1,600 을 더해 적어야 한다.

### BL-7. 잘린 계면을 읽는 명명 치수(B25 고침)
- 결함 — `edge[…]` 명명 치수가 잘린 계면을 읽으면 잘린 쪽에서 ref 가 비어(ref_missing) `null_one_side` 가 되고 의미층이
  `dim.named_unmeasured` 를 냈다(B25 는 dims_delta 를 보지 않았다). 검토 단위에는 그 사건이 active 줄로, 치수 줄은 단서(caveat)로 실렸다 —
  '잰 간섭이 사라졌다' 가 셀에 갔다. clearance 가 정렬 규칙상 가장 먼저 잘리므로 간격 치수가 가장 잘 걸린다.
- 고침 — `diff._truncated_dims` 가 두 쪽 dims_named 행의 `ref`(eid)를 그쪽 스냅샷의 eid → kind 로 보고 잘린 kind 면 그 치수를 고른다.
  잘린 쪽은 ref 가 비므로 남은 쪽 ref 로 알아본다(잘린 쪽이 base 여도 같다). 파생 치수(`dim(a) op dim(b)` — ref 가 치수 이름 둘)는 정의 사슬을
  따라 함께 든다. 고른 치수는 `excluded_reason='truncated'` 로 null_one_side 를 이긴다(까닭이 절단이다). 미측정 고리는 제외 사유가 없거나
  null_one_side 일 때만 사건을 낸다. 잘리지 않은 kind 의 계면이 정말 사라져 빈 치수는 그대로 사건이다(시험).
- 요약(summary_text — 브리프 E1)의 [치수] 도 truncated 치수를 싣지 않는다 — 실으면 '0.050→미측정' 이 그대로 간다. 그 수는 [비교가능성] 의
  '제외 truncated N건' 에 든다(정본 §3.3.6 — 제외 항목은 건수만). 브리프 E3 는 줄마다 `excluded_reason=truncated` 를 달아 그대로 두었다.
- eid → kind 는 스냅샷의 엣지 전부(rejected 포함)에서 읽는다 — 명명 치수는 rejected 계면도 읽고, eid 는 스냅샷 안에서 유일해 엣지 파라메트릭의
  답은 종전과 같다.

### BL-8. 고아 전이와 근거 줄(B25 고침)
- 결함 — 잘린 간섭이 그 부품의 유일한 계면이면 orphans_delta 가 '고아됨' 을 냈고 검토 단위가 부품 상태와 줄마다의 표지로 실었다. 근거 줄(A 층)은
  한쪽에만 있는 그 계면을 '삭제' 와 '0.050→미측정' 으로 적었다. 둘 다 B25 전부터 있던 길이지만 B25 가 사건에서 뺀 '간섭이 사라졌다' 를 그대로
  나른다. 요약의 '고아 +N' 도 같은 목록을 센다.
- 고침(고아) — 고아가 아닌 쪽에서 잘린 kind(clearance 빼고 — 고아 차수가 세지 않는다)의 계면에 끼어 있던 부품은 고아 쪽에서 그 행이 잘렸을 수
  있다. 그런 전이는 `became_orphan` · `left_orphan` 에서 빼 `orphans_delta.truncated{became_orphan, left_orphan}` 로 옮긴다(목록 base · target 은
  그대로 — 흔적 없이 지우지 않는다). 잘린 kind 가 없으면 그 키가 생기지 않아 잘리지 않은 diff 는 종전과 같다.
- 고른 규칙 — 반대 검토의 두 안 가운데 '잘린 kind 를 빼고 고아를 다시 센다' 는 버렸다 — 잘린 kind 의 계면이 남아 있는 부품을 고아라 부르게
  된다. '전이가 잘린 kind 에서만 왔으면 뺀다' 보다 한 걸음 넓게 '고아가 아닌 쪽에 잘린 kind 의 계면이 있었으면 뺀다' 로 했다 — tied 와 간섭을
  함께 잃었는데 tied 가 잘린 kind 면 tied 행이 고아 쪽에서 잘렸을 수 있어 고아라 말할 수 없다. dn 단위라 한 클러스터(mcad 부품 · dyna pid)에서
  다른 쪽이 정말 고아가 된 경우도 함께 빠진다 — 표지를 놓치는 쪽이고(거짓 표지는 아니다) 그 접촉 변화의 사건은 남는다.
- 고침(근거 줄) — diff 가 truncated 로 뺀 구조 변경의 열쇠(`units._diff_edge_changes` 셋째 값)에 걸린 한쪽만의 계면은 있는 쪽 값만 적고
  '목록 절단 — 비교 불가(base 에만 있다 · target 에만 있다)' 로 둔다. 순서는 바뀌지 않은 계면 쪽이다. 두 쪽에 다 있는 계면은 값이 실측이라
  그대로다.

### BL-9. 롤업은 kind 별로(B25 고침)
- 결함 — B25 는 롤업 항목(kind 를 합친 수)에서 수가 움직인 행을 잘린 kind 와 무관하게 뺐다. clearance 만 잘린 쌍(정렬 규칙상 가장 흔한 꼴)에서
  clearance 가 하나도 없는 조립 단위의 실제 tied 증가가 asm.rollup_changed 를 잃었다(정본 §3.3.6 과 triage 행은 잘린 kind 의 변화만 뺀다).
  tied 만 잘린 쌍의 간섭 감소도 같았고, 종전 시험이 그 억제를 단언하고 있었다 — 고쳤다.
- 고침 — `diff._truncate_rollups` 가 IR 롤업 행의 kind 별 수를 다시 읽어 잘린 kind 의 수가 두 쪽에서 다를 때만 행을 뺀다. 같으면 행은 비교
  대상이고 계면 수를 잘리지 않은 kind 로만 다시 센다(잘린 쪽의 그 kind 수는 일부라 합에 넣으면 숫자가 틀린다). 뺀 kind 는 항목의
  `truncated_kinds` 에, 사건 글과 검토 줄에 '(목록이 잘린 kind … 는 세지 않았다)' 로 적힌다. 잘린 kind 가 그 행에 없으면 행은 손대지 않는다.
  잘린 kind 의 수와 다른 kind 의 수가 함께 움직인 행은 통째로 뺀다(그 계면 하나하나의 사건은 남는다).

### BL-10. 시험 · 변이 · 전체 시험
- 시험 — `test_sameas_fuzzy_cap.py` 15 → 21(곱 · 변 경계 매개변수 10 · 기운 남은 노드의 resolve · 기운 스냅샷), `test_diff_truncation.py` 6 → 14
  (명명 치수 둘 · 고아와 근거 줄 넷 · 롤업 둘, 고친 것 하나 — tied 만 잘린 쌍의 롤업과 고아).
- 고치기 전 — b1e1ee7 사본에 새 시험을 얹으면 19건이 붉다. B24 11건 가운데 5건이 행동(기운 모양을 돌린다)이고 6건은 skip 의 `side_limit` 꼴이다.
  B25 8건 가운데 7건이 행동이고 1건(clearance 만 잘린 쌍의 고아 전이)은 새 코드가 지나치게 빼지 않는지 지키는 시험이라 옛 코드에서는 새 키가
  없어 붉다. 정직한 제거는 '삭제' · '고아됨' 이라는 대조 시험은 옛 코드에서도 통과한다 — 앞 시험이 빈 것을 단언한 게 아님을 보이는 짝이다.
- 변이(스크래치 사본, 끝나면 원문으로 되돌렸다) 19개 전부 잡혔다 — B24 5(변 줄 없음 · ≥ · resolve 만 곱 · fuzzy_skip 만 곱 · 쌍의 side_limit) ·
  치수 5(표시 안 함 · 파생 사슬 없음 · base ref 만 · 미측정 고리가 사유를 안 봄 · 요약 거르기 없음) · 롤업 4(아무 kind 나 움직이면 뺌 · 다시
  세지 않음 · 사건 글 · 검토 줄) · 고아와 근거 줄 5(거르기 없음 · clearance 를 셈 · 두 쪽을 뒤바꿈 · '삭제' · 두 쪽 값).
- 관련 시험 19파일(diff · units · render · sameas · ir_builder · brief 등) 820 통과 · xfail 1. ruff — 바꾼 파일은 깨끗하다.
- 전체 시험(공유 잠금 아래, 작업 트리 = 이 고침 셋) — 3,549 통과 · xfail 4 · 실패 0 · 건너뜀 0(rc 0, 12분 18초 — 앞 판 3,535 에 새 시험 14).
- 하지 않은 것 — 배선 리허설(`tests/synth/rehearsal_d.py`)은 프로세스를 띄우는 일이라 돌리지 않았다. 카드 대조 사슬에서 바뀐 것은 검토 단위의
  근거 줄(한쪽만의 잘린 계면)과 롤업 줄 글뿐이다. stats.edges_removed · 요약의 '계면 −N' 은 제외된 구조 변경도 센다 — 모든 제외 사유가 그렇고
  [제외] 줄이 함께 실려 이 일의 몫으로 두지 않았다. 서비스 재기동 · push · 병합은 없다.

## 남은 일 10-31 리스크 엔진 — B23 · B27 · B29(가지 `wt1031/bl-risk-engine`, main 9bd5f48 위, 2026-10-31)

> 포털 `docs/leftovers-1017/triage-1031.md` 표 B 의 세 줄이다 — B23(포털 design-risk-review checklist 106 ① ~ ③) · B27(132 · 152) ·
> B29(135). 사용자 결정 10-31 — 표 A 추천 전부를 받고 표 B 의 dev 작업을 한다. 계획 정본은 포털 plan.md §2.8b · §5.6.1 · §5.2.2 ·
> §7.7 · §4.3.2 · §5.9.5 다. B29 는 계획 글(plan.md 3339-3346 의 여섯 걸음)에서 먼저 설계했고(BE-6 · BE-7) 걸음마다 시험을 따로 세웠다.

### BE-1. 요구 대조는 저장된 상태가 아니라 지금 원장으로 센다(B23)
- 브리프 E0 · E3 와 원자 저장 보정이 같은 함수(`requirements.compute_req_signals`)로 그 대상 스냅샷(diff 면 뒤 스냅샷)의 명명 치수와 지금
  rr_requirements 를 대조한다. 브리프는 한 번만 센다(`brief._req_view` — ctx 에 둔다), 저장은 `SpecContext.requirement_view` 가 한 번 센다.
- 까닭 — 동결(`ir_builder.freeze_snapshot`)이 `state.build_state(ir)` 를 요구 없이 불러 rr_states 에 `req.margin` 이 서지 않는다. 요구를
  고쳐도 상태를 다시 세지 않는다(`upsert_requirements` 가 `recompute` 목록을 돌려줄 뿐 부르는 곳이 없다). 저장된 상태를 읽었으면 E0 는 늘
  '요구 미등록' 이었고 E3 에는 여유가 한 번도 서지 않았을 것이다.
- 고치지 않은 것 — rr_states 의 `sig:req.margin` · `missing.req_absent` · R-007 은 그대로 비어 있다. 포털 106 줄의 'state.py 대조 · 요구 편집은
  rr_states 재계산' 칸이고 B23(① ~ ③)의 범위 밖이다(BE-10).

### BE-2. E0 요구 한 줄과 E3 두 열의 꼴(B23)
- E0 — `요구 dim_limit n · 최소 여유 ±m 단위 [req:<이름>] · 시나리오 a/b` 또는 `요구 미등록`. 미등록은 요구 행이 하나도 없을 때다(면제까지 0 —
  compute_req_signals 의 req_absent 와 같다). 한계만 있고 여유를 모르면 `최소 여유 미측정` 이다. missing 줄 뒤 · 소스 id 줄 앞에 둔다 — 짧고
  E0 에만 있는 줄이라 상한에 걸리면 소스 줄이 먼저 잘린다.
- E3 — 줄 끝에 ` | limit=<op> <값> <단위> [req:<이름>] | margin=<±값> <단위>(위반|여유)`, 요구 없는 치수는 ` | limit=— | margin=—` 다.
  한계 꼴은 `req:` 의 정규 표기(`narrative.canonical_text_for` — `<op> <canonical_json(값)> <단위>`)와 같아 좌석이 옮긴 한계가 인용 대조를
  지난다. 여유 ≤ 0 이 위반이다(R-007 `req_margin_negative` 와 같은 경계). 여유 값은 저장 값(반올림 6자리) 그대로에 부호(+ · U+2212)를 붙인다.
- 차례 — 요구가 걸린 줄이 여유 오름차순으로 먼저(위반 · 근접이 상한에 잘리지 않게), 미측정은 0 이 아니라 그 뒤, 요구 없는 줄은 그 뒤에 종전
  차례(바뀐 치수가 먼저)다. 이 스냅샷에 치수가 없는 요구도 `치수 없음 «<이름>» | … | margin=미측정` 한 줄로 선다 — `d:` 참조는 만들지 않는다
  (스코프에 없는 치수를 가리키면 dangling 이다).
- 이름은 `[req:<이름>]` 토큰으로 싣는다(`_ref_name` — 위생을 지나고 린터 제외 구간이다). 계획 예시는 `(battery_to_frame_gap)` 처럼 맨 이름이지만
  사람이 지은 이름이라 토큰으로 바꿨다. 규격(standard) 요구 수는 싣지 않았다 — 줄 꼴이 dim_limit 과 시나리오만 적는다.

### BE-3. 원자 저장 보정은 요구 인용이 있는 원자만(B23)
- `narrative._normalize_finding` 이 인용 해석 뒤 `_check_requirement` → `requirements.check_finding_requirement`(지금까지 시험만 부르던 함수)를
  부른다. 요구 인용(requirement_ref 또는 `req:` cite)이 있는 원자만이다. 여유 ≤ 0 인 요구를 가리키며 OK 면 undetermined 로 보정하고
  parse_warnings 1건이다. 유효 요구는 candidate · confirmed 다(인용 해석 `SpecContext.requirement` 와 같은 범위 — waived 는 근거가 아니다).
- 요구 인용이 없는 원자는 손대지 않는다 — check 함수는 빈 requirement_ref 칸을 세우므로 그대로 부르면 모든 finding_json 의 바이트가 바뀐다.
- 패널 저장 행에 requirement_ref 열을 쓴다(지표 req_consistency 가 이 열을 읽는다 — 종전에는 패널 원자에서 늘 NULL). 카드 대조 저장 행
  (`expert_report._finding_row`)의 열은 그대로다 — 값은 finding_json 에 있고, 그 표의 열 비교 목록(`_FINDING_CODE_COLUMNS`)은 넓히지 않았다.
  보정 자체는 같은 정규화를 지나는 카드 대조 원자에도 걸린다.
- 사람 finding(POST /targets/{key}/findings)의 판정은 고치지 않는다 — 계획 문면이 '파서' 의 보정이고, 사람이 정한 판정을 코드가 덮지 않는다.

### BE-4. role_sha · persona_rev(B27)
- 원천은 `list_agents(compact=False, domain)` 의 description 이다 — 엔진 `_restore_role` 이 좌석에 되살리는 글(AIDataHub Agent.description)과
  같은 칸이다. 압축 응답(agent_type · name · common_tags)에는 그 글이 없어 두 칸을 채울 수 없었다. 늘어나는 것은 전문가당 역할 글 한 칸이다
  (dev 의 전문가 정의 사본 754명 — 중앙값 약 410자 · 최대 714자).
- role_sha = sha256(글)[:12], persona_rev = 그 앞 7자(`planner.persona_stamp`). 글이 없거나 공백뿐이면 둘 다 NULL 이다 — 빈 글의 해시로 적지
  않는다. description 이 빈 전문가는 엔진이 system_prompt 의 역할 문서로 앉히는데 그 글은 list_agents 에 없어 NULL 로 둔다. 역할 글 자체는
  저장하지 않는다(해시만).
- persona_rev 를 박스마다 세는 차례 번호(r1 · r2 …)로 두지 않은 까닭 — 계획은 '사람이 읽는 판번호' 라 적지만 AIDataHub 에 전문가의 판 칸이
  없고, rr_roster · rr_seat_opinions 는 dev ↔ cae00 반출 · 들여오기로 박스를 넘는다. 박스마다 따로 매긴 번호는 같은 역할을 다른 번호로, 다른
  역할을 같은 번호로 적어 E7 의 판 비교를 틀리게 한다. 글에서 바로 나온 짧은 해시는 어느 박스에서도 같다(git 짧은 해시 꼴).
- 덧붙이기(refresh_roster)도 새 행에 같은 칸을 쓴다. 기존 행은 불변이다(§6.3).

### BE-5. 의견 행 사본 · nightly 스탬프 · E7 [이전 정의](B27)
- 패널 저장이 rr_seat_opinions.persona_rev 에 그 좌석 로스터 행의 판을 베낀다(원장 좌석만 — 반대석 · 추가 좌석은 NULL). 카드 대조 의견은
  종전부터 베꼈고(`expert_report._write_opinion`) 이제 로스터에 값이 있다.
- nightly 스탬프는 손대지 않았다 — rk01 가지가 그 파일을 고치는 중이고, 로스터의 첫 판(agent_key 순)을 읽는 종전 식이 이제 값을 낸다.
  대상 전체의 페르소나를 한 값으로 접는 일(전 좌석 판의 해시 등)은 열린 항목이다(BE-10).
- E7 — 회수한 의견의 판과 그 좌석의 지금 로스터 판을 둘 다 알고 서로 다르면 줄 앞에 `[이전 정의] ` 를 붙이고 220자 안에서 그 길이만큼 발췌가
  준다(`_seat_line(marker=)`). 한쪽이라도 모르면 붙이지 않는다 — 옛 의견(판 이전) · 역할 글 없는 로스터를 '정의가 바뀌었다' 로 적지 않는다
  (E5 의 변경 주체 접두와 같은 원칙 — 모름과 바뀜을 같은 글자로 쓰지 않는다). 줄 머리가 `[…] narr:` 꼴이라 린터의 인용 줄(`_QUOTE_LINE`)로
  읽힌다.
- AIDataHub 회수 경로(`_adh_seat_memory`)는 판정하지 않는다 — 그 레코드를 보내는 쪽(M4)이 아직 없어 판이 실릴 자리가 정해지지 않았다.

### BE-6. rekey 모델 — 계획 글에서 지은 설계(B29)
- 저장 키는 바뀌지 않는다. rr_findings.subject_key 는 저장 때 그 스냅샷 노드의 ckey(동결 시점의 유효 ckey — `assign_ckeys` 가 resolve_ckey 를
  지난 값)이고 cluster_key 도 삽입 시 동결이다(§4.3.2 1).
- '지금 원장으로 다시 센 주체'(`rekey.current_subject`) = 동결 주체의 `ck:` 조각을 지금 merged_into 사슬로 풀고(≤5단, 그 소유자의 원장)
  계면이면 살아 있는 rr_iface_alias 로 접은 값이다. dim: · asm: · 미해석('')은 원장과 무관해 그대로다.
- 같은 cluster_key 의 원자는 동결 입력(메커니즘 · 세부 · 주체 · 변경 종류)이 같으므로 다시 센 키도 같다 — 그래서 옮김을 별칭(옛 키 → 새 키)
  으로 적을 수 있다. 계획 3걸음의 'finding 마다 다시 계산' 을 키마다 셌다. 계획 문면을 원자마다 노드의 '계산 ckey' 로 다시 세는 뜻으로 읽으면
  한 cluster_key 안의 원자(대표 X 의 원자와 병합 중 X 로 들어온 Q 의 원자)가 서로 다른 새 키를 원하는데 별칭은 키 단위라 적을 자리가 없다.
- 맞추기(3걸음, `reconcile_aliases`) — 다시 센 키가 동결 키와 다르면 원장 별칭을 append 한다(reason ckey_merge — 파트 키가 풀린 탓 · iface_alias
  — 계면 별칭 탓). 같으면 그 옛 키에 원장이 세웠던 별칭(ckey_merge · iface_alias)을 같은 사람 · 같은 시각으로 revoke 한다(§5.9.5 3 의 문면).
  사람 · 재매핑이 세운 별칭(cluster_merge · taxonomy_major · dim_rename)은 거두지도 덮지도 않고 결과에 kept_human 으로 남긴다. 동결 키를 같은 식
  으로 다시 만들 수 없는 원자는 옮기지 않는다(skipped `key_not_reproducible` — 생산자마다 빈 값의 꼴(None · '')이 달라 둘 다 대본다).
- 왜 되돌리기만이 아닌가 — 되돌릴 별칭은 확정 때 섰어야 한다. 그래서 merge_key 도 같은 길(`run(op='merge_key')`)을 돈다 — 병합이 등록부를
  접고(ckey_merge 별칭) unmerge_key 가 그것을 거둔다. 이 짝 없이 되돌리기만 지으면 '확정 → reject 왕복' 시험은 아무것도 보지 않는다 — 실제로
  옛 코드에서 처음 쓴 왕복 시험이 헛통과해 맞대 보기(확정 뒤 옛 키 행 superseded · priors 바뀜)를 더했다.
- 한계 — 병합이 서 있던 동안 동결한 스냅샷의 노드는 대표 키를 받았다. 병합을 풀어도 그 스냅샷 위 원자의 주체는 대표 키 그대로다 — 갈라 보려면
  '재해석 적용'(새 스냅샷)이 필요하다(§2.7.3 '기존 스냅샷의 ckey 는 바뀌지 않는다'). intra · pair same-as 확정도 같은 까닭으로 동결 때 노드
  ckey 에 흡수된다 — reject 의 키 효과는 그 확정에서 자동 승계된 rr_part_keys 행(§2.7.3)을 되돌리는 것뿐이다.

### BE-7. 네 조작과 짝 · 한 트랜잭션 · 감사(B29)
- same-as reject — 1걸음 · 결정이 뒤집힐 때 prev_status · prev_decided_by · prev_decided_at 에 직전 값을 남긴다(UPSERT 의 CASE — 같은 결정을
  다시 내면 그대로, 행은 하나). confirmed → rejected 면 그 rr_sameas 행에서 자동 승계된 rr_part_keys 행(decided_by code:pair_correspondence ·
  merge_evidence_json.ledger_id = 그 행 id)을 되돌린다(status confirmed · merged_into NULL · merge_evidence_json NULL). 승계 근거에 ledger_id 를
  싣게 `inherit_ckeys` 를 고쳤다(원장 1단계 대응에서 온 링크만 — 다른 승계 근거의 바이트는 그대로). inherit_ckeys 는 아직 파이프라인에서
  부르지 않는다(test_sameas 의 strict xfail) — 지금 운영에서 reject 의 키 효과는 0 이고 감사 1행이 남는다.
- unmerge_key — 1걸음은 종전 그대로(자동 승계 행 포함). merged 였을 때만 재키를 돈다. 영향 범위는 그 키와 그 키에 매달린 키(`with_descendants`)다.
- 계면 원장 confirmed · manual → rejected(PUT /projects/{id}/iface-ledger) — 계면 원장은 다음 동결의 엣지만 바꾸고 저장 키(ckey · 계면 별칭)를
  바꾸지 않아 별칭 · 등록부는 그대로이고 감사 1행이 남는다. 계면 별칭 사전은 과제를 가로지르는 이름 원장이라 한 과제의 거절로 거두지 않았다.
- 계면 별칭 revoke — 계획의 REST 목록에 길이 없어 POST /sameas/decide 의 새 결정 `revoke_iface_alias {alias_key}` 로 열었다(남의 별칭은 404,
  이미 철회면 already). status revoked · revoked_by · revoked_at 을 쓰고 영향 범위는 별칭 키 둘 · 대표 둘(매달린 키 포함)이다. 지금 별칭은 전부
  자동 · 항등(대표 = 키 자체)이라 주체가 바뀌지 않는다 — 사람 확정 별칭(근접 별칭 확정 → source human · 대표 병합, §5.9.3)은 아직 길이 없다.
  저장 때 정규화(`narrative._iface_alias`)도 이제 살아 있는 별칭만 본다 — 종전에는 철회한 별칭으로도 새 원자의 주체를 접었다.
- 한 트랜잭션 — `record_decision` 의 원장 쓰기와 `rekey.run` 이 같은 store.tx 이고, 라우트는 배열 전체를 바깥 tx 로 감싼다(재진입 tx). 별칭
  6홉 · 순환은 `add_cluster_alias` 의 409 alias_chain_too_long 이 그대로 올라와 원장 변경까지 되돌린다. 되돌리기도 별칭을 세울 수 있어
  (Z → Y → X 에서 Y 를 풀면 Z 의 원자는 Y 의 클러스터로 간다) 그 길에서도 409 가 난다.
- 감사(6걸음) — scope registry · action rekey · subject_id `ckey:<ckey>` · `sameas:<id>` · `alias:<alias_key>` · `ledger:<project>:<pair_key>`,
  before {op, ledger, old_cluster_keys{옛 키: 그때 풀린 키}} · after {new_cluster_keys, findings_n, targets_n, aliases_added · aliases_revoked,
  kept_human, skipped, patterns, queue_closed}. 뒤집을 확정이 없던 조작(이미 confirmed 인 unmerge · 확정 아니던 쌍의 reject)은 재키도 감사도
  하지 않는다. merge_key 는 매번 남긴다(사람 조작이다).

### BE-8. 등록부 병합의 옛 행 · 5걸음(B29)
- 접힌 · 빈 옛 행 — 원자가 별칭으로 다른 클러스터로 옮겨 간 행(그 행의 옛 구성원 merged_json.member_ids · rejected_refs 가 이번 병합의 다른 행에
  있다)을 superseded · superseded_by='<대상>#<원자가 간 곳>' 으로 닫는다(`registry._close_vacated_rows`, §4.3.2 3). 접힘의 옛 키와, 갈라질 때
  접힘으로만 섰던 대표 키 행(다른 대상에서 접힘이 새로 세운 행) 둘 다다. 원자가 지워져 빈 행(패널 재제출 · 사람 finding 삭제)은 종전 그대로
  열려 있다(BE-10). 행은 지우지 않는다 — GET /refs 의 `reg:` 는 정확한 키로 찾으므로 옛 인용이 두 방향 모두 해석된다(dangling 0). 코드가 정한
  열린 행(open · rejected_in_panel)만 닫는다.
- 다시 열기 — 닫힌 클러스터가 다시 서면 superseded_by 가 같은 대상 표지인 행을 코드 상태로 다시 열고 superseded_by 를 비운다(`_write_registry_row`).
- 다른 대상의 닫힘 표지 — 코드 출처 status 옮기기를 open ↔ rejected_in_panel 로 좁혔다(주석이 말하던 범위). 종전에는 §4.8 이 닫은 옛 대상의 행
  (superseded · superseded_by=T′#…)을 다시 병합하면 open 으로 돌아갔다 — rekey 가 옛 대상까지 다시 병합해 드러났다.
- 이 병합 규칙은 사람의 클러스터 병합(PUT /registry/{k}/merge · cluster_merge 큐 결정)에도 걸린다 — 종전에는 접힌 옛 행이 열린 채 남아 판정
  후보 · 회수가 같은 지지를 두 번 셌다.
- 5걸음 — 기여 · priors 는 병합이 원자에서 다시 센다(증분 없음). 패턴은 cluster_key_norm 이 별칭으로 다른 키에 접히면 그 키의 패턴 id 를
  merged_into 에, 갈라지면 NULL 로 둔다 — 대표 키에 패턴이 아직 없으면 비워 둔다(다음 야간 마이너가 세운다). n_* 재합산은 야간 마이너의
  몫이다(접힌 패턴은 마이너가 건너뛴다). 열린 cluster_merge 큐 가운데 두 키가 이제 한 키로 풀리거나 한쪽이 다른 키에 접혀 홀로 서지 않는
  항목은 rejected · decision_json.reason='rekey' 로 닫는다.

### BE-9. 시험 · 변이(B23 · B27 · B29)
- 새 시험 — `tests/test_req_brief.py` 8 · `tests/test_persona_rev.py` 8(모름 셋은 매개) · `tests/test_rekey.py` 20. 고친 시험 — test_brief(E0 줄 수
  9 → 10, E3 의 옛 줄 꼴 둘) · test_roster(compact 끔 응답 꼴, 게이트웨이 → 동결의 판 대조).
- 옛 코드에서 붉은지(9bd5f48 의 스크래치 사본에 새 시험을 얹어) — test_req_brief 7/8 · test_persona_rev 5/8 이 붉고, 초록 넷은 지킴 시험이다(요구
  인용 없는 원자의 바이트 · E7 이 모름을 바뀜으로 적지 않는 셋 — 옛 코드는 접두를 아예 붙이지 않는다). test_rekey 는 rekey 모듈이 없어 모으기에서
  깨지고, 사본에 빈 자리 모듈을 두면 20/20 이 붉다(등록부 'open' ≠ 'superseded' · prev_status None · 철회한 별칭으로 접음 · 감사 0 · 6홉 DID NOT
  RAISE 등 까닭대로). 고친 옛 시험 여섯(test_brief 4 · test_roster 2)도 옛 코드에서 붉다.
- 변이 31(스크래치 사본, 바이트코드 끔, 변이마다 되돌리고 __pycache__ 를 지운다) — 31/31 잡힘. B23 일곱(E0 줄 · 여유 차례 · 미측정을 0 으로 ·
  0 을 여유로 · 치수 없는 요구 줄 · 저장 보정 · requirement_ref 열) · B27 여섯(판번호 · compact · 정규화의 역할 · 의견 사본 · 접두 · 모름을 바뀜으로)
  · B29 열여덟(prev_status · reject 재키 · unmerge 재키 · revoke · revoke 의 사람 · 시각 · append · 사람 별칭 · 재현 확인 · 재병합 · 패턴 · 큐 ·
  감사 · 자동 승계 행 고르기 · 옛 행 닫기 · 다시 열기 · 다른 대상 표지 · 철회한 별칭 정규화 · 계면 원장 재키). 사본은 끝에 작업 트리와 바이트가 같다.
- 전체 시험(공유 잠금 아래) — 첫 판(1de79d1)은 3,539 통과 · 실패 1 이었다. rr_findings 읽기 가드(test_review_findings)가 새 읽기
  `rekey.touching_findings` 를 잡았다 — 카드 대조 원자를 일부러 읽는 자리라 까닭과 함께 면제 목록에 넣었다(7630563, 별칭은 소유자 단위의 키
  사실이고 다시 병합할 때 등록부가 대상의 흐름대로 거른다). 다시 돈 판(7630563) — 3,540 통과 · xfail 4 · 실패 0(rc 0, 11분 58초 — 앞 판 3,504 에
  새 시험 36). ruff — 바꾼 파일은 깨끗하다.
- 하지 않은 것 — 배선 리허설(`tests/synth/rehearsal_d.py`)은 프로세스를 띄우는 일이라 돌리지 않았다(카드 대조 사슬은 바꾸지 않았다 — 보정이 같은
  정규화를 지나는 카드 대조 원자에 걸리는 것 말고). 서비스 재기동 · push · 병합은 없다.

### BE-10. 남긴 것(열린 항목)
- rr_states 의 요구 신호 — 동결이 요구를 대조하지 않고 요구 편집이 상태를 다시 세지 않는다(포털 106 줄의 다른 칸). E0 · E3 · 저장 보정은 BE-1
  대로 돌지만 SnapshotPage 여유 표 · R-007 · character_seed(`requirement_tight`)는 비어 있다.
- 코드가 세운 병합(어휘 재계산 code:vocab_recompute · 자동 승계 code:pair_correspondence)은 등록부를 접지 않는다 — 재키를 사람 조작에만 걸었다
  (rr_audit 은 사람 행위 한정이다). 접게 하려면 감사 없이 맞추기만 부르는 길을 더한다(inherit_ckeys 를 파이프라인에 걸 때 함께).
- 사람 확정 계면 별칭(근접 별칭 확정 → source human · 대표 병합)의 길 — 생기면 그 확정도 맞추기를 불러야 revoke 가 거둘 것이 생긴다.
- 원자가 지워져 빈 등록부 행(패널 재제출 · 사람 finding 삭제)을 닫는 일.
- nightly 스탬프의 persona_rev 가 대상 전체를 대표하지 못한다(첫 좌석의 판) — rk01 가지가 nightly.py 를 마친 뒤.
- E7 의 AIDataHub 회수 경로 판정 — 보내는 쪽(M4)이 레코드에 persona_rev 를 실을 때.
- E7 앱 DB 경로의 상태 필터(포털 152 줄의 다른 칸, B27 글 밖 — 이번에 보고 적는다) — `_seat_memory_line` 의 SQL 은 의견이 올린 finding 의
  status(dismissed · rejected_in_panel · superseded 제외)도 recall_eligible 도 보지 않는다. AIDataHub 경로만 제외 태그를 건다
  (RECALL_EXCLUDE_TAGS). 계획 P5 (12) 의 'E7 은 그 좌석의 dismissed · rejected_in_panel · superseded 발췌를 싣지 않는다' 를 지키는 시험도 없다.
- 화면(화면 세션) — SnapshotPage 여유 표(포털 B34 · 106 ④) · 별칭 철회 버튼 · 되돌리기 결과(rekey 요약 · kept_human)를 보이기.
- 포털 plan 문면(포털 세션) — E0 예시의 맨 이름 → `[req:]` 토큰 · persona_rev 꼴 · rekey 의 키 단위 해석과 merge_key 짝 · revoke_iface_alias 결정.

## 검토 후속 10-31 — rekey 가지의 확인된 일곱 건(가지 `wt1031/bl-risk-engine`, 0ee9fb1 위, 2026-10-31)

> 이 가지(0ee9fb1)를 반대 검토가 일곱 건으로 짚었고 전부 재현됐다(검토 탐침을 이 가지의 스크래치 사본에서 그대로 돌렸다). 건마다 옛 코드
> (0ee9fb1 사본)에서 붉고 고친 코드에서 푸른 시험을 `tests/test_rekey.py` 에 더했다. 포털 문서와 rk01 가지의 파일(ra_client · nightly ·
> main · config)은 건드리지 않았다.

### BE-11. 접힌 등록부 행의 주체는 그 행 키의 주체다(검토 1)
- 무엇이 틀렸나 — 병합 행의 subject_key 는 대표 원자(근거 등급 → 제기 좌석 수 → 최신 → id)의 동결 주체였다. merge_key Y → X 로 T1 의 key(X)
  행이 [F1(Y) · F2(X)] 로 접히면 대표가 F1 일 때 행의 주체가 Y 가 되는데, 회수(`brief._subject_path` · E5 주체 경로 · precedents)는 지금 원장으로
  푼 X 로만 찾고 옛 key(Y) 행은 superseded 라 T1 이 회수에서 빠졌다. 병합이 '같은 파트' 라고 말한 그 파트의 위험을 회수에서 지웠다.
- 고친 것 — `registry._folded_subject`. 원자가 별칭으로 들어온(접힌) 행만 주체를 다시 정한다 — 동결 키가 그 행 키인 원자가 있으면 그 원자의
  주체(같은 키면 같은 주체다), 없으면(원자가 전부 별칭으로 들어왔다 — T2) 대표 주체를 지금 원장으로 다시 센 값(`rekey.current_subject` — 원장
  별칭은 그 주체로 행 키를 셌다). 접히지 않은 행은 바이트 그대로다.
- 고르지 않은 것 — 모든 행의 주체를 지금 원장으로 다시 세기. 코드가 세운 병합(어휘 재계산 · 자동 승계)은 별칭 없이 ckey 만 이어(BE-10) 그런
  행의 주체도 회수에서 빠지지만, 접힘과 무관한 행의 바이트가 바뀌는 다른 빈칸이다.
- 남는 것 — 사람 별칭(cluster_merge)으로만 들어온 원자뿐인 행은 그 별칭 끝 키의 주체를 이 대상의 원자로는 모른다 — 대표 주체를 지금 원장으로
  센 값이고 종전과 같은 결과다.

### BE-12. 별칭 사슬로만 닿는 대상도 다시 병합하고, 맞춘 뒤 앞 키의 사슬을 본다(검토 2)
- 무엇이 틀렸나 — 영향 대상은 주체가 그 ckey 를 담은 원자의 대상뿐이었다. 사람 별칭 key(Q) → key(Y) 로 Y 의 클러스터에 닿는 대상 TQ 는 Y 가
  X 에 접혀 key(Q) 의 풀이가 바뀌어도 다시 병합되지 않아 열린 행 둘 · 판정 후보 2 · priors(n_raised 4 — 새로 세면 3)가 다음 병합까지 남았다.
  되돌릴 때도 같은 구멍으로 그 사이에 접힌 채 다시 병합된 TQ 가 그대로 접혀 있었다.
- 고친 것 — `rekey.upstream_keys`. 별칭이 바뀔 수 있는 키(동결 키 · 재매핑 끝 자리, BE-16)와 살아 있는 별칭 사슬이 그 키를 지나는 앞 키
  전부다(소유자 단위, `ix_rr_cluster_alias_owner_new`). 맞추기 전에 한 번 센다 — 앞 키에서 그 키에 닿기까지의 별칭은 이 맞추기가 건드리지
  않는 키의 것이라 바꾸기 전과 뒤의 집합이 같다(검토가 권한 '바꾸기 전 또는 뒤에 살아 있던 별칭의 역폐포' 와 같은 집합이다). 풀이가
  바뀐 키를 동결 키로 가진 원자의 대상(`touching_findings(cluster_keys=…)` — 이미 rr_findings 읽기 가드의 면제 목록에 있는 같은 함수)도
  다시 병합하고, 패턴 재해석 · 무효 큐 닫기도 같은 키 집합을 본다. 감사의 old/new_cluster_keys 에 풀이가 바뀐 앞 키를, findings_n ·
  targets_n 에 별칭으로 닿은 원자 · 대상을 더한다.
- 덧붙인 것(검토 4 의 '마지막 별칭 집합으로 점검' 갈래) — `_check_chains`. 맞춘 뒤 그 키 집합의 사슬이 5홉 안이고 순환하지 않는지 본다.
  세울 때의 점검(`add_cluster_alias`)은 새 별칭 뒤만 세어, key(Q) → key(Y) 위에 key(Y) → key(X)(뒤로 사람 4홉)를 세우면 Q 의 사슬이 6홉이 돼도
  지나갔다(Q 는 5홉에서 끊긴 중간 키로 풀린다). 별칭으로 닿는 대상을 이제 곧바로 다시 병합하므로 그 틀린 풀이가 등록부에 실린다 — 그래서
  함께 넣었다. 409 면 원장 변경까지 되돌아간다.
- 넣지 않은 것 — 사람이 세우는 별칭(PUT /registry/{k}/merge · cluster_merge 큐 결정)의 같은 앞 키 점검. 키 전파 밖의 길이라 열린 항목으로 둔다.

### BE-13. 접혀 닫힌 행은 주의 D 이고, 클러스터를 세는 곳이 건너뛴다(검토 3)
- 무엇이 틀렸나 — `_close_vacated_rows` 가 status · superseded_by 만 쓰고 attention 은 닫을 때의 A 로 남겼다. 다음 병합은 그 행을 다시 세지
  않아(그 대상의 클러스터가 아니다) 고쳐지지 않는다. 상태를 보지 않는 카드 대조 쪽 소비처가 같은 원자를 두 번 셌다 — 종합 입력(A 둘) ·
  마감 판(clusters 2 · A 2) · 쟁점 후보(같은 닻 둘 → 고르기 candidates 2) · 보고서. 판정 후보(open · verified 만)는 1 이었다. 이 가지 전에는
  merge_key 가 접지 않아 원자가 한 번씩만 섰다 — 이 가지의 접힘이 만든 이중 셈이다.
- 고친 것 — 닫을 때 attention 을 `attention_of({'status': 'superseded'})`(D)로 쓴다. `registry.vacated(row, target)` = 같은 대상 표지의
  superseded(그 대상 안에서 접혀 닫힌 행 — §4.8 의 T′# 닫힘은 아니다)를 두고 클러스터를 세는 곳이 건너뛴다 — `closure.cell_counts` 의 등록부 수
  (clusters · attention · card_fail_claimed) · `issues.candidates` · 종합의 `domain_rows` 와 보고서 `build_report`(주의 A · B 는 등급으로도 빠지지만
  개선 상위 · 영역 쪽 C/D · 메커니즘 표는 등급을 보지 않는다). `_write_registry_row` 의 다시 열기도 같은 판정을 쓴다.
- 쟁점 칸(issue_id · issue_state)은 지우지 않았다(검토가 함께 권한 것과 다르다) — rr_issues 의 거울이라 `issues._sync_registry` 가 쟁점 고르기마다
  닻 키의 행에 다시 쓴다. 지우면 다음 고르기가 되살리고 그 사이에는 거울이 rr_issues 와 어긋난다. 소비처가 그 행을 건너뛰므로 세지 않는다.
- 건드리지 않은 것 — 상태 열을 함께 적는 줄(쟁점 브리프 I8 · 통합 보고서 표)은 그 행을 `superseded` 로 보인다(세는 것이 아니라 이력이다).
  종합 `_risk_rows`(target_rows 의 A · B 고르기)는 D 로 이미 빠져 따로 거르지 않았다. 등록부 조회(GET …/registry · risk_get_registry)는 계약대로
  전 행이다.

### BE-14. 별칭 맞추기는 두 걸음이다 — 다 거두고 세운다(검토 4)
- 무엇이 틀렸나 — 동결 키를 정렬 차례로 돌며 키마다 거두고 세웠다. 뒤로 사람 4홉인 X 에 middle → X · leaf → middle 을 병합한 뒤 middle 을
  풀면, key(leaf) → key(middle) 을 세울 때 같은 맞추기가 곧 거둘 key(middle) → key(X) 를 세어 6홉 409 가 났다 — key(leaf) 가 먼저 정렬될 때만
  (키 해시 차례). 이름만 바꾼 같은 모양은 지나갔다.
- 고친 것 — `_plan`(할 일을 센다, 쓰지 않는다) → 거둘 원장 별칭을 다 거둔다 → 세운다 → 맞춘 뒤 점검(BE-12). 세우는 동안의 별칭은 마지막
  별칭 집합의 부분이라 세울 때의 홉 · 순환 점검이 거짓으로 걸리지 않는다. 시험은 두 이름 차례를 다 본다.

### BE-15. 쓰는 병합은 읽기부터 한 트랜잭션이다(검토 5)
- 무엇이 틀렸나 — `registry.merge` 가 원자 · 별칭을 트랜잭션 밖에서 읽고 행을 센 뒤 쓰기만 트랜잭션에 넣었다. 저장소 락은 쿼리마다 풀리므로
  그 사이에 다른 요청의 키 전파(별칭 · 접힘 · 커밋)가 끝날 수 있고, 낡은 행이 그 접힘을 덮어 닫힌 옛 행을 다시 열었다(이 가지의 다시 열기
  규칙이 같은 대상 표지를 다시 연다) — 별칭은 살아 있는데 등록부는 접히지 않은 채 다음 병합까지 남았다. 트랜잭션 밖 계산은 이 가지 전부터
  있었고 PUT /registry/{k}/merge 도 같은 경합이었다 — 키 전파의 모든 길이 이제 그 경합에 닿는다. 트랜잭션 밖에서 병합을 부르는 곳은
  `chain.py`(러너 스레드)와 사람 finding 만들기 · 고치기 · 지우기 라우트다.
- 고친 것 — `merge(persist=True)` 가 `store.tx()` 를 맨 앞에서 연다(본체는 `_merge`). RLock · BEGIN IMMEDIATE 가 병합과 키 전파를 줄 세운다.
  안쪽 쓰기 tx 는 재진입이라 그대로고 `persist=False`(비교 보기)는 트랜잭션이 없다.
- 대가 — 병합이 세는 동안에도 저장소 락을 쥔다(종전에는 쓰는 동안만). 헬스는 `try_lock` 이라 기다리지 않지만 큰 cells 대상을 병합하는 동안
  다른 요청의 저장소 접근은 그만큼 기다린다.
- 시험 — 바깥 트랜잭션을 여는 순간 '락을 먼저 잡은 다른 요청' 이 키 병합을 끝까지 돌려 커밋하게 store.tx 를 감싼다. 옛 코드는 그 순간이
  읽기 뒤라 낡은 행을 쓰고, 고친 코드는 읽기 앞이라 새 원장으로 센다.

### BE-16. 재매핑 별칭(taxonomy_major)의 끝에 원장 별칭을 이어 붙인다(검토 6)
- 무엇이 틀렸나 — 맞추기가 원장이 세우지 않은 별칭을 전부 사람 별칭으로 보아 건너뛰었다(kept_human). 재매핑(`learning.apply_remap` —
  key(unclassified, Y) → key(drop_stress, Y))을 거친 원자는 어떤 파트 병합도 따라가지 않았다 — 같은 파트의 재매핑 안 된 원자는 따라갔다.
- 고친 것 — `_landing`. 동결 키에서 재매핑 별칭을 따라가 그 끝(원장 별칭이 설 자리)을 찾는다. 한 걸음마다 근거의 to_detail 로 다음 키를
  같은 식으로 다시 만들어 보고(`_reproduce` — 빈 값 두 꼴), 못 만들면 건너뛴다(skipped `remap_not_reproducible` — 다른 식의 키를 지어 잇지
  않는다, 동결 키를 못 만들 때와 같은 규칙). 끝 자리에서 원장이 원하는 키는 끝의 세부와 지금 주체로 센 키다 — 그 자리에 원장 별칭을 세우거나
  거둔다. 재매핑 별칭 자체는 건드리지 않는다. 새 별칭 근거에 via(그 원자의 동결 키)를 싣는다.
- 사람 결정이 이기는 것은 cluster_merge · dim_rename 이다. dim_rename 은 `dim:` 주체의 이름 바꾸기라 ck 주체를 다시 세는 키 전파에 닿지
  않는다(그 별칭을 짓는 코드도 아직 없다) — 이어 붙이는 대상에 넣지 않았다.

### BE-17. 재검토 표기는 세운 대상의 근거가 남아 있을 때만이다(검토 7)
- 무엇이 틀렸나 — `_flag_escalations` 는 표기를 세우기만 했다. merge_key 가 T1 의 key(X) 지지를 늘려 T9 의 사람 기각 행에 표기를 세운 뒤
  unmerge_key 로 지지가 돌아와도 표기가 남아, 없어진 근거를 들어 재검토를 청했다.
- 고친 것 — `_retract_escalations`. 병합마다 이 대상이 세운 표기(by_target = 이 대상) 가운데 이 대상의 지금 행으로 더 서지 않는 것(그 클러스터가
  없어졌거나 더 강하지 않다)을 다시 본다. 다른 대상의 지금 행(접혀 닫힌 행 빼고)이 여전히 더 강하면 그 대상으로 옮기고 — 표기는 한 칸이라
  뒤 대상이 앞 대상의 표기를 덮어 썼으니 덮은 대상의 근거가 없어졌다고 앞 대상의 근거까지 지우지 않는다 — 없으면 끈다.
- 계획과의 관계 — 계획 §4.7.1 은 '사람이 status 를 다시 확정하면 꺼진다' 만 적었다. 코드가 거두는 것은 표기의 근거(by_target 의 행)가 없어졌을
  때뿐이고 사람 확정으로 꺼지는 것은 그대로다. 왕복만이 아니라 원자 삭제 · 패널 재제출로 약해진 대상에도 같은 규칙이다.
- 고르지 않은 것 — 키 전파가 제 병합이 세운 표기를 적어 두었다가 되돌릴 때 거두기. 왕복 사이에 다른 병합이 같은 표기를 다시 세웠는지 가를
  수 없다.

### BE-18. 시험 · 변이 · 전체 시험(검토 후속)
- 새 시험 — test_rekey 11(매개 둘 포함, 20 → 31). 옛 코드(0ee9fb1 사본)에서 10 이 까닭대로 붉다(접힌 행 주체 Y · 대상 TQ 빠짐 · 앞 키 6홉 통과 ·
  키 차례 409 · 재매핑 kept_human · 재매핑 건너뛰기 없음 · 주의 A · 다시 열림 · 표기 남음 · 접힌 행으로 옮김). 초록 하나는 지킴 시험이다(middle 이
  먼저 정렬되는 차례 — 옛 코드도 지나갔다).
- 변이 21(스크래치 사본, 바이트코드 끔, 변이마다 되돌리고 __pycache__ 를 지운다) — 21/21 잡힘. 주체 셋(그 줄 · 동결 키 원자 · 지금 원장
  폴백) · 대상 넷(별칭 대상 · 앞 키 집합 · 사슬 점검 · 패턴 · 큐 키 집합) · 닫힌 행 다섯(D · 마감 판 · 쟁점 후보 · 종합 행 · 보고서) · 두 걸음(키마다
  거두고 세우는 한 걸음으로 되돌린 변이 — 그 차례 시험만 붉다) · 한 트랜잭션 · 재매핑 둘(사람 별칭 취급 · 재현 확인 없음) · 표기 넷(거두기 ·
  옮기기 · 더 강한지 · 접힌 행 건너뛰기) · 다시 열기 판정. 사본은 끝에 작업 트리와 바이트가 같다.
- 회수 시험(BE-11)의 diff 는 생산자 경로로 뜬다(make_project → make_snapshot 둘 → make_diff) — 그 뒤 스냅샷의 한 파트를 원장 merge_key 로
  X 에 이어 노드가 X 로 풀린다. 첫 판에서는 rr_diffs 행을 손으로 써서 씨앗 출처 래칫(`tests/rr/test_fixture_provenance` — 손 INSERT
  rr_diffs 8 → 9)에 걸렸다. 커밋은 건마다 나눴고(일곱 + 문서), 커밋마다 그 커밋의 새 시험이 앞 커밋의 코드에서 붉고(차례 지킴 하나 빼고)
  그 커밋에서 test_rekey · rr_findings 읽기 가드 · ruff 가 푸른 것을 스크래치 사본으로 봤다.
- 전체 시험(공유 잠금 아래) — 첫 판 3,550 통과 · 실패 1(위 래칫) · xfail 4(rc 1, 12분 57초). 고친 판 — 3,551 통과 · xfail 4 ·
  실패 0(rc 0, 12분 04초 — 앞 판 3,540 에 새 시험 11). ruff — 바꾼 파일은 깨끗하다. 배선 리허설(`tests/synth/rehearsal_d.py`)은 프로세스를
  띄우는 일이라 돌리지 않았다. 서비스 재기동 · push · 병합은 없다.

## RK-01 RA 보내는 쪽(가지 `wt1031/rk01`, main 9bd5f48 위, 2026-10-31)

> 포털 세션에서 사용자가 답한 결정이다 — 포털 `docs/request-1027/review-07-hwax-risk.md` 3절 D-1 의 (가), 기록은 같은 폴더 context-notes
> 'RK-01 D-1' 절. 지식 그래프 op 는 박스 쓰기 PAT(`HWAXRISK_PORTAL_PAT_RW`, OB-18) 하나로 RA 에 쓰고, 누가 했는지는 앱 DB 의 owner_sub 가
> 맡는다(정본 plan.md 원칙 10 · §5.3.5 · §8.2.7 그대로). 종합 보고서는 지금처럼 사람 이름이다(포털 챗 PAT 길 — FU-D17). 짓는 길은 검토의
> '권하는 길 2 · 3' 이다.

### RS-1. 보내는 쪽은 ra_client 한 곳이고 박스 쓰기 PAT 만 잡는다
- `ra_client.RaSender` 를 `main.py` 가 `RiskRunner(external_sync_send=…)` 로 꽂는다 — sync_loop 가 60초마다 `nightly.retry_external_sync` 로
  부른다(야간 nightly_loop 는 여전히 비어 있다 — 검토 0절 '요청서 밖' 셋째 줄, 이 일과 따로다). 쓰기 4종의 이름은 앱에서 ra_client.py 에만
  나오고(`test_no_write_tools` 가 새로 본다), 배선한 main.py 에도 쓰기 키 글자가 없다. 사람의 등록 PAT(_user_credentials · 복호)와 읽기 PAT 는
  ra_client 가 잡지 않는다 — 정적 검사 하나와, 게이트웨이 대역이 실제로 나간 Authorization 이 쓰기 PAT 뿐인지 보는 시험이 지킨다.
- 키는 틱마다 secrets.env 에서 다시 읽는다 — 이 앱의 다른 선택 키(backup_key 등)와 같은 꼴이다. 키가 없으면 `off_reason()` 이
  `credential_missing:HWAXRISK_PORTAL_PAT_RW` 를 주고 retry_external_sync 는 아무것도 부르지 않는다(상태도 바꾸지 않는다). 넣으면 재기동 없이
  다음 주기부터 나간다. 기동 로그에 켜짐 · 꺼짐 한 줄을 남긴다(검토 '권하는 길 3' 마지막 줄).
- 호스트 불일치(origin.json)로는 막지 않았다 — 이 앱의 다른 박스 자격(읽기 PAT · 서비스 PAT)도 런타임에서 그것으로 막지 않는다. 옮겨 온
  PAT 가 새 박스에서 무효면 게이트웨이 401 → `unauthorized` 로 멈추고 그렇게 말한다.

### RS-2. 번역 — op 넷이 RA 도구 호출 몇 개가 되나
- `merge_object` risk_finding(라벨 상태) — finding 이 실린 **등록부 행**이 RA 객체다(plan §5.3.1 — 단위는 클러스터, code `<target_key>#<cluster_key>`).
  행은 registry.merge 와 같은 규칙으로 고른다(별칭을 거친 대표 키 · improvement 는 `.imp` 행). rr_id_map 에 id 가 있으면 get_object → 병합 →
  update_object, 없으면 code 로 create_object(같은 code 면 RA 가 있는 것을 돌려준다 — created:false 면 그 속성에 병합).
- `merge_object` design_trait(X태그 승격) — value = code = `char:<axis>:<value>`, 속성 axis · token · status. 어휘 객체라 주인이 따로 없다.
- `link` verified_by|refuted_by — dst 는 근거 `inc:<RA 객체 id>` 가 RA 사고 · 시험일 때만이다(get_object 로 incident 다음 test_run 을 본다).
  글 근거 · 다른 축의 객체면 잇지 않는다 — concerns → part 를 RA 에 part 가 있을 때만 잇는 정본 규칙(§5.3.5 ⑥)과 같은 자세이고, 사고 · 시험
  객체를 만들지 않는다. 그 op 는 큐에서 빼되 채널에 `skipped_n` · `last_skip` 을 남기고 요약 글이 'RA 에 잇지 않은 것 n건' 을 말한다. 큐에
  남겨 두면 사람 라벨(대부분 글 근거)마다 그 대상의 RA 채널이 영영 막힌다.
- `link` exhibits — src 는 과제(project, code = 과제 id, 속성 없음), dst 는 design_trait. 관계 속성은 op 의 props 그대로(값 없는 칸은 뺀다 —
  사람 라벨의 match_score 는 None 이다).
- 원칙 9 의 투영 범위 표기(owner · visibility)와 되짚을 열쇠(cluster_key · portal_registry_key)만 앱이 쥔 속성으로 싣는다. risk_finding 의
  나머지 투영 속성(severity · mechanism 등 enum)은 패널 때 쓰는 쪽(M4 쓰기 순서 ⑥)의 몫으로 남겼다 — 지금 실으면 박스 온톨로지가 계획표와
  어긋날 때(drift) 라벨 하나가 enum 검증에 걸려 대상의 채널을 멈춘다.

### RS-3. RA 의 실제 계약에 맞췄다 — 래퍼가 틀려 있었다
- dev 의 RA 사본(3ece194) mcp_server · ai/agent_tools 를 읽어 보니 래퍼의 인자 넷이 RA 와 달랐다 — get_object 에 type 이 없었고(RA 는
  `type` · `id` 둘 다 필수, 축이 다르면 없는 것으로 답한다), update_object · add_object_alias 는 `object_id` 대신 id · entity_id, get_subgraph 는
  `entity_id` 대신 id 를 보냈다. 런타임에서 부르는 곳이 없어 드러나지 않았다. 고쳤고 인자 표를 시험으로 고정했다. cae00 의 RA 판은 보지
  못했다 — 박스 확인 줄에 `tools/list` 대조를 넣었다.
- 도구 이름은 게이트웨이의 호출 전용 별칭 `reportarchive_<이름>` 이다 — 맨 이름은 다른 백엔드가 같은 이름을 내면 둘 다 접두가 붙어 바뀐다
  (노출 이름이 제3자 앱의 가동 여부로 뒤집힌다 — 게이트웨이 bdd05b2). 무인 배경 잡이 그 뒤집힘에 흔들리지 않게 했다. 계약 목록(RA_*_TOOLS)은
  맨 이름 그대로다.
- RA 는 실패를 성공 답 안의 `{"error": …}` 로 준다(RA MCP 가 HTTP 상태를 글로만 넘긴다) — 래퍼가 그것을 성공으로 읽지 않게 했다.

### RS-4. value 에 code 를 꼬리로 단다(plan §5.3.1 의 꼴을 따르지 않은 까닭)
- RA 의 resolve_existing 은 code 가 맞는 객체가 없으면 **value(대소문자 무시) · 별칭**으로 찾는다. 계획표의 risk_finding value
  `<과제코드>@<mechanism>.<detail>@<cluster_key>` 는 같은 과제의 다른 대상(같은 클러스터 내용) · 같은 과제 코드를 쓰는 다른 주인과 겹친다 —
  그러면 create_object 가 남의 객체를 created:false 로 돌려주고, 그대로 병합하면 남의 객체를 고친다. 과제 value(계획은 '과제 표시명')도 같다.
  그래서 value 는 `<계획의 머리>@<code>` 이고(≤255), 돌려받은 객체의 code 가 우리 code 가 아니면 쓰지 않고 `value_collision` 으로 멈춘다.
  과제 표시명은 description 에 싣는다. 포털 정본 표를 고칠지는 포털 몫이다(돌려주는 글에 적었다).

### RS-5. 가린 값을 되쓰지 않는다
- 게이트웨이(HG-20)는 나가는 모든 백엔드 답에서 owner 칸 · 메일 꼴 · 계정 꼴을 `[가림:…]` 로 바꾼다. update_object 는 통째 교체라 get_object 로
  읽은 속성을 그대로 병합해 보내면 가린 글이 RA 원본(owner = 과제 주인 이메일)을 덮는다. upsert_props 는 가린 칸을 patch(앱이 쥔 값)가 채우면
  그 값을 쓰고, 못 채우는 칸이 남으면 보내지 않고 `masked_readback` 으로 멈춘다(그 칸 이름을 남긴다). 바뀔 것이 없으면 부르지 않는다.
  risk_finding 의 owner 는 앱이 쥔 칸이라 늘 앱 값으로 되돌아간다.

### RS-6. 보류는 대상 단위 — 비공개면 부르지도 않는다
- 상태기계(§5.5.3)가 대상 단위라 그 대상의 op 가 가리키는 과제 가운데 하나라도 조직 공개가 아니면 MCP 세션조차 열지 않고 `withheld` 로 둔다
  (op 는 큐에 그대로). 과제 축은 정본상 비공개에서도 만들 수 있지만 대상의 op 를 나눠 보내는 상태가 없어 함께 보류했다 — 조직 공개로 풀면
  (`routes._release_withheld`) 쌓인 op 가 순서대로 나간다. 폐기된 과제 · 없는 대상은 `rejected` 로 멈춘다(폐기 뒤에 RA 객체를 새로 만들지 않게).
- queue_sync_ops 가 withheld 를 pending 으로 되돌리던 것을 막았다 — 정본 '새 패널 종료' 행이 'withheld 면 withheld 유지' 다. 그동안 withheld 를
  세우는 코드가 없어 드러나지 않았다. sync_badge 도 withheld(n) 를 센다(정본 표기).

### RS-7. 실패 — 큐에 남기고 까닭을 적는다
- 한 대상의 op 는 순서대로 보내고 처음 실패한 자리에서 멈춘다 — 나간 것만 큐에서 빼고, 실패한 op 와 뒤의 op 는 남는다(뒤의 연결이 앞의 객체에
  기대므로). last_error 는 `<낱말>: <글>` 이고 sync_summary 의 reason 이 그 낱말이다(검토 '권하는 길 3' 의 갈래 — credential_missing · read_only
  · forbidden · transient · withheld — 에 unauthorized · tool_missing · ontology_missing · masked_readback · value_collision · rejected 를 더했다).
- `transient`(전송 실패 · 5xx · 408/425/429 · 기한 초과 · 게이트웨이의 백엔드 불통 · 사람별 위임 실패)만 지수 백오프로 다시 보낸다(8회 뒤
  unavailable — 종전 규칙). 그 틱의 남은 대상은 미룬다(deferred) — 죽은 RA 를 대상마다 기한(120초)까지 두드리면 같은 sync_loop 의 PAT 폐기 대조가
  밀린다. 나머지는 곧바로 unavailable 이고 사람이 고친 뒤 '재동기' 로 되살린다(검토 그대로). RA 의 'Internal server error' · 'HTTP 5xx' 글은
  transient, '시스템 관리자' 는 forbidden, '알 수 없는 타입' 은 ontology_missing(부트스트랩 전), 토큰 · 인증 글은 unauthorized, 그 밖의 RA 거절은
  rejected 다. 게이트웨이 거절은 글 머리(read_only: · forbidden: · unknown tool:)와 외부 연결 미등록 글로 가르고 그 밖은 transient 다.
- 상태 전이는 retry_external_sync 가 한 트랜잭션으로 한다(`_apply_outcome`) — 네트워크 호출은 트랜잭션 밖이다(저장소 락은 RLock 이라 tx 가
  쥐는 동안 다른 스레드가 선다).

### RS-8. retry_external_sync 의 전송기 계약을 넓혔다(종전 꼴은 그대로)
- bool 을 돌려주는 전송기는 종전대로 읽는다. dict 를 돌려주면 done · skipped · hold · error · retry · off 를 본다. 전송기에 `channels` 가 있으면
  그 채널만 보낸다 — RaSender 는 ra 만이고 AIDataHub 대기는 세기만 한다(unwired, 요약은 sender_unwired 그대로 — M4). `off_reason()` 이 있으면
  틱 앞에서 한 번 묻는다. 결과의 새 칸(held · unwired · deferred)은 0 이 아닐 때만 실어 종전 답 꼴(시험 · 야간 단계 보고)이 바뀌지 않는다.

### RS-9. 하지 않은 것 · 남긴 것
- 패널 때 쓰는 투영(project · snapshot · diff · expert · assessment · risk_finding 의 나머지 속성 · 패널 보고서 update_report_draft — 쓰기 순서
  ①~⑧)과 AIDataHub 반입은 M4 다. 그 op 를 만드는 쪽이 아직 없다.
- 야간 nightly_loop · run_nightly 배선은 이 일 밖이다(검토 0절). 화면이 reason 낱말을 그리는 일은 프런트 세션 몫이다(요약 글 `message` 는 늘 있다).
- cae00 사람 몫은 checklist 2장 'RK-01 cae00 확인' 이다 — 핵심은 쓰기 PAT 주인이 RA 시스템 관리자인지다(RA 온톨로지 쓰기가 관리자 전용).

### RS-10. 시험 · 변이 · 전체 시험
- 새 시험 22 — `tests/test_ra_sender.py` 15건(부른 것을 적는 게이트웨이 · RA 대역 — RA 의 실제 인자 · 별칭만 받는 도구 이름 · 관리자만 쓰기 ·
  성공 답 안의 error · owner · 메일 가림을 흉내 낸다. 진짜 RA 는 부르지 않는다) · `test_external_sync.py` 3(보류 유지 · 상태별 reason · 래퍼 인자 표)
  · `test_nightly.py` 2(전송기 결과 적용 · 꺼짐 · 미룸 · 채널) · `test_no_write_tools.py` 2(쓰기 4종 이름은 ra_client 하나 · 보내는 쪽은 쓰기 PAT
  만 — 이 둘은 앞 판에서도 통과하는 경계 가드다). 기대를 고친 것 — 요약 시험 하나(sender_unwired → credential_missing, 이름도 바꿨다) ·
  upsert_props · 자격 없는 래퍼(새 서명) · test_mcp_entry · test_mcp_tools(RA reason) · test_runner(러너에 RaSender 가 꽂혔다).
- 앞 판(9bd5f48)에 새 시험을 얹으면 test_ra_sender 15건이 오류(RaSender 없음), test_external_sync 6건 · test_nightly 2건 · test_runner ·
  test_mcp_entry · test_mcp_tools 각 1건이 실패한다.
- 변이(스크래치 사본, 바이트코드 끔) 23개가 다 잡혔다 — 맨 이름 호출 · update_object 의 id · 가림 검사 없음 · code 대조 없음 · 비공개도 보냄 ·
  읽기 PAT 로 켜짐 · 재시도 뒤 틱 계속 · 쌓으면 보류 풀림 · 멈춤도 백오프 · 근거 축 안 봄 · 원본 표 id 안 적음 · 관리자 거절 못 알아봄 · 요약
  늘 미배선 · 러너에 안 꽂음 · 빈 속성 실음 · 건너뜀 안 셈 · 멈추면 나간 것도 남김 · 낡은 사상 안 풂 · .imp 안 붙임 · 읽기 전용 거절 못 알아봄 ·
  5xx 안 다시 보냄 · 별칭 없이 행 고름 · 꺼짐을 알리지 않고 부름. 마지막 판(아래 고침 뒤)에서 다시 돌려 23/23 이다.
- 전체 시험(공유 잠금 아래 한 번, 12분 1초) — 3,525 통과 · 실패 1 · xfail 4(앞 판 3,504 에 새 시험 22). 실패는
  `test_review_findings::test_every_panel_path_reader_of_rr_findings_filters_card_review_findings` 였다 — `_finding_object` 의 rr_findings 조회가
  카드 대조 원자를 거르지 않았다(M2 #20 가드). 라벨 op 를 낸 쪽(metrics._finding_row)과 같은 거름을 달았고, 가드 파일과 바꾼 시험 파일들을 다시
  돌려 243 통과다. 전체 시험은 다시 돌리지 않았다(한 번 — 지시).
- 하지 않은 것 — 서비스 · 인스턴스 기동 · 정지, push · 병합, 진짜 RA 호출. 배선 리허설(rehearsal_d)은 카드 대조 사슬을 바꾸지 않아 돌리지 않았다.

## RK-01 반대 검토 고침(가지 `wt1031/rk01`, 2026-10-31)

> 반대 검토(스크래치 재현 R1 ~ R9 · 전체 시험 한 번)가 낸 지적 아홉을 고쳤다. 사용자 결정 10-31 D-1 (가)는 그대로다 — 지식 그래프 op 는
> 박스 쓰기 PAT 하나, 누가 했는지는 앱 DB 의 owner_sub, 종합 보고서는 사람 이름(포털 챗 PAT 길). 거두기(RS-18)만 사용자 결정으로 남겼다.

### RS-11. 전체 시험 실패 1 — 카드 대조 거름 자리
- RS-10 이 test_review_findings 를 맞추려고 `_finding_object` 에 카드 대조 거름을 달았는데, 거름 자리를 등록표와 견주는 `test_registry_cells`
  가 새 자리를 몰라 전체 시험이 실패한 채 커밋됐다(고친 파일만 다시 돌렸다). 등록표에 한 줄을 더했다(까닭 — metrics._finding_row 와 같은 거름).

### RS-12. 라벨마다 병합 op 가 다르고, status 는 보낼 때의 등록부 값이다(지적 — 큐의 같은 꼴 버림이 되돌림을 삼킨다)
- 재현 — 보류 중 확정 → 반증 → 확정이면 셋째 병합 op 가 첫째와 바이트까지 같아 큐에 들어가지 않고(queue_sync_ops), RA 는 dismissed · 앱은
  verified 인 채 요약은 sent 였다. 보내는 틱 도중에 뒤집혀도 complete_sync_ops 가 내용으로 함께 지워 같은 일이 난다.
- 둘을 함께 했다. ① 검토가 권한 대로 병합 op 머리에 label_id 를 싣는다(metrics._queue_ra_status — props 밖이라 RA 로 가는 값은 그대로다).
  라벨마다 op 가 달라 큐가 줄이지 않고, 보내는 도중에 붙은 라벨의 op 를 complete 가 함께 지우지 않는다. ② 보내는 쪽은 risk_finding 의 status 를
  op 에 적힌 라벨 때의 값이 아니라 **보낼 때의 등록부 값**으로 싣는다(원칙 3 — 투영은 정본을 따라간다).
- 둘 다인 까닭 — ② 만이면 같은 대상의 op 를 보내는 동안(complete 전) 붙은 라벨의 op 가 아직 큐에 있는 같은 꼴 op 에 줄어든 뒤 함께 지워져,
  앞서 읽은 값이 RA 에 남는다(처음엔 ② 만 넣었다가 전체 시험 전에 찾았다 — 시험 'in flight'). ① 만이면 op 하나의 영구 거절을 따로 두고
  재동기로 늦게 보낼 때(RS-13) 옛 라벨 값이 그 사이 나간 새 값을 덮는다(시험 'sent late'). 큐의 같은 꼴 버림 · 내용으로 지우는 complete 는
  그대로 뒀다(성격 태그 op 는 멱등이라 줄이는 편이 낫다). op 의 props.status 는 라벨 때의 값으로 남는다(기록).
- 따라 생긴 차이 — 사람이 등록부 status 를 바꾸는 길(PUT registry status)은 op 를 쌓지 않는데, 그 값이 다음 라벨 op 가 나갈 때 함께 실린다.
  사람 status 만 바뀐 경우의 투영은 그대로 M4 몫이다.
- 같은 결함이 AIDataHub 의 status:* 재부착 op(metrics._queue_retag)와 가시성 재부착 op(routes._queue_visibility_retag)에도 있다 — 보내는 쪽이
  없어(M4) 지금은 나가는 것이 없다. AIDataHub 보내는 쪽을 지을 때 같은 규칙(보낼 때의 값)을 쓴다.

### RS-13. op 하나의 영구 거절은 따로 두고 나머지를 보낸다(지적 — 독 op 하나가 대상의 RA 채널을 영영 막는다)
- 재현 — RA 에 값은 같고 code 가 없는 design_trait 이 있으면 승격 op 가 value_collision 으로 멈추고, 뒤에 쌓인 상관없는 라벨 병합 · 연결이
  영영 나가지 않았다. 재동기해도 같은 op 에서 다시 멈췄다(RS-2 가 스스로 적은 위험이다).
- 가름 — 채널 전체(unauthorized · read_only · forbidden · tool_missing · ontology_missing, 게이트웨이의 그 밖 4xx(끝점) · JSON-RPC 오류(인자 꼴 —
  판이 다른 RA))는 종전처럼 그 대상을 멈춘다. op 하나에만 걸린 것(RA 의 성공 답 안 거절 — 관계 축 제약 · enum · 길이 · 닫힌 축,
  value_collision · masked_readback · 꼴이 틀린 op · 잇는 사이 사라진 객체)은 그 op 만 `dead_ops`({op, error, at})로 옮기고 다음 op 로 간다.
  같은 꼴이 다시 따로 두어지면 까닭만 새로 적는다. 큐가 비면 done 이다. 따로 둘 때는 이번에 거절된 op 만 큐에서 뺀다(예전에 따로 둔 것과
  같은 꼴이어도 새로 쌓인 op 는 남는다).
- 뒤 op 가 앞 op 에 기대는 경우(성격 태그 병합이 따로 두어진 뒤의 exhibits)는 뒤 op 도 같은 거절을 받아 따로 두어진다 — 남의 객체는 고치지 않는다.
- masked_readback 은 RS-5 에서 '멈춘다' 였다 — 그 객체의 속성에만 걸린 것이라 따로 두는 쪽으로 옮겼다(검토의 '채널 전체만 멈춘다' 를 따랐다).
- 재동기 — 멈춘 채널을 되살리고 따로 둔 op 를 큐 **앞**으로 되돌린다. 따로 둔 op 는 큐에 남은 어느 op 보다 앞선 것이라(순서대로 보내고 걸린
  자리에서 뺀다) 앞에 둬야 원래 순서다. 같은 꼴은 한 번만.
- 요약 — `dead_ops` 건수 칸을 더했다(두 채널). reason 은 상태 그대로(sent 등)이고 글 끝에 '따로 둔 op n건 — 마지막 까닭' 을 단다. 화면은 이
  칸을 경고로 그린다(프런트 세션 몫).

### RS-14. 가시성 · 폐기를 호출마다 본다(지적 — 틱 머리에서 한 번만 봤다)
- RaClient 에 `gate`(부를 때마다 묻는 문)를 더하고, 보내는 쪽이 '그 대상의 과제가 아직 조직 공개이고 폐기되지 않았나' 를 준다(가벼운 SELECT).
  닫히면 그 호출부터 부르지 않는다 — 조회도 부르지 않는다(쓰기에만 문을 달면 다음 op 의 조회가 나간다, 변이로 확인했다). 그때까지 보낸 op 는
  큐에서 빼고 남은 op 는 보류(비공개) 또는 멈춤(폐기)이다.
- 닫힌 직후 다시 열렸으면(그 사이 되돌렸다) 보류하지 않는다 — 보류는 공개 토글(_release_withheld)만 풀어 그대로 두면 영영 멈춘다.

### RS-15. 멈춤 · 따로 둠을 로그에 남긴다(지적 — 채널 전체 실패도 한 줄 없었다)
- retry_external_sync 가 이번 틱에 unavailable 이 된 대상(사유 낱말별)과 따로 둔 op(낱말별)를 세어 틱 끝에 경고 한 줄씩 남긴다
  (`hwax_risk.nightly`). 이미 멈춘 대상은 due 가 아니라 다시 찍히지 않는다. 폐기된 과제에 남은 op 도 'rejected' 멈춤으로 한 번 찍힌다.
- 검토 재현 R6 은 로거 이름을 `app.*` 으로 걸러 앱의 `hwax_risk.*` 를 보지 못했다 — 결론(로그 없음)은 맞았다. 새 시험은 `hwax_risk` 로 본다.
- /api/me 의 box.reasons 에는 싣지 않았다 — box_assessment 는 설정 파일의 판정이라 러너 상태를 섞으면 결이 달라진다. 운영자 몫은 로그와 대상
  화면이다.

### RS-16. 한 틱의 크기(지적 — 상한이 없었다)
- RaSender 가 `tick_max_targets = 50` · `tick_budget_s = 30.0` 을 갖고 retry_external_sync 가 대상 사이마다 그것과 러너의 정지 신호
  (`should_stop` — runner 가 `_stop.is_set` 을 넘긴다)를 본다. 넘거나 멈추면 남은 대상은 상태 그대로 미룬다(deferred). 첫 대상은 늘 보낸다
  (예산이 0 이어도 나아간다).
- 값의 까닭 — sync_loop 주기 60초 · PAT 폐기 대조 60초. 한 대상은 세션 둘 + 호출 1 ~ 4 라 정상이면 1초 안팎이고 한 틱에 수십 대상이
  나간다. 설정 손잡이로 빼지 않았다(요청 밖이다).

### RS-17. 박스 PAT 클라이언트는 보고서를 쓰지 않는다(지적 — 결정의 보고서 쪽에 가드가 없었다)
- RaClient 계약에서 보고서 도구(get_report · update_report_draft)와 그 메서드를 뺐다 — 부르는 런타임 코드가 없었다. 정본 plan §5.3.5 ⑧(패널
  보고서 tags 병합을 서비스 키로)은 사용자 결정 10-31(보고서는 사람 이름)과 어긋나므로 M4 에서 사람 이름의 길로 다시 정한다.
- 가드 — 보고서 쓰기 도구의 이름이 앱 어디에도 없는지, 박스 클라이언트가 보고서 도구를 tool_not_contracted 로 거절하는지(test_no_write_tools).
  검토의 변이(synth.py · ra_client.py 에 박스 클라이언트로 보고서 초안 갱신)를 잡는다.

### RS-18. 거두기 — 사용자 결정 대기(지적 — 되돌리는 길이 없다)
- 조직 공개를 비공개로 되돌리거나 폐기 · 이양해도 이미 나간 RA 객체(과제 설명의 과제 이름 · risk_finding 의 owner · visibility=org · status ·
  exhibits)가 그대로 남는다 — 원칙 9 가 그만큼 지켜지지 않는다. 고를 것은 (a) 보류를 건너뛰는 거두기 op, (b) 나간 과제의 비공개 전환을 막기,
  (c) 그대로 두고 원칙을 고치기다 — checklist 6장 'RK-01 거두기'. 고르지 않고 동작은 그대로 뒀다.
- 결정과 무관한 것만 했다 — 폐기 보고서의 RA 층 글이 'status=retracted 표기만 남는다' 였지만 그 표기를 하는 코드도 부트스트랩 status enum 의
  retracted 값도 없다. 실제 동작(그대로 남는다 · 나간 객체 수 · 새로 보내지 않는다)을 말하게 고쳤다(reason `not_retracted`, `objects`).
- 같은 보고서의 AIDataHub 층 글('빈 UPSERT 만 가능')도 하는 코드가 없다(보내는 쪽 M4) — 이 일 밖이라 그대로 뒀다.

### RS-19. cae00 확인 ③ 을 고쳤다(지적 — 별칭은 tools/list 에 없다)
- RS-3 의 '박스 확인 줄에 tools/list 대조' 는 틀렸다 — 게이트웨이는 호출 전용 별칭을 tools/list · /tools-map 에 올리지 않는다(게이트웨이
  gateway.py 의 alias_route 주석 · test_aliases_do_not_change_the_visible_catalogue). checklist 2장 ③ 을 '박스 쓰기 PAT 로
  reportarchive_list_object_types 를 직접 부른다 · 인자는 맨 이름 항목의 inputSchema · /tools-map 의 reportarchive 도구' 로 고치고,
  ⑥(첫 동기 주기 뒤 멈춤 경고가 없는지)을 더했다.

### RS-20. 시험 · 변이 · 전체 시험
- 고치기 전 판(5956e88)에 새 시험을 얹으면 20건이 실패한다(test_external_sync 는 새 함수가 없어 모음 오류, 거름 가드는 그 판의 시험 파일로
  실패). 채널 멈춤 둘(404 · JSON-RPC 오류)은 지켜야 할 종전 동작이라 그 판에서도 통과하고 변이가 지킨다. 검토 재현 R2 · R2b · R4 · R5 는 고친 뒤 실패한다(결함이 없어졌다). R3 · R9 는 그대로(거두기 결정 대기),
  R1(교차 과제 diff)은 이번 지적 목록에 없어 손대지 않았다.
- 새 시험 — test_ra_sender 15 · test_external_sync 1 · test_nightly 1 · test_no_write_tools 1 · test_project_patch 1(폐기 글). 고친 기대 —
  test_ra_sender 4 · test_external_sync 2(계약 · 요약 꼴) · test_metrics 1(병합 op 의 label_id) · test_registry_cells 1(등록표).
- 변이(스크래치 사본, 바이트코드 끔) 25개가 다 잡혔다 — 거름 자리 · op 값 status · label_id 없음 · 따로 두지 않음 · 재동기가 안 되돌림 · 빈 큐
  정리 · 예전 것과 같은 꼴 지움 · RA 거절 멈춤 · JSON-RPC 오류를 op 하나로 · 값 겹침 멈춤 · 가린 칸 멈춤 · 문 없음 · 쓰기에만 문 · 다시 열려도
  보류 · 경고 없음 · 대상마다 경고 · 수 상한 · 예산 · 정지 신호 · 러너 배선 · 첫 대상 · 보고서 계약 · 보고서 메서드 · 폐기 글 · 폐기 수.
- 전체 시험(공유 잠금 아래 한 번, HEAD f227b19 + 이 문서들, 12분 38초) — 3,545 통과 · 실패 0 · xfail 4(rc 0). 앞 판의 3,525 통과 ·
  실패 1(거름 가드)에 새 시험 19. ruff — 바꾼 파일은 깨끗하다.
- 하지 않은 것 — 서비스 · 인스턴스 기동 · 정지, push · 병합, 진짜 RA 호출.

## RK-01 거두기(가지 `wt1031/rk01`, 39a2dab 위, 2026-10-31)

> RK-01 반대 검토 뒤 포털 세션에서 사용자가 고른 답이다 — checklist 6장 'RK-01 거두기' 의 **(가)**(사용자 결정 10-31). 박스 서비스 계정으로
> RA 에 나간 객체를 가진 과제가 비공개 · 폐기 · 이양되면 보류를 건너뛰는 '거두기' op 를 쌓아 RA 객체를 다시 표기한다 — visibility=private, 또는
> 그것을 못 하면 status · 설명 칸을 비운다(RA 객체 모델이 받는 쪽으로). (b) 비공개 전환 막기 · (c) 그대로 두기는 고르지 않았다.

### RS-21. RA 가 허락하는 것 — dev 사본(3ece194)을 읽기만 했다
- MCP 온톨로지 쓰기는 넷뿐이다 — create_object · update_object · add_object_alias · link_objects(ReportArchive `mcp_server/server.py`
  1823 ~ 1912, 실행 화이트리스트 `backend/app/modules/ai/routes.py` 712 ~ 717). 라우트가 `require_system_admin`(728)이라 시스템 관리자의
  토큰만 쓴다(박스 확인 ② 그대로). 객체를 지우거나 연결을 끊는 MCP 도구는 없다(`remove_rows` 는 보고서 표의 줄이다).
- `update_object`(server.py 1858 ~ 1878)는 object_id · value · code · description · properties 를 받고 None 인 칸은 뺀다. 실행부
  `_w_update_object`(`backend/app/ai/agent_tools.py` 849 ~ 869)는 그 넷만 넘긴다(859 ~ 862). 스키마 `EntityUpdate`
  (`backend/app/modules/entities/schemas.py` 382 ~ 395)에 status(active · deprecated, 389)가 있지만 MCP 로는 닿지 않는다 — 객체를 숨기는
  deprecated 도 못 한다.
- `update_entity`(`backend/app/modules/entities/services.py` 859 ~ 898) — value 를 바꾸면 같은 축 값 겹침(대소문자 무시)을 보고
  `이미 같은 값이 있습니다`(878), description 은 빈 글도 그대로 적고(883 ~ 884), properties 는 축 속성 정의로 검증해 통째로 바꾼다(894).
  `_validate_props`(739 ~ 765)는 정의 밖 칸을 거절하고(746 ~ 748) 빈 값(None · '' · [])을 저장하지 않는다(752 ~ 756).
- 엔티티에 공개 범위 열은 없다(`entities/models.py` Entity 190 ~ 249, 상태 enum 52 ~ 57). visibility 는 이 앱의 부트스트랩이 네 record 축에 단
  속성이다(`backend/scripts/bootstrap_ra_ontology.py` `_VISIBILITY` 52, risk_finding 176). 과제(project)는 RA 기존 축이라 그 속성이 없고,
  risk_finding status enum 에 retracted 가 없다(169 ~ 172).
- 그래서 — risk_finding 은 visibility=private 로 다시 표기하고 속성을 통째로 바꿔 owner · status 를 뺀다(되짚을 열쇠 cluster_key ·
  portal_registry_key 만 남긴다). 과제는 표기할 칸이 없어 설명(과제 이름)을 비운다. value 는 비울 수 없어(최소 1자) 과제 코드 · 메커니즘을 뺀
  `비공개@<code>` 로 바꾼다 — 투영이 채운 칸을 RA 가 받는 만큼 비웠다. 객체 자체와 연결은 남는다. status enum 에 retracted 를 더하지는
  않았다 — 결정이 '칸을 비운다' 이고, enum 을 바꾸면 박스 부트스트랩(시스템 관리자)을 다시 돌려야 한다.
- 계획 정본 §5.2.6 4층의 `update_object(status='retracted')` 는 이 RA 가 받지 않는다(MCP 가 상태를 넘기지 않고 enum 에 값도 없다) — 정본
  글은 포털 몫이라 돌려주는 글에 적었다.

### RS-22. op 꼴 — 무엇을 쓸지는 op 가 아니라 보낼 때의 정본 범위다
- op 는 `{op: retract, reason: private|purged|owner|org, kind: project|registry, portal_id, project_id, by}` 다. reason · by 는 기록(감사 ·
  셈)이고 꼴은 보낼 때 과제의 상태로 고른다 — 조직 공개가 아니거나 폐기면 거둔 꼴, 조직 공개면 나간 꼴. RS-12 의 '보낼 때의 등록부 값' 과
  같은 자세다(원칙 3). 그래서 큐가 같은 꼴을 한 번만 쌓아도, 비공개 → 공개 → 비공개를 틱 사이에 오가도 마지막에 나간 op 가 정본을 따른다.
  보내는 도중 닫혔다 다시 열린 경우는 비공개 도중 시험의 끝이 본다(거두지 않고 나간 꼴 그대로).
- 이양(owner)과 다시 공개(org)를 같은 op 로 했다 — 둘 다 '정본 범위로 다시 표기' 라 꼴을 고르는 길이 같다. 셈(retract_pending ·
  retract_failed · 폐기 보고서)은 거두기(private · purged)만 센다 — 다시 표기를 거두기 대기로 세면 다시 연 과제의 화면이 '거두기 대기' 를 말한다.
- 다시 공개는 지금 거둔 꼴인 객체(대상의 retracted)만 다시 표기한다 — 지시의 '다시 조직 공개면 보통 보내기가 이어진다' 에 더해, 거둔 값 ·
  설명 · visibility 가 정본(조직 공개)과 어긋난 채 남지 않게 했다. 보류된 보낼 op 는 그 앞에서 순서대로 나간다.

### RS-23. 보류 · 폐기 멈춤을 건너뛴다 — 큐 순서는 지킨다
- RaSender 는 닫힌 과제여도 큐에 거두기 op 가 있으면 MCP 세션을 열고 거두기 op 만 큐 순서대로 보낸다(보낼 op 는 보류 · 멈춤 그대로). 열린
  과제면 큐 순서대로 다 보내므로 거두기 op 는 같은 대상의 앞에 쌓인 보낼 op 다음에 나간다. 큐 끝에 붙이는 것은 queue_sync_ops 다.
- 호출마다 보는 문(RS-14)은 거두기 op 에 걸지 않는다 — 걸면 비공개가 된 순간 거두기 자신이 막힌다. 보낼 op 가 문에 걸리면 그 뒤로는 거두기
  op 만 보내고(종전에는 그 자리에서 끝냈다) 끝에 보류 · 멈춤을 단다(그 사이 다시 열렸으면 종전처럼 보류하지 않는다).
- retry_external_sync 는 보류 채널을 집지 않았다(공개 토글만 푼다) — 거두기 op 가 있으면 집는다(next_at 는 보지 않는다 — 보류에는 백오프가
  없다). 보류 대상이 거두기 op 만 남았다가 다 보내면 done 이다(종전 _settle 은 pending 만 옮겨 '대기 0건인 보류' 가 남았을 것이다).
- 채널 전체가 막히는 실패(관리자 아님 · 토큰 · 도구 없음 · 온톨로지 없음)에는 거두기도 다른 op 처럼 멈추고 재동기를 기다린다 — 같은 거절을
  틱마다 두드리지 않는다. 그동안 요약 · 폐기 보고서가 그 사유 낱말을 단다.

### RS-24. 무엇을 거두나
- 과제 객체와 등록부 risk_finding — rr_id_map(정본)과 원본 표의 ra_entity_id(조회 편의용 중복)를 둘 다 본다(쌓을 때 · 보낼 때). 공개 범위를
  지키는 일이라 사상 한 칸이 어긋났다고 나간 객체를 남겨 두지 않는다. risk_finding op 는 그 행의 대상 큐에, 과제 객체 op 는 과제의 첫
  대상(만든 순서 — 대상이 늘어도 바뀌지 않는다)에 둔다.
- 성격 태그(design_trait)는 거두지 않는다 — 과제를 가로지르는 통제 어휘라 다른 과제도 같은 객체를 잇는다. 과제 → 태그 exhibits 와
  verified_by · refuted_by 연결(속성 label_id · match_score · source)도 남는다 — 끊는 도구가 없다. 연결 속성은 빈 속성으로 link_objects 를
  다시 부르면 비울 수 있지만(RA add_relation 이 넘긴 속성으로 바꾼다) 연결이 남아 얻는 것이 적어 하지 않았다. 폐기 보고서 글이 그렇게 말한다.

### RS-25. 남의 객체를 쓰지 않는다(id_mismatch)
- 거둔 꼴은 value · properties 를 통째로 바꾸므로 사상된 id 가 남의 객체면 그 객체를 망친다. 반출 · 들여오기가 rr_id_map · ra_entity_id 를
  싣는다(export 의 rr_id_map) — 다른 박스의 RA id 가 이 박스의 RA 에서 다른 객체를 가리킬 수 있다. get_object 는 code 를 주지 않으므로 값
  (label)의 꼬리로 본다 — 이 앱은 값 끝에 늘 `@<code>` 를 단다(RS-4). 게이트웨이 가림(HG-20 — 메일 · 계정 꼴, gateway.py `_EMAIL_RX` ·
  `_ACCOUNT_RX`)은 값 머리에 걸려도 code 꼬리(`diff:<hex>#<cluster>` · 과제 id)는 그 꼴이 아니라 남는다.
- 종전 보내는 길(_ensure)에도 같은 빈틈이 있다 — 사상된 id 로 get_object 가 되면 code 를 보지 않고 병합한다. 그 길은 병합이라 피해가 작고 이
  일 밖이라 그대로 뒀다(RS-29).

### RS-26. 비공개로 돌리는 순간의 경합 — 뒤따라 쌓기
- 비공개로 돌리는 순간 RA 에 만드는 호출(create_object)이 나가 있으면, 라우트가 거두기 op 를 쌓을 때 그 객체의 id 는 아직 적히지 않았다
  (_ensure 가 답을 받은 뒤 적는다). 그대로면 그 객체만 visibility=org 로 남는다. 보내는 쪽이 결과를 적는 트랜잭션(record_retracts)에서 닫힌
  과제의 객체 가운데 거둔 꼴도 아니고 거두기 op 도 따로 둔 것도 없는 것에 거두기 op 를 뒤따라 쌓는다 — 다음 틱에 보류를 건너뛰어 거둔다.
  따로 둔 것은 다시 쌓지 않는다(재동기를 기다린다 — 쌓으면 틱마다 같은 거절을 두드린다). 행위자가 없어 감사 행은 과제 소유자로 적는다.
- 시험을 짜다 스스로 찾았다 — 종전 비공개 도중 시험 둘(남은 op 는 link 하나)이 뒤따른 거두기 op 를 하나 더 보게 되어 기대를 고쳤다.

### RS-27. 셈 · 폐기 보고서 · 감사
- 대상 RA 채널에 `retracted`(지금 거둔 꼴인 객체 → 시각)를 둔다(있을 때만 — 빈 꼴의 바이트는 그대로다). 나간 꼴로 다시 표기하면 지운다.
  요약은 retracted · retract_pending · retract_failed · retract_reasons 를 RA 채널에 늘 싣는다(화면 계약). 글은 '거두기(비공개 · 폐기) — RA 에서
  거둔 객체 n개 · 대기 n건 · 못 거둔 것 n건(까닭 n)'. 보류 글의 '대기 n건' 은 보류된 op 수다(거두기 op 는 보류되지 않는다).
- 폐기는 요청 안에서 RA 를 부르지 않는다 — 앱의 외부 쓰기는 sync_loop 한 곳이다(정본 §5.2.6 도 '202 응답 후 러너가 순서대로 돈다').
  그래서 폐기 응답의 RA 층은 대기(retract_pending)이고, 거두기 결과를 적을 때마다 purge_report_json 의 RA 층을 다시 짓는다
  (refresh_purge_report — 객체마다 대기 · 못 거둠(까닭) · 거둠 · 쌓이지 않음을 큐 · 따로 둠 · retracted 에서 다시 센다). 읽는 길은 늘리지 않았다
  — 폐기 응답, 저장된 보고서, 대상 요약이 말한다.
- rr_audit 는 사람 행위 한정이지만 거두기는 사람(비공개 · 폐기 · 이양을 한 사람)의 행위를 동기 주기가 마저 하는 것이라 그 사람을 행위자로
  거두기 op 마다 한 행 남긴다 — `ra.retract`(거둔 꼴) · `ra.remark`(나간 꼴), 채널 rest(그 행위가 들어온 입구 — DDL CHECK 가 넷뿐이다), 범위는
  과제 · 등록부(subject `<target_key>#<cluster_key>`), after 에 RA id · 꼴 · 결과(retracted · remarked · unchanged · absent · failed 와 까닭).
  쌓을 때가 아니라 RA 에 닿았거나 받지 않았을 때 남긴다 — 쌓은 사실은 그 행위의 감사 행(project.mcp_visibility · purge · transfer)이 이미 있다.

### RS-28. routes.py 에서 바꾼 곳(병렬 가지 `wt1031/bl-risk-api` 가 같은 파일을 고친다)
- `patch_project` — `if visibility_changed:` 안, `_queue_visibility_retag` 다음 한 줄(응답 `resynced.ra_retract_ops`).
- `transfer_project` — TRANSFER_DERIVED 갱신 다음 · 감사 앞 한 줄과 응답의 `ra_retract_ops`.
- `purge_project` — RA 층 주석과 `not_retracted` 항목을 `queue_retracts` 한 줄과 `ra_client.purge_ra_layer` 로 바꿨고, 쓰지 않게 된
  `_ra_projection_count`(이 가지 a070e14 가 넣었다)를 지웠다. 그 가지의 routes 덩어리(get_project_audit 뒤 · add_source · 잡 · 사람 finding ·
  큐레이션)와 겹치는 줄은 없다.

### RS-29. 하지 않은 것 · 남긴 것
- RA 객체 · 연결 지우기, 엔티티 상태(deprecated) — RA MCP 에 없다(RS-21). RA 리포는 손대지 않는다.
- 화면의 거두기 칸(retracted · retract_pending · retract_failed · retract_reasons, 폐기 보고서 RA 층) — 프런트 세션 몫.
- 포털 정본 §5.1 원칙 9 · §5.2.6 4층 글 — 포털 몫(status='retracted' 는 RA 가 받지 않는다, 거두기는 다시 표기다).
- AIDataHub 쪽 회수(가시성 태그 재부착 · 빈 UPSERT)는 보내는 쪽이 없어 그대로다(M4).
- 종전 보내는 길(_ensure)의 사상 id 대조(RS-25), RA 에는 생겼지만 답을 잃어 id 를 모르는 객체(code 로 찾으려면 search_objects 계약을 넓혀야
  한다) — 따로 할 일로 남긴다.

### RS-30. 시험 · 변이 · 전체 시험
- 새 시험 15 — test_ra_sender 12(게이트웨이 · RA 대역의 update_object 를 RA 그대로 고쳤다 — 넘긴 칸만 · 값 겹침 · 빈 값 빼기) ·
  test_external_sync 2 · test_nightly 1. 고쳐 쓴 것 — test_project_patch 의 폐기 보고서(not_retracted → retract_pending · nothing_sent). 기대를
  고친 것 넷 — 비공개 도중 시험 둘(뒤따른 거두기 op, RS-26) · 요약 칸 · PATCH 응답 칸.
- 고치기 전 판(39a2dab)에 새 시험 파일 넷을 얹으면 20건이 실패한다(새 15 · 고쳐 쓴 1 · 기대를 고친 4). 고친 판에서는 다 통과한다.
- 변이(스크래치 사본, 바이트코드 끔) 31개가 다 잡혔다 — 보류 건너뜀 · 문 · 보류 채널 집기 · id 대조 · 거둔 꼴의 통째 교체 · value · 설명 ·
  꼴을 op 로 고름 · 다시 공개 · 이양 · 비공개 · 폐기의 쌓기 · 감사 · 보고서 다시 짓기 · 뒤따라 쌓기 · 따로 둔 것 다시 쌓기 · 보류 정리 · 셈의
  까닭 거름 · 값 겹침 낱말 · 빈 설명 · 같은 꼴 한 번 · 바뀐 것 없으면 부르지 않음 · 원본 표 폴백 · 보고서 낱말 · 다시 표기 뒤 표시 지움 ·
  행위자 폴백 · 거둔 뒤 보류 · 큐 순서 · 이양에 과제 객체 · 요약 칸 · 결과 적기.
- 전체 시험(공유 잠금 아래 한 번, 코드 HEAD 74f695f, 11분 59초) — 3,560 통과 · 실패 0 · xfail 4(rc 0). 앞 판의 3,545 에 새 시험 15. ruff — 바꾼
  파일은 깨끗하다.
- 하지 않은 것 — 서비스 · 인스턴스 기동 · 정지, push · 병합, 진짜 RA 호출(RA 는 dev 사본을 읽기만 했다). 배선 리허설(rehearsal_d)은 카드 대조
  사슬을 바꾸지 않아 돌리지 않았다.

## RK-01 거두기 반대 검토 고침(가지 `wt1031/rk01`, 0a461b3 위, 2026-10-31)

> 거두기(RS-21 ~ RS-30)의 반대 검토(스크래치 재현 R1 · R1b · R2 · R2b · R2c · R2d · R3 · R4 · R5 · R6)가 낸 지적 여섯을 고쳤다. 사용자 결정 10-31 (가)는
> 그대로다 — 박스 서비스 계정으로 RA 에 나간 객체를 가진 과제가 비공개 · 폐기 · 이양되면 보류를 건너뛰는 거두기 op 로 RA 객체를 다시 표기한다.
> 재현 열 개는 고치기 전 판(0a461b3)에서 모두 결함을 보였다(결함을 단언하는 일곱은 통과, 나머지 셋은 인쇄만).

### RS-31. 폐기된 과제의 보낼 op 는 버린다 — 대상을 멈추지 않는다(지적 1 — 폐기가 쌓은 거두기가 멈춘 큐에 갇힌다, RS-6 · RS-23 일부 뒤집음)
- 재현 — 조직 공개 과제의 대상에 보낼 op 가 있는데 동기 틱 도중 폐기되면 (c) 그 대상을 보내는 도중이면 다음 호출이 문에 걸리고 틱 끝의 `_closed` 가
  rejected 로 멈췄다. (d) 그 대상에 닿기 전이면 스냅숏에 보낼 op 뿐이라 곧바로 rejected 로 멈췄다(창은 한 틱 예산 30초까지). (a) 만드는 호출
  도중이면 뒤따른 거두기가 같은 결과가 멈춘 대상에 쌓였다. 어느 쪽이든 폐기가 쌓은(또는 뒤따른) 거두기 op 가 unavailable 큐에 갇혀 사람이
  재동기하기 전까지 RA 에 visibility=org · owner · status · 과제 이름이 남았고, 폐기 보고서는 까닭 rejected('RA 가 이 op 를 받지 않았다' — RA 는
  거절하지 않았다)를 말했다. 재동기해도 거두기만 나가고 대상은 다시 멈췄다(R2b).
- 고른 것 — 폐기된 과제의 보낼 op 는 대상을 멈추지 않고 큐에서 뺀다. 'RA 에 잇지 않은 것'(skipped_n · last_skip)으로 센다 — 낱말 `project_purged`
  (SKIP_TEXT). 폐기는 되돌리는 길이 없고(행을 지우지 않는 tombstone, 폐기 과제는 고칠 수 없다) '폐기 뒤에는 새로 보내지 않는다' 라 큐에 남겨 둘
  까닭이 없다. 멈추지 않으니 폐기가 나중에 쌓은 거두기 op 도 보통 대기처럼 다음 동기 주기에 집힌다. 스냅숏에 보낼 op 만 있으면 MCP 세션도 열지
  않고 뺀다(부르지 않는다).
- 검토가 든 다른 두 길을 고르지 않은 까닭 — (ㄱ) 따로 둔 op(dead_ops, 까닭 purged)는 '받지 않아 따로 둔 op' 경고 칸 · 틱 경고 줄 · '재동기'
  안내를 단다(RA 가 거절한 것이 아니고 고칠 것도 없다). (ㄴ) 멈춘 채로 폐기 과제의 거두기 op 만 집기는 멈춘 까닭을 글로 가려야 한다 — rejected
  낱말은 게이트웨이 거절 · JSON-RPC 오류에도 쓴다(그 멈춤은 재동기를 기다려야 한다, RS-23).
- 대상 · 과제 행이 없으면 종전처럼 rejected 로 멈춘다(글에서 '폐기됐다' 를 뺐다). 폐기로는 이제 멈추지 않으니 틱 경고 줄에도 나오지 않는다 —
  RS-15 의 '폐기된 과제에 남은 op 도 rejected 멈춤으로 한 번 찍힌다' 는 더는 맞지 않다. 요약은 끝(sent)에 'RA 에 잇지 않은 것 n건 — 과제가 폐기됐다'
  를 단다.
- 따라 고친 시험 둘 — 폐기 도중(`test_a_purge_mid_send_stops_the_next_call` — 다음 호출을 하지 않는 것은 그대로, 대상은 멈추지 않고 뒤따른 거두기가
  다음 틱에 나간다) · 폐기 보고서(남은 보낼 op 는 버려지고 대상은 done).

### RS-32. 열린 과제에 거둔 꼴로 남은 객체는 다시 표기한다 — 뒤따라 쌓기(지적 2 — 다시 열기가 나가는 중인 거두기를 놓친다, RS-26 넓힘)
- 재현 — 비공개 거두기가 나가는 도중(`_retract_op` 가 과제 행을 읽은 뒤 · 그 대상의 결과를 적기 전) 소유자가 다시 조직 공개로 열면 다시 열기의
  `queue_retracts('org')` 는 대상의 retracted 표만 보는데 그 객체는 아직 적히지 않았다 — 다시 표기 op 가 0 이고 RS-26 의 뒤따라 쌓기는 닫힌 과제만
  봤다. 과제 객체는 값 '비공개@<id>' · 빈 설명으로, risk_finding 은 값이 '비공개@<code>' 인 채 뒤의 라벨 병합이 속성만 되돌려 반쯤 거둔 꼴로 굳었고
  요약은 열린 과제에 '거둔 객체 n개' 를 말했다(실수로 비공개를 누르고 곧바로 되돌리면 생긴다).
- 고른 것 — `record_retracts` 가 결과를 적은 뒤 열린 과제면 그 대상에 거둔 꼴로 남은 객체(retracted · absent)를 보고, 그것을 다룰 거두기 op 가 큐에도
  따로 둔 것에도 없으면 다시 표기 op(reason org)를 쌓는다(`_catch_up_remarks`). 따로 둔 것은 다시 쌓지 않는다(재동기를 기다린다 — 틱마다 같은
  거절을 두드리지 않는다). 거둔 꼴 표시는 그 객체의 op 가 나간 대상(집 대상 — 과제 객체는 첫 대상, risk_finding 은 그 행의 대상)에만 적히므로 그
  대상만 본다 — 열린 과제는 보낼 op 가 잦아 결과마다 과제의 모든 대상을 읽지 않는다.
- 검토의 다른 길(`queue_retracts('org')` 가 대기 중인 거두기의 객체도 집는다)은 고르지 않았다 — 결과를 적을 때 보는 쪽이 어느 순간에 겹쳐도
  잡는다. 그 대신 다시 여는 PATCH 응답의 `ra_retract_ops` 는 그 순간 집은 것만 센다(경합이면 0 — 뒤따라 쌓기가 마저 한다).
- 다시 열기는 RA 에 없던 객체(absent — RS-35)도 집는다 — 표시를 지우는 다시 표기 op 이고 RA 에는 조회만 나간다.

### RS-33. 거두기는 앞선 보내기의 백오프를 물려받지 않는다(지적 3 — 4시간 · 6시간 뒤에야 나갔다)
- 재현 — 앞선 보내기가 RA 불통으로 네 번 실패해 next_at 이 4시간 뒤인 채널에서 비공개로 돌리면 거두기 op 는 쌓였지만 대상이 due 가 아니라 RA 가
  멀쩡해도 백오프가 끝날 때까지 visibility=org · owner 가 남았다(다섯 번부터는 6시간). 여덟 번 실패해 멈춘(unavailable) 채널은 재동기 전까지
  영영이었다. 폐기 보고서는 그동안 '다음 동기 주기에 나간다' 고 말했다.
- 고른 것 — `queue_retracts` 가 거두기(private · purged)를 쌓으면 그 대상을 다음 동기 주기에 집히게 한다(`_due_now`) — pending 이면 next_at 을
  지금으로, transient 로 재시도를 다 써 멈춘 대상은 pending 으로 한 번 되살린다(attempts 는 그대로라 또 실패하면 곧바로 다시 멈춘다). 채널 전체가
  막힌 멈춤(관리자 아님 · 토큰 · 도구 · 온톨로지 · 게이트웨이 거절)은 그대로 재동기를 기다린다(RS-23). 한 번 바로 보내 보고 실패하면 종전
  백오프다 — 틱마다 두드리지 않는다.
- 이양 · 다시 공개(다시 표기)는 당기지 않았다 — 열린 과제라 큐 앞의 보낼 op 를 먼저 보내야 하고, 당기면 실패하던 보낼 op 를 곧바로 다시 두드린다.
  뒤따라 쌓는 op(RS-26 · RS-32)도 당기지 않는다 — 같은 틱의 실패가 방금 백오프를 걸었으면 그것을 따른다.
- 검토의 다른 길(대기 고르기가 거두기 op 가 쌓인 채널의 next_at 을 무시한다)은 고르지 않았다 — RA 가 죽어 있으면 그 길은 틱마다 두드린다.
- 폐기 보고서 글은 기다리는 거두기가 언제 나가는지를 그 채널 상태로 말한다 — 다음 동기 주기(pending · 거두기 op 가 있는 보류) · 재시도 대기
  (pending 이고 next_at 이 지금 뒤 — '다음 시도는 저절로 한다', 까닭은 그 실패의 낱말) · 멈춤(unavailable — 까닭을 고친 뒤 재동기). 종전에는 늘
  '다음 동기 주기에 나가고, 멈춘 채널이면 재동기' 였다.

### RS-34. 거둔 꼴은 앱이 투영한 칸만 뺀다 — RA 에서 따로 단 속성은 둔다(지적 4, RS-21 · RS-22 의 '속성을 통째로 바꿔 열쇠 둘만' 뒤집음)
- 재현 — RA 운영자가 risk_finding 에 단 속성(예 subject_key)이 비공개 전환의 통째 교체로 지워졌고, 다시 열면 앱이 쥔 칸만 돌아와 영영 사라졌다.
  병합(RS-5 · `test_merge_on_an_existing_object_restores_the_masked_owner_and_keeps_other_properties`)은 남이 단 칸을 두는데 거두기만 지웠다. 결정 ·
  RS-21 의 말은 '투영이 채운 칸을 비운다' 였다.
- 고른 것 — 거둔 꼴은 `RETRACT_DROP_KEYS`(앱의 투영이 채운 칸 — 지금 owner · status)를 빼고 visibility=private · 되짚을 열쇠 둘을 쓴다. 나머지
  속성은 읽은 그대로 되쓴다(update_object 가 통째 교체라 보내지 않으면 지워진다 — RA `update_entity` 894). 다만 게이트웨이가 가려 읽힌 칸(HG-20 —
  owner 칸 · 메일 · 계정 꼴)은 되쓸 수 없다 — 가린 글이 원본을 덮는다. 그 칸만 뺀다(공개 범위가 앞선다, 뺀 칸 이름은 감사 행 after 의
  `dropped`). 검토는 가린 칸이 하나라도 있으면 통째 교체로 돌아가라고 했지만, 가린 칸만 빼도 가린 글을 되쓰지 않고 사람 정보가 든 칸이 빠진다 —
  지워지는 남의 칸이 가장 적은 쪽을 골랐다.
- M4 의 패널 투영이 risk_finding 에 칸(부트스트랩의 severity · mechanism · statement 등)을 채우기 시작하면 그 칸을 `RETRACT_DROP_KEYS` 에 더해야
  거둔 뒤 RA 에 남지 않는다. 가드 시험(`test_the_retracted_form_drops_every_property_the_projection_writes`)이 `_registry_object` 의 칸과 라벨 병합의
  status 를 견준다 — 다른 길로 칸을 채우면 그 시험도 넓힌다. 다시 열면 남이 단 칸은 나간 꼴에도 그대로다(병합).
- RA 의 `_validate_props` 는 정의 밖 칸을 거절하므로(RS-21) 남이 단 칸은 그 축의 정의 안이다 — 되써도 거절되지 않는다.

### RS-35. RA 에 이미 없던 객체는 따로 센다 — 셈의 차례를 하나로(지적 5, RS-27 고침)
- 재현 — RA 관리자가 지운 과제 객체(get_object 가 못 찾는다 — outcome absent)도 대상의 retracted 에 들어가 폐기 보고서가 '2개를 거뒀다 — 값을
  바꾸고 …' 라 했다(update_object 는 한 번뿐이고 감사 행은 absent). 따로, 거둔 뒤 다시 받지 않은 객체(retracted 에 남은 키 + 따로 둔 거두기)를
  요약은 거둔 수와 못 거둔 수에 함께 셌고 폐기 보고서는 못 거둔 것 하나로 셌다.
- 고친 것 — 대상 RA 채널에 absent(거두려니 RA 에 없던 객체 → 시각)를 retracted 와 따로 둔다(한 객체는 둘 가운데 하나에만, 나간 꼴로 다시 표기하면
  둘 다 지운다). 요약에 `retract_absent`, 폐기 보고서 RA 층에 `absent` 칸을 더했다(화면 계약은 칸 더하기라 하위 호환). 보고서 글은 실제로 거둔
  꼴로 바꾼 수와 '이미 없어 거둘 것이 없었다' 를 따로 말한다. 보고서 낱말 retracted 는 '다 거뒀거나 RA 에 이미 없다'(남은 것이 없다)다.
- 셈은 한 함수(`_retract_states`)로 — 객체마다 대기 > 못 거둠 > 거둠 > 없음의 차례로 한 처지에만 든다. 요약(`retract_counts`)과 보고서
  (`purge_ra_layer`)가 같은 함수를 쓴다. 요약의 retract_pending · retract_failed 도 op 수가 아니라 객체 수가 됐다(같은 객체에 비공개 · 폐기 거두기
  op 둘이 쌓이면 1).

### RS-36. 뒤따라 쌓은 거두기의 행위자는 과제를 닫거나 연 사람이다(지적 6, RS-26 · RS-27 의 '과제 소유자로 적는다' 뒤집음)
- 재현 — 관리자(risk_admin_roles)가 폐기하는 순간 만드는 호출이 나가 있으면 뒤따른 거두기의 감사 행이 과제 소유자를 actor_verified=1 로 적었다 —
  소유자는 아무것도 하지 않았다. rr_audit 는 사람 행위 한정이다.
- 고친 것 — 뒤따라 쌓는 op 의 by 를 과제를 지금 범위로 만든 사람으로 싣는다(`_closing_actor`) — 폐기면 폐기 보고서의 by(관리자일 수 있다), 비공개 ·
  다시 공개면 mcp_visibility_by(가시성을 마지막으로 바꾼 사람). 모르면(들여온 과제 · 보고서가 없다) 감사 행은 actor 'system' · actor_verified 0
  이다 — 사람이 한 것으로 적지 않는다(owner_sub 칸도 같은 값 — routes `_audit` 처럼 행위자를 적는 칸이다).

### RS-37. routes.py 에서 바꾼 곳
- `purge_project` 의 RA 층 주석 두 줄(1583 ~ 1584 — '폐기 멈춤을 건너뛰어' → '폐기된 과제의 보낼 op 는 버리고 거두기만')뿐이다. 동작은 그대로다. 병렬
  가지 `wt1031/bl-risk-api` 의 덩어리(RS-28)와 겹치지 않는다. nightly.py 는 바꾸지 않았다(대기 고르기 · 결과 적기 그대로).

### RS-38. 하지 않은 것 · 남긴 것
- 보류(withheld)인 채 폐기된 과제 — RA 로 나간 것이 없으면 거두기 op 가 없어 그 대상은 집히지 않고, 요약은 '조직 공개로 바꾸면 대기 n건이 나간다'
  고 말한다(폐기 과제는 바꿀 수 없다). 종전 그대로이고 이번 지적 밖이다.
- 화면의 absent · retract_absent 칸 · 보고서 글의 세 갈래 — 프런트 세션 몫(요약 `message` · 보고서 `detail` 은 늘 사람이 읽을 글이다).
- 검토 재현 R2b(재동기 뒤 다시 멈춤)는 폐기로 멈추지 않게 되어 사라졌다.

### RS-39. 시험 · 변이 · 전체 시험
- 새 시험 15(test_ra_sender) — 폐기 경합 셋(보내는 도중 · 닿기 전 · 만드는 도중), 다시 열기 경합 둘(과제 · risk_finding 거두기 도중), 백오프 둘(4회
  백오프 · 8회 멈춤 되살리기와 거절 멈춤은 그대로), 폐기 보고서 글 하나, 남이 단 속성 둘(두기 · 가린 칸 빼기 · 다시 열면 그대로, 투영 칸 가드),
  RA 에 없던 객체 둘(폐기 · 다시 열면 표시 지움), 셈의 차례 하나, 뒤따른 거두기의 행위자 하나, 다시 표기를 RA 가 받지 않으면 다시 쌓지 않음 하나.
  고쳐 쓴 것 셋 — 폐기 도중 · 폐기 보고서(test_ra_sender) · 요약 칸(test_external_sync — retract_absent).
- 고치기 전 판(0a461b3)에 새 시험 파일을 얹으면 17건이 실패한다(새 14 · 고쳐 쓴 3). 새 시험 하나(다시 표기를 받지 않으면 다시 쌓지 않음)는 그
  판에서도 통과한다 — 이번에 더한 뒤따라 쌓기를 지키는 시험이다. 고친 판에서 다 통과한다.
- 검토 재현 열 개를 고친 판의 스크래치 사본에 얹으면 결함을 단언하는 일곱(R1 · R1b · R2 · R2c · R2d · R3 · R4)이 실패한다(결함이 없어졌다). 인쇄만
  하는 셋은 — R2b 재동기 뒤 done, R5 거둔 1 · 이미 없던 1, R6 뒤따른 거두기의 감사 행위자가 관리자.
- 변이(스크래치 사본, 바이트코드 끔) — 이번 고침의 23개가 다 잡혔다(폐기에 멈춤 · 머리 버림 없음 · 끝 버림 없음 · 버림 안 셈 · 열린 과제 뒤따라
  쌓기 없음 · 따로 둔 것 다시 쌓기 · 다시 표기 행위자 없음 · 당기기 없음 · 8회 멈춤 안 되살림 · 아무 멈춤이나 되살림 · 재시도 대기 없음 · 남이 단
  칸 지움 · 가린 칸 되쓰기 · 빼는 칸 모자람 · 뺀 칸 감사 없음 · 없던 것을 거둔 것으로 · 셈 차례 무시 · 다시 열기가 없던 것을 안 집음 · 보고서가
  없던 것을 거둔 것으로 · 못 거둠을 거둠 아래로 · 뒤따른 거두기 행위자 없음 · 폐기 보고서 by 안 봄 · 모르는 행위자를 검증됨으로). 앞 판(RS-30)의
  변이 31개 가운데 글이 그대로인 24개가 그대로 잡혔고, 이번에 고친 자리라 글이 달라진 일곱은 같은 뜻을 새 글에 넣어 일곱 다 잡혔다.
- 전체 시험(공유 잠금 아래 한 번, 코드 HEAD 1409d86, 12분 40초) — 3,575 통과 · 실패 0 · xfail 4(rc 0). 앞 판의 3,560 에 새 시험 15. ruff — 바꾼
  파일은 깨끗하다.
- 하지 않은 것 — 서비스 · 인스턴스 기동 · 정지, push · 병합, 진짜 RA 호출(RA 는 dev 사본 3ece194 를 읽기만 했다).

## 화면 세션 10-31(가지 `wt1031/riskfe`, main 9bd5f48 위, 2026-10-31)

> 사용자 결정 10-31 A32 (가) — 리스크 앱 화면 일을 한 세션으로 묶는다. 1차 걸음은 B33(과제 등급) · B35(포털 `docs/risk-credentials/frontend-request.md`
> 대로 — 자동 등록 · 박스 까닭 · 반영 요약) · B36(포털 `docs/claude-delib-parity/frontend-request.md` 1 · 2절 — 패널 잡 판단 LLM)이다.
> 백엔드는 고치지 않았다. 확인은 실 백엔드(이 가지의 코드)를 스크래치 하네스로 띄워 브라우저로 눌러 봤다(FE-6).

### FE-1. 과제 등급은 미리 고르지 않는다(B33)
- 폼에 등급(internal · confidential)을 두되 첫 값은 '고르세요'(비활성)다. 정본이 '기본 confidential, 등록 화면에서 필수로 고른다' 이고 서버도 빠지면
  422 `classification_required` 로 거절한다 — 화면이 기본값을 채우면 사람이 고르지 않은 채 반출 경계가 정해진다(동의 체크를 미리 해 두는 것과 같은 일).
  고르기 전에는 '과제 등록' 이 잠기고, 모르면 confidential 을 고르라고 한 줄 적었다.
- 거절은 code 로 그 칸에 붙인다 — `classification_required` → 등급, `E409` → code(이미 있는 과제 코드), `E404` → 앞 과제. 그 밖(401 · 어휘 밖
  `E100`)은 배너다(`api/projectCreate.ts`).
- 과제 행 타입을 서버 열(`routes._project_row`) 그대로 고쳤다 — `adh_scope` 는 보낼 때만의 꼴이고 받을 때는 `adh_team` · `adh_group` 이다.
  그래서 과제 개요의 'AIDataHub 범위' 는 늘 '모름' 이었다. 과제 행에 없는 `external_sync` 를 읽던 머리 배지는 늘 비어 있어 걷었다.

### FE-2. 포털 PAT 자동 등록은 탭 세션마다 한 번이다(B35 요청서 1절)
- 앱 셸(`components/AutoPortalPat.tsx`)이 첫 마운트에 `GET /me` 를 읽어 `auto.enabled && auto.due` 면 설정 버튼과 같은 일(`/auth/pat` 발급 →
  `PUT /me/portal-pat`, 출처 web)을 조용히 한 번 한다. 성공은 말하지 않고(설정 화면은 끝날 때 `GET /me` 를 다시 읽는다) 실패만 한 줄로 알린다.
- '같은 세션에서 되풀이하지 않는다' 는 sessionStorage 표지 하나(값 "1")다 — 토큰 · 계정은 담지 않는다. 저장소를 못 쓰는 창에서도 메모리 표지로
  그 페이지 안에서는 한 번이다. 실패한 시도도 센다(다시 하는 길은 설정의 버튼이다). 표지는 발급을 시작할 때 닫는다 — StrictMode 의 두 번 마운트는
  첫 `GET /me` 를 끊으므로 발급이 두 번 나가지 않는다. 같은 탭에서 계정을 바꾸면 그 탭에서는 다시 하지 않는다(드문 일이라 남긴다).
- 판정은 서버가 한다 — 화면은 `enabled` · `due` 두 칸만 읽고 `due_reason`(absent · revoked · undecryptable · expiring · audience)은 보이기만 한다.
  audience 는 등록된 PAT 에 step-forge 청중이 없다는 뜻이라 두 청중으로 새로 받으면 된다.
- 발급 청중을 `["mcp-gateway", "step-forge"]` 로(백엔드 `PORTAL_PAT_WANTED` 와 같다) — 손 버튼 · 자동 등록 · 스위치 켜기가 한 함수
  (`registerFromPortal`)를 지난다. 이름 `hwax-risk` 는 백엔드가 갈아 끼울 때 옛 PAT 를 폐기하는 표지라 그대로다.

### FE-3. 출처 — 앱이 받아 온 PAT 만 web 이다(B35)
- 손 버튼 · 자동 등록은 `source: "web"` 을 싣는다. 붙여 넣은 PAT 는 싣지 않는다(= manual) — 그 사람의 Claude PAT 일 수 있어 백엔드가 폐기하지
  않아야 한다. 종전 버튼은 아무것도 싣지 않아 manual 로 적혔고, 그러면 다음 갱신 때 폐기되지 않고 쌓였다. 삭제(`{pat: null}`)도 싣지 않는다.

### FE-4. 자동 등록 스위치 · 지우기(B35)
- 설정 화면에 스위치(`auto.enabled`)를 두고 그 옆에 `how_to_stop` 을 글자 그대로 보인다. 스위치의 이름은 '자동 등록' 하나(상태는 aria-checked)이고
  설명 · 멈추는 길은 aria-describedby 로 잇는다. `last_source` · `last_at` · `last_error`(갈래 transient · final 과 시각)를 보인다.
- 켜서 지금 받아야 하면(due) 그 자리에서 발급해 등록한다 — 켠 것은 사람의 손이라 결과를 보인다(앱을 다시 열 때까지 기다리게 두면 '켰는데 없다').
- 자동이 켜진 채 지우면 다음에 앱을 열 때 다시 등록된다(요청서) — 그래서 지울 때 '자동 등록도 끄고 지우기 · 지우기만 · 그만두기' 를 묻는다. 함께
  끄면 스위치를 먼저 내린 뒤 지운다(그 사이에 게이트웨이가 다시 등록하지 않게).

### FE-5. 띄워 보니 과제 · 타깃 화면이 백지였다 — 타입이 서버와 달랐다
- 실 백엔드를 띄워 B36 을 보려 했더니 타깃 화면이 통째로 백지였다. `verdict_candidate` 를 `{reason, conditions[]}` 로 적어 두었는데 서버는 늘
  `{verdict, counts, reasons[]}` 를 준다(08-31 부터) — `conditions.length` 에서 죽는다. 패널 품질은 `flags`(복수)인데 `flag.map` 을 읽어, 끝난
  패널이 하나라도 있으면 같은 꼴로 죽었다. 패널 열쇠는 `id` 이지 `panel_id` 가 아니고, `call_path` 는 품질 칸 안에 있으며, `tool_calls_n` 같은
  칸은 없다(도구 사용률 `tool_use_rate` 다).
- 과제 화면도 대상이 하나라도 있으면 백지였다 — 반영 요약 `external_sync` 의 채널 값이 객체(`{state, pending_ops, reason, message}`)인데 배지가
  그것을 React 자식으로 그렸다(React #31). 요청서 3절의 결함이다. 재동기 응답은 채널마다 `{state, attempts, next_at, last_error, done_at,
  pending_ops[]}` 라 둘을 다른 타입으로 두었다. 성격 태그도 글자가 아니라 `{tag, n}` 이라 태그가 있는 과제는 같은 꼴로 죽었고, 잡 진행은 숫자가 아니라
  `{done, total, …}` 이라 'NaN%' 였다. 보고서 목록의 반영 값은 `done` 인데 화면이 `synced` 를 찾았다.
- 잡 만들기 답의 `llm_calls_estimate` 는 `{low, high}` 라 '[object Object]' 였고, 자격 갈래는 U-3 뒤 `requester` · `owner` 다('service' 문구는 걷었다).
  진행판 잡의 `reason` · `progress` · `daily_remaining` 은 서버에 없다 — `pause_reason` · `panels_done/panels_total` · `signal` 이다.
- 25d7b07 의 교훈 그대로다 — 타입이 거짓이면 tsc 는 그 거짓을 지켜 준다. 이번에 손댄 호출(과제 만들기 · `GET /me` · PAT 셋 · 잡 만들기 · 진행판 ·
  패널 목록 · 등록부 후보 · 재동기 · 과제 상세의 잡 · 태그)은 백엔드 코드와 실 응답으로 맞췄다. 손대지 않은 칸의 거짓은 FE-7 에 적는다.

### FE-6. 패널 잡의 판단 LLM(B36)
- '판단 LLM' 은 이 박스의 LLM(GLM)이 기본이고 Claude 를 고르면 반출 경고와 동의 체크가 열린다. 경고 글은 검토 잡의 것에 '패널 잡은 그 패널의 브리프 ·
  좌석 조회 결과' 를 붙인 뜻이다. 체크는 늘 비어서 시작하고, GLM 으로 돌렸다 다시 고를 때와 잡을 만든 뒤에도 비운다(다음 잡의 미리 체크된 동의가
  되지 않게). 체크하기 전에는 시작이 잠기고 까닭을 한 줄 보인다.
- 본문은 `api/panelJob.ts` 한 함수가 짓는다 — 앞 다섯 칸(tier · concurrency · modifiers · user_memo · consent)은 종전 본문과 같은 순서 · 같은 값이라
  GLM 잡의 JSON 이 바이트로 같다. Claude 일 때만 `llm: "claude"` 를, 체크했을 때만 `consent_external: true` 를 뒤에 붙인다.
- 거절은 code 로 — 422 `consent_external_required` · 422 `pat_unavailable`(설정으로 가는 길) · 409 `external_llm_unavailable`('GLM 으로 고르기') ·
  422 `flow_mismatch` · 409 `review_job_running`. 서버 글은 고칠 곳까지 말하므로 제목만 화면이 고르고 글은 글자 그대로 보인다.
- 만든 뒤 — 내 Claude Code 에서 워크플로 `hwax-risk-claude` 를 인자 `{"targetKey": …}` 로 돌려야 나아가고, 돌지 않으면 보류 external_worker 로
  멈추며 다시 돌린 뒤 재개한다는 안내. 진행판 잡 줄에 'Claude' 배지(검토 잡 줄도 쓸 `LlmBadge`) · 반출 동의 기록(누가 · 언제 · 입구) ·
  `llm_mismatch` 수를 보인다.

### FE-7. 시험 · 확인 · 남긴 것
- 시험(`pnpm test`) — 새 의존 없이 tsc 로 순수 모듈 · 배지 컴포넌트를 CommonJS 로 옮겨(`tsconfig.test.json`, 산출물은 node_modules/.cache)
  node:test 로 돈다. 14건 — GLM 본문 288 조합이 종전 본문과 바이트로 같음 · Claude 본문의 동의 칸 · 시작 가능 여부 · 거절 code · 자동 등록 판정과
  한 번 문(저장소가 던져도) · 발급 청중 · 과제 거절 칸 · PAT 실패 문구 · 반영 배지(요약 · 재동기 응답)와 박스 까닭(react-dom/server 로 그림).
  변이 16개(스크래치 사본) 16/16 이 잡혔다. node --test 는 시험 파일마다 프로세스를 함께 띄운다 — 처음에는 파일마다 CommonJS 표지
  (package.json)를 덮어써서 다른 프로세스가 반쯤 쓴 표지를 읽고 한 번 죽었다. 이미 있으면 두고 없으면 임시 파일에 쓴 뒤 이름을 바꾼다(4c52c51).
- 실 백엔드 확인 — 이 가지의 백엔드를 스크래치 데이터 · 빈 루프백 포트로 띄우고(가짜 포털 `/auth/pat` · heax · 에이전트 `/health`, 소켓 가드로
  자기 포트 밖 연결 0) 브라우저(Playwright)로 눌렀다. 앱을 열면 발급 1 · 등록 1(source web, 청중 둘) · 같은 탭 새로 고침에 0 · PAT 없이 설정
  화면을 열면 한 번 등록 · 발급 403 은 한 줄 알림이고 되풀이 없음 · 스위치 끄기 · 켜기(켜면 발급) · 붙여 넣기는 `{pat}` 만 · '자동 등록도 끄고 지우기'
  는 끄기 → 지우기 순서. 과제 만들기 200(등급 실림) · 같은 code 는 code 칸에. 패널 잡 GLM 본문 `{"tier":"B","concurrency":1}` · Claude 는 체크
  전 시작 잠김 · 체크 뒤 `…"llm":"claude","consent_external":true}` · 409 · 422 의 글 · 진행판 'Claude' 배지와 동의 기록. 하네스는 리포에 넣지
  않았다(스크래치).
- 브라우저로 못 본 것 — 실제 포털의 `/auth/pat`(CSRF · feat:api-token)과 게이트웨이 교환 길, 실제 에이전트 서버의 외부 응답자 길, 끝난 패널이 있는
  타깃의 패널 표(패널을 돌리지 않았다 — 그 칸은 서버 코드로 맞췄다).
- 남긴 것(이 걸음 밖) — 등록부 행 타입도 서버와 다르다(`claim` · `cites` · `subject` · `domain` 이 없고 `merged` 가 있다 — 행을 누르면
  `cites.length` 에서 죽는다, M3 화면 요청서 7절 몫) · 과제 화면 대상 표의 `unseated_n` · `superseded_by` 는 그 응답에 없다('미착석 명') ·
  과제 화면의 동결 알림은 스냅샷 잡이 그 목록(`jobs[]`)에 없고 상태 `done` 을 찾아 서지 않는다 · 좌석 드릴다운 · 브리프 탭의 타입은 대조하지
  않았다.

## 화면 세션 10-31 2차 걸음 — ECAD 화면 · B34 묶음(가지 `wt1031/riskfe`, 2026-10-31)

> 포털 `docs/design-risk-review/ecad-1031/frontend-request.md` 1 ~ 10절(계약은 그 '반영' — main 9bd5f48)과 B34 묶음이다. 백엔드는 고치지
> 않았다. 서버에 없는 칸은 지어내지 않고 '이 서버는 주지 않는다' 로 보였고, 청할 것은 FE-14 끝에 모았다.

### FE-8. ECAD 카드 · 스냅샷 · 비교 · 대상의 ECAD(요청서 1 ~ 5 · 7 ~ 9절)
- 카드의 길은 `GET /meta/adapters` 의 ecad 줄 `status` 하나로 가른다(`api/ecadBoard.ts` `ecadRoute`) — ready 면 찾기 칸, unavailable 이면 빠진
  도구와 '운영자 몫', planned 면 '다시 읽기'. 줄이 없거나 모르는 값(옛 `contract_only`)이면 길을 열지 않는다(unknown). 붙은 보드의 정체는
  `probe.board` 이고 job_id 는 그것이 없으면 `ref.odb_job_id` 다. 도구가 없어도 붙은 보드는 보인다(떼기는 PAT 없이도 된다).
- 바꾸기 · 떼기 · 찾기는 과제 주인에게만 — 과제 행의 `owner_sub` 가 `GET /me` 의 email 인가로 가른다(서버도 남이면 404). 찾기 칸은 보드가
  없으면 열려 있고, 붙어 있으면 '바꾸기' 를 눌러야 열린다.
- 후보 표는 판 · 올린 시각을 앞 열에 두고 미리 고른 행이 없다. 지금 붙은 보드는 단추 대신 '붙은 보드' 배지다. job_id 가 16자리 16진이 아니면
  단추를 잠근다(서버는 422 E100 — 5절의 '화면이 먼저 막는다'). 붙은 보드가 있을 때만 '앞 보드(판) → 새 보드(판)' 확인을 받는다.
- 거절은 code 로만 가른다(`describeEcadError`) — 같은 서버 글이라도 code 가 다르면 다른 갈래다. 옛 판의 `ecad_credential_absent` 는
  `ecad_pat_absent` 와 같은 안내(설정 길)다. 422 `ecad_board_not_found` 는 본문 `candidates` · `hub_message` 를 후보 표로 다시 보이고 고르지
  않는다. 404 는 공용 '없음' 이다.
- 스냅샷의 '보드' 묶음은 board 노드 `attrs` 에서 읽는다(노드 표 경로 part `nodes` 는 attrs 를 싣지 않는다). null 은 '없음'(0 이 아니다),
  `n_nets` · `odb_version` · `outline_bbox` 옆에 '2단계'. 노드 표는 IR 노드에서 kind 거름 · 찾기(nid · 이름 · 정규 이름 · canon_key · ckey · dn)다.
- 비교의 ECAD 여부는 서버가 행에 적지 않아 화면이 가른다(`diffRows`) — 구조층 노드 변화는 `domain`, 엣지는 `kind_family: net`, 파라메트릭
  항목은 그 dn 이 ECAD 노드 변화에 있는가, 사건은 주체 dn 이 다 ECAD 인가다. 1단계는 ECAD 칸 변화를 싣지 않아(요청서 8절) 이것으로 넉넉하다 —
  2단계에서 ECAD 파라메트릭 항목이 생기면 서버가 행에 domain 을 싣는 편이 맞다.
- 좌석 까닭(9절)은 code 를 그대로 두고 사람 말을 붙인다(`lib/targetView.ts`). 사람이 적은 넘김 사유는 snake_case code 꼴이 아니면 글 그대로다.

### FE-9. 동결 폼 — 기본 kinds · 409 두 갈래(요청서 6절)
- ECAD 카드가 있으면 기본 kinds 에 ecad 를 넣는다. 사람이 체크를 한 번이라도 만지면 카드가 나중에 생겨도 덮지 않는다.
- 409 `model_too_large` — detail 의 `leaf_mcad` · `leaf_ecad` 로 무엇이 넘겼는지 한 줄을 적고 '그래도 동결' 확인 뒤에만 같은 본문에
  `allow_large: true` 를 싣는다. 예산 초(`budget_s`)는 적지 않는다 — '600초에 끊긴다' 로 읽혔다는 백엔드 주석(routes.LARGE_BUDGET_S)을 따랐다.
- 409 `source_unreachable` 은 detail 의 꼴로 가른다 — `{kinds, attached}` 면 kinds 를 붙은 종류로 바꾸는 단추, `{kind: "ecad", reason}` 이면
  'ECAD 보드를 못 읽었습니다'(reason 이 `ecad_pat_absent` 면 설정 길). 둘 다 아니면 공용 배너다. 거절 뒤 과제를 다시 받아 카드의 '못 읽음' 을 보인다.

### FE-10. 서버 꼴 — 스냅샷 · 비교 화면이 백지였다(요청서 10절과 그 둘레)
- 띄워 보니 스냅샷 화면은 'e.some is not a function', 비교 화면은 't.map is not a function' 으로 백지였다. `missing` 은 배열이 아니라 bool
  사전이고, 상태의 게이트는 사전(G1 ~ G6 레코드)이며 신호도 사전(열쇠에 'sig:' 가 없다), 비교 가능성은 `{ok, excluded_reason, note}` 가 아니라
  parity 칸 열댓 개다. diff 는 3층 문서, 사건 부분은 `{diff_id, events[]}`, 요약 부분에는 줄이 없다(summary_text 를 줄로 나눈다).
- 동결(`POST /projects/{id}/snapshots`)은 동기다 — 답의 snapshot_id 로 곧바로 연다. 1차 걸음에서 남긴 '동결 알림이 서지 않는다' 는 이것으로 닫았다.
- 일반 연결의 `ref` 는 객체다(서버 칸이 dict) — 글자로 보내 늘 422 였다. kind 마다 어댑터가 읽는 열쇠를 칸으로 받는다(mcad
  `stepforge_project_id` · `detect_job_id`, dyna `session_id` · `file_id` · `sha256`).
- 요구 목록의 값 칸은 `value` 다(`value_json` 이 아니다). 타입이 틀린 채 쓰는 곳이 없던 `getSnapshotNodes` · `getSnapshotEdges` 는 걷었다.

### FE-11. B34 — 스냅샷 · 비교 화면
- 게이트 `pass: null` 은 중립색 '판정 불가(까닭)' 이고 fail 배너에 세지 않는다(따로 '판정 불가 … — fail 이 아닙니다' 정보 줄). 까닭이 없는 자리
  (동결 답의 요약)에서는 까닭을 지어내지 않는다 — 처음에 'unknown' 을 붙였다가 걷었다.
- 규칙은 `evaluable=false` 가 이긴다 — '평가 불가(사유)' 이고 pass · fail 집계 밖이다. 변이 하나(집계에서 evaluable 검사 빼기)가 살아남아
  'pass 칸에 값이 남아 와도 평가 불가' 단언을 더했다.
- ack — fail 이고 차단이 아닌 게이트에만 '사유 적고 진행(ack)'(사유 300자, `POST …/gates/{gate}/ack {reason}`), 붙은 ack 에는 '확인 취소'
  (DELETE). G6 은 차단이라 단추 대신 '다시 캡처' 안내다(unit_unknown 이면 REST 원문으로). 9bd5f48 의 `part=state` 는 동결 때의 상태 원문이라
  ack 를 다시 싣지 않는다 — 그래서 답을 그 칸에 들고 있고 '새로 열면 이 줄이 보이지 않는다' 고 적었다(서버가 실으면 서버 값이 이긴다).
- 요구 여유(`sig:req.margin`) — 9bd5f48 은 동결 때 요구를 대조하지 않는다(`freeze_snapshot` 은 `build_state(ir)` 만 부르고
  `compute_state_for_snapshot` 을 부르는 곳이 없다). 신호가 없으면 표를 짓지 않고 '이 스냅샷의 상태에 요구 대조가 없습니다' 를 보인다.
- 키 대장 — 노드를 누르면 그 ckey 의 이름 바꾸기 · 병합(같은 스냅샷의 다른 ckey 고르기 또는 적기, 확인) · 되돌리기(확인) · 확정이다
  (`POST /sameas/decide` 의 ckey 결정). 키의 지금 상태(병합됐는가 · 표시 이름)를 읽을 길이 없어 답의 결과 줄만 보인다.
- '파서 세대 다름' 은 parity 가 정말 거짓일 때만이다(null 은 모름). 항목 · 사건의 `parser_differs` 는 출처가 둘이라(소스 앱 판 · 어댑터 →
  모든 행, ECAD 어댑터 → ECAD 행) 행마다 까닭을 비교 가능성에서 고른다 — 처음에는 모든 행에 'ECAD 어댑터' 말이 붙었다.
- 대응 확정표의 confirm · reject 는 늘 400 E100 이었다 — 노드 id 만 보내고 pair_key 가 없었다. stable 키와 '|' 로 이은 정렬한 두 과제 id
  (서버 글이 정한 꼴, GET /sameas 가 원장을 읽는 열쇠와 같다)로 보낸다. 과제 id 는 확정할 행이 있을 때만 두 스냅샷의 상태에서 읽는다.

### FE-12. B34 — 과제 화면
- 등급 · 수명 주기 · 코퍼스 제외 · 조직 공개 · 제품 연결은 9bd5f48 의 과제 상세(`_project_row`)에 없다 — '모름(이 서버가 과제 상세에 싣지
  않음)' 으로 보이고, 바꾸면 PATCH 답(열 그대로 — `corpus_excluded` 0/1 · `product_refs_json` 글자)이 이긴다.
- '조직 공개' 는 소유자만 — 편집자 · 보기에게 잠그고 까닭을 말한다. 역할을 모르면(멤버 표를 못 받음) 잠그지 않되 403 `role_insufficient` 를
  code 로 받으면 잠근다. 공개 전에 확인을 받고(보류 RA op 수) 답의 `resynced` 를 한 줄로 보인다.
- 과제 상세가 주인에게만 열린다(`_project_row` 가 소유 검사) — 편집자는 이 화면을 열지 못해 잠금은 브라우저로 못 보고 렌더 시험으로 본다.
- 멤버 탭 · 이양 · 폐기 · 이력 탭 — 거절은 code 로, 폐기는 과제 코드를 다시 적어야 하고 답의 `purge_report.remaining` 을 보인다. 이력은 그
  탭을 볼 때만 받는다.
- mcad 소스 카드의 '격리 없음' 경고는 상시다 — 연결 답의 `warnings`(`stepforge_no_isolation`)에만 실리면 카드를 다시 열 때 사라진다.

### FE-13. B34 — 대상 · 홈
- 좌석 넘기기(skipped)는 사유가 있어야 보낸다(빈 사유는 서버도 422). pending · assigned · running · failed 에만, 되돌리기는 carried 에만 연다
  (planner 의 허용 전이). 보류(deferred)는 되돌리기로 풀지 않는다. '좌석 상태 되돌리기 · skipped 사유 입력 경로는 아직 서버에 없습니다' 는
  틀린 글이라 걷었다.
- 마지막 신호는 서버 시계로 잰 초(`frame_idle_s`)를 쓴다. 러너가 1분 간격으로 적어 건강한 패널도 80초 안팎까지 가므로 80초를 넘을 때만
  경고 배지다. 시험이 닿게 두 줄 컴포넌트를 `components/JobSignals.tsx` 로 뗐다(페이지는 mermaid 를 끌어 node 시험에 못 싣는다).
- 홈 칩 · 거름은 카드가 그 칸을 줄 때만 — 하나도 안 주면 거름을 잠그고 까닭을 적는다(모르는 값으로 카드를 숨기지 않는다). 등급 칩 말은
  과제 화면의 사전과 같게 '기밀' 이다(처음에 '대외비' 로 적었다가 맞췄다).

### FE-14. 시험 · 확인 · 남긴 것 · 백엔드에 청할 것
- 시험 36건을 더해 50건(`pnpm test`) — ECAD 9 · 판정 18 · 렌더 9. 컴파일 산출물에 넣은 변이 20개가 다 잡혔다(하나는 FE-11 의 단언을 더한 뒤).
  `tsc -b && vite build` 통과. 커밋마다(첫 넷은 그 상태로 되돌려) 타입 검사 · 빌드 · 시험을 돌렸다.
- 실 백엔드 하네스(이 가지의 코드 · 스크래치 데이터 · 빈 루프백 포트 · 소켓 가드, 게이트웨이는 백엔드 시험의 FakeGateway)로 브라우저에서 본 것 —
  ECAD 카드의 세 갈래 · 찾기 → 후보 표 · 붙이기 · 바꾸기 확인 · 떼기 · 거절 code(하네스 스위치로 PAT 없음 · 게이트웨이 끊김 · find_job 없음 ·
  호출 실패 · 꼴 바뀜 · 허브에서 사라진 보드),
  동결 폼의 기본 kinds · 모델 크기 409 와 '그래도 동결' · kinds 밖 409 · 보드를 못 읽은 409, 스냅샷의 보드 묶음 · 표지 · 노드 거름, 비교의 ECAD 줄 ·
  '파서 세대 다름'(판이 다른 두 스냅샷), mcp_degraded 스냅샷의 G3 · G4 '판정 불가' · R-004 · R-005 '평가 불가', ack 와 취소, 요구 여유 없음 배너,
  키 대장, 과제 메타 PATCH · 조직 공개(주인) · 멤버 · 이양 · 폐기 · 이력, 좌석 넘기기 · 되돌리기, 도는 패널의 마지막 신호(80초 넘김). 대응 확정은
  하네스에 후보 쌍이 없어 단추를 못 눌렀고 본문만 서버에 보내 봤다(옛 본문 400 · 새 본문 200).
- 브라우저로 못 본 것 — 편집자로 과제 화면(FE-12), 도는 검토 잡의 일꾼 줄(렌더 시험), 찾기의 `hub_message`(꺼내기만 시험), 실제 ODB 허브 ·
  게이트웨이 · 포털.
- 백엔드에 청할 것 —
  1. `GET /projects/{id}` 의 과제 행에 `classification` · `lifecycle` · `closed_at` · `corpus_excluded` · `excluded_reason` · `mcp_visibility` ·
     `product_code` · `product_refs_json` · `predecessor_product_code` · `status` 와 계약의 `members`, 그리고 멤버(편집자 · 보기)도 읽게(지금 남은 404).
  2. `GET /projects` 카드에 `classification` · `lifecycle` · `corpus_excluded` · `my_role`, 그리고 멤버로 든 과제.
  3. `GET /snapshots/{id}?part=state` 가 ack(`ack_by` · `ack_at` · `ack_reason`)와 `gates_hash` 를 지금 값으로 싣기(rr_gate_acks · gates_json).
  4. 동결 때 요구 대조(`sig:req.margin`)와 요구를 고친 뒤 다시 세기(`compute_state_for_snapshot`).
  5. 키 대장 읽기 — 예 `GET /api/part-keys?ckey=` → `{ckey, status, merged_into, display_name, aliases}`, 없으면 404.
  6. `GET /sameas` 의 답(또는 행)에 `pair_key` — 화면이 서버 글의 꼴로 짓고 있다.
  7. 도는 패널마다의 신호 — 진행판 `job.signal` 은 마지막에 적힌 하나라 동시 2 에서 덮인다(`signals: [...]`).
  8. 과제 상세의 스냅샷 머리에 판 칸(`app_versions` · `adapter_versions`) — 과제 화면 목록에서 '파서 세대 다름' 을 미리 보일 수 없다.

## 화면 세션 10-31 3차 걸음 — M3 화면(가지 `wt1031/riskfe`, 2026-10-31)

> 포털 `docs/risk-review-redesign/m3-frontend-request.md` 1 ~ 7절이다. 요청서는 a27e569(가지 m3)를 대조했고 이 걸음은 그 뒤 main 에 합쳐진
> 이 가지의 백엔드 코드를 계약으로 읽었다 — 칸이 다르면 코드를 따랐다. 백엔드는 고치지 않았다. 확인은 실 백엔드를 스크래치 하네스(가짜 검토 ·
> 쟁점 패널 · 요약 엔진으로 원장을 만든 카드 대조 대상 넷과 패널 대상 하나)로 띄워 브라우저로 눌렀다(FE-22). 커밋 — 9055a0a(7절 등록부) ·
> bc580e8(1 ~ 6절) · 07e7af4(대상마다 다시 마운트) · 7cc4464(서버 견본 · 시험).

### FE-15. 자리 — 카드 대조 대상의 탭과 대상 열쇠마다 다시 마운트
- 카드 대조 대상(진행판 `flow: "cells"`)에만 셀 격자 · 전문가 · 쟁점 · 완결 탭이 더해지고, 보고서 탭은 종합 보고서가 된다(패널 대상은 통합
  보고서 그대로). 브리프 탭은 카드 대조 대상이면 서버가 `cells_flow_web_only` 로 거절하므로 부르지 않고 그 말을 보인다.
- 카드 대조 대상은 Tier 패널 잡을 세우지 않는다(422 `flow_mismatch`) — '패널 실행' 카드는 방식을 바꾸기 전에 선 패널 잡이 있을 때만 그 줄 ·
  조작으로 남기고 만들기 칸은 두지 않는다. 검토 잡은 진행판의 '검토 잡 만들기' 에서 만든다.
- 대상이 바뀌어도 같은 라우트라 TargetPage 가 다시 마운트되지 않아 앞 대상의 탭 · 고른 셀 · 폼이 넘어갔다 — 하네스의 합성 대상들은 단위
  id 까지 같아 고른 셀이 그대로 다음 대상의 셀로 보였다. 대상 열쇠를 React key 로 둔다(`TargetView`).
- 셀 격자 · 쟁점 · 완결은 탭을 볼 때만(볼 때마다) 읽고 마운트는 남긴다 — 적던 사유 · 고른 셀은 탭을 바꿔도 남는다(TabPanel 주석의 규칙).
  전문가 보고서 · 종합 보고서는 입력이 없어 볼 때만 그린다(새 판을 처음 쪽부터 받는다).
- 요청서 8절대로 검토 잡의 판단 LLM 고르기(llm · consent_external)는 짓지 않았다. 진행판이 Claude 검토 잡을 실어 오면 'Claude' 배지만
  보인다(MCP 로 만든 잡).

### FE-16. 1 · 2절 — 사슬 머리 · 검토 진행판
- 완결 표기는 서버 글(`level_label`)을 그대로 보인다 — 화면이 잔여로 표기를 다시 짓지 않는다. 막음이고 확인되지 않은 잔여(`blocking &&
  !acked`)를 세어 '확인 안 된 막음 잔여 N — 완결 화면' 단추를 단다.
- 사슬 배지는 `stage.state` 로, 멈춤의 까닭은 `error` 머리로 가른다 — `pat_unavailable:` 은 설정 길, `restart:` 는 '사람이 재개', `draining:`
  은 비우는 동안. 멈춘 사슬 잡의 재개는 종전 `resumeJob` 그대로다. `advice` 가 `issue_yield_low` 면 알림만(잡은 멈추지 않는다).
- M2 시절 잡 뒤의 '쟁점 · 종합 시작' 은 요청서의 조건 그대로다(사슬 · 판 없음 · 마지막 검토 잡 completed · 대기 셀 0). 그 잡이 사슬 표지를
  가졌는지는 칸이 없어 가르지 못한다(백엔드에 청할 것 4).
- 거르기 줄 — `approved` false 면 '배정표 승인 전 — 거르지 않는다', null(검토 잡 전)이면 그 말, 95% 상한이 null 이면 '표본 없음'(0% 로
  적지 않는다). 그림자 모드 · 기다리는 표본 · 넓힌 영역 · 끔은 한 줄씩이다.
- 잡 줄 — 단계(live 는 '근거 꾸러미 실호출'), 기다림의 `note` 글 그대로, 다시 연 셀 몫, 호출 'ok N / 추정 E' 와 남은 시간 어림(남은 호출 ×
  평균 호출 초 ÷ 지금 도는 호출 수 — 추정이 거르기 없음 가정이라 실제보다 길다고 적는다). 진행판을 아직 세지 않은 잡은 칸이 null · 빈
  객체라 '셈 전' 이다. 끝난 잡도 `error` 칸에 사람이 할 일을 남기므로(실패 셀 처분) '오류' 가 아니라 '잡이 남긴 글' 로 부른다.
- 진행판 5초 폴링을 검토 잡 · 사슬 잡이 돌거나 줄에 섰을 때까지 넓혔다(멈춤은 사람이 움직일 때까지 그대로라 읽지 않는다).

### FE-17. 3절 — 검토 잡 · 셀 처분 · 동의 · 보류 풀기
- 검토 잡 본문은 빈 범위 칸을 싣지 않는다(빈 목록은 서버가 422 `scope_invalid`) — 다 비면 scope 없이 로스터 전원이다. 동의는 늘 비어서
  시작하고, 422 `consent_required`(아무것도 바꾸기 전)를 받아야 추정과 체크가 열린다. 범위를 바꾸면 앞선 추정 · 동의를 걷는다.
- 셀 격자는 서버가 검토 순서 → 단위 순번으로 주는 쪽(500칸)을 전문가 × 단위로 편다 — 쪽 경계에서 전문가 하나가 단위 일부만 가질 수 있다.
  칸의 짧은 말은 상태 말에 '표본'(route audit) · '사람'(human_retry) · '↺n'(다시 연 횟수)을 붙이고, 말풍선에 거른 까닭 · 길 · 오류 ·
  사람의 처분을 서버 글 그대로 싣는다. 고른 셀은 그 쪽의 셀만이고 거름 · 쪽을 바꾸면 걷는다.
- 다시는 기본 실패 셀만(나머지는 서버가 not_failed 로 센다) · force 는 검토함 · 입력 결손도 열고 판정 행을 지우므로 사유가 필수 · 사유는 주면
  4~300자. 넘김은 사유 필수다. '이 잡의 실패 셀 전부' 는 `filter {job_id, state: "failed"}` 이고 잡은 진행판의 가장 최근 검토 잡이다(처분이
  잡을 세우면 그 잡으로 바뀐다 — 앞 잡의 실패 셀은 고른 셀로 처분한다).
- 처분 답의 잡 줄 — 넘김이 세운 잡은 돌 셀이 없는 마감 잡이라 그렇게 말한다(처음에 '검토 잡을 세웠다' 로 적었다가 띄워 보고 고쳤다).
  걸림 셈이 `pack_missing` 이면 0 이 아니라 '모름' 과 서버의 까닭이다.
- 3-5 — 재개 갈래는 보류 코드가 아니라 `progress.reopened_extra.hold` 로 가른다(사람이 멈춘 잡도 몫이 넘쳐 있으면 동의가 든다).
  consent_extra 는 동의를 기다리는 셀 수 · 추정 호출 · 여유 · 처음 동의한 추정을 보이고 체크 뒤 `resume?consent=true`, max_calls 는 재개를
  잠그고(409) 기다리는 셀 넘기기를 앞에 둔다. 그냥 재개가 422 `consent_required` 로 돌아오면(그사이 몫이 넘쳤다) 그 답의 몫으로 같은 동의
  칸을 연다.
- 보류 풀기는 패널 대상의 진행판에만 둔다(카드 대조 대상은 검토 잡이 범위 안 보류를 저절로 푼다). 답의 note · depth 를 그대로 보인다.

### FE-18. 4절 — 쟁점
- 서버는 쟁점 id 순(쪽을 잇는 안정 열쇠)으로 주고 화면이 순위대로 정렬한다(기본 켬). '더 받기' 의 `ledger_rev` 가 첫 쪽과 다르면 잇지 않고
  처음부터 다시 받는다.
- 버튼 — 편성 · 도는 쟁점은 둘 다 잠그고(409 `issue_in_flight`) 이유를 말한다. 이미 대기인 쟁점에 올리기, 이미 건너뛴 쟁점에 건너뛰기는 하는
  일이 없어 두지 않는다. 쟁점 사유는 1~300자다(처분 사유 4~300자와 다르다 — routes.put_issue).
- 행의 `outcome_json` 은 서버가 늘 null 로 싣는다 — `routes._issue_row_out` 이 `_loads(…, None)` 을 부르고 `_loads` 가 `type(default)` 가
  아니면 기본값을 돌려준다(DB 에는 있다). 그래서 쟁점 한 줄은 결과 낱말까지이고 펼친 칸에 '서버가 결과 칸을 싣지 않았다' 고 적었다(백엔드에
  청할 것 1). 칸이 오면 '상향 치명/FAIL' 꼴로 덮은 값을 붙인다.

### FE-19. 5절 · 3-7 — 종합 보고서 · 전문가 보고서 쪽
- 두 보고서가 `components/ReportPager.tsx` 하나로 쪽을 넘긴다 — 첫 쪽은 판을 싣지 않고 첫 쪽의 `version` 을 둘째 쪽부터 싣는다. 409
  `report_version_moved` 면 '판이 vA 에서 vB 로 바뀌었다' 를 보이고 1쪽부터 다시 받는다(하네스에서 확인 한 번으로 v5 → v6 을 만들어 봤다).
  part 를 바꾸면 1쪽부터다. 422 E100 의 `pages_total: 0` 은 '이 부분에는 쪽이 없다' 다.
- 쪽의 블록 값은 마크다운 조각 배열이고 조각 안에 줄바꿈이 있다(전문가 보고서). `MarkdownLines` 는 제목 · 목록(들여쓰기 깊이) · 굵게 ·
  고정폭만 글 노드로 그린다 — 서버 글을 HTML 로 해석하지 않는다(새 의존 없음).
- 판이 없으면(404 `report_absent`) '다시 내기'(코드 조립 판)를 안내한다. '요약부터 다시' 는 진행판의 사슬 단계가 살아 있는 종합 잡이면
  잠근다(서버는 막지 않고 새 잡을 세운다). 종합 잡 답의 `error` 가 `pat_unavailable` 이면 설정 길을 단다.

### FE-20. 6절 — 완결과 확인
- 확인은 지금 읽은 잔여 행의 `basis_hash` 를 그대로 보낸다. 409 `residual_changed` 면 `?fresh=1` 로 한 번 다시 세어 지금 집합을 보이고 다시
  확인받는다 — 요청서는 fresh 를 '버튼으로만' 부른다고 했지만 캐시가 낡은 채면(쟁점 결정이 캐시를 새로 쓰지 않는다 — 백엔드에 청할 것 2)
  캐시를 다시 읽어도 같은 해시라 409 가 되풀이된다. 사람이 누른 확인의 뒤끝이라 한 번만 센다. 하네스에서 이 길이 실제로 났다(올린 쟁점 뒤
  '미토의 4건' 캐시 → 409 → 지금 3건).
- 확인 취소는 행을 지우지 않는다 — 한 번 더 묻고 보낸다. 확인 · 취소의 답으로 표기를 보이고 `report_version` 이 있으면 보고서 탭 단추, null
  이면 '판 조립 실패(확인 자체는 섰다)' 다.
- 잔여 표는 내용 폭이라 미토의 쟁점 문장이 확인 칸을 화면 밖으로 밀었다 — 글 칸만 폭을 묶어 접어 쓴다(등록부의 쟁점 칸도 같다).

### FE-21. 7절 — 등록부
- 행 타입을 서버 꼴로 고쳤다 — 주장 · 근거 · 영역은 행이 아니라 `merged`(claim · cites · domains · owner_domain)에 있다. 전에 행 칸으로 적어
  두어 행을 누르면 `cites.length` 에서 백지였다(FE-7). 영역은 대표의 소유 영역이 먼저이고 제기 원자들의 영역이 뒤다. 패널만 본 비교 보기는
  저장하지 않은 계산 행이라 저장 칸이 없고 상태 변경 폼을 두지 않는다.
- 주의 · 단위 · 패널만 본 비교 보기는 서버 쿼리이고(대상 화면이 들고 머리의 판정도 같은 응답에서 읽는다), 카드 대조 대상의 기본은 주의
  A · B 다. 패널 대상에는 기본 거름을 걸지 않는다(그 대상의 주의 등급은 참고값).
- 쟁점 칸 — 쟁점 패널이 덮은 행(`merged.before_issue`)은 덮기 전의 지지 전문가 수와 분포로 '원래 — 제기 N명(FAIL a · WARNING b) → 쟁점 패널
  결과', 덮지 않는 결과(기각 · 판정 못 함)는 지금 분포로 센다. `issue_reraised.label` 은 굵게. 열은 읽는 차례(주의 · 키 · 영역 · 심각도 ·
  판정 · 쟁점 · 지지)로 앞에 둔다.

### FE-22. 서버 견본 · 시험 · 확인 · 남긴 것 · 백엔드에 청할 것
- `src/contract/serverSamples.ts` — 하네스의 실 응답(진행판 둘 · 완결 · 쟁점 · 등록부 · 보고서 쪽 · 셀 목록 · 처분 답)을 줄여 옮기고 tsc 가
  타입과 견준다(요구 칸이 빠지거나 값 종류가 다르면 빌드가 깨진다, 서버가 더 싣는 칸은 받는다). 화면 코드는 import 하지 않아 번들에 들지
  않는다. 이것이 둘을 잡았다 — 진행판 `strong` 은 숫자가 아니라 `{done, done_weak, ratio}` 이고, 등록부 행 · merged 에 적지 않은 칸이
  있었다. 타입을 일부러 틀리게 바꾼 8가지 가운데 7가지를 잡는다(주의 등급 null 은 견본에 그런 행이 없다).
- 시험(`pnpm test`) — 25건을 더해 75건. 순수 판정(사슬 배지 · 사슬 시작 · 거르기 · 입력 결손 · 호출 어림 · 보류 갈래 · 잡 본문 · 사유 ·
  처분 답 · 걸림 셈 · 셀 격자 · 거절 code · 쟁점 줄 · 버튼 · 쪽 잇기 · 보고서 쪽 물음 · 마크다운 · 확인 상태 · 깊이 · 등록부 줄)과 견본으로 그린
  조각(대상 머리 · 진행판 · 등록부 쟁점 칸 · 행 펼침). 컴파일 산출물에 넣은 변이 33개가 다 잡혔다(둘은 처음에 살아남아 단언을 더했다).
- 실 백엔드 하네스에서 브라우저로 본 것 — 대상 머리(표기 · 잔여 표지 · 사슬 · 판 링크) · 진행판 · 셀 격자의 넘김(답의 마감 잡 · 걸림 0) ·
  다시(살아 있는 잡의 범위 밖 → 다음 잡) · force 다시(사유 4자 미만 잠금 → 살아 있는 잡에 얹혀 consent_extra) · 동의 재개
  (`resume?consent=true`) · 기다리는 셀 넘기기(잡이 이어 돈다) · 검토 잡 만들기(422 → 추정 · 동의 → 200) · M2 시절 잡 뒤 사슬 시작 · 보류 풀기 ·
  쟁점 올리기 · 발언 · 완결 확인(409 → 다시 세기 → 200, 보고서 v4) · 확인 취소(v5) · 보고서 쪽(v5 둘째 쪽 409 → v6 1쪽) · 영역 part · 전문가
  보고서 · 등록부 쟁점 칸 · 행 펼침 · 패널만 본 비교 보기. 쓰기 본문은 하네스 기록으로 요청서와 견줬다. 자기 포트 밖 연결 0.
- 브라우저로 못 본 것 — 편집자 · 보기 역할(하네스 신원이 하나다 — 403 은 code · 공용 배너), 기다림(health_unknown · draining — 러너를 하네스가
  잠갔다), max_calls 보류(렌더 시험), 거른 셀이 있는 대상(거름 0), 다시 토의 표기가 선 쟁점, 실제 에이전트 서버 · 포털.
- 백엔드에 청할 것 —
  1. `GET /targets/{key}/issues`(와 MCP `risk_get_issues`)의 `outcome_json` 이 늘 null — `routes._issue_row_out` 의 `_loads(…, None)`(DB 값은
     있다). `{}` 기본값으로 읽고 비면 null 로 싣거나 `_loads` 의 형 검사를 그 자리에서 건너뛴다.
  2. `PUT /issues/{id}` 뒤 `closure.refresh` — 지금은 완결 캐시가 그대로라 진행판 `level_label` · `qualifiers` 와 `GET …/closure` 가 낡고, 그
     캐시로 보낸 확인이 409 `residual_changed` 다(화면은 한 번 다시 세어 넘긴다).
  3. 진행판 `review.job`(routes.review_payload)과 `review_cells._latest_review_job` 의 `ORDER BY created_at DESC, id DESC` — 같은 초에 선 두
     검토 잡이면 uuid 순이라 앞 잡을 고를 수 있다(하네스에서 났다). 사슬 단계처럼 `rowid DESC` 로.
  4. 진행판에 마지막 검토 잡의 사슬 표지(`params.chain`) 칸 — 'M2 시절 잡 뒤의 사슬 시작' 을 요청서의 어림이 아니라 그 칸으로 가르게.
- 포털 요청서에 고칠 말 — 2절의 '`by_basis` 의 `unset` 은 search_only 셀을 함께 센다' 는 지금 코드와 다르다(CELL_BASES 에 search_only 가
  있어 따로 센다).

## 화면 세션 10-31 4차 걸음 — 리뷰 후속(가지 `wt1031/riskfe`, 2026-10-31)

> 이 가지 전체를 본 리뷰가 검증해 넘긴 지적 13건이다(높음 1 · 중간 1 · 낮음 2 · 그 밖 9). 지적마다 먼저 재현했다 — 스크래치 jsdom 하네스(리뷰의
> 재현 스크립트를 이 가지의 컴파일 산출물에 대고) · 스크래치 백엔드 사본(이 가지의 코드, 바이트코드 끔, 공용 시험 픽스처) · 스크래치 SQLite. 13건
> 다 재현됐고 다 고쳤다. 백엔드는 고치지 않았다. 커밋 5ea092f ~ 1021e30.

### FE-23. 쟁점 다시 토의 표기의 두 꼴 · 화면 자리의 오류 경계
- 사람이 끝난 쟁점을 올리면(PUT /issues queue) reraised_json 이 빈 채로 대기가 되고, 새 패널이 판정 못 함이면 issues._keep_verdict 가
  `{new_panel_failed}` 만 적는다 — 쟁점 행의 reargue 는 label · new_panel_failed 뿐이다(스크래치 백엔드 사본에서 그 길을 돌려 받은 행). 타입이
  label 밖을 다 요구 칸으로 적어 두어 그 행을 누르면 `raisers_added.length` 에서 #root 가 내려갔다(jsdom · 실 Chromium 둘 다 재현).
- label 밖은 선택 칸이다. 근거가 바뀐 표기(basis_hash 가 있다)만 들고 남 · '주장값이 바뀌었다' · 시각 · 회차를 보이고, 새 패널 실패는 그
  패널 · 까닭(말과 code) · 시각이다(`ReargueNote`). 견본 `issueReargueRows` 가 두 꼴을 tsc 와 시험에 싣는다.
- 오류 경계(`ErrorBoundary`)를 Routes 둘레에 둔다 — 이 가지에서만 서버 꼴 하나로 앱 전체가 백지가 된 일이 넷이었다(FE-5 · FE-10 · 9055a0a ·
  이것). 주소(pathname)가 바뀌면 멈춤을 걷고, 아이들을 다시 마운트하지 않아 평소 동작은 그대로다.

### FE-24. 등록부 상태 변경에 target_key
- 9bd5f48 부터 본문에 target_key 가 없어 registry.set_status 가 그 사람의 같은 cluster_key 행 전부(앞뒤 스냅샷 · diff 대상)를 바꾸고
  verified · dismissed 면 다른 대상의 finding 에 라벨까지 달았다(스크래치 백엔드 — updated 2, target_key 를 실으면 1). 본문은
  `registryStatusBody` 한 곳에서 늘 싣는다.

### FE-25. 완결 fresh=1 은 그 읽기 한 번
- `mode.fresh` 가 참으로 남고 useAsync 가 active 도 deps 로 보아 완결 탭에 돌아올 때마다 fresh=1(다시 세어 rr_targets 에 쓴다)이 나갔다.
  그 읽기 차례(mode.n)에 이미 보냈으면 캐시를 읽는다. FE-20 의 '409 residual_changed 뒤 한 번' 은 그대로다.

### FE-26. 과제 스냅샷 머리의 degraded
- bool 이 아니라 호환 열 그대로(degraded_json 의 첫 code | null)다. 배지에 code 를 보이고(첫 값이라 전부는 스냅샷 화면), null 은 '없음' 이다.
  견본 `projectSnapshotHeaders` — 타입을 boolean 으로 되돌리면 tsc 가 깨진다(확인).

### FE-27. 동의는 받은 그 요청 · 그 몫에만
- 셀 격자 — 요청 열쇠(동작 · 고른 셀 또는 이 잡의 실패 셀 · force · start)가 바뀌면 추정 · 동의를 걷는다. 바뀐 요청은 동의 없이 다시 가서
  새 추정을 받는다.
- 진행판 consent_extra — 체크는 몫의 열쇠(`consentAmountKey` — 잡 · 다시 연 셀 · 동의한 셀 · 기다리는 셀과 그 추정 호출)에 묶인다. 몫이
  바뀌면 빈 체크로 보이고, 넘김 · 재개 뒤와 기다리는 몫이 없어지면 걷는다. ReviewJobPanel 은 잡 · 보류마다 다시 마운트되지 않아 상태가 넘어갔다.
- 패널 잡 Tier C 승인 — 잡을 만든 뒤와 티어를 바꿀 때 걷는다(웹 REST 는 부를 때마다 새 잡을 세운다).

### FE-28. 확인 뒤에만 쓰는 조작
- 키 대장 — 고른 노드마다 다시 마운트한다(앞 노드에서 연 '되돌리기' 확인이 새 노드 아래로 넘어가 앞 노드의 키를 되돌렸다, 07e7af4 와 같은 꼴).
  '독립 키로 확정' 도 확인 뒤다 — sameas confirm_key 는 status 만 confirmed 로 바꾸고 유효 키 해석은 merged 일 때만 merged_into 를 따라,
  병합된 키를 확정하면 그 병합이 풀린다(스크래치 SQLite 로 백엔드 코드 실행). 키 상태를 읽을 길이 없어 '병합돼 있으면 풀린다' 로 말한다.
- 잡 취소 — 검토 잡 · 패널 잡 모두 잡을 id 로 부르고 '재개되지 않는다 · 잠시 세우려면 일시정지' 를 말하는 확인(`JobCancelConfirm`) 뒤에만.
  확인은 연 그 잡에 묶인다.
- 과제 — 멤버 빼기는 그 사람을 부르는 확인 뒤, 역할은 고른 뒤 '적용', 등급은 고른 뒤 '바꾸기'(기밀 또는 모름 → internal 은 반출 머리의 최고
  등급 말과 함께 확인), 수명 주기는 고른 뒤 '바꾸기'(active 를 떠나면 closed_at 이 찍힌다는 확인). 고르기만으로는(화살표 키의 change 도) 쓰지 않는다.
- 동결 — '그래도 동결' 은 거절된 그 본문에 allow_large 만 더한다(`capture.allowLargeBody` — snapshotBody 는 allow_large 를 싣지 않는다). 폼을
  바꾸면 거절 배너와 단추를 걷는다.

### FE-29. PAT 자동 등록 — 받은 PAT 를 버려 두지 않는다
- 등록이 실패하면 — 저장 전 거절(4xx · 502 portal_unreachable — routes._register_portal_pat 은 검사를 다 지난 뒤 저장한다)이면 포털
  `POST /auth/pat/revoke-self`(Bearer 그 PAT, 쿠키 · CSRF 없이 — 백엔드가 갈아 끼운 PAT 를 폐기하는 길과 같다)로 곧바로 폐기한다. 저장됐을 수도
  있는 실패(다른 5xx · 네트워크)는 GET /me 의 jti 로 가른다 — 같으면 성공, 다르면 폐기, 못 읽거나 portal_pat 이 null 이면 두고(등록된 자격을
  폐기하지 않게) 사람에게 jti 를 대조하라고 말한다. 실패는 `PortalRegisterError` 이고 알림은 거절의 글에 그 처리를 붙인다.
- 이 브라우저의 쉼 — 등록 단계의 실패 뒤 localStorage `{until, code}`(토큰 · 계정 없음)로 일시 실패 10분 · 사람이 고칠 거절 6시간(백엔드가 게이트웨이
  교환 실패에 거는 두 쉼) 동안 새 탭이 발급하지 않는다. 버튼 · 스위치 성공이 걷고, 설정은 그동안 '앱을 열면 저절로 받는다' 대신 쉼을 말한다.
  발급 단계의 실패는 PAT 를 만들지 않아 쉬지 않는다.
- box.reasons 에 cred_key_invalid 가 있으면 자동으로 받지 않는다(등록은 반드시 422 cred_key_absent 인데 그 전에 새 PAT 가 포털 검증에 나간다).
  리뷰가 제안한 `secrets_valid` 로는 막지 않았다 — 키 없음(missing_required) · 개발용 폴백(cred_key_dev_fallback)에서도 거짓인데 그때 등록은 되므로
  dev 박스의 자동 등록이 꺼진다.
- 쉼은 웹 실패를 서버가 적지 않아 화면이 들고 있는 것이다 — 서버가 웹 실패도 auto.last_error 에 적으면(백엔드에 청할 것 2) 걷는다.

### FE-30. 시험 · 확인 · 남긴 것 · 백엔드에 청할 것
- 시험 12건을 더해 87건(`pnpm test`). 컴파일 산출물 변이 — 쟁점 1 · 등록부 1 · PAT 6 이 다 잡혔다. `tsc -b && vite build` 통과.
- jsdom 하네스(스크래치, 리뷰 스크립트와 고친 뒤의 길 스크립트) — 13건 전부의 고친 뒤 동작과 정상 길(같은 몫의 동의 재개 · 폼 그대로의 '그래도
  동결' · 409 뒤 fresh 한 번 · 500 뒤 저장된 PAT 는 그대로). 실 Chromium(빌드한 dist, API 는 Playwright 경로 가로채기로 흉내 — 서비스 · 프로세스를
  띄우지 않았다) — 쟁점 행 누르기(백지 아님 · 페이지 오류 0) · 완결 탭 오가기(closure · fresh=1 · closure · closure) · 등록부 상태 저장 본문의
  target_key.
- 브라우저로 못 본 것 — 실 백엔드 · 실 포털(revoke-self 를 실제 포털에 보내 보지 않았다 — 포털 코드로 Bearer 만 · CSRF 없음 · 청중 mcp-gateway 를
  맞췄다), 동의 · 확인 조작들의 실 브라우저 클릭(jsdom 으로 봤다).
- 백엔드에 청할 것 —
  1. sameas confirm_key — 병합된 키(status merged)면 거절하거나 merged_into 를 비운다(지금은 confirmed 인데 merged_into 가 남는 행이 된다).
  2. PUT /me/portal-pat 의 웹 등록 실패도 portal_pat.auto 의 last_error · last_error_kind · last_error_at 에 적기(지금은 게이트웨이 교환 실패만 적는다) —
     due 판정이 그 쉼을 보면 화면의 브라우저 쉼을 걷는다.
  3. GET /projects/{id} 의 스냅샷 머리에 degraded_json(목록 전체).
  4. 키 대장 읽기(FE-14 청할 것 5) — 있으면 확정 확인이 '병합돼 있으면' 대신 지금 상태를 말한다.
  5. (선택) 다시 토의 표기의 꼴을 하나로 — _keep_verdict 가 비어 있던 쟁점에도 at · round 를 적으면 화면이 길마다 가르지 않아도 된다.

## 사람 조작 감사 — 잡 제어 · 등록부 status · verdict 확정(가지 `wt1031/risk-audit`, int1031/risk2 7b1042d 위, 2026-10-31)

> 사용자 결정 10-31(포털 세션의 답) — 심사의 길을 바꾸는 사람 조작은 정본 plan §8.2.3 대로 rr_audit 를 남긴다. '10-31 백로그' BL-4 가 남긴
> 줄(잡 제어 · 등록부 status · verdict 확정이 감사 행을 남기지 않아 대상 감사와 보고서 '사람 개입 요약' 에 늘 없다)을 닫는다.

### AU-1. 셋과 그 자리
- 잡 제어 — `POST /jobs/{id}/pause|resume|cancel` → `rr_audit(scope job · subject 잡 id · action job.pause|resume|cancel)`. MCP
  `risk_job_action` 의 pause · resume · cancel 은 같은 라우트 함수(`entry.job_action` → `routes.job_action`)라 같은 행이 선다. 대상 감사는
  `rr_jobs.target_key` 로 그 잡을 고른다(BL-2 의 job 갈래).
- 등록부 status — `PUT /registry/{cluster}/status` → 바꾼 (대상, 클러스터) 행마다 `rr_audit(scope registry · subject '<대상>#<클러스터>' ·
  action registry.status)`. 대상을 고르지 않은 전이는 그 열쇠의 내 행 전부를 바꾸므로(`registry.set_status`) 내 대상마다 한 행이다 — 맨
  열쇠 한 행으로 적으면 그 열쇠를 나중에 갖게 된 내 다른 대상(바뀐 적 없는 행)의 감사에도 실린다. 대상을 고른 공개 토글 · 병합과 같은
  꼴이라 BL-8 의 소유자 조건 갈래를 타지 않고, 남의 같은 열쇠 행에는 닿지 않는다.
- verdict 확정 — `PUT /targets/{key}/verdict` → `rr_audit(scope target · subject 대상 열쇠 · action verdict.final)`.
- 셋 다 project_id 는 그 대상의 과제다 — 과제 감사(`GET /projects/{id}/audit`)에도 선다(잡 · 좌석 · finding 행과 같다).
- 행위자는 부른 사람이다 — `routes._audit` 가 owner_sub · actor 둘 다에 적는다(다른 감사 행과 같다). 셋 다 소유자만 부를 수 있는 길이라
  (`_owned_row` · `set_status(owner_sub=)` · `_target_row`) 행위자가 곧 그 대상 소유자다. 입구는 `AUDIT_CHANNELS`(쿠키 web · Bearer rest ·
  게이트웨이 위임 mcp)이고 mcp 길은 actor_verified 0 이다(M3C-8 의 규칙).

### AU-2. 행의 칸 — 코드 어휘만, 사람이 쓴 글은 싣지 않는다
- 잡 — before · after `{state, hold_code}`. 잡의 error 글(러너 · 엔진의 글 — 엔진 쪽 멈춤 글에는 멈춘 사람의 메일이 든다)은 싣지 않는다.
  라우트는 사유를 받지 않는다(정본 §8.2.3 의 `{reason≤200}` 본문은 앱에 없다 — 이번에 더하지 않았다).
- 등록부 — before `{status}` · after `{status, status_log_seq}`. note · evidence_ref 는 싣지 않는다 — 그 글은 그 seq 의 상태 기록
  (`rr_registry_status_log`)과 등록부 행(status_note · verified_by_json)에 그대로 있고, 감사 행은 seq 로 그 자리를 가리킨다. evidence_ref 도
  자유 글이다(record_label 은 빈 값만 막는다).
- verdict — before · after `{verdict_final}`. note 는 rr_targets.verdict_note 에 있다.
- 까닭 — 사용자 결정의 '다른 감사 행이 이미 싣는 것 밖의, 개인 정보가 될 수 있는 자유 글은 싣지 않는다'. 감사 행은 폐기(purge)가
  비우지 않는다(plan §5.2.6 — 감사 기록은 폐기 대상이 아니다). 다른 감사 행의 reason(좌석 넘김 · 완결 확인 · 쟁점 · 큐 결정의 사유)은 사람이
  그 조작에서 쓴 4~300자 사유인데, 등록부 note · verdict note 는 길이 제한이 없고 그 글의 자리가 따로 있다. 그래서 셋의 reason 은 늘 NULL 이다.

### AU-3. 언제 한 행인가
- 잡 — 러너가 전이를 썼고(결과에 state_at — `runner._set_job`) 잡 상태나 보류 코드가 달라졌을 때만. 끝난 잡의 취소(러너가 쓰지 않는다) ·
  멈출 수 없는 상태(409) · 남의 잡 · 모르는 조작(404) · 이미 그 상태(MCP changed:false — 라우트가 409 로 거절한 것을 입구가 돌려준다)는
  행이 없다. 도는 호출을 기다리는 검토 잡을 다시 취소하면 러너는 같은 cancelling 을 다시 쓰지만 바뀐 것이 없어 행이 없다. 코드 보류
  (llm_outage 따위)로 멈춘 검토 잡을 사람이 멈추면 상태는 paused 그대로 보류 코드만 user 로 바뀐다 — 자동 재개가 다시 세우지 않게 하는 사람의
  정지라 한 행이다.
- 등록부 — 바꾼 행마다 늘 한 행이다(같은 status 로 다시 정해도). 그 PUT 은 상태 기록 한 행을 새로 쓰고 verified · dismissed 면 새 근거의
  라벨을 세운다 — 사람의 결정 한 번이다.
- verdict — 확정마다 한 행이다(같은 값이어도). 라우트가 verdict_by · verdict_at 을 다시 찍는 사람의 확정이다.
- 둘의 차이 — 잡 제어는 전이라 바뀐 것이 없으면 조작이 아니고, status · verdict 는 결정이라 결정마다 기록(상태 기록 · 확정 시각)이 선다.

### AU-4. 사람 조작이 아닌 것 — 남기지 않는다(고른 쪽)
- 코드가 일으킨 전이는 감사하지 않는다 — 'system' 으로 표시해 싣는 쪽이 아니라 빼는 쪽을 골랐다. rr_audit 는 사람 행위 한정이고(DDL 주석 ·
  plan §0.6 — 자동 전이는 각 표의 *_source · state_by 로 가른다), 시스템 행을 넣으면 '사람 개입 요약' 과 대상 감사가 그것을 다시 걸러야
  한다. 일일 상한 정지와 그 자정 재개 · 줄어드는 수확 · 코드 보류(검토 잡) · 자동 재개 · 재기동 복구 · 집기(queued → running) · 취소의
  마감(cancelling → cancelled) · 야간 잡이 그렇다. 코드의 정지 · 보류는 rr_jobs.state_by 에 'code:…' 를 적는다(종전 그대로). 집기 · 취소의
  마감은 주체를 적지 않는다(state_by 는 앞 값 그대로 — 종전부터).
- 엔진 쪽 멈춤(A24) — 포털 화면 · 운영 창구에서 사람이 패널 심의를 멈추면 러너가 그 패널을 닫고 잡을 멈춘다(state_by code:cancelled).
  사람의 행위는 에이전트 서버에서 일어났고 앱의 잡 정지는 러너의 반응이라 남기지 않았다. 멈춘 사람은 엔진이 알린 값으로 패널 · 잡의
  error 글에 남는다(앱이 확인한 신원이 아니다).
- 다른 사람 조작에 딸린 효과 — 폐기는 진행 중 잡을 cancelled 로 닫지만 그 사람 행위는 project.purge 한 행(폐기 보고서의 jobs_cancelled)이고
  잡마다 job.cancel 을 더 쓰지 않았다(한 행위를 두 번 세지 않는다). 실패 셀 넘김(cells.skip)이 동의를 기다리던 잡을 이어 돌리는 재개도 그
  행의 after.job.resumed 로 이미 남는다(D-49).
- 사람 라벨(`POST /findings/{id}/labels`)이 등록부 status 를 label_manual 로 바꾸는 길은 이번 셋 밖이다 — 그 행위는 rr_labels(labeled_by)와
  상태 기록에 남는다(AU-7).

### AU-5. 트랜잭션과 계약
- 정지 · 재개 · 등록부 status · verdict 는 전이와 감사 행이 한 트랜잭션이다(재개의 동의 몫 옮기기 resume_gate 도 같이 — 거절되면 아무것도
  남지 않는다). 등록부 status 의 라벨이 422 로 되돌아가면 감사 행도 같이 되돌아간다. 정지는 종전에 트랜잭션 없이 읽고 썼다 — 이제 한
  트랜잭션이다.
- 취소는 커밋 뒤에 쓴다 — 검토 잡의 취소는 제 트랜잭션에서 닫고 그 밖에서 전문가 보고서를 다시 짓는다(runner.cancel_job · M3C-81). 바깥
  트랜잭션으로 감싸면 다시 짓는 동안 저장소를 쥔다. 그래서 앞 값은 취소 직전에 읽고(그 사이 루프가 상태를 바꾸면 앞 값이 한 걸음 늦을 수
  있다), 확인과 취소 사이에 루프가 잡을 끝냈으면 러너가 쓰지 않아 행이 없다(시험).
- 잡 제어 셋을 `JOB_ACTIONS` 하나로 부른다(종전 재개만 runner.resume_job 을 바로 불렀다 — 같은 함수다).
- `registry.set_status` 가 `changes[{target_key, from_status, status_log_seq}]` 를 돌려주고 라우트가 그것으로 행을 쓴 뒤 응답에서 뺀다 — REST
  응답 · MCP 계약 · 화면은 그대로다. status_log_seq 는 라벨 훅의 applied=0 기록이 붙기 전의 그 행 자신의 seq 다(응답의 status_log_seq 는
  종전처럼 마지막 행의 것).
- '사람 개입 요약' 은 action 별 한 줄(BL-4 의 꼴)이라 job.cancel · job.pause · job.resume · registry.status · verdict.final 줄이 선다. 정본
  §4.7.3 의 '잡 제어 n · status 변경 n' 은 이 action 줄들이다 — 묶어 세는 줄은 만들지 않았다(옛 타깃 골든은 이 길을 지나지 않아 그대로다).

### AU-6. 시험 · 변이 · 전체 시험
- 새 시험 `tests/test_human_control_audit.py` 아홉 — 잡 셋(입구 web · rest, 대상 감사 · 요약) · 거절과 할 일 없는 조작 · MCP(mcp ·
  actor_verified 0 · 다시 부름) · 검토 잡의 보류 코드(코드 보류 → 사람 정지 → 재개 → 취소) · 도는 호출을 기다리는 검토 잡의 다시 취소 · 확인과
  취소 사이에 끝난 잡 · 러너 전이(일일 상한 · 집기 · 취소의 마감 · 엔진 쪽 멈춤 A24 — 사람 행 둘만) · 등록부 status(대상마다 · 남의 같은 열쇠 ·
  글 없음 · 과제 감사) · verdict(확정마다 · 글 없음). 옛 코드(7b1042d)의 스크래치 사본에 얹으면 여덟이 진다(행 없음) — 지나는 하나(확인과
  취소 사이에 끝난 잡)는 지킴 시험이다.
- 고친 옛 시험 하나 — `test_p6_routes` 의 손 신원(type('I'))에 source 칸을 더했다(진짜 Identity 의 꼴 — test_project_patch 의 손 신원과 같은
  고침). 등록부 status 라우트가 이제 신원 출처로 입구를 가른다.
- 변이 22/22 — 잡(state_at 조건 · 앞뒤 같음 조건 · 보류 코드 · MCP 검증 · 과제 id · action 이름 · 취소 감사 · 정지 재개 감사 · 입구 · 재개의
  앞 값) · 등록부(맨 열쇠 자리 · seq · note 를 reason 에 · 앞 status · set_status 의 앞 status · 과제 id · 감사 뺌 · 입구와 검증) · verdict(쓴
  뒤 읽은 앞 · note 를 reason 에 · 입구 · 감사 뺌). 스크래치 사본에서만 바꾸고 되돌린 뒤 __pycache__ 를 지웠다(사본과 작업 트리 diff 0).
- 전체 시험(공유 잠금, e21ca9a — 이 줄을 더한 커밋과 코드가 같다) — 3,722 통과 · xfail 4 · 실패 0(rc 0, 12분 56초). ruff — 바꾼 파일은
  깨끗하다.
- 하지 않은 것 — 배선 리허설(`tests/synth/rehearsal_d.py`)은 프로세스를 띄우는 일이라 돌리지 않았다(카드 대조 사슬은 바꾸지 않았다). 서비스
  재기동 · push · 병합은 없다.

### AU-7. 남긴 것
- 사람 라벨 경로(`POST /findings/{id}/labels` — 정본 §7.6 경로 5)가 등록부 status 를 label_manual 로 바꾸는 것은 감사 행이 없다 — 그 행위는
  rr_labels(labeled_by)와 상태 기록에 남는다. 화면 · MCP 가 부르지 않는 REST 길이다(결정 필요 — 남기면 registry.status 와 같은 꼴로 바꾼 행마다).
- 엔진 쪽 멈춤(A24)을 사람 행위로 셀지(엔진이 알린 사람을 검증되지 않은 행위자로 — 입구 어휘에 엔진 자리가 없다) — 지금은 러너의 반응으로
  둔다(AU-4, 결정 필요).
- MCP risk_job_action 의 changed 는 상태만 견준다 — 코드 보류로 멈춘 검토 잡을 사람이 멈추면 감사 행은 서는데 changed 는 false 다(종전부터 —
  이번 줄 밖).
- MCP 입구로 만든 잡의 job.create 행은 actor_verified 1 이다(종전부터 — 같은 입구의 다른 행은 0, 이번 줄 밖).
- 포털 정본 문면(포털 세션) — §8.2.3 잡 제어 본문의 `{reason≤200}`(앱은 사유를 받지 않는다) · '사람 개입 요약' 의 묶음 이름(앱은 action 줄) ·
  등록부 status 감사의 자리(바꾼 대상마다 '<대상>#<클러스터>')와 칸(글 없음).
- 화면(화면 세션) — 대상 감사 '이력 탭'(B34)에 새 action 셋(job.pause|resume|cancel · registry.status · verdict.final)의 이름표.

## 사람 조작 감사 — 반대 검토 뒤 고침(가지 `wt1031/risk-audit`, 16f2595 위, 2026-10-31)

> 반대 검토 지적 둘(중간 1 · 낮음~중간 1)을 고치기 전 코드(16f2595)에서 시험으로 먼저 재현했다 — 둘 다 재현됐다. 고친 뒤 같은 시험이 지난다.
> 지적마다 아래 한 절이고 AU-4 · AU-5 · AU-7 의 일부를 뒤집는다. 코드 커밋은 bcff65e(지적 1) · 69e18d6(지적 2)다.

### AU-8. 잡 취소의 감사 행은 취소를 쓰는 그 트랜잭션 안에서 쓴다(AU-5 일부 뒤집음 · 반대 검토 중간)
- 재현 — 도는 호출이 없는 검토 잡을 취소하면 runner.cancel_job 이 제 트랜잭션에서 cancelled 를 커밋하고, 건드린 전문가 보고서를 전문가마다
  다시 지은 뒤에야 돌아왔다. 라우트는 그 뒤에 job.cancel 을 썼다. refresh_cancelled 를 예외로 바꾸면 다시 짓는 동안 원장은 cancelled · 행 0
  이고 끝난 뒤에도 행이 없었다(그 사이 앱이 멈춰도 같다). 앞 · 뒤를 트랜잭션 밖에서 읽어, 라우트가 확인한 뒤 러너가 집고(queued → running)
  취소 바로 뒤에 마감하면(cancelling → cancelled) 사람 행이 queued → cancelled 였다. 패널 갈래는 트랜잭션 없이 첫 확인의 상태로 정해, 첫
  확인 바로 뒤에 집힌 잡에도 곧바로 cancelled 를 썼다(도는 패널이 있는데 cancelling 을 건너뛴다).
- 고침 — `runner.cancel_job(…, on_change=)` 가 `_set_job` 바로 뒤, 같은 `store.tx()` 안에서 훅을 부른다. 앞 값은 그 트랜잭션 안의
  `_job_row` 로 읽은 {state, hold_code} 다. 패널 · 쟁점 갈래도 잡을 그 트랜잭션 안에서 다시 읽고 그 값으로 정하고 쓴다(`_untry_after_cancel`
  은 종전처럼 그 뒤). `refresh_cancelled` 는 종전처럼 커밋 뒤다 — 다시 짓는 동안 저장소를 쥐지 않는다(M3C-81). 라우트의 취소 갈래는 그 훅으로
  `_audit_job_control` 을 부른다. 끝난 잡의 취소에는 훅을 부르지 않는다.
- 뒤 값 — 지적은 `_set_job` 결과로 잡으라 했다. 같은 트랜잭션 안에서 잡 행을 다시 읽는 것(`_job_control_view`)과 값이 같고(그 사이 다른 쓰기가
  끼지 못한다 — 저장소 잠금 · BEGIN IMMEDIATE), 패널 잡의 `_set_job` 결과에는 보류 코드가 없어 읽는 쪽을 골랐다. 정지 · 재개와 같은 함수다.
- `_audit_job_control` 의 결과 state_at 조건(끝난 잡의 취소를 거르던 것)은 훅이 대신해 뺐다 — 정지 · 재개는 늘 쓰거나 거절한다.
- AU-5 의 '취소는 커밋 뒤에 쓴다 · 앞 값이 한 걸음 늦을 수 있다' 는 더는 맞지 않는다. 확인과 취소 사이에 끝난 잡은 종전대로 행이 없다.

### AU-9. 포털 화면의 '멈춤'(엔진 쪽 멈춤 A24)이 잡을 멈추면 그 사람의 job.pause 다(AU-4 · AU-7 일부 뒤집음 · 반대 검토 낮음~중간)
- 결정의 근거 — 사용자 결정 10-31 은 포털 세션의 물음 '잡 멈춤 · 재개 · 취소, 등록부 상태 변경, 판정 확정 같은 사람 행동도 감사 행으로
  남길까요?' 에 대한 사용자의 답 '남긴다 — 계획서대로' 다. 이 작업에 전달된 범위는 `/jobs/{id}/{action}` 과 '사람의 요청으로 같은 일을 하는
  MCP · 러너 길' 이다. A24 는 사람이 포털 화면에서 누른 '멈춤' 으로 러너가 잡을 멈추는 길이라 그 범위에 든다. 반대 검토는 (가) 메일일 때만
  job.pause 를 쓴다 · (나) 지금처럼 빼고 '사용자가 확인함' 을 남긴다 가운데 사용자 확인을 권했다. 이 고침은 전달된 범위대로 (가)를 했다. 사용자가
  (나)를 고르면 69e18d6 하나를 되돌린다(AU-4 의 뺌으로 돌아간다).
- 재현 — Tier B 패널이 도는 동안 delib cancelled(by 멈춘 사람의 메일)가 오면 러너는 잡을 paused · state_by code:cancelled 로 멈추는데 rr_audit 에
  행이 없었다. 멈춘 사람의 메일은 잡 · 패널의 error 글에만 있었다.
- 고침 — `engine_client.collect_stream` 이 by 를 `EngineStreamLost.by` 따로 된 칸으로 넘긴다(앱이 놓은 스트림은 None). `runner._close_panel_stream_lost`
  가 잡의 확인 · 정지와 감사 행을 한 트랜잭션으로 하고, `_audit_engine_stop` 이 by 가 메일('@' — 신원 모듈이 SSO 단언에 쓰는 잣대)일 때만
  `rr_audit(scope job · action job.pause · actor_verified 0 · channel web)` 한 행을 쓴다. 행위자는 소문자로 적는다(다른 감사 행과 같다). 앞 · 뒤는
  잡 상태와 보류 코드뿐이고 멈춤 글은 싣지 않는다. '운영'(운영의 루프백) · 빈 값은 신원이 없어 쓰지 않는다.
- 칸을 고른 까닭 — 앱이 확인한 신원이 아니라 엔진이 알린 값이라 actor_verified 0 이다(포털은 세션 + CSRF 로 그 대화의 주인만 받는다).
  입구 어휘(web · rest · mcp · import — CHECK)에 엔진 자리가 없고 사람이 누른 곳이 포털 웹 화면이라 web 이다.
- 두 번 세지 않는다 — 사람이 앱에서 먼저 멈춘 잡(라우트가 행을 썼다)에 멈춤 사건이 뒤따라도 러너는 잡이 아직 돌 때만 멈추므로 행이 없다. 앱이
  놓은 스트림(정지 · 취소를 들은 should_stop)은 by 가 없어 쓰지 않는다.
- 잡 행의 state_by 는 종전대로 code:cancelled 다 — 이 고침은 감사 행만 더한다. 쟁점 잡의 패널도 같은 함수를 지난다.

### AU-10. 시험 · 변이 · 전체 시험(반대 검토 고침)
- 새 시험 다섯 함수(여덟 항목, `tests/test_human_control_audit.py`) — 지적 1 셋(다시 짓기 실패에도 남는 행 · 러너가 취소 앞뒤로 옮기는 잡 · 첫
  확인 바로 뒤에 집힌 잡) · 지적 2 둘(멈춘 사람 매개 넷 — 메일 · 대소문자 섞인 메일 · '운영' · 없음, 앱에서 먼저 멈춘 잡). 고친 시험 하나 — 러너
  전이 시험에서 A24 를 '행 없음' 으로 보던 몫을 뺐다(새 시험이 그 자리를 본다). 고치기 전 코드(16f2595)의 스크래치 사본에 얹으면 다섯이 진다 —
  지나는 셋('운영' · 없음 · 앱에서 먼저 멈춘 잡)은 지킴 시험이다. 지적 1 만 고친 코드(bcff65e)에서는 메일 둘이 진다.
- 변이 17/17 — 지적 1 일곱(취소 감사를 다시 짓기 뒤로 · 검토 취소 훅을 커밋 뒤로 · 패널 취소의 트랜잭션 안 다시 읽기 뺌 · 앞 값을 쓰기 뒤에 읽음
  · 패널 훅 뺌 · 검토 cancelling 훅 뺌 · 앞뒤 같음 조건 뺌) · 지적 2 열(by 안 넘김 · 감사 호출 뺌 · 메일 검사 뺌 · 소문자 뺌 · 검증됨 · 입구 rest ·
  과제 id 없음 · 앞 값을 뒤 값으로 · 도는 잡이 아니어도 씀 · 멈춤 글을 reason 에). 스크래치 사본에서만 바꾸고 되돌린 뒤 __pycache__ 를 지웠다(사본과
  작업 트리 diff 0). 처음 판의 지킴 시험은 '도는 잡이 아니어도 씀' 을 살렸다 — 사람이 스트림 전에 멈추면 러너의 물음(should_stop)이 먼저 스트림을
  닫아 멈춤 사건에 닿지 않았다. 첫 프레임과 멈춤 사건 사이에 멈추게 고쳐(물음은 5초 동안 앞 답을 쓴다) 죽였다.
- 전체 시험(공유 잠금, 69e18d6 — 이 줄을 더한 커밋과 코드가 같다) — 3,730 통과 · xfail 4 · 실패 0(rc 0, 12분 15초). ruff — 바꾼 파일은 깨끗하다.
- 하지 않은 것 — 서비스 재기동 · push · 병합 · 배선 리허설(카드 대조 사슬은 바꾸지 않았다).

### AU-11. 남긴 것
- AU-7 의 사람 라벨 경로 · 포털 정본 문면 · 화면 이름표는 그대로 열려 있다. 포털 정본 문면에는 A24 멈춤의 job.pause(엔진이 알린 사람 ·
  actor_verified 0 · web) 한 줄이 더 붙는다.
- A24 로 멈춘 잡 행의 state_by 는 code:cancelled 그대로라 감사 행(사람)과 다르다 — state_by 까지 사람으로 바꾸는 것은 이번 지적 밖이다.

## 사람 조작 감사 — 남긴 줄 셋 고침(가지 `wt1031/risk-gaps`, int1031/risk4 b71a262 위, 2026-10-31)

> 사용자 결정 10-31 — 사람 조작 감사(AU-7 · AU-11)가 남긴 줄 가운데 셋을 지금 고친다. MCP 로 만든 잡의 job.create 가 actor_verified 1 ·
> 코드 보류로 멈춘 검토 잡을 MCP 로 멈추면 감사 행은 서는데 changed 는 false · 이력 탭에 새 행위 다섯의 이름표가 없다. 가지는 감사 가지
> (6f345d0)에서 떴는데 화면 파일(B34 이력 탭)이 그 판에 없어, 아무것도 올리기 전에 통합 판 int1031/risk4(b71a262 — 백엔드는 6f345d0 과 바이트가
> 같다)로 앞감기한 뒤 일했다. 코드 커밋은 4eea6b6(1) · c232e55(2) · 29a3bc3(1 · 2 지킴 시험) · 77e5480(3)이다.

### AU-12. MCP 길의 감사 행은 입구 mcp · actor_verified 0 이다 — 같은 실수를 MCP 가 닿는 자리 전부에서(남긴 줄 1)
- 규칙은 하나다(AU-1 · M3C-8) — channel 은 신원 출처(`AUDIT_CHANNELS` — 쿠키 web · Bearer rest · 게이트웨이 위임 mcp)이고 actor_verified 는
  channel != 'mcp' 다. 잡 제어 · 보류 풀기(coverage.undefer) · 셀 처분(cells.*)은 그렇게 적었다.
- 훑은 범위 — 앱의 MCP 쓰기 도구(mcp_server · entry)가 부르는 라우트와 그 아래(sameas · rekey)에서 rr_audit 를 쓰는 자리 전부. 모든 MCP 쓰기는
  위임 단언(source sso)으로만 오므로(entry.require_delegate) 이 자리의 행은 늘 mcp · 0 이어야 한다.
  - 입구만 적고 검증을 빠뜨린 자리 — job.create(검토 잡 · Claude 패널 잡, risk_start_job) · brief.exclude(같은 도구) · target.flow
    (risk_open_target 의 flow) · project.ecad_board(risk_set_ecad_board 의 붙이기 · 떼기).
  - 둘 다 기본값(rest · 1)이던 자리 — gate.ack(risk_ack_gate) · finding.create(risk_add_finding) · panel.repersist · panel.repersist_discard
    (risk_repersist_panel) · rekey(risk_decide_sameas 가 확정을 reject 로 뒤집을 때 — rekey.run 이 검증 1 을 SQL 에 글자로 박았다).
- 고침 — 그 자리마다 같은 꼴(channel = AUDIT_CHANNELS.get(ident.source, 'rest') · actor_verified = channel != 'mcp'). rekey.run ·
  rekey.revoke_iface_alias 가 actor_verified 를 받고, sameas.record_decision 이 channel · actor_verified 를 받아 키 전파 넷(reject · merge_key ·
  unmerge_key · revoke_iface_alias)에 넘긴다. post_sameas_decide 가 신원 출처에서 한 번 정한다 — 한 요청의 행은 한 입구다(MCP 도구가 닿는 것은
  확정 · reject 뿐이지만 같은 라우트의 다른 갈래만 기본값으로 남기면 한 요청 안에서 입구가 갈린다).
- 웹에도 바뀐 것 — 웹(쿠키)으로 한 gate.ack · finding.create · panel.repersist(_discard) · rekey 는 이제 입구 web 이다(종전에는 칸을 주지 않아
  rest). 규칙을 하나로 쓰면 따라오는 바뀜이라 그대로 두었다 — 입구 칸으로 걸러 세는 곳은 없다(대상 감사 · 과제 감사 · '사람 개입 요약' 은
  action 으로 센다). Bearer 는 그대로 rest · 1 이다.
- 바꾸지 않은 것 — MCP 도구가 닿지 않는 REST 전용 감사 자리(project.update · project.mcp_visibility · member.put · project.transfer ·
  project.purge · requirement.decide · gate.ack 취소 · coverage.skip|uncarry · close.ack(.revoke) · issue.* · registry.merge(.revoke) ·
  registry.visibility · finding.update · finding.delete · recall.approve · curation.decide · vocab.edit · 계면 원장 reject 의 rekey)는 종전대로
  기본값이다. entry · mcp_server 가 그 함수들을 부르지 않는 것을 확인했다. 이 앱의 REST 를 게이트웨이 rest_call 의 사람별 단언으로 열면 그
  자리들도 rest · 1 로 적힌다 — dev 게이트웨이의 REST 사이트 표에는 이 앱이 없다. 열게 되면 같은 꼴로 고친다. ra_client 의 ra.retract ·
  ra.remark 는 REST 조작(비공개 전환 · 폐기 · 이양)을 뒤따라 쓰는 행이라 MCP 가 닿지 않는다.

### AU-13. MCP risk_job_action 의 changed 는 감사 행과 같은 판정이다(남긴 줄 2)
- 틀린 쪽은 changed 다. 행은 계획대로다(AU-3) — 코드 보류(llm_outage 따위)로 멈춘 검토 잡을 사람이 멈추면 상태는 paused 그대로 보류만 user 로
  바뀐다. 자동 재개가 다시 세우지 않게 하는 사람의 정지(P-10 · runner.pause_job)라 한 행이다. 입구는 라우트 밖에서 읽은 상태만 견주어 false 라
  했다(답의 hold_code 는 user 인데).
- 같은 뿌리의 반대 어긋남도 있었다 — 확인과 취소 사이에 러너가 잡을 끝냈으면 취소는 아무것도 쓰지 않아 행이 없는데, 입구는 앞 상태(queued)와
  답(completed)을 견주어 changed true 라 했다(시험으로 재현).
- 고침 — `routes.job_control` 이 (러너의 답, 바뀜)을 돌려준다. 바뀜은 `_audit_job_control` 이 행을 썼는가다(전이와 같은 트랜잭션 안의 앞 · 뒤
  {state, hold_code}). 취소는 on_change 훅이 불렸고 그 훅이 썼는가다(끝난 잡의 취소는 훅이 불리지 않는다). REST 라우트는 답만 돌려준다 —
  응답 계약 그대로이고 REST 에 changed 칸을 더하지 않았다. 입구는 그 바뀜을 changed 로 싣고 라우트 밖의 앞 상태 읽기를 뺐다. 이미 그 상태(라우트
  409)는 종전대로 changed false · 행 없음이다.
- MCP 도구 설명('이미 그 상태면 그대로 돌려주고(changed:false)')은 그대로 맞아 바꾸지 않았다 — 코드 보류 위의 사람 정지는 '이미 그 상태' 가
  아니다(보류가 user 로 바뀐다).

### AU-14. 화면 — 이력 탭의 이름표와 전 → 후(남긴 줄 3)
- 자리 — 화면에 대상 감사 탭은 따로 없다. B34 의 이력 탭은 과제 이력(`ProjectAuditCard` — GET /projects/{id}/audit)이고, 다섯 행은 그 대상의 과제
  id 를 실어 거기에 선다(AU-1).
- 이름표 — 종전 사전(코드는 글자 그대로, 뜻만 붙인다)에 다섯을 더했다 — 잡 일시정지 · 잡 재개 · 잡 취소 · 등록부 상태 바꿈 · 판정 확정. 말은 그
  조작의 단추(일시정지 · 재개 · 취소… · 상태 저장 · 확정)를 따랐다. 거름 선택지에도 '말 코드' 로 선다.
- 전 → 후 — 종전에는 canonical JSON(키 차례)이라 잡 행이 `{"hold_code":null,"state":"queued"} → …` 였다. 다섯의 앞 · 뒤는 코드 어휘 몇 칸뿐이라
  값을 글자 그대로 잇는다 — 잡은 상태(보류 코드가 있으면 '· 보류 <코드>'), 등록부는 status(뒤에는 '· 상태 기록 #<seq>' — 사람이 쓴 글은 그 기록에
  있다), 판정은 값(처음 확정의 앞은 '없음'). 코드에 한국어 뜻을 덧붙이지 않았다 — 배지와 같은 '저장 값 = 보이는 글' 규칙이다(Badge.tsx · §8.2.4).
  그 밖의 행위와 꼴이 다른 값은 종전대로 JSON 이다(`auditChange`).
- 시험 — 이름표 사전과 거름 선택지(아직 읽지 않은 탭을 서버 렌더로 그린다) · auditChange 의 다섯 꼴과 되돌림 · 서버 꼴의 한 쪽으로 그린 표
  (`tests/auditTab.test.cjs` — 탭이 읽는 useAsync 를 그 파일 안에서만 바꿔 끼운다. node --test 는 시험 파일마다 프로세스를 따로 띄운다). 표 시험이
  없으면 '전 → 후 칸을 JSON 으로 되돌림' 변이가 산다(처음 판에서 살았다).
- 남긴 것 — '미확인' 배지의 풀이('게이트웨이 위임으로 확인되지 않은 행위자(자칭)')는 MCP 행에도 A24 멈춤 행(엔진이 알린 사람 · web)에도 꼭 맞지
  않는다(화면 세션 몫). 이름표가 없는 다른 행위(job.create · brief.exclude · gate.ack · finding.* · target.flow · cells.* · close.ack · issue.* ·
  panel.repersist · recall.approve · curation.decide · rekey · ra.* · registry.merge · registry.visibility …)는 이번 몫 밖이라 그대로다.

### AU-15. 사람 라벨 경로의 감사 — 닫음(메인 세션 10-31 의 plan §0.6 읽기)
- AU-7 의 '사람 라벨(`POST /findings/{id}/labels`)이 등록부 status 를 label_manual 로 바꾸는 것은 감사 행이 없다 — 결정 필요' 는 결정이 필요
  없다. 포털 정본 plan §0.6 '사람 개입 기록' 이 사람의 상태 변경은 rr_audit 한 행이되 '자동(코드·라벨 훅) 전이는 rr_audit 에 넣지 않고 각 표의
  *_source 열로 구분한다' 고 한다. 라벨이 일으킨 status 변경은 라벨 훅 전이(status_source label_manual)이고 라벨 자체는 rr_labels(labeled_by)에
  남는다. 그래서 감사 행 없이 둔다(코드 변경 없음).

### AU-16. 시험 · 변이 · 전체 시험
- 백엔드 새 시험 — `tests/test_mcp_audit_actor.py` 여덟 함수(열 항목 — 도구마다 MCP 행 (mcp, 0)과 웹 · REST 의 (web, 1) · (rest, 1), 키 전파 세
  갈래는 웹 · Bearer · 위임 단언 매개 셋) · `tests/test_human_control_audit.py` 셋(코드 보류 위의 사람 정지에서 다시 취소까지 changed 가 행 수의
  변화와 같다 · 도는 호출을 기다리는 검토 잡의 다시 취소 · 확인과 취소 사이에 끝난 잡). 옛 코드(b71a262)의 스크래치 사본에 얹으면 열하나가 진다 —
  지나는 둘(키 전파 Bearer 매개 · 다시 취소)은 지킴 시험이다. 고친 시험 하나 — test_gate_ack 의 손 신원에 source 칸(진짜 Identity 의 꼴).
- 지킴 시험 둘은 변이를 세다 더했다(29a3bc3) — MCP 가 닿지 않는 키 전파 세 갈래는 검증된 신원(웹 · Bearer)으로만 보면 검증 넘김을 빼도 살고,
  훅이 불렸는데 바뀐 것이 없는 경우가 없으면 '앞뒤가 같아도 참' 이 산다. 변이 결과에서 그 다섯은 각각 그 매개 · 그 시험이 처음 잡았다.
- 백엔드 변이 33/33 — 입구 25(create_job 입구 고정 · job.create 둘 · brief.exclude · target.flow · ECAD 둘의 검증 뺌, gate.ack 입구 고정 · 검증
  1 · 검증 0, finding.create 입구 고정 · 검증 1, repersist 입구 고정 · 둘의 검증 뺌, sameas 라우트 입구 고정 · 검증 1, record_decision 의 넷
  넘김 뺌 여섯, rekey INSERT 의 1 박기, revoke_iface_alias 안 run 의 넘김 뺌) · changed 8(행을 써도 거짓 · 같아도 참 · 취소 바뀜 늘 참 · 늘 거짓 ·
  정지 재개 뒤집기 · 입구 늘 참 · 이미 그 상태도 참 · 상태만 보던 옛 판정). 스크래치 사본에서만 바꾸고(바이트코드를 쓰지 않고) 되돌린 뒤
  __pycache__ 를 지웠다(사본과 작업 트리 diff 0).
- 화면 — `pnpm test` 90 통과(87 + 3) · `tsc -b && vite build` 통과(크기 경고는 종전 그대로, 이 프런트에는 eslint 설정이 없다). 옛 화면(b71a262)
  사본에 새 시험을 얹으면 셋 다 진다(87 은 지난다). 변이 12/12 — 이름표 뺌 · 바꿈 · 보류 코드 · 상태 기록 번호 · '없음' · job.cancel 꼴 뺌 ·
  되돌림 조건 · verdict_final 칸 확인 · 표 칸을 JSON 으로 · 거름 선택지 이름표 뺌 · 형 확인 둘(tsc).
- 전체 시험(공유 잠금, 77e5480 — 이 줄을 더한 커밋과 코드가 같다) — 3,743 통과 · xfail 4 · 실패 0(rc 0, 14분 5초 — 앞 판 3,730 에 새 시험
  항목 13). ruff — 바꾼 파일은 깨끗하다.
- 하지 않은 것 — 서비스 재기동 · push · 병합 · 실 브라우저(표는 서버 렌더로 봤다) · 배선 리허설(카드 대조 사슬은 바꾸지 않았다).

## 이력 탭 이름표 전부 · '미확인' 풀이(가지 `wt1031/risk-labels`, main 4145b2c 위, 2026-10-31)

> 사용자 결정 10-31(사람 조작 감사 이름표와 같은 갈래 — 메인 세션 후속) — AU-14 가 남긴 둘을 고친다. 앱이 쓸 수 있는 감사 행위 전부에
> 이름표를 붙이고 빠지면 지는 시험을 둔다 · '미확인' 배지 풀이를 행을 쓴 길마다 바로 적는다. 코드 커밋은 01a9f8d(1) · 88d32d9(2)다.

### AU-17. 이름표 — 앱이 쓰는 행위 39 가지 전부
- 행위 목록은 앱 소스에서 끌어냈다. rr_audit 에 쓰는 자리는 넷이다 — routes._audit 의 INSERT · rekey.run 의 SQL 글자 'rekey' ·
  runner._audit_engine_stop 의 SQL 글자 'job.pause'(A24) · ra_client._audit_retract 의 매개 조건식(ra.retract | ra.remark). routes._audit 을
  부르는 곳은 routes · planner · review_runner 이고, 행위는 글자 · 조건식(recall.approve | curation.decide) · 함수 안 대입(put_coverage 의
  coverage.skip | uncarry) · f-string 셋(job.{JOB_ACTIONS} · issue.{ISSUE_ACTIONS} · cells.{dispose_cells 가 받는 retry | skip})이다. 모두 39
  가지 — 이름표가 있던 것 15, 더한 것 24.
- 말은 화면의 단추 · 안내 글을 따랐다 — gate.ack '게이트 ack 붙이기 · 취소'(ack 취소도 같은 행위 이름으로 쓴다 — after.revoked) · cells '셀
  다시 열기 · 셀 넘김' · issue '쟁점 올리기 · 건너뛰기' · close.ack '잔여 확인(취소)' · finding '사람 finding 올림 · 고침 · 지움' · rekey '키
  전파' · ra 'RA 거두기 · 다시 표기' 따위. DDL 주석에만 있는 이름(project.lifecycle · project.classification · gate.ack.revoke ·
  finding.add|edit|delete · import.conflict)은 앱이 쓰지 않아 붙이지 않았다(실제로 쓰는 이름은 project.update · gate.ack ·
  finding.create|update|delete).
- 다 이 탭에 서는 것은 아니다 — 과제 이력(GET /projects/{id}/audit)은 project_id 로 고른다. 과제 id 를 싣지 않는 행(gate.ack ·
  registry.merge(.revoke) · registry.visibility · vocab.edit · 과제 id 없는 rekey)은 대상 감사(REST)에만 선다. 사전은 행위의 뜻이라 다 둔다.

### AU-18. 빠지면 지는 시험 — 백엔드 시험이 앱 소스(AST)와 화면 사전을 견준다
- 자리는 `backend/tests/test_audit_action_labels.py` 다. 화면 시험(node)은 파이썬 소스를 믿을 만하게 읽지 못하고 백엔드는 AST 로 쓰는 자리를
  정확히 훑는다. 화면 소스를 읽는 백엔드 시험은 이미 있다(test_client_contract 가 risk.api.ts 를 읽는다). 그래서 앱 코드도 공유 목록 파일도
  더하지 않았다 — 백엔드 변경은 시험 하나다.
- 끌어내는 법 — `INSERT INTO rr_audit` SQL 을 부르는 호출마다 action 칸(열 목록에서 그 자리를 찾는다)을 읽는다. SQL 글자면 그것, 자리표면
  매개 튜플의 그 자리 식을 푼다. 그 식이 감싼 함수의 매개면(routes._audit) 그 함수를 부르는 곳의 action 인자를 푼다. 푸는 꼴은 글자 ·
  조건식 · 함수 안 대입 · f-string(앞 글자마다 앱의 열거 — FAMILIES)이고, 풀 수 없는 식 · 모르는 f-string 꼴은 실패한다(조용히 빠뜨리지
  않는다). 쓰는 꼴마다 하나씩 실제로 찾는지 따로 본다(훑기가 녹슬어 빈손으로 지나가지 않게).
- 화면 사전은 정규식으로 읽는다(ACTION_LABEL 블록의 "열쇠": "말"). 사전이 옮겨 가면 그 자리를 알리며 진다. 말이 빈 이름표도 없는 것으로 센다.
- 이 시험은 백엔드 전체 시험에서 돈다 — 화면만 고치는 세션의 `pnpm test` 는 이것을 보지 않는다(화면 시험에는 'job.create 이름표' 와
  '모르는 행위는 이름표 없음' 만 남겼다).

### AU-19. '미확인' 배지 풀이 — 행을 쓴 길마다
- 종전 '게이트웨이 위임으로 확인되지 않은 행위자(자칭)' 는 틀렸다. MCP 행의 행위자는 바로 게이트웨이가 위임으로 넘긴 신원이고(앱은
  게이트웨이의 서명만 본다 — 그 사람을 직접 확인하지 않아 0), A24 행은 에이전트 서버가 알린 사람이다. 어느 쪽도 자칭이 아니다.
- 백엔드가 actor_verified 0 을 쓰는 자리는 셋이다 — MCP 길(입구 mcp, AU-12) · 포털 '멈춤'(입구 web 의 job.pause, AU-9) · RA 거두기의 모르는
  행위자(actor system, 입구 rest — RS-36). `unverifiedTitle` 이 그 셋을 가르고 그 밖은 '앱이 직접 확인한 신원이 아닙니다(입구 …)' 다. '멈춤'
  풀이는 웹의 job.pause 에만 준다 — 웹의 다른 행위나 다른 입구의 job.pause 에 빌려 주지 않는다. 배지 글은 그대로 '미확인' 이다.

### AU-20. 시험 · 변이
- 1 — 4145b2c 사본에서 이름표 시험이 진다(빠진 24 를 쓰는 자리와 함께 말한다). 변이 14/14 — 화면 쪽 셋(이름표 뺌 · 말 비움 · 열쇠 오타)과
  앱 쪽 열하나(RA 조건식 갈래 · JOB_ACTIONS 하나 더 · dispose_cells 검사 하나 더 · ISSUE_ACTIONS 하나 더 · 함수 안 대입 · SQL 글자 둘 ·
  쓰는 함수 글자 · 새 f-string 꼴 · 조건식 갈래 · 쓰는 함수 이름 — 마지막은 녹슮 지킴이 잡았다). 화면 시험 하나를 고쳤다(job.create 에 이름표가
  생겼다).
- 2 — 01a9f8d 사본에서 화면 시험 둘이 진다(89 는 지난다). 변이 7/7 — 처음 판에서 '멈춤 갈래의 입구 조건 뺌' 이 살았다(오늘 쓰는 행으로는 같은
  답이다). 다른 입구의 job.pause 단언을 더해 죽였다.
- 화면 — pnpm test 91 · tsc -b · vite build 통과(각각 rc 0). 백엔드 — 이름표 시험 · test_client_contract 통과, ruff 깨끗. 앱 코드를 바꾸지
  않아 백엔드 전체 시험은 돌리지 않았다. 변이는 스크래치 사본에서만 바꾸고 되돌린 뒤 __pycache__ 를 지웠다(사본과 작업 트리 diff 0).
- 하지 않은 것 — push · 병합 · 재배포 · 실 브라우저(표는 서버 렌더로 봤다).

## 화면 읽기 완결 10-31(가지 `wt1031/risk-reads`, main dbe5f93 위, 2026-10-31)

> 화면 세션(FE-14 · FE-30 끝)이 청한 읽기 일곱이다 — 과제 상세 · 목록 · 스냅샷 상태의 ack · 키 대장 읽기 · `GET /sameas` 의 pair_key · 진행판
> signals · 병합된 키의 confirm_key. 화면은 '모름' 이던 칸이 서면 고치지 않고 보이는지를 실 응답 견본으로 확인했고, 서버 동작이 바뀌어 거짓이 된
> 글과 서버 값으로 바꿀 자리만 고쳤다. 커밋 — 212f4a4(과제) · f4e9a96(스냅샷 · 키 · 대응 · 진행판) · a9e9cb3(confirm_key 409) · 1d0c88a(화면) ·
> 2bb6314(C3 자동 후속 — 의도된 동작). 같은 때 도는 가지 `wt1031/risk-audit` 와 routes.py 에서 겹치는 함수는 없다 — 이 가지는
> `list_projects` · `projects_payload` · `get_project` · `snapshot_part` · `get_sameas` · `coverage_payload` 를 고치고 `_with_live_acks` ·
> `get_part_key` · `part_key_payload` 를 더했다(그 가지는 `job_action` · `put_verdict` · `put_registry_status`).

### RD-1. 과제 상세는 구성원이 연다 — 주인 검사 → 구성원 검사
- `GET /projects/{id}` 는 `_project_row`(주인 검사) 대신 `require_role(viewer)` 를 지난다 — 편집자 · 보기는 200, 남은 없는 과제와 같은 404 다
  (글자까지 같다 — 시험이 견준다). `_project_row` 는 그대로 둔다 — 같은 함수를 쓰는 다른 길(POST /projects 의 답 · 성격 · 유사 · 요구 · MCP
  쓰기 입구)은 주인 검사 그대로다.
- 대상 · 잡은 부른 사람이 아니라 과제의 주인(rr_projects.owner_sub — 하위 표 owner_sub 는 그 복제다)으로 고른다. 종전처럼 부른 사람으로
  고르면 구성원에게 대상 · 잡이 빈 표다(변이로 확인했다).
- 과제 행에 메타 열(routes.PROJECT_META_COLS) — `corpus_excluded` 는 bool, `product_refs_json` 은 푼 배열(없으면 [])이다. PATCH 의 답은 종전대로
  열 그대로(0/1 · JSON 글자)다 — 화면의 knownMeta 가 둘 다 푼다.
- `members` 는 응답 머리의 칸이다(plan §8.2.3 표의 `{project, members[{email, role}], …}` · 화면 타입 ProjectDetail.members 의 자리) — 과제 행 안이
  아니다. 소유자 행도 실린다(_members_of 차례).
- 스냅샷 머리 — `label`(그 스냅샷을 만든 동결 잡의 이름 — rr_snapshot_jobs 를 LEFT JOIN, MCP 길잡이 `entry._snapshots` 와 같은 출처. 동결 잡 없이
  언 것 · 옮겨 온 것(반출에 동결 잡이 없다)은 null) · `app_versions` · `adapter_versions`(푼 객체) · `degraded_json`(푼 배열 — `degraded` 는 첫 값인
  호환 열 그대로). IR 의 label 은 읽지 않았다(스냅샷마다 IR 전체를 풀어야 한다).

### RD-2. 과제 목록 — 소유 ∪ 구성원, 카드마다 내 역할
- 웹 목록은 소유하거나 구성원인 과제다 — 조직 공개(org)만으로는 들지 않는다(MCP `visible_projects` 와 다르다). `projects_payload` 는 과제 id
  목록과 viewer 를 받는다(쓰는 곳이 없어진 owner_sub 인자는 걷었다). MCP `risk_list_projects` 도 부른 사람을 viewer 로 넘긴다 — service · 조직
  공개로만 보이는 과제는 my_role null.
- `my_role` 은 `project_role` 과 같은 판정이다 — 주인 열이 먼저, 아니면 멤버 행. owner 멤버 행이 없는 과제도 주인에게 owner 다(시험은
  seed_raw — 생산자는 owner 행을 늘 함께 쓴다).

### RD-3. 스냅샷 상태의 ack — rr_gate_acks 가 정본, 낡은 ack 는 싣지 않는다
- `part=state` 는 동결 때의 state_json 이라 ack 칸이 늘 null 이었다(ack 는 gates_json · rr_gate_acks 에만 갔다). 응답에서만 rr_gate_acks 의 지금
  ack 를 게이트에 얹는다 — state_json · gates_json 은 바꾸지 않는다. 취소된 것(revoked_at) · 비교 스코프(diff_id 가 선 것) · 단 때의 판정
  지문(rr_gate_acks.gates_hash)이 지금 지문과 다른 것은 싣지 않는다. 판정은 IR 만의 함수라 지금은 지문이 바뀌지 않지만(다시 세는
  compute_state_for_snapshot 을 부르는 곳이 없다) 판이 바뀐 계산이 다시 세면 앞 판정에 단 ack 를 새 판정에 붙이지 않게 그 열의 뜻(DDL 주석 —
  'ack 는 stale')을 따랐다.
- `gates_hash` 를 응답에 싣는다 — ack 칸을 뺀 판정만의 지문(state.gates_hash)이라 ack 로는 바뀌지 않고, ack 라우트가 gates_json 으로 세는 값과
  같다(시험이 같음을 보고 그 값을 실어 다시 ack 해도 409 가 아니다). MCP `risk_get_snapshot(part='state')` 도 같은 함수라 같이 받는다.
- `GET /sameas` 의 G2 도 지금 ack 를 얹는다(RD-13 에서 고쳤다). 이 줄은 처음에 '그대로 load_state 원문이다(이번 범위 밖 — 그 G2 의 ack 를
  읽는 화면이 없다)' 였는데 틀렸다 — SameAsResolver 가 그 G2 를 게이트 표로 그리고 배지 · ack 열이 record.ack_by 를 읽는다(반대 검토 10-31).

### RD-4. 키 대장 읽기 — `GET /part-keys/{ckey}`
- 경로 꼴 하나만 열었다(`?ckey=` 는 두지 않았다 — 같은 일을 두 길로 열지 않는다). 답은 `{ckey, status, merged_into, display_name, aliases[],
  decided_by, decided_at}`.
- 범위 — 원장 행은 주인(owner_sub — 그 키를 처음 적립한 과제 주인)의 것이다(쓰기 결정도 주인만 — record_decision 이 owner_sub 로 건다). 주인은
  별칭 전부, 그 키가 든 과제(행의 first_project_id · 별칭의 project_id)의 구성원은 제 과제의 별칭만 본다(주인의 다른 과제 id · 부품 이름을 흘리지
  않는다). ckey 는 이름 · 크기 · 재질의 해시라 사람 사이에 겹친다 — 남의 스냅샷 노드가 같은 ckey 를 달아도 그 노드의 과제로는 열지 않는다(남의
  원장 행의 이름 · 결정자를 흘린다). 남과 없는 키는 같은 404 E404 다 — 남 시험 표(tests/rr/test_review1_stranger.py)에 경로를 더했다.
- 별칭 열은 목록이거나 cross_project 승계 제안을 품은 객체(`{items, merged_candidates}` — sameas.inherit_ckeys)라 items 를 편다. 제안은 싣지 않는다
  (청한 칸 밖).
- `merged_into` 는 열 그대로다 — 유효 키 해석은 status merged 일 때만 따르므로 화면은 status 로 가른다(RD-6 의 옛 행).

### RD-5. `GET /sameas` 의 pair_key · 진행판 `job.signals`
- `pair_key` 는 그 표가 쌍 원장을 읽은 열쇠 그대로다. 화면은 확정 · 거부 본문에 그 값을 싣고, 두 스냅샷 상태를 더 받아 과제 id 로 짓던
  길(compareView.samePairKey)은 걷었다 — 화면과 서버는 한 앱(SIF 하나 · 서버가 frontend/dist 를 낸다)이라 옛 서버 갈래를 둘 일이 없다.
- `signals` — 러너는 대상마다 패널을 하나씩만 돌린다(claim_next_job 이 그 대상에 도는 패널이 있으면 건너뛴다 · planner.check_invariants (2)
  'running 패널 ≤1'). 잡의 concurrency 칸(화면 '동시 실행 ≤2')은 저장만 되고 러너가 읽지 않는다 — risk_concurrency(2)는 대상 둘을 함께 돌리는
  전역 자리 수다. 그래서 FE-14 청할 것 7 의 '동시 2 에서 덮인다' 는 한 잡 안에서는 일어나지 않고, signals 는 많아야 한 줄이며 signal 과 같다.
  계약은 목록으로 열어 두었다 — 한 잡이 패널을 함께 돌리게 되면 러너가 신호를 패널마다 적어야 한다(_progress_writer 는 잡 행 하나를 덮어쓴다).
  화면의 신호 줄(JobSignalLine)은 고치지 않았다 — 보이는 것이 같다.

### RD-6. confirm_key 의 병합 키 — 409 key_merged(merged_into 를 비우지 않는다)
- 두 길 가운데 거절을 골랐다. merged_into 만 비우면 행은 confirmed · 병합 없음으로 맞아 보이지만 병합 때 돈 키 전파(rekey — 저장 키 · 등록부 ·
  별칭)가 되돌아가지 않아 원장과 파생이 어긋난다. 비우면서 키 전파까지 돌리면 unmerge_key 와 같은 일을 이름이 다른 결정이 하게 돼, '확정' 을 누른
  사람의 병합이 풀린다(화면은 그때 키 상태를 몰랐다). 거절은 병합을 푸는 길을 키 전파 · 감사(rr_audit rekey)가 함께 도는 unmerge_key 하나로
  남긴다 — 되돌린 키는 이미 confirmed 라 따로 확정할 일도 없다. detail `{ckey, merged_into}`. 배열(POST /sameas/decide)은 한 트랜잭션이라 함께
  보낸 결정도 되돌아간다(시험).
- 옛 행 — 이 고침 전의 confirm_key 가 남긴 행(status confirmed · merged_into 남음)은 유효 키 해석으로는 독립 키지만 병합 때의 키 전파는 그대로다.
  고치는 길은 넣지 않았다(남은 것 — unmerge_key 는 status 가 merged 일 때만 키 전파를 돈다). 박스에서
  `SELECT ckey, merged_into FROM rr_part_keys WHERE status <> 'merged' AND merged_into IS NOT NULL` 로 셀 수 있다.
- 화면 — 키 대장 패널이 키 상태를 읽어 병합된 키의 '독립 키로 확정' 을 잠그고 까닭(먼저 병합 되돌리기)을 말한다. 확인 글의 '병합돼 있으면 그
  병합도 풀립니다' 는 이제 거짓이라 걷었다.

### RD-7. C3 자동 후속 Tier C 는 GLM 이다 — 의도된 동작(바꾸지 않는다)
- Claude 로 돈 Tier B 잡 뒤에 러너가 세우는 C3 자동 후속(_finish_job → create_job, consent_source close_level)은 llm · consent_external 을 물려받지
  않는다 — GLM 이다. 반출 동의는 잡마다 사람이 한다(사용자 결정 10-15) — 사람이 동의하지 않은 잡이 그 대상의 자료(브리프 · 좌석 조회 결과)를
  Claude 로 보내지 않는다. 그 Tier C 도 Claude 로 돌리려면 사람이 그 잡을 만들며 동의한다. 메모 · 층 · 뺀 항목은 물려받는다(BL-10).
- 지키는 시험 — test_claude_panel_jobs.py `test_the_c3_follow_up_of_a_claude_tier_b_job_stays_on_glm`(옛 코드에서도 통과한다 — 동작을 굳힌 것)과
  runner._finish_job 의 그 자리 주석.

### RD-8. 화면 — '모름' 칸과 거짓이 된 글
- 이름 그대로 읽는 것을 실 응답 견본으로 확인했다 — 과제 메타 카드(knownMeta 가 detail.project 의 열 이름을 읽는다 — '모름' 이 없어진다) · 홈
  카드 거름(네 칸) · 게이트 표(record.ack_by — 다시 읽은 서버 값이 이긴다) · 신호 줄. 고치지 않고 선다(옛 화면 코드에서도 그 시험 넷이 통과).
- 고친 것 — 닫은 때(closed_at)는 PATCH 답에서만 읽어 과제를 다시 열면 사라졌다(상세의 열도 읽는다) · 게이트 ack 의 '새로 열면 이 줄이 보이지
  않습니다' 꼬리(거짓이 됐다) · 대응표의 pair_key(서버 값) · 키 대장 패널(지금 상태 줄 · 404 E404 는 '원장에 없거나 내 원장이 아니다' · 병합된
  키의 확정 잠금 — 패널을 읽기(KeyLedgerPanel)와 본문(KeyLedgerBody)으로 나눠 본문을 견본으로 그려 시험한다).
- 타입 — Project 메타는 물음표 그대로(POST /projects 의 답은 싣지 않는다). ProjectCard 넷 · ProjectDetail.members · SnapshotHeader 넷 ·
  SnapshotState.gates_hash · SameAs.pair_key · CoverageJob.signals 는 필수, 새 PartKey · PartKeyAlias. 견본 일곱(과제 상세(편집자) · 목록 · 상태(ack) ·
  대응표 · 키 둘 · 패널 잡)을 스크래치 백엔드의 실 응답에서 옮겼고(상태는 신호 · 규칙 · 씨앗 · 특징 벡터를 앞 몇 개로 줄였다) 스냅샷 머리 견본은
  새 칸으로 다시 받았다.
- 고치지 않은 것(화면 세션 몫) — 과제 화면 스냅샷 표에 이름 · 판 · 강등 표지 전부 · '파서 세대 다름' 을 미리 보이는 일(서버는 이제 싣는다) ·
  대상 표의 unseated_n · superseded_by(이 응답에 없다 — FE-7 의 남긴 것).

### RD-9. 시험 · 확인 · 남긴 것
- 백엔드 새 시험 아홉 — tests/test_project_reads.py 둘 · tests/test_screen_reads.py 여섯 · test_sameas.py 하나. 옛 코드(dbe5f93 의 app/) 사본에
  얹으면 아홉 다 진다(KeyError classification · 구성원 과제 없음 · ack null · gates_hash 없음 · get_part_key 없음 · pair_key 없음 · signals 없음 ·
  DID NOT RAISE). 고친 시험 둘(GLM 잡 진행판 칸 집합에 signals · 남 시험 표의 경로 — 둘 다 옛 코드에서 진다), 지키는 시험 하나(RD-7, 옛 코드에서
  통과).
- 변이(스크래치 사본, 바이트코드 끔) — 백엔드 22/22(구성원 검사 · 대상 거름 · bool · 배열 · 멤버 · 이름 · 강등 표지 · 목록 범위 · 내 역할 · 카드
  bool · 취소된 ack · 낡은 ack · 비교 스코프 ack · 지문 · 구성원 별칭 · 남 열기 · 객체 별칭 · pair_key 정렬 · signals 둘 · confirm_key 둘), 화면
  컴파일 산출물 7/7.
- 화면 — tests/reads.test.cjs 일곱(87 → 94). 옛 화면 코드에 얹으면 tsc 가 깨지고(PartKey 없음) 셋이 진다(닫은 때 · 키 줄 · 키 패널). `tsc -b` ·
  `vite build` · `pnpm test` 통과.
- 전체 시험(공유 잠금 아래 한 번, 코드 HEAD 2bb6314, 12분 52초) — 3,724 통과 · 실패 0 · xfail 4(rc 0). ruff — 바꾼 파이썬 파일은 깨끗하다.
- 하지 않은 것 — 서비스 · 인스턴스 기동 · 정지, push · 병합, 실 브라우저 확인(견본 렌더 · 계약 시험만 — 편집자로 과제 화면 열기 · 키 대장 패널 ·
  대응 확정 단추는 브라우저로 보지 않았다).
- 남긴 것 —
  1. 구성원 읽기는 과제 상세 · 목록(과 이미 열려 있던 멤버 · 이력 · 대상 감사)까지다. 스냅샷 · 대상 · 진행판 · 성격 · 유사 · 요구 · 등록부 읽기는
     아직 주인만이라(`_snapshot_row` · `_target_row` · `_project_row` 의 주인 검사) 편집자가 과제 화면을 열면 스냅샷 · 대상 링크와 성격 · 유사 탭이
     404 를 받는다 — plan §14 의 두 계정 시나리오는 구성원이 스냅샷 · 타깃 · 등록부를 읽는다고 적는다(다음 걸음 — 읽기 전부를 구성원에게 열지 결정).
  2. 옛 confirm_key 가 남긴 행(RD-6) 고치기.
  3. 잡의 concurrency 칸은 러너가 읽지 않는다(RD-5) — 화면 '동시 실행 ≤2' 칸과 계약을 둘지(결정 필요).
  4. 같은 초에 선 두 패널 잡이면 진행판의 `job` 이 uuid 순으로 앞 잡을 고를 수 있다(coverage_payload 의 `ORDER BY created_at DESC LIMIT 1` — FE-22
     끝 3 의 검토 잡과 같은 꼴, 시험을 짜다 났다).
  5. 이번 범위 밖의 청할 것 — FE-14 끝 4(동결 때 요구 대조) · FE-30 끝 2 · 5 · FE-22 끝 1 ~ 4 · 1차 걸음의 셋.

### 화면 읽기 완결 — 반대 검토 고침(10-31)

> 반대 검토가 확인한 지적 다섯(High 1 · Medium 1 · Low 3)을 고쳤다. 다섯 다 스크래치 사본에서 그 검토의 탐침(A ~ H)으로 먼저 재현했고,
> 고친 뒤 같은 탐침이 반대로 나온다. 커밋 — f560f34(들여오기 · 과제 읽기) · a73f7ca(키 대장 mine) · 956812c(게이트 글) · c1edf3c(대응표 G2) ·
> 7ac4ea7(닫은 때). routes.py 에서 손댄 함수는 `_project_sources` · `list_projects` · `projects_payload` · `get_project` · `project_role` ·
> `_with_live_acks` · `get_sameas` · `part_key_payload`(+ `get_part_key` 글) — 같은 때 도는 `wt1031/risk-audit`(`job_action` · `put_verdict` ·
> `put_registry_status`)와 겹치지 않는다. 그 밖에는 export.py(`import_jsonl` · 새 `_refusal`)와 state.py(새 `gate_line` · `restate_gate_acks`).

### RD-10. 들여오기는 남의 과제에 매달린 줄을 받지 않는다(High — 뿌리는 이 가지 앞, 이 가지가 넓혔다)
- 재현(탐침 A · D · G, HEAD 77e2525) — 남이 `{table: rr_project_members, row: {project_id: 주인의 과제, owner_sub: 자기, role: owner}}` 한 줄을
  들여오면 `inserted 1` 이었다(본문 owner_sub 가 부른 사람이면 받았고 project_id 는 보지 않았다). 그 뒤 과제 상세 200(기밀 메타 · 멤버 · 대상) ·
  목록 my_role owner · 키 대장 200, 스냅샷 · 동결 잡 줄로 주인과 구성원의 스냅샷 머리에 남이 지은 이름 · 판이 섰다. main dbe5f93 에서도 같은
  행으로 이양이 됐다(남이 과제를 가져가는 길 — 이 가지 앞부터).
- 고침 — `export._refusal` 이 쓰는 줄(새 행 · 사람 확정 병합 둘 다 — 병합도 부모 열을 고쳐 쓴다)의 부모 열을 본다. 범위 부모(반출 `_select`
  가 그 줄을 싣는 거름의 차례 — 과제 열 → 대상 열쇠 → 스냅샷(스냅샷 없는 호출 원문은 동결 잡) → 비교의 두 과제 → 비교)는 이 박스에 있고
  부른 사람 것이어야 하고, 그 밖의 부모 열(base · target · first 의 과제 · 스냅샷, first_target_key, rr_targets.ref_id — kind 로 스냅샷 ·
  비교)은 있으면 부른 사람 것이어야 한다(제 대상으로 남의 스냅샷을 가리켜 그 상태를 브리프로 읽는 길). 남의 것과 없는 것은 같은 까닭
  `parent_not_owned` 다 — 있는지를 흘리지 않고, 없는 부모를 받으면 주인이 뒤에 옮겨 올 과제 · 대상 id 에 미리 심어 둘 수 있다(예 —
  'snap:<스냅샷 id>' 대상의 queued 잡). 같은 들여오기에서 앞서 들어간 부모도 된다 — 줄을 TABLE_ORDER 로 안정 정렬해 쓴다(반출은 이미 그
  차례다). 멤버 owner 행은 그 과제 주인의 이메일만 받는다(`owner_row_immutable` — put_members 와 같은 규칙). predecessor_project_id 는 보지
  않는다(D44 — 계보 읽기가 거른다).
- 읽기 쪽(고침 전에 이미 선 행 몫 — 이제 들여오기로는 못 만든다) — `project_role` 은 owner 를 과제 행의 주인 열에서만 준다(주인 아닌 사람의
  owner 멤버 행은 역할이 아니다 — 이양 · 상세가 그 행으로 열렸다). 목록 · 카드의 내 역할도 같은 판정이다(멤버 행은 편집자 · 보기만 — RD-2 의
  '주인 열이 먼저, 아니면 멤버 행' 을 좁혔다). 과제 상세 · 목록은 대상 · 잡처럼 스냅샷 · 소스 · 성격 태그 · 카드의 마지막 스냅샷도 과제 주인의
  행만 싣고, 스냅샷 머리의 이름은 같은 주인의 동결 잡만 잇는다(RD-1 의 LEFT JOIN — 옮겨 온 스냅샷의 끊긴 잡 id 에 남이 제 과제의 잡 행을
  들여와 이름을 다는 길이 남는다, 그 들여오기는 제 과제라 받는다). 스냅샷 상태의 ack 행도 그 스냅샷 주인의 것만 얹는다(RD-3 의 새 읽기 —
  ack 라우트는 주인만 쓴다). `_project_sources` 는 JOIN 으로 고쳐 다른 부르는 곳(MCP 입구 · 동결 · ECAD)도 같다 — 생산자는 소스 행을 과제
  주인으로만 쓴다(add_source · put_ecad_board 가 주인 검사).
- 남긴 것 — 고침 전에 선 남의 편집자 · 보기 멤버 행은 아직 역할이다(project_role 뿐 아니라 MCP visible_projects · brief 구성원 · runner 도
  멤버 행을 그대로 믿는다). 그런 행을 만드는 길은 들여오기뿐이었다. 박스에서 센다 — 생산자(create · put_members · transfer)는 멤버 행의
  owner_sub 를 늘 과제 주인으로 쓰므로 `SELECT m.project_id, m.email, m.role FROM rr_project_members m JOIN rr_projects p ON p.id = m.project_id
  WHERE m.owner_sub <> p.owner_sub` 가 0 이어야 한다(하위 표도 같은 꼴 — owner_sub ≠ 과제 주인). 나오면 지울지는 사람이 정한다.
  화면 타입 ImportResult 의 conflicts 꼴은 쓰는 화면이 없어 고치지 않았다(owner_conflict 때부터 reason 칸을 모른다).
- 검사가 막는 정상 줄 하나 — 옛 주인의 키 대장 행(first_project_id)은 이양으로 옮겨 가지 않아 이양된 과제를 가리킨다. 새 주인의 그 과제가 이
  박스에 있으면 그 행은 parent_not_owned 로 눕는다(없으면 받는다 — 충돌 목록에 선다). 거꾸로 키 대장 행은 과제 범위가 없어, 남의 부품 ckey(이름 ·
  크기 · 재질의 해시)로 키 행을 미리 들여와 그 키의 주인이 되는 줄은 부모 검사로 막지 못한다 — 열쇠가 ckey 하나라 먼저 적립한 사람이 주인이
  되는 RD-11 남긴 것과 같은 뿌리다.

### RD-11. 키 대장 읽기의 `mine` — 결정은 내 원장 행만(Medium)
- 재현(탐침 B · E) — 동료 과제의 편집자, 이양받은 새 주인이 키 행을 읽으면 200(병합 · 이름 · 정한 사람)인데 결정 넷은 다 404 였고(record_decision 은
  owner_sub = 부른 사람인 행만 고친다), 화면은 그 병합을 내 키처럼 말하며 '병합 되돌리기' 로 이끌었다. 그 사람의 유효 키 해석(resolve_ckey)은
  그 병합을 따르지 않는다.
- 고침 — 답에 `mine`(행 주인 == 부른 사람). 읽기 범위는 그대로다(구성원이 그 키의 상태를 보는 것이 화면 세션이 청한 일). 화면은
  `keyDecisionsBlocked` 로 결정 넷(이름 · 병합 · 되돌리기 · 확정)을 잠그고 '다른 사람의 원장 행' 이라 말한다 — 상태(status)로 가르지 않는다.
  404 도 잠근다 — 종전 화면은 404 에서 '결정도 받지 않습니다' 라 말하면서 단추는 열어 두었다(반대 검토는 404 갈래가 잠근다고 적었는데 실제로는
  열려 있었다 — 서버는 두 경우 다 404 라 함께 잠갔다). 못 읽은 것(그 밖의 실패)은 잠그지 않는다(결정의 거절 code 로 말한다).
- 견본 — partKeyMerged(보기 멤버로 받은 것 — mine false) · partKeyNamed(주인 — true)에 칸을 더하고 partKeyMergedOwn(같은 병합 키를 주인으로 —
  확정만 잠긴다)을 더했다. 스크래치에서 같은 장면(같은 과제 id · 시각)을 고친 백엔드로 다시 세워 받았고 바이트까지 같다(mine 칸만 더해졌다).
- 남긴 것 — 이양은 rr_part_keys 를 옮기지 않는다(TRANSFER_PROJECT_TABLES 밖 — 원장 행은 그 키를 처음 적립한 사람의 것이고 열쇠가 ckey
  하나라 두 번째 주인의 행은 생기지 않는다, ir_builder 의 적립). 그래서 이양받은 새 주인은 그 과제의 키를 결정할 수 없다(옛 주인만 —
  시험이 그 404 를 적어 둔다). 고치려면 원장 열쇠를 (ckey, owner_sub) 로 넓히거나 이양이 키 행을 옮겨야 하는데, 둘 다 스키마(v5 블록)와 한
  사람의 여러 과제가 함께 쓰는 키 행이 걸려 결정이 필요하다.

### RD-12. 스냅샷 상태의 게이트 글도 지금 ack 를 말한다(Low)
- 재현(탐침 F) — G3 에 ack 를 붙인 뒤 gates.G3.ack_by 는 섰는데 같은 답의 `signals['gates.summary']` 값 G3.ack 은 false, 글과 summary_text 의
  [게이트] 줄은 'G3 fail(1, ack 없음)' 이었다(화면의 요약 카드 · 신호 목록 · '단발 심사 열기' 복사가 그 글을 그대로 쓴다).
- 고침 — `state.restate_gate_acks` 가 얹은 ack 로 그 신호의 값(ack) · 글과 [게이트] 줄을 다시 쓴다(같은 표기 `state.gate_line` — 동결 때의
  compute_signals · _summary_lines 도 이 함수를 쓴다). 게이트 줄은 고정 어휘라 판단어 린터에 걸리지 않아(네 꼴 실측) 동결 때에도 싸이지 않는다
  — 줄 머리로 갈아 끼운다. 저장된 원문은 그대로다. 화면은 고치지 않았다 — 상태 견본의 두 칸을 고친 백엔드의 실 응답으로 바꾸고 화면 시험이 그
  일치(게이트 표 · 신호 · 요약 줄)를 본다.

### RD-13. `GET /sameas` 의 G2 도 지금 ack(Low)
- 재현(탐침 C — 픽스처가 G2 fail 을 만들지 않아 상태 원문과 gates_json 의 G2 를 fail 로 바꿨다) — 상태 G2 ack_by 는 섰는데 대응표 G2 는 None.
  RD-3 의 '그 G2 의 ack 를 읽는 화면이 없다' 는 틀렸다(SameAsResolver 가 GateTable 로 그린다 — RD-3 에 고쳐 적었다).
- 고침 — get_sameas 가 대상 상태를 `_with_live_acks` 로 지난다. 시험이 대응표 G2 와 상태 G2 가 같은 레코드임을 본다(취소도).

### RD-14. 과제 메타의 닫은 때는 진행(active)이면 보이지 않는다(Low)
- 재현(탐침 H) — shipped 뒤 active 로 되돌려도 closed_at 이 남고, 화면이 이 가지부터 상세의 열도 읽어 '진행 active … 닫은 때 …' 가 섰다.
- 고침 — 화면이 lifecycle 이 active 면 닫은 때를 보이지 않는다. 서버 열은 고치지 않았다 — 열의 뜻이 'active 를 떠난 시각'(DDL 주석 · 포털
  plan)이고 PATCH 감사에 before/after 가 남는다.

### RD-15. 시험 · 확인
- 백엔드 — 새 시험 열(test_project_reads 여섯 · test_screen_reads 넷)과 고친 하나(키 대장 키 집합에 mine). 옛 코드(77e2525 의 app/)에 얹으면
  열하나 다 진다. 변이(스크래치 사본, 바이트코드 끔) 26/26 — 부모 검사 여섯(새 행 · 병합 · 없는 범위 부모 · 남의 부모 · 대상 ref_id · 멤버
  owner 행) · 범위 셋(대상 · 스냅샷 · 호출 원문의 잡) · 표 차례 · project_role · 목록 · 카드 역할 · 머리 · 이름 잇기 · 소스 · 성격 · 카드 마지막
  스냅샷 둘 · mine · ack 주인 · 게이트 글 넷 · 대응표 G2.
- 화면 — tests/reads.test.cjs 다섯을 더하고 키 대장 패널 시험 하나를 고쳐 나눴다(94 → 99). 옛 화면 코드에 얹으면 넷(새 견본) · 여섯(옛
  견본)이 지고, 새 타입은 옛 견본을 tsc 로 거절한다(mine 없음). 변이 10/10. `tsc -b` · `vite build` · `pnpm test` 통과. 실 응답 견본 넷(키 셋 ·
  상태의 두 칸)은 고친 백엔드의 응답과 같음을 확인했다.
- 전체 시험(공유 잠금 아래 한 번) — 3,734 통과 · xfail 4 · 실패 0(rc 0, 17분 49초). 코드는 7ac4ea7 과 같은 작업 트리다 — 남 시험 표의
  들여오기 면제 까닭 글만 수집 뒤에 고쳤고, 그 파일은 아래 커밋마다의 시험에서 돌았다. 커밋 다섯마다 그 판을 따로 풀어 대상 시험
  (test_project_reads · test_screen_reads · rr/test_review1_stranger · test_export_import)과 화면 시험 전체를 돌렸다 — 다 통과(백엔드 165 →
  168, 화면 94 → 99).
- 하지 않은 것 — 서비스 · 인스턴스 기동 · 정지, push · 병합, 실 브라우저 확인.
- 본 것(이번 범위 밖) — 손 픽스처(dyna 결과 포함)로 언 스냅샷의 ir_json 은 rr_ir.v1 스키마의 results `oneOf` 검증을 지나지 못한다(seed_raw 의
  검증이 잡았다 — 시험은 mcad 만의 스냅샷을 옮겨 심었다). 까닭은 보지 않았다.

## 리스크 흐름 10-31 — 화면 세션이 청한 결함 · 잡 / 쟁점 흐름(가지 `wt1031/risk-flow`, main dbe5f93 위, 2026-10-31)

> 화면 세션(FE-7 · FE-14 · FE-22 · FE-30 끝)이 백엔드에 청한 것 가운데 잡 · 쟁점 흐름 열 가지와 Tier C 후속 노트다. 화면이 '모름' 으로
> 비워 둔 칸은 서버가 채운 뒤 화면을 고치지 않고 보이는지(읽는 칸 이름이 같은지)까지 봤다 — 같으면 낡은 글만 고쳤고, 읽는 칸이 없던
> 셋(사슬 표지 · 패널 잡 보류 · 자동 등록 쉼)만 화면을 고쳤다. 같이 도는 가지 `wt1031/risk-audit`(잡 제어 · status 변경 감사)의 함수
> (job_action · put_verdict · put_registry_status · registry.set_status)는 건드리지 않았다 — 두 가지의 코드는 글자 충돌 없이 합쳐지고
> 작업 대장 두 파일의 끝 덧붙임만 겹친다. 커밋 046c327 ~ d4c565d.

### RF-1. 쟁점 행의 결과 칸(outcome_json)은 원장 값 그대로다(046c327)
- `routes._issue_row_out` 이 `_loads(…, None)` 을 불렀고 `_loads` 는 기본값과 같은 형만 돌려주므로 기본값 None 은 무엇을 읽어도 None 이었다
  (DB 에는 있다). 기본값을 빈 객체로 읽고 비면 null 이다. REST `GET /targets/{key}/issues` 와 MCP `risk_get_issues` 가 같은 함수다.
- 다른 모듈의 `_loads(…, None)`(closure · unit_live · synth)는 형 검사가 없는 다른 함수라 같은 결함이 아니다(확인만 했다).

### RF-2. 쟁점 결정 뒤 완결 캐시를 같은 트랜잭션에서 새로 쓴다(14ebb56)
- 올리기 · 건너뛰기가 완결의 수 · 잔여(쟁점 진행 · 미토의)를 바꾸는데 `rr_targets.closure_json` 이 그대로라 진행판 level_label ·
  qualifiers 와 `GET …/closure` 가 앞 값을 냈고, 그 basis_hash 로 보낸 확인이 409 residual_changed 였다(FE-20 의 '한 번 다시 세기' 가
  그것을 넘겼다 — 그 길은 그대로 둔다).
- 쓰는 자리는 쟁점 쓰기 · 감사와 같은 트랜잭션이다. 사람이 올린 쟁점이 세우는 GLM 쟁점 잡은 사슬 표지(chain_json)가 없어 완결이
  읽는 값(`_fresh` 의 사슬 잡 지문)을 바꾸지 않으므로 잡보다 먼저 써도 된다.

### RF-3. 요구 여유 — 동결이 대조하고 요구 편집이 다시 센다(ac16932)
- 종전에는 `freeze_snapshot` 이 `build_state(ir)` 만 불렀고 `compute_state_for_snapshot` 을 부르는 곳이 없었다 — rr_states 에
  `sig:req.margin` 이 없어 스냅샷 화면의 요구 여유 표가 늘 비었고 R-007 은 늘 평가 불가였다(plan P1 (20) 의 기준이 이것이다).
- `state.freeze_state` 를 동결과 다시 세기가 같이 쓴다 — 지금 요구 원장의 대조를 싣고 규칙은 동결 때와 같은 시드다(rules 를 주지
  않는다). 다시 세기에 `compute_state_for_snapshot` 을 쓰지 않은 까닭 — 그 함수는 rr_rules 의 active 규칙(학습이 올린 규칙만 있으면
  시드가 빠진다)으로 세므로 요구를 고쳤을 뿐인데 다른 규칙의 적중이 바뀔 수 있다. 규칙을 갈아 끼운 뒤의 재계산은 그 함수의 몫으로 둔다.
- 요구는 IR 에 들지 않는다 — IR 로 옮기는 셋(게이트 · 성격 씨앗 · 특징 벡터)은 요구 신호를 읽지 않음을 확인했다(씨앗 DSL 의
  `missing.*` 은 IR 의 결측을 읽는다). 그래서 ir_json · ir_hash 는 바이트 그대로다.
- `state.recompute_project_states` — 요구 등록(POST) · 상태(PUT — waived 는 대조하지 않고 여유 행이 status 를 싣는다) · 승계가 요구
  쓰기와 같은 트랜잭션에서 그 과제 스냅샷의 상태를 다시 센다. 검사에 걸린 편집은 상태도 다시 세지 않는다. 상태가 있는 스냅샷만이고
  폐기로 비운 상태(state_json '')는 건너뛴다.
- 게이트 ack — `save_state` 가 gates_json 을 통째로 덮으므로 지금 gates_json 에 붙은 ack 를 그대로 싣는다(빼면 사람이 붙인 ack 가
  사라진다). 판정은 같은 IR 이라 그대로고 gates_hash 도 같아 ack 는 낡지 않는다. 다시 센 state_json 의 게이트에도 ack 가 실린다
  (`part=state` 가 동결 때 원문이라 ack 를 싣지 않던 것 — FE-11 — 은 다시 센 스냅샷에서는 지금 값이 된다).
- 동기로 센다(과제의 스냅샷 수 × 상태 계산 한 번). 큐는 짓지 않았다 — 동결 한 번이 이미 같은 계산을 동기로 한다.
- 그 전에 언 스냅샷은 그 과제의 요구를 고치기 전까지 `req.margin` 이 없다 — 화면은 그 사실과 '요구를 저장하면 다시 센다' 를 보인다.

### RF-4. 같은 초에 선 잡은 넣은 차례(rowid)로 가른다(a57ff8b · 83411f1)
- 진행판 review.job(`review_payload`)과 셀 처분이 얹는 잡(`review_cells._latest_review_job`)이 `created_at DESC, id DESC` 라 같은 초면
  uuid 가 큰 앞 잡을 골랐다(하네스에서 났다). 사슬 단계(`chain_stage`)처럼 `created_at DESC, rowid DESC` 다.
- 같은 '마지막 검토 잡' 의 품질을 읽는 셋(`review_quality._latest_review_job` · `closure._quality` · `synth._quality_block`)도 함께
  바꿨다 — 하나만 바꾸면 한 진행판 안에서 잡 줄과 품질 · 완결 잔여가 다른 잡을 읽는다. 시험 하나가 다섯 자리를 다 본다(변이 다섯이 다
  잡혔다).
- 진행판의 패널 잡 줄도 같은 결함이었다(순서 열쇠가 created_at 하나 — 같은 초면 앞 잡) — RF-6 에서 그 줄을 고치며 rowid 를 더했다.
- 남긴 것 — 브리프의 패널 잡 메모(`brief.py` M 항목의 `created_at DESC, id DESC`)도 같은 꼴이다. 이번 범위(검토 잡)가 아니라 두었다.

### RF-5. 진행판 검토 잡에 사슬 표지 칸 `chain`(896e7c8)
- `params.chain is True`(M3 코드가 세운 잡) — 판정은 `chain.chain_marked` · 길잡이(`entry._chain_marked`)와 같다. 시험은 M3 잡(true)과
  v4 원장의 M2 잡(false)을 본다.
- 화면의 'M2 시절 잡 뒤의 사슬 시작' 은 그 칸으로 가른다(사슬 없음 · 마지막 검토 잡 completed · chain false · 대기 셀 0). 판 유무의
  어림을 걷었다 — 사람이 '다시 내기' 로 코드 조립 판을 세운 M2 시절 대상에도 사슬은 서지 않았으므로 단추가 서야 한다(길잡이도 판을 보지
  않는다).

### RF-6. 진행판 패널 잡에 hold_code · hold_until(83411f1)
- 외부 응답자 패널이 워커가 없어 멈춘 잡은 `pause_reason` 이 비고 `rr_jobs.hold_code` 가 external_worker 인데 줄에 그 칸이 없어 화면이
  '멈춘 까닭 — 모름' 이었다. 검토 잡 줄과 같은 두 칸이다. 화면은 정지 까닭이 없으면 보류 코드와 자동 재개 시각을 보이고(`panelJobPause`),
  external_worker 면 '워크플로를 다시 돌린 뒤 재개' 를 말한다.

### RF-7. 패널 잡의 반출 동의 글(7d40238)
- 패널 잡의 422 `consent_external_required` 가 검토 잡의 반출 글(지식카드 · 사슬이 이어 도는 쟁점 패널 · 종합 요약)을 썼다.
  `runner.PANEL_EGRESS_WARNING` — 그 잡이 돌리는 패널마다 브리프와 좌석 조회 결과가 나가고, 동의는 그 잡에만이며 C3 자동 후속 Tier C 는
  GLM 이다(RF-11). `check_llm_choice` 가 `warning` 을 받는다(검토 잡은 종전 글 그대로). 화면의 동의 글(`PANEL_EGRESS_WARNING`)은
  고치지 않았다 — 같은 뜻이다.

### RF-8. 자동 등록 안내의 꼬리를 뗐다(2172cb7)
- 설정의 '자동 등록' 스위치와 앱을 열 때의 자동 등록(화면 세션 B35)이 나왔다 — `AUTO_STOP_HINT` · `pat_unavailable_guidance` 의
  '곧 생긴다 — 그때까지는 운영자가 앱 데이터 DB 에서 끈다(켠다)' 와 포털 절차서 꼬리를 걷고, 등록 길에 '웹 리스크 앱을 열 때' 를 더했다.
  `entry.fix_register_pat`(길잡이 · 잡 만들기의 pat_unavailable 고칠 곳)도 같은 길을 말한다. 쓰는 곳이 없어진 `AUTO_SWITCH_RUNBOOK` 은 걷었다.
- '자동으로 등록된다' 낱말은 남겼다 — 다른 시험 다섯이 그 낱말로 안내를 알아본다.

### RF-9. 웹 등록 실패를 서버가 적고 due 가 그 쉼을 본다 — 화면의 브라우저 쉼을 걷었다(30e002c · a3aaec2)
- `PUT /me/portal-pat` 의 source web(브라우저가 받아 온 PAT — 앱을 열 때 · 설정의 버튼) 거절을 `web-<code>: <글>` 로 적는다(갈래는
  교환 실패와 같다 — portal_unreachable 은 일시). 붙여 넣은 PAT(manual)의 거절은 자동 등록이 아니라 적지 않는다.
- `auto_paused_until` — 게이트웨이 길(portal_pat_wanted, 종전 그대로)과 웹 길(GET /api/me 의 due)이 같은 쉼을 본다. due 는 받을 까닭이
  있고 쉼 밖일 때만 참이며 `paused_until` 이 쉼의 끝이다. 설정의 버튼은 쉼과 상관없이 되고 성공하면 기록과 쉼을 지운다.
- 기록이 하나라 쉼도 하나다(요청 그대로) — 게이트웨이 교환의 실패(Claude 에 넣은 PAT 탓 따위)도 앱을 열 때의 자동 등록을 쉬게 하고,
  웹 등록의 실패도 게이트웨이의 바람을 쉬게 한다. 화면은 그때 쉼의 끝과 마지막 실패를 보이고 버튼은 된다. 길마다 쉼을 나누려면 열이
  하나 더 든다(_user_prefs — 지금 열을 바꾸지 않았다, 결정 필요로 남긴다).
- 화면 — localStorage 쉼(`AUTO_HELD_KEY` · `createAutoHold` · `autoHoldOf` · 쉼 길이 상수 둘)을 걷었다. 탭 세션마다 한 번 문
  (sessionStorage)은 남겨 한 탭이 되풀이해 받지 않는다. 설정 화면은 서버의 쉼(`autoPausedUntil`)을 말한다. 이미 브라우저에 남은
  옛 표지(값 `{until, code}` — 토큰 · 계정 없음)는 읽지 않을 뿐 지우지 않는다.
- 서버가 적지 못하는 실패(네트워크 · 다른 5xx — 등록이 났는지 모름)는 쉼이 없다 — 새 탭이 다시 받는다. 그 PAT 는 FE-29 의 길(GET /me 의
  jti 로 가른 뒤 폐기)이 그대로 치운다.

### RF-10. 다시 토의 표기의 꼴을 하나로(f134686 · d4c565d)
- `_keep_verdict` 가 비어 있던 표기(사람이 다시 올린 결과 쟁점)에 at(그 시각) · round(그 쟁점이 고른 회차)를 채운다 — 근거가 바뀌어
  선 표기와 같은 칸이다. 이미 있는 at · round 는 그대로다(덮어쓰기 변이가 처음에 살아남아 시험을 더했다). 부르는 두 곳(resolve_issue ·
  release_issue)이 selected_round 를 읽는다. 10-31 전에 선 행은 label · new_panel_failed 뿐이라 화면 타입은 선택 칸 그대로다.

### RF-11. Claude Tier B 잡 뒤의 C3 자동 후속 Tier C 는 GLM 이다 — 정책(의도, 바꾸지 않는다)
- 러너의 `_finish_job` 이 닫힘 레벨 C3 에서 Tier B 잡 뒤에 세우는 Tier C 는 메모 · 층 · 브리프 제외(BL-10)를 물려받지만 판단 LLM(llm ·
  consent_external)은 물려받지 않는다. 반출 동의는 잡마다다(사용자 결정 10-15) — 사람이 그 잡에 동의하지 않았는데 시스템이 데이터를
  Claude 로 보내지 않는다. 검토 잡의 사슬(쟁점 · 종합)이 판단 LLM 을 물려받는 것과 다르다 — 그쪽은 동의 글(EGRESS_WARNING)이 사슬이
  내보내는 것까지 말하고 사람이 그 글에 동의한다. 패널 잡의 동의 글은 이제 '동의는 이 잡에만 — Tier C 후속은 GLM' 을 말한다(RF-7).
- 고정 — `_finish_job` 주석과 시험(`test_the_c3_follow_up_of_a_claude_tier_b_job_stays_on_glm` — 후속 params 에 llm · consent_external 이
  없고 자격은 GLM 잡의 순서). 바꾸려면 사람이 그 후속에 따로 동의하는 길이 먼저다.

### RF-12. 화면 · 서버 견본(a3aaec2)
- 읽는 칸 이름이 이미 서버와 같았던 둘 — 쟁점 결과 칸(`row.outcome_json` — 쟁점 한 줄의 덮은 값 · 펼친 칸)과 요구 여유
  (`state.signals["req.margin"]`)는 화면 코드를 고치지 않고 서버 값이 보인다(고치기 전 화면 사본에 새 견본을 넣어 돌린 시험이 통과한다).
  낡은 글(서버가 늘 null · 동결이 대조하지 않는다)만 고쳤다. 다시 토의 표기의 새 꼴도 그대로 그려진다(at · 회차 · 실패 줄).
- 고친 셋 — 사슬 표지(`chainStartVisible`), 패널 잡 줄의 보류(`panelJobPause` · TargetPage), 자동 등록 쉼(RF-9).
- 견본(`src/contract/serverSamples.ts`) — 이 가지 하네스(스크래치, 백엔드 시험 도구로 만든 원장)의 실 응답: 쟁점 목록을 새로 옮겼다
  (상향 · 닻 원자 없어 판정 못 함 · 상한 밖 — 결과 칸이 원장 값이다), 다시 토의 표기의 새 꼴(`issueRepanelFailedRow`), 보류된 Claude 패널
  잡의 진행판(`coveragePanelHeld`), 쉬는 PAT 요약(`portalPatPaused` — 박스 칸은 dev 호스트 이름이 들어 싣지 않았다), 상태의 요구 여유
  (`snapshotStateMargin`). 검토 잡 줄 견본 둘에는 chain(M3 잡이라 true)을 더했다.

### RF-13. 시험 · 변이 · 전체 시험 · 남긴 것
- 백엔드 새 시험 18(쟁점 2 · 요구 상태 4 · 검토 잡 3 · 패널 잡 3 · PAT 자동 등록 4 · 다시 토의 표기 2)과 계약이 바뀐 시험 6(검토 잡 줄 칸 ·
  패널 잡 줄 칸 · external_worker 보류 · /me auto 칸 · 안내 둘). 고치기 전 코드(dbe5f93 스크래치 사본)에 이 시험 파일을 넣으면 21이
  붉다 — 새 15 와 바뀐 6 이고, 남은 새 셋은 지킴 시험이다(검사에 걸린 요구 편집은 다시 세지 않음 · Tier C 후속 GLM · 근거 바뀐 표기의
  at · round 를 덮지 않음).
- 화면 시험 87 → 89(브라우저 쉼 시험 둘을 걷고 서버 쉼 · 저장 전 거절 · 요구 여유 견본 · 패널 잡 보류 넷을 더했다). 고치기 전 화면
  사본에 새 시험 · 견본을 넣으면 셋이 붉다(사슬 표지 · 패널 잡 보류 · 서버 쉼). `tsc -b` · `vite build` 통과.
- 변이(스크래치 사본) — 백엔드 25/25(덮어쓰기 둘은 시험을 더한 뒤), 화면 6/6.
- 리스크 전체 시험 한 번(공유 잠금) — 3,731 통과 · xfail 4 · 실패 0(rc 0, d260b83).
- 남긴 것 — 길마다 자동 등록 쉼 나누기(RF-9, 열이 든다 — 결정 필요) · 브리프 패널 잡 메모의 같은 초 고르기(RF-4) · FE-14 청할 것의
  나머지(과제 상세 메타 · 멤버 읽기 · 상태의 ack · 키 대장 · pair_key · 패널마다의 신호 · 스냅샷 머리 판 칸)와 FE-30 의 나머지(confirm_key
  병합 키 · 스냅샷 머리 degraded_json · 키 대장)는 이 가지의 범위가 아니다. 요구 라우트 셋은 지금도 과제 소유자만이다(plan 은 editor —
  접근 규칙은 바꾸지 않았다).

### 반대 검토 10-31 — 세 지적(RF-14 ~ RF-17, 커밋 1b05177 ~ e269f7a)

> 이 가지(8d42a84)를 본 반대 검토가 셋을 짚었다 — 셋 다 재현했고(고치기 전 코드에서 새 시험이 붉다) 고쳤다. routes.py 에서 손댄 곳은 자동
> 등록 쉼(auto_paused_until · portal_pat_auto · portal_pat_wanted), PUT /me/portal-pat 의 웹 거절 기록, 과제 폐기의 주석 하나다 — main
> b71a262(사람 조작 감사)이 바꾼 함수(job_action · put_verdict · put_registry_status · 감사 도우미)와 겹치지 않아 저절로 합쳐진다. 겹치는
> 것은 runner.cancel_job 한 줄이다(RF-14 끝).

### RF-14. 취소가 보류를 비운다 — 패널 · 쟁점 잡(1b05177 · e269f7a)
- 지적 — 보류 external_worker 로 멈춘 Claude 패널 잡을 주인이 취소하면(REST · MCP risk_job_action — 같은 runner.cancel_job) 패널 갈래가
  hold 를 주지 않아 hold_code 가 남았다. RF-6 이 진행판 패널 잡 줄에 보류를 실은 뒤로 cancelled 잡의 줄이 external_worker 를 싣고 화면의
  '멈춘 까닭' 이 '워크플로를 다시 돌린 뒤 재개' 를 말했다. 쟁점 잡(credential · external_config · external_worker 보류)도 같아 사슬 단계가
  취소된 잡에 보류를 실었다(길잡이 · 사슬 배지는 paused 일 때만 보류를 읽어 겉으로는 드러나지 않았다).
- 고침 — cancel_job 의 패널 갈래가 resume_job 처럼 보류가 있으면 `_HOLD_CLEARED` 를 준다(보류가 없던 잡의 문장은 종전 그대로). 검토 잡의
  취소와 과제 폐기는 이미 비웠다. 폐기 문장의 주석('패널 잡은 그 열이 늘 NULL')과 `_set_job` 의 hold 설명을 지금 사실로 고쳤다.
- 화면 — `panelJobPause` 가 paused 일 때만 까닭을 낸다(사슬 배지 · 판단 LLM 줄과 같은 규칙). 서버를 고치기 전에 취소된 잡의 원장에는
  보류가 남아 있어서다 — 원장은 고치지 않았다(이행을 더하지 않는다). 그런 줄이 있으면 화면은 '멈춘 까닭 — 모름' 이고 MCP 줄은 state
  cancelled 와 남은 보류를 함께 싣는다.
- 합칠 때 — main b71a262 이 같은 갈래를 트랜잭션(다시 읽기 · 쓰기 · on_change 감사)으로 감쌌다. 글자 충돌이 난다 — main 쪽을 두고 그 안의
  `_set_job(store, job_id, state, by=by)` 에 `hold=_HOLD_CLEARED if row["hold_code"] is not None else None` 만 더한다(`row` 는 트랜잭션
  안에서 다시 읽은 것, 주석 두 줄은 그 위로). 스크래치 클론에서 그렇게 풀어 합친 판의 관련 시험(사람 조작 감사 포함) 270 이 통과했고,
  보류된 잡의 취소 감사 행은 앞 {paused, external_worker} · 뒤 {cancelled, null} 이었다.

### RF-15. 자동 등록 쉼은 길마다 — 기록의 머리가 길을 말한다(659b251 · e269f7a)
- 지적 — RF-9 의 기록 하나 · 쉼 하나가 두 길을 함께 쉬게 했다. (A) Claude 에 넣은 PAT 의 청중 탓 교환 실패(widen_audience)가 앱을 열 때의
  자동 등록을 6시간 막았다 — 웹 길은 브라우저의 포털 세션으로 받아 Claude PAT 와 상관없는데 dbe5f93 에서는 due 가 참이었다. (B) 다른
  계정의 포털 세션으로 누른 설정 버튼 하나(web-pat_email_mismatch)가 Claude 길의 바람을 6시간 멈췄다. (C) 웹 실패가 기록을 덮어 Claude 길
  안내(pat_unavailable · risk_next_step · 잡 error)에서 Claude PAT 를 고치라는 글이 사라졌다.
- 고침 — `auto_paused_until(prefs, path=…)` 가 마지막 실패가 그 길의 것일 때만 쉰다. 길은 글의 머리로 가른다 — `web-<code>` 는 웹 길(PUT
  /me/portal-pat source web), 그 밖(교환 실패 `<code>` · 게이트웨이가 보낸 PAT 의 등록 거절 `register-<code>`)은 게이트웨이 길이다.
  GET /api/me 의 `due` · `paused_until` 은 웹 길의 것이고(게이트웨이 실패에는 due 참 · paused_until null), portal_pat_wanted 는 게이트웨이
  길의 쉼만 본다. 열은 더하지 않았다 — 머리가 이미 길을 말하고, _user_prefs 는 버전 밖 살림 표라 열을 더하면 옛 DB 에 ALTER 길이 든다.
- 결정(지적이 물은 것) — 사람이 누른 버튼의 실패는 Claude 길을 쉬게 하지 않는다. 버튼도 앱을 열 때의 자동 등록과 같은 브라우저 세션으로
  받으므로 웹 길만 쉰다(같은 까닭으로 또 거절될 PAT 를 새 탭마다 받지 않게 — 버튼 자체는 쉼과 상관없이 된다).
- 대가 — 기록은 하나라 다른 길의 실패가 덮으면 쉼도 그 길로 넘어가고 덮인 길은 한 번 더 해 본다(실패하면 제 글을 다시 적는다 — (C) 는
  다음 Claude 호출의 단언 발급에서 게이트웨이가 다시 실패하며 되찾는다). 두 길이 함께 실패하는 동안(박스 · 계정 탓 같은 까닭이거나 서로
  다른 까닭) 길을 바꿀 때마다 한 번씩 더 든다 — 게이트웨이는 4xx 면 새 PAT 를 폐기하고 화면은 저장 전 거절이면 받은 PAT 를 폐기한다(둘 다
  최선 노력이라 폐기가 실패하면 그 PAT 는 포털에 남는다 — 종전과 같은 길). 이것이 거슬리면 길마다 기록 열을 두는 것이 다음 걸음이다
  (지금은 하지 않았다).
- 화면 — 읽는 칸(`due` · `paused_until`)은 그대로라 동작은 고치지 않았다. 설정 글을 '앱을 열 때의 자동 등록을 쉰다 — Claude 에서 부를 때의
  등록은 쉬지 않는다' 로, 타입 · `autoPausedUntil` 주석을 웹 길의 쉼으로 고쳤다. 견본 `portalPatGatewayFailed`(게이트웨이 교환 실패 뒤의 실
  응답 — due 참 · paused_until null)에서 화면이 고치지 않고 받는다(`autoRegisterWanted` 참)는 시험을 더했다.
- 게이트웨이가 보내는 code 가 `web-` 로 시작하면 웹 길로 읽힌다 — 게이트웨이 code 는 정해진 어휘(AUTO_ERROR_TEMPLATES · http_* · unknown)라
  막지 않았다.

### RF-16. 동결의 요구 원장 읽기를 스냅샷을 넣는 트랜잭션 안으로(3cf27f3)
- 지적 — `freeze_snapshot` 이 `freeze_state`(요구 원장 대조)를 트랜잭션 앞에서 불렀다. 그 틈에 다른 요청이 요구를 저장하면 그 트랜잭션의
  `recompute_project_states` 는 아직 없는 새 스냅샷을 보지 못하고, 새 스냅샷은 옛 원장으로 센 상태로 들어가 다음 요구 편집까지 req.margin ·
  missing.req_absent · R-007 이 낡았다(드물지만 조용하다).
- 고침 — 상태 계산(과 IR 로 옮기는 게이트 · 씨앗 · 특징)을 `with store.tx():` 안, INSERT 앞으로 옮겼다. 저장소의 RLock 과 BEGIN IMMEDIATE 가
  동결과 요구 편집을 줄 세운다 — 요구 편집이 먼저면 동결이 새 원장을 읽고, 동결이 먼저면 요구 편집의 다시 세기가 새 스냅샷을 본다.
- 비용 — 잠금 안에서 상태 계산 한 번이 더 돈다. 합성 모델(부품 1,450 · 노드 1,985 · 엣지 2,591)에서 `freeze_state` 19 ms(동결 전체 약 2 초 —
  대부분 트랜잭션 밖 IR 조립)였다. 다른 시도(트랜잭션 안에서 요구 신호만 다시 세기)는 계산이 두 번이라 두지 않았다.
- 시험 — 두 스레드로 끼운다. `build_state` 를 감싸 첫 부름(원장을 읽은 뒤)에서 다른 스레드가 요구를 저장하게 하고 1초까지 기다린다. 고치기
  전에는 그 저장이 곧바로 끝나 새 스냅샷의 여유 행이 plate2_t 하나이고, 고친 뒤에는 저장이 동결의 잠금에 막혔다가 새 스냅샷까지 다시 센다
  (같은 스레드로 끼우면 트랜잭션이 재진입으로 합쳐져 고친 뒤에도 붉으므로 다른 스레드다).

### RF-17. 시험 · 변이 · 합친 판
- 백엔드 새 시험 6(취소 둘 · 길마다 쉼 셋 · 동결 끼우기 하나)과 바뀐 시험 1(웹 실패 뒤에도 게이트웨이 길은 바란다). 고치기 전 코드에서 8 이
  붉다(지적마다 재현 — 1: 2, 2: 5, 3: 1).
- 화면 시험 89 → 91. 고치기 전 화면 사본에 새 시험 · 견본을 넣으면 '멈춘 잡만' 하나가 붉고, 게이트웨이 견본 시험은 화면을 고치지 않고
  통과한다(읽는 칸 이름이 같다). 기존 패널 잡 시험의 손 견본에 state 'paused' 를 더했다. `tsc -b` · `vite build` 통과.
- 변이(스크래치 사본) 백엔드 10/10 — 취소에서 안 비움 · 패널 잡만 비움 · 코드만 비움, 쉼 하나로 되돌림 · 뒤집음 · /me 가 게이트웨이 쉼을
  읽음 · 바람이 웹 쉼을 읽음 · 웹 기록의 머리 뺌 · 일시 웹 실패 무시, 상태 계산을 트랜잭션 밖으로.
- 합친 판 — 스크래치 클론에서 main b71a262 에 이 가지를 합치고 RF-14 의 한 줄로 풀어 관련 시험(사람 조작 감사 · Claude 패널 잡 · 외부 응답자
  잡 · PAT 자동 등록 · 요구 상태 · 패널 러너 · P6 라우트) 270 이 통과했다. checklist.md · context-notes.md 는 두 가지의 끝 덧붙임이 겹친다(종전과 같다).
- 리스크 전체 시험 한 번(공유 잠금) — 3,737 통과 · xfail 4 · 실패 0(rc 0, 963f661 — 종전 3,731 에 새 시험 6).

## 구성원 읽기 · 들여오기 키 선점 10-31(가지 `wt1031/risk-members`, main 3a188f3 위, 2026-10-31)

> 사용자 결정 둘(10-31) — '계획서대로 구성원도 읽는다'(RD-9 남긴 것 1 · 포털 plan §9.2 (14) 두 계정 시나리오) · '들여오기 선점만 막는다'(RD-10 ·
> RD-11 남긴 것의 들여오기 몫). 커밋 — 07ed329(구성원 읽기) · 1a18503(들여오기 키 선점). 같은 때 도는 가지(러너 잡 동시성)와 겹치는 곳은 없다 —
> 이 가지는 routes.py 의 읽기 라우트 · MCP 문지기 · entry.get_sameas 글과 export.import_jsonl 만 고쳤고 runner.py 는 손대지 않았다.

### MB-1. 구성원 읽기 — 문 하나(`_reader`)를 읽기 라우트마다
- 연 것 — 과제에 딸린 것을 읽는 REST 읽기 전부다. 스냅샷(ir · state · nodes · edges · calls · rule_hits)과 규칙 적중, 대응표 · 비교 · 선례,
  대상의 단위 · 진행판 · 완결 · 쟁점 · 종합 보고서 · 셀 · 전문가 · 전문가 보고서 · 등록부 · 좌석 · 패널, 패널 발언 · 패널 동결 브리프, 과제의
  성격 · 유사 · 요구, 참조의 스냅샷 · 비교 스코프와 req · voc · paper(MB-2), 목록 셋(MB-3). 과제 상세 · 목록 · 멤버 · 이력 · 대상 감사 · 키
  대장 · 원장 참조(reg · narr · tool — D50)는 이미 열려 있었다.
- 판정 — 부른 사람의 project_role(과제 상세 RD-1 과 같은 문 — owner 는 과제 행의 주인 열, 구성원은 편집자 · 보기 행)이 있고 그 행이 과제
  주인의 행(행 owner_sub == rr_projects.owner_sub — 하위 표의 owner_sub 는 과제 주인의 복제다)이면 행의 주인을, 아니면 부른 사람을 돌려준다.
  라우트는 그 값을 본체(MCP 와 같은 payload 함수)의 owner_sub 로 넘긴다. 본체는 `_target_row` · `_snapshot_row` · `_project_row` ·
  `_panel_row` · `get_diff` 로 그 주인의 행을 고르므로 구성원은 주인과 같은 답(글 전체)을 받는다. 부른 사람을 받은 본체는 오늘과 같은 404 를
  낸다 — 남과 없는 것이 글자까지 같은 답이고(남 숨김), 행 주인이 부른 사람이면 문을 보지 않으므로 주인의 길은 바뀌지 않는다.
- 고르는 행 — 주인이 다른 행(고침 전의 들여오기가 남의 과제에 매단 것, RD-10)은 구성원 길로 열지 않는다. 그 행을 들여온 사람 자신은 오늘처럼
  제 행을 읽는다(새는 것이 없다).
- 대상은 그 과제(rr_targets.project_id)로 본다 — 비교 대상의 base 과제는 보지 않는다(MCP 문지기 · 반출과 같은 규칙, D50). 비교 자체(GET
  /diffs/{id})는 두 과제를 다 읽어야 한다(MB-2) — 대상 과제만의 구성원은 비교 대상의 진행판 · 등록부는 읽고 비교 화면은 404 다(MCP 와 같다).
- 관리자 우회(risk_admin_roles)는 읽기에 넓히지 않았다 — 과제 상세(RD-1)처럼 구성원 검사만이다. 멤버 · 이력 · 대상 감사만 관리자 우회가 있고,
  plan §0.6 은 관리자를 전 과제 편집자로 적는다(남긴 것 — 넓힐지 결정).
- 쓰기는 그대로다(MB-5).

### MB-2. 두 과제에 걸친 것 — 비교 · 대응표 · 선례 · 유사 · 참조
- 비교 — 두 과제(base · target)를 다 읽고 행 주인이 두 과제 가운데 하나의 주인일 때 연다(`_diff_reader` · 비교 목록 · MCP 문지기가 같은 규칙).
  처음에는 '대상 과제의 주인' 하나로 짰다가 바꿨다 — 비교는 이양이 옮기지 않아(TRANSFER_PROJECT_TABLES 밖) 뒤 과제만 넘기면 행 주인이 대상
  과제의 주인이 아니게 되는데 그 비교는 만든 사람(앞 과제의 주인)의 정상 행이다. 두 과제를 다 넘기면 행 주인이 어느 쪽의 주인도 아니라
  들여온 남의 행과 가를 길이 없어 만든 사람의 제 행으로만 열린다(새 주인 · 구성원은 404 — 새 주인은 오늘도 못 열었다). 이양이 비교를 옮기지
  않는 것은 그대로 두었다(범위 밖).
- 대응표(GET /sameas) — 두 스냅샷을 다 읽는 사람이 연다. 쌍 원장(rr_sameas)은 대상 스냅샷 주인의 것으로 읽는다 — 주인이 정한 대응이 구성원의
  표에도 선다(주인의 길은 두 스냅샷 다 자기 것이라 같다). MCP risk_get_sameas 는 이 라우트를 그대로 부르는 입구라 같이 열렸다.
- 유사 · 선례 — 구성원이 부르면 다른 과제는 주인과 그 사람 둘 다 읽는 과제만 싣는다(caller_projects = 그 사람의 소유 ∪ 구성원 과제 — MCP 의
  D46 과 같다. MCP 는 조직 공개 과제까지 든다). 주인의 답은 그대로다.
- 참조 — 스냅샷 · 비교 스코프는 스냅샷 · 비교 조회와 같은 문이다. req · voc · paper 는 참조 글에 과제가 없어 부른 사람의 것을 먼저 보고(오늘
  그대로) 없으면 구성원인 과제(그 과제 주인의 행)의 요구 · 대상별 브리프 호출 원장에서 찾는다 — D50 '그대로 둔 것' 의 둘을 닫았다. voc ·
  paper 는 대상마다 찾는다(새 대상부터). 주인의 길은 그 사람의 브리프 호출 전부를 fetched_at 차례로 찾으므로 두 사람이 같은 키의 다른 판
  항목을 받을 수 있다(키가 같으면 같은 이슈 · 논문이다).

### MB-3. 목록 셋(대상 · 비교 · 보고서) — 제 행 ∪ 구성원 과제
- 과제 목록(RD-2)처럼 소유 ∪ 구성원 과제다. 대상 · 보고서는 `owner_sub = 부른 사람` 에 구성원 과제의 과제 주인 행을 더하고
  (`_member_row_sql`), 비교는 두 과제를 다 읽고 행 주인이 두 과제 가운데 하나의 주인인 행을 더한다. 주인의 줄은 그대로다(제 행은 오늘과 같은
  조건). 홈 탭 셋과 명령 팔레트(대상 목록)가 구성원 과제의 줄을 함께 보인다.
- 과제로 거르는 목록에 남의 과제를 주면 종전처럼 빈 목록이다(남 시험 표 GET_EXPECT).

### MB-4. MCP — 같은 판정
- 볼 수 있는 과제(visible_projects)의 멤버는 편집자 · 보기 행만 센다 — 주인 아닌 사람의 owner 멤버 행(RD-10 남긴 것)은 MCP 에서도 역할이
  아니다. 종전에는 그 행 하나로 MCP 목록과 읽기가 열렸다(시험이 재현한다).
- 문지기(mcp_scope_owner)는 과제 범위를 본 뒤 행 주인이 그 행 과제의(비교는 두 과제 가운데 하나의) 주인이거나 부른 사람 자신일 때만 연다.
  종전에는 과제만 보고 행의 주인으로 읽어, 남이 주인의 과제에 매단 스냅샷 · 대상을 주인 · 구성원 · 조직 공개 호출자에게 내주었다(시험이
  주인에게서 재현했다). '부른 사람 자신' 은 두 과제를 다 넘긴 뒤 만든 사람이 제 비교를 읽는 길이다(MB-2).
- 그대로 둔 것 — risk_get_brief(토큰의 패널 주인만 — 결과를 낼 수 있는 사람, RV-1) · risk_next_step(주인의 진행 길잡이 — 다음 걸음이 소스 ·
  캡처 · 대상 · 잡 같은 주인의 쓰기라 구성원에게 무엇을 보일지 정하지 않았다, 남긴 것). 시험 표가 MCP 도구를 읽기 · 주인만 · 쓰기로 나눠 새
  도구가 셋 가운데 하나로 들어오게 한다.

### MB-5. 쓰기는 그대로다 — 쓰기인 읽기 둘
- 쓰기 라우트는 한 줄도 바꾸지 않았다. 보기가 쓰기 경로 45 를 걸어 보는 가드를 더했다 — 제 과제 만들기와 대응 결정(그 표의 줄은 새 행이라
  부른 사람의 행이 선다) 둘만 지나고 나머지는 오늘 그대로 403 · 404 로 막힌다(옛 코드에서도 통과하는 지킴 시험). 대응 결정은 이미 있는
  남의 행을 뒤집을 수 있다 — MB-11(높음 · 결정 필요).
- GET /targets/{key}/brief 는 읽기가 아니다 — 패널을 편성하고 패널마다 brief_token 을 새로 낸다(앞서 복사한 토큰이 무효가 된다 — 화면
  RecallPreview 주석). 토큰은 결과를 낼 패널 주인의 열쇠라(risk_get_brief · complete_panel 이 패널 주인만 받는다) 주인만 그대로 둔다. 구성원은
  없는 대상과 같은 404 를 받고 패널 · 토큰이 서지 않는다(시험). 패널의 동결 브리프(GET /panels/{id}/brief)는 읽기라 열었다.
- GET /targets/{key}/closure?fresh=1 은 완결 캐시(rr_targets.closure_json)를 다시 쓴다 — 사람 결정이 아니라 파생 캐시이고 캐시가 없을 때의
  첫 읽기도 같은 캐시를 쓰므로 구성원의 읽기에도 열었다(감사 행 없음).
- 계획과 코드의 어긋남(넓히지 않았다 — 사용자 지시) — plan §0.6 은 편집자에게 '스냅샷 · 타깃 · 잡 · status · 사람 finding' 을, §8.2.3 은 요구
  (올리기 · 결정 · 승계) · 게이트 ack 를 편집자 쓰기로 적는다. 코드는 잡 · 좌석 · 사람 finding · 방식 · 단위 · 쟁점 · 보고서 · 셀 처분 · 과제
  메타가 편집자 이상이고, 스냅샷 동결 · 소스 · ECAD 보드 · 치수 · 계면 원장 · 요구 · 게이트 ack · 등록부 status · verdict 확정 · 재동기 · 명단
  갱신은 주인만이다. 구성원이 과제 · 대상 화면의 그 단추를 누르면 404 · 403 배너다(남긴 것 — 넓힐지 결정).

### MB-6. 들여오기는 정규 키를 선점하지 못한다(1a18503)
- 무엇이 샜나 — rr_part_keys 는 열쇠가 ckey 하나인 과제 공용 표라 처음 적립한 사람이 행의 주인이다(ir_builder._upsert_part_keys — 뒤에 같은
  키를 적립하는 사람은 IntegrityError 를 삼키고 지나간다). 들여오기는 아무 ckey 의 새 행이나 받아(부모 열이 없거나 이 박스에 없으면 받았다 —
  RD-10 의 부모 검사는 first_project_id 를 범위 부모로 보지 않는다), 남이 주인의 키(이름 · 크기 · 재질의 해시라 짐작할 수 있다)를 주인이
  적립하기 전에 쥐면 주인의 동결은 행을 얻지 못하고 그 키의 결정이 다 404 였다(RD-11 의 mine false).
- 고침 — 새 행은 그 ckey 가 부른 사람의 과제에 실려 있을 때만 받는다 — 부른 사람 소유의 노드(rr_ir_nodes.ckey)가 부른 사람 소유의 스냅샷 ·
  과제에 있어야 한다(노드 · 스냅샷 · 과제 주인 셋을 다 본다 — 남이 주인의 스냅샷에 매단 노드로 걸치지 못한다). 이 박스에 이미 있는 노드도,
  같은 들여오기에서 앞서 들어간 노드도 된다 — 줄은 TABLE_ORDER 로 쓰고 rr_ir_nodes 가 rr_part_keys 앞이다(본문에서 키 줄이 앞에 와도 된다).
  아니면 그 줄만 `ckey_not_referenced` 로 눕힌다(parent_not_owned 와 같은 꼴 — {table, key, reason}, 남의 값은 싣지 않는다). 그 판정은
  부른 사람의 과제만 보므로 남의 키가 있는지를 흘리지 않는다(이미 남의 행이 있으면 종전대로 owner_conflict 다).
- 왜 노드인가 — 운영에서 키 원장 행을 만드는 길은 동결의 적립(_upsert_part_keys — 노드가 단 유효 ckey)과 그 행의 사람 결정뿐이다
  (sameas.assign_ckeys · inherit_ckeys 는 앱 안에 부르는 곳이 없다 — 시험만 부른다). 그래서 정상 행의 ckey 는 늘 그 사람 스냅샷의 노드에
  실려 있고, 들여오기가 적립보다 더 쥐지 못한다. dev 원장의 키 97 행은 모두 제 노드가 쓴다(MB-9 쿼리 — 다시 들여와도 눕는 행이 없다).
- 기존 행의 병합은 그대로다 — 부른 사람이 이미 쥔 행(found 갈래)은 이 검사를 보지 않는다(새 행에만 건다). 시험이 '제 과제가 이제 쓰지 않는
  키의 제 행' 에 사람 확정을 병합해 그대로 받는 것을 지킨다.
- 남는 것 — 같은 이름 · 크기 · 재질의 부품을 먼저 동결한 사람이 행의 주인이 되는 것은 설계 그대로다(적립 규칙). 들여오기로 제 스냅샷 · 노드를
  만들어 그 키를 실은 뒤 키 행을 들여오는 것도 '제 과제가 쓰는 키' 라 받는다 — 동결로 같은 부품을 올리는 것과 같은 힘이다. 열쇠를 (ckey,
  owner_sub) 로 넓히는 것은 하지 않았다(스키마 · 사용자 결정 10-31 — 선점만 막는다).

### MB-7. 이양과 키 원장 — 설계 그대로(사용자 결정 10-31)
- 이양은 rr_part_keys 를 옮기지 않는다(TRANSFER_PROJECT_TABLES 밖) — 행은 그 키를 처음 적립한 사람의 것이다. 그래서 새 주인은 그 과제의 키를
  결정하지 못하고(RD-11 — 화면은 mine false 로 결정을 잠근다), 새 주인의 다음 동결도 그 키의 행을 얻지 못한다(열쇠가 ckey 하나).
- 옛 주인이 그 행을 다시 들여오면 — 같은 박스에서는 first_project_id 가 이제 남의 과제라 RD-10 의 parent_not_owned 이고(병합 줄도 같다 — 판정만
  실으면 받는다), 새 박스에서는 그 키를 쓰는 제 과제가 없어 MB-6 의 ckey_not_referenced 다(제 다른 과제가 그 키를 쓰면 받는다). 둘 다 '이양은
  키를 옮기지 않는다' 와 같은 뜻이라 따로 풀지 않았다. 시험 — 이양 뒤에도 행이 옛 주인의 것이고 새 주인의 새 행은 owner_conflict 다.

### MB-8. 화면 — 고치지 않았다
- 주인만 읽기에 기대 탭 · 칸을 숨긴 화면은 없었다(ProjectPage 의 isOwner · role 은 ECAD 보드 · 멤버 · 메타 쓰기 잠금에만 쓴다 — 읽기 탭은
  역할로 가르지 않는다). 구성원이 열던 404 가 이제 서버에서 200 이라 과제 화면의 요구 · 성격 · 유사 탭과 스냅샷 · 대상 · 비교 화면이 고치지
  않고 선다. 응답 꼴은 바뀌지 않았다(목록 셋은 줄이 늘 뿐이다).
- 구성원에게 남는 화면 거슬림(화면 세션 몫) — 대상 화면의 '브리프' 탭은 공용 404 배너('찾을 수 없습니다 — 삭제됐거나 내 소유가 아닌 항목')를
  보인다(브리프는 주인만 — 글은 맞다). 과제 · 대상 화면의 주인 쓰기 단추(동결 · 소스 · 요구 · 재동기 · 명단 갱신 · verdict …)는 구성원에게도
  보이고 누르면 404 · 403 배너다 — 과제 화면은 RD-1 부터 그랬고 이번에 여러 탭이 열려 더 보인다. 대상 화면은 부른 사람의 역할을 모른다(응답에
  역할 칸이 없다).
- 화면을 고치지 않아 화면 시험 · tsc · 빌드는 돌리지 않았다.

### MB-9. 남긴 것을 세는 쿼리(cae00 — 읽기만, dev 는 둘 다 0)
- 고침 전(RD-10 앞)의 들여오기가 남긴 남의 편집자 · 보기 멤버 행 — 과제 주인이 들인 적 없는 행이다. 구성원 읽기가 열려 그런 행이 읽을 수 있는
  것이 넓어졌다(스냅샷 · 등록부 · 보고서 …) — cae00 에서 반영 전에 센다. 열을 고를 때 둘을 조심했다 — rr_project_members.owner_sub 는 이양이
  그 과제의 모든 멤버 행을 새 주인으로 다시 찍어 이양 뒤의 남의 행을 숨기고, added_by 는 들여오는 사람이 적은 값이라 증거가 아니다. 그래서
  둘을 센다. ① RD-10 의 쿼리(이양으로 다시 찍히지 않은 남의 행)
  `SELECT m.project_id, m.email, m.role, m.owner_sub, m.added_by FROM rr_project_members m JOIN rr_projects p ON p.id = m.project_id
  WHERE m.role IN ('editor', 'viewer') AND m.owner_sub <> p.owner_sub;`
  ② 생산자의 흔적이 없는 행(이양으로 다시 찍힌 것까지) — 편집자 · 보기 행을 만드는 길은 put_members(rr_audit member.put — after.members 에 그
  이메일)와 이양(옛 주인 — rr_audit project.transfer 의 before.owner_sub)뿐이고 제 박스 옮기기는 그 감사 행을 함께 옮긴다.
  `SELECT m.project_id, m.email, m.role, m.added_by FROM rr_project_members m WHERE m.role IN ('editor', 'viewer')
  AND NOT EXISTS (SELECT 1 FROM rr_audit a, json_each(a.after_json, '$.members') j WHERE a.project_id = m.project_id
  AND a.action = 'member.put' AND json_extract(j.value, '$.email') = m.email)
  AND NOT EXISTS (SELECT 1 FROM rr_audit a WHERE a.project_id = m.project_id AND a.action = 'project.transfer'
  AND json_extract(a.before_json, '$.owner_sub') = m.email);`
  ②는 rr_audit 이 빠진 옛 이관 원장에서 정상 행도 셀 수 있다 — 나온 행은 사람이 본다. 지울지는 사람이 정한다(RD-10 남긴 것과 같다).
  ③ 주인 아닌 사람의 owner 멤버 행 — 읽기 문(project_role · visible_projects)은 이제 역할로 읽지 않지만 MB-11 의 둘은 아직 센다.
  `SELECT m.project_id, m.email FROM rr_project_members m JOIN rr_projects p ON p.id = m.project_id WHERE m.role = 'owner'
  AND m.email <> p.owner_sub;`
- 옛 confirm_key 가 남긴 키 행(RD-6 — status 가 merged 가 아닌데 merged_into 가 남은 행)
  `SELECT COUNT(*) FROM rr_part_keys WHERE status <> 'merged' AND merged_into IS NOT NULL;`(행을 보려면 `SELECT ckey, owner_sub, status,
  merged_into, decided_by, decided_at FROM …`). 고치는 길은 넣지 않았다(RD-6 그대로).
- 함께 — 들여오기를 다시 하면 MB-6 으로 눕을 키 행(제 노드가 쓰지 않는 제 행)
  `SELECT COUNT(*) FROM rr_part_keys k WHERE NOT EXISTS (SELECT 1 FROM rr_ir_nodes n JOIN rr_snapshots s ON s.id = n.snapshot_id
  JOIN rr_projects p ON p.id = s.project_id WHERE n.ckey = k.ckey AND n.owner_sub = k.owner_sub AND s.owner_sub = k.owner_sub
  AND p.owner_sub = k.owner_sub);`
- dev(`/data/appdata/hwax_risk/risk_review.db`, 읽기 전용 연결 — 10-31 13시 UTC) — ① 0 · ② 0(편집자 · 보기 행이 아직 없다) · ③ 0 · 과제 없는 멤버 행 0 · RD-6 0 · 키 행 97 가운데 제 노드가 쓰지 않는 것 0.

### MB-10. 시험 · 변이 · 전체 시험
- 구성원 읽기(07ed329) — 새 tests/rr/test_member_reads.py 103(라우트 표 32 — 남 시험 표의 읽기 경로에서 브리프를 뺀 전부, 주인 · 편집자 · 보기는
  같은 답 · 남은 없는 것과 같은 답 · MCP 읽기 도구 15 · 보기의 쓰기 가드 45 · 낱 시험 11 — 표 덮음 · 브리프 · 목록 셋 · 참조 스코프 · MCP
  분류 · MCP 목록 · 남이 매단 행 · 주인 아닌 owner 행 · 대응표 원장 · 두 과제 비교와 이양 · req · voc · paper)와 test_review1_stranger_recall 의
  REST D46 쌍둥이 하나. 옛 코드(3a188f3 의 app/ — 스크래치 사본)에 얹으면 35 가 진다(라우트 표 26 · 목록 · 참조 스코프 · MCP 대응표 · 남이 매단
  행 · owner 행 · 대응표 원장 · 비교 · 참조 셋 · REST D46). 나머지는 지킴 시험이다(이미 열린 읽기 6 · MCP 읽기 14 · 보기의 쓰기 45 · 브리프 · 표 분류 둘 · MCP 목록).
- 들여오기 키 선점(1a18503) — test_project_reads 새 넷. 옛 코드(07ed329)에서 선점 시험이 진다(남의 두 행이 들어간다). 제 노드가 쓰는 키(이미 있는
  노드 · 같은 본문의 노드)와 이양 뒤 제 행 병합 셋은 지킴 시험이다 — 규칙이 너무 좁으면 진다. 반출입 시험 씨앗은 노드 n1 이 그 키를 단다(키는
  노드에서 적립된다 — 씨앗이 노드 없는 키 행을 심고 있었다).
- 변이(스크래치 사본, 바이트코드 끔, 변이마다 되돌리고 __pycache__ 를 지운다 — 변이 없는 대조 실행이 먼저 통과) — 구성원 읽기 28/28(구성원
  검사 · 과제 주인 대조 · 구성원 길 끔 · 구성원 SQL 역할 거름 · 행 SQL 주인 대조 · 대상 · 보고서 목록 · 비교 목록 base · 행 주인 · 비교 문 base ·
  행 주인 · 스냅샷 · 대상 · 패널 · 과제 문 · 유사 · 선례 D46 · 대응표 원장 · 참조 스냅샷 · 비교 스코프 · req · voc/paper · MCP 역할 거름 · MCP 행
  주인 · MCP 제 행 예외 · 읽는 과제 전부 · 라우트 둘), 들여오기 6/6(검사 끔 · 늘 쓴다 · 주인 조건 다 뺌 · 스냅샷 · 과제 주인 뺌 · 병합에도 ·
  모든 표에). 처음 판의 변이 하나(선례 D46)는 무늬가 유사 과제 줄에도 걸려 걸리지 않았고 앞 줄을 붙여 다시 걸어 잡혔다.
- 대상 시험(커밋 전) — 구성원 읽기에 닿는 파일 42 개 928 통과 · xfail 1, 들여오기에 닿는 파일 14 개 442 통과 · xfail 1.
- 리스크 전체 시험 한 번(공유 잠금, 코드 1a18503 — 문서만 고치던 작업 트리) — 3,897 통과 · xfail 4 · 실패 0(rc 0, 13분 26초). 그 뒤 시험 파일의
  글 한 줄(VIEWER_WRITES_OWN 의 대응 결정 까닭 — MB-11 을 가리킨다)만 고쳤고 그 파일을 다시 돌렸다.
- 하지 않은 것 — 서비스 · 인스턴스 기동 · 정지, push · 병합, 실 브라우저 확인.

### MB-11. 본 것(이번 범위 밖)
- (높음 — 결정 필요) 대응 결정(POST /sameas/decide 의 confirm · reject)은 누구의 결정이든 남의 rr_sameas 행을 뒤집는다. 그 표의 유일 열쇠가
  (scope, pair_key, a_stable, b_stable) 이고 `record_decision` 의 `ON CONFLICT … DO UPDATE` 에 주인 거름이 없어, 주인이 확정한 행에 다른 사람이
  같은 네 값으로 reject 를 보내면 행의 owner_sub 는 주인 그대로 status 가 rejected · decided_by 가 그 사람으로 바뀐다 — 주인의 원장(load_ledger)이
  그 행을 읽으므로 주인의 대응 · 다음 비교가 바뀌고, 확정 → reject 의 키 전파(rekey)는 부른 사람의 행으로 돌아 주인 쪽은 돌지 않는다. 원장
  사본 탐침으로 확인했다(보기 구성원이 주인의 확정을 rejected 로 뒤집음 — 커밋하지 않았다). 종전부터 있던 구멍이지만(그 경로는 남 시험 표에서
  '제 행만 쓴다' 로 면제돼 있었다) 구성원 읽기가 그 네 값(대응표의 pair_key · stable 키, 스냅샷 노드)을 보기 구성원에게 연다 — 보기가 쓰는
  길이 된다. 쓰기를 바꾸는 일이라 고치지 않았다. 고치는 길은 둘 — 열쇠를 주인별로(스키마) 하거나, confirm · reject 를 pair_key 의 과제(들)에
  주인(또는 편집자)인 사람만 받고 upsert 에 주인 거름을 둔다(남의 행은 없는 것과 같은 404).
- 합성기(devseed)가 생산자 경로로 언 IR 의 엣지 attrs.note 가 null 이라 rr_ir.v1 스키마를 지나지 못한다(seed_raw 의 검증이 잡았다 — 시험은
  그 행만 검증을 껐다). RD-15 에 적은 손 픽스처의 results oneOf 와 같은 결이다 — 생산자와 공개 스키마가 어긋난다.
- brief._MEMBER_OF · _member(유사 · 선례 · 좌석 기억 · 코퍼스가 쓰는 '주인의 다른 과제')와 러너의 자격 후보(runner — 멤버 행 존재만 본다)는 아직
  어느 역할의 멤버 행이든 센다 — 주인 아닌 사람의 owner 행(RD-10 남긴 것)이 그 사람의 시야를 넓힌다. 읽기 문(project_role · visible_projects)은
  이번에 맞췄고 이 둘은 손대지 않았다.
- GET /export 는 제 행만이다 — 구성원은 남의 과제를 반출하지 못한다(반출 경계는 주인의 일 — 그대로).

### MB-12. 작업 대장 정리(조정자 요청 10-31 — 읽고 확인한 뒤 체크)
- '포털 정본 문면' 두 줄 — 잡 제어 본문 · 사람 개입 요약 이름 · 등록부 status 감사 자리와 칸 · A24 job.pause(AU-7 · AU-11)는 포털 `90c121ca`
  (plan §8.2.3 의 잡 제어 · verdict · 등록부 status 줄과 회의록 '사람 개입 요약' 정의를 구현에 맞춤 — 그 diff 를 읽었다), duplicate_of 범위 ·
  'E키 또는 ref' 와 §5.7 의 어긋남 · 대상 감사의 남 답 404 와 칸은 포털 `ccbc1b9f`(design-risk-review context-notes 새 절 — 계획서 줄은 두고
  어긋남 넷을 적었다)가 답했다.
- '등록부 병합이 접힌 옛 행을 닫지 않는다(결정 필요)' — 9b41001(BE-8, main)의 `registry._close_vacated_rows` 가 쓰는 registry.merge 마다 옮겨 간
  행을 superseded · superseded_by='<대상>#<간 곳>' 으로 닫는다. 재열쇠 길은 test_rekey 의 4걸음 시험이 지키고, 사람의 클러스터 병합(PUT
  /registry/{k}/merge)도 같은 함수라 원장 사본에서 접힌 행이 superseded 로 닫히는 것을 확인했다(탐침 — 커밋하지 않았다). 원자가 지워져 빈 행은
  다른 줄(BE-10)이다.

## 대응 결정 · 편집자 쓰기 · 이양 10-31(같은 가지 `wt1031/risk-members`, 사용자 결정 셋)

> 사용자 결정 셋(10-31) — 대응 결정 '주인 · 편집자만, 주인으로 지킨다'(MB-11 높음) · '계획서대로 편집자도 쓴다'(MB-5 남긴 것) · 비교는 '둘 다
> 받은 사람에게 옮긴다'(MB-2 남긴 것). 같은 갈래로 함께 — brief · 러너의 구성원 판정, IR 계약(MB-11 범위 밖 둘). 커밋 — a6daeb8(대응 결정) ·
> 58f5c07(편집자 쓰기) · 3618953(이양) · c99634f(구성원 판정) · a49e85f(IR 계약) · b9798ec(finding 쓰기 문의 카드 대조 거름 — 전체 시험의
> 가드 둘이 잡았다). 러너는 diff_ref_withheld 의 멤버 SQL 한 줄만 고쳤다(잡 집기 ·
> 동시성 길은 손대지 않았다 — 다른 가지 wt1031/risk-concurrency 와 겹치는 곳은 그 한 줄뿐이다).

### MB-13. 대응 결정 — 주인 · 편집자만, 주인의 원장으로(a6daeb8)
- 문 — confirm · reject 는 pair_key 의 과제의 주인 · 편집자(관리자 포함)만 한다. pair 는 두 과제 둘 다다 — plan §2.6.1 · §2.6.2 의 pair 결정은
  두 과제의 노드를 잇고(pair_key 는 정렬한 두 과제 id) 두 과제 사이 비교의 대응이 된다(create_diff 가 그 원장을 읽는다). 한쪽 과제만의
  편집자는 다른 과제의 구성원이 아니라 그 과제가 없는 것과 같은 404 다. intra 는 그 과제 하나다. 보기는 403 role_insufficient, 남 · 없는 과제는
  404, 열쇠 꼴이 scope 와 안 맞으면 400 이다(pair 인데 과제 하나 · intra 인데 둘). global(ckey 쌍)은 과제에 묶이지 않아 종전처럼 부른 사람의 행이다.
- 행 — 그 과제 주인의 원장 행이다(owner_sub 주인 · decided_by 부른 사람). 두 과제의 주인이 다르면(두 사람의 과제를 다 편집한다) 적을 원장이
  하나가 아니라 422 pair_owners_differ 다. 확정 → reject 의 키 전파(rekey)는 행의 주인으로 돌고 감사 행의 행위자는 부른 사람이다.
- 지킴 — 같은 자리(scope · 열쇠 · 두 stable 키 — 유일 열쇠에 주인이 없다)에 다른 사람의 행이 있으면 덮지 않고 409 sameas_row_foreign 이다(남의
  이메일은 싣지 않는다 — 조용히 넘기지 않는다). upsert 의 `ON CONFLICT … DO UPDATE` 에도 `WHERE rr_sameas.owner_sub = excluded.owner_sub` 를
  둔다(같은 트랜잭션의 앞 검사와 겹 — 변이 D9 가 살아남는 까닭이다, 앞 검사를 빼는 변이 D8 은 잡힌다).
- MCP risk_decide_sameas 는 웹 라우트를 그대로 부른다 — 두 스냅샷을 읽는 사람이면 열쇠를 짓고, 받을지는 라우트의 문이 정한다.

### MB-14. 편집자 쓰기 — 계획서대로(58f5c07)
- 쓰기 문 하나(`routes._writer`) — 행 주인이 부른 사람이면 문을 보지 않는다(주인의 길 그대로). 아니면 그 행이 과제 주인의 행이고(행 owner_sub ==
  rr_projects.owner_sub — 남이 매단 행은 열지 않는다, RD-10) 부른 사람이 그 과제의 편집자 이상(관리자 — plan §0.6, 기존 편집자 길과 같은 우회)일
  때 행의 주인을 돌려준다. 구성원이 아닌 남은 부른 사람으로 내려가 본체가 오늘과 같은 404 를 내고(남과 없는 것이 같은 답), 보기는 403
  role_insufficient 다(plan §5.2.1 — 구성원의 등급 미달). 읽기 문(`_reader`, MB-1)과 같은 꼴이다.
- 편집자에게 연 것(plan §8.2.3 '쓰기는 require_role(editor)' · 행마다의 '(editor)' · §0.6 의 스냅샷 · 타깃 · 잡 · status · 사람 finding) — 소스 ·
  동결 · 치수 · 요구 셋 · 계면 원장 · 게이트 ack · 취소 · 대응 결정(MB-13) · 비교 · 대상 · 명단 갱신 · 잡 조작 · 판정 확정 · 등록부 status ·
  병합 · 철회 · 패널 결과(REST · MCP) · 브리프(편성 · 토큰 — 결과를 낼 사람의 열쇠라 쓰기 문이다, MCP 토큰 열람도) · 라벨. 이미 편집자였던
  잡 만들기 · 좌석 · 셀 처분 · 쟁점 · 보고서 · 단위 · 방식 · 사람 finding 만들기 · 다시 저장 · 과제 메타는 그대로다.
- 주인(· 관리자)만 남긴 것 — 멤버 · 이양 · 폐기(§8.2.3), mcp_visibility · confidential → internal(§8.2.3 PATCH), 재동기(소유자 전용), 큐레이션
  (과제 owner · 관리자), 완결 확인(M3 — 편집자 403), ECAD 보드(포털 ecad-1031 — 그 사람 토큰), 등록부 공개 토글(P6-8). 사람 finding 고치기 ·
  지우기는 작성자 본인 또는 과제 주인이다(§8.2.3 — 작성자도 지금 편집자 이상이어야 한다, 보기로 내려가면 제 finding 도 못 고친다). 이 길들의
  편집자 · 보기 답은 종전 그대로다(404 는 부른 사람의 행만 고르는 길 — 화면은 404 를 '소유자 불일치' 로 보인다).
- 행과 사람 — 쓴 행은 과제 주인의 원장이다(하위 표의 owner_sub 는 과제 주인의 복제). 사람 칸(decided_by · ack_by · verdict_by · state_by ·
  labeled_by · built_by · created_by · revoked_by · 감사 actor)은 부른 사람이다. 감사 행의 owner_sub 는 라우트의 `_audit` 꼴 그대로 행위자다(기존
  편집자 길인 잡 · 사람 finding · 쟁점과 같다). 별칭 철회만 원장 주인으로 적고 행위자를 따로 둔다(`_audit` 의 actor 인자) — 자리가 맨 클러스터
  열쇠라 대상 감사가 '그 대상 소유자의 행위' 로 고른다(BL-8, 행위자 이름으로 적으면 어느 대상 감사에도 실리지 않았다).
- 자격 — 동결(캡처)은 시작한 사람의 등록 PAT 로 읽는다(위임 다리 · ECAD 도 그 사람) — 주인의 PAT 를 빌리지 않는다. 명단 조회(대상 열기 · 명단
  갱신)는 종전 설계대로 대상 주인의 PAT → 서비스 PAT 다(roster.credential — 사람의 비공개 자료를 열지 않는 짧은 호출). 잡은 요청자 → 주인
  순(plan §0.1.6, 종전 그대로).
- 대상 없이 부르는 등록부 status · 병합 · 철회는 부른 사람 자신의 행이다(주인의 다른 과제까지 걸쳐 고를 주인이 없다) — 화면은 늘 대상을 싣는다.
  비교는 두 스냅샷 과제의 편집자 이상이고 두 스냅샷의 주인이 다르면 422 pair_owners_differ 다. 대상(diff)은 그 비교를 읽고 대상 과제의 편집자
  이상이며 비교 행이 대상 과제 주인의 것이어야 연다.
- finding 쓰기 문(`_finding_writer` — 사람 finding 고치기 · 지우기 · 라벨)은 카드 대조 finding 을 거른다(b9798ec — rr_findings 를 읽는 SELECT 는
  card_review 를 거르거나 까닭과 함께 목록에 있다, M2 5절 #20 · 그 거름 자리는 래칫 표 S3-4 ⑥ 에 까닭과 함께). 라벨은 그 원자를 없는 것과 같이
  보고(metrics._finding_row) 사람 finding 은 카드 finding 이 아니라 답이 같다.
- 시험 가짜 신원(test_p6_routes)에 role 칸을 더했고(진짜 Identity 에 늘 있다 — 쓰기 문이 관리자 우회를 읽는다), MCP 쟁점 패널 시험은 문의
  결과를 갈아 끼우는 대신 위임 단언을 실은 요청으로 신원을 세운다(도구가 그 신원으로 쓰기 문을 본다 — 진짜 꼴).
- 화면은 고치지 않았다(화면 세션 몫) — 과제 · 대상 화면의 쓰기 단추는 역할로 가르지 않아(ECAD 보드 · 멤버 · 공개 토글만 isOwner) 편집자의
  쓰기가 이제 그대로 선다. 보기에게는 단추가 보이고 누르면 403 배너다. 대상 화면 브리프 탭은 편집자에게 서고 보기에게 403 이다.

### MB-15. 이양 — 비교 · 대응 원장이 둘 다 받은 사람에게(3618953)
- 규칙 — 이양 트랜잭션이 이양 감사 행을 쓴 뒤 `_follow_full_transfer` 를 부른다. 이 과제를 한쪽으로 하는 비교(변경 항목 rr_diff_events 와
  함께)와 대응 원장 행(intra · pair) 가운데, 모든 쪽 과제의 지금 주인이 받는 사람이고 행 주인이 그 과제들을 다 넘겨 준 사람(이양 감사
  project.transfer 의 앞 주인 — 이번 이양의 앞 주인도 든다)인 것을 받는 사람의 행으로 옮긴다. 응답 rows_updated 에 rr_diffs ·
  rr_diff_events · rr_sameas 수를 싣는다.
- 그래서 — 두 과제가 다른 길로 한 사람에게 모여도(앞 과제는 C 에게, 뒤 과제는 B 를 거쳐 C 에게) 마지막 이양에서 옮긴다(앞 주인 기록 —
  '이번 이양의 앞 주인' 하나로만 보면 이 경우를 놓친다). 과제 안 리비전 비교 · intra 행은 그 과제 하나를 넘기면 옮긴다 — 종전에는 새 주인의
  diff 대상(rr_targets 는 옮긴다)이 옛 주인의 비교를 가리켰다. 한쪽만 넘어간 것은 만든 사람의 행 그대로다(두 과제를 다 읽는 사람이 연다 —
  사용자 결정). 넘겨 준 적이 없는 사람의 행(남이 적어 넣은 것 — RD-10)은 따라가지 않는다.
- 함께 닫은 결함 둘 — ① 두 과제를 다 넘긴 뒤 새 주인이 같은 쌍을 다시 만들면 옛 주인의 행이 유일 열쇠(base, target)를 쥐어 IntegrityError(500)
  였다(탐침으로 재현 — 이제 그 비교를 돌려준다). ② 대응 원장이 따라가지 않아 새 주인에게 결정이 사라지고(load_ledger 는 주인으로 읽는다) 다시
  정하면 남의 행이라 409 sameas_row_foreign 이었다(MB-13 의 덮지 않기가 새로 만든 막힘).
- 그대로 둔 것 — ckey 원장(rr_part_keys) · global 대응은 과제에 묶이지 않아 옮기지 않는다(MB-7). rr_id_map(RA 엔티티 사상)은 스냅샷 · 과제의
  사상도 옮기지 않으므로 비교도 그대로다.

### MB-16. 구성원 판정 — 브리프 · 러너도 같은 규칙(c99634f)
- brief._member · _MEMBER_OF(E6 유사 · E7 좌석 기억 · E8 선례 코퍼스 수 · 계보 · learning 의 공통 구성원 과제)와 runner.diff_ref_withheld(좌석에
  diff_id 를 실을지 — 그 자격 이메일이 두 과제의 구성원인가)의 멤버 행은 편집자 · 보기만 센다 — owner 는 과제 행의 주인 열만 정한다(project_role
  과 같은 규칙, RD-10). 종전에는 역할을 보지 않아 주인 아닌 사람의 owner 멤버 행(고침 전의 들여오기)이 그 사람의 대상 브리프에 남의 과제의
  의견 · 성격 · 선례를 실었고, 그 사람 자격의 좌석에 남의 diff 를 열 수 있다고 보았다. 러너는 그 멤버 SQL 한 줄만 고쳤다(MB-13 머리말).

### MB-17. IR 계약 — note null · 합성기 해석 조건 해시(a49e85f)
- 계면 attrs.note 는 null 도 받는다 — StepForge 계면 행이 note 를 비우면 mcad 어댑터가 `row.get("note")` 그대로 null 을 싣는다(이웃 칸
  tol_config_hash 처럼). 스키마만 넓혔다 — 실제 캡처의 IR 바이트(ir_hash)는 그대로다. 생산자를 고쳐 칸을 빼거나 빈 글로 바꾸면 같은 내용의
  다음 캡처가 다른 ir_hash 가 되어 재사용(reused)이 깨진다.
- 합성기(devseed)의 해석 조건 해시는 'simp-syn' 이 아니라 실제 어댑터 함수(dyna._sim_params_hash — 64자 sha256)다. 합성 IR 이 rr_ir.v1 안이
  되어 구성원 시험의 '남이 매단 스냅샷' 사본이 검증을 끄지 않는다. 앞 · 뒤가 같은 해시라 비교 가능성은 그대로다. dev 에 이 판 전에 주입한 합성
  스냅샷은 옛 글자라 새 합성 스냅샷과 비교하면 해석 조건이 다르다고 나온다(dev 합성 자료만).
- 계약 시험 둘 — note 없는 계면 행(어댑터 함수의 실제 산출) · 합성기의 앞 · 뒤 IR.
- 남긴 것 — 생산자 diff_json 도 rr_diff.v1 밖이다. 합성 비교 하나에서 15건 — 최상위 pair_kind 가 계약에 없고 조립품 주체(asm:…)가 주체 무늬
  (^p:…)에 맞지 않는다. 계약을 넓힐지 생산자를 맞출지 정하지 않았다 — 구성원 시험의 남이 적어 넣은 비교 행 사본은 검증을 끈 채로 두었다(까닭을
  시험 글에 적었다). 손 픽스처의 results oneOf(RD-15)도 그대로다.

### MB-18. 시험 · 변이 · 전체 시험
- 대응 결정(a6daeb8) — tests/rr/test_editor_writes.py 의 앞 9(보기 · 남의 뒤집기 · pair 는 두 과제 · 두 주인 · 편집자는 주인의 원장 · 남의 행
  409 · MCP · 없는 과제 · 열쇠 꼴)와 남 시험 표의 대응 결정 칸(이제 404). 고치기 전 코드에서 10 이 진다. 변이 9/10 — 살아남은 D9 는 upsert 의
  주인 거름(앞 검사와 겹, MB-13).
- 편집자 쓰기(58f5c07) — 같은 파일에 쓰기 경로 표(라우터의 쓰기 경로 45 = 편집자에게 연 것 31 · 주인만 12 · 제 행만 2) — 편집자는 주인과 같은
  답(성공이든 같은 업무 거절이든), 주인의 부름이 사람 칸에 주인 이름을 적는 자리에 편집자 이름(새 행 · 바뀐 칸만 — 표마다 주 키로 앞 · 뒤를
  견준다), 편집자 몫 owner_sub 행 없음, 보기는 403 · 원장 그대로, 남 404, 주인만의 것은 편집자 · 보기 거절 · 원장 그대로(신원 해석 계측
  rr_metrics 는 뺀다). 남 시험 표의 부름이 빈 목록 · 어휘 밖 값 · 끝난 잡이라 사람 칸을 쓰지 않는 칸은 받는 값으로 부른다(게이트 G3 · 치수 ·
  판정 · 대상 · 계면 원장 · 잡 멈춤 — 주인이 세운 검토 잡). MCP 쓰기 도구 13 도 같은 셋. 낱 시험 — 남이 매단 행 · 관리자 · 두 주인 비교 · 편집자
  finding · 별칭 철회 감사 · 동결 자격 · MCP 브리프. 고치기 전 코드(a6daeb8)에서 33 이 진다. 변이 24/24(쓰기 문 넷 — 주인 대조 · 등급 · 남 내리기 ·
  관리자, 사람 칸 열 · 감사 둘 · 두 주인 · 옛 문 넷 · 브리프 토큰 · finding 주인 · 승계 원본).
- 이양(3618953) — test_member_reads 의 비교 시험을 새 규칙으로 고치고 셋을 더했다(다른 길로 모임 · 과제 안 리비전 비교와 변경 항목 · 대응 원장).
  고치기 전 코드에서 넷이 진다. 변이 7/7(앞 주인 검사 · 다른 쪽 주인 검사 · 변경 항목 · 대응 원장 · 부르지 않음 · pair 를 한 과제로 · 앞 주인
  기록 안 읽음).
- 같은 갈래(c99634f · a49e85f) — 구성원 판정 하나 · 계약 둘. 고치기 전에 진다(브리프 _member 가 owner 행을 구성원으로 · 합성 IR 이 계약 밖).
  변이 5/5(브리프 둘 · 러너 · 계약 note · 합성 해시).
- 대상 시험(커밋 전) — 역할 · MCP 에 닿는 파일 888 통과 · xfail 2, 이양에 닿는 파일 682 통과 · xfail 2, 합성기에 닿는 파일 528 통과 · xfail 2.
- 리스크 전체 시험(공유 잠금, -q 없이) — 첫 판(a49e85f) 3,978 통과 · 실패 1 · xfail 4(rc 1) — rr_findings 읽기 가드(test_review_findings)가 새
  `_finding_writer` 조회를 잡았다. 걸러 다시 돌린 판(751d4bf) 3,978 통과 · 실패 1(rc 1) — 이번에는 card_review 거름 자리 래칫(test_registry_cells)이
  새 거름 자리를 잡았다. 래칫 표에 까닭과 함께 적어(커밋을 고쳐 b9798ec) 끝 판 3,979 통과 · xfail 4 · 실패 0(rc 0, 12분 47초). 대상 시험이 그
  두 가드 파일을 고르지 않았다 — 새 rr_findings 조회 · card_review 글자는 test_review_findings · test_registry_cells 를 함께 돌린다.
- 하지 않은 것 — 서비스 · 인스턴스 기동 · 정지, push · 병합, 실 브라우저 확인.

### MB-19. 본 것 · 남긴 것
- 기존 편집자 길(`_target_editor` — 잡 만들기 · 좌석 · 셀 처분 · 쟁점 · 보고서 · 단위 · 방식 · 사람 finding 만들기, `_member_or_missing` — 다시
  저장)은 대상 행의 주인이 과제 주인인지 보지 않는다 — 남이 주인의 과제에 매단 대상(RD-10)에 편집자가 쓸 수 있다(새 쓰기 문 `_writer` 는 본다).
  그런 행은 MB-9 ① ② 가 센다(dev 0). → 조정자 요청으로 고쳤다(MB-20).
- risk_next_step 은 주인 과제만 걷는다 — 편집자도 그 쓰기를 하게 됐지만 길잡이는 넓히지 않았다(MB-4 남긴 것 그대로).
- 관리자는 쓰기에서 전 과제 편집자이지만(MB-14) 읽기 우회는 여전히 멤버 · 이력 · 대상 감사뿐이다(MB-1 남긴 것) — 관리자가 쓰는 대상의 읽기
  화면은 404 일 수 있다.
- 다른 가지(wt1031/risk-concurrency)가 progress_json 에 넣는 panels 지도 — 과제 상세의 jobs[].progress 는 progress_json 을 통째로 펼치므로 그
  지도가 그대로 보이고(구성원도 — 패널은 구성원 읽기다), 진행판의 job.signal 도 progress_json 전체를 신호로 펼친다. 숨기지 않았다(이 가지는
  그 칸을 모른다 — 합칠 때 그 가지가 정한다).
- 시험 파일의 앞선 lint 둘(이 가지가 만들지 않았다) — tests/test_claude_panel_jobs.py 에 같은 이름의 시험 함수가 둘이라(F811) 앞의 것이 돌지
  않는다. tests/test_backup_wrapper_run.py 에 ruff 지적 하나. → 조정자 요청으로 고쳤다(MB-21).

### MB-20. 기존 편집자 길도 과제 주인의 대상만(조정자 요청 10-31 · 845fdd5)
- `_target_editor(target_key, row, ident)` — 대상 행의 owner_sub 가 과제 주인이 아니면(남이 과제에 매단 대상 — RD-10) 관리자 우회보다 먼저 없는
  대상과 같은 404 를 내고, 그다음 종전처럼 편집자 이상(관리자 우회) · 보기 403 · 남 404 다. 부르는 자리 — 잡 만들기 · 좌석(coverage ·
  undefer) · 셀 처분(retry · skip) · 사람 finding 만들기와 `_editable_target`(단위 · 방식 · 쟁점 · 보고서 · MCP 셀 처분), MCP 잡 시작
  (entry.start_job — 살아 있는 잡을 돌려주는 갈래도 이 문 뒤다). 다시 저장(POST /panels/{id}/repersist)은 결과 제출의 `_panel_writer` 처럼
  패널 행의 주인을 본다.
- 새 쓰기 문 `_writer` 와 같은 규칙이다 — 남이 매단 대상은 과제 주인 · 편집자 · 관리자 · 보기 모두에게 없는 대상과 같고 원장은 그대로다. 한 가지
  다르다 — `_writer` 길은 행 주인 자신(그 대상을 들여온 사람)이 제 행에 쓰는 오늘의 길을 두고(그 길들은 원래 행 주인의 길이었다), 이 길들은 그런
  길이 처음부터 없었다(과제의 구성원 검사만 — 그 사람은 과제의 구성원이 아니라 404). 어느 쪽도 넓히지 않았다.
- 시험 — 쓰기 경로 표에 남이 매단 대상 칸을 더했다. 대상 · 쟁점 · 패널 · 잡으로 짚는 편집자 쓰기 15(기존 길 11 · 새 쓰기 문 넷 — 명단 갱신 ·
  판정 · 패널 결과 · 잡 조작)를 과제 주인 · 편집자 · 보기 · 관리자로 불러 없는 id 와 같은 답 · 원장 그대로를 보고, MCP 입구 넷(잡 시작 — 살아
  있는 잡을 심었다 · 사람 finding · 다시 저장 · 셀 처분)도 같다. 고치기 전 코드(4737637)에서 15 가 진다(기존 길 11 · MCP 넷 — 새 쓰기 문 넷은
  이미 막혀 있었다). 변이 7/7(행 주인 대조 끔 · 관리자에게만 대조 없음 · 등급을 보기로 · 다시 저장 대조 끔 · `_editable_target` 문 끔 · 대조
  늘 참 · MCP 잡 시작 문 끔 — 마지막 것은 처음에 살아남아(살아 있는 잡이 없으면 잡 만들기 라우트의 문이 대신 막는다) 심은 잡을 살아 있게 하고
  잡혔다).
- 대상 시험 — 그 길들을 부르는 시험 파일 50 과 가드 둘(test_review_findings · test_registry_cells) 1,295 통과.

### MB-21. 시험 lint 둘(조정자 요청 10-31 · 6f24240)
- tests/test_claude_panel_jobs.py 의 test_the_c3_follow_up_of_a_claude_tier_b_job_stays_on_glm 은 두 가지가 같은 이름으로 넣어(7d40238 10:16 —
  자격 순서(요청자)까지 본다 · 2bb6314 10:25 — job_llm None 을 본다, 서로 조상이 아니다) 합친 판에서 앞의 것이 가려져 돌지 않았다(F811). 앞의
  것(오래된 것)을 ..._with_the_glm_credential_order 로 바꿨다 — 둘 다 돌고 둘 다 통과한다(앞의 것이 지금 코드에서도 맞다).
- tests/test_backup_wrapper_run.py 의 쓰지 않는 import os 를 뺐다(F401). ruff 가 app · tests 전부 깨끗하다.
- 리스크 전체 시험 한 번(공유 잠금, -q 없이, 6f24240) — 4,000 통과 · xfail 4 · 실패 0(rc 0, 12분 57초 — 종전 3,979 에 남이 매단 대상 칸 20 과
  이제 도는 앞의 C3 시험 하나).

## 패널 잡 동시 실행 — 잡의 concurrency 를 실제로 읽는다(가지 `wt1031/risk-concurrency`, main 3a188f3 위, 2026-10-31)

> 사용자 결정 10-31 — 잡 만들기 칸 '동시 실행 ≤2'(`POST /targets/{key}/jobs` 의 concurrency)는 저장만 되고 러너가 읽지 않았다(RD-5 ·
> RD-9 남긴 것 3). "실제로 짓는다" — 동시 2 잡은 제 패널을 둘까지 함께 돌리고 동시 1(기본)은 종전 그대로다. 커밋 — 6fc775a(러너 · 원장 ·
> 진행판 · 시험) · 0fddbdf(화면) · 600d538(변이에 살아남은 것을 잡는 시험). routes.py 는 `coverage_payload` 의 signals 줄만 손댔다(같은 때
> 도는 구성원 읽기 · 들여오기 가지와 겹치지 않게).

### CC-1. 뜻 — 잡 하나가 박스의 전역 자리 안에서 자리를 둘까지 쓴다(전역 수는 늘지 않는다)
- 전역 자리는 그대로 `HWAXRISK_CONCURRENCY`(risk_concurrency, 기본 2 — 러너 세마포어)다. 잡의 concurrency 는 자리를 더하지 않고 잡 하나가
  그 자리를 몇 개까지 쓰나다(`runner.job_slots` — 잡의 값을 지금의 전역 자리 수로 다시 묶는다. 만들 때도 종전대로 묶는다).
- 까닭 — 에이전트 서버의 한도(`/limits` 의 max_running · max_seats_running)는 MCP 심의 잡(delib_jobs)만 센다. 웹 심의(리스크 패널)는 줄이
  없고 좌석 합에도 들지 않으며, 리스크 패널은 앱이 HWAXRISK_CONCURRENCY 로 묶는다고 보고 뺐다(포털 docs/delib-ops DO-D16). 잡의 동시
  실행이 전역 수를 넘기면 그 가정이 깨진다 — 그래서 늘지 않는다. 포털 정본 plan 의 '타깃당 패널 직렬 · risk_concurrency 는 타깃이 다를
  때만'(§6.4 · Settings 표)은 이제 '대상 안에서 잡끼리는 직렬, 잡 하나는 제 자리 수까지' 다(포털 세션에 넘길 문면).
- 기본 박스(전역 2)에서 동시 2 잡 하나만 돌면 패널 둘, 다른 대상의 잡이 같이 서 있으면 하나씩이다(CC-3).

### CC-2. 잡의 도는 패널은 러너가 센다(패널 행에 잡 열이 없다)
- rr_panels 에는 잡 열이 없고 스키마는 고정이다(리포 CLAUDE.md — v5 블록 밖에서 표 · 열을 바꾸지 않는다). 러너(`RiskRunner._running` — 잡
  id → 그 잡으로 돌리는 패널 id)가 센다. 틱이 편성하며 넣고 워커가 끝날 때 뺀다 — 닫는 중인(원장은 이미 done · error) 워커 몫까지다.
- 재기동하면 비고, 재기동 복구가 도는 패널을 다 닫으므로 원장과 어긋나지 않는다. 러너 잠금을 쥔 프로세스만 패널을 돌린다(종전).
- 집기(`claim_next_job(running=)`)는 대상의 running 패널 가운데 그 잡의 것이 아닌 것(다른 잡 · MCP 보충 회차의 패널)이 있으면 그 대상을
  건너뛴다 — 대상 안에서 잡끼리는 종전대로 직렬이다. `running` 을 주지 않으면(시험 · 단독 호출) 종전 판정 그대로다(대상에 도는 패널이 있으면
  건너뛴다).
- 같은 잡의 다른 패널이 도는가(`_sibling_running`)는 원장에서 같은 대상의 도는 패널로 본다 — 잡끼리 직렬이라 그 패널은 그 잡의 것이다.
  동시 1 잡은 늘 거짓이다(다른 길의 패널을 형제로 읽어 종전 동작이 바뀌지 않게 — 시험이 지킨다).

### CC-3. 둘째 자리는 첫 패널을 기다리는 잡이 없을 때만(공정)
- 집기는 두 번 훑는다 — 먼저 도는 패널이 없는 잡(먼저 선 차례), 그다음 자리가 남은 잡의 둘째 자리. 도는 패널은 빼앗지 않는다 — 전역 자리가
  다 찬 뒤 선 잡은 패널 하나가 끝나 자리가 나면 첫 자리로 먼저 받는다.
- 동시 1 잡만 있으면 둘째 훑기가 비어 종전 집기와 같다.

### CC-4. 편성은 틱 스레드에서 한 줄로 · 형제가 돌면 잡을 끝내지 않는다
- 종전에는 워커가 run_panel 안에서 편성했다. 한 잡의 두 워커가 함께 편성하면 같은 pending 좌석을 읽고 둘째의 선점 rowcount 가 어긋나 편성기가
  None 을 내는데, run_panel 은 None 을 '남은 좌석 없음' 으로 읽어 잡을 completed 로 닫는다(좌석이 남은 채). 그래서 틱이 편성 · 시작하고
  (`plan_job_panel` — 좌석 · 쟁점 running 까지) 워커는 그 패널을 돈다(`run_panel(panel=)`). run_panel 을 패널 없이 부르면 종전처럼 편성까지 한다.
- 남은 좌석이 없어도 형제가 돌거나 닫히는 중이면 잡을 끝내지 않는다(`siblings`) — 형제가 실패하면 좌석이 pending 으로 돌아온다. 형제가 다
  닫힌 뒤의 첫 자리 집기가 마저 편성하거나 끝낸다(C3 자동 후속도 그때 한 번).
- 둘째 자리는 그 Tier 에 pending 좌석이 있을 때만 집는다(`planner.has_pending`) — 꼬리에서 틱(5초)마다 집어 잡 행(credential_email · error)을
  다시 쓰지 않게. 집기와 편성 사이에 좌석이 사라지는 경합(사람의 좌석 넘기기 · MCP 편성)은 위 `siblings` 가 받는다(시험이 그 경합을 흉내 낸다).

### CC-5. Claude 길(외부 응답자)은 동시 1
- 계약은 막지 않는다 — 반출 동의는 잡마다라 그 잡의 패널 전부를 덮고(PANEL_EGRESS_WARNING '이 잡이 돌리는 패널마다'), 엔진의 외부 과제는
  주인(동의한 사람)마다 한 줄이며 과제 머리의 target_key 로 워크플로가 제 대상 것을 집고, 워크플로가 다른 과제를 쓰는 동안은 '없다' 로 치지
  않는다(external_llm — 바쁜 것이지 없는 것이 아니다). 웹 심의의 외부 길에는 주인마다의 상한도 없다.
- 그래도 묶는다 — 판단 호출이 전부 그 사람의 Claude Code 워크플로 하나(일꾼 기본 4)로 가는 사람 속도의 줄이라 두 패널을 함께 돌려도 빨라지지
  않고 둘 다 늦어져 패널 벽시계 · 답 한도에 더 다가간다. 한 패널이 external_worker 보류로 멈추면 형제도 닫힌다(CC-6). 엔진도 MCP 외부
  응답자 심의를 주인마다 한 건씩 돌린다(delib_jobs EXTERNAL_PER_OWNER = 1 · 포털 risk-claude-engine X-D6). claude-delib-parity CP-D7 의
  '동시 수는 죄지 않는다' 는 잡의 concurrency 가 읽히지 않던 때의 대상 사이 동시성이다 — 그것은 이번에 바꾸지 않았다.
- 만들 때 1 로 저장하고 답에 `concurrency_note`(CLAUDE_CONCURRENCY_NOTE)를 싣는다. 집기도 claude 잡은 1 로 본다(2 로 저장된 옛 행).
- 청한 것보다 적게 도는 다른 까닭(박스 전역 자리 수)도 답에 싣는다 — 종전에는 말없이 죄었다. 청한 만큼 돌면 칸이 없다(동시 1 잡의 답은 종전
  그대로). MCP `risk_start_job` 의 concurrency 설명도 이 뜻으로 고쳤다.

### CC-6. 멈춤 · 취소 · 보류 · 실패는 그 잡의 도는 패널 전부에 닿는다
- 패널마다 물음(`_stop_reader`)이 잡 행을 읽으므로 잡이 running 을 떠나면 도는 패널이 다 닫힌다(좌석 차감 없음 — 'cancelled' 는 스트림 유실
  부류). failed 도 닫는 상태에 더했다 — 동시 2 잡에서 한 패널의 연속 실패가 잡을 failed 로 끝내면 형제가 실패한 잡 밑에서 몇 시간 더 돌았다.
  동시 1 잡에서는 패널이 도는 동안 failed 로 가는 길이 없다(종전 그대로).
- 닫힌 형제의 글 — 사람의 정지 · 취소는 종전 글('사용자가 잡을 …') 그대로다. 코드가 멈춘 잡은 '잡이 멈췄다(<코드> · 보류 <코드>)', 엔진 쪽
  멈춤(A24)은 '잡이 멈췄다(사람이 포털에서 같은 잡의 다른 패널 심의를 멈췄다)', 실패는 '잡이 실패로 끝났다(<코드>)' 다(`_stop_why`).
- 취소의 마감 — 러너는 그 잡의 워커가 다 끝난 뒤에 cancelled 로 닫는다(cancel_job 문서의 '도는 패널이 스트림을 닫은 뒤' 그대로). 동시 1 잡도
  이제 그 워커가 돌아올 때까지 cancelling 으로 보인다 — 종전에는 다음 틱에 cancelled 였다(패널이 아직 돌 때도). 그 길이는 정해져 있지 않다
  (반대 검토 10-31 F9 로 고침 — 처음에 '길어야 20초' 라 적은 것은 틀렸다) — 스트림이 흐르면 프레임 하나 · ping(15초) + 물음 간격(5초)
  안이지만, 워커가 브리프를 짓는 중(필드 근거 HTTP 포함) · 포털 대화를 만드는 중 · 429 대기의 잠(HWAXRISK_ENGINE_BUSY_WAIT_S, 기본 30초)
  이면 그것이 끝날 때까지고, 읽기 한도를 끈 박스(HWAXRISK_ENGINE_READ_TIMEOUT_S 0)에서 조용히 멈춘 스트림이면 패널 벽시계까지다. 동시 1 잡에서
  달라진 것 전부는 CC-24.
- 멈췄다 곧바로 재개한 잡 — 앞 패널이 아직 닫히는 중이면 다시 집지 않는다. 다시 집으면 그 잡이 running 이 되고, 닫히던 패널의
  `_close_panel_stream_lost` 가 running 을 보고 잡을 다시 멈춘다. 동시 1 잡은 종전에도 대상이 바빠 집히지 않았다(같은 동작).
- 감사 — 사람 조작마다 한 행 그대로다(라우트가 쓴다). 패널이 닫히며 쓰지 않는다 — 앱의 물음으로 닫힌 패널은 잡을 옮기지 않고, 엔진 쪽 멈춤
  (A24)은 먼저 닫힌 패널이 잡을 멈추며 한 행, 형제는 이미 멈춘 잡을 본다.

### CC-7. 형제가 도는 동안의 '사이 판정'은 잡을 멈추지 않고 둘째 자리만 막는다
- 하루 상한 · 수확 체감은 종전에 패널 사이(도는 패널이 없을 때)에만 일어났다. 형제가 도는 동안 잡을 멈추면 정당하게 시작한 그 패널이 닫힌다
  — 엔진은 분리 태스크로 그 심의를 끝까지 돌리므로 LLM 은 쓰고 결과만 잃는다. 그래서 형제가 도는 동안에는 둘째 자리만 막고, 마지막 형제가
  끝난 뒤의 판정(완료 직후의 수확 체감 · 첫 자리 집기의 하루 상한)이 종전대로 멈춘다.
- 수확 체감 정지는 이제 잡이 아직 running 일 때만 쓴다 — 종전에는 무조건 써서, 저장 도중에 사람이 건 취소(cancelling)나 실패를 paused 로 덮을
  수 있었다(동시 1 에서는 좁은 틈).
- 집기의 수확 체감은 C1 여부를 보지 않는다(완결 레벨을 다시 세지 않는다) — 둘째 자리만 더 보수적으로 막을 뿐이고 멈춤 판정은 종전 자리다.

### CC-8. 엔진 자리 없음(포털 429)과 동시 2
- 웹 패널의 '바쁨' 답은 포털 429(agent_semaphore)뿐이다 — 에이전트 서버의 한도는 웹 심의를 줄 세우지도 세지도 않는다(CC-1). 그래서 러너의
  engine_busy 처리(간격 · 예산 · 시작 못 함 · 차감 없음)를 두 패널에서 그대로 쓰고 하나만 바꿨다.
- 둘째 패널이 예산을 다 써도 형제가 돌면 잡을 멈추지 않는다(멈추면 자리를 얻어 잘 도는 형제가 닫힌다) — 그 패널만 닫고(engine_busy … 꼬리
  ENGINE_BUSY_SIBLING_NOTE) 그 대상의 둘째 자리는 쉰다(`_busy_backoff` — 가장 늦게 닫힌 error 패널이 engine_busy 일 때, 그 뒤로 예산이 아직
  지나지 않았거나 그 패널이 자리를 포기할 때 돌던 형제가 아직 돌면). 쉬지 않으면 다음 틱이 곧바로 새 패널을 편성해 또 한 시간 429 를
  기다린다(패널 행만 쌓인다). 형제 조건은 예산 0(HWAXRISK_ENGINE_BUSY_MAX_WAIT_S=0 — 기다리지 않는 박스) 때문이다 — 예산만 보면 그 박스에서는
  틱(5초)마다 둘째 패널이 하나씩 429 로 닫혀 쌓인다. 형제가 없으면 종전대로 멈춘다.
- 형제의 대기 중 취소 · 정지는 종전 길(대기 루프의 물음)로 듣는다.

### CC-9. 패널마다 신호 — 동시 2 잡은 progress_json 에 패널별 칸
- `_progress_writer(per_panel=)` — 잡 행의 맨 위 칸은 종전처럼 마지막에 적은 신호(진행판 `signal` 호환)이고, `panels{패널 id: 신호}` 에도
  적는다. 두 워커가 같은 행을 쓰므로 읽고 고쳐 쓰기를 저장소 트랜잭션 하나로 한다. 패널이 닫히면 그 칸을 지운다(`_drop_panel_signal`).
- 진행판(`coverage_payload`) — signals 는 그 칸의 도는 패널(+ 맨 위 신호가 살아 있으면 그것)을 차례(panel_no)대로, signal 은 맨 위 신호가
  닫힌 패널이면 가장 늦게 시작한 도는 패널이다.
- 동시 1 잡의 행은 바이트째 종전이다(그 칸이 없다 — 기존 시험이 잡 행 전체를 견준다). 과제 상세의 잡 목록 `progress` 는 progress_json 을
  펼치므로 동시 2 잡이면 `panels` 가 더 실린다(더해지기만 한다 — 그 함수는 구성원 읽기 가지의 것이라 손대지 않았다).

### CC-10. 연속 실패 셈은 도는 패널을 건너뛴다
- `_error_streak` 은 panel_no 내림차순으로 error 를 세다 error 가 아닌 패널에서 멈춘다. 동시 2 잡은 실패한 패널 사이에 형제가 돌고 있어 거기서
  멈추면 셈이 셋에 닿지 않는다 — 실패마다 좌석만 차감돼 skipped 로 굳고 잡은 죽지 않는다. 도는 패널은 건너뛴다(planned 는 종전대로 끊는다).
- 동시 1 잡에서 다른 점은 다른 길(MCP 보충 회차 제출)의 패널이 바로 그 순간 running 인 좁은 경우뿐이다(종전에는 셈이 0 으로 끊겼다).

### CC-11. C3 자동 후속 Tier C 는 동시 실행을 물려받는다
- 메모 · 층 · 뺀 항목과 같은 실행 손잡이다(사람이 B 잡에 고른 것). 판단 LLM · 동의는 종전대로 물려받지 않는다(RD-7) — Claude B 잡은 동시
  1 로 저장되므로 그 후속(GLM)도 1 이다. 동시 1 잡의 후속은 종전대로 1 이다.

### CC-12. 원장 불변식 (2) — 대상의 도는 패널은 살아 있는 잡의 자리 수까지
- `planner.check_invariants` (2) 가 '≤1' 대신 그 대상의 살아 있는 패널 · 쟁점 잡의 가장 큰 자리 수(없으면 1)를 쓴다. 좌석 수 검사(running 좌석 ≤
  5 × 도는 패널 수)는 그대로다.

### CC-13. 뜻이 달라지는 것(받아들인 것)
- 형제가 도는 동안 시작한 패널의 브리프에는 그 형제의 결과가 아직 없다(등록부 · 선례 E5 · 좌석 기억 E7 은 끝난 패널의 것이다). 동시 실행의
  값이다.
- 등록부는 패널이 끝날 때마다 대상 전체를 다시 병합한다(`registry.merge` — 멱등 재계산)라 끝나는 차례가 바뀌어도 마지막 등록부는 같다. 옛
  정본이 동시성을 막은 까닭('같은 IR 을 두 패널이 동시에 보면 등록부 병합 순서가 흔들린다')은 그 구현으로 풀려 있다. 차례에 달린 것은
  패널마다의 `new_clusters`(먼저 끝난 패널이 센다 — 수확 체감의 입력)와 brief_drift(얼린 차례로 견준다)다.
- 쟁점 잡은 그대로 동시 1 이다 — M3 결정(대상 안에서 쟁점 패널은 한 줄 — 카드 대조와 같은 LLM 을 나눈다). 사슬이 1 로 만들지만
  (issues.create_issues_job) 그 값에 기대지 않고 `job_slots` 가 쟁점 잡을 1 로 본다 — 쟁점 길의 진행판 advice 고쳐 쓰기(`_note_issue_yield`)는
  트랜잭션 밖의 읽고 고쳐 쓰기라 두 패널이 겹치면 칸을 잃는다.

### CC-14. 시험 · 변이
- 새 시험 `tests/test_panel_concurrency.py` 22 — 진짜 러너(RiskRunner, 틱은 손으로) + 진짜 엔진 클라이언트(PortalPanelEngine)를 패널마다
  스트림을 줄 단위로 흘리는 가짜 포털에 물린 것 — 두 패널 섞여 흐름(좌석 겹침 없음 · 패널별 신호 · 늦게 시작한 쪽이 먼저 끝남 · 꼬리에서 끝내지
  않음 · 편성 경합) · 동시 1 그대로 · 하나 실패와 돌아온 좌석의 새 패널 · 도중 멈춤/취소(늦게 닫히는 패널 · 감사 한 행 · 재개) · 형제를 닫는
  의장 실패의 글 · 연속 실패가 형제를 닫음. 러너 없이 — 재기동 복구(두 패널) · 429(형제 · 예산 쉼 · 예산 0 의 형제 쉼) · 동시 1 은 다른 길의
  패널을 형제로 읽지 않음 ·
  하루 상한 · 수확 체감 · 재개 · 취소 마감 · 공정 · 대상 직렬 · 자리 수(박스 · 쟁점 · Claude) · Claude 1 · concurrency_note · C3 후속 · 불변식 ·
  연속 실패 셈. 다섯~여덟 번
  되풀이해 흔들림이 없다(같은 초에 선 두 잡의 차례가 uuid 라 흔들린 시험 하나는 차례를 고정했다). 대상은 생산자 경로(factories.make_diff_target)로
  세운다 — 처음에 손 INSERT(rr_diffs 1 · rr_panels 2)로 세웠다가 전체 시험의 씨앗 출처 래칫(tests/rr/test_fixture_provenance)에 걸려 걷었다
  (연속 실패 셈의 패널은 편성기로 세우고 상태만 고치고, 수확 체감 시험은 판정 함수를 대역으로 둔다 — 그 판정은 test_runner_panel 이 본다).
- 고치기 전 코드(3a188f3) 사본에 얹으면 20 이 다 진다(뒤에 더한 자리 수 · 예산 0 시험 둘도 없는 함수 · 인자라 진다). 동작으로 지는 것 — 러너 시험 여섯은 '2 번째 스트림이 열리지 않았다'(옛 러너는 둘째
  패널을 시작하지 않는다), 429 는 ('paused', 'code:engine_busy'), C3 후속은 1 ≠ 2, 불변식은 (2) 위반, 연속 실패는 1 ≠ 3, Claude · note 는 칸이
  없다. 나머지는 없는 인자 · 함수(claim_next_job running · plan_job_panel)다. 지킴 시험 둘(동시 1 그대로 · 동시 1 은 다른 길의 패널을 형제로
  읽지 않음)은 옛 코드에서 동작은 같고 새 이름(PROGRESS_PANELS_KEY · ENGINE_BUSY_SIBLING_NOTE)이 없어서만 진다.
- 변이(스크래치 사본 · 바이트코드 끔) 백엔드 30/30 — 429 쉼의 예산 창 · 형제 조건 · 쟁점 잡 1 · 대상 직렬 · 자리 수 · 공정 · 취소 마감 · 재개 · 하루 상한 · 429 쉼 · 수확 체감(집기 ·
  완료) · 꼬리 · Claude(집기 · 저장) · note · 형제가 돌면 끝내지 않음(편성 · 틱) · 429 형제 · 까닭 글 · failed 닫음 · 연속 실패 · 패널별 칸 · 칸
  지움 · signals · signal 대체 · 불변식 · C3 후속 · 동시 1 형제 없음 · 집기가 러너의 패널을 읽음. 처음 돌림에서 넷이 살아(수확 체감 둘째 자리 ·
  형제 끝내기 둘 · signal 대체) 시험을 더했다. 화면 4/4. 사본과 작업 트리는 diff 0, __pycache__ 없음.
- 화면 — 시험 107 → 108(옛 신호 줄에 얹으면 진다 — 한 줄만 그린다), `tsc -b` · `vite build` · `pnpm test` 통과. 서버 견본 coverageJobTwoPanels
  는 이 가지의 실 백엔드 하네스 응답이다.
- 리스크 전체 시험(공유 잠금 아래 한 번, 31df680) — 3,811 통과 · xfail 4 · 실패 0(rc 0, 12분 41초). 그 앞 판의 한 번은 씨앗 출처 래칫 하나가
  붉어(위) 고친 뒤 다시 돌렸다. ruff — 바꾼 파이썬 파일은 깨끗하다.
- 하지 않은 것 — 서비스 · 인스턴스 기동 · 정지 · 재배포, push · 병합, 배선 리허설(`tests/synth/rehearsal_d.py` — 프로세스를 띄운다 · 카드 대조
  사슬은 바꾸지 않았다), 실 엔진 · 포털로 두 패널 돌리기(가짜 포털 스트림까지만).

### CC-15. 남긴 것
- 포털 정본 문면(포털 세션) — design-risk-review/plan.md §6.4 '타깃당 패널은 직렬 · 서버 전역 동시 패널은 타깃이 다를 때만', Settings 표의
  HWAXRISK_CONCURRENCY '타깃 다를 때만', §6.7 · §8.2.9 의 '타깃당 직렬' 을 CC-1 의 뜻으로.
- MCP `risk_start_job` 이 같은 Tier 의 살아 있는 잡을 돌려줄 때 그 잡의 concurrency 를 싣지 않고 다른 값을 청해도 differs 에 넣지 않는다
  (entry.start_job — 결정 필요).
- 종전부터 — 편성기의 선점 경합(PlanConflict — MCP 브리프 편성 · 사람의 좌석 넘기기가 읽기와 선점 사이에 끼면)이 None 을 내면 첫 자리의
  run_panel · plan_job_panel 은 '남은 좌석 없음' 으로 읽어 잡을 끝낸다(좌석이 남은 채). 러너 쪽 편성은 틱 한 줄이라 이번 일로 늘지 않았다.
- (뺐다 — 반대 검토 10-31 F6) 에이전트 서버의 '새 심의 멈춤'(delib_paused)이 패널을 차감되는 engine_error 로 닫는다고 적었는데 닿지 않는
  길이다 — 엔진은 그 멈춤을 사람이 띄운 심의에만 건다(HWAXAgentServer app.py — `started_by != "app"` 일 때만 판정한다). 러너는 패널마다
  started_by app 을 싣는다(STARTED_BY_APP).
- 종전부터 — 편성과 시작 사이(틱 안의 몇 ms)에 앱이 죽으면 planned 러너 패널의 좌석이 assigned 로 남는다(재기동 복구는 running 만 본다).
- 화면 — 잡 만들기 답의 concurrency_note 줄은 렌더 시험이 없다(credential_note 줄과 같은 한 줄 그리기).

## 패널 잡 동시 실행 — 반대 검토 10-31 고침(가지 `wt1031/risk-concurrency`, 2229b32 위, 2026-10-31)

> 메인 세션이 받은 독립 반대 검토(F1 ~ F10)를 고쳤다. 고치기 전에 하나씩 재현했다 — 2229b32 사본에 새 시험을 얹으면 이번 시험 29 가운데 23 이
> 진다(지킴 6 은 같다). F3 은 메인 세션의 결정(검토자의 제안대로)이다. 커밋 ec9e040(코드 · 시험) 과 이 문서.

### CC-16. 집기의 쓰기는 한 문장 — 읽은 상태 그대로일 때만(F1 · F8)
- 재현 — 둘째 자리 집기가 잡을 읽은 뒤 비우기 물음(/health 왕복) 사이에 첫 패널이 의장 실패로 잡을 멈추면, 집기의 마지막 쓰기
  (`credential_email · error`)가 그 멈춤 글을 NULL 로 지우고 둘째 패널을 편성 · 시작했다(엔진은 그 심의를 분리 태스크로 끝까지 돈다). 줄 선
  잡의 첫 자리도 같다 — 자격을 고르는 사이 사람이 취소 · 정지하면 `cancelled → running` 으로 덮었다(종전부터, F8).
- 고침 — 집는 쓰기 하나(`UPDATE … WHERE id = ? AND state = <읽은 상태>`, queued 면 running 으로 옮기기까지 같은 문장)가 0 행이면 집지 않는다.
  같은 판정의 다른 쓰기도 조건을 단다 — 기다리는 까닭 글(다시 저장 · 비우기 · 자격 없음), 첫 자리의 하루 상한 정지, 자정의 다시 줄 세우기
  (paused 일 때만), 취소의 마감(cancelling 일 때만). `_set_job(expect=)` 가 그 문장이다.
- 처음에 '미뤄 둔 멈춤이 없을 때만' 도 같은 문장에 걸었다가 걷었다 — 잡 하나가 패널을 둘까지만 돌리므로 둘째 자리를 집는 동안 미뤄 둔 멈춤이
  생길 수 없고(미루려면 도는 형제가 있어야 하는데 그러면 자리가 다 찼다), 생겨도 아래 시작 전 물음이 받는다. 둘째 자리의 판정은 그 칸을
  먼저 본다.

### CC-17. 워커는 엔진에 보내기 바로 앞에서 다시 묻는다(F1)
- 틱이 편성한 뒤 워커가 브리프를 짓는 사이(필드 근거 HTTP · 모델 물음)에 잡이 멈췄거나 실패로 끝났거나 미뤄 둔 멈춤이 생기면, 포털 대화도
  만들지 않고 그 패널을 시작 못 한 것으로 닫는다(`cancelled: … — 엔진에 보내기 전에 닫았다`, 좌석 차감 없음). 종전에는 보낸 뒤 첫 프레임에서야
  들어 엔진의 분리 태스크가 끝까지 돌았다.

### CC-18. 패널 하나의 일은 형제가 끝날 때까지 미룬다(F2 · F3 — CC-6 · CC-7 일부 뒤집음, 메인 세션 결정)
- 재현 — 의장 실패 · 스트림 벽시계 · 침묵 · 결정론 브리프 오류가 몇 시간째 잘 도는 형제를 곧바로 닫았다(엔진은 그 형제의 심의를 끝까지 돌고
  결과는 원장에 안 온다). 형제가 돌아 미룬 수확 체감 정지는 마지막 형제가 done 으로 끝날 때만 다시 판정해, 그 형제가 실패로 끝나면 잡이
  running 으로 남아 다음 첫 자리가 셋째 패널을 편성했다(F2).
- 고침 — `_stop_job` 이 같은 잡의 다른 패널이 돌면 잡을 옮기지 않고 progress_json 의 `deferred` 칸({state, by, reason, error, panel_id, at})에
  적는다. 그동안 새 자리는 주지 않고(집기의 둘째 자리 · 워커의 시작 전 물음 · 엔진 자리 대기의 물음 — CC-28), 잡 행 error 에 까닭과 '그 패널이
  끝나면 멈춘다' 를 보인다(부르는 쪽 글의 '잡을 멈췄다' 꼬리는 뺀다 — CC-28). 마지막 형제가 닫힐 때(run_panel 의 끝 — 그 형제가 어떻게
  끝났든) 옮긴다(`_apply_deferred_stop` — 잡이 running · queued 일 때만 쓰고 쓴 때만 칸을 걷는다, CC-29 고침).
- 미루는 것 — 의장 실패(chair_failed) · 결정론 브리프 오류 · 브리프 일시 장애 잇달음 · 스트림 벽시계 · 침묵 · 절단 · 연속 실패(failed) · 수확
  체감. 실패가 멈춤을 이긴다 — 미룬 실패가 있는데 마지막 형제가 제 일로 곧바로 멈추면 실패로 끝난다. 멈춤끼리는 나중 것이 앞에 서고 앞의 까닭이
  error 뒤에 붙는다(같은 까닭이면 붙이지 않는다).
- 사람의 재개가 걷는다 — 사람이 멈췄다 재개하면 그 칸을 지운다(사람의 뜻이 이긴다). 형제가 도는 동안의 재개는 끝에서 'running 일 때만' 이 이미
  막지만, 옮기다 실패해 칸이 남은 잡(다음 집기가 그 칸을 옮긴다 — 아래)에서는 재개가 걷지 않으면 사람이 재개한 잡을 집기가 다시 멈춘다.
  사람의 정지 · 취소 · 엔진 쪽 멈춤(A24)도 그때 걷는다(정지 · A24 는 그 까닭을 error 에 남긴다 — CC-32 고침).
- 집기의 안전망 — 러너가 그 잡의 패널을 다 놓았는데 칸이 남았으면(마지막으로 닫힌 것이 다른 길의 패널 · 옮기다 실패) 다음 첫 자리 집기가
  옮긴다(새 패널을 주지 않는다). 기동 복구도 끊기지 않은 대상의 running 잡에 남은 칸을 옮긴다(CC-29). 안전망은 틱이 전역 자리를 얻을 때만
  돈다(CC-35).
- 동시 1 잡은 형제가 없어 늘 곧바로다(종전 그대로). 쟁점 잡은 동시 1 이다.

### CC-19. 곧바로 옮기는 멈춤 — 형제도 닫힌다(F3 의 지킴)
- 사람의 정지 · 취소, 엔진 쪽 멈춤(A24 — 사람이 포털에서 한 패널 심의를 멈췄다, 그 사람의 job.pause 한 행), 보류(external_worker · credential ·
  external_config), 다시 저장을 기다리는 일(persist_error — 그 대상은 다시 저장 전까지 편성되지 않는다), 자격 실패(pat_unavailable), 배선 결손
  (missing_interface). 잡이 running 을 떠나면 그 잡의 도는 패널이 다 닫힌다는 CC-6 의 규칙은 그대로다 — 패널 하나의 일이 형제가 도는 동안
  잡을 running 에서 떼지 않게 된 것이 바뀐 점이다.

### CC-20. 러너의 자동 전이는 확인과 쓰기를 한 트랜잭션으로(F4)
- 재현 — 수확 체감 정지가 잡 상태를 읽고(running) 쓰는 사이에 다른 스레드의 사람 취소가 끼면 정지가 그 취소를 paused 로 덮었다(감사 행은
  job.cancel). `_pause_running_job` · `_close_panel_unstarted` · `_close_panel_no_decision` · 보류 둘 · 동의자 없음 보류가 같은 꼴이었다
  (`_close_panel_stream_lost` 만 트랜잭션이었다).
- 고침 — 전부 `_stop_job` 하나를 지난다(저장소 트랜잭션 안에서 running 확인 → 쓰기). 사람의 취소는 그 트랜잭션 뒤에 선다(시험은 두 스레드로
  끼운다). 연속 실패 · 자격 실패 · 배선 결손의 failed 도 running 일 때만 쓴다 — 종전에는 무조건이라 패널이 도는 사이 사람이 건 취소를 failed 로
  덮을 수 있었다.

### CC-21. 닫힌 패널의 신호 칸이 쌓이지 않는다(F5)
- 재현 — 앱이 죽은 뒤 복구 → 재개 → 새 패널이 잡 행에 죽은 패널 둘의 칸을 그대로 두었다(과제 상세의 잡 목록이 progress_json 을 그대로 편다).
- 고침 — 재기동 복구가 끊긴 대상 잡의 `panels` 칸을 비우고 미뤄 둔 멈춤도 걷는다(그 까닭은 restart 멈춤 글 끝에 붙인다). 신호를 적는 쪽은 원장에서
  도는 패널의 칸만 남긴다(같은 트랜잭션, 미뤄 둔 멈춤 칸은 그대로). 끊기지 않은 대상의 running 잡에 남은 미뤄 둔 멈춤은 복구가 옮긴다(CC-29).

### CC-22. 편성기의 선점 경합을 '남은 좌석 없음' 으로 읽지 않는다(F7 — 종전부터)
- 재현 — 편성기가 좌석을 고른 뒤 선점 전에 사람이 그 좌석을 넘기면(또는 MCP 브리프 편성이 끼면) rowcount 가 어긋나 None 이고, 첫 자리는 그것을
  끝으로 읽어 Tier C 좌석 17 이 pending 인 채 잡을 completed 로 닫았다.
- 고침 — None 이면 그 Tier 에 pending 좌석이 남았나(`planner.has_pending`)를 다시 보고, 남았으면 끝내지 않는다 — 다음 집기가 다시 편성한다. 쟁점
  잡은 손대지 않았다(그 경합은 쟁점 상태를 사람이 바꾸는 좁은 경우뿐이다 — CC-27).

### CC-23. 상한 둘 · 후속은 실제 자리 수 · 셈은 닫힌 차례(F10)
- 잡의 동시 실행은 둘까지다(`MAX_JOB_CONCURRENCY`) — 본문(JobBody · MCP risk_start_job)이 1 ~ 2 밖이면 422 이고, 박스의 전역 자리가 더 많아도
  `job_slots` · create_job 이 둘로 묶는다. 화면 · 계약('≤2')과 같다. 0 · 음수도 422 다(종전에는 받아 저장했다). 검사 자리 · MCP 스키마 · 검토
  잡의 까닭은 CC-33.
- C3 자동 후속 Tier C 는 B 잡이 실제로 돈 자리 수(`job_slots`)를 물려받는다 — 2 로 저장된 옛 Claude B 잡(동시 1 로 돌았다)의 후속은 1 이다(CC-11
  고침).
- 연속 실패 · 수확 체감 · 브리프 재시도 셈은 닫힌 차례(ended_at, 같으면 panel_no)로 본다 — 번호가 앞인 형제가 나중에 잘 끝나면 셈이 끊기고 창에
  든다. 한 줄로 도는 동시 1 잡도 러너 패널끼리는 번호 차례와 닫힌 차례가 같지만(같은 초면 번호로), 같은 대상에 MCP 길 패널이 섞이면 판정이
  바뀐다(CC-34 — 처음에 '같다' 고만 적은 것을 고쳤다).

### CC-24. 동시 1 잡에서 달라진 것 전부(F9 — 앞 목록을 고치고 더함)
1. 취소의 마감은 그 잡의 워커가 돌아온 뒤다 — 길이는 정해져 있지 않다(CC-6 고침 — 브리프 조립 · 대화 만들기 · 429 대기의 잠 · 읽기 한도를 끈
   박스의 멈춘 읽기).
2. 다음 패널은 앞 패널의 워커가 다 끝난 뒤에 집힌다 — 종전에는 패널 행이 running 을 떠나면(워커가 통합 보고서를 짓는 등 마무리 중이어도) 다음
   틱에 집혔다.
3. 편성(과 남은 좌석이 없을 때의 잡 마감 · C3 자동 후속 만들기)이 워커가 아니라 틱 스레드에서 돈다.
4. 워커를 띄우지 못하면 그 패널을 'stopped' 로 닫은 error 행이 남는다(종전에는 편성 전이라 행이 없었다 — 그 대신 세마포어가 새고 잡이 패널 없이
   running 이었다).
5. 엔진에 보내기 바로 앞의 물음(CC-17) — 편성 뒤 · 보내기 전에 사람이 취소 · 정지하면 그 패널은 보내지 않고 닫힌다(글 '엔진에 보내기 전에
   닫았다').
6. 러너의 자동 전이가 사람의 취소 · 정지를 덮지 않는다(CC-20) · 집기가 사이에 바뀐 잡을 덮지 않는다(CC-16) · 수확 체감 정지도 running 일 때만.
7. 연속 실패 셈이 도는 패널을 건너뛰고(CC-10) 닫힌 차례로 본다(CC-23).
8. 편성기의 선점 경합에 잡을 끝내지 않는다(CC-22).
9. 청한 것보다 적게 돌면 답에 concurrency_note(CC-5), 1 ~ 2 밖의 concurrency 는 422(CC-23 · CC-33 — 0 · 음수 포함).
10. 같은 대상에 MCP 길 패널(브리프 편성 → 결과 제출)이 섞이면 연속 실패 · 수확 체감 판정이 닫힌 차례로 달라진다(CC-34).
11. 집은 뒤 편성 전에 사람이 취소 · 정지하고 남은 좌석이 없으면 잡을 completed 로 덮지 않고 C3 자동 후속 · 사슬도 잇지 않는다(CC-31 — 종전에는
    덮었다).

### CC-25. cae00 반영 때 — 이미 2 로 저장된 잡
- 칸이 아무 일도 하지 않던 동안 화면에서 동시 2 를 골라 만든 살아 있는 잡은 이 판을 받은 뒤 패널 둘을 함께 돈다(전역 자리는 그대로 — 기본
  2). 보는 법(읽기 전용) — 앱 데이터 디렉터리에서
  `sqlite3 -readonly risk_review.db "SELECT id, target_key, tier, state, concurrency FROM rr_jobs WHERE state IN ('queued','running','paused') AND COALESCE(mode,'panels') = 'panels' AND concurrency > 1"`.
  Claude 잡은 몇으로 저장됐든 1 로 돈다.
- 묶는 법 — (가) 박스 전체를 한 줄로 — 앱 env 에 `HWAXRISK_CONCURRENCY=1` 을 적고 앱을 다시 띄운다(모든 잡이 1 · 전역 자리도 1). (나) 잡 하나 —
  그 잡을 취소하고 동시 1 로 다시 만든다(화면). 앱이 떠 있는 동안 DB 를 손으로 고치지 않는다 — 꼭 고쳐야 하면 앱을 내린 뒤
  `UPDATE rr_jobs SET concurrency = 1 WHERE id = '<잡>'`(러너는 집을 때마다 읽는다).
- 이 줄은 포털 리포의 cae00 절차서(리스크 앱 반영 절)에 옮겨 적을 몫이다 — 이 세션은 포털 리포를 고치지 않는다.

### CC-26. 시험 · 변이
- 새 시험 26 항목(함수 23) — F1(집기 · 시작 전 물음 · 기다림 글) · F8(첫 자리 · 자정 재개 · 하루 상한 정지) · F2(실패로 끝난 마지막 형제 · 재개가 걷음 ·
  사람의 정지가 이김 · 집기의 안전망 · 남은 칸의 재개) · F3(의장 실패 러너 · 벽시계 · 침묵 · 브리프 오류 · 미룬 실패가 이김 · A24 곧바로 · persist_error
  곧바로) · F4(두 스레드 경합 · 앞선 취소) · F5 · F7 · F10(상한 · 옛 Claude 후속 · 닫힌 차례 셋). 고친 시험 둘 — 의장 실패로 형제를 닫던 시험은
  곧바로 닫는 persist_error 로, 연속 실패로 형제를 닫던 시험은 형제를 기다리는 것으로. 러너 없이 '형제가 도는 동안' 을 한 스레드로 짓는
  `_InFlight`(엔진 호출 도중에 다른 패널을 닫는다 — 시작 전 물음을 이미 지난 형제)를 썼다.
- 고치기 전(2229b32 사본) — 이번 시험 29(새 26 + 고친 2 + 다시 지은 수확 체감 1) 가운데 23 이 진다 — 지킴 6(곧바로 닫는 persist_error 둘 · A24 ·
  수확 체감 · 앞선 취소 · 재개가 걷음)은 같다.
- 변이(스크래치 사본 · 바이트코드 끔) 33 가운데 32 — 살아남은 하나(미룸 칸의 실패 우선 — 미룸 쪽)는 잡이 패널을 둘까지만 돌리는 동안 같은
  판이다(미루려면 형제가 돌아야 하고 그러면 자리가 다 차, 미룸이 둘 쌓이지 않는다). 처음 돌림의 '재개가 걷는다' 는 살아남아 남은 칸의 재개 시험을
  더해 잡았다. 사본과 작업 트리는 diff 0, __pycache__ 없음.
- 관련 시험 638 통과. 리스크 전체 시험(공유 잠금 아래 한 번, 8d18a7b) — 3,837 통과 · xfail 4 · 실패 0(rc 0, 13분 25초 — 앞 판 3,811 에 새 26).

### CC-27. 남긴 것
- 포털 cae00 절차서에 CC-25 의 줄(포털 세션 몫).
- 쟁점 잡의 편성 경합(CC-22 밖) — 쟁점 상태를 사람이 바꾸는 사이에 끼면 그 잡이 끝날 수 있다(종전부터 · 좁다).
- CC-15 의 남은 줄(MCP 살아 있는 잡의 concurrency · 종전부터의 planned 좌석)은 그대로다.

## 패널 잡 동시 실행 — 반대 검토 2차 10-31 고침(가지 `wt1031/risk-concurrency`, c4bdfa7 위, 2026-10-31)

> 메인 세션이 받은 2차 검토(`git diff 2229b32 c4bdfa7` — R2-1 ~ R2-8 · N31)를 고쳤다. 하나씩 재현했다 — c4bdfa7 사본에 새 시험을 얹으면 16 항목
> 가운데 15 가 진다(N31 고정 하나는 규칙을 묶는 시험이라 같다). 커밋 e91db9b(코드 · 시험)와 이 문서. CC-18 · CC-21 · CC-23 · CC-24 의 해당 줄도
> 고쳤다(고친 줄마다 이 절의 번호를 단다).

### CC-28. 엔진 자리를 기다리는 패널도 미뤄 둔 멈춤을 읽는다 · 미뤄 둔 동안의 글(R2-1)
- 재현 — 둘째 패널이 포털 429 로 자리를 기다리는 사이 형제가 의장 실패로 끝나 멈춤을 미루면, 대기 루프는 사람의 취소 · 정지만 물어
  (`should_stop`) 자리가 나자 그 패널의 심의 전체를 보냈다. 엔진에 보내기 전 물음(CC-17)과 어긋났다.
- 고침 — 대기 루프의 물음도 `should_stop() or _deferred_why(…)`(동시 2 잡만)다. 기다리던 패널은 시작 못 한 것으로 닫히고(cancelled · 좌석 차감
  없음 · 글 '잡이 멈출 참이다(<까닭>) … 엔진 자리를 기다리던 패널을 닫았다'), 그 패널이 마지막 형제면 run_panel 의 끝이 그 멈춤을 옮긴다.
- 미뤄 둔 동안 잡 행 error 는 부르는 쪽 글의 ' — 잡을 멈췄다(…). 재개하면 …' 꼬리를 뺀다(`STOPPED_TAIL`) — 잡은 아직 running 인데 '멈췄다' 와
  '그 패널이 끝나면 멈춘다' 가 한 줄에 함께 섰다. 옮긴 뒤에는 부르는 쪽 글 그대로다(의장 실패 · 스트림 벽시계 · 브리프 오류 셋을 본다).

### CC-29. 미뤄 둔 멈춤은 옮겨야 걷는다 — 기동 복구 · 줄에 선 잡(R2-2)
- 재현 — 마지막 형제의 패널 행이 닫힌 뒤 그 워커의 끝(`_apply_deferred_stop`)에 닿기 전에 앱이 내려가면, 기동 복구는 도는 패널이 없는 대상의
  running 잡을 queued 로 돌리며 error 를 지웠다(칸은 남는다). 다음 집기의 안전망은 'running 일 때만' 쓰기가 0 행인데 칸을 걷어, 그 잡이 멈춤
  없이 다시 돌았다.
- 고침 — (1) 기동 복구가 끊기지 않은 대상의 running 잡에 칸이 남았으면 그 멈춤을 옮긴다(그 밖은 종전대로 queued — 그 쓰기도 'running 일
  때만'). (2) `_apply_deferred_stop` 은 잡이 running · queued(`DEFERRED_APPLY_STATES`)일 때만 쓰고, 쓴 때만 칸을 걷는다. 사람이 멈춤 · 취소한
  잡에는 쓰지 않고 칸도 그대로다 — 그 조작이 칸을 걷으므로(CC-32) 남는 일은 드물고, 남으면 재개가 걷는다.
- queued 에도 쓰는 까닭 — 쓰지 못한 칸을 남긴 채 안전망이 건너뛰기만 하면 그 잡은 영영 집히지 않는다. 사람의 재개는 칸을 걷으므로 줄에 선 잡에
  남은 칸은 자동 길(복구가 옮기다 실패한 것)의 것이다.
- 끊긴 대상(복구가 패널을 닫은 대상)의 잡은 종전대로 restart 멈춤에 그 까닭을 붙인다(CC-21) — 미룬 실패도 restart 멈춤이 되어 재개할 수 있고, 글이
  그 실패를 말한다.

### CC-30. 자격 실패가 연속 실패보다 먼저 선다(R2-3 — 동시 1 잡도)
- 재현 — 엔진 실패 둘 뒤 셋째 패널의 PatUnavailable — `_close_panel_error` 가 그 패널을 차감으로 닫으며 연속 실패를 세어 잡을
  failed/engine_fail_streak 로 끝냈고, 뒤의 자격 실패 `_stop_job` 은 잡이 running 이 아니라 건너뛰었다. 2229b32 까지는 뒤에 쓴
  failed/pat_unavailable 이 덮었다(무조건 쓰기).
- 고침 — 잡을 먼저 failed/pat_unavailable 로 옮기고(곧바로 — 형제도 닫힌다) 패널을 닫는다. 패널의 차감 · 연속 실패 셈은 종전 그대로다(그 뒤의
  연속 실패 전이는 잡이 running 이 아니라 서지 않는다). 그 사이 사람이 취소한 잡은 덮지 않는다(CC-20 그대로).

### CC-31. 잡 마감은 running 일 때만 — 후속 · 사슬도(R2-4 — 종전부터, F8 계열)
- 재현 — 집은 뒤 편성 전에 사람이 취소했고 남은 좌석이 없으면 `_finish_job` 이 상태를 보지 않고 completed 를 써 그 취소(cancelling)를 덮고 C3
  자동 후속 Tier C 를 세웠다(쟁점 잡은 사슬의 종합 잡을 이었다).
- 고침 — `_finish_job(expect=)` — 편성기가 'running' 을 주고, 못 쓰면 후속 · 사슬 없이 그때 상태를 돌려준다(취소는 다음 집기가 cancelled 로
  마감한다). 시험이 행 상태를 맞추지 않고 후속만 보려고 부르는 직접 호출(다른 시험 파일 다섯)은 주지 않아 종전 그대로다.

### CC-32. 사람의 조작이 미뤄 둔 멈춤을 걷는다 — 까닭은 남기고 진행판에는 싣지 않는다(R2-6)
- 사람의 정지(REST · MCP 잡 제어)와 엔진 쪽 멈춤(A24)은 칸을 걷고 그 까닭을 잡 error 에 남긴다 — '앞서 미룬 실패|멈춤 — <까닭>'
  (`_earlier_note` — 정지는 그 글만, A24 는 멈춤 글 끝에 ' · ' 로). 사람의 뜻이 이기되(멈춤 — 재개할 수 있다) 미뤄 둔 실패가 소리 없이 재개되지
  않는다. 종전에는 정지가 error 를 NULL 로 덮었고 칸은 남았다가 마지막 형제의 끝에서 쓰이지 않은 채 걷혔다.
- 사람의 취소도 칸을 걷는다(형제가 닫히는 동안 · 마감 뒤 진행판에 남지 않게). 재개는 종전대로 걷는다.
- 진행판(`coverage_payload`)의 signal · signals 와 과제 상세 잡 목록의 progress 에서 그 칸을 뺀다 — 종전에는 신호 칸을 통째로 펴
  {state, by, reason, error, panel_id, at} 가 실렸다. 까닭은 잡 error 가 말한다.
- 감사 행은 종전대로 사람의 조작 한 번에 한 행이다(칸을 걷는 것은 잡 상태 · 보류 코드를 바꾸지 않는다).

### CC-33. 동시 실행 범위 — MCP 스키마 · 검토 잡의 까닭 · 0 과 음수(R2-7)
- MCP risk_start_job 의 concurrency 스키마가 minimum 1 · maximum 2 를 싣는다(인자 계약 고정본 `tests/fixtures/mcp_arg_contract.json` 의 그 칸도
  고쳤다 — 일부러 바꾼 인자다).
- 검사는 REST 와 같은 본문(JobBody)의 모드 검사가 한다. 칸에 ge · le 를 걸면(c4bdfa7) 검토 잡(mode=reviews)에 준 3 이 '패널 잡의 칸이다' 보다
  pydantic 의 일반 글('Input should be less than or equal to 2')로 먼저 졌다. 그래서 JobBody 칸과 MCP 칸은 스키마 범위만 싣고(json_schema_extra)
  패널 잡의 1 ~ 2 는 모드 검사의 한국어 까닭이다('concurrency 는 1 ~ 2 다 — …'). MCP 칸에 ge · le 를 걸지 않은 것도 같은 까닭이다(FastMCP 의 칸
  검증은 일반 글이다).
- MCP 입구(`entry.start_job`)는 살아 있는 잡을 돌려주는 갈래 앞에서도 범위를 본다 — 스키마가 범위를 싣는데 그 갈래만 3 을 받아 살아 있는 잡을
  돌려주지 않게. 범위 안의 다른 값은 종전대로 differs 없이 돌려준다(CC-15 · checklist 의 남은 줄 — 결정 필요).
- 0 · 음수도 이제 422 다 — 칸이 아무 일도 안 하던 동안(3a188f3)은 받아 저장했다. 그렇게 저장된 옛 행은 `job_slots` 가 1 로 읽는다(`max(1, …)`).

### CC-34. 닫힌 차례 셈이 동시 1 잡에서도 바꾸는 판정(R2-5 — CC-23 고침)
- CC-23 은 '한 줄로 도는 동시 1 잡은 번호 차례와 닫힌 차례가 같다' 고 적었다. 러너 패널끼리는 맞지만 같은 대상에 MCP 길 패널이 섞이면 다르다 —
  그 패널은 브리프를 편성할 때 번호를 받고(planned · ended_at 없음) 결과를 제출할 때 닫힌다.
- 수확 체감(`_diminishing` — done 인 coverage 패널 최근 셋) — 일찍 편성하고 늦게 제출한 MCP 패널 #2(new_clusters 2)가 러너 패널 #3 · #4 · #5(셋 다
  0) 뒤에 닫히면, 번호 차례는 #5 · #4 · #3 이라 참(잡을 멈춘다)이었고 닫힌 차례는 #2 · #5 · #4 라 거짓(멈추지 않는다)이다.
- 연속 실패(`_error_streak` — running 이 아닌 패널을 최근부터) — 버려진 MCP 브리프는 planned 로 남고 ended_at 이 비어 있다. #1 엔진 실패 · #2
  버려진 브리프 · #3 · #4 엔진 실패에서 번호 차례는 #4 · #3 다음 #2(planned)에서 끊겨 2(잡이 산다)였고, 닫힌 차례는 ended_at 이 빈 행을 맨 뒤로
  보내 #4 · #3 · #1 — 3(failed/engine_fail_streak)이다. 브리프 재시도 셈(done · error 만)은 늦게 제출한 MCP 패널에서 끊긴다(번호 차례로는
  이어졌다).
- 그대로 둔다 — 세 셈 모두 '최근에 닫힌 것' 을 보려는 규칙이고, 버려진 브리프는 엔진이 도는 증거가 아니다. 동시 1 잡에서 달라진 것 목록(CC-24)에
  더했다.

### CC-35. 남는 틈 둘(R2-8 — 고치지 않고 적는다)
- 집기의 안전망(러너가 그 잡의 패널을 다 놓았는데 남은 미뤄 둔 멈춤을 옮긴다)은 틱이 전역 자리(세마포어)를 얻을 때만 돈다 — 전역 자리가 다 찬
  동안은 남은 칸이 있는 잡이 패널 없이 running 으로 남는다(진행판은 미뤄 둔 글을 보인다). 자리가 난 틱의 집기가 앞 차례의 잡을 집지 않고 그
  잡에 닿을 때 옮긴다.
- 좀비 running 패널(워커는 끝났는데 패널 행이 running 에 남은 것 — 러너 밖에서 그 행을 닫는 길은 재기동 복구다)이 있으면 동시 2 잡은 그 형제가
  끝나기를 기다리며 미뤄 둔 글과 함께 running 에 남는다 — 재기동 복구가 그 패널을 닫으면 그 대상은 끊긴 대상이라 restart 멈춤에 미뤄 둔 까닭이 붙는다
  (CC-21). 그 전에는 사람이 멈추면(CC-32) 칸이 걷히고 까닭이 남는다.

### CC-36. 시험 · 변이
- 새 시험 16 항목(함수 14) — R2-1(자리 대기 · 미뤄 둔 동안의 글 셋) · R2-2(복구 · 옮겨야 걷음 — 줄에 선 잡 · 사람이 멈춘 잡) · R2-3 · R2-4(C3
  후속 · 쟁점 사슬) · R2-6(사람의 정지 · A24 · 취소 · 진행판과 과제 잡 목록) · R2-7(스키마 · 검토 잡 까닭 · 0 과 음수 · MCP 입구의 살아 있는 잡
  갈래) · N31 고정(셋째 도는 패널을 편성기로 세워 '미룬 실패를 나중의 미룬 멈춤이 덮지 않는다' 를 직접 묶는다 — 1차의 같은 판 변이가 이제 잡힌다).
- 고치기 전(c4bdfa7 사본) — 16 가운데 15 가 진다(N31 고정은 규칙을 묶는 시험이라 같다).
- 시험 대역의 구멍 — `_InFlight` 의 during(엔진 호출 도중에 부르는 형제 일) 안의 단언이 러너의 `except Exception`(엔진 실패로 읽고 패널만
  닫는다)에 삼켜졌다. 바깥 단언이 최종 상태만 보면 시험이 통과했다(이번 '미뤄 둔 동안의 글' 시험이 고치기 전 사본에서 통과해 찾았다). 이제
  during 안의 실패는 `_DuringFailed`(BaseException)로 올라온다. 1차 시험 48 은 그대로 다 통과했다 — 가려진 실패는 없었다.
- 변이(스크래치 사본 · 바이트코드 끔) 24 가운데 24 — 이번 고침 23 과 1차에서 같은 판으로 남은 N31. 사본과 작업 트리는 diff 0(__pycache__ 밖),
  사본에 __pycache__ 없음.
- 관련 시험 532 통과(패널 동시 · 러너 패널 · 쟁점 패널 · 검토 라우트 · 인자 계약 · Claude 패널 잡 · 대상 방식 · 브리프 빼기 · MCP 쓰기 신원 · 배선
  회귀 · 외부 LLM 잡 · 사람 조작 감사 · 감사 이름표 · MCP 입구 · MCP 도구 · 과제 읽기 · 화면 읽기 · 사슬 · 패널 원장).
- 리스크 전체 시험(공유 잠금 아래 한 번, e91db9b) — 3,853 통과 · xfail 4 · 실패 0(rc 0, 13분 15초 — 앞 판 3,837 에 새 16).

### CC-37. 남긴 것
- CC-27 의 줄 그대로(포털 cae00 절차서의 CC-25 줄 · 쟁점 잡의 편성 경합 · MCP 살아 있는 잡의 concurrency — 범위 밖의 값만 이번에 막았다).
- 화면은 고치지 않았다 — 진행판 신호 칸에서 빠진 것은 화면이 읽지 않던 칸이다.

## 남은 일 다섯 11-01(가지 `wt1101/risk-open`, main 2460cd0 위, 2026-11-01)

> 사용자 승인 11-01 — 조정자가 넘긴 다섯 줄이다. ① 생산자 diff_json 과 `rr_diff.v1` 계약(우선 — MB-17 남긴 것) ② 보기에게 보이는 쓰기
> 단추(MB-8 · MB-14 의 화면 몫) ③ `risk_next_step` 을 구성원에게(MB-4 · MB-19) ④ MCP 입구가 돌려주는 살아 있는 잡의 동시 실행(CC-15 ·
> CC-33 남긴 것) ⑤ 관리자 읽기 우회(MB-1 남긴 것 — 계획서가 그렇게 적었을 때만). 줄마다 커밋 하나이고 번호는 줄 번호와 같다(OI-1 = ①).
> 고친 동작마다 고치기 전 코드의 스크래치 사본에서 지는 시험을 먼저 보고, 변이는 스크래치 사본에서만 걸었다.

### OI-1. 생산자 diff 본문과 `rr_diff.v1` — 계약을 생산자 쪽으로 고쳤다(사용자 결정 11-01 · MB-17 남긴 것)
- 정본 — 앱 docs/plan.md 는 포털 plan 을 계약 정본으로 가리키고 `rr_diff.v1.json` 을 그 §3 의 옮김으로 적는다. 포털 plan §3.3.1 봉투에는
  pair_kind 가 없다(열은 §5.2.2 rr_diffs.pair_kind, RA design_diff 칸은 §5.3.3). §3.3.2 의 cid 열쇠는 노드 dn · 명명 치수 `dim:<name>` · 롤업
  `asm:<asm_key>` · 결과 `dn|metric` 이고, §3.3.5 사건 레코드의 subject.dns 는 노드 예만 보인다. §3.3.6 제외 사유는 13종이다(source_drift ·
  capture_partial 포함). 계약 파일은 P0 비계(4cf8ed5)에서 정본의 예를 옮겨 적은 것이고 생산자가 자라며(소스 5키 · 롤업 · 결과) 어긋났다.
- 탐침 — 시험 전체(2460cd0 스크래치 사본 · 4,040 통과)에서 `diff.compute_diff` 산출 1,077 개를 계약으로 검증했다(감싼 플러그인 · 원장은
  그대로). 갈래 — 최상위 pair_kind(1,077 전부) · 사건 주체 열쇠(asm: 4,585 · [dn, metric] 2,364 · dim: 1,509 + 770 · contact#<n> 1,502) · 제외
  사유 capture_partial(파라메트릭 323 · 구조 엣지 2) · 의미층 차단 capture_partial 4 · rule_version null 111 · diff_id 빈 글 110 · 결과
  kind 'drop' 9. MB-17 의 '15건' 은 syn40 기본 씨앗 하나의 것이다(pair_kind 1 · 노드 아닌 주체 열쇠 14).
- 판정 — 생산자를 고친 곳은 없다(본문 바이트째 그대로).
  - pair_kind — rr_diffs.pair_kind 열의 사본이고 비교 화면 '짝' 칸이 본문(`doc.pair_kind`)에서 읽는다. 생산자에서 빼면 화면이 다른 과제
    비교를 '같은 과제 리비전' 으로 보이고, 저장된 본문(dev · cae00)에는 이미 있다 — 계약에 넣고 필수로 했다(생산자가 늘 싣는다).
  - 주체 열쇠 — 생산자는 cid 의 key_a · key_b(§3.3.2)를 subject.dns 에 싣는다. 노드만 싣게 고치면 cid 는 지킬 수 있지만 저장된 본문은
    옛 꼴이라 계약이 두 꼴을 다 받아야 하고, 소비처(브리프 이름 후보 · ECAD caveat · 화면 ECAD 판정)는 노드가 아닌 열쇠에도 그대로 돈다 —
    계약이 code 마다 꼴을 묶는다(아래 4). 합집합 하나로 넓히면 부품 사건에 asm: 가 와도 지나가 종전의 노드 검사를 잃는다.
  - 제외 사유 · 의미층 차단 — 정본 §3.3.6 그대로다. 생산자의 어휘 상수 `diff.EXCLUDED_REASONS`(쓰는 곳 없는 기록)에도 둘을 더했다 — 화면
    `compareView.EXCLUDED_LABEL` 은 이미 13종이었다. blocked_by capture_partial 은 capture_parity 거짓의 '의미 이벤트 미생성' 을 생산자가
    적는 자리다(검토 단위 표 blocked_by 열 주석도 'G2' · 'capture_partial').
  - 계약 밖에 둔 셋 — rule_version null(상태 행 없이 손으로 심은 스냅샷 — test_diff 의 create_diff 시험 하나), diff_id 빈 글(생산자 함수를
    직접 부른 단위 시험 — create_diff 는 늘 id 를 준다), 결과 kind 'drop'(rr_ir 밖의 손 IR 을 먹인 시험 — rr_ir 도 deep · sphere · impact
    만 받는다). 운영 경로(동결 → 상태 → create_diff)는 내지 않는다.
- 계약이 바뀐 것(정확히) —
  1. 최상위 `pair_kind` — `{"type": "string", "enum": ["same_project_revision", "cross_project"]}`, `required` 에 든다.
  2. `semantic.blocked_by` — enum `["G2", "capture_partial", null]`(capture_partial 이 더해졌다).
  3. `definitions.excluded_reason` — enum 에 `source_drift` · `capture_partial` 을 더해 13종 + null(차례는 정본 §3.3.6).
  4. `definitions.event` — `subject.dns.items` 를 nid 에서 string 으로 풀고 `allOf` 다섯이 code 마다 묶는다 — asm.rollup_changed →
     `^asm:.+` · dim.named_changed · dim.named_unmeasured → `^dim:.+` · contact.scope_changed → `^contact#[0-9]+$` · result.part_metric_shift →
     `[nid, result_metric]`(둘 — `additionalItems: false`) · 그 밖의 code → nid(종전 그대로).
  5. 새 definitions 넷 — `result_metric`(result_item.metric 과 같은 넷 — 시험이 같음을 본다) · `dim_key` · `asm_key_ref` · `contact_scope_key`.
  손 픽스처 넷(valid 둘 · invalid 둘)에 pair_kind 를 넣었다 — 무효 픽스처가 제 까닭으로만 거부되게.
- 소비처 — 본문이 바뀌지 않았다. REST GET /diffs/{id}?part=diff 와 MCP risk_get_diff(part='diff') 는 같은 함수(routes.diff_part →
  diff.get_diff)로 저장된 본문을 그대로 내고(lines · events · summary 는 열 · 펼침 표를 읽는다), 등록부 · 서술(narrative 의 대상 맥락) ·
  단위 · 브리프 · 러너는 열(pair_kind · summary_text · comparability_json) 또는 본문의 층을 읽어 바뀐 곳이 없다. 화면 타입(DiffDoc)은
  pair_kind · `subject.dns: string[]` 로 이미 맞다 — 실제 생산자 본문 견본(serverSamples `diffDocSyn40` — 층마다 앞 항목 하나 · 사건은 주체
  열쇠 꼴마다 하나)을 더해 tsc 가 타입과 견주고 views 시험이 그 사건 줄(이름 · ECAD 아님)을 그린다.
- 시험 — 새 tests/test_diff_contract.py 20(생산자 본문 여섯 — syn40 씨앗 셋 · 다른 과제 쌍(G2) · 뒤 캡처가 부분인 쌍(어댑터가 싣는 scope) ·
  소스 꼴이 바뀐 쌍(schema_drift) — 오류 0 · 넓힌 자리를 다 지나는가 · MCP 본문 · 제외 어휘가 생산자 상수와 하나 · 계약이 여전히 거절하는
  것 열하나). 구성원 시험의 남이 적어 넣은 비교 행 사본은 이제 검증을 지난다(`validate=False` 와 그 까닭 글을 걷었다). 고치기 전 코드(2460cd0
  사본)에서 9 가 진다(본문 여섯 — 옛 계약 오류 syn40 15 · 16 · 14 · 다른 과제 1 · 부분 59 · 꼴 바뀜 52, MCP 본문, 어휘, 구성원 시험) — 11 은
  지킴(넓힌 자리 도달 · 거절 열). 변이 16/16(pair_kind 칸 · 필수 · 어휘, 차단 capture_partial · 어휘, 제외 둘 · 어휘, 롤업 · 치수 · 접촉
  범위 · 결과 꼴, 노드 사건의 else, 결과 셋째 열쇠, 생산자 어휘 상수, 결과 지표 어휘). 관련 시험 15 파일 542 통과 · xfail 2, 화면 tsc ·
  pnpm test 109 통과.
- 포털 정본 문면(포털 세션 몫) — plan §3.3.1 봉투에 pair_kind 를, §3.3.5 사건 레코드에 subject.dns 의 꼴(노드가 아닌 열쇠 넷)을 적는다.

### OI-2. 쓰기 단추를 서버의 역할로 가른다 — 보기에게 잠그고 까닭 한 줄(사용자 결정 11-01 · MB-8 · MB-14 화면 몫)
- 무엇이 거슬렸나 — 구성원 읽기(MB-1)와 편집자 쓰기(MB-14) 뒤로 보기도 과제 · 대상 화면을 다 여는데 쓰기 단추는 역할로 가르지 않아 누르면
  403 배너였다. 대상 화면은 부른 사람의 역할을 몰랐다(응답에 칸이 없었다).
- 서버(칸만 더함) — 과제 상세(`GET /projects/{id}`)와 웹 진행판(`GET /targets/{key}/coverage` 라우트 — MCP risk_get_coverage 의 본체
  coverage_payload 는 그대로)에 `my_role`(project_role — owner 는 과제 행의 주인 열, 구성원은 편집자 · 보기 행, 구성원이 아닌 관리자는 null —
  과제 목록 카드의 my_role 과 같은 판정), `GET /me` 에 `risk_admin`(risk_admin_roles — 사전 편집을 미리 가른다, 익명은 false). 대상 화면은
  진행판을 이미 받으므로 따로 부르지 않는다. 구성원 읽기 표의 '부른 사람에 매인 칸'(CALLER_FIELDS)에 둘을 더했다.
- 화면 — `lib/access.ts` 의 판정 하나(`writeAccess(role, need)` — 보기는 편집자 쓰기를, 소유자가 아니면 주인 쓰기를 잠그고 까닭의 글을 낸다.
  역할을 모르면(null · 칸 없음 — 구성원이 아닌 관리자 포함) 잠그지 않는다 — 서버가 가른다)와 `LockNote`(잠겼을 때만 자물쇠 한 줄 — 단추의
  title 에도 같은 글). 까닭 글 — 보기 '보기 권한이라 바꿀 수 없습니다 — 과제 소유자 · 편집자만 합니다.', 주인 쓰기 '과제 소유자만 할 수
  있습니다(지금 편집자).', 사전 '관리자(risk_admin_roles)만 할 수 있습니다.'.
- 가른 단추(편집자 이상) — 과제: 소스 연결 · 동결(그래도 동결 포함) · 요구 저장 · 확정 · waive · 승계 · dims · 계면 원장(행 추가 · 저장) ·
  메타(등급 · 수명 주기 · 코퍼스 — 종전 잠금에 까닭 줄). 스냅샷: ack · 확인 취소 · 타깃 만들기. 비교: diff 생성 · 쌍 대응 결정(확정 · 거부 ·
  일괄 수용 — 두 과제의 약한 역할, `weakerRole`) · 타깃 만들기(비교 본문의 과제). 대상: 로스터 갱신 · 좌석 넘기기 · 되돌리기 · 보류 풀기 ·
  패널 잡 시작 · 일시정지 · 재개 · 취소 · 검토 잡 시작 · 검토 잡 줄의 조작(일시정지 · 재개 · 동의하고 재개 · 취소 · 넘기기) · 사슬 재개 ·
  사슬 시작 · 셀 다시 · 넘김 · 쟁점 올리기 · 건너뛰기 · 등록부 상태 · 판정 확정 · 사람 리스크 등록 · 보고서 다시 내기 · 요약부터 다시 ·
  브리프 탭(브리프는 편성 · 토큰을 내는 쓰기라 보기에게는 부르지 않고 까닭을 보인다 — 종전 403 배너). 주인만 — 재동기 · 완결 잔여 확인 ·
  확인 취소 · confidential → internal 낮추기(`lowerClassificationLock` — 편집자가 고르면 '바꾸기' 를 잠근다) · 조직 공개(종전 잠금 그대로) ·
  멤버 · 이양 · 폐기 · ECAD 보드(종전 isOwner 그대로). 관리자만 — 사전 편집(/me.risk_admin). 읽기 단추(새로 읽기 · 다시 세기 · 거름 ·
  탭 · 발언 보기)는 그대로다.
- 역할의 출처 — 과제 화면은 과제 상세의 my_role(그 칸이 없는 서버면 멤버 표로 센 종전 값), 대상 화면 · 대상 머리(CellsHead) · 좌석 표는
  진행판의 my_role, 스냅샷 화면은 과제 화면 안이면 그 값 · 딥링크로 홀로 열면 그 과제 상세를 받아 센다, 비교 화면은 과제 목록 카드의
  my_role(두 과제의 약한 쪽 · 비교 본문의 과제). 폴링 전(첫 응답 전)에는 모름이라 잠그지 않는다 — 서버의 거절은 그대로다.
- 받아들인 것 — 구성원이기도 한 관리자(보기 행)는 my_role 이 viewer 라 화면이 잠그지만 서버는 관리자 우회로 받는다(드문 경우 — 그 사람은
  멤버 행을 빼면 된다). 구성원이 아닌 관리자는 null 이라 잠기지 않고, 관리자도 막히는 주인 쓰기(ECAD 보드 · 등록부 공개 토글)는 종전처럼
  서버가 404 로 막는다.
- 시험 — 백엔드: test_member_reads 새 하나(과제 상세 · 진행판 my_role — 주인 · 편집자 · 보기 · 관리자 null · 남 404), test_me(/me 칸 ·
  risk_admin 거짓 · 역할 목록을 바꾸면 참). 고치기 전 코드(70a0d5a 사본)에서 넷 진다. 변이 5/5(상세 역할 없음 · 늘 owner · 진행판 역할 없음 ·
  관리자 칸 늘 거짓 · 익명도 참). 화면: 새 tests/roles.test.cjs 9(판정 표 · 게이트 ack · 검토 잡 줄 · 대상 머리 · 등록부와 사람 리스크 ·
  보류 풀기와 검토 잡 시작 · 완결 확인(주인만) · 보고서 · 셀 · 쟁점 · 대응 · 과제 메타 — 보기 · 편집자 · 소유자로 그려 잠김 · 까닭을 본다),
  시험 컴파일 목록에 카드 일곱과 판정 · 까닭 줄. 고치기 전 화면(70a0d5a 사본에 새 판정 · 까닭 줄만 얹음)에서 9 가운데 8 이 진다(판정 표는
  새 파일이라 같다). 변이 20/20(판정 다섯 · 카드마다 단추나 까닭 줄 · 역할 안 넘김 · 까닭 줄 그리지 않음). 견본 둘(과제 상세 편집자 ·
  진행판 주인)에 my_role 을 더했다. tsc · pnpm test 118 · vite build 통과.
- 시험 밖 — 화면 넷(과제 · 대상 · 비교 · 스냅샷)의 배선(역할을 읽어 카드에 넘기는 줄)과 화면 안 카드(소스 · 동결 · 요구 · dims · 계면 원장 ·
  사전 · 좌석 표 · 패널 실행 · 브리프)는 시험 하네스가 화면을 엮지 않아(쪽 파일은 시험 컴파일 목록 밖) tsc · 빌드로만 보았다. 브라우저로
  보기 · 편집자 · 소유자 화면을 열어 보지 않았다.

### OI-3. `risk_next_step` — 구성원에게 읽기 문으로, 쓰기 걸음은 편집자 규칙으로(사용자 결정 11-01 · MB-4 · MB-19 남긴 것)
- 무엇을 하나 — `entry.next_step` 은 쓰지 않는다(문서 그대로 읽기 전용). 단계마다 원장을 읽어(소스 · 동결 · 스냅샷 · 비교 · 대상 · 진행판 ·
  잡) where · blocked · next · facts 를 짓는다. 편성 · 토큰 같은 쓰기는 없고 다음에 부를 도구를 걸음(next)으로 싣는데 그 가운데 쓰기(write)
  걸음이 있다. 그래서 문은 읽기 문이고 걸음이 편집자 규칙을 따른다.
- 고침 — 과제는 웹 구성원 읽기와 같은 문(`routes._project_reader` — 구성원이면 과제 주인, 아니면 부른 사람)으로 고르고, 이후의 원장
  조회(대상 · 비교 · 진행판 · 계보 과제)는 그 과제 주인으로 한다. 남은 종전대로 없는 과제와 같은 E404 다(남 숨김). 답의
  `project.my_role` 이 부른 사람의 역할이다. 보기에게는 쓰기 걸음을 빼고 `role_insufficient` 막힘 하나(그 걸음의 도구 · 고칠 곳 —
  편집자 권한을 청하거나 주인 · 편집자에게 부탁)를 싣는다 — 조용히 빼지 않는다. 편집자는 주인과 같은 걸음이다(길잡이가 싣는 쓰기 도구는
  다 편집자에게 열렸다 — MB-14, 주인만의 쓰기 도구 risk_set_ecad_board 는 걸음으로 싣지 않는다).
- 과제 없이 부르면 소유 ∪ 구성원(편집자 · 보기 행) 과제 목록이고 카드마다 `my_role` 이다(웹 과제 목록과 같은 범위 — 조직 공개만으로는
  들지 않는다). MCP 신원은 역할을 떼므로 관리자 우회는 없다(SEC-2 그대로).
- 자격 칸(`_credentials`) — 등록 · 캡처 채널은 부른 사람의 등록이고(동결은 시작한 사람의 PAT 로 읽는다 — MB-14), 러너는 요청자(부른 사람)
  → 잡 주인(과제 주인), 명단은 대상 주인(과제 주인)의 것이다. 주인이 부르면 종전과 같다(둘이 같은 사람).
- 계보 과제(앞 리비전) — 과제 주인의 것이어야 하고(비교는 두 스냅샷의 주인이 같다 — pair_owners_differ), 구성원은 그 과제도 읽어야 한다
  (대응표 · 비교는 두 과제를 다 읽는 사람이 연다 — MB-2). 못 읽으면 그 과제의 스냅샷을 싣지 않고 노트로 까닭을 말한다 — 실으면 앞 과제의
  스냅샷 id 가 새고 대응표 조회가 E404 로 끊긴다.
- 함께 고친 것 — 길잡이의 스냅샷 · 동결 잡은 과제 주인의 행만이다(과제 상세 · 구성원 읽기와 같은 거름). 종전에는 과제 id 로만 골라 남이
  주인의 과제에 매단 스냅샷(RD-10)이 같은 초면 최신으로 서고, 주인의 길잡이가 대응표 조회에서 E404 로 끊겼다(시험이 재현한다 — 주인도
  고치기 전에 진다). 구성원에게 열면서 그 행이 구성원에게도 보이게 되는 것을 막는다.
- 시험 — test_member_reads 의 길잡이 다섯(세 단계를 주인 · 편집자 · 보기로 — 같은 단계 · 사실 · 편집자는 같은 걸음 · 보기는 쓰기 걸음 대신
  막힘 하나 / 목록과 남 / 부른 사람의 등록 · 러너 순서 / 못 읽는 계보 과제 / 남이 매단 스냅샷 · 동결 잡). MCP 표의 risk_next_step 면제
  까닭을 '구성원에게 열지만 답이 부른 사람에게 매인다' 로 고쳤다. 고치기 전 코드(7ddf822 사본)에서 다섯 다 진다(구성원 E404 · my_role 없음 ·
  facts 없음 · 남이 매단 스냅샷이 목록에 서고 주인의 길잡이가 E404). 변이 13/13(구성원 길 · 보기 거름 · 막힘 · 쓰기 걸음 · 역할 · 자격 행 ·
  러너 요청자 · 계보 읽기 · 스냅샷 거름 · 동결 잡 거름 · 목록 구성원 · 목록 역할 · 목록 보기 행). 관련 시험 14 파일 568 통과.

### OI-4. MCP 입구가 돌려주는 살아 있는 잡 — 도는 자리 수를 싣고 다르면 differs(사용자 결정 11-01)
- 무엇이 비었나 — `entry.start_job` 은 같은 대상 · 같은 Tier 의 살아 있는 패널 잡을 돌려줄 때 그 잡의 concurrency 를 싣지 않았고, 범위 안의
  다른 값(1 ↔ 2)을 청해도 differs 가 비었다(CC-15 · CC-33 — 범위 밖 값만 422 로 막았다). 부른 쪽은 청한 동시 실행이 받아들여졌다고 읽는다.
- 고침 — 답에 `concurrency` 를 싣는다. 값은 저장 열(`rr_jobs.concurrency`)이 아니라 그 잡이 실제로 도는 자리 수(`runner.job_slots` — 러너가
  집을 때 읽는 값, 박스의 전역 자리로 다시 묶고 claude 잡은 1)다 — 저장 열을 실으면 그 손잡이를 낮춘 박스 · 2 로 저장된 옛 Claude 잡에서 도는
  것과 다른 수를 말한다. 청한 값은 새 잡이 받을 자리 수(같은 `job_slots` 로 죈 값)로 견주고 다르면 differs 에 'concurrency' 다(바꾸지 않는다 —
  취소한 뒤 새로, llm · exclude_evidence 칸과 같은 규칙). 판단 LLM 을 주지 않은 호출은 살아 있는 잡의 판단 LLM 으로 견준다(llm 칸도 준
  것만 견준다 — 주지 않은 llm 을 GLM 으로 읽으면 Claude 잡마다 concurrency 가 다르다고 나온다).
- 같은 자리 수로 죄여 다르지 않은데 청한 값보다 적게 돌면 잡 만들기 답과 같은 `concurrency_note` 를 싣는다(말없이 죄지 않는다 — CC-5, 박스
  글은 HWAXRISK_CONCURRENCY 값을, Claude 잡은 CLAUDE_CONCURRENCY_NOTE). MCP 인자 설명(_A_CONCURRENCY)과 도구 설명에 같은 뜻을 적었다.
- MCP concurrency 기본값은 1 그대로다 — 값을 빼고 부른 호출도 1 을 청한 것이라 동시 2 로 도는 살아 있는 잡이면 differs 에 든다(인자 계약
  고정본은 바꾸지 않았다). 검토 잡(mode=reviews)은 이 칸이 없다(JobBody 가 1 밖을 422 로 받는다 — 그대로).
- 시험 — test_panel_concurrency 의 새 하나(같은 값 · 기본 1 · 박스 전역 1 의 까닭 · Claude 잡의 까닭 · llm 과 함께 다름). 고치기 전 코드
  (2460cd0 사본)에서 진다(KeyError 'concurrency'). 변이 6/6(differs 끔 · 저장 값 · 주지 않은 llm 을 GLM 으로 · 까닭 끔 · Claude 글 대신 박스
  글 · 청한 값 그대로 견줌). 관련 파일 아홉(MCP 입구 · 도구 · 인자 설명 · 동시 실행 · Claude 패널 잡 · 외부 LLM 잡 · 브리프 빼기 · 검토
  MCP · 쓰기 신원) 275 통과.

### OI-5. 관리자 읽기 우회 — 계획서가 그렇게 적었다(사용자 결정 11-01 조건부 · MB-1 · MB-19 남긴 것)
- 계획서 문면(포털 docs/design-risk-review/plan.md) — §0.6 표 '과제 접근·역할': "조회는 `owner_sub` 일치 OR `rr_project_members` 행 OR
  `visibility='org'`. 역할 `owner`(전권·이양·폐기) ⊃ `editor`(스냅샷·타깃·잡·status·사람 finding) ⊃ `viewer`(읽기). `identity.role ∈
  risk_admin_roles` 는 전 과제에 대해 `editor` 로 취급하고 폐기·이양은 owner 와 동등하다." §5.2.1 표 '멤버십': "`identity.role ∈
  risk_admin_roles` 는 멤버 행 없이 editor 로 통과하며 그 접근도 `rr_audit` 에 남는다." 역할이 포함 관계(editor ⊃ viewer(읽기))라 관리자는
  전 과제를 읽는다 — 조건이 섰다. 계획서의 관리자는 앱의 `risk_admin_roles`(heax 역할, 기본 admin)다 — 포털의 CAEG 그룹이 아니다(그 그룹이
  heax admin 역할인지는 앱이 모른다).
- 고침(웹만) — 읽기 문 `_reader`(와 `_project_reader` · `_snapshot_reader` · `_target_reader` · `_panel_reader`) · `_diff_reader` 에 `admin`
  인자를 두고 웹 읽기 라우트가 `_is_admin(ident)` 를 넘긴다 — 관리자는 구성원 검사를 건너뛰고 구성원처럼 그 과제 주인의 행을 읽는다(주인과
  같은 답). 쓰기 문 `_writer` 의 관리자 우회와 같은 꼴이다. 함께 — 과제 상세(require_role 대신 — 없는 과제는 404), 키 대장(전 과제의
  별칭 · mine 은 false), 유사 · 선례(다른 과제를 관리자의 소유 ∪ 구성원으로 좁히지 않고 주인의 답), 원장 참조(reg · narr · tool 행의 구성원
  판정 · req · voc · paper 의 '구성원인 과제' 를 전 과제로), 대상(diff) 만들기의 '그 비교를 읽나' 판정(종전에는 읽기 판정이 관리자를 몰라
  쓰기 문의 관리자 우회까지 닿지 못하고 404 였다 — 관리자는 계획서대로 편집자다).
- 넓히지 않은 것 — 발견 목록 넷(과제 · 대상 · 비교 · 보고서)은 소유 ∪ 구성원 그대로다(관리자 홈에 박스의 모든 과제가 서는 것은 따로
  정할 일이다 — 관리자는 링크 · id 로 연다). 행 주인 대조는 그대로라 남이 매단 행(RD-10)은 관리자에게도 닫히고, 과제에 매이지 않은 원장
  행(스냅샷 · 동결 잡이 없는 호출 원문)은 그 행의 주인만 연다. MCP 길에는 관리자가 없다(mcp_identity 가 역할을 뗀다 — SEC-2 그대로).
- 남는 어긋남(결정 필요) — §5.2.1 의 "그 접근도 rr_audit 에 남는다" 는 쓰기 우회에도 읽기 우회에도 없다(관리자의 쓰기는 라우트가 남기는
  감사 행의 행위자로만 남는다). 읽기마다 감사 행을 쓰면 진행판의 5초 폴링이 이력 탭을 채운다 — 하루 한 행 같은 접기는 계획에 없는 설계라
  넣지 않았다.
- 시험 — 가짜 신원 셋(test_wiring_regressions 셋 · test_gate_ack)에 role 칸을 더했다(진짜 Identity 에 늘 있다 — 읽기 문이 이제 관리자 우회를
  읽는다, MB-14 의 같은 고침). test_member_reads 의 관리자 읽기 표(남 시험 표의 읽기 경로 − 브리프 · 발견 목록 셋 — 구성원이 아닌 관리자가
  주인과 같은 답) · 대상(diff) 만들기 · 넓히지 않은 것(목록 · 남이 매단 행 · 과제 없는 원장 행 · MCP), 스코프 참조 · req · voc · paper 시험에
  관리자, test_review1_stranger_recall 의 관리자 유사 · 선례(주인의 답). 고치기 전 코드(0f64c21 사본)에서 30 이 진다(관리자 읽기 26 ·
  스코프 참조 · req · voc · paper · 대상 만들기 · 유사 선례) — 5 는 지킴(이미 열린 멤버 · 이력 · 대상 감사 · 넓히지 않은 것). 변이
  15/15(처음 판에서 '과제 모르는 행도 관리자에게' 가 살아남아 과제 없는 원장 행 시험을 더해 잡았다). 관련 시험(rr 전부 · 과제 읽기 ·
  p6 라우트 · 대응 · 완결 · 과제 메타 · MCP 쓰기 신원 · 도구 · 입구 · 브리프 · 배선 회귀) 967 통과 — 처음 돌림의 실패 하나가 role 없는 가짜
  신원이었다.
