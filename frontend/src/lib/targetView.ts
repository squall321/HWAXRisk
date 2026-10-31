// 대상 화면의 순수 판정 — 좌석 까닭 code 의 사람 말(ECAD 의존 영역) · 사람이 옮길 수 있는 좌석 · 도는 패널의 마지막 신호(ecad-1031 §9 · B34 143 · 486)
import type { CoverageStatus, JobSignal, ReviewWorkerSignal, Seat } from "../types";

/**
 * 좌석 `reason` code 의 사람 말 — code 는 그대로 보이고 이 말을 덧붙인다. `ecad_absent` 는 대상 종류마다 뜻이 다르다(요청서 9절).
 * 스냅샷 대상은 보드가 없다는 뜻이고, diff 대상은 1단계 비교가 ECAD 칸 변화를 보지 않아 ECAD 의존 영역을 모두 미룬 것이다.
 * `ecad_nets_deferred` 는 결정 2(10-31) — pwr · rf 는 넷 · 배치가 필요해 ECAD 2단계까지 미룬다.
 */
export function seatReasonLabel(reason: string | null | undefined, targetKind: string): string | null {
  switch (reason) {
    case "ecad_absent":
      return targetKind === "diff" ? "1단계 비교는 ECAD 칸 변화를 보지 않는다" : "보드 없음";
    case "ecad_nets_deferred":
      return "넷 · 배치가 필요해 ECAD 2단계까지 미룸";
    default:
      return null;
  }
}

/** 사람이 넘길(skipped) 수 있는 좌석 상태(planner.ALLOWED_TRANSITIONS 에서 skipped 로 가는 칸). */
const SKIPPABLE: ReadonlySet<CoverageStatus> = new Set<CoverageStatus>(["pending", "assigned", "running", "failed"]);

/**
 * 좌석 한 줄에 열 수 있는 사람의 조작(routes.put_coverage) — 넘기기(skipped, 사유 필수)와 carried 되돌리기(pending)다. 보류
 * (deferred)는 되돌리기로 풀지 않는다(보류 풀기는 따로다). 끝난 좌석(done · skipped …)은 옮길 수 없다.
 */
export function seatActions(seat: Pick<Seat, "status">): { skip: boolean; revert: boolean } {
  return { skip: SKIPPABLE.has(seat.status), revert: seat.status === "carried" };
}

/** 넘기기 사유 — 앞뒤 공백을 떼고 비면 보내지 않는다(서버는 빈 사유를 422 E100 으로 거절한다). */
export function skipReasonProblem(reason: string): string | null {
  return reason.trim() === "" ? "넘기는 까닭을 적으세요 — 사유 없는 넘김은 저장되지 않습니다." : null;
}

/**
 * 러너는 1분 간격으로 신호를 적으므로(runner.PROGRESS_WRITE_INTERVAL_S) 건강한 패널도 마지막 프레임이 80초 안팎까지 간다. 그래서
 * 80초를 넘었을 때만 강조한다(포털 change-request-8-10 server-setup 486 · B34).
 */
export const SIGNAL_STALE_S = 80;

/** 도는 패널의 마지막 신호 한 줄 — 초는 서버 시계로 잰 값이다(화면 시계를 쓰지 않는다). */
export function signalView(signal: JobSignal | null | undefined): {
  worker: string;
  text: string;
  stale: boolean;
  step: string | null;
} | null {
  if (!signal) return null;
  const worker = signal.panel_no !== null && signal.panel_no !== undefined ? `P${signal.panel_no}` : signal.panel_id;
  const idle = signal.frame_idle_s;
  if (idle === null || idle === undefined) {
    return { worker, text: "아직 신호 없음", stale: false, step: signal.last_step || null };
  }
  return {
    worker,
    text: `마지막 신호 ${idle}초 전`,
    stale: idle > SIGNAL_STALE_S,
    step: signal.last_step || null,
  };
}

/** 카드 대조 검토 잡의 일꾼 한 명 — 누구(전문가 · 호출 종류 · 단위)와 마지막 신호. 80초를 넘을 때만 강조한다. */
export function workerSignalView(worker: ReviewWorkerSignal): { worker: string; text: string; stale: boolean } {
  const who = [worker.agent_key, worker.call_kind, worker.unit_id].filter(Boolean).join(" · ") || "일꾼";
  const idle = worker.frame_idle_s;
  if (idle === null || idle === undefined) return { worker: who, text: "아직 신호 없음", stale: false };
  return { worker: who, text: `마지막 신호 ${idle}초 전`, stale: idle > SIGNAL_STALE_S };
}
