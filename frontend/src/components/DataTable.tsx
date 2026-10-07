// 가로 스크롤 컨테이너에 담긴 공용 표 — 좁은 화면에서 페이지 본문이 옆으로 밀리지 않게 표만 스크롤한다.
import type { ReactNode } from "react";
import { cn } from "../lib/cn";
import { Field } from "../ui/primitives";

export type Column<T> = {
  /** 열 식별자(React key). */
  key: string;
  header: ReactNode;
  /**
   * 머리글 옆에 작게 붙는 원시 필드명(`verdict_final` 등). `KeyValueTable` 의 `hint` 와 같은 규율이다 —
   * 머리글을 한국어로 올리면서 서버와 대조할 이름까지 지우면, 화면에서 본 값을 API·DB 에서 찾을 길이 없어진다.
   */
  hint?: string;
  /** 셀 내용. 값 가공은 화면 몫이고 이 컴포넌트는 판단을 만들지 않는다. */
  cell: (row: T, index: number) => ReactNode;
  align?: "left" | "right" | "center";
  /** 숫자 열처럼 줄바꿈을 막고 싶을 때. */
  nowrap?: boolean;
  width?: string;
};

/** 표 하나를 가로 스크롤 상자에 담는다. 표가 아닌 넓은 블록(mermaid 등)에도 쓸 수 있다. */
export function TableScroll({ children }: { children: ReactNode }) {
  return <div className="max-w-full overflow-x-auto">{children}</div>;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  selectedKey,
  empty,
  caption,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string;
  onRowClick?: (row: T, index: number) => void;
  selectedKey?: string | null;
  /** 행이 0건일 때 표 대신 보일 것(없으면 한 줄 안내). */
  empty?: ReactNode;
  caption?: ReactNode;
}) {
  if (rows.length === 0) {
    return (
      <div className="px-4 py-8 text-center text-sm text-muted-foreground">
        {empty ?? "표시할 행이 없습니다."}
      </div>
    );
  }
  return (
    <TableScroll>
      {/* preflight 를 꺼 둬서 border-collapse·width 는 Tailwind 유틸로 직접 준다(기존 .rr-table 과 같은 값). */}
      <table className="w-full min-w-max border-collapse text-sm">
        {caption ? (
          <caption className="caption-top pb-2 text-left text-xs text-muted-foreground">{caption}</caption>
        ) : null}
        <thead>
          <tr className="border-b border-border">
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className="px-3 py-2 text-xs font-medium text-muted-foreground"
                style={{ textAlign: c.align ?? "left", width: c.width }}
              >
                {c.header}
                {c.hint ? <span className="ml-1 font-mono font-normal opacity-60">{c.hint}</span> : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const key = rowKey(row, i);
            return (
              <tr
                key={key}
                className={cn(
                  "border-b border-border/60 last:border-0",
                  onRowClick && "cursor-pointer hover:bg-muted/50",
                  selectedKey === key && "bg-accent",
                )}
                onClick={onRowClick ? () => onRowClick(row, i) : undefined}
                // 마우스 전용이 되지 않게 — 열 수 있는 행은 키보드 초점과 Enter·Space 를 받는다.
                tabIndex={onRowClick ? 0 : undefined}
                onKeyDown={
                  onRowClick
                    ? (event) => {
                        if (event.key !== "Enter" && event.key !== " ") return;
                        event.preventDefault();
                        onRowClick(row, i);
                      }
                    : undefined
                }
                aria-selected={onRowClick ? selectedKey === key : undefined}
                data-clickable={onRowClick ? "true" : undefined}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={cn("px-3 py-2 align-top", c.nowrap && "whitespace-nowrap")}
                    style={{ textAlign: c.align ?? "left" }}
                  >
                    {c.cell(row, i)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </TableScroll>
  );
}

/**
 * 개요 카드의 라벨·값 목록. **표가 아니라 정의 목록이다** — 개요는 행을 비교하는 자리가 아니라
 * 한 대상을 읽는 자리이고, 표로 그리면 좁은 화면에서 라벨 열이 값을 밀어낸다.
 *
 * `label` 은 사람 말로 쓰고 원시 필드명은 `hint` 로 넘긴다(§8.2.4 — 화면이 엔지니어 덤프가 되지
 * 않게 하되, 서버와 대조할 이름을 지우지는 않는다).
 */
export function KeyValueTable({
  rows,
  columns = 2,
}: {
  /** `label` 이 string 인 것은 일부러다 — ReactNode 를 받으면 원시 필드명이 다시 라벨 자리로 돌아온다. */
  rows: Array<{ label: string; value: ReactNode; hint?: string }>;
  /** 넓은 화면에서 몇 열로 흘릴지. 값이 긴 개요는 1 로 둔다. */
  columns?: 1 | 2;
}) {
  return (
    <dl className={cn("m-0 grid gap-x-6", columns === 2 && "sm:grid-cols-2")}>
      {rows.map((r) => (
        <Field key={r.label} label={r.label} hint={r.hint}>
          {r.value}
        </Field>
      ))}
    </dl>
  );
}
