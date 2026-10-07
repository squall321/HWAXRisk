// 스냅샷 화면 — 개요·강등 플래그·게이트·노드/엣지·롤업·dims·rule_hits·character_seed·warnings·호출 로그(계획 §8.2.4 SnapshotPage 행). ProjectPage 가 ?snapshot= 일 때 그린다.
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
import { GateBanner, GateTable, isGateFailing } from "../components/GateBanner";
import { Banner, Button, Input, Mono, PageHeader } from "../ui/primitives";
import { fmtCell, fmtCounts, fmtEpoch, fmtJson, fmtNum } from "../format";
import type { DimNamed, Gate, IrEdge, IrNode, IrWarning, JsonObject, RuleHit, SnapshotCall } from "../types";

/** 스냅샷(단일) 에 나오는 게이트. G7 은 pair 전용이라 여기에 없다(§3.2.1). */
const SNAP_GATE_IDS = ["G1", "G2", "G3", "G4", "G5", "G6"];

/** 게이트 id → 계획 §3.2.2 의 이름. 판정·사유는 서버가 준 값(effect·message)이 정본이다. */
const GATE_LABEL: Record<string, string> = {
  G1: "dup_or_anon_names",
  G2: "sameas_pending",
  G3: "iface_unconfirmed",
  G4: "coordinate",
  G5: "partial_scope",
  G6: "unit_scale",
  G7: "yardstick_parity(pair 전용)",
};

/**
 * 강등·결측 플래그 사전 — `missing.*`(§3.2.1) 과 어댑터 `degraded[]` 코드(§2.2)를 한 자리에서 읽는다.
 * 사전에 없는 코드는 서버 문자열을 그대로 보인다.
 */
const FLAG_LABEL: Record<string, string> = {
  ecad_absent: "ecad 소스 없음",
  dyna_absent: "dyna 소스 없음",
  dyna_result_absent: "dyna 결과 리포트 없음",
  result_kind_mismatch: "결과 kind 가 서로 다름",
  world_transform_absent: "world 좌표 변환 없음",
  volume_null: "부피 값 없음",
  material_density_unsourced: "밀도 출처 없음",
  mcp_degraded: "REST 원문 없이 MCP 로만 캡처",
  no_world_transform: "어댑터가 world 좌표 변환을 얻지 못함",
  no_node_id: "소스 노드 id 없음(이름으로 대응)",
  volume_null_pre_d168: "부피·재질이 전부 null(재파싱 대상)",
  tol_config_unknown: "공차 설정 해시 없음",
  interfaces_truncated: "계면 목록 잘림",
  edges_truncated: "엣지 목록 잘림",
  components_truncated: "ecad 컴포넌트 목록 잘림",
  nets_truncated: "ecad 넷 목록 잘림",
  truncated_scan: "스캔 잘림",
  no_secid: "secid 없음",
  detect_absent: "detect 산출 없음",
  report_parts_mismatch: "리포트 파트명과 K파일 이름 불일치",
  unit_converted_mil: "mil 을 mm 로 환산",
};

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

