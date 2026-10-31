// 등록부 · 판정 확정 — 주의 등급 · 지지 수(전문가 · 영역 · 단위 · 검증) · 쟁점 패널이 덮은 행의 '원래 — …' 줄 · 다시 토의 표기, 주의 · 단위 거름과 패널만 본 비교 보기(포털 m3-frontend-request 7절)
import { useState } from "react";
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import type { Async } from "../hooks/useAsync";
import {
  Badge,
  EvidenceGradeBadge,
  JudgementBadge,
  RegistryStatusBadge,
  SeverityBadge,
  StatusBadge,
  VerdictBadge,
} from "./Badge";
import { DataTable, KeyValueTable } from "./DataTable";
import type { Column } from "./DataTable";
import { HumanFindingForm } from "./HumanFindingForm";
import { SectionCard, VerbatimBlock } from "./SectionCard";
import { ErrorBanner, LoadingBlock } from "./StateBlocks";
import { Banner, Button, FormField, FormGrid, Input, Select, SubPanel } from "../ui/primitives";
import { distributionText, labelOf, OUTCOME_LABEL, registryOverlayLine } from "../lib/issueView";
import { fmtCounts, fmtJson, fmtNum } from "../format";
import type { Registry, RegistryQuery, RegistryRow, RegistryStatusInput, Verdict } from "../types";

const VERDICTS: Verdict[] = ["go", "conditional", "no-go", "undetermined"];
const REGISTRY_STATUSES: RegistryStatusInput[] = ["verified", "dismissed", "mitigated"];
const ATTENTIONS = ["A", "B", "C", "D"] as const;
const ATTENTION_TONE: Record<string, "bad" | "warn" | "info" | "muted"> = { A: "bad", B: "warn", C: "info", D: "muted" };

/** 행의 영역 — 병합 행에는 domain 칸이 없다. 대표의 소유 영역(owner_domain), 없으면 제기 원자들의 영역(domains). */
export function rowDomains(row: Pick<RegistryRow, "merged">): string[] {
  const owner = row.merged.owner_domain;
  const domains = row.merged.domains ?? [];
  return owner ? [owner, ...domains.filter((d) => d !== owner)] : domains;
}

/** 지지 수 넷 — 서로 다른 제기 전문가 · 영역 · 단위 · 검증된 인용을 낸 전문가. 병합 전 옛 행은 칸이 비어 '모름' 이다. */
export function supportText(row: Pick<RegistryRow, "support_experts" | "support_domains" | "support_units" | "support_verified">): string {
  const n = (v: number | null) => (v === null || v === undefined ? "?" : String(v));
  return `전문가 ${n(row.support_experts)} · 영역 ${n(row.support_domains)} · 단위 ${n(row.support_units)} · 검증 ${n(row.support_verified)}`;
}

