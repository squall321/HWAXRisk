// 보고서 쪽의 마크다운 줄을 그린다 — 제목 · 목록 · 굵게 · 고정폭만, 서버 글은 늘 글 노드로(HTML 로 해석하지 않는다)
import { Fragment } from "react";
import { parseInline, parseMdLine } from "../lib/reportView";
import { cn } from "../lib/cn";

function Inline({ text }: { text: string }) {
  return (
    <>
      {parseInline(text).map((span, i) =>
        span.kind === "strong" ? (
          <strong key={i}>{span.text}</strong>
        ) : span.kind === "code" ? (
          <code key={i} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.8em]">
            {span.text}
          </code>
        ) : (
          <Fragment key={i}>{span.text}</Fragment>
        ),
      )}
    </>
  );
}

const HEADING_CLASS: Record<number, string> = {
  1: "text-base font-semibold",
  2: "text-sm font-semibold",
  3: "text-sm font-medium",
};

/** 줄 배열을 그린다 — 줄마다 한 덩이(목록은 깊이만큼 들여 쓴다). 긴 줄은 접어 쓴다. */
export function MarkdownLines({ lines, className }: { lines: string[]; className?: string }) {
  return (
    <div className={cn("flex flex-col gap-1 break-words text-sm leading-relaxed", className)}>
      {lines.map((line, i) => {
        const md = parseMdLine(line);
        switch (md.kind) {
          case "blank":
            return <div key={i} className="h-2" aria-hidden="true" />;
          case "heading":
            return (
              <p key={i} role="heading" aria-level={Math.min(6, md.level + 2)} className={cn("m-0 mt-2", HEADING_CLASS[md.level] ?? "text-sm font-medium")}>
                <Inline text={md.text} />
              </p>
            );
          case "item":
            return (
              <p key={i} className="m-0 flex gap-1.5" style={{ paddingLeft: `${md.depth * 1.25}rem` }}>
                <span aria-hidden="true" className="text-muted-foreground">
                  •
                </span>
                <span className="min-w-0">
                  <Inline text={md.text} />
                </span>
              </p>
            );
          default:
            return (
              <p key={i} className="m-0">
                <Inline text={md.text} />
              </p>
            );
        }
      })}
    </div>
  );
}
