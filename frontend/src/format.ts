// 표시용 값 변환 — 시각·비율·자유 JSON 을 화면 공통 형식으로 만든다(값을 해석하지 않고 형식만 바꾼다).
import type { JsonValue } from "./types";

/** epoch 초(또는 밀리초)를 지역 시각 문자열로. */
export function fmtEpoch(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  const ms = value > 1e12 ? value : value * 1000;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "-";
  return d.toLocaleString("ko-KR", { hour12: false });
}

/** 0~100 커버리지 백분율. */
export function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return `${Math.round(value)}%`;
}

export function fmtNum(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return Number.isInteger(value) ? String(value) : value.toFixed(digits);
}

/** 표 한 칸에 들어갈 자유 JSON — 스칼라는 그대로, 나머지는 한 줄 JSON. */
export function fmtCell(value: JsonValue | undefined): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

/** 원문 상자에 넣을 들여쓴 JSON. */
export function fmtJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** `Record<string, number>` 카운트를 한 줄로. */
export function fmtCounts(counts: Record<string, number> | null | undefined): string {
  if (!counts) return "-";
  const entries = Object.entries(counts);
  if (entries.length === 0) return "-";
  return entries.map(([k, v]) => `${k} ${v}`).join(" · ");
}
