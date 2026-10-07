// 홈 화면 — 상단 탭 4개(과제·비교·타깃·보고서)·박스 자격 배너·과제 카드 그리드·과제 등록 폼(계획 §8.2.4 RiskHomePage 행).
import { useState } from "react";
import { Link } from "react-router-dom";
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { CardGrid, SectionCard } from "../components/SectionCard";
import { EmptyBlock, ErrorBanner, LoadingBlock } from "../components/StateBlocks";
import { Badge, LevelBadge, VerdictBadge } from "../components/Badge";
import { Banner, Button, Chip, FormField, FormGrid, Input, Select, TabBar } from "../ui/primitives";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { fmtDay, fmtEpoch, fmtPct } from "../format";
import type { DiffListRow, ProjectCard, ReportListRow, SourceKind, TargetListRow } from "../types";

/** 카드에 아이콘처럼 늘어놓는 소스 3종(해석 결과는 스냅샷 kinds 에서만 쓴다). */
const CARD_KINDS: SourceKind[] = ["mcad", "dyna", "ecad"];
const KIND_LABEL: Record<string, string> = {
  mcad: "MCAD",
  dyna: "DynaForge",
  dyna_result: "해석 결과",
  ecad: "ECAD",
};
/** §8.2.4 의 stage 정규식. */
const STAGE_RE = /^(pre|dv|pv|pra|mp)([123r])?$/;

/** 홈 상단 탭 4개(정본 §8.2.4). 넷 다 서버 목록 경로가 있다. */
type HomeTab = "projects" | "diffs" | "targets" | "reports";
const HOME_TABS: Array<{ tab: HomeTab; label: string }> = [
  { tab: "projects", label: "과제" },
  { tab: "diffs", label: "비교" },
  { tab: "targets", label: "타깃" },
  { tab: "reports", label: "보고서" },
];

/** 소스 상태 → 칩 색. 'unlinked'(연결 안 함)는 실패가 아니라 **아직 안 한 것**이라 muted 다. */
const SOURCE_TONE: Record<string, "ok" | "warn" | "bad" | "muted"> = {
  ready: "ok",
  linked: "ok",
  unavailable: "bad",
  unreachable: "bad",
  planned: "warn",
  contract_only: "warn",
  unlinked: "muted",
};

/**
 * 과제 카드 — 요약 먼저다.
 *
 * 이 카드에서 사람이 먼저 알아야 할 것은 **"이 과제를 지금 심사할 수 있나"** 이고, 그건 소스가
 * 붙었는지로 결정된다. 그래서 소스 3종을 맨 위 줄에 두고, 진행도(열린 타깃·커버리지)는 숫자를 키워
 * 한눈에 읽히게 하며, 시각·단계 같은 보조 사실은 밑에 작게 깐다. 예전에는 다섯 줄이 같은 크기로
 * 평평하게 쌓여 있어 무엇이 중요한지 읽는 사람이 매번 다시 판단해야 했다.
 */
function ProjectTile({ card }: { card: ProjectCard }) {
  const linked = CARD_KINDS.filter((k) => {
    const status = card.sources.find((s) => s.kind === k)?.status ?? "unlinked";
    return status !== "unlinked";
  }).length;
  return (
    <Link
      to={`/projects/${encodeURIComponent(card.id)}`}
      className="group flex flex-col gap-3 rounded-lg border border-border bg-card p-4 shadow-sm no-underline transition-all hover:border-primary/50 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-foreground">{card.name}</div>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
            <span className="font-mono">{card.code}</span>
            {card.stage ? <span>· {card.stage}</span> : null}
          </div>
        </div>
        {/* level 은 타깃이 생겨야 정해진다 — 없을 때 '-' 배지를 그리면 '등급이 하이픈' 으로 읽힌다. */}
        {card.level ? <LevelBadge value={card.level} /> : null}
      </div>

      {/* 소스 — '지금 심사할 수 있나' 의 답이라 맨 위다. */}
      <div className="flex flex-wrap items-center gap-1">
        {CARD_KINDS.map((kind) => {
          const status = card.sources.find((s) => s.kind === kind)?.status ?? "unlinked";
          return (
            <Chip key={kind} tone={SOURCE_TONE[status] ?? "muted"} title={`${KIND_LABEL[kind]} — ${status}`}>
              {KIND_LABEL[kind]}
            </Chip>
          );
        })}
        {linked === 0 ? <span className="text-xs text-muted-foreground">소스를 먼저 연결하세요.</span> : null}
      </div>

      {/* 진행 — 숫자를 키워 한눈에. 없을 때 0 을 쓰지 않는다(미측정과 0 은 다르다). */}
      <div className="mt-auto flex items-end gap-5 border-t border-border pt-3">
        <div className="flex flex-col">
          <span className="text-lg font-semibold leading-none tabular-nums">{card.open_targets}</span>
          <span className="mt-1 text-xs text-muted-foreground">열린 타깃</span>
        </div>
        <div className="flex flex-col">
          <span className="text-lg font-semibold leading-none tabular-nums">
            {card.coverage_pct === null ? <span className="text-muted-foreground">—</span> : fmtPct(card.coverage_pct)}
          </span>
          <span className="mt-1 text-xs text-muted-foreground">커버리지</span>
        </div>
        <span className="ml-auto text-xs text-muted-foreground">
          {card.last_snapshot_at ? `스냅샷 ${fmtDay(card.last_snapshot_at)}` : "스냅샷 없음"}
        </span>
      </div>
    </Link>
  );
}

