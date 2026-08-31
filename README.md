# HWAXRisk

설계 리스크 심사 앱(HEAX 앱 id `hwax_risk`, 표시명 **HWAX Risk Review**).

과제의 MCAD(StepForge)·Dyna(DynaForge)·ECAD(ODB 어댑터 계약, 스텁) 소스를 **읽기 전용**으로 읽어
불변 설계 IR 스냅샷(rr_ir)으로 동결하고, 단일 스냅샷의 상태(rr_state)와 두 스냅샷의 3층 diff(rr_diff)를
결론 없이 코드가 정리하며, HW/XD 전문가 패널이 낸 finding·gain·성격 서술을 IR id 에 앵커된 원자로
앱 DB 에 누적해 다음 과제의 심사 브리프에 되먹인다. 이름·경로·계약 정본은 포털 리포
`HWAXPortal/docs/design-risk-review/plan.md`(§10.8 #28) 이고, 이 리포의 `docs/plan.md` 는 그 포인터와 앱 관점 요약이다.

현재는 **P0 스캐폴드(정합 완료)** 단계다 — 계약(스키마·자산 JSON)·설정·스토어(§5.2.2 DDL 전문)·risk_spec 파서·MCP 도구 6종 시그니처·
REST `/api/health`·`/api/me`·`/api/me/portal-pat`·`/api/meta/*`·러너 골격·어댑터 레지스트리 v0·Vite/React 플레이스홀더 SPA 까지 있다.
레이아웃은 HEAXHub `fastapi_react` 스택(`backend/` + `frontend/`, MaterialTwinWeb 선례)이다.

## 구성 요소

| 구성 | 내용 |
|---|---|
| REST | `GET /api/health` · `GET /api/me` · `PUT /api/me/portal-pat` · `GET /api/meta/taxonomy` · `/api/meta/adapters` · `/api/meta/vocab` (Caddy 경유 `/apps/hwax_risk/api/…`, plan §8.2.3) |
| 헬스 | `GET /api/health` → `{ok: true, app_version, schema_version}` (형식 고정, 러너 상태는 싣지 않는다) |
| 신원 | `backend/app/identity.py` — `Authorization: Bearer`(우선) 또는 쿠키 `heax_access_token` 을 heax `GET /api/v1/auth/me` 로 되묻고 `sha256(token)` TTL 60 s 캐시. `X-Heax-User-*` 헤더는 읽지 않는다(위조 가능). 토큰 없음·401·불통은 anonymous |
| MCP | `hwax-risk` 서버, 도구 6종 `risk_get_snapshot(P1)` · `risk_get_diff(P2)` · `risk_get_registry` · `risk_claims_for_ref` · `risk_submit_panel_result(P3)` · `risk_get_brief(P5)` — P0 본문은 `{error:'not_implemented', ready_in}`. 앱 내부 exact `Route('/mcp')` → `/apps/hwax_risk/mcp` → 게이트웨이 백엔드 `heax-hwax_risk` |
| UI | `GET /` → `frontend/dist`(StaticFiles, html=True). dist 가 없으면 `backend/app/static/index.html` 플레이스홀더 |
| DB | `<data>/risk_review.db` — `PRAGMA user_version`=1, plan §5.2.2 `rr_*` 표 전문(33표) + 살림 표 `_schema_migrations` · `_user_credentials`, WAL |
| 러너 | `backend/app/runner.py` — 데몬 스레드 `panel_loop`·`sync_loop`·`nightly_loop`(P0 는 잠만 잔다), lifespan 이 start/stop |
| 스키마 | `backend/app/schemas/{rr_ir, rr_state, rr_diff, risk_spec, seat_opinion}.v1.json`(JSON Schema draft-07) |
| 자산 | `backend/app/assets/{taxonomy, character-vocab, character-seed-rules, adjacency, rules-seed, seat-contract}.v1.json`(package-data) · `docs/odb-adapter-contract.md` |

## 설치

```bash
cd /home/koopark/claude/HWAXRisk/backend
/usr/bin/python3.12 -m venv .venv
.venv/bin/pip install -e ".[test]"

cd ../frontend
pnpm install            # pnpm 10 · node 20, pnpm-lock.yaml 은 커밋 대상
pnpm build              # frontend/dist 생성(.gitignore)
```

Python ≥ 3.12. `mcp` 는 `>=1.10,<2` 로 핀한다(2.0 은 FastMCP 를 제거해 비호환). `httpx` 는 런타임 의존성이다(신원 되묻기·포털 PAT 검증).

## 실행

```bash
cd backend
# 콘솔 스크립트 (uvicorn app.main:app, --port 로 포트 지정, ROOT_PATH env 를 --root-path 로 전달)
.venv/bin/hwax-risk --port 8000

# 또는 직접 (HEAX fastapi_react 스택 entrypoint 와 동일, runscript 가 /app/backend 로 cd 한다)
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --root-path "${ROOT_PATH:-}"
```

확인.

```bash
curl -s http://127.0.0.1:8000/api/health          # {"ok":true,"app_version":"0.1.0","schema_version":1}
curl -s http://127.0.0.1:8000/api/me              # 토큰 없으면 anonymous
curl -s http://127.0.0.1:8000/api/meta/taxonomy | head -c 400
```

HEAX 러너는 `PORT · HOST=127.0.0.1 · HEAX_DATA_DIR · ROOT_PATH=/apps/hwax_risk · PYTHONNOUSERSITE=1` 를 env 로 준다.
앱은 `ROOT_PATH` 를 FastAPI `root_path` 에만 쓰고 라우트는 `/` 기준으로 선언한다. 프런트엔드는 `fetch('api/…')` 상대경로와
Vite `base: './'` 로 서브패스에서 그대로 동작한다.

## 설정·데이터 경로·시크릿

env 접두는 `HWAXRISK_`(plan §8.2.6). 데이터 루트 우선순위 `HWAXRISK_DATA_DIR` > `HEAX_DATA_DIR` > `<리포>/data`. 첫 기동 시 디렉터리를
만들고 쓸 수 없으면 기동을 중단하며, `<data>/risk_review.db` 에 v1 DDL 을 적용하고(멱등, 버전 정본은 `PRAGMA user_version`, 이력은
`_schema_migrations`) `origin.json{hostname, app_version, schema_version, written_at}` 을 쓴다. 기존 DB 의 `user_version` 이 목표보다
낮으면 적용 직전 `risk_review.db.pre-migrate-<ts>` 사본을 남기고, 코드보다 높으면 기동을 실패시킨다.
확장자 `.db` 는 HEAXHub `appdata-to-drive.sh` 의 `sqlite3 .backup` 원자 스냅샷 조건이다. 로컬 실행 시 리포 `data/` 는
`.gitignore` 로 `*.db*` 를 제외한다.

시크릿은 `<data>/secrets.env`(0600, `KEY=VALUE`) 의 `HWAXRISK_PORTAL_PAT · HWAXRISK_HEAX_SERVICE_PAT · HWAXRISK_AIDH_API_KEY` 3종이며 값은
로그에 싣지 않는다. `GET /api/me.box.secrets_valid` 는 세 값이 있고 `origin.json.hostname` 이 현재 호스트와 같을 때만 true 다.
사용자 포털 PAT 는 `PUT /api/me/portal-pat {pat}` 로 등록한다(email 일치 → aud `mcp-gateway`+scope `api` → 만료 ≥24 h → 포털
`GET /agent/conversations?limit=1` 200 순으로 검증, 실패 코드 `pat_email_mismatch · pat_audience · pat_expiring · pat_invalid`, `null` 은 삭제).

```bash
HWAXRISK_DATA_DIR=/tmp/hwax-risk-data backend/.venv/bin/hwax-risk --port 8001
```

## HEAX 등록

1. GitHub `squall321/HWAXRisk` 에 push(아직 미생성 — 생성 전에는 아래 등록을 보류한다).
2. `HEAXHub/integrations/hwax-risk/.portal/manifest.yaml` 에 이 리포 `.portal/manifest.yaml` 의 **복사본**(심볼릭 링크 아님)을 커밋.
3. 5분 스캔(또는 즉시 트리거 `backend/.venv/bin/python -c 'from app.workers.integration_tasks import scan_integrations_periodic as s; print(s()["by_action"])'`)이
   `var/sifs/hwax-risk.sif` 를 빌드하고 `var/app_data/hwax_risk/` 를 만든다. 로그 `var/logs/sif_build_hwax-risk.log` · `var/logs/integration_hwax_risk.log`.
   빌드는 스택 `install`(`pnpm install --frozen-lockfile && pnpm build && pip install -e ../backend`) 뒤 훅 `backend/scripts/heaxhub-build.sh`
   (PYTHONNOUSERSITE=1 재설치 + httpx 명시 + import 검증)를 실행한다.
4. 기동 후 heax `GET /api/v1/mcp/servers` 에 `hwax_risk` 가 나오면 게이트웨이 revive 루프가 `heax-hwax_risk` 백엔드를 자동 흡수한다(설정 변경 0).

매니페스트 요점(plan §8.2.2) — `schema_version 2 · app_type web_app · execution_target linux_runner · build{python_venv, stack fastapi_react, 3.12} ·
launch{service, env {PYTHONNOUSERSITE: "1"} 만, health /api/health} · permissions.visibility company · resources{cpu 1, memory_gb 2} · source{git, main} ·
mcp{expose, /mcp, streamable_http, allowed_groups []}`. `HWAXRISK_DATA_DIR` 은 `launch.env` 에 두지 않는다(HEAX 런처의 `HEAX_DATA_DIR` 폴백만,
context-notes D6).

## MCP 등록 예

```bash
# 로컬 dev (리포의 .mcp.json 과 동일)
claude mcp add --transport http hwax-risk http://127.0.0.1:8000/mcp

# 포털 경유 (Caddy forward_auth 뒤, heax PAT 필요)
claude mcp add --transport http hwax-risk <포털베이스>/apps/hwax_risk/mcp --header "Authorization: Bearer heax_pat_…"
```

직접 등록은 선택이다. 게이트웨이(`:9110`)가 heax `GET /api/v1/mcp/servers` 폴링으로 이 앱을 백엔드
`heax-hwax_risk` 로 자동 흡수하므로, 게이트웨이를 이미 붙여 둔 Claude Code 세션은 `risk_*` 6종을
그대로 본다. 위 두 줄은 게이트웨이 없이 앱만 직접 붙일 때 쓴다.

## Claude Code 에서 심사 돌리기

심의 엔진은 둘이고 앱 MCP 는 그 사이의 원장 접점이다(계획 §6.11).

| 등급 | 어떻게 | 원장 |
|---|---|---|
| L1 단발 | `hwax-deliberate` 워크플로에 `chairTemplate:'risk-review'` — 결정문 8항목 + `risk_spec` 펜스 + 기준선 옹호 지정석이 붙는다 | 미연동. 결과를 넣으려면 `risk_submit_panel_result` 를 사람이 부른다(패널이 `planned` 로 편성돼 있어야 하며 없으면 409) |
| L2 오케스트레이터 | `hwax-risk-review` 워크플로(`{targetKey, tier, panels?, actor?, model?}`) — `risk_get_brief` 로 패널·근거를 받아 패널마다 심의를 돌리고 `risk_submit_panel_result` 로 되돌린다 | `engine='mcp'` · `tool_mode='evidence_only'` · `actor_verified:false` |

두 워크플로 정본은 포털 리포 `HWAXPortal/infra/pipeline/` 에 있고 `infra/scripts/sync-workflows.sh`
로 `.claude/workflows/` 사본에 반영한다. Tier A 대표 패널과 무인 배치는 웹 러너 전용이라
`risk_get_brief(target_key, tier:'A')` 는 `{error:'tier_a_web_only'}` 를 돌려준다.

## 테스트

```bash
cd backend && .venv/bin/python -m pytest -q
```

`backend/tests/` — `test_boot.py`(기동 3점: `/api/health` 3키 · `POST /mcp` initialize+세션 헤더 · `/` text/html, dist 유무 분기, 옛 경로 404) ·
`test_config_datadir.py`(경로 우선순위·Settings 기본값·secrets.env) · `test_store.py`(user_version 1·rr_ 33표+살림 2·멱등·pre-migrate 사본·상위 버전 예외) ·
`test_parser.py`(risk_spec 파서) · `test_schemas.py` · `test_mcp_tools.py`(6종 고정·not_implemented·exact `Route('/mcp')`) · `test_manifest.py` ·
`test_identity.py`(Bearer/쿠키/위조 헤더/캐시, heax 는 `httpx.MockTransport`) · `test_me.py`(`/me`·`/me/portal-pat` 422 4종·등록·삭제, 포털은 MockTransport) ·
`test_runner.py` · `test_parity.py`(`HWAX_PORTAL_REPO` 와 엔진 additive 가 있을 때만, 아니면 skip). 외부 HTTP 실호출은 없다.
`frontend/dist` 가 있든 없든 전부 통과해야 한다.

## 프로젝트 구조

```
HWAXRisk/
├── .portal/manifest.yaml     # HEAX 매니페스트 v2 정본(stack fastapi_react)
├── .mcp.json                 # dev 로컬 http 등록 예
├── docs/                     # plan.md(포인터+요약) · odb-adapter-contract.md
├── backend/
│   ├── pyproject.toml        # hwax-risk, 콘솔 스크립트 hwax-risk, package-data(schemas·assets·static)
│   ├── app/                  # config · risk_store · narrative · taxonomy · identity · routes · mcp_server · runner · main · cli · adapters/ · schemas/ · assets/ · static/
│   ├── tests/
│   ├── scripts/heaxhub-build.sh   # SIF hermetic 보정 훅
│   └── .venv/                # git 제외
├── frontend/                 # Vite+React(TS) — package.json · pnpm-lock.yaml · src/{main,App,api}.tsx,ts · dist/(git 제외)
├── checklist.md · context-notes.md
└── data/                     # HEAX_DATA_DIR 폴백(*.db* 는 git 제외)
```
