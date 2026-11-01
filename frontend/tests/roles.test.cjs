// 역할로 가르는 쓰기 단추 — 보기 · 편집자 · 소유자로 그려 잠김 · 까닭 한 줄을 본다(OI-2 — 서버 my_role · /me.risk_admin)
const test = require("node:test");
const assert = require("node:assert/strict");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const { MemoryRouter } = require("react-router-dom");
const load = require("./load.cjs");

const access = load("lib/access.js");
const samples = load("contract/serverSamples.js");
const { GateTable } = load("components/GateBanner.js");
const { ReviewBoard } = load("components/ReviewBoard.js");
const { CellsHead } = load("components/CellsHead.js");
const { RegistryCard } = load("components/RegistryCard.js");
const { HumanFindingForm } = load("components/HumanFindingForm.js");
const { UndeferForm } = load("components/UndeferForm.js");
const { ReviewJobFormCard } = load("components/ReviewJobForm.js");
const { ClosureCard } = load("components/ClosureCard.js");
const { SynthReport } = load("components/SynthReport.js");
const { CellGrid } = load("components/CellGrid.js");
const { IssuesCard } = load("components/IssuesCard.js");
const { SameAsResolver } = load("components/SameAsResolver.js");
const { ProjectMetaCard } = load("components/ProjectMetaCard.js");

const h = React.createElement;
const clone = (v) => JSON.parse(JSON.stringify(v));
const routed = (el) => renderToStaticMarkup(h(MemoryRouter, null, el));
const noop = () => {};
const VIEWER = access.VIEWER_REASON;
const ROLES = ["viewer", "editor", "owner"];

/** 글자가 `label` 로 끝나는 첫 단추의 여는 꼬리표 — 속성 차례에 매이지 않게 `>label</button>` 에서 거슬러 올라간다(아이콘 뒤 글자도). */
function buttonTag(html, label) {
  const at = html.indexOf(`>${label}</button>`);
  assert.notEqual(at, -1, `단추 글자를 못 찾았다 — ${label}`);
  const open = html.lastIndexOf("<button", at);
  assert.notEqual(open, -1, `단추가 아니다 — ${label}`);
  return html.slice(open, html.indexOf(">", open) + 1);
}
const disabled = (tag) => /\sdisabled=""/.test(tag);
const noted = (html, reason) => html.includes('role="note"') && html.includes(reason);

test("역할 판정 — 보기는 편집자 쓰기를, 소유자가 아니면 주인 쓰기를 잠그고 까닭을 말한다 · 모르면 잠그지 않는다", () => {
  assert.deepEqual(access.writeAccess("viewer"), { allowed: false, reason: VIEWER });
  assert.deepEqual(access.writeAccess("editor"), { allowed: true, reason: null });
  assert.deepEqual(access.writeAccess("owner"), { allowed: true, reason: null });
  assert.deepEqual(access.writeAccess("editor", "owner"), { allowed: false, reason: "과제 소유자만 할 수 있습니다(지금 편집자)." });
  assert.deepEqual(access.writeAccess("viewer", "owner"), { allowed: false, reason: "과제 소유자만 할 수 있습니다(지금 보기)." });
  assert.deepEqual(access.writeAccess("owner", "owner"), { allowed: true, reason: null });
  for (const unknown of [null, undefined]) {
    assert.deepEqual(access.writeAccess(unknown), { allowed: true, reason: null }); // 서버가 가른다(구성원이 아닌 관리자 포함)
    assert.deepEqual(access.writeAccess(unknown, "owner"), { allowed: true, reason: null });
  }
  assert.deepEqual(access.adminAccess(false), { allowed: false, reason: access.ADMIN_REASON });
  assert.deepEqual(access.adminAccess(true), { allowed: true, reason: null });
  assert.deepEqual(access.adminAccess(undefined), { allowed: true, reason: null });
  assert.equal(access.weakerRole("owner", "viewer"), "viewer"); // 두 과제에 걸친 쓰기는 약한 쪽으로
  assert.equal(access.weakerRole("owner", "editor"), "editor");
  assert.equal(access.weakerRole("owner", null), "owner");
  assert.equal(access.weakerRole(null, undefined), null);
  assert.equal(access.lowerClassificationLock("editor", "internal", "confidential"), "과제 소유자만 할 수 있습니다(지금 편집자).");
  assert.equal(access.lowerClassificationLock("editor", "internal", undefined), "과제 소유자만 할 수 있습니다(지금 편집자)."); // 모름은 기밀로
  assert.equal(access.lowerClassificationLock("owner", "internal", "confidential"), null);
  assert.equal(access.lowerClassificationLock("editor", "confidential", "internal"), null); // 올리기는 편집자도
  assert.equal(access.lowerClassificationLock(null, "internal", "confidential"), null);
});

