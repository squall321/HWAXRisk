// 가로 스크롤 컨테이너에 담긴 공용 표 — 좁은 화면에서 페이지 본문이 옆으로 밀리지 않게 표만 스크롤한다.
import type { ReactNode } from "react";

export type Column<T> = {
  /** 열 식별자(React key). */
  key: string;
  header: ReactNode;
  /** 셀 내용. 값 가공은 화면 몫이고 이 컴포넌트는 판단을 만들지 않는다. */
  cell: (row: T, index: number) => ReactNode;
  align?: "left" | "right" | "center";
  /** 숫자 열처럼 줄바꿈을 막고 싶을 때. */
  nowrap?: boolean;
  width?: string;
};

/** 표 하나를 가로 스크롤 상자에 담는다. 표가 아닌 넓은 블록(mermaid 등)에도 쓸 수 있다. */
export function TableScroll({ children }: { children: ReactNode }) {
  return <div className="rr-scroll-x">{children}</div>;
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
    return <div className="rr-state rr-state-empty">{empty ?? <span className="rr-muted">표시할 행이 없습니다.</span>}</div>;
  }
  return (
    <TableScroll>
      <table className="rr-table">
        {caption ? <caption>{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" style={{ textAlign: c.align ?? "left", width: c.width }}>
                {c.header}
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
                className={selectedKey === key ? "rr-row-selected" : undefined}
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
                    style={{ textAlign: c.align ?? "left" }}
                    className={c.nowrap ? "rr-nowrap" : undefined}
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

/** 키·값 두 열짜리 정의 표(개요 카드에서 쓴다). */
export function KeyValueTable({ rows }: { rows: Array<{ label: ReactNode; value: ReactNode }> }) {
  return (
    <TableScroll>
      <table className="rr-table rr-table-kv">
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <th scope="row">{r.label}</th>
              <td>{r.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}
