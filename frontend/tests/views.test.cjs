// 스냅샷 · 비교 · 대상 · 과제 화면의 순수 판정 시험 — 서버 꼴 그대로의 값에서 표지 · 판정 불가 · 평가 불가 · ECAD 말 · 신호 · 메타를 본다
const test = require("node:test");
const assert = require("node:assert/strict");
const load = require("./load.cjs");

const snap = load("lib/snapshotView.js");
const cmp = load("lib/compareView.js");
const tgt = load("lib/targetView.js");
const meta = load("lib/projectMeta.js");

/** state.compute_gates 의 한 칸 꼴. */
const gate = (key, pass, extra = {}) => ({
  key, count: pass === null ? null : pass ? 0 : 1, threshold: 0, pass, reason: null, blocking: false, effect: "mark",
  ack_by: null, ack_at: null, ack_reason: null, detail: [], ...extra,
});

test("ECAD 표지 열둘과 결측 하나에 사람 말이 있다(ecad-1031 §7 표)", () => {
  for (const code of [
    "ecad_nets_deferred", "component_xy_deferred", "components_unclassified_omitted", "outline_origin_unknown",
    "stackup_material_unmatched", "copper_weight_absent", "plane_type_unknown", "odb_version_absent",
    "component_value_absent", "component_height_partial", "components_unavailable", "layers_unavailable",
    "ecad_capture_failed",
  ]) {
    assert.ok(snap.FLAG_LABEL[code], code);
  }
  assert.equal(snap.FLAG_LABEL.ecad_nets_deferred, "회로 넷 없음(2단계)");
});

test("표지 — missing 은 참인 열쇠만, 소스 degraded 는 kind 를 붙이고 같은 코드는 한 번", () => {
  const flags = snap.snapshotFlags({
    missing: { ecad_absent: false, mcad_absent: true, dyna_absent: true },
    sources: [
      { kind: "ecad", degraded: ["ecad_nets_deferred", "mcad_absent"] },
      { kind: "mcad", degraded: [] },
    ],
  });
  assert.deepEqual(flags.map((f) => `${f.where}:${f.code}`), ["missing:mcad_absent", "missing:dyna_absent", "ecad:ecad_nets_deferred"]);
  assert.equal(flags[2].label, "회로 넷 없음(2단계)");
  assert.deepEqual(snap.snapshotFlags({ missing: {}, sources: [{ kind: "x", degraded: ["new_code"] }] })[0].label, null);
});

test("게이트 판정 — null 은 중립색 '판정 불가(까닭)' 이고 fail 이 아니다(mcp_degraded 의 G3 · G4)", () => {
  const g3 = snap.gateVerdict(gate("iface_unconfirmed", null, { reason: "capture_partial" }));
  const g4 = snap.gateVerdict(gate("coordinate", null, { reason: "warnings_unavailable" }));
  for (const v of [g3, g4]) {
    assert.equal(v.tone, "muted");
    assert.doesNotMatch(v.label, /fail/);
  }
  assert.equal(g3.label, "판정 불가(capture_partial)");
  assert.equal(snap.gateVerdict(gate("x", null)).label, "판정 불가"); // 까닭이 없으면 지어내지 않는다
  assert.deepEqual(snap.gateVerdict(gate("x", true)), { tone: "ok", label: "pass" });
  assert.equal(snap.gateVerdict(gate("x", false, { count: 3 })).label, "fail(3)");
  assert.equal(snap.gateVerdict(gate("x", false, { count: 3, ack_by: "a@b" })).label, "fail(3) · ack");
  assert.equal(snap.gateFailing({ G3: gate("x", null) }, "G3"), false);
  assert.equal(snap.gateFailing({ G3: gate("x", false) }, "G3"), true);
});

test("ack 는 fail 이고 차단이 아닌 게이트에만 — G6 · 판정 불가 · pass 는 아니다", () => {
  assert.equal(snap.gateAckable("G3", gate("x", false)), true);
  assert.equal(snap.gateAckable("G6", gate("unit_scale", false, { blocking: true })), false);
  assert.equal(snap.gateAckable("G2", gate("x", false, { blocking: true })), false);
  assert.equal(snap.gateAckable("G3", gate("x", null)), false);
  assert.equal(snap.gateAckable("G3", gate("x", true)), false);
  assert.deepEqual(snap.gateRows({ G6: gate("a", true), G1: gate("b", true) }).map((r) => r.id), ["G1", "G6"]);
});

