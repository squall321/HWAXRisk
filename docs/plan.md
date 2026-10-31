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
| §2.5.3 · §2.13.5 | ODB 허브 어댑터 — 지금 도구·발견·두 단계·필드·표지(1단계, 2026-10-31 개정) | `docs/odb-adapter-contract.md` · `adapters/ecad.py` |
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
                                /apps/hwax_risk/mcp       MCP ──▶ 게이트웨이  ODB hub     odb-hub           (ecad, 1단계)
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
  `GET /targets/{key}/brief` 가 발급한 `brief_token` 으로만 200 이다. 그 토큰의 쓰임은 결과 제출뿐이라, 제출을 받을 수 있는 신원
  (게이트웨이 위임으로 확인된 그 패널 소유자)에게만 열고 그 밖은 동결·패널 품질 쓰기 전에 `delegation_required`·`E404` 다(RV-1).
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
  (로컬 dev 는 리포의 `.mcp.json` 과 같은 `http://127.0.0.1:8000/mcp`). 직접 등록은 **읽기 전용**이다 — 쓰기·결과 제출·사람 finding·
  브리프 수신은 게이트웨이 위임으로 확인된 신원만 받아(`entry.require_delegate`) 게이트웨이(hwax) 경유로만 된다(RV-6).
- 실행 등급 둘 — L1 단발은 `hwax-deliberate` 에 `chairTemplate:'risk-review'`(원장 미연동), L2 는 포털 워크플로 `hwax-risk-review`
  (`{targetKey, tier, panels?, actor?, model?}`)가 `risk_get_brief` → 패널별 심의 → `risk_submit_panel_result` 로 돈다. 자세한 표는 `README.md`.
  Tier A 대표 패널과 무인 배치는 웹 러너 전용이라 `risk_get_brief(target_key, tier:'A')` 는 `{error:'tier_a_web_only'}` 다.

## REST

- base `/apps/hwax_risk/api`(앱 내부 `/api`, `backend/app/routes.py`), 모든 핸들러는 `Depends(identity.current)`. 정본 §8.2.3 의 경로를 포함해 **97개**가 배선돼 있다(2026-10-31 실측 — 재설계 M2 · M3 와 ECAD · 백로그 경로 · 키 대장 읽기 포함).
- 신원·메타 — `GET /health {ok, app_version, schema_version}` · `GET /me`(+`box{hostname, secrets_valid, cred_key_present}`) ·
  `PUT /me/portal-pat {pat|null}`(익명 401, 422 6종) · `GET /meta/{taxonomy, adapters, vocab, metrics}` · `POST /meta/metrics/recompute`.
- 과제·소스·스냅샷 — `projects`(생성·조회(목록 · 상세는 구성원도 — 메타 열 · 멤버 · 내 역할)·`PATCH`(lifecycle·등급·`mcp_visibility`)·멤버·이양·폐기·감사·유사·dims·요구·`iface-ledger`) ·
  `sources`(같은 원천이 붙은 내 다른 과제(폐기 과제 제외)는 `duplicate_of` 로 알림) · `snapshots`(조회 — 상태는 지금 살아 있는 게이트 ack · `gates_hash` 를 얹는다·게이트 ack·`rule_hits`) · `sameas`(조회 — 답 머리에 `pair_key`·`decide` — 확정을 뒤집는 결정 · `merge_key` · 계면 별칭 철회
  `revoke_iface_alias` 는 같은 트랜잭션에서 키 전파 `rekey` 를 돈다, §5.9.5 · 병합된 키의 `confirm_key` 는 409 `key_merged`) · `part-keys/{ckey}`(키 대장 한 행 — 주인 · 그 키가 든 과제의 구성원, `mine` 은 내 원장 행인가 — 아니면 결정은 404) · `diffs`.
- 심사 — `targets`(브리프·커버리지(패널 잡의 `signal` · 도는 패널마다의 `signals`)·편성 `jobs`(`exclude_evidence` — 브리프 항목 빼기)·`refresh_roster`·`resync`·`findings`(mechanism · domain 은 택소노미 어휘)·`registry`·`verdict`·`audit`(그 대상의 사람 행위 — 맨 클러스터 열쇠 행은 그 대상 소유자의 것만)) · `panels`(브리프·`complete`) ·
  `registry`(status·visibility·merge) · `findings`(수정·삭제·라벨) · `curation`(MCP 길 원자의 회수 복귀 `approve_recall` — 다른 격리가 남은 원자는 되돌리지 않고 `applied.held`) · `patterns` · `precedents` · `refs/{ref:path}`.
