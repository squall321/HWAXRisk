# HWAXRisk

설계 리스크 심사 앱(HEAX 앱 id `hwax_risk`, 표시명 **HWAX Risk Review**).

과제의 MCAD(StepForge)·Dyna(DynaForge)·ECAD(ODB 어댑터 계약, 스텁) 소스를 **읽기 전용**으로 읽어
불변 설계 IR 스냅샷(rr_ir)으로 동결하고, 단일 스냅샷의 상태(rr_state)와 두 스냅샷의 3층 diff(rr_diff)를
결론 없이 코드가 정리하며, HW/XD 전문가 패널이 낸 finding·gain·성격 서술을 IR id 에 앵커된 원자로
앱 DB 에 누적해 다음 과제의 심사 브리프에 되먹인다. 이름·경로·계약 정본은 포털 리포
`HWAXPortal/docs/design-risk-review/plan.md`(§10.8 #28) 이고, 이 리포의 `docs/plan.md` 는 그 포인터와 앱 관점 요약이다.

현재는 **P6(학습 루프)까지 구현** 단계다 — P1 IR 스냅샷·상태·게이트·규칙, P2 Dyna 어댑터·same-as·3층 diff, P3 패널 e2e·서술 저장,
P4 커버리지·편성·배치 러너·통합 보고서, P5 재사용 루프(선례·브리프), P6 학습 루프(라벨·패턴·규칙·지표)가 코드와 테스트로 서 있다.
남은 구멍은 E10 필드·VOC 근거(스텁)·라벨 자동 유입 4경로·프런트 화면 6종·P7 ODB 실연동이며 전부 [checklist.md](checklist.md) 에 있다.
레이아웃은 HEAXHub `fastapi_react` 스택(`backend/` + `frontend/`, MaterialTwinWeb 선례)이다.

## 구성 요소

| 구성 | 내용 |
|---|---|
| REST | `backend/app/routes.py` **64경로**(Caddy 경유 `/apps/hwax_risk/api/…`, plan §8.2.3) — `me`·`meta` · `projects`(멤버·이양·폐기·요구·감사·유사) · `sources`·`snapshots`(게이트 ack·rule_hits) · `sameas` · `diffs` · `targets`(브리프·커버리지·편성·findings·verdict) · `panels` · `registry` · `curation` · `patterns`·`precedents` · `vocab` · `export`/`import`. 모든 핸들러가 `Depends(identity.current)` |
| 헬스 | `GET /api/health` → `{ok: true, app_version, schema_version}` (형식 고정, 러너 상태는 싣지 않는다) |
| 신원 | `backend/app/identity.py` — `Authorization: Bearer`(우선) 또는 쿠키 `heax_access_token` 을 heax `GET /api/v1/auth/me` 로 되묻고 `sha256(token)` TTL 60 s 캐시. `X-Heax-User-*` 헤더는 읽지 않는다(위조 가능). 토큰 없음·401·불통은 anonymous |
| MCP | `hwax-risk` 서버, 도구 **7종** 실구현 — `risk_get_snapshot` · `risk_get_diff` · `risk_get_registry` · `risk_claims_for_ref` · `risk_submit_panel_result` · `risk_get_brief(target_key, brief_token, tier='B')` · `risk_add_finding`(P5 추가). 읽기 4종은 caller 를 `visible_projects` 로 걸러 범위 밖이면 `{error:'not_visible'}` 다. 앱 내부 exact `Route('/mcp')` → `/apps/hwax_risk/mcp` → 게이트웨이 백엔드 `heax-hwax_risk` |
| UI | `GET /` → `frontend/dist`(StaticFiles, html=True) — HashRouter 화면 6종 `RiskHomePage` · `ProjectPage` · `SnapshotPage` · `ComparePage` · `TargetPage` · `SettingsPage`. dist 가 없으면 `backend/app/static/index.html` 플레이스홀더 |
| DB | `<data>/risk_review.db` — `PRAGMA user_version`=1, plan §5.2.2 `rr_*` 표 전문(**41표**) + 살림 표 `_schema_migrations` · `_user_credentials`, WAL |
| 러너 | `backend/app/runner.py` — 데몬 스레드 `panel_loop`(패널 편성·심의 호출·회수) · `sync_loop`(RA·ADH 보류 op) · `nightly_loop`(00:30 지표 재합산·패턴 채굴·근접 중복 스캔), lifespan 이 start/stop |
| 파이프라인 | 캡처 `adapters/{mcad,dyna,ecad_stub}.py` → `ir_builder.py`(rr_ir) → `state.py`(G1~G7·signals·rule_hits) · `sameas.py`(사다리 7단) → `diff.py`(3층) → `brief.py`(E0~E10) → `narrative.py`(risk_spec 파싱·서술 저장) → `registry.py`(병합·C1~C3·보고서) → `learning.py`·`metrics.py`·`nightly.py`(학습 루프) |
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

시크릿은 `<data>/secrets.env`(0600, `KEY=VALUE`) 의 5키다 — `HWAXRISK_PORTAL_PAT`(scopes `read` 전용) · `HWAXRISK_PORTAL_PAT_RW`(RA·ADH 쓰기 전용) ·
`HWAXRISK_HEAX_SERVICE_PAT` · `HWAXRISK_AIDH_API_KEY` · `HWAXRISK_CRED_KEY`(Fernet). 값은 로그에 싣지 않는다.
`GET /api/me.box.secrets_valid` 는 다섯 값이 다 있고 `origin.json.hostname` 이 현재 호스트와 같을 때만 true 다.

사용자 포털 PAT 는 `PUT /api/me/portal-pat {pat}` 로 등록한다(email 일치 → aud `mcp-gateway`+scope → 만료 ≥24 h → 포털
`GET /agent/conversations?limit=1` 200 순으로 검증, 실패 코드 6종 `pat_email_mismatch · pat_audience · pat_scope_too_broad · pat_expiring ·
pat_invalid · cred_key_absent`, `null` 은 삭제). 저장은 **`portal_pat_enc` Fernet 암호문만**이고 평문 열은 없다(plan §8.2.7) —
키를 못 읽으면 평문 폴백 없이 422 다. 로컬 개발은 `<data>/cred.key` 폴백을 쓰며 그때 `secrets_valid` 는 내려간다.

```bash
HWAXRISK_DATA_DIR=/tmp/hwax-risk-data backend/.venv/bin/hwax-risk --port 8001
```

## HEAX 등록

**1~4 는 dev 에서 완료됐다**(2026-09-01 — SIF 빌드·기동·Caddy 라우트·게이트웨이 흡수 확인). 아래는 절차 기록이자 cae00 이관 때 그대로 쓸 순서다.

1. GitHub `squall321/HWAXRisk` 에 push.
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
`heax-hwax_risk` 로 자동 흡수하므로, 게이트웨이를 이미 붙여 둔 Claude Code 세션은 `risk_*` 7종을
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

`backend/tests/` 42파일 — 2026-09-02 실측 **1085 passed, 2 skipped**(`test_parity` 는 `HWAX_PORTAL_REPO` 미설정 시 skip).

| 묶음 | 파일 |
|---|---|
| 기동·설정·스토어 | `test_boot`(`/api/health` 3키·`POST /mcp` initialize+세션 헤더·`/` text/html, dist 유무 분기) · `test_config_datadir` · `test_store`(user_version 1·rr_ 41표+살림 2·멱등·pre-migrate 사본) · `test_manifest` |
| 계약·파서 | `test_schemas`(스키마 5종 × 유효/무효) · `test_parser` · `test_sanitize`(표기층 위생·인젝션) · `test_common` |
| 캡처·IR·상태 | `test_adapters` · `test_ir_builder` · `test_state_gates` · `test_gate_ack` · `test_requirements` · `test_render` |
| 비교·서술 | `test_sameas` · `test_diff` · `test_atoms` · `test_registry` · `test_character` |
| 패널·편성 | `test_planner` · `test_roster` · `test_runner` · `test_runner_panel` · `test_persist_panel` · `test_engine_client` · `test_brief` |
| 학습·야간 | `test_learning` · `test_learning_scenario` · `test_metrics` · `test_nightly` |
| 경계·배선 | `test_identity` · `test_me` · `test_p6_routes` · `test_project_patch` · `test_no_write_tools` · `test_mcp_tools`(7종·exact `Route('/mcp')`) · `test_wiring_regressions` |
| 통합 | `test_e2e_smoke` · `test_export_import` · `test_external_sync` · `test_bootstrap_scripts` · `test_parity` |

외부 HTTP 실호출은 없다(heax·포털·RA·ADH·agent-server 전부 `httpx.MockTransport`, SSE 는 `tests/fixtures/sse/` 3종).
`frontend/dist` 가 있든 없든 전부 통과해야 한다.

## 프로젝트 구조

```
HWAXRisk/
├── .portal/manifest.yaml     # HEAX 매니페스트 v2 정본(stack fastapi_react)
├── .mcp.json                 # dev 로컬 http 등록 예
├── docs/                     # plan.md(포인터+요약) · odb-adapter-contract.md
├── backend/
│   ├── pyproject.toml        # hwax-risk, 콘솔 스크립트 hwax-risk, package-data(schemas·assets·static)
│   ├── app/                  # 38모듈
│   │   ├── main · cli · config · risk_store · identity · errors · common      # 골격·경계
│   │   ├── routes(64경로) · mcp_server(7도구) · export · taxonomy            # 바깥으로 난 창
│   │   ├── adapters/{base,registry,mcad,dyna,ecad_stub}                       # 소스 앱 읽기(읽기 전용)
│   │   ├── ir_builder · state · sameas · diff                                 # IR·상태·비교
│   │   ├── brief · narrative · registry · character · render · requirements   # 서술·등록부
│   │   ├── runner · planner · roster · engine_client                          # 편성·심의 호출
│   │   ├── learning · metrics · nightly                                       # 학습 루프
│   │   ├── ra_client · adh_client                                             # 외부 투영(RA·AIDataHub)
│   │   └── schemas/ · assets/ · static/
│   ├── tests/                # 42파일 + fixtures/{rr_ir,rr_state,rr_diff,risk_spec,seat_opinion,diff_pairs,incidents,ir,sse}
│   ├── scripts/              # heaxhub-build.sh(SIF 훅) · bootstrap_{ra_ontology,adh}.py · recompute_part_keys.py · remap_findings.py · backup-to-drive.sh
│   └── .venv/                # git 제외
├── frontend/                 # Vite+React(TS) — src/{App,main,types,format} · pages/(6) · components/(6) · api/risk.api.ts · dist/(git 제외)
├── checklist.md              # 진척과 잔여 백로그(작업 대장)
├── context-notes.md          # 결정과 그 이유
└── data/                     # HEAX_DATA_DIR 폴백(*.db* 는 git 제외)
```
