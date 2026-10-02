// 화면 구역을 감싸는 카드 — §8.2.4 표의 '구역(위→아래)' 한 칸이 카드 하나다.
import type { ReactNode } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../ui/primitives";
import { cn } from "../lib/cn";

export function SectionCard({
  title,
  subtitle,
  actions,
  children,
  id,
  /** 본문 여백을 직접 잡고 싶을 때(표를 카드 끝까지 붙이는 경우 등). */
  bodyClassName,
}: {
  title: ReactNode;
  /** 제목 아래 한 줄 설명(원문·출처 표기 등). */
  subtitle?: ReactNode;
  /** 제목 오른쪽에 붙는 버튼·배지. */
  actions?: ReactNode;
  children: ReactNode;
  id?: string;
  bodyClassName?: string;
}) {
  return (
    <Card asChild id={id} className="mb-4">
      <section>
        <CardHeader className="flex-row items-start justify-between gap-3">
          <div className="min-w-0 flex flex-col gap-1">
            <CardTitle>{title}</CardTitle>
            {subtitle ? <CardDescription>{subtitle}</CardDescription> : null}
          </div>
          {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
        </CardHeader>
        <CardContent className={bodyClassName}>{children}</CardContent>
      </section>
    </Card>
  );
}

/** 카드를 2열 이상으로 늘어놓을 때 감싸는 격자(좁은 화면에서는 1열). */
export function CardGrid({ children, min = "18rem" }: { children: ReactNode; min?: string }) {
  // auto-fill/minmax 는 Tailwind 임의값으로는 min 을 못 바꾸므로 style 로 남긴다 — 호출자가 폭을 정한다.
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${min}, 1fr))` }}>
      {children}
    </div>
  );
}

/** 코드가 만든 원문(summary_text·결정문)을 그대로 보이는 상자 — 화면이 다시 쓰지 않는다. */
export function VerbatimBlock({
  text,
  label,
  className,
}: {
  text: string | null | undefined;
  label?: ReactNode;
  className?: string;
}) {
  if (!text) {
    // 생성 실패는 '내용 없음' 과 다르다 — 그 사실을 적는다(null 은 0 이 아니다).
    return <p className="m-0 text-sm text-muted-foreground">요약 생성 실패.</p>;
  }
  return (
    <figure className={cn("m-0 rounded-md border border-border bg-muted/40 p-3", className)}>
      {label ? <figcaption className="mb-1 text-xs text-muted-foreground">{label}</figcaption> : null}
      <pre className="m-0 whitespace-pre-wrap break-words font-mono text-[0.8rem] leading-relaxed">{text}</pre>
    </figure>
  );
}
