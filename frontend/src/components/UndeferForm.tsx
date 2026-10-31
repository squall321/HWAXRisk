// 패널 대상의 보류(deferred) 좌석 풀기 — 사유 4~300자, 도는 잡이 있으면 409 job_live, 저장된 레벨은 내려가지 않는다(포털 m3-frontend-request 3-6절)
import { useState } from "react";
import { riskApi } from "../api/risk.api";
import { ReviewErrorBanner } from "./ReviewErrorBanner";
import { Banner, Button, FormField, Input } from "../ui/primitives";
import { reasonProblem } from "../lib/reviewView";
import type { Undeferred } from "../types";

/**
 * 카드 대조 대상은 검토 잡을 만들 때 범위 안 보류가 저절로 풀리므로 이 버튼은 패널 대상(검토를 얹은 대상 포함)에만 둔다. 푼 좌석이
 * 영역 깊이의 분모에 든다 — 답의 depth 가 지금의 깊이다.
 */
export function UndeferForm({ targetKey, deferred, onChanged }: { targetKey: string; deferred: number; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<Undeferred | null>(null);
  const problem = reasonProblem(reason, true);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (problem) return;
    setBusy(true);
    setError(null);
    try {
      const out = await riskApi.undefer(targetKey, reason.trim());
      setResult(out);
      setOpen(false);
      setReason("");
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span>보류(deferred) 좌석 {deferred}석</span>
        <Button type="button" variant="outline" size="sm" onClick={() => setOpen((v) => !v)} disabled={deferred === 0}>
          보류 풀기…
        </Button>
      </div>
      {result ? (
        <Banner
          tone="info"
          live="status"
          title={result.changed ? `보류 좌석 ${result.undeferred}석을 풀었습니다(pending).` : "풀 보류 좌석이 없었습니다."}
          detail={
            <>
              {result.agents.length > 0 ? `${result.agents.join(" · ")}${result.agents_total > result.agents.length ? ` 외 ${result.agents_total - result.agents.length}` : ""}. ` : ""}
              {result.note}
              {result.depth
                ? ` 지금 깊이 — ${Object.entries(result.depth)
                    .map(([d, v]) => `${d} ${v.have}/${v.need}`)
                    .join(" · ")}.`
                : ""}
            </>
          }
        />
      ) : null}
      {open ? (
        <form className="flex flex-col gap-2 rounded-md border border-border p-3" onSubmit={send}>
          <ReviewErrorBanner error={error} onReload={onChanged} />
          <p className="m-0 text-sm">
            이 대상의 보류 좌석을 모두 대기(pending)로 풉니다 — 저장된 레벨은 내려가지 않고, 푼 좌석이 영역 깊이의 분모에 듭니다.
          </p>
          <FormField label="푸는 사유" hint="필수 · 4~300자" error={reason !== "" && problem ? problem : undefined}>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} aria-label="보류 푸는 사유" />
          </FormField>
          <span className="flex flex-wrap items-center gap-2">
            <Button type="submit" size="sm" disabled={busy || problem !== null}>
              보류 풀기
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
              그만두기
            </Button>
          </span>
        </form>
      ) : null}
    </div>
  );
}
