// 앱 셸 — 사이드바·커맨드 팔레트(⌘K)·HashRouter 라우트 7개. 딥링크는 /apps/hwax_risk/#/targets/<key> 형식이라 새로고침에 안전하다(계획 §8.2.4).
import { HashRouter, Link, NavLink, Route, Routes, useParams } from "react-router-dom";
import { FileDiff, LayoutGrid, ListChecks, Settings as SettingsIcon } from "lucide-react";
import { CommandPalette } from "./ui/CommandPalette";
import { cn } from "./lib/cn";
import RiskHomePage from "./pages/RiskHomePage";
import ProjectPage from "./pages/ProjectPage";
import SnapshotPage from "./pages/SnapshotPage";
import ComparePage from "./pages/ComparePage";
import TargetPage from "./pages/TargetPage";
import CurationQueuePage from "./pages/CurationQueuePage";
import SettingsPage from "./pages/SettingsPage";
import { SectionCard } from "./components/SectionCard";
import { EmptyBlock } from "./components/StateBlocks";

// 사이드바 — 아이콘은 글자를 대신하지 않고 **거든다**(글자를 지우면 어느 화면인지 못 읽는 사람이 생긴다).
const NAV = [
  { to: "/", label: "과제", end: true, icon: LayoutGrid },
  { to: "/compare", label: "비교", icon: FileDiff },
  { to: "/curation", label: "큐레이션", icon: ListChecks },
  { to: "/settings", label: "설정", icon: SettingsIcon },
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
    <div className="flex min-h-screen bg-background text-foreground">
      <CommandPalette />
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-border bg-card sm:flex">
        <NavLink to="/" className="flex flex-col gap-0.5 border-b border-border px-4 py-4 no-underline">
          <span className="text-sm font-semibold leading-tight text-foreground">설계 리스크 심사</span>
          <span className="text-xs text-muted-foreground">HWAX Risk Review</span>
        </NavLink>
        <nav className="flex flex-col gap-0.5 p-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm no-underline transition-colors",
                  isActive
                    ? "bg-accent font-medium text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
                )
              }
            >
              <item.icon className="size-4 shrink-0" />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <p className="mt-auto px-4 py-3 text-xs text-muted-foreground">
          <kbd className="rounded border border-border bg-muted px-1 py-0.5 font-mono text-[0.7rem]">⌘K</kbd> 로
          과제·타깃을 찾습니다.
        </p>
      </aside>
      {/* 좁은 화면에서는 사이드바를 상단 줄로 접는다 — 숨기면 이동할 방법이 사라진다. */}
      <nav className="fixed inset-x-0 top-0 z-40 flex gap-1 border-b border-border bg-card/95 px-2 py-1.5 backdrop-blur sm:hidden">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "flex flex-1 flex-col items-center gap-0.5 rounded-md py-1 text-[0.7rem] no-underline",
                isActive ? "bg-accent text-accent-foreground" : "text-muted-foreground",
              )
            }
          >
            <item.icon className="size-4" />
            {item.label}
          </NavLink>
        ))}
      </nav>
      <main className="mx-auto flex w-full max-w-[1180px] flex-col gap-4 px-4 pb-10 pt-14 sm:pt-6">
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
