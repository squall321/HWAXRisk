// 쟁점 탭 — 제기 · 반대 분포와 쟁점 패널 결과를 한 줄로, 다시 토의 표기, 패널 발언, 상한 밖 · 끝난 쟁점의 올리기 · 건너뛰기(사유 필수 — 웹뿐), ledger_rev 로 쪽 잇기(포털 m3-frontend-request 4절)
import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { Badge } from "./Badge";
import { DataTable, KeyValueTable } from "./DataTable";
import type { Column } from "./DataTable";
import { PanelTranscript } from "./PanelTranscript";
import { ReviewErrorBanner } from "./ReviewErrorBanner";
import { SectionCard } from "./SectionCard";
import { ErrorBanner, LoadingBlock } from "./StateBlocks";
import { Banner, Button, FormField, Input, Mono, Select } from "../ui/primitives";
import {
  ISSUE_ROLE_LABEL,
  ISSUE_STATE_LABEL,
  ISSUE_STATE_TONE,
  ISSUE_TYPE_LABEL,
  STATE_REASON_LABEL,
  appendPage,
  byRank,
  distributionText,
  issueActions,
  issueLine,
  issueReasonProblem,
  labelOf,
} from "../lib/issueView";
import { fmtEpoch, fmtJson } from "../format";
import type { IssueActed, IssueReargue, IssueRow } from "../types";

const LIMIT = 100;
const STATES = ["queued", "planned", "running", "resolved", "inconclusive", "untried_cap", "withdrawn", "skipped"];

/**
 * 다시 토의 표기 — 칸은 표기가 선 길마다 다르다(types IssueReargue). 근거가 바뀐 표기(basis_hash 가 있다)는 제기 · 반대의 들고 남과
 * 시각 · 회차를, 사람이 다시 올린 쟁점의 새 패널이 결정을 못 낸 표기는 그 패널과 까닭만 보인다 — 없는 칸을 읽지 않는다.
 */
export function ReargueNote({ reargue: r }: { reargue: IssueReargue }) {
  const moved = [
    r.raisers_added?.length ? `제기 + ${r.raisers_added.join(", ")}` : null,
    r.raisers_removed?.length ? `제기 − ${r.raisers_removed.join(", ")}` : null,
    r.opposers_added?.length ? `반대 + ${r.opposers_added.join(", ")}` : null,
    r.opposers_removed?.length ? `반대 − ${r.opposers_removed.join(", ")}` : null,
  ].filter(Boolean);
  const changes = moved.length > 0 ? moved.join(" · ") : r.basis_hash ? "제기 · 반대는 그대로이고 주장값이 바뀌었습니다." : null;
  const failed = r.new_panel_failed;
  return (
    <div className="rounded-md border-l-[3px] border-warn bg-warn/10 p-3 text-sm">
      <p className="m-0 font-semibold">{r.label}</p>
      {changes ? <p className="m-0">{changes}</p> : null}
      <p className="m-0 text-xs text-muted-foreground">
        {r.at !== undefined ? `${fmtEpoch(r.at)} · ` : ""}
        {r.round !== undefined ? `회차 ${r.round} · ` : ""}
        새 패널이 정할 때까지 옛 판정이 보입니다.
        {failed
          ? ` 새 패널(${failed.panel_id})이 결정을 못 냈습니다 — ${labelOf(STATE_REASON_LABEL, failed.reason)}(${failed.reason}) · ${fmtEpoch(failed.at)}.`
          : ""}
      </p>
    </div>
  );
}

