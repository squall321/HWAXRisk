// ECAD 보드 찾기 · 붙이기 · 떼기의 순수 판정 — 카드 갈래 · 찾을 말 검사 · 거절 code 의 말 · 확인 글(포털 ecad-1031 화면 요청서 1 ~ 5절)
import { isApiError } from "./risk.api";
import type { AdapterEntry, EcadBoard, ProjectSource } from "../types";

/** 찾을 말 상한(routes.ECAD_QUERY_MAX) — 넘거나 비면 서버가 422 E100 이라 화면이 먼저 막는다. */
export const ECAD_QUERY_MAX = 200;
/** ODB 허브 job_id 꼴(adapters/ecad.JOB_ID_RE) — 붙이기는 후보 표에서 고른 이 값 하나만 보낸다. */
export const ODB_JOB_ID_RE = /^[0-9a-fA-F]{16}$/;

/** 찾을 말을 서버에 보내기 전에 본다 — 막을 까닭이 있으면 그 글, 없으면 null. */
export function boardQueryProblem(query: string): string | null {
  const q = query.trim();
  if (q === "") return "찾을 말을 적으세요 — 과제 · 모델 · 파일 이름이나 job_id 입니다.";
  if (q.length > ECAD_QUERY_MAX) return `찾을 말은 ${ECAD_QUERY_MAX}자까지입니다 — 지금 ${q.length}자.`;
  return null;
}

/**
 * ECAD 카드의 길(요청서 1절) — `GET /meta/adapters` 의 ecad 줄 status 로 가른다. ready 면 찾기 칸, unavailable 이면 운영자 몫
 * (게이트웨이에 ODB 허브 도구가 없다), planned 면 게이트웨이 도구 지도를 못 읽었다(잠시 뒤 다시). 발견을 아직 못 받았으면 unknown.
 */
export type EcadRoute = "ready" | "unavailable" | "planned" | "unknown";
export function ecadRoute(adapters: AdapterEntry[] | null | undefined): EcadRoute {
  const row = (adapters ?? []).find((a) => a.kind === "ecad");
  if (!row) return "unknown";
  if (row.status === "ready") return "ready";
  if (row.status === "unavailable") return "unavailable";
  if (row.status === "planned") return "planned";
  return "unknown";
}

/** 과제의 ECAD 카드(많아야 한 장 — 옛 일반 연결로 둘이 됐으면 서버가 앞의 것만 읽는다). */
export function ecadSource(sources: ProjectSource[] | null | undefined): ProjectSource | null {
  return (sources ?? []).find((s) => s.kind === "ecad") ?? null;
}

/** 사람이 읽는 보드 이름과 판 — '앞 보드 이름(판) → 새 보드 이름(판)' 확인 글에 쓴다. 이름이 없으면 job_id 로 말한다. */
export function boardLabel(board: Pick<EcadBoard, "name" | "revision" | "job_id"> | null | undefined): string {
  if (!board) return "보드 없음";
  const name = board.name ?? (board.job_id ? `job ${board.job_id}` : "이름 없는 보드");
  return `${name}(판 ${board.revision ?? "모름"})`;
}

/** 붙이기 확인 글(요청서 3절) — 이미 붙은 보드가 있을 때만 묻는다. 없으면 null(묻지 않고 붙인다). */
export function replaceConfirmText(current: EcadBoard | null | undefined, next: EcadBoard): string | null {
  if (!current) return null;
  return (
    `${boardLabel(current)} → ${boardLabel(next)} 로 바꿉니다. ` +
    "이미 동결된 스냅샷은 그대로이고 다음 캡처부터 새 보드를 읽습니다."
  );
}

/** 떼기 확인 글(요청서 4절). */
export const DETACH_CONFIRM_TEXT =
  "보드를 뗍니다. 이미 동결된 스냅샷은 그대로이고 다음 캡처부터 ECAD 가 빠집니다(스냅샷의 ECAD 는 결측 ecad_absent).";

/** 거절 뒤 화면이 덧붙일 다음 걸음 — 설정으로(내 PAT) · 다시 찾기 · 후보를 다시 보이기 · 없음(운영자 몫 · 입력). */
export type EcadNext = "settings" | "retry" | "candidates" | null;
export type EcadFailure = { title: string; next: EcadNext; detail?: string };

/**
 * 찾기 · 붙이기 · 떼기의 거절을 code 로 가른다(요청서 5절 표). 서버 글은 고칠 곳까지 말하므로 화면은 제목과 다음 걸음만 고르고
 * 글(`message`)은 글자 그대로 보인다. 모르는 code 는 null — 공용 배너(describeError)가 말한다. 404(내 과제가 아니다)도 공용이다.
 */
export function describeEcadError(err: unknown): EcadFailure | null {
  if (!isApiError(err)) return null;
  switch (err.code) {
    case "ecad_pat_absent":
    case "ecad_credential_absent": // 9bd5f48 전의 옛 판만 낸다 — 같은 안내다.
      return { title: "내 포털 PAT 가 없어 ODB 허브를 부르지 않았습니다.", next: "settings" };
    case "ecad_gateway_unreadable":
      return { title: "게이트웨이를 못 읽었습니다 — 잠시 뒤 다시 찾습니다.", next: "retry" };
    case "ecad_unavailable": {
      const missing = detailList(err.body, "tools_missing");
      return {
        title: "ODB 허브가 게이트웨이에 붙어 있지 않습니다 — 운영자 몫입니다.",
        next: null,
        detail: missing.length > 0 ? `빠진 도구 ${missing.join(" · ")}` : undefined,
      };
    }
    case "ecad_unreachable":
      return { title: "ODB 허브 호출이 실패했습니다.", next: "retry" };
    case "ecad_schema_drift":
      return { title: "ODB 허브 답의 꼴이 바뀌었습니다 — 운영자 몫입니다.", next: null };
    case "ecad_board_not_found":
      return { title: "그 보드를 찾지 못했습니다 — 후보에서 다시 고르세요.", next: "candidates" };
    case "E100":
      return { title: "입력을 확인하세요.", next: null };
    default:
      return null;
  }
}

/** 422 `ecad_board_not_found` 본문의 후보와 허브 글(detail 은 오류 본문 최상위에 펼쳐진다). 자동으로 고르지 않는다. */
export function notFoundCandidates(err: unknown): { candidates: EcadBoard[]; hub_message: string | null } | null {
  if (!isApiError(err) || err.code !== "ecad_board_not_found") return null;
  const body = (err.body ?? {}) as { candidates?: unknown; hub_message?: unknown };
  const candidates = Array.isArray(body.candidates) ? (body.candidates as EcadBoard[]) : [];
  return { candidates, hub_message: typeof body.hub_message === "string" ? body.hub_message : null };
}

function detailList(body: unknown, key: string): string[] {
  const value = body && typeof body === "object" ? (body as Record<string, unknown>)[key] : undefined;
  return Array.isArray(value) ? value.map(String) : [];
}
