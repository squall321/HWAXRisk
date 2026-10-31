// 잡 취소 확인 줄 — 한 번 누르면 곧바로 끝내지 않고, 취소한 잡은 재개되지 않으며 멈춰 두는 길은 일시정지라는 것을 말한 뒤에만 보낸다.
import { Banner, Button } from "../ui/primitives";

/**
 * 취소는 끝이다 — runner.cancel_job 은 잡을 cancelling → cancelled 로 닫고 재개는 멈춘(paused) 잡만 받는다. 며칠 도는 검토 잡을 '일시정지'
 * 옆 같은 모양 단추 한 번에 끝내지 않게 잡을 이름으로 부르고 확인받는다(과제 화면의 이양 · 폐기 확인과 같은 꼴).
 */
export function JobCancelConfirm({
  what,
  jobId,
  busy,
  note,
  onConfirm,
  onClose,
}: {
  /** 잡의 종류 말(검토 잡 · 패널 잡). */
  what: string;
  jobId: string;
  busy: boolean;
  /** 그 잡에만 붙는 말(다시 만들 때 드는 동의 따위). */
  note?: string;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Banner
      tone="warn"
      live="status"
      title={`${what} ${jobId} 을 취소합니다 — 되돌릴 수 없습니다.`}
      detail={`취소한 잡은 재개되지 않습니다 — 다시 돌리려면 새 잡을 만듭니다.${note ? ` ${note}` : ""} 잠시 세워 두려면 일시정지를 쓰세요(멈춘 잡은 재개됩니다).`}
    >
      <span className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="destructive" size="sm" disabled={busy} onClick={onConfirm}>
          잡 취소
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onClose}>
          그만두기
        </Button>
      </span>
    </Banner>
  );
}
