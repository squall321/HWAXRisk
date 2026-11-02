<!-- F2 risk_locate_for_section 설계 — 리스크 항목 · refdes · 넷 · ECAD 좌표를 MCAD 좌표와 단면 두 장(F1 section_pair_view 입력)으로 바꾸고, 보드 ↔ CAD 변환 등록부와 그 검증을 정한다 -->
# F2 — 단면 자리 찾기(`risk_locate_for_section`)

긴급 'CAD 그림을 보고서로'(11-02)의 F2 다. 현장 심사자는 접이식 폰의 두 CAD 판(StepForge MCAD · ODB 허브 보드)을 견주며 안건마다 같은
자리의 단면 한 쌍이 필요하다. 지금은 ECAD → MCAD 변환을 손으로 셈한다 — 한 메인 보드는 `x_CAD = 82.13 − x_ODB`, `y_CAD = y_ODB + 2.82`,
ODB top 면 = CAD 보드 몸체의 아래 면이었다. F2 는 그 셈과 단면 고르기를 대신해 StepForge 세션의 F1 `section_pair_view` 에 넘길 자리를 낸다.

## 1. 입력 · 출력

**입력**(넷 가운데 하나 — 둘 이상이거나 없으면 422)

| 입력 | 뜻 |
|---|---|
| 항목 | 리스크 항목 — finding(`finding_id`) 또는 등록부 묶음(`target_key` + `cluster_key`). 과제의 대상이어야 한다 |
| `refdes` | 보드의 부품 |
| `net` | 넷 이름 |
| `x` · `y` (+ `side`) | 보드 좌표(ODB, mm). side 는 top · bottom(선택) |

함께 `project_id`(필수), `odb_job_id` · `stepforge_project_id`(선택 — 비우면 과제의 원천 카드 ecad · mcad 에서). 항목은 그 항목의 스냅샷 원천이
먼저다.

**출력** — 늘 `status` 가 있다.

- `located` — `mcad`{x, y, z, unit: "mm"} · `body`(그 자리의 CAD 몸체 경로, 확신할 때만 — 아니면 null 과 `body_note` · 후보) ·
  `planes`[긴 축, 짧은 축] 각 {axis, offset, unit: "mm"} · `window_mm` · `stepforge_project_id`(등록부가 가리키는 CAD 과제) ·
  `f1`{stepforge_project_id, point, part, planes, window_mm} — F1 입력은 `part` · `point` · `axis`+`offset` 가운데 하나와 `window_mm` 이라
  그대로 넘길 꼴이다. 변환을 탔으면 `transform`{formula, mirror_x, mirror_y, offset_x, offset_y, top_face, status, error_mm,
  verification 요지, verified_at}, ECAD 원점은 `ecad`{x, y, side, unit, center_basis}.
- `unknown` — `reason`{code, message, fix?}. 자리를 정하지 못한 것은 오류가 아니라 이 답이다(아래 4절). 신원 · 권한 · 인자 · 자격(PAT)
  문제는 오류다(401 · 403 · 404 · 409 · 422).

**단면 고르기.** 평면은 F1(StepForge `section_view`)과 같은 뜻이다 — `axis` 는 평면의 법선 축, `offset` 은 그 축의 자리(mm). 두 평면은 늘
두께 축(보드 법선 z)을 품는 세로 단면이고 자리를 지난다. 긴 축 평면은 그 대상의 긴 변을 품고(법선 = 짧은 변 축), 짧은 축 평면은 긴 변에
수직이다. 긴 변은 대상의 크기로 정한다 — refdes 는 핀들의 bbox(없거나 잘렸으면 보드의 긴 변), MCAD 몸체는 그 bbox 의 면내 두 변, 넷은 핀들의
bbox, 좌표는 보드의 긴 변. 어느 것을 썼는지 `plane_basis` 에 적는다.

## 2. 변환 등록부(`rr_board_transforms`, 스키마 v7)

