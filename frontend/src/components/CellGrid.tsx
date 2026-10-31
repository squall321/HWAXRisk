// 카드 대조 셀 격자와 처분 — 전문가 × 단위 칸의 상태(거름 · 입력 결손 표기), 거른 까닭 말풍선, 길 · 상태 거름, 고른 셀 · 이 잡의 실패 셀의 다시 · 넘김(포털 m3-frontend-request 3-2 ~ 3-4절)
import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { isApiError, riskApi } from "../api/risk.api";
import { estimateOf } from "../api/reviewErrors";
import { useAsync } from "../hooks/useAsync";
import { Badge, toneOf } from "./Badge";
import { KeyValueTable, TableScroll } from "./DataTable";
import { EstimateBlock } from "./ReviewJobForm";
import { ReviewErrorBanner } from "./ReviewErrorBanner";
import { SectionCard } from "./SectionCard";
import { EmptyBlock, ErrorBanner, LoadingBlock } from "./StateBlocks";
import { Banner, Button, FormField, Input, Mono, Select } from "../ui/primitives";
import { cn } from "../lib/cn";
import { CELL_STATES, cellStateLabel, disposeJobLine, hitsLine, reasonProblem } from "../lib/reviewView";
import { cellKey, cellMatrix, cellShortLabel, cellTitle, ROUTE_LABEL } from "../lib/cellView";
import { fmtEpoch } from "../format";
import type { CallsEstimate, CellState, CellsDisposed, CellsSelector, CoverageReview, ReviewCellRow } from "../types";

const PAGE = 500;
const ROUTES = ["review", "filtered", "audit", "noinput"] as const;

type Action = { kind: "retry" | "skip"; target: "selected" | "job_failed" };

/** 셀 하나의 자세한 칸 — 서버 글은 글자 그대로다. */
function CellDetail({ row }: { row: ReviewCellRow }) {
  return (
    <KeyValueTable
      rows={[
        { label: "셀", hint: "unit_id · agent_key", value: <span><Mono>{row.unit_id}</Mono> · <Mono>{row.agent_key}</Mono></span> },
        { label: "상태", hint: "state", value: `${cellStateLabel(row.state)} (${row.state})` },
        { label: "바탕", hint: "basis", value: row.basis ?? "—" },
        {
          label: "길",
          hint: "route · route_forced",
          value: `${row.route ?? "—"}${row.route_forced ? ` · 거르지 않은 까닭 ${row.route_forced}` : ""}`,
        },
        { label: "거른 까닭", hint: "filter_reason", value: row.filter_reason ?? "—" },
        {
          label: "판정",
          hint: "cards_judged / cards_expected",
          value: `${row.cards_judged ?? "모름"} / ${row.cards_expected ?? "모름"} · FAIL ${row.n_fail} · WARNING ${row.n_warning} · 보류 ${row.n_undetermined} · 카드 밖 ${row.n_offcard}${row.truncated === 1 ? " · 절단" : ""}`,
        },
        { label: "시도", hint: "tries · charged · reopened_n", value: `${row.tries} · 차감 ${row.charged} · 다시 연 횟수 ${row.reopened_n}` },
        { label: "오류", hint: "error_code · error", value: row.error_code ? `${row.error_code}${row.error ? ` — ${row.error}` : ""}` : "—" },
        {
          label: "사람의 처분",
          hint: "decided_by · decide_note",
          value:
            row.status_source === "human"
              ? `${row.decided_by ?? "?"} · ${fmtEpoch(row.decided_at)}${row.decide_note ? ` — ${row.decide_note}` : ""}`
              : "—",
        },
        { label: "잡", hint: "run_id", value: row.run_id ? <Mono>{row.run_id}</Mono> : "—" },
      ]}
    />
  );
}

