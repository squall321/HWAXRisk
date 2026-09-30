// 커맨드 팔레트(⌘K) — 이 앱의 진입점은 id 다(과제·스냅샷·타깃·비교 모두 키로 열린다). 그 id 를
// 주소창에 손으로 조립하지 않게 한 곳에서 찾아 연다. Report Archive 와 같은 조작법이다.
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Command } from "cmdk";
import { FileDiff, FolderOpen, LayoutGrid, ListChecks, Settings, Target } from "lucide-react";
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import { cn } from "../lib/cn";

/** 화면 이동은 목록을 기다리지 않는다 — 팔레트를 열자마자 쓸 수 있어야 한다. */
const ROUTES = [
  { to: "/", label: "과제 목록", icon: LayoutGrid },
  { to: "/compare", label: "비교 만들기", icon: FileDiff },
  { to: "/curation", label: "큐레이션 큐", icon: ListChecks },
  { to: "/settings", label: "설정 · 자격", icon: Settings },
];

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // 목록은 팔레트를 **열 때만** 부른다 — 안 쓰는 사람에게 요청을 내보내지 않는다.
  const projects = useAsync((signal) => (open ? riskApi.listProjects({ signal }) : Promise.resolve(null)), [open]);
  const targets = useAsync(
    (signal) => (open ? riskApi.listTargets({ limit: 30 }, { signal }) : Promise.resolve(null)),
    [open],
  );

  const items = useMemo(() => {
    const out: Array<{ key: string; label: string; hint?: string; to: string; icon: typeof Target }> = [];
    for (const p of projects.data?.projects ?? []) {
      out.push({ key: `p:${p.id}`, label: `${p.code} · ${p.name}`, hint: "과제", to: `/projects/${p.id}`, icon: FolderOpen });
    }
    for (const t of targets.data?.targets ?? []) {
      out.push({
        key: `t:${t.target_key}`,
        label: t.target_key,
        hint: `타깃 · ${t.level}`,
        to: `/targets/${encodeURIComponent(t.target_key)}`,
        icon: Target,
      });
    }
    return out;
  }, [projects.data, targets.data]);

  function go(to: string) {
    setOpen(false);
    navigate(to);
  }

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-foreground/25 p-4 pt-[12vh]"
      onClick={() => setOpen(false)}
      role="presentation"
    >
      <Command
        label="명령 팔레트"
        className="w-full max-w-xl overflow-hidden rounded-lg border border-border bg-popover text-popover-foreground shadow-lg outline-none focus:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <Command.Input
          autoFocus
          placeholder="과제·타깃을 찾거나 화면을 엽니다."
          className="w-full border-b border-border bg-transparent px-4 py-3 text-sm outline-none focus:outline-none focus:ring-0 placeholder:text-muted-foreground"
        />
        <Command.List className="max-h-[52vh] overflow-y-auto p-1.5">
          <Command.Empty className="px-3 py-6 text-center text-sm text-muted-foreground">
            찾는 것이 없습니다.
          </Command.Empty>
          <Command.Group heading="이동" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-muted-foreground">
            {ROUTES.map((r) => (
              <PaletteRow key={r.to} icon={r.icon} label={r.label} onSelect={() => go(r.to)} />
            ))}
          </Command.Group>
          {items.length > 0 ? (
            <Command.Group heading="열기" className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:text-muted-foreground">
              {items.map((item) => (
                <PaletteRow
                  key={item.key}
                  icon={item.icon}
                  label={item.label}
                  hint={item.hint}
                  onSelect={() => go(item.to)}
                />
              ))}
            </Command.Group>
          ) : null}
          {projects.loading || targets.loading ? (
            <div className="px-3 py-3 text-xs text-muted-foreground">목록을 읽는 중.</div>
          ) : null}
        </Command.List>
      </Command>
    </div>
  );
}

function PaletteRow({
  icon: Icon,
  label,
  hint,
  onSelect,
}: {
  icon: typeof Target;
  label: string;
  hint?: string;
  onSelect: () => void;
}) {
  return (
    <Command.Item
      value={`${label} ${hint ?? ""}`}
      onSelect={onSelect}
      className={cn(
        "flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm",
        "data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground",
      )}
    >
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      <span className="truncate">{label}</span>
      {hint ? <span className="ml-auto shrink-0 text-xs text-muted-foreground">{hint}</span> : null}
    </Command.Item>
  );
}
