// shadcn/ui 기본 조각 — Report Archive 와 같은 언어를 쓰되 이 앱이 실제로 쓰는 것만 둔다(§8.2.4)
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "../lib/cn";

/* ── Button ────────────────────────────────────────────────────────────────── */
// tone 이 아니라 variant 로 쓴다(shadcn 관례). 판정 색 ok·warn 은 버튼에 두지 않는다 —
// 버튼은 '무엇이 일어나는가' 이고 판정은 배지가 말한다.
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md text-sm font-medium " +
    "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
    "focus-visible:ring-offset-2 focus-visible:ring-offset-background " +
    "disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        outline: "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: { sm: "h-8 px-3", md: "h-9 px-4", icon: "h-9 w-9" },
    },
    defaultVariants: { variant: "default", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
  },
);
Button.displayName = "Button";

/* ── Card ──────────────────────────────────────────────────────────────────── */
// asChild 는 시맨틱을 호출자에게 넘기기 위한 것이다 — §8.2.4 의 '구역' 은 <section> 이어야 하는데
// 카드가 div 를 강제하면 화면 구조가 스크린리더에게 평평해진다.
export function Card({
  className,
  asChild = false,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "div";
  return <Comp className={cn("rounded-lg border border-border bg-card text-card-foreground", className)} {...props} />;
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex flex-col gap-1 border-b border-border px-5 py-4", className)} {...props} />;
}

// `m-0` 은 장식이 아니다 — preflight 를 꺼 둬서 <h2>·<p> 의 UA margin(13.28px·14px, 실측)이
// 그대로 살아 있다. 빼면 카드 머리말이 헐겁게 벌어진다. 새 조각에서 제목·문단을 쓸 때는 늘 붙인다.
export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("m-0 text-base font-semibold leading-none tracking-tight", className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("m-0 text-sm text-muted-foreground", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 py-4", className)} {...props} />;
}

/* ── Chip ──────────────────────────────────────────────────────────────────── */
// 판정을 말하는 조각. 이 앱에서 가장 많이 쓰이므로 tone 을 명시적으로 나눈다 —
// '모름(미측정)' 을 '괜찮다' 나 '나쁘다' 와 같은 색으로 쓰지 않는다(null 은 0 이 아니다).
const chipVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        ok: "border-transparent bg-ok/15 text-ok",
        warn: "border-transparent bg-warn/20 text-warn-foreground dark:text-warn",
        bad: "border-transparent bg-destructive/15 text-destructive",
        info: "border-transparent bg-primary/12 text-primary",
        /** 모름·미측정·해당 없음. 값이 없다는 사실 자체가 정보다. */
        muted: "border-border bg-muted text-muted-foreground",
        /** 어휘를 모르는 저장 값. 색으로 판단을 지어내지 않고 글자만 보인다(§8.2.4 '배지 = 저장 값'). */
        neutral: "border-border bg-background text-foreground",
      },
    },
    defaultVariants: { tone: "muted" },
  },
);

