// 스냅샷 화면의 순수 판정 — 강등 · 결측 표지 사전과 모으기 · 게이트 · 규칙의 세 값 표기 · 보드 묶음 · 노드 kind 거름 · 요구 여유 행
import type {
  DimNamed,
  EcadBoardAttrs,
  GateId,
  GateRecord,
  Gates,
  IrNode,
  JsonValue,
  ReqMarginRow,
  RuleHit,
  SnapshotIr,
  SnapshotState,
} from "../types";

/**
 * 강등 · 결측 표지 사전 — `missing.*`(bool 사전의 참인 열쇠)과 소스 `degraded[]` 코드를 한 자리에서 읽는다. 사전에 없는 코드는 서버
 * 글자 그대로 보인다. ECAD 표지 열둘과 결측 하나는 ecad-1031 화면 요청서 7절 표 그대로다.
 */
export const FLAG_LABEL: Record<string, string> = {
  mcad_absent: "mcad 소스 없음",
  ecad_absent: "ecad 소스 없음",
  dyna_absent: "dyna 소스 없음",
  dyna_result_absent: "dyna 결과 리포트 없음",
  iface_kinds_absent: "계면 kind 를 통째로 못 읽음",
  mcad_capture_failed: "붙은 mcad 소스를 못 읽음",
  dyna_capture_failed: "붙은 dyna 소스를 못 읽음",
  result_kind_mismatch: "결과 kind 가 서로 다름",
  world_transform_absent: "world 좌표 변환 없음",
  volume_null: "부피 값 없음",
  material_density_unsourced: "밀도 출처 없음",
  mcp_degraded: "REST 원문 없이 MCP 로만 캡처",
  no_world_transform: "어댑터가 world 좌표 변환을 얻지 못함",
  no_node_id: "소스 노드 id 없음(이름으로 대응)",
  volume_null_pre_d168: "부피·재질이 전부 null(재파싱 대상)",
  tol_config_unknown: "공차 설정 해시 없음",
  interfaces_truncated: "계면 목록 잘림",
  edges_truncated: "엣지 목록 잘림",
  components_truncated: "ecad 컴포넌트 목록 잘림",
  nets_truncated: "ecad 넷 목록 잘림",
  truncated_scan: "스캔 잘림",
  no_secid: "secid 없음",
  detect_absent: "detect 산출 없음",
  report_parts_mismatch: "리포트 파트명과 K파일 이름 불일치",
  unit_converted_mil: "mil 을 mm 로 환산",
  capture_partial: "부분 캡처(호출 일부 실패)",
  schema_drift: "소스 응답 꼴이 계약과 다름",
  // ECAD 1단계 표지(ecad-1031 §7) — '없다' 가 아니라 '아직 읽지 않는다 · 못 읽었다' 다.
  ecad_nets_deferred: "회로 넷 없음(2단계)",
  component_xy_deferred: "부품 좌표 · 회전 없음(2단계)",
  components_unclassified_omitted: "분류 안 된 부품 빠짐(저항 · 테스트 포인트 등)",
  outline_origin_unknown: "외곽 원점 모름(폭 · 높이 · 면적만)",
  stackup_material_unmatched: "적층 재료를 표준 적층과 못 맞춤",
  copper_weight_absent: "동박 무게 없음(두께만)",
  plane_type_unknown: "plane 구분 없음(없다는 뜻이 아니다)",
  odb_version_absent: "ODB 형식 판 없음",
  component_value_absent: "부품 값 없음",
  component_height_partial: "부품 높이 일부만(면마다 큰 부품 10개)",
  components_unavailable: "부품 목록을 못 읽음(부품 노드가 통째로 없다 — 부품 수는 미측정)",
  layers_unavailable: "층 목록을 못 읽음(층 노드가 통째로 없다)",
  ecad_capture_failed: "붙은 ECAD 보드를 못 읽음",
};

