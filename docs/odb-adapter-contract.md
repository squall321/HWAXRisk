<!-- ODB 허브(ECAD) 어댑터 계약 — hwax_risk 가 ecad 소스를 읽는 지금 도구 · 발견 · 보드 고르기 · 두 단계 · rr_ir 사상 · 표지(정본 plan §2.5.3·§2.13.5, 개정 요청 포털 docs/design-risk-review/ecad-1031) -->
# ODB 어댑터 계약(ecad, ir_version '1.1')

정본은 `HWAXPortal/docs/design-risk-review/plan.md` §2.5.3(사상) · §2.13.5(어댑터)이고 이 문서는 그 계약을 앱 리포에 옮긴 것이다.
2026-10-31 개정 — 계약 4도구(`odb_get_board` · `odb_list_components` · `odb_list_nets` · `odb_get_stackup`)는 어디에도 없어 기다리지 않고
ODB 허브의 **지금 도구**로 읽는다. 근거와 실측(cae00 10-31, 표본 보드 둘)은 포털 `docs/design-risk-review/ecad-1031/request.md` 이고, 사용자
결정 D-1 = (가)에 따라 2단계(좌표 · 넷)는 허브가 지금 도구에 묶음 읽기(OH-01 ~ OH-04)를 더한 뒤에 한다.

## 지금 상태

- ODB 허브는 게이트웨이 백엔드 `odb-hub` 로 도구 39개를 낸다(2026-10-31 `/tools-map`). 다른 앱과 이름이 겹친 둘만 접두가 붙는다 —
  `odbhub_list_jobs` · `odbhub_list_parts`. 나머지(`find_job` · `get_board_layers` · `check_job_stackup` · `get_volume_result` ·
  `get_odb_download` · `get_part_detail` · `find_nets` · `get_net` 등)는 이름 그대로다. 심의 좌석도 같은 도구를 이름으로 부른다.
- 어댑터는 `backend/app/adapters/ecad.py`(1단계)다. 스텁 `ecad_stub.py` 는 지웠다 — 보드를 붙이지 않은 과제의 ecad 결측 행은 스텁
  시절과 같은 봉투다(`adapter_version` `0.0-stub`, `degraded: ['ecad_absent']`). 세대를 그대로 두는 까닭은 아래 '1단계 뒤 주의' 에 있다.
- 단위는 허브가 mm 로 맞춰 준다(인치 ODB 도 mm 로 바꾼다). 층 두께만 µm(`thickness_um`)로 와서 어댑터가 mm 로 옮긴다 — rr_ir 의 길이
  단위는 mm 다. 그래서 `unit_converted_mil` 은 나오지 않는다.

## 발견(ER-02)

- 이름 집합이 아니라 **백엔드 키와 원래 이름**으로 찾는다. 게이트웨이 `/tools-map` 의 `map`(실이름 → 백엔드)에서 백엔드 `odb-hub` 의 것만
  보고, 실이름은 원래 이름이거나 `odbhub_` + 원래 이름이다(게이트웨이 접두 규칙 `backend.replace('-','') + '_'`). 다른 백엔드의 같은 이름
  (StepForge 의 `heaxstep_forge_list_parts`)은 보지 않는다 — `adapters/base.backend_tool_name`.
- 1단계 도구 여섯 — `find_job` · `get_board_layers` · `check_job_stackup` · `get_volume_result` · `get_odb_download` · `list_parts`.
  `GET /api/meta/adapters` 의 ecad 는 여섯이 다 보이면 `ready`, 하나라도 없으면 `unavailable`(빠진 원래 이름이 `tools_missing`), 게이트웨이를
  못 읽었으면 `planned` 다. `contract_only` 는 더 나오지 않는다.
- 캡처의 모든 MCP 호출은 같은 지도로 그 소스 카드의 백엔드 이름을 먼저 고른다(`CallRecorder` — 지도가 없거나 그 백엔드에 없으면 종전의
  suffix 해석). 응답 계약(§2.13.1)은 어댑터마다 제 표로 잰다 — ODB 허브 `list_parts` 의 `rows` 를 StepForge 의 `/parts` 계약으로 재지 않는다.

## 보드 고르기(ER-01)

