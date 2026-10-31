// 스냅샷 화면 — 게이트(판정 불가 · ack)·개요·보드·강등 표지·요약 · 신호·요구 여유·노드(kind 거름 · 정규 키 원장)·엣지·롤업·dims·rule_hits·warnings·호출 로그(계획 §8.2.4 SnapshotPage 행). ProjectPage 가 ?snapshot= 일 때 그린다.
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ExternalLink, Plus } from "lucide-react";
import { isNotReady, riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { SectionCard, VerbatimBlock } from "../components/SectionCard";
import type { Column } from "../components/DataTable";
import { DataTable, KeyValueTable } from "../components/DataTable";
import { EmptyBlock, ErrorBanner, LoadingBlock, NotReadyBlock } from "../components/StateBlocks";
import { Badge, SeverityBadge, StatusBadge } from "../components/Badge";
import { GATE_LABEL, GateBanner, GateTable } from "../components/GateBanner";
import { KeyLedgerPanel } from "../components/KeyLedgerPanel";
import { Banner, Button, Input, Mono, PageHeader, Select } from "../ui/primitives";
import { fmtCell, fmtEpoch, fmtJson, fmtNum } from "../format";
import {
  SNAP_GATE_IDS,
  boardNode,
  boardRows,
  dimValue,
  filterNodes,
  marginRows,
  nodeKindCounts,
  ruleCounts,
  ruleVerdict,
  snapshotFlags,
} from "../lib/snapshotView";
import type { FlagChip } from "../lib/snapshotView";
import type { DimNamed, IrEdge, IrNode, IrWarning, JsonObject, ReqMarginRow, RuleHit, SnapshotCall } from "../types";

/** §2.9 rollups.by_assembly 한 행. 서버가 준 자유 JSON 을 열 이름으로만 읽는다. */
const ROLLUP_COLUMNS: Array<{ key: string; header: string; align?: "right" }> = [
  { key: "path_prefix", header: "path_prefix" },
  { key: "depth", header: "depth", align: "right" },
  { key: "n_leaf", header: "n_leaf", align: "right" },
  { key: "edges_internal", header: "edges_internal" },
  { key: "edges_external", header: "edges_external" },
  { key: "orphan_leaf", header: "orphan_leaf", align: "right" },
];

/** 배지 여러 개를 한 줄로 흘리는 묶음(기존 `.rr-badge-group`). 이 화면에서만 쓰므로 지역 상수로 둔다. */
const BADGE_GROUP = "inline-flex flex-wrap items-center gap-1";

/** 노드 kind 의 사람 말 — 값은 그대로 보이고 뜻만 붙인다. 사전에 없는 kind 는 글자 그대로다. */
const NODE_KIND_LABEL: Record<string, string> = {
  part: "부품(MCAD)",
  assembly: "어셈블리",
  file: "파일",
  pid: "PID(dyna)",
  contact_set: "접촉(dyna)",
  component: "부품(ECAD)",
  layer: "층(ECAD)",
  board: "보드(ECAD)",
  net: "넷(ECAD)",
};

function NodeTable({ nodes, onPick, picked }: { nodes: IrNode[]; onPick: (node: IrNode) => void; picked: string | null }) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const kinds = useMemo(() => nodeKindCounts(nodes), [nodes]);
  const filtered = useMemo(() => filterNodes(nodes, kind, q), [nodes, kind, q]);

  const columns: Column<IrNode>[] = [
    { key: "nid", header: "nid", cell: (n) => <code>{n.nid}</code>, nowrap: true },
    { key: "kind", header: "kind", cell: (n) => n.kind, nowrap: true },
    { key: "label", header: "이름", hint: "label", cell: (n) => n.label },
    { key: "domain", header: "도메인", hint: "domain", cell: (n) => n.domain, nowrap: true },
    { key: "group", header: "묶음", hint: "group", cell: (n) => n.group ?? <span className="text-muted-foreground">—</span>, nowrap: true },
    { key: "ckey", header: "정규 키", hint: "ckey", cell: (n) => (n.ckey ? <code>{n.ckey}</code> : "-"), nowrap: true },
    { key: "dn", header: "dn", cell: (n) => (n.dn ? <code>{n.dn}</code> : "-"), nowrap: true },
    {
      key: "flags",
      header: "표지",
      hint: "status_flags",
      cell: (n) => (
        <span className={BADGE_GROUP}>
          {n.status_flags.map((f) => (
            <Badge key={f} tone="neutral">
              {f}
            </Badge>
          ))}
        </span>
      ),
    },
  ];

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select className="w-auto min-w-[12rem]" aria-label="노드 kind 거르기" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">kind 전체</option>
          {kinds.map((k) => (
            <option key={k.kind} value={k.kind}>
              {NODE_KIND_LABEL[k.kind] ? `${NODE_KIND_LABEL[k.kind]} ${k.kind}` : k.kind} · {k.n}
            </option>
          ))}
        </Select>
        <Input
          className="max-w-xs"
          placeholder="nid · 이름 · ckey · dn 검색"
          aria-label="노드 검색"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <span className="text-sm text-muted-foreground">
          {filtered.length} / {nodes.length} 개 — 행을 누르면 아래에 그 정규 키의 원장 조작이 열립니다.
        </span>
      </div>
      <DataTable
        columns={columns}
        rows={filtered}
        rowKey={(n) => n.nid}
        selectedKey={picked}
        onRowClick={onPick}
        empty="노드가 없습니다."
      />
    </>
  );
}

