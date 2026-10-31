// 배지 · 박스 까닭을 서버 꼴의 값으로 그려 보는 시험 — 객체를 React 자식으로 그려 화면이 백지가 되던 것(React #31)을 다시 막는다.
const test = require("node:test");
const assert = require("node:assert/strict");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load.cjs");

const { ExternalSyncBadge, LlmBadge } = load("components/Badge.js");
const { BoxReasons } = load("components/BoxReasons.js");

/** 서버 ra_client.sync_summary 의 꼴 그대로. */
const SUMMARY = {
  ra: { state: "pending", pending_ops: 2, reason: "sender_unwired", message: "RA 반영 안 됨 — 보내는 쪽이 아직 배선되지 않았다(M4). 대기 2건, 보낸 것 없음." },
  adh: { state: "done", pending_ops: 0, reason: "sender_unwired", message: "AIDataHub 반영 안 됨 — 대기 0건." },
};
/** 서버 ra_client.resync 의 꼴 그대로(채널마다 op 목록). */
const RESYNC = {
  ra: { state: "pending", attempts: 0, next_at: 0, last_error: null, done_at: null, pending_ops: [{ op: "x" }] },
  adh: { state: "unavailable", attempts: 3, next_at: 0, last_error: "no key", done_at: null, pending_ops: [] },
};

test("반영 배지는 요약 · 재동기 응답 둘 다 상태 글자로 그린다(객체를 자식으로 그리지 않는다)", () => {
  const a = renderToStaticMarkup(React.createElement(ExternalSyncBadge, { sync: SUMMARY }));
  assert.match(a, /RA pending/);
  assert.match(a, /ADH done/);
  assert.match(a, /보내는 쪽이 아직 배선되지 않았다/); // message 는 title 로 실린다
  const b = renderToStaticMarkup(React.createElement(ExternalSyncBadge, { sync: RESYNC }));
  assert.match(b, /ADH unavailable/);
  assert.match(b, /title="no key"/);
  assert.equal(renderToStaticMarkup(React.createElement(ExternalSyncBadge, { sync: null })), "");
});

test("판단 LLM 배지 — claude 만 'Claude', 칸이 없으면 GLM", () => {
  assert.match(renderToStaticMarkup(React.createElement(LlmBadge, { llm: "claude" })), />Claude</);
  assert.match(renderToStaticMarkup(React.createElement(LlmBadge, {})), />GLM</);
});

test("박스 까닭 — 막는 것은 alert, 선택 키 없음은 status, fix 의 백틱 명령만 코드로, 글은 HTML 로 풀지 않는다", () => {
  const reasons = [
    { code: "missing_required", keys: ["HWAXRISK_CRED_KEY"], message: "자격 암호화 키가 없다 <b>x</b>", fix: "이 한 줄을 실행한다 `hwax-risk cred-key --new`. 보관한다." },
    { code: "missing_optional", keys: ["HWAXRISK_BACKUP_KEY"], message: "없는 선택 키", fix: "필요한 길만 켠다." },
  ];
  const all = renderToStaticMarkup(React.createElement(BoxReasons, { reasons }));
  assert.match(all, /role="alert"[^>]*>.*자격 암호화 키가 없다 &lt;b&gt;x&lt;\/b&gt;/);
  assert.match(all, /<code[^>]*>hwax-risk cred-key --new<\/code>/);
  assert.match(all, /role="status"[^>]*>.*없는 선택 키/);
  const blocking = renderToStaticMarkup(React.createElement(BoxReasons, { reasons, only: "blocking" }));
  assert.doesNotMatch(blocking, /없는 선택 키/);
  // 익명에게는 code 만 온다 — 짧은 말로 보인다.
  const anon = renderToStaticMarkup(React.createElement(BoxReasons, { reasons: [{ code: "host_mismatch" }] }));
  assert.match(anon, /옮겨 온 뒤 첫 기동/);
});
