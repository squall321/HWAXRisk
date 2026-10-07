// 과제 화면 — 머리말·구역 탭 4개(심사 · 요구·정의 · 성격·유사 · 사전)·소스 카드 3장·스냅샷 동결·스냅샷 목록·dims·iface-ledger·성격 프로파일·유사 과제(계획 §8.2.4 ProjectPage 행). ?snapshot= 이면 같은 화면에 SnapshotPage 를 그린다.
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ChevronRight, Link2, Plus, Snowflake, Trash2, X } from "lucide-react";
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
import {
  Banner,
  Button,
  FormField,
  FormGrid,
  Input,
  Mono,
  PageHeader,
  Select,
  SubPanel,
  TabBar,
  TabPanel,
} from "../ui/primitives";
import { fmtEpoch, fmtNum } from "../format";
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
  SourceRef,
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

/**
 * 값이 없을 때 쓰는 자리 — 0 이나 '-' 가 아니라 '모름' 으로 읽히게 한다.
 * 미측정·미입력은 실패가 아니고, 그 사실 자체가 정보다(앱 제1 규율).
 */
const UNKNOWN = <span className="text-muted-foreground">—</span>;

/** 서버가 문자열로 주는 `kinds_json` 을 푼다. 깨진 값은 빈 목록이다(화면을 터뜨리지 않는다). */
function parseKinds(raw: string | null | undefined): string[] {
  if (!raw) return [];
  try {
    const v: unknown = JSON.parse(raw);
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

/** 소스 `ref` 객체를 키=값 줄로 편다 — 모양이 kind 마다 달라 고정 필드로 못 적는다. */
function RefPairs({ ref_ }: { ref_: SourceRef }) {
  const pairs = Object.entries(ref_);
  if (pairs.length === 0) return UNKNOWN;
  return (
    <span className="flex flex-col gap-0.5">
      {pairs.map(([k, v]) => (
        <span key={k} className="flex flex-wrap items-baseline gap-1">
          <span className="font-mono text-xs opacity-60">{k}</span>
          <Mono>{String(v)}</Mono>
        </span>
      ))}
    </span>
  );
}

/**
 * 서버가 **재서** '없다' 고 말한 자리. UNKNOWN(모름)과 반드시 구분한다 —
 * 측정 안 된 것과 측정해서 아니었던 것을 한 기호로 그리면 제1 규율이 거꾸로 선다.
 */
function NONE() {
  return <span className="text-muted-foreground">없음</span>;
}

/**
 * 과제 화면의 구역 묶음 4개.
 *
 * 카드가 열세 장이라 한 줄로 쌓으면 아래 절반은 스크롤로만 닿는다. 그래서 묶되 — **심사를 시작하려면
 * 꼭 봐야 하는 것(소스·스냅샷 동결·스냅샷 목록·잡·타깃)은 기본 탭에 그대로 둔다.** 뒤로 보낸 것은
 * 가끔 고치는 정의(요구·dims·iface-ledger)와 참고용 맥락(성격·유사), 그리고 과제와 무관한 전사
 * 사전이다. 정보를 지운 것은 없고 자리만 옮겼다.
 */
type ProjectTab = "review" | "spec" | "context" | "vocab";
const PROJECT_TABS: Array<{ tab: ProjectTab; label: string }> = [
  { tab: "review", label: "심사" },
  { tab: "spec", label: "요구·정의" },
  { tab: "context", label: "성격·유사" },
  { tab: "vocab", label: "사전" },
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
    <SubPanel title={KIND_LABEL[kind]} actions={<SourceStatusBadge value={source?.status ?? "unlinked"} />}>
      {stub ? (
        <p className="m-0 text-sm text-muted-foreground">연결 대기(스텁) — 어댑터를 찾지 못했습니다.</p>
      ) : null}
      {source ? (
        // 카드가 좁으므로 한 열로 읽는다. 라벨은 사람 말이고 서버 필드명은 hint 로 남긴다.
        <KeyValueTable
          columns={1}
          rows={[
            { label: "어댑터", hint: "app_key", value: source.app_key ?? UNKNOWN },
            {
              label: "참조",
              hint: "ref",
              // 서버는 파싱된 객체를 준다(`{stepforge_project_id: …}` 등). 그대로 그리면 React 가
              // 터져 화면이 통째로 백지가 된다 — 실제로 그랬다. 키=값 줄로 편다.
              value: source.ref ? <RefPairs ref_={source.ref} /> : UNKNOWN,
            },
            {
              label: "브리지 선언",
              hint: "bridge_declared",
              // null·undefined 를 "false" 로 단정하지 않는다 — 안 적힌 것과 아니라고 적힌 것은 다르다.
              value: source.bridge_declared === undefined || source.bridge_declared === null
                ? UNKNOWN
                : source.bridge_declared ? "true" : "false",
            },
            {
              label: "도달 측정",
              hint: "probe",
              value: source.probe ? (
                <span className="flex flex-wrap items-center gap-2">
                  <Badge tone={source.probe.reachable ? "ok" : "bad"}>
                    {source.probe.reachable ? "reachable" : "unreachable"}
                  </Badge>
                  <span className="text-muted-foreground">
                    {source.probe.detail} · {source.probe.capture_mode}
                  </span>
                </span>
              ) : (
                UNKNOWN
              ),
            },
          ]}
        />
      ) : (
        <p className="m-0 text-sm text-muted-foreground">아직 연결하지 않았습니다.</p>
      )}
      <form className="mb-4 flex flex-col gap-3" onSubmit={link}>
        <ErrorBanner error={error} />
        <FormField label="어댑터" hint="app_key">
          <Select value={appKey} onChange={(e) => setAppKey(e.target.value)}>
            <option value="">선택</option>
            {candidates.map((a) => (
              <option key={a.app_key ?? a.kind} value={a.app_key ?? ""}>
                {a.app_key ?? a.kind} ({a.status})
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="참조" hint="ref">
          {choices.length > 0 ? (
            <Select value={ref} onChange={(e) => setRef(e.target.value)}>
              <option value="">선택</option>
              {choices.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                  {c.detail ? ` — ${c.detail}` : ""}
                </option>
              ))}
            </Select>
          ) : (
            <Input value={ref} onChange={(e) => setRef(e.target.value)} />
          )}
        </FormField>
        <label className="flex flex-wrap items-center gap-2">
          <input type="checkbox" checked={bridge} onChange={(e) => setBridge(e.target.checked)} />
          <span className="text-sm text-muted-foreground">bridge_declared</span>
        </label>
        <Button type="submit" variant="outline" className="self-start" disabled={busy || appKey === "" || ref === ""}>
          <Link2 className="size-4" aria-hidden="true" />
          연결
        </Button>
      </form>
    </SubPanel>
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
    <form className="mb-4 flex flex-col gap-3" onSubmit={submit}>
      <ErrorBanner error={error} />
      {notice ? <p className="m-0 text-sm text-muted-foreground">{notice}</p> : null}
      {/* degraded 는 서버가 준 사실이다 — 동결은 됐지만 온전히 읽지 못했다는 것을 지우지 않는다. */}
      {degraded ? (
        <Banner tone="warn" title="degraded" detail="일부 소스를 온전히 읽지 못한 채 동결했습니다." />
      ) : null}
      {gates ? (
        <>
          <GateBanner gates={gates} />
          <GateTable gates={gates} />
        </>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {SNAPSHOT_KINDS.map((kind) => (
          <label key={kind} className="flex flex-wrap items-center gap-2">
            <input type="checkbox" checked={kinds.includes(kind)} onChange={() => toggle(kind)} />
            <span className="text-sm">{KIND_LABEL[kind]}</span>
          </label>
        ))}
      </div>
      <FormGrid>
        <FormField label="스냅샷 이름" hint="label · 선택">
          <Input value={label} onChange={(e) => setLabel(e.target.value)} />
        </FormField>
        <FormField label="보고서 id" hint="report_ids · 쉼표 구분">
          <Input value={reportIds} onChange={(e) => setReportIds(e.target.value)} />
        </FormField>
        <FormField label="detect 결과 파일" hint="detect_result_file_id · 선택">
          <Input value={detectId} onChange={(e) => setDetectId(e.target.value)} />
        </FormField>
      </FormGrid>
      <Button type="submit" className="self-start" disabled={busy || kinds.length === 0}>
        <Snowflake className="size-4" aria-hidden="true" />
        스냅샷 동결
      </Button>
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
    <form className="mb-4 flex flex-col gap-3" onSubmit={submit}>
      <ErrorBanner error={error} />
      {created ? <p className="m-0 text-sm text-muted-foreground">등록됨 — {created}</p> : null}
      <FormGrid>
        <FormField label="이름" hint="name">
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </FormField>
        <FormField label="종류" hint="kind">
          <Input value={kind} onChange={(e) => setKind(e.target.value)} />
        </FormField>
        <FormField label="단위" hint="unit">
          <Input value={unit} onChange={(e) => setUnit(e.target.value)} />
        </FormField>
        <FormField label="추출기" hint="extractor">
          <Input value={extractor} onChange={(e) => setExtractor(e.target.value)} />
        </FormField>
      </FormGrid>
      <Button type="submit" variant="outline" className="self-start" disabled={!ready}>
        dim 정의 추가
      </Button>
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
    { key: "kind", header: "종류", hint: "kind", cell: (r) => r.kind, nowrap: true },
    { key: "name", header: "이름", hint: "name", cell: (r) => r.name },
    { key: "op", header: "비교", hint: "op", cell: (r) => r.op ?? UNKNOWN, nowrap: true },
    { key: "value", header: "값", hint: "value", cell: (r) => JSON.stringify(r.value_json ?? null) },
    { key: "unit", header: "단위", hint: "unit", cell: (r) => r.unit ?? UNKNOWN, nowrap: true },
    { key: "status", header: "status", cell: (r) => <StatusBadge value={r.status} />, nowrap: true },
    { key: "waive_reason", header: "사유", cell: (r) => r.waive_reason ?? UNKNOWN },
    {
      key: "actions",
      header: "결정",
      nowrap: true,
      cell: (r) => (
        <span className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={() => decide(r.id, "confirmed")}>
            확정
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={() => decide(r.id, "waived")}>
            waive
          </Button>
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
        <Button type="button" variant="ghost" className="mt-3" onClick={inherit}>
          계보 과제에서 요구 승계
        </Button>
      ) : null}
      <form className="mb-4 flex flex-col gap-3" onSubmit={submit}>
        <FormGrid>
          <FormField label="종류" hint="kind">
            <Select value={kind} onChange={(e) => setKind(e.target.value as RequirementKind)}>
              <option value="dim_limit">dim_limit</option>
              <option value="scenario">scenario</option>
              <option value="standard">standard</option>
            </Select>
          </FormField>
          <FormField label="이름" hint="name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </FormField>
          <FormField label="비교" hint="op">
            <Select value={op} onChange={(e) => setOp(e.target.value)} disabled={kind !== "dim_limit"}>
              <option value="lte">lte</option>
              <option value="gte">gte</option>
              <option value="between">between</option>
            </Select>
          </FormField>
          <FormField label="값" hint="value_json · JSON">
            <Input value={value} onChange={(e) => setValue(e.target.value)} />
          </FormField>
          <FormField label="단위" hint="unit">
            <Input value={unit} onChange={(e) => setUnit(e.target.value)} disabled={kind !== "dim_limit"} />
          </FormField>
          <FormField label="출처" hint="source_ref">
            <Input value={sourceRef} onChange={(e) => setSourceRef(e.target.value)} />
          </FormField>
        </FormGrid>
        <Button type="submit" variant="outline" className="self-start" disabled={busy || name.trim() === ""}>
          요구 저장
        </Button>
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
      cell: (r, i) => <Input value={r.pair_key} onChange={(e) => update(i, { pair_key: e.target.value })} />,
    },
    {
      key: "kind_override",
      header: "kind_override",
      cell: (r, i) => (
        <Input
          value={r.kind_override ?? ""}
          onChange={(e) => update(i, { kind_override: e.target.value === "" ? null : e.target.value })}
        />
      ),
    },
    {
      key: "status",
      header: "status",
      cell: (r, i) => <Input value={r.status} onChange={(e) => update(i, { status: e.target.value })} />,
    },
    {
      key: "note",
      header: "note",
      cell: (r, i) => (
        <Input
          value={r.note ?? ""}
          onChange={(e) => update(i, { note: e.target.value === "" ? null : e.target.value })}
        />
      ),
    },
    {
      key: "remove",
      header: "",
      nowrap: true,
      cell: (_r, i) => (
        <Button type="button" variant="ghost" size="sm" onClick={() => setRows((p) => p.filter((_, j) => j !== i))}>
          <Trash2 className="size-4" aria-hidden="true" />
          삭제
        </Button>
      ),
    },
  ];

  return (
    <>
      <ErrorBanner error={error} />
      {saved ? <p className="m-0 text-sm text-muted-foreground">확정 원장을 저장했습니다.</p> : null}
      <DataTable columns={columns} rows={rows} rowKey={(_r, i) => String(i)} empty="확정할 인터페이스 행이 없습니다." />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={() => setRows((p) => [...p, { pair_key: "", kind_override: null, status: "confirmed", note: null }])}
        >
          <Plus className="size-4" aria-hidden="true" />
          행 추가
        </Button>
        <Button type="button" onClick={save} disabled={busy || rows.length === 0}>
          저장
        </Button>
        <span className="text-sm text-muted-foreground">확정은 앱 원장에만 기록됩니다.</span>
      </div>
      <p className="mt-3 mb-0 text-sm text-muted-foreground">
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
        // 메이저 승급은 기존 파트 키를 낡게 만든다 — 그래서 정보가 아니라 오류 톤이다.
        <Banner
          tone={bump.recompute_required ? "error" : "info"}
          title={`${bump.vocab_version} · ${bump.bump} 승급`}
          detail={
            bump.recompute_required
              ? "메이저 승급입니다 — 기존 파트 키가 낡았습니다. backend/scripts/recompute_part_keys.py 를 돌리기 전까지 새 스냅샷은 409 recompute_pending 입니다."
              : "마이너 승급입니다 — 기존 ckey 와 ir_hash 는 그대로입니다."
          }
        />
      ) : null}

      <div className="mt-3 flex flex-col gap-2">
        <h3 className="m-0 text-sm text-muted-foreground">동의어</h3>
        <div className="flex flex-wrap items-center gap-2">
          <FormField label="대표 이름" hint="head">
            <Input value={head} onChange={(e) => setHead(e.target.value)} />
          </FormField>
          <FormField label="동의어" hint="from · 줄 또는 쉼표로 구분">
            <Input value={aliases} onChange={(e) => setAliases(e.target.value)} />
          </FormField>
          <Button
            type="button"
            variant="outline"
            disabled={busy || !head.trim() || aliasList.length === 0}
            onClick={() => run(() => riskApi.putVocabSynonym({ head: head.trim(), from: aliasList, op: "add" }))}
          >
            추가(마이너)
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={busy || !head.trim() || aliasList.length === 0}
            onClick={() => run(() => riskApi.putVocabSynonym({ head: head.trim(), from: aliasList, op: "remove" }))}
          >
            삭제(메이저)
          </Button>
        </div>
      </div>

      <div className="mt-3 flex flex-col gap-2">
        <h3 className="m-0 text-sm text-muted-foreground">stop tokens</h3>
        <div className="flex flex-wrap items-center gap-2">
          <FormField label="토큰" hint="tokens · 줄 또는 쉼표로 구분">
            <Input value={tokens} onChange={(e) => setTokens(e.target.value)} />
          </FormField>
          <Button
            type="button"
            variant="outline"
            disabled={busy || tokenList.length === 0}
            onClick={() => run(() => riskApi.putVocabStopTokens({ tokens: tokenList, op: "add" }))}
          >
            추가(마이너)
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={busy || tokenList.length === 0}
            onClick={() => run(() => riskApi.putVocabStopTokens({ tokens: tokenList, op: "remove" }))}
          >
            삭제(메이저)
          </Button>
        </div>
      </div>

      {vocab.data ? (
        <p className="mt-3 mb-0 text-sm text-muted-foreground">
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
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted-foreground">과제 성격 층</span>
              <Badge tone="info">{character.data.character_status}</Badge>
            </div>
          ) : null}
          <div className="mt-3 flex flex-col gap-2">
            {FACET_ORDER.map((facet) => {
              const statements = byFacet.get(facet) ?? [];
              return (
                <SubPanel
                  key={facet}
                  title={
                    <>
                      {FACET_LABEL[facet]} <span className="font-normal text-muted-foreground">{facet}</span>
                    </>
                  }
                >
                  <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(16rem,1fr))]">
                    {STATEMENT_LAYERS.map((layer) => {
                      const items = statements.filter((s) => s.status === layer.status);
                      return (
                        <div key={layer.status}>
                          <div className="text-sm text-muted-foreground">{layer.label}</div>
                          {items.length === 0 ? (
                            <p className="m-0 text-sm text-muted-foreground">없음</p>
                          ) : (
                            <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
                              {items.map((s) => (
                                <li key={s.id}>
                                  <Badge tone="neutral">{s.tag}</Badge> {s.statement}
                                  <span className="text-muted-foreground">
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
                </SubPanel>
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
          <div className="mt-3 flex flex-col gap-2">
            <h3 className="m-0 text-sm text-muted-foreground">계보</h3>
            {data.lineage.length === 0 ? (
              <p className="m-0 text-sm text-muted-foreground">선행·후속 과제가 없습니다.</p>
            ) : (
              <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
                {data.lineage.map((e) => (
                  <li key={`${e.relation}:${e.project_id}`}>
                    {projectLink(e.project_id, e.code)}
                    <span className="text-muted-foreground"> · {e.relation} · {e.hops}홉</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="mt-3 flex flex-col gap-2">
            <h3 className="m-0 text-sm text-muted-foreground">특징 벡터</h3>
            {data.vector.length === 0 ? (
              <p className="m-0 text-sm text-muted-foreground">{data.reason.vector ?? "이웃이 없습니다."}</p>
            ) : (
              <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
                {data.vector.map((e) => (
                  <li key={e.project_id}>
                    {projectLink(e.project_id)}
                    <span className="text-muted-foreground"> · cosine {fmtNum(e.cosine)} · {e.rank}위</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="mt-3 flex flex-col gap-2">
            <h3 className="m-0 text-sm text-muted-foreground">서술(AIDataHub)</h3>
            {data.text.length === 0 ? (
              <p className="m-0 text-sm text-muted-foreground">{data.reason.text ?? "적중이 없습니다."}</p>
            ) : (
              <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
                {data.text.map((e) => (
                  <li key={e.record_id || `${e.project_id}:${e.rank}`}>
                    {projectLink(e.project_id)}
                    <span className="text-muted-foreground"> · {e.rank}위 · {e.section_id || "-"}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="mt-3 flex flex-col gap-2">
            <h3 className="m-0 text-sm text-muted-foreground">같은 subject</h3>
            {data.subject.length === 0 ? (
              <p className="m-0 text-sm text-muted-foreground">겹치는 subject 가 없습니다.</p>
            ) : (
              <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
                {data.subject.map((e) => (
                  <li key={e.subject_key}>
                    <Mono>{e.subject_key}</Mono>
                    <span className="text-muted-foreground">
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
            <div className="mt-3 flex flex-col gap-2">
              <h3 className="m-0 text-sm text-muted-foreground">경로 합산</h3>
              <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
                {data.merged.map((e) => (
                  <li key={e.project_id}>
                    {projectLink(e.project_id)}
                    <span className="text-muted-foreground"> · score {fmtNum(e.score)} · {e.paths.join(" · ")}</span>
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
  const [tab, setTab] = useState<ProjectTab>("review");

  const detail = useAsync((signal) => riskApi.getProject(projectId, { signal }), [projectId], projectId !== "");
  const adapters = useAsync((signal) => riskApi.getAdapters({ signal }), []);

  const jobs: JobHeader[] = detail.data?.jobs ?? [];
  const active = jobs.some((j) => j.state === "queued" || j.state === "running");
  useInterval(detail.reload, active ? POLL_MS : null);

  /** 방금 건 동결 잡. 끝나면 §8.2.4 대로 `?snapshot=` 을 열어 준다. */
  const [pendingJob, setPendingJob] = useState<string | null>(null);
  /** 방금 동결돼 열린 스냅샷 id. 탭을 뺏는 대신 이것으로 알린다. 사용자가 닫으면 사라진다. */
  const [frozen, setFrozen] = useState<string | null>(null);
  useEffect(() => {
    if (pendingJob === null || !detail.data) return;
    const job = detail.data.jobs.find((j) => j.id === pendingJob);
    if (job && (job.state === "queued" || job.state === "running")) return;
    setPendingJob(null);
    if (!job || job.state !== "done") return;
    const newest = detail.data.snapshots.reduce<SnapshotHeader | null>(
      (best, s) => (best === null || s.created_at > best.created_at ? s : best),
      null,
    );
    if (newest) {
      // 스냅샷은 열어 두되 **탭은 뺏지 않는다.** 이 effect 는 5초 폴링이 깨우므로, 탭을 옮기면
      // 사용자가 아무것도 누르지 않았는데 보던 화면이 바뀐다. 다른 탭에서 입력 중이었다면
      // 그 입력이 눈앞에서 사라지는 것으로 보인다. 동결이 끝났다는 사실은 아래 배너로 말한다.
      setParams({ snapshot: newest.id });
      setFrozen(newest.id);
    }
  }, [pendingJob, detail.data, setParams]);

  const snapshotColumns: Column<SnapshotHeader>[] = [
    { key: "id", header: "스냅샷", hint: "snapshot_id", cell: (s) => <Mono>{s.id}</Mono>, nowrap: true },
    { key: "hash", header: "IR 해시", hint: "ir_hash", cell: (s) => <Mono>{s.ir_hash}</Mono>, nowrap: true },
    // 서버는 `kinds_json` 을 **문자열 그대로** 준다(routes.py 가 변환하지 않는다). 여기서 푼다.
    { key: "kinds", header: "소스", hint: "kinds_json", cell: (s) => parseKinds(s.kinds_json).join(" · "), nowrap: true },
    { key: "at", header: "동결 시각", hint: "created_at", cell: (s) => fmtEpoch(s.created_at), nowrap: true },
    {
      key: "counts",
      header: "집계",
      hint: "node_count · edge_count",
      cell: (s) => `노드 ${fmtNum(s.node_count)} · 엣지 ${fmtNum(s.edge_count)}`,
    },
    {
      key: "degraded",
      header: "degraded",
      // `degraded: boolean` 은 서버가 **재서** 아니라고 말한 값이다 — UNKNOWN(모름) 을 쓰면
      // 측정 안 된 것과 측정해서 아니었던 것이 한 기호로 합쳐진다. 그건 이 앱 제1 규율의 반대다.
      cell: (s) => (s.degraded ? <Badge tone="warn">degraded</Badge> : <NONE />),
      nowrap: true,
    },
  ];

  const targetColumns: Column<TargetHeader>[] = [
    {
      key: "key",
      header: "타깃", hint: "target_key",
      nowrap: true,
      cell: (t) => <Link to={`/targets/${encodeURIComponent(t.target_key)}`}>{t.target_key}</Link>,
    },
    { key: "kind", header: "종류", hint: "kind", cell: (t) => t.kind, nowrap: true },
    { key: "level", header: "완결 레벨", hint: "level", cell: (t) => <LevelBadge value={t.level} />, nowrap: true },
    {
      key: "verdict",
      header: "판정", hint: "verdict_final",
      cell: (t) => <StatusBadge value={t.verdict_final ?? "undetermined"} />,
      nowrap: true,
    },
    { key: "unseated", header: "착석", cell: (t) => <UnseatedBadge n={t.unseated_n} />, nowrap: true },
    { key: "sync", header: "반영", hint: "external_sync", cell: (t) => <ExternalSyncBadge sync={t.external_sync} />, nowrap: true },
    {
      key: "superseded",
      header: "대체됨", hint: "superseded_by",
      nowrap: true,
      cell: (t) =>
        t.superseded_by ? (
          <Link to={`/targets/${encodeURIComponent(t.superseded_by)}`}>{t.superseded_by}</Link>
        ) : (
          UNKNOWN
        ),
    },
  ];

  const jobColumns: Column<JobHeader>[] = [
    { key: "id", header: "잡", hint: "job_id", cell: (j) => <Mono>{j.id}</Mono>, nowrap: true },
    { key: "kind", header: "종류", hint: "kind", cell: (j) => j.kind, nowrap: true },
    { key: "state", header: "상태", cell: (j) => <JobStateBadge value={j.state} />, nowrap: true },
    {
      key: "progress",
      header: "진행",
      nowrap: true,
      width: "10rem",
      cell: (j) => {
        const pct = Math.max(0, Math.min(100, Math.round(j.progress * 100)));
        return (
          <span className="flex items-center gap-2">
            <span aria-hidden="true" className="inline-block h-1.5 w-24 overflow-hidden rounded-full bg-muted">
              <span className="block h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
            </span>
            <span className="tabular-nums">{pct}%</span>
          </span>
        );
      },
    },
    // error 가 null 인 것은 '오류가 없었다' 는 확정 사실이다(모름이 아니다).
    { key: "error", header: "오류", cell: (j) => j.error ?? <NONE /> },
  ];

  /** 상위 화면으로 돌아가는 길 — 상세 화면은 id 로 들어오므로 늘 보여야 한다. */
  const crumb = (
    <>
      <Link to="/">과제 목록</Link>
      <ChevronRight className="size-3 opacity-60" aria-hidden="true" />
      <span className="truncate">{detail.data?.project.code ?? projectId}</span>
    </>
  );

  if (projectId === "") {
    return (
      <>
        <PageHeader crumb={crumb} title="과제" />
        <SectionCard title="과제">
          <EmptyBlock title="과제를 찾을 수 없습니다." />
        </SectionCard>
      </>
    );
  }

  return (
    <>
      <PageHeader
        crumb={crumb}
        title={detail.data ? detail.data.project.name : "과제"}
        // id 는 이름 자리가 아니라 보조 사실 자리다 — 사람은 이름으로 과제를 부르고 id 로 서버와 대조한다.
        subtitle={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {detail.data ? <Mono>{detail.data.project.code}</Mono> : null}
            {detail.data?.project.stage ? <span>단계 {detail.data.project.stage}</span> : null}
            <span className="opacity-70">project_id</span>
            <Mono>{projectId}</Mono>
          </span>
        }
        actions={detail.data ? <ExternalSyncBadge sync={detail.data.project.external_sync ?? null} /> : null}
      />

      {/* 과제 조회 실패는 **탭 밖**에서 말한다. 탭 안에 두면 다른 탭에서는 경고도 재시도 버튼도 없이
          머리말이 그냥 "과제" 로 조용히 그려진다 — 사라진 것이 값이 아니라 경고라 더 나쁘다. */}
      <ErrorBanner error={detail.error} onRetry={detail.reload} />

      {/* 동결이 끝났다는 사실은 여기서 말한다 — 폴링이 사용자의 탭을 옮기지 않기 위해서다. */}
      {frozen && tab !== "review" ? (
        <Banner tone="info" title="동결이 끝났습니다." detail="새 스냅샷이 '심사' 탭에 열려 있습니다.">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setTab("review");
              setFrozen(null);
            }}
          >
            보러 가기
          </Button>
        </Banner>
      ) : null}

      <TabBar idPrefix="proj" tabs={PROJECT_TABS} value={tab} onChange={setTab} label="과제 구역 탭" />

      {/* 탭은 **보이는 것만** 바꾼다 — 조건부 렌더로 쓰면 iface-ledger 의 저장 전 행처럼
          서버에서 다시 읽을 경로가 없는 입력이 탭 전환만으로 사라진다(TabPanel 주석 참조). */}
      <TabPanel active={tab === "review"} tab="review" idPrefix="proj">
          <SectionCard title="과제 개요">
            {detail.loading && !detail.data ? <LoadingBlock /> : null}
            {detail.data ? (
              // 라벨은 사람 말로, 원시 필드명은 hint 로 접어 둔다(D35 — 화면이 엔지니어 덤프가 되지 않게 하되
              // 서버와 대조할 이름을 지우지는 않는다). 값과 순서는 그대로다.
              <KeyValueTable
                rows={[
                  { label: "단계", hint: "stage", value: detail.data.project.stage ?? UNKNOWN },
                  {
                    label: "선행 과제",
                    hint: "predecessor_project_id",
                    value: detail.data.project.predecessor_project_id ? (
                      <Link to={`/projects/${encodeURIComponent(detail.data.project.predecessor_project_id)}`}>
                        {detail.data.project.predecessor_project_id}
                      </Link>
                    ) : (
                      UNKNOWN
                    ),
                  },
                  {
                    label: "AIDataHub 범위",
                    hint: "adh_scope",
                    value: detail.data.project.adh_scope
                      ? `${detail.data.project.adh_scope.team} / ${detail.data.project.adh_scope.group}`
                      : UNKNOWN,
                  },
                  { label: "만든 때", hint: "created_at", value: fmtEpoch(detail.data.project.created_at) },
                  {
                    label: "성격 태그",
                    hint: "character_top_tags",
                    value:
                      detail.data.character_top_tags.length === 0 ? (
                        <span className="text-muted-foreground">없음</span>
                      ) : (
                        <span className="inline-flex flex-wrap items-center gap-1">
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

          <SectionCard
            title="스냅샷"
            subtitle="행을 누르면 아래에 스냅샷 화면이 열립니다."
            // 닫기는 열어 준 카드가 들고 있는다 — 떠다니는 버튼 한 개로는 무엇을 닫는지 말하지 못한다.
            actions={
              snapshotId ? (
                <Button type="button" variant="ghost" size="sm" onClick={() => setParams({})}>
                  <X className="size-4" aria-hidden="true" />
                  스냅샷 화면 닫기
                </Button>
              ) : null
            }
          >
            <DataTable
              columns={snapshotColumns}
              rows={detail.data?.snapshots ?? []}
              rowKey={(s) => s.id}
              selectedKey={snapshotId}
              onRowClick={(s) => setParams({ snapshot: s.id })}
              empty="동결된 스냅샷이 없습니다."
            />
          </SectionCard>

          {/* 누른 행의 내용은 바로 아래에 와야 한다 — 전에는 타깃 표를 지나야 나왔다(열어 놓고도 못 찾는다). */}
          {snapshotId ? <SnapshotPage snapshotId={snapshotId} /> : null}

          <SectionCard title="타깃">
            <DataTable
              columns={targetColumns}
              rows={detail.data?.targets ?? []}
              rowKey={(t) => t.target_key}
              empty="열린 타깃이 없습니다."
            />
          </SectionCard>
      </TabPanel>

      <TabPanel active={tab === "spec"} tab="spec" idPrefix="proj">
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
      </TabPanel>

      <TabPanel active={tab === "context"} tab="context" idPrefix="proj">
        <CharacterCard projectId={projectId} />
        <SimilarCard projectId={projectId} />
      </TabPanel>

      {/* 사전은 과제가 아니라 전사 자산이다 — 과제 구역과 섞이지 않게 탭을 따로 둔다. */}
      <TabPanel active={tab === "vocab"} tab="vocab" idPrefix="proj">
        <VocabCard />
      </TabPanel>
    </>
  );
}
