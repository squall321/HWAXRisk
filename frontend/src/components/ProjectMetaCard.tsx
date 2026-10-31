// 과제 머리의 메타 — 등급 칩 · 수명 주기 · 코퍼스 제외 · 소유자 · '조직 공개' 토글(보류 op 수) · 제품 연결(B34 104 · 105 · 106, plan §8.2.4 ProjectPage 머리)
import { useState } from "react";
import { isApiError, riskApi } from "../api/risk.api";
import { KeyValueTable } from "./DataTable";
import { Badge } from "./Badge";
import { ErrorBanner } from "./StateBlocks";
import { Banner, Button, Mono, Select } from "../ui/primitives";
import { fmtEpoch } from "../format";
import {
  CLASSIFICATION_LABEL,
  LIFECYCLE_LABEL,
  ROLE_LABEL,
  knownMeta,
  noProductLink,
  visibilityControl,
} from "../lib/projectMeta";
import { CLASSIFICATIONS, EXCLUDED_REASONS, LIFECYCLES } from "../types";
import type {
  Classification,
  ExcludedReason,
  Lifecycle,
  McpVisibility,
  ProjectDetail,
  ProjectMeta,
  ProjectPatch,
  ProjectPatched,
  ProjectRole,
} from "../types";

/** 서버가 그 칸을 주지 않았다는 표시 — '없음' 과 다르다(모르는 것이다). */
function NotSent() {
  return (
    <span className="text-muted-foreground" title="9bd5f48 의 과제 상세는 이 칸을 싣지 않는다 — 바꾸면 그 답으로 안다.">
      모름(이 서버가 과제 상세에 싣지 않음)
    </span>
  );
}

const EXCLUDED_REASON_LABEL: Record<ExcludedReason, string> = {
  fixture: "시험 자료",
  misregistered: "잘못 등록",
  duplicate: "중복",
  user: "사용자 판단",
};

/** 보류(withheld)된 RA op 수 — 비공개 과제의 IR · 판정이 바깥으로 나가지 않고 쌓인 수다(대상들의 반영 요약에서 센다). */
export function withheldOps(detail: Pick<ProjectDetail, "targets">): number {
  return detail.targets.reduce(
    (n, t) => n + (t.external_sync?.ra?.state === "withheld" ? Number(t.external_sync.ra.pending_ops ?? 0) : 0),
    0,
  );
}

