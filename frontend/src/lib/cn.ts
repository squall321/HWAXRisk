// 클래스 합성 — 조건부 클래스(clsx)와 Tailwind 충돌 해소(tailwind-merge)를 한 함수로 둔다(shadcn 관례)
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** `cn("p-2", cond && "p-4")` → 뒤에 온 것이 이긴다. 조건부 스타일을 문자열 이어 붙이기로 하지 않는다. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