export function CellGrid({
  targetKey,
  review,
  active,
  onChanged,
}: {
  targetKey: string;
  review: CoverageReview;
  /** 탭을 보고 있는가 — 볼 때만(볼 때마다) 칸을 받는다. 고른 셀 · 적던 사유는 탭을 바꿔도 남는다. */
  active: boolean;
  onChanged: () => void;
}) {
  const [agent, setAgent] = useState("");
  const [domain, setDomain] = useState("");
  const [unit, setUnit] = useState("");
  const [state, setState] = useState<"" | CellState>("");
  const [route, setRoute] = useState("");
  const [jobOnly, setJobOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [focus, setFocus] = useState<string | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [reason, setReason] = useState("");
  const [force, setForce] = useState(false);
  const [start, setStart] = useState(true);
  const [consent, setConsent] = useState(false);
  const [asked, setAsked] = useState<CallsEstimate | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<CellsDisposed | null>(null);

  const jobId = review.job?.id ?? null;
  const query = {
    agent_key: agent || undefined,
    domain: domain || undefined,
    unit_id: unit.trim() || undefined,
    state: state || undefined,
    route: route || undefined,
    job_id: jobOnly && jobId ? jobId : undefined,
    limit: PAGE,
    offset,
  };
  const cells = useAsync((signal) => riskApi.getCells(targetKey, query, { signal }), [targetKey, JSON.stringify(query)], active);
  const rows = cells.data?.rows ?? [];
  const matrix = useMemo(() => cellMatrix(rows), [rows]);
  const byKey = useMemo(() => new Map(rows.map((r) => [cellKey(r), r])), [rows]);
  const domains = useMemo(() => Array.from(new Set(review.order.map((r) => r.domain))).sort(), [review.order]);
  const focused = focus ? byKey.get(focus) ?? null : null;
  const needsReason = action?.kind === "skip" || force;
  const problem = reasonProblem(reason, needsReason);

  /** 거름을 바꾸면 쪽 · 고른 셀은 처음으로(다른 쪽의 셀을 고른 채 보내지 않는다). */
  function refilter<T>(set: (v: T) => void) {
    return (v: T) => {
      set(v);
      setOffset(0);
      setSelected(new Set());
      setFocus(null);
    };
  }

  function toggle(key: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function open(next: Action) {
    setAction(next);
    setReason("");
    setForce(false);
    setStart(true);
    setConsent(false);
    setAsked(null);
    setError(null);
    setResult(null);
  }

  function selector(): CellsSelector | null {
    if (!action) return null;
    if (action.target === "job_failed") return jobId ? { filter: { job_id: jobId, state: "failed" } } : null;
    const pairs = rows.filter((r) => selected.has(cellKey(r))).map((r) => [r.unit_id, r.agent_key] as [string, string]);
    return pairs.length > 0 ? { cells: pairs } : null;
  }

  // 동의는 422 consent_required 가 추정을 준 그 요청에만 선다 — 고른 셀(거름 · 쪽 · 체크) · 이 잡 · force · start 가 하나라도 바뀌면
  // 앞선 추정 · 동의를 걷는다. 전에는 셀 하나 · 1,600회에 체크한 동의가 force 와 검토함 셀 둘을 더한 요청에 consent:true 로 실렸다
  // (서버는 consent:true 를 새 추정 없이 받아들인다).
  const requestKey = JSON.stringify([action, selector(), force, start]);
  useEffect(() => {
    setAsked(null);
    setConsent(false);
  }, [requestKey]);

  async function send(withConsent: boolean) {
    const sel = selector();
    if (!action || !sel || problem) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const text = reason.trim();
      const out =
        action.kind === "skip"
          ? await riskApi.skipCells(targetKey, { ...sel, reason: text })
          : await riskApi.retryCells(targetKey, {
              ...sel,
              ...(text ? { reason: text } : {}),
              ...(force ? { force: true as const } : {}),
              ...(start ? {} : { start: false as const }),
              ...(withConsent && consent ? { consent: true as const } : {}),
            });
      setResult(out);
      setAction(null);
      setAsked(null);
      setConsent(false);
      setSelected(new Set());
      cells.reload();
      onChanged();
    } catch (err) {
      const estimate = estimateOf(err);
      if (estimate && isApiError(err) && err.code === "consent_required") {
        // 아무것도 바꾸기 전의 거절이다 — 그 셀만의 추정을 보이고 동의를 받아 다시 보낸다.
        setAsked(estimate);
        setConsent(false);
      } else {
        setError(err);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <SectionCard
      title="셀 격자"
      subtitle="전문가 × 단위 칸의 상태입니다. 칸을 누르면 자세히, 체크하면 다시 · 넘김에 고릅니다(이 쪽의 칸만)."
      actions={
        <Button type="button" variant="outline" size="sm" onClick={cells.reload}>
          <RefreshCw className="size-4" aria-hidden="true" />
          새로 읽기
        </Button>
      }
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground">길</span>
        <Button type="button" size="sm" variant={route === "" ? "default" : "outline"} onClick={() => refilter(setRoute)("")}>
          전체
        </Button>
        {ROUTES.map((r) => (
          <Button
            key={r}
            type="button"
            size="sm"
            variant={route === r ? "default" : "outline"}
            onClick={() => refilter(setRoute)(r)}
            title={`route=${r}`}
          >
            {ROUTE_LABEL[r]}
          </Button>
        ))}
        <span className="mx-1 h-5 w-px bg-border" aria-hidden="true" />
        <Button
          type="button"
          size="sm"
          variant={state === "failed" ? "default" : "outline"}
          onClick={() => refilter(setState)(state === "failed" ? "" : "failed")}
        >
          실패만
        </Button>
      </div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select className="w-auto min-w-[9rem]" aria-label="상태 거름" value={state} onChange={(e) => refilter(setState)(e.target.value as "" | CellState)}>
          <option value="">상태 전체</option>
          {CELL_STATES.map((s) => (
            <option key={s} value={s}>
              {cellStateLabel(s)} ({s})
            </option>
          ))}
        </Select>
        <Select className="w-auto min-w-[9rem]" aria-label="영역 거름" value={domain} onChange={(e) => refilter(setDomain)(e.target.value)}>
          <option value="">영역 전체</option>
          {domains.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </Select>
        <Select className="w-auto min-w-[12rem]" aria-label="전문가 거름" value={agent} onChange={(e) => refilter(setAgent)(e.target.value)}>
          <option value="">전문가 전체</option>
          {review.order.map((r) => (
            <option key={r.agent_key} value={r.agent_key}>
              {r.agent_key} · {r.domain} · {r.tier}
            </option>
          ))}
        </Select>
        <Input
          className="w-auto min-w-[10rem]"
          aria-label="단위 거름"
          placeholder="단위 id"
          value={unit}
          onChange={(e) => refilter(setUnit)(e.target.value)}
        />
        {jobId ? (
          <label className="flex items-center gap-1 text-sm">
            <input type="checkbox" checked={jobOnly} onChange={(e) => refilter(setJobOnly)(e.target.checked)} />
            가장 최근 검토 잡 범위만
          </label>
        ) : null}
      </div>
      <ErrorBanner error={cells.error} onRetry={cells.reload} />
      {cells.loading && !cells.data ? <LoadingBlock /> : null}
      {cells.data ? (
        <>
          <p className="m-0 mb-2 text-sm text-muted-foreground">
            {cells.data.total === 0
              ? "맞는 칸이 없습니다."
              : `${cells.data.total}칸 가운데 ${cells.data.offset + 1}~${cells.data.offset + rows.length} · 전문가 ${matrix.agents.length}명 × 단위 ${matrix.units.length}개`}
          </p>
          {rows.length === 0 ? (
            <EmptyBlock title="이 거름에 맞는 셀이 없습니다." />
          ) : (
            <TableScroll>
              <table className="border-collapse text-xs">
                <thead>
                  <tr className="border-b border-border">
                    <th scope="col" className="px-2 py-1 text-left font-medium text-muted-foreground">
                      전문가
                    </th>
                    {matrix.units.map((u) => (
                      <th key={u.unit_id} scope="col" className="px-1 py-1 text-center font-medium text-muted-foreground" title={u.unit_id}>
                        #{u.unit_seq}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {matrix.agents.map((a) => (
                    <tr key={a.agent_key} className="border-b border-border/60 last:border-0">
                      <th scope="row" className="whitespace-nowrap px-2 py-1 text-left font-normal">
                        <Mono>{a.agent_key}</Mono> <span className="text-muted-foreground">{a.domain}</span>
                      </th>
                      {matrix.units.map((u) => {
                        const row = byKey.get(cellKey({ unit_id: u.unit_id, agent_key: a.agent_key }));
                        if (!row) return <td key={u.unit_id} className="px-1 py-1 text-center text-muted-foreground">·</td>;
                        const key = cellKey(row);
                        return (
                          <td key={u.unit_id} className={cn("px-1 py-1 text-center", focus === key && "bg-accent")}>
                            <span className="inline-flex items-center gap-0.5">
                              <input
                                type="checkbox"
                                aria-label={`셀 고르기 ${row.unit_id} · ${row.agent_key}`}
                                checked={selected.has(key)}
                                onChange={() => toggle(key)}
                              />
                              <button
                                type="button"
                                className="rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                title={cellTitle(row)}
                                onClick={() => setFocus((cur) => (cur === key ? null : key))}
                              >
                                <Badge tone={toneOf(row.state === "na_irrelevant" ? "skipped" : row.state)}>{cellShortLabel(row)}</Badge>
                              </button>
                            </span>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - PAGE)); setSelected(new Set()); }}>
              앞 쪽
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={cells.data.next_offset === undefined}
              onClick={() => { setOffset(cells.data?.next_offset ?? offset); setSelected(new Set()); }}
            >
              다음 쪽
            </Button>
          </div>
        </>
      ) : null}
      {focused ? (
        <div className="mt-3">
          <CellDetail row={focused} />
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <span className="text-sm">고른 셀 {selected.size}개</span>
        <Button type="button" size="sm" variant="outline" disabled={selected.size === 0} onClick={() => open({ kind: "retry", target: "selected" })}>
          다시…
        </Button>
        <Button type="button" size="sm" variant="outline" disabled={selected.size === 0} onClick={() => open({ kind: "skip", target: "selected" })}>
          넘김…
        </Button>
        {jobId ? (
          <>
            <span className="mx-1 h-5 w-px bg-border" aria-hidden="true" />
            <span className="text-sm">이 잡({jobId.slice(0, 8)})의 실패 셀 전부</span>
            <Button type="button" size="sm" variant="outline" onClick={() => open({ kind: "retry", target: "job_failed" })}>
              다시…
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => open({ kind: "skip", target: "job_failed" })}>
              넘김…
            </Button>
          </>
        ) : null}
      </div>
      {result ? (
        <Banner
          tone="info"
          live="status"
          title={
            result.changed
              ? `${result.retried !== undefined ? `다시 연 셀 ${result.retried}` : `넘긴 셀 ${result.skipped ?? 0}`} · 손대지 않은 셀 ${result.not_failed} · 전문가 ${result.experts}명`
              : `바꿀 셀이 없었습니다(맞은 ${result.matched} · 손대지 않은 ${result.not_failed}).`
          }
          detail={[disposeJobLine(result.job, result.skipped !== undefined ? "skip" : "retry"), hitsLine(result)]
            .filter(Boolean)
            .join(" ")}
        />
      ) : null}
      {action ? (
        <form
          className="mt-3 flex flex-col gap-2 rounded-md border border-border p-3"
          onSubmit={(event) => {
            event.preventDefault();
            void send(asked !== null);
          }}
        >
          <ReviewErrorBanner error={error} onReload={cells.reload} />
          <p className="m-0 text-sm">
            {action.target === "selected" ? `고른 셀 ${selected.size}개` : `잡 ${jobId} 의 실패 셀 전부(filter {job_id, state: "failed"})`}를{" "}
            {action.kind === "retry"
              ? "다시 엽니다 — 기본은 실패 셀만 열고 나머지는 손대지 않습니다(not_failed)."
              : "넘깁니다 — 실패 셀만 skipped 가 되고 그 전문가는 다시 마감되어 보고서 '보지 못한 것' 에 '넘김 — 사유' 로 남습니다."}
          </p>
          {action.kind === "retry" ? (
            <>
              <label className="flex flex-wrap items-center gap-2 text-sm">
                <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
                <span>
                  force — 검토함(reviewed) · 입력 결손(no_input) 셀도 다시 열고 그 판정 행을 지웁니다(사유 필수 · 엔진 판이 오르기 전에
                  끝난 셀을 새 판으로 다시 볼 때). 이 길은 웹뿐입니다.
                </span>
              </label>
              <label className="flex flex-wrap items-center gap-2 text-sm">
                <input type="checkbox" checked={start} onChange={(e) => setStart(e.target.checked)} />
                <span>살아 있는 검토 잡이 없으면 다시 연 셀만 묶은 검토 잡을 세웁니다(start).</span>
              </label>
            </>
          ) : null}
          <FormField
            label={action.kind === "skip" ? "넘기는 사유" : "다시 여는 사유"}
            hint={needsReason ? "필수 · 4~300자" : "선택 · 적으면 4~300자"}
            error={reason !== "" && problem ? problem : undefined}
          >
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} aria-label="처분 사유" />
          </FormField>
          {asked ? (
            <div className="flex flex-col gap-2 rounded-md border-l-[3px] border-warn bg-warn/10 p-3 text-sm">
              <span className="font-medium">이 셀들을 다시 돌리는 호출 추정이 동의 문턱을 넘습니다 — 아무것도 바꾸지 않았습니다.</span>
              <EstimateBlock estimate={asked} />
              <label className="flex flex-wrap items-center gap-2">
                <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span className="font-medium">이 추정으로 다시 여는 데 동의합니다.</span>
              </label>
            </div>
          ) : null}
          <span className="flex flex-wrap items-center gap-2">
            <Button type="submit" size="sm" disabled={busy || problem !== null || selector() === null || (asked !== null && !consent)}>
              {asked ? "동의하고 다시" : action.kind === "retry" ? "다시 열기" : "넘기기"}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setAction(null)}>
              그만두기
            </Button>
          </span>
        </form>
      ) : null}
    </SectionCard>
  );
}