과제의 ECAD 보드는 소스 카드(kind `ecad`) 한 장이고 ref 는 `{odb_job_id}` 다. `job_id` 는 허브가 발급한 16자리 16진(원본 sha256 앞
16자리)이다. 같은 모델의 다른 판이 함께 나올 수 있어 **고르는 것은 사람이다** — 모델 이름만으로 정하지 않는다.

| 할 일 | REST | MCP(게이트웨이 위임 신원만) |
|---|---|---|
| 찾기 | `GET /api/ecad/boards?q=<과제 · 모델 · 파일 이름 또는 job_id>` | `risk_find_ecad_boards(query)` |
| 붙이기 · 바꾸기 | `PUT /api/projects/{id}/ecad-board {odb_job_id}` | `risk_set_ecad_board(project_id, odb_job_id)` |
| 떼기 | `DELETE /api/projects/{id}/ecad-board` | `risk_set_ecad_board(project_id, null)` |

- 찾기는 `find_job` 한 번의 후보 `{job_id, project, model, board_type, revision, original_filename, uploaded_at, name}` 를 최대 10개와
  `truncated` 로 준다. 허브의 봉투형 오류(찾는 것이 없다)는 빈 후보와 `hub_message` 다. 자격 없음 · 도구 없음 · 호출 실패는 409
  (`ecad_credential_absent` · `ecad_unavailable` · `ecad_unreachable`)다.
- 붙이기는 그 job_id 가 `find_job` 후보에 실제로 있을 때만 적는다(없으면 422 `ecad_board_not_found`, 꼴이 16자리 16진이 아니면 422 `E100`).
  카드는 과제마다 한 장이라 다른 보드를 주면 같은 카드를 바꾸고, 바뀌면 감사 `project.ecad_board` 한 줄이 남는다. 같은 보드를 다시 주면
  `changed:false` 다. 카드의 `probe.board` 에 찾은 보드 정보가 남는다.
- 떼기는 카드를 지울 뿐이다. 이미 동결된 스냅샷은 그대로이고 다음 캡처의 ecad 는 결측이다.
- 일반 소스 연결(`POST /api/projects/{id}/sources` · `risk_add_source`)은 kind `ecad` 를 422 `ecad_board_route` 로 거절한다 — 확인 없이
  붙거나 카드가 둘이 되면 어느 보드를 읽을지 uuid 순서가 정한다.
- 자격은 캡처와 같다 — 그 사람의 등록된 포털 PAT, 없거나 곧 끝나면 박스의 읽기 PAT(`HWAXRISK_PORTAL_PAT`). 그래서 찾아진 보드는 캡처도 읽는다.
  odb-hub 는 사람별 격리가 없고 게이트웨이의 `plat:odbhub` 로만 막힌다 — 박스 PAT 로 내려가면 그 문을 서비스 계정으로 지난다. 그 사람의 PAT 만
  쓸지(없으면 `ecad_pat_absent`) 박스 PAT 로 내려가되 답 · 스냅샷에 자격을 적을지는 **사용자 결정**으로 남겼다(context-notes EC-15).
- 게이트웨이 도구 지도(`/tools-map`)를 못 읽었으면 찾기는 409 `ecad_gateway_unreadable` 이다 — '그 백엔드에 find_job 이 없다'(`ecad_unavailable`)와
  고칠 곳이 다르다. 못 읽은 지도는 캐시하지 않는다(읽은 지도만 60 s 캐시).

## 두 단계

| 단계 | 누가 | 무엇이 실리나 | 보드 1장 호출 수 |
|---|---|---|---|
| 1단계(지금) | 리스크 앱(ER-01 ~ ER-05) | board(소스 1건 + board 노드 1건) · layer(5종으로 거른 행) · component(분류된 부품, 좌표 · 넷 없이). `ecad_absent` 가 사라지고 빠진 칸은 표지로 남는다 | `find_job` 1 · `get_board_layers` 1 · `check_job_stackup` 1 · `get_volume_result` 1 · `get_odb_download` 1 · `list_parts` 100행씩(보드 1 은 8쪽, 모두 13) |
| 2단계 | ODB 허브 OH-01 · OH-02(가능하면 OH-03 · OH-04) 다음 리스크 앱 ER-06 | component 좌표 · 넷, net 노드, component→net 엣지, 분류 안 된 부품 | 묶음 읽기 몇 번 |

