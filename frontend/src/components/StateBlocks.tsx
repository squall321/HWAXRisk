// 화면 3종 상태(로딩·빈 상태·오류)와 '아직 준비 중' 배너 — 모든 화면이 같은 문구·모양을 쓰도록 여기서만 만든다.
import type { ReactNode } from "react";
import { Inbox, Loader2, Wrench } from "lucide-react";
import { describeError, isNotReady } from "../api/risk.api";
import { Banner, Button } from "../ui/primitives";

/** 세 상태가 공유하는 가운데 정렬 상자 — 셋이 같은 자리·같은 높이로 서야 화면이 덜컹거리지 않는다. */
function StateBox({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-8 text-center text-sm text-muted-foreground">
      {children}
    </div>
  );
}

export function LoadingBlock({ label = "불러오는 중." }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 px-4 py-8 text-sm text-muted-foreground"
         role="status" aria-busy="true">
      {/* 움직임을 줄이기로 한 사람에게는 돌지 않는다(기존 rr-spinner 의 prefers-reduced-motion 과 같은 처리). */}
      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

/**
 * 데이터가 없을 때가 기본이다 — 무엇을 하면 되는지까지 적는다.
 * `action` 에는 버튼·링크를 넣는다(첫 과제 만들기 등).
 */
export function EmptyBlock({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <StateBox>
      <Inbox className="size-5 opacity-50" aria-hidden="true" />
      <strong className="text-sm font-medium text-foreground">{title}</strong>
      {hint ? <span>{hint}</span> : null}
      {action ? <span className="mt-1">{action}</span> : null}
    </StateBox>
  );
}

/**
 * 오류 배너 한 줄. 404·501·not_implemented 는 자동으로 '아직 준비 중' 정보 톤이 된다.
 * 콘솔에는 아무것도 찍지 않는다(폴링 중 폭주 방지).
 */
export function ErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (error === null || error === undefined) return null;
  const { tone, title, detail } = describeError(error);
  return (
    <Banner tone={tone === "info" ? "info" : "error"} title={title} detail={detail}>
      {onRetry && !isNotReady(error) ? (
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          다시 시도
        </Button>
      ) : null}
    </Banner>
  );
}

/** 서버에 아직 없는 구역을 자리만 남겨 두는 블록(에러 배너 대신 쓸 때). */
export function NotReadyBlock({ what }: { what: string }) {
  return (
    <StateBox>
      <Wrench className="size-5 opacity-50" aria-hidden="true" />
      <strong className="text-sm font-medium text-foreground">{what} 은(는) 아직 준비 중입니다.</strong>
      <span>서버 경로가 붙으면 이 자리에 표시됩니다.</span>
    </StateBox>
  );
}