function EdgeTable({ edges }: { edges: IrEdge[] }) {
  const columns: Column<IrEdge>[] = [
    { key: "eid", header: "eid", cell: (e) => <code>{e.eid}</code>, nowrap: true },
    { key: "kind", header: "kind", cell: (e) => <StatusBadge value={e.kind} />, nowrap: true },
    { key: "status", header: "status", cell: (e) => <StatusBadge value={e.status} />, nowrap: true },
    { key: "a", header: "a", cell: (e) => <code>{e.a}</code>, nowrap: true },
    { key: "b", header: "b", cell: (e) => (e.b ? <code>{e.b}</code> : "-"), nowrap: true },
    {
      key: "min_gap",
      header: "min_gap",
      cell: (e) => fmtNum(typeof e.attrs.min_gap === "number" ? e.attrs.min_gap : null),
      align: "right",
      nowrap: true,
    },
    {
      key: "pen",
      header: "penetration_depth",
      align: "right",
      nowrap: true,
      // 하한 표기는 서버 플래그(attrs.penetration_depth_is_lower_bound)를 그대로 옮긴 것이다.
      cell: (e) =>
        typeof e.attrs.penetration_depth !== "number"
          ? "-"
          : `${e.attrs.penetration_depth_is_lower_bound ? "≥ " : ""}${fmtNum(e.attrs.penetration_depth)}`,
    },
  ];
  return <DataTable columns={columns} rows={edges} rowKey={(e) => e.eid} empty="엣지가 없습니다." />;
}

function DimsTable({ dims }: { dims: DimNamed[] }) {
  const columns: Column<DimNamed>[] = [
    { key: "name", header: "name", cell: (d) => d.name, nowrap: true },
    { key: "method", header: "method", cell: (d) => d.method, nowrap: true },
    { key: "value", header: "값", hint: "value · null_reason", cell: (d) => dimValue(d), align: "right", nowrap: true },
    { key: "ref", header: "ref", cell: (d) => (d.ref ? <code>{fmtCell(d.ref)}</code> : "-") },
    { key: "formula", header: "formula", cell: (d) => d.formula ?? "-" },
  ];
  return <DataTable columns={columns} rows={dims} rowKey={(d, i) => `${d.name}#${i}`} empty="dims_named 가 없습니다." />;
}