- 살림 — `vocab/{synonyms, stop-tokens}` · `jobs/{id}/{action}` · `GET /export` · `POST /import`(내 과제 · 스냅샷 · 대상 · 비교에 매달린 줄만 — 남의(또는 없는) 부모에 매달린 줄은 `parent_not_owned`, 남의 이메일로 적은 멤버 owner 행은 `owner_row_immutable`, 내 과제가 쓰지 않는 정규 키의 새 키 대장 행은 `ckey_not_referenced` 로 그 줄만
  눕는다 — 키 선점을 막는다).
- 구성원 읽기(2026-10-31, 사용자 결정 '계획서대로') — 과제에 딸린 읽기 전부(스냅샷 · 대상의 진행판 · 등록부 · 패널 · 보고서 · 셀 · 전문가 ·
  성격 · 유사 · 요구 · 비교 · 대응표 · 선례 · 참조 · 목록 셋)를 편집자 · 보기가 주인과 같은 답으로 연다(그 과제 주인의 행을 고른다 — 남은
  없는 것과 같은 404). 비교는 두 과제를 다 읽어야 한다. MCP 읽기 도구도 같은 판정이다(context-notes MB-1 ~ MB-7).
- 편집자 쓰기(2026-10-31, 사용자 결정 '계획서대로 편집자도 쓴다') — 계획(§8.2.3 · §0.6)이 편집자에게 연 쓰기(소스 · 동결 · 치수 · 요구 ·
  계면 원장 · 게이트 ack · 대응 결정 · 비교 · 대상 · 명단 · 잡 · 판정 · 등록부 status · 병합 · 철회 · 패널 결과 · 브리프 · 라벨)는 그 과제의
  편집자 이상(관리자 포함)이 한다 — 행은 과제 주인의 원장이고 사람 칸 · 감사 행위자는 부른 사람, 보기는 403 `role_insufficient`, 남은 없는
  것과 같은 404. 멤버 · 이양 · 폐기 · `mcp_visibility` · 재동기 · 큐레이션 · 완결 확인 · ECAD 보드 · 등록부 공개 토글은 주인(· 관리자)만, 사람
  finding 고치기 · 지우기는 작성자 또는 과제 주인이다. 대응 결정(confirm · reject)은 pair_key 의 과제(pair 는 둘 다)의 주인 · 편집자만이고
  그 과제 주인의 원장 행이며 다른 사람의 행이 있는 자리는 409 `sameas_row_foreign` 이다. MCP 쓰기 도구도 같은 문이다(context-notes MB-13 · MB-14).
- 이양과 두 과제에 걸친 것(2026-10-31, 사용자 결정 '둘 다 받은 사람에게 옮긴다') — 비교(변경 항목과 함께)와 대응 원장(intra · pair)은 모든 쪽
  과제가 받는 사람에게 모이면 그 사람의 행이 된다(한쪽만 넘어간 것은 만든 사람의 행 — 두 과제를 다 읽는 사람이 연다). 키 원장은 옮기지
  않는다(context-notes MB-15 · MB-7).
- 사람 조작 감사(2026-10-31, 사용자 결정) — `jobs/{id}/{action}`(MCP `risk_job_action` 도 같은 함수) · `registry/{cluster}/status` ·
  `targets/{key}/verdict` 는 rr_audit 한 행씩(`job.pause|resume|cancel` — 잡 행을 바꾼 조작만 · `registry.status` — 바꾼 대상 행마다
  '<대상>#<클러스터>' · `verdict.final` — 확정마다)을 남겨 대상 감사와 통합 보고서 '사람 개입 요약' 에 선다. 행에는 코드 어휘(상태 · 보류 코드 ·
  상태 기록 seq · 판정 값)만 싣고 사람이 쓴 글(note · evidence_ref)은 싣지 않는다. 코드가 일으킨 전이(일일 상한 · 코드 보류 · 자동 재개 …)는
  남기지 않는다. 포털 화면의 '멈춤'(엔진 쪽 멈춤 A24)이 잡을 멈추면 엔진이 알린 그 사람의 `job.pause`(actor_verified 0 · web)다. 감사 행은 전이와
  한 트랜잭션이다(취소도 — 전문가 보고서 다시 짓기보다 먼저) — 근거는 `../context-notes.md` AU-1 ~ AU-11.

