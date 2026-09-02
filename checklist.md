<!-- HWAXRisk 앱 리포 작업 대장 — P0~P6 진척과 앱 몫 잔여 백로그. 포털 정본 checklist.md 에서 앱 몫만 떼어 와 실측으로 갱신한다 -->
# HWAXRisk 체크리스트

계획 정본은 `HWAXPortal/docs/design-risk-review/{plan.md, checklist.md}` 다. 이 문서는 **앱 리포가 실제로 무엇까지 했고 무엇이 남았는지**를
코드 대조로 확인해 적은 작업 대장이며, 앞으로의 진행은 이 문서를 늘려 가며 한다. 정본 체크리스트는 단계 착수 전에 쓴 것이라 P1~P7 항목이
전부 미체크로 남아 있다 — 여기서 실측한 완료 상태가 그보다 최신이다.

마지막 실측 2026-09-02 — `pytest` **1103 passed, 2 skipped**(`test_parity` 는 `HWAX_PORTAL_REPO` 미설정) · `ruff` 통과 · `pnpm build` 통과.

## 진척 요약

| 단계 | 정본 절 | 상태 | 근거 |
|---|---|---|---|
| P0 부트스트랩 | §9.1 | **완료** — 실환경 통과 기준 일부 미실측(↓ 3장) | 스캐폴드·계약·정합 A-δ, SIF 빌드·기동·게이트웨이 흡수 확인 |
| P1 IR·상태·게이트·규칙(MCAD) | §9.2 | **완료**(합성 픽스처 기준) | `ir_builder.py` · `state.py` · `render.py` · `requirements.py` · `adapters/mcad.py` · `export.py` |
| P2 Dyna·same-as·원장·diff | §9.3 | **완료**(합성 픽스처 기준) | `adapters/dyna.py` · `sameas.py` · `diff.py` · `ComparePage.tsx` · `recompute_part_keys.py` |
| P3 패널 e2e·서술 저장 | §9.4 | **완료**(엔진 실호출 미실측) | `narrative.py` · `runner.py` · `registry.py` · `character.py` · `ra_client.py` · `adh_client.py` |
| P4 커버리지·편성·배치·보고서 | §9.5 | **완료** | `planner.py` · `roster.py` · `runner.py` 배치 · C1~C3 · `GET /api/meta/metrics` |
| P5 재사용 루프 | §9.6 | **부분** — E10 필드·VOC 근거가 스텁, UI 3종 부재 | `brief.py` E5±·E6~E8 · `risk_add_finding` · `/api/precedents` |
| P6 학습 루프 | §9.7 | **부분** — 라벨 자동 유입 4경로 미구현(의도적 노출) | `learning.py` · `metrics.py` · `nightly.py` · `bootstrap_*.py` |
| P7 ODB 실연동 | §9.8 | **미착수**(조건부 — ODB hub 계약 합의 대기) | `adapters/ecad_stub.py` 만 |

실측 규모 — 백엔드 `app/` 38모듈 25,018줄 · 프런트 `src/` 5,700여 줄 · REST 66경로 · MCP 7도구 · DDL `rr_*` 41표 + 살림 2표 · 테스트 42파일.

## 1. 앱 코드 구멍 — 지금 바로 가능한 것

착수 순서대로 적었다. 외부 자격·합의가 필요 없는 항목만 여기에 둔다.

