// 카드 대조 전문가 머리 목록과 전문가 보고서 쪽(md) — M3 표지(거름 · 넘긴 셀 · 다툼 · 입력 결손 …)는 md 글에 이미 들어 있어 그대로 그린다(포털 m3-frontend-request 3-7절)
import { useState } from "react";
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { Badge, StatusBadge } from "./Badge";
import { DataTable, KeyValueTable } from "./DataTable";
import type { Column } from "./DataTable";
import { ReportPager, isAbsent } from "./ReportPager";
import { SectionCard } from "./SectionCard";
import { EmptyBlock, ErrorBanner, LoadingBlock } from "./StateBlocks";
import { cellStateLabel } from "../lib/reviewView";
import { fmtEpoch } from "../format";
import type { ExpertHead, ExpertReportPart } from "../types";

const PARTS: ReadonlyArray<{ part: ExpertReportPart; label: string }> = [
  { part: "summary", label: "요약" },
  { part: "units", label: "단위별" },
  { part: "cards", label: "카드 점검표" },
  { part: "full", label: "전부" },
];

/** 셀 상태 셈 한 줄 — 0 인 칸은 뺀다. */
function cellsText(by: Record<string, number>): string {
  const parts = Object.entries(by)
    .filter(([, n]) => n > 0)
    .map(([s, n]) => `${cellStateLabel(s)} ${n}`);
  return parts.length > 0 ? parts.join(" · ") : "셀 없음";
}

export function ExpertReports({ targetKey }: { targetKey: string }) {
  const experts = useAsync((signal) => riskApi.getExperts(targetKey, { signal }), [targetKey]);
  const [agent, setAgent] = useState<string | null>(null);
  const rows = experts.data?.experts ?? [];

  const columns: Column<ExpertHead>[] = [
    { key: "order", header: "차례", hint: "review_order", cell: (e) => e.review_order ?? "—", align: "right", nowrap: true },
    { key: "agent", header: "전문가", hint: "agent_key", cell: (e) => <code>{e.agent_key}</code>, nowrap: true },
    { key: "domain", header: "영역", cell: (e) => e.domain, nowrap: true },
    { key: "tier", header: "tier", cell: (e) => e.tier ?? "—", nowrap: true },
    { key: "state", header: "머리", hint: "state", cell: (e) => <StatusBadge value={e.state} />, nowrap: true },
    {
      key: "cards",
      header: "카드",
      hint: "cards · card_basis",
      nowrap: true,
      cell: (e) =>
        e.cards ? `${e.cards.cards_total}장(점검 ${e.cards.checkable_n})${e.card_basis ? ` · ${e.card_basis}` : ""}` : (
          <span className="text-muted-foreground">묶음 전{e.pack_status !== "todo" ? ` · ${e.pack_status}` : ""}</span>
        ),
    },
    { key: "cells", header: "셀", hint: "cells.by_state", cell: (e) => `${e.cells.total} — ${cellsText(e.cells.by_state)}` },
    { key: "rev", header: "판", hint: "revision", cell: (e) => (e.finalized_at ? `v${e.revision} · ${fmtEpoch(e.finalized_at)}` : "마감 전"), nowrap: true },
    {
      key: "why",
      header: "까닭",
      hint: "error",
      cell: (e) => (e.state === "blocked" && e.error ? <Badge tone="bad">{e.error}</Badge> : e.error ?? null),
    },
  ];

  return (
    <SectionCard title="전문가 보고서" subtitle="행을 누르면 그 전문가의 보고서 쪽이 열립니다(마감 때 얼린 판).">
      <ErrorBanner error={experts.error} onRetry={experts.reload} />
      {experts.loading && !experts.data ? <LoadingBlock /> : null}
      {experts.data ? (
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(e) => e.agent_key}
          selectedKey={agent}
          onRowClick={(e) => setAgent((cur) => (cur === e.agent_key ? null : e.agent_key))}
          empty="전문가 머리가 아직 없습니다 — 검토 잡이 계획하면 생깁니다."
        />
      ) : null}
      {agent ? (
        <div className="mt-4">
          <ReportPager
            key={`${targetKey}|${agent}`}
            idPrefix="expert-report"
            loadKey={`${targetKey}|${agent}`}
            parts={PARTS}
            load={(query, signal) => riskApi.getExpertReport(targetKey, agent, query, { signal })}
            absent={(error) =>
              isAbsent(error, "E404") ? (
                <EmptyBlock title="이 전문가의 보고서가 아직 없습니다." hint="마감 전이거나 원문이 비었습니다." />
              ) : null
            }
            header={(data) => (
              <KeyValueTable
                rows={[
                  { label: "전문가", hint: "agent_key", value: <code>{data.agent_key}</code> },
                  { label: "머리", hint: "state", value: <StatusBadge value={data.state} /> },
                  { label: "마감", hint: "finalized_at", value: fmtEpoch(data.finalized_at) },
                  { label: "좌석 상태", hint: "coverage_status", value: data.coverage_status ?? "—" },
                  ...(data.state_why ? [{ label: "막힌 까닭", hint: "state_why", value: data.state_why }] : []),
                ]}
              />
            )}
          />
        </div>
      ) : null}
    </SectionCard>
  );
}
