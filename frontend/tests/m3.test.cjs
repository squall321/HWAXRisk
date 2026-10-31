// M3 화면 시험 — 사슬 · 진행판 · 처분 · 쟁점 · 보고서 쪽 · 완결 · 등록부의 순수 판정과, 실 백엔드 견본(src/contract/serverSamples.ts)으로 그린 조각
const test = require("node:test");
const assert = require("node:assert/strict");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const { MemoryRouter } = require("react-router-dom");
const load = require("./load.cjs");

const view = load("lib/reviewView.js");
const cells = load("lib/cellView.js");
const issues = load("lib/issueView.js");
const closure = load("lib/closureView.js");
const report = load("lib/reportView.js");
const errors = load("api/reviewErrors.js");
const { ApiError, NotReadyError } = load("api/risk.api.js");
const samples = load("contract/serverSamples.js");
const { MarkdownLines } = load("components/MarkdownLines.js");
const { CellsHead } = load("components/CellsHead.js");
const { ReviewBoard } = load("components/ReviewBoard.js");
const { RegistryRowDetail, IssueCell, rowDomains, supportText } = load("components/RegistryCard.js");

const h = React.createElement;
const clone = (v) => JSON.parse(JSON.stringify(v));
const routed = (el) => renderToStaticMarkup(h(MemoryRouter, null, el));
const noop = () => {};

// ── 1절 — 사슬 · 완결 표기 ────────────────────────────────────────────────────

test("사슬 배지 — 단계 · 멈춤의 까닭(pat_unavailable · restart · draining)과 재개 여부", () => {
  assert.equal(view.stageView(null), null);
  const queued = view.stageView({ mode: "issues", job_id: "j", state: "queued", hold_code: null, pause_reason: null, error: null });
  assert.equal(queued.label, "쟁점 패널 중");
  assert.equal(queued.resumable, false);
  const pat = view.stageView({ mode: "synth", job_id: "j", state: "queued", hold_code: null, pause_reason: null, error: "pat_unavailable: 등록된 PAT 가 없다" });
  assert.equal(pat.label, "종합 중");
  assert.equal(pat.needsPat, true);
  assert.match(pat.note, /PAT 를 등록하면 저절로 집힙니다/);
  const restart = view.stageView({ mode: "issues", job_id: "j", state: "paused", hold_code: null, pause_reason: "user", error: "restart: 앱 재기동" });
  assert.equal(restart.resumable, true);
  assert.equal(restart.label, "쟁점 패널 멈춤(user)");
  assert.match(restart.note, /사람이 재개해야 합니다/);
  assert.match(view.stageView({ mode: "issues", job_id: "j", state: "running", hold_code: null, pause_reason: null, error: "draining: 비우기" }).note, /비우는 동안/);
  assert.equal(view.stageView({ mode: "synth", job_id: "j", state: "completed", hold_code: null, pause_reason: null, error: null }).label, "종합 끝");
  assert.match(view.adviceText("issue_yield_low"), /잡은 멈추지 않습니다/);
  assert.equal(view.adviceText(undefined), null);
});

test("M2 시절 잡 뒤의 사슬 시작 — 사슬 · 판이 없고 마지막 검토 잡이 끝났고 대기 셀이 0 일 때만", () => {
  const base = clone(samples.coverageCells);
  base.stage = null;
  base.report = null;
  base.review.job.state = "completed";
  base.review.cells.by_state.pending = 0;
  assert.equal(view.chainStartVisible(base), true);
  assert.equal(view.chainStartVisible({ ...base, flow: "panels" }), false);
  assert.equal(view.chainStartVisible({ ...base, stage: samples.coverageCells.stage }), false);
  assert.equal(view.chainStartVisible({ ...base, report: samples.coverageCells.report }), false);
  const pending = clone(base);
  pending.review.cells.by_state.pending = 1;
  assert.equal(view.chainStartVisible(pending), false);
  const queued = clone(base);
  queued.review.job.state = "queued";
  assert.equal(view.chainStartVisible(queued), false);
  // 견본 그대로(사슬 잡 대기 · 판 v6)는 버튼이 없다.
  assert.equal(view.chainStartVisible(samples.coverageCells), false);
});

