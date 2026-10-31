// 과제 멤버 · 이양 · 폐기 — 멤버 표(소유자만 고친다)와 소유권 이양(사유 필수) · 과제 폐기(코드 다시 적기)(B34 104, plan §5.2.1 · §5.2.6)
import { useState } from "react";
import { Link } from "react-router-dom";
import { Trash2, UserPlus } from "lucide-react";
import { isApiError, riskApi } from "../api/risk.api";
import type { Async } from "../hooks/useAsync";
import type { Column } from "./DataTable";
import { DataTable } from "./DataTable";
import { Badge } from "./Badge";
import { SectionCard } from "./SectionCard";
import { ErrorBanner, LoadingBlock } from "./StateBlocks";
import { Banner, Button, FormField, FormGrid, Input, Mono, Select, SubPanel } from "../ui/primitives";
import { fmtEpoch } from "../format";
import { ROLE_LABEL, emailProblem } from "../lib/projectMeta";
import type { ProjectMember, ProjectMembers, ProjectPurged, ProjectRole, ProjectTransferred } from "../types";

/** 이양 · 폐기 사유 상한(routes.TransferBody · PurgeBody). */
const REASON_MAX = 300;

/** 거절 code 의 말 — 서버 글은 글자 그대로 보이고 제목만 고른다. 모르는 code 는 공용 배너다. */
const MEMBER_ERRORS: Record<string, string> = {
  owner_row_immutable: "소유자 행은 이양으로만 바뀝니다.",
  role_insufficient: "소유자만 할 수 있습니다.",
  job_running: "진행 중인 배치 잡이 있습니다 — 먼저 일시정지합니다.",
  same_owner: "이미 이 사람이 소유자입니다.",
  unknown_user: "heax 사용자 이메일이 아닙니다.",
  code_mismatch: "과제 코드가 일치하지 않습니다.",
  already_purged: "이미 폐기된 과제입니다.",
  project_purged: "폐기된 과제는 고칠 수 없습니다.",
};

function MemberErrorBanner({ error }: { error: unknown }) {
  if (error === null || error === undefined) return null;
  if (isApiError(error) && MEMBER_ERRORS[error.code]) {
    const title = MEMBER_ERRORS[error.code];
    // 서버 글이 제목과 같으면 한 번만 보인다.
    return <Banner title={title} detail={error.message !== title ? error.message : undefined} />;
  }
  return <ErrorBanner error={error} />;
}

