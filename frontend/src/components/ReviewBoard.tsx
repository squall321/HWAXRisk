// 카드 대조 검토 진행판 — 셀 · 전문가 셈, 거르기 · 입력 결손 · 처분 줄, 검토 잡 줄(단계 · 기다림 · 다시 연 셀 몫 · 호출)과 보류의 재개(동의) · 넘김(포털 m3-frontend-request 2 · 3-5절)
import { useEffect, useState } from "react";
import { riskApi } from "../api/risk.api";
import { reopenedOf } from "../api/reviewErrors";
import { Badge, JobStateBadge, LlmBadge, toneOf } from "./Badge";
import { KeyValueTable } from "./DataTable";
import { ReviewErrorBanner } from "./ReviewErrorBanner";
import { SectionCard, VerbatimBlock } from "./SectionCard";
import { Banner, Button, FormField, Input, Mono } from "../ui/primitives";
import {
  CELL_STATES,
  callsLine,
  cellStateLabel,
  consentAmountKey,
  dispositionsLine,
  disposeJobLine,
  filterLines,
  hitsLine,
  holdView,
  noinputLine,
  phaseLabel,
  reasonProblem,
  reopenedLine,
} from "../lib/reviewView";
import { fmtEpoch } from "../format";
import type { CoverageReview, ReopenedExtra, ReviewJob, ReviewScope } from "../types";

/** 셈 칩 한 줄 — 0 은 흐리게(서버가 센 0 이라 '모름' 이 아니다). */
function StateChips({ counts }: { counts: Record<string, number> }) {
  return (
    <span className="flex flex-wrap items-center gap-1">
      {Object.entries(counts).map(([state, n]) => (
        <Badge key={state} tone={n === 0 ? "muted" : toneOf(state === "na_irrelevant" ? "skipped" : state)} title={state}>
          {cellStateLabel(state)} {n}
        </Badge>
      ))}
    </span>
  );
}