2단계 전에 꼭 필요하면 핀 수 상위 부품만 `get_part_detail` 로 읽고(호출 상한을 둔다) `component_xy_partial` 을 남긴다(ER-06 — 지금은 하지 않는다).

## 1단계 사상(요청서 부록 A)

캡처는 소스 카드의 `odb_job_id` 로 `find_job(query=<job_id>)` 을 불러 그 job_id 와 같은 행을 찾는다(필수 호출). 다음 넷은 한 번씩이고
`list_parts` 는 `{job_id, category:'', side:'', sort:'', page, page_size:100}` 로 끝까지 쪽을 넘긴다 — 허브는 page_size 를 100 으로 줄이고,
빠진 선택 인자를 거부한 적이 있어 기본값이라도 다 싣는다.

| rr_ir | 원천 | 변환 · 주의 |
|---|---|---|
| kind `board` 노드 1건 | `find_job` 행과 아래 `stats` 의 보드 칸 | canon_key `ecad:board` · label `board`(판이 바뀌어도 같은 값 — 쌍 비교가 두 판의 보드를 이름으로 맞춘다) · local_key = job_id. attrs `{board_id, name, revision, units, outline_bbox(null), outline{x_mm, y_mm, area_mm2}, thickness, stackup_verdict, stackup_id, ecad_stackup_total, layer_count, n_components, n_components_placed, n_nets(null), odb_version(null), source_hash}` — 두께 · 적층 합은 mm. 노드라 ir_hash 에 든다 — ir_hash 는 노드 · 엣지만 보므로 보드가 소스에만 있으면 배치 · 배선만 바꾼 판(1단계 칸이 같다)으로 바꿔 붙였을 때 앞 판의 스냅샷이 옛 보드 이름 · 해시로 재사용됐다. |
| `sources[ecad].ref.board_id` | `find_job` 행의 `job_id` | 그대로. |
| `sources[ecad].ref.name` | `find_job` 행의 project · model · board_type · revision | `' / '` 로 엮는다. `job_name` · `step_name` 은 쓰지 않는다(최근 100건 가운데 37건 · 58건이 같은 기본값). 넷 다 비면 null. |
| `sources[ecad].source_hash` | `get_odb_download.sha256`(+ `size_bytes` → `stats.source_size_bytes`) | 64자리 16진이 아니면 쓰지 않는다. job_id 가 sha256 앞 16자리가 아니면 INFO 경고 `source_hash_job_mismatch`. |
| `stats.units` | — | 늘 `mm`. |
| `stats.thickness_mm` · `stats.stackup_verdict` · `stats.stackup_id` | `get_board_layers.total_thickness_mm` · `check_job_stackup.verdict`(없으면 `get_board_layers.stackup_verdict`) · `check_job_stackup.chosen_id` | ODB 두께가 자주 틀려 판정을 함께 싣는다. |
| `stats.stackup_total_mm` | 5종 층 두께 합(실크 제외, 하나라도 null 이면 null) | 계약의 `ecad_stackup_total`. 보드 두께와 0.001 mm 넘게 다르면 경고 `stackup_total_mismatch`. |
| `stats.layer_count` | `get_board_layers.signal_layer_count`(없으면 `check_job_stackup.layer_count`) | `get_board_layers.layer_count` 는 부품 · 실크 · 페이스트 · 드릴 · 문서 층까지 세어 쓰지 않는다(보드 1 은 35, 동박층은 10). |
| `stats.outline` · `stats.outline_bbox` | `get_volume_result.board.{x_mm, y_mm, outline_area_mm2}` | 폭 · 높이 · 면적뿐이다 — 원점이 없어 `outline_bbox` 는 null(OH-04). |
| `stats.n_components` · `n_components_basis` · `n_components_placed` | `list_parts.total` · `'classified'` · `get_volume_result` 의 top + bottom `count`(없으면 `counted` — 요청서 OH-02 의 이름, cae00 에서 칸 이름을 확인한다) | `n_components` 는 분류된 부품 수 = component 노드의 원천이다. 배치 수(분류 안 된 부품 포함, 약 30% 많다)는 따로 싣는다. 배치 수가 분류된 부품 수보다 작으면 그 칸이 배치 수가 아니다 — 경고 `placed_below_classified` 이고 `components_unclassified_omitted` 는 그대로 선다. |
| `stats.n_nets` · `stats.odb_version` | — | null(OH-01 · OH-05). |
| kind `layer` 노드 | `get_board_layers.layers[]` | 5종(SIGNAL→signal · POWER_GROUND→plane · DIELECTRIC→dielectric · SOLDER_MASK→soldermask · SILK_SCREEN→silkscreen)으로 거르고 위에서 아래 물리 순서로 idx 를 1부터 매긴다(보드 1 은 23행, 보드 2 는 19행). canon_key `ecad:layer:<idx>` · label · local_key = 층 이름. |
| `attrs.thickness` | `layers[].thickness_um` ÷ 1000 | mm. 실크 층은 null. |
| `attrs.material` | `check_job_stackup.layers[].material` | 판정이 `standard` 이고 표준 적층의 층 구분(SolderResist · Signal · Dielectric)이 보드 층(실크 제외)과 수 · 차례가 하나하나 맞을 때만이다 — 값은 보드 ODB 가 아니라 맞춘 표준 적층에서 온다. 아니면 null. |
| `attrs.copper_weight` | — | null — 무게 칸은 없고 바깥층 두께는 도금을 포함한다. |
| kind `component` 노드 | `list_parts.rows[]` | canon_key `ecad:<refdes>` · label · local_key = refdes · group = side. refdes 가 겹치면 앞의 것만(경고 `duplicate_refdes`), 빈 refdes 는 싣지 않는다(`refdes_missing`). refdes 가 `board` · `layer:…` · `net:…` 꼴이면 보드 · 층 · 넷 노드의 열쇠와 겹쳐 싣지 않는다(`refdes_reserved`). |
| `attrs.{refdes, part_number, footprint, side, pin_count}` | `rows[].{refdes, part_name, pkg_name, side, pin_count}` | 그대로(`part_name` 은 자재 코드이거나 라이브러리 이름). side 가 top · bottom 이 아니면 그 칸을 빼고 `type_unexpected` 경고. |
| `attrs.{x, y, rot, nets}` | — | null(2단계 — `get_part_detail` 을 부품마다 불러야 한다). rot 의 [0,360) 정규화도 2단계다. |
| `attrs.height` | `get_volume_result.{top,bottom}.largest_items[].height_mean_mm` | 면마다 큰 부품 10개만 있다. |
| `attrs.value` | — | null(어느 도구에도 없다). |
| kind `net` 노드 · `net` 엣지 | — | 없다(2단계). |

