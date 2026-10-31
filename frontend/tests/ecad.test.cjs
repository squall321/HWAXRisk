// ECAD 보드 화면 판정 시험 — 카드 갈래 · 찾을 말 · 거절 code · 확인 글 · 동결 폼의 기본 kinds · 409 두 갈래(ecad-1031 1 ~ 6절)
const test = require("node:test");
const assert = require("node:assert/strict");
const load = require("./load.cjs");

const ecad = load("api/ecadBoard.js");
const capture = load("lib/capture.js");
const { ApiError, NotReadyError } = load("api/risk.api.js");

const ROW = (status, extra = {}) => ({
  kind: "ecad", app_key: "odb-hub", status, tools_ok: status === "ready", tools_missing: [], gateway_error: null,
  warnings: [], choices: [], ...extra,
});
const BOARD = (rev, job) => ({
  job_id: job, name: `PRJ-A / MDL-1 / Main / ${rev}`, project: "PRJ-A", model: "MDL-1", board_type: "Main", revision: rev,
  original_filename: `MDL-1_${rev}.tgz`, uploaded_at: "2026-10-29T02:11:40+00:00",
});

test("카드 갈래는 meta/adapters 의 ecad status 로만 가른다", () => {
  assert.equal(ecad.ecadRoute([ROW("ready")]), "ready");
  assert.equal(ecad.ecadRoute([ROW("unavailable", { tools_missing: ["find_job"] })]), "unavailable");
  assert.equal(ecad.ecadRoute([ROW("planned")]), "planned");
  assert.equal(ecad.ecadRoute([ROW("contract_only")]), "unknown"); // 더 나오지 않는 옛 값은 길을 열지 않는다
  assert.equal(ecad.ecadRoute([{ ...ROW("ready"), kind: "mcad" }]), "unknown");
  assert.equal(ecad.ecadRoute(null), "unknown");
});

test("찾을 말 — 비거나 200자를 넘으면 보내기 전에 막는다", () => {
  assert.match(ecad.boardQueryProblem(""), /찾을 말/);
  assert.match(ecad.boardQueryProblem("   "), /찾을 말/);
  assert.match(ecad.boardQueryProblem("x".repeat(201)), /200자/);
  assert.equal(ecad.boardQueryProblem("x".repeat(200)), null);
  assert.equal(ecad.boardQueryProblem("61f311d47203781d"), null);
});

test("거절은 code 로 가른다 — 같은 글이어도 code 가 다르면 갈래가 다르다", () => {
  const same = "같은 서버 글";
  const of = (status, code, body) => ecad.describeEcadError(new ApiError(status, code, same, body));
  assert.equal(of(409, "ecad_pat_absent").next, "settings");
  assert.equal(of(409, "ecad_credential_absent").next, "settings"); // 9bd5f48 전 옛 판 — 같은 안내
  assert.equal(of(409, "ecad_gateway_unreadable").next, "retry");
  assert.equal(of(409, "ecad_unreachable").next, "retry");
  const unavailable = of(409, "ecad_unavailable", { error: {}, tools_missing: ["find_job"] });
  assert.equal(unavailable.next, null);
  assert.match(unavailable.detail, /find_job/);
  assert.equal(of(409, "ecad_schema_drift").next, null);
  assert.equal(of(422, "ecad_board_not_found").next, "candidates");
  assert.equal(of(422, "E100").next, null);
  assert.equal(of(409, "other_code"), null); // 모르는 code 는 공용 배너
  assert.equal(ecad.describeEcadError(new NotReadyError(404, "E404", same)), null); // 남의 과제 — 공용 '없음'
  assert.equal(ecad.describeEcadError(new Error(same)), null);
});

test("422 ecad_board_not_found — 본문의 후보와 허브 글을 꺼내되 고르지 않는다", () => {
  const body = { error: { code: "ecad_board_not_found" }, candidates: [BOARD("0.7", "61f311d47203781d")], hub_message: "허브 글" };
  const out = ecad.notFoundCandidates(new ApiError(422, "ecad_board_not_found", "x", body));
  assert.equal(out.candidates.length, 1);
  assert.equal(out.hub_message, "허브 글");
  assert.equal(ecad.notFoundCandidates(new ApiError(409, "ecad_unreachable", "x", body)), null);
});

