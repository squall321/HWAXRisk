// 화면 구역을 감싸는 카드 — §8.2.4 표의 '구역(위→아래)' 한 칸이 카드 하나다.
import type { ReactNode } from "react";

export function SectionCard({
  title,
  subtitle,
  actions,
  children,
  id,
}: {
  title: ReactNode;
  /** 제목 아래 한 줄 설명(원문·출처 표기 등). */
  subtitle?: ReactNode;
  /** 제목 오른쪽에 붙는 버튼·배지. */
  actions?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  return (
    <section className="rr-card" id={id}>
      <div className="rr-card-head">
        <div className="rr-card-title">
          <h2>{title}</h2>
          {subtitle ? <p className="rr-muted">{subtitle}</p> : null}
        </div>
        {actions ? <div className="rr-card-actions">{actions}</div> : null}
      </div>
      <div className="rr-card-body">{children}</div>
    </section>
  );
}

/** 카드를 2열 이상으로 늘어놓을 때 감싸는 격자(좁은 화면에서는 1열). */
export function CardGrid({ children, min = "18rem" }: { children: ReactNode; min?: string }) {
  return (
    <div className="rr-grid" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${min}, 1fr))` }}>
      {children}
    </div>
  );
}

/** 코드가 만든 원문(summary_text·결정문)을 그대로 보이는 상자 — 화면이 다시 쓰지 않는다. */
export function VerbatimBlock({ text, label }: { text: string | null | undefined; label?: ReactNode }) {
  if (!text) {
    return <p className="rr-muted">요약 생성 실패.</p>;
  }
  return (
    <figure className="rr-verbatim">
      {label ? <figcaption className="rr-muted">{label}</figcaption> : null}
      <pre>{text}</pre>
    </figure>
  );
}
