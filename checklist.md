<!-- HWAXRisk 앱 리포 작업 대장 — P0~P6 진척과 앱 몫 잔여 백로그. 포털 정본 checklist.md 에서 앱 몫만 떼어 와 실측으로 갱신한다 -->
# HWAXRisk 체크리스트

계획 정본은 `HWAXPortal/docs/design-risk-review/{plan.md, checklist.md}` 다. 이 문서는 **앱 리포가 실제로 무엇까지 했고 무엇이 남았는지**를
코드 대조로 확인해 적은 작업 대장이며, 앞으로의 진행은 이 문서를 늘려 가며 한다. 정본 체크리스트는 단계 착수 전에 쓴 것이라 P1~P7 항목이
전부 미체크로 남아 있다 — 여기서 실측한 완료 상태가 그보다 최신이다.

마지막 실측 2026-09-29 — `pytest` **1201 passed, 2 skipped**(`test_parity` 는 `HWAX_PORTAL_REPO` 미설정) · `ruff` 통과 · `pnpm build` 통과.

## 진척 요약

| 단계 | 정본 절 | 상태 | 근거 |
|---|---|---|---|
| P0 부트스트랩 | §9.1 | **완료** — 실환경 통과 기준 일부 미실측(↓ 3장) | 스캐폴드·계약·정합 A-δ, SIF 빌드·기동·게이트웨이 흡수 확인 |
| P1 IR·상태·게이트·규칙(MCAD) | §9.2 | **완료**(합성 픽스처 기준) — §2.2 봉투 승격은 2026-09-04 에 닫음 | `ir_builder.py` · `state.py` · `render.py` · `requirements.py` · `adapters/mcad.py` · `export.py` |
| P2 Dyna·same-as·원장·diff | §9.3 | **완료**(합성 픽스처 기준) | `adapters/dyna.py` · `sameas.py` · `diff.py` · `ComparePage.tsx` · `recompute_part_keys.py` |
| P3 패널 e2e·서술 저장 | §9.4 | **완료**(엔진 실호출 미실측) | `narrative.py` · `runner.py` · `registry.py` · `character.py` · `ra_client.py` · `adh_client.py` |
| P4 커버리지·편성·배치·보고서 | §9.5 | **완료** | `planner.py` · `roster.py` · `runner.py` 배치 · C1~C3 · `GET /api/meta/metrics` |
| P5 재사용 루프 | §9.6 | **완료**(합성 픽스처 기준) — E10·UI 3종 2026-09-25 에 닫음 | `brief.py` E5±·E6~E8 · `risk_add_finding` · `/api/precedents` |
| P6 학습 루프 | §9.7 | **부분** — 라벨 자동 유입 4경로 미구현(의도적 노출) | `learning.py` · `metrics.py` · `nightly.py` · `bootstrap_*.py` |
| P7 ODB 실연동 | §9.8 | **1단계 완료**(2026-10-31, 가지 `wt1031/ecad` — 보드·적층·분류된 부품) · 2단계(좌표·넷)는 ODB 허브 OH-01·OH-02 뒤 | `adapters/ecad.py` · 보드 고르기 REST·MCP(↓ 4장) |

실측 규모 — 백엔드 `app/` 38모듈 25,018줄 · 프런트 `src/` 5,700여 줄 · REST 66경로 · MCP 7도구 · DDL `rr_*` 42표(v2) + 살림 2표 · 테스트 42파일.

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
- [x] **probe 에 나이가 생기는 구멍** (2026-10-01, PAT 재발급 실측 중 발견 — context-notes D36) — 위 항이 **연결 시점**의
  거짓말을 고쳤는데 `probe_json` 은 그 한 번만 쓰이고 갱신되지 않았다. 그래서 라이브 앱은 방금 캡처가 200 으로 읽은
  소스를 네 과제 전부 `unreachable` 이라 적고 있었다 — 한 번 잰 값이 영구히 현재 사실처럼 보인다. 캡처 성공 자체가
  도달 측정이므로 `refresh_source_probes(store, project_id, calls)` 로 되쓴다. 호출 0건인 kind 는 건드리지 않고
  (미측정은 실패가 아니다) `system_status`·전사 집계는 세지 않는다(캡처 `failed_calls` 와 같은 제외).
  회귀는 E2E 스모크(배선 떼고 깨지는 것 확인)와 `test_project_patch.py` 음성 2건. 부수로 `capture_all` 독스트링의
  허위 반환 키 `probes` 를 고쳤다(실제는 `context`, 읽는 곳 없음).
- [x] **mcad REST 계약 점검 + 파트 절단 버그** (2026-09-02) — 실 STEP 을 붙이기 전에 어댑터가 기대하는 StepForge REST 를
  실물(`/home/koopark/claude/StepForge/app/rest.py`)과 대조했다. 5경로·base·`artifacts/graph/` 의 빈 `ref` 까지 전부 맞았는데
  **`/parts` 하나가 틀렸다** — `limit` 기본이 500 인데 어댑터가 안 넘겨 501번째 파트부터 조용히 사라진다(`/interfaces` 는
  5000 을 넘기고 있었다). `/parts` 는 `/interfaces` 의 `counts` 같은 총수도 주지 않아 응답만으로는 잘렸는지 알 수 없다.
  MCP 폴백에는 이미 트리 요약 대조 가드가 있었는데(recon §2.2) REST 경로에만 빠져 있었다. `REST_PARTS_LIMIT=5000` 명시 +
  `summary.leaf_instances` 대조로 `degraded='parts_truncated'` + 사유 경고를 붙였다. **잘린 파트 목록은 오류가 아니라
  '없는 리스크' 를 만든다** — 그 파트의 계면·치수가 통째로 사라진 채 심사가 정상으로 보인다.
- [x] **`req:` 참조를 1급으로** (2026-09-04, E10 매핑에서 딸려 나옴) — 좌석 계약이 `req:` 인용을 **지시**하는데
  `REF_SCHEMES` 에 없어 전부 dangling·경험칙이었다(정본 §0.2.1 (5)는 `측정`). 파싱·해석(`rr_requirements`)·등급을
  이었다. `parse_ref` 의 catch-all 이 `inc:` 라 스킴만 더하고 분기를 빠뜨리면 사고 참조로 읽혀 등급이 튄다 —
  분기를 명시로 넣었다. `voc:`·`paper:` 는 해석 규칙이 정본 안에서 갈려 E10 본체와 함께 간다.
- [x] **E10 필드·VOC·문헌 근거** (2026-09-04) — P0 결정 4건을 실측 위에서 확정하고 구현했다(context-notes D18).
  ① `E5_FIELD_CAP` 500→340(CAPS 는 오버헤드 포함 라인 상한이라 정본 합 1500 이 안 들어가고 clip_lines 가 E10 을
  먼저 지웠다 — 선례 두 블록은 정본 값 그대로) ② 결측 문구를 `[조회 불가: …]` 로(정본의 '실패' 가 판단어 린터 L14 에
  걸려 strict_lint 경로에서 브리프가 죽는다) ③ `rr_brief_calls`(DDL v2) — `rr_panel_calls` 는 `source_kind` 열이 없고
  `panel_id` NOT NULL 이며 패널 DELETE 가 브리프 행을 지운다 ④ 24h 캐시 키 `(target_key, tool, args_hash)`·행 하나 갱신.
  `voc:`·`paper:` 를 1급 참조로 만들고 등급을 §0.2.1 (5)대로 이었다 — **브리프가 부른 원문 원장이 곧 '실린 것' 의
  목록**이라 정본의 두 갈래(§0.2.1 '실린 것만' vs §5.6.2 '원장에 남아')가 한 갈래가 됐다. 좌석이 지어낸 `voc:` 는
  dangling 이고 등급이 안 오른다. 외부 자유 문자열은 전부 `«…»` 안으로 넣었다(밖에 두면 남의 VOC 문구 하나가
  브리프 조립을 죽인다) — 적대적 응답으로 방어를 시험에 고정했다.
- [x] **'품질' 카드 — 죽어 있던 `GET /meta/metrics`** (2026-09-26) — 정본 §9.7 산출물이 "지표 대시보드
  (앱 `TargetPage` 하단 '품질' 카드) · '루프 작동' 배지" 를 요구하는데 `getMetrics` 가 API 클라이언트에만
  선언돼 있고 **아무도 부르지 않았다**(화면 5종 점검에서 이 경로를 놓쳤다). 배지 판정은 이미 서버가
  `rr_metrics` 행(`loop_ok`·`loop_bottleneck_*`·`label_ingest_wired`)으로 내고 있어 화면만 없었다.
  `QualityCard` 를 만들어 배지 3종 + 지표 표를 보이고, 정본 P6 통과 기준 2 의 **'표본 부족' 표기**를
  세웠다(`value=null` + `n` — 0 으로 보이면 '나쁜 값' 으로 읽힌다). 같이 나온 계약 표류 1건 —
  `MetricRow.value` 가 `number` 인데 서버는 표본 부족 시 `null` 을 보낸다(`tsc` 가 새 카드에서 바로 잡았다).
- [x] **정본 통과 기준 식별자 전수 대조** (2026-09-26) — 통과 기준 246줄에서 식별자 451종을 뽑아 코드·시험·
  스키마에 전수 대조했다(자동). 흔적 없는 26종 중 엔진·허브 소관 20종을 걸러 이 리포 6종이 남았고, 그중
  **오류 코드 표기 2건을 고쳤다** — 코드가 `evidence_ref_required`·`family_key_mismatch` 인데 정본은
  `evidence_required`·`family_key_differs` 로 **일관되게**(3회·2회, 다른 표기 0회) 적는다. 오류 코드는
  계약이고 클라이언트가 문자열로 분기하므로, 갈리면 '근거 없는 확정을 막는 가드' 가 화면에서 '알 수 없는
  오류' 로 보인다. `family_key` 가드는 두 곳이었다(직접 병합 + 큐레이션 큐 병합). 표기가 다시 갈리면
  깨지는 시험을 뒀다. `note_required` 는 원래 정본 표기였다.
  **클라이언트 죽은 선언도 반대 방향으로 전수 점검했다**(56종 중 4종) — `getSnapshotNodes`·`getSnapshotEdges`
  는 화면이 `part=ir` 로 이미 그려 중복 선언이고, `completePanel` 은 엔진·러너 콜백이라 UI 가 부르면 안 되며,
  `exportJsonl` 은 운영자 이관 경로로 정본 §8.2.4 에 화면이 없다 — **셋 다 빠진 기능이 아니다**(다음 세션이
  다시 조사하지 않도록 적어 둔다).
- [ ] **`taxonomy.voc_map` 시드 12행** (2026-09-04, E10 범위 밖) — §7.6 라벨 경로 4 의 입력이다. 정본이 예시 4개만
  주고 그중 3개(`mechanical.fracture`·`interface.gap`·`interface.delamination`)가 택소노미 38코드 밖이라
  코드 신설(마이너 승급 → 지표 계열 분리) vs 기존 코드 사상 결정이 선행한다.
- [ ] **`evidence_profile.field`** (2026-09-04 발견) — §0.2.1 (5)가 `voc:` 인용 수를 이 키로 세라 하는데
  §0.1 용어표·`risk_spec.v1.json` 어디에도 자리가 없다(5키뿐). 의장이 신고하는 6번째 키인지 코드 계산값인지,
  `_profile_mismatch` 대조에 넣을지(넣으면 기존 의장 헤더가 전부 header_mismatch) 정본 결정 필요.
- [x] **프런트 화면 5종 전부** (2026-09-25 완료) — REST 는 있는데 사람이 쓸 입구가 없던 것들.
  - [x] `CurationQueuePage.tsx`(`#/curation`) (2026-09-02) — kind 6종의 열린 항목을 사람이 결정한다. 결정 어휘는 서버
    `CURATION_DECISIONS` 와 같은 집합이고 그 사실을 시험으로 고정했다. 값을 더 받아야 하는 결정(`x_tag_promote` 의 `axis`,
    `unclassified_code` 의 `mechanism_detail`)은 빈 값이면 버튼이 잠긴다. 승격 축 선택지는 `GET /meta/vocab.promotable_axes`
    로 서버가 준다 — 통제 어휘를 화면이 따로 갖지 않는다. 성격 승격 UI(아래 항)가 여기 안에 함께 들어갔다.
  - [x] `CoverageHeatmap` — 이미 `TargetPage.tsx` 안에 있었다(앞선 조사에서 대소문자 때문에 못 찾았다). 셀 클릭 드릴다운이
    부르던 좌석 경로가 없어 죽어 있던 것이고, 위 계약 정리로 살아났다.
  - [x] `TargetPage` '리스크 직접 등록' 폼 (2026-09-25) — `HumanFindingForm`. 인용 최소 1건을 폼이 먼저
    강제한다(서버 422 를 보고 나서야 알게 두지 않는다 — 서버 가드는 그대로). mechanism 선택지는
    `GET /meta/taxonomy` 에서 온다.
  - [x] `TargetPage` '브리프 토큰 복사' (2026-09-25) — `BriefTokens`(RecallPreview 안). 실측으로 32자
    토큰이 발급되고 DB 에는 해시만 남는 것을 확인했다 — "떠나면 다시 볼 수 없다" 는 문구가 사실이다.
    클립보드가 막힌 환경은 `window.prompt` 폴백.
  - [x] `ProjectPage` '사전' (2026-09-25) — `VocabCard`. 추가는 마이너, 삭제는 메이저이고 메이저면
    붉은 배너로 `recompute_part_keys.py` 안내를 띄운다(실측 — 추가 1.1/minor, 삭제 2.0/major).
- [x] **`context.corpus_usage` 봉투 승격(§2.2) + rr_ir 스키마 표류 3건** (2026-09-04) — dyna 계약 대조에서 나온 P1 미완 항목.
  전사 집계를 4도구·정본 순서로 늘리고 `sources[dyna].context` → 봉투 최상위 `context.corpus_usage` 로 옮겼으며,
  `capture_all` 의 kind 루프 뒤로 들어내 **dyna 소스 카드도 사용자 PAT 도 없을 때 돌게** 했다(정본이 명시한 요구인데
  early return 으로 안 돌고 있었다). 정본 내부 모순(§2.11.3 "부재여도 수행" vs §9.2 "rest5+mcp3 초과는 실패")은
  적대 검증이 내 해석을 정정했다 — 3a 는 "3. dyna 캡처" 의 하위 단계이고 "부재여도" 는 *자격* 부재를 뜻하므로
  **dyna 를 요청했을 때만** 돌되 자격 무관이다(mcad 단독은 DynaForge 를 안 부른다). 전사 호출은
  `source_kind='context'` 로 `call_ids`·`reuse_prior_calls`·`partial` 판정 밖에 둔다. 봉투는 4응답의 병합이다.
  스키마는 `primary_source`·`source.app_version`·`degraded` 의 `app_version_unknown` 셋이 빠져 있어 실제 산출이
  자기 계약을 어기고 있었고, **실제 `build_ir()` 산출을 검증하는 시험**(`test_ir_schema_contract.py`)을 세워 막았다.
  적대 검증(5렌즈·137에이전트)이 확정 28건을 냈고 그중 내가 만든 회귀 하나(`app_version` 타입을 추측으로 넣어 실제
  mcad 봉투가 전부 거부)와 항진명제 시험이 가리던 버그 둘(`CORPUS_TOOLS` 순서 역전·`CONTEXT_KIND='dyna'`)을 잡았다.
- [x] **E10 적대 검증 후속 10건** (2026-09-25) — 5렌즈는 끝났고 **반증 186개가 세션 한도로 전부 죽어**
  워크플로 집계(`confirmed 0 · refuted 62`)가 결과가 아니라 실패의 흔적이었다. 정본과 코드를 직접 대조해
  9건을 확정·수정했다 — ① 죽어 있던 `E5_FIELD_CAP`(D18 이 계산만 하고 적용하지 않아 막으려던 실패가
  그대로 살아 있었다) ② `voc:`·`paper:`·`req:` 가 판단어 린터 중립 목록에 없어 외부 id 하나로 브리프가
  E500(재현 확인) ③ 실패한 재조회가 `INSERT OR REPLACE` 로 성공 원문을 지워 인용이 dangling
  ④ `rr_brief_calls` 가 폐기·이양·증분 반출 세 계약 밖 ⑤ 인용 검증 범위가 '부른 것' 이라 블록에 없던
  이슈가 측정 등급(+ 제품코드 미대조) ⑥ `paper:` 가 최근 3행만 봐 예전 패널 인용이 뒤늦게 dangling
  ⑦ "상위 카테고리 3" 을 '앞 3건' 으로 읽음 ⑧ `req:` 가 `waived` 를 풀었다(정본 §4.3.1 범위 위반)
  ⑨ `req:` 를 무조건 측정으로 올렸다(정본 §2.8b `standard` 예외). **시험을 쓰다가 하나 더** —
  `POST /projects` 가 정본 계약의 제품 3열을 pydantic extra 로 조용히 버려 E10 이 영영 결측이었다.
  기각 1건(`[조회 불가]` 가 5줄 상한 밖인 것은 정본과 같다). 시험 13건, 그중 12건은 고치기 전 실제로 깨진다.
- [x] **스키마 `required` 에 `primary_source`·`context` 추가** (2026-09-26) — 픽스처 9종에 두 키를 넣고
  (텍스트 편집 14줄, 재포맷 0) `required` 에 더했다. **미뤄 둔 사유는 틀렸다** — `iter_errors` 는 모든 오류를
  내므로 새 필수 키가 원래 결함을 가리지 않는다(`validate()` 처럼 첫 오류만 보면 그랬을 것이다).
  대신 진짜 구멍은 **시험이 '왜' 거부됐는지 안 본다**는 것이었다. 픽스처 이름의 토큰이 실제 오류의
  경로·문구에 나타나야 한다는 불변식을 세웠고, 첫 실행에서 `invalid_facet7` 하나를 실제로 잡았다
  (이름의 꼬리 숫자가 개수였다 — `facet7` = 8축이어야 하는데 7축, 오류 경로는 `character/facets`).
- [x] **호출 시점 도구 이름 해석** (2026-09-26) — 정본 §2.13.2 는 "게이트웨이 **실이름**(접두 포함형)을
  **호출 인자와** `rr_snapshot_calls.tool` 에 적는다" 고 적고 통과 기준 (23)(a)가 그 둘을 함께 검사하는데,
  suffix 매칭이 probe 에만 있고 호출은 맨이름으로 나갔다. `resolve_tool_name` 을 `adapters/base`(채널 층)에
  두고 probe·호출이 **같은 규칙 하나**를 쓴다 — 갈리면 probe 가 찾은 도구를 호출이 못 찾는다.
  `CallRecorder` 가 호출 직전에 해석하고 원장에 실이름을 적는다. 계약 검사는 **맨이름**으로 유지한다
  (실이름으로 찾으면 계약표가 전부 '모르는 도구' 가 되어 검사가 조용히 꺼진다). 다의면 아무 쪽도 고르지
  않는다. 이름 목록은 `clients_from_settings` 가 받는다 — `capture_all` 이 직접 받아 오면 캡처 경로가
  '외부 호출 안 함' 계약을 깬다(E2E 스모크가 실제로 그걸 잡았다). E10 채널도 같은 해석을 쓰되 **원장에는
  맨이름을 적는다** — 그 표의 `tool` 이 24 h 재사용 키이자 `voc:` 해석 키라, 실이름을 적으면 게이트웨이가
  접두를 붙이는 날 캐시가 통째로 무효가 되고 예전 인용이 dangling 이 된다. 시험 4건, 전부 고치기 전 깨진다.
