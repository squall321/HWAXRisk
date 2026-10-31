// 완결 판정의 순수 판정 — 잔여 확인 상태 말 · 확인 · 취소 버튼, 영역 깊이 표, 내려간 레벨의 말, 확인 사유 검사(포털 m3-frontend-request 6절)
import type { ClosureCells, DepthRow, Qualifier } from "../types";

/** 잔여의 확인 상태 말 — 막음 잔여만 확인을 받는다. 확인 뒤 잔여 집합이 바뀌면 낡는다(다시 막는다). */
export function ackStateText(q: Pick<Qualifier, "blocking" | "acked" | "ack">): string {
  if (q.ack?.state === "valid") return "확인됨";
  if (q.ack?.state === "stale") return "확인 낡음 — 잔여가 바뀌어 다시 막습니다";
  if (q.ack?.state === "revoked") return q.blocking ? "확인 취소됨 — 막습니다" : "확인 취소됨";
  return q.blocking ? "확인 전 — 막습니다" : "표기만(확인 필요 없음)";
}

/** 확인 버튼 — 막음이고 유효한 확인이 없는 잔여. */
export function canAck(q: Pick<Qualifier, "blocking" | "acked">): boolean {
  return q.blocking && !q.acked;
}

/** 확인 취소 버튼 — 취소되지 않은 확인(유효 · 낡음)이 있을 때. 취소는 행을 지우지 않고 표기한다. */
export function canRevoke(q: Pick<Qualifier, "ack">): boolean {
  return q.ack !== undefined && q.ack.state !== "revoked";
}

/** 확인 사유(closure.ack_residual) — 앞뒤 공백을 떼고 1~300자. */
export function ackReasonProblem(reason: string): string | null {
  const text = reason.trim();
  if (text === "") return "확인에는 사유가 필요합니다(300자 안).";
  if (text.length > 300) return `사유는 300자까지입니다 — 지금 ${text.length}자.`;
  return null;
}

/** 내려간 계산의 말(요청서 6절) — 지금 계산이 저장 레벨보다 낮으면 '지금 계산 X — 저장 레벨은 내려가지 않는다'. */
export function regressedNote(c: Pick<ClosureCells, "regressed" | "level_current">): string | null {
  return c.regressed ? `지금 계산 ${c.level_current} — 저장 레벨은 내려가지 않는다.` : null;
}

/** 영역 깊이 줄 — 모자란 영역(카드 없는 영역은 면제)을 가른다. 영역 이름 순. */
export function depthRows(depth: Record<string, DepthRow> | null | undefined): Array<DepthRow & { domain: string; short: boolean }> {
  return Object.entries(depth ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([domain, row]) => ({ ...row, domain, short: row.exempt === undefined && row.have < row.need }));
}

/** 잔여를 막음 · 표기로 가른 수 — 머리의 한 줄. */
export function residualCounts(qualifiers: Qualifier[]): { blocking: number; unacked: number; marks: number } {
  const blocking = qualifiers.filter((q) => q.blocking);
  return {
    blocking: blocking.length,
    unacked: blocking.filter((q) => !q.acked).length,
    marks: qualifiers.length - blocking.length,
  };
}