function ProjectForm({ options, onCreated }: { options: ProjectCard[]; onCreated: () => void }) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [stage, setStage] = useState("");
  const [predecessor, setPredecessor] = useState("");
  const [team, setTeam] = useState("");
  const [group, setGroup] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const stageInvalid = stage.trim() !== "" && !STAGE_RE.test(stage.trim());
  const canSubmit =
    code.trim() !== "" && name.trim() !== "" && team.trim() !== "" && group.trim() !== "" && !stageInvalid && !busy;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created = await riskApi.createProject({
        code: code.trim(),
        name: name.trim(),
        stage: stage.trim() === "" ? null : stage.trim(),
        predecessor_project_id: predecessor.trim() === "" ? null : predecessor.trim(),
        adh_scope: { team: team.trim(), group: group.trim() },
      });
      setNotice(`과제 ${created.code} 를 만들었습니다.`);
      setCode("");
      setName("");
      setStage("");
      setPredecessor("");
      onCreated();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="mb-4 flex flex-col gap-3" onSubmit={submit}>
      <ErrorBanner error={error} />
      {/* 등록 성공은 끼어들어 읽힐 일이 아니다 — status 로 둔다. */}
      {notice ? <Banner tone="info" live="status" title={notice} /> : null}
      <FormGrid>
        <FormField label="code (≤40)">
          <Input maxLength={40} value={code} onChange={(e) => setCode(e.target.value)} />
        </FormField>
        <FormField label="name (≤200)">
          <Input maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
        </FormField>
        <FormField
          label="stage (pre · dv · pv · pra · mp + 1/2/3/r)"
          error={stageInvalid ? "형식이 맞지 않습니다." : undefined}
        >
          <Input value={stage} onChange={(e) => setStage(e.target.value)} />
        </FormField>
        <FormField label="predecessor_project_id (선택)">
          <Select value={predecessor} onChange={(e) => setPredecessor(e.target.value)}>
            <option value="">없음</option>
            {options.map((p) => (
              <option key={p.id} value={p.id}>
                {p.code} · {p.name}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="adh_scope.team">
          <Input value={team} onChange={(e) => setTeam(e.target.value)} />
        </FormField>
        <FormField label="adh_scope.group">
          <Input value={group} onChange={(e) => setGroup(e.target.value)} />
        </FormField>
      </FormGrid>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={!canSubmit}>
          과제 등록
        </Button>
        <span className="text-sm text-muted-foreground">adh_scope 는 자동으로 채우지 않습니다.</span>
      </div>
    </form>
  );
}

export default function RiskHomePage() {
  const me = useAsync((signal) => riskApi.getMe({ signal }), []);
  const projects = useAsync((signal) => riskApi.listProjects({ signal }), []);
  const [formOpen, setFormOpen] = useState(false);
  const [tab, setTab] = useState<HomeTab>("projects");
  const cards = projects.data?.projects ?? [];

  return (
    <>
      <ErrorBanner error={me.error} onRetry={me.reload} />
      {me.data && me.data.box.secrets_valid === false ? (
        <Banner title="이 박스의 자격이 없습니다.">
          <Link to="/settings" className="text-sm underline underline-offset-4">
            설정
          </Link>
        </Banner>
      ) : null}

      <TabBar tabs={HOME_TABS} value={tab} onChange={setTab} label="홈 탭" />

      {tab === "diffs" ? <DiffsTab /> : null}
      {tab === "targets" ? <TargetsTab /> : null}
      {tab === "reports" ? <ReportsTab /> : null}

      {tab === "projects" ? (
        <SectionCard
          title="과제"
          subtitle="설계 리스크 심사의 시작점입니다."
          actions={
            <Button type="button" variant="outline" onClick={() => setFormOpen((v) => !v)}>
              {formOpen ? "등록 폼 닫기" : "과제 등록"}
            </Button>
          }
        >
          {formOpen ? <ProjectForm options={cards} onCreated={projects.reload} /> : null}
          <ErrorBanner error={projects.error} onRetry={projects.reload} />
          {projects.loading && !projects.data ? <LoadingBlock /> : null}
          {projects.data && cards.length === 0 ? (
            <EmptyBlock
              title="아직 과제가 없습니다."
              hint="소스(StepForge · DynaForge · ODB)를 연결할 과제를 먼저 등록하세요."
              action={
                <Button type="button" onClick={() => setFormOpen(true)}>
                  과제 등록
                </Button>
              }
            />
          ) : null}
          {cards.length > 0 ? (
            <CardGrid>
              {cards.map((card) => (
                <ProjectTile key={card.id} card={card} />
              ))}
            </CardGrid>
          ) : null}
        </SectionCard>
      ) : null}
    </>
  );
}


/** 비교 목록 — 게이트가 막은 diff 를 목록에서 바로 가린다(§2.12: 믿어도 되는지가 먼저다). */
function DiffsTab() {
  const list = useAsync((signal) => riskApi.listDiffs({ limit: 50 }, { signal }), []);
  const rows = list.data?.diffs ?? [];
  const columns: Column<DiffListRow>[] = [
    {
      key: "id",
      header: "비교",
      cell: (d) => <Link to={`/compare?diff=${encodeURIComponent(d.id)}`}>{d.id.slice(0, 12)}</Link>,
      nowrap: true,
    },
    {
      key: "state",
      header: "상태",
      nowrap: true,
      cell: (d) =>
        d.blocked ? (
          <Badge tone="bad">차단 {d.gates_failed.join("·")}</Badge>
        ) : d.summary_status === "lint_failed" ? (
          <Badge tone="warn">요약 린트 실패</Badge>
        ) : (
          <Badge tone="ok">열람 가능</Badge>
        ),
    },
    {
      key: "pair",
      header: "짝",
      nowrap: true,
      cell: (d) => (d.pair_kind === "cross_project" ? "다른 과제" : "같은 과제 리비전"),
    },
    { key: "base", header: "base", cell: (d) => <code>{d.base_snapshot_id.slice(0, 10)}</code>, nowrap: true },
    { key: "target", header: "target", cell: (d) => <code>{d.target_snapshot_id.slice(0, 10)}</code>, nowrap: true },
    { key: "created", header: "만든 때", cell: (d) => fmtEpoch(d.created_at), nowrap: true },
  ];
  return (
    <SectionCard
      title="비교"
      subtitle={list.data ? `${list.data.total}건 — 최신순` : undefined}
      actions={<Link to="/compare">두 스냅샷을 골라 비교하기</Link>}
    >
      <ErrorBanner error={list.error} onRetry={list.reload} />
      {list.loading && !list.data ? <LoadingBlock /> : null}
      {list.data && rows.length === 0 ? (
        <EmptyBlock title="비교가 아직 없습니다." hint="스냅샷 두 개를 골라 비교를 만들면 여기 쌓입니다." />
      ) : null}
      {rows.length > 0 ? <DataTable columns={columns} rows={rows} rowKey={(d) => d.id} /> : null}
    </SectionCard>
  );
}

/** 타깃 목록 — 진행도와 판정을 한 줄에 둔다(목록에서 안 보이면 타깃마다 들어가 봐야 한다). */
function TargetsTab() {
  const [withClosed, setWithClosed] = useState(false);
  const list = useAsync(
    (signal) => riskApi.listTargets({ include_superseded: withClosed, limit: 50 }, { signal }),
    [withClosed],
  );
  const rows = list.data?.targets ?? [];
  const columns: Column<TargetListRow>[] = [
    {
      key: "key",
      header: "타깃",
      cell: (t) => <Link to={`/targets/${encodeURIComponent(t.target_key)}`}>{t.target_key}</Link>,
      nowrap: true,
    },
    { key: "level", header: "level", cell: (t) => <LevelBadge value={t.level} />, nowrap: true },
    {
      key: "coverage",
      header: "진행",
      align: "right",
      nowrap: true,
      cell: (t) =>
        t.coverage_pct === null ? (
          <span className="text-muted-foreground">편성 전</span>
        ) : (
          `${fmtPct(t.coverage_pct)} / ${t.roster_size}석`
        ),
    },
    {
      key: "verdict",
      header: "verdict",
      nowrap: true,
      cell: (t) => <VerdictBadge value={t.verdict_final ?? t.verdict_candidate ?? "undetermined"} />,
    },
    {
      key: "reports",
      header: "보고서",
      align: "right",
      nowrap: true,
      // `report_ids: string[]` 은 서버가 **센** 값이다 — 빈 배열은 '아직 없다' 는 확정 사실이고
      // '모름' 이 아니다. 그래서 — 가 아니라 0 을 흐리게 그린다(§ 미측정과 0 을 섞지 않는다).
      cell: (t) =>
        t.report_ids.length ? String(t.report_ids.length) : <span className="text-muted-foreground">0</span>,
    },
    {
      key: "state",
      header: "",
      nowrap: true,
      cell: (t) => (t.superseded_by ? <Badge tone="muted">닫힘</Badge> : null),
    },
    { key: "updated", header: "갱신", cell: (t) => fmtEpoch(t.updated_at), nowrap: true },
  ];
  return (
    <SectionCard
      title="타깃"
      subtitle={list.data ? `${list.data.total}건 — 최신순` : undefined}
      actions={
        <label className="flex flex-wrap items-center gap-2 text-sm">
          <input type="checkbox" checked={withClosed} onChange={(e) => setWithClosed(e.target.checked)} />
          닫힌 타깃 포함
        </label>
      }
    >
      <ErrorBanner error={list.error} onRetry={list.reload} />
      {list.loading && !list.data ? <LoadingBlock /> : null}
      {list.data && rows.length === 0 ? (
        <EmptyBlock
          title={withClosed ? "타깃이 없습니다." : "열려 있는 타깃이 없습니다."}
          hint="스냅샷이나 비교에서 '타깃 만들기' 를 누르면 여기 쌓입니다."
        />
      ) : null}
      {rows.length > 0 ? <DataTable columns={columns} rows={rows} rowKey={(t) => t.target_key} /> : null}
    </SectionCard>
  );
}

/** 보고서 목록 — 앱은 전문을 갖지 않는다(§5.3). RA 포인터와 반영 상태만 보인다. */
function ReportsTab() {
  const list = useAsync((signal) => riskApi.listReports({ limit: 50 }, { signal }), []);
  const rows = list.data?.reports ?? [];
  const columns: Column<ReportListRow>[] = [
    { key: "ref", header: "보고서", cell: (r) => <code>{r.ref}</code>, nowrap: true },
    {
      key: "target",
      header: "타깃",
      cell: (r) => <Link to={`/targets/${encodeURIComponent(r.target_key)}`}>{r.target_key}</Link>,
      nowrap: true,
    },
    { key: "level", header: "level", cell: (r) => <LevelBadge value={r.level} />, nowrap: true },
    {
      key: "verdict",
      header: "verdict",
      nowrap: true,
      cell: (r) => <VerdictBadge value={r.verdict_final ?? "undetermined"} />,
    },
    {
      key: "ra",
      header: "RA 반영",
      nowrap: true,
      cell: (r) =>
        // `ra_state: string | null` — null 은 서버가 '아니다' 라고 한 게 아니라 **아직 모르는** 것이다.
        // 0 이나 '-' 로 그리면 '반영 안 됨' 이라는 없는 판정이 생긴다.
        r.ra_state ? (
          <Badge tone={r.ra_state === "synced" ? "ok" : "warn"}>{r.ra_state}</Badge>
        ) : (
          <span className="text-muted-foreground">모름</span>
        ),
    },
    { key: "updated", header: "갱신", cell: (r) => fmtEpoch(r.updated_at), nowrap: true },
  ];
  return (
    <SectionCard title="보고서" subtitle={list.data ? `${list.data.total}건` : undefined}>
      <ErrorBanner error={list.error} onRetry={list.reload} />
      {list.loading && !list.data ? <LoadingBlock /> : null}
      {list.data && rows.length === 0 ? (
        <EmptyBlock
          title="보고서가 아직 없습니다."
          hint="타깃이 C1 이상으로 닫히면 통합 보고서가 만들어지고 그 포인터가 여기 쌓입니다."
        />
      ) : null}
      {rows.length > 0 ? <DataTable columns={columns} rows={rows} rowKey={(r) => r.ref} /> : null}
      <p className="text-sm text-muted-foreground">전문은 Report Archive 가 갖습니다 — 앱은 사본을 두지 않습니다.</p>
    </SectionCard>
  );
}