export function ProjectMembersCard({
  projectId,
  projectCode,
  isOwner,
  members,
}: {
  projectId: string;
  projectCode: string;
  /** 멤버 고치기 · 이양 · 폐기는 소유자만(관리자 role 은 서버가 소유자와 같게 본다). */
  isOwner: boolean;
  /** 과제 화면이 받아 둔 멤버 표(내 역할도 여기서 센다) — 고친 뒤 다시 받는다. */
  members: Async<ProjectMembers>;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"viewer" | "editor">("viewer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function put(body: { members: Array<{ email: string; role: "viewer" | "editor" }>; remove: string[] }) {
    setBusy(true);
    setError(null);
    try {
      await riskApi.putMembers(projectId, body);
      setEmail("");
      members.reload();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<ProjectMember>[] = [
    { key: "email", header: "이메일", hint: "email", cell: (m) => <Mono>{m.email}</Mono>, nowrap: true },
    {
      key: "role",
      header: "역할",
      hint: "role",
      nowrap: true,
      cell: (m) =>
        isOwner && m.role !== "owner" ? (
          <Select
            className="w-auto min-w-[8rem]"
            aria-label={`${m.email} 역할`}
            value={m.role}
            disabled={busy}
            onChange={(e) => void put({ members: [{ email: m.email, role: e.target.value as "viewer" | "editor" }], remove: [] })}
          >
            <option value="viewer">{ROLE_LABEL.viewer} viewer</option>
            <option value="editor">{ROLE_LABEL.editor} editor</option>
          </Select>
        ) : (
          <Badge tone={m.role === "owner" ? "info" : "neutral"}>
            {ROLE_LABEL[m.role as ProjectRole] ?? m.role} {m.role}
          </Badge>
        ),
    },
    { key: "by", header: "추가한 사람", hint: "added_by", cell: (m) => m.added_by ?? "-", nowrap: true },
    { key: "at", header: "추가한 때", hint: "added_at", cell: (m) => fmtEpoch(m.added_at), nowrap: true },
    {
      key: "remove",
      header: "",
      nowrap: true,
      cell: (m) =>
        isOwner && m.role !== "owner" ? (
          <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void put({ members: [], remove: [m.email] })}>
            <Trash2 aria-hidden="true" />
            빼기
          </Button>
        ) : null,
    },
  ];

  const addProblem = email.trim() === "" ? null : emailProblem(email);

  return (
    <>
      <SectionCard title="멤버" subtitle="소유자 행은 이양으로만 바뀝니다. 멤버 고치기는 소유자만 합니다.">
        <ErrorBanner error={members.error} onRetry={members.reload} />
        <MemberErrorBanner error={error} />
        {members.loading && !members.data ? <LoadingBlock /> : null}
        {members.data ? (
          <DataTable columns={columns} rows={members.data.members} rowKey={(m) => m.email} empty="멤버가 없습니다." />
        ) : null}
        {isOwner ? (
          <form
            className="mt-3 flex flex-wrap items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (email.trim() === "" || addProblem) return;
              void put({ members: [{ email: email.trim().toLowerCase(), role }], remove: [] });
            }}
          >
            <FormField label="이메일" hint="heax 사용자" error={addProblem ?? undefined} className="min-w-[16rem]">
              <Input value={email} onChange={(e) => setEmail(e.target.value)} />
            </FormField>
            <FormField label="역할" hint="role">
              <Select value={role} onChange={(e) => setRole(e.target.value as "viewer" | "editor")}>
                <option value="viewer">{ROLE_LABEL.viewer} viewer</option>
                <option value="editor">{ROLE_LABEL.editor} editor</option>
              </Select>
            </FormField>
            <Button type="submit" variant="outline" disabled={busy || email.trim() === "" || addProblem !== null}>
              <UserPlus aria-hidden="true" />
              멤버 추가
            </Button>
          </form>
        ) : (
          <p className="mt-3 mb-0 text-sm text-muted-foreground">멤버 고치기 · 이양 · 폐기는 과제 소유자만 합니다.</p>
        )}
      </SectionCard>
      {isOwner ? <TransferCard projectId={projectId} /> : null}
      {isOwner ? <PurgeCard projectId={projectId} projectCode={projectCode} /> : null}
    </>
  );
}

