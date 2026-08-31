# HWAXRisk

설계 리스크 심사 앱(HEAX 앱 id `hwax_risk`, 표시명 **HWAX Risk Review**).

과제의 MCAD(StepForge)·Dyna(DynaForge)·ECAD(ODB 어댑터 계약, 스텁) 소스를 **읽기 전용**으로 읽어
불변 설계 IR 스냅샷(rr_ir)으로 동결하고, 단일 스냅샷의 상태(rr_state)와 두 스냅샷의 3층 diff(rr_diff)를
결론 없이 코드가 정리하며, HW/XD 전문가 패널이 낸 finding·gain·성격 서술을 IR id 에 앵커된 원자로
앱 DB 에 누적해 다음 과제의 심사 브리프에 되먹인다. 계획 정본은 포털 리포
`HWAXPortal/docs/design-risk-review/plan.md` 이고, 이 리포의 `docs/plan.md` 는 그 포인터와 앱 관점 요약이다.

현재는 **P0 스캐폴드** 단계다 — 계약(스키마·자산 JSON)·설정·스토어 골격·risk_spec 파서·읽기 전용 MCP 도구 3종·
REST `/api/meta*`·Vite/React 플레이스홀더 SPA 까지만 있다. 레이아웃은 HEAXHub `fastapi_react` 스택(`backend/` + `frontend/`,
MaterialTwinWeb 선례)이다.

## 구성 요소

| 구성 | 내용 |
|---|---|
| REST | `/api/meta` · `/api/meta/taxonomy` · `/api/meta/adapters` · `/api/meta/vocab` (Caddy 경유 `/apps/hwax_risk/api/…`) |
| MCP | `hwax-risk` 서버, 도구 3종 `risk_health` · `risk_get_taxonomy` · `risk_get_meta`. 앱 내부 exact `Route('/mcp')` → `/apps/hwax_risk/mcp` → 게이트웨이 백엔드 `heax-hwax_risk` |
| 헬스 | `GET /api/health` → `{status, app_id, version, schema_version, data_dir}` |
| UI | `GET /` → `frontend/dist`(StaticFiles, html=True). dist 가 없으면 `backend/app/static/index.html` 플레이스홀더 |
| DB | `<data>/risk_review.db` — P0 는 `rr_projects · rr_sources · rr_snapshots · rr_snapshot_calls` 4표 + `schema_migrations` |
| 스키마 | `backend/app/schemas/{rr_ir, rr_state, rr_diff, risk_spec, seat_opinion}.v1.json`(JSON Schema draft-07) |
| 자산 | `docs/{taxonomy, character-vocab, character-seed-rules, adjacency, rules-seed, seat-contract}.v1.json` · `docs/odb-adapter-contract.md` |

## 설치

```bash
cd /home/koopark/claude/HWAXRisk/backend
/usr/bin/python3.12 -m venv .venv
.venv/bin/pip install -e ".[test]"

cd ../frontend
pnpm install            # pnpm 10 · node 20, pnpm-lock.yaml 은 커밋 대상
pnpm build              # frontend/dist 생성(.gitignore)
```

Python ≥ 3.12. `mcp` 는 `>=1.10,<2` 로 핀한다(2.0 은 FastMCP 를 제거해 비호환).