- [x] **`x_tag_promote` 큐 결정 어휘** (2026-09-02) — `CURATION_DECISIONS` 에 `("promote", "reject")` 를 넣고
  `character.promote_x_tag(store, tag, axis, owner_sub)` 를 붙였다. 승격은 소유자의 살아 있는 진술만 통제 태그로 옮기고(대표 태그가
  없던 행은 승격 태그가 대표가 되며 그 축의 facet 을 따르고, 이미 `char:` 대표가 있으면 대표·facet 불변), 어휘 마이너 승급 값은
  결정 기록에만 남긴다(자산 파일은 앱이 고치지 않는다 — `unclassified_code` 관례). 승격된 태그는 `design_trait`+`exhibits` op 로 RA 에
  올라간다(§5.4 ⑦ — `x:` 는 승격 전 미연결). 축은 코드가 못 고르므로 `payload.axis` 없으면 422 이고 큐는 열린 채다.
  회귀 가드로 'DDL 이 허용한 kind == 결정 어휘 == 감사 scope' 를 시험으로 고정했다.
- [x] **`character-vocab.v1.json` 이 정본과 어긋나 있었다** (2026-09-02, 위 작업 중 발견) — 자산에 `char:constraint` 축이 통째로 없고
  `char:analysis` 가 5값이었다(정본 plan §4.6.3 블록은 8축·8값). 그래서 씨앗이 내는 `char:analysis:sim_only`·`ecad_only`
  (`character.py` `SOURCE_ABSENT_SEEDS`)가 `narrative.py:1046` 어휘 검사에서 **어휘 밖으로 판정돼 `x:sim_only` 로 강등**되고
  `x_tag_promote` 큐를 채우고 있었다 — 통제 값이 자유 태그 후보로 되돌아오는 고리다. 자산을 정본 블록과 바이트 동일하게 맞췄다.
- [x] **어댑터 발견 배선** (2026-09-02) — `list_adapters()` 고정 목록이 mcad 를 늘 `planned` 로 적어, 캡처는 도는데도
  소스 카드가 '연결 안 됨' 이라고 거짓말하고 있었다(`capture_all` 은 probe 상태를 보지 않는다). 이미 구현돼 있던
  `GatewayRegistry` 를 `discover_adapters(token=, force=, client=)`(60 s 캐시)로 감싸 `GET /meta/adapters` 와
  `POST /projects/{id}/sources` 에 이었다. 실측 — mcad `heax-step_forge` **ready** · dyna `heax-kooremapper_mcp` **ready** ·
  ecad 는 도구 4종이 없어 `contract_only`. 소스 등록이 `status='linked'` 를 적는다. 게이트웨이를 못 읽으면 `planned` +
  `gateway_error` 로 남긴다 — '도구가 없다' 와 '못 물어봤다' 를 섞지 않는다.
  `choices[]`(StepForge 프로젝트 선택지)는 소스 앱 도구 실호출이라 포털 PAT 가 선행한다 — 아직 빈 배열이고 사용자가 ref 를 직접 적는다.
- [ ] **E10 필드·VOC·문헌 근거가 스텁이다.**
  `brief.py:688 _field_evidence_lines` 가 제품 연결 유무만 보고 늘 `[필드·문헌 근거 없음 …]` 한 줄을 낸다. 정본 §5.6.1 E10·§6.5.2 가
  요구하는 것 — `get_top_issues`·`query_voc`·`search_scholar` 실호출을 러너가 하고 `rr_panel_calls(source_kind='brief')` 에 저장해 24 h
  재사용 · `voc:`·`paper:` 참조와 등급 매핑(§0.2.1 (5)) · `GET /refs` 해석 · `taxonomy.v1.json` 의 `voc_map` 시드 12행(현재 `[]`) ·
  `evidence_profile.field`. 지표 `field_evidence_rate`(`metrics.py:43`)는 이미 있으나 분자가 항상 0 이다.
  → 검증: 제품 연결된 타깃에서 E10 ≤5줄·`voc:` 인용이 `GET /refs` 200·미등록 타깃은 결측 1줄, 항목 수 12·드롭 0