/** 쟁점 한 행을 펼친 칸 — 시험이 서버 견본으로 그린다. */
export function IssueDetail({ row }: { row: IssueRow }) {
  const r = row.reargue;
  return (
    <div className="flex flex-col gap-2">
      <KeyValueTable
        rows={[
          { label: "닻 클러스터", hint: "anchor_cluster_key", value: <Mono>{row.anchor_cluster_key}</Mono> },
          { label: "단위", hint: "unit_id", value: row.unit_id ? <Mono>{row.unit_id}</Mono> : "—" },
          { label: "유형", hint: "types", value: row.types.map((t) => labelOf(ISSUE_TYPE_LABEL, t)).join(" · ") || "—" },
          {
            label: "제기 영역",
            hint: "distribution.raisers_by_domain",
            value: Object.entries(row.distribution.raisers_by_domain)
              .map(([d, n]) => `${d} ${n}`)
              .join(" · ") || "—",
          },
          { label: "심각도 분포", hint: "distribution.by_severity", value: distributionText(row.distribution.by_severity) ?? "—" },
          {
            label: "좌석",
            hint: "seats",
            value:
              row.seats.length === 0
                ? "—"
                : row.seats.map((s) => `${s.key ?? "?"}(${labelOf(ISSUE_ROLE_LABEL, s.issue_role)} · ${s.domain ?? "?"})`).join(" · "),
          },
          { label: "시도", hint: "attempts · charged · selected_round", value: `${row.attempts} · 내용 탓 ${row.charged} · 고른 회차 ${row.selected_round ?? "—"}` },
          {
            label: "결과 칸",
            hint: "outcome_json",
            // 결과가 있는데 칸이 비면 서버가 이 행에 싣지 않은 것이다(routes._issue_row_out 이 늘 null 을 싣는다 — 백엔드에 청했다).
            value: row.outcome_json ? (
              <code className="whitespace-pre-wrap">{fmtJson(row.outcome_json)}</code>
            ) : row.outcome ? (
              <span className="text-muted-foreground">서버가 이 행에 결과 칸을 싣지 않았습니다 — 결과 낱말만 있습니다.</span>
            ) : (
              "—"
            ),
          },
        ]}
      />
      {r ? <ReargueNote reargue={r} /> : null}
      {row.panel_id ? <PanelTranscript panelId={row.panel_id} /> : null}
    </div>
  );
}

