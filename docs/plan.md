<!-- HWAXRisk 앱 관점 계획 요약 — 포털 정본 plan.md 를 가리키는 포인터와 B 토폴로지·데이터 경로·MCP·REST·구현 범위 1페이지 -->
# HWAXRisk — 계획(앱 관점 요약)

작성일 2026-08-31. P6 구현 반영 2026-09-02. 단계별 진척과 잔여 백로그는 `../checklist.md` 가 정본이다.

## 정본 포인터

계획 정본은 포털 리포 **`/home/koopark/claude/HWAXPortal/docs/design-risk-review/plan.md`** 이다. 이 문서는 그 정본을 앱 리포에서
빠르게 찾기 위한 절 색인과 앱 관점 1페이지 요약이다. 이름·경로·계약 정본도 그 plan.md(§10.8 #28) 이며, 이 리포의 `context-notes.md` 는
앱 리포에서 내린 결정의 이유만 남긴다.

| 정본 절 | 내용 | 이 리포에서 쓰는 곳 |
|---|---|---|
| §0 | spine — 용어·식별자·저장 3층·파일·API·상수표 | 전체 이름 |
| §0.5.1 · §0.5.2 · §0.5.3 | REST base `/api` 경로 목록 · MCP 도구 시그니처(6종 + P5 `risk_add_finding`) · Settings env `HWAXRISK_` | `backend/app/{routes,mcp_server,config}.py` |
| §2 | rr_ir 봉투·노드·엣지·소스 매핑·same-as·ckey·dims_named·원장·ir_hash | `backend/app/schemas/rr_ir.v1.json` · `ir_builder.py` |
| §2.5.3 · §2.13.5 | ODB 어댑터 계약 4도구·필드·상한, 스텁 동작 | `docs/odb-adapter-contract.md` · `adapters/ecad_stub.py` |
| §2.11 · §2.13 | 캡처 잡·부분 실패·호출 예산·어댑터 실측 계약(suffix 매칭·타입 정규화·절단 감지) | `backend/app/adapters/{base,registry,mcad,dyna}.py` |
| §3 | rr_state(G1~G7·signals·character_seed·feature_vector·rule_hits)·rr_diff 3층 | `backend/app/schemas/rr_state.v1.json` · `rr_diff.v1.json` |
| §3.2 · §3.3 | 게이트·규칙 평가 · 3층 diff·의미 이벤트·비교 가능성 5키 | `backend/app/{state,sameas,diff}.py` |
| §3.2.4 · §3.2.6 | character-seed-rules · rules-seed | `backend/app/assets/character-seed-rules.v1.json` · `rules-seed.v1.json` |
| §3.4.1 | 표기층 위생·인젝션 어휘(`«…»`·suspect_text 큐·recall_eligible) | `backend/app/render.py` |
| §4.2 · §4.3 · §4.7 | risk_spec 규격·파싱 · 원자·클러스터·별칭 · 등록부 status 주체·이력 | `backend/app/schemas/risk_spec.v1.json` · `{narrative,registry}.py` |
| §4.5 | seat_opinion | `backend/app/schemas/seat_opinion.v1.json` |
| §4.6.3 | character-vocab · 성격 서술·X태그 승격 | `backend/app/assets/character-vocab.v1.json` · `character.py` |
| §5.2.2 · §5.2.5 · §5.2.6 | 앱 DB DDL 전문(A~H) · 데이터 지속 · 소유·수명주기·감사·폐기 회수 | `backend/app/risk_store.py`(v1 = DDL 전문) · `main.py` lifespan · `routes.py` |
| §5.3 · §5.4 · §5.5 | 외부 투영 3층(앱 DB 정본 · RA · AIDataHub)과 보류 op | `backend/app/{ra_client,adh_client}.py` |
| §5.6 · §6.6 | prior_evidence E0~E10 · 브리프 예산·항목 12 | `backend/app/brief.py` |
| §6.4 · §6.5.3 | adjacency · seat-contract | `backend/app/assets/adjacency.v1.json` · `seat-contract.v1.json` |
| §6.7 · §6.8 | 러너 경로 (A)/(B)·자격 결정 · 커버리지 원장·편성·완결 레벨 | `backend/app/{runner,planner,roster,engine_client}.py` |
| §6.11 | MCP 경로의 실행 등급(웹 러너 · L1 단발 · L2 오케스트레이터 · 재제출) | `README.md` "Claude Code 에서 심사 돌리기" · 포털 `infra/pipeline/hwax-risk-review.js` |
| §7.1 | 택소노미 v1 | `backend/app/assets/taxonomy.v1.json` · `backend/app/taxonomy.py` |
| §7.5 · §7.6 · §7.7 | 라벨·조건 DSL·백테스트·패턴 승격 · 지표 · 큐레이션 큐 | `backend/app/{learning,metrics,nightly}.py` |
| §8.2 | 앱 구조·매니페스트·REST·MCP·Settings·시크릿·신원·러너·헬스·기동 순서 | `.portal/manifest.yaml` · `backend/app/{main,routes,mcp_server,config,identity,runner}.py` · `frontend/` |
| §8.3 | 엔진 파리티(PY/JS 문자열) | `backend/tests/test_parity.py`(skip 조건부) |
| §9.1~§9.8 | 단계별 산출물·통과 기준 | `../checklist.md`(실측 진척과 잔여 백로그) |

## B 토폴로지 — 자산은 앱, 포털은 창

```
포털(HWAXPortal)                      HEAX 앱 hwax_risk(이 리포)                      소스 앱(읽기 전용)
 메뉴 타일 hwax-risk ─launch─▶ /apps/hwax_risk/ (Vite/React SPA, 화면 6종)            StepForge   heax-step_forge   (mcad)
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
| v1 표 | 정본 §5.2.2 A~H DDL 전문(`rr_*` 41표 + 인덱스) + 살림 표 `_schema_migrations` · `_user_credentials`(CREATE TABLE IF NOT EXISTS) |
| 지속 | 기존 DB 에 적용할 버전이 있으면 `risk_review.db.pre-migrate-<ts>` 사본, `user_version` 이 코드보다 높으면 기동 실패, 기동마다 `origin.json` 갱신 |
| 시크릿 | `<data>/secrets.env`(0600) 의 5키 — `HWAXRISK_PORTAL_PAT`(scopes read) · `PORTAL_PAT_RW`(RA·ADH 쓰기) · `HEAX_SERVICE_PAT` · `AIDH_API_KEY` · `CRED_KEY`(Fernet). `secrets_valid` = 다섯 값 존재 AND `origin.json.hostname` 일치 |
| 사용자 자격 | `_user_credentials.portal_pat_enc`(Fernet 암호문만, 평문 열 없음) · `pat_scopes_json` · `pat_jti` · `revoked_at`. 키는 `HWAXRISK_CRED_KEY` > `CRED_KEY_PATH` > `<data>/cred.key`(로컬 폴백, 그때 `secrets_valid` 는 내려간다) |
| 소유권 | `owner_sub` = `identity.email`. 원천은 heax `GET /api/v1/auth/me` 되묻기(`backend/app/identity.py`). `X-Heax-User-*` 헤더는 service 모드에 복사되지 않고 위조 가능해 읽지 않는다 |
| SIF | `HEAX_DATA_DIR=/data`(호스트 `HEAXHub/var/app_data/hwax_risk/`), rootfs read-only |

## MCP

- 서버 `hwax-risk`(FastMCP, `mcp>=1.10,<2`, DNS-rebinding 보호 off), 앱 내부 exact `Route('/mcp')`(Mount 아님 — 307 없음) → `/apps/hwax_risk/mcp` → 게이트웨이 백엔드 `heax-hwax_risk`.
- 도구 **14종**, 전부 실구현. 발견 7종(2026-09-07 추가) — `risk_list_projects`(진입점) · `risk_get_coverage` ·
  `risk_list_panels` · `risk_get_panel_transcript` · `risk_taxonomy` · `risk_get_precedents` · `risk_similar_projects`.
  나머지 원장 7종(§0.5.2 6종 + P5 의 `risk_add_finding`) — `risk_get_snapshot(snapshot_id, part)` · `risk_get_diff(diff_id, part)` ·
  `risk_get_registry(target_key, status?, severity?)` · `risk_claims_for_ref(ref)` · `risk_get_brief(target_key, brief_token, tier='B')` ·
  `risk_submit_panel_result(panel_id, engine, decision_text, turns, report_id, actor, model=None)` · `risk_add_finding`(P3 REST 를 감싼다).
- 읽기 4종은 `mcp_caller` → `routes.visible_projects(caller)` 로 범위를 거르고 밖이면 `{error:'not_visible'}` 다 — 서비스 신원에는
  `mcp_visibility='org'` 과제만, 개인 PAT 에는 멤버십 범위까지 열린다(§5.1 원칙 9). `risk_get_brief` 는 `actor` 만으로는 열리지 않고
  `GET /targets/{key}/brief` 가 발급한 `brief_token` 으로만 200 이다.
- 게이트웨이 경유 호출도 **사용자 신원으로 온다**(2026-09-07). `POST /api/auth/sso` 가 공유 시크릿
  (`secrets.env` 의 `HWAXRISK_HEAX_GATEWAY_SECRET`, 없으면 404)을 받고 이메일·만료만 담은 무상태 HMAC 단언
  `rrsso_…`(기본 900 s)을 내주며, 게이트웨이는 그것을 `X-Heax-Sso-Assertion` 헤더로 실어 부른다.
  Authorization 은 Caddy `forward_auth` 통과용 heax 서비스 토큰이라 비워둘 수 없어 헤더를 따로 쓴다.
  `identity.current` 는 그 헤더를 먼저 보고 **서명만** 검증한다(heax 되묻기 없음) — 신뢰 근거가 헤더 위치가 아니라
  서명이라 위조 헤더는 anonymous 로 떨어진다. 역할·부서는 단언에 없으므로 관리자 경로는 SSO 호출자에게 닫힌다.
  이 배선이 없으면 서비스 신원이라 `mcp_visibility='org'` 과제만 보이고, 실제 과제가 전부 private 이면 0건이 된다(실측).
  쓰기 도구의 `actor` 인자는 그대로 미검증 표기다.
- Claude 연결 경로 둘(§6.11). 게이트웨이(`:9110`)를 붙인 세션은 백엔드 `heax-hwax_risk` 로 `risk_*` 14종을 그대로 본다.
  앱만 직접 붙이려면 `claude mcp add --transport http hwax-risk <포털베이스>/apps/hwax_risk/mcp --header "Authorization: Bearer heax_pat_…"`
  (로컬 dev 는 리포의 `.mcp.json` 과 같은 `http://127.0.0.1:8000/mcp`).
- 실행 등급 둘 — L1 단발은 `hwax-deliberate` 에 `chairTemplate:'risk-review'`(원장 미연동), L2 는 포털 워크플로 `hwax-risk-review`
  (`{targetKey, tier, panels?, actor?, model?}`)가 `risk_get_brief` → 패널별 심의 → `risk_submit_panel_result` 로 돈다. 자세한 표는 `README.md`.
  Tier A 대표 패널과 무인 배치는 웹 러너 전용이라 `risk_get_brief(target_key, tier:'A')` 는 `{error:'tier_a_web_only'}` 다.

## REST

- base `/apps/hwax_risk/api`(앱 내부 `/api`, `backend/app/routes.py`), 모든 핸들러는 `Depends(identity.current)`. 정본 §8.2.3 의 경로가 **64개** 배선돼 있다.
- 신원·메타 — `GET /health {ok, app_version, schema_version}` · `GET /me`(+`box{hostname, secrets_valid, cred_key_present}`) ·
  `PUT /me/portal-pat {pat|null}`(익명 401, 422 6종) · `GET /meta/{taxonomy, adapters, vocab, metrics}` · `POST /meta/metrics/recompute`.
- 과제·소스·스냅샷 — `projects`(생성·조회·`PATCH`(lifecycle·등급·`mcp_visibility`)·멤버·이양·폐기·감사·유사·dims·요구·`iface-ledger`) ·
  `sources` · `snapshots`(조회·게이트 ack·`rule_hits`) · `sameas`(조회·`decide`) · `diffs`.
- 심사 — `targets`(브리프·커버리지·편성 `jobs`·`refresh_roster`·`resync`·`findings`·`registry`·`verdict`) · `panels`(브리프·`complete`) ·
  `registry`(status·visibility·merge) · `findings`(수정·삭제·라벨) · `curation` · `patterns` · `precedents` · `refs/{ref:path}`.
- 살림 — `vocab/{synonyms, stop-tokens}` · `jobs/{id}/{action}` · `GET /export` · `POST /import`.

## 구현 범위(현재 P6, 이 리포 몫)

단계별 상태와 잔여 백로그의 정본은 이 리포 `checklist.md` 다. 여기서는 계층만 적는다.

- **계약** — JSON 스키마 5종(draft-07, 최상위만 `additionalProperties:false`)·자산 JSON 6종(`backend/app/assets/`)·ODB 어댑터 계약 문서·§5.2.2 DDL 41표.
- **캡처·IR**(P1·P2) — `adapters/{base,registry,mcad,dyna,ecad_stub}` 가 소스 앱을 읽기 전용으로 열고 `ir_builder` 가 rr_ir 봉투를 동결한다.
  표기층 위생·인젝션 어휘(`render.sanitize_source_text`·`INJECTION_LEXICON`)가 원문을 «…» 안에 가두고 적중분은 `suspect_text` 큐로 보낸다.
- **상태·비교**(P1·P2) — `state`(G1~G7·signals·`character_seed`·`feature_vector`·`rule_hits`) · `sameas`(사다리 7단·헝가리안·원장 재적용) · `diff`(3층·의미 이벤트·`comparability` 5키).
- **서술·등록부**(P3) — `brief`(E0~E10) → 심의 → `narrative`(risk_spec 파싱·cites·`evidence_grade`·좌석 의견) → `registry`(병합·별칭 체인·status 이력·기각 보존).
  원문은 `rr_panel_calls` 에 gzip 으로 남고 `rr_panels.brief_gz` 로 브리프 자체가 재현된다.
- **편성·회계**(P4) — `planner`(Tier A/B/C·라운드로빈·인접·deferred·carried) · `roster` · `runner` 배치 · 완결 레벨 C1~C3 · 통합 보고서.
- **재사용**(P5) — `brief` 의 E5+/E5−·E6~E8·kNN·유사 과제 · `rr_delta_priors` · `risk_add_finding` · `/api/precedents`.
- **학습**(P6) — `learning`(라벨·조건 DSL·백테스트·패턴 승격) · `metrics`(코퍼스 전체 1회 계산) · `nightly`(00:30 재합산·채굴·근접 중복 스캔) ·
  `bootstrap_{ra_ontology,adh}.py`.
- **경계** — `identity`(되묻기+TTL 캐시) · `visible_projects` 투영 · `_user_credentials` Fernet 암호문 · `ra_client`/`adh_client` 의 `withheld`+보류 op.

지금 얻는 것 — 과제 등록부터 스냅샷·비교·패널 심사·등록부 누적·다음 과제 브리프 되먹임까지의 폐루프가 앱 DB 안에서 돈다.
아직 못 얻는 것 — 실소스 자격(B1~B6)이 없어 통과 기준 상당수가 합성 픽스처로만 채워져 있고, 필드·VOC 근거(E10)와 라벨 자동 유입은 비어 있다.