## 외부 반영 — RA 보내는 쪽 · 거두기(RK-01, 2026-10-31)

사용자 결정 10-31(포털 docs/request-1027 RK-01 D-1 (가)) — 지식 그래프 op 는 **박스 쓰기 PAT(`HWAXRISK_PORTAL_PAT_RW`, OB-18) 하나**로
RA 에 쓴다. RA 에 적히는 주인은 그 PAT 의 계정이고 누가 했는지는 앱 DB 의 `owner_sub` 가 맡는다. 종합 보고서는 지금처럼 사람 이름(포털 챗 PAT 길)이다 —
박스 PAT 클라이언트(`ra_client_from_settings`)의 계약은 지식 그래프 쓰기 4종 + 읽기 4종뿐이고 보고서 도구는 계약 밖이다(`test_no_write_tools` 가 지킨다).

- 자리 — `ra_client.RaSender`(쓰기 4종의 이름이 나오는 유일한 모듈) → `main.py` 가 `RiskRunner(external_sync_send=…)` 로 꽂는다 → `sync_loop`
  60초마다 `nightly.retry_external_sync`. 키는 틱마다 다시 읽는다(넣으면 재기동 없이 켜진다). 사람의 등록 PAT · 읽기 PAT 는 쓰지 않는다.
  한 틱은 대상 50개 · 30초까지이고 러너의 정지 신호를 대상마다 본다(남은 대상은 상태 그대로 다음 틱) — 같은 루프의 PAT 폐기 대조가 밀리지 않게.
- 번역 — `merge_object`(risk_finding · design_trait)는 `rr_id_map` 의 id 가 살아 있으면 get_object → 병합 → update_object, 없으면 code 로
  create_object(같은 code 면 RA 가 있는 것을 돌려준다). `link` 는 link_objects — verified_by · refuted_by 의 dst 는 근거 `inc:<RA 객체 id>` 가
  사고 · 시험일 때만(아니면 잇지 않고 건수 · 까닭을 남긴다), exhibits 의 src 는 과제(project, code = 과제 id). id 는 `rr_id_map`(RA 칸만)과
  원본 표의 `ra_entity_id`(rr_projects · rr_registry)에 적는다. risk_finding 의 단위는 등록부 행이다(code `<target_key>#<cluster_key>`).
  라벨의 병합 op 는 머리에 label_id 를 실어 라벨마다 다르다(큐가 줄이지 않고 보내는 도중에 붙은 op 를 complete 가 지우지 않는다). risk_finding
  의 status 는 op 에 적힌 라벨 때의 값이 아니라 **보낼 때의 등록부 값**이다(원칙 3) — 따로 둔 op 를 재동기로 늦게 보내도 새 값을 덮지 않는다.
- RA 계약 — 도구는 게이트웨이 별칭 `reportarchive_<이름>`, 인자는 RA MCP 의 것(get_object(type, id) · update_object(object_id, …)). value 에
  code 를 꼬리로 단다(plan §5.3.1 의 꼴은 축 안 유니크가 아니다). 돌려받은 객체의 code 가 다르면 쓰지 않는다(value_collision). 게이트웨이가
  가린 값(`[가림:…]`)은 되쓰지 않는다 — 앱이 쥔 칸(owner 등)은 앱 값으로, 모르는 칸이 가려졌으면 그 op 를 보내지 않는다(masked_readback).
- 보류 · 실패 — 과제가 조직 공개가 아니면 아무것도 부르지 않고 `withheld`(op 는 큐에 그대로). 거두기 op 만은 예외다(아래). 가시성 · 폐기는 틱 머리와 **호출마다** 다시
  본다 — 보내는 도중 비공개로 돌리면 다음 호출부터 하지 않고 남은 op 는 보류다. 폐기면 남은 보낼 op 를 버린다(부르지 않고 큐에서 뺀다 —
  'RA 에 잇지 않은 것' `project_purged` 로 센다, 폐기 뒤에는 RA 에 새로 보내지 않는다). 폐기로는 대상을 멈추지 않는다 — 멈추면 폐기가 쌓은
  거두기 op 까지 멈춘 큐에 갇힌다(RK-01 거두기 반대 검토). 대상 · 과제 행이 없으면 `rejected` 로 멈춘다. `transient`(전송 · 5xx · 기한 · 백엔드 불통)만
  백오프로 다시 보낸다(그 틱의 남은 대상은 미룬다). 채널 전체가 막히는 실패(`unauthorized` · `read_only` · `forbidden` · `tool_missing` ·
  `ontology_missing` · 게이트웨이의 그 밖 4xx · JSON-RPC 오류)는 곧바로 `unavailable` 이고 실패한 op 와 그 뒤 op 는 큐에 남는다(last_error
  `<낱말>: <글>`). **op 하나에만 걸린 영구 거절**(RA 의 거절 — 관계 축 제약 · enum · 길이 · 닫힌 축, `value_collision`(값 바꾸기의 겹침 포함) ·
  `masked_readback` · `id_mismatch`(거두기 — 남의 객체) · 꼴이 틀린 op)은 그 op 만 `dead_ops`(op · 까닭 · 시각)로 따로 두고 대상의 나머지 op 를 계속 보낸다. '재동기' 가 멈춘 채널을 되살리고 따로
  둔 op 를 큐 앞으로 되돌린다(원래 순서). 멈춘 대상 · 따로 둔 op 는 틱마다 경고 한 줄씩 로그에 남긴다(사유 낱말과 수).
