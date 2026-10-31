// ECAD 카드 — 붙은 보드의 정체 · 찾기(검색 칸 → 후보 표) · 붙이기 · 바꾸기 · 떼기와 거절 code 의 말(포털 ecad-1031 화면 요청서 1 ~ 5절)
import { useState } from "react";
import { Link } from "react-router-dom";
import { Search, Trash2, Unplug } from "lucide-react";
import { isApiError, riskApi } from "../api/risk.api";
import {
  DETACH_CONFIRM_TEXT,
  ECAD_QUERY_MAX,
  ODB_JOB_ID_RE,
  boardQueryProblem,
  describeEcadError,
  ecadRoute,
  notFoundCandidates,
  replaceConfirmText,
} from "../api/ecadBoard";
import type { Column } from "./DataTable";
import { DataTable, KeyValueTable } from "./DataTable";
import { Badge, SourceStatusBadge } from "./Badge";
import { ErrorBanner } from "./StateBlocks";
import { Banner, Button, FormField, Input, Mono, SubPanel } from "../ui/primitives";
import { fmtIso } from "../format";
import type { AdapterEntry, EcadBoard, ProjectSource } from "../types";

/** 찾기 · 붙이기 · 떼기의 거절 — 아는 code 는 제목과 다음 걸음을 붙이고 서버 글은 글자 그대로 보인다. */
function EcadErrorBanner({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (error === null || error === undefined) return null;
  const known = describeEcadError(error);
  if (!known) return <ErrorBanner error={error} />;
  const detail = [isApiError(error) ? error.message : null, known.detail].filter(Boolean).join(" ");
  return (
    <Banner title={known.title} detail={detail || undefined}>
      {known.next === "settings" ? (
        // 자동 등록 스위치 · '포털에서 발급해 등록' 이 설정 화면에 있다(risk-credentials 요청서 1절).
        <Link to="/settings" className="text-sm underline underline-offset-4">
          설정에서 내 포털 PAT 등록
        </Link>
      ) : null}
      {known.next === "retry" && onRetry ? (
        <Button type="button" variant="outline" size="sm" onClick={onRetry}>
          다시 찾기
        </Button>
      ) : null}
    </Banner>
  );
}

/**
 * 후보 표 — 같은 모델의 다른 판이 줄줄이 나오므로 판과 올린 시각을 앞쪽 열에 둔다. 미리 고른 행이 없고, 후보가 하나여도 사람이 그 행의
 * '이 보드' 를 눌러야 붙는다(요청서 0 · 2절). job_id 가 16자리 16진이 아닌 행은 서버가 422 E100 으로 거절하므로 단추를 잠근다(5절).
 */
export function CandidateTable({
  candidates,
  currentJobId,
  busy,
  onPick,
}: {
  candidates: EcadBoard[];
  currentJobId: string | null;
  busy: boolean;
  onPick: (board: EcadBoard) => void;
}) {
  const columns: Column<EcadBoard>[] = [
    { key: "revision", header: "판", hint: "revision", cell: (b) => b.revision ?? <span className="text-muted-foreground">모름</span>, nowrap: true },
    { key: "uploaded", header: "올린 시각", hint: "uploaded_at", cell: (b) => fmtIso(b.uploaded_at), nowrap: true },
    { key: "name", header: "이름", hint: "name", cell: (b) => b.name ?? <span className="text-muted-foreground">이름 없음</span> },
    { key: "file", header: "원본 파일", hint: "original_filename", cell: (b) => b.original_filename ?? "-" },
    { key: "job", header: "job_id", cell: (b) => (b.job_id ? <Mono>{b.job_id}</Mono> : "-"), nowrap: true },
    {
      key: "pick",
      header: "",
      nowrap: true,
      cell: (b) =>
        b.job_id && b.job_id === currentJobId ? (
          <Badge tone="ok">붙은 보드</Badge>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy || !b.job_id || !ODB_JOB_ID_RE.test(b.job_id)}
            title={b.job_id && !ODB_JOB_ID_RE.test(b.job_id) ? "job_id 가 16자리 16진이 아니라 붙일 수 없습니다." : undefined}
            onClick={() => onPick(b)}
          >
            이 보드
          </Button>
        ),
    },
  ];
  return <DataTable columns={columns} rows={candidates} rowKey={(b, i) => `${b.job_id ?? "none"}#${i}`} empty="찾은 보드가 없습니다." />;
}

