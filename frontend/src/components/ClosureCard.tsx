// 완결 화면 — 완결 표기 · C1 · C2 · C3 조건 · 영역 깊이 · 잔여 표(막음/표기 · 확인 상태), 막음 잔여의 확인(사유 · basis_hash 그대로) · 확인 취소 · 다시 세기(포털 m3-frontend-request 6절)
import { useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { riskApi } from "../api/risk.api";
import { residualChangedOf } from "../api/reviewErrors";
import { useAsync } from "../hooks/useAsync";
import { Badge, LevelBadge } from "./Badge";
import { DataTable, KeyValueTable } from "./DataTable";
import type { Column } from "./DataTable";
import { ReviewErrorBanner } from "./ReviewErrorBanner";
import { SectionCard } from "./SectionCard";
import { ErrorBanner, LoadingBlock } from "./StateBlocks";
import { LockNote } from "./LockNote";
import { Banner, Button, FormField, Input, Mono } from "../ui/primitives";
import { ackReasonProblem, ackStateText, canAck, canRevoke, depthRows, regressedNote, residualCounts } from "../lib/closureView";
import { fmtEpoch } from "../format";
import { writeAccess } from "../lib/access";
import type { CloseAck, ClosureCells, ProjectRole, Qualifier } from "../types";

/** 확인 · 취소의 결과 한 줄 — 표기와 그 조작이 세운 보고서 판. */
type Outcome = { text: string; level_label: string; report_version: number | null };

function Conditions({ closure }: { closure: ClosureCells }) {
  const item = (name: string, ok: boolean) => (
    <Badge tone={ok ? "ok" : "muted"} title={ok ? `${name} 조건을 채웠다` : `${name} 조건 미달`}>
      {name} {ok ? "충족" : "미달"}
    </Badge>
  );
  return (
    <span className="flex flex-wrap items-center gap-1">
      {item("C1", closure.c1)}
      {item("C2", closure.c2)}
      {item("C3", closure.c3)}
    </span>
  );
}

/** 잔여 낱말마다 더 실리는 칸의 짧은 말 — 서버 칸 그대로. */
function extraText(q: Qualifier): string | null {
  const parts = [
    q.by_code ? `코드 ${Object.entries(q.by_code).map(([k, v]) => `${k} ${v}`).join(" · ")}` : null,
    q.crowded?.length ? `몰림 ${q.crowded.join(" · ")}` : null,
    q.sentences?.length ? q.sentences.join(" / ") : null,
    q.issue_ids?.length ? `쟁점 ${q.issue_ids.join(", ")}` : null,
    q.by_reason ? `까닭 ${Object.entries(q.by_reason).map(([k, v]) => `${k} ${v}`).join(" · ")}` : null,
    q.out_of_bounds?.length ? `기준 밖 ${q.out_of_bounds.join(" · ")}` : null,
    q.mixed && Object.keys(q.mixed).length ? `섞인 영역 ${Object.entries(q.mixed).map(([k, v]) => `${k} ${v}`).join(" · ")}` : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : null;
}

export function ClosureCard({
  targetKey,
  active,
  onChanged,
  onOpenReport,
  role = null,
}: {
  targetKey: string;
  /** 탭을 보고 있는가 — 볼 때마다 다시 읽는다(적던 확인 사유는 탭을 바꿔도 남는다). */
  active: boolean;
  onChanged: () => void;
  onOpenReport: () => void;
  /**
   * 대상 과제의 내 역할(진행판 my_role) — 잔여 확인 · 확인 취소는 소유자(와 관리자)만이라 편집자 · 보기에게는 잠그고 까닭을 보인다(OI-2,
   * 모르면 잠그지 않는다 — 구성원이 아닌 관리자는 서버가 받는다). '다시 세기' 는 읽기라 그대로다.
   */
  role?: ProjectRole | null;
}) {
  const access = writeAccess(role, "owner");
  const [mode, setMode] = useState<{ fresh: boolean; n: number }>({ fresh: false, n: 0 });
  /** fresh=1 을 이미 보낸 읽기 차례(mode.n). */
  const freshSent = useRef(-1);
  const closure = useAsync(
    (signal) => {
      // fresh=1(다시 세어 rr_targets 에 쓴다)은 '다시 세기' 와 409 residual_changed 뒤의 그 읽기 한 번만이다. 탭을 떠났다 돌아올 때는
      // (useAsync 가 active 도 deps 로 본다) 캐시를 읽는다 — 전에는 한 번 누른 뒤 탭에 돌아올 때마다 다시 세어 썼다.
      const fresh = mode.fresh && freshSent.current !== mode.n;
      if (fresh) freshSent.current = mode.n;
      return riskApi.getClosure(targetKey, fresh, { signal });
    },
    [targetKey, mode.n],
    active,
  );
  const [acking, setAcking] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [changedNote, setChangedNote] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const data = closure.data && closure.data.flow === "cells" ? closure.data : null;
  const problem = ackReasonProblem(reason);

  function reload(fresh: boolean) {
    setMode((m) => ({ fresh, n: m.n + 1 }));
  }

  async function ack(q: Qualifier) {
    if (problem) return;
    setBusy(true);
    setError(null);
    setChangedNote(null);
    setOutcome(null);
    try {
      const out = await riskApi.ackClosure(targetKey, q.item, reason.trim(), q.basis_hash);
      setOutcome({ text: `${q.item} 를 확인했습니다(${out.basis_n}건).`, level_label: out.level_label, report_version: out.report_version });
      setAcking(null);
      setReason("");
      reload(false);
      onChanged();
    } catch (err) {
      const now = residualChangedOf(err);
      if (now) {
        // 그사이 잔여가 바뀌었다 — 다시 읽어 사람에게 지금 집합을 보이고 다시 확인받는다(같은 사유 칸은 남긴다).
        setChangedNote(`그사이 잔여가 바뀌었습니다 — 지금 ${now.basis_n}건입니다. 다시 읽은 잔여를 보고 다시 확인하세요.`);
        reload(true);
      } else {
        setError(err);
      }
    } finally {
      setBusy(false);
    }
  }

  async function revoke(q: Qualifier) {
    setBusy(true);
    setError(null);
    setOutcome(null);
    try {
      const out = await riskApi.revokeClosureAck(targetKey, q.item);
      setOutcome({ text: `${q.item} 의 확인을 취소했습니다 — 그 잔여는 다시 막습니다.`, level_label: out.level_label, report_version: out.report_version });
      setRevoking(null);
      reload(false);
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<Qualifier>[] = [
    {
      key: "label",
      header: "잔여",
      hint: "label",
      // 표는 내용 폭(min-w-max)이라 긴 잔여 글(미토의 쟁점 문장 따위)이 확인 칸을 화면 밖으로 민다 — 이 칸만 폭을 묶어 접어 쓴다.
      cell: (q) => (
        <span className="flex max-w-[34rem] flex-col gap-0.5 whitespace-normal">
          <span>{q.label}</span>
          <span className="text-xs text-muted-foreground">
            <code>{q.item}</code>
            {extraText(q) ? ` · ${extraText(q)}` : ""}
          </span>
        </span>
      ),
    },
    {
      key: "blocking",
      header: "막음/표기",
      hint: "blocking",
      nowrap: true,
      cell: (q) => <Badge tone={q.blocking ? "warn" : "muted"}>{q.blocking ? "막음" : "표기"}</Badge>,
    },
    {
      key: "ack",
      header: "확인",
      hint: "ack",
      cell: (q) => (
        <span className="flex max-w-[18rem] flex-col items-start gap-0.5 whitespace-normal">
          <Badge tone={q.acked ? "ok" : q.blocking ? "warn" : "muted"}>{ackStateText(q)}</Badge>
          {q.ack ? (
            <span className="text-xs text-muted-foreground">
              {q.ack.by} · {fmtEpoch(q.ack.at)} — {q.ack.reason}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: "act",
      header: "조작",
      nowrap: true,
      cell: (q) => (
        <span className="flex flex-wrap items-center gap-1">
          {canAck(q) ? (
            <Button type="button" variant="outline" size="sm" disabled={!access.allowed} title={access.reason ?? undefined}
                    onClick={() => { setAcking(q.item); setRevoking(null); setReason(""); setError(null); setChangedNote(null); }}>
              확인…
            </Button>
          ) : null}
          {canRevoke(q) ? (
            <Button type="button" variant="ghost" size="sm" disabled={!access.allowed} title={access.reason ?? undefined}
                    onClick={() => { setRevoking(q.item); setAcking(null); setError(null); }}>
              확인 취소…
            </Button>
          ) : null}
        </span>
      ),
    },
  ];

  const ackColumns: Column<CloseAck>[] = [
    { key: "item", header: "잔여", hint: "item", cell: (a) => <code>{a.item}</code>, nowrap: true },
    { key: "state", header: "상태", hint: "state", cell: (a) => <Badge tone={a.state === "valid" ? "ok" : a.state === "stale" ? "warn" : "muted"}>{a.state}</Badge>, nowrap: true },
    { key: "by", header: "확인한 사람", hint: "ack_by · ack_at", cell: (a) => `${a.ack_by} · ${fmtEpoch(a.ack_at)}`, nowrap: true },
    { key: "reason", header: "사유", hint: "ack_reason", cell: (a) => a.ack_reason },
    { key: "basis", header: "받은 집합", hint: "basis_n", cell: (a) => `${a.basis_n}건`, align: "right", nowrap: true },
    { key: "revoked", header: "취소", hint: "revoked_by", cell: (a) => (a.revoked_at ? `${a.revoked_by ?? "?"} · ${fmtEpoch(a.revoked_at)}` : "—"), nowrap: true },
  ];

  const acked = data?.qualifiers.find((q) => q.item === acking) ?? null;
  const toRevoke = data?.qualifiers.find((q) => q.item === revoking) ?? null;
  const counts = data ? residualCounts(data.qualifiers) : null;

  return (
    <SectionCard
      title="완결과 확인"
      subtitle="막음 잔여는 소유자 · 관리자가 사유와 함께 확인해야 레벨이 오릅니다. 확인 길은 웹뿐입니다."
      actions={
        <Button type="button" variant="outline" size="sm" onClick={() => reload(true)} disabled={closure.loading}>
          <RefreshCw className="size-4" aria-hidden="true" />
          다시 세기
        </Button>
      }
    >
      <LockNote access={access} />
      <ErrorBanner error={closure.error} onRetry={() => reload(false)} />
      {closure.loading && !closure.data ? <LoadingBlock /> : null}
      {closure.data && closure.data.flow === "panels" ? (
        <p className="m-0 text-sm text-muted-foreground">패널 대상은 패널 판정으로 닫힙니다 — 잔여 확인 길이 없습니다.</p>
      ) : null}
      {outcome ? (
        <Banner tone="info" live="status" title={outcome.text} detail={`표기 — ${outcome.level_label}`}>
          {outcome.report_version !== null ? (
            <Button type="button" variant="outline" size="sm" onClick={onOpenReport}>
              보고서 v{outcome.report_version}
            </Button>
          ) : (
            <span className="text-xs">보고서 판 조립이 실패했습니다(확인 자체는 섰다).</span>
          )}
        </Banner>
      ) : null}
      {data ? (
        <>
          <KeyValueTable
            columns={1}
            rows={[
              {
                label: "완결 표기",
                hint: "level_label",
                value: (
                  <span className="flex flex-wrap items-center gap-2">
                    <LevelBadge value={data.level} />
                    <span>{data.level_label}</span>
                  </span>
                ),
              },
              {
                label: "레벨",
                hint: "level · level_current · close_level",
                value: (
                  <span className="flex flex-col gap-0.5">
                    <span>
                      저장 {data.level} · 지금 계산 {data.level_current} · 마감 레벨 {data.close_level}
                    </span>
                    {regressedNote(data) ? <strong>{regressedNote(data)}</strong> : null}
                  </span>
                ),
              },
              { label: "조건", hint: "c1 · c2 · c3", value: <Conditions closure={data} /> },
              {
                label: "잔여",
                hint: "qualifiers",
                value: counts ? `막음 ${counts.blocking}(확인 안 됨 ${counts.unacked}) · 표기 ${counts.marks}` : "—",
              },
              {
                label: "셀",
                hint: "counts.cells",
                value: `${data.counts.cells.actual}/${data.counts.cells.expected}칸 · 판정 누락 ${data.counts.cells.verdict_gaps} · ${Object.entries(data.counts.cells.by_state)
                  .map(([k, v]) => `${k} ${v}`)
                  .join(" · ")}`,
              },
              {
                label: "전문가 보고서",
                hint: "counts.experts.reports",
                value: `기대 ${data.counts.experts.reports.expected} · ready ${data.counts.experts.reports.ready} · partial ${data.counts.experts.reports.partial} · blocked ${data.counts.experts.reports.blocked} · 누락 ${data.counts.experts.reports.missing}`,
              },
              {
                label: "쟁점",
                hint: "counts.issues",
                value: `진행 ${data.counts.issues.open} · ${Object.entries(data.counts.issues.by_state)
                  .map(([k, v]) => `${k} ${v}`)
                  .join(" · ") || "없음"}`,
              },
              {
                label: "등록부 주의",
                hint: "counts.registry.attention",
                value: `A ${data.counts.registry.attention.A} · B ${data.counts.registry.attention.B} · C ${data.counts.registry.attention.C} · D ${data.counts.registry.attention.D} · 카드 FAIL 주장 ${data.counts.registry.card_fail_claimed}`,
              },
              {
                label: "후속 신선도",
                hint: "detail.fresh",
                value: `쟁점 ${data.detail.fresh.issues ? "지금 셀 지문" : "낡음"} · 보고서 ${data.detail.fresh.report ? "지금 셀 지문" : "낡음"}${
                  data.detail.fresh.report_version !== null ? ` · 마지막 판 v${data.detail.fresh.report_version}` : ""
                }`,
              },
            ]}
          />
          {data.counts.invariants.length > 0 ? (
            <Banner tone="warn" live="none" title={`셀 원장 불변식 위반 ${data.counts.invariants.length}건`} detail={data.counts.invariants.join(" · ")} />
          ) : null}
          <h3 className="m-0 mt-4 text-sm text-muted-foreground">잔여</h3>
          {changedNote ? <Banner tone="warn" live="status" title={changedNote} /> : null}
          <ReviewErrorBanner error={error} onReload={() => reload(true)} />
          <DataTable columns={columns} rows={data.qualifiers} rowKey={(q) => q.item} empty="잔여가 없습니다." />
          {acked ? (
            <form
              className="mt-3 flex flex-col gap-2 rounded-md border border-border p-3"
              onSubmit={(event) => {
                event.preventDefault();
                void ack(acked);
              }}
            >
              <p className="m-0 text-sm">
                <strong>{acked.label}</strong> 을 확인으로 넘깁니다 — 지금 읽은 집합(<Mono>{acked.basis_hash}</Mono> · {acked.basis_n}건)에 대한
                확인입니다. 확인 뒤 집합이 바뀌면 그 확인은 낡아 다시 막습니다.
              </p>
              <FormField label="확인 사유" hint="필수 · 300자 안" error={reason !== "" && problem ? problem : undefined}>
                <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} aria-label="확인 사유" />
              </FormField>
              <span className="flex flex-wrap items-center gap-2">
                <Button type="submit" size="sm" disabled={busy || problem !== null}>
                  확인
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => setAcking(null)}>
                  그만두기
                </Button>
              </span>
            </form>
          ) : null}
          {toRevoke ? (
            <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-border p-3 text-sm">
              <span className="min-w-0 flex-1">
                <strong>{toRevoke.label}</strong> 의 확인을 취소합니다 — 행은 지우지 않고 취소로 표기하며, 막음 잔여는 다시 막습니다.
              </span>
              <Button type="button" variant="outline" size="sm" onClick={() => void revoke(toRevoke)} disabled={busy}>
                확인 취소하기
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={() => setRevoking(null)}>
                그만두기
              </Button>
            </div>
          ) : null}
          <h3 className="m-0 mt-4 text-sm text-muted-foreground">영역 깊이(분모는 카드로 본 전문가)</h3>
          <DataTable
            columns={[
              { key: "domain", header: "영역", cell: (r: ReturnType<typeof depthRows>[number]) => r.domain, nowrap: true },
              {
                key: "have",
                header: "have/need",
                align: "right",
                nowrap: true,
                cell: (r: ReturnType<typeof depthRows>[number]) =>
                  r.short ? <Badge tone="warn">{`${r.have}/${r.need}`}</Badge> : `${r.have}/${r.need}`,
              },
              { key: "active", header: "카드로 본 전문가", align: "right", nowrap: true, cell: (r: ReturnType<typeof depthRows>[number]) => String(r.active) },
              { key: "cardless", header: "카드 없는 전문가", align: "right", nowrap: true, cell: (r: ReturnType<typeof depthRows>[number]) => String(r.cardless) },
              {
                key: "exempt",
                header: "면제",
                nowrap: true,
                cell: (r: ReturnType<typeof depthRows>[number]) => (r.exempt ? "카드 없는 영역 — 표기 잔여" : "—"),
              },
            ]}
            rows={depthRows(data.detail.depth)}
            rowKey={(r) => r.domain}
            empty="깊이를 셀 영역이 없습니다."
          />
          <h3 className="m-0 mt-4 text-sm text-muted-foreground">확인 이력</h3>
          <DataTable columns={ackColumns} rows={data.acks} rowKey={(a) => `${a.item}#${a.ack_at}`} empty="확인 이력이 없습니다." />
        </>
      ) : null}
    </SectionCard>
  );
}