export function IssuesCard({
  targetKey,
  active,
  onChanged,
}: {
  targetKey: string;
  /** 탭을 보고 있는가 — 볼 때만(볼 때마다) 첫 쪽을 받는다. 적던 사유는 탭을 바꿔도 남는다. */
  active: boolean;
  onChanged: () => void;
}) {
  const [state, setState] = useState("");
  const [pClass, setPClass] = useState("");
  const [type, setType] = useState("");
  const [sortRank, setSortRank] = useState(true);
  const [tick, setTick] = useState(0);
  const [extra, setExtra] = useState<{ rev: string; rows: IssueRow[]; next?: number } | null>(null);
  const [more, setMore] = useState<unknown>(null);
  const [restarted, setRestarted] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [acting, setActing] = useState<{ row: IssueRow; action: "queue" | "skip" } | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<IssueActed | null>(null);

  const query = { state: state || undefined, p_class: pClass || undefined, type: type || undefined, limit: LIMIT, offset: 0 };
  const first = useAsync((signal) => riskApi.getIssues(targetKey, query, { signal }), [targetKey, state, pClass, type, tick], active);
  useEffect(() => setExtra(null), [first.data]);

  const rows = first.data ? [...first.data.rows, ...(extra?.rows ?? [])] : [];
  const shown = sortRank ? byRank(rows) : rows;
  const next = extra ? extra.next : first.data?.next_offset;
  const selectedRow = rows.find((r) => r.issue_id === selected) ?? null;
  const problem = issueReasonProblem(reason);

  async function loadMore() {
    if (!first.data || next === undefined) return;
    setMore(null);
    try {
      const page = await riskApi.getIssues(targetKey, { ...query, offset: next });
      const joined = appendPage({ rev: first.data.ledger_rev, rows }, page);
      if (joined === null) {
        // 그사이 원장이 바뀌었다 — 쪽을 섞지 않고 처음부터 다시 받는다(요청서 0절).
        setRestarted(true);
        setTick((t) => t + 1);
        return;
      }
      setExtra({ rev: page.ledger_rev, rows: [...(extra?.rows ?? []), ...page.rows], next: page.next_offset });
    } catch (err) {
      setMore(err);
    }
  }

  async function act(event: React.FormEvent) {
    event.preventDefault();
    if (!acting || problem) return;
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const out = await riskApi.putIssue(acting.row.issue_id, { action: acting.action, reason: reason.trim() });
      setDone(out);
      setActing(null);
      setReason("");
      setRestarted(false);
      setTick((t) => t + 1);
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<IssueRow>[] = [
    { key: "rank", header: "순위", hint: "rank", cell: (r) => r.rank ?? "—", align: "right", nowrap: true },
    { key: "p", header: "등급", hint: "p_class", cell: (r) => <Badge tone={r.p_class === "P1" ? "bad" : r.p_class === "P2" ? "warn" : "muted"}>{r.p_class}</Badge>, nowrap: true },
    {
      key: "state",
      header: "상태",
      hint: "state · state_reason",
      nowrap: true,
      cell: (r) => (
        <span className="flex flex-col items-start gap-0.5">
          <Badge tone={ISSUE_STATE_TONE[r.state] ?? "neutral"} title={r.state}>
            {labelOf(ISSUE_STATE_LABEL, r.state)}
          </Badge>
          <span className="text-xs text-muted-foreground">
            <code>{r.state}</code>
            {r.state_reason ? ` · ${labelOf(STATE_REASON_LABEL, r.state_reason)}` : ""}
          </span>
        </span>
      ),
    },
    {
      key: "line",
      header: "제기 · 반대 → 결과",
      cell: (r) => (
        <span className="flex flex-col gap-0.5">
          <span>{issueLine(r)}</span>
          {r.reargue ? <strong>{r.reargue.label}</strong> : null}
          <span className="text-xs text-muted-foreground">{r.types.map((t) => labelOf(ISSUE_TYPE_LABEL, t)).join(" · ")}</span>
        </span>
      ),
    },
    {
      key: "panel",
      header: "패널",
      hint: "panel_id",
      nowrap: true,
      cell: (r) =>
        r.panel_id ? (
          <Button type="button" variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); setSelected(r.issue_id); }}>
            발언 보기
          </Button>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: "act",
      header: "사람의 결정",
      nowrap: true,
      cell: (r) => {
        const can = issueActions(r);
        return (
          <span className="flex flex-wrap items-center gap-1" title={can.inFlight ? "편성 · 도는 쟁점은 바꾸지 않습니다" : undefined}>
            {can.queue || can.inFlight ? (
              <Button type="button" variant="outline" size="sm" disabled={can.inFlight}
                      onClick={(e) => { e.stopPropagation(); setActing({ row: r, action: "queue" }); setReason(""); setError(null); }}>
                올리기…
              </Button>
            ) : null}
            {can.skip || can.inFlight ? (
              <Button type="button" variant="outline" size="sm" disabled={can.inFlight}
                      onClick={(e) => { e.stopPropagation(); setActing({ row: r, action: "skip" }); setReason(""); setError(null); }}>
                건너뛰기…
              </Button>
            ) : null}
          </span>
        );
      },
    },
  ];

  return (
    <SectionCard
      title="쟁점"
      subtitle="코드가 고른 쟁점(hold 가 가린 FAIL · 한 사람만 중대 이상 · 같은 줄의 OK 둘 이상)과 쟁점 패널 결과입니다. 올리기 · 건너뛰기는 웹에서만 됩니다."
      actions={
        <Button type="button" variant="outline" size="sm" onClick={() => { setRestarted(false); setTick((t) => t + 1); }}>
          <RefreshCw className="size-4" aria-hidden="true" />
          새로 읽기
        </Button>
      }
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select className="w-auto min-w-[9rem]" aria-label="쟁점 상태 거름" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="">상태 전체</option>
          {STATES.map((s) => (
            <option key={s} value={s}>
              {labelOf(ISSUE_STATE_LABEL, s)} ({s})
            </option>
          ))}
        </Select>
        <Select className="w-auto min-w-[7rem]" aria-label="쟁점 등급 거름" value={pClass} onChange={(e) => setPClass(e.target.value)}>
          <option value="">등급 전체</option>
          {["P1", "P2", "P3"].map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </Select>
        <Select className="w-auto min-w-[10rem]" aria-label="쟁점 유형 거름" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">유형 전체</option>
          {Object.keys(ISSUE_TYPE_LABEL).map((t) => (
            <option key={t} value={t}>
              {ISSUE_TYPE_LABEL[t]} ({t})
            </option>
          ))}
        </Select>
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={sortRank} onChange={(e) => setSortRank(e.target.checked)} />
          선정 순위대로
        </label>
      </div>
      {restarted ? <Banner tone="info" live="status" title="그사이 원장이 바뀌어 처음 쪽부터 다시 받았습니다." /> : null}
      {done ? (
        <Banner
          tone="info"
          live="status"
          title={done.state === "queued" ? `쟁점 ${done.issue_id} 을 다시 줄 세웠습니다.` : `쟁점 ${done.issue_id} 을 건너뛰었습니다 — 완결 잔여 '미토의 쟁점' 에 듭니다.`}
          detail={done.job_id ? `쟁점 잡 ${done.job_id} 이 집습니다.` : undefined}
        />
      ) : null}
      <ErrorBanner error={first.error} onRetry={first.reload} />
      <ErrorBanner error={more} />
      {first.loading && !first.data ? <LoadingBlock /> : null}
      {first.data ? (
        <>
          <p className="m-0 mb-2 text-sm text-muted-foreground">
            {first.data.total}건 가운데 {rows.length}건 · 쟁점 패널 상한 — 돌았거나 도는 {first.data.cap.run} · 기본 {first.data.cap.base} · P1
            하드 {first.data.cap.hard}
          </p>
          <DataTable
            columns={columns}
            rows={shown}
            rowKey={(r) => r.issue_id}
            selectedKey={selected}
            onRowClick={(r) => setSelected((cur) => (cur === r.issue_id ? null : r.issue_id))}
            empty="쟁점이 없습니다 — 검토가 마감 범위를 닫으면 코드가 고릅니다."
          />
          {next !== undefined ? (
            <Button type="button" variant="outline" size="sm" className="mt-2" onClick={loadMore}>
              더 받기
            </Button>
          ) : null}
        </>
      ) : null}
      {acting ? (
        <form className="mt-3 flex flex-col gap-2 rounded-md border border-border p-3" onSubmit={act}>
          <ReviewErrorBanner error={error} onReload={() => setTick((t) => t + 1)} />
          <p className="m-0 text-sm">
            쟁점 <Mono>{acting.row.issue_id}</Mono> 을{" "}
            {acting.action === "queue"
              ? "다시 줄 세웁니다 — 상한을 넘기는 사람의 결정이고 내용 탓 셈을 0 으로 돌립니다. 살아 있는 쟁점 잡이 없으면 잡을 세웁니다."
              : "건너뜁니다 — 완결 잔여 '미토의 쟁점' 에 듭니다."}{" "}
            사람의 결정은 다음 자동 고르기가 바꾸지 않습니다.
          </p>
          <FormField label="사유" hint="필수 · 300자 안" error={reason !== "" && problem ? problem : undefined}>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} aria-label="쟁점 결정 사유" />
          </FormField>
          <span className="flex flex-wrap items-center gap-2">
            <Button type="submit" size="sm" disabled={busy || problem !== null}>
              {acting.action === "queue" ? "올리기" : "건너뛰기"}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setActing(null)}>
              그만두기
            </Button>
          </span>
        </form>
      ) : null}
      {selectedRow ? (
        <div className="mt-4">
          <IssueDetail key={selectedRow.issue_id} row={selectedRow} />
        </div>
      ) : null}
    </SectionCard>
  );
}
