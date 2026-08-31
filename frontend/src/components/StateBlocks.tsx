// 화면 3종 상태(로딩·빈 상태·오류)와 '아직 준비 중' 배너 — 모든 화면이 같은 문구·모양을 쓰도록 여기서만 만든다.
import type { ReactNode } from "react";
import { describeError, isNotReady } from "../api/risk.api";

export function LoadingBlock({ label = "불러오는 중." }: { label?: string }) {
  return (
    <div className="rr-state" role="status" aria-busy="true">
      <span className="rr-spinner" aria-hidden="true" />
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
    <div className="rr-state rr-state-empty">
      <strong>{title}</strong>
      {hint ? <span className="rr-muted">{hint}</span> : null}
      {action ? <span className="rr-state-action">{action}</span> : null}
    </div>
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
    <div className={tone === "info" ? "rr-banner rr-banner-info" : "rr-banner rr-banner-error"} role="alert">
      <span className="rr-banner-title">{title}</span>
      <span className="rr-banner-detail">{detail}</span>
      {onRetry && !isNotReady(error) ? (
        <button type="button" className="rr-btn rr-btn-quiet" onClick={onRetry}>
          다시 시도
        </button>
      ) : null}
    </div>
  );
}

/** 서버에 아직 없는 구역을 자리만 남겨 두는 블록(에러 배너 대신 쓸 때). */
export function NotReadyBlock({ what }: { what: string }) {
  return (
    <div className="rr-state rr-state-empty">
      <strong>{what} 은(는) 아직 준비 중입니다.</strong>
      <span className="rr-muted">서버 경로가 붙으면 이 자리에 표시됩니다.</span>
    </div>
  );
}
