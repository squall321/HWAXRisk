// 비교 화면 — base/target 선택·SameAsResolver·게이트·diff 생성·comparability·3층 DiffView·사건·선례·타깃 만들기(계획 §8.2.4 ComparePage 행).
import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { GitCompare, Target } from "lucide-react";
import { ApiError, isNotReady, riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { SectionCard, VerbatimBlock } from "../components/SectionCard";
import type { Column } from "../components/DataTable";
import { DataTable, KeyValueTable } from "../components/DataTable";
import { EmptyBlock, ErrorBanner, LoadingBlock, NotReadyBlock } from "../components/StateBlocks";
import { Badge } from "../components/Badge";
import { GateBanner, GateTable, isGateFailing } from "../components/GateBanner";
import { SameAsResolver } from "../components/SameAsResolver";
import { Banner, Button, FormField, FormGrid, Mono, PageHeader, Select, SubPanel } from "../ui/primitives";
import { fmtCell, fmtCounts, fmtEpoch } from "../format";
import type { DiffBlocked, DiffEvent, DiffItem, DiffLayer, Gate, ProjectCard } from "../types";

const LAYERS: Array<{ layer: DiffLayer; label: string }> = [
  { layer: "structural", label: "구조" },
  { layer: "parametric", label: "파라메트릭" },
  { layer: "semantic", label: "의미" },
];
/** summary_text 각 줄의 각주 — `[c:<cid>]`. */
const FOOTNOTE_RE = /\[c:([^\]]+)\]/g;

/** §3.3.6 excluded_reason 사전. 값은 서버 문자열 그대로 두고 뜻만 붙인다. */
const EXCLUDED_LABEL: Record<string, string> = {
  tol_differs: "두 스냅샷의 공차 설정이 다름",
  tol_unknown: "공차 설정을 읽지 못함",
  result_kind_differs: "결과 kind 가 다름",
  sim_params_differ: "해석 파라미터가 다름",
  unit_scale: "단위·축척 불일치",
  partial_scope: "부분 검출 범위 밖",
  suspect_coords: "좌표계 의심",
  null_one_side: "한쪽 값이 없음",
  sameas_pending: "대응 미확정",
  bridge_stale: "메시 다리(bridge)가 낡음",
};

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
              {s.label ?? s.id} · {fmtEpoch(s.captured_at)}
              {s.degraded ? " · degraded" : ""}
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

