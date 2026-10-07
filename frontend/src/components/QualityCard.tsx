// 품질·학습 루프 계측 카드 — GET /api/meta/metrics 를 읽어 '루프 작동' 배지와 지표 표를 보인다(계획 §7.6·§9.7)
import { useMemo } from "react";
import { RefreshCw } from "lucide-react";
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { SectionCard } from "./SectionCard";
import { DataTable } from "./DataTable";
import { Badge } from "./Badge";
import { EmptyBlock, ErrorBanner, LoadingBlock } from "./StateBlocks";
import { Button } from "../ui/primitives";
import type { Column } from "./DataTable";
import type { MetricRow } from "../types";

/** 배지 3종은 서버가 `rr_metrics` 행으로 낸다(§7.6 판정 규칙) — 화면이 임계를 다시 계산하지 않는다. */
const BOTTLENECKS: Array<[string, string]> = [
  ["loop_bottleneck_labels", "라벨"],
  ["loop_bottleneck_queue", "큐 적체"],
  ["loop_bottleneck_coverage", "커버리지"],
];

function pick(rows: MetricRow[], metric: string): MetricRow | undefined {
  return rows.find((r) => r.dimension === "global" && r.metric === metric);
}

/** 표본 부족은 서버가 `value=null` 로 낸다(§7.6 — n 이 임계 미달이면 값을 만들지 않는다). */
function valueText(row: MetricRow): string {
  if (row.value === null) return `표본 부족 (n=${row.n})`;
  return Number.isInteger(row.value) ? String(row.value) : row.value.toFixed(3);
}

export function QualityCard() {
  const metrics = useAsync((signal) => riskApi.getMetrics({ signal }), []);
  const rows = metrics.data?.metrics ?? [];

  const loopOk = pick(rows, "loop_ok");
  const wired = pick(rows, "label_ingest_wired");
  const hits = BOTTLENECKS.filter(([metric]) => (pick(rows, metric)?.value ?? 0) > 0);

  /** 배지 행(loop_*·label_ingest_wired)은 판정이지 지표가 아니라 표에서 뺀다. */
  const table = useMemo(
    () =>
      rows
        .filter((r) => !r.metric.startsWith("loop_") && r.metric !== "label_ingest_wired")
        .sort((a, b) =>
          a.dimension === b.dimension
            ? a.metric.localeCompare(b.metric) || a.key.localeCompare(b.key)
            : a.dimension.localeCompare(b.dimension)),
    [rows],
  );

  const columns: Column<MetricRow>[] = [
    { key: "metric", header: "지표", cell: (r) => r.metric, nowrap: true },
    { key: "dimension", header: "차원", cell: (r) => r.dimension, nowrap: true },
    { key: "key", header: "키", cell: (r) => r.key, nowrap: true },
    {
      key: "value",
      header: "값",
      align: "right",
      nowrap: true,
      // 표본 부족은 '0' 이 아니라 '재지 않았다' 라서 흐리게 둔다(§7.6).
      cell: (r) => (r.value === null ? <span className="text-muted-foreground">{valueText(r)}</span> : valueText(r)),
    },
    { key: "n", header: "n", cell: (r) => String(r.n), align: "right", nowrap: true },
  ];

  return (
    <SectionCard
      title="품질"
      subtitle="학습 루프가 도는지의 계측입니다. 판정·임계는 서버 값이고 화면은 다시 계산하지 않습니다."
      actions={
        <>
          {loopOk ? (
            <Badge tone={(loopOk.value ?? 0) > 0 ? "ok" : "warn"}>
              {(loopOk.value ?? 0) > 0 ? "루프 작동" : "루프 미작동"}
            </Badge>
          ) : null}
          {hits.map(([metric, label]) => (
            <Badge key={metric} tone="warn">
              병목 {label}
            </Badge>
          ))}
          {wired && (wired.value ?? 1) === 0 ? <Badge tone="info">라벨 자동 유입 미배선</Badge> : null}
          <Button type="button" variant="outline" onClick={metrics.reload} disabled={metrics.loading}>
            <RefreshCw className="size-4" aria-hidden="true" />
            갱신
          </Button>
        </>
      }
    >
      <ErrorBanner error={metrics.error} onRetry={metrics.reload} />
      {metrics.loading && !metrics.data ? <LoadingBlock /> : null}
      {wired && (wired.value ?? 1) === 0 ? (
        <p className="text-sm text-muted-foreground">
          라벨 자동 유입 4경로(RA incident · test_run · DynaForge · VOC)가 아직 배선되지 않았습니다 —
          학습 루프의 분모가 사람 라벨뿐이라는 뜻입니다. '병목 라벨' 은 그 사실의 결과일 수 있습니다.
        </p>
      ) : null}
      {metrics.data && table.length === 0 ? (
        <EmptyBlock
          title="지표가 아직 없습니다."
          hint="패널이 돌고 라벨이 쌓이면 여기 채워집니다. 지금 계산하려면 야간 잡 또는 재계산을 부르세요."
        />
      ) : null}
      {table.length > 0 ? (
        <DataTable columns={columns} rows={table} rowKey={(r) => `${r.dimension}|${r.key}|${r.metric}`} />
      ) : null}
    </SectionCard>
  );
}
