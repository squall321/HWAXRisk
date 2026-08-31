<!-- ODB hub(ECAD) 어댑터 계약 — hwax_risk 가 ecad 소스를 읽기 위해 ODB hub 가 이행할 MCP 4도구의 인자·응답·rr_ir 사상·상한(정본 plan §2.5.3·§2.13.5) -->
# ODB 어댑터 계약(ecad, ir_version '1.1')

정본은 `HWAXPortal/docs/design-risk-review/plan.md` §2.5.3(필드 표)·§2.13.5(스텁 → 실구현) 이고, 이 문서는 그 계약을 앱 리포에 옮긴 것이다.
ODB hub 가 아래 4도구를 게이트웨이 manifest `mcp:{}` 로 노출하면 `adapters/registry.py`(P1)가 도구명 집합으로 발견하고
`adapters/ecad_stub.py` 가 `adapters/ecad.py`(P7)로 교체된다. 그 전까지 스냅샷은 `missing.ecad_absent=true` 다.

## 4도구

| 도구(인자) | 응답 필드 | rr_ir 필드 | 상한·주의 |
|---|---|---|---|
| `odb_get_board(job_ref)` | `{board_id, name, units: mm\|mil, outline_bbox[4], thickness, layer_count, n_components, n_nets, odb_version, source_hash}` | `sources[ecad].ref.{board_id, name}`, `source_hash`, G6 입력(units 가 mil 이면 어댑터가 mm 로 환산하고 `degraded: unit_converted_mil`) | 보드 1장 = 소스 1건. |
| `odb_list_components(job_ref, side?, offset, limit)` | `items[{refdes, part_number, footprint, side, x, y, rot, pin_count, nets[], height, value}]`, `total`, `next_offset` | kind `component` 노드, `attrs.ecad.component`, kind `net` 엣지(component→net, pin 당 1건이 아니라 넷 당 1건) | limit ≤2000/호출, 총 상한 2000(초과 시 `degraded: components_truncated`). x·y 는 보드 원점 기준 mm. |
| `odb_list_nets(job_ref, offset, limit)` | `items[{net_name, pin_count, layers[], net_class}]`, `total`, `next_offset` | kind `net` 노드 | 총 상한 5000(`degraded: nets_truncated`). |
| `odb_get_stackup(job_ref)` | `layers[{idx, name, type, thickness, material, copper_weight}]` | kind `layer` 노드, `dims_named` 자동 후보 `ecad_stackup_total`(두께 합, §2.8 시드 예약 이름) | type 어휘는 §2.3 attrs 의 5종 `signal \| plane \| dielectric \| soldermask \| silkscreen` 으로 고정. |

## rr_ir attrs(ecad, §2.3)

```
component: {refdes, part_number|null, footprint|null, side: top|bottom, x, y, rot, pin_count, nets[], height|null, value|null}
net:       {net_name, pin_count, layers[], net_class|null}
layer:     {idx, name, type: signal|plane|dielectric|soldermask|silkscreen, thickness|null, material|null, copper_weight|null}
```

## 계약 조건

1. 4도구 전부 읽기 전용이고 `job_ref` 는 ODB hub 가 발급한 불투명 문자열이다.
2. 인증은 게이트웨이 PAT 전달 규약(DynaForge 와 같음)을 따른다.
3. 응답은 JSON 이고 좌표·두께 단위는 `odb_get_board.units` 로 선언한다.
4. ecad↔mcad/dyna same-as 는 1차에서 `ledger·title_norm/name_norm(refdes 또는 part_number 토큰)` 만 허용하고 기하 지문(footprint bbox ↔ mcad part bbox)은 계약 이행 후 P7 에서 켠다.
5. 계약 밖 필드(패드·비아·트레이스 폭)는 이 버전에서 가정하지 않는다.

## 스텁 동작(§2.13.5)

- `adapters/ecad_stub.py` 는 `discover` 만 구현한다 — 게이트웨이 `/tools-map` 에서 위 4도구 이름 집합의 존재를 검사한다.
- `capture` 는 빈 결과 + `degraded: ['ecad_absent']` 다. 스냅샷 `missing.ecad_absent=true`, warnings 에 `ecad_absent`(INFO, 어댑터 미발견).
- 계약이 이행되어 4도구가 발견되면 `adapters/ecad.py` 가 component/net/layer 노드와 `net` 엣지를 만들고 `ir_version` 을 `'1.1'` 로 올린다.
- 그 전에 ecad 를 가정하는 코드는 `missing.ecad_absent` 분기뿐이다 — §6 의 ECAD 의존 도메인 6(`pcb · pwr · rf · soc · passive · mem`)은 대표 1석 외 `deferred`.

## P0 에서의 상태

- 어댑터 코드는 없다. `GET /api/meta/adapters` 가 `{kind: 'ecad', app: null, status: 'contract_only'}` 로 계약만 있음을 표시한다.
- ODB hub 는 HEAXHub 에 `external_link` 앱(`integrations/odb-hub`)으로만 있고 게이트웨이 백엔드가 없다. 계약 합의(정본 §10 (9)·(14a))가 P7 선행 조건이다.