export function ProjectMetaCard({
  detail,
  role,
  onPatched,
}: {
  detail: ProjectDetail;
  /** 이 과제에서의 내 역할 — 모르면 null(잠그지 않고 서버의 거절 code 로 말한다). */
  role: ProjectRole | null;
  onPatched: (patched: ProjectMeta) => void;
}) {
  const projectId = detail.project.id;
  const [patched, setPatched] = useState<ProjectMeta | null>(null);
  const [resynced, setResynced] = useState<ProjectPatched["resynced"] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [visibilityDenied, setVisibilityDenied] = useState(false);
  const [confirmOrg, setConfirmOrg] = useState(false);
  const [excludeReason, setExcludeReason] = useState<ExcludedReason | "">("");
  // 등급 · 수명 주기는 고른 뒤 '바꾸기' 로만 쓴다 — 전에는 고르기만 해도(화살표 키의 change 도) 곧바로 PATCH 가 나갔다.
  const [classDraft, setClassDraft] = useState<Classification | "">("");
  const [lifeDraft, setLifeDraft] = useState<Lifecycle | "">("");
  const [confirmClass, setConfirmClass] = useState(false);
  const [confirmLife, setConfirmLife] = useState(false);

  const meta = knownMeta(detail.project, patched);
  const control = visibilityControl(visibilityDenied ? "editor" : role, meta.mcp_visibility as McpVisibility | null);
  const editorLocked = role === "viewer";
  const withheld = withheldOps(detail);
  const noProduct = noProductLink(meta);

  async function patch(body: ProjectPatch, what: "visibility" | "other" = "other") {
    setBusy(true);
    setError(null);
    try {
      const out = await riskApi.patchProject(projectId, body);
      setPatched(out.project);
      if (what === "visibility") setResynced(out.resynced ?? null);
      if ("classification" in body) setClassDraft("");
      if ("lifecycle" in body) setLifeDraft("");
      onPatched(out.project);
    } catch (err) {
      // 소유자가 아니면 403 role_insufficient — code 로 토글을 잠근다(문구로 가르지 않는다).
      if (what === "visibility" && isApiError(err) && err.code === "role_insufficient") setVisibilityDenied(true);
      setError(err);
    } finally {
      setBusy(false);
      setConfirmOrg(false);
      setConfirmClass(false);
      setConfirmLife(false);
    }
  }

  /** 등급 바꾸기 — confidential(또는 모름 — 등록 때 기본이 기밀이다)에서 internal 로 낮추는 것은 반출 경계를 넓히므로 확인받는다. */
  function applyClassification() {
    if (classDraft === "") return;
    if (classDraft === "internal" && meta.classification !== "internal") setConfirmClass(true);
    else void patch({ classification: classDraft });
  }

  /** 수명 주기 바꾸기 — 진행(active)을 떠나면 서버가 닫은 때(closed_at)를 찍으므로 확인받는다. */
  function applyLifecycle() {
    if (lifeDraft === "") return;
    if (lifeDraft !== "active" && meta.lifecycle !== lifeDraft && (meta.lifecycle === "active" || meta.lifecycle === undefined)) {
      setConfirmLife(true);
    } else {
      void patch({ lifecycle: lifeDraft });
    }
  }

  const visibilityValue = (
    <span className="flex flex-col gap-1.5">
      <span className="flex flex-wrap items-center gap-2">
        {control.known ? (
          <Badge tone={meta.mcp_visibility === "org" ? "info" : "muted"}>
            {meta.mcp_visibility === "org" ? "조직 공개(org)" : "비공개(private)"}
          </Badge>
        ) : (
          <NotSent />
        )}
        {control.locked ? (
          <span className="text-xs text-muted-foreground">{control.lockReason}</span>
        ) : (
          <>
            {meta.mcp_visibility !== "org" ? (
              <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setConfirmOrg(true)}>
                조직에 공개
              </Button>
            ) : null}
            {meta.mcp_visibility !== "private" ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => void patch({ mcp_visibility: "private" }, "visibility")}
              >
                비공개로
              </Button>
            ) : null}
          </>
        )}
      </span>
      {meta.mcp_visibility !== "org" ? (
        <span className="text-xs text-muted-foreground">
          비공개면 이 과제의 IR · 판정은 RA · 다른 심의 도구에 나가지 않습니다(보류 op {withheld}건).
        </span>
      ) : null}
      {confirmOrg ? (
        <Banner
          tone="warn"
          live="status"
          title="조직에 공개합니다."
          detail={`이 과제의 IR · 판정이 RA 와 조직의 다른 심의 도구에 나갑니다 — 보류된 RA op ${withheld}건이 풀려 보내기 줄에 다시 섭니다.`}
        >
          <span className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" disabled={busy} onClick={() => void patch({ mcp_visibility: "org" }, "visibility")}>
              공개
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => setConfirmOrg(false)}>
              그만두기
            </Button>
          </span>
        </Banner>
      ) : null}
      {resynced ? (
        <span className="text-xs text-muted-foreground">
          풀린 대상 {resynced.targets}개 · RA op {resynced.ra_ops_released}건
          {resynced.adh_retag_ops !== undefined ? ` · AIDataHub 태그 다시 붙이기 ${resynced.adh_retag_ops}건` : ""}
        </span>
      ) : null}
    </span>
  );

  return (
    <>
      <ErrorBanner error={error} />
      <KeyValueTable
        rows={[
          { label: "소유자", hint: "owner_sub", value: <Mono>{detail.project.owner_sub}</Mono> },
          {
            label: "내 역할",
            hint: "members[me].role",
            value: role ? <Badge tone="neutral">{ROLE_LABEL[role]}</Badge> : <span className="text-muted-foreground">모름</span>,
          },
          {
            label: "등급",
            hint: "classification",
            value: (
              <span className="flex flex-wrap items-center gap-2">
                {meta.classification ? (
                  <Badge tone={meta.classification === "confidential" ? "warn" : "neutral"}>
                    {CLASSIFICATION_LABEL[meta.classification as Classification] ?? meta.classification}
                  </Badge>
                ) : (
                  <NotSent />
                )}
                <Select
                  className="w-auto min-w-[10rem]"
                  aria-label="등급 바꾸기"
                  value={classDraft}
                  disabled={busy || editorLocked}
                  onChange={(e) => {
                    setClassDraft(e.target.value as Classification | "");
                    setConfirmClass(false);
                  }}
                >
                  <option value="">바꿀 등급…</option>
                  {CLASSIFICATIONS.map((c) => (
                    <option key={c} value={c}>
                      {CLASSIFICATION_LABEL[c]}
                    </option>
                  ))}
                </Select>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy || editorLocked || classDraft === "" || classDraft === meta.classification}
                  onClick={applyClassification}
                >
                  바꾸기
                </Button>
                <span className="text-xs text-muted-foreground">confidential → internal 은 소유자만 합니다.</span>
                {confirmClass ? (
                  <Banner
                    tone="warn"
                    live="status"
                    title="등급을 internal(사내 일반)로 낮춥니다."
                    detail={`등급은 반출 경계입니다 — 낮추면 이 과제는 내보내기의 최고 등급(X-Risk-Classification-Max)에서 기밀로 세어지지 않습니다.${
                      meta.classification === undefined ? " 이 서버는 지금 등급을 과제 상세에 싣지 않아, 등록 때 기본인 기밀일 수 있다고 보고 묻습니다." : ""
                    }`}
                  >
                    <span className="flex flex-wrap items-center gap-2">
                      <Button type="button" size="sm" disabled={busy} onClick={() => void patch({ classification: "internal" })}>
                        낮추기
                      </Button>
                      <Button type="button" variant="ghost" size="sm" onClick={() => setConfirmClass(false)}>
                        그만두기
                      </Button>
                    </span>
                  </Banner>
                ) : null}
              </span>
            ),
          },
          {
            label: "수명 주기",
            hint: "lifecycle",
            value: (
              <span className="flex flex-wrap items-center gap-2">
                {meta.lifecycle ? (
                  <Badge tone={meta.lifecycle === "active" ? "ok" : "muted"}>
                    {LIFECYCLE_LABEL[meta.lifecycle as Lifecycle] ?? meta.lifecycle} {meta.lifecycle}
                  </Badge>
                ) : (
                  <NotSent />
                )}
                <Select
                  className="w-auto min-w-[10rem]"
                  aria-label="수명 주기 바꾸기"
                  value={lifeDraft}
                  disabled={busy || editorLocked}
                  onChange={(e) => {
                    setLifeDraft(e.target.value as Lifecycle | "");
                    setConfirmLife(false);
                  }}
                >
                  <option value="">바꿀 수명 주기…</option>
                  {LIFECYCLES.map((l) => (
                    <option key={l} value={l}>
                      {LIFECYCLE_LABEL[l]} {l}
                    </option>
                  ))}
                </Select>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy || editorLocked || lifeDraft === "" || lifeDraft === meta.lifecycle}
                  onClick={applyLifecycle}
                >
                  바꾸기
                </Button>
                {patched?.closed_at ? <span className="text-xs text-muted-foreground">닫은 때 {fmtEpoch(patched.closed_at)}</span> : null}
                {confirmLife && lifeDraft !== "" ? (
                  <Banner
                    tone="warn"
                    live="status"
                    title={`수명 주기를 바꿉니다 — ${LIFECYCLE_LABEL[lifeDraft]}(${lifeDraft}).`}
                    detail="진행(active)을 떠나면 서버가 닫은 때(closed_at)를 지금으로 찍습니다."
                  >
                    <span className="flex flex-wrap items-center gap-2">
                      <Button type="button" size="sm" disabled={busy} onClick={() => void patch({ lifecycle: lifeDraft })}>
                        바꾸기
                      </Button>
                      <Button type="button" variant="ghost" size="sm" onClick={() => setConfirmLife(false)}>
                        그만두기
                      </Button>
                    </span>
                  </Banner>
                ) : null}
              </span>
            ),
          },
          {
            label: "코퍼스 제외",
            hint: "corpus_excluded · excluded_reason",
            value: (
              <span className="flex flex-wrap items-center gap-2">
                {meta.corpus_excluded === undefined ? (
                  <NotSent />
                ) : meta.corpus_excluded ? (
                  <Badge tone="warn">
                    코퍼스 제외 {meta.excluded_reason ? `— ${EXCLUDED_REASON_LABEL[meta.excluded_reason as ExcludedReason] ?? meta.excluded_reason}` : ""}
                  </Badge>
                ) : (
                  <Badge tone="muted">포함</Badge>
                )}
                <Select
                  className="w-auto min-w-[9rem]"
                  aria-label="코퍼스 제외 사유"
                  value={excludeReason}
                  disabled={busy || editorLocked}
                  onChange={(e) => setExcludeReason(e.target.value as ExcludedReason | "")}
                >
                  <option value="">제외 사유…</option>
                  {EXCLUDED_REASONS.map((r) => (
                    <option key={r} value={r}>
                      {EXCLUDED_REASON_LABEL[r]} {r}
                    </option>
                  ))}
                </Select>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={busy || editorLocked || excludeReason === ""}
                  onClick={() => excludeReason !== "" && void patch({ corpus_excluded: true, excluded_reason: excludeReason })}
                >
                  코퍼스에서 빼기
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={busy || editorLocked || meta.corpus_excluded === false}
                  onClick={() => void patch({ corpus_excluded: false })}
                >
                  다시 넣기
                </Button>
              </span>
            ),
          },
          { label: "조직 공개", hint: "mcp_visibility · 소유자만", value: visibilityValue },
          {
            label: "제품 연결",
            hint: "product_refs_json · product_code",
            value:
              noProduct === null ? (
                <NotSent />
              ) : noProduct ? (
                <Badge tone="warn" title="제품 연결이 없으면 라벨 경로의 제품 일치가 늘 0 이라 자동 확정이 안 됩니다(§7.6).">
                  제품 연결 없음
                </Badge>
              ) : (
                <span className="inline-flex flex-wrap items-center gap-1">
                  {(meta.product_refs ?? []).map((r) => (
                    <Badge key={`${r.kind}:${r.value}`} tone="neutral" title={r.kind}>
                      {r.value}
                    </Badge>
                  ))}
                  {meta.product_code && !(meta.product_refs ?? []).some((r) => r.value === meta.product_code) ? (
                    <Badge tone="neutral" title="product_code">
                      {meta.product_code}
                    </Badge>
                  ) : null}
                </span>
              ),
          },
        ]}
      />
    </>
  );
}
