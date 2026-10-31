// 서버가 새로 싣는 칸을 화면이 그 이름 그대로 읽는가 — 과제 메타 · 홈 카드 · 게이트 ack · 대응표 pair_key · 키 대장 · 패널 신호(가지 wt1031/risk-reads 의 실 응답 견본)
const test = require("node:test");
const assert = require("node:assert/strict");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = require("./load.cjs");

const samples = load("contract/serverSamples.js");
const meta = load("lib/projectMeta.js");
const snap = load("lib/snapshotView.js");
const cmp = load("lib/compareView.js");
const { ProjectMetaCard } = load("components/ProjectMetaCard.js");
const { GateTable } = load("components/GateBanner.js");
const { JobSignalLine } = load("components/JobSignals.js");
const { KeyLedgerBody } = load("components/KeyLedgerPanel.js");

const h = React.createElement;
const NOT_SENT = "모름(이 서버가 과제 상세에 싣지 않음)";

test("과제 상세 — 구성원이 받은 실 응답의 메타 칸이 '모름' 없이 서고, 닫은 때는 과제를 다시 열어도 보인다", () => {
  const detail = samples.projectDetailMember;
  const known = meta.knownMeta(detail.project, null);
  assert.deepEqual(
    [known.classification, known.lifecycle, known.mcp_visibility, known.corpus_excluded, known.product_code],
    ["confidential", "shipped", "private", false, "SM-X100"],
  );
  assert.deepEqual(known.product_refs, [{ kind: "product_code", value: "SM-X100" }, { kind: "ra_model", value: "X100" }]);
  assert.equal(meta.noProductLink(known), false);
  const html = renderToStaticMarkup(h(ProjectMetaCard, { detail, role: "editor", onPatched() {} }));
  assert.equal(html.includes(NOT_SENT), false);
  assert.match(html, /닫은 때 /);
  // 멤버 표는 {email, role} 이고 소유자 행도 있다 — 내 역할을 이 표로도 셀 수 있다.
  assert.equal(meta.myRole(detail.members, "editor@example.com"), "editor");
});

test("과제 상세 — 다시 진행(active)으로 돌린 과제는 서버에 남은 지난 닫은 때를 보이지 않는다", () => {
  // 서버는 active 를 떠날 때만 closed_at 을 찍고 되돌아와도 지우지 않는다(열의 뜻 — active 를 떠난 시각). 실 응답 견본의 수명 주기만 바꿨다.
  const reopened = { ...samples.projectDetailMember, project: { ...samples.projectDetailMember.project, lifecycle: "active" } };
  assert.notEqual(reopened.project.closed_at, null);
  const html = renderToStaticMarkup(h(ProjectMetaCard, { detail: reopened, role: "editor", onPatched() {} }));
  assert.doesNotMatch(html, /닫은 때 /);
  assert.equal(html.includes(NOT_SENT), false);
});

test("홈 카드 — 실 응답이 네 칸을 다 실어 거름이 열리고, 내 역할로 거른다", () => {
  const cards = samples.projectCardsMember.projects;
  assert.deepEqual(meta.homeFieldsAvailable(cards), { lifecycle: true, role: true, excluded: true, classification: true });
  const editorOnly = meta.filterCards(cards, { lifecycle: "", role: "editor", includeExcluded: false });
  assert.deepEqual(editorOnly.map((c) => c.code), ["DEMO-7"]);
  assert.deepEqual(meta.filterCards(cards, { lifecycle: "shipped", role: "", includeExcluded: false }).map((c) => c.code), ["DEMO-7"]);
});

test("스냅샷 상태 — 서버가 얹은 ack 를 게이트 표가 그대로 보이고(다시 열어도), 판정 지문은 ack 답과 같다", () => {
  const state = samples.snapshotStateAcked;
  const html = renderToStaticMarkup(h(GateTable, { gates: state.gates, snapshotId: state.snapshot_id }));
  assert.match(html, /syn@example\.com/);
  assert.match(html, /계면 확인 뒤 진행/);
  assert.match(html, /fail\(1\) · ack/);
  assert.match(html, /확인 취소/);
  assert.doesNotMatch(html, /새로 열면 이 줄이 보이지 않습니다/);
  assert.match(state.gates_hash, /^[0-9a-f]{12}$/);
});