- **프런트 화면** — REST 는 있는데 사람이 쓸 입구가 없던 것들.
  - [x] `CurationQueuePage.tsx`(`#/curation`) (2026-09-02) — kind 6종의 열린 항목을 사람이 결정한다. 결정 어휘는 서버
    `CURATION_DECISIONS` 와 같은 집합이고 그 사실을 시험으로 고정했다. 값을 더 받아야 하는 결정(`x_tag_promote` 의 `axis`,
    `unclassified_code` 의 `mechanism_detail`)은 빈 값이면 버튼이 잠긴다. 승격 축 선택지는 `GET /meta/vocab.promotable_axes`
    로 서버가 준다 — 통제 어휘를 화면이 따로 갖지 않는다. 성격 승격 UI(아래 항)가 여기 안에 함께 들어갔다.
  - [x] `CoverageHeatmap` — 이미 `TargetPage.tsx` 안에 있었다(앞선 조사에서 대소문자 때문에 못 찾았다). 셀 클릭 드릴다운이
    부르던 좌석 경로가 없어 죽어 있던 것이고, 위 계약 정리로 살아났다.
  - [ ] `TargetPage` '리스크 직접 등록' 폼 — `POST /targets/{key}/findings` 의 UI 짝(작성자만 수정·삭제)
  - [ ] `TargetPage` '브리프 토큰 복사' 버튼 — L2 워크플로가 `briefToken` 없이는 앱을 못 부른다
  - [ ] `ProjectPage` '사전' 탭 — `POST /vocab/synonyms`·`stop-tokens` 와 재계산 필요 배너
- [ ] **라벨 자동 유입 4경로 미구현**(RA incident · test_run · DynaForge · VOC). 야간 ①·⑤(`metrics.sync_labels`·`refresh_fv_stats`)가
  비어 있고 `run_nightly()['unwired']` 와 `rr_metrics(label_ingest_wired)` 배지로 드러내는 중이다 — 숨긴 게 아니라 학습 루프의 분모가
  아직 사람 라벨뿐이라는 뜻이다. 경로 1·2 는 RA 게이트웨이 읽기, 3 은 러너 자격 (b), 4 는 `product_code` 조건이 선행한다.
- [x] **`ruff` 설치** (2026-09-02) — `pip install -e ".[test]"` 재실행. `ruff check .` All checks passed.
- [x] **로컬 `frontend/dist` 재빌드** (2026-09-02) — `pnpm build` 통과(`tsc -b && vite build`).
- [x] **프런트↔서버 계약 표류 9건 정리** (2026-09-02) — 클라이언트 호출과 `@router` 를 기계로 대조하다 죽은 경로 2종을 찾았고,
  이어 응답 모양까지 전수 대조하니 7건이 더 나왔다. 정본(§8.2.3 응답표·§8.2.4 화면표)이 판정 기준이었고 대부분 **서버가 맞고
  클라이언트가 낡아** 있었다.
  - 서버에 더한 것 — `GET /panels/{id}/transcript`(§8.2.4 `PanelTranscript` '발언' 탭) · `GET /targets/{key}/seats?domain=`
    (`CoverageHeatmap` 셀 클릭 드릴다운) · `registry_payload` 의 `verdict_final`(헤더가 후보·확정을 한 응답에서 읽는다)
  - 클라이언트를 서버에 맞춘 것 — `getAdapters`(`{apps}` 봉투·`app_key`) · `getPanels`·`getRuleHits`·`getSnapshotCalls`·
    `getSeats`(봉투) · `getCharacter`(`facets`→`layers` 3층) · `getSimilar`(`by_source`→회수 경로 4종)
  - 회귀 가드 — `tests/test_client_contract.py` 가 클라이언트가 부르는 모든 경로의 서버 존재를 검사한다(경로 하나를 지워
    실제로 실패하는 것까지 확인했다). 응답 모양은 TypeScript 가 잡는다 — 봉투를 고치자 `tsc` 가 깨진 소비처 20곳을 그대로 짚었다.