- [x] **`freeze_snapshot` 재사용 분기가 값을 얼린다** (2026-09-25) — 스냅샷 불변(§2.1)은 지켜야 하니 `ir_json` 은
  건드리지 않고, **버려지던 이번 값을 응답으로 낸다** — `context`(이번에 받은 전사 집계) · `context_frozen_at`
  (얼어 있는 값의 조회 시각) · `context_changed`(값이 달라졌는지, 이번 4호출이 전부 실패하면 `False` 가 아니라
  `None`=모름). 두 분기가 같은 키를 낸다. 같이 나온 것 — 재사용일 때 `UPDATE rr_snapshots SET job_id, capture_partial`
  이 **남의 스냅샷을 이번 잡으로 덮어쓰고** 있었다(완주했던 스냅샷이 부분으로 바뀐다). 재사용이면 그 UPDATE 를
  건너뛴다 — 잡→스냅샷 방향은 `rr_snapshot_jobs.snapshot_id` 가 이미 맡는다. 시험 2건(하나는 고치기 전 실제로 깨지는 것 확인).
- [ ] **corpus_usage 의 위생·상한 미정** (2026-09-04 발견) — 남의 모델 재료명·섹션명 원문이 들어오는데
  `sanitize_source_text`(§3.4.1) 를 타지 않고 `part='ir'` 응답에 상한도 없다. 정본이 '원문 발췌' 의 추출 규칙을
  정하지 않아 코드로 지어내지 않았다 — 화면·브리프가 이 값을 읽기 시작하기 전에 정본 결정이 필요하다.
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
- [x] **E10 후속 4건 + 기각 2건** (2026-09-26) — ② 자격 순서를 세웠다(`field_source.for_target` —
  (b) 타깃 owner → (a) 서비스, 만료 임박 제외). 게이트웨이 `actor` 는 **미검증 값**(§6.11)이라 (c) 로
  쓰지 않는다 — 쓰면 남의 PAT 를 고른다. ③ E10 이 `render.sanitize_source_text` 를 직접 불러 `on_suspect`
  가 빠져 있었다 → `brief._q`·`_cut` 경유(줄바꿈까지 접는다 — 접지 않으면 남의 VOC 한 줄이 두 줄이 되어
  줄 수 상한을 우회한다). ⑤ 지표 분자에서 `dangling` 인용을 빼고, 분모 판정을 `brief.product_keys_of`
  로 공유했다(`ra_model` 만 든 과제는 E10 이 구조적으로 불가능한데 분모에 들었고, 전작 코드만 있는
  과제는 E10 이 도는데 빠져 있었다 — 양방향으로 틀렸다). ⑥ `character.evidence_grade_of` 가 존재 검증
  없이 `req:`·`voc:` 를 측정으로 올렸다 → 지역 검증 가능한 두 스킴만 검증한다(`inc:` 는 채널 부재라
  검증하지 않고 `p:`·`e:`·`c:` 는 스코프가 없어 그대로 센다). **기각 2건** — `registry._is_stronger` 의
  등급표 표류는 이번 변경이 등급을 **내리는** 방향이라 dismissed 가 되살아나지 않고(방향이 반대다),
  기존 `req:`·`voc:` 인용은 애초에 없다. `all_heuristic` 이 죽는다는 지적은 정본 §0.2.1 (5) 의 설계
  그대로다. 시험 4건, 전부 고치기 전 깨진다.
- [x] **`voc:`·`paper:`·`req:` quote 대조** (2026-09-26) — `canonical_text_for` 에 분기가 없어 §4.4.2 가
  건너뛰어지고 있었다. 외부 근거는 **사람이 눈으로 확인할 방법이 없어** 지어낸 인용문이 가장 잘 먹히는
  자리다. E10 줄을 만드는 곳을 `brief.field_evidence_line` 한 곳으로 모아 조립과 대조가 같은 문자열을
  본다(대조 기준이 그 줄이 아니면 무슨 대조든 헛것이다). `req:` 는 한계값이 정규 표기라 좌석이 한계를
  다르게 적는 것을 잡는다 — 그 실패가 §4.4.2 가 있는 이유다. `standard` 는 한계가 없어 조항·제목이
  표기다(§2.8b). 시험 2건, 둘 다 고치기 전 깨진다.
- [ ] **E10 적대 검증에서 남긴 지적 1건 — 정본 결정 대기** — `product_refs_json` 에 제품코드가 여럿일 때
  `codes[0]` 만 조회한다. 정본이 "`product_code` **값들**"(복수, §5.6.2)이라 적고 호출은
  `get_top_issues(product_code, 90d)`(단수)라 적는다. 제품마다 부르면 호출 예산이 제품 수만큼 늘고
  5줄 상한을 제품들이 나눠 쓰게 되므로 코드로 지어내지 않았다(↓ 6장에 결정 행을 뒀다).
- [x] **`missing.mcad_capture_failed` — 잘린 트리로 IR 을 지어내던 것** (2026-09-29) — MCP 폴백 응답에
  `nodes` 키가 없으면(리프 >500) 정본 §2.5.1·§2.13.3 은 **mcad 를 통째로 버리라** 한다. 코드는
  `tree_truncated` 만 세우고 계속 진행해 `list_parts`(500 클램프·truncated 플래그 없음)로 노드를 만들었다.
  **실측으로 증명했다** — 요약이 리프 620건이라 말하는데 IR 은 파트 2건으로 서고(실환경이면 620 중 500)
  `missing` 은 그 사실을 한 마디도 안 한다. 사라진 파트가 낀 간섭이 함께 사라지므로 '없는 리스크' 다.
  §2.2 degraded 표가 이 경로를 **"실무 어셈블리에서는 상시 경로"** 라 적는다 — 첫 실캡처에서 바로 걸린다.
  `_capture_failed` 로 마감하고(소스 행은 남긴다 — 원인을 사람이 봐야 한다) 정본 표대로 `mcad_absent` 와
  **함께** 세워 형상층 게이트가 `pass=null` 로 내려가게 했다 — 그러지 않으면 노드 0건인데 위반 0건이라
  G3 가 통과로 읽힌다. 같이 맞춘 것 — `missing` 키가 코드 9·스키마 7·정본 11 로 셋이 갈려 있었다.
  정본 11키로 통일하고 IR 모양 픽스처 16종을 실산출에 맞췄다. 어댑터 선언이 **기본값 있는 키만** 통과하는
  필터도 주석으로 못 박았다(없는 키를 선언하면 조용히 버려진다 — 이번에 그 함정을 직접 밟았다).
  시험 3건, 전부 고치기 전 깨진다.
- [x] **§4.8 스냅샷 변경 시 무효화 배선** (2026-09-30) — 기계는 다 있는데(`rr_targets.superseded_by` 열 ·
  `diff.changed_ckeys(resolve)` · `registry.invalidate(resolve_ckey=)` · `planner.apply_carry_over`)
  **부르는 곳이 시험뿐이었다** — `create_target` 이 §4.8 을 전혀 하지 않아 stale·superseded·unraised·carried 가
  한 번도 안 쓰였다. 시험이 함수를 직접 불러 초록이었을 뿐이다(브리지와 같은 계열). 이제 타깃 생성이
  ① 옛 타깃을 `superseded_by=T′` 로 닫고 ③ 등록부 stale 를 표기하고 ④ 좌석 carried 를 판정하고
  ⑤ 성격 행에 `needs_review` 를 남긴다(status 는 안 건드린다 — confirmed 를 코드가 내리지 않는다).
  **안전 핵심 — `changed_ckeys` 를 모를 때 빈 집합으로 진행하지 않는다.** 빈 집합은 '아무것도 안 바뀌었다'
  와 같아서 `invalidate` 는 stale 0건, `apply_carry_over` 는 **전 좌석 carried** 가 된다(정적으로 확인했다).
  재검증 없이 통과시키는 쪽이라 '없는 리스크' 다. 두 스냅샷 사이 diff 가 없으면 ①만 하고 사유
  (`skipped: diff_absent`)를 남긴다 — 정본은 "없으면 생성" 이라 하지만 타깃 생성이 diff 를 부수효과로
  만들면 게이트 차단·비교 불가로 409 가 날 수 있어 **재사용만** 한다(생성은 `POST /diffs` 가 한다).
  ckey 비교는 전부 `resolve_ckey` 를 거친다 — 안 거치면 자동 승계로 병합된 키가 한쪽에서만 맞아 판정이
  '어느 스냅샷 키로 계산했는지' 에 따라 갈린다. 남은 것 — E5 의 `[변경 주체 — 재검증 대상]`·`[미변경 주체]`
  접두(§4.8 3)는 **완료**(↓ 다음 항). 시험 3건, 전부 고치기 전 깨진다.
- [x] **E5 변경 주체 접두 2종** (2026-09-30) — §4.8 3 의 `[변경 주체 — 재검증 대상]`·`[미변경 주체]` 를
  세웠다. `stale_json` 이 브리프 조회 열에 아예 없었다. **판정하지 않은 선례에는 붙이지 않는다** — stale
  표기는 `stale_json[T′]` 이고 그 판정은 같은 과제 직전 타깃에만 일어나므로, 다른 과제 선례에 `[미변경
  주체]` 를 적으면 확인하지 않은 것을 확인했다고 적는 것이다(모름과 '안 바뀜' 을 같은 글자로 쓰지 않는다).
  §5.6.1 의 접두 2종과는 다른 사실이라 겹쳐 붙이고 변경 주체를 먼저 둔다(재검증이 필요한지를 좌석이 먼저
  알아야 한다). 예산 실측 — 접두가 최악(전부 stale)일 때 E5+ 700자가 4줄→3줄이 된다. 정본이 요구한
  대가이고, 선례 전부의 주체가 바뀌었으면 줄이 줄어드는 쪽이 맞다. 시험 2건, 둘 다 고치기 전 깨진다.
  **남긴 판단** — E5− 에는 붙이지 않았다. §4.8 은 "E5 는" 이라 적고 E5− 도 E5 의 블록이지만, §5.6.1 의
  E5− 줄 형식에 접두 자리가 없고 300자·6줄 상한을 접두가 먹는다. 기각된 선례의 주체가 바뀐 사실도
  중요할 수 있어(옛 형상에서 기각한 리스크가 지금은 실재할 수 있다) **정본 확인이 필요하다**(↓ 6장).
- [x] **목록 경로 3종 — 첫 화면 탭 3개가 빈 자리였다** (2026-09-30) — 홈 탭 4개 중 3개가
  "목록 경로가 아직 없습니다" 였고 서버에 **정말 없었다**(항목 경로 `/diffs/{id}` 등만 있고 컬렉션
  경로가 없었다. 정본 §8.2.3 경로표에도 셋이 빠져 있다). 정본 §8.2.4 RiskHomePage 는 "상단 탭
  과제/비교(diff 목록)/타깃/보고서" 를 요구하는데 앱은 **"여기 무엇이 있는지" 를 보여 줄 방법이 없었다** —
  UX 가 나쁜 1차 원인이 디자인이 아니라 이것이었다. `GET /diffs`·`/targets`·`/reports` 를 열고 탭 3개를
  배선했다. 목록은 고르기 위한 것이라 본문(`diff_json`·`summary_text`)을 안 싣는다. 목록에서 바로 보이는
  판정 — diff 는 `blocked`·`gates_failed`(믿어도 되는지가 먼저다, §2.12) · 타깃은 `coverage_pct`·verdict
  (안 보이면 타깃마다 들어가 봐야 한다) · 보고서는 RA 반영 상태(앱은 전문을 갖지 않는다, §5.3).
  기본 목록은 §4.8 로 닫힌 타깃을 가린다. 창은 상한 200 으로 자른다. 시험 4건, 전부 고치기 전 깨진다.
- [ ] **정본 통과 기준 대조에서 남은 4건**(2026-09-26, 식별자 전수 대조로 발견) —
  ① **완료(2026-09-30)** — 브리지를 구현했다. `part_mesh_map` 을 정본 MCP 3 예산에서 부르고(§2.13.3),
  `kind='bridge'` 엣지를 mcad part ↔ dyna pid 로 잇는다. 조인 키 2종(`path:` REST · `file+name:` MCP)과
  `ambiguous_bridge_key`(같은 키 2행 이상이면 그 키만 건너뛴다 — 표 하나가 전부를 죽이지 않는다)을 세웠다.
  도구 집합도 정본 6종으로 되돌렸다(코드는 5종이었다). 곁에서 셋이 더 나왔다 — **@** MCP 폴백에서
  프로젝트 접두가 안 벗겨져 같은 파트의 canon_key 가 채널마다 달랐다(정본은 "반드시 제거한다";
  same-as 3단계가 채널 간에 통째로 빗나가고 ckey 가 '과제 무관' 이라는 정의가 깨진다) · **@** `sameas` 의
  브리지 attrs 자리가 `attrs.bridge_stale` 평면인데 정본은 `attrs.dyna.bridge` 다 — 시험 헬퍼도 같은
  평면이라 **둘이 서로 맞춰져 있었지만 둘 다 정본과 달랐다**(브리지를 만드는 코드가 없어 안 드러난
  항진명제 쌍) · **@** `bridge_stale` 판정이 **정본 내부 불일치**다(↓ 6장 결정 행). 시험 6건, 전부 고치기 전 깨진다.
  · ② **완료(2026-09-29, ↓ 1장)** · ③ `rr_findings.finding_json.cited_by_later[]`
  (§5.6 (4)) — 인용된 선례에 후속 `claim_uid` 를 누적해야 '선례가 실제로 쓰였는지' 의 원자료가 된다 ·
  ④ 등록부 `subject_ckeys` 를 `resolve_ckey()` 로 해석하는지(§5.9.1) — 이름이 다를 수 있어 의미 대조가 필요하다.
  ①②는 어댑터 픽스처가 선행이고 ③④는 원자·별칭 경로를 건드려 한 번에 하지 않았다.
  · ④ **완료(2026-10-17)** — 등록부는 이미 풀고 있었다(`registry.invalidate(resolve_ckey=…)`). 같은 규칙(plan §4.8 2)의
  나머지 둘 — 좌석 인용 ckey(승계 판정) · 성격 인용 ckey(재확인) — 가 병합 전 키 그대로 대조해, 옛 키를 인용한 좌석이
  바뀐 주체를 못 보고 승계됐다. `_supersede_previous_target` 이 둘 다 풀게 고쳤다(시험 1 · 변이 2/2).
  · ③ 은 빈칸 하나가 아니다 — plan §5.8 의 기록 넷(`precedent_refs` · `precedent_clusters` · `prior_cites_n` ·
  `cited_by_later`)이 DDL 주석에만 있고 쓰는 코드가 없다. 패널 방식의 선례 인용 기록이고 P5 통과 기준 (4) 의 원자료라
  그 측정 때 함께 짓는다(포털 docs/leftovers-1017 context-notes LO-D5).
- [x] **UX 전환 2c — 남은 상세 화면 다섯** (2026-10-07, context-notes D37) — Project·Snapshot·Target·
  Compare·CurationQueue(3,464줄)를 Report Archive 스택으로 옮겼다. 공유 층(SectionCard·Badge·
  DataTable·StateBlocks·GateBanner + primitives 12종)을 먼저 확정해 방언을 막고, 화면마다 한
  에이전트가 전환한 뒤 **다른 눈이 diff 를 직접 보고** 역검토했다(33건 중 실질 11건 수정).
  레거시 `rr-*` 실사용 0 · `index.css` 666 → 227줄 · **preflight 켬**(공존 계획의 종점).
  띄워 보기 전에 안 보이던 것 다섯을 브라우저로 잡았다 — `border-*` 유틸 전체 무효 · 그 수정을
  되돌리던 `border: 0` 축약 · Tailwind 스캐너가 못 본 Select 화살표 · 제목·문단 UA margin ·
  **앱 전체 가로 밀림**(flex 자식에 `w-full`, 전환 이전부터 있던 결함).
  **그리고 타입이 서버와 달라 `tsc` 가 거짓을 지켜 주고 있었다** — 배포본이 백지였고, 선언을
  서버 열 이름에 맞추자 호출처 9곳이 드러났다.
- [x] **same-as 6단계 상한**(2026-10-31, 포털 triage-1031 B24 · context-notes BL-1 · BL-6) — 남은 노드 수의 곱이 800×800 을 넘거나
  배정 행렬의 변(남은 a + 남은 b)이 1,600 을 넘으면 점수도 헝가리안 행렬도 만들지 않고 5단계까지의 대응으로 진행한다
  (`sameas.FUZZY_MAX_PAIRS` · `FUZZY_MAX_SIDE` · `fuzzy_skip`). 스냅샷은 두 도메인 소스의 degraded `fuzzy_skipped_large` · 경고 한 줄 ·
  `sig:capture.fuzzy_skipped`, 쌍은 `correspondence.fuzzy_skipped{…, limit, side_limit}` 와 의미층 · 이벤트 `caveat='fuzzy_skipped_large'`.
  801×801 건너뜀 · 799×799 · 800×800 그대로 · ir_hash 결정론. 변 상한은 반대 검토(10-31)가 더했다 — 곱만 보면 30 × 3,000(곱 9만)이
  3,030 변 행렬로 10분을 넘는다(30 × 1,571 · 1 × 1,600 건너뜀, 30 × 1,570 그대로 — 시험 21 · 변이 11/11 · 반대 검토 뒤 5/5).
- [x] **계면 목록 절단의 kind 별 수와 제외 사유**(2026-10-31, B25 · BL-2 · BL-7 ~ BL-9) — mcad 캡처가 `stats.interfaces_truncated{kind: n}` 을
  남기고(안 잘렸으면 `{}`), 쌍의 한쪽이라도 잘린 kind 의 엣지 변경 · 엣지 파라메트릭 · 그 계면을 읽는 명명 치수(파생 치수 포함)가
  `excluded_reason='truncated'` 다 — 잘린 쪽에서 빠진 간섭이 '사라졌다'(iface.removed · dim.named_unmeasured) 는 가짜 사건을 내지 않는다.
  롤업은 kind 별이다 — 잘린 kind 의 수가 두 쪽에서 다를 때만 빼고, 같으면 계면 수를 잘리지 않은 kind 로만 센다(`truncated_kinds`).
  고아 전이는 고아가 아닌 쪽에서 잘린 kind 에 끼어 있었으면 `orphans_delta.truncated` 로 옮기고, 검토 근거 줄은 한쪽만의 잘린 계면을
  '목록 절단 — 비교 불가' 로 적는다. 요약 [치수] 도 truncated 치수를 싣지 않는다. 종류별 수가 없는 옛 캡처는 네 kind 전부. 검토
  단위에서는 제외 단위가 갖는다(시험 17 — 절단 14 · 어댑터 3, 변이 9/9 · 반대 검토 뒤 14/14 — 치수 · 고아 · 롤업 셋은 반대 검토 10-31 이
  찾았다). 규칙 R-001 · R-002 의 `truncated` 판정은 아직 kind 를 보지 않는다(↓ 다음 수).
