// 비교 화면의 순수 판정 — 비교 가능성 줄 · ECAD 한 줄 · 제외 사유의 말 · '파서 세대 다름' · 3층 항목을 한 표의 줄로(ecad-1031 §8 · B34 107)
import type { Comparability, DiffDoc, DiffLayer, JsonValue, SameAsPair, SameAsPairDecision } from "../types";

/** §3.3.6 excluded_reason 사전. 값은 서버 문자열 그대로 두고 뜻만 붙인다. */
export const EXCLUDED_LABEL: Record<string, string> = {
  tol_differs: "두 스냅샷의 공차 설정이 다름",
  tol_unknown: "공차 설정을 읽지 못함",
  result_kind_differs: "결과 kind 가 다름",
  sim_params_differ: "해석 파라미터가 다름",
  unit_scale: "단위·축척 불일치",
  partial_scope: "부분 검출 범위 밖",
  suspect_coords: "좌표계 의심",
  null_one_side: "한쪽 값이 없음",
  sameas_pending: "대응 미확정",
  bridge_stale: "메시 다리(bridge)가 낡음",
  capture_partial: "한쪽 캡처가 부분 · 실패",
  source_drift: "소스 응답 꼴이 바뀜",
  truncated: "목록이 잘림",
};

/**
 * 제외 사유의 말 — ECAD 항목의 partial_scope 는 '부분 검출 범위' 가 아니라 '한쪽 스냅샷에만 보드' 다(요청서 8절).
 */
export function excludedLabel(reason: string, isEcad: boolean): string {
  if (isEcad && reason === "partial_scope") return "한쪽 스냅샷에만 보드";
  if (isEcad && reason === "capture_partial") return "한쪽 보드를 온전히 읽지 못함";
  return EXCLUDED_LABEL[reason] ?? "사전에 없는 사유입니다.";
}

const ECAD_SIDE_LABEL: Record<string, string> = { present: "보드 있음", absent: "보드 없음", failed: "못 읽음 · 부분" };

/** 비교 가능성의 ECAD 한 줄(요청서 8절) — 두 쪽의 상태와 견주지 않은 까닭. 서버가 ECAD 칸을 주지 않으면 null. */
export function ecadComparabilityLine(comp: Partial<Comparability> | null | undefined): {
  sides: string;
  note: string | null;
  phase1Note: string | null;
} | null {
  const ecad = comp?.ecad;
  if (!ecad) return null;
  const side = (v: string) => ECAD_SIDE_LABEL[v] ?? v;
  const sides = `기준 ${side(ecad.base)} · 비교 대상 ${side(ecad.target)}`;
  let note: string | null = null;
  if (ecad.excluded_reason === "partial_scope") {
    note =
      "한쪽 스냅샷에만 보드가 있습니다 — ECAD 는 견주지 않았습니다. 앞 리비전에도 보드를 붙여 다시 캡처하면 견줍니다.";
  } else if (ecad.excluded_reason === "capture_partial") {
    note = "한쪽 보드를 온전히 읽지 못했습니다 — ECAD 는 견주지 않았습니다.";
  } else if (ecad.excluded_reason) {
    note = `ECAD 는 견주지 않았습니다(${ecad.excluded_reason}).`;
  }
  const bothPresent = ecad.base === "present" && ecad.target === "present";
  const phase1Note = bothPresent ? "1단계 비교는 ECAD 부품 · 층의 추가 · 삭제만 봅니다(칸 변화 없음)." : null;
  return { sides, note, phase1Note };
}

/**
 * '파서 세대 다름'(B34 107 · plan §3.3.6) — 소스 앱 판(app_version_parity) · 어댑터 세대(adapter_parity) · ECAD 어댑터 세대
 * (ecad.adapter_parity) 가운데 하나라도 **거짓**이면 참이다. null(모름)은 다름이 아니다.
 */
export function parserGenerationDiffers(comp: Partial<Comparability> | null | undefined): boolean {
  if (!comp) return false;
  return comp.app_version_parity === false || comp.adapter_parity === false || comp.ecad?.adapter_parity === false;
}

/** 무엇이 다른지 한 줄 — 배지의 title 로 싣는다. */
export function parserGenerationNote(comp: Partial<Comparability> | null | undefined): string {
  const parts: string[] = [];
  if (comp?.app_version_parity === false) parts.push("소스 앱 판이 다름(app_version_parity)");
  if (comp?.adapter_parity === false) parts.push("어댑터 세대가 다름(adapter_parity)");
  if (comp?.ecad?.adapter_parity === false) parts.push("ECAD 어댑터 세대가 다름(ecad.adapter_parity)");
  return parts.length > 0
    ? `${parts.join(" · ")} — 수치 변화의 일부가 파서 차이일 수 있습니다.`
    : "파서 세대가 같습니다.";
}

/** parity 한 칸의 표기 — true 같음 · false 다름 · null 모름(잴 입력이 없었다). */
export function parityWord(value: boolean | null | undefined): { tone: "ok" | "bad" | "muted"; label: string } {
  if (value === true) return { tone: "ok", label: "같음" };
  if (value === false) return { tone: "bad", label: "다름" };
  return { tone: "muted", label: "모름" };
}