test("대상 머리 — 완결 표기는 서버 글 그대로, 확인 안 된 막음 잔여 표지 · 사슬 배지 · 보고서 판 링크", () => {
  const cov = samples.coverageCells;
  assert.equal(view.blockingUnacked(cov.qualifiers), 2); // skipped · issues_untried(취소됨) — quality 는 확인됨
  const html = routed(h(CellsHead, { coverage: cov, targetKey: cov.target_key, onChanged: noop, onOpenTab: noop }));
  assert.ok(html.includes(cov.level_label.replace(/&/g, "&amp;")));
  assert.match(html, /확인 안 된 막음 잔여 2 — 완결 화면/);
  assert.match(html, /쟁점 패널 중/);
  assert.match(html, /종합 보고서 v6/);
  assert.doesNotMatch(html, /쟁점 · 종합 시작/);
  // 멈춘 사슬 잡(재기동이 닫았다)은 재개 버튼과 까닭을, PAT 없음은 설정 길을 보인다.
  const paused = clone(cov);
  paused.stage = { ...paused.stage, state: "paused", pause_reason: "user", error: "restart: 앱 재기동이 패널을 닫았다" };
  const p = routed(h(CellsHead, { coverage: paused, targetKey: cov.target_key, onChanged: noop, onOpenTab: noop }));
  assert.match(p, />재개</);
  assert.match(p, /사람이 재개해야 합니다/);
  const pat = clone(cov);
  pat.stage = { ...pat.stage, error: "pat_unavailable: 등록된 PAT 가 없다" };
  assert.match(routed(h(CellsHead, { coverage: pat, targetKey: cov.target_key, onChanged: noop, onOpenTab: noop })), /href="\/settings"/);
  const m2 = clone(cov);
  m2.stage = null;
  m2.report = null;
  m2.review.job.state = "completed";
  m2.review.cells.by_state.pending = 0;
  assert.match(routed(h(CellsHead, { coverage: m2, targetKey: cov.target_key, onChanged: noop, onOpenTab: noop })), /쟁점 · 종합 시작/);
});

// ── 2절 — 진행판 줄 ──────────────────────────────────────────────────────────

const FILTER = {
  mode: "on",
  approved: true,
  would_filter: 40,
  filtered: 30,
  audited: 12,
  audit: { risk_miss: 1, relevance_miss: 0, undetermined: 0, kept: 11, upper95: 0.0523, upper95_conservative: 0.06, n_audit: 12, floor_met: true, pending: 0 },
  shadow: { would_filter: 0, sampled: 0, risk_miss: 0, upper95: null },
  widened: [],
  off: false,
  saved_calls_est: 150,
};

test("거르기 줄 — 승인 전 · 잡 전 · 표본 없음(0% 가 아니다) · 넓힌 영역 · 끔 · 그림자", () => {
  assert.equal(view.filterLines(FILTER)[0], "거름 30셀 · 표본 12 · 놓친 걸림 1 · 95% 상한 5.2% (거르기 on)");
  assert.equal(view.filterLines({ ...FILTER, approved: false })[0], "배정표 승인 전 — 거르지 않는다(거르기 on).");
  assert.match(view.filterLines({ ...FILTER, approved: null })[0], /^검토 잡 전/);
  const none = view.filterLines({ ...FILTER, audit: { ...FILTER.audit, upper95: null } })[0];
  assert.match(none, /95% 상한 표본 없음/);
  assert.doesNotMatch(none, /0\.0%/);
  const widened = view.filterLines({ ...FILTER, widened: ["xd", "sim"], off: true });
  assert.ok(widened.includes("넓힌 영역 xd · sim"));
  assert.ok(widened.includes("이 대상의 거르기를 껐다(넓힌 영역 셋 이상)."));
  assert.match(view.filterLines({ ...FILTER, mode: "shadow" })[1], /^그림자 — 걸렀을 셀 0/);
  // 실 서버 값(검토가 끝난 대상 — 거른 셀 0 · 표본 없음)
  assert.equal(view.filterLines(samples.coverageCells.review.filter)[0], "거름 0셀 · 표본 0 · 놓친 걸림 0 · 95% 상한 표본 없음 (거르기 on)");
});

