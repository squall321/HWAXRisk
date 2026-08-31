// 타깃 화면 — 진행판·PanelRunner·패널 목록/모델 혼합·등록부·verdict·RecallPreview(계획 §8.2.4 TargetPage 행). :key 는 snap:<id>/diff:<id> 다.
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { riskApi } from "../api/risk.api";
import type { Async } from "../hooks/useAsync";
import { POLL_MS, useAsync, useInterval } from "../hooks/useAsync";
import { SectionCard, VerbatimBlock } from "../components/SectionCard";
import type { Column } from "../components/DataTable";
import { DataTable, KeyValueTable, TableScroll } from "../components/DataTable";
import { EmptyBlock, ErrorBanner, LoadingBlock, NotReadyBlock } from "../components/StateBlocks";
import {
  Badge,
  CoverageStatusBadge,
  EvidenceGradeBadge,
  ExternalSyncBadge,
  JobStateBadge,
  JudgementBadge,
  LevelBadge,
  PanelStatusBadge,
  RegistryStatusBadge,
  SeverityBadge,
  StatusBadge,
  toneOf,
  UnseatedBadge,
  VerdictBadge,
} from "../components/Badge";
import { PanelTranscript } from "../components/PanelTranscript";
import { fmtEpoch, fmtJson, fmtNum } from "../format";
import type {
  Coverage,
  CoverageStatus,
  EvidenceItem,
  ExternalSync,
  Panel,
  Registry,
  RegistryRow,
  RegistryStatusInput,
  Seat,
  Tier,
  Verdict,
} from "../types";

const COVERAGE_STATUSES: CoverageStatus[] = [
  "pending",
  "assigned",
  "running",
  "done",
  "done_weak",
  "abstain",
  "failed",
  "skipped",
  "deferred",
  "carried",
];
const TIERS: Tier[] = ["A", "B", "C"];
const VERDICTS: Verdict[] = ["go", "conditional", "no-go", "undetermined"];
const REGISTRY_STATUSES: RegistryStatusInput[] = ["verified", "dismissed", "mitigated"];
const ACTIVE_JOB_STATES = new Set(["queued", "running", "cancelling"]);

/** 모델 혼합 표 한 줄 — 패널을 센 값만 담는다. */
type ModelMixRow = { key: string; model: string; captured: string; n: number; done: number };

/** 참조 하나를 눌러서 펼쳐 보는 상자(`GET refs/{ref}`). */
function RefPeek({ value }: { value: string }) {
  const [open, setOpen] = useState(false);
  const resolved = useAsync((signal) => riskApi.getRef(value, { signal }), [value], open);
  return (
    <div className="rr-stack">
      <button type="button" className="rr-btn rr-btn-quiet" onClick={() => setOpen((v) => !v)}>
        <code>{value}</code>
      </button>
      {open ? (
        <>
          <ErrorBanner error={resolved.error} onRetry={resolved.reload} />
          {resolved.loading && !resolved.data ? <LoadingBlock /> : null}
          {resolved.data ? (
            <VerbatimBlock
              text={fmtJson(resolved.data.payload)}
              label={`${resolved.data.ref_type} · ${resolved.data.resolved ? "resolved" : "dangling"}`}
            />
          ) : null}
        </>
      ) : null}
    </div>
  );
}