test("바꾸기 확인 글은 앞 보드(판) → 새 보드(판)와 동결 스냅샷이 그대로라는 말 — 붙은 보드가 없으면 묻지 않는다", () => {
  assert.equal(ecad.replaceConfirmText(null, BOARD("0.8", "079eb91bd2974d87")), null);
  const text = ecad.replaceConfirmText(BOARD("0.7", "61f311d47203781d"), BOARD("0.8", "079eb91bd2974d87"));
  assert.match(text, /0\.7\(판 0\.7\) → .*0\.8\(판 0\.8\)/);
  assert.match(text, /이미 동결된 스냅샷은 그대로이고 다음 캡처부터 새 보드를 읽습니다/);
  assert.equal(ecad.boardLabel({ name: null, revision: null, job_id: "abcdef0123456789" }), "job abcdef0123456789(판 모름)");
  assert.match(ecad.DETACH_CONFIRM_TEXT, /ecad_absent/);
});

test("동결 폼 기본 kinds — ECAD 카드가 붙어 있으면 ecad 를 더한다", () => {
  assert.deepEqual(capture.defaultSnapshotKinds([]), ["mcad"]);
  assert.deepEqual(capture.defaultSnapshotKinds([{ kind: "mcad" }]), ["mcad"]);
  assert.deepEqual(capture.defaultSnapshotKinds([{ kind: "ecad" }]), ["mcad", "ecad"]);
});

test("동결 본문 — report_ids 는 수, 수가 아니면 보내지 않고, allow_large 는 다시 보낼 때만 싣는다", () => {
  const form = { label: " rev1 ", kinds: ["ecad"], reportIds: "12, 7", detectId: "" };
  assert.deepEqual(capture.snapshotBody(form), { kinds: ["ecad"], label: "rev1", report_ids: [12, 7] });
  assert.equal("allow_large" in capture.snapshotBody(form), false);
  assert.equal(capture.snapshotBody(form, true).allow_large, true);
  assert.equal(capture.snapshotBody({ ...form, reportIds: "12, x7" }), null);
  assert.deepEqual(capture.snapshotBody({ label: "", kinds: ["mcad", "ecad"], reportIds: "", detectId: "" }), {
    kinds: ["mcad", "ecad"],
  });
});

test("409 두 갈래를 code 와 detail 로 가른다 — model_too_large · source_unreachable(kinds · ECAD 하나)", () => {
  const large = capture.describeSnapshotError(new ApiError(409, "model_too_large", "글", {
    error: {}, leaf: 812, leaf_mcad: 0, leaf_ecad: 812, interfaces: 0, max_leaf: 800, max_interfaces: 6000, budget_s: 600,
  }));
  assert.equal(large.kind, "model_too_large");
  assert.equal(large.detail.leaf_ecad, 812);
  const kinds = capture.describeSnapshotError(new ApiError(409, "source_unreachable", "글", { kinds: ["mcad"], attached: ["ecad"] }));
  assert.deepEqual(kinds, { kind: "kinds_excluded", attached: ["ecad"], message: "글" });
  const unread = capture.describeSnapshotError(new ApiError(409, "source_unreachable", "글", { kind: "ecad", reason: "ecad_pat_absent" }));
  assert.deepEqual(unread, { kind: "ecad_unread", reason: "ecad_pat_absent", message: "글" });
  // 카드가 아예 없는 source_unreachable(detail 없음)과 다른 code 는 공용 배너다.
  assert.equal(capture.describeSnapshotError(new ApiError(409, "source_unreachable", "글", {})).kind, "other");
  assert.equal(capture.describeSnapshotError(new ApiError(422, "model_too_large", "글", { leaf: 1 })).kind, "other");
});

test("모델 크기 한 줄 — 무엇이 상한을 넘겼는지 MCAD 리프와 ECAD 부품으로 나눠 말한다", () => {
  const base = { interfaces: 0, max_leaf: 800, max_interfaces: 6000, budget_s: 600 };
  assert.match(capture.modelTooLargeLine({ ...base, leaf: 812, leaf_mcad: 0, leaf_ecad: 812 }), /ECAD 부품만으로 넘겼습니다/);
  assert.match(capture.modelTooLargeLine({ ...base, leaf: 900, leaf_mcad: 300, leaf_ecad: 600 }), /MCAD 리프와 ECAD 부품이 함께/);
  assert.match(capture.modelTooLargeLine({ ...base, leaf: 900, leaf_mcad: 900, leaf_ecad: 0 }), /MCAD 리프가 넘겼습니다/);
  assert.match(capture.modelTooLargeLine({ ...base, leaf: 10, leaf_mcad: 10, leaf_ecad: 0, interfaces: 7000 }), /계면 상한/);
  // 예산 600 s 를 적지 않는다 — '600초에 끊긴다' 로 읽혔다(routes.LARGE_BUDGET_S 주석).
  assert.doesNotMatch(capture.modelTooLargeLine({ ...base, leaf: 900, leaf_mcad: 0, leaf_ecad: 900 }), /예산|600 ?s|600초/);
});
