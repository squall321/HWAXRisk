// 앱 REST 얇은 클라이언트 — 계획 §8.2.3 을 1:1 로 감싼다. 모든 경로는 상대 'api/…' 라 /apps/hwax_risk/ 아래서 그대로 풀린다.
import type {
  AdapterList,
  ApiErrorBody,
  Brief,
  CharacterProfile,
  Coverage,
  CurationDecided,
  CurationDecision,
  CurationList,
  DiffCreate,
  DiffCreated,
  DiffDoc,
  DiffEvent,
  DiffSummary,
  DimDef,
  DimDefCreate,
  Requirement,
  RequirementCreate,
  RequirementList,
  Health,
  IfaceLedgerRow,
  ImportResult,
  IrEdge,
  IrNode,
  JobStateResponse,
  Me,
  Metrics,
  PanelList,
  PanelComplete,
  PanelCompleted,
  PanelTranscript,
  PortalPatSummary,
  Precedents,
  Project,
  ProjectCreate,
  ProjectDetail,
  ProjectList,
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
  Similar,
  SnapshotAccepted,
  SnapshotCallList,
  SnapshotCreate,
  SnapshotIr,
  SnapshotState,
  SourceCreate,
  SourceCreated,
  Taxonomy,
  TargetCreate,
  TargetCreated,
  TargetJobCreate,
  TargetJobCreated,
  VerdictUpdate,
  VocabIndex,
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
  putPortalPat: (pat: string | null, o?: Opt) =>
    request<PortalPatSummary>("me/portal-pat", { method: "PUT", body: { pat }, ...o }),
  getTaxonomy: (o?: Opt) => request<Taxonomy>("meta/taxonomy", o),
  getAdapters: (o?: Opt) => request<AdapterList>("meta/adapters", o),
  getVocab: (o?: Opt) => request<VocabIndex>("meta/vocab", o),
  getMetrics: (o?: Opt) => request<Metrics>("meta/metrics", o),

  // ── 과제 ──────────────────────────────────────────────────────────────────
  listProjects: (o?: Opt) => request<ProjectList>("projects", o),
  createProject: (body: ProjectCreate, o?: Opt) => request<Project>("projects", { method: "POST", body, ...o }),
  getProject: (id: string, o?: Opt) => request<ProjectDetail>(`projects/${encodeURIComponent(id)}`, o),
  addSource: (id: string, body: SourceCreate, o?: Opt) =>
    request<SourceCreated>(`projects/${encodeURIComponent(id)}/sources`, { method: "POST", body, ...o }),
  createSnapshot: (id: string, body: SnapshotCreate, o?: Opt) =>
    request<SnapshotAccepted>(`projects/${encodeURIComponent(id)}/snapshots`, { method: "POST", body, ...o }),
  listRequirements: (id: string, o?: Opt) =>
    request<RequirementList>(`projects/${encodeURIComponent(id)}/requirements`, o),
  upsertRequirements: (id: string, body: RequirementCreate[], o?: Opt) =>
    request<RequirementList>(`projects/${encodeURIComponent(id)}/requirements`, { method: "POST", body, ...o }),
  decideRequirement: (rid: string, body: { status: string; waive_reason?: string | null }, o?: Opt) =>
    request<Requirement>(`requirements/${encodeURIComponent(rid)}`, { method: "PUT", body, ...o }),
  inheritRequirements: (id: string, fromProjectId: string, o?: Opt) =>
    request<RequirementList>(`projects/${encodeURIComponent(id)}/requirements/inherit`, {
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
  getSnapshotNodes: (id: string, o?: Opt) =>
    request<IrNode[]>(`snapshots/${encodeURIComponent(id)}`, { query: { part: "nodes" }, ...o }),
  getSnapshotEdges: (id: string, o?: Opt) =>
    request<IrEdge[]>(`snapshots/${encodeURIComponent(id)}`, { query: { part: "edges" }, ...o }),
  getSnapshotCalls: (id: string, o?: Opt) =>
    request<SnapshotCallList>(`snapshots/${encodeURIComponent(id)}`, { query: { part: "calls" }, ...o }),
  getRuleHits: (id: string, o?: Opt) =>
    request<RuleHitList>(`snapshots/${encodeURIComponent(id)}/rule_hits`, o),

  // ── same-as · diff ────────────────────────────────────────────────────────
  getSameAs: (base: string, target: string, o?: Opt) => request<SameAs>("sameas", { query: { base, target }, ...o }),
  decideSameAs: (decisions: SameAsDecision[], o?: Opt) =>
    request<SameAsDecided>("sameas/decide", { method: "POST", body: decisions, ...o }),
  createDiff: (body: DiffCreate, o?: Opt) => request<DiffCreated>("diffs", { method: "POST", body, ...o }),
  getDiff: (id: string, o?: Opt) => request<DiffDoc>(`diffs/${encodeURIComponent(id)}`, { query: { part: "diff" }, ...o }),
  getDiffSummary: (id: string, o?: Opt) =>
    request<DiffSummary>(`diffs/${encodeURIComponent(id)}`, { query: { part: "summary" }, ...o }),
  getDiffEvents: (id: string, o?: Opt) =>
    request<DiffEvent[]>(`diffs/${encodeURIComponent(id)}`, { query: { part: "events" }, ...o }),
  getPrecedents: (diffId: string, o?: Opt) => request<Precedents>("precedents", { query: { diff_id: diffId }, ...o }),

  // ── 타깃 · 잡 ─────────────────────────────────────────────────────────────
  createTarget: (body: TargetCreate, o?: Opt) => request<TargetCreated>("targets", { method: "POST", body, ...o }),
  createTargetJob: (key: string, body: TargetJobCreate, o?: Opt) =>
    request<TargetJobCreated>(`targets/${encodeTargetKey(key)}/jobs`, { method: "POST", body, ...o }),
  pauseJob: (jobId: string, o?: Opt) =>
    request<JobStateResponse>(`jobs/${encodeURIComponent(jobId)}/pause`, { method: "POST", ...o }),
  resumeJob: (jobId: string, o?: Opt) =>
    request<JobStateResponse>(`jobs/${encodeURIComponent(jobId)}/resume`, { method: "POST", ...o }),
  cancelJob: (jobId: string, o?: Opt) =>
    request<JobStateResponse>(`jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST", ...o }),

  getCoverage: (key: string, o?: Opt) => request<Coverage>(`targets/${encodeTargetKey(key)}/coverage`, o),
  getSeats: (key: string, domain: string, o?: Opt) =>
    request<SeatList>(`targets/${encodeTargetKey(key)}/seats`, { query: { domain }, ...o }),
  getRegistry: (key: string, o?: Opt) => request<Registry>(`targets/${encodeTargetKey(key)}/registry`, o),
  getPanels: (key: string, o?: Opt) => request<PanelList>(`targets/${encodeTargetKey(key)}/panels`, o),
  getPanelTranscript: (panelId: string, o?: Opt) =>
    request<PanelTranscript>(`panels/${encodeURIComponent(panelId)}/transcript`, o),
  getBrief: (key: string, tier?: string, o?: Opt) =>
    request<Brief>(`targets/${encodeTargetKey(key)}/brief`, { query: { tier }, ...o }),
  putVerdict: (key: string, body: VerdictUpdate, o?: Opt) =>
    request<Registry>(`targets/${encodeTargetKey(key)}/verdict`, { method: "PUT", body, ...o }),
  putRegistryStatus: (cluster: string, body: RegistryStatusUpdate, o?: Opt) =>
    request<Registry>(`registry/${encodeURIComponent(cluster)}/status`, { method: "PUT", body, ...o }),
  completePanel: (panelId: string, body: PanelComplete, o?: Opt) =>
    request<PanelCompleted>(`panels/${encodeURIComponent(panelId)}/complete`, { method: "POST", body, ...o }),
  resyncTarget: (key: string, o?: Opt) =>
    request<ResyncQueued>(`targets/${encodeTargetKey(key)}/resync`, { method: "POST", ...o }),
  refreshRoster: (key: string, o?: Opt) =>
    request<RosterRefreshed>(`targets/${encodeTargetKey(key)}/refresh_roster`, { method: "POST", ...o }),

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
