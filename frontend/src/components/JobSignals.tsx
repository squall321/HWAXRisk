// 도는 패널 · 검토 일꾼의 마지막 신호 줄 — 80초를 넘긴 것만 강조해 도는 것과 멈춘 것을 가른다(B34 486, 대상 화면)
import { Badge } from "./Badge";
import { SectionCard } from "./SectionCard";
import { Mono } from "../ui/primitives";
import { SIGNAL_STALE_S, signalView, workerSignalView } from "../lib/targetView";
import type { CoverageJob, CoverageReview, JobSignal } from "../types";

/**
 * 도는 패널의 마지막 신호(routes._live_signal — 그 패널이 지금 도는 동안에만 온다). 러너가 1분 간격으로 적어 건강한 패널도 80초
 * 안팎까지 가므로 80초를 넘을 때만 강조한다 — 도는 패널과 멈춘 패널이 둘 다 running 으로만 보이던 자리다(B34 486).
 * 도는 패널마다 한 줄이다(`signals` — 동시 2 잡은 둘까지, 패널 차례대로). `signals` 가 없는 응답은 `signal` 한 줄이다.
 */
export function JobSignalLine({ job }: { job: NonNullable<CoverageJob> }) {
  const signals = job.signals?.length ? job.signals : job.signal ? [job.signal] : [];
  if (signals.length === 0) {
    return (
      <span className="text-muted-foreground">
        {job.state === "running" ? "지금 도는 패널이 없습니다(패널 사이 · 자리 기다림)." : "—"}
      </span>
    );
  }
  if (signals.length === 1) return <PanelSignal signal={signals[0]} />;
  return (
    <span className="flex flex-col gap-1">
      {signals.map((signal) => (
        <PanelSignal key={signal.panel_id} signal={signal} />
      ))}
    </span>
  );
}

function PanelSignal({ signal }: { signal: JobSignal }) {
  const view = signalView(signal);
  if (!view) return null;
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Mono>{view.worker}</Mono>
      {view.stale ? (
        <Badge tone="warn" title={`${SIGNAL_STALE_S}초를 넘겼다 — 패널이 멈췄을 수 있다`}>
          {view.text}
        </Badge>
      ) : (
        <span>{view.text}</span>
      )}
      {view.step ? <span className="text-xs text-muted-foreground">단계 {view.step}</span> : null}
      {signal.advice ? <Badge tone="info">{signal.advice}</Badge> : null}
    </span>
  );
}

/**
 * 카드 대조 검토 잡의 일꾼별 마지막 신호(routes._review_job_payload — 도는 호출마다 한 줄). 80초를 넘은 일꾼만 강조한다 — 도는
 * 호출과 멈춘 호출을 가른다(B34 486). 검토 진행판의 나머지 칸은 M3 화면 요청서 2절의 몫이다.
 */
export function ReviewWorkers({ review }: { review: CoverageReview | null | undefined }) {
  const job = review?.job;
  if (!job || !job.signal) return null;
  const workers = job.signal.workers;
  return (
    <SectionCard title="검토 잡 — 일꾼별 마지막 신호" subtitle={`잡 ${job.id} · ${job.state} · 도는 호출 ${workers.length}개`}>
      {workers.length === 0 ? (
        <p className="m-0 text-sm text-muted-foreground">지금 도는 호출이 없습니다.</p>
      ) : (
        <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
          {workers.map((w, i) => {
            const view = workerSignalView(w);
            return (
              <li key={`${view.worker}#${i}`}>
                <span className="inline-flex flex-wrap items-center gap-2">
                  <Mono>{view.worker}</Mono>
                  {view.stale ? (
                    <Badge tone="warn" title={`${SIGNAL_STALE_S}초를 넘겼다 — 호출이 멈췄을 수 있다`}>
                      {view.text}
                    </Badge>
                  ) : (
                    <span>{view.text}</span>
                  )}
                  {w.last_step ? <span className="text-xs text-muted-foreground">단계 {w.last_step}</span> : null}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </SectionCard>
  );
}
