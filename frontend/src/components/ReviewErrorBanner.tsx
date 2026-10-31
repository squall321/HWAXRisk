// 카드 대조 화면들의 거절 배너 — 아는 code 는 제목과 다음 걸음(설정 · 다시 읽기)을 붙이고 서버 글은 글자 그대로 보인다
import { Link } from "react-router-dom";
import { isApiError } from "../api/risk.api";
import { describeReviewError } from "../api/reviewErrors";
import { ErrorBanner } from "./StateBlocks";
import { Banner, Button } from "../ui/primitives";

export function ReviewErrorBanner({ error, onReload }: { error: unknown; onReload?: () => void }) {
  if (error === null || error === undefined) return null;
  const known = describeReviewError(error);
  if (!known) return <ErrorBanner error={error} />;
  return (
    <Banner tone={known.next === "restart" ? "info" : "error"} title={known.title} detail={isApiError(error) ? error.message : undefined}>
      {known.next === "settings" ? (
        <Link to="/settings" className="text-sm underline underline-offset-4">
          설정에서 PAT 등록
        </Link>
      ) : null}
      {known.next === "reload" && onReload ? (
        <Button type="button" variant="outline" size="sm" onClick={onReload}>
          다시 읽기
        </Button>
      ) : null}
    </Banner>
  );
}
