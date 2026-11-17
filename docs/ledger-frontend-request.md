<!-- 판정표 원장(RK-01 ~ RK-07) 화면 요청서 — 백엔드가 낸 경로 · 응답 칸과 화면이 보일 것(화면 세션 몫, 백엔드는 짓지 않았다) -->
# 화면 요청 — 판정표 원장(RK-01 ~ RK-07)

백엔드 가지 `wt1117/rk`(포털 `docs/request-1117`)가 낸 것이다. 화면은 짓지 않았다(CLAUDE.md — `frontend/` 는 화면 세션 몫). 설계는
[ledger-rk01-07.md](ledger-rk01-07.md). 쓰기 단추는 대상의 편집자 이상에게만 보인다(보기는 403 `role_insufficient`).

## 청할 것

1. **대상 화면의 '판정표' 탭** — `GET /api/targets/{key}/ledger` 의 `templates`(종류별 판) · `versions`(판 · 기준 판 · 칸 정의 판 · 행 수 · 등급 바뀐
   코드 수) · `layers`(쓰지 않은 층은 `used false`) · `bundles` · `recent_exports` 를 보인다. 칸 정의가 없으면 등록 안내를 보인다.
2. **판 비교** — `GET …/ledger/versions/{v}/diff?base=` 의 `changes`(코드 · 칸 · 앞뒤 값)를 표로, `codes_added` · `codes_removed` ·
   `grade_changed_codes` 를 머리에 보인다. 빈 칸 앞뒤는 '(빈 칸)' 으로.
3. **덮은 차례 보기** — 판 머리의 `layers`(이름 · 차례 · 원천 파일 · 덮은 칸 · 바뀐 칸 · 새 코드). 칸 하나의 덮인 내력이 필요하면 백엔드에
   경로를 청한다(지금은 `rr_ledger_cells` 를 읽는 REST 가 없다).
4. **내보내기 단추** — `GET …/export?fmt=csv`(파일 받기 — 첫 줄이 보안 문구다, 수식으로 읽힐 칸은 앞에 `'` — 그 수는 `X-Formula-Guarded` 머리) ·
   `fmt=json`. 원본 대조용 `raw=true` 는 따로 단추로(설명과 함께). 내보낼 때마다 기록이 선다는 것을 단추 곁에 적는다.
5. **근거 묶음 만들기** — 틀(칸별 상한 · 합 상한) 입력 꼴과 `POST …/evidence-bundles` 답의 `per_field`(자수 · 잘림 · 잘린 코드 수) ·
   `masked_n` · `limits` · `label_check`. 422 `bundle_too_many_items` · `bundle_too_large` 는 `detail` 의 넘은 값과 상한을 보인다.
6. **결정 반영 미리 보기** — `POST …/ledger/layers/from-decision` 답의 `cells`(상태별 색 — filled · empty · conflict · no_source) · `counts` ·
   `consistency`(match false 면 경고 띠 — '결정문은 만장일치를 말하는데 표결에 조건부 · 반대가 있다') · `notes`.
7. **숫자 점검** — `POST …/numbers/check` 답의 네 목록(원장에 없는 수 · 금지값 · 단위 불일치 · 원장에 없는 id)을 위치(where · col · 앞뒤 글)와 함께.
8. **출처 표지** — 과제 화면에 `GET /api/projects/{id}/provenance` 의 `warnings`(이른 사본 · 더 진행된 사본 · 빈/옛 앱 키 · 운영 아닌 env · 요소 없는 파트 · 요소 id 충돌 · 빠진 파트 · 운영 아닌 리포트)를 띠로,
   `checks` 를 상태 칩(ok · warn · unknown)으로, `unknown` 칸은 '모름 — 까닭' 으로 보인다.
9. **표기** — 등급 · 증거 유형 · 주의 등급 · 판정 글자는 `GET /api/taxonomy/labels` 의 표시 글로 보인다(같은 글자를 축 낱말 없이 쓰지 않는다).
