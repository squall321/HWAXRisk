// REST 응답·화면 상태 어휘의 타입 정본 — 계획 §8.2.3 계약표와 §8.2.4 상태 어휘표를 그대로 옮긴다.

/** 서버가 그대로 흘려보내는 자유 JSON(스키마가 §2·§3 에 있고 화면은 원문만 보인다). */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

// ── 화면 상태 어휘(§8.2.4 표. 배지 문자열 = 저장 값) ────────────────────────────

export type SourceKind = "mcad" | "dyna" | "dyna_result" | "ecad";
export type SourceStatus = "unlinked" | "linked" | "unreachable";
/** 어댑터 레지스트리 상태(백엔드 adapters/registry.py). 소스 카드 상태와 다른 축이다. */
export type AdapterStatus = "planned" | "ready" | "contract_only" | "unavailable";

export type SnapshotJobState = "queued" | "running" | "done" | "failed";
export type BatchJobState =
  | "queued"
  | "running"
  | "paused"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed";

export type CoverageLevel = "C0" | "C1" | "C2" | "C2(closed)" | "C3";
export type CloseLevel = "C2" | "C3";
export type CoverageStatus =
  | "pending"
  | "assigned"
  | "running"
  | "done"
  | "done_weak"
  | "abstain"
  | "failed"
  | "skipped"
  | "deferred"
  | "carried";

export type PanelStatus = "planned" | "running" | "done" | "error";
export type PanelEngine = "web" | "mcp";
export type CallPath = "portal" | "agent_direct";
export type ToolMode = "tools" | "evidence_only";
export type Credential = "service" | "owner";

export type SyncState = "pending" | "done" | "unavailable";
export type ExternalSync = { ra: SyncState; adh: SyncState };

export type RegistryStatus = "open" | "verified" | "dismissed" | "mitigated" | "superseded";
/** 사람이 바꿀 수 있는 값만(§8.2.3 `PUT /registry/{cluster}/status`). superseded 는 코드가 붙인다. */
export type RegistryStatusInput = "verified" | "dismissed" | "mitigated";

export type Severity = "경미" | "중대" | "치명";
export type Judgement = "OK" | "WARNING" | "FAIL" | "undetermined";
export type Direction = "risk" | "improvement" | "neutral";
export type EvidenceGrade = "측정" | "문헌·규격" | "도구예측" | "경험칙";
export type Precedent = "in_range" | "out_of_range" | "none";
export type Verdict = "go" | "conditional" | "no-go" | "undetermined";

export type TargetKind = "snap" | "diff";
export type Tier = "A" | "B" | "C";

/** 성격 서술 facet 8종(순서 고정, §4.6). */
export type Facet =
  | "intent"
  | "constraint"
  | "anomaly"
  | "lineage"
  | "vulnerability"
  | "strength"
  | "tradeoff"
  | "unknown";
export const FACET_ORDER: readonly Facet[] = [
  "intent",
  "constraint",
  "anomaly",
  "lineage",
  "vulnerability",
  "strength",
  "tradeoff",
  "unknown",
];

export type CharacterStatementStatus = "seed" | "panel" | "confirmed";
export type SnapshotPart = "ir" | "state" | "nodes" | "edges" | "calls";
export type DiffPart = "diff" | "summary" | "events";

// ── 서버 오류 봉투 ─────────────────────────────────────────────────────────────

/** 백엔드 errors.AppError 가 내는 본문. */
export type ApiErrorBody = { error: { code: string; message: string } };

// ── /health · /me · /meta ─────────────────────────────────────────────────────

export type Health = { ok: boolean; app_version: string; schema_version: number };

export type PortalPatSummary = {
  registered: boolean;
  email: string | null;
  groups: string[];
  exp: number | null;
  /** 등록 시 강제된 PAT 스코프(계획 §8.2.7 — 읽기 전용 `['read']`). PAT 원문·암호문은 응답에 없다. */
  scopes?: string[];
  /** 포털이 폐기한 PAT 는 시각이 찍힌다 — 화면은 '이 PAT 는 폐기됨 — 재등록하세요' 를 띄운다. */
  revoked_at?: number | null;
  /** 폐기 대조 키(§8.2.7). 포털 토큰 페이지의 항목과 대조한다. */
  jti?: string | null;
  /** false 면 저장된 암호문을 현재 cred.key 로 풀 수 없다 — 화면엔 '등록됨' 인데 러너는 자격 (a) 로 강등된다. */
  decryptable?: boolean;
};