export function Chip({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof chipVariants>) {
  return <span className={cn(chipVariants({ tone }), className)} {...props} />;
}

/* ── 작은 것들 ─────────────────────────────────────────────────────────────── */
export function Mono({ className, ...props }: React.HTMLAttributes<HTMLElement>) {
  return <code className={cn("rounded bg-muted px-1 py-0.5 font-mono text-[0.8em]", className)} {...props} />;
}

/* ── 화면 뼈대 ─────────────────────────────────────────────────────────────── */
// 다섯 상세 화면이 똑같이 필요로 하는 것만 둔다. 화면마다 따로 지으면 같은 앱 안에서 머리말이
// 다섯 가지가 되고, 그게 '제품 같지 않다' 의 실체다.

/** 화면 맨 위 한 줄 — 어디에 있는지(`crumb`) · 무엇인지(`title`) · 지금 할 수 있는 것(`actions`). */
export function PageHeader({
  crumb,
  title,
  subtitle,
  actions,
  as: Heading = "h1",
}: {
  /** 상위 화면으로 돌아가는 링크·경로. 상세 화면은 id 로 들어오므로 돌아갈 길이 늘 보여야 한다. */
  crumb?: React.ReactNode;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  /**
   * 제목의 수준. 기본 `h1` 이지만 **다른 화면 안에 끼워 그려지는 화면은 `h2` 로 내린다** —
   * 그러지 않으면 품고 있는 화면의 문서 제목이 끼워진 쪽 이름으로 바뀐다(SnapshotPage 가 그랬다).
   */
  as?: "h1" | "h2";
}) {
  return (
    <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex flex-col gap-1">
        {crumb ? <div className="flex items-center gap-1 text-xs text-muted-foreground">{crumb}</div> : null}
        <Heading className="m-0 truncate text-xl font-semibold tracking-tight">{title}</Heading>
        {subtitle ? <div className="text-sm text-muted-foreground">{subtitle}</div> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** 구역 탭. 홈이 인라인으로 굴리던 것을 꺼내 왔다 — 화면마다 다시 지으면 조작법이 화면마다 달라진다. */
export function TabBar<T extends string>({
  tabs,
  value,
  onChange,
  label,
  className,
  idPrefix = "tab",
}: {
  tabs: ReadonlyArray<{ tab: T; label: React.ReactNode; count?: number | null }>;
  value: T;
  onChange: (tab: T) => void;
  /** 스크린리더용 탭 묶음 이름. */
  label: string;
  className?: string;
  /** 한 화면에 탭 묶음이 둘 이상일 때 id 가 겹치지 않게. */
  idPrefix?: string;
}) {
  // role="tab" 을 쓰면 WAI-ARIA 가 좌우 화살표 이동을 약속한다 — 약속만 하고 안 지키면
  // 키보드 사용자에게는 '탭처럼 보이는데 탭처럼 안 되는 것' 이 된다(역검토가 세 화면에서 잡았다).
  function move(delta: number) {
    const i = tabs.findIndex((t) => t.tab === value);
    if (i === -1) return;
    const next = tabs[(i + delta + tabs.length) % tabs.length];
    onChange(next.tab);
    // 초점도 같이 옮긴다 — 안 그러면 화살표를 눌러도 읽히는 것은 그대로다.
    document.getElementById(`${idPrefix}-${next.tab}`)?.focus();
  }
  return (
    <div
      // 세그먼티드 컨트롤 — 버튼 n 개가 아니라 '지금 어디를 보고 있나' 를 말하는 한 덩이다.
      className={cn(
        "mb-4 inline-flex w-fit flex-wrap items-center gap-0.5 rounded-lg border border-border bg-muted/50 p-0.5",
        className,
      )}
      role="tablist"
      aria-label={label}
      onKeyDown={(event) => {
        if (event.key === "ArrowRight") { event.preventDefault(); move(1); }
        else if (event.key === "ArrowLeft") { event.preventDefault(); move(-1); }
      }}
    >
      {tabs.map((item) => (
        <button
          key={item.tab}
          id={`${idPrefix}-${item.tab}`}
          type="button"
          role="tab"
          aria-selected={value === item.tab}
          aria-controls={`${idPrefix}panel-${item.tab}`}
          // 선택된 탭만 Tab 키 순서에 둔다(roving tabindex) — 탭 묶음은 한 정거장이다.
          tabIndex={value === item.tab ? 0 : -1}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors",
            value === item.tab
              ? "bg-background font-medium text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
          onClick={() => onChange(item.tab)}
        >
          {item.label}
          {/* 0 과 '모름' 을 구분한다 — count 가 null 이면 숫자 자리를 아예 안 만든다. */}
          {item.count === null || item.count === undefined ? null : (
            <span className="text-xs tabular-nums opacity-60">{item.count}</span>
          )}
        </button>
      ))}
    </div>
  );
}

/**
 * 탭 한 칸의 내용. **마운트를 유지하고 보이는 것만 바꾼다** — `{tab === "x" ? <Card/> : null}` 로 쓰면 안 된다.
 *
 * 왜 이게 공용이어야 하나. 화면을 탭으로 묶으면서 조건부 렌더를 쓰면 **자리를 옮기는 작업이 입력의 수명까지
 * 바꾼다.** 실제로 그렇게 깨진 것 넷을 역검토가 잡았다 — ㉮ `iface-ledger` 의 저장 전 행은 메모리에만 있고
 * 서버에서 다시 읽을 경로가 없는데 탭을 한 번 바꾸면 사라진다 · ㉯ 등록부의 상태 변경 폼(사유·근거 참조)과
 * 판정 메모가 같은 이유로 날아간다 · ㉰ `credential === "service"` 경고가 탭 전환으로 사라진다 ·
 * ㉱ **브리프 탭은 재진입마다 `GET /brief` 가 돌고 그 경로가 `issue_brief_token` 으로 `brief_token_hash` 를
 * 덮어써, 사용자가 이미 복사해 둔 토큰이 조용히 무효가 된다**(routes.py `get_brief` → `issue_brief_token`).
 *
 * 숨기는 비용은 DOM 이 남는 것뿐이고, 날리는 비용은 사람이 친 글자다. 그래서 기본을 숨김으로 둔다.
 * 정말 매번 새로 받아야 하는 칸이 있으면 그 칸만 호출자가 조건부로 쓰고 **왜 그런지 주석을 단다.**
 */
export function TabPanel({
  active,
  children,
  /** 짝이 되는 탭의 값. TabBar 와 같은 `idPrefix` 를 주면 aria-controls 로 이어진다. */
  tab,
  idPrefix = "tab",
}: {
  active: boolean;
  children: React.ReactNode;
  tab?: string;
  idPrefix?: string;
}) {
  // `hidden` 은 보조기술에게도 숨긴다 — 안 보이는 칸이 스크린리더에서만 읽히는 일이 없게.
  return (
    <div
      hidden={!active}
      role="tabpanel"
      id={tab ? `${idPrefix}panel-${tab}` : undefined}
      aria-labelledby={tab ? `${idPrefix}-${tab}` : undefined}
    >
      {children}
    </div>
  );
}

/** 한 줄 배너. 오류·정보·경고를 같은 모양으로 말한다(ErrorBanner·GateBanner 가 이것을 쓴다). */
export function Banner({
  tone = "error",
  title,
  detail,
  children,
  live = tone === "error" ? "alert" : "status",
}: {
  tone?: "error" | "info" | "warn";
  title: React.ReactNode;
  detail?: React.ReactNode;
  /** 오른쪽에 붙는 버튼·링크. */
  children?: React.ReactNode;
  /**
   * 보조기기에게 어떻게 읽힐지. `alert` 는 **하던 말을 끊고** 읽고 `status` 는 정중히 기다린다.
   * 기본은 톤을 따른다 — 오류만 끼어들 자격이 있다. '등록했습니다' 같은 성공 알림이나 행을 누를
   * 때마다 뜨는 안내를 `alert` 로 두면 스크린리더 사용자에게는 소음이 된다(역검토가 둘 다 잡았다).
   */
  live?: "alert" | "status" | "none";
}) {
  const skin =
    tone === "error"
      ? "border-destructive/30 bg-destructive/10 text-destructive"
      : tone === "warn"
        ? "border-warn/30 bg-warn/15 text-warn-foreground dark:text-warn"
        : "border-primary/25 bg-primary/8 text-foreground";
  return (
    <div className={cn("mb-3 flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-md border px-3 py-2 text-sm", skin)}
         role={live === "none" ? undefined : live}>
      <span className="font-medium">{title}</span>
      {detail ? <span className="text-foreground/75">{detail}</span> : null}
      {children ? <span className="ml-auto">{children}</span> : null}
    </div>
  );
}

/* ── 입력 ──────────────────────────────────────────────────────────────────── */
// index.css 의 `:where(input…)` 리셋이 테두리·배경을 0 으로 깎아 두므로(네이티브 크롬 제거)
// 여기서 명시적으로 되돌린다. `:where()` 는 특이도 0 이라 이 클래스가 항상 이긴다.
const controlClass =
  "h-9 w-full max-w-full rounded-md border border-input bg-background px-3 py-1 text-sm " +
  "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background " +
  "disabled:cursor-not-allowed disabled:opacity-50";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => <input ref={ref} className={cn(controlClass, className)} {...props} />,
);
Input.displayName = "Input";

/** `<select>` 의 펼침 화살표(lucide chevron-down 과 같은 모양). currentColor 를 못 쓰므로 토큰 대신 중립 회색이다. */
const SELECT_ARROW =
  "url(\"data:image/svg+xml;charset=utf-8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' " +
  "fill='none' stroke='%23888' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>" +
  "<path d='m6 9 6 6 6-6'/></svg>\")";

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => (
    // 네이티브 화살표를 지웠으므로 직접 그린다 — 지우기만 하면 '열리는 것' 이라는 신호가 사라진다.
    // 배경 이미지는 `style` 로 준다. Tailwind 임의값(`bg-[url(…)]`)으로 쓰면 스캐너가 **소스에 그대로
    // 적힌 문자열**만 보므로, 길어서 `+` 로 쪼개는 순간 규칙이 아예 생성되지 않는다(실제로 빌드 CSS 에
    // `svg+xml` 이 0건이었고 화살표 없는 네모만 남았다 — 역검토가 잡았다).
    <select
      ref={ref}
      className={cn(controlClass, "appearance-none bg-no-repeat pr-8", className)}
      style={{ backgroundImage: SELECT_ARROW, backgroundPosition: "right 0.5rem center", backgroundSize: "1rem", ...props.style }}
      {...props}
    />
  ),
);
Select.displayName = "Select";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea ref={ref} className={cn(controlClass, "h-auto min-h-[5rem] py-2", className)} {...props} />
  ),
);
Textarea.displayName = "Textarea";

