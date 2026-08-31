// 과제 화면 — 헤더·소스 카드 3장·스냅샷 동결·스냅샷 목록·dims·iface-ledger·성격 프로파일·유사 과제(계획 §8.2.4 ProjectPage 행). ?snapshot= 이면 같은 화면에 SnapshotPage 를 그린다.
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { riskApi } from "../api/risk.api";
import { POLL_MS, useAsync, useInterval } from "../hooks/useAsync";
import { CardGrid, SectionCard, VerbatimBlock } from "../components/SectionCard";
import type { Column } from "../components/DataTable";
import { DataTable, KeyValueTable } from "../components/DataTable";
import { GateBanner, GateTable } from "../components/GateBanner";
import { EmptyBlock, ErrorBanner, LoadingBlock } from "../components/StateBlocks";
import {
  Badge,
  ExternalSyncBadge,
  JobStateBadge,
  LevelBadge,
  SourceStatusBadge,
  StatusBadge,
  UnseatedBadge,
} from "../components/Badge";
import { fmtCounts, fmtEpoch } from "../format";
import { FACET_ORDER } from "../types";
import type {
  AdapterEntry,
  CharacterStatement,
  Gate,
  IfaceLedgerRow,
  JobHeader,
  ProjectDetail,
  SnapshotHeader,
  SourceKind,
  TargetHeader,
} from "../types";
import SnapshotPage from "./SnapshotPage";

const SOURCE_KINDS: SourceKind[] = ["mcad", "dyna", "ecad"];
const SNAPSHOT_KINDS: SourceKind[] = ["mcad", "dyna", "dyna_result", "ecad"];
const KIND_LABEL: Record<SourceKind, string> = {
  mcad: "MCAD",
  dyna: "DynaForge",
  dyna_result: "해석 결과",
  ecad: "ECAD",
};
const FACET_LABEL: Record<string, string> = {
  intent: "의도",
  constraint: "제약",
  anomaly: "이상",
  lineage: "계보",
  vulnerability: "취약",
  strength: "강점",
  tradeoff: "상충",
  unknown: "미상",
};
const STATEMENT_LAYERS: Array<{ status: CharacterStatement["status"]; label: string }> = [
  { status: "seed", label: "seed (L0)" },
  { status: "panel", label: "panel (L2)" },
  { status: "confirmed", label: "confirmed" },
];

function SourceCard({
  kind,
  detail,
  adapters,
  onChanged,
}: {
  kind: SourceKind;
  detail: ProjectDetail;
  adapters: AdapterEntry[];
  onChanged: () => void;
}) {
  const source = detail.sources.find((s) => s.kind === kind);
  const candidates = adapters.filter((a) => a.kind === kind);
  const [appKey, setAppKey] = useState("");
  const [ref, setRef] = useState("");
  const [bridge, setBridge] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const chosen = candidates.find((a) => (a.app ?? "") === appKey);
  const choices = chosen?.choices ?? [];
  const stub = kind === "ecad" && candidates.length === 0;

  async function link(event: React.FormEvent) {
    event.preventDefault();
    if (appKey.trim() === "" || ref.trim() === "") return;
    setBusy(true);
    setError(null);
    try {
      await riskApi.addSource(detail.project.id, {
        kind,
        app_key: appKey.trim(),
        ref: ref.trim(),
        bridge_declared: bridge,
      });
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rr-panel">
      <div className="rr-row rr-panel-head">
        <strong>{KIND_LABEL[kind]}</strong>
        <SourceStatusBadge value={source?.status ?? "unlinked"} />
      </div>
      {stub ? <p className="rr-muted">연결 대기(스텁) — 어댑터를 찾지 못했습니다.</p> : null}
      {source ? (
        <KeyValueTable
          rows={[
            { label: "app_key", value: source.app_key ?? "-" },
            { label: "ref", value: source.ref ?? "-" },
            { label: "bridge_declared", value: source.bridge_declared ? "true" : "false" },
            {
              label: "probe",
              value: source.probe ? (
                <span className="rr-row">
                  <Badge tone={source.probe.reachable ? "ok" : "bad"}>
                    {source.probe.reachable ? "reachable" : "unreachable"}
                  </Badge>
                  <span className="rr-muted">
                    {source.probe.detail} · {source.probe.capture_mode}
                  </span>
                </span>
              ) : (
                "-"
              ),
            },
          ]}
        />
      ) : (
        <p className="rr-muted">아직 연결하지 않았습니다.</p>
      )}
      <form className="rr-form" onSubmit={link}>
        <ErrorBanner error={error} />
        <label className="rr-field">
          <span>app_key</span>
          <select className="rr-select" value={appKey} onChange={(e) => setAppKey(e.target.value)}>
            <option value="">선택</option>
            {candidates.map((a) => (
              <option key={a.app ?? a.kind} value={a.app ?? ""}>
                {a.app ?? a.kind} ({a.status})
              </option>
            ))}
          </select>
        </label>
        <label className="rr-field">
          <span>ref</span>
          {choices.length > 0 ? (
            <select className="rr-select" value={ref} onChange={(e) => setRef(e.target.value)}>
              <option value="">선택</option>
              {choices.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                  {c.detail ? ` — ${c.detail}` : ""}
                </option>
              ))}
            </select>
          ) : (
            <input className="rr-input" value={ref} onChange={(e) => setRef(e.target.value)} />
          )}
        </label>
        <label className="rr-row">
          <input type="checkbox" checked={bridge} onChange={(e) => setBridge(e.target.checked)} />
          <span className="rr-muted">bridge_declared</span>
        </label>
        <button type="submit" className="rr-btn" disabled={busy || appKey === "" || ref === ""}>
          연결
        </button>
      </form>
    </div>
  );
}

