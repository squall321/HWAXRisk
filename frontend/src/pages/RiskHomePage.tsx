// 홈 화면 — 상단 탭 4개(과제·비교·타깃·보고서)·박스 자격 배너·과제 카드 그리드·과제 등록 폼(계획 §8.2.4 RiskHomePage 행).
import { useState } from "react";
import { Link } from "react-router-dom";
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { CardGrid, SectionCard } from "../components/SectionCard";
import { EmptyBlock, ErrorBanner, LoadingBlock } from "../components/StateBlocks";
import { Badge, LevelBadge, SourceStatusBadge, VerdictBadge } from "../components/Badge";
import { DataTable } from "../components/DataTable";
import type { Column } from "../components/DataTable";
import { cn } from "../lib/cn";
import { fmtEpoch, fmtPct } from "../format";
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

function ProjectTile({ card }: { card: ProjectCard }) {
  return (
    <Link to={`/projects/${encodeURIComponent(card.id)}`} className="rr-tile">
      <div className="rr-row rr-tile-head">
        <strong>{card.code}</strong>
        <LevelBadge value={card.level} />
      </div>
      <div className="rr-tile-name">{card.name}</div>
      <div className="rr-muted">{card.stage ?? "단계 미지정"}</div>
      <div className="rr-row">
        {CARD_KINDS.map((kind) => {
          const source = card.sources.find((s) => s.kind === kind);
          return (
            <span key={kind} className="rr-row rr-tile-source">
              <span className="rr-muted">{KIND_LABEL[kind]}</span>
              <SourceStatusBadge value={source?.status ?? "unlinked"} />
            </span>
          );
        })}
      </div>
      <div className="rr-muted">최근 스냅샷 {fmtEpoch(card.last_snapshot_at)}</div>
      <div className="rr-muted">
        열린 타깃 {card.open_targets} · 커버리지 {fmtPct(card.coverage_pct)}
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
    <form className="rr-form" onSubmit={submit}>
      <ErrorBanner error={error} />
      {notice ? <p className="rr-muted">{notice}</p> : null}
      <div className="rr-form-grid">
        <label className="rr-field">
          <span>code (≤40)</span>
          <input className="rr-input" maxLength={40} value={code} onChange={(e) => setCode(e.target.value)} />
        </label>
        <label className="rr-field">
          <span>name (≤200)</span>
          <input className="rr-input" maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="rr-field">
          <span>stage (pre · dv · pv · pra · mp + 1/2/3/r)</span>
          <input className="rr-input" value={stage} onChange={(e) => setStage(e.target.value)} />
          {stageInvalid ? <span className="rr-error-text">형식이 맞지 않습니다.</span> : null}
        </label>
        <label className="rr-field">
          <span>predecessor_project_id (선택)</span>
          <select className="rr-select" value={predecessor} onChange={(e) => setPredecessor(e.target.value)}>
            <option value="">없음</option>
            {options.map((p) => (
              <option key={p.id} value={p.id}>
                {p.code} · {p.name}
              </option>
            ))}
          </select>
        </label>
        <label className="rr-field">
          <span>adh_scope.team</span>
          <input className="rr-input" value={team} onChange={(e) => setTeam(e.target.value)} />
        </label>
        <label className="rr-field">
          <span>adh_scope.group</span>
          <input className="rr-input" value={group} onChange={(e) => setGroup(e.target.value)} />
        </label>
      </div>
      <div className="rr-row">
        <button type="submit" className="rr-btn rr-btn-primary" disabled={!canSubmit}>
          과제 등록
        </button>
        <span className="rr-muted">adh_scope 는 자동으로 채우지 않습니다.</span>
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
        <div className="rr-banner rr-banner-error" role="alert">
          <span className="rr-banner-title">이 박스의 자격이 없습니다.</span>
          <Link to="/settings">설정</Link>
        </div>
      ) : null}

      {/* 세그먼티드 컨트롤 — 버튼 네 개가 아니라 '지금 어디를 보고 있나' 를 말하는 한 덩이다. */}
      <div
        className="inline-flex w-fit items-center gap-0.5 rounded-lg border border-border bg-muted/50 p-0.5"
        role="tablist"
        aria-label="홈 탭"
      >
        {HOME_TABS.map((item) => (
          <button
            key={item.tab}
            type="button"
            role="tab"
            aria-selected={tab === item.tab}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm transition-colors",
              tab === item.tab
                ? "bg-background font-medium text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
            onClick={() => setTab(item.tab)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "diffs" ? <DiffsTab /> : null}
      {tab === "targets" ? <TargetsTab /> : null}
      {tab === "reports" ? <ReportsTab /> : null}

      {tab === "projects" ? (
        <SectionCard
          title="과제"
          subtitle="설계 리스크 심사의 시작점입니다."
          actions={
            <button type="button" className="rr-btn" onClick={() => setFormOpen((v) => !v)}>
              {formOpen ? "등록 폼 닫기" : "과제 등록"}
            </button>
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
                <button type="button" className="rr-btn rr-btn-primary" onClick={() => setFormOpen(true)}>
                  과제 등록
                </button>
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
        t.coverage_pct === null ? <span className="rr-muted">편성 전</span> : `${fmtPct(t.coverage_pct)} / ${t.roster_size}석`,
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
      cell: (t) => (t.report_ids.length ? String(t.report_ids.length) : <span className="rr-muted">-</span>),
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
        <label className="rr-row">
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
        r.ra_state ? <Badge tone={r.ra_state === "synced" ? "ok" : "warn"}>{r.ra_state}</Badge> : <span className="rr-muted">-</span>,
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
      <p className="rr-muted">전문은 Report Archive 가 갖습니다 — 앱은 사본을 두지 않습니다.</p>
    </SectionCard>
  );
}