/** 3층을 한 표로 그릴 줄 — 서버 항목을 그대로 옮기고 화면이 판정을 새로 만들지 않는다. */
export type DiffRow = {
  cid: string;
  layer: DiffLayer;
  part: string;
  code: string;
  subject: string;
  before: JsonValue;
  after: JsonValue;
  delta: JsonValue;
  excluded_reason: string | null;
  caveat: string | null;
  isEcad: boolean;
  text: string | null;
};

/** ECAD 노드만으로 이뤄진 dn — 구조층의 ECAD 노드 변화에서 모은다(파라메트릭 항목이 ECAD 인지 가르는 데 쓴다). */
export function ecadDns(doc: Pick<DiffDoc, "structural">): Set<string> {
  return new Set(doc.structural.node_changes.filter((c) => c.domain === "ecad").map((c) => c.dn));
}

/** diff 본문의 3층을 표 줄로 편다(rr_diff.v1 — structural · parametric · semantic). */
export function diffRows(doc: DiffDoc): DiffRow[] {
  const ecad = ecadDns(doc);
  const rows: DiffRow[] = [];
  for (const c of doc.structural.node_changes) {
    rows.push({
      cid: c.cid, layer: "structural", part: "node", code: `node.${c.op}`, subject: `${c.label} · ${c.kind}`,
      before: c.nid_base, after: c.nid_target, delta: null, excluded_reason: c.excluded_reason ?? null,
      caveat: c.caveat ?? null, isEcad: c.domain === "ecad", text: c.text ?? null,
    });
  }
  for (const c of doc.structural.edge_changes) {
    rows.push({
      cid: c.cid, layer: "structural", part: "edge", code: `edge.${c.op}`, subject: `${c.dn_a} ↔ ${c.dn_b ?? "—"}`,
      before: c.kind_from, after: c.kind_to, delta: null, excluded_reason: c.excluded_reason ?? null, caveat: null,
      isEcad: c.kind_family === "net", text: c.text ?? null,
    });
  }
  const params: Array<[string, keyof DiffDoc["parametric"]]> = [
    ["node", "node_params"], ["edge", "edge_params"], ["material", "materials"], ["dim", "dims_delta"],
    ["result", "result_delta"],
  ];
  for (const [part, key] of params) {
    for (const p of doc.parametric[key] as DiffDoc["parametric"]["node_params"]) {
      rows.push({
        cid: p.cid, layer: "parametric", part, code: p.flag ? `${part}.${p.flag}` : part,
        subject: [p.name ?? p.dn ?? p.eid ?? "", p.attr ?? p.field ?? p.metric ?? ""].filter(Boolean).join(" · "),
        before: p.before, after: p.after, delta: p.delta ?? null, excluded_reason: p.excluded_reason ?? null,
        caveat: p.caveat ?? null, isEcad: p.dn !== undefined && ecad.has(p.dn), text: p.text ?? null,
      });
    }
  }
  for (const e of doc.semantic.events) {
    const dns = e.subject?.dns ?? [];
    rows.push({
      cid: e.cid, layer: "semantic", part: "event", code: e.code, subject: (e.subject?.names ?? []).join(" · "),
      before: null, after: null, delta: null, excluded_reason: e.excluded_reason ?? null, caveat: e.caveat ?? null,
      isEcad: dns.length > 0 && dns.every((dn) => ecad.has(dn)), text: e.text,
    });
  }
  return rows;
}

/** 제외 사유별 수 — 항목은 diff 에 남고 의미 사건만 생기지 않는다(§3.3.6). ECAD 항목은 그 말로 따로 센다. */
export function excludedCounts(rows: DiffRow[]): Array<{ reason: string; isEcad: boolean; n: number }> {
  const acc = new Map<string, { reason: string; isEcad: boolean; n: number }>();
  for (const row of rows) {
    if (!row.excluded_reason) continue;
    const key = `${row.excluded_reason}|${row.isEcad}`;
    const cur = acc.get(key) ?? { reason: row.excluded_reason, isEcad: row.isEcad, n: 0 };
    cur.n += 1;
    acc.set(key, cur);
  }
  return Array.from(acc.values());
}

/**
 * 쌍 원장의 열쇠 — 두 과제 id 를 정렬해 '|' 로 잇는다(GET /sameas 가 원장을 읽는 열쇠이고, 빠지면 서버 글이 이 꼴을 말한다). 과제 id 를
 * 하나라도 모르면 null 이다.
 */
export function samePairKey(baseProjectId: string | null | undefined, targetProjectId: string | null | undefined): string | null {
  if (!baseProjectId || !targetProjectId) return null;
  return [baseProjectId, targetProjectId].sort().join("|");
}

/**
 * 대응 확정 · 거부 본문 한 줄 — stable 키로 보낸다(행의 `a` · `b` 는 노드 id 라 원장 열쇠가 아니다). stable 키가 없는 행(한쪽 노드가 없다)
 * 이나 쌍 열쇠를 모를 때는 null 이다(보내지 않는다 — 보내면 400 이거나 엉뚱한 열쇠로 적힌다).
 */
export function pairDecision(
  pair: Pick<SameAsPair, "a_stable" | "b_stable">,
  decision: "confirm" | "reject",
  pairKey: string | null,
): SameAsPairDecision | null {
  if (!pair.a_stable || !pair.b_stable || !pairKey) return null;
  return { decision, scope: "pair", a_stable: pair.a_stable, b_stable: pair.b_stable, pair_key: pairKey };
}