/** 소유권 이양 — 사유 필수, 확인 뒤 보낸다. 이전 소유자는 편집자로 남는다(plan §5.2.1). */
function TransferCard({ projectId }: { projectId: string }) {
  const [to, setTo] = useState("");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<ProjectTransferred | null>(null);

  const toProblem = to.trim() === "" ? null : emailProblem(to);
  const ready = to.trim() !== "" && !toProblem && reason.trim() !== "";

  async function send() {
    setBusy(true);
    setError(null);
    setConfirm(false);
    try {
      setDone(await riskApi.transferProject(projectId, { to_email: to.trim(), reason: reason.trim() }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <SectionCard title="소유권 이양" subtitle="과제와 하위 표의 소유자를 한 번에 옮깁니다 — 이전 소유자는 편집자로 남습니다.">
      <MemberErrorBanner error={error} />
      {done ? (
        <Banner tone="info" live="status" title={`소유권을 ${done.to} 에게 넘겼습니다.`} detail="이 화면은 소유자의 것이라 이제 열리지 않을 수 있습니다.">
          <Link to="/" className="text-sm underline underline-offset-4">
            과제 목록으로
          </Link>
        </Banner>
      ) : null}
      <FormGrid>
        <FormField label="새 소유자 이메일" hint="to_email" error={toProblem ?? undefined}>
          <Input value={to} onChange={(e) => setTo(e.target.value)} />
        </FormField>
        <FormField label="사유" hint={`필수 · ${REASON_MAX}자까지`}>
          <Input maxLength={REASON_MAX} value={reason} onChange={(e) => setReason(e.target.value)} />
        </FormField>
      </FormGrid>
      <Button type="button" variant="outline" className="mt-3" disabled={busy || !ready} onClick={() => setConfirm(true)}>
        이양…
      </Button>
      {confirm ? (
        <Banner
          tone="warn"
          live="status"
          title={`소유권을 ${to.trim()} 에게 넘깁니다.`}
          detail="진행 중인 배치 잡이 있으면 409 job_running 으로 막힙니다 — 먼저 일시정지합니다. 나는 편집자로 남습니다."
        >
          <span className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" disabled={busy} onClick={() => void send()}>
              넘기기
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setConfirm(false)}>
              그만두기
            </Button>
          </span>
        </Banner>
      ) : null}
    </SectionCard>
  );
}

/** 과제 폐기 — 행을 지우지 않고 원문 열을 비우는 표기다(plan §5.2.6). 과제 코드를 다시 적어야 보낸다. */
function PurgeCard({ projectId, projectCode }: { projectId: string; projectCode: string }) {
  const [code, setCode] = useState("");
  const [reason, setReason] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<ProjectPurged | null>(null);

  const ready = code.trim() !== "" && reason.trim() !== "";

  async function send() {
    setBusy(true);
    setError(null);
    setConfirm(false);
    try {
      setDone(await riskApi.purgeProject(projectId, { code: code.trim(), reason: reason.trim() }));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <SectionCard
      title="과제 폐기"
      subtitle="원문 열(IR · 발언 · 근거)을 비우고 해시 · 수 · 감사는 남깁니다. 되돌릴 수 없습니다."
    >
      <MemberErrorBanner error={error} />
      {done ? (
        <SubPanel title="폐기 보고">
          <p className="m-0 text-sm">
            {fmtEpoch(done.purge_report.purged_at)} · {done.purge_report.by} · «{done.purge_report.reason}»
          </p>
          <h4 className="m-0 text-xs font-medium text-muted-foreground">남은 것(remaining)</h4>
          <ul className="m-0 list-disc pl-5 text-sm [&>li]:mb-1">
            {done.purge_report.remaining.map((r) => (
              <li key={r.layer}>
                <code>{r.layer}</code> {r.reason} — {r.detail}
              </li>
            ))}
          </ul>
        </SubPanel>
      ) : null}
      <FormGrid>
        <FormField label={`과제 코드 다시 적기(${projectCode})`} hint="code">
          <Input value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" />
        </FormField>
        <FormField label="사유" hint={`필수 · ${REASON_MAX}자까지`}>
          <Input maxLength={REASON_MAX} value={reason} onChange={(e) => setReason(e.target.value)} />
        </FormField>
      </FormGrid>
      <Button type="button" variant="destructive" className="mt-3" disabled={busy || !ready} onClick={() => setConfirm(true)}>
        폐기…
      </Button>
      {confirm ? (
        <Banner
          tone="error"
          live="status"
          title="이 과제를 폐기합니다 — 되돌릴 수 없습니다."
          detail="진행 중인 잡은 취소되고 남은 좌석은 넘김으로 닫힙니다. 원문 열이 비워집니다."
        >
          <span className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="destructive" size="sm" disabled={busy} onClick={() => void send()}>
              폐기
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setConfirm(false)}>
              그만두기
            </Button>
          </span>
        </Banner>
      ) : null}
    </SectionCard>
  );
}