- 요약 계약(`sync_summary` 의 `ra.reason`) — `withheld` · `sent` · `credential_missing:HWAXRISK_PORTAL_PAT_RW`(꺼짐) · `unauthorized` ·
  `read_only` · `forbidden` · `tool_missing` · `ontology_missing` · `masked_readback` · `value_collision` · `rejected` · `transient` · `queued` ·
  `idle`. `message` 는 늘 사람이 읽을 글이다. `dead_ops` 는 따로 둔 op 의 건수다 — `reason` 이 `sent` 여도 0 이 아니면 RA 에 가지 않은 것이
  있다(화면은 경고로 그린다). RA 채널에는 거두기 셈(객체 수) — `retracted`(지금 거둔 꼴) · `retract_absent`(거두려니 RA 에 이미 없었다) ·
  `retract_pending`(비공개 · 폐기로 쌓인 거두기 op 가 큐에 있다) · `retract_failed`(RA 가 받지 않아 따로 뒀다) · `retract_reasons`(못 거둔 것의
  까닭 낱말별 수) — 이 늘 실린다. 한 객체는 한 칸에만 든다 — 폐기 보고서와 같은 차례(대기 > 못 거둠 > 거둠 > 없음)다. AIDataHub 는 보내는
  쪽이 없어 `sender_unwired` 그대로다(M4).
- 원칙 9(투영 범위 = 정본 범위)는 나가기 전에는 보류(`withheld`)로, 나간 뒤에는 거두기로 지킨다(사용자 결정 10-31 (가) — 거두기 op). 거두기
  op 는 보류 · 폐기에 갇히지 않고 앞선 보내기의 재시도 백오프도 물려받지 않는다 — 비공개 · 폐기 다음 동기 주기에 나간다. RA 가 객체를 지우지
  못해(아래) 지켜지는 것은 **앱이 투영한 내용**까지다 — 내용 없는 껍데기와 연결, RA 에서 따로 단 속성은 RA 에 남는다.
