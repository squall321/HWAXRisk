// 과제 이력 탭 — 사람 행위 감사(rr_audit)를 시각 · 행위자 · 행위 · 전후로, 행위로 거르고 쪽으로 넘긴다(B34 104, plan §8.2.3 GET projects/{id}/audit)
import { useMemo, useState } from "react";
import { riskApi } from "../api/risk.api";
import { useAsync } from "../hooks/useAsync";
import type { Column } from "./DataTable";
import { DataTable } from "./DataTable";
import { Badge } from "./Badge";
import { SectionCard } from "./SectionCard";
import { ErrorBanner, LoadingBlock } from "./StateBlocks";
import { Button, Select } from "../ui/primitives";
import { fmtCell, fmtEpoch } from "../format";
import type { AuditEntry } from "../types";

/** 한 쪽의 줄 수(서버 상한 500). */
const PAGE = 50;

/** 알려진 행위의 사람 말 — 값은 글자 그대로 보이고 뜻만 붙인다. 모르는 행위는 글자 그대로다. */
const ACTION_LABEL: Record<string, string> = {
  "project.update": "메타 고침",
  "project.mcp_visibility": "조직 공개 바꿈",
  "project.transfer": "소유권 이양",
  "project.purge": "과제 폐기",
  "project.ecad_board": "ECAD 보드 붙이기 · 떼기",
  "member.put": "멤버 고침",
  "requirement.decide": "요구 결정",
  "coverage.skip": "좌석 넘김",
  "coverage.uncarry": "좌석 되돌리기",
  "coverage.undefer": "보류 풀기",
};

export function ProjectAuditCard({ projectId, active }: { projectId: string; active: boolean }) {
  const [action, setAction] = useState("");
  const [offset, setOffset] = useState(0);
  const page = useAsync(
    (signal) => riskApi.getProjectAudit(projectId, { action: action || undefined, limit: PAGE, offset }, { signal }),
    [projectId, action, offset],
    active,
  );
  /** 거름 선택지 — 사전에 있는 행위와 지금 쪽에 나온 행위. */
  const actions = useMemo(() => {
    const seen = new Set(Object.keys(ACTION_LABEL));
    for (const e of page.data?.entries ?? []) seen.add(e.action);
    return Array.from(seen).sort();
  }, [page.data]);

  const columns: Column<AuditEntry>[] = [
    { key: "at", header: "시각", hint: "at", cell: (e) => fmtEpoch(e.at), nowrap: true },
    {
      key: "actor",
      header: "행위자",
      hint: "actor · actor_verified",
      nowrap: true,
      cell: (e) => (
        <span className="inline-flex items-center gap-1">
          {e.actor}
          {e.actor_verified ? null : (
            <Badge tone="warn" title="게이트웨이 위임으로 확인되지 않은 행위자(자칭)">
              미확인
            </Badge>
          )}
        </span>
      ),
    },
    { key: "channel", header: "경로", hint: "channel", cell: (e) => e.channel ?? "-", nowrap: true },
    {
      key: "action",
      header: "행위",
      hint: "action",
      cell: (e) => (
        <span>
          <code>{e.action}</code>
          {ACTION_LABEL[e.action] ? <span className="text-muted-foreground"> {ACTION_LABEL[e.action]}</span> : null}
        </span>
      ),
    },
    { key: "subject", header: "대상", hint: "scope · subject_id", cell: (e) => `${e.scope} · ${e.subject_id ?? "-"}` },
    {
      key: "change",
      header: "전 → 후",
      hint: "before · after",
      cell: (e) => (
        <code className="text-xs">
          {fmtCell(e.before)} → {fmtCell(e.after)}
        </code>
      ),
    },
    { key: "reason", header: "사유", hint: "reason", cell: (e) => e.reason ?? <span className="text-muted-foreground">—</span> },
  ];

  const total = page.data?.total ?? 0;
  return (
    <SectionCard title="이력" subtitle="사람 행위만 남습니다 — 자동 전이는 감사에 들어가지 않습니다.">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select
          className="w-auto min-w-[14rem]"
          aria-label="행위 거르기"
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">행위 전체</option>
          {actions.map((a) => (
            <option key={a} value={a}>
              {ACTION_LABEL[a] ? `${ACTION_LABEL[a]} ${a}` : a}
            </option>
          ))}
        </Select>
        {page.data ? (
          <span className="text-sm text-muted-foreground">
            {total === 0 ? "0건" : `${offset + 1}–${offset + page.data.entries.length} / ${total}건`}
          </span>
        ) : null}
        <Button type="button" variant="ghost" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          앞 쪽
        </Button>
        <Button type="button" variant="ghost" size="sm" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
          다음 쪽
        </Button>
      </div>
      <ErrorBanner error={page.error} onRetry={page.reload} />
      {page.loading && !page.data ? <LoadingBlock /> : null}
      {page.data ? <DataTable columns={columns} rows={page.data.entries} rowKey={(e) => e.id} empty="이력이 없습니다." /> : null}
    </SectionCard>
  );
}
