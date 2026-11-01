// 비교 화면 — base/target 선택·SameAsResolver·게이트·diff 생성·비교 가능성(ECAD · 파서 세대)·3층 DiffView·사건·선례·타깃 만들기(계획 §8.2.4 ComparePage 행).
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { GitCompare, Target } from "lucide-react";
import { ApiError, isNotReady, riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { SectionCard } from "../components/SectionCard";
import type { Column } from "../components/DataTable";
import { DataTable, KeyValueTable } from "../components/DataTable";
import { EmptyBlock, ErrorBanner, LoadingBlock, NotReadyBlock } from "../components/StateBlocks";
import { Badge } from "../components/Badge";
import { GateVerdictBadge } from "../components/GateBanner";
import { SameAsResolver } from "../components/SameAsResolver";
import { LockNote } from "../components/LockNote";
import { Banner, Button, FormField, FormGrid, Mono, PageHeader, Select, SubPanel } from "../ui/primitives";
import { fmtCell, fmtEpoch } from "../format";
import {
  caveatTitle,
  diffRows,
  ecadComparabilityLine,
  excludedCounts,
  excludedLabel,
  parityWord,
  parserGenerationDiffers,
  parserGenerationNote,
} from "../lib/compareView";
import type { DiffRow } from "../lib/compareView";
import { weakerRole, writeAccess } from "../lib/access";
import type { Comparability, DiffBlocked, DiffEventRow, DiffLayer, GateRecord, Precedents, ProjectCard } from "../types";

const LAYERS: Array<{ layer: DiffLayer; label: string }> = [
  { layer: "structural", label: "구조" },
  { layer: "parametric", label: "파라메트릭" },
  { layer: "semantic", label: "의미" },
];
/** summary_text 각 줄의 각주 — `[c:<cid>]`. */
const FOOTNOTE_RE = /\[c:([^\]]+)\]/g;

function SnapshotPicker({
  label,
  field,
  projects,
  projectId,
  onProjectChange,
  value,
  onChange,
}: {
  label: string;
  /** 서버·주소에서 쓰는 원시 이름(base · target) — 사람 말 라벨 옆에 작게 둔다. */
  field: string;
  projects: ProjectCard[];
  projectId: string;
  onProjectChange: (projectId: string) => void;
  value: string;
  onChange: (snapshotId: string) => void;
}) {
  const detail = useAsync((signal) => riskApi.getProject(projectId, { signal }), [projectId], projectId !== "");

  return (
    <SubPanel
      title={
        <span className="flex items-baseline gap-1.5">
          {label}
          <Mono className="text-[0.7rem] opacity-70">{field}</Mono>
        </span>
      }
    >
      <FormField label="과제">
        <Select
          value={projectId}
          onChange={(e) => {
            onProjectChange(e.target.value);
            onChange("");
          }}
        >
          <option value="">선택</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.code} · {p.name}
            </option>
          ))}
        </Select>
      </FormField>
      {isNotReady(detail.error) ? (
        <NotReadyBlock what="과제 상세" />
      ) : (
        <ErrorBanner error={detail.error} onRetry={detail.reload} />
      )}
      <FormField label="스냅샷">
        <Select value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">선택</option>
          {(detail.data?.snapshots ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.id} · {fmtEpoch(s.created_at)}
              {s.degraded ? ` · 강등 ${s.degraded}` : ""}
            </option>
          ))}
        </Select>
      </FormField>
      {detail.loading && !detail.data ? <LoadingBlock label="스냅샷 목록을 불러오는 중." /> : null}
      {value ? (
        <p className="m-0 text-xs text-muted-foreground">
          snapshot_id <code>{value}</code>
        </p>
      ) : null}
    </SubPanel>
  );
}

/** parity 한 칸 — 같음 · 다름 · 모름(잴 입력이 없었다). */
function Parity({ value }: { value: boolean | null | undefined }) {
  const p = parityWord(value);
  return <Badge tone={p.tone}>{p.label}</Badge>;
}

