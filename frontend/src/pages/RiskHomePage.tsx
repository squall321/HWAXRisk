// 홈 화면 — 상단 탭 4개(과제·비교·타깃·보고서)·박스 자격 배너·과제 카드 그리드·과제 등록 폼(계획 §8.2.4 RiskHomePage 행).
import { useState } from "react";
import { Link } from "react-router-dom";
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { CardGrid, SectionCard } from "../components/SectionCard";
import { EmptyBlock, ErrorBanner, LoadingBlock, NotReadyBlock } from "../components/StateBlocks";
import { LevelBadge, SourceStatusBadge } from "../components/Badge";
import { fmtEpoch, fmtPct } from "../format";
import type { ProjectCard, SourceKind } from "../types";

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

/** 홈 상단 탭 4개. 과제 말고는 서버 목록 경로가 아직 없어 자리만 남긴다. */
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

      <div className="rr-row" role="tablist" aria-label="홈 탭">
        {HOME_TABS.map((item) => (
          <button
            key={item.tab}
            type="button"
            role="tab"
            aria-selected={tab === item.tab}
            className={tab === item.tab ? "rr-btn rr-btn-primary" : "rr-btn"}
            onClick={() => setTab(item.tab)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === "diffs" ? (
        <SectionCard title="비교(diff 목록)" subtitle="목록 경로가 아직 없습니다.">
          <NotReadyBlock what="diff 목록" />
          <Link to="/compare">두 스냅샷을 골라 비교하기</Link>
        </SectionCard>
      ) : null}
      {tab === "targets" ? (
        <SectionCard title="타깃" subtitle="타깃 목록 경로가 아직 없습니다.">
          <NotReadyBlock what="타깃 목록" />
          <p className="rr-muted">지금은 과제 상세의 타깃 표에서 엽니다.</p>
        </SectionCard>
      ) : null}
      {tab === "reports" ? (
        <SectionCard title="보고서" subtitle="보고서 목록 경로가 아직 없습니다.">
          <NotReadyBlock what="보고서 목록" />
        </SectionCard>
      ) : null}

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