과제마다 (ODB 보드 `odb_job_id`, StepForge 과제 `stepforge_project_id`) 한 행.

- 값 — `mirror_x` · `mirror_y`(뒤집기) · `offset_x` · `offset_y`(mm) · `top_face`(ODB top 면이 닿는 CAD 보드 몸체 면 — `zmax` 위 면 ·
  `zmin` 아래 면) · `board_body_path`(CAD 보드 몸체 경로) · `board_z_min` · `board_z_max`(등록 때 읽은 몸체 z 범위).
- 식 — `x_CAD = s_x · x_ODB + offset_x`, `y_CAD = s_y · y_ODB + offset_y`(s = 뒤집으면 −1). 부품의 z 는 그 부품 면이 닿는 CAD 면의 z 다 —
  top 면 부품은 `top_face`, bottom 면 부품은 그 반대 면.
- 누가 — 과제 주인 · 편집자(관리자는 편집자). 사람이 적거나(`source: manual`) 제안(`GET …/board-transforms/proposal`)에서 골라
  적는다(`source: proposed`). 적기는 늘 이 박스에서 다시 검증한다. 바뀌면 감사 `project.board_transform` 한 줄.
- 읽기 — 과제 구성원(보기 이상 · 관리자 열람 줄). MCP 는 그 사람이 보는 과제(소유 · 구성원 · 조직 공개).

**왜 회전이 없나.** 등록부는 계약대로 원점 · 뒤집기 · 면만 둔다. 90° 돌아간 보드는 이 꼴로 못 적는다 — 외곽 크기 검사가 가로 · 세로가 바뀐
것으로 거절한다(정사각에 가까운 보드는 구멍이 가른다). 보드 법선이 CAD z 가 아니면(몸체 bbox 의 가장 얇은 변이 z 가 아니면) 거절한다.

## 3. 검증 — 등록 때 이 박스에서

ODB 허브와 StepForge 를 **그 사람의 포털 PAT** 로 부른다(ECAD 보드 붙이기 · SP 과제 풀이와 같은 자격 — 박스 읽기 PAT 로 내려가지 않는다,
없으면 409 `locate_pat_absent`). 게이트웨이 호출 전용 별칭(`<백엔드 키 하이픈 뺌>_<도구>`)으로 부르고 도구 지도는 받지 않는다.

| 원천 | 도구 | 쓰는 칸 |
|---|---|---|
| ODB | `odbhub_get_volume_result(job_id)` | `board.x_mm` · `y_mm`(외곽 크기) · `thickness_mm`, 있으면 `board.outline_bbox` [x_min, y_min, x_max, y_max](OH-04) |
| ODB | `odbhub_get_mounting_holes(job_id, page, page_size)` | `holes[]`{x, y, diameter_mm} — `has_more` 면 쪽을 넘긴다 |
| CAD | `heaxstep_forge_part_info(project_id, part, full)` | `world_bbox`(보드 몸체) |
| CAD | `heaxstep_forge_corner_proximity(project_id, part, limit, full)` | `parts[0].hole_list[]`{center, axis, radius_mm} · 단위 칸(`declared_units` · `unit_note`) |

검사(오차 상한 `MAX_ERROR_MM` 0.5 mm — 코드 상수):

1. **손대칭(parity)** — ODB 의 (x, y, top 법선)은 오른손 좌표계이고 강체 보드는 거울상이 될 수 없으니 top 법선은 `s_x · s_y · ẑ` 로 간다.
   `top_face` 는 `s_x · s_y = +1` 이면 `zmax`, `−1` 이면 `zmin` 이어야 한다. 예 — x 만 뒤집은 손 셈은 `zmin`(ODB top = CAD 아래 면)과 맞는다.
