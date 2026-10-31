// 카드 대조 검토 잡 만들기 — 범위(tier · 영역 · 전문가 · 단위) · 메모, 동의 문턱을 넘으면 추정을 보이고 동의를 받아 다시 보낸다(포털 m3-frontend-request 3-1절)
import { useMemo, useState } from "react";
import { isApiError, riskApi } from "../api/risk.api";
import { estimateOf } from "../api/reviewErrors";
import { ReviewErrorBanner } from "./ReviewErrorBanner";
import { SectionCard } from "./SectionCard";
import { KeyValueTable } from "./DataTable";
import { Banner, Button, FormField, FormGrid, Input, Mono } from "../ui/primitives";
import { LIVE_STATES, reviewJobBody } from "../lib/reviewView";
import type { ReviewJobForm } from "../lib/reviewView";
import { fmtEpoch } from "../format";
import type { CallsEstimate, CoverageReview, ReviewJobCreated } from "../types";

const TIERS = ["A", "B", "C"] as const;

/** 추정 한 덩이 — 기대 · 낮은 끝 · 높은 끝과 한 줄 설명(basis)을 글자 그대로. */
export function EstimateBlock({ estimate }: { estimate: CallsEstimate }) {
  return (
    <span className="flex flex-col gap-1">
      <span>
        호출 추정 기대 <strong>{estimate.expected.toLocaleString("ko-KR")}회</strong> · 낮은 끝 {estimate.low.toLocaleString("ko-KR")} · 높은
        끝 {estimate.high.toLocaleString("ko-KR")}
      </span>
      <span className="text-xs text-muted-foreground">{estimate.basis}</span>
    </span>
  );
}