컴포넌트 총 상한은 2000 이다(넘으면 앞의 것만 싣고 `components_truncated`). 다 받았는지는 **서로 다른** 행 수(겹친 refdes 는 한 번, 빈 refdes
는 행마다)로 total 과 견준다 — 쪽 순서가 쪽마다 흔들리는 허브(sort 기본값의 쪽 넘김)는 어떤 행을 두 번 주고 어떤 행은 주지 않아, 받은 행 수로
세면 빠진 부품이 보이지 않는다(모자라면 `capture_partial` + 경고 `components_incomplete`). 쪽 수는 ceil(min(total, 2000) / 100) + 1 을 넘기지
않는다(넘으면 `capture_partial` + `odb_paging_capped` — 쪽마다 새 행 하나만 주는 허브가 캡처 예산을 넘겨 수천 번 불리지 않게).
응답 계약 — `get_board_layers` `/layers` · `check_job_stackup`
`/verdict` · `get_volume_result` `/board` · `get_odb_download` `/sha256` · `list_parts` `/rows` `/total`. 위반은 `schema_drift` 와
경고 `source_schema_drift` 다. `find_job` 은 봉투 열쇠가 부록 A 에 없어 알려진 꼴(`jobs` · `matches` · `results` · `items` · 맨 목록 · 잡 하나)을
읽고, 못 읽으면 드리프트로 캡처를 닫는다.

## 표지(ER-04)

지어내지 않고 남긴다. 아래 열두 개는 rr_ir 스키마의 `degraded_code` 어휘다.

