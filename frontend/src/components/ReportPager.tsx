// 보고서 쪽 넘김 — part 탭 · 쪽 넘김, 둘째 쪽부터 첫 쪽의 판을 실어 보내고 409 report_version_moved 면 1쪽부터 다시 받는다(전문가 보고서 · 종합 보고서가 같이 쓴다)
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { isApiError } from "../api/risk.api";
import { pagesTotalOf, versionMovedOf } from "../api/reviewErrors";
import { useAsync } from "../hooks/useAsync";
import { MarkdownLines } from "./MarkdownLines";
import { ReviewErrorBanner } from "./ReviewErrorBanner";
import { EmptyBlock, LoadingBlock } from "./StateBlocks";
import { Banner, Button, TabBar } from "../ui/primitives";
import { pageLines, pageQuery } from "../lib/reportView";
import type { ReportPage } from "../types";

/** 쪽 응답의 공통 칸 — 판 번호 · 쪽 번호 · 쪽 수 · 다음 쪽 · 쪽 본문. */
export type PagedReport = { version: number; part: string; page_no: number; pages_total: number; next_page?: number; page: ReportPage };

export function ReportPager<P extends string, T extends PagedReport>({
  loadKey,
  parts,
  load,
  header,
  absent,
  idPrefix,
}: {
  /** 무엇의 보고서인가(대상 · 전문가). 바뀌면 처음 쪽부터라 부르는 쪽이 이 값을 React key 로도 준다(다시 마운트). */
  loadKey: string;
  parts: ReadonlyArray<{ part: P; label: string }>;
  load: (query: { part: P; page: number; version?: number }, signal: AbortSignal) => Promise<T>;
  header: (data: T) => ReactNode;
  /** 판이 없을 때(404 report_absent · E404)의 자리. */
  absent: (error: unknown) => ReactNode | null;
  idPrefix: string;
}) {
  const [part, setPart] = useState<P>(parts[0].part);
  const [page, setPage] = useState(1);
  const [version, setVersion] = useState<number | null>(null);
  const [moved, setMoved] = useState<{ version: number; asked: number } | null>(null);

  const data = useAsync(
    (signal) => load({ part, ...pageQuery(page, version) }, signal),
    // 첫 쪽은 판을 싣지 않으므로 판이 정해져도 다시 받지 않는다.
    [loadKey, part, page, page === 1 ? null : version],
  );

  useEffect(() => {
    if (data.data && data.data.page_no === 1) setVersion(data.data.version);
  }, [data.data]);

  useEffect(() => {
    const mv = versionMovedOf(data.error);
    if (mv) {
      // 그사이 새 판이 섰다 — 쪽이 섞이지 않게 1쪽부터 다시 받는다(요청서 5절).
      setMoved(mv);
      setPage(1);
      setVersion(null);
    }
  }, [data.error]);

  function choose(next: P) {
    setPart(next);
    setPage(1);
    setVersion(null);
    setMoved(null);
  }

  const empty = pagesTotalOf(data.error) === 0;
  const missing = data.error && !versionMovedOf(data.error) ? absent(data.error) : null;
  // 받은 쪽이 지금 고른 part · 쪽일 때만 그린다 — part 를 바꾼 사이 앞 part 의 쪽이 새 탭 이름 아래 보이지 않게.
  const current = data.data && data.data.page_no === page && data.data.part === part ? data.data : null;

  return (
    <div className="flex flex-col gap-2">
      <TabBar
        idPrefix={idPrefix}
        label="보고서 부분"
        value={part}
        onChange={choose}
        tabs={parts.map((p) => ({ tab: p.part, label: p.label }))}
      />
      {moved ? (
        <Banner
          tone="info"
          live="status"
          title={`보고서 판이 v${moved.asked} 에서 v${moved.version} 로 바뀌었습니다 — 처음 쪽부터 다시 받았습니다.`}
        />
      ) : null}
      {empty ? <EmptyBlock title="이 부분에는 쪽이 없습니다." /> : null}
      {missing ?? (!empty && !versionMovedOf(data.error) ? <ReviewErrorBanner error={data.error} onReload={data.reload} /> : null)}
      {data.loading && !current ? <LoadingBlock /> : null}
      {current ? (
        <>
          {header(current)}
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">
              쪽 {current.page_no}/{current.pages_total} · 판 v{current.version}
            </span>
            <Button type="button" variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              앞 쪽
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={current.next_page === undefined}
              onClick={() => current.next_page !== undefined && setPage(current.next_page)}
            >
              다음 쪽
            </Button>
          </div>
          <article className="rounded-md border border-border p-4" aria-label={current.page.title}>
            <MarkdownLines lines={pageLines(current.page)} />
          </article>
        </>
      ) : null}
    </div>
  );
}

/** 판이 없다는 거절인가(404 report_absent · 전문가 보고서의 E404) — 화면이 '아직 없음' 자리를 고른다. */
export function isAbsent(error: unknown, code: string): boolean {
  return isApiError(error) && error.status === 404 && error.code === code;
}
