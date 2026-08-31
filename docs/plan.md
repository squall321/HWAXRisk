<!-- HWAXRisk 앱 관점 계획 요약 — 포털 정본 plan.md 를 가리키는 포인터와 B 토폴로지·데이터 경로·MCP·REST·P0 범위 1페이지 -->
# HWAXRisk — 계획(앱 관점 요약)

작성일 2026-08-31. P0 정합(plan §9.1 A-δ) 반영 2026-08-31.

## 정본 포인터

계획 정본은 포털 리포 **`/home/koopark/claude/HWAXPortal/docs/design-risk-review/plan.md`** 이다. 이 문서는 그 정본을 앱 리포에서
빠르게 찾기 위한 절 색인과 앱 관점 1페이지 요약이다. 이름·경로·계약 정본도 그 plan.md(§10.8 #28) 이며, 이 리포의 `context-notes.md` 는
앱 리포에서 내린 결정의 이유만 남긴다.

| 정본 절 | 내용 | 이 리포에서 쓰는 곳 |
|---|---|---|
| §0 | spine — 용어·식별자·저장 3층·파일·API·상수표 | 전체 이름 |
| §0.5.1 · §0.5.2 · §0.5.3 | REST base `/api` 경로 목록 · MCP 도구 6종 시그니처 · Settings env `HWAXRISK_` | `backend/app/{routes,mcp_server,config}.py` |
| §2 | rr_ir 봉투·노드·엣지·소스 매핑·same-as·ckey·dims_named·원장·ir_hash | `backend/app/schemas/rr_ir.v1.json` |
| §2.5.3 · §2.13.5 | ODB 어댑터 계약 4도구·필드·상한, 스텁 동작 | `docs/odb-adapter-contract.md` |
| §3 | rr_state(G1~G7·signals·character_seed·feature_vector·rule_hits)·rr_diff 3층 | `backend/app/schemas/rr_state.v1.json` · `rr_diff.v1.json` |
| §3.2.4 · §3.2.6 | character-seed-rules · rules-seed | `backend/app/assets/character-seed-rules.v1.json` · `rules-seed.v1.json` |
| §4.2 · §4.2.2 | risk_spec 규격 · parse_risk_spec(P0) | `backend/app/schemas/risk_spec.v1.json` · `backend/app/narrative.py` |
| §4.5 | seat_opinion | `backend/app/schemas/seat_opinion.v1.json` |
| §4.6.3 | character-vocab | `backend/app/assets/character-vocab.v1.json` |
| §5.2.2 · §5.2.5 | 앱 DB DDL 전문(A~H) · 데이터 지속(pre-migrate 사본·origin.json·user_version) | `backend/app/risk_store.py`(v1 = DDL 전문) · `main.py` lifespan |
| §6.4 · §6.5.3 | adjacency · seat-contract | `backend/app/assets/adjacency.v1.json` · `seat-contract.v1.json` |
| §7.1 | 택소노미 v1 | `backend/app/assets/taxonomy.v1.json` · `backend/app/taxonomy.py` |
| §8.2 | 앱 구조·매니페스트·REST·MCP·Settings·시크릿·신원·러너·헬스·기동 순서 | `.portal/manifest.yaml` · `backend/app/{main,routes,mcp_server,config,identity,runner}.py` · `frontend/` |
| §8.3 | 엔진 파리티(PY/JS 문자열) | `backend/tests/test_parity.py`(skip 조건부) |
| §9.1 | P0 산출물·A-δ 즉시 델타·통과 기준 | `checklist.md` |

## B 토폴로지 — 자산은 앱, 포털은 창

```
포털(HWAXPortal)                      HEAX 앱 hwax_risk(이 리포)                      소스 앱(읽기 전용)
 메뉴 타일 hwax-risk ─launch─▶ /apps/hwax_risk/ (Vite/React SPA, P0 플레이스홀더)      StepForge   heax-step_forge   (mcad)
 심의 Job 'risk-review'(L1)     /apps/hwax_risk/api/*     REST                DynaForge   heax-kooremapper_mcp (dyna)
                                /apps/hwax_risk/mcp       MCP ──▶ 게이트웨이  ODB hub     계약만(ecad, 스텁)
                                $DATA/risk_review.db      앱 DB(단일 진실 원천)
                                                          ↕ appdata-to-drive.sh 백업 · cae00 이관
```

- 앱이 소유하는 것 — 전용 sqlite(rr_* 표)·REST·MCP·UI·러너. 포털은 메뉴 창 하나와 심의 엔진(additive 항목)만.
- 소스 앱은 읽기만 한다. 앱 화면·도구에 소스 앱 쓰기 버튼은 없다(헌법 P1·P8).
- 게이트웨이 흡수는 설정·코드 변경 0 — 매니페스트 `status beta` + `mcp.expose` + 기동 state 파일이면 heax `GET /api/v1/mcp/servers` 에
  나오고 revive 루프가 `heax-hwax_risk` 를 만든다.

## 데이터 경로·시크릿

| 항목 | 값 |
|---|---|
| 루트 우선순위 | `HWAXRISK_DATA_DIR` > `HEAX_DATA_DIR` > `<리포>/data` (없으면 생성, 쓰기 불가면 기동 중단) |
| DB | `<data>/risk_review.db` — stdlib sqlite3 + `threading.Lock`, WAL, 버전 정본 `PRAGMA user_version`, 이력 `_schema_migrations(version, applied_at, app_version)`. `.db` 는 `appdata-to-drive.sh` 원자 백업 조건 |
| v1 표 | 정본 §5.2.2 A~H DDL 전문(`rr_*` 33표 + 인덱스) + 살림 표 `_schema_migrations` · `_user_credentials`(CREATE TABLE IF NOT EXISTS) |
| 지속 | 기존 DB 에 적용할 버전이 있으면 `risk_review.db.pre-migrate-<ts>` 사본, `user_version` 이 코드보다 높으면 기동 실패, 기동마다 `origin.json` 갱신 |
| 시크릿 | `<data>/secrets.env`(0600) 의 `HWAXRISK_PORTAL_PAT · HWAXRISK_HEAX_SERVICE_PAT · HWAXRISK_AIDH_API_KEY`. `secrets_valid` = 세 값 존재 AND `origin.json.hostname` 일치 |
| 소유권 | `owner_sub` = `identity.email`. 원천은 heax `GET /api/v1/auth/me` 되묻기(`backend/app/identity.py`). `X-Heax-User-*` 헤더는 service 모드에 복사되지 않고 위조 가능해 읽지 않는다 |
| SIF | `HEAX_DATA_DIR=/data`(호스트 `HEAXHub/var/app_data/hwax_risk/`), rootfs read-only |

## MCP

- 서버 `hwax-risk`(FastMCP, `mcp>=1.10,<2`, DNS-rebinding 보호 off), 앱 내부 exact `Route('/mcp')`(Mount 아님 — 307 없음) → `/apps/hwax_risk/mcp` → 게이트웨이 백엔드 `heax-hwax_risk`.
- 도구 6종(§0.5.2) — `risk_get_snapshot(snapshot_id, part)` · `risk_get_diff(diff_id, part)` · `risk_get_registry(target_key)` · `risk_claims_for_ref(ref)` ·
  `risk_get_brief(target_key, tier='B')` · `risk_submit_panel_result(panel_id, engine, decision_text, turns, report_id, actor, model=None)`.
  P0 본문은 전부 `{error:'not_implemented', ready_in}`(snapshot P1 · diff P2 · registry/claims/submit P3 · brief P5).
- 게이트웨이 경유 호출은 heax 서비스 PAT 신원으로 도달하므로 최종 사용자는 오지 않는다 — 쓰기 도구는 `actor`(미검증 표기) 인자를 받는다.

## REST

- base `/apps/hwax_risk/api`(앱 내부 `/api`, `backend/app/routes.py`), 모든 핸들러는 `Depends(identity.current)`.
- P0 — `GET /health {ok, app_version, schema_version}` · `GET /me {email, display_name, role, organization, anonymous, source, portal_pat|null, box{hostname, secrets_valid}}` ·
  `PUT /me/portal-pat {pat|null}`(익명 401, 422 `pat_email_mismatch · pat_audience · pat_expiring · pat_invalid`) · `GET /meta/taxonomy` · `GET /meta/adapters`
  (`mcad → heax-step_forge planned`, `dyna → heax-kooremapper_mcp planned`, `ecad → contract_only`, `adapters/registry.py` v0) · `GET /meta/vocab`.
- 정본 §8.2.3 의 나머지 경로(projects·sources·snapshots·sameas·diffs·targets·panels·registry·export/import)는 P1~P6.

## P0 범위(이 리포 몫)

- 계약 — JSON 스키마 5종(draft-07, 최상위만 `additionalProperties:false`)·자산 JSON 6종(`backend/app/assets/`)·ODB 어댑터 계약 문서.
- 골격 — Settings(§8.2.6)·RiskStore(DDL 전문)·`parse_risk_spec`/`validate_risk_spec`·taxonomy 로더·identity(되묻기+캐시)·routes(`/me`·`/me/portal-pat`·meta 3종)·
  MCP 도구 6종 시그니처·`/api/health`·러너 골격·어댑터 레지스트리 v0·Vite/React 플레이스홀더 SPA(`frontend/`)·CLI.
- 테스트 — 기동 3점·데이터 경로·스토어·파서·스키마·MCP 도구·매니페스트·신원·`/me`·러너·파리티(조건부 skip).
- 보류 — GitHub 생성·HEAXHub 등록·엔진 additive·포털 메뉴·`scripts/{bootstrap_ra_ontology,bootstrap_adh}.py`·`export.py`·정규화 10단계·어댑터 실구현(`context-notes.md` D4·D6).

이 단계만으로 얻는 것 — 앱이 HEAX 에 등록·기동 가능한 형태(헬스·MCP initialize·SPA 3점)와, 이후 단계가 그 위에서만 움직일 계약(스키마·자산·DDL·REST/MCP 시그니처).
