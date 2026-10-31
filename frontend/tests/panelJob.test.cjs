// 패널 잡 본문 시험 — GLM 본문은 판단 LLM 칸이 생기기 전과 바이트로 같고, Claude 칸은 동의를 체크했을 때만 실린다.
const test = require("node:test");
const assert = require("node:assert/strict");
const load = require("./load.cjs");

const { panelJobBody, panelJobReady, describeJobError } = load("api/panelJob.js");
const { ApiError, NotReadyError } = load("api/risk.api.js");

/** 판단 LLM 칸이 생기기 전의 본문(TargetPage PanelRunner.start 의 객체 그대로) — 견줄 기준이다. */
function legacyBody(f) {
  const needsConsent = f.tier === "C";
  return {
    tier: f.tier,
    concurrency: f.concurrency,
    modifiers: f.modifiers.trim() === "" ? undefined : f.modifiers.split(",").map((s) => s.trim()).filter(Boolean),
    user_memo: f.memo.trim() === "" ? undefined : f.memo.trim(),
    consent: needsConsent ? f.tierConsent : undefined,
  };
}

function* forms() {
  for (const tier of ["A", "B", "C"])
    for (const concurrency of [1, 2])
      for (const modifiers of ["", "  ", "voi", " voi , premortem ,, "])
        for (const memo of ["", "  ", " 메모 한 줄 "])
          for (const tierConsent of [false, true])
            yield { tier, concurrency, modifiers, memo, tierConsent };
}

test("GLM 본문은 종전 본문과 JSON 바이트가 같다(동의 체크가 남아 있어도)", () => {
  let n = 0;
  for (const f of forms()) {
    for (const externalConsent of [false, true]) {
      const body = panelJobBody({ ...f, llm: "glm", externalConsent });
      assert.equal(JSON.stringify(body), JSON.stringify(legacyBody(f)));
      assert.equal("llm" in body, false);
      assert.equal("consent_external" in body, false);
      n += 1;
    }
  }
  assert.equal(n, 288);
});

test("Claude 를 고르고 동의를 체크하지 않으면 consent_external 이 본문에 없고 시작할 수 없다", () => {
  const form = { tier: "B", concurrency: 1, modifiers: "", memo: "", tierConsent: false, llm: "claude", externalConsent: false };
  const body = panelJobBody(form);
  assert.equal(body.llm, "claude");
  assert.equal("consent_external" in body, false);
  assert.equal(JSON.stringify(body), '{"tier":"B","concurrency":1,"llm":"claude"}');
  assert.equal(panelJobReady(form), false);
});

test("Claude 에 동의를 체크했을 때만 consent_external 이 JSON true 로 실린다", () => {
  const form = { tier: "A", concurrency: 2, modifiers: "voi", memo: "m", tierConsent: false, llm: "claude", externalConsent: true };
  const body = panelJobBody(form);
  assert.equal(body.consent_external, true);
  assert.equal(
    JSON.stringify(body),
    '{"tier":"A","concurrency":2,"modifiers":["voi"],"user_memo":"m","llm":"claude","consent_external":true}',
  );
  assert.equal(panelJobReady(form), true);
});

test("Tier C 는 명시 승인이 있어야 시작하고, Claude 면 반출 동의도 따로 있어야 한다", () => {
  const base = { tier: "C", concurrency: 1, modifiers: "", memo: "", llm: "glm", externalConsent: false };
  assert.equal(panelJobReady({ ...base, tierConsent: false }), false);
  assert.equal(panelJobReady({ ...base, tierConsent: true }), true);
  assert.equal(panelJobReady({ ...base, tierConsent: true, llm: "claude" }), false);
  assert.equal(panelJobReady({ ...base, tierConsent: true, llm: "claude", externalConsent: true }), true);
});

test("잡 만들기 거절은 code 로 가른다 — 문구가 같아도 code 가 다르면 다르게 읽는다", () => {
  const msg = "아무 글";
  assert.deepEqual(describeJobError(new ApiError(422, "consent_external_required", msg)), {
    title: "Claude 로 고르려면 반출 동의가 필요합니다.",
    next: null,
  });
  assert.equal(describeJobError(new ApiError(422, "pat_unavailable", msg)).next, "settings");
  assert.equal(describeJobError(new ApiError(409, "external_llm_unavailable", msg)).next, "use_glm");
  assert.equal(describeJobError(new ApiError(422, "flow_mismatch", msg)).next, null);
  assert.equal(describeJobError(new ApiError(409, "review_job_running", msg)).next, null);
  assert.equal(describeJobError(new ApiError(422, "E100", "external_llm_unavailable")), null);
  assert.equal(describeJobError(new NotReadyError(404, "E404", msg)), null);
  assert.equal(describeJobError(new Error("pat_unavailable")), null);
});