const FAILING = {
  G1: { key: "dup_or_anon_names", count: 2, threshold: 0, pass: false, reason: null, blocking: false, effect: "mark", ack_by: null,
        ack_at: null, ack_reason: null, detail: ["PLATE"] },
};

test("게이트 ack — 보기에게는 '사유 적고 진행' 이 잠기고 표 위에 까닭, 편집자 · 소유자에게는 열린다", () => {
  for (const role of ROLES) {
    const html = renderToStaticMarkup(h(GateTable, { gates: FAILING, snapshotId: "s1", role }));
    const tag = buttonTag(html, "사유 적고 진행(ack)");
    assert.equal(disabled(tag), role === "viewer", role);
    assert.equal(noted(html, VIEWER), role === "viewer", role);
  }
  // 이미 붙은 ack 의 '확인 취소' 도 같은 문이다.
  const acked = { G1: { ...FAILING.G1, ack_by: "a@x", ack_at: 1761800000, ack_reason: "임시" } };
  assert.equal(disabled(buttonTag(renderToStaticMarkup(h(GateTable, { gates: acked, snapshotId: "s1", role: "viewer" })), "확인 취소")), true);
  assert.equal(disabled(buttonTag(renderToStaticMarkup(h(GateTable, { gates: acked, snapshotId: "s1", role: "editor" })), "확인 취소")), false);
});

test("검토 잡 줄 — 보기에게는 일시정지 · 취소 · 넘기기가 잠기고 까닭, 편집자는 그대로", () => {
  const review = clone(samples.coveragePausedConsent.review);
  review.job.state = "running";
  review.job.hold_code = null;
  review.job.progress.reopened_extra.hold = null;
  for (const role of ROLES) {
    const html = renderToStaticMarkup(h(ReviewBoard, { review, targetKey: "t", onChanged: noop, role }));
    for (const label of ["일시정지", "취소…"]) assert.equal(disabled(buttonTag(html, label)), role === "viewer", `${role} ${label}`);
    assert.equal(noted(html, VIEWER), role === "viewer", role);
  }
  const paused = clone(samples.coveragePausedConsent.review); // consent_extra — 기다리는 셀 넘기기
  const viewer = renderToStaticMarkup(h(ReviewBoard, { review: paused, targetKey: "t", onChanged: noop, role: "viewer" }));
  assert.equal(disabled(buttonTag(viewer, "기다리는 셀 넘기기…")), true);
});

test("대상 머리 — 진행판 my_role 이 보기면 사슬 재개 · 사슬 시작이 잠기고 까닭, 편집자는 그대로", () => {
  const paused = clone(samples.coverageCells);
  paused.stage = { ...paused.stage, state: "paused", pause_reason: "user", error: "restart: 앱 재기동이 패널을 닫았다" };
  const m2 = clone(samples.coverageCells);
  m2.stage = null;
  m2.report = null;
  m2.review.job.state = "completed";
  m2.review.job.chain = false;
  m2.review.cells.by_state.pending = 0;
  for (const role of ROLES) {
    const p = routed(h(CellsHead, { coverage: { ...paused, my_role: role }, targetKey: "t", onChanged: noop, onOpenTab: noop }));
    assert.equal(disabled(buttonTag(p, "재개")), role === "viewer", role);
    assert.equal(noted(p, VIEWER), role === "viewer", role);
    const s = routed(h(CellsHead, { coverage: { ...m2, my_role: role }, targetKey: "t", onChanged: noop, onOpenTab: noop }));
    assert.equal(disabled(buttonTag(s, "쟁점 · 종합 시작")), role === "viewer", role);
  }
});