export type Me = {
  email: string | null;
  display_name: string | null;
  role: string | null;
  organization: string | null;
  anonymous: boolean;
  source: "bearer" | "cookie" | "none";
  portal_pat: PortalPatSummary | null;
  /** cred_key_present=false 면 PAT 등록이 422 `cred_key_absent` 로 거부된다(§8.2.7). */
  box: {
    hostname: string;
    secrets_valid: boolean;
    cred_key_present?: boolean;
    /** 앱이 포털을 부르는 주소. 틀리면 PAT 등록·패널 실행이 전부 실패한다(비밀이 아니다). */
    portal_base?: string;
  };
};

export type Adapter = { kind: string; app_key: string | null; status: string };

/** `GET /meta/adapters` 의 P1 확장형 — 소스 카드 선택지(§8.2.3 각주). */
export type AdapterChoice = { value: string; label: string; detail?: string | null };
export type AdapterEntry = Adapter & { tools_ok?: boolean; choices?: AdapterChoice[] };
export type AdapterList = { apps: AdapterEntry[] };

export type TaxonomyAxis = { code: string; label: string; [key: string]: JsonValue | undefined };
export type Taxonomy = { taxonomy_version: string; axes: Record<string, TaxonomyAxis[]> };

export type VocabAsset = { name: string; file: string; present: boolean; version: string | null };
export type VocabIndex = {
  asset_version: string;
  assets: VocabAsset[];
  /** 자유 태그를 올릴 수 있는 축 — 통제 값 목록이 있는 축만 서버가 준다(§7.7). */
  promotable_axes: string[];
};

export type MetricRow = {
  period: string;
  dimension: "expert" | "domain" | "mechanism" | "pattern" | "project" | "global";
  key: string;
  metric: string;
  /** 표본 부족(n < 지표별 임계)이면 서버가 값을 만들지 않고 null 을 낸다(§7.6). */
  value: number | null;
  n: number;
};
export type Metrics = { metrics: MetricRow[] };

// ── 과제(project) ─────────────────────────────────────────────────────────────

export type AdhScope = { team: string; group: string };

export type ProjectCreate = {
  code: string;
  name: string;
  stage?: string | null;
  predecessor_project_id?: string | null;
  adh_scope: AdhScope;
};

export type Project = {
  id: string;
  code: string;
  name: string;
  stage: string | null;
  predecessor_project_id: string | null;
  adh_scope: AdhScope | null;
  created_at: number;
  external_sync?: ExternalSync | null;
};

export type ProjectSource = {
  kind: SourceKind;
  app_key: string | null;
  status: SourceStatus;
  ref?: string | null;
  bridge_declared?: boolean | null;
  probe?: SourceProbe | null;
};

/** `GET /projects` 의 카드 1장. */
export type ProjectCard = {
  id: string;
  code: string;
  name: string;
  stage: string | null;
  sources: ProjectSource[];
  last_snapshot_at: number | null;
  open_targets: number;
  coverage_pct: number;
  level: CoverageLevel;
};

export type ProjectList = { projects: ProjectCard[] };

export type SnapshotHeader = {
  id: string;
  label: string | null;
  ir_hash: string;
  kinds: SourceKind[];
  captured_at: number;
  degraded: boolean;
  counts?: Record<string, number> | null;
};

export type TargetHeader = {
  target_key: string;
  kind: TargetKind;
  ref_id: string;
  level: CoverageLevel;
  verdict_final: Verdict | null;
  unseated_n: number;
  external_sync: ExternalSync;
  superseded_by: string | null;
};

export type JobHeader = {
  id: string;
  kind: string;
  state: SnapshotJobState | BatchJobState;
  progress: number;
  error?: string | null;
};