- [ ] 골든 `backend/tests/golden/sif-e2e.ir.json` 부재 — 선행 B2(골든 프로젝트 재파싱)가 닫혀야 만들 수 있다(↓ 2장).
- [x] **RK-01 RA 보내는 쪽**(2026-10-31, 가지 `wt1031/rk01`, 사용자 결정 10-31 D-1 (가) — context-notes 'RK-01' 절 RS-1~) —
  `ra_client.RaSender` 가 external_sync.ra 의 대기 op(라벨 상태 병합 · verified_by|refuted_by · X태그 승격의 design_trait · exhibits)를
  RA 도구 호출로 옮겨 박스 쓰기 PAT 하나로 보낸다. `main.py` 가 `RiskRunner(external_sync_send=…)` 로 꽂고 sync_loop 가 60초마다 부른다.
  id 는 `rr_id_map` 과 원본 표 `ra_entity_id` 에, 비공개 과제는 `withheld`, 쓰기 PAT 가 없으면 꺼진 채 요약이 `credential_missing` 으로 말한다.
  실패한 op 는 까닭과 함께 큐에 남는다(transient 만 백오프). RA 래퍼의 인자 이름을 RA MCP 의 것으로 바로잡았다(get_object 의 type ·
  update_object · add_object_alias 의 object_id · get_subgraph 의 entity_id). 남은 것 — ↓ 2장 cae00 확인, 패널 때 투영(M4), 화면의
  reason 낱말(프런트 세션).
- [x] **RK-01 반대 검토 고침**(2026-10-31, 같은 가지 — context-notes 'RK-01 반대 검토 고침' 절 RS-11~) — 카드 대조 거름 자리 등록(전체 시험
  실패 1) · 라벨마다 다른 병합 op(label_id) · risk_finding status 는 보낼 때의 등록부 값(되돌린 상태가 RA 에 틀린 채 'sent' 로 끝나던 것) ·
  op 하나에만 걸린 영구 거절은 `dead_ops` 로 따로 두고 나머지를 보낸다(재동기가 되돌린다) · 가시성 · 폐기를 호출마다 본다 · 멈춤 · 따로 둠을
  틱마다 경고 한 줄 · 한 틱 대상 50 · 30초 · 정지 신호 · 박스 PAT 클라이언트에서 보고서 도구를 뺐다 · 폐기 보고서의 RA 층 글을 실제 동작으로.
  남은 것 — ↓ 6장 'RK-01 거두기' 결정, 화면의 `dead_ops` 칸(프런트 세션).
- [x] **RK-01 거두기**(2026-10-31, 같은 가지, ↓ 6장 (가) 사용자 결정 10-31 — context-notes 'RK-01 거두기' 절 RS-21~) — 비공개 전환 · 폐기 ·
  이양 · 다시 공개 때 `ra_client.queue_retracts` 가 RA 에 나간 객체(과제 · 등록부 risk_finding)마다 거두기 op 를 큐 끝에 쌓고, 보내는 쪽이
  보류 · 폐기 멈춤을 건너뛰어 보낸다. 꼴은 보낼 때의 정본 범위로 — 닫힌 과제면 값 '비공개@<code>' · 과제 설명 비움 · risk_finding 은
  visibility=private 와 열쇠만(owner · status 를 뺀다), 열린 과제면 나간 꼴(이양 뒤 owner · 다시 연 과제). 남의 객체는 쓰지 않고(`id_mismatch`)
  비공개 순간에 만들어진 객체도 뒤따라 거둔다. 요약에 `retracted` · `retract_pending` · `retract_failed` · `retract_reasons`, 폐기 보고서
  RA 층은 거둔 수 · 대기 · 못 거둔 수와 까닭 낱말(`not_retracted` 를 갈음), 거두기마다 rr_audit(`ra.retract` · `ra.remark`). RA 에 지우기 ·
  끊기가 없어 객체 껍데기와 연결은 남는다. 남은 것 — ↓ 2장 cae00 확인 ⑦, 화면의 거두기 칸(프런트 세션), 포털 정본 §5.2.6 4층 · §5.1 원칙 9
  글(포털 몫 — `status='retracted'` 는 RA 가 받지 않는다).
- [x] **RK-01 거두기 반대 검토 고침**(2026-10-31, 같은 가지 — context-notes 'RK-01 거두기 반대 검토 고침' 절 RS-31~) — 폐기 경합(폐기된 과제의
  보낼 op 는 대상을 멈추지 않고 버린다 — `project_purged`, 폐기가 쌓은 거두기 · 뒤따른 거두기가 멈춘 큐에 갇히지 않는다) · 다시 열기 경합(열린
  과제의 거둔 꼴로 남은 객체에 다시 표기 op 를 뒤따라 쌓는다) · 거두기는 앞선 보내기의 백오프를 물려받지 않는다(transient 로 멈춘 채널은 한 번
  되살린다) · 거둔 꼴은 앱이 투영한 owner · status 만 뺀다(RA 에서 따로 단 속성은 둔다, 가려 읽힌 것만 뺀다) · RA 에 이미 없던 객체는 따로
  센다(`absent` · `retract_absent`, 요약과 폐기 보고서가 같은 차례로 한 번씩) · 뒤따라 쌓은 거두기의 행위자는 과제를 닫거나 연 사람(모르면
  `system`, 검증되지 않음) · 폐기 보고서 글은 기다리는 거두기가 언제 나가는지를 채널 상태로.

## 2. 실환경 실측 대기 — 자격·선행 조건이 필요한 것

여기 있는 것은 코드가 없어서가 아니라 **소스 앱·자격·실데이터가 없어 합성 픽스처로만 채워 둔** 통과 기준이다.

- **자격 — 정본 서술이 낡았다(2026-09-02 정정).** 정본은 B1(heax 서비스 PAT)을 '최대 단일 레버' 로 적었지만 커밋 `37b9c3b` 이
  그 레버를 이미 뺐다 — **사람이 시작한 캡처는 호출자 본인의 heax 토큰으로 StepForge REST 를 읽는다**(대리 읽기, 읽기 전용,
  권한 확대 없음). 지금 실제로 필요한 것은 셋으로 갈린다.
  - [x] STEP 읽어 스냅샷 동결 → 게이트·규칙 — **추가 자격 0**(로그인만). 코드 준비됨
  - [x] 패널 심의(LLM 좌석) — **포털 PAT 등록 실측 완료**(2026-10-01, context-notes D36). 라이브 배포본에서
    '포털에서 발급해 등록' 버튼을 실제로 눌러 `oDRGWDrElFg7…`(만료 2026-12-30 · `scopes read` · `aud mcp-gateway`)
    이 `_user_credentials` 에 들어갔다. 1차 시도는 컨테이너 `HWAXRISK_PORTAL_BASE` 가 죽은 포트 `5283` 이라
    등록이 502 였고(내 `portal_unreachable` 진단이 그대로 떴다), HEAXHub `.env` 를 소싱한 재배포로 `8088` 을
    넣어 해소했다. 그때 포털에 남은 고아 PAT `1OgmWBaZ…` 는 폐기했다.
    그 PAT 으로 캡처 전 구간 200 — `:9110/tools-map` · StepForge REST 5경로 · `:9110/mcp` 5회
  - [ ] 무인 배치(야간 러너)·RA/ADH 쓰기 — `secrets.env` 서비스 키(현재 파일 자체가 없다)
