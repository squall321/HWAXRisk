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

// ── 등록이 실패한 뒤 — 방금 받은 PAT 를 버려 두지 않는다 · 이 브라우저의 쉼 ───────────────────────────────

const { AUTO_HELD_KEY, AUTO_HOLD_FINAL_MS, AUTO_HOLD_TRANSIENT_MS, createAutoHold } = load("api/autoPortalPat.js");
const { PortalMintError, PortalRegisterError, autoHoldOf, refusedBeforeStore, registerFromPortal } = load("api/portalPat.js");
const { ApiError, NetworkError } = load("api/risk.api.js");
const { describePatFailure } = load("api/patErrors.js");

test("자격 암호화 키가 Fernet 키가 아닌 박스는 자동으로 받지 않는다(등록은 반드시 422) — 키 없음 · 개발용 폴백은 등록이 되므로 막지 않는다", () => {
  const box = (codes) => ({ hostname: "h", secrets_valid: false, cred_key_present: true, portal_base: "x", reasons: codes.map((code) => ({ code })) });
  assert.equal(autoRegisterWanted(me(AUTO, { box: box(["cred_key_invalid"]) })), false);
  assert.equal(autoRegisterWanted(me(AUTO, { box: box(["cred_key_dev_fallback", "missing_optional"]) })), true);
  assert.equal(autoRegisterWanted(me(AUTO, { box: box(["missing_required"]) })), true);
});

test("쉼 표지 — {until, code} 만 담고, 지난 쉼 · 읽을 수 없는 값은 없는 것이며, 저장소가 던져도 이 페이지 안에서는 쉰다", () => {
  const store = new Map();
  const storage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
  const hold = createAutoHold(() => storage);
  assert.equal(hold.current(1000), null);
  hold.hold({ until: 5000, code: "portal_unreachable" });
  assert.deepEqual(JSON.parse(store.get(AUTO_HELD_KEY)), { until: 5000, code: "portal_unreachable" });
  assert.deepEqual(createAutoHold(() => storage).current(4999), { until: 5000, code: "portal_unreachable" }); // 다른 탭
  assert.equal(hold.current(5000), null);
  hold.clear();
  assert.equal(store.has(AUTO_HELD_KEY), false);
  store.set(AUTO_HELD_KEY, "{망가진");
  assert.equal(hold.current(0), null);
  const broken = createAutoHold(() => {
    throw new Error("SecurityError");
  });
  broken.hold({ until: 9000, code: "pat_invalid" });
  assert.deepEqual(broken.current(1), { until: 9000, code: "pat_invalid" });
});

test("쉼의 길이 — 일시 실패(네트워크 · 5xx · portal_unreachable)는 10분, 사람이 고칠 거절은 6시간, 발급 단계의 실패는 쉬지 않는다", () => {
  const now = 1_000_000;
  const of = (rejection) => autoHoldOf(new PortalRegisterError(rejection, "jti-1", "revoked"), now);
  assert.deepEqual(of(new ApiError(502, "portal_unreachable", "x")), { until: now + AUTO_HOLD_TRANSIENT_MS, code: "portal_unreachable" });
  assert.deepEqual(of(new NetworkError("끊김")), { until: now + AUTO_HOLD_TRANSIENT_MS, code: "network" });
  assert.deepEqual(of(new ApiError(422, "pat_email_mismatch", "x")), { until: now + AUTO_HOLD_FINAL_MS, code: "pat_email_mismatch" });
  assert.equal(autoHoldOf(new PortalMintError(403, "권한"), now), null);
  assert.equal(AUTO_HOLD_TRANSIENT_MS, 600_000); // 백엔드 AUTO_RETRY_TRANSIENT_S
  // 저장 전 거절 — 4xx 와 502 portal_unreachable(포털 검증에 못 닿음). 다른 5xx · 네트워크는 저장됐을 수도 있다.
  assert.equal(refusedBeforeStore(new ApiError(422, "cred_key_absent", "x")), true);
  assert.equal(refusedBeforeStore(new ApiError(502, "portal_unreachable", "x")), true);
  assert.equal(refusedBeforeStore(new ApiError(500, "E500", "x")), false);
  assert.equal(refusedBeforeStore(new NetworkError("끊김")), false);
});

/** 포털 · 앱 둘 다 흉내 내는 fetch — 경로별 답을 정하고 부른 차례를 적는다. */
function fakeFetch(routes) {
  const calls = [];
  const fetch = async (input, init = {}) => {
    const url = String(input);
    const call = { url, method: (init.method || "GET").toUpperCase(), headers: init.headers || {}, credentials: init.credentials };
    calls.push(call);
    const out = routes(call) ?? { status: 404, body: { error: { code: "E404", message: "없음" } } };
    if (out.throws) throw out.throws;
    return new Response(JSON.stringify(out.body), { status: out.status, headers: { "Content-Type": "application/json" } });
  };
  return { fetch, calls };
}

const MINTED = { token: "eyJ.minted.sig", jti: "jti-minted-0123456789", name: "hwax-risk", audiences: ["mcp-gateway", "step-forge"], scopes: ["read"], exp: 9999999999 };

