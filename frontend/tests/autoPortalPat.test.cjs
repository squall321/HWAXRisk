// 포털 PAT 자동 등록 판정 시험 — enabled && due 일 때만, 같은 탭 세션에서 한 번만(저장소가 막혀도).
const test = require("node:test");
const assert = require("node:assert/strict");
const load = require("./load.cjs");

const { autoRegisterWanted, createOnceGate, AUTO_TRIED_KEY } = load("api/autoPortalPat.js");
const { MINT_BODY } = load("api/portalPat.js");

function me(auto, extra = {}) {
  return {
    email: "someone@example.test",
    anonymous: false,
    portal_pat: auto === null ? null : { registered: false, email: null, groups: [], exp: null, auto },
    ...extra,
  };
}
const AUTO = { enabled: true, due: true, due_reason: "absent", last_source: null, last_at: null, last_error: null,
  last_error_kind: null, last_error_at: null, how_to_stop: "멈추려면 끈다" };

test("자동 등록은 로그인한 사람의 enabled && due 일 때만이다", () => {
  assert.equal(autoRegisterWanted(me(AUTO)), true);
  assert.equal(autoRegisterWanted(me({ ...AUTO, due: false, due_reason: null })), false);
  assert.equal(autoRegisterWanted(me({ ...AUTO, enabled: false, how_to_stop: null })), false);
  assert.equal(autoRegisterWanted(me(AUTO, { anonymous: true })), false);
  assert.equal(autoRegisterWanted(me(null)), false); // 익명 · 박스 불일치는 portal_pat 이 null 이다
  assert.equal(autoRegisterWanted(null), false);
});

test("한 번 문 — 표시하면 같은 탭 세션의 다음 페이지에서도 닫혀 있고, 값은 '해 봤다' 한 글자뿐이다", () => {
  const store = new Map();
  const storage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
  const first = createOnceGate(() => storage);
  assert.equal(first.tried(), false);
  first.mark();
  assert.equal(first.tried(), true);
  assert.deepEqual([...store.entries()], [[AUTO_TRIED_KEY, "1"]]);
  const reloaded = createOnceGate(() => storage); // 새로 고침 — 메모리는 비고 sessionStorage 는 남는다
  assert.equal(reloaded.tried(), true);
});

test("저장소가 던져도 이 페이지 안에서는 한 번이다", () => {
  const broken = () => {
    throw new Error("SecurityError");
  };
  const gate = createOnceGate(broken);
  assert.equal(gate.tried(), false);
  gate.mark();
  assert.equal(gate.tried(), true);
  const missing = createOnceGate(() => null);
  missing.mark();
  assert.equal(missing.tried(), true);
});

test("발급 청중은 mcp-gateway · step-forge 둘이고 이름은 hwax-risk 다(백엔드 PORTAL_PAT_WANTED 와 같다)", () => {
  assert.deepEqual([...MINT_BODY.audiences], ["mcp-gateway", "step-forge"]);
  assert.equal(MINT_BODY.name, "hwax-risk");
  assert.deepEqual([...MINT_BODY.scopes], ["read"]);
});