2. **평면** — CAD 보드 몸체 bbox 의 가장 얇은 변이 z 다.
3. **외곽 크기** — ODB `x_mm` · `y_mm` 와 CAD 몸체 x · y 변. 단위(인치 머리 · 25.4배) · 엉뚱한 몸체 · 90° 회전을 잡는다.
4. **외곽 자리**(OH-04 뒤) — ODB 외곽 bbox 네 변을 변환해 CAD 몸체 bbox 와 견준다.
5. **구멍** — ODB 고정홀을 변환해 CAD 몸체의 z 축 원형 구멍과 지름(차 ≤ 0.3 mm)이 맞는 가장 가까운 것끼리(2 mm 안, 짧은 짝부터) 짝짓는다.
6. **뒤집기 모호함** — 다른 뒤집기 셋마다 가장 잘 맞는 원점을 찾아, 근거(외곽 · 구멍)를 같은 수 이상 같은 오차 안에서 설명하면 모호하다.
   외곽 bbox 는 늘 점대칭이라 외곽만으로는 뒤집기를 가르지 못한다 — 대칭이 아닌 구멍 둘 이상이 가른다.

거절(422 `transform_unverified`, detail 에 검증 전부) — 손대칭 어긋남 · 평면 아님 · 크기를 못 읽음 · 크기 오차 넘음 · 자리 근거 없음(외곽 자리를
모르고 맞은 구멍이 둘 미만) · 자리 오차 넘음 · 모호함 · CAD 단위 의심 · ODB 구멍 대부분이 짝 없음. `force: true` 와 사유(`reason`)로 넘길 수
있다(`status: forced`, 감사 행에 사유). CAD 보드 몸체를 못 읽으면(z 면을 모른다) 강제로도 적지 않는다.

**제안**(`GET …/board-transforms/proposal`) — 몸체 경로가 없으면 최근 스냅샷에서 ODB 외곽 크기 · 두께에 맞는 몸체 후보를 준다. 있으면 뒤집기
넷마다 원점 후보(외곽 bbox 가운데 맞춤 · 지름이 맞는 구멍 짝마다)에서 짝 수가 가장 많고 오차가 가장 작은 것을 고르고 짝 평균으로 다듬어,
같은 검증을 붙여 차례로 준다. 쓰지 않는다.

**들여오기.** 검증은 이 박스의 일이다 — 반출은 `status` · `error_mm` · `verify_json` · `reason` 을 싣지 않고 들여오기는 받지 않는다. 들여온 행은
`status` 가 없고 위치 찾기는 `transform_unverified` 로 답한다(다시 적어 이 박스에서 검증한다).

## 4. 위치 찾기와 실패

| 입력 | 길 | unknown 의 까닭 |
|---|---|---|
| 항목 위치 | 항목의 `location`(아래)이 있으면 그것 — 점이면 바로 평면, 몸체 경로뿐이면 그 스냅샷 몸체 bbox 가운데 | `item_part_absent`(스냅샷에 그 몸체가 없다) |
| 항목 주제 | 주제 ckey 의 노드(대상 스냅샷 먼저, 비교면 앞 판) — MCAD 부품은 bbox 가운데 · 몸체, 계면(ckey 둘)은 두 bbox 겹침(없으면 가운데 사이), ECAD 부품은 refdes 길 | `subject_not_placeable`(asm: · dim: · 빈 주제) · `subject_nodes_absent` · `bbox_world_absent` |
| `refdes` | `odbhub_get_part_detail` — 핀 bbox 가운데(핀이 없거나 잘렸으면 배치점) · side · 변환 · 부품 면 z | `board_missing` · `cad_project_missing` · `transform_missing` · `transform_unverified` · `refdes_not_found` · `side_unknown` · `odb_call_failed` |
| `net` | `odbhub_get_net` 의 `pins[]`{x, y} bbox | `net_not_found` · `net_pins_absent`(핀 좌표가 없다 — ODB 허브 몫) |
| `x` · `y` | 그대로 변환 — side 가 없으면 z 는 보드 두께 가운데 | 변환 쪽 까닭 |