function NodeTable({ nodes }: { nodes: IrNode[] }) {
  const [q, setQ] = useState("");
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return nodes;
    return nodes.filter((n) =>
      [n.nid, n.name, n.ckey ?? "", n.dn ?? "", n.geom_fp ?? ""].some((v) => v.toLowerCase().includes(needle)),
    );
  }, [nodes, q]);

  const columns: Column<IrNode>[] = [
    { key: "nid", header: "nid", cell: (n) => <code>{n.nid}</code>, nowrap: true },
    { key: "name", header: "name", cell: (n) => n.name },
    { key: "ckey", header: "ckey", cell: (n) => (n.ckey ? <code>{n.ckey}</code> : "-"), nowrap: true },
    { key: "dn", header: "dn", cell: (n) => n.dn ?? "-" },
    { key: "geom_fp", header: "geom_fp", cell: (n) => (n.geom_fp ? <code>{n.geom_fp}</code> : "-"), nowrap: true },
    {
      key: "flags",
      header: "flags",
      cell: (n) => (
        <span className={BADGE_GROUP}>
          {n.flags.map((f) => (
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
        <Input
          className="max-w-xs"
          placeholder="nid · name · ckey · dn 검색"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <span className="text-sm text-muted-foreground">
          {filtered.length} / {nodes.length} 개
        </span>
      </div>
      <DataTable columns={columns} rows={filtered} rowKey={(n) => n.nid} empty="노드가 없습니다." />
    </>
  );
}

function EdgeTable({ edges }: { edges: IrEdge[] }) {
  const columns: Column<IrEdge>[] = [
    { key: "eid", header: "eid", cell: (e) => <code>{e.eid}</code>, nowrap: true },
    { key: "kind", header: "kind", cell: (e) => <StatusBadge value={e.kind} />, nowrap: true },
    { key: "status", header: "status", cell: (e) => <StatusBadge value={e.status} />, nowrap: true },
    { key: "a", header: "a", cell: (e) => <code>{e.a}</code>, nowrap: true },
    { key: "b", header: "b", cell: (e) => <code>{e.b}</code>, nowrap: true },
    { key: "min_gap", header: "min_gap", cell: (e) => fmtNum(e.min_gap), align: "right", nowrap: true },
    {
      key: "pen",
      header: "penetration_depth",
      align: "right",
      nowrap: true,
      // 하한 표기는 서버 플래그를 그대로 옮긴 것이다.
      cell: (e) =>
        e.penetration_depth === null
          ? "-"
          : `${e.penetration_is_lower_bound ? "≥ " : ""}${fmtNum(e.penetration_depth)}`,
    },
  ];
  return <DataTable columns={columns} rows={edges} rowKey={(e) => e.eid} empty="엣지가 없습니다." />;
}

function DimsTable({ dims }: { dims: DimNamed[] }) {
  const columns: Column<DimNamed>[] = [
    { key: "name", header: "name", cell: (d) => d.name, nowrap: true },
    { key: "kind", header: "kind", cell: (d) => d.kind, nowrap: true },
    { key: "unit", header: "unit", cell: (d) => d.unit ?? "-", nowrap: true },
    { key: "value", header: "value", cell: (d) => fmtNum(d.value), align: "right", nowrap: true },
    { key: "ref", header: "ref", cell: (d) => (d.ref ? <code>{d.ref}</code> : "-") },
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

function RuleHitTable({ hits }: { hits: RuleHit[] }) {
  const columns: Column<RuleHit>[] = [
    { key: "rule", header: "rule", cell: (h) => <code>{h.rule}</code>, nowrap: true },
    { key: "severity", header: "severity", cell: (h) => <SeverityBadge value={h.severity} />, nowrap: true },
    {
      key: "pass",
      header: "판정",
      cell: (h) => <Badge tone={h.pass ? "ok" : "bad"}>{h.pass ? "pass" : "fail"}</Badge>,
      nowrap: true,
    },
    { key: "found", header: "found", cell: (h) => h.found },
    { key: "why", header: "why_it_matters", cell: (h) => h.why_it_matters },
    { key: "fix", header: "fix_hint", cell: (h) => h.fix_hint },
  ];
  return <DataTable columns={columns} rows={hits} rowKey={(h, i) => `${h.rule}#${i}`} empty="규칙 위반이 없습니다." />;
}

function CallTable({ calls }: { calls: SnapshotCall[] }) {
  const columns: Column<SnapshotCall>[] = [
    { key: "ref", header: "참조", cell: (c) => <code>{`tool:${c.call_id}`}</code>, nowrap: true },
    { key: "app", header: "app_key", cell: (c) => c.app_key, nowrap: true },
    { key: "tool", header: "tool", cell: (c) => c.tool, nowrap: true },
    { key: "args", header: "args_digest", cell: (c) => (c.args_digest ? <code>{c.args_digest}</code> : "-") },
    { key: "ok", header: "ok", cell: (c) => <Badge tone={c.ok ? "ok" : "bad"}>{c.ok ? "ok" : "fail"}</Badge>, nowrap: true },
    { key: "at", header: "called_at", cell: (c) => fmtEpoch(c.called_at), nowrap: true },
  ];
  return <DataTable columns={columns} rows={calls} rowKey={(c) => c.call_id} empty="호출 로그가 없습니다." />;
}

/** 강등·결측 플래그 칩. 뜻은 사전에서 붙이고 값 자체는 서버 문자열 그대로다. */
function FlagList({ flags }: { flags: string[] }) {
  if (flags.length === 0) return <p className="m-0 text-sm text-muted-foreground">강등·결측 플래그가 없습니다.</p>;
  return (
    <span className={BADGE_GROUP}>
      {flags.map((f) => (
        <Badge key={f} tone="warn" title={FLAG_LABEL[f] ?? "사전에 없는 코드입니다."}>
          {f}
          {FLAG_LABEL[f] ? ` — ${FLAG_LABEL[f]}` : null}
        </Badge>
      ))}
    </span>
  );
}

/** 판정표가 담지 못하는 세 가지 — 게이트 이름, 이번 응답에 오지 않은 게이트, 값이 비어 있는 게이트. */
function GateSupplement({ gates }: { gates: Gate[] }) {
  const seen = new Set(gates.map((g) => g.id));
  const notJudged = SNAP_GATE_IDS.filter((id) => !seen.has(id));
  const unknown = gates.filter((g) => g.value === null).map((g) => g.id);
  return (
    <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
      <li className="text-muted-foreground">
        {SNAP_GATE_IDS.map((id) => `${id} ${GATE_LABEL[id]}`).join(" · ")}
      </li>
      {notJudged.length > 0 ? (
        <li>
          이번 응답에 오지 않은 게이트 —{" "}
          <span className={BADGE_GROUP}>
            {notJudged.map((id) => (
              <Badge key={id} tone="muted" title={GATE_LABEL[id]}>
                {id}
              </Badge>
            ))}
          </span>
        </li>
      ) : null}
      {unknown.length > 0 ? (
        <li>
          값이 비어 있는 게이트 — <code>{unknown.join(" · ")}</code>{" "}
          <span className="text-muted-foreground">이 게이트의 값이 비어 있습니다.</span>
        </li>
      ) : null}
      <li className="text-muted-foreground">G7 {GATE_LABEL.G7} 은 두 스냅샷을 비교할 때만 나옵니다.</li>
    </ul>
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

export default function SnapshotPage({ snapshotId }: { snapshotId: string }) {
  const navigate = useNavigate();
  const ir = useAsync((signal) => riskApi.getSnapshotIr(snapshotId, { signal }), [snapshotId]);
  const state = useAsync((signal) => riskApi.getSnapshotState(snapshotId, { signal }), [snapshotId]);
  const calls = useAsync((signal) => riskApi.getSnapshotCalls(snapshotId, { signal }), [snapshotId]);
  const ruleHits = useAsync((signal) => riskApi.getRuleHits(snapshotId, { signal }), [snapshotId]);

  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // 서버가 아직 없는 동안 필드가 비어 와도 화면이 살아 있게 기본값을 둔다.
  const dims = ir.data?.dims_named ?? [];
  const nodes = ir.data?.nodes ?? [];
  const edges = ir.data?.edges ?? [];
  const warnings = ir.data?.warnings ?? [];
  const missing = ir.data?.missing ?? [];
  const rollups = ir.data?.rollups ?? {};
  const gates = state.data?.gates ?? [];
  /** G6 fail 이면 서버가 diff·타깃 생성을 409 로 막는다(§3.2.2 effect=block). 화면은 그 사실만 옮긴다. */
  const blocked = isGateFailing(gates, "G6");
  /** §8.2.4 — volume·material 이 전부 null 이면 소스 앱에서 재파싱하라고만 알린다(앱은 쓰기를 하지 않는다). */
  const needsReparse = useMemo(() => {
    const relevant = dims.filter((d) => d.kind === "volume" || d.kind === "material");
    return relevant.length > 0 && relevant.every((d) => d.value === null);
  }, [dims]);

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
        title="스냅샷"
        subtitle={
          // id 는 제목이 아니라 보조 사실이다 — 사람이 읽는 이름은 '스냅샷' 이고 id 는 서버와 대조할 때 쓴다.
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            {/* 원시 필드명을 지우지 않는다 — 다른 라벨은 전부 hint 로 남겼는데 여기만 예외일 이유가 없다. */}
            <span>
              <span className="font-mono opacity-60">snapshot_id</span> <Mono>{snapshotId}</Mono>
            </span>
            {ir.data ? <span>동결 {fmtEpoch(ir.data.captured_at)}</span> : null}
            {ir.data && ir.data.kinds.length > 0 ? <span>소스 {ir.data.kinds.join(" · ")}</span> : null}
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
              title={blocked ? "G6 fail 인 스냅샷은 타깃을 만들 수 없습니다." : undefined}
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

      {/* 순서를 바꿨다 — 게이트를 첫 카드로 올렸다. G6 fail 하나가 '타깃 만들기' 를 막으므로 이 화면에서
          사람이 가장 먼저 알아야 할 판정이고, 예전에는 세 번째 카드에 묻혀 있었다. 아래 카드들은 그대로다. */}
      <SectionCard title="게이트" subtitle="G1~G6 판정은 서버가 계산한 값입니다(G7 은 비교 전용).">
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
                title="blocked — G6 fail."
                detail="diff 생성과 타깃 만들기가 409 로 막힙니다. 소스를 고쳐 새 스냅샷을 만들어야 합니다."
              />
            ) : null}
            <GateBanner gates={gates} />
            <GateTable gates={gates} />
            <GateSupplement gates={gates} />
          </>
        ) : null}
      </SectionCard>

      <SectionCard title="스냅샷 개요">
        {isNotReady(ir.error) ? <NotReadyBlock what="스냅샷 IR" /> : <ErrorBanner error={ir.error} onRetry={ir.reload} />}
        {ir.loading && !ir.data ? <LoadingBlock /> : null}
        {needsReparse ? (
          <Banner tone="info" title="재파싱이 필요합니다." detail="volume · material 값이 비어 있습니다.">
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
              { label: "소스", hint: "kinds", value: ir.data.kinds.join(" · ") || "-" },
              { label: "동결 시각", hint: "captured_at", value: fmtEpoch(ir.data.captured_at) },
              { label: "항목 수", hint: "counts", value: fmtCounts(ir.data.counts) },
              {
                label: "노드 · 엣지 · 명명 치수",
                hint: "nodes · edges · dims_named",
                value: `${nodes.length} · ${edges.length} · ${dims.length}`,
              },
              { label: "경고", hint: "warnings", value: `${warnings.length}건` },
            ]}
          />
        ) : null}
      </SectionCard>

      <SectionCard
        title="강등 플래그"
        subtitle="missing.* 와 어댑터 강등 코드(mcp_degraded 등)를 그대로 보입니다."
      >
        {ir.data ? <FlagList flags={missing} /> : ir.loading ? <LoadingBlock /> : null}
      </SectionCard>

      <SectionCard title="요약 · 신호 · 성격 seed" subtitle="코드가 만든 원문을 그대로 보입니다.">
        {state.data ? (
          <>
            <VerbatimBlock text={state.data.summary_text} label="summary_text" />
            <div className="mt-3 flex flex-col gap-2">
              <h3 className="m-0 text-sm text-muted-foreground">신호</h3>
              {state.data.signals.length === 0 ? (
                <p className="m-0 text-sm text-muted-foreground">신호가 없습니다.</p>
              ) : (
                <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
                  {state.data.signals.map((s) => (
                    <li key={s.key}>
                      <code>{s.key}</code> {s.text} {s.ref ? <code>{s.ref}</code> : null}
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

      <SectionCard title="노드" subtitle="IR 노드 표(part=ir 응답의 nodes).">
        {ir.data ? <NodeTable nodes={nodes} /> : ir.loading ? <LoadingBlock /> : <EmptyBlock title="노드가 없습니다." />}
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
