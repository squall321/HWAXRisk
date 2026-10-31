// 과제 이력 탭을 서버 꼴의 감사 행 한 쪽으로 그려 보는 시험 — 사람 조작 감사 다섯의 이름표와 전 → 후 칸(코드 어휘 그대로)이 실제 표에 선다
const test = require("node:test");
const assert = require("node:assert/strict");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load.cjs");

// 탭이 읽는 쪽(useAsync)을 서버 답 한 쪽으로 바꿔 끼운다 — 컴파일 산출물은 부를 때마다 모듈 객체에서 그 함수를 찾는다
// (`(0, useAsync_1.useAsync)(…)`). node --test 는 시험 파일마다 프로세스를 따로 띄우므로 다른 화면 시험에 번지지 않는다.
const hooks = load("hooks/useAsync.js");
const { ProjectAuditCard } = load("components/ProjectAuditCard.js");

/** GET /projects/{id}/audit 의 한 줄(routes.get_project_audit — before · after 는 풀린 객체). */
const row = (action, before, after, extra = {}) => ({
  id: `${action}-1`, actor: "a@x", actor_verified: true, channel: "web", scope: "job", subject_id: "j1", project_id: "p1",
  action, before, after, reason: null, at: 1761800000, ...extra,
});

function renderPage(entries) {
  const real = hooks.useAsync;
  hooks.useAsync = () => ({
    data: { project_id: "p1", total: entries.length, limit: 50, offset: 0, entries }, loading: false, error: null, reload() {},
  });
  try {
    return renderToStaticMarkup(React.createElement(ProjectAuditCard, { projectId: "p1", active: true }));
  } finally {
    hooks.useAsync = real;
  }
}

test("이력 탭 표 — 사람 조작 감사 행은 이름표가 붙고 전 → 후 칸이 코드 어휘 그대로다(미확인 배지는 행을 쓴 길마다 풀이)", () => {
  const html = renderPage([
    row("job.pause", { hold_code: "llm_outage", state: "paused" }, { hold_code: "user", state: "paused" },
      { channel: "mcp", actor_verified: false }),
    row("registry.status", { status: "open" }, { status: "verified", status_log_seq: 2 },
      { scope: "registry", subject_id: "diff:d1#k1" }),
    row("verdict.final", { verdict_final: null }, { verdict_final: "no-go" }, { scope: "target", subject_id: "diff:d1" }),
    row("member.put", { members: [] }, { members: ["b@x"] }, { scope: "project", subject_id: "p1" }),
    // 포털 화면의 '멈춤'(A24) — 에이전트 서버가 알린 사람 · web · 미확인, RA 거두기의 모르는 행위자 — system · rest · 미확인
    row("job.pause", { hold_code: null, state: "running" }, { hold_code: null, state: "paused" }, { actor_verified: false }),
    row("ra.retract", null, { form: "retracted" }, { actor: "system", channel: "rest", actor_verified: false, scope: "project" }),
  ]);
  assert.match(html, /<code>job\.pause<\/code><span class="text-muted-foreground"> (<!-- -->)?잡 일시정지<\/span>/);
  assert.match(html, /<code class="text-xs">paused · 보류 llm_outage → paused · 보류 user<\/code>/);
  assert.match(html, /<code class="text-xs">open → verified · 상태 기록 #2<\/code>/);
  assert.match(html, /<code class="text-xs">없음 → no-go<\/code>/);
  // 그 밖의 행위의 전 → 후는 종전대로 JSON(따옴표는 HTML 로 옮겨진다)
  assert.match(html, /<code class="text-xs">\{&quot;members&quot;:\[\]\} → \{&quot;members&quot;:\[&quot;b@x&quot;\]\}<\/code>/);
  assert.equal((html.match(/>미확인</g) ?? []).length, 3);
  // 배지 풀이는 행을 쓴 길마다 — MCP 위임 · 포털 '멈춤' · 모르는 뒤처리(옛 '자칭' 풀이는 없다)
  assert.match(html, /title="Claude\(MCP\) 길 — 게이트웨이가 위임으로 넘긴 신원입니다\.[^"]*"[^>]*>미확인</);
  assert.match(html, /title="포털 화면의 &#x27;멈춤&#x27;으로 멈춘 잡 — 에이전트 서버가 알린[^"]*"[^>]*>미확인</);
  assert.match(html, /title="누가 했는지 모르는 뒤처리입니다[^"]*"[^>]*>미확인</);
  assert.doesNotMatch(html, /자칭/);
});