- [ ] 백테스트 표본 재설계(§7.5 정본 결정 대기) — train 구간에서만 범위 산출 · 라벨 없는 심사 타깃을 관측 음성으로 편입 · 홀드아웃 최소 표본.
  계획이 표본 우주를 정하지 않아 코드로 지어내지 않고 남겨 둔 것이다(context-notes 2026-08-31 P6 항).
- [ ] 골든 `backend/tests/golden/sif-e2e.ir.json` 부재 — 선행 B2(골든 프로젝트 재파싱)가 닫혀야 만들 수 있다(↓ 2장).

## 2. 실환경 실측 대기 — 자격·선행 조건이 필요한 것

여기 있는 것은 코드가 없어서가 아니라 **소스 앱·자격·실데이터가 없어 합성 픽스처로만 채워 둔** 통과 기준이다.

- **자격 — 정본 서술이 낡았다(2026-09-02 정정).** 정본은 B1(heax 서비스 PAT)을 '최대 단일 레버' 로 적었지만 커밋 `37b9c3b` 이
  그 레버를 이미 뺐다 — **사람이 시작한 캡처는 호출자 본인의 heax 토큰으로 StepForge REST 를 읽는다**(대리 읽기, 읽기 전용,
  권한 확대 없음). 지금 실제로 필요한 것은 셋으로 갈린다.
  - [x] STEP 읽어 스냅샷 동결 → 게이트·규칙 — **추가 자격 0**(로그인만). 코드 준비됨
  - [ ] 패널 심의(LLM 좌석) — 사용자가 SettingsPage 에서 **포털 PAT 1개** 등록(`resolve_credential` 의 (b) owner 자격).
    `cred.key` 는 배포 박스에 있어 등록은 지금도 된다
  - [ ] 무인 배치(야간 러너)·RA/ADH 쓰기 — `secrets.env` 서비스 키(현재 파일 자체가 없다)
