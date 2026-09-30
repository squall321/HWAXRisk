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
export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-lg border border-border bg-card text-card-foreground", className)} {...props} />;
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
