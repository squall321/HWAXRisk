<!-- 판정표 원장(RK-01 ~ RK-07) 설계 — 칸 정의 · 덮어쓰기 층 · 판 · 근거 묶음 · 결정 반영 · 숫자 원장 · 보고 묶음 · 출처 표지 · 표기 규칙과 PC 수용 절차 -->
# 판정표 원장 — RK-01 ~ RK-07

포털 `docs/request-1117`(PLAN §1 · contracts.md · context-notes R-2 ~ R-4)의 리스크 앱 몫이다. 사용자 팀이 PC 스크립트로 하던 판정표 관리 ·
근거 묶음 · 결정 반영 · 숫자 점검 · 보고 묶음을 앱이 갖는다. 과제 자료(과제 · 모델 · 부품 · 넷 이름 · PC 경로)는 리포에 넣지 않는다 — 칸 이름 ·
facts 키 · 실제 판정표는 PC 수용 때 등록하는 데이터다. 아래 예의 값은 모두 합성 값이다.

## 1. 표(v8)

모든 표가 대상 열쇠(`target_key` — `snap:` · `diff:`)에 매달린다. 반출 · 들여오기 · 회수는 그 대상의 과제를 따른다.

| 표 | 무엇 |
|---|---|
| `rr_ledger_templates` | 틀의 판 — `columns`(칸 정의) · `facts`(보고 묶음 틀) · `decision_map`(결정 칸 → 원장 칸). 같은 몸이면 새 판을 세우지 않는다 |
| `rr_ledger_layers` | 덮어쓰기 층 — 이름 · 차례 · 원천 파일 · `{코드: {칸: 값}}`, 결정 반영 층은 칸 상태 · 표결을 `meta` 에 |
| `rr_ledger_versions` · `rr_ledger_rows` | 판(기준 판 · 칸 정의 판 · 보안 문구 · 덮은 층 차례)과 그 행(열쇠는 코드) |
| `rr_ledger_cells` | 판을 지을 때 층이 덮은 칸 하나하나와 그 앞 값 — 층 차례가 병합 스크립트 안에만 있던 것을 데이터로 |
| `rr_evidence_bundles` | 심의 근거 묶음(evidence 원문 gzip · 지문 · 칸별 자수 · 가림 수) |
| `rr_ledger_numbers` · `rr_ledger_forbidden` | 숫자 원장 · 코드별 금지값 |
| `rr_ledger_exports` | 내보내기 · 보고 묶음 기록(누가 어느 판을 어떤 꼴로 · 지문) |

감사 행(`rr_audit`)은 쓰지 않는다 — 화면 이력 탭에 이름표가 없는 행위는 코드만 보인다(시험 `test_audit_action_labels`). 쓴 사람은 각 표의
`created_by` · `updated_by` 다.

## 2. 도구 · 경로

| 일 | MCP | REST | 문 |
|---|---|---|---|
| 한눈 | `risk_ledger_overview` | `GET /api/targets/{key}/ledger` | 읽기 |
| 틀 적기 | `risk_ledger_put_template` | `PUT …/ledger/templates/{kind}` | 편집자 |
| 층 쌓기 | `risk_ledger_put_layer` | `POST …/ledger/layers` | 편집자 |
| 판 짓기 | `risk_ledger_build` | `POST …/ledger/versions` | 편집자 |
| 판 비교 | `risk_ledger_diff` | `GET …/ledger/versions/{v}/diff?base=` | 읽기 |
| 내보내기 | `risk_ledger_export` | `GET …/ledger/versions/{v}/export?fmt=csv\|json` | 읽기(기록) |
| 근거 묶음 | `risk_build_evidence_bundle` · `risk_get_evidence_bundle` | `POST …/evidence-bundles` · `GET /api/evidence-bundles/{id}` | 편집자 · 읽기 |
| 결정 반영 | `risk_ledger_apply_decision` | `POST …/ledger/layers/from-decision` | 편집자 |
| 숫자 원장 | `risk_numbers_put` · `risk_numbers_check` | `PUT …/numbers` · `POST …/numbers/check` | 편집자 · 읽기 |
| 보고 묶음 | `risk_export_report_bundle` | `GET …/ledger/versions/{v}/report-bundle` | 읽기(기록) |
| 출처 표지 | `risk_get_provenance`(+ 스냅샷 · 등록부 · 단면 자리 · 길잡이 답) | `GET /api/projects/{id}/provenance` | 읽기 |
| 표기 규칙 | `risk_taxonomy(part="labels")` | `GET /api/taxonomy/labels` | 공용 |

