// 카드 대조 대상의 머리 — 완결 표기 · 막음 잔여 표지 · 사슬 단계(재개) · 마지막 종합 보고서 판 · M2 시절 잡 뒤의 사슬 시작(포털 m3-frontend-request 1절)
import { useState } from "react";
import { Link } from "react-router-dom";
import { riskApi } from "../api/risk.api";
import { Badge, LevelBadge, LlmBadge } from "./Badge";
import { KeyValueTable } from "./DataTable";
import { ReviewErrorBanner } from "./ReviewErrorBanner";
import { Button, Mono } from "../ui/primitives";
import { adviceText, blockingUnacked, chainStartVisible, stageView } from "../lib/reviewView";
import { narrativeNote, triggerLabel } from "../lib/reportView";
import { fmtEpoch } from "../format";
import type { Coverage } from "../types";

export type CellsTab = "closure" | "report";

/**
 * 완결 표기는 서버 글(`level_label`) 그대로다 — '무엇이 남아 C3 가 아닌지' 를 말한다. 막음이고 확인되지 않은 잔여가 있으면 완결
 * 화면으로 가는 표지를 단다. 사슬 배지는 `stage`, 보고서 링크는 `report`(마지막 판의 머리)로 그린다.
 */
export function CellsHead({
  coverage,
  targetKey,
  onChanged,
  onOpenTab,
}: {
  coverage: Coverage;
  targetKey: string;
  onChanged: () => void;
  onOpenTab: (tab: CellsTab) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [note, setNote] = useState<string | null>(null);
  const stage = coverage.stage ?? null;
  const view = stageView(stage);
  const report = coverage.report ?? null;
  const unacked = blockingUnacked(coverage.qualifiers);
  const advice = adviceText(stage?.advice);

  async function resume() {
    if (!stage) return;
    setBusy(true);
    setError(null);
    try {
      await riskApi.resumeJob(stage.job_id);
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function startChain() {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      // 셀이 다 닫혀 있어 검토 호출 없이 곧바로 끝나고, 그 끝에서 사슬(쟁점 → 종합)이 선다(요청서 1절).
      const out = await riskApi.createReviewJob(targetKey, { mode: "reviews" });
      setNote(`검토 잡 ${out.job_id} 을 세웠습니다 — 셀이 다 닫혀 있어 호출 없이 끝나고 그 끝에서 쟁점 · 종합이 섭니다.`);
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
      {note ? <p className="m-0 text-sm text-muted-foreground">{note}</p> : null}
      <KeyValueTable
        columns={1}
        rows={[
          {
            label: "완결 표기",
            hint: "level_label",
            value: (
              <span className="flex flex-wrap items-center gap-2">
                <LevelBadge value={coverage.level} />
                <span>{coverage.level_label ?? coverage.level}</span>
                {unacked > 0 ? (
                  <Button type="button" variant="outline" size="sm" onClick={() => onOpenTab("closure")}>
                    확인 안 된 막음 잔여 {unacked} — 완결 화면
                  </Button>
                ) : null}
              </span>
            ),
          },
          {
            label: "사슬",
            hint: "stage",
            value: view && stage ? (
              <span className="flex flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2">
                  <Badge tone={view.tone}>{view.label}</Badge>
                  <Mono>{stage.job_id}</Mono>
                  {stage.llm === "claude" ? <LlmBadge llm={stage.llm} /> : null}
                  {view.resumable ? (
                    <Button type="button" variant="outline" size="sm" onClick={resume} disabled={busy}>
                      재개
                    </Button>
                  ) : null}
                </span>
                {view.note ? <span className="text-xs text-muted-foreground">{view.note}</span> : null}
                {view.needsPat ? (
                  <Link to="/settings" className="w-fit text-xs underline underline-offset-4">
                    설정에서 PAT 등록
                  </Link>
                ) : null}
                {stage.error && !view.note ? <span className="text-xs text-muted-foreground">{stage.error}</span> : null}
                {advice ? (
                  <Badge tone="warn" title="issue_yield_low">
                    {advice}
                  </Badge>
                ) : null}
              </span>
            ) : (
              <span className="text-muted-foreground">쟁점 · 종합 잡이 아직 없습니다.</span>
            ),
          },
          {
            label: "종합 보고서",
            hint: "report",
            value: report ? (
              <span className="flex flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2">
                  <Button type="button" variant="link" size="sm" className="h-auto px-0" onClick={() => onOpenTab("report")}>
                    종합 보고서 v{report.version_no}
                  </Button>
                  <span className="text-xs text-muted-foreground">
                    {triggerLabel(report.trigger)} · {fmtEpoch(report.created_at)}
                  </span>
                </span>
                {narrativeNote(report.narrative_state) ? (
                  <span className="text-xs text-muted-foreground">{narrativeNote(report.narrative_state)}</span>
                ) : null}
              </span>
            ) : (
              <span className="text-muted-foreground">판이 아직 없습니다.</span>
            ),
          },
        ]}
      />
      {chainStartVisible(coverage) ? (
        <div className="flex flex-wrap items-center gap-2 rounded-md border border-border p-3 text-sm">
          <span className="min-w-0 flex-1">
            M2 앱이 세운 검토 잡이 끝난 대상이라 쟁점 · 종합이 저절로 서지 않았습니다. 검토 잡을 한 번 더 세우면(셀이 다 닫혀 호출
            없이 끝난다) 그 끝에서 사슬이 섭니다.
          </span>
          <Button type="button" variant="outline" size="sm" onClick={startChain} disabled={busy}>
            쟁점 · 종합 시작
          </Button>
        </div>
      ) : null}
    </div>
  );
}