export type ProjectDetail = {
  project: Project;
  sources: ProjectSource[];
  snapshots: SnapshotHeader[];
  targets: TargetHeader[];
  jobs: JobHeader[];
  character_top_tags: string[];
};

export type SourceCreate = {
  kind: SourceKind;
  app_key: string;
  ref: string;
  bridge_declared?: boolean;
};

export type SourceProbe = { reachable: boolean; detail: string; capture_mode: string };
export type SourceCreated = { ok: boolean; probe: SourceProbe };

// ── 스냅샷 ────────────────────────────────────────────────────────────────────

export type SnapshotCreate = {
  label?: string;
  kinds: SourceKind[];
  report_ids?: string[];
  detect_result_file_id?: string;
};

/** 202 이면 `job_id` 만, 동일 `ir_hash` 재요청이면 200 으로 기존 스냅샷이 온다(§8.2.3 409 행). */
export type SnapshotAccepted = {
  job_id?: string;
  snapshot_id?: string;
  ir_hash?: string;
  gates?: Gate[];
  degraded?: boolean;
};

export type Gate = {
  id: string;
  pass: boolean;
  value: JsonValue;
  threshold: JsonValue;
  effect: string;
  message: string;
};

export type IrNode = {
  nid: string;
  name: string;
  ckey: string | null;
  dn: string | null;
  geom_fp: string | null;
  flags: string[];
  kind?: string | null;
  [key: string]: JsonValue | undefined;
};

export type IrEdge = {
  eid: string;
  kind: string;
  status: string;
  a: string;
  b: string;
  min_gap: number | null;
  penetration_depth: number | null;
  penetration_is_lower_bound?: boolean | null;
  [key: string]: JsonValue | undefined;
};

export type IrWarning = {
  severity: "CRITICAL" | "WARNING" | "INFO";
  code: string;
  message: string;
  ref: string | null;
  source_kind: string | null;
};

export type DimNamed = {
  name: string;
  kind: string;
  unit: string | null;
  value: number | null;
  ref: string | null;
};

/** `GET /snapshots/{id}?part=ir` — 봉투는 §2.2, 내부 구조는 화면이 해석하지 않고 표로만 그린다. */
export type SnapshotIr = {
  ir_version: string;
  snapshot_id: string;
  project_id: string;
  ir_hash: string;
  captured_at: number;
  kinds: SourceKind[];
  counts: Record<string, number>;
  missing: string[];
  nodes: IrNode[];
  edges: IrEdge[];
  dims_named: DimNamed[];
  rollups: JsonObject;
  results: JsonObject;
  warnings: IrWarning[];
};

export type Signal = { key: string; text: string; ref: string | null };
export type CharacterSeed = { tag: string; rule: string; cites: string[]; text: string };

/** `GET /snapshots/{id}?part=state`. */
export type SnapshotState = {
  state_version: string;
  snapshot_id: string;
  gates: Gate[];
  signals: Signal[];
  character_seed: CharacterSeed[];
  feature_vector: number[];
  summary_text: string | null;
};

export type SnapshotCall = {
  call_id: string;
  app_key: string;
  tool: string;
  args_digest: string | null;
  ok: boolean;
  called_at: number;
};

export type RuleHit = {
  rule: string;
  severity: Severity | string;
  pass: boolean;
  found: string;
  why_it_matters: string;
  fix_hint: string;
};

// ── 요구 규격(rr_requirements, plan §2.8b) ─────────────────────────────────────
export type RequirementKind = "dim_limit" | "scenario" | "standard";
export type RequirementStatus = "candidate" | "confirmed" | "waived";
export type RequirementCreate = {
  kind: RequirementKind;
  name: string;
  op?: string | null;
  value_json?: unknown;
  unit?: string | null;
  source_ref?: string | null;
};
export type Requirement = RequirementCreate & {
  id: string;
  project_id: string;
  status: RequirementStatus;
  waive_reason?: string | null;
  inherited_from?: string | null;
  decided_by?: string | null;
  decided_at?: number | null;
};
export type RequirementList = { project_id: string; requirements: Requirement[] };

