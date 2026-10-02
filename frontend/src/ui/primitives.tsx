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

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("text-base font-semibold leading-none tracking-tight", className)} {...props} />;
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...props} />;
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
}: {
  /** 상위 화면으로 돌아가는 링크·경로. 상세 화면은 id 로 들어오므로 돌아갈 길이 늘 보여야 한다. */
  crumb?: React.ReactNode;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex flex-col gap-1">
        {crumb ? <div className="flex items-center gap-1 text-xs text-muted-foreground">{crumb}</div> : null}
        <h1 className="m-0 truncate text-xl font-semibold tracking-tight">{title}</h1>
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
}: {
  tabs: ReadonlyArray<{ tab: T; label: React.ReactNode; count?: number | null }>;
  value: T;
  onChange: (tab: T) => void;
  /** 스크린리더용 탭 묶음 이름. */
  label: string;
  className?: string;
}) {
  return (
    <div
      // 세그먼티드 컨트롤 — 버튼 n 개가 아니라 '지금 어디를 보고 있나' 를 말하는 한 덩이다.
      className={cn(
        "mb-4 inline-flex w-fit flex-wrap items-center gap-0.5 rounded-lg border border-border bg-muted/50 p-0.5",
        className,
      )}
      role="tablist"
      aria-label={label}
    >
      {tabs.map((item) => (
        <button
          key={item.tab}
          type="button"
          role="tab"
          aria-selected={value === item.tab}
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

/** 한 줄 배너. 오류·정보·경고를 같은 모양으로 말한다(ErrorBanner·GateBanner 가 이것을 쓴다). */
export function Banner({
  tone = "error",
  title,
  detail,
  children,
}: {
  tone?: "error" | "info" | "warn";
  title: React.ReactNode;
  detail?: React.ReactNode;
  /** 오른쪽에 붙는 버튼·링크. */
  children?: React.ReactNode;
}) {
  const skin =
    tone === "error"
      ? "border-destructive/30 bg-destructive/10 text-destructive"
      : tone === "warn"
        ? "border-warn/30 bg-warn/15 text-warn-foreground dark:text-warn"
        : "border-primary/25 bg-primary/8 text-foreground";
  return (
    <div className={cn("mb-3 flex flex-wrap items-baseline gap-x-2 gap-y-1 rounded-md border px-3 py-2 text-sm", skin)}
         role="alert">
      <span className="font-medium">{title}</span>
      {detail ? <span className="text-foreground/75">{detail}</span> : null}
      {children ? <span className="ml-auto">{children}</span> : null}
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
