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