/** '파서 세대 다름' 배지(B34 107 · §3.3.6) — 수치 변화의 일부가 파서 차이일 수 있다. 같으면 그리지 않는다. */
export function ParserGenerationBadge({ comparability }: { comparability: Partial<Comparability> | null | undefined }) {
  if (!parserGenerationDiffers(comparability)) return null;
  return (
    <Badge tone="warn" title={parserGenerationNote(comparability)}>
      파서 세대 다름
    </Badge>
  );
}

/** 비교 가능성 표 — 잣대마다 서버 값을 그대로 보이고, ECAD 한 줄과 '파서 세대 다름' 을 더한다(ecad-1031 §8 · B34 107). */
function ComparabilityTable({ comp }: { comp: Comparability }) {
  const ecad = ecadComparabilityLine(comp);
  return (
    <KeyValueTable
      rows={[
        {
          label: "잣대 일치(G7)",
          hint: "G7",
          value: (
            <span className="inline-flex flex-wrap items-center gap-1.5">
              <GateVerdictBadge record={comp.G7} />
              {comp.G7.detail.length > 0 ? (
                <span className="text-xs text-muted-foreground">{comp.G7.detail.map((d) => fmtCell(d)).join(" · ")}</span>
              ) : null}
            </span>
          ),
        },
        {
          label: "파서 세대",
          hint: "app_version_parity · adapter_parity",
          value: (
            <span className="inline-flex flex-wrap items-center gap-1.5">
              {parserGenerationDiffers(comp) ? <ParserGenerationBadge comparability={comp} /> : <Badge tone="ok">같음</Badge>}
              <span className="text-xs text-muted-foreground">
                소스 앱 판 {parityWord(comp.app_version_parity).label} · 어댑터 {parityWord(comp.adapter_parity).label}
              </span>
            </span>
          ),
        },
        {
          label: "ECAD",
          hint: "comparability.ecad",
          value: ecad ? (
            <span className="flex flex-col gap-0.5">
              <span>{ecad.sides}</span>
              {ecad.note ? <span className="text-xs text-muted-foreground">{ecad.note}</span> : null}
              {comp.ecad && comp.ecad.adapter_parity === false ? (
                <span className="text-xs text-muted-foreground">ECAD 어댑터 세대가 달라 ECAD 항목 · 사건에 parser_differs 가 붙었습니다.</span>
              ) : null}
            </span>
          ) : (
            <span className="text-muted-foreground">이 서버는 ECAD 칸을 주지 않습니다.</span>
          ),
        },
        { label: "공차", hint: "tol_parity", value: <Parity value={comp.tol_parity} /> },
        { label: "단위", hint: "unit_parity", value: <Parity value={comp.unit_parity} /> },
        {
          label: "해석 결과",
          hint: "result_parity · result_reason",
          value: (
            <span className="inline-flex flex-wrap items-center gap-1.5">
              <Parity value={comp.result_parity} />
              {comp.result_reason ? <span className="text-xs text-muted-foreground">{comp.result_reason}</span> : null}
            </span>
          ),
        },
        { label: "검출 범위", hint: "scope_parity", value: <Parity value={comp.scope_parity} /> },
        { label: "좌표계", hint: "coordinate_ok", value: <Parity value={comp.coordinate_ok} /> },
        { label: "IR 판", hint: "ir_version_parity", value: <Parity value={comp.ir_version_parity} /> },
        {
          label: "소스 응답 꼴",
          hint: "source_schema_parity",
          value: (
            <span className="inline-flex flex-wrap items-center gap-1.5">
              <Parity value={comp.source_schema_parity} />
              {(comp.source_schema_drift_kinds ?? []).length > 0 ? (
                <span className="text-xs text-muted-foreground">{(comp.source_schema_drift_kinds ?? []).join(" · ")}</span>
              ) : null}
            </span>
          ),
        },
        { label: "캡처 완주", hint: "capture_parity", value: <Parity value={comp.capture_parity} /> },
        { label: "주 소스", hint: "primary_source_parity", value: <Parity value={comp.primary_source_parity} /> },
        {
          label: "차단",
          hint: "base_blocked · target_blocked",
          value:
            comp.base_blocked || comp.target_blocked ? (
              <Badge tone="bad">{comp.base_blocked ? "기준 차단" : ""}{comp.base_blocked && comp.target_blocked ? " · " : ""}{comp.target_blocked ? "비교 대상 차단" : ""}</Badge>
            ) : (
              <span className="text-muted-foreground">없음</span>
            ),
        },
      ]}
    />
  );
}

