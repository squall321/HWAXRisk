// 화면 조각을 서버 꼴의 값으로 그려 보는 시험 — 판정 불가 게이트 · ack 단추 · 조직 공개 잠금 · ECAD 카드 갈래 · 마지막 신호 강조
const test = require("node:test");
const assert = require("node:assert/strict");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load.cjs");

const { GateTable, GateBanner } = load("components/GateBanner.js");
const { ProjectMetaCard } = load("components/ProjectMetaCard.js");
const { ProjectMembersCard } = load("components/ProjectMembersCard.js");
const { MemoryRouter } = require("react-router-dom");
const { EcadBoardCard, CandidateTable } = load("components/EcadBoardCard.js");
const { JobSignalLine, ReviewWorkers } = load("components/JobSignals.js");
const { ACTION_LABEL, ProjectAuditCard, auditChange, unverifiedTitle } = load("components/ProjectAuditCard.js");

const h = React.createElement;
const count = (html, re) => (html.match(new RegExp(re, "g")) ?? []).length;

const gate = (key, pass, extra = {}) => ({
  key, count: pass === null ? null : pass ? 0 : 1, threshold: 0, pass, reason: null, blocking: false, effect: "mark",
  ack_by: null, ack_at: null, ack_reason: null, detail: [], ...extra,
});

/** mcp_degraded 스냅샷의 게이트 꼴(state.compute_gates) — G3 · G4 는 입력이 없어 null, G6 은 단위를 몰라 차단. */
const MCP_DEGRADED = {
  G1: gate("dup_or_anon_names", false, { count: 2, detail: ["PLATE"] }),
  G2: gate("sameas_pending", true),
  G3: gate("iface_unconfirmed", null, { reason: "capture_partial" }),
  G4: gate("coordinate", null, { reason: "warnings_unavailable" }),
  G5: gate("partial_scope", true),
  G6: gate("unit_scale", false, { reason: "unit_unknown", blocking: true, effect: "block" }),
};

test("mcp_degraded 의 G3 · G4 는 '판정 불가' 로 보이고 fail 로 세지 않는다", () => {
  const table = renderToStaticMarkup(h(GateTable, { gates: MCP_DEGRADED, snapshotId: "s1" }));
  assert.match(table, /판정 불가\(capture_partial\)/);
  assert.match(table, /판정 불가\(warnings_unavailable\)/);
  const banner = renderToStaticMarkup(h(GateBanner, { gates: MCP_DEGRADED }));
  assert.match(banner, /게이트 G1 · G6 fail\./); // fail 배너에는 G1 · G6 만
  assert.doesNotMatch(banner, /G3 · G4 fail|G3[^<]*fail\./);
  assert.match(banner, /판정 불가 G3 · G4 — fail 이 아닙니다\./);
});

test("ack 단추는 fail 이고 차단이 아닌 게이트에만 — G6 은 다시 캡처 안내, 판정 불가 · pass 에는 없다", () => {
  const table = renderToStaticMarkup(h(GateTable, { gates: MCP_DEGRADED, snapshotId: "s1" }));
  assert.equal(count(table, "사유 적고 진행\\(ack\\)"), 1); // G1 하나
  assert.match(table, /REST 원문으로 다시 캡처해야 풀립니다\./);
  // 비교 화면(스냅샷 id 없음)은 붙이기 단추를 두지 않는다.
  const readOnly = renderToStaticMarkup(h(GateTable, { gates: MCP_DEGRADED }));
  assert.equal(count(readOnly, "사유 적고 진행"), 0);
  // 서버가 ack 를 실어 주면 누가 · 사유와 취소 단추를 보인다(사유는 글자 그대로).
  const acked = { ...MCP_DEGRADED, G1: { ...MCP_DEGRADED.G1, ack_by: "a@x", ack_at: 1761800000, ack_reason: "<b>임시</b>" } };
  const html = renderToStaticMarkup(h(GateTable, { gates: acked, snapshotId: "s1" }));
  assert.match(html, /a@x/);
  assert.match(html, /&lt;b&gt;임시&lt;\/b&gt;/);
  assert.match(html, /확인 취소/);
  assert.match(html, /fail\(2\) · ack/);
});