function WarningTable({ warnings }: { warnings: IrWarning[] }) {
  const columns: Column<IrWarning>[] = [
    { key: "severity", header: "severity", cell: (w) => <StatusBadge value={w.severity} />, nowrap: true },
    { key: "code", header: "code", cell: (w) => <code>{w.code}</code>, nowrap: true },
    { key: "message", header: "message", cell: (w) => w.message },
    { key: "ref", header: "ref", cell: (w) => (w.ref ? <code>{w.ref}</code> : "-") },
    { key: "source", header: "source_kind", cell: (w) => w.source_kind ?? "-", nowrap: true },
  ];
  return <DataTable columns={columns} rows={warnings} rowKey={(w, i) => `${w.code}#${i}`} empty="경고가 없습니다." />;
}

/** 규칙 적중 — 평가 불가(evaluable=false)는 회색 '평가 불가(사유)' 로 보이고 pass 집계에 들지 않는다(§3.2.6). */
function RuleHitTable({ hits }: { hits: RuleHit[] }) {
  const counts = ruleCounts(hits);
  const columns: Column<RuleHit>[] = [
    { key: "rule", header: "rule", cell: (h) => <code>{h.rule}</code>, nowrap: true },
    { key: "severity", header: "severity", cell: (h) => <SeverityBadge value={h.severity} />, nowrap: true },
    {
      key: "pass",
      header: "판정",
      cell: (h) => {
        const v = ruleVerdict(h);
        return (
          <Badge tone={v.tone} title={v.title}>
            {v.label}
          </Badge>
        );
      },
      nowrap: true,
    },
    { key: "found", header: "found", cell: (h) => h.found?.text ?? "-" },
    { key: "why", header: "why_it_matters", cell: (h) => h.why_it_matters },
    { key: "fix", header: "fix_hint", cell: (h) => h.fix_hint },
  ];
  return (
    <>
      <p className="m-0 mb-2 text-sm text-muted-foreground">
        pass {counts.pass} · fail {counts.fail} · 평가 불가 {counts.notEvaluable} — 평가 불가는 pass 로 세지 않습니다.
      </p>
      <DataTable columns={columns} rows={hits} rowKey={(h, i) => `${h.rule}#${i}`} empty="규칙 적중이 없습니다." />
    </>
  );
}

function CallTable({ calls }: { calls: SnapshotCall[] }) {
  const columns: Column<SnapshotCall>[] = [
    { key: "ref", header: "참조", cell: (c) => <code>{`tool:${c.call_id}`}</code>, nowrap: true },
    { key: "kind", header: "source_kind", cell: (c) => c.source_kind ?? "-", nowrap: true },
    { key: "app", header: "app_key", cell: (c) => c.app_key ?? "-", nowrap: true },
    { key: "tool", header: "tool", cell: (c) => c.tool, nowrap: true },
    { key: "args", header: "args", cell: (c) => <code className="text-xs">{fmtCell(c.args)}</code> },
    {
      key: "ok",
      header: "ok",
      cell: (c) => <Badge tone={c.ok ? "ok" : "bad"}>{c.ok ? "ok" : "fail"}</Badge>,
      nowrap: true,
    },
    { key: "error", header: "error", cell: (c) => c.error ?? "-" },
    { key: "at", header: "started_at", cell: (c) => fmtEpoch(c.started_at), nowrap: true },
  ];
  return <DataTable columns={columns} rows={calls} rowKey={(c) => c.call_id} empty="호출 로그가 없습니다." />;
}

/** 강등 · 결측 표지 칩. 뜻은 사전에서 붙이고 값 자체는 서버 문자열 그대로다. */
function FlagList({ flags }: { flags: FlagChip[] }) {
  if (flags.length === 0) return <p className="m-0 text-sm text-muted-foreground">강등 · 결측 표지가 없습니다.</p>;
  return (
    <span className={BADGE_GROUP}>
      {flags.map((f) => (
        <Badge key={`${f.where}:${f.code}`} tone="warn" title={f.label ?? "사전에 없는 코드입니다."}>
          {f.where === "missing" ? "" : `${f.where} · `}
          {f.code}
          {f.label ? ` — ${f.label}` : null}
        </Badge>
      ))}
    </span>
  );
}