- [ ] **B2 골든 `sif-e2e` StepForge 재파싱·재검출**(§10 #15, 사용자 실행) — 미실행이면 첫 캡처가 `volume_null_pre_d168` 확정
- [ ] **B4 실무 규모 STEP 1건 업로드** · **B5 DynaForge 세션·K파일·리포트 각 1건**(P2 (8)(9) 선행) · **B6 `heax-materialtwin_web` 기동**(§10 #41)
- [ ] `var/app_data/hwax_risk/secrets.env`(0600) 5키 — `HWAXRISK_PORTAL_PAT`(scopes read) · `HWAXRISK_PORTAL_PAT_RW` · `HWAXRISK_HEAX_SERVICE_PAT` ·
  `HWAXRISK_AIDH_API_KEY` · `HWAXRISK_CRED_KEY`(Fernet) → `redeploy-app.sh hwax-risk`. 현재 `cred.key` 만 있다
- [ ] `bootstrap_ra_ontology.py --base <RA> --apply`(env `RA_ADMIN_PAT`, §10 #1 승인 선행) · `bootstrap_adh.py`(§10 #10 확인 선행) 1회 실행
- [ ] 통과 기준 실측 — P0 (4) StepForge 직접 읽기 · (9) 러너 자격 3항 · (16) app-data 왕복(`appdata-to-drive.sh` → 복원 `integrity_check ok`) ·
  (17) 신원 해석 라이브 · (18) 자격 최소 권한·암호 보관 4항
- [ ] P3 엔진 실호출 실측 — 포털 `/agent/chat` 경로 (A) 로 패널 1건 완주 · SSE 귀속 ≥95% · 도구 사용률 ≥80% · IR 인용 ≥50%
- [ ] 성능 실측 — 500·2000 diff <5 s + RSS 피크 기록(§10 27) · 500파트 캡처 ≤10 s

**이미 실측된 것**(다시 하지 않는다) — SIF 빌드·기동·Caddy 라우트·게이트웨이 `heax-hwax_risk` 자동 흡수(`POST /mcp` 200 · `tools/list` 응답,
`var/logs/integration_hwax_risk.log`) · `var/app_data/hwax_risk/` 생성과 DB 지속 · 로컬 기동 3점.

## 3. 이 리포 밖 — 포털·엔진 몫

앱 코드는 손대지 않지만 앱의 통과 기준이 여기에 걸려 있다.

- [ ] 포털 `delibTaxonomy.ts`(JobId·JOBS 8행째·JOB_ROUTING·suggestJob) · `conversations.api.ts` ConvKind · `agent/routes.py` `ConvCreate.kind`
- [ ] agent-server `GET /health` 에 `sampling{temperature, top_p, max_tokens, seed?}` 1키 additive — 없으면 앱은 `sampling=null` 로 진행한다(막히지 않음)
- [ ] `delib_metrics.py` 에 risk_spec 파싱 성공률 1종
- [ ] `HWAXPortal/infra/pipeline/hwax-risk-review.js` args 에 `briefToken` 필수화(§6.11) + `sync-workflows.sh`
- [ ] `check_chair_parity.py` exit 0 확인 — 되면 이 리포 `test_parity.py` 가 skip 에서 실검사로 바뀐다

**HEAX 플랫폼 쪽 알림**(앱 버그 아님) — 헬스 프로브가 `/apps/hwax_risk/apps/hwax_risk/api/health` 로 접두를 두 번 붙여 404 를 3,756회 냈다
(200 은 0회). `materialtwin_web`·`web_design_agents`·`voice_recorder` 로그에도 같은 이중 접두가 있어 플랫폼 공통 문제다. 앱은 정상 기동 중이다.

## 4. P7 — 조건부, 미착수

- [ ] `adapters/ecad.py`(계약 4도구, `registry.py` 도구명 발견) · ir_version 1.1(`MIGRATIONS` v2) · refdes↔파트 사전 UI · `ecad.*` 이벤트 · SedInput 어댑터
- [ ] 예측기 HEAX 앱 계획서(별도 리포·매니페스트, 라벨 원천 `GET /api/export`) — 활성화 게이트 `n_labeled ≥50`·`project ≥15`
- [ ] 선행(§10 9·14a) — ODB hub 계약 합의, 명명 규칙. 그전에는 `ecad_stub.py` 가 `discover` 만 하고 `capture` 는 빈 결과 + `ecad_absent` 다

## 5. 운영·이관

- [ ] dev crontab `appdata-to-drive.sh` 일 1회(기본 03:30, RETAIN 5) — `secrets.env` 제외 패턴 additive(§10 #18 ② 승인 대기)
- [ ] cae00 이관(§8.4.4 6, P3 실측 통과 뒤) — `build-all-to-drive.sh` → cae00 `dist-from-drive.sh` → 자격 재발급 → `redeploy-app.sh hwax-risk`.
  이후 dev→cae00 은 `GET /api/export` → `POST /api/import` 만

## 6. 정본에 남은 사용자 결정

포털 `checklist.md` '착수 전 — 사용자 결정' 절의 미결 항목 중 앱 동작을 바꾸는 것만 옮겨 적는다. 코드는 각 항의 **기본값**으로 이미 돌고 있다.

- [ ] #17 MCP 쓰기 귀속 — `actor` 미검증(`actor_verified:false`) 유지 vs 게이트웨이 `x-hwax-user` 전달 (기본 미채택)
- [ ] #18b 데이터 등급 — `confidential` 이면 조직 공개를 막을지 (현재 등급과 `mcp_visibility` 는 분리돼 있다)
- [ ] #29 과제 공유 기본값 — 명시 초대만(기본) vs 부서 자동 viewer / 열람 감사 로그 (기본 안 남김)
- [ ] #31 사람 finding 을 선례로 되먹일지 — `risk_prior_include_human` 기본 true
- [ ] #32 인젝션 위생 강도 — 자리표시자 차단(기본) vs 어휘 축소 vs 경고만
- [ ] #37 소스 응답 계약 위반 강도 — `risk_source_drift_block=false`+`caveat='parser_differs'`(기본) vs 차단
- [ ] #39 모델 상한 — `risk_max_leaf` 1500 · `risk_max_interfaces` 6000 · 예산 180 s(`allow_large` 600) 값 승인
- [ ] #5·6·7 로스터·마감 — 도메인 15 · ECAD 6 · 기본 마감 C2 vs C3 · carried 90일 · 패널 LLM 상한 120
- [ ] #33·40 브리프 예산 — 기각·반증 선례(E5−)를 다른 과제 브리프에 실을지(기본 실음, 6줄 상한) · `delib_opts.evidence` 항목 상한 12 상향 (기본 접어 둠)
- [ ] #23·24 매니페스트 확정값·리포 위치 승인 — 코드·등록은 이미 그 값으로 서 있다(`squall321/HWAXRisk`, `company`, `memory_gb 2`)

## 다음 수

1장이 외부 의존이 없어 바로 된다. `x_tag_promote` 어휘·어휘 자산 정합·CurationQueue 화면은 닫혔다. 다음은
**E10 실호출**(브리프 근거 한 축이 통째로 비어 있음)이 값이 가장 크고, 그 앞에 **죽은 경로 2종**(속기록·좌석)의 정본 결정이 있다.
2장의 자격 항은 생각보다 가볍다 — 캡처는 로그인만으로 되고, 패널까지 가려면 **사용자 포털 PAT 1개**면 된다.
서비스 키는 무인 배치를 켤 때 필요하다.

남은 UI 구멍 하나 더 — `TargetPage` 가 '좌석 상태 되돌리기 · skipped 사유 입력 경로는 아직 서버에 없습니다' 라고 적어 두었는데
`PUT /targets/{key}/coverage/{agent_key}` 는 서버에 있다(클라이언트에 함수가 없을 뿐이다). §8.2.4 가 요구하는 폼이라 다음 차례다.

## 완료 기록 — P0 (2026-08-31)

<details>
<summary>P0 스캐폴드·정합 항목(전부 완료)</summary>

- [x] 이름·경로 정본 확정(context-notes D2·D6) — 리포 `HWAXRisk` · id `hwax_risk` · Caddy `/apps/hwax_risk` · MCP `heax-hwax_risk` · REST `/api`
- [x] `backend/pyproject.toml` / `.gitignore` / `.portal/manifest.yaml` / `.mcp.json` / 문서 5종
- [x] `config.py`(§8.2.6 전 필드·데이터 루트 우선순위·`secrets.env`) · `risk_store.py`(§5.2.2 DDL 전문·`_schema_migrations`·pre-migrate 사본) ·
  `narrative.py` v0 · `taxonomy.py` · `identity.py`(되묻기+TTL 캐시) · `routes.py` · `mcp_server.py` · `main.py` lifespan ①~⑦ · `runner.py` 골격 · `cli.py`
- [x] 스키마 5종 · 자산 6종(package-data) · `docs/odb-adapter-contract.md`
- [x] `fastapi_react` 레이아웃 전환(D5) — `backend/` + `frontend/`, `pnpm build` → `frontend/dist`
- [x] P0 정합 A-δ 13항(D6) — env 접두 `HWAXRISK_` · DDL 전문 · lifespan · MCP 6종 시그니처 · 자산 이동 · 매니페스트 · identity 재작성 · 테스트 재편
- [x] GitHub `squall321/HWAXRisk` 생성·push · HEAXHub `integrations/hwax-risk/.portal/manifest.yaml` 커밋 → SIF 빌드 → 기동 → 게이트웨이 흡수
- [x] 정본 불일치 2건 해소 — DDL 표 수는 41표(정본 §5.2.2 전문 기준) · heax 불통 시 anonymous 유지(§8.2.8, context-notes D6)

</details>
