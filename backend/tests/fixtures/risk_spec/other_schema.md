[해석 계획] 결정문

(1) 메커니즘. 낙하 시 UTG 에지 우선 접촉.

(8) 해석 설계. 아래는 sim_spec 이지 risk_spec 이 아니다 — 파서는 schema 가 'risk_spec' 이 아니면 null 을 돌려준다.

```json
{"schema":"sim_spec","version":"1.0",
 "objective":"코너 낙하 corner_45 에서 UTG 최대 응력 확인",
 "solver":"ls-dyna","cases":[{"name":"corner_45","drop_height_m":1.0}],
 "outputs":["worst_stress","worst_disp"]}
```
