// 쓰기 단추를 서버가 준 과제 역할(my_role)로 가르는 순수 판정과 그 까닭의 말 — 서버가 거절할 사람에게 단추를 미리 잠근다(OI-2)
import type { ProjectRole } from "../types";

/**
 * 단추가 요구하는 등급 — editor(계획서가 편집자에게 연 쓰기 — 소스 · 동결 · 요구 · 대상 · 잡 · 판정 · 등록부 · 쟁점 · 보고서 …),
 * owner(주인만 — 재동기 · 완결 잔여 확인 · 조직 공개 · confidential → internal · 멤버 · ECAD 보드).
 */
export type WriteNeed = "editor" | "owner";
export type WriteAccess = { allowed: boolean; reason: string | null };

const OPEN: WriteAccess = { allowed: true, reason: null };
const ROLE_WORD: Record<ProjectRole, string> = { owner: "소유자", editor: "편집자", viewer: "보기" };

export const VIEWER_REASON = "보기 권한이라 바꿀 수 없습니다 — 과제 소유자 · 편집자만 합니다.";
export const ADMIN_REASON = "관리자(risk_admin_roles)만 할 수 있습니다.";

/** 주인만의 쓰기를 소유자가 아닌 사람이 볼 때의 말 — 지금 역할을 덧붙인다. */
export function ownerReason(role: ProjectRole): string {
  return `과제 소유자만 할 수 있습니다(지금 ${ROLE_WORD[role]}).`;
}

/**
 * 이 역할이 그 쓰기를 할 수 있나. 역할을 모르면(null · 칸 없음 — 서버가 싣지 않았거나 구성원이 아닌 관리자) 잠그지 않는다 — 서버가
 * 가른다(관리자는 편집자 쓰기 · 이양 · 폐기를 받는다). 화면은 미리 알릴 뿐이고 서버의 거절은 그대로다.
 */
export function writeAccess(role: ProjectRole | null | undefined, need: WriteNeed = "editor"): WriteAccess {
  if (!role) return OPEN;
  if (need === "owner") return role === "owner" ? OPEN : { allowed: false, reason: ownerReason(role) };
  return role === "viewer" ? { allowed: false, reason: VIEWER_REASON } : OPEN;
}

/** 관리자 쓰기(사전 편집) — `/me.risk_admin` 이 거짓일 때만 잠근다(칸이 없으면 모름 — 잠그지 않는다). */
export function adminAccess(riskAdmin: boolean | null | undefined): WriteAccess {
  return riskAdmin === false ? { allowed: false, reason: ADMIN_REASON } : OPEN;
}

/** 두 과제에 걸친 쓰기(비교 만들기 · 쌍 대응 결정)는 두 과제 모두 편집자 이상이어야 한다 — 더 약한 역할로 가른다(모르는 쪽은 빼고 본다). */
export function weakerRole(...roles: Array<ProjectRole | null | undefined>): ProjectRole | null {
  const rank: Record<ProjectRole, number> = { viewer: 1, editor: 2, owner: 3 };
  const known = roles.filter((r): r is ProjectRole => r === "owner" || r === "editor" || r === "viewer");
  if (known.length === 0) return null;
  return known.reduce((a, b) => (rank[b] < rank[a] ? b : a));
}

/**
 * 등급 낮추기(confidential · 모름 → internal)는 주인만이다(plan §8.2.3 PATCH — 편집자는 403). 고른 등급이 낮추기이고 역할이 소유자가
 * 아니면 그 까닭, 아니면 null(역할을 모르면 잠그지 않는다).
 */
export function lowerClassificationLock(
  role: ProjectRole | null | undefined,
  draft: string,
  current: string | null | undefined,
): string | null {
  const lowering = draft === "internal" && current !== "internal";
  return lowering && role && role !== "owner" ? ownerReason(role) : null;
}
