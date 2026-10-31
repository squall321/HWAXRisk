// 앱 REST 얇은 클라이언트 — 계획 §8.2.3 을 1:1 로 감싼다. 모든 경로는 상대 'api/…' 라 /apps/hwax_risk/ 아래서 그대로 풀린다.
import type {
  AdapterList,
  ApiErrorBody,
  CellList,
  CellsDisposed,
  CellsRetryBody,
  CellsSkipBody,
  CellState,
  CloseAcked,
  CloseAckRevoked,
  Closure,
  ExpertList,
  ExpertReportPage,
  ExpertReportPart,
  IssueActed,
  IssueAction,
  IssueList,
  RegistryQuery,
  RegistryStatusSet,
  ReportAssembled,
  ReviewJobCreate,
  ReviewJobCreated,
  SynthJobCreated,
  SynthPart,
  SynthReportPage,
  Undeferred,
  UnitManifest,
  AuditPage,
  Brief,
  CharacterProfile,
  Coverage,
  HumanFindingCreate,
  HumanFindingCreated,
  CurationDecided,
  CurationDecision,
  CurationList,
  DiffCreate,
  DiffCreated,
  DiffDoc,
  DiffEvents,
  DiffSummary,
  DimDef,
  DimDefCreate,
  EcadBoardDeleted,
  EcadBoardPut,
  EcadBoardSearch,
  GateAcked,
  GateId,
  Requirement,
  RequirementCreate,
  RequirementList,
  Health,
  IfaceLedgerRow,
  ImportResult,
  JobStateResponse,
  Me,
  Metrics,
  PanelList,
  PanelComplete,
  PanelCompleted,
  PanelTranscript,
  PartKey,
  DiffListRow,
  Paged,
  PortalPatAuto,
  PortalPatPutResult,
  ReportListRow,
  TargetListRow,
  Precedents,
  Project,
  ProjectCreate,
  ProjectDetail,
  ProjectList,
  ProjectMembers,
  ProjectMembersPut,
  ProjectPatch,
  ProjectPatched,
  ProjectPurged,
  ProjectTransferred,
  RefResolution,
  Registry,
  RegistryStatusUpdate,
  ResyncQueued,
  RosterRefreshed,
  RuleHitList,
  SameAs,
  SameAsDecided,
  SameAsDecision,
  SeatList,
  SeatUpdate,
  SeatUpdated,
  Similar,
  SnapshotCallList,
  SnapshotCreate,
  SnapshotCreated,
  SnapshotIr,
  SnapshotState,
  SourceCreate,
  SourceCreated,
  Taxonomy,
  TargetCreate,
  TargetCreated,
  TargetJobCreate,
  TargetJobCreated,
  VerdictSaved,
  VerdictUpdate,
  VocabBump,
  VocabIndex,
  VocabOp,
} from "../types";

/** REST base. 절대경로·오리진을 하드코딩하지 않는다 — Vite base './' 와 짝이다. */
export const API_BASE = "api/";

/** 401 안내 문구(§8.2.4 오류 규약). 앱에는 로그인 화면도 리다이렉트도 없다. */
export const SIGN_IN_HINT = "포털 메뉴 '리스크 심사' 에서 HEAX 로그인을 먼저 하세요.";

/** 서버가 낸 {error:{code,message}} 를 그대로 실은 예외. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** 오류 본문 전체(409 `{gates}` 처럼 code 밖에 실리는 값을 화면이 읽는다). */
  readonly body: unknown;

  constructor(status: number, code: string, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

/**
 * 아직 서버에 없는 경로 — 404 · 501 · code 'not_implemented'.
 * 404 는 '소유자 불일치' 이기도 하므로(§8.2.4) 화면은 `reason` 으로 문구를 고른다.
 */
export class NotReadyError extends ApiError {
  readonly reason: "not_implemented" | "not_found";

  constructor(status: number, code: string, message: string, body?: unknown) {
    super(status, code, message, body);
    this.name = "NotReadyError";
    this.reason = status === 404 && code !== "not_implemented" ? "not_found" : "not_implemented";
  }
}

/** 서버에 닿지 못했을 때(네트워크·중단). */
export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NetworkError";
  }
}

