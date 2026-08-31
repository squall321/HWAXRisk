[리스크심사 M22 snap:1a2b3c4d5e6f708192a3b4c5d6e7f809] 결정문

(1) 대상. 과제 M22 스냅샷 1a2b3c4d. 앞 문단에 다른 중괄호 블록이 하나 있다 — {"note":"이건 spec 이 아니다"} — 파서는 텍스트 끝에서 역방향으로 마지막 균형 블록만 취한다.

(3) 도메인별 리스크 판정. F1 [mech] PLATE_2 와 BRACKET_L 사이 간섭이 auto 로 남아 있다 [e:9a1f3c2b0d4e]. 중대·WARNING.

(8) 판정 후보 undetermined. 아래는 펜스 없이 낸 기계판독이다.

{"schema":"risk_spec","version":"1.0","taxonomy_version":"1.0",
 "scope":{"kind":"snap","target_key":"snap:1a2b3c4d5e6f708192a3b4c5d6e7f809","project_refs":["0f1e2d3c4b5a69788796a5b4c3d2e1f0"],"ir_refs":["1a2b3c4d5e6f708192a3b4c5d6e7f809"],"diff_ref":null,"ir_hash":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"},
 "findings":[{"id":"F1","direction":"risk","domain":"mech","mechanism":"interface","mechanism_detail":"interference","change_kind":"none",
   "subject":{"ckeys":[],"names":["PLATE_2","BRACKET_L"]},"trigger_condition":"none",
   "severity":"중대","judgement":"WARNING","detectability":{"level":"sim-detectable","tool":"list_interfaces"},
   "evidence_grade":"도구예측","precedent":"none",
   "cites":[{"ref":"e:9a1f3c2b0d4e","quote":"PLATE_2↔BRACKET_L interference penetration_depth≥0.05 mm(lower_bound) status=auto(미확정 초안)"}],
   "tool_calls":["list_interfaces(kind=interference)"],
   "claim":"PLATE_2 와 BRACKET_L 사이 간섭이 auto 로 남아 있어 억지끼움 의도인지 확정되지 않았다.",
   "warrant":"penetration_depth 하한 0.05 mm 가 검출되었고 status=auto 다.",
   "resolving_check":{"kind":"tool","ref":"set_interface 로 kind 확정 후 재스냅샷"},
   "owner_domain":"mech","raised_by":["mech-housing-structure"],"contested_by":[],"contest_note":"","status":"open"}],
 "gains":[],"cross_domain":[],
 "character":{"one_liner":"3 리프 적층 시제 — 간섭 1건 미확정.",
  "facets":[{"facet":"intent","statements":[],"na_reason":"좌석 미기재"},{"facet":"constraint","statements":[],"na_reason":"좌석 미기재"},
            {"facet":"anomaly","statements":[],"na_reason":"비교 불가(코퍼스 n<5)"},{"facet":"lineage","statements":[],"na_reason":"선행 과제 미지정"},
            {"facet":"vulnerability","statements":[],"na_reason":"좌석 미기재"},{"facet":"strength","statements":[],"na_reason":"개선 항목 없음"},
            {"facet":"tradeoff","statements":[],"na_reason":"단면만 기술"},{"facet":"unknown","statements":[],"na_reason":"미지 항목 없음"}]},
 "open_items":[],
 "coverage":{"seats":[{"key":"mech-housing-structure","domain":"mech","origin":"primary"}],"domains_seated":["mech"],
             "domains_missing":["xd","sim","cam","rel","soc","disp","pcb","rf","passive","pwr","sh","mem","std","material"]},
 "verdict":"undetermined","verdict_conditions":[],
 "evidence_profile":{"tool":1,"card":0,"precedent":{"verified":0,"dismissed":0},"heuristic":0,"measured":0}}
