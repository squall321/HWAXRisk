<!-- HWAXRisk 앱 리포 작업 대장 — P0~P6 진척과 앱 몫 잔여 백로그. 포털 정본 checklist.md 에서 앱 몫만 떼어 와 실측으로 갱신한다 -->
# HWAXRisk 체크리스트

계획 정본은 `HWAXPortal/docs/design-risk-review/{plan.md, checklist.md}` 다. 이 문서는 **앱 리포가 실제로 무엇까지 했고 무엇이 남았는지**를
코드 대조로 확인해 적은 작업 대장이며, 앞으로의 진행은 이 문서를 늘려 가며 한다. 정본 체크리스트는 단계 착수 전에 쓴 것이라 P1~P7 항목이
전부 미체크로 남아 있다 — 여기서 실측한 완료 상태가 그보다 최신이다.

마지막 실측 2026-09-29 — `pytest` **1184 passed, 2 skipped**(`test_parity` 는 `HWAX_PORTAL_REPO` 미설정) · `ruff` 통과 · `pnpm build` 통과.

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
| P7 ODB 실연동 | §9.8 | **미착수**(조건부 — ODB hub 계약 합의 대기) | `adapters/ecad_stub.py` 만 |

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
- [ ] **정본 통과 기준 대조에서 남은 4건**(2026-09-26, 식별자 전수 대조로 발견) —
  ① **범위를 잘못 적었다 — `ambiguous_bridge_key` 가 없는 게 아니라 브리지 자체가 없다.** `part_mesh_map`
  을 아무도 부르지 않고(`mcad.py` 주석이 "캡처가 한 번도 부르지 않는다" 고 적어 둔 그대로) `kind='bridge'`
  엣지를 만드는 코드가 0건이다. 그래서 `attrs.dyna.bridge.join_key`·`bridge_stale`·`ambiguous_bridge_key`
  가 전부 없고, 그 엣지를 입력으로 쓰는 `sameas` 2단계 `pid_map` 과 `diff` 의 `cross.bridge_stale` 이
  **구조적으로 죽어 있다**. 정본 MCP 3 예산(§2.13.3 `job_status`·`part_mesh_map`·`inspect_report`) 중
  코드는 `job_status`·`interface_graph` 둘만 부른다 — `inspect_report` 의 `source_inconsistent` 교차 검증도
  함께 없다. P2 산출물 한 덩이라 별도 단위로 한다 · ② **완료(2026-09-29, ↓ 1장)** · ③ `rr_findings.finding_json.cited_by_later[]`
  (§5.6 (4)) — 인용된 선례에 후속 `claim_uid` 를 누적해야 '선례가 실제로 쓰였는지' 의 원자료가 된다 ·
  ④ 등록부 `subject_ckeys` 를 `resolve_ckey()` 로 해석하는지(§5.9.1) — 이름이 다를 수 있어 의미 대조가 필요하다.
  ①②는 어댑터 픽스처가 선행이고 ③④는 원자·별칭 경로를 건드려 한 번에 하지 않았다.
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
- [ ] **E10 제품코드 복수 조회**(2026-09-26 발견) — `product_refs_json` 에 `product_code` 가 여럿일 때
  ㉮ 첫 값만 부른다(기본, 현재 코드) ㉯ 값마다 부르고 5줄 상한을 나눠 쓴다 ㉰ 값마다 부르고 상한을
  제품 수만큼 올린다. ㉯㉰ 는 호출 예산(§9.2)과 24 h 캐시 행 수가 제품 수에 비례해 늘어난다.
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