function SnapshotForm({
  projectId,
  onQueued,
  onOpenSnapshot,
}: {
  projectId: string;
  /** 202 로 잡이 걸렸을 때 — 화면이 그 잡을 좇아 완료 시 스냅샷을 연다. */
  onQueued: (jobId: string | null) => void;
  onOpenSnapshot: (snapshotId: string) => void;
}) {
  const [label, setLabel] = useState("");
  const [kinds, setKinds] = useState<SourceKind[]>(["mcad"]);
  const [reportIds, setReportIds] = useState("");
  const [detectId, setDetectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [gates, setGates] = useState<Gate[] | null>(null);
  const [degraded, setDegraded] = useState(false);

  function toggle(kind: SourceKind) {
    setKinds((prev) => (prev.includes(kind) ? prev.filter((k) => k !== kind) : [...prev, kind]));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (kinds.length === 0) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    setGates(null);
    setDegraded(false);
    try {
      const accepted = await riskApi.createSnapshot(projectId, {
        label: label.trim() === "" ? undefined : label.trim(),
        kinds,
        report_ids: reportIds.trim() === "" ? undefined : reportIds.split(",").map((s) => s.trim()).filter(Boolean),
        detect_result_file_id: detectId.trim() === "" ? undefined : detectId.trim(),
      });
      setGates(accepted.gates ?? null);
      setDegraded(accepted.degraded === true);
      if (accepted.snapshot_id) {
        // 같은 ir_hash 라 서버가 200 으로 기존 스냅샷을 돌려준 경우다(§8.2.3 409 행).
        setNotice(`같은 ir_hash 의 기존 스냅샷을 씁니다 — ${accepted.snapshot_id}.`);
        onOpenSnapshot(accepted.snapshot_id);
      } else {
        setNotice(`동결 잡을 시작했습니다 — ${accepted.job_id ?? "job"}. 완료되면 아래에 스냅샷이 열립니다.`);
      }
      onQueued(accepted.snapshot_id ? null : accepted.job_id ?? null);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="rr-form" onSubmit={submit}>
      <ErrorBanner error={error} />
      {notice ? <p className="rr-muted">{notice}</p> : null}
      {degraded ? <p className="rr-muted">degraded — 일부 소스를 온전히 읽지 못한 채 동결했습니다.</p> : null}
      {gates ? (
        <>
          <GateBanner gates={gates} />
          <GateTable gates={gates} />
        </>
      ) : null}
      <div className="rr-row">
        {SNAPSHOT_KINDS.map((kind) => (
          <label key={kind} className="rr-row">
            <input type="checkbox" checked={kinds.includes(kind)} onChange={() => toggle(kind)} />
            <span>{KIND_LABEL[kind]}</span>
          </label>
        ))}
      </div>
      <div className="rr-form-grid">
        <label className="rr-field">
          <span>label (선택)</span>
          <input className="rr-input" value={label} onChange={(e) => setLabel(e.target.value)} />
        </label>
        <label className="rr-field">
          <span>report_ids (쉼표 구분)</span>
          <input className="rr-input" value={reportIds} onChange={(e) => setReportIds(e.target.value)} />
        </label>
        <label className="rr-field">
          <span>detect_result_file_id (선택)</span>
          <input className="rr-input" value={detectId} onChange={(e) => setDetectId(e.target.value)} />
        </label>
      </div>
      <button type="submit" className="rr-btn rr-btn-primary" disabled={busy || kinds.length === 0}>
        스냅샷 동결
      </button>
    </form>
  );
}

function DimForm({ projectId }: { projectId: string }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState("");
  const [unit, setUnit] = useState("");
  const [extractor, setExtractor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const row = await riskApi.createDim(projectId, {
        name: name.trim(),
        kind: kind.trim(),
        unit: unit.trim(),
        extractor: extractor.trim(),
      });
      setCreated(`${row.name} (${row.vocab_status})`);
      setName("");
      setExtractor("");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const ready = name.trim() !== "" && kind.trim() !== "" && extractor.trim() !== "" && !busy;

  return (
    <form className="rr-form" onSubmit={submit}>
      <ErrorBanner error={error} />
      {created ? <p className="rr-muted">등록됨 — {created}</p> : null}
      <div className="rr-form-grid">
        <label className="rr-field">
          <span>name</span>
          <input className="rr-input" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="rr-field">
          <span>kind</span>
          <input className="rr-input" value={kind} onChange={(e) => setKind(e.target.value)} />
        </label>
        <label className="rr-field">
          <span>unit</span>
          <input className="rr-input" value={unit} onChange={(e) => setUnit(e.target.value)} />
        </label>
        <label className="rr-field">
          <span>extractor</span>
          <input className="rr-input" value={extractor} onChange={(e) => setExtractor(e.target.value)} />
        </label>
      </div>
      <button type="submit" className="rr-btn" disabled={!ready}>
        dim 정의 추가
      </button>
    </form>
  );
}

function IfaceLedgerEditor({ projectId }: { projectId: string }) {
  const [rows, setRows] = useState<IfaceLedgerRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);

  function update(index: number, patch: Partial<IfaceLedgerRow>) {
    setRows((prev) => prev.map((r, i) => (i === index ? { ...r, ...patch } : r)));
  }

  async function save() {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const confirmed = await riskApi.putIfaceLedger(projectId, rows);
      setRows(confirmed);
      setSaved(true);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<IfaceLedgerRow>[] = [
    {
      key: "pair_key",
      header: "pair_key",
      cell: (r, i) => (
        <input className="rr-input" value={r.pair_key} onChange={(e) => update(i, { pair_key: e.target.value })} />
      ),
    },
    {
      key: "kind_override",
      header: "kind_override",
      cell: (r, i) => (
        <input
          className="rr-input"
          value={r.kind_override ?? ""}
          onChange={(e) => update(i, { kind_override: e.target.value === "" ? null : e.target.value })}
        />
      ),
    },
    {
      key: "status",
      header: "status",
      cell: (r, i) => (
        <input className="rr-input" value={r.status} onChange={(e) => update(i, { status: e.target.value })} />
      ),
    },
    {
      key: "note",
      header: "note",
      cell: (r, i) => (
        <input
          className="rr-input"
          value={r.note ?? ""}
          onChange={(e) => update(i, { note: e.target.value === "" ? null : e.target.value })}
        />
      ),
    },
    {
      key: "remove",
      header: "",
      cell: (_r, i) => (
        <button type="button" className="rr-btn rr-btn-quiet" onClick={() => setRows((p) => p.filter((_, j) => j !== i))}>
          삭제
        </button>
      ),
    },
  ];

  return (
    <>
      <ErrorBanner error={error} />
      {saved ? <p className="rr-muted">확정 원장을 저장했습니다.</p> : null}
      <DataTable
        columns={columns}
        rows={rows}
        rowKey={(_r, i) => String(i)}
        empty="확정할 인터페이스 행이 없습니다."
      />
      <div className="rr-row">
        <button
          type="button"
          className="rr-btn"
          onClick={() => setRows((p) => [...p, { pair_key: "", kind_override: null, status: "confirmed", note: null }])}
        >
          행 추가
        </button>
        <button type="button" className="rr-btn rr-btn-primary" onClick={save} disabled={busy || rows.length === 0}>
          저장
        </button>
        <span className="rr-muted">확정은 앱 원장에만 기록됩니다.</span>
      </div>
      <p className="rr-muted">
        저장하면 원장이 이 표의 내용으로 대체될 수 있습니다. 조회 경로가 아직 없어 표는 빈 상태에서 시작하고, 저장
        응답으로 돌아온 전체 행이 그다음 기준 상태가 됩니다.
      </p>
    </>
  );
}

function CharacterCard({ projectId }: { projectId: string }) {
  const character = useAsync((signal) => riskApi.getCharacter(projectId, { signal }), [projectId]);
  const byFacet = useMemo(() => {
    const map = new Map<string, CharacterStatement[]>();
    for (const entry of character.data?.facets ?? []) map.set(entry.facet, entry.statements);
    return map;
  }, [character.data]);

  return (
    <SectionCard title="성격 프로파일" subtitle="facet 8종 · seed(L0) · panel(L2) · confirmed 3층을 나란히 보입니다.">
      <ErrorBanner error={character.error} onRetry={character.reload} />
      {character.loading && !character.data ? <LoadingBlock /> : null}
      {character.data ? (
        <>
          {character.data.one_liner ? <VerbatimBlock text={character.data.one_liner} label="한 줄 요약" /> : null}
          <div className="rr-stack">
            {FACET_ORDER.map((facet) => {
              const statements = byFacet.get(facet) ?? [];
              const naReason = character.data?.facets.find((f) => f.facet === facet)?.na_reason ?? null;
              return (
                <div key={facet} className="rr-panel">
                  <div className="rr-row rr-panel-head">
                    <strong>
                      {FACET_LABEL[facet]} <span className="rr-muted">{facet}</span>
                    </strong>
                    {naReason ? <Badge tone="muted">{naReason}</Badge> : null}
                  </div>
                  <div className="rr-cols">
                    {STATEMENT_LAYERS.map((layer) => {
                      const items = statements.filter((s) => s.status === layer.status);
                      return (
                        <div key={layer.status}>
                          <div className="rr-muted">{layer.label}</div>
                          {items.length === 0 ? (
                            <p className="rr-muted">없음</p>
                          ) : (
                            <ul className="rr-list">
                              {items.map((s) => (
                                <li key={s.id}>
                                  <Badge tone="neutral">{s.tag}</Badge> {s.statement}
                                  <span className="rr-muted">
                                    {" "}
                                    · {s.by} · 패널 {s.support_panels} · 타깃 {s.support_targets}
                                  </span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      ) : null}
    </SectionCard>
  );
}

function SimilarCard({ projectId }: { projectId: string }) {
  const similar = useAsync((signal) => riskApi.getSimilar(projectId, { signal }), [projectId]);
  return (
    <SectionCard title="유사 과제" subtitle="출처별 top-k 를 섞지 않고 따로 보입니다.">
      <ErrorBanner error={similar.error} onRetry={similar.reload} />
      {similar.loading && !similar.data ? <LoadingBlock /> : null}
      {similar.data && similar.data.by_source.length === 0 ? (
        <EmptyBlock title="유사 과제가 없습니다." hint="비교할 출처가 아직 없거나 top-k 가 비어 있습니다." />
      ) : null}
      {similar.data
        ? similar.data.by_source.map((group) => (
            <div key={group.source} className="rr-stack">
              <h3 className="rr-subhead">{group.source}</h3>
              {group.items.length === 0 ? (
                <EmptyBlock title="이 출처의 항목이 없습니다." />
              ) : (
                <ul className="rr-list">
                  {group.items.map((item) => (
                    <li key={item.project_id}>
                      <Link to={`/projects/${encodeURIComponent(item.project_id)}`}>
                        {item.code} · {item.name}
                      </Link>
                      <span className="rr-muted">
                        {" "}
                        · score {item.score} · {item.why}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))
        : null}
    </SectionCard>
  );
}

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = id ?? "";
  const [params, setParams] = useSearchParams();
  const snapshotId = params.get("snapshot");

  const detail = useAsync((signal) => riskApi.getProject(projectId, { signal }), [projectId], projectId !== "");
  const adapters = useAsync((signal) => riskApi.getAdapters({ signal }), []);

  const jobs: JobHeader[] = detail.data?.jobs ?? [];
  const active = jobs.some((j) => j.state === "queued" || j.state === "running");
  useInterval(detail.reload, active ? POLL_MS : null);

  /** 방금 건 동결 잡. 끝나면 §8.2.4 대로 `?snapshot=` 을 열어 준다. */
  const [pendingJob, setPendingJob] = useState<string | null>(null);
  useEffect(() => {
    if (pendingJob === null || !detail.data) return;
    const job = detail.data.jobs.find((j) => j.id === pendingJob);
    if (job && (job.state === "queued" || job.state === "running")) return;
    setPendingJob(null);
    if (!job || job.state !== "done") return;
    const newest = detail.data.snapshots.reduce<SnapshotHeader | null>(
      (best, s) => (best === null || s.captured_at > best.captured_at ? s : best),
      null,
    );
    if (newest) setParams({ snapshot: newest.id });
  }, [pendingJob, detail.data, setParams]);

  const snapshotColumns: Column<SnapshotHeader>[] = [
    { key: "id", header: "snapshot_id", cell: (s) => <code>{s.id}</code>, nowrap: true },
    { key: "label", header: "label", cell: (s) => s.label ?? "-" },
    { key: "hash", header: "ir_hash", cell: (s) => <code>{s.ir_hash}</code>, nowrap: true },
    { key: "kinds", header: "kinds", cell: (s) => s.kinds.join(" · "), nowrap: true },
    { key: "at", header: "captured_at", cell: (s) => fmtEpoch(s.captured_at), nowrap: true },
    { key: "counts", header: "counts", cell: (s) => fmtCounts(s.counts) },
    {
      key: "degraded",
      header: "degraded",
      cell: (s) => (s.degraded ? <Badge tone="warn">degraded</Badge> : <span className="rr-muted">-</span>),
      nowrap: true,
    },
  ];

  const targetColumns: Column<TargetHeader>[] = [
    {
      key: "key",
      header: "target_key",
      nowrap: true,
      cell: (t) => <Link to={`/targets/${encodeURIComponent(t.target_key)}`}>{t.target_key}</Link>,
    },
    { key: "kind", header: "kind", cell: (t) => t.kind, nowrap: true },
    { key: "level", header: "level", cell: (t) => <LevelBadge value={t.level} />, nowrap: true },
    {
      key: "verdict",
      header: "verdict_final",
      cell: (t) => <StatusBadge value={t.verdict_final ?? "undetermined"} />,
      nowrap: true,
    },
    { key: "unseated", header: "착석", cell: (t) => <UnseatedBadge n={t.unseated_n} />, nowrap: true },
    { key: "sync", header: "external_sync", cell: (t) => <ExternalSyncBadge sync={t.external_sync} />, nowrap: true },
    {
      key: "superseded",
      header: "superseded_by",
      nowrap: true,
      cell: (t) =>
        t.superseded_by ? (
          <Link to={`/targets/${encodeURIComponent(t.superseded_by)}`}>{t.superseded_by}</Link>
        ) : (
          <span className="rr-muted">-</span>
        ),
    },
  ];

  const jobColumns: Column<JobHeader>[] = [
    { key: "id", header: "job_id", cell: (j) => <code>{j.id}</code>, nowrap: true },
    { key: "kind", header: "kind", cell: (j) => j.kind, nowrap: true },
    { key: "state", header: "state", cell: (j) => <JobStateBadge value={j.state} />, nowrap: true },
    {
      key: "progress",
      header: "progress",
      nowrap: true,
      width: "10rem",
      cell: (j) => {
        const pct = Math.max(0, Math.min(100, Math.round(j.progress * 100)));
        return (
          <span className="rr-row">
            <span
              aria-hidden="true"
              style={{ display: "inline-block", width: "6rem", height: "0.4rem", background: "var(--rr-muted-bg)" }}
            >
              <span style={{ display: "block", width: `${pct}%`, height: "100%", background: "currentColor" }} />
            </span>
            <span>{pct}%</span>
          </span>
        );
      },
    },
    { key: "error", header: "error", cell: (j) => j.error ?? "-" },
  ];

  if (projectId === "") {
    return (
      <SectionCard title="과제">
        <EmptyBlock title="과제를 찾을 수 없습니다." />
      </SectionCard>
    );
  }

  return (
    <>
      <SectionCard
        title={detail.data ? `${detail.data.project.code} · ${detail.data.project.name}` : "과제"}
        subtitle={`project_id ${projectId}`}
        actions={detail.data ? <ExternalSyncBadge sync={detail.data.project.external_sync ?? null} /> : null}
      >
        <ErrorBanner error={detail.error} onRetry={detail.reload} />
        {detail.loading && !detail.data ? <LoadingBlock /> : null}
        {detail.data ? (
          <KeyValueTable
            rows={[
              { label: "stage", value: detail.data.project.stage ?? "-" },
              {
                label: "계보",
                value: detail.data.project.predecessor_project_id ? (
                  <Link to={`/projects/${encodeURIComponent(detail.data.project.predecessor_project_id)}`}>
                    {detail.data.project.predecessor_project_id}
                  </Link>
                ) : (
                  "-"
                ),
              },
              {
                label: "adh_scope",
                value: detail.data.project.adh_scope
                  ? `${detail.data.project.adh_scope.team} / ${detail.data.project.adh_scope.group}`
                  : "-",
              },
              { label: "created_at", value: fmtEpoch(detail.data.project.created_at) },
              {
                label: "성격 태그",
                value:
                  detail.data.character_top_tags.length === 0 ? (
                    <span className="rr-muted">없음</span>
                  ) : (
                    <span className="rr-badge-group">
                      {detail.data.character_top_tags.map((t) => (
                        <Badge key={t} tone="neutral">
                          {t}
                        </Badge>
                      ))}
                    </span>
                  ),
              },
            ]}
          />
        ) : null}
      </SectionCard>

      <SectionCard title="소스" subtitle="unlinked → linked → unreachable. 소스 앱에 쓰기를 하지 않습니다.">
        <ErrorBanner error={adapters.error} onRetry={adapters.reload} />
        {detail.data ? (
          <CardGrid min="20rem">
            {SOURCE_KINDS.map((kind) => (
              <SourceCard
                key={kind}
                kind={kind}
                detail={detail.data as ProjectDetail}
                adapters={adapters.data ?? []}
                onChanged={detail.reload}
              />
            ))}
          </CardGrid>
        ) : null}
      </SectionCard>

      <SectionCard title="스냅샷 동결" subtitle="소스 앱의 parse · detect 는 각 앱 화면에서 먼저 실행하세요.">
        <SnapshotForm
          projectId={projectId}
          onQueued={(jobId) => {
            setPendingJob(jobId);
            detail.reload();
          }}
          onOpenSnapshot={(id) => setParams({ snapshot: id })}
        />
      </SectionCard>

      <SectionCard title="잡" subtitle={active ? "진행 중 — 5초마다 갱신합니다." : undefined}>
        <DataTable columns={jobColumns} rows={jobs} rowKey={(j) => j.id} empty="진행 중인 잡이 없습니다." />
      </SectionCard>

      <SectionCard title="스냅샷" subtitle="행을 누르면 아래에 스냅샷 화면이 열립니다.">
        <DataTable
          columns={snapshotColumns}
          rows={detail.data?.snapshots ?? []}
          rowKey={(s) => s.id}
          selectedKey={snapshotId}
          onRowClick={(s) => setParams({ snapshot: s.id })}
          empty="동결된 스냅샷이 없습니다."
        />
      </SectionCard>

      <SectionCard title="타깃">
        <DataTable
          columns={targetColumns}
          rows={detail.data?.targets ?? []}
          rowKey={(t) => t.target_key}
          empty="열린 타깃이 없습니다."
        />
      </SectionCard>

      {snapshotId ? (
        <>
          <div className="rr-row">
            <button type="button" className="rr-btn rr-btn-quiet" onClick={() => setParams({})}>
              스냅샷 화면 닫기
            </button>
          </div>
          <SnapshotPage snapshotId={snapshotId} />
        </>
      ) : null}

      <SectionCard title="dims 정의">
        <DimForm projectId={projectId} />
      </SectionCard>

      <SectionCard title="iface-ledger" subtitle="확정 원장은 앱 DB 에만 저장합니다.">
        <IfaceLedgerEditor projectId={projectId} />
      </SectionCard>

      <CharacterCard projectId={projectId} />
      <SimilarCard projectId={projectId} />
    </>
  );
}