test("스냅샷 상태 — 요약 카드 · 신호 목록이 그대로 보이는 게이트 글도 게이트 표와 같은 ack 를 말한다", () => {
  // 화면은 summary_text 와 신호 글을 고치지 않고 보인다(요약 카드 · '단발 심사 열기' 복사) — 서버가 얹은 ack 를 그 글도 따라야 한다.
  const state = samples.snapshotStateAcked;
  const summary = state.signals["gates.summary"];
  const gateLine = state.summary_text.split("\n").find((line) => line.startsWith("[게이트] "));
  assert.equal(gateLine, `[게이트] ${summary.text}`);
  for (const [id, record] of Object.entries(state.gates)) {
    if (record.pass !== false) continue;
    const word = record.ack_by ? "ack 있음" : "ack 없음";
    assert.match(summary.text, new RegExp(`${id} fail\\(${record.count}, ${word}\\)`), id);
    assert.equal(summary.value[id].ack, Boolean(record.ack_by), id);
  }
  assert.match(gateLine, /G3 fail\(1, ack 있음\)/);
});

test("대응표 — 확정 본문은 서버가 준 pair_key 를 그대로 싣는다", () => {
  const table = samples.sameAsPairKey;
  const body = cmp.pairDecision({ a_stable: "mcad:/a", b_stable: "mcad:/b" }, "confirm", table.pair_key);
  assert.equal(body.pair_key, table.pair_key);
  assert.equal(body.scope, "pair");
});

test("키 대장 — 지금 상태 한 줄과, 병합된 키의 확정은 잠그고 되돌리기를 말한다", () => {
  const merged = samples.partKeyMerged;
  assert.equal(
    snap.partKeyLine(merged),
    `다른 키로 병합됨 · 대표 키 ${merged.merged_into} · 이름 없음 · 정한 사람 ${merged.decided_by}`,
  );
  const why = snap.confirmKeyBlocked(merged);
  assert.match(why, /병합돼 있어 확정할 수 없습니다/);
  assert.match(why, /병합 되돌리기/);
  const named = samples.partKeyNamed;
  assert.equal(snap.partKeyLine(named), `후보 — 아직 아무도 정하지 않았다 · 이름 «보호 필름» · 정한 사람 ${named.decided_by}`);
  assert.equal(snap.confirmKeyBlocked(named), null);
  assert.equal(snap.confirmKeyBlocked({ ...named, status: "confirmed" }), null);
  assert.equal(snap.confirmKeyBlocked(null), null); // 상태를 못 읽었으면 잠그지 않는다(서버의 409 로 말한다)
  assert.equal(snap.partKeyLine({ ...named, status: "odd", display_name: null, decided_by: null }), "odd · 이름 없음");
});

test("키 대장 — 결정 넷을 잠그는 것은 상태가 아니라 내 원장 행인가(mine)와 404 다", () => {
  // 보기 멤버가 받은 병합된 키는 주인의 원장 행이다 — 어느 결정이든 404 라 넷 다 잠근다. 같은 키를 주인이 받으면 확정만 잠근다.
  assert.equal(samples.partKeyMerged.mine, false);
  assert.match(snap.keyDecisionsBlocked(samples.partKeyMerged, false), /다른 사람.*원장입니다/);
  assert.equal(samples.partKeyMergedOwn.mine, true);
  assert.equal(snap.keyDecisionsBlocked(samples.partKeyMergedOwn, false), null);
  assert.match(snap.confirmKeyBlocked(samples.partKeyMergedOwn), /병합돼 있어 확정할 수 없습니다/);
  assert.equal(snap.keyDecisionsBlocked(samples.partKeyNamed, false), null);
  // 원장에 없는 키(404)도 결정을 받지 않는다. 못 읽은 것(그 밖의 실패)은 잠그지 않는다.
  assert.match(snap.keyDecisionsBlocked(null, true), /결정을 받지 않습니다\(404\)/);
  assert.equal(snap.keyDecisionsBlocked(null, false), null);
  // 남의 행이면 상태가 후보 · 확정이어도 잠근다(상태로 가르지 않는다).
  assert.notEqual(snap.keyDecisionsBlocked({ ...samples.partKeyNamed, mine: false }, false), null);
});

test("진행판 패널 잡 — signals 는 도는 패널마다 한 줄이고 지금은 signal 과 같다, 신호 줄은 그 값으로 그린다", () => {
  const job = samples.coverageJobRunning;
  assert.deepEqual(job.signals, [job.signal]);
  const html = renderToStaticMarkup(h(JobSignalLine, { job }));
  assert.match(html, /P1/);
  assert.match(html, /마지막 신호 0초 전/);
});

/** 키 대장 패널 본문 — 노드 하나와 키 상태(useAsync 꼴)를 넣어 그린다. */
const keyPanel = (key, extra = {}) => {
  const node = { nid: "n1", label: "PLATE_2", kind: "part", ckey: key.ckey };
  const keyState = { data: key, loading: false, error: null, reload() {}, ...extra };
  return renderToStaticMarkup(h(KeyLedgerBody, { node, nodes: [node], onClose() {}, keyState }));
};

