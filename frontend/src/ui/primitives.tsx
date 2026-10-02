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

export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, ...props }, ref) => (
    // 네이티브 화살표를 지웠으므로 직접 그린다 — 지우기만 하면 '열리는 것' 이라는 신호가 사라진다.
    <select
      ref={ref}
      className={cn(
        controlClass,
        "appearance-none bg-[length:1rem] bg-[right_0.5rem_center] bg-no-repeat pr-8",
        "bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A//www.w3.org/2000/svg%22%20" +
          "viewBox%3D%220%200%2024%2024%22%20fill%3D%22none%22%20stroke%3D%22%23888%22%20stroke-width%3D%222%22" +
          "%3E%3Cpath%20d%3D%22m6%209%206%206%206-6%22/%3E%3C/svg%3E')]",
        className,
      )}
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