| 표지 | 언제 | 뜻 |
|---|---|---|
| `ecad_nets_deferred` | 1단계 캡처마다 | 넷 · component→net 엣지가 없다(2단계). `sig:counts.ecad.nets` 는 0 이 아니라 미측정이다. |
| `component_xy_deferred` | 부품이 실리면 | 좌표 · 회전이 없다(2단계). |
| `components_unclassified_omitted` | 부품을 읽었고 배치 수가 list_parts total 과 같다고 확인되지 않을 때(크거나 · 작거나 · 모르거나) | 분류 안 된 부품(저항 · 테스트 포인트 등, category Unknown)이 빠졌다(OH-02). |
| `outline_origin_unknown` | 1단계 캡처마다 | 외곽은 폭 · 높이 · 면적뿐이고 부품 좌표와 같은 기준의 원점이 없다(OH-04). |
| `stackup_material_unmatched` | 층이 있고 재료를 표준 적층과 맞추지 못했을 때 | 비표준 · 판정 없음 · 구분 불일치 — 재료가 null 이다. |
| `copper_weight_absent` | 동박층이 있으면 | 원판 동박 무게가 없다(두께만). |
| `plane_type_unknown` | 동박층이 다 SIGNAL 일 때 | 허브가 plane 을 가르지 않는다 — plane 이 없다는 뜻이 아니다. |
| `odb_version_absent` | 1단계 캡처마다 | ODB++ 형식 판이 없다(revision 은 설계 판이다). |
| `component_value_absent` | 부품이 실리면 | 값(용량 · 저항)이 없다. |
| `component_height_partial` | 높이가 빈 부품이 있으면 | 높이는 면마다 큰 부품 10개뿐이다. |
| `components_unavailable` | 부품 목록 첫 쪽을 못 읽었을 때(호출 실패 · 봉투형 오류 · 드리프트) | component 노드 가족이 통째로 없다 — '보드에 부품이 없다' 가 아니다. `stats.n_components` 는 null(미측정)이다. |
| `layers_unavailable` | 층 목록을 못 읽었거나 5종 행이 없을 때 | layer 노드 가족이 통째로 없다. `stats.layer_rows` · `layer_rows_all` 은 못 읽었으면 null 이다. |

그 밖 — `capture_partial`(선택 호출 실패 · 쪽 넘김이 멈춤 · 쪽 상한에 닿음 · 서로 다른 행이 total 보다 적음), `components_truncated`(2000 초과),
`schema_drift`.

## 못 읽었을 때

| 경우 | 봉투 |
|---|---|
| 보드를 붙이지 않았다 | `ecad_absent`(INFO) — 스텁 시절과 같다 |
| 캡처 요청 kinds 에 ecad 가 없다 | 결측 행만 남기고 보드를 읽지 않는다 — ECAD 없는 앞 스냅샷과 견줄 캡처를 사람이 고를 수 있다 |
| 보드는 붙었는데 호출 없이 끝났다 — MCP 자격이 없다 · 게이트웨이 도구 지도를 못 읽었다 · 그 백엔드에 1단계 도구가 다 없다 | `missing.ecad_absent` + 경고(WARNING) `ecad_pat_absent` · `ecad_gateway_unreadable` · `ecad_tools_missing` — dyna 의 자격 없음(`dyna_pat_absent`)과 같은 결측 + 경고이고 `ecad_capture_failed` 가 아니다 |
| 보드는 붙었는데 `find_job` 이 실패했다 · 그 job_id 가 없다 · 응답을 못 읽었다 | `missing.ecad_absent` + `missing.ecad_capture_failed`, 경고(WARNING) `capture_call_failed` · `ecad_board_not_found` · `source_schema_drift` — 붙은 보드를 못 읽은 것은 '회로가 없다' 가 아니다(§2.11.3 필수 호출 실패) |
| 위 두 줄인데 이번 캡처가 읽은 카드가 ECAD 하나뿐이다 | 스냅샷을 만들지 않는다 — 409 `source_unreachable`(detail `{kind:'ecad', reason:<경고 code>}`), 잡 `failed`, 호출 원문은 스냅샷 없이 남는다(§2.11.3 '남은 kind 없음') |
| 선택 호출(`get_board_layers` · `check_job_stackup` · `get_volume_result` · `get_odb_download` · `list_parts` 쪽)이 실패했다 | 그 칸만 비고 `capture_partial` + 경고 `capture_call_failed`, 잡은 partial |
| 허브가 200 + `{error, hint}`(봉투형 오류 — 분석을 돌리지 않은 보드)로 답했다 | 그 칸만 비고 경고 `odb_error_body` — 허브에 그 값이 없다는 뜻이라 부분 캡처가 아니다. 부품 목록 · 층이 그러면 노드 가족이 통째로 빠지므로 `components_unavailable` · `layers_unavailable` 를 세운다 |