export function EcadBoardCard({
  projectId,
  source,
  adapters,
  adaptersLoading,
  isOwner,
  onAdaptersRetry,
  onChanged,
}: {
  projectId: string;
  /** 과제의 ECAD 카드(없으면 null — 보드 없음). */
  source: ProjectSource | null;
  adapters: AdapterEntry[] | null;
  adaptersLoading: boolean;
  /** 바꾸기 · 떼기는 과제 주인에게만 보인다(서버도 남이면 없는 것과 같은 404 다). */
  isOwner: boolean;
  onAdaptersRetry: () => void;
  onChanged: () => void;
}) {
  const route = ecadRoute(adapters);
  const ecadRow = (adapters ?? []).find((a) => a.kind === "ecad") ?? null;
  const board = source?.probe?.board ?? null;
  const currentJobId = board?.job_id ?? (typeof source?.ref?.odb_job_id === "string" ? source.ref.odb_job_id : null);

  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [queryError, setQueryError] = useState<string | null>(null);
  const [found, setFound] = useState<{ candidates: EcadBoard[]; truncated: boolean; hub_message: string | null } | null>(null);
  const [pendingPick, setPendingPick] = useState<EcadBoard | null>(null);
  const [confirmDetach, setConfirmDetach] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function search() {
    const problem = boardQueryProblem(query);
    setQueryError(problem);
    if (problem) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    setPendingPick(null);
    try {
      const out = await riskApi.findEcadBoards(query.trim());
      setFound({ candidates: out.candidates, truncated: out.truncated, hub_message: out.hub_message ?? null });
    } catch (err) {
      setFound(null);
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  /** 고른 행 — 이미 붙은 보드가 있으면 바꾸기 확인을 먼저 받는다(요청서 3절). */
  function pick(next: EcadBoard) {
    setNotice(null);
    if (replaceConfirmText(board, next)) setPendingPick(next);
    else void attach(next);
  }

  async function attach(next: EcadBoard) {
    if (!next.job_id || !ODB_JOB_ID_RE.test(next.job_id)) return;
    setBusy(true);
    setError(null);
    setPendingPick(null);
    try {
      const out = await riskApi.putEcadBoard(projectId, next.job_id);
      setNotice(
        out.changed
          ? "보드를 붙였습니다 — 이미 동결된 스냅샷은 그대로이고 다음 캡처부터 이 보드를 읽습니다."
          : "이미 붙은 보드입니다 — 카드의 보드 정보만 새로 적었습니다.",
      );
      setFound(null);
      setSearchOpen(false);
      setQuery("");
      onChanged();
    } catch (err) {
      // 그 사이 허브에서 사라졌거나 다른 판이 걸렸다 — 본문의 후보를 다시 보이고 자동으로 고르지 않는다.
      const again = notFoundCandidates(err);
      if (again) setFound({ candidates: again.candidates, truncated: false, hub_message: again.hub_message });
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function detach() {
    setBusy(true);
    setError(null);
    setConfirmDetach(false);
    try {
      const out = await riskApi.deleteEcadBoard(projectId);
      setNotice(out.removed > 0 ? "보드를 뗐습니다 — 다음 캡처부터 ECAD 가 빠집니다." : "붙은 보드가 없었습니다.");
      onChanged();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  // 붙이기는 과제 주인만 한다(서버도 남이면 404) — 찾기 칸도 주인에게만 연다.
  const showSearch = isOwner && route === "ready" && (source === null || searchOpen);

  return (
    <SubPanel title="ECAD" actions={<SourceStatusBadge value={source?.status ?? "unlinked"} />}>
      {route === "unavailable" ? (
        <Banner
          tone="warn"
          title="ODB 허브 도구가 게이트웨이에 없습니다 — 운영자 몫입니다."
          detail={
            ecadRow && ecadRow.tools_missing.length > 0 ? `빠진 도구 ${ecadRow.tools_missing.join(" · ")}` : undefined
          }
        />
      ) : null}
      {route === "planned" ? (
        <Banner tone="info" title="게이트웨이 도구 지도를 못 읽었습니다 — 잠시 뒤 다시 봅니다." detail={ecadRow?.gateway_error ?? undefined}>
          <Button type="button" variant="outline" size="sm" onClick={onAdaptersRetry} disabled={adaptersLoading}>
            다시 읽기
          </Button>
        </Banner>
      ) : null}

      <EcadErrorBanner error={error} onRetry={search} />
      {notice ? <Banner tone="info" live="status" title={notice} /> : null}

      {source ? (
        <>
          <KeyValueTable
            columns={1}
            rows={[
              {
                label: "보드",
                hint: "probe.board.name",
                value: board?.name ?? <span className="text-muted-foreground">이름 없음(과제 · 모델 · 보드 종류 · 판이 다 비었다)</span>,
              },
              { label: "판", hint: "revision", value: board?.revision ?? <span className="text-muted-foreground">모름</span> },
              { label: "원본 파일", hint: "original_filename", value: board?.original_filename ?? "-" },
              { label: "올린 시각", hint: "uploaded_at", value: fmtIso(board?.uploaded_at) },
              { label: "job_id", hint: "ref.odb_job_id", value: currentJobId ? <Mono>{currentJobId}</Mono> : "-" },
              {
                label: "도달 측정",
                hint: "status · probe.detail",
                value: (
                  <span className="flex flex-wrap items-center gap-2">
                    <SourceStatusBadge value={source.status} />
                    <span className="text-muted-foreground">{source.probe?.detail ?? "잰 적 없음"}</span>
                  </span>
                ),
              },
            ]}
          />
          {isOwner ? (
            <div className="flex flex-wrap items-center gap-2">
              {route === "ready" ? (
                <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setSearchOpen((v) => !v)}>
                  <Search aria-hidden="true" />
                  {searchOpen ? "바꾸기 닫기" : "바꾸기"}
                </Button>
              ) : null}
              <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => setConfirmDetach(true)}>
                <Unplug aria-hidden="true" />
                떼기
              </Button>
            </div>
          ) : null}
          {confirmDetach ? (
            <Banner tone="warn" live="status" title={DETACH_CONFIRM_TEXT}>
              <span className="flex flex-wrap items-center gap-2">
                <Button type="button" variant="destructive" size="sm" disabled={busy} onClick={detach}>
                  <Trash2 aria-hidden="true" />
                  떼기
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => setConfirmDetach(false)}>
                  그만두기
                </Button>
              </span>
            </Banner>
          ) : null}
        </>
      ) : (
        <p className="m-0 text-sm text-muted-foreground">보드 없음 — 과제마다 ODB 허브 보드 한 장을 사람이 골라 붙입니다.</p>
      )}

      {showSearch ? (
        <div className="flex flex-col gap-2">
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              void search();
            }}
          >
            <FormField
              label="보드 찾기"
              hint={`과제 · 모델 · 파일 이름 또는 job_id · ${ECAD_QUERY_MAX}자까지`}
              error={queryError ?? undefined}
              className="min-w-[16rem] flex-1"
            >
              <Input value={query} onChange={(e) => setQuery(e.target.value)} aria-label="ECAD 보드 찾을 말" />
            </FormField>
            <Button type="submit" variant="outline" disabled={busy}>
              <Search aria-hidden="true" />
              찾기
            </Button>
          </form>
          {found ? (
            <>
              {found.candidates.length === 0 ? (
                <p className="m-0 text-sm text-muted-foreground">{found.hub_message ?? "찾은 보드가 없습니다."}</p>
              ) : (
                <>
                  {found.hub_message ? <p className="m-0 text-sm text-muted-foreground">{found.hub_message}</p> : null}
                  <CandidateTable candidates={found.candidates} currentJobId={currentJobId} busy={busy} onPick={pick} />
                </>
              )}
              {found.truncated ? (
                <p className="m-0 text-sm text-muted-foreground">후보가 더 있습니다 — 검색어를 좁힙니다(서버는 10개까지 줍니다).</p>
              ) : null}
            </>
          ) : null}
          {pendingPick ? (
            <Banner tone="warn" live="status" title={replaceConfirmText(board, pendingPick) ?? ""}>
              <span className="flex flex-wrap items-center gap-2">
                <Button type="button" size="sm" disabled={busy} onClick={() => void attach(pendingPick)}>
                  바꾸기
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => setPendingPick(null)}>
                  그만두기
                </Button>
              </span>
            </Banner>
          ) : null}
        </div>
      ) : null}
    </SubPanel>
  );
}