export function ReviewJobFormCard({
  targetKey,
  review,
  onChanged,
}: {
  targetKey: string;
  review: CoverageReview;
  onChanged: () => void;
}) {
  const [tiers, setTiers] = useState<string[]>([]);
  const [domains, setDomains] = useState<string[]>([]);
  const [agents, setAgents] = useState("");
  const [unitIds, setUnitIds] = useState("");
  const [memo, setMemo] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  /** 동의 문턱을 넘어 돌아온 추정 — 이것이 있으면 동의 체크가 열린다. */
  const [asked, setAsked] = useState<CallsEstimate | null>(null);
  const [created, setCreated] = useState<ReviewJobCreated | null>(null);

  const allDomains = useMemo(() => Array.from(new Set(review.order.map((r) => r.domain))).sort(), [review.order]);
  const live = review.job !== null && LIVE_STATES.has(review.job.state);
  const tooLarge = estimateOf(error);

  function toggle(list: string[], value: string, set: (next: string[]) => void) {
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
    // 범위가 바뀌면 앞선 추정 · 동의는 맞지 않는다 — 다시 받는다.
    setAsked(null);
    setConsent(false);
  }

  function changed<T>(set: (v: T) => void) {
    return (v: T) => {
      set(v);
      setAsked(null);
      setConsent(false);
    };
  }

  async function start(withConsent: boolean) {
    const form: ReviewJobForm = { tiers, domains, agents, unitIds, memo, consent: withConsent && consent };
    setBusy(true);
    setError(null);
    setCreated(null);
    try {
      const out = await riskApi.createReviewJob(targetKey, reviewJobBody(form));
      setCreated(out);
      setAsked(null);
      // 다음 잡은 다시 동의받는다 — 체크를 남겨 두면 다음 잡에 미리 체크된 동의가 된다.
      setConsent(false);
      onChanged();
    } catch (err) {
      const estimate = estimateOf(err);
      if (estimate && isApiError(err) && err.code === "consent_required") {
        // 아무것도 바꾸기 전에 온 거절이다 — 추정을 보이고 동의를 받아 consent:true 로 다시 보낸다.
        setAsked(estimate);
        setConsent(false);
      } else {
        setError(err);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <SectionCard
      title="검토 잡 만들기"
      subtitle="범위를 비우면 로스터 전원 × 검토 대상 단위 전부입니다. 칸끼리는 AND 이고 빠진 칸은 전부입니다."
    >
      {live ? (
        <Banner
          tone="info"
          live="none"
          title={`살아 있는 검토 잡(${review.job?.id})이 있어 새 잡을 세우지 않습니다.`}
          detail="그 잡이 끝나거나 취소된 뒤 만듭니다(서버도 409 review_job_exists 로 거절합니다)."
        />
      ) : null}
      <ReviewErrorBanner error={error} onReload={onChanged} />
      {tooLarge ? (
        <p className="m-0 mb-3 text-sm">
          <EstimateBlock estimate={tooLarge} />
        </p>
      ) : null}
      <fieldset className="m-0 flex flex-col gap-3 border-0 p-0" disabled={live || busy}>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-xs font-medium text-muted-foreground">
            tier <span className="font-normal opacity-75">scope.tiers</span>
          </span>
          {TIERS.map((t) => (
            <label key={t} className="flex items-center gap-1">
              <input type="checkbox" checked={tiers.includes(t)} onChange={() => toggle(tiers, t, setTiers)} />
              {t}
            </label>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="text-xs font-medium text-muted-foreground">
            영역 <span className="font-normal opacity-75">scope.domains</span>
          </span>
          {allDomains.length === 0 ? <span className="text-muted-foreground">검토 순서가 비었습니다.</span> : null}
          {allDomains.map((d) => (
            <label key={d} className="flex items-center gap-1">
              <input type="checkbox" checked={domains.includes(d)} onChange={() => toggle(domains, d, setDomains)} />
              {d}
            </label>
          ))}
        </div>
        <FormGrid>
          <FormField label="전문가" hint="scope.agents · 쉼표로 여럿">
            <Input value={agents} onChange={(e) => changed(setAgents)(e.target.value)} placeholder="비우면 전부" />
          </FormField>
          <FormField label="단위" hint={`scope.unit_ids · 쉼표로 여럿 · 검토 대상 단위 ${review.units}개`}>
            <Input value={unitIds} onChange={(e) => changed(setUnitIds)(e.target.value)} placeholder="비우면 전부" />
          </FormField>
          <FormField label="메모" hint="user_memo">
            <Input value={memo} onChange={(e) => setMemo(e.target.value)} />
          </FormField>
        </FormGrid>
        {asked ? (
          <div className="flex flex-col gap-2 rounded-md border-l-[3px] border-warn bg-warn/10 p-3 text-sm">
            <span className="font-medium">호출 추정이 동의 문턱을 넘습니다 — 아무것도 바꾸지 않았습니다.</span>
            <EstimateBlock estimate={asked} />
            <label className="flex flex-wrap items-center gap-2">
              <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              <span className="font-medium">이 추정({asked.expected.toLocaleString("ko-KR")}회)으로 검토 잡을 세우는 데 동의합니다.</span>
            </label>
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          {asked ? (
            <Button type="button" onClick={() => start(true)} disabled={live || busy || !consent}>
              동의하고 시작
            </Button>
          ) : (
            <Button type="button" onClick={() => start(false)} disabled={live || busy}>
              검토 잡 시작
            </Button>
          )}
          {asked && !consent ? <span className="text-sm text-muted-foreground">동의에 체크해야 시작할 수 있습니다.</span> : null}
        </div>
      </fieldset>
      {created ? (
        <div className="mt-3">
          <KeyValueTable
            rows={[
              { label: "잡 id", hint: "job_id", value: <Mono>{created.job_id}</Mono> },
              {
                label: "범위",
                hint: "cells_in_scope · experts_in_scope",
                value: `셀 ${created.cells_in_scope} / 격자 ${created.cells_total} · 전문가 ${created.experts_in_scope}명 · 단위 ${created.units}개`,
              },
              { label: "호출 추정", hint: "calls_estimate", value: <EstimateBlock estimate={created.calls_estimate} /> },
              {
                label: "자격",
                hint: "credential",
                value: `${created.credential.kind} · ${created.credential.email} · 만료 ${fmtEpoch(created.credential.exp)}`,
              },
              { label: "풀린 보류 좌석", hint: "undeferred", value: String(created.undeferred) },
            ]}
          />
          {created.credential_note ? <p className="m-0 mt-2 text-sm text-muted-foreground">{created.credential_note}</p> : null}
        </div>
      ) : null}
    </SectionCard>
  );
}
