// 잠긴 쓰기 단추 곁의 한 줄 까닭 — 보기 · 주인만의 일을 서버가 거절하기 전에 말한다(OI-2, 까닭은 lib/access.ts 가 짓는다)
import { Lock } from "lucide-react";
import type { WriteAccess } from "../lib/access";

/** 잠기지 않았으면 아무것도 그리지 않는다. 단추의 title 에도 같은 글을 둔다 — 마우스를 올린 사람과 화면을 읽는 사람이 같은 말을 듣는다. */
export function LockNote({ access }: { access: WriteAccess }) {
  if (access.allowed || !access.reason) return null;
  return (
    <p className="m-0 inline-flex items-center gap-1.5 text-xs text-muted-foreground" role="note">
      <Lock className="size-3.5 shrink-0" aria-hidden="true" />
      <span>{access.reason}</span>
    </p>
  );
}