/** 라벨 + 입력 한 칸. `error` 가 있으면 그 자리에서 말한다(제출 뒤 어딘가에서 말하지 않는다). */
export function FormField({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: React.ReactNode;
  /** 형식·상한 같은 보조 설명. */
  hint?: React.ReactNode;
  error?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("flex flex-col gap-1.5 text-sm", className)}>
      <span className="flex flex-wrap items-baseline gap-1.5 text-xs font-medium text-muted-foreground">
        {label}
        {hint ? <span className="font-normal opacity-75">{hint}</span> : null}
      </span>
      {children}
      {error ? <span className="text-xs text-destructive">{error}</span> : null}
    </label>
  );
}

/** 입력 칸을 자동으로 흘려 넣는 격자(좁으면 1열). 기존 `.rr-form-grid` 와 같은 14rem 기준이다. */
export function FormGrid({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(14rem,1fr))]", className)}>
      {children}
    </div>
  );
}

/** 카드 **안**의 작은 묶음(기존 `.rr-panel`). 카드가 구역이면 이것은 그 안의 한 덩이다. */
export function SubPanel({
  title,
  actions,
  children,
  className,
}: {
  title?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-2 rounded-md border border-border bg-muted/40 p-3", className)}>
      {title || actions ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {title ? <h3 className="m-0 text-sm font-medium">{title}</h3> : <span />}
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </div>
  );
}

/** 라벨과 값 한 쌍. 라벨은 사람 말로 쓰고, 원시 필드명은 `hint` 로 접어 둔다. */
export function Field({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-0.5 py-1.5", className)}>
      <dt className="flex items-baseline gap-1.5 text-xs text-muted-foreground">
        {label}
        {hint ? <span className="font-mono text-[0.68rem] opacity-60">{hint}</span> : null}
      </dt>
      <dd className="m-0 text-sm">{children}</dd>
    </div>
  );
}