test("입력 결손 · 처분 · 단계 · 다시 연 셀 줄", () => {
  assert.equal(
    view.noinputLine({ experts: 3, cells: 15, by_outcome: { impact: 2, unknown: 5, request: 3, none: 5 } }),
    "입력 결손 3명 · 15셀(영향 있음 2 · 모름 5 · 확인할 것 3 · 없음 5)",
  );
  assert.equal(view.dispositionsLine(samples.coverageCells.review.dispositions), "사람이 다시 연 셀 1 · 넘긴 셀 1");
  assert.equal(view.phaseLabel("live"), "근거 꾸러미 실호출");
  assert.equal(view.phaseLabel("completed"), "completed");
  assert.equal(view.phaseLabel(null), "진행판 전");
  const extra = samples.coveragePausedConsent.review.job.progress.reopened_extra;
  assert.equal(view.reopenedLine(extra), "다시 연 셀 2(추정 11회 · 여유 2회) · 동의 안 받은 1셀(추정 5회)");
  assert.equal(view.reopenedLine({ ...extra, cells: 0 }), null);
});

test("호출 줄 — ok / 추정, 남은 시간 어림은 평균 · 추정이 있을 때만(거르기 없음 가정이라 실제보다 길다)", () => {
  assert.match(view.callsLine(null, 100, 0).head, /호출 셈 전/);
  const line = view.callsLine({ ok: 40, infra_fail: 2, content_fail: 1, wait: 0, aborted: 0, last_ok_at: 1, avg_ok_s: 300 }, 100, 4);
  assert.equal(line.head, "호출 ok 40 / 추정 100");
  assert.equal(line.tail, "인프라 실패 2 · 내용 실패 1");
  assert.match(line.eta, /^남은 시간 어림 1시간 15분\(남은 60회 × 평균 300초 ÷ 도는 호출 4/);
  assert.equal(view.callsLine({ ok: 40, avg_ok_s: 0 }, 100, 4).eta, null);
  // 실 서버 값 — 끝난 잡(ok 105 · 추정 164 · 평균 0초)
  const real = view.callsLine(samples.coverageCells.review.job.progress.calls, null, 0);
  assert.equal(real.head, "호출 셈 전(진행판을 아직 세지 않았다)");
});

test("보류 — reopened_extra.hold 로 가른다(consent_extra 는 동의 재개, max_calls 는 넘김을 앞에)", () => {
  const job = samples.coveragePausedConsent.review.job;
  assert.deepEqual(view.holdView(job), { reopenHold: "consent_extra", resume: "consent", skipWaiting: true });
  const max = clone(job);
  max.progress.reopened_extra.hold = "max_calls";
  assert.deepEqual(view.holdView(max), { reopenHold: "max_calls", resume: "blocked", skipWaiting: true });
  // 사람이 멈춘 잡도 몫이 넘쳐 있으면 같은 동의가 든다 — 보류 코드가 아니라 몫으로 본다.
  const user = clone(job);
  user.hold_code = "user";
  assert.equal(view.holdView(user).resume, "consent");
  const plain = clone(job);
  plain.progress.reopened_extra.hold = null;
  assert.equal(view.holdView(plain).resume, "plain");
  assert.equal(view.holdView({ ...job, state: "running" }).resume, null);
});

test("진행판 렌더 — consent_extra 로 멈춘 잡: 몫 · 미리 체크하지 않은 동의 · 잠긴 '동의하고 재개' · 기다리는 셀 넘기기", () => {
  const cov = samples.coveragePausedConsent;
  const html = renderToStaticMarkup(h(ReviewBoard, { review: cov.review, targetKey: cov.target_key, onChanged: noop }));
  assert.match(html, /동의를 기다리는 다시 연 셀 1개 · 호출 추정 5회/);
  assert.match(html, /<input type="checkbox"\/>/); // checked 가 없다
  assert.match(html, /<button[^>]*disabled=""[^>]*>동의하고 재개<\/button>/);
  assert.match(html, /기다리는 셀 넘기기…/);
  assert.match(html, /멈춤 — consent_extra/);
  assert.match(html, /거름 \d+셀/);
  assert.match(html, /입력 결손 0명/);
  // max_calls — 재개는 잠기고(409) 넘김이 앞에, 동의 칸은 없다.
  const max = clone(cov.review);
  max.job.progress.reopened_extra.hold = "max_calls";
  const m = renderToStaticMarkup(h(ReviewBoard, { review: max, targetKey: cov.target_key, onChanged: noop }));
  assert.match(m, /<button[^>]*disabled=""[^>]*>재개\(상한 넘음\)<\/button>/);
  assert.doesNotMatch(m, /동의하고 재개/);
  assert.match(m, /기다리는 셀 넘기기…/);
});

test("진행판 렌더 — 셀 상태 말(거름 · 입력 결손 — 판정 못 함), 끝난 잡의 글은 '오류' 가 아니라 잡이 남긴 글", () => {
  const review = clone(samples.coverageCells.review);
  review.job.state = "completed";
  review.job.error = "범위 안 셀 2개가 실패로 끝났다 — 사람이 처분한다";
  const html = renderToStaticMarkup(h(ReviewBoard, { review, targetKey: "t", onChanged: noop }));
  assert.match(html, /거름 0/);
  assert.match(html, /입력 결손 — 판정 못 함 0/);
  assert.match(html, /잡이 남긴 글: <span>범위 안 셀 2개가 실패로 끝났다/);
  assert.doesNotMatch(html, /오류: /);
  assert.match(html, /사람이 다시 연 셀 1 · 넘긴 셀 1/);
});

// ── 3절 — 검토 잡 본문 · 처분 ────────────────────────────────────────────────

test("검토 잡 본문 — 빈 범위 칸은 싣지 않고(전원), 동의는 체크했을 때만 true", () => {
  const empty = { tiers: [], domains: [], agents: " , ", unitIds: "", memo: " ", consent: false };
  assert.equal(JSON.stringify(view.reviewJobBody(empty)), '{"mode":"reviews"}');
  const full = view.reviewJobBody({ tiers: ["A"], domains: ["xd"], agents: "a1, a2,a1", unitIds: "u1", memo: " 메모 ", consent: true });
  assert.deepEqual(full, { mode: "reviews", scope: { tiers: ["A"], domains: ["xd"], agents: ["a1", "a2"], unit_ids: ["u1"] }, user_memo: "메모", consent: true });
  assert.equal("consent" in view.reviewJobBody({ ...empty, consent: false }), false);
});

test("처분 사유 — 4~300자(앞뒤 공백 뗌), 선택일 때 비면 문제 없음", () => {
  assert.match(view.reasonProblem("", true), /4~300자/);
  assert.equal(view.reasonProblem("   ", false), null);
  assert.match(view.reasonProblem(" 새판 ", true), /4자 이상입니다 — 지금 2자/);
  assert.equal(view.reasonProblem("  네 글자  ", true), null);
  assert.match(view.reasonProblem("가".repeat(301), false), /300자까지입니다/);
});

test("처분 답 — 잡에 한 일(넘김이 세운 마감 잡 · 얹힘과 멈춤 · 다음 잡) · 걸림 셈(pack_missing 은 0 이 아니라 모름)", () => {
  assert.match(view.disposeJobLine({ action: "created", job_id: "j1" }, "skip"), /넘긴 셀만 묶은 마감 잡/);
  assert.match(view.disposeJobLine({ action: "created", job_id: "j1", calls_estimate: { low: 1, expected: 6, high: 9, basis: "" } }), /호출 추정 6회/);
  const adopted = view.disposeJobLine(samples.retryAdopted.job);
  assert.match(adopted, /얹힘 1 · 다음 잡 기다림 0/);
  assert.match(adopted, /잡이 멈췄습니다\(consent_extra\)/);
  assert.match(view.disposeJobLine({ action: "waiting", job_id: "j", waiting: 1 }), /다음 잡이 집습니다\(1셀\)/);
  assert.equal(view.hitsLine({ hits: 3, hits_by: { card: 1, offcard: 1, noinput: 1 }, hits_basis: "members" }), "이미 판정된 걸림 3(카드 1 · 카드 밖 1 · 입력 결손 1)");
  const missing = view.hitsLine({ hits: null, hits_by: null, hits_basis: "pack_missing", hits_note: "얼린 카드 묶음이 이 박스에 없다" });
  assert.match(missing, /^이미 판정된 걸림 — 모름/);
  assert.doesNotMatch(missing, / 0\(/);
  assert.equal(view.hitsLine(samples.retryAdopted), null); // 다시의 답에는 걸림 셈이 없다
});

test("셀 격자 — 쪽 행을 전문가 × 단위로(전문가는 온 차례, 단위는 순번), 칸의 짧은 말과 말풍선", () => {
  const rows = samples.cellRows.rows;
  const m = cells.cellMatrix(rows);
  assert.deepEqual(m.agents.map((a) => a.agent_key), [...new Set(rows.map((r) => r.agent_key))]);
  assert.deepEqual(m.units.map((u) => u.unit_seq), [...m.units.map((u) => u.unit_seq)].sort((a, b) => a - b));
  const skipped = rows.find((r) => r.state === "skipped");
  const retried = rows.find((r) => r.route_forced === "human_retry");
  assert.equal(cells.cellShortLabel(skipped), "넘김");
  assert.equal(cells.cellShortLabel(retried), "대기 사람 ↺1");
  assert.equal(cells.cellShortLabel({ ...skipped, state: "no_input" }), "입력 결손");
  assert.equal(cells.cellShortLabel({ ...skipped, state: "na_irrelevant", route: "audit" }), "거름 표본");
  const title = cells.cellTitle({ ...skipped, filter_reason: "코드 신호 무관(관련 영역 xd) · 훑기 무관 «대상 밖»", error_code: "no_rows", error: "판정 행 없음" });
  assert.match(title, /거른 까닭: 코드 신호 무관/);
  assert.match(title, /오류: no_rows — 판정 행 없음/);
  assert.match(title, /사람의 처분: /);
  assert.notEqual(cells.cellKey(rows[0]), cells.cellKey({ ...rows[0], agent_key: rows[0].agent_key + "x" }));
});

// ── 거절 code ────────────────────────────────────────────────────────────────

const apiError = (status, code, body = {}) => new ApiError(status, code, "서버 글", { error: { code, message: "서버 글" }, ...body });

test("거절은 code 로 — 다음 걸음(동의 · 설정 · 다시 읽기 · 처음 쪽부터)과 detail 꺼내기", () => {
  assert.equal(errors.describeReviewError(apiError(422, "consent_required")).next, "consent");
  assert.equal(errors.describeReviewError(apiError(422, "pat_unavailable")).next, "settings");
  assert.equal(errors.describeReviewError(apiError(409, "report_version_moved")).next, "restart");
  assert.equal(errors.describeReviewError(apiError(409, "residual_changed")).next, "reload");
  assert.equal(errors.describeReviewError(apiError(409, "issue_in_flight")).next, "reload");
  assert.equal(errors.describeReviewError(apiError(500, "모르는_코드")), null);
  assert.equal(errors.describeReviewError(new Error("x")), null);
  const est = { low: 10, expected: 1600, high: 4000, basis: "k 8" };
  assert.deepEqual(errors.estimateOf(apiError(422, "consent_required", { calls_estimate: est, knob: "HWAXRISK_REVIEW_CONSENT_CALLS" })), est);
  assert.deepEqual(errors.estimateOf(apiError(409, "review_too_large", { calls_estimate: est })), est);
  assert.equal(errors.estimateOf(apiError(422, "scope_invalid", { calls_estimate: est })), null);
  const extra = samples.coveragePausedConsent.review.job.progress.reopened_extra;
  assert.deepEqual(errors.reopenedOf(apiError(422, "consent_required", { reopened_extra: extra })), extra);
  assert.deepEqual(errors.versionMovedOf(apiError(409, "report_version_moved", { version: 6, asked: 5 })), { version: 6, asked: 5 });
  assert.deepEqual(errors.residualChangedOf(apiError(409, "residual_changed", { item: "failed", basis_hash: "abc", basis_n: 3 })), {
    item: "failed",
    basis_hash: "abc",
    basis_n: 3,
  });
  assert.equal(errors.pagesTotalOf(apiError(422, "E100", { pages_total: 0 })), 0);
  assert.equal(errors.pagesTotalOf(apiError(422, "E100")), null);
  // 404 report_absent 는 NotReadyError 로 오지만 code 가 그대로다(판 없음 자리를 고른다).
  assert.equal(errors.describeReviewError(new NotReadyError(404, "report_absent", "판 없음")).title, "이 대상에는 종합 보고서 판이 아직 없습니다.");
});

// ── 4절 — 쟁점 ───────────────────────────────────────────────────────────────

test("쟁점 한 줄 — '제기 N명(분포) · 반대 M명 → 쟁점 패널 결과', 결과가 없으면 상태(사유)", () => {
  const [resolved] = samples.issueList.rows.filter((r) => r.state === "resolved");
  assert.equal(issues.issueLine(resolved), "제기 3명(FAIL 3) · 반대 0명 → 쟁점 패널 상향");
  const after = { ...resolved, outcome_json: { panel_id: "p", severity_after: "치명", judgement_after: "FAIL" } };
  assert.equal(issues.issueLine(after), "제기 3명(FAIL 3) · 반대 0명 → 쟁점 패널 상향 치명/FAIL");
  const untried = samples.issueList.rows.find((r) => r.state === "untried_cap");
  assert.match(issues.issueLine(untried), /→ 미토의\(상한 밖\)$/);
  assert.equal(issues.distributionText({ OK: 1, FAIL: 9, WARNING: 3 }), "FAIL 9 · WARNING 3 · OK 1");
});

test("쟁점 결정 버튼 — 편성 · 도는 쟁점은 둘 다 끄고, 대기에는 건너뛰기만 · 건너뛴 쟁점에는 올리기만", () => {
  assert.deepEqual(issues.issueActions({ state: "planned" }), { queue: false, skip: false, inFlight: true });
  assert.deepEqual(issues.issueActions({ state: "running" }), { queue: false, skip: false, inFlight: true });
  assert.deepEqual(issues.issueActions({ state: "queued" }), { queue: false, skip: true, inFlight: false });
  assert.deepEqual(issues.issueActions({ state: "skipped" }), { queue: true, skip: false, inFlight: false });
  assert.deepEqual(issues.issueActions({ state: "untried_cap" }), { queue: true, skip: true, inFlight: false });
  assert.match(issues.issueReasonProblem(" "), /사유를 적으세요/);
  assert.equal(issues.issueReasonProblem("a"), null); // 쟁점 사유는 1~300자
  assert.match(issues.issueReasonProblem("가".repeat(301)), /300자까지/);
});

test("쪽 잇기 — ledger_rev 가 앞 쪽과 다르면 잇지 않는다(처음부터 다시), 순위대로 정렬은 화면이", () => {
  const page = (rev, offset, rows) => ({ ledger_rev: rev, offset, rows });
  assert.deepEqual(issues.appendPage(null, page("r1", 0, [1, 2])), [1, 2]);
  assert.deepEqual(issues.appendPage({ rev: "r1", rows: [1, 2] }, page("r1", 2, [3])), [1, 2, 3]);
  assert.equal(issues.appendPage({ rev: "r1", rows: [1, 2] }, page("r2", 2, [3])), null);
  const ranked = issues.byRank([
    { issue_id: "b", rank: null },
    { issue_id: "c", rank: 2 },
    { issue_id: "a", rank: 1 },
  ]);
  assert.deepEqual(ranked.map((r) => r.issue_id), ["a", "c", "b"]);
});

// ── 5절 — 보고서 쪽 ──────────────────────────────────────────────────────────

test("보고서 쪽 물음 — 첫 쪽은 판을 싣지 않고 둘째 쪽부터 첫 쪽의 판을 싣는다", () => {
  assert.deepEqual(report.pageQuery(1, 6), { page: 1 });
  assert.deepEqual(report.pageQuery(2, 6), { page: 2, version: 6 });
  assert.deepEqual(report.pageQuery(2, null), { page: 2 });
  assert.deepEqual(report.pageQuery(0, 6), { page: 1 });
  assert.equal(report.triggerLabel("synth_done"), "영역 요약 · 종합까지 끝");
  assert.equal(report.triggerLabel("future_trigger"), "future_trigger");
  assert.equal(report.narrativeNote("full"), null);
  assert.match(report.narrativeNote("none"), /^서술 없음 — 표는 다 있습니다/);
  assert.match(report.narrativeNote("partial"), /^서술 일부/);
});

test("쪽 블록 → 마크다운 줄 — 블록 차례대로, 조각 안의 줄바꿈으로 나눈다", () => {
  const page = { page_no: 1, kind: "expert_report", title: "t", blocks: { background: [], results: ["## 단위\n- 하나\n  - 둘"], recommendation: ["끝"], minutes: [] } };
  assert.deepEqual(report.pageLines(page), ["## 단위", "- 하나", "  - 둘", "끝"]);
  assert.deepEqual(report.parseMdLine("## 단위"), { kind: "heading", level: 2, text: "단위" });
  assert.deepEqual(report.parseMdLine("  - 둘"), { kind: "item", depth: 1, text: "둘" });
  assert.deepEqual(report.parseMdLine("  "), { kind: "blank" });
  assert.deepEqual(report.parseInline("**굵게** 와 `코드` 끝"), [
    { kind: "strong", text: "굵게" },
    { kind: "text", text: " 와 " },
    { kind: "code", text: "코드" },
    { kind: "text", text: " 끝" },
  ]);
  // 실 서버 쪽 — 본문 첫 쪽의 첫 줄은 제목이다.
  const real = report.pageLines(samples.reportSummaryPage.page);
  assert.equal(report.parseMdLine(real[0]).kind, "heading");
});

test("마크다운 렌더 — 서버 글은 글로만(HTML 로 해석하지 않는다), 굵게 · 제목 · 목록 깊이", () => {
  const html = renderToStaticMarkup(h(MarkdownLines, { lines: ["# 제목 <b>x</b>", "- **걸림** <script>alert(1)</script>", "    - 깊이 둘"] }));
  assert.match(html, /role="heading" aria-level="3"/);
  assert.match(html, /제목 &lt;b&gt;x&lt;\/b&gt;/);
  assert.match(html, /<strong>걸림<\/strong> &lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /padding-left:2\.5rem/);
});

// ── 6절 — 완결 ───────────────────────────────────────────────────────────────

test("잔여 확인 상태 — 유효 · 낡음 · 취소 · 확인 전, 확인 버튼은 막음이고 유효 확인이 없을 때만, 취소는 취소 안 된 확인에", () => {
  const byItem = Object.fromEntries(samples.closureCells.qualifiers.map((q) => [q.item, q]));
  assert.equal(closure.ackStateText(byItem.quality), "확인됨");
  assert.equal(closure.canAck(byItem.quality), false);
  assert.equal(closure.canRevoke(byItem.quality), true);
  assert.equal(closure.ackStateText(byItem.issues_untried), "확인 취소됨 — 막습니다");
  assert.equal(closure.canAck(byItem.issues_untried), true);
  assert.equal(closure.canRevoke(byItem.issues_untried), false);
  assert.equal(closure.ackStateText(byItem.skipped), "확인 전 — 막습니다");
  assert.equal(closure.ackStateText(byItem.mech_not_run), "표기만(확인 필요 없음)");
  assert.equal(closure.canAck(byItem.mech_not_run), false);
  const stale = { blocking: true, acked: false, ack: { state: "stale", by: "a", at: 1, reason: "r" } };
  assert.match(closure.ackStateText(stale), /^확인 낡음/);
  assert.equal(closure.canAck(stale), true);
  assert.equal(closure.canRevoke(stale), true);
  assert.deepEqual(closure.residualCounts(samples.closureCells.qualifiers), { blocking: 3, unacked: 2, marks: 4 });
  assert.match(closure.ackReasonProblem(""), /사유가 필요합니다/);
  assert.equal(closure.ackReasonProblem("a"), null);
});

test("내려간 계산 · 영역 깊이 — 저장 레벨은 내려가지 않는다, 카드 없는 영역은 모자람에서 뺀다", () => {
  assert.equal(closure.regressedNote(samples.closureCells), "지금 계산 C1 — 저장 레벨은 내려가지 않는다.");
  assert.equal(closure.regressedNote({ regressed: false, level_current: "C2" }), null);
  const rows = closure.depthRows(samples.closureCells.detail.depth);
  assert.deepEqual(rows.map((r) => [r.domain, r.short]), [["mech", false], ["sim", false], ["xd", true]]);
  assert.equal(rows.find((r) => r.domain === "sim").exempt, "no_cards");
});

// ── 7절 — 등록부 ─────────────────────────────────────────────────────────────

test("등록부 — 쟁점 패널이 덮은 행은 '원래 — 제기 N명(분포) → 쟁점 패널 결과', 덮지 않은 행은 줄이 없다", () => {
  const [covered, plain] = samples.registryAB.rows;
  assert.equal(issues.registryOverlayLine(covered), "원래 — 제기 3명(FAIL 3) → 쟁점 패널 상향");
  assert.equal(issues.registryOverlayLine(plain), null);
  // 기각은 행을 덮지 않는다(before_issue 없음) — 지금 분포로 센다.
  const rejected = { ...plain, issue_state: "rejected", support_experts: 2, merged: { ...plain.merged, distribution: { by_judgement_claimed: { FAIL: 2 }, by_severity: {}, raisers_by_domain: {} } } };
  assert.equal(issues.registryOverlayLine(rejected), "원래 — 제기 2명(FAIL 2) → 쟁점 패널 기각");
  assert.equal(issues.registryOverlayLine({ ...plain, issue_state: "queued" }), null);
  // 덮은 행의 제기 수는 덮기 전 값이다 — 지금 행의 지지 수(쟁점 패널 원자를 뺀 다시 셈)와 다를 수 있다.
  assert.match(issues.registryOverlayLine({ ...covered, support_experts: 9 }), /^원래 — 제기 3명/);
  const cell = renderToStaticMarkup(h(IssueCell, { row: covered }));
  assert.match(cell, /escalated/);
  assert.match(cell, /원래 — 제기 3명\(FAIL 3\) → 쟁점 패널 상향/);
  const reraised = { ...covered, merged: { ...covered.merged, issue_reraised: { label: "패널 판정 — 근거 바뀜, 다시 토의 필요" } } };
  assert.match(renderToStaticMarkup(h(IssueCell, { row: reraised })), /<strong[^>]*>패널 판정 — 근거 바뀜, 다시 토의 필요<\/strong>/);
});

test("등록부 행의 영역 — 행에 domain 칸이 없다, 대표의 소유 영역이 먼저이고 제기 원자들의 영역이 뒤", () => {
  assert.deepEqual(rowDomains({ merged: { owner_domain: "xd", domains: ["mech", "xd"] } }), ["xd", "mech"]);
  assert.deepEqual(rowDomains({ merged: { domains: ["mech"] } }), ["mech"]);
  assert.deepEqual(rowDomains({ merged: {} }), []);
  assert.equal(supportText({ support_experts: 3, support_domains: null, support_units: 1, support_verified: 0 }), "전문가 3 · 영역 ? · 단위 1 · 검증 0");
});

test("등록부 행 펼침 — 주장 · 근거는 merged 에서(행 칸이 아니다 — 전에 cites.length 에서 백지), 덮기 전 값", () => {
  const [covered, plain] = samples.registryAB.rows;
  const html = renderToStaticMarkup(h(RegistryRowDetail, { row: covered }));
  assert.ok(html.includes(covered.merged.claim));
  assert.ok(html.includes(covered.merged.cites[0].ref));
  assert.match(html, /쟁점 패널이 덮기 전/);
  assert.match(html, /전문가 3 · 영역 2 · 단위 1 · 검증 3/);
  // merged 가 빈 옛 행 · 패널만 본 비교 보기의 행도 그린다(칸이 없으면 '없다' 고 말한다).
  const bare = renderToStaticMarkup(h(RegistryRowDetail, { row: { ...plain, merged: {}, support_experts: null } }));
  assert.match(bare, /주장 글이 없습니다/);
  assert.match(bare, /근거 참조가 없습니다/);
  assert.match(bare, /전문가 \? · 영역/);
});
