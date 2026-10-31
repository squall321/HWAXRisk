// 쟁점 · 등록부의 순수 판정 — 결과 · 상태 · 유형 말, 쟁점 한 줄('제기 N명 · 반대 M명 → 쟁점 패널 결과'), 사람의 결정 버튼, 등록부의 '원래 — …' 줄(포털 m3-frontend-request 4 · 7절)
import type { IssueRow, RegistryRow } from "../types";

/** 쟁점 결과 — 보고서와 같은 낱말(유지 · 하향 · 상향 · 기각 · 판정 못 함). */
export const OUTCOME_LABEL: Record<string, string> = {
  upheld: "유지",
  downgraded: "하향",
  escalated: "상향",
  rejected: "기각",
  undetermined: "판정 못 함",
};

export const ISSUE_STATE_LABEL: Record<string, string> = {
  queued: "대기",
  planned: "편성",
  running: "도는 중",
  resolved: "끝",
  inconclusive: "결론 못 냄",
  untried_cap: "미토의",
  withdrawn: "후보에서 빠짐",
  skipped: "건너뜀",
};

/** 쟁점 상태의 색 — 끝은 ok, 결론 못 냄 · 미토의는 warn, 도는 것은 info, 나머지는 흐리게. */
export const ISSUE_STATE_TONE: Record<string, "ok" | "warn" | "info" | "muted"> = {
  resolved: "ok",
  inconclusive: "warn",
  untried_cap: "warn",
  queued: "muted",
  planned: "info",
  running: "info",
  skipped: "muted",
  withdrawn: "muted",
};

export const STATE_REASON_LABEL: Record<string, string> = {
  cap: "상한 밖",
  engine_fail: "엔진 실패",
  job_failed: "잡 실패",
  chain_cancelled: "사슬 취소",
  spec_parse_failed: "결정문을 못 읽음",
  no_decision: "결정 못 함",
  no_matching_atom: "맞는 원자 없음",
  human: "사람의 결정",
  reraised: "근거 바뀜",
};

export const ISSUE_TYPE_LABEL: Record<string, string> = {
  held_fail: "hold 가 가린 FAIL",
  solo_severe: "한 사람만 중대 이상",
  split_verdict: "같은 줄에 OK 둘 이상",
};

export const ISSUE_ROLE_LABEL: Record<string, string> = { raiser: "제기", opposer: "반대", adjacent: "인접" };

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

/**
 * 쟁점 한 줄(요청서 4절) — '제기 N명(판정별 분포) · 반대 M명 → 쟁점 패널 <결과>'. 결과가 없으면 '→ <상태>(<사유>)'. 패널이 하향 ·
 * 상향 · 유지로 덮었으면 그 뒤 값을 붙인다.
 */
export function issueLine(row: Pick<IssueRow, "distribution" | "outcome" | "outcome_json" | "state" | "state_reason">): string {
  const dist = distributionText(row.distribution.by_judgement_claimed);
  const head = `제기 ${row.distribution.raisers}명${dist ? `(${dist})` : ""} · 반대 ${row.distribution.opposers}명`;
  if (row.outcome) {
    const after = row.outcome_json?.severity_after
      ? ` ${row.outcome_json.severity_after}/${row.outcome_json.judgement_after ?? "—"}`
      : "";
    return `${head} → 쟁점 패널 ${labelOf(OUTCOME_LABEL, row.outcome)}${after}`;
  }
  return `${head} → ${labelOf(ISSUE_STATE_LABEL, row.state)}${row.state_reason ? `(${labelOf(STATE_REASON_LABEL, row.state_reason)})` : ""}`;
}

/** 편성 · 도는 쟁점은 바꾸지 않는다(409 issue_in_flight) — 버튼을 끈다. */
export const ISSUE_IN_FLIGHT: ReadonlySet<string> = new Set(["planned", "running"]);

/**
 * 사람의 결정 버튼(요청서 4절) — 상한 밖 · 끝난 쟁점에 '올리기' · '건너뛰기'. 편성 · 도는 쟁점은 둘 다 끈다. 이미 대기인 쟁점에
 * 올리기, 이미 건너뛴 쟁점에 건너뛰기는 하는 일이 없어 두지 않는다.
 */
export function issueActions(row: Pick<IssueRow, "state">): { queue: boolean; skip: boolean; inFlight: boolean } {
  const inFlight = ISSUE_IN_FLIGHT.has(row.state);
  return { queue: !inFlight && row.state !== "queued", skip: !inFlight && row.state !== "skipped", inFlight };
}

/** 쟁점 결정 사유(routes.put_issue) — 앞뒤 공백을 떼고 1~300자. */
export function issueReasonProblem(reason: string): string | null {
  const text = reason.trim();
  if (text === "") return "사유를 적으세요(300자 안).";
  if (text.length > 300) return `사유는 300자까지입니다 — 지금 ${text.length}자.`;
  return null;
}

/** 쟁점 행을 선정 순위대로(순위 없는 행은 끝, 같으면 id) — 서버는 쪽을 잇는 안정 열쇠(issue_id) 순으로 준다. */
export function byRank(rows: IssueRow[]): IssueRow[] {
  return [...rows].sort(
    (a, b) => (a.rank ?? Number.MAX_SAFE_INTEGER) - (b.rank ?? Number.MAX_SAFE_INTEGER) || a.issue_id.localeCompare(b.issue_id),
  );
}

/**
 * 쪽을 이을 때 — 새 쪽의 ledger_rev 가 앞 쪽과 다르면 그사이 원장이 바뀐 것이라 처음부터 다시 받는다(요청서 0절). 이을 수 있으면
 * 합친 행, 아니면 null.
 */
export function appendPage<T>(prev: { rev: string; rows: T[] } | null, page: { ledger_rev: string; rows: T[]; offset: number }): T[] | null {
  if (page.offset === 0) return page.rows;
  if (!prev || prev.rev !== page.ledger_rev) return null;
  return [...prev.rows, ...page.rows];
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