test("규칙 — evaluable=false 는 '평가 불가(사유)' 이고 pass 집계에 들지 않는다(R-004 · R-005)", () => {
  const hit = (rule, pass, evaluable, reason, count = 0) => ({
    rule, version: "rules-1.0", severity: "중대", pass, evaluable, not_evaluable_reason: reason,
    found: { count, refs: [], text: "" }, why_it_matters: "", fix_hint: "", refs: [],
  });
  const hits = [hit("R-004", null, false, "degraded"), hit("R-005", null, false, "degraded"), hit("R-002", true, true, null),
    hit("R-001", false, true, null, 2)];
  assert.deepEqual(snap.ruleVerdict(hits[0]), { tone: "muted", label: "평가 불가(degraded)", title: "소스가 강등돼 입력을 믿을 수 없음" });
  assert.equal(snap.ruleVerdict(hits[3]).label, "fail(2건)");
  assert.deepEqual(snap.ruleCounts(hits), { pass: 1, fail: 1, notEvaluable: 2 });
  // evaluable=false 가 이긴다 — pass 칸에 값이 남아 와도 fail · pass 로 세지 않는다.
  assert.deepEqual(snap.ruleCounts([hit("R-009", false, false, "truncated")]), { pass: 0, fail: 0, notEvaluable: 1 });
  assert.equal(snap.ruleVerdict(hit("R-009", false, false, "truncated")).label, "평가 불가(truncated)");
});

test("보드 묶음 — null 은 '없음'(0 이 아니다) · 2단계 칸 표시 · 외곽 폭 × 높이", () => {
  const node = {
    kind: "board", domain: "ecad", attrs: {
      board_id: "61f3", name: "PRJ / M / Main / 0.7", revision: "0.7", units: "mm", thickness: 0.8, stackup_verdict: "standard",
      stackup_id: null, ecad_stackup_total: 0.8, layer_count: 10, n_components: 748, n_components_placed: null,
      outline: { x_mm: 107.18, y_mm: 72.97, area_mm2: 6100.3212 }, outline_bbox: null, n_nets: null, odb_version: null,
      source_hash: null,
    },
  };
  const rows = Object.fromEntries(snap.boardRows(node).map((r) => [r.hint, r]));
  assert.equal(rows.thickness.value, "0.8 mm");
  assert.equal(rows.stackup_id.value, null);
  assert.equal(rows.n_components_placed.value, null);
  assert.equal(rows["outline.x_mm · y_mm"].value, "107.18 × 72.97 mm");
  assert.equal(rows["outline.area_mm2"].value, "6100.3 mm²");
  for (const k of ["n_nets", "odb_version", "outline_bbox"]) assert.equal(rows[k].phase2, true, k);
  assert.equal(rows.n_components.phase2, undefined);
  assert.equal(snap.boardNode({ nodes: [{ domain: "mcad", kind: "part" }] }), null);
  // 자릿수 0 으로 반올림한 글의 0 은 떼지 않는다('100' 이 '1' 이 되던 자리) — 소수점 뒤의 끝 0 만 뗀다.
  const odd = Object.fromEntries(
    snap.boardRows({ kind: "board", domain: "ecad", attrs: { layer_count: 99.6, thickness: 1.0004 } }).map((r) => [r.hint, r.value]),
  );
  assert.equal(odd.layer_count, "100");
  assert.equal(odd.thickness, "1 mm");
});

