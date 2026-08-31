[리스크심사 M22 snap:1a2b3c4d5e6f708192a3b4c5d6e7f809] 결정문

(3) 도메인별 리스크 판정. F1 [mech] PLATE_2 와 BRACKET_L 사이 간섭이 auto 로 남아 있다 [e:9a1f3c2b0d4e].

(8) 판정 후보 undetermined. 아래 기계판독은 출력이 잘려 닫는 괄호가 맞지 않는다 — 펜스 안 JSON 파싱이 실패하고, 마지막 균형 중괄호 블록도 유효한 JSON 이 아니라 파서는 null 을 돌려줘야 한다.

```json
{"schema":"risk_spec","version":"1.0","taxonomy_version":"1.0",
 "scope":{"kind":"snap","target_key":"snap:1a2b3c4d5e6f708192a3b4c5d6e7f809","project_refs":[],"ir_refs":["1a2b3c4d5e6f708192a3b4c5d6e7f809"],"diff_ref":null,"ir_hash":""},
 "findings":[{"id":"F1","direction":"risk","domain":"mech","mechanism":"interface","mechanism_detail":"interference","change_kind":"none",
   "subject":{"ckeys":[],"names":["PLATE_2","BRACKET_L"]},"trigger_condition":"none",
   "severity":"중대","judgement":"WARNING","detectability":{"level":"sim-detectable","tool":"list_interfaces"},
   "evidence_grade":"도구예측","precedent":"none","cites":[],"tool_calls":[],
   "claim":"PLATE_2 와 BRACKET_L 사이 간섭이 auto 로 남아 있다.","warrant":"status=auto 다.",
   "resolving_check":{"kind":"tool","ref":"set_interface"},
   "owner_domain":"mech","raised_by":["mech-housing-structure"],"contested_by":[],"contest_note":"","status":"open"
 "gains":[],"cross_domain":[],"character":{"one_liner":"","facets":[]},"open_items":[],
 "coverage":{"seats":[],"domains_seated":[],"domains_missing":[]},
 "verdict":"undetermined","verdict_conditions":[],
 "evidence_profile":{"tool":0,"card":0,"precedent":{"verified":0,"dismissed":0},"heuristic":0,"measured":0}
```
