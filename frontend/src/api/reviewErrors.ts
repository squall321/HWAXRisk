// 카드 대조 · 쟁점 · 종합 보고서 · 완결 확인의 거절을 code 로 가른다 — 제목과 다음 걸음만 화면이 고르고 서버 글은 그대로 보인다(포털 m3-frontend-request 0 ~ 6절)
import { isApiError } from "./risk.api";
import type { CallsEstimate, ReopenedExtra } from "../types";

/** 거절 뒤 화면이 덧붙일 다음 걸음 — 설정(내 PAT) · 동의 받기 · 다시 읽기 · 처음 쪽부터 · 없음. */
export type ReviewNext = "settings" | "consent" | "reload" | "restart" | null;
export type ReviewFailure = { title: string; next: ReviewNext };

/**
 * 검토 잡 만들기 · 셀 처분 · 재개 · 보류 풀기 · 쟁점 결정 · 보고서 · 확인의 거절(요청서 표). 모르는 code 는 null — 공용 배너
 * (describeError)가 말한다. 404 는 '없음', 403 은 '권한 없음' 이고(0절 규칙) 그것도 공용이다.
 */
export function describeReviewError(err: unknown): ReviewFailure | null {
  if (!isApiError(err)) return null;
  switch (err.code) {
    // 동의 · 상한(3-1 · 3-3 · 3-5)
    case "consent_required":
      return { title: "호출 추정이 동의 문턱을 넘습니다 — 추정을 보고 동의해야 진행합니다.", next: "consent" };
    case "review_too_large":
      return { title: "호출 추정이 잡 하나의 상한을 넘습니다 — 범위를 나눠 돌립니다.", next: null };
    case "max_calls":
      return { title: "이 잡의 호출 추정 합이 상한을 넘어 동의로는 풀리지 않습니다.", next: null };
    // 검토 잡 만들기(3-1 — M2 그대로)
    case "review_disabled":
      return { title: "이 박스는 카드 대조 검토가 꺼져 있습니다 — 운영자 몫입니다.", next: null };
    case "review_job_exists":
      return { title: "이 대상에 살아 있는 검토 잡이 있습니다.", next: "reload" };
    case "review_in_flight":
      return { title: "끝난 잡의 호출이 아직 돌고 있습니다 — 잠시 뒤 다시 합니다.", next: "reload" };
    case "panel_job_running":
      return { title: "이 대상에 살아 있는 패널 잡이 있습니다.", next: null };
    case "repersist_pending":
      return { title: "다시 앉히기를 기다리는 패널이 있습니다.", next: null };
    case "units_absent":
      return { title: "검토 단위가 서지 않았습니다.", next: null };
    case "scope_invalid":
      return { title: "범위에 이 대상에 없는 값이 있습니다.", next: null };
    case "scope_empty":
      return { title: "범위에 드는 셀이 없습니다.", next: null };
    case "pat_unavailable":
      return { title: "내 포털 PAT 가 없어 검토 잡을 세우지 못했습니다.", next: "settings" };
    // 셀 처분(3-3 · 3-4) · 보류 풀기(3-6)
    case "cells_selector_invalid":
      return { title: "고른 셀이 이 대상의 격자에 없거나 거름 칸이 틀렸습니다.", next: "reload" };
    case "reason_required":
      return { title: "사유가 필요합니다.", next: null };
    case "job_live":
      return { title: "이 대상에 도는 잡이 있어 보류를 풀지 않습니다 — 그 잡이 끝난 뒤 풉니다.", next: null };
    // 쟁점(4절)
    case "issue_in_flight":
      return { title: "편성 · 도는 쟁점은 바꾸지 않습니다.", next: "reload" };
    // 보고서(5절)
    case "report_absent":
      return { title: "이 대상에는 종합 보고서 판이 아직 없습니다.", next: null };
    case "report_version_moved":
      return { title: "그사이 보고서 판이 바뀌었습니다 — 처음 쪽부터 다시 받습니다.", next: "restart" };
    case "flow_mismatch":
      return { title: "패널 대상에는 종합 보고서 판이 없습니다 — 통합 보고서를 봅니다.", next: null };
    case "project_purged":
      return { title: "폐기된 과제의 대상에는 보고서 판을 세우지 않습니다.", next: null };
    // 완결 확인(6절)
    case "residual_changed":
      return { title: "그사이 잔여가 바뀌었습니다 — 다시 읽고 확인합니다.", next: "reload" };
    case "ack_not_allowed":
      return { title: "확인으로 넘길 수 있는 막음 잔여가 아닙니다.", next: "reload" };
    case "role_insufficient":
      return { title: "권한이 모자랍니다.", next: null };
    default:
      return null;
  }
}

function body(err: unknown): Record<string, unknown> {
  if (!isApiError(err)) return {};
  const value = err.body;
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

/** 422 consent_required · 409 review_too_large 의 추정(detail calls_estimate — 오류 본문 최상위에 펼쳐진다). 없으면 null. */
export function estimateOf(err: unknown): CallsEstimate | null {
  if (!isApiError(err) || (err.code !== "consent_required" && err.code !== "review_too_large")) return null;
  const value = body(err).calls_estimate;
  if (!value || typeof value !== "object") return null;
  const e = value as Partial<CallsEstimate>;
  if (typeof e.expected !== "number") return null;
  return { low: Number(e.low ?? 0), expected: e.expected, high: Number(e.high ?? 0), basis: String(e.basis ?? "") };
}

/** 재개 거절(422 consent_required · 409 max_calls)의 다시 연 셀 몫. 없으면 null. */
export function reopenedOf(err: unknown): ReopenedExtra | null {
  if (!isApiError(err) || (err.code !== "consent_required" && err.code !== "max_calls")) return null;
  const value = body(err).reopened_extra;
  return value && typeof value === "object" ? (value as ReopenedExtra) : null;
}

/** 409 report_version_moved 의 {version, asked}. 없으면 null. */
export function versionMovedOf(err: unknown): { version: number; asked: number } | null {
  if (!isApiError(err) || err.code !== "report_version_moved") return null;
  const b = body(err);
  return typeof b.version === "number" && typeof b.asked === "number" ? { version: b.version, asked: b.asked } : null;
}

/** 409 residual_changed 의 지금 값 {item, basis_hash, basis_n}. 없으면 null. */
export function residualChangedOf(err: unknown): { item: string; basis_hash: string; basis_n: number } | null {
  if (!isApiError(err) || err.code !== "residual_changed") return null;
  const b = body(err);
  return typeof b.basis_hash === "string"
    ? { item: String(b.item ?? ""), basis_hash: b.basis_hash, basis_n: Number(b.basis_n ?? 0) }
    : null;
}

/** 쪽 번호 밖(422 E100)의 pages_total — 0 이면 그 part 에 쪽이 없다. 아니면 null. */
export function pagesTotalOf(err: unknown): number | null {
  if (!isApiError(err) || err.code !== "E100") return null;
  const value = body(err).pages_total;
  return typeof value === "number" ? value : null;
}
