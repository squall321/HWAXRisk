# HWAXRisk — 에이전트용 안내

설계 리스크 심사 앱(HEAX 앱 `hwax_risk`). 백엔드는 `backend/`, 화면은 `frontend/` 다.

## 나눠 맡는다

- `frontend/` 는 화면 세션의 몫이다. 백엔드 세션은 응답 필드(계약)까지만 바꾼다.
- 백엔드의 큰 흐름은 리스크 심사 재설계가 정한다 — 계획과 결정은 형제 리포 `../HWAXPortal/docs/risk-review-redesign/`(PLAN · M2 · checklist · context-notes)에 있다.

## 스키마는 v4 까지 나갔다

- v4(재설계 M2 — 검토 단위·셀 원장)는 dev 배선 리허설을 통과하고 2026-10-12 에 main 에 올랐다. 나간 판은 고치지 않는다 — `backend/tests/test_store.py` 의 `PUSHED_DDL_SHA256` 이 지킨다.
- 다음 판(v5)은 재설계 M3 몫이다(`rr_roster.input_gaps_json` 등). 스키마가 필요하면 재설계 문서에 먼저 적고 그 블록에 합친다.
- 배선 리허설은 `backend/tests/synth/rehearsal_d.py` 다(빈 포트·스크래치 디렉터리, 약 4.5분). 카드 대조 사슬을 바꿨으면 다시 돌린다.
