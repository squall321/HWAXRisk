// 셀 격자의 순수 판정 — 칸 열쇠 · 쪽 행을 전문가 × 단위 격자로 · 칸의 짧은 말과 말풍선(포털 m3-frontend-request 3-2절)
import type { ReviewCellRow } from "../types";
import { cellStateLabel } from "./reviewView";

/** 거르기 분류의 길(셀 목록 route 쿼리) — 칩의 말. */
export const ROUTE_LABEL: Record<string, string> = {
  review: "검토",
  filtered: "거름",
  audit: "거름 표본",
  noinput: "입력 결손",
};

/** 칸 하나의 열쇠 — (단위, 전문가). 쪽 안에서 고르기 · 자세히에 쓴다. */
export function cellKey(row: Pick<ReviewCellRow, "unit_id" | "agent_key">): string {
  return `${row.unit_id}\u0000${row.agent_key}`;
}

/**
 * 쪽 행(서버가 검토 순서 → 단위 순번으로 준다)을 격자로 — 전문가는 처음 나온 차례 그대로, 단위는 순번 순이다. 쪽은 칸 수로
 * 끊기므로 첫 · 끝 전문가는 단위 일부만 있을 수 있다(빈 칸은 그 쪽에 없는 칸이다).
 */
export function cellMatrix(rows: ReviewCellRow[]): {
  agents: Array<{ agent_key: string; domain: string }>;
  units: Array<{ unit_id: string; unit_seq: number }>;
} {
  const agents: Array<{ agent_key: string; domain: string }> = [];
  const seenAgents = new Set<string>();
  const units = new Map<string, number>();
  for (const row of rows) {
    if (!seenAgents.has(row.agent_key)) {
      seenAgents.add(row.agent_key);
      agents.push({ agent_key: row.agent_key, domain: row.domain });
    }
    if (!units.has(row.unit_id)) units.set(row.unit_id, row.unit_seq);
  }
  return {
    agents,
    units: Array.from(units, ([unit_id, unit_seq]) => ({ unit_id, unit_seq })).sort(
      (a, b) => a.unit_seq - b.unit_seq || a.unit_id.localeCompare(b.unit_id),
    ),
  };
}

/** 칸의 짧은 말 — 상태 말에 표본 · 사람이 다시 연 칸 · 다시 연 횟수를 붙인다. */
export function cellShortLabel(row: ReviewCellRow): string {
  const marks = [
    row.route === "audit" ? "표본" : null,
    row.route_forced === "human_retry" ? "사람" : null,
    row.reopened_n > 0 ? `↺${row.reopened_n}` : null,
  ].filter(Boolean);
  const head = row.state === "no_input" ? "입력 결손" : cellStateLabel(row.state);
  return marks.length > 0 ? `${head} ${marks.join(" ")}` : head;
}

/** 칸 말풍선 — 거른 까닭 · 오류 · 사람의 처분 · 길을 한 줄씩(서버 글 그대로, 브라우저가 글로만 보인다). */
export function cellTitle(row: ReviewCellRow): string {
  const lines = [
    `${row.unit_id} · ${row.agent_key} — ${cellStateLabel(row.state)}(${row.state})`,
    row.filter_reason ? `거른 까닭: ${row.filter_reason}` : null,
    row.route ? `길: ${row.route}${row.route_forced ? ` · 거르지 않은 까닭 ${row.route_forced}` : ""}` : null,
    row.error_code ? `오류: ${row.error_code}${row.error ? ` — ${row.error}` : ""}` : null,
    row.decide_note ? `사람의 처분: ${row.decide_note}` : null,
  ].filter(Boolean);
  return lines.join("\n");
}