export type DimDefCreate = { name: string; kind: string; unit: string; extractor: string };
export type DimDef = DimDefCreate & { id: string; project_id: string; vocab_status: string };

// ── same-as · 원장 ────────────────────────────────────────────────────────────

export type SameAsPair = {
  a: string;
  b: string;
  method: string;
  score: number;
  status: "candidate" | "confirmed" | "rejected" | "conflict";
};

export type SameAs = { pairs: SameAsPair[]; pending_n: number; G2: Gate };

export type SameAsPairDecision = {
  a: string;
  b: string;
  decision: "confirm" | "reject";
  scope: "intra" | "pair" | "global";
};

export type CkeyLedgerDecision = {
  decision: "merge_key" | "rename_key" | "confirm_key" | "unmerge_key";
  ckey_from?: string;
  ckey_into?: string;
  ckey?: string;
  display_name?: string;
};

/** 한 배열에 두 종류를 섞어 보낼 수 있다(§8.2.3). */
export type SameAsDecision = SameAsPairDecision | CkeyLedgerDecision;
export type SameAsDecided = { updated: number; G2: Gate };

export type IfaceLedgerRow = {
  pair_key: string;
  kind_override: string | null;
  status: string;
  note: string | null;
};

// ── diff ─────────────────────────────────────────────────────────────────────

export type DiffCreate = { base_snapshot_id: string; target_snapshot_id: string };

export type Comparability = { ok: boolean; excluded_reason: string | null; note: string | null };

export type DiffCreated = {
  diff_id: string;
  counts: Record<string, number>;
  comparability: Comparability;
};

/** 409 본문 — G6 fail 로 diff 생성이 막혔을 때 `ApiError.body` 에 실린다. */
export type DiffBlocked = { gates: Gate[] };

export type DiffLayer = "structural" | "parametric" | "semantic";

export type DiffItem = {
  cid: string;
  layer: DiffLayer;
  code: string;
  subject: string;
  before: JsonValue;
  after: JsonValue;
  delta: JsonValue;
  ref: string | null;
  [key: string]: JsonValue | undefined;
};

export type DiffDoc = {
  diff_version: string;
  diff_id: string;
  base_snapshot_id: string;
  target_snapshot_id: string;
  comparability: Comparability;
  items: DiffItem[];
  counts: Record<string, number>;
};

/** `?part=summary` — `summary_text` 는 코드가 만든 원문이라 화면이 다시 쓰지 않는다. */
export type DiffSummary = { diff_id: string; summary_text: string; lines: string[] };

export type DiffEvent = {
  cid: string;
  code: string;
  text: string;
  refs: string[];
  [key: string]: JsonValue | undefined;
};

export type Precedents = {
  diff_id: string;
  rows: Array<{
    cluster_key: string;
    n: number;
    in_range: number;
    out_of_range: number;
    [key: string]: JsonValue;
  }>;
};

// ── 타깃 · 잡 ────────────────────────────────────────────────────────────────

export type TargetCreate = { kind: TargetKind; ref_id: string; consent: true };

export type TierPlanRow = { tier: Tier; panels: number; seats: number };

export type TargetCreated = {
  target_key: string;
  roster_size: number;
  deferred: number;
  tier_plan: TierPlanRow[];
  cost_estimate: { llm_calls: number; gpu_hours: number | null };
};

export type TargetJobCreate = {
  tier: Tier;
  concurrency?: number;
  modifiers?: string[];
  user_memo?: string;
  consent?: boolean;
};

export type TargetJobCreated = {
  job_id: string;
  panels_planned: number;
  llm_calls_estimate: number;
  credential: Credential;
};

export type JobStateResponse = { state: BatchJobState };

export type CoverageJob = {
  id: string;
  state: BatchJobState;
  reason: string | null;
  progress: number;
  error: string | null;
  daily_remaining: number;
} | null;

export type Coverage = {
  job: CoverageJob;
  roster_size: number;
  /** 도메인 코드 → 커버리지 상태별 좌석 수. */
  by_domain: Record<string, Partial<Record<CoverageStatus, number>>>;
  /** 전체 합계(도메인을 가로지른 상태별 수). */
  by_status: Partial<Record<CoverageStatus, number>>;
  strong: number;
  unseated_n: number;
  level: CoverageLevel;
  close_level: CloseLevel;
};