test("노드 kind 거름 · 요구 여유 — 신호가 없으면 null(지어내지 않는다)", () => {
  const nodes = [
    { nid: "p:1", kind: "component", label: "C1", name_norm: "c1", canon_key: "ecad:C1", ckey: null, dn: null },
    { nid: "p:2", kind: "component", label: "C2", name_norm: "c2", canon_key: "ecad:C2", ckey: "ck:aa", dn: null },
    { nid: "p:3", kind: "layer", label: "signal_1", name_norm: "signal_1", canon_key: "ecad:layer:1", ckey: null, dn: null },
  ];
  assert.deepEqual(snap.nodeKindCounts(nodes), [{ kind: "component", n: 2 }, { kind: "layer", n: 1 }]);
  assert.deepEqual(snap.filterNodes(nodes, "component", "").map((n) => n.nid), ["p:1", "p:2"]);
  assert.deepEqual(snap.filterNodes(nodes, "", "ck:aa").map((n) => n.nid), ["p:2"]);
  assert.equal(snap.marginRows({ signals: {} }), null);
  const row = { name: "t", op: "lte", limit: 1, unit: "mm", actual: null, margin: null, rel: null, known: false, status: "candidate" };
  assert.deepEqual(snap.marginRows({ signals: { "req.margin": { value: [row] } } }), [row]);
});

test("요구 여유 — 동결이 요구를 대조해 상태에 싣는다(실 서버 견본 · 10-31 risk-flow) — 위반 · 여유 · 미측정 차례 그대로", () => {
  const samples = load("contract/serverSamples.js");
  const rows = snap.marginRows(samples.snapshotStateMargin);
  assert.deepEqual(rows.map((r) => [r.name, r.margin, r.known]), [["plate1_t", -0.2, true], ["plate2_t", 0.1, true], ["ghost_t", null, false]]);
  assert.equal(samples.snapshotStateMargin.missing.req_absent, false);
});

test("진행판 패널 잡이 멈춘 까닭 — 정지 까닭이 없으면 보류 코드(실 서버 견본 · external_worker), 둘 다 없으면 null", () => {
  const samples = load("contract/serverSamples.js");
  const job = samples.coveragePanelHeld.job;
  assert.equal(job.pause_reason, null);
  const pause = tgt.panelJobPause(job);
  assert.equal(pause.code, "external_worker");
  assert.equal(pause.externalWorker, true);
  assert.match(pause.label, /외부 응답자 워커 없음/);
  assert.deepEqual(tgt.panelJobPause({ state: "paused", pause_reason: "user", hold_code: null }), { code: "user", label: "사람이 멈춤", externalWorker: false });
  assert.equal(tgt.panelJobPause({ state: "paused", pause_reason: null, hold_code: "new_code" }).label, "new_code");
  assert.equal(tgt.panelJobPause({ state: "paused", pause_reason: null, hold_code: null }), null);
});

test("진행판 패널 잡 — 멈춘 잡만 멈춘 까닭이 있다: 취소가 보류를 비운 줄(실 서버 견본)도, 그 전에 취소돼 보류가 남은 줄도 까닭이 없다(반대 검토 10-31)", () => {
  const samples = load("contract/serverSamples.js");
  const job = samples.coveragePanelCancelledAfterHold.job;
  assert.deepEqual([job.state, job.pause_reason, job.hold_code, job.hold_until], ["cancelled", null, null, null]);
  assert.equal(tgt.panelJobPause(job), null);
  // 서버가 취소에서 보류를 비우기 전의 원장 — 취소된 잡에 external_worker 가 남아 있다. '워크플로를 다시 돌린 뒤 재개' 를 말하지 않는다.
  assert.equal(tgt.panelJobPause({ ...job, hold_code: "external_worker" }), null);
  for (const state of ["queued", "running", "cancelling", "completed", "failed"]) {
    assert.equal(tgt.panelJobPause({ state, pause_reason: null, hold_code: "external_worker" }), null, state);
  }
  assert.equal(tgt.panelJobPause(samples.coveragePanelHeld.job).code, "external_worker"); // 멈춘 잡은 그대로
});