export function isApiError(err: unknown): err is ApiError {
  return err instanceof ApiError;
}

/** '아직 준비 중' 으로 접어야 하는 오류인지. */
export function isNotReady(err: unknown): err is NotReadyError {
  return err instanceof NotReadyError;
}

/** 요청이 취소돼 화면이 아무것도 하지 않아야 하는 경우(언마운트·폴링 중단). */
export function isAborted(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

/** 오류 배너 한 줄용 — 모든 화면이 같은 문구를 쓰도록 여기서만 만든다. */
export function describeError(err: unknown): { tone: "info" | "error"; title: string; detail: string } {
  if (isNotReady(err)) {
    return err.reason === "not_found"
      ? { tone: "info", title: "찾을 수 없습니다.", detail: "삭제됐거나 내 소유가 아닌 항목입니다." }
      : { tone: "info", title: "아직 준비 중입니다.", detail: "이 화면이 쓰는 서버 경로가 아직 없습니다." };
  }
  if (err instanceof ApiError) {
    if (err.status === 401) return { tone: "error", title: "로그인이 필요합니다.", detail: SIGN_IN_HINT };
    if (err.status === 403) return { tone: "error", title: "권한이 없습니다.", detail: err.message };
    if (err.status === 409) return { tone: "error", title: "지금은 진행할 수 없습니다.", detail: err.message };
    if (err.status === 422) return { tone: "error", title: "입력을 확인하세요.", detail: err.message };
    return { tone: "error", title: `요청 실패 (${err.status}).`, detail: err.message };
  }
  if (err instanceof NetworkError) {
    return { tone: "error", title: "서버에 닿지 못했습니다.", detail: err.message };
  }
  return { tone: "error", title: "오류가 발생했습니다.", detail: err instanceof Error ? err.message : String(err) };
}

type Query = Record<string, string | number | boolean | undefined | null>;

function withQuery(path: string, query?: Query): string {
  if (!query) return API_BASE + path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const qs = params.toString();
  return API_BASE + path + (qs ? `?${qs}` : "");
}

function toError(status: number, raw: string): ApiError {
  let code = `http_${status}`;
  let message = raw.slice(0, 400) || `HTTP ${status}`;
  try {
    const parsed = JSON.parse(raw) as Partial<ApiErrorBody> & { detail?: unknown };
    if (parsed && typeof parsed === "object" && parsed.error && typeof parsed.error === "object") {
      code = parsed.error.code ?? code;
      message = parsed.error.message ?? message;
    } else if (parsed && typeof parsed.detail === "string") {
      message = parsed.detail;
    }
    if (status === 404 || status === 501 || code === "not_implemented") {
      return new NotReadyError(status, code, message, parsed);
    }
    return new ApiError(status, code, message, parsed);
  } catch {
    if (status === 404 || status === 501) return new NotReadyError(status, code, message);
    return new ApiError(status, code, message);
  }
}

type RequestOptions = { method?: string; body?: unknown; query?: Query; signal?: AbortSignal };

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal } = options;
  let res: Response;
  try {
    res = await fetch(withQuery(path, query), {
      method,
      // 브라우저가 이미 가진 heax 쿠키에 실려 나간다 — 코드는 토큰을 만지지 않는다.
      credentials: "same-origin",
      headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (isAborted(err)) throw err;
    throw new NetworkError(err instanceof Error ? err.message : String(err));
  }
  const raw = await res.text();
  if (!res.ok) throw toError(res.status, raw);
  if (!raw) return undefined as T;
  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new ApiError(res.status, "bad_json", "서버 응답을 JSON 으로 읽을 수 없습니다.");
  }
}

async function requestText(path: string, options: RequestOptions = {}): Promise<string> {
  const { method = "GET", body, query, signal } = options;
  let res: Response;
  try {
    res = await fetch(withQuery(path, query), {
      method,
      credentials: "same-origin",
      headers: body === undefined ? {} : { "Content-Type": "application/x-ndjson" },
      body: body === undefined ? undefined : String(body),
      signal,
    });
  } catch (err) {
    if (isAborted(err)) throw err;
    throw new NetworkError(err instanceof Error ? err.message : String(err));
  }
  const raw = await res.text();
  if (!res.ok) throw toError(res.status, raw);
  return raw;
}