export type Seat = {
  agent_key: string;
  domain: string;
  tier: string | null;
  origin: "primary" | "counter" | null;
  status: CoverageStatus;
  reason: string | null;
  panel_id: string | null;
  opinion_id: string | null;
  model: string | null;
  /** 'human' 이면 사람이 옮긴 상태다(§6.8.2) — 셀 툴팁의 decided_by 와 짝. */
  status_source: "code" | "human";
  decided_by: string | null;
  decided_at: number | null;
  started_at: number | null;
  finished_at: number | null;
};

export type SeatList = { target_key: string; domain: string | null; seats: Seat[] };

// ── 등록부 · verdict ─────────────────────────────────────────────────────────

export type Cite = { ref: string; quote: string; dangling?: boolean };

export type RegistryRow = {
  cluster_key: string;
  direction: Direction;
  domain: string;
  mechanism: string;
  mechanism_detail: string;
  change_kind: string;
  subject: string;
  severity: Severity;
  judgement: Judgement;
  evidence_grade: EvidenceGrade;
  precedent: Precedent;
  support: number;
  contested: number;
  status: RegistryStatus;
  claim: string;
  cites: Cite[];
  priority: number;
};

export type VerdictCandidate = {
  verdict: Verdict;
  reason: string;
  conditions: string[];
};

export type Registry = {
  target_key: string;
  rows: RegistryRow[];
  /** limit 를 넘겨 잘렸는지(REST 조회는 limit 를 주지 않아 늘 false 다 — MCP 경로가 쓴다). */
  truncated: boolean;
  verdict_candidate: VerdictCandidate | null;
  verdict_final: Verdict | null;
};

export type VerdictUpdate = { verdict: Verdict; note: string };
export type RegistryStatusUpdate = {
  status: RegistryStatusInput;
  evidence_ref?: string;
  note?: string;
};

// ── 패널 ─────────────────────────────────────────────────────────────────────

export type PanelQuality = {
  flag: string[];
  tool_calls_n: number | null;
  tool_calls_ok: number | null;
  used_tool: boolean | null;
  attribution_rate: number | null;
  credential?: Credential;
};

/** 어떤 LLM 이 점검했는지 — `rr_panels.model_json`(§6.11 D6). */
export type PanelModel = {
  model: string;
  captured: "caller_reported" | "runner_observed" | "unknown";
};

export type Panel = {
  panel_id: string;
  panel_no: number;
  target_key: string;
  tier: Tier;
  engine: PanelEngine;
  call_path: CallPath;
  tool_mode: ToolMode;
  status: PanelStatus;
  conv_id: string | null;
  report_id: string | null;
  seats: string[];
  quality: PanelQuality;
  model: PanelModel | null;
  started_at: number | null;
  finished_at: number | null;
};

export type SeatTurn = {
  seat: string;
  round: number;
  say_excerpt: string;
  position?: string | null;
  stance?: string | null;
};

/** `PanelTranscript` 가 그리는 것 — 앱 DB 의 좌석 발언·결정문·risk_spec(포털 conv_store 를 읽지 않는다). */
export type PanelTranscript = {
  panel_id: string;
  decision_text: string;
  turns: SeatTurn[];
  risk_spec: JsonObject | null;
};

export type PanelComplete = {
  engine: PanelEngine;
  conv_id?: string;
  decision_text: string;
  turns: SeatTurn[];
  report_id?: string;
  events?: Array<{
    kind: "status" | "evidence" | "personas";
    step?: string;
    tool?: string;
    source?: string;
    personas?: string[];
  }>;
  model?: string;
};

export type PanelCompleted = {
  parsed: boolean;
  findings_n: number;
  coverage_updated: number;
  attribution_rate: number | null;
  events_truncated?: boolean;
};

// ── 브리프(RecallPreview) ────────────────────────────────────────────────────

export type EvidenceItem = { source: string; tool: string; args: string; result: string };

