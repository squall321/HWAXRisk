// 타깃 화면 — 판정 요약(verdict·완결 레벨)을 맨 위에 고정하고 그 아래 탭으로 진행판·패널·등록부·보고서·브리프·품질을 묶는다(계획 §8.2.4 TargetPage 행). 카드 대조 대상은 셀 격자 · 전문가 · 쟁점 · 완결 탭과 종합 보고서가 더해진다(재설계 M3). :key 는 snap:<id>/diff:<id> 다.
import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ChevronLeft, RefreshCw, Users } from "lucide-react";
import { isApiError, riskApi } from "../api/risk.api";
import {
  EXTERNAL_WORKFLOW,
  PANEL_EGRESS_WARNING,
  describeJobError,
  panelJobBody,
  panelJobReady,
} from "../api/panelJob";
import type { JudgeLlm, PanelJobForm } from "../api/panelJob";
import { POLL_MS, useAsync, useInterval } from "../hooks/useAsync";
import { SectionCard } from "../components/SectionCard";
import type { Column } from "../components/DataTable";
import { DataTable, KeyValueTable, TableScroll } from "../components/DataTable";
import { QualityCard } from "../components/QualityCard";
import { EmptyBlock, ErrorBanner, LoadingBlock, NotReadyBlock } from "../components/StateBlocks";
import {
  Badge,
  CoverageStatusBadge,
  ExternalSyncBadge,
  JobStateBadge,
  LevelBadge,
  LlmBadge,
  PanelStatusBadge,
  StatusBadge,
  toneOf,
  UnseatedBadge,
  VerdictBadge,
} from "../components/Badge";
import { PanelTranscript } from "../components/PanelTranscript";
import { CellsHead } from "../components/CellsHead";
import { ReviewBoard } from "../components/ReviewBoard";
import { ReviewJobFormCard } from "../components/ReviewJobForm";
import { CellGrid } from "../components/CellGrid";
import { ExpertReports } from "../components/ExpertReports";
import { UndeferForm } from "../components/UndeferForm";
import { IssuesCard } from "../components/IssuesCard";
import { SynthReport } from "../components/SynthReport";
import { ClosureCard } from "../components/ClosureCard";
import { RegistryCard } from "../components/RegistryCard";
import { seatActions, seatReasonLabel, skipReasonProblem } from "../lib/targetView";
import { JobSignalLine, ReviewWorkers } from "../components/JobSignals";
import { JobCancelConfirm } from "../components/JobCancelConfirm";
import {
  Banner, Button, FormField, FormGrid, Input, Mono, PageHeader, Select, TabBar, TabPanel,
} from "../ui/primitives";
import { cn } from "../lib/cn";
import { fmtEpoch, fmtNum, fmtPct } from "../format";
import type {
  BriefPanel,
  Coverage,
  CoverageJob,
  CoverageStatus,
  EvidenceItem,
  ExternalSync,
  Panel,
  RegistryQuery,
  ResyncQueued,
  Seat,
  TargetJobCreated,
  Tier,
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
const ACTIVE_JOB_STATES = new Set(["queued", "running", "cancelling"]);

/** target_key 접두 → 사람이 읽는 이름. 모르는 접두는 그대로 보인다(어휘를 지어내지 않는다). */
const KIND_LABEL: Record<string, string> = { snap: "스냅샷", diff: "비교" };

/** 화면 구역 탭 — 카드 여덟 개가 한 줄로 쌓여 있던 것을 묶는다. 판정·커버리지는 탭 밖에 남는다. */
type TargetTab =
  | "coverage"
  | "cells"
  | "experts"
  | "issues"
  | "closure"
  | "panels"
  | "registry"
  | "report"
  | "brief"
  | "quality";

/**
 * 진행판을 5초마다 다시 읽나 — 패널 잡 · 검토 잡 · 사슬(쟁점 · 종합) 잡 가운데 하나라도 돌거나 줄에 섰으면. 멈춘(paused) 잡은
 * 사람이 움직일 때까지 그대로라 읽지 않는다(누르면 화면이 다시 읽는다).
 */
function isPolling(coverage: Coverage | null): boolean {
  if (!coverage) return false;
  const live = (state: string | undefined) => state !== undefined && ACTIVE_JOB_STATES.has(state);
  return live(coverage.job?.state) || live(coverage.review?.job?.state) || live(coverage.stage?.state ?? undefined);
}

/** 모델 혼합 표 한 줄 — 패널을 센 값만 담는다. */
type ModelMixRow = { key: string; model: string; captured: string; n: number; done: number };

/**
 * 값이 없다는 사실을 그 자리에서 말한다 — `-` 는 '값이 하이픈' 으로 읽히고 0 과도 섞인다(null 은 0 이 아니다).
 * 다섯 상세 화면이 같은 자리에서 같은 말을 해야 하므로 **공용(primitives)으로 올릴 후보**다.
 */
function Unknown({ children = "—" }: { children?: ReactNode }) {
  return <span className="text-muted-foreground">{children}</span>;
}

/** 좌석 조작 거절 — 아는 code 는 제목을 고르고 서버 글은 글자 그대로 보인다. */
function SeatErrorBanner({ error }: { error: unknown }) {
  if (error === null || error === undefined) return null;
  if (isApiError(error) && error.code === "role_insufficient") {
    return <Banner title="편집자 이상만 좌석을 옮깁니다." detail={error.message} />;
  }
  if (isApiError(error) && error.code === "E100" && error.status === 409) {
    return <Banner title="이 좌석은 그렇게 옮길 수 없습니다." detail={error.message} />;
  }
  return <ErrorBanner error={error} />;
}

/**
 * 좌석 한 줄의 사람 조작(routes.put_coverage) — 넘기기(skipped, 사유 필수)와 carried 되돌리기(pending). 처리 뒤 행에는
 * status_source 'human' · decided_by 가 남는다(§6.8.2).
 */
function SeatActionForm({
  targetKey,
  seat,
  mode,
  onDone,
  onCancel,
}: {
  targetKey: string;
  seat: Seat;
  mode: "skip" | "revert";
  onDone: (note: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const problem = mode === "skip" ? skipReasonProblem(reason) : null;

  async function send(event: React.FormEvent) {
    event.preventDefault();
    if (problem) return;
    setBusy(true);
    setError(null);
    try {
      const out = await riskApi.putSeat(targetKey, seat.agent_key, {
        status: mode === "skip" ? "skipped" : "pending",
        reason: reason.trim() === "" ? undefined : reason.trim(),
      });
      onDone(
        mode === "skip"
          ? `${out.agent_key} 를 넘겼습니다(skipped) — ${out.decided_by ?? "나"} 의 결정으로 남습니다.`
          : `${out.agent_key} 를 다시 심사 대기(pending)로 되돌렸습니다.`,
      );
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="mt-3 flex flex-col gap-2 rounded-md border border-border p-3" onSubmit={send}>
      <SeatErrorBanner error={error} />
      <p className="m-0 text-sm">
        <code>{seat.agent_key}</code>{" "}
        {mode === "skip"
          ? "을(를) 넘깁니다 — 이 좌석은 이 대상에서 더 심사하지 않고 까닭이 원장에 남습니다."
          : "을(를) 다시 심사 대기로 되돌립니다 — 이어받은(carried) 의견 대신 새로 심사합니다."}
      </p>
      <FormField
        label={mode === "skip" ? "넘기는 까닭" : "되돌리는 까닭"}
        hint={mode === "skip" ? "필수" : "선택"}
        error={reason !== "" && problem ? problem : undefined}
      >
        <Input value={reason} onChange={(e) => setReason(e.target.value)} aria-label="좌석 조작 사유" />
      </FormField>
      <span className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={busy || problem !== null}>
          {mode === "skip" ? "넘기기" : "되돌리기"}
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
          그만두기
        </Button>
      </span>
    </form>
  );
}

function CoverageHeatmap({
  coverage,
  targetKey,
  targetKind,
  onChanged,
}: {
  coverage: Coverage;
  targetKey: string;
  /** 대상 종류(snap · diff) — 좌석 까닭 ecad_absent 의 뜻이 갈린다(ecad-1031 §9). */
  targetKind: string;
  onChanged: () => void;
}) {
  const [domain, setDomain] = useState<string | null>(null);
  const seats = useAsync(
    (signal) => riskApi.getSeats(targetKey, domain ?? "", { signal }),
    [targetKey, domain],
    domain !== null,
  );
  const [acting, setActing] = useState<{ seat: Seat; mode: "skip" | "revert" } | null>(null);
  const [seatNote, setSeatNote] = useState<string | null>(null);

  const domains = Object.keys(coverage.by_domain);
  /** 열별 합계 — 도메인 행을 더한 값이다(새 판정이 아니다). */
  const totals: Record<string, number> = {};
  for (const d of domains) {
    const counts = coverage.by_domain[d] ?? {};
    for (const s of COVERAGE_STATUSES) totals[s] = (totals[s] ?? 0) + (counts[s] ?? 0);
  }
  const seatColumns: Column<Seat>[] = [
    { key: "agent", header: "agent_key", cell: (s) => <code>{s.agent_key}</code>, nowrap: true },
    {
      key: "status",
      header: "status",
      nowrap: true,
      cell: (s) => (
        <span className="inline-flex items-center gap-1">
          <CoverageStatusBadge value={s.status} />
          {s.status_source === "human" ? (
            <Badge tone="info" title={`${s.decided_by ?? "?"} · ${fmtEpoch(s.decided_at)}`}>
              사람
            </Badge>
          ) : null}
        </span>
      ),
    },
    {
      key: "reason",
      header: "reason",
      cell: (s) => {
        if (!s.reason) return <Unknown />;
        // code 는 그대로 보이고 사람 말을 덧붙인다(ECAD 의존 영역 — 대상 종류마다 뜻이 다르다).
        const label = seatReasonLabel(s.reason, targetKind);
        // 까닭 code(snake_case)는 고정폭으로, 사람이 적은 넘김 사유는 글 그대로 보인다.
        return (
          <span>
            {/^[a-z0-9_]+$/.test(s.reason) ? <code>{s.reason}</code> : s.reason}
            {label ? <span className="text-muted-foreground"> — {label}</span> : null}
          </span>
        );
      },
    },
    {
      key: "panel",
      header: "panel_id",
      nowrap: true,
      cell: (s) => (s.panel_id ? <code>{s.panel_id}</code> : <Unknown />),
    },
    {
      key: "opinion",
      header: "opinion_id",
      nowrap: true,
      cell: (s) => (s.opinion_id ? <code>{s.opinion_id}</code> : <Unknown />),
    },
    {
      key: "act",
      header: "조작",
      nowrap: true,
      cell: (s) => {
        const can = seatActions(s);
        if (!can.skip && !can.revert) return null;
        return (
          <span className="flex flex-wrap items-center gap-1">
            {can.skip ? (
              <Button type="button" variant="ghost" size="sm" onClick={() => setActing({ seat: s, mode: "skip" })}>
                넘기기…
              </Button>
            ) : null}
            {can.revert ? (
              <Button type="button" variant="ghost" size="sm" onClick={() => setActing({ seat: s, mode: "revert" })}>
                되돌리기…
              </Button>
            ) : null}
          </span>
        );
      },
    },
  ];

  return (
    <>
      <TableScroll>
        {/* 합계 행(tfoot)과 행 머리(th scope=row) 때문에 DataTable 로는 그릴 수 없다 — 클래스는 DataTable 과 같은 값이다. */}
        <table className="w-full min-w-max border-collapse text-sm">
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">
                도메인
              </th>
              {COVERAGE_STATUSES.map((s) => (
                <th key={s} scope="col" className="px-3 py-2 text-right text-xs font-medium text-muted-foreground">
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
                  className={cn(
                    "cursor-pointer border-b border-border/60 last:border-0 hover:bg-muted/50",
                    domain === d && "bg-accent",
                  )}
                >
                  <th scope="row" className="px-3 py-2 text-left align-top font-medium">
                    {d}
                  </th>
                  {COVERAGE_STATUSES.map((s) => {
                    const n = counts[s] ?? 0;
                    return (
                      <td key={s} className="whitespace-nowrap px-3 py-2 text-right align-top tabular-nums">
                        {n === 0 ? (
                          // 0 은 서버가 센 값이라 '모름' 이 아니다 — 흐리게만 둔다.
                          <span className="text-muted-foreground">0</span>
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
              <tr className="border-t border-border">
                <th scope="row" className="px-3 py-2 text-left font-medium">
                  합계
                </th>
                {COVERAGE_STATUSES.map((s) => (
                  <td key={s} className="whitespace-nowrap px-3 py-2 text-right tabular-nums">
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
        <div className="mt-3 flex flex-col gap-2">
          <h3 className="m-0 text-sm text-muted-foreground">{domain} 좌석</h3>
          <ErrorBanner error={seats.error} onRetry={seats.reload} />
          {seats.loading && !seats.data ? <LoadingBlock /> : null}
          {seatNote ? <Banner tone="info" live="status" title={seatNote} /> : null}
          {seats.data ? (
            <DataTable columns={seatColumns} rows={seats.data.seats} rowKey={(s) => s.agent_key} empty="좌석이 없습니다." />
          ) : null}
          {acting ? (
            <SeatActionForm
              key={`${acting.seat.agent_key}:${acting.mode}`}
              targetKey={targetKey}
              seat={acting.seat}
              mode={acting.mode}
              onCancel={() => setActing(null)}
              onDone={(note) => {
                setActing(null);
                setSeatNote(note);
                seats.reload();
                onChanged();
              }}
            />
          ) : null}
          <p className="m-0 text-sm text-muted-foreground">
            넘기기는 pending · assigned · running · failed 좌석에, 되돌리기는 carried 좌석에만 열립니다. 보류(deferred) 좌석은 보류 풀기로
            풉니다.
          </p>
        </div>
      ) : null}
    </>
  );
}

/** 러너 자격의 말 — 값은 배지로 그대로 보이고 뜻을 덧붙인다(runner.resolve_credential_with_note · U-3). */
const CREDENTIAL_LABEL: Record<string, string> = {
  requester: "잡을 만든 사람의 PAT 로 돕니다.",
  owner: "대상 소유자의 PAT 로 돕니다.",
  service: "서비스 계정으로 돌았습니다.",
};

/** 반출 동의가 들어온 입구(routes.CONSENT_SOURCES) — 모르는 값은 그대로 보인다. */
const CONSENT_SOURCE_LABEL: Record<string, string> = { web: "웹 화면", mcp: "Claude(MCP)", api: "REST(개인 PAT)" };

/** 판단 LLM 고르기 — 기본은 이 박스의 LLM 이다. Claude 를 고르면 반출 경고와 동의 체크가 열린다(체크는 늘 비어서 시작한다). */
function LlmChoice({
  llm,
  consent,
  onLlm,
  onConsent,
}: {
  llm: JudgeLlm;
  consent: boolean;
  onLlm: (llm: JudgeLlm) => void;
  onConsent: (consent: boolean) => void;
}) {
  return (
    <fieldset className="mt-3 flex flex-col gap-2 rounded-md border border-border p-3">
      <legend className="px-1 text-xs font-medium text-muted-foreground">
        판단 LLM <span className="font-normal opacity-75">llm</span>
      </legend>
      <label className="flex flex-wrap items-center gap-2 text-sm">
        <input type="radio" name="panel-job-llm" value="glm" checked={llm === "glm"} onChange={() => onLlm("glm")} />
        <span>이 박스의 LLM(GLM) — 기본</span>
      </label>
      <label className="flex flex-wrap items-center gap-2 text-sm">
        <input type="radio" name="panel-job-llm" value="claude" checked={llm === "claude"} onChange={() => onLlm("claude")} />
        <span>Claude — 내 Claude Code 의 워크플로가 판단합니다(외부)</span>
      </label>
      {llm === "claude" ? (
        <div className="flex flex-col gap-2 rounded-md border-l-[3px] border-warn bg-warn/10 p-3 text-sm">
          <p className="m-0">{PANEL_EGRESS_WARNING}</p>
          <label className="flex flex-wrap items-center gap-2">
            <input type="checkbox" checked={consent} onChange={(e) => onConsent(e.target.checked)} />
            <span className="font-medium">위 내용이 Claude(외부)로 나가는 데 동의합니다.</span>
          </label>
          <p className="m-0 text-xs text-muted-foreground">
            만든 뒤에는 내 Claude Code 에서 워크플로 <code>{EXTERNAL_WORKFLOW}</code> 를 이 대상으로 돌려야 잡이 나아갑니다.
          </p>
        </div>
      ) : null}
    </fieldset>
  );
}

/** Claude 잡을 만든 직후의 안내 — 워크플로를 돌려야 나아가고, 돌지 않으면 보류로 멈춘다. */
function ClaudeWorkflowGuide({ targetKey }: { targetKey: string }) {
  return (
    <Banner
      tone="info"
      live="status"
      title="Claude 잡을 만들었습니다 — 내 Claude Code 에서 워크플로를 돌려야 나아갑니다."
      detail={
        <>
          이 잡에 동의한 내 PAT 로 게이트웨이에 붙은 Claude Code 에서 워크플로 <code>{EXTERNAL_WORKFLOW}</code> 를 인자{" "}
          <code>{JSON.stringify({ targetKey })}</code> 로 돌리세요. 돌지 않으면 잡이 기다림 한도 뒤 보류(external_worker)로
          멈춥니다 — 워크플로를 다시 돌린 뒤 '재개' 를 누르면 이어 돕니다(차감 없음).
        </>
      }
    />
  );
}

/** 진행판 잡 줄의 판단 LLM — Claude 잡이면 배지 · 동의 기록 · 외부 응답이 아니었던 수 · 워크플로 안내. */
function JobLlm({ job }: { job: NonNullable<CoverageJob> }) {
  if (job.llm !== "claude") return <LlmBadge llm={job.llm} />;
  const consent = job.consent_external ?? {};
  const live = job.state === "queued" || job.state === "running" || job.state === "paused";
  return (
    <span className="flex flex-col gap-1">
      <span className="flex flex-wrap items-center gap-2">
        <LlmBadge llm={job.llm} />
        <span className="text-xs text-muted-foreground">
          반출 동의 {consent.by ?? "기록 없음"}
          {consent.at ? ` · ${fmtEpoch(consent.at)}` : ""}
          {consent.source ? ` · ${CONSENT_SOURCE_LABEL[consent.source] ?? consent.source}` : ""}
        </span>
        {job.llm_mismatch ? (
          <Badge tone="warn" title="Claude 잡인데 외부 응답자 답이 아니었던 호출 · 패널 수(llm_mismatch)">
            외부 응답 아님 {job.llm_mismatch}
          </Badge>
        ) : null}
      </span>
      {live ? (
        <span className="text-xs text-muted-foreground">
          잡 주인의 Claude Code 에서 워크플로 <code>{EXTERNAL_WORKFLOW}</code> 가 돌아야 나아갑니다.
          {job.state === "paused" ? " 멈췄다면 워크플로를 다시 돌린 뒤 '재개' 를 누르세요." : ""}
        </span>
      ) : null}
    </span>
  );
}

/** 잡 만들기 거절 — 아는 code 는 제목과 다음 걸음을 붙이고, 서버 글(고칠 곳까지 말한다)은 글자 그대로 보인다. */
function JobErrorBanner({ error, onUseGlm }: { error: unknown; onUseGlm: () => void }) {
  if (error === null || error === undefined) return null;
  const known = describeJobError(error);
  if (!known) return <ErrorBanner error={error} />;
  return (
    <Banner title={known.title} detail={isApiError(error) ? error.message : undefined}>
      {known.next === "settings" ? (
        <Link to="/settings" className="text-sm underline underline-offset-4">
          설정에서 PAT 등록
        </Link>
      ) : null}
      {known.next === "use_glm" ? (
        <Button type="button" variant="outline" size="sm" onClick={onUseGlm}>
          GLM 으로 고르기
        </Button>
      ) : null}
    </Banner>
  );
}

function PanelRunner({
  targetKey,
  coverage,
  onChanged,
  creatable = true,
}: {
  targetKey: string;
  coverage: Coverage | null;
  onChanged: () => void;
  /** 카드 대조 대상은 Tier 패널 잡을 세우지 않는다(422 flow_mismatch) — 만들기 칸을 두지 않고 남은 패널 잡의 줄 · 조작만 보인다. */
  creatable?: boolean;
}) {
  const [tier, setTier] = useState<Tier>("B");
  const [concurrency, setConcurrency] = useState(1);
  const [modifiers, setModifiers] = useState("");
  const [memo, setMemo] = useState("");
  const [consent, setConsent] = useState(false);
  const [llm, setLlm] = useState<JudgeLlm>("glm");
  const [externalConsent, setExternalConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState<TargetJobCreated | null>(null);
  /** 취소 확인을 연 잡 — 그 잡이 지금 줄의 잡일 때만 확인 줄을 보인다. */
  const [cancelFor, setCancelFor] = useState<string | null>(null);

  const job = coverage?.job ?? null;
  const needsConsent = tier === "C";
  const form: PanelJobForm = { tier, concurrency, modifiers, memo, tierConsent: consent, llm, externalConsent };
  const ready = panelJobReady(form);

  function chooseLlm(next: JudgeLlm) {
    setLlm(next);
    // 동의는 고를 때마다 새로 받는다 — GLM 으로 돌렸다가 다시 Claude 를 고르면 다시 체크해야 한다.
    setExternalConsent(false);
  }

  async function start() {
    if (!ready) return;
    setBusy(true);
    setError(null);
    setCreated(null);
    try {
      const out = await riskApi.createTargetJob(targetKey, panelJobBody(form));
      setCreated(out);
      // 다음 잡은 다시 동의받는다 — 체크를 남겨 두면 다음 잡에 미리 체크된 동의가 된다. Tier C 승인도 본문의 consent 로 가므로 같다
      // (웹 REST 는 부를 때마다 새 잡을 세운다 — 두 번째 '시작' 이 승인 없이 가장 비싼 티어 잡을 하나 더 세웠다).
      setExternalConsent(false);
      setConsent(false);
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
      <JobErrorBanner
        error={error}
        onUseGlm={() => {
          // GLM 으로 바꾸면 그 거절(Claude 길이 닫힘)은 더 맞지 않는다 — 배너도 걷는다.
          chooseLlm("glm");
          setError(null);
        }}
      />
      {job ? (
        <KeyValueTable
          rows={[
            { label: "잡 id", hint: "job_id", value: <code>{job.id}</code> },
            { label: "티어", hint: "tier", value: job.tier },
            { label: "상태", hint: "state", value: <JobStateBadge value={job.state} /> },
            { label: "판단 LLM", hint: "llm", value: <JobLlm job={job} /> },
            { label: "멈춘 까닭", hint: "pause_reason", value: job.pause_reason ?? <Unknown /> },
            { label: "도는 패널", hint: "signal", value: <JobSignalLine job={job} /> },
            {
              label: "진행",
              hint: "panels_done / panels_total",
              value: `${job.panels_done} / ${job.panels_total} 패널`,
            },
            { label: "오류", hint: "error", value: job.error ?? <Unknown /> },
          ]}
        />
      ) : (
        <p className="text-sm text-muted-foreground">진행 중인 배치 잡이 없습니다.</p>
      )}
      {creatable ? (
      <>
      <FormGrid>
        <FormField label="티어" hint="tier">
          <Select
            value={tier}
            onChange={(e) => {
              setTier(e.target.value as Tier);
              // 승인은 고른 그 티어에 준 것이다 — 티어를 바꾸면 다시 받는다.
              setConsent(false);
            }}
          >
            {TIERS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="동시 실행" hint="concurrency ≤2">
          <Input
            type="number"
            min={1}
            max={2}
            value={concurrency}
            onChange={(e) => setConcurrency(Math.min(2, Math.max(1, Number(e.target.value) || 1)))}
          />
        </FormField>
        <FormField label="수정자" hint="modifiers · 쉼표 구분">
          <Input value={modifiers} onChange={(e) => setModifiers(e.target.value)} />
        </FormField>
        <FormField label="메모" hint="user_memo">
          <Input value={memo} onChange={(e) => setMemo(e.target.value)} />
        </FormField>
      </FormGrid>
      <LlmChoice llm={llm} consent={externalConsent} onLlm={chooseLlm} onConsent={setExternalConsent} />
      {needsConsent ? (
        <label className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>Tier C 는 명시 승인이 필요합니다.</span>
        </label>
      ) : null}
      </>
      ) : (
        <p className="m-0 mt-3 text-sm text-muted-foreground">
          카드 대조 대상은 Tier 패널 잡을 세우지 않습니다(flow_mismatch) — 검토 잡은 위 '검토 잡 만들기' 에서 시작합니다. 아래는 방식을
          바꾸기 전에 선 패널 잡입니다.
        </p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {creatable ? (
          <Button type="button" onClick={start} disabled={busy || !ready}>
            시작
          </Button>
        ) : null}
        <Button type="button" variant="outline" onClick={() => control("pause")} disabled={busy || !job}>
          일시정지
        </Button>
        <Button type="button" variant="outline" onClick={() => control("resume")} disabled={busy || !job}>
          재개
        </Button>
        <Button type="button" variant="outline" onClick={() => job && setCancelFor(job.id)} disabled={busy || !job}>
          취소…
        </Button>
        {creatable && llm === "claude" && !externalConsent ? (
          <span className="text-sm text-muted-foreground">반출 동의에 체크해야 시작할 수 있습니다.</span>
        ) : null}
      </div>
      {job && cancelFor === job.id ? (
        <div className="mt-3">
          <JobCancelConfirm
            what="패널 잡"
            jobId={job.id}
            busy={busy}
            onConfirm={() => {
              setCancelFor(null);
              void control("cancel");
            }}
            onClose={() => setCancelFor(null)}
          />
        </div>
      ) : null}
      {created ? (
        <div className="mt-3 flex flex-col gap-2">
          <p className="m-0 text-sm text-muted-foreground">
            패널 {created.panels_planned}개 · LLM 호출 추정 {created.llm_calls_estimate.low}~{created.llm_calls_estimate.high}회
          </p>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">러너 자격</span>
            <StatusBadge value={created.credential} />
            <span className="text-muted-foreground">{CREDENTIAL_LABEL[created.credential] ?? ""}</span>
            {created.credential_email ? <Mono>{created.credential_email}</Mono> : null}
          </div>
          {created.credential_note ? <p className="m-0 text-sm text-muted-foreground">{created.credential_note}</p> : null}
          {created.user_memo_cut ? (
            <p className="m-0 text-sm text-muted-foreground">
              메모가 길어 좌석은 앞 {created.user_memo_cut.kept}자만 받습니다(원문 {created.user_memo_cut.chars}자).
            </p>
          ) : null}
          {created.llm === "claude" ? <ClaudeWorkflowGuide targetKey={targetKey} /> : null}
        </div>
      ) : null}
    </>
  );
}

function PanelsCard({ targetKey }: { targetKey: string }) {
  const panels = useAsync((signal) => riskApi.getPanels(targetKey, undefined, { signal }), [targetKey]);
  const [openPanel, setOpenPanel] = useState<string | null>(null);

  const rows = panels.data?.panels ?? [];
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
    { key: "tier", header: "tier", cell: (p) => p.tier ?? "—", nowrap: true },
    {
      key: "kind",
      header: "종류",
      hint: "kind · issue_id",
      nowrap: true,
      // 쟁점 패널(kind issue · tier I)은 그 쟁점 id 를 단다 — 쟁점 탭의 행과 잇는다(재설계 M3 S3-10).
      cell: (p) =>
        p.kind === "issue" ? (
          <span className="flex flex-col gap-0.5">
            <Badge tone="info">쟁점 패널</Badge>
            {p.issue_id ? <code className="text-xs">{p.issue_id}</code> : null}
          </span>
        ) : (
          <span className="text-muted-foreground">Tier 패널</span>
        ),
    },
    { key: "engine", header: "engine", cell: (p) => <StatusBadge value={p.engine} />, nowrap: true },
    // call_path 는 패널 줄이 아니라 품질 칸에 있다(runner 의 품질 계산 — 끝나기 전 패널은 없다).
    { key: "path", header: "call_path", cell: (p) => p.quality.call_path ?? <Unknown />, nowrap: true },
    { key: "mode", header: "tool_mode", cell: (p) => p.tool_mode, nowrap: true },
    { key: "status", header: "status", cell: (p) => <PanelStatusBadge value={p.status} />, nowrap: true },
    { key: "model", header: "model", cell: (p) => p.model?.model ?? "unknown", nowrap: true },
    {
      key: "tools",
      header: "도구 사용",
      hint: "tool_use_rate",
      align: "right",
      nowrap: true,
      // 서버는 좌석 중 도구를 쓴 비율을 준다. 재지 못했으면(끝나기 전 · evidence_only) 칸이 없거나 null 이다 — 0 으로 바꿔 읽지 않는다.
      cell: (p) =>
        p.quality.tool_use_rate === null || p.quality.tool_use_rate === undefined ? (
          <span className="text-muted-foreground" title="도구 사용률 기록 없음(끝나기 전 · evidence_only).">
            기록 없음
          </span>
        ) : (
          fmtPct(p.quality.tool_use_rate * 100)
        ),
    },
    {
      key: "quality",
      header: "quality.flags",
      cell: (p) => (
        <span className="inline-flex flex-wrap items-center gap-1">
          {(p.quality.flags ?? []).map((f) => (
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
      // 귀속률 null 은 '0 귀속' 이 아니라 '재지 않았다' 다.
      cell: (p) =>
        p.quality.attribution_rate === null || p.quality.attribution_rate === undefined ? (
          <Unknown />
        ) : (
          fmtNum(p.quality.attribution_rate, 2)
        ),
    },
    { key: "seats", header: "좌석", cell: (p) => String(p.seats.length), align: "right", nowrap: true },
    { key: "started", header: "시작", cell: (p) => fmtEpoch(p.started_at), nowrap: true },
    {
      key: "links",
      header: "기록",
      nowrap: true,
      cell: (p) => (
        <span className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setOpenPanel((cur) => (cur === p.id ? null : p.id))}
          >
            기록 열기
          </Button>
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
          <DataTable columns={columns} rows={rows} rowKey={(p) => p.id} selectedKey={openPanel} empty="패널이 없습니다." />
          <h3 className="m-0 mt-4 text-sm text-muted-foreground">모델 혼합</h3>
          <p className="text-sm text-muted-foreground">
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
          <p className="text-sm text-muted-foreground">
            strong 비율은 좌석 단위 서버 계산값이라 위 진행판 열에 있는 값만 봅니다 — 이 표는 세지 않습니다.
          </p>
          {openPanel ? <PanelTranscript panelId={openPanel} /> : null}
        </>
      ) : null}
    </SectionCard>
  );
}

/** 통합 보고서 — 레벨 상승마다 코드가 RA `deliberation` 템플릿으로 조립한다(§6.9). 조회 경로는 아직 없다. */
function ConsolidatedReportCard({
  level,
  summary,
  resynced,
}: {
  level: string | null;
  /** 진행판이 늘 싣는 반영 요약 — 재동기를 누르기 전에도 그 글(message)을 보인다. */
  summary: ExternalSync | null;
  /** 재동기를 누른 뒤의 채널 상태(있으면 상태는 이것이 앞선다). */
  resynced: ResyncQueued | null;
}) {
  const shown = resynced ?? summary;
  const channel = (key: "ra" | "adh") =>
    shown ? (
      <span className="flex flex-col gap-0.5">
        <span>
          <StatusBadge value={shown[key].state} />
        </span>
        {summary ? <span className="text-xs text-muted-foreground">{summary[key].message}</span> : null}
        {resynced?.[key].last_error ? (
          <span className="text-xs text-muted-foreground">{resynced[key].last_error}</span>
        ) : null}
      </span>
    ) : (
      <Unknown>진행판을 읽는 중입니다.</Unknown>
    );
  return (
    <SectionCard
      title="통합 보고서"
      subtitle="레벨이 오를 때마다 v1(C1)·v2(C2)·v3(C3) 이 ReportArchive 에 쌓입니다."
      actions={<ExternalSyncBadge sync={shown} />}
    >
      <KeyValueTable
        rows={[
          { label: "현재 레벨", hint: "level", value: level ? <LevelBadge value={level} /> : <Unknown /> },
          { label: "RA 반영", hint: "external_sync.ra", value: channel("ra") },
          { label: "AIDataHub 반영", hint: "external_sync.adh", value: channel("adh") },
        ]}
      />
      <NotReadyBlock what="통합 보고서 링크(v1/v2/v3)" />
      <p className="text-sm text-muted-foreground">
        패널별 RA 보고서 id 는 위 패널 표의 '기록' 칸에 있습니다. RA 반영이 unavailable 이어도 완결 레벨은 오릅니다.
      </p>
    </SectionCard>
  );
}

/**
 * 패널마다 1건인 `brief_token` — L2 오케스트레이터(`hwax-risk-review`)가 MCP `risk_get_brief` 에
 * 그대로 넘기는 유일한 열쇠다(§8.2.5). 이 값 없이는 게이트웨이 경유 호출이 열리지 않는다.
 * 토큰은 발급 때만 원문이 오고 앱은 해시만 저장하므로 이 화면을 떠나면 다시 볼 수 없다.
 */
function BriefTokens({ panels }: { panels: BriefPanel[] }) {
  const [copied, setCopied] = useState<string | null>(null);
  const withToken = panels.filter((p) => p.brief_token);

  if (withToken.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        브리프 토큰이 없습니다 — 편성된 패널이 없거나 이 경로가 토큰을 발급하지 않았습니다.
      </p>
    );
  }

  async function copy(panelId: string, token: string) {
    try {
      await navigator.clipboard.writeText(token);
      setCopied(panelId);
    } catch {
      // 클립보드가 막힌 환경(비보안 오리진 등) — 값을 직접 고를 수 있게 노출만 한다.
      setCopied(null);
      window.prompt("브리프 토큰(복사하세요)", token);
    }
  }

  return (
    <div className="mt-3 flex flex-col gap-2">
      <h3 className="m-0 text-sm text-muted-foreground">브리프 토큰</h3>
      <p className="m-0 text-sm text-muted-foreground">
        L2 워크플로 인자 <code>briefToken</code> 에 넣습니다. 발급 때만 원문이 오므로 이 화면을 떠나면
        다시 볼 수 없습니다(앱은 해시만 저장합니다).
      </p>
      <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
        {withToken.map((panel) => (
          <li key={panel.panel_id}>
            <span className="flex flex-wrap items-center gap-2">
              <code>{panel.panel_id}</code>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => copy(panel.panel_id, panel.brief_token as string)}
              >
                토큰 복사
              </Button>
              {copied === panel.panel_id ? <Badge tone="ok">복사됨</Badge> : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}


/**
 * `active` 가 왜 필요한가. `GET /targets/{key}/brief` 는 **읽기가 아니다** — 서버가 그 자리에서
 * `issue_brief_token` 으로 패널마다 새 토큰을 발급하고 `brief_token_hash` 를 덮어쓴다
 * (routes.py `get_brief` → `issue_brief_token`). 그래서 이 호출이 한 번 더 나갈 때마다 사용자가
 * 이미 복사해 둔 토큰이 조용히 무효가 된다.
 *
 * 탭을 `TabPanel` 로 바꿔 재마운트는 막았지만 그것만으로는 모자랐다 — 마운트가 유지되니
 * **타깃 화면에 들어가기만 해도** 브리프 탭을 한 번도 안 열고 토큰이 발급됐다(띄워 보고 잡았다).
 * 그 탭을 실제로 보고 있을 때만 부른다.
 */
function RecallPreview({ targetKey, active }: { targetKey: string; active: boolean }) {
  const [tier, setTier] = useState<string>("");
  const brief = useAsync(
    (signal) => riskApi.getBrief(targetKey, tier === "" ? undefined : tier, { signal }),
    [targetKey, tier],
    active,
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
        <Select className="w-auto min-w-[9rem]" aria-label="tier 걸러내기" value={tier} onChange={(e) => setTier(e.target.value)}>
          <option value="">tier 전체</option>
          {TIERS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </Select>
      }
    >
      <ErrorBanner error={brief.error} onRetry={brief.reload} />
      {brief.loading && !brief.data ? <LoadingBlock /> : null}
      {brief.data ? (
        <>
          <p className="text-sm text-muted-foreground">
            패널 {brief.data.panels.length}개 · {brief.data.budget.bytes} bytes · 잘린 항목 {brief.data.budget.dropped}
          </p>
          <BriefTokens panels={brief.data.panels} />
          {slots.length === 0 ? <EmptyBlock title="근거 슬롯이 비어 있습니다." /> : null}
          {slots.map(([slot, items]) => (
            <div key={slot} className="mt-3 flex flex-col gap-2">
              <h3 className="m-0 text-sm text-muted-foreground">{slot}</h3>
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

/**
 * 대상이 바뀌면 화면 상태(탭 · 셀 고르기 · 폼 · 등록부 거름)를 처음부터 — 같은 라우트라 컴포넌트가 다시 마운트되지 않아 앞 대상에서 고른
 * 셀 · 탭이 다음 대상으로 넘어갔다(고른 셀 열쇠는 대상마다 다르다). 대상 열쇠로 다시 마운트한다.
 */
export default function TargetPage() {
  const { key } = useParams<{ key: string }>();
  return <TargetView key={key ?? ""} targetKey={key ?? ""} />;
}

function TargetView({ targetKey }: { targetKey: string }) {
  const coverage = useAsync(
    (signal) => riskApi.getCoverage(targetKey, { signal }),
    [targetKey],
    targetKey !== "",
  );
  const flow = coverage.data?.flow ?? null;
  const cells = flow === "cells";
  // 등록부 거름 가운데 서버 쿼리(주의 등급 · 단위 · 패널만 본 비교 보기). 방식을 안 뒤에 처음 값을 정한다 — 카드 대조 대상은 주의 A · B
  // 가 기본이다(요청서 7절). 헤더의 verdict_final 과 등록부 카드가 같은 응답을 쓴다(판정 칸은 거름과 상관없다).
  const [registryQuery, setRegistryQuery] = useState<RegistryQuery | null>(null);
  const [queryFlow, setQueryFlow] = useState<string | null>(null);
  if (flow !== null && queryFlow !== `${targetKey}|${flow}`) {
    setQueryFlow(`${targetKey}|${flow}`);
    setRegistryQuery(flow === "cells" ? { attention: "A,B" } : {});
  }
  const registry = useAsync(
    (signal) => riskApi.getRegistry(targetKey, registryQuery ?? {}, { signal }),
    [targetKey, JSON.stringify(registryQuery)],
    targetKey !== "" && registryQuery !== null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // 재동기 응답(채널마다 op 목록까지) — 누르기 전에는 진행판의 반영 요약(coverage.external_sync)을 쓴다.
  const [sync, setSync] = useState<ResyncQueued | null>(null);
  const [rosterNote, setRosterNote] = useState<string | null>(null);
  const [tab, setTab] = useState<TargetTab>("coverage");

  const job = coverage.data?.job ?? null;
  const polling = isPolling(coverage.data);
  useInterval(coverage.reload, polling ? POLL_MS : null);

  const [kind, refId] = useMemo(() => {
    const idx = targetKey.indexOf(":");
    return idx === -1 ? [targetKey, ""] : [targetKey.slice(0, idx), targetKey.slice(idx + 1)];
  }, [targetKey]);

  /** 진행판과 등록부를 같이 다시 읽는다 — 처분 · 확인 · 쟁점 결정이 표기 · 등록부를 바꾼다. */
  function reloadAll() {
    coverage.reload();
    registry.reload();
  }

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

  const review = coverage.data?.review ?? null;
  const deferred = coverage.data?.by_status.deferred ?? 0;
  const tabs: Array<{ tab: TargetTab; label: string; count?: number | null }> = [
    { tab: "coverage", label: "진행판", count: coverage.data ? Object.keys(coverage.data.by_domain).length : null },
    ...(cells
      ? ([
          { tab: "cells", label: "셀 격자", count: review ? review.cells.total : null },
          { tab: "experts", label: "전문가", count: review ? review.experts.total : null },
          { tab: "issues", label: "쟁점" },
          { tab: "closure", label: "완결" },
        ] as Array<{ tab: TargetTab; label: string; count?: number | null }>)
      : []),
    { tab: "panels", label: "패널" },
    { tab: "registry", label: "등록부", count: registry.data ? registry.data.rows.length : null },
    { tab: "report", label: "보고서" },
    { tab: "brief", label: "브리프" },
    { tab: "quality", label: "품질" },
  ];

  return (
    <>
      <PageHeader
        // 과제로 돌아가는 링크는 아직 못 만든다 — 서버 응답에 과제 id 가 없다(아래 NotReadyBlock 과 같은 공백).
        // 그래서 상위 화면은 홈의 타깃 목록이다.
        crumb={
          <Link to="/" className="inline-flex items-center gap-1 underline-offset-4 hover:underline">
            <ChevronLeft className="size-3.5" aria-hidden="true" />
            타깃 목록
          </Link>
        }
        title={`${KIND_LABEL[kind] ?? kind} 심사`}
        subtitle={
          <span className="flex flex-wrap items-center gap-x-2">
            <Mono>{targetKey}</Mono>
            {coverage.data ? <span>좌석 {coverage.data.roster_size}석</span> : null}
            {flow ? <span>{cells ? "카드 대조(cells)" : "패널(panels)"}</span> : null}
          </span>
        }
        actions={
          <>
            {coverage.data ? <UnseatedBadge n={coverage.data.unseated_n} /> : null}
            <ExternalSyncBadge sync={sync ?? coverage.data?.external_sync ?? null} />
            <Button type="button" variant="outline" onClick={resync} disabled={busy}>
              <RefreshCw className="size-4" aria-hidden="true" />
              재동기
            </Button>
            <Button type="button" variant="outline" onClick={refreshRoster} disabled={busy}>
              <Users className="size-4" aria-hidden="true" />
              로스터 갱신
            </Button>
          </>
        }
      />

      {/*
       * 요약 먼저 — 예전에는 이 카드가 `kind`·`ref_id` 로 시작하고 verdict 가 일곱 번째 줄이었다.
       * 이 화면에서 사람이 가장 먼저 알아야 할 것은 **"이 타깃을 지금 닫을 수 있나"** 이고 그 답은
       * verdict 와 완결 레벨이다. 그래서 둘을 맨 위로 올리고 신원(kind·ref_id)은 아래로 내렸다 —
       * 지운 줄은 없다. 집계 후보는 아래 '판정 확정' 카드(등록부 탭)에 상세가 있지만, 탭에 들어가야
       * 보이면 '늘 보여야 하는 판정' 이 숨으므로 배지 한 칸만 여기 둔다.
       */}
      <SectionCard title="판정" subtitle="이 타깃을 지금 닫을 수 있는지입니다. 확정은 사람이 하고 후보는 집계입니다.">
        <ErrorBanner error={error} />
        <ErrorBanner error={coverage.error} onRetry={coverage.reload} />
        {rosterNote ? <p className="text-sm text-muted-foreground">{rosterNote}</p> : null}
        {coverage.loading && !coverage.data ? <LoadingBlock /> : null}
        <KeyValueTable
          rows={[
            {
              label: "확정 판정",
              hint: "verdict_final",
              value: registry.data ? (
                <VerdictBadge value={registry.data.verdict_final ?? "undetermined"} />
              ) : (
                <Unknown>등록부를 읽는 중입니다.</Unknown>
              ),
            },
            {
              label: "집계 후보",
              hint: "verdict_candidate",
              value: registry.data?.verdict_candidate ? (
                <VerdictBadge value={registry.data.verdict_candidate.verdict} />
              ) : (
                <Unknown>후보가 아직 없습니다.</Unknown>
              ),
            },
            { label: "완결 레벨", hint: "level", value: coverage.data ? <LevelBadge value={coverage.data.level} /> : <Unknown /> },
            {
              label: "닫기 레벨",
              hint: "close_level",
              value: coverage.data ? <LevelBadge value={coverage.data.close_level} /> : <Unknown />,
            },
            { label: "편성 좌석", hint: "roster_size", value: coverage.data ? String(coverage.data.roster_size) : <Unknown /> },
            { label: "심사 대상", hint: "kind", value: KIND_LABEL[kind] ?? kind },
            {
              label: "대상 id",
              hint: "ref_id",
              value:
                kind === "snap" && refId ? (
                  <code>{refId}</code>
                ) : refId ? (
                  <Link to={`/compare?diff=${encodeURIComponent(refId)}`}>{refId}</Link>
                ) : (
                  <Unknown />
                ),
            },
            {
              label: "외부 반영",
              hint: "external_sync",
              value:
                sync ?? coverage.data?.external_sync ? (
                  <ExternalSyncBadge sync={sync ?? coverage.data?.external_sync ?? null} />
                ) : (
                  <Unknown>진행판을 읽는 중입니다.</Unknown>
                ),
            },
          ]}
        />
        {cells && coverage.data ? (
          <CellsHead coverage={coverage.data} targetKey={targetKey} onChanged={reloadAll} onOpenTab={setTab} />
        ) : null}
        <NotReadyBlock what="ir_hash · 과제 링크 · superseded_by" />
      </SectionCard>

      <TabBar idPrefix="tgt" label="타깃 구역 탭" value={tab} onChange={setTab} tabs={tabs} />

      {/* 탭은 **보이는 것만** 바꾼다. 조건부 렌더로 쓰면 저장 전 폼(등록부 상태 변경·판정 메모)과
          실행 직후 경고(credential === "service")가 탭 전환만으로 날아가고, 브리프는 재진입마다
          brief_token 이 재발급돼 사용자가 복사해 둔 토큰이 무효가 된다. TabPanel 주석 참조. */}
      <TabPanel active={tab === "coverage"} tab="coverage" idPrefix="tgt">
        <SectionCard title="진행판" subtitle="행 = 도메인, 열 = 커버리지 상태. 행을 누르면 좌석 목록이 열립니다.">
          {coverage.loading && !coverage.data ? <LoadingBlock /> : null}
          {coverage.data ? (
            <CoverageHeatmap coverage={coverage.data} targetKey={targetKey} targetKind={kind} onChanged={coverage.reload} />
          ) : coverage.loading ? null : (
            <EmptyBlock title="커버리지가 아직 없습니다." hint="타깃이 편성되면 도메인별 좌석 상태가 여기 쌓입니다." />
          )}
          {/* 보류 풀기는 패널 대상의 길이다 — 카드 대조 대상은 검토 잡을 만들 때 범위 안 보류가 저절로 풀린다(요청서 3-6). */}
          {coverage.data && !cells ? <UndeferForm targetKey={targetKey} deferred={deferred} onChanged={reloadAll} /> : null}
        </SectionCard>

        {review ? <ReviewBoard review={review} targetKey={targetKey} onChanged={reloadAll} /> : null}

        <ReviewWorkers review={review} />

        {cells && review ? <ReviewJobFormCard targetKey={targetKey} review={review} onChanged={reloadAll} /> : null}

        {!cells || job ? (
          <SectionCard title="패널 실행" subtitle={polling ? "진행 중 — 5초마다 갱신합니다." : undefined}>
            <PanelRunner targetKey={targetKey} coverage={coverage.data} onChanged={coverage.reload} creatable={!cells} />
          </SectionCard>
        ) : null}
      </TabPanel>

      {cells ? (
        <>
          <TabPanel active={tab === "cells"} tab="cells" idPrefix="tgt">
            {review ? <CellGrid targetKey={targetKey} review={review} active={tab === "cells"} onChanged={reloadAll} /> : null}
          </TabPanel>
          <TabPanel active={tab === "experts"} tab="experts" idPrefix="tgt">
            {/* 열 때만 받는다 — 전문가 359명 목록을 진행판과 함께 늘 받지 않는다. */}
            {tab === "experts" ? <ExpertReports targetKey={targetKey} /> : null}
          </TabPanel>
          <TabPanel active={tab === "issues"} tab="issues" idPrefix="tgt">
            <IssuesCard targetKey={targetKey} active={tab === "issues"} onChanged={reloadAll} />
          </TabPanel>
          <TabPanel active={tab === "closure"} tab="closure" idPrefix="tgt">
            <ClosureCard
              targetKey={targetKey}
              active={tab === "closure"}
              onChanged={reloadAll}
              onOpenReport={() => setTab("report")}
            />
          </TabPanel>
        </>
      ) : null}

      <TabPanel active={tab === "panels"} tab="panels" idPrefix="tgt">
        <PanelsCard targetKey={targetKey} />
      </TabPanel>
      <TabPanel active={tab === "registry"} tab="registry" idPrefix="tgt">
        <RegistryCard
          targetKey={targetKey}
          registry={registry}
          query={registryQuery ?? {}}
          onQuery={setRegistryQuery}
          cells={cells}
        />
      </TabPanel>
      <TabPanel active={tab === "report"} tab="report" idPrefix="tgt">
        {cells ? (
          // 종합 보고서는 판이 바뀌면 처음 쪽부터 받으므로 볼 때만 그린다(확인 · 사슬이 판을 세운 뒤 다시 열면 새 판이다).
          tab === "report" ? <SynthReport targetKey={targetKey} stage={coverage.data?.stage ?? null} onChanged={reloadAll} /> : null
        ) : (
          <ConsolidatedReportCard
            level={coverage.data?.level ?? null}
            summary={coverage.data?.external_sync ?? null}
            resynced={sync}
          />
        )}
      </TabPanel>
      <TabPanel active={tab === "brief"} tab="brief" idPrefix="tgt">
        {cells ? (
          <SectionCard title="브리프(RecallPreview)">
            <EmptyBlock
              title="카드 대조 대상은 패널 브리프를 내지 않습니다."
              hint="검토 근거는 셀 격자 · 전문가 보고서에 있습니다(서버도 cells_flow_web_only 로 거절합니다)."
            />
          </SectionCard>
        ) : (
          // active 를 넘긴다 — 이 호출은 서버에서 토큰을 **발급**하므로 보고 있을 때만 나가야 한다.
          <RecallPreview targetKey={targetKey} active={tab === "brief"} />
        )}
      </TabPanel>
      <TabPanel active={tab === "quality"} tab="quality" idPrefix="tgt">
        <QualityCard />
      </TabPanel>
    </>
  );
}