async function register(routes) {
  const fake = fakeFetch((c) => {
    if (c.url === "/auth/pat" && c.method === "POST") return { status: 200, body: MINTED };
    return routes(c);
  });
  globalThis.document = { cookie: "hwax_csrf=csrf-test" };
  globalThis.fetch = fake.fetch;
  try {
    return { out: await registerFromPortal(), calls: fake.calls };
  } catch (err) {
    return { err, calls: fake.calls };
  }
}

const revokes = (calls) => calls.filter((c) => c.url === "/auth/pat/revoke-self");

test("저장 전 거절이면 방금 받은 PAT 를 그 토큰 자신으로 폐기한다(Bearer · 쿠키 없이) — 알림은 거절의 글에 '폐기했다 · 다시 하면 새로 발급' 을 붙인다", async () => {
  const { err, calls } = await register((c) => {
    if (c.url === "api/me/portal-pat") return { status: 502, body: { error: { code: "portal_unreachable", message: "포털에 닿지 못했습니다" } } };
    if (c.url === "/auth/pat/revoke-self") return { status: 200, body: { revoked: MINTED.jti } };
  });
  assert.ok(err instanceof PortalRegisterError);
  assert.equal(err.minted, "revoked");
  assert.equal(err.rejection.code, "portal_unreachable");
  const [revoke] = revokes(calls);
  assert.equal(revoke.method, "POST");
  assert.equal(revoke.headers.Authorization, `Bearer ${MINTED.token}`);
  assert.equal(revoke.credentials, "omit");
  assert.equal(calls.some((c) => c.url === "api/me"), false); // 저장 전 거절은 다시 읽지 않는다
  const text = describePatFailure(err);
  assert.equal(text.title, "포털에 닿지 못했습니다 — PAT 문제가 아닙니다.");
  assert.match(text.detail, /jti jti-minted-0\)는 등록하지 못해 포털에서 폐기했습니다 — 다시 하면 새로 발급합니다\./);
  assert.doesNotMatch(JSON.stringify(text), /eyJ\.minted\.sig/); // 토큰 값은 글에 싣지 않는다
});

test("폐기가 실패하면 사람이 포털 토큰 화면에서 폐기하라고 말한다", async () => {
  const { err } = await register((c) => {
    if (c.url === "api/me/portal-pat") return { status: 422, body: { error: { code: "pat_email_mismatch", message: "x" } } };
    if (c.url === "/auth/pat/revoke-self") return { status: 401, body: { detail: "invalid_token" } };
  });
  assert.equal(err.minted, "revoke_failed");
  assert.match(describePatFailure(err).detail, /폐기하지 못했습니다 — 포털 토큰 화면에서 그 jti 를 폐기하세요/);
});

test("저장됐을 수도 있는 실패(5xx · 네트워크)는 GET /me 로 가른다 — 그 jti 가 등록돼 있으면 성공, 다른 것이면 폐기, 못 읽으면 건드리지 않는다", async () => {
  const pat = (jti) => ({ status: 200, body: { email: "a@example.test", anonymous: false, portal_pat: { registered: true, jti, auto: {} }, box: {} } });
  const stored = await register((c) => {
    if (c.url === "api/me/portal-pat") return { status: 500, body: { error: { code: "E500", message: "x" } } };
    if (c.url === "api/me") return pat(MINTED.jti);
  });
  assert.deepEqual(stored.out, { jti: MINTED.jti });
  assert.equal(revokes(stored.calls).length, 0);

  const other = await register((c) => {
    if (c.url === "api/me/portal-pat") return { throws: new TypeError("Failed to fetch") };
    if (c.url === "api/me") return pat("jti-other");
    if (c.url === "/auth/pat/revoke-self") return { status: 200, body: {} };
  });
  assert.equal(other.err.minted, "revoked");
  assert.ok(other.err.rejection instanceof NetworkError);
  assert.equal(revokes(other.calls).length, 1);

  const unknown = await register((c) => {
    if (c.url === "api/me/portal-pat") return { status: 503, body: { error: { code: "E503", message: "x" } } };
    if (c.url === "api/me") return { status: 500, body: { error: { code: "E500", message: "x" } } };
  });
  assert.equal(unknown.err.minted, "unknown");
  assert.equal(revokes(unknown.calls).length, 0);
  assert.match(describePatFailure(unknown.err).detail, /등록됐는지 확인하지 못했습니다/);

  // 박스 불일치처럼 portal_pat 이 null 이면 등록 여부를 모른다 — 폐기하지 않는다.
  const nullPat = await register((c) => {
    if (c.url === "api/me/portal-pat") return { status: 500, body: { error: { code: "E500", message: "x" } } };
    if (c.url === "api/me") return { status: 200, body: { email: "a@example.test", anonymous: false, portal_pat: null, box: {} } };
  });
  assert.equal(nullPat.err.minted, "unknown");
  assert.equal(revokes(nullPat.calls).length, 0);
});

test("발급 단계의 실패는 PAT 를 만들지 않았으니 폐기할 것도 없다(PortalMintError 그대로)", async () => {
  globalThis.document = { cookie: "hwax_csrf=csrf-test" };
  const fake = fakeFetch((c) => (c.url === "/auth/pat" ? { status: 403, body: { detail: "feat:api-token" } } : undefined));
  globalThis.fetch = fake.fetch;
  await assert.rejects(registerFromPortal(), (err) => err instanceof PortalMintError && err.status === 403);
  assert.deepEqual(fake.calls.map((c) => c.url), ["/auth/pat"]);
});