/** rollups.by_assembly 가 표 모양이면 표로, 아니면 원문 JSON 으로 보인다. */
function RollupBlock({ rollups }: { rollups: JsonObject }) {
  const rows = Array.isArray(rollups.by_assembly)
    ? (rollups.by_assembly.filter((r) => typeof r === "object" && r !== null && !Array.isArray(r)) as JsonObject[])
    : null;
  const rest = Object.entries(rollups).filter(([k]) => k !== "by_assembly");
  if (rows === null) {
    return <VerbatimBlock text={fmtJson(rollups)} label="rollups" />;
  }
  const columns: Column<JsonObject>[] = ROLLUP_COLUMNS.map((c) => ({
    key: c.key,
    header: c.header,
    align: c.align,
    nowrap: true,
    cell: (row: JsonObject) => fmtCell(row[c.key]),
  }));
  return (
    <div className="mt-3 flex flex-col gap-2">
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(row, i) => `${fmtCell(row.path_prefix)}#${i}`}
        empty="서브어셈블리 롤업이 없습니다."
      />
      {rest.length > 0 ? <VerbatimBlock text={fmtJson(Object.fromEntries(rest))} label="rollups(그 밖)" /> : null}
    </div>
  );
}

/** 보드 묶음(ecad-1031 §7) — board 노드의 attrs 를 사람 말 라벨로. null 은 '없음', 2단계 칸에는 '2단계' 를 붙인다. */
function BoardCard({ node }: { node: IrNode }) {
  return (
    <SectionCard title="보드" subtitle="ODB 허브에서 실은 ECAD 보드 — 1단계는 보드 · 적층 · 분류된 부품까지입니다.">
      <KeyValueTable
        rows={boardRows(node).map((r) => ({
          label: r.label,
          hint: r.hint,
          value: (
            <span className="inline-flex flex-wrap items-center gap-1.5">
              {r.value === null ? <span className="text-muted-foreground">없음</span> : r.value}
              {r.phase2 ? (
                <Badge tone="muted" title="부품 좌표 · 넷 · 외곽 원점은 ODB 허브 쪽 도구가 붙은 뒤(2단계)에 실린다">
                  2단계
                </Badge>
              ) : null}
            </span>
          ),
        }))}
      />
    </SectionCard>
  );
}

/** 요구 여유 표(`sig:req.margin`) — margin 오름차순, 미측정은 0 이 아니라 '미측정' 이다(§2.8b · §3.2.3). */
function MarginCard({ rows, reqAbsent }: { rows: ReqMarginRow[] | null; reqAbsent: boolean | undefined }) {
  const columns: Column<ReqMarginRow>[] = [
    { key: "name", header: "요구", hint: "name", cell: (r) => <code>{`req:${r.name}`}</code>, nowrap: true },
    { key: "op", header: "비교", hint: "op", cell: (r) => r.op ?? "-", nowrap: true },
    { key: "limit", header: "한계", hint: "limit", cell: (r) => `${fmtCell(r.limit)}${r.unit ? ` ${r.unit}` : ""}`, nowrap: true },
    {
      key: "actual",
      header: "실측",
      hint: "actual",
      align: "right",
      nowrap: true,
      cell: (r) => (r.known && r.actual !== null ? fmtNum(r.actual) : <span className="text-muted-foreground">미측정</span>),
    },
    {
      key: "margin",
      header: "여유",
      hint: "margin",
      align: "right",
      nowrap: true,
      cell: (r) =>
        r.margin === null ? (
          <span className="text-muted-foreground">미측정</span>
        ) : (
          <Badge tone={r.margin <= 0 ? "bad" : "ok"}>{fmtNum(r.margin)}</Badge>
        ),
    },
    {
      key: "rel",
      header: "상대 여유",
      hint: "rel",
      align: "right",
      nowrap: true,
      cell: (r) => (r.rel === null ? <span className="text-muted-foreground">—</span> : `${(r.rel * 100).toFixed(1)}%`),
    },
    { key: "status", header: "상태", hint: "status", cell: (r) => <StatusBadge value={r.status} />, nowrap: true },
  ];
  return (
    <SectionCard title="요구 여유" subtitle="sig:req.margin 을 여유 오름차순으로 — 서버가 정렬한 그대로이고 미측정은 맨 뒤입니다.">
      {rows === null ? (
        <Banner
          tone="info"
          title="이 스냅샷의 상태에 요구 대조(sig:req.margin)가 없습니다."
          detail="요구 대조가 들어가기 전에 언 스냅샷입니다 — 과제의 요구를 저장(등록 · 상태 바꾸기 · 승계)하면 그 과제 스냅샷의 상태를 다시 세어 이 자리에 여유 표가 섭니다."
        />
      ) : rows.length === 0 ? (
        <Badge tone="muted">{reqAbsent ? "요구 미등록 — 판정은 좌석 기준" : "치수 한계 요구가 없습니다"}</Badge>
      ) : (
        <DataTable columns={columns} rows={rows} rowKey={(r) => r.name} empty="요구 여유가 없습니다." />
      )}
    </SectionCard>
  );
}

