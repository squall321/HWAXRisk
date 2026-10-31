// 과제 만들기 · PAT 등록 거절을 code 로 가르는 시험 — 문구로 가르지 않는다.
const test = require("node:test");
const assert = require("node:assert/strict");
const load = require("./load.cjs");

const { projectCreateFieldError } = load("api/projectCreate.js");
const { describePatFailure, PAT_ERRORS } = load("api/patErrors.js");
const { ApiError, NotReadyError, NetworkError } = load("api/risk.api.js");
const { PortalMintError } = load("api/portalPat.js");

test("과제 만들기 — 등급 빠짐 · 같은 code · 앞 과제 없음은 그 칸으로, 나머지는 배너로", () => {
  assert.equal(projectCreateFieldError(new ApiError(422, "classification_required", "x")).field, "classification");
  const dup = projectCreateFieldError(new ApiError(409, "E409", "이미 있는 과제 코드입니다 — P1."));
  assert.deepEqual(dup, { field: "code", message: "이미 있는 과제 코드입니다 — P1." });
  // 404 는 NotReadyError 로 오지만 code 는 E404 다.
  assert.equal(projectCreateFieldError(new NotReadyError(404, "E404", "앞 과제(p) 를 찾을 수 없습니다.")).field, "predecessor");
  assert.equal(projectCreateFieldError(new ApiError(422, "E100", "classification 은 …")), null);
  assert.equal(projectCreateFieldError(new ApiError(401, "unauthorized", "x")), null);
  assert.equal(projectCreateFieldError(new NetworkError("down")), null);
});

test("PAT 실패 — 발급 단계는 그 글, 등록 거절은 code 표, 모르는 것은 null", () => {
  const mint = describePatFailure(new PortalMintError(403, "포털이 토큰 발급 권한(feat:api-token)을 요구합니다."));
  assert.equal(mint.title, "포털에서 PAT 를 발급하지 못했습니다.");
  assert.equal(mint.detail, "포털이 토큰 발급 권한(feat:api-token)을 요구합니다.");
  assert.deepEqual(describePatFailure(new ApiError(502, "portal_unreachable", "서버 글")), PAT_ERRORS.portal_unreachable);
  assert.deepEqual(describePatFailure(new ApiError(422, "pat_audience", "서버 글")), PAT_ERRORS.pat_audience);
  assert.equal(describePatFailure(new ApiError(500, "E500", "pat_audience")), null);
  assert.equal(describePatFailure(new Error("x")), null);
});
