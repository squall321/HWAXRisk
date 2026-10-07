// same-as 확정판 — 사다리 단계(method)별 대응 후보와 사람 확정 버튼, score ≥ 0.9 일괄 수용(계획 §2.6·§2.10·§8.2.4).
import { useEffect, useMemo, useRef, useState } from "react";
import { isNotReady, riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import type { Column } from "./DataTable";
import { DataTable } from "./DataTable";
import { ErrorBanner, LoadingBlock, NotReadyBlock } from "./StateBlocks";
import { Badge, StatusBadge } from "./Badge";
import { GateTable } from "./GateBanner";
import { Banner, Button, FormField, Select } from "../ui/primitives";
import { fmtNum } from "../format";
import type { Gate, SameAsDecision, SameAsPair } from "../types";

/** 일괄 수용의 문턱 — §8.2.4 가 정한 값이다. */
const BULK_SCORE = 0.9;

/** §2.6.2 사다리 단계 순서. 앞 단계에서 확정된 노드는 뒤 단계 후보에서 빠진다. */
const METHODS: Array<{ method: string; label: string }> = [
  { method: "ledger", label: "1 원장" },
  { method: "pid_map", label: "2 pid 다리" },
  { method: "exact_path", label: "3 경로 일치" },
  { method: "fingerprint", label: "4 기하 지문" },
  { method: "name_norm", label: "5 정규명" },
  { method: "fuzzy", label: "6 유사도 배정" },
  { method: "manual", label: "7 사람 확정" },
];
const METHOD_INDEX: Record<string, number> = Object.fromEntries(METHODS.map((m, i) => [m.method, i]));

/** 사람이 먼저 봐야 하는 순서 — 충돌 · 미확정이 위로 온다. */
const STATUS_RANK: Record<SameAsPair["status"], number> = {
  conflict: 0,
  candidate: 1,
  confirmed: 2,
  rejected: 3,
};

type Filter = "all" | "todo" | "confirmed" | "rejected";
const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: "all", label: "전체" },
  { value: "todo", label: "확정 필요(candidate · conflict)" },
  { value: "confirmed", label: "확정됨" },
  { value: "rejected", label: "거부됨" },
];

