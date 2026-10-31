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

test("키 대장 패널 — 서버가 준 지금 상태를 보이고, 병합된 키면 '독립 키로 확정' 이 잠기고 까닭을 말한다", () => {
  const merged = keyPanel(samples.partKeyMerged);
  assert.match(merged, /다른 키로 병합됨 · 대표 키 ck:[0-9a-f]{12}/);
  assert.match(merged, /<button[^>]*disabled=""[^>]*>독립 키로 확정…<\/button>/);
  assert.match(merged, /병합돼 있어 확정할 수 없습니다/);
  assert.doesNotMatch(merged, /읽는 길을 주지 않아/);
  const named = keyPanel(samples.partKeyNamed);
  assert.match(named, /이름 «보호 필름»/);
  assert.doesNotMatch(named, /<button[^>]*disabled=""[^>]*>독립 키로 확정…<\/button>/);
  // 원장에 없는(또는 남의) 키는 404 E404 — 그렇게 말한다. 그 밖의 실패는 '모름' 이다(잠그지 않는다 — 서버가 409 로 말한다).
  const { NotReadyError } = load("api/risk.api.js");
  const absent = keyPanel(samples.partKeyMerged, { data: null, error: new NotReadyError(404, "E404", "정규 키를 찾을 수 없습니다") });
  assert.match(absent, /원장에 이 키의 행이 없거나 내 원장이 아닙니다/);
  assert.doesNotMatch(absent, /<button[^>]*disabled=""[^>]*>독립 키로 확정…<\/button>/);
  const failed = keyPanel(samples.partKeyMerged, { data: null, error: new Error("network") });
  assert.match(failed, /모름\(읽지 못했습니다\)/);
});
