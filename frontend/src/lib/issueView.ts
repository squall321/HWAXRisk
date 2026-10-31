// 등록부 쟁점 칸의 순수 판정 — 쟁점 패널 결과 말 · 판정별 분포 한 줄 · 덮은 행의 '원래 — 제기 N명 → 쟁점 패널 결과' 줄(포털 m3-frontend-request 7절)
import type { RegistryRow } from "../types";

/** 쟁점 결과 — 보고서와 같은 낱말(유지 · 하향 · 상향 · 기각 · 판정 못 함). */
export const OUTCOME_LABEL: Record<string, string> = {
  upheld: "유지",
  downgraded: "하향",
  escalated: "상향",
  rejected: "기각",
  undetermined: "판정 못 함",
};

export function labelOf(map: Record<string, string>, value: string | null | undefined): string {
  if (!value) return "—";
  return map[value] ?? value;
}

/** 판정별 분포 한 줄 — 'FAIL 9 · WARNING 3'(무거운 판정 먼저). 비면 null. */
export function distributionText(dist: Record<string, number> | null | undefined): string | null {
  const order = ["FAIL", "WARNING", "undetermined", "OK"];
  const entries = Object.entries(dist ?? {}).filter(([, n]) => n > 0);
  if (entries.length === 0) return null;
  entries.sort(([a], [b]) => (order.indexOf(a) === -1 ? 9 : order.indexOf(a)) - (order.indexOf(b) === -1 ? 9 : order.indexOf(b)));
  return entries.map(([k, n]) => `${k} ${n}`).join(" · ");
}

/** 등록부 행이 쟁점 패널 결과를 얹었나(issue_state 가 결과 낱말) — 그 낱말. */
export function registryIssueOutcome(row: Pick<RegistryRow, "issue_state">): string | null {
  return row.issue_state && row.issue_state in OUTCOME_LABEL ? row.issue_state : null;
}

/**
 * 등록부 행의 '원래 — 제기 N명(FAIL a · WARNING b) → 쟁점 패널 <결과>'(요청서 7절 · D-34 덮되 분포를 남긴다). 쟁점 패널이 덮은 행은
 * 덮기 전 값(before_issue)으로, 기각처럼 덮지 않은 결과는 지금 분포로 센다. 쟁점 결과가 없으면 null.
 */
export function registryOverlayLine(row: Pick<RegistryRow, "issue_state" | "merged" | "support_experts">): string | null {
  const outcome = registryIssueOutcome(row);
  if (!outcome) return null;
  const before = row.merged.before_issue;
  const raisers = before ? before.support_experts : row.support_experts;
  const dist = distributionText((before ? before.distribution : row.merged.distribution)?.by_judgement_claimed);
  return `원래 — 제기 ${raisers ?? "?"}명${dist ? `(${dist})` : ""} → 쟁점 패널 ${OUTCOME_LABEL[outcome]}`;
}