export type FlagChip = { code: string; where: string; label: string | null };

/**
 * 스냅샷의 강등 · 결측 표지 — `missing` 은 참인 열쇠만, 소스마다 `degraded` 는 그 소스 kind 를 붙여 모은다. 결측과 같은 코드를 소스가
 * 다시 말하면(예 ecad_absent) 한 번만 보인다.
 */
export function snapshotFlags(ir: Pick<SnapshotIr, "missing" | "sources"> | null | undefined): FlagChip[] {
  if (!ir) return [];
  const out: FlagChip[] = [];
  const seen = new Set<string>();
  for (const [code, on] of Object.entries(ir.missing ?? {})) {
    if (on !== true) continue;
    seen.add(code);
    out.push({ code, where: "missing", label: FLAG_LABEL[code] ?? null });
  }
  for (const source of ir.sources ?? []) {
    for (const code of source.degraded ?? []) {
      if (seen.has(code)) continue;
      seen.add(code);
      out.push({ code, where: String(source.kind), label: FLAG_LABEL[code] ?? null });
    }
  }
  return out;
}

/** 게이트 null 의 까닭(state.GATE_NULL_REASONS) — '위반' 이 아니라 '검문할 입력이 없었다' 다. */
export const GATE_NULL_REASON_LABEL: Record<string, string> = {
  mcad_absent: "mcad 소스 없음",
  capture_partial: "부분 캡처 — 계면 kind 를 못 읽음",
  unit_only: "단위 검문 입력 없음",
  warnings_unavailable: "MCP 로만 읽어 경고 목록이 없음",
  unit_unknown: "단위를 모름 — 차단은 유지",
};

/** 판정 표기 하나 — 색과 글. 화면은 색만 고르고 판정을 새로 만들지 않는다. */
export type Verdict3 = { tone: "ok" | "bad" | "muted"; label: string; title?: string };

/**
 * 게이트 한 칸의 표기(state._gate_word 와 같은 뜻) — pass · fail(건수) · 판정 불가(까닭). null 은 중립색이다(fail 이 아니다 —
 * mcp_degraded 스냅샷의 G3 · G4 가 붉게 보이던 자리). ack 가 붙어도 fail 은 fail 이고 '(ack)' 만 덧붙인다.
 */
export function gateVerdict(record: GateRecord | null | undefined): Verdict3 {
  if (!record) return { tone: "muted", label: "기록 없음" };
  if (record.pass === true) return { tone: "ok", label: "pass" };
  if (record.pass === null || record.pass === undefined) {
    // 까닭이 없는 자리(동결 답의 gates_summary 는 판정만 싣는다)에서는 까닭을 지어내지 않는다.
    const reason = record.reason ?? null;
    return {
      tone: "muted",
      label: reason ? `판정 불가(${reason})` : "판정 불가",
      title: (reason && GATE_NULL_REASON_LABEL[reason]) || "검문할 입력이 없었다 — fail 이 아니다",
    };
  }
  const count = record.count === null || record.count === undefined ? "" : String(record.count);
  return { tone: "bad", label: `fail${count ? `(${count})` : ""}${record.ack_by ? " · ack" : ""}` };
}

/** 게이트 순서대로 펼친다(사전 → 줄). 단일 스냅샷은 G1 ~ G6 이다. */
export const SNAP_GATE_IDS: GateId[] = ["G1", "G2", "G3", "G4", "G5", "G6"];
export function gateRows(gates: Gates | null | undefined): Array<{ id: GateId; record: GateRecord }> {
  const out: Array<{ id: GateId; record: GateRecord }> = [];
  for (const id of [...SNAP_GATE_IDS, "G7" as GateId]) {
    const record = gates?.[id];
    if (record) out.push({ id, record });
  }
  return out;
}

/** 그 게이트가 **fail** 인가 — pass 가 정말 false 일 때만이다(null 은 fail 이 아니다). */
export function gateFailing(gates: Gates | null | undefined, id: GateId): boolean {
  return gates?.[id]?.pass === false;
}