ECAD 카드(소스 카드 probe)는 호출의 전송이 아니라 어댑터 결과로 잰다 — 보드를 실었으면 `linked` · `capture_ok calls=N`(부분이면 — 선택 호출
실패 · 쪽 넘김 — `capture_partial calls=N` 과 실패한 호출) · `capture_mode: mcp`, 못 읽었으면 `unreachable` · `capture_failed <경고 code> — <글>` 이다. kinds 에 ecad 가 없어 읽지
않은 캡처는 카드를 건드리지 않는다. 붙은 보드만 있는데 kinds 가 ecad 를 뺐으면 409 의 글이 '연결하라' 가 아니라 kinds 를 고치라고 말한다
(detail `{kinds, attached}`).

## ECAD 의존 도메인 6(ER-05)

`pcb · pwr · rf · soc · passive · mem`(`HWAXRISK_ECAD_DOMAINS`)은 편성 규칙(`planner`)이 `routes._ecad_absent_for_target` 하나로 가른다.

- **스냅샷 대상** — 그 스냅샷의 `missing.ecad_absent` 다. 1단계 캡처는 ECAD 를 실으므로(`ecad_absent=false`) **여섯 다 deferred 에서 풀린다** —
  대표 1석만이 아니라 전원이 편성되고, 카드 대조의 입력 결손(`input_gaps: ['ecad_absent']`)도 사라진다. 빠진 칸은 표지로 E0 · 단위 근거 줄에
  실려 좌석이 '없다' 가 아니라 '안 실렸다' 로 읽는다.
- **diff 대상** — 1단계 동안 늘 ECAD 부재로 본다(여섯 다 rank 1 외 deferred · 입력 결손). 1단계 쌍 비교는 ECAD 노드를 refdes · 층 이름으로 맞춰
  추가 · 삭제만 보고 칸 변화(층 두께 · 재료 · 품번 · 패키지 · 핀 수 · 높이)를 싣지 않는다 — 그 비교를 받은 ECAD 좌석이 '회로 변경 없음' 으로
  읽지 않게 한다. 두 리비전 모두 보드가 실렸으면 대상의 결측 블록 첫 줄(kind `ecad`)이 그 까닭을 말하고 입력 결손 전문가에게는 그 영역의
  실마리가 붙는다(`units._target_missing` · `gap_missing`). 비교가 ECAD 칸을 보게 되면(§3.3 의 `ecad.*` 예약 이벤트) 이 분기를 걷는다.

| 도메인 | 1단계로 보는 것 | 아직 못 보는 것(2단계) |
|---|---|---|
| pcb | 적층 · 층별 두께 · 판정 · 동박층 수 · 외곽 폭 · 높이 · 면마다 부품 수 | 부품 좌표 · 외곽 원점 · 동박 무게 · plane 구분 |
| pwr | 전원 부품(분류된 IC · 인덕터 · 캐패시터)의 품번 · 패키지 · 핀 수 · 동박층 | 전원 · 그라운드 넷 · plane 구분 |
| rf | RF 부품의 품번 · 패키지 · 적층 | 배치 좌표 · 넷 |
| soc | AP · IC 의 품번 · 패키지 · 핀 수 | 좌표 · 넷 |
| passive | 분류된 수동 소자(캐패시터 · 인덕터)의 품번 · 패키지 | 분류 안 된 부품(저항 등) · 값 · 좌표 |
| mem | 메모리 IC 의 품번 · 패키지 | 좌표 · 넷 |

넷 · 배치가 꼭 필요한 판단(pwr · rf 의 넷 · 거리)은 2단계까지 `undetermined` 가 맞다. 넷이 없는 도메인을 deferred 로 남기는 규칙(넷 의존
도메인을 따로 두는 것)은 두지 않았다 — 두려면 편성 규칙과 설정을 함께 바꾼다.