export default function SnapshotPage({ snapshotId }: { snapshotId: string }) {
  const navigate = useNavigate();
  const ir = useAsync((signal) => riskApi.getSnapshotIr(snapshotId, { signal }), [snapshotId]);
  const state = useAsync((signal) => riskApi.getSnapshotState(snapshotId, { signal }), [snapshotId]);
  const calls = useAsync((signal) => riskApi.getSnapshotCalls(snapshotId, { signal }), [snapshotId]);
  const ruleHits = useAsync((signal) => riskApi.getRuleHits(snapshotId, { signal }), [snapshotId]);

  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pickedNode, setPickedNode] = useState<IrNode | null>(null);

  // 서버가 아직 없는 동안 필드가 비어 와도 화면이 살아 있게 기본값을 둔다.
  const dims = ir.data?.dims_named ?? [];
  const nodes = ir.data?.nodes ?? [];
  const edges = ir.data?.edges ?? [];
  const warnings = ir.data?.warnings ?? [];
  const rollups = ir.data?.rollups ?? {};
  const flags = useMemo(() => snapshotFlags(ir.data), [ir.data]);
  const board = useMemo(() => boardNode(ir.data), [ir.data]);
  const kinds = useMemo(() => (ir.data?.sources ?? []).map((s) => String(s.kind)), [ir.data]);
  const gates = state.data?.gates ?? null;
  /**
   * 서버가 센 차단(state.is_blocked — G6 fail 이거나 G6 판정 불가 unit_unknown)이면 diff · 타깃 만들기가 409 로 막힌다(§2.12).
   * 화면은 그 사실만 옮긴다 — 판정 불가 일반(null)은 차단이 아니다.
   */
  const blocked = state.data?.blocked === true;
  /** §8.2.4 — mcad 부품의 부피 · 재질이 전부 null 이면 소스 앱에서 재파싱하라고만 알린다(앱은 쓰기를 하지 않는다). */
  const needsReparse = ir.data?.missing?.volume_null === true;

  async function openSingleReview() {
    const text = state.data?.summary_text;
    if (text) {
      try {
        await navigator.clipboard.writeText(text);
        setNotice("스냅샷 요약을 클립보드에 복사했습니다.");
      } catch {
        setNotice("클립보드 복사에 실패했습니다. 요약 카드에서 직접 복사하세요.");
      }
    }
    window.open("/deliberate", "_blank", "noopener");
  }

  async function createTarget() {
    setBusy(true);
    setActionError(null);
    try {
      const created = await riskApi.createTarget({ kind: "snap", ref_id: snapshotId, consent: true });
      navigate(`/targets/${encodeURIComponent(created.target_key)}`);
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(false);
    }
  }

  /** 돌아갈 과제. id 는 IR 응답에만 있으므로 아직 오지 않았으면 링크를 만들지 않는다(없는 주소를 지어내지 않는다). */
  const projectId = ir.data?.project_id ?? null;
  const signals = Object.entries(state.data?.signals ?? {}).sort(([a], [b]) => a.localeCompare(b));

  return (
    <>
      <PageHeader
        // 이 화면은 독립 라우트가 아니라 ProjectPage 안에 `?snapshot=` 으로 끼워 그려진다
        // (ProjectPage.tsx `<SnapshotPage snapshotId=… />`). h1 로 두면 과제 화면의 문서 제목이
        // '스냅샷' 으로 바뀐다 — 품고 있는 쪽이 h1 이어야 한다.
        as="h2"
        crumb={
          projectId ? (
            <Link to={`/projects/${encodeURIComponent(projectId)}`} className="hover:underline">
              과제
            </Link>
          ) : (
            <span>과제</span>
          )
        }
        title={ir.data?.label ? `스냅샷 ${ir.data.label}` : "스냅샷"}
        subtitle={
          // id 는 제목이 아니라 보조 사실이다 — 사람이 읽는 이름은 '스냅샷' 이고 id 는 서버와 대조할 때 쓴다.
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            {/* 원시 필드명을 지우지 않는다 — 다른 라벨은 전부 hint 로 남겼는데 여기만 예외일 이유가 없다. */}
            <span>
              <span className="font-mono opacity-60">snapshot_id</span> <Mono>{snapshotId}</Mono>
            </span>
            {ir.data ? <span>동결 {fmtEpoch(ir.data.captured_at)}</span> : null}
            {kinds.length > 0 ? <span>소스 {kinds.join(" · ")}</span> : null}
          </span>
        }
        actions={
          <>
            <Button type="button" variant="outline" onClick={openSingleReview}>
              {/* 새 창에서 열린다는 사실을 아이콘이 말한다. */}
              <ExternalLink aria-hidden="true" />
              단발 심사 열기
            </Button>
            <Button
              type="button"
              onClick={createTarget}
              disabled={busy || blocked}
              title={blocked ? "G6 로 차단된 스냅샷은 타깃을 만들 수 없습니다." : undefined}
            >
              <Plus aria-hidden="true" />
              타깃 만들기
            </Button>
          </>
        }
      />

      {/* 두 버튼이 머리말로 올라갔으니 그 결과(오류·안내)도 버튼 옆에서 말한다 — 아래 카드에 두면 눌린 자리와 멀어진다. */}
      <ErrorBanner error={actionError} />
      {notice ? <p className="mb-3 text-sm text-muted-foreground">{notice}</p> : null}

      {/* 게이트를 첫 카드로 둔다 — G6 차단 하나가 '타깃 만들기' 를 막으므로 이 화면에서 사람이 가장 먼저 알아야 할 판정이다. */}
      <SectionCard
        title="게이트"
        subtitle="G1~G6 판정은 서버가 계산한 값입니다 — 판정 불가는 fail 이 아니라 검문할 입력이 없었다는 뜻입니다(G7 은 비교 전용)."
      >
        {isNotReady(state.error) ? (
          <NotReadyBlock what="게이트 판정" />
        ) : (
          <ErrorBanner error={state.error} onRetry={state.reload} />
        )}
        {state.loading && !state.data ? <LoadingBlock /> : null}
        {state.data ? (
          <>
            {blocked ? (
              <Banner
                title="차단 — G6."
                detail={
                  gates?.G6?.pass === null
                    ? "단위를 몰라(unit_unknown) 차단을 유지합니다. REST 원문으로 다시 캡처해야 풀립니다 — diff 생성과 타깃 만들기가 409 로 막힙니다."
                    : "diff 생성과 타깃 만들기가 409 로 막힙니다. 소스를 고쳐 새 스냅샷을 만들어야 합니다."
                }
              />
            ) : null}
            <GateBanner gates={gates} />
            <GateTable gates={gates} snapshotId={snapshotId} onChanged={state.reload} />
            <p className="m-0 mt-2 text-xs text-muted-foreground">
              {SNAP_GATE_IDS.map((id) => `${id} ${GATE_LABEL[id]}`).join(" · ")}
            </p>
          </>
        ) : null}
      </SectionCard>

      <SectionCard title="스냅샷 개요">
        {isNotReady(ir.error) ? <NotReadyBlock what="스냅샷 IR" /> : <ErrorBanner error={ir.error} onRetry={ir.reload} />}
        {ir.loading && !ir.data ? <LoadingBlock /> : null}
        {needsReparse ? (
          <Banner tone="info" title="재파싱이 필요합니다." detail="mcad 부품의 부피 값이 전부 비어 있습니다(missing.volume_null).">
            <a
              href="/apps/step_forge/"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-sm"
            >
              <ExternalLink className="size-4" aria-hidden="true" />
              StepForge 열기
            </a>
          </Banner>
        ) : null}
        {ir.data ? (
          // 라벨은 사람 말로 쓰고 원시 필드명은 hint 로 접어 둔다 — 서버와 대조할 이름을 지우지 않으면서
          // 화면이 엔지니어 덤프로 읽히지 않게 한다(D35). 값과 순서는 그대로다.
          <KeyValueTable
            rows={[
              { label: "IR 해시", hint: "ir_hash", value: <code>{ir.data.ir_hash}</code> },
              { label: "IR 버전", hint: "ir_version", value: ir.data.ir_version },
              {
                label: "소스",
                hint: "sources[].kind · adapter_version",
                value:
                  ir.data.sources.length === 0
                    ? "-"
                    : ir.data.sources.map((s) => `${s.kind} ${s.adapter_version}`).join(" · "),
              },
              { label: "주 소스", hint: "primary_source", value: ir.data.primary_source ?? "-" },
              { label: "동결 시각", hint: "captured_at", value: fmtEpoch(ir.data.captured_at) },
              {
                label: "노드 · 엣지 · 명명 치수",
                hint: "nodes · edges · dims_named",
                value: `${nodes.length} · ${edges.length} · ${dims.length}`,
              },
              { label: "부분 범위", hint: "partial", value: ir.data.partial ? <Badge tone="warn">partial</Badge> : "아님" },
              { label: "경고", hint: "warnings", value: `${warnings.length}건` },
            ]}
          />
        ) : null}
      </SectionCard>

      {/* 보드가 없으면 이 묶음을 그리지 않는다(ecad-1031 §7). */}
      {board ? <BoardCard node={board} /> : null}

      <SectionCard title="강등 · 결측 표지" subtitle="missing.* 의 참인 열쇠와 소스마다 degraded 코드를 그대로 보입니다.">
        {ir.data ? <FlagList flags={flags} /> : ir.loading ? <LoadingBlock /> : null}
      </SectionCard>

      <SectionCard title="요약 · 신호 · 성격 seed" subtitle="코드가 만든 원문을 그대로 보입니다.">
        {state.data ? (
          <>
            <VerbatimBlock text={state.data.summary_text} label="summary_text" />
            <div className="mt-3 flex flex-col gap-2">
              <h3 className="m-0 text-sm text-muted-foreground">신호 {signals.length}개</h3>
              {signals.length === 0 ? (
                <p className="m-0 text-sm text-muted-foreground">신호가 없습니다.</p>
              ) : (
                <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
                  {signals.map(([key, s]) => (
                    <li key={key} className={s.known ? undefined : "text-muted-foreground"}>
                      <code>{`sig:${key}`}</code> {s.text}
                    </li>
                  ))}
                </ul>
              )}
              <h3 className="m-0 text-sm text-muted-foreground">character_seed</h3>
              {state.data.character_seed.length === 0 ? (
                <p className="m-0 text-sm text-muted-foreground">seed 가 없습니다.</p>
              ) : (
                <span className={BADGE_GROUP}>
                  {state.data.character_seed.map((c, i) => (
                    <Badge key={`${c.tag}#${i}`} tone="info" title={`${c.rule} · ${c.text}`}>
                      {c.tag}
                    </Badge>
                  ))}
                </span>
              )}
            </div>
          </>
        ) : state.loading ? null : isNotReady(state.error) ? (
          <NotReadyBlock what="스냅샷 요약" />
        ) : (
          <EmptyBlock title="요약이 없습니다." />
        )}
      </SectionCard>

      {state.data ? <MarginCard rows={marginRows(state.data)} reqAbsent={state.data.missing?.req_absent} /> : null}

      <SectionCard title="노드" subtitle="IR 노드 표(part=ir 응답의 nodes) — kind 로 거릅니다.">
        {ir.data ? (
          <>
            <NodeTable nodes={nodes} onPick={(n) => setPickedNode((cur) => (cur?.nid === n.nid ? null : n))} picked={pickedNode?.nid ?? null} />
            {pickedNode ? (
              // 노드마다 다시 마운트한다 — 앞 노드에서 연 확인(병합 · 되돌리기 · 확정)과 고른 병합 대상이 새 노드의 패널 아래로 넘어가
              // 앞 노드의 키를 바꾸지 않게(07e7af4 의 대상 화면과 같은 꼴).
              <KeyLedgerPanel key={pickedNode.nid} node={pickedNode} nodes={nodes} onClose={() => setPickedNode(null)} />
            ) : null}
          </>
        ) : ir.loading ? (
          <LoadingBlock />
        ) : (
          <EmptyBlock title="노드가 없습니다." />
        )}
      </SectionCard>

      <SectionCard title="엣지" subtitle="관통 깊이는 하한일 때 ≥ 로 표기합니다.">
        {ir.data ? <EdgeTable edges={edges} /> : ir.loading ? <LoadingBlock /> : <EmptyBlock title="엣지가 없습니다." />}
      </SectionCard>

      <SectionCard title="조립 그래프" subtitle="계획 §8.2.4 의 mermaid 그래프 자리입니다(엣지 300 초과 시 상위 서브어셈블리 축약).">
        <NotReadyBlock what="조립 그래프" />
      </SectionCard>

      <SectionCard title="롤업" subtitle="서브어셈블리 접두별 리프·엣지 집계(rollups.by_assembly).">
        {ir.data ? <RollupBlock rollups={rollups} /> : ir.loading ? <LoadingBlock /> : <EmptyBlock title="롤업이 없습니다." />}
      </SectionCard>

      <SectionCard title="dims_named">
        {ir.data ? <DimsTable dims={dims} /> : ir.loading ? <LoadingBlock /> : <EmptyBlock title="명명 치수가 없습니다." />}
      </SectionCard>

      <SectionCard title="규칙 위반(rule_hits)">
        {isNotReady(ruleHits.error) ? (
          <NotReadyBlock what="rule_hits" />
        ) : (
          <ErrorBanner error={ruleHits.error} onRetry={ruleHits.reload} />
        )}
        {ruleHits.loading && !ruleHits.data ? <LoadingBlock /> : null}
        {ruleHits.data ? <RuleHitTable hits={ruleHits.data.rule_hits} /> : null}
      </SectionCard>

      <SectionCard title="경고">
        {ir.data ? <WarningTable warnings={warnings} /> : ir.loading ? <LoadingBlock /> : <EmptyBlock title="경고가 없습니다." />}
      </SectionCard>

      <SectionCard title="호출 로그" subtitle="근거 참조는 tool:&lt;call_id&gt; 형식입니다.">
        {isNotReady(calls.error) ? (
          <NotReadyBlock what="호출 로그" />
        ) : (
          <ErrorBanner error={calls.error} onRetry={calls.reload} />
        )}
        {calls.loading && !calls.data ? <LoadingBlock /> : null}
        {calls.data ? <CallTable calls={calls.data.calls} /> : null}
      </SectionCard>
    </>
  );
}