/**
 * ack 를 받을 수 있는 게이트인가(routes._gate_state) — fail 이고 차단(G6 · blocking)이 아닐 때만. 이미 ack 가 있으면 취소를 보인다.
 */
export function gateAckable(id: GateId, record: GateRecord): boolean {
  return record.pass === false && !record.blocking && id !== "G6" && id !== "G7";
}

/** 규칙 한 줄의 표기(state._rule_word) — 평가 불가(사유)는 중립색이고 pass 집계에 들지 않는다. */
export const NOT_EVALUABLE_LABEL: Record<string, string> = {
  source_absent: "그 규칙의 입력 소스가 없음",
  degraded: "소스가 강등돼 입력을 믿을 수 없음",
  truncated: "목록이 잘려 입력이 모자람",
};
export function ruleVerdict(hit: Pick<RuleHit, "pass" | "evaluable" | "not_evaluable_reason" | "found">): Verdict3 {
  if (hit.evaluable === false || hit.pass === null || hit.pass === undefined) {
    const reason = hit.not_evaluable_reason ?? "unknown";
    return { tone: "muted", label: `평가 불가(${reason})`, title: NOT_EVALUABLE_LABEL[reason] };
  }
  if (hit.pass) return { tone: "ok", label: "pass" };
  return { tone: "bad", label: `fail(${hit.found?.count ?? "?"}건)` };
}

/** 규칙 pass 집계 — 평가 불가는 분모에서 뺀다. */
export function ruleCounts(hits: RuleHit[]): { pass: number; fail: number; notEvaluable: number } {
  let pass = 0;
  let fail = 0;
  let notEvaluable = 0;
  for (const hit of hits) {
    if (hit.evaluable === false || hit.pass === null) notEvaluable += 1;
    else if (hit.pass) pass += 1;
    else fail += 1;
  }
  return { pass, fail, notEvaluable };
}

/** board 노드 하나(보드를 실은 스냅샷만). 없으면 null — 그때 '보드' 묶음을 그리지 않는다. */
export function boardNode(ir: Pick<SnapshotIr, "nodes"> | null | undefined): IrNode | null {
  return (ir?.nodes ?? []).find((n) => n.domain === "ecad" && n.kind === "board") ?? null;
}

/** 보드 묶음 한 줄 — `phase2` 면 '2단계' 표지를 붙인다(1단계에서는 늘 null 인 칸). 값이 null 이면 '없음' 이다(0 이 아니다). */
export type BoardRow = { label: string; hint: string; value: string | null; phase2?: boolean };

function num(value: JsonValue | undefined, digits: number, unit = ""): string | null {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  // 소수점 뒤의 끝 0 만 뗀다 — 소수점이 없는 글(자릿수 0 으로 반올림한 '100')의 0 을 떼면 '1' 이 된다.
  const text = Number.isInteger(value) ? String(value) : value.toFixed(digits).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  return `${text}${unit}`;
}