/** `snap:<id>` / `diff:<id>` 형태의 target_key 를 URL 경로 조각으로. */
export const encodeTargetKey = (key: string): string => encodeURIComponent(key);

type Opt = { signal?: AbortSignal };

export const riskApi = {
  // ── 신원·메타 ──────────────────────────────────────────────────────────────
  getHealth: (o?: Opt) => request<Health>("health", o),
  getMe: (o?: Opt) => request<Me>("me", o),
  /**
   * `source` 는 앱이 받아 온 PAT(포털 발급 버튼 · 자동 등록)일 때만 `web` 을 싣는다 — 백엔드는 갈아 끼울 때 앞선 등록의 출처가
   * web · gateway-exchange 일 때만 옛 PAT 를 폐기한다. 사람이 붙여 넣은 PAT 와 삭제(null)는 싣지 않는다(= manual).
   */
  putPortalPat: (pat: string | null, source?: "web", o?: Opt) =>
    request<PortalPatPutResult>("me/portal-pat", {
      method: "PUT",
      body: source ? { pat, source } : { pat },
      ...o,
    }),
  putPortalPatAuto: (enabled: boolean, o?: Opt) =>
    request<PortalPatAuto>("me/portal-pat-auto", { method: "PUT", body: { enabled }, ...o }),
  getTaxonomy: (o?: Opt) => request<Taxonomy>("meta/taxonomy", o),
  getAdapters: (o?: Opt) => request<AdapterList>("meta/adapters", o),
  getVocab: (o?: Opt) => request<VocabIndex>("meta/vocab", o),
  getMetrics: (o?: Opt) => request<Metrics>("meta/metrics", o),

  // ── 과제 ──────────────────────────────────────────────────────────────────
  listProjects: (o?: Opt) => request<ProjectList>("projects", o),
  createProject: (body: ProjectCreate, o?: Opt) => request<Project>("projects", { method: "POST", body, ...o }),
  getProject: (id: string, o?: Opt) => request<ProjectDetail>(`projects/${encodeURIComponent(id)}`, o),
  /** 과제 메타(editor, `mcp_visibility` 는 owner 만 — 아니면 403 role_insufficient). */
  patchProject: (id: string, body: ProjectPatch, o?: Opt) =>
    request<ProjectPatched>(`projects/${encodeURIComponent(id)}`, { method: "PATCH", body, ...o }),
  getMembers: (id: string, o?: Opt) => request<ProjectMembers>(`projects/${encodeURIComponent(id)}/members`, o),
  putMembers: (id: string, body: ProjectMembersPut, o?: Opt) =>
    request<ProjectMembers>(`projects/${encodeURIComponent(id)}/members`, { method: "PUT", body, ...o }),
  transferProject: (id: string, body: { to_email: string; reason: string }, o?: Opt) =>
    request<ProjectTransferred>(`projects/${encodeURIComponent(id)}/transfer`, { method: "POST", body, ...o }),
  purgeProject: (id: string, body: { code: string; reason: string }, o?: Opt) =>
    request<ProjectPurged>(`projects/${encodeURIComponent(id)}/purge`, { method: "POST", body, ...o }),
  getProjectAudit: (id: string, q?: { action?: string; limit?: number; offset?: number }, o?: Opt) =>
    request<AuditPage>(`projects/${encodeURIComponent(id)}/audit`, { query: q, ...o }),
  addSource: (id: string, body: SourceCreate, o?: Opt) =>
    request<SourceCreated>(`projects/${encodeURIComponent(id)}/sources`, { method: "POST", body, ...o }),
  // ECAD 보드 — 찾기는 과제에 묶이지 않는다. 붙이기 · 떼기는 과제 주인만(남이면 없는 것과 같은 404).
  findEcadBoards: (q: string, o?: Opt) => request<EcadBoardSearch>("ecad/boards", { query: { q }, ...o }),
  putEcadBoard: (id: string, odbJobId: string, o?: Opt) =>
    request<EcadBoardPut>(`projects/${encodeURIComponent(id)}/ecad-board`, {
      method: "PUT",
      body: { odb_job_id: odbJobId },
      ...o,
    }),
  deleteEcadBoard: (id: string, o?: Opt) =>
    request<EcadBoardDeleted>(`projects/${encodeURIComponent(id)}/ecad-board`, { method: "DELETE", ...o }),
  createSnapshot: (id: string, body: SnapshotCreate, o?: Opt) =>
    request<SnapshotCreated>(`projects/${encodeURIComponent(id)}/snapshots`, { method: "POST", body, ...o }),
  listRequirements: (id: string, o?: Opt) =>
    request<RequirementList>(`projects/${encodeURIComponent(id)}/requirements`, o),
  upsertRequirements: (id: string, body: RequirementCreate[], o?: Opt) =>
    request<{ upserted: number; rows: Requirement[]; recompute: string[] }>(
      `projects/${encodeURIComponent(id)}/requirements`,
      { method: "POST", body, ...o },
    ),
  decideRequirement: (rid: string, body: { status: string; waive_reason?: string | null }, o?: Opt) =>
    request<Requirement>(`requirements/${encodeURIComponent(rid)}`, { method: "PUT", body, ...o }),
  inheritRequirements: (id: string, fromProjectId: string, o?: Opt) =>
    request<{ copied: number; skipped: number }>(`projects/${encodeURIComponent(id)}/requirements/inherit`, {
      method: "POST",
      body: { from_project_id: fromProjectId },
      ...o,
    }),
  createDim: (id: string, body: DimDefCreate, o?: Opt) =>
    request<DimDef>(`projects/${encodeURIComponent(id)}/dims`, { method: "POST", body, ...o }),
  putIfaceLedger: (id: string, rows: IfaceLedgerRow[], o?: Opt) =>
    request<IfaceLedgerRow[]>(`projects/${encodeURIComponent(id)}/iface-ledger`, { method: "PUT", body: rows, ...o }),
  getCharacter: (id: string, o?: Opt) => request<CharacterProfile>(`projects/${encodeURIComponent(id)}/character`, o),
  getSimilar: (id: string, o?: Opt) => request<Similar>(`projects/${encodeURIComponent(id)}/similar`, o),

  // ── 스냅샷 ────────────────────────────────────────────────────────────────
  getSnapshotIr: (id: string, o?: Opt) =>
    request<SnapshotIr>(`snapshots/${encodeURIComponent(id)}`, { query: { part: "ir" }, ...o }),
  getSnapshotState: (id: string, o?: Opt) =>
    request<SnapshotState>(`snapshots/${encodeURIComponent(id)}`, { query: { part: "state" }, ...o }),
  getSnapshotCalls: (id: string, o?: Opt) =>
    request<SnapshotCallList>(`snapshots/${encodeURIComponent(id)}`, { query: { part: "calls" }, ...o }),
  getRuleHits: (id: string, o?: Opt) =>
    request<RuleHitList>(`snapshots/${encodeURIComponent(id)}/rule_hits`, o),
  /** fail 게이트에 사유를 적고 진행한다(G6 은 422 gate_blocking). ack 해도 pass 는 그대로다. */
  ackGate: (id: string, gate: GateId, reason: string, o?: Opt) =>
    request<GateAcked>(`snapshots/${encodeURIComponent(id)}/gates/${gate}/ack`, {
      method: "POST",
      body: { reason },
      ...o,
    }),
  revokeGateAck: (id: string, gate: GateId, o?: Opt) =>
    request<GateAcked>(`snapshots/${encodeURIComponent(id)}/gates/${gate}/ack`, { method: "DELETE", ...o }),

  // ── same-as · diff ────────────────────────────────────────────────────────
  getSameAs: (base: string, target: string, o?: Opt) => request<SameAs>("sameas", { query: { base, target }, ...o }),
  decideSameAs: (decisions: SameAsDecision[], o?: Opt) =>
    request<SameAsDecided>("sameas/decide", { method: "POST", body: decisions, ...o }),
  /** 키 대장 한 행의 지금 상태(병합 · 이름 · 정한 사람) — 원장에 없거나 볼 수 없으면 404 `E404`. */
  getPartKey: (ckey: string, o?: Opt) => request<PartKey>(`part-keys/${encodeURIComponent(ckey)}`, o),
  createDiff: (body: DiffCreate, o?: Opt) => request<DiffCreated>("diffs", { method: "POST", body, ...o }),
  // 목록 3종 — 홈 탭 3개가 이 셋이 없어 '아직 없습니다' 였다(정본 §8.2.4).
  listDiffs: (q?: { project_id?: string; limit?: number; offset?: number }, o?: Opt) =>
    request<Paged<"diffs", DiffListRow>>("diffs", { query: q, ...o }),
  listTargets: (q?: { project_id?: string; include_superseded?: boolean; limit?: number; offset?: number },
                o?: Opt) => request<Paged<"targets", TargetListRow>>("targets", { query: q, ...o }),
  listReports: (q?: { project_id?: string; limit?: number; offset?: number }, o?: Opt) =>
    request<Paged<"reports", ReportListRow>>("reports", { query: q, ...o }),

  getDiff: (id: string, o?: Opt) => request<DiffDoc>(`diffs/${encodeURIComponent(id)}`, { query: { part: "diff" }, ...o }),
  getDiffSummary: (id: string, o?: Opt) =>
    request<DiffSummary>(`diffs/${encodeURIComponent(id)}`, { query: { part: "summary" }, ...o }),
  getDiffEvents: (id: string, o?: Opt) =>
    request<DiffEvents>(`diffs/${encodeURIComponent(id)}`, { query: { part: "events" }, ...o }),
  getPrecedents: (diffId: string, o?: Opt) => request<Precedents>("precedents", { query: { diff_id: diffId }, ...o }),

  // ── 타깃 · 잡 ─────────────────────────────────────────────────────────────
  createTarget: (body: TargetCreate, o?: Opt) => request<TargetCreated>("targets", { method: "POST", body, ...o }),
  createTargetJob: (key: string, body: TargetJobCreate, o?: Opt) =>
    request<TargetJobCreated>(`targets/${encodeTargetKey(key)}/jobs`, { method: "POST", body, ...o }),
  pauseJob: (jobId: string, o?: Opt) =>
    request<JobStateResponse>(`jobs/${encodeURIComponent(jobId)}/pause`, { method: "POST", ...o }),
  /**
   * 재개 — `consent` 는 검토 잡이 다시 연 셀의 몫을 넘어 멈췄을 때(reopened_extra.hold consent_extra) 사람이 그 몫에 동의한 뒤에만
   * 참이다(쿼리 consent=true). 그 밖의 재개는 쿼리를 싣지 않는다.
   */
  resumeJob: (jobId: string, o?: Opt & { consent?: true }) =>
    request<JobStateResponse>(`jobs/${encodeURIComponent(jobId)}/resume`, {
      method: "POST",
      query: o?.consent ? { consent: true } : undefined,
      signal: o?.signal,
    }),
  cancelJob: (jobId: string, o?: Opt) =>
    request<JobStateResponse>(`jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST", ...o }),

  getCoverage: (key: string, o?: Opt) => request<Coverage>(`targets/${encodeTargetKey(key)}/coverage`, o),
  getSeats: (key: string, domain: string, o?: Opt) =>
    request<SeatList>(`targets/${encodeTargetKey(key)}/seats`, { query: { domain }, ...o }),
  /** 좌석을 사람이 옮긴다 — skipped(사유 필수) · carried 되돌리기(pending). */
  putSeat: (key: string, agentKey: string, body: SeatUpdate, o?: Opt) =>
    request<SeatUpdated>(`targets/${encodeTargetKey(key)}/coverage/${encodeURIComponent(agentKey)}`, {
      method: "PUT",
      body,
      ...o,
    }),
  getRegistry: (key: string, query?: RegistryQuery, o?: Opt) =>
    request<Registry>(`targets/${encodeTargetKey(key)}/registry`, { query, ...o }),
  /** `kind` — coverage(Tier 패널) · issue(쟁점 패널). 없으면 둘 다. */
  getPanels: (key: string, kind?: "coverage" | "issue", o?: Opt) =>
    request<PanelList>(`targets/${encodeTargetKey(key)}/panels`, { query: { kind }, ...o }),
  getPanelTranscript: (panelId: string, o?: Opt) =>
    request<PanelTranscript>(`panels/${encodeURIComponent(panelId)}/transcript`, o),
  getBrief: (key: string, tier?: string, o?: Opt) =>
    request<Brief>(`targets/${encodeTargetKey(key)}/brief`, { query: { tier }, ...o }),
  putVerdict: (key: string, body: VerdictUpdate, o?: Opt) =>
    request<VerdictSaved>(`targets/${encodeTargetKey(key)}/verdict`, { method: "PUT", body, ...o }),
  putRegistryStatus: (cluster: string, body: RegistryStatusUpdate, o?: Opt) =>
    request<RegistryStatusSet>(`registry/${encodeURIComponent(cluster)}/status`, { method: "PUT", body, ...o }),
  completePanel: (panelId: string, body: PanelComplete, o?: Opt) =>
    request<PanelCompleted>(`panels/${encodeURIComponent(panelId)}/complete`, { method: "POST", body, ...o }),
  // ── 카드 대조 검토 · 쟁점 · 종합 보고서 · 완결(재설계 M2 · M3 — 포털 m3-frontend-request.md) ─────────────
  /** 검토 잡(mode reviews) — 동의 문턱을 넘는 추정이면 consent 없이는 아무것도 바꾸기 전에 422 consent_required 다. */
  createReviewJob: (key: string, body: ReviewJobCreate, o?: Opt) =>
    request<ReviewJobCreated>(`targets/${encodeTargetKey(key)}/jobs`, { method: "POST", body, ...o }),
  getUnits: (key: string, o?: Opt) => request<UnitManifest>(`targets/${encodeTargetKey(key)}/units`, o),
  getCells: (
    key: string,
    query: {
      agent_key?: string;
      unit_id?: string;
      domain?: string;
      state?: CellState;
      job_id?: string;
      route?: string;
      limit?: number;
      offset?: number;
    },
    o?: Opt,
  ) => request<CellList>(`targets/${encodeTargetKey(key)}/cells`, { query, ...o }),
  retryCells: (key: string, body: CellsRetryBody, o?: Opt) =>
    request<CellsDisposed>(`targets/${encodeTargetKey(key)}/cells/retry`, { method: "POST", body, ...o }),
  skipCells: (key: string, body: CellsSkipBody, o?: Opt) =>
    request<CellsDisposed>(`targets/${encodeTargetKey(key)}/cells/skip`, { method: "POST", body, ...o }),
  /** 패널 대상의 보류(deferred) 좌석을 사람이 푼다 — 사유 4~300자, 도는 잡이 있으면 409 job_live. */
  undefer: (key: string, reason: string, o?: Opt) =>
    request<Undeferred>(`targets/${encodeTargetKey(key)}/undefer`, { method: "POST", body: { reason }, ...o }),
  getExperts: (key: string, o?: Opt) => request<ExpertList>(`targets/${encodeTargetKey(key)}/experts`, o),
  /** 전문가 보고서 쪽 — 둘째 쪽부터 첫 쪽의 version 을 실어 보낸다(그사이 다시 마감되면 409 report_version_moved). */
  getExpertReport: (
    key: string,
    agentKey: string,
    query: { part: ExpertReportPart; page: number; version?: number },
    o?: Opt,
  ) =>
    request<ExpertReportPage>(`targets/${encodeTargetKey(key)}/experts/${encodeURIComponent(agentKey)}/report`, {
      query: { format: "md", ...query },
      ...o,
    }),
  getIssues: (
    key: string,
    query: { state?: string; p_class?: string; type?: string; limit?: number; offset?: number },
    o?: Opt,
  ) => request<IssueList>(`targets/${encodeTargetKey(key)}/issues`, { query, ...o }),
  putIssue: (issueId: string, body: IssueAction, o?: Opt) =>
    request<IssueActed>(`issues/${encodeURIComponent(issueId)}`, { method: "PUT", body, ...o }),
  /** 종합 보고서 쪽 — 지금 판만 읽힌다. `version` 은 대조 칸이다(둘째 쪽부터 첫 쪽의 판을 싣는다). */
  getReport: (key: string, query: { part: SynthPart; page: number; version?: number }, o?: Opt) =>
    request<SynthReportPage>(`targets/${encodeTargetKey(key)}/report`, { query: { format: "md", ...query }, ...o }),
  /** 다시 내기 — false 는 코드 조립 판(그 자리에서), true 는 종합 잡(영역 요약 → 과제 종합 → 판). */
  assembleReport: (key: string, o?: Opt) =>
    request<ReportAssembled>(`targets/${encodeTargetKey(key)}/report`, {
      method: "POST",
      body: { refresh_summaries: false },
      ...o,
    }),
  createSynthJob: (key: string, o?: Opt) =>
    request<SynthJobCreated>(`targets/${encodeTargetKey(key)}/report`, {
      method: "POST",
      body: { refresh_summaries: true },
      ...o,
    }),
  /** 완결 판정 — 진행판과 같은 캐시를 읽고 `fresh` 면 그 자리에서 다시 센다(버튼으로만). */
  getClosure: (key: string, fresh = false, o?: Opt) =>
    request<Closure>(`targets/${encodeTargetKey(key)}/closure`, { query: { fresh: fresh ? 1 : undefined }, ...o }),
  /** 막음 잔여 확인 — `basisHash` 는 지금 읽은 그 잔여 행의 값 그대로(그사이 바뀌었으면 409 residual_changed). */
  ackClosure: (key: string, item: string, reason: string, basisHash: string, o?: Opt) =>
    request<CloseAcked>(`targets/${encodeTargetKey(key)}/closure/acks/${encodeURIComponent(item)}`, {
      method: "POST",
      body: { reason, basis_hash: basisHash },
      ...o,
    }),
  revokeClosureAck: (key: string, item: string, o?: Opt) =>
    request<CloseAckRevoked>(`targets/${encodeTargetKey(key)}/closure/acks/${encodeURIComponent(item)}`, {
      method: "DELETE",
      ...o,
    }),
  resyncTarget: (key: string, o?: Opt) =>
    request<ResyncQueued>(`targets/${encodeTargetKey(key)}/resync`, { method: "POST", ...o }),
  refreshRoster: (key: string, o?: Opt) =>
    request<RosterRefreshed>(`targets/${encodeTargetKey(key)}/refresh_roster`, { method: "POST", ...o }),

  // ── 사람 finding · 사전 ───────────────────────────────────────────────────
  createFinding: (key: string, body: HumanFindingCreate, o?: Opt) =>
    request<HumanFindingCreated>(`targets/${encodeTargetKey(key)}/findings`, { method: "POST", body, ...o }),
  putVocabSynonym: (body: { head: string; from: string[]; op: VocabOp }, o?: Opt) =>
    request<VocabBump>("vocab/synonyms", { method: "POST", body, ...o }),
  putVocabStopTokens: (body: { tokens: string[]; op: VocabOp }, o?: Opt) =>
    request<VocabBump>("vocab/stop-tokens", { method: "POST", body, ...o }),

  // ── 큐레이션 큐 ───────────────────────────────────────────────────────────
  getCuration: (query: { kind?: string; status?: string; limit?: number } = {}, o?: Opt) =>
    request<CurationList>("curation", { query, ...o }),
  decideCuration: (queueId: string, body: CurationDecision, o?: Opt) =>
    request<CurationDecided>(`curation/${encodeURIComponent(queueId)}`, { method: "PUT", body, ...o }),

  // ── 참조 · 반출입 ─────────────────────────────────────────────────────────
  getRef: (ref: string, o?: Opt) => request<RefResolution>(`refs/${encodeURIComponent(ref)}`, o),
  exportJsonl: (since: number, o?: Opt) => requestText("export", { query: { since }, ...o }),
  /** 본문은 JSONL 원문이라 JSON.stringify 를 거치지 않는다. */
  importJsonl: async (jsonl: string, o?: Opt): Promise<ImportResult> =>
    JSON.parse(await requestText("import", { method: "POST", body: jsonl, ...o })) as ImportResult,
};

export type RiskApi = typeof riskApi;
