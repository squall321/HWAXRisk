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