/** board 노드 attrs 를 사람 말 라벨로(요청서 7절). */
export function boardRows(node: IrNode): BoardRow[] {
  const a = node.attrs as Partial<EcadBoardAttrs> & Record<string, JsonValue | undefined>;
  const outline = (a.outline && typeof a.outline === "object" ? a.outline : {}) as {
    x_mm?: number | null;
    y_mm?: number | null;
    area_mm2?: number | null;
  };
  const x = num(outline.x_mm ?? undefined, 2);
  const y = num(outline.y_mm ?? undefined, 2);
  return [
    { label: "보드 이름", hint: "name", value: typeof a.name === "string" ? a.name : null },
    { label: "판", hint: "revision", value: typeof a.revision === "string" ? a.revision : null },
    { label: "두께", hint: "thickness", value: num(a.thickness ?? undefined, 3, " mm") },
    { label: "적층 판정", hint: "stackup_verdict", value: typeof a.stackup_verdict === "string" ? a.stackup_verdict : null },
    { label: "표준 적층", hint: "stackup_id", value: typeof a.stackup_id === "string" ? a.stackup_id : null },
    { label: "5종 층 두께 합", hint: "ecad_stackup_total", value: num(a.ecad_stackup_total ?? undefined, 3, " mm") },
    { label: "동박층 수", hint: "layer_count", value: num(a.layer_count ?? undefined, 0) },
    { label: "분류된 부품 수", hint: "n_components", value: num(a.n_components ?? undefined, 0) },
    { label: "배치 수(분류 안 된 부품 포함)", hint: "n_components_placed", value: num(a.n_components_placed ?? undefined, 0) },
    { label: "외곽 폭 × 높이", hint: "outline.x_mm · y_mm", value: x && y ? `${x} × ${y} mm` : null },
    { label: "외곽 면적", hint: "outline.area_mm2", value: num(outline.area_mm2 ?? undefined, 1, " mm²") },
    { label: "외곽 상자(원점)", hint: "outline_bbox", value: a.outline_bbox ? JSON.stringify(a.outline_bbox) : null, phase2: true },
    { label: "회로 넷 수", hint: "n_nets", value: num(a.n_nets ?? undefined, 0), phase2: true },
    { label: "ODB 형식 판", hint: "odb_version", value: typeof a.odb_version === "string" ? a.odb_version : null, phase2: true },
  ];
}

/** 노드 표의 kind 거름 — 있는 kind 와 그 수(많은 순). 보드 한 장에 노드가 수백 ~ 2,000 개 더해진다. */
export function nodeKindCounts(nodes: IrNode[]): Array<{ kind: string; n: number }> {
  const counts = new Map<string, number>();
  for (const node of nodes) counts.set(node.kind, (counts.get(node.kind) ?? 0) + 1);
  return Array.from(counts, ([kind, n]) => ({ kind, n })).sort((a, b) => b.n - a.n || a.kind.localeCompare(b.kind));
}

/** 노드 거름 — kind 가 비면 전부, 찾을 말은 nid · 이름 · 정규 이름 · ckey · dn 에서 찾는다. */
export function filterNodes(nodes: IrNode[], kind: string, query: string): IrNode[] {
  const needle = query.trim().toLowerCase();
  return nodes.filter((n) => {
    if (kind !== "" && n.kind !== kind) return false;
    if (needle === "") return true;
    return [n.nid, n.label, n.name_norm, n.canon_key, n.ckey ?? "", n.dn ?? ""].some((v) =>
      String(v ?? "").toLowerCase().includes(needle),
    );
  });
}

/**
 * 요구 여유 행(`sig:req.margin`, requirements.compute_req_signals) — 서버가 margin 오름차순(미측정은 맨 뒤)으로 준다. 동결이 요구를
 * 대조해 상태에 싣고 요구를 고치면 그 과제 스냅샷의 상태를 다시 센다(10-31 risk-flow). 신호가 상태에 없으면 null 이다 — 그 전에 언
 * 스냅샷이고 과제의 요구를 고치기 전이다. 그때 화면은 그 사실을 보인다(값을 지어내지 않는다).
 */
export function marginRows(state: Pick<SnapshotState, "signals"> | null | undefined): ReqMarginRow[] | null {
  const signal = state?.signals?.["req.margin"];
  if (!signal) return null;
  return Array.isArray(signal.value) ? (signal.value as unknown as ReqMarginRow[]) : [];
}

/** 명명 치수의 값 칸 — null 이면 까닭(null_reason)을 말한다. */
export function dimValue(dim: DimNamed): string {
  if (dim.value === null || dim.value === undefined) return dim.null_reason ? `미측정(${dim.null_reason})` : "미측정";
  return `${dim.value}${dim.unit ? ` ${dim.unit}` : ""}`;
}