## 1단계 뒤 주의

- **쌍 비교의 ECAD 는 kind 별로 따진다**(`diff.comparability.ecad = {base, target, excluded_reason, adapter_parity}`) — 쪽마다 `present`(보드를
  온전히 실었다) · `absent`(보드 없음 · 읽지 않음) · `failed`(못 읽었거나 `capture_partial` · `components_unavailable` · `layers_unavailable`)다.
  한쪽이라도 `failed` 면 ECAD 항목(구조층 node_changes · ECAD dn 의 파라메트릭 항목)에 `excluded_reason='capture_partial'`, 한쪽에만 실렸으면
  (첫 보드를 붙인 캡처 · kinds 에서 ecad 를 뺀 웹 기본 캡처와 MCP 캡처) `partial_scope` 다 — 항목은 남고 의미 이벤트(`part.added` ·
  `part.removed`)를 만들지 않으며 검토 단위에서는 제외 단위로 간다. 다른 kind 의 항목 · 이벤트는 그대로다 — 종전에는 ecad_capture_failed
  하나가 쌍 전체의 의미층을 지웠고, 한쪽에만 보드가 있으면 mcad 이벤트까지 parser_differs · 등급 낮춤이었다. 두 쪽 다 실렸는데 ECAD 어댑터
  세대가 다르면 ECAD 항목 · 이벤트에만 parser_differs 와 등급 한 단계 낮춤이다. 전역 `capture_parity` 는 ecad_capture_failed 를, 전역
  `adapter_parity` 는 ecad 를 세지 않는다. 2단계에서 net 엣지가 붙으면 엣지 항목도 같은 규칙에 든다.
- **결측 행의 세대** — 보드를 싣지 못한 ecad 소스(보드 없음 · 못 읽음)는 스텁 시절의 `0.0-stub` 을 그대로 쓴다. 쌍 비교의 세대 견줌은 두 쪽 다
  보드를 실었을 때만이라(위) 결측 행의 세대는 비교에 효과가 없다.
- **same-as** — ecad↔mcad/dyna 는 1차에서 원장(1단계) · 이름(5단계, refdes · part_number 토큰이 상대 이름과 겹칠 때만)뿐이다. 지문(4단계)과
  fuzzy(6단계)에는 ecad 노드가 들지 않는다 — 4단계는 ecad 노드만 빼고 mcad · dyna 끼리는 그대로 돈다(종전에는 ecad 노드가 하나라도 있으면
  단계를 통째로 꺼 쌍 비교에서 mcad 지문 대응까지 꺼졌다 — ecad 노드가 없던 동안에는 드러나지 않았다).
- **예약 치수** — `dims_named` 의 예약 이름 `ecad_stackup_total` 은 아직 자동 정의되지 않는다(예약 치수 시드는 mcad 도 없다). 값은
  `stats.stackup_total_mm` 에 있다.
- **모델 크기 상한** — `risk_max_leaf` 는 지금 mcad 리프만 센다(§2.11.3 은 ECAD 부품 수도 세라고 적었다 — 결정 필요). same-as 5단계는
  이름으로 나눠 짝을 찾는다 — 모든 쌍을 펼치던 때는 부품 2,000 개 보드 두 판의 쌍 비교가 5 초 · 330 MB 였고, 지금은 0.2 초 · 수 MB 다(dev 실측).

## 계약 조건

1. 부르는 도구는 전부 읽기다. 잡을 시작하거나 값을 바꾸는 도구(`run_*` · 업로드)는 부르지 않는다.
2. 인증은 게이트웨이 PAT 전달 규약(DynaForge 와 같음)을 따른다 — 캡처의 다른 MCP 호출과 같은 채널이다.
3. 응답은 JSON 이고 단위는 mm 다(층 두께만 µm → mm).
4. ecad↔mcad/dyna same-as 는 1차에서 `ledger · name_norm(refdes 또는 part_number 토큰)` 만 허용한다. 기하 지문(footprint bbox ↔ mcad part
   bbox)은 2단계에서 켠다(좌표가 와야 한다).
5. 계약 밖 필드(패드 · 비아 · 트레이스 폭, 부품 분류 category · 패키지 치수)는 싣지 않는다 — 실으려면 이 계약에 먼저 적는다.