test("등록부 — 보기에게는 판정 확정 · 사람 리스크 등록이 잠기고 까닭, 편집자 · 소유자는 그대로", () => {
  const registry = { data: samples.registryAB, loading: false, error: null, reload: noop };
  for (const role of ROLES) {
    const html = routed(h(RegistryCard, { targetKey: "t", registry, query: {}, onQuery: noop, cells: true, role }));
    assert.equal(disabled(buttonTag(html, "리스크 직접 등록")), role === "viewer", role);
    const verdict = html.slice(html.lastIndexOf("판정 확정"));
    assert.equal(disabled(buttonTag(verdict, "확정")), role === "viewer", role);
    assert.equal(noted(html, VIEWER), role === "viewer", role);
  }
  const alone = renderToStaticMarkup(h(HumanFindingForm, { targetKey: "t", mechanisms: [], onCreated: noop, role: "viewer" }));
  assert.equal(disabled(buttonTag(alone, "리스크 직접 등록")), true);
  assert.ok(noted(alone, VIEWER));
});

test("보류 풀기 · 검토 잡 만들기 — 보기에게 잠기고 까닭, 편집자는 그대로", () => {
  for (const role of ROLES) {
    const undefer = renderToStaticMarkup(h(UndeferForm, { targetKey: "t", deferred: 3, onChanged: noop, role }));
    assert.equal(disabled(buttonTag(undefer, "보류 풀기…")), role === "viewer", role);
    assert.equal(noted(undefer, VIEWER), role === "viewer", role);
    const review = clone(samples.coverageCells.review);
    review.job.state = "completed";
    const form = renderToStaticMarkup(h(ReviewJobFormCard, { targetKey: "t", review, onChanged: noop, role }));
    assert.equal(disabled(buttonTag(form, "검토 잡 시작")), role === "viewer", role);
    assert.equal(noted(form, VIEWER), role === "viewer", role);
  }
});

test("완결 잔여 확인은 소유자만 — 편집자 · 보기에게 까닭(지금 역할), 소유자 · 모름에게는 없다", () => {
  const card = (role) => routed(h(ClosureCard, { targetKey: "t", active: false, onChanged: noop, onOpenReport: noop, role }));
  assert.ok(noted(card("editor"), "과제 소유자만 할 수 있습니다(지금 편집자)."));
  assert.ok(noted(card("viewer"), "과제 소유자만 할 수 있습니다(지금 보기)."));
  assert.doesNotMatch(card("owner"), /role="note"/);
  assert.doesNotMatch(card(null), /role="note"/);
});

test("보고서 다시 내기 · 셀 처분 · 쟁점 결정 · 대응 결정 — 보기에게 까닭, 편집자 · 소유자에게는 없다", () => {
  const review = clone(samples.coverageCells.review);
  for (const role of ROLES) {
    const synth = routed(h(SynthReport, { targetKey: "t", stage: null, onChanged: noop, role }));
    assert.equal(disabled(buttonTag(synth, "다시 내기")), role === "viewer", role);
    assert.equal(disabled(buttonTag(synth, "요약부터 다시")), role === "viewer", role);
    const grid = routed(h(CellGrid, { targetKey: "t", review, active: false, onChanged: noop, role }));
    assert.equal(noted(grid, VIEWER), role === "viewer", role);
    const issues = routed(h(IssuesCard, { targetKey: "t", active: false, onChanged: noop, role }));
    assert.equal(noted(issues, VIEWER), role === "viewer", role);
    const sameas = routed(h(SameAsResolver, { base: "", target: "", role }));
    assert.equal(noted(sameas, VIEWER), role === "viewer", role);
  }
});

test("과제 메타 — 보기에게 카드 머리에 까닭(바꾸기 칸은 잠김), 편집자 · 소유자에게는 없다", () => {
  const detail = samples.projectDetailMember;
  for (const role of ROLES) {
    const html = renderToStaticMarkup(h(ProjectMetaCard, { detail, role, onPatched: noop }));
    assert.equal(noted(html, VIEWER), role === "viewer", role);
  }
  assert.equal(samples.projectDetailMember.my_role, "editor"); // 서버가 싣는 칸(실 백엔드 견본)
  assert.equal(samples.coverageCells.my_role, "owner");
});
