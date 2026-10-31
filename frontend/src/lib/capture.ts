// 스냅샷 동결 폼의 순수 판정 — 기본 kinds · 409 두 갈래(source_unreachable · model_too_large)의 말 · 다시 보낼 본문(ecad-1031 §6)
import { isApiError } from "../api/risk.api";
import type { ModelTooLarge, ProjectSource, SnapshotCreate, SourceKind, SourceUnreachable } from "../types";

/** 폼의 kinds 선택지 순서. */
export const SNAPSHOT_KINDS: SourceKind[] = ["mcad", "dyna", "dyna_result", "ecad"];

/**
 * 동결 폼의 기본 kinds — 종전 기본은 mcad 하나라 보드를 붙여도 읽지 않았다. 과제에 ECAD 카드가 붙어 있으면 ecad 를 더한다
 * (요청서 6절). 사람이 체크를 바꾸면 그 값이 이긴다(이 함수는 처음 값만 정한다).
 */
export function defaultSnapshotKinds(sources: ProjectSource[] | null | undefined): SourceKind[] {
  const hasEcad = (sources ?? []).some((s) => s.kind === "ecad");
  return hasEcad ? ["mcad", "ecad"] : ["mcad"];
}

/** 동결 폼의 입력 — 입력란 그대로(다듬기는 본문을 지을 때 한다). */
export type SnapshotForm = { label: string; kinds: SourceKind[]; reportIds: string; detectId: string };

/**
 * 본문 — `report_ids` 는 수 목록이다(서버 칸이 list[int]). 수가 아닌 조각이 있으면 null 을 돌려 화면이 보내기 전에 막는다.
 * `allow_large` 는 싣지 않는다 — 그것은 거절된 본문에만 붙인다(allowLargeBody).
 */
export function snapshotBody(form: SnapshotForm): SnapshotCreate | null {
  const parts = form.reportIds.split(",").map((s) => s.trim()).filter(Boolean);
  if (parts.some((p) => !/^\d+$/.test(p))) return null;
  const body: SnapshotCreate = { kinds: form.kinds };
  if (form.label.trim() !== "") body.label = form.label.trim();
  if (parts.length > 0) body.report_ids = parts.map(Number);
  if (form.detectId.trim() !== "") body.detect_result_file_id = form.detectId.trim();
  return body;
}

/**
 * '그래도 동결' 의 본문 — 409 model_too_large 로 거절된 그 본문에 `allow_large` 만 더한다. 지금 폼 값으로 다시 짓지 않는다 — 거절 뒤에
 * 종류를 더 고르면(ECAD 보드는 부품 500 ~ 750) 사람이 본 적 없는 크기에 상한을 넘기게 된다(요청서 6절 '같은 요청에 allow_large').
 */
export function allowLargeBody(rejected: SnapshotCreate): SnapshotCreate {
  return { ...rejected, allow_large: true };
}

/** 동결 거절의 갈래 — 화면이 폼 안에서 처리하는 409 두 가지와 그 밖. */
export type SnapshotFailure =
  | { kind: "model_too_large"; detail: ModelTooLarge; message: string }
  | { kind: "kinds_excluded"; attached: SourceKind[]; message: string }
  | { kind: "ecad_unread"; reason: string | null; message: string }
  | { kind: "other" };

/** 409 를 code 로 가른다(문구로 가르지 않는다). detail 칸은 오류 본문 최상위에 펼쳐진다. */
export function describeSnapshotError(err: unknown): SnapshotFailure {
  if (!isApiError(err) || err.status !== 409) return { kind: "other" };
  const body = (err.body ?? {}) as Partial<ModelTooLarge> & SourceUnreachable;
  if (err.code === "model_too_large" && typeof body.leaf === "number") {
    return {
      kind: "model_too_large",
      message: err.message,
      detail: {
        leaf: body.leaf,
        leaf_mcad: Number(body.leaf_mcad ?? 0),
        leaf_ecad: Number(body.leaf_ecad ?? 0),
        interfaces: Number(body.interfaces ?? 0),
        max_leaf: Number(body.max_leaf ?? 0),
        max_interfaces: Number(body.max_interfaces ?? 0),
        budget_s: Number(body.budget_s ?? 0),
      },
    };
  }
  if (err.code === "source_unreachable") {
    if (Array.isArray(body.attached)) {
      const attached = body.attached.filter((k): k is SourceKind => SNAPSHOT_KINDS.includes(k as SourceKind));
      return { kind: "kinds_excluded", attached, message: err.message };
    }
    if (body.kind === "ecad") return { kind: "ecad_unread", reason: body.reason ?? null, message: err.message };
  }
  return { kind: "other" };
}

/**
 * 모델 크기 상한을 넘긴 것이 무엇인지 한 줄(요청서 6절 — 결정 3: 상한은 MCAD 리프와 ECAD 부품의 합이다).
 */
export function modelTooLargeLine(d: ModelTooLarge): string {
  const parts = [
    `리프 ${d.leaf}/${d.max_leaf}(MCAD 리프 ${d.leaf_mcad} · ECAD 부품 ${d.leaf_ecad})`,
    `계면 ${d.interfaces}/${d.max_interfaces}`,
  ];
  const over: string[] = [];
  if (d.leaf > d.max_leaf) {
    if (d.leaf_ecad > 0 && d.leaf_mcad > 0) over.push("리프 상한을 MCAD 리프와 ECAD 부품이 함께 넘겼습니다");
    else if (d.leaf_ecad > 0) over.push("리프 상한을 ECAD 부품만으로 넘겼습니다");
    else over.push("리프 상한을 MCAD 리프가 넘겼습니다");
  }
  if (d.interfaces > d.max_interfaces) over.push("계면 상한을 넘겼습니다");
  return `${parts.join(" · ")}${over.length > 0 ? ` — ${over.join(" · ")}.` : "."}`;
}