/** 참조 하나를 눌러서 펼쳐 보는 상자(`GET refs/{ref}`). */
function RefPeek({ value }: { value: string }) {
  const [open, setOpen] = useState(false);
  const resolved = useAsync((signal) => riskApi.getRef(value, { signal }), [value], open);
  return (
    <div className="mt-1 flex flex-col gap-2">
      <Button type="button" variant="ghost" size="sm" className="w-fit" onClick={() => setOpen((v) => !v)}>
        <code>{value}</code>
      </Button>
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

/** 쟁점 칸 — 쟁점 상태 · '원래 — …' 줄 · 다시 토의 표기(굵게). */
export function IssueCell({ row }: { row: RegistryRow }) {
  const overlay = registryOverlayLine(row);
  const reraised = row.merged.issue_reraised;
  if (!row.issue_state && !overlay && !reraised) return <span className="text-muted-foreground">—</span>;
  return (
    // 표는 내용 폭(min-w-max)이라 폭을 묶어 '원래 — …' 줄을 접어 쓴다(그래야 뒤 열이 화면 밖으로 밀리지 않는다).
    <span className="flex max-w-[20rem] flex-col items-start gap-0.5 whitespace-normal">
      {row.issue_state ? (
        <StatusBadge value={row.issue_state} title={labelOf(OUTCOME_LABEL, row.issue_state)} />
      ) : null}
      {overlay ? <span className="text-xs">{overlay}</span> : null}
      {reraised ? <strong className="text-xs">{reraised.label}</strong> : null}
    </span>
  );
}

/** 등록부 행 하나를 펼친 칸 — 주장 · 근거 · 지지 · 주장값 · 분포 · 쟁점 패널이 덮기 전 값(행 칸이 아니라 merged 에서 읽는다). */
export function RegistryRowDetail({ row }: { row: RegistryRow }) {
  const m = row.merged;
  const before = m.before_issue;
  return (
    <>
      {m.claim ? <VerbatimBlock text={m.claim} label="주장(claim)" /> : <p className="m-0 text-sm text-muted-foreground">주장 글이 없습니다.</p>}
      {m.warrant ? <VerbatimBlock text={m.warrant} label="근거 문장(warrant)" /> : null}
      <KeyValueTable
        rows={[
          { label: "주체", hint: "subject_key", value: row.subject_key ? <code>{row.subject_key}</code> : "—" },
          { label: "영역", hint: "merged.owner_domain · domains", value: rowDomains(row).join(" · ") || "—" },
          { label: "제기", hint: "merged.raised_by", value: (m.raised_by ?? []).join(" · ") || "—" },
          { label: "단위", hint: "merged.unit_ids", value: (m.unit_ids ?? []).join(" · ") || "—" },
          { label: "지지", hint: "support_*", value: supportText(row) },
          {
            label: "주장값",
            hint: "merged.claimed",
            value: m.claimed
              ? `${m.claimed.judgement ?? "—"} · ${m.claimed.severity ?? "—"} · FAIL 주장 ${m.claimed.fail_experts}명 · 치명 ${m.claimed.critical_experts}명 · 검증된 FAIL ${m.claimed.verified_fail_experts}명`
              : "—",
          },
          {
            label: "분포",
            hint: "merged.distribution",
            value: m.distribution ? (distributionText(m.distribution.by_judgement_claimed) ?? "—") : "—",
          },
          ...(before
            ? [
                {
                  label: "쟁점 패널이 덮기 전",
                  hint: "merged.before_issue",
                  value: `${before.severity}/${before.judgement} · ${before.evidence_grade} · 제기 ${before.support_experts ?? "?"}명${
                    before.distribution ? ` · ${distributionText(before.distribution.by_judgement_claimed) ?? ""}` : ""
                  }`,
                },
              ]
            : []),
        ]}
      />
      {m.issue_reraised ? (
        <Banner tone="warn" live="none" title={m.issue_reraised.label} detail={`쟁점 ${row.issue_id ?? "?"} — 새 패널이 정할 때까지 옛 판정이 보입니다.`} />
      ) : null}
      <h3 className="m-0 text-sm text-muted-foreground">근거</h3>
      {(m.cites ?? []).length === 0 ? (
        <p className="m-0 text-sm text-muted-foreground">근거 참조가 없습니다.</p>
      ) : (
        <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
          {(m.cites ?? []).map((c, i) => (
            <li key={`${c.ref}#${i}`}>
              <RefPeek value={c.ref} />
              <span className="text-sm text-muted-foreground">{c.quote}</span>
              {c.quote_chars ? <span className="text-xs text-muted-foreground"> (원래 {c.quote_chars}자)</span> : null}
            </li>
          ))}
        </ul>
      )}
      {(m.contest_notes ?? []).length > 0 ? (
        <>
          <h3 className="m-0 text-sm text-muted-foreground">이의</h3>
          <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
            {(m.contest_notes ?? []).map((c) => (
              <li key={c.finding_id}>
                {c.by.join(" · ")} — {c.note || "사유 없음"}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </>
  );
}

/**
 * 등록부 카드 — 거름 칸 가운데 주의 등급 · 단위 · 패널만 본 비교 보기는 서버 쿼리다(TargetPage 가 들고 같은 응답으로 머리의 판정을
 * 읽는다). 심각도 · 영역 · 방향 · 상태는 받은 행 안에서 거른다. 카드 대조 대상의 기본은 주의 A · B 다.
 */
export function RegistryCard({
  targetKey,
  registry,
  query,
  onQuery,
  cells,
}: {
  targetKey: string;
  registry: Async<Registry>;
  query: RegistryQuery;
  onQuery: (next: RegistryQuery) => void;
  /** 카드 대조 대상인가 — 주의 등급 · 지지 수가 그 대상에서 뜻이 있다(패널 대상은 참고값). */
  cells: boolean;
}) {
  // mechanism 선택지는 서버 택소노미에서 온다(§7.1) — 화면이 어휘를 따로 가지면 한쪽만 늙는다.
  const taxonomy = useAsync((signal) => riskApi.getTaxonomy({ signal }), []);
  const [severity, setSeverity] = useState("");
  const [domain, setDomain] = useState("");
  const [direction, setDirection] = useState("");
  const [status, setStatus] = useState("");
  const [unit, setUnit] = useState(query.unit_id ?? "");
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [nextStatus, setNextStatus] = useState<RegistryStatusInput>("verified");
  const [evidenceRef, setEvidenceRef] = useState("");
  const [note, setNote] = useState("");
  const [verdict, setVerdict] = useState<Verdict>("undetermined");
  const [verdictNote, setVerdictNote] = useState("");

  const attention = new Set((query.attention ?? "").split(",").filter(Boolean));
  const rows = registry.data?.rows ?? [];
  const filtered = rows.filter(
    (r) =>
      (severity === "" || r.severity === severity) &&
      (domain === "" || rowDomains(r).includes(domain)) &&
      (direction === "" || r.direction === direction) &&
      (status === "" || r.status === status),
  );
  const selectedRow = rows.find((r) => r.cluster_key === selected) ?? null;
  const domains = Array.from(new Set(rows.flatMap((r) => rowDomains(r)))).sort();

  function toggleAttention(grade: string) {
    const next = new Set(attention);
    if (next.has(grade)) next.delete(grade);
    else next.add(grade);
    onQuery({ ...query, attention: next.size > 0 ? ATTENTIONS.filter((a) => next.has(a)).join(",") : undefined });
  }

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

  // 읽는 차례대로 — 주의 · 키 · 영역 · 심각도 · 판정 · 쟁점(덮었으면 '원래 — …') · 지지가 앞이다. 표는 내용 폭이라 앞 열이 화면 안에
  // 남고 나머지(근거 등급 · 메커니즘 · 방향 · 옛 지지 · 상태 · 우선순위)는 가로로 흘러간다.
  const columns: Column<RegistryRow>[] = [
    {
      key: "attention",
      header: "주의",
      hint: "attention",
      nowrap: true,
      cell: (r) =>
        r.attention ? (
          <Badge tone={ATTENTION_TONE[r.attention] ?? "muted"} title="읽는 순서이지 판정이 아닙니다">
            {r.attention}
          </Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    { key: "cluster", header: "cluster_key", cell: (r) => <code>{r.cluster_key}</code>, nowrap: true },
    { key: "domain", header: "영역", hint: "merged.owner_domain", cell: (r) => rowDomains(r)[0] ?? "—", nowrap: true },
    { key: "severity", header: "severity", cell: (r) => <SeverityBadge value={r.severity} />, nowrap: true },
    { key: "judgement", header: "judgement", cell: (r) => <JudgementBadge value={r.judgement} />, nowrap: true },
    { key: "issue", header: "쟁점", hint: "issue_state", cell: (r) => <IssueCell row={r} /> },
    { key: "support4", header: "지지", hint: "support_*", cell: (r) => supportText(r), nowrap: true },
    { key: "grade", header: "evidence_grade", cell: (r) => <EvidenceGradeBadge value={r.evidence_grade} />, nowrap: true },
    { key: "mechanism", header: "mechanism", cell: (r) => `${r.mechanism}${r.mechanism_detail ? ` · ${r.mechanism_detail}` : ""}`, nowrap: true },
    { key: "direction", header: "direction", cell: (r) => r.direction, nowrap: true },
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
      <SectionCard
        title="등록부"
        subtitle={
          cells
            ? "주의 등급 → 우선순위 → 지지 영역 → 지지 전문가 순입니다. 주의 등급은 읽는 순서이지 판정이 아닙니다."
            : "행을 누르면 주장과 근거 참조가 펼쳐집니다. 주의 등급 · 지지 수는 패널 대상에서 참고값입니다."
        }
      >
        <ErrorBanner error={registry.error} onRetry={registry.reload} />
        <ErrorBanner error={error} />
        {registry.loading && !registry.data ? <LoadingBlock /> : null}
        <HumanFindingForm
          targetKey={targetKey}
          mechanisms={taxonomy.data?.axes?.mechanism ?? []}
          onCreated={registry.reload}
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">주의 등급</span>
          {ATTENTIONS.map((a) => (
            <label key={a} className="flex items-center gap-1 text-sm">
              <input type="checkbox" checked={attention.has(a)} onChange={() => toggleAttention(a)} />
              {a}
            </label>
          ))}
          <span className="text-xs text-muted-foreground">{attention.size === 0 ? "(전부)" : ""}</span>
          <span className="mx-1 h-5 w-px bg-border" aria-hidden="true" />
          <form
            className="flex items-center gap-1"
            onSubmit={(event) => {
              event.preventDefault();
              onQuery({ ...query, unit_id: unit.trim() || undefined });
            }}
          >
            <Input className="w-auto min-w-[10rem]" aria-label="단위 거름" placeholder="단위 id" value={unit} onChange={(e) => setUnit(e.target.value)} />
            <Button type="submit" variant="outline" size="sm">
              단위로 거르기
            </Button>
          </form>
          <label className="flex items-center gap-1 text-sm" title="저장하지 않고 패널 finding 만으로 다시 센 등록부(패널을 돌린 뒤 cells 로 바꾼 대상의 '바꾸기 전 등록부')">
            <input
              type="checkbox"
              checked={query.source === "panels"}
              onChange={(e) => onQuery({ ...query, source: e.target.checked ? "panels" : undefined })}
            />
            패널만 본 비교 보기
          </label>
        </div>
        {query.source === "panels" ? (
          <Banner tone="info" live="none" title="패널 finding 만으로 다시 센 비교 보기입니다 — 저장하지 않았고 상태 변경은 저장된 등록부에 합니다." />
        ) : null}
        {/* 걸러내기 네 칸 — Select 는 기본이 w-full 이라 한 줄에 서려면 폭을 풀어 준다. */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Select className="w-auto min-w-[9rem]" aria-label="severity 걸러내기" value={severity} onChange={(e) => setSeverity(e.target.value)}>
            <option value="">severity 전체</option>
            {["경미", "중대", "치명"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
          <Select className="w-auto min-w-[9rem]" aria-label="영역 걸러내기" value={domain} onChange={(e) => setDomain(e.target.value)}>
            <option value="">영역 전체</option>
            {domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </Select>
          <Select className="w-auto min-w-[9rem]" aria-label="direction 걸러내기" value={direction} onChange={(e) => setDirection(e.target.value)}>
            <option value="">direction 전체</option>
            {["risk", "improvement", "neutral"].map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </Select>
          <Select className="w-auto min-w-[9rem]" aria-label="status 걸러내기" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">status 전체</option>
            {["open", "verified", "dismissed", "mitigated", "superseded", "rejected_in_panel"].map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
          <span className="text-sm text-muted-foreground">
            {filtered.length} / {rows.length} 행{registry.data ? ` · 서버 거름 뒤 ${registry.data.total}` : ""}
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
          <SubPanel className="mt-3" title={selectedRow.cluster_key} actions={<RegistryStatusBadge value={selectedRow.status} />}>
            <RegistryRowDetail row={selectedRow} />
            {query.source === "panels" ? null : (
              <>
                <h3 className="m-0 text-sm text-muted-foreground">상태 변경</h3>
                <FormGrid>
                  <FormField label="바꿀 상태" hint="status">
                    <Select value={nextStatus} onChange={(e) => setNextStatus(e.target.value as RegistryStatusInput)}>
                      {REGISTRY_STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                    </Select>
                  </FormField>
                  <FormField label="근거 참조" hint="evidence_ref · 선택">
                    <Input value={evidenceRef} onChange={(e) => setEvidenceRef(e.target.value)} />
                  </FormField>
                  <FormField label="메모" hint="note · 선택">
                    <Input value={note} onChange={(e) => setNote(e.target.value)} />
                  </FormField>
                </FormGrid>
                <Button type="button" variant="outline" className="w-fit" onClick={saveStatus} disabled={busy}>
                  상태 저장
                </Button>
              </>
            )}
          </SubPanel>
        ) : null}
      </SectionCard>

      <SectionCard title="판정 확정" subtitle="후보는 집계일 뿐이고 확정은 사람이 합니다.">
        {registry.data?.verdict_candidate ? (
          <KeyValueTable
            rows={[
              {
                label: "집계 후보",
                hint: "verdict_candidate.verdict",
                value: <VerdictBadge value={registry.data.verdict_candidate.verdict} />,
              },
              {
                label: "후보 사유",
                hint: "reasons",
                value:
                  registry.data.verdict_candidate.reasons.length === 0 ? (
                    <span className="text-muted-foreground">없음</span>
                  ) : (
                    <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
                      {registry.data.verdict_candidate.reasons.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                  ),
              },
              {
                // 열린 · 검증된 클러스터만 센 수다 — 후보가 어디서 나왔는지 보이게 둔다.
                label: "집계",
                hint: "counts",
                value: fmtCounts(registry.data.verdict_candidate.counts),
              },
              {
                label: "확정값",
                hint: "verdict_final",
                value: <VerdictBadge value={registry.data.verdict_final ?? "undetermined"} />,
              },
            ]}
          />
        ) : (
          <p className="text-sm text-muted-foreground">후보가 아직 없습니다.</p>
        )}
        <FormGrid>
          <FormField label="판정" hint="verdict">
            <Select value={verdict} onChange={(e) => setVerdict(e.target.value as Verdict)}>
              {VERDICTS.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="사유 메모" hint="note">
            <Input value={verdictNote} onChange={(e) => setVerdictNote(e.target.value)} />
          </FormField>
        </FormGrid>
        <Button type="button" className="mt-3" onClick={saveVerdict} disabled={busy}>
          확정
        </Button>
      </SectionCard>
    </>
  );
}