test("비교 — ECAD 항목의 partial_scope 는 '한쪽에만 보드', 한쪽 실패는 capture_partial 말", () => {
  assert.equal(cmp.excludedLabel("partial_scope", true), "한쪽 스냅샷에만 보드");
  assert.equal(cmp.excludedLabel("partial_scope", false), "부분 검출 범위 밖");
  assert.equal(cmp.excludedLabel("capture_partial", false), "한쪽 캡처가 부분 · 실패");
  assert.equal(cmp.excludedLabel("brand_new", false), "사전에 없는 사유입니다.");
  const scope = cmp.ecadComparabilityLine({ ecad: { base: "absent", target: "present", excluded_reason: "partial_scope", adapter_parity: true } });
  assert.match(scope.note, /한쪽 스냅샷에만 보드가 있습니다 — ECAD 는 견주지 않았습니다/);
  assert.equal(scope.phase1Note, null);
  const failed = cmp.ecadComparabilityLine({ ecad: { base: "failed", target: "present", excluded_reason: "capture_partial", adapter_parity: true } });
  assert.match(failed.note, /한쪽 보드를 온전히 읽지 못했습니다/);
  const both = cmp.ecadComparabilityLine({ ecad: { base: "present", target: "present", excluded_reason: null, adapter_parity: true } });
  assert.match(both.phase1Note, /추가 · 삭제만/);
  assert.equal(cmp.ecadComparabilityLine({}), null);
});

test("'파서 세대 다름' — parity 가 정말 false 일 때만(모름은 다름이 아니다)", () => {
  assert.equal(cmp.parserGenerationDiffers({ app_version_parity: false }), true);
  assert.equal(cmp.parserGenerationDiffers({ adapter_parity: false }), true);
  assert.equal(cmp.parserGenerationDiffers({ ecad: { adapter_parity: false } }), true);
  assert.equal(cmp.parserGenerationDiffers({ app_version_parity: null, adapter_parity: true }), false);
  assert.equal(cmp.parserGenerationDiffers({}), false);
  assert.match(cmp.parserGenerationNote({ app_version_parity: false }), /소스 앱 판이 다름/);
  assert.deepEqual(cmp.parityWord(null), { tone: "muted", label: "모름" });
});

test("caveat 말 — parser_differs 의 까닭을 행마다 비교 가능성에서 고른다(ECAD 말을 MCAD 행에 붙이지 않는다)", () => {
  const mcadItem = { caveat: "parser_differs", isEcad: false, layer: "parametric" };
  const ecadEvent = { caveat: "parser_differs", isEcad: true, layer: "semantic" };
  const appDiffers = { app_version_parity: false, adapter_parity: true, ecad: { adapter_parity: true } };
  assert.equal(cmp.caveatTitle(mcadItem, appDiffers), "소스 앱 판이 다름 — 이 변화의 일부가 파서 차이일 수 있습니다.");
  assert.doesNotMatch(cmp.caveatTitle(mcadItem, appDiffers), /ECAD/);
  // 두 출처가 겹쳐도 MCAD 행에는 ECAD 까닭을 붙이지 않는다.
  const both = { app_version_parity: false, adapter_parity: true, ecad: { adapter_parity: false } };
  assert.equal(cmp.caveatTitle(mcadItem, both), "소스 앱 판이 다름 — 이 변화의 일부가 파서 차이일 수 있습니다.");
  const ecadOnly = { app_version_parity: true, adapter_parity: true, ecad: { adapter_parity: false } };
  assert.equal(cmp.caveatTitle(ecadEvent, ecadOnly), "ECAD 어댑터 세대가 다름 — 이 사건의 신뢰 등급을 한 단계 낮췄습니다.");
  assert.match(cmp.caveatTitle(mcadItem, null), /^두 스냅샷의 파서 세대가 다름/);
  assert.equal(cmp.caveatTitle({ caveat: "other_note", isEcad: false, layer: "structural" }, appDiffers), "other_note");
  assert.equal(cmp.caveatTitle({ caveat: null, isEcad: false, layer: "structural" }, appDiffers), null);
});