**editable 설치 전제.** 런타임 자산 `docs/*.v1.json` 은 리포 루트의 `docs/` 에서 읽으며 wheel 패키지 데이터에 들어 있지 않다.
비-editable 설치(wheel)에서는 `/api/meta/taxonomy`·`risk_get_taxonomy` 가 503 이 된다 — HEAX `fastapi_react` 스택은
`pip install -e ../backend` 이라 지금은 동작하고, 자산을 `backend/app/assets/` 로 옮기는 일은 P1 이다(plan §5.2.5 (1)).

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
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/meta
curl -s http://127.0.0.1:8000/api/meta/taxonomy | head -c 400
```

HEAX 러너는 `PORT · HOST=127.0.0.1 · HEAX_DATA_DIR · ROOT_PATH=/apps/hwax_risk · PYTHONNOUSERSITE=1` 를 env 로 준다.
앱은 `ROOT_PATH` 를 FastAPI `root_path` 에만 쓰고 라우트는 `/` 기준으로 선언한다. 프런트엔드는 `fetch('api/…')` 상대경로와
Vite `base: './'` 로 서브패스에서 그대로 동작한다.

## 데이터 경로

우선순위 `HWAX_RISK_DATA_DIR` > `HEAX_DATA_DIR` > `<리포>/data`. 첫 기동 시 디렉터리를 만들고 쓸 수 없으면 기동을
중단하며, `<data>/risk_review.db` 에 `schema_migrations` 와 v1 표 4종을 만든다(멱등, 버전 정본은 `PRAGMA user_version`).
확장자 `.db` 는 HEAXHub `appdata-to-drive.sh` 의 `sqlite3 .backup` 원자 스냅샷 조건이다. 로컬 실행 시 리포 `data/` 는
`.gitignore` 로 `*.db*` 를 제외한다.

```bash
HWAX_RISK_DATA_DIR=/tmp/hwax-risk-data backend/.venv/bin/hwax-risk --port 8001
```

## HEAX 등록

1. GitHub `squall321/HWAXRisk` 에 push(아직 미생성 — 생성 전에는 아래 등록을 보류한다).
2. `HEAXHub/integrations/hwax-risk/.portal/manifest.yaml` 에 이 리포 `.portal/manifest.yaml` 의 **복사본**(심볼릭 링크 아님)을 커밋.
3. 5분 스캔(또는 즉시 트리거 `backend/.venv/bin/python -c 'from app.workers.integration_tasks import scan_integrations_periodic as s; print(s()["by_action"])'`)이
   `var/sifs/hwax-risk.sif` 를 빌드하고 `var/app_data/hwax_risk/` 를 만든다. 로그 `var/logs/sif_build_hwax-risk.log` · `var/logs/integration_hwax_risk.log`.
   빌드는 스택 `install`(`pnpm install --frozen-lockfile && pnpm build && pip install -e ../backend`) 뒤 훅 `backend/scripts/heaxhub-build.sh`
   (PYTHONNOUSERSITE=1 재설치 + httpx 명시 + import 검증)를 실행한다.
4. 기동 후 heax `GET /api/v1/mcp/servers` 에 `hwax_risk` 가 나오면 게이트웨이 revive 루프가 `heax-hwax_risk` 백엔드를 자동 흡수한다(설정 변경 0).

매니페스트 요점 — `schema_version 2 · app_type web_app · execution_target linux_runner · build{python_venv, stack fastapi_react, 3.12} ·
launch{service, env PYTHONNOUSERSITE=1, health /api/health} · permissions.visibility team · resources{cpu 1, memory_gb 1} · source{git, main} · mcp{expose, /mcp, streamable_http}`.

## MCP 등록 예

```bash
# 로컬 dev (리포의 .mcp.json 과 동일)
claude mcp add --transport http hwax-risk http://127.0.0.1:8000/mcp

# 포털 경유 (Caddy forward_auth 뒤, heax PAT 필요)
claude mcp add --transport http hwax-risk <포털베이스>/apps/hwax_risk/mcp --header "Authorization: Bearer heax_pat_…"
```

## 테스트

```bash
cd backend && .venv/bin/python -m pytest -q
```

`backend/tests/` — 헬스(`/api/health`, 옛 `/health`·`/api/v1` 404) · `/`(dist 유무 분기) · 데이터 경로 우선순위 · 스토어 마이그레이션 멱등 ·
risk_spec 파서 픽스처 · 스키마 라운드트립 · MCP 도구 3종 + exact `Route('/mcp')`(Mount 아님·307 아님) · 매니페스트 스키마 검증 · 신원 헤더.
`frontend/dist` 가 있든 없든 전부 통과해야 한다.

## 프로젝트 구조

```
HWAXRisk/
├── .portal/manifest.yaml     # HEAX 매니페스트 v2 정본(stack fastapi_react)
├── .mcp.json                 # dev 로컬 http 등록 예
├── docs/                     # plan.md(포인터+요약) · odb-adapter-contract.md · *.v1.json 자산 6종
├── backend/
│   ├── pyproject.toml        # hwax-risk, 콘솔 스크립트 hwax-risk
│   ├── app/                  # config · risk_store · narrative · taxonomy · identity · api · mcp_server · main · cli · schemas/ · static/
│   ├── tests/
│   ├── scripts/heaxhub-build.sh   # SIF hermetic 보정 훅
│   └── .venv/                # git 제외
├── frontend/                 # Vite+React(TS) — package.json · pnpm-lock.yaml · src/{main,App,api}.tsx,ts · dist/(git 제외)
├── checklist.md · context-notes.md
└── data/                     # HEAX_DATA_DIR 폴백(sqlite 는 git 제외)
```
