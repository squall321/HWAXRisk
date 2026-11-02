# HWAXRisk — 에이전트용 안내

설계 리스크 심사 앱(HEAX 앱 `hwax_risk`). 백엔드는 `backend/`, 화면은 `frontend/` 다.

## 나눠 맡는다

- `frontend/` 는 화면 세션의 몫이다. 백엔드 세션은 응답 필드(계약)까지만 바꾼다.
- 백엔드의 큰 흐름은 리스크 심사 재설계가 정한다 — 계획과 결정은 형제 리포 `../HWAXPortal/docs/risk-review-redesign/`(PLAN · M2 · checklist · context-notes)에 있다.

## 스키마는 v5 까지 나갔고 v6 은 과제 인사이트 그래프 M2b 다

- v4(재설계 M2 — 검토 단위·셀 원장)는 2026-10-12, v5(재설계 M3 — 쟁점·종합·완결)는 2026-10-15 에 main 에 올랐다. 나간 판은 고치지 않는다 — `backend/tests/test_store.py` 의 `PUSHED_DDL_SHA256` 이 지킨다.
- **v6 은 과제 인사이트 그래프 M2b 몫이다**(`rr_projects.sp_task` 한 칸과 색인 — 포털 `docs/project-insight-graph/contracts.md` §9). main 에 오르는 날 `PUSHED_DDL_SHA256[6]` 이 굳는다. 재설계 M4 가 v6 에 두기로 적었던 `rr_reports.ra_*` 는 다음 판(v7)으로 간다.
- 새 판은 허용 연산(CREATE TABLE IF NOT EXISTS · ADD COLUMN · CREATE INDEX IF NOT EXISTS)만 쓰고, 판을 더하는 커밋이 `PUSHED_DDL_SHA256` 에 해시를 같이 적는다.
- 배선 리허설은 `backend/tests/synth/rehearsal_d.py` 다(빈 포트·스크래치 디렉터리, 약 4.5분). 카드 대조 사슬을 바꿨으면 다시 돌린다.