test("diff 3층을 한 표 줄로 — ECAD 노드 변화와 그 dn 의 파라메트릭 · 사건은 ECAD 항목이다", () => {
  const doc = {
    structural: {
      node_changes: [
        { cid: "c:1", op: "added", dn: "p:e1", nid_base: null, nid_target: "p:e1", ckey: null, label: "C1", kind: "component",
          domain: "ecad", correspondence_method: null, confidence: "medium", excluded_reason: "partial_scope" },
        { cid: "c:2", op: "removed", dn: "p:m1", nid_base: "p:m1", nid_target: null, ckey: null, label: "PLATE", kind: "part",
          domain: "mcad", correspondence_method: null, confidence: "medium", excluded_reason: null },
      ],
      edge_changes: [],
    },
    parametric: {
      node_params: [{ cid: "c:3", dn: "p:e1", attr: "height", before: 1, after: 2, delta: 1, flag: "changed", excluded_reason: null,
        caveat: "parser_differs" }],
      edge_params: [], materials: [], dims_delta: [], result_delta: [], rollup_delta: [],
    },
    semantic: { blocked_by: null, events: [
      { cid: "c:4", code: "part.added", change_kind: "count", subject: { dns: ["p:e1"], names: ["C1"] }, subject_key: "ck",
        confidence: "low", design_relevant: true, unconfirmed: false, excluded_reason: null, caveat: "parser_differs", text: "t" },
      { cid: "c:5", code: "part.removed", change_kind: "count", subject: { dns: ["p:m1"], names: ["PLATE"] }, subject_key: "ck",
        confidence: "medium", design_relevant: true, unconfirmed: false, excluded_reason: null, text: "t" },
    ] },
  };
  const rows = cmp.diffRows(doc);
  assert.deepEqual(rows.map((r) => [r.cid, r.layer, r.isEcad]), [
    ["c:1", "structural", true], ["c:2", "structural", false], ["c:3", "parametric", true], ["c:4", "semantic", true],
    ["c:5", "semantic", false],
  ]);
  assert.deepEqual(cmp.excludedCounts(rows), [{ reason: "partial_scope", isEcad: true, n: 1 }]);
});

test("대응 확정 본문 — stable 키와 서버가 준 pair_key, 하나라도 없으면 보내지 않는다", () => {
  const row = { a: "p:1", b: "p:9", a_stable: "st:x", b_stable: "st:y" };
  assert.deepEqual(cmp.pairDecision(row, "reject", "p-a|p-b"), {
    decision: "reject", scope: "pair", a_stable: "st:x", b_stable: "st:y", pair_key: "p-a|p-b",
  });
  assert.equal("a" in cmp.pairDecision(row, "confirm", "k"), false); // 노드 id 는 원장 열쇠가 아니다
  assert.equal(cmp.pairDecision({ ...row, b_stable: null }, "confirm", "p-a|p-b"), null);
  assert.equal(cmp.pairDecision(row, "confirm", null), null);
});

test("좌석 까닭 — ecad_absent 는 대상 종류마다 뜻이 다르고, 넷 · 배치 미룸에는 2단계 말", () => {
  assert.equal(tgt.seatReasonLabel("ecad_absent", "snap"), "보드 없음");
  assert.equal(tgt.seatReasonLabel("ecad_absent", "diff"), "1단계 비교는 ECAD 칸 변화를 보지 않는다");
  assert.equal(tgt.seatReasonLabel("ecad_nets_deferred", "snap"), "넷 · 배치가 필요해 ECAD 2단계까지 미룸");
  assert.equal(tgt.seatReasonLabel("tier_cap", "snap"), null);
  assert.equal(tgt.seatReasonLabel(null, "snap"), null);
});

test("좌석 조작 — 넘기기는 진행 전 · 실패 좌석, 되돌리기는 carried 만, 보류 · 끝난 좌석은 없음", () => {
  for (const status of ["pending", "assigned", "running", "failed"]) assert.deepEqual(tgt.seatActions({ status }), { skip: true, revert: false });
  assert.deepEqual(tgt.seatActions({ status: "carried" }), { skip: false, revert: true });
  for (const status of ["deferred", "done", "done_weak", "abstain", "skipped"]) {
    assert.deepEqual(tgt.seatActions({ status }), { skip: false, revert: false }, status);
  }
  assert.match(tgt.skipReasonProblem("   "), /까닭/);
  assert.equal(tgt.skipReasonProblem("담당 없음"), null);
});

