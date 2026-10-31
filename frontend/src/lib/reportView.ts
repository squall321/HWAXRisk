// 보고서 쪽의 순수 판정 — 판의 계기 · 서술 정도의 말, 쪽 블록을 마크다운 줄로, 그 줄을 안전한 조각으로(포털 m3-frontend-request 3-7 · 5절)
import type { ReportPage } from "../types";

/** 보고서 판의 계기(rr_reports.trigger) 말 — 모르는 값은 그대로 보인다. */
export const TRIGGER_LABEL: Record<string, string> = {
  reviews_partial: "좁은 범위 검토 뒤(마감 범위 미완)",
  reviews_closed: "마감 범위 검토 끝",
  issues_closed: "쟁점 단계 끝",
  synth_done: "영역 요약 · 종합까지 끝",
  ack: "확인 · 확인 취소가 표기를 바꿈",
  manual: "사람이 다시 냄",
  level_up: "레벨 오름",
};

export function triggerLabel(trigger: string | null | undefined): string {
  if (!trigger) return "—";
  return TRIGGER_LABEL[trigger] ?? trigger;
}

/** 서술 정도 — full 이 아니면 '서술 일부 · 없음 — 표는 다 있다'(표 · 수는 늘 코드다). full 이면 null. */
export function narrativeNote(state: string | null | undefined): string | null {
  if (state === "full") return null;
  if (state === "partial") return "서술 일부 — 표는 다 있습니다(표 · 수는 늘 코드가 씁니다).";
  if (state === "none") return "서술 없음 — 표는 다 있습니다(표 · 수는 늘 코드가 씁니다).";
  return state ? `서술 ${state} — 표는 다 있습니다.` : null;
}

const BLOCK_ORDER = ["background", "results", "recommendation", "minutes"] as const;

/** 쪽 하나의 마크다운 줄 — 블록 차례대로 조각을 잇고 조각 안의 줄바꿈으로 나눈다(쪽을 이으면 part 전체와 같다). */
export function pageLines(page: ReportPage | null | undefined): string[] {
  if (!page) return [];
  const out: string[] = [];
  for (const block of BLOCK_ORDER) {
    for (const piece of page.blocks?.[block] ?? []) out.push(...String(piece).split("\n"));
  }
  return out;
}

/** 줄 하나의 꼴 — 제목 · 목록(들여쓰기 깊이) · 빈 줄 · 문단. */
export type MdLine =
  | { kind: "heading"; level: number; text: string }
  | { kind: "item"; depth: number; text: string }
  | { kind: "blank" }
  | { kind: "para"; text: string };

export function parseMdLine(line: string): MdLine {
  if (line.trim() === "") return { kind: "blank" };
  const heading = /^(#{1,6})\s+(.*)$/.exec(line);
  if (heading) return { kind: "heading", level: heading[1].length, text: heading[2] };
  const item = /^(\s*)[-*]\s+(.*)$/.exec(line);
  if (item) return { kind: "item", depth: Math.floor(item[1].replace(/\t/g, "  ").length / 2), text: item[2] };
  return { kind: "para", text: line };
}

/** 글 안의 굵게(**…**) · 고정폭(`…`) 조각 — 그 밖은 글이다. HTML 로 해석하지 않는다(그리는 쪽이 글 노드로만 쓴다). */
export type MdSpan = { kind: "text" | "strong" | "code"; text: string };

export function parseInline(text: string): MdSpan[] {
  const out: MdSpan[] = [];
  const re = /\*\*([^*]+?)\*\*|`([^`]+?)`/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push({ kind: "text", text: text.slice(last, m.index) });
    if (m[1] !== undefined) out.push({ kind: "strong", text: m[1] });
    else out.push({ kind: "code", text: m[2] });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

/**
 * 쪽을 받을 물음 — 첫 쪽은 판을 싣지 않고(지금 판), 둘째 쪽부터 첫 쪽의 판을 싣는다(그사이 새 판이 섰으면 409 report_version_moved 로
 * 쪽이 섞이지 않게). 쪽 번호는 1 이상이다.
 */
export function pageQuery(page: number, version: number | null): { page: number; version?: number } {
  const n = Math.max(1, Math.floor(page));
  return n === 1 || version === null ? { page: n } : { page: n, version };
}