읽기는 대상의 구성원(MCP 는 다른 읽기 도구와 같은 시야 — 소유 · 구성원 · 조직 공개), 쓰기는 편집자 이상이고 MCP 쓰기는 게이트웨이 위임 신원만이다.

## 3. 정한 것

- **칸 정의** `{columns: [{name, order, grade?, sp_key?, axis?, figure?}], notice?, code_label?}` — `grade` 칸이 '등급 바뀐 코드' 셈에 들고, `axis`
  (grade · type · attention · verdict)가 근거 · 보고 묶음의 표기를 정한다. 칸 이름에 판정 낱말(OK · FAIL · 치명 따위)이 들면 받지 않는다(좌석이 칸
  이름을 판정으로 인용했다).
- **덮기** — 층은 `order` 차례(목록 차례가 아니다)로 덮고 같은 칸이면 뒤 층이 이긴다. 한 번 짓기 안에서 차례가 겹치면 422 다. 층의 null 은 그 칸을
  비운다. 빈 칸(null · 빈 글)은 서로 같다. 같은 (기준 판 · 층 · 칸 정의 판)이면 지은 판을 돌려준다.
- **셈은 행이다** — 값 안의 줄바꿈은 행 수를 바꾸지 않는다. 등급 바뀐 코드는 두 판에 다 있는 코드만 센다(든 코드는 추가다).
- **근거 묶음** — 칸 하나가 근거 항목 하나(`R-001 | 값` 한 줄에 코드 하나, 빈 값은 '(빈 칸)'), 맨 앞 색인은 실은 코드 전부와 '이 목록 밖의 행은 싣지
  않았다(없다는 뜻이 아니다)'. 색인은 자기 지문을 담을 수 없어 '본문 지문'(색인 뒤 항목들의 같은 셈)을 싣는다 — 묶음의 `fingerprint` 는
  contracts §1 의 식 그대로 evidence 전체의 것이다. 칸 상한은 그 항목 글 전체(머리 · 잘림 안내 포함), 합 상한은 틀 차례로 남은 만큼이다. 엔진 상한
  (`HWAXRISK_BUNDLE_MAX_ITEMS` · `HWAXRISK_BUNDLE_MAX_CHARS`, 기본 120 · 135,538 — knobs.env)은 `result` 글자 합(색인 포함)으로 잰다.
- **가림**(`app/pii.py`) — 메일 · 휴대 · 지역 전화(하이픈 · 빈칸으로 가른 꼴, +82) · 사설 IPv4 · 주민번호 꼴 · 표지 붙은 사번. 가르지 않은 긴 숫자열 ·
  소수 · 코드 · 버전은 건드리지 않는다(게이트웨이 HG-21 의 교훈). 사람 이름은 꼴로 가르지 않는다.
- **결정 반영** — `decision_json` · `decision_text` · `job_id` 가운데 하나. job_id 는 그 사람의 포털 PAT 로 게이트웨이 `deliberate_result` 를
  `view="decision_json"` 으로 먼저 부르고, 엔진이 그 꼴을 모르면 `view="summary"` 의 결정문을 쪽마다 이어 읽는다(표결은 그 답의 votes.tally).
  칸마다 filled · empty · conflict · no_source — conflict 칸도 층에 싣는다(판 짓기가 덮을지는 사람이 본다). 패널 결과 다시 저장의 길은 쓰지 않는다.
- **숫자 점검** — 작은 정수까지 세고, 코드 · 키 꼴 낱말 속 숫자는 수로 보지 않는다. 원장 코드 · 지표 키와 같은 머리인데 원장에 없는 id 는
  unknown_ids 다. 근거 묶음을 주면 줄마다 코드를 안다.