/** 그 단추가 잠겼는가 — 정적 렌더의 disabled 속성. */
const locked = (html, label) => new RegExp(`<button[^>]*disabled=""[^>]*>${label}</button>`).test(html);
/** 그 단추에 원장 잠금의 까닭(title)이 붙었는가 — 이름 붙이기 · 병합은 빈 입력으로도 잠겨 있어 까닭으로 가른다. */
const ledgerTitled = (html, label) => new RegExp(`<button[^>]*title="[^"]*(원장입니다|결정을 받지 않습니다)[^"]*"[^>]*>${label}</button>`).test(html);
const DECISIONS = ["이름 붙이기", "병합…", "병합 되돌리기…", "독립 키로 확정…"];

test("키 대장 패널 — 내 원장의 병합된 키면 '독립 키로 확정' 만 잠기고 까닭을 말한다", () => {
  const merged = keyPanel(samples.partKeyMergedOwn);
  assert.match(merged, /다른 키로 병합됨 · 대표 키 ck:[0-9a-f]{12}/);
  assert.doesNotMatch(merged, /다른 사람의 원장 행/);
  assert.equal(locked(merged, "독립 키로 확정…"), true);
  assert.match(merged, /병합돼 있어 확정할 수 없습니다/);
  assert.equal(locked(merged, "병합 되돌리기…"), false);
  assert.deepEqual(DECISIONS.map((d) => ledgerTitled(merged, d)), [false, false, false, false]);
  assert.doesNotMatch(merged, /읽는 길을 주지 않아/);
  const named = keyPanel(samples.partKeyNamed);
  assert.match(named, /이름 «보호 필름»/);
  assert.equal(locked(named, "독립 키로 확정…"), false);
  assert.equal(locked(named, "병합 되돌리기…"), false);
});

test("키 대장 패널 — 남의 원장 행(mine false)이면 다른 사람의 행이라 말하고 결정 넷을 모두 잠근다", () => {
  // 보기 멤버 · 이양받은 새 주인이 본 키 — 서버는 부른 사람의 원장 행만 고쳐 어느 결정이든 404 다. 상태(병합됨)로 가르지 않는다.
  const theirs = keyPanel(samples.partKeyMerged);
  assert.match(theirs, /지금 상태 — <\/span><span[^>]*>다른 사람의 원장 행 — <\/span>다른 키로 병합됨/);
  // 까닭은 단추의 title 말고는 패널 글(알림)로 한 번만 선다 — 요소 내용(> 뒤)으로 센다(확정 단추 옆에 되풀이하지 않는다).
  assert.equal((theirs.match(/>이 행은 다른 사람\(그 키를 처음 적립한 사람\)의 원장입니다/g) ?? []).length, 1);
  assert.deepEqual(DECISIONS.map((d) => locked(theirs, d)), [true, true, true, true]);
  assert.deepEqual(DECISIONS.map((d) => ledgerTitled(theirs, d)), [true, true, true, true]);
  assert.doesNotMatch(theirs, /병합돼 있어 확정할 수 없습니다/);   // 병합 까닭이 아니라 원장 까닭이다
  const candidate = keyPanel({ ...samples.partKeyNamed, mine: false });
  assert.deepEqual(DECISIONS.map((d) => locked(candidate, d)), [true, true, true, true]);
});

test("키 대장 패널 — 원장에 없는 키(404)는 그렇게 말하고 결정을 잠그며, 못 읽은 것은 '모름' 이고 잠그지 않는다", () => {
  const { NotReadyError } = load("api/risk.api.js");
  const absent = keyPanel(samples.partKeyMerged, { data: null, error: new NotReadyError(404, "E404", "정규 키를 찾을 수 없습니다") });
  assert.match(absent, /원장에 이 키의 행이 없거나 내 원장이 아닙니다/);
  assert.deepEqual(DECISIONS.map((d) => locked(absent, d)), [true, true, true, true]);
  assert.deepEqual(DECISIONS.map((d) => ledgerTitled(absent, d)), [true, true, true, true]);
  assert.doesNotMatch(absent, />원장에 내 행이 없는 키라/);   // 지금 상태 줄이 이미 말한다 — 확정 단추 옆에 되풀이하지 않는다
  // 그 밖의 실패는 '모름' 이다 — 잠그지 않는다(서버가 결정의 거절 code 로 말한다).
  const failed = keyPanel(samples.partKeyMerged, { data: null, error: new Error("network") });
  assert.match(failed, /모름\(읽지 못했습니다\)/);
  assert.equal(locked(failed, "독립 키로 확정…"), false);
  assert.equal(locked(failed, "병합 되돌리기…"), false);
  assert.deepEqual(DECISIONS.map((d) => ledgerTitled(failed, d)), [false, false, false, false]);
});