/** 9bd5f48 의 과제 상세 꼴 — 과제 행에 메타 칸이 없다. */
const DETAIL = (project = {}) => ({
  project: {
    id: "p1", owner_sub: "owner@x", code: "DEMO-1", name: "시연", stage: null, predecessor_project_id: null, adh_team: null,
    adh_group: null, character_status: null, created_at: 0, updated_at: 0, ...project,
  },
  sources: [], snapshots: [], jobs: [], character_top_tags: [],
  targets: [{ key: "t1", external_sync: { ra: { state: "withheld", pending_ops: 3 } } }],
});

test("조직 공개 토글 — 편집자에게는 잠기고(단추 없음) 소유자에게는 단추가 있다", () => {
  const editor = renderToStaticMarkup(h(ProjectMetaCard, { detail: DETAIL({ mcp_visibility: "private" }), role: "editor", onPatched() {} }));
  assert.match(editor, /조직 공개는 과제 소유자만 바꿉니다\(지금 편집자\)\./);
  assert.doesNotMatch(editor, />조직에 공개</);
  assert.doesNotMatch(editor, />비공개로</);
  const owner = renderToStaticMarkup(h(ProjectMetaCard, { detail: DETAIL({ mcp_visibility: "private" }), role: "owner", onPatched() {} }));
  assert.match(owner, />조직에 공개</);
  assert.match(owner, /보류 op 3건/);
  assert.doesNotMatch(owner, /소유자만 바꿉니다\(지금/);
});

test("고르기만으로 쓰지 않는다 — 등급 · 수명 주기는 고른 뒤 '바꾸기'(처음엔 잠김), 멤버는 '빼기…'(확인) · 역할은 고른 뒤 '적용'", () => {
  const owner = renderToStaticMarkup(h(ProjectMetaCard, { detail: DETAIL({ classification: "confidential", lifecycle: "active" }), role: "owner", onPatched() {} }));
  assert.equal(count(owner, '<button[^>]*disabled=""[^>]*>바꾸기</button>'), 2);
  assert.match(owner, /<option value="" selected="">바꿀 등급…<\/option>/);
  const members = {
    data: { project_id: "p1", members: [{ email: "owner@x", role: "owner", added_by: null, added_at: 1 }, { email: "ed@x", role: "editor", added_by: "owner@x", added_at: 2 }] },
    loading: false, error: null, reload() {},
  };
  const card = renderToStaticMarkup(h(MemoryRouter, null, h(ProjectMembersCard, { projectId: "p1", projectCode: "C", isOwner: true, members })));
  assert.match(card, /빼기…<\/button>/);
  assert.doesNotMatch(card, />적용</); // 역할을 고르기 전에는 적용 단추가 없다
  assert.doesNotMatch(card, /을 멤버에서 뺍니다/);
});

test("과제 메타 — 서버가 칸을 주지 않으면 '모름', 제품 연결이 비었다고 말하면 '제품 연결 없음' 배지", () => {
  const bare = renderToStaticMarkup(h(ProjectMetaCard, { detail: DETAIL(), role: null, onPatched() {} }));
  assert.ok(count(bare, "모름\\(이 서버가 과제 상세에 싣지 않음\\)") >= 4);
  assert.doesNotMatch(bare, /제품 연결 없음/);
  const none = renderToStaticMarkup(h(ProjectMetaCard, {
    detail: DETAIL({ product_refs_json: "[]", product_code: null }), role: "owner", onPatched() {},
  }));
  assert.match(none, />제품 연결 없음</);
  const linked = renderToStaticMarkup(h(ProjectMetaCard, {
    detail: DETAIL({ product_refs_json: '[{"kind":"ra_model","value":"<i>M-1</i>"}]', product_code: null }), role: "owner", onPatched() {},
  }));
  assert.doesNotMatch(linked, /제품 연결 없음/);
  assert.match(linked, /&lt;i&gt;M-1&lt;\/i&gt;/); // 서버 글은 글자로
});

const ADAPTER = (status, extra = {}) => ({
  kind: "ecad", app_key: "odb-hub", status, tools_ok: status === "ready", tools_missing: [], gateway_error: null, warnings: [],
  choices: [], ...extra,
});
const CARD = (props) => h(EcadBoardCard, {
  projectId: "p1", source: null, adapters: [ADAPTER("ready")], adaptersLoading: false, isOwner: true, onAdaptersRetry() {},
  onChanged() {}, ...props,
});

test("ECAD 카드 — 도구가 없으면 운영자 몫 배너(빠진 도구), 지도를 못 읽으면 '다시 읽기', 둘 다 찾기 칸을 열지 않는다", () => {
  const off = renderToStaticMarkup(CARD({ adapters: [ADAPTER("unavailable", { tools_missing: ["find_job", "get_job"] })] }));
  assert.match(off, /ODB 허브 도구가 게이트웨이에 없습니다 — 운영자 몫입니다\./);
  assert.match(off, /빠진 도구 find_job · get_job/);
  assert.doesNotMatch(off, /ECAD 보드 찾을 말/);
  const planned = renderToStaticMarkup(CARD({ adapters: [ADAPTER("planned", { gateway_error: "timeout" })] }));
  assert.match(planned, /게이트웨이 도구 지도를 못 읽었습니다/);
  assert.match(planned, />다시 읽기</);
  assert.doesNotMatch(planned, /ECAD 보드 찾을 말/);
});

test("ECAD 카드 — 찾기 · 바꾸기 · 떼기는 과제 주인에게만, 보드 정체는 서버 글자 그대로", () => {
  assert.match(renderToStaticMarkup(CARD({})), /aria-label="ECAD 보드 찾을 말"/);
  assert.doesNotMatch(renderToStaticMarkup(CARD({ isOwner: false })), /ECAD 보드 찾을 말/);
  const source = {
    id: "src-e", kind: "ecad", app_key: "odb-hub", ref: { odb_job_id: "61f311d47203781d" }, bridge_declared: false,
    probe_at: 1761800000, status: "ok",
    probe: { reachable: true, detail: "find_job ok", board: {
      job_id: "61f311d47203781d", name: "PRJ / M / <b>Main</b> / 0.7", project: "PRJ", model: "M", board_type: "Main",
      revision: "0.7", original_filename: "M_0.7.tgz", uploaded_at: "2026-10-29T02:11:40+00:00",
    } },
  };
  const owner = renderToStaticMarkup(CARD({ source }));
  assert.match(owner, /PRJ \/ M \/ &lt;b&gt;Main&lt;\/b&gt; \/ 0\.7/);
  assert.match(owner, /61f311d47203781d/);
  assert.match(owner, />바꾸기</);
  assert.match(owner, />떼기</);
  assert.doesNotMatch(owner, /ECAD 보드 찾을 말/); // 붙은 보드가 있으면 '바꾸기' 를 눌러야 찾기 칸이 열린다
  const viewer = renderToStaticMarkup(CARD({ source, isOwner: false }));
  assert.match(viewer, /61f311d47203781d/);
  assert.doesNotMatch(viewer, />떼기</);
  assert.doesNotMatch(viewer, />바꾸기</);
});

test("후보 표 — 판 · 올린 시각이 앞 열, 미리 고른 행 없음, 붙은 보드는 배지, 16자리 16진이 아닌 job_id 는 잠금", () => {
  const row = (rev, job) => ({
    job_id: job, name: `PRJ / M / Main / ${rev}`, project: "PRJ", model: "M", board_type: "Main", revision: rev,
    original_filename: `M_${rev}.tgz`, uploaded_at: "2026-10-29T02:11:40+00:00",
  });
  const html = renderToStaticMarkup(h(CandidateTable, {
    candidates: [row("0.7", "61f311d47203781d"), row("0.8", "079eb91bd2974d87"), row("0.9", "not-a-job-id")],
    currentJobId: "61f311d47203781d", busy: false, onPick() {},
  }));
  const headers = [...html.matchAll(/<th[^>]*>(.*?)<\/th>/g)].map((m) => m[1].replace(/<[^>]+>/g, ""));
  assert.match(headers[0], /^판/);
  assert.match(headers[1], /^올린 시각/);
  assert.equal(count(html, ">붙은 보드<"), 1);
  assert.equal(count(html, ">이 보드<"), 2); // 미리 고른 행 없음 — 붙은 보드 밖의 두 행 모두 단추
  assert.match(html, /disabled=""[^>]*title="job_id 가 16자리 16진이 아니라 붙일 수 없습니다\."/);
  assert.doesNotMatch(html, /checked|aria-selected="true"/);
});

const SIGNAL = (idle) => ({
  panel_id: "pn-1", panel_no: 4, started_at: 0, last_frame_at: 1, last_event_at: 1, last_step: "2라운드", frames: 9,
  frame_idle_s: idle, event_idle_s: idle,
});
const JOB = (signal) => ({
  id: "j1", tier: "B", state: "running", pause_reason: null, panels_done: 1, panels_total: 3, error: null, signal,
});

test("도는 패널과 멈춘 패널을 가른다 — 80초까지는 보통 글, 넘으면 경고 배지", () => {
  const running = renderToStaticMarkup(h(JobSignalLine, { job: JOB(SIGNAL(62)) }));
  assert.match(running, /<span>마지막 신호 62초 전<\/span>/);
  assert.doesNotMatch(running, /멈췄을 수 있다/);
  const stalled = renderToStaticMarkup(h(JobSignalLine, { job: JOB(SIGNAL(240)) }));
  assert.match(stalled, /title="80초를 넘겼다 — 패널이 멈췄을 수 있다"[^>]*>마지막 신호 240초 전/);
  assert.match(renderToStaticMarkup(h(JobSignalLine, { job: JOB(null) })), /지금 도는 패널이 없습니다/);
});

test("검토 잡 일꾼마다 마지막 신호 — 넘긴 일꾼만 강조한다", () => {
  const review = { job: { id: "rj", state: "running", signal: { workers: [
    { agent_key: "pcb-1", call_kind: "verdict", unit_id: "u1", last_frame_at: 1, last_event_at: 1, frame_idle_s: 30, event_idle_s: 30 },
    { agent_key: "mech-2", call_kind: "scan", unit_id: null, last_frame_at: 1, last_event_at: 1, frame_idle_s: 95, event_idle_s: 95 },
  ] } } };
  const html = renderToStaticMarkup(h(ReviewWorkers, { review }));
  assert.match(html, /pcb-1 · verdict · u1/);
  assert.match(html, /<span>마지막 신호 30초 전<\/span>/);
  assert.equal(count(html, "멈췄을 수 있다"), 1);
  assert.match(html, /mech-2 · scan/);
  assert.equal(renderToStaticMarkup(h(ReviewWorkers, { review: { job: null } })), "");
});

/** 사람 조작 감사 행의 앞 · 뒤 — 서버가 싣는 꼴 그대로(routes._job_control_view · put_registry_status · put_verdict, canonical_json 의 키 차례). */
const audit = (action, before, after) => ({ action, before, after });

test("이력 탭 — 사람 조작 감사 다섯(잡 제어 · 등록부 status · verdict 확정)에 이름표가 있고 종전 이름표는 그대로다", () => {
  assert.deepEqual(
    ["job.pause", "job.resume", "job.cancel", "registry.status", "verdict.final"].map((a) => ACTION_LABEL[a]),
    ["잡 일시정지", "잡 재개", "잡 취소", "등록부 상태 바꿈", "판정 확정"],
  );
  assert.equal(ACTION_LABEL["coverage.undefer"], "보류 풀기");
  assert.equal(ACTION_LABEL["job.create"], "잡 시작"); // 앱이 쓰는 행위는 전부 이름표가 있다(backend test_audit_action_labels)
  assert.equal(ACTION_LABEL["future.action"], undefined); // 모르는 행위는 이름표 없이 글자 그대로 보인다
  // 거름 선택지는 이름표 사전에서 선다 — 아직 읽지 않은 탭(active=false)도 다섯을 '말 코드' 꼴로 보인다.
  const html = renderToStaticMarkup(h(ProjectAuditCard, { projectId: "p1", active: false }));
  const five = [["job.pause", "잡 일시정지"], ["job.resume", "잡 재개"], ["job.cancel", "잡 취소"],
    ["registry.status", "등록부 상태 바꿈"], ["verdict.final", "판정 확정"]];
  for (const [code, label] of five) {
    assert.match(html, new RegExp(`<option value="${code.replace(".", "\\.")}">${label} ${code.replace(".", "\\.")}</option>`));
  }
});

test("이력 탭 전 → 후 — 다섯 행위는 코드 어휘를 글자 그대로 잇고, 그 밖과 꼴이 다른 값은 종전대로 JSON 이다", () => {
  const job = (state, hold = null) => ({ hold_code: hold, state });
  assert.equal(auditChange(audit("job.pause", job("queued"), job("paused"))), "queued → paused");
  assert.equal(auditChange(audit("job.resume", job("paused", "user"), job("queued"))), "paused · 보류 user → queued");
  // 코드 보류 위의 사람 정지 — 상태는 그대로 보류만 바뀐다(그래서 행이 선다)
  assert.equal(
    auditChange(audit("job.pause", job("paused", "llm_outage"), job("paused", "user"))),
    "paused · 보류 llm_outage → paused · 보류 user",
  );
  assert.equal(auditChange(audit("job.cancel", job("running"), job("cancelling"))), "running → cancelling");
  assert.equal(
    auditChange(audit("registry.status", { status: "open" }, { status: "mitigated", status_log_seq: 3 })),
    "open → mitigated · 상태 기록 #3",
  );
  assert.equal(auditChange(audit("verdict.final", { verdict_final: null }, { verdict_final: "go" })), "없음 → go");
  assert.equal(
    auditChange(audit("verdict.final", { verdict_final: "go" }, { verdict_final: "conditional" })),
    "go → conditional",
  );
  assert.equal(
    auditChange(audit("member.put", { members: [] }, { members: ["a@x"] })),
    '{"members":[]} → {"members":["a@x"]}',
  );
  assert.equal(auditChange(audit("job.pause", null, job("paused"))), '- → {"hold_code":null,"state":"paused"}');
  assert.equal(auditChange(audit("verdict.final", {}, { verdict_final: "go" })), '{} → {"verdict_final":"go"}');
});

test("이력 탭 '미확인' 풀이 — 행을 쓴 길마다 까닭이 다르다(MCP 위임 · 포털 '멈춤' · 모르는 뒤처리), 옛 '자칭' 풀이는 없다", () => {
  const mcp = unverifiedTitle({ channel: "mcp", action: "job.create", actor: "a@x" });
  const stop = unverifiedTitle({ channel: "web", action: "job.pause", actor: "a@x" });
  const system = unverifiedTitle({ channel: "rest", action: "ra.retract", actor: "system" });
  const other = unverifiedTitle({ channel: "rest", action: "gate.ack", actor: "a@x" });
  assert.match(mcp, /^Claude\(MCP\) 길 — 게이트웨이가 위임으로 넘긴 신원입니다\./);
  assert.match(stop, /^포털 화면의 '멈춤'으로 멈춘 잡 — 에이전트 서버가 알린/);
  assert.match(system, /누가 했는지 모르는 뒤처리입니다 — 사람으로 적지 않고 system 으로 적었습니다\./);
  assert.equal(other, "앱이 직접 확인한 신원이 아닙니다(입구 rest).");
  // 웹의 다른 행위는 포털 '멈춤' 이 아니다 — 그 풀이를 빌리지 않는다
  assert.equal(unverifiedTitle({ channel: "web", action: "job.cancel", actor: "a@x" }), "앱이 직접 확인한 신원이 아닙니다(입구 web).");
  // 포털 '멈춤' 풀이는 웹 행에만 — 다른 입구의 job.pause 미확인 행에 빌려 주지 않는다
  assert.equal(unverifiedTitle({ channel: "rest", action: "job.pause", actor: "a@x" }), "앱이 직접 확인한 신원이 아닙니다(입구 rest).");
  for (const text of [mcp, stop, system, other]) assert.doesNotMatch(text, /자칭|위임으로 확인되지 않은/);
});
