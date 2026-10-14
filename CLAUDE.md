# HWAXRisk — 에이전트용 안내

설계 리스크 심사 앱(HEAX 앱 `hwax_risk`). 백엔드는 `backend/`, 화면은 `frontend/` 다.

## 나눠 맡는다

- `frontend/` 는 화면 세션의 몫이다. 백엔드 세션은 응답 필드(계약)까지만 바꾼다.
- 백엔드의 큰 흐름은 리스크 심사 재설계가 정한다 — 계획과 결정은 형제 리포 `../HWAXPortal/docs/risk-review-redesign/`(PLAN · M2 · checklist · context-notes)에 있다.

## 스키마는 v4 까지 나갔고 v5 는 예약돼 있다

- v4(재설계 M2 — 검토 단위·셀 원장)는 dev 배선 리허설을 통과하고 2026-10-12 에 main 에 올랐다. 나간 판은 고치지 않는다 — `backend/tests/test_store.py` 의 `PUSHED_DDL_SHA256` 이 지킨다.
- **v5 는 재설계 M3 몫이다.** 통합 가지 `m3` 에서 짓고(꾸러미 하위 가지 `m3-cells`·`m3-synth` 는 `m3` 위로 rebase 한다), 블록(`backend/app/risk_store.py` 의 `_DDL_V5_SQL`)의 주인은 쟁점·종합 꾸러미의 걸음 S3-1 하나다 — 셀 꾸러미의 `rr_unit_live` 도 그 블록 안에 있다. 단계 D(dev 리허설) 전에는 push 하지 않는다(재설계 PLAN 4절 C-2 · M3.md 3절).
- 그동안 main 에서 `MIGRATIONS` 에 판을 더하거나 표·열을 바꾸지 않는다. 스키마가 필요하면 재설계 문서(M3.md 4.2)에 먼저 적고 블록 주인이 그 블록에 합친다.
- 배선 리허설은 `backend/tests/synth/rehearsal_d.py` 다(빈 포트·스크래치 디렉터리, 약 4.5분). 카드 대조 사슬을 바꿨으면 다시 돌린다.
