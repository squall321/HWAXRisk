# HWAXRisk — 에이전트용 안내

설계 리스크 심사 앱(HEAX 앱 `hwax_risk`). 백엔드는 `backend/`, 화면은 `frontend/` 다.

## 나눠 맡는다

- `frontend/` 는 화면 세션의 몫이다. 백엔드 세션은 응답 필드(계약)까지만 바꾼다.
- 백엔드의 큰 흐름은 리스크 심사 재설계가 정한다 — 계획과 결정은 형제 리포 `../HWAXPortal/docs/risk-review-redesign/`(PLAN · M2 · checklist · context-notes)에 있다.

## 스키마 v4 는 예약돼 있다

- `backend/app/risk_store.py` 의 `MIGRATIONS` 다음 판(v4)은 **재설계 M2 몫**이다. 가지 `m2-cells` 에서 짓고 있고, dev 리허설이 끝날 때까지 main 에 올리지 않는다(PLAN 4절 C-2).
- 그동안 main 에서 `MIGRATIONS` 에 판을 더하거나 표·열을 바꾸지 않는다. 스키마가 필요하면 재설계 문서에 먼저 적고 그 블록에 합친다.