- [ ] **B2 골든 `sif-e2e` StepForge 재파싱·재검출**(§10 #15, 사용자 실행) — 미실행이면 첫 캡처가 `volume_null_pre_d168` 확정
- [ ] **B4 실무 규모 STEP 1건 업로드** · **B5 DynaForge 세션·K파일·리포트 각 1건**(P2 (8)(9) 선행) · **B6 `heax-materialtwin_web` 기동**(§10 #41)
- [ ] `var/app_data/hwax_risk/secrets.env`(0600) 5키 — `HWAXRISK_PORTAL_PAT`(scopes read) · `HWAXRISK_PORTAL_PAT_RW` · `HWAXRISK_HEAX_SERVICE_PAT` ·
  `HWAXRISK_AIDH_API_KEY` · `HWAXRISK_CRED_KEY`(Fernet) → `redeploy-app.sh hwax-risk`. 현재 `cred.key` 만 있다
- [ ] `bootstrap_ra_ontology.py --base <RA> --apply`(env `RA_ADMIN_PAT`, §10 #1 승인 선행) · `bootstrap_adh.py`(§10 #10 확인 선행) 1회 실행
- [ ] **RK-01 cae00 확인**(사람 몫) — ① `HWAXRISK_PORTAL_PAT_RW`(aud mcp-gateway · scopes read · write)를 secrets.env 에 넣는다(재기동은
  필요 없다 — 다음 동기 주기부터 켜진다). ② **그 PAT 주인 계정이 RA 시스템 관리자인지** — RA 온톨로지 쓰기는 `require_system_admin`
  이라 아니면 모든 대상이 `forbidden: … 시스템 관리자 권한이 필요합니다` 로 멈춘다(RA 사람별 위임이 켜진 박스는 그 이메일의 RA 계정,
  꺼진 박스는 포털 '외부 연결' 에 등록한 rat_ 의 주인). ③ 게이트웨이로 RA 도구를 부를 수 있는지 — 앱이 부르는 별칭 `reportarchive_<이름>` 은
  **호출 전용이라 `tools/list` · `/tools-map` 에 나오지 않는다**(목록에서 찾으면 RA 가 멀쩡해도 '없다' 로 보인다). 박스 쓰기 PAT 로 게이트웨이에
  MCP `initialize` → `tools/call` 로 `reportarchive_list_object_types` 를 직접 불러 답이 오는지 본다. 인자 이름은 `tools/list` 의 맨
  `create_object` · `update_object` · `get_object` 항목(다른 백엔드와 이름이 겹치면 `reportarchive_` 접두가 붙은 항목)의 inputSchema 로
  `update_object(object_id, value, description, properties)` · `get_object(type, id)` 인지 본다(dev RA 사본 3ece194 기준으로 지었다 — 거두기가
  value · description 을 쓴다). `/tools-map` 의 `map` 에서 값이 `reportarchive` 인 도구도 함께 본다. ④ 위 부트스트랩이 돌았는지(아니면
  `ontology_missing`) — 거두기는 risk_finding 의 `visibility` 속성(enum private · org)을 쓰므로 그 속성이 박스 RA 에 있는지도 본다(없으면
  거두기가 `rejected`('정의되지 않은 속성')로 따로 두어진다). ⑤ 과제는 기본이 비공개라 조직 공개로 바꾼 과제만 나간다(나머지는 `withheld`).
  ⑥ 첫 동기 주기 뒤 앱 로그에 `외부 반영 RA 멈춤` 경고가 없는지 본다(있으면 그 사유 낱말을 고친 뒤 대상 화면의 '재동기'). ⑦ 거두기 —
  RA 에 나간 조직 공개 과제 하나(시험용)를 비공개로 돌리고 다음 동기 주기(60초) 뒤 그 과제의 RA risk_finding 이 값 `비공개@<code>` ·
  속성 visibility=private 이고 owner · status 가 빠졌는지(RA 에서 따로 단 속성은 남는다 — 게이트웨이가 가려 읽힌 칸만 빠지고 그 이름은 감사 행의
  `dropped`), 과제 객체의 값이 `비공개@<과제 id>` 이고 설명이 비었는지 본다(RA 화면 · `reportarchive_get_object`). 앞선 보내기가 RA 불통으로
  재시도 대기여도 거두기는 다음 동기 주기에 나간다.
  앱에서는 대상 요약의 `retracted` 수와 과제 감사(`GET /api/projects/{id}/audit?action=ra.retract`)를 본다. 다시 조직 공개로 돌리면 나간 꼴로
  돌아오는지도 본다. `id_mismatch` 로 따로 두어지면 다른 박스에서 들여온 사상이다 — 그 박스의 RA 가 아니므로 쓰지 않은 것이다.
- [ ] 통과 기준 실측 — P0 (4) StepForge 직접 읽기 · (9) 러너 자격 3항 · (16) app-data 왕복(`appdata-to-drive.sh` → 복원 `integrity_check ok`) ·
  (17) 신원 해석 라이브 · (18) 자격 최소 권한·암호 보관 4항
- [ ] P3 엔진 실호출 실측 — 포털 `/agent/chat` 경로 (A) 로 패널 1건 완주 · SSE 귀속 ≥95% · 도구 사용률 ≥80% · IR 인용 ≥50%
- [x] 성능 실측 diff — 500·2000 diff <5 s + 피크 기록(§10 27) — 2026-10-31 B26 · BL-3: 노드 505 · 엣지 2,084 합성 쌍
  `compute_diff` 0.20 s · tracemalloc 피크 20 MB · 새 프로세스 RSS 피크 97 MB → 매니페스트 `memory_gb 2` 그대로(`tests/test_diff_scale.py`)
- [ ] 성능 실측 캡처 — 500파트 캡처 ≤10 s(가짜 소스로 dev 가 먼저 할 수 있다 — 포털 design-risk-review 118)
- [ ] **cae00 카드 분포 측정 한 번(사람)** — `backend/scripts/card_window_census.py`(B32 · context-notes W-D 절)를 cae00 명단 전원으로.
  절차는 context-notes 「W-D — 리스크 20만 창 카드 분포」의 'cae00 에서 한 번' 이다

**이미 실측된 것**(다시 하지 않는다) — SIF 빌드·기동·Caddy 라우트·게이트웨이 `heax-hwax_risk` 자동 흡수(`POST /mcp` 200 · `tools/list` 응답,
`var/logs/integration_hwax_risk.log`) · `var/app_data/hwax_risk/` 생성과 DB 지속 · 로컬 기동 3점.

## 3. 이 리포 밖 — 포털·엔진 몫

앱 코드는 손대지 않지만 앱의 통과 기준이 여기에 걸려 있다.

- [ ] **정본 §4.4.3 등급 표에 세 행 추가**(`HWAXPortal/docs/design-risk-review/plan.md`, 문면 개정 1건) —
  §0.2.1 (5)가 "`req:` 와 `voc:` 는 `측정`, `paper:` 는 `문헌·규격` 이다(§4.4.3 자동 산출 표가 이 세 행을
  그대로 쓴다)" 고 적는데 그 표에 세 행이 없다. 코드는 §0.2.1 을 따랐고 시험으로 고정했다. 붙여넣을 초안 —
  `| req: | 측정 | 단 kind='standard' 는 문헌·규격(§2.8b) · status ∈ candidate\|confirmed 만 |` ·
  `| voc: | 측정 | 브리프 E10 블록에 실린 항목만(§0.2.1) |` ·
  `| paper: | 문헌·규격 | 같음 |`. 표기만 맞추는 일이라 코드 변경 0 이다.
- [ ] 포털 `delibTaxonomy.ts`(JobId·JOBS 8행째·JOB_ROUTING·suggestJob) · `conversations.api.ts` ConvKind · `agent/routes.py` `ConvCreate.kind`
- [ ] agent-server `GET /health` 에 `sampling{temperature, top_p, max_tokens, seed?}` 1키 additive — 없으면 앱은 `sampling=null` 로 진행한다(막히지 않음)
- [ ] `delib_metrics.py` 에 risk_spec 파싱 성공률 1종
- [ ] `HWAXPortal/infra/pipeline/hwax-risk-review.js` args 에 `briefToken` 필수화(§6.11) + `sync-workflows.sh`
- [ ] `check_chair_parity.py` exit 0 확인 — 되면 이 리포 `test_parity.py` 가 skip 에서 실검사로 바뀐다

**HEAX 플랫폼 쪽 알림**(앱 버그 아님) — 헬스 프로브가 `/apps/hwax_risk/apps/hwax_risk/api/health` 로 접두를 두 번 붙여 404 를 3,756회 냈다
(200 은 0회). `materialtwin_web`·`web_design_agents`·`voice_recorder` 로그에도 같은 이중 접두가 있어 플랫폼 공통 문제다. 앱은 정상 기동 중이다.

## 4. P7 — ODB 허브(ECAD)

> 1단계는 가지 `wt1031/ecad`(2026-10-31)다 — 요청서 정본은 포털 `docs/design-risk-review/ecad-1031/request.md`(ER-01 ~ ER-06 · OH-01 ~ OH-05),
> 사용자 결정 D-1 = (가)(계약 4도구를 새로 내지 않고 허브가 지금 도구에 묶음 읽기를 더한다). 결정과 까닭은 context-notes 'ECAD 1단계' 절(EC-1~).
> 계약은 `docs/odb-adapter-contract.md` 다.

- [x] 선행 — 계약 합의 대신 지금 도구(게이트웨이 백엔드 `odb-hub` 39개)로 간다(D-1 = 가). 스텁 `ecad_stub.py` 는 지웠다
- [x] ER-02 발견 — `/tools-map` 의 백엔드 `odb-hub` 와 원래 이름(접두 `odbhub_` 포함) · 상태 실측(ready · unavailable · planned, `contract_only` 없음) ·
      캡처의 MCP 호출은 그 소스의 백엔드 이름으로(`backend_tool_name`) · 응답 계약은 어댑터마다 제 표로
- [x] ER-03 `adapters/ecad.py` — `find_job` · `get_board_layers` · `check_job_stackup` · `get_volume_result` · `get_odb_download` 한 번씩 +
      `list_parts` 100행씩 → board(소스 1건 + board 노드 1건 — EC-14) · layer(5종, 위에서 아래 idx) · component(분류된 부품, 좌표·넷 없이) · ir_version 1.1
- [x] ER-04 표지 열두 개(`rr_ir.v1.json` degraded_code — 부품 · 층 가족이 통째로 빠지면 `components_unavailable` · `layers_unavailable`) ·
      find_job 을 불러 못 읽으면 `ecad_capture_failed`, 호출 없이 끝나면 결측 + 경고(EC-16) · 허브 봉투형 오류는 경고만 · `sig:counts.ecad.nets` 는
      0 이 아니라 미측정
- [x] ER-01 보드 고르기 — `GET /api/ecad/boards` · `PUT · DELETE /api/projects/{id}/ecad-board` · MCP `risk_find_ecad_boards` · `risk_set_ecad_board`
      (find_job 후보를 사람이 고르고, 붙이기는 find_job 에 있는 job_id 만 · 일반 소스 연결의 kind ecad 는 422 `ecad_board_route`)
- [x] ER-05 `docs/odb-adapter-contract.md` 개정(지금 도구 · 발견 · 두 단계 · 사상 · 표지 · 의존 도메인 6) — 포털 plan §2.5.3 · §2.13.5 는 포털 몫
- [x] same-as 4단계는 ecad 노드만 뺀다(종전에는 ecad 가 하나라도 있으면 단계를 통째로 꺼 쌍 비교의 mcad 지문 대응까지 꺼졌다) · 3단계도 ecad 를 짝 목록에서 뺀다
- [x] 시험 — 부록 A 꼴 가짜 odb-hub(`tests/test_ecad_adapter.py`) · 남 숨김 표 · 변이 20/20 · 전체 3,427 통과 · xfail 4 · 실패 0(context-notes EC-13)
- [x] 블랙박스(`tests/test_bb_ecad_stage1.py`, 요청서만 보고 지은 23건) 들여오기 · 가정 도우미 A1 · A5 · A6 만 구현에 맞춤(EC-25)
- [x] 반대 검토 고침(EC-14 ~ EC-23) — board 노드 · 쌍 비교의 ECAD 를 kind 별로(실패 · 한쪽만 · 세대) · diff 대상의 ECAD 의존 영역은 1단계 동안
      deferred · 노드 가족 표지 · 서로 다른 행으로 다 받았나 · 쪽 상한 · 배치 수 count/counted · 못 읽은 도구 지도는 캐시하지 않음 · 보드만 붙은
      과제의 못 읽은 보드는 409 · ECAD 카드는 어댑터 결과로 · same-as 5단계 이름 나눔
- [ ] 화면 — ProjectPage 의 ECAD 카드에 보드 찾기 · 후보 고르기 · 떼기, SnapshotPage 의 표지 이름(화면 세션 몫)
- [ ] 화면 — 보드가 붙은 과제의 웹 캡처 기본 kinds 에 ecad 를 담는다(지금 `['mcad']` 라 보드만 붙은 과제는 409, mcad 와 함께면 보드를 읽지 않는다 —
      EC-22) · 노드 kind `board` 와 comparability.ecad 를 보인다(화면 세션 몫)
- [ ] 포털 plan §2.5.3 · §2.13.5(그리고 §2.3 attrs 머리 · §2.11.3 5단계 · §2.13.2 ecad 집합)를 1단계 글로(포털 세션)
- [ ] cae00 다시 볼 시험(포털 요청서 6절 1단계 캡처) — ecad_absent 없음 · component 수 = list_parts total · layer 수 = 5종 행 수 · 빠진 칸은 표지
- [x] 결정(사용자 10-31) — 찾기 · 붙이기 확인 · 캡처 자격은 그 사람의 PAT 만이다. 없으면 찾기 · 붙이기 409 `ecad_pat_absent`, 캡처는
      결측 + 경고 `ecad_pat_absent` 이고 박스 PAT 로 내려가지 않는다(REST · MCP, mcad · dyna 폴백은 그대로 — EC-27, EC-15 닫음)
- [x] 결정(사용자 10-31) — 넷 · 배치 의존 도메인 pwr · rf 는 스냅샷 대상에서도 2단계까지 deferred 다(대표 1석만, 사유 · 입력 결손
      `ecad_nets_deferred`). 1단계 보드 캡처 뒤 pcb · soc · passive · mem 은 편성된다. 단계 스위치는 `adapters/ecad.STAGE` 하나다(EC-28)
- [x] 결정(사용자 10-31) — 모델 크기 상한 risk_max_leaf(1,500)는 MCAD 리프 + ECAD 부품 노드를 센다(층 · board 노드는 빼고). 넘으면 종전
      allow_large 길이고 409 의 글 · detail(`leaf_mcad` · `leaf_ecad`)이 몫을 나눠 말한다(EC-29).
      (한쪽에만 ECAD 가 있는 비교는 partial_scope 로 정했다 — EC-17)
- [ ] 화면 — 409 `model_too_large` 의 detail `leaf_mcad` · `leaf_ecad` 를 보이고(보드만 붙은 과제도 부품 1,500 개를 넘으면 든다),
      allow_large 확인으로 잇는다(화면 세션 몫)
- [x] 사용자 결정 10-31 셋의 시험 — 새 시험 30(test_ecad_person_pat 24 · test_ecad_adapter 6) · 변이 23/23 · 전체 3,504 통과 · xfail 4 ·
      실패 0(EC-30)
- [ ] 화면 — ECAD 찾기 · 붙이기의 409 `ecad_pat_absent`(그 사람의 포털 PAT 가 없다 · 곧 끝난다 — detail.fix `portal_pat`)를 설정 화면의
      PAT 등록으로 잇는다. 종전 코드 `ecad_credential_absent` 는 없어졌다(화면 세션 몫)
- [ ] 1단계 칸의 쌍 비교(층 두께 · 재료 · 품번 · 패키지 · 핀 수 · 높이)와 거르기 표의 행 — 표 승인과 함께. 그때 diff 대상의 ECAD deferred(EC-18)를 걷는다
- [ ] 기존 결함 — 노드 provenance.call_id 접두(snapshot_id[:8])가 원장 rr_snapshot_calls 의 call_id 접두(job_id[:8])와 달라 `tool:<call_id>` 가
      풀리지 않는다(mcad · dyna · ecad 모두, main 부터 — 반대 검토 14, EC-24)
- [ ] 2단계 ER-06 — ODB 허브 OH-01 · OH-02(가능하면 OH-03 · OH-04) 뒤. 부품 좌표 · 넷 · net 노드 · component→net 엣지 · 분류 안 된 부품 · rot 정규화 · ecad↔mcad 기하 지문
- [ ] refdes↔파트 사전 UI · `ecad.*` 이벤트 · SedInput 어댑터
- [ ] 예측기 HEAX 앱 계획서(별도 리포·매니페스트, 라벨 원천 `GET /api/export`) — 활성화 게이트 `n_labeled ≥50`·`project ≥15`

## 5. 운영·이관

- [ ] dev crontab `appdata-to-drive.sh` 일 1회(기본 03:30, RETAIN 5) — `secrets.env` 제외 패턴 additive(§10 #18 ② 승인 대기)
- [ ] cae00 이관(§8.4.4 6, P3 실측 통과 뒤) — `build-all-to-drive.sh` → cae00 `dist-from-drive.sh` → 자격 재발급 → `redeploy-app.sh hwax-risk`.
  이후 dev→cae00 은 `GET /api/export` → `POST /api/import` 만

## 6. 정본에 남은 사용자 결정

포털 `checklist.md` '착수 전 — 사용자 결정' 절의 미결 항목 중 앱 동작을 바꾸는 것만 옮겨 적는다. 코드는 각 항의 **기본값**으로 이미 돌고 있다.

- [x] **RK-01 D-1 지식 그래프 쓰기 주체**(포털 docs/request-1027 review-07 3절) — (가) 박스 쓰기 PAT(서비스 계정)로 쓰고 누가 했는지는
  `owner_sub` 가 맡는다. 종합 보고서는 사람 이름 그대로(포털 챗 PAT 길). 사용자 결정 10-31.
- [x] **RK-01 거두기**(반대 검토 10-31, context-notes RS-18 → RS-21~) — **(가) 사용자 결정 10-31**. 조직 공개였던 과제를 비공개로 되돌리거나
  폐기 · 이양하면 보류를 건너뛰는 '거두기' op 를 쌓아 RA 에 나간 객체를 다시 표기한다 — RA 가 허락하는 만큼(risk_finding 은 visibility=private
  로 바꾸고 앱이 투영한 owner · status 를 뺀다 — RA 에서 따로 단 속성은 둔다(반대 검토 RS-34), 과제는 설명을 비운다, 둘 다 값은 '비공개@<code>').
  이양은 owner 를 새 소유자로 다시 표기하고, 다시 조직 공개로 열면 보낼 op 가 이어 나가고 거둔 것은 나간 꼴로 돌아온다. 거두기는 폐기 · 다시
  열기와 겹쳐도 · 앞선 백오프가 있어도 다음 동기 주기에 나간다(반대 검토 RS-31 ~ RS-33). (b) 비공개 전환 막기 · (c) 그대로 두고 원칙 고치기는
  고르지 않았다. RA 에 지우기 · 끊기가 없고 MCP update 가 엔티티 상태(deprecated)를 넘기지 않아 객체 껍데기와 연결(exhibits · verified_by ·
  refuted_by)은 남는다. risk_finding 의 status 속성은 enum 에 retracted 를 더하는 대신 뺐다(결정의 '칸을 비운다' — enum 을 바꾸면 박스
  부트스트랩을 다시 돌려야 한다).
- [ ] #17 MCP 쓰기 귀속 — `actor` 미검증(`actor_verified:false`) 유지 vs 게이트웨이 `x-hwax-user` 전달 (기본 미채택)
- [ ] #18b 데이터 등급 — `confidential` 이면 조직 공개를 막을지 (현재 등급과 `mcp_visibility` 는 분리돼 있다)
- [ ] #29 과제 공유 기본값 — 명시 초대만(기본) vs 부서 자동 viewer / 열람 감사 로그 (기본 안 남김)
- [ ] #31 사람 finding 을 선례로 되먹일지 — `risk_prior_include_human` 기본 true
- [ ] #32 인젝션 위생 강도 — 자리표시자 차단(기본) vs 어휘 축소 vs 경고만
- [ ] #37 소스 응답 계약 위반 강도 — `risk_source_drift_block=false`+`caveat='parser_differs'`(기본) vs 차단
- [ ] #39 모델 상한 — `risk_max_leaf` 1500 · `risk_max_interfaces` 6000 · 예산 180 s(`allow_large` 600) 값 승인
- [ ] #5·6·7 로스터·마감 — 도메인 15 · ECAD 6 · 기본 마감 C2 vs C3 · carried 90일 · 패널 LLM 상한 120
- [ ] **E10 제품코드 복수 조회**(2026-09-26 발견) — `product_refs_json` 에 `product_code` 가 여럿일 때
  ㉮ 첫 값만 부른다(기본, 현재 코드) ㉯ 값마다 부르고 5줄 상한을 나눠 쓴다 ㉰ 값마다 부르고 상한을
  제품 수만큼 올린다. ㉯㉰ 는 호출 예산(§9.2)과 24 h 캐시 행 수가 제품 수에 비례해 늘어난다.
- [ ] **`bridge_stale` 판정 — 정본 내부 불일치**(2026-09-30 발견) — §2.6.2 2단계는 stale=false 를
  "K파일 filename 이 `mesh_report.artifacts.kfile` 과 같고 **그리고** pid 최대값이 part_mesh 행 수 이하"
  로 적는데, `mesh_report` 는 §2.13.3 의 정상 경로 MCP 3(`job_status`·`part_mesh_map`·`inspect_report`)에
  **없다**. 없는 근거로 'stale 아님' 이라 단정하지 않았으므로 지금은 브리지가 항상 stale 이고 **pid_map 이
  돌지 않는다**(4단계 fingerprint 추정으로 내려간다). 선택지 —
  ㉮ `mesh_report` 를 mcad MCP 4번째 호출로 추가한다(§9.2 통과 기준 2 의 'MCP 3' 숫자가 4로 바뀐다) ·
  ㉯ pid 항만으로 false 를 낸다(정본 AND 를 한 항으로 약화 — 메시가 다른 K파일에서 나왔을 때 pid 가
  우연히 맞으면 틀린 대응이 1.0/auto 로 확정된다) · ㉰ 지금대로 두고 pid_map 을 접어 둔다(브리지 엣지는
  남아 `diff`·화면이 형상↔해석 대응을 보여 주되 same-as 는 4단계가 맡는다).
- [ ] **E5− 에도 §4.8 변경 주체 접두를 붙일지**(2026-09-30 발견) — §4.8 3 은 "E5 는" 이라 적고 E5− 도
  E5 의 블록인데, §5.6.1 의 E5− 줄 형식에는 접두 자리가 없고 300자·6줄 상한을 접두가 먹는다.
  기각된 선례의 주체가 바뀐 사실은 오히려 더 중요할 수 있다 — 옛 형상에서 기각한 리스크가 지금은
  실재할 수 있다. ㉮ E5− 에도 붙인다(줄 수가 줄어든다) · ㉯ E5+ 만(현재) · ㉰ E5− 는 stale 일 때만 붙인다.
- [ ] #33·40 브리프 예산 — 기각·반증 선례(E5−)를 다른 과제 브리프에 실을지(기본 실음, 6줄 상한) · `delib_opts.evidence` 항목 상한 12 상향 (기본 접어 둠)
- [ ] #23·24 매니페스트 확정값·리포 위치 승인 — 코드·등록은 이미 그 값으로 서 있다(`squall321/HWAXRisk`, `company`, `memory_gb 2`)

## 다음 수

1장이 외부 의존이 없어 바로 된다. `x_tag_promote` 어휘·어휘 자산 정합·CurationQueue 화면은 닫혔다. 다음은
**E10 실호출**(브리프 근거 한 축이 통째로 비어 있음)이 값이 가장 크고, 그 앞에 **죽은 경로 2종**(속기록·좌석)의 정본 결정이 있다.
2장의 자격 항은 생각보다 가볍다 — 캡처는 로그인만으로 되고, 패널까지 가려면 **사용자 포털 PAT 1개**면 된다.
서비스 키는 무인 배치를 켤 때 필요하다.

남은 UI 구멍 하나 더 — `TargetPage` 가 '좌석 상태 되돌리기 · skipped 사유 입력 경로는 아직 서버에 없습니다' 라고 적어 두었는데
`PUT /targets/{key}/coverage/{agent_key}` 는 서버에 있다(클라이언트에 함수가 없을 뿐이다). §8.2.4 가 요구하는 폼이라 다음 차례다.

B25 가 남긴 작은 것 하나(2026-10-31, context-notes BL-2) — 캡처가 이제 kind 별 잘린 수를 남기므로 규칙 R-001 · R-002 의
`not_evaluable_reason='truncated'` 를 정본 §3.2.6 표대로 그 kind(R-001 interference · R-002 clearance)가 잘렸을 때만 세울 수 있다.
지금 `state.not_evaluable_reason` 은 `interfaces_truncated` 하나로 둘 다 평가 불가로 둔다(안전한 쪽이다).

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

## 리스크 심사 Claude 길 X-2(가지 `x2-claude`, 2026-10-15)

> 정본 계획은 포털 `docs/risk-claude-engine/`(PLAN · context-notes X-D1~X-D6)이고 엔진 계약은 HWAXAgentServer README '외부 응답자'
> 절(main 839fa68)이다. 기본 꺼짐 — 사람이 잡마다 고르고 동의할 때만 돈다. 실제 Claude 로 돌리는 시험은 하지 않는다(가짜만).
> 결정과 까닭은 context-notes 의 'Claude 길 X-2' 절(XR-1~)에 적는다.

- [x] 잡 선택 `llm`(glm | claude, 없음 = glm) · `consent_external` 엄격 true(아니면 422 consent_external_required) · 동의 기록(누가·언제·입구)
- [x] 엔진 /health 의 capabilities 에 external_llm 이 없으면 409 external_llm_unavailable
- [x] 엔진 호출 — limits `?llm=external` · plan `llm` · run `llm` + `consent_external` · 외부 창 판을 그 잡에 일관되게(GLM 잡의 판은 그대로)
- [x] 사슬 — 쟁점 · 종합 잡이 검토 잡의 `llm` 과 동의 기록을 물려받는다
- [x] 쟁점 패널 — `delib_opts.llm` + `consent_external` · 동의한 사람의 PAT 로만(서비스 · 남의 PAT 로 내려가지 않는다) · 브리프는 외부 evid_budget
- [x] 오류 — external_worker_absent · external_answer_timeout(인프라 → 기존 다시 내기 뒤 보류 `external_worker`, 차감 없음) ·
      review_busy external_per_owner(기다림) · external_llm_disabled · external_consent_required · external_owner_missing(설정 보류)
- [x] 무엇이 돌았나 — meta.llm · 패널 result.llm 이 external 이 아니면 Claude 로 적지 않고 `llm_mismatch` 를 잡 · 보고서에
- [x] 보고서 · 품질 글 — '판단 LLM: Claude(외부, 사용자 신고 모델)'(GLM 잡의 글은 그대로)
- [x] 길잡이 · MCP `risk_start_job` · REST 인자와 반출 경고
- [x] 시험(가짜만) — 외부 계약 예제 바이트 사본 · 카드 대조 · 패널 · GLM 회귀 · 변이 검사 · 전체 시험(공유 잠금) — 변이 22/22 · 전체 3,277 통과(b711f3a, rc 0)
- [x] 반대 검토(포털 X-D7, 10-16) 고침 — 동의는 번지지 않는다(길 · claude 쟁점 잡의 issue_rounds · 같은 길끼리만 다시 세우기 · 사람의 올리기와
      보고서 다시 내기는 GLM · 반출 경고는 대상 전체) XR-12 · MCP 동의 StrictBool(XR-2 고침) · 재개한 종합 잡의 인프라 몫 XR-13 · claude 패널
      model=external · 패널 모드의 llm=claude 422 XR-14 · 동의자 없는 잡은 닫힌 채 XR-15 · 엔진 자체 에이전트 거절 넓힘(엔진 가지 x2-gate) XR-16
- [x] X-D8 ⑦ — claude 쟁점 패널 delib_opts.target_key(엔진 x2-gate 가 외부 과제 머리에 싣는다) XR-17 — 포털 중계(DelibOpts)는 코디네이터 몫,
      그 전까지 포털 중계 시험 하나가 strict xfail
- [x] 시험 · 변이 · 전체 시험 — 새 시험 22 · 변이 앱 30/30 · 엔진 13/13 · 전체 3,299 통과 · xfail 5(rc 0, a111e95) · main 시험 교차 실패는
      검토 때와 같은 표면 고정 둘뿐 · GLM 출력은 종합 답의 llm: glm 말고 같다 — XR-18
- [ ] 엔진 가지 x2-gate 를 main 에 합치기 전까지 이 가지의 사본 가드는 `HWAX_AGENT_SERVER_REPO=<x2-gate 작업 트리>` 로 돈다(delib_frames.json)
- [ ] 포털 DelibOpts 가 target_key 를 선언 · 중계하면 strict xfail 이 스스로 꺼진다(코디네이터 몫 — 그 뒤 전체 시험 xfail 4)

## 10-31 백로그 B22 · B28 · B30 · B31 · A18(가지 `wt1031/bl-risk-api`, 2026-10-31)

> 포털 `docs/leftovers-1017/triage-1031.md` 표 B(B22 · B28 · B30 · B31)와 표 A(A18 (A) — 사용자 결정 10-31)의 리스크 앱 백엔드 몫이다.
> 결정과 까닭은 context-notes 의 '10-31 백로그' 절(BL-1~)에 적는다.

- [x] B22 — `POST /projects/{id}/sources` 응답 `duplicate_of[{project_id, code, owner_sub, created_at}]`(막지 않는다 · 구성원 과제만 — BL-1) ·
      MCP risk_add_source 같은 칸
- [x] B30 — `GET /targets/{key}/audit`(action · since · until · offset · limit ≤200, 칸은 과제 감사와 같다 · viewer 이상 · 남은 404 — BL-2) ·
      그 대상의 행을 고르는 조각 `registry.target_audit_clause`
- [x] B31 ① — `POST /targets/{key}/jobs` 의 `exclude_evidence`(항목 키 E2~E9, 밖은 422 exclude_evidence_invalid) → params_json · 그 잡 패널
      브리프에서 뺌 · `rr_panels.evidence_excluded_json` · `rr_audit(brief.exclude)` 한 행 · MCP risk_start_job 같은 인자(BL-3)
- [x] B31 ② — 통합 보고서 minutes '[사람 개입 요약]'(그 대상 rr_audit 의 action 별 수) · 사람이 넘긴 skipped 칸에 decided_by(BL-4, P4 (13))
- [x] B28 — MCP 길(미검증 actor) 패널마다 큐 항목(suspect_text · reason actor_unverified) · `PUT /curation/{id} {decision:'approve_recall'}` →
      recall_eligible=1 · `rr_audit(recall.approve)` · 카드 대조 finding 은 종전대로(BL-5, P3 (21))
- [x] A18 — 사람 finding 의 mechanism · domain 을 택소노미 어휘로 검사(422 taxonomy_invalid + 허용값 · unclassified 받음 · 코드 꼴은 대분류 +
      세부로 나눠 적음 — BL-6) · MCP 인자 설명
- [x] 시험 · 변이 — 새 시험 28(옛 코드 사본에서 24 짐) · 변이 32/32 · 전체 3,536 통과 · xfail 4(rc 0, 공유 잠금 — BL-7)
- [ ] 화면 몫(화면 세션 — 포털 트리아지 B34 · A32) — 대상 감사 '이력 탭' · RecallPreview 의 제외를 잡 본문 `exclude_evidence` 로 보내기
      (지금 화면은 '미리보기용 — 서버에 반영되지 않는다' 고 적는다) · 소스 카드의 `duplicate_of` 배지 · 큐의 미검증 신원 항목 요약 칸과
      approve_recall 설명
- [x] 감사 행을 남기지 않는 사람 조작 셋(잡 pause · resume · cancel · 등록부 status · verdict 확정 — 정본 §8.2.3 은 남기라 한다) — 남기면
      '사람 개입 요약' 에 '잡 제어 · status 변경' 줄이 선다(BL-4) — 사용자 결정 10-31 로 남긴다(아래 '사람 조작 감사' 절 · AU-1 ~)
- [x] 포털 정본 문면(포털 세션) — plan §8.2.3 의 duplicate_of 범위(구성원 과제만) · 'E키 또는 ref' 와 §5.7 '항목 제외만' 의 어긋남 · 대상 감사의
      남 답(404)과 칸(entries · total · offset) — 포털 `ccbc1b9f`(design-risk-review context-notes 새 절 — 계획서 줄은 두고 어긋남 넷을 적었다,
      읽고 확인 — MB-12)
- [x] 반대 검토 높음 — 대상 감사 · '사람 개입 요약' 에 남의 같은 클러스터 열쇠 행(공개 토글 · 큐 결정 사유)이 실림 → 맨 열쇠 행은 그 대상
      소유자의 것만 · 대상을 고른 공개 토글은 '<대상>#<클러스터>' 자리(BL-8)
- [x] 반대 검토 중간 — 한 항목의 승인이 다른 격리(의심 문구 · 미검증 신원)까지 풂 → 남은 격리를 큐 · 본문에서 다시 읽고 `applied.held`(BL-9)
- [x] 반대 검토 중간 — C3 자동 후속 Tier C 가 사람의 브리프 제외를 버림 → 물려받고 params `exclude_evidence_from`(BL-10, BL-3 일부 뒤집음)
- [x] 반대 검토 낮음 — `duplicate_of` 에 폐기 과제(BL-11) · MCP 가 돌려주는 살아 있는 잡의 제외(BL-12) · A18 전 코드 꼴 사람 finding 의
      재열쇠 스크립트 `backend/scripts/rekey_human_codes.py`(BL-13)
- [x] 시험 · 변이 — 새 시험 12 · 고친 시험 1(옛 코드 사본에서 11 짐) · 변이 18/18 · 전체 3,548 통과 · xfail 4(rc 0, 공유 잠금 — BL-14)
- [ ] cae00 배치 한 번(사람) — 앱 환경(HWAXRISK_DATA_DIR)에서 `python3 backend/scripts/rekey_human_codes.py`(dry-run — planned · skipped 를
      본다) 뒤 `--apply`(BL-13)
- [x] 등록부 병합이 별칭으로 접힌 옛 (대상, 옛 열쇠) 행을 닫지 않는다 — 정본 plan §4.3.2 3 의 `superseded` · `superseded_by` 가 없어 옛 행이
      open 으로 남아 판정 후보에 든다(종전부터 — 재열쇠 · cluster_merge · PUT merge · 재매핑 공통, BL-13, 결정 필요) — 9b41001(BE-8, main)의
      `registry._close_vacated_rows` 가 쓰는 병합마다 닫는다 · test_rekey 4걸음 시험 · PUT merge 도 같은 함수(원장 사본 탐침, MB-12)

## 남은 일 10-31 — 리스크 엔진 B23 · B27 · B29(가지 `wt1031/bl-risk-engine`, 2026-10-31)

> 포털 `docs/leftovers-1017/triage-1031.md` 표 B 의 세 줄(사용자 결정 10-31 — 표 B dev 작업). 결정과 까닭은 context-notes 'BE-1 ~ BE-10'.

- [x] B23 ① 브리프 E0 요구 한 줄 — `요구 dim_limit n · 최소 여유 ±m 단위 [req:<이름>] · 시나리오 a/b` 또는 `요구 미등록`(BE-1 · BE-2)
- [x] B23 ② E3 limit · margin 두 열 — 여유 오름차순, 미측정은 0 이 아니라 그 뒤, 요구 없는 치수는 `—`, 치수 없는 요구도 한 줄(BE-2)
- [x] B23 ③ 원자 저장 — 여유 ≤0 인 요구를 가리키며 OK 면 undetermined + parse_warnings 1건, 패널 저장 행에 requirement_ref(BE-3)
- [x] B27 로스터 동결 · 덧붙이기가 role_sha(원본 role 글 sha256[:12]) · persona_rev(그 앞 7자)를 채운다 — 원천은 list_agents(compact 끔)의
      description(BE-4)
- [x] B27 패널 의견 행에 로스터 판 사본 · nightly 스탬프에 persona_rev · E7 의 판이 다른 회수 의견에 `[이전 정의]`(둘 다 알 때만, BE-5)
- [x] B29 rekey — 네 조작(same-as reject · unmerge_key · 계면 원장 rejected · 계면 별칭 revoke)과 짝 merge_key 가 한 트랜잭션에서 plan §5.9.5
      여섯 걸음(원장 이력 · 주체 재계산 · 별칭 append/revoke · registry.merge · priors · 패턴 · 무효 큐 · rr_audit rekey)을 돈다(BE-6 · BE-7)
- [x] B29 registry.merge — 원자가 옮겨 간 옛 행을 superseded 로 닫고 다시 서면 다시 연다 · 다른 대상의 닫힘 표지는 열지 않는다(BE-8)
- [x] 시험 — 새 36(test_req_brief 8 · test_persona_rev 8 · test_rekey 20) · 옛 코드에서 32 붉음(나머지 넷은 지킴 시험) · 변이 31/31 ·
      전체 3,540 통과 · xfail 4 · 실패 0(7630563, BE-9)
- [x] rr_states 의 요구 신호(동결 · 요구 편집의 상태 재계산) — 포털 106 줄의 다른 칸(BE-10) — 가지 `wt1031/risk-flow` ac16932(RF-3)
- [ ] 코드가 세운 병합(어휘 재계산 · 자동 승계)의 등록부 접기 · 사람 확정 계면 별칭의 길 · 원자가 지워져 빈 등록부 행(BE-10)
- [ ] nightly 스탬프의 대상 전체 페르소나 판 · E7 AIDataHub 경로의 판(BE-10)
- [ ] E7 앱 DB 경로의 상태 필터(dismissed · rejected_in_panel · superseded · recall_eligible=0 제외) — 포털 152 줄의 다른 칸(BE-10)
- [ ] 화면 — SnapshotPage 여유 표 · 별칭 철회 버튼 · rekey 요약(화면 세션 몫)

### 검토 후속(10-31, 같은 가지) — 확인된 일곱 건(BE-11 ~ BE-18)

- [x] 접힌 행의 주체 — 동결 키가 그 행 키인 원자의 주체, 없으면 대표 주체를 지금 원장으로(병합 뒤에도 §5.9.4 회수가 X 로 찾는다, BE-11)
- [x] 별칭 사슬로만 닿는 대상 — 바뀐 키의 앞 키(upstream_keys)를 동결 키로 가진 원자의 대상도 다시 병합 · 패턴 · 큐도 같은 키 집합(BE-12)
- [x] 맞춘 뒤 앞 키 사슬의 5홉 점검(_check_chains) — 사람 별칭 Q → Y 위의 Y → X 가 Q 를 6홉으로 만들면 409(BE-12)
- [x] 접혀 닫힌 행의 주의 등급 D · 클러스터를 세는 곳(마감 판 · 쟁점 후보 · 종합 영역 행 · 보고서)이 registry.vacated 행을 건너뛴다(BE-13)
- [x] 별칭 맞추기 두 걸음 — 다 거두고 세운다(키 해시 차례로 409 가 갈리지 않는다, BE-14)
- [x] 쓰는 registry.merge 를 읽기부터 한 트랜잭션으로(동시 병합이 키 전파의 접힘을 덮지 않는다, BE-15)
- [x] 재매핑 별칭(taxonomy_major)의 끝에 원장 별칭을 이어 붙인다 — 재매핑 별칭은 그대로, 못 다시 만들면 건너뛴다(BE-16)
- [x] 재검토 표기는 세운 대상의 지금 행이 여전히 더 강할 때만 — 아니면 다른 대상의 더 강한 행으로 옮기거나 끈다(BE-17)
- [x] 시험 — test_rekey 새 11(옛 코드에서 10 붉음 · 지킴 1) · 변이 21/21 · 전체 3,551 통과 · xfail 4 · 실패 0(BE-18)
- [ ] 사람 별칭 세우기(PUT /registry/{k}/merge · cluster_merge 큐)의 앞 키 사슬 점검 — 키 전파 밖이라 이번에 넣지 않았다(BE-18)

## 화면 세션 10-31(A32 — 가지 `wt1031/riskfe`)

> 사용자 결정 10-31 A32 (가) — 리스크 앱 화면 일을 한 세션으로 묶어 돌린다(포털 `docs/leftovers-1017/triage-1031.md` 3절 B33 ~ B36 ·
> 요청서 넷 — risk-credentials · claude-delib-parity · ecad-1031 · m3). 1차 걸음은 B33 · B35 · B36 이다. 백엔드는 고치지 않는다.
> 결정과 까닭은 context-notes '화면 세션 10-31' 절(FE-1~)에 적는다.

- [x] B33 과제 만들기 등급 — 폼에 classification(internal · confidential, 미리 고르지 않는다) · 422 `classification_required` · 409 `E409` ·
      404 `E404` 는 code 로 그 칸에 · 과제 행 타입을 서버 열(`_project_row`) 그대로(FE-1)
- [x] B35 포털 PAT 자동 등록(risk-credentials 요청서 1절) — 앱을 열 때 `auto.enabled && due` 면 조용히 한 번(source web, 같은 탭 세션에서
      되풀이하지 않는다) · 발급 청중 mcp-gateway · step-forge(손 버튼도) · 손 버튼은 source web · 붙여 넣기는 source 없이(manual) ·
      설정에 자동 스위치와 last_source · last_at · last_error · how_to_stop · 지울 때 자동도 끄는 길(FE-2 ~ FE-4)
- [x] B35 요청서 2절 — 박스 자격 까닭(`box.reasons` 의 message · fix 를 그대로, fix 의 백틱 명령은 코드 모양, 선택 키 없음은 정보, 익명은 code 만)
- [x] B35 요청서 3절 — 반영 요약 · 재동기 응답의 채널 값이 객체(과제 화면 백지 React #31) · 보고서 반영 값 `done` · 재동기 전에도 message(FE-5)
- [x] B36 패널 잡 판단 LLM(claude-delib-parity 요청서 1 · 2절) — GLM 기본 · Claude 는 반출 경고와 미리 체크하지 않은 동의 · 체크했을
      때만 `llm` · `consent_external` · 422 · 409 는 code 로 · hwax-risk-claude 안내 · 진행판 'Claude' 배지 · GLM 본문은 바이트 그대로(FE-6)
- [x] 띄워 보고 잡은 백지 — 타깃 화면(판정 후보 `{counts, reasons}` · 패널 품질 `flags` · 패널 `id`) · 과제 화면(반영 요약 객체 · 성격 태그
      `{tag, n}` · 잡 진행 객체 'NaN%') · 잡 만들기 답(호출 어림 `{low, high}` · 자격 requester · owner)(FE-5)
- [x] 시험 — 순수 함수 · 배지 렌더(node:test, 새 의존 없이 tsc 로 옮겨 돈다) 14건 · 변이 16/16 · 실 백엔드 하네스 + 브라우저(스크래치 데이터 · 빈
      포트, FE-7)
- [x] 백엔드에 청할 것 — `how_to_stop` · `pat_unavailable` 안내의 '설정의 스위치는 곧 생긴다 — 운영자가 DB 에서' 꼬리 떼기와 '웹에서 앱을 열면
      자동 등록' 더하기(요청서 1절 끝) · 패널 잡의 422 `consent_external_required` 글이 검토 잡 반출 글이다 · 진행판 패널 잡에 `hold_code` 가
      없어 보류 external_worker 를 code 로 가를 수 없다 — 가지 `wt1031/risk-flow` 2172cb7 · 7d40238 · 83411f1(RF-6 ~ RF-8)
- [ ] 화면 — 등록부 행 타입(`claim` · `cites` · `subject` · `domain` 없음, `merged` 있음 — 행을 누르면 죽는다, M3 요청서 7절) · 과제 화면 대상 표의
      `unseated_n` · `superseded_by`(그 응답에 없다) · 과제 화면 동결 알림(스냅샷 잡은 `rr_snapshot_jobs` 라 `jobs[]` 에 없다) — 동결 알림은 2차 걸음에서 닫았다(FE-10)

### 2차 걸음 — ECAD 화면(포털 ecad-1031 화면 요청서) · B34 묶음(2026-10-31)

> 계약은 main 9bd5f48 의 '반영' 이다. 타입은 라우트 · 모델을 읽어 서버가 보내는 칸 그대로 두었다. 결정과 까닭은 context-notes FE-8 ~ FE-14.

- [x] ECAD 카드(요청서 1 ~ 5절) — `meta/adapters` 의 ecad status 로 갈래(ready 찾기 칸 · unavailable 빠진 도구 · planned 다시 읽기) · 붙은 보드의
      정체 · 찾기 칸 → 후보 표(판 · 올린 시각이 앞 열, 미리 고르지 않음, 16자리 16진이 아닌 job_id 는 잠금) · 바꾸기 · 떼기 확인 · 주인만 ·
      거절은 code 로(`ecad_pat_absent` 는 설정 길, `ecad_board_not_found` 는 후보 다시)(FE-8)
- [x] 동결 폼(6절) — 기본 kinds 에 ecad · 409 `model_too_large`(`leaf_mcad` · `leaf_ecad` 한 줄, '그래도 동결' 때만 `allow_large`) · 409
      `source_unreachable` 두 꼴(`{kinds, attached}` 는 kinds 바꾸기, `{kind: ecad, reason}` 은 보드를 못 읽음)(FE-9)
- [x] 스냅샷(7절) 보드 묶음 · 표지 열둘과 `ecad_capture_failed` · 노드 kind 거름, 비교(8절) ECAD 한 줄 · 제외 사유 말, 대상(9절) 좌석 까닭 말(FE-8)
- [x] 10절과 그 둘레 — `missing` bool 사전 · `Comparability` 전 칸 · 상태 · diff · 사건 · 동결 답(동기) · 일반 연결 ref(객체). 스냅샷 · 비교 화면이
      서버 값에서 백지였다. 과제 화면 동결 알림도 동결 답으로 연다(FE-10)
- [x] B34 스냅샷 · 비교 — 게이트 null 은 중립 '판정 불가' · 규칙 evaluable=false 는 '평가 불가' · fail 게이트 ack · 취소 · 요구 여유 표 · 키 대장 ·
      '파서 세대 다름'(행마다 까닭을 비교 가능성에서) · 대응 확정의 본문(늘 400 이던 것)(FE-11)
- [x] B34 과제 · 대상 · 홈 — 등급 · 수명 주기 · 코퍼스 제외 · 조직 공개(편집자 잠금) · 제품 연결 · 멤버 · 이력 · 이양 · 폐기 · mcad 격리 상시 경고 ·
      좌석 넘기기 · 되돌리기 · 틀린 문구 걷기 · 마지막 신호(80초) · 홈 칩 · 거름 · 등록 폼 제품 행 · 비교 목록 배지(FE-12 · FE-13)
- [x] 시험 36건 더해 50건 · 변이 20/20(하나는 처음에 살아남아 단언을 더했다) · 실 백엔드 하네스 + 브라우저(FE-14)
- [x] 백엔드에 청할 것(FE-14 끝 1 · 2 · 3 · 5 · 6 · 7 · 8) — 과제 상세 · 목록에 메타 칸과 멤버 읽기 · 상태에 ack · 키 대장 읽기 · `GET /sameas`
      의 pair_key · 도는 패널마다의 신호 · 과제 상세 스냅샷 머리의 판 칸 — 가지 `wt1031/risk-reads`(212f4a4 · f4e9a96, 화면 1d0c88a — 아래
      '화면 읽기 완결 10-31' · context-notes RD-1 ~ RD-5)
- [x] 백엔드에 청할 것(FE-14 끝 4) — 동결 때 요구 대조(`sig:req.margin`)와 요구를 고친 뒤 다시 세기 — 가지 `wt1031/risk-flow` (ac16932 — 요구를 고친 뒤 다시 세기까지, context-notes RF-3)
- [ ] 브라우저로 못 본 것 — 편집자로 과제 화면 열기(서버가 주인만 준다 — 이제 구성원에게 준다, 212f4a4 · 브라우저 확인은 남음) · 도는 검토 잡의
      일꾼 줄 · 대응 확정 단추(하네스에 후보 쌍이 없다) · 실제 ODB 허브 · 게이트웨이

### 3차 걸음 — M3 화면(포털 risk-review-redesign/m3-frontend-request 1 ~ 7절, 2026-10-31)

> 계약은 이 가지(main 9bd5f48 위)의 백엔드 코드다 — 요청서가 대조한 a27e569 뒤에 바뀐 칸(검토 잡 Claude 길 · `search_only` 바탕 · 잡 진행판의
> 빈 칸)은 코드를 따랐다. 결정과 까닭은 context-notes FE-15 ~ FE-22. 커밋 9055a0a · bc580e8 · 07e7af4 · 7cc4464.

- [x] 1절 대상 머리 — `level_label` 글 그대로(레벨 배지 옆) · 확인 안 된 막음 잔여 표지(완결 탭으로) · 사슬 배지(쟁점 패널 중 · 종합 중 · 멈춤과
      재개 · 끝, `pat_unavailable:` · `restart:` · `draining:` 의 말, `issue_yield_low` 알림) · '종합 보고서 v{n}' 링크 · M2 시절 잡 뒤의 '쟁점 ·
      종합 시작'(FE-16)
- [x] 2절 검토 진행판 — 셀 · 바탕 · 전문가 셈, 거르기 줄(승인 전 · 잡 전 · 표본 없음은 0% 가 아니다 · 넓힌 영역 · 끔 · 그림자), 입력 결손 줄,
      처분 줄, 잡 줄(단계 · 기다림 note · 다시 연 셀 몫 · 호출 ok/추정과 남은 시간 어림 · 보류 글), 품질 문면(FE-16)
- [x] 3-1 검토 잡 만들기 — 범위 넷 · 메모, 422 `consent_required` 는 추정(기대 · 낮은 끝 · 높은 끝 · basis)과 미리 체크하지 않은 동의 뒤
      `consent: true`, 409 `review_too_large` 는 추정과 함께, 그 밖의 거절은 code 로(FE-17)
- [x] 3-2 ~ 3-4 셀 격자 — 전문가 × 단위 칸(거름 · 입력 결손 표기) · 거른 까닭 말풍선 · 길 칩 · 실패만 · 상태 · 영역 · 전문가 · 단위 · 잡 범위
      거름 · 쪽 넘김, 고른 셀 · 이 잡의 실패 셀 전부의 다시(force 와 사유) · 넘김(사유 필수), `consent_required` 동의 · 걸림 셈(pack_missing 은
      모름)(FE-17)
- [x] 3-5 동의 — `reopened_extra.hold` 로 가른다 — consent_extra 는 몫을 보이고 체크 뒤 `resume?consent=true`, max_calls 는 재개를 잠그고
      기다리는 셀 넘기기(`filter {job_id, state: "pending"}`)를 앞에(FE-17)
- [x] 3-6 보류 풀기(패널 대상만) · 3-7 전문가 보고서(md 쪽 · part 넷 · 판 대조)(FE-17 · FE-19)
- [x] 4절 쟁점 탭 — 제기 · 반대 분포 → 쟁점 패널 결과 한 줄 · 다시 토의 표기 굵게 · 패널 발언 · 올리기 · 건너뛰기(사유 · 편성 · 도는 쟁점은
      잠금) · `ledger_rev` 가 바뀌면 처음부터 · 순위 정렬(FE-18), 패널 탭에 종류 · 쟁점 id 열
- [x] 5절 종합 보고서 — part 탭 · 쪽 넘김 · 둘째 쪽부터 판 · 409 면 1쪽부터 다시 · 마크다운은 글로만 · 머리(제목 · 계기 · 시각 · 서술 정도) ·
      '다시 내기' · '요약부터 다시'(살아 있는 종합 잡이면 잠금) · 판 없음(FE-19)
- [x] 6절 완결 — 표기 · 저장 · 지금 · 마감 레벨(내려간 계산의 말) · C1 · C2 · C3 · 잔여 표(막음/표기 · 확인 상태 · 누가 · 사유 · 시각) · 확인
      (사유 · basis_hash 그대로) · 409 `residual_changed` 는 다시 읽고 다시 확인 · 확인 취소 · 다시 세기 · 영역 깊이 · 확인 이력 · 보고서 판
      링크(FE-20)
- [x] 7절 등록부 — 행 타입을 서버 꼴로(행을 누르면 `cites.length` 에서 백지였다, FE-7) · 주의 등급 열 · 지지 수 넷 · 쟁점 칸('원래 — 제기 N명 →
      쟁점 패널 결과' · 다시 토의 표기) · 주의 거름(cells 기본 A · B) · 단위 거름 · 패널만 본 비교 보기(FE-21)
- [x] 대상이 바뀌면 화면 상태를 처음부터(같은 라우트라 앞 대상의 고른 셀 · 탭이 넘어갔다 — 합성 대상은 단위 id 까지 같았다)(FE-15)
- [x] 서버 견본(`src/contract/serverSamples.ts` — 실 응답을 줄여 tsc 가 타입과 견준다) · 시험 25건 더해 75건 · 변이 33/33 · 타입 변이 7/8 ·
      실 백엔드 하네스 + 브라우저(FE-22)
- [x] 백엔드에 청할 것(FE-22 끝) — 쟁점 행 `outcome_json` 이 늘 null(`_loads` 기본값 None) · 쟁점 결정 뒤 완결 캐시 새로 쓰기 · 같은 초에 선
      검토 잡의 고르기(`id DESC`) · 사슬 표지 칸 — 가지 `wt1031/risk-flow` 046c327 · 14ebb56 · a57ff8b · 896e7c8(RF-1 · RF-2 · RF-4 · RF-5)
- [ ] 짓지 않은 것 — 검토 잡의 판단 LLM 고르기(요청서 8절 — 화면은 Claude 잡이면 배지만), 셀 하나 경로(판정 행 · 호출 목록)
- [ ] 브라우저로 못 본 것 — 편집자 · 보기 역할의 403(하네스 신원이 하나다) · 도는 잡의 기다림(health_unknown · draining) · max_calls 보류 ·
      거른 셀이 있는 대상(하네스 대상은 거름 0) · 다시 토의 표기가 선 쟁점 · 실제 에이전트 서버 · 포털

### 4차 걸음 — 리뷰 후속(검증된 지적 13건, 2026-10-31)

> 지적마다 먼저 재현했다(스크래치 jsdom 하네스 · 백엔드 사본 · SQLite) — 13건 다 재현, 다 고쳤다. 백엔드는 고치지 않았다. 결정과 까닭은
> context-notes FE-23 ~ FE-30. 커밋 5ea092f ~ 1021e30.

- [x] 높음 — 쟁점 다시 토의 표기의 두 꼴(label · new_panel_failed 뿐인 행을 누르면 앱 전체가 백지) · 견본 · 화면 자리의 오류 경계(FE-23)
- [x] 중간 — 등록부 상태 변경에 target_key(빠지면 같은 cluster_key 의 다른 대상 행까지 바뀌었다)(FE-24)
- [x] 낮음 — 완결 fresh=1 은 그 읽기 한 번(FE-25) · 과제 스냅샷 머리 degraded 는 첫 code | null(FE-26)
- [x] 동의 — 셀 격자 다시 열기(요청이 바뀌면 걷는다) · consent_extra(몫에 묶는다) · Tier C 승인(만든 뒤 · 티어를 바꾸면 걷는다)(FE-27)
- [x] 확인 — 키 대장(노드마다 다시 마운트 · 독립 키 확정) · 잡 취소(검토 · 패널) · 멤버 빼기 · 역할 · 등급 · 수명 주기 · '그래도 동결' 은
      거절된 본문 그대로(FE-28)
- [x] PAT 자동 등록 — 실패 뒤 받은 PAT 폐기(저장 전 거절은 곧바로, 모호하면 GET /me 로 가른다) · 브라우저 쉼 · cred_key_invalid 면 받지
      않는다(FE-29)
- [x] 시험 12건 더해 87건 · 변이 8/8 · jsdom 하네스로 13건 · 실 Chromium 셋(FE-30)
- [x] 백엔드에 청할 것(FE-30 끝 1 · 3 · 4) — confirm_key 의 병합 키(409 key_merged, a9e9cb3) · 스냅샷 머리 degraded_json(212f4a4) · 키 대장
      읽기(f4e9a96) — 가지 `wt1031/risk-reads`(context-notes RD-1 · RD-4 · RD-6)
- [x] 백엔드에 청할 것(FE-30 끝 2 · 5) — 웹 등록 실패 기록(브라우저 쉼도 걷었다) · 다시 토의 표기 꼴 하나로 — 가지 `wt1031/risk-flow`(30e002c · a3aaec2 · f134686, context-notes RF-9 · RF-10)
- [ ] 브라우저로 못 본 것 — 실 백엔드 · 실 포털의 revoke-self · 동의 · 확인 조작들의 실 브라우저 클릭(jsdom 으로 봤다)

## 사람 조작 감사 — 잡 제어 · 등록부 status · verdict 확정(가지 `wt1031/risk-audit`, int1031/risk2 7b1042d 위, 2026-10-31)

> 사용자 결정 10-31(포털 세션의 답) — 심사의 길을 바꾸는 사람 조작은 정본 plan §8.2.3 대로 rr_audit 를 남긴다. 위 '10-31 백로그' 의 열린 줄
> '감사 행을 남기지 않는 사람 조작 셋'(BL-4)을 닫는다. 결정과 까닭은 context-notes 의 '사람 조작 감사' 절(AU-1~)에 적는다.

- [x] 잡 제어 — `POST /jobs/{id}/pause|resume|cancel`(MCP `risk_job_action` 은 같은 함수) → `rr_audit(scope job, action job.pause|resume|cancel)`
      한 행 · 앞 · 뒤는 상태와 보류 코드뿐 · 바꾼 것이 없는 조작(끝난 잡의 취소 · 이미 그 상태 · 도는 호출을 기다리는 검토 잡의 다시 취소)과
      거절된 조작은 남기지 않는다 · 정지 · 재개는 같은 트랜잭션, 취소는 커밋 뒤(AU-1 · AU-3 · AU-5 — 반대 검토 고침에서 취소도 전이와 한
      트랜잭션으로, AU-8)
- [x] 등록부 status — `PUT /registry/{cluster}/status` → 바뀐 (대상, 클러스터) 행마다 `rr_audit(scope registry, subject '<대상>#<클러스터>',
      action registry.status)` 한 행 · 앞 · 뒤는 status 와 상태 기록 seq 뿐(note · evidence_ref 는 싣지 않는다) · `registry.set_status` 의
      `changes`(REST 응답에서는 뺀다 — AU-2 · AU-5)
- [x] verdict 확정 — `PUT /targets/{key}/verdict` → 확정마다 `rr_audit(scope target, action verdict.final)` 한 행 · 앞 · 뒤는 판정 값뿐(note 는
      싣지 않는다)
- [x] 세 행이 `GET /targets/{key}/audit` · 과제 감사와 통합 보고서 minutes '[사람 개입 요약]' 에 선다(같은 조각 `registry.target_audit_clause` —
      action 줄 job.cancel · job.pause · job.resume · registry.status · verdict.final)
- [x] 코드가 일으킨 전이(일일 상한 · 줄어드는 수확 · 코드 보류 · 자동 재개 · 재기동 복구 · 집기 · 취소의 마감 · 엔진 쪽 멈춤 A24)는 남기지
      않는다 — 'system' 표시가 아니라 빼는 쪽(AU-4) · 폐기의 잡 취소와 셀 넘김의 재개는 그 행위의 행에 이미 있다(A24 는 반대 검토 고침에서
      사람의 job.pause 로 — AU-9)
- [x] 시험 · 변이 · 전체 시험 — 새 시험 9(옛 코드 사본에서 8 짐 · 지킴 1) · 고친 시험 1(test_p6_routes 손 신원의 source) · 변이 22/22 · 전체
      3,722 통과 · xfail 4 · 실패 0(rc 0, e21ca9a, 공유 잠금 — AU-6)
- [x] 사람 라벨(`POST /findings/{id}/labels`)의 등록부 status 변경 감사(AU-7, 결정 필요) — 엔진 쪽 멈춤(A24)은 반대 검토 고침에서 남긴다(AU-9)
      — 닫음(결정이 필요 없다) — plan §0.6 은 라벨 훅 전이를 rr_audit 에 넣지 않고 *_source 로 가른다(label_manual · rr_labels 의 labeled_by —
      메인 세션 10-31 읽기, AU-15)
- [x] 포털 정본 문면(포털 세션) — §8.2.3 잡 제어의 `{reason≤200}`(앱은 받지 않는다) · 요약의 묶음 이름 · 등록부 status 감사의 자리와 칸(AU-7) ·
      A24 멈춤의 job.pause(엔진이 알린 사람 · actor_verified 0 · web — AU-11) — 포털 `90c121ca`(plan §8.2.3 세 줄 · 회의록 '사람 개입 요약'
      정의를 구현에 맞춤, 읽고 확인 — MB-12)
- [x] 화면(화면 세션) — 대상 감사 '이력 탭'(B34)에 새 action 셋의 이름표(AU-7) — 가지 `wt1031/risk-gaps` 77e5480 에서 했다(과제 이력 탭의
      이름표 다섯 · 전 → 후, AU-14)

### 반대 검토 고침(10-31, 같은 가지 — 16f2595 위) — 지적 둘(AU-8 ~ AU-11)

- [x] 반대 검토 중간 — 검토 잡 취소의 감사 행이 취소 트랜잭션 밖(전문가 보고서 다시 짓기 뒤)이라 그 사이 실패 · 멈춤에 사라지고 앞 · 뒤에
      러너의 집기 · 마감이 섞임 → `runner.cancel_job(on_change=)` 가 전이와 같은 트랜잭션에서 행을 쓴다 · 패널 · 쟁점 갈래도 그 트랜잭션 안에서
      잡을 다시 읽고 정한다(AU-8, AU-5 일부 뒤집음)
- [x] 반대 검토 낮음~중간 — 포털 화면의 '멈춤'(엔진 쪽 멈춤 A24)이 잡을 멈춰도 감사 행이 없음 → 멈춘 사람이 메일이면 그 사람의 job.pause
      (actor_verified 0 · web, '운영' · 빈 값은 없음) — 사용자 결정 10-31 의 '사람의 요청으로 같은 일을 하는 러너 길'(AU-9, AU-4 일부 뒤집음 ·
      사용자가 (나) 뺌을 고르면 69e18d6 을 되돌린다)
- [x] 시험 · 변이 · 전체 시험 — 새 시험 8(옛 코드 사본에서 5 짐 · 지킴 3) · 고친 시험 1 · 변이 17/17 · 전체 3,730 통과 · xfail 4 · 실패 0
      (rc 0, 69e18d6, 공유 잠금 — AU-10)

## 사람 조작 감사 — 남긴 줄 셋 고침(가지 `wt1031/risk-gaps`, int1031/risk4 b71a262 위, 2026-10-31)

> 사용자 결정 10-31 — 사람 조작 감사(AU-7 · AU-11)가 남긴 줄 셋을 지금 고친다. 결정과 까닭은 context-notes 의 '남긴 줄 셋 고침' 절(AU-12 ~)에
> 적는다. 화면 파일이 감사 가지 판에 없어 통합 판 b71a262 로 앞감기한 뒤 일했다(백엔드는 6f345d0 과 같다).

- [x] 남긴 줄 1 — MCP 길의 감사 행은 입구 mcp · actor_verified 0 — job.create(검토 · Claude 패널) · brief.exclude · target.flow ·
      project.ecad_board 는 검증을, gate.ack · finding.create · panel.repersist(_discard) · rekey(same-as reject)는 입구와 검증을 신원 출처에서
      정한다 · 키 전파 넷은 라우트의 입구를 넘겨받는다 · 웹 쿠키 행은 이제 web(AU-12 — 4eea6b6)
- [x] 남긴 줄 2 — MCP risk_job_action 의 changed 는 감사 행과 같은 판정(`routes.job_control` 의 바뀜 — 전이와 같은 트랜잭션의 상태 · 보류
      코드) · 틀린 쪽은 changed(행은 AU-3 대로) · 확인과 취소 사이에 끝난 잡의 changed true 도 같이 고쳤다 · REST 응답은 그대로(AU-13 — c232e55)
- [x] 남긴 줄 3 — 과제 이력 탭(B34)의 이름표 다섯 · 전 → 후를 코드 어휘 그대로(잡 상태 · 보류, 등록부 status · 상태 기록 번호, 판정 값)
      (AU-14 — 77e5480)
- [x] 사람 라벨 경로의 감사 — 닫음(plan §0.6 의 라벨 훅 전이, 메인 세션 10-31 읽기 — AU-15)
- [x] 시험 · 변이 — 백엔드 새 시험 11(13 항목, 옛 코드 사본에서 11 짐 · 지킴 2 — 29a3bc3 의 지킴 둘은 변이를 세다 더했다) · 고친 시험 1
      (test_gate_ack 손 신원의 source) · 변이 33/33 · 화면 새 시험 3(옛 화면 사본에서 3 짐) · 변이 12/12 · pnpm test 90 · build 통과 ·
      전체 3,743 통과 · xfail 4 · 실패 0(rc 0, 77e5480, 공유 잠금 — AU-16)
- [ ] MCP 가 닿지 않는 REST 전용 감사 자리의 입구 · 검증(AU-12 — 이 앱의 REST 를 게이트웨이 rest_call 사람별 단언으로 열 때 같은 꼴로)
- [x] 화면 — '미확인' 배지 풀이(MCP 행 · A24 멈춤 행에 꼭 맞지 않는다) · 이름표가 없는 다른 행위(AU-14, 화면 세션 몫) — 가지
      `wt1031/risk-labels` 01a9f8d · 88d32d9 에서 했다(AU-17 ~ AU-20)

## 이력 탭 이름표 전부 · '미확인' 풀이(가지 `wt1031/risk-labels`, main 4145b2c 위, 2026-10-31)

> 사용자 결정 10-31(이력 탭 이름표 후속 — 메인 세션). 결정과 까닭은 context-notes 의 같은 절(AU-17 ~)에 적는다.

- [x] 앱이 rr_audit 에 쓸 수 있는 행위 39 가지 모두에 이름표(빠진 24 를 더함 — 말은 화면의 단추 · 안내 글을 따른다, AU-17 — 01a9f8d)
- [x] 빠지면 지는 시험 — backend tests/test_audit_action_labels.py 가 앱 소스(AST)에서 행위를 끌어내 화면 사전과 견준다(앱 코드 변경 없음,
      풀 수 없는 식 · 모르는 f-string 꼴은 실패, AU-18)
- [x] '미확인' 배지 풀이를 행을 쓴 길마다(MCP 위임 신원 · 포털 '멈춤' 의 에이전트 서버가 알린 사람 · system 의 모르는 뒤처리, AU-19 — 88d32d9)
- [x] 시험 · 변이 — 1 은 4145b2c 사본에서 짐 · 변이 14/14, 2 는 01a9f8d 사본에서 화면 시험 둘 짐 · 변이 7/7, pnpm test 91 · tsc -b · vite build
      통과(각각 rc 0), 백엔드 이름표 시험 · test_client_contract 통과(AU-20)

## 화면 읽기 완결 10-31(가지 `wt1031/risk-reads`, main dbe5f93 위)

> 화면 세션(위 '화면 세션 10-31' 의 FE-14 · FE-30 끝)이 청한 읽기 일곱이다. 결정과 까닭은 context-notes '화면 읽기 완결 10-31' 절(RD-1~).
> 커밋 — 212f4a4 · f4e9a96 · a9e9cb3 · 1d0c88a · 2bb6314.

- [x] `GET /projects/{id}` — 구성원(편집자 · 보기) 200 · 남은 없는 과제와 같은 404 · 과제 행 메타 열(corpus_excluded bool · product_refs_json 배열) ·
      응답 머리 members[{email, role}] · 대상 · 잡은 과제 주인으로 고른다 · 스냅샷 머리 label · app_versions · adapter_versions · degraded_json(RD-1, 212f4a4)
- [x] `GET /projects` — 소유 ∪ 구성원 과제 · 카드 classification · lifecycle · corpus_excluded · my_role(MCP 목록도 부른 사람의 역할)(RD-2, 212f4a4)
- [x] `GET /snapshots/{id}?part=state` — 게이트 G1 ~ G6 에 지금 살아 있는 ack(취소 · 비교 스코프 · 낡은 것 빼고) · gates_hash(RD-3, f4e9a96)
- [x] `GET /part-keys/{ckey}` — 키 대장 한 행 · 주인 / 그 키가 든 과제의 구성원 · 남과 없는 키는 같은 404 E404 · 남 시험 표(RD-4, f4e9a96)
- [x] `GET /sameas` 의 pair_key · 진행판 패널 잡 `signals`(러너가 대상마다 패널 하나라 많아야 한 줄 — RD-5, f4e9a96)
- [x] sameas confirm_key 의 병합 키 — 409 key_merged(병합은 unmerge_key 로만 푼다, RD-6, a9e9cb3)
- [x] C3 자동 후속 Tier C 는 GLM — 의도된 동작으로 적고 지키는 시험 · 주석(RD-7, 2bb6314)
- [x] 화면 — 키 대장 지금 상태 · 병합 키 확정 잠금 · 대응표 서버 pair_key · 닫은 때 · ack 꼬리 걷기 · 타입 · 실 응답 견본 일곱(RD-8, 1d0c88a)
- [x] 시험 · 변이 · 전체 시험 — 백엔드 새 시험 아홉(옛 코드에서 아홉 다 짐) · 고친 시험 둘 · 지키는 시험 하나 · 변이 22/22 · 화면 시험 일곱(87 → 94,
      옛 화면 코드에서 tsc 깨짐 · 셋 짐) · 화면 변이 7/7 · 전체 3,724 통과 · xfail 4 · 실패 0(rc 0, 2bb6314, 공유 잠금)(RD-9)
- [x] 구성원 읽기를 스냅샷 · 대상 · 진행판 · 성격 · 유사 · 요구 · 등록부까지 열지(지금은 주인만 — 편집자가 과제 화면에서 그 링크 · 탭을 열면 404,
      plan §14 두 계정 시나리오, RD-9 남긴 것 1 — 결정 필요) — 사용자 결정 10-31 '계획서대로 구성원도 읽는다' · 07ed329(MB-1 ~ MB-5)
- [ ] 옛 confirm_key 가 남긴 행(status confirmed · merged_into 남음) 고치기(RD-6) — 세는 쿼리는 MB-9(dev 0)
- [ ] 잡의 concurrency 칸(화면 '동시 실행 ≤2')은 러너가 읽지 않는다 — 칸 · 문구를 둘지(RD-5, 결정 필요)
- [ ] 같은 초에 선 두 패널 잡의 진행판 고르기(`coverage_payload` 의 `created_at DESC LIMIT 1`, RD-9 남긴 것 4)
- [ ] 화면(화면 세션) — 과제 화면 스냅샷 표의 이름 · 판 · 강등 표지 전부 · '파서 세대 다름' 미리 보이기 · 대상 표 unseated_n · superseded_by
- [ ] 브라우저로 못 본 것 — 편집자로 과제 화면 · 키 대장 패널 · 대응 확정 단추(견본 렌더 · 계약 시험만)

### 반대 검토 고침 10-31(같은 가지 — context-notes RD-10 ~ RD-15)

> 반대 검토가 확인한 지적 다섯 — 스크래치 사본에서 그 검토의 탐침으로 먼저 재현했다. 커밋 — f560f34 · a73f7ca · 956812c · c1edf3c · 7ac4ea7.

- [x] (High) 들여오기가 남의 과제에 매달린 줄을 받던 것 — 쓰는 줄의 부모(과제 · 스냅샷 · 동결 잡 · 대상 · 비교)가 부른 사람 것이 아니거나 없으면
      parent_not_owned, 남의 이메일 owner 멤버 행은 owner_row_immutable · 표 차례로 쓴다 · project_role 의 owner 는 과제 주인 열만 · 목록 · 카드
      역할도 같다 · 과제 상세 · 목록의 스냅샷 · 이름 잇기 · 소스 · 성격 · 상태의 ack 는 주인의 행만(RD-10, f560f34)
- [x] (Medium) 키 대장 읽기의 `mine` · 화면이 남의 원장 행(과 404)이면 결정 넷을 잠그고 '다른 사람의 원장 행' 이라 말한다 · 견본 셋(RD-11, a73f7ca)
- [x] (Low) 스냅샷 상태의 gates.summary 신호 · summary_text [게이트] 줄도 지금 ack · 상태 견본 두 칸(RD-12, 956812c)
- [x] (Low) `GET /sameas` 의 G2 도 지금 ack · RD-3 의 틀린 줄 고침(RD-13, c1edf3c)
- [x] (Low) 과제 메타의 닫은 때는 진행(active)이면 보이지 않는다(RD-14, 7ac4ea7)
- [x] 시험 · 변이 · 전체 시험 — 백엔드 새 열 · 고친 하나(옛 코드에서 열하나 짐) · 변이 26/26 · 화면 94 → 99(옛 코드에서 넷 · 옛 견본까지 여섯 짐) ·
      화면 변이 10/10 · 전체 3,734 통과 · xfail 4 · 실패 0(rc 0, 공유 잠금) · 커밋마다 대상 시험 통과(RD-15)
- [ ] 고침 전에 선 남의 멤버 행(편집자 · 보기)은 아직 역할이다 — 박스에서 `rr_project_members.owner_sub <> rr_projects.owner_sub` 행을 세고
      나오면 지울지 정한다(RD-10 남긴 것 — 사람) — 이양으로 다시 찍힌 행까지 세는 감사 흔적 쿼리를 더했다(MB-9 ① ② ③, dev 0) · 구성원 읽기로
      그런 행이 읽는 것이 넓어졌다 — 반영 전에 센다
- [x] 이양은 키 대장 행(rr_part_keys)을 옮기지 않아 새 주인은 그 과제의 키를 결정하지 못하고, 남이 같은 ckey 의 키 행을 먼저 들여오면 그 키의
      주인이 된다(열쇠가 ckey 하나) — 원장 열쇠 (ckey, owner_sub) 또는 이양이 옮기기(스키마 · 결정 필요, RD-10 · RD-11 남긴 것) — 사용자 결정
      10-31 '들여오기 선점만 막는다' · 1a18503(MB-6) · 이양은 옮기지 않는 것이 설계 · 열쇠는 그대로(MB-7)
## 리스크 흐름 10-31 — 화면 세션이 청한 결함 · 잡 / 쟁점 흐름(가지 `wt1031/risk-flow`, main dbe5f93 위)

> 화면 세션(FE-7 · FE-14 · FE-22 · FE-30 끝)이 백엔드에 청한 것 가운데 잡 · 쟁점 흐름 열 가지다. 화면이 '모름' 으로 비워 둔 칸은 서버가
> 채우면 화면이 고치지 않고 보이는지(읽는 칸 이름)까지 봤다. 결정과 까닭은 context-notes 'RF-1 ~ RF-13'. 같이 도는 가지 `wt1031/risk-audit`
> (잡 제어 · status 변경 감사)의 함수(job_action · put_verdict · put_registry_status · registry.set_status)는 건드리지 않았다.

- [x] 1 쟁점 행의 `outcome_json` 이 늘 null(`_loads(…, None)` 의 형 검사) — 원장 값을 싣는다(REST · MCP risk_get_issues 같은 함수, 046c327 — RF-1)
- [x] 2 `PUT /issues/{id}` 뒤 완결 캐시를 같은 트랜잭션에서 새로 쓴다 — 진행판 level_label · qualifiers 와 그 캐시로 보낸 확인의 409(14ebb56 — RF-2)
- [x] 3 요구 여유 — 동결이 요구를 대조(sig:req.margin)하고 요구를 고치면(등록 · 상태 · 승계) 그 과제 스냅샷의 상태를 같은 트랜잭션에서 다시
      센다 · 게이트 ack 는 그대로(ac16932 — RF-3)
- [x] 4 같은 초에 선 두 검토 잡 — 진행판 review.job · review_cells._latest_review_job 과 같은 잡의 품질을 읽는 셋을 rowid 로(a57ff8b — RF-4)
- [x] 5 진행판 검토 잡에 사슬 표지 `chain`(params.chain) · 화면의 'M2 시절 잡 뒤 사슬 시작' 을 그 칸으로(896e7c8 · a3aaec2 — RF-5)
- [x] 6 진행판 패널 잡에 `hold_code` · `hold_until`(같은 초는 rowid) · 화면의 '멈춘 까닭' 이 보류 코드를 보인다(83411f1 · a3aaec2 — RF-6)
- [x] 7 패널 잡의 422 `consent_external_required` 글을 패널 잡의 것으로(runner.PANEL_EGRESS_WARNING, 7d40238 — RF-7)
- [x] 8 `how_to_stop` · `pat_unavailable` 안내(과 entry.fix_register_pat)의 '스위치는 곧 생긴다 — 운영자가 DB 에서' 꼬리 떼기 · '웹 리스크 앱을
      열 때' 더하기(2172cb7 — RF-8)
- [x] 9 `PUT /me/portal-pat` 의 웹 등록 거절을 portal_pat.auto 에 적기 · `due` 가 그 쉼을 본다(`paused_until`) · 화면의 브라우저 쉼 걷기(탭마다
      한 번 문은 남김)(30e002c · a3aaec2 — RF-9)
- [x] 10 (선택) `_keep_verdict` 도 at · round 를 적는다(있는 값은 그대로)(f134686 · d4c565d — RF-10)
- [x] Tier C 후속 노트 — Claude Tier B 잡 뒤 C3 자동 후속 Tier C 는 GLM 이다(잡마다 반출 동의, 사용자 결정 10-15 — 의도, 바꾸지 않았다) ·
      `_finish_job` 주석 · 고정 시험(7d40238 — RF-11)
- [x] 서버 견본(화면 tsc 가 견주는 것) — 쟁점 목록 · 다시 토의 표기 새 꼴 · 보류된 패널 잡 진행판 · 쉬는 PAT 요약 · 상태의 요구 여유를 이 가지
      하네스의 실 응답으로(a3aaec2 — RF-12)
- [x] 시험 · 변이 — 백엔드 새 18 · 바뀐 6(고치기 전 사본에서 21 붉음 · 지킴 셋), 화면 87 → 89(고치기 전 사본에서 셋 붉음), 변이 백엔드
      25/25 · 화면 6/6, `tsc -b` · `vite build` · `pnpm test` 통과(RF-13)
- [x] 리스크 전체 시험 한 번(공유 잠금) — 3,731 통과 · xfail 4 · 실패 0(rc 0, d260b83, 13분)
- [x] 길마다 자동 등록 쉼 나누기 — 지금은 기록 하나 · 쉼 하나라 게이트웨이 교환 실패도 앱을 열 때의 자동 등록을 쉬게 한다(RF-9, _user_prefs 에
      열이 든다 — 결정 필요) — 닫음 · 열 없이 기록의 머리(`web-`)로 길마다 쉰다(반대 검토 10-31 지적 2, 659b251 — RF-15)
- [ ] 브리프의 패널 잡 메모 고르기(`brief.py` M 항목 — `created_at DESC, id DESC`)도 같은 초면 앞 잡일 수 있다(RF-4, 이번 범위 밖)

### 반대 검토 10-31 — 세 지적(같은 가지, 8d42a84 위)

> 셋 다 재현했다(고치기 전 코드에서 새 시험이 붉다). 결정과 까닭은 context-notes 'RF-14 ~ RF-17'. routes.py 는 자동 등록 쉼 · 웹 거절 기록 ·
> 폐기 주석만 손댔다(main b71a262 과 저절로 합쳐진다). main 과 겹치는 것은 runner.cancel_job 한 줄이다(풀이는 RF-14).

- [x] 1 보류로 멈춘 패널 · 쟁점 잡을 취소해도 hold_code 가 남아 취소된 잡의 진행판 줄 · 사슬 단계가 보류를 싣고 화면이 '워크플로를 다시 돌린 뒤
      재개' 를 말했다 — 취소가 재개처럼 보류 열을 비우고, 화면의 '멈춘 까닭' 은 paused 일 때만 읽는다(1b05177 · e269f7a — RF-14)
- [x] 2 기록 하나가 두 길을 함께 쉬게 했다(게이트웨이 교환 실패 → 앱을 열 때의 자동 등록 6시간 멈춤, 다른 계정으로 누른 설정 버튼 → Claude 길
      6시간 멈춤, 웹 실패가 Claude PAT 고칠 글을 덮음) — 기록의 머리로 길마다 쉰다 · 설정 글 · 견본(659b251 · e269f7a — RF-15)
- [x] 3 동결이 요구 원장을 넣는 트랜잭션 앞에서 읽어 그 틈에 저장된 요구가 새 스냅샷의 req.margin · R-007 에서 빠졌다 — 읽기를 트랜잭션
      안으로(3cf27f3 — RF-16)
- [x] 시험 · 변이 — 백엔드 새 6 · 바뀐 1(고치기 전 코드에서 8 붉음), 화면 89 → 91(고치기 전 사본에서 1 붉음 — 게이트웨이 견본 시험은 화면을
      고치지 않고 통과), 변이 백엔드 10/10, 합친 판(main b71a262 + 이 가지 · 충돌 한 줄 풀이)의 관련 시험 270 통과(RF-17)
- [x] 리스크 전체 시험 한 번(공유 잠금) — 3,737 통과 · xfail 4 · 실패 0(rc 0, 963f661, 13분 47초)

## 구성원 읽기 · 들여오기 키 선점 10-31(가지 `wt1031/risk-members`, main 3a188f3 위)

> 사용자 결정 둘(10-31) — '계획서대로 구성원도 읽는다' · '들여오기 선점만 막는다'. 결정과 까닭은 context-notes MB-1 ~ MB-12.
> 커밋 — 07ed329(구성원 읽기) · 1a18503(들여오기 키 선점).

- [x] 구성원(편집자 · 보기) 읽기 — 과제에 딸린 REST 읽기 전부(스냅샷 · 규칙 적중 · 대상의 단위 · 진행판 · 완결 · 쟁점 · 보고서 · 셀 · 전문가 ·
      등록부 · 좌석 · 패널 · 발언 · 동결 브리프 · 성격 · 유사 · 요구) · 고르는 행은 과제 주인의 것 · 남은 없는 것과 같은 404 · 주인의 길 그대로
      (`_reader`, MB-1)
- [x] 두 과제에 걸친 것 — 비교(두 과제를 다 읽고 행 주인이 한쪽의 주인) · 대응표(대상 스냅샷 주인의 쌍 원장) · 유사 · 선례(D46) · 참조의
      스냅샷 · 비교 스코프와 req · voc · paper(MB-2)
- [x] 목록 셋(대상 · 비교 · 보고서) — 제 행 ∪ 구성원 과제의 과제 주인 행(MB-3)
- [x] MCP — 볼 수 있는 과제의 멤버는 편집자 · 보기 행만 · 문지기는 행 주인이 그 과제(비교는 한쪽)의 주인이거나 부른 사람일 때만 · 대응표 입구가
      웹 라우트를 그대로(MB-4)
- [x] 쓰기는 그대로 — 보기의 쓰기 가드 45 · `GET /targets/{key}/brief`(편성 · 토큰 — 쓰기)는 주인만 · 완결 fresh 는 파생 캐시라 읽기(MB-5)
- [x] 들여오기 — 새 rr_part_keys 행은 부른 사람의 과제 · 스냅샷 · 노드가 쓰는 키만(이 박스에 있거나 같은 본문에 앞서 오는 노드), 아니면
      `ckey_not_referenced` · 기존 행 병합은 그대로(MB-6)
- [x] 이양과 키 원장 — 옮기지 않는 것이 설계(처음 적립한 사람의 행) · 옛 주인의 다시 들여오기는 RD-10 · MB-6 이 눕힌다(MB-7)
- [x] 화면 — 주인만 읽기에 기대 숨긴 탭 · 칸이 없어 고치지 않았다(MB-8)
- [x] 세는 쿼리(cae00 · 읽기만) — 남의 멤버 행 ① 주인 열 ② 감사 흔적 ③ owner 행 · RD-6 옛 키 행 · MB-6 영향, dev 다 0(MB-9)
- [x] 시험 · 변이 — 새 103 + REST D46 하나(옛 코드에서 35 짐) · 들여오기 넷(옛 코드에서 선점 하나 짐 · 셋은 지킴) · 변이 28/28 · 6/6(MB-10)
- [x] 리스크 전체 시험 한 번(공유 잠금) — 3,897 통과 · xfail 4 · 실패 0(rc 0, 1a18503, 13분 26초 — MB-10)
- [x] (결정) 계획이 편집자에게 연 쓰기 — 스냅샷 동결 · 소스 · 치수 · 계면 원장 · 요구 · 게이트 ack · 등록부 status · verdict 는 코드가 주인만이다
      (넓히지 않았다, MB-5) — 사용자 결정 10-31 '계획서대로 편집자도 쓴다' · 58f5c07(MB-14)
- [x] (결정) 관리자(risk_admin_roles) 읽기 우회를 구성원 읽기에도 넓힐지 — 지금은 멤버 · 이력 · 대상 감사만(MB-1) — 사용자 결정 11-01
      (계획서 조건부) · 계획서가 전 과제 편집자로 적어 넓혔다(context-notes OI-5)
- [x] (결정) risk_next_step 을 구성원에게 열지 — 다음 걸음이 주인의 쓰기다(MB-4) · 편집자가 그 쓰기를 하게 된 뒤에도 길잡이는 주인 과제만(MB-19)
      — 사용자 결정 11-01 · 읽기 문으로 열고 보기는 쓰기 걸음 대신 막힘(context-notes OI-3)
- [x] (화면 세션) 구성원에게 보이는 주인 쓰기 단추 · 대상 화면 브리프 탭의 404 배너 — 대상 응답에 역할 칸이 없다(MB-8) · 편집자 쓰기(MB-14) 뒤로는
      편집자의 쓰기 · 브리프가 서고 보기만 403 배너다 — 사용자 결정 11-01 · 과제 상세 · 진행판 my_role 로 잠그고 까닭(context-notes OI-2)
- [ ] (cae00 · 사람) MB-9 쿼리를 반영 전에 센다 — 남의 멤버 행이 나오면 지울지 정한다
- [x] (높음 · 결정) 대응 결정 confirm · reject 가 남의 rr_sameas 행을 뒤집는다(upsert 에 주인 거름 없음 — 종전부터) — 구성원 읽기가 그 열쇠를 보기에게
      열어 보기가 쓰는 길이 됐다. 열쇠를 주인별로 또는 그 과제 주인 · 편집자만 받기(MB-11) — 사용자 결정 10-31 '주인 · 편집자만, 주인으로
      지킨다' · a6daeb8(MB-13)
- [x] (범위 밖) brief._MEMBER_OF · 러너 자격 후보가 owner 멤버 행도 센다 · 합성기 IR 의 엣지 attrs.note null 이 rr_ir.v1 밖(MB-11) — 조정자 요청
      10-31(같은 갈래) · c99634f(MB-16) · a49e85f(MB-17 — 합성기 해석 조건 해시도)

## 대응 결정 · 편집자 쓰기 · 이양 10-31(같은 가지 `wt1031/risk-members`)

> 사용자 결정 셋(10-31) — 대응 결정 '주인 · 편집자만, 주인으로 지킨다' · '계획서대로 편집자도 쓴다' · 비교는 '둘 다 받은 사람에게 옮긴다'.
> 결정과 까닭은 context-notes MB-13 ~ MB-19. 커밋 — a6daeb8 · 58f5c07 · 3618953 · c99634f · a49e85f · b9798ec.

- [x] 대응 결정 — confirm · reject 는 pair_key 의 과제(pair 는 둘 다)의 주인 · 편집자 · 그 과제 주인의 원장 행 · 두 주인이면 422 · 남의 행은
      409 sameas_row_foreign(upsert 에도 주인 거름) · 키 전파는 행 주인으로 · MCP 같은 문(MB-13)
- [x] 편집자 쓰기 — 쓰기 문 하나(`_writer`) · 계획이 연 쓰기 31 · 주인만 남긴 것 12 · 사람 칸은 부른 사람 · 행은 주인의 원장 · 보기 403 · 남
      404 · 관리자는 편집자 · 동결 자격은 시작한 사람의 PAT · 별칭 철회 감사는 원장 주인으로(MB-14)
- [x] 이양 — 비교 · 변경 항목 · 대응 원장(intra · pair)은 모든 쪽 과제가 받는 사람에게 모이면 옮긴다(앞 주인 기록 — 다른 길로 모여도) · 한쪽만은
      그대로 · 남이 적어 넣은 행은 그대로 · 새 주인의 같은 쌍 비교 500 · 대응 409 막힘을 함께 닫음(MB-15)
- [x] 같은 갈래 — 브리프 · 러너의 구성원 판정은 편집자 · 보기 행만(MB-16) · IR 계약 note null · 합성기 해석 조건 해시(MB-17)
- [x] 시험 · 변이 — 대응 결정 10 짐 · 변이 9/10(겹 거름 하나 살아남음) · 쓰기 표(45 경로 · MCP 13 · 낱 7) 33 짐 · 변이 24/24 · 이양 4 짐 · 7/7 ·
      같은 갈래 짐 · 5/5(MB-18)
- [x] finding 쓰기 문이 카드 대조 finding 을 거른다 · 그 거름 자리를 래칫 표에 — 전체 시험의 가드 둘이 잡았다(b9798ec, MB-14 · MB-18)
- [x] 리스크 전체 시험(공유 잠금) — 3,979 통과 · xfail 4 · 실패 0(rc 0, b9798ec, 12분 47초 — 앞 두 판은 가드 하나씩 붉음, MB-18)
- [x] (결정) 기존 편집자 길(`_target_editor` — 잡 · 좌석 · 셀 · 쟁점 · 보고서 · 단위 · 방식 · 사람 finding 만들기)도 대상 행 주인 = 과제 주인을
      볼지 — 남이 매단 대상에 편집자가 쓸 수 있다(MB-19) — 조정자 요청 10-31 · 845fdd5(다시 저장 · MCP 잡 시작까지, MB-20)
- [x] (결정) 생산자 diff_json 이 rr_diff.v1 밖(최상위 pair_kind · 조립품 주체 asm:…) — 계약을 넓힐지 생산자를 맞출지(MB-17) — 사용자
      결정 11-01 · 계약을 생산자 · 정본 쪽으로(context-notes OI-1)
- [ ] (합칠 때) wt1031/risk-concurrency 의 progress_json panels 지도 — 과제 상세 jobs[].progress · 진행판 job.signal 이 그대로 보인다(MB-19)
- [x] (시험 lint · 이 가지 밖) tests/test_claude_panel_jobs.py 의 같은 이름 시험 둘(F811 — 앞의 것이 돌지 않는다) · test_backup_wrapper_run.py(MB-19)
      — 6f24240(앞의 것 이름을 바꿔 둘 다 통과 · 쓰지 않는 import, MB-21)
- [x] 리스크 전체 시험(공유 잠금, 6f24240 — 조정자 요청 두 건 뒤) — 4,000 통과 · xfail 4 · 실패 0(rc 0, 12분 57초 — MB-21)

## 패널 잡 동시 실행 — 잡의 concurrency 를 실제로 읽는다(가지 `wt1031/risk-concurrency`, main 3a188f3 위, 2026-10-31)

> 사용자 결정 10-31 — 잡 만들기 칸 '동시 실행 ≤2'(`POST /targets/{key}/jobs` 의 concurrency)는 저장만 되고 러너가 읽지 않았다(RD-5) —
> "실제로 짓는다". 동시 2 잡은 제 패널을 둘까지 함께 돌리고 동시 1(기본)은 종전 그대로다. 결정과 까닭은 context-notes 'CC-1' 부터.
> routes.py 는 진행판(coverage_payload)의 signals 줄만 손댄다(같은 때 도는 구성원 읽기 · 들여오기 가지와 겹치지 않게).

- [x] 계획 — 러너가 잡마다 도는 패널을 센다(러너 메모리 · 패널 행에 잡 열이 없다) · 편성은 틱 스레드에서 · 전역 자리(HWAXRISK_CONCURRENCY)는 그대로
      (CC-1 · CC-2 · CC-4)
- [x] 집기 — 잡의 자리 수(`job_slots` — concurrency 를 전역 자리 수로 다시 묶고 Claude 잡은 1) · 둘째 자리는 첫 패널을 기다리는 잡이 없을 때만 ·
      대상의 다른 잡 패널이 돌면 건너뜀(종전 대상 직렬) · 하루 상한 · 수확 체감 · 엔진 자리 없음 뒤 쉼 · 편성할 좌석 없음은 둘째 자리를 막기만
      (6fc775a — CC-2 · CC-3 · CC-7 · CC-8)
- [x] 편성 · 마감 — 틱이 편성하고 워커는 그 패널을 돈다(`plan_job_panel` · `run_panel(panel=)`) · 남은 좌석이 없어도 도는 형제가 있으면 끝내지
      않는다(6fc775a — CC-4)
- [x] 멈춤 · 취소 · 보류 — 잡이 running 을 떠나면 도는 패널 전부가 닫힌다(실패 failed 도) · 닫힌 형제의 글이 까닭을 말한다 · 취소는 워커가 다 끝난
      뒤 cancelled · 재개한 잡은 앞 패널이 닫힌 뒤 · 감사 행은 사람 조작마다 하나 그대로(6fc775a — CC-6)
- [x] 패널마다 신호 — 동시 2 잡은 progress_json 에 패널별 칸 · 진행판 signals 가 도는 패널마다 한 줄 · 동시 1 잡의 잡 행은 바이트째 종전
      (6fc775a — CC-9)
- [x] 엔진 자리(429) — 둘째 패널이 예산을 다 써도 형제가 돌면 잡을 멈추지 않는다 · 그 대상의 둘째 자리는 예산 동안 · 그때 돌던 형제가 도는
      동안 쉰다(예산 0 박스에서 쌓이지 않게)(6fc775a · 다음 커밋 — CC-8)
- [x] Claude 길 — 판단 LLM claude 잡은 동시 1 로 묶고(만들 때 저장 · 집을 때도) 답에 concurrency_note · MCP 인자 설명(6fc775a — CC-5)
- [x] 원장 불변식(2) — 대상의 도는 패널 수 ≤ 살아 있는 잡의 자리 수 · 연속 실패 셈은 도는 패널을 건너뜀(6fc775a — CC-10 · CC-12)
- [x] C3 자동 후속 Tier C 가 동시 실행을 물려받는다(6fc775a — CC-11)
- [x] 화면 — 신호 줄이 signals 마다 한 줄 · 잡 만들기 답의 concurrency_note · 서버 견본(두 줄) · tsc · build · pnpm test 107 → 108(0fddbdf)
- [x] 시험 — 새 22(고치기 전 사본에서 다 진다 — 동작으로 지는 것과 이름이 없어 지는 것은 CC-14) · 변이 백엔드 30/30 · 화면 4/4(600d538 ·
      a78f702 · 다음 커밋)
- [x] 리스크 전체 시험 한 번(공유 잠금) — 3,811 통과 · xfail 4 · 실패 0(rc 0, 31df680, 12분 41초). 그 앞 판(5625832)은 씨앗 출처 래칫
      하나가 붉었다(새 시험의 손 INSERT — 52088fa 에서 생산자 경로로 걷었다, CC-14)
- [ ] 포털 정본 문면(포털 세션) — design-risk-review/plan.md §6.4 '타깃당 패널은 직렬 · 서버 전역 동시 패널은 타깃이 다를 때만' · Settings 표의
      HWAXRISK_CONCURRENCY '타깃 다를 때만' · §6.7 의 '타깃당 직렬' 을 CC-1 의 뜻으로(대상 안에서 잡끼리는 직렬, 잡 하나는 제 자리 수까지)
- [x] MCP risk_start_job 이 같은 Tier 의 살아 있는 잡을 돌려줄 때 그 잡의 concurrency 를 싣지 않고 differs 에도 넣지 않는다(entry.start_job —
      이번 범위 밖, 결정 필요) — 사용자 결정 11-01 · 도는 자리 수를 싣고 다르면 differs(context-notes OI-4)

### 반대 검토 10-31 고침(같은 가지 — 2229b32 위, context-notes CC-16 ~ CC-27)

> 메인 세션이 받은 독립 반대 검토 F1 ~ F10 — 하나씩 재현한 뒤 고쳤다(2229b32 사본에서 이번 시험 29 가운데 23 이 진다 · 지킴 6). F3 은 메인 세션의
> 결정(검토자의 제안대로)이다.

- [x] F1 — 둘째 자리 집기가 형제의 멈춤을 덮고(error NULL) 둘째 패널을 세우던 것 — 집기의 쓰기를 읽은 상태 조건의 한 문장으로 · 기다림 글도 같은
      조건 · 워커가 엔진에 보내기 바로 앞에서 다시 묻는다(ec9e040 — CC-16 · CC-17)
- [x] F8(종전부터) — 첫 자리 집기가 사람의 취소 · 정지를 running 으로 덮던 것 · 자정 재개 · 하루 상한 정지 · 취소 마감도 같은 조건(ec9e040 — CC-16)
- [x] F2 — 미룬 수확 체감 정지가 마지막 형제가 실패로 끝나면 사라지던 것 — 미뤄 둔 멈춤 칸 · 마지막 형제가 어떻게 끝나든 옮김 · 재개가 걷음 ·
      집기의 안전망(ec9e040 — CC-18)
- [x] F3(메인 세션 결정) — 패널 하나의 일(의장 실패 · 브리프 오류 · 일시 장애 잇달음 · 벽시계 · 침묵 · 절단 · 연속 실패)은 형제가 끝날 때까지 미루고
      새 자리만 막는다 · 사람 · A24 · 보류 · persist_error · 자격은 곧바로 · 형제를 닫던 시험 둘 고침(ec9e040 — CC-18 · CC-19)
- [x] F4 — 러너의 자동 전이(정지 · 보류 · 실패)는 확인과 쓰기를 한 트랜잭션으로(_stop_job) · 두 스레드 경합 시험(ec9e040 — CC-20)
- [x] F5 — 재기동 복구가 끊긴 잡의 패널별 칸 · 미뤄 둔 멈춤을 걷고, 적는 쪽은 도는 패널의 칸만(ec9e040 — CC-21)
- [x] F7(종전부터) — 편성기의 선점 경합에 남은 좌석이 있으면 잡을 끝내지 않는다(ec9e040 — CC-22)
- [x] F10 — 동시 실행 1 ~ 2(밖이면 422 · job_slots · create_job) · C3 후속은 job_slots · 셈은 닫힌 차례(ec9e040 — CC-23)
- [x] 문서 — F6(CC-15 의 delib_paused 줄은 닿지 않는 길이라 뺐다) · F9(CC-6 의 '20초' 고침 · 동시 1 잡에서 달라진 것 전부 CC-24) · cae00 반영 때
      이미 2 로 저장된 잡을 보고 묶는 법(CC-25)
- [x] 변이 33 가운데 32(살아남은 하나는 잡이 둘까지만 도는 동안 같은 판 — CC-26) · 관련 시험 638 통과
- [x] 리스크 전체 시험 한 번(공유 잠금) — 3,837 통과 · xfail 4 · 실패 0(rc 0, 8d18a7b, 13분 25초)
- [ ] 포털 cae00 절차서에 CC-25 의 줄(포털 세션)

### 반대 검토 2차 10-31 고침(같은 가지 — c4bdfa7 위, context-notes CC-28 ~ CC-37)

> 메인 세션이 받은 2차 검토(R2-1 ~ R2-8 · N31) — 하나씩 재현한 뒤 고쳤다(c4bdfa7 사본에서 새 시험 16 가운데 15 가 진다 · N31 고정 하나는 같다).

- [x] R2-1 — 엔진 자리(429)를 기다리던 패널이 형제가 미룬 멈춤을 읽지 않고 심의를 보내던 것 · 미뤄 둔 동안 잡 error 의 '잡을 멈췄다' 꼬리
      (e91db9b — CC-28)
- [x] R2-2 — 기동 복구가 끊기지 않은 대상의 running 잡에 남은 미뤄 둔 멈춤을 옮긴다 · 옮겨야 칸을 걷는다(running · queued)(e91db9b — CC-29)
- [x] R2-3 — 엔진 실패 둘 뒤의 자격 실패가 failed/engine_fail_streak 로 묻히던 것(잡을 먼저 옮긴다)(e91db9b — CC-30)
- [x] R2-4(종전부터) — 집은 뒤 편성 전의 사람 취소를 잡 마감이 completed 로 덮고 C3 후속 · 사슬을 잇던 것(e91db9b — CC-31)
- [x] R2-6 — 사람의 정지 · A24 가 미뤄 둔 멈춤을 걷고 까닭을 남긴다 · 취소도 걷는다 · 진행판 signal · signals 와 과제 잡 목록 progress 에서 뺀다
      (e91db9b — CC-32)
- [x] R2-7 — MCP 스키마 1 ~ 2 · 검토 잡에 준 concurrency 는 한국어 까닭 그대로 · 0 · 음수 422 · MCP 입구의 살아 있는 잡 갈래도 범위를 본다 · 인자 계약
      고정본(e91db9b — CC-33)
- [x] 문서 — R2-5(닫힌 차례 셈이 동시 1 잡에서도 바꾸는 판정 · CC-23 · CC-24 고침, CC-34) · R2-8(안전망은 전역 자리를 얻은 틱에서만 · 좀비 running
      패널, CC-35) · CC-18 · CC-21 의 해당 줄
- [x] N31 — 셋째 도는 패널을 편성기로 세워 '미룬 실패를 나중의 미룬 멈춤이 덮지 않는다' 를 직접 묶음(CC-36)
- [x] 시험 대역 — `_InFlight` 의 during 안 실패가 러너에 삼켜지던 것을 `_DuringFailed` 로 올림(1차 시험 48 그대로 통과, CC-36)
- [x] 변이 24/24 · 관련 시험 532 통과(CC-36)
- [x] 리스크 전체 시험 한 번(공유 잠금) — 3,853 통과 · xfail 4 · 실패 0(rc 0, e91db9b, 13분 15초)


## 남은 일 다섯 11-01(가지 `wt1101/risk-open`, main 2460cd0 위)

> 사용자 승인 11-01 — 결정과 까닭은 context-notes 'OI-1' 부터(줄 번호 = OI 번호).

- [x] ① 생산자 diff_json 이 `rr_diff.v1` 밖 — 계약을 정본 · 생산자에 맞춤(pair_kind 필수 · 사건 주체 열쇠 code 마다 · 제외 사유 13종 ·
      차단 capture_partial), 실제 생산자 본문 여섯을 검증하는 계약 시험 · 구성원 시험의 검증 끔을 걷음 · 화면 견본(OI-1)
- [x] ② 보기 · 서버가 거절할 사람에게 쓰기 단추를 잠그고 까닭을 보인다 — 편집자는 계획이 연 것, 주인만의 것은 주인만(OI-2) — 과제 상세 ·
      진행판 my_role · /me risk_admin, 화면 넷(과제 · 대상 · 비교 · 스냅샷)과 카드 열넷, 시험 roles.test.cjs
- [x] ③ `risk_next_step` 을 구성원에게 — 읽기 문(_project_reader)으로 과제 주인의 행을 걷고 보기는 쓰기 걸음 대신 role_insufficient ·
      목록은 소유 ∪ 구성원 · 자격 칸은 부른 사람의 등록 · 못 읽는 계보 과제는 싣지 않음 · 스냅샷 · 동결 잡은 과제 주인의 행만(OI-3)
- [x] ④ MCP 살아 있는 잡을 돌려줄 때 도는 자리 수(concurrency)를 싣고 새 잡이 받을 자리 수와 다르면 differs · 같은데 적게 돌면
      concurrency_note(OI-4)
- [x] ⑤ 관리자 읽기 우회 — 계획서(§0.6 · §5.2.1)가 관리자를 전 과제 편집자(⊃ 읽기)로 적었다 · 웹 읽기 문 전부 · 키 대장 · 유사 ·
      선례 · 원장 참조 · 대상(diff) 만들기의 읽기 판정 · 목록 · MCP 는 그대로(OI-5)
- [ ] (결정) §5.2.1 '관리자 접근도 rr_audit 에 남는다' — 쓰기 · 읽기 우회 어디에도 없다(OI-5) · 관리자의 발견 목록을 전 과제로 넓힐지(OI-5)
- [ ] 포털 정본 문면(포털 세션) — plan §3.3.1 봉투의 pair_kind · §3.3.5 사건의 subject.dns 꼴(OI-1)
- [ ] 브라우저로 못 본 것 — 보기 · 편집자 · 소유자로 과제 · 대상 · 비교 · 스냅샷 화면의 잠김과 까닭(정적 렌더 시험 · tsc · 빌드까지, OI-2)