export function SameAsResolver({
  base,
  target,
  onG2,
}: {
  base: string;
  target: string;
  /** 조회 직후와 확정 직후의 G2 판정을 비교 화면에 그대로 올린다. */
  onG2?: (g2: Gate) => void;
}) {
  const sameas = useAsync(
    (signal) => riskApi.getSameAs(base, target, { signal }),
    [base, target],
    base !== "" && target !== "",
  );
  const onG2Ref = useRef(onG2);
  onG2Ref.current = onG2;
  const loadedG2 = sameas.data?.G2 ?? null;
  // 사람이 확정하기 전에도 서버 판정이 화면에 전달되게 로드 때 한 번 보고한다.
  useEffect(() => {
    if (loadedG2) onG2Ref.current?.(loadedG2);
  }, [loadedG2]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [filter, setFilter] = useState<Filter>("all");

  const pairs = sameas.data?.pairs ?? [];
  const bulkCandidates = useMemo(
    () => pairs.filter((p) => p.status === "candidate" && p.score >= BULK_SCORE),
    [pairs],
  );
  const conflictN = useMemo(() => pairs.filter((p) => p.status === "conflict").length, [pairs]);

  /** 단계별 건수 — 사다리 어디에서 대응이 나왔는지 그대로 센다. */
  const byMethod = useMemo(() => {
    const acc: Record<string, number> = {};
    for (const p of pairs) acc[p.method] = (acc[p.method] ?? 0) + 1;
    return acc;
  }, [pairs]);
  const unknownMethods = useMemo(
    () => Object.keys(byMethod).filter((m) => METHOD_INDEX[m] === undefined),
    [byMethod],
  );

  const rows = useMemo(() => {
    const kept = pairs.filter((p) => {
      if (filter === "all") return true;
      if (filter === "todo") return p.status === "candidate" || p.status === "conflict";
      return p.status === filter;
    });
    return [...kept].sort(
      (a, b) =>
        STATUS_RANK[a.status] - STATUS_RANK[b.status] ||
        (METHOD_INDEX[a.method] ?? METHODS.length) - (METHOD_INDEX[b.method] ?? METHODS.length) ||
        b.score - a.score ||
        a.a.localeCompare(b.a),
    );
  }, [pairs, filter]);

  async function decide(decisions: SameAsDecision[]) {
    if (decisions.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const result = await riskApi.decideSameAs(decisions);
      onG2?.(result.G2);
      sameas.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<SameAsPair>[] = [
    {
      key: "stage",
      header: "단계",
      nowrap: true,
      cell: (p) => {
        const idx = METHOD_INDEX[p.method];
        return idx === undefined ? p.method : METHODS[idx].label;
      },
    },
    { key: "a", header: "a", cell: (p) => <code>{p.a}</code>, nowrap: true },
    { key: "b", header: "b", cell: (p) => <code>{p.b}</code>, nowrap: true },
    { key: "method", header: "method", cell: (p) => p.method, nowrap: true },
    { key: "score", header: "score", cell: (p) => fmtNum(p.score), align: "right", nowrap: true },
    { key: "status", header: "status", cell: (p) => <StatusBadge value={p.status} />, nowrap: true },
    {
      key: "act",
      header: "확정",
      nowrap: true,
      // 표 한 칸이라 size="sm" 으로 둔다 — 기본 높이면 행이 두 배로 두꺼워진다.
      cell: (p) => (
        <span className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => decide([{ a: p.a, b: p.b, decision: "confirm", scope: "pair" }])}
          >
            confirm
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => decide([{ a: p.a, b: p.b, decision: "reject", scope: "pair" }])}
          >
            reject
          </Button>
        </span>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <ErrorBanner error={error} />
      {isNotReady(sameas.error) ? (
        <NotReadyBlock what="same-as 매칭" />
      ) : (
        <ErrorBanner error={sameas.error} onRetry={sameas.reload} />
      )}
      {sameas.loading && !sameas.data ? <LoadingBlock /> : null}
      {sameas.data ? (
        <>
          {/* 미확정·충돌 건수가 이 구역의 판정이다 — 일괄 수용 버튼과 한 줄에 둬서 '무엇이 남았나 → 무엇을 누르나' 가 이어진다. */}
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={sameas.data.pending_n > 0 ? "warn" : "ok"}>미확정 {sameas.data.pending_n}</Badge>
            {conflictN > 0 ? <Badge tone="bad">충돌 {conflictN}</Badge> : null}
            <Button
              type="button"
              variant="outline"
              disabled={busy || bulkCandidates.length === 0}
              onClick={() =>
                decide(bulkCandidates.map((p) => ({ a: p.a, b: p.b, decision: "confirm", scope: "pair" })))
              }
            >
              자동 매칭 전부 수용 (score ≥ {BULK_SCORE}, {bulkCandidates.length}건)
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">사다리 단계</span>
            <span className="inline-flex flex-wrap items-center gap-1">
              {METHODS.map((m) => (
                <Badge key={m.method} tone={byMethod[m.method] ? "info" : "muted"} title={m.method}>
                  {m.label} {byMethod[m.method] ?? 0}
                </Badge>
              ))}
              {unknownMethods.map((m) => (
                <Badge key={m} tone="neutral" title="사다리 표에 없는 method 입니다.">
                  {m} {byMethod[m]}
                </Badge>
              ))}
            </span>
          </div>

          {conflictN > 0 ? (
            <Banner
              tone="info"
              title={`충돌 ${conflictN}건.`}
              detail="한 클러스터에 같은 도메인 노드가 둘 이상입니다. 한 쌍을 reject 하면 풀립니다."
            />
          ) : null}

          <FormField label="보기" className="max-w-xs">
            <Select value={filter} onChange={(e) => setFilter(e.target.value as Filter)}>
              {FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </Select>
          </FormField>

          {sameas.data.G2 ? <GateTable gates={[sameas.data.G2]} /> : null}
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(p) => `${p.a}|${p.b}`}
            empty={filter === "all" ? "자동 매칭 후보가 없습니다." : "이 조건에 맞는 행이 없습니다."}
          />
        </>
      ) : null}
    </div>
  );
}