test("마지막 신호 — 80초를 넘을 때만 강조, 신호가 없으면 '아직 신호 없음'", () => {
  const sig = (idle) => ({ panel_id: "p", panel_no: 3, started_at: 0, last_frame_at: idle === null ? null : 1, last_event_at: null,
    last_step: "2라운드", frames: 1, frame_idle_s: idle, event_idle_s: null });
  assert.deepEqual(tgt.signalView(sig(80)), { worker: "P3", text: "마지막 신호 80초 전", stale: false, step: "2라운드" });
  assert.equal(tgt.signalView(sig(81)).stale, true);
  assert.deepEqual(tgt.signalView(sig(null)), { worker: "P3", text: "아직 신호 없음", stale: false, step: "2라운드" });
  assert.equal(tgt.signalView(null), null);
  const w = tgt.workerSignalView({ agent_key: "pcb-1", call_kind: "verdict", unit_id: "u1", last_frame_at: 1, last_event_at: 1,
    frame_idle_s: 200, event_idle_s: 200 });
  assert.deepEqual(w, { worker: "pcb-1 · verdict · u1", text: "마지막 신호 200초 전", stale: true });
});

test("과제 메타 — 서버가 칸을 주지 않으면 모름, PATCH 답의 열은 글자(JSON) · 0/1 을 풀어 이긴다", () => {
  assert.equal(meta.parseProductRefs(undefined), undefined);
  assert.deepEqual(meta.parseProductRefs(null), []);
  assert.deepEqual(meta.parseProductRefs('[{"kind":"product_code","value":"PC-1"},{"kind":"bad","value":"x"}]'), [
    { kind: "product_code", value: "PC-1" },
  ]);
  assert.deepEqual(meta.parseProductRefs("not json"), []);
  const known = meta.knownMeta({ id: "p" }, null);
  assert.deepEqual(known, {});
  assert.equal(meta.noProductLink(known), null);
  const patched = meta.knownMeta({ id: "p" }, {
    classification: "confidential", lifecycle: "shipped", mcp_visibility: "private", corpus_excluded: 0, excluded_reason: null,
    product_code: null, product_refs_json: null,
  });
  assert.equal(patched.corpus_excluded, false);
  assert.equal(meta.noProductLink(patched), true);
  assert.equal(meta.noProductLink(meta.knownMeta({ product_refs_json: [{ kind: "ra_model", value: "M" }], product_code: null })), false);
});

test("조직 공개 토글 — 편집자 · 보기에게 잠기고, 역할을 모르면 잠그지 않는다(서버 403 이 막는다)", () => {
  assert.equal(meta.visibilityControl("editor", "private").locked, true);
  assert.match(meta.visibilityControl("editor", "private").lockReason, /소유자만/);
  assert.equal(meta.visibilityControl("viewer", null).locked, true);
  assert.equal(meta.visibilityControl("owner", "org").locked, false);
  assert.equal(meta.visibilityControl(null, undefined).locked, false);
  assert.equal(meta.visibilityControl("owner", undefined).known, false);
  assert.equal(meta.myRole([{ email: "a@b", role: "editor" }], "a@b"), "editor");
  assert.equal(meta.myRole(null, "a@b"), null);
});

test("홈 거름 — 칸을 주지 않는 서버에서는 걸지 않고(모르는 값으로 숨기지 않는다), 주면 건다", () => {
  const bare = [{ id: "1" }, { id: "2" }];
  assert.deepEqual(meta.homeFieldsAvailable(bare), { lifecycle: false, role: false, excluded: false, classification: false });
  assert.equal(meta.filterCards(bare, { lifecycle: "shipped", role: "owner", includeExcluded: false }).length, 2);
  const full = [
    { id: "1", lifecycle: "active", my_role: "owner", corpus_excluded: false },
    { id: "2", lifecycle: "shipped", my_role: "viewer", corpus_excluded: true },
  ];
  assert.deepEqual(meta.filterCards(full, { lifecycle: "", role: "", includeExcluded: false }).map((c) => c.id), ["1"]);
  assert.deepEqual(meta.filterCards(full, { lifecycle: "shipped", role: "", includeExcluded: true }).map((c) => c.id), ["2"]);
  assert.deepEqual(meta.filterCards(full, { lifecycle: "", role: "owner", includeExcluded: true }).map((c) => c.id), ["1"]);
  assert.deepEqual(meta.productRefsBody([{ kind: "product_code", value: " PC-1 " }, { kind: "ra_model", value: "  " }]), [
    { kind: "product_code", value: "PC-1" },
  ]);
  assert.equal(meta.productRefsBody([]), undefined);
  assert.match(meta.emailProblem("nobody"), /이메일/);
  assert.equal(meta.emailProblem("a@b.c"), null);
});
