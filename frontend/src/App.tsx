// 앱 셸 — HashRouter 라우트 6개와 상단 내비. 딥링크는 /apps/hwax_risk/#/targets/<key> 형식이라 새로고침에 안전하다(계획 §8.2.4).
import { HashRouter, Link, NavLink, Route, Routes, useParams } from "react-router-dom";
import RiskHomePage from "./pages/RiskHomePage";
import ProjectPage from "./pages/ProjectPage";
import SnapshotPage from "./pages/SnapshotPage";
import ComparePage from "./pages/ComparePage";
import TargetPage from "./pages/TargetPage";
import CurationQueuePage from "./pages/CurationQueuePage";
import SettingsPage from "./pages/SettingsPage";
import { SectionCard } from "./components/SectionCard";
import { EmptyBlock } from "./components/StateBlocks";

const NAV = [
  { to: "/", label: "과제", end: true },
  { to: "/compare", label: "비교" },
  { to: "/curation", label: "큐레이션" },
  { to: "/settings", label: "설정" },
];

/** `#/snapshots/<id>` 딥링크 — 과제 화면의 `?snapshot=` 과 같은 화면을 단독으로 연다. */
function SnapshotRoute() {
  const { id } = useParams<{ id: string }>();
  if (!id) {
    return (
      <SectionCard title="스냅샷">
        <EmptyBlock title="스냅샷을 찾을 수 없습니다." hint="주소에 snapshot_id 가 없습니다." />
      </SectionCard>
    );
  }
  return <SnapshotPage snapshotId={id} />;
}

/** 어디에도 걸리지 않은 주소 — 빈 화면 대신 안내로 떨어진다(§8.2.4 오류 규약). */
function NotFoundPage() {
  return (
    <SectionCard title="없는 주소입니다.">
      <EmptyBlock
        title="이 주소에 해당하는 화면이 없습니다."
        hint="딥링크는 #/projects/<id> · #/snapshots/<id> · #/compare · #/targets/<key> · #/curation · #/settings 형식입니다."
        action={
          <Link className="rr-btn rr-btn-primary" to="/">
            과제 목록으로
          </Link>
        }
      />
    </SectionCard>
  );
}

function Shell() {
  return (
    <div className="rr-app">
      <header className="rr-topbar">
        <NavLink to="/" className="rr-brand">
          HWAX 설계 리스크 심사
        </NavLink>
        <nav className="rr-nav">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? "rr-nav-link rr-nav-link-active" : "rr-nav-link")}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="rr-main">
        <Routes>
          <Route path="/" element={<RiskHomePage />} />
          <Route path="/projects/:id" element={<ProjectPage />} />
          <Route path="/snapshots/:id" element={<SnapshotRoute />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/targets/:key" element={<TargetPage />} />
          <Route path="/curation" element={<CurationQueuePage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <HashRouter>
      <Shell />
    </HashRouter>
  );
}