몸체는 그 CAD 과제의 최근 스냅샷(같은 StepForge 과제를 읽은 것)에서 찾는다. 스냅샷의 보드 몸체 bbox 가 등록 때 읽은 것과 오차 상한 넘게
다르면 찾지 않는다(`snapshot_board_moved`). 부품 면 바로 바깥(0.05 mm)을 품는 몸체 가운데 가장 작은 것이 그 부품 크기에 맞고 자리가 그 몸체의
가운데 반 안일 때만 `body` 다 — 아니면 null 과 후보(bbox 가 품을 뿐이다). MCAD 항목은 그 몸체가 곧 `body` 다.

**항목 위치**(`rr_findings.location_json` · `rr_registry.location_json`, v7) — `{part, point{x, y, z, unit: "mm"}, set_by, set_at}`. 쓰기는
`PUT /api/projects/{id}/item-location`(편집자 이상, 감사 `finding.location` · `registry.location`) · MCP `risk_set_item_location`. 패널을 다시
저장하면 그 패널의 finding 행은 새로 서므로 위치도 사라진다(다른 주장에 붙지 않는다). 좌석 길(브리프 · 패널 질문)은 이 칸을 읽지 않는다.

## 5. 길 · 이름

- REST — `GET /api/projects/{id}/locate` · `GET /api/projects/{id}/board-transforms` · `GET …/board-transforms/proposal` ·
  `PUT /api/projects/{id}/board-transforms` · `DELETE /api/projects/{id}/board-transforms` · `PUT /api/projects/{id}/item-location`.
- MCP — `risk_locate_for_section`(읽기) · `risk_propose_board_transform`(읽기) · `risk_set_board_transform`(쓰기 — null 이면 뗀다) ·
  `risk_set_item_location`(쓰기). 넷 다 그 사람의 PAT 로 부르거나 그 사람의 이름으로 쓰므로 게이트웨이 위임으로 확인된 신원만 받는다
  (`delegation_required`). 이름이 `risk_` 로 시작해 엔진의 D-18 문(`_risk_designated_refusal` 갈래 app)이 리스크 심사 좌석에 닫는다.

## 6. 어디서 확인했나 · cae00 에서 볼 것

- dev — 계산(변환 · 손대칭 · 검사 · 모호함 · 제안 · 평면)과 저장 · 권한 · 감사 · MCP 문은 시험으로 본다. 손 셈 예(x 뒤집기 · y 원점 · 아래 면)를
  그대로 되짚는다. 가짜 응답은 ODB 허브 레퍼런스(포털 `docs/procedures/fixtures/odb-hub/reference.md` §4.6 · §4.10 · §4.11)와 StepForge 원문
  (`part_info` · `corner_proximity`)의 꼴이다.
- dev 에 없는 것 — ODB 허브는 cae00 에서만 닿는다. 그래서 아래는 cae00 에서 처음 확인한다.
  - `get_part_detail` 에 `side` 칸이 있는지(없으면 그 보드의 스냅샷 부품 노드 side 를 쓴다 — 없으면 `side_unknown`) · 핀 좌표가 보드 좌표인지.
  - `get_net` 의 인자 이름(`net` 으로 부른다)과 핀 좌표(`pins[].x · y`)가 있는지 — 없으면 넷은 늘 `net_pins_absent` 다.
  - `get_mounting_holes` 의 쪽 넘김 칸(`has_more`)과 `diameter_mm` 가 CAD 구멍 지름과 같은 기준(마감 · 드릴)인지.
  - OH-04 외곽 bbox 의 자리와 꼴(`get_volume_result.board.outline_bbox` = [x_min, y_min, x_max, y_max])은 ODB 허브가 정해야 한다 — 그 전에는
    외곽 자리 검사가 없고 구멍이 유일한 자리 근거다.
  - 실제 메인 보드 하나로 손 셈(82.13 · 2.82 · 아래 면)을 제안이 되찾는지.
- ODB 허브에 바라는 것 — OH-04(외곽 bbox, 부품과 같은 기준), `get_net` 핀 좌표, `get_part_detail.side`.