export type BriefPanel = {
  panel_id: string;
  seats_json: JsonObject;
  delib_opts: JsonObject;
  /** REST `GET /targets/{key}/brief` 만 싣는 1건짜리 열쇠 — L2 오케스트레이터가 MCP `risk_get_brief` 에 그대로 넘긴다(§8.2.5). */
  brief_token?: string;
};

export type Brief = {
  panels: BriefPanel[];
  /** E0~E9 슬롯 → 항목들. 화면은 제외만 가능하고 추가할 수 없다(헌법, §8.2.4). */
  evidence: Record<string, EvidenceItem[]>;
  budget: { bytes: number; dropped: number };
};

// ── 성격 프로파일 · 유사 과제 ───────────────────────────────────────────────

export type CharacterStatement = {
  id: string;
  facet: Facet;
  tag: string;
  statement: string;
  polarity: string;
  cites: Cite[];
  by: string[];
  tags: string[];
  status: CharacterStatementStatus;
  needs_review?: number;
  first_target_key?: string | null;
  updated_at?: number;
  support_panels: number;
  support_targets: number;
};

/** 서버는 층(seed · panel · confirmed · superseded)으로 나눠 준다 — 섞지 않는다(§4.6.4). */
export type CharacterLayers = Record<"seed" | "panel" | "confirmed" | "superseded", CharacterStatement[]>;

export type CharacterProfile = {
  project_id: string;
  character_status: string | null;
  layers: CharacterLayers;
};

// 유사 과제 — 회수 경로 4종을 섞지 않는다(§5.7·§8.2.4). 경로마다 항목 모양이 다르다.
export type LineageEntry = {
  project_id: string;
  code: string | null;
  hops: number;
  relation: "predecessor" | "successor";
};
export type VectorNeighbour = {
  project_id: string;
  snapshot_id: string;
  cosine: number;
  top_features: JsonValue;
  rank: number;
};
export type TextHit = { record_id: string; project_id: string; rank: number; section_id: string };
export type SubjectHit = {
  subject_key: string;
  n_registry: number;
  n_verified: number;
  project_ids: string[];
  path: JsonValue;
};
/** 경로 가중 합산 — 어느 경로로 걸렸는지 `paths` 에 남는다(섞은 것이 아니라 병기다). */
export type MergedHit = { project_id: string; score: number; paths: string[] };

export type Similar = {
  lineage: LineageEntry[];
  vector: VectorNeighbour[];
  text: TextHit[];
  subject: SubjectHit[];
  merged: MergedHit[];
  corpus_n: number;
  /** 그 경로가 비었다면 왜 비었는지(코퍼스 부족·external_sync 불통 등). */
  reason: { vector: string | null; text: string | null };
};

// ── 참조 해석 · 동기화 · 반출입 ─────────────────────────────────────────────

export type RefResolution = {
  ref_type: string;
  resolved: boolean;
  payload: JsonValue;
};

export type ResyncQueued = { ra: SyncState; adh: SyncState };
export type RosterRefreshed = { added_pending: number };

export type ImportResult = {
  inserted: number;
  merged: number;
  skipped: number;
  conflicts: Array<{ table: string; key: string; local: JsonValue; incoming: JsonValue }>;
};

// ── 큐레이션 큐(plan §7.7) ──────────────────────────────────────────────────

/** DDL 이 허용하는 6종. 결정 어휘는 kind 마다 다르다. */
export type CurationKind =
  | "unclassified_code"
  | "pattern_candidate"
  | "label_match"
  | "x_tag_promote"
  | "suspect_text"
  | "cluster_merge";

export type CurationStatus = "open" | "done" | "rejected";

export type CurationRow = {
  id: string;
  kind: CurationKind;
  /** kind 마다 모양이 다르다 — 화면은 아는 키만 꺼내 보이고 나머지는 원문으로 접는다. */
  payload: JsonObject;
  status: CurationStatus;
  decision: JsonObject;
  decided_by: string | null;
  decided_at: number | null;
  created_at: number;
};

export type CurationList = { rows: CurationRow[] };