function DiffView({
  diffId,
  base,
  target,
  semanticBlocked,
}: {
  diffId: string;
  /** 주소에서 고른 두 스냅샷 — 식별자 카드가 그대로 보인다(diff 본문을 기다리지 않는다). */
  base: string;
  target: string;
  semanticBlocked: boolean;
}) {
  const doc = useAsync((signal) => riskApi.getDiff(diffId, { signal }), [diffId]);
  const summary = useAsync((signal) => riskApi.getDiffSummary(diffId, { signal }), [diffId]);
  const events = useAsync((signal) => riskApi.getDiffEvents(diffId, { signal }), [diffId]);
  const precedents = useAsync((signal) => riskApi.getPrecedents(diffId, { signal }), [diffId]);
  const [selectedCid, setSelectedCid] = useState<string | null>(null);

  /** 제외 사유별 건수 — 항목은 diff 에 남고 의미 이벤트만 생기지 않는다(§3.3.6). */
  const excludedCounts = useMemo(() => {
    const acc: Record<string, number> = {};
    for (const item of doc.data?.items ?? []) {
      const reason = item.excluded_reason;
      if (typeof reason === "string" && reason !== "") acc[reason] = (acc[reason] ?? 0) + 1;
    }
    return acc;
  }, [doc.data]);

  const itemColumns: Column<DiffItem>[] = [
    { key: "cid", header: "cid", cell: (d) => <code>{d.cid}</code>, nowrap: true },
    { key: "code", header: "code", cell: (d) => d.code, nowrap: true },
    { key: "subject", header: "subject", cell: (d) => d.subject },
    { key: "before", header: "before", cell: (d) => fmtCell(d.before) },
    { key: "after", header: "after", cell: (d) => fmtCell(d.after) },
    { key: "delta", header: "delta", cell: (d) => fmtCell(d.delta), nowrap: true },
    { key: "flag", header: "flag", cell: (d) => fmtCell(d.flag), nowrap: true },
    {
      key: "excluded",
      header: "excluded_reason",
      nowrap: true,
      cell: (d) =>
        typeof d.excluded_reason === "string" && d.excluded_reason !== "" ? (
          <Badge tone="muted" title={EXCLUDED_LABEL[d.excluded_reason] ?? "사전에 없는 사유입니다."}>
            {d.excluded_reason}
          </Badge>
        ) : (
          "-"
        ),
    },
    { key: "ref", header: "ref", cell: (d) => (d.ref ? <code>{d.ref}</code> : "-") },
  ];

  const eventColumns: Column<DiffEvent>[] = [
    { key: "cid", header: "cid", cell: (e) => <code>{e.cid}</code>, nowrap: true },
    { key: "code", header: "code", cell: (e) => e.code, nowrap: true },
    { key: "change_kind", header: "change_kind", cell: (e) => fmtCell(e.change_kind), nowrap: true },
    { key: "confidence", header: "confidence", cell: (e) => fmtCell(e.confidence), nowrap: true },
    { key: "text", header: "text", cell: (e) => e.text },
    {
      key: "refs",
      header: "refs",
      cell: (e) => (
        <span className="inline-flex flex-wrap items-center gap-1">
          {e.refs.map((r) => (
            <code key={r}>{r}</code>
          ))}
        </span>
      ),
    },
  ];

  return (
    <>
      {/* 순서를 바꿨다 — 비교할 수 없는 두 스냅샷의 diff 를 읽는 것은 무의미하므로 그 판정을 요약보다 위로 올렸다. */}
      <SectionCard title="비교 가능성(comparability)" subtitle="판정은 서버가 계산한 값입니다.">
        <div className="flex flex-col gap-3">
          {isNotReady(doc.error) ? (
            <NotReadyBlock what="diff 본문" />
          ) : (
            <ErrorBanner error={doc.error} onRetry={doc.reload} />
          )}
          {doc.loading && !doc.data ? <LoadingBlock /> : null}
          {doc.data ? (
            <KeyValueTable
              rows={[
                {
                  label: "비교 가능",
                  hint: "comparability.ok",
                  value: (
                    <Badge tone={doc.data.comparability.ok ? "ok" : "bad"}>
                      {doc.data.comparability.ok ? "ok" : "no"}
                    </Badge>
                  ),
                },
                {
                  label: "제외 사유",
                  hint: "excluded_reason",
                  value: doc.data.comparability.excluded_reason ? (
                    <Badge
                      tone="muted"
                      title={EXCLUDED_LABEL[doc.data.comparability.excluded_reason] ?? "사전에 없는 사유입니다."}
                    >
                      {doc.data.comparability.excluded_reason}
                    </Badge>
                  ) : (
                    <span className="text-muted-foreground">없음</span>
                  ),
                },
                {
                  label: "비고",
                  hint: "note",
                  value: doc.data.comparability.note ?? <span className="text-muted-foreground">없음</span>,
                },
                { label: "건수 집계", hint: "counts", value: fmtCounts(doc.data.counts) },
                {
                  label: "제외 항목",
                  hint: "items[].excluded_reason",
                  value:
                    Object.keys(excludedCounts).length === 0 ? (
                      <span className="text-muted-foreground">없음</span>
                    ) : (
                      <span className="inline-flex flex-wrap items-center gap-1">
                        {Object.entries(excludedCounts).map(([reason, n]) => (
                          <Badge key={reason} tone="muted" title={EXCLUDED_LABEL[reason] ?? "사전에 없는 사유입니다."}>
                            {reason} {n}건
                          </Badge>
                        ))}
                      </span>
                    ),
                },
              ]}
            />
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
            <>
              <VerbatimBlock text={summary.data.summary_text} label="summary_text" />
              <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
                {(summary.data.lines ?? []).map((line, i) => {
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
                          onClick={() => setSelectedCid(cid)}
                        >
                          {cid}
                        </Button>
                      ))}
                    </li>
                  );
                })}
              </ul>
            </>
          ) : null}
        </div>
      </SectionCard>

      {/* 아래로 내렸다 — 식별자는 대조할 때만 필요하고 판정·요약보다 먼저 읽을 것이 아니다(지우지는 않는다). */}
      <SectionCard title="비교한 두 스냅샷" subtitle="주소에서 고른 짝입니다.">
        <KeyValueTable
          rows={[
            { label: "기준 스냅샷", hint: "base_snapshot_id", value: <code>{base || "-"}</code> },
            { label: "비교 대상 스냅샷", hint: "target_snapshot_id", value: <code>{target || "-"}</code> },
          ]}
        />
      </SectionCard>

      <SectionCard title="diff 3층" subtitle="구조 · 파라메트릭 · 의미 층을 서버가 준 항목 그대로 보입니다.">
        {doc.data
          ? LAYERS.map(({ layer, label }) => {
              const rows = (doc.data?.items ?? []).filter((d) => d.layer === layer);
              return (
                <div key={layer} className="mt-3 flex flex-col gap-2">
                  <h3 className="m-0 text-sm text-muted-foreground">
                    <strong className="font-medium text-foreground">{label}</strong>{" "}
                    <span className="tabular-nums">{rows.length}건</span>
                  </h3>
                  {layer === "semantic" && semanticBlocked ? (
                    <Banner
                      tone="info"
                      title="의미층 차단(G2)."
                      detail="대응이 미확정이라 의미 이벤트를 만들지 않았습니다."
                    />
                  ) : null}
                  <DataTable
                    columns={itemColumns}
                    rows={rows}
                    rowKey={(d) => d.cid}
                    selectedKey={selectedCid}
                    onRowClick={(d) => setSelectedCid(d.cid)}
                    empty={`${label} 층 변경이 없습니다.`}
                  />
                </div>
              );
            })
          : null}
      </SectionCard>

      <SectionCard title="조립 그래프(before/after)" subtitle="계획 §8.2.4 의 mermaid 그래프 자리입니다.">
        <NotReadyBlock what="조립 그래프" />
      </SectionCard>

      <SectionCard title="사건(events)" subtitle="의미층 이벤트 펼침 표입니다.">
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
              rows={events.data ?? []}
              rowKey={(e, i) => `${e.cid}#${i}`}
              selectedKey={selectedCid}
              onRowClick={(e) => setSelectedCid(e.cid)}
              empty="사건이 없습니다."
            />
          ) : null}
        </div>
      </SectionCard>

      <SectionCard title="선례" subtitle="rr_delta_priors 의 수치만 보입니다.">
        <div className="flex flex-col gap-3">
          {isNotReady(precedents.error) ? (
            <NotReadyBlock what="선례" />
          ) : (
            <ErrorBanner error={precedents.error} onRetry={precedents.reload} />
          )}
          {precedents.loading && !precedents.data ? <LoadingBlock /> : null}
          {precedents.data ? (
            <DataTable
              columns={[
                { key: "cluster", header: "cluster_key", cell: (r) => <code>{String(r.cluster_key)}</code>, nowrap: true },
                { key: "n", header: "n", cell: (r) => String(r.n), align: "right", nowrap: true },
                { key: "in", header: "in_range", cell: (r) => String(r.in_range), align: "right", nowrap: true },
                { key: "out", header: "out_of_range", cell: (r) => String(r.out_of_range), align: "right", nowrap: true },
              ]}
              rows={precedents.data.rows ?? []}
              rowKey={(r, i) => `${String(r.cluster_key)}#${i}`}
              empty="선례가 없습니다."
            />
          ) : null}
        </div>
      </SectionCard>
    </>
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
  const [gates, setGates] = useState<Gate[] | null>(null);
  const [g2, setG2] = useState<Gate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const blocked = isGateFailing(gates, "G6");
  const semanticBlocked = g2 !== null && !g2.pass;
  const ready = base !== "" && target !== "" && base !== target;

  function setParam(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value === "") next.delete(name);
    else next.set(name, value);
    next.delete("diff");
    setParams(next);
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
      setGates(null);
      const next = new URLSearchParams(params);
      next.set("diff", created.diff_id);
      setParams(next);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const body = err.body as Partial<DiffBlocked> | null;
        setGates(body?.gates ?? null);
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
            <Button type="button" onClick={createTarget} disabled={busy}>
              <Target className="size-4" aria-hidden="true" />
              타깃 만들기
            </Button>
          ) : null
        }
      />

      {/* diff 생성·타깃 만들기 둘이 같은 `error` 를 쓴다. 버튼 하나가 머리말로 올라갔으므로 배너도
          화면 맨 위에 둔다 — 아래 카드 안에 두면 타깃 만들기 실패가 긴 화면 밑에서 조용히 뜬다. */}
      <ErrorBanner error={error} />

      {/* 순서를 바꿨다 — diff 가 있으면 그 판정이 먼저다. 고르기·same-as 는 그 diff 를 만든 수단이라 아래로 내렸다. */}
      {diffId ? <DiffView diffId={diffId} base={base} target={target} semanticBlocked={semanticBlocked} /> : null}

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
          {gates ? (
            <>
              <GateBanner gates={gates} />
              <GateTable gates={gates} />
            </>
          ) : null}
          {semanticBlocked ? <Banner tone="info" title="의미층 차단(G2)." detail={g2?.message} /> : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              onClick={createDiff}
              disabled={!ready || busy || blocked}
              title={blocked ? "G6 fail 이라 diff 를 만들 수 없습니다." : undefined}
            >
              <GitCompare className="size-4" aria-hidden="true" />
              diff 생성
            </Button>
            {blocked ? <span className="text-sm text-muted-foreground">G6 fail — diff 를 만들 수 없습니다.</span> : null}
            {!ready ? <span className="text-sm text-muted-foreground">서로 다른 두 스냅샷을 고르세요.</span> : null}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="same-as 확정" subtitle="자동 매칭을 사람이 확정합니다 — 소스 앱에는 쓰지 않습니다.">
        {ready ? (
          <SameAsResolver base={base} target={target} onG2={setG2} />
        ) : (
          <EmptyBlock title="스냅샷을 두 개 고르면 매칭 후보가 나옵니다." />
        )}
      </SectionCard>
    </>
  );
}
