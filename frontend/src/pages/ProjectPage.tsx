// 과제 화면 — 헤더·소스 카드 3장·스냅샷 동결·스냅샷 목록·dims·iface-ledger·성격 프로파일·유사 과제(계획 §8.2.4 ProjectPage 행). ?snapshot= 이면 같은 화면에 SnapshotPage 를 그린다.
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { riskApi } from "../api/risk.api";
import { POLL_MS, useAsync, useInterval } from "../hooks/useAsync";
import { CardGrid, SectionCard } from "../components/SectionCard";
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
import { fmtCounts, fmtEpoch, fmtNum } from "../format";
import { FACET_ORDER } from "../types";
import type {
  VocabBump,
  AdapterEntry,
  Requirement,
  RequirementKind,
  RequirementStatus,
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

  const chosen = candidates.find((a) => (a.app_key ?? "") === appKey);
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
              <option key={a.app_key ?? a.kind} value={a.app_key ?? ""}>
                {a.app_key ?? a.kind} ({a.status})
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

// 요구 탭(plan §2.8b·§8.2.4) — rr_requirements 표·등록·waive. 여유 계산은 SnapshotPage 의 sig:req.margin 이 보여준다.
function RequirementsCard({ projectId, predecessorId }: { projectId: string; predecessorId?: string | null }) {
  const rows = useAsync(() => riskApi.listRequirements(projectId), [projectId]);
  const [kind, setKind] = useState<RequirementKind>("dim_limit");
  const [name, setName] = useState("");
  const [op, setOp] = useState("lte");
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("mm");
  const [sourceRef, setSourceRef] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let parsed: unknown = value.trim();
      try {
        parsed = JSON.parse(value);
      } catch {
        // 숫자·JSON 이 아니면 문자열 그대로 보낸다 — 어휘 검사는 서버가 한다.
      }
      await riskApi.upsertRequirements(projectId, [
        {
          kind,
          name: name.trim(),
          op: kind === "dim_limit" ? op : null,
          value_json: parsed,
          unit: kind === "dim_limit" ? unit.trim() || null : null,
          source_ref: sourceRef.trim() || null,
        },
      ]);
      setName("");
      setValue("");
      rows.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function decide(id: string, status: RequirementStatus) {
    setError(null);
    try {
      const reason = status === "waived" ? window.prompt("waive 사유(필수)") : null;
      if (status === "waived" && !reason) return;   // 사유 없는 waive 는 서버가 422 다
      await riskApi.decideRequirement(id, { status, waive_reason: reason });
      rows.reload();
    } catch (err) {
      setError(err);
    }
  }

  async function inherit() {
    if (!predecessorId) return;
    setError(null);
    try {
      await riskApi.inheritRequirements(projectId, predecessorId);
      rows.reload();
    } catch (err) {
      setError(err);
    }
  }

  const columns: Array<Column<Requirement>> = [
    { key: "kind", header: "kind", cell: (r) => r.kind },
    { key: "name", header: "name", cell: (r) => r.name },
    { key: "op", header: "op", cell: (r) => r.op ?? "—" },
    { key: "value", header: "value", cell: (r) => JSON.stringify(r.value_json ?? null) },
    { key: "unit", header: "unit", cell: (r) => r.unit ?? "—" },
    { key: "status", header: "status", cell: (r) => <StatusBadge value={r.status} /> },
    { key: "waive_reason", header: "사유", cell: (r) => r.waive_reason ?? "—" },
    {
      key: "actions",
      header: "결정",
      cell: (r) => (
        <span className="rr-row">
          <button type="button" className="rr-btn rr-btn-quiet" onClick={() => decide(r.id, "confirmed")}>
            확정
          </button>
          <button type="button" className="rr-btn rr-btn-quiet" onClick={() => decide(r.id, "waived")}>
            waive
          </button>
        </span>
      ),
    },
  ];

  return (
    <SectionCard
      title="요구"
      subtitle="요구는 스냅샷에 복사되지 않습니다 — 고쳐도 ir_hash 는 그대로이고 rr_state 만 다시 계산됩니다."
    >
      <ErrorBanner error={error ?? rows.error} />
      {rows.loading ? <LoadingBlock /> : null}
      <DataTable
        columns={columns}
        rows={rows.data?.requirements ?? []}
        rowKey={(r) => r.id}
        empty="등록된 요구가 없습니다 — 판정은 좌석 기준입니다(missing.req_absent)."
      />
      {predecessorId ? (
        <button type="button" className="rr-btn rr-btn-quiet" onClick={inherit}>
          계보 과제에서 요구 승계
        </button>
      ) : null}
      <form className="rr-form" onSubmit={submit}>
        <div className="rr-form-grid">
          <label className="rr-field">
            <span>kind</span>
            <select className="rr-input" value={kind} onChange={(e) => setKind(e.target.value as RequirementKind)}>
              <option value="dim_limit">dim_limit</option>
              <option value="scenario">scenario</option>
              <option value="standard">standard</option>
            </select>
          </label>
          <label className="rr-field">
            <span>name</span>
            <input className="rr-input" value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="rr-field">
            <span>op</span>
            <select className="rr-input" value={op} onChange={(e) => setOp(e.target.value)}
                    disabled={kind !== "dim_limit"}>
              <option value="lte">lte</option>
              <option value="gte">gte</option>
              <option value="between">between</option>
            </select>
          </label>
          <label className="rr-field">
            <span>value(JSON)</span>
            <input className="rr-input" value={value} onChange={(e) => setValue(e.target.value)} />
          </label>
          <label className="rr-field">
            <span>unit</span>
            <input className="rr-input" value={unit} onChange={(e) => setUnit(e.target.value)}
                   disabled={kind !== "dim_limit"} />
          </label>
          <label className="rr-field">
            <span>source_ref</span>
            <input className="rr-input" value={sourceRef} onChange={(e) => setSourceRef(e.target.value)} />
          </label>
        </div>
        <button type="submit" className="rr-btn" disabled={busy || name.trim() === ""}>
          요구 저장
        </button>
      </form>
    </SectionCard>
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

function VocabCard() {
  const vocab = useAsync((signal) => riskApi.getVocab({ signal }), []);
  const [head, setHead] = useState("");
  const [aliases, setAliases] = useState("");
  const [tokens, setTokens] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [bump, setBump] = useState<VocabBump | null>(null);

  async function run(work: () => Promise<VocabBump>) {
    setBusy(true);
    setError(null);
    try {
      setBump(await work());
      vocab.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const aliasList = aliases.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);
  const tokenList = tokens.split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

  return (
    <SectionCard
      title="사전"
      subtitle="동의어 추가는 마이너, 삭제는 메이저 승급입니다. 메이저면 기존 ckey 를 다시 계산해야 합니다(§2.7.1)."
    >
      <ErrorBanner error={error} />
      <ErrorBanner error={vocab.error} onRetry={vocab.reload} />
      {bump ? (
        <div
          className={bump.recompute_required ? "rr-banner rr-banner-error" : "rr-banner rr-banner-info"}
          role="alert"
        >
          <span className="rr-banner-title">
            {bump.vocab_version} · {bump.bump} 승급
          </span>
          <span className="rr-banner-detail">
            {bump.recompute_required
              ? "메이저 승급입니다 — 기존 파트 키가 낡았습니다. backend/scripts/recompute_part_keys.py 를 돌리기 전까지 새 스냅샷은 409 recompute_pending 입니다."
              : "마이너 승급입니다 — 기존 ckey 와 ir_hash 는 그대로입니다."}
          </span>
        </div>
      ) : null}

      <div className="rr-stack">
        <h3 className="rr-subhead">동의어</h3>
        <div className="rr-row">
          <label className="rr-field">
            <span>head — 대표 이름</span>
            <input className="rr-input" value={head} onChange={(e) => setHead(e.target.value)} />
          </label>
          <label className="rr-field">
            <span>from — 줄 또는 쉼표로 구분</span>
            <input className="rr-input" value={aliases} onChange={(e) => setAliases(e.target.value)} />
          </label>
          <button
            type="button"
            className="rr-btn"
            disabled={busy || !head.trim() || aliasList.length === 0}
            onClick={() => run(() => riskApi.putVocabSynonym({ head: head.trim(), from: aliasList, op: "add" }))}
          >
            추가(마이너)
          </button>
          <button
            type="button"
            className="rr-btn rr-btn-quiet"
            disabled={busy || !head.trim() || aliasList.length === 0}
            onClick={() => run(() => riskApi.putVocabSynonym({ head: head.trim(), from: aliasList, op: "remove" }))}
          >
            삭제(메이저)
          </button>
        </div>
      </div>

      <div className="rr-stack">
        <h3 className="rr-subhead">stop tokens</h3>
        <div className="rr-row">
          <label className="rr-field">
            <span>tokens — 줄 또는 쉼표로 구분</span>
            <input className="rr-input" value={tokens} onChange={(e) => setTokens(e.target.value)} />
          </label>
          <button
            type="button"
            className="rr-btn"
            disabled={busy || tokenList.length === 0}
            onClick={() => run(() => riskApi.putVocabStopTokens({ tokens: tokenList, op: "add" }))}
          >
            추가(마이너)
          </button>
          <button
            type="button"
            className="rr-btn rr-btn-quiet"
            disabled={busy || tokenList.length === 0}
            onClick={() => run(() => riskApi.putVocabStopTokens({ tokens: tokenList, op: "remove" }))}
          >
            삭제(메이저)
          </button>
        </div>
      </div>

      {vocab.data ? (
        <p className="rr-muted">
          어휘 자산 {vocab.data.assets.length}종 · 자산 판 {vocab.data.asset_version}
        </p>
      ) : null}
    </SectionCard>
  );
}


function CharacterCard({ projectId }: { projectId: string }) {
  const character = useAsync((signal) => riskApi.getCharacter(projectId, { signal }), [projectId]);
  // 서버는 층(seed·panel·confirmed·superseded)으로 주고 화면은 facet 격자로 보인다 — 여기서만 뒤집는다.
  const byFacet = useMemo(() => {
    const map = new Map<string, CharacterStatement[]>();
    for (const items of Object.values(character.data?.layers ?? {})) {
      for (const statement of items) {
        const list = map.get(statement.facet) ?? [];
        list.push(statement);
        map.set(statement.facet, list);
      }
    }
    return map;
  }, [character.data]);

  return (
    <SectionCard title="성격 프로파일" subtitle="facet 8종 · seed(L0) · panel(L2) · confirmed 3층을 나란히 보입니다.">
      <ErrorBanner error={character.error} onRetry={character.reload} />
      {character.loading && !character.data ? <LoadingBlock /> : null}
      {character.data ? (
        <>
          {character.data.character_status ? (
            <div className="rr-row">
              <span className="rr-muted">과제 성격 층</span>
              <Badge tone="info">{character.data.character_status}</Badge>
            </div>
          ) : null}
          <div className="rr-stack">
            {FACET_ORDER.map((facet) => {
              const statements = byFacet.get(facet) ?? [];
              return (
                <div key={facet} className="rr-panel">
                  <div className="rr-row rr-panel-head">
                    <strong>
                      {FACET_LABEL[facet]} <span className="rr-muted">{facet}</span>
                    </strong>
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
  const data = similar.data;
  const projectLink = (id: string, label?: string | null) => (
    <Link to={`/projects/${encodeURIComponent(id)}`}>{label || id}</Link>
  );
  // 경로마다 항목 모양이 다르다 — 한 표로 합치지 않는다(§5.7 '경로를 섞지 않는다').
  const empty = data !== null && data.lineage.length === 0 && data.vector.length === 0
    && data.text.length === 0 && data.subject.length === 0;

  return (
    <SectionCard
      title="유사 과제"
      subtitle={
        data ? `회수 경로 4종을 섞지 않고 따로 보입니다 · 코퍼스 ${data.corpus_n}건` : "회수 경로 4종을 섞지 않고 따로 보입니다."
      }
    >
      <ErrorBanner error={similar.error} onRetry={similar.reload} />
      {similar.loading && !data ? <LoadingBlock /> : null}
      {empty ? (
        <EmptyBlock title="유사 과제가 없습니다." hint="계보가 없고 코퍼스가 아직 얕습니다." />
      ) : null}
      {data ? (
        <>
          <div className="rr-stack">
            <h3 className="rr-subhead">계보</h3>
            {data.lineage.length === 0 ? (
              <p className="rr-muted">선행·후속 과제가 없습니다.</p>
            ) : (
              <ul className="rr-list">
                {data.lineage.map((e) => (
                  <li key={`${e.relation}:${e.project_id}`}>
                    {projectLink(e.project_id, e.code)}
                    <span className="rr-muted"> · {e.relation} · {e.hops}홉</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rr-stack">
            <h3 className="rr-subhead">특징 벡터</h3>
            {data.vector.length === 0 ? (
              <p className="rr-muted">{data.reason.vector ?? "이웃이 없습니다."}</p>
            ) : (
              <ul className="rr-list">
                {data.vector.map((e) => (
                  <li key={e.project_id}>
                    {projectLink(e.project_id)}
                    <span className="rr-muted"> · cosine {fmtNum(e.cosine)} · {e.rank}위</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rr-stack">
            <h3 className="rr-subhead">서술(AIDataHub)</h3>
            {data.text.length === 0 ? (
              <p className="rr-muted">{data.reason.text ?? "적중이 없습니다."}</p>
            ) : (
              <ul className="rr-list">
                {data.text.map((e) => (
                  <li key={e.record_id || `${e.project_id}:${e.rank}`}>
                    {projectLink(e.project_id)}
                    <span className="rr-muted"> · {e.rank}위 · {e.section_id || "-"}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="rr-stack">
            <h3 className="rr-subhead">같은 subject</h3>
            {data.subject.length === 0 ? (
              <p className="rr-muted">겹치는 subject 가 없습니다.</p>
            ) : (
              <ul className="rr-list">
                {data.subject.map((e) => (
                  <li key={e.subject_key}>
                    <code>{e.subject_key}</code>
                    <span className="rr-muted">
                      {" "}· 등록부 {e.n_registry}건(확인 {e.n_verified}) · 과제{" "}
                    </span>
                    {e.project_ids.map((pid, i) => (
                      <span key={pid}>
                        {i > 0 ? ", " : ""}
                        {projectLink(pid)}
                      </span>
                    ))}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {data.merged.length > 0 ? (
            <div className="rr-stack">
              <h3 className="rr-subhead">경로 합산</h3>
              <ul className="rr-list">
                {data.merged.map((e) => (
                  <li key={e.project_id}>
                    {projectLink(e.project_id)}
                    <span className="rr-muted"> · score {fmtNum(e.score)} · {e.paths.join(" · ")}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}
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
                adapters={adapters.data?.apps ?? []}
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

      <RequirementsCard
        projectId={projectId}
        predecessorId={(detail.data as ProjectDetail | null)?.project?.predecessor_project_id ?? null}
      />

      <SectionCard title="dims 정의">
        <DimForm projectId={projectId} />
      </SectionCard>

      <SectionCard title="iface-ledger" subtitle="확정 원장은 앱 DB 에만 저장합니다.">
        <IfaceLedgerEditor projectId={projectId} />
      </SectionCard>

      <VocabCard />
      <CharacterCard projectId={projectId} />
      <SimilarCard projectId={projectId} />
    </>
  );
}