- 거두기(RK-01 거두기) — 과제를 비공개로 돌리거나 폐기 · 이양하면 RA 에 나간 객체(과제 · 등록부 risk_finding — `rr_id_map`, 없으면 원본 표의
  `ra_entity_id`)마다 거두기 op(`{op: retract, reason: private|purged|owner|org, kind, portal_id, project_id, by}`)를 큐 끝에 쌓는다 — 앞에 쌓인
  보낼 op 다음이고 같은 꼴은 한 번만이다. 거두기 op 는 보류 · 폐기를 건너뛰고(보류된 대상도 동기 주기가 집는다 — 폐기된 과제의 보낼 op 는
  버린다) 문(호출마다 보는 가시성)도 지나지 않는다. 거두기(비공개 · 폐기)를 쌓으면 그 대상을 다음 동기 주기에 집히게 한다 — 앞선 보내기의
  재시도 백오프(최대 6시간)를 물려받지 않고, transient 로 재시도를 다 써 멈춘 대상도 한 번 되살린다(또 실패하면 종전 백오프 · 멈춤). 다시
  표기할 꼴은 op 가 아니라 **보낼 때의 정본 범위**로 고른다(원칙 3) — 조직 공개가 아니거나 폐기면 거둔 꼴(값 `비공개@<code>`, 과제 설명은
  비우고, risk_finding 은 앱의 투영이 채운 칸 `RETRACT_DROP_KEYS` — owner · status — 를 빼고 visibility=private · 되짚을 열쇠 둘을 쓴다. RA 에서
  따로 단 속성은 둔다 — 게이트웨이가 가려 읽힌 것만 뺀다, 되쓰면 가린 글이 원본을 덮는다. 뺀 칸은 감사 행의 `dropped`), 조직 공개면 나간
  꼴(값 · 과제 설명 · owner · visibility=org · 보낼 때의 등록부 status). 그래서 이양은 owner 를 새 소유자로 다시 표기하고(비공개면 거둔 꼴
  그대로), 다시 조직 공개로 열면 보류된 op 가 순서대로 나간 뒤 거둔 객체(RA 에 없던 것 포함)가 나간 꼴로 돌아온다(reason org). 닫거나 여는
  순간 RA 호출이 나가 있었으면 그 결과는 큐를 쌓은 뒤에 적히므로 보내는 쪽이 결과를 적을 때 뒤따라 쌓는다 — 닫힌 과제는 거두지 않은 객체에
  거두기 op, 열린 과제는 그 대상에 거둔 꼴로 남은 객체에 다시 표기 op(따로 둔 것은 다시 쌓지 않는다 — 재동기를 기다린다). 사상된 id 의
  객체 값이 `@<code>` 로 끝나지 않으면 남의 객체라 쓰지 않는다(`id_mismatch` — 다른 박스에서 들여온 사상 · RA 에서 바뀐 값). 거두기 op 마다
  (나갔거나 따로 둔 것) rr_audit 한 행(`ra.retract` · `ra.remark`, 행위자는 그렇게 한 사람 — 뒤따라 쌓은 것은 과제를 닫거나 연 사람(폐기
  보고서의 `by` · `mcp_visibility_by`), 모르면 `system` 을 검증되지 않은 행위자로). 채널 전체가 막히는 실패에는 다른 op 처럼 멈추고 재동기를
  기다린다.
- RA 가 허락하는 것(dev 사본 3ece194) — MCP 온톨로지 쓰기는 create · update · alias · link 넷뿐이고 시스템 관리자 전용이다. 객체를 지우거나
  연결을 끊는 도구가 없고, `update_object` 는 value · code · description · properties(통째 교체, 빈 값은 저장하지 않는다)만 넘긴다 — 엔티티
  상태(deprecated)는 넘기지 않는다. 엔티티에 공개 범위 열은 없다 — visibility 는 이 앱의 부트스트랩이 risk_finding 에 단 속성이고 과제 축
  (RA 기존 축)에는 없다. 그래서 거둔 뒤에도 객체 자체 · 연결(exhibits · verified_by · refuted_by) · 성격 태그(design_trait — 과제를 가로지르는
  어휘)는 남는다. 계획 정본 §5.2.6 4층의 `update_object(status='retracted')` 는 RA 가 받지 않는다(MCP 가 상태를 넘기지 않고 risk_finding
  status enum 에 retracted 가 없다) — 정본 글은 포털 몫이다.
- 폐기 보고서의 RA 층(`remaining`) — `reason` 은 `nothing_sent` · `retract_pending` · `retract_failed` · `retracted`(다 거뒀거나 RA 에 이미
  없다 — 종전의 `not_retracted` 를 갈음한다)이고 `objects`(나간 객체) · `retracted`(실제로 거둔 꼴로 바꾼 것) · `absent`(RA 에 이미 없어 거둘
  것이 없던 것) · `retract_pending` · `retract_failed` · `reasons`(재시도 대기 · 멈춘 채널 · 못 거둔 객체의 까닭 낱말별 수)를 싣는다. 글은
  기다리는 거두기가 언제 나가는지를 채널 상태로 말한다 — 다음 동기 주기 · 재시도 대기(저절로) · 멈춤(고친 뒤 재동기). 폐기 응답 때는 아직
  보내기 전이라 대기이고, 동기 주기가 거두기 결과를 적을 때마다 `purge_report_json` 의 그 층을 다시 짓는다.
- 남은 것 — 패널 때 쓰는 투영(risk_finding 의 나머지 속성 · assessment · snapshot · diff, plan §5.3.5 쓰기 순서 ①~⑧)과 AIDataHub 반입은 M4 다.

## 구현 범위(현재 P6, 이 리포 몫)

단계별 상태와 잔여 백로그의 정본은 이 리포 `checklist.md` 다. 여기서는 계층만 적는다.

