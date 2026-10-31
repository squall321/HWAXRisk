# 옛 타깃 골든 변경 기록

`risk_review.v2.db.gz` 와 `golden/*.json` 은 HWAXRisk `7248651`(스키마 v2) 코드로 `tests/rr/legacy_build.py` 가 만들었다.
DB 는 다시 만들지 않는다. 새 코드로 만들면 '옛 DB 를 새 코드로 연다' 는 시험이 빈 시험이 된다.

골든은 불변 사영이다 — 키가 더해지는 것은 통과하고, 있던 키의 값이 달라지면 `tests/rr/test_legacy_flow.py` 가 붉다.
재설계가 그 값을 일부러 바꾸는 커밋은 골든의 그 칸만 고치고 아래에 한 줄을 더한다(커밋 · 칸 · 까닭).

| 커밋 | 칸 | 까닭 |
|---|---|---|
| (얼림) | 전부 | `7248651` 에서 받았다 |
| `feat(브리프 제외 · 사람 개입 요약 B31)` | `golden/{done,planned,human}.json` 의 `report.block_lines.minutes`(12→14 · 10→12 · 10→13) | 통합 보고서 minutes 끝에 '[사람 개입 요약]'(plan §4.7.3 — 그 대상 rr_audit 의 action 별 수, 없으면 '(없음)')이 붙었다. human 은 사람 finding · 게이트 ack 두 줄이다 |
