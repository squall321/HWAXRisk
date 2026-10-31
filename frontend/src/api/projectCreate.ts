// 과제 만들기(`POST /projects`)의 서버 거절을 그 칸의 말로 옮긴다 — code 로만 가르고 문구로 가르지 않는다.
import { isApiError } from "./risk.api";

export type ProjectField = "classification" | "code" | "predecessor";

/**
 * 칸 하나에 붙일 수 있는 거절(routes.create_project) — 등급 빠짐(422 `classification_required`) · 같은 code(409 `E409`) ·
 * 앞 과제 없음(404 `E404` — 남의 과제도 같은 답이다). 그 밖(401 · 어휘 밖 E100 · 5xx)은 null 이고 배너가 말한다.
 */
export function projectCreateFieldError(err: unknown): { field: ProjectField; message: string } | null {
  if (!isApiError(err)) return null;
  switch (err.code) {
    case "classification_required":
      return { field: "classification", message: "등급을 고르세요 — 반출 경계라서 등록할 때 사람이 정합니다." };
    case "E409":
      return { field: "code", message: err.message };
    case "E404":
      return { field: "predecessor", message: err.message };
    default:
      return null;
  }
}