- **계약** — JSON 스키마 5종(draft-07, 최상위만 `additionalProperties:false`)·자산 JSON 6종(`backend/app/assets/`)·ODB 어댑터 계약 문서·§5.2.2 DDL 41표.
- **캡처·IR**(P1·P2 · ECAD 1단계) — `adapters/{base,registry,mcad,dyna,ecad}` 가 소스 앱을 읽기 전용으로 열고 `ir_builder` 가 rr_ir 봉투를 동결한다.
  표기층 위생·인젝션 어휘(`render.sanitize_source_text`·`INJECTION_LEXICON`)가 원문을 «…» 안에 가두고 적중분은 `suspect_text` 큐로 보낸다.
- **상태·비교**(P1·P2) — `state`(G1~G7·signals·`character_seed`·`feature_vector`·`rule_hits`) · `sameas`(사다리 7단·헝가리안·원장 재적용) · `diff`(3층·의미 이벤트·`comparability` 5키).
  2026-10-31 — §2.6.3 의 6단계 상한(남은 노드 곱 > 800×800 또는 배정 행렬 변 > 1,600 이면 헝가리안을 건너뛰고 degraded · 경고 ·
  `sig:capture.fuzzy_skipped` · 쌍 caveat — 변 상한은 정본에 없는 앱 결정, BL-6)과 §2.5.1 · §3.3.6 의 계면 절단(`stats.interfaces_truncated{kind:n}` ·
  잘린 kind 의 엣지 · 파라메트릭 · 명명 치수는 `excluded_reason='truncated'`, 롤업은 kind 별, 고아 전이는 `orphans_delta.truncated`)이 코드에 섰다.
  노드 500 · 엣지 2,000 diff 는 0.2 s · 피크 20 MB 다(§10 #27 — `memory_gb 2` 그대로). 근거는 `../context-notes.md` BL-1 ~ BL-3 · BL-6 ~ BL-9.
- **서술·등록부**(P3) — `brief`(E0~E10) → 심의 → `narrative`(risk_spec 파싱·cites·`evidence_grade`·좌석 의견) → `registry`(병합·별칭 체인·status 이력·기각 보존).
  `rekey`(§5.9.5) — 원장 확정이 뒤집히면(그리고 `merge_key` 면) 영향 원자의 주체를 지금 원장으로 다시 세어 원장 별칭을 맞추고 등록부를 다시 병합한다
  (거둘 별칭을 다 거둔 뒤 세운다 · 재매핑 별칭은 그 끝에 이어 붙인다 · 별칭 사슬로만 닿는 대상도 다시 병합한다 · 맞춘 뒤 앞 키의 사슬도 5홉 점검).
  쓰는 `registry.merge` 는 읽기부터 한 트랜잭션이고, 접혀 닫힌 행(`registry.vacated`)은 주의 D 로 닫혀 클러스터를 세는 곳이 건너뛴다.
  원문은 `rr_panel_calls` 에 gzip 으로 남고 `rr_panels.brief_gz` 로 브리프 자체가 재현된다.
- **편성·회계**(P4) — `planner`(Tier A/B/C·라운드로빈·인접·deferred·carried) · `roster` · `runner` 배치 · 완결 레벨 C1~C3 · 통합 보고서.
- **재사용**(P5) — `brief` 의 E5+/E5−·E6~E8·kNN·유사 과제 · `rr_delta_priors` · `risk_add_finding` · `/api/precedents`.
- **학습**(P6) — `learning`(라벨·조건 DSL·백테스트·패턴 승격) · `metrics`(코퍼스 전체 1회 계산) · `nightly`(00:30 재합산·채굴·근접 중복 스캔) ·
  `bootstrap_{ra_ontology,adh}.py`.
- **경계** — `identity`(되묻기+TTL 캐시) · `visible_projects` 투영 · `_user_credentials` Fernet 암호문 · `ra_client`/`adh_client` 의 `withheld`+보류 op ·
  RA 보내는 쪽(`ra_client.RaSender`, 박스 쓰기 PAT 하나 — 위 절)과 거두기(`ra_client.queue_retracts` — 비공개 전환 · 폐기 · 이양 · 다시 공개).

지금 얻는 것 — 과제 등록부터 스냅샷·비교·패널 심사·등록부 누적·다음 과제 브리프 되먹임까지의 폐루프가 앱 DB 안에서 돈다.
아직 못 얻는 것 — 실소스 자격(B1~B6)이 없어 통과 기준 상당수가 합성 픽스처로만 채워져 있고, 필드·VOC 근거(E10)와 라벨 자동 유입은 비어 있다.