- **보고 묶음** — 틀의 키를 전부 채운다(빈 키는 null 과 `null_reasons`). id 는 내용 지문(`rb_`), 근거 묶음은 `eb_` — id 만으로 둘이 갈린다.
- **인용 형식**(contracts §5 C1) — 두 묶음 모두 `cite{source_platform: "hwax_risk", source_kind: risk_bundle | risk_report_bundle, source_id,
  source_version: "v<판>/c<칸 정의 판>", scope{target_key, codes}}`.
- **출처 표지** — 앱이 가진 값만 싣는다. 환경 낱말은 게이트웨이 낱말 `dev` · `prod` · `unknown`(원래 낱말은 `env_raw`).

## 4. 원천 앱이 내줘야 채워지는 칸(11-17 dev 소스 대조)

| 앱 | 칸 | 지금 | 청할 것 |
|---|---|---|---|
| StepForge | 과제 단계 | 앱이 부르는 도구(프로젝트 상세 · 트리 · 계면 · 시스템 상태)에 없다 — `list_projects` · `what_next` 에만 | `GET /api/projects/{id}` 에 `stage` · `stage_code`(empty · files · parsed · detected · deck) |
| StepForge | 설계 판 이름 | `get_project_meta.revision` 에만 | 같은 상세에 `revision{rev_label, rev_seq, model_key, task_code, status}` |
| StepForge | 환경 | `system_status` 에 없다 | `env` · `instance` · `app` · `build` |
| DynaForge | 덱에 적힌 요소 수 | `inspect_file` 의 `elements` 는 같은 id 를 덮어쓴 뒤의 고유 수다 | `elements_declared` · `duplicate_element_ids{count, top}` |
| DynaForge | 덱 판 | 없다 | 덱 `title` · `sha256`, `report_summary` 에 `source_kfile{id, filename, sha256}` |

DynaForge `system_status` 의 `env` 는 이미 나온다 — 캡처가 `app_version.extra.env` 에 남긴다. 지금 잴 수 있는 신호는 덱 파트 수 대 요소가 있는 파트
수(요소 없는 파트 경고)와 검출 흔적 없음 · 계면 0(이른 사본 경고)이다.

## 5. PC 수용 절차(실제 판정표 대조)

과제 자료는 PC 에서만 다룬다. 순서 —

1. 대상(`snap:` · `diff:`)을 고르고 `risk_ledger_put_template(kind="columns")` 로 실제 판정표의 칸 20개를 등록한다(등급 칸에 `grade: true`, SP 사전 키
   칸에 `sp_key: true`, 증거 유형 칸에 `axis: "type"`).
2. 기준 행 층으로 첫 판을 짓는다 — `risk_ledger_build(layers=[{name: "기준 행", order: 10, rows, source_file}])`.
3. 덮어쓰기 층 다섯을 병합 스크립트의 차례 그대로 `order` 를 주어 쌓고(앞 회차 행 → 뒤 회차 행 → 수기 수정 → 이어하기 결과 마지막) 기준 판 위에 짓는다.
4. `risk_ledger_export(fmt="csv")` 의 셋째 줄부터를 PC 의 다음 판 csv 와 칸 단위로 견준다 — 수용 기준은 칸 차이 0 · 행 수 · 층마다 덮은 칸 수 · 등급
   바뀐 코드 수가 PC 기록과 같다는 것이다.
5. 근거 틀(칸별 상한 · 합 상한)로 `risk_build_evidence_bundle` 을 만들고 `risk_get_evidence_bundle` 의 evidence 를 `deliberate_start(evidence=…)` 에
   넣어 본다 — `label_check.violations_n` 0, 색인의 코드 목록이 실은 행 전부인지 본다.
6. 결정이 나면 `decision_map` 틀을 등록하고 `risk_ledger_apply_decision(job_id=…)` — 칸 상태 수와 합의 문장 대조를 PC 의 결정 파싱 결과와 견준다.
7. 숫자 원장 · 금지값을 넣고 결정문 · 근거 묶음을 `risk_numbers_check` 로 본다. facts 틀을 등록하고 `risk_export_report_bundle` 의 facts 를 PC 의 facts
   출력과 키 단위로 견준다.