export type CurationDecision = {
  decision: string;
  reason?: string | null;
  /** 결정에 딸린 인자 — 승격의 `axis`, 미분류 코드의 `mechanism_detail` 등. */
  payload?: JsonObject | null;
};

export type CurationDecided = {
  status: CurationStatus;
  decision_json: JsonObject;
  /** 적용 결과. 적용 함수가 없는 결정(단순 기각·라벨 확정)은 빈 객체다. */
  applied: JsonObject;
};

/** `GET /snapshots/{id}?part=calls` 봉투. */
export type SnapshotCallList = { snapshot_id: string; calls: SnapshotCall[] };
/** `GET /snapshots/{id}/rule_hits` 봉투. */
export type RuleHitList = { snapshot_id: string; rule_version: string | null; rule_hits: RuleHit[] };
/** `GET /targets/{key}/panels` 봉투. */
export type PanelList = { target_key: string; panels: Panel[] };

// ── 사람 finding · 사전 편집(plan §4.3.1 · §2.7.1) ──────────────────────────

/** `POST /targets/{key}/findings` 본문. 인용이 0건이면 서버가 422 다. */
export type HumanFindingCreate = {
  direction: Direction;
  domain?: string | null;
  mechanism: string;
  mechanism_detail?: string | null;
  subject_key?: string | null;
  subject_names?: string[];
  severity?: Severity | null;
  judgement?: Judgement | null;
  trigger_condition?: string | null;
  claim: string;
  warrant?: string | null;
  /** §0.2.1 문법의 참조. `cites:[]` 는 422 라 폼이 최소 1건을 강제한다. */
  cites: Array<{ ref: string; quote?: string }>;
  requirement_ref?: string | null;
};

export type HumanFindingCreated = {
  finding_id: string;
  claim_uid: string;
  cluster_key: string;
  origin: "human";
};

/** 동의어 추가는 마이너, 삭제는 메이저 승급이다(§2.7.1). */
export type VocabOp = "add" | "remove";
export type VocabBump = {
  vocab_version: string;
  bump: "minor" | "major";
  synonyms: Record<string, string[]>;
  stop_tokens: string[];
  /** major 승급이면 true — 화면은 `recompute_part_keys.py` 안내 배너를 띄운다(§2.7.1). */
  recompute_required: boolean;
};

// ── 목록 3종(정본 §8.2.4 RiskHomePage 탭) ────────────────────────────────────
// 목록은 고르기 위한 것이라 본문(diff_json·summary_text)이 없다 — 전문은 항목 경로가 준다.

export type DiffListRow = {
  id: string;
  base_snapshot_id: string;
  target_snapshot_id: string;
  base_project_id: string;
  target_project_id: string;
  pair_kind: "same_project_revision" | "cross_project" | null;
  diff_version: string;
  summary_status: "ok" | "lint_failed" | null;
  stats: Record<string, unknown>;
  comparability: Record<string, unknown>;
  /** 게이트가 막았나 — 이 diff 를 믿어도 되는지의 판정이다(§2.12). */
  blocked: boolean;
  gates_failed: string[];
  diff_hash: string | null;
  created_at: number | null;
};

export type TargetListRow = {
  target_key: string;
  kind: "snap" | "diff";
  ref_id: string;
  project_id: string;
  level: string;
  close_level: string | null;
  verdict_candidate: string | null;
  verdict_final: string | null;
  /** §4.8 로 닫힌 타깃 — 기본 목록에는 안 나온다. */
  superseded_by: string | null;
  report_ids: string[];
  roster_size: number;
  coverage_pct: number | null;
  created_at: number | null;
  updated_at: number | null;
};

export type ReportListRow = {
  report_id: string;
  /** `rpt:<id>` — 앱은 보고서를 소유하지 않고 이 포인터만 갖는다(§5.3). */
  ref: string;
  target_key: string;
  kind: "snap" | "diff";
  project_id: string;
  level: string;
  verdict_final: string | null;
  ra_state: string | null;
  updated_at: number | null;
};

export type Paged<K extends string, T> = { total: number; limit: number; offset: number } & {
  [P in K]: T[];
};
