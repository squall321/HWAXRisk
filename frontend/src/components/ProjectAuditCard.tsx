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
import type { AuditEntry, JsonValue } from "../types";

/** 한 쪽의 줄 수(서버 상한 500). */
const PAGE = 50;

/** 알려진 행위의 사람 말 — 값은 글자 그대로 보이고 뜻만 붙인다. 모르는 행위는 글자 그대로다. */
export const ACTION_LABEL: Record<string, string> = {
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
  // 사람 조작 감사(백엔드 사용자 결정 10-31) — 잡 제어 · 등록부 status · verdict 확정. 말은 그 조작의 단추 이름을 따른다.
  "job.pause": "잡 일시정지",
  "job.resume": "잡 재개",
  "job.cancel": "잡 취소",
  "registry.status": "등록부 상태 바꿈",
  "verdict.final": "판정 확정",
};

/** 앞 · 뒤 한쪽의 글 — 그 행위의 꼴이 아니면 null(그때는 JSON 그대로 보인다). */
type ChangeSide = (value: JsonValue) => string | null;

const fields = (value: JsonValue): { [key: string]: JsonValue } | null =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? value : null;

/** 잡 제어의 {state, hold_code} — 상태에 보류 코드가 있으면 붙인다(코드 보류 위의 사람 정지는 보류만 바뀐다). */
const jobSide: ChangeSide = (value) => {
  const v = fields(value);
  if (!v || typeof v.state !== "string") return null;
  return typeof v.hold_code === "string" ? `${v.state} · 보류 ${v.hold_code}` : v.state;
};

/** 등록부 status 의 {status}(앞) · {status, status_log_seq}(뒤) — 뒤에는 그 결정의 상태 기록 번호를 붙인다(사람이 쓴 글은 거기 있다). */
const registrySide: ChangeSide = (value) => {
  const v = fields(value);
  if (!v || typeof v.status !== "string") return null;
  return typeof v.status_log_seq === "number" ? `${v.status} · 상태 기록 #${v.status_log_seq}` : v.status;
};

/** verdict 확정의 {verdict_final} — 처음 확정이면 앞이 비었다(없음). */
const verdictSide: ChangeSide = (value) => {
  const v = fields(value);
  if (!v || !("verdict_final" in v)) return null;
  return typeof v.verdict_final === "string" ? v.verdict_final : "없음";
};

const CHANGE_SIDE: Record<string, ChangeSide> = {
  "job.pause": jobSide,
  "job.resume": jobSide,
  "job.cancel": jobSide,
  "registry.status": registrySide,
  "verdict.final": verdictSide,
};

/**
 * 전 → 후 칸의 글. 사람 조작 감사 셋의 앞 · 뒤는 코드 어휘 몇 칸뿐이라 그 값을 글자 그대로 잇는다(잡 상태 · 보류 코드, 등록부 status ·
 * 상태 기록 번호, 판정 값). 그 밖의 행위와, 꼴이 다른 값(옛 행 따위)은 종전대로 JSON 이다.
 */
export function auditChange(entry: Pick<AuditEntry, "action" | "before" | "after">): string {
  const side = CHANGE_SIDE[entry.action];
  const before = side ? side(entry.before) : null;
  const after = side ? side(entry.after) : null;
  if (before === null || after === null) return `${fmtCell(entry.before)} → ${fmtCell(entry.after)}`;
  return `${before} → ${after}`;
}

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
      cell: (e) => <code className="text-xs">{auditChange(e)}</code>,
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