function DiffView({
  diffId,
  semanticBlocked,
  onProject,
}: {
  diffId: string;
  semanticBlocked: boolean;
  /** 비교 본문의 과제(대상 과제 — diff_json.project_id)를 머리에 알린다 — '타깃 만들기' 를 그 과제의 내 역할로 가른다(OI-2). */
  onProject?: (projectId: string) => void;
}) {
  const doc = useAsync((signal) => riskApi.getDiff(diffId, { signal }), [diffId]);
  const docProject = doc.data?.project_id ?? "";
  useEffect(() => {
    if (docProject) onProject?.(docProject);
  }, [docProject, onProject]);
  const summary = useAsync((signal) => riskApi.getDiffSummary(diffId, { signal }), [diffId]);
  const events = useAsync((signal) => riskApi.getDiffEvents(diffId, { signal }), [diffId]);
  const precedents = useAsync((signal) => riskApi.getPrecedents(diffId, { signal }), [diffId]);
  const [selectedCid, setSelectedCid] = useState<string | null>(null);

  const rows = useMemo(() => (doc.data ? diffRows(doc.data) : []), [doc.data]);
  /** 제외 사유별 건수 — 항목은 diff 에 남고 의미 사건만 생기지 않는다(§3.3.6). ECAD 항목은 그 말로 센다. */
  const excluded = useMemo(() => excludedCounts(rows), [rows]);
  const ecad = doc.data ? ecadComparabilityLine(doc.data.comparability) : null;
  const lines = (summary.data?.summary_text ?? "").split("\n").filter((l) => l.trim() !== "");

  const itemColumns: Column<DiffRow>[] = [
    { key: "cid", header: "cid", cell: (d) => <code>{d.cid}</code>, nowrap: true },
    { key: "code", header: "code", cell: (d) => d.code, nowrap: true },
    { key: "subject", header: "subject", cell: (d) => d.subject || "-" },
    { key: "before", header: "before", cell: (d) => fmtCell(d.before) },
    { key: "after", header: "after", cell: (d) => fmtCell(d.after) },
    { key: "delta", header: "delta", cell: (d) => fmtCell(d.delta), nowrap: true },
    {
      key: "excluded",
      header: "제외 사유",
      hint: "excluded_reason",
      nowrap: true,
      cell: (d) =>
        d.excluded_reason ? (
          <Badge tone="muted" title={d.excluded_reason}>
            {excludedLabel(d.excluded_reason, d.isEcad)}
          </Badge>
        ) : (
          "-"
        ),
    },
    {
      key: "caveat",
      header: "주의",
      hint: "caveat",
      nowrap: true,
      cell: (d) =>
        d.caveat ? (
          <Badge tone="warn" title={caveatTitle(d, doc.data?.comparability) ?? undefined}>
            {d.caveat === "parser_differs" ? "파서 세대 다름" : d.caveat}
          </Badge>
        ) : (
          "-"
        ),
    },
  ];

  const eventColumns: Column<DiffEventRow>[] = [
    { key: "cid", header: "cid", cell: (e) => <code>{e.cid}</code>, nowrap: true },
    { key: "code", header: "code", cell: (e) => e.code, nowrap: true },
    { key: "change_kind", header: "change_kind", cell: (e) => e.change_kind ?? "-", nowrap: true },
    { key: "confidence", header: "confidence", cell: (e) => e.confidence ?? "-", nowrap: true },
    {
      key: "excluded",
      header: "제외 사유",
      hint: "excluded_reason",
      cell: (e) => (e.excluded_reason ? <Badge tone="muted">{e.excluded_reason}</Badge> : "-"),
      nowrap: true,
    },
    { key: "text", header: "text", cell: (e) => e.text },
  ];

  return (
    <>
      {/* 비교할 수 없는 두 스냅샷의 diff 를 읽는 것은 무의미하므로 그 판정을 요약보다 위에 둔다. */}
      <SectionCard
        title="비교 가능성(comparability)"
        subtitle="판정은 서버가 계산한 값입니다 — 다름이어도 diff 는 만들어지고, 막는 것은 G6 하나입니다."
        actions={doc.data ? <ParserGenerationBadge comparability={doc.data.comparability} /> : null}
      >
        <div className="flex flex-col gap-3">
          {isNotReady(doc.error) ? (
            <NotReadyBlock what="diff 본문" />
          ) : (
            <ErrorBanner error={doc.error} onRetry={doc.reload} />
          )}
          {doc.loading && !doc.data ? <LoadingBlock /> : null}
          {ecad?.phase1Note ? <Banner tone="info" title={ecad.phase1Note} /> : null}
          {doc.data ? (
            <>
              <ComparabilityTable comp={doc.data.comparability} />
              <KeyValueTable
                rows={[
                  {
                    label: "제외 항목",
                    hint: "items[].excluded_reason",
                    value:
                      excluded.length === 0 ? (
                        <span className="text-muted-foreground">없음</span>
                      ) : (
                        <span className="inline-flex flex-wrap items-center gap-1">
                          {excluded.map((e) => (
                            <Badge key={`${e.reason}|${e.isEcad}`} tone="muted" title={e.reason}>
                              {excludedLabel(e.reason, e.isEcad)} {e.n}건
                            </Badge>
                          ))}
                        </span>
                      ),
                  },
                  { label: "짝", hint: "pair_kind", value: doc.data.pair_kind === "cross_project" ? "다른 과제" : "같은 과제 리비전" },
                ]}
              />
            </>
          ) : null}
        </div>
      </SectionCard>

      <SectionCard title="diff 요약" subtitle="코드가 만든 summary_text 원문입니다 — 화면이 다시 쓰지 않습니다.">
        <div className="flex flex-col gap-3">
          {isNotReady(summary.error) ? (
            <NotReadyBlock what="diff 요약" />
          ) : (
            <ErrorBanner error={summary.error} onRetry={summary.reload} />
          )}
          {summary.loading && !summary.data ? <LoadingBlock /> : null}
          {summary.data ? (
            <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
              {lines.map((line, i) => {
                const cids = Array.from(line.matchAll(FOOTNOTE_RE)).map((m) => m[1]);
                return (
                  <li key={i}>
                    {line}
                    {cids.map((cid) => (
                      <Button
                        key={cid}
                        type="button"
                        // ghost 는 hover 전에 아무 표시가 없다 — 본문 안에 박힌 글자라 누를 수 있다는
                        // 사실이 사라진다(레거시 .rr-btn-quiet 는 밑줄을 줬다). link 가 그 자리다.
                        variant="link"
                        size="sm"
                        className="ml-1 h-auto p-0 align-baseline font-mono text-xs"
                        onClick={() => setSelectedCid(`c:${cid}`)}
                      >
                        {cid}
                      </Button>
                    ))}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </div>
      </SectionCard>

      {/* 식별자는 대조할 때만 필요하고 판정 · 요약보다 먼저 읽을 것이 아니다(지우지는 않는다). */}
      <SectionCard title="비교한 두 스냅샷" subtitle="diff 본문의 짝입니다.">
        <KeyValueTable
          rows={[
            {
              label: "기준 스냅샷",
              hint: "base.snapshot_id",
              value: doc.data ? (
                <span>
                  <code>{doc.data.base.snapshot_id}</code> {doc.data.base.label ? `«${doc.data.base.label}»` : ""}
                </span>
              ) : (
                "-"
              ),
            },
            {
              label: "비교 대상 스냅샷",
              hint: "target.snapshot_id",
              value: doc.data ? (
                <span>
                  <code>{doc.data.target.snapshot_id}</code> {doc.data.target.label ? `«${doc.data.target.label}»` : ""}
                </span>
              ) : (
                "-"
              ),
            },
          ]}
        />
      </SectionCard>

      <SectionCard title="diff 3층" subtitle="구조 · 파라메트릭 · 의미 층을 서버가 준 항목 그대로 보입니다.">
        {doc.data
          ? LAYERS.map(({ layer, label }) => {
              const layerRows = rows.filter((d) => d.layer === layer);
              const picked = layerRows.findIndex((d) => d.cid === selectedCid);
              return (
                <div key={layer} className="mt-3 flex flex-col gap-2">
                  <h3 className="m-0 text-sm text-muted-foreground">
                    <strong className="font-medium text-foreground">{label}</strong>{" "}
                    <span className="tabular-nums">{layerRows.length}건</span>
                  </h3>
                  {layer === "semantic" && (semanticBlocked || doc.data?.semantic.blocked_by) ? (
                    <Banner
                      tone="info"
                      title="의미층 차단(G2)."
                      detail="대응이 미확정이라 의미 사건을 만들지 않았습니다."
                    />
                  ) : null}
                  <DataTable
                    columns={itemColumns}
                    rows={layerRows}
                    rowKey={(d, i) => `${d.cid}#${i}`}
                    selectedKey={picked === -1 ? null : `${selectedCid}#${picked}`}
                    onRowClick={(d) => setSelectedCid(d.cid)}
                    empty={`${label} 층 변경이 없습니다.`}
                  />
                </div>
              );
            })
          : null}
        {selectedCid ? (
          <p className="m-0 mt-2 text-xs text-muted-foreground">
            고른 항목 <code>{selectedCid}</code> — {rows.find((r) => r.cid === selectedCid)?.text ?? "본문에서 찾지 못했습니다."}
          </p>
        ) : null}
      </SectionCard>

      <SectionCard title="조립 그래프(before/after)" subtitle="계획 §8.2.4 의 mermaid 그래프 자리입니다.">
        <NotReadyBlock what="조립 그래프" />
      </SectionCard>

      <SectionCard title="사건(events)" subtitle="의미층 사건 펼침 표입니다.">
        <div className="flex flex-col gap-3">
          {isNotReady(events.error) ? (
            <NotReadyBlock what="사건 표" />
          ) : (
            <ErrorBanner error={events.error} onRetry={events.reload} />
          )}
          {events.loading && !events.data ? <LoadingBlock /> : null}
          {events.data ? (
            <DataTable
              columns={eventColumns}
              rows={events.data.events}
              rowKey={(e, i) => `${e.cid}#${i}`}
              onRowClick={(e) => setSelectedCid(e.cid)}
              empty="사건이 없습니다."
            />
          ) : null}
        </div>
      </SectionCard>

      <SectionCard title="선례" subtitle="변화 종류별 선례 수치(rr_delta_priors)와 같은 주체의 등록부 행입니다.">
        <div className="flex flex-col gap-3">
          {isNotReady(precedents.error) ? (
            <NotReadyBlock what="선례" />
          ) : (
            <ErrorBanner error={precedents.error} onRetry={precedents.reload} />
          )}
          {precedents.loading && !precedents.data ? <LoadingBlock /> : null}
          {precedents.data ? <PrecedentTables data={precedents.data} /> : null}
        </div>
      </SectionCard>
    </>
  );
}

function PrecedentTables({ data }: { data: Precedents }) {
  return (
    <>
      <DataTable
        columns={[
          { key: "kind", header: "change_kind", cell: (r) => r.change_kind, nowrap: true },
          { key: "mech", header: "mechanism", cell: (r) => [r.mechanism, r.mechanism_detail].filter(Boolean).join(" · ") || "-" },
          { key: "raised", header: "제기", cell: (r) => String(r.n_raised), align: "right", nowrap: true },
          { key: "targets", header: "대상", cell: (r) => String(r.n_targets), align: "right", nowrap: true },
          { key: "verified", header: "검증", cell: (r) => String(r.n_verified), align: "right", nowrap: true },
          { key: "dismissed", header: "기각", cell: (r) => String(r.n_dismissed), align: "right", nowrap: true },
        ]}
        rows={data.delta_priors}
        rowKey={(r, i) => `${r.change_kind}#${r.mechanism ?? ""}#${i}`}
        empty="선례 수치가 없습니다."
      />
      <DataTable
        columns={[
          { key: "ref", header: "등록부", cell: (r) => <code>{r.reg_ref}</code>, nowrap: true },
          { key: "project", header: "과제", cell: (r) => r.project_code ?? "-", nowrap: true },
          { key: "severity", header: "severity", cell: (r) => r.severity ?? "-", nowrap: true },
          { key: "status", header: "status", cell: (r) => r.status, nowrap: true },
          { key: "claim", header: "claim", cell: (r) => r.claim ?? "-" },
        ]}
        rows={data.clusters}
        rowKey={(r) => r.reg_ref}
        empty="같은 주체의 등록부 행이 없습니다."
      />
    </>
  );
}

/** 409 gate_blocked 의 막힌 쪽 G6 — 기준 · 비교 대상 어느 쪽인지와 판정. */
function BlockedSides({ blocked }: { blocked: DiffBlocked }) {
  const sides: Array<[string, GateRecord | undefined]> = [
    ["기준", blocked.gates.base],
    ["비교 대상", blocked.gates.target],
  ];
  return (
    <span className="inline-flex flex-wrap items-center gap-2 text-sm">
      {sides
        .filter(([, record]) => record)
        .map(([side, record]) => (
          <span key={side} className="inline-flex items-center gap-1">
            {side} G6 <GateVerdictBadge record={record} />
          </span>
        ))}
      <span className="text-muted-foreground">까닭 {blocked.reason}</span>
    </span>
  );
}

export default function ComparePage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const base = params.get("base") ?? "";
  const target = params.get("target") ?? "";
  const diffId = params.get("diff") ?? "";

  const projects = useAsync((signal) => riskApi.listProjects({ signal }), []);
  const [baseProject, setBaseProject] = useState("");
  const [targetProject, setTargetProject] = useState("");
  const [diffProject, setDiffProject] = useState("");
  /** 과제 목록 카드의 내 역할(my_role) — 모르는 과제(고르기 전 · 목록 밖)는 null 이라 잠그지 않는다(OI-2). */
  const roleOf = (id: string) => (id ? projects.data?.projects.find((p) => p.id === id)?.my_role ?? null : null);
  // 비교 만들기 · 쌍 대응 결정은 두 과제 모두 편집자 이상이다(MB-13 · MB-14) — 더 약한 역할로 가른다. 타깃은 비교의 대상 과제다.
  const pairRole = weakerRole(roleOf(baseProject), roleOf(targetProject));
  const pairAccess = writeAccess(pairRole);
  const targetAccess = writeAccess(roleOf(diffProject));
  const [blocked, setBlocked] = useState<DiffBlocked | null>(null);
  const [g2, setG2] = useState<GateRecord | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const semanticBlocked = g2 !== null && g2.pass === false;
  const ready = base !== "" && target !== "" && base !== target;

  function setParam(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value === "") next.delete(name);
    else next.set(name, value);
    next.delete("diff");
    setParams(next);
    setBlocked(null);
  }

  /** 비교 상대는 같은 과제가 기본이다 — target 과제를 아직 안 골랐으면 base 과제를 따라간다. */
  function chooseBaseProject(id: string) {
    setBaseProject(id);
    if (targetProject === "") setTargetProject(id);
  }

  async function createDiff() {
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const created = await riskApi.createDiff({ base_snapshot_id: base, target_snapshot_id: target });
      setBlocked(null);
      const next = new URLSearchParams(params);
      next.set("diff", created.diff_id);
      setParams(next);
    } catch (err) {
      // G6 차단은 code 로 가른다 — 본문의 막힌 쪽 G6 레코드를 보인다(detail 은 오류 본문 최상위에 펼쳐진다).
      if (err instanceof ApiError && err.code === "gate_blocked") {
        const body = err.body as Partial<DiffBlocked> | null;
        setBlocked(body?.gates ? { gates: body.gates, reason: String(body.reason ?? "") } : null);
      }
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function createTarget() {
    if (diffId === "") return;
    setBusy(true);
    setError(null);
    try {
      const created = await riskApi.createTarget({ kind: "diff", ref_id: diffId, consent: true });
      navigate(`/targets/${encodeURIComponent(created.target_key)}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        crumb={
          <>
            <Link to="/">과제</Link>
            <span aria-hidden="true">/</span>
            <span>비교</span>
          </>
        }
        title="스냅샷 비교"
        // id 는 제목이 아니라 보조 사실이다. diff 가 아직 없으면 그 사실(없음)을 그대로 적는다.
        subtitle={
          diffId ? (
            <>
              <span className="font-mono opacity-60">diff_id</span>{" "}
              <Mono className="break-all">{diffId}</Mono>
            </>
          ) : (
            "두 스냅샷을 골라 구조 · 파라메트릭 · 의미 3층 diff 를 만듭니다."
          )
        }
        // 'diff 생성' 은 바로 아래 고르기 칸의 상태(두 스냅샷·G6)에 달려 있어 그 칸 옆에 남긴다.
        actions={
          diffId ? (
            <Button type="button" onClick={createTarget} disabled={busy || !targetAccess.allowed}
                    title={targetAccess.reason ?? undefined}>
              <Target className="size-4" aria-hidden="true" />
              타깃 만들기
            </Button>
          ) : null
        }
      />
      {diffId ? <LockNote access={targetAccess} /> : null}

      {/* diff 생성·타깃 만들기 둘이 같은 `error` 를 쓴다. 버튼 하나가 머리말로 올라갔으므로 배너도
          화면 맨 위에 둔다 — 아래 카드 안에 두면 타깃 만들기 실패가 긴 화면 밑에서 조용히 뜬다. */}
      <ErrorBanner error={error} />

      {/* diff 가 있으면 그 판정이 먼저다. 고르기·same-as 는 그 diff 를 만든 수단이라 아래로 내렸다. */}
      {diffId ? <DiffView diffId={diffId} semanticBlocked={semanticBlocked} onProject={setDiffProject} /> : null}

      <SectionCard title="비교할 스냅샷" subtitle="두 스냅샷의 구조 · 파라메트릭 · 의미 3층 diff 를 만듭니다.">
        <div className="flex flex-col gap-3">
          {isNotReady(projects.error) ? (
            <NotReadyBlock what="과제 목록" />
          ) : (
            <ErrorBanner error={projects.error} onRetry={projects.reload} />
          )}
          {projects.loading && !projects.data ? <LoadingBlock label="과제 목록을 불러오는 중." /> : null}
          {projects.data && projects.data.projects.length === 0 ? (
            <EmptyBlock title="과제가 없습니다." hint="먼저 과제를 등록하고 스냅샷을 동결하세요." />
          ) : null}
          <FormGrid className="[grid-template-columns:repeat(auto-fit,minmax(16rem,1fr))]">
            <SnapshotPicker
              label="기준 스냅샷"
              field="base"
              projects={projects.data?.projects ?? []}
              projectId={baseProject}
              onProjectChange={chooseBaseProject}
              value={base}
              onChange={(v) => setParam("base", v)}
            />
            <SnapshotPicker
              label="비교 대상 스냅샷"
              field="target"
              projects={projects.data?.projects ?? []}
              projectId={targetProject}
              onProjectChange={setTargetProject}
              value={target}
              onChange={(v) => setParam("target", v)}
            />
          </FormGrid>
          {blocked ? (
            <Banner title="G6 로 차단된 스냅샷입니다 — diff 를 만들 수 없습니다." detail={<BlockedSides blocked={blocked} />} />
          ) : null}
          {semanticBlocked ? (
            <Banner tone="info" title="의미층 차단(G2)." detail={`대응 미확정 ${g2?.count ?? "?"}건 — 아래 same-as 확정에서 고릅니다.`} />
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              onClick={createDiff}
              disabled={!ready || busy || blocked !== null || !pairAccess.allowed}
              title={blocked ? "G6 로 차단돼 diff 를 만들 수 없습니다." : pairAccess.reason ?? undefined}
            >
              <GitCompare className="size-4" aria-hidden="true" />
              diff 생성
            </Button>
            {!ready ? <span className="text-sm text-muted-foreground">서로 다른 두 스냅샷을 고르세요.</span> : null}
            <LockNote access={pairAccess} />
          </div>
        </div>
      </SectionCard>

      <SectionCard title="same-as 확정" subtitle="자동 매칭을 사람이 확정합니다 — 소스 앱에는 쓰지 않습니다.">
        {ready ? (
          <SameAsResolver base={base} target={target} onG2={setG2} role={pairRole} />
        ) : (
          <EmptyBlock title="스냅샷을 두 개 고르면 매칭 후보가 나옵니다." />
        )}
      </SectionCard>
    </>
  );
}
