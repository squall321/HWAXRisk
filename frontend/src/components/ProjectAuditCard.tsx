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

/**
 * 알려진 행위의 사람 말 — 값은 글자 그대로 보이고 뜻만 붙인다. 모르는 행위는 글자 그대로다. 앱이 rr_audit 에 쓸 수 있는 행위는 전부 여기
 * 있어야 한다 — backend tests/test_audit_action_labels.py 가 앱 소스에서 끌어낸 행위와 이 사전의 열쇠를 견준다.
 */
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
  // 그 밖에 앱이 쓰는 행위 전부(이력 탭 이름표 후속 10-31). 말은 화면의 단추 · 안내 글을 따른다(ack · 다시 · 넘김 · 올리기 · 건너뛰기).
  "gate.ack": "게이트 ack 붙이기 · 취소",
  "target.flow": "심사 방식 바꿈",
  "job.create": "잡 시작",
  "brief.exclude": "브리프 항목 빼기",
  "cells.retry": "셀 다시 열기",
  "cells.skip": "셀 넘김",
  "issue.queue": "쟁점 올리기",
  "issue.skip": "쟁점 건너뛰기",
  "close.ack": "잔여 확인",
  "close.ack.revoke": "잔여 확인 취소",
  "finding.create": "사람 finding 올림",
  "finding.update": "사람 finding 고침",
  "finding.delete": "사람 finding 지움",
  "panel.repersist": "패널 다시 저장",
  "panel.repersist_discard": "패널 다시 저장 포기",
  "registry.merge": "등록부 병합",
  "registry.merge.revoke": "등록부 병합 되돌리기",
  "registry.visibility": "등록부 공개 바꿈",
  "rekey": "키 전파",
  "recall.approve": "회수 승인",
  "curation.decide": "큐 결정",
  "vocab.edit": "어휘 고침",
  "ra.retract": "RA 거두기",
  "ra.remark": "RA 다시 표기",
  // 관리자 접근 감사(사용자 결정 11-01) — 구성원이 아닌 관리자의 읽기는 관리자 · 과제 · 날(KST)마다 한 줄이다.
  "admin.read": "관리자 열람",
};

/** 쓰기의 관리자 우회 표시(entry.via "admin")의 풀이 — 배지 글은 '관리자 권한' 이다. */
export const ADMIN_VIA_TITLE =
  "구성원이 아니거나 그 쓰기에 모자란 역할의 관리자(risk_admin_roles)가 관리자 권한으로 한 쓰기입니다 — 구성원으로도 할 수 있는 쓰기에는 붙지 않습니다.";

/**
 * '미확인' 배지의 풀이 — 행위자가 앱이 직접 확인한 신원이 아닌 까닭은 행을 쓴 길마다 다르다(백엔드가 actor_verified 0 을 쓰는 자리 셋).
 * MCP(Claude) 길은 게이트웨이가 위임으로 넘긴 신원이고(앱은 게이트웨이의 서명만 본다), 웹의 job.pause 미확인 행은 포털 화면의 '멈춤'(엔진
 * 쪽 멈춤 A24)으로 에이전트 서버가 알린 사람이며, system 은 누가 했는지 모르는 RA 뒤처리(거두기 · 다시 표기)다.
 */
export function unverifiedTitle(entry: Pick<AuditEntry, "channel" | "action" | "actor">): string {
  if (entry.channel === "mcp") {
    return "Claude(MCP) 길 — 게이트웨이가 위임으로 넘긴 신원입니다. 앱은 게이트웨이의 서명만 확인했고 그 사람을 직접 확인하지는 않았습니다.";
  }
  if (entry.channel === "web" && entry.action === "job.pause") {
    return "포털 화면의 '멈춤'으로 멈춘 잡 — 에이전트 서버가 알린, 심의를 멈춘 사람입니다. 앱이 직접 확인한 신원은 아닙니다.";
  }
  if (entry.actor === "system") {
    return "누가 했는지 모르는 뒤처리입니다 — 사람으로 적지 않고 system 으로 적었습니다.";
  }
  return `앱이 직접 확인한 신원이 아닙니다(입구 ${entry.channel ?? "-"}).`;
}

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
  if (entry.action === "admin.read") {
    // 열람 줄은 바뀐 것이 없다 — 그 줄이 맡은 한국 날만 보인다(그날 첫 열람에만 한 줄이 선다).
    const day = fields(entry.after)?.day;
    if (typeof day === "string") return `${day}(KST) 하루 한 줄`;
  }
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
      hint: "actor · actor_verified · via",
      nowrap: true,
      cell: (e) => (
        <span className="inline-flex items-center gap-1">
          {e.actor}
          {e.actor_verified ? null : (
            <Badge tone="warn" title={unverifiedTitle(e)}>
              미확인
            </Badge>
          )}
          {e.via === "admin" ? (
            <Badge tone="info" title={ADMIN_VIA_TITLE}>
              관리자 권한
            </Badge>
          ) : null}
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
    <SectionCard
      title="이력"
      subtitle="사람 행위만 남습니다 — 자동 전이는 감사에 들어가지 않습니다. 구성원이 아닌 관리자의 열람은 관리자 · 날(KST)마다 한 줄로 남습니다."
    >
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