function CoverageHeatmap({ coverage, targetKey }: { coverage: Coverage; targetKey: string }) {
  const [domain, setDomain] = useState<string | null>(null);
  const seats = useAsync(
    (signal) => riskApi.getSeats(targetKey, domain ?? "", { signal }),
    [targetKey, domain],
    domain !== null,
  );

  const domains = Object.keys(coverage.by_domain);
  /** 열별 합계 — 도메인 행을 더한 값이다(새 판정이 아니다). */
  const totals: Record<string, number> = {};
  for (const d of domains) {
    const counts = coverage.by_domain[d] ?? {};
    for (const s of COVERAGE_STATUSES) totals[s] = (totals[s] ?? 0) + (counts[s] ?? 0);
  }
  const seatColumns: Column<Seat>[] = [
    { key: "agent", header: "agent_key", cell: (s) => <code>{s.agent_key}</code>, nowrap: true },
    { key: "status", header: "status", cell: (s) => <CoverageStatusBadge value={s.status} />, nowrap: true },
    { key: "reason", header: "reason", cell: (s) => s.reason ?? "-" },
    { key: "panel", header: "panel_id", cell: (s) => (s.panel_id ? <code>{s.panel_id}</code> : "-"), nowrap: true },
    {
      key: "opinion",
      header: "opinion_id",
      nowrap: true,
      cell: (s) => (s.opinion_id ? <code>{s.opinion_id}</code> : "-"),
    },
  ];

  return (
    <>
      <TableScroll>
        <table className="rr-table">
          <thead>
            <tr>
              <th scope="col">도메인</th>
              {COVERAGE_STATUSES.map((s) => (
                <th key={s} scope="col" style={{ textAlign: "right" }}>
                  {s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {domains.map((d) => {
              const counts = coverage.by_domain[d] ?? {};
              return (
                <tr
                  key={d}
                  data-clickable="true"
                  onClick={() => setDomain(d)}
                  tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter" && event.key !== " ") return;
                    event.preventDefault();
                    setDomain(d);
                  }}
                  aria-selected={domain === d}
                  className={domain === d ? "rr-row-selected" : undefined}
                >
                  <th scope="row">{d}</th>
                  {COVERAGE_STATUSES.map((s) => {
                    const n = counts[s] ?? 0;
                    return (
                      <td key={s} style={{ textAlign: "right" }} className="rr-nowrap">
                        {n === 0 ? (
                          <span className="rr-muted">0</span>
                        ) : (
                          <Badge tone={toneOf(s)} title={s}>
                            {n}
                          </Badge>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
          {domains.length > 0 ? (
            <tfoot>
              <tr>
                <th scope="row">합계</th>
                {COVERAGE_STATUSES.map((s) => (
                  <td key={s} style={{ textAlign: "right" }} className="rr-nowrap">
                    {totals[s] ?? 0}
                  </td>
                ))}
              </tr>
            </tfoot>
          ) : null}
        </table>
      </TableScroll>
      {domains.length === 0 ? <EmptyBlock title="커버리지 행이 없습니다." /> : null}
      {domain !== null ? (
        <div className="rr-stack">
          <h3 className="rr-subhead">{domain} 좌석</h3>
          <ErrorBanner error={seats.error} onRetry={seats.reload} />
          {seats.loading && !seats.data ? <LoadingBlock /> : null}
          {seats.data ? (
            <DataTable columns={seatColumns} rows={seats.data} rowKey={(s) => s.agent_key} empty="좌석이 없습니다." />
          ) : null}
          <p className="rr-muted">좌석 상태 되돌리기 · skipped 사유 입력 경로는 아직 서버에 없습니다.</p>
        </div>
      ) : null}
    </>
  );
}

function PanelRunner({ targetKey, coverage, onChanged }: { targetKey: string; coverage: Coverage | null; onChanged: () => void }) {
  const [tier, setTier] = useState<Tier>("B");
  const [concurrency, setConcurrency] = useState(1);
  const [modifiers, setModifiers] = useState("");
  const [memo, setMemo] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [credential, setCredential] = useState<string | null>(null);
  const [planned, setPlanned] = useState<string | null>(null);

  const job = coverage?.job ?? null;
  const needsConsent = tier === "C";

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const created = await riskApi.createTargetJob(targetKey, {
        tier,
        concurrency,
        modifiers: modifiers.trim() === "" ? undefined : modifiers.split(",").map((s) => s.trim()).filter(Boolean),
        user_memo: memo.trim() === "" ? undefined : memo.trim(),
        consent: needsConsent ? consent : undefined,
      });
      setCredential(created.credential);
      setPlanned(`패널 ${created.panels_planned}개 · LLM 호출 추정 ${created.llm_calls_estimate}`);
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function control(action: "pause" | "resume" | "cancel") {
    if (!job) return;
    setBusy(true);
    setError(null);
    try {
      if (action === "pause") await riskApi.pauseJob(job.id);
      else if (action === "resume") await riskApi.resumeJob(job.id);
      else await riskApi.cancelJob(job.id);
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <ErrorBanner error={error} />
      {job ? (
        <KeyValueTable
          rows={[
            { label: "job_id", value: <code>{job.id}</code> },
            { label: "state", value: <JobStateBadge value={job.state} /> },
            { label: "reason", value: job.reason ?? "-" },
            { label: "progress", value: `${Math.round(job.progress * 100)}%` },
            { label: "error", value: job.error ?? "-" },
            { label: "일일 상한 잔량", value: String(job.daily_remaining) },
          ]}
        />
      ) : (
        <p className="rr-muted">진행 중인 배치 잡이 없습니다.</p>
      )}
      <div className="rr-form-grid">
        <label className="rr-field">
          <span>Tier</span>
          <select className="rr-select" value={tier} onChange={(e) => setTier(e.target.value as Tier)}>
            {TIERS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="rr-field">
          <span>concurrency (≤2)</span>
          <input
            className="rr-input"
            type="number"
            min={1}
            max={2}
            value={concurrency}
            onChange={(e) => setConcurrency(Math.min(2, Math.max(1, Number(e.target.value) || 1)))}
          />
        </label>
        <label className="rr-field">
          <span>modifiers (쉼표 구분)</span>
          <input className="rr-input" value={modifiers} onChange={(e) => setModifiers(e.target.value)} />
        </label>
        <label className="rr-field">
          <span>user_memo</span>
          <input className="rr-input" value={memo} onChange={(e) => setMemo(e.target.value)} />
        </label>
      </div>
      {needsConsent ? (
        <label className="rr-row">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>Tier C 는 명시 승인이 필요합니다.</span>
        </label>
      ) : null}
      <div className="rr-row">
        <button
          type="button"
          className="rr-btn rr-btn-primary"
          onClick={start}
          disabled={busy || (needsConsent && !consent)}
        >
          시작
        </button>
        <button type="button" className="rr-btn" onClick={() => control("pause")} disabled={busy || !job}>
          일시정지
        </button>
        <button type="button" className="rr-btn" onClick={() => control("resume")} disabled={busy || !job}>
          재개
        </button>
        <button type="button" className="rr-btn" onClick={() => control("cancel")} disabled={busy || !job}>
          취소
        </button>
      </div>
      {planned ? <p className="rr-muted">{planned}</p> : null}
      {credential ? (
        <div className="rr-row">
          <span className="rr-muted">러너 자격</span>
          <StatusBadge value={credential} />
          {credential === "service" ? (
            <span className="rr-muted">포털 PAT 미등록 — DynaForge 사용자 데이터는 서비스 시야로 읽습니다.</span>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

function PanelsCard({ targetKey }: { targetKey: string }) {
  const panels = useAsync((signal) => riskApi.getPanels(targetKey, { signal }), [targetKey]);
  const [openPanel, setOpenPanel] = useState<string | null>(null);

  const rows = panels.data ?? [];
  /** 모델 혼합 — 어떤 LLM 이 점검했는지 세기만 한다(§6.11 D6). 판정을 새로 만들지 않고 패널을 센다. */
  const models = useMemo(() => {
    const map = new Map<string, ModelMixRow>();
    for (const p of rows) {
      const model = p.model?.model ?? "unknown";
      const captured = p.model?.captured ?? "unknown";
      const key = `${model}|${captured}`;
      const cur = map.get(key) ?? { key, model, captured, n: 0, done: 0 };
      cur.n += 1;
      if (p.status === "done") cur.done += 1;
      map.set(key, cur);
    }
    return Array.from(map.values());
  }, [rows]);

  const columns: Column<Panel>[] = [
    { key: "no", header: "패널", cell: (p) => `P${p.panel_no}`, nowrap: true },
    { key: "tier", header: "tier", cell: (p) => p.tier, nowrap: true },
    { key: "engine", header: "engine", cell: (p) => <StatusBadge value={p.engine} />, nowrap: true },
    { key: "path", header: "call_path", cell: (p) => p.call_path, nowrap: true },
    { key: "mode", header: "tool_mode", cell: (p) => p.tool_mode, nowrap: true },
    { key: "status", header: "status", cell: (p) => <PanelStatusBadge value={p.status} />, nowrap: true },
    { key: "model", header: "model", cell: (p) => p.model?.model ?? "unknown", nowrap: true },
    {
      key: "tools",
      header: "도구 사용",
      nowrap: true,
      // SSE 귀속이 없으면 서버가 null 로 둔다(§6.11) — 화면이 0 으로 바꿔 읽지 않는다.
      cell: (p) =>
        p.quality.tool_calls_n === null || p.quality.tool_calls_n === undefined ? (
          <span className="rr-muted" title="도구 호출 기록 없음(evidence_only 또는 SSE 미귀속).">
            기록 없음
          </span>
        ) : (
          <span title={p.quality.used_tool === null ? "used_tool 미기록" : `used_tool ${String(p.quality.used_tool)}`}>
            {p.quality.tool_calls_ok ?? "-"} / {p.quality.tool_calls_n}
          </span>
        ),
    },
    {
      key: "quality",
      header: "quality.flag",
      cell: (p) => (
        <span className="rr-badge-group">
          {p.quality.flag.map((f) => (
            <Badge key={f} tone="warn">
              {f}
            </Badge>
          ))}
        </span>
      ),
    },
    {
      key: "attr",
      header: "귀속률",
      align: "right",
      nowrap: true,
      cell: (p) => fmtNum(p.quality.attribution_rate, 2),
    },
    { key: "seats", header: "좌석", cell: (p) => String(p.seats.length), align: "right", nowrap: true },
    { key: "started", header: "시작", cell: (p) => fmtEpoch(p.started_at), nowrap: true },
    {
      key: "links",
      header: "기록",
      nowrap: true,
      cell: (p) => (
        <span className="rr-row">
          <button
            type="button"
            className="rr-btn rr-btn-quiet"
            onClick={() => setOpenPanel((cur) => (cur === p.panel_id ? null : p.panel_id))}
          >
            기록 열기
          </button>
          {p.report_id ? <code>{p.report_id}</code> : null}
          {p.conv_id ? <code>{p.conv_id}</code> : null}
        </span>
      ),
    },
  ];

  return (
    <SectionCard title="패널" subtitle="engine · call_path · tool_mode · 품질 플래그는 서버가 기록한 값입니다.">
      <ErrorBanner error={panels.error} onRetry={panels.reload} />
      {panels.loading && !panels.data ? <LoadingBlock /> : null}
      {panels.data ? (
        <>
          <DataTable columns={columns} rows={rows} rowKey={(p) => p.panel_id} selectedKey={openPanel} empty="패널이 없습니다." />
          <h3 className="rr-subhead">모델 혼합</h3>
          <p className="rr-muted">
            어떤 LLM 이 점검했는지 — `rr_panels.model_json.model` 기준으로 패널을 셉니다. captured 가
            caller_reported 이면 호출자 신고값이라 검증되지 않았습니다(§6.11 D6).
          </p>
          <DataTable
            columns={[
              { key: "model", header: "model", cell: (m: ModelMixRow) => m.model, nowrap: true },
              { key: "captured", header: "captured", cell: (m: ModelMixRow) => m.captured, nowrap: true },
              { key: "n", header: "패널 수", cell: (m: ModelMixRow) => String(m.n), align: "right", nowrap: true },
              { key: "done", header: "done", cell: (m: ModelMixRow) => String(m.done), align: "right", nowrap: true },
            ]}
            rows={models}
            rowKey={(m) => m.key}
            empty="모델 기록이 없습니다."
          />
          <p className="rr-muted">
            strong 비율은 좌석 단위 서버 계산값이라 위 진행판 열에 있는 값만 봅니다 — 이 표는 세지 않습니다.
          </p>
          {openPanel ? <PanelTranscript panelId={openPanel} /> : null}
        </>
      ) : null}
    </SectionCard>
  );
}

function RegistryCard({ targetKey, registry }: { targetKey: string; registry: Async<Registry> }) {
  const [severity, setSeverity] = useState("");
  const [domain, setDomain] = useState("");
  const [direction, setDirection] = useState("");
  const [status, setStatus] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [nextStatus, setNextStatus] = useState<RegistryStatusInput>("verified");
  const [evidenceRef, setEvidenceRef] = useState("");
  const [note, setNote] = useState("");
  const [verdict, setVerdict] = useState<Verdict>("undetermined");
  const [verdictNote, setVerdictNote] = useState("");

  const rows = registry.data?.rows ?? [];
  const filtered = rows.filter(
    (r) =>
      (severity === "" || r.severity === severity) &&
      (domain === "" || r.domain === domain) &&
      (direction === "" || r.direction === direction) &&
      (status === "" || r.status === status),
  );
  const selectedRow = rows.find((r) => r.cluster_key === selected) ?? null;
  const domains = Array.from(new Set(rows.map((r) => r.domain))).sort();

  async function saveStatus() {
    if (!selectedRow) return;
    setBusy(true);
    setError(null);
    try {
      await riskApi.putRegistryStatus(selectedRow.cluster_key, {
        status: nextStatus,
        evidence_ref: evidenceRef.trim() === "" ? undefined : evidenceRef.trim(),
        note: note.trim() === "" ? undefined : note.trim(),
      });
      registry.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function saveVerdict() {
    setBusy(true);
    setError(null);
    try {
      await riskApi.putVerdict(targetKey, { verdict, note: verdictNote });
      registry.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<RegistryRow>[] = [
    { key: "cluster", header: "cluster_key", cell: (r) => <code>{r.cluster_key}</code>, nowrap: true },
    { key: "direction", header: "direction", cell: (r) => r.direction, nowrap: true },
    { key: "domain", header: "domain", cell: (r) => r.domain, nowrap: true },
    { key: "mechanism", header: "mechanism", cell: (r) => `${r.mechanism} · ${r.mechanism_detail}` },
    { key: "change", header: "change_kind", cell: (r) => r.change_kind, nowrap: true },
    { key: "subject", header: "subject", cell: (r) => r.subject },
    { key: "severity", header: "severity", cell: (r) => <SeverityBadge value={r.severity} />, nowrap: true },
    { key: "judgement", header: "judgement", cell: (r) => <JudgementBadge value={r.judgement} />, nowrap: true },
    { key: "grade", header: "evidence_grade", cell: (r) => <EvidenceGradeBadge value={r.evidence_grade} />, nowrap: true },
    { key: "precedent", header: "precedent", cell: (r) => r.precedent, nowrap: true },
    {
      key: "support",
      header: "support / contested",
      align: "right",
      nowrap: true,
      cell: (r) => `${r.support} / ${r.contested}`,
    },
    { key: "status", header: "status", cell: (r) => <RegistryStatusBadge value={r.status} />, nowrap: true },
    { key: "priority", header: "priority", cell: (r) => fmtNum(r.priority), align: "right", nowrap: true },
  ];

  return (
    <>
      <SectionCard title="등록부" subtitle="행을 누르면 주장과 근거 참조가 펼쳐집니다.">
        <ErrorBanner error={registry.error} onRetry={registry.reload} />
        <ErrorBanner error={error} />
        {registry.loading && !registry.data ? <LoadingBlock /> : null}
        <div className="rr-row">
          <select className="rr-select" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="">severity 전체</option>
            {["경미", "중대", "치명"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select className="rr-select" value={domain} onChange={(e) => setDomain(e.target.value)}>
            <option value="">domain 전체</option>
            {domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <select className="rr-select" value={direction} onChange={(e) => setDirection(e.target.value)}>
            <option value="">direction 전체</option>
            {["risk", "improvement", "neutral"].map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <select className="rr-select" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">status 전체</option>
            {["open", "verified", "dismissed", "mitigated", "superseded"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <span className="rr-muted">
            {filtered.length} / {rows.length} 행
          </span>
        </div>
        <DataTable
          columns={columns}
          rows={filtered}
          rowKey={(r) => r.cluster_key}
          selectedKey={selected}
          onRowClick={(r) => setSelected((cur) => (cur === r.cluster_key ? null : r.cluster_key))}
          empty="등록부 행이 없습니다."
        />
        {selectedRow ? (
          <div className="rr-panel">
            <div className="rr-row rr-panel-head">
              <strong>{selectedRow.cluster_key}</strong>
              <RegistryStatusBadge value={selectedRow.status} />
            </div>
            <VerbatimBlock text={selectedRow.claim} label="claim" />
            <h3 className="rr-subhead">근거</h3>
            {selectedRow.cites.length === 0 ? (
              <p className="rr-muted">근거 참조가 없습니다.</p>
            ) : (
              <ul className="rr-list">
                {selectedRow.cites.map((c, i) => (
                  <li key={`${c.ref}#${i}`}>
                    <RefPeek value={c.ref} />
                    <span className="rr-muted">{c.quote}</span>
                    {c.dangling ? <Badge tone="bad">dangling</Badge> : null}
                  </li>
                ))}
              </ul>
            )}
            <h3 className="rr-subhead">상태 변경</h3>
            <div className="rr-form-grid">
              <label className="rr-field">
                <span>status</span>
                <select
                  className="rr-select"
                  value={nextStatus}
                  onChange={(e) => setNextStatus(e.target.value as RegistryStatusInput)}
                >
                  {REGISTRY_STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </label>
              <label className="rr-field">
                <span>evidence_ref (선택)</span>
                <input className="rr-input" value={evidenceRef} onChange={(e) => setEvidenceRef(e.target.value)} />
              </label>
              <label className="rr-field">
                <span>note (선택)</span>
                <input className="rr-input" value={note} onChange={(e) => setNote(e.target.value)} />
              </label>
            </div>
            <button type="button" className="rr-btn" onClick={saveStatus} disabled={busy}>
              상태 저장
            </button>
          </div>
        ) : null}
      </SectionCard>

      <SectionCard title="verdict" subtitle="후보는 집계일 뿐이고 확정은 사람이 합니다.">
        {registry.data?.verdict_candidate ? (
          <KeyValueTable
            rows={[
              { label: "후보", value: <VerdictBadge value={registry.data.verdict_candidate.verdict} /> },
              { label: "사유", value: registry.data.verdict_candidate.reason },
              {
                label: "조건",
                value:
                  registry.data.verdict_candidate.conditions.length === 0 ? (
                    <span className="rr-muted">없음</span>
                  ) : (
                    <ul className="rr-list">
                      {registry.data.verdict_candidate.conditions.map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  ),
              },
              { label: "확정값", value: <VerdictBadge value={registry.data.verdict_final ?? "undetermined"} /> },
            ]}
          />
        ) : (
          <p className="rr-muted">후보가 아직 없습니다.</p>
        )}
        <div className="rr-form-grid">
          <label className="rr-field">
            <span>verdict</span>
            <select className="rr-select" value={verdict} onChange={(e) => setVerdict(e.target.value as Verdict)}>
              {VERDICTS.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label className="rr-field">
            <span>note</span>
            <input className="rr-input" value={verdictNote} onChange={(e) => setVerdictNote(e.target.value)} />
          </label>
        </div>
        <button type="button" className="rr-btn rr-btn-primary" onClick={saveVerdict} disabled={busy}>
          확정
        </button>
      </SectionCard>
    </>
  );
}

/** 통합 보고서 — 레벨 상승마다 코드가 RA `deliberation` 템플릿으로 조립한다(§6.9). 조회 경로는 아직 없다. */
function ConsolidatedReportCard({ level, sync }: { level: string | null; sync: ExternalSync | null }) {
  return (
    <SectionCard
      title="통합 보고서"
      subtitle="레벨이 오를 때마다 v1(C1)·v2(C2)·v3(C3) 이 ReportArchive 에 쌓입니다."
      actions={<ExternalSyncBadge sync={sync} />}
    >
      <KeyValueTable
        rows={[
          { label: "현재 레벨", value: level ? <LevelBadge value={level} /> : "-" },
          {
            label: "RA 반영",
            value: sync ? <StatusBadge value={sync.ra} /> : <span className="rr-muted">재동기를 누르면 확인합니다.</span>,
          },
          {
            label: "AIDataHub 반영",
            value: sync ? <StatusBadge value={sync.adh} /> : <span className="rr-muted">재동기를 누르면 확인합니다.</span>,
          },
        ]}
      />
      <NotReadyBlock what="통합 보고서 링크(v1/v2/v3)" />
      <p className="rr-muted">
        패널별 RA 보고서 id 는 위 패널 표의 '기록' 칸에 있습니다. RA 반영이 unavailable 이어도 완결 레벨은 오릅니다.
      </p>
    </SectionCard>
  );
}

function RecallPreview({ targetKey }: { targetKey: string }) {
  const [tier, setTier] = useState<string>("");
  const brief = useAsync(
    (signal) => riskApi.getBrief(targetKey, tier === "" ? undefined : tier, { signal }),
    [targetKey, tier],
  );
  const [excluded, setExcluded] = useState<Set<string>>(new Set());

  function toggle(id: string) {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const slots = Object.entries(brief.data?.evidence ?? {}).sort(([a], [b]) => a.localeCompare(b));

  return (
    <SectionCard
      title="브리프(RecallPreview)"
      subtitle="항목은 제외만 할 수 있고 추가할 수 없습니다. 이 화면의 제외는 미리보기용이며 아직 서버 브리프에 반영되지 않습니다."
      actions={
        <select className="rr-select" value={tier} onChange={(e) => setTier(e.target.value)}>
          <option value="">tier 전체</option>
          {TIERS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      }
    >
      <ErrorBanner error={brief.error} onRetry={brief.reload} />
      {brief.loading && !brief.data ? <LoadingBlock /> : null}
      {brief.data ? (
        <>
          <p className="rr-muted">
            패널 {brief.data.panels.length}개 · {brief.data.budget.bytes} bytes · 잘린 항목 {brief.data.budget.dropped}
          </p>
          {slots.length === 0 ? <EmptyBlock title="근거 슬롯이 비어 있습니다." /> : null}
          {slots.map(([slot, items]) => (
            <div key={slot} className="rr-stack">
              <h3 className="rr-subhead">{slot}</h3>
              <DataTable
                columns={[
                  {
                    key: "keep",
                    header: "포함",
                    nowrap: true,
                    cell: (_item: EvidenceItem, i: number) => (
                      <input
                        type="checkbox"
                        checked={!excluded.has(`${slot}#${i}`)}
                        onChange={() => toggle(`${slot}#${i}`)}
                      />
                    ),
                  },
                  { key: "source", header: "source", cell: (item: EvidenceItem) => item.source, nowrap: true },
                  { key: "tool", header: "tool", cell: (item: EvidenceItem) => item.tool, nowrap: true },
                  { key: "args", header: "args", cell: (item: EvidenceItem) => item.args },
                  { key: "result", header: "result", cell: (item: EvidenceItem) => item.result },
                ]}
                rows={items}
                rowKey={(_item, i) => `${slot}#${i}`}
                empty="항목이 없습니다."
              />
            </div>
          ))}
        </>
      ) : null}
    </SectionCard>
  );
}

export default function TargetPage() {
  const { key } = useParams<{ key: string }>();
  const targetKey = key ?? "";
  const coverage = useAsync(
    (signal) => riskApi.getCoverage(targetKey, { signal }),
    [targetKey],
    targetKey !== "",
  );
  // 헤더의 verdict_final 과 등록부 카드가 같은 응답을 쓴다.
  const registry = useAsync(
    (signal) => riskApi.getRegistry(targetKey, { signal }),
    [targetKey],
    targetKey !== "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sync, setSync] = useState<ExternalSync | null>(null);
  const [rosterNote, setRosterNote] = useState<string | null>(null);

  const job = coverage.data?.job ?? null;
  const polling = job !== null && ACTIVE_JOB_STATES.has(job.state);
  useInterval(coverage.reload, polling ? POLL_MS : null);

  const [kind, refId] = useMemo(() => {
    const idx = targetKey.indexOf(":");
    return idx === -1 ? [targetKey, ""] : [targetKey.slice(0, idx), targetKey.slice(idx + 1)];
  }, [targetKey]);

  async function resync() {
    setBusy(true);
    setError(null);
    try {
      setSync(await riskApi.resyncTarget(targetKey));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function refreshRoster() {
    setBusy(true);
    setError(null);
    try {
      const result = await riskApi.refreshRoster(targetKey);
      setRosterNote(`대기 좌석 ${result.added_pending}개를 추가했습니다.`);
      coverage.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (targetKey === "") {
    return (
      <SectionCard title="타깃">
        <EmptyBlock title="타깃을 찾을 수 없습니다." />
      </SectionCard>
    );
  }

  return (
    <>
      <SectionCard
        title="타깃"
        subtitle={`target_key ${targetKey}`}
        actions={
          <>
            {coverage.data ? <UnseatedBadge n={coverage.data.unseated_n} /> : null}
            <ExternalSyncBadge sync={sync} />
            <button type="button" className="rr-btn" onClick={resync} disabled={busy}>
              재동기
            </button>
            <button type="button" className="rr-btn" onClick={refreshRoster} disabled={busy}>
              로스터 갱신
            </button>
          </>
        }
      >
        <ErrorBanner error={error} />
        <ErrorBanner error={coverage.error} onRetry={coverage.reload} />
        {rosterNote ? <p className="rr-muted">{rosterNote}</p> : null}
        {coverage.loading && !coverage.data ? <LoadingBlock /> : null}
        <KeyValueTable
          rows={[
            { label: "kind", value: kind },
            {
              label: "ref_id",
              value:
                kind === "snap" && refId ? (
                  <code>{refId}</code>
                ) : refId ? (
                  <Link to={`/compare?diff=${encodeURIComponent(refId)}`}>{refId}</Link>
                ) : (
                  "-"
                ),
            },
            { label: "level", value: coverage.data ? <LevelBadge value={coverage.data.level} /> : "-" },
            { label: "close_level", value: coverage.data ? <LevelBadge value={coverage.data.close_level} /> : "-" },
            { label: "roster_size", value: coverage.data ? String(coverage.data.roster_size) : "-" },
            {
              label: "verdict_final",
              value: registry.data ? (
                <VerdictBadge value={registry.data.verdict_final ?? "undetermined"} />
              ) : (
                <span className="rr-muted">등록부를 읽는 중입니다.</span>
              ),
            },
            {
              label: "external_sync",
              value: sync ? (
                <ExternalSyncBadge sync={sync} />
              ) : (
                <span className="rr-muted">재동기를 누르면 확인합니다.</span>
              ),
            },
          ]}
        />
        <NotReadyBlock what="ir_hash · 과제 링크 · superseded_by" />
      </SectionCard>

      <SectionCard title="진행판" subtitle="행 = 도메인, 열 = 커버리지 상태. 행을 누르면 좌석 목록이 열립니다.">
        {coverage.loading && !coverage.data ? <LoadingBlock /> : null}
        {coverage.data ? (
          <CoverageHeatmap coverage={coverage.data} targetKey={targetKey} />
        ) : coverage.loading ? null : (
          <EmptyBlock title="커버리지가 아직 없습니다." hint="타깃이 편성되면 도메인별 좌석 상태가 여기 쌓입니다." />
        )}
      </SectionCard>

      <SectionCard title="패널 실행" subtitle={polling ? "진행 중 — 5초마다 갱신합니다." : undefined}>
        <PanelRunner targetKey={targetKey} coverage={coverage.data} onChanged={coverage.reload} />
      </SectionCard>

      <PanelsCard targetKey={targetKey} />
      <RegistryCard targetKey={targetKey} registry={registry} />
      <ConsolidatedReportCard level={coverage.data?.level ?? null} sync={sync} />
      <RecallPreview targetKey={targetKey} />
    </>
  );
}