function scopeText(scope: ReviewScope): string {
  const parts = [
    scope.tiers?.length ? `tier ${scope.tiers.join(" · ")}` : null,
    scope.domains?.length ? `영역 ${scope.domains.join(" · ")}` : null,
    scope.agents?.length ? `전문가 ${scope.agents.length}명` : null,
    scope.unit_ids?.length ? `단위 ${scope.unit_ids.length}개` : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "로스터 전원 × 검토 대상 단위 전부";
}

/** 동의를 기다리는 몫 — 셀 수와 추정 호출, 여유와 처음 추정을 그대로 보인다. */
function ConsentNumbers({ extra }: { extra: ReopenedExtra }) {
  return (
    <span>
      동의를 기다리는 다시 연 셀 {extra.unconsented.cells}개 · 호출 추정 {Math.round(extra.unconsented.calls_est)}회(여유{" "}
      {extra.allowance}회 · 처음 동의한 추정 {extra.expected}회 · 상한 {extra.max_calls}회).
    </span>
  );
}

/**
 * 검토 잡 한 줄과 조작. 보류는 `reopened_extra.hold` 로 가른다(holdView) — consent_extra 는 몫을 보이고 체크(미리 체크하지 않는다)한 뒤
 * `resume?consent=true`, max_calls 는 재개가 풀리지 않아 기다리는 셀 넘기기를 앞에 둔다. 일시정지 · 재개 · 취소는 잡 주인만이다.
 */
function ReviewJobPanel({ job, targetKey, onChanged }: { job: ReviewJob; targetKey: string; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  /** 동의 체크 — 체크한 그 몫의 열쇠(consentAmountKey). 몫이 바뀌면 체크는 비어 보인다(미리 체크된 동의가 되지 않게). */
  const [consentFor, setConsentFor] = useState<string | null>(null);
  const [skipping, setSkipping] = useState(false);
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<string[] | null>(null);
  const hold = holdView(job);
  const extra = job.progress?.reopened_extra ?? null;
  // 그냥 재개가 422 consent_required 로 돌아오면(그사이 몫이 넘쳤다) 그 답의 몫으로 동의를 받는다.
  const askedExtra = reopenedOf(error);
  const consentExtra = hold.resume === "consent" ? extra : askedExtra;
  const amountKey = consentExtra && (hold.resume === "consent" || askedExtra) ? consentAmountKey(job.id, consentExtra) : null;
  const consent = amountKey !== null && consentFor === amountKey;
  const workers = job.signal?.workers.length ?? 0;
  const calls = callsLine(job.progress?.calls, extra?.expected, workers);
  const reopened = reopenedLine(extra);
  const live = job.state === "queued" || job.state === "running";
  const problem = reasonProblem(reason, true);

  // 동의를 기다리는 몫이 없어지면(넘겼거나 이어 돈다) 체크를 걷는다 — 같은 크기의 몫으로 다시 멈춰도 체크된 채 열리지 않게.
  useEffect(() => {
    if (amountKey === null) setConsentFor(null);
  }, [amountKey]);

  async function act(action: "pause" | "cancel" | "resume" | "resume_consent") {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      if (action === "pause") await riskApi.pauseJob(job.id);
      else if (action === "cancel") await riskApi.cancelJob(job.id);
      else if (action === "resume") await riskApi.resumeJob(job.id);
      else await riskApi.resumeJob(job.id, { consent: true });
      setConsentFor(null);
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function skipWaiting(event: React.FormEvent) {
    event.preventDefault();
    if (problem) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const out = await riskApi.skipCells(targetKey, {
        filter: { job_id: job.id, state: "pending" },
        reason: reason.trim(),
      });
      setResult([
        `넘긴 셀 ${out.skipped ?? 0} · 손대지 않은 셀 ${out.not_failed}.`,
        disposeJobLine(out.job, "skip"),
        ...(hitsLine(out) ? [hitsLine(out) as string] : []),
      ]);
      setSkipping(false);
      setReason("");
      // 넘긴 몫에 준 체크는 그 몫과 함께 끝난다 — 다음 멈춤의 몫은 다시 동의받는다.
      setConsentFor(null);
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 flex flex-col gap-2">
      <ReviewErrorBanner error={error} onReload={onChanged} />
      {result ? <Banner tone="info" live="status" title={result[0]} detail={result.slice(1).join(" ")} /> : null}
      <KeyValueTable
        rows={[
          { label: "잡 id", hint: "job.id", value: <Mono>{job.id}</Mono> },
          {
            label: "상태",
            hint: "state · hold_code",
            value: (
              <span className="flex flex-wrap items-center gap-2">
                <JobStateBadge value={job.state} />
                {job.hold_code ? <Badge tone="warn">{job.hold_code}</Badge> : null}
                {job.llm === "claude" ? <LlmBadge llm={job.llm} /> : null}
              </span>
            ),
          },
          { label: "단계", hint: "phase", value: phaseLabel(job.phase) },
          { label: "자격", hint: "credential_email", value: job.credential_email ?? <span className="text-muted-foreground">—</span> },
          { label: "범위", hint: "scope", value: scopeText(job.scope) },
          {
            label: "호출",
            hint: "progress.calls",
            value: (
              <span className="flex flex-col gap-0.5">
                <span>{calls.head}</span>
                {calls.tail ? <span className="text-xs text-muted-foreground">{calls.tail}</span> : null}
                {calls.eta ? <span className="text-xs text-muted-foreground">{calls.eta}</span> : null}
              </span>
            ),
          },
          {
            label: "다시 연 셀",
            hint: "progress.reopened_extra",
            value: reopened ?? <span className="text-muted-foreground">없음</span>,
          },
          {
            label: "카드 묶음",
            hint: "progress.packs",
            value: job.progress?.packs && Object.keys(job.progress.packs).length > 0 ? (
              <span>
                {Object.entries(job.progress.packs)
                  .map(([k, v]) => `${k} ${v}`)
                  .join(" · ")}
              </span>
            ) : (
              <span className="text-muted-foreground">셈 전</span>
            ),
          },
        ]}
      />
      {job.waiting ? (
        <Banner
          tone="info"
          live="none"
          title={`기다림 — ${job.waiting.reason}${job.waiting.retry_at ? ` · 다시 볼 시각 ${fmtEpoch(job.waiting.retry_at)}` : ""}`}
          detail={job.waiting.note}
        />
      ) : null}
      {job.state === "paused" && job.error ? (
        <Banner tone="warn" live="none" title={`멈춤${job.hold_code ? ` — ${job.hold_code}` : ""}`} detail={job.error} />
      ) : null}
      {job.state !== "paused" && job.error ? (
        // 끝난 잡도 사람이 할 일(실패 셀 처분 따위)을 이 칸에 남긴다 — '오류' 로 부르지 않고 잡이 남긴 글로 보인다.
        <p className="m-0 text-sm text-muted-foreground">
          잡이 남긴 글: <span>{job.error}</span>
        </p>
      ) : null}
      {consentExtra && (hold.resume === "consent" || askedExtra) ? (
        <div className="flex flex-col gap-2 rounded-md border-l-[3px] border-warn bg-warn/10 p-3 text-sm">
          <ConsentNumbers extra={consentExtra} />
          <label className="flex flex-wrap items-center gap-2">
            <input type="checkbox" checked={consent} onChange={(e) => setConsentFor(e.target.checked ? amountKey : null)} />
            <span className="font-medium">이 몫의 호출에 동의하고 이어 돌립니다.</span>
          </label>
          <span className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" onClick={() => act("resume_consent")} disabled={busy || !consent}>
              동의하고 재개
            </Button>
            <span className="text-xs text-muted-foreground">동의하지 않으면 아래 '기다리는 셀 넘기기' 로 그 셀을 넘깁니다(차감 없음).</span>
          </span>
        </div>
      ) : null}
      {hold.resume === "blocked" ? (
        <p className="m-0 text-sm text-muted-foreground">
          호출 추정 합이 상한(HWAXRISK_REVIEW_MAX_CALLS)을 넘어 재개가 풀리지 않습니다 — 기다리는 셀을 넘기거나 운영자가 상한을 올린 뒤
          재개합니다.
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {hold.skipWaiting ? (
          <Button type="button" onClick={() => setSkipping((v) => !v)} disabled={busy}>
            기다리는 셀 넘기기…
          </Button>
        ) : null}
        {hold.resume === "plain" ? (
          <Button type="button" variant="outline" onClick={() => act("resume")} disabled={busy}>
            재개
          </Button>
        ) : null}
        {hold.resume === "blocked" ? (
          <Button type="button" variant="outline" disabled title="동의로 풀리지 않는다(409 max_calls)">
            재개(상한 넘음)
          </Button>
        ) : null}
        {live ? (
          <Button type="button" variant="outline" onClick={() => act("pause")} disabled={busy}>
            일시정지
          </Button>
        ) : null}
        {live || job.state === "paused" ? (
          <Button type="button" variant="outline" onClick={() => act("cancel")} disabled={busy}>
            취소
          </Button>
        ) : null}
      </div>
      {skipping ? (
        <form className="flex flex-col gap-2 rounded-md border border-border p-3" onSubmit={skipWaiting}>
          <p className="m-0 text-sm">
            이 잡에서 동의를 기다리는 셀을 넘깁니다(filter <code>{`{job_id, state: "pending"}`}</code>) — 그 셀은 차감 없이 skipped 가 되고
            보고서 '보지 못한 것' 에 사유와 함께 남습니다.
          </p>
          <FormField label="넘기는 사유" hint="필수 · 4~300자" error={reason !== "" && problem ? problem : undefined}>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} aria-label="넘기는 사유" />
          </FormField>
          <span className="flex flex-wrap items-center gap-2">
            <Button type="submit" size="sm" disabled={busy || problem !== null}>
              넘기기
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setSkipping(false)}>
              그만두기
            </Button>
          </span>
        </form>
      ) : null}
    </div>
  );
}

export function ReviewBoard({
  review,
  targetKey,
  onChanged,
}: {
  review: CoverageReview;
  targetKey: string;
  onChanged: () => void;
}) {
  const cells = review.cells;
  const job = review.job;
  return (
    <SectionCard
      title="검토 진행판"
      subtitle="셀 · 전문가 셈은 원장 값이고 품질 · 카드 폭포는 검토 잡이 60초마다 센 값입니다."
    >
      <KeyValueTable
        columns={1}
        rows={[
          {
            label: "셀",
            hint: "cells.by_state",
            value: (
              <span className="flex flex-col gap-1">
                <span>
                  {cells.total}칸 = 단위 {review.units} × 로스터 · 처분 전 실패 {cells.failed_open} · 범위 밖 대기 {cells.out_of_scope_pending}
                </span>
                <StateChips counts={Object.fromEntries(CELL_STATES.map((s) => [s, cells.by_state[s] ?? 0]))} />
              </span>
            ),
          },
          {
            label: "검토한 셀의 바탕",
            hint: "cells.by_basis",
            value: Object.entries(cells.by_basis)
              .map(([k, v]) => `${k} ${v}`)
              .join(" · "),
          },
          {
            label: "전문가",
            hint: "experts.by_state",
            value: `${review.experts.total}명 — ${Object.entries(review.experts.by_state)
              .map(([k, v]) => `${k} ${v}`)
              .join(" · ")}`,
          },
          {
            label: "거르기",
            hint: "filter",
            value: (
              <span className="flex flex-col gap-0.5">
                {filterLines(review.filter).map((line, i) => (
                  <span key={i}>{line}</span>
                ))}
                {review.filter.saved_calls_est > 0 ? (
                  <span className="text-xs text-muted-foreground">거른 셀이 아낀 호출 어림 {review.filter.saved_calls_est}회</span>
                ) : null}
              </span>
            ),
          },
          { label: "입력 결손", hint: "noinput", value: noinputLine(review.noinput) },
          { label: "처분", hint: "dispositions", value: dispositionsLine(review.dispositions) },
        ]}
      />
      {job ? (
        <ReviewJobPanel job={job} targetKey={targetKey} onChanged={onChanged} />
      ) : (
        <p className="m-0 mt-3 text-sm text-muted-foreground">검토 잡이 아직 없습니다 — 아래 '검토 잡 만들기' 에서 범위를 골라 시작합니다.</p>
      )}
      {review.quality?.text ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm text-muted-foreground">
            검토 품질(코드 계측{review.quality.computed_at ? ` · ${fmtEpoch(review.quality.computed_at)}` : ""}
            {review.quality.out_of_bounds.length > 0 ? ` · 기준 밖 ${review.quality.out_of_bounds.length}항` : ""})
          </summary>
          <VerbatimBlock className="mt-2" text={review.quality.text} label={review.quality.title ?? undefined} />
        </details>
      ) : null}
    </SectionCard>
  );
}
